"""sessions ノード: 開いている会話を (リポジトリ, 枝) の組にする。"""

import unittest

from . import DISPATCH  # noqa: F401
from . import schemacheck
from nodes import sessions

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


if __name__ == "__main__":
    unittest.main()
