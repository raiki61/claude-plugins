#!/usr/bin/env bash
# リポジトリの .sh を、CI と同じ版の shellcheck（-S warning）で見る。回すのは 2 か所: 軽い検査（scripts/light-check.sh。
# main へ入れるゲートと main への push の前のフック）と tests/run.sh。CI の段（.github/workflows/test.yml の shellcheck）は
# pip で同じ版を入れて回す。版は下の SHELLCHECK_PY で、test.yml の pip の行と同じ値（tests/run.sh の SHELLCHECK_PIN_OK が突き合わせる）。
# 足した訳: ゲートが shellcheck を回さず、shellcheck の指摘は main に入った後の CI で初めて赤になった
# （2026-11-18 の run 44272400817。tests/run.sh の trap の SC2154 で test の全 job が赤。頼み c2aa8f）。
# 版の行は CR を落として見る（Windows の CI で CRLF の出力に当たっても同じ版と読む）。shellcheck の選び方: PATH の shellcheck が同じ版ならそれ、無ければ uvx で同じ版を取る（初回だけ PyPI から取り、後は uv の cache）。
# 終わりの値: 0 は指摘なし、1 は指摘あり、3 は同じ版の shellcheck を用意できない（uv が無い・PyPI に届かない）。
# 3 を赤にするか見送りにするかは呼ぶ側が決める。
set -uo pipefail
SHELLCHECK_PY=0.11.0.1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
want="version: ${SHELLCHECK_PY%.*}"
if command -v shellcheck >/dev/null 2>&1 && shellcheck --version 2>/dev/null | tr -d '\r' | grep -qx "$want"; then
    sc=(shellcheck)
elif command -v uvx >/dev/null 2>&1 && uvx --from "shellcheck-py==$SHELLCHECK_PY" shellcheck --version 2>/dev/null | tr -d '\r' | grep -qx "$want"; then
    sc=(uvx --from "shellcheck-py==$SHELLCHECK_PY" shellcheck)
else
    echo "shellcheck.sh: 版 ${SHELLCHECK_PY%.*} の shellcheck を用意できない（PATH に同じ版が無く、uvx でも取れない。uv を入れるか、pip install shellcheck-py==$SHELLCHECK_PY）"
    exit 3
fi
# 写した第三者の文（superpowers の写し）は直さない写しなので見ない。写しの一致は works/tests/test_sp_skills.py の VendoredCopyCase が縛る
files=()
while IFS= read -r f; do files+=("$f"); done < <(find "$ROOT" -name "*.sh" -not -path "*/.git/*" -not -path "*/.shared/borrow/superpowers/*" | sort)
[ "${#files[@]}" -gt 0 ] || { echo "shellcheck.sh: 見る .sh が 1 本も無い（置き場の探し方が壊れている）"; exit 1; }
"${sc[@]}" -S warning "${files[@]}" || exit 1
