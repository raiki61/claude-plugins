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
