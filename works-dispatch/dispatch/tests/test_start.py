"""受け持ちの起動方法（[skills.start]）: フィールドの読み（start ノード・tree）と、--start・--due を入口から。
git（tests/fakegit.py）・herdr・claude は偽物で回す。部署は test_deliver の Flow の永続の部署「調べ」（役 調べ役）。"""

import os
import pathlib
import unittest

from . import test_deliver
import starts
from nodes import deliver, provision, start, tree


def shape_text(start_table, role_line="persistent = true", name="調べ"):
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
        self.assertTrue(start.due(st, last, 100 + 7200 * 5))   # 過ぎた回が幾つ有っても、起動するのは今の 1 回
        self.assertTrue(start.due(st, None, 0))
        self.assertFalse(start.due({"every": None}, None, 0))   # 周期の無い物はコマンドでだけ起動する

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
        provision.mark(self.place, self.src, {"lifecycle": "persistent"}, self.g)
        self.shape(shape_text('report_to = "社長室"\ntext = "部署の作りを見直す"'))
        rc, out = self.main(self.src, "--start", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertIn("起動した: ", out)
        self.assertEqual(len(self.prompts()), 1)
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual((attrs["boss"], attrs.get("boss-session")), ("社長室", None))   # 起動した会話でなく report_to に返る
        self.assertEqual(attrs["boss-inbox"], self.inbox)
        brief = next(r["file"] for r in deliver.records(self.inbox) if r.get("kind") == "ask")
        with open(brief, encoding="utf-8") as f:
            self.assertIn("受け持ち「調べ」の起動方法（[skills.start]）で、コマンド（desk）が出した頼みです。", f.read())
        (rec,) = self.starts()
        self.assertEqual((rec["skill"], rec["status"], rec["report_to"]), ("調べ", "sent", "社長室"))

    def test_by_limits_who_may_start_by_command(self):
        self.shape(shape_text('report_to = "社長室"\ntext = "見直す"\nby = ["社長室"]'))
        rc, out = self.main(self.src, "--start", "調べ", "--from-name", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("コマンドで起動できるのは 社長室（会社の形の by）。打った会話は 段取り", out)
        self.assertEqual(self.prompts(), [])
        rc, out = self.main(self.src, "--start", "調べ", "--from-name", "段取り", "--dry-run")   # 試し打ちは止めずに先まで見立てる
        self.assertEqual(rc, 2, out)   # 終了の値は本当に打った時と同じ
        self.assertIn("本当に打てばここで止まる", out)
        self.assertIn("起動する: ", out)

    def test_a_person_outside_claude_code_may_always_start(self):
        self.shape(shape_text('report_to = "社長室"\ntext = "見直す"\nby = ["社長室"]'))
        self.ports.env = {}
        rc, out = self.main(self.src, "--start", "調べ", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("起動する: ", out)
        self.assertIn("コマンド（人）", out)

    def test_a_one_off_skill_is_not_started_while_the_last_run_stands(self):
        self.shape(shape_text('report_to = "社長室"\ntext = "見直す"\nevery = "1d"', role_line=""))
        rc, out = self.main(self.src, "--start", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("前の回の部署がまだ立っている", out)
        self.assertEqual((self.prompts(), self.starts()), ([], []))

    def test_due_starts_only_what_is_due(self):
        provision.mark(self.place, self.src, {"lifecycle": "persistent"}, self.g)
        self.shape(shape_text('report_to = "社長室"\ntext = "見直す"\nevery = "1d"'))
        rc, out = self.main(self.src, "--due")
        self.assertEqual(rc, 0, out)
        self.assertIn("起動した: ", out)
        self.assertIn("周期（1d ごと）", out)
        rc, out = self.main(self.src, "--due")   # 起動したばかりなので、まだ来ていない
        self.assertEqual(rc, 0, out)
        self.assertIn("周期の来た受け持ちも、見る時の来たリマインダーも無い", out)
        self.assertEqual(len(self.starts()), 1)

    def test_ask_and_deliver_run_due_in_the_back(self):
        # 周期を刻むのは頼みと納品: 通った --ask と --deliver の後に、--due を切り離して打つ（段取りの打ち忘れで点検が止まらない）
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて", "--dry-run")
        self.assertEqual((rc, self.ports.spawned), (0, []), out)   # 試し打ちは打たない
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        ((argv, cwd, log, env),) = self.ports.spawned
        self.assertEqual((argv[1:], cwd), ([starts.DISPATCH_PY, "--due", "--config", self.cfg], self.src))
        self.assertEqual(log, os.path.join(self.inbox, "due.log"))
        # 打った会話の印は渡さない（渡すと、打った部署自身の受け持ちを起動する頼みが「宛先はこの会話自身」で止まる）
        self.assertEqual(env, {})
        summary = pathlib.Path(self.root).parent / "summary.md"
        summary.write_text(test_deliver.GOOD, encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", str(summary))
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.ports.spawned), 2)
        with open(log, encoding="utf-8") as f:
            heads = [x.split(" ", 2)[2] for x in f.read().splitlines()]
        self.assertEqual(heads, ["頼みの後", "納品の後"])
        summary.write_text("## 結論\n直した。\n", encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", str(summary))   # 送らなかった納品（項目が足りない）の後は打たない
        self.assertEqual((rc, len(self.ports.spawned)), (2, 2), out)

    def test_due_skips_a_company_another_due_is_counting(self):
        # 裏の --due が 2 つ並ぶと、会社の錠を持つ方だけが数えて起動し、もう一方は待たずにその会社を飛ばす（同じ受け持ちを 2 度
        # 起動せず、待つ処理も積まない）
        provision.mark(self.place, self.src, {"lifecycle": "persistent"}, self.g)
        self.shape(shape_text('report_to = "社長室"\ntext = "見直す"\nevery = "1d"'))
        with starts._due_lock(self.inbox) as got:
            self.assertTrue(got)
            rc, out = self.main(self.src, "--due")
        self.assertEqual(rc, 0, out)
        self.assertIn("はほかの --due が数えている", out)
        self.assertEqual((self.starts(), self.prompts()), ([], []))
        rc, out = self.main(self.src, "--due")   # 錠が外れれば数える
        self.assertIn("起動した: ", out)
        self.assertEqual(len(self.starts()), 1)

    def test_skill_without_start_cannot_be_started(self):
        self.shape('[[roles]]\nname = "調べ役"\n[[skills]]\nname = "調べ"\nrole = "調べ役"\n')
        rc, out = self.main(self.src, "--start", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("起動方法（[skills.start]）の有る受け持ち「調べ」が無い", out)


if __name__ == "__main__":
    unittest.main()
