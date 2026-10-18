"""会社の形（会社の形の設計 4.2・4.4・9.1）: 部署の属性（gitx）、ツリー図（tree ノードと --tree）、herdr の表示の付け直し（sync ノードと
--sync）、部署の片付け（clean.departments・retire と --clean）。git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest
import urllib.parse

from . import DISPATCH  # noqa: F401
from . import schemacheck
from .test_dispatch import FakeHerdr, FakePorts, gitx_source, make_cfg, run_main
from .test_provision import git, make_world
import dispatch
import gitx
import herdr as real_herdr
import orders
import shape_hook
from nodes import clean, land, provision, sync, tree


def fake_runner(out="", rc=0):
    calls = []

    def run(argv, env=None):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, rc, out, "")
    run.calls = calls
    return run


class OpenAsks(unittest.TestCase):
    """--tree が台帳から出す、まだ閉じていない頼み（deliver.open_asks・calls.asks_of）と、ほかの会社が兼ねる窓口（会社の形の desk）。"""

    def test_an_ask_closes_by_its_delivery_its_notice_a_forward_or_a_withdrawal(self):
        from nodes import deliver
        ask = lambda i, **k: {"kind": "ask", "id": i, "status": "queued", "to": {"company": "co", "name": "調べ"}, **k}
        records = [ask("a1"), ask("a2"), ask("a3"), ask("a4"), ask("a5"), ask("a6"), {"kind": "ask", "id": "a7", "status": "failed"},
                   {"kind": "deliver", "id": "d1", "ask": "a1", "status": "sent"},
                   {"kind": "deliver", "id": "a2", "to": "co/段取り"},   # 頼み元の待ち受けへの知らせ
                   {"kind": "forwarded", "id": "a3"}, {"kind": "withdrawn", "id": "a4"},
                   {"kind": "deliver", "id": "d5", "ask": "a5", "status": "failed"},   # 知らせられなかった納品は閉じない
                   {"kind": "deliver", "id": "d6", "ask": "a6", "status": "sent", "for": "x"}]   # --for の返しは今の頼みを閉じない
        self.assertEqual([r["id"] for r in deliver.open_asks(records)], ["a5", "a6"])
        f = pathlib.Path(tempfile.mkdtemp(), "q-ask.md")
        f.write_text("段取りが回した: 割り振りが止まっている\n\n---\n\n前提が違う、と思ったら返して。\n\n## 困りごと\n本文\n", encoding="utf-8")
        self.assertEqual(deliver.ask_title(str(f)), "困りごと")
        self.assertIsNone(deliver.ask_title("/無い"))

    def test_the_desk_of_another_company_written_in_the_shape_is_the_desk(self):
        d = tempfile.mkdtemp()
        info = pathlib.Path(d, "company.toml")
        info.write_text('name = "co"\ndesk = "my_notes/段取り"\n', encoding="utf-8")
        got = tree.read_info(d, None, committed=lambda root: (str(info), info.read_text(encoding="utf-8")))
        self.assertEqual((got["desk"], got["problems"]), ("my_notes/段取り", []))
        company = {"name": "co", "skills": [], "departments": [], "desk_of": got["desk"]}
        tree.contacts(company, {"roles": {}})
        self.assertEqual(company["desk"], {"name": "my_notes/段取り", "role": None, "ask": "--ask my_notes/段取り"})
        bad = tree.read_info(d, None, committed=lambda root: (str(info), 'desk = "段取り"\n'))
        self.assertIn("desk は「会社/名前」", bad["problems"][0])

    def test_open_asks_go_to_the_company_that_holds_the_department(self):
        import calls
        from nodes import deliver
        inbox = tempfile.mkdtemp()
        place = tempfile.mkdtemp()
        deliver.log(inbox, {"kind": "ask", "id": "a1", "status": "sent", "at": 1, "from": {"name": "段取り"},
                            "to": {"company": "co", "name": "調べ", "path": place}, "file": "/無い"})
        first = {"name": "co", "inbox": None, "departments": []}
        second = {"name": "co", "inbox": inbox, "departments": [{"path": place}]}
        calls.asks_of([first, second])
        self.assertEqual(first["asks"], [])
        (got,) = second["asks"]
        self.assertEqual((got["id"], got["from"], got["to"], got["state"]), ("a1", "段取り", "調べ", "渡った"))
        line = "\n".join(tree.lines([{"name": "co", "root": "/co", "info_source": None, "description": None, "skills": [],
                                       "problems": [], "departments": [], "asks": second["asks"]}]))
        self.assertIn("動いている頼み（台帳でまだ閉じていない物。1 件）:", line)
        self.assertIn("    a1  ", line)


class Attrs(unittest.TestCase):
    """部署の属性（git の worktree ごとの設定 company.*）と、.git/info/exclude。"""

    def setUp(self):
        self.src, self.root = make_world()
        self.place = str(pathlib.Path(self.root) / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place, "origin/main")

    def test_the_extension_turns_rerere_on_unless_the_owner_set_it(self):
        git("-C", self.src, "config", "rerere.autoUpdate", "false")   # 持ち主の値は替えない
        self.assertEqual(gitx.enable_worktree_config(self.src), "enabled")
        self.assertEqual(git("-C", self.src, "config", "--get", "rerere.enabled").strip(), "true")
        self.assertEqual(git("-C", self.src, "config", "--get", "rerere.autoUpdate").strip(), "false")

    def test_attrs_are_empty_before_the_extension_and_stay_in_their_own_worktree(self):
        self.assertEqual(gitx.worktree_attrs(self.place), {})
        self.assertEqual(gitx.enable_worktree_config(self.src), "enabled")
        self.assertEqual(gitx.enable_worktree_config(self.src), "already")
        provision.mark(self.place, self.src, {"role": "調べ役", "boss-account": "p1", "boss": None}, gitx)
        provision.mark(self.place, self.src, {"role": "調べ役"}, gitx)   # 同じ値をもう一度書いても同じ
        self.assertEqual(gitx.worktree_attrs(self.place), {"role": "調べ役", "boss-account": "p1"})
        self.assertEqual(gitx.worktree_attrs(self.src), {})
        # 値は元の clone の .git/worktrees/<部署>/config.worktree に入り、共有の設定には入らない
        self.assertNotIn("company", git("-C", self.src, "config", "--local", "--list"))

    def test_extension_is_not_enabled_over_core_worktree_or_bare(self):
        git("-C", self.src, "config", "--local", "core.worktree", self.src)
        with self.assertRaises(gitx.GitError) as e:
            gitx.enable_worktree_config(self.src)
        self.assertIn("core.worktree", str(e.exception))

    def test_exclude_adds_the_line_once(self):
        path = pathlib.Path(self.src) / ".git" / "info" / "exclude"
        path.write_text("# mine", encoding="utf-8")
        self.assertEqual(provision.hide_claude_dir(self.place, gitx), ["added", "added"])   # worktree から打っても共有の exclude
        self.assertEqual(provision.hide_claude_dir(self.src, gitx), ["already", "already"])
        self.assertEqual(path.read_text(encoding="utf-8"), "# mine\n.claude/settings.local.json\n__pycache__/\n")

    def test_common_dir_and_root_of_a_linked_worktree_are_the_source(self):
        self.assertEqual(os.path.realpath(gitx.root_of(gitx.common_dir(self.place))), os.path.realpath(self.src))
        self.assertIsNone(gitx.common_dir(tempfile.mkdtemp()))
        self.assertEqual(gitx.root_of(os.path.join("x", "bare.git")), os.path.join("x", "bare.git"))

    def test_is_merged_reads_the_target(self):
        self.assertTrue(gitx.is_merged(self.place, "refs/remotes/origin/main"))
        git("-C", self.place, "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-q", "--allow-empty", "-m", "x")
        self.assertFalse(gitx.is_merged(self.place, "refs/remotes/origin/main"))


class HerdrPorts(unittest.TestCase):
    def test_workspaces_take_the_repo_root_or_none(self):
        run = fake_runner(json.dumps({"result": {"workspaces": [
            {"workspace_id": "w1", "label": "r", "worktree": {"repo_root": "/s/r", "checkout_path": "/s/r"}},
            {"workspace_id": "w3", "label": "d", "worktree": {"repo_root": "/s/r", "checkout_path": "/w/d", "is_linked_worktree": True}},
            {"workspace_id": "w2", "label": "notes", "tokens": {"kind": "都度"}}]}}))
        self.assertEqual(real_herdr.workspaces(runner=run), [
            {"workspace_id": "w1", "label": "r", "repo_root": os.path.normpath("/s/r"), "path": os.path.normpath("/s/r"),
             "linked": False, "tokens": {}},
            {"workspace_id": "w3", "label": "d", "repo_root": os.path.normpath("/s/r"), "path": os.path.normpath("/w/d"),
             "linked": True, "tokens": {}},
            {"workspace_id": "w2", "label": "notes", "repo_root": None, "path": None, "linked": False, "tokens": {"kind": "都度"}}])

    def test_move_workspace_sends_one_json_line_to_the_socket_and_reads_the_answer(self):
        # herdr 0.9.3 の CLI に作業場を並べ替える命令が無いので、ソケットの API に 1 行の JSON で頼む
        sent = []

        class Sock:
            def __init__(self, answer):
                self.answer = answer

            def sendall(self, data):
                sent.append(json.loads(data.decode("utf-8")))

            def recv(self, n):
                out, self.answer = self.answer, b""
                return out

            def close(self):
                pass
        env = {"HERDR_SOCKET_PATH": "/s/herdr.sock"}
        ok = lambda path: Sock(b'{"id":"works-dispatch","result":{"type":"workspace_list"}}\n')   # noqa: E731
        real_herdr.move_workspace("w3", 1, request=lambda m, p: real_herdr._request(m, p, env=env, connect=ok))
        self.assertEqual((sent[0]["method"], sent[0]["params"]), ("workspace.move", {"workspace_id": "w3", "insert_index": 1}))
        bad = lambda path: Sock(b'{"id":"works-dispatch","error":{"code":"workspace_not_found","message":"x"}}\n')   # noqa: E731
        with self.assertRaises(real_herdr.HerdrError) as got:
            real_herdr._request("workspace.move", {}, env=env, connect=bad)
        self.assertEqual(got.exception.detail, "workspace_not_found")
        run = fake_runner("client:\n  version: 0.9.3\nserver:\n  socket: /c/herdr.sock\n")
        self.assertEqual(real_herdr._socket_path({}, run), "/c/herdr.sock")   # herdr の外からは herdr status で引く

    def test_rename_workspace_passes_the_label_as_one_argument(self):
        run = fake_runner(json.dumps({"result": {"type": "workspace_info"}}))
        real_herdr.rename_workspace("wX", "初見 読み", runner=run)
        self.assertEqual(run.calls, [["herdr", "workspace", "rename", "wX", "初見 読み"]])

    def test_metadata_sets_and_clears_in_one_call(self):
        run = fake_runner("")
        real_herdr.report_pane_metadata("p", "company", "調べ役", None, {"role": "調べ役"}, ["boss"], runner=run)
        self.assertEqual(run.calls, [["herdr", "pane", "report-metadata", "p", "--source", "company", "--display-agent", "調べ役",
                                      "--clear-title", "--token", "role=調べ役", "--clear-token", "boss"]])

    def test_workspace_metadata_sets_and_clears_in_one_call(self):
        run = fake_runner("")
        real_herdr.report_workspace_metadata("wX", "company", {"kind": "常設・毎回空"}, ["old"], runner=run)
        self.assertEqual(run.calls, [["herdr", "workspace", "report-metadata", "wX", "--source", "company",
                                      "--token", "kind=常設・毎回空", "--clear-token", "old"]])

    def test_read_returns_the_screen_text(self):
        self.assertEqual(real_herdr.read("p", 3, runner=fake_runner("a\nb\n")), "a\nb\n")
        with self.assertRaises(real_herdr.HerdrError):
            real_herdr.read("p", 3, runner=fake_runner("", rc=1))


def write(path, text):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(path).write_text(text, encoding="utf-8")
    return str(path)


class Info(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="company-")
        self.settings = tempfile.mkdtemp(prefix="company-settings-")

    def test_none_without_a_file(self):
        got = tree.read_info(self.root, self.settings)
        self.assertEqual((got["source"], got["skills"], got["problems"]), (None, [], []))

    def test_settings_file_is_read_when_the_repo_has_none(self):
        local = write(tree.settings_info_path(self.settings, self.root), 'name = "ノート"\n[[skills]]\nid = "r"\nname = "調べもの"\n')
        self.assertEqual(os.path.basename(local), urllib.parse.quote(os.path.realpath(self.root), safe="") + ".toml")
        got = tree.read_info(self.root, self.settings)
        self.assertEqual((got["source"], got["name"]), ("settings", "ノート"))
        self.assertEqual(got["skills"], [{"id": "r", "name": "調べもの", "description": None, "role": None, "model": None, "effort": None, "start": None,
                                          "standing": True}])

    def test_repo_file_wins_and_unknown_fields_are_skipped(self):
        write(tree.settings_info_path(self.settings, self.root), 'name = "手元"\n')
        write(os.path.join(self.root, ".claude", "company.toml"),
              'name = "会社"\ndescription = "説明"\nversion = "1"\n'
              '[[skills]]\nid = "r"\nname = "調べもの"\ndescription = "結論と原典の一句"\nrole = "調べ役"\ntags = ["x"]\n')
        got = tree.read_info(self.root, self.settings)
        self.assertEqual((got["source"], got["name"], got["description"]), ("repo", "会社", "説明"))
        self.assertEqual(got["skills"][0]["role"], "調べ役")

    def test_duty_model_and_effort_are_read_and_bad_ones_are_dropped_alone(self):
        # 部署ごとのモデルと effort は受け持ちに書く。形の違う欄はその欄だけ外し、受け持ち（部署の説明）は残す
        write(os.path.join(self.root, ".claude", "company.toml"),
              '[[skills]]\nname = "割り振り"\nrole = "担当"\nmodel = "sonnet"\neffort = "low"\n'
              '[[skills]]\nname = "点検"\nrole = "担当"\nmodel = "inherit"\neffort = "hihg"\n')
        got = tree.read_info(self.root, self.settings)
        self.assertEqual([(s["name"], s["model"], s["effort"]) for s in got["skills"]], [("割り振り", "sonnet", "low"), ("点検", None, None)])
        self.assertEqual(len(got["problems"]), 2)
        self.assertIn("inherit は作っていない", got["problems"][0])
        self.assertIn("effort は low・medium・high・xhigh・max・ultracode・inherit のどれか。外して、役の effort で起こす", got["problems"][1])

    def test_broken_file_is_a_problem_and_does_not_fall_back(self):
        write(os.path.join(self.root, ".claude", "company.toml"), "name = \n")
        write(tree.settings_info_path(self.settings, self.root), 'name = "手元"\n')
        got = tree.read_info(self.root, self.settings)
        self.assertEqual(got["source"], "repo")
        self.assertIsNone(got["name"])
        self.assertIn("TOML として読めない", got["problems"][0])

    def test_wrong_shapes_are_named(self):
        write(os.path.join(self.root, ".claude", "company.toml"), 'name = 3\nskills = [{ id = "x" }]\n')
        got = tree.read_info(self.root, None)
        self.assertEqual(len(got["problems"]), 2)


def publish(src, text):
    """origin の main に .claude/company.toml を commit して push し（元の clone の作業ツリーは動かさない）、origin/HEAD を main に向ける。"""
    side = tempfile.mkdtemp(prefix="company-pub-") + "/w"
    git("-C", src, "fetch", "-q", "origin", "main")
    git("-C", src, "worktree", "add", "-q", "--detach", side, "origin/main")
    write(os.path.join(side, ".claude", "company.toml"), text)
    git("-C", side, "add", ".claude/company.toml")
    git("-C", side, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "company")
    git("-C", side, "push", "-q", "origin", "HEAD:refs/heads/main")
    git("-C", src, "worktree", "remove", "--force", side)
    git("-C", src, "fetch", "-q", "origin", "main")
    git("-C", src, "remote", "set-head", "origin", "main")


class Source(unittest.TestCase):
    """会社の形を読む場所（read_info）: origin の既定の枝に commit された物を、元の clone の作業ツリーより先に読む。"""

    def setUp(self):
        self.src, self.root = make_world()
        self.settings = tempfile.mkdtemp(prefix="company-settings-")
        # 元の clone はほかの会話が古い枝で使っている（会社の形を持たないか、古い物を持つ）
        git("-C", self.src, "checkout", "-q", "-b", "old")

    def test_default_branch_wins_over_a_clone_without_the_shape(self):
        publish(self.src, 'name = "本流"\n')
        write(tree.settings_info_path(self.settings, self.src), 'name = "手元"\n')
        got = tree.read_info(self.src, self.settings)
        self.assertEqual((got["source"], got["name"], got["path"]), ("origin", "本流", "origin/main:.claude/company.toml"))
        self.assertEqual(got["text"], 'name = "本流"')

    def test_default_branch_wins_over_an_old_shape_in_the_clone(self):
        publish(self.src, 'name = "新しい"\n')
        write(os.path.join(self.src, ".claude", "company.toml"), 'name = "古い"\n')
        self.assertEqual(tree.read_info(self.src, self.settings)["name"], "新しい")

    def test_a_department_reads_the_same_shape_as_the_head_office(self):
        publish(self.src, 'name = "本流"\n')
        place = os.path.join(self.root, "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", place, "origin/main")
        write(os.path.join(place, ".claude", "company.toml"), 'name = "部署が書き換えた"\n')
        root = gitx.root_of(gitx.common_dir(place))
        self.assertEqual(tree.read_info(root, self.settings)["name"], "本流")

    def test_without_origin_head_the_clone_is_read(self):
        git("-C", self.src, "remote", "set-head", "origin", "--delete")
        write(os.path.join(self.src, ".claude", "company.toml"), 'name = "手元の clone"\n')
        got = tree.read_info(self.src, self.settings)
        self.assertEqual((got["source"], got["name"]), ("repo", "手元の clone"))
        # 既定の枝を決められない訳と直し方を、止めずに知らせる（会社の形が無くても）
        self.assertEqual(len(got["notes"]), 1)
        self.assertIn(f"git -C {self.src} remote set-head origin --auto", got["notes"][0])
        os.remove(os.path.join(self.src, ".claude", "company.toml"))
        self.assertEqual(len(tree.read_info(self.src, self.settings)["notes"]), 1)

    def test_with_origin_head_or_without_origin_there_is_no_note(self):
        git("-C", self.src, "remote", "set-head", "origin", "main")
        self.assertEqual(tree.read_info(self.src, self.settings)["notes"], [])
        self.assertIsNone(tree.head_note(tempfile.mkdtemp(prefix="company-plain-")))   # git でない・origin が無い

    def test_default_branch_without_the_shape_falls_back_to_the_clone(self):
        git("-C", self.src, "remote", "set-head", "origin", "main")
        write(os.path.join(self.src, ".claude", "company.toml"), 'name = "手元の clone"\n')
        self.assertEqual(tree.read_info(self.src, self.settings)["source"], "repo")

    def test_broken_shape_on_the_default_branch_is_a_problem_and_does_not_fall_back(self):
        publish(self.src, "name = \n")
        write(os.path.join(self.src, ".claude", "company.toml"), 'name = "手元"\n')
        got = tree.read_info(self.src, self.settings)
        self.assertEqual((got["source"], got["name"]), ("origin", None))
        self.assertIn("origin/main:.claude/company.toml: TOML として読めない", got["problems"][0])

    def test_land_rules_are_read_from_the_default_branch(self):
        publish(self.src, '[land]\nmode = "pr"\n')
        info = tree.read_info(self.src, self.settings)
        self.assertEqual(land.read_rules(info["path"], None, info["text"])["mode"], "pr")


class Build(unittest.TestCase):
    PLACES = {"/s/r": [{"path": "/s/r", "branch": "main", "linked": False, "workspace": "w1"},
                       {"path": "/wt/r/a", "branch": "dept/a", "linked": True, "workspace": "w2"},
                       {"path": "/wt/r/b", "branch": "dept/b", "linked": True, "workspace": None},
                       {"path": "/wt/r/gone", "branch": "x", "linked": True, "prunable": True}]}
    ATTRS = {"/wt/r/a": {"role": "調べ役", "residency": "resident", "account": "p2", "name": "調べ", "session": "s-a",
                         "boss": "窓口"}}

    def build(self, panes=(), sessions=None):
        return tree.build(["/s/r"], self.PLACES, list(panes), lambda p: self.ATTRS.get(p, {}),
                          lambda root: {"source": None, "name": None, "skills": [], "problems": []}, sessions)

    def test_departments_carry_attrs_session_state_and_window(self):
        sessions = {"p2": [{"id": "a1", "sessionId": "s-a", "name": "調べ", "cwd": "/elsewhere", "kind": "background",
                            "state": "blocked", "startedAt": 2}],
                    "p1": [{"sessionId": "s-h", "name": "窓口", "cwd": "/s/r/sub", "kind": "interactive", "status": "busy"},
                           {"id": "b1", "sessionId": "s-b", "name": "古い", "cwd": "/wt/r/b", "kind": "background",
                            "state": "done", "startedAt": 1}]}
        panes = [{"pane_id": "w2:p1", "workspace_id": "w2", "cwd": "/wt/r/a", "agent": "claude", "label": "調べ p2"}]
        [c] = self.build(panes, sessions)
        self.assertEqual(c["name"], "r")
        head, a, b = c["departments"]
        self.assertTrue(head["head_office"])
        self.assertEqual((head["state"], head["account"], head["panes"]), ("working", "p1", []))
        # 部署の会話は属性の会話の id で結ぶ（会話の作業フォルダが部署の外でも）
        self.assertEqual((a["state"], a["role"], a["account"], a["boss"], a["session"]["id"]), ("blocked", "調べ役", "p2", "窓口", "a1"))
        self.assertEqual([p["pane_id"] for p in a["panes"]], ["w2:p1"])
        # 属性の無い部署は、会話の作業フォルダの場所で結び、アカウントと名前は会話から
        self.assertEqual((b["state"], b["account"], b["name"], b["role"]), ("done", "p1", "古い", None))
        self.assertEqual(len(c["departments"]), 3)   # prunable は並べない
        out = {"schema": 1, "companies": [c], "notes": []}
        self.assertEqual(schemacheck.check(out, schemacheck.schema("tree")), [])

    def test_lines_show_the_tree(self):
        sessions = {"p2": [{"id": "a1", "sessionId": "s-a", "cwd": "/wt/r/a", "kind": "background", "state": "working"}]}
        text = "\n".join(tree.lines(self.build((), sessions)))
        self.assertIn("r  /s/r  （会社の情報なし）", text)
        self.assertIn("  本社 main  会話なし", text)
        self.assertIn("  ├ dept/a  作業中  会話 調べ  役 調べ役（常設・持ち越し）  アカウント p2  頼み元 窓口  窓 なし", text)
        self.assertIn("  └ dept/b  会話なし  役 -  アカウント -  頼み元 -  窓 なし", text)

    def test_contacts_show_who_to_ask_and_the_desk(self):
        # 受ける仕事ごとの宛て方（常設の受け持ちは部署の名前、まだ立っていなければ役と --task、都度の役は役と --task）と窓口を出す。
        # 頼み元（company.boss）は納品の返し先なので、宛て方にも窓口にも使わない
        from nodes import role
        shape = role.load("t", '[[roles]]\nname = "担当"\nresident = true\n[[roles]]\nname = "作業"\n'
                               '[[roles]]\nname = "配布"\nmachine = true\n')
        company = {"name": "c", "skills": [{"name": "調べ", "description": None, "role": "担当"}, {"name": "点検", "description": None, "role": "担当"},
                                           {"name": "直し", "description": None, "role": "作業"}, {"name": "配る", "description": None, "role": "配布"},
                                           {"name": "無役", "description": None, "role": None}],
                   "departments": [{"head_office": True, "attrs": {"name": "段取り", "role": "段取り", "boss": "社長室"}},
                                   {"head_office": False, "attrs": {"name": "調べ", "role": "担当", "boss": "段取り"}}]}
        tree.contacts(company, shape)
        self.assertEqual([s["ask"] for s in company["skills"]],
                         ["--ask c/調べ", "--ask c/担当 --task 点検 --branch <枝>", "--ask c/作業 --task <部署の名前> --branch <枝>",
                          None, None])
        self.assertEqual(company["desk"], {"name": "段取り", "role": "段取り", "ask": "--ask c/段取り", "model": None, "effort": None})
        company.update({"root": "/s/c", "info_source": "origin", "description": None, "problems": []})
        text = "\n".join(tree.lines([company | {"departments": []}]))
        self.assertIn("  受ける仕事: 調べ → 担当  宛て方 --ask c/調べ", text)
        self.assertIn("  窓口: 段取り（受ける仕事に当たらない件・部署をまたぐ件）  model 既定  effort 既定  宛て方 --ask c/段取り", text)
        # ほかの会社が兼ねる窓口（会社の形の desk）は、その会社の形を読まないので model・effort を出さない
        other = company | {"departments": [], "desk": None, "desk_of": "n/段取り"}
        tree.contacts(other, shape)
        self.assertIn("  窓口: n/段取り（受ける仕事に当たらない件・部署をまたぐ件）  宛て方 --ask n/段取り", "\n".join(tree.lines([other])))
        # 本社を名付けていなければ、名付けていないと出す
        unnamed = company | {"departments": [], "desk": None}
        self.assertIn("  窓口: 名付けていない", "\n".join(tree.lines([unnamed])))

    def test_desk_shows_the_model_and_effort_it_starts_with(self):
        # 窓口の会話が起きるときに効く値: 役の欄（--move が旗で渡す）が [roles.settings] の model・effortLevel より先。
        # effort の inherit は窓口に引き継ぐ会話が無いので旗を付けず、設定の値が効く。役の前の名前（former_names）でも引く
        from nodes import role
        def desk(text):
            company = {"name": "c", "skills": [], "departments": [{"head_office": True, "attrs": {"name": "段取り", "role": "窓口"}}]}
            return tree.contacts(company, role.load("t", text))["desk"]
        head = '[[roles]]\nname = "段取り"\nformer_names = ["窓口"]\n'
        got = desk(head + '[roles.settings]\nmodel = "opus"\neffortLevel = "low"\n')
        self.assertEqual((got["model"], got["effort"]), ("opus", "low"))
        got = desk(head + 'model = "sonnet"\neffort = "inherit"\n[roles.settings]\nmodel = "opus"\neffortLevel = "low"\n')
        self.assertEqual((got["model"], got["effort"]), ("sonnet", "low"))
        got = desk(head + 'effort = "high"\n[roles.settings]\neffortLevel = "low"\n')
        self.assertEqual((got["model"], got["effort"]), (None, "high"))
        company = {"name": "c", "root": "/s/c", "info_source": "origin", "description": None, "problems": [], "skills": [],
                   "departments": [], "desk": got}
        self.assertIn("  窓口: 段取り（受ける仕事に当たらない件・部署をまたぐ件）  model 既定  effort high  宛て方 --ask c/段取り",
                      "\n".join(tree.lines([company])))

    def test_roots_come_from_herdr_then_from_conversations(self):
        common = {"/notes": "/notes", "/wt/n/x": "/notes", "/r2/sub": "/r2"}
        got = tree.roots([{"workspace_id": "w1", "repo_root": "/s/r"}, {"workspace_id": "w9", "repo_root": None},
                          {"workspace_id": "w8", "repo_root": None}],
                         [{"workspace_id": "w9", "cwd": "/notes"}], common.get, ["/wt/n/x", "/r2/sub", "/nowhere"])
        self.assertEqual(got, ["/s/r", "/notes", "/r2"])


class Sync(unittest.TestCase):
    def company(self, *depts):
        return [{"name": "r", "departments": list(depts)}]

    def dept(self, attrs, panes, branch="dept/a"):
        return {"branch": branch, "path": "/wt", "attrs": attrs, "panes": panes}

    def test_plan_names_and_tags_the_conversation_pane_only_where_attrs_exist(self):
        attrs = {"role": "調べ役", "account": "p2", "name": "調べ", "boss": "窓口"}
        ops, notes = sync.plan(self.company(
            self.dept(attrs, [{"pane_id": "a", "agent": None}, {"pane_id": "b", "agent": "claude", "label": "x"}]),
            self.dept({}, [{"pane_id": "c", "agent": "claude"}])), many_accounts=True)
        self.assertEqual(ops, [{"pane": "b", "label": "調べ p2", "display_agent": "調べ役", "title": "調べ",
                                "tokens": {"role": "調べ役", "account": "p2", "boss": "窓口"}, "clear_tokens": []}])
        self.assertEqual(notes, [])

    def test_same_label_is_not_renamed_and_missing_values_are_cleared(self):
        op = sync.op("p", {"name": "調べ", "account": "p2"}, many_accounts=False, current_label="調べ")
        self.assertEqual((op["label"], op["display_agent"], op["clear_tokens"]), (None, None, ["role", "boss"]))

    def test_single_quiet_pane_is_used_and_none_is_noted(self):
        ops, notes = sync.plan(self.company(self.dept({"name": "a"}, [{"pane_id": "p", "agent": None}]),
                                            self.dept({"name": "b"}, [], branch="dept/b")), many_accounts=False)
        self.assertEqual([o["pane"] for o in ops], ["p"])
        self.assertIn("dept/b: 付ける先のペインが無い（作業場が開いていない）", notes[0])

    def test_workspace_takes_the_name_of_the_place_including_the_head_office(self):
        # herdr のサイドバーの 1 行目は作業場の名前。部署は属性の name、本社（元の clone）は属性が有れば会社の名前で付ける
        # 作業場には席の見え方を印 kind で付ける（会話の行でなく作業場の行に出す）
        office = {**self.dept({"name": "窓口", "account": "a1", "role": "窓口", "residency": "resident"}, []), "head_office": True,
                  "workspace": "wX"}
        same = {**self.dept({"name": "調べ", "role": "作業", "residency": "per-task"}, [], branch="dept/b"), "workspace": "wB"}
        kinded = {**self.dept({"name": "割り振り", "role": "担当", "residency": "resident", "fresh": "true"}, [], branch="dept/k"),
                  "workspace": "wK"}
        shared = [{**self.dept({"name": n, "role": "作業"}, [], branch=f"dept/{n}"), "workspace": "wS"} for n in ("c", "d")]
        bare = {**self.dept({}, [], branch="dept/e"), "workspace": "wE"}
        got = sync.workspace_ops(self.company(office, same, kinded, *shared, bare), [
            {"workspace_id": "wX", "label": "mynotes"}, {"workspace_id": "wB", "label": "調べ", "tokens": {"kind": "都度"}},
            {"workspace_id": "wK", "label": "割り振り", "tokens": {"kind": "常設・持ち越し"}},
            {"workspace_id": "wS", "label": "x"}, {"workspace_id": "wE", "label": "y"}])
        # 本社の作業場は herdr の木の親なので会社の名前。名前と印が今と同じなら付け直さず、属性を持つ場所が 2 つ居る作業場と属性の
        # 無い場所の作業場は触らない
        self.assertEqual(got, [{"workspace": "wX", "label": "r", "kind": "常設・持ち越し"},
                               {"workspace": "wK", "label": None, "kind": "常設・毎回空"}])

    def test_apply_keeps_going_after_a_failure(self):
        class H:
            HerdrError = real_herdr.HerdrError
            calls = []

            def rename_pane(self, pane, label):
                if pane == "bad":
                    raise real_herdr.HerdrError(["herdr"], "pane_not_found")
                self.calls.append(("rename", pane, label))

            def report_pane_metadata(self, pane, source, display_agent, title, tokens, clear_tokens=()):
                self.calls.append(("meta", pane, source))

        ops = [sync.op("bad", {"name": "x"}, False), sync.op("ok", {"name": "y"}, False)]
        got = sync.apply(ops, H())
        self.assertEqual([g["status"] for g in got], ["failed", "done"])
        self.assertEqual(H.calls, [("rename", "ok", "y"), ("meta", "ok", "company")])


class FlowOrder(unittest.TestCase):
    """部署の作業場を仕事の流れの順に並べる（sync.flow_order。持ち主 2026-10-17 の案 A）。"""

    WS = [("d", "/r/notes", "/r/notes", False), ("x", None, None, False), ("a", "/r/notes", "/w/a", True),
          ("b", "/r/notes", "/w/b", True), ("p", "/r/notes", "/w/p", True), ("c", "/r/plugins", "/w/c", True),
          ("t1", "/r/notes", "/w/t1", True), ("h", "/r/notes", "/w/h", True), ("t2", "/r/notes", "/w/t2", True)]
    ATTRS = {"/w/a": {"role": "担当", "name": "調べもの", "residency": "resident", "fresh": "true"},
             "/w/b": {"role": "担当", "name": "ノートの手入れ", "residency": "resident", "fresh": "true"},
             "/w/p": {"role": "相談", "name": "社長室", "residency": "resident"},
             "/w/c": {"role": "担当", "name": "割り振り", "residency": "resident", "fresh": "true"},
             "/w/t1": {"role": "作業", "name": "作業：1", "residency": "per-task"},
             "/w/t2": {"role": "作業", "name": "作業：2", "residency": "per-task"}}

    @staticmethod
    def play(ids, moves):
        """herdr の workspace.move と同じに当てる（動かす前の並びの位置の前に入る）。"""
        now = list(ids)
        for o in moves:
            j, i = now.index(o["workspace"]), o["index"]
            now.insert(i if i < j else i - 1, now.pop(j))
        return now

    def order(self, ws):
        listed = [{"workspace_id": w, "label": w, "repo_root": root, "path": path, "linked": linked} for w, root, path, linked in ws]
        skills = {"/r/notes": [{"name": "ノートの手入れ"}, {"name": "調べもの"}], "/r/plugins": []}
        return sync.flow_order(listed, lambda path: self.ATTRS.get(path, {}), lambda root: skills[root])

    def test_departments_line_up_carry_over_then_standing_in_the_shape_order_then_per_task_then_the_rest(self):
        moves = self.order(self.WS)
        got = self.play([w[0] for w in self.WS], moves)
        # 本社 d とまとまりの無い x、ほかの会社の c の位置はそのまま。my_notes の部署は 社長室・受け持ちの書き順の担当・作業（今の順）・手で開いた場所
        self.assertEqual(got, ["d", "x", "p", "b", "a", "c", "t1", "t2", "h"])
        self.assertEqual(self.order([next(w for w in self.WS if w[0] == i) for i in got]), [])   # 並んだら動かさない

    def test_sync_orders_only_the_companies_it_read(self):
        # --sync の会社の並び（tree.build）の部署の属性で並べ、読んでいない会社の作業場は動かさない
        companies = [{"root": "/r/notes", "skills": [{"name": "ノートの手入れ"}, {"name": "調べもの"}],
                      "departments": [{"path": path, "attrs": attrs} for path, attrs in self.ATTRS.items() if path != "/w/c"]}]
        listed = [{"workspace_id": w, "label": w, "repo_root": root, "path": path, "linked": linked} for w, root, path, linked in self.WS]
        listed.insert(6, {"workspace_id": "c2", "label": "c2", "repo_root": "/r/plugins", "path": "/w/c2", "linked": True})
        moves = sync.flow_order(*dispatch._flow_inputs(companies, listed))
        self.assertEqual(self.play([w["workspace_id"] for w in listed], moves), ["d", "x", "p", "b", "a", "c", "c2", "t1", "t2", "h"])

    def test_apply_order_stops_after_the_first_failure(self):
        class H:
            HerdrError = real_herdr.HerdrError
            seen = []

            def move_workspace(self, ws, index):
                self.seen.append(ws)
                raise real_herdr.HerdrError(["herdr", "api", "workspace.move"], "workspace_not_found")
        got = sync.apply_order([{"workspace": "p", "index": 2}, {"workspace": "b", "index": 3}], H())
        self.assertEqual([r["status"] for r in got], ["failed", "skipped"])
        self.assertEqual(H.seen, ["p"])


class CompanyHerdr(FakeHerdr):
    """FakeHerdr に、作業場の並び（元の clone の作業場と、git の印の無いノートの作業場）を足す。"""

    def __init__(self, source):
        super().__init__()
        self.source = source

    def workspaces(self):
        seen = {p["workspace_id"] for p in self._panes}
        return [{"workspace_id": w, "label": w, "repo_root": self.source if w in self._wt.values() else None} for w in sorted(seen)]


class Entry(unittest.TestCase):
    """入口の --tree・--json・--sync。dispatch の設定のアカウントの会話の一覧も偽物で渡す。"""

    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        self.place = str(pathlib.Path(self.root) / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place, "origin/main")
        provision.mark(self.place, self.src, {"role": "調べ役", "account": "a1", "name": "調べ", "session": "s-a"}, gitx)
        self.ports = FakePorts([])
        self.ports.herdr = CompanyHerdr(self.src)
        self.ports.herdr.open_at(self.src)
        self.pane = self.ports.herdr.open_at(self.place, agent="claude")["pane_id"]
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"id": "a", "sessionId": "s-a", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working"}]

    def main(self, *argv):
        return run_main(["--config", self.cfg, *argv], self.ports)

    def test_sync_copies_the_roles_fresh_to_every_department(self):
        # 会社の形の役の fresh を変えたら、--sync 1 回で今いる部署の属性 company.fresh と herdr の表示に行き渡る（--ask・
        # --reorg --role を待たない。ノートの手入れの納品で見つかった）
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
        shape = pathlib.Path(self.src, ".claude", "company.toml")
        shape.parent.mkdir(exist_ok=True)
        shape.write_text('[[roles]]\nname = "調べ役"\nresident = true\nfresh = true\n', encoding="utf-8")
        rc, out = self.main("--sync", "--dry-run")
        self.assertIn("company.fresh - → true（役 調べ役 の fresh を写す）", out)
        self.assertIn("印 常設・毎回空", out)   # 席の見え方は作業場の印に出す
        self.assertIn("表示名 調べ役  ", out)   # ペインの表示名は役だけ
        self.assertNotIn("fresh", gitx.worktree_attrs(self.place), "--dry-run が書いた")
        rc, out = self.main("--sync")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place)["fresh"], "true")
        shape.write_text('[[roles]]\nname = "調べ役"\nresident = true\n', encoding="utf-8")   # 持ち越しに戻す
        rc, out = self.main("--sync")
        self.assertIn("company.fresh true → （消す）", out)
        self.assertNotIn("fresh", gitx.worktree_attrs(self.place))

    def test_sync_renames_a_former_role_name_to_the_current_one(self):
        # 会社の形で役の名前を替え、前の名前を former_names に書けば、--sync が前の名前を持つ場所の属性を今の名前に書き直す
        shape = pathlib.Path(self.src, ".claude", "company.toml")
        shape.parent.mkdir(exist_ok=True)
        shape.write_text('[[roles]]\nname = "調べもの"\nformer_names = ["調べ役"]\n', encoding="utf-8")
        rc, out = self.main("--sync")
        self.assertEqual(rc, 0, out)
        self.assertIn("company.role 調べ役 → 調べもの（役の前の名前を今の名前に）", out)
        self.assertEqual(gitx.worktree_attrs(self.place)["role"], "調べもの")
        self.assertIn("表示名 調べもの  ", out)

    def test_tree_prints_the_company_and_its_departments(self):
        rc, out = self.main("--tree")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"{os.path.basename(self.src)}  {self.src}  （会社の情報なし）", out)
        self.assertIn("  本社 main  会話なし", out)
        self.assertIn("  └ dept/a  作業中  会話 調べ  役 調べ役（都度）  アカウント a1  頼み元 -  窓 あり", out)

    def test_tree_json_matches_the_schema(self):
        rc, out = self.main("--tree", "--json")
        self.assertEqual(rc, 0, out)
        got = json.loads(out)
        self.assertEqual(schemacheck.check(got, schemacheck.schema("tree")), [])
        self.assertEqual(got["companies"][0]["departments"][1]["attrs"]["session"], "s-a")

    def test_tree_works_without_a_config(self):
        rc, out = run_main(["--config", str(pathlib.Path(self.root).parent / "none.toml"), "--tree"], self.ports)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("設定を読めない", out)
        self.assertIn("dept/a", out)

    def test_sync_tags_the_department_pane_and_dry_run_writes_nothing(self):
        rc, out = self.main("--sync", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ports.herdr.writes, [])
        self.assertIn(f"ペイン {self.pane}: 名前 調べ  表示名 調べ役  題名 調べ  札 role=調べ役、account=a1", out)
        ws = next(p["workspace_id"] for p in self.ports.herdr.panes() if p["pane_id"] == self.pane)
        self.assertIn(f"作業場 {ws}: 名前 調べ  印 都度", out)
        rc, out = self.main("--sync")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ports.herdr.writes, [
            ("rename_workspace", ws, "調べ"),
            ("report_workspace_metadata", ws, {"kind": "都度"}, []),
            ("rename_pane", self.pane, "調べ"),
            ("report_pane_metadata", self.pane, "調べ役", "調べ", {"role": "調べ役", "account": "a1"}, ["boss"])])

    def test_flags_go_together(self):
        for argv in (["--tree", "--sync"], ["--json"], ["--sync", "--json"], ["--tree", "--dry-run"]):
            with self.subTest(argv=argv):
                rc, out = self.main(*argv)
                self.assertEqual(rc, 2, out)

    def test_herdr_that_cannot_be_read_stops_with_one_line(self):
        def broken():
            raise real_herdr.HerdrError(["herdr", "pane", "list"], "no socket")
        self.ports.herdr.panes = broken
        rc, out = self.main("--tree")
        self.assertEqual(rc, 1)
        self.assertIn("止めた: herdr を読めない", out)

    def test_sync_keeps_the_waiting_mark_of_a_department(self):
        # 番の終わりのフックが表示名に添えた「裏の処理待ち」を、付け直し（手の --sync も、会社の形が替わったときのフックも）が消さない
        real = tempfile.tempdir
        tempfile.tempdir = tempfile.mkdtemp()
        try:
            orders.wait_mark(tempfile.tempdir, "s-a").parent.mkdir(parents=True)
            orders.wait_mark(tempfile.tempdir, "s-a").write_text("1", encoding="utf-8")
            rc, out = self.main("--sync", "--dry-run")
        finally:
            tempfile.tempdir = real
        self.assertIn(f"表示名 調べ役・{sync.WAITING}", out)

    def hook(self, sync_=None):
        env = {"WORKS_DISPATCH_CONFIG": self.cfg}
        return shape_hook.run({"cwd": self.place}, env,
                              sync_ or (lambda config_path, root: dispatch.sync_companies(self.cfg, self.ports, only=root)))

    def test_shape_hook_syncs_the_company_once_per_change_of_the_shape(self):
        # 会社の形を替えたら、どの会話の番の終わりでも、その会社の部署の属性と herdr の表示が揃う（手で --sync を打たない。
        # my_notes で役の名前を替えたとき、表示の替え残しを持ち主が herdr の上で見つけた）
        shape = pathlib.Path(self.src, ".claude", "company.toml")
        shape.parent.mkdir(exist_ok=True)
        shape.write_text('[[roles]]\nname = "調べ役"\n', encoding="utf-8")
        self.assertEqual(self.hook(), (True, []))   # 控えが無ければ 1 度揃える
        self.assertTrue(pathlib.Path(shape_hook.mark_path(os.path.join(self.src, ".git"))).is_file())
        self.ports.herdr.writes.clear()
        self.assertEqual(self.hook(), (False, []))   # 替わっていなければ何もしない
        self.assertEqual(self.ports.herdr.writes, [])
        shape.write_text('[[roles]]\nname = "調べもの"\nformer_names = ["調べ役"]\nresident = true\nfresh = true\n', encoding="utf-8")
        self.assertEqual(self.hook(), (True, []))
        self.assertEqual(gitx.worktree_attrs(self.place)["role"], "調べもの")
        self.assertEqual(gitx.worktree_attrs(self.place)["fresh"], "true")
        self.assertIn(("report_pane_metadata", self.pane, "調べもの", "調べ", {"role": "調べもの", "account": "a1"}, ["boss"]),
                      self.ports.herdr.writes)

    def test_shape_hook_retries_until_everything_is_tagged(self):
        shape = pathlib.Path(self.src, ".claude", "company.toml")
        shape.parent.mkdir(exist_ok=True)
        shape.write_text('[[roles]]\nname = "調べ役"\n', encoding="utf-8")
        called = []

        def failing(config_path, root):
            called.append(root)
            return ["ペイン w1-1: …  failed（pane_not_found）"], 1
        self.assertEqual(self.hook(failing), (True, ["ペイン w1-1: …  failed（pane_not_found）"]))
        self.assertEqual(self.hook(failing)[0], True)   # 控えを書かないので、次の番の終わりにもう一度揃える
        self.assertEqual(len(called), 2)

    def test_shape_hook_does_nothing_without_a_shape_or_outside_git(self):
        def never(config_path, root):
            raise AssertionError("揃え直した")
        self.assertEqual(self.hook(never), (False, []))   # 会社の形の無いリポジトリ
        self.assertEqual(shape_hook.run({"cwd": tempfile.mkdtemp()}, {}, never), (False, []))

    def test_sync_of_one_company_leaves_the_others(self):
        lines, rc = dispatch.sync_companies(self.cfg, self.ports, only=tempfile.mkdtemp())
        self.assertEqual((rc, lines), (0, ["付け直す部署は無い（属性を持つ部署が無い）"]))
        self.assertEqual(self.ports.herdr.writes, [])

    def test_plugin_declares_the_shape_hook_in_the_background_at_stop(self):
        hooks = json.loads((pathlib.Path(DISPATCH).parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        [h] = [h for grp in hooks["Stop"] for h in grp["hooks"] if "shape_hook.py" in h["command"]]
        self.assertIn('"${CLAUDE_PLUGIN_ROOT}/dispatch/shape_hook.py"', h["command"])
        self.assertTrue(h.get("async"))   # 番の終わりを待たせない


class Departments(unittest.TestCase):
    """部署の片付け: 会話が終わり、手元の作業が無く、枝が本流に入った部署だけを、claude rm と一緒に消す。"""

    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        self.ports = FakePorts([])
        self.place = self.dept("dept/a", "s-a")
        self.state = {"s-a": "done"}
        self.removed, self.rm_env = [], []
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"id": sid[-1], "sessionId": sid, "state": st} for sid, st in self.state.items()] if include_done else []

    def dept(self, branch, session):
        path = self.ports.herdr.create_worktree(self.src, branch, "origin/main", branch)["path"]
        self.ports.herdr.writes.clear()
        provision.mark(path, self.src, {"name": branch, "session": session}, gitx)
        return path

    def clean(self, *extra):
        import dispatch
        real = dispatch.claudex.remove_session
        dispatch.claudex.remove_session = lambda cdir, sid, **kw: (self.removed.append((cdir, sid)) or self.rm_env.append(kw.get("base_env"))
                                                                   or (True, "removed"))
        try:
            return run_main(["--config", self.cfg, "--clean", *extra], self.ports)
        finally:
            dispatch.claudex.remove_session = real

    def test_finished_merged_department_is_listed_then_removed_with_its_session(self):
        rc, out = self.clean()
        self.assertEqual(rc, 0, out)
        self.assertIn("部署 dept/a dept/a  done  消せる", out)
        self.assertNotIn("no_pr", out)   # 部署は PR の片付けの並びに出さない
        self.assertIn("消すには --clean --apply を付けて打ち直す", out)
        rc, out = self.clean("--apply")
        self.assertEqual(rc, 0, out)
        self.assertIn("部署 dept/a 消した", out)
        self.assertEqual(self.removed, [(f"{pathlib.Path(self.cfg).parent}/c1", "a")])
        self.assertFalse(os.path.exists(self.place))

    def test_rm_looks_in_the_login_shell_folder_not_the_calling_session(self):
        # 2026-10-17: p2 の会話から打った --clean --apply が、config_dir の無い main の会話を p2 の置き場で探して断られた
        self.ports.env = {**os.environ, "CLAUDE_CONFIG_DIR": "/h/.claude-p2"}
        self.ports._account_env = None
        rc, out = self.clean("--apply")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.rm_env), 1)
        self.assertNotIn("CLAUDE_CONFIG_DIR", self.rm_env[0])   # ペインのログインのシェル（ここでは値無し）に倣う

    def test_running_unpushed_and_unmerged_departments_are_kept(self):
        self.state["s-a"] = "working"
        git("-C", self.dept("dept/b", "s-b"), "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-q", "--allow-empty", "-m", "x")
        self.state["s-b"] = "done"
        rc, out = self.clean("--apply")
        self.assertIn("部署 dept/a dept/a  working  残す（会話がまだ動いている）", out)
        self.assertIn("部署 dept/b dept/b  done  残す（手元にしか無い commit か stash が有る）", out)
        self.assertEqual(self.removed, [])

    def test_resident_department_is_never_removed(self):
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
        rc, out = self.clean("--apply")
        self.assertIn("部署 dept/a dept/a  done  残す（常設の部署は畳まない）", out)
        self.assertEqual(self.removed, [])
        self.assertTrue(os.path.exists(self.place))

    def test_clean_works_without_a_config_file_and_does_not_ask_github(self):
        # 設定のファイルが無くても、--repo のパスの代表の clone の部署を片付ける。[[repos]] に無いので PR の作業場（GitHub）は見ない
        self.ports.pr_for_branch = lambda repo, branch: self.fail("設定の無い --clean が PR を GitHub に問うた")
        none = str(pathlib.Path(self.cfg).parent / "none.toml")
        rc, out = run_main(["--config", none, "--clean", "--repo", self.src], self.ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("部署 dept/a dept/a  done  消せる", out)
        self.assertIn("消すには --clean --apply を付けて打ち直す", out)

    def test_resident_department_branches_it_landed_are_removed_after_it_moves_on(self):
        # 常設の部署は作業場を残し、頼みごとに枝を移る。--land が書いた「入れた枝 → commit」のうち、もう開いていない枝を消す
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
        old_sha = git("-C", self.place, "rev-parse", "HEAD")
        git("-C", self.place, "switch", "-q", "-c", "dept/next")             # 次の頼みの枝に移った
        git("-C", self.src, "branch", "-q", "dept/moved", old_sha)
        git("-C", self.src, "branch", "-q", "-f", "dept/moved", git("-C", self.src, "-c", "user.name=o", "-c", "user.email=o@o",
                                                                   "commit-tree", f"{old_sha}^{{tree}}", "-p", old_sha,
                                                                   "-m", "after"))
        provision.mark(self.place, self.src, {"landed-branches": json.dumps(
            {"dept/a": old_sha, "dept/next": old_sha, "dept/moved": old_sha})}, gitx)
        rc, out = self.clean()
        self.assertIn("入れ終えた枝 dept/a: 消せる", out)
        self.assertIn("dept/a", git("-C", self.src, "branch", "--list", "dept/a"), "見立てだけで消した")
        rc, out = self.clean("--apply")
        self.assertIn("入れ終えた枝 dept/a: 消した", out)
        self.assertIn("入れ終えた枝 dept/moved: 入れた後に commit が有るので消さず", out)
        self.assertEqual(git("-C", self.src, "branch", "--list", "dept/a"), "")
        self.assertNotEqual(git("-C", self.src, "branch", "--list", "dept/moved"), "")
        # 開いている枝（今の頼みの枝）だけが記録に残る
        self.assertEqual(json.loads(gitx.worktree_attrs(self.place)["landed-branches"]), {"dept/next": old_sha})
        self.assertTrue(os.path.exists(self.place))

    def test_retire_stops_when_rm_refuses(self):
        class C:
            @staticmethod
            def remove_session(cdir, sid, base_env=None):
                return False, "kept a — its worktree has unpushed commits"

            @staticmethod
            def job_tmp(cdir, sid, env=None):
                return "/nowhere"
        got = clean.retire({"path": self.place, "branch": "dept/a", "session": "a", "config_dir": "/c", "pr_head": None},
                           self.src, "x", self.ports.herdr, gitx, C)
        self.assertFalse(got["removed"])
        self.assertIn("claude rm が断った", got["detail"])
        self.assertTrue(os.path.exists(self.place))

    def test_job_tmp_is_copied_into_the_common_git_before_rm(self):
        # claude rm は会話の一時の置き場も消す。部署がそこに残した物（2026-10-17 の測りの道具）を、消す前に写して残す
        tmp = pathlib.Path(tempfile.mkdtemp()) / "jobs" / "a" / "tmp"
        (tmp / "tools").mkdir(parents=True)
        (tmp / "tools" / "measure.py").write_text("x\n", encoding="utf-8")
        real = dispatch.claudex.job_tmp
        dispatch.claudex.job_tmp = lambda cdir, sid, env=None: str(tmp)
        self.addCleanup(setattr, dispatch.claudex, "job_tmp", real)
        rc, out = self.clean()
        self.assertIn("消せる（会話の一時の置き場の 1 件は、共通の .git の company/kept-tmp/ に写してから消す）", out)
        rc, out = self.clean("--apply")
        self.assertEqual(rc, 0, out)
        kept = pathlib.Path(gitx.common_dir(self.src), "company", "kept-tmp", "a")
        self.assertIn(f"会話の一時の置き場の 1 件を {kept} に写した", out)
        self.assertEqual((kept / "tools" / "measure.py").read_text(encoding="utf-8"), "x\n")
        self.assertEqual(len(self.removed), 1)

    def test_job_tmp_copy_finishes_when_a_former_copy_stopped_halfway(self):
        # 前の回の写しが読み取り専用のファイル（git の objects）とリンクを残しても、打ち直せば写し終える（2026-10-17 の
        # --retire 点検は Errno 13 と 17 で止まり続けた）
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "repo" / "objects").mkdir(parents=True)
        obj = tmp / "repo" / "objects" / "ab"
        obj.write_text("blob\n", encoding="utf-8")
        obj.chmod(0o444)
        (tmp / "link").symlink_to("repo")
        os.mkfifo(tmp / "pipe")
        clean.keep_tmp(str(tmp), self.src, "half", gitx)
        (tmp / "new").write_text("later\n", encoding="utf-8")
        n, dest = clean.keep_tmp(str(tmp), self.src, "half", gitx)
        self.assertEqual(n, 4)
        self.assertEqual(pathlib.Path(dest, "repo", "objects", "ab").read_text(encoding="utf-8"), "blob\n")
        self.assertEqual(os.readlink(os.path.join(dest, "link")), "repo")
        self.assertEqual(pathlib.Path(dest, "new").read_text(encoding="utf-8"), "later\n")
        self.assertTrue(stat.S_ISFIFO(os.lstat(os.path.join(dest, "pipe")).st_mode))
        # 写し元で種類が替わった物（リンク→フォルダ・フォルダ→ファイル）も、写し先の前の物を消して写し直す
        (tmp / "link").unlink()
        (tmp / "link").mkdir()
        (tmp / "link" / "in").write_text("in\n", encoding="utf-8")
        shutil.rmtree(tmp / "repo")
        (tmp / "repo").write_text("now a file\n", encoding="utf-8")
        clean.keep_tmp(str(tmp), self.src, "half", gitx)
        self.assertFalse(os.path.islink(os.path.join(dest, "link")))
        self.assertEqual(pathlib.Path(dest, "link", "in").read_text(encoding="utf-8"), "in\n")
        self.assertEqual(pathlib.Path(dest, "repo").read_text(encoding="utf-8"), "now a file\n")

    def test_job_tmp_copy_stops_on_a_folder_it_cannot_read(self):
        # 読めないフォルダを飛ばして「写した」とすると、claude rm が中身ごと消す
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "locked").mkdir()
        (tmp / "locked" / "note").write_text("x", encoding="utf-8")
        (tmp / "locked").chmod(0o300)
        self.addCleanup((tmp / "locked").chmod, 0o700)
        with self.assertRaises(OSError):
            clean.keep_tmp(str(tmp), self.src, "locked", gitx)

    def test_retire_keeps_everything_when_job_tmp_cannot_be_copied(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "note").write_text("x", encoding="utf-8")
        asked = []

        class C:
            @staticmethod
            def remove_session(cdir, sid, base_env=None):
                asked.append(sid)
                return True, ""

            @staticmethod
            def job_tmp(cdir, sid, env=None):
                return str(tmp)

        class G:
            @staticmethod
            def common_dir(cwd):
                return None
        got = clean.retire({"path": self.place, "branch": "dept/a", "session": "a", "config_dir": "/c", "pr_head": None},
                           self.src, "x", self.ports.herdr, G, C)
        self.assertFalse(got["removed"])
        self.assertIn("会話の一時の置き場を写せないので消さない", got["detail"])
        self.assertEqual(asked, [])
        self.assertTrue(os.path.exists(self.place))

    def test_department_whose_session_is_gone_is_still_judged_by_git(self):
        rows = clean.departments(self.ports.herdr.worktrees(self.src), gitx.worktree_attrs, lambda attrs: None, gitx.is_clean,
                                 gitx.unpushed, lambda p: True, gitx.head_sha, source=self.src)
        self.assertEqual([(r["state"], r["removable"], r["session"]) for r in rows], [("gone", True, None)])


if __name__ == "__main__":
    unittest.main()
