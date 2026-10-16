"""設計書 4 節の決まり D1〜D6・D8 の柵。今の木で緑なことと、わざと破った小さな木で各柵が誤りを返すことを見る。"""

import json
import pathlib
import tempfile
import textwrap
import unittest

from . import DISPATCH
from . import fences


def tree(files):
    """{相対パス: 本文} から一時の木を作り、その根を返す。"""
    root = pathlib.Path(tempfile.mkdtemp(prefix="dispatch-fence-"))
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
    return root


SCHEMA_OK = json.dumps({"type": "object", "required": ["schema"], "properties": {"schema": {"type": "integer"}}})


class RealTree(unittest.TestCase):
    def test_real_tree_keeps_every_rule(self):
        self.assertEqual(fences.check_all(DISPATCH), [])


class EachFenceCatches(unittest.TestCase):
    def assertCaught(self, fence, files):
        self.assertNotEqual(fence(tree(files)), [], f"{fence.__name__} が破った木を通した")

    def test_d1_old_works_path(self):
        self.assertCaught(fences.d1_old_works, {"x.py": "P = '../.shared/core/claude_auth.py'\n"})
        self.assertCaught(fences.d1_old_works, {"x.py": "import sys\nsys.path.append('works/dev')\n"})
        self.assertCaught(fences.d1_old_works, {"x.py": "R = 'darkfactory'\n"})

    def test_compiles_without_warning(self):
        self.assertCaught(fences.compiles_clean, {"x.py": 'S = "\\`"\n'})

    def test_d2_shell_script(self):
        self.assertCaught(fences.d2_no_sh, {"run.sh": "echo hi\n"})

    def test_d3_node_imports_node(self):
        self.assertCaught(fences.d3_nodes_blind, {"nodes/a.py": "import b\n", "nodes/b.py": "X = 1\n"})
        self.assertCaught(fences.d3_nodes_blind, {"nodes/a.py": "from b import X\n", "nodes/b.py": "X = 1\n"})

    def test_d4_subprocess_outside_ports(self):
        self.assertCaught(fences.d4_outward, {"nodes/assign.py": "import subprocess\n"})
        self.assertCaught(fences.d4_outward, {"nodes/assign.py": "from subprocess import run\n"})

    def test_d4_herdr_write_outside_launch_and_turn(self):
        self.assertCaught(fences.d4_outward, {"nodes/report.py": "import herdr\nherdr.run('p', 'c')\n"})
        self.assertCaught(fences.d4_outward, {"nodes/report.py": "import herdr as h\nh.prompt('p', 't', False)\n"})
        self.assertCaught(fences.d4_outward, {"nodes/report.py": "from herdr import prompt\n"})

    def test_d4_write_through_an_injected_port_outside_its_node(self):
        self.assertCaught(fences.d4_outward, {"nodes/report.py": "def f(h):\n    h.create_worktree('/s', 'b', 'o/b', 'x')\n"})
        self.assertCaught(fences.d4_outward, {"nodes/assign.py": "def f(h):\n    h.remove_worktree('/s', '/p', 'x')\n"})
        self.assertCaught(fences.d4_outward, {"nodes/turn.py": "def f(g):\n    g.delete_branch('/s', 'b', 'sha')\n"})
        self.assertCaught(fences.d4_outward, {"nodes/clean.py": "def f(gh):\n    gh.issue_develop('o/r', 1, 'main')\n"})
        self.assertCaught(fences.d4_outward, {"dispatch.py": "from ghx import issue_develop\n"})
        self.assertCaught(fences.d4_outward, {"nodes/assign.py": "def f(g):\n    g.fast_forward('/c', 'b')\n"})
        self.assertCaught(fences.d4_outward, {"nodes/launch.py": "def f(h):\n    h.prompt('p', 't', True)\n"})
        self.assertCaught(fences.d4_outward, {"dispatch.py": "from gitx import fetch\n"})
        self.assertCaught(fences.d4_outward, {"dispatch.py": "def f(h):\n    h.rename_pane('p', 'x')\n"})

    def test_d4_subprocess_run_is_not_a_herdr_write(self):
        self.assertEqual(fences.d4_outward(tree({"dispatch.py": "import subprocess\nsubprocess.run(['x'])\n"})), [])

    def test_d4_allows_launch_and_turn(self):
        ok = {"nodes/launch.py": "import herdr\nherdr.run('p', 'c')\n",
              "nodes/turn.py": "def f(h):\n    h.prompt('p', 't', True)\n",
              "nodes/provision.py": ("def f(h, g, gh):\n    g.fetch('s', 'b')\n    h.create_worktree('s', 'b', 'o/b', 'l')\n"
                                     "    h.open_worktree('s', 'p', 'l')\n    g.fast_forward('p', 'b')\n"
                                     "    gh.issue_develop('o/r', 1, 'main')\n"),
              "nodes/clean.py": "def f(h, g):\n    h.remove_worktree('s', 'p', 'l')\n    g.delete_branch('s', 'b', 'x')\n",
              "herdr.py": "import subprocess\n", "ghx.py": "def issue_develop(r, n, b):\n    pass\n"}
        self.assertEqual(fences.d4_outward(tree(ok)), [])

    def test_d5_timeout(self):
        self.assertCaught(fences.d5_no_timeout, {"x.py": "subprocess.run(a, timeout=5)\n"})

    def test_d6_owner_env(self):
        for word in ("raiki61", "claude-code-oauth-default", "/Users/someone", "claude-p1"):
            with self.subTest(word=word):
                self.assertCaught(fences.d6_no_owner_env, {"x.py": f"V = '{word}'\n"})

    def test_d6_does_not_catch_the_official_plugin_folder_name(self):
        # .claude-plugin は Claude Code のプラグインの決まったフォルダ名で、持ち主の環境の値ではない
        self.assertEqual(fences.d6_no_owner_env(tree({"x.py": "P = '.claude-plugin/plugin.json'\n"})), [])
        self.assertCaught(fences.d6_no_owner_env, {"x.py": "C = 'claude-p12'\n"})

    def test_d8_schema_shape(self):
        self.assertCaught(fences.d8_schemas, {"schemas/a.schema.json": "{not json"})
        self.assertCaught(fences.d8_schemas, {"schemas/a.schema.json": json.dumps({"type": "object"})})
        self.assertEqual(fences.d8_schemas(tree({"schemas/a.schema.json": SCHEMA_OK})), [])

    def test_tests_and_vendor_are_not_scanned(self):
        files = {"tests/t.py": "import subprocess\nV = 'raiki61 timeout darkfactory'\n",
                 "vendor/w.py": "import subprocess\nV = 'timeout'\n"}
        self.assertEqual(fences.check_all(tree(files)), [])


if __name__ == "__main__":
    unittest.main()
