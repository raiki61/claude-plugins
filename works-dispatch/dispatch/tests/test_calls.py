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
import gitx
from nodes import deliver, land, provision, role, tools


def shape_text(command, fallback='fallback_role = "調べ役"', machine="machine = true"):
    return f"""
[[roles]]
name = "調べ役"
resident = true

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


class Call(unittest.TestCase):
    """--call を入口から。会社の形は本社のファイル。回す先は Flow の常設の部署「調べ」（役 調べ役）。"""

    Flow = test_deliver.Flow
    setUp, main, prompts, shape = Flow.setUp, Flow.main, Flow.prompts, Flow.shape
    del Flow

    def use(self, command, **kw):
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
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
        (path, why), = tools.sweep(self.src, gitx)[1]
        self.assertEqual((os.path.realpath(path), why), (os.path.realpath(dirty), "未コミットの変更が在る"))

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
        self.assertEqual([(os.path.realpath(p), why) for p, why in failed], [(os.path.realpath(dirty), "未コミットの変更が在る")])
        self.assertTrue(os.path.exists(os.path.join(dirty, "half.txt")))

    def test_an_unswept_place_gets_steps_that_keep_its_commit(self):
        # 鍵の無い物と、ほかの訳の鍵の物は走っているかを確かめられないので消さず、手で消す手順に commit を残す手を添える
        made = self.leave(None)
        git("-C", made, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "来歴")
        sha = gitx.rev(made, "HEAD")
        held = self.leave("持ち主が調べている")
        rc, out = self.main(self.src, "--clean", "--apply")
        self.assertIn(f"、先に git -C {self.src} update-ref {tools.KEPT_REF}{sha} {sha} で先頭の commit を残してから git -C", out)
        self.assertIn(f"ツールの一時の場所 {os.path.realpath(held)}  残す（鍵の訳が「持ち主が調べている」。ツールが走っているかもしれないので", out)
        self.assertTrue(os.path.exists(made) and os.path.exists(held))

    def test_an_unsettled_call_is_counted_and_handed_to_the_ai_role(self):
        self.use(self.script("import sys; print('p2 で失敗'); sys.exit(4)"))
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins")
        self.assertEqual(rc, calls.CALLED, out)
        miss = [r for r in deliver.records(self.inbox) if r["kind"] == "miss"]
        self.assertEqual((len(miss), miss[0]["code"], miss[0]["tail"]), (1, 4, "p2 で失敗"))
        self.assertIn("ツール 配布/spread-plugins は片づかなかった（終了の値 4）。調べ役 に回した: 受付 ", out)
        (w,) = self.prompts()   # 常設の部署「調べ」に頼む（待ち受けが居ないので窓に打つ）
        self.assertIn("-ask.md を読んで", w[2])
        brief = next(pathlib.Path(self.inbox).glob("*-call.md")).read_text(encoding="utf-8")
        self.assertIn("機械のツール「全アカウントに配る」（配布/spread-plugins）が片づけられなかった（終了の値 4）", brief)
        self.assertIn("p2 で失敗", brief)
        # 外れは --tree で数えられる
        companies = [{"root": self.src, "name": "src", "skills": [], "departments": []}]   # tree.build の会社の 1 件の形
        calls.annotate(companies, os.path.dirname(self.cfg), gitx)
        self.assertEqual(companies[0]["tools"][0]["misses"], 1)

    def test_bad_input_stops_before_running(self):
        self.use(self.script("raise SystemExit(9)"))
        rc, out = self.main(self.src, "--call", "配布", "spread-plugins", "--input", '{"x": 1}')
        self.assertEqual(rc, 2, out)
        self.assertIn("知らない鍵 x", out)
        self.assertEqual(deliver.records(self.inbox), [])

    def test_fire_after_land_hands_over_with_the_landers_boss(self):
        self.use(self.script("raise SystemExit(1)"))
        a = argparse.Namespace(config=self.cfg, dry_run=False, from_name=None, from_account=None, ask=None, text=None,
                               brief=None, task=None, branch=None, role=None, resident=False)
        lines = calls.fire([{"role": "配布", "tool": "spread-plugins", "input": {}}], self.src, self.ports, a, None,
                           {"boss": "窓口", "boss-account": "a1", "boss-inbox": self.inbox})
        self.assertEqual(lines[0], "合図（メインブランチに入れた後）: 配布/spread-plugins AI に回した")
        attrs = gitx.worktree_attrs(self.place)   # 回した頼みの頼み元は、メインブランチに入れた部署の頼み元
        self.assertEqual((attrs["boss"], attrs["boss-account"]), ("窓口", "a1"))
        self.assertEqual(len(self.prompts()), 1)

if __name__ == "__main__":
    unittest.main()
