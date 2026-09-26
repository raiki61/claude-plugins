# works/dev/guard.sh — archon.sh・mktarget.sh・real-run.sh・dogfood.sh が . で読む（単独では走らせない）
#
# Claude Code のサンドボックスは、自分の一時フォルダ（/private/tmp/claude-<uid>/。/tmp は macOS では /private/tmp への
# symlink）への書き込みを Bash に許す。そこに開発の家（WORKS_DEV_HOME）・対象・origin を置くと、サンドボックスの中の
# 役の Bash がそれらを書き換えられる。pack にはこの穴を塞げないので、その下に解ける場所を使わせない（設計書 7 節）。

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
