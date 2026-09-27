"""線 A の試験の手助け（test_* でないので unittest の発見に拾われない）。

- seed_repo: dev/target-seed/ を写した使い捨ての git リポジトリ（初めの commit つき。名前と時刻は固定）
- reply:     tests/replies/<名>.json の役の返答の見本
- git_env:   名前と時刻を固定した git の環境
- work_home: 使い捨ての物を置く家（${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/single/。Claude Code の一時フォルダの下に置かない）
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
SEED = ROOT / "dev" / "target-seed"
REPLIES = TESTS / "replies"
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
GIT_ID = ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "init.defaultBranch=main"]
DECLARATION = {"suite": [{"name": "suite", "argv": ["python3", "-m", "unittest", "test_stats"]}]}
BROKEN_DECLARATION = {"suite": []}   # 宣言の書式の誤り（suite は 1 段以上）。engine は読めずに任せ先へ落とす


def git_env() -> dict:
    """名前と時刻を固定した git の環境（利用者の設定の名前・署名に左右されない）"""
    fixed = {"GIT_AUTHOR_NAME": "works-test", "GIT_AUTHOR_EMAIL": "works-test@example.invalid",
             "GIT_COMMITTER_NAME": "works-test", "GIT_COMMITTER_EMAIL": "works-test@example.invalid",
             "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000"}
    return {**os.environ, **fixed}


def git(repo, *args) -> str:
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True,
                          env=git_env()).stdout.strip()


def seed_repo(into: pathlib.Path, *, declared: bool = False, broken_declaration: bool = False) -> pathlib.Path:
    """into に種（stats.py・test_stats.py）を写し、git の初めの commit を作って、その置き場の絶対パスを返す。
    declared なら .review-checks.json（suite 1 段）も、broken_declaration なら書式の誤った宣言も同じ commit に入れる"""
    if declared and broken_declaration:
        raise ValueError("declared と broken_declaration は片方だけ")
    into = pathlib.Path(into)
    shutil.copytree(SEED, into, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    decl = DECLARATION if declared else BROKEN_DECLARATION if broken_declaration else None
    if decl is not None:
        (into / ".review-checks.json").write_text(json.dumps(decl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    git(into, "init", "-q")
    git(into, "add", "-A")
    git(into, "commit", "-q", "-m", "seed")
    return into.resolve()


def reply(name: str) -> dict:
    """tests/replies/<name>.json"""
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


CLAUDE_TMP = ("/private/tmp/claude-", "/tmp/claude-")   # Claude Code の一時フォルダ（dev/guard.sh と同じ決まり）


def work_home() -> pathlib.Path:
    """${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/single/（作って返す）。Claude Code の一時フォルダの下に解決される置き場は、
    作る前に BoardGap で拒む（サンドボックスの Bash が書ける所に使い捨ての物を置かない）"""
    from board import BoardGap   # 盤面の層の誤りの型（.shared/core を sys.path に足してある）
    base = os.environ.get("WORKS_DEV_HOME") or str(pathlib.Path.home() / ".cache" / "works-dev")
    home = pathlib.Path(base) / "single"
    for p in (str(home), str(home.resolve())):
        if p.startswith(CLAUDE_TMP):
            raise BoardGap(f"work_home: {home} が Claude Code の一時フォルダの下にある（{home.resolve()}）。WORKS_DEV_HOME を別の場所にする")
    home.mkdir(parents=True, exist_ok=True)
    return home
