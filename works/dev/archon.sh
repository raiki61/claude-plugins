#!/bin/sh
# works/dev/archon.sh <archon の引数…>
#
# 固定した版の Archon の実行ファイルを WORKS_DEV_HOME の下にキャッシュし、sha256 を
# 確かめてから、HOME・ARCHON_HOME・CLAUDE_CONFIG_DIR・XDG_* を全部そこへ向けて隔離した
# 状態で実行ファイルを exec する。works/ のパックには入らない（77MB 級のため）。
set -eu

ARCHON_VERSION="v0.11.1"
ARCHON_SHA256="b9338474fd3151d5d5402d76ae278105e65835f2e3506a93f0e5e4a378d10ede"
ARCHON_BIN_NAME="archon-darwin-arm64"

WORKS_DEV_HOME="${WORKS_DEV_HOME:-${TMPDIR:-/tmp}/works-dev}"

# keychain は HOME を隔離する前に読む（macOS の security はログイン keychain を
# $HOME 基準で探すので、後で読むと隔離した偽の HOME の下を探して必ず失敗する）。
# WORKS_DEV_NO_AUTH=1 のときは読まない（テストなど、認証が要らないとき用）。
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ "${WORKS_DEV_NO_AUTH:-}" != "1" ]; then
  CLAUDE_CODE_OAUTH_TOKEN="$(security find-generic-password -s claude-code-oauth-p1 -w)"
  export CLAUDE_CODE_OAUTH_TOKEN
fi

BIN_DIR="$WORKS_DEV_HOME/bin"
BIN_PATH="$BIN_DIR/$ARCHON_BIN_NAME"

mkdir -p "$BIN_DIR"

# 既にキャッシュにあるなら、確かめるだけでネットワークには出ない。
if [ ! -f "$BIN_PATH" ]; then
  gh release download "$ARCHON_VERSION" -R coleam00/Archon -p "$ARCHON_BIN_NAME" -D "$BIN_DIR" --clobber
fi

actual_sha256="$(shasum -a 256 "$BIN_PATH" | awk '{print $1}')"
if [ "$actual_sha256" != "$ARCHON_SHA256" ]; then
  echo "archon.sh: sha256 mismatch for $BIN_PATH (expected $ARCHON_SHA256, got $actual_sha256)" >&2
  exit 1
fi

chmod +x "$BIN_PATH"

# HOME・ARCHON_HOME・Claude の設定・XDG_* を全部 WORKS_DEV_HOME の下へ隔離する
# （keychain はもう読み終えている）。
HOME="$WORKS_DEV_HOME/home"
ARCHON_HOME="$WORKS_DEV_HOME/archon-home"
CLAUDE_CONFIG_DIR="$WORKS_DEV_HOME/claude-config"
XDG_CONFIG_HOME="$WORKS_DEV_HOME/xdg-config"
XDG_DATA_HOME="$WORKS_DEV_HOME/xdg-data"
XDG_CACHE_HOME="$WORKS_DEV_HOME/xdg-cache"
XDG_STATE_HOME="$WORKS_DEV_HOME/xdg-state"

mkdir -p "$HOME" "$ARCHON_HOME" "$CLAUDE_CONFIG_DIR" \
  "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME" "$XDG_STATE_HOME"

export HOME ARCHON_HOME CLAUDE_CONFIG_DIR
export XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME XDG_STATE_HOME

ARCHON_TELEMETRY_DISABLED=1
DO_NOT_TRACK=1
export ARCHON_TELEMETRY_DISABLED DO_NOT_TRACK

exec "$BIN_PATH" "$@"
