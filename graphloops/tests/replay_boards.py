"""盤面の再生の突き合わせ——盤面が周ごとに記録した条件の評価（周の rd: 条件外 na の『cond <名前>: 理由』と、走った節）を、
今の rules と graph の条件の関数で評価し直して比べる（Temporal の replay test と同じ形: 新しいコードが記録済みの履歴と両立するか）。

正解は旧いコードの出力ではなく、盤面に記録された評価そのもの。周ごとに残っていない値（周の途中の記録・盤面の loop）は作らない:
  - 節の出力と周の rd は、その節の祖先（deps の推移閉包）が出した物だけを今の周の値として見せる（評価した時点に在った物）
  - 周の記録は rounds/round-<N>.json の欄を、書き手の節が祖先に在る物だけ（素材・単位・問い・R の判定・規模の数値）
  - 記録の process は最後の値。周を刻んだ行（fixes）はその周より前の行だけ
  - 盤面の loop は run の状態のうち、周をまたいで一方向にだけ変わる旗（request_fixed_at・escalated）を、立った周より後にだけ見せる
旧い版の rules が書いた出力（ブロックの出口の欄を持たない出力）は、この道具の中で今の形に読み替えてから評価する（upcast）——
周の頭の節の前の周の P3 が触ったファイルは、今の rules と同じ定義（前の周の頭の版と、この周の頭の版の木の差）を git で測る。

入口は 2 つ: replay(盤面, graph) は 1 つの盤面の周ごとの食い違いを返し（台本が CI で呼ぶ）、sweep は置き場の盤面を全部舐める
（手で打つ入口。見つかった盤面が 0 件なら exit 1——飛ばして緑にしない）:

  python3 graphloops/tests/replay_boards.py sweep --graph graphloops/graphs/review-loop.json [--boards <盤面の glob>]
"""
import argparse
import copy
import glob
import json
import pathlib
import subprocess
import sys

PLUGIN = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN))

from engine import board as board_mod  # noqa: E402
from engine.schema import load_graph  # noqa: E402
from engine.rules import load_rules  # noqa: E402
from engine.util import read_json, safe_name  # noqa: E402

WRITER_OF_RECORD = {"units": ("p2.diagnose",), "questions": ("p2.diagnose",), "scalars": ("p4.scalars",),
                    "reviews": ("r1.minimality", "r2.design", "r2.compare", "r3.coherence", "r4.hidden_scope")}
ROUND_STAMPED = ("fixes",)   # 記録の process の、周を刻んで積む行（その周より前の行だけを見せる）


def ancestors(nodes, nid):
    seen, todo = set(), list(nodes[nid].get("deps", []))
    while todo:
        d = todo.pop()
        if d in nodes and d not in seen:
            seen.add(d)
            todo += nodes[d].get("deps", [])
    return seen


def _git(repo, *args):
    q = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return q.stdout if q.returncode == 0 else None


def upcast(nid, out, head_revs, rnd, repo):
    """旧い版の rules が書いた出力を今の形に読み替える（読み替えた欄の名前を返す）。今の形の出力はそのまま"""
    got = []
    if not isinstance(out, dict):
        return out, got
    out = copy.deepcopy(out)
    if nid == "p1.worktree_before" and "snapshot" not in out and isinstance(out.get("diff_file"), str):
        tb = out.get("tree_before") or {}
        out["snapshot"] = {"rev": tb.get("rev") or tb.get("tree") or "", "diff_file": out["diff_file"],
                           "changed_files": out.get("changed_files") or [], "changed_files_file": "", "stat": out.get("stat") or ""}
        got.append("snapshot")
    if nid == "p1.worktree_before" and "changed_since_prev_round" not in out:
        prev, cur = head_revs.get(str(rnd - 1)), head_revs.get(str(rnd))
        if rnd == 1:
            out["changed_since_prev_round"] = []
            got.append("changed_since_prev_round")
        elif prev and cur and repo:
            names = _git(repo, "diff", "--name-only", "-z", prev, cur)
            if names is not None:
                out["changed_since_prev_round"] = sorted(x for x in names.split("\0") if x)
                got.append("changed_since_prev_round")
    if nid in ("p3.fix_delta", "p3.fix_delta2") and "delta" not in out and isinstance(out.get("changed_files"), list):
        out["delta"] = {"file": out.get("fix_delta_file") or "", "files": out["changed_files"], "rev": ""}
        got.append("delta")
    return out, got


class ReplayBoard(board_mod.Board):
    """盤面を読むだけの Board——ディスクには何も書かない。周 N・節 nid の評価の時点の見え方を組む"""

    def __init__(self, d, graph_path, repo=None):   # super を呼ばない（盤面の state.graph でなく渡した graph で読む）
        self.dir = pathlib.Path(d)
        self.full = read_json(self.dir / "state.json")
        self.final_record = read_json(self.dir / "record.json")
        self.graph, why = load_graph(str(graph_path))
        if why:
            raise SystemExit(why)
        self.nodes = self.graph["nodes"]
        self.rules = load_rules(str(graph_path), self.graph)
        self.repo = repo
        self.seen_rev, self.halted_at_read, self.upcasts = 0, False, set()
        self._head_revs = {}

    def save(self):
        raise RuntimeError("再生の盤面は保存しない")

    def trace(self, op, **kw):
        pass

    def _round_output_files(self, nid, n):
        rd = next((r for r in self.full["rounds"] if r.get("round") == n), None) or {}
        done = [i for i in (rd.get("instances") or {}).values() if i.get("node") == nid and i.get("status") == "done" and i.get("output_file")]
        if done:
            return done[-1]["output_file"]
        p = self.dir / "out" / f"r{n}" / (safe_name(nid) + ".json")
        return str(p.relative_to(self.dir)) if p.is_file() else None

    def read_out(self, path, *, board_relative=False):
        out = super().read_out(path, board_relative=board_relative)
        nid, rnd = self._file_owner.get(str(path), (None, None))
        if nid:
            out, got = upcast(nid, out, self._head_revs, rnd, self.repo)
            for g in got:
                self.upcasts.add(f"{nid}.{g}")
        return out

    def at(self, n, nid):
        """周 n の、節 nid を評価する時点の見え方に盤面を組み直す"""
        anc = ancestors(self.nodes, nid)
        rounds = copy.deepcopy([r for r in self.full["rounds"] if r.get("round", 0) <= n])
        cur = rounds[-1]
        for box in ("done", "na", "skipped"):
            cur[box] = {k: v for k, v in (cur.get(box) or {}).items() if k in anc}
        cur["instances"] = {k: v for k, v in (cur.get("instances") or {}).items() if v.get("node") in anc}
        outputs, self._file_owner = {}, {}
        for x in self.nodes:
            for k in range(n, 0, -1):
                if k == n and x not in anc:
                    continue
                f = self._round_output_files(x, k)
                if f:
                    outputs[x] = {"file": f, "round": k}
                    self._file_owner[f] = (x, k)
                    break
        self.state = {**self.full, "round": n, "rounds": rounds, "outputs": outputs, "unevaluable": []}
        loop = {}
        fin = self.full.get("loop") or {}
        if isinstance(fin.get("request_fixed_at"), int) and fin["request_fixed_at"] < n:
            loop["request_fixed_at"] = fin["request_fixed_at"]
        esc = fin.get("escalated")
        if isinstance(esc, dict) and isinstance(esc.get("round"), int) and esc["round"] <= n:
            loop["escalated"] = esc
        self.state["loop"] = loop
        rec_file = self.dir / "rounds" / f"round-{n}.json"
        rnd_rec = read_json(rec_file) if rec_file.is_file() else {}
        proc = copy.deepcopy(self.final_record.get("process") or {})
        for k in ROUND_STAMPED:
            if isinstance(proc.get(k), list):
                proc[k] = [r for r in proc[k] if not (isinstance(r, dict) and isinstance(r.get("round"), int) and r["round"] >= n)]
        materials = {m: v for m, v in (rnd_rec.get("materials") or {}).items()
                     if any(m in (self.nodes[a].get("materials") or []) for a in anc)}
        self.record = {"base": self.final_record.get("base"), "round": n, "materials": materials, "process": proc,
                       **{f: (rnd_rec.get(f) or ({} if f in ("scalars", "reviews") else []))
                          if any(w in anc for w in ws) else ({} if f in ("scalars", "reviews") else [])
                          for f, ws in WRITER_OF_RECORD.items()}}
        self.__dict__.pop("_out_cache", None)
        self._head_revs = {}
        try:
            self._head_revs = self.hist("head_revs") or {}
        except (Exception, SystemExit):   # noqa: BLE001 — 版の履歴が作れない盤面は読み替えを諦める（upcast が測らない）
            self._head_revs = {}
        self.__dict__.pop("_out_cache", None)
        return self


def recorded(rd, nid, cond):
    """周の rd に残った評価: 条件外（na の理由が cond <名前>: …）なら False、走った・省かれた・止めた・出したなら True、無ければ None"""
    why = (rd.get("na") or {}).get(nid)
    if isinstance(why, str):
        return False if why.startswith(f"cond {cond}:") else None
    if nid in (rd.get("done") or {}) or nid in (rd.get("skipped") or {}) or nid in (rd.get("stopped") or {}):
        return True
    if any(i.get("node") == nid for i in (rd.get("instances") or {}).values()):
        return True
    return None


def replay(board_dir, graph_path, repo=None):
    """盤面の全部の周で、条件を持つ節の評価を今の rules で作り直して記録と比べる ——（評価した数, 食い違い[], 読み替えた欄）"""
    b = ReplayBoard(board_dir, graph_path, repo)
    conds = getattr(b.rules, "CONDS", {})
    n_eval, diffs = 0, []
    once_done = set()
    for rd in b.full["rounds"]:
        n = rd.get("round")
        for nid, node in b.nodes.items():
            c = node.get("cond")
            if not c or c not in conds or nid in once_done:
                continue
            want = recorded(rd, nid, c)
            if want is None:
                continue
            if node.get("once") and want is True:
                once_done.add(nid)
            try:
                got, why = b.at(n, nid).cond(c)
            except (Exception, SystemExit) as e:   # noqa: BLE001 — 評価できなかった回も食い違いとして名指す
                got, why = None, f"評価できない（{type(e).__name__}: {str(e)[:120]}）"
            n_eval += 1
            if got is not want:
                diffs.append({"round": n, "node": nid, "cond": c, "recorded": want, "now": got, "why": why})
    return n_eval, diffs, sorted(b.upcasts)


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):   # 盤面の理由の文（日本語）を書くので、Windows の既定コーデックに依らない
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sw = sub.add_parser("sweep")
    sw.add_argument("--graph", required=True)
    sw.add_argument("--boards", help="盤面の置き場の glob（既定: このリポジトリの共有の git ディレクトリの下の review-loop の盤面全部）")
    sw.add_argument("--repo", help="版を引くリポジトリ（既定: カレントのリポジトリ）")
    sw.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    repo = a.repo or (_git(".", "rev-parse", "--show-toplevel") or "").strip() or None
    pattern = a.boards
    if not pattern:
        common = (_git(".", "rev-parse", "--path-format=absolute", "--git-common-dir") or "").strip()
        pattern = f"{common}/**/graphloops/review-loop/*/"
    boards = sorted(p for p in glob.glob(pattern, recursive=True) if (pathlib.Path(p) / "state.json").is_file())
    if not boards:
        print(f"NG 盤面が 1 つも見つからない（{pattern}）——0 件の掃引は何も確かめていない")
        return 1
    total, rows, upcasts = 0, [], {}
    for d in boards:
        try:
            n, diffs, up = replay(d, a.graph, repo)
        except (Exception, SystemExit) as e:   # noqa: BLE001
            rows.append({"board": d, "error": f"{type(e).__name__}: {str(e)[:200]}"})
            continue
        total += n
        rows += [{"board": d, **x} for x in diffs]
        for u in up:
            upcasts[u] = upcasts.get(u, 0) + 1
    summary = {"boards": len(boards), "evaluated": total, "mismatches": len([r for r in rows if "error" not in r]),
               "errors": len([r for r in rows if "error" in r]), "upcasts": upcasts}
    print(json.dumps({"summary": summary, "rows": rows} if a.json else summary, ensure_ascii=False, indent=1))
    return 0 if not rows else 2


if __name__ == "__main__":
    sys.exit(main())
