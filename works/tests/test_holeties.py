"""差分の審査の穴に枝の名札を付ける（線の木の段 4a。設計 docs/plans/2026-10-07-hole-to-branch.md の 2.2・2.3）。

holeties の純粋な関数（tie・groups・spread・earlier・lines）を見本の入力で、refix.hole_ties を偽の盤面（state・dir・work と
output_of_round だけ。盤面を開かない）で直に呼ぶ（FAST。git・子のプロセスなし）"""
import json
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import holeties  # noqa: E402

U1 = "works/a.py+f: 一つ目"
U2 = "works/b.py+g: 二つ目"
U3 = "works/c.py+h: 三つ目"
LOOSE = "works/d.py+k: どの項目にも無い単位"
ITEMS = [
    {"item": 1, "unit_keys": [U1], "allowed_paths": ["works/a.py", "works/lib/*.py"],
     "tests": [{"id": "works/tests/test_a.py::ACase::test_x"}], "rewrite_tests": []},
    {"item": 2, "unit_keys": [U2], "allowed_paths": ["works/b.py", "works/lib/*.py"], "tests": [], "rewrite_tests": []},
    {"item": 3, "unit_keys": [U3], "allowed_paths": ["works/c.py"], "tests": [], "rewrite_tests": [], "held": "ask_human の裁定 c1"},
]


def hole(key, where="", check=False):
    return {"key": key, "from": "p3.delta_review.checks" if check else "p3.delta_review", "where": where, "check": check}


def by_key(ties):
    return {t["key"]: t for t in ties}


class TieCase(unittest.TestCase):
    def test_compliance_row_names_item(self):
        """準拠の落ちた行の face_key が穴の key なら、その行の項目に結ぶ（場所が無くても）"""
        got = by_key(holeties.tie([hole("missing-thing-in-a")], ITEMS,
                                  compliance=[{"item": 2, "kind": "missing", "face_key": "missing-thing-in-a", "why": "x" * 20}]))
        self.assertEqual(got["missing-thing-in-a"]["branches"], ["item:2"])
        self.assertIn("compliance", got["missing-thing-in-a"]["via"])

    def test_check_follows_plan_face_units(self):
        """塞がっていない検算は、事前審査の穴の unit_keys を持つ項目に結ぶ"""
        got = by_key(holeties.tie([hole("plan-face-one", check=True)], ITEMS,
                                  plan_faces=[{"key": "plan-face-one", "unit_keys": [U1]}]))
        self.assertEqual(got["plan-face-one"]["branches"], ["item:1"])
        self.assertEqual(got["plan-face-one"]["via"], ["check"])

    def test_where_in_allowed_paths(self):
        """where が項目の allowed_paths の glob か受け入れのテストのファイルに当たれば、その項目"""
        got = by_key(holeties.tie([hole("hole-in-a-file", "works/a.py"), hole("hole-in-test", "works/tests/test_a.py")], ITEMS))
        self.assertEqual(got["hole-in-a-file"]["branches"], ["item:1"])
        self.assertEqual(got["hole-in-test"]["branches"], ["item:1"])
        self.assertIn("path", got["hole-in-a-file"]["via"])

    def test_shared_glob_is_two_branches(self):
        """2 つの項目の glob に当たる where は枝 2 つ（相乗りの組へ行く）"""
        got = by_key(holeties.tie([hole("hole-in-shared-lib", "works/lib/x.py")], ITEMS))
        self.assertEqual(got["hole-in-shared-lib"]["branches"], ["item:1", "item:2"])

    def test_change_of_unit_outside_items(self):
        """修正の changes で where を変えた単位がどの項目にも無ければ、その単位の枝"""
        got = by_key(holeties.tie([hole("hole-in-d-file", "works/d.py")], ITEMS,
                                  changes=[{"unit_key": LOOSE, "files": ["works/d.py"]}]))
        self.assertEqual(got["hole-in-d-file"]["branches"], [f"unit:{LOOSE}"])
        self.assertIn("change", got["hole-in-d-file"]["via"])

    def test_change_of_unit_in_item(self):
        """changes の単位が項目に在れば、その項目（範囲の外のファイルでも）"""
        got = by_key(holeties.tie([hole("hole-in-other-file", "works/zzz.py")], ITEMS,
                                  changes=[{"unit_key": U2, "files": ["works/zzz.py"]}]))
        self.assertEqual(got["hole-in-other-file"]["branches"], ["item:2"])

    def test_unit_key_path(self):
        """単位の key の頭のパスが where と同じなら、その単位の項目（範囲も changes も無い時の手）"""
        items = [{"item": 1, "unit_keys": ["works/x.py: 何か"]}]
        got = by_key(holeties.tie([hole("hole-in-x-file", "works/x.py")], items))
        self.assertEqual(got["hole-in-x-file"]["branches"], ["item:1"])
        self.assertEqual(got["hole-in-x-file"]["via"], ["unit"])

    def test_nothing_matches(self):
        got = by_key(holeties.tie([hole("hole-nowhere", "works/zzz.py")], ITEMS))
        self.assertEqual(got["hole-nowhere"]["branches"], [])
        self.assertEqual(got["hole-nowhere"]["via"], [])

    def test_held_only(self):
        """裁定で外れた項目にだけ結ばれた穴は held に理由を持つ。外れていない項目にも結ばれれば held は空"""
        got = by_key(holeties.tie([hole("hole-in-c-file", "works/c.py"), hole("hole-in-a-file", "works/a.py")], ITEMS))
        self.assertEqual(got["hole-in-c-file"]["branches"], ["item:3"])
        self.assertEqual(got["hole-in-c-file"]["held"], "ask_human の裁定 c1")
        self.assertEqual(got["hole-in-a-file"]["held"], "")

    def test_order_kept(self):
        keys = ["hole-b-first", "hole-a-second"]
        got = holeties.tie([hole(keys[0], "works/b.py"), hole(keys[1], "works/a.py")], ITEMS)
        self.assertEqual([t["key"] for t in got], keys)

    def test_earlier_for_second_pass(self):
        """2 回目: 検算の key は 1 回目にその key に結んだ枝、where は 1 回目の手直しがそのファイルを変えた穴の枝"""
        first = holeties.tie([hole("first-hole-in-a", "works/a.py"), hole("first-hole-in-b", "works/b.py")], ITEMS)
        handled = [{"key": "first-hole-in-a", "handled": "fixed", "how": "x" * 20, "files": ["works/zzz.py"]},
                   {"key": "first-hole-in-b", "handled": "declared", "how": "y" * 20}]
        earlier = holeties.earlier(first, handled)
        got = by_key(holeties.tie([hole("first-hole-in-a", check=True), hole("second-hole-in-zzz", "works/zzz.py")],
                                  ITEMS, earlier=earlier))
        self.assertEqual(got["first-hole-in-a"]["branches"], ["item:1"])
        self.assertEqual(got["second-hole-in-zzz"]["branches"], ["item:1"])
        self.assertEqual(got["second-hole-in-zzz"]["via"], ["earlier"])


class GroupCase(unittest.TestCase):
    def setUp(self):
        self.ties = holeties.tie([hole("hole-a-one", "works/a.py"), hole("hole-a-two", "works/a.py"),
                                  hole("hole-shared", "works/lib/x.py"), hole("hole-nowhere", "works/zzz.py"),
                                  hole("hole-held", "works/c.py")], ITEMS)

    def test_groups(self):
        got = holeties.groups(self.ties)
        self.assertEqual(got["lanes"], {"item:1": ["hole-a-one", "hole-a-two"]})
        self.assertEqual(got["synergy"], ["hole-shared", "hole-nowhere", "hole-held"])

    def test_spread(self):
        got = holeties.spread(self.ties)
        self.assertEqual(got, {"holes": 5, "single": 2, "multi": 1, "none": 1, "held": 1, "groups": 2,
                               "branches": {"item:1": 2}})

    def test_spread_empty(self):
        self.assertEqual(holeties.spread([])["groups"], 0)

    def test_lines(self):
        text = "\n".join(holeties.lines(self.ties))
        self.assertIn("hole-a-one: 項目 1", text)
        self.assertIn("hole-shared: 項目 1・項目 2（2 つ以上の枝にまたがる）", text)
        self.assertIn("hole-nowhere: どの枝にも結べない", text)
        self.assertIn("hole-held: 項目 3（裁定で外れた項目だけ: ask_human の裁定 c1）", text)

    def test_note_of_unit(self):
        t = holeties.tie([hole("hole-in-d-file", "works/d.py")], ITEMS, changes=[{"unit_key": LOOSE, "files": ["works/d.py"]}])
        self.assertEqual(holeties.note(t[0]), f"単位 {LOOSE}")


def fake_board(tmp, outputs: dict, loop: dict, files: dict | None = None) -> types.SimpleNamespace:
    """偽の盤面（今の周 1。outputs は {節: 出力}、loop は loop_state、files は盤面の根からのパス → 中身）"""
    d = pathlib.Path(tmp)
    state = {"round": 1, "outputs": {}, "loop": loop}
    for nid, doc in outputs.items():
        (d / f"{nid}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        state["outputs"][nid] = {"file": f"{nid}.json", "round": 1}
    for rel, doc in (files or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    b = types.SimpleNamespace(state=state, dir=d, round=1, loop_state=loop, scope="", scope_root=d)

    def work(name, round_=None):
        p = d / f"r{round_ or 1}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def output_of_round(nid, rnd):
        info = state["outputs"].get(nid)
        if not info or info["round"] != rnd:
            return None
        return json.loads((d / info["file"]).read_text(encoding="utf-8"))
    b.work, b.output_of_round = work, output_of_round
    return b


class BoardCase(unittest.TestCase):
    """refix.hole_ties: 盤面の今の周の義務・差分の審査・修正案・修正の変更・準拠の控えから名札を組む"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        import refix  # 写しの RL を読む（DELTA_PASSES）
        self.refix = refix

    def tearDown(self):
        self._tmp.cleanup()

    def board(self, *, fields=True, held=False):
        plan = [{"unit_keys": [U1]}, {"unit_keys": [U2]}]
        outputs = {
            "p2.fix_plan": {"plan": plan},
            "p2.plan_review": {"faces": [{"key": "plan-face-one", "unit_keys": [U2], "kind": "copy", "where": "x",
                                          "why": "w" * 20, "severity": "block"}]},
            "p3.fix": {"changes": [{"unit_key": U1, "files": ["works/zzz.py"]}]},
            "p3.delta_review": {"faces": [{"key": "hole-in-a-file", "kind": "copy", "where": "works/a.py", "cite": "abcd",
                                           "why": "w" * 20},
                                          {"key": "hole-in-zzz", "kind": "copy", "where": "works/zzz.py", "cite": "abcd",
                                           "why": "w" * 20}],
                                "checks": [{"key": "plan-face-one", "closed": False, "why": "w" * 20}]},
        }
        rows = [{"key": "hole-in-a-file", "from": "p3.delta_review", "text": "t"},
                {"key": "hole-in-zzz", "from": "p3.delta_review", "text": "t"},
                {"key": "plan-face-one", "from": "p3.delta_review.checks", "text": "t"}]
        loop = {"delta_owed": {"round": 1, "rows": rows}}
        files = {}
        if fields:
            import hashlib
            import planmarks
            doc = {"round": 1, "fields": [{"allowed_paths": ["works/a.py"]}, {"allowed_paths": ["works/b.py"]}]}
            raw = (json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
            files[planmarks.FIELDS_FILE] = raw
            files["trace.jsonl"] = json.dumps({"op": planmarks.SAVED_OP, "round": 1,
                                               "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest()}) + "\n"
        if held:
            files["r1/conflicts.json"] = {"items": [{"id": "c1", "unit_key": U2, "ruling": {"decision": "ask_human"}}]}
        return fake_board(self._tmp.name, outputs, loop, files)

    def test_first_pass(self):
        got = by_key(self.refix.hole_ties(self.board(), 1))
        self.assertEqual(got["hole-in-a-file"]["branches"], ["item:1"])
        self.assertEqual(got["hole-in-zzz"]["branches"], ["item:1"])     # changes の単位 U1
        self.assertEqual(got["plan-face-one"]["branches"], ["item:2"])   # 事前審査の穴の単位 U2
        self.assertEqual(got["hole-in-a-file"]["where"], "works/a.py")

    def test_no_fields_still_ties_by_change_and_check(self):
        """凍結した欄の無い盤面（項目が引けない）は項目の枝を作らず、changes・単位の key の頭のパス・検算の単位は単位の枝で結ぶ"""
        got = by_key(self.refix.hole_ties(self.board(fields=False), 1))
        self.assertEqual(got["hole-in-a-file"]["branches"], [f"unit:{U1}"])   # U1 の頭のパス works/a.py
        self.assertEqual(got["hole-in-a-file"]["via"], ["unit"])
        self.assertEqual(got["hole-in-zzz"]["branches"], [f"unit:{U1}"])
        self.assertEqual(got["plan-face-one"]["branches"], [f"unit:{U2}"])

    def test_held_item(self):
        got = by_key(self.refix.hole_ties(self.board(held=True), 1))
        self.assertTrue(got["plan-face-one"]["held"])

    def test_no_owed(self):
        b = self.board()
        b.loop_state.clear()
        self.assertEqual(self.refix.hole_ties(b, 1), [])


class PathCase(unittest.TestCase):
    def test_lead_path(self):
        self.assertEqual(holeties.lead_path("works/x.py:513-540 (_final_text の residue 呼び)"), "works/x.py")
        self.assertEqual(holeties.lead_path("works/x.py の docstring「…」"), "works/x.py")
        self.assertEqual(holeties.lead_path("works/x.py:550（_final_text の直前）"), "works/x.py")
        self.assertEqual(holeties.lead_path("works/x.py（何か）"), "works/x.py")
        self.assertEqual(holeties.lead_path("全体の設計"), "")
        self.assertEqual(holeties.lead_path(""), "")

    def test_unit_path(self):
        self.assertEqual(holeties.unit_path("works/a.py+f: 一言"), "works/a.py")
        self.assertEqual(holeties.unit_path("works/a.py: 一言"), "works/a.py")
        self.assertEqual(holeties.unit_path("名だけ: 一言"), "")


class ShownCase(unittest.TestCase):
    """名札を見せる所: 手直しの brief の欄・報告と最後の関所の行（report.branch_rows）・次の run の依頼の下書きの text"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cases = BoardCase()
        self.cases._tmp = self._tmp
        import refix
        import report
        self.cases.refix, self.refix, self.report = refix, refix, report

    def tearDown(self):
        self._tmp.cleanup()

    def test_brief_ties(self):
        got = self.refix.brief_ties(self.refix.hole_ties(self.cases.board(), 1))
        self.assertEqual(got[0], {"key": "hole-in-a-file", "branches": ["項目 1"], "note": "項目 1", "via": ["path", "unit"]})

    def test_branch_rows(self):
        text = "\n".join(self.report.branch_rows(self.cases.board()))
        self.assertIn(self.report.BRANCH_HEAD[1] + ": 3 件（枝 1 つ 3", text)
        self.assertIn("  - plan-face-one: 項目 2", text)
        self.assertNotIn(self.report.BRANCH_HEAD[2], text)   # 2 回目の義務が無ければ行を出さない

    def test_branch_rows_empty_without_holes(self):
        b = self.cases.board()
        b.loop_state.clear()
        self.assertEqual(self.report.branch_rows(b), [])

    def test_eye_rows(self):
        b = self.cases.board()
        (b.dir / "r4.json").write_text(json.dumps({"surfaced": [{"where": "works/b.py:12（何か）", "text": "t"}]}), encoding="utf-8")
        b.state["outputs"]["r4.hidden_scope"] = {"file": "r4.json", "round": 1}
        text = "\n".join(self.report.branch_rows(b))
        self.assertIn(self.report.EYE_HEAD + ": 1 件", text)
        self.assertIn("  - R4: works/b.py:12（何か）: 項目 2", text)

    def test_next_request_tag(self):
        b = self.cases.board()
        (b.dir / "fix1.json").write_text(json.dumps({"handled": [
            {"key": "hole-in-a-file", "handled": "declared", "how": "x" * 20}]}), encoding="utf-8")
        b.state["outputs"]["p3.delta_fix"] = {"file": "fix1.json", "round": 1}
        b.record = {}
        rows = self.report.next_request(b)
        self.assertTrue(rows[0]["text"].endswith("（枝: 項目 1）"), rows)

if __name__ == "__main__":
    unittest.main()
