"""報告のブロック（blk-report。本線の R13: report。頭と初見検査の節はこのラインで absent）の検査。

- YAML の形: 役の output_format が report_roles.output_format（写しの型か本文の型に印）と同じ・初見の読み手は道具を持たない・
  輪は done の旗で抜ける・when: が読むのはいつも走る経路の節の欄だけ・スクリプトが読む INPUTS_* と with: の鍵が同じ
- 指示書の写し（prompts/）が本線の a1202d0 に台帳の手直しを当てた物とバイト単位で同じ。commands は写しを貼らず、持ち主の書式の決まりを持つ
- 芯（blk-report/lib/report_roles.py）: 手本の盤面（graphloops の台本 test_converges の周の締めの後）を darkfactory の表で開き、
  経路・支度・受け付け・出口を回す。数は盤面から、機械の事実は書き換えずに付ける
- スクリプト: 子のプロセスで Archon と同じ形（cwd は対象・ARTIFACTS_DIR・INPUTS_*）に回し、輪の抜け方を until_bash の式で見る
表は pack の外の一時の置き場に写し、entry.PACK をそこへ向けて開く（hook の board_hook.py を足せるように）。
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
import copyledger  # noqa: E402
import entry  # noqa: E402
import prepkit  # noqa: E402
import report_roles as rr  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

DEADLINE = 1728000000
SCENARIO, RUN, READY_SEQ, MID_SEQ = "test_converges", "1", 171, 100
PROMPTED = ("report.cold_check", "report")   # ブロックが描く写しの指示書の節（report.cold_check は書き手の輪の初見の読み手が借りる）


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
    """手本の台本がその節に返した返答（report は本文、report.cold_check は JSON。書き手の輪の初見の読み手の見本に使う）"""
    step = next(s for s in br.load_runs(SCENARIO)[RUN] if s.get("node") == nid and s["kind"] == "accept")
    text = step["args"]["text"]
    return {"text": text} if nid != "report.cold_check" else json.loads(text)


# ---------------------------------------------------------------- 表の pack と盤面
class Pack:
    """darkfactory の表を写した一時の pack の根。hook を渡せば board_hook.py も置く"""

    def __init__(self, hook=None):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        doc = json.loads((ROOT / "darkfactory" / "nodes.json").read_text(encoding="utf-8"))
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
        if kind != "mid":
            rr.route(bd, rr.WRITE)   # Archon の rp-route と同じく settle して書き手の節を出す（頭と初見検査は absent で省く）
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

    def test_one_writer_loop(self):
        """役は書き手 1 つ（report）。頭と初見検査の節は darkfactory の表で absent（2026-10-09 の片付け）"""
        self.assertEqual(rr.ROLES, (rr.WRITE,))
        self.assertEqual(rr.NODE_OF, {rr.WRITE: "report"})
        loops = self.loops()
        self.assertEqual([g["id"] for g in loops], [f"{rr.WRITE}-loop"])
        self.assertEqual(loops[0]["when"], f"$rp-route.output.next == '{rr.WRITE}'")
        self.assertEqual(loops[0]["depends_on"], ["rp-route"])
        self.assertEqual(self.top["rp-route"]["with"], {"role": rr.WRITE})
        table = json.loads((ROOT / "darkfactory" / "nodes.json").read_text(encoding="utf-8"))["nodes"]
        self.assertEqual([table[n]["by"] for n in rr.REPORT_NODES], ["absent", "absent", "role"])

    def test_loops_exit_on_done_flag(self):
        for grp in self.loops():
            g = grp["loop_group"]
            # 書き手の輪だけは、書き手の出した物の頭を初見の読み手（道具なし）が読み、その返答を受け付けが見る（書き手に戻す輪）。
            # 返答を受け付けに出す役は輪 1 つに 1 つのまま
            ai = [m for m in g["nodes"] if ("command" in m or "prompt" in m) and m["id"] != rr.WRITE_COLD]
            with self.subTest(grp["id"]):
                self.assertEqual(len(ai), 1)
                role = ai[0]["id"]
                self.assertEqual(g["max_iterations"], rr.GIVE_UP_AFTER, "諦めの数は輪の上限と同じ（上限で輪を落とさない。R50）")
                self.assertEqual(g["until_bash"], f"test ${role}-accept.output.done = true")
                cold = [f"{rr.WRITE_COLD}-prep", rr.WRITE_COLD] if role == rr.WRITE else []
                self.assertEqual([m["id"] for m in g["nodes"]], [f"{role}-prep", role, *cold, f"{role}-accept"])
                # 書き手は同じ会話で出し直す（本線の writer）。初見の読み手は節の context: fresh
                self.assertIs(g["fresh_context"], False)

    def test_write_cold_reads_in_a_new_conversation(self):
        """書き手の輪の初見の読み手は、どの周も新しい会話で起きる（Archon の輪は直前の AI の節の会話を次の AI の節に継がせるので、
        書かないと書き手の会話の続きで読み、初見でなくなる。run f57a5374）。書き手は自分の会話で出し直す"""
        grp = next(g for g in self.loops() if g["id"] == "report-write-loop")["loop_group"]
        inner = {m["id"]: m for m in grp["nodes"]}
        self.assertIs(grp["fresh_context"], False)
        self.assertEqual(inner[rr.WRITE_COLD].get("context"), "fresh")
        self.assertNotIn("context", inner[rr.WRITE])
        self.assertIn("self-resume", inner[rr.WRITE]["output_format"]["description"].split(" ")[2:])

    def test_role_nodes(self):
        # 役の節は command: の役と、書き手の輪の初見の読み手（prompt: に支度が描いた本文。commands/ の決まりで包んだ物）
        roles = [m for grp in self.loops() for m in grp["loop_group"]["nodes"] if "command" in m or "prompt" in m]
        self.assertIn(rr.WRITE_COLD, [m["id"] for m in roles])
        for role in roles:
            with self.subTest(role["id"]):
                if role["id"] == rr.WRITE_COLD:
                    self.assertEqual(role["prompt"], f"${role['id']}-prep.output.prompt")
                else:
                    self.assertEqual(role["command"], role["id"])
                    self.assertTrue((BLK / "commands" / f"{role['id']}.md").is_file())
                self.assertEqual(role["output_format"], rr.output_format(role["id"]))
                self.assertEqual(role["settingSources"], ["user"])
                self.assertEqual(role["idle_timeout"], DEADLINE)
                self.assertEqual(role["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
                if role["id"] == rr.WRITE_COLD:
                    self.assertEqual(role["allowed_tools"], [], "初見の読み手は道具を持たない（本文だけを読む。X3）")
                else:
                    self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "WebSearch", "WebFetch"])

    def test_output_formats(self):
        # 書き手の輪には初見の読み手（新しい会話）が挟まるので、書き手は 2 周目から自分の会話に戻る（包みの旗 self-resume）
        self.assertEqual(rr.output_format("report-write")["description"], "works-node: report-write self-resume")
        self.assertEqual(rr.output_format(rr.WRITE_COLD)["description"], f"works-node: {rr.WRITE_COLD}")
        self.assertEqual(validate_schema(golden_reply("report.cold_check"), rr.output_format(rr.WRITE_COLD)), [])
        self.assertEqual(validate_schema(golden_reply("report"), rr.output_format(rr.WRITE)), [])
        self.assertTrue(validate_schema({"text": ""}, rr.output_format(rr.WRITE)), "空の本文は型で落とす")
        with self.assertRaises(rr.BoardGap):
            rr.output_format("report-items")

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
        self.assertEqual(sorted(p.stem for p in (BLK / "commands").glob("*.md")), sorted([rr.WRITE, rr.WRITE_COLD]))
        for role in (rr.WRITE, rr.WRITE_COLD):
            text = (BLK / "commands" / f"{role}.md").read_text(encoding="utf-8")
            with self.subTest(role):
                self.assertNotIn("$LOOP_PREV", text, "拒否の文は prep が指示書に書く（R44）")
                self.assertNotIn("{{", text, "指示書を写さない（本文は写しの描画）")
        cold = (BLK / "commands" / f"{rr.WRITE_COLD}.md").read_text(encoding="utf-8")
        # 道具を持たない役: 描いた本文そのものを貼る（支度が貼る所を置き換えるので、中の $ は置き換え直されない）
        self.assertIn(rr.COLD_PASTE + "\n", cold + "\n")
        self.assertNotIn("prompt_file", cold)
        self.assertNotIn("Read", cold)
        self.assertIn("道具を一切持たない", cold)       # 本線の cold-reader の定義
        self.assertIn("冒頭 3 行", cold)                # 持ち主の冷読の問い
        # 頭だけを読む読み手に、報告の後ろに詳しい節と機械の事実の節が付くことを言う（言わないと、頭がその節を名指した所を
        # 「本文の外への参照」として止まった所に挙げる。実物の拒否 55 回のうち 37 回）
        self.assertIn(rr.MACHINE_HEADING.removeprefix("## "), cold)
        self.assertNotIn("前の回の受け付けが拒んだ理由", cold, "初見の読み手の指示に拒否の節は付かない")
        write = (BLK / "commands" / f"{rr.WRITE}.md").read_text(encoding="utf-8")
        self.assertIn(f"${rr.WRITE}-prep.output.prompt_file", write)
        self.assertIn(f"${rr.WRITE}-prep.output.facts_file", write)
        self.assertIn("前の回の受け付けが拒んだ理由", write)
        for words in ("冒頭 3 行", "セルに", "中身→記号", "今壊れているのか", "初見の読み手", "機械の事実の節"):
            self.assertIn(words, write)
        self.assertEqual(write.count("**セルに説明の文を入れない**"), 1, "書式の決まりは 1 か所だけに持つ")

    def test_prompt_copies_verbatim(self):
        """指示書の写し（prompts/）は COPIED_FROM の 1 行目の commit の graphloops/prompts/ の下に、台帳の手直し（! 行）を
        当てた物とバイト単位で同じ。ブロックが描く節の prompt_file を全部持ち、prompt_append を持たない"""
        base = BLK / "prompts"
        led = copyledger.read(base / "COPIED_FROM")
        listed = [rel for rel, _ in led.rows]
        self.assertEqual(sorted(listed), sorted(str(p.relative_to(base)) for p in base.rglob("*.md")))
        self.assertEqual(led.commit, copyledger.core_commit(), "写し（graphloops/）と同じ commit から写す")
        g = json.loads((CORE / "graphloops" / "graphs" / "review-loop.json").read_text(encoding="utf-8"))
        for nid in PROMPTED:
            self.assertIn(g["nodes"][nid]["prompt_file"].removeprefix("../prompts/"), listed)
            self.assertNotIn("prompt_append", g["nodes"][nid])
        for rel in listed:
            with self.subTest(rel):
                src = subprocess.run(["git", "-C", str(CORE), "show", f"{led.commit}:graphloops/prompts/{rel}"],
                                     capture_output=True, check=True).stdout
                self.assertEqual((base / rel).read_bytes(), copyledger.apply(led, rel, src))

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"pass.stubs.yaml", "rejected-thrice.stubs.yaml", "not-ready.stubs.yaml"})
        p = fx["pass.stubs.yaml"]
        self.assertEqual(p["fixture"]["expect"], "completed")
        for role in (*rr.ROLES, rr.WRITE_COLD):
            self.assertIn(role, p["fixture"]["reached"])
        self.assertIs(p["collect"]["ok"], True)
        r = fx["rejected-thrice.stubs.yaml"]
        self.assertEqual((r["report-write-accept"]["ok"], r["report-write-accept"]["done"]), (False, True))
        self.assertIn("dry-run は until_bash を回さず", (BLK / "fixtures" / "rejected-thrice.stubs.yaml").read_text(encoding="utf-8"))
        self.assertIs(r["collect"]["ok"], False)
        n = fx["not-ready.stubs.yaml"]
        self.assertEqual(n["rp-route"]["next"], "")
        self.assertNotIn("report-write", n)
        self.assertIs(n["collect"]["ok"], False)
        for name, f in fx.items():
            for nid, out in f.items():
                if nid in (*rr.ROLES, rr.WRITE_COLD):
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
        """周の締めの後は書き手の節がすぐ ready（頭と初見検査の節は表で absent なので省かれる）"""
        self.board()
        got = rr.route(self.bd, rr.WRITE)
        self.assertEqual((got["next"], got["node"]), (rr.WRITE, "report"), got)
        skipped = entry.open_board(self.bd).rd["skipped"]
        self.assertIn("report.human_items", skipped)
        self.assertIn("report.cold_check", skipped)

    def test_mid_round_not_ready(self):
        self.board("mid")
        got = rr.route(self.bd, rr.WRITE)
        self.assertEqual(got["next"], "")
        self.assertIn("report", got["why"])
        out = rr.collect(self.bd)
        self.assertFalse(out["ok"])
        self.assertIn("ready", out["reason"])

    def test_stopped_run_reaches_report(self):
        """人が周の途中で止めた run も報告の節へ届く（graph の stop.node の下流。本線の answer stop と同じ道）"""
        self.board("stopped")
        self.assertEqual(rr.route(self.bd, rr.WRITE)["next"], rr.WRITE)
        prep, got = self.run_role(rr.WRITE, {"text": "人が止めた run の報告"})
        self.assertTrue(got["ok"], got)
        self.assertIn("stop", pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8"))


class PathCase(_Case):
    def test_full_pass_path(self):
        self.board()
        rec_before = record(self.bd)
        # 書き手: 数の出どころ（盤面の事実）のファイルと、検証器の結果と頭を書く材料を描いた指示書
        self.assertEqual(rr.route(self.bd, rr.WRITE)["next"], rr.WRITE)
        wprep = rr.prep(self.bd, rr.WRITE, self.repo)
        self.assertNotIn("prompt", wprep, "書き手には本文を貼らない（ファイルで読む）")
        wtext = pathlib.Path(wprep["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn("{{", wtext)
        for words in ("検証器の最終結果", "冒頭 3 行は「人が決めること」だけ", "問いの台帳: ", "根本ユニット: "):
            self.assertIn(words, wtext)                          # 本線の指示書（台帳の手直しの後）を盤面の値で描いた
        self.assertIn(wprep["facts_file"], wtext, "書き手に数の出どころを渡す")
        # 初見の読み手: 書き手の頭だけを貼る。盤面・記録・差分の置き場を渡さない
        reply = json.dumps(golden_reply("report"), ensure_ascii=False)
        drawn = rr.write_cold_prep(self.bd, reply)["prompt"]
        self.assertIn(rr.head_of(golden_reply("report")["text"])[:40], drawn)
        self.assertNotIn(str(self.bd), drawn)
        self.assertNotIn(str(self.repo), drawn)
        self.assertNotIn("record.json", drawn)
        got = rr.accept(self.bd, rr.WRITE, reply, self.repo, cold=json.dumps(golden_reply("report.cold_check")))
        self.assertEqual((got["ok"], got["done"], got["give_up"]), (True, True, False), got)
        facts = pathlib.Path(wprep["facts_file"]).read_text(encoding="utf-8")
        out = rr.collect(self.bd)
        self.assertTrue(out["ok"], out)
        self.assertNotIn("human_items_file", out)
        self.assertEqual(out["cold_check"], golden_reply("report.cold_check"), "出口の cold_check は書き手の頭を読んだ初見の読み手の判定")
        self.assertEqual(set(out["rejects"]), {"report"})
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
        prep, got = self.run_role(rr.WRITE, bad)
        self.assertEqual((got["ok"], got["done"], got["give_up"]), (False, False, False), got)
        self.assertIn("セル", got["reason"])
        st = state(self.bd)
        self.assertEqual(st["rounds"][-1]["instances"]["report"]["status"], "pending")
        self.assertNotIn("report", st["rounds"][-1]["done"])
        self.assertTrue(before)
        # 2 回目の指示書の頭に前の拒否の文
        prep2 = rr.prep(self.bd, rr.WRITE, self.repo)
        again = pathlib.Path(prep2["prompt_file"]).read_text(encoding="utf-8")
        self.assertTrue(again.startswith(rr.REJECT_HEADING))
        prepkit.drawn(self, rr.WRITE, again)

    def test_give_up_after_three_then_fallback_report(self):
        self.board()
        rounds = [self.run_role(rr.WRITE, {"text": "| A |\n|---|\n| 説明の文。 |\n"})[1] for _ in range(rr.GIVE_UP_AFTER)]
        self.assertEqual([(g["ok"], g["done"], g["give_up"]) for g in rounds],
                         [(False, False, False)] * (rr.GIVE_UP_AFTER - 1) + [(False, True, True)])
        out = rr.collect(self.bd)
        self.assertFalse(out["ok"])
        self.assertIn("3 回とも", out["reason"])
        rep = pathlib.Path(out["report_file"]).read_text(encoding="utf-8")
        self.assertIn(out["reason"].splitlines()[0], rep, "諦めた事実を報告の頭に出す（黙らない）")
        self.assertIn(rr.MACHINE_HEADING, rep, "諦めても機械の事実は付ける")

    def test_writer_must_not_move_tree(self):
        self.board()
        rr.prep(self.bd, rr.WRITE, self.repo)
        (pathlib.Path(self.repo) / "stray.txt").write_text("書き手が作った", encoding="utf-8")
        try:
            got = rr.accept(self.bd, rr.WRITE, json.dumps(golden_reply("report")), self.repo)
        finally:
            (pathlib.Path(self.repo) / "stray.txt").unlink()
        self.assertFalse(got["ok"])
        self.assertIn("読むだけの役", got["reason"])

    def test_unreadable_reply_is_returned_to_role(self):
        self.board()
        rr.prep(self.bd, rr.WRITE, self.repo)
        got = rr.accept(self.bd, rr.WRITE, "{JSON でない", self.repo)
        self.assertFalse(got["ok"])
        self.assertIn("JSON", got["reason"])


GLOSSARY = BLK / "glossary.json"
GLOSSARY_HEAD = "## 語の定義"
PACK_TERM = "取り込みの前"   # 線 A の機械の報告の固定の行（line_edge.py）に在る語


def pack_definition(case, term):
    case.assertTrue(GLOSSARY.is_file(), "pack の語の定義の一覧 glossary.json が無い")
    terms = json.loads(GLOSSARY.read_text(encoding="utf-8"))["terms"]
    got = [t["definition"] for t in terms if t["term"] == term]
    case.assertEqual(len(got), 1, f"{term} が一覧に 1 つだけ在る")
    return got[0]


class GlossaryCase(unittest.TestCase):
    def test_section_lists_only_terms_in_text(self):
        self.assertTrue(callable(getattr(rr, "glossary_section", None)), "語の定義の節を描く glossary_section が無い")
        terms = [{"term": "語エー", "definition": "定義エー"}, {"term": "語ビー", "definition": "定義ビー"}]
        got = rr.glossary_section("本文は語エーだけを使う", terms)
        self.assertIn(GLOSSARY_HEAD, got)
        self.assertIn("語エー", got)
        self.assertIn("定義エー", got)
        self.assertNotIn("定義ビー", got, "本文に出ない語は並べない")
        self.assertEqual(rr.glossary_section("x", terms), "", "現れる語が無ければ節を付けない")

    def test_pack_list_has_fixed_line_term(self):
        self.assertTrue(pack_definition(self, PACK_TERM))


class GlossaryPortCase(_Case):
    ITEMS = f"## 人が決めること\n\n{PACK_TERM}に人が PR の CI を見るかを決める\n"

    def test_writer_cold_gets_section_outside_body(self):
        """初見の読み手に渡す書き手の頭（write_cold_prep）の後ろへ、機械が語の定義の節を付ける"""
        self.board()
        definition = pack_definition(self, PACK_TERM)
        rr.prep(self.bd, "report-write", self.repo)
        drawn = rr.write_cold_prep(self.bd, json.dumps({"text": self.ITEMS + "\n## 詳しく\n\n本文の続き\n"}, ensure_ascii=False))
        self.assertIn(GLOSSARY_HEAD, drawn["prompt"], "head_of が落とさない所に機械が付ける")
        self.assertIn(definition, drawn["prompt"])
        self.assertGreater(drawn["prompt"].index(GLOSSARY_HEAD), drawn["prompt"].index(self.ITEMS.strip()),
                           "本文の中に差し込まない")
        self.assertNotIn("本文の続き", drawn["prompt"], "頭だけを渡す")

    def test_collect_adds_section_for_terms_in_facts(self):
        """人に渡す report-ai.md: 本文と機械の事実の間に節。語は機械の事実の固定の行からも拾う"""
        self.board()
        definition = pack_definition(self, PACK_TERM)
        mr = self.root / "machine-report-glossary.md"
        body = f"# 機械の報告\n\n- {PACK_TERM}に人が PR の CI を見る\n"
        mr.write_text(body, encoding="utf-8")
        _, got = self.run_role("report-write", golden_reply("report"), machine_report=str(mr))
        self.assertTrue(got["ok"], got)
        rep = pathlib.Path(rr.collect(self.bd, machine_report=str(mr))["report_file"]).read_text(encoding="utf-8")
        self.assertIn(GLOSSARY_HEAD, rep)
        self.assertIn(definition, rep)
        self.assertLess(rep.index(GLOSSARY_HEAD), rep.index(rr.MACHINE_HEADING), "節は本文と機械の事実の間")
        self.assertGreater(rep.index(GLOSSARY_HEAD), rep.index(golden_reply("report")["text"].strip()[:40]))
        self.assertTrue(rep.endswith(body), "機械の事実は書き換えずに最後に付ける")


RUN_TERM = {"term": "次の版の枝", "definition": "この run が直した物を載せて PR に出す作業用の枝"}


class RunTermsCase(_Case):
    """書き手は本文と別に run ごとの語（terms）を返せる。盤面には {text} だけを渡し、語は初見の読み手と報告の節に出す"""

    def test_schema_takes_optional_terms_and_rejects_broken(self):
        role = rr.WRITE
        self.assertEqual(validate_schema({"text": "本文", "terms": [RUN_TERM]}, rr.output_format(role)), [],
                         "書き手の型が任意の terms を受けない")
        self.assertEqual(validate_schema({"text": "本文"}, rr.output_format(role)), [], "terms は任意")
        for bad in ([{"term": "語"}], [{"term": "", "definition": "定義"}], [{"term": "語", "definition": "定義", "x": 1}], "語"):
            self.assertTrue(validate_schema({"text": "本文", "terms": bad}, rr.output_format(role)), bad)

    def test_terms_kept_off_board(self):
        self.board()
        text = f"## 人が決めること\n\n{RUN_TERM['term']}を消すかを決める\n"
        _, got = self.run_role(rr.WRITE, {"text": text, "terms": [RUN_TERM]})
        self.assertTrue(got["ok"], got)
        saved = entry.open_board(self.bd, allow_halted=True).output_of_round("report", entry.open_board(self.bd, allow_halted=True).round)
        self.assertEqual(saved, {"text": text}, "盤面には本文だけを渡す")

    def test_broken_terms_returned_to_writer(self):
        self.board()
        _, got = self.run_role(rr.WRITE, {"text": "頭", "terms": [{"term": "語"}]})
        self.assertEqual((got["ok"], got["done"]), (False, False), got)
        self.assertIn("terms", got["reason"])
        self.assertEqual(state(self.bd)["rounds"][-1]["instances"]["report"]["status"], "pending")

    def test_writer_terms_reach_writer_cold_and_report(self):
        self.board()
        rr.prep(self.bd, "report-write", self.repo)
        reply = {"text": f"{RUN_TERM['term']}は残した\n\n## 人が決めること\n\n無し\n", "terms": [RUN_TERM]}
        drawn = rr.write_cold_prep(self.bd, json.dumps(reply, ensure_ascii=False))
        self.assertIn(RUN_TERM["definition"], drawn["prompt"], "書き手の頭を読む初見の読み手に run の語の定義が届く")
        got = rr.accept(self.bd, "report-write", json.dumps(reply, ensure_ascii=False), self.repo)
        self.assertTrue(got["ok"], got)
        rep = pathlib.Path(rr.collect(self.bd)["report_file"]).read_text(encoding="utf-8")
        self.assertIn(RUN_TERM["definition"], rep)
        self.assertLess(rep.index(RUN_TERM["definition"]), rep.index(rr.MACHINE_HEADING))

    def test_pack_definition_wins_over_run_term(self):
        got = rr.glossary_section(f"{PACK_TERM}に見る", [{"term": PACK_TERM, "definition": "run の別の定義"}])
        self.assertNotIn("run の別の定義", got)
        self.assertEqual(got.count(PACK_TERM), 1, "同じ語を重ねて並べない")


COLD_LINE = "- 初見の読み手の拒否（この周）:"


class RejectCountCase(_Case):
    """拒否の行に種類（cold＝初見の読み手・format＝表のセル・answer＝返答の型や take）を持ち、collect が節ごと・種類ごとの
    回数を出口の rejects と報告の 1 行に出す（文を読まずに数えられる）"""

    def rejected_flow(self):
        self.board()
        redesign = json.dumps({"verdict": "redesign-needed", "stops": ["冒頭"], "guessed": [], "decidable": False})
        passed = json.dumps(golden_reply("report.cold_check"))
        reply = json.dumps(golden_reply("report"), ensure_ascii=False)
        rr.prep(self.bd, "report-write", self.repo)
        got = rr.accept(self.bd, "report-write", json.dumps({"text": "| A |\n|---|\n| 説明の文。 |\n"}), self.repo,
                        cold=passed)                                                                 # format
        self.assertFalse(got["ok"], got)
        rr.prep(self.bd, "report-write", self.repo)
        got = rr.accept(self.bd, "report-write", reply, self.repo, cold=redesign)                  # cold
        self.assertFalse(got["ok"], got)
        rr.prep(self.bd, "report-write", self.repo)
        got = rr.accept(self.bd, "report-write", "{JSON でない", self.repo, cold=passed)           # answer
        self.assertFalse(got["ok"], got)
        return rr.collect(self.bd)

    def test_reject_rows_have_kind(self):
        self.rejected_flow()
        rows = json.loads(entry.open_board(self.bd).work(rr.REJECTS_NAME).read_text(encoding="utf-8"))
        self.assertEqual([(r["node"], r.get("kind")) for r in rows],
                         [("report", "format"), ("report", "cold"), ("report", "answer")])

    def test_collect_counts_rejects_by_kind(self):
        out = self.rejected_flow()
        self.assertFalse(out["ok"], out)   # 3 回とも拒まれて諦めた
        self.assertEqual(out.get("rejects"), {"report": {"cold": 1, "format": 1, "answer": 1}})
        rep = pathlib.Path(out["report_file"]).read_text(encoding="utf-8")
        self.assertIn(f"{COLD_LINE} 1 回", rep, "報告の行は出口の rejects の cold の合計と同じ値")
        self.assertLess(rep.index(rr.MACHINE_HEADING), rep.index(COLD_LINE), "機械の事実の見出しの直後に置く")
        facts = pathlib.Path(out["facts_file"]).read_text(encoding="utf-8")
        self.assertTrue(rep.endswith(facts), "報告の最後は機械の事実のまま")


class RejectCountRowsCase(unittest.TestCase):
    """拒否の行の配列を数える純粋な関数 count_rejects。kind の無い行（kind が入る前の run の行）・知らない kind の行は
    捨てずに unknown へ数える（無い欄を既定値で読む）。node が REPORT_NODES（頭と初見検査が回っていた前の版の節も）に無い行は数えない"""

    def test_rows_without_kind_count_as_unknown(self):
        count = getattr(rr, "count_rejects", None)
        self.assertIsNotNone(count, "report_roles に拒否の行の配列を数える count_rejects が無い")
        rows = [{"node": "report", "reason": "kind が入る前の行"},
                {"node": "report.human_items", "reason": "kind が入る前の行"},
                {"node": "report", "kind": "cold"},
                {"node": "report", "kind": "answer"},
                {"node": "report.human_items", "kind": "format"},
                {"node": "report", "kind": "何か"},
                {"node": "よその節", "kind": "cold"}]
        got = count(rows)
        self.assertEqual(got["report"], {"cold": 1, "format": 0, "answer": 1, "unknown": 2})
        self.assertEqual(got["report.human_items"], {"cold": 0, "format": 1, "answer": 0, "unknown": 1})
        self.assertEqual(got["report.cold_check"], {"cold": 0, "format": 0, "answer": 0, "unknown": 0})
        self.assertNotIn("よその節", got)
        self.assertEqual(rr.REJECT_KINDS, ("cold", "format", "answer"), "unknown は読むときだけの種類で、書ける種類は 3 つのまま")

    def test_round_counts_cold_unpassed_beside_rejects(self):
        """盤面の周のディレクトリ r<N> を数える count_round_rejects は、拒否の回数に並べて、書き手の節（report）に
        上限の回に初見の確かめを通らず受け取った件数（COLD_MARK_NAME の有無で 0 か 1）を出す"""
        count = getattr(rr, "count_round_rejects", None)
        self.assertIsNotNone(count, "report_roles に周のディレクトリを数える count_round_rejects が無い")
        with tempfile.TemporaryDirectory() as td:
            rd = pathlib.Path(td) / "r1"
            rd.mkdir()
            (rd / rr.REJECTS_NAME).write_text(json.dumps([{"node": "report", "kind": "cold"}, {"node": "report"}]),
                                              encoding="utf-8")
            got = count(rd)
            self.assertEqual(got["report"], {"cold": 1, "format": 0, "answer": 0, "unknown": 1, "cold_unpassed": 0})
            (rd / rr.COLD_MARK_NAME).write_text(json.dumps({"reason": "冒頭で止まった"}), encoding="utf-8")
            got = count(rd)
            self.assertEqual(got["report"], {"cold": 1, "format": 0, "answer": 0, "unknown": 1, "cold_unpassed": 1})
            self.assertNotIn("cold_unpassed", got["report.human_items"], "上限の受け取りは書き手の節だけの値")


class RecordInvalidCase(_Case):
    hook = BAD_VALIDATOR_HOOK

    def test_validator_gate_stops_report(self):
        """記録が検証器を通らない run は report の節を出さない（本線の pre: finalize の関所）。ブロックは落ちずに、書き手を
        起こさず、出口は ok: false・record_invalid と理由を返す（報告の節が出ていないので report-ai.md は書かない。人に渡る
        報告はラインの機械の報告で、結末 record_invalid と検証器の出力を載せる）"""
        self.board()
        r = rr.route(self.bd, rr.WRITE)
        self.assertEqual(r["next"], "")
        self.assertIn("検証器", r["why"])
        out = rr.collect(self.bd)
        self.assertFalse(out["ok"])
        self.assertTrue(out["record_invalid"])
        self.assertIn("検証器", out["reason"])
        self.assertEqual(out["report_file"], "")


FIRST_ROUND_HOOK = '''
def board_kwargs(table):
    def runner(b, target):
        return {"exit": 1, "out": "収束を妨げるもの 2 件:\\n  - [block] 未解消: a.py:f — 見本\\n  - 前ラウンドの記録が無い（連続 2 ラウンドの 1 ラウンド目。収束は次ラウンド以降）"}
    return {"validator_runner": runner}
'''


class FirstRoundLineCase(_Case):
    """1 周で止める run で写しの検証器が必ず出す帳尻の行（report.FIRST_ROUND_LINE）は、書き手の指示書の検証器の結果
    （{{validation}}）に渡さない（機械の報告の残りの数えと同じく雑音として除く。実物の AI の報告 56 本のうち 49 本が
    2 周続けての決まりを書いていた）。ほかの阻害の行と件数の見出しは残す"""
    hook = FIRST_ROUND_HOOK

    def test_writer_prompt_drops_first_round_line(self):
        import report
        self.board()
        text = pathlib.Path(rr.prep(self.bd, rr.WRITE, self.repo)["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn(report.FIRST_ROUND_LINE, text)
        self.assertIn("[block] 未解消: a.py:f — 見本", text)
        self.assertIn("収束を妨げるもの 1 件:", text)

    def test_drop_keeps_other_output(self):
        import report
        only = {"exit": 1, "out": f"前置き\n収束を妨げるもの 1 件:\n  - {report.FIRST_ROUND_LINE}\n後ろ"}
        self.assertEqual(report.without_first_round_line(only), {"exit": 1, "out": "前置き\n後ろ"})
        clean = {"exit": 0, "out": "阻害なし"}
        self.assertEqual(report.without_first_round_line(clean), clean)


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
            cold = ""
            if role == rr.WRITE:   # 書き手の輪: 書き手の頭を描いて初見の読み手（ここでは pass の見本）の返答を受け付けに渡す
                drawn = self.ok("cold_prep", writer=json.dumps(reply, ensure_ascii=False))["prompt"]
                self.assertIn(reply["text"].strip().splitlines()[0], drawn)
                # 描き方は report.cold_check の読み手と同じ（render_body: 穴を残さず、report.cold_check の schema の断りが付く）
                self.assertIn(rr.rolekit.SCHEMA_NOTE, drawn)
                self.assertIn('"redesign-needed"', drawn)
                self.assertNotIn("{{", drawn)
                self.assertNotIn(rr.COLD_PASTE, drawn)
                cold =json.dumps(golden_reply("report.cold_check"), ensure_ascii=False)
            got = self.ok("accept", role=role, reply=json.dumps(reply, ensure_ascii=False), cold=cold)
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
        self.assertEqual(self.ok("route", role=rr.WRITE)["next"], rr.WRITE)
        exited, rounds = self.run_loop(rr.WRITE, golden_reply("report"))
        self.assertEqual(exited, 1, rounds)
        self.assertEqual(rounds[0][1]["reason_file"], "")
        out = self.ok("collect", machine_report="")
        self.assertTrue(out["ok"], out)
        self.assertTrue(pathlib.Path(out["report_file"]).is_file())

    def test_loop_gives_up_after_three(self):
        self.board()
        self.assertEqual(self.ok("route", role=rr.WRITE)["next"], rr.WRITE)
        exited, rounds = self.run_loop(rr.WRITE, {"text": "| A |\n|---|\n| 説明の文。 |\n"})
        self.assertEqual(exited, rr.GIVE_UP_AFTER, "輪が上限まで抜けない（Archon は run を落とす）")
        self.assertTrue(all(pathlib.Path(a["reason_file"]).is_file() for _, a in rounds), "拒否の文はファイルで渡す（R44）")
        out = self.ok("collect", machine_report="")
        self.assertFalse(out["ok"])

    def test_exit_two_on_wiring(self):
        self.board()
        rc, _, err = self.run_script("route", drop=("ARTIFACTS_DIR",), role=rr.WRITE)
        self.assertEqual(rc, 2, err)
        self.assertIn("ARTIFACTS_DIR", err)
        rc, _, err = self.run_script("prep")
        self.assertEqual(rc, 2)
        self.assertIn("INPUTS_ROLE", err)
        rc, out, err = self.run_script("prep", role="report-cold", machine_report="")   # もう役に無い名（頭と初見検査は absent）
        self.assertEqual(rc, 2, out)
        self.assertEqual(out, "")
        rc, _, err = self.run_script("route", role="no-such-role")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
