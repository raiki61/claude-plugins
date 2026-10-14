"""assign ノード: PR ごとに結末を 1 つ決める（設計書 2 節の 5）。"""

import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
from nodes import assign


def pr(n, head=None):
    return {"number": n, "title": f"t{n}", "head": head or f"feat/{n}", "url": f"u{n}", "role": "implementer", "days": 1}


def acct(name, eligible=True):
    return {"name": name, "command": f"c-{name}", "config_dir": None, "eligible": eligible}


def slot(ws, free=True, branch=None):
    return {"workspace": ws, "pane": f"{ws}:p1", "path": f"/r/{ws}", "branch": branch, "free": free,
            "reason": None if free else "agent"}


def outcomes(rows):
    return [(r["number"], r["outcome"], (r["slot"] or {}).get("workspace"), (r["account"] or {}).get("name"))
            for r in rows]


class Plan(unittest.TestCase):
    def test_open_conversation_on_same_repo_and_branch(self):
        rows = assign.plan("o/r", [pr(1), pr(2)], {("o/r", "feat/1")}, [acct("a")], [slot("w0"), slot("w1")])
        self.assertEqual(outcomes(rows), [(1, "already_open", None, None), (2, "assigned", "w0", "a")])

    def test_same_branch_name_in_another_repo_does_not_count(self):
        rows = assign.plan("o/r", [pr(1, "main")], {("o/other", "main")}, [acct("a")], [slot("w0")])
        self.assertEqual(rows[0]["outcome"], "assigned")

    def test_no_eligible_account(self):
        rows = assign.plan("o/r", [pr(1), pr(2)], set(), [acct("a", eligible=False)], [slot("w0")])
        self.assertEqual([r["outcome"] for r in rows], ["no_account", "no_account"])

    def test_all_go_to_the_first_eligible_account(self):
        accts = [acct("x", eligible=False), acct("a"), acct("b")]
        rows = assign.plan("o/r", [pr(1), pr(2)], set(), accts, [slot("w0"), slot("w1")])
        self.assertEqual([r["account"]["name"] for r in rows], ["a", "a"])

    def test_not_enough_slots_leaves_the_later_prs(self):
        rows = assign.plan("o/r", [pr(1), pr(2), pr(3)], set(), [acct("a")], [slot("w0"), slot("w1", free=False), slot("w2")])
        self.assertEqual(outcomes(rows), [(1, "assigned", "w0", "a"), (2, "assigned", "w2", "a"), (3, "no_slot", None, None)])

    def test_slot_already_on_the_head_branch_is_used_first(self):
        rows = assign.plan("o/r", [pr(1), pr(2)], set(), [acct("a")],
                           [slot("w0"), slot("w1"), slot("w2", branch="feat/2")])
        self.assertEqual(outcomes(rows), [(1, "assigned", "w0", "a"), (2, "assigned", "w2", "a")])

    def test_preferred_slot_is_not_given_away_to_an_earlier_pr(self):
        # w0 は PR 2 の枝にいる。PR 1 は設定の順の最初の空き w0 ではなく、PR 2 の取り分を残して w1 を取る
        rows = assign.plan("o/r", [pr(1), pr(2)], set(), [acct("a")], [slot("w0", branch="feat/2"), slot("w1")])
        self.assertEqual(outcomes(rows), [(1, "assigned", "w1", "a"), (2, "assigned", "w0", "a")])

    def test_order_follows_prs(self):
        rows = assign.plan("o/r", [pr(5), pr(3), pr(4)], set(), [acct("a")], [slot("w0"), slot("w1"), slot("w2")])
        self.assertEqual([r["number"] for r in rows], [5, 3, 4])

    def test_output_matches_schema(self):
        rows = assign.plan("o/r", [pr(1), pr(2)], {("o/r", "feat/2")}, [acct("a")], [slot("w0")])
        self.assertEqual(schemacheck.check({"schema": 1, "plan": rows}, schemacheck.schema("plan")), [])


if __name__ == "__main__":
    unittest.main()
