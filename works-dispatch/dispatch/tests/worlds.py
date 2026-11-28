"""試験の場の作り（試験でない helper）。いくつもの試験のファイルが同じ場で回る所を、試験のクラスから借りずにここの 1 か所に置く。

- FlowWorld: --ask と --deliver を入口から回す場（test_deliver.Flow・test_retire・test_setup.AskWithoutRepos などが継ぐ）
- TaskWorld: 入口の --task を回す場（test_task.Task・test_role.TaskWithRole が継ぐ）

どちらも unittest.TestCase と一緒に継ぐ mixin で、自分の試験を持たない（継いでも試験は二度走らない）。
"""

import contextlib
import os
import pathlib
import re
import shlex
from unittest import mock

from . import fakegit
from .test_company import CompanyHerdr
from .test_dispatch import FakePorts, fake_cfg, gitx_source, make_cfg, run_main
from .test_provision import git
import dispatch
import gitx
import orders
import wake_hook
import role_hook
import limit_hook
import refresh_hook
import shape_hook
from nodes import deliver, provision, wake


BG = re.compile(r"^(claude-a\d) --bg --name ")


class FlowWorld:
    """--ask と --deliver を入口から。頼み元（窓口）は元の clone のペイン P0、部署は worktree の窓 P1。"""

    def setUp(self, real=False):
        """git は偽物（tests/fakegit.py。self.g）。real なら一時のフォルダの本物（self.g は gitx。git との境目を確かめる組が使う）。"""
        if real:
            self.cfg, self.root = make_cfg()
            self.g = gitx
        else:
            self.cfg, self.root, self.g = fake_cfg()
            fakegit.wire(self, self.g, orders, wake_hook, role_hook, limit_hook, refresh_hook, shape_hook)
        self.src = gitx_source(self.cfg)
        self.place = str(pathlib.Path(self.root) / "dept")
        if real:
            git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place, "origin/main")
        else:
            self.g.add_worktree(self.place, "dept/a", "origin/main")
        provision.mark(self.place, self.src, {"role": "調べ役", "account": "a1", "name": "調べ", "session": "s-dept"}, self.g)
        self.ports = FakePorts([], git=None if real else self.g)
        self.ports.term = CompanyHerdr(self.src, None if real else self.g)
        patcher = mock.patch.object(orders, "ghx", self.ports.gh)   # フック（orders.stop_hook）が呼ぶ時に引く gh の口も偽物にする
        patcher.start()
        self.addCleanup(patcher.stop)
        self.desk = self.ports.term.open_at(self.src, agent="claude")["pane_id"]
        self.window = self.ports.term.open_at(self.place, agent="claude")["pane_id"]
        self.ports.term.talking.add(self.window)   # 部署の窓の前には attach の画面（会話）が居る
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk", "HERDR_PANE_ID": self.desk}
        # 部署の会話は、窓に 1 行が送られると動き出す（status が busy になる）。--ask は送った後にそれを見て、届いたと確かめる
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "d", "sessionId": "s-dept", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working",
             "status": "busy" if any(w[0] == "prompt" and w[1] != self.desk for w in self.ports.term.writes) else "idle"}]
        self.inbox = os.path.join(self.src, ".git", "company", "inbox")

    def main(self, cwd, *argv):
        with contextlib.chdir(cwd):
            return run_main(["--config", self.cfg, *argv], self.ports)

    def other_clone(self, path):
        """ほかのリポジトリの clone（git init しただけ。origin が無い）を path に作り、ports.git が場所で振り分けるようにする。"""
        other = fakegit.FakeGit(path, {}, url="")
        self.ports.git = fakegit.Repos(self.g, other)
        return other

    def prompts(self):
        return [w for w in self.ports.term.writes if w[0] == "prompt"]

    def deliver_notices(self):
        """台帳に置いた納品の知らせ（kind deliver の wake.notice。宛先 to と会話に渡す文 text を持つ）。納品は窓に打たない。"""
        return [r for r in deliver.records(self.inbox) if r.get("kind") == "deliver" and "to" in r and "text" in r]

    def take_queued(self, place=None):
        """部署の待ち受けが順番待ちの先頭を渡したところまで進める（--take。待ち受けと同じに頼み元の属性を書く）。立っている部署への
        --ask は部署の窓に打たずに順番待ちに積むので（受付 d70b23）、納品などの試験はこれで部署が頼みを受けた形にする。渡した件。"""
        place = place or self.place
        [first, *_] = wake.queued(self.inbox, self.ports.git.git_dir(place))
        rc, out = self.main(place, "--take", first["id"])
        self.assertEqual(rc, 0, out)
        return first

    def ask_taken(self, *argv, cwd=None):
        """--ask <argv> を打ち、部署の待ち受けが受け取ったところまで進める（take_queued）。(終了の値, 出力)。"""
        rc, out = self.main(cwd or self.src, "--ask", *argv)
        self.assertEqual(rc, 0, out)
        self.take_queued()
        return rc, out

    def fall(self, keep_mark=False):
        """部署の窓の会話が落ちた形（PC の再起動などで attach の画面が終わり、ペインにはシェルだけが居る）。keep_mark なら、
        herdr がペインの会話の印を残したままの形（まっさらな環境での 6 回目の試しの 1）。"""
        self.ports.term.talking.discard(self.window)
        if not keep_mark:
            for p in self.ports.term._panes:
                if p["pane_id"] == self.window:
                    p["agent"] = None
        real_run = self.ports.term.run

        def run(pane, command):   # attach を打つと、窓に会話が戻る
            real_run(pane, command)
            if " attach " in command:
                self.ports.term.talking.add(pane)
                for p in self.ports.term._panes:
                    if p["pane_id"] == pane:
                        p["agent"] = "claude"
        self.ports.term.run = run

    def ask_args(self, **given):
        """orders.ask・orders.take・retire.spread に直に渡す引数。本物の dispatch の引数の定義（dispatch._parser）の既定に given を重ねて
        作るので、dispatch に引数が増えても試験の側で引数の写しを直さない。"""
        a = dispatch._parser().parse_args(["--config", self.cfg])
        vars(a).update(given)
        return a

    def ask_then_summary(self, text):
        # 同じ頼みを打ち直すと、部署が受けたままの頼み（同じ中身）の受付番号が返り、順番待ちには積まない。受けていなければ受けさせる
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "調べて")[0], 0)
        if not wake.pending(self.g.worktree_attrs(self.place)):
            self.take_queued()
        self.ports.term.writes.clear()
        summary = pathlib.Path(self.root).parent / "summary.md"
        summary.write_text(text, encoding="utf-8")
        return str(summary)

    def push_from_the_department(self, files):
        """部署が --land を通さずに、部署の作業場から手でメインブランチへ push した形（git push origin HEAD:main）。入れた commit を返す。"""
        fakegit.materialize(self.place, files)
        head = self.g.commit(self.place, files, "部署の作業")
        self.g.push(self.place, head, "main")
        return head

    def shape(self, text):
        # 会社の形は本社（元の clone）のものを読む（--tree と頼む側と同じ。部署のブランチの中の写しではない）
        shape = pathlib.Path(self.src) / ".claude" / "company.toml"
        shape.parent.mkdir(exist_ok=True)
        shape.write_text(text, encoding="utf-8")


class TaskWorld:
    """入口の --task を回す場。呼んだ会話の識別子は s-caller。"""

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
