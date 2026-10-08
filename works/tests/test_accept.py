"""受け付けの口（.shared/core/accept.py）の検査。

良い返答の見本が通り、悪い見本（拒む理由が 1 つだけになるように作った物）が ok: False で拒まれるかを、
dev/target-seed/ を一時ディレクトリの git に写した使い捨ての対象リポジトリで見る。見本は tests/replies/ に在る。
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.path.insert(0, str(CORE))

from accept import (_ignored_entries, check_judge, check_request, role_schema, snapshot_tree, tree_change,  # noqa: E402
                    tree_state)
from gitkit import committed_copy, git  # noqa: E402
import querytest  # noqa: E402

def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text())


class AcceptCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        self.base = committed_copy(self.repo, SEED)   # 種を写して commit した git（型の写し。gitkit）
        self.board = tmp / "board"
        self.board.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def judged(self):
        r = check_judge(load("judge_ok"), self.board, self.base, self.repo)
        self.assertTrue(r["ok"], r["reason"])
        return r


class TestIntake(AcceptCase):
    def test_intake_accepts_request(self):
        r = check_request(load("request_ok"), self.board, "持ち主")
        self.assertTrue(r["ok"], r["reason"])
        batches = json.loads((self.board / "request.json").read_text())
        self.assertEqual(batches, [{"round": 1, "origin": "持ち主", "findings": load("request_ok")}])

    def test_add_reads_nodes_and_runners_of_scratch_board(self):
        # 0.21.0 の add は、積んだ欄を読む待ちの instance を b.nodes の reads と b.is_runner で振り分ける（他へ渡した物は描き直し、
        # 回す側の節は言うだけ）。今の works は instances が空でこの道を通らない——受け付けの入れ物（DiskBoard.scratch）の
        # nodes・is_runner が engine と同じ振り分けになるかを、instance を 3 つ持たせて見る
        import accept
        rules = accept._rules()
        b = accept.DiskBoard.scratch(self.board, review_rev="", record=rules.init_record(None, None))
        self.assertFalse(b.is_runner(b.nodes["p2.diagnose"]))   # judge
        self.assertTrue(b.is_runner(b.nodes["report"]))          # writer（graph の runners）
        none = str(self.board / "まだ無い返答.json")
        b.rd["instances"] = {i: {"id": i, "node": n, "status": "pending", "out_path": none}
                             for i, n in (("p2.diagnose#1", "p2.diagnose"), ("report#1", "report"), ("p3.fix#1", "p3.fix"))}
        r = rules.add(b, load("request_ok"), "持ち主")
        self.assertEqual(r["redraw"], ["p2.diagnose#1"])   # 依頼を読む・回す側でない・まだ起きていない
        self.assertIn("report#1 は起きた後か回す側の節なので描き直していない", r["msg"])
        self.assertNotIn("p3.fix#1", r["msg"])               # 依頼の欄を読まない節は触らない

    def test_intake_rejects_unknown_key(self):
        r = check_request(load("request_extra_key"), self.board, "持ち主")
        self.assertFalse(r["ok"])
        self.assertIn("severity", r["reason"])
        self.assertFalse((self.board / "request.json").exists())

    def test_intake_rejects_non_list(self):
        r = check_request({"where": "stats.py", "text": "x"}, self.board, "持ち主")
        self.assertFalse(r["ok"])


class TestJudge(AcceptCase):
    def test_judge_accepts_good_reply(self):
        check_request(load("request_ok"), self.board, "持ち主")
        r = check_judge(load("judge_ok"), self.board, self.base, self.repo)
        self.assertTrue(r["ok"], r["reason"])
        self.assertTrue((self.board / "judgment.json").exists())
        self.assertEqual(r["judgment_file"], str(self.board / "judgment.json"))
        self.assertEqual(sorted(r["open_units"]), sorted(u["key"] for u in load("judge_ok")["units"] if u["label"] == "block"))

    def test_judge_tests_query_examples_itself(self):
        # core の check_judge を直に呼ぶ入口（script_io の例・golden）も class_query の例を試す。通れば例は judgment.json に戻り、
        # 外した例は query-examples.json に在る（blk-judge の judgetake を通らない道で、試していない例を盤面に書かない）
        reply = load("judge_ok")
        cq = reply["units"][0]["class_query"]
        cq["misses"] = ["    return sum(xs) / (len(xs) - 1)  # 直した"]
        r = check_judge(reply, self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("直した後の正しい形にも当たる", r["reason"])
        self.assertFalse((self.board / "judgment.json").exists())
        cq["misses"] = ["    return sum(xs) / len(xs)"]
        r = check_judge(reply, self.board, self.base, self.repo)
        self.assertTrue(r["ok"], r["reason"])
        doc = json.loads((self.board / "judgment.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["units"][0]["class_query"]["misses"], cq["misses"])
        self.assertIn(reply["units"][0]["key"], json.loads((self.board / "query-examples.json").read_text(encoding="utf-8")))

    def saved_examples(self):
        p = self.board / querytest.EXAMPLES_FILE
        self.assertTrue(p.is_file(), f"盤面に {querytest.EXAMPLES_FILE} が無い")
        return json.loads(p.read_text(encoding="utf-8"))

    def test_judge_marks_open_units_without_examples(self):
        # 49 件目（6fd8266f）の意図: 例の無い開いた単位は拒まず、印だけを盤面に書く（報告と最後の関所が unproven_lines で読む）
        reply = load("judge_ok")
        r = check_judge(reply, self.board, self.base, self.repo)
        self.assertTrue(r["ok"], r["reason"])
        keys = [u["key"] for u in reply["units"]]
        self.assertEqual(self.saved_examples(), {k: {querytest.UNPROVEN: querytest.NO_EXAMPLES} for k in keys})
        doc = json.loads((self.board / "judgment.json").read_text(encoding="utf-8"))
        self.assertEqual([u["class_query"] for u in doc["units"]], [u["class_query"] for u in reply["units"]])
        self.assertEqual(querytest.unproven_lines(self.board), [f"{k}: {querytest.NO_EXAMPLES}" for k in keys])

    def test_judge_mixes_examples_and_marks(self):
        reply = load("judge_ok")
        cq = reply["units"][0]["class_query"]
        cq["hits"], cq["misses"] = ["    return sum(xs) / (len(xs) - 1)"], ["    return sum(xs) / len(xs)"]
        r = check_judge(reply, self.board, self.base, self.repo)
        self.assertTrue(r["ok"], r["reason"])
        first, second = (u["key"] for u in reply["units"])
        self.assertEqual(self.saved_examples(), {first: {"hits": cq["hits"], "misses": cq["misses"]},
                                                 second: {querytest.UNPROVEN: querytest.NO_EXAMPLES}})
        doc = json.loads((self.board / "judgment.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["units"][0]["class_query"], cq)
        self.assertNotIn(querytest.UNPROVEN, doc["units"][1]["class_query"])

    def test_judge_replace_drops_previous_round(self):
        # 2 度目の判定は前の周の例も印も捨てる。例も印も無い判定は、ファイルが在れば空に置き換え、無ければ作らない
        reply = load("judge_ok")
        cq = reply["units"][0]["class_query"]
        cq["hits"], cq["misses"] = ["    return sum(xs) / (len(xs) - 1)"], ["    return sum(xs) / len(xs)"]
        self.assertTrue(check_judge(reply, self.board, self.base, self.repo)["ok"])
        self.assertTrue(check_judge(load("judge_ok"), self.board, self.base, self.repo)["ok"])
        self.assertEqual(self.saved_examples(), {u["key"]: {querytest.UNPROVEN: querytest.NO_EXAMPLES}
                                                 for u in reply["units"]})
        self.assertTrue(check_judge(load("judge_no_fix"), self.board, self.base, self.repo)["ok"])
        self.assertEqual(self.saved_examples(), {})
        (self.board / querytest.EXAMPLES_FILE).unlink()
        self.assertTrue(check_judge(load("judge_no_fix"), self.board, self.base, self.repo)["ok"])
        self.assertFalse((self.board / querytest.EXAMPLES_FILE).exists())

    def test_judge_empty_base_rev_reads_head(self):
        # Ruling R2: base_rev が空なら repo の HEAD をその場で読む
        r = check_judge(load("judge_ok"), self.board, "", self.repo)
        self.assertTrue(r["ok"], r["reason"])

    def test_judge_missing_units(self):
        no_units = load("judge_ok")
        del no_units["units"]
        r = check_judge(no_units, self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("units", r["reason"])
        self.assertFalse((self.board / "judgment.json").exists())

    def test_judge_rejects_precedent_without_searched(self):
        r = check_judge(load("judge_notfound_no_searched"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("searched", r["reason"])

    def test_judge_rejects_dirty_tree(self):
        (self.repo / "extra.txt").write_text("読むだけの役が書いた\n")
        r = check_judge(load("judge_ok"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("extra.txt", r["reason"])
        self.assertFalse((self.board / "judgment.json").exists())

    def test_judge_rejects_ignored_file_without_snapshot(self):
        # 写しが無い時も、git が無視するファイル（__pycache__ など）を読むだけの役が作れば拒む
        (self.repo / "__pycache__").mkdir()
        (self.repo / "__pycache__" / "stats.cpython-314.pyc").write_bytes(b"x")
        r = check_judge(load("judge_ok"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("__pycache__", r["reason"])

    def test_judge_rejects_ignored_file_after_snapshot(self):
        # 依頼の受け付けの時の写し（judge-snapshot.json）の後に、git が無視するファイルが増えた・書き換わったら拒む。
        # 前から在った無視されるファイルは、変わっていなければ通る
        (self.repo / "__pycache__").mkdir()
        old = self.repo / "__pycache__" / "old.pyc"
        old.write_bytes(b"old")
        (self.board / "judge-snapshot.json").write_text(json.dumps(tree_state(self.repo)))
        self.assertTrue(check_judge(load("judge_ok"), self.board, self.base, self.repo)["ok"])
        (self.repo / ".env.pyc").write_bytes(b"x")
        r = check_judge(load("judge_ok"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn(".env.pyc", r["reason"])
        (self.repo / ".env.pyc").unlink()
        old.write_bytes(b"new")
        r = check_judge(load("judge_ok"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"], "無視されるファイルの中身の書き換えも拒む")
        self.assertIn("作業ツリー", r["reason"])

    def test_judge_carried_r1_tells_to_copy_the_where(self):
        # graphloops 0.21.0 の _carried_r1_accounted は、前の周の R1 の削除候補に無い where を拒むとき『貼られた行の no で指せ』と
        # 案内する。works の判定役には番号の一覧を貼らないので、where を字面のまま写せと返す。
        # 今の works は 1 周だけで盤面に前の周の R1 が無く、この道は通らない——前の周の R1 を持つ盤面を差して通す
        import accept
        scratch = accept.DiskBoard.scratch

        def prev_r1_board(*a, **kw):
            b = scratch(*a, **kw)
            b.new_round()
            b.state["outputs"] = {"r1.minimality": {"round": 1}}
            b.outputs = lambda before_round=None: {"r1.minimality": {"deletions": [{"where": "stats.py:3"}]}}
            return b

        reply = load("judge_ok")
        reply["carried_r1"] = [{"where": "stats.py:4", "disposition": "decline", "why": "削除すると mean が壊れる"},
                               {"where": "stats.py:3", "disposition": "decline", "why": "削除すると mean が壊れる"}]
        with mock.patch.object(accept.DiskBoard, "scratch", prev_r1_board):
            r = check_judge(reply, self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("carried_r1[0] の where 'stats.py:4'", r["reason"])
        self.assertIn("削除候補の where を字面のまま写せ", r["reason"])
        self.assertNotIn("no で指せ", r["reason"])
        self.assertFalse((self.board / "judgment.json").exists())

    def test_judge_rejects_non_object(self):
        r = check_judge("units", self.board, self.base, self.repo)
        self.assertFalse(r["ok"])


class TestSnapshot(AcceptCase):
    def test_snapshot_sees_ignored_content(self):
        (self.repo / "__pycache__").mkdir()
        pyc = self.repo / "__pycache__" / "stats.cpython-314.pyc"
        pyc.write_bytes(b"a")
        before = snapshot_tree(self.repo)
        self.assertEqual(before["ignored"], ["__pycache__/"])
        self.assertEqual(before["porcelain"], "", "porcelain は無視されるファイルを映さない（だから ignored が要る）")
        pyc.write_bytes(b"b")
        self.assertNotEqual(before["diff_sha256"], snapshot_tree(self.repo)["diff_sha256"])

    def test_snapshot_skips_cli_write_ledger(self):
        # Claude Code 2.1.283 が役の cwd に作る空のフォルダ .claude/.cc-writes/（台帳 R62・自分食い 23 件目で読むだけの役が 3 回拒まれた）
        (self.repo / ".gitignore").write_text(".claude/\n")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-qm", "ignore")
        before = snapshot_tree(self.repo)
        (self.repo / ".claude" / ".cc-writes").mkdir(parents=True)
        (self.repo / ".claude" / ".cc-writes" / "w").write_bytes(b"x")
        self.assertEqual(snapshot_tree(self.repo), before)
        (self.repo / ".claude" / "other").write_bytes(b"x")    # 同じ .claude/ の下でも、ほかの物は見る
        self.assertNotEqual(snapshot_tree(self.repo), before)

    def test_snapshot_skips_nested_cli_write_ledger(self):
        # run 30: 役の Bash が cd した先（works/docs/specs）にも Claude Code が空の .claude/.cc-writes/ を作り、git の全体の除外
        # （.claude/.cc-writes/）で `!! works/docs/specs/.claude/.cc-writes/` に出た。深さを問わず数えない
        (self.repo / "docs" / "specs").mkdir(parents=True)
        (self.repo / "docs" / "specs" / "a.md").write_text("a\n")
        (self.repo / ".gitignore").write_text(".claude/.cc-writes/\n")
        git(self.repo, "add", ".gitignore", "docs")
        git(self.repo, "commit", "-qm", "ignore")
        before = snapshot_tree(self.repo)
        (self.repo / "docs" / "specs" / ".claude" / ".cc-writes").mkdir(parents=True)
        self.assertEqual(snapshot_tree(self.repo), before)
        (self.repo / "docs" / "specs" / ".claude" / ".cc-writes" / "settings.json.tmp.0a1b2c3d").write_bytes(b"x")
        self.assertEqual(snapshot_tree(self.repo), before)
        (self.repo / "docs" / "specs" / ".claude" / "other").write_bytes(b"x")    # 同じ .claude/ の下でも、ほかの物は見る
        self.assertNotEqual(snapshot_tree(self.repo), before)

    def test_snapshot_skips_nested_collapsed_cli_dir(self):
        # 対象の .gitignore が .claude/ を無視すると、git は深い所の物も `<dir>/.claude/` に畳む。中身が控えのフォルダだけなら数えない
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "a.md").write_text("a\n")
        (self.repo / ".gitignore").write_text(".claude/\n")
        git(self.repo, "add", ".gitignore", "docs")
        git(self.repo, "commit", "-qm", "ignore")
        before = snapshot_tree(self.repo)
        (self.repo / "docs" / ".claude" / ".cc-writes").mkdir(parents=True)
        (self.repo / "docs" / ".claude" / ".cc-writes" / "w.tmp.0a1b2c3d").write_bytes(b"x")
        self.assertEqual(snapshot_tree(self.repo), before)
        (self.repo / "docs" / ".claude" / "settings.local.json").write_bytes(b"{}")
        self.assertNotEqual(snapshot_tree(self.repo), before)

    def test_snapshot_skips_untracked_cli_write_ledger(self):
        # 除外の規則が無い対象: 空の控えは git に出ないが、書きかけの一時ファイルが残ると未追跡に出る。これも数えない。
        # Claude Code は全体の除外（~/.config/git/ignore）に **/.claude/.cc-writes/ を足すので、ここではそれを読ませない
        git(self.repo, "config", "core.excludesFile", os.devnull)
        before = snapshot_tree(self.repo)
        (self.repo / "sub" / ".claude" / ".cc-writes").mkdir(parents=True)
        (self.repo / "sub" / ".claude" / ".cc-writes" / "x.json.tmp.0a1b2c3d").write_bytes(b"x")
        self.assertEqual(snapshot_tree(self.repo), before)
        (self.repo / "sub" / "real.txt").write_text("x\n")
        self.assertNotEqual(snapshot_tree(self.repo), before)

    def test_snapshot_sees_untracked_content(self):
        (self.repo / "new.txt").write_text("a\n")
        before = snapshot_tree(self.repo)
        (self.repo / "new.txt").write_text("b\n")
        self.assertEqual(before["porcelain"], snapshot_tree(self.repo)["porcelain"])
        self.assertNotEqual(before["diff_sha256"], snapshot_tree(self.repo)["diff_sha256"])


class TestTreeState(AcceptCase):
    """読むだけの任せ先の役（blk-pr・blk-ci）の前後の作業ツリーの姿（tree_state）と、その違いの文（tree_change）"""

    def test_change_names_content_when_porcelain_is_same(self):
        # 既に変えてあるファイルの中身をさらに書き換えた: porcelain の行は同じまま。違いは差分の中身だと言う（審査 M4）
        with open(self.repo / "stats.py", "a") as f:
            f.write("# 前から在った変更\n")
        before = tree_state(self.repo)
        with open(self.repo / "stats.py", "a") as f:
            f.write("# 役が書いた\n")
        moved = tree_change(before, tree_state(self.repo))
        self.assertTrue(moved)
        self.assertFalse([m for m in moved if m.startswith("git status --porcelain")], moved)
        self.assertTrue([m for m in moved if "中身が変わった" in m], moved)

    def test_change_ignored_only_has_no_porcelain_noise(self):
        # 無視されるパスだけが増えた: porcelain の空の行（『前 [] / 今 []』）を出さない（審査 M4）
        before = tree_state(self.repo)
        (self.repo / "__pycache__").mkdir()
        (self.repo / "__pycache__" / "stats.cpython-314.pyc").write_bytes(b"x")
        moved = tree_change(before, tree_state(self.repo))
        self.assertFalse([m for m in moved if m.startswith("git status --porcelain")], moved)
        self.assertTrue([m for m in moved if "増えた ['__pycache__/']" in m], moved)

    def test_change_shows_porcelain_when_it_differs(self):
        before = tree_state(self.repo)
        (self.repo / "new.txt").write_text("x\n")
        moved = tree_change(before, tree_state(self.repo))
        self.assertIn("git status --porcelain: 役を起こす前 [] / 今 ['?? new.txt']", moved)
        self.assertEqual(tree_change(before, before), [])

    def test_ignored_entries_skip_origin_of_worktree_rename(self):
        # 作業ツリーの rename（intent-to-add を伴う。Y の欄が R）は元の名前の欄が続く。X だけ見ると元の名前を読み違える（審査 M5）
        (self.repo / "!! old.txt").write_text("a\nb\nc\nd\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "old")
        (self.repo / "!! old.txt").rename(self.repo / "new.txt")
        git(self.repo, "add", "-N", "new.txt")
        z = subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain", "-z"], capture_output=True, check=True).stdout
        self.assertTrue(z.startswith(b" R new.txt\0!! old.txt\0"), z)
        self.assertEqual(_ignored_entries(self.repo), [])


class TestRoleSchema(unittest.TestCase):
    def test_role_schema_resolves_refs(self):
        self.assertNotIn("$ref", json.dumps(role_schema("p2.diagnose")))

    def test_role_schema_drops_notes_but_keeps_note_fields(self):
        s = role_schema("p2.diagnose")
        self.assertNotIn("note", s)
        self.assertNotIn("note", s["properties"]["units"]["items"]["properties"]["class_query"]["properties"]["how"])
        # router の行は note という名前の欄を必須に持つ——注記と一緒に欄まで落とすと、どの行も型を通らない
        router = s["properties"]["router"]["items"]
        self.assertIn("note", router["required"])
        self.assertIn("note", router["properties"])

    def test_pointer_fields_stay_names(self):
        # graphloops 0.21.0 は pointers の位置（番号で指す欄）の型を [integer, string] に広げる。既定（numbered=False）は
        # 番号の控えを固めない役の型で、番号を名前に戻す段が無いので、名前（文字列）の型のまま役に渡す
        where = role_schema("p2.diagnose")["properties"]["carried_r1"]["items"]["properties"]["where"]
        self.assertEqual(where, {"type": "string", "minLength": 1})
        key = role_schema("p3.delta_review")["properties"]["checks"]["items"]["properties"]["key"]
        self.assertEqual(key, {"type": "string", "minLength": 8})
        # 番号を貼る節も、numbered を渡さなければ名前の型のまま（開くのは planblk.output_format だけ）
        keys = role_schema("p2.fix_plan")["properties"]["plan"]["items"]["properties"]["unit_keys"]["items"]
        self.assertEqual(keys, {"type": "string", "minLength": 1})

    def test_delta_kinds_exclude_plan_only(self):
        kind = role_schema("p3.delta_review")["properties"]["faces"]["items"]["properties"]["kind"]
        self.assertEqual(kind["enum"], ["copy", "entrance", "contract_drift", "dead_path", "scope_creep"])

    def test_good_replies_pass_role_schema(self):
        from engine.schema import validate_schema
        self.assertEqual(validate_schema(load("judge_ok"), role_schema("p2.diagnose")), [])
        self.assertEqual(validate_schema(load("delta_ok"), role_schema("p3.delta_review")), [])


if __name__ == "__main__":
    unittest.main()
