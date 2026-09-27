# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""何も変えずに「済んだ」と言うのを止める検査（blk-fix の節 assert-changed。sdlc の assert-changed の考え方）。

変わったファイル = git diff --name-only <base_rev> と未追跡のファイル（.gitignore に当たる物は外す。どちらも -z で読み、
日本語などの名前を git の引用無しのまま申告と突き合わせる）。
どちらも .archon/ の下は数えない（Archon が run の作業ツリーに写す工程の置き場で、修正役の仕事ではない）。
.archon/ の下だけを触った修正は通らない（安全側に倒す）。
申告 = 受け付けた返答の changes[].files（INPUTS_ACCEPTED。輪の出力 = 最後の周の fix-accept の {ok, reason, changes}）。
変わった物だけでは見ない: テストを回すと __pycache__ などの未追跡のゴミができ、中身を 1 行も直さずに通ってしまう。
git が無視するファイルは、ここでは数えない（取り込む差分に載らない物。Ruling R15）。修正役が残したそれは、この前の節
clean が消す（盤面の fix-ignored-before.json の控えに無かった物だけ。消した物は collect が出口に並べる）。
- 申告したファイルが全部変わっている: {"ok": true, "files": [申告 ∩ 変わった物]} を 1 行出して 0（ゴミは下流に流さない）
- 申告が空・申告したのに変わっていないファイルが在る: 標準エラーに理由（どのファイルか）を 1 行出して 1（run が止まる）
- 環境変数が無い・INPUTS_ACCEPTED が読めない・受け付けが通っていない・版として引けない・git が効かない:
  標準エラーに理由を 1 行出して 2
base_rev が空ならその場の HEAD（Ruling R2）。cwd が対象リポジトリ（Archon は対象で起こす）。標準ライブラリだけ。
"""
import json
import os
import posixpath
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前

from leftovers import ARCHON_PREFIX, Unreadable, git, git_names  # noqa: E402   .archon/ の決まりと git の呼び方の正本（clean と同じ物。同じフォルダの模块）


def touched(base_rev):
    name = base_rev or "HEAD"
    if name.startswith("-"):
        raise Unreadable(f"base_rev {base_rev!r} は版の名前でない")
    try:
        rev = git(".", "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}").strip()
    except Unreadable:
        raise Unreadable(f"base_rev {base_rev!r} が版として引けない")
    files = git_names(".", "diff", "--name-only", "--no-renames", rev, "--", ":/")
    files += git_names(".", "ls-files", "--others", "--exclude-standard", "--full-name", "--", ":/")
    return rev, sorted({f for f in files if f and not f.startswith(ARCHON_PREFIX)})


def declared_files(raw):
    """受け付けた返答の changes[].files を、リポジトリの根からの相対パスに揃えた集合にする"""
    try:
        accepted = json.loads(raw)
    except json.JSONDecodeError as e:
        raise Unreadable(f"INPUTS_ACCEPTED が JSON として読めない: {e}（頭: {raw[:200]!r}）")
    if not isinstance(accepted, dict) or accepted.get("ok") is not True:
        raise Unreadable(f"受け付けが通っていない（{str(accepted)[:200]!r}）")
    changes = accepted.get("changes")
    if not isinstance(changes, list) or not all(isinstance(c, dict) and isinstance(c.get("files"), list) for c in changes):
        raise Unreadable("受け付けの出力に changes[].files が無い")
    out = set()
    for c in changes:
        for f in c["files"]:
            if not isinstance(f, str) or not f.strip():
                raise Unreadable(f"changes[].files に空・文字列でない物が在る（{f!r}）")
            out.add(posixpath.normpath(f.strip()))
    return out


def main():
    missing = [n for n in ("INPUTS_BASE_REV", "INPUTS_ACCEPTED") if n not in os.environ]
    if missing:
        print(f"assert-changed: 環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    base_rev = os.environ["INPUTS_BASE_REV"]
    try:
        declared = declared_files(os.environ["INPUTS_ACCEPTED"])
        rev, changed = touched(base_rev)
    except Unreadable as e:
        print(f"assert-changed: {e}".replace("\n", " "), file=sys.stderr)
        return 2
    since = f"{rev[:12]}（base_rev {base_rev or 'HEAD'}）"
    if not declared:
        print("assert-changed: 修正役は済んだと言ったが、触ったファイルを 1 つも申告していない（changes[].files が空）", file=sys.stderr)
        return 1
    unchanged = sorted(declared - set(changed))
    if unchanged:
        print(f"assert-changed: 修正役は済んだと言ったが、申告したファイル {unchanged} は {since} から何も変わっていない"
              f"（git diff --name-only と未追跡のファイル。.archon/ の下は数えない。変わった物: {changed[:10]}）", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "files": sorted(declared)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
