# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ラインの最後にいつも走る節 finish（returns の節。Ruling R21）。run の後に人が見る物を 1 つの出口にまとめる。

読む環境変数（Archon が節の with: から JSON の文字列で渡す）:
- INPUTS_JUDGED: 判定のブロックの出口（{ok, open_units, need_fix, judgment_file, one_shot}）
- INPUTS_REVIEW: 差分の審査のブロックの出口（{ok, faces, review_file, diff_file}）。審査を飛ばした run では null
出口（標準出力に 1 行、終了コード 0）:
- 直した run: {"ok": true, "outcome": "fixed", "judgment_file", "review_file", "diff_file", "faces"}
- 直す物が無い判定の run（修正から後を飛ばした）: {"ok": true, "outcome": "no_fix_needed", "judgment_file"}
入力が読めない・判定と審査の有る無しが食い違う（need_fix なのに審査が無い、など）: 標準エラーに理由を 1 行出して 1。
標準ライブラリだけ。
"""
import json
import os
import sys

sys.dont_write_bytecode = True


class Broken(Exception):
    pass


def env_json(name):
    raw = os.environ.get(name)
    if raw is None:
        raise Broken(f"環境変数が無い: {name}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise Broken(f"{name} が JSON として読めない: {e}（頭: {raw[:200]!r}）")


def finish():
    judged, review = env_json("INPUTS_JUDGED"), env_json("INPUTS_REVIEW")
    if not isinstance(judged, dict) or judged.get("ok") is not True or not isinstance(judged.get("need_fix"), bool) \
            or not isinstance(judged.get("judgment_file"), str):
        raise Broken(f"判定の出口が崩れている（ok・need_fix・judgment_file が要る）: {str(judged)[:200]!r}")
    out = {"ok": True, "judgment_file": judged["judgment_file"]}
    if not judged["need_fix"]:
        if review is not None:
            raise Broken("判定は直す物が無いと言ったのに、差分の審査が走っている")
        return {**out, "outcome": "no_fix_needed"}
    if review is None:
        raise Broken("判定は直す物が在ると言ったのに、差分の審査が走っていない")
    if not isinstance(review, dict) or review.get("ok") is not True \
            or not all(isinstance(review.get(k), str) for k in ("review_file", "diff_file")) \
            or not isinstance(review.get("faces"), int):
        raise Broken(f"差分の審査の出口が崩れている（ok・faces・review_file・diff_file が要る）: {str(review)[:200]!r}")
    return {**out, "outcome": "fixed", "review_file": review["review_file"], "diff_file": review["diff_file"],
            "faces": review["faces"]}


def main():
    try:
        out = finish()
    except Broken as e:
        print(f"finish: {e}".replace("\n", " "), file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
