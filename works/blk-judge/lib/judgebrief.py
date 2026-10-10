"""blk-judge の支度 judge-brief の芯（R61 judgeread・run 27）。判定役に、本線の判定（graph の p2.diagnose）が読む物——凍結した目的の文・
素材の 15 欄・P1 の目の所見・前の決定の突合・目的の監査・人の依頼・対象差分・観点の正本——と、本線の問いの台帳の決まりを渡す。

描き方は engine と同じ（rolekit.render_body。graph の reads だけ・番号の穴の縛り）で、描く本文は本線の指示書の写し
gl-prompts/prompts/review-loop/p2.diagnose.md の 2 か所: 「## 入力」の節から「## 手順」の前まで（欠けた素材を materials_missing で
名指す決まりの 1 文を含む）と、「問いの台帳（questions）」の段から「**前の周の R1 最小性」の段の前まで（kind・status・書ける欄は
検証器の表 {{validator.*}} から描く。素材が awaiting_human なら awaiting を必ず載せる決まり）。手順・出力の決まりは blk-judge の
commands/diagnose.md のまま。受け付けは盤面の p2.diagnose の done（judgetake。本線と同じ judge_output）。

- brief: ラインの盤面（$ARTIFACTS_DIR/board/state.json）が無ければ（ブロックを単独で回した）{ok, go: true, materials_file: ""}。
  盤面が止まっていれば（同じ境の節の後ろの素材集めが止めた。run 30）何も書かずに go: false（判定役を起こさない。blk-material の
  支度と同じ形）。止まっていなければ盤面の p2.diagnose が待っていること（待っていなければ BoardGap——線の順の誤り。黙って空にしない）。描いた本文を今の周の
  作業ファイル judge-materials.md に書き（盤面の根の世界の解の控えが行を指せば worldmark.section の節を頭に貼る。
  前の run で最後まで通らなかった物 prior-failures-in.json の行が在れば、
  carry.prior_section の節を末尾に足す。直す穴ではない注意）、判定役を起こす前の作業ツリーの姿を今の周の judge-tree.json に置き（entry.snapshot。
  受け付けが比べる）、待っている試行に起こした印を置く（描く → 印 → 起こす。盤面の決まり 2）。パスを返す
"""
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import carry  # noqa: E402
import entry  # noqa: E402
import entryshape  # noqa: E402
import judgetake  # noqa: E402
import promptsection  # noqa: E402
import rolekit  # noqa: E402
import worldmark  # noqa: E402  （世界の解の行の住処。盤面の根の控えが指す行を材料の頭に貼る）

NODE = judgetake.NODE
BRIEF_FILE = "judge-materials.md"
START = promptsection.Section("## 入力", human="本線の判定の指示書から節を切り出す探し字（役の指示書には貼らない）")
END = promptsection.Section("## 手順", human="本線の判定の指示書から節を切り出す探し字（役の指示書には貼らない）")
LEDGER_START, LEDGER_END = "問いの台帳（questions）", "**前の周の R1 最小性"   # 問いの台帳の決まりの段（本線の同じ指示書）
LEDGER_HEAD = promptsection.Section("## 問いの台帳（本線の判定の指示書の同じ段。kind・status・書ける欄はここが正本）\n\n", source="fn:judgebrief.template")
HEAD = promptsection.Section("# 判定の材料（盤面から描いた物）\n\n"
                             "本線の判定の指示書（graphloops の p2.diagnose.md）の「入力」の節と問いの台帳の段を、この run の盤面から engine と同じ描き方で描いた物。"
                             "値が貼ってある欄はそのまま読め。パス（対象差分・観点の正本など）は Read で読め。手順と返す JSON の形は、お前を起こした"
                             "指示書のとおり。", source="fn:judgebrief.brief")
# 受け手の宣言（役の印の名 ← 節 ← 入る条件を判じる関数）。判定役は材料の頭と、依頼・PR・世界の解の行・前の run の落ちた理由を受ける
RECEIVES = [
    promptsection.Receive("judge", LEDGER_HEAD, "judgebrief.template"),
    promptsection.Receive("judge", HEAD, "judgebrief.brief"),
    promptsection.Receive("judge", carry.PRIOR_HEAD, "carry.prior_section"),
    promptsection.Receive("judge", worldmark.HEAD, "worldmark.section"),
    *(promptsection.Receive("judge", head, "entryshape.request_text") for head in (entryshape.REQUEST_HEAD, entryshape.PR_TEXT_HEAD)),
    *(promptsection.Receive("judge", head, "entryshape.write_pr_file")
      for head in (entryshape.PR_TITLE, entryshape.PR_SUBJECT_HEAD, entryshape.PR_BODY_HEAD)),
]


def section(text: str, start_at: str = START, end_at: str = END) -> str:
    """指示書の本文から start_at で始まる行から end_at で始まる行の前まで。どちらかの行が無ければ BoardGap（写しが替わった）"""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith(start_at)), None)
    end = next((i for i, ln in enumerate(lines) if ln.startswith(end_at)), None)
    if start is None or end is None or end <= start:
        raise BoardGap(f"{NODE} の指示書に「{start_at}」と「{end_at}」で始まる行がこの順に無い（写しが替わった）")
    return "".join(lines[start:end]).rstrip("\n") + "\n"


def template(b) -> str:
    """盤面の graph の p2.diagnose の指示書（rolekit.prompt_graph_path と同じ引き方）の「入力」の節と問いの台帳の段"""
    n = b.nodes[NODE]
    text = (rolekit.prompt_graph_path(b, n).parent / n["prompt_file"]).read_text(encoding="utf-8")
    return section(text) + "\n" + LEDGER_HEAD + section(text, LEDGER_START, LEDGER_END)


def brief(board_dir, repo) -> dict:
    """judge-brief。返り {ok: True, go, materials_file}（盤面が無ければ go 真で空）。止まった盤面は go 偽（判定役の輪は when: で
    飛び、出口 collect が止まった盤面を ok 偽で渡す）。repo は対象リポジトリ（作業ツリーの姿を取る）"""
    d = pathlib.Path(board_dir)
    if not (d / "state.json").is_file():
        return {"ok": True, "go": True, "materials_file": ""}
    b = entry.open_board(d, allow_halted=True)
    if b.state.get("halted") or b.state.get("stop"):
        # 前の段が盤面を止めた（run 30）。役を起こさず、出口が止まった盤面を渡す
        return {"ok": True, "go": False, "materials_file": ""}
    inst = b.rd["instances"].get(NODE)
    if not inst or inst.get("status") != "pending":
        raise BoardGap(f"盤面の {NODE} が待っていない（{b.node_state(NODE)}）——判定の支度を回す所でない（線の順の誤り）")
    body, snap = rolekit.render_body(b, NODE, template=template(b), schema_note=False)
    if any(row.get("names") for row in snap):
        raise BoardGap(f"{NODE} の番号の穴（{snap}）が在る——前の周の R1 の削除候補を番号で指す形を、このブロックの受け付けは受けない")
    p = b.work(BRIEF_FILE)
    tmp = p.with_name(p.name + ".tmp")
    prior = carry.prior_section(d, gap=BoardGap)   # 盤面の根の前の run で最後まで通らなかった物（manifest の consumes。無ければ貼らない）
    world = worldmark.section(worldmark.stage_rows(d) or [])   # 盤面の根の控えが指す世界の解の行（無い・落ちた周は貼らない）
    tmp.write_text(HEAD + "\n\n" + (f"{world}\n" if world else "") + body + (f"\n\n{prior}\n" if prior else ""),
                   encoding="utf-8")
    tmp.replace(p)
    entry.snapshot(d, judgetake.TREE_FILE, pathlib.Path(repo))
    entry.open_board(d).mark_launched(NODE, inst.get("attempts", 1))
    return {"ok": True, "go": True, "materials_file": str(p)}
