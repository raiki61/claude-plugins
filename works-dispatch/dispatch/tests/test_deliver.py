"""依頼と納品（会社の形の設計 4.5・4.10 の 3）: deliver ノード、orders の --ask・--deliver の流れ、Stop フック。
git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import argparse
import contextlib
import io
import json
import os
import pathlib
import re
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
import claudex
import herdr as real_herdr
import orders
import wake_hook
from nodes import deliver, provision, wake


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
        same = company("c", "/r/c", dept_row(name="調べ", path="/r/c-w"), dept_row(name="調べ", branch=None, path="/t/tree"))
        with self.assertRaises(deliver.DeliverError) as e:
            deliver.find_target([same], "/r/c", "c/調べ")   # 同じ会社の中の重なりは、会社を添えても分けられない
        self.assertIn("c/（枝無し） /t/tree", str(e.exception))
        self.assertIn("宛て方では分けられない", str(e.exception))


    def test_a_company_name_alone_goes_to_its_desk(self):
        # 部署でない会話は、宛先の会社の窓口の役の名前を知らなくても、会社の名前で頼める
        desk = {**dept_row(name="段取り", role="段取り", residency="resident", path="/r/n"), "head_office": True}
        notes = {**company("my_notes", "/r/n", desk, dept_row(name="調べもの", role="担当", path="/r/n-w")), "info_source": "origin"}
        a = {**self.a, "info_source": "repo"}
        got = deliver.find_target([a, notes], "/r/a", "my_notes")
        self.assertEqual((got["company"]["name"], got["department"]["path"], got["role"]), ("my_notes", "/r/n", "段取り"))
        with self.assertRaises(deliver.DeliverError) as e:   # 窓口を名付けていない会社
            deliver.find_target([a, notes], "/r/n", "a")
        self.assertIn("窓口が名付けられていない", str(e.exception))
        # 会社の形の無いリポジトリの名前は会社に当たらず、今までどおり頼む側の会社の役で宛てる
        plain = company("出荷役", "/r/出荷役")
        self.assertEqual(deliver.find_target([a, plain], "/r/a", "出荷役")["department"]["path"], "/r/a-w2")
        # 部署の名前は会社の名前より先に当たる
        named = company("c", "/r/c", dept_row(name="my_notes", role="担当", path="/r/c-w"))
        self.assertEqual(deliver.find_target([a, notes, named], "/r/a", "my_notes")["department"]["path"], "/r/c-w")
        twin = {**company("my_notes", "/s/my_notes", desk), "info_source": "origin"}   # 同じ会社を別の所にも clone した
        with self.assertRaises(deliver.DeliverError) as e:
            deliver.find_target([a, notes, twin], "/r/a", "my_notes")
        self.assertIn("2 つ以上ある", str(e.exception))

    def test_a_company_name_alone_goes_to_the_desk_written_in_its_shape_and_skips_a_bare_clone(self):
        # claude-plugins の窓口は my_notes の段取りが兼ねる（会社の形の desk）。部署を立てていない別の clone（claude-plugins-work1）は
        # 同じ名前でも会社に数えない（2026-10-17、--ask claude-plugins が「2 つ以上ある」で止まった。415c94）
        desk = {**dept_row(name="段取り", role="段取り", residency="resident", path="/r/n"), "head_office": True}
        notes = {**company("my_notes", "/r/n", desk), "info_source": "origin"}
        plugins = {**company("claude-plugins", "/r/cp", {**dept_row(path="/r/cp"), "head_office": True},
                             dept_row(name="割り振り", role="担当", path="/r/cp-w")), "info_source": "origin", "desk_of": "my_notes/段取り"}
        bare = {**company("claude-plugins", "/r/cp-work1", {**dept_row(path="/r/cp-work1"), "head_office": True}),
                "info_source": "origin", "desk_of": "my_notes/段取り"}
        got = deliver.find_target([notes, plugins, bare], "/r/n", "claude-plugins")
        self.assertEqual((got["company"]["name"], got["department"]["path"], got["role"]), ("my_notes", "/r/n", "段取り"))
        self.assertIn("会社の形の desk", got["via"])
        for far in ("claude-plugins", "my_notes/無い窓口"):   # 書いた先が部署の名前で当たらなければ、役の道に落とさずに止める
            with self.assertRaises(deliver.DeliverError) as e:
                deliver.find_target([notes, {**plugins, "desk_of": far}], "/r/n", "claude-plugins")
            self.assertIn("その窓口が見つからない", str(e.exception))


class Holders(unittest.TestCase):
    """残った疑問の持ち手の検査（役の holders・ask_holders。my_notes の tools/deliver_check.py から移した。24e521）。"""

    def test_each_open_item_needs_a_holder_and_the_owner_only_with_a_reason(self):
        ok = "- 測り直す。持ち手: 割り振り\n- どれを採るか。持ち手: 持ち主（価値で選ぶ）\n  続きの行"
        self.assertEqual(deliver.holder_problems(ok), [])
        self.assertEqual(deliver.holder_problems("なし"), [])
        bad = deliver.holder_problems("- 持ち手の無い疑問\n- 決めて。持ち手: 持ち主\n- 中継。持ち手: 社長室", ["社長室"])
        self.assertEqual(len(bad), 3)
        self.assertIn("持ち手が無い", bad[0])
        self.assertIn("持ち主（価値で選ぶ）", bad[1])
        self.assertEqual(deliver.holder_problems("- 中継。持ち手: 社長室"), [])   # 中継の名前を書かない会社では普通の持ち手
        for none in ("- なし", "なし（全部閉じた）", "ありません", "・特になし"):
            self.assertEqual(deliver.holder_problems(none), [], none)
        lead = "次の 2 件。\n1） 測る。持ち手: 割り振り\n② 決める。持ち手: 持ち主 (価値で選ぶ)"
        self.assertEqual(deliver.holder_problems(lead), [])   # 前置きの行は数えない。空白と半角の括弧も読む
        self.assertEqual(len(deliver.holder_problems("(1) 測る。持ち手: 割り振り\n(2) 持ち手の無い疑問")), 1)   # 番号で 1 件ずつ
        self.assertEqual(deliver.unsure_problems({"結論": "直した（要確認）", deliver.OPEN: "要確認。持ち手: 割り振り"}),
                         ["「結論」に「要確認」がある。残った疑問に移して持ち手を付ける"])

    def test_the_role_reads_holders_as_off_true_or_relay_names(self):
        import tomllib
        from nodes import role
        path = pathlib.Path(tempfile.mkdtemp(), "c.toml")
        path.write_text('[[roles]]\nname = "担当"\nholders = ["社長室"]\n[[roles]]\nname = "相談"\nask_holders = true\n'
                        '[[roles]]\nname = "作業"\n', encoding="utf-8")
        got = role.load(str(path), path.read_text(encoding="utf-8"))["roles"]
        self.assertEqual((got["担当"]["holders"], got["相談"]["ask_holders"], got["作業"]["holders"]), (["社長室"], [], None))


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
        # --wait で人の答え待ちにした頼みは促さない。前の頼みの印が残っていても、今の頼みは促す
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, {**self.ATTRS, "waiting": "id1"}, 0, "/d.py"))
        self.assertIn("受付 id1", deliver.stop_verdict({"session_id": "s1"}, {**self.ATTRS, "waiting": "id0"}, 0, "/d.py"))

    def test_hook_blocks_with_json_then_gives_up_after_the_limit(self):
        tmp = tempfile.mkdtemp()
        payload = json.dumps({"session_id": "s1", "cwd": "/w"})
        outs = []
        for _ in range(deliver.STOP_LIMIT + 1):
            out = io.StringIO()
            self.assertEqual(orders.stop_hook(io.StringIO(payload), out, lambda cwd: dict(self.ATTRS), tmp, lambda: None), 0)
            outs.append(out.getvalue())
        self.assertEqual([json.loads(o)["decision"] for o in outs[:-1]], ["block"] * deliver.STOP_LIMIT)
        self.assertEqual(outs[-1], "")

    def test_plugin_hook_runs_orders_stop_and_is_quiet_outside_a_department(self):
        hooks = json.loads((DISPATCH.parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        (command,) = [h["command"] for g in hooks["Stop"] for h in g["hooks"] if not h.get("asyncRewake") and not h.get("async")]
        self.assertIn('"${CLAUDE_PLUGIN_ROOT}/dispatch/orders.py" stop', command)
        plain = tempfile.mkdtemp()
        p = subprocess.run([sys.executable, str(DISPATCH / "orders.py"), "stop"], input=json.dumps({"cwd": plain}),
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((p.returncode, p.stdout), (0, ""), p.stderr)

    def test_hook_does_nothing_outside_a_department(self):
        out = io.StringIO()
        self.assertEqual(orders.stop_hook(io.StringIO(json.dumps({"session_id": "s1", "cwd": "/w"})), out,
                                          lambda cwd: {}, tempfile.mkdtemp(), lambda: None), 0)
        self.assertEqual(out.getvalue(), "")

    def test_waiting_for_background_work_shows_on_herdr_and_is_not_sent_back(self):
        # 番を終えて裏の処理（run_in_background の Bash。--land など）を待つ部署は、herdr の状態が done になり、終わったように
        # 見えた。表示名に「裏の処理待ち」を添え、待ち終えたら外す。待っている間は納品を差し戻さない（終われば会話が起きる）
        class H:
            HerdrError = real_herdr.HerdrError

            def __init__(self):
                self.writes = []

            def panes(self):
                return [{"pane_id": "P1", "agent": "claude", "cwd": "/w"}, {"pane_id": "P2", "agent": None, "cwd": "/w"}]

            def report_pane_metadata(self, pane, source, display_agent, title, tokens, clear_tokens=()):
                self.writes.append((pane, display_agent))
        tmp, h = tempfile.mkdtemp(), H()
        attrs = {**self.ATTRS, "residency": "resident", "fresh": "true", "name": "割り振り"}

        def stop(n):
            out = io.StringIO()
            orders.stop_hook(io.StringIO(json.dumps({"session_id": "s1", "cwd": "/w"})), out, lambda cwd: dict(attrs), tmp,
                             lambda: n, h)
            return out.getvalue()
        self.assertEqual(stop(1), "")
        self.assertEqual(h.writes, [("P1", "作業役・裏の処理待ち")])
        self.assertEqual(stop(2), "")
        self.assertEqual(len(h.writes), 1, "変わらないときは書き直さない")
        self.assertEqual(json.loads(stop(0))["decision"], "block")   # 待ち終えた: 表示を戻し、納品していなければ差し戻す
        self.assertEqual(h.writes[-1], ("P1", "作業役"))

    def test_a_running_background_agent_lets_the_turn_end_and_a_finished_one_does_not(self):
        # 裏で立てた作業役（Agent）は会話のプロセスの子に Bash を残さないので、ps では待っているのが見えず、差し戻された
        # （2026-10-17 の割り振り）。Stop フックの入力の background_tasks が在れば、その running の物で見る
        class NoPanes:   # herdr の窓が見えない（表示名は書かない）。差し戻すかだけを見る
            HerdrError = real_herdr.HerdrError

            def panes(self):
                return []

        def stop(payload, shells=lambda: 0):
            out = io.StringIO()
            orders.stop_hook(io.StringIO(json.dumps({"session_id": "s1", "cwd": "/w", **payload})), out,
                             lambda cwd: dict(self.ATTRS), tempfile.mkdtemp(), shells, NoPanes())
            return out.getvalue()
        agent = {"id": "a1", "type": "subagent", "status": "running", "agent_type": "convergence-loops:inspector"}
        self.assertEqual(stop({"background_tasks": [agent]}), "")
        self.assertEqual(json.loads(stop({"background_tasks": []}, shells=lambda: 1))["decision"], "block",
                         "一覧が在れば一覧で見る（空なら裏で動く物は無い）")
        self.assertEqual(json.loads(stop({"background_tasks": [{**agent, "status": "completed"}]}))["decision"], "block")
        self.assertEqual(stop({}, shells=lambda: 1), "", "一覧の無い版では裏の Bash を ps で数える")
        self.assertEqual(json.loads(stop({}, shells=lambda: None))["decision"], "block", "動いているのを確かめられなければ差し戻す")
        self.assertIn("番を終えてよい", json.loads(stop({"background_tasks": []}))["reason"])

    def test_background_shells_are_the_claude_childs_bash_tool_shells(self):
        # 会話のプロセス（claude）の子のうち、Bash の道具のシェル（シェルの写しを読み込む物）を数える。フック自身の祖先は数えない
        ps = "\n".join([
            "  1     0 /sbin/launchd",
            " 10  1 claude bg-spare --bg-spare /tmp/x.sock",
            " 11 10 caffeinate -i -t 300",
            " 12 10 /bin/bash -c source /h/.claude/shell-snapshots/snapshot-bash-1.sh && sleep 60",
            " 13 10 /bin/bash -c source /h/.claude/shell-snapshots/snapshot-bash-1.sh && bash run-python.sh orders.py stop",
            " 14 13 python3 orders.py stop",
            " 15 10 node mcp-server.js"])
        run = lambda argv, env=None: subprocess.CompletedProcess(argv, 0, ps, "")   # noqa: E731
        self.assertEqual(claudex.background_shells(14, run), 1)
        self.assertIsNone(claudex.background_shells(11 + 100, run), "claude の下でないなら分からない")


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
        self.ports.herdr.talking.add(self.window)   # 部署の窓の前には attach の画面（会話）が居る
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk", "HERDR_PANE_ID": self.desk}
        # 部署の会話は、窓に 1 行が送られると動き出す（status が busy になる）。--ask は送った後にそれを見て、届いたと確かめる
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "d", "sessionId": "s-dept", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working",
             "status": "busy" if any(w[0] == "prompt" and w[1] != self.desk for w in self.ports.herdr.writes) else "idle"}]
        self.inbox = os.path.join(self.src, ".git", "company", "inbox")

    def main(self, cwd, *argv):
        with contextlib.chdir(cwd):
            return run_main(["--config", self.cfg, *argv], self.ports)

    def prompts(self):
        return [w for w in self.ports.herdr.writes if w[0] == "prompt"]

    def fall(self, keep_mark=False):
        """部署の窓の会話が落ちた形（PC の再起動などで attach の画面が終わり、ペインにはシェルだけが居る）。keep_mark なら、
        herdr がペインの会話の印を残したままの形（まっさらな環境での 6 回目の試しの 1）。"""
        self.ports.herdr.talking.discard(self.window)
        if not keep_mark:
            for p in self.ports.herdr._panes:
                if p["pane_id"] == self.window:
                    p["agent"] = None
        real_run = self.ports.herdr.run

        def run(pane, command):   # attach を打つと、窓に会話が戻る
            real_run(pane, command)
            if " attach " in command:
                self.ports.herdr.talking.add(pane)
                for p in self.ports.herdr._panes:
                    if p["pane_id"] == pane:
                        p["agent"] = "claude"
        self.ports.herdr.run = run

    def test_fallen_department_is_attached_again_and_the_ask_goes_through(self):
        self.fall()
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        runs = [w for w in self.ports.herdr.writes if w[0] == "run"]
        self.assertEqual(runs, [("run", self.window, "claude-a1 attach d")])   # 会話の一覧の短い id で打つ（長い id は断られる）
        self.assertIn("部署の窓に会話が居なかったので", out)
        self.assertEqual(len(self.prompts()), 1)

    @unittest.skipIf(os.name == "nt", "Windows では前に居るプロセスを見る口が当てにならないので見ず、画面の exited の行で見分ける"
                                      "（test_exited_line_on_the_screen_counts_as_fallen）")
    def test_fallen_department_missing_from_the_list_is_attached_by_its_job_id(self):
        # /clear で会話の id が変わっても、裏の会話の短い id（company.job）は変わらない。一覧に見えないときは job で打つ
        # （会話の id の頭の字は /clear の後の id では短い id と合わない）
        provision.mark(self.place, self.src, {"session": "a5b0bc07-new", "job": "8c4a1102"}, gitx)
        self.ports.list_sessions = lambda cdir, include_done=False: []
        self.fall()
        self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertIn(("run", self.window, "claude-a1 attach 8c4a1102"), self.ports.herdr.writes)

    def test_fallen_department_without_its_talk_id_is_attached_by_the_talk_at_its_place(self):
        # 属性の会話の id が消えていても（前の版の --move が id を消した直後に止められた。2026-10-17 の割り振り・説明書）、会話の
        # 一覧の、部署の場所の裏の会話で戻し、属性を書き戻す
        subprocess.run(["git", "-C", self.place, "config", "--worktree", "--unset", "company.session"], check=True)
        self.fall()
        self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertIn(("run", self.window, "claude-a1 attach d"), self.ports.herdr.writes)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["session"], attrs["job"]), ("s-dept", "d"))
        old = {"kind": "background", "sessionId": "s-old", "id": "o", "cwd": self.place, "name": "調べ", "state": "done", "startedAt": 9}
        talk = {"kind": "background", "sessionId": "s-now", "id": "n", "cwd": self.place, "name": "調べ", "state": "working", "startedAt": 1}
        here = {"attrs": {"name": "調べ"}, "path": self.place}
        self.assertEqual(orders.place_talk(here, {"a1": [old, talk]}, [])[1]["id"], "n")   # 動いている物を先に
        self.assertEqual(orders.place_talk({**here, "attrs": {"name": "調べ", "account": "a2"}}, {"a1": [talk]}, []), None)
        self.assertIsNone(orders.place_talk({**here, "head_office": True}, {"a1": [talk]}, []))   # 本社は選ばない
        self.ports.list_sessions = lambda cdir, include_done=False: []   # 一覧にも無ければ、今までどおり立て直しを頼む
        self.assertEqual(orders.revive({"attrs": {}, "path": self.place, "panes": []}, [], self.ports, {})[1][:30],
                         "部署の属性に会話の id（company.session）が無く、会話の一覧にも部署の場所の裏の"[:30])

    def test_window_back_at_the_shell_counts_as_fallen_even_if_herdr_keeps_the_mark(self):
        # attach の画面が終わってシェルに戻っても、herdr はペインの会話の印を残す。前に居るのがシェルなら落ちたと見て戻す
        self.fall(keep_mark=True)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertIn(("run", self.window, "claude-a1 attach d"), self.ports.herdr.writes)

    def test_stopped_session_behind_a_stuck_attach_is_ended_and_attached_again(self):
        # Linux: 裏の処理が止まると、窓の attach は「Waking session …」のまま前に残る。会話の一覧が stopped と言えば落ちたと見て、
        # 残った attach を Ctrl-C で終わらせ、シェルに戻ってから短い id で打ち直す
        real_list = self.ports.list_sessions
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {**x, "state": "stopped"} if x.get("sessionId") == "s-dept" else x for x in real_list(cdir, include_done)]
        self.ports.herdr.front[self.window] = ["claude attach d"]
        self.fall(keep_mark=True)
        self.ports.herdr.talking.add(self.window)   # 止まった attach が前に居る（シェルでない）
        real_keys = self.ports.herdr.send_keys

        def keys(pane, *k):
            real_keys(pane, *k)
            if "ctrl+z" in k:
                self.ports.herdr.talking.discard(pane)
                self.ports.herdr.front.pop(pane, None)
                self.ports.list_sessions = real_list   # 打ち直すと会話が起きる
        self.ports.herdr.send_keys = keys
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        writes = [w for w in self.ports.herdr.writes if w[0] in ("send_keys", "run")]
        self.assertEqual(writes[:2], [("send_keys", self.window, "ctrl+z"), ("run", self.window, "claude-a1 attach d")])

    def test_department_whose_pane_was_closed_is_reopened_and_attached(self):
        # ペインを閉じると部署の作業場も閉じる（SKILL.md の「部署の会話を止める」の止め方）。作業場を開き直し、その新しいペインで
        # 短い id の attach を打って戻す（まっさらな環境での 8 回目の試しの 2）
        h = self.ports.herdr
        ws = next(p["workspace_id"] for p in h._panes if p["pane_id"] == self.window)
        h.close_workspace(ws)
        real_run = h.run

        def run(pane, command):
            real_run(pane, command)
            if " attach " in command:
                h.talking.add(pane)
                for p in h._panes:
                    if p["pane_id"] == pane:
                        p["agent"] = "claude"
        h.run = run
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        opened = [w for w in h.writes if w[0] == "open_worktree"]
        self.assertEqual(len(opened), 1)
        [attach] = [w for w in h.writes if w[0] == "run"]
        self.assertEqual(attach[2], "claude-a1 attach d")
        self.assertNotEqual(attach[1], self.window, "閉じたペインでなく、開き直した作業場の新しいペインに打つ")
        self.assertIn(("rename_pane", attach[1], "調べ"), h.writes)   # 開き直したペインにも --sync と同じ名前を付ける
        # 開き直した作業場は新しいので、常設か都度かの印も付け直す
        self.assertTrue([w for w in h.writes if w[0] == "report_workspace_metadata" and w[2].get("kind")], h.writes)

    def test_clear_before_ask_sees_the_clear_by_a_new_talk_file_when_the_list_keeps_the_id(self):
        # 裏の会話は /clear の後も会話の一覧の sessionId が替わらないことがある（2026-10-17 の試し）。記録のファイルが替われば空と見る
        class H:
            HerdrError = real_herdr.HerdrError

            def prompt(self, pane, text, wait):
                files.append(("new.jsonl", 2))

            def read(self, pane, lines):
                return ""

        def busy():
            busy.found = "s-old"
            return False
        busy.found = "s-old"
        files = [("old.jsonl", 1)]
        ports = argparse.Namespace(herdr=H(), pause=lambda: None)
        ok, said = orders.clear_before_ask({"attrs": {}}, "a0", "p1", busy, ports, lambda: files[-1])
        self.assertTrue(ok, said)
        files[:] = [("old.jsonl", 1)]
        H.prompt = lambda self, pane, text, wait: None   # 記録も替わらない
        ok, said = orders.clear_before_ask({"attrs": {}}, "a0", "p1", busy, ports, lambda: files[-1])
        self.assertFalse(ok)
        self.assertIn("見られなかった", said[0])

    def test_newest_talk_is_the_last_written_record_of_the_folder(self):
        home = tempfile.mkdtemp()
        cwd = "/w/a.b"
        d = pathlib.Path(home, "projects", "-w-a-b")
        d.mkdir(parents=True)
        self.assertIsNone(claudex.newest_talk(home, cwd))
        for name, t in (("x.jsonl", 10), ("y.jsonl", 20), ("z.txt", 30)):
            (d / name).write_text("{}", encoding="utf-8")
            os.utime(d / name, (t, t))
        self.assertEqual(claudex.newest_talk(home, cwd), ("y.jsonl", 20))

    def test_confirmed_send_waits_for_the_box_and_resends_only_when_the_line_never_arrived(self):
        # Windows: attach で戻した直後の会話は、打った字を受けられるまで間がある。入力欄が出てから送り、動き出す（busy）まで見る
        BOX = "──────────── 計算 ─\n❯ {}\n────────────────"

        class H:
            HerdrError = real_herdr.HerdrError

            def __init__(self, screens):
                self.screens, self.writes = list(screens), []

            def read(self, pane, lines):
                return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

            def prompt(self, pane, text, wait):
                self.writes.append(("prompt", text))

            def send_keys(self, pane, *keys):
                self.writes.append(("keys",) + keys)
        line = "再開の知らせです: この会話は落ちて戻った。受付 X"
        # 入力欄に残った: Enter を 1 回足し、動き出したら送れた
        state = {"n": 0}

        def busy_after_enter():
            return any(w[0] == "keys" for w in h.writes)
        h = H(["", BOX.format(""), BOX.format(line)])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, busy_after_enter)[0], "sent")
        self.assertEqual([w[0] for w in h.writes], ["prompt", "keys"])
        # 入力欄にも上にも見えず、動き出さない: 打ち直す
        h = H([BOX.format("")])
        status, detail = deliver.send_confirmed("P", line, h, lambda: None, lambda: False)
        self.assertEqual(status, "failed")
        self.assertEqual([w[0] for w in h.writes], ["prompt"] * deliver.SEND_TRIES)
        # 入力欄より上に載った（届いた）: 打ち直さない
        h = H([BOX.format(""), "● " + line + "\n" + BOX.format("")])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, lambda: False)[0], "sent")
        self.assertEqual([w[0] for w in h.writes], ["prompt"])
        # 前に送った同じ字が画面に残っているだけ（今の 1 行は届いていない）: 届いたと見誤らず、打ち直す
        h = H(["● " + line + "\n" + BOX.format("")])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, lambda: False)[0], "failed")
        self.assertEqual([w[0] for w in h.writes], ["prompt"] * deliver.SEND_TRIES)
        # 送る前から動いている会話: 打った字は番の後の待ちの列に回る。動き出しでは確かめず、打ち直さない（同じ頼みが 3 回届いた）
        h = H([BOX.format(""), "❯ " + line + "\n  ctrl+x ctrl+s to send now\n" + BOX.format("")])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, lambda: True)[0], "sent")
        self.assertEqual([w[0] for w in h.writes], ["prompt"])
        # 入力欄に残った字は Enter で待ちの列に回し、入力欄から出たのを見て届いたとする
        h = H([BOX.format(""), BOX.format(line), BOX.format("Press up to edit queued messages")])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, lambda: True)[0], "sent")
        self.assertEqual([w[0] for w in h.writes], ["prompt", "keys"])
        # 画面で見られなくても、動いている会話には 1 回だけ打つ（番の途中で取り込まれて画面から消えることもある）
        h = H([BOX.format("")])
        status, detail = deliver.send_confirmed("P", line, h, lambda: None, lambda: True)
        self.assertEqual((status, [w[0] for w in h.writes]), ("sent", ["prompt"]))
        self.assertIn("打ち直さない", detail)
        # 促しの 1 行は時刻で前の促しと字を分ける
        import orders
        self.assertNotEqual(orders.nudge_line("X", "desk", 1_000_000)[:20], orders.nudge_line("X", "desk", 1_000_007)[:20])

    def test_ask_finds_the_department_talk_after_clear_and_rewrites_its_id(self):
        # 部署の会話で /clear を打つと会話の id が変わる。属性の古い id で一覧を引くと動き出しを見られず、届いた頼みを 3 回打ち直して
        # failed を返し、頼み元の属性を書かなかった（2026-10-16 の試しの部署）。部署の場所に居る裏の会話で見つけ、id を書き直す
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "e", "sessionId": "s-cleared", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working",
             "status": "busy" if any(w[0] == "prompt" and w[1] != self.desk for w in self.ports.herdr.writes) else "idle"}]
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.prompts()), 1)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs.get("session"), attrs.get("boss")), ("s-cleared", "desk"))

    def test_a_line_left_in_the_input_box_gets_an_enter(self):
        # Windows: attach で戻した直後に送った文が、入力欄に入ったまま送信されなかった。残っていれば Enter を足す
        h = self.ports.herdr
        h.screen = "────\n❯ 再開の知らせです: この会話は落ちて戻った。\n────"
        status, detail = deliver.send(self.window, "再開の知らせです: この会話は落ちて戻った。受付 X", h, lambda: None)
        self.assertEqual(status, "sent")
        self.assertIn(("send_keys", self.window, "enter"), h.writes)
        h.writes.clear()
        h.screen = "────\n❯\n────"
        deliver.send(self.window, "再開の知らせです: この会話は落ちて戻った。受付 X", h, lambda: None)
        self.assertNotIn(("send_keys", self.window, "enter"), h.writes)

    def test_exited_line_on_the_screen_counts_as_fallen(self):
        # Windows では前のプロセスを見る口が当てにならないので、画面の「Session … has exited.」でも見分ける
        orders = __import__("orders")
        self.ports.herdr.screen = "Session d has exited.\nPS C:\\w> "
        dept = {"panes": [{"pane_id": self.window, "agent": "claude"}]}
        self.assertIsNone(orders.live_window(dept, self.ports))
        self.ports.herdr.screen = "> 作業中"
        self.assertEqual(orders.live_window(dept, self.ports), self.window)

    def test_fallen_department_with_a_pending_ask_is_nudged_to_deliver(self):
        # 落ちる前の頼みを納品していない部署: 戻して納品を促し、新しい頼みは送らずに止まる（待っても来ない、で止めない）
        provision.mark(self.place, self.src, {"ask": "20261016-000000-aaaaaa", "boss": "desk"}, gitx)
        self.fall()
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "次")
        self.assertEqual(rc, 2, out)
        self.assertIn("会話が落ちていたので戻して納品を促した", out)
        [(_, pane, text, _)] = self.prompts()
        self.assertEqual(pane, self.window)
        self.assertIn("受付 20261016-000000-aaaaaa", text)
        self.assertIn("--deliver", text)

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

    def test_ask_from_a_named_place_names_the_asker_by_the_place_not_the_talk(self):
        # 窓口の待ち受けは場所の名前（company.name）で受ける。会話の一覧の名前（desk）は替わりうるので、頼み元には場所の名前を書く
        # （段取りが会話の名前 my-notes-d7 で頼み、納品が待ち受けに届かなかった。my_notes の受付 20261017-032608-18b5f5）
        provision.mark(self.src, self.src, {"role": "窓口", "name": "段取り", "session": "s-desk"}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss"), "段取り")
        self.assertIn("段取り から）", self.prompts()[0][2])

    def test_ask_from_the_desk_right_after_clear_names_the_asker_by_the_place(self):
        # 窓口が /clear で会話を空にした直後は、会話の id が company.session と合わない。--desk が書いた処理（company.pid）の中から
        # 頼んだなら、場所の名前を書く（会話の一覧の名前 my-notes-d7 で頼み元を書き続けた。my_notes の受付 20261017-054115-5bc0b0）
        provision.mark(self.src, self.src, {"role": "窓口", "name": "段取り", "session": "s-before-clear", "pid": "4242"}, gitx)
        self.ports.same_process = lambda pid: pid == "4242"
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss"), "段取り")

    def test_ask_typed_in_another_clone_returns_to_the_askers_own_inbox(self):
        # 窓口が別の会社の clone で命令を打っても、納品の受付箱は窓口の居る場所の会社の物（段取りが claude-plugins の clone で打ち、
        # 返り先が claude-plugins の受付箱になった。my_notes の受付 20261017-054115-5bc0b0）
        other = str(pathlib.Path(self.root) / "other")
        git("init", "-q", other)
        rc, out = self.main(other, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(os.path.realpath(gitx.worktree_attrs(self.place).get("boss-inbox")), os.path.realpath(self.inbox))

    def test_ask_from_another_talk_in_the_head_office_keeps_the_talks_name(self):
        # 本社にはほかの会話も居る。--desk が書いた会話（company.session）でなければ、窓口の名前を名乗らない
        provision.mark(self.src, self.src, {"role": "窓口", "name": "段取り", "session": "s-other"}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss"), "desk")

    def test_the_command_handed_to_the_department_is_quoted_with_forward_slashes(self):
        self.assertNotIn("\\", orders.RUN)
        self.assertTrue(orders.RUN.endswith("/dispatch.py") or orders.RUN.endswith("/dispatch.py'"))

    def test_a_second_ask_waits_until_the_first_is_delivered(self):
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "一つ目")[0], 0)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "二つ目")
        self.assertEqual(rc, 2, out)
        self.assertIn("まだ納品していない", out)
        self.assertEqual(len(self.prompts()), 1)

    def test_the_askers_window_is_where_the_asking_talk_is_not_the_inherited_env(self):
        # 裏の会話（claude --bg）は控えの処理の HERDR_PANE_ID を継ぎ、別のペインを指すことがある（2026-10-17 に見た）
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk", "HERDR_PANE_ID": self.window}
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss-pane"), self.desk)

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

    def test_ask_to_a_duty_raised_only_when_asked_starts_its_department_with_a_branch_of_its_own(self):
        # 頼まれたときだけ立てる受け持ち（standing = false）: --task・--branch を渡さなくても、受け持ちの名前の部署を立てる（813bb8）
        self.shape('[[roles]]\nname = "担当"\nresident = true\n[[skills]]\nname = "見渡し"\nrole = "担当"\nstanding = false\n')
        seen = {}

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.update(name=ns.task, branch=ns.branch, role=ns.role)
            return 1
        with contextlib.chdir(self.src):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                a = argparse.Namespace(config=self.cfg, ask="見渡し", text="見て", brief=None, task=None, branch=None,
                                       dry_run=False, role=None, resident=False, base=None, from_name=None, from_account=None)
                orders.ask(a, self.ports, self.src, task)
        self.assertEqual((seen["name"], seen["role"]), ("見渡し", "担当"), buf.getvalue())
        self.assertRegex(seen["branch"], r"^work/ask-[0-9a-f]{6}$")
        self.assertIn("頼まれたときだけ立てる受け持ち", buf.getvalue())
        companies = [{"name": "co", "root": self.src, "departments": [],
                      "skills": [{"name": "見渡し", "role": "担当", "standing": False}]}]
        self.assertEqual(deliver.find_target(companies, self.src, "co/見渡し")["on_demand"], "見渡し")
        companies[0]["departments"] = [dept_row(name="見渡し", role="担当", path="/r/w")]   # 立っている間は、その部署に届ける
        self.assertEqual(deliver.find_target(companies, self.src, "co/見渡し")["department"]["path"], "/r/w")

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

    def test_wait_marks_the_ask_until_a_prompt_or_the_delivery(self):
        # 人の答えを待つ部署（持ち主が答えるのは数時間後もありうる）が、番の終わりごとに納品を促されない
        summary = self.ask_then_summary(GOOD)
        self.assertEqual(self.main(self.place, "--wait", "")[0], 2)   # 何を待つかが要る
        rc, out = self.main(self.place, "--wait", "持ち主の答え（どちらの案にするか）")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["waiting"], attrs["waiting-why"]), (attrs["ask"], "持ち主の答え（どちらの案にするか）"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "s-dept"}, attrs, 0, "/d.py"))
        # 人が打つと外れ、また促す（ほかの会話の文では外さない）
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s-other"})
        self.assertIn("waiting", gitx.worktree_attrs(self.place))
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s-dept"})
        attrs = gitx.worktree_attrs(self.place)
        self.assertNotIn("waiting", attrs)
        self.assertIn("受付", deliver.stop_verdict({"session_id": "s-dept"}, attrs, 0, "/d.py"))
        # 納品でも外れる
        self.assertEqual(self.main(self.place, "--wait", "持ち主の答え")[0], 0)
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)
        self.assertNotIn("waiting", gitx.worktree_attrs(self.place))
        self.assertEqual(self.main(self.place, "--wait", "持ち主の答え")[0], 2)   # 納品した後は待つ頼みが無い
        self.assertEqual(self.main(self.src, "--wait", "持ち主の答え")[0], 2)     # 部署でない所

    def test_rest_marks_a_break_only_after_the_ask_is_delivered(self):
        # 会話を持ち越す部署と窓口が、空にしてよい区切りを自分で印す（空にするのは番の終わりの待ち受け）
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--rest")
        self.assertEqual(rc, 2, out)   # 納品していない頼みが在る
        self.assertIn("納品していない頼み", out)
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)
        rc, out = self.main(self.place, "--rest")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place)[wake.REST], "s-dept")
        self.assertEqual(self.main(self.src, "--rest")[0], 2)   # 部署でも窓口でもない所

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

    def fresh_world(self, busy_before=False):
        """頼みごとに空にする役（fresh）の部署。/clear を打つと会話の id が変わり、頼みを打つと動き出す。"""
        self.shape('[[roles]]\nname = "調べ役"\nresident = true\nfresh = true\n')
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
        sent = lambda: [w[2] for w in self.prompts() if w[1] != self.desk]   # noqa: E731
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "s", "sessionId": "s-new" if "/clear" in sent() else "s-dept", "name": "調べ", "cwd": self.place,
             "kind": "background", "state": "working",
             "status": "busy" if busy_before or any(x != "/clear" for x in sent()) else "idle"}]
        return sent

    def test_fresh_role_clears_the_talk_before_the_next_ask_once_the_last_one_is_delivered(self):
        # 担当は常設の席のまま、頼みごとに空の会話で受ける（前の頼みの記憶で書き直すと、ほかの部署が入れた行を消す）
        sent = self.fresh_world()
        provision.mark(self.place, self.src, {"ask": "20261016-000000-aaaaaa", "delivered": "20261016-000000-aaaaaa"}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sent()[0], "/clear")
        self.assertIn("調べて", sent()[1])
        self.assertIn("/clear で会話を空にしてから送る", out)
        attrs = gitx.worktree_attrs(self.place)
        # 変わった会話の id と、attach に渡す短い id（/clear の前の id の頭）、役の fresh を属性に書く
        self.assertEqual((attrs["session"], attrs["job"], attrs["fresh"]), ("s-new", "s", "true"))
        # herdr の作業場の印にも出る
        rc, out = self.main(self.src, "--sync", "--dry-run")
        self.assertIn("印 常設・毎回空", out)

    def test_fresh_role_sees_the_clear_in_the_records_of_the_pane_account_not_of_the_asker(self):
        # 設定のフォルダを書かないアカウントの部署は、ペインのシェルの素の claude で起きて ~/.claude に記録を書く。頼む会話の
        # CLAUDE_CONFIG_DIR（別のアカウント）の下を探すと記録が見つからず、一覧の id も替わらないので、空になったのを見られない
        # （2026-10-17 に、設定のフォルダを書いたアカウントの会話から、書かないアカウントの部署へ 2 回頼んで 2 回止まった。my_notes の受付 20261017-075753-01991f）
        cfg = pathlib.Path(self.cfg)
        cfg.write_text(cfg.read_text(encoding="utf-8").replace(f", config_dir = '{cfg.parent}/c1'", ""), encoding="utf-8")
        home = pathlib.Path(self.root).parent / "home"
        records = home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(self.place))
        records.mkdir(parents=True)
        (records / "old.jsonl").write_text("{}", encoding="utf-8")
        os.utime(records / "old.jsonl", (1, 1))
        self.ports.env = {**self.ports.env, "HOME": str(home), "CLAUDE_CONFIG_DIR": str(pathlib.Path(self.root).parent / "c2")}
        sent = self.fresh_world()
        self.ports.list_sessions = lambda cdir, include_done=False: [   # 裏の会話は /clear の後も一覧の id が替わらない
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "s", "sessionId": "s-dept", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working",
             "status": "busy" if any(x != "/clear" for x in sent()) else "idle"}]
        typed = self.ports.herdr.prompt

        def prompt(pane, text, wait):
            if text == "/clear":
                (records / "new.jsonl").write_text("{}", encoding="utf-8")
            return typed(pane, text, wait)
        self.ports.herdr.prompt = prompt
        provision.mark(self.place, self.src, {"ask": "20261016-000000-aaaaaa", "delivered": "20261016-000000-aaaaaa"}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sent()[0], "/clear")
        self.assertIn("調べて", sent()[1])

    def test_fresh_role_does_not_clear_a_talk_without_a_delivered_ask_or_a_running_one(self):
        sent = self.fresh_world()
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")   # 頼みの無い部署（--task の頼みのファイルで働いているかも）
        self.assertEqual(rc, 0, out)
        self.assertNotIn("/clear", sent())
        self.assertIn("まだ納品した頼みが無いので、空にせずに送る", out)
        self.ports.herdr.writes.clear()
        sent = self.fresh_world(busy_before=True)
        provision.mark(self.place, self.src, {"delivered": gitx.worktree_attrs(self.place)["ask"]}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "次")
        # 納品し終えた部署が動いていて空にできないなら送らない（打つと番の後に前の会話のまま届く。my_notes の受付 6f32b7）
        self.assertEqual(rc, 1, out)
        self.assertEqual(sent(), [])
        self.assertIn("空にできないので送らなかった", out)

    def test_fresh_role_mid_turn_with_a_watcher_history_queues_the_ask(self):
        # 待ち受けの跡の在る部署が番の途中（待ち受けが止まっている）なら、打ち込まずに順番待ちに積む（番の終わりの待ち受けが
        # 空にしてから渡す）
        sent = self.fresh_world(busy_before=True)
        provision.mark(self.place, self.src, {"name": "調べ", "ask": "20261016-000000-aaaaaa",
                                              "delivered": "20261016-000000-aaaaaa"}, gitx)
        place_dir = gitx.git_dir(self.place)
        pos = pathlib.Path(wake.pos_path(self.inbox, place_dir))
        pos.parent.mkdir(parents=True, exist_ok=True)
        pos.write_text("0", encoding="utf-8")
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "次")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sent(), [])
        self.assertIn("順番待ちに積んだ", out)
        self.assertEqual(len(wake.queued(self.inbox, place_dir)), 1)

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

    def test_deliver_check_of_the_role_stops_the_delivery_until_it_passes(self):
        # 何を確かめるかは会社の側のスクリプト（ここでは「要約が reference/ を挙げていなければ 1」）。dispatch は走らせて終わりの値を見るだけ
        script = pathlib.Path(self.root).parent / "gate.py"
        got = pathlib.Path(self.root).parent / "gate.json"
        script.write_text("import json, os, sys\n"
                          "p = json.load(sys.stdin)\n"
                          f"open({str(got)!r}, 'w', encoding='utf-8').write(json.dumps({{**p, 'cwd': os.getcwd()}}))\n"
                          "if 'reference/' not in p['summary']:\n"
                          "    print('reference/ に無い URL: https://example.com/spec')\n"
                          "    sys.exit(1)\n", encoding="utf-8")
        command = " ".join(f'"{pathlib.Path(x).as_posix()}"' for x in (sys.executable, script))
        self.shape(f'[[roles]]\nname = "調べ役"\ndeliver_check = {json.dumps(command)}\n')
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--deliver", summary, "--dry-run")
        self.assertEqual(rc, 2, out)   # --dry-run でも検査する（送る前に通るかを見られる）
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn("送らなかった: 納品の検査が通らなかった（終了の値 1）", out)
        self.assertIn("  reference/ に無い URL: https://example.com/spec", out)
        self.assertEqual(self.prompts(), [])
        self.assertNotIn("delivered", gitx.worktree_attrs(self.place))
        payload = json.loads(got.read_text(encoding="utf-8"))
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((payload["role"], payload["ask"], payload["branch"]), ("調べ役", attrs["ask"], "dept/a"))
        self.assertEqual(os.path.realpath(payload["cwd"]), os.path.realpath(self.place))   # 部署の作業場の根で走る
        self.assertEqual(payload["place"], payload["cwd"])
        self.assertIn("決め手", payload["items"])
        self.assertTrue(payload["summary"].startswith("## 結論\n直した。"))
        pathlib.Path(summary).write_text(GOOD.replace("なし", "写しは reference/spec.md"), encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertIn("納品の検査が通った", out)
        self.assertEqual(len(self.prompts()), 1)

    def test_a_check_script_missing_in_the_workplace_says_to_rebase(self):
        # 会社の形は本流から読むが、検査は作業場で走る。台本の入る前の本流から切った枝では台本が無いので、載せ直すよう言う
        self.shape(f'[[roles]]\nname = "調べ役"\ndeliver_check = {json.dumps(f'"{pathlib.Path(sys.executable).as_posix()}" tools/check.py')}\n')
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn("検査の台本 tools/check.py がこの作業場に無い", out)
        self.assertIn("git rebase origin/main", out)
        self.assertEqual(self.prompts(), [])

    def test_roles_written_by_name_are_not_read_and_say_to_move_them(self):
        self.shape('[roles."調べ役"]\ndeliver = ["結論", "差分", "試験"]\n')
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)   # 既定の項目で確かめる（黙って無視せず、注記を出す）
        self.assertIn('[roles."役"] の形で書いている（調べ役）', out)
        self.assertIn("[[roles]] の項目", out)

    def test_deliver_with_holders_stops_an_open_item_without_a_holder(self):
        self.shape('[[roles]]\nname = "調べ役"\nholders = true\n')
        summary = self.ask_then_summary(GOOD.replace("## 残った疑問\nなし", "## 残った疑問\n- 測り直す"))
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn("持ち手が無い: - 測り直す", out)
        self.assertEqual(self.prompts(), [])
        pathlib.Path(summary).write_text(GOOD.replace("## 残った疑問\nなし", "## 残った疑問\n- 測り直す。持ち手: 割り振り"), encoding="utf-8")
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)

    def test_an_ask_to_a_role_with_ask_holders_is_checked_when_it_has_open_items(self):
        self.shape('[[roles]]\nname = "調べ役"\nask_holders = true\n')
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "問いです\n## 残った疑問\n- 持ち手の無い疑問", "--dry-run")
        self.assertEqual(rc, 2, out)
        self.assertIn("役の ask_holders の検査", out)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "残った疑問の節の無い頼み", "--dry-run")
        self.assertEqual(rc, 0, out)

    def test_an_ask_runs_the_check_of_the_receiving_role_at_the_receiving_company(self):
        # 受ける会社の決まりで、ほかの会社から届く頼みも止める（242baa）。関所は受ける会社の代表の clone で走り、本文を JSON で受ける
        script = pathlib.Path(self.src, "gate.py")
        script.write_text("import json,sys,os\nd=json.load(sys.stdin)\nopen('seen.txt','w').write(os.getcwd())\n"
                          "sys.exit(1 if '知らせ' in d['body'] else 0)\n", encoding="utf-8")
        self.shape(f'[[roles]]\nname = "調べ役"\nask_check = {json.dumps(pathlib.Path(sys.executable).as_posix() + " gate.py")}\n')
        git("-C", self.src, "add", "gate.py")
        git("-C", self.src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "gate")
        git("-C", self.src, "push", "-q", "origin", "HEAD:main")
        git("-C", self.src, "fetch", "-q", "origin")
        script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")   # 作業ツリーの物でなく、origin の既定の枝の物が走る
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "知らせです", "--dry-run")
        self.assertEqual(rc, 2, out)
        self.assertIn("の関所（役「調べ役」の ask_check", out)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "問いです", "--dry-run")
        self.assertEqual(rc, 0, out)

    def test_deliver_outside_a_department_stops(self):
        summary = pathlib.Path(self.root).parent / "s.md"
        summary.write_text(GOOD, encoding="utf-8")
        rc, out = self.main(self.src, "--deliver", str(summary))
        self.assertEqual(rc, 2, out)
        self.assertIn("部署でない", out)

    def test_deliver_without_the_asker_window_posts_a_notice_and_closes_the_ask(self):
        # 頼み元の会話が終わって窓が無い: 待っても窓は開かず、部署の順番待ちが止まる（2026-10-17 の点検）。頼み元の名前に宛てた
        # 知らせを台帳に置いて納品済みにする（頼み元の名前の待ち受けが後で張られれば、その知らせで起きる）
        summary = self.ask_then_summary(GOOD)
        self.ports.herdr._panes = [p for p in self.ports.herdr._panes if p["pane_id"] != self.desk]
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 1, out)   # 頼み元の会話が一覧に居る（生きていて窓を決められないだけ）なら閉じない
        self.assertNotIn("delivered", gitx.worktree_attrs(self.place))
        listed = self.ports.list_sessions
        self.ports.list_sessions = lambda cdir, include_done=False: [s for s in listed(cdir, include_done) if s.get("sessionId") != "s-desk"]
        before = len(self.prompts())
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertIn("見つからない", out)
        notice, record = deliver.records(self.inbox)[-2:]   # 打ち直しの分
        self.assertEqual((record["status"], record["kind"]), (orders.POSTED, "deliver"))
        self.assertTrue(pathlib.Path(record["file"]).is_file())
        self.assertEqual((notice["kind"], notice["to"], notice["file"]), ("deliver", wake.address("src", "desk"), record["file"]))
        self.assertEqual(gitx.worktree_attrs(self.place)["delivered"], gitx.worktree_attrs(self.place)["ask"])
        self.assertEqual(len(self.prompts()), before)   # 窓には打たない

    def test_deliver_whose_send_fails_does_not_close_the_ask(self):
        # 窓は在るが打てなかった（herdr の誤り）: 窓が戻れば打ち直せるので、納品済みにしない
        summary = self.ask_then_summary(GOOD)
        self.ports.herdr.prompt = lambda *a, **k: (_ for _ in ()).throw(real_herdr.HerdrError(["herdr"], "pane_not_found"))
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 1, out)
        self.assertEqual(deliver.records(self.inbox)[-1]["status"], "failed")
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
