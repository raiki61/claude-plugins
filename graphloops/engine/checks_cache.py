"""宣言した検査の一式（.review-checks.json の suite）の結果を、入力の指紋で使い回す（テスト結果のキャッシュ）。
role_run.run_steps が入口（plan・lookup）と出口（store）で呼ぶ。role_run と同じく盤面も graph も import しない。

同じ土台から並べた run が、同じ中身の作業ツリーで同じ一式（1 回 17〜57 分）を 1 本ずつ回し直していた（実測 2026-09-27:
05d3f69 に 5 本・38d7dde に 3 本）。形は Bazel の --cache_test_results=auto と Turborepo のタスクのキャッシュに倣う。

**使い回すのは、全段が exit 0 で終わった一式だけ。** 赤・起動できない段を含む一式は書かない（Bazel の auto も落ちたテストは
回し直す）。負荷の高い機械では赤が揺らぎでありうる。使い回すと、揺らぎが同じ中身の run 全部に貼り付く。
**一式ごとに使い回す**（段ごとにはしない）——段は前の段の副作用に依りうる。keep_background の段を 1 つでも含む一式は
対象外で、毎回回す（Bazel の external タグと同じ扱い）。宣言と一致しない語（engine 同梱の語）も対象外——外の今の状態を読む。

**指紋に入れる物**（材料。置き場の中に丸ごと持ち、読むときに完全一致を見る——鍵の sha256 は置き場の名前にだけ使う）:
- 作業ツリーの中身: 一時の index で `git add -A` して `git write-tree` した木の id（worktree_tree）。追跡中のファイルと
  .gitignore に当たらない未追跡のファイルの中身・実行ビット・シンボリックリンク
- 段の定義: declared.steps_sha
- 実行の土台: OS と CPU の種類・カーネルの版・各段の argv[0] を解決した実パスと大きさと更新時刻（ccache の
  compiler_check=mtime の見方——宣言はツールの版を持たないので、ツールの同一性をここで見る）
- 子に渡る環境変数の全部（child_env）——ただし IGNORED_ENV に在る名前は除く。子は環境の全部を見て走るので
  （結果を変える変数の例: このリポジトリの tests/run.sh の FAIL_ON_SKIP）、指紋も全部を覆う。Turborepo の既定（Strict Mode）は
  子の環境を指紋に入れた物と明示のパススルーに絞って同じ不変条件を保つ。ここは子の環境を狭めず（外すのは下の STRIPPED_ENV・
  STRIPPED_PREFIXES だけ）、指紋の側を広げる。値は名前ごとの sha256 で持ち、平文では書かない——ただし塩が無いので、
  短い値（1・true など）は逆引きでき、秘密の保護にはならない（置き場には一式の出力も丸ごと写る）
- PATH は並びの文字列でなく、意味で持つ（_path_identity）: 載っているフォルダの集合と、PATH で引ける名前ごとに最初に当たる
  フォルダの表。子がコマンドを引く規則（PATH の頭から、実行できるファイルの在る最初のフォルダ）と同じ表なので、並びや重複だけが
  違う PATH は同じ指紋になり、どれかの名前の引き先が変わる並べ替え・フォルダの足し引きは外れる。相対のフォルダを含む PATH と
  Windows（PATHEXT で引く）は、文字列のまま持つ

**環境変数を許す名前の一覧（allowlist）で持たない理由**（2026-10-19）: 一覧に無い変数を子が読むと、その変数が違う 2 つの環境で
緑を使い回す（偽の緑）。Turborepo が一覧で済むのは、子の環境も一覧に絞るから。ここは任意のリポジトリの一式を、人が手で回すのと
同じ環境で回す（子の環境を狭めると、一式が要る HOME・SSH_AUTH_SOCK・プロキシなどを名指しで足し続けることになる）。そのため
外す側を名指しする。外す名前は 2 つに分ける:
- IGNORED_ENV: 子に渡し、指紋から外す。どの端末・接続・会話かを指す識別子で、それを読んで結果を変える検査を知らない物
- STRIPPED_ENV・STRIPPED_PREFIXES: 子に渡さず、指紋からも外す。会話ごと・Claude Code の更新ごとに変わり、検査が要らない物。
  子が見ないので、外しても偽の緑にならない。CLAUDE_JOB_DIR は gates/hooks/coldread-gate.py が読んで振る舞いを変える
  （このリポジトリの tests/run.sh も外して回す）ので、渡したまま指紋から外すことはできない

**指紋に入れない物と理由**:
- 作業ツリーの絶対パス: 入れると worktree をまたいで当たらず、使い回しの主眼が消える
- HEAD・ブランチ・refs: 同じ中身なら同じ結果とみなす。履歴を読む検査はこの前提に合わない（下の旗で回す）
- .gitignore の対象・~/.cache などの外の置き場・段の中で呼ぶツール（argv[0] 以外）の版・時刻・ネットワークの先・機械の負荷:
  入れると run ごとに変わる値で当たらなくなる。これらだけが変わった差には、使い回しの回は気づかない
- IGNORED_ENV の変数: シェルの状態・接続と端末の識別子・起動した会話の識別子で、結果に効かないと分かっている物だけ。
  迷う変数は入れる側に倒す（偽の緑は偽の赤より悪い）。一覧に無い、起動するごとに変わる変数が在ると当たらなくなる——
  外れた回は、同じ作業ツリーの中身と段の記録が在れば、違った環境変数の名前を cache の行に出す（値は出さない。_miss_detail）
人のゲート（2026-09-27）はこの 4 つ——揺らぐテストの緑が固まる・履歴を読む検査・外の状態に依る検査・argv[0] 以外のツールの
版——を承知のうえで、既定を使い回しにすると決めた。

**当たり外れの控え**: 引いた回（lookup）は、当たったか・外れの訳（causes）・書いたかを盤面の log_dir の NOTE_NAME に書く。
scripts/quality-ledger.py がそれを数えて、当たりの率を出す。

**使い回しを切る旗**: engine のプロセスの環境変数 RERUN_ENV が空でなければ引かずに回す（書くのは続ける——Turborepo の
--force と同じ）。旗は宣言の一式の子に渡さない（child_env）。回している間に作業ツリーが変わった回（前後の木の id が違う）は
書かない——.gitignore の外に副産物を書く一式は 1 度も書かれないので、そうなった理由は段の行の cache に残す。

**置き場**: `git rev-parse --git-common-dir` の下の graphloops/checks-cache/<鍵>/（worktree から共有される）。消すなら
その置き場を丸ごと消せばよい（盤面の行は、当たった回も出力を盤面の log_dir に写してあるので切れない）。期限・件数の
上限は付けない（実測で決めた値が無い）。置き場は宣言の語が走らせるコードからも書ける（declared.py の冒頭の注記）。
"""
import datetime
import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile

from . import declared
from .util import worktree_tree

RERUN_ENV = "GRAPHLOOPS_RERUN_CHECKS"
# 指紋から外す環境変数（上の注記の「入れない物」。子には渡す）。2026-09-27 に同じ機械の loop.py launch 3 本と回す側のシェルの環境を
# 突き合わせて違った物（_・PWD・OLDPWD・SHLVL・SSH_CLIENT・SSH_CONNECTION）と、会話・端末・接続ごとに変わる識別子。
# HERDR_* の 3 つは herdr（端末を作業ごとの窓に分けるツール）がペインの中の殻に渡すペイン・タブ・作業場の番号（TMUX_PANE と同じ類）
IGNORED_ENV = frozenset({
    "_", "PWD", "OLDPWD", "SHLVL",
    "SSH_CLIENT", "SSH_CONNECTION", "SSH_TTY", "SSH_AUTH_SOCK",
    "TERM_SESSION_ID", "ITERM_SESSION_ID", "WINDOWID", "TMUX", "TMUX_PANE", "STY", "SESSIONNAME",
    "VSCODE_GIT_IPC_HANDLE", "VSCODE_IPC_HOOK_CLI",
    "HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
})
# 子に渡さず、指紋からも外す環境変数（上の注記の「allowlist で持たない理由」）。2026-10-19 に使い回しの置き場の 27 件（1 件も当たって
# いない）の material.env を突き合わせて値の違った名前のうち PATH を除く物と、会話ごとの一時の置き場:
# CLAUDE_CODE_EXECPATH（Claude Code の本体の置き場。版の番号を含み、自動の更新で変わる）・AI_AGENT（Claude Code の版を含む印）・
# CLAUDE_JOB_DIR（会話ごとの一時の置き場）。mise（ツールの版を切り替えるツール）の __MISE_* は殻の中の差分の控えで、効き目は PATH に出る
STRIPPED_ENV = frozenset({"CLAUDE_CODE_EXECPATH", "AI_AGENT", "CLAUDE_JOB_DIR"})
STRIPPED_PREFIXES = ("__MISE_",)
CACHE_PARTS = ("graphloops", "checks-cache")
FORMAT = 3   # 3: PATH を意味で持ち、STRIPPED_ENV を外した（2 の記録とは指紋が合わない）
NOTE_NAME = "cache.json"   # 引いた回の当たり外れの控え（盤面の log_dir に書く）
SHOW_NAMES = 12   # 外れの訳に並べる名前の数の上限（超えた分は数だけ）
# 外れの訳のキー（控えの causes に書く。機械が比べるのはキーで、表示の語はこの表から引く）。環境変数は "env:<名前>" で持つ
CAUSES = {"flag": "旗", "steps": "段の定義", "tree": "作業ツリーの中身", "platform": "OS・CPU・カーネルの版",
          "tools": "argv[0] のツール（実パス・大きさ・更新時刻）", "broken": "記録が壊れている"}
ENV_CAUSE = "env:"


def cause_label(key):
    """外れの訳のキーの表示の語（知らないキーはそのまま出す）"""
    return f"環境変数 {key[len(ENV_CAUSE):]}" if key.startswith(ENV_CAUSE) else CAUSES.get(key, key)


def cwd_git(cwd):
    """util.git と同じ呼び口（*args, env, why → 標準出力か None）の、cwd に縛った git。role_run の側から worktree_tree を
    呼ぶため（util.git は engine の大域の GIT_CWD を見る）。時間の上限は付けない"""
    def run(*args, env=None, why=None):
        try:
            r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env={**os.environ, **env} if env else None)
        except OSError as e:
            if why is not None:
                why.append(f"{type(e).__name__}: {e}")
            return None
        if r.returncode == 0:
            return r.stdout
        if why is not None:
            why.append(r.stderr.strip()[-300:] or f"exit {r.returncode}（標準エラーは空）")
        return None
    return run


def _stripped(name):
    return name == RERUN_ENV or name in STRIPPED_ENV or name.startswith(STRIPPED_PREFIXES)


def child_env():
    """宣言の一式の子に渡す環境——使い回しを切る旗（一式の中のテストが engine の旗を見て振る舞いを変えない）と、STRIPPED_ENV・
    STRIPPED_PREFIXES の名前を外す。走らせる道（使い回しの対象外の一式も）はどれもこの環境で回す"""
    return {k: v for k, v in os.environ.items() if not _stripped(k)}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()


def _path_identity(path):
    """PATH の意味の指紋（上の注記）。フォルダの集合と、名前ごとに最初に当たるフォルダの表を 1 つの sha256 にする。
    相対のフォルダを含む・Windows・読めないフォルダが在る、のどれかなら文字列のまま（引き先を確かめられない）"""
    dirs = path.split(os.pathsep) if path else []
    if os.name == "nt" or any(not os.path.isabs(d) for d in dirs):
        return _sha(path)
    dirs = [os.path.normpath(d) for d in dirs]   # 末尾の / だけ違うフォルダは同じフォルダ
    found = {}
    for d in dirs:
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.name in found:
                        continue
                    try:
                        if e.is_file() and os.access(e.path, os.X_OK):
                            found[e.name] = d
                    except OSError:   # 消えた・読めないファイルは子にも引けない
                        continue
        except (FileNotFoundError, NotADirectoryError):
            continue   # 無いフォルダからは何も引けない（子にとっても同じ）
        except OSError:
            return _sha(path)
    return _sha(json.dumps({"dirs": sorted(set(dirs)), "resolve": found}, sort_keys=True, ensure_ascii=False))


def _env_material(env):
    """指紋の env——名前ごとの値の sha256（PATH は _path_identity）。IGNORED_ENV の名前は入れない"""
    return {k: _path_identity(v) if k == "PATH" else _sha(v) for k, v in sorted(env.items()) if k not in IGNORED_ENV}


def _tool(argv0, cwd, path):
    """argv[0] の解決先の実パス・大きさ・更新時刻。/ を含む語は cwd から、含まない語は PATH から引く（子と同じ引き方）"""
    found = str(pathlib.Path(cwd) / argv0) if os.sep in argv0 or "/" in argv0 else shutil.which(argv0, path=path)
    if not found or not os.path.exists(found):
        return {"argv0": argv0, "missing": True}
    real = os.path.realpath(found)
    st = os.stat(real)
    return {"argv0": argv0, "path": real, "size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def plan(steps, cwd):
    """使い回しの対象か ——（計画, 対象外の理由）。対象外なら今までどおり回すだけ"""
    if any(s.get("keep_background") for s in steps):
        return None, "keep_background の段を含む一式は使い回さない"
    d, sha = declared.read(cwd), declared.steps_sha(steps)
    if not d or d.get("sha") != sha:
        return None, f"宣言 {declared.DECL_NAME} と一致する一式でない"
    git = cwd_git(cwd)
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common or not common.strip():
        return None, "共有の .git（git rev-parse --git-common-dir）が引けない"
    why = []
    tree = worktree_tree(why, git_fn=git)
    if tree is None:
        return None, f"作業ツリーの木の id が取れない（{' / '.join(why) or '理由は無し'}）"
    env = child_env()
    material = {"format": FORMAT, "tree": tree, "steps_sha": sha,
                "os": platform.system(), "machine": platform.machine(), "kernel": platform.release(),
                "env": _env_material(env),
                "tools": [_tool(s["argv"][0], cwd, env.get("PATH", "")) for s in steps]}
    key = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"key": key, "material": material, "entry": str(pathlib.Path(common.strip()).joinpath(*CACHE_PARTS, key)),
            "cwd": str(cwd)}, None


def _note(log_dir, **kw):
    """引いた回の当たり外れを log_dir の NOTE_NAME に足して書く（scripts/quality-ledger.py が数える）。書けなくても回すのは止めない"""
    f = pathlib.Path(log_dir) / NOTE_NAME
    try:
        cur = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except (OSError, ValueError):
        cur = {}
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({**(cur if isinstance(cur, dict) else {}), **kw}, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:   # 控えは数えるための物で、書けなくても一式の結果は変わらない（quality-ledger は控えの無い回を数えない）
        pass


def _names(items):
    return "・".join(items[:SHOW_NAMES]) + (f" ほか {len(items) - SHOW_NAMES} 個" if len(items) > SHOW_NAMES else "")


def _differs(now, old):
    """2 つの指紋の材料の違う所 ——（訳のキーの一覧, 違う環境変数の名前）。値は出さない"""
    ne, oe = now.get("env") or {}, old.get("env") if isinstance(old.get("env"), dict) else {}
    names = sorted(k for k in set(ne) | set(oe) if ne.get(k) != oe.get(k))
    causes = [ENV_CAUSE + k for k in names]
    if any(now.get(k) != old.get(k) for k in ("os", "machine", "kernel")):
        causes.append("platform")
    if now.get("tools") != old.get("tools"):
        causes.append("tools")
    return causes, names


def _miss_detail(p):
    """同じ指紋の記録が無いとき、置き場の他の記録と比べて外れの訳を出す ——（文, 訳の一覧）。
    同じ作業ツリーの中身と段の記録が在れば、違った所が一番少ない記録との違いの名前を出す"""
    root, m = pathlib.Path(p["entry"]).parent, p["material"]
    old_format, same_steps, closest = 0, 0, None
    try:
        dirs = [d for d in root.iterdir() if not d.name.startswith(".") and d.name != p["key"]]
    except OSError:
        dirs = []
    for d in dirs:
        try:
            e = json.loads((d / "entry.json").read_text(encoding="utf-8"))
            om = e.get("material") if isinstance(e, dict) else None
        except (OSError, ValueError):   # 読めない記録は比べる相手にしない（引く側は別に外れとして回す）
            continue
        if not isinstance(om, dict):
            continue
        if e.get("format") != FORMAT:
            old_format += 1
            continue
        if om.get("steps_sha") != m["steps_sha"]:
            continue
        same_steps += 1
        if om.get("tree") != m["tree"]:
            continue
        causes, names = _differs(m, om)
        if (closest is None or len(causes) < len(closest[0])
                or (len(causes) == len(closest[0]) and str(e.get("at")) > str(closest[2]))):
            closest = (causes, names, e.get("at"))   # 違う所の一番少ない記録（同じ数なら新しい方）
    if closest:
        causes, names, at = closest
        envs = [f"環境変数 {_names(names)}（値は伏せる）"] if names else []
        rest = [cause_label(c) for c in causes if not c.startswith(ENV_CAUSE)]
        return (f"同じ作業ツリーの中身と段の記録（{at}）と、{'・'.join(envs + rest) or '材料の形'}が違う"), causes
    if same_steps:
        return f"同じ段の記録 {same_steps} 件は、どれも作業ツリーの中身が違う", ["tree"]
    tail = f"（旧い形式の記録 {old_format} 件は比べない）" if old_format else ""
    return f"同じ段の定義の記録が無い{tail}", ["steps"]


def lookup(p, steps, log_dir):
    """同じ指紋の緑を引く ——（段の行, 外れの理由）。当たれば置き場の出力を log_dir に写し、行は log_dir を指す。
    どの道でも当たり外れを log_dir の NOTE_NAME に書く"""
    rows, why, causes = _lookup(p, steps, log_dir)
    _note(log_dir, format=1, at=_now(), key=p["key"], hit=rows is not None, why=why, causes=causes)
    return rows, why


def _lookup(p, steps, log_dir):
    if os.environ.get(RERUN_ENV):
        return None, f"旗 {RERUN_ENV} が立っている（引かずに回す。書くのは続ける）", ["flag"]
    entry_dir = pathlib.Path(p["entry"])
    try:
        e = json.loads((entry_dir / "entry.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        detail, causes = _miss_detail(p)
        return None, f"同じ指紋の記録が無い（鍵 {p['key'][:12]}）——{detail}", causes
    except (OSError, ValueError) as err:
        return None, f"記録が読めない（{err}）——回す", ["broken"]
    if not isinstance(e, dict):
        return None, "記録の形が崩れている——回す", ["broken"]
    runs = e.get("runs")
    if (e.get("format") != FORMAT or e.get("material") != p["material"] or not isinstance(runs, list) or len(runs) != len(steps)
            or any(not isinstance(r, dict) or r.get("name") != s["name"] or r.get("argv") != s["argv"] or r.get("exit") != 0
                   for r, s in zip(runs, steps))):
        return None, "記録が今の指紋・段・緑と一致しない——回す", ["broken"]
    t0 = datetime.datetime.now().timestamp()
    rows = []
    try:
        for i, (r, s) in enumerate(zip(runs, steps), 1):
            out, err = pathlib.Path(log_dir) / f"{i}.out", pathlib.Path(log_dir) / f"{i}.err"
            shutil.copyfile(entry_dir / f"{i}.out", out)
            shutil.copyfile(entry_dir / f"{i}.err", err)
            rows.append({"name": s["name"], "argv": list(s["argv"]), "out": str(out), "err": str(err), "exit": 0,
                         "tail": r.get("tail", ""),
                         "reused": {"at": e.get("at"), "wall_s": r.get("wall_s"), "key": p["key"], "entry": str(entry_dir),
                                    "from": e.get("from")}})
    except OSError as err:
        return None, f"記録の出力が欠けている（{err}）——回す", ["broken"]
    took = round(datetime.datetime.now().timestamp() - t0, 1)
    for r in rows:
        r["wall_s"] = took
    return rows, None, []


def _intact(entry, material, n):
    try:
        e = json.loads((entry / "entry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(e, dict) and e.get("format") == FORMAT and e.get("material") == material and isinstance(e.get("runs"), list)
            and len(e["runs"]) == n and all((entry / f"{i}.{x}").is_file() for i in range(1, n + 1) for x in ("out", "err")))


def store(p, steps, runs, log_dir):
    """全段が緑で、回す前後の木の id が同じなら置き場に書く ——（書いた置き場か None, 書かない理由）。
    書いたかを log_dir の NOTE_NAME に足す"""
    entry, why = _store(p, steps, runs, log_dir)
    _note(log_dir, stored=entry, not_stored=why)
    return entry, why


def _store(p, steps, runs, log_dir):
    if len(runs) != len(steps) or any(r.get("exit") != 0 for r in runs):
        return None, "赤か起動できない段を含む一式は書かない（落ちた一式は毎回回し直す）"
    tree = worktree_tree(git_fn=cwd_git(p["cwd"]))
    if tree != p["material"]["tree"]:
        return None, f"回している間に作業ツリーが変わった（木 {p['material']['tree'][:12]} → {str(tree)[:12]}）ので書かない"
    final = pathlib.Path(p["entry"])
    if final.exists():
        if _intact(final, p["material"], len(steps)):
            return str(final), None
        # 壊れた・欠けた記録（引く側は外れとして回した）を、今の緑で置き換える。消すのは脇へ退けてから
        try:
            aside = pathlib.Path(tempfile.mkdtemp(prefix=".broken-", dir=final.parent))
        except OSError as err:
            return None, f"壊れた記録 {final} を脇へ退ける置き場を作れない（{err}）ので書かない"
        try:
            os.rename(final, aside / "old")
            stuck = None
        except OSError as err:
            stuck = err
        shutil.rmtree(aside, ignore_errors=True)
        if stuck:
            # 退けられなければ壊れた記録が final に残る——下の rename は在る final に当たって落ち、在るから書けたと読み違える
            return None, f"壊れた記録 {final} を退けられない（{stuck}）ので書かない"
    final.parent.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix=".tmp-", dir=final.parent))
    try:
        for i, r in enumerate(runs, 1):
            shutil.copyfile(r["out"], tmp / f"{i}.out")
            shutil.copyfile(r["err"], tmp / f"{i}.err")
        (tmp / "entry.json").write_text(json.dumps(
            {"format": FORMAT, "key": p["key"], "material": p["material"], "at": _now(), "from": str(log_dir),
             "runs": [{k: r.get(k) for k in ("name", "argv", "exit", "wall_s", "tail")} for r in runs]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        os.rename(tmp, final)   # 読む側は entry.json の在る完成した置き場しか見ない
    except OSError as err:
        shutil.rmtree(tmp, ignore_errors=True)
        if final.is_dir():   # 同じ鍵を別の run が先に書いた
            return str(final), None
        return None, f"置き場に書けない（{err}）"
    return str(final), None
