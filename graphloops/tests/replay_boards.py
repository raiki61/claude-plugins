"""盤面の再生の突き合わせ——盤面が周ごとに記録した条件の評価（周の rd: 条件外 na の『cond <名前>: 理由』と、走った節）を、
今の rules と graph の条件の関数で評価し直して比べる（Temporal の replay test と同じ形: 新しいコードが記録済みの履歴と両立するか）。

正解は旧いコードの出力ではなく、盤面に記録された評価そのもの。周ごとに残っていない値（周の途中の記録・盤面の loop）は作らない:
  - 節の出力と周の rd は、その節の祖先（deps の推移閉包）が出した物だけを今の周の値として見せる（評価した時点に在った物）
  - 周の記録は rounds/round-<N>.json の欄を、書き手の節が祖先に在る物だけ（素材・単位・問い・R の判定・規模の数値）
  - 記録の process は最後の値。周を刻んだ行（fixes）はその周より前の行だけ
  - 盤面の loop は run の状態のうち、周をまたいで一方向にだけ変わる旗（request_fixed_at・escalated）を、立った周より後にだけ見せる
旧い版の rules が書いた出力（ブロックの出口の欄を持たない出力）は、この道具では読み替えない——本番の読み替え（rules の hist と
条件の部品）をそのまま通し、通ったことを印で数える（読み替えの写しを道具に持つと、再生が本番の読み替えを確かめなくなる）。
道具が足すのは記録の周に合わせて測り直す値 1 つだけ: 周の頭の節の、前の周の P3 が触ったファイル（今の rules と同じ定義——前の周の
頭の版と、この周の頭の版の木の差——を git で測る。rules は旧い出力でこの値を測り直さず、触った側へ倒す）。

入口は 2 つ: replay(盤面, graph) は 1 つの盤面の周ごとの食い違いを返し（台本が CI で呼ぶ）、sweep は置き場の盤面を全部舐める
（手で打つ入口。見つかった盤面が 0 件なら exit 1——飛ばして緑にしない）:

  python3 graphloops/tests/replay_boards.py sweep --graph graphloops/graphs/review-loop.json [--boards <盤面の glob>] [--old-rules <旧い rules>]

受け付けの再生（replay_accepts）: 読み口を受ける新しい形へ移した受け付けの関数（POST_CHECKS）を、盤面が受け付けた返答（周の instance の
出力）に、受け付けた時点の見え方で当て直す。盤面が受け付けた返答は、今の関数でも受け付けるのが正解。旧い rules（--old-rules。移す前の
版の rules のファイル）を渡すと、同じ返答に旧い関数も当て、受け付けたか・注記が新旧で一致するかも比べる（移してから旧を消す前の突き合わせ）。
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
from engine.advance import load_item  # noqa: E402
from engine.rules import load_rules, takes_view  # noqa: E402
from engine import util  # noqa: E402
from engine.record import writes_to  # noqa: E402
from engine.util import get_path, has_path, pick, read_json, safe_name  # noqa: E402

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
    """記録の周に合わせて測り直す値（周の頭の節の changed_since_prev_round）だけを足す（足した欄の名前を返す）。今の形の出力はそのまま"""
    got = []
    if not isinstance(out, dict):
        return out, got
    out = copy.deepcopy(out)
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
    return out, got


class ReplayBoard(board_mod.Board):
    """盤面を読むだけの Board——ディスクには何も書かない。周 N・節 nid の評価の時点の見え方を組む"""

    def __init__(self, d, graph_path, repo=None):   # super を呼ばない（盤面の state.graph でなく渡した graph で読む）
        self.dir = pathlib.Path(d)
        self.full = read_json(self.dir / "state.json")
        self.final_record = read_json(self.dir / "record.json")
        util.GIT_CWD = (self.full.get("inputs") or {}).get("cwd")   # Board と同じく、規則の関数の git は盤面の対象リポジトリで走らせる
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

    def hist(self, name):
        """本番の hist を呼び、旧い出力を読み替えた印（from_old_output）の付いた値を数える"""
        v = super().hist(name)
        if isinstance(v, dict) and v.get("from_old_output"):
            self.upcasts.add(f"hist.{name}")
        return v

    def cond(self, name, overlay=None):
        """本番の条件を呼び、条件の部品が旧い出力を読み替えた痕跡（unevaluable）を数える"""
        seen = len(self.state.get("unevaluable") or [])
        got = super().cond(name, overlay)
        for u in (self.state.get("unevaluable") or [])[seen:]:
            self.upcasts.add(f"cond:{u['trigger']}")
        return got

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


def _old_rules(path, graph_path):
    """旧い版の rules のファイルを、今の graph と同じ差し込み（INJECT）で読む（graph の rules の宣言を差し替えた写しで load_rules を通す）"""
    g = json.loads(pathlib.Path(graph_path).read_text(encoding="utf-8"))
    g["rules"] = str(pathlib.Path(path).resolve())
    return load_rules(str(graph_path), g)


def replay_accepts(board_dir, graph_path, repo=None, old_rules_path=None, by_fn=None):
    """盤面が受け付けた返答に、新しい形の受け付けの関数（と機械の節・記録を書く op）を当て直す ——（当てた数, 食い違い[], 新旧とも拒む[]）。
    by_fn（dict）を渡すと関数ごとの当てた数を足す——稀な枝だけで働く関数は盤面に 1 回も当たらないことがあり、全体の『食い違い 0』は
    その関数について何も確かめていない（旧い形を消す前に関数ごとの数を見る）。食い違いは、旧い関数と
    受け付けたか注記が違う行（旧い rules を渡さない回は、今の関数が拒む行）と当てられない（例外）の行。新旧とも拒む行は、盤面を作った
    版の graph・rules が今と違う（返答の型や柵がその後に変わった）盤面で起きる——移しの食い違いではないので別に返す"""
    b = ReplayBoard(board_dir, graph_path, repo)
    old = _old_rules(old_rules_path, graph_path) if old_rules_path else None
    checks = getattr(b.rules, "POST_CHECKS", {})
    n_eval, diffs, both = 0, [], []
    for rd in b.full["rounds"]:
        n = rd.get("round")
        for inst in (rd.get("instances") or {}).values():
            nid, pc = inst.get("node"), (b.nodes.get(inst.get("node")) or {}).get("post_check")
            fn = checks.get(pc)
            if inst.get("status") != "done" or not inst.get("output_file") or fn is None or not takes_view(fn):
                continue
            row = {"round": n, "node": nid, "post_check": pc}
            def old_says(at, out, item):
                try:   # 当て直しの前に見え方を組み直す（新しい関数は盤面を書かないが、旧い関数は書く物が在る）
                    return _said(at.at(n, nid).rule(pc, old.POST_CHECKS[pc], nid, copy.deepcopy(out), item))
                except Exception as e:   # noqa: BLE001 — 旧い関数の拒否（Reject）も受け付けなかった側として比べる
                    return (False, None) if type(e).__name__ in ("Reject", "AnswerReject") else ("例外", type(e).__name__)
            try:
                at = b.at(n, nid)
                out = copy.deepcopy(at.read_out(inst["output_file"], board_relative=True))
                item = load_item(inst, at.dir)
            except (Exception, SystemExit) as e:   # noqa: BLE001 — 組めなかった回も食い違いとして名指す
                diffs.append({**row, "why": f"見え方を組めない（{type(e).__name__}: {str(e)[:160]}）"})
                continue
            try:
                _, got = at.rule(pc, fn, nid, copy.deepcopy(out), item)
                now = _said((True, got))
            except Exception as e:   # noqa: BLE001 — 旧い関数も同じ例外で落ちる返答（盤面を作った版の型が今と違う）は新旧とも拒む側
                if old is not None and old_says(at, out, item) == ("例外", type(e).__name__):
                    both.append({**row, "why": f"新旧とも {type(e).__name__}"})
                else:
                    diffs.append({**row, "why": f"当てられない（{type(e).__name__}: {str(e)[:160]}）"})
                continue
            was = old_says(at, out, item) if old is not None else None
            n_eval += 1
            _tally(by_fn, f"POST_CHECKS.{pc}")
            if old is not None and was != now:
                diffs.append({**row, "why": f"旧い関数 {was} と今の関数 {now} が違う（今の拒否: {str(got.get('reason'))[:160]}）"})
            elif old is None and not now[0]:
                diffs.append({**row, "why": f"盤面が受け付けた返答を今の関数が拒む: {str(got.get('reason'))[:200]}"})
            elif not now[0]:
                both.append({**row, "why": str(got.get("reason"))[:200]})
    # 新しい形へ移した機械の節は、同じ見え方で今の関数の出力を作り、旧い関数の出力（旧い rules を渡さない回は、周に記録した出力
    # out/r<周>/<節>.json）と比べる
    builtins = getattr(b.rules, "BUILTINS", {})
    for rd in b.full["rounds"]:
        n = rd.get("round")
        for nid, node in b.nodes.items():
            fn = builtins.get(node.get("builtin"))
            f = b.dir / "out" / f"r{n}" / (safe_name(nid) + ".json")
            if fn is None or not takes_view(fn) or nid not in (rd.get("done") or {}) or not f.is_file():
                continue
            row = {"round": n, "node": nid, "builtin": node["builtin"]}
            try:
                _, got = b.at(n, nid).rule(node["builtin"], fn, nid)
            except (Exception, SystemExit) as e:   # noqa: BLE001
                diffs.append({**row, "why": f"当てられない（{type(e).__name__}: {str(e)[:160]}）"})
                continue
            got = {k: v for k, v in got.items() if k != "effects"}
            n_eval += 1
            _tally(by_fn, f"BUILTINS.{node['builtin']}")
            if old is not None:
                was = b.at(n, nid).rule(node["builtin"], old.BUILTINS[node["builtin"]], nid)[1]
                was = {k: v for k, v in was.items() if k != "effects"} if isinstance(was, dict) else was
                if got != was:
                    diffs.append({**row, "why": "旧い関数の出力と今の関数の出力が違う"})
            elif got != read_json(f):
                diffs.append({**row, "why": "周に記録した出力と今の関数の出力が違う"})
    # 新しい形へ移した記録を書く op（WRITE_OPS）は、節の受け付けた返答から同じ見え方で書く値を作り、旧い関数が同じ見え方の記録に
    # 書いた値（op の writes_to の path）と比べる（旧い rules を渡さない回は、当てられるかだけを見る）
    ops = getattr(b.rules, "WRITE_OPS", {})
    for rd in b.full["rounds"]:
        n = rd.get("round")
        for inst in (rd.get("instances") or {}).values():
            nid = inst.get("node")
            if inst.get("status") != "done" or not inst.get("output_file"):
                continue
            for w in (b.nodes.get(nid) or {}).get("writes") or []:
                fn = ops.get(w.get("op"))
                if fn is None or not takes_view(fn):
                    continue
                row = {"round": n, "node": nid, "write_op": w["op"]}
                try:
                    at = b.at(n, nid)
                    out = at.read_out(inst["output_file"], board_relative=True)
                    frm = w.get("from", "$")
                    if not has_path(out, frm):
                        continue
                    src = out if frm == "$" else get_path(out, frm)
                    src = pick(src, w["pick"]) if "pick" in w else src
                    ww = {**w, "_item": load_item(inst, at.dir)}
                    _, got = at.rule(w["op"], fn, nid, copy.deepcopy(src), ww)
                except (Exception, SystemExit) as e:   # noqa: BLE001
                    diffs.append({**row, "why": f"当てられない（{type(e).__name__}: {str(e)[:160]}）"})
                    continue
                n_eval += 1
                _tally(by_fn, f"WRITE_OPS.{w['op']}")
                if old is not None:
                    at = b.at(n, nid)
                    try:   # 旧い形の op は見え方の記録に書き、新しい形の op（移した後の版の rules）は値を返す
                        new_old, was = at.rule(w["op"], old.WRITE_OPS[w["op"]], nid, copy.deepcopy(src), ww)
                        was = was if new_old else get_path(at.record, writes_to(fn, w["op"], w))
                    except (Exception, SystemExit) as e:   # noqa: BLE001
                        was = ("例外", type(e).__name__)
                    if was != got:
                        diffs.append({**row, "why": f"旧い関数が書いた値と今の関数が返した値が違う（旧 {str(was)[:120]} / 今 {str(got)[:120]}）"})
    return n_eval, diffs, both


def _said(ran):
    """受け付けの関数の返り（Board.rule の（新しい形か, 返り））を（受け付けたか, 注記）に揃える——旧い形は注記を返し、拒否は例外"""
    new, got = ran
    return (got.get("ok") is True, got.get("note")) if new else (True, got or None)


def _tally(by_fn, name):
    if by_fn is not None:
        by_fn[name] = by_fn.get(name, 0) + 1


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
    sw.add_argument("--old-rules", help="受け付けの再生で旧い関数にも当てる、移す前の版の rules のファイル")
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
    total, accepted, refused_by_both, rows, upcasts, by_fn = 0, 0, 0, [], {}, {}
    for d in boards:
        try:
            n, diffs, up = replay(d, a.graph, repo)
            k, adiffs, aboth = replay_accepts(d, a.graph, repo, a.old_rules, by_fn)
        except (Exception, SystemExit) as e:   # noqa: BLE001
            rows.append({"board": d, "error": f"{type(e).__name__}: {str(e)[:200]}"})
            continue
        total, accepted, refused_by_both = total + n, accepted + k, refused_by_both + len(aboth)
        rows += [{"board": d, **x} for x in diffs + adiffs]
        for u in up:
            upcasts[u] = upcasts.get(u, 0) + 1
    summary = {"boards": len(boards), "evaluated": total, "accepts_replayed": accepted, "accepts_refused_by_both": refused_by_both,
               "mismatches": len([r for r in rows if "error" not in r]),
               "errors": len([r for r in rows if "error" in r]), "upcasts": upcasts, "replayed_by_fn": dict(sorted(by_fn.items()))}
    print(json.dumps({"summary": summary, "rows": rows} if a.json else summary, ensure_ascii=False, indent=1))
    return 0 if not rows else 2


if __name__ == "__main__":
    sys.exit(main())
