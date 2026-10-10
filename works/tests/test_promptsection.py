"""役の指示書に機械が貼る節の見出しの宣言（.shared/core/promptsection.py。考え prompt-sections）の検査。

縛る事:
- Section は見出しの字そのものの str（f-string・.format・==・dict の鍵が素の字と同じ）。出どころ（source）と人向けの理由
  （human）を欄に持ち、複製（copy.deepcopy）と pickle の往復で欄が残る
- Receive は受け手の役の側の行（role・section・when）
- declared_sections(module) はモジュールの直下の Section の値だけを名と並べて返す
標準ライブラリだけ。mock なし（モジュールの代わりに types.SimpleNamespace を渡す）。
"""
import copy
import pathlib
import pickle
import sys
import types
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))


class SectionCase(unittest.TestCase):
    def ps(self):
        try:
            import promptsection as m   # 住処（無ければこの試験が断言の失敗で落ちる）
        except ImportError as e:
            self.fail(f"promptsection が読めない: {e}")
        for name in ("Section", "Receive", "declared_sections"):
            self.assertTrue(hasattr(m, name), f"promptsection.{name} が無い")
        return m

    def test_section_is_the_heading_with_its_declaration(self):
        """Section は見出しの字と同じ str として指示書の本文に入り、出どころ・理由の欄が複製と pickle の往復で残る。
        Receive は (role, section, when)。declared_sections はモジュールの Section の値だけを名と並べる"""
        m = self.ps()
        head = "## 前の回の受け付けが拒んだ理由"
        s = m.Section(head, source="board:worldmark.HEAD", human="")

        # 素の字と同じ値として使える
        self.assertIsInstance(s, str)
        self.assertEqual(s, head)
        self.assertEqual(f"{s}\n\n本文", f"{head}\n\n本文")
        self.assertEqual("{}\n本文".format(s), f"{head}\n本文")
        self.assertEqual({head: 1}[s], 1)
        self.assertEqual(hash(s), hash(head))
        hole = m.Section("## 項目 {n}", source="fn:planblk.items")
        self.assertEqual(hole.format(n=3), "## 項目 3")       # 穴は呼び手が .format で埋める

        # 欄。全部キーワードの引数で、既定は空
        self.assertEqual((s.source, s.human), ("board:worldmark.HEAD", ""))
        bare = m.Section("## x")
        self.assertEqual((bare.source, bare.human), ("", ""))
        human = m.Section("## 人が決めること", human="報告の見出しで、役の文脈ではない")
        self.assertEqual((human.source, human.human), ("", "報告の見出しで、役の文脈ではない"))
        with self.assertRaises(TypeError):
            m.Section("## x", "input:a")

        # 複製と往復で字も欄も残る
        for name, back in (("deepcopy", copy.deepcopy(s)), ("pickle", pickle.loads(pickle.dumps(s)))):
            with self.subTest(name):
                self.assertIsInstance(back, m.Section)
                self.assertEqual(back, head)
                self.assertEqual((back.source, back.human), (s.source, s.human))
        back = pickle.loads(pickle.dumps(human))
        self.assertEqual((back.source, back.human), (human.source, human.human))

        # 受け手の行
        row = m.Receive(role="plan", section=s, when="planblk.design_section")
        self.assertEqual((row.role, row.when), ("plan", "planblk.design_section"))
        self.assertIs(row.section, s)

        # 宣言の口: Section の値だけを名と並べる（素の str・数・関数は数えない）
        mod = types.SimpleNamespace(A_HEAD=s, B_HEAD=human, PLAIN_HEAD="## 素の字", N=3, ROWS=[row], f=lambda: s)
        got = dict(m.declared_sections(mod))
        self.assertEqual(set(got), {"A_HEAD", "B_HEAD"})
        self.assertIs(got["A_HEAD"], s)
        self.assertIs(got["B_HEAD"], human)
        self.assertEqual(dict(m.declared_sections(types.SimpleNamespace(X="## y"))), {})


if __name__ == "__main__":
    unittest.main()
