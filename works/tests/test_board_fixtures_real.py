"""graphloops の実物の盤面の写し（tests/boards/real/・tests/boards/foreign/）の検査。

real/ は写しの graph（a1202d0、走った時の graph_sha f9897bb07384）で走った実物の 2 個で、線 A の節を通っている（仕様 1 の 14）。
写しの graph に任意の欄 lens を足した時と、軽量の深さで省ける節に optional を足した時（2026-10-06）に、state.json の graph_sha だけを
今の写しの sha 2eb140b879e5 に書き換えた（README）。
foreign/ は graph の違う実物 35 個と、fbd40e3 の simulator の 4 個の state.json（開くと BoardMismatch になる試験に使う）。
開くときは最初に state.graph_sha を写しの graph の sha(graph_text(...)) と比べて断る（仕様 4.4）ので、foreign/ の state.json は
graph_sha の 1 つの鍵だけに削ってある（値は元と同じ）。削る前の元の state.json の sha256 は README に残す〔BL-R1〕。
README は置き場・元のパス・graph_sha・元の state.json の sha256 を 1 行ずつ持つ。見本はディスクの上で書き換えない（仕様 4.4）。
"""
import hashlib
import json
import pathlib
import re
import sys
import unittest

BOARDS = pathlib.Path(__file__).resolve().parent / "boards"
REAL = BOARDS / "real"
FOREIGN = BOARDS / "foreign"
README = BOARDS / "README"
GRAPH_SHA = "2eb140b879e5"
REAL_NAMES = ("wt-ci-skip", "wt-layer1")
TRACK_A = ("p2.fix_plan", "p2.plan_review", "p2.human_gate", "p3.fix", "p3.delta_owed2")
CORE = pathlib.Path(__file__).resolve().parents[1] / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import board  # noqa: E402,F401  （写しの graphloops を sys.path に足す）
from engine.schema import graph_text  # noqa: E402
from engine.util import sha  # noqa: E402

# 開くときに比べる相手と同じ求め方の、写しの graph の graph_sha
COPY_GRAPH_SHA = sha(graph_text(CORE / "graphloops" / "graphs" / "review-loop.json"))


def state_of(board):
    return json.loads((board / "state.json").read_text(encoding="utf-8"))


def boards_in(place):
    return sorted(p for p in place.iterdir() if p.is_dir()) if place.is_dir() else []


def readme_rows():
    """README の見本の行（`#` で始まる行と空行を除く）を {置き場: (元, graph_sha, 元の state.json の sha256)} に"""
    rows = {}
    for line in README.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        place, origin, gsha, src_sha256 = line.split("\t")
        rows[place] = (origin, gsha, src_sha256)
    return rows


class RealBoardsCase(unittest.TestCase):
    def test_real_boards_on_same_graph(self):
        self.assertEqual(COPY_GRAPH_SHA, GRAPH_SHA)
        self.assertEqual([p.name for p in boards_in(REAL)], list(REAL_NAMES))
        for board in boards_in(REAL):
            state = state_of(board)
            self.assertEqual(state["graph_sha"], GRAPH_SHA, board.name)
            self.assertNotIn("works", state, board.name)
            self.assertTrue((board / "record.json").is_file(), board.name)
            self.assertEqual(sorted(p.name for p in (board / "rounds").iterdir()),
                             ["round-1.json", "round-2.json"], board.name)

    def test_real_boards_have_track_a_nodes(self):
        self.assertEqual(len(boards_in(REAL)), 2)
        for board in boards_in(REAL):
            for nid in TRACK_A:
                self.assertTrue((board / "out" / "r1" / f"{nid}.json").is_file(), f"{board.name} {nid}")

    def test_foreign_boards_differ(self):
        foreign = boards_in(FOREIGN)
        self.assertEqual(len(foreign), 39)
        self.assertEqual(sum(p.name.startswith("sim__") for p in foreign), 4)
        for board in foreign:
            self.assertEqual(sorted(p.name for p in board.iterdir()), ["state.json"], board.name)
            state = state_of(board)
            self.assertEqual(sorted(state), ["graph_sha"], board.name)
            self.assertRegex(state["graph_sha"], r"^[0-9a-f]{12}$", board.name)
            self.assertNotEqual(state["graph_sha"], COPY_GRAPH_SHA, board.name)

    def test_readme_lists_all(self):
        rows = readme_rows()
        places = [f"real/{p.name}" for p in boards_in(REAL)] + [f"foreign/{p.name}" for p in boards_in(FOREIGN)]
        self.assertEqual(len(places), 41)
        self.assertEqual(sorted(rows), sorted(places))
        for place, (origin, gsha, src_sha256) in rows.items():
            self.assertTrue(origin, place)
            self.assertEqual(gsha, state_of(BOARDS / place)["graph_sha"], place)
            self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", src_sha256), place)
            if place.startswith("real/"):  # real/ は削っていないので、写しの sha256 が README の値と同じ（graph_sha を書き換えた後の値）
                data = (BOARDS / place / "state.json").read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), src_sha256, place)


if __name__ == "__main__":
    unittest.main()
