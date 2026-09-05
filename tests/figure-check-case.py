#!/usr/bin/env python3
"""figure-check.py（絵の幅と縦線の検査）を固定の図で叩く。run.sh から case 名で呼ぶ。

gh にも git にも触らない。通る図は命令書の例（14 行。仕様で検査済み）をそのまま使い、
崩し方は「1 行だけ 1 桁ずらす」「1 行だけ幅を超える」のように、目視では見落とす形にする。
合否は落ちる／通るだけでなく、**行と桁が出力に出ること**で見る（どこを直すかを AI に返す
のが目的なので、位置が無い出力は役に立たない）。

CLI（file 引数・標準入力・終了コード）は pass の case で 1 回だけ subprocess で確かめ、
他の case は純関数 report() を直接呼ぶ。"""

import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "attention" / "scripts" / "figure-check.py"
spec = importlib.util.spec_from_file_location("figure_check", SCRIPT)
fc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fc)

# 命令書の例をそのまま使う（写しを別に持つと、例を直したときに検査だけ古い図を守り続ける）。
# 縦線の列は 4, 15, 31, 45（0 始まり）。最終行に改行を付けて file / heredoc の形に揃える
_DOC = (ROOT / "attention" / "commands" / "catchup.md").read_text(encoding="utf-8")
_M = re.search(r"^```text\n(.*?)\n```$", _DOC, re.S | re.M)
assert _M, "catchup.md に ```text の絵の例が無い"
GOOD = _M.group(1) + "\n"
GOOD_LINES = GOOD.split("\n")[:-1]


def verdict(want, out):
    bad = [k for k, v in want.items() if not v]
    return "FIGURE_OK" if not bad else "FIGURE_NG " + ",".join(bad) + "\n" + out


def replaced(lineno, new_line):
    """GOOD の lineno 行目（1 始まり）だけを差し替えた図。"""
    lines = list(GOOD_LINES)
    lines[lineno - 1] = new_line
    return "\n".join(lines) + "\n"


def run_cli(args, stdin_text):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin_text,
                       capture_output=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout + r.stderr).strip()


CASES = {}


def case(name):
    def deco(fn):
        CASES[name] = fn
        return fn
    return deco


@case("pass")
def _pass():
    """通る例は 14 行・最大 48 桁で通る。file でも標準入力でも同じ 1 行で exit 0。"""
    code, lines = fc.report(GOOD)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = os.path.join(tmp, "fig.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(GOOD)
        file_code, file_out = run_cli([path], "")
    stdin_code, stdin_out = run_cli([], GOOD)
    out = "\n".join(lines)
    return verdict({"exit": code == 0,
                    "line": out == "通った（14 行、最大 48 桁）",
                    "file": (file_code, file_out) == (0, out),
                    "stdin": (stdin_code, stdin_out) == (0, out)},
                   "\n".join((out, file_out, stdin_out)))


@case("width")
def _width():
    """縦線の右に全角の注釈を足して 60 桁を超えた行は、行番号と実際の幅で落ちる（縦線は元の桁の
    ままなので、落ちるのは幅の 1 件だけ）。短い注釈なら通る。"""
    line7 = "    │ 「gh pr checkout N で取れる」の案内    │ ← 前の版は案内だけで止まる"
    w = fc.width(line7)
    assert w > 60, w  # 検査の材料が幅を超えていなければ検査が空振りする
    code, lines = fc.report(replaced(7, line7))
    narrow = replaced(7, "    │ 「gh pr checkout N で取れる」の案内    │ ← 案内だけ")
    n_code, n_lines = fc.report(narrow)
    cli_code, cli_out = run_cli([], replaced(7, line7))  # 落ちる側の終了コードも CLI で 1 回見る
    out = "\n".join(lines + n_lines)
    return verdict({"exit": code == 1,
                    "line": f"行 7: 幅 {w} 桁（60 まで）" in lines,
                    "only": len(lines) == 1,
                    "narrow": n_code == 0,
                    "cli": cli_code == 1 and cli_out == "\n".join(lines)}, out)


@case("lines")
def _lines():
    """15 行目（空行でも）を足すと落ちる。行数が出る。"""
    code, lines = fc.report(GOOD + "\n")
    out = "\n".join(lines)
    return verdict({"exit": code == 1, "line": "行数 15 行（14 まで）" in lines,
                    "only": len(lines) == 1}, out)


@case("bar")
def _bar():
    """1 行の 2 本目の │ だけを 1 桁右にずらす（後ろの 2 本は元の桁のまま）と、その行と桁で
    落ちて縦線の列が添う。全角のラベルで 1 桁ずれるのが典型（「番号」の後ろの空白が 1 つ多い）。"""
    shifted = replaced(3, "    │ 番号  ───→│              │             │")
    code, lines = fc.report(shifted)
    out = "\n".join(lines)
    return verdict({"exit": code == 1,
                    "line": "行 3 桁 16: │ がずれ（縦線の列は 4, 15, 31, 45）" in lines,
                    "only": len(lines) == 1}, out)


@case("bar-lone")
def _bar_lone():
    """縦線の列が 1 つも無い図（│ が 1 本だけ）では、その 1 本がずれとして出て列は「無い」。"""
    code, lines = fc.report("a │ b\nc\n")
    out = "\n".join(lines)
    return verdict({"exit": code == 1,
                    "line": "行 1 桁 2: │ がずれ（縦線の列は 無い）" in lines}, out)


@case("box")
def _box():
    """┌┐ の幅と └┘ の幅が違えば箱がずれ。合っていれば通る（箱の │ も縦線の列に入る。
    中身が 1 行の箱は │ が 1 行にしか無いので縦線の列にならない——中身は 2 行以上）。"""
    good = "┌────┐\n│ ab │\n│ cd │\n└────┘\n"
    bad = "┌────┐\n│ ab │\n│ cd │\n└─────┘\n"
    lone = "┌────\n│ ab │\n│ cd │\n└────┘\n"
    top_only = "┌────┐\n│ ab │\n│ cd │\n"
    g_code, g_lines = fc.report(good)
    b_code, b_lines = fc.report(bad)
    l_code, l_lines = fc.report(lone)
    t_code, t_lines = fc.report(top_only)
    out = "\n".join(g_lines + b_lines + l_lines + t_lines)
    return verdict({"good": g_code == 0,
                    "bad": b_code == 1 and "行 4 桁 0: 箱がずれ（上辺は行 1 で 5 桁、下辺は 6 桁）" in b_lines,
                    "lone": l_code == 1 and "行 1 桁 0: 箱がずれ（同じ行に対の罫線が無い）" in l_lines,
                    "top_only": t_code == 1 and "箱がずれ（上辺 ┌┐ が 1 組、下辺 └┘ が 0 組）" in t_lines},
                   out)


@case("empty")
def _empty():
    """空の入力は通さない（何も渡っていないのに「通った」と言わない）。"""
    code, lines = fc.report("")
    return verdict({"exit": code == 1, "line": lines == ["図が空（何も渡されていない）"]},
                   "\n".join(lines))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        sys.exit("使い方: figure-check-case.py <" + "|".join(CASES) + ">")
    print(CASES[sys.argv[1]]())
    return 0


if __name__ == "__main__":
    sys.exit(main())
