"""依頼と納品（会社の形の設計 4.5・4.10 の 3）: deliver ノード、orders の --ask・--deliver の流れ、Stop フック。
git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import argparse
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from . import DISPATCH
from .test_company import CompanyHerdr
from .test_dispatch import FakePorts, gitx_source, make_cfg, run_main
from .test_provision import git
from .test_task import push_shape
from . import test_role
import gitx
import orders
from nodes import deliver, provision


def dept_row(name=None, role=None, residency=None, session=None, panes=(), branch="b", path="/x"):
    attrs = {k: v for k, v in (("name", name), ("role", role), ("residency", residency), ("session", session)) if v}
    return {"path": path, "branch": branch, "attrs": attrs, "panes": list(panes)}


def company(name, root, *depts):
    return {"name": name, "root": root, "departments": list(depts)}


GOOD = """## 結論
直した。
試験は緑。

## 決め手
「要約なしで終われない」 https://example.com/spec

## 残った疑問
なし
"""


class Target(unittest.TestCase):
    def setUp(self):
        self.a = company("a", "/r/a", dept_row(name="調べ", role="調べ役", path="/r/a-w1"),
                         dept_row(name="出荷", role="出荷役", residency="resident", path="/r/a-w2"))
        self.b = company("b", "/r/b", dept_row(name="出荷b", role="出荷役", path="/r/b-w1"))

    def test_parse_target(self):
        self.assertEqual(deliver.parse_target("a/出荷役"), ("a", "出荷役"))
        self.assertEqual(deliver.parse_target("出荷役"), (None, "出荷役"))
        with self.assertRaises(deliver.DeliverError):
            deliver.parse_target("a/")

    def test_department_name_wins_anywhere_and_role_goes_to_the_resident(self):
        got = deliver.find_target([self.a, self.b], "/r/a", "出荷b")
        self.assertEqual((got["company"]["name"], got["department"]["path"]), ("b", "/r/b-w1"))
        got = deliver.find_target([self.a, self.b], "/r/b", "a/出荷役")
        self.assertEqual(got["department"]["path"], "/r/a-w2")

    def test_role_without_a_resident_department_means_a_new_one(self):
        got = deliver.find_target([self.a, self.b], "/r/b", "出荷役")   # b の出荷役は都度の部署
        self.assertEqual((got["company"]["name"], got["department"], got["role"]), ("b", None, "出荷役"))

    def test_unknown_company_and_twin_names_stop(self):
        with self.assertRaises(deliver.DeliverError) as e:
            deliver.find_target([self.a], "/r/a", "zz/出荷役")
        self.assertIn("herdr に開いていない", str(e.exception))
        twin = company("c", "/r/c", dept_row(name="調べ", path="/r/c-w"))
        with self.assertRaises(deliver.DeliverError):
            deliver.find_target([self.a, twin], "/r/a", "調べ")
        self.assertEqual(deliver.find_target([self.a, twin], "/r/a", "c/調べ")["department"]["path"], "/r/c-w")


class Summary(unittest.TestCase):
    def test_headings_and_labels_are_read(self):
        got = deliver.parse("結論: 直した\n**決め手**：原文 https://x.example\n## 残った疑問\nなし\n## 補足\n関係ない",
                            deliver.DEFAULT_ITEMS)
        self.assertEqual(got, {"結論": "直した", "決め手": "原文 https://x.example", "残った疑問": "なし"})

    def test_check_names_what_is_missing(self):
        items = deliver.parse(GOOD, deliver.DEFAULT_ITEMS)
        self.assertEqual(deliver.check(items, ["結論", "決め手", "残った疑問"]), [])
        self.assertEqual(deliver.check({**items, "結論": "1\n2\n3\n4"}, ["結論"]), ["結論（3 行を超える）"])
        self.assertEqual(deliver.check({**items, "決め手": "原文だけ"}, ["決め手"]), ["決め手（原典の URL が無い）"])
        self.assertEqual(deliver.check(items, ["枝", "試験"]), ["枝（無いか空）", "試験（無いか空）"])

    def test_required_items_come_from_the_role_or_default(self):
        self.assertEqual(deliver.required_items(None), list(deliver.DEFAULT_ITEMS))
        self.assertEqual(deliver.required_items({"name": "作業役", "deliver": None}), list(deliver.DEFAULT_ITEMS))
        self.assertEqual(deliver.required_items({"name": "作業役", "deliver": ["結論", "差分", "試験"]}), ["結論", "差分", "試験"])

    def test_short_text_is_typed_and_long_text_points_at_the_file(self):
        line = deliver.ask_line("id1", "desk", "直して", "/i/id1-ask.md", ["結論"], "py /p/dispatch.py")
        self.assertTrue(line.startswith("頼みです（受付 id1、desk から）: 直して 終わったら"))
        self.assertIn("py /p/dispatch.py --deliver <要約のファイル>", line)
        line = deliver.ask_line("id1", "desk", "一\n二", "/i/id1-ask.md", ["結論"], "py /p/dispatch.py")
        self.assertIn("/i/id1-ask.md を読んで", line)
        self.assertNotIn("\n", line)


class BossWindow(unittest.TestCase):
    def test_department_window_then_matching_mark_then_the_pane_at_ask_time(self):
        boss_dept = dept_row(session="s-boss", panes=[{"pane_id": "P9", "agent": "claude"}])
        self.assertEqual(deliver.boss_window({}, "s-boss", None, [], [company("a", "/r", boss_dept)]), ("P9", "部署の窓"))
        panes = [{"pane_id": "P1", "agent": "claude", "cwd": "/r/w", "agent_session": {"value": "s-boss"}},
                 {"pane_id": "P2", "agent": "claude", "cwd": "/r/home", "agent_session": {"value": "s-boss"}}]
        # herdr は attach の窓に別の会話の印を付けることがある。場所が会話と合うペインだけを使う
        self.assertEqual(deliver.boss_window({}, "s-boss", {"cwd": "/r/home"}, panes, []), ("P2", "会話の印"))
        self.assertEqual(deliver.boss_window({"boss-pane": "P1"}, "s-x", None, panes, [])[0], "P1")
        pane, why = deliver.boss_window({}, None, None, panes, [])
        self.assertIsNone(pane)
        self.assertIn("分からない", why)

    def test_boss_session_by_name_only_when_it_is_one(self):
        sessions = {"m": [{"sessionId": "s1", "name": "desk", "state": "working"},
                          {"sessionId": "s0", "name": "desk", "state": "done"}]}
        self.assertEqual(deliver.boss_session({"boss": "desk", "boss-account": "m"}, sessions)[0], "s1")
        sessions["m"].append({"sessionId": "s2", "name": "desk"})
        self.assertEqual(deliver.boss_session({"boss": "desk", "boss-account": "m"}, sessions), (None, None))
        self.assertEqual(deliver.boss_session({"boss-session": "s2", "boss-account": "m"}, sessions)[0], "s2")

    def test_boss_session_takes_the_current_process_of_a_resumed_session(self):
        old = {"pid": 1, "startedAt": 100, "sessionId": "s1", "name": "desk", "cwd": "/old"}
        new = {"pid": 2, "startedAt": 200, "sessionId": "s1", "name": "desk", "cwd": "/new"}
        sessions = {"m": [old, new]}
        self.assertEqual(deliver.boss_session({"boss-session": "s1", "boss-account": "m"}, sessions), ("s1", new))
        # 名前で引くときも、同じ id の 2 件は 1 つの会話に数える
        self.assertEqual(deliver.boss_session({"boss": "desk", "boss-account": "m"}, sessions), ("s1", new))


class StopVerdict(unittest.TestCase):
    ATTRS = {"role": "作業役", "ask": "id1", "session": "s1", "boss": "desk"}

    def test_blocks_only_an_undelivered_ask_in_its_own_conversation_up_to_the_limit(self):
        self.assertIn("受付 id1", deliver.stop_verdict({"session_id": "s1"}, self.ATTRS, 0, "/d.py"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, {}, 0, "/d.py"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, {"ask": "id1"}, 0, "/d.py"))   # 部署でない
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, {**self.ATTRS, "delivered": "id1"}, 0, "/d.py"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "other"}, self.ATTRS, 0, "/d.py"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, self.ATTRS, deliver.STOP_LIMIT, "/d.py"))

    def test_hook_blocks_with_json_then_gives_up_after_the_limit(self):
        tmp = tempfile.mkdtemp()
        payload = json.dumps({"session_id": "s1", "cwd": "/w"})
        outs = []
        for _ in range(deliver.STOP_LIMIT + 1):
            out = io.StringIO()
            self.assertEqual(orders.stop_hook(io.StringIO(payload), out, lambda cwd: dict(self.ATTRS), tmp), 0)
            outs.append(out.getvalue())
        self.assertEqual([json.loads(o)["decision"] for o in outs[:-1]], ["block"] * deliver.STOP_LIMIT)
        self.assertEqual(outs[-1], "")

    def test_plugin_hook_runs_orders_stop_and_is_quiet_outside_a_department(self):
        hooks = json.loads((DISPATCH.parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        (command,) = [h["command"] for g in hooks["Stop"] for h in g["hooks"]]
        self.assertIn('"${CLAUDE_PLUGIN_ROOT}/dispatch/orders.py" stop', command)
        plain = tempfile.mkdtemp()
        p = subprocess.run([sys.executable, str(DISPATCH / "orders.py"), "stop"], input=json.dumps({"cwd": plain}),
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((p.returncode, p.stdout), (0, ""), p.stderr)

    def test_hook_does_nothing_outside_a_department(self):
        out = io.StringIO()
        self.assertEqual(orders.stop_hook(io.StringIO(json.dumps({"session_id": "s1", "cwd": "/w"})), out,
                                          lambda cwd: {}, tempfile.mkdtemp()), 0)
        self.assertEqual(out.getvalue(), "")


class Flow(unittest.TestCase):
    """--ask と --deliver を入口から。頼み元（窓口）は元の clone のペイン P0、部署は worktree の窓 P1。"""

    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        self.place = str(pathlib.Path(self.root) / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place, "origin/main")
        provision.mark(self.place, self.src, {"role": "調べ役", "account": "a1", "name": "調べ", "session": "s-dept"}, gitx)
        self.ports = FakePorts([])
        self.ports.herdr = CompanyHerdr(self.src)
        self.desk = self.ports.herdr.open_at(self.src, agent="claude")["pane_id"]
        self.window = self.ports.herdr.open_at(self.place, agent="claude")["pane_id"]
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk", "HERDR_PANE_ID": self.desk}
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "d", "sessionId": "s-dept", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working"}]
        self.inbox = os.path.join(self.src, ".git", "company", "inbox")

    def main(self, cwd, *argv):
        with contextlib.chdir(cwd):
            return run_main(["--config", self.cfg, *argv], self.ports)

    def prompts(self):
        return [w for w in self.ports.herdr.writes if w[0] == "prompt"]

    def test_ask_types_one_line_into_the_department_window_and_writes_the_ask(self):
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        (w,) = self.prompts()
        self.assertEqual((w[1], w[3]), (self.window, False))
        self.assertIn("頼みです（受付 ", w[2])
        self.assertIn("desk から）: これを調べて 終わったら、要約を 結論・決め手・残った疑問・枝 の見出しで", w[2])
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual({k: attrs.get(k) for k in ("boss", "boss-account", "boss-session", "boss-pane")},
                         {"boss": "desk", "boss-account": "a1", "boss-session": "s-desk", "boss-pane": self.desk})
        self.assertEqual(os.path.realpath(attrs["boss-inbox"]), os.path.realpath(self.inbox))
        (rec,) = deliver.records(self.inbox)
        self.assertEqual((rec["kind"], rec["status"], rec["id"], rec["to"]["name"]), ("ask", "sent", attrs["ask"], "調べ"))
        self.assertEqual(pathlib.Path(rec["file"]).read_text(encoding="utf-8"), "これを調べて\n")
        # 受付箱は commit されない（共通の .git の中）
        self.assertEqual(git("-C", self.src, "status", "--porcelain").strip(), "")

    def test_ask_names_the_asker_from_the_current_process_of_a_resumed_session(self):
        # 窓口を一時停止したまま --resume で開き直し、/rename した。一覧には古い処理（desk）と今の処理（窓口）が並ぶ
        listed = self.ports.list_sessions
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"pid": 10**9, "startedAt": 100, **listed(cdir)[0]},   # 試験を走らせる処理の親に当たらない pid
            {"pid": 10**9 + 1, "startedAt": 200, **listed(cdir)[0], "name": "窓口"}, *listed(cdir)[1:]]
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss"), "窓口")
        self.assertIn("窓口 から）", self.prompts()[0][2])

    def test_ask_takes_the_askers_name_and_account_from_the_flags(self):
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x", "--from-name", "窓口", "--from-account", "a2")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs.get("boss"), attrs.get("boss-account")), ("窓口", "a2"))

    def test_the_command_handed_to_the_department_is_quoted_with_forward_slashes(self):
        self.assertNotIn("\\", orders.RUN)
        self.assertTrue(orders.RUN.endswith("/dispatch.py") or orders.RUN.endswith("/dispatch.py'"))

    def test_a_second_ask_waits_until_the_first_is_delivered(self):
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "一つ目")[0], 0)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "二つ目")
        self.assertEqual(rc, 2, out)
        self.assertIn("まだ納品していない", out)
        self.assertEqual(len(self.prompts()), 1)

    def test_a_new_ask_does_not_keep_the_previous_askers_values(self):
        provision.mark(self.place, self.src, {"boss": "前の窓口", "boss-account": "zz", "boss-session": "s-old",
                                              "boss-pane": "P-old"}, gitx)
        self.ports.env = {}   # Claude Code の外から頼んだ（頼む会話が分からない）
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual({k: attrs.get(k) for k in ("boss", "boss-account", "boss-session", "boss-pane")},
                         {"boss": None, "boss-account": None, "boss-session": None, "boss-pane": None})

    def test_ask_dry_run_writes_nothing(self):
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("打ち込む 1 行: 頼みです", out)
        self.assertEqual(self.prompts(), [])
        self.assertNotIn("ask", gitx.worktree_attrs(self.place))
        self.assertFalse(os.path.exists(self.inbox))

    def test_ask_to_a_role_without_a_resident_department_starts_one_through_the_task_path(self):
        seen = {}

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.update(name=ns.task, branch=ns.branch, role=ns.role, brief=ns.brief, attrs=extra_attrs, tail=tail,
                        source=repo.source, refreshed=refreshed)
            path = str(pathlib.Path(self.root) / "new")
            git("-C", self.src, "worktree", "add", "-q", "-b", ns.branch, path, "origin/main")
            provision.mark(path, self.src, {**extra_attrs, "role": ns.role, "session": "s-new"}, gitx)
            return 0

        with contextlib.chdir(self.src):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                a = argparse.Namespace(config=self.cfg, ask="出荷役", text=None, brief=None, task="出荷", branch="ship/1",
                                       dry_run=False, role=None, resident=False, base=None, from_name=None, from_account=None)
                brief = pathlib.Path(self.root).parent / "b.md"
                brief.write_text("長い頼み\n二行目", encoding="utf-8")
                a.brief = str(brief)
                rc = orders.ask(a, self.ports, self.src, task)
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertEqual((seen["name"], seen["branch"], seen["role"]), ("出荷", "ship/1", "出荷役"))
        self.assertEqual(os.path.realpath(seen["source"]), os.path.realpath(self.src))
        self.assertEqual(pathlib.Path(seen["brief"]).read_text(encoding="utf-8"), "長い頼み\n二行目\n")
        self.assertIn("--deliver <要約のファイル>", seen["tail"])
        self.assertTrue(seen["refreshed"])
        self.assertEqual(seen["attrs"]["boss"], "desk")
        self.assertEqual(deliver.records(self.inbox)[0]["status"], "sent")

    def test_ask_that_starts_a_department_reads_the_items_from_the_fetched_shape(self):
        seen = {}

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.update(tail=tail)
            return 1

        sha = push_shape(self.src, '[[roles]]\nname = "出荷役"\ndeliver = ["結論", "差分"]\n')
        a = argparse.Namespace(config=self.cfg, ask="出荷役", text="x", brief=None, task="出荷", branch="ship/1",
                               dry_run=False, role=None, resident=False, base=None, from_name=None, from_account=None)
        with contextlib.chdir(self.src), contextlib.redirect_stdout(io.StringIO()):
            orders.ask(a, self.ports, self.src, task)
        self.assertEqual(git("-C", self.src, "rev-parse", "origin/main"), sha)
        self.assertIn("結論・差分", seen["tail"])

    def test_ask_to_a_missing_role_needs_a_name_and_a_branch(self):
        rc, out = self.main(self.src, "--ask", "出荷役", "--text", "x")
        self.assertEqual(rc, 2, out)
        self.assertIn("--task <名前>、枝を --branch <枝>", out)

    def test_text_needs_ask_and_ask_needs_one_body(self):
        self.assertEqual(self.main(self.src, "--text", "x")[0], 2)
        self.assertEqual(self.main(self.src, "--ask", "調べ")[0], 2)

    def ask_then_summary(self, text):
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "調べて")[0], 0)
        self.ports.herdr.writes.clear()
        summary = pathlib.Path(self.root).parent / "summary.md"
        summary.write_text(text, encoding="utf-8")
        return str(summary)

    def test_deliver_sends_the_summary_to_the_asker_and_marks_it_delivered(self):
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        (w,) = self.prompts()
        self.assertEqual(w[1], self.desk)
        self.assertIn("納品です（受付 ", w[2])
        self.assertIn("調べ・枝 dept/a から）: 【結論】直した。 / 試験は緑。 【決め手】", w[2])
        self.assertIn("【枝】dept/a", w[2])   # 枝は機械が足す
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual(attrs["delivered"], attrs["ask"])
        recs = deliver.records(self.inbox)
        self.assertEqual([r["kind"] for r in recs], ["ask", "deliver"])
        self.assertIn("## 結論\n直した。", pathlib.Path(recs[1]["file"]).read_text(encoding="utf-8"))
        # 納品の後は Stop フックが差し戻さない
        self.assertIsNone(deliver.stop_verdict({"session_id": "s-dept"}, attrs, 0, "/d.py"))

    def test_deliver_with_missing_items_sends_nothing_and_names_them(self):
        summary = self.ask_then_summary("結論: 直した\n")
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn("送らなかった: 要約に足りない項目がある: 決め手（無いか空）、残った疑問（無いか空）", out)
        self.assertEqual(self.prompts(), [])
        attrs = gitx.worktree_attrs(self.place)
        self.assertNotIn("delivered", attrs)
        self.assertIn("受付", deliver.stop_verdict({"session_id": "s-dept"}, attrs, 0, "/d.py"))

    def shape(self, text):
        # 会社の形は本社（元の clone）のものを読む（--tree と頼む側と同じ。部署の枝の中の写しではない）
        shape = pathlib.Path(self.src) / ".claude" / "company.toml"
        shape.parent.mkdir(exist_ok=True)
        shape.write_text(text, encoding="utf-8")

    def test_deliver_items_follow_the_role_in_the_company_shape(self):
        # 役の起こし方の欄（instructions・model・settings）と納品の項目（deliver）を同じ [[roles]] の項目に書く
        self.shape(test_role.SHAPE)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertIn("結論・差分・試験 の見出しで", self.prompts()[0][2])
        self.ports.herdr.writes.clear()
        summary = pathlib.Path(self.root).parent / "summary.md"
        summary.write_text("結論: 直した\n差分: 1 行\n", encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", str(summary))
        self.assertEqual(rc, 2, out)
        self.assertIn("送らなかった: 要約に足りない項目がある: 試験（無いか空）", out)
        self.assertNotIn("決め手", out.splitlines()[0])
        summary.write_text("結論: 直した\n差分: 1 行\n試験: 緑\n", encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", str(summary))
        self.assertEqual(rc, 0, out)
        self.assertIn("【試験】緑", self.prompts()[0][2])

    def test_roles_written_by_name_are_not_read_and_say_to_move_them(self):
        self.shape('[roles."調べ役"]\ndeliver = ["結論", "差分", "試験"]\n')
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)   # 既定の項目で確かめる（黙って無視せず、注記を出す）
        self.assertIn('[roles."役"] の形で書いている（調べ役）', out)
        self.assertIn("[[roles]] の項目", out)

    def test_deliver_outside_a_department_stops(self):
        summary = pathlib.Path(self.root).parent / "s.md"
        summary.write_text(GOOD, encoding="utf-8")
        rc, out = self.main(self.src, "--deliver", str(summary))
        self.assertEqual(rc, 2, out)
        self.assertIn("部署でない", out)

    def test_deliver_without_the_asker_window_still_leaves_the_summary_in_the_inbox(self):
        summary = self.ask_then_summary(GOOD)
        self.ports.herdr._panes = [p for p in self.ports.herdr._panes if p["pane_id"] != self.desk]
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 1, out)
        self.assertIn("見つからない", out)
        self.assertEqual(deliver.records(self.inbox)[-1]["status"], "failed")
        self.assertTrue(pathlib.Path(deliver.records(self.inbox)[-1]["file"]).is_file())
        # 知らせられなかったので納品済みにしない（窓が開いたら打ち直せる。Stop フックは上限まで差し戻す）
        self.assertNotIn("delivered", gitx.worktree_attrs(self.place))

    def test_each_delivery_gets_its_own_file(self):
        summary = self.ask_then_summary(GOOD)
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)
        self.ports.now = lambda: 1
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)
        files = [r["file"] for r in deliver.records(self.inbox) if r["kind"] == "deliver"]
        self.assertEqual(len(set(files)), 2)
        self.assertTrue(all(pathlib.Path(f).is_file() for f in files))


if __name__ == "__main__":
    unittest.main()
