"""踏んだ事実を、利用者の環境に 1 件 1 行で残す記録器（設計は docs/feedback/intake.md の段階 1・2）。ループの中身を知らない。

来歴（プラグインの名前と版・取れればコミット・run の番号と周）はここだけが組む。呼ぶ所は 4 つ:
loop.py の最上段（非 0 で終わった呼び出し）・launch の ok でない行・手の口（loop.py intake）・報告の頭の 1 行
（accept_output が save_text_as の本文を保存するとき）。

**どう失敗しても呼び元を止めない。** 残す処理は失敗の口の中で走るので、ここで上がった例外は元の終了コードを
書き換える。だから engine のツール（read_json・die・Board・util.git）を呼ばない——die と read_json は SystemExit を
上げ（except Exception を素通りする）、util.git は対象のリポジトリで走るのでプラグインのコミットを取り違える。
使うのは filelock の錠だけ（例外を上げず、取れるまで待つ——持ち主が死ねば OS が外す）。

**溜まる物の持ち主は loop を回す人。** 行は CAP で切り（古い行から捨てる）、まだ作者へ手渡していない行の数は init と status が
毎回出す（backlog。ログに書くだけでは誰も読まない——docs/standards/breakage-detection.md の決まり 1・5）。
"""
import collections
import datetime
import functools
import hashlib
import json
import os
import pathlib
import platform
import re
import subprocess
import sys
import urllib.request

from . import filelock

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = "intake.jsonl"
CURSOR = "intake.cursor"      # 「手渡した（書き出した・送った・既読にした）所 捨てた行の数」。どちらも書いた行の通し番号で数える
LOCK = "intake.lock"          # 足す・切る・手渡すを不可分にする錠（並ぶ launch が同じ秒に足す）
CAP = 1000                    # 残す行の上限。超えたら古い行から捨てる（実測は 1 か月で 30 行ほど）
LEDGER = "installed_plugins.json"   # Claude Code が入れた plugin の台帳（<plugins>/ の直下）
SCOPES = ("local", "project", "user")   # 台帳の行の scope。狭い順——狭い scope の行が先に効く
CONFIG = "intake-config.json"
CLIP = 500                    # 人が書く 1 行と標準エラーの頭を切る長さ
DETAIL_ENV = "GRAPHLOOPS_INTAKE_STDERR"   # 1 のときだけ標準エラーの頭を残す（既定は構造化したフィールドだけ）


def quiet(fn):
    """呼び元を止めない握り。例外は捨てて None を返す（KeyboardInterrupt だけは通す）。引数を組む処理ごと中に入れるため、
    記録器へ渡す値は呼ぶ前に組まず、この握りを付けた関数の中で組む。"""
    @functools.wraps(fn)
    def guarded(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except KeyboardInterrupt:
            raise
        # 黙らせるのは決めた事（記録器は呼び元の終了コードと出力を変えない）。Exception でなく BaseException なのは、盤面を読む
        # util.die が SystemExit を上げるため——壊れた盤面の下で記録器が SystemExit を通すと、exit 1 の拒否が 2 に化ける
        # （test_intake の test_unreadable_board_under_dir_keeps_reject_exit）
        except BaseException:
            return None
    return guarded


def plugin_meta(root=PLUGIN_ROOT):
    """(名前, 版)。plugin.json が読めなければ空文字——engine_changed と来歴が同じ読み手を使う。"""
    try:
        d = json.loads((pathlib.Path(root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        return str(d.get("name") or ""), str(d.get("version") or "")
    except (OSError, ValueError, AttributeError):
        return "", ""


def _installed(root):
    """Claude Code が入れた置き場 <plugins>/cache/<marketplace>/<plugin>/<version> なら (plugins, marketplace, plugin)。"""
    p = pathlib.Path(root).resolve()
    if len(p.parents) >= 4 and p.parents[2].name == "cache":
        return p.parents[3], p.parents[1].name, p.parents[0].name
    return None


def version_key(name):
    """版の名前（数値でない部分が混ざってもよい）を大小で並べられる形。並べ方は SemVer 2.0.0 §11 の優先順位——+ 以降（build）は見ず、
    - 以降のプレリリースは同じ本体の正式版より下、識別子は数字どうしなら数で、ほかは字で比べて数字を字より下に置き、前が全部等しければ
    短い方が下。版を並べる所（scripts/quality-ledger.py）は全部これを引く。入っている版を選ぶ所はこれでなく台帳を読む（installed_roots）"""
    core, _, pre = name.split("+", 1)[0].partition("-")
    ids = lambda s: [(0, int(x)) if x.isdigit() else (1, x) for x in s.split(".")]   # noqa: E731
    return ids(core), ((0, ids(pre)) if pre else (1, []))


def _main_tree(top):
    """top が linked worktree（.git がファイル）なら、主の作業ツリー（共有の .git の親。共有の .git の名前が .git のときだけ——
    `git rev-parse --git-common-dir` の親と同じ）。ほか・読めない回は None。git は呼ばない: .git のファイルの `gitdir:` と、
    その中の commondir（共有の .git への道）を読む（git-worktree の文書の DETAILS）"""
    g = top / ".git"
    if not g.is_file():
        return None
    try:
        line = g.read_text(encoding="utf-8").strip()
        if not line.startswith("gitdir:"):
            return None
        gd = (top / line[len("gitdir:"):].strip()).resolve()
        common = (gd / (gd / "commondir").read_text(encoding="utf-8").strip()).resolve()
    except (OSError, ValueError):
        return None
    return common.parent if common.name == ".git" else None


def _here(cwd=None):
    """台帳の project・local の行が効く場所: 今の作業フォルダと、それを含む git の作業ツリーのルートと、linked worktree なら
    主の作業ツリー（Claude Code は主の clone で入れた行の projectPath に主の clone を書く）と、CLAUDE_PROJECT_DIR
    （util.git は呼ばない。.git を上へたどる）"""
    cur = pathlib.Path(cwd or os.getcwd()).resolve()
    out = {cur}
    top = next((q for q in (cur, *cur.parents) if (q / ".git").exists()), None)
    if top:
        out.add(top)
        main = _main_tree(top)
        if main:
            out.add(main)
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        out.add(pathlib.Path(os.environ["CLAUDE_PROJECT_DIR"]).resolve())
    return out


def installed_roots(plugins, plugin, cwd=None):
    """Claude Code の台帳（<plugins>/installed_plugins.json）の installPath のうち、今の場で効く plugin の置き場を出所（marketplace）ごとに 1 つ。
    返すのは ({出所: 置き場}, 使えない理由の一覧)。

    版をフォルダの名前で選ばない——名前の大小では commit の名前のフォルダ（git の出所の版）が版の番号より上に来て、
    .orphaned_at の付いた外れた版（Claude Code が入れ替えた後に残す古い置き場）も拾う。効く行は scope が user の行と、
    project・local で projectPath が今の場（_here）に当たる行で、狭い scope の行を取る。取った行の installPath が無い・
    .orphaned_at が付いていれば、広い scope の行に倒さずに理由に残す（黙って別の版を使わない）。台帳が無い・読めない・
    知らない scope の行も理由に残す。validator.find_plugin_path（役の定義・検証器）と install_drift（動いている版）が引く"""
    f = pathlib.Path(plugins) / LEDGER
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, [f"台帳 {f} が無い"]
    except (OSError, ValueError) as e:
        return {}, [f"台帳 {f} が読めない（{e}）"]
    here, roots, why = _here(cwd), {}, []
    for key, rows in ((d.get("plugins") if isinstance(d, dict) else None) or {}).items():
        name, _, market = key.rpartition("@")
        if name != plugin:
            continue
        live = []
        for r in rows if isinstance(rows, list) else []:
            scope = r.get("scope") if isinstance(r, dict) else None
            if scope not in SCOPES:
                why.append(f"台帳の {key} に知らない scope {scope!r} の行がある（{f}）——この行は使わない")
            elif scope == "user" or (r.get("projectPath") and pathlib.Path(r["projectPath"]).resolve() in here):
                live.append(r)
        if not live:
            continue
        r = min(live, key=lambda r: SCOPES.index(r["scope"]))
        p = pathlib.Path(r.get("installPath") or "")
        if not r.get("installPath") or not p.is_dir():
            why.append(f"台帳の {key}（scope {r['scope']}）の installPath {p} が無い")
        elif (p / ".orphaned_at").exists():
            why.append(f"台帳の {key}（scope {r['scope']}）の installPath {p} に .orphaned_at が付いている（外れた版）")
        else:
            roots[market] = p.resolve()
    return roots, why


def noted(fn):
    """止めずに知らせる関数の握り（init・status が出す知らせの材料を組む所）。例外は None にするが、黙らずに関数の名前と例外の型を
    標準エラーに 1 行出す——quiet のように捨てると、知らせが出なくなったことに誰も気づかない（docs/standards/breakage-detection.md の決まり 1）"""
    @functools.wraps(fn)
    def guarded(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:   # noqa: BLE001 — 何で落ちても知らせの材料が無いだけで、呼び元は止めない
            try:
                print(f"注意: intake.{fn.__name__} が {type(e).__name__} で落ちた——この知らせは今回出せていない（止めずに続ける）",
                      file=sys.stderr)
            except Exception:   # noqa: BLE001 — 標準エラーが閉じていても止めない
                pass
            return None
    return guarded


@noted
def install_drift(root=PLUGIN_ROOT, cwd=None):
    """root が Claude Code の入れた置き場なら、台帳がこの場で効かせる同じ plugin の置き場と比べる。違えば
    {"installed": 台帳の置き場（決まらなければ None）, "version": その版, "why": 決まらない理由}。同じ・checkout から走る回
    （--plugin-dir を含む）・読めない回は None——止めずに知らせるだけの材料（init_notices が出す）"""
    inst = _installed(root)
    if not inst:
        return None
    plugins, market, name = inst
    roots, why = installed_roots(plugins, name, cwd)
    got = roots.get(market)
    if got == pathlib.Path(root).resolve():
        return None
    return {"installed": str(got) if got else None, "version": plugin_meta(got)[1] if got else "",
            "why": "" if got else ("; ".join(why) or f"台帳に {name}@{market} の効く行が無い")}


def data_dir(given=None):
    """残す置き場。明示の値 → 環境変数 CLAUDE_PLUGIN_DATA → 入れた置き場から Claude Code と同じ規則で導く。

    CLAUDE_PLUGIN_DATA は Bash で走るコマンドの環境に入らない（手順書の本文でだけ置き換わる）ので、導く道が要る。
    置き換わらなかった `${…}` の字面と空は無視する。どれにも当たらなければ None で、書かない——checkout から直に
    走らせたテストや開発の run（--plugin-dir で読んだ回も）は、利用者の置き場を汚さない。"""
    for v in (given, os.environ.get("CLAUDE_PLUGIN_DATA")):
        if v and "${" not in v:
            return pathlib.Path(v)
    inst = _installed(PLUGIN_ROOT)
    if inst:
        plugins, market, name = inst
        return plugins / "data" / re.sub(r"[^A-Za-z0-9_-]", "-", f"{name}-{market}")
    return None


def _commit(root):
    inst = _installed(root)
    if inst:   # 入れた置き場は git の作業ツリーではない——Claude Code の台帳が入れた commit を持つ
        d = json.loads((inst[0] / "installed_plugins.json").read_text(encoding="utf-8"))
        for rows in (d.get("plugins") or {}).values():
            for r in rows or []:
                if r.get("gitCommitSha") and pathlib.Path(r.get("installPath") or "/").resolve() == pathlib.Path(root).resolve():
                    return r["gitCommitSha"][:12]
        return None
    r = subprocess.run(["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def read_state(run_dir):
    """盤面の state.json を素の open で読む（読めなければ None）。"""
    try:
        return json.loads((pathlib.Path(run_dir) / "state.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def provenance(state=None):
    """来歴のフィールド。盤面があれば、その周を回した engine（state.engine）の置き場と版を使う——記録の engine_changes と同じ値。"""
    state = state if isinstance(state, dict) else {}
    eng = state.get("engine") if isinstance(state.get("engine"), dict) else {}
    root = pathlib.Path(eng["root"]) if eng.get("root") and pathlib.Path(eng["root"]).is_dir() else PLUGIN_ROOT
    name, ver = plugin_meta(root)
    out = {"plugin": name or root.name, "version": eng.get("version") or ver}
    try:
        c = _commit(root)
    except Exception:
        c = None
    if c:
        out["commit"] = c
    out["os"] = f"{platform.system().lower()} {platform.release()}"
    out["python"] = platform.python_version()
    run = {k: state[k] for k in ("loop_name", "run_id", "round", "graph_sha") if state.get(k) is not None}
    if run:
        out["run"] = run
    return out


@quiet
def stamp_line(state):
    """報告の頭に刻む 1 行（読めなければ None——報告は刻まずに保存する）。"""
    p = provenance(state)
    r = p.get("run", {})
    head = f"{p['plugin']} {p['version'] or '?'}" + (f" ({p['commit']})" if p.get("commit") else "")
    return " / ".join([head, f"{r.get('loop_name', '?')} run {r.get('run_id', '?')}",
                       f"round {r.get('round', '?')}", f"graph {r.get('graph_sha', '?')}"])


def where_of(argv):
    """揺れない呼び口: `loop.py <サブコマンド>`（--node があればノードの id。[ ] の項目の鍵と #k の試行の後置は落とす
    ——鍵にはパスが混ざり、後置は同じノードを試行ごとに別の問題へ割る）。"""
    sub = next((x for x in argv if not x.startswith("-")), "?")
    where = f"loop.py {sub if re.fullmatch(r'[a-z][a-z-]*', sub) else '?'}"   # 打ち間違いの語（パスかもしれない）は残さない
    node = re.sub(r"#\d+$", "", (flag(argv, "--node") or "").split("[", 1)[0])
    if re.fullmatch(r"[\w.-]+", node):
        where += " --node " + node
    return where


def flag(argv, name):
    for i, x in enumerate(argv):
        if x == name and i + 1 < len(argv):
            return argv[i + 1]
        if x.startswith(name + "="):
            return x.split("=", 1)[1]
    return None


def raised_in(tb):
    """例外を上げた engine の関数（`<module>.<関数>`）。ユーティリティ（util.py の die・read_json）の呼び元まで戻る
    ——die は exit 2 の道の大半が通るので、die の名前では別々の失敗が 1 つの鍵にまとまる。"""
    found = None
    while tb is not None:
        f = pathlib.Path(tb.tb_frame.f_code.co_filename)
        try:
            inside = f.resolve().is_relative_to(PLUGIN_ROOT) and f.name != "util.py"
        except OSError:
            inside = False
        if inside:
            found = f"{f.stem}.{tb.tb_frame.f_code.co_name}"
        tb = tb.tb_next
    return found


def key_of(row):
    """同じ問題を数える鍵。版と run を入れない（版をまたいで続く同じ問題を割らない。Sentry の既定の組み分けと同じ向き）。"""
    parts = [row.get("plugin"), row.get("kind"), row.get("where"), row.get("exit"), row.get("exc"), row.get("func")]
    return hashlib.sha1("\0".join("" if x is None else str(x) for x in parts).encode("utf-8")).hexdigest()[:12]


@quiet
def record(kind, where, *, exit=None, exc=None, func=None, what=None, state=None, detail=None, given_dir=None):
    """1 件 1 行を追記する。書いた置き場を返し、どう失敗しても None を返すだけ（何も出さない）。

    kind が auto の行だけが鍵を持つ——手の行は呼び口が決まった値なので、鍵にすると別々の問題が 1 つに数えられる。"""
    d = data_dir(given_dir)
    if d is None:
        return None
    row = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "kind": kind,
           **provenance(state), "where": where}
    for k, v in (("exit", exit), ("exc", exc), ("func", func)):
        if v is not None:
            row[k] = v
    if what:
        row["what"] = str(what)[:CLIP]
    if detail and os.environ.get(DETAIL_ENV) == "1":
        row["stderr"] = str(detail)[:CLIP]
    if kind == "auto":
        row["key"] = key_of(row)
    d.mkdir(parents=True, exist_ok=True)
    with filelock.BoardLock(d / LOCK):
        with open(d / LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        _trim(d)
    return d / LOG


def _trim(d):
    """CAP を超えた分を古い行から捨て、捨てた数を手渡しの印に足す（錠の中で呼ぶ）。捨てた行がまだ手渡していない物なら、
    backlog の lost に出る——黙って消さない"""
    lines = [x for x in (d / LOG).read_text(encoding="utf-8").splitlines(keepends=True) if x.strip()]
    over = len(lines) - CAP
    if over <= 0:
        return
    tmp = d / (LOG + ".tmp")
    tmp.write_text("".join(lines[over:]), encoding="utf-8")
    os.replace(tmp, d / LOG)
    done, dropped = _cursor(d)
    _write_cursor(d, done, dropped + over)


@quiet
def failed(argv, code, exc, tb=None, detail=None):
    """loop.py が非 0 で終わるときの 1 行（最上段の例外口が呼ぶ）。"""
    d, where = flag(argv, "--dir"), where_of(argv)
    # --data-dir は手の口の旗——ほかのサブコマンドに打ち間違いで付いた値（相対なら作業ツリーの中）には書かない
    given = flag(argv, "--data-dir") if where == "loop.py intake" else None
    return record("auto", where, exit=code if isinstance(code, int) else 1, exc=type(exc).__name__,
                  func=raised_in(tb), state=read_state(d) if d else None, detail=detail, given_dir=given)


# ---- 手の口（loop.py intake）----------------------------------------------------------------------------

def _row(x):
    """1 行を読む。壊れた行は読めない印の行にする——飛ばすと手渡しの印（行の通し番号）がずれ、落とすと書き出し・知らせが全部止まる"""
    try:
        r = json.loads(x)
        return r if isinstance(r, dict) else {"kind": "unreadable", "line": x[:CLIP]}
    except ValueError:
        return {"kind": "unreadable", "line": x[:CLIP]}


def _rows(d):
    try:
        return [_row(x) for x in (d / LOG).read_text(encoding="utf-8").splitlines() if x.strip()]
    except FileNotFoundError:
        return []


def _cursor(d):
    """(手渡した所, 捨てた行の数)。前の版の 1 つの数だけの印は、捨てた行が 0 として読む"""
    try:
        nums = [int(x) for x in (d / CURSOR).read_text(encoding="utf-8").split()][:2]
    except (FileNotFoundError, ValueError):
        return 0, 0
    nums += [0] * (2 - len(nums))
    return nums[0], nums[1]


def _write_cursor(d, done, dropped):
    tmp = d / (CURSOR + ".tmp")
    tmp.write_text(f"{done} {dropped}", encoding="utf-8")
    os.replace(tmp, d / CURSOR)


def pending(d, everything=False, with_detail=False):
    """まだ手渡していない行（everything なら残っている全部）と、書いた行の通し番号の終わり（handed に渡す）。既定は標準エラーのフィールドを落とす。
    行と印は錠の中で一緒に読む——間に _trim が切ると、捨てた数が古いまま行だけ減り、通し番号の終わりが実際より小さく・まだ見ていない行の
    位置がずれる。錠を呼ぶたびに新しく作るので入れ子にしない（同じプロセスでも 2 本目の flock は自分を待って止まる）——錠を持った所は _unlocked を呼ぶ"""
    with filelock.BoardLock(d / LOCK):
        return _pending_unlocked(d, everything, with_detail)[:2]


def _pending_unlocked(d, everything=False, with_detail=False):
    """pending の中身（錠の中で呼ぶ）。返すのは (行, 通し番号の終わり, 手渡した所, 捨てた行の数)"""
    rows = _rows(d)
    done, dropped = _cursor(d)
    out = rows if everything else rows[max(0, done - dropped):]
    if not with_detail:
        out = [{k: v for k, v in r.items() if k != "stderr"} for r in out]
    return out, dropped + len(rows), done, dropped


def handed(d, upto):
    """手渡した所を upto（pending が返した通し番号）まで進める。捨てた数は錠の中で読み直す——読んだ後に _trim が切っても印がずれない"""
    with filelock.BoardLock(d / LOCK):
        _write_cursor(d, upto, _cursor(d)[1])


@noted
def backlog(given=None):
    """まだ作者へ手渡していない行のまとめ（init と status が毎回出す知らせの材料）。置き場が決まらない・手渡していない行が無ければ None。
    返すのは {dir, file, pending, oldest, lost, top}: lost は手渡す前に CAP で捨てた数、top は（呼び口, 例外か種類）ごとの数の多い順の 3 つ
    ——どの失敗が溜まったかを、ファイルを開かずに読める。呼び口の --node は落とす（同じ失敗がノードごとに割れる）"""
    d = data_dir(given)
    if d is None:
        return None
    if not (d / LOG).exists():
        return None   # 錠のファイルを作らない（まだ 1 行も残していない置き場）
    with filelock.BoardLock(d / LOCK):
        rows, _, done, dropped = _pending_unlocked(d)
    lost = max(0, dropped - done)
    if not rows and not lost:
        return None
    label = lambda r: ("手で残した 1 行" if r.get("kind") == "manual" else   # noqa: E731
                       f"{str(r.get('where') or '?').split(' --node', 1)[0]} {r.get('exc') or r.get('kind')}")
    return {"dir": str(d), "file": str(d / LOG), "pending": len(rows), "oldest": rows[0].get("at") if rows else None, "lost": lost,
            "top": collections.Counter(label(r) for r in rows).most_common(3)}


def summary(rows):
    """送る本文の text（incoming webhook は text を要る）。1 行 1 件、構造化したフィールドだけ。"""
    lines = []
    for r in rows:
        head = f"{r.get('plugin')} {r.get('version')} {r.get('where')}"
        if r.get("kind") == "manual":
            lines.append(f"{head} — {r.get('what', '')}")
        else:
            lines.append(f"{head} exit={r.get('exit')} {r.get('exc')}@{r.get('func')} key={r.get('key')}")
    return "\n".join(lines)


def url_of(d):
    try:
        return json.loads((d / CONFIG).read_text(encoding="utf-8")).get("url") or None
    except (FileNotFoundError, ValueError):
        return None


def set_url(d, url):
    d.mkdir(parents=True, exist_ok=True)
    (d / CONFIG).write_text(json.dumps({"url": url or None}, ensure_ascii=False), encoding="utf-8")


def post(url, rows):
    """届け先へ {text, records} を POST する（利用者が明示に呼んだときだけ。失敗の口からは呼ばない）。返すのは HTTP の状態。"""
    body = json.dumps({"text": summary(rows), "records": rows}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as res:
        return res.status
