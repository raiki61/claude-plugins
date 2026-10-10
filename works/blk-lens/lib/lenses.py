"""修正の後の局所レビュー（レンズ）のブロックの中身。控え lens.json の形と読み書きは core の lens だけが持つ。

レンズは利用者が入れた pr-review-toolkit の agent（定義は写さない。役の隔離した設定のキャッシュか <PLUGIN>_ROOT から
rolekit.agent_def で前付けを剥がした本文を引く）。レンズの節は定義の本文を指示書に貼った節そのもので、子（Agent）を起こさない
（節ごとの model が効くように。持ち主 2026-10-01）。

- LENSES:               レンズの表（{lens, agent, route}。route(files) -> (go, 理由)。レンズを足す時は行と YAML の節を 1 つずつ足す）
- key(row)・input_name(row): 振り分けの出口の欄の頭（<key>_go・prompt_<key>）と、集め役が読む環境変数の名
- route(board):         振り分け（AI なし）。今の周の修正の差分から、レンズごとの go と理由・指示書を出口に出し、lens.json に書く。
                        定義が引けないレンズは起こさない（not_routed と理由）。盤面に今の周の修正の差分が無ければ BoardGap
- render(row, body, diff_file, files, lang): レンズの節の指示書（定義の本文と、この線での読み方・返し方）
- collect(board, env):  集め役。レンズの節の出口（無ければ null）で lens.json を埋め、落ちたレンズも理由つきで記録して ok
- exit_(board, collected): 境。集め役の出口が無い・ok でないなら盤面を止めて（by stopby.LENS）ok: false
"""
import json
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap  # noqa: E402
import entry  # noqa: E402
import lens  # noqa: E402
import promptsection  # noqa: E402
import refix  # noqa: E402
import rolekit  # noqa: E402
import stopby  # noqa: E402  （L1。止めの理由の住処）


def _any_change(files):
    return (True, "") if files else (False, "修正の差分に変わったファイルが無い")


LENSES = (
    {"lens": "silent-failure-hunter", "agent": "pr-review-toolkit:silent-failure-hunter", "route": _any_change},
)


def key(row) -> str:
    return row["lens"].replace("-", "_")


def input_name(row) -> str:
    return f"INPUTS_{key(row).upper()}"


TASK_HEAD = promptsection.Section("## この節での仕事", source="fn:lenses.render")
REPLY_HEAD = promptsection.Section("## 返答の書き方", source="fn:lenses.render")
# レンズごとの役の印の名は lens-<レンズの名>
RECEIVES = [
    *(promptsection.Receive(f"lens-{row['lens']}", head) for row in LENSES for head in (TASK_HEAD, REPLY_HEAD)),
    *(promptsection.Receive(f"lens-{row['lens']}", rolekit.ROLE_DEF_HEAD, "lenses.render") for row in LENSES),
]


def render(row, body: str, diff_file: str, files: list, lang: str) -> str:
    return "\n".join([
        rolekit.ROLE_DEF_HEAD.format(agent=row['agent']), "", body.strip(), "", "---", "",
        TASK_HEAD, "",
        f"お前は修正の後の局所レビューのレンズ（{row['lens']}）として、新しい会話で起きている。上の定義の観点だけで、"
        "この周の修正が作った差分を見る。修正を書いた役の会話も、判定の経緯も引き継いでいない。",
        "お前は読むだけの役。使えるのは Read・Grep・Glob だけで、作業ツリーを 1 文字も変えない。子（Agent）は起こせない——"
        "定義がほかの道具や子に触れていても、自分で読んで答えよ。", "",
        f"- 修正の差分: `{diff_file}`（Read せよ。周の頭に固めた版と修正後の姿の差）",
        f"- 変わったファイル: {json.dumps(files, ensure_ascii=False)}", "",
        "差分は起点であって線ではない——呼び元・読む側まで読め。指摘は変わったファイルの中の物だけを挙げる。"
        "指摘は差分の審査役が検算してから穴にする。",
        "",
        REPLY_HEAD, "",
        "- 指摘 1 件ごとに `findings` の 1 行: `where`（変わったファイルのパス。上の一覧の字のまま）・"
        "`cite`（そのファイルの今の姿に在る字列そのまま。4 字以上）・`why`（何が黙って失敗し、誰が気づけないか。20 字以上）。",
        "- 指摘が無いなら `findings` を空にし、`findings_none` に何を読んで無いと言えるかを書け。",
        "- 返すのは JSON だけ。", "", lang,
    ]) + "\n"


def route(board) -> dict:
    b = entry.open_board(pathlib.Path(board))
    b.work(lens.LENS_FILE).unlink(missing_ok=True)   # 前の試みの控えを次の集め役に読ませない
    d = refix.fix_delta(b)
    if not d or not d.get("file"):
        raise BoardGap("盤面に今の周の修正の差分が無い（修正が差分を作った run だけで回すブロック）")
    files = list(d.get("files") or [])
    lang = rolekit.lang_line(b.state.get("inputs"))
    out, rows = {"ok": True, "diff_file": d["file"]}, []
    for row in LENSES:
        go, why = row["route"](files)
        prompt = ""
        if go:
            got = rolekit.agent_def(row["agent"])
            if got is None or not got.get("body"):
                go, why = False, f"{row['agent']} の定義が役の設定に無い（pr-review-toolkit が入っていない）"
            else:
                prompt = render(row, got["body"], d["file"], files, lang)
        rows.append({"lens": row["lens"], "agent": row["agent"], "go": go, "reason": why})
        out[f"{key(row)}_go"], out[f"prompt_{key(row)}"] = go, prompt
    lens.write_routes(b, rows)
    out["why"] = "・".join(f"{r['lens']}: {r['reason']}" for r in rows if not r["go"])
    return out


def _parse(raw):
    raw = (raw or "").strip()
    if raw in ("", "null"):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw   # 形の違う出口として集め役が failed に記録する


def collect(board, env: dict) -> dict:
    b = entry.open_board(pathlib.Path(board), allow_halted=True)
    try:
        rows = lens.collect(b, {row["lens"]: _parse(env.get(input_name(row))) for row in LENSES})
    except ValueError as e:
        return {"ok": False, "reason": str(e), "lens_file": "", "ran": 0, "failed": 0, "not_routed": 0}
    count = {s: sum(1 for r in rows if r["state"] == s) for s in ("ran", "failed", "not_routed")}
    return {"ok": True, "reason": "", "lens_file": str(b.work(lens.LENS_FILE)), **count}


def exit_(board, collected) -> dict:
    if isinstance(collected, dict) and collected.get("ok") is True:
        return {"ok": True, "reason": "", "lens_file": collected.get("lens_file") or ""}
    why = collected.get("reason") if isinstance(collected, dict) else "集め役の出口が無い（集め役が落ちた）"
    reason = f"レンズの集め役が終わらなかった: {why or '理由の記録が無い'}"
    b = entry.open_board(pathlib.Path(board), allow_halted=True)
    if not (b.state.get("halted") or b.state.get("stop")):
        b.stop(reason, by=stopby.LENS)
    return {"ok": False, "reason": reason, "lens_file": ""}
