#!/bin/sh
# works/dev/archon.sh <archon の引数…>
#
# 固定した版の Archon の実行ファイルを WORKS_DEV_HOME の下にキャッシュし、sha256 を
# 確かめてから、HOME・ARCHON_HOME・CLAUDE_CONFIG_DIR・XDG_* を全部そこへ向けて隔離した
# 状態で実行ファイルを exec する。works/ のパックには入らない（77MB 級のため）。
# 認証を使う実行では、隔離した Archon の設定に模型（WORKS_DEV_MODEL。既定は guard.sh の WORKS_DEV_MODEL_DEFAULT）を毎回書く。
# YAML は AI の段の全部に model: を書くので、この設定の値は段に効かない。明示した WORKS_DEV_MODEL は、包み（WORKS_DEV_ADAPTER=1）が
# 前付けの無い役の段（.shared/core/stage-models.json）をその模型で起こす（adapter.py の頭の 19）。
set -eu

ARCHON_VERSION="v0.11.1"
ARCHON_SHA256="b9338474fd3151d5d5402d76ae278105e65835f2e3506a93f0e5e4a378d10ede"
ARCHON_BIN_NAME="archon-darwin-arm64"

WORKS_ADAPTER="$(cd "$(dirname "$0")/.." && pwd -P)/.shared/core/claude-adapter"

# 開発の家と対象（cwd）が Claude Code の一時フォルダの下なら、認証も実行ファイルも触らずに止まる（guard.sh）
. "$(cd "$(dirname "$0")" && pwd -P)/guard.sh"
# 開発の家の既定と本物の claude の解決は launch.py env が持つ（何も作らず認証も読まない）。認証の要らない道では claude を解かない
if [ "${WORKS_DEV_NO_AUTH:-}" != "1" ]; then
  works_dev_launch_env archon.sh --claude --adapter "$WORKS_ADAPTER"
else
  works_dev_launch_env archon.sh
fi
works_dev_abs_claude_config
works_dev_refuse_claude_tmp archon.sh "WORKS_DEV_HOME" "$WORKS_DEV_HOME"
works_dev_refuse_claude_tmp archon.sh "対象（cwd）" "$(pwd -P)"

# Claude の包み（works/.shared/core/claude-adapter。README の「Claude の包み」）。WORKS_DEV_ADAPTER=1 で入れる（既定は入れない）。
# 入れる時は、認証を使う実行で隔離した Archon の設定に claudeBinaryPath（包み）を書き、本物の claude を WORKS_REAL_CLAUDE で
# 包みに渡し、env の CLAUDE_BIN_PATH（Archon では設定より強い）を外す。包みの家（会話の id・読んだ記録・起動の記録）は
# WORKS_ADAPTER_HOME（既定は $WORKS_DEV_HOME/adapter）。役の sandbox の Bash から書けない所に置く（guard.sh）。
# 包みの実パス WORKS_ADAPTER は頭で決める（launch.py env が CLAUDE_BIN_PATH の包み自身を本物から除くのに使う）。
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

# 認証は起こし役 .shared/core/auth_launch.py が持つ（WORKS_KEYCHAIN_ITEM → 本流 claude_auth.py の写しの auth_env → Claude Code
# 自身の keychain の項目。利用者自身の物だけを拾い、R20 には拾った出どころの名を 1 行に出して応える）。トークンは殻の変数・
# 標準出力を通さない: ここでは実行ファイルに触る前に読んで捨てて名だけを受け（無ければ起こし役の 1 行の案内で止まる）、
# 最後の exec で起こし役がもう一度読んで同じプロセスから Archon を起こす。use.sh が確かめて WORKS_AUTH_FROM を渡した時は
# ここの確かめを飛ばす（exec で必ず読み直すので、値の無い起動は止まる）。WORKS_DEV_NO_AUTH=1 のときは読まない。
# keychain は隔離の前の利用者の HOME で読む（macOS の security はログイン keychain を $HOME 基準で探す）ので、その HOME と
# 利用者の CLAUDE_CONFIG_DIR を隔離の前に取っておく
AUTH_LAUNCH="$(cd "$(dirname "$0")/.." && pwd -P)/.shared/core/auth_launch.py"
USER_HOME="$HOME"
USER_CONFIG_RAW="${CLAUDE_CONFIG_DIR:-}"
if [ "${WORKS_DEV_NO_AUTH:-}" != "1" ] && [ -z "${WORKS_AUTH_FROM:-}" ]; then
  _auth_from="$(python3 -I "$AUTH_LAUNCH" check --for archon.sh --user-home "$USER_HOME" --user-config "$USER_CONFIG_RAW")" || exit $?
  echo "archon.sh: 認証は ${_auth_from} から拾う（値は出さない）" >&2
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

# 借りる物のうち coldwrite・pr-review-toolkit は、利用者が Claude Code に入れたプラグインから取る（下の toolset.py）。superpowers の
# スキルと部品は、works に写した固定の版（.shared/borrow/superpowers/<版>/）から入れ、利用者が入れた版は run に使わない（開発の
# 再開の確かめが比べるだけ）。その一覧（plugins/installed_plugins.json）を読む利用者の設定の置き場を、隔離の前に決めておく（隔離の後の CLAUDE_CONFIG_DIR は
# 選んだ物だけの設定で、利用者の物ではない）。相対の値は頭の works_dev_abs_claude_config が絶対に直してある。殻の中から入れ子で
# 打って隔離の置き場そのものになっていれば、toolset.py が名指しで止める
USER_CLAUDE_CONFIG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

# 機械全体の重いテストの枠の台本（WORKS_TESTSLOT）の既定は、利用者の家のキャッシュから引く式（正本は .shared/core/slotwrap.sh）。
# 下で HOME・XDG を隔離すると式が利用者の家を指さないので、名指しが無ければ隔離の前に引いて名指しにする（run の中の試験も同じ
# 台本を通る）。台本が無ければ空（run の中の試験は黙って枠を取らない）。利用者の名指し（空も）はそのまま
if [ -z "${WORKS_TESTSLOT+x}" ]; then
  WORKS_TESTSLOT="$(bash "$(cd "$(dirname "$0")/.." && pwd -P)/.shared/core/slotwrap.sh" --default)"
  export WORKS_TESTSLOT
fi

# mise の信頼はパスに結び付き（利用者の家の信頼の控え）、run の worktree は隔離した家の下の新しいパスなので、対象の根で信頼した
# 設定も run の中のテストでは信頼されず、道具の失敗が偽の赤になる。対象（cwd）の根を利用者の mise が信頼済みの時だけ、それを隔離の
# 前に読み（mise trust --show の `<dir>: trusted` の行）、下で run の worktree の置き場を mise の公式の設定 MISE_TRUSTED_CONFIG_PATHS
# に足す。AI の節（とその中の最後のテスト）を回す認証の道だけ
MISE_TRUST_RUNS=""
if [ "${WORKS_DEV_NO_AUTH:-}" != "1" ] && command -v mise >/dev/null 2>&1 &&
  mise trust --show </dev/null 2>/dev/null | grep -Fqx "$(pwd -P): trusted"; then
  MISE_TRUST_RUNS=1
fi

# run の中の gh は利用者の gh のログインを継ぐ（持ち主 2026-10-08。本流の review-graph は利用者の環境のまま gh を打つ）。隔離した
# HOME・XDG の gh は利用者の設定（hosts.yml）も macOS の keychain のトークン（keychain は HOME から探す）も見えず、並行 PR の確かめが
# 毎回 gh の失敗で人待ちになり、1 周の run が round_limit で終わった（実の利用者の run 97fd532f）。隔離の前の HOME と gh の設定の
# 置き場で本物の gh を起こすだけの口（<包みの家か開発の家>/host-gh/<中身の印>/gh。パスだけを持ち、トークンは写さない・出さない。GH_TOKEN も立てない）を
# dev/hostgh.py が書き、下で PATH の頭に置く。AI の役は包みが gh を丸ごと拒み、読むだけの口だけを通す（adapter.py の 5）。
# 認証を使う実行だけ（mise の信頼と同じ）。利用者の gh がログインしていなければ gh の言葉のまま（run の中は今どおり人待ち）
HOST_GH=""
if [ "${WORKS_DEV_NO_AUTH:-}" != "1" ]; then
  # 包みを通す run では包みの家（切符が役の書き込みから守る所）の下に置く（役が口を書き換えて sandbox の外で走らせない）
  HOST_GH="$(python3 -I "$(cd "$(dirname "$0")" && pwd -P)/hostgh.py" write --dir "${WORKS_ADAPTER_HOME:-$WORKS_DEV_HOME}/host-gh" --path "$PATH" \
    --home "$HOME" --gh-config-dir "${GH_CONFIG_DIR:-}" --xdg-config-home "${XDG_CONFIG_HOME:-}")"
fi

# HOME・ARCHON_HOME・Claude の設定・XDG_* を全部 WORKS_DEV_HOME の下へ隔離する
# （keychain は起こし役が USER_HOME で読む）。
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
if [ -n "$HOST_GH" ]; then
  PATH="$(dirname "$HOST_GH")${PATH:+:$PATH}"
  export PATH
fi

# Archon は run の worktree を $ARCHON_HOME/workspaces の下に切る。mise はこのパスの下の設定を問わずに信頼するので、足すのは
# 利用者が対象の根を信頼した時だけ（前の値は残す。実体のパスで渡す）
if [ -n "$MISE_TRUST_RUNS" ]; then
  mkdir -p "$ARCHON_HOME/workspaces"
  MISE_TRUSTED_CONFIG_PATHS="${MISE_TRUSTED_CONFIG_PATHS:+$MISE_TRUSTED_CONFIG_PATHS:}$(works_dev_real "$ARCHON_HOME/workspaces")"
  export MISE_TRUSTED_CONFIG_PATHS
fi

# 認証を使う（AI を呼びうる）実行は毎回、隔離した Archon の全体設定に既定の模型を書き、run の題を作る
# 模型も同じにする（TITLE_GENERATION_MODEL。設定済みならそのまま）。書かないと Claude CLI の既定の模型で
# 黙って回る。模型は WORKS_DEV_MODEL（空か未設定なら guard.sh の WORKS_DEV_MODEL_DEFAULT。既定を埋めるのはここだけ）で、
# 明示か既定かを WORKS_MODEL_FROM に残して下へ渡す。works の YAML は AI の段の全部に model: を書く（持ち主 2026-10-06。
# 前付けを持つ役の段は前付けの値、ほかは表 .shared/core/stage-models.json の値）。Archon は段の値をこの設定より先に使うので、
# ここで書く値が効くのは run の題（TITLE_GENERATION_MODEL）だけ。明示した値（WORKS_DEV_MODEL が空でない）は、包みが
# 前付けの無い役の段をその模型で起こす（adapter.py の頭の 19。effort は段の値のまま）。包みの無い run には効かないので 1 行で言う。
# 解いた値は WORKS_DEV_MODEL に書き戻さず（書き戻すと Archon の下で起こす殻と包みに既定が明示として届く）、別の名
# WORKS_MODEL_RESOLVED で渡す（run の版の控え versions.json の model が読む）。
# 認証の要らない道（WORKS_DEV_NO_AUTH=1。テスト・validate・workflow test）は変えない（書かない・模型も要らない）。
WORKS_MODEL_FROM="$(works_dev_model_from)"
WORKS_MODEL_RESOLVED="$(works_dev_model_value)"
# start の時の既定の釘は、この起動の模型を解くのにだけ使う（Archon の下の殻・入れ子の run に既定として継がせない）
unset WORKS_MODEL_PINNED
if [ "${WORKS_DEV_NO_AUTH:-}" != "1" ]; then
  export WORKS_MODEL_FROM WORKS_MODEL_RESOLVED
  cat >"$ARCHON_HOME/config.yaml" <<EOF
# works/dev/archon.sh が認証を使う実行のたびに書く、隔離した開発用の Archon の全体設定
assistants:
  claude:
    model: $WORKS_MODEL_RESOLVED
EOF
  TITLE_GENERATION_MODEL="${TITLE_GENERATION_MODEL:-$WORKS_MODEL_RESOLVED}"
  export TITLE_GENERATION_MODEL
  if [ -n "${WORKS_DEV_MODEL:-}" ] && [ -z "$WORKS_DEV_ADAPTER" ]; then
    echo "archon.sh: WORKS_DEV_MODEL=${WORKS_DEV_MODEL} は包みを通した run（WORKS_DEV_ADAPTER=1）でだけ前付けの無い役の段に効く。包み無しのこの起動では、段は YAML の model: で走る（効くのは run の題だけ）" >&2
  fi
  # 本物の claude（頭の launch.py env が WORKS_REAL_CLAUDE、CLAUDE_BIN_PATH（包み自身を差していれば使わない）、PATH の順で解いた）。
  # 隔離した設定にプラグインを入れる（下の toolset.py）のにも、包みが起こすのにも使う
  REAL_CLAUDE="$WORKS_LAUNCH_CLAUDE"
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
# ここを読む: works に写した固定の版の superpowers の 5 つのスキルを skills/ へ、部品を works-parts/superpowers/ へ写し、利用者が
# 入れた coldwrite・pr-review-toolkit を設定の中の手元の marketplace から claude の plugin の CLI で入れる。superpowers の写しが
# borrow.json の pin の sha256 と合わない・借りる物が入っていない・works が名前で頼る物が無ければ、借りる物ごとに理由（と入れる
# コマンド）を出して終了コード 2 で止まる。柵が一覧の外（CLAUDE.md・rules/・agents/・ほかのプラグイン・余分な設定の鍵
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

exec python3 -I "$AUTH_LAUNCH" exec --for archon.sh --user-home "$USER_HOME" --user-config "$USER_CONFIG_RAW" -- "$BIN_PATH" "$@"
