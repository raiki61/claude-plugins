"""pack の YAML の決まり（設計書 7 節の守りと期限・Ruling R4）の検査。

check_file(path) は 1 本の工程の YAML を読み、決まりに反する所を文の一覧で返す（空なら緑）。決まり:
- bash・script の節は timeout: 1728000000（20 日）を持つ。2^31-1 ms を超える値は Archon の検査を通るのに実行で即失敗する
- AI の節（prompt: か command: を持つ節）は idle_timeout: 1728000000・output_format・sandbox: {enabled: true} を持つ
- AI の節の allowed_tools は [Read, Grep, Glob] の部分集合（無ければ全部の道具を持つので違反）。
  外れてよいのは blk-fix/blk-fix.yaml の節 fix（書く役）だけ
- approval・include・loop_group の節は期限を持たない。書く期限の欄は上の 2 つだけ（AI の節の timeout・bash の節の idle_timeout も違反）
- loop_group は max_iterations: 3 と until_bash を持つ。中の節（loop_group.nodes）も同じ決まりで辿る
- 上のどれでもない種類の節（loop: など）は違反（決まりを決めていない種類を黙って通さない）

違反の見本は tests/yaml_bad/（1 本 1 違反）、守った見本は tests/yaml_good/。YAML を読むのはテストだけ（PyYAML は run.sh が足す）。
"""
import pathlib
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent

DEADLINE = 1728000000                     # 20 日（ms）
READ_ONLY_TOOLS = {"Read", "Grep", "Glob"}
WRITER = ("blk-fix", "blk-fix.yaml", "fix")   # 書く道具を持ってよい唯一の節: (フォルダ, ファイル, 節)
AI_KEYS = ("prompt", "command")
TIMED_KEYS = ("bash", "script")
QUIET_KEYS = ("approval", "include", "loop_group")   # 期限を持たない種類


def _is_deadline(v):
    return type(v) is int and v == DEADLINE      # True や "1728000000" は通さない


def _kind(node):
    for k in AI_KEYS + TIMED_KEYS + QUIET_KEYS:
        if k in node:
            return k
    return None


def _check_node(node, where, writer_ok, out):
    if not isinstance(node, dict):
        out.append(f"{where}: 節が表（mapping）でない")
        return
    nid = node.get("id")
    at = f"{where}節 {nid}"
    kind = _kind(node)
    if kind is None:
        out.append(f"{at}: 節の種類が決まりの内に無い（{sorted(node)}）")
        return
    has_t, has_it = "timeout" in node, "idle_timeout" in node
    if kind in TIMED_KEYS:
        if not _is_deadline(node.get("timeout")):
            out.append(f"{at}: {kind} の節の timeout が {DEADLINE} でない（{node.get('timeout')!r}）")
        if has_it:
            out.append(f"{at}: {kind} の節に idle_timeout を書いた")
    elif kind in AI_KEYS:
        if not _is_deadline(node.get("idle_timeout")):
            out.append(f"{at}: AI の節の idle_timeout が {DEADLINE} でない（{node.get('idle_timeout')!r}）")
        if has_t:
            out.append(f"{at}: AI の節に timeout を書いた")
        if not isinstance(node.get("output_format"), dict) or not node["output_format"]:
            out.append(f"{at}: AI の節に output_format が無い")
        sb = node.get("sandbox")
        if not (isinstance(sb, dict) and sb.get("enabled") is True):
            out.append(f"{at}: AI の節の sandbox.enabled が true でない（{sb!r}）")
        tools = node.get("allowed_tools")
        if not (writer_ok and nid == WRITER[2]):
            if not isinstance(tools, list):
                out.append(f"{at}: AI の節に allowed_tools が無い（無ければ全部の道具を持つ）")
            elif not set(tools) <= READ_ONLY_TOOLS:
                out.append(f"{at}: AI の節の allowed_tools が {sorted(READ_ONLY_TOOLS)} の外を持つ"
                           f"（{sorted(set(tools) - READ_ONLY_TOOLS)}）")
    else:
        if has_t or has_it:
            out.append(f"{at}: {kind} の節に期限（timeout・idle_timeout）を書いた")
    if kind == "loop_group":
        g = node["loop_group"]
        if not isinstance(g, dict):
            out.append(f"{at}: loop_group が表でない")
            return
        if not (type(g.get("max_iterations")) is int and g["max_iterations"] == 3):
            out.append(f"{at}: loop_group の max_iterations が 3 でない（{g.get('max_iterations')!r}）")
        if not (isinstance(g.get("until_bash"), str) and g["until_bash"].strip()):
            out.append(f"{at}: loop_group に until_bash が無い")
        _check_nodes(g.get("nodes"), f"{at} の中の", writer_ok, out)


def _check_nodes(nodes, where, writer_ok, out):
    if not isinstance(nodes, list) or not nodes:
        out.append(f"{where}nodes が無い")
        return
    for n in nodes:
        _check_node(n, where, writer_ok, out)


def check_file(path: pathlib.Path) -> list:
    """1 本の工程の YAML の違反の文の一覧（空なら決まりを全部守っている）"""
    path = pathlib.Path(path)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    if not isinstance(doc, dict):
        return [f"{path.name}: 工程の YAML が表でない"]
    writer_ok = (path.parent.name, path.name) == WRITER[:2]
    _check_nodes(doc.get("nodes"), f"{path.name}: ", writer_ok, out)
    return out


class YamlRulesCase(unittest.TestCase):
    def test_each_bad_yaml_is_red(self):
        bad = sorted((TESTS / "yaml_bad").glob("*.yaml"))
        self.assertGreaterEqual(len(bad), 5)
        for p in bad:
            with self.subTest(p.name):
                found = check_file(p)
                self.assertEqual(len(found), 1, f"{p.name}: 違反はちょうど 1 つのはず: {found}")

    def test_good_yaml_is_green(self):
        good = sorted((TESTS / "yaml_good").glob("*.yaml"))
        self.assertTrue(good)
        for p in good:
            with self.subTest(p.name):
                self.assertEqual(check_file(p), [])

    def test_pack_yaml_is_green(self):
        files = sorted(ROOT.glob("*/*.yaml"))
        for p in files:
            with self.subTest(str(p.relative_to(ROOT))):
                self.assertEqual(check_file(p), [])

    def test_writer_allowed_only_in_blk_fix(self):
        body = (TESTS / "yaml_bad" / "fix_outside_blk_fix.yaml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            for folder, name, want in (("blk-fix", "blk-fix.yaml", 0), ("blk-judge", "blk-fix.yaml", 1),
                                       ("blk-fix", "other.yaml", 1)):
                p = pathlib.Path(tmp) / folder / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
                with self.subTest(f"{folder}/{name}"):
                    self.assertEqual(len(check_file(p)), want, check_file(p))
            # blk-fix の中でも fix 以外の節は読むだけの道具に限る
            p = pathlib.Path(tmp) / "blk-fix" / "blk-fix.yaml"
            p.write_text(body.replace("id: fix", "id: accept-fix"), encoding="utf-8")
            self.assertEqual(len(check_file(p)), 1, check_file(p))


if __name__ == "__main__":
    unittest.main()
