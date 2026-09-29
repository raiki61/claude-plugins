"""works/dev/report_rejects.py — run をまたいで報告の拒否の数を集計する（開発の殻。読むだけで何も書かない）。

  python3 report_rejects.py <盤面の置き場の根>

根の下を再帰でたどって board/r<N>/ を探し、run（board の親のディレクトリ名）ごとに 1 行をタブ区切りで出す:
  <run>  日付 <YYYY-MM-DD>  拒否 <行数>  cold <回>  format <回>  answer <回>  不明 <回>  上限の受け取り <件>  [読めない <パス>...]
日付は run の最初の拒否の行の at の日付（拒否の無い run は -）で、依頼の基準値と日付ごとに突き合わせるために出す。最後に
全部の run を足した「合計」の 1 行を出す。数えは blk-report/lib/report_roles の count_round_rejects（周ごとの REJECTS_NAME と COLD_MARK_NAME）に任せ、周を足す。
不明は kind の無い行（kind が入る前の run）と知らない kind の行。読めない JSON はその run の行に名指して続け、黙って 0 に
しない。run の並びはパスの順で、現在時刻を入れない（同じ置き場なら同じ出力）。閾値で止めず、いつも exit 0。
"""
import pathlib
import re
import sys

sys.dont_write_bytecode = True
_LIB = pathlib.Path(__file__).resolve().parent.parent / "blk-report" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import report_roles as rr  # noqa: E402

COLUMNS = (*((k, k) for k in rr.REJECT_KINDS), (rr.UNKNOWN_KIND, "不明"), (rr.COLD_UNPASSED, "上限の受け取り"))


def _is_round(p: pathlib.Path) -> bool:
    return p.is_dir() and re.fullmatch(r"r\d+", p.name) is not None


def boards(root: pathlib.Path) -> list:
    """根の下の盤面 board/（r<N>/ を持つ物）をパスの順に"""
    return sorted({p.parent for p in root.rglob("r*") if p.parent.name == "board" and _is_round(p)}, key=str)


def run_counts(board: pathlib.Path) -> tuple:
    """(日付, {列: 回数}, 読めないパス)。日付は最初の拒否の行の at の頭 10 字（行が無ければ "-"）"""
    total = dict.fromkeys((k for k, _ in COLUMNS), 0)
    day, bad = "-", []
    for rd in sorted(filter(_is_round, board.iterdir()), key=lambda p: int(p.name[1:])):
        try:
            got = rr.count_round_rejects(rd)
            rows = rr._read_json(rd / rr.REJECTS_NAME, [])
        except rr.BoardGap:
            bad.append(str(rd / rr.REJECTS_NAME))
            continue
        if day == "-" and rows and rows[0].get("at"):
            day = str(rows[0]["at"])[:10]
        for counts in got.values():
            for k, n in counts.items():
                total[k] += n
    return day, total, bad


def _cells(name: str, day: str, total: dict) -> list:
    rows = sum(total[k] for k in (*rr.REJECT_KINDS, rr.UNKNOWN_KIND))
    return [name, f"日付 {day}", f"拒否 {rows}", *(f"{label} {total[k]}" for k, label in COLUMNS)]


def main(argv) -> int:
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    grand = dict.fromkeys((k for k, _ in COLUMNS), 0)
    for board in boards(pathlib.Path(argv[0])):
        day, total, bad = run_counts(board)
        print("\t".join(_cells(board.parent.name, day, total) + [f"読めない {p}" for p in bad]))
        for k, n in total.items():
            grand[k] += n
    print("\t".join(_cells("合計", "-", grand)))
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
