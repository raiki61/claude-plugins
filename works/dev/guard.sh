# shellcheck shell=sh
# works/dev/guard.sh — archon.sh・mktarget.sh・real-run.sh・dogfood.sh・use.sh が . で読む（単独では走らせない）
#
# Claude Code のサンドボックスは、自分の一時フォルダ（/private/tmp/claude-<uid>/。/tmp は macOS では /private/tmp への
# symlink）への書き込みを Bash に許す。そこに開発の家（WORKS_DEV_HOME）・対象・origin を置くと、サンドボックスの中の
# 役の Bash がそれらを書き換えられる。pack にはこの穴を塞げないので、その下に解ける場所を使わせない（設計書 7 節）。

# 全体の模型の既定。入口の殻は埋めず、埋めるのは archon.sh だけ（埋めると明示と既定が見分けられない）。
# 環境から上書きさせない。続き（answer・show の行）は start の時に解いた既定を別の名 WORKS_MODEL_PINNED で渡し
# （use.sh load_ledger・lib.sh works_dev_go だけが置く。入口の殻 use.sh・dogfood.sh・real-run.sh は起動の時に外し、
# 利用者の殻に残った値を受けない）、archon.sh が読んで外す（run の途中で既定を解き直さない）
WORKS_DEV_MODEL_DEFAULT=opus

# works_dev_model_value / works_dev_model_from: 全体の模型の値と出どころ。空でなければ明示、次に start の時の既定
# （WORKS_MODEL_PINNED）、無ければ今の既定
works_dev_model_value() {
  echo "${WORKS_DEV_MODEL:-${WORKS_MODEL_PINNED:-$WORKS_DEV_MODEL_DEFAULT}}"
}
works_dev_model_from() {
  if [ -n "${WORKS_DEV_MODEL:-}" ]; then
    echo "env WORKS_DEV_MODEL"
  elif [ -n "${WORKS_MODEL_PINNED:-}" ]; then
    echo "start の時の既定（WORKS_MODEL_PINNED）"
  else
    echo "既定（WORKS_DEV_MODEL_DEFAULT）"
  fi
}

# works_dev_real <path>: symlink を辿った絶対パス。まだ無い部分は、在る一番近い祖先を pwd -P で解いた後ろに足す。
# 先の無い symlink（mkdir や git init がその先を作る）も readlink で先を辿る（辿るのは 40 回まで。輪の symlink で回り続けない）
works_dev_real() {
  _p=$1
  _rest=""
  _hops=0
  case "$_p" in /*) ;; *) _p="$(pwd -P)/$_p" ;; esac
  while [ ! -d "$_p" ]; do
    if [ -L "$_p" ] && [ "$_hops" -lt 40 ]; then
      _hops=$((_hops + 1))
      _to=$(readlink "$_p")
      case "$_to" in /*) _p=$_to ;; *) _p="$(dirname "$_p")/$_to" ;; esac
      continue
    fi
    _rest="/$(basename "$_p")${_rest}"
    _p=$(dirname "$_p")
  done
  printf '%s%s\n' "$(cd "$_p" && pwd -P)" "$_rest"
}

# works_dev_abs_claude_config: 相対の CLAUDE_CONFIG_DIR（借りる物を探す利用者の設定の置き場）を今の cwd から絶対パスに直して
# export する。殻は対象へ cd してから archon.sh を起こすので、cd の前に呼ぶ（後だと対象から解かれる。toolset.py は絶対だけを受ける）
works_dev_abs_claude_config() {
  case "${CLAUDE_CONFIG_DIR:-}" in
    "" | /*) ;;
    *) CLAUDE_CONFIG_DIR="$(pwd -P)/$CLAUDE_CONFIG_DIR"; export CLAUDE_CONFIG_DIR ;;
  esac
}

# works_dev_claude_keychain_services: Claude Code 自身が macOS の keychain に認証を置く項目の名の候補（先に試す物から 1 行ずつ）。
# CLAUDE_CONFIG_DIR を設定した Claude Code は `Claude Code-credentials-<その値（NFC）の sha256 の頭 8 桁>` に置き、無ければ
# `Claude Code-credentials`（本線 claude_auth.py の段 2 と同じく CLAUDE_CONFIG_DIR から導く。名の付け方は Claude Code の版で
# 変わりうるので、どちらにも無ければ認証が無いと言って止まる）。値は archon.sh だけが読む
works_dev_claude_keychain_services() {
  if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
    printf 'Claude Code-credentials-%s\n' "$(CFG="$CLAUDE_CONFIG_DIR" python3 -c 'import hashlib, os, unicodedata
print(hashlib.sha256(unicodedata.normalize("NFC", os.environ["CFG"]).encode("utf-8")).hexdigest()[:8])')"
  fi
  echo "Claude Code-credentials"
}

# 認証の順の正本（archon.sh は値を読み、use.sh は在るかだけを見る。片方だけ変えると check が通るのに起動が落ちるので 1 か所に置く）。
# 本線 claude_auth.py の順で、効く段の候補だけを先に試す物から 1 行ずつ出す: CLAUDE_CODE_OAUTH_TOKEN が在れば `env`、
# 無くて WORKS_KEYCHAIN_ITEM が在れば `item <項目名>`（名を指したのに空なら次へ進まず止まる）、どちらも無ければ macOS でだけ
# `claude <項目名>`（works_dev_claude_keychain_services の順）。値は出さない
works_dev_auth_candidates() {
  if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "env CLAUDE_CODE_OAUTH_TOKEN"
  elif [ -n "${WORKS_KEYCHAIN_ITEM:-}" ]; then
    echo "item ${WORKS_KEYCHAIN_ITEM}"
  elif [ "$(uname -s)" = Darwin ]; then
    works_dev_claude_keychain_services | sed 's/^/claude /'
  fi
}
works_dev_no_auth_howto() {
  echo "認証が無い。claude にログインするか、CLAUDE_CODE_OAUTH_TOKEN（例: claude setup-token で作る）か、トークンを入れた keychain の項目名 WORKS_KEYCHAIN_ITEM を設定する"
}

# works_dev_refuse_claude_tmp <呼び手> <何か> <path>: path が Claude Code の一時フォルダの下に解けるなら、
# 1 行の理由を出して終了コード 2 で止める
works_dev_refuse_claude_tmp() {
  _real=$(works_dev_real "$3")
  case "$_real" in
    /private/tmp/claude-* | /tmp/claude-*)
      echo "${1}: ${2} が Claude Code の一時フォルダの下にある（${_real}。/private/tmp/claude-* はサンドボックスの Bash が書ける）。別の場所を使う（WORKS_DEV_HOME の既定は \$TMPDIR/works-dev）" >&2
      exit 2
      ;;
  esac
}
