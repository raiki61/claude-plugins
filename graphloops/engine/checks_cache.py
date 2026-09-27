"""宣言した検査の一式（.review-checks.json の suite）の結果を、入力の指紋で使い回す（テスト結果のキャッシュ）。
role_run.run_steps が入口（plan・lookup）と出口（store）で呼ぶ。role_run と同じく盤面も graph も import しない。

同じ土台から並べた run が、同じ中身の作業ツリーで同じ一式（1 回 17〜57 分）を 1 本ずつ回し直していた（実測 2026-09-27:
05d3f69 に 5 本・38d7dde に 3 本）。形は Bazel の --cache_test_results=auto と Turborepo のタスクのキャッシュに倣う。

**使い回すのは、全段が exit 0 で終わった一式だけ。** 赤・起こせない段を含む一式は書かない（Bazel の auto も落ちたテストは
回し直す）。負荷の高い機械では赤が揺らぎでありうる。使い回すと、揺らぎが同じ中身の run 全部に貼り付く。
**一式ごとに使い回す**（段ごとにはしない）——段は前の段の副作用に依りうる。keep_background の段を 1 つでも含む一式は
対象外で、毎回回す（Bazel の external タグと同じ扱い）。宣言と一致しない語（engine 同梱の語）も対象外——外の今の状態を読む。

**指紋に入れる物**（材料。置き場の中に丸ごと持ち、読むときに完全一致を見る——鍵の sha256 は置き場の名前にだけ使う）:
- 作業ツリーの中身: 一時の index で `git add -A` して `git write-tree` した木の id（worktree_tree）。追跡中のファイルと
  .gitignore に当たらない未追跡のファイルの中身・実行ビット・シンボリックリンク
- 段の定義: declared.steps_sha
- 実行の土台: OS と CPU の種類・子に渡る PATH の値・各段の argv[0] を解決した実パスと大きさと更新時刻（ccache の
  compiler_check=mtime の見方——宣言は道具の版を持たないので、道具の同一性をここで見る）

**指紋に入れない物と理由**:
- 作業ツリーの絶対パス: 入れると worktree をまたいで当たらず、使い回しの主眼が消える
- HEAD・枝・refs: 同じ中身なら同じ結果とみなす。履歴を読む検査はこの前提に合わない（下の旗で回す）
- .gitignore の対象・~/.cache などの外の置き場・段の中で呼ぶ道具（argv[0] 以外）の版・PATH 以外の環境変数・時刻・
  ネットワークの先・機械の負荷: 全部入れると run ごとに変わる値で当たらなくなる（Bazel が指紋に入れる環境変数も
  --test_env で名指しした物だけ）。これらだけが変わった差には、使い回しの回は気づかない
人の関所（2026-09-27）はこの 4 つ——揺らぐテストの緑が固まる・履歴を読む検査・外の状態に依る検査・argv[0] 以外の道具の
版——を承知のうえで、既定を使い回しにすると決めた。

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

RERUN_ENV = "GRAPHLOOPS_RERUN_CHECKS"
CACHE_PARTS = ("graphloops", "checks-cache")
FORMAT = 1


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


def worktree_tree(git, why=None):
    """作業ツリーの今の姿の木の id ——（木, None）か（None, (何が, 手掛かり)）。git は util.git と同じ呼び口。
    rules の _worktree_tree（周に採点する版の固定と前後の突合）と、使い回しの指紋が同じここを引く——『同じ中身』の意味を割らない。

    **本物の index を一時 index に写してから** `add -A` する。空の一時 index から始めていたとき、追跡中だが .gitignore に
    当たるファイルは `add -A` に拾われず、版から落ちて『削除』に見えた（実測 2026-09-25: 別のリポジトリの run で、判定役が
    これを根拠に誤った [block] を出した）。写しは stat の情報も持つので、`add -A` は変わったファイルだけをハッシュする。
    写しの上で `--really-refresh` を打つのは assume-unchanged の印を外すため——印を持ったままだと、git はそのファイルを
    見ずに古い中身で版を作る。本物の index は読むだけで書かない"""
    why = [] if why is None else why
    tmp = tempfile.mkdtemp(prefix="graphloops-index-")
    idx = pathlib.Path(tmp) / "index"
    env = {"GIT_INDEX_FILE": str(idx)}
    try:
        real = git("rev-parse", "--path-format=absolute", "--git-path", "index", why=why)
        if real is None or not real.strip():
            return None, ("本物の index の場所を git rev-parse --git-path で引けない", "git 2.31 以上か、リポジトリの中で呼んでいるかを確かめよ")
        try:
            shutil.copy2(real.strip(), idx)   # 時刻ごと写す——index の時刻が新しくなると、同じ秒に書き換えたファイル（racy git）を綺麗と見誤る
        except FileNotFoundError:
            pass   # index がまだ無い（init の直後で 1 度も add していない）＝追跡中のファイルが無いので、空から始めて落ちる物が無い
        except OSError as e:
            return None, (f"本物の index を写せない: {e}", None)
        if git("update-index", "-q", "--really-refresh", env=env, why=why) is None or git("add", "-A", env=env, why=why) is None:
            return None, ("一時 index への git update-index / add -A が失敗した", None)
        tree = git("write-tree", env=env, why=why)
        if tree is None or not tree.strip():
            return None, ("git write-tree が木を返さない", None)
        return tree.strip(), None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def child_env():
    """宣言の一式の子に渡す環境——使い回しを切る旗だけを外す（一式の中のテストが engine の旗を見て振る舞いを変えない）"""
    return {k: v for k, v in os.environ.items() if k != RERUN_ENV}


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
    """使い回しの対象か ——（計画, 対象外の理由）。計画は {key, material, entry}。対象外なら今までどおり回すだけ"""
    if any(s.get("keep_background") for s in steps):
        return None, "keep_background の段を含む一式は使い回さない"
    d = declared.read(cwd)
    if not d or d.get("sha") != declared.steps_sha(steps):
        return None, f"宣言 {declared.DECL_NAME} と一致する一式でない"
    git = cwd_git(cwd)
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common or not common.strip():
        return None, "共有の .git（git rev-parse --git-common-dir）が引けない"
    why = []
    tree, bad = worktree_tree(git, why)
    if tree is None:
        return None, f"作業ツリーの木の id が取れない（{bad[0]}。git の言い分: {' / '.join(why) or '無し'}）"
    path = os.environ.get("PATH", "")
    material = {"format": FORMAT, "tree": tree, "steps_sha": declared.steps_sha(steps),
                "os": platform.system(), "machine": platform.machine(), "path": path,
                "tools": [_tool(s["argv"][0], cwd, path) for s in steps]}
    key = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"key": key, "material": material, "entry": str(pathlib.Path(common.strip()).joinpath(*CACHE_PARTS, key)),
            "cwd": str(cwd)}, None


def lookup(p, steps, log_dir):
    """同じ指紋の緑を引く ——（段の行, 外れの理由）。当たれば置き場の出力を log_dir に写し、行は log_dir を指す"""
    if os.environ.get(RERUN_ENV):
        return None, f"旗 {RERUN_ENV} が立っている（引かずに回す。書くのは続ける）"
    started = pathlib.Path(p["entry"])
    try:
        e = json.loads((started / "entry.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"同じ指紋の記録が無い（鍵 {p['key'][:12]}）"
    except (OSError, ValueError) as err:
        return None, f"記録が読めない（{err}）——回す"
    if not isinstance(e, dict):
        return None, "記録の形が崩れている——回す"
    runs = e.get("runs")
    if (e.get("format") != FORMAT or e.get("material") != p["material"] or not isinstance(runs, list) or len(runs) != len(steps)
            or any(not isinstance(r, dict) or r.get("name") != s["name"] or r.get("argv") != s["argv"] or r.get("exit") != 0
                   for r, s in zip(runs, steps))):
        return None, "記録が今の指紋・段・緑と一致しない——回す"
    t0 = datetime.datetime.now().timestamp()
    rows = []
    try:
        for i, (r, s) in enumerate(zip(runs, steps), 1):
            out, err = pathlib.Path(log_dir) / f"{i}.out", pathlib.Path(log_dir) / f"{i}.err"
            shutil.copyfile(started / f"{i}.out", out)
            shutil.copyfile(started / f"{i}.err", err)
            rows.append({"name": s["name"], "argv": list(s["argv"]), "out": str(out), "err": str(err), "exit": 0,
                         "tail": r.get("tail", ""),
                         "reused": {"at": e.get("at"), "wall_s": r.get("wall_s"), "key": p["key"], "entry": str(started),
                                    "from": e.get("from")}})
    except OSError as err:
        return None, f"記録の出力が欠けている（{err}）——回す"
    took = round(datetime.datetime.now().timestamp() - t0, 1)
    for r in rows:
        r["wall_s"] = took
    return rows, None


def _intact(entry, material, n):
    try:
        e = json.loads((entry / "entry.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(e, dict) and e.get("format") == FORMAT and e.get("material") == material and isinstance(e.get("runs"), list)
            and len(e["runs"]) == n and all((entry / f"{i}.{x}").is_file() for i in range(1, n + 1) for x in ("out", "err")))


def store(p, steps, runs, log_dir):
    """全段が緑で、回す前後の木の id が同じなら置き場に書く ——（書いた置き場か None, 書かない理由）"""
    if len(runs) != len(steps) or any(r.get("exit") != 0 for r in runs):
        return None, "赤か起こせない段を含む一式は書かない（落ちた一式は毎回回し直す）"
    tree, _bad = worktree_tree(cwd_git(p["cwd"]))
    if tree != p["material"]["tree"]:
        return None, f"回している間に作業ツリーが変わった（木 {p['material']['tree'][:12]} → {str(tree)[:12]}）ので書かない"
    final = pathlib.Path(p["entry"])
    if final.exists():
        if _intact(final, p["material"], len(steps)):
            return str(final), None
        # 壊れた・欠けた記録（引く側は外れとして回した）を、今の緑で置き換える。消すのは脇へ退けてから
        aside = pathlib.Path(tempfile.mkdtemp(prefix=".broken-", dir=final.parent))
        try:
            os.rename(final, aside / "old")
        except OSError:
            pass
        shutil.rmtree(aside, ignore_errors=True)
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
