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

# Archon は .archon/.env などを process の cwd 基準で読むので、--cwd ではなく実際に
# 対象の中へ cd してから回す。validate は認証が要らないので keychain を読ませない。
if ! (cd "$TARGET_DIR" && WORKS_DEV_NO_AUTH=1 sh "$DEV_DIR/archon.sh" validate workflows); then
  status=1
fi

if ! (cd "$TARGET_DIR" && sh "$DEV_DIR/archon.sh" workflow test works); then
  status=1
fi

exit "$status"
