"""blk-material（素材集め。本線 BLOCKS.md の R3。差し込み口 material）の検査。

ブロックが回す役の節は、写しの graph の P1 の目 9 本（p1.local_review ほか）と、素材集めに属す P0 の 2 本
（p0.prior_decisions・p0.purpose_review）。回すかどうかは盤面の ready（写しの条件 cond）だけで決まり、ブロックは条件を持たない
（判定から入る run の 1 周目は写しの not_request_entry などで na。条件はそのまま）。

盤面は linekit の種（dev/target-seed/）で作る。線 A の本物の表（darkfactory/nodes.json）は P1 の目を absent に持つので、
試験は提案の行（PROPOSED_ROWS。報告の nodes.json の差分と同じ）を当てた表を entry.load_table の差し替えで渡す
（盤面の state.works.table_sha もその表の sha。entry.open_board は同じ表で開く）。
- normal: 判定から入らない run（依頼を積まない create）。作業ツリーに未コミットの直し（stats.py）と新しい手順書（notes.md）を
  置き、p0.base・CI（宣言）・並行 PR・前提まで進めた盤面。P1 の目 9 本と p0.prior_decisions が待つ
- entry:  entry.start（判定から入る 1 周の run）。P1 の目は写しの条件で na、p0.prior_decisions だけが待つ
1 つの盤面を作るのに数秒かかるので、種類ごとに 1 度だけ作って置き場ごと控え、試験ごとに同じパスへ戻す（盤面は絶対パスを持つ）。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
BLK = ROOT / "blk-material"
sys.dont_write_bytecode = True
for _p in (str(TESTS), str(CORE), str(BLK / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import accept  # noqa: E402
import board as board_mod  # noqa: E402
from board import BoardGap, DiskBoard, NodeTable, base_output  # noqa: E402
import engine.util as engine_util  # noqa: E402
import entry  # noqa: E402
import linekit  # noqa: E402
import material  # noqa: E402
import node_marker  # noqa: E402
import test_entry as TE  # noqa: E402
import hermetic  # noqa: E402

LINE = "darkfactory"
WHERE = "blk-material"
# 提案の行（報告の nodes.json の差分と同じ）。p0.purpose_review は absent のまま（条件が p0.purpose の出力を読むので、
# p0.purpose がラインに無い間は role にできない——盤面の settle が測れずに落ちる）
PROPOSED_ROWS = {nid: {"by": "role", "where": WHERE} for nid in (
    "p0.prior_decisions", "p1.local_review", "p1.consistency_bypass", "p1.hygiene", "p1.external_standards",
    "p1.procedure_trace", "p1.gate_efficacy", "p1.test_double_fidelity", "p1.main_path_observation", "p1.provenance")}
LENSES = [r for r, n in material.ROLES.items() if n.startswith("p1.")]
YAML_PATH = BLK / "blk-material.yaml"
# 網を閉じ、読むだけの口 works-gh だけを sandbox の外に出す役（graphloops の investigator と、回す側の会話で走る局所レビュー）
EXCLUDED_ROLES = {"prior-decisions", "external-standards", "procedure-trace", "local-review"}


# 目的の節が無い表（素材集めの「目的の文が無い run」の道を見る。ラインは p0.purpose を blk-purpose で持つので、ここで戻す）
NO_PURPOSE_ROWS = {"p0.purpose": {"by": "absent", "reason": "目的の文の無い表（試験）", "comes_with": "blk-purpose"},
                   "p0.purpose_review": {"by": "absent", "reason": "目的の文の無い表（試験）", "comes_with": "blk-purpose"}}


def proposed_table() -> NodeTable:
    raw = json.loads((ROOT / LINE / "nodes.json").read_text(encoding="utf-8"))
    for nid, row in {**PROPOSED_ROWS, **NO_PURPOSE_ROWS}.items():
        raw["nodes"][nid] = dict(row)
    d = pathlib.Path(tempfile.mkdtemp(prefix="works-mat-table-"))
    (d / "nodes.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    t = NodeTable.load(d / "nodes.json")
    shutil.rmtree(d, ignore_errors=True)
    return t


TABLE = proposed_table()
# 目的の節がラインに入った後の表（p0.purpose を blk-purpose の役、p0.purpose_review を素材集めの役に）。目的の審査の筋を通す
PURPOSE_ROWS = {"p0.purpose": {"by": "role", "where": "blk-purpose"}, "p0.purpose_review": {"by": "role", "where": WHERE}}


def purpose_table() -> NodeTable:
    raw = json.loads((ROOT / LINE / "nodes.json").read_text(encoding="utf-8"))
    for nid, row in {**PROPOSED_ROWS, **PURPOSE_ROWS}.items():
        raw["nodes"][nid] = dict(row)
    d = pathlib.Path(tempfile.mkdtemp(prefix="works-mat-table-"))
    (d / "nodes.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    t = NodeTable.load(d / "nodes.json")
    shutil.rmtree(d, ignore_errors=True)
    return t


PURPOSE_TABLE = purpose_table()
_TABLE_NOW = [TABLE]   # 試験の表の差し替え（PurposeCase だけが PURPOSE_TABLE に替える）


def _patched_table(line: str = LINE, *a, **kw):
    if line != LINE:
        raise BoardGap(f"試験の表は {LINE} だけ（{line!r}）")
    return _TABLE_NOW[0]


# ---------------------------------------------------------------- 役の返答の見本（写しの schema と post_check に通る形）
def _clean(what="差分 stats.py の 1 行と新しい notes.md を読んだ"):
    return {"status": "clean", "checked": what}


def good_reply(nid: str) -> dict:
    graph = board_mod.graph_expanded()
    if nid == "p1.local_review":
        rows = [{"skill": e["skill"], "items": [], "failed": "起こしたが所見なし（差分 stats.py の 1 行を見た）", "invoked": True}
                for e in graph["nodes"][nid]["skills"]]
        return {"material": _clean(), "simplify_carried": False, "findings": rows}
    if nid == "p1.consistency_bypass":
        return {"consistency": _clean(), "bypass": _clean(), "findings": [], "bypass_findings": [],
                "seen": "stats.py と test_stats.py の全部", "unseen": "無し（リポジトリは 2 ファイル）"}
    if nid == "p1.hygiene":
        return {"findings": [], "seen": "差分の全部（stats.py の 1 行と notes.md）"}
    if nid == "p1.external_standards":
        return {"material": _clean(), "findings": [], "seen": "statistics の公式文書", "unseen": "無し", "web_refetched": True,
                "rankings": [{"problem": "算術平均の分母", "source": "https://docs.python.org/3/library/statistics.html",
                              "ranked": ["statistics.fmean を使う", "sum(xs) / len(xs) を自前で書く"],
                              "diff_at": "sum(xs) / len(xs) を自前で書く",
                              "why_not_higher": "種は標準の関数に寄せる前の形で、分母の取り違えだけを直す差分だから"}]}
    if nid == "p1.procedure_trace":
        return {"material": _clean("notes.md の手順を読み、書かれたコマンドを写しで動かした"), "findings": [], "unmeasured": []}
    if nid == "p1.gate_efficacy":
        return {"material": {"status": "not_run", "reason": "差分は検証ゲートを足していない——撃てる腕が無い"}, "arms": []}
    if nid == "p1.test_double_fidelity":
        return {"material": _clean("代役は無い（test_stats.py は実物の関数を呼ぶ）"), "mismatches": []}
    if nid == "p1.main_path_observation":
        return {"material": _clean("python3 -c で mean を 1 回呼んだ"), "observed": [{"path": "stats.mean([1, 2, 3])", "value": "2.0"}]}
    if nid == "p1.provenance":
        return {"material": _clean("差分に『正本は X』の主張は無い"), "claims": []}
    if nid == "p0.prior_decisions":
        return {"material": _clean("決定記録（ADR・台帳・issue）はリポジトリに無い"), "checked": True,
                "searched": ["リポジトリの全部（2 ファイル）"], "settled": []}
    raise KeyError(nid)


# ---------------------------------------------------------------- 盤面
PURPOSE_REPLY = {"purpose_text": "標本分散の分母の取り違えを直す", "source": "③writer の要約",
                 "known_weaknesses": [], "source_files": []}


def _build_purpose(into: pathlib.Path):
    """目的の節がラインに在る盤面（PURPOSE_TABLE）。p0.purpose は writer の要約（③）で、1 周目なので目的の審査が待つ"""
    bd, repo = _build_normal(into, table=PURPOSE_TABLE)
    TE.launch(bd, "p0.purpose")
    got = entry.take(bd, "p0.purpose", PURPOSE_REPLY, repo)
    assert got["ok"], got
    return bd, repo


def _build_normal(into: pathlib.Path, table: NodeTable = None, touch_test: bool = False):
    table = table or TABLE
    repo = linekit.seed_repo(into / "repo", declared=True)
    p = repo / "stats.py"
    p.write_text(p.read_text(encoding="utf-8").replace("(len(xs) - 1)", "len(xs)"), encoding="utf-8")
    if touch_test:   # 検証ゲート（テスト）も変える差分（ゲートの検算の役が『条件外』を名乗れない形）
        t = repo / "test_stats.py"
        t.write_text(t.read_text(encoding="utf-8") + "\n# 試験の 1 行\n", encoding="utf-8")
    (repo / "notes.md").write_text("# 手順\n\n1. python3 -m unittest test_stats\n", encoding="utf-8")
    bd = into / "art" / "board"
    b = DiskBoard.create(bd, repo=repo, table=table, inputs={}, request_text="素材集めの試験", stop_after_round=1,
                         **entry.open_kwargs(LINE, table))
    b.settle()
    inst = TE.pending_inst(b, "p0.base")
    b.mark_launched("p0.base", inst["attempts"])
    b.accept("p0.base", base_output(repo, ""))
    entry._drain(b, b.settle(), test_cmd="")
    # 種は remote を持たない forge の無い run: 並行 PR は機械が条件外にする（任せ先の役は無い）
    for nid, reply in (("p0.premises", TE.PREMISES_REPLY),):
        TE.launch(bd, nid)
        got = entry.take(bd, nid, reply, repo)
        assert got["ok"], got
    return bd, repo


def _build_entry(into: pathlib.Path):
    repo = linekit.seed_repo(into / "repo", declared=True)
    req = TE.request_file(into / "req" / "request.json")
    raw = {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "", "adapter": "", "policy_md": ""}
    bd = into / "art" / "board"
    entry.start(bd, repo, raw, run_id="run-mat")
    for nid, reply in (("p0.parallel_pr", TE.pr_reply()), ("p0.premises", TE.PREMISES_REPLY)):
        if nid in entry.open_board(bd).settle()["ready"]:
            TE.launch(bd, nid)
            got = entry.take(bd, nid, reply, repo)
            assert got["ok"], got
    linekit.pre_judge(bd, repo, only=("p0.purpose",))   # 目的の文（p1.consistency_bypass・p1.external_standards が待つ）
    return bd, repo


class Boards:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.root = pathlib.Path(self._tmp.name)
        self.made = {}

    def fresh(self, kind):
        into, snap = self.root / kind, self.root / f"{kind}.snap"
        if kind not in self.made:
            self.made[kind] = {"normal": _build_normal, "entry": _build_entry, "purpose": _build_purpose,
                               "gated": lambda d: _build_normal(d, touch_test=True)}[kind](into)
            shutil.copytree(into, snap, symlinks=True)
        else:
            shutil.rmtree(into)
            shutil.copytree(snap, into, symlinks=True)
        return self.made[kind]

    def cleanup(self):
        self._tmp.cleanup()


class _Case(unittest.TestCase):
    boards = None

    @classmethod
    def setUpClass(cls):
        cls._table = mock.patch.object(entry, "load_table", _patched_table)
        cls._table.start()
        cls._home = tempfile.TemporaryDirectory(dir=linekit.work_home())
        cls._env = mock.patch.dict("os.environ", {"WORKS_ADAPTER_HOME": str(pathlib.Path(cls._home.name) / "adapter-home")})
        cls._env.start()
        if _Case.boards is None:
            _Case.boards = Boards()

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()
        cls._table.stop()
        cls._home.cleanup()

    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD

    def tearDown(self):
        engine_util.GIT_CWD = self._old_cwd

    def board(self, kind="normal"):
        self.bd, self.repo = _Case.boards.fresh(kind)
        return self.bd, self.repo

    def run_role(self, role, reply=None, adapter="optional", purpose_file=""):
        """prep → take（役の代わりに見本の返答を渡す）"""
        got = material.prep(self.bd, role, self.repo, purpose_file)
        self.assertTrue(pathlib.Path(got["prompt_file"]).is_file(), got)
        nid = material.ROLES[role]
        return material.take(self.bd, role, reply if reply is not None else good_reply(nid), self.repo, adapter)


def tearDownModule():
    if _Case.boards is not None:
        _Case.boards.cleanup()


# ---------------------------------------------------------------- 表と YAML の形（盤面なし）
class ShapeCase(unittest.TestCase):
    def test_roles_are_the_r3_role_nodes(self):
        """ROLES は写しの graph の素材集めの役の節の全部（p1 の driver の 2 節を除く P1 と、p0.prior_decisions・p0.purpose_review）"""
        g = board_mod.graph_expanded()
        want = {nid for nid, n in g["nodes"].items() if nid.startswith("p1.") and n.get("run_by") != "driver"}
        want |= {"p0.prior_decisions", "p0.purpose_review"}
        self.assertEqual(set(material.ROLES.values()), want)
        self.assertEqual(len(material.ROLES), len(set(material.ROLES.values())))
        for role in material.ROLES:
            self.assertTrue(node_marker.parse(f"works-node: {role}"), role)

    def test_proposed_rows_pass_the_table_check(self):
        self.assertEqual(TABLE.check(board_mod.graph_expanded(), board_mod.GRAPH_SHA), [])
        self.assertEqual(TABLE.nodes["p0.purpose_review"].by, "absent")

    def test_sandbox_shapes_are_the_rule_table_shapes(self):
        """任せ先の sandbox は graphloops の任せ先の形（test_yaml_rules の DELEGATE_SANDBOX）、investigator と局所レビューは
        MATERIAL_SANDBOX。Bash を持つ役は全部、印に旗 no-tree-write（包みが本物の作業ツリーを守る）"""
        import test_yaml_rules as R
        self.assertEqual(material.SANDBOX["delegate"], R.DELEGATE_SANDBOX)
        self.assertEqual(material.SANDBOX["investigator"], R.MATERIAL_SANDBOX)
        self.assertEqual(material.SANDBOX["skill"], R.MATERIAL_SANDBOX)
        for role, tools in material.TOOLS.items():
            with self.subTest(role):
                self.assertEqual("Bash" in tools, "no-tree-write" in material.FLAGS.get(role, ()))

    def test_output_format_is_marked_copy_schema(self):
        for role, nid in material.ROLES.items():
            with self.subTest(role):
                of = material.output_format(role)
                self.assertEqual(node_marker.strip(of), accept.role_schema(nid))
                mark = node_marker.parse(of["description"])
                self.assertEqual((mark["name"], mark["cont"], set(mark["flags"])), (role, None, set(material.FLAGS.get(role, ()))))

    def test_yaml_loops(self):
        doc = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
        self.assertEqual(doc["name"], "blk-material")
        self.assertEqual((doc["returns"], doc["outcome_field"]), ("collect", "ok"))
        self.assertEqual(set(doc["inputs"]), {"adapter", "purpose_file"})
        nodes = {n["id"]: n for n in doc["nodes"]}
        route = nodes["mat-route"]
        self.assertEqual((route["script"], route["timeout"]), ("route", 1728000000))
        self.assertEqual(set(route["output_format"]["required"]),
                         {"ok", "stopped", "why", "snapshot_file", *(material.route_key(r) for r in material.ROLES)})
        loops = [n for n in doc["nodes"] if "loop_group" in n]
        self.assertEqual({n["id"] for n in loops}, {f"{r}-loop" for r in material.ROLES})
        for role in material.ROLES:
            with self.subTest(role):
                lp = nodes[f"{role}-loop"]
                self.assertEqual(lp["depends_on"], ["mat-route"])
                self.assertEqual(lp["when"], f"$mat-route.output.{material.route_key(role)} == true")
                g = lp["loop_group"]
                self.assertEqual(g["max_iterations"], material.GIVE_UP_AFTER)
                self.assertIs(g["fresh_context"], False)   # 拒否の後の出し直しは同じ会話（graphloops の --resume）
                self.assertEqual(g["until_bash"], f"test ${role}-accept.output.done = true")
                inner = {n["id"]: n for n in g["nodes"]}
                self.assertEqual(set(inner), {f"{role}-prep", role, f"{role}-accept"})
                prep, ai, acc = inner[f"{role}-prep"], inner[role], inner[f"{role}-accept"]
                self.assertEqual((prep["script"], prep["timeout"], prep["with"]),
                                 ("prep", 1728000000, {"role": role, "purpose_file": "$INPUTS.purpose_file"}))
                self.assertEqual(set(prep["output_format"]["required"]), set(material.PREP_KEYS))
                self.assertEqual(set(prep["output_format"]["properties"]), set(material.PREP_KEYS))
                self.assertEqual(ai["command"], role)
                self.assertTrue((BLK / "commands" / f"{role}.md").is_file())
                self.assertEqual(ai["idle_timeout"], 1728000000)
                self.assertEqual(ai["depends_on"], [f"{role}-prep"])
                # 盤面が止まった後の周（同じ波の他の目が止めた）は役を起こさない。受け付けは飛ばした役の返答（null）で
                # 止まった旨の done を出し、輪を抜ける
                self.assertEqual(ai["when"], f"${role}-prep.output.stopped == false")
                self.assertEqual(ai["output_format"], material.output_format(role))
                self.assertEqual(ai["allowed_tools"], list(material.TOOLS[role]))
                self.assertEqual(ai.get("settingSources"), list(material.SETTING_SOURCES.get(role, ())))
                self.assertEqual(ai.get("skills"), material.SKILLS.get(role))
                self.assertEqual(ai["sandbox"], material.SANDBOX[material.POSTURE[role]])
                self.assertEqual((acc["script"], acc["timeout"], acc["depends_on"]),
                                 ("accept", 1728000000, [f"{role}-prep", role]))
                self.assertEqual(acc["trigger_rule"], "none_failed_min_one_success")
                self.assertEqual(acc["with"], {"role": role, "reply": {"from": f"${role}.output", "if_skipped": None},
                                               "adapter": "$INPUTS.adapter"})
                self.assertEqual(set(acc["output_format"]["required"]), {"ok", "done", "give_up", "reason", "reason_file"})
                self.assertIn("stopped", acc["output_format"]["properties"])
        col = nodes["collect"]
        self.assertEqual(set(col["depends_on"]), {"mat-route", *(f"{r}-loop" for r in material.ROLES)})
        self.assertEqual(col["trigger_rule"], "none_failed_min_one_success")
        self.assertEqual(set(col["output_format"]["required"]), set(material.EXIT_KEYS))

    def test_commands_read_prompt_file_or_paste(self):
        """役の指示書は prep が描いた本線の指示書を読む（遮断の役だけは本文を貼る。道具を持たない）"""
        for role in material.ROLES:
            with self.subTest(role):
                text = (BLK / "commands" / f"{role}.md").read_text(encoding="utf-8")
                if role in material.PASTE:
                    self.assertIn(f"${role}-prep.output.prompt_text", text)
                    self.assertNotIn("prompt_file", text)
                    self.assertEqual(material.TOOLS[role], ())
                else:
                    self.assertIn(f"${role}-prep.output.prompt_file", text)
                self.assertNotIn("$LOOP_PREV", text)   # 拒否の理由は prep が指示書の頭に置く（R44）

    def test_no_role_opens_a_host_network(self):
        """網: 任せ先（graphloops の任せ先と同じ `*`）のほかは、どの役もどの宛先にも網を開けない（GitHub も）。
        Bash を持つ役は網を閉じ、sandbox の外に出すのは読むだけの口 works-gh だけ（graphloops の investigator の SANDBOX_BASE と
        同じ考え。Archon が捨てる strictAllowlist は包みが足す——test_adapter の NetworkCase）"""
        doc = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
        ais = {n["id"]: n for lp in doc["nodes"] if "loop_group" in lp for n in lp["loop_group"]["nodes"] if "command" in n}
        self.assertEqual(set(ais), set(material.ROLES))
        for role, ai in ais.items():
            with self.subTest(role):
                sb = ai["sandbox"]
                self.assertNotIn("github", json.dumps(sb))
                net = sb.get("network")
                if material.POSTURE[role] == "delegate":
                    self.assertEqual(net["allowedDomains"], ["*"])
                    continue
                self.assertNotIn("enableWeakerNetworkIsolation", sb)
                if "Bash" in material.TOOLS[role]:
                    self.assertEqual(net, {"allowedDomains": []})
                    self.assertEqual(sb["excludedCommands"], ["works-gh:*"])
                else:
                    self.assertIsNone(net)
                    self.assertNotIn("excludedCommands", sb)

    def test_works_gh_exclusion_is_gated_by_no_post(self):
        """sandbox の外に出る works-gh は、読む形だけを通す口のまま: 除外を持つ役は印に旗 no-post（包みが口を PATH の頭に置き、
        本物の gh を permissions.deny で拒む）を持ち、除外は口の名だけ（gh は外に出さない）。口は書く形を本物の gh に渡さない。
        包みはこの役の sandbox の網を strictAllowlist で閉じる"""
        sys.path.insert(0, str(CORE))
        import adapter
        bindir = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(bindir), True)
        gh, log = bindir / "gh", bindir / "gh.log"
        gh.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$FAKE_GH_LOG\"\n")
        gh.chmod(0o755)
        env = hermetic.child_env(PATH=f"{bindir}{os.pathsep}{os.path.dirname(sys.executable)}{os.pathsep}/usr/bin:/bin", FAKE_GH_LOG=str(log), PYTHONDONTWRITEBYTECODE="1")
        env.pop("WORKS_GH_ACTIVE", None)
        shim = adapter.NO_POST_BIN / "works-gh"
        self.assertEqual({r for r in material.ROLES if "excludedCommands" in material.SANDBOX[material.POSTURE[r]]},
                         EXCLUDED_ROLES)
        for role in material.ROLES:
            sb = material.SANDBOX[material.POSTURE[role]]
            if "excludedCommands" not in sb:
                continue
            with self.subTest(role):
                self.assertEqual(sb["excludedCommands"], ["works-gh:*"])
                self.assertIn("no-post", material.FLAGS[role])
                argv = ["--json-schema", json.dumps(material.output_format(role)), "--settings", json.dumps({"sandbox": sb})]
                out, strict = adapter.strict_network(argv)
                self.assertIs(strict, True)
                self.assertEqual(json.loads(out[-1])["sandbox"]["network"], {"allowedDomains": [], "strictAllowlist": True})
        for args in (["pr", "view", "12", "-R", "o/r"], ["repo", "view", "o/r"]):
            r = subprocess.run([str(shim), *args], env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(r.returncode, 0, r.stderr)
        before = log.read_text()
        for args in (["issue", "create", "-R", "o/r", "-t", "x"], ["api", "repos/o/r/issues", "-X", "POST"],
                     ["pr", "comment", "12", "-R", "o/r", "-b", "x"], ["pr", "merge", "12", "-R", "o/r"]):
            with self.subTest(args=args):
                r = subprocess.run([str(shim), *args], env=env, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(log.read_text(), before)   # 書く形は本物の gh を起こさない

    def test_command_roles_use_bare_works_gh_and_web_tools(self):
        """網を閉じた Bash の役の指示: gh は素の名 works-gh で 1 つのコマンドとして打たせ（除外に当たる形。変数・つなぎは sandbox の
        中で走り網に出られない）、issue・検索・Web は WebFetch・WebSearch で読ませる"""
        for role in EXCLUDED_ROLES:
            with self.subTest(role):
                text = (BLK / "commands" / f"{role}.md").read_text(encoding="utf-8")
                self.assertIn("`works-gh`", text)
                self.assertIn("WebFetch・WebSearch で読め", text)
                self.assertNotIn("$WORKS_GH", text)
                self.assertNotIn("網は GitHub", text)

    def test_scripts_missing_env_exit_2(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "ARTIFACTS_DIR"}
        for name in ("route", "prep", "accept", "collect"):
            with self.subTest(name):
                p = subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], capture_output=True, text=True, encoding="utf-8",
                                   env=env, cwd=str(ROOT))
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertEqual(p.stdout, "")
                self.assertIn("環境変数が無い", p.stderr)


# ---------------------------------------------------------------- 盤面の上
class RouteCase(_Case):
    def test_normal_run_routes_every_due_lens(self):
        bd, repo = self.board("normal")
        got = material.route(bd, repo, "optional")
        self.assertEqual((got["ok"], got["stopped"]), (True, False))
        for role in material.ROLES:
            with self.subTest(role):
                self.assertIs(got[material.route_key(role)], role != "purpose-review")
        self.assertIn("p0.purpose_review", got["why"])
        snap = json.loads(pathlib.Path(got["snapshot_file"]).read_text(encoding="utf-8"))
        self.assertTrue(set(accept.TREE_KEYS) <= set(snap))

    def test_entry_round_keeps_graph_conditions(self):
        """判定から入る 1 周目: P1 の目は写しの条件で na（ブロックは条件を持たない）。p0.prior_decisions は 1 周目なので回す"""
        bd, repo = self.board("entry")
        got = material.route(bd, repo, "optional")
        self.assertFalse(got["stopped"])
        for role in LENSES:
            with self.subTest(role):
                self.assertIs(got[material.route_key(role)], False)
        self.assertIs(got["prior_decisions"], True)
        b = entry.open_board(bd)
        for role in LENSES:
            self.assertIn(material.ROLES[role], b.rd["na"])
        self.assertIn("判定から入る", got["why"])

    def test_route_keeps_first_snapshot(self):
        bd, repo = self.board("normal")
        first = pathlib.Path(material.route(bd, repo, "optional")["snapshot_file"]).read_bytes()
        (repo / "stray.txt").write_text("後から\n", encoding="utf-8")
        again = pathlib.Path(material.route(bd, repo, "optional")["snapshot_file"]).read_bytes()
        self.assertEqual(first, again)

    def test_wrapped_run_without_ticket_stops_board(self):
        """包みを宣言した run（adapter 空）で切符が無ければ、旗 no-tree-write の役を起こさずに盤面を止める"""
        bd, repo = self.board("normal")
        got = material.route(bd, repo, "")
        self.assertTrue(got["stopped"])
        self.assertFalse(any(got[material.route_key(r)] for r in material.ROLES))
        st = entry.open_board(bd, allow_halted=True).state
        self.assertEqual((st.get("stop") or st.get("halted") or {}).get("by"), material.FENCE_BY)

    def test_bad_adapter_word_is_wiring_error(self):
        bd, repo = self.board("normal")
        with self.assertRaises(BoardGap):
            material.route(bd, repo, "maybe")


class PrepCase(_Case):
    def test_prompt_is_mainline_prompt_rendered_from_board(self):
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        got = material.prep(bd, "consistency-bypass", repo, "")
        text = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")
        b = entry.open_board(bd)
        self.assertIn("お前は inspector。整合性の確認と、標準機構の迂回の検査を", text)
        self.assertIn(b.loop_state["diff_file"], text)
        self.assertIn("返答はこの JSON Schema に合う JSON だけ", text)
        self.assertEqual((got["node"], got["attempt"], got["already"], got["prompt_text"]), ("p1.consistency_bypass", 1, False, ""))
        self.assertTrue(b.rd["instances"]["p1.consistency_bypass"].get("launched_at"))

    def test_local_review_prompt_carries_declared_lenses(self):
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        text = pathlib.Path(material.prep(bd, "local-review", repo, "")["prompt_file"]).read_text(encoding="utf-8")
        for e in board_mod.graph_expanded()["nodes"]["p1.local_review"]["skills"]:
            self.assertIn(e["skill"], text)
        # fork の /code-review の返り方（受け付けが記録から戻す・起こし直させない・旗の綴りを args に書かせない）の読み替え
        self.assertTrue(text.rstrip("\n").endswith(material.LENS_FORK_NOTE), text[-400:])

    def test_isolated_role_gets_pasted_prompt(self):
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        got = material.prep(bd, "hygiene", repo, "")
        self.assertIn("len(xs)", got["prompt_text"])            # 差分の本文
        self.assertIn("お前は文脈を持たない読み手", got["prompt_text"])
        self.assertEqual(got["prompt_text"], pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8"))

    def test_purpose_missing_is_said_not_invented(self):
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        text = pathlib.Path(material.prep(bd, "external-standards", repo, "")["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(material.PURPOSE_MISSING, text)

    def test_purpose_file_fills_absent_purpose(self):
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        pf = self.bd.parent / "purpose.json"
        pf.write_text(json.dumps({"purpose_text": "平均と clamp の既知のバグを直す", "source": "②計画・タスク記述",
                                  "known_weaknesses": ["分母が 0 の列は扱わない"], "source_files": []}, ensure_ascii=False),
                      encoding="utf-8")
        text = pathlib.Path(material.prep(bd, "external-standards", repo, str(pf))["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("平均と clamp の既知のバグを直す", text)
        self.assertIn("分母が 0 の列は扱わない", text)
        self.assertNotIn(material.PURPOSE_MISSING, text)

    def test_prep_for_node_not_waiting_is_wiring_error(self):
        bd, repo = self.board("entry")
        material.route(bd, repo, "optional")
        with self.assertRaises(BoardGap):
            material.prep(bd, "hygiene", repo, "")


class TakeCase(_Case):
    def test_all_roles_then_collect(self):
        bd, repo = self.board("normal")
        r = material.route(bd, repo, "optional")
        run = [role for role in material.ROLES if r[material.route_key(role)]]
        for role in run:
            with self.subTest(role):
                got = self.run_role(role)
                self.assertEqual((got["ok"], got["done"], got["give_up"]), (True, True, False), got)
        out = material.collect(bd)
        self.assertEqual(set(out), set(material.EXIT_KEYS))
        self.assertTrue(out["ok"], out)
        b = entry.open_board(bd)
        self.assertEqual({n for n in material.ROLES.values() if n in b.rd["done"]}, {material.ROLES[x] for x in run})
        self.assertNotIn("p0.purpose_review", b.rd["done"])
        self.assertEqual(b.node_state("p1.worktree_after"), "done")
        self.assertEqual(b.record["materials"]["local_review"]["status"], "clean")

    def test_rejected_reply_retries_then_gives_up(self):
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        bad = good_reply("p1.provenance")
        bad["claims"] = "壊れた"
        before = TE.board_shas(bd / "out") if (bd / "out").exists() else {}
        for i in range(1, material.GIVE_UP_AFTER + 1):
            got = self.run_role("provenance", bad)
            self.assertFalse(got["ok"])
            self.assertIn("型に合わない", got["reason"])
            self.assertEqual(got["done"], i == material.GIVE_UP_AFTER)
            self.assertEqual(got["give_up"], i == material.GIVE_UP_AFTER)
        again = material.prep(bd, "provenance", repo, "")
        self.assertTrue(pathlib.Path(again["prompt_file"]).read_text(encoding="utf-8").startswith(material.REJECT_HEADING))
        self.assertTrue(again["already"])
        self.assertEqual(TE.board_shas(bd / "out") if (bd / "out").exists() else {}, before)
        out = material.collect(bd)
        self.assertFalse(out["ok"])
        self.assertIn("p1.provenance", out["reason"])
        st = entry.open_board(bd, allow_halted=True).state
        self.assertEqual((st.get("stop") or st.get("halted") or {}).get("by"), material.STOP_BY)

    def test_tree_change_rejects_and_names_peers(self):
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        material.prep(bd, "hygiene", repo, "")
        material.prep(bd, "provenance", repo, "")
        (repo / "stray.txt").write_text("役が書いた\n", encoding="utf-8")
        got = material.take(bd, "provenance", good_reply("p1.provenance"), repo, "optional")
        self.assertFalse(got["ok"])
        self.assertTrue(got["reason"].startswith("読むだけの役が作業ツリーを変えた"), got["reason"])
        self.assertIn("stray.txt", got["reason"])
        self.assertIn("p1.hygiene", got["reason"])   # 同じ波で起きている役（変えたのがこの役とは限らない）
        (repo / "stray.txt").unlink()
        got = material.take(bd, "provenance", good_reply("p1.provenance"), repo, "optional")
        self.assertTrue(got["ok"], got)

    def test_unreadable_reply_counts_as_reject(self):
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        material.prep(bd, "hygiene", repo, "")
        got = material.refuse(bd, "hygiene", "返答が JSON として読めない")
        self.assertEqual((got["ok"], got["done"]), (False, False))

    def test_wrapped_run_requires_fenced_launch(self):
        """包みを宣言した run（adapter 空）: 旗 no-tree-write の役の起動に包みの柵が掛かった記録が無ければ、受けずに盤面を止める"""
        bd, repo = self.board("normal")
        import ticket
        ticket.write(bd, repo, "run-mat")
        r = material.route(bd, repo, "")
        self.assertFalse(r["stopped"], r)
        got = self.run_role("provenance", adapter="")
        self.assertEqual((got["ok"], got["done"]), (False, True))
        self.assertIn("柵", got["reason"])
        st = entry.open_board(bd, allow_halted=True).state
        self.assertEqual((st.get("stop") or st.get("halted") or {}).get("by"), material.FENCE_BY)

    def test_unflagged_role_needs_no_fence(self):
        bd, repo = self.board("normal")
        import ticket
        ticket.write(bd, repo, "run-mat")
        material.route(bd, repo, "")
        self.assertNotIn("consistency-bypass", material.FLAGS)
        got = self.run_role("consistency-bypass", adapter="")
        self.assertTrue(got["ok"], got)

    def test_entry_round_prior_decisions_only(self):
        bd, repo = self.board("entry")
        material.route(bd, repo, "optional")
        got = self.run_role("prior-decisions")
        self.assertTrue(got["ok"], got)
        out = material.collect(bd)
        self.assertTrue(out["ok"], out)
        b = entry.open_board(bd)
        self.assertEqual([n for n in material.ROLES.values() if n in b.rd["done"]], ["p0.prior_decisions"])
        self.assertFalse({material.ROLES[r] for r in LENSES} & set(b.rd["done"]))

    def test_concurrent_takes_do_not_lose_updates(self):
        """並んで走る受け付け（Archon は同じ層の輪を同時に回す）は盤面の錠で 1 本ずつ書く——どれも受かり、どれも盤面に残る"""
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        roles = ["hygiene", "provenance", "test-double-fidelity", "main-path-observation"]
        for role in roles:
            material.prep(bd, role, repo, "")
        drv = (f"import sys, json; sys.dont_write_bytecode = True; sys.path[:0] = {[str(CORE), str(BLK / 'lib'), str(TESTS)]!r}\n"
               "from unittest import mock\n"
               "import entry, material, test_blk_material as T\n"
               "role = sys.argv[1]\n"
               "with mock.patch.object(entry, 'load_table', T._patched_table):\n"
               "    got = material.take(sys.argv[2], role, T.good_reply(material.ROLES[role]), sys.argv[3], 'optional')\n"
               "print(json.dumps(got, ensure_ascii=False))\n")
        env = hermetic.child_env(**{"PYTHONDONTWRITEBYTECODE": "1"})
        procs = [subprocess.Popen([sys.executable, "-c", drv, role, str(bd), str(repo)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env, cwd=str(repo)) for role in roles]
        for role, p in zip(roles, procs):
            out, err = p.communicate()
            self.assertEqual(p.returncode, 0, err)
            self.assertTrue(json.loads(out)["ok"], out)
        b = entry.open_board(bd)
        for role in roles:
            self.assertEqual(b.node_state(material.ROLES[role]), "done", role)

    def test_collect_names_every_waiting_node(self):
        """2 本の目が諦めたら、collect の理由は 2 本とも名指す（先頭の 1 本だけにしない）"""
        bd, repo = self.board("normal")
        r = material.route(bd, repo, "optional")
        bad = {"provenance": good_reply("p1.provenance"), "test-double-fidelity": good_reply("p1.test_double_fidelity")}
        bad["provenance"]["claims"] = "壊れた"
        bad["test-double-fidelity"]["mismatches"] = "壊れた"
        for role in material.ROLES:
            if r[material.route_key(role)] and role not in bad:
                self.assertTrue(self.run_role(role)["ok"], role)
        for _ in range(material.GIVE_UP_AFTER):
            for role, reply in bad.items():
                self.run_role(role, reply)
        out = material.collect(bd)
        self.assertFalse(out["ok"])
        for nid in ("p1.provenance", "p1.test_double_fidelity"):
            self.assertIn(nid, out["reason"])


def _board_bytes(bd: pathlib.Path) -> dict:
    """盤面の state.json・record.json と out/ の中身（止まった後の受け付けが盤面を書かないことを見る）"""
    got = {n: (bd / n).read_bytes() for n in ("state.json", "record.json") if (bd / n).is_file()}
    got.update(TE.board_shas(bd / "out") if (bd / "out").exists() else {})
    return got


class StoppedBoardCase(_Case):
    """同じ波の 1 本の目が盤面を止めた後も、並んで走る他の目の輪は普通に抜け（done・stopped）、collect が出口を返す"""

    def _fenced_wave(self, roles):
        bd, repo = self.board("normal")
        import ticket
        ticket.write(bd, repo, "run-mat")
        r = material.route(bd, repo, "")
        self.assertFalse(r["stopped"], r)
        for role in roles:
            material.prep(bd, role, repo, "")
        return bd, repo

    def test_peers_in_flight_after_mid_wave_stop(self):
        bd, repo = self._fenced_wave(["provenance", "hygiene", "gate-efficacy", "consistency-bypass"])
        first = material.take(bd, "provenance", good_reply("p1.provenance"), repo, "")   # 柵の記録が無い→止める
        self.assertEqual((first["ok"], first["done"]), (False, True))
        before = _board_bytes(bd)
        for role, mode in (("hygiene", ""), ("gate-efficacy", ""), ("consistency-bypass", "optional")):
            with self.subTest(role):
                got = material.take(bd, role, good_reply(material.ROLES[role]), repo, mode)
                self.assertEqual((got["ok"], got["done"], got["give_up"], got["stopped"]), (False, True, False, True), got)
                self.assertIn(material.FENCE_BY, got["reason"])
        # 読めない返答（飛ばした役の null）の受け付けも止まった旨の done
        got = material.refuse(bd, "gate-efficacy", "返答が JSON のオブジェクトでない（NoneType）")
        self.assertEqual((got["done"], got["stopped"]), (True, True))
        # 輪の 2 周目の支度（または遅れて起きた目の支度）は役を起こさない印を返す
        prep = material.prep(bd, "test-double-fidelity", repo, "")
        self.assertIs(prep["stopped"], True)
        self.assertEqual(set(prep), set(material.PREP_KEYS))
        self.assertEqual(_board_bytes(bd), before)   # 止まった後の受け付けと支度は盤面を書かない
        b = entry.open_board(bd, allow_halted=True)
        self.assertEqual(material._read_json(b.work(material.REJECTS), []), [])   # 止まった旨は拒否の回数に積まない
        out = material.collect(bd)
        self.assertFalse(out["ok"])
        self.assertIn(material.FENCE_BY, out["reason"])
        self.assertIn("柵", out["reason"])

    def test_accept_script_on_stopped_board_exits_0(self):
        """スクリプトの入口: 飛ばした役の返答（null）でも、止まった盤面なら 0 で done・stopped を出す（輪の節を落とさない）"""
        bd, repo = self._fenced_wave(["provenance", "gate-efficacy"])
        material.take(bd, "provenance", good_reply("p1.provenance"), repo, "")
        import contextlib
        import io
        env = {"ARTIFACTS_DIR": str(bd.parent), "INPUTS_ROLE": "gate-efficacy", "INPUTS_REPLY": "null", "INPUTS_ADAPTER": ""}
        buf = io.StringIO()
        old = os.getcwd()
        os.chdir(repo)
        try:
            with mock.patch.dict("os.environ", env), contextlib.redirect_stdout(buf):
                rc = material.main_accept()
        finally:
            os.chdir(old)
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertEqual((out["done"], out["stopped"], out["ok"]), (True, True, False))

    def test_two_concurrent_fence_failures(self):
        """旗の役 2 本が同時に柵の確かめで落ちても、どちらも 0 で done を返し、盤面の止め札は 1 つだけ"""
        roles = ["provenance", "gate-efficacy"]
        bd, repo = self._fenced_wave(roles)
        drv = (f"import sys, json; sys.dont_write_bytecode = True; sys.path[:0] = {[str(CORE), str(BLK / 'lib'), str(TESTS)]!r}\n"
               "from unittest import mock\n"
               "import entry, material, test_blk_material as T\n"
               "role = sys.argv[1]\n"
               "with mock.patch.object(entry, 'load_table', T._patched_table):\n"
               "    got = material.take(sys.argv[2], role, T.good_reply(material.ROLES[role]), sys.argv[3], '')\n"
               "print(json.dumps(got, ensure_ascii=False))\n")
        env = hermetic.child_env(**{"PYTHONDONTWRITEBYTECODE": "1"})
        procs = [subprocess.Popen([sys.executable, "-c", drv, role, str(bd), str(repo)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env, cwd=str(repo)) for role in roles]
        outs = []
        for p in procs:
            out, err = p.communicate()
            self.assertEqual(p.returncode, 0, err)
            outs.append(json.loads(out))
        self.assertTrue(all(o["done"] and not o["ok"] for o in outs), outs)
        self.assertEqual(sorted(bool(o.get("stopped")) for o in outs), [False, True])   # 1 本が止め、1 本は止まった盤面を見る
        st = entry.open_board(bd, allow_halted=True).state
        self.assertEqual((st.get("stop") or st.get("halted") or {}).get("by"), material.FENCE_BY)

    def test_stop_is_idempotent(self):
        """もう止まった盤面に止め札を重ねない（記録も変えず、例外も出さない）"""
        bd, repo = self._fenced_wave(["provenance"])
        material.take(bd, "provenance", good_reply("p1.provenance"), repo, "")
        before = _board_bytes(bd)
        b = entry.open_board(bd, allow_halted=True)
        got = material.stop_once(b, "2 本目の柵の落ち", by=material.FENCE_BY)
        self.assertEqual(got.get("by"), material.FENCE_BY)
        self.assertNotIn("2 本目", got.get("reason", ""))
        self.assertEqual(_board_bytes(bd), before)


class GateNaCase(_Case):
    """ゲートの検算の役（p1.gate_efficacy）の『条件に当たらない』。線 A の p0.base は機械が組み（board.base_output）、
    touches_gates を判定せずに走らせる側に倒すので、写しの check_record はゲートに触れない差分でも役の not_applicable を
    『機械が持つ事実と食い違う』と拒み、0 腕で名乗れる値が not_run（検証器の阻害）しか残らなかった（canary の run e91112dd:
    docstring 1 行の差分で結末が round_limit）。works の差し替え（entry.role_judged_na_works）は、前の周の修正がゲートを
    変えたと申告しておらず、差分に機械が見るゲートの印（テスト・CI・pre-commit の定義のファイル、assert の行）が無い時だけ受ける"""

    NA = {"material": {"status": "not_applicable",
                       "reason": "差分は stats.py の 1 行と notes.md で、検証ゲート（CI・assert・テスト・pre-commit）を新設・変更していない"},
          "arms": []}

    def test_na_is_taken_when_diff_has_no_gate(self):
        bd, repo = self.board("normal")
        material.route(bd, repo, "optional")
        got = self.run_role("gate-efficacy", self.NA)
        self.assertEqual((got["ok"], got["done"], got["status"]), (True, True, "not_applicable"), got)
        self.assertEqual(entry.open_board(bd).record["materials"]["gate_efficacy"]["status"], "not_applicable")

    def test_na_is_refused_when_diff_changes_a_test(self):
        """ゲート（テストのファイル）を変えた差分では今どおり拒む——腕を撃って赤を見るか、撃てなければ not_run"""
        bd, repo = self.board("gated")
        material.route(bd, repo, "optional")
        got = self.run_role("gate-efficacy", self.NA)
        self.assertFalse(got["ok"], got)
        self.assertIn("applies_cond が真で走ったのに not_applicable", got["reason"])


class PurposeCase(_Case):
    """目的の節がラインに入った後: 目的の審査（p0.purpose_review）が route・prep・take を通り、盤面の目的で描かれる"""

    def setUp(self):
        super().setUp()
        _TABLE_NOW[0] = PURPOSE_TABLE

    def tearDown(self):
        _TABLE_NOW[0] = TABLE
        super().tearDown()

    def test_purpose_review_runs_its_path(self):
        bd, repo = self.board("purpose")
        r = material.route(bd, repo, "optional")
        self.assertIs(r["purpose_review"], True, r["why"])
        got = material.prep(bd, "purpose-review", repo, "")
        text = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(PURPOSE_REPLY["purpose_text"], text)           # 盤面の目的（purpose_file ではない）
        self.assertNotIn(material.PURPOSE_MISSING, text)
        reply = {"verdict": "問題なし", "reason": "要約は依頼の範囲を狭めていない", "findings": []}
        took = material.take(bd, "purpose-review", reply, repo, "optional")
        self.assertTrue(took["ok"], took)
        self.assertEqual(entry.open_board(bd).node_state("p0.purpose_review"), "done")


if __name__ == "__main__":
    unittest.main()
