"""役が読むだけの gh を呼ぶ形の柵（呼び方の正本は包み .shared/core/adapter.py の RO_GH・RO_GH_EXCLUDED・RO_GH_RULE）。

役の Bash は sandbox の中で網を閉じて走り、外に出るのは sandbox の excludedCommands（`works-gh:*`）に当たるコマンドだけ。
当たるのは口を素の名 works-gh で打った 1 つだけのコマンドで、`"$WORKS_GH" pr list …` のように変数や絶対パスで打つと、
パイプ・`&&` でつなぐと、前に変数の代入を置くと当たらずに sandbox の中で走り、`deny network-outbound api.github.com:443` で
落ちる（2026-10-09 の利用者の run で並行 PR の確認役が PR を読めなかった。写しの graphloops の role_run.py の頭の実測も同じ）。

ここで縛る物:
1. 口の名は 1 か所: 口のファイル（no-post-bin/<RO_GH>）と、除外の名 RO_GH_EXCLUDED は RO_GH から組む
2. sandbox に除外を持つ AI の節は、除外が RO_GH_EXCLUDED だけで、その節の指示書が呼び方の文 RO_GH_RULE をそのまま持つ
3. 役の指示書（下の SCAN）のコマンド（`…` と ``` の中の行）は、gh を打つなら素の名 works-gh の 1 つだけのコマンドで始める。
   `$WORKS_GH` は書かない。`gh …` は禁じる行（使うな・打つな）でだけ名指してよい
"""
import pathlib
import re
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import adapter  # noqa: E402

# 役の指示書でない md（人が読む文書・人の会話で走る skill・試験と開発の殻）
NOT_ROLE = ("docs/", "tests/", "dev/", "skills/", "README.md", "CHANGELOG.md")
BORROW = ".shared/borrow/"
# 借りた superpowers の本文は写しで直せない。gh を打つ段落は seams.json の錨（rule GITHUB）が役の指示書で読み替える
BORROW_GH_RULE = "GITHUB"
JOINERS = ("|", "&&", ";", "$(", "`", "\n")
FORBID = ("使うな", "打つな")


def role_prompts(root=ROOT):
    """役に渡る md（works からのパス → 中身）"""
    out = {}
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(NOT_ROLE) or "__pycache__" in rel:
            continue
        out[rel] = p.read_text(encoding="utf-8")
    return out


def commands(text):
    """(行, コマンド) の組: 行の中の `…` と、``` の囲みの中の行"""
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            yield line, line.strip()
            continue
        for span in re.findall(r"`([^`]+)`", line):
            yield line, span.strip()


def gh_misuse(text):
    """役に gh を素の名 works-gh の 1 つだけのコマンドの外で打たせる所（コマンドの一覧）"""
    bad = []
    for line, cmd in commands(text):
        words = cmd.split()
        if not words:
            continue
        if "WORKS_GH" in cmd:
            bad.append(cmd)
        elif adapter.RO_GH in cmd and cmd not in (adapter.RO_GH, f"command -v {adapter.RO_GH}"):   # 名と、在るかの確かめは打つ形でない
            if words[0] != adapter.RO_GH or any(j in cmd for j in JOINERS):
                bad.append(cmd)
        elif words[0] == "gh" and len(words) > 1 and not any(f in line for f in FORBID):
            bad.append(cmd)
    return bad


def ai_nodes(node):
    """YAML の木の AI の節（command を持つ dict）"""
    if isinstance(node, dict):
        if "command" in node:
            yield node
        for v in node.values():
            yield from ai_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from ai_nodes(v)


class PortName(unittest.TestCase):
    def test_port_file_and_exclusion_come_from_one_name(self):
        """口のファイルは no-post-bin/<RO_GH>、sandbox の除外の名は RO_GH から組む"""
        self.assertTrue((adapter.NO_POST_BIN / adapter.RO_GH).is_file())
        self.assertEqual(adapter.RO_GH_EXCLUDED, f"{adapter.RO_GH}:*")
        self.assertIn(f"`{adapter.RO_GH}`", adapter.RO_GH_RULE)
        self.assertIn(f"`{adapter.RO_GH} pr view ", adapter.RO_GH_RULE)
        self.assertEqual(gh_misuse(adapter.RO_GH_RULE), [])


class ExcludingRoles(unittest.TestCase):
    def test_excluding_nodes_use_the_port_name_and_carry_the_rule(self):
        """sandbox に除外を持つ AI の節: 除外は口の名だけ、指示書は呼び方の文をそのまま持つ"""
        seen = []
        for y in sorted(ROOT.glob("*/*.yaml")):
            doc = yaml.safe_load(y.read_text(encoding="utf-8"))
            for n in ai_nodes(doc):
                ex = (n.get("sandbox") or {}).get("excludedCommands")
                if ex is None:
                    continue
                where = f"{y.relative_to(ROOT)}:{n.get('id')}"
                seen.append(where)
                with self.subTest(where):
                    self.assertEqual(ex, [adapter.RO_GH_EXCLUDED])
                    prompt = y.parent / "commands" / f"{n['command']}.md"
                    self.assertIn(adapter.RO_GH_RULE, prompt.read_text(encoding="utf-8"), prompt)
        self.assertGreaterEqual(len(seen), 5, seen)   # 並行 PR の確認役 1 と素材集めの 4（数えずに通らないように）

    def test_prompts_that_call_the_port_carry_the_rule(self):
        """口でコマンドを打たせる指示書は、なぜ素の名の 1 つだけかの文も持つ"""
        for rel, text in role_prompts().items():
            if rel.startswith(BORROW):
                continue
            calls = [c for _, c in commands(text) if c.startswith(f"{adapter.RO_GH} ")]
            if calls:
                with self.subTest(rel):
                    self.assertIn(adapter.RO_GH_RULE, text)


class RolePromptsCallBarePort(unittest.TestCase):
    def test_role_prompts_start_gh_with_the_bare_port(self):
        """役の指示書のどれも、gh を口の素の名の 1 つだけのコマンドの外で打たせない"""
        import json
        seams = json.loads((ROOT / BORROW / "seams.json").read_text(encoding="utf-8"))
        overridden = {a["file"] for s in seams.values() if isinstance(s, dict)
                      for a in s.get("anchors", []) if a.get("rule") == BORROW_GH_RULE}
        prompts = role_prompts()
        self.assertGreater(len(prompts), 30, sorted(prompts))
        for rel, text in prompts.items():
            if rel.startswith(BORROW) and any(rel.endswith(f) for f in overridden):
                continue
            with self.subTest(rel):
                self.assertEqual(gh_misuse(text), [])

    def test_fence_catches_the_broken_forms(self):
        """柵そのもの: 変数・絶対パス・つなぎ・素の gh を赤に、素の名の 1 つだけと禁じる行の名指しを緑にする"""
        red = ['`"$WORKS_GH" pr list -R o/r`', "`/x/no-post-bin/works-gh pr view 1 -R o/r`",
               "`works-gh pr diff 1 -R o/r | head`", "`cd x && works-gh pr list -R o/r`",
               "`GH_TOKEN=x works-gh pr list -R o/r`", "`gh pr view 1 -R o/r` で読め",
               "```\nworks-gh pr list -R o/r; echo\n```"]
        for t in red:
            with self.subTest(t):
                self.assertNotEqual(gh_misuse(t), [])
        green = ["`works-gh pr view 1 -R o/r --json files --jq '.files[].path'`", "口 `works-gh` を素の名で",
                 "`gh repo view` の値を使うな", "素の `gh` は包みが拒む", "`git log`", "`command -v works-gh` が何も出さない"]
        for t in green:
            with self.subTest(t):
                self.assertEqual(gh_misuse(t), [])


if __name__ == "__main__":
    unittest.main()
