"""記録の検証器 review-record.py に渡す「壊した記録」を作る。作り方は tests/run.sh の write_broken_records の heredoc を読む。

写しを持たないのは、新旧の検査が同じ入力を読むことを作りで縛るため（写しは食い違っても何も赤くならない）。
区切りが引用付き（<<'PY'）なので本文は字のままの Python で、bash を通さずに起こせる。関数の形が変わったら、
黙って別の物を読まずに止める（ledger.py の SECTION と同じ流儀）。
"""
import pathlib
import subprocess
import sys

HEAD = ("write_broken_records() {", '    "$PY_BIN" - "$ROOT" "$WORK" <<\'PY\'')
TAIL = ("PY", "}")


def generator(root):
    """tests/run.sh の write_broken_records の heredoc の本文"""
    lines = (pathlib.Path(root) / "tests" / "run.sh").read_text(encoding="utf-8").splitlines()
    try:
        a = lines.index(HEAD[0])
        b = lines.index(TAIL[0], a)
    except ValueError:
        a = b = None
    # 定義が 2 つあれば bash は後のほうを使うので、最初の 1 つを読むと別の物になる
    if a is None or lines.count(HEAD[0]) != 1 or tuple(lines[a:a + 2]) != HEAD or tuple(lines[b:b + 2]) != TAIL:
        raise SystemExit(f"tests/run.sh の write_broken_records が {HEAD} … {TAIL} の形でない"
                         "——台本の関数を変えたら、tests/py/broken_records.py も直せ")
    return "\n".join(lines[a + 2:b]) + "\n"


def write_all(root, work):
    """<root>/templates の雛形から壊した記録を <work> の下に書く（<work> は在る空のディレクトリ）"""
    subprocess.run([sys.executable, "-", str(root), str(work)], input=generator(root).encode("utf-8"), check=True)
