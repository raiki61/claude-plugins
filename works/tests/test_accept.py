"""受け付けの口（.shared/core/accept.py）の検査。

良い返答の見本が通り、悪い見本（拒む理由が 1 つだけになるように作った物）が ok: False で拒まれるかを、
dev/target-seed/ を一時ディレクトリの git に写した使い捨ての対象リポジトリで見る。見本は tests/replies/ に在る。
"""
import json
import pathlib
import shutil
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

from accept import check_delta, check_fix, check_judge, check_request, role_schema, snapshot_tree  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
FIXED_STATS = '''"""直した後の姿。"""


def mean(xs):
    return sum(xs) / len(xs)


def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
'''


def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text())


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


class AcceptCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        shutil.copytree(SEED, self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "seed")
        self.base = git(self.repo, "rev-parse", "HEAD")
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
        (self.board / "judge-snapshot.json").write_text(json.dumps(snapshot_tree(self.repo)))
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

        class PrevR1Board(accept._Board):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.round = 2
                self.state["outputs"] = {"r1.minimality": {"round": 1}}

            def outputs(self, before_round=None):
                return {"r1.minimality": {"deletions": [{"where": "stats.py:3"}]}}

        reply = load("judge_ok")
        reply["carried_r1"] = [{"where": "stats.py:4", "disposition": "decline", "why": "削除すると mean が壊れる"},
                               {"where": "stats.py:3", "disposition": "decline", "why": "削除すると mean が壊れる"}]
        with mock.patch.object(accept, "_Board", PrevR1Board):
            r = check_judge(reply, self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("carried_r1[0] の where 'stats.py:4'", r["reason"])
        self.assertIn("削除候補の where を字面のまま写せ", r["reason"])
        self.assertNotIn("no で指せ", r["reason"])
        self.assertFalse((self.board / "judgment.json").exists())

    def test_judge_rejects_non_object(self):
        r = check_judge("units", self.board, self.base, self.repo)
        self.assertFalse(r["ok"])


class TestFix(AcceptCase):
    def test_fix_accepts_covering_reply(self):
        self.judged()
        r = check_fix(load("fix_ok"), self.board, self.base, self.repo)
        self.assertTrue(r["ok"], r["reason"])

    def test_fix_rejects_uncovered_unit(self):
        self.judged()
        r = check_fix(load("fix_missing_unit"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        covered = {c["unit_key"] for c in load("fix_missing_unit")["changes"]}
        missing = [u["key"] for u in load("judge_ok")["units"] if u["key"] not in covered]
        self.assertEqual(len(missing), 1)
        self.assertIn(missing[0], r["reason"])

    def test_fix_unknown_key_tells_to_copy_the_key(self):
        # graphloops 0.21.0 の拒否文は『貼られた単位の no で指せ』（番号の一覧を貼る graphloops の役向け）。works の修正役には
        # 番号の一覧が無く、unit_key は文字列だけを通すので、判定の key を字面のまま写せと返す
        self.judged()
        reply = load("fix_ok")
        reply["changes"][0]["unit_key"] += "（写し違い）"
        r = check_fix(reply, self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("判定の key を字面のまま写せ", r["reason"])
        self.assertNotIn("no で指せ", r["reason"])

    def test_fix_without_judgment(self):
        r = check_fix(load("fix_ok"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("judgment.json", r["reason"])


class TestDelta(AcceptCase):
    def fix_stats(self):
        (self.repo / "stats.py").write_text(FIXED_STATS)

    def test_delta_accepts_good_reply(self):
        self.fix_stats()
        r = check_delta(load("delta_ok"), self.board, self.base, self.repo)
        self.assertTrue(r["ok"], r["reason"])

    def test_delta_rejects_uncited_face(self):
        self.fix_stats()
        r = check_delta(load("delta_bad_cite"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("cite", r["reason"])

    def test_delta_face_on_untracked_file(self):
        # 触ったファイルは未追跡も含む（修正が足したファイルを審査が指せる）
        self.fix_stats()
        (self.repo / "helper.py").write_text("def helper():\n    return 1\n")
        reply = {"faces": [{"key": "helper.py 使われない関数", "kind": "dead_path", "where": "helper.py",
                            "cite": "def helper():", "why": "どこからも呼ばれない関数を修正が足している"}], "checks": []}
        r = check_delta(reply, self.board, self.base, self.repo)
        self.assertTrue(r["ok"], r["reason"])

    def test_delta_rejects_tree_changed_after_snapshot(self):
        # Ruling R3: cut が盤面に置いた写しと、受け付けの時の作業ツリーが違えば拒む
        self.fix_stats()
        (self.board / "delta-snapshot.json").write_text(json.dumps(snapshot_tree(self.repo)))
        self.assertTrue(check_delta(load("delta_ok"), self.board, self.base, self.repo)["ok"])
        with open(self.repo / "stats.py", "a") as f:
            f.write("# 審査役が書いた\n")
        r = check_delta(load("delta_ok"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("作業ツリー", r["reason"])

    def test_delta_rejects_ignored_file_after_snapshot(self):
        self.fix_stats()
        (self.board / "delta-snapshot.json").write_text(json.dumps(snapshot_tree(self.repo)))
        (self.repo / "__pycache__").mkdir()
        (self.repo / "__pycache__" / "stats.cpython-314.pyc").write_bytes(b"x")
        r = check_delta(load("delta_ok"), self.board, self.base, self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("__pycache__/", r["reason"])

    def test_snapshot_sees_ignored_content(self):
        (self.repo / "__pycache__").mkdir()
        pyc = self.repo / "__pycache__" / "stats.cpython-314.pyc"
        pyc.write_bytes(b"a")
        before = snapshot_tree(self.repo)
        self.assertEqual(before["ignored"], ["__pycache__/"])
        self.assertEqual(before["porcelain"], "", "porcelain は無視されるファイルを映さない（だから ignored が要る）")
        pyc.write_bytes(b"b")
        self.assertNotEqual(before["diff_sha256"], snapshot_tree(self.repo)["diff_sha256"])

    def test_delta_rejects_plan_only_kind(self):
        # graphloops 0.21.0 の face_kind は事前審査と共有で regression・policy・precedent を含むが、修正差分のレビューでは拒む語
        self.fix_stats()
        for kind in ("regression", "policy", "precedent"):
            reply = {"faces": [{"key": f"stats.py の {kind} の穴", "kind": kind, "where": "stats.py", "cite": "def clamp(x, lo, hi):",
                                "why": "修正差分のレビューが事前審査だけの語で穴を挙げている"}], "checks": []}
            r = check_delta(reply, self.board, self.base, self.repo)
            self.assertFalse(r["ok"], kind)
            # 型の段で拒む（役の型の enum に無い語）。rules の段の拒否文（works に無い r4.human_gate を指す）まで行かせない
            self.assertIn(f"値 '{kind}' が語彙", r["reason"])
            self.assertNotIn("事前審査だけの語", r["reason"])
            self.assertNotIn("r4.human_gate", r["reason"])
            self.assertFalse((self.board / "delta-review.json").exists())

    def test_snapshot_sees_untracked_content(self):
        (self.repo / "new.txt").write_text("a\n")
        before = snapshot_tree(self.repo)
        (self.repo / "new.txt").write_text("b\n")
        self.assertEqual(before["porcelain"], snapshot_tree(self.repo)["porcelain"])
        self.assertNotEqual(before["diff_sha256"], snapshot_tree(self.repo)["diff_sha256"])


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
        # graphloops 0.21.0 は pointers の位置（番号で指す欄）の型を [integer, string] に広げる。works の役には番号を振った
        # 一覧を貼らず、番号を名前に戻す段も無いので、名前（文字列）の型のまま役に渡す
        where = role_schema("p2.diagnose")["properties"]["carried_r1"]["items"]["properties"]["where"]
        self.assertEqual(where, {"type": "string", "minLength": 1})
        key = role_schema("p3.delta_review")["properties"]["checks"]["items"]["properties"]["key"]
        self.assertEqual(key, {"type": "string", "minLength": 8})

    def test_delta_kinds_exclude_plan_only(self):
        kind = role_schema("p3.delta_review")["properties"]["faces"]["items"]["properties"]["kind"]
        self.assertEqual(kind["enum"], ["copy", "entrance", "contract_drift", "dead_path", "scope_creep"])

    def test_good_replies_pass_role_schema(self):
        from engine.schema import validate_schema
        self.assertEqual(validate_schema(load("judge_ok"), role_schema("p2.diagnose")), [])
        self.assertEqual(validate_schema(load("delta_ok"), role_schema("p3.delta_review")), [])


if __name__ == "__main__":
    unittest.main()
