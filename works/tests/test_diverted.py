"""局所レビューの fork のレンズ（/code-review）の所見が届かなかった空の行を「見ていない」と書く口（.shared/core/diverted.py）と、
局所レビューの受け付け（blk-material の take）がそれを盤面と報告に渡す振る舞いの検査（FAST: 一時の置き場のファイルだけ。git・盤面の
再生を使わない）。

実測（2026-10-08、利用者の run f57a5374 ほか 6 つの works の家）: 組み込みの skill code-review は fork（下請けの会話）で走り、
返答の道具 StructuredOutput を継いだ fork は所見をそこに書いて終わった。Skill の結果は『Skill execution completed』だけになり、
局所レビューの役は /code-review の行を items 空で返していた（run f57a5374 では 10 件の所見が消えた）。今は旗 text-reply で
fork に返答の道具が無いが、空の行は「所見なし」でなく「見ていない」と書く。0.2.46 の拾い戻し（record-output.py のフックと
diverted.recover）は 2026-10-09 の掃除で外した。
"""
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
sys.path.insert(0, str(ROOT / "blk-material" / "lib"))

import diverted  # noqa: E402
import material  # noqa: E402

LENSES = [{"skill": "/code-review", "required": True}, {"skill": "pr-review-toolkit:code-reviewer", "required": True},
          {"skill": "/simplify", "required": True},
          {"skill": "/security-review", "required": False, "applies_cond": "security_surface_touched"}]
ITEM2 = {"where": "deploy/values.yaml:174", "text": "常設環境に漏れる"}
LOST = "起こしたが fork 実行の結果が本文なし（Skill execution completed のみ）で、所見を受け取れなかった。"


def reply(code_review_items=(), failed=LOST, status="clean"):
    rows = [{"skill": e["skill"], "items": [], "invoked": True, "failed": "起こしたが所見なし（差分を見た）"} for e in LENSES]
    rows[0].update(items=list(code_review_items), failed=failed)
    material_ = {"status": status, "checked": "差分を見た"} if status == "clean" else \
        {"status": status, "count": 3, "detail": "code-reviewer が 3 件"}
    return {"material": material_, "simplify_carried": False, "findings": rows}


class UnseenCase(unittest.TestCase):
    def test_empty_fork_lens_row_is_marked_unseen_not_nothing_found(self):
        for failed in (LOST, "起こしたが所見なし（スキルは結果本文を返さずに完了）"):
            with self.subTest(failed):
                out, notes = diverted.mark_unseen(reply(failed=failed), LENSES)
                row = out["findings"][0]
                self.assertTrue(row["failed"].startswith(diverted.UNSEEN_TAG), row)
                self.assertIn(failed, row["failed"], "役の文は残す")
                self.assertEqual(notes, {"unseen": ["/code-review"]})
                self.assertIn(diverted.UNSEEN_TAG, out["material"]["checked"])
        given = reply()
        diverted.mark_unseen(given, LENSES)
        self.assertEqual(given, reply(), "受けた返答は書き換えない（写しを返す）")

    def test_rows_with_items_and_inline_lenses_are_left_alone(self):
        out, notes = diverted.mark_unseen(reply(code_review_items=[ITEM2], failed=""), LENSES)
        self.assertEqual(out["findings"][0]["items"], [ITEM2], "役が受け取った本文を差し替えない")
        self.assertEqual(out["findings"][2]["failed"], "起こしたが所見なし（差分を見た）", "/simplify は fork しない（0 件は 0 件）")
        self.assertEqual(notes, {"unseen": []})

    def test_not_invoked_row_is_not_marked(self):
        r = reply()
        r["findings"][0]["invoked"] = False
        out, notes = diverted.mark_unseen(r, LENSES)
        self.assertEqual(out["findings"][0]["failed"], LOST)
        self.assertEqual(notes, {"unseen": []})


class MatBoard:
    """material.take が触る欄だけを持つ盤面の偽物（節 p1.local_review が待っている周 1。起こした印は利用者の run の時刻）"""

    def __init__(self, root: pathlib.Path):
        self.dir = root / "board"
        self.round = 1
        self.graph = {"nodes": {"p1.local_review": {"skills": LENSES}}}
        self.rd = {"instances": {"p1.local_review": {"node": "p1.local_review", "status": "pending", "attempts": 1,
                                                     "skills": LENSES, "launched_at": "2026-10-08T08:42:34+09:00"}}}
        self.loop_state = {}
        self.taken = []

    def work(self, name):
        p = self.dir / f"r{self.round}" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def output_of_round(self, nid, rnd):
        return None

    def done(self, nid, reply_):
        self.taken.append((nid, reply_))


class TakeCase(unittest.TestCase):
    """局所レビューの受け付けが、/code-review の所見が届かなかった空の行を見ていないと書いて盤面に渡し、控えと報告に残す"""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        self.home, self.repo = self.tmp / "adapter-home", self.tmp / "repo"
        self.b = MatBoard(self.tmp)
        self.b.work(material.SNAPSHOT).write_text(json.dumps({k: None for k in material.TREE_KEYS}), encoding="utf-8")
        cfg = self.tmp / "cfg"
        (cfg / "plugins").mkdir(parents=True)
        (cfg / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {"pr-review-toolkit@x": []}}),
                                                                encoding="utf-8")
        for name, value in (("_locked", lambda *a, **k: mock.MagicMock()), ("_open", lambda *a, **k: self.b),
                            ("_stopped", lambda b: None), ("_refuse_halted", lambda b: None),
                            ("_waiting", lambda b, nid: None), ("tree_moved", lambda *a, **k: [])):
            p = mock.patch.object(material, name, value)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(cfg)})
        env.start()
        self.addCleanup(env.stop)

    def take(self, r):
        return material.take(self.b.dir, "local-review", r, self.repo, "optional")

    def test_unrecovered_loss_is_taken_but_said_unseen(self):
        out = self.take(reply())
        self.assertTrue(out["ok"], "起こし直しても同じ形で落ちる（実測）ので拒まない")
        (_, got), = self.b.taken
        self.assertTrue(got["findings"][0]["failed"].startswith(diverted.UNSEEN_TAG))
        doc = json.loads(self.b.work(diverted.LENS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(doc["unseen"], ["/code-review"])
        lines = diverted.report_lines(self.b.dir)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("/code-review", lines[0])
        self.assertIn("見ていない", lines[0])

    def test_prompt_note_tells_role_not_to_rerun_and_not_to_spell_flags(self):
        for word in ("Skill execution completed", "起こし直すな", "--fix", "invoked: true"):
            self.assertIn(word, material.LENS_FORK_NOTE)

    def test_prompt_note_tells_role_to_copy_text_findings(self):
        """包みの旗 text-reply の起動（adapter.py の頭の 21）では fork に返答の道具が無く、/code-review は所見を本文で返す。
        指示はそれを行の items に写させ、空の行（『Skill execution completed』だけ）は今までどおり見ていない形で返させる"""
        note = material.LENS_FORK_NOTE
        self.assertIn("本文で返", note)
        self.assertIn("`items` に写せ", note)


if __name__ == "__main__":
    unittest.main()
