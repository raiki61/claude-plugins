#!/usr/bin/env bash
# 軽い検査: main へ入る commit に、--land でも直接の push でも通させる 4 つ（共有の写し・語・機械が読む値の決まり・shellcheck）と、ブランチが消した
# 試験の一覧（tests/removed-tests.py。止めずに出すだけ。試験の件数の定数を突き合わせる形は 2026-11-18 にやめた。docs/reform/ledger.md）。全部で数十秒
# （2026-11-18 の実測で、shellcheck を足す前が約 9 秒、shellcheck だけで約 15 秒）。
# 回すのは 2 か所: main へ入れるコマンド（works-dispatch の --land）のゲート（.claude/company.toml の [land] の check の頭）と、
# main への push の前のフック（.githooks/pre-push）。--land を通さない急ぎの直接の push でも、フックがこれを回し、落ちれば push を止める
# （2026-10-20、受付 2ee37b。ゲートを通らずに直接 push された commit d3be9e43 が語の検査に落ち、main が赤になってほかの --land が全部落ちた）。
# 試験を走らせる物はここに入れない。試験は main に入った後の CI だけが回す（持ち主 2026-11-23「重いのでテストはCIで回すようにしてね」。docs/adr/0077-tests-run-only-in-ci.md）。
# 緑で、作業ツリーに変更が無ければ、その tree の印を共通の git の場所（light-check-ok/<tree>）に残す。フックは同じ tree の印を見たら
# 回し直さない（--land はゲートで回した後に同じ commit を push するので、二度回さない）。
# 止めない道: --no-verify の push と GitHub の画面での変更。サーバの側（GitHub の ruleset の必須の status check）で止めると、
# --land も main へ入れる前に CI を待つことになり、「main の CI は待たない」決め（持ち主 2026-10-16。ルートの CLAUDE.md の「判断の線」）とぶつかる。
# 入った後の赤は main の CI（.github/workflows/test.yml。tests/run.sh がこの 4 つも回す）が見つける。
# core.hooksPath がどの設定（clone・global など）にも無ければ、この clone に .githooks を書く（clone ごとの入れ忘れを、--land のゲートで塞ぐ。worktree は設定を共有する）。
# 別の値なら止める（持ち主の他のフックを黙って外さない）。終わりの値: 0 は緑、それ以外は赤。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
hooks=$(git config --get core.hooksPath || true)
if [ -z "$hooks" ]; then
    git config --local core.hooksPath .githooks
    echo "light-check: この clone の core.hooksPath に .githooks を書いた（main への push の前に軽い検査を回す）"
elif [ "$hooks" != .githooks ]; then
    echo "light-check: core.hooksPath が $hooks で、.githooks でない（main への push の前の軽い検査が回らない）。git config core.hooksPath .githooks で直す"
    exit 1
fi
PY_BIN=$(command -v python3 || command -v python || true)
[ -n "$PY_BIN" ] || { echo "light-check: python3 / python が PATH に無い"; exit 2; }
"$PY_BIN" scripts/shared-copies.py
"$PY_BIN" tests/removed-tests.py
"$PY_BIN" scripts/terms.py
"$PY_BIN" tests/value-rules.py
# 静的検査の shellcheck（CI と同じ版。足した訳と版の選び方は scripts/shellcheck.sh の頭）。同じ版を用意できない機械（uv が無い・PyPI に届かない）では
# 見送りの行を出して止めない。tests/run.sh も手元に shellcheck が無ければ見送り、入った後の CI がどの OS でも回す（docs/reform/ledger.md の頼み c2aa8f）
sc_rc=0
bash scripts/shellcheck.sh || sc_rc=$?
if [ "$sc_rc" = 3 ]; then
    echo "light-check: shellcheck を見送った（上の訳。main に入った後の CI が回す）"
elif [ "$sc_rc" != 0 ]; then
    echo "light-check: shellcheck が指摘を出した（上の行を直す）"
    exit 1
fi
if [ -z "$(git status --porcelain)" ]; then
    mark="$(git rev-parse --path-format=absolute --git-common-dir)/light-check-ok"
    mkdir -p "$mark"
    : > "$mark/$(git rev-parse 'HEAD^{tree}')"
fi
