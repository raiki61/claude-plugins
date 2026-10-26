#!/usr/bin/env bash
# 終わりのあるバックグラウンド（run_in_background の Bash と Monitor〔印 herdr:ignore の付いた終わらない見張りは数えない〕と、
# バックグラウンドで起動したサブエージェント）の本数を出す。statusline.sh が「⧖ バックグラウンド作業中 N 本」の N に使う。
#
# 使い方: bg-count.sh <会話の記録 transcript_path>（statusline の入力の transcript_path。空ならサブエージェントは数えない）
#
# 元は持ち主の手元の ~/.claude/herdr-bg-hold.sh の --count（2026-10-19 に tiers へ移した）。herdr へ作業中を報告し続ける見張り
# （--hook と report-agent の繰り返し）は 2026-10-13 に止めてあったので写していない。2026-10-12 から herdr の Claude 連携が会話の
# 持ち主を herdr:claude に登録し、ほかの報告を捨てるため、作業中は画面の印と herdr の判定ルール（claude-rule.toml）で出す。
#
# 決まり:
# - 数えるのは、この Claude の直下の Bash（shell-snapshots を source する bash -c）。終わらない見張り（使用率の見張りなど）は、
#   コマンドに印 `herdr:ignore` を書けば数えない（数えると作業中が解けない）。印は終わらない物だけに付ける。darkfactory の run の
#   起動・承認・試験のような終わりのある背景に付けると、走っている間ずっと待機に見える（2026-10-01、work1 の Claude が run の起動
#   全部に付けていて、run が 19 本走る間 idle だった）。
set -u

# この台本を起動した Claude の pid を、親をたどって探す。
# 背景の Bash の親になる、いちばん近い Claude を採る。Claude のプロセスの名前（comm）は起動方法で 3 通りある:
#   - claude: 端末で ~/.local/bin/claude を起動した会話
#   - 2.1.302 など: ~/.local/share/claude/versions/<版> を直に起動した会話（名前が版の数字になる）。macOS の comm はパスごと
#     出るので */claude/versions/* で当たるが、Linux の comm はパスを持たず版の数字だけになるので、実行ファイルのパス（/proc/<pid>/exe）で見る
#     （2026-10-26 に python:3.14-slim で、versions/2.1.302 を直に起動した処理の comm が「2.1.302」、exe がパスごとなのを見た）
#   - claude bg-spare: claude --bg や claude attach で開く背景の会話。会話は daemon（claude）→ bg-pty-host → bg-spare の
#     bg-spare の中で動き、背景の Bash はその直下に付く。名前が「claude」とだけ合う物を探すと、上の daemon を採って
#     直下に Bash が無く、0 本と数えていた（2026-10-18、guided-resolver の w9R:p1 で「1 shell」なのに印が出なかった）。
find_claude() {
  local p=$1 c
  while [ -n "$p" ] && [ "$p" -gt 1 ]; do
    c=$(ps -o comm= -p "$p" 2>/dev/null)
    case "$c" in
      "claude bg-spare"*|*/claude/versions/*|claude|*/claude) echo "$p"; return ;;
    esac
    case "$(readlink "/proc/$p/exe" 2>/dev/null)" in
      */claude/versions/*) echo "$p"; return ;;
    esac
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  done
}
# この Claude の直下の背景（Bash と Monitor）の pid を並べる
bg_pids() {
  ps -Ao pid=,ppid=,command= | awk -v c="$1" '$2==c && /shell-snapshots\/snapshot-/ && !/herdr:ignore/ {print $1}'
}
# 会話の記録 $1（statusline の transcript_path）の隣の subagents/ のうち、バックグラウンドで起動して（meta の
# requestShape が background）まだ走っているサブエージェントの本数。$2 はこの Claude のプロセスが起きた時刻（UNIX 秒。空なら見ない）。
# サブエージェントは Claude のプロセスの中で動き、プロセスに出ない。そこで「終わった」と言える印を、確かな順に見る。
# どれにも当たらなければ走っている。
#   1. 親の記録の終わりの知らせ: Claude Code は下請けが終わると、親の記録に <task-notification>（status が
#      completed・failed・killed など）を書く。それが下請けの最後の行と同じか後なら終わり。知らせの後に下請けが書き足して
#      いれば（SendMessage で続けた）、走っている。止めた（TaskStop・割り込み）下請けも killed の知らせで終わりと分かる
#      （2026-10-14、guided-resolver-work0 の会話で、最後の行が「[Request interrupted by user]」の止めた 1 本を、3 の決まり
#      だけで見ていて 6 時間の区切りまで走っていると数えた）。
#   2. プロセスより前: 下請けの最後の行が、今の Claude のプロセスが起きるより前なら終わり。下請けはプロセスより長く
#      生きないので、Claude を落として開き直した時など、知らせが書かれずに終わった物もこれで外れる。
#   3. 最後の会話の行（assistant か user。後ろの attachment などの行は飛ばす）が、文を書いてツールを呼んでいない assistant の
#      行なら終わり（知らせが書かれる前の一瞬を埋める。stop_reason は空のことがあるので見ない。2026-10-13 の my_notes の会話）。
# 6 時間書かれていない記録は数えない（どの印も読めない形に変わった時の止め）。
# 記録の形が読めない時は数えない（作業中に見え続けるより、待機に見える方へ倒す）。
bg_agents() {
  [ -n "${1:-}" ] || { echo 0; return; }
  python3 - "$1" "${2:-}" <<'PY' 2>/dev/null || echo 0
import datetime, json, os, re, sys, time
t, born = sys.argv[1], sys.argv[2]
d = os.path.join(os.path.dirname(t), os.path.basename(t)[:-len(".jsonl")], "subagents")
born_at = datetime.datetime.fromtimestamp(int(born), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") if born.isdigit() else ""
ENDED = re.compile(rb"<task-id>([0-9a-z]+)</task-id>.*?<status>(completed|failed|killed|stopped|cancelled)</status>", re.S)
ended = {}   # 下請けの id → 終わりの知らせの最後の時刻（ISO 8601 の UTC の字のまま比べる。どれも Claude Code が書く同じ形）
try:
    with open(t, "rb") as fh:
        for raw in fh:
            if b"<task-notification>" not in raw:
                continue
            try:
                stamp = json.loads(raw).get("timestamp") or ""
            except ValueError:
                continue
            for task, _ in ENDED.findall(raw.replace(b"\\n", b"\n")):
                key = task.decode()
                if stamp > ended.get(key, ""):
                    ended[key] = stamp
except OSError:
    pass
n = 0
for f in os.listdir(d) if os.path.isdir(d) else []:
    if not f.endswith(".jsonl"):
        continue
    p = os.path.join(d, f)
    try:
        if time.time() - os.path.getmtime(p) > 6 * 3600:
            continue
        with open(p[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as m:
            if json.load(m).get("requestShape") != "background":
                continue
        with open(p, "rb") as fh:
            fh.seek(max(0, os.path.getsize(p) - 262144))
            rows = fh.read().splitlines()
        last = None
        for raw in reversed(rows):
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if row.get("type") in ("assistant", "user"):
                last = row
                break
        if last is None:
            continue
        stamp = last.get("timestamp") or ""
        task = f[len("agent-"):-len(".jsonl")] if f.startswith("agent-") else ""
        if task in ended and ended[task] >= stamp:
            continue
        if born_at and stamp and stamp[:19] < born_at:
            continue
        content = (last.get("message") or {}).get("content")
        kinds = [c.get("type") for c in content if isinstance(c, dict)] if isinstance(content, list) else []
        if not (last.get("type") == "assistant" and "text" in kinds and "tool_use" not in kinds):
            n += 1
    except Exception:
        continue
print(n)
PY
}

claude_pid=$(find_claude "$PPID")
# 会話でない Claude（背景の会話をまとめる daemon）を採ったか、見つからなかったときは、シェルを 0 本と数えて黙って待機に見せず、
# statusline.sh と同じエラーの記録に残す。Claude Code が起動方法やプロセスの名前を変えるとここが外れる（上の find_claude の
# 2026-10-18 の外れ方は、どこにも記録されずに続いていた）。
case "$(ps -o command= -p "${claude_pid:-0}" 2>/dev/null)" in
  ""|*" daemon run"*)
    printf '%s %s bg-count: 会話の Claude が見つからない（親の名前: %s）\n' "$(date '+%m-%dT%H:%M:%S')" "${HERDR_PANE_ID:-?}" \
      "$(p=$PPID; while [ "${p:-0}" -gt 1 ]; do ps -o comm= -p "$p" | sed 's#.*/##'; p=$(ps -o ppid= -p "$p" | tr -d ' '); done | paste -sd '<' -)" \
      >> "${TMPDIR:-/tmp}/statusline-errors.log"
    claude_pid="" ;;
esac
shells=0
[ -n "$claude_pid" ] && shells=$(bg_pids "$claude_pid" | wc -l | tr -d ' ')
born=""
# macOS の date は -j -f で読み、Linux（GNU の date に -j が無い）は ps の経過秒（etimes）を今から引く
[ -n "$claude_pid" ] && born=$(date -j -f "%a %b %d %T %Y" "$(LC_ALL=C ps -o lstart= -p "$claude_pid")" +%s 2>/dev/null \
  || { e=$(ps -o etimes= -p "$claude_pid" 2>/dev/null | tr -d ' '); [ -n "$e" ] && echo $(( $(date +%s) - e )); })
echo $(( shells + $(bg_agents "${1:-}" "$born") ))
