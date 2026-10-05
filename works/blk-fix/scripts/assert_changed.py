# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""何も変えずに「済んだ」と言うのを止める検査（blk-fix の節 assert-changed。sdlc の assert-changed の考え方）。

変わったファイル = git diff --name-only <base_rev> と未追跡のファイル（.gitignore に当たる物は外す。どちらも -z で読み、
日本語などの名前を git の引用無しのまま申告と突き合わせる）。
どちらも .archon/ の下は数えない（Archon が run の作業ツリーに写す工程の置き場で、修正役の仕事ではない）。
.archon/ の下だけを触った修正は通らない（安全側に倒す）。
申告 = 受け付けた返答の changes[].files（INPUTS_ACCEPTED。輪の出力 = 最後の周の fix-accept の {ok, reason, changes}。
食い違いの申し出で 2 回目の修正の輪が走った run は、その輪の出力 INPUTS_RULED（飛ばされれば文字列 null）の方）。
変わった物だけでは見ない: テストを回すと __pycache__ などの未追跡のゴミができ、中身を 1 行も直さずに通ってしまう。
git が無視するファイルは、ここでは数えない（取り込む差分に載らない物。Ruling R15）。修正役が残したそれは、この前の節
clean が消す（盤面の fix-ignored-before.json の控えに無かった物だけ。消した物の件数と全件のファイルは collect が出口に通す）。
- 申告したファイルが全部変わっている: {"ok": true, "files": [申告 ∩ 変わった物]} を 1 行出して 0（ゴミは下流に流さない）
- 申告が空でも、直す義務の単位が残らず、答え待ちの fork・escalate の出どころか直す裁定でない裁定（ask_human・fix_plan_item）で外れた単位が在る盤面
  （conflict.nothing_owed_but_excused）なら正しい返答: {"ok": true, "files": [], "reason"（外れた単位と理由）} を 1 行出して 0、
  盤面の trace に 1 行（止めずに最後の人の関所へ届ける）
- 申告が空（上の場合を除く）・申告したのに変わっていないファイルが在る: run を落とさずに盤面（$ARTIFACTS_DIR/board）を理由つきで止め（by works:fix。R50）、
  {"ok": false, "files": [], "reason"} を 1 行出して 0。後ろの段は境の節が飛ばし、報告と書き出しは走る（run 26）。
  盤面が開けない（盤面の無いブロックだけの模擬実行）なら、標準エラーに理由を 1 行出して 1（1 本目のまま）
- 受け付けは最後の回に必ず通る（義務の単位を全部止めても写しが返答を受けなければ、受け付けが機械の空の返答を渡す。依頼 242 決め 5）
  ので、輪の出力が ok: false なら入力の誤り。それと、環境変数が無い・INPUTS_ACCEPTED が読めない・changes[].files の形が違う・
  版として引けない・git が効かない: 標準エラーに理由を 1 行出して 2
base_rev が空ならその場の HEAD（Ruling R2）。cwd が対象リポジトリ（Archon は対象で起こす）。標準ライブラリだけ。
"""
import json
import os
import posixpath
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
from leftovers import ARCHON_PREFIX, Unreadable, git, git_names  # noqa: E402
from script_io import later_output  # noqa: E402   .archon/ の決まりと git の呼び方の正本（clean と同じ物。.shared/core の模块）

STOP_BY = "works:fix"   # 修正の段が盤面を止めた印（報告の結末は stopped_by_line）
NOTHING_OWED_OP = "fix_nothing_owed"   # 空の申告を、直す義務が残らず外れた単位だけの正しい返答として通した盤面の trace の行


class GiveUp(Exception):
    """修正の段が通らない（run を落とさずに盤面を止める道）"""


def give_up(reason: str) -> int:
    """盤面を理由つきで止めて {"ok": false, "files": [], "reason"} を出し 0。盤面が開けなければ標準エラーに 1 行で 1"""
    artifacts = os.environ.get("ARTIFACTS_DIR")
    try:
        if not artifacts:
            raise Unreadable("環境変数 ARTIFACTS_DIR が無い")
        import entry   # 盤面の入口（.shared/core。止める時だけ読む）
        b = entry.open_board(Path(artifacts) / "board", allow_halted=True)
        if not (b.state.get("stop") or b.state.get("halted")):   # もう止まった盤面は止め直さない（最初の理由が正）
            b.stop(reason, by=STOP_BY)
    except Exception as e:   # 盤面の無い模擬実行・開けない盤面: 止められないので 1 本目のまま run を止める
        print(f"assert-changed: {reason}（盤面を止められない: {' '.join(str(e).split())}）".replace("\n", " "), file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"ok": False, "files": [], "reason": reason}, ensure_ascii=False))
    return 0


def nothing_owed() -> str:
    """直す義務が残らず、外れた単位が在る盤面なら通す理由の文（conflict.nothing_owed_but_excused。外れた単位と理由を並べ、
    盤面の trace に 1 行）。違う・盤面が開けなければ空（止める側）"""
    artifacts = os.environ.get("ARTIFACTS_DIR")
    if not artifacts:
        return ""
    try:
        import conflict
        import entry
        b = entry.open_board(Path(artifacts) / "board", allow_halted=True)
        excused = conflict.nothing_owed_but_excused(b)
        if not excused:
            return ""
        b.trace(NOTHING_OWED_OP, node="assert-changed", excused=dict(sorted(excused.items())))
    except Exception:
        return ""
    return f"{conflict.NOTHING_OWED}: " + "・".join(f"{k}（{why}）" for k, why in sorted(excused.items()))


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
    if not isinstance(accepted, dict):
        raise Unreadable(f"INPUTS_ACCEPTED が JSON のオブジェクトでない（{str(accepted)[:200]!r}）")
    if accepted.get("ok") is not True:   # 受け付けは最後の回に必ず通る（決め 5）。ok: false も回す側の誤り
        raise Unreadable(f"受け付けの出力が ok: true でない（{str(accepted)[:200]!r}）")
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
        declared = declared_files(later_output(os.environ["INPUTS_ACCEPTED"], os.environ.get("INPUTS_RULED")))
        rev, changed = touched(base_rev)
    except GiveUp as e:
        return give_up(str(e))
    except Unreadable as e:
        print(f"assert-changed: {e}".replace("\n", " "), file=sys.stderr)
        return 2
    since = f"{rev[:12]}（base_rev {base_rev or 'HEAD'}）"
    passed = nothing_owed() if not declared else ""
    if passed:
        print(json.dumps({"ok": True, "files": [], "reason": passed}, ensure_ascii=False))
        return 0
    if not declared:
        return give_up("修正役は済んだと言ったが、触ったファイルを 1 つも申告していない（changes[].files が空。直す義務の単位が"
                       "残っているか、答え待ち・直さない裁定で外れた単位が 1 つも無い）")
    unchanged = sorted(declared - set(changed))
    if unchanged:
        return give_up(f"修正役は済んだと言ったが、申告したファイル {unchanged} は {since} から何も変わっていない"
                       f"（git diff --name-only と未追跡のファイル。.archon/ の下は数えない。変わった物: {changed[:10]}）")
    print(json.dumps({"ok": True, "files": sorted(declared)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
