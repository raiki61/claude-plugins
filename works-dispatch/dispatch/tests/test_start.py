"""受け持ちの起こし方（[skills.start]）: 欄の読み（start ノード・tree）と、--start・--due を入口から。
git は一時のフォルダの本物、herdr・claude は偽物で回す。部署は test_deliver の Flow の常設の部署「調べ」（役 調べ役）。"""

import unittest

from . import test_deliver
import gitx
from nodes import deliver, provision, start, tree


def shape_text(start_table, role_line="resident = true", name="調べ"):
    return f"""
[[roles]]
name = "調べ役"
{role_line}

[[skills]]
id = "survey"
name = "{name}"
role = "調べ役"
[skills.start]
{start_table}
"""


class Fields(unittest.TestCase):
    def test_start_is_read_from_the_skill(self):
        problems = []
        got = tree._skills([{"name": "業務改革", "role": "作業",
                             "start": {"every": "7d", "report_to": "社長室", "brief": "docs/reform.md", "by": ["社長室"]}}],
                           "/c.toml", problems)
        self.assertEqual(problems, [])
        self.assertEqual(got[0]["start"], {"report_to": "社長室", "brief": "docs/reform.md", "text": None, "every": "7d",
                                           "by": ["社長室"]})

    def test_a_bad_start_is_dropped_with_every_reason(self):
        problems = []
        got = tree._skills([{"name": "x", "start": {"every": "1y", "text": "a", "brief": "b", "by": "社長室"}}], "/c.toml", problems)
        self.assertIsNone(got[0]["start"])
        for want in ("report_to", "どちらか 1 つ", "every は数と単位", "by は会話の名前の並び"):
            self.assertIn(want, problems[0])

    def test_due_counts_from_the_last_sent_start_and_catches_up_once(self):
        st = {"every": "2h"}
        records = [{"kind": "start", "skill": "x", "status": "sent", "at": 100},
                   {"kind": "start", "skill": "x", "status": "failed", "at": 5000},
                   {"kind": "start", "skill": "y", "status": "sent", "at": 9000}]
        last = start.last_started(records, "x")
        self.assertEqual(last, 100)
        self.assertFalse(start.due(st, last, 100 + 7199))
        self.assertTrue(start.due(st, last, 100 + 7200 * 5))   # 過ぎた回が幾つ有っても、起こすのは今の 1 回
        self.assertTrue(start.due(st, None, 0))
        self.assertFalse(start.due({"every": None}, None, 0))   # 周期の無い物は命令でだけ起こす

    def test_branch_of_a_started_department(self):
        self.assertEqual(start.branch({"id": "Org_Reform"}, "20261017-010203-a1b2c3"), "work/org-reform-a1b2c3")
        self.assertEqual(start.branch({"id": None}, "20261017-010203-a1b2c3"), "work/start-a1b2c3")


class Start(unittest.TestCase):
    Flow = test_deliver.Flow
    setUp, main, prompts, shape = Flow.setUp, Flow.main, Flow.prompts, Flow.shape
    del Flow

    def starts(self):
        return [r for r in deliver.records(self.inbox) if r.get("kind") == "start"]

    def test_start_asks_the_resident_department_and_reports_to_report_to(self):
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
        self.shape(shape_text('report_to = "社長室"\ntext = "部署の作りを見直す"'))
        rc, out = self.main(self.src, "--start", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertIn("起こした: ", out)
        self.assertEqual(len(self.prompts()), 1)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["boss"], attrs.get("boss-session")), ("社長室", None))   # 起こした会話でなく report_to に返る
        self.assertEqual(attrs["boss-inbox"], self.inbox)
        brief = next(r["file"] for r in deliver.records(self.inbox) if r.get("kind") == "ask")
        with open(brief, encoding="utf-8") as f:
            self.assertIn("受け持ち「調べ」の起こし方（[skills.start]）で、命令（desk）が起こした頼みです。", f.read())
        (rec,) = self.starts()
        self.assertEqual((rec["skill"], rec["status"], rec["report_to"]), ("調べ", "sent", "社長室"))

    def test_by_limits_who_may_start_by_command(self):
        self.shape(shape_text('report_to = "社長室"\ntext = "見直す"\nby = ["社長室"]'))
        rc, out = self.main(self.src, "--start", "調べ", "--from-name", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("命令で起こせるのは 社長室（会社の形の by）。打った会話は 段取り", out)
        self.assertEqual(self.prompts(), [])
        rc, out = self.main(self.src, "--start", "調べ", "--from-name", "段取り", "--dry-run")   # 試し打ちは止めずに先まで見立てる
        self.assertEqual(rc, 2, out)   # 終了の値は本当に打った時と同じ
        self.assertIn("本当に打てばここで止まる", out)
        self.assertIn("起こす: ", out)

    def test_a_person_outside_claude_code_may_always_start(self):
        self.shape(shape_text('report_to = "社長室"\ntext = "見直す"\nby = ["社長室"]'))
        self.ports.env = {}
        rc, out = self.main(self.src, "--start", "調べ", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("起こす: ", out)
        self.assertIn("命令（人）", out)

    def test_a_one_off_skill_is_not_started_while_the_last_run_stands(self):
        self.shape(shape_text('report_to = "社長室"\ntext = "見直す"\nevery = "1d"', role_line=""))
        rc, out = self.main(self.src, "--start", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("前の回の部署がまだ立っている", out)
        self.assertEqual((self.prompts(), self.starts()), ([], []))

    def test_due_starts_only_what_is_due(self):
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
        self.shape(shape_text('report_to = "社長室"\ntext = "見直す"\nevery = "1d"'))
        rc, out = self.main(self.src, "--due")
        self.assertEqual(rc, 0, out)
        self.assertIn("起こした: ", out)
        self.assertIn("周期（1d ごと）", out)
        rc, out = self.main(self.src, "--due")   # 起こしたばかりなので、まだ来ていない
        self.assertEqual(rc, 0, out)
        self.assertIn("周期の来た受け持ちは無い", out)
        self.assertEqual(len(self.starts()), 1)

    def test_skill_without_start_cannot_be_started(self):
        self.shape('[[roles]]\nname = "調べ役"\n[[skills]]\nname = "調べ"\nrole = "調べ役"\n')
        rc, out = self.main(self.src, "--start", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("起こし方（[skills.start]）の有る受け持ち「調べ」が無い", out)


if __name__ == "__main__":
    unittest.main()
