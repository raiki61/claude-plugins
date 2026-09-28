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
works_dev_abs_claude_config
works_dev_refuse_claude_tmp archon.sh "WORKS_DEV_HOME" "$WORKS_DEV_HOME"
works_dev_refuse_claude_tmp archon.sh "対象（cwd）" "$(pwd -P)"

# Claude の包み（works/.shared/core/claude-adapter。README の「Claude の包み」）。WORKS_DEV_ADAPTER=1 で入れる（既定は入れない）。
# 入れる時は、認証を使う実行で隔離した Archon の設定に claudeBinaryPath（包み）を書き、本物の claude を WORKS_REAL_CLAUDE で
# 包みに渡し、env の CLAUDE_BIN_PATH（Archon では設定より強い）を外す。包みの家（会話の id・読んだ記録・起動の記録）は
# WORKS_ADAPTER_HOME（既定は $WORKS_DEV_HOME/adapter）。役の sandbox の Bash から書けない所に置く（guard.sh）。
WORKS_ADAPTER="$(cd "$(dirname "$0")/.." && pwd -P)/.shared/core/claude-adapter"
case "${WORKS_DEV_ADAPTER:-}" in
  "" | 0) WORKS_DEV_ADAPTER="" ;;
  1)
    WORKS_ADAPTER_HOME="${WORKS_ADAPTER_HOME:-$WORKS_DEV_HOME/adapter}"
    case "$WORKS_ADAPTER_HOME" in
      /*) ;;
      *)
        # 相対だと包みは起動ごとに止まり、Archon が起こし直しを繰り返す。殻で先に拒む
        echo "archon.sh: WORKS_ADAPTER_HOME は絶対パスにする（受けた値: ${WORKS_ADAPTER_HOME}）" >&2
        exit 2
        ;;
    esac
    works_dev_refuse_claude_tmp archon.sh "WORKS_ADAPTER_HOME" "$WORKS_ADAPTER_HOME"
    ;;
  *)
    echo "archon.sh: WORKS_DEV_ADAPTER は 1（包みを入れる）か空・0（入れない）。受けた値: ${WORKS_DEV_ADAPTER}" >&2
    exit 2
    ;;
esac

# 認証は本線 claude_auth.py の順で、利用者自身の物だけを拾う（どこかの口座で黙って回さない。R20 には拾った出どころの名を
# 1 行に出して応える。値は出さない）。順と案内の文の正本は guard.sh works_dev_auth_candidates・works_dev_no_auth_howto で、
# どれも無ければ 1 行の案内を出して止まる（本線の段 3「子自身の保存済み認証」は、隔離した CLAUDE_CONFIG_DIR が空なので無い）。
# WORKS_DEV_NO_AUTH=1 のときは読まない（テストや validate など、認証が要らないとき用）。
# keychain は HOME を隔離する前に読む（macOS の security はログイン keychain を
# $HOME 基準で探すので、後で読むと隔離した偽の HOME の下を探して必ず失敗する）。
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ "${WORKS_DEV_NO_AUTH:-}" != "1" ]; then
  _candidates="$(works_dev_auth_candidates)"
  _ifs=$IFS
  IFS='
'
  for _c in $_candidates; do
    case $_c in
      "item "*)
        CLAUDE_CODE_OAUTH_TOKEN="$(security find-generic-password -s "${_c#item }" -w)"
        # 項目が空の値を返したら、空のトークンを渡さずに止まる（項目名は出すが、値は出さない）
        if [ -z "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
          echo "archon.sh: $(works_dev_no_auth_howto)（keychain の項目 ${_c#item } が空）" >&2
          exit 2
        fi
        break
        ;;
      "claude "*)
        _svc=${_c#claude }
        # 値は Claude Code の JSON（claudeAiOauth.accessToken）か、トークンそのもの。sk-ant-oat01- で始まらない物は渡さない
        CLAUDE_CODE_OAUTH_TOKEN="$(security find-generic-password -s "$_svc" -w 2>/dev/null | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
try:
    tok = ((json.loads(raw) or {}).get("claudeAiOauth") or {}).get("accessToken") or ""
except (ValueError, AttributeError):
    tok = raw
if isinstance(tok, str) and tok.startswith("sk-ant-oat01-"):
    print(tok)
' || true)"
        if [ -n "$CLAUDE_CODE_OAUTH_TOKEN" ]; then
          echo "archon.sh: 認証は Claude Code の keychain の項目 ${_svc} から拾った（値は出さない）" >&2
          break
        fi
        ;;
    esac
  done
  IFS=$_ifs
  if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "archon.sh: $(works_dev_no_auth_howto)（Claude Code の keychain の項目 $(works_dev_claude_keychain_services | tr '\n' ' ')にも無い）" >&2
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

# 借りる物（superpowers のスキル・coldwrite・pr-review-toolkit）は、利用者が Claude Code に入れたプラグインから取る（下の toolset.py）。
# その一覧（plugins/installed_plugins.json）を読む利用者の設定の置き場を、隔離の前に決めておく（隔離の後の CLAUDE_CONFIG_DIR は
# 選んだ物だけの設定で、利用者の物ではない）。相対の値は頭の works_dev_abs_claude_config が絶対に直してある。殻の中から入れ子で
# 打って隔離の置き場そのものになっていれば、toolset.py が名指しで止める
USER_CLAUDE_CONFIG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

# mise の信頼はパスに結び付き（利用者の家の信頼の控え）、run の worktree は隔離した家の下の新しいパスなので、対象の根で信頼した
# 設定も run の中のテストでは信頼されず、道具の失敗が偽の赤になる。対象（cwd）の根を利用者の mise が信頼済みの時だけ、それを隔離の
# 前に読み（mise trust --show の `<dir>: trusted` の行）、下で run の worktree の置き場を mise の公式の設定 MISE_TRUSTED_CONFIG_PATHS
# に足す。AI の節（とその中の最後のテスト）を回す認証の道だけ
MISE_TRUST_RUNS=""
if [ "${WORKS_DEV_NO_AUTH:-}" != "1" ] && command -v mise >/dev/null 2>&1 &&
  mise trust --show </dev/null 2>/dev/null | grep -Fqx "$(pwd -P): trusted"; then
  MISE_TRUST_RUNS=1
fi

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

# Archon は run の worktree を $ARCHON_HOME/workspaces の下に切る。mise はこのパスの下の設定を問わずに信頼するので、足すのは
# 利用者が対象の根を信頼した時だけ（前の値は残す。実体のパスで渡す）
if [ -n "$MISE_TRUST_RUNS" ]; then
  mkdir -p "$ARCHON_HOME/workspaces"
  MISE_TRUSTED_CONFIG_PATHS="${MISE_TRUSTED_CONFIG_PATHS:+$MISE_TRUSTED_CONFIG_PATHS:}$(works_dev_real "$ARCHON_HOME/workspaces")"
  export MISE_TRUSTED_CONFIG_PATHS
fi

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
  # 本物の claude: WORKS_REAL_CLAUDE、CLAUDE_BIN_PATH（包み自身を差していれば使わない）、PATH の順（関数・別名は飛ばす）。
  # 隔離した設定にプラグインを入れる（下の toolset.py）のにも、包みが起こすのにも使う
  REAL_CLAUDE="${WORKS_REAL_CLAUDE:-}"
  if [ -z "$REAL_CLAUDE" ] && [ -n "${CLAUDE_BIN_PATH:-}" ] &&
    [ "$(works_dev_real "$CLAUDE_BIN_PATH")" != "$WORKS_ADAPTER" ]; then
    REAL_CLAUDE="$CLAUDE_BIN_PATH"
  fi
  if [ -z "$REAL_CLAUDE" ]; then
    REAL_CLAUDE="$(command -v claude || true)"
    case "$REAL_CLAUDE" in /*) ;; *) REAL_CLAUDE="" ;; esac
  fi
  if [ -z "$REAL_CLAUDE" ]; then
    echo "archon.sh: 本物の claude（隔離した設定にプラグインを入れる・包みが起こす）が見つからない。WORKS_REAL_CLAUDE か CLAUDE_BIN_PATH に絶対パスを設定する" >&2
    exit 2
  fi
  if [ -n "$WORKS_DEV_ADAPTER" ]; then
    WORKS_REAL_CLAUDE="$REAL_CLAUDE"
    echo "    claudeBinaryPath: $WORKS_ADAPTER" >>"$ARCHON_HOME/config.yaml"
    unset CLAUDE_BIN_PATH
    export WORKS_REAL_CLAUDE WORKS_ADAPTER_HOME
  fi
fi

# 選んだ物だけの隔離した Claude の設定を組む（toolset.py。P1 計画 Task 20・裁定 P1-R8）。AI の節は全部 settingSources: [user] で
# ここを読む: 利用者が入れた superpowers の 5 つのスキルを skills/ へ写し、利用者が入れた coldwrite・pr-review-toolkit を設定の中の
# 手元の marketplace から claude の plugin の CLI で入れる。借りる物が入っていない・works が名前で頼る物が無ければ、借りる物ごとに
# 理由と入れるコマンドを出して終了コード 2 で止まる。柵が一覧の外（CLAUDE.md・rules/・agents/・ほかのプラグイン・余分な設定の鍵
# など）を見つければ、名前を出して終了コード 2 で止まる。どちらも Archon を起こさない。認証の要らない道（validate・テスト）は
# claude を起こさず、スキルだけを写す（validate も同じ置き場で探す。借りる物の確かめは同じ）
TOOLSET="$(cd "$(dirname "$0")" && pwd -P)/toolset.py"
if [ "${WORKS_DEV_NO_AUTH:-}" = "1" ]; then
  python3 "$TOOLSET" install --no-plugins --user-config "$USER_CLAUDE_CONFIG" "$CLAUDE_CONFIG_DIR"
else
  python3 "$TOOLSET" install --claude "$REAL_CLAUDE" --user-config "$USER_CLAUDE_CONFIG" "$CLAUDE_CONFIG_DIR"
fi

# run ごとの版の控え（<ARTIFACTS_DIR>/versions.json。線の start が .shared/core/versions.py で書く）へ渡す版。
# claude の --version は設定を読み書きしない（2.1.283 で確かめた）。認証の要らない道は claude を起こさない
WORKS_ARCHON_VERSION="$ARCHON_VERSION"
export WORKS_ARCHON_VERSION
if [ "${WORKS_DEV_NO_AUTH:-}" != "1" ]; then
  WORKS_CLAUDE_VERSION="$("$REAL_CLAUDE" --version 2>/dev/null | head -n 1)" || WORKS_CLAUDE_VERSION=""
  export WORKS_CLAUDE_VERSION
fi

ARCHON_TELEMETRY_DISABLED=1
DO_NOT_TRACK=1
export ARCHON_TELEMETRY_DISABLED DO_NOT_TRACK

exec "$BIN_PATH" "$@"
