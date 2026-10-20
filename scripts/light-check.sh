#!/usr/bin/env bash
# 軽い検査: main へ入る commit が、どの道で入っても通す 4 つ（共有の写し・試験の件数・語・機械が読む値の決まり）。全部で数十秒。
# 回すのは 2 か所: main へ入れるコマンド（works-dispatch の --land）のゲート（.claude/company.toml の [land] の check の頭）と、
# main への push の前のフック（.githooks/pre-push）。--land を通さない急ぎの直接の push でも、フックがこれを回し、落ちれば push を止める
# （2026-10-20、受付 2ee37b。ゲートを通らずに直接 push された commit d3be9e43 が語の検査に落ち、main が赤になってほかの --land が全部落ちた）。
# 重い検査（tests/land-check.py）はここに入れない（持ち主 2026-10-20「いそぎはlandしなくていいからって。」）。
# 緑で、作業ツリーに変更が無ければ、その tree の印を共通の git の場所（light-check-ok/<tree>）に残す。フックは同じ tree の印を見たら
# 回し直さない（--land はゲートで回した後に同じ commit を push するので、二度回さない）。
# この clone の core.hooksPath が空なら .githooks を書く（clone ごとの入れ忘れを、--land のゲートで塞ぐ。worktree は設定を共有する）。
# 別の値なら止める（持ち主の他のフックを黙って外さない）。終わりの値: 0 は緑、それ以外は赤。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
hooks=$(git config --get core.hooksPath || true)
if [ -z "$hooks" ]; then
    git config core.hooksPath .githooks
    echo "light-check: この clone の core.hooksPath に .githooks を書いた（main への push の前に軽い検査を回す）"
elif [ "$hooks" != .githooks ]; then
    echo "light-check: core.hooksPath が $hooks で、.githooks でない（main への push の前の軽い検査が回らない）。git config core.hooksPath .githooks で直す"
    exit 1
fi
python3 scripts/shared-copies.py
bash tests/count-fences.sh
python3 scripts/terms.py
python3 tests/value-rules.py
if [ -z "$(git status --porcelain)" ]; then
    mark="$(git rev-parse --path-format=absolute --git-common-dir)/light-check-ok"
    mkdir -p "$mark"
    : > "$mark/$(git rev-parse 'HEAD^{tree}')"
fi
