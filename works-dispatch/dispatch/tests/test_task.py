"""サブエージェント（入口の --task）。git（tests/fakegit.py）・herdr の会話の口・claude・gh は偽物で回す。"""

import json
import os
import pathlib
import re
import shlex
import unittest
from unittest import mock

from . import DISPATCH, fakegit  # noqa: F401
from .test_dispatch import FakePorts, fake_cfg, gitx_source, run_main
from .test_provision import WorktreeHerdr
import dispatch
import gitx
from config import Repo
from nodes import provision


def two_accounts(cfg_path):
    """make_cfg の設定を、アカウント 2 つ（a1・a2）の形に書き直す。"""
    p = pathlib.Path(cfg_path)
    d = p.parent
    p.write_text(p.read_text(encoding="utf-8").replace(
        f"accounts = [{{ name = \"a1\", command = \"claude-a1\", config_dir = '{d}/c1' }}]",
        f"accounts = [{{ name = \"a1\", command = \"claude-a1\", config_dir = '{d}/c1' }},\n"
        f"            {{ name = \"a2\", command = \"claude-a2\", config_dir = '{d}/c2' }}]"), encoding="utf-8")
    return {"a1": f"{d}/c1", "a2": f"{d}/c2"}


def over(name):
    """その名のアカウントの週の使用率が上限を超えた控え。"""
    return {name: {"seven_day": {"used_percentage": 99, "resets_at": 10**10}, "five_hour": {"used_percentage": 1}}}


BG = re.compile(r"^(claude-a\d) --bg --name ")


def push_shape(g, text):
    """ほかの clone が origin の main に会社の形を commit して push した形にする（元の clone の origin/main は動かさない。別の所でメイン
    ブランチの会社の形を変えて、元の clone では fetch していない形）。g は git の偽物（tests/fakegit.py）。"""
    return g.push_origin("main", {".claude/company.toml": text}, "company")


SHAPE = '[[roles]]\nname = "調べ役"\nmodel = "haiku"\n'


class Task(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root, self.g = fake_cfg()
        fakegit.forbid_real_git(self)
        self.brief = str(pathlib.Path(self.root).parent / "brief.md")
        pathlib.Path(self.brief).write_text("頼み", encoding="utf-8")

    def ports(self, sessions=None, starts=True):
        """sessions: 設定のフォルダ → そのアカウントの会話の並び。呼んだ会話の識別子は s-caller。
        starts が真なら、ペインに打ち込んだ `<アカウントのコマンド> --bg --name <名前>` の後に、そのアカウントの一覧に裏の会話が出る。"""
        ports = FakePorts([], git=self.g)
        ports.fetch_prs = lambda repo: self.fail("--task では whose-turn を呼ばない")
        ports.env = {"CLAUDE_CODE_SESSION_ID": "s-caller"}
        d = pathlib.Path(self.cfg).parent
        dirs = {"claude-a1": f"{d}/c1", "claude-a2": f"{d}/c2"}

        def listed(cdir, include_done=False):
            got = list((sessions or {}).get(cdir, []))
            for i, w in enumerate(x for x in ports.term.writes if x[0] == "run" and BG.match(x[2])):
                if starts and dirs[BG.match(w[2]).group(1)] == cdir:
                    cwd = next(p["cwd"] for p in ports.term.panes() if p["pane_id"] == w[1])
                    got.append({"id": f"bg{i}", "sessionId": f"bg{i}-full", "name": shlex.split(w[2])[3], "cwd": cwd,
                                "kind": "background", "state": "working", "startedAt": i})
            return got

        ports.list_sessions = listed
        return ports

    def run_task(self, ports, *extra, name="直し", branch="task/fix"):
        return run_main(["--config", self.cfg, "--task", name, "--branch", branch, "--brief", self.brief, *extra], ports)

    def sent(self, ports):
        """裏の会話を起動した打ち込み（最初の文はその最後の語）。"""
        return [w[2] for w in ports.term.writes if w[0] == "run" and BG.match(w[2])]

    def place(self, ports, branch="task/fix"):
        return next(w["path"] for w in ports.term.worktrees(gitx_source(self.cfg)) if w["branch"] == branch)

    def test_creates_the_place_starts_a_background_session_there_and_attaches(self):
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertTrue(ports.preflight_task)
        src = gitx_source(self.cfg)
        path = self.place(ports)
        [command] = self.sent(ports)
        words = shlex.split(command) if os.name != "nt" else None
        # 作業場の名前は作業の名前。アカウントが 1 つなら、ペインの名前にアカウントを添えない。/catchup の窓を閉じる前置きも付けない
        self.assertEqual(ports.term.writes[:5], [
            ("create_worktree", "task/fix", "直し"),
            ("trust", "a1", src, path),
            ("rename_pane", "P0", "直し"),
            ("run", "P0", command),
            ("run", "P0", "claude-a1 attach bg0"),
        ])
        if words:
            self.assertEqual(words[:6], ["claude-a1", "--bg", "--name", "直し", "--settings", ports.department_settings()])
            self.assertTrue(words[6].startswith(f"作業の頼みです。{self.brief} を読んで進めてください。"), words)
            self.assertNotIn("\n", words[6])
        # 裏の会話にだけ効く設定は、会話が自分で worktree を作らないようにする
        self.assertEqual(json.loads(pathlib.Path(ports.department_settings()).read_text(encoding="utf-8")),
                         {"worktree": {"bgIsolation": "none"}})
        # 部署の属性は作業場の git の設定に入り、元の clone には入らない
        # 試験の設定は既定の置き場に無いので、その場所も書く（役を足すフックが設定の置き場の会社の形を探すため）
        # 部署がメインブランチを知った位置（ブランチを作ったときの origin のメインブランチ）も書く（--land の書き換えの取り合いのゲートが使う）
        # 起動したときの会社の形の model・effort も書く（毎回クリアする部署の待ち受けが、今の値と比べる）
        self.assertEqual(self.g.worktree_attrs(path), {"role": "作業", "lifecycle": "ephemeral", "residency": "per-task", "account": "a1", "name": "直し",
                                                     "session": "bg0-full", "job": "bg0", "config": self.cfg,
                                                     "launched": '{"effort": null, "model": null}',
                                                     "base": self.g.tracking["main"]})
        self.assertEqual(self.g.worktree_attrs(src), {})
        # 元の clone の .git/info/exclude に、部署の会話が書く許可の記録だけが入る（.claude/ を丸ごと隠すと、.claude/ の下に
        # 新しく作ったファイルの commit し忘れに気づけない）
        excluded = self.g.excludes
        self.assertIn(".claude/settings.local.json", excluded)
        self.assertNotIn(".claude/", excluded)
        self.assertIn("__pycache__/", excluded)   # 部署が試しに走らせた Python の控えで --land と --clean が止まらない
        # 表示名と札、作業場の印は、書いた属性から付ける（名前は起動するときに付けたので付け直さない）
        self.assertEqual(ports.term.writes[5], ("report_pane_metadata", "P0", "作業", "直し", {"role": "作業", "account": "a1"},
                                                 ["boss"]))
        self.assertEqual(ports.term.writes[6][0::2], ("report_workspace_metadata", {"kind": "エフェメラル", "seat": "ephemeral"}))
        self.assertIn("部署 直し  task/fix  a1  started", out)
        self.assertEqual(self.g.branch(src), "main")

    def test_role_and_residency_are_written_as_given(self):
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役", "--resident")   # 前の版の旗の名前も効く（今は --persistent）
        self.assertEqual(rc, 0, out)
        path = self.place(ports)
        attrs = self.g.worktree_attrs(path)
        self.assertEqual((attrs["role"], attrs["lifecycle"]), ("調べ役", "persistent"))
        # 永続の部署の最初のブランチも、入れたブランチと同じ記録に書く（入れずに次のブランチへ移っても、先頭がそのままなら後で消える）
        self.assertEqual(json.loads(attrs["landed-branches"]), {"task/fix": self.g.head_sha(path)})

    def test_shape_picks_the_default_role_and_a_role_can_be_resident(self):
        # 会社の形の default_role は --role を省いたときの役、役の resident = true は --persistent と同じ
        push_shape(self.g, 'default_role = "担当"\n[[roles]]\nname = "担当"\npersistent = true\n'
                                          '[[roles]]\nname = "作業"\n')
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        attrs = self.g.worktree_attrs(self.place(ports))
        self.assertEqual((attrs["role"], attrs["lifecycle"]), ("担当", "persistent"))
        self.assertNotIn("既定の", out)
        rc, out = self.run_task(ports, "--role", "作業", name="別", branch="task/other")
        self.assertEqual(rc, 0, out)
        attrs = self.g.worktree_attrs(self.place(ports, "task/other"))
        self.assertEqual((attrs["role"], attrs["lifecycle"]), ("作業", "ephemeral"))

    def test_a_duty_raised_only_when_asked_starts_per_task_even_under_a_resident_role(self):
        # 受け持ちの on_demand = true（オンデマンド）は、役が persistent = true でもエフェメラルの部署で立つ（--done で畳まれる）
        push_shape(self.g, 'default_role = "担当"\n[[roles]]\nname = "担当"\npersistent = true\n'
                                          '[[skills]]\nname = "直し"\nrole = "担当"\non_demand = true\n')
        ports = self.ports()
        rc, out = self.run_task(ports)   # 部署の名前（直し）が受け持ちの名前
        self.assertEqual(rc, 0, out)
        attrs = self.g.worktree_attrs(self.place(ports))
        self.assertEqual((attrs["role"], attrs["lifecycle"]), ("担当", "ephemeral"))

    def test_a_duty_role_starts_only_under_a_duty_name(self):
        # 受け持ちに名指される永続の役（担当）は、受け持ちの名前でない「<受け持ち>：<主題>」では立てない（立てると誰の席でもない
        # 永続の部署が残る。my_notes の受付 90b7d8）。受け持ちの名前なら永続で立ち、--persistent を名指せば名前を問わない
        push_shape(self.g, 'default_role = "作業"\n[[roles]]\nname = "担当"\npersistent = true\n'
                                          '[[roles]]\nname = "作業"\n[[skills]]\nname = "直し"\nrole = "担当"\n')
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "担当", name="直し：題", branch="task/topic")
        self.assertEqual(rc, 2, out)
        self.assertIn("止めた: 役 担当 は受け持ちごとに 1 つの永続の部署で、部署の名前は受け持ちの名前（直し）。「直し：題」はどれでもない", out)
        self.assertIn("--role 作業（--ask なら <会社>/作業）で頼む", out)
        self.assertFalse(self.sent(ports))
        self.assertFalse([w for w in ports.term.worktrees(gitx_source(self.cfg)) if w["branch"] == "task/topic"])
        rc, out = self.run_task(ports, "--role", "担当")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.g.worktree_attrs(self.place(ports))["lifecycle"], "persistent")
        rc, out = self.run_task(ports, "--role", "担当", "--persistent", name="別", branch="task/other")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.g.worktree_attrs(self.place(ports, "task/other"))["lifecycle"], "persistent")

    def test_default_role_missing_from_the_shape_stops(self):
        # 役の名前を英語で書いた会社などで、どの役でもない「作業」の部署を、役の本文も起動の設定も無いまま立てない
        push_shape(self.g, SHAPE)   # 役は調べ役だけで、default_role も無い
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 2, out)
        self.assertFalse([w for w in ports.term.worktrees(gitx_source(self.cfg)) if w["branch"] == "task/fix"])
        self.assertIn("止めた: --role を省いたので役は既定の 作業 だが、会社の形に無い", out)
        self.assertIn("default_role", out)

    def test_branch_on_origin_is_made_from_origin_not_the_default_branch(self):
        src = gitx_source(self.cfg)
        self.g.origin["task/old"] = self.g.origin["main"]
        sha = self.g.push_origin("task/old", {}, "theirs")
        ports = self.ports()
        rc, out = self.run_task(ports, branch="task/old")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.g.head_sha(self.place(ports, "task/old")), sha)

    def test_shape_changed_on_origin_is_fetched_before_the_role_is_read(self):
        src = gitx_source(self.cfg)
        sha = push_shape(self.g, SHAPE)
        ports = self.ports()
        rc, out = self.run_task(ports, "--role", "調べ役")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.g.tracking["main"], sha)
        # 起動するときの設定（model）も、立てた後のフックと同じ新しい会社の形で決まる
        [command] = self.sent(ports)
        self.assertRegex(command, r'--model "?haiku\b')   # POSIX でない殻（Windows）では語を "…" で囲む
        # 起動したときの model・effort を属性に残す（毎回クリアする部署の待ち受けが、会社の形の今の値と比べる）
        launched = self.g.worktree_attrs(self.place(ports))["launched"]
        self.assertEqual(json.loads(launched), {"model": "haiku", "effort": None})

    def test_dry_run_reads_the_shape_without_fetching(self):
        src = gitx_source(self.cfg)
        before = self.g.tracking["main"]
        push_shape(self.g, SHAPE)
        rc, out = self.run_task(self.ports(), "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.g.tracking["main"], before)
        self.assertIn("- 会社の形: 無い（--dry-run なので origin を取り直さず、手元の控えで読んだ）", out)

    def test_refresh_fetches_only_the_default_branch_and_notes_a_failure(self):
        src = gitx_source(self.cfg)
        sha = push_shape(self.g, SHAPE)
        self.assertIsNone(provision.refresh_shape(src, self.g))
        self.assertEqual(self.g.tracking["main"], sha)
        with mock.patch.object(self.g, "fetch", side_effect=gitx.GitError("fatal: '/gone.git' does not appear to be a git repository")):
            self.assertIn("origin の既定のブランチを取り直せないので、手元の origin/main", provision.refresh_shape(src, self.g))
            self.g.has_origin_head = False
            self.assertIsNone(provision.refresh_shape(src, self.g))   # 既定のブランチが分からなければ取りに行かない

    def test_clone_without_origin_head_is_told_how_to_fix_it(self):
        src = gitx_source(self.cfg)
        self.g.has_origin_head = False
        rc, out = self.run_task(self.ports(), "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"git -C {src} remote set-head origin --auto", out)

    def test_existing_place_is_opened_again_and_not_moved(self):
        src = gitx_source(self.cfg)
        elsewhere = str(pathlib.Path(self.root).parent / "hand-made")
        self.g.add_worktree(elsewhere, "task/fix", "origin/main")
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertEqual(ports.term.writes[0][0], "open_worktree")
        self.assertIn("task/fix  a1  started", out)

    def test_session_that_does_not_appear_is_launch_failed_with_the_screen(self):
        ports = self.ports(starts=False)
        ports.term.screen = "Error: something\n$ "
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 1, out)   # 起きなかったことを終了の値でも知らせる
        self.assertIn("task/fix  a1  launch_failed", out)
        self.assertIn(f"「直し」の裏の会話が出ない（{dispatch.STARTED_LOOKS} 回見た。画面の終わり: Error: something $）", out)
        self.assertFalse([w for w in ports.term.writes if w[0] == "run" and " attach " in w[2]])

    def test_desk_attributes_copied_by_git_worktree_add_are_not_kept(self):
        # git worktree add は本社の config.worktree を新しい worktree に写す。窓口の会話の id や前の名前が部署に残らない
        src = gitx_source(self.cfg)
        provision.mark(src, src, {"role": "窓口", "name": "窓口", "session": "s-desk", "former-names": '["前の窓口"]'}, self.g)
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        attrs = self.g.worktree_attrs(self.place(ports))
        self.assertEqual((attrs["role"], attrs["name"], attrs["session"]), ("作業", "直し", "bg0-full"))
        self.assertNotIn("former-names", attrs)
        self.assertEqual(self.g.worktree_attrs(src)["session"], "s-desk", "本社の属性は触らない")

    def test_running_task_again_on_a_standing_department_keeps_its_asker_inbox(self):
        # 立っている部署に --task を打ち直すと、本社と同じ値の頼み元の受付箱（company.boss-inbox）が、写り込んだ物と見て消えていた（d7d50c の 2）
        src = gitx_source(self.cfg)
        inbox = str(pathlib.Path(src) / ".git" / "company" / "inbox")
        provision.mark(src, src, {"role": "窓口", "name": "窓口", "boss-inbox": inbox}, self.g)
        ports = self.ports()
        self.assertEqual(self.run_task(ports)[0], 0)
        provision.mark(self.place(ports), src, {"boss-inbox": inbox, "ask": "q1"}, self.g)
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        attrs = self.g.worktree_attrs(self.place(ports))
        self.assertEqual((attrs.get("boss-inbox"), attrs.get("ask")), (inbox, "q1"))

    def test_a_session_that_appears_late_is_found_and_attached(self):
        # Windows の claude --bg は、裏の会話が一覧に出るまで 2〜3 秒かかる。1 回目に見えなくても、見直して見つけ、attach を打つ
        ports = self.ports()
        real, looks = ports.list_sessions, []

        def late(cdir, include_done=False):
            looks.append(cdir)
            return real(cdir, include_done) if len(looks) > 3 else []
        ports.list_sessions = late
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("task/fix  a1  started", out)
        self.assertTrue([w for w in ports.term.writes if w[0] == "run" and " attach " in w[2]])

    def test_same_account_caller_gets_sendmessage_and_becomes_the_boss(self):
        dirs = two_accounts(self.cfg)
        ports = self.ports({dirs["a1"]: [{"sessionId": "s-caller", "name": "窓口", "cwd": "/x"}]})
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        [command] = self.sent(ports)
        self.assertIn("SendMessage で「窓口」へ送る", command)
        # アカウントが 2 つ以上なら、ペインの名前にアカウントの名前を添える
        self.assertIn(("rename_pane", "P0", "直し a1"), ports.term.writes)
        attrs = self.g.worktree_attrs(self.place(ports))
        self.assertEqual((attrs["boss"], attrs["boss-account"]), ("窓口", "a1"))

    def test_other_account_caller_gets_the_screen_route(self):
        dirs = two_accounts(self.cfg)
        ports = self.ports({dirs["a1"]: [{"sessionId": "s-caller", "name": "窓口", "cwd": "/x"}]})
        ports.limits_seq = [over("a1")]
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("task/fix  a2  started", out)
        [command] = self.sent(ports)
        self.assertTrue(command.startswith("claude-a2 --bg "), command)
        self.assertIn(("run", "P0", "claude-a2 attach bg0"), ports.term.writes)
        self.assertIn("この画面に短く書いて止まる", command)
        self.assertIn("「窓口」とはアカウントが違い", command)
        self.assertNotIn("SendMessage で「", command)

    def test_account_with_fewer_running_conversations_gets_the_department(self):
        # 使用率が同じ（ここでは控えが無い）なら、PR と同じく動いている会話の少ないアカウントに立てる。a1 は設定の順では先
        dirs = two_accounts(self.cfg)
        ports = self.ports({dirs["a1"]: [{"sessionId": "w1", "cwd": "/x", "kind": "background", "state": "working"},
                                         {"sessionId": "w2", "cwd": "/y", "kind": "interactive", "status": "busy"}]})
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("task/fix  a2  started", out)

    def test_the_account_named_by_the_role_is_used_when_it_can_be(self):
        # 会社の形の役の account は、使えれば使用率の順より先（a1 は設定の順で先）。使えなければ使用率の順で選び、訳を注記に出す
        dirs = two_accounts(self.cfg)
        push_shape(self.g, '[[roles]]\nname = "作業"\naccount = "a2"\n')
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("task/fix  a2  started", out)
        self.assertNotIn("名指した", out)
        # a2 に終わっていない裏の会話（待機中）が在れば、使用率の順で a1
        ports = self.ports({dirs["a2"]: [{"sessionId": "w1", "cwd": "/x", "kind": "background", "state": "idle"}]})
        rc, out = self.run_task(ports, name="別", branch="task/other")
        self.assertEqual(rc, 0, out)
        self.assertIn("task/other  a1  started", out)
        self.assertIn("役 作業 が名指したアカウント a2 は終わっていない会話が 1 件在り、設定の max_open（1）に達したので、使用率の順で選ぶ", out)

    def test_max_open_lets_the_named_account_take_more_departments(self):
        # 設定の max_open まで、終わっていない会話の在る名指しのアカウントに立てる（my_notes の受付 20261021-063439-aee108。
        # 使用率の枠の無い Foundry の口に部署を並べる）
        dirs = two_accounts(self.cfg)
        p = pathlib.Path(self.cfg)
        p.write_text(p.read_text(encoding="utf-8").replace('name = "a2", command = "claude-a2",',
                                                           'name = "a2", command = "claude-a2", max_open = 2,'),
                     encoding="utf-8")
        push_shape(self.g, '[[roles]]\nname = "作業"\naccount = "a2"\n')
        idle = {"sessionId": "w1", "cwd": "/x", "kind": "background", "state": "idle"}
        rc, out = self.run_task(self.ports({dirs["a2"]: [idle]}))
        self.assertEqual(rc, 0, out)
        self.assertIn("task/fix  a2  started", out)
        rc, out = self.run_task(self.ports({dirs["a2"]: [idle, {**idle, "sessionId": "w2"}]}), name="別", branch="task/other")
        self.assertEqual(rc, 0, out)
        self.assertIn("task/other  a1  started", out)
        self.assertIn("終わっていない会話が 2 件在り、設定の max_open（2）に達した", out)

    def test_a_named_only_account_that_cannot_take_it_stops_instead_of_another_account(self):
        # 名指しのときだけ使うアカウントの名指しが使えなければ、ほかのアカウント（別のモデル）で立てずに止める
        dirs = two_accounts(self.cfg)
        p = pathlib.Path(self.cfg)
        p.write_text(p.read_text(encoding="utf-8").replace('name = "a2", command = "claude-a2",',
                                                           'name = "a2", command = "claude-a2", named_only = true,'),
                     encoding="utf-8")
        push_shape(self.g, '[[roles]]\nname = "作業"\naccount = "a2"\n')
        rc, out = self.run_task(self.ports({dirs["a2"]: [{"sessionId": "w1", "cwd": "/x", "kind": "background", "state": "idle"}]}))
        self.assertEqual(rc, 1, out)
        self.assertIn("止めた: 役 作業 が名指したアカウント a2 は終わっていない会話が 1 件在り、設定の max_open（1）に達した。"
                      "名指しのときだけ使うアカウント（named_only）なので、ほかのアカウントでは立てない", out)
        self.assertNotIn("started", out)

    def test_the_account_named_outside_its_hours_falls_back_to_the_usage_order(self):
        # 試験の時刻は 0（UTC 00:00）。a1 の使える時間帯の外なので、名指しても a2
        two_accounts(self.cfg)
        p = pathlib.Path(self.cfg)
        p.write_text(p.read_text(encoding="utf-8").replace('name = "a1", command = "claude-a1",',
                                                           'name = "a1", command = "claude-a1", hours = "08:00-16:00 UTC",'),
                     encoding="utf-8")
        push_shape(self.g, '[[roles]]\nname = "作業"\naccount = "a1"\n')
        self.g.fetch(self.g.source, "main")   # --dry-run は origin を取り直さないので、手元の控えに入れておく
        ports = self.ports()
        rc, out = self.run_task(ports, "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("役 作業 が名指したアカウント a1 は使える時間帯（08:00-16:00 UTC）の外", out)
        self.assertIn("- 先に使うアカウント: a1（役 作業。使わない）", out)
        self.assertIn("task/fix  a2  ", out)

    def test_unknown_caller_gets_the_screen_route_and_a_note(self):
        ports = self.ports()
        ports.env = {}
        rc, out = self.run_task(ports)
        [command] = self.sent(ports)
        self.assertIn("呼んだ会話が分からず", command)
        self.assertIn("--from-name と --from-account で渡す", out)

    def test_from_name_and_account_override_what_was_found(self):
        ports = self.ports()
        ports.env = {}
        rc, out = self.run_task(ports, "--from-name", "窓口", "--from-account", "a1")
        [command] = self.sent(ports)
        self.assertIn("SendMessage で「窓口」へ送る", command)

    def test_same_account_caller_without_a_name_gets_the_screen_route(self):
        ports = self.ports()
        ports.env = {}
        rc, out = self.run_task(ports, "--from-account", "a1")
        [command] = self.sent(ports)
        self.assertIn("呼んだ会話の名前が分からず", command)
        self.assertNotIn("アカウントが違い", command)

    def test_from_account_not_in_the_config_stops(self):
        ports = self.ports()
        rc, out = self.run_task(ports, "--from-account", "nobody")
        self.assertEqual(rc, 2)
        self.assertIn("--from-account の nobody が設定の accounts に無い", out)
        self.assertEqual(ports.term.writes, [])

    def test_task_cwd_in_the_config_is_noted_and_the_session_starts_in_the_place(self):
        with open(self.cfg, "a", encoding="utf-8") as f:
            f.write("task_cwd = '/notes'\n")
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("外した鍵 task_cwd は読まない（0.5.0 で外した", out)
        self.assertFalse([w for w in ports.term.writes if w[0] == "run" and w[2].startswith("cd ")])

    def test_dry_run_writes_nothing_and_shows_the_plan_and_the_first_text(self):
        ports = self.ports()
        rc, out = self.run_task(ports, "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(ports.term.writes, [])
        self.assertFalse(hasattr(ports, "refreshed"))
        self.assertIn("部署 直し  task/fix  a1  create", out)
        self.assertIn("- 部署の属性: company.role=作業、company.lifecycle=ephemeral、company.residency=per-task、company.account=a1、company.name=直し", out)
        self.assertIn("- 最初の文: 作業の頼みです。", out)
        self.assertNotIn(".claude/", self.g.excludes)

    def test_a_conversation_with_the_same_name_elsewhere_and_no_other_account_stops(self):
        dirs = {"a1": f"{pathlib.Path(self.cfg).parent}/c1"}
        ports = self.ports({dirs["a1"]: [{"sessionId": "s-other", "name": "直し", "cwd": "/x"}]})
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 1)
        self.assertIn("「直し」という名前の会話がほかの会社でもう開いていて（アカウント a1）、振れるアカウントがほかに無い", out)
        self.assertEqual(ports.term.writes, [])

    def test_a_conversation_with_the_same_name_in_another_company_moves_to_another_account(self):
        # 会社が違えば同じ名前の部署を並べて立てる。SendMessage の宛先はアカウントの中で決まるので、重なったアカウントを避ける
        dirs = two_accounts(self.cfg)
        ports = self.ports({dirs["a1"]: [{"sessionId": "s-other", "name": "直し", "cwd": "/elsewhere", "state": "working"}]})
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        [command] = self.sent(ports)
        self.assertTrue(command.startswith("claude-a2 --bg --name "), command)
        self.assertIn("ほかの会社でアカウント a1 に開いているので、そのアカウントを避けて振る", out)

    def test_a_conversation_with_the_same_name_in_this_company_stops_even_with_another_account(self):
        # 同じ会社の中の重なりは、「会社/名前」の宛て方でも分けられないので止める
        dirs = two_accounts(self.cfg)
        ports = self.ports({dirs["a1"]: [{"sessionId": "s-other", "name": "直し", "cwd": gitx_source(self.cfg), "state": "working"}]})
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 1)
        self.assertIn("「直し」という名前の会話がこの会社にもう開いている（アカウント a1）", out)
        self.assertEqual(ports.term.writes, [])

    def test_a_conversation_open_in_the_place_is_already_open(self):
        src = gitx_source(self.cfg)
        elsewhere = str(pathlib.Path(self.root).parent / "hand-made")
        self.g.add_worktree(elsewhere, "task/fix", "origin/main")
        ports = self.ports({f"{pathlib.Path(self.cfg).parent}/c1": [{"sessionId": "s1", "name": "別", "cwd": elsewhere}]})
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0)
        self.assertIn("already_open", out)
        self.assertEqual(ports.term.writes, [])

    def test_a_reused_place_loses_the_desk_process_number_copied_from_the_head_office(self):
        # 前の版で作った PR の作業場には本社の company.pid が写っている。残ると部署が窓口の席と見られ、役の本文を受けない（3d3ccc）
        src = gitx_source(self.cfg)
        old = str(pathlib.Path(self.root).parent / "old-pr")
        self.g.add_worktree(old, "task/fix", "origin/main")
        provision.mark(old, src, {"role": "窓口", "name": "窓口", "pid": "777"}, self.g)
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        attrs = self.g.worktree_attrs(old)
        self.assertEqual((attrs.get("pid"), attrs["name"]), (None, "直し"))

    def test_branch_open_in_the_source_clone_is_branch_busy(self):
        src = gitx_source(self.cfg)
        self.g.local["task/fix"] = self.g.local["main"]
        self.g.heads[src] = "task/fix"   # git checkout -b task/fix
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertIn("task/fix  a1  branch_busy", out)
        self.assertFalse([w for w in ports.term.writes if w[0] in ("run", "prompt")])

    def test_missing_brief_stops_before_anything(self):
        ports = self.ports()
        rc, out = run_main(["--config", self.cfg, "--task", "直し", "--branch", "b", "--brief", "/nowhere/brief.md"], ports)
        self.assertEqual(rc, 2)
        self.assertIn("頼みのファイルが無い", out)
        self.assertEqual(ports.term.writes, [])

    def test_task_needs_branch_and_brief_and_takes_no_other_entry(self):
        for argv, said in ((["--task", "直し"], "--branch <ブランチ> と --brief"),
                           (["--task", "直し", "--branch", "b", "--brief", "x", "--pr", "1"], "一緒に使えない"),
                           (["--branch", "b"], "--task と一緒にだけ使う"),
                           (["--role", "調べ役"], "--task と一緒にだけ使う"),
                           (["--persistent"], "--task と一緒にだけ使う")):
            with self.subTest(argv=argv):
                rc, out = run_main(["--config", self.cfg, *argv], self.ports())
                self.assertEqual(rc, 2)
                self.assertIn(said, out)

    def test_preflight_problem_stops(self):
        ports = FakePorts([], problems=["PATH の claude が --bg を持たない"], git=self.g)
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 2)
        self.assertIn("--bg を持たない", out)
        self.assertEqual(ports.term.writes, [])

    def test_repo_can_be_named_by_its_source_clone_path(self):
        ports = self.ports()
        rc, out = self.run_task(ports, "--repo", gitx_source(self.cfg), "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("部署 直し", out)


class PrepareTask(unittest.TestCase):
    def setUp(self):
        self.g, self.src, self.root = fakegit.world()
        fakegit.forbid_real_git(self)
        self.repo = Repo("o/r", "second", self.src, ("frontend/.env.local",))

    def test_new_branch_is_made_from_the_default_branch_with_the_task_name_and_files_copied(self):
        h = WorktreeHerdr(self.root, self.g)
        got = provision.prepare_task({"head": "task/new", "label": "新しい作業"}, self.repo, "main", h, self.g)
        self.assertEqual(got["status"], "ready", got)
        self.assertEqual(h.writes, [("create_worktree", "task/new", "新しい作業")])
        self.assertEqual(self.g.branch(got["path"]), "task/new")
        self.assertEqual(self.g.head_sha(got["path"]), self.g.tracking["main"])
        self.assertEqual((pathlib.Path(got["path"]) / "frontend" / ".env.local").read_text(), "SECRET=1\n")

    def test_existing_local_branch_is_checked_out_as_it_is(self):
        self.g.local["task/mine"] = self.g.tracking["feat/1"]   # git branch task/mine origin/feat/1
        h = WorktreeHerdr(self.root, self.g)
        got = provision.prepare_task({"head": "task/mine", "label": "x"}, self.repo, "main", h, self.g)
        self.assertEqual(got["status"], "ready", got)
        self.assertEqual(self.g.branch(got["path"]), "task/mine")

    def test_unreadable_origin_is_provision_failed(self):
        with mock.patch.object(self.g, "fetch", side_effect=gitx.GitError("fatal: '/nowhere/o/r.git' does not appear to be a git repository")):
            got = provision.prepare_task({"head": "task/new", "label": "x"}, self.repo, "main", WorktreeHerdr(self.root, self.g), self.g)
        self.assertEqual(got["status"], "provision_failed")
        self.assertTrue(got["detail"])

    def test_no_branch_is_provision_failed(self):
        got = provision.prepare_task({"head": None, "label": "x"}, self.repo, "main", WorktreeHerdr(self.root, self.g), self.g)
        self.assertEqual((got["status"], got["detail"]), ("provision_failed", "ブランチが決まっていない"))


if __name__ == "__main__":
    unittest.main()
