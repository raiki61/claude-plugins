#!/bin/sh
# works/dev/check.sh
#
# 使い捨ての対象リポジトリを作り、その中で固定した版の Archon の
# `validate workflows <名>`（works 自身の工程 works/<d>/<d>.yaml を 1 本ずつ）と `workflow test works` を回す。
# どれか 1 つでも赤なら終了コード 1（赤でも残りは全部回す）。
# Archon に同梱の工程は見ない（Ruling R10。archon-smart-pr-review は .archon/mcp/ntfy.json が無くて必ず赤になる）。
# WORKS_DEV_ARCHON は Archon を呼ぶ殻の差し替え（既定は同じフォルダの archon.sh。tests/test_dev.py が偽物を差す）。
set -eu

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
WORKS_DIR="$(cd "$DEV_DIR/.." && pwd -P)"
ARCHON="${WORKS_DEV_ARCHON:-$DEV_DIR/archon.sh}"
TARGET_DIR="$(mktemp -d "${TMPDIR:-/tmp}/works-check.XXXXXX")"
trap 'rm -rf "$TARGET_DIR"' EXIT

sh "$DEV_DIR/mktarget.sh" "$TARGET_DIR" >/dev/null

status=0

# Archon は .archon/.env などを process の cwd 基準で読むので、--cwd ではなく実際に
# 対象の中へ cd してから回す。validate は認証が要らないので keychain を読ませない。
for yaml in "$WORKS_DIR"/*/*.yaml; do
  name="$(basename "$(dirname "$yaml")")"
  [ "$(basename "$yaml" .yaml)" = "$name" ] || continue
  if ! (cd "$TARGET_DIR" && WORKS_DEV_NO_AUTH=1 sh "$ARCHON" validate workflows "$name"); then
    status=1
  fi
done

if ! (cd "$TARGET_DIR" && sh "$ARCHON" workflow test works); then
  status=1
fi

exit "$status"
