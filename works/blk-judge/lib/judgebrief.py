"""blk-judge の支度 judge-brief の芯（R61 judgeread）。判定役に、本線の判定（graph の p2.diagnose）が読む物——凍結した目的の文・
素材の 15 欄・P1 の目の所見・前の決定の突合・目的の監査・人の依頼・対象差分・観点の正本——を渡す。

描き方は engine と同じ（rolekit.render_body。graph の reads だけ・番号の穴の縛り）で、描く本文は本線の指示書の写し
gl-prompts/prompts/review-loop/p2.diagnose.md の「## 入力」の節から「## 手順」の前まで（欠けた素材を materials_missing で名指す
決まりの 1 文を含む）。手順・出力の決まりは blk-judge の commands/diagnose.md のまま（受け付けは v1 の check_judge）。

- brief: ラインの盤面（$ARTIFACTS_DIR/board/state.json）が無ければ（ブロックを単独で回した）{ok, materials_file: ""}。在れば
  盤面の p2.diagnose が待っていること（待っていなければ BoardGap——線の順の誤り。黙って空にしない）。描いた本文を今の周の
  作業ファイル judge-materials.md に書き、パスを返す。盤面へは書かない（受けるのはラインの h-plan）
"""
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import entry  # noqa: E402
import rolekit  # noqa: E402

NODE = "p2.diagnose"
BRIEF_FILE = "judge-materials.md"
START, END = "## 入力", "## 手順"
HEAD = ("# 判定の材料（盤面から描いた物）\n\n"
        "本線の判定の指示書（graphloops の p2.diagnose.md）の「入力」の節を、この run の盤面から engine と同じ描き方で描いた物。"
        "値が貼ってある欄はそのまま読め。パス（対象差分・観点の正本など）は Read で読め。手順と返す JSON の形は、お前を起こした"
        "指示書のとおり。")


def section(text: str) -> str:
    """指示書の本文から「## 入力」の行から「## 手順」の行の前まで。どちらかの見出しが無ければ BoardGap（写しが替わった）"""
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.startswith(START)), None)
    end = next((i for i, ln in enumerate(lines) if ln.startswith(END)), None)
    if start is None or end is None or end <= start:
        raise BoardGap(f"{NODE} の指示書に「{START}」と「{END}」の見出しがこの順に無い（写しが替わった）")
    return "".join(lines[start:end]).rstrip("\n") + "\n"


def template(b) -> str:
    """盤面の graph の p2.diagnose の指示書（rolekit.prompt_graph_path と同じ引き方）の「入力」の節"""
    n = b.nodes[NODE]
    path = rolekit.prompt_graph_path(b, n).parent / n["prompt_file"]
    return section(path.read_text(encoding="utf-8"))


def brief(board_dir, repo=None) -> dict:
    """judge-brief。返り {ok: True, materials_file}（盤面が無ければ空）。repo は script_main の口を揃えるだけ（盤面が inputs.cwd を持つ）"""
    d = pathlib.Path(board_dir)
    if not (d / "state.json").is_file():
        return {"ok": True, "materials_file": ""}
    b = entry.open_board(d)
    inst = b.rd["instances"].get(NODE)
    if not inst or inst.get("status") != "pending":
        raise BoardGap(f"盤面の {NODE} が待っていない（{b.node_state(NODE)}）——判定の支度を回す所でない（線の順の誤り）")
    body, snap = rolekit.render_body(b, NODE, template=template(b), schema_note=False)
    if any(row.get("names") for row in snap):
        raise BoardGap(f"{NODE} の番号の穴（{snap}）が在る——前の周の R1 の削除候補を番号で指す形を、このブロックの受け付けは受けない")
    p = b.work(BRIEF_FILE)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(HEAD + "\n\n" + body, encoding="utf-8")
    tmp.replace(p)
    return {"ok": True, "materials_file": str(p)}
