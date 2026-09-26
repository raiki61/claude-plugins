#!/bin/sh
# works/dev/check.sh
#
# 使い捨ての対象リポジトリを作り、その中で固定した版の Archon の
# `validate workflows` と `workflow test works` を回す。どちらかが赤なら終了コード 1。
set -eu

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
TARGET_DIR="$(mktemp -d "${TMPDIR:-/tmp}/works-check.XXXXXX")"
trap 'rm -rf "$TARGET_DIR"' EXIT

sh "$DEV_DIR/mktarget.sh" "$TARGET_DIR" >/dev/null

status=0

if ! sh "$DEV_DIR/archon.sh" validate workflows --cwd "$TARGET_DIR"; then
  status=1
fi

if ! sh "$DEV_DIR/archon.sh" workflow test works --cwd "$TARGET_DIR"; then
  status=1
fi

exit "$status"
