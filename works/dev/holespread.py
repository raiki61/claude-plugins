"""works/dev/holespread.py — 差分の審査の穴の枝の名札の分布を、記録の残る盤面で測る（線の木の段 4a の Task 2。開発の殻。読むだけで
何も書かない）。設計は docs/plans/2026-10-07-hole-to-branch.md の 5 の 1 と 7 の決め事 1（4b の木の形を作るかの材料）。

  python3 holespread.py <盤面> [<盤面> …]     盤面ごとに 1 行の JSON（標準出力）と、終わりに表（標準エラー）

行: {board, run, items（承認済みの項目の数）, pass1, pass2（各 holeties.spread か null＝義務が無い）, eyes（目が場所を挙げた行の
spread か null）, ties1（穴ごとの {key, branches, via}）}。盤面は開かない（DiskBoard は graph_sha を照らし、scope を登録して書く）。
読むだけの入れ物（SavedBoard）が state.json と盤面のファイルを読み、refix.hole_ties と report.eye_ties をそのまま当てる。
読めない盤面は行に error を置いて続ける。誤り（引数が無い）は標準エラーに 1 行で 2、ほかは 0
"""
import json
import pathlib
import sys

sys.dont_write_bytecode = True
_CORE = pathlib.Path(__file__).resolve().parents[1] / ".shared" / "core"
sys.path.insert(0, str(_CORE))

import holeties  # noqa: E402
import refix  # noqa: E402
import report  # noqa: E402


class SavedBoard:
    """読むだけの盤面（今の周・出力・loop_state・作業ファイルの置き場）。書く口は持たない"""

    def __init__(self, d):
        self.dir = pathlib.Path(d)
        self.state = json.loads((self.dir / "state.json").read_text(encoding="utf-8"))
        self.round = self.state["round"]
        self.loop_state = self.state.get("loop") or {}
        self.scope, self.scope_root = "", self.dir
        self.record = {}

    def work(self, name, round_=None):
        return self.dir / f"r{round_ or self.round}" / name

    def output_of_round(self, nid, rnd):
        info = (self.state.get("outputs") or {}).get(nid)
        if not info or info.get("round") != rnd:
            return None
        return json.loads((self.dir / info["file"]).read_text(encoding="utf-8"))


def row(path) -> dict:
    out = {"board": str(path), "run": pathlib.Path(path).parent.name[:8]}
    try:
        b = SavedBoard(path)
        out["items"] = len(refix.tie_items(b))
        t1, t2 = refix.hole_ties(b, 1), refix.hole_ties(b, 2)
        eyes = report.eye_ties(b)
    except Exception as e:   # 前の版の盤面で欠ける物は行に残して続ける
        out["error"] = f"{type(e).__name__}: {' '.join(str(e).split())[:300]}"
        return out
    out["pass1"] = holeties.spread(t1) if t1 else None
    out["pass2"] = holeties.spread(t2) if t2 else None
    out["eyes"] = holeties.spread(eyes) if eyes else None
    out["ties1"] = [{"key": t["key"], "branches": t["branches"], "via": t["via"], "held": bool(t["held"])} for t in t1]
    return out


def table(rows) -> str:
    head = "run       items  穴  枝1  2以上  無し  held  組 | 2回目の穴 | 目の行(枝1/2以上/無し)"
    lines = [head]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['run']:<9} 読めない: {r['error'][:80]}")
            continue
        p, q, e = r["pass1"] or {}, r["pass2"] or {}, r["eyes"] or {}
        lines.append(f"{r['run']:<9} {r['items']:>5} {p.get('holes', 0):>3} {p.get('single', 0):>4} {p.get('multi', 0):>6} "
                     f"{p.get('none', 0):>5} {p.get('held', 0):>5} {p.get('groups', 0):>3} | {q.get('holes', 0):>8} | "
                     f"{e.get('holes', 0)}（{e.get('single', 0)}/{e.get('multi', 0)}/{e.get('none', 0)}）")
    return "\n".join(lines)


def main(argv) -> int:
    if len(argv) < 2:
        print("使い方: python3 holespread.py <盤面> [<盤面> …]", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    rows = [row(p) for p in argv[1:]]
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    print(table(rows), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
