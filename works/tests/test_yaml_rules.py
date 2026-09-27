"""pack の YAML の決まり（設計書 7 節の守りと期限・Ruling R4）の検査。

check_file(path) は 1 本の工程の YAML を読み、決まりに反する所を文の一覧で返す（空なら緑）。決まり:
- bash・script の節は timeout: 1728000000（20 日）を持つ。2^31-1 ms を超える値は Archon の検査を通るのに実行で即失敗する
- AI の節（prompt: か command: を持つ節）は idle_timeout: 1728000000・output_format・
  sandbox: {enabled: true, allowUnsandboxedCommands: false} を持つ（Ruling R12。Bash がサンドボックスの外へ出る道を閉じる）
- AI の節の allowed_tools は [Read, Grep, Glob] の部分集合（無ければ全部の道具を持つので違反）。
  外れてよいのは blk-fix/blk-fix.yaml の節 fix（書く役）と、blk-premises/blk-premises.yaml の節 premises（測る役。
  [Read, Grep, Glob, Bash] の部分集合まで。測るためにコマンドを走らせるが書く道具は持たない。Bash はサンドボックスの中）だけ
- AI の節は settingSources: [] を持つ（役に利用者・対象の CLAUDE.md を読ませない。graphloops の --setting-sources "" と同じ。
  書かなければ Archon は ['project', 'user'] を読ませ、CLAUDE.md の文体の決まりが JSON だけを返す約束を崩す）。
  skills: を持つ節だけは [project] も許す（skills は読む元が要る）
- approval・include・loop_group の節は期限を持たない。書く期限の欄は上の 2 つだけ（AI の節の timeout・bash の節の idle_timeout も違反）
- loop_group は max_iterations: 3 と until_bash を持つ。中の節（loop_group.nodes）も同じ決まりで辿る
- 上のどれでもない種類の節（loop: など）は違反（決まりを決めていない種類を黙って通さない）

違反の見本は tests/yaml_bad/（1 本 1 違反。どの決まりに引っかかるべきかは BAD_EXPECT に置き、件数だけでなく文面で照合する）、
守った見本は tests/yaml_good/。YAML を読むのはテストだけ（PyYAML は run.sh が足す）。
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
MEASURER = ("blk-premises", "blk-premises.yaml", "premises")   # 読む道具に Bash だけを足してよい唯一の節（測る役）
MEASURE_TOOLS = READ_ONLY_TOOLS | {"Bash"}
AI_KEYS = ("prompt", "command")
TIMED_KEYS = ("bash", "script")
QUIET_KEYS = ("approval", "include", "loop_group")   # 期限を持たない種類
# 役の節: (フォルダ, ファイル, 節)。どれもブロックの最初の AI の節で、輪（loop_group）の 1 周目の新しい会話で起きる
ROLES = (("blk-judge", "blk-judge.yaml", "judge"), ("blk-fix", "blk-fix.yaml", "fix"),
         ("blk-delta", "blk-delta.yaml", "review"), ("blk-premises", "blk-premises.yaml", "premises"))


# 違反の見本（yaml_bad の stem）→ 出るべき違反の文面の一部。狙いの検査が壊れて別の検査が偶然 1 件出しても赤になるように、
# 節と決まりと実際の値まで書く（ESLint の RuleTester が invalid な例ごとに messageId を求めるのと同じ考え）
BAD_EXPECT = {
    "ai_no_idle_timeout": "節 judge: AI の節の idle_timeout が 1728000000 でない（None）",
    "ai_no_output_format": "節 judge: AI の節に output_format が無い",
    "ai_no_sandbox": "節 judge: AI の節の sandbox が {enabled: true, allowUnsandboxedCommands: false} でない"
                     "（{'enabled': False, ",
    "ai_no_setting_sources": "節 judge: AI の節の settingSources が [] でない（'（無し）'",
    "ai_sandbox_unsandboxed_allowed": "節 judge: AI の節の sandbox が {enabled: true, allowUnsandboxedCommands: false} でない"
                                      "（{'enabled': True}）",
    "approval_with_timeout": "節 gate: approval の節に期限（timeout・idle_timeout）を書いた",
    "fix_outside_blk_fix": "節 fix: AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash', 'Edit', 'Write']）",
    "measure_outside_blk_premises": "節 premises: AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash']）",
    "loop_body_timeout": "節 judge-loop の中の節 accept: bash の節の timeout が 1728000000 でない（120000）",
    "loop_no_max": "節 judge-loop: loop_group の max_iterations が 3 でない（None）",
    "loop_no_until_bash": "節 judge-loop: loop_group に until_bash が無い",
    "readonly_no_allowed_tools": "節 judge: AI の節に allowed_tools が無い",
    "readonly_with_edit": "節 judge: AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Edit']）",
    "script_no_timeout": "節 accept: script の節の timeout が 1728000000 でない（None）",
    "timeout_25days": "節 run: bash の節の timeout が 1728000000 でない（2160000000）",
}


def _is_deadline(v):
    return type(v) is int and v == DEADLINE      # True や "1728000000" は通さない


def _kind(node):
    for k in AI_KEYS + TIMED_KEYS + QUIET_KEYS:
        if k in node:
            return k
    return None


def _allowed_tools(place, nid):
    """(フォルダ, ファイル) の節 nid が持ってよい道具の集合。None は決まりの外（書く役）"""
    if place == WRITER[:2] and nid == WRITER[2]:
        return None
    if place == MEASURER[:2] and nid == MEASURER[2]:
        return MEASURE_TOOLS
    return READ_ONLY_TOOLS


def _check_node(node, where, place, out):
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
        if not (isinstance(sb, dict) and sb.get("enabled") is True and sb.get("allowUnsandboxedCommands") is False):
            out.append(f"{at}: AI の節の sandbox が {{enabled: true, allowUnsandboxedCommands: false}} でない（{sb!r}）")
        tools = node.get("allowed_tools")
        allowed = _allowed_tools(place, nid)
        if allowed is not None:
            if not isinstance(tools, list):
                out.append(f"{at}: AI の節に allowed_tools が無い（無ければ全部の道具を持つ）")
            elif not set(tools) <= allowed:
                out.append(f"{at}: AI の節の allowed_tools が {sorted(allowed)} の外を持つ"
                           f"（{sorted(set(tools) - allowed)}）")
        ss = node.get("settingSources", "（無し）")
        if not (ss == [] or ("skills" in node and ss == ["project"])):
            out.append(f"{at}: AI の節の settingSources が [] でない（{ss!r}。skills: を持つ節だけ [project] も可）")
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
        _check_nodes(g.get("nodes"), f"{at} の中の", place, out)


def _check_nodes(nodes, where, place, out):
    if not isinstance(nodes, list) or not nodes:
        out.append(f"{where}nodes が無い")
        return
    for n in nodes:
        _check_node(n, where, place, out)


def check_file(path: pathlib.Path) -> list:
    """1 本の工程の YAML の違反の文の一覧（空なら決まりを全部守っている）"""
    path = pathlib.Path(path)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    if not isinstance(doc, dict):
        return [f"{path.name}: 工程の YAML が表でない"]
    _check_nodes(doc.get("nodes"), f"{path.name}: ", (path.parent.name, path.name), out)
    return out


class YamlRulesCase(unittest.TestCase):
    def assertOneRule(self, found, part, what):
        """違反がちょうど 1 つで、その文面が part を含む（件数だけでは狙いの決まりが当たったか分からない）"""
        self.assertEqual([part in f for f in found], [True],
                         f"{what}: 違反はちょうど 1 つで {part!r} を含むはず: {found}")

    def test_each_bad_yaml_is_red(self):
        bad = sorted((TESTS / "yaml_bad").glob("*.yaml"))
        self.assertGreaterEqual(len(bad), 5)
        # 期待の無い見本・見本の無い期待を許さない
        self.assertEqual({p.stem for p in bad}, set(BAD_EXPECT))
        for p in bad:
            with self.subTest(p.name):
                self.assertOneRule(check_file(p), f"{p.name}: {BAD_EXPECT[p.stem]}", p.name)

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
            outside = "AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash', 'Edit', 'Write']）"
            for folder, name, want in (("blk-fix", "blk-fix.yaml", None), ("blk-judge", "blk-fix.yaml", outside),
                                       ("blk-fix", "other.yaml", outside)):
                p = pathlib.Path(tmp) / folder / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
                with self.subTest(f"{folder}/{name}"):
                    if want is None:
                        self.assertEqual(check_file(p), [])
                    else:
                        self.assertOneRule(check_file(p), f"{name}: 節 fix: {want}", f"{folder}/{name}")
            # blk-fix の中でも fix 以外の節は読むだけの道具に限る
            p = pathlib.Path(tmp) / "blk-fix" / "blk-fix.yaml"
            p.write_text(body.replace("id: fix", "id: accept-fix"), encoding="utf-8")
            self.assertOneRule(check_file(p), f"blk-fix.yaml: 節 accept-fix: {outside}", "blk-fix/accept-fix")

    def test_measurer_allowed_only_in_blk_premises(self):
        body = (TESTS / "yaml_bad" / "measure_outside_blk_premises.yaml").read_text(encoding="utf-8")
        read_only = "AI の節の allowed_tools が ['Glob', 'Grep', 'Read'] の外を持つ（['Bash']）"
        with tempfile.TemporaryDirectory() as tmp:
            for folder, name, want in (("blk-premises", "blk-premises.yaml", None),
                                       ("blk-judge", "blk-premises.yaml", read_only),
                                       ("blk-premises", "other.yaml", read_only),
                                       ("blk-fix", "blk-fix.yaml", read_only)):   # 書く役の置き場でも節の名前が違えば外
                p = pathlib.Path(tmp) / folder / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
                with self.subTest(f"{folder}/{name}"):
                    if want is None:
                        self.assertEqual(check_file(p), [])
                    else:
                        self.assertOneRule(check_file(p), f"{name}: 節 premises: {want}", f"{folder}/{name}")
            p = pathlib.Path(tmp) / "blk-premises" / "blk-premises.yaml"
            # 測る役でも書く道具は外
            p.write_text(body.replace("[Read, Grep, Glob, Bash]", "[Read, Grep, Glob, Bash, Edit, Write]"), encoding="utf-8")
            self.assertOneRule(check_file(p), "blk-premises.yaml: 節 premises: AI の節の allowed_tools が "
                               "['Bash', 'Glob', 'Grep', 'Read'] の外を持つ（['Edit', 'Write']）", "premises + Edit")
            # blk-premises の中でも premises 以外の節は読むだけの道具に限る
            p.write_text(body.replace("id: premises", "id: premises-accept"), encoding="utf-8")
            self.assertOneRule(check_file(p), f"blk-premises.yaml: 節 premises-accept: {read_only}", "premises-accept")

    def test_setting_sources_project_only_with_skills(self):
        base = ("nodes:\n  - id: judge\n    prompt: 判定せよ\n    allowed_tools: [Read]\n"
                "    sandbox: {enabled: true, allowUnsandboxedCommands: false}\n"
                "    idle_timeout: 1728000000\n    output_format: {type: object}\n")
        with tempfile.TemporaryDirectory() as tmp:
            bad = "w.yaml: 節 judge: AI の節の settingSources が [] でない"
            for extra, want in (("    settingSources: []\n", None),
                                ("    skills: [x]\n    settingSources: [project]\n", None),
                                ("    skills: [x]\n    settingSources: []\n", None),
                                ("    settingSources: [project]\n", f"{bad}（['project']。"),
                                ("    skills: [x]\n    settingSources: [project, user]\n", f"{bad}（['project', 'user']。"),
                                ("    skills: [x]\n", f"{bad}（'（無し）'")):
                p = pathlib.Path(tmp) / "w.yaml"
                p.write_text(base + extra, encoding="utf-8")
                with self.subTest(extra):
                    if want is None:
                        self.assertEqual(check_file(p), [])
                    else:
                        self.assertOneRule(check_file(p), want, extra)


def _is_ai(node):
    return _kind(node) in AI_KEYS or _kind(node) == "include"   # include は中に AI の節を持ちうる


def _ancestors(nid, by_id):
    seen, todo = set(), list(by_id[nid].get("depends_on") or [])
    while todo:
        d = todo.pop()
        if d in by_id and d not in seen:
            seen.add(d)
            todo.extend(by_id[d].get("depends_on") or [])
    return seen


class RoleSessionCase(unittest.TestCase):
    """役の節は、CLAUDE.md を読んだ前の会話を引き継がない（settingSources: [] が効くのは新しい会話だけ）。

    輪の中の役に context: fresh は書けない（受け付けが拒んだ時の同じ会話での出し直しが壊れる）。代わりに形で守る:
    役はブロックの輪（loop_group）の中に居て、ブロックの中で役より前（depends_on を辿った先）に AI の節も include も無い。
    Archon は輪の 1 周目をいつも新しい会話で起こし（dag-executor.ts:5069）、include の入口の節は外の会話を
    引き継がない（dag-executor.ts:10417-10427）。2 周目からの出し直しは、1 周目の settingSources: [] の会話の続き。
    """

    def test_role_is_first_ai_node_in_its_block_loop(self):
        for folder, name, rid in ROLES:
            with self.subTest(f"{folder}/{rid}"):
                doc = yaml.safe_load((ROOT / folder / name).read_text(encoding="utf-8"))
                top = {n["id"]: n for n in doc["nodes"]}
                loops = [n for n in doc["nodes"] if _kind(n) == "loop_group"
                         and any(m.get("id") == rid for m in n["loop_group"]["nodes"])]
                self.assertEqual(len(loops), 1, f"{rid} が輪の中にちょうど 1 つ居ない")
                grp = loops[0]
                inner = {m["id"]: m for m in grp["loop_group"]["nodes"]}
                role = inner[rid]
                self.assertEqual(role.get("settingSources"), [])
                self.assertNotIn("context", role, "輪の中の役に context を書くと同じ会話での出し直しが壊れる")
                before = [inner[a] for a in _ancestors(rid, inner)] + [top[a] for a in _ancestors(grp["id"], top)]
                self.assertEqual([n["id"] for n in before if _is_ai(n)], [],
                                 f"{rid} より前に AI の節か include が在る（前の会話を引き継ぐ恐れ）")
                others = [m["id"] for m in inner.values() if m["id"] != rid and _is_ai(m)]
                self.assertEqual(others, [], f"{rid} の輪に別の AI の節が在る")


if __name__ == "__main__":
    unittest.main()
