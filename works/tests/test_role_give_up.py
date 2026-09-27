"""役の出し直しの輪は done で抜ける（R50）を、全部のブロックの YAML に縛る。

受け付けの ok で抜ける輪は、3 回目の拒否で max_iterations に当たって run を落とす。blk-judge・blk-fix などには当たった形が
delta・pr・premises・purpose・refix の 7 本に漏れていた（ブロックごとの試験がそれぞれの形を固め、どちらも緑だった）。
ここは YAML を読むだけ（git・子のプロセスなし）。
"""
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
UNTIL = re.compile(r"test \$(?P<node>[\w-]+)\.output\.(?P<field>\w+) = true$")


def loops(doc):
    """(輪の節, 中の節の一覧) を辿る"""
    for n in doc.get("nodes") or []:
        lg = n.get("loop_group")
        if lg:
            yield n, lg
            yield from loops(lg)


def block_files():
    return sorted(p for p in ROOT.glob("blk-*/blk-*.yaml") if p.stem == p.parent.name)


class RoleLoopDoneCase(unittest.TestCase):
    def test_every_loop_exits_on_done(self):
        """どのブロックの輪も、最後の節（受け付け）の done で抜け、その節の output_format は done を必ず持つ"""
        files = block_files()
        self.assertTrue(files)
        for path in files:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            for n, lg in loops(doc):
                with self.subTest(f"{path.parent.name}/{n['id']}"):
                    m = UNTIL.match(lg["until_bash"].split("#")[0].strip())
                    self.assertIsNotNone(m, lg["until_bash"])
                    self.assertEqual(m["field"], "done", lg["until_bash"])
                    last = lg["nodes"][-1]
                    self.assertEqual(m["node"], last["id"])
                    fmt = last.get("output_format") or {}
                    self.assertEqual((fmt.get("properties") or {}).get("done"), {"type": "boolean"})
                    self.assertIn("done", fmt.get("required") or [])


if __name__ == "__main__":
    unittest.main()
