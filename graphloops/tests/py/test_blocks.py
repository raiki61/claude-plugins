"""ブロックの約束の置き場（graphloops/blocks/）——graph は出口の節の schema を $ref で指し、engine（engine/schema.py の
inline_block_refs）が graph の置き場から引いて展開する。graphcheck の検査 18 が所属・出口・並列の上書き・共有の核を照らす。"""
import json
import shutil

import pytest

from conftest import PLUGIN, REPO, graphcheck
from engine.schema import graph_text, inline_block_refs, load_graph

REVIEW_VALIDATOR = REPO / "scripts" / "review-record.py"
RESEARCH_VALIDATOR = REPO / "scripts" / "research-record.py"


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def plugin(tmp_path):
    """graph・prompts・rules・blocks の写し（graph はブロックのファイルを graph の置き場から相対で引く）"""
    for d in ("graphs", "prompts", "rules", "blocks"):
        shutil.copytree(PLUGIN / d, tmp_path / d)
    return tmp_path


def run_check(path, validator=REVIEW_VALIDATOR):
    lines = []
    ok = graphcheck.check(path, str(validator), emit=lines.append)
    return ok, "\n".join(map(str, lines))


# ---------------------------------------------------------------- 展開（engine/schema.py）
def test_block_ref_resolves_against_the_referring_file(tmp_path):
    """$ref は参照する側のファイルの置き場に対して解決し、ブロックのファイルの中の #/… はそのファイル自身を引く。engine#/ は残す"""
    write(tmp_path / "blocks" / "l" / "b" / "exit.schema.json",
          {"properties": {"n": {"$ref": "#/$defs/t"}, "m": {"$ref": "engine#/driver_problems"}}, "$defs": {"t": {"type": "string"}}})
    g = write(tmp_path / "graphs" / "g.json", {"nodes": {"n": {"schema": {"$ref": "../blocks/l/b/exit.schema.json#/properties/n"}},
                                                          "m": {"schema": {"$ref": "../blocks/l/b/exit.schema.json#/properties/m"}},
                                                          "k": {"schema": {"$ref": "#/$defs/x"}}}})
    used = []
    out = inline_block_refs(read(g), g, used)
    assert out["nodes"]["n"]["schema"] == {"type": "string"}
    assert out["nodes"]["m"]["schema"] == {"$ref": "engine#/driver_problems"}
    assert out["nodes"]["k"]["schema"] == {"$ref": "#/$defs/x"}      # graph の $defs は重ねの後で引く
    assert [p.name for p in used] == ["exit.schema.json"]


def test_whole_file_ref_drops_its_defs(tmp_path):
    write(tmp_path / "blocks" / "l" / "b" / "block.json", {"nodes": ["n"], "exit": {"$ref": "exit.schema.json"}})
    write(tmp_path / "blocks" / "l" / "b" / "exit.schema.json", {"properties": {"n": {"$ref": "#/$defs/t"}}, "$defs": {"t": {"type": "integer"}}})
    g = write(tmp_path / "graphs" / "g.json", {"blocks": {"b": {"$ref": "../blocks/l/b/block.json"}}})
    out = inline_block_refs(read(g), g)
    assert out["blocks"]["b"] == {"nodes": ["n"], "exit": {"properties": {"n": {"type": "integer"}}}}


@pytest.mark.parametrize("ref,files,words", [
    pytest.param("../rules/x.json#/a", {"rules/x.json": {"a": 1}}, "引けるのは", id="outside-blocks"),
    pytest.param("../blocks/x.txt", {"blocks/x.txt": {}}, "引けるのは", id="not-json"),
    pytest.param("../blocks/none.json", {}, "無い", id="missing"),
    pytest.param("../blocks/a.json#/nope", {"blocks/a.json": {"x": 1}}, "'nope' が引けない", id="bad-pointer"),
    pytest.param("../blocks/a.json#/x", {"blocks/a.json": {"x": {"$ref": "#/x"}}}, "自分を引いている", id="self-ref"),
])
def test_block_ref_refuses(tmp_path, ref, files, words):
    for rel, body in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(json.dumps(body), encoding="utf-8")
    g = write(tmp_path / "graphs" / "g.json", {"nodes": {"n": {"schema": {"$ref": ref}}}})
    with pytest.raises(ValueError, match=words):
        inline_block_refs(read(g), g)


def test_block_ref_with_siblings_is_refused(tmp_path):
    write(tmp_path / "blocks" / "a.json", {"type": "string"})
    g = write(tmp_path / "graphs" / "g.json", {"nodes": {"n": {"schema": {"$ref": "../blocks/a.json", "minLength": 1}}}})
    with pytest.raises(ValueError, match="他の語"):
        inline_block_refs(read(g), g)


def test_overlay_can_still_patch_an_exit_schema(plugin):
    """差し替えの版（extends）は、ブロックへ移した出口の節の schema にも欄を部分的に重ねられる（ブロックの参照は重ねの前に各ファイルで展開する。
    人の答え 2026-09-27: 後退は通さない）"""
    tdd = plugin / "graphs" / "review-loop-tdd.json"
    over = read(tdd)
    over["nodes"]["p3.fix"]["schema"] = {"properties": {"x_note": {"type": "string"}}}
    write(tdd, over)
    g, why = load_graph(tdd)
    assert why == ""
    sch = g["nodes"]["p3.fix"]["schema"]
    assert sch["properties"]["x_note"] == {"type": "string"} and "changes" in sch["properties"]


def test_shipped_graphs_have_no_schema_body_for_exit_nodes():
    """出口の節の schema の正本はブロックのファイルだけ。展開した後の姿は、ブロックの出口の型と同じ"""
    for name in ("review-loop", "research-loop", "review-loop-tdd"):
        g, why = load_graph(PLUGIN / "graphs" / f"{name}.json")
        assert why == "", why
        assert '"$ref":' not in json.dumps(g["nodes"]) and '"$ref":' not in json.dumps(g["blocks"])
        for b in g["blocks"].values():
            for n, sch in ((b.get("exit") or {}).get("properties") or {}).items():
                assert "pointers" in g["nodes"][n] or sch == g["nodes"][n]["schema"], (name, n)   # pointers は展開の後に型を広げる


def test_graph_text_covers_block_files(plugin):
    """graph の同一性（init の graph_sha・周ごとの graph_changed）は、引いたブロックのファイルを含む——ブロックの型だけを変えても変化に数える"""
    gp = plugin / "graphs" / "review-loop.json"
    before = graph_text(gp)
    ex = plugin / "blocks" / "review-loop" / "fix" / "exit.schema.json"
    ex.write_text(ex.read_text(encoding="utf-8").replace('"description"', '"note": "x", "description"', 1), encoding="utf-8")
    assert graph_text(gp) != before
    # 差し替えの版は元の graph の本文も、両方が引くブロックのファイルも含む
    tdd = plugin / "graphs" / "review-loop-tdd.json"
    assert ex.read_text(encoding="utf-8") in graph_text(tdd)


def test_graph_text_without_block_refs_is_unchanged(tmp_path):
    """ブロックを引かない graph（走っている run の古い版）の同一性は今までと同じ本文"""
    (tmp_path / "base.json").write_text('{"nodes": {}}', encoding="utf-8")
    (tmp_path / "over.json").write_text('{"extends": "base.json"}', encoding="utf-8")
    assert graph_text(tmp_path / "over.json") == '{"extends": "base.json"}' + "\n" + '{"nodes": {}}'
    assert graph_text(tmp_path / "base.json") == '{"nodes": {}}'


# ---------------------------------------------------------------- 検査 18（graphcheck）
@pytest.mark.parametrize("name,validator", [
    ("review-loop", REVIEW_VALIDATOR), ("research-loop", RESEARCH_VALIDATOR), ("review-loop-tdd", REVIEW_VALIDATOR)])
def test_shipped_graphs_pass_the_block_checks(name, validator):
    ok, out = run_check(PLUGIN / "graphs" / f"{name}.json", validator)
    assert ok and "が 1 つずつ属し、別のブロックが読む節は全部出口に在る" in out, out[-400:]


def test_shipped_graph_has_no_parallel_overwrite():
    """同じ周の擦り合わせは 3 往復（REJUDGE_PASSES）の鎖で p2.rejudge から p2.rejudge_third まで祖先の関係に在る——並列の上書きは残っていない"""
    ok, out = run_check(PLUGIN / "graphs" / "review-loop.json")
    assert ok and "並んで走りうる" not in out, out[-400:]


def test_conditional_parallel_overwrite_is_printed_not_failed(plugin):
    """条件つきの並列の上書きは機械で排他を決められない——落とさず、印字して人に渡す（init の警告にはしない）"""
    def cut(g):     # 第三の目を往復の鎖から外し、p2.rejudge と並べる（どちらも条件つきで record.units を上書きする）
        n = g["nodes"]["p2.rejudge_third"]
        n["deps"] = ["p3.fix"]
        n["reads"] = [r for r in n["reads"] if not r.startswith("cur.p3.rejudge_reply")]
    edit(plugin / "graphs" / "review-loop.json", cut)
    ok, out = run_check(plugin / "graphs" / "review-loop.json")
    assert "--  節 p2.rejudge と p2.rejudge_third" in out and "WARN 節 p2.rejudge" not in out
    assert not any(l.startswith("NG") and "並んで走りうる" in l for l in out.splitlines()), out[-400:]


def inline_exit(plugin, loop, block, node, drop=True):
    """出口の節の schema を graph に直に戻し（drop なら出口のファイルからも外す）——出口の宣言を壊す検査の下ごしらえ"""
    ex_p = plugin / "blocks" / loop / block / "exit.schema.json"
    ex = read(ex_p)
    gp = plugin / "graphs" / f"{loop}.json"
    g = read(gp)
    body = inline_block_refs({"x": {"$ref": f"../blocks/{loop}/{block}/exit.schema.json#/properties/{node}"}}, gp)["x"]
    g["nodes"][node]["schema"] = body
    write(gp, g)
    if drop:
        ex["properties"].pop(node)
        write(ex_p, ex)
    return gp


def edit(p, fn):
    obj = read(p)
    fn(obj)
    write(p, obj)


@pytest.mark.parametrize("breaks,words", [
    pytest.param(lambda d: edit(d / "blocks/review-loop/report/block.json", lambda b: b["nodes"].remove("report")),
                 "節 report がどのブロックにも属さない", id="node-in-no-block"),
    pytest.param(lambda d: edit(d / "blocks/review-loop/judge/block.json", lambda b: b["nodes"].append("p2.fix_plan")),
                 "節 p2.fix_plan が 2 つのブロック", id="node-in-two-blocks"),
    pytest.param(lambda d: edit(d / "blocks/review-loop/judge/block.json", lambda b: b["nodes"].append("p9.none")),
                 "節 p9.none が graph に無い", id="block-names-unknown-node"),
    pytest.param(lambda d: edit(d / "blocks/review-loop/judge/block.json", lambda b: b.__setitem__("slot", "judge")),
                 "block.json の鍵は", id="unknown-block-key"),
    pytest.param(lambda d: inline_exit(d, "review-loop", "prereq", "p0.purpose"),
                 "p0.purpose が、ブロック prereq の出口に無い", id="read-across-not-in-exit"),
    # hist.<名> を読む節は、その値が hist_reads で読む節も読む（hist.snapshot → out.p1.worktree_before）
    pytest.param(lambda d: inline_exit(d, "review-loop", "material", "p1.worktree_before"),
                 "（hist_reads の out.p1.worktree_before） で読む p1.worktree_before が、ブロック material の出口に無い", id="hist-read-not-in-exit"),
    pytest.param(lambda d: inline_exit(d, "review-loop", "fix", "p3.fix", drop=False),
                 "出口の節 p3.fix の schema は graph の中に書かず", id="exit-schema-written-twice"),
    pytest.param(lambda d: edit(d / "blocks/review-loop/prereq/exit.schema.json",
                                lambda e: e["properties"].__setitem__("p0.premises", {"type": "object"})),
                 "prereq の出口の p0.premises を、ほかのブロックのどの節も読まない", id="exit-read-by-nobody"),
    pytest.param(lambda d: edit(d / "graphs/review-loop.json", lambda g: g.pop("blocks")),
                 "最上位に blocks（ブロックの宣言）が無い", id="blocks-removed"),
    pytest.param(lambda d: edit(d / "graphs/review-loop.json", lambda g: g["nodes"]["p0.premises"]["writes"].append(
                     {"op": "set", "to": "process.base", "from": "constraints"})),
                 "節 p0.base と p0.premises は祖先の関係に無く", id="unconditional-parallel-overwrite"),
    pytest.param(lambda d: edit(d / "blocks/shared/cold-reader/core.schema.json", lambda c: c["properties"].__setitem__("findings", {"type": "array"})),
                 "使い手の節 report.cold_check の findings が無い", id="shared-core-field-missing"),
    pytest.param(lambda d: edit(d / "blocks/shared/two-stage/derive.schema.json", lambda c: c["properties"]["reason"].__setitem__("type", "boolean")),
                 "使い手の節 r2.design の reason の type", id="shared-core-type-differs"),
    pytest.param(lambda d: edit(d / "blocks/shared/prior-decisions/block.json", lambda b: b["parts"]["core"]["users"].pop("review-loop")),
                 "このループ（review-loop）の使い手が 1 つも無い", id="shared-without-users"),
])
def test_graphcheck_rejects_broken_blocks(plugin, breaks, words):
    breaks(plugin)
    ok, out = run_check(plugin / "graphs" / "review-loop.json")
    assert not ok and words in out, out[-600:]


def test_tdd_overlay_block_must_list_the_base_nodes(plugin):
    """TDD 版は修正のブロックを fix-tdd に差し替える——既定の修正の節を落とすと、差し替えの版の検査と所属の検査が落とす"""
    edit(plugin / "blocks/review-loop/fix-tdd/block.json", lambda b: b["nodes"].remove("p3.lane_merge"))
    ok, out = run_check(plugin / "graphs" / "review-loop-tdd.json")
    assert not ok and "p3.lane_merge" in out, out[-600:]
