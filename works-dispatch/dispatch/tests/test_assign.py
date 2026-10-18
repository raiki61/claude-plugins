"""assign ノード: PR ごとに結末を 1 つ決める（設計書のセクション 2 の 4）。"""

import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
from config import Repo
from nodes import assign

REPO = Repo("o/r", "s", "/src/r", ())
PLACES = {"feat/1": "/w/r/feat-1", "feat/10": "/w/r/feat-10"}


def pr(n, head=None):
    return {"number": n, "title": f"t{n}", "head": head or f"feat/{n}", "url": f"u{n}", "role": "implementer", "days": 1}


def acct(name, eligible=True, seven=None, five=None, known=True):
    return {"name": name, "command": f"c-{name}", "config_dir": None, "eligible": eligible, "known": known,
            "seven_day": {"used": seven, "resets_at": None}, "five_hour": {"used": five, "resets_at": None}}


def names(rows):
    return [(r["account"] or {}).get("name") for r in rows]


def outcomes(rows):
    return [(r["number"], r["outcome"], (r["account"] or {}).get("name")) for r in rows]


class Plan(unittest.TestCase):
    def test_open_conversation_on_same_repo_and_branch(self):
        rows = assign.plan(REPO, [pr(1), pr(2)], {("o/r", "feat/1")}, set(), [acct("a")])
        self.assertEqual(outcomes(rows), [(1, "already_open", None), (2, "assigned", "a")])

    def test_open_conversation_inside_the_branch_place(self):
        rows = assign.plan(REPO, [pr(1)], set(), {"/w/r/feat-1/backend"}, [acct("a")], places=PLACES)
        self.assertEqual(rows[0]["outcome"], "already_open")

    def test_conversation_in_a_similar_folder_does_not_count(self):
        rows = assign.plan(REPO, [pr(1)], set(), {"/w/r/feat-10"}, [acct("a")], places=PLACES)
        self.assertEqual(rows[0]["outcome"], "assigned")

    def test_conversation_behind_a_symlink_counts_as_inside_the_place(self):
        import os
        import pathlib
        import tempfile
        real = pathlib.Path(tempfile.mkdtemp()).resolve()
        (real / "feat-1").mkdir()
        link = pathlib.Path(tempfile.mkdtemp()) / "w"
        os.symlink(real, link)
        rows = assign.plan(REPO, [pr(1)], set(), {str(real / "feat-1" / "backend")}, [acct("a")],
                           places={"feat/1": str(link / "feat-1")})
        self.assertEqual(rows[0]["outcome"], "already_open")

    def test_rows_carry_the_place_kind_and_fork(self):
        issue = {"number": 12, "kind": "issue", "title": "t", "head": None, "url": "i12"}
        rows = assign.plan(REPO, [pr(1), {**pr(2), "fork": True}, issue], set(), set(), [acct("a")], places=PLACES)
        self.assertEqual([(r["kind"], r["path"], r["fork"]) for r in rows],
                         [("pr", "/w/r/feat-1", False), ("pr", None, True), ("issue", None, False)])

    def test_same_branch_name_in_another_repo_does_not_count(self):
        rows = assign.plan(REPO, [pr(1, "main")], {("o/other", "main")}, set(), [acct("a")])
        self.assertEqual(rows[0]["outcome"], "assigned")

    def test_no_eligible_account(self):
        rows = assign.plan(REPO, [pr(1), pr(2)], set(), set(), [acct("a", eligible=False)])
        self.assertEqual([r["outcome"] for r in rows], ["no_account", "no_account"])

    def test_without_a_measured_cost_prs_are_dealt_one_by_one(self):
        # 1 件あたりの使用率をまだ測っていないうちは、1 つのアカウントに寄せない。順の頭から 1 件ずつ配る
        rows = assign.plan(REPO, [pr(1), pr(2), pr(3)], set(), set(), [acct("x", eligible=False), acct("a"), acct("b")])
        self.assertEqual([r["account"]["name"] for r in rows], ["a", "b", "a"])

    def test_the_soonest_account_takes_what_fits_below_the_limit(self):
        # 週 89%・1 件 1% なら、95% に届かずに入るのは 5 件（89 + 5 = 94）。あふれた分は次のアカウントへ
        accts = [acct("a", seven=89, five=5), acct("b", seven=40, five=5)]
        rows = assign.plan(REPO, [pr(n) for n in range(1, 8)], set(), set(), accts, 95, {"seven_day": 1.0, "five_hour": 0.5})
        self.assertEqual(names(rows), ["a"] * 5 + ["b"] * 2)

    def test_the_five_hour_window_also_caps(self):
        accts = [acct("a", seven=10, five=90), acct("b", seven=10, five=0)]
        rows = assign.plan(REPO, [pr(n) for n in range(1, 5)], set(), set(), accts, 95, {"seven_day": 0.1, "five_hour": 2.0})
        self.assertEqual(names(rows), ["a", "a", "b", "b"])

    def test_account_with_unknown_usage_takes_the_rest(self):
        accts = [acct("a", seven=93, five=0), acct("local", known=False)]
        rows = assign.plan(REPO, [pr(n) for n in range(1, 4)], set(), set(), accts, 95, {"seven_day": 1.0})
        self.assertEqual(names(rows), ["a", "local", "local"])

    def test_when_every_account_is_full_the_rest_gets_no_account(self):
        accts = [acct("a", seven=93, five=0)]
        rows = assign.plan(REPO, [pr(1), pr(2)], set(), set(), accts, 95, {"seven_day": 1.0})
        self.assertEqual([r["outcome"] for r in rows], ["assigned", "no_account"])

    def test_open_conversations_take_no_slot(self):
        accts = [acct("a", seven=93, five=0), acct("b", seven=10, five=0)]
        rows = assign.plan(REPO, [pr(1), pr(2)], {("o/r", "feat/1")}, set(), accts, 95, {"seven_day": 1.0})
        self.assertEqual(outcomes(rows), [(1, "already_open", None), (2, "assigned", "a")])

    def test_order_follows_prs(self):
        rows = assign.plan(REPO, [pr(5), pr(3), pr(4)], set(), set(), [acct("a")])
        self.assertEqual([r["number"] for r in rows], [5, 3, 4])

    def test_output_matches_schema(self):
        issue = {"number": 12, "kind": "issue", "title": "t", "head": None, "url": "i12"}
        rows = assign.plan(REPO, [pr(1), pr(2), issue], {("o/r", "feat/2")}, set(), [acct("a")], places=PLACES)
        self.assertEqual(schemacheck.check({"schema": 1, "plan": rows}, schemacheck.schema("plan")), [])


if __name__ == "__main__":
    unittest.main()
