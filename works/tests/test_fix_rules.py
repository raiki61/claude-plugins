"""修正の決まりの正本（blk-fix/rules/common.md）と、2 つの修正役の指示書の組み立て（blk-fix/lib/fixrules.py。裁定 R65）の検査。

- 決まりの正本は 1 つ: 直す役（fix-prep が組む）と TDD の輪の役（tdd-prep が組む）の両方の指示書が、正本の節をそのまま含む
- 正本の文は works のほかの置き場に写さない（前から在る写しは KNOWN_COPIES に載せ、減らす方向にだけ変える）
- 本線から来た決まりの句が正本に在る・「プロジェクトのテストを回せ」の文は RUN_TESTS と一字違わず（直した単位に絞る）・
  変更の種類ごとの直の証拠（決定 C8）が在る
- 節を機械が選ぶ: 本線の核（直し方・守ること）はいつも、証拠の節は単位のファイルと差分に在る種類だけ、TDD の段の約束は今の段だけ
- 2 つの形（持ち主 2026-09-28）: full（全部。prompt_file はこの写し）と delta（変わった物と決まりの sha256 の 1 行）を並べて書き、
  控え <名>.variants.json を置く。1 回目の delta は full と同じ。どの節を載せたか・なぜかは各形の 1 行目の見出しに在る
- 組み立ては機械だけ（AI を通さない）で、同じ入力からはバイト単位で同じ。値の穴は全部埋まる
- 2 つの役の節の指示は 1 行（組んだ指示書のファイルを Read で読め）で、commands/ の手書きの指示書は無い
盤面・子のプロセスは使わない（組み立ての関数を直に呼ぶ。盤面の上の fix-prep は test_blk_fix、tdd-prep は test_blk_fix_tdd が見る）。
"""
import json
import pathlib
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(CORE))

import fixrules  # noqa: E402
import node_marker  # noqa: E402
import rolekit  # noqa: E402

SHARED = BLK / "rules" / "common.md"
# 本線（graphloops の p3.fix.md）から来た決まりの句。正本に在り、両方の指示書に届く
MAINLINE = ("根本の単位ごとに直せ", "同じ形を全部直せ", "直す前に既製の物で済まないかを確かめろ", "動きを変えたら",
            "テストを消すな・緩めるな", "git commit` するな")
# 書く役の試験の回し方（直した単位に絞る。一式は線の最後のテストの段が回す。裁定 c1-1 で書き換えた文）
RUN_TESTS = ("- **プロジェクトのテストを回せ。** 直した単位に当たる試験だけを絞って回せ（pytest の node id か `-k`、unittest の "
             "`-k` かモジュール名。絞り方はリポジトリの `run.sh`・テストの置き場から探す）。テストの実行器が在る run では、受け付けが"
             "版からの変更に当たる試験を機械で選んで回し、元で赤でなかった試験が赤なら理由のファイルで返す——自分で回すなら同じく"
             "変えたファイルに当たる試験を選べ。リポジトリのテスト一式は線の最後のテストの段が回すので、役は回さない。絞る手が無い時"
             "だけ、返答の直前に一式を 1 回だけ回せ。赤が残るなら、どの単位のどこかを直してから出せ。Python は "
             "`PYTHONDONTWRITEBYTECODE=1` を立てて回せ。git が無視する生成物（`__pycache__` など）のうち、あなたの前に無かった物は"
             "後の節が消す（消した物は人に見せる）。")
# 前から在る正本の行の写し（減らす方向にだけ変える。直ったのに残っていれば赤）: (置き場, 行の頭)
KNOWN_COPIES = {
    # 読み替えが同じ行き先の行を持つ（test_sp_skills が同じ行であることを縛る。読み替えは役に届かない読み物）
    (".shared/superpowers/unattended.md", "- **義務の単位の行き先**"),
    # 差分の審査への手直し役（blk-refix）の指示書。ブロックはほかのブロックのファイルを読めないので写しのまま
    ("blk-refix/commands/refix.md", "- 作業ツリーの外"),
    ("blk-refix/commands/refix2.md", "- 作業ツリーの外"),
}
MIN_LINE = 20   # 写しを探す行の長さの下限（見出し・短い語は偶然に重なる）
VALUES = {"judgment_file": "/b/out/r1/p2.diagnose.json", "open_units": '["a: 分母", "b: 上限"]', "plan_file": "/b/out/r1/p2.fix_plan.json",
          "policy_path": "", "notes_file": "/b/r1/notes.md", "summary_file": "/b/tdd-1/summary.md"}
PHASE_TEXT = "## この段ですること\n\n今の単位だけを直せ。\n\n## 返す JSON\n\n{\"phase\": \"fix\"}"
TITLE = "# TDD の輪の指示書（2 回目・段 fix）"
CORE_IDS = ("core-fix", "core-keep")
KIND_BULLET = {"docs": "- 文書:", "prompts": "- 指示書（プロンプト）:", "config": "- 設定・YAML・workflow:", "code": "- 注記・型:"}
PHASE_BULLET = {"route": "- **route**:", "test": "- **test**:", "fix": "- **fix**:", "refactor": "- **refactor**:"}


def shared_lines():
    return [ln for ln in SHARED.read_text(encoding="utf-8").splitlines() if not fixrules.MARK.match(ln)]


def tdd_values():
    return {k: VALUES[k] for k in fixrules.TDD_VALUES}


def header(text):
    first = text.split("\n", 1)[0]
    assert first.startswith("<!-- works-prompt ") and first.endswith(" -->"), first
    return json.loads(first[len("<!-- works-prompt "):-len(" -->")])


def block():
    return yaml.safe_load((BLK / "blk-fix.yaml").read_text(encoding="utf-8"))


def find_node(nodes, nid):
    for n in nodes:
        if n.get("id") == nid:
            return n
        if "loop_group" in n:
            got = find_node(n["loop_group"]["nodes"], nid)
            if got is not None:
                return got
    return None


class TestSharedSource(unittest.TestCase):
    def test_source_is_the_one_file(self):
        """正本の全部の節を繋ぐと、ファイルから節の印の行を除いた字そのもの（節で切っても文は変えない）"""
        self.assertEqual(fixrules.shared(), "\n".join(shared_lines()).strip("\n"))
        self.assertEqual(list(fixrules.sections(fixrules.SHARED)),
                         ["core-fix", "evidence", "evidence-docs", "evidence-prompts", "evidence-config", "evidence-code",
                          "core-conflict", "core-keep"])

    def test_conflict_rule_in_both_prompts_and_ruler(self):
        """食い違いの申し出（持ち主 2026-09-28）: 正本の core-conflict の決まりの文が、組んだ修正役・TDD の輪の役の指示書の両方に
        いつも載る（種類を選ばない時も）。裁定役の指示書は持ち主の決まり（principles.md）の全文と返す JSON の形を持つ"""
        rule = "緑にするためにテスト・依頼・コードのどれかを曲げるくらいなら、食い違いとして返せ"
        self.assertIn(rule, fixrules.sections(fixrules.SHARED)["core-conflict"])
        self.assertEqual(sum(ln.count(rule) for ln in shared_lines()), 1, "正本に 1 か所だけ")
        for text in (fixrules.fix_prompt(VALUES, kinds={}),
                     fixrules.tdd_prompt({k: VALUES[k] for k in fixrules.TDD_VALUES}, "route", "## 今の段", title="# t", kinds={})):
            self.assertIn(rule, text)
        ruler = fixrules.ruler_prompt({"conflicts_file": "/b/r1/conflicts.json", "ids": "c1-1", "judgment_file": "/b/j.json",
                                       "request_file": "", "policy_path": ""})
        self.assertIn(fixrules.sections(fixrules.PRINCIPLES)["principles"], ruler)
        for w in ("`c1-1`", "`/b/r1/conflicts.json`", "fix_test_scope", "fix_code_as", "ask_human", "review-graph"):
            self.assertIn(w, ruler)

    def test_every_rules_file_is_cut_into_sections(self):
        for name, ids in ((fixrules.DIRECT, ["fix-head", "fix-keep", "fix-reply"]), (fixrules.RULER, ["ruler-head", "ruler-reply"]),
                          (fixrules.PRINCIPLES, ["principles"]),
                          (fixrules.TDD, ["tdd-head", "tdd-remap", "tdd-phase", *(f"tdd-phase-{p}" for p in fixrules.PHASES),
                                          "tdd-phase-all", "tdd-end"])):
            with self.subTest(name):
                self.assertEqual(list(fixrules.sections(name)), ids)

    def test_mainline_phrases_in_the_core(self):
        core = "\n".join(fixrules.sections(fixrules.SHARED)[i] for i in CORE_IDS)
        for phrase in MAINLINE:
            with self.subTest(phrase):
                self.assertIn(phrase, core)

    def test_run_tests_sentence_kept(self):
        self.assertEqual([ln for ln in shared_lines() if "プロジェクトのテストを回せ" in ln], [RUN_TESTS])

    def test_direct_evidence_by_change_kind(self):
        """決定 C8: 先にテストを書けない直しの証拠を、変更の種類ごとに（文書・指示書・設定・注記と型）1 節ずつ"""
        sec = fixrules.sections(fixrules.SHARED)
        for kind, words in (("docs", ("パス", "リンク", "冷読")), ("prompts", ("描いて", "写し", "次の run")),
                            ("config", ("validate", "check.sh")), ("code", ("静的な検査",))):
            with self.subTest(kind):
                self.assertTrue(sec[f"evidence-{kind}"].startswith(KIND_BULLET[kind]))
                self.assertNotIn("\n", sec[f"evidence-{kind}"])
                for w in words:
                    self.assertIn(w, sec[f"evidence-{kind}"])

    def test_owed_routing_and_policy_once(self):
        body = shared_lines()
        self.assertEqual(len([ln for ln in body if ln.startswith("- **義務の単位の行き先**: ")]), 1)
        self.assertEqual(len([ln for ln in body if ln.startswith("- 人の方針に反するもの")]), 1)

    def test_no_copies_elsewhere(self):
        """正本の行（見出し・印・短い行を除く）は、works のほかの置き場（tests・docs を除く）に現れない。前からの写しは KNOWN_COPIES だけ"""
        lines = [ln for ln in shared_lines() if len(ln) >= MIN_LINE and not ln.startswith("#")]
        skip = {ROOT / d for d in ("tests", "docs")}
        hits = set()
        for p in sorted(ROOT.rglob("*")):
            if not p.is_file() or p == SHARED or any(s in p.parents for s in skip) or "__pycache__" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            rel = str(p.relative_to(ROOT))
            for ln in lines:
                if ln in text:
                    hits.add((rel, next((k for f, k in KNOWN_COPIES if f == rel and ln.startswith(k)), ln[:40])))
        self.assertEqual(hits - KNOWN_COPIES, set(), "正本の文を写した。写さずに正本から組む")
        self.assertEqual(KNOWN_COPIES - hits, set(), "写しが消えた。KNOWN_COPIES から行を消す")

    def test_run_tests_sentences_not_copied(self):
        """「プロジェクトのテストを回せ」の文は、行の頭を変えても文単位で写さない（行の一致だけでは写しを見落とす）"""
        sents = [s for s in RUN_TESTS.split("。") if len(s) >= MIN_LINE]
        skip = {ROOT / d for d in ("tests", "docs")}
        for f in sorted(ROOT.rglob("*.md")):
            if f != SHARED and not any(s in f.parents for s in skip):
                text = f.read_text(encoding="utf-8")
                self.assertEqual([s[:40] for s in sents if s in text], [], f.relative_to(ROOT))


class TestCompose(unittest.TestCase):
    def fix(self, **kw):
        return fixrules.fix_prompt(VALUES, **kw)

    def tdd(self, phase="fix", **kw):
        return fixrules.tdd_prompt(tdd_values(), phase, PHASE_TEXT, title=TITLE, **kw)

    def test_both_prompts_carry_the_shared_source(self):
        """種類を選ばない組み立て（全部の種類）では、正本の全文がそのまま両方に入る"""
        body = fixrules.shared()
        self.assertIn(body, self.fix())
        self.assertIn(body, self.tdd())

    def test_core_always_even_without_kinds(self):
        sec = fixrules.sections(fixrules.SHARED)
        for text in (self.fix(kinds={}), self.tdd(kinds={})):
            for i in CORE_IDS:
                self.assertIn(sec[i], text)
            self.assertNotIn(sec["evidence"], text)
            for b in KIND_BULLET.values():
                self.assertNotIn(b, text)

    def test_evidence_only_for_present_kinds(self):
        kinds = {"code": "判定 stats.py", "config": "差分 a.yaml"}
        for text in (self.fix(kinds=kinds), self.tdd(kinds=kinds)):
            for k, b in KIND_BULLET.items():
                (self.assertIn if k in kinds else self.assertNotIn)(b, text)
            got = {s["id"]: s for s in header(text)["sections"]}
            self.assertEqual(got["evidence-code"]["why"], "判定 stats.py", "選んだ理由（機械の事実）が見出しに在る")
            self.assertNotIn("evidence-docs", got)

    def test_tdd_phase_rules_only_for_the_current_phase(self):
        for phase in fixrules.PHASES:
            with self.subTest(phase):
                text = self.tdd(phase=phase)
                for p, b in PHASE_BULLET.items():
                    (self.assertIn if p == phase else self.assertNotIn)(b, text)
                self.assertIn("- この後の単位や direct の単位には", text)

    def test_path_specific_rules(self):
        fix, tdd = self.fix(), self.tdd()
        for s in ("## 修正ごとに書くこと", "## 周の全体に書くこと", "何も変えずに「済んだ」と言うな", "`plan_faces`", "`wrote_refs`"):
            self.assertIn(s, fix)
            self.assertNotIn(s, tdd)
        for s in ("## 今の段の約束", "## この輪での読み替え", "JUnit XML の書き先は作業ツリーの外", PHASE_TEXT, TITLE):
            self.assertIn(s, tdd)
            self.assertNotIn(s, fix)
        self.assertEqual(tdd.split("\n")[1], TITLE, "見出しの次が題")
        self.assertLess(tdd.index(fixrules.shared()), tdd.index(PHASE_TEXT), "今の段は決まりの後（末尾）")
        self.assertIn("- 作業ツリーの外（ホームや /tmp の設定など）を書き換えない。\n- 何も変えずに", fix, "守ることの箇条に続ける")

    def test_run_values_fill_every_hole(self):
        fix, tdd = self.fix(), self.tdd()
        for text in (fix, tdd):
            self.assertNotIn("<<", text)
            self.assertNotIn("$INPUTS", text)
            self.assertNotIn("$LOOP_PREV", text)
            self.assertNotIn("{{", text)
            self.assertNotIn("<!-- 節", text)
        for k in fixrules.FIX_VALUES:
            if VALUES[k]:
                self.assertIn(f"`{VALUES[k]}`", fix, k)
        for k in fixrules.TDD_VALUES:
            if VALUES[k]:
                self.assertIn(f"`{VALUES[k]}`", tdd, k)
        self.assertIn(f"人の方針の文書: {fixrules.EMPTY}", fix, "空の値は空と書く")

    def test_missing_value_is_an_error(self):
        with self.assertRaises(fixrules.Unfilled):
            fixrules.fix_prompt({k: v for k, v in VALUES.items() if k != "plan_file"})
        with self.assertRaises(fixrules.Unfilled):
            fixrules.fill("a <<nope>> b", {})

    def test_values_are_not_rescanned(self):
        """値の中の <<…>>・$… は字のまま（埋めた値をもう一度穴として読まない）"""
        odd = {**VALUES, "notes_file": "/x/<<plan_file>>/$INPUTS.plan_file"}
        self.assertIn("`/x/<<plan_file>>/$INPUTS.plan_file`", fixrules.fix_prompt(odd))

    def test_same_inputs_same_bytes(self):
        self.assertEqual(self.fix().encode(), self.fix().encode())
        self.assertEqual(self.fix().encode(), fixrules.fix_prompt(dict(reversed(list(VALUES.items())))).encode())
        self.assertEqual(self.tdd().encode(), self.tdd().encode())
        prior = {"delivered": {"core-fix": "0"}}
        self.assertEqual(self.fix(prior=prior, reject_file="/b/r-1.txt").encode(),
                         self.fix(prior=prior, reject_file="/b/r-1.txt").encode())
        self.assertNotEqual(self.fix(), fixrules.fix_prompt({**VALUES, "plan_file": "/other"}))

    def test_reject_line_after_the_header(self):
        """前の回の拒否の理由はファイルのパスで、見出しの次の 1 行（rolekit と同じ文。理由の文は貼らない。R44）"""
        got = self.fix(reject_file="/b/reject-accept_fix-2.txt")
        self.assertEqual(got.split("\n")[1], rolekit.REJECT_LINE.format(path="/b/reject-accept_fix-2.txt"))
        self.assertNotIn("拒まれた", self.fix())

    def test_tdd_reason_on_top(self):
        got = self.tdd(reason="- 名指しのテストが落ちない")
        head = got.split(fixrules.shared())[0]
        self.assertIn("- 名指しのテストが落ちない", head)

    def test_header_records_sections_and_why(self):
        h = header(self.fix(kinds={"code": "判定 stats.py"}))
        self.assertEqual((h["role"], h["iteration"], h["mode"]), ("fix", 1, "full"))
        self.assertEqual([s["id"] for s in h["sections"]],
                         ["fix-head", "core-fix", "evidence", "evidence-code", "core-conflict", "core-keep", "fix-keep",
                          "fix-reply"])
        self.assertTrue(all(s["sent"] and s["why"] for s in h["sections"]))
        self.assertEqual(len(h["rules_sha"]), 64)


class TestDelta(unittest.TestCase):
    """2 回目からの delta の形: 変わった物と、渡した決まりの sha256 の 1 行だけ"""

    def first(self, kinds=None):
        return fixrules.render("fix", 1, fixrules.fix_parts(VALUES, kinds), rules_file="/b/prompt-p3.fix.rules.md")

    def test_second_iteration_carries_only_what_changed(self):
        one = self.first()
        two = fixrules.render("fix", 2, fixrules.fix_parts(VALUES), prior={"delivered": one["delivered"]},
                              rules_file="/b/prompt-p3.fix.rules.md", reject_file="/b/reject-accept_fix-1.txt")
        text = two["text"]
        self.assertEqual(text.split("\n")[1], rolekit.REJECT_LINE.format(path="/b/reject-accept_fix-1.txt"))
        self.assertIn(fixrules.RULES_SAME.format(sha=one["head"]["rules_sha"], path="/b/prompt-p3.fix.rules.md"), text)
        for sec in fixrules.sections(fixrules.SHARED).values():
            self.assertNotIn(sec, text)
        h = header(text)
        self.assertEqual((h["mode"], h["iteration"]), ("delta", 2))
        self.assertFalse(any(s["sent"] for s in h["sections"]))
        self.assertLess(len(text), len(one["text"]) // 5)

    def test_added_kind_is_sent_once(self):
        one = self.first(kinds={"code": "判定 stats.py"})
        kinds = {"code": "判定 stats.py", "docs": "差分 README.md"}
        two = fixrules.render("fix", 2, fixrules.fix_parts(VALUES, kinds), prior={"delivered": one["delivered"]},
                              rules_file="/r.md")
        self.assertIn(KIND_BULLET["docs"], two["text"])
        self.assertNotIn(KIND_BULLET["code"], two["text"])
        self.assertIn("決まりに下の節を足した", two["text"])
        self.assertEqual([s["id"] for s in header(two["text"])["sections"] if s["sent"]], ["evidence-docs"])

    def test_tdd_delta_keeps_the_current_phase(self):
        one = fixrules.tdd_render(tdd_values(), "route", "## この段ですること\n\n振れ", title="# 1")
        two = fixrules.tdd_render(tdd_values(), "test", PHASE_TEXT, title="# 2", reason="- 落ちない",
                                  prior={"delivered": one["delivered"]}, rules_file="/r.md")["text"]
        for s in ("# 2", "- 落ちない", PHASE_BULLET["test"], PHASE_TEXT, "決まりは、この会話で前の回までに渡した物"):
            self.assertIn(s, two)
        self.assertNotIn(fixrules.sections(fixrules.SHARED)["core-fix"], two)
        self.assertNotIn(PHASE_BULLET["route"], two)


class TestVariants(unittest.TestCase):
    """支度の節が並べて書く 2 つの形と控え（prompt_file は full の写し。1 回目の delta は full と同じ）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        judgment = self.dir / "judgment.json"
        judgment.write_text(json.dumps({"units": [
            {"key": "stats.py mean: 分母", "class_query": {"how": {"paths": ["stats.py"]}}},
            {"key": "README.md: 古い説明", "class_query": {"how": {"paths": ["docs/*.md"]}}},
            {"key": "defer.yaml: 後回し"}]}, ensure_ascii=False), encoding="utf-8")
        self.values = {**VALUES, "judgment_file": str(judgment),
                       "open_units": json.dumps(["stats.py mean: 分母", "README.md: 古い説明"], ensure_ascii=False)}
        self.prompt = self.dir / "prompt-p3.fix.md"

    def write(self, n, reject=""):
        def build(kinds, prior, rules_file):
            return fixrules.render("fix", n, fixrules.fix_parts(self.values, kinds), prior=prior, rules_file=rules_file,
                                   reject_file=reject)
        return fixrules.write_variants(self.prompt, None, self.values, build, n)

    def files(self):
        b = fixrules.beside
        return (b(self.prompt, fixrules.FULL).read_text(encoding="utf-8"), b(self.prompt, fixrules.DELTA).read_text(encoding="utf-8"),
                json.loads(b(self.prompt, fixrules.VARIANTS).read_text(encoding="utf-8")))

    def test_first_iteration_delta_is_full_and_prompt_is_full(self):
        got = self.write(1)
        full, delta, side = self.files()
        self.assertEqual(delta, full)
        self.assertEqual(self.prompt.read_text(encoding="utf-8"), full, "既定は full（包みが無い起動）")
        self.assertEqual(side, got)
        self.assertEqual(set(side), {"full", "delta", "rules_sha", "iteration", "delta_is_full", "why", "sections"})
        self.assertEqual((side["iteration"], side["delta_is_full"]), (1, True))
        self.assertEqual(side["full"], str(fixrules.beside(self.prompt, fixrules.FULL)))
        rules = fixrules.beside(self.prompt, fixrules.RULES).read_text(encoding="utf-8")
        self.assertEqual(fixrules._sha(rules.rstrip("\n")), side["rules_sha"])

    def test_kinds_from_open_units_only(self):
        """判定の義務の単位のパス（class_query の paths と key の中のパス）から種類を選ぶ。義務でない単位（defer）は見ない"""
        self.write(1)
        full, _, side = self.files()
        self.assertIn(KIND_BULLET["code"], full)
        self.assertIn(KIND_BULLET["docs"], full)
        self.assertNotIn(KIND_BULLET["config"], full)
        self.assertNotIn(KIND_BULLET["prompts"], full)
        why = {s["id"]: s["why"] for s in side["sections"]}
        self.assertIn("stats.py", why["evidence-code"])

    def test_second_iteration_delta_with_sha_and_full_default(self):
        self.write(1)
        full1, _, side1 = self.files()
        self.write(2, reject="/b/reject-accept_fix-1.txt")
        full2, delta2, side2 = self.files()
        self.assertEqual(self.prompt.read_text(encoding="utf-8"), full2, "既定は full のまま")
        self.assertNotEqual(delta2, full2)
        self.assertIn(side1["rules_sha"], delta2)
        self.assertIn(str(fixrules.beside(self.prompt, fixrules.RULES)), delta2)
        self.assertIn(rolekit.REJECT_LINE.format(path="/b/reject-accept_fix-1.txt"), delta2)
        self.assertIn(fixrules.sections(fixrules.SHARED)["core-fix"], full2, "full は毎回全部")
        self.assertNotIn(fixrules.sections(fixrules.SHARED)["core-fix"], delta2)
        self.assertEqual((side2["iteration"], side2["delta_is_full"]), (2, False))
        self.assertEqual(header(delta2)["mode"], "delta")
        self.assertEqual(header(full2)["mode"], "full")

    def test_unknown_kinds_fall_back_to_all(self):
        self.values["judgment_file"] = str(self.dir / "missing.json")
        self.write(1)
        full, _, side = self.files()
        for b in KIND_BULLET.values():
            self.assertIn(b, full)
        self.assertTrue(all("全部載せる" in s["why"] for s in side["sections"] if s["id"].startswith("evidence-")))


class TestKinds(unittest.TestCase):
    def test_kind_of(self):
        for path, kind in (("README.md", "docs"), ("docs/guide.rst", "docs"), ("blk-x/commands/fix.md", "prompts"),
                           ("CLAUDE.md", "prompts"), ("skills/a/SKILL.md", "prompts"), ("a/b.yaml", "config"),
                           (".github/workflows/ci.yml", "config"), ("pyproject.toml", "config"), ("stats.py", "code"),
                           ("src/x.ts", "code"), ("*.py", "code"), ("docs/**", None), ("LICENSE", None)):
            with self.subTest(path):
                self.assertEqual(fixrules.kind_of(path), kind)

    def test_select_kinds_names_the_source(self):
        got = fixrules.select_kinds({"判定": ["stats.py"], "差分": ["README.md", "stats.py"]})
        self.assertEqual(set(got), {"code", "docs"})
        self.assertIn("判定 stats.py", got["code"])
        self.assertIn("差分 README.md", got["docs"])
        self.assertEqual(set(fixrules.select_kinds({"判定": ["LICENSE"], "差分": []})), set(fixrules.KINDS))


class TestRoleNodes(unittest.TestCase):
    def test_roles_read_the_composed_file(self):
        """2 つの役の節の指示は 1 行（組んだ指示書を Read で読め）。手書きの commands/ は無い"""
        for rid, prep in (("fix", "fix-prep"), ("tdd", "tdd-prep")):
            with self.subTest(rid):
                n = find_node(block()["nodes"], rid)
                self.assertNotIn("command", n)
                self.assertEqual(n["depends_on"], [prep])
                self.assertNotIn("\n", n["prompt"].strip())
                self.assertIn(f"`${prep}.output.prompt_file` を Read で", n["prompt"])
                self.assertNotRegex(n["prompt"], r"\$(INPUTS|LOOP_PREV)")
                mark = node_marker.parse(n["output_format"]["description"])
                self.assertEqual(mark["name"], rid, "包みが節の名で会話を分け、続きの起動で形を選ぶ")
        self.assertFalse((BLK / "commands").exists())

    def test_prep_nodes_pass_the_run_values(self):
        nodes = block()["nodes"]
        fp = find_node(nodes, "fix-prep")
        self.assertEqual(fp["script"], "fix_prep")
        self.assertEqual(fp["with"], {"judgment_file": "$INPUTS.judgment_file", "open_units": "$INPUTS.open_units",
                                      "plan_file": "$INPUTS.plan_file", "policy_path": "$INPUTS.policy_path",
                                      "notes_file": "$INPUTS.notes_file", "summary_file": "$tdd-start.output.summary_file",
                                      "pass": "first"})
        self.assertEqual(set(fp["with"]) - {"pass"}, set(fixrules.FIX_VALUES))
        self.assertIn("variants_file", fp["output_format"]["required"])
        tp = find_node(nodes, "tdd-prep")
        self.assertEqual(tp["with"], {"state_file": "$tdd-start.output.state_file", "judgment_file": "$INPUTS.judgment_file",
                                      "plan_file": "$INPUTS.plan_file", "policy_path": "$INPUTS.policy_path",
                                      "notes_file": "$INPUTS.notes_file"})
        self.assertEqual(set(tp["with"]) - {"state_file"}, set(fixrules.TDD_VALUES) - {"open_units"},
                         "義務の単位は輪の状態が持つ")
        loop = find_node(nodes, "fix-loop")["loop_group"]
        self.assertEqual([n["id"] for n in loop["nodes"]], ["fix-prep", "fix", "fix-accept"])


if __name__ == "__main__":
    unittest.main()
