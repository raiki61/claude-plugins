"""報告と初見検査のブロック（blk-report。本線の R13: report.human_items・report.cold_check・report）の検査。

- YAML の形: 役の output_format が report_roles.output_format（写しの型か本文の型に印）と同じ・初見の読み手は道具を持たない・
  輪は done の旗で抜ける・when: が読むのはいつも走る経路の節の欄だけ・スクリプトが読む INPUTS_* と with: の鍵が同じ
- 指示書の写し（prompts/）が本線の a1202d0 とバイト単位で同じ。commands は写しを貼らず、持ち主の書式の決まりを持つ
- 芯（blk-report/lib/report_roles.py）: 手本の盤面（graphloops の台本 test_converges の周の締めの後）を、提案の表
  （3 節を role にした darkfactory の表）で開き、経路・支度・受け付け・出口を回す。数は盤面から、機械の事実は書き換えずに付ける
- スクリプト: 子のプロセスで Archon と同じ形（cwd は対象・ARTIFACTS_DIR・INPUTS_*）に回し、輪の抜け方を until_bash の式で見る
提案の表は pack の外の一時の置き場に置き、entry.PACK をそこへ向けて開く（本物の darkfactory/nodes.json は変えない。配線は後）。
"""
import contextlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

sys.dont_write_bytecode = True
TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
BLK = ROOT / "blk-report"
CORE = ROOT / ".shared" / "core"
for _p in (str(TESTS), str(CORE), str(BLK / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import boardreplay as br  # noqa: E402
import entry  # noqa: E402
import report_roles as rr  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

DEADLINE = 1728000000
SCENARIO, RUN, READY_SEQ, MID_SEQ = "test_converges", "1", 171, 100
NODES = ("report.human_items", "report.cold_check", "report")
# 提案の表の行（報告に載せた darkfactory/nodes.json の差分と同じ。配線の時に本物の表へ入れる）
PROPOSED = {
    "report.human_items": {"by": "role", "where": "blk-report",
                           "reason": "書き手（読むだけ）が報告の頭——平易な 3 行と人が決めること——を書く（本線 R13。台帳 R27）"},
    "report.cold_check": {"by": "role", "where": "blk-report",
                          "reason": "道具を持たない初見の読み手が、報告の頭の本文だけを貼られて読む（本線 X3。注記であって門ではない）"},
    "report": {"by": "role", "where": "blk-report",
               "reason": "書き手が初見検査の詰まりを直して本文の全部を書く。検証器の関所は盤面の settle が踏み、機械の事実は出口が字のまま付ける"},
}


def workflow():
    return yaml.safe_load((BLK / "blk-report.yaml").read_text(encoding="utf-8"))


def walk(nodes, inside=None):
    for n in nodes or []:
        yield n, inside
        if "loop_group" in n:
            yield from walk(n["loop_group"].get("nodes"), n)


def script_inputs(name):
    spec = importlib.util.spec_from_file_location(f"_blk_report_{name}", BLK / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "argv", [str(BLK / "scripts" / f"{name}.py")]):
        spec.loader.exec_module(mod)
    return mod.INPUTS


def golden_reply(nid):
    """手本の台本がその節に返した返答（report.human_items・report は本文、report.cold_check は JSON）"""
    step = next(s for s in br.load_runs(SCENARIO)[RUN] if s.get("node") == nid and s["kind"] == "accept")
    text = step["args"]["text"]
    return {"text": text} if nid != "report.cold_check" else json.loads(text)


# ---------------------------------------------------------------- 提案の表の pack と盤面
class Pack:
    """提案の表（darkfactory の表の 3 節を role にした物）を置いた一時の pack の根。hook を渡せば board_hook.py も置く"""

    def __init__(self, hook=None):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        doc = json.loads((ROOT / "darkfactory" / "nodes.json").read_text(encoding="utf-8"))
        doc["nodes"].update(PROPOSED)
        line = self.root / doc["line"]
        line.mkdir()
        (line / "nodes.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        if hook:
            (line / "board_hook.py").write_text(hook, encoding="utf-8")
        self.line = doc["line"]

    @contextlib.contextmanager
    def on(self):
        with mock.patch.object(entry, "PACK", self.root):
            yield

    def cleanup(self):
        self._tmp.cleanup()


BAD_VALIDATOR_HOOK = '''
def board_kwargs(table):
    def runner(b, target):
        return {"exit": 9, "out": "偽の検証器: 記録が通らない"}
    return {"validator_runner": runner}
'''


def build(pack, kind, into):
    """kind: ready（周の締めの後で報告の頭の節を待つ）・mid（周の途中）・stopped（周の途中で人が止めた）"""
    rs = br.load_runs(SCENARIO)[RUN]
    seq, which = {"ready": (READY_SEQ, "before"), "mid": (MID_SEQ, "after"), "stopped": (MID_SEQ, "after")}[kind]
    with pack.on():
        table = entry.load_table(pack.line)
        bd, repo = br.restore(rs, seq, which, into)
        b = br.board_from_memory(br.memory_at(rs, seq, which), bd, table)
        b.state["works"].update(line=pack.line, table_sha=table.sha())
        b.save()
        if kind == "stopped":
            entry.open_board(bd).stop("試験: 周の途中で人が止めた", by="human:test")
    return bd, repo


def state(bd):
    return json.loads((pathlib.Path(bd) / "state.json").read_text(encoding="utf-8"))


def record(bd):
    return json.loads((pathlib.Path(bd) / "record.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- YAML と写し
class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()
        self.top = {n["id"]: n for n in self.y["nodes"]}

    def loops(self):
        return [n for n in self.y["nodes"] if "loop_group" in n]

    def test_inputs_and_exit(self):
        self.assertEqual(set(self.y["inputs"]), {"machine_report"})
        self.assertEqual(self.y["inputs"]["machine_report"].get("default"), "")
        self.assertEqual((self.y["returns"], self.y["outcome_field"]), ("collect", "ok"))
        self.assertNotIn("model", yaml.safe_dump(self.y))
        self.assertNotIn("effort", yaml.safe_dump(self.y), "effort はまだ置かない（報告の表で提案するだけ）")

    def test_roles_follow_graph_order(self):
        """段 k の輪の役が ROLES の k 番目、ROLES の節の並びが写しの graph の依存の並び"""
        self.assertEqual([rr.NODE_OF[r] for r in rr.ROLES], list(NODES))
        got = []
        for k, grp in enumerate(self.loops(), 1):
            m = re.fullmatch(r"\$rp-route(\d+)\.output\.next == '([a-z0-9-]+)'", grp.get("when", ""))
            self.assertIsNotNone(m, grp.get("when"))
            self.assertEqual(int(m.group(1)), k)
            self.assertEqual(grp["depends_on"], [f"rp-route{k}"])
            got.append(m.group(2))
            self.assertEqual(self.top[f"rp-route{k}"]["with"], {"role": m.group(2)})
        self.assertEqual(got, list(rr.ROLES))

    def test_loops_exit_on_done_flag(self):
        for grp in self.loops():
            g = grp["loop_group"]
            ai = [m for m in g["nodes"] if "command" in m or "prompt" in m]
            with self.subTest(grp["id"]):
                self.assertEqual(len(ai), 1)
                role = ai[0]["id"]
                self.assertEqual(g["max_iterations"], rr.GIVE_UP_AFTER, "諦めの数は輪の上限と同じ（上限で輪を落とさない。R50）")
                self.assertEqual(g["until_bash"], f"test ${role}-accept.output.done = true")
                self.assertEqual([m["id"] for m in g["nodes"]], [f"{role}-prep", role, f"{role}-accept"])
                # 初見の読み手は毎回新しい会話（本線の fresh_context）。書き手は同じ会話で出し直す（本線の writer）
                self.assertIs(g["fresh_context"], role == "report-cold")

    def test_role_nodes(self):
        for grp in self.loops():
            role = next(m for m in grp["loop_group"]["nodes"] if "command" in m)
            with self.subTest(role["id"]):
                self.assertEqual(role["command"], role["id"])
                self.assertTrue((BLK / "commands" / f"{role['id']}.md").is_file())
                self.assertEqual(role["output_format"], rr.output_format(role["id"]))
                self.assertEqual(role["settingSources"], ["user"])
                self.assertEqual(role["idle_timeout"], DEADLINE)
                self.assertEqual(role["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
                if role["id"] == "report-cold":
                    self.assertEqual(role["allowed_tools"], [], "初見の読み手は道具を持たない（本文だけを読む。X3）")
                else:
                    self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "WebSearch", "WebFetch"])

    def test_output_formats(self):
        self.assertEqual(rr.output_format("report-items")["description"], "works-node: report-items")
        self.assertEqual(rr.output_format("report-cold")["description"], "works-node: report-cold")
        self.assertEqual(rr.output_format("report-write")["description"], "works-node: report-write")
        self.assertEqual(validate_schema(golden_reply("report.cold_check"), rr.output_format("report-cold")), [])
        for nid, role in (("report.human_items", "report-items"), ("report", "report-write")):
            self.assertEqual(validate_schema(golden_reply(nid), rr.output_format(role)), [])
            self.assertTrue(validate_schema({"text": ""}, rr.output_format(role)), "空の本文は型で落とす")

    def test_when_reads_only_routes(self):
        routes = {nid for nid, n in self.top.items() if n.get("script") == "route"}
        for n, _ in walk(self.y["nodes"]):
            if "when" in n:
                refs = set(re.findall(r"\$([A-Za-z0-9_-]+)\.output", n["when"]))
                with self.subTest(n["id"]):
                    self.assertTrue(refs and refs <= routes, refs)
        for nid in routes:
            self.assertNotIn("when", self.top[nid], "経路の節はいつも走る")
        for nid, n in self.top.items():
            if any(d in self.top and "loop_group" in self.top[d] for d in n.get("depends_on") or []):
                self.assertEqual(n.get("trigger_rule"), "none_failed_min_one_success", nid)
                refs = set(re.findall(r"\$([A-Za-z0-9_-]+)\.output", json.dumps(n.get("with") or {})))
                self.assertFalse(refs, f"{nid}: 飛ばされうる輪の欄を読まない")

    def test_ids_do_not_collide(self):
        """Ruling R17・R19: 輪の中の節の id は模擬実行で名前空間の付かない id で stub を引くので、ブロックをまたいで重ねない。
        ラインの include の id とも重ねない"""
        mine = {n["id"] for n, inside in walk(self.y["nodes"]) if inside is not None}
        line = yaml.safe_load((ROOT / "darkfactory" / "darkfactory.yaml").read_text(encoding="utf-8"))
        self.assertEqual({n["id"] for n in line["nodes"] if "include" in n} & ({n["id"] for n, _ in walk(self.y["nodes"])}), set())
        for p in sorted(ROOT.glob("blk-*/blk-*.yaml")):
            if p.parent.name == "blk-report" or p.stem != p.parent.name:
                continue
            with self.subTest(p.parent.name):
                other = {n["id"] for n, inside in walk(yaml.safe_load(p.read_text(encoding="utf-8"))["nodes"]) if inside is not None}
                self.assertEqual(other & mine, set())

    def test_script_inputs_match_with(self):
        for n, _ in walk(self.y["nodes"]):
            if "script" not in n:
                continue
            with self.subTest(n["id"]):
                want = {f"INPUTS_{k.upper()}" for k in (n.get("with") or {})}
                self.assertEqual(set(script_inputs(n["script"])), want)
                self.assertEqual(n["timeout"], DEADLINE)
                self.assertEqual(n["runtime"], "uv")
                if "role" in (n.get("with") or {}) and n["script"] != "route":
                    self.assertEqual(n["id"].rsplit("-", 1)[0], n["with"]["role"])

    def test_commands(self):
        for role in rr.ROLES:
            text = (BLK / "commands" / f"{role}.md").read_text(encoding="utf-8")
            with self.subTest(role):
                self.assertNotIn("$LOOP_PREV", text, "拒否の文は prep が指示書に書く（R44）")
                self.assertNotIn("{{", text, "指示書を写さない（本文は写しの描画）")
                if role == "report-cold":
                    # 道具を持たない役: 描いた本文そのものを貼る（最後の置き換えで入れるので、中の $ は置き換え直されない）
                    self.assertIn("$report-cold-prep.output.prompt\n", text + "\n")
                    self.assertNotIn("prompt_file", text)
                    self.assertNotIn("Read", text)
                    self.assertIn("道具を一切持たない", text)       # 本線の cold-reader の定義
                    self.assertIn("冒頭 3 行", text)                # 持ち主の冷読の問い
                else:
                    self.assertIn(f"${role}-prep.output.prompt_file", text)
                    self.assertIn("前の回の受け付けが拒んだ理由", text)
                    for words in ("冒頭 3 行", "セルに", "中身→記号", "今壊れているのか"):
                        self.assertIn(words, text)
        write = (BLK / "commands" / "report-write.md").read_text(encoding="utf-8")
        self.assertIn("$report-write-prep.output.facts_file", write)

    def test_prompt_copies_verbatim(self):
        """指示書の写し（prompts/）は COPIED_FROM の 1 行目の commit の graphloops/prompts/ の下とバイト単位で同じ。
        graph の 3 節の prompt_file を全部持ち、prompt_append を持たない"""
        base = BLK / "prompts"
        lines = (base / "COPIED_FROM").read_text(encoding="utf-8").splitlines()
        commit = lines[0].split()[0]
        listed = [ln.split()[0] for ln in lines[1:] if ln.strip() and not ln.startswith("#")]
        self.assertEqual(sorted(listed), sorted(str(p.relative_to(base)) for p in base.rglob("*.md")))
        core = (CORE / "COPIED_FROM").read_text(encoding="utf-8").splitlines()[0].split()[0]
        self.assertEqual(commit, core, "写し（graphloops/）と同じ commit から写す")
        g = json.loads((CORE / "graphloops" / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
        for nid in NODES:
            self.assertIn(g["nodes"][nid]["prompt_file"].removeprefix("../prompts/"), listed)
            self.assertNotIn("prompt_append", g["nodes"][nid])
        for rel in listed:
            with self.subTest(rel):
                src = subprocess.run(["git", "-C", str(CORE), "show", f"{commit}:graphloops/prompts/{rel}"],
                                     capture_output=True, check=True).stdout
                self.assertEqual((base / rel).read_bytes(), src)

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"pass.stubs.yaml", "rejected-thrice.stubs.yaml", "not-ready.stubs.yaml"})
        p = fx["pass.stubs.yaml"]
        self.assertEqual(p["fixture"]["expect"], "completed")
        for role in rr.ROLES:
            self.assertIn(role, p["fixture"]["reached"])
        self.assertIs(p["collect"]["ok"], True)
        r = fx["rejected-thrice.stubs.yaml"]
        self.assertEqual((r["report-items-accept"]["ok"], r["report-items-accept"]["done"]), (False, True))
        self.assertIn("dry-run は until_bash を回さず", (BLK / "fixtures" / "rejected-thrice.stubs.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("report-cold", r, "後の輪は飛ぶ")
        self.assertIs(r["collect"]["ok"], False)
        n = fx["not-ready.stubs.yaml"]
        self.assertEqual(n["rp-route1"]["next"], "")
        self.assertNotIn("report-items", n)
        self.assertIs(n["collect"]["ok"], False)
        for name, f in fx.items():
            for nid, out in f.items():
                if nid in rr.ROLES:
                    with self.subTest(f"{name}:{nid}"):
                        self.assertEqual(validate_schema(out, rr.output_format(nid)), [])


# ---------------------------------------------------------------- 書式の機械の検査
class FormatCase(unittest.TestCase):
    def test_short_cells_pass(self):
        text = "結果\n\n| 項目 | 件数 |\n|---|---|\n| 直した | 3 |\n| `src/very/long/path/to/some/module_name.py` | 済み |\n"
        self.assertEqual(rr.format_problems(text), [])

    def test_sentence_in_cell_rejected(self):
        text = "| 項目 | 説明 |\n|---|---|\n| A | これは説明の文である。 |\n"
        got = rr.format_problems(text)
        self.assertEqual(len(got), 1)
        self.assertIn("3 行目", got[0])

    def test_long_cell_rejected(self):
        text = "| 項目 |\n|---|\n| " + "あ" * (rr.CELL_LIMIT + 1) + " |\n"
        self.assertEqual(len(rr.format_problems(text)), 1)

    def test_pipes_in_code_are_not_cells(self):
        text = "```\n| " + "あ" * 80 + "。 |\n```\n"
        self.assertEqual(rr.format_problems(text), [])


# ---------------------------------------------------------------- 芯
class _Case(unittest.TestCase):
    hook = None

    @classmethod
    def setUpClass(cls):
        cls.pack = Pack(cls.hook)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = pathlib.Path(cls._tmp.name)
        cls.made = {}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        cls.pack.cleanup()

    def setUp(self):
        on = self.pack.on()
        on.__enter__()
        self.addCleanup(on.__exit__, None, None, None)

    def board(self, kind="ready"):
        """種類ごとに 1 度だけ作って控え、試験ごとに同じパスへ戻す（盤面は絶対パスを持つ）"""
        into, snap = self.root / kind, self.root / f"{kind}.snap"
        if kind not in self.made:
            self.made[kind] = build(self.pack, kind, into)
            shutil.copytree(into / "work", snap, symlinks=True)
        else:
            shutil.rmtree(into / "work")
            shutil.copytree(snap, into / "work", symlinks=True)
        self.bd, self.repo = self.made[kind]
        return self.bd

    def run_role(self, role, reply, *, machine_report=""):
        prep = rr.prep(self.bd, role, self.repo, machine_report=machine_report)
        got = rr.accept(self.bd, role, json.dumps(reply, ensure_ascii=False), self.repo)
        return prep, got


class RouteCase(_Case):
    def test_ready_after_converge(self):
        self.board()
        got = rr.route(self.bd, "report-items")
        self.assertEqual((got["next"], got["node"]), ("report-items", "report.human_items"), got)
        self.assertEqual(rr.route(self.bd, "report-cold")["next"], "")

    def test_mid_round_not_ready(self):
        self.board("mid")
        got = rr.route(self.bd, "report-items")
        self.assertEqual(got["next"], "")
        self.assertIn("report.human_items", got["why"])
        out = rr.collect(self.bd)
        self.assertFalse(out["ok"])
        self.assertIn("ready", out["reason"])

    def test_stopped_run_reaches_report(self):
        """人が周の途中で止めた run も報告の節へ届く（graph の stop.node の下流。本線の answer stop と同じ道）"""
        self.board("stopped")
        self.assertEqual(rr.route(self.bd, "report-items")["next"], "report-items")
        prep, got = self.run_role("report-items", {"text": "人が止めた run の報告の頭"})
        self.assertTrue(got["ok"], got)
        self.assertIn("stop", pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8"))


class PathCase(_Case):
    def test_full_pass_path(self):
        self.board()
        rec_before = record(self.bd)
        prep, got = self.run_role("report-items", golden_reply("report.human_items"))
        self.assertEqual((got["ok"], got["done"], got["give_up"]), (True, True, False), got)
        text = pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("最終報告の冒頭", text)                    # 本線の指示書を盤面の値で描いた
        self.assertNotIn("{{", text)
        self.assertEqual(prep["prompt"], "", "書き手には本文を貼らない（ファイルで読む）")
        # 初見の読み手: 人が決めるところの本文だけを貼る。盤面・記録・差分の置き場を渡さない
        self.assertEqual(rr.route(self.bd, "report-cold")["next"], "report-cold")
        cprep = rr.prep(self.bd, "report-cold", self.repo)
        self.assertIn(golden_reply("report.human_items")["text"].strip(), cprep["prompt"])
        self.assertNotIn(str(self.bd), cprep["prompt"])
        self.assertNotIn(str(self.repo), cprep["prompt"])
        self.assertNotIn("record.json", cprep["prompt"])
        got = rr.accept(self.bd, "report-cold", json.dumps(golden_reply("report.cold_check")), self.repo)
        self.assertTrue(got["ok"], got)
        self.assertEqual(state(self.bd)["loop"]["cold_check"]["verdict"], "pass")   # 写しの post_check の注記（本線と同じ）
        # 書き手: 数の出どころ（盤面の事実）のファイルと、検証器の結果を描いた指示書
        self.assertEqual(rr.route(self.bd, "report-write")["next"], "report-write")
        wprep, got = self.run_role("report-write", golden_reply("report"))
        self.assertTrue(got["ok"], got)
        facts = pathlib.Path(wprep["facts_file"]).read_text(encoding="utf-8")
        wtext = pathlib.Path(wprep["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("検証器の最終結果", wtext)
        self.assertIn(wprep["facts_file"], wtext, "書き手に数の出どころを渡す")
        out = rr.collect(self.bd)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["cold_check"]["verdict"], "pass")
        rep = pathlib.Path(out["report_file"]).read_text(encoding="utf-8")
        head, _, rest = rep.partition("\n\n")
        self.assertIn(f"run {state(self.bd)['run_id']}", head)          # 来歴の 1 行は機械が刻む
        self.assertTrue(rest.startswith(golden_reply("report")["text"].strip()[:40]))
        self.assertIn(rr.MACHINE_HEADING, rep)
        self.assertTrue(rep.rstrip().endswith(facts.rstrip()), "機械の事実は書き換えずに最後に付ける")
        self.assertEqual(pathlib.Path(out["report_file"]).name, rr.REPORT_NAME)
        self.assertNotEqual(rr.REPORT_NAME, "report.md", "線 A の機械の報告（$B/report.md）を上書きしない")
        self.assertEqual(len(rec_before["units"]), len(record(self.bd)["units"]))

    def test_facts_numbers_from_board(self):
        self.board()
        b = entry.open_board(self.bd)
        facts = rr.board_facts(b)
        units = b.record.get("units") or []
        qs = b.record.get("questions") or []
        self.assertIn(f"根本の単位: {len(units)} 件", facts)
        self.assertIn(f"問いの台帳: {len(qs)} 件", facts)
        self.assertIn(f"周: {b.round}", facts)
        self.assertEqual(rr.format_problems(facts), [], "機械の事実も書式の決まりを守る")

    def test_machine_report_attached_verbatim(self):
        self.board()
        mr = self.root / "machine-report.md"
        body = "# 機械の報告\n\n- 結末: fixed\n- 引用符 \" と $ARTIFACTS_DIR と $x.output.y はそのまま\n"
        mr.write_text(body, encoding="utf-8")
        self.run_role("report-items", golden_reply("report.human_items"))
        rr.prep(self.bd, "report-cold", self.repo)
        rr.accept(self.bd, "report-cold", json.dumps(golden_reply("report.cold_check")), self.repo)
        wprep, got = self.run_role("report-write", golden_reply("report"), machine_report=str(mr))
        self.assertTrue(got["ok"], got)
        self.assertEqual(pathlib.Path(wprep["facts_file"]).read_text(encoding="utf-8"), body)
        out = rr.collect(self.bd, machine_report=str(mr))
        rep = pathlib.Path(out["report_file"]).read_text(encoding="utf-8")
        self.assertTrue(rep.endswith(body), "機械の報告は 1 バイトも変えずに付ける")

    def test_format_rejects_sentence_cells_without_writing_board(self):
        self.board()
        before = (pathlib.Path(self.bd) / "state.json").read_bytes()
        bad = {"text": "頭\n\n| 項目 | 説明 |\n|---|---|\n| A | これは説明の文である。 |\n"}
        prep, got = self.run_role("report-items", bad)
        self.assertEqual((got["ok"], got["done"], got["give_up"]), (False, False, False), got)
        self.assertIn("セル", got["reason"])
        st = state(self.bd)
        self.assertEqual(st["rounds"][-1]["instances"]["report.human_items"]["status"], "pending")
        self.assertNotIn("report.human_items", st["rounds"][-1]["done"])
        self.assertTrue(before)
        # 2 回目の指示書の頭に前の拒否の文
        prep2 = rr.prep(self.bd, "report-items", self.repo)
        self.assertTrue(pathlib.Path(prep2["prompt_file"]).read_text(encoding="utf-8").startswith(rr.REJECT_HEADING))

    def test_give_up_after_three_then_fallback_report(self):
        self.board()
        rounds = [self.run_role("report-items", {"text": "| A |\n|---|\n| 説明の文。 |\n"})[1] for _ in range(rr.GIVE_UP_AFTER)]
        self.assertEqual([(g["ok"], g["done"], g["give_up"]) for g in rounds],
                         [(False, False, False)] * (rr.GIVE_UP_AFTER - 1) + [(False, True, True)])
        self.assertEqual(rr.route(self.bd, "report-cold")["next"], "")
        out = rr.collect(self.bd)
        self.assertFalse(out["ok"])
        self.assertIn("3 回とも", out["reason"])
        rep = pathlib.Path(out["report_file"]).read_text(encoding="utf-8")
        self.assertIn(out["reason"].splitlines()[0], rep, "諦めた事実を報告の頭に出す（黙らない）")
        self.assertIn(rr.MACHINE_HEADING, rep, "諦めても機械の事実は付ける")

    def test_writer_must_not_move_tree(self):
        self.board()
        rr.prep(self.bd, "report-items", self.repo)
        (pathlib.Path(self.repo) / "stray.txt").write_text("書き手が作った", encoding="utf-8")
        try:
            got = rr.accept(self.bd, "report-items", json.dumps(golden_reply("report.human_items")), self.repo)
        finally:
            (pathlib.Path(self.repo) / "stray.txt").unlink()
        self.assertFalse(got["ok"])
        self.assertIn("読むだけの役", got["reason"])

    def test_unreadable_reply_is_returned_to_role(self):
        self.board()
        rr.prep(self.bd, "report-items", self.repo)
        got = rr.accept(self.bd, "report-items", "{JSON でない", self.repo)
        self.assertFalse(got["ok"])
        self.assertIn("JSON", got["reason"])


class RecordInvalidCase(_Case):
    hook = BAD_VALIDATOR_HOOK

    def test_validator_gate_stops_report_but_keeps_facts(self):
        """記録が検証器を通らない run は report の節を出さない（本線の pre: finalize の関所）。ブロックは落ちずに、
        人が決めるところの本文・検証器の出力の末尾・機械の事実を付けた報告を ok: false で残す"""
        self.board()
        self.run_role("report-items", golden_reply("report.human_items"))
        rr.prep(self.bd, "report-cold", self.repo)
        got = rr.accept(self.bd, "report-cold", json.dumps(golden_reply("report.cold_check")), self.repo)
        self.assertEqual((got["ok"], got["done"], got["record_invalid"]), (True, True, True), got)
        r = rr.route(self.bd, "report-write")
        self.assertEqual(r["next"], "")
        self.assertIn("検証器", r["why"])
        out = rr.collect(self.bd)
        self.assertFalse(out["ok"])
        self.assertTrue(out["record_invalid"])
        rep = pathlib.Path(out["report_file"]).read_text(encoding="utf-8")
        self.assertIn("偽の検証器", rep)
        self.assertIn(golden_reply("report.human_items")["text"].strip(), rep)
        self.assertIn(rr.MACHINE_HEADING, rep)


# ---------------------------------------------------------------- スクリプト（子のプロセス）
WRAP = """
import pathlib, runpy, sys
sys.dont_write_bytecode = True
core, pack, script = sys.argv[1:4]
sys.path.insert(0, core)
import entry
entry.PACK = pathlib.Path(pack)
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
"""


class ScriptCase(_Case):
    def run_script(self, name, drop=(), **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({"ARTIFACTS_DIR": str(pathlib.Path(self.bd).parent), "PYTHONDONTWRITEBYTECODE": "1"})
        env.update({f"INPUTS_{k.upper()}": v for k, v in inputs.items()})
        for k in drop:
            env.pop(k, None)
        r = subprocess.run([sys.executable, "-c", WRAP, str(CORE), str(self.pack.root), str(BLK / "scripts" / f"{name}.py")],
                           cwd=str(self.repo), env=env, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            lines = r.stdout.splitlines()
            self.assertEqual(len(lines), 1, r.stdout + r.stderr)
            return 0, json.loads(lines[0]), r.stderr
        return r.returncode, r.stdout, r.stderr

    def ok(self, name, **inputs):
        rc, out, err = self.run_script(name, **inputs)
        self.assertEqual(rc, 0, err)
        return out

    def run_loop(self, role, reply):
        """Archon の輪と同じ順（prep → 役 → accept → until_bash を sh で評価）。抜けた周の番号と各周の (prep, accept)"""
        g = next(n for n in workflow()["nodes"] if n.get("id") == f"{role}-loop")["loop_group"]
        rounds = []
        for i in range(1, g["max_iterations"] + 1):
            prep = self.ok("prep", role=role, machine_report="")
            got = self.ok("accept", role=role, reply=json.dumps(reply, ensure_ascii=False))
            rounds.append((prep, got))

            def value(m):
                self.assertEqual(m.group(1), f"{role}-accept")
                return json.dumps(got[m.group(2)])
            cond = re.sub(r"\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+)", value, g["until_bash"])
            if subprocess.run(["sh", "-c", cond]).returncode == 0:
                return i, rounds
        return None, rounds

    def test_block_pass_path(self):
        self.board()
        replies = {"report-items": golden_reply("report.human_items"), "report-cold": golden_reply("report.cold_check"),
                   "report-write": golden_reply("report")}
        for k, role in enumerate(rr.ROLES, 1):
            self.assertEqual(self.ok("route", role=role)["next"], role)
            exited, rounds = self.run_loop(role, replies[role])
            self.assertEqual(exited, 1, rounds)
            self.assertEqual(rounds[0][1]["reason_file"], "")
        out = self.ok("collect", machine_report="")
        self.assertTrue(out["ok"], out)
        self.assertTrue(pathlib.Path(out["report_file"]).is_file())

    def test_loop_gives_up_after_three(self):
        self.board()
        self.assertEqual(self.ok("route", role="report-items")["next"], "report-items")
        exited, rounds = self.run_loop("report-items", {"text": "| A |\n|---|\n| 説明の文。 |\n"})
        self.assertEqual(exited, rr.GIVE_UP_AFTER, "輪が上限まで抜けない（Archon は run を落とす）")
        self.assertTrue(all(pathlib.Path(a["reason_file"]).is_file() for _, a in rounds), "拒否の文はファイルで渡す（R44）")
        self.assertEqual(self.ok("route", role="report-cold")["next"], "")
        out = self.ok("collect", machine_report="")
        self.assertFalse(out["ok"])

    def test_exit_two_on_wiring(self):
        self.board()
        rc, _, err = self.run_script("route", drop=("ARTIFACTS_DIR",), role="report-items")
        self.assertEqual(rc, 2, err)
        self.assertIn("ARTIFACTS_DIR", err)
        rc, _, err = self.run_script("prep")
        self.assertEqual(rc, 2)
        self.assertIn("INPUTS_ROLE", err)
        rc, out, err = self.run_script("prep", role="report-cold", machine_report="")   # 待っている instance が無い
        self.assertEqual(rc, 2, out)
        self.assertEqual(out, "")
        rc, _, err = self.run_script("route", role="no-such-role")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
