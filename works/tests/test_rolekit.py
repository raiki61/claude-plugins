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

    def test_render_body_reads_only(self):
        b = FakeBoard(self.tmp, reads=("record.units",))   # 穴 inputs.policy_md が reads に無い
        with self.assertRaises(BoardGap):
            rolekit.render_body(b, "p9.role", prompts_dir=self.tmp / "gl")
        text, snap = rolekit.render_body(b, "p9.role", prompts_dir=self.tmp / "gl", reads_only=False)
        self.assertIn("方針: ", text)
        self.assertEqual(snap, [])

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


if __name__ == "__main__":
    unittest.main()
