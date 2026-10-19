# Claude Code のステータスライン。標準入力の JSON を整形する。
# statusline.sh が呼ぶ（tiers プラグインの物。元は持ち主の手元の ~/.claude/statusline.jq）。

def esc: "\u001b[" + . + "m";
def dim: ("2" | esc) + . + ("0" | esc);
def tint(p): ((if p >= 80 then "31" elif p >= 50 then "33" else "32" end) | esc) + . + ("0" | esc);
# 高いほど良い値（キャッシュ命中率）用。tint と色の向きが逆。
def tinthi(p): ((if p >= 90 then "32" elif p >= 70 then "33" else "31" end) | esc) + . + ("0" | esc);

# 3 セルの目盛り。比例配分ではなく tint と同じ 50/80 の境目で刻む。
# 3 セルで比例させると 34% が 2 セル（見た目 67%）まで伸び、色は緑のままゲージだけ
# 警告に見える。長さと色を同じ境目に揃えて、2 つの信号が食い違わないようにする。
def bar(p): (if p <= 0 then 0 elif p < 50 then 1 elif p < 80 then 2 else 3 end) as $f
  | (("▰" * $f) // "") + (("▱" * (3 - $f)) // "");

def kfmt: if . >= 1000000 then "\(. / 1000000 | floor)M"
          elif . >= 1000 then "\(. / 1000 | floor)k"
          else tostring end;

# jq に小数桁指定がないので、セント単位の整数から組み立てる。
def usd: (. * 100 | round) as $c
  | "$\($c / 100 | floor)." + ("\($c % 100)" | if length < 2 then "0" + . else . end);

# 秒数を残り時間の表記にする。上位 2 桁だけ出す（3d4h / 1h23m / 12m）。
# jq の % は整数専用なので先に floor する。
def left: floor as $s
  | if $s <= 0 then "0m"
    else (($s / 86400) | floor) as $d
       | ((($s % 86400) / 3600) | floor) as $h
       | ((($s % 3600) / 60) | floor) as $m
       | if $d > 0 then "\($d)d\($h)h"
         elif $h > 0 then "\($h)h\($m)m"
         else "\($m)m" end
    end;

def gauge(name; e): e | select(.) | . as $g
  | (.used_percentage | round) as $p
  | (name | dim) + " " + (bar($p) | tint($p)) + " " + ("\($p)%" | tint($p))
    + (if ($g.resets_at | type) == "number"
       then " " + ("↻ " + (($g.resets_at - now) | left) | dim)
       else "" end);

. as $d
| [
    ( [ ($d.model.display_name | select(.) | sub(" *\\(.*\\)$"; "")),
        ($d.effort.level | select(.)) ]
      | join("/") + (if $d.fast_mode then "*" else "" end) | dim ),

    ( $d.context_window | select(.)
      | (.current_usage | to_entries | map(.value) | add) as $used
      | (.used_percentage | round) as $p
      | ("ctx" | dim) + " " + (bar($p) | tint($p)) + " " + ("\($p)%" | tint($p))
        + " " + ("\($used | kfmt)/\(.context_window_size | kfmt)" | dim) ),

    # 直近リクエストの入力のうちキャッシュから読めた割合。毎ターン低いままなら
    # 何か（model / effort 切替、MCP 再接続、ツール名まるごとの deny 等）が
    # プレフィックスを壊し続けている。
    ( $d.context_window.current_usage | select(.)
      | (.cache_read_input_tokens // 0) as $r
      | ((.cache_creation_input_tokens // 0) + (.input_tokens // 0)) as $m
      | select($r + $m > 0)
      | (($r * 100 / ($r + $m)) | round) as $p
      | ("cache" | dim) + " " + ("\($p)%" | tinthi($p)) ),

    gauge("5h"; $d.rate_limits.five_hour),
    gauge("7d"; $d.rate_limits.seven_day),

    ( $d.cost.total_cost_usd | select(. != null) | usd | dim )
  ]
| join((" · " | dim))
