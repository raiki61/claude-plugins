"""束（[land] batch を 2 以上にした会社で、列の先頭の --land が後ろに待つ部署のブランチを重ねて 1 回のゲートで入れる。
docs/specs/2026-10-26-land-batch-design.md。landing.py・nodes/batch.py・nodes/land.py・nodes/landqueue.py・nodes/bump.py）。

決めるだけの関数（batch.select・adopt_step・upcoming・finished、bump.added_entries）は表で試す。重ねる・受け取る・ゲートの流れは、git の
振る舞い（rebase --onto・reset --keep・merge-tree）そのものを見るので、一時のフォルダの本物の git で試す（test_land の World と同じ形）。
乗る札は、列の置き場に後ろの時刻の札と名乗りを置いて作る（作ったばかりの札はロックが無くても生きていると見る。landqueue.GRACE）。
"""

import contextlib
import io
import os
import time
import unittest
from unittest import mock

from . import DISPATCH  # noqa: F401
import gitx
import landing
import landorder
import wake_hook
from config import Repo
from nodes import batch, bump, land, landqueue

from .test_land import QUEUE_RULES, LandCase, Ports, World, commit, git, no_rows, write

RULES = QUEUE_RULES + "batch = 3\n"


def fact(**kw):
    """batch.select に渡す札の事実（乗れる形が既定）。"""
    return {"ticket": kw.get("ticket", "t"), "who": ("d", "feat/d"), "alive": True, "path": "/p", "landed": False,
            "same": True, "clean": True, "suspect": False, **kw}


class Select(unittest.TestCase):
    def test_closes_at_the_first_ticket_that_cannot_ride_and_skips_landed_ones(self):
        cases = [
            ({"who": None}, "名乗らない札（--queue-run など）"),
            ({"alive": False}, "札が列を抜けた"),
            ({"path": None}, "部署の場所が見つからない"),
            ({"unadopted": True}, "前の束で入った中身をまだ受け取っていない"),
            ({"same": False}, "取り込みの決まりが束ね役と違う"),
            ({"clean": False}, "未コミットの変更が有る"),
            ({"suspect": True}, "疑いの印が有る（前の束が赤だった）"),
        ]
        for bad, why in cases:
            with self.subTest(why=why):
                riders, closed, got = batch.select([fact(ticket="1"), fact(ticket="2", **bad), fact(ticket="3")], 4)
                self.assertEqual(([f["ticket"] for f in riders], closed["ticket"], got), (["1"], "2", why))
        riders, closed, why = batch.select([fact(ticket="1", landed=True), fact(ticket="2"), fact(ticket="3"), fact(ticket="4")], 3)
        self.assertEqual(([f["ticket"] for f in riders], closed["ticket"], why), (["2", "3"], "4", "束の上限"))
        self.assertEqual(batch.select([fact(ticket="1")], 4)[1:], (None, None))

    def test_adopt_step(self):
        self.assertEqual(batch.adopt_step(True, "o", "o", True), "reset")
        self.assertEqual(batch.adopt_step(True, "n", "o", True), "onto")
        self.assertEqual(batch.adopt_step(False, "o", "o", True), "dirty")
        self.assertEqual(batch.adopt_step(False, "n", "o", False), "none")   # 部署が書き換えた: 汚れていても今の道へ

    def test_upcoming_estimates_the_next_batch_from_names_and_marks(self):
        a, b, c, d = (("a", "feat/a"), ("b", "feat/b"), ("c", "feat/c"), ("d", "feat/d"))
        self.assertEqual(batch.upcoming([("1", a), ("2", b), ("3", c), ("4", d)], 3, {}), ["1", "2", "3"])
        self.assertEqual(batch.upcoming([("1", None), ("2", b)], 3, {}), ["1"])   # 名乗らない札は 1 本で走る
        self.assertEqual(batch.upcoming([("1", a), ("2", b), ("3", c)], 3, {"feat/b": "x"}), ["1"])
        self.assertEqual(batch.upcoming([("1", a), ("2", b)], 3, {"feat/a": "x"}), ["1"])
        self.assertEqual(batch.upcoming([], 3, {}), [])


class AddedEntries(unittest.TestCase):
    def test_counts_lines_added_under_unreleased(self):
        before = "# c\n\n## [Unreleased]\n\n- 前から\n\n## [0.1.0]\n"
        self.assertFalse(bump.added_entries(before, before))
        self.assertFalse(bump.added_entries(before, before.replace("- 前から\n", "")))
        self.assertTrue(bump.added_entries(before, before.replace("- 前から\n", "- 前から\n- 前から\n")))   # 同じ字の 2 行目も足した行
        self.assertTrue(bump.added_entries(None, before))
        with self.assertRaises(bump.BumpError):
            bump.added_entries(before, "# c\n")


class ReadRules(unittest.TestCase):
    def rules(self, text):
        return land.read_rules("/c.toml", None, text)

    def test_batch_defaults_to_one_and_needs_a_queue(self):
        self.assertEqual(self.rules(QUEUE_RULES)["batch"], 1)
        self.assertEqual(self.rules(RULES)["batch"], 3)
        self.assertIn("land.batch を 2 以上にするなら land.queue（列の置き場）が要る",
                      " ".join(self.rules(RULES.replace('queue = "land-queue"\n', ""))["problems"]))
        for bad in ("0", "true", '"4"'):
            with self.subTest(bad=bad):
                self.assertTrue(self.rules(QUEUE_RULES + f"batch = {bad}\n")["problems"])


class Marks(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.queue = tempfile.mkdtemp(prefix="dispatch-batch-")

    def test_suspects_and_batches_round_trip(self):
        self.assertEqual(landqueue.suspects(self.queue), {})
        landqueue.set_suspects(self.queue, {"feat/b": "s"})
        self.assertEqual(landqueue.suspects(self.queue), {"feat/b": "s"})
        landqueue.set_suspects(self.queue, {})
        self.assertFalse(os.path.exists(os.path.join(self.queue, landqueue.SUSPECTS)))
        landqueue.write_batch(self.queue, "t1", {"candidate": "c", "members": []})
        self.assertEqual(landqueue.batches(self.queue), [("t1", {"candidate": "c", "members": []})])
        landqueue.drop_batch(self.queue, "t1")
        self.assertEqual(landqueue.batches(self.queue), [])

    def test_a_rider_that_leaves_before_its_turn_says_the_leader_may_have_landed_it(self):
        said = []
        blocker = os.path.join(self.queue, f"{time.time_ns() - 10**9:020d}-1.ticket")   # 前に居る生きた札（作ったばかり）
        open(blocker, "w").close()

        def sleep(_):
            mine = [n for n in landqueue.alive(self.queue) if n != os.path.basename(blocker)]
            landqueue.mark_riders(self.queue, mine, "a")
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            with landqueue.turn(self.queue, say=said.append, sleep=sleep, name=("b", "feat/b")):
                pass
        self.assertIn("束に乗っていたので、束ね役 a が入れたかもしれない", said[-1])
        self.assertEqual(sorted(n for n in os.listdir(self.queue) if n != "lock"), [os.path.basename(blocker)])


class Depts(Ports):
    """部署 a・b・c（feat/a・feat/b・feat/c）を持つ本物の git の口。"""

    def __init__(self, world, places):
        super().__init__(world)
        self.by_path = {os.path.realpath(p): {"name": n, "session": f"s-{n}", "role": "worker"} for n, p in places.items()}

    def attrs(self, path):
        return dict(self.by_path.get(os.path.realpath(path), {}))


class Bundle(LandCase):
    """3 つの部署のブランチを 1 回のゲートで入れ、乗った部署が自分の --land で受け取る。"""

    def setUp(self):
        super().setUp()
        self.w = World(self.tmp, {".claude/company.toml": RULES, "README.md": "r\n"})
        self.places = {"a": self.w.dept}
        for n in ("b", "c"):
            self.places[n] = os.path.join(self.tmp, "wt", n)
            git("-C", self.w.source, "worktree", "add", "-q", "-b", f"feat/{n}", self.places[n], "origin/main")
        self.ports = Depts(self.w, self.places)
        self.queue = os.path.join(self.w.source, ".git", "land-queue")
        self.gates = []

    def work(self, n, rel=None, text=None):
        write(os.path.join(self.places[n], rel or f"{n}.txt"), text or f"{n}\n")
        return commit(self.places[n], f"部署 {n} の作業")

    def wait(self, *names):
        """乗る札: 後ろの時刻の札と名乗りを列の置き場に置く（束ね役の札より後ろに並ぶ）。"""
        os.makedirs(self.queue, exist_ok=True)
        out = {}
        for i, n in enumerate(names, 1):
            t = f"{time.time_ns() + i * 10**12:020d}-9{i}.ticket"
            open(os.path.join(self.queue, t), "w").close()
            write(os.path.join(self.queue, t + landqueue.WHO), f"{n}\nfeat/{n}\n")
            out[n] = t
        return out

    def leave(self, ticket):
        for suffix in ("", landqueue.WHO, landqueue.RIDER):
            with contextlib.suppress(OSError):
                os.remove(os.path.join(self.queue, ticket + suffix))

    def checker(self, red=False):
        def run(command, cwd, env=None):
            self.gates.append((cwd, dict(env or {})))
            return (1, "落ちた") if red and (env or {}).get(landing.WORKS_LAND_KEY, "").endswith(" batch") else (0, "")
        return run

    def g_base(self, n):
        return gitx.worktree_attrs(self.places[n]).get("base")

    def on_main(self, rel):
        return subprocess_ok(["git", "--git-dir", self.w.remote, "cat-file", "-e", f"refs/heads/main:{rel}"])

    def test_three_branches_go_in_with_one_gate_and_riders_adopt_on_their_own_land(self):
        heads = {n: self.work(n) for n in ("a", "b", "c")}
        tickets = self.wait("b", "c")
        code, out = self.land(self.w, self.ports, checker=self.checker(), name="a")
        self.assertEqual(code, 0, out)
        self.assertIn("束: a と b・c の 3 本を、1 回のゲートで入れる", out)
        self.assertEqual(len(self.gates), 1)
        cwd, env = self.gates[0]
        self.assertNotEqual(os.path.realpath(cwd), os.path.realpath(self.w.dept))   # 一時の場所で回す
        ((_, record),) = landqueue.batches(self.queue)
        stacked = {m["name"]: m["stacked"] for m in record["members"]}
        # 初見の読み手のゲートは、重ねた先頭（束の全員の変更）を読み、控えの鍵に束の印を付け、帰属は束ね役のブランチに寄せる
        self.assertEqual((env[landing.WORKS_LAND_KEY], env[landing.WORKS_LAND_BRANCH], env[landing.WORKS_LAND_TIP]),
                         ("feat/a batch", "feat/a", stacked["c"]))
        self.assertTrue(all(self.on_main(f"{n}.txt") for n in "abc"))
        self.assertEqual(gitx.rev(self.w.source, "refs/heads/feat/b"), heads["b"])   # 束ね役は乗った部署の場所を書かない
        self.assertEqual([m["name"] for m in record["members"]], ["a", "b", "c"])
        self.assertEqual(stacked["a"], heads["a"])
        self.assertFalse([n for n in os.listdir(self.queue) if n.endswith(landqueue.RIDER)])
        # 乗った部署 b が自分の順番で --land を打つ: 写しへ替えて終わる（ゲートも合図も回さない）
        self.leave(tickets["b"])
        code, out = self.land(self.w, self.ports, checker=self.checker(), name="b")
        self.assertEqual(code, 0, out)
        self.assertIn("束（束ね役 a）でメインブランチに入った", out)
        self.assertEqual(len(self.gates), 1)
        self.assertEqual(gitx.rev(self.places["b"], "HEAD"), stacked["b"])
        self.assertEqual(len(landqueue.batches(self.queue)), 1)   # c がまだ受け取っていない
        # c は待ち受けの追いつき（follow_main）で受け取る
        self.leave(tickets["c"])
        said = wake_hook.adopt_batch({"root": self.w.source, "cwd": self.places["c"]}, {"role": "worker"}, "main")
        self.assertIn("束（束ね役 a）でメインブランチに入った中身を受け取った", said)
        self.assertEqual(gitx.rev(self.places["c"], "HEAD"), stacked["c"])

    def test_a_conflicting_rider_closes_the_batch_and_later_tickets_do_not_overtake(self):
        self.work("a", "x.txt", "a\n")
        self.work("b", "x.txt", "b\n")
        self.work("c")
        self.wait("b", "c")
        code, out = self.land(self.w, self.ports, checker=self.checker(), name="a")
        self.assertEqual(code, 0, out)
        self.assertIn("束: 札 b で閉じた（ぶつかる（x.txt））", out)
        self.assertIn("乗せられる札が無いので、1 本で通す", out)
        self.assertEqual(self.gates[0][1][landing.WORKS_LAND_KEY], "feat/a")
        self.assertFalse(self.on_main("c.txt"))
        self.assertEqual(landqueue.batches(self.queue), [])

    def test_a_red_batch_marks_riders_and_the_leader_goes_alone(self):
        heads = {n: self.work(n) for n in ("a", "b", "c")}
        self.wait("b", "c")
        code, out = self.land(self.w, self.ports, checker=self.checker(red=True), name="a")
        self.assertEqual(code, 0, out)
        self.assertIn("束が赤だったので束をほどき", out)
        self.assertEqual([e[landing.WORKS_LAND_KEY] for _, e in self.gates], ["feat/a batch", "feat/a"])
        self.assertTrue(self.on_main("a.txt"))
        self.assertFalse(self.on_main("b.txt"))
        self.assertEqual(landqueue.suspects(self.queue), {"feat/b": heads["b"], "feat/c": heads["c"]})

    def test_a_rider_that_committed_after_the_batch_moves_its_commit_onto_the_copy(self):
        self.work("a")
        self.work("b")
        tickets = self.wait("b")
        self.assertEqual(self.land(self.w, self.ports, checker=self.checker(), name="a")[0], 0)
        ((_, record),) = landqueue.batches(self.queue)
        stacked = record["members"][1]["stacked"]
        self.work("b", "d.txt")
        self.leave(tickets["b"])
        code, out = self.land(self.w, self.ports, checker=self.checker(), name="b")
        self.assertEqual(code, 0, out)
        self.assertIn("その後の commit を移した", out)
        self.assertTrue(self.on_main("d.txt"))
        self.assertEqual(git("-C", self.places["b"], "rev-parse", "HEAD~1"), stacked)
        self.assertEqual(landqueue.batches(self.queue), [])

    def test_the_leader_landing_again_while_the_record_remains_takes_the_usual_path(self):
        # 束ね役の行（写しが元と同じ）は受け取りに当たらない。当たると company.base を前の束の候補へ戻してしまう
        self.work("a")
        self.work("b")
        self.wait("b")
        self.assertEqual(self.land(self.w, self.ports, checker=self.checker(), name="a")[0], 0)
        self.assertEqual(len(landqueue.batches(self.queue)), 1)   # b がまだ受け取っていない
        self.work("a", "e.txt")
        code, out = self.land(self.w, self.ports, checker=self.checker(), name="a")
        self.assertEqual(code, 0, out)
        self.assertNotIn("束（束ね役", out)
        self.assertTrue(self.on_main("e.txt"))
        self.assertEqual(self.g_base("a"), git("--git-dir", self.w.remote, "rev-parse", "refs/heads/main"))

    def test_land_order_and_dry_run_show_the_next_batch(self):
        for n in ("a", "b", "c"):
            self.work(n)
        os.makedirs(self.queue, exist_ok=True)
        head = f"{time.time_ns():020d}-1.ticket"
        open(os.path.join(self.queue, head), "w").close()
        write(os.path.join(self.queue, head + landqueue.WHO), "z\nfeat/z\n")
        self.wait("b", "c")
        lines = landorder.rows(self.queue, self.w.source, "main", gitx, limit=3)
        self.assertNotIn("次の束", lines[0])
        self.assertIn("次の束の束ね役（見込み）", lines[1])
        self.assertIn("次の束に乗る見込み", lines[2])
        self.assertNotIn("次の束", "".join(landorder.rows(self.queue, self.w.source, "main", gitx)))
        code, out = self.land(self.w, self.ports, name="a", dry_run=True)
        self.assertEqual(code, 0, out)
        self.assertIn("束: 上限 3 本", out)
        self.assertIn("次の束の見込み: b・c", out)


class GitBoundary(LandCase):
    def test_rebase_onto_reset_to_and_merges_clean(self):
        w = World(self.tmp)
        base = w.origin("main")
        first = w.work("a.txt", "1\n")
        second = w.work("b.txt", "2\n")
        git("-C", w.dept, "checkout", "-q", "--detach", base)
        self.assertEqual(gitx.rebase_onto(w.dept, base, first, second), (True, []))   # first より後（second）だけを base の上へ
        self.assertEqual(git("-C", w.dept, "show", "--name-only", "--format=", "HEAD"), "b.txt")
        gitx.detach(w.dept, first)
        self.assertEqual(gitx.rev(w.dept, "HEAD"), first)
        self.assertEqual(gitx.merge_base(w.dept, first, base), base)
        git("-C", w.dept, "checkout", "-q", "feat/a")
        gitx.reset_to(w.dept, first)
        self.assertEqual(gitx.rev(w.dept, "HEAD"), first)
        self.assertTrue(gitx.merges_clean(w.dept, first, second))
        git("-C", w.dept, "checkout", "-q", "-b", "other", base)
        clash = w.work("a.txt", "x\n")
        self.assertIs(gitx.merges_clean(w.dept, first, clash), False)


def subprocess_ok(cmd):
    import subprocess
    return subprocess.run(cmd, capture_output=True).returncode == 0


if __name__ == "__main__":
    unittest.main()
