"""修正の決まりの正本（.shared/core/writerules/common.md）と、2 つの修正役の指示書の組み立て（blk-fix/lib/fixrules.py。裁定 R65）の検査。

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
import os
import pathlib
import re
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
import rulebook  # noqa: E402

SHARED = CORE / "writerules" / "common.md"
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
    (".shared/borrow/unattended.md", "- **義務の単位の行き先**"),
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
        for w in ("`c1-1`", "`/b/r1/conflicts.json`", "fix_test_scope", "fix_code_as", "ask_human", "裁定の決まり"):
            self.assertIn(w, ruler)

    def test_questions_for_the_human_go_to_the_conflict_exit(self):
        """人への問い・人にしか決められない疑いは食い違いの出口（which_is_right unknown → 裁定役 → ask_human）へ、rejudge_requested は
        判定のフレーミングへの異議だけ（finaltests の懸念 1: 読み替えが人への問いを rejudge_requested に書かせ、判定への異議と
        混ぜていた。包み無しの run はそこで再審できずに止まる）。組んだ修正役・TDD の輪の役の指示書の両方が言い、正本と読み替えと
        README に、問い・疑い・方針のぶつかりを rejudge_requested へ送る文が残らない"""
        ask = "人に聞きたいこと・人にしか決められない疑いの行き先はここ"
        only = "`rejudge_requested` は判定のフレーミング（単位の切り方・根の見立て・disposition）への異議だけの欄"
        sec = fixrules.sections(fixrules.SHARED)
        self.assertIn(ask, sec["core-conflict"])
        self.assertIn(only, sec["core-fix"])
        self.assertIn("`which_is_right` を unknown", sec["core-conflict"])
        old = re.compile(r"(疑い|疑いの理由|何が要るか|ぶつかるか|人に聞きたいこと)(は|を)\s*`rejudge_requested`\s*に書")
        prompts = {"fix": fixrules.fix_prompt(VALUES, kinds={}),
                   "tdd": fixrules.tdd_prompt({k: VALUES[k] for k in fixrules.TDD_VALUES}, "fix", "## 今の段", title="# t", kinds={})}
        for name, text in prompts.items():
            with self.subTest(name):
                self.assertIn(ask, text)
                self.assertIn(only, text)
                self.assertEqual(old.findall(text), [])
        for rel in (".shared/borrow/unattended.md", "README.md"):
            with self.subTest(rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                self.assertEqual(old.findall(text), [], "人への問い・疑いを rejudge_requested へ送る文が残った")
                self.assertIn("which_is_right", text)
                self.assertIn("needs_context", text)

    def test_every_rules_file_is_cut_into_sections(self):
        for name, ids in ((fixrules.DIRECT, ["fix-head", "fix-keep", "fix-reply"]), (fixrules.RULER, ["ruler-head", "ruler-reply"]),
                          (fixrules.PRINCIPLES, ["principles"]), (fixrules.BRIEF, ["brief-canon"]),
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

    def test_brief_rule_reaches_fixer_and_tdd_only(self):
        """brief の決まり（brief-canon）は修正役と TDD の役の頭の次にだけ載る。裁定役と手直しの役には載せない"""
        fix = [pid for pid, _, _ in fixrules.fix_parts(VALUES)]
        tdd = [pid for pid, _, _ in fixrules.tdd_parts(tdd_values())]
        self.assertEqual(fix[fix.index("fix-head") + 1], "brief-canon")
        self.assertEqual(tdd[tdd.index("tdd-head") + 1], "brief-canon")
        ruler = [pid for pid, _, _ in fixrules.ruler_parts({k: "/b/x" for k in fixrules.RULER_VALUES})]
        self.assertNotIn("brief-canon", ruler)
        refix = [pid for pid, _, _ in refixrules().parts(1, {"brief_file": "", "diff_file": "", "policy_path": ""})]
        self.assertNotIn("brief-canon", refix)

    def test_brief_rule_wins_and_names_the_exit(self):
        """brief が要求の正本で判定は背景。誤りと見たら食い違いの申し出で返し、rewrite_tests は最後の人の関所に並ぶ。
        brief の無い run は判定のファイルが正本のまま"""
        sec = fixrules.sections(fixrules.BRIEF)["brief-canon"]
        for w in ("要求の正本", "brief が勝つ", "背景", "食い違いの申し出", "rewrite_tests", "最後の人の関所", "判定のファイルが正本"):
            self.assertIn(w, sec)

    def test_brief_rule_one_voice_with_brief_background(self):
        """brief と判定が食い違えば brief どおり直す（止めない）。brief そのものを誤りと見た時だけ申し出る。brief のファイルの背景の
        見出し（planbrief.BACKGROUND）も同じ 1 つの決まりを言う"""
        import planbrief
        sec = fixrules.sections(fixrules.BRIEF)["brief-canon"]
        self.assertIn("brief が勝つ", planbrief.BACKGROUND)
        self.assertIn("brief が誤りと見たら申し出よ", planbrief.BACKGROUND)
        self.assertNotIn("自分で解かずに", planbrief.BACKGROUND)
        self.assertIn("単位の切り方（unit）は判定どおり。何をどう直すかは brief", sec)

    def test_brief_rule_names_ruling_and_range_exit(self):
        """裁定を受けた単位は裁定の範囲で brief に勝つ。範囲の申し出の which_is_right の決め方を言う"""
        sec = fixrules.sections(fixrules.BRIEF)["brief-canon"]
        self.assertIn("裁定を受けた単位は、裁定の範囲で裁定が brief に勝つ", sec)
        self.assertIn("範囲の外が要るなら request", sec)
        self.assertIn("query（`correct_lines` 付き）", sec)

    def test_brief_rule_names_scope(self):
        """brief の allowed_paths の外と out_of_scope は変えない。範囲の外が要るなら食い違いの申し出で返す（依頼 218）"""
        sec = fixrules.sections(fixrules.BRIEF)["brief-canon"]
        for w in ("allowed_paths", "out_of_scope", "範囲の外", "食い違いの申し出"):
            self.assertIn(w, sec)

    def test_rewrite_tests_is_an_exception_to_frozen_tests(self):
        """修正役の頭の「テストのファイルは変えるな」の例外に、修正案の rewrite_tests の名指しが並ぶ"""
        head = fixrules.sections(fixrules.DIRECT)["fix-head"]
        self.assertIn("修正案の `rewrite_tests` の名指しと、裁定 fix_test_scope の範囲だけは例外", head)

    def test_judgment_is_background_in_heads(self):
        """修正役・TDD の役の頭の判定のファイルの行は「全部読め」でなく背景"""
        for name, sid in ((fixrules.DIRECT, "fix-head"), (fixrules.TDD, "tdd-head")):
            line = next(ln for ln in fixrules.sections(name)[sid].splitlines() if "<<judgment_file>>" in ln)
            self.assertNotIn("全部読め", line)
            self.assertIn("背景", line)

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
                         ["fix-head", "brief-canon", "core-fix", "evidence", "evidence-code", "core-conflict", "core-keep",
                          "fix-keep", "fix-reply"])
        self.assertTrue(all(s["sent"] and s["why"] for s in h["sections"]))
        self.assertEqual(len(h["rules_sha"]), 64)

    def test_tdd_brief_after_title_before_reason(self):
        """TDD の役の指示書の頭: 題 → brief の節 → 前の回に拒んだ理由"""
        text = fixrules.tdd_prompt(tdd_values(), "fix", PHASE_TEXT, title=TITLE, reason="R", brief="## 要求の正本（brief）\n\nX")
        self.assertLess(text.index(TITLE), text.index("## 要求の正本（brief）"))
        self.assertLess(text.index("## 要求の正本（brief）"), text.index("前の回の返答を機械が拒んだ理由"))


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

    def test_canon_is_a_prompt(self):
        """正本の置き場を移しても、正本を直す run の証拠は指示書の節（描いて穴が埋まる・写しが揃う）のまま"""
        self.assertEqual(fixrules.kind_of(str(SHARED.relative_to(ROOT.parent))), "prompts")

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
                                      "base_rev": "$INPUTS.base_rev", "pass": "first"})
        # base_rev は指示書の run の値でなく、修正の形 g1 の審査役の型の [BASE_SHA]（fixrules.g1_values）
        self.assertEqual(set(fp["with"]) - {"pass", "base_rev"}, set(fixrules.FIX_VALUES))
        self.assertIn("variants_file", fp["output_format"]["required"])
        tp = find_node(nodes, "tdd-prep")
        self.assertEqual(tp["with"], {"state_file": "$tdd-start.output.state_file", "judgment_file": "$INPUTS.judgment_file",
                                      "plan_file": "$INPUTS.plan_file", "policy_path": "$INPUTS.policy_path",
                                      "notes_file": "$INPUTS.notes_file"})
        self.assertEqual(set(tp["with"]) - {"state_file"}, set(fixrules.TDD_VALUES) - {"open_units"},
                         "義務の単位は輪の状態が持つ")
        loop = find_node(nodes, "fix-loop")["loop_group"]
        self.assertEqual([n["id"] for n in loop["nodes"]], ["fix-prep", "fix", "fix-accept"])



class TestCopyRejectOfOneUnit(unittest.TestCase):
    """修正の受け付け（blk-fix の fix-accept の accept_fix）: 閉鎖の数え合わせの食い違いは前段の表（unitrows.take）が記録し、
    写しの 4 つの拒否が発火しないように返答を揃えるので、役に返らない。それでも写しの受け付け（recount.accept_fix）が 1 単位を
    名指して拒めば（数え合わせの外の閉鎖の柵など）、輪の 1・2 回目は役に返し、3 回目は返答全体を拒んで盤面を止めずに、その単位
    だけを ask_human に裁いて止め（conflict.park。最後の人の関所へ運ぶ）、残りの単位の直しを受ける。盤面・git は使わない
    （写しの受け付けと盤面を mock にする）"""

    MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
    CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"

    def setUp(self):
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("blk_fix_accept_script", BLK / "scripts" / "accept.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.parked = []
        patches = [
            mock.patch.object(self.mod.tddloop, "frozen_problems", return_value=[]),
            mock.patch.object(self.mod, "check_writes", side_effect=lambda reply, *a, **k: {"problems": [], "reply": reply}),
            mock.patch.object(self.mod, "take_conflicts", side_effect=lambda reply, *a, **k: (reply, None)),
            mock.patch.object(self.mod, "fix_unit_keys", return_value=None),
            mock.patch.object(self.mod, "check_tests", return_value=([], "")),
            mock.patch.object(self.mod.fixgates, "problems", return_value=[]),   # 事後の関門の束（test_fix_gates が見る）
            mock.patch.object(self.mod.fixgates, "skipped", return_value=[]),
            mock.patch.object(self.mod.recount, "accept_fix", side_effect=self.recount),
            mock.patch.object(self.mod.entry, "open_board", return_value=mock.MagicMock()),
            mock.patch.object(self.mod.writes, "trace"),
            mock.patch.object(self.mod.conflict, "waiting", return_value=[]),   # 案の直しを待つ単位は無い（控えない）
            # 1 回目に受け付けた返答の控えは無い（1 回目の修正の段。盤面は mock なので控えを読ませない）
            mock.patch.object(self.mod.conflict, "held_reply", return_value=(None, pathlib.Path("/b/r1/fix-held-reply.json"))),
            mock.patch.object(self.mod, "_parked_reply", return_value=None),   # 申し出の回の控えも無い
            mock.patch.object(self.mod.conflict, "park", side_effect=lambda b, rows, **k: self.parked.append((rows, k))),
            mock.patch.object(self.mod.conflict, "write_rulings"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def recount(self, reply, board, base_rev, repo, commit=True):
        """写しの受け付けの代わり: CLAMP の行が在れば、写しと同じ文の形（unit_key の頭 60 字: …）で閉鎖の柵（数え合わせの外）で拒む。
        申告の sites が 1 件を超える行は、写しの数え合わせ（母数 1）と同じく拒む（前段が揃えていれば発火しない）"""
        keys = [c["unit_key"] for c in reply["changes"]]
        over = [c["unit_key"] for c in reply["changes"] if len((c.get("closure") or {}).get("sites") or []) > 1]
        if over:
            return {"ok": False, "changes": [], "reason": f"{over[0][:60]}: 申告の site が母数 1 を超える"}
        if self.CLAMP in keys:
            return {"ok": False, "changes": [],
                    "reason": f"{self.CLAMP[:60]}: 閉鎖の実証で赤を一度も見ていないのに fix_closure=clean"}
        return {"ok": True, "reason": "", "changes": [{"unit_key": k, "files": ["stats.py"], "what": "直した"} for k in keys]}

    def run_accept(self, iteration):
        from unittest import mock
        reply = {"changes": [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                             {"unit_key": self.CLAMP, "files": ["stats.py"], "what": "上限の枝を直した"}]}
        with mock.patch.dict("os.environ", {"INPUTS_ITERATION": iteration, "INPUTS_TDD_STATE": "", "INPUTS_PASS": "first"}):
            return self.mod.with_done(self.mod.accept_fix(reply, pathlib.Path("/b"), "", pathlib.Path("/r")))

    def test_count_mismatch_is_recorded_not_sent_back(self):
        # 申告の sites が母数を超える食い違いは、前段（unitrows.take の本体 build）が表に記録して sites を切るので、写しは拒まない
        from unittest import mock
        how = {"patterns": ["return lo"], "paths": ["stats.py"], "count": "lines", "fixed": True}
        rows = []

        def take(reply, b, repo):
            out, got = self.mod.unitrows.build(reply["changes"], {self.MEAN: {"how": how, "counts": "defects"}},
                                               count=lambda h, at_rev: (1, "") if at_rev else (0, ""),
                                               blank=lambda s, n: len((s or "").strip()) < n)
            rows.extend(got)
            return {**reply, "changes": out}, got
        reply = {"changes": [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した",
                              "closure": {"sites": [{"site": "a", "red_seen": True}, {"site": "b"}]}}]}
        with mock.patch.object(self.mod.unitrows, "take", side_effect=take), \
                mock.patch.object(self.mod.querytest, "save_closure", return_value="/b/r1/fix-unit-rows.json"), \
                mock.patch.dict("os.environ", {"INPUTS_ITERATION": "1", "INPUTS_TDD_STATE": "", "INPUTS_PASS": "first"}):
            got = self.mod.with_done(self.mod.accept_fix(reply, pathlib.Path("/b"), "", pathlib.Path("/r")))
        self.assertIs(got["ok"], True, got)
        self.assertTrue(any("超える" in d for d in rows[0]["discrepancies"]), rows)
        self.assertEqual(self.parked, [])

    def test_first_and_second_copy_reject_go_back_to_role(self):
        for it in ("1", "2"):
            with self.subTest(iteration=it):
                got = self.run_accept(it)
                self.assertEqual((got["ok"], got["done"]), (False, False))
                self.assertIn(self.CLAMP[:20], got["reason"])
        self.assertEqual(self.parked, [])

    def split_reply(self):
        """2 つの単位が別のファイルを触った返答（共有のファイルが在ると単位に結べず、返答全体を拒む）"""
        return {"changes": [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                            {"unit_key": self.CLAMP, "files": ["clamp.py"], "what": "上限の枝を直した"}]}

    def accept_split(self, iteration):
        from unittest import mock
        with mock.patch.dict("os.environ", {"INPUTS_ITERATION": iteration, "INPUTS_TDD_STATE": "", "INPUTS_PASS": "first"}):
            return self.mod.with_done(self.mod.accept_fix(self.split_reply(), pathlib.Path("/b"), "", pathlib.Path("/r")))

    def test_third_reject_of_one_unit_parks_it_by_the_bound_path(self):
        # 申告と数え直しの食い違いは前段の表（unitrows）に記録して拒否にしない。それでも写しの受け付けが 1 単位を名指して拒めば、
        # 3 回目はほかの拒否と同じ道（changes[].files か unit_key で単位に結ぶ）でその単位だけを戻して止める
        from unittest import mock
        with mock.patch.object(self.mod, "revert_units", return_value="/b/r1/fix-parked-1.patch") as revert:
            got = self.accept_split("3")
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        self.assertEqual([c["unit_key"] for c in got["changes"]], [self.MEAN], "止めた単位は changes から外す")
        rows = [r for rs, _ in self.parked for r in rs]
        self.assertEqual([r["unit_key"] for r in rows], [self.CLAMP])
        rulings = [k.get("ruling") or {} for _, k in self.parked]
        self.assertEqual([r.get("decision") for r in rulings], ["ask_human"])
        self.assertIn("fix_closure=clean", rulings[0].get("text", ""), "人に回す裁定の文に、単位に結んだ拒否の文を載せる")
        revert.assert_called_once()
        self.assertIn(self.CLAMP, repr(revert.call_args), "止めた単位の直しを作業ツリーから戻す")
        self.assertNotIn(self.MEAN, repr(revert.call_args), "通した単位の直しは戻さない")

    def test_third_park_then_other_reject_undoes_the_park(self):
        # 止めた後の通し直しがどの単位にも結べない文で拒めば、止めた単位の直し・食い違いの控え・裁定の文を止める前に戻す
        # （拒否では盤面を前のままにする）
        from unittest import mock
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = pathlib.Path(tmp.name)
        (work / self.mod.conflict.RULINGS_FILE).write_text("前の裁定\n", encoding="utf-8")
        b = mock.MagicMock()
        b.work.side_effect = lambda name: work / name

        def park(b_, rows, **k):
            (work / self.mod.conflict.FILE).write_text(json.dumps({"items": rows}, ensure_ascii=False), encoding="utf-8")

        def recount(reply, *a, **k):
            if self.CLAMP in [c["unit_key"] for c in reply["changes"]]:
                return self.recount(reply, *a, **k)
            return {"ok": False, "changes": [], "reason": "閉鎖の実証で赤を一度も見ていないのに fix_closure=clean"}

        with mock.patch.object(self.mod.entry, "open_board", return_value=b), \
                mock.patch.object(self.mod.conflict, "park", side_effect=park), \
                mock.patch.object(self.mod.conflict, "write_rulings",
                                  side_effect=lambda b_: (work / self.mod.conflict.RULINGS_FILE).write_text("止めた\n", encoding="utf-8")), \
                mock.patch.object(self.mod.recount, "accept_fix", side_effect=recount), \
                mock.patch.object(self.mod, "revert_units", return_value="/b/r1/fix-parked-1.patch"), \
                mock.patch.object(self.mod, "unrevert_units") as unrevert:
            got = self.accept_split("3")
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.assertFalse((work / self.mod.conflict.FILE).exists(), "止める前に無かった食い違いの控えは消す")
        self.assertEqual((work / self.mod.conflict.RULINGS_FILE).read_text(encoding="utf-8"), "前の裁定\n")
        b.trace.assert_any_call(self.mod.PARK_UNDONE_OP, node=self.mod.recount.ROLE, unit_keys=[self.CLAMP])
        unrevert.assert_called_once()
        self.assertIn(self.CLAMP, repr(unrevert.call_args), "戻した単位の直しを作業ツリーに戻す")

    def test_count_mismatch_phrase_matching_is_gone(self):
        # 閉鎖は前段の表（unitrows）が数え直しで決め、写しの拒否の文の句を照らして後から単位を外す継ぎ目は持たない
        src = (BLK / "scripts" / "accept.py").read_text(encoding="utf-8")
        for name in ("COUNT_MISMATCH", "mismatched_unit", "park_mismatched_units", "MISMATCH_PARKED"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(self.mod, name))
                self.assertNotIn(name, src)


class TestQueryConflictExit(unittest.TestCase):
    """判定者の問い（class_query）が直した後の正しい形にも当たる、と申し出る出口（which_is_right: query。直した後の正しい行を
    correct_lines に写す）と、問いを置き換える裁定（replace_query。新しい問いを hits・misses と申し出の correct_lines で機械が試す）。
    盤面は使わない（conflict.problems と ruling.problems を直に呼ぶ）"""

    KEY = "stats.py clamp: 上限を超えた値に lo を返す"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = pathlib.Path(tmp.name)
        (self.repo / "stats.py").write_text("def clamp(x, lo, hi):\n    if x > hi:\n        return lo\n    return x\n",
                                            encoding="utf-8")
        (self.repo / "test_stats.py").write_text("def test_clamp():\n    assert clamp(11, 0, 10) == 10\n", encoding="utf-8")

    def item(self, **extra):
        return {"unit_key": self.KEY, "between": ["stats.py:3", "test_stats.py:2"],
                "why_both_cannot_hold": "判定者の問い return lo は下限の枝の正しい return lo にも当たり、直しても件数が減らない",
                "which_is_right": "query", "kind": "query_hits_fixed", **extra}

    def test_query_conflict_needs_correct_lines(self):
        import conflict
        self.assertIn("query", conflict.WHICH)
        errs = conflict.problems([self.item()], repo=self.repo, board_dir=self.repo, owed={self.KEY})
        self.assertTrue(any("correct_lines" in e for e in errs), errs)

    def test_replace_query_ruling_is_tried_on_examples(self):
        import conflict
        import ruling
        self.assertIn("replace_query", conflict.DECISIONS)
        todo = {"c1-1": {"id": "c1-1", **self.item(correct_lines=["        return lo"])}}

        def reply(how, hits, misses):
            return {"rulings": [{"id": "c1-1", "decision": "replace_query", "limits": [],
                                 "text": "上限の枝だけに当たる問いに置き換える（下限の枝の return lo は正しい形）",
                                 "query": {"how": how, "counts": "defects", "hits": hits, "misses": misses}}]}

        good = {"patterns": ["return lo  # hi"], "fixed": True, "paths": ["stats.py"], "count": "lines"}
        broad = {"patterns": ["return lo"], "fixed": True, "paths": ["stats.py"], "count": "lines"}
        self.assertEqual(ruling.problems(reply(good, ["        return lo  # hi"], ["        return hi"]), todo, self.repo), [],
                         "hits に当たり、misses と申し出の correct_lines に当たらない問いは通す")
        errs = ruling.problems(reply(broad, ["        return lo"], ["        return hi"]), todo, self.repo)
        self.assertTrue(any("correct_lines" in e for e in errs), f"申し出の正しい行にも当たる問いは拒む: {errs}")
        errs = ruling.problems(reply(good, ["        return lo  # hi"], ["        return lo  # hi"]), todo, self.repo)
        self.assertTrue(any("misses" in e for e in errs), f"misses に当たる問いは拒む: {errs}")


class TestThirdRejectParksBoundUnit(unittest.TestCase):
    """修正の受け付けの輪の 3 回目: 数え合わせ以外の拒否（凍ったテストの書き換え・元で赤でなかった試験の赤）も、changes[].files で
    ちょうど 1 単位に結べれば、その単位だけを ask_human に止め（conflict.park）、その単位の直しを作業ツリーから戻し（revert_units）、
    残りの単位で受け付けを通し直す。どの単位にも結べない拒否は今までどおり返答全体を拒んで輪を抜ける（assert-changed が止める）。
    盤面・git は使わない（検査・数え直し・戻しを mock にする）"""

    MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
    CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"
    RED = ("受け付けが走らせた選んだ試験（-k clamp）で、元で赤でなかった試験が赤: ['test_clamp.py::test_clamp_above_range']"
           "（1 件。ログ /b/suite.log）")
    FROZEN = "TDD の輪で凍ったテストのファイルを書き換えた: ['test_clamp.py']（輪で直した単位のテストは変えない）"

    def setUp(self):
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("blk_fix_accept_script", BLK / "scripts" / "accept.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.parked = []
        self.frozen = [[]]
        self.tests = [([], "")]
        self.gates = [[]]   # 事後の関門の束の行（回ごと。最後の 1 つを繰り返す）
        self.revert = mock.MagicMock(return_value="/b/r1/fix-parked-1.patch")
        patches = [
            mock.patch.object(self.mod.tddloop, "frozen_problems", side_effect=lambda *a, **k: self.frozen.pop(0)
                              if len(self.frozen) > 1 else self.frozen[0]),
            mock.patch.object(self.mod, "check_writes", side_effect=lambda reply, *a, **k: {"problems": [], "reply": reply}),
            mock.patch.object(self.mod, "take_conflicts", side_effect=lambda reply, *a, **k: (reply, None)),
            mock.patch.object(self.mod, "fix_unit_keys", return_value=None),
            mock.patch.object(self.mod, "check_tests", side_effect=lambda *a, **k: self.tests.pop(0)
                              if len(self.tests) > 1 else self.tests[0]),
            mock.patch.object(self.mod.fixgates, "problems", side_effect=lambda *a, **k: self.gates.pop(0)
                              if len(self.gates) > 1 else self.gates[0]),
            mock.patch.object(self.mod.fixgates, "skipped", return_value=[]),
            mock.patch.object(self.mod.recount, "accept_fix",
                              side_effect=lambda reply, *a, **kw: {"ok": True, "reason": "", "changes": [
                                  {k: c[k] for k in ("unit_key", "files", "what")} for c in reply["changes"]]}),
            mock.patch.object(self.mod.entry, "open_board", return_value=mock.MagicMock()),
            mock.patch.object(self.mod.writes, "trace"),
            mock.patch.object(self.mod.conflict, "waiting", return_value=[]),   # 案の直しを待つ単位は無い（控えない）
            # 1 回目に受け付けた返答の控えは無い（1 回目の修正の段。盤面は mock なので控えを読ませない）
            mock.patch.object(self.mod.conflict, "held_reply", return_value=(None, pathlib.Path("/b/r1/fix-held-reply.json"))),
            mock.patch.object(self.mod, "_parked_reply", return_value=None),   # 申し出の回の控えも無い
            mock.patch.object(self.mod.conflict, "park", side_effect=lambda b, rows, **k: self.parked.append((rows, k))),
            mock.patch.object(self.mod.conflict, "write_rulings"),
            mock.patch.object(self.mod, "revert_units", self.revert, create=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_accept(self, iteration):
        from unittest import mock
        reply = {"changes": [{"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"},
                             {"unit_key": self.CLAMP, "files": ["clamp.py", "test_clamp.py"], "what": "上限の枝を直した"}]}
        with mock.patch.dict("os.environ", {"INPUTS_ITERATION": iteration, "INPUTS_TDD_STATE": "/b/tdd.json",
                                            "INPUTS_PASS": "first"}):
            return self.mod.with_done(self.mod.accept_fix(reply, pathlib.Path("/b"), "", pathlib.Path("/r")))

    def assert_parked_clamp(self, got):
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        self.assertEqual([c["unit_key"] for c in got["changes"]], [self.MEAN], "止めた単位は changes から外し、ほかの単位は通す")
        rows = [r for rs, _ in self.parked for r in rs]
        self.assertEqual([r["unit_key"] for r in rows], [self.CLAMP])
        self.assertEqual([(k.get("ruling") or {}).get("decision") for _, k in self.parked], ["ask_human"])
        self.revert.assert_called_once()
        self.assertIn(self.CLAMP, repr(self.revert.call_args), "止めた単位の直しを作業ツリーから戻す")
        self.assertNotIn(self.MEAN, repr(self.revert.call_args), "通した単位の直しは戻さない")

    def test_third_red_test_bound_to_one_unit_parks_only_that_unit(self):
        self.tests = [([self.RED], ""), ([], "")]
        self.assert_parked_clamp(self.run_accept("3"))

    def test_third_frozen_edit_bound_to_one_unit_parks_only_that_unit(self):
        self.frozen = [[self.FROZEN], []]
        self.assert_parked_clamp(self.run_accept("3"))

    def test_third_battery_row_bound_to_one_unit_parks_only_that_unit(self):
        """事後の関門の束の行（計画 220 Task 4）も、名指しのファイルで 1 単位に結べれば、その単位だけを止めて残りを通す"""
        self.gates = [[{"gate": "test_edits", "id": "test_clamp.py::test_clamp_above_range", "detail": "名指しの外"}], []]
        self.assert_parked_clamp(self.run_accept("3"))

    def test_third_battery_rows_of_two_units_park_both(self):
        """束の行は行ごとの文で渡るので、別の単位を指す 2 行はそれぞれの単位に結んで両方を止める（red_green は項目の
        unit_key で結ぶ。名指しのテストのファイルが changes に無くても）。1 回目の拒否の文には 2 行とも並ぶ"""
        rows = [{"gate": "red_green", "id": "test_mean.py::test_mean_of_two", "detail": "base で緑", "unit_keys": [self.MEAN]},
                {"gate": "test_edits", "id": "test_clamp.py::test_clamp_above_range", "detail": "名指しの外", "unit_keys": []}]
        self.gates = [rows]
        first = self.run_accept("1")
        self.assertEqual((first["ok"], first["done"]), (False, False), first)
        for w in ("test_mean.py::test_mean_of_two", "test_clamp.py::test_clamp_above_range"):
            self.assertIn(w, first["reason"])
        self.gates = [rows, []]
        got = self.run_accept("3")
        self.assertEqual((got["ok"], got["done"], got["changes"]), (True, True, []), got)
        self.assertEqual(sorted(r["unit_key"] for rs, _ in self.parked for r in rs), sorted([self.MEAN, self.CLAMP]))
        self.revert.assert_called_once()

    def test_unbound_third_reject_still_gives_up(self):
        self.tests = [(["受け付けが走らせた一式（環境）で、元で赤でなかった試験が赤: ['test_env.py::test_x']（1 件）"], "")]
        got = self.run_accept("3")
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.assertEqual(self.parked, [])
        self.revert.assert_not_called()

    def test_third_not_opened_key_is_not_parked(self):
        # 今の周に開いていない unit_key は、3 回目でも ask_human に積まず返答全体を拒む（直す義務の外の単位を人に回さない）
        from unittest import mock
        with mock.patch.object(self.mod, "fix_unit_keys", return_value=([self.MEAN, self.CLAMP], {self.MEAN}, {})), \
                mock.patch.object(self.mod, "check_pack_copy", return_value=""), \
                mock.patch.object(self.mod, "check_plan_scope", return_value=([], None)):   # 積んだ後も範囲の照らしまで回る
            got = self.run_accept("3")
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.assertIn(self.CLAMP, got["reason"])
        self.assertEqual(self.parked, [])
        self.revert.assert_not_called()

    def g1_reply(self, failed_in):
        """修正の形 g1 の修正役の返答: mean の項目は審査を通った。clamp の項目は 3 回の審査を通らなかった（failed_in が changes なら
        行を残して root_or_symptom を symptom・why に残った指摘、not_done なら前の手順 3 の形）"""
        why = "審査を 3 回通らなかった: 残った指摘は下限の枝の取り違え（test_clamp.py の上限の試験が赤のまま）"
        mean = {"unit_key": self.MEAN, "files": ["stats.py"], "what": "分母を直した"}
        if failed_in == "changes":
            return {"changes": [mean, {"unit_key": self.CLAMP, "files": ["clamp.py", "test_clamp.py"], "what": "上限の枝を直した",
                                       "root_or_symptom": {"kind": "symptom", "why": why}}]}
        return {"changes": [mean], "not_done": [{"unit_key": self.CLAMP, "why": why}]}

    def run_reply(self, reply, iteration):
        from unittest import mock
        with mock.patch.dict("os.environ", {"INPUTS_ITERATION": iteration, "INPUTS_TDD_STATE": "/b/tdd.json",
                                            "INPUTS_PASS": "first"}):
            return self.mod.with_done(self.mod.accept_fix(reply, pathlib.Path("/b"), "", pathlib.Path("/r")))

    def copy_owed(self):
        """写しの受け付けの直す義務の数え（fix_covers_open_units と同じ文）: 止めた単位を除いた義務が changes に無ければ拒む"""
        def accept(reply, *a, **k):
            parked = {r["unit_key"] for rs, _ in self.parked for r in rs}
            missing = sorted({self.MEAN, self.CLAMP} - parked - {c["unit_key"] for c in reply["changes"]})
            if missing:
                return {"ok": False, "reason": "直していない [block] / do-now がある（writer の裁量で defer に覆せない。異議は新しい "
                                               "judge に再判定させる）: " + "; ".join(missing)}
            return {"ok": True, "reason": "", "changes": [{k: c[k] for k in ("unit_key", "files", "what")} for c in reply["changes"]]}
        return accept

    def test_g1_failed_item_in_changes_is_parked_alone_on_the_last_attempt(self):
        """g1（強み 4）: 3 回の審査を通らなかった項目の単位を changes に残した返答は、最後の回の拒否（選んだ試験の赤）がその単位に
        結べ、その単位の直しだけを戻して ask_human に止め、ほかの単位を通す"""
        from unittest import mock
        self.tests = [([self.RED], ""), ([], "")]
        with mock.patch.object(self.mod.recount, "accept_fix", side_effect=self.copy_owed()):
            self.assert_parked_clamp(self.run_reply(self.g1_reply("changes"), "3"))

    def test_g1_failed_item_in_not_done_refuses_the_whole_reply(self):
        """同じ単位を not_done に置いた返答（前の手順 3 の形）は、拒否が changes の行に結べず、最後の回も返答全体を拒む（単位ごとに
        戻せない）。g1 の手順 3 が changes に残す理由"""
        from unittest import mock
        self.tests = [([self.RED], ""), ([], "")]
        with mock.patch.object(self.mod.recount, "accept_fix", side_effect=self.copy_owed()):
            got = self.run_reply(self.g1_reply("not_done"), "3")
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.assertNotIn(self.CLAMP, [r["unit_key"] for rs, _ in self.parked for r in rs])
        self.revert.assert_not_called()

    def test_first_bound_red_still_goes_back_to_role(self):
        self.tests = [([self.RED], "")]
        got = self.run_accept("1")
        self.assertEqual((got["ok"], got["done"]), (False, False), got)
        self.assertEqual(self.parked, [])


REFIX = ROOT / "blk-refix"
CANON = CORE / "writerules" / "common.md"
REFIX_VALUES = {"brief_file": "/b/refix1-brief.json", "diff_file": "/b/r1/diff.patch", "policy_path": ""}
REMAP_TITLE = "この輪での読み替え（上の決まりより、ここが勝つ）"


def refixrules():
    """手直しの役の組み立て（blk-refix/lib/refixrules.py）。無ければ試験の失敗にする（読み込みの誤りにしない）"""
    sys.path.insert(0, str(REFIX / "lib"))
    try:
        import refixrules as mod
    except ImportError as e:
        raise AssertionError(f"手直しの役の組み立てが無い: {e}")
    return mod


class TestLangLine(unittest.TestCase):
    """書く役（修正・TDD の輪・裁定・手直し）の文は関所と報告に字のまま載るので、支度が盤面から取った言語の 1 行
    （rolekit.lang_line）を、どの形でも指示書の末尾に置く。見出しの次の 1 行（拒否・裁定のファイル・題）は動かさない"""
    LINE = rolekit.LANG_RULE.format(lang="English")

    def test_every_writer_prompt_ends_with_the_lang_line(self):
        fix = rulebook.render("fix", 1, fixrules.fix_parts(VALUES), reject_file="/b/r-1.txt", lang=self.LINE)["text"]
        delta = rulebook.render("fix", 2, fixrules.fix_parts(VALUES), prior={"delivered": {}}, lang=self.LINE)["text"]
        tdd = fixrules.tdd_render(tdd_values(), "fix", PHASE_TEXT, title=TITLE, lang=self.LINE)["text"]
        rule = fixrules.ruler_prompt({k: "/b/x" for k in fixrules.RULER_VALUES}, lang=self.LINE)
        refix = refixrules().build(1, {**REFIX_VALUES, "lang": self.LINE})
        for name, text in (("fix", fix), ("delta", delta), ("tdd", tdd), ("rule", rule), ("refix", refix)):
            with self.subTest(name):
                self.assertTrue(text.endswith(self.LINE + "\n"), text[-200:])
        self.assertEqual(fix.split("\n")[1], rolekit.REJECT_LINE.format(path="/b/r-1.txt"))
        self.assertEqual(tdd.split("\n")[1], TITLE)

    def test_no_lang_no_line(self):
        """盤面の外で組む（lang が空）なら置かない。置いても本文はそのまま"""
        plain = fixrules.fix_prompt(VALUES)
        self.assertNotIn(rolekit.LANG_RULE.split("{lang}")[0], plain)
        got = rulebook.render("fix", 1, fixrules.fix_parts(VALUES), lang=self.LINE)["text"]
        self.assertEqual(got, plain.rstrip("\n") + "\n\n" + self.LINE + "\n")

    def test_preps_take_the_lang_from_the_board(self):
        """支度（fixrules.prep・tddloop.prep・ruling.prep・refix.prep_fix）は盤面から言語の 1 行を取って渡す"""
        srcs = {"fix": (BLK / "lib" / "fixrules.py", "before=before, lang=lang)"),
                "tdd": (BLK / "lib" / "tddloop.py", "rules_file=rules_file, lang=lang)"),
                "rule": (BLK / "lib" / "ruling.py", "lang=fixrules.lang_at(board_dir)"),
                "refix": (CORE / "refix.py", '"lang": rolekit.lang_line(b.state.get("inputs"))')}
        for name, (path, needle) in srcs.items():
            with self.subTest(name):
                self.assertIn(needle, path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(fixrules.lang_at(d), "", "盤面でない置き場では置かない")


class TestPrepOwedValues(unittest.TestCase):
    def test_open_units_value_is_the_fix_duty_owed(self):
        """指示書の <<open_units>> は受け付けと同じ conflict.fix_duty の owed: 判定の並びを保ち、答え待ちの単位は載せず、
        関所で答えて戻った単位を後ろに足す"""
        from unittest import mock
        back = "c.py back: 関所で答えて戻した単位"
        with mock.patch.object(fixrules.conflict, "fix_duty", return_value=({"b: 上限", back}, {"a: 分母": "答え待ちの問い q"})):
            got = fixrules.owed_values(object(), VALUES)
        self.assertEqual(json.loads(got["open_units"]), ["b: 上限", back])
        self.assertEqual({k: v for k, v in got.items() if k != "open_units"}, {k: v for k, v in VALUES.items() if k != "open_units"})

    def test_prep_reads_the_duty_before_it_builds_the_prompt(self):
        src = (BLK / "lib" / "fixrules.py").read_text(encoding="utf-8")
        self.assertLess(src.index("values = owed_values(b, values)"), src.index("docs = lib_section(b, repo, values)"))


class TestRefixCarriesCanon(unittest.TestCase):
    """手直しの役（blk-refix の refix・refix2）も書く役なので、同じ正本の節を全部受け取る。正本はブロックの境を越えて読める
    .shared/core の下に 1 つだけ置き、手書きの commands/refix*.md は無い"""

    def test_canon_lives_in_shared_core(self):
        self.assertTrue(CANON.is_file(), "正本は .shared/core の下（ほかのブロックからも読める置き場）")
        self.assertFalse((BLK / "rules" / "common.md").exists(), "blk-fix の中に写しを残さない")

    def test_refix_roles_read_the_composed_file(self):
        nodes = yaml.safe_load((REFIX / "blk-refix.yaml").read_text(encoding="utf-8"))["nodes"]
        for rid, prep in (("refix", "refix-prep"), ("refix2", "refix2-prep")):
            with self.subTest(rid):
                n = find_node(nodes, rid)
                self.assertNotIn("command", n)
                self.assertIn(f"`${prep}.output.prompt_file` を Read で", n.get("prompt", ""))
                self.assertIn("prompt_file", find_node(nodes, prep)["output_format"]["properties"])
                self.assertFalse((REFIX / "commands" / f"{rid}.md").exists(), "手書きの指示書は無い")

    def test_refix_prompts_carry_every_canon_section(self):
        self.assertTrue(CANON.is_file(), "正本は .shared/core の下")
        canon = "\n".join(ln for ln in CANON.read_text(encoding="utf-8").splitlines()
                          if not fixrules.MARK.match(ln)).strip("\n")
        mod = refixrules()
        for n in (1, 2):
            with self.subTest(n):
                text = mod.build(n, REFIX_VALUES)
                self.assertIn(canon, text, "正本の全節を字のまま")
                self.assertIn(REMAP_TITLE, text)
                self.assertLess(text.index(canon), text.index(REMAP_TITLE), "読み替えは正本の後（ここが勝つ）")
                self.assertNotIn("<<", text)
                self.assertNotIn("<!-- 節", text)
                self.assertIn(f"`{REFIX_VALUES['brief_file']}`", text)
                self.assertEqual(text.encode(), mod.build(n, dict(reversed(list(REFIX_VALUES.items())))).encode())

    def test_refix_reply_is_written_once_and_only_the_tail_differs(self):
        """返答の決まりは rules/refix.md に 1 つだけ書き、どの回にも同じ字で載る。回ごとに違うのは後に当たる物（tail）だけ"""
        mod = refixrules()
        r = rulebook.sections(REFIX / "rules" / "refix.md")
        reply, tails = r["refix-reply"], {n: r[f"refix-tail-{n}"] for n in (1, 2)}
        self.assertEqual((REFIX / "rules" / "refix.md").read_text(encoding="utf-8").count(reply), 1)
        for n in (1, 2):
            with self.subTest(n):
                text = mod.build(n, REFIX_VALUES)
                self.assertEqual(text.count(reply), 1)
                self.assertLess(text.index(reply), text.index(tails[n]))
                self.assertNotIn(tails[3 - n], text)


class TestBriefCanonEdges(unittest.TestCase):
    """brief の決まり（brief-canon）の端: 人が関所で付けた条件との強さの順と、指示書の頭の節の見出しとの重なり"""

    def test_gate_notes_win_over_brief(self):
        """修正の前に人が答えた条件（notes_file）は brief に勝つ。brief が条件を超えれば条件どおりに直し、超えた所は申し出で返す。
        決まりの文は「関所」の語を使わない（ブロックはほかの段を知らない。test の BLOCK_KNOWN の数え）"""
        sec = fixrules.sections(fixrules.BRIEF)["brief-canon"]
        self.assertIn("修正の前に人が答えた条件（notes_file）は brief に勝つ", sec)
        self.assertIn("brief が条件を超えれば条件どおりに直し、超えた所は食い違いの申し出で返す", sec)

    def test_rule_heading_does_not_overlap_brief_head(self):
        """決まりの節の見出しは、指示書の頭の brief の節の見出し（planbrief.HEAD）を含まない。READ_ALL は決まりの節の名を名指す"""
        import planbrief
        sec = fixrules.sections(fixrules.BRIEF)["brief-canon"]
        self.assertNotIn(planbrief.HEAD, sec)
        heading = next(ln for ln in sec.splitlines() if ln.startswith("## "))
        self.assertIn(f"『{heading[3:]}』", planbrief.READ_ALL)
        for name, sid in ((fixrules.DIRECT, "fix-head"), (fixrules.TDD, "tdd-head")):
            line = next(ln for ln in fixrules.sections(name)[sid].splitlines() if "<<judgment_file>>" in ln)
            self.assertIn(f"「{heading[3:]}」", line)


class TestSeatParts(unittest.TestCase):
    """借りたスキルの座（seat.section の文）は、渡された時だけ節 seat として載る（修正の形 g3。計画 220 Task 2）。
    修正役の座の型の穴の値は implementer_values が盤面と run の値から組む"""

    def test_seat_part_only_when_given(self):
        tdd = [pid for pid, _, _ in fixrules.tdd_parts(tdd_values(), seat="S")]
        self.assertEqual(tdd[tdd.index("tdd-remap") + 1], "seat")
        fix = [pid for pid, _, _ in fixrules.fix_parts(VALUES, seat="S")]
        self.assertEqual(fix[fix.index("fix-reply") - 1], "seat")
        self.assertNotIn("seat", [pid for pid, _, _ in fixrules.fix_parts(VALUES)])
        self.assertNotIn("seat", [pid for pid, _, _ in fixrules.tdd_parts(tdd_values())])

    def test_prompts_pass_the_seat_through(self):
        self.assertIn("座の文 S", fixrules.fix_prompt(VALUES, seat="座の文 S"))
        self.assertIn("座の文 S", fixrules.tdd_prompt(tdd_values(), "fix", PHASE_TEXT, title=TITLE, seat="座の文 S"))
        self.assertEqual(fixrules.fix_prompt(VALUES), fixrules.fix_prompt(VALUES, seat=""))

    def _values(self, rows, owed):
        from unittest import mock
        import seat
        import spseam
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = pathlib.Path(tmp.name)
        b = mock.Mock()
        b.work.side_effect = lambda name: d / name
        with mock.patch.object(fixrules.planbrief, "cut", return_value=rows):
            got = fixrules.implementer_values(b, VALUES, pathlib.Path("/repo"), owed)
        self.assertEqual(set(got), set(spseam.load_seams()["implementer"]["placeholders"]))
        self.assertEqual(got["[REPORT_FILE]"], seat.NO_REPORT_FILE)
        self.assertEqual(got["[directory]"], "/repo")
        scene = got["[Scene-setting: where this fits, dependencies, architectural context]"]
        self.assertIn(seat.SCENE, scene)
        self.assertIn(VALUES["summary_file"], scene)
        return got, d

    def test_implementer_values_with_briefs(self):
        import planbrief
        owed = ["a: 分母", "b: 上限"]
        rows = [{"item": 1, "unit_keys": ["a: 分母"], "file": "/b/r1/brief-1.md", "sha256": "a" * 64},
                {"item": 2, "unit_keys": ["z: 外"], "file": "/b/r1/brief-2.md", "sha256": "b" * 64},
                {"item": 3, "unit_keys": ["b: 上限", "y: 外"], "file": "/b/r1/brief-3.md", "sha256": "c" * 64}]
        got, d = self._values(rows, owed)
        self.assertEqual(got["[task name]"], "直す義務の単位 2 件（修正案の項目 1、3）")
        self.assertEqual(got["[BRIEF_FILE]"], str(d / fixrules.SEAT_BRIEFS))
        text = (d / fixrules.SEAT_BRIEFS).read_text(encoding="utf-8")
        self.assertIn(planbrief.HEAD, text)
        self.assertIn("brief-1.md", text)
        self.assertIn("brief-3.md", text)
        self.assertNotIn("brief-2.md", text, "義務の単位を持たない項目は載せない")

    def test_implementer_values_without_briefs(self):
        got, d = self._values([], ["a: 分母"])
        self.assertEqual(got["[task name]"], "直す義務の単位 1 件")
        self.assertEqual(got["[BRIEF_FILE]"], VALUES["judgment_file"], "brief が無い run は判定のファイル")
        self.assertFalse((d / fixrules.SEAT_BRIEFS).exists())

    def test_implementer_values_fill_the_real_template(self):
        """組んだ値で 216 の型が埋まる（穴が残らない）"""
        import seat
        got, _ = self._values([], ["a: 分母"])
        self.assertIn(VALUES["judgment_file"], seat.section("fix", "g3", got))


class G1ValuesCase(unittest.TestCase):
    """修正の形 g1 の下請けのファイル（fixrules.g1_values）: brief の項目ごと・項目に無い直す義務の単位は残りの 1 項目
    （[BRIEF_FILE] は判定のファイル）・項目のほかの単位は『今は直すな』。座の節の理由の文は形ごと（g3 は前と同じ文）"""

    ROWS = [{"item": 1, "unit_keys": ["a: 分母"], "file": "/b/r1/brief-1.md", "sha256": "0" * 64},
            {"item": 2, "unit_keys": ["b: 上限", "c: 外"], "file": "/b/r1/brief-2.md", "sha256": "1" * 64}]
    OWED = ["a: 分母", "b: 上限", "d: 案の外"]

    def board(self, d=None, scope=""):
        """盤面の替わり（work は scope の根の下。d を渡せば同じ置き場の別の scope の入れ物）"""
        if d is None:
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            d = pathlib.Path(tmp.name)

        class B:
            state = {"inputs": {"review_rev": "abc123"}}
            dir = d / "art" / "board"

            def work(self, name):
                p = d / scope / name
                p.parent.mkdir(parents=True, exist_ok=True)
                return p
        return B()

    def test_items_and_remainder(self):
        import planbrief
        from unittest import mock
        b = self.board()
        with mock.patch.object(fixrules, "briefs_or_halt", return_value=self.ROWS):
            got = fixrules.g1_values(b, VALUES, "/repo", self.OWED, "")
        self.assertEqual([r["item"] for r in got], [1, 2, 3], "項目に無い直す義務の単位は残りの 1 項目")
        self.assertEqual({r["base"] for r in got}, {"abc123"})
        # 差分のファイルは run ごとの置き場（盤面の隣。包みが sandbox で書けるようにする所）の絶対パス。審査役の Diff file もそのパス
        place = b.dir.parent / "run-place"
        self.assertEqual([r["patch"] for r in got], [str(place / f"g1-{n}.patch") for n in (1, 2, 3)])
        review = pathlib.Path(got[0]["review_file"]).read_text(encoding="utf-8")
        self.assertIn(f"**Diff file:** {place / 'g1-1.patch'}", review)
        impl2 = pathlib.Path(got[1]["impl_file"]).read_text(encoding="utf-8")
        for w in ("修正案の項目 2", "b: 上限", planbrief.NOT_NOW, "c: 外", "/b/r1/brief-2.md"):
            self.assertIn(w, impl2)
        self.assertNotIn("a: 分母", impl2)
        for f in (got[2]["impl_file"], got[2]["review_file"]):
            text = pathlib.Path(f).read_text(encoding="utf-8")
            self.assertIn(VALUES["judgment_file"], text, "残りの項目の brief は判定のファイル")
        self.assertIn("d: 案の外", pathlib.Path(got[2]["impl_file"]).read_text(encoding="utf-8"))

    def test_second_pass_files_live_under_its_scope(self):
        """2 回目の修正の段（include refitting。依頼 226・239）の下請けのファイル・差分のファイル・座の brief は 1 回目と同じ名で
        その scope の根の下に書き、1 回目の物を上書きしない"""
        from unittest import mock
        b = self.board()
        refit = self.board(b.dir.parent.parent, "refitting")
        place = b.dir.parent / "run-place"
        node = {"ARCHON_NODE_EXECUTION": json.dumps({"runId": "r", "path": "refitting__fix-loop.fix-prep"})}
        with mock.patch.object(fixrules, "briefs_or_halt", return_value=self.ROWS), \
                mock.patch.object(fixrules.planbrief, "cut", return_value=self.ROWS):
            first = fixrules.g1_values(b, VALUES, "/repo", self.OWED[:2], "")
            with mock.patch.dict(os.environ, node):
                second = fixrules.g1_values(refit, VALUES, "/repo", self.OWED[:1], "")
                seat_brief = fixrules.implementer_values(refit, VALUES, "/repo", self.OWED[:1])["[BRIEF_FILE]"]
        self.assertEqual([second[0][k] for k in ("impl_file", "review_file", "patch")],
                         [str(refit.work("g1-impl-1.md")), str(refit.work("g1-review-1.md")),
                          str(place / "refitting" / "g1-1.patch")])
        self.assertTrue((place / "refitting").is_dir(), "役の差分のコマンドが書ける")
        self.assertEqual(first[0]["patch"], str(place / "g1-1.patch"))
        self.assertEqual(seat_brief, str(refit.work("seat-briefs.md")))
        self.assertIn("b: 上限", pathlib.Path(first[0]["impl_file"]).parent.joinpath("g1-impl-2.md").read_text(encoding="utf-8"),
                      "1 回目の段のファイルは残る")
        self.assertNotEqual(first[0]["impl_file"], second[0]["impl_file"])
        self.assertIn("a: 分母", pathlib.Path(first[0]["impl_file"]).read_text(encoding="utf-8"))

    def test_no_remainder_when_items_cover_the_duty(self):
        from unittest import mock
        with mock.patch.object(fixrules, "briefs_or_halt", return_value=self.ROWS):
            got = fixrules.g1_values(self.board(), VALUES, "/repo", self.OWED[:2], "")
        self.assertEqual([r["item"] for r in got], [1, 2])

    def test_g1_task_names_now_and_not_now(self):
        import planbrief
        got = fixrules._g1_task(self.ROWS[1], self.OWED)
        self.assertEqual(got, f"修正案の項目 2（直す義務の単位 b: 上限・{planbrief.NOT_NOW}: c: 外）")

    def test_unit_note_is_shared_with_head_text(self):
        import planbrief
        self.assertEqual(planbrief.unit_note(["a", "b"], ["a"]), f"a・{planbrief.NOT_NOW}: b")
        self.assertEqual(planbrief.unit_note(["a", "b"]), "a、b")
        self.assertEqual(planbrief.unit_note(["b"], ["a"]), f"{planbrief.NONE}・{planbrief.NOT_NOW}: b")
        self.assertIn(f"単位 {planbrief.unit_note(['b: 上限', 'c: 外'], ['b: 上限'])}）",
                      planbrief.head_text(self.ROWS[1:], ["b: 上限"]))

    def test_gate_off_shapes_use_the_fixshape_words(self):
        """tdd-start が test_cmd の関門を切る形は fixshape の語（平の run は fixshape.PLAIN）と seat.G1_SHAPE で引く"""
        import fixshape
        import seat
        import tddloop
        self.assertEqual(set(tddloop.GATE_OFF_BY_SHAPE), {fixshape.PLAIN, seat.G1_SHAPE})
        self.assertFalse(hasattr(tddloop, "PLAIN_SHAPE"), "形の語を写さない")
        self.assertTrue(set(tddloop.GATE_OFF_BY_SHAPE) <= set(fixshape.SHAPES))

    def test_seat_reason_names_the_shape_and_g3_is_unchanged(self):
        """g3 の指示書は前とバイト単位で同じ（座の節の理由の文は『（修正の形 g3 の座）』のまま）。g1 は g1 と書く"""
        def reason(**kw):
            return {pid: why for pid, _, why in fixrules.fix_parts(VALUES, seat="S", **kw)}["seat"]
        self.assertEqual(reason(), "いつも（修正の形 g3 の座）")
        self.assertEqual(reason(shape="g1"), "いつも（修正の形 g1 の座）")
        tdd = {pid: why for pid, _, why in fixrules.tdd_parts(tdd_values(), seat="S")}["seat"]
        self.assertEqual(tdd, "いつも（修正の形 g3 の座）")


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_edge import EdgeBase, fix_reply  # noqa: E402  （盤面を線の順に進める手助け。本物の盤面と写しの規則を通す）


class FixCoversOpenUnitsAllErrorsCase(EdgeBase):
    """修正の返答の受け付け（写しの fix_covers_open_units）は、形の誤りを最初の 1 つで投げず、全部を 1 回の拒否に 1 誤り 1 行で並べる
    （3 回の枠を形の誤りだけで使い切らないため）。誤りは文でなく problems の配列でも運ぶ（受け付けが行に割らずに単位へ結ぶため）"""

    HEADING = "下の行を直した返答を丸ごと出し直せ:"

    def test_shape_errors_listed_one_per_line(self):
        import entry
        import test_edge
        self.planned()
        entry.open_board(self.board).answer("continue", "clamp の上限は hi でよい")
        src = (self.repo / "stats.py").read_text(encoding="utf-8")
        (self.repo / "stats.py").write_text(src.replace("(len(xs) - 1)", "len(xs)").replace(
            "    if x > hi:\n        return lo", "    if x > hi:\n        return hi"), encoding="utf-8")
        reply = fix_reply(faces=True)
        mean, clamp = reply["changes"]
        mean["bypass_tried"] = "なし"        # 形の誤り 1（mean の行。空語は型には通り、規則が空同然として拒む）
        clamp["breaks"]["result"] = "なし"   # 形の誤り 2（clamp の行）
        reply["interactions"] = []           # 2 単位が同じ stats.py を触るのに面の記録が無い（誤り 3）
        b = entry.open_board(self.board)
        b.mark_launched("p3.fix", test_edge.pending_inst(b, "p3.fix").get("attempts", 1))
        got = entry.take(self.board, "p3.fix", reply, self.repo)
        self.assertFalse(got["ok"], got)
        lines = [ln for ln in got["reason"].splitlines() if ln.startswith("  - ")]
        self.assertIn(self.HEADING, got["reason"])
        self.assertEqual(len(lines), 3, got["reason"])
        self.assertTrue(any("interactions" in ln for ln in lines), lines)
        self.assertTrue(any("bypass_tried" in ln and ln.lstrip(" -").startswith(test_edge.UNIT_MEAN[:60]) for ln in lines), lines)
        self.assertTrue(any("breaks.result" in ln and ln.lstrip(" -").startswith(test_edge.UNIT_CLAMP[:60]) for ln in lines), lines)
        self.assertEqual(len(got.get("problems") or []), 3, got)


if __name__ == "__main__":
    unittest.main()
