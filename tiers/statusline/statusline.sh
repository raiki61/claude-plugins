#!/usr/bin/env bash
# Claude Code のステータスライン。標準入力の JSON を statusline.jq に描かせたうえで、
# 同じ JSON から herdr のサイドバー用トークンも投げる。
#
# herdr 側にはコンテキスト量も課金額も知る手段が無く（サイドバーの組み込みトークンは
# 状態・ワークスペース・タブ・エージェント種別・端末タイトルだけ）、pane metadata の
# カスタムトークンに外から押し込むしか経路が無い。値を持っているのは Claude Code の
# ステータスライン入力だけなので、描画のついでにここから送る。
#
# 描画は無条件に先に済ませる。herdr への送信が失敗してもステータスラインは壊れない。
#
# tiers プラグインの物（元は持ち主の手元の ~/.claude/statusline.sh。2026-10-19 に移した）。settings.json の statusLine は
# tiers-statusline setup が書き、このファイルを ${CLAUDE_PLUGIN_DATA}/current（プラグインの SessionStart のフックが今の版へ張り替える
# リンク）の下で指す。使い方は tiers の README の「Status line」。
set -u

# **jq を PATH で引かない。**PATH に mise の shim（~/.local/share/mise/shims/jq）が
# 先に来る環境があり、その shim は「今居るディレクトリの mise.toml が信頼されていない」
# だけで jq を実行せず非ゼロで死ぬ。サイドバーの表示が、たまたま居る作業場の信頼状態に
# 左右されてはいけない。
# 2026-09-28 に実際に起きた: work8 / work9（mise trust 未実施の worktree）で jq が死に、
# 下の metrics が `|| exit 0` で黙って終わり、statusline が送るトークン（lim・mdl・br・
# ref・prt）が 5 分の TTL で全部消えた。act だけはフックが別 TTL(60 分)で送るので残り、
# 「一部だけ出ない」という分かりにくい形になった。
if [ -x /usr/bin/jq ]; then
  jq() { /usr/bin/jq "$@"; }
fi

# 失敗を黙って捨てない。上の不具合が表に出なかったのは 2>/dev/null と || exit 0 の
# 組み合わせで、4 日ぶんの欠測がどこにも記録されていなかったため。
err_log="${TMPDIR:-/tmp}/statusline-errors.log"
log_fail() { printf '%s %s %s\n' "$(date '+%m-%dT%H:%M:%S')" "${HERDR_PANE_ID:-?}" "$*" >> "$err_log"; }

json=$(cat)
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

printf '%s' "$json" | jq -rf "$here/statusline.jq"

# 終わりのあるバックグラウンド（run_in_background の Bash と Monitor〔印 herdr:ignore の付いた終わらない見張りは
# 数えない〕と、バックグラウンドで起動したサブエージェント）が残っている間だけ、印「⧖ バックグラウンド作業中 N 本」を
# 2 行目に出す。herdr は判定ルールの手元の上書き（~/.config/herdr/agent-detection/claude.toml。足す規則は claude-rule.toml）で
# この印を作業中と見分ける。数え方は bg-count.sh の 1 か所。
# 上書きは herdr が配ったルールの丸ごとの置き換えなので、上書きが無いか、tiers の作った上書き（1 行目の印で見分ける。中身は
# tiers_statusline.py の MARK）より配られたルールか足す規則の方が新しければ、tiers-statusline refresh を裏で起動して作り直す。
# 配られたルールがまだ無いときと、手で書いた上書きは、30 秒ごとに起動しても変わらないので起動しない。
if [ "${HERDR_ENV:-}" = 1 ]; then
  bg_n=$("$here/bg-count.sh" "$(printf '%s' "$json" | jq -r '.transcript_path // empty' 2>/dev/null)" 2>/dev/null || echo 0)
  [ "${bg_n:-0}" -gt 0 ] 2>/dev/null && printf '⧖ バックグラウンド作業中 %s 本\n' "$bg_n"
  hd_over="${XDG_CONFIG_HOME:-$HOME/.config}/herdr/agent-detection/claude.toml"
  hd_remote="${XDG_STATE_HOME:-$HOME/.local/state}/herdr/agent-detection/remote/claude.toml"
  if [ -e "$hd_remote" ] && { [ ! -e "$hd_over" ] || { head -n 1 "$hd_over" | grep -qF '# tiers-statusline が作った herdr の判定ルールの上書き。' \
       && { [ "$hd_remote" -nt "$hd_over" ] || [ "$here/claude-rule.toml" -nt "$hd_over" ]; }; }; }; then
    "$here/../bin/tiers-statusline" refresh >/dev/null 2>>"$err_log" &
  fi
fi

# アカウント単位の使用率の控え。5h / 7d の枠はアカウントに付くので、同じ
# CLAUDE_CONFIG_DIR のペインが何枚あっても値は 1 つ。
# 読むのは ~/.config/herdr/limits.sh（herdr のタブバー右端で全アカウントを 1 行に並べる）。
# herdr の外でも書く——アカウントの残量は、どこで使ったかに関係なく減るため。
# API キー認証（ollama など）には rate_limits が来ないので書かない。
#
# 上書きせず、枠ごとに控えと突き合わせて「新しい方」だけを取り込む。rate_limits はその
# セッションが最後に受けた API 応答の値で、放置したセッションは古い値を 30 秒ごとに
# 渡し続けるため。2026-09-24 に main で実際に起きた: 放置ペイン 2 枚が 7d 33% と 57% を
# 交互に書き、実際（probe のヘッダ）は 97%。しかも Claude Code は切り替え時刻を過ぎた
# 5h 枠を rate_limits から丸ごと落として渡してくる（両ペインとも seven_day しか無かった）ので、
# 「切り替え時刻を過ぎた枠を含む値は書かない」という前の版の弾き方をすり抜け、5h が
# 消えたまま居座った。updated_at も 30 秒ごとに今へ更新されるので limits.sh の取り直しも
# 走らなかった。
# 新しい方の決め方: 切り替え時刻が後の枠が新しい。同じ枠なら高い方を採る。欠けた枠は
# 控えを残す。何も変わらなければ書かない——updated_at は「値が最後に動いた時刻」になり、
# 動かないまま PROBE_STALE_MIN を過ぎると limits.sh が取り直す（放置ペインしか無い
# アカウントの値も、これで最長 60 分で本物に戻る）。
#
# **「同じ枠なら使用率は下がらない」は 7d には成り立たない（2026-09-27 に判明）。**
# 7d は移動窓なので、古い使用が窓から抜けると resets_at が変わらないまま使用率が下がる。
# 「高い方が勝つ」だけだとピークを握ったまま二度と下がらない——実際 p2 が 7d 99% を
# 握り続け、probe で測ると 30% だった。読み取り時刻は statusline 入力に無い
# （rate_limits は used_percentage と resets_at だけ）ので、高い方を採る以外に
# 放置ペインの古い値を弾く手が無く、規則そのものは残す。下がる側は probe に任せる。
# そのため **updated_at は枠ごとに持つ**。ファイル単位だと 5h が動くだけで全体が
# 「新しい」と読まれ、凍った 7d の取り直しが永久に走らなかった（これが p2 の原因）。
limits_dir="${XDG_CACHE_HOME:-$HOME/.cache}/claude-limits"
limits_name=$(basename "${CLAUDE_CONFIG_DIR:-$HOME/.claude}")
limits_name=${limits_name#.claude-}
[ "$limits_name" = .claude ] && limits_name=main
limits_old=$(jq -c . "$limits_dir/$limits_name.json" 2>/dev/null)
if snap=$(printf '%s' "$json" | jq -ce --argjson old "${limits_old:-null}" '
      def newer(o; n):
        if n == null then o
        elif o == null or (o.resets_at | type) != "number" then n
        elif (n.resets_at | type) != "number" then o
        elif n.resets_at > o.resets_at then n
        elif n.resets_at == o.resets_at and n.used_percentage > o.used_percentage then n
        else o end;
      # 採った値が前と違うときだけ、その枠の時刻を今にする。同じなら前の時刻を残す
      # ——limits.sh はこの時刻で枠ごとの古さを測る。
      def stamped(o; n):
        newer(o; n) as $w
        | if $w == null then null
          elif o == null or $w.resets_at != o.resets_at or $w.used_percentage != o.used_percentage
            then $w + {updated_at: now}
          else $w end;
      # **7d は大きさで採らない。枠が進んだときと、控えが無いときだけ書く。**
      # 5h は枠の中で単調に増えるので「高い方が新しい」が成り立つが、7d は移動窓で
      # 古い使用が抜けると下がるため成り立たない。放置ペインは古い＝高い 7d を持っており、
      # 大きさで採ると probe が測った今の値を秒単位で潰す（2026-09-27 に実測: probe が
      # 33% を書いた直後に放置ペインが 62% で上書きし、2 倍の値が行き来していた）。
      # 7d を書くのは limits.sh の probe に任せる——読み取り時刻を持つのは probe だけ。
      def keep7d(o; n):
        if o == null then (if n == null then null else n + {updated_at: now} end)
        elif n != null and (n.resets_at | type) == "number"
             and (o.resets_at | type) == "number" and n.resets_at > o.resets_at
          then n + {updated_at: now}
        else o end;
      # 控えのほかの項目（works-dispatch の limits.py が書く unknown など）は残す
      select(.rate_limits.five_hour or .rate_limits.seven_day)
      | ($old // {}) as $o
      | { five_hour: stamped($o.five_hour; .rate_limits.five_hour),
          seven_day: keep7d($o.seven_day; .rate_limits.seven_day) } as $n
      | select($n != {five_hour: $o.five_hour, seven_day: $o.seven_day})
      | $o + $n + {updated_at: now}' 2>/dev/null); then
  mkdir -p "$limits_dir" 2>/dev/null \
    && printf '%s\n' "$snap" > "$limits_dir/$limits_name.json.$$" \
    && mv -f "$limits_dir/$limits_name.json.$$" "$limits_dir/$limits_name.json"
fi

[ "${HERDR_ENV:-}" = 1 ] && [ -n "${HERDR_PANE_ID:-}" ] || exit 0
command -v herdr >/dev/null 2>&1 || exit 0

# 1 行目に赤の引き金、2 行目に使用率の計器、3 行目にモデル/effort。
#
# 計器（$lim / $limhot）は ctx・5h・7d を 1 本に詰める。herdr は隣接トークンの間に
# " · " を自分で入れるので、3 つに割ると区切りだけで 6〜8 桁——サイドバー本文の
# 予算の 2 割弱——が消える。同じ色で塗る値は 1 トークンに詰めて区切りを買い戻す。
#
# 空白の幅で括りを表す: 塊の中（ラベルと数字の間）は 1 空白、塊の境は 2 空白以上。
# 桁を揃える詰め物は padr で塊の右端へ出し、境の空白に溶かす。前の版はこれが逆で、
# 詰め物を塊の中（"ctx  35%"）に入れたため境（"35% 5h"）より広くなり、"35% 5h" が
# 1 語に、"ctx  35" が 2 語に見えていた。実物を見た人の「なんか文字が変な感じ。
# 重なってるというか」はこの近接の逆転と一致する。
# 左詰めにすると数字の右端は揃わなくなるが、塊の開始桁は値によらず固定される
# （ctx=1・5h=11・7d=20・残り時間=29 桁目）。揃えて嬉しい操作は「80 を越えたか」
# だけで、それは下の記号と赤で取れているので数字の右端は買わない。
#
# 記号は 80% 以上なら "%" を "!" に置き換える。0 桁で「5h と 7d のどちらが枯れたか」
# が読める。行頭に "! " を置く前の版では逼迫行だけ本文が 2 桁右へずれ、いちばん
# 比べたい行が縦揃えから外れていた（実測時点で 8 ペイン中 5 ペインが逼迫）。
# ctx に記号は出さない——ctx を赤の引き金に混ぜない規則をそのまま形にしている。
#
# 残り時間は 5h / 7d の高い方が 80% 以上のときだけ、その枠の分を 1 つだけ行末に出す
# （同点なら 7d。枠が長い方が縛りが強い）。80 未満の枠の復帰時刻は読む用事が無い。
# 行末なのは、可変長のフィールドを 5h と 7d の間に挟むと 7d の開始桁が行ごとに動くため。
# 端末のステータスバーには両方の残り時間が常時出るので、詳細はそちらで見る。
metrics=$(printf '%s' "$json" | jq -r '
  def padr(n): tostring | . + ((" " * (n - length)) // "");
  def mark(p): if p >= 80 then "!" else "%" end;
  def left: floor as $sec
    | if $sec <= 0 then "0m"
      else (($sec / 86400) | floor) as $d
         | ((($sec % 86400) / 3600) | floor) as $h
         | ((($sec % 3600) / 60) | floor) as $m
         | if $d > 0 then "\($d)d\($h)h" elif $h > 0 then "\($h)h\($m)m" else "\($m)m" end
      end;

  # 欠けた値は -1 に倒して束縛しておく。// と if/then/else は必ず値を返すので、
  # ここで空になって以降の出力ごと消える事故が起きない。表示側は select で項ごと
  # 落とすので -1 は出ない。resets_at が欠けた入力（実測で存在した）で jq が落ちると、
  # metrics が空になって 3 行目のトークンが 1 本も送られなくなる。
    ( (.rate_limits.five_hour.used_percentage  // -1) | round ) as $f5
  | ( (.rate_limits.seven_day.used_percentage // -1) | round ) as $d7
  | ( ([$f5, $d7] | max) >= 80 ) as $hot
  | ( if $hot then (if $d7 >= $f5 then .rate_limits.seven_day.resets_at
                                  else .rate_limits.five_hour.resets_at end)
      else null end ) as $reset
  | ( if ($reset | type) == "number" then (($reset - now) | left | .[0:5]) else "" end ) as $eta
  |

  # 赤の引き金は 5h / 7d の高い方が 80% 以上のときだけ。ctx は混ぜない——長い会話では
  # 自動圧縮の手前で必ず 80% を越えるが、越えても人の手は要らない（勝手に圧縮されて
  # 戻る）。混ぜると一覧の大半が常時赤くなり、「今すぐ手を止めるか」の合図でなくなる。
  # 判定は記号と同じ丸めた後の値で行う。生値と混ぜると 79.6% で「記号は ! なのに
  # 赤くない」行ができる。境目 80 は statusline.jq の tint が赤へ変わる境目と同じで、
  # 端末のステータスバーとサイドバーで同じ値が違う段に見えないようにするため。
  ( if $hot then "HOT" else "OK" end ),

  # 取れない項は select で丸ごと落ちる（API キー認証には rate_limits が来ない）。
  ( [ ( .context_window        | select(.used_percentage != null) | "ctx \(.used_percentage | round)%" | padr(8) ),
      ( .rate_limits.five_hour | select(.used_percentage != null) | "5h \($f5)\(mark($f5))" | padr(7) ),
      ( .rate_limits.seven_day | select(.used_percentage != null) | "7d \($d7)\(mark($d7))" | padr(7) )
    ]
    | join("  ")
    | . + (if $eta == "" then "" else "  " + $eta end)
    | sub(" +$"; "") ),

  # 誤ったモデル・effort で走っている事故を拾うためだけの値なので、頭文字＋数字まで
  # 詰める（O5/xh = Opus 5・xhigh、末尾 * は fast mode）。effort は 2 文字にする——
  # 1 文字だと medium と max が大文字小文字の差だけになり、拾い読みで取り違える。
  ( ( .model.display_name | select(.) | sub(" *\\(.*\\)$"; "") ) as $dn
    | if $dn then
        ($dn | .[0:1]) + ([$dn | scan("[0-9]")] | join("") | .[0:2])
        + ( .effort.level
            | if . then "/" + ({low:"lo", medium:"md", high:"hi", xhigh:"xh", max:"mx"}[.] // .[0:2]) else "" end )
        + ( if .fast_mode then "*" else "" end )
      else "" end )
' 2>>"$err_log") || { log_fail "metrics の jq が失敗"; exit 0; }

hot=$(printf '%s\n' "$metrics" | sed -n 1p)
lim=$(printf '%s\n' "$metrics" | sed -n 2p)
mdl=$(printf '%s\n' "$metrics" | sed -n 3p)

# サイドバーに出すブランチ名と、ブランチに紐づく PR 番号。サイドバーのエージェントの列の組み込みトークンには
# ブランチが無い（branch と git_status は spaces 行専用）ので、コンテキスト量や
# 課金額と同じくカスタムトークンとして押し込むしか経路が無い。
#
# PR の番号とタイトルは gh が GitHub API を叩くので、ブランチ単位でキャッシュする。
# 期限切れは背景で取り直し、今回の描画は手元の値で済ませる（このスクリプトは 30 秒ごとに
# 走るので、次の描画までに間に合う）。PR が無いことも "-" として覚える。覚えないと
# PR を持たないブランチで毎回 API を叩くことになる。返す形は「番号 TAB タイトル」。
#
# タイトルの整形（前置きの除去と上限）も背景側でやる。結果は 15 分変わらないので、
# 30 秒ごとの描画でやり直す意味が無い。桁での切り詰めはしない——サイドバーでは 2 行目を
# 単独で使っており、幅に入らない分は herdr が切る。
branch_pr_info() {
  local dir=$1 branch=$2 cache val
  # 鍵は cksum（POSIX）の CRC とバイト数で作る。shasum は POSIX に無く、Debian の slim などでは perl の包みに入っていて無い。無いと鍵が空になり、
  # どのブランチも同じ控えを読んで、ほかのブランチの PR を黙って出す（2026-10-26 に python:3.14-slim で無いのを見た）。CRC は 32 ビットなので、
  # バイト数も足して、長さの違うブランチどうしは鍵がぶつからないようにする
  cache="${TMPDIR:-/tmp}/herdr-pr-$(printf '%s|%s' "$dir" "$branch" | cksum | tr ' ' -)"
  if [ ! -s "$cache" ] || [ -n "$(find "$cache" -mmin +15 2>/dev/null)" ]; then
    (
      # 打ち切りは再描画の間隔（30 秒）より短く取る。gh 自身は要求を打ち切らないので、
      # 半開きの接続（スリープ復帰・VPN 切断）を掴むと戻ってこない。上限が無いと
      # 掴んだまま次の描画がもう 1 本起動し、詰まっている間だけ背景の gh が積み上がる。
      #
      # タイトルの空白は 1 つに潰す。区切りに TAB を使うので、TAB や改行が混じると
      # 読み出し側の cut が途中で切れる。
      raw=$(cd "$dir" && ${timeout_cmd:+$timeout_cmd 20} gh pr list --head "$branch" --state open \
        --json number,title --jq '.[0] | select(.number) | "\(.number)\t\(.title | gsub("\\s+"; " "))"' 2>/dev/null)
      if [ -n "$raw" ]; then
        num=${raw%%	*}
        title=${raw#*	}
        # conventional commit の前置き（"docs(ollama): "）は落とす。どのセッションの行にも
        # 同じ語が並ぶだけで、狭い行の先頭を食う。
        case "$title" in
          [a-z]*:\ *) title=${title#*: } ;;
        esac
        # 末尾の issue 参照（"… (#1809)"）も落とす。1 行上に PR 番号が出ているので、
        # 番号が 2 つ並んでどちらが今の作業か分からなくなる（$ref がブランチ名を
        # 消しているのと同じ理由）。しかも行末は切り詰めが最初に効くところで、
        # 読みたいタイトルの末尾がこの参照に押し出される。
        case "$title" in
          *" (#"[0-9]*")") title=${title% (#*} ;;
        esac
        # metadata に送る値の上限。幅で切るのは herdr なので、ここは「どう転んでも
        # 1 行に入らない」ところに置けば足りる。2 行目の予算は 45 桁前後で、
        # 日本語なら 1 文字 2 桁なので 22 文字ほどしか入らない。
        [ ${#title} -gt 60 ] && title="${title:0:59}…"
        raw="$num	$title"
      fi
      printf '%s' "${raw:--}" > "$cache.$$" && mv -f "$cache.$$" "$cache"
    ) >/dev/null 2>&1 &
  fi
  val=$(cat "$cache" 2>/dev/null)
  [ -n "$val" ] && [ "$val" != "-" ] && printf '%s' "$val"
}

timeout_cmd=""
timeout_cmd=$(command -v timeout || command -v gtimeout || true)

# ワークスペース名と同じブランチ（work5 の worktree に居て work5 ブランチ、という既定の
# 居場所）は出さない。サイドバーに同じ文字列が 2 つ並ぶだけで、何も分からない。
# 別のブランチへ移っているときだけ名前を出す。
dir=$(printf '%s' "$json" | jq -r '.workspace.current_dir // .cwd // empty')
label=""
[ -n "${HERDR_WORKSPACE_ID:-}" ] && label=$(herdr workspace get "$HERDR_WORKSPACE_ID" 2>/dev/null \
  | jq -r '.result.workspace.label // empty')

br=""
branch_pr=""
branch_pr_title=""
if [ -n "$dir" ]; then
  if branch=$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null); then
    pr_info=$(branch_pr_info "$dir" "$branch")
    branch_pr=${pr_info%%	*}
    [ "$pr_info" != "$branch_pr" ] && branch_pr_title=${pr_info#*	}
    if [ "$branch" != "$label" ]; then
      # 種別の prefix を落として詰める。サイドバーは 1 行しか描かない。
      short=${branch#*/}
      [ ${#short} -gt 18 ] && short="${short:0:17}…"
      br="$short"
    fi
  elif sha=$(git -C "$dir" rev-parse --short HEAD 2>/dev/null); then
    # 切り離し HEAD。rev-parse --abbrev-ref だとどれも "HEAD" としか出ず
    # 見分けがつかないので、短縮 SHA を出す。PR の照合はブランチ名が要るので省く。
    br="@$sha"
  fi
fi

# 今どの PR / issue を見ているか。値を作るのはフック側（持ち主の手元の herdr-activity.sh。tiers は配らないので、無ければ
# ここは何も送らず、下のブランチから引いた PR に落ちる）で、ここは読んで送るだけ。会話記録を読んで番号を拾うのは
# フックの受け持ち（statusLine の入力にも transcript_path は来るが、30 秒ごとに会話記録を読み直さない）。それでも送信を
# ここへ寄せるのは、TTL と消去を br と揃えるため——フックから別 TTL で送ると、
# ブランチが消えて番号だけ残る行ができ、br 由来の PR 番号と見分けがつかなくなる。
# 控えた時点から別のブランチへ移っていたら、フック由来の番号は捨てる。
# Claude Code が書く pr-link は「このセッションが持つ PR」として貼り付き続けるので
# （実測: 会話が別の話題へ移っても同じ番号が書かれ直す）、これが無いと用が済んだ
# 番号が出たままになる。ブランチが変われば用事も変わった、と見なす。
#
# ただしブランチは「用事が終わった」の代理でしかなく、代理が効かない場面が 2 つある。
# どちらも実測で貼り付いた:
#   - main に留まる作業場（プラグイン開発など）では、ブランチが永久に変わらない。
#     別リポジトリの番号を打つと、そのまま何時間も出続けた（#1583、81 分）。
#   - 控えた時点のブランチが空（フックがリポジトリの外で走った）の記録は、空を理由に
#     照合を素通りして残り続けた（#1162・#1593）。
# そこで捨てる規則を 2 本にする。番号は owner/repo と組でないと 1 件を指さないので、
# ここで「正しい番号か」は決められない。決められないものを残さない方に倒す。
REF_STALE_MIN=30  # 記録がこれより古ければ捨てる。打ち直せば更新時刻も今になる
ref_file="${TMPDIR:-/tmp}/herdr-ref-${HERDR_PANE_ID//:/_}"
# 1 本目: 時間で切る。ブランチが動かない場でも、どんな取り違えも有限時間で必ず終わる。
# 消えた後は branch_pr（今のブランチの open PR）へ落ちるので、無言で空になるわけではない。
[ -n "$(find "$ref_file" -mmin "+$REF_STALE_MIN" 2>/dev/null)" ] && rm -f "$ref_file"
# 2 本目: ブランチでの照合。控えた時点のブランチが空なら、出所を確かめる術が無い記録なので
# 捨てる——「取れなかった」を「捨てなくてよい」に潰さない（それが #1162・#1593 の残り方）。
if [ -s "$ref_file" ]; then
  ref_branch=$(cut -f3 "$ref_file" 2>/dev/null)
  if [ -z "$ref_branch" ] || { [ -n "${branch:-}" ] && [ "$ref_branch" != "$branch" ]; }; then
    rm -f "$ref_file"
  fi
fi

# フック由来の番号が無いときは、ブランチから引いた open PR で埋める。ブランチへ移った
# 直後で、まだその PR に触っていない（pr-link がまだ書かれていない）セッションのため。
ref=$(cut -f2 "$ref_file" 2>/dev/null)
# タイトルを添えるのはブランチ由来の番号のときだけ。フック由来（人が打った #NNNN）は
# 別リポジトリの番号でありうるのに、gh は今のディレクトリのリポジトリで引くので、
# 同じ番号を持つ無関係な PR のタイトルが付く（取り違えの実例は上の #1583）。番号だけなら
# 「合っているか分からない」で済むが、タイトルが付くと読み手は確実に別物だと誤解する。
prt=""
if [ -z "$ref" ]; then
  ref="$branch_pr"
  prt="$branch_pr_title"
fi

# 番号を出すならブランチ名は出さない。同じ行に番号が 2 つ並ぶと、どちらが「今見て
# いるもの」か読み手に分からない（実測: "#1599 1535-required-che… #1592" と出た。
# 前者はセッションが触っている PR、後者はブランチに紐づく PR で、別物だった）。
[ -n "$ref" ] && br=""

args=()
# 出さないと決めたときは、前に送った値を明示して消す。消さないと TTL（5 分）の間、
# 切り替える前のブランチ名がサイドバーに残り続ける。
if [ -n "$br" ]; then args+=(--token "br=$br"); else args+=(--clear-token br); fi
if [ -n "$ref" ]; then args+=(--token "ref=#$ref"); else args+=(--clear-token ref); fi
if [ -n "$prt" ]; then args+=(--token "prt=$prt"); else args+=(--clear-token prt); fi
# 計器の色は値の側に埋められない。トークン値の制御文字は保存前に除去されるため
# （公式: "Metadata reporters provide values only; styling stays in the local sidebar
# configuration"）。段を変える手段は「別トークンへ送り分けて config 側の固定色を
# 切り替える」しか無い。空トークンとその区切りは herdr が消すので、この送り分けは
# 0 桁で色 1 段を買っている。$ref / $br と同じく 1 つの if/else で組むこと——
# 両方に値が入ると計器が二重に描かれ、本文が幅を越えて切り詰めが勝つ。
# 値が空のとき両方消すのは、赤い残骸だけが TTL の 5 分間居座らないようにするため。
if [ -z "$lim" ]; then
  args+=(--clear-token lim --clear-token limhot)
elif [ "$hot" = HOT ]; then
  args+=(--token "limhot=$lim" --clear-token lim)
else
  args+=(--token "lim=$lim" --clear-token limhot)
fi
[ -n "$mdl" ] && args+=(--token "mdl=$mdl")
[ ${#args[@]} -gt 0 ] || exit 0

# TTL は refreshInterval（30 秒）の 10 倍。セッションが死んだら数値も消える。
herdr pane report-metadata "$HERDR_PANE_ID" \
  --source claude-statusline --ttl-ms 300000 "${args[@]}" >/dev/null 2>&1 || true
