"""何も変えずに「済んだ」と言うのを止める検査（blk-fix の節 assert-changed。sdlc の assert-changed の考え方）。

触ったファイル = git diff --name-only <base_rev> と未追跡のファイル（.gitignore に当たる物は外す）。
どちらも .archon/ の下は数えない（Archon が run の作業ツリーに写す工程の置き場で、修正役の仕事ではない）。
- 触ったファイルが在る: {"ok": true, "files": [...]} を 1 行出して 0
- 無い: 標準エラーに理由を 1 行出して 1（節が落ち、run が止まる）
- INPUTS_BASE_REV が無い・版として引けない・git が効かない: 標準エラーに理由を 1 行出して 2
base_rev が空ならその場の HEAD（Ruling R2）。cwd が対象リポジトリ（Archon は対象で起こす）。標準ライブラリだけ。
"""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True

GIT_TIMEOUT = 120
IGNORED_PREFIX = ".archon/"


class Unreadable(Exception):
    pass


def git(*args):
    try:
        r = subprocess.run(["git", *args], capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unreadable(f"git {' '.join(args)} を呼べない（{type(e).__name__}: {e}）")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().replace("\n", " ")[-300:]
        raise Unreadable(f"git {' '.join(args)} が失敗した（{err or f'exit {r.returncode}'}）")
    return r.stdout.decode("utf-8", "replace")


def touched(base_rev):
    name = base_rev or "HEAD"
    if name.startswith("-"):
        raise Unreadable(f"base_rev {base_rev!r} は版の名前でない")
    try:
        rev = git("rev-parse", "--verify", "--quiet", f"{name}^{{commit}}").strip()
    except Unreadable:
        raise Unreadable(f"base_rev {base_rev!r} が版として引けない")
    files = git("diff", "--name-only", "--no-renames", rev, "--", ":/").splitlines()
    files += git("ls-files", "--others", "--exclude-standard", "--full-name", "--", ":/").splitlines()
    return rev, sorted({f for f in files if f and not f.startswith(IGNORED_PREFIX)})


def main():
    if "INPUTS_BASE_REV" not in os.environ:
        print("assert-changed: 環境変数が無い: INPUTS_BASE_REV", file=sys.stderr)
        return 2
    base_rev = os.environ["INPUTS_BASE_REV"]
    try:
        rev, files = touched(base_rev)
    except Unreadable as e:
        print(f"assert-changed: {e}", file=sys.stderr)
        return 2
    if not files:
        print(f"assert-changed: 修正役は済んだと言ったが、作業ツリーは {rev[:12]}（base_rev {base_rev or 'HEAD'}）から"
              "何も変わっていない（git diff --name-only と未追跡のファイルが空）", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "files": files}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
