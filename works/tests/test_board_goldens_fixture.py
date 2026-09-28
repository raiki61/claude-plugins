"""盤面の手本（tests/boards/golden-a1202d0/）の検査（仕様 9.2）。

手本は写しの graphloops の commit（.shared/core/COPIED_FROM の 1 行目。MANIFEST の graphloops_rev）の台本 simulate_review.py の場面を回し、engine の中で手の前後に記憶の中の
state と record・ディスクの目録・対象リポジトリの目録を撮った物（作り手は dev/board-goldens/make.py）。
ここでは手本そのものの形を見る: 差分を順に当てると撮った最後の値に戻るか・中身の置き場が揃っているか・
絶対パスが残っていないか・線 A と B が要る手の種類（周の頭と締め・周の途中の問い・patch・finalize・engine が
走らせる節の分け方・拒んだ手）が入っているか・大きさが上限の中か。再生（手本を DiskBoard に当てる）は別の試験。
"""
import collections
import copy
import gzip
import hashlib
import json
import os
import pathlib
import sys
import unittest
import zlib

GOLD = pathlib.Path(__file__).resolve().parent / "boards" / "golden-a1202d0"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / ".shared" / "core"))
import copyledger  # noqa: E402
LIMIT = 30 * 1024 * 1024
sys.dont_write_bytecode = True

# init で拒まれる Run（台本の Run の名前。目録の dir は gl-review-<名前>-*/state）
INIT_REJECTED = ("policy-missing", "stop0", "gbad-gates", "gbad-flow", "gbad-key")
SKIPPED = ("test_delta_conditions", "test_fix_counts_by_engine", "test_lane_end_to_end")


def manifest():
    return json.loads((GOLD / "MANIFEST.json").read_text(encoding="utf-8"))


def blob(sha):
    return gzip.decompress((GOLD / "blobs" / f"{sha}.gz").read_bytes())


def steps(scenario):
    return json.loads(gzip.decompress((GOLD / "steps" / f"{scenario}.json.gz").read_bytes()))


def runs_of(scenario):
    """{run の番号: [手（seq の順）]}"""
    got = collections.defaultdict(list)
    for s in steps(scenario):
        got[str(s["run"])].append(s)
    for rows in got.values():
        rows.sort(key=lambda s: s["seq"])
    return dict(got)


def every_run():
    m = manifest()
    for scen, info in m["scenarios"].items():
        rows = runs_of(scen)
        for run, meta in info["runs"].items():
            yield scen, run, meta, rows.get(run, [])


def apply_ops(obj, ops):
    """記憶の差分 [{path, op: set|del, value?}] を当てる（元は変えない）"""
    obj = copy.deepcopy(obj)
    for o in ops:
        *head, last = o["path"]
        cur = obj
        for k in head:
            cur = cur[k]
        if o["op"] == "set":
            if isinstance(cur, list) and last == len(cur):
                cur.append(copy.deepcopy(o["value"]))
            else:
                cur[last] = copy.deepcopy(o["value"])
        elif o["op"] == "del":
            del cur[last]
        else:
            raise AssertionError(f"知らない op: {o}")
    return obj


def apply_listing(base, diff):
    got = dict(base)
    got.update((diff or {}).get("add") or {})
    for p in (diff or {}).get("drop") or []:
        del got[p]
    return got


def memory_walk(rows):
    """記憶の差分を順に当て、[(手, before, after)] を返す（記憶を持たない手は飛ばす）"""
    ref, out = None, []
    for s in rows:
        m = s.get("memory")
        if not m:
            continue
        if "base" in m:
            if s["kind"] == "init":
                before, after = None, m["base"]
            else:
                before = m["base"]
                after = apply_ops(before, m["after"]) if "after" in m else None
        else:
            before = apply_ops(ref, m["before"])
            after = apply_ops(before, m["after"]) if "after" in m else None
        out.append((s, before, after))
        ref = after if after is not None else before
    return out


class GoldenFixtureCase(unittest.TestCase):
    def test_manifest_names_source(self):
        m = manifest()
        self.assertEqual(m["graphloops_rev"], copyledger.core_commit(), "手本と写しの版が割れている（写し直したら手本も撮り直す）")
        self.assertEqual(m["graph_sha"], "f9897bb07384")
        self.assertTrue(m["git_env"])
        for k in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE", "GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
            self.assertIn(k, m["git_env"])

    def test_every_initialized_run_has_steps(self):
        n = 0
        for scen, run, meta, rows in every_run():
            with self.subTest(scenario=scen, run=run, dir=meta["dir"]):
                self.assertEqual(meta["steps"], len(rows))
                self.assertEqual(rows[0]["kind"], "init")
                if meta["init_rejected"]:
                    continue
                n += 1
                if meta.get("init_only"):   # 台本が init の返りだけを見る Run（作り手の表に理由つきで在る物だけ）
                    self.assertEqual(len(rows), 1, meta["init_only"])
                    continue
                self.assertGreater(len(rows), 1)
        self.assertGreater(n, 20)

    def test_init_rejected_runs_recorded(self):
        seen = set()
        for scen, run, meta, rows in every_run():
            name = run_name(meta["dir"])
            if name not in INIT_REJECTED:
                continue
            seen.add(name)
            with self.subTest(run=name):
                self.assertTrue(meta["init_rejected"])
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["kind"], "init")
                self.assertTrue(rows[0]["raised"]["text"])
                self.assertNotIn("memory", rows[0])
        self.assertEqual(seen, set(INIT_REJECTED))
        rejected = {run_name(meta["dir"]) for _, _, meta, _ in every_run() if meta["init_rejected"]}
        self.assertEqual(rejected, set(INIT_REJECTED))

    def test_skipped_scenarios_reasoned(self):
        sk = manifest()["skipped_scenarios"]
        for name in SKIPPED:
            self.assertIn(name, sk)
            self.assertGreater(len(sk[name].strip()), 10, name)
        self.assertFalse(set(sk) & set(manifest()["scenarios"]))

    def test_memory_diffs_apply(self):
        for scen, run, meta, rows in every_run():
            if meta["init_rejected"]:
                continue
            with self.subTest(scenario=scen, run=run):
                walked = memory_walk(rows)
                builtins = [(b, a) for s, b, a in walked if s["kind"] == "builtin" and a is not None]
                if builtins:
                    self.assertTrue(any(b != a for b, a in builtins))
                last = walked[-1][2] if walked[-1][2] is not None else walked[-1][1]
                self.assertEqual(last, json.loads(blob(meta["last"]["memory"])))
                self.assertEqual(set(last), {"state", "record"})

    def test_na_steps_are_light(self):
        n = 0
        for scen, run, meta, rows in every_run():
            for s in rows:
                if s["kind"] != "na":
                    continue
                n += 1
                self.assertEqual(set(s["na"]), {"node", "why"})
                self.assertEqual(s["na"]["node"], s["node"])
                self.assertTrue(s["na"]["why"])
                for k in ("memory", "disk", "repo_before"):
                    self.assertNotIn(k, s)
        self.assertGreater(n, 0)

    def test_kinds_cover_round_turn(self):
        nodes, opens = set(), 0
        for scen, run, meta, rows in every_run():
            for s in rows:
                if s["kind"] == "builtin":
                    nodes.add(s["node"])
                opens += s["kind"] == "open_round"
        self.assertLessEqual({"p4.record", "converge"}, nodes)
        self.assertGreater(opens, 0)

    def test_kinds_cover_in_round_ask(self):
        hits = 0
        for scen, run, meta, rows in every_run():
            if meta["init_rejected"]:
                continue
            asked = None
            for s, before, after in memory_walk(rows):
                if (s["kind"] == "builtin" and s["node"] == "p2.human_gate" and after is not None
                        and (after["state"].get("pending_human") or {}).get("in_round")):
                    asked = s["seq"]
                if asked is not None and s["kind"] == "answer" and s["seq"] > asked:
                    hits += 1
                    break
        self.assertGreater(hits, 0)

    def test_kinds_cover_patch_finalize(self):
        self.assertIn("patch", {s["kind"] for s in steps("test_rejudge_path")})
        self.assertIn("finalize", {s["kind"] for s in steps("test_stop_after_round")})

    def test_engine_run_split(self):
        n = 0
        for scen, run, meta, rows in every_run():
            for i, s in enumerate(rows):
                if s["kind"] != "engine_run":
                    continue
                er = s["engine_run"]
                self.assertIn("plan", er)
                self.assertIn("runs", er)
                if not (s.get("result") or {}).get("ok"):
                    continue
                n += 1
                self.assertTrue(er["runs"])
                for r in er["runs"]:
                    self.assertIn("out_text", r)
                nxt = rows[i + 1]
                self.assertEqual((nxt["kind"], nxt["node"]), ("accept", s["node"]), (scen, run, s["seq"]))
        self.assertGreater(n, 0)

    def test_rejected_steps_present(self):
        bad = [s for s in steps("test_rejections") if s["kind"] == "accept" and s.get("raised")]
        self.assertGreater(len(bad), 0)
        for s in bad:
            self.assertTrue(s["raised"]["type"])
            self.assertNotIn("after", s.get("memory") or {})

    def test_multi_run_numbered(self):
        runs = manifest()["scenarios"]["test_request_entry"]["runs"]
        self.assertGreaterEqual(len(runs), 2)
        dirs = [r["dir"] for r in runs.values()]
        self.assertEqual(len(dirs), len(set(dirs)))
        self.assertEqual(sorted(runs, key=int), [str(i) for i in range(1, len(runs) + 1)])

    def test_blobs_referenced_exist(self):
        refs = set()
        for scen, run, meta, rows in every_run():
            refs.update((meta.get("last") or {}).values())
            refs.update((meta.get("final") or {}).values())
            for s in rows:
                d = s.get("disk") or {}
                refs.update((d.get("base") or {}).values())
                for k in ("before", "after"):
                    refs.update(((d.get(k) or {}).get("add") or {}).values())
                r = s.get("repo_before") or {}
                refs.update((r.get("base") or {}).values())
                refs.update((r.get("add") or {}).values())
        self.assertGreater(len(refs), 100)
        on_disk = {p.name.removesuffix(".gz") for p in (GOLD / "blobs").glob("*.gz")}
        self.assertEqual(refs - on_disk, set())
        for sha in sorted(on_disk):
            with self.subTest(sha=sha):
                self.assertEqual(hashlib.sha256(blob(sha)).hexdigest(), sha)

    def test_no_absolute_paths(self):
        # 撮った機械の綴りを一般に探す（試験を回す機械の Python は撮った Python と別物なので名指ししない）。
        # git の object は zlib で縮めてあるので、gzip を解いた後に zlib も解いて中まで見る
        raw = ["/Users/", "/var/folders", "/private/var/folders", "/private/tmp", str(pathlib.Path.home())]
        texts, inflated = [], 0
        for p in sorted((GOLD / "blobs").glob("*.gz")):
            data = gzip.decompress(p.read_bytes())
            texts.append((p.name, data))
            try:
                texts.append((p.name + "（zlib を解いた物）", zlib.decompress(data)))
                inflated += 1
            except zlib.error:
                pass
        texts += [(p.name, gzip.decompress(p.read_bytes())) for p in sorted((GOLD / "steps").glob("*.json.gz"))]
        texts.append(("MANIFEST.json", (GOLD / "MANIFEST.json").read_bytes()))
        self.assertGreater(inflated, 50)   # git の object を実際に解いている
        for name, data in texts:
            for r in raw:
                self.assertNotIn(r.encode("utf-8"), data, name)

    def test_only_stop_nodecl_on_other_graph(self):
        """graph の違う Run はちょうど 1 本（test_stop_midround の stop-nodecl。台本が graph の stop の宣言を消して回す）"""
        head = manifest()["graph_sha"]
        other = [(scen, run_name(meta["dir"]), meta.get("graph_sha")) for scen, run, meta, rows in every_run()
                 if not meta["init_rejected"] and meta.get("graph_sha") != head]
        self.assertEqual([(s, n) for s, n, _ in other], [("test_stop_midround", "stop-nodecl")])
        self.assertTrue(other[0][2])

    def test_final_board_after_last_launch(self):
        """各 Run の最後の起動の後のディスクの盤面（final）が在り、最後の手（last）より版が進んでいるか同じ"""
        for scen, run, meta, rows in every_run():
            if meta["init_rejected"]:
                self.assertNotIn("final", meta)
                continue
            with self.subTest(scenario=scen, run=run):
                final = {k: json.loads(blob(v)) for k, v in meta["final"].items()}
                last = json.loads(blob(meta["last"]["memory"]))
                self.assertEqual(set(final["memory"]), {"state", "record"})
                self.assertGreaterEqual(final["memory"]["state"].get("rev", 0), last["state"].get("rev", 0))
                self.assertEqual(final["memory"]["state"]["run_id"], last["state"]["run_id"])
                self.assertTrue(any(p.startswith(".git/objects/") for p in final["repo"]))

    def test_nested_steps_point_to_parent(self):
        """入れ子の手は親の手の seq を parent に持つ（engine_run の中の accept・converge と answer の中の open_round）"""
        kinds = collections.Counter()
        for scen, run, meta, rows in every_run():
            by_seq = {s["seq"]: s for s in rows}
            for i, s in enumerate(rows):
                if "parent" in s:
                    par = by_seq[s["parent"]]
                    self.assertLess(par["seq"], s["seq"])
                    kinds[(par["kind"], s["kind"])] += 1
                if s["kind"] == "engine_run" and (s.get("result") or {}).get("ok"):
                    self.assertEqual(rows[i + 1].get("parent"), s["seq"])
                if s["kind"] == "open_round":
                    self.assertIn(by_seq[s["parent"]]["kind"], ("builtin", "answer"))
        self.assertGreater(kinds[("engine_run", "accept")], 0)
        self.assertGreater(kinds[("builtin", "open_round")], 0)
        self.assertLessEqual(set(kinds), {("engine_run", "accept"), ("builtin", "open_round"), ("answer", "open_round")})

    def test_uncovered_listed(self):
        u = manifest()["uncovered"]
        self.assertIsInstance(u, list)
        print(f"\n手本が通らない節（uncovered）: {', '.join(u) if u else '無し'}", file=sys.stderr)

    def test_manifest_diffs_apply(self):
        for scen, run, meta, rows in every_run():
            if meta["init_rejected"]:
                continue
            with self.subTest(scenario=scen, run=run):
                disk = repo = None
                for s in rows:
                    d = s.get("disk")
                    if d is not None:
                        if "base" in d:
                            disk = apply_listing(d["base"], d.get("after"))
                        else:
                            disk = apply_listing(apply_listing(disk, d.get("before")), d.get("after"))
                    r = s.get("repo_before")
                    if r is not None:
                        repo = r["base"] if "base" in r else apply_listing(repo, r)
                self.assertEqual(disk, json.loads(blob(meta["last"]["disk"])))
                self.assertEqual(repo, json.loads(blob(meta["last"]["repo"])))
                self.assertTrue(any(p.startswith("out/") for p in disk) or meta.get("init_only"))
                self.assertTrue(any(p.startswith(".git/objects/") for p in repo))

    def test_die_text_from_last_die(self):
        n = 0
        for scen, run, meta, rows in every_run():
            r = rows[0].get("raised") if meta["init_rejected"] else None
            if not r or r["type"] != "SystemExit":
                continue
            n += 1
            self.assertNotIn(r["text"].strip(), ("", "1", "2"))
            if run_name(meta["dir"]) == "stop0":
                self.assertIn("1 以上", r["text"])
        self.assertGreater(n, 0)

    def test_size_budget(self):
        m = manifest()
        real = sum(p.stat().st_size for p in (GOLD / "blobs").glob("*.gz"))
        real += sum(p.stat().st_size for p in (GOLD / "steps").glob("*.json.gz"))
        self.assertEqual(m["total_bytes"], real)
        parts = {s: sum(r["bytes"] for r in info["runs"].values()) for s, info in m["scenarios"].items()}
        self.assertLessEqual(real, LIMIT, "場面ごとの内訳: " + ", ".join(f"{k} {v}" for k, v in sorted(parts.items())))


def run_name(d):
    """目録の dir（gl-review-<名前>-*/state）から台本の Run の名前"""
    head = d.split("/")[0]
    return head.removeprefix("gl-review-").removesuffix("-*")


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    unittest.main()
