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

# works_dev_save_ledger <控えの置き場> <run-id> <対象の dir>: run の控え <置き場>/<run-id>.json を書く（use.sh・dogfood.sh・
# real-run.sh の同じ口）。模型（model は明示された全体の指定で、明示しなければ空。model_resolved は start の時に解いた
# {value, from}）・claude の実行ファイル・keychain の項目の名（値でなく名）・包み・結んだ時刻・包んだ基の参照
# （WRAP_REF）と、herdr の枠の中で起こしたならその枠（herdr_pane。works_dev_herdr_sync が枠ごとに数える元）を残す
works_dev_save_ledger() {
  mkdir -p "$1"
  RUN_ID="$2" DIR="$3" WRAP_REF="${WRAP_REF:-}" MODEL_VALUE="$(works_dev_model_value)" \
    MODEL_FROM="$(works_dev_model_from)" python3 -c '
import json, os, time
e = os.environ
pane = e.get("HERDR_PANE_ID", "") if e.get("HERDR_ENV") == "1" else ""
print(json.dumps({"run_id": e["RUN_ID"], "target": e["DIR"], "model": e.get("WORKS_DEV_MODEL", ""),
                  "model_resolved": {"value": e["MODEL_VALUE"], "from": e["MODEL_FROM"]},
                  "claude_bin": e.get("CLAUDE_BIN_PATH", ""), "keychain_item": e.get("WORKS_KEYCHAIN_ITEM", ""),
                  "adapter": e.get("WORKS_DEV_ADAPTER", ""), "started_at": time.time(),
                  "wrap_ref": e.get("WRAP_REF", ""), "herdr_pane": pane}, ensure_ascii=False))
' >"$1/$2.json"
}

# works_dev_ledgers <控えの置き場> [<run-id>]: 控え（works_dev_save_ledger の書いた形）を読む一覧の口。読めた控え 1 つを 1 行、
# run_id・対象の dir（realpath）・結んだ時刻（無ければ 0）・包んだ基の参照（refs/works/wraps/ の下の時だけ）・herdr_pane を
# タブで区切って出す（run-id を渡せばその控えだけ）。壊れた・run_id の無い控えは飛ばす。run_id・target・started_at・wrap_ref・herdr_pane の欄を読むのはここだけ
# （model・claude_bin・keychain_item・adapter の欄は use.sh の load_ledger が控えを直に開いて読む）
works_dev_ledgers() {
  RUNS_DIR="$1" RUN_ID="${2:-*}" python3 -c '
import glob, json, os
e = os.environ
for p in sorted(glob.glob(os.path.join(e["RUNS_DIR"], e["RUN_ID"] + ".json"))):
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        continue
    if not (isinstance(d, dict) and isinstance(d.get("run_id"), str) and d["run_id"]):
        continue
    s = lambda k: d.get(k) if isinstance(d.get(k), str) else ""
    wrap = s("wrap_ref") if s("wrap_ref").startswith("refs/works/wraps/") else ""
    at = d.get("started_at") if isinstance(d.get("started_at"), (int, float)) else 0
    print("\t".join([d["run_id"], os.path.realpath(s("target")) if s("target") else "", repr(at), wrap, s("herdr_pane")]))
'
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
'

# works_dev_herdr_sync <archon を呼ぶ殻> <控えの置き場…（改行で区切る）> [<run-id>=<状態>…]: herdr の枠（HERDR_ENV=1 と HERDR_PANE_ID）の中で
# herdr が在る時だけ、その枠から起こした run（控えの herdr_pane）の集計を 1 つの信号で出す（herdr の公式の口。source works-factory・
# agent works は 1 つのまま、run ごとに上書きしない）。関所で待つ・落ちた run が 1 つでも在れば blocked、無くて走っている run が
# 在れば working（試験の枠を待つ run は走る run のうちに「うち枠待ち k」と数える）、全部終わった時だけ pane release-agent。その枠から起こした run が 0 なら何もしない。状態を渡されなかった run が
# 在る時だけ、控えの在る家（控えの置き場の親）ごとに一覧を 1 回引く。herdr を呼ぶのはここだけ。枠の外・herdr が無い・失敗した時は何もしない（run を止めない）
works_dev_herdr_sync() {
  [ "${HERDR_ENV:-}" = 1 ] && [ -n "${HERDR_PANE_ID:-}" ] && command -v herdr >/dev/null 2>&1 || return 0
  _archon="$1"
  _runs="$2"
  shift 2
  _mine="$(printf '%s\n' "$_runs" | while IFS= read -r _d; do
    works_dev_ledgers "$_d" | awk -F'\t' -v pane="$HERDR_PANE_ID" -v home="${_d%/runs}" '$5 == pane { print home "\t" $1 }'
  done)"
  _sig="$(ARCHON_SH="$_archon" MINE="$_mine" SLOT_PY="$WORKS_DEV_SLOT_PY" python3 -c '
import json, os, subprocess, sys
e = os.environ
exec(e["SLOT_PY"])
home_of = dict(reversed(l.split("\t", 1)) for l in e["MINE"].splitlines() if "\t" in l)
mine = list(home_of)
if not mine:
    sys.exit(0)
known = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
rows = None
def listed():
    got_rows = {}
    for home in sorted(set(home_of.values())):
        got = subprocess.run(["sh", e["ARCHON_SH"], "workflow", "runs", "--json"],
                             env=dict(e, WORKS_DEV_NO_AUTH="1", WORKS_DEV_HOME=home), capture_output=True, text=True)
        try:
            got_rows.update({r.get("id"): r for r in json.loads(got.stdout).get("runs", [])})
        except (ValueError, AttributeError):
            sys.exit(0)
    return got_rows
if any(r not in known for r in mine):
    rows = listed()
    known = {**{k: r.get("status") or "" for k, r in rows.items()}, **known}
done = ("completed", "cancelled", "")
states = [known.get(r, "") for r in mine]
running = sum(s in ("running", "pending") for s in states)
ended = sum(s in done for s in states)
waiting = len(states) - running - ended
if waiting:
    print("blocked\tfactory: 人の番 {}・走る {}・終わった {}".format(waiting, running, ended))
elif running:
    # 枠待ちは人の答えが要る待ちではないので working のまま、走る run のうちに数える（印を読むのに一覧の output_root が要る）
    rows = rows if rows is not None else listed()
    slot_wait = sum(1 for r, s in zip(mine, states) if s in ("running", "pending")
                    and slot_waiting(slot_mark(run_board(rows.get(r) or {}))))
    print("working\tfactory: 走る {}{}・終わった {}".format(running, "（うち枠待ち {}）".format(slot_wait) if slot_wait else "",
                                                          ended))
else:
    print("release")
' "$@" 2>/dev/null)" || return 0
  [ -n "$_sig" ] || return 0
  # herdr は同じ source の通し番号が前に受けた物より大きい報告だけを受ける（release も同じ）。ミリ秒の時刻を通し番号にする
  _seq="$(python3 -c 'import time; print(time.time_ns() // 1000000)')"
  case $_sig in
    release) herdr pane release-agent "$HERDR_PANE_ID" --source works-factory --agent works --seq "$_seq" >/dev/null 2>&1 || true ;;
    *)
      herdr pane report-agent "$HERDR_PANE_ID" --source works-factory --agent works --state "${_sig%%	*}" --message "${_sig#*	}" \
        --seq "$_seq" >/dev/null 2>&1 || true
      ;;
  esac
}

# works_dev_go <archon を呼ぶ殻> <対象の dir> [<前置きの後ろのコマンド>]: 承認・答え・続きの行の頭（後ろに approve <id> などを
# 足せば打てる）。3 つめ（字句で組んだ 1 行）を渡せば、sh <archon を呼ぶ殻> workflow の代わりに同じ前置きでそれを打つ行にする。
# 承認・続きも AI の節を回すので認証が要る。変数の代入はその単純コマンドにだけ掛かるので、cd の後・sh の直前に置く。
# 呼び手が WORKS_KEYCHAIN_ITEM で回したなら項目名（秘密ではない）を載せ、そのまま打てば通るようにする。
# トークン（CLAUDE_CODE_OAUTH_TOKEN）だけで回したなら値は出さない（show が export した殻で打つよう 1 行で案内する）。
# 包みを入れた run（WORKS_DEV_ADAPTER=1）は続きのコマンドにも付ける（archon.sh は認証を使う実行のたびに設定を書き直す）。
# dogfood.sh はこれに respond を足して関所の文の答えの行の頭（WORKS_ANSWER_CMD）にする。
# 呼び手が WORKS_ANSWER_CMD を export していれば行に載せる（承認・続きはその場で残りの工程を回し、関所の文の答えの行をこれで組む）。
# WORKS_ANSWER_WHO（答えた者の穴。use.sh が置く）も在れば一緒に載せる。
# 模型を明示しなかった run は空の指定に start の時の既定を WORKS_MODEL_PINNED で添え、続きで既定を解き直さない
works_dev_go() {
  ARCHON_SH="$1" DIR="$2" TAIL="${3:-}" MODEL_PINNED="$(works_dev_model_value)" python3 -c '
import os, shlex
model = os.environ.get("WORKS_DEV_MODEL", "")
# 空は引用符なしで書く（行は WORKS_ANSWER_CMD の中に引用符ごと包まれるので、'' だと引用が入れ子になる）
model = shlex.quote(model) if model else " WORKS_MODEL_PINNED=" + shlex.quote(os.environ["MODEL_PINNED"])
item = os.environ.get("WORKS_KEYCHAIN_ITEM", "")
auth = "WORKS_KEYCHAIN_ITEM={} ".format(shlex.quote(item)) if item else ""
adapter = "WORKS_DEV_ADAPTER=1 " if os.environ.get("WORKS_DEV_ADAPTER") == "1" else ""
answer = os.environ.get("WORKS_ANSWER_CMD", "")
answer = "WORKS_ANSWER_CMD={} ".format(shlex.quote(answer)) if answer else ""
who = os.environ.get("WORKS_ANSWER_WHO", "")
answer += "WORKS_ANSWER_WHO={} ".format(shlex.quote(who)) if answer and who else ""
print("cd {} && {}WORKS_DEV_HOME={} WORKS_DEV_MODEL={} CLAUDE_BIN_PATH={} {}{}{}".format(
    shlex.quote(os.environ["DIR"]), auth, shlex.quote(os.environ["WORKS_DEV_HOME"]),
    model, shlex.quote(os.environ["CLAUDE_BIN_PATH"]),
    adapter, answer, os.environ["TAIL"] or "sh {} workflow".format(shlex.quote(os.environ["ARCHON_SH"]))))
'
}

# works_dev_run_json <呼び手> <archon を呼ぶ殻> <対象の dir> [<run-id> [<依頼のファイル>]]: Archon の run の一覧を 1 回引き、
# その対象の darkfactory の run を 1 つ選んで行を JSON の 1 行で出す（run の選び方はここだけ）。選び方:
# - 依頼のファイルを渡せば（start が起動の直後に run を結ぶ時）、盤面（r1/start.json の request_file か state.json の
#   inputs.request）がその依頼の run。依頼は start ごとに <家>/requests/<印>.json に写すので、並べた start の run と混ざらない。
#   盤面の無い run（盤面を作る前に落ちた）しか無ければそれを候補にする。候補が 1 つでなければ選ばず、候補と
#   <呼び手> show <対象> <id> の行を標準エラーに出して 1
# - run-id を渡せばその run（この対象の物でなければ見つからない）。どちらも無ければ一番新しい run
# 見つからない・一覧が読めなければ 1 行の理由で 1。問い合わせは認証が要らないので認証を読ませない
works_dev_run_json() {
  WORKS_DEV_NO_AUTH=1 sh "$2" workflow runs --json 2>/dev/null |
    CALLER="$1" DIR="$3" RUN_ID="${4:-}" REQUEST="${5:-}" python3 -c '
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
def asked(r):
    board = os.path.join(r.get("output_root") or "", "artifacts", "runs", r.get("id") or "", "board")
    for name, pick in (("r1/start.json", lambda d: d.get("request_file")),
                       ("state.json", lambda d: (d.get("inputs") or {}).get("request"))):
        try:
            with open(os.path.join(board, name), encoding="utf-8") as f:
                v = pick(json.load(f))
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(v, str) and v:
            return os.path.realpath(v)
    return None
here, rid, req = os.path.realpath(e["DIR"]), e["RUN_ID"], e["REQUEST"]
runs = [r for r in listed.get("runs", []) if r.get("workflow_name") == "darkfactory" and origin(r) in (None, here)]
if req:
    want = os.path.realpath(req)
    tagged = [(r, asked(r)) for r in runs]
    mine = [r for r, a in tagged if a == want] or [r for r, a in tagged if a is None]
    if len(mine) != 1:
        print("{}: この起動の run を 1 つに結べない（依頼 {} の run の候補が {} 本）。推定では選ばない".format(caller, want, len(mine)),
              file=sys.stderr)
        for r in mine:
            print("  候補 {}（{}）: {} show {} {}".format(r.get("id"), r.get("status"), caller, here, r.get("id")), file=sys.stderr)
        sys.exit(1)
    runs = mine
elif rid:
    runs = [r for r in runs if r.get("id") == rid]
if not runs:
    sys.exit("{}: darkfactory の run が見つからない（対象 {}{}）".format(caller, here, "・run id " + rid if rid else ""))
print(json.dumps(runs[0], ensure_ascii=False))
'
}

# works_dev_quote <語>: shlex.quote と同じ字句で 1 語を引用する（殻の口を組むのに python を起こさない）
works_dev_quote() {
  case "$1" in
    '') printf "''" ;;
    *[!A-Za-z0-9@%+=:,./_-]*) printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\"'\"'/g")" ;;
    *) printf '%s' "$1" ;;
  esac
}

# works_dev_show_cmd <殻のパス> <archon を呼ぶ殻> <dir>: 続きの行の後ろに付ける口（<殻> --show <dir>。WORKS_DEV_SHOW_CMD）を export する。
# dogfood.sh・real-run.sh が起動の後と --show で呼ぶ
works_dev_show_cmd() {
  WORKS_DEV_SHOW_CMD="WORKS_DEV_ARCHON=$(works_dev_quote "$2") sh $(works_dev_quote "$1") --show $(works_dev_quote "$3")"
  export WORKS_DEV_SHOW_CMD
}

# works_dev_id_status: 標準入力の run の行（works_dev_run_json の 1 行）を <run-id>=<状態> にする
works_dev_id_status() {
  python3 -c 'import json, sys; r = json.load(sys.stdin); print("{}={}".format(r.get("id") or "", r.get("status") or ""))'
}

# works_dev_show_synced <呼び手> <archon を呼ぶ殻> <対象の dir> [<差分を取り込むリポジトリ>]: dogfood.sh・real-run.sh の起動の後と --show。
# run の行（WORKS_RUN_ROW。無ければ WORKS_RUN_ID の run か一番新しい run）を 1 回だけ引き、works_dev_show_run で出し、
# その状態で herdr の枠の集計（$WORKS_DEV_HOME/runs の控え）を出す。続きの行の後段もここを通るので、承認・答え・続け・拒否・取り消しの
# 後に集計が run を追う。終了の値は works_dev_show_run の値（集計の成否で変えない）。引けなければ 1 行の理由で 1
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

# works_dev_show_started <呼び手> <archon を呼ぶ殻> <対象の dir> [<差分を取り込むリポジトリ>]: dogfood.sh・real-run.sh の起動の後。
# その対象の一番新しい run（対象は起動ごとに作り直すので 1 つ）を 1 回だけ引き、控え（$WORKS_DEV_HOME/runs）を書いてから
# works_dev_show_synced に渡す（--show は控えを書き直さない。起動の時の started_at と herdr_pane を残す）
works_dev_show_started() {
  _row="$(works_dev_run_json "$1" "$2" "$3")" || return 1
  _id_st="$(printf '%s\n' "$_row" | works_dev_id_status)"
  works_dev_save_ledger "$WORKS_DEV_HOME/runs" "${_id_st%%=*}" "$3"
  WORKS_RUN_ROW="$_row" works_dev_show_synced "$@"
}

# works_dev_show_run <呼び手> <archon を呼ぶ殻> <対象の dir> [<差分を取り込むリポジトリ> [<差分の置き場>]]:
# その対象の run（呼び手が WORKS_RUN_ROW に works_dev_run_json の行を渡せばその行、WORKS_RUN_ID を export すればその run、
# どちらも無ければ一番新しい run）の run id・状態・修正の差分がある worktree・次に打つコマンド（承認・関所に答える continue と stop・
# 拒否・続き）・報告の置き場（盤面の report.md。report の節まで済んだ後に在る）を出す。
# 4 つめを渡せば、run の worktree の git diff --binary <周の頭の版>（未追跡も入れる。P1 Task 29）を <差分の置き場>（既定は
# <対象の dir の親>）/run-<id>.diff に書き、取り込むと消えるファイルを 1 本ずつ名指しし、git apply で取り込むコマンドも出し、対象に pack の写し（.archon/workflows/works）が在って
# 修正がその .archon/ に触れていれば取り込まないよう 1 行で注意する。差分が空（起動の直後の関所など）なら書かず、前に書いた
# 同じ名のファイルを消し、取り込むコマンドも出さない（0 バイトの差分は「修正なし」に見え、取り込みを誤る）。
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
  # shellcheck disable=SC2016  # python の中の $? は、出す続きの行が打たれる殻で展開する字
  printf '%s\n' "$_row" |
    CALLER="$1" ARCHON_SH="$2" DIR="$3" BRING_BACK="${4:-}" DIFF_DIR="${5:-}" GO="$_go" REDO="$_redo" \
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
import datetime
def when(v):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(str(v), fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            pass
    return None
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
    if os.path.isdir(wp):
        base = base or subprocess.run(["git", "-C", wp, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_INDEX_FILE=os.path.join(td, "index"))
            subprocess.run(["git", "-C", wp, "read-tree", "HEAD"], env=env, capture_output=True)
            subprocess.run(["git", "-C", wp, "add", "-A"], env=env, capture_output=True)
            got = subprocess.run(["git", "-C", wp, "diff", "--cached", "--binary", base], env=env, capture_output=True)
            gone = subprocess.run(["git", "-C", wp, "diff", "--cached", "--diff-filter=D", "--name-only", "-z", base],
                                  env=env, capture_output=True, text=True).stdout.split("\0")
        empty = not got.stdout
        if empty:
            if os.path.isfile(diff):
                os.remove(diff)
            print("修正の差分: まだ無い（run の worktree と周の頭の版 {} の差が空。書く先: {}）".format(base[:12], diff))
        else:
            with open(diff, "wb") as f:
                f.write(got.stdout)
            print("修正の差分（run の worktree と周の頭の版 {} の差。未追跡も入れる）: {}".format(base[:12], diff))
        wrapped = os.path.join(os.environ.get("WORKS_WRAPS_DIR", ""), base + ".txt")
        if os.environ.get("WORKS_WRAPS_DIR") and base and os.path.isfile(wrapped):
            with open(wrapped, encoding="utf-8") as f:
                print("包んだ（wrapped）: 起動の時の対象の手元の変更・未追跡を commit {} に包んで run の基にした: {}".format(
                    base[:12], " ".join(f.read().split())))
        for p in filter(None, gone):
            print("取り込むと消えるファイル:", p)
    else:
        print("修正の差分: run の worktree（{}）が無いので書いていない".format(wp))
    if not empty:
        print("差分を元のリポジトリへ取り込む:", "git -C {} apply {}".format(shlex.quote(os.environ["BRING_BACK"]), shlex.quote(diff)))
    if os.environ.get("WORKS_USE_SH"):
        use = "sh {} {{}} {} {}".format(shlex.quote(os.environ["WORKS_USE_SH"]), shlex.quote(os.environ["DIR"]), r.get("id"))
        print("殻で取り込む（当たるかを先に見る・消す行は止まる）:", use.format("apply"))
        print("終わった run の worktree と枝を片付ける:", use.format("clean"))
    touched = False
    # 注意は対象に pack の写しが在る時だけ（自分食い・使い捨ての対象）。ほかのリポジトリの .archon/ は対象自身の物
    if os.path.isfile(diff) and os.path.isdir(os.path.join(os.environ["DIR"], ".archon", "workflows", "works")):
        with open(diff, encoding="utf-8", errors="replace") as f:
            touched = any(l.startswith(("diff --git a/.archon/", "--- a/.archon/", "+++ b/.archon/")) for l in f)
    if touched:
        print("注意: 修正が works/ でなく pack の写し（.archon/）に触れている。その部分は元のリポジトリへ取り込まない")
'
}
