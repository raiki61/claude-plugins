"""sessions ノード（開いている会話を (リポジトリ, 枝) の組にする）と、作業場のノードの約束。"""

import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
from config import Repo, Slot
from nodes import sessions, slots

REPOS = {"/r/w0": "o/r", "/r/w1": "o/r", "/other/x": "o/other", "/r/w0/sub": "o/r"}
BRANCHES = {"/r/w0": "feat/7", "/r/w1": "main", "/other/x": "main", "/r/w0/sub": "feat/7"}


def origin_of(cwd):
    return REPOS.get(cwd)


def branch_of(cwd):
    return BRANCHES.get(cwd)


class Sessions(unittest.TestCase):
    def test_merges_accounts_and_reads_repo_and_branch(self):
        listed = {"a1": [{"cwd": "/r/w0", "sessionId": "s1", "status": "idle"}],
                  "a2": [{"cwd": "/other/x", "sessionId": "s2", "state": "blocked"}]}
        got = sessions.collect(listed, branch_of, origin_of)
        self.assertEqual([(s["account"], s["repo"], s["branch"], s["status"]) for s in got],
                         [("a1", "o/r", "feat/7", "idle"), ("a2", "o/other", "main", "blocked")])

    def test_same_branch_name_in_another_repo_is_a_different_key(self):
        listed = {"a1": [{"cwd": "/r/w1", "sessionId": "s1"}, {"cwd": "/other/x", "sessionId": "s2"}]}
        keys = sessions.open_keys(sessions.collect(listed, branch_of, origin_of))
        self.assertEqual(keys, {("o/r", "main"), ("o/other", "main")})

    def test_unreadable_cwd_is_not_a_key(self):
        listed = {"a1": [{"cwd": "/tmp/nogit", "sessionId": "s1"}, {"sessionId": "s2"}]}
        got = sessions.collect(listed, branch_of, origin_of)
        self.assertEqual(sessions.open_keys(got), set())
        self.assertEqual(len(got), 2)

    def test_output_matches_schema(self):
        listed = {"a1": [{"cwd": "/r/w0", "sessionId": "s1", "status": "idle"}, {"sessionId": "s2"}]}
        out = {"schema": 1, "sessions": sessions.collect(listed, branch_of, origin_of)}
        self.assertEqual(schemacheck.check(out, schemacheck.schema("sessions")), [])


REPO = Repo("o/r", "second", (Slot("work0", "/r/w0"), Slot("work1", "/r/w1"), Slot("work2", "/r/w2")))
LABELS = {"wA": "work0", "wB": "work1", "wC": "work2"}


def panes(**over):
    base = {"work0": {"pane_id": "wA:p1", "workspace_id": "wA", "cwd": "/r/w0", "agent": None},
            "work1": {"pane_id": "wB:p1", "workspace_id": "wB", "cwd": "/r/w1", "agent": None},
            "work2": {"pane_id": "wC:p1", "workspace_id": "wC", "cwd": "/r/w2", "agent": None}}
    for k, v in over.items():
        if v is None:
            base.pop(k)
        else:
            base[k] = {**base[k], **v}
    return list(base.values())


def fixed(panes_, session_cwds=(), dirty=()):
    return slots.fixed(REPO, panes_, LABELS, set(session_cwds), branch_of, lambda p: p not in dirty)


def contract(test, impl):
    """作業場のノードの約束。差し替えの実装（PR ごとの作業フォルダなど）も同じ約束を通す。

    impl(panes, session_cwds, dirty) は slots の出力の並びを返す。
    """
    by = lambda rows: {r["workspace"]: r for r in rows}  # noqa: E731
    rows = by(impl(panes(), (), ()))
    test.assertTrue(all(r["free"] for r in rows.values()))
    rows = by(impl(panes(work0={"agent": "claude", "agent_status": "idle"}), (), ()))
    test.assertEqual((rows["work0"]["free"], rows["work0"]["reason"]), (False, "agent"))  # 入力待ちの会話も閉じない
    rows = by(impl(panes(), ("/r/w1",), ()))
    test.assertEqual((rows["work1"]["free"], rows["work1"]["reason"]), (False, "session"))
    rows = by(impl(panes(), (), ("/r/w2",)))
    test.assertEqual((rows["work2"]["free"], rows["work2"]["reason"]), (False, "dirty"))
    out = {"schema": 1, "slots": impl(panes(), (), ())}
    test.assertEqual(schemacheck.check(out, schemacheck.schema("slots")), [])


class FixedSlots(unittest.TestCase):
    def test_contract(self):
        contract(self, lambda p, s, d: fixed(p, s, d))

    def test_keeps_config_order_and_reports_branch(self):
        rows = fixed(panes())
        self.assertEqual([(r["workspace"], r["pane"], r["branch"]) for r in rows],
                         [("work0", "wA:p1", "feat/7"), ("work1", "wB:p1", "main"), ("work2", "wC:p1", None)])

    def test_missing_workspace(self):
        rows = fixed(panes(work2=None))
        self.assertEqual((rows[2]["free"], rows[2]["reason"], rows[2]["pane"]), (False, "no_pane", None))

    def test_session_below_the_path_counts(self):
        rows = fixed(panes(), session_cwds=("/r/w0/sub",))
        self.assertEqual(rows[0]["reason"], "session")

    def test_prefix_of_another_path_does_not_count(self):
        rows = fixed(panes(), session_cwds=("/r/w0x",))
        self.assertTrue(rows[0]["free"])

    def test_pane_in_another_folder(self):
        rows = fixed(panes(work1={"cwd": "/elsewhere"}))
        self.assertEqual(rows[1]["reason"], "path_mismatch")


if __name__ == "__main__":
    unittest.main()
