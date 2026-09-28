"""役の節を回す共通の口（.shared/core/rolekit.py。P1 計画 Task 13）の検査（FAST: git・盤面の再生・子のプロセスを使わない）。

- render_prompt: 頭の行（前の拒否の理由のファイルのパス）→ head → engine と同じ描き方の本文 → schema の断り、の順で
  今の周の作業ファイル prompt-<節>.md に書く。理由の文そのものは本文に無い（R44）
- accept_role: 拒否ごとに reject-take_<節>-<連番>.txt と控えの行、GIVE_UP_AFTER 回目で done・give_up（R50）
- script_main・main_accept の終了コード（予定の状態は 0 の 1 行、配線の誤りは 2 で標準出力は空）
- 写しが残っていない: works の中で script_main・parse_reply・render_prompt を定義し Renderer を呼ぶのは rolekit だけ（AST）
実物の盤面での描画（本線の p2.fix_plan・p2.plan_review）は test_blk_plan（HEAVY）、rejudge.render の本文の一致は test_rejudge が見る。
盤面はここでは小さな偽物（rolekit が触る欄だけ）で、entry の口は mock で差し替える。
"""
import ast
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

from board import BoardGap  # noqa: E402
from engine.util import AnswerReject, Reject, dump  # noqa: E402
import rolekit  # noqa: E402
import hermetic  # noqa: E402

REASON = '読めない: $ARTIFACTS_DIR と $plan-accept.output.reason と "引用" と\n改行'
TPL = "単位: {{record.units | pick key}}\n方針: {{?inputs.policy_md}}\n"


class FakeBoard:
    """rolekit が触る欄だけを持つ盤面の偽物（節 p9.role を 1 つ持つ graph・今の周 2）"""

    def __init__(self, root: pathlib.Path, *, pending=True, reads=("record.units", "inputs.policy_md")):
        self.dir = root / "board"
        self.dir.mkdir(parents=True)
        gl = root / "gl" / "graphs"
        gl.mkdir(parents=True)
        (root / "gl" / "prompts").mkdir()
        (root / "gl" / "prompts" / "p9.role.md").write_text(TPL, encoding="utf-8")
        self.state = {"graph": str(gl / "g.json")}
        self.round = 2
        self.schema = {"type": "object", "required": ["plan"], "properties": {"plan": {"type": "array"}}}
        self.nodes = {"p9.role": {"prompt_file": "../prompts/p9.role.md", "reads": list(reads), "schema": self.schema}}
        self.rd = {"instances": {"p9.role": {"status": "pending", "attempts": 1}} if pending else {}}

    def ctx(self):
        return {"record": {"units": [{"key": "u1", "label": "block"}]}, "inputs": {"policy_md": ""}}

    def ref(self, path):
        raise KeyError(path)

    def work(self, name):
        p = self.dir / f"r{self.round}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def call(fn, *args, env=None, **kw):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}, clear=True), contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        code = fn(*args, **kw)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()


class RenderCase(Base):
    def test_render_prompt_order_and_place(self):
        b = FakeBoard(self.tmp)
        p = rolekit.render_prompt(b, "p9.role", prompts_dir=self.tmp / "gl", head="お前は役。")
        self.assertEqual(p, b.work("prompt-p9.role.md"))
        text = p.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("お前は役。\n\n単位: "), text)
        self.assertIn('"key": "u1"', text)
        self.assertTrue(text.endswith(rolekit.SCHEMA_NOTE + dump(b.schema)))

    def test_compose_joins_parts_under_the_reject_line(self):
        """compose: 空でない部分を空行 1 つで繋ぐ（部分の字は変えない）。reject_file が在れば 1 行目で名指す（R44）。
        render_prompt もこれで組む（前と同じバイト）"""
        self.assertEqual(rolekit.compose(["頭", "", "本文\n"]), "頭\n\n本文\n")
        got = rolekit.compose(["頭"], reject_file="/b/reject-x-1.txt")
        self.assertEqual(got, rolekit.REJECT_LINE.format(path="/b/reject-x-1.txt") + "\n\n頭")
        self.assertEqual(rolekit.compose(["頭"], reject_file=""), "頭")
        b = FakeBoard(self.tmp)
        body, _ = rolekit.render_body(b, "p9.role", prompts_dir=self.tmp / "gl")
        p = rolekit.render_prompt(b, "p9.role", prompts_dir=self.tmp / "gl", head="お前は役。\n")
        self.assertEqual(p.read_text(encoding="utf-8"), "お前は役。\n\n" + body)

    def test_render_body_reads_only(self):
        b = FakeBoard(self.tmp, reads=("record.units",))   # 穴 inputs.policy_md が reads に無い
        with self.assertRaises(BoardGap):
            rolekit.render_body(b, "p9.role", prompts_dir=self.tmp / "gl")
        text, snap = rolekit.render_body(b, "p9.role", prompts_dir=self.tmp / "gl", reads_only=False)
        self.assertIn("方針: ", text)
        self.assertEqual(snap, [])

    def test_render_body_template_and_ctx_hook(self):
        """template は graph の指示書の代わりの本文（ブロックが持つ写し）、ctx_hook は描く前の ctx を足す（engine が足す欄）"""
        b = FakeBoard(self.tmp, reads=("record.units", "inputs.policy_md", "validation"))
        text, _ = rolekit.render_body(b, "p9.role", template="検証: {{validation}}\n",
                                      ctx_hook=lambda ctx: ctx.update(validation="exit 0"))
        self.assertTrue(text.startswith("検証: exit 0\n"), text)
        self.assertTrue(text.endswith(rolekit.SCHEMA_NOTE + dump(b.schema)))

    def test_render_needs_pending_instance(self):
        with self.assertRaises(BoardGap):
            rolekit.render_prompt(FakeBoard(self.tmp, pending=False), "p9.role", prompts_dir=self.tmp / "gl")

    def test_prev_reject_named_by_path(self):
        """この周に拒否が 1 回在る → 1 行目が理由のファイルのパスを名指し、理由の文そのものは本文に無い"""
        b = FakeBoard(self.tmp)
        rf = b.dir / "reject-take_p9_role-1.txt"
        rf.write_text(REASON, encoding="utf-8")
        b.work(rolekit.REJECTS_NAME).write_text(json.dumps([{"node": "p9.role", "reason_file": str(rf)}]), encoding="utf-8")
        text = rolekit.render_prompt(b, "p9.role", prompts_dir=self.tmp / "gl", head="頭").read_text(encoding="utf-8")
        first = text.splitlines()[0]
        self.assertIn(str(rf), first)
        self.assertEqual(first, rolekit.REJECT_LINE.format(path=rf))
        self.assertNotIn("$plan-accept", text)
        self.assertNotIn("引用", text)
        self.assertEqual(text.split("\n\n")[1], "頭")
        # 別の周の拒否は名指さない
        b.round = 3
        self.assertFalse(rolekit.render_prompt(b, "p9.role", prompts_dir=self.tmp / "gl").read_text(
            encoding="utf-8").startswith("前の回"))


class AcceptCase(Base):
    def setUp(self):
        super().setUp()
        self.b = FakeBoard(self.tmp)
        p = mock.patch.object(rolekit.entry, "open_board", return_value=self.b)
        p.start()
        self.addCleanup(p.stop)

    def test_gives_up_on_third_reject(self):
        take = mock.patch.object(rolekit.entry, "take", return_value={"ok": False, "reason": REASON})
        with take:
            got = [rolekit.accept_role(self.b.dir, "p9.role", "{}", self.tmp, snapshot_name="s.json")
                   for _ in range(rolekit.GIVE_UP_AFTER)]
        self.assertEqual([(g["ok"], g["done"], g["give_up"]) for g in got],
                         [(False, False, False)] * (rolekit.GIVE_UP_AFTER - 1) + [(False, True, True)])
        self.assertEqual([pathlib.Path(g["reason_file"]).name for g in got],
                         [f"reject-take_p9_role-{i}.txt" for i in range(1, rolekit.GIVE_UP_AFTER + 1)])
        self.assertEqual(pathlib.Path(got[0]["reason_file"]).read_text(encoding="utf-8"), REASON)
        self.assertEqual(rolekit.last_reject_file(self.b, "p9.role"), got[-1]["reason_file"])

    def test_give_up_arms_share_text_and_stop_once(self):
        # 盤面の節の諦め（gave_up）と盤面の節でない諦め（given_up_reason・stop_line）は同じ文を出し、止まった盤面を止め直さない
        stops = []

        def stop(reason, by):
            stops.append((reason, by))
            self.b.state["stop"] = {"reason": reason, "by": by}
        self.b.stop = stop
        with mock.patch.object(rolekit.entry, "take", return_value={"ok": False, "reason": REASON}):
            for _ in range(rolekit.GIVE_UP_AFTER):
                rolekit.accept_role(self.b.dir, "p9.role", "{}", self.tmp)
        why = rolekit.gave_up(self.b.dir, "p9.role", by="works:t")
        for _ in range(rolekit.GIVE_UP_AFTER):
            rolekit.with_done(self.tmp, "p9.role", {"ok": False, "reason": REASON})
        self.assertEqual(rolekit.given_up_reason(self.tmp, "p9.role"), why)
        self.assertIn(" ".join(REASON.split()), why)
        (self.tmp / "state.json").write_text("{}", encoding="utf-8")   # ラインの盤面の印（on_line）
        rolekit.stop_line(self.tmp, "別の理由", by="works:t2")
        self.assertEqual(rolekit.gave_up(self.b.dir, "p9.role", by="works:t3"), why)
        self.assertEqual(stops, [(why, "works:t")])

    def test_unreadable_reply_is_a_reject(self):
        with mock.patch.object(rolekit.entry, "take", side_effect=AssertionError("take を呼んだ")):
            got = rolekit.accept_role(self.b.dir, "p9.role", "{JSON でない", self.tmp)
        self.assertEqual((got["ok"], got["done"]), (False, False))
        self.assertIn("JSON", pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"))

    def test_ok_is_done(self):
        with mock.patch.object(rolekit.entry, "take", return_value={"ok": True, "reason": "", "out_file": "out/r2/x.json"}):
            got = rolekit.accept_role(self.b.dir, "p9.role", "{}", self.tmp)
        self.assertEqual((got["ok"], got["done"], got["give_up"], got["reason_file"]), (True, True, False, ""))
        self.assertEqual(got["out_file"], "out/r2/x.json")
        self.assertFalse(self.b.work(rolekit.REJECTS_NAME).exists())

    def test_main_accept_exit_codes(self):
        env = {"ARTIFACTS_DIR": str(self.tmp), "INPUTS_REPLY": "{}"}
        with mock.patch.object(rolekit.entry, "take", return_value={"ok": False, "reason": "x"}):
            code, out, _ = call(rolekit.main_accept, "p9.role", env=env)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["ok"], False)
        for exc in (BoardGap("gap"), Reject("止めた run")):
            with mock.patch.object(rolekit.entry, "take", side_effect=exc):
                code, out, err = call(rolekit.main_accept, "p9.role", env=env)
            self.assertEqual((code, out), (2, ""), err)
        code, out, err = call(rolekit.main_accept, "p9.role", env={"ARTIFACTS_DIR": str(self.tmp)})
        self.assertEqual((code, out), (2, ""))
        self.assertIn("INPUTS_REPLY", err)

    def test_main_accept_after_adds_fields(self):
        """after(盤面, 返り) は出す前に当たる（blk-judge が judgment_file・open_units を足す）。after の誤りも 2"""
        env = {"ARTIFACTS_DIR": str(self.tmp), "INPUTS_REPLY": "{}"}
        seen = []

        def after(board, out):
            seen.append(board)
            return {**out, "extra": 1}
        with mock.patch.object(rolekit.entry, "take", return_value={"ok": False, "reason": "x"}):
            code, out, _ = call(rolekit.main_accept, "p9.role", env=env, after=after)
        self.assertEqual((code, json.loads(out)["extra"]), (0, 1))
        self.assertEqual(seen, [(self.tmp / "board").resolve()])

        def broken(board, out):
            raise BoardGap("出口を組めない")
        with mock.patch.object(rolekit.entry, "take", return_value={"ok": False, "reason": "x"}):
            code, out, err = call(rolekit.main_accept, "p9.role", env=env, after=broken)
        self.assertEqual((code, out), (2, ""), err)


class ScriptMainCase(Base):
    def test_script_main_exit_codes(self):
        env = {"ARTIFACTS_DIR": str(self.tmp), "INPUTS_X": "1"}
        seen = []

        def ok(board, repo, got):
            seen.append((board, got))
            return {"ok": False, "reason": "予定の拒否"}
        code, out, _ = call(rolekit.script_main, ok, ("INPUTS_X",), env=env)
        self.assertEqual((code, json.loads(out)["ok"]), (0, False))
        self.assertEqual(seen, [(self.tmp / "board", {"INPUTS_X": "1"})])
        code, out, err = call(rolekit.script_main, ok, ("INPUTS_X",), env=env, not_ok_is_wiring=True)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("予定の拒否", err)
        for exc in (BoardGap("gap"), Reject("止めた"), AnswerReject("中身"), ValueError("思わぬ")):
            def boom(*_):
                raise exc
            code, out, err = call(rolekit.script_main, boom, env=env)
            self.assertEqual((code, out), (2, ""), exc)
            self.assertEqual(len(err.splitlines()), 1)
        code, out, err = call(rolekit.script_main, ok, ("INPUTS_X",), env={"ARTIFACTS_DIR": ""})
        self.assertEqual((code, out), (2, ""))
        self.assertIn("ARTIFACTS_DIR", err)
        self.assertIn("INPUTS_X", err)

    def test_script_main_fence(self):
        """fence なら盤面は script_io.board_dir の値（resolve 済み）で、解決したパスが $ を含めば 2"""
        seen = []

        def ok(board, repo, got):
            seen.append(board)
            return {"go": True}
        link = self.tmp / "link"
        link.symlink_to(self.tmp)
        code, out, _ = call(rolekit.script_main, ok, env={"ARTIFACTS_DIR": str(link)}, fence=True)
        self.assertEqual((code, json.loads(out)), (0, {"go": True}))
        self.assertEqual(seen, [self.tmp / "board"])
        dollar = self.tmp / "a$b"
        dollar.mkdir()
        code, out, err = call(rolekit.script_main, ok, env={"ARTIFACTS_DIR": str(dollar)}, fence=True)
        self.assertEqual((code, out, len(seen)), (2, "", 1))
        self.assertIn("$", err)

    def test_script_main_take_writes_reason_file(self):
        """take を与えると、done を持つ返り（受け付け）は script_io.emit_result を通る: 拒否は理由の本文を
        reject-<take>_<節>-<連番>.txt に書き reason_file を足す。done を持たない返りはそのまま"""
        env = {"ARTIFACTS_DIR": str(self.tmp)}
        code, out, _ = call(rolekit.script_main, lambda *_: {"ok": False, "done": False, "reason": REASON, "node": "n1"},
                            env=env, take="eyes")
        got = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(pathlib.Path(got["reason_file"]).name, "reject-eyes_n1-1.txt")
        self.assertEqual(pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"), REASON)
        code, out, _ = call(rolekit.script_main, lambda *_: {"ok": True, "done": True, "node": "n1"}, env=env, take="eyes")
        self.assertEqual(json.loads(out)["reason_file"], "")
        code, out, _ = call(rolekit.script_main, lambda *_: {"go": True}, env=env, take="eyes")
        self.assertEqual(json.loads(out), {"go": True})

    def test_parse_reply(self):
        self.assertEqual(rolekit.parse_reply('{"a": 1}'), ({"a": 1}, ""))
        self.assertIsNone(rolekit.parse_reply("{x")[0])
        self.assertIn("オブジェクトでない", rolekit.parse_reply("[1]")[1])


class NoCopiesCase(unittest.TestCase):
    OWN = ("script_main", "parse_reply", "render_prompt")

    def test_no_copies_left(self):
        """works の pack（dev・tests・docs・写しの graphloops を除く）で、script_main・parse_reply・render_prompt を def し、
        Renderer を呼ぶ関数を持つのは rolekit だけ"""
        skip = {ROOT / d for d in ("dev", "tests", "docs")} | {CORE / "graphloops", CORE / "scripts"}
        hits = []
        for p in sorted(ROOT.rglob("*.py")):
            if any(s == p or s in p.parents for s in skip) or p == CORE / "rolekit.py":
                continue
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if isinstance(n, ast.FunctionDef) and n.name in self.OWN:
                    hits.append(f"{p.relative_to(ROOT)}: def {n.name}")
                if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "Renderer":
                    hits.append(f"{p.relative_to(ROOT)}: Renderer(")
        self.assertEqual(hits, [])


LENSES = [{"skill": "/code-review", "required": True}, {"skill": "pr-review-toolkit:code-reviewer", "required": True},
          {"skill": "/simplify", "required": True},
          {"skill": "/security-review", "required": False, "applies_cond": "security_surface_touched"}]


class MatBoard:
    """material.take が触る欄だけを持つ盤面の偽物（節 p1.local_review が待っている周 1）。done は写しの規則の受け付け
    （awaiting_human も必須のレンズの未起動も通す 0.21.0 の local_review_covers_lenses）の代わりに、受けた返答を積むだけ"""

    def __init__(self, root: pathlib.Path):
        self.dir = root / "board"
        self.round = 1
        self.graph = {"nodes": {"p1.local_review": {"skills": LENSES}}}
        self.rd = {"instances": {"p1.local_review": {"node": "p1.local_review", "status": "pending", "attempts": 1,
                                                     "skills": LENSES}}}
        self.loop_state = {}
        self.taken = []

    def work(self, name):
        p = self.dir / f"r{self.round}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def output_of_round(self, nid, rnd):
        return None

    def done(self, nid, reply):
        self.taken.append((nid, reply))


class LocalReviewRetryCase(Base):
    """p1.local_review の受け付け: 必須のレンズを起こさなかった返答と material が awaiting_human の返答は、上限
    （material.GIVE_UP_AFTER 回目）に届く前は拒み、同じ会話で起こし直させる（本流 0.23.0 の local_review_covers_lenses の
    engine の子の枝。Step Functions の Retry と同じ形）。拒みが上限に届いた時だけ人に渡す。隔離した設定にレンズの
    プラグインが無い（毎回落ちる環境の失敗）は出し直さずに名指しで人に渡す（人の関所の答え (6)）"""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(ROOT / "blk-material" / "lib"))
        self.addCleanup(sys.path.remove, str(ROOT / "blk-material" / "lib"))
        import material
        self.material = material
        self.b = MatBoard(self.tmp)
        self.b.work(material.SNAPSHOT).write_text(json.dumps({k: None for k in material.TREE_KEYS}), encoding="utf-8")
        for name, value in (("_locked", lambda *a, **k: contextlib.nullcontext()), ("_open", lambda *a, **k: self.b),
                            ("_stopped", lambda b: None), ("_refuse_halted", lambda b: None),
                            ("_waiting", lambda b, nid: None), ("tree_moved", lambda *a, **k: [])):
            p = mock.patch.object(material, name, value)
            p.start()
            self.addCleanup(p.stop)

    def config(self, plugins):
        cfg = self.tmp / "claude-config"
        (cfg / "plugins").mkdir(parents=True, exist_ok=True)
        (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {f"{p}@works-local": [{"scope": "user", "installPath": str(cfg / p), "version": "1"}]
                                       for p in plugins}}), encoding="utf-8")
        return str(cfg)

    @staticmethod
    def reply(skip=None, why="Agent の呼び出しが時間切れで落ちた", status="clean"):
        rows = [{"skill": e["skill"], "items": [], "failed": "起こしたが所見なし（差分を見た）", "invoked": True} for e in LENSES]
        for r in rows:
            if r["skill"] == skip:
                r.update(invoked=False, failed=why)
        material = {"status": status, "checked": "差分を見た"}
        if status == "awaiting_human":
            material["reason"] = why
        return {"material": material, "simplify_carried": False, "findings": rows}

    def take(self, reply, cfg):
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfg}):
            return self.material.take(self.b.dir, "local-review", reply, self.tmp / "repo", "optional")

    def test_required_lens_not_invoked_rejected_for_retry(self):
        out = self.take(self.reply(skip="pr-review-toolkit:code-reviewer"), self.config(["pr-review-toolkit", "coldwrite"]))
        self.assertFalse(out["ok"], out)
        self.assertFalse(out["done"], "上限の前は同じ会話で起こし直させる")
        self.assertFalse(out["give_up"])
        self.assertIn("pr-review-toolkit:code-reviewer", out["reason"])

    def test_awaiting_human_rejected_before_limit(self):
        out = self.take(self.reply(skip="/code-review", status="awaiting_human"), self.config(["pr-review-toolkit"]))
        self.assertFalse(out["ok"], out)
        self.assertFalse(out["done"])
        self.assertIn("awaiting_human", out["reason"])

    def test_gives_up_to_human_at_the_limit(self):
        cfg = self.config(["pr-review-toolkit"])
        outs = [self.take(self.reply(skip="/simplify"), cfg) for _ in range(self.material.GIVE_UP_AFTER)]
        self.assertEqual([o["give_up"] for o in outs], [False] * (self.material.GIVE_UP_AFTER - 1) + [True], outs)
        self.assertTrue(outs[-1]["done"])

    def test_missing_plugin_goes_to_human_without_retry(self):
        out = self.take(self.reply(skip="pr-review-toolkit:code-reviewer", why="pr-review-toolkit の agent が無い"),
                        self.config(["coldwrite"]))
        self.assertFalse(out["ok"], out)
        self.assertTrue(out["done"], "毎回落ちる環境の失敗は出し直さない")
        self.assertTrue(out["give_up"])
        self.assertIn("pr-review-toolkit", out["reason"])

    def carry_round(self, same: bool, claim: bool = True) -> dict:
        """周 2 の /simplify の持ち越し。周の頭の版（写しの loop_state.head_revs）を本物の git の版で置き、前の周と木が
        同じ（same）か 1 ファイル違うかを作って、持ち越しの返答（claim が偽なら simplify_carried の無い返答）を受け付けに通す"""
        repo = self.tmp / "repo"
        repo.mkdir()
        env = hermetic.child_env(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                                 GIT_COMMITTER_EMAIL="t@t")

        def git(*a):
            return subprocess.run(["git", "-C", str(repo), *a], env=env, check=True, capture_output=True,
                                  text=True).stdout.strip()
        git("init", "-q")
        (repo / "a.txt").write_text("1\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "r1")
        r1 = git("rev-parse", "HEAD")
        if not same:
            (repo / "a.txt").write_text("2\n", encoding="utf-8")
            git("add", "-A")
        git("commit", "-q", "--allow-empty", "-m", "r2")   # 版の commit は周ごとに別（木だけが同じになりうる）
        self.b.round = 2
        self.b.loop_state = {"head_revs": {"1": r1, "2": git("rev-parse", "HEAD")}}
        self.b.work(self.material.SNAPSHOT).write_text(json.dumps({k: None for k in self.material.TREE_KEYS}),
                                                       encoding="utf-8")
        reply = self.reply(skip="/simplify", why="持ち越し（前の周から変わっていない）")
        if claim:
            reply["simplify_carried"] = True
        with mock.patch.object(self.material._util, "GIT_CWD", str(repo)):   # 本物の _open が入れる対象（ここは偽の _open）
            return self.take(reply, self.config(["pr-review-toolkit"]))

    def test_simplify_carry_taken_when_round_head_unchanged(self):
        out = self.carry_round(same=True)
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(self.b.taken), 1)

    def test_simplify_carry_rejected_when_a_file_changed(self):
        out = self.carry_round(same=False)
        self.assertFalse(out["ok"], out)
        self.assertFalse(out["done"])
        self.assertIn("/simplify", out["reason"])
        self.assertIn("この周は当たらない", out["reason"])

    def test_simplify_reject_says_round_qualifies_when_carry_unclaimed(self):
        out = self.carry_round(same=True, claim=False)   # 当たる周なのに simplify_carried を書き落とした返答
        self.assertFalse(out["ok"], out)
        self.assertIn("この周は当たる", out["reason"])
        self.assertNotIn("この周は当たらない", out["reason"])


if __name__ == "__main__":
    unittest.main()
