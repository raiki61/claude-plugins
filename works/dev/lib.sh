# shellcheck shell=sh
# works/dev/lib.sh — mktarget.sh・real-run.sh・dogfood.sh が . で読む（単独では走らせない）

# works_dev_copy_pack <works の dir> <pack の dir>: works/ を project pack として写す。tests/・dev/・docs/ は除く
# （Archon はドット始まりのフォルダと、直下に YAML の無いフォルダを工程として読まない）。
# Python のバイトコードキャッシュや OS のゴミファイル、Claude Code がプラグインのキャッシュの版の置き場に置く印
# （.in_use/・.orphaned_at。works をプラグインのキャッシュから起こした時に在る）は pack に残さない。
works_dev_copy_pack() {
  mkdir -p "$2"
  for _entry in "$1"/* "$1"/.[!.]*; do
    [ -e "$_entry" ] || continue
    case "$(basename "$_entry")" in
      tests | dev | docs | .git | .in_use | .orphaned_at) continue ;;
    esac
    cp -R "$_entry" "$2/"
  done
  find "$2" \( -name "__pycache__" -o -name ".DS_Store" -o -name "*.pyc" \) -print0 | xargs -0 rm -rf
  # 出どころの控え <pack>/.works-source.json（{rev, dirty, from, version}）。run ごとの版の控え versions.json（線の start が
  # .shared/core/versions.py で書く）が読む。写しは git を持たないので、写す時に元の commit と手元の書き換えの有無を残す。
  # rev・dirty は、元の works がその git のリポジトリで追跡されている時だけ引く（プラグインのキャッシュ（git の外）から写した時と、
  # キャッシュを含む別のリポジトリ（設定の置き場を git で持つ人）の中の時は null。別のリポジトリの commit を works の版と偽らない）。
  # version は元の .claude-plugin/plugin.json の version（無ければ null）。中身そのものの印は versions.json の pack_sha256 が持つ
  SRC_DIR="$1" python3 -c '
import json, os, subprocess, sys
src = os.environ["SRC_DIR"]
def git(*a):
    r = subprocess.run(["git", "-C", src, *a], capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip() if r.returncode == 0 else None
tracked = bool(git("ls-files", "--", ".claude-plugin/plugin.json"))
rev = git("rev-parse", "HEAD") if tracked else None
status = git("status", "--porcelain", "--", ".") if rev else None
try:
    with open(os.path.join(src, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        version = json.load(f).get("version")
except (OSError, ValueError, AttributeError):
    version = None
doc = {"rev": rev, "dirty": None if status is None else status != "", "from": os.path.abspath(src),
       "version": version if isinstance(version, str) else None}
sys.stdout.write(json.dumps(doc, ensure_ascii=False) + "\n")
' >"$2/.works-source.json"
}

# works_dev_launch <launch.py の引数…>: 部品 launch.py を呼ぶ。lib.sh は . で読まれ自分の場所を知れないので、呼び手の殻が置いた
# DEV_DIR（works/dev）を使う（無ければ呼び手の殻の dir）
works_dev_launch() {
  python3 -I "${DEV_DIR:-$(cd "$(dirname "$0")" && pwd -P)}/launch.py" "$@"
}

# works_dev_ledgers <控えの置き場> [<run-id>]: 控えを読む一覧の口（launch.py ledger list）。読めた控え 1 つを 1 行、
# run_id・対象の dir（realpath）・結んだ時刻（無ければ 0）・包んだ基の参照（refs/works/wraps/ の下の時だけ）・herdr_pane・
# herdr_socket・続き中（works_dev_continue の印 <置き場>/<run-id>.cont の鍵を誰かが持っていれば 1、無ければ空）・
# 隔離の前の読み出しのファイル（.json の絶対パスの時だけ）をタブで区切って出す（run-id を渡せばその控えだけ）。壊れた・run_id の無い・
# 知らない版の控えは飛ばす
works_dev_ledgers() {
  if [ -n "${2:-}" ]; then
    works_dev_launch ledger list --dir "$1" --run-id "$2"
  else
    works_dev_launch ledger list --dir "$1"
  fi
}

# 試験の枠の印（盤面の testslot.json。書くのは .shared/core/slotwrap.sh、消すのは tree_run.slotted_run）の読み口。
# works_dev_show_run と works_dev_herdr_sync の python が exec して使う（lib.sh は works/dev の外から . されることがあり、
# .shared/core を import できるとは限らないので、読み口はここに 1 つ置く）
WORKS_DEV_SLOT_PY='
import json as _json, os as _os, time as _time
def run_board(row):
    return _os.path.join(row.get("output_root") or "", "artifacts", "runs", row.get("id") or "", "board")
def slot_mark(board):
    """印 {state: waiting|held, since, slots, pid} に alive（pid が居るか。読めなければ None）と minutes（since からの分）を足す。
    無い・読めない・知らない形なら None"""
    try:
        with open(_os.path.join(board, "testslot.json"), encoding="utf-8") as f:
            d = _json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("state") not in ("waiting", "held"):
        return None
    pid, alive = d.get("pid"), None
    if isinstance(pid, int) and pid > 0:
        try:
            _os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
    since = d.get("since")
    minutes = int((_time.time() - since) // 60) if isinstance(since, (int, float)) else None
    return dict(d, alive=alive, minutes=minutes)
def slot_waiting(m):
    return bool(m) and m["state"] == "waiting" and m["alive"] is not False
import datetime
def when(v):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(str(v), fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    return None
'

# works_dev_herdr_sync <archon を呼ぶ殻> <控えの置き場…（改行で区切る）> [<run-id>[=<状態>]…]: herdr が在る時だけ、run を起こした
# herdr の枠（控えの herdr_pane と herdr_socket の組）ごとに、その枠から起こした run の集計を 1 つの信号で出し、その枠のサーバへ送る
# （herdr の公式の口。source works-factory・agent works は 1 つのまま、run ごとに上書きしない）。送る枠は、名指した run を起こした枠と、
# 打った殻の枠（HERDR_ENV=1 の HERDR_PANE_ID）だけ（昔の枠へ毎回送らない）。打った殻が枠の外でも、名指した run の起こした枠へは送る
# （公式の手引きの「枠の外では何もしない」から外れるのは、run を起こした枠の表示を別の殻から打った続きに追わせるため。枠の外で
# 起こした run は控えに枠が無いので、今も何も送らない）。関所で待つ・落ちた run（同じ枠・同じ対象で後に起こした run が在る落ちた run は
# 終わった run に数える。比べる順は Archon の一覧の started_at で、控えの started_at ではない）が 1 つでも在れば blocked、無くて走っている run が
# 在れば working（試験の枠を待つ run は走る run のうちに「うち枠待ち k」と数える。続き中の印の在る run は Archon がまだ paused を
# 返しても走る run）、全部終わった時だけ pane release-agent。状態の分からない run か落ちた run が在る時だけ、その控えの在る家（控えの置き場の親）
# ごとに一覧を 1 回引く。herdr を呼ぶのはここだけ。herdr が無い・失敗した時は何もしない（run を止めない・終了の値を変えない）
works_dev_herdr_sync() {
  command -v herdr >/dev/null 2>&1 || return 0
  _archon="$1"
  _runs="$2"
  shift 2
  _ledgers="$(printf '%s\n' "$_runs" | while IFS= read -r _d; do
    [ -n "$_d" ] || continue
    works_dev_ledgers "$_d" | awk -F'\t' -v home="${_d%/runs}" '$5 != "" { print home "\t" $1 "\t" $2 "\t" $5 "\t" $6 "\t" $7 }'
  done)"
  [ -n "$_ledgers" ] || return 0
  _sigs="$(ARCHON_SH="$_archon" LEDGERS="$_ledgers" SLOT_PY="$WORKS_DEV_SLOT_PY" python3 -c '
import json, os, subprocess, sys, time
e = os.environ
exec(e["SLOT_PY"])
me_pane = e.get("HERDR_PANE_ID", "") if e.get("HERDR_ENV") == "1" else ""
me_sock = e.get("HERDR_SOCKET_PATH", "") if me_pane else ""
home_of, where, target_of, cont = {}, {}, {}, set()
for line in e["LEDGERS"].splitlines():
    f = line.split("\t")
    if len(f) < 6 or f[1] in home_of:   # 同じ run の控えが 2 つの置き場に在れば先の物
        continue
    home, rid, target, pane, sock, c = f[:6]
    home_of[rid] = home
    target_of[rid] = target
    # サーバを残していない前の控えは、同じ名の枠に居る打った殻のサーバと見る（前の作りと同じ送り先）。それ以外は既定のサーバ
    where[rid] = (sock or (me_sock if pane == me_pane else ""), pane)
    if c:
        cont.add(rid)
named = {a.split("=", 1)[0] for a in sys.argv[1:]}
known = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
known.update({r: "running" for r in cont})
picked = sorted({where[r] for r in named if r in where} | ({(me_sock, me_pane)} if me_pane else set()))
rows = {}
def listed(home):
    if home not in rows:
        got = subprocess.run(["sh", e["ARCHON_SH"], "workflow", "runs", "--json"],
                             env=dict(e, WORKS_DEV_NO_AUTH="1", WORKS_DEV_HOME=home), capture_output=True, text=True)
        try:
            rows[home] = {r.get("id"): r for r in json.loads(got.stdout).get("runs", [])}
        except (ValueError, AttributeError):
            sys.exit(0)
    return rows[home]
done = ("completed", "cancelled", "")
# herdr は同じ source の通し番号が前に受けた物より大きい報告だけを受ける（release も同じ）。ミリ秒の時刻から始め、送るたびに 1 つ増やす
seq = time.time_ns() // 1000000
for sock, pane in picked:
    mine = [r for r in where if where[r] == (sock, pane)]
    if not mine:
        continue
    states = [known[r] if r in known else (listed(home_of[r]).get(r) or {}).get("status") or "" for r in mine]
    # 同じ枠・同じ対象で後に起こした run が在る failed は、人がもう起こし直した物なので終わった run に数える（後の run の状態は問わない。
    # 後の run がまた落ちれば、その run が人の番になる）。比べる材料が欠ける時（対象が空・時刻が読めない・同じ時刻）は人の番に倒す
    if "failed" in states:
        began = {r: when((listed(home_of[r]).get(r) or {}).get("started_at")) for r in mine}
        states = ["completed" if s == "failed" and target_of[r] and began[r]
                  and any(target_of[o] == target_of[r] and began[o] and began[o] > began[r] for o in mine)
                  else s for r, s in zip(mine, states)]
    running = sum(s in ("running", "pending") for s in states)
    ended = sum(s in done for s in states)
    waiting = len(states) - running - ended
    if waiting:
        sig = "blocked\tfactory: 人の番 {}・走る {}・終わった {}".format(waiting, running, ended)
    elif running:
        # 枠待ちは人の答えが要る待ちではないので working のまま、走る run のうちに数える（印を読むのに一覧の output_root が要る。
        # 続き中の run はまだ枠を待たないので一覧を引かない——続きの口が Archon を呼ぶ前の集計を遅らせない）
        slot_wait = sum(1 for r, s in zip(mine, states) if s in ("running", "pending") and r not in cont
                        and slot_waiting(slot_mark(run_board(listed(home_of[r]).get(r) or {}))))
        sig = "working\tfactory: 走る {}{}・終わった {}".format(running, "（うち枠待ち {}）".format(slot_wait) if slot_wait else "",
                                                              ended)
    else:
        sig = "release"
    print("{}\t{}\t{}\t{}".format(seq, sock, pane, sig))
    seq += 1
' "$@" 2>/dev/null)" || return 0
  printf '%s\n' "$_sigs" | while IFS= read -r _l; do
    [ -n "$_l" ] || continue
    _seq="${_l%%	*}"
    _l="${_l#*	}"
    _sock="${_l%%	*}"
    _l="${_l#*	}"
    _pane="${_l%%	*}"
    _sig="${_l#*	}"
    case $_sig in
      release) set -- pane release-agent "$_pane" --source works-factory --agent works --seq "$_seq" ;;
      *) set -- pane report-agent "$_pane" --source works-factory --agent works --state "${_sig%%	*}" --message "${_sig#*	}" --seq "$_seq" ;;
    esac
    # 控えのサーバが空なら既定のサーバへ（打った殻のサーバを継がない）
    if [ -n "$_sock" ]; then
      HERDR_SOCKET_PATH="$_sock" herdr "$@" >/dev/null 2>&1 || true
    else
      (unset HERDR_SOCKET_PATH; herdr "$@") >/dev/null 2>&1 || true
    fi
  done
}

# works_dev_ledger_dirs: herdr の枠の集計が数える控えの置き場（改行で区切る）。1 行目は今の家の置き場（$WORKS_DEV_HOME/runs）。
# 家の根 WORKS_STATE_ROOT（launch.py env が解く use.sh の家の根）が在れば、既定の家の全部（前の既定の家 use と clone ごとの
# use-<印>）の置き場も足す。1 つの枠から別の clone の run を起こしても、ある clone の人の番の合図が別の clone の終わりで消えない
works_dev_ledger_dirs() {
  printf '%s\n' "$WORKS_DEV_HOME/runs"
  if [ -n "${WORKS_STATE_ROOT:-}" ]; then
    printf '%s\n' "$WORKS_STATE_ROOT/use/runs" "$WORKS_STATE_ROOT"/use-*/runs
  fi
}

# 殻の trap はプロセスに 1 つなので、後始末の trap を張る・外すはここの 1 組だけが書く（呼び手が trap を直に書くと、後から別の呼び手が消す）。
# works_dev_trap_add <名> <コマンド>: 終わる時（EXIT）と INT・TERM・HUP で回す後始末を名で登録する（同じ名は置き換え。コマンドは回す時に
# eval する）。シグナルは信号ごとに受け、後始末の後に同じ信号で落ち直す（呼び手から見た終わり方を trap の無い時から変えない）。
# works_dev_trap_del <名>: その名だけを外し、登録が空になったら trap を戻す。works_dev_continue は INT・TERM・HUP の trap を自分で
# 張って外す（持ち主の条件で変えない）ので、登録は works_dev_continue を通る前に外す並びで使う
works_dev_trap_add() {
  eval "_works_dev_trap_cmd_$1=\$2"
  case " ${_works_dev_trap_names:-} " in
    *" $1 "*) ;;
    *) _works_dev_trap_names="${_works_dev_trap_names:-} $1" ;;
  esac
  trap '_works_dev_trap_fire' EXIT
  trap '_works_dev_trap_die INT' INT
  trap '_works_dev_trap_die TERM' TERM
  trap '_works_dev_trap_die HUP' HUP
}

works_dev_trap_del() {
  _wdtd_rest=""
  for _wdtd_n in ${_works_dev_trap_names:-}; do
    [ "$_wdtd_n" = "$1" ] || _wdtd_rest="$_wdtd_rest $_wdtd_n"
  done
  _works_dev_trap_names="$_wdtd_rest"
  eval "unset _works_dev_trap_cmd_$1"
  case "$_wdtd_rest" in
    *[!\ ]*) ;;
    *) trap - EXIT INT TERM HUP ;;
  esac
}

# 登録の並びを空にしてから回す（信号の後の EXIT で 2 度走らない）。後始末の失敗は次の後始末を止めない
_works_dev_trap_fire() {
  _wdtf_names="${_works_dev_trap_names:-}"
  _works_dev_trap_names=""
  for _wdtf_n in $_wdtf_names; do
    eval "_wdtf_cmd=\${_works_dev_trap_cmd_$_wdtf_n:-}"
    eval "unset _works_dev_trap_cmd_$_wdtf_n"
    eval "$_wdtf_cmd" || true
  done
}

_works_dev_trap_die() {
  _works_dev_trap_fire
  trap - EXIT INT TERM HUP
  kill -s "$1" "$$"
}

# works_dev_reads_guard <out>: 隔離の前に読む読み出しのファイル <out>（非公開の本文を持つ）の後始末を登録する。ghreads read の前に呼ぶ。
# 殻が works_dev_reads_settle より前に落ちたら（set -e・INT・TERM・HUP）、<out> と ghreads._write の一時のファイル（.<out の名>.*.tmp。
# python の子が TERM で落ちると後始末が走らない）を消す
works_dev_reads_guard() {
  GITHUB_READS=""
  _works_dev_reads_out="$1"
  works_dev_trap_add reads 'rm -f "$_works_dev_reads_out" "$(dirname "$_works_dev_reads_out")"/."$(basename "$_works_dev_reads_out")".*.tmp'
}

# works_dev_reads_settle <既に名指したか 1|0>: 読み出しのファイルを渡すべき run が在りうる所まで来たので guard を外し、残っていれば
# 0600 に揃える。結べて runs/ の控えに載った・unbound/ の控えか殻の案内の行が既に名指した（1）なら黙る。名指していない（0）なら
# 残したことと消してよいことを 1 行で出す（結べないことは run が無いことと同じではない。消すのは clean か人）
works_dev_reads_settle() {
  works_dev_trap_del reads
  [ -e "${_works_dev_reads_out:-}" ] || return 0
  chmod 600 "$_works_dev_reads_out"
  if [ "$1" = 0 ]; then
    echo "隔離の前の読み出し ${_works_dev_reads_out} は 0600 で残した（どの run の控えにも結べない）。続けないなら消してよい"
  fi
}

# works_dev_continue <archon を呼ぶ殻> <控えの置き場…（改行で区切る。1 行目がその run の控えの置き場）> <run-id> <archon の引数…>:
# Archon に続きを渡す口（承認・関所の答え・続き・止める・取り消し。どの殻のどの行もここを通る）。続き中の印
# <置き場>/<run-id>.cont（この殻が fd 9 で開いたまま flock で持つ）を置いてその run を running で集計し、Archon を呼び、印を外して run の今の状態で集計する
# （herdr の手引きの「始まりに working、人が要る時に blocked」）。止められても印を外して集計し直す。終了の値は Archon の値
# （集計の成否で変えない）。WORKS_CONTINUE_RC にファイルを渡せば Archon の終了の値をそこへ書く（切り離した呼び手が、後段の集計を
# 待たずに早い失敗を見る）
works_dev_continue() {
  _c_archon="$1"
  _c_runs="$2"
  _c_rid="$3"
  shift 3
  _c_mark="$(printf '%s\n' "$_c_runs" | sed -n 1p)/$_c_rid.cont"
  mkdir -p "$(dirname "$_c_mark")"
  # 鍵を取ってから置く（読み手が鍵の無い印を見る間を作らない）
  exec 9>"$_c_mark.$$"
  PYTHONDONTWRITEBYTECODE=1 python3 "${DEV_DIR:-}/../.shared/core/hold_lock.py" 9
  mv "$_c_mark.$$" "$_c_mark"
  trap 'rm -f "$_c_mark"; exec 9>&-; works_dev_herdr_sync "$_c_archon" "$_c_runs" "$_c_rid"; exit 130' INT TERM HUP
  works_dev_herdr_sync "$_c_archon" "$_c_runs" "$_c_rid=running"
  _c_rc=0
  # Archon の後に残る処理に鍵を継がせない
  sh "$_c_archon" "$@" 9>&- || _c_rc=$?
  if [ -n "${WORKS_CONTINUE_RC:-}" ]; then
    echo "$_c_rc" >"$WORKS_CONTINUE_RC.tmp" && mv "$WORKS_CONTINUE_RC.tmp" "$WORKS_CONTINUE_RC"
  fi
  trap - INT TERM HUP
  rm -f "$_c_mark"
  exec 9>&-
  works_dev_herdr_sync "$_c_archon" "$_c_runs" "$_c_rid"
  return "$_c_rc"
}

# works_dev_go <archon を呼ぶ殻> <対象の dir> [<前置きの後ろのコマンド>]: 承認・答え・続きの行の頭（後ろに approve <id> などを
# 足せば打てる）。既定の尾は sh <DEV_DIR>/continue.sh <archon を呼ぶ殻> workflow（続きの口 works_dev_continue を通り、前後で
# herdr の枠の集計を出す。DEV_DIR を置かない呼び手には sh <archon を呼ぶ殻> workflow）。3 つめ（字句で組んだ 1 行）を渡せば、その尾の代わりに同じ前置きでそれを打つ行にする。
# 承認・続きも AI の節を回すので認証が要る。変数の代入はその単純コマンドにだけ掛かるので、cd の後・sh の直前に置く。
# 呼び手が WORKS_KEYCHAIN_ITEM で回したなら項目名（秘密ではない）を載せ、そのまま打てば通るようにする。
# トークン（CLAUDE_CODE_OAUTH_TOKEN）だけで回したなら値は出さない（show が export した殻で打つよう 1 行で案内する）。
# 包みを入れた run（WORKS_DEV_ADAPTER=1）は続きのコマンドにも付ける（archon.sh は認証を使う実行のたびに設定を書き直す）。
# dogfood.sh はこれに respond を足して関所の文の答えの行の頭（WORKS_ANSWER_CMD）にする。
# 呼び手が WORKS_ANSWER_CMD を export していれば行に載せる（承認・続きはその場で残りの工程を回し、関所の文の答えの行をこれで組む）。
# WORKS_ANSWER_WHO（答えた者の穴。use.sh が置く）も在れば一緒に載せる。
# 模型を明示しなかった run は空の指定に start の時の既定を WORKS_MODEL_PINNED で添え、続きで既定を解き直さない
works_dev_go() {
  ARCHON_SH="$1" DIR="$2" TAIL="${3:-}" MODEL_PINNED="$(works_dev_model_value)" CONTINUE_SH="${DEV_DIR:+$DEV_DIR/continue.sh}" \
    STATE_ROOT="${WORKS_STATE_ROOT:-}" python3 -c '
import os, shlex
model = os.environ.get("WORKS_DEV_MODEL", "")
# 空は引用符なしで書く（行は WORKS_ANSWER_CMD の中に引用符ごと包まれるので、'' だと引用が入れ子になる）
model = shlex.quote(model) if model else " WORKS_MODEL_PINNED=" + shlex.quote(os.environ["MODEL_PINNED"])
item = os.environ.get("WORKS_KEYCHAIN_ITEM", "")
auth = "WORKS_KEYCHAIN_ITEM={} ".format(shlex.quote(item)) if item else ""
# Context7 の鍵の keychain の項目の名（秘密ではない。値は起こし役が読む）も同じに載せ、続きの支度の節も同じ鍵で引く
c7 = os.environ.get("WORKS_CONTEXT7_KEYCHAIN_ITEM", "")
auth += "WORKS_CONTEXT7_KEYCHAIN_ITEM={} ".format(shlex.quote(c7)) if c7 else ""
adapter = "WORKS_DEV_ADAPTER=1 " if os.environ.get("WORKS_DEV_ADAPTER") == "1" else ""
answer = os.environ.get("WORKS_ANSWER_CMD", "")
answer = "WORKS_ANSWER_CMD={} ".format(shlex.quote(answer)) if answer else ""
who = os.environ.get("WORKS_ANSWER_WHO", "")
answer += "WORKS_ANSWER_WHO={} ".format(shlex.quote(who)) if answer and who else ""
# 続きの集計が既定の家の全部の控えを数えるよう、家の根（use.sh の家）も載せる
root = "WORKS_STATE_ROOT={} ".format(shlex.quote(os.environ["STATE_ROOT"])) if os.environ["STATE_ROOT"] else ""
# 続きの口の入口は DEV_DIR（works/dev）の下。sh の . で読まれた lib.sh は自分の置き場を知れないので、DEV_DIR を置かずに
# 読んだ呼び手（入口の殻の外の試験など）には Archon を直に打つ尾を出す
cont = os.environ["CONTINUE_SH"]
tail = "sh {} {} workflow".format(shlex.quote(cont), shlex.quote(os.environ["ARCHON_SH"])) if cont else \
    "sh {} workflow".format(shlex.quote(os.environ["ARCHON_SH"]))
print("cd {} && {}WORKS_DEV_HOME={} {}WORKS_DEV_MODEL={} CLAUDE_BIN_PATH={} {}{}{}".format(
    shlex.quote(os.environ["DIR"]), auth, shlex.quote(os.environ["WORKS_DEV_HOME"]), root,
    model, shlex.quote(os.environ["CLAUDE_BIN_PATH"]),
    adapter, answer, os.environ["TAIL"] or tail))
'
}

# works_dev_run_json <呼び手> <archon を呼ぶ殻> <対象の dir> [<run-id>]: Archon の run の一覧を 1 回引き、その対象の
# darkfactory の run を 1 つ選んで行を JSON の 1 行で出す（起動の後でない引き方。起動の後に結ぶのは works_dev_ledger_bind）。
# run-id を渡せばその run（この対象の物でなければ見つからない）。無ければ一番新しい run。4 つめが all なら、この対象の全部の run を 1 行ずつ出す
# （1 本も無ければ何も出さずに 0）。見つからない・一覧が読めなければ 1 行の理由で 1。問い合わせは認証が要らないので認証を読ませない
works_dev_run_json() {
  WORKS_DEV_NO_AUTH=1 sh "$2" workflow runs --json 2>/dev/null |
    CALLER="$1" DIR="$3" RUN_ID="${4:-}" python3 -c '
import json, os, sys
e = os.environ
caller = e["CALLER"]
try:
    listed = json.load(sys.stdin)
except ValueError as err:
    sys.exit("{}: archon workflow runs --json の出力が JSON として読めない（{}）".format(caller, err))
# 名指しの家（WORKS_USE_HOME・前の既定の家 works/use）は対象をまたいで 1 つなので、起動した対象（Archon の run の行の metadata.workflow_source.origin）が
# この対象と違う run は採らない（origin の無い行は見分けられないので残す）
def origin(r):
    o = ((r.get("metadata") or {}).get("workflow_source") or {}).get("origin")
    return os.path.realpath(o) if isinstance(o, str) and o else None
here, rid = os.path.realpath(e["DIR"]), e["RUN_ID"]
every = rid == "all"
if every:
    rid = ""
runs = [r for r in listed.get("runs", []) if r.get("workflow_name") == "darkfactory" and origin(r) in (None, here)]
if rid:
    runs = [r for r in runs if r.get("id") == rid]
if not runs and not every:
    sys.exit("{}: darkfactory の run が見つからない（対象 {}{}）".format(caller, here, "・run id " + rid if rid else ""))
for r in runs if every else runs[:1]:
    print(json.dumps(r, ensure_ascii=False))
'
}

# works_dev_show_cmd <殻のパス> <archon を呼ぶ殻> <dir>: 続きの行の後ろに付ける口（<殻> --show <dir>。WORKS_DEV_SHOW_CMD）を export する。
# dogfood.sh・real-run.sh が起動の後と --show で呼ぶ
works_dev_show_cmd() {
  WORKS_DEV_SHOW_CMD="$(SHELL_SH="$1" ARCHON_SH="$2" DIR="$3" python3 -c '
import os, shlex
e = os.environ
print("WORKS_DEV_ARCHON={} {}".format(shlex.quote(e["ARCHON_SH"]), shlex.join(["sh", e["SHELL_SH"], "--show", e["DIR"]])))
')"
  export WORKS_DEV_SHOW_CMD
}

# works_dev_id_status: 標準入力の run の行（works_dev_run_json の 1 行）を <run-id>=<状態> にする
works_dev_id_status() {
  python3 -c 'import json, sys; r = json.load(sys.stdin); print("{}={}".format(r.get("id") or "", r.get("status") or ""))'
}

# works_dev_show_synced <呼び手> <archon を呼ぶ殻> <対象の dir> [<差分を取り込むリポジトリ>]: dogfood.sh・real-run.sh の起動の後と --show。
# run の行（WORKS_RUN_ROW。無ければ WORKS_RUN_ID の run か一番新しい run）を 1 回だけ引き、works_dev_show_run で出し、
# その状態で herdr の枠の集計（$WORKS_DEV_HOME/runs の控え）を出す。続きの行の後段（差分の書き直し）もここを通る。終了の値は
# works_dev_show_run の値（集計の成否で変えない）。引けなければ 1 行の理由で 1
works_dev_show_synced() {
  _row="${WORKS_RUN_ROW:-}"
  if [ -z "$_row" ]; then
    _row="$(works_dev_run_json "$1" "$2" "$3" "${WORKS_RUN_ID:-}")" || return 1
  fi
  _id_st="$(printf '%s\n' "$_row" | works_dev_id_status)"
  _st=0
  WORKS_RUN_ROW="$_row" works_dev_show_run "$1" "$2" "$3" "${4:-}" || _st=$?
  works_dev_herdr_sync "$2" "$WORKS_DEV_HOME/runs" "$_id_st"
  return "$_st"
}

# works_dev_ledger_bind <呼び手> <archon を呼ぶ殻> <対象の dir> <この起動の依頼の写し> [show [<差分を取り込むリポジトリ>]]:
# use.sh・dogfood.sh・real-run.sh の起動の後に run を結ぶ口（設計書 2.3）。run の一覧を 1 回引き、launch.py ledger bind が
# 盤面の依頼がこの起動の写し（起動ごとに一意の絶対パス。依頼を省いた起動は GITHUB_READS の読み出しのファイル）と一致する run が
# ちょうど 1 本の時だけ結んで控え（$WORKS_DEV_HOME/runs）を書き、WORKS_RUN_ROW・WORKS_RUN_ID・WORKS_RUN_STATUS を置く。5 つめに show を渡せば works_dev_show_synced に渡す（--show は控えを
# 書き直さない。起動の時の started_at と herdr_pane を残す）。結べなければ一覧に触れず控えも続きの行も書かず、理由と候補の後に
# 結べなかった 1 行を出して 1
works_dev_ledger_bind() {
  if ! _lb_out=$(WORKS_DEV_NO_AUTH=1 sh "$2" workflow runs --json 2>/dev/null |
    works_dev_launch ledger bind --for "$1" --dir "$WORKS_DEV_HOME/runs" --target "$3" --request "$4" \
      --model-value "$(works_dev_model_value)" --model-from "$(works_dev_model_from)" --wrap-ref "${WRAP_REF:-}" \
      --github-reads "${GITHUB_READS:-}"); then
    echo "この起動の run を結べなかった（続きの行は出さない。候補が在れば上の show の行で run id を名指しして出す）"
    return 1
  fi
  works_dev_launch_eval "$1" "$_lb_out" || return $?
  unset _lb_out
  [ "${5:-}" = show ] || return 0
  works_dev_show_synced "$1" "$2" "$3" "${6:-}"
}

# works_dev_show_run <呼び手> <archon を呼ぶ殻> <対象の dir> [<差分を取り込むリポジトリ> [<差分の置き場>]]:
# その対象の run（呼び手が WORKS_RUN_ROW に works_dev_run_json の行を渡せばその行、WORKS_RUN_ID を export すればその run、
# どちらも無ければ一番新しい run）の run id・状態・修正の差分がある worktree・次に打つコマンド（承認・関所に答える continue と stop・
# 拒否・続き）・報告の置き場（盤面の report.md。report の節まで済んだ後に在る）を出す。
# 4 つめを渡せば、run の worktree の git diff --binary <周の頭の版>（未追跡も入れる。P1 Task 29）を <差分の置き場>（既定は
# <対象の dir の親>）/run-<id>.diff に書き、取り込むと消えるファイルを 1 本ずつ名指しし、git apply で取り込むコマンドも出し、対象に pack の写し（.archon/workflows/works）が在って
# 修正がその .archon/ に触れていれば取り込まないよう 1 行で注意する。差分が空（起動の直後の関所など）なら書かず、前に書いた
# 同じ名のファイルを消し、取り込むコマンドも出さない（0 バイトの差分は「修正なし」に見え、取り込みを誤る）。
# 差分を書く git（read-tree・add -A・diff）のどれかが落ちた時は、前の差分ファイルを消さず「書けなかった」と出して終了コード 4 で
# 終わる（空の差分と取り違えない）。差分を書き終えた・本当に空と確かめられた時だけ 0（use.sh の片付けと apply が頼る口はこの値だけ）。
# 承認・拒否・続きのコマンドは、呼び手の WORKS_KEYCHAIN_ITEM を sh の直前に載せ、export の無い殻でもそのまま打てる形で出す。
# 呼び手が WORKS_DEV_SHOW_CMD（この関数を同じ対象で呼び直す殻の口。字句で組んだ 1 行で、後ろに run id を足して打つ）を export
# すれば、承認・関所の答え・続き・拒否・取り消しの行の後ろに同じ前置きでそれを付け、Archon が戻った後に差分を書き直す（行の終了は続きが落ちれば
# その値、続きが通れば書き直しの値）。その口だけを打つ行も出す。
# 修正は対象ではなく、Archon が run ごとに切った worktree の中にある。関所の文面の「テストのログ」の行が、テストの出力のファイル。
# 状態の下に launched_min（起こしてからの分）を出し、走っている run は Archon の workflow get の出来事を 1 回引いて、
# 走っている節・alive（最後の動きから 30 分以内か）・試験の枠を待っているか（盤面の testslot.json）・節ごとの費用 cost_usd
# （report.head_cost。報告の費用の行と同じ）も出す。
# WORKS_DEV_HOME・CLAUDE_BIN_PATH を export 済み（WORKS_DEV_MODEL は明示した時だけ）で、guard.sh を読み DEV_DIR（works/dev）を置いた殻から呼ぶ。
works_dev_show_run() {
  _go="$(works_dev_go "$2" "$3")"
  _redo=""
  [ -n "${WORKS_DEV_SHOW_CMD:-}" ] && _redo="$(works_dev_go "$2" "$3" "$WORKS_DEV_SHOW_CMD")"
  _row="${WORKS_RUN_ROW:-}"
  if [ -z "$_row" ]; then
    _row="$(works_dev_run_json "$1" "$2" "$3" "${WORKS_RUN_ID:-}")" || return $?
  fi
  _done_st="$(printf '%s\n' "$_row" | works_dev_id_status)"
  _is_done="$(works_dev_launch ledger "done" --status "${_done_st#*=}" 2>/dev/null)" || _is_done=""
  # shellcheck disable=SC2016  # python の中の $? は、出す続きの行が打たれる殻で展開する字
  printf '%s\n' "$_row" |
    IS_DONE="$_is_done" CALLER="$1" ARCHON_SH="$2" DIR="$3" BRING_BACK="${4:-}" DIFF_DIR="${5:-}" GO="$_go" REDO="$_redo" \
    CORE_DIR="${DEV_DIR:-}/../.shared/core" SLOT_PY="$WORKS_DEV_SLOT_PY" PYTHONDONTWRITEBYTECODE=1 python3 -c '
import json, os, shlex, subprocess, sys
exec(os.environ["SLOT_PY"])
r = json.load(sys.stdin)
item = os.environ.get("WORKS_KEYCHAIN_ITEM", "")
go = os.environ["GO"]
board = run_board(r)
wp = r.get("working_path") or ""
print("run id:", r.get("id"))
print("状態:", r.get("status"))
# 経過・生きているか・走っている節・節ごとの費用。欄名は本流 graphloops [0.23.0] の status（launched_min・alive・cost_usd）
now = datetime.datetime.now(datetime.timezone.utc)
began = when(r.get("started_at"))
print("launched_min:", "{}（Archon の run の started_at から今までの分）".format(int((now - began).total_seconds() // 60))
      if began else "取れない（run に started_at が無い）")
status = r.get("status") or ""
if status in ("running", "pending"):
    # 走っている run だけ出来事を 1 回引く（関所で待つ・終わった run は報告と関所の文が費用と節を出す）
    got = subprocess.run(["sh", os.environ["ARCHON_SH"], "workflow", "get", r.get("id") or "", "--verbose", "--events", "--json"],
                         env=dict(os.environ, WORKS_DEV_NO_AUTH="1"), capture_output=True, text=True)
    try:
        events = json.loads(got.stdout).get("events")
    except (ValueError, AttributeError):
        events = None
    if not isinstance(events, list):
        print("走っている節・節ごとの費用: 取れない（archon workflow get の出来事を読めない。終了コード {}）".format(got.returncode))
        events = []
    ends = ("node_completed", "node_failed", "node_skipped")
    open_nodes = {}
    for e in events:
        if isinstance(e, dict) and e.get("step_name"):
            k = e["step_name"]
            if e.get("event_type") == "node_started":
                open_nodes[k] = open_nodes.get(k, 0) + 1
            elif e.get("event_type") in ends and open_nodes.get(k):
                open_nodes[k] -= 1
    running = [k for k, n in open_nodes.items() if n > 0]
    if events:
        print("走っている節:", "・".join(running) if running else "無い（節の合間）")
    # 試験の枠は期限なしで待つので、待っていることを止まった run と見分けられるように出す（印が無ければ出さない）
    m = slot_mark(board)
    if m and m["alive"] is False:
        print("試験の枠: 古い印（pid {} が居ない。{} の {}）".format(m.get("pid"), os.path.join(board, "testslot.json"), m["state"]))
    elif m and m["state"] == "waiting":
        print("試験の枠: 待っている（{} 分・置き場 {}。空くまで期限なしで待つ）".format(m["minutes"], m.get("slots")))
    elif m:
        print("試験の枠: 中（{} 分前に取った・置き場 {}）".format(m["minutes"], m.get("slots")))
    # 生きているか: 最後の動き（run の行の last_activity_at か最後の出来事）が STALE_MIN 分より新しい。Archon の行は子の pid を出さない
    STALE_MIN = 30
    seen = [t for t in [when(r.get("last_activity_at"))] + [when(e.get("created_at")) for e in events if isinstance(e, dict)] if t]
    if seen:
        quiet = int((now - max(seen)).total_seconds() // 60)
        print("alive: {}（最後の動きから {} 分。{} 分を超えて動きが無ければ false）".format(
            "true" if quiet <= STALE_MIN else "false", quiet, STALE_MIN))
    else:
        print("alive: 取れない（run に動きの時刻が無い）")
    # 節ごとの費用は報告の費用の行そのもの（report.head_cost を import する。写さない）: 取れない節の件数と理由・
    # 1 つも取れない時の「取れない」・欄の形が未確認の印・合計は途中の節の和（run の和は読まない）まで報告と同じ
    if events:
        try:
            sys.path.insert(0, os.environ["CORE_DIR"])
            import report
            for line in report.head_cost(None, r.get("id") or "", events=events, launches=[]):
                print("cost_usd", line)
        except Exception as err:
            print("cost_usd: 取れない（report を読めない: {}）".format(err))
else:
    cost = (r.get("metadata") or {}).get("total_cost_usd")
    print("今までの費用:", "{} USD（Archon の run の metadata.total_cost_usd。目安で、正は報告の費用の行）".format(cost)
          if isinstance(cost, (int, float)) else "取れない（run に total_cost_usd が無い）")
print("修正の差分がある worktree:", r.get("working_path"))
# 出どころの名は起こし役 auth_launch.py の check の出力: keychain の段なら archon.sh が同じ順で拾い直し、受け継いだ変数の段なら
# その変数の名（殻に export が要る）
auth_from = os.environ.get("WORKS_AUTH_FROM", "")
if "keychain の項目" in auth_from and not item:
    print("認証: 下の行は archon.sh が {} から拾う（値は出さない）".format(auth_from))
elif not item:
    print("認証: 下の 3 つは {} を export した殻で打つ（値は出さない。keychain なら WORKS_KEYCHAIN_ITEM=<項目名> を sh の直前に足す）".format(
        auth_from or "CLAUDE_CODE_OAUTH_TOKEN"))
# 承認・答えはその場で続きを回す。use.sh からなら、決まった時間で戻って状態を返す wait の行も出す（承認・答えを裏で打った後、
# これを打ち直して見る）
redo = os.environ["REDO"]
def then(*words):
    # 続きの後に差分を書き直す。続きの終了の値は隠さない（落ちればその値、通れば書き直しの値）。exit は子の殻で打つ
    line = " ".join([go, *words])
    return line + "; works_rc=$?; {} {}; (exit $((works_rc ? works_rc : $?)))".format(redo, r.get("id")) if redo else line
print("進める（承認するとその場で続きを回す）:", then("approve", r.get("id")))
if os.environ.get("WORKS_USE_SH"):
    print("殻で進める（切り離して承認し、すぐ戻る）:", "sh {} approve {} {}".format(
        shlex.quote(os.environ["WORKS_USE_SH"]), shlex.quote(os.environ["DIR"]), r.get("id")))
    print("待って状態を見る（決まった時間で戻る。まだ走っていれば打ち直す）:", "sh {} wait {} {}".format(
        shlex.quote(os.environ["WORKS_USE_SH"]), shlex.quote(os.environ["DIR"]), r.get("id")))
print("取り消す（走っている run を Archon の cancel で止める。報告は report.sh で組む）:", then("cancel", r.get("id")))
# use.sh からなら、関所の答えと止めるのは殻の answer・stop だけを出す（生の respond・reject は答えた者の記録と run の控えを通らない）
if not os.environ.get("WORKS_USE_SH"):
    print("関所に一言で答えて進める:", then("respond", r.get("id"), "continue", shlex.quote("<通す範囲と条件>")))
    print("関所で止める（報告は出る）:", then("respond", r.get("id"), "stop", shlex.quote("<理由>")))
    print("止める:", then("reject", r.get("id")))
print("失敗や中断から続ける:", then("resume", r.get("id")))
if redo:
    print("差分だけを書き直す（Archon の生のコマンドで続けた後）:", redo, r.get("id"))
if os.environ.get("WORKS_USE_SH"):
    use = "sh {} {{}} {} {}".format(shlex.quote(os.environ["WORKS_USE_SH"]), shlex.quote(os.environ["DIR"]), r.get("id"))
    print("関所に殻で答える（人が決める関所は依頼者に聞き、答えた者を残す）:", use.format("answer"), "continue",
          shlex.quote("<通す範囲と条件>"), shlex.quote("<答えた者>"))
    print("止める（関所で待つ run は respond stop、走っている run は止め札。報告は出る）:", use.format("stop"), shlex.quote("<理由>"))
print("報告（report の節まで済んだ後）:", os.path.join(board, "report.md"))
# 次の run の依頼の下書き（報告の節が書く）。無人の run が人の判断の所で止まると、answers に答えの下書き（draft の行）が載る
nxt = os.path.join(board, "next-request.json")
if os.path.isfile(nxt):
    try:
        with open(nxt, encoding="utf-8") as f:
            doc = json.load(f)
        ans, fnd = doc.get("answers") or [], doc.get("findings") or []
        drafts = [a for a in ans if isinstance(a, dict) and a.get("draft")] if isinstance(ans, list) else []
        carried = [a for a in fnd if isinstance(a, dict) and a.get("draft")] if isinstance(fnd, list) else []
    except (OSError, ValueError, AttributeError):
        drafts, carried = [], []
    notes = []
    if drafts:
        notes.append("答えの下書き {} 件。機械は答えていない——見直して、台帳の問いの行（question が問いの key）は採るなら draft と source"
                     "（と note）を消して text を答えにし、関所の項目の行は次の run の関所の continue の一言に写してから消す".format(len(drafts)))
    if carried:
        notes.append("目的の外とした所見の下書き {} 件（findings）——次の run の目的に入れる行は draft と source を消し、入れない行は"
                     "消す".format(len(carried)))
    print("次の run の依頼の下書き:", nxt + ("（{}）".format("。".join(notes)) if notes else ""))
rc = 0
if os.environ["BRING_BACK"]:
    # 修正の差分は run の worktree の今の姿と周の頭の版（start の控え r<N>/start.json の base_rev）の差（未追跡も入れる。
    # 盤面の fix.diff は審査の段の物で、手直しの後の姿を持たないので読まない）。一時の index で数え、worktree の index は動かさない。
    # 一時の index は worktree の HEAD の木から始める（空から add -A すると、.gitignore に当たるのに追跡している物が消す行になる）
    import glob, tempfile
    base = ""
    for p in sorted(glob.glob(os.path.join(board, "r*", "start.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                base = json.load(f).get("base_rev") or base
        except (OSError, ValueError):
            pass
    diff_dir = os.environ["DIFF_DIR"] or os.path.dirname(os.path.abspath(os.environ["DIR"]))
    os.makedirs(diff_dir, exist_ok=True)
    diff = os.path.join(diff_dir, "run-{}.diff".format(r.get("id")))
    empty = False
    if os.path.isdir(wp) and os.path.exists(os.path.join(wp, ".git")):
        if not base:
            # 基が読めない時に worktree 自身の HEAD で代用すると、commit 済みの修正が差分に出ず 0 になり、片付けの門を通ってしまう。
            # 差分は見せるが、書けた物と言わず終了コード 4 にする
            base = subprocess.run(["git", "-C", wp, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            rc = 4
            print("修正の差分: 周の頭の版（start の控えの base_rev）が読めないので worktree 自身の HEAD を基にした。commit 済みの修正は差分に出ない（書き終えた物と見ず、終了コード 4）")
        failed = None
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_INDEX_FILE=os.path.join(td, "index"))
            for step, args in (("read-tree", ["read-tree", "HEAD"]), ("add -A", ["add", "-A"]),
                               ("diff", ["diff", "--cached", "--binary", base]),
                               ("diff --name-only", ["diff", "--cached", "--diff-filter=D", "--name-only", "-z", base])):
                got = subprocess.run(["git", "-C", wp] + args, env=env, capture_output=True)
                if got.returncode:
                    failed = (step, got.returncode)
                    break
                if step == "diff":
                    body = got.stdout
            if not failed:
                gone = got.stdout.decode("utf-8", "replace").split("\0")
        if failed:
            # git の失敗を空の差分と読むと前の差分ファイルを消す。書けなかった印は終了コード 4（呼び手が片付けてよいかを決める口）
            rc = 4
            empty = True
            print("修正の差分: 書けなかった（git {} が終了コード {}）。前の差分ファイルは消さずに残した: {}".format(
                failed[0], failed[1], diff))
        elif not body:
            empty = True
            if os.path.isfile(diff):
                os.remove(diff)
            print("修正の差分: まだ無い（run の worktree と周の頭の版 {} の差が空。書く先: {}）".format(base[:12], diff))
        else:
            with open(diff, "wb") as f:
                f.write(body)
            print("修正の差分（run の worktree と周の頭の版 {} の差。未追跡も入れる）: {}".format(base[:12], diff))
        wrapped = os.path.join(os.environ.get("WORKS_WRAPS_DIR", ""), base + ".txt")
        if os.environ.get("WORKS_WRAPS_DIR") and base and os.path.isfile(wrapped):
            with open(wrapped, encoding="utf-8") as f:
                print("包んだ（wrapped）: 起動の時の対象の手元の変更・未追跡を commit {} に包んで run の基にした: {}".format(
                    base[:12], " ".join(f.read().split())))
        for p in filter(None, [] if failed else gone):
            print("取り込むと消えるファイル:", p)
    else:
        print("修正の差分: run の worktree（{}）が無いので書いていない".format(wp))
    # 記録が止まりを示す run は、殻からなら生の git apply の行を出さない（use.sh apply の止まりの拒みを素通りさせない）
    # 判定が壊れた時も止まりと同じに扱う（止まりかを言えないまま生の行を出さない）
    try:
        sys.path.insert(0, os.environ["CORE_DIR"])
        import report
        stopped = report.stopped_run(board) if os.path.isdir(board) else None
        broken = ""
    except Exception as e:
        stopped, broken = None, " ".join("{}: {}".format(type(e).__name__, e).split())
    if not empty and stopped:
        print("止まった run: {}（{}）で止まった: 「{}」".format(
            report.OUTCOME_WORDS.get(stopped[0], stopped[0]), stopped[1], " ".join(stopped[2].split())))
    if not empty and broken:
        print("止まりの判定: できなかった（{}）。止まった run かを確かめてから取り込む".format(broken))
    if not empty and not ((stopped or broken) and os.environ.get("WORKS_USE_SH")):
        print("差分を元のリポジトリへ取り込む:", "git -C {} apply {}".format(shlex.quote(os.environ["BRING_BACK"]), shlex.quote(diff)))
    if os.environ.get("WORKS_USE_SH"):
        use = "sh {} {{}} {} {}".format(shlex.quote(os.environ["WORKS_USE_SH"]), shlex.quote(os.environ["DIR"]), r.get("id"))
        print("殻で取り込む（当たるかを先に見る・消す行は止まる・止まりの run は止まる）:", use.format("apply"))
        if os.environ["IS_DONE"] and not rc:
            # use.sh の show・wait は終わった run を差分を書いた直後に片付ける。ここで clean を勧めると消えた worktree へ打たせる
            print("終わった run の worktree と枝: use.sh の show・wait が差分を書いた後に自動で片付ける（残っていれば手で:", use.format("clean") + "）")
        else:
            print("終わった run の worktree と枝を片付ける:", use.format("clean"))
    touched = False
    # 注意は対象に pack の写しが在る時だけ（自分食い・使い捨ての対象）。ほかのリポジトリの .archon/ は対象自身の物
    if not rc and os.path.isfile(diff) and os.path.isdir(os.path.join(os.environ["DIR"], ".archon", "workflows", "works")):
        with open(diff, encoding="utf-8", errors="replace") as f:
            touched = any(l.startswith(("diff --git a/.archon/", "--- a/.archon/", "+++ b/.archon/")) for l in f)
    if touched:
        print("注意: 修正が works/ でなく pack の写し（.archon/）に触れている。その部分は元のリポジトリへ取り込まない")
sys.exit(rc)
'
}
