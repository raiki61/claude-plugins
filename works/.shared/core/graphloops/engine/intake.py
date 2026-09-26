"""踏んだ事実を、利用者の環境に 1 件 1 行で残す記録器（設計は docs/feedback/intake.md の段階 1・2）。ループの中身を知らない。

来歴（プラグインの名前と版・取れればコミット・run の番号と周）はここだけが組む。呼ぶ所は 4 つ:
loop.py の最上段（非 0 で終わった呼び出し）・launch の ok でない行・手の口（loop.py intake）・報告の頭の 1 行
（accept_output が save_text_as の本文を保存するとき）。

**どう失敗しても呼び元を止めない。** 残す処理は失敗の口の中で走るので、ここで上がった例外は元の終了コードを
書き換える。だから engine の道具（read_json・die・Board・util.git）を呼ばない——die と read_json は SystemExit を
上げ（except Exception を素通りする）、util.git は対象のリポジトリで走るのでプラグインのコミットを取り違える。
"""
import datetime
import hashlib
import json
import os
import pathlib
import platform
import re
import subprocess
import urllib.request

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parent.parent
LOG = "intake.jsonl"
CURSOR = "intake.cursor"      # 手渡した（書き出した・送った）所までの行数
CONFIG = "intake-config.json"
CLIP = 500                    # 人が書く 1 行と標準エラーの頭を切る長さ
DETAIL_ENV = "GRAPHLOOPS_INTAKE_STDERR"   # 1 のときだけ標準エラーの頭を残す（既定は構造化した欄だけ）


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
    """来歴の欄。盤面があれば、その周を回した engine（state.engine）の置き場と版を使う——記録の engine_changes と同じ値。"""
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


def stamp_line(state):
    """報告の頭に刻む 1 行（読めなければ None——報告は刻まずに保存する）。"""
    try:
        p = provenance(state)
        r = p.get("run", {})
        head = f"{p['plugin']} {p['version'] or '?'}" + (f" ({p['commit']})" if p.get("commit") else "")
        return " / ".join([head, f"{r.get('loop_name', '?')} run {r.get('run_id', '?')}",
                           f"round {r.get('round', '?')}", f"graph {r.get('graph_sha', '?')}"])
    except Exception:
        return None


def where_of(argv):
    """揺れない呼び口: `loop.py <サブコマンド>`（--node があれば節の id。[ ] の項目の鍵と #k の試行の後置は落とす
    ——鍵にはパスが混ざり、後置は同じ節を試行ごとに別の問題へ割る）。"""
    sub = next((x for x in argv if not x.startswith("-")), "?")
    where = f"loop.py {sub if re.fullmatch(r'[a-z][a-z-]*', sub) else '?'}"   # 打ち間違いの語（パスかもしれない）は残さない
    node = re.sub(r"#\d+$", "", (flag(argv, "--node") or "").split("[", 1)[0])
    if re.fullmatch(r"[\w.-]+", node):
        where += " --node " + node
    return where


def flag(argv, name):
    """argv の `--name 値` / `--name=値`（無ければ None）。"""
    for i, x in enumerate(argv):
        if x == name and i + 1 < len(argv):
            return argv[i + 1]
        if x.startswith(name + "="):
            return x.split("=", 1)[1]
    return None


def raised_in(tb):
    """例外を上げた engine の関数（`<module>.<関数>`）。小道具（util.py の die・read_json）の呼び元まで戻る
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


def record(kind, where, *, exit=None, exc=None, func=None, what=None, state=None, detail=None, given_dir=None):
    """1 件 1 行を追記する。書いた置き場を返し、どう失敗しても None を返すだけ（何も出さない）。

    kind が auto の行だけが鍵を持つ——手の行は呼び口が決まった値なので、鍵にすると別々の問題が 1 つに数えられる。"""
    try:
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
        with open(d / LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return d / LOG
    except KeyboardInterrupt:
        raise
    except BaseException:
        return None


def failed(argv, code, exc, tb=None, detail=None):
    """loop.py が非 0 で終わるときの 1 行（最上段の例外口が呼ぶ）。"""
    d, where = flag(argv, "--dir"), where_of(argv)
    # --data-dir は手の口の旗——ほかのサブコマンドに打ち間違いで付いた値（相対なら作業ツリーの中）には書かない
    given = flag(argv, "--data-dir") if where == "loop.py intake" else None
    return record("auto", where, exit=code if isinstance(code, int) else 1, exc=type(exc).__name__,
                  func=raised_in(tb), state=read_state(d) if d else None, detail=detail, given_dir=given)


# ---- 手の口（loop.py intake）----------------------------------------------------------------------------

def _rows(d):
    try:
        return [json.loads(x) for x in (d / LOG).read_text(encoding="utf-8").splitlines() if x.strip()]
    except FileNotFoundError:
        return []


def _cursor(d):
    try:
        return int((d / CURSOR).read_text(encoding="utf-8").strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def pending(d, everything=False, with_detail=False):
    """まだ手渡していない行（everything なら全部）と、全部の行数。既定は標準エラーの欄を落とす。"""
    rows = _rows(d)
    out = rows if everything else rows[_cursor(d):]
    if not with_detail:
        out = [{k: v for k, v in r.items() if k != "stderr"} for r in out]
    return out, len(rows)


def handed(d, upto):
    (d / CURSOR).write_text(str(upto), encoding="utf-8")


def summary(rows):
    """送る本文の text（incoming webhook は text を要る）。1 行 1 件、構造化した欄だけ。"""
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
