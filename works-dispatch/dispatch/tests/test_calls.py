"""機械窓口（受付の設計 5 章）: ツールのフィールド（role ノード）・入力の確かめ（tools ノード）・--call と回す・[[land.after]] の合図・--tree。
git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from . import test_deliver
from .test_provision import git
import calls
import orders
import gitx
from nodes import deliver, land, provision, role, tools, tree


def shape_text(command, fallback='fallback_role = "調べ役"', machine="machine = true"):
    return f"""
[[roles]]
name = "調べ役"
persistent = true

[[roles]]
name = "配布"
{machine}

[[roles.tools]]
name = "spread-plugins"
title = "全アカウントに配る"
inputSchema = {{ type = "object", properties = {{ dry = {{ type = "boolean" }} }}, additionalProperties = false }}
command = '''{command}'''
{fallback}
"""


class Fields(unittest.TestCase):
    def test_machine_role_tools_need_a_role_to_hand_over_to(self):
        got = role.load("/c.toml", shape_text("true", fallback=""))
        self.assertEqual(got["roles"]["配布"]["tools"], [])
        self.assertIn("回す役（fallback_role）が無いので外す", got["problems"][0])
        got = role.load("/c.toml", shape_text("true", fallback='fallback_role = "配布"'))
        self.assertIn("機械だけの役（AI の部署を持たない）ので外す", got["problems"][0])

    def test_fallback_defaults_to_the_owning_role(self):
        got = role.load("/c.toml", shape_text("true", fallback="", machine=""))
        self.assertEqual(got["roles"]["配布"]["tools"][0]["fallback_role"], "配布")

    def test_fallback_may_name_a_duty_and_is_checked_against_its_role(self):
        # 回す先は --ask 会社/<名前> と同じ宛て方なので、受け持ちの名前でも書ける（CI の見張りの fallback_role = "点検"）
        duty = '\n[[roles]]\nname = "担当"\n[[skills]]\nname = "点検"\nrole = "{}"\n'
        got = role.load("/c.toml", shape_text("true", fallback='fallback_role = "点検"') + duty.format("担当"))
        self.assertEqual((got["problems"], got["roles"]["配布"]["tools"][0]["fallback_role"]), ([], "点検"))
        got = role.load("/c.toml", shape_text("true", fallback='fallback_role = "点検"') + duty.format("配布"))
        self.assertIn("回す先 点検 が受け持ち 点検 の役が機械だけの役（AI の部署を持たない）ので外す", got["problems"][0])
        got = role.load("/c.toml", shape_text("true", fallback='fallback_role = "見張り"') + duty.format("担当"))
        self.assertIn("回す先 見張り が会社の形の役にも受け持ちにも無いので外す", got["problems"][0])
        got = role.load("/c.toml", shape_text("true", fallback='fallback_role = "点検"') + '\n[[skills]]\nname = "点検"\n')
        self.assertIn("回す先 点検 が受け持ち 点検 の役が無いので外す", got["problems"][0])

    def test_tool_fields_follow_the_mcp_tool(self):
        bad = role.load("/c.toml", '[[roles]]\nname = "r"\n[[roles.tools]]\nname = "a b"\ninputSchema = { type = "string" }\n')
        self.assertIn("name（英数字・_・-・. の 1〜128 字）, inputSchema（ルートに type = \"object\" の表）, command", bad["problems"][0])

    def test_input_is_checked_only_for_shape(self):
        schema = {"type": "object", "required": ["n"], "properties": {"n": {"type": "integer"}, "s": {"type": ["string", "null"]}},
                  "additionalProperties": False}
        self.assertEqual(tools.check_input(schema, {"n": 1, "s": None}), [])
        self.assertEqual(tools.check_input(schema, {"n": True, "x": 1}), ["知らない鍵 x", "鍵 n の型が integer で無い"])
        self.assertEqual(tools.check_input(schema, []), ["入力が JSON の物（{...}）で無い"])
        self.assertEqual(tools.check_input(schema, {}), ["要る鍵 n が無い"])

    def test_auto_department_name_and_branch(self):
        tool = {"name": "Spread_Plugins.v2", "title": "全アカウントに配る"}
        self.assertEqual(tools.auto_name("配布", tool), "配布：全アカウントに配る")
        self.assertEqual(tools.auto_branch(tool, "20261017-010203-a1b2c3"), "work/spread-plugins-v2-a1b2c3")

    def test_leftover_tool_places_are_those_whose_run_is_gone(self):
        t = lambda name: f"/tmp/{tools.PREFIX}{name}/tree"   # noqa: E731
        entries = [{"path": t("live"), "locked": f"{tools.OWNER}10"}, {"path": t("dead"), "locked": f"{tools.OWNER}20"},
                   {"path": t("old"), "locked": None},   # この版より前の place が作った（鍵が無い。前の版が走っているかもしれない）
                   {"path": t("oldgone"), "locked": None},
                   {"path": t("making"), "locked": "initializing"}, {"path": t("gone"), "locked": "initializing"},
                   {"path": t("odd"), "locked": f"{tools.OWNER}１２"},   # pid でない訳は、ほかの訳の鍵と同じに親のフォルダを見る
                   {"path": "/w/dept/tree", "locked": None}, {"path": f"/tmp/{tools.PREFIX}x/other", "locked": None}]
        got = tools.leftovers(entries, alive=lambda pid: pid == 10, exists=lambda d: d.endswith(("making", "odd", "old")))
        self.assertEqual(got, [t("dead"), t("oldgone"), t("gone")])
        self.assertFalse(tools._alive(10 ** 30, posix=True))   # 大きすぎる pid で落ちない
        self.assertTrue(tools._alive(os.getpid(), posix=False))   # Windows は確かめずに居るとみなす（消さない）

    def test_land_after_is_read(self):
        text = '[land]\nmode = "none"\n[[land.after]]\nrole = "配布"\ntool = "spread-plugins"\n[[land.after]]\nrole = ""\n'
        got = land.read_rules("/c.toml", None, text)
        self.assertEqual(got["after"], [{"role": "配布", "tool": "spread-plugins", "input": {}}])
        self.assertIn("land.after[1] は role・tool", got["problems"][0])


class ToolEnv(unittest.TestCase):
    def test_tools_get_the_running_dispatch_to_call_back(self):
        env = calls.tool_env()
        self.assertTrue(os.path.isfile(env["WORKS_DISPATCH"]), env["WORKS_DISPATCH"])   # ツールが --queue-run で列に並べる
        self.assertEqual(os.path.basename(env["WORKS_DISPATCH"]), "dispatch.py")
        self.assertEqual(env["WORKS_DISPATCH_PYTHON"], sys.executable)
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")


class CompanyRoot(unittest.TestCase):
    def test_two_clones_with_the_same_company_name_stop_unless_one_has_departments(self):
        from unittest import mock
        import orders
        clone = {"name": "co", "root": "/x/co-work", "departments": []}
        real = {"name": "co", "root": "/x/co", "departments": [{"attrs": {"role": "作業"}}]}
        for found, want in (([clone, real], "/x/co"), ([clone, dict(clone, root="/x/co2")], None)):
            with self.subTest(want=want), mock.patch.object(orders, "survey", return_value=([], [], found, None, [])), \
                    mock.patch.object(calls.tree, "read_info", return_value={}):
                got, why = calls._company_root("co/調べ", mock.Mock(), "/", None)   # 口は survey と read_info を差し替えたので使わない
                if want:
                    self.assertEqual(got[0], want)
                else:
                    self.assertIn("2 つ以上", why)


class Call(unittest.TestCase):
    """--call を入口から。会社の形は本社のファイル。回す先は Flow の keep の部署「調べ」（役 調べ役）。"""

    Flow = test_deliver.Flow
    setUp, main, prompts, shape = Flow.setUp, Flow.main, Flow.prompts, Flow.shape
    del Flow

    def use(self, command, **kw):
        provision.mark(self.place, self.src, {"lifecycle": "persistent"}, self.g)
        self.shape(shape_text(command, **kw))

    def script(self, body):
        path = pathlib.Path(self.root).parent / "tool.py"
        path.write_text(body, encoding="utf-8")
        return f'"{sys.executable}" "{path}"'

    def test_a_settled_call_answers_and_wakes_no_one(self):
        self.use(self.script("import json,sys; v=json.load(sys.stdin); print('配った', v)"))
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins", "--input", '{"dry": true}')
        self.assertEqual(rc, 0, out)
        self.assertIn("配った {'dry': True}", out)
        self.assertEqual(self.prompts(), [])
        (rec,) = deliver.records(self.inbox)
        self.assertEqual((rec["kind"], rec["status"], rec["tool"]), ("call", "done", "spread-plugins"))

    def test_an_unsettled_call_is_counted_and_handed_to_the_ai_role(self):
        self.use(self.script("import sys; print('p2 で失敗'); sys.exit(4)"))
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins")
        self.assertEqual(rc, calls.CALLED, out)
        miss = [r for r in deliver.records(self.inbox) if r["kind"] == "miss"]
        self.assertEqual((len(miss), miss[0]["code"], miss[0]["tail"]), (1, 4, "p2 で失敗"))
        self.assertIn("ツール 配布/spread-plugins は片づかなかった（終了の値 4）。調べ役 に回した: 受付 ", out)
        (w,) = self.prompts()   # keep の部署「調べ」に頼む（待ち受けが居ないので窓に打つ）
        self.assertIn("-ask.md を読んで", w[2])
        brief = next(pathlib.Path(self.inbox).glob("*-call.md")).read_text(encoding="utf-8")
        self.assertIn("機械のツール「全アカウントに配る」（配布/spread-plugins）が片づけられなかった（終了の値 4）", brief)
        self.assertIn("p2 で失敗", brief)
        # 外れは --tree で数えられる
        companies = [{"root": self.src, "name": "src", "skills": [], "departments": []}]   # tree.build の会社の 1 件の形
        calls.annotate(companies, os.path.dirname(self.cfg), self.g)
        self.assertEqual(companies[0]["tools"][0]["misses"], 1)

    def test_a_rerun_inside_the_handed_over_ask_returns_the_miss_instead_of_handing_over_again(self):
        # 片づかずに回った頼みを受けた部署が、その頼みの中で同じ入力を打ち直しても、同じ頼みをもう 1 つ積まない（my_notes の受付 50f4d5）
        self.use(self.script("import sys; print('まだ取れない'); sys.exit(4)"))
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins", "--input", '{"dry": true}')
        self.assertEqual(rc, calls.CALLED, out)
        (first,) = [r["id"] for r in deliver.records(self.inbox) if r["kind"] == "ask"]
        provision.mark(self.place, self.src, {"ask": first}, self.g)   # 回った頼みを部署が受けている
        rc, out = self.main(self.place, "--call", "配布", "spread-plugins", "--input", '{"dry":  true}')
        self.assertEqual(rc, 1, out)
        self.assertIn(f"この会話が受けている頼み（受付 {first}）が、同じ入力でこのツールが片づかずに回った頼みなので、もう一度は回さない", out)
        self.assertIn("まだ取れない", out)
        rows = deliver.records(self.inbox)
        self.assertEqual([r["id"] for r in rows if r["kind"] == "ask"], [first])
        self.assertEqual([(r.get("ask"), r.get("rerun_of")) for r in rows if r["kind"] == "miss"], [(first, None), (None, first)])
        # 別の入力は打ち直しでないので、今までどおり回しに行く（ここでは宛先がこの部署自身で、まだ納品していないので --ask が止める）
        rc, out = self.main(self.place, "--call", "配布", "spread-plugins", "--input", '{"dry": false}')
        self.assertIn("調べ役 に回したが、頼みが通らなかった", out)
        self.assertEqual([r.get("rerun_of") for r in deliver.records(self.inbox) if r["kind"] == "miss"], [None, first, None])
        # 合図（--land の後に呼ぶ）は打ち直しを見分けず、今までどおり回しに行く
        a = argparse.Namespace(config=self.cfg, dry_run=False, from_name=None, from_account=None, ask=None, text=None,
                               brief=None, task=None, branch=None, role=None, persistent=False)
        calls.fire([{"role": "配布", "tool": "spread-plugins", "input": {"dry": True}}], self.src, self.ports, a, None,
                   {"ask": first, "boss": "窓口", "boss-inbox": self.inbox})
        last = [r for r in deliver.records(self.inbox) if r["kind"] == "miss"][-1]
        self.assertEqual((last.get("rerun_of"), bool(last.get("ask"))), (None, True))

    def test_bad_input_stops_before_running(self):
        self.use(self.script("raise SystemExit(9)"))
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins", "--input", '{"x": 1}')
        self.assertEqual(rc, 2, out)
        self.assertIn("知らない鍵 x", out)
        self.assertEqual(deliver.records(self.inbox), [])

    def test_the_tree_shows_the_account_the_fallback_role_names(self):
        # 片づかなかった仕事を回す役の部署は hand_over が立てるので、役の account が効く。--tree のツールの行に出す
        self.use("true")
        self.shape(shape_text("true").replace('name = "調べ役"\n', 'name = "調べ役"\naccount = "cheapest"\n', 1))
        companies = [{"root": self.src, "name": "src", "skills": [], "departments": [], "problems": []}]
        calls.annotate(companies, os.path.dirname(self.cfg), self.g)
        self.assertEqual(companies[0]["tools"][0]["account"], "cheapest")
        companies[0].update(info_source=None, description=None)
        self.assertIn("片づかなければ 調べ役 に回す（先に使うアカウント cheapest）  外れ 0 回", "\n".join(tree.lines(companies)))

    def test_a_tool_dropped_for_its_fallback_shows_on_the_tree(self):
        # 外したツールは --land の合図で黙って呼ばれなくなるので、--tree の会社の注記に出す
        self.use("true", fallback='fallback_role = "見張り"')
        companies = [{"root": self.src, "name": "src", "skills": [], "departments": [], "problems": []}]
        calls.annotate(companies, os.path.dirname(self.cfg), self.g)
        self.assertEqual(companies[0]["tools"], [])
        self.assertIn("回す先 見張り が会社の形の役にも受け持ちにも無いので外す", companies[0]["problems"][0])

    def test_handing_over_to_an_on_demand_duty_lets_ask_name_its_department(self):
        # on-demand の受け持ちに回すときは、ツールの名前の部署を立てず、--ask と同じく受け持ちの名前の部署を立てる
        self.use("true", fallback='fallback_role = "見渡し"')
        with open(os.path.join(self.src, ".claude", "company.toml"), "a", encoding="utf-8") as f:
            f.write('\n[[skills]]\nname = "見渡し"\nrole = "調べ役"\non_demand = true\n')
        seen = {}

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.update(name=ns.task, role=ns.role)
            return 1
        a = argparse.Namespace(config=self.cfg, dry_run=False, from_name=None, from_account=None, ask=None, text=None,
                               brief=None, task=None, branch=None, role=None, persistent=False, base=None)
        info = tree.read_info(self.src, os.path.dirname(self.cfg), self.g)
        tool = role.load(info["path"], info["text"])["roles"]["配布"]["tools"][0]
        calls.hand_over(self.src, tree.company_name(self.src, info), "配布", tool, {}, 1, "", self.ports, a, task, None, self.src)
        self.assertEqual((seen.get("name"), seen.get("role")), ("見渡し", "調べ役"))

    def test_handing_over_to_a_duty_whose_department_is_down_raises_it_with_the_duty_role(self):
        # on-demand でない受け持ち「調べ物」の部署が立っていなければ（立っているのは別の名前の「調べ」）、--tree の宛て方（--ask 会社/<役> --task <受け持ち>）と同じ形で立てる
        self.use("true", fallback='fallback_role = "調べ物"')
        with open(os.path.join(self.src, ".claude", "company.toml"), "a", encoding="utf-8") as f:
            f.write('\n[[skills]]\nname = "調べ物"\nrole = "調べ役"\n')
        seen = {}

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.update(name=ns.task, role=ns.role)
            return 1
        a = argparse.Namespace(config=self.cfg, dry_run=False, from_name=None, from_account=None, ask=None, text=None,
                               brief=None, task=None, branch=None, role=None, persistent=False, base=None)
        info = tree.read_info(self.src, os.path.dirname(self.cfg), self.g)
        tool = role.load(info["path"], info["text"])["roles"]["配布"]["tools"][0]
        calls.hand_over(self.src, tree.company_name(self.src, info), "配布", tool, {}, 1, "", self.ports, a, task, None, self.src)
        self.assertEqual((seen.get("name"), seen.get("role")), ("調べ物", "調べ役"))

    def test_handing_over_finds_the_keep_department_that_still_has_the_roles_former_name(self):
        # 役の名前を替えた（former_names）後も、前の名前を属性に持つ keep の部署に回す（今の名前に引き直さず、ツールの名前の部署を新しく立てていた）
        self.use("true")
        provision.mark(self.place, self.src, {"role": "旧調べ役"}, self.g)
        self.shape(shape_text("true").replace('name = "調べ役"\n', 'name = "調べ役"\nformer_names = ["旧調べ役"]\n', 1))
        seen = {}

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.update(name=ns.task)
            return 1
        a = argparse.Namespace(config=self.cfg, dry_run=False, from_name=None, from_account=None, ask=None, text=None,
                               brief=None, task=None, branch=None, role=None, persistent=False, base=None)
        info = tree.read_info(self.src, os.path.dirname(self.cfg), self.g)
        tool = role.load(info["path"], info["text"])["roles"]["配布"]["tools"][0]
        rc, out = calls.hand_over(self.src, tree.company_name(self.src, info), "配布", tool, {}, 1, "", self.ports, a, task, None,
                                  self.src)
        self.assertEqual((rc, seen), (calls.CALLED, {}), out)
        self.assertNotIn("部署", out[0].rsplit("受付", 1)[1])

    def test_fire_after_land_hands_over_with_the_landers_boss(self):
        self.use(self.script("raise SystemExit(1)"))
        a = argparse.Namespace(config=self.cfg, dry_run=False, from_name=None, from_account=None, ask=None, text=None,
                               brief=None, task=None, branch=None, role=None, persistent=False)
        lines = calls.fire([{"role": "配布", "tool": "spread-plugins", "input": {}}], self.src, self.ports, a, None,
                           {"boss": "窓口", "boss-account": "a1", "boss-inbox": self.inbox})
        self.assertEqual(lines[0], "合図（メインブランチに入れた後）: 配布/spread-plugins AI に回した")
        attrs = self.g.worktree_attrs(self.place)   # 回した頼みの頼み元は、メインブランチに入れた部署の頼み元
        self.assertEqual((attrs["boss"], attrs["boss-account"]), ("窓口", "a1"))
        self.assertEqual(len(self.prompts()), 1)

    def test_fire_after_a_land_by_a_department_without_a_boss_hands_over_with_the_desk(self):
        # 機械の上げ（works-factory-pin）が自分の作業場から打った --land は、部署に頼み元が無い。頼み元の無いまま回すと、立った部署の納品が
        # 受付箱を引けずに止まった（2026-10-29 の受付 cee7e1。頼み 2c4310）
        self.use(self.script("raise SystemExit(1)"))
        a = argparse.Namespace(config=self.cfg, dry_run=False, from_name=None, from_account=None, ask=None, text=None,
                               brief=None, task=None, branch=None, role=None, persistent=False)
        provision.mark(self.src, self.src, {"name": "受付", "lifecycle": "persistent"}, self.g)   # 本社の名付いた会話（窓口）
        lines = calls.fire([{"role": "配布", "tool": "spread-plugins", "input": {}}], self.src, self.ports, a, None, {"name": None})
        self.assertEqual(lines[0], "合図（メインブランチに入れた後）: 配布/spread-plugins AI に回した")
        attrs = self.g.worktree_attrs(self.place)   # 回した頼みの頼み元は会社の窓口
        self.assertEqual((attrs.get("boss"), attrs.get("boss-inbox")), ("受付", self.inbox))
        (row,) = [r for r in deliver.records(self.inbox) if r["kind"] == "ask"]
        self.assertEqual(row["from"]["name"], "受付")

    def test_fire_after_a_land_by_a_department_without_a_boss_hands_over_with_the_held_asks_boss(self):
        # 受付 cee7e1 の形: --land を打った場所が頼みを受けていれば、その頼みの頼み元（cause_boss）を頼み元にする
        self.use(self.script("raise SystemExit(1)"))
        a = argparse.Namespace(config=self.cfg, dry_run=False, from_name=None, from_account=None, ask=None, text=None,
                               brief=None, task=None, branch=None, role=None, persistent=False)
        provision.mark(self.src, self.src, {"ask": "20261029-005748-29e7fd", "boss": "窓口", "boss-session": "s0",
                                            "boss-inbox": self.inbox}, self.g)
        calls.fire([{"role": "配布", "tool": "spread-plugins", "input": {}}], self.src, self.ports, a, None, {"name": None})
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual((attrs.get("boss"), attrs.get("boss-session"), attrs.get("boss-inbox")), ("窓口", "s0", self.inbox))
        (row,) = [r for r in deliver.records(self.inbox) if r["kind"] == "ask"]
        self.assertEqual((row["from"]["name"], row["cause"]), ("窓口", "20261029-005748-29e7fd"))

    def test_a_handed_boss_falls_back_to_the_parent_asks_boss_then_the_desk(self):
        parent = {"name": "窓口", "session": "s0", "account": "a0", "pane": "w1:p1", "inbox": "/in"}
        desk = {"boss": "受付", "boss-inbox": "/desk"}
        self.assertEqual(orders.lent_boss({"ask": "x", "boss": "頼み元", "boss-inbox": "/b"}, parent, lambda: desk),
                         {"boss": "頼み元", "boss-inbox": "/b"})
        self.assertEqual(orders.lent_boss({"ask": "x", "boss": None, "boss-session": None}, parent, lambda: desk),
                         {"boss": "窓口", "boss-session": "s0", "boss-account": "a0", "boss-pane": "w1:p1", "boss-inbox": "/in"})
        self.assertEqual(orders.lent_boss({"boss": None}, None, lambda: desk), desk)
        self.assertEqual(orders.lent_boss({"boss": None}, None, lambda: None), {"boss": None})

    def test_fire_after_a_batch_names_every_member_and_parents_the_riders_asks(self):
        # 束（束の設計 9）: 合図は 1 回。ツールに部署の名前の並びを渡し、回した頼みの親に乗った部署の受けている頼みを並べる（納品済みと束ね役と同じ頼みは除く）
        self.use(self.script(f"import os, sys; print(os.environ['{calls.WORKS_LAND_MEMBERS}'].replace(chr(10), ',')); sys.exit(1)"))
        a = argparse.Namespace(config=self.cfg, dry_run=False, from_name=None, from_account=None, ask=None, text=None,
                               brief=None, task=None, branch=None, role=None, persistent=False)
        members = [{"name": "b", "ask": "r-b"}, {"name": "c", "ask": "r-c", "delivered": "r-c"}, {"name": "d", "ask": "l"}, {"name": "e"}]
        calls.fire([{"role": "配布", "tool": "spread-plugins", "input": {}}], self.src, self.ports, a, None,
                   {"name": "a", "ask": "l", "boss": "窓口", "boss-inbox": self.inbox}, members=members)
        rows = deliver.records(self.inbox)
        self.assertEqual([r["tail"] for r in rows if r["kind"] == "miss"], ["a,b,c,d,e"])
        self.assertEqual([(r.get("cause"), r.get("causes")) for r in rows if r["kind"] == "ask"], [("l", ["r-b"])])

if __name__ == "__main__":
    unittest.main()


class ToolPlace(unittest.TestCase):
    """--call がツールを走らせる一時の場所（メインブランチの先頭に切る detached の worktree。鍵・残った場所の片付け・どのブランチにも無い
    commit を残す ref）。git の worktree と ref の振る舞いそのものを見るので、git は一時のフォルダの本物（git との境目の組）。"""

    Flow = test_deliver.Flow
    main, shape = Flow.main, Flow.shape
    use, script = Call.use, Call.script
    del Flow

    def setUp(self):
        test_deliver.Flow.setUp(self, real=True)

    def test_the_tool_runs_on_the_default_branch_not_on_what_the_clone_has_open(self):
        self.use("git rev-parse HEAD")
        want = gitx.rev(self.src, gitx.origin_head(self.src))
        git("-C", self.src, "switch", "-q", "-c", "other")   # 持ち主が代表の clone で別のブランチを開いている
        git("-C", self.src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "other")
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins")
        self.assertEqual(rc, 0, out)
        self.assertIn(want, out)
        self.assertEqual(len(git("-C", self.src, "worktree", "list").splitlines()), 2)   # 一時の worktree は消える（代表の clone と部署）

    def test_the_tool_place_does_not_carry_the_clone_department_attrs(self):
        # git の worktree add は config.worktree を写す。本社の属性が載ると、--call の間だけ同じ名前の部署が 2 つに見えた（2026-10-17）
        self.use("git config --worktree --get-regexp company || echo 属性無し")
        gitx.enable_worktree_config(self.src)
        gitx.set_worktree_attr(self.src, "name", "段取り")
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins")
        self.assertEqual(rc, 0, out)
        self.assertIn("属性無し", out)
        self.assertEqual(gitx.worktree_attrs(self.src)["name"], "段取り")   # 本社の属性はそのまま

    def test_the_tool_place_is_locked_by_the_running_process(self):
        self.use("git worktree list --porcelain")
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"locked {tools.OWNER}{os.getpid()}", out)
        self.assertEqual(len(git("-C", self.src, "worktree", "list").splitlines()), 2)

    def leave(self, owner=False):
        """殺された処理が残したツールの場所を作る（owner は鍵の訳。省けば終わった処理の pid の鍵、None なら鍵を掛けない）。"""
        if owner is False:
            gone = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, encoding="utf-8")
            owner = f"{tools.OWNER}{gone.stdout.strip()}"
        path = os.path.join(tempfile.mkdtemp(prefix=tools.PREFIX), "tree")
        self.addCleanup(shutil.rmtree, os.path.dirname(path), True)
        gitx.add_detached(self.src, path, gitx.rev(self.src, "HEAD"), lock=owner)
        return path

    @unittest.skipIf(os.name == "nt", "Windows では作った処理が居るかを確かめない（os.kill は 0 を渡しても処理を止める）ので、--clean・--call は鍵の pid の処理が居ない場所を消さない（消し方は test_sweep_with_a_gone_owner で見る）")
    def test_places_left_by_killed_runs_are_swept_by_the_next_call_and_by_clean(self):
        # 2026-10-17 に my_notes で、消えずに残ったツールの場所と、場所が無いのに鍵だけ残った行が --tree に「（ブランチ無し）」で並んだ
        self.use("true")
        dead = self.leave()
        old = self.leave(None)   # 前の版の place が作った（鍵が無い）。前の版のツールが走っているかもしれない
        moved = self.leave("initializing")
        shutil.rmtree(os.path.dirname(moved))
        live = self.leave(f"{tools.OWNER}{os.getpid()}")
        listed = lambda: {os.path.realpath(e["path"]) for e in gitx.listed_worktrees(self.src) if tools.is_place(e["path"])}   # noqa: E731
        rc, out = self.main(self.src, "--clean")
        self.assertIn(f"ツールの一時の場所 {os.path.realpath(live)}  残す（ツールが走っている）", out)
        self.assertIn(f"ツールの一時の場所 {os.path.realpath(old)}  残す（鍵が無い。ツールが走っているかもしれないので消さない。走っていなければ "
                      f"git -C {self.src} worktree remove -f -f {os.path.realpath(old)} で消す）", out)
        self.assertEqual(out.count("消せる（作った処理がもう居ない）"), 2, out)
        self.assertNotIn("（ブランチ無し）", out)
        self.assertEqual(len(listed()), 4)   # 並べるだけでは消さない
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins")
        self.assertEqual(rc, 0, out)
        self.assertEqual(listed(), {os.path.realpath(live), os.path.realpath(old)})
        self.assertFalse(os.path.exists(os.path.dirname(dead)))
        self.assertEqual(git("-C", self.src, "for-each-ref", tools.KEPT_REF), "")   # 先頭がブランチに在れば ref を足さない
        gitx.remove_detached(self.src, live)
        gitx.remove_detached(self.src, old)
        self.leave()
        rc, out = self.main(self.src, "--tree")
        self.assertIn("（ツールの一時の場所）", out)
        rc, out = self.main(self.src, "--clean", "--apply")
        self.assertIn("消した", out)
        self.assertEqual(listed(), set())

    @unittest.skipIf(os.name == "nt", "Windows では作った処理が居るかを確かめない（os.kill は 0 を渡しても処理を止める）ので、--clean・--call は鍵の pid の処理が居ない場所を消さない（消し方は test_sweep_with_a_gone_owner で見る）")
    def test_a_commit_only_in_a_left_place_is_kept_and_a_dirty_place_is_left(self):
        # 2026-10-17 に my_notes に残ったツールの場所には、push できないまま殺された写しのツールの commit が載っていた
        made = self.leave()
        git("-C", made, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "来歴")
        sha = gitx.rev(made, "HEAD")
        dirty = self.leave()
        pathlib.Path(dirty, "half.txt").write_text("書きかけ", encoding="utf-8")
        rc, out = self.main(self.src, "--clean")
        self.assertIn(f"どのブランチにも無い先頭の commit を {tools.KEPT_REF}{sha} に残してから消す", out)
        self.assertIn("残す（作った処理はもう居ないが、未コミットの変更が在る。中を見て、要らなければ git -C", out)
        rc, out = self.main(self.src, "--clean", "--apply")
        self.assertEqual(rc, 0, out)   # 書きかけの場所を残すのは失敗に数えない
        self.assertEqual(gitx.rev(self.src, f"{tools.KEPT_REF}{sha}"), sha)
        self.assertFalse(os.path.exists(made))
        self.assertTrue(os.path.exists(os.path.join(dirty, "half.txt")))
        (path, reason, why), = tools.sweep(self.src, self.g)[1]
        self.assertEqual((os.path.realpath(path), reason, why), (os.path.realpath(dirty), tools.DIRTY, "未コミットの変更が在る"))

    def test_a_commit_made_by_the_tool_is_kept_and_a_dirty_place_is_left(self):
        # 走り終えた場所を消すときも、sweep と同じく、どのブランチにも無い commit を残し、未コミットの変更が在れば消さない（頼み cce9a3）
        self.use(self.script("import subprocess, sys; subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', "
                             "'-q', '--allow-empty', '-m', '来歴'], check=True); print(subprocess.run(['git', 'rev-parse', 'HEAD'], "
                             "capture_output=True, text=True).stdout.strip()); sys.exit(1)"))
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins")
        self.assertEqual(rc, calls.CALLED, out)
        (miss,) = [r for r in deliver.records(self.inbox) if r["kind"] == "miss"]
        sha = miss["tail"]   # ツールが走らせる場所で作った commit（どのブランチにも無い）
        self.assertEqual(gitx.rev(self.src, f"{tools.KEPT_REF}{sha}"), sha)
        self.assertEqual(len(git("-C", self.src, "worktree", "list").splitlines()), 2)
        self.use(self.script("import pathlib; pathlib.Path('half.txt').write_text('書きかけ', encoding='utf-8')"))
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins")
        self.assertEqual(rc, 0, out)
        (left,) = [e["path"] for e in gitx.listed_worktrees(self.src) if tools.is_place(e["path"])]
        self.addCleanup(shutil.rmtree, os.path.dirname(left), True)
        self.assertTrue(os.path.exists(os.path.join(left, "half.txt")))

    def test_a_place_that_cannot_be_made_stops_the_call_without_a_traceback(self):
        # git worktree add が落ちても（残ったパス・index.lock）、--land の後の合図ごと traceback で止まらず、一時のフォルダも残さない（頼み cce9a3）
        from unittest import mock
        self.use("true")
        made = []
        real = tempfile.mkdtemp
        def mkdtemp(**kw):
            made.append(real(**kw))
            return made[-1]
        with mock.patch.object(tools.tempfile, "mkdtemp", side_effect=mkdtemp), \
                mock.patch.object(gitx, "add_detached", side_effect=gitx.GitError("fatal: index.lock")):
            rc, out = self.main(self.src, "--call", "配布", "spread-plugins")
        self.assertEqual(rc, 1, out)
        self.assertIn("止めた: ツールを走らせる場所を作れない（fatal: index.lock）", out)
        # 失敗は台帳に残す（後から追えるように）。ツールは走っていないので外れとは数えず、ほかの部署へも回さない（頼み 2827a8）
        rows = [r for r in deliver.records(self.inbox) if r.get("kind") in ("call", "miss", "ask")]
        self.assertEqual([(r["kind"], r.get("status"), r.get("tool")) for r in rows], [("call", "failed", "spread-plugins")], rows)
        self.assertIn("fatal: index.lock", rows[0]["why"])
        self.assertTrue(made)
        self.assertFalse(any(os.path.exists(d) for d in made))

    def test_sweep_with_a_gone_owner_keeps_a_lone_commit_and_leaves_a_dirty_place(self):
        # 居るかの見方を渡して、消し方そのものを OS に依らずに見る（Windows の既定の見方は「居る」で消さない）
        made = self.leave()
        git("-C", made, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "来歴")
        sha = gitx.rev(made, "HEAD")
        dirty = self.leave()
        pathlib.Path(dirty, "half.txt").write_text("書きかけ", encoding="utf-8")
        done, failed = tools.sweep(self.src, gitx, alive=lambda pid: False)
        self.assertEqual([(os.path.realpath(e["path"]), e["keep"]) for e in done], [(os.path.realpath(made), sha)])
        self.assertEqual(gitx.rev(self.src, f"{tools.KEPT_REF}{sha}"), sha)
        self.assertFalse(os.path.exists(made))
        self.assertEqual([(os.path.realpath(p), reason, why) for p, reason, why in failed],
                         [(os.path.realpath(dirty), tools.DIRTY, "未コミットの変更が在る")])
        self.assertTrue(os.path.exists(os.path.join(dirty, "half.txt")))

    def test_an_unswept_place_gets_steps_that_keep_its_commit(self):
        # 鍵の無い物と、ほかの訳の鍵の物は走っているかを確かめられないので消さず、手で消す手順に commit を残す手を添える
        made = self.leave(None)
        git("-C", made, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "来歴")
        sha = gitx.rev(made, "HEAD")
        held = self.leave("持ち主が調べている")
        rc, out = self.main(self.src, "--clean", "--apply")
        self.assertIn(f"、先に git -C {self.src} update-ref {tools.KEPT_REF}{sha} {sha} で先頭の commit を残してから git -C", out)
        shown = pathlib.Path(os.path.realpath(held)).as_posix() if os.name == "nt" else os.path.realpath(held)   # git の並べる字（Windows は / 区切り）
        self.assertIn(f"ツールの一時の場所 {shown}  残す（鍵の訳が「持ち主が調べている」。ツールが走っているかもしれないので", out)
        self.assertTrue(os.path.exists(made) and os.path.exists(held))
