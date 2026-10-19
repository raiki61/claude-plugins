"""会社の形と dispatch の設定の、読む鍵と外した鍵の一覧（known_keys）。見本は my_notes と claude-plugins の今の会社の形から採った
鍵の骨組み（samples/company-*.toml。文は x に置き換えた）。--deliver と --ask が止まるのは test_deliver の Flow で見る。"""

import pathlib
import tomllib
import unittest
from unittest import mock

from . import DISPATCH
import known_keys
from nodes import land, role, tree

SAMPLES = pathlib.Path(__file__).parent / "samples"
SHAPES = ("company-my_notes.toml", "company-claude-plugins.toml")
LIVE = DISPATCH.parent.parent / ".claude" / "company.toml"   # このリポジトリの今の会社の形（works-dispatch だけを配った所には無い）


def read(text, tmp):
    p = pathlib.Path(tmp, *tree.INFO_FILE)
    p.parent.mkdir(exist_ok=True)
    p.write_text(text, encoding="utf-8")
    info = tree.read_info(tmp, None, committed=lambda root: None)
    return info, role.load(info["path"], info["text"])


class Samples(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def test_the_current_shapes_have_no_unknown_keys(self):
        for name in SHAPES:
            with self.subTest(name=name):
                info, shape = read((SAMPLES / name).read_text(encoding="utf-8"), self.tmp)
                self.assertEqual((info["problems"], info["keys"], shape["problems"]), ([], [], []))
                self.assertTrue(shape["roles"])
                self.assertEqual({n: r["odd"] for n, r in shape["roles"].items() if r["odd"]}, {})
                for r in shape["roles"]:
                    self.assertEqual(land.read_rules(info["path"], r, info["text"])["problems"], [])

    @unittest.skipUnless(LIVE.is_file(), "このリポジトリの会社の形が無い")
    def test_this_repository_shape_has_no_unknown_keys(self):
        # 会社の形に鍵を足したのに一覧（known_keys.COMPANY）を直し忘れると、ここで赤になる
        raw = tomllib.loads(LIVE.read_text(encoding="utf-8"))
        self.assertEqual(known_keys.company(raw, str(LIVE)), [])

    def test_a_misspelt_key_is_noted_and_marks_the_role(self):
        text = (SAMPLES / "company-my_notes.toml").read_text(encoding="utf-8").replace("deliver_check =", "deliver_chek =", 1)
        info, shape = read(text, self.tmp)
        self.assertEqual(len(info["keys"]), 1, info["keys"])
        self.assertIn("roles[0]（担当）: 知らない鍵 deliver_chek（読まない", info["keys"][0])
        self.assertIn(info["keys"][0], info["notes"])
        self.assertEqual(info["problems"], [])   # 止めはしない（役を外さず、ほかの読み手も今までどおり動く）
        self.assertEqual(shape["roles"]["担当"]["odd"], ["deliver_chek"])
        self.assertIsNone(shape["roles"]["担当"]["deliver_check"])
        self.assertEqual(shape["roles"]["作業"]["odd"], [])

    def test_unknown_keys_of_every_table_are_noted(self):
        text = (SAMPLES / "company-claude-plugins.toml").read_text(encoding="utf-8")
        text = text.replace('default_role = "作業"', 'default_role = "作業"\nowner = "x"', 1)
        text = text.replace('fallback_role = "作業"', 'fallback_role = "作業"\nfallback = "x"', 1)
        text = text.replace('effort = "high"', 'effort = "high"\nondemand = true', 1)
        text = text.replace('report_to = "my_notes/社長室"', 'report_to = "my_notes/社長室"\nevry = "7d"', 1)
        text = text.replace('[[land.after]]', '[[land.after]]\ninputs = {}', 1)
        info, shape = read(text, self.tmp)
        got = [n.split(": ", 1)[1] for n in info["keys"]]
        self.assertEqual(len(got), 5, got)
        self.assertIn("知らない鍵 owner（読まない", got[0])
        self.assertIn("の tools[0]: 知らない鍵 fallback（読まない", got[1])
        self.assertIn("skills[1]（割り振り）: 知らない鍵 ondemand", got[2])
        self.assertIn("の start: 知らない鍵 evry", got[3])
        self.assertIn("land.after[0]: 知らない鍵 inputs", got[4])
        self.assertEqual({n: r["odd"] for n, r in shape["roles"].items() if r["odd"]}, {})   # ツールの鍵は役のゲートでない

    def test_the_contents_handed_to_others_are_not_read(self):
        # [roles.settings] は Claude Code に、inputSchema は JSON Schema に、[[land.after]] の input はツールに渡す中身
        text = ('[[roles]]\nname = "a"\n[roles.settings]\nanything = 1\n[roles.settings.permissions]\ndeny = []\n'
                '[[roles.tools]]\nname = "t"\ncommand = "true"\ninputSchema = { type = "object", properties = { x = { type = "string" } } }\n'
                '[land]\nmode = "none"\n[[land.after]]\nrole = "a"\ntool = "t"\ninput = { whatever = 1 }\n')
        info, shape = read(text, self.tmp)
        self.assertEqual((info["keys"], shape["roles"]["a"]["odd"]), ([], []))

    def test_land_stops_on_unknown_keys_of_its_own_layers(self):
        text = ('[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "true"\nchek = "x"\n'
                '[land.roles."担当"]\nmian = "dev"\n[land.roles."作業"]\nmain = "dev"\nbmp = "x"\n')
        got = land.read_rules("c.toml", "担当", text)["problems"]
        self.assertEqual(len(got), 2, got)
        self.assertIn("c.toml: land: 知らない鍵 chek", got[0])
        self.assertIn("c.toml: land.roles.担当: 知らない鍵 mian", got[1])   # ほかの役の [land.roles.作業] はこの取り込みに効かない
        self.assertEqual(len(land.read_rules("c.toml", None, text)["problems"]), 1)   # 役の無い部署には、どの役の層も効かない

    def test_retired_keys_are_noted_apart_from_unknown_keys(self):
        text = '[[roles]]\nname = "a"\nold_gate = "x"\n'
        with mock.patch.dict(known_keys.COMPANY_RETIRED, {"roles": {"old_gate": "0.1.0 で外した。deliver_check に書く"}}):
            info, shape = read(text, self.tmp)
        (note,) = info["keys"]
        self.assertIn("roles[0]（a）: 外した鍵 old_gate は読まない（0.1.0 で外した。deliver_check に書く）", note)
        self.assertNotIn("知らない鍵", note)
        self.assertEqual(shape["roles"]["a"]["odd"], ["old_gate"])   # 外した鍵の役も、ゲートでは止める


if __name__ == "__main__":
    unittest.main()
