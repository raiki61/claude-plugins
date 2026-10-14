"""assign ノード: PR ごとに結末を 1 つ決める（設計書 2 節の 4）。"""

import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
from config import Repo
from nodes import assign

REPO = Repo("o/r", "s", "/src/r", "/clones", ())


def pr(n, head=None):
    return {"number": n, "title": f"t{n}", "head": head or f"feat/{n}", "url": f"u{n}", "role": "implementer", "days": 1}


def acct(name, eligible=True):
    return {"name": name, "command": f"c-{name}", "config_dir": None, "eligible": eligible}


def outcomes(rows):
    return [(r["number"], r["outcome"], (r["account"] or {}).get("name")) for r in rows]


class Plan(unittest.TestCase):
    def test_open_conversation_on_same_repo_and_branch(self):
        rows = assign.plan(REPO, [pr(1), pr(2)], {("o/r", "feat/1")}, set(), [acct("a")])
        self.assertEqual(outcomes(rows), [(1, "already_open", None), (2, "assigned", "a")])

    def test_open_conversation_inside_the_pr_clone(self):
        rows = assign.plan(REPO, [pr(1)], set(), {"/clones/r-pr-1/backend"}, [acct("a")])
        self.assertEqual(rows[0]["outcome"], "already_open")

    def test_conversation_in_a_similar_folder_does_not_count(self):
        rows = assign.plan(REPO, [pr(1)], set(), {"/clones/r-pr-10"}, [acct("a")])
        self.assertEqual(rows[0]["outcome"], "assigned")

    def test_same_branch_name_in_another_repo_does_not_count(self):
        rows = assign.plan(REPO, [pr(1, "main")], {("o/other", "main")}, set(), [acct("a")])
        self.assertEqual(rows[0]["outcome"], "assigned")

    def test_no_eligible_account(self):
        rows = assign.plan(REPO, [pr(1), pr(2)], set(), set(), [acct("a", eligible=False)])
        self.assertEqual([r["outcome"] for r in rows], ["no_account", "no_account"])

    def test_all_go_to_the_first_eligible_account_with_their_clone_path(self):
        rows = assign.plan(REPO, [pr(1), pr(2)], set(), set(), [acct("x", eligible=False), acct("a"), acct("b")])
        self.assertEqual([(r["account"]["name"], r["clone_path"]) for r in rows],
                         [("a", "/clones/r-pr-1"), ("a", "/clones/r-pr-2")])

    def test_order_follows_prs(self):
        rows = assign.plan(REPO, [pr(5), pr(3), pr(4)], set(), set(), [acct("a")])
        self.assertEqual([r["number"] for r in rows], [5, 3, 4])

    def test_output_matches_schema(self):
        rows = assign.plan(REPO, [pr(1), pr(2)], {("o/r", "feat/2")}, set(), [acct("a")])
        self.assertEqual(schemacheck.check({"schema": 1, "plan": rows}, schemacheck.schema("plan")), [])


if __name__ == "__main__":
    unittest.main()
