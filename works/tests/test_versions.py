"""run ごとの版の控え（.shared/core/versions.py）と、それを書く線の start の検査（FAST: 一時の置き場に書くだけ・python を 1 本起こす）。

- snapshot: pack の中身の sha256（キャッシュ・出どころの控えを除く）・出どころ（dev の殻が写しに置く .works-source.json）・
  VERSION・graphloops の写しの行・借りた物の記録（$CLAUDE_CONFIG_DIR/.works-toolset.json）・Archon と Claude Code の版（env）。
  分からない値は null にして、unknown に鍵と理由を書く（推測で埋めない）
- write: <ARTIFACTS_DIR>/versions.json に一時ファイルから置き換えて書く
- darkfactory/scripts/start.py は入力を拒む run でも、盤面より先に versions.json を書く
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import versions  # noqa: E402

TOOLSET = {"superpowers": {"version": "6.4.2", "source": "/x", "sha256": "ab", "loaded": True}}


def make_pack(base: pathlib.Path) -> pathlib.Path:
    pack = base / "pack"
    (pack / ".shared" / "core").mkdir(parents=True)
    (pack / ".shared" / "core" / "COPIED_FROM").write_text("a1202d0  graphloops 0.21.0\nengine/x.py\n", encoding="utf-8")
    (pack / "archon-plugin.json").write_text("{}\n", encoding="utf-8")
    (pack / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    (pack / versions.SOURCE_FILE).write_text(json.dumps({"rev": "f" * 40, "dirty": False, "from": "/src/works"}),
                                             encoding="utf-8")
    return pack


class VersionsCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.pack = make_pack(self.tmp)
        self.cfg = self.tmp / "claude-config"
        self.cfg.mkdir()
        (self.cfg / versions.TOOLSET_RECORD).write_text(json.dumps(TOOLSET), encoding="utf-8")
        self.env = {"WORKS_ARCHON_VERSION": "v0.11.1", "WORKS_CLAUDE_VERSION": "2.1.0 (Claude Code)",
                    "CLAUDE_CONFIG_DIR": str(self.cfg)}

    def tearDown(self):
        self._tmp.cleanup()

    def test_snapshot_fields(self):
        doc = versions.snapshot(self.pack, self.env, run_id="r-1")
        self.assertEqual(doc["schema"], versions.SCHEMA)
        self.assertEqual(doc["run_id"], "r-1")
        self.assertEqual(doc["works"]["source"], {"rev": "f" * 40, "dirty": False, "from": "/src/works"})
        self.assertEqual(doc["works"]["version"], "0.2.0")
        self.assertRegex(doc["works"]["pack_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(doc["works"]["files"], 3)   # COPIED_FROM・archon-plugin.json・VERSION（出どころの控えは数えない）
        self.assertEqual(doc["graphloops_copy"], "a1202d0  graphloops 0.21.0")
        self.assertEqual(doc["borrowed"], TOOLSET)
        self.assertEqual(doc["archon"], "v0.11.1")
        self.assertEqual(doc["claude_code"], "2.1.0 (Claude Code)")
        self.assertTrue(doc["python"])
        self.assertTrue(doc["at"].endswith("Z"))
        self.assertEqual(doc["unknown"], {})

    def test_unknown_is_null_with_reason(self):
        """分からない値は null、unknown に同じ鍵と理由（黙って落とさない）"""
        bare = self.tmp / "bare"
        bare.mkdir()
        (bare / "a.txt").write_text("x", encoding="utf-8")
        doc = versions.snapshot(bare, {}, run_id="")
        for key, got in (("works.source", doc["works"]["source"]), ("works.version", doc["works"]["version"]),
                         ("graphloops_copy", doc["graphloops_copy"]), ("borrowed", doc["borrowed"]),
                         ("archon", doc["archon"]), ("claude_code", doc["claude_code"])):
            with self.subTest(key):
                self.assertIsNone(got)
                self.assertTrue(doc["unknown"].get(key), doc["unknown"])
        self.assertEqual(set(doc["unknown"]), {"works.source", "works.version", "graphloops_copy", "borrowed",
                                               "archon", "claude_code"})
        self.assertEqual(doc["works"]["files"], 1)

    def test_broken_side_files_are_unknown_not_errors(self):
        (self.pack / versions.SOURCE_FILE).write_text("{not json", encoding="utf-8")
        (self.cfg / versions.TOOLSET_RECORD).write_text("[]", encoding="utf-8")
        doc = versions.snapshot(self.pack, self.env)
        self.assertIsNone(doc["works"]["source"])
        self.assertIn("works.source", doc["unknown"])
        self.assertIsNone(doc["borrowed"])
        self.assertIn("borrowed", doc["unknown"])

    def test_pack_digest_ignores_caches_and_source_file(self):
        before = versions.pack_digest(self.pack)
        (self.pack / "__pycache__").mkdir()
        (self.pack / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
        (self.pack / "y.pyc").write_bytes(b"\0")
        (self.pack / ".DS_Store").write_bytes(b"\0")
        (self.pack / versions.SOURCE_FILE).write_text("{}", encoding="utf-8")
        self.assertEqual(versions.pack_digest(self.pack), before)
        (self.pack / "archon-plugin.json").write_text('{"x": 1}\n', encoding="utf-8")
        self.assertNotEqual(versions.pack_digest(self.pack), before)

    def test_write_replaces_atomically(self):
        art = self.tmp / "artifacts"
        doc = versions.snapshot(self.pack, self.env, run_id="r-2")
        p = versions.write(art, doc)
        self.assertEqual(p, art / versions.FILE)
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), doc)
        versions.write(art, {**doc, "run_id": "r-3"})
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["run_id"], "r-3")
        self.assertEqual(sorted(x.name for x in art.iterdir()), [versions.FILE])   # 一時ファイルを残さない


class StartWritesVersionsCase(unittest.TestCase):
    def test_start_writes_versions_even_when_refused(self):
        """入力を拒む run（依頼のファイルが無い）でも、start は盤面より先に <ARTIFACTS_DIR>/versions.json を書く"""
        with tempfile.TemporaryDirectory() as t:
            tmp = pathlib.Path(t)
            art = tmp / "artifacts"
            cwd = tmp / "target"
            cwd.mkdir()
            env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
            env.update({"INPUTS_REQUEST": str(tmp / "no-such-request.json"), "INPUTS_TEST_CMD": "true",
                        "INPUTS_THICKNESS": "", "INPUTS_GATES": "", "INPUTS_FINAL_GATE": "", "INPUTS_ADAPTER": "",
                        "INPUTS_POLICY_MD": "", "ARTIFACTS_DIR": str(art), "WORKFLOW_ID": "run-v-1",
                        "WORKS_ARCHON_VERSION": "v0.11.1", "PYTHONDONTWRITEBYTECODE": "1"})
            r = subprocess.run([sys.executable, str(ROOT / "darkfactory" / "scripts" / "start.py")], cwd=cwd, env=env,
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0, r.stdout)
            doc = json.loads((art / versions.FILE).read_text(encoding="utf-8"))
            self.assertEqual(doc["run_id"], "run-v-1")
            self.assertEqual(doc["archon"], "v0.11.1")
            self.assertEqual(doc["works"]["pack_sha256"], versions.pack_digest(ROOT))


if __name__ == "__main__":
    unittest.main()
