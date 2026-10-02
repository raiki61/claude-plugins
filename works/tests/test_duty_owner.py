"""直す義務の集合の持ち主を縛る検査（FAST。works の .py を AST で読むだけ。盤面・git・子のプロセスなし）。

直す義務（conflict.fix_duty の owed）は、担当のモジュール（gatemarks・conflict・recount・tddloop・report）が 1 か所で作る。その外の
.py が、同じ関数の中で「単位が開いている（is_open）」と「答え待ちの問いで外す（問いの台帳の kind が fork・status が ASKING か
escalate・裁定の decision が ask_human、か正本の部品 gatemarks.withheld・returned・asked_keys などの呼び）」を一緒に使えば、集合を作り直す
式として赤にする（食い違いは試験に出るまで見えなかった）。

- 走査の範囲は works の下の .py。tests・dev・fixtures と、写しの L0（.shared/core/graphloops・.shared/core/scripts）は見ない
  （写しはバイト一致で変えない。works は entry.CORE_OVERRIDES で差し替える。写しの中の同じ式は差し替えの方が読む）
- 行の鍵は「<模块>:<関数>」。行番号は使わない（直した後の行のずれで表を書き換えさせない）
- 今ある違反は KNOWN_REBUILDS に {鍵: 理由か直す依頼の番号} で載せる。期限は置かない。表は手で書き、走査は足さない。
  直って違反が消えたのに残っている行は赤（test_layers の KNOWN と同じ。表は減らす方向にだけ変える）
"""
import ast
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True

OWNERS = frozenset({"gatemarks", "conflict", "recount", "tddloop", "report"})
SKIP_DIRS = frozenset({"tests", "dev", "fixtures", "__pycache__"})
SKIP_PREFIXES = ((".shared", "core", "graphloops"), (".shared", "core", "scripts"))
OPEN_CALLS = frozenset({"is_open"})
CANON_CALLS = frozenset({"withheld", "withheld_by", "returned", "asked_keys", "asks", "pending", "fixable", "fix_duty", "held_by_rulings"})
RAW_MARKS = ("'fork'", "'escalate'", "ASKING")

# 今ある違反 {"<模块>:<関数>": 理由か直す依頼の番号}。走査が実際に挙げた物だけを、理由をつけて載せる
KNOWN_REBUILDS: dict = {}


def _call_name(node) -> str:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _rebuilds(fn) -> bool:
    opened = canon = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            name = _call_name(n)
            opened |= name in OPEN_CALLS
            canon |= name in CANON_CALLS
        elif isinstance(n, ast.Compare):
            text = ast.unparse(n)
            canon |= any(m in text for m in RAW_MARKS) or ("decision" in text and "ASK" in text)
    return opened and canon


def scan(root: pathlib.Path) -> set:
    out = set()
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).parts
        if SKIP_DIRS & set(rel) or p.stem in OWNERS or any(rel[:len(x)] == x for x in SKIP_PREFIXES):
            continue
        for fn in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and _rebuilds(fn):
                out.add(f"{p.stem}:{fn.name}")
    return out


def verdict(found: set, known: dict) -> list:
    return ([f"持ち主の外で直す義務の集合を作り直している: {k}（conflict.fix_duty を読め。正当な理由が在る時だけ KNOWN_REBUILDS に理由つきで載せる）"
             for k in sorted(found - set(known))]
            + [f"直ったのに KNOWN_REBUILDS に残っている行（消す）: {k}" for k in sorted(set(known) - found)])


class TestDutyOwner(unittest.TestCase):
    def test_no_rebuild_outside_the_owner_modules(self):
        self.assertEqual(verdict(scan(ROOT), KNOWN_REBUILDS), [])

    def test_known_rows_carry_a_reason(self):
        for k, why in KNOWN_REBUILDS.items():
            with self.subTest(k):
                self.assertTrue(str(why).strip(), f"理由か直す依頼の番号が無い行: {k}")


class CheckerCase(unittest.TestCase):
    """検査の検査: 使い捨ての置き場に植えて、赤になる形・ならない形を確かめる"""

    def plant(self, files: dict) -> set:
        """{置き場の中の相対パス: 本文} を置いて走査する"""
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            for rel, src in files.items():
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(src, encoding="utf-8")
            return scan(root)

    def test_raw_key_rebuild_is_caught(self):
        src = ("def owed(b, V):\n    held = {q['origin'] for q in b.qs if q.get('kind') == 'fork' and q.get('status') in V.ASKING}\n"
               "    return {u['key'] for u in b.units if V.is_open(u)} - held\n")
        self.assertEqual(self.plant({"stray.py": src}), {"stray:owed"})

    def test_canon_parts_rebuild_is_caught(self):
        src = "def owed(b, V, gm):\n    return {u['key'] for u in b.units if V.is_open(u)} - gm.withheld(b)\n"
        self.assertEqual(self.plant({"blk-x/lib/stray.py": src}), {"stray:owed"})

    def test_ask_human_filter_is_caught(self):
        src = ("def owed(b, V):\n    skip = {i['unit_key'] for i in b.items if i.get('decision') == ASK}\n"
               "    return [u for u in b.units if V.is_open(u) and u['key'] not in skip]\n")
        self.assertEqual(self.plant({"stray.py": src}), {"stray:owed"})

    def test_owner_module_and_skipped_places_are_not_scanned(self):
        src = "def owed(b, V, gm):\n    return {u for u in b.units if V.is_open(u)} - gm.withheld(b)\n"
        self.assertEqual(self.plant({"conflict.py": src, "tests/t.py": src, "dev/d.py": src, ".shared/core/graphloops/rules/r.py": src,
                                    ".shared/core/scripts/s.py": src}), set())

    def test_one_side_only_is_not_a_rebuild(self):
        opened = "def keys(b, V):\n    return [u['key'] for u in b.units if V.is_open(u)]\n"
        asked = "def waiting(b):\n    return [q for q in b.qs if q.get('kind') == 'fork']\n"
        self.assertEqual(self.plant({"a.py": opened, "b.py": asked}), set())

    def test_known_row_passes_and_stale_row_is_red(self):
        self.assertEqual(verdict({"stray:owed"}, {"stray:owed": "理由"}), [])
        self.assertEqual(len(verdict({"stray:owed"}, {})), 1)
        self.assertEqual(len(verdict(set(), {"stray:owed": "理由"})), 1)


if __name__ == "__main__":
    unittest.main()
