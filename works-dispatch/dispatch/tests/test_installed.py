"""前の版の置き場で打たれた dispatch.py が、今入っている版へ乗り換えるか（installed.py）。
2026-10-17 に、0.25.0 を入れる --land を、頼みの行に残った 0.23.0 の置き場の dispatch.py で打ち、0.24.0 で足した合図
（[[land.after]]）が黙って飛ばされた。"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import installed


class Installed(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp()) / "plugins"
        self.old = self.put("0.23.0", "print('old')")
        # dispatch.py と同じく標準入出力を UTF-8 にする（Windows の既定の符号では日本語を print できない。下の hop の子の標準エラーも同じ）
        self.new = self.put("0.25.0", "import os, sys; sys.stdout.reconfigure(encoding='utf-8'); "
                                      "print('new', sys.argv[1:], os.environ.get('WORKS_DISPATCH_HOPPED'))")

    def put(self, version, body):
        script = self.root / "cache" / "raiki61" / "works-dispatch" / version / "dispatch" / "dispatch.py"
        script.parent.mkdir(parents=True)
        script.write_text(body + "\n", encoding="utf-8")
        return script

    def record(self, *entries):
        (self.root / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {"works-dispatch@raiki61": list(entries)}}),
                                                          encoding="utf-8")

    def entry(self, version, scope="user"):
        return {"scope": scope, "installPath": str(self.root / "cache" / "raiki61" / "works-dispatch" / version), "version": version}

    def test_an_old_version_hops_to_the_installed_one(self):
        self.record(self.entry("0.25.0"))
        self.assertEqual(installed.target(self.old, {}), str(self.new))
        self.assertIsNone(installed.target(self.new, {}))   # 今の版はそのまま

    def test_the_user_install_wins_and_a_listed_install_stays(self):
        self.record(self.entry("0.23.0", "project"), self.entry("0.25.0"))
        self.assertIsNone(installed.target(self.old, {}))   # 自分も控えに載っている（project の入れ方）なら、そのまま
        newest = self.put("0.26.0", "")
        self.record(self.entry("0.25.0", "project"), self.entry("0.26.0"))
        self.assertEqual(installed.target(self.old, {}), str(newest))

    def test_no_hop_outside_the_cache_without_a_record_or_after_a_hop(self):
        self.record(self.entry("0.25.0"))
        self.assertIsNone(installed.target(self.old, {installed.HOPPED: "1"}))
        self.assertIsNone(installed.target(pathlib.Path(installed.__file__), {}))   # リポジトリの checkout
        (self.root / "installed_plugins.json").write_text("{", encoding="utf-8")
        self.assertIsNone(installed.target(self.old, {}))
        self.record(self.entry("0.24.0"))                     # 控えの指す置き場が消えている
        self.assertIsNone(installed.target(self.old, {}))

    def test_a_record_in_an_unexpected_shape_says_why_instead_of_staying_silent(self):
        self.assertEqual(installed.look(pathlib.Path(installed.__file__), {}), (None, None))   # リポジトリの checkout は言わない
        self.record(self.entry("0.25.0"))
        self.assertEqual(installed.look(self.new, {}), (None, None))
        for broken, why in (("{", "読めない"), (json.dumps({"version": 3, "plugins": {"works-dispatch@raiki61": {"path": "x"}}}), "installPath が無い")):
            (self.root / "installed_plugins.json").write_text(broken, encoding="utf-8")
            with self.subTest(why=why):
                self.assertIn(why, installed.look(self.old, {})[1])
        self.record(self.entry("0.24.0"))
        self.assertIn("が無い", installed.look(self.old, {})[1])
        deeper = self.root / "cache" / "raiki61" / "works-dispatch" / "0.25.0" / "x" / "dispatch" / "dispatch.py"
        self.assertIn("の形でない", installed.look(deeper, {})[1] or "")

    def test_the_real_record_still_reads(self):
        # 2026-10-19 の本物の控え（tests/samples。パスだけ試験の置き場に替えた）。形が変われば、ここで落ちる
        sample = json.loads((pathlib.Path(__file__).parent / "samples" / "installed_plugins.json").read_text(encoding="utf-8"))
        for e in sample["plugins"]["works-dispatch@raiki61"]:
            e["installPath"] = str(self.root / "cache" / "raiki61" / "works-dispatch" / "0.25.0")
        (self.root / "installed_plugins.json").write_text(json.dumps(sample), encoding="utf-8")
        self.assertEqual(installed.look(self.old, {}), (str(self.new), None))

    def test_hop_runs_the_installed_script_with_the_same_arguments(self):
        self.record(self.entry("0.25.0"))
        got = subprocess.run([sys.executable, "-c", "import sys; sys.stderr.reconfigure(encoding='utf-8'); sys.path.insert(0, sys.argv[1]); import installed; "
                              "sys.exit(installed.hop(sys.argv[2], ['--land', '割り振り']))",
                              os.path.dirname(installed.__file__), str(self.old)],
                             capture_output=True, text=True, encoding="utf-8", env={k: v for k, v in os.environ.items() if k != installed.HOPPED})
        self.assertEqual((got.returncode, got.stdout.strip()), (0, "new ['--land', '割り振り'] 1"))
        self.assertIn("今入っている版", got.stderr)
        self.assertIsNone(installed.hop(self.new, []))
