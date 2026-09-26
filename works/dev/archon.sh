#!/bin/sh
# works/dev/archon.sh <archon の引数…>
#
# 固定した版の Archon の実行ファイルを WORKS_DEV_HOME の下にキャッシュし、sha256 を
# 確かめてから、HOME・ARCHON_HOME・CLAUDE_CONFIG_DIR・XDG_* を全部そこへ向けて隔離した
# 状態で実行ファイルを exec する。works/ のパックには入らない（77MB 級のため）。
# 認証を使う実行では、隔離した Archon の設定に模型（WORKS_DEV_MODEL。既定は opus）を毎回書く。
set -eu

ARCHON_VERSION="v0.11.1"
ARCHON_SHA256="b9338474fd3151d5d5402d76ae278105e65835f2e3506a93f0e5e4a378d10ede"
ARCHON_BIN_NAME="archon-darwin-arm64"

WORKS_DEV_HOME="${WORKS_DEV_HOME:-${TMPDIR:-/tmp}/works-dev}"

# 開発の家と対象（cwd）が Claude Code の一時フォルダの下なら、認証も実行ファイルも触らずに止まる（guard.sh）
. "$(cd "$(dirname "$0")" && pwd -P)/guard.sh"
works_dev_refuse_claude_tmp archon.sh "WORKS_DEV_HOME" "$WORKS_DEV_HOME"
works_dev_refuse_claude_tmp archon.sh "対象（cwd）" "$(pwd -P)"

# 認証に既定の口座は無い（Ruling R20）。順は
#   1. CLAUDE_CODE_OAUTH_TOKEN があればそれを使う。
#   2. 無ければ WORKS_KEYCHAIN_ITEM の名の keychain の項目を読む。
#   3. どちらも無ければ、1 行の案内を出して止まる。
# WORKS_DEV_NO_AUTH=1 のときは読まない（テストや validate など、認証が要らないとき用）。
# keychain は HOME を隔離する前に読む（macOS の security はログイン keychain を
# $HOME 基準で探すので、後で読むと隔離した偽の HOME の下を探して必ず失敗する）。
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ "${WORKS_DEV_NO_AUTH:-}" != "1" ]; then
  NO_AUTH_HOWTO="archon.sh: 認証が無い。CLAUDE_CODE_OAUTH_TOKEN（例: claude setup-token で作る）か、トークンを入れた keychain の項目名 WORKS_KEYCHAIN_ITEM を設定する"
  if [ -z "${WORKS_KEYCHAIN_ITEM:-}" ]; then
    echo "${NO_AUTH_HOWTO}" >&2
    exit 2
  fi
  CLAUDE_CODE_OAUTH_TOKEN="$(security find-generic-password -s "$WORKS_KEYCHAIN_ITEM" -w)"
  # 項目が空の値を返したら、空のトークンを渡さずに止まる（項目名は出すが、値は出さない）
  if [ -z "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
    echo "${NO_AUTH_HOWTO}（keychain の項目 ${WORKS_KEYCHAIN_ITEM} が空）" >&2
    exit 2
  fi
  export CLAUDE_CODE_OAUTH_TOKEN
fi

BIN_DIR="$WORKS_DEV_HOME/bin"
BIN_PATH="$BIN_DIR/$ARCHON_BIN_NAME"

mkdir -p "$BIN_DIR"

# 既にキャッシュにあるなら、確かめるだけでネットワークには出ない。
if [ ! -f "$BIN_PATH" ]; then
  gh release download "$ARCHON_VERSION" -R coleam00/Archon -p "$ARCHON_BIN_NAME" -D "$BIN_DIR" --clobber
fi

# 合わなければ止まる。壊れたキャッシュ（ダウンロードが途中で切れた等）は在る限り毎回同じ所で止まるので、
# 消せば次で取り直すと 1 行で案内する。消すのは人に任せる（利用者のファイルを黙って消さない）。
actual_sha256="$(shasum -a 256 "$BIN_PATH" | awk '{print $1}')"
if [ "$actual_sha256" != "$ARCHON_SHA256" ]; then
  echo "archon.sh: sha256 mismatch for $BIN_PATH (expected $ARCHON_SHA256, got $actual_sha256)。壊れたキャッシュなら、このファイルを消して回し直せば取り直す（rm \"$BIN_PATH\"）" >&2
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

# 認証を使う（AI を呼びうる）実行は毎回、隔離した Archon の全体設定に既定の模型を書き、run の題を作る
# 模型も同じにする（TITLE_GENERATION_MODEL。設定済みならそのまま）。書かないと Claude CLI の既定の模型で
# 黙って回る。模型は WORKS_DEV_MODEL（既定は opus）。works の YAML には model: を書かない——利用者の選択を残すため。
# 認証の要らない道（WORKS_DEV_NO_AUTH=1。テスト・validate・workflow test）は変えない（書かない・模型も要らない）。
if [ "${WORKS_DEV_NO_AUTH:-}" != "1" ]; then
  WORKS_DEV_MODEL="${WORKS_DEV_MODEL:-opus}"
  cat >"$ARCHON_HOME/config.yaml" <<EOF
# works/dev/archon.sh が認証を使う実行のたびに書く、隔離した開発用の Archon の全体設定
assistants:
  claude:
    model: $WORKS_DEV_MODEL
EOF
  TITLE_GENERATION_MODEL="${TITLE_GENERATION_MODEL:-$WORKS_DEV_MODEL}"
  export TITLE_GENERATION_MODEL
fi

ARCHON_TELEMETRY_DISABLED=1
DO_NOT_TRACK=1
export ARCHON_TELEMETRY_DISABLED DO_NOT_TRACK

exec "$BIN_PATH" "$@"
