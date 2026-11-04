#!/usr/bin/env python3
"""attention/scripts/lib/people.py（その件に関わっている人の事実）を pin する回帰テスト。GitHub には触らない。

/whose-turn・/catchup・/milestone-map は、担当者・Linked PR の作者・閉じた人・レビューの依頼先の事実を people.py から
読み、その上に自分の規則（誰のターンか・誰が進めているか）を組む。事実ごとに、持ち主の言葉か実測を添えて止める。
もう 1 つ、ほかのスクリプトが同じ事実を自分で読み直していないことを字で見る（Readback）。読み直すと、片方だけ直って
食い違う（持ち主 2026-11-04「それぞれ担保してるロジックはmyturnと共有してるだろうが、それを綺麗に担保していかないと
修正で崩れるのは怖いね。例えばさっきいれたPRが入ってれば実質担当だみたいなのとか」）。
"""

import importlib.util
import pathlib
import re
import sys
import unittest

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "attention" / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))
import people  # noqa: E402
import turn  # noqa: E402

_spec = importlib.util.spec_from_file_location("milestone_map", SCRIPTS / "milestone-map.py")
mm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mm)


def user(login):
    return {"__typename": "User", "login": login}


def bot(login):
    return {"__typename": "Bot", "login": login}


def mannequin(login):
    return {"__typename": "Mannequin", "login": login}


def assigned(*actors, unknown=False):
    node = {"assignees": {"totalCount": len(actors), "nodes": list(actors)}}
    if unknown:
        node["assigneeKindsUnknown"] = True
    return node


def closed(who=(), pr_by=None, actor=None, actor_bot=False, reason="COMPLETED", events=True):
    """閉じた issue の生の材料。pr_by は閉じた PR の作者（None なら PR でなく閉じた）、actor は閉じる操作をした人。"""
    ev = {"closer": {"__typename": "PullRequest", "author": user(pr_by)} if pr_by else None,
          "actor": (bot if actor_bot else user)(actor) if actor else None}
    return {"stateReason": reason, "assignees": {"nodes": [user(w) for w in who]},
            "timelineItems": {"nodes": [ev] if events else []}}


class Login(unittest.TestCase):
    def test_deleted_account_is_none(self):
        # 実測: 退会済みのアカウントは author・actor が null で返る（GitHub の「ghost」）
        self.assertIsNone(people.login(None))
        self.assertEqual(people.login(user("a")), "a")
        self.assertEqual(people.login(bot("Copilot")), "Copilot")


class Answerable(unittest.TestCase):
    """返答できる人は User だけ（attention の CHANGELOG「人に数えるのは返答できるアカウント（User）だけで、Copilot
    などの Bot・Mannequin（他のサービスから移した履歴の、実在しない名義）・退会済みは数えない」）。"""

    def test_user_only(self):
        self.assertEqual(people.answerable(user("a")), "a")
        for nobody in (bot("Copilot"), mannequin("old"), {"__typename": "Organization", "login": "o"}, None):
            self.assertIsNone(people.answerable(nobody), nobody)
        # login の有無で見分けない（クエリに Bot { login } を足した途端 Bot が人になる）
        self.assertIsNone(people.answerable({"login": "x"}))

    def test_assigned_people(self):
        self.assertEqual(people.assigned_people(assigned(user("a"), bot("Copilot"), mannequin("m"))), ["a"])
        # 種別を返さない GitHub（GHES など、assignedActors が無い）では、人か Bot か分からないので login の取れた全員
        self.assertEqual(people.assigned_people(assigned({"login": "a"}, {"login": "Copilot"}, {}, unknown=True)),
                         ["a", "Copilot"])


class Logins(unittest.TestCase):
    def test_bots_stay_in_github_order(self):
        # 表示と「誰が進めているか」には Bot も入れる。Copilot を Assignees に入れると Copilot が進めて PR を出す
        # （https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github
        # 「You can ask Copilot to start working on an issue by assigning the issue to Copilot.」）
        self.assertEqual(people.logins(assigned(bot("Copilot"), user("a"))), ["Copilot", "a"])
        self.assertEqual(people.logins(assigned()), [])


class BotAssignee(unittest.TestCase):
    """Copilot だけに振った issue は、/milestone-map では Copilot が進めている物、ターンの規則では誰にも渡っていない物。
    問いが違う（進めている者か・返答できる人か）ので揃えない、を 1 か所で止める。"""

    def test_map_counts_it_turn_does_not(self):
        node = assigned(bot("Copilot"))
        self.assertEqual(mm.doers(people.logins(node), []), ["Copilot"])
        self.assertEqual(people.assigned_people(node), [])
        self.assertIs(turn.assigned_people, people.assigned_people)


class LinkedPrs(unittest.TestCase):
    """閉じる PR を出した人も実質の担当（持ち主 2026-11-04「PRをやってclosesに入れた人も実質担当じゃないかな」）。
    その材料は、issue を閉じる Linked PR（closedByPullRequestsReferences）の番号と作者。"""

    def test_open_only_and_deleted_author(self):
        issue = {"closedByPullRequestsReferences": {"nodes": [
            {"number": 7, "state": "OPEN", "author": user("dev")},
            {"number": 8, "state": "MERGED", "author": user("old")},
            {"number": 9, "state": "OPEN", "author": None},
            {"number": 10, "state": "OPEN", "author": bot("Copilot")},
        ]}}
        self.assertEqual(people.linked_prs(issue), [[7, "dev"], [9, None], [10, "Copilot"]])
        self.assertEqual(people.linked_prs(issue, "MERGED"), [[8, "old"]])
        self.assertEqual(people.linked_prs({}), [])
        self.assertEqual(people.linked_prs({"closedByPullRequestsReferences": None}), [])


class Closer(unittest.TestCase):
    """閉じた人と閉じ方。PR で閉じたらその PR の作者（持ち主 2026-11-04「PRをやってclosesに入れた人も実質担当じゃない
    かな」）。手で閉じた人は、担当者が居ないときだけ、完了で閉じ、Bot でないときだけ数える（頼み 1f27bb の見直しの指摘:
    stale の Bot や、重複を閉じて回った人が、仕事を終えた人に見えないように）。"""

    def test_by_pr(self):
        self.assertEqual(people.closer_of(closed(who=("a",), pr_by="dev")), ("dev", "pr"))
        self.assertEqual(people.closer_of(closed(pr_by="dev", reason="NOT_PLANNED")), ("dev", "pr"))

    def test_by_hand(self):
        self.assertEqual(people.closer_of(closed(actor="x")), ("x", "hand"))
        self.assertEqual(people.closer_of(closed(actor="x", reason=None)), ("x", "hand"))   # 古い GitHub は stateReason が無い
        self.assertEqual(people.closer_of(closed(who=("a",), actor="x")), (None, None))      # 担当者が実質の担当
        for reason in ("NOT_PLANNED", "DUPLICATE"):
            self.assertEqual(people.closer_of(closed(actor="x", reason=reason)), (None, None), reason)
        self.assertEqual(people.closer_of(closed(actor="stale", actor_bot=True)), (None, None))
        self.assertEqual(people.closer_of(closed(actor=None)), (None, None))                 # 退会済み
        self.assertEqual(people.closer_of(closed(actor="x", events=False)), (None, None))    # ClosedEvent が取れない


class RequestedPerson(unittest.TestCase):
    def test_user_or_team(self):
        # attention の CHANGELOG「Copilot などの Bot だけへの依頼は依頼に数えない（`/whose-turn` と同じ）」
        self.assertTrue(people.requested_person(user("a")))
        self.assertTrue(people.requested_person({"__typename": "Team", "name": "t"}))
        for nobody in (bot("Copilot"), mannequin("m"), {"login": "x"}, None):
            self.assertFalse(people.requested_person(nobody), nobody)


# 人の事実をほかのスクリプトが読み直している字。people.py と ghtext.py（is_bot）の外で当たれば赤
Q = "[\"']"
READBACK = {
    "人の種別を __typename の字で比べている":
        rf"__typename{Q}\)?\]?\s*(?:==|!=|in)\s*\(?[^)\n]*{Q}(?:User|Bot|Mannequin|Organization|Team){Q}",
    "担当者を自分で読んでいる": rf"assignees{Q}\]\s*\[\s*{Q}nodes|get\({Q}assignees{Q}\s*,\s*\{{\}}\)\s*\.get\({Q}nodes",
    "Linked PR を自分で読んでいる": rf"closedByPullRequestsReferences{Q}\s*[\]),]",
    "閉じた PR を自分で読んでいる": rf"(?:\.get\(|\[){Q}closer{Q}",
}
FACTS = {SCRIPTS / "lib" / "people.py", SCRIPTS / "lib" / "ghtext.py"}


def readbacks(text):
    return [why for why, pat in READBACK.items() if re.search(pat, text)]


class Readback(unittest.TestCase):
    def test_scripts_read_facts_from_people(self):
        hits = []
        scanned = [p for p in sorted(SCRIPTS.rglob("*.py")) if p not in FACTS]
        # 走査の空振りを防ぐ（場所を変えて 1 本も読まなくなっても緑にならない）
        self.assertTrue({"catchup.py", "whose-turn.py", "milestone-map.py", "turn.py"} <= {p.name for p in scanned})
        for path in scanned:
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                hits += [f"{path.relative_to(ROOT)}:{n}: {why}" for why in readbacks(line)]
        self.assertEqual(hits, [], "人の事実は attention/scripts/lib/people.py から読む")

    def test_patterns_catch_the_old_forms(self):
        # 検査の空振りを防ぐ。people.py へ移す前の、各スクリプトに在った字
        for old in ('return (reviewer or {}).get("__typename") in ("User", "Team")',
                    'return actor["login"] if (actor or {}).get("__typename") == "User" else None',
                    'who = [a["login"] for a in i["assignees"]["nodes"]]',
                    'for a in (a["login"] for a in node["assignees"]["nodes"]):',
                    'any(a["login"] != author for a in node["assignees"]["nodes"])',
                    'any(a["login"] == me for a in node.get("assignees", {}).get("nodes", []))',
                    "others = [n for n in map(login, pr['assignees']['nodes']) if n]",
                    'return node["combinedSlug"] if (node or {}).get("__typename") == "Team" else None',
                    'nodes = issue.get("closedByPullRequestsReferences", {}).get("nodes")',
                    'prs = (i.get("closedByPullRequestsReferences") or {}).get("nodes") or []',
                    'by = ((ev.get("closer") or {}).get("author") or {}).get("login")'):
            self.assertTrue(readbacks(old), old)
        # 種別でない __typename の比べ（PR か issue か）は当たらない
        self.assertEqual(readbacks('is_pr = node["__typename"] == "PullRequest"'), [])

    def test_commands_share_the_same_functions(self):
        # turn.py は people.py の事実を名前ごと引き継ぐだけで、同じ名前を自分で定義し直さない
        for name in ("ASSIGNEES", "KINDS_FIELD", "LEGACY_ASSIGNEES", "answerable", "assigned_people", "login"):
            self.assertIs(getattr(turn, name), getattr(people, name), name)
        for name in ("closer_of", "linked_prs", "logins"):
            self.assertIs(getattr(mm, name), getattr(people, name), name)


if __name__ == "__main__":
    unittest.main()
