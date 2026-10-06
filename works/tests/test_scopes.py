"""部品の置き場（依頼 239）の口の検査: 流れの道具の口 flow_adapter と、部品ごとの宣言 manifest の読み口 scopes。

- AdapterCase: flow_adapter が Archon の環境変数だけから scope・置き場・入力を読むこと、聞き直しの口（session_handle・resume）が
  まだ作られず、誰にも呼ばれていないこと
- ManifestCase: 全部のブロックと線の manifest.json が manifest.schema.json に合い、公開の名の持ち主が 1 つで、Consumes が
  在る Produces を指し、JSON の Produces が Schema を持ち、測り M2（台帳の inventory.json）の公開の名が宣言されていること
- ClaimCase: 盤面の周の scopes.json への scope の登録（同じ scope の 2 つ目のブロックと盤面の根の物とのぶつかりを拒む）と、
  scope の根に分かれた同じ名のファイルを集める口（all_rounds・each）

盤面・git・子のプロセスを使わない（一時の置き場のファイルだけ）。
"""
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE / "graphloops"))

import flow_adapter  # noqa: E402
import scopes  # noqa: E402
from board import BoardGap  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

NODE_EXECUTION = "ARCHON_NODE_EXECUTION"

# 測り M2（.superpowers/sdd/2026-10-03-block-scope/inventory.json）の class published と per_include の名を字のまま
INVENTORY_PUBLISHED = (
    "design-premises.json", "design.json", "fixture-outside/**", "gate-marks.json", "github.json", "judgment.json",
    "next-request.json", "no-turn-exits.json", "plan-fields.json", "premises.json", "purpose.json", "rejects-*.json",
    "report.md", "structure-state.json", "brief-*.md", "briefs.json", "delta-verdicts.json", "final-gate-answer.json",
    "final-gate.md", "fix-held-reply.json", "fix-shape.json", "gate.md", "human-notes.md", "judged.json", "lens.json",
    "plan-converge.json", "plan-converge/**", "pr-excluded.json", "reads-pr-check.json", "reads-rejudge.json",
    "rejudge-diff.json", "rejudge-exit.json", "rejudge-session.json", "replan-gate.md", "replan-notes.md", "replan.json",
    "start.json", "structure-units.json")
INVENTORY_PER_INCLUDE = ("fix-unit-rows.json", "changes.json", "reads-*.json", "reads-fix.json", "reads-plan-block.json",
                         "reads-replan-block.json")
# M2 の where が root の名（盤面の根。manifest の at: root）。rejects-*.json は持ち主ごとの名に割って宣言する
INVENTORY_ROOT = ("design-premises.json", "design.json", "fixture-outside/**", "gate-marks.json", "github.json", "judgment.json",
                  "next-request.json", "no-turn-exits.json", "plan-fields.json", "premises.json", "purpose.json",
                  "rejects-*.json", "report.md", "structure-state.json", "fix-unit-rows.json")
# M2 の published から振り直した名（blk-fix の 2 つの include が同じ周に両方書くので、公開の名にすると持ち主が 2 つになる）:
# 外が読む物は per_include（各 include の写しが scope に残る）、blk-fix の中だけが読む物は私物（宣言しない）
RECLASSIFIED = {"brief-*.md": "per_include",          # replan.material（線の h-replan）が読む
                "fix-held-reply.json": "per_include",  # replan.hand_held（線の h-rejudge）と報告が読む
                "briefs.json": "private"}              # 読むのは blk-fix の planbrief・fixrules・スクリプトだけ


def _execution(path: str) -> str:
    """Archon v0.11.1 が script の節に渡す ARCHON_NODE_EXECUTION の形（測り M1。path 以外の欄は値を問わない）"""
    return json.dumps({"runId": "r", "path": path, "invocation": {"id": "i", "loopPath": []}, "attempt": {"id": "a"}})


class AdapterCase(unittest.TestCase):
    def _with(self, env: dict):
        """os.environ を env だけにして返す文脈（試験の外の値を混ぜない）"""
        return mock.patch.dict(os.environ, env, clear=True)

    def test_current_scope_reads_measured_source(self):
        # 形 A（測り M1）: path の最初の "__" の前が include の名。輪の中は <include>__<輪>.<節>、線の最上段は "__" を持たない
        for path, want in (("fixing__fix-prep", "fixing"), ("refitting__fix-loop.fix-accept", "refitting"),
                           ("planning__envpost", "planning"), ("h-fix", ""), ("start", "")):
            with self._with({NODE_EXECUTION: _execution(path)}):
                self.assertEqual(flow_adapter.current_scope(), want, path)
        for env in ({}, {NODE_EXECUTION: ""}):
            with self._with(env):
                self.assertEqual(flow_adapter.current_scope(), "")
        # 読むのは 1 つの出どころだけ: 形 B の入力 INPUTS_INCLUDE_ID は今は読まない
        with self._with({"INPUTS_INCLUDE_ID": "refitting"}):
            self.assertEqual(flow_adapter.current_scope(), "")
        with self._with({NODE_EXECUTION: _execution("fixing__x"), "INPUTS_INCLUDE_ID": "refitting"}):
            self.assertEqual(flow_adapter.current_scope(), "fixing")

    def test_fan_out_child_scope_is_fan_node_and_item_mark(self):
        # fan_out の子（2026-10-04 に実測。印は items の値の sha256 の頭 16 字）: scope は <fan の節>--<印の頭 8 字>。子ごとに分かれ、
        # 同じ値なら走り直しても同じ。輪の中の子の節（<輪>.<節>）も同じ scope
        mark = hashlib.sha256(b"a").hexdigest()[:16]
        for node in ("work", "fix-loop.fix-accept"):
            with self._with({NODE_EXECUTION: _execution(f"__archon_fan_out__fan__root__{mark}__fan__{mark}__{node}")}):
                self.assertEqual(flow_adapter.current_scope(), f"fan--{mark[:8]}")
        other = hashlib.sha256(b"b").hexdigest()[:16]
        with self._with({NODE_EXECUTION: _execution(f"__archon_fan_out__fan__root__{other}__fan__{other}__work")}):
            self.assertEqual(flow_adapter.current_scope(), f"fan--{other[:8]}")
        self.assertEqual((flow_adapter.fan_node(f"fan--{mark[:8]}"), flow_adapter.fan_node("fixing"), flow_adapter.fan_node("")),
                         ("fan", "", ""))

    def test_fan_out_unmeasured_shapes_refused(self):
        # 測っていない形（root でない親・入れ子の中の fan_out・印の食い違い）と、fan_out の子の名と紛れる include の名は拒む
        m = "ca978112ca1bbdca"
        for path in (f"__archon_fan_out__fan__fixing__{m}__fan__{m}__work",
                     f"fixing____archon_fan_out__fan__root__{m}__fan__{m}__work",
                     f"fixing__inner__archon_fan_out__fan__root__{m}__fan__{m}__work",
                     f"__archon_fan_out__fan__root__{m}__fan__3e23e8160039594a__work",
                     f"__archon_fan_out__r2__root__{m}__r2__{m}__work",
                     "fix--x__y"):
            with self.subTest(path=path), self._with({NODE_EXECUTION: _execution(path)}):
                with self.assertRaises(ValueError):
                    flow_adapter.current_scope()

    def test_current_scope_refuses_unreadable_execution(self):
        # 在るのに読めない値は黙って線（空の scope）に落とさない（2 度目の include が 1 度目の置き場に書く穴になる）
        for raw in ("{", "[]", json.dumps({"runId": "r"}), json.dumps({"path": 3})):
            with self._with({NODE_EXECUTION: raw}):
                with self.assertRaises(ValueError) as cm:
                    flow_adapter.current_scope()
                self.assertIn(NODE_EXECUTION, str(cm.exception))

    def test_current_scope_refuses_bad_include_names(self):
        # include の名が scope の名の決まり（board.SCOPE_RULE と同じ字の組）に外れれば、置き場に書く・登録する前に拒む。
        # r2 は周の置き場 r<N> に私物を書き込む名
        import script_io
        for path in ("r2__fix-prep", "1fix__x", "-x__y", "a.b__c"):
            with self.subTest(path=path), self._with({NODE_EXECUTION: _execution(path)}):
                with self.assertRaises(ValueError) as cm:
                    flow_adapter.current_scope()
                self.assertIn(path.split("__")[0], str(cm.exception))
                with self.assertRaises(ValueError):
                    script_io.scope_dir(pathlib.Path("/b"))
        with self._with({NODE_EXECUTION: _execution("r2x__y")}):
            self.assertEqual(flow_adapter.current_scope(), "r2x")
        import board   # 盤面の scope の名の決まりと同じ字の組（board は flow_adapter を読まないので両方が字で持つ）
        self.assertEqual((flow_adapter.SCOPE_NAME.pattern, flow_adapter.ROUND_NAME.pattern),
                         (board._SCOPE_NAME.pattern, board._ROUND_NAME.pattern))

    def test_artifact_root_none_when_missing_or_empty(self):
        for env in ({}, {"ARTIFACTS_DIR": ""}):
            with self._with(env):
                self.assertIsNone(flow_adapter.artifact_root())
        with self._with({"ARTIFACTS_DIR": "/tmp/art"}):
            self.assertEqual(flow_adapter.artifact_root(), pathlib.Path("/tmp/art"))

    def test_input_reads_inputs_env(self):
        with self._with({"INPUTS_JUDGMENT_FILE": "/x", "INPUTS_BASE_REV": ""}):
            self.assertEqual(flow_adapter.input("judgment_file"), "/x")
            self.assertEqual(flow_adapter.input("base_rev"), "")   # 既定の空は届く（測り M1 の (c)）。無いとは分ける
            self.assertIsNone(flow_adapter.input("reply"))

    def test_ask_back_mouths_not_built(self):
        for call in (flow_adapter.session_handle, lambda: flow_adapter.resume({}, "q")):
            with self.assertRaises(NotImplementedError) as cm:
                call()
            self.assertEqual(str(cm.exception), "聞き直しはまだ作らない（依頼 239 の §5。形は session.schema.json）")
        self.assertTrue((CORE / "session.schema.json").is_file())

    def test_ask_back_mouths_have_no_callers(self):
        callers = re.compile(r"session_handle|flow_adapter\s*\.\s*resume\b|from\s+flow_adapter\s+import[^\n]*\bresume\b")
        found = [str(p.relative_to(ROOT)) for p in sorted(ROOT.rglob("*.py"))
                 if "tests" not in p.relative_to(ROOT).parts and p.name != "flow_adapter.py"
                 and callers.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(found, [])


class ManifestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.all = scopes.manifests()

    def _declared(self):
        """(owner, produce の行) の全部"""
        return [(owner, p) for owner, m in self.all.items() for p in m["produces"]]

    def test_every_owner_has_valid_manifest(self):
        want = {p.name for p in ROOT.glob("blk-*") if p.is_dir()} | {p.parent.name for p in ROOT.glob("*/nodes.json")}
        self.assertEqual(set(self.all), want)
        self.assertIn("darkfactory", self.all)
        for owner, m in self.all.items():
            self.assertEqual(m["owner"], owner)
            self.assertEqual(scopes.manifest(ROOT / owner), m)

    def test_published_name_has_one_owner(self):
        seen = {}
        for owner, p in self._declared():
            if p.get("per_include"):
                continue
            self.assertNotIn(p["name"], seen, f"{p['name']} を {seen.get(p['name'])} と {owner} が出す")
            seen[p["name"]] = owner
            self.assertEqual(scopes.owner_of(p["name"]), owner, p["name"])   # ほかの owner の形の陰にも入らない
        # published は盤面の work が周の置き場 r<N>/ に置く名だけ（at: root の名は盤面の根に直に書かれ、work を通らない）
        rounds = {name for owner, p in self._declared() if not p.get("per_include") and p.get("at", "round") == "round"
                  for name in [p["name"]]}
        self.assertEqual(scopes.published(), frozenset(rounds))
        self.assertLess(scopes.published(), frozenset(seen))
        self.assertEqual(scopes.round_names(), scopes.published() | scopes.SHARED_ROUND)
        self.assertIsNone(scopes.owner_of("rule-tree.json"))   # 宣言していない名は持ち主が無い（私物）

    def test_consumes_point_at_a_producer(self):
        # consumes は名だけ（部品はほかの部品の名を書かない）。出す owner は名から引き、ちょうど 1 つで、自分ではない
        for owner, m in self.all.items():
            for c in m["consumes"]:
                self.assertEqual(set(c), {"name"}, f"{owner} の consumes {c}")
                got = scopes.owner_of(c["name"])
                self.assertIsNotNone(got, f"{owner} の consumes {c} を公開の名に出す owner が無い")
                self.assertNotEqual(got, owner, f"{owner} の consumes {c}（自分の物は読むのに宣言しない）")

    def test_json_produces_have_schema(self):
        for owner, p in self._declared():
            if p["format"] != "json":
                self.assertNotIn("schema", p, f"{owner} の {p['name']}")
                continue
            path = ROOT / owner / p["schema"]
            self.assertTrue(path.is_file(), f"{owner} の {p['name']}: {path}")
            schema = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(schema, dict)
            self.assertIsInstance(validate_schema({}, schema), list)
            self.assertIsNot(schema.get("additionalProperties"), False, f"{path}: 今の書き手を落とさないよう閉じない")

    def test_inventory_names_are_declared(self):
        decl = self._declared()
        for names, per in ((INVENTORY_PUBLISHED, False), (INVENTORY_PER_INCLUDE, True)):
            for name in names:
                # 字のまま宣言しているか、M2 の形（rejects-*.json）を持ち主ごとの名に割って宣言している
                hit = [(o, p) for o, p in decl if p["name"] == name] or [(o, p) for o, p in decl if scopes.matches(p["name"], name)]
                want = RECLASSIFIED.get(name, "per_include" if per else "published")
                if want == "private":
                    self.assertEqual(hit, [], name)
                    continue
                self.assertTrue(hit, name)
                self.assertTrue(all(bool(p.get("per_include")) is (want == "per_include") for _, p in hit), f"{name}: {hit}")
                at = "root" if name in INVENTORY_ROOT else "round"
                self.assertTrue(all(p.get("at", "round") == at for _, p in hit), f"{name}: {hit}（M2 の where は {at}）")

    def test_borrowed_shape_keeps_notice(self):
        doc = json.loads((CORE / "manifest.schema.json").read_text(encoding="utf-8"))
        self.assertIn("writing-plans", doc["description"])
        self.assertIn(".shared/borrow/superpowers/6.4.2/LICENSE", doc["description"])
        lic = (ROOT / ".shared/borrow/superpowers/6.4.2/LICENSE").read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2025 Jesse Vincent", lic)
        self.assertIn("Permission is hereby granted", lic)

    def test_broken_manifest_names_path_and_errors(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t) / "blk-x"
            d.mkdir()
            with self.assertRaises(scopes.ManifestBroken) as cm:
                scopes.manifest(d)
            self.assertIn(str(d / "manifest.json"), str(cm.exception))
            self.assertIsInstance(cm.exception, BoardGap)
            (d / "manifest.json").write_text(json.dumps({
                "owner": "blk-y", "consumes": [{"name": "x.json", "from": "blk-z"}],
                "produces": [{"name": "a.md"}, {"name": "b.json", "format": "json"}, {"name": "c/*/../d.md", "format": "md"},
                             {"name": "e.json", "format": "json", "schema": "schemas/none.schema.json"}]}), encoding="utf-8")
            with self.assertRaises(scopes.ManifestBroken) as cm:
                scopes.manifest(d)
            msg = str(cm.exception)
            for part in (str(d / "manifest.json"), "blk-y", "blk-x", "'format'", "'schema'", "'from'", "c/*/../d.md",
                         "schemas/none.schema.json"):
                self.assertIn(part, msg)

    def test_patterns_match_per_segment(self):
        self.assertTrue(scopes.matches("rejects-r2.design.json", "rejects-*.json"))
        self.assertFalse(scopes.matches("rejects-a/b.json", "rejects-*.json"))   # * は段をまたがない
        self.assertTrue(scopes.matches("plan-converge/p1/x.md", "plan-converge/**"))
        self.assertFalse(scopes.matches("plan-converge", "plan-converge/**"))


class ClaimCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.board = pathlib.Path(self._tmp.name) / "board"
        self.board.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def registry(self, n=1) -> dict:
        return json.loads((self.board / f"r{n}" / "scopes.json").read_text(encoding="utf-8"))

    def put(self, rel: str) -> pathlib.Path:
        p = self.board / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
        return p

    def test_claim_same_scope_same_block_twice_is_ok(self):
        # Archon の再開で同じ include が同じ周に走り直す: 2 度目も通り、登録は 1 行のまま
        scopes.claim(self.board, 1, "fixing", "blk-fix")
        (self.board / "fixing" / "r1").mkdir(parents=True)   # 1 度目の書き込みで scope の根が出来ている
        scopes.claim(self.board, 1, "fixing", "blk-fix")
        self.assertEqual(self.registry(), {"fixing": {"block": "blk-fix", "order": 1}})
        scopes.claim(self.board, 1, "refitting", "blk-fix")
        self.assertEqual(self.registry()["refitting"], {"block": "blk-fix", "order": 2})
        scopes.claim(self.board, 2, "fixing", "blk-fix")   # 次の周も同じ scope は通る（根の物は前の周の登録）
        self.assertEqual(self.registry(2), {"fixing": {"block": "blk-fix", "order": 1}})

    def test_claim_other_block_same_scope_refused(self):
        scopes.claim(self.board, 1, "fixing", "blk-fix")
        with self.assertRaises(BoardGap) as cm:
            scopes.claim(self.board, 1, "fixing", "blk-plan")
        self.assertIn("blk-fix", str(cm.exception))
        self.assertIn("blk-plan", str(cm.exception))
        with self.assertRaises(BoardGap) as cm:   # 別の周に名乗り直しても同じ
            scopes.claim(self.board, 2, "fixing", "blk-plan")
        self.assertIn("blk-fix", str(cm.exception))
        self.assertEqual(self.registry(), {"fixing": {"block": "blk-fix", "order": 1}})

    def test_claim_refuses_root_entry_that_is_not_a_scope(self):
        self.put("out/r1/p3.fix.json")
        for scope in ("out", "prompts", "tdd-3", "fixture-outside"):   # 根の記録のフォルダ（在っても無くても）
            with self.subTest(scope=scope), self.assertRaises(BoardGap) as cm:
                scopes.claim(self.board, 1, scope, "blk-fix")
            self.assertIn(str(self.board / scope), str(cm.exception))
        with self.assertRaises(BoardGap):   # 登録の持ち主の鍵（照らしが書く owns）と同じ名
            scopes.claim(self.board, 1, scopes.OWNS, "blk-fix")
        self.put("notes")   # 根の同じ名のフォルダでない物
        with self.assertRaises(BoardGap):
            scopes.claim(self.board, 1, "notes", "blk-fix")
        self.assertFalse((self.board / "r1" / "scopes.json").exists())
        self.put("judging/judge-snapshot.json")   # 盤面を開かない節が先に scope の根に書いた（intake）
        scopes.claim(self.board, 1, "judging", "blk-judge")
        self.assertEqual(self.registry(), {"judging": {"block": "blk-judge", "order": 1}})

    def test_all_rounds_covers_scoped_files(self):
        scopes.claim(self.board, 1, "fixing", "blk-fix")
        scopes.claim(self.board, 1, "refitting", "blk-fix")
        want = [self.put("r1/reads-x.json"), self.put("fixing/r1/reads-fix.json"), self.put("refitting/r1/reads-fix.json")]
        r2 = self.put("r2/reads-y.json")
        self.put("unregistered/r1/reads-z.json")    # 登録の無い置き場は scope でない
        self.put("refitting/reads-w.json")          # 周の置き場の外は数えない
        self.assertEqual(scopes.all_rounds(self.board, "reads-*.json"), want + [r2])

    def test_each_reads_round_place_then_scopes_in_claim_order(self):
        b = types.SimpleNamespace(dir=self.board, round=1)
        self.assertEqual(scopes.each(b, "fix-held-reply.json"), [])
        scopes.claim(self.board, 1, "fixing", "blk-fix")
        scopes.claim(self.board, 1, "refitting", "blk-fix")
        second = self.put("refitting/r1/fix-held-reply.json")
        first = self.put("fixing/r1/fix-held-reply.json")
        self.assertEqual(scopes.each(b, "fix-held-reply.json"), [first, second])
        line = self.put("r1/fix-held-reply.json")   # scope の無い盤面（線・今までの置き場）の物が先
        self.assertEqual(scopes.each(b, "fix-held-reply.json"), [line, first, second])
        self.assertEqual(scopes.scope_roots(b), [self.board, self.board / "fixing", self.board / "refitting"])

    def test_manifests_read_once_per_process(self):
        # 盤面を開くたび（公開の名・根の物とのぶつかり）に全部の manifest を読み直して照らさない。返す写しを書き換えても控えは変わらない
        scopes._loaded.cache_clear()
        self.addCleanup(scopes._loaded.cache_clear)
        with mock.patch.object(scopes, "manifest", wraps=scopes.manifest) as read:
            scopes.round_names()
            scopes.claim(self.board, 1, "fixing", "blk-fix")
            scopes.round_names()
            got = scopes.manifests()
            got["blk-fix"]["produces"].clear()
            self.assertEqual(read.call_count, len(scopes.manifests()))
        self.assertTrue(scopes.manifests()["blk-fix"]["produces"])

    def test_running_block_reads_script_place(self):
        for argv0, want in ((str(ROOT / "blk-fix" / "scripts" / "accept.py"), "blk-fix"),
                            (str(ROOT / "darkfactory" / "scripts" / "edge.py"), "darkfactory"),
                            ("-m", ""), ("/x/unittest/__main__.py", ""), ("", "")):
            with self.subTest(argv0=argv0), mock.patch.object(sys, "argv", [argv0]):
                self.assertEqual(scopes.running_block(), want)


def _fake_pack(root: pathlib.Path) -> pathlib.Path:
    """偽の pack: blk-fix（公開の fix-held-reply.json・per_include の reads-fix.json）と blk-lens（required の lens.json）"""
    pack = root / "pack"
    loose = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
    for owner, doc in (
            ("blk-fix", {"owner": "blk-fix", "consumes": [{"name": "lens.json"}],
                         "produces": [{"name": "fix-held-reply.json", "format": "json", "schema": "schemas/x.schema.json"},
                                      {"name": "reads-fix.json", "format": "json", "schema": "schemas/o.schema.json",
                                       "per_include": True}]}),
            ("blk-lens", {"owner": "blk-lens", "consumes": [],
                          "produces": [{"name": "lens.json", "format": "json", "schema": "schemas/x.schema.json",
                                        "required": True}]})):
        d = pack / owner
        (d / "schemas").mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
        (d / "schemas" / "x.schema.json").write_text(json.dumps(loose), encoding="utf-8")
        (d / "schemas" / "o.schema.json").write_text(json.dumps({"type": "object"}), encoding="utf-8")
    return pack


class GateCase(unittest.TestCase):
    """窓（scope が盤面を開いてから次の scope が開くまで）の間の盤面の変化を、その scope のブロックの宣言に照らす（偽の盤面と偽の pack）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = pathlib.Path(self._tmp.name)
        self.pack = _fake_pack(root)
        self.board = root / "board"
        for rel in ("state.json", "trace.jsonl", "r1/start.json"):
            self.put(rel, "{}")

    def put(self, rel: str, text: str = '{"ok": true}') -> pathlib.Path:
        p = self.board / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def window(self, scope: str, block: str) -> dict:
        return {"scope": scope, "block": block, "round": 1, "files": scopes.snapshot(self.board)}

    def check(self, window: dict) -> list:
        return scopes.check_window(self.board, window, self.pack)

    def test_snapshot_lists_every_file_with_size_and_mtime(self):
        snap = scopes.snapshot(self.board)
        self.assertEqual(set(snap), {"state.json", "trace.jsonl", "r1/start.json"})
        st = (self.board / "r1" / "start.json").stat()
        self.assertEqual(snap["r1/start.json"], [st.st_size, st.st_mtime_ns])
        self.assertEqual(scopes.snapshot(self.board / "none"), {})

    def test_write_in_own_scope_root_passes(self):
        w = self.window("fixing", "blk-fix")
        self.put("fixing/r1/x.json")
        self.put("fixing/r1/deep/y.md", "y")
        self.assertEqual(self.check(w), [])

    def test_write_in_other_scope_refused(self):
        w = self.window("fixing", "blk-fix")
        self.put("refitting/r1/x.json")
        got = self.check(w)
        self.assertEqual(len(got), 1, got)
        for part in ("refitting/r1/x.json", "fixing", "blk-fix", "fix-held-reply.json", "reads-fix.json"):
            self.assertIn(part, got[0])

    def test_write_to_shared_record_passes(self):
        w = self.window("fixing", "blk-fix")
        self.put("state.json", '{"round": 1, "more": true}')
        self.put("trace.jsonl", '{"op": "x"}\n')
        self.put("out/r1/p3.fix.json")
        self.put("r1/conflicts.json")
        self.put("r1/scopes.json", '{"fixing": {"block": "blk-fix", "order": 1}}')
        self.put("scope-window.json")
        self.assertEqual(self.check(w), [])

    def test_test_result_caches_pass(self):
        # 受け付けが base の試験の結末を控える置き場（周の置き場と盤面の根。fixing と refitting の両方の scope が書く。run 195g の
        # 0.2.28 で宣言の外として run が止まった）
        w = self.window("fixing", "blk-fix")
        self.put("r1/fixgates-base.json")
        self.put("accept-rev-cache.json")
        self.assertEqual(self.check(w), [])

    def test_published_name_records_owner(self):
        w = self.window("fixing", "blk-fix")
        self.put("r1/fix-held-reply.json")
        self.assertEqual(self.check(w), [])
        reg = json.loads((self.board / "r1" / "scopes.json").read_text(encoding="utf-8"))
        self.assertEqual(reg["owns"], {"fix-held-reply.json": "fixing"})
        self.assertEqual(self.check(w), [])   # 同じ窓を照らし直しても同じ持ち主

    def test_second_owner_of_published_name_refused(self):
        w = self.window("fixing", "blk-fix")
        self.put("r1/fix-held-reply.json")
        self.assertEqual(self.check(w), [])
        w2 = self.window("refitting", "blk-fix")
        self.put("r1/fix-held-reply.json", '{"ok": false, "again": 1}')
        got = self.check(w2)
        self.assertEqual(len(got), 1, got)
        for part in ("r1/fix-held-reply.json", "fixing", "refitting"):
            self.assertIn(part, got[0])

    def test_undeclared_round_place_write_refused(self):
        w = self.window("fixing", "blk-fix")
        self.put("r1/rule-tree.json")
        self.put("loose.txt", "x")       # 盤面の根の宣言していない名
        (self.board / "r1" / "start.json").unlink()   # 消えたも変化に数える
        got = self.check(w)
        self.assertEqual(len(got), 3, got)   # 最初の 1 つで止めずに全部を並べる
        self.assertTrue(any("r1/rule-tree.json" in g for g in got), got)
        self.assertTrue(any("loose.txt" in g for g in got), got)
        self.assertTrue(any("r1/start.json" in g for g in got), got)

    def test_opener_own_root_not_charged_to_closing_window(self):
        # 盤面を開く前に自分の scope の根に書く節（依頼の受け付けの intake）の物は、次に開く scope（opener）の物で、閉じる窓の物でない
        w = self.window("gathering", "blk-fix")
        self.put("judging/judge-snapshot.json")
        self.assertEqual(scopes.check_window(self.board, w, self.pack, opener="judging"), [])
        got = self.check(w)
        self.assertEqual(len(got), 1, got)
        self.assertIn("judging/judge-snapshot.json", got[0])

    def test_unknown_block_checked_by_published_owner(self):
        # 起こされたブロックが分からない窓（running_block が ""）は、公開の名の持ち主で照らす（ブロックの名に頼らない）
        w = self.window("fixing", "")
        self.put("r1/fix-held-reply.json")
        self.put("fixing/r1/x.json")
        self.assertEqual(self.check(w), [])
        self.put("r1/rule-tree.json")
        got = self.check(w)
        self.assertEqual(len(got), 1, got)
        self.assertIn("r1/rule-tree.json", got[0])

    def test_line_window_not_checked(self):
        w = self.window("", "darkfactory")
        self.put("refitting/r1/x.json")
        self.put("r1/rule-tree.json")
        self.assertEqual(self.check(w), [])

    def test_missing_required_listed_not_refused(self):
        # required の出力の欠けは照らしの誤りにしない（役が落ちた部品の窓を止めると、落ちた理由が隠れ報告も書けない）。
        # missing_required が並べ、呼び手が trace と報告に載せる
        w = self.window("lensing", "blk-lens")
        self.assertEqual(self.check(w), [])
        self.assertEqual(scopes.missing_required(self.board, w, self.pack), ["r1/lens.json"])
        self.put("r1/lens.json")
        self.assertEqual(scopes.missing_required(self.board, w, self.pack), [])
        fixing = self.window("fixing", "blk-fix")   # required でない物は無くてよい
        self.assertEqual((self.check(fixing), scopes.missing_required(self.board, fixing, self.pack)), ([], []))
        self.assertEqual(scopes.missing_required(self.board, self.window("lensing", ""), self.pack), [])

    def test_json_produce_schema_mismatch_refused(self):
        w = self.window("fixing", "blk-fix")
        self.put("r1/fix-held-reply.json", '{"ok": "yes"}')
        self.put("fixing/r1/reads-fix.json", "{")   # per_include の物も照らす（読めない JSON）
        got = self.check(w)
        self.assertEqual(len(got), 2, got)
        held = next(g for g in got if "fix-held-reply.json" in g)
        self.assertIn("$.ok", held)
        self.assertIn("x.schema.json", held)
        self.assertTrue(any("fixing/r1/reads-fix.json" in g for g in got), got)

    def test_reads_outside_listed_not_refused(self):
        w = self.window("fixing", "blk-fix")
        rows = [{"path": str(self.board / p), "hook": "read", "event": None}
                for p in ("refitting/r1/y.md", "fixing/r1/brief-1.md", "r1/lens.json", "r1/start.json", "out/r1/p1.json")]
        rows.append({"path": "src/app.py", "hook": "read", "event": None})   # 盤面の外（リポジトリの相対）は数えない
        self.put("fixing/r1/reads-fix.json", json.dumps({"role": "fix", "node_path": "fixing__fix", "rows": rows,
                                                         "sources": {"hook": True, "events": "none"}, "missing": []}))
        self.assertEqual(self.check(w), [])
        self.assertEqual(scopes.reads_outside(self.board, w, self.pack), ["r1/start.json", "refitting/r1/y.md"])
        self.assertEqual(scopes.reads_outside(self.board, self.window("", "darkfactory"), self.pack), [])

    def test_fan_children_share_one_window(self):
        # fan_out の子は 1 つの窓（鍵 <fan の節>--*）を分け合う: どの子の scope の根も窓の scope の根として通り、公開の名の持ち主は
        # 鍵で記録する。子の外（ほかの include の根・宣言の外の名）への書き込みは今までどおり誤り
        key = scopes.window_key("fan--aaaa1111")
        self.assertEqual((key, scopes.window_key("fixing"), scopes.window_key("")), ("fan--*", "fixing", ""))
        w = self.window(key, "blk-fix")
        self.put("fan--aaaa1111/r1/notes.md", "a")
        self.put("fan--bbbb2222/r1/reads-fix.json")
        self.put("r1/fix-held-reply.json")
        self.assertEqual(self.check(w), [])
        reg = json.loads((self.board / "r1" / "scopes.json").read_text(encoding="utf-8"))
        self.assertEqual(reg["owns"], {"fix-held-reply.json": key})
        self.put("refitting/r1/x.json")
        self.put("fan/r1/x.json")   # fan の節の名そのものの置き場は子の物でない
        got = self.check(w)
        self.assertEqual(len(got), 2, got)
        self.assertTrue(all("fan--*" in g for g in got), got)
        # 子が盤面を開く前に自分の根に書いた物は、子が閉じる前の窓の物に数えない（どの子が先に開いても）
        prev = self.window("judging", "blk-fix")
        self.put("fan--cccc3333/r1/early.md", "c")
        self.assertEqual(scopes.check_window(self.board, prev, self.pack, opener=key), [])

    def test_shared_patterns_cover_round_and_root_records(self):
        for path in ("state.json", "out/r1/a.json", "r12/libdocs/x.md", "r1/scopes.json.lock", "scope-window.json", "state.json.lock",
                     "diff-r1.patch", "prompts/r1/fix.md"):
            self.assertTrue(scopes.shared(path), path)
        for path in ("r1/rule-tree.json", "fixing/r1/a.json", "r1/x-r1.patch"):
            self.assertFalse(scopes.shared(path), path)
        self.assertEqual(scopes.SHARED_ROUND, frozenset(p.split("/", 1)[1] for p in scopes.SHARED if p.startswith("r[0-9]*/")))
        self.assertLessEqual({"out", "runs", "prompts"}, scopes.ROOT_DIRS)


class EnterCase(unittest.TestCase):
    """scopes.enter が fan_out の子の同時の開きで窓を互いに閉じないこと（本物の pack の blk-fix の宣言。一時の盤面のファイルだけ）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.board = pathlib.Path(self._tmp.name) / "board"
        for rel in ("state.json", "trace.jsonl"):
            self.put(rel, "{}")

    def put(self, rel: str, text: str = "x") -> None:
        p = self.board / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def window(self) -> dict:
        return json.loads((self.board / scopes.WINDOW).read_text(encoding="utf-8"))

    def test_sibling_does_not_close_first_childs_window(self):
        a, b = "fan--aaaa1111", "fan--bbbb2222"
        self.assertEqual(scopes.enter(self.board, 1, "", "darkfactory"), [])
        self.assertEqual(scopes.enter(self.board, 1, a, "blk-fix"), [])
        self.put(f"{a}/r1/notes.md")
        opened = self.window()
        self.assertEqual(scopes.enter(self.board, 1, b, "blk-fix"), [])   # 後の子は前の子の窓を閉じない
        self.assertEqual(self.window(), opened)
        self.assertEqual(opened["scope"], "fan--*")
        self.put(f"{b}/r1/notes.md")
        self.put(f"{a}/r1/later.md")   # 前の子が、後の子が開いた後に自分の根に書く
        self.assertEqual(scopes.enter(self.board, 1, "", "darkfactory"), [])

    def test_fan_window_still_checks_declaration(self):
        self.assertEqual(scopes.enter(self.board, 1, "fan--aaaa1111", "blk-fix"), [])
        self.put("r1/rule-tree.json", "{}")
        got = scopes.enter(self.board, 1, "", "darkfactory")
        self.assertEqual(len(got), 1, got)
        for part in ("r1/rule-tree.json", "fan--*", "blk-fix"):
            self.assertIn(part, got[0])


if __name__ == "__main__":
    unittest.main()
