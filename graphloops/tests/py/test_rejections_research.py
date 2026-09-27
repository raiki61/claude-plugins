"""research-loop の否定検査（graphloops/tests/simulate.py の test_rejections を、控えた波・1 手・手で書いた期待へ移した物）。

盤面を使う検査は waves.py が控えた波から始めて 1 手を打つ（medium）。材料の上限（slim_item）と直読みの柵の標本・走査は、盤面を
歩かずに engine の部品と engine・rules のソースを直に見る（small）。移した元の check は ``moved_from`` の印が名乗る（台帳は ledger.py）。
"""
import json
import pathlib
import types

import glharness
import pytest
import waves
from engine.advance import ITEM_INLINE, load_item, slim_item
from engine.rules import load_rules
from engine.util import dump

SRC = "simulate.test_rejections"
research = waves.research
PLUGIN = glharness.PLUGIN


def moved(head, **kw):
    return pytest.mark.moved_from(SRC, head, **kw)


def rejected(r, *words):
    assert r.returncode == 1, f"rc={r.returncode} {(r.stdout + r.stderr).strip()[-300:]}"
    missing = [w for w in words if w not in r.stderr]
    assert not missing, f"拒否文に {missing} が無い: {r.stderr.strip()[-300:]}"


def std(run, node):
    return research.base_answers(run, "std")[node](None, 1)


# ---- init の入口 -----------------------------------------------------------------------------------------------------

def _init_without_document(run, *extra):
    return glharness.inproc(["init", "--loop", "research-loop", "--request", "x", "--dir", str(run.tmp / "nodoc"),
                             "--validator", str(research.VALIDATOR), *extra], cwd=run.repo)


@pytest.mark.medium
@moved("research を --document 無しで init すると入口で落ち、要る節と穴を名指しする",
       kept="子プロセスとして起こした loop.py init の argv と、入口の拒否が 0 以外の終了コードになること（__main__ の写像）")
def test_init_without_document_names_the_node_and_hole(wave):
    r = _init_without_document(wave("research/neg/init").run)
    assert r.returncode != 0
    assert "--document" in r.stderr and "p0.claims" in r.stderr, r.stderr[-300:]


@pytest.mark.medium
@moved("実在しない --document も入口で落ちる", kept="子プロセスとして起こした loop.py init の argv と終了コード")
def test_init_with_missing_document_fails_at_the_entrance(wave):
    run = wave("research/neg/init").run
    r = _init_without_document(run, "--document", str(run.tmp / "no-such.md"))
    assert r.returncode != 0
    assert "が無い" in r.stderr, r.stderr[-300:]


# ---- P0 の 1 波目（p0.question） -------------------------------------------------------------------------------------

@pytest.mark.medium
@moved("最初の節は p0.question（回す側）")
def test_first_node_is_the_runner_question(wave):
    q = wave("research/neg/init").run.next()["ready"][0]
    assert q["node"] == "p0.question" and q["mode"] == "runner"


@pytest.mark.medium
@moved("型に合わない返答は exit 1")
def test_reply_outside_the_schema_is_rejected(wave):
    w = wave("research/neg/q")
    rejected(w.run.done(w.pending()["p0.question"]["id"], {"question": "x"}), "必須の欄")


@pytest.mark.medium
@moved("回す側の降格は exit 1")
def test_runner_cannot_lower_the_thickness(wave):
    w = wave("research/neg/q")
    rejected(w.run.done(w.pending()["p0.question"]["id"], {**std(w.run, "p0.question"), "thickness": "軽量"}), "下げようとしている")


@pytest.mark.medium
@moved("正しい返答は通る")
def test_correct_reply_is_accepted(wave):
    w = wave("research/neg/q")
    r = w.run.done(w.pending()["p0.question"]["id"], std(w.run, "p0.question"))
    assert r.returncode == 0, r.stderr[-300:]


@pytest.mark.medium
@moved("同じ節に 2 回 done は exit 1")
def test_second_done_on_the_same_node_is_rejected(wave):
    run = wave("research/neg/q-done").run
    rejected(run.done("p0.question", std(run, "p0.question")), "既に")


@pytest.mark.medium
@moved("optional でない節は省けない")
def test_non_optional_node_cannot_be_skipped(wave):
    rejected(wave("research/neg/q-done").run.cmd("skip", "--node", "p0.claims", "--reason", "面倒"), "optional でない")


# ---- P0 の 2 波目 ------------------------------------------------------------------------------------------------------

@pytest.mark.medium
@moved("2 波目に P0 の残りと先行起動が並ぶ")
def test_second_wave_has_the_rest_of_p0_and_early_starts(wave):
    by = {i["node"]: i for i in wave("research/neg/q-done").run.next()["ready"]}
    assert {"p0.claims", "p0.terms", "p0.prior_decisions", "p5.internal", "p3.rederiver"} <= set(by)


@pytest.mark.medium
@moved("調べ役の agent_type は convergence-loops: 接頭")
def test_investigator_agent_type_has_the_plugin_prefix(wave):
    by = {i["node"]: i for i in wave("research/neg/q-done").run.next()["ready"]}
    assert by["p0.prior_decisions"]["agent_type"] == "convergence-loops:investigator"


def _stray_then_investigator_done(w):
    (w.run.repo / "stray.txt").write_text("x", encoding="utf-8")
    return w.run.done(w.pending()["p0.prior_decisions"]["id"], std(w.run, "p0.prior_decisions"))


@pytest.mark.medium
@moved("investigator の前後で作業ツリーが変わると exit 1")
def test_worktree_change_around_the_investigator_is_rejected(wave):
    rejected(_stray_then_investigator_done(wave("research/neg/w2")), "作業ツリーが変わっている")


def _accept_after_stray(w):
    _stray_then_investigator_done(w)
    return w.run.cmd("done", "--node", w.pending()["p0.prior_decisions"]["id"], "--output", str(w.run.tmp / "out.json"),
                     "--accept-tree-change", "自分で作った")


@pytest.mark.medium
@moved("理由付きなら通る（痕跡が残る）")
def test_accept_tree_change_with_a_reason_passes(wave):
    r = _accept_after_stray(wave("research/neg/w2"))
    assert r.returncode == 0, r.stderr[-300:]


@pytest.mark.medium
@moved("git_mismatches に理由が残る")
def test_accepted_reason_is_kept_in_git_mismatches(wave):
    w = wave("research/neg/w2")
    _accept_after_stray(w)
    assert w.run.state()["git_mismatches"][0]["accepted"] == "自分で作った"


def _second_wave_prompt(wave, node):
    run = wave("research/neg/q-done").run
    by = {i["node"]: i for i in run.next()["ready"]}
    return pathlib.Path(by[node]["prompt_file"]).read_text(encoding="utf-8"), str(run.doc.resolve())


@pytest.mark.medium
@moved("回す側の節には文書のパスが渡り、本文は貼られない")
def test_runner_node_gets_the_document_path_not_its_body(wave):
    body, doc = _second_wave_prompt(wave, "p0.claims")
    assert doc in body and "主張 A・B・C・D" not in body


@pytest.mark.medium
@moved("同じ波の 2 節目（p0.terms）も本文を貼らない")
def test_second_runner_node_of_the_wave_does_not_paste_the_body(wave):
    body, doc = _second_wave_prompt(wave, "p0.terms")
    assert doc in body and "主張 A・B・C・D" not in body


@pytest.mark.medium
@moved("前の節の出力の穴が埋まっている")
def test_holes_from_earlier_outputs_are_filled(wave):
    body, _ = _second_wave_prompt(wave, "p0.claims")
    assert "open_questions" not in body or "[]" in body or "この周には無い" in body


# ---- クラスタと checker ----------------------------------------------------------------------------------------------

@pytest.mark.medium
@moved("クラスタに入れ漏れた主張があると exit 1")
def test_claim_left_out_of_every_cluster_is_rejected(wave):
    w = wave("research/neg/w3")
    rejected(w.run.done(w.pending()["p0.clusters"]["id"], {"clusters": [{"key": "c1", "claim_ids": ["A", "B"]}]}), "どのクラスタにも入っていない")


@pytest.mark.medium
@moved("claims_submitted は機械が数える")
def test_claims_submitted_is_counted_by_the_engine(wave):
    w = wave("research/neg/w3")
    assert w.run.done(w.pending()["p0.clusters"]["id"], std(w.run, "p0.clusters")).returncode == 0
    assert [c["claims_submitted"] for c in w.run.record()["clusters"]] == [2, 2]


def _checkers(wave):
    run = wave("research/neg/w4").run
    return {i["item"]["key"]: i for i in run.next()["ready"] if i["node"] == "p1.checker"}


@pytest.mark.medium
@moved("checker はクラスタごとに並ぶ")
def test_checkers_fan_out_per_cluster(wave):
    assert set(_checkers(wave)) == {"c1", "c2"}


@pytest.mark.medium
@moved("材料の正本（items/ のファイル）に材料の欄が在る")
def test_item_file_keeps_the_material(wave):
    assert "claims" in load_item(_checkers(wave)["c1"])


@pytest.mark.medium
@moved("c1 の材料は字数では上限内・バイトでは超過")
def test_fat_material_is_under_the_limit_in_chars_and_over_in_bytes(wave):
    claims = dump(load_item(_checkers(wave)["c1"]).get("claims"))
    assert len(claims) < ITEM_INLINE < len(claims.encode("utf-8"))


@pytest.mark.medium
@moved("太い材料の長い欄は instance から落ち、短い欄（key）は残る")
def test_long_field_of_a_fat_item_is_dropped_from_the_instance(wave):
    c1 = _checkers(wave)["c1"]
    assert c1.get("item_omitted") == ["claims"]
    assert "claims" not in c1["item"] and c1["item"].get("key") == "c1"


@pytest.mark.medium
@moved("短い材料は落ちず、落ちた欄が無いことも欄で言う")
def test_short_item_keeps_everything_and_says_so(wave):
    c2 = _checkers(wave)["c2"]
    assert c2.get("item_omitted") == [] and c2["item"].get("claims")


def _checker_body(wave):
    ch = _checkers(wave)
    text = pathlib.Path(ch["c1"]["prompt_file"]).read_text(encoding="utf-8")
    head, tail = text.split("返答はこの JSON Schema")[:2]
    return ch, head, tail


@pytest.mark.medium
@moved("checker には他の束の主張も判定も見立ても貼られない")
def test_checker_prompt_has_no_other_cluster_or_verdicts(wave):
    _, body, _ = _checker_body(wave)
    assert "C は Z" not in body and '"verdict":' not in body and "surveyor" not in body


@pytest.mark.medium
@moved("役には束の全員（")
def test_checker_prompt_carries_every_claim_of_the_cluster_to_the_end(wave):
    ch, body, _ = _checker_body(wave)
    claims = load_item(ch["c1"])["claims"]
    assert [c["id"] for c in claims] == ["A", "B"]   # 期待は台本の束（c1 は A と B）から——材料の側から取らない
    assert all(c["claim"] in body for c in claims)
    assert claims[0]["claim"][-20:] in body


@pytest.mark.medium
@moved("役へ渡す schema の断りに、引用符をエスケープしろの 1 行が付く")
def test_schema_note_tells_the_role_to_escape_quotes(wave):
    _, _, tail = _checker_body(wave)
    assert '\\"' in tail and "エスケープ" in tail


@pytest.mark.medium
@moved("扇の被覆: 渡した項目に無い id を返すと exit 1")
def test_checker_returning_an_id_it_was_not_given_is_rejected(wave):
    run = wave("research/neg/w5").run
    rejected(run.done("p1.checker[c1]", {"cluster": "c1", "findings": [{"id": "Z", "verdict": "確証", "evidence": "e", "sources": ["https://x"],
                                                                         "conditions": "c"}]}), "項目に無い")


@pytest.mark.medium
@moved("語彙に無い判定語は節の schema")
def test_verdict_outside_the_vocabulary_is_rejected(wave):
    run = wave("research/neg/w5").run
    rejected(run.done("p1.checker[c1]", {"cluster": "c1", "findings": [{"id": "A", "verdict": "たぶん", "evidence": "e", "sources": ["https://x"],
                                                                         "conditions": "c"}]}), "型に合わない")


@pytest.mark.medium
@moved("判定が欠けた主張は欠けた分だけ出し直す")
def test_missing_verdicts_are_reissued(wave):
    r = wave("research/neg/w5").run.done("p1.checker[c1]", waves.CHECKER_A_ONLY)
    assert r.returncode == 0, r.stderr[-300:]
    assert "欠けた" in r.stdout and "p1.checker[c1]#2" in r.stdout


@pytest.mark.medium
@moved("済んだ instance にはもう done できない")
def test_done_instance_cannot_be_done_again(wave):
    assert wave("research/neg/w5b").run.done("p1.checker[c1]", {"cluster": "c1", "findings": []}).returncode == 1


@pytest.mark.medium
@moved("欠けた分の checker と、返った分の refuter が同じ波に出る")
def test_reissued_checker_and_refuter_share_a_wave(wave):
    ids = [i["id"] for i in wave("research/neg/w5b").run.next()["ready"]]
    assert "p1.checker[c1]#2" in ids and "p1.refuter[A]" in ids


@pytest.mark.medium
@moved("refuter の upheld と verdict の食い違いは exit 1")
def test_refuter_upheld_and_verdict_must_agree(wave):
    r = wave("research/neg/w6").run.done("p1.refuter[A]", {"id": "A", "mode": "confirm", "upheld": True, "verdict": "相違",
                                                         "refuter_reasoning": "x", "sources": ["https://x"], "correction": "y"})
    rejected(r, "整合")


@pytest.mark.medium
@moved("相違に correction が無いと exit 1")
def test_discrepancy_without_correction_is_rejected(wave):
    r = wave("research/neg/w6").run.done("p1.checker[c1]#2", {"cluster": "c1", "findings": [{"id": "B", "verdict": "相違", "evidence": "e",
                                                                                              "sources": ["https://x"]}]})
    rejected(r, "correction")


@pytest.mark.medium
@moved("欄が揃えば通る")
def test_complete_discrepancy_is_accepted(wave):
    r = wave("research/neg/w6").run.done("p1.checker[c1]#2", waves.CHECKER_B_CORRECTED)
    assert r.returncode == 0, r.stderr[-300:]


# ---- 記録の手当て ----------------------------------------------------------------------------------------------------

@pytest.mark.medium
@moved("patch は痕跡付き")
def test_patch_leaves_a_trace(wave):
    run = wave("research/neg/w7").run
    (run.tmp / "p.json").write_text('"x"', encoding="utf-8")
    r = run.cmd("patch", "--path", "process.note", "--file", str(run.tmp / "p.json"), "--reason", "試験")
    assert r.returncode == 0, r.stderr[-300:]
    assert run.state()["patches"][0]["reason"] == "試験"


@pytest.mark.medium
@moved("check_record は語彙に無い verdict を拒む")
def test_check_record_rejects_a_verdict_written_by_patch(wave):
    run = wave("research/neg/w7").run
    rec = run.record()
    rec["claims"][0]["verdict"] = "たぶん"
    (run.tmp / "c.json").write_text(json.dumps(rec["claims"], ensure_ascii=False), encoding="utf-8")
    assert run.cmd("patch", "--path", "claims", "--file", str(run.tmp / "c.json"), "--reason", "試験（語彙外の判定語）").returncode == 0
    graph = PLUGIN / "graphs" / "research-loop.json"
    rules = load_rules(graph, json.loads(graph.read_text(encoding="utf-8")))
    errs = rules.check_record(types.SimpleNamespace(state={"validator": str(research.VALIDATOR)}, record=run.record()))
    assert any("語彙に無い" in e for e in errs), errs[:3]


# ---- 材料の上限（engine の slim_item を直に） ---------------------------------------------------------------------------

@pytest.mark.small
@moved("上限を超える長さの key でも slim_item は key を落とさない")
def test_slim_item_never_drops_the_key():
    slim, omitted = slim_item({"key": "あ" * 400, "claims": [{"id": "A"}]})
    assert "key" in slim and "key" not in omitted


@pytest.mark.small
@moved("欄ごとに上限未満でも合計が超えれば大きい順に逃がす")
def test_slim_item_bounds_the_total():
    slim, omitted = slim_item({"key": "c1", **{f"f{i}": "あ" * 200 for i in range(4)}})
    assert len(dump(slim).encode("utf-8")) <= ITEM_INLINE and omitted


@pytest.mark.small
@moved("大きい欄 1 つを落とせば収まる材料は、その 1 つだけが落ちる")
def test_slim_item_drops_the_biggest_field_first():
    slim, omitted = slim_item({"key": "c1", "small": "あ" * 10, "mid": "あ" * 60, "big": "あ" * 400})
    assert omitted == ["big"] and {"key", "small", "mid"} <= set(slim)


# ---- instance の item を直読みしない柵（標本と engine・rules の走査） --------------------------------------------------------
# 綴りと許しは台本の test_rejections の柵をこちらへ移した物（閉じ括弧まで綴りに入れない・拾わない形も標本で言う理由は台本の注記）

SPELLINGS = ('["item"]', "['item']", '.get("item"', ".get('item'")
ALLOW = ('inst["item"], omitted = slim_item(item)', 'return inst.get("item")')
CAUGHT = ('    x = i["item"]["key"]', "    x = i['item']['key']", '    x = i.get("item")["key"]', "    x = i.get('item')['key']",
          '    x = i.get("item", {})["key"]', "    x = i.get('item', {})['key']")
MISSES = ('    x = i [ "item" ]',            # 空白を挟んだ添字
          '    k = "item"; x = i[k]',         # 鍵を変数に逃がした形
          '    x = getattr(i, "item", None)',  # 属性としての読み
          '    x = {**i}[ITEM_KEY]')          # 鍵を定数に逃がした形


def flags(line):
    return any(sp in line for sp in SPELLINGS) and not any(a in line for a in ALLOW)


@pytest.mark.small
@moved("柵は 6 綴りとも拾う")
def test_fence_catches_all_six_spellings():
    assert [ln for ln in CAUGHT if flags(ln)] == list(CAUGHT)


@pytest.mark.small
@moved("射程の外（空白入り・変数の鍵・属性・定数の鍵）は拾わない")
def test_fence_does_not_catch_outside_its_reach():
    assert not [ln for ln in MISSES if flags(ln)]


@pytest.mark.small
@moved("書き手と load_item の中は許す")
def test_fence_allows_the_writer_and_load_item():
    assert not flags('        inst["item"], omitted = slim_item(item)')
    assert not flags('    return inst.get("item")')


@pytest.mark.small
@moved("engine と rules が instance の item を直読みしていない")
def test_engine_and_rules_do_not_read_the_instance_item_directly():
    direct = [f"{f.name}:{i + 1}" for f in sorted([*(PLUGIN / "engine").glob("*.py"), *(PLUGIN / "rules").glob("*.py")])
              for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()) if flags(line)]
    assert not direct
