"""組み直し（入口の --reorg・--desk）と、前の名前で部署を引くこと（--ask の宛先・--land）。git は本物の一時の clone と worktree、
herdr と claude の会話の一覧は偽物で回す。"""

import json
import os
import pathlib
import unittest

from . import DISPATCH  # noqa: F401
from .test_company import CompanyHerdr
from .test_dispatch import FakePorts, gitx_source, make_cfg, run_main
from .test_provision import git
import gitx
import landing
from nodes import deliver, provision, role, wake


class Reorg(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        self.place = str(pathlib.Path(self.root) / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "work/dispatch", self.place, "origin/main")
        provision.mark(self.place, self.src, {"role": "担当", "residency": "resident", "account": "a1", "name": "振り分け",
                                              "session": "s-a", "boss": "窓口", "boss-session": "s-desk", "boss-pane": "P9"}, gitx)
        self.ports = FakePorts([])
        self.ports.herdr = CompanyHerdr(self.src)
        self.office_pane = self.ports.herdr.open_at(self.src, agent="claude")["pane_id"]
        self.pane = self.ports.herdr.open_at(self.place, agent="claude")["pane_id"]
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-a"}
        self.sessions = [{"id": "a", "sessionId": "s-a", "name": "振り分け", "cwd": self.place, "kind": "background",
                          "state": "working"},
                         {"id": "d", "sessionId": "s-desk", "name": "my-notes-31", "cwd": self.src, "kind": "interactive",
                          "status": "busy"}]
        self.ports.list_sessions = lambda cdir, include_done=False: list(self.sessions)
        self.ports._cwd = self.place

    def main(self, *argv):
        return run_main(["--config", self.cfg, *argv], self.ports)

    def ws(self, pane):
        return next(p["workspace_id"] for p in self.ports.herdr.panes() if p["pane_id"] == pane)

    def test_rename_keeps_the_old_name_and_renames_the_pane_and_workspace(self):
        rc, out = self.main("--reorg", "--name", "割り振り")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["name"], gitx.former_names(attrs)), ("割り振り", ["振り分け"]))
        self.assertEqual(self.ports.herdr.writes, [
            ("rename_workspace", self.ws(self.pane), "割り振り"),
            ("report_workspace_metadata", self.ws(self.pane), {"kind": "常設・持ち越し"}, []),
            ("rename_pane", self.pane, "割り振り"),
            ("report_pane_metadata", self.pane, "担当", "割り振り", {"role": "担当", "account": "a1", "boss": "窓口"}, [])])
        self.assertIn("company.name: 振り分け → 割り振り", out)
        self.assertIn("前の名前 振り分け でも --land・--ask で引ける", out)
        self.assertIn("/rename 割り振り", out)
        # もう一度替えると前の名前が積まれ、戻した名前は前の名前から外れる
        rc, out = self.main("--reorg", "--name", "振り分け")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["name"], gitx.former_names(attrs)), ("振り分け", ["割り振り"]))

    def test_role_residency_and_boss_are_replaced(self):
        push = pathlib.Path(self.src, ".claude")
        push.mkdir()
        (push / "company.toml").write_text('[[roles]]\nname = "担当"\nresident = true\n[[roles]]\nname = "作業"\n',
                                           encoding="utf-8")
        rc, out = self.main("--reorg", "--role", "作業", "--per-task", "--boss", "割り振り", "--boss-account", "a1")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["role"], attrs["residency"], attrs["boss"], attrs["boss-account"]), ("作業", "per-task", "割り振り", "a1"))
        # 前の頼み元の会話の id とペインは消す（納品は新しい頼み元を名前で引く）
        self.assertNotIn("boss-session", attrs)
        self.assertNotIn("boss-pane", attrs)
        # 役の名前の書き損じは止める
        rc, out = self.main("--reorg", "--role", "作業や")
        self.assertEqual(rc, 2)
        self.assertIn("在る役: 担当, 作業", out)

    def test_dry_run_and_nothing_to_change_write_nothing(self):
        rc, out = self.main("--reorg", "--name", "割り振り", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("空打ち", out)
        self.assertEqual(gitx.worktree_attrs(self.place)["name"], "振り分け")
        rc, out = self.main("--reorg", "--name", "振り分け")
        self.assertEqual(rc, 0, out)
        self.assertIn("付け替える物は無い", out)
        self.assertEqual(self.ports.herdr.writes, [])

    def test_wrong_uses_stop(self):
        for argv, said in ((["--reorg"], "替える物"), (["--reorg", "--resident", "--per-task"], "一緒に使えない"),
                           (["--name", "x"], "--reorg と一緒にだけ"), (["--reorg", "--desk"], "一緒に使えない")):
            with self.subTest(argv=argv):
                rc, out = self.main(*argv)
                self.assertEqual(rc, 2, out)
                self.assertIn(said, out)
        self.ports._cwd = self.src   # 本社は部署でない
        rc, out = self.main("--reorg", "--name", "x")
        self.assertEqual(rc, 2)
        self.assertIn("部署でない", out)

    def test_a_name_another_department_has_stops(self):
        other = str(pathlib.Path(self.root) / "other")
        git("-C", self.src, "worktree", "add", "-q", "-b", "work/other", other, "origin/main")
        provision.mark(other, self.src, {"role": "担当", "name": "点検"}, gitx)
        self.ports.herdr.open_at(other, agent="claude")
        rc, out = self.main("--reorg", "--name", "点検")
        self.assertEqual(rc, 2, out)
        self.assertIn("「点検」という名前の部署がもう在る", out)

    def test_desk_names_the_head_office_and_its_own_pane_with_the_company_on_the_workspace(self):
        self.ports._cwd = self.src
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk"}
        # 本社には持ち主のほかの会話も居る。窓口の会話の印のペインだけに付ける
        for p in self.ports.herdr._panes:
            if p["pane_id"] == self.office_pane:
                p["agent_session"] = {"value": "s-desk"}
        self.ports.herdr.add_pane(self.ws(self.office_pane), self.src, agent="claude")
        rc, out = self.main("--desk")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.src)
        self.assertEqual({k: attrs.get(k) for k in ("role", "residency", "name", "account", "session")},
                         {"role": "窓口", "residency": "resident", "name": "窓口", "account": "a1", "session": "s-desk"})
        self.assertEqual(self.ports.herdr.writes, [
            ("rename_workspace", self.ws(self.office_pane), os.path.basename(self.src)),
            ("report_workspace_metadata", self.ws(self.office_pane), {"kind": "常設・持ち越し"}, []),
            ("rename_pane", self.office_pane, "窓口"),
            ("report_pane_metadata", self.office_pane, "窓口", "窓口", {"role": "窓口", "account": "a1"}, ["boss"])])
        # 部署の場所で打つと、部署の名前を窓口にせず止める
        self.ports._cwd = self.place
        rc, out = self.main("--desk", "x")
        self.assertEqual(rc, 2, out)
        self.assertIn("--reorg で付け替える", out)

    def test_desk_does_not_ask_for_rename_when_the_conversation_already_has_the_name(self):
        # claude --name 窓口 で起こした窓口: 会話の名前がもう 窓口 なので /rename を勧めない
        self.sessions[1]["name"] = "窓口"
        self.ports._cwd = self.src
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk"}
        rc, out = self.main("--desk")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("/rename", out)

    def test_desk_takes_the_role_from_the_shape_keeps_its_name_and_writes_the_process(self):
        # 役の名前を替えた会社: --role を省いても、会社の形の desk_role を書く（DESK_ROLE の 窓口 を書かない）
        shape = pathlib.Path(self.src, ".claude", "company.toml")
        shape.parent.mkdir(exist_ok=True)
        shape.write_text('desk_role = "段取り"\n[[roles]]\nname = "段取り"\nformer_names = ["窓口"]\n[[roles]]\nname = "担当"\n',
                         encoding="utf-8")
        provision.mark(self.src, self.src, {"role": "窓口", "name": "段取り"}, gitx)
        self.sessions[1]["pid"] = 4242
        self.ports._cwd = self.src
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk"}
        rc, out = self.main("--desk")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.src)
        self.assertEqual({k: attrs.get(k) for k in ("role", "name", "session", "pid")},
                         {"role": "段取り", "name": "段取り", "session": "s-desk", "pid": "4242"})
        self.assertNotIn("former-names", attrs)
        # 前の役の名前で宛てても、今の役の常設の場所（本社の段取り）に当たる
        self.ports._cwd = self.place
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-dept"}   # 頼むのは部署の会話（窓口の会話が自分に頼むのは止まる）
        rc, out = self.main("--ask", f"{os.path.basename(self.src)}/窓口", "--brief", str(shape), "--dry-run")
        self.assertIn(f"宛先の部署 {os.path.basename(self.src)}/段取り（main）", out)

    def test_desk_writes_the_settings_of_its_role_and_shows_the_command_to_start_with_them(self):
        # 持ち主が手で起こす窓口に [roles.settings] を届ける口: --desk が設定のファイルを書き、起こす命令を出す
        shape = pathlib.Path(self.src, ".claude", "company.toml")
        shape.parent.mkdir(exist_ok=True)
        shape.write_text('[[roles]]\nname = "窓口"\n[[roles]]\nname = "担当"\n', encoding="utf-8")
        self.ports._cwd = self.src
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk"}
        path = os.path.join(gitx.git_dir(self.src), role.SETTINGS_FILE)
        rc, out = self.main("--desk")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("--settings", out)   # 役に設定が無ければ出さない
        self.assertFalse(os.path.exists(path))
        shape.write_text('[[roles]]\nname = "窓口"\n[roles.settings]\nenabledPlugins = { "works@m" = false }\n'
                         '[[roles]]\nname = "担当"\n', encoding="utf-8")
        rc, out = self.main("--desk", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("空打ちなので書いていない", out)
        self.assertFalse(os.path.exists(path))
        rc, out = self.main("--desk")   # 属性は替わらなくても、命令は出す
        self.assertEqual(rc, 0, out)
        self.assertIn("付け替える物は無い", out)
        self.assertIn(f"claude-a1 --name '窓口' --settings {path}", out)
        self.assertEqual(json.loads(pathlib.Path(path).read_text(encoding="utf-8")), {"enabledPlugins": {"works@m": False}})
        # 役の model・effort は、--move と同じく旗で付ける（effort の inherit は窓口に引き継ぐ会話が無いので付けない）
        shape.write_text('[[roles]]\nname = "窓口"\nmodel = "opus"\neffort = "inherit"\n[roles.settings]\neffortLevel = "low"\n'
                         '[[roles]]\nname = "担当"\n', encoding="utf-8")
        rc, out = self.main("--desk")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"claude-a1 --name '窓口' --model opus --settings {path}", out)

    def test_desk_does_not_take_the_seat_while_the_desk_talk_runs(self):
        # 窓口の会話が動いている間に、ほかの会話（試しの claude -p など）が --desk で席を取ると、納品がそちらに届く（53d5d1・6be241）
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-old", "pid": "777"}, gitx)
        self.sessions[1]["pid"] = 4242
        self.ports._cwd = self.src
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk"}
        self.ports.running_claude = lambda pid: pid == "777"
        rc, out = self.main("--desk")
        self.assertEqual(rc, 2, out)
        self.assertIn("窓口 窓口 の会話（処理 777、会話 s-old）がまだ動いている", out)
        self.assertEqual(gitx.worktree_attrs(self.src)["session"], "s-old")
        self.ports.running_claude = lambda pid: False   # 前の窓口を終えた（アカウントを移すときなど）
        rc, out = self.main("--desk")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.src)["session"], "s-desk")

    def test_desk_keeps_what_move_launched_and_forgets_it_for_a_talk_started_by_hand(self):
        # --move が起こした会話（company.launching）は起こした値を残す。手で起こした会話は、起こした値を知らないので消す
        # （区切りの番の終わりに、待ち受けが会社の形の設定で起こし直す）
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-old", "launched": "k1",
                                            wake.LAUNCHING: "1"}, gitx)
        self.ports._cwd = self.src
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk"}
        rc, out = self.main("--desk")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.src)
        self.assertEqual((attrs.get("launched"), attrs.get(wake.LAUNCHING)), ("k1", None))
        rc, out = self.main("--desk")   # 同じ会話が打ち直しても残す
        self.assertEqual(gitx.worktree_attrs(self.src).get("launched"), "k1")
        self.sessions[1]["sessionId"] = "s-hand"   # 持ち主が手で起こした会話
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-hand"}
        rc, out = self.main("--desk")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("launched", gitx.worktree_attrs(self.src))

    def test_desk_replaces_a_hand_written_role_and_keeps_the_old_name(self):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "my_notesの窓口"}, gitx)
        self.ports._cwd = self.src
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk"}
        rc, out = self.main("--desk", "窓口")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.src)
        self.assertEqual((attrs["name"], gitx.former_names(attrs)), ("窓口", ["my_notesの窓口"]))


class FormerNames(unittest.TestCase):
    def test_ask_target_finds_a_department_by_its_former_name_after_the_current_names(self):
        def row(name, former=(), path="/r/w"):
            attrs = {"name": name, "role": "担当", "residency": "resident"}
            if former:
                attrs["former-names"] = json.dumps(list(former), ensure_ascii=False)
            return {"branch": "b", "path": path, "attrs": attrs, "panes": []}
        companies = [{"name": "c", "root": "/r", "departments": [row("割り振り", ["振り分け"]), row("振り分け", path="/r/x")]}]
        self.assertEqual(deliver.find_target(companies, "/r", "振り分け")["department"]["path"], "/r/x")   # 今の名前が先
        companies[0]["departments"].pop()
        self.assertEqual(deliver.find_target(companies, "/r", "振り分け")["department"]["path"], "/r/w")

    def test_role_with_a_task_name_goes_to_that_department_not_to_another_resident(self):
        # --ask 会社/担当 --task 点検: 名前違いの常設の担当（割り振り）が 1 つだけ居ても、そこへは届けず、点検を新しく立てる
        def row(name, path):
            return {"branch": "b", "path": path, "attrs": {"name": name, "role": "担当", "residency": "resident"}, "panes": []}
        companies = [{"name": "c", "root": "/r", "departments": [row("割り振り", "/r/w")]}]
        got = deliver.find_target(companies, "/r", "c/担当", "点検")
        self.assertEqual((got["department"], got["role"]), (None, "担当"))
        self.assertEqual(deliver.find_target(companies, "/r", "c/担当")["department"]["path"], "/r/w")   # 名前を渡さなければ今までどおり
        companies[0]["departments"].append(row("点検", "/r/x"))
        self.assertEqual(deliver.find_target(companies, "/r", "c/担当", "点検")["department"]["path"], "/r/x")

    def test_land_finds_a_department_by_its_former_name(self):
        found = [{"path": "/w", "linked": True, "branch": "work/a"}, {"path": "/s", "linked": False, "branch": "main"}]
        attrs = {"/w": {"name": "割り振り", "former-names": '["総務部の管理者"]'}}
        hits = landing._find(found, "総務部の管理者", lambda p: attrs.get(p, {}))
        self.assertEqual([h[0]["path"] for h in hits], ["/w"])
        self.assertEqual(landing._find(found, "無い", lambda p: attrs.get(p, {})), [])

    def test_broken_former_names_read_as_none(self):
        for raw in ("{", '"x"', "[1, null]"):
            self.assertEqual(gitx.former_names({"former-names": raw}), [])


class Duty(unittest.TestCase):
    def test_the_hook_adds_the_duty_whose_name_is_the_department_name(self):
        text = role.context("担当", {"instructions": "預かる。"}, "c", {"name": "割り振り", "description": "works-dispatch の直し"})
        self.assertEqual(text, "この会話は会社「c」の部署で、役は「担当」。受け持ちは「割り振り」（works-dispatch の直し）。\n預かる。")
        self.assertEqual(role.context("作業", None, "c"), "この会話は会社「c」の部署で、役は「作業」。")


if __name__ == "__main__":
    unittest.main()
