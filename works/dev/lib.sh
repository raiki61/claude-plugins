# shellcheck shell=sh
# works/dev/lib.sh — mktarget.sh・real-run.sh・dogfood.sh が . で読む（単独では走らせない）

# works_dev_copy_pack <works の dir> <pack の dir>: works/ を project pack として写す。tests/・dev/・docs/ は除く
# （Archon はドット始まりのフォルダと、直下に YAML の無いフォルダを工程として読まない）。
# Python のバイトコードキャッシュや OS のゴミファイルは pack に残さない。
works_dev_copy_pack() {
  mkdir -p "$2"
  for _entry in "$1"/* "$1"/.[!.]*; do
    [ -e "$_entry" ] || continue
    case "$(basename "$_entry")" in
      tests | dev | docs | .git) continue ;;
    esac
    cp -R "$_entry" "$2/"
  done
  find "$2" \( -name "__pycache__" -o -name ".DS_Store" -o -name "*.pyc" \) -print0 | xargs -0 rm -rf
}

# works_dev_show_run <呼び手> <archon を呼ぶ殻> <対象の dir> [<差分を取り込むリポジトリ>]:
# 一番新しい darkfactory の run を引き、run id・状態・修正の差分がある worktree・次に打つコマンド（承認・拒否・続き）・
# 3 つめを渡せば、run の worktree の git diff --binary <周の頭の版>（未追跡も入れる。P1 Task 29）を <対象の dir の親>/run-<id>.diff に
# 書き、git apply で取り込むコマンドも出し、修正が pack の写し（.archon/）に触れていれば取り込まないよう 1 行で注意する。問い合わせは認証が要らないので認証を読ませない。
# 承認・拒否・続きのコマンドは、呼び手の WORKS_KEYCHAIN_ITEM を sh の直前に載せ、export の無い殻でもそのまま打てる形で出す。
# 修正は対象ではなく、Archon が run ごとに切った worktree の中にある。関所の文面の「テストのログ」の行が、テストの出力のファイル。
# WORKS_DEV_HOME・WORKS_DEV_MODEL・CLAUDE_BIN_PATH を export 済みで呼ぶ。
works_dev_show_run() {
  WORKS_DEV_NO_AUTH=1 sh "$2" workflow runs --json 2>/dev/null |
    CALLER="$1" ARCHON_SH="$2" DIR="$3" BRING_BACK="${4:-}" python3 -c '
import json, os, shlex, subprocess, sys
runs = [r for r in json.load(sys.stdin).get("runs", []) if r.get("workflow_name") == "darkfactory"]
if not runs:
    sys.exit(os.environ["CALLER"] + ": darkfactory の run が見つからない")
r = runs[0]
# 承認・続きも AI の節を回すので認証が要る。変数の代入はその単純コマンドにだけ掛かるので、cd の後・sh の直前に置く。
# 呼び手が WORKS_KEYCHAIN_ITEM で回したなら項目名（秘密ではない）を載せ、そのまま打てば通るようにする。
# トークン（CLAUDE_CODE_OAUTH_TOKEN）だけで回したなら値は出さず、export した殻で打つよう 1 行で案内する。
# 包みを入れた run（WORKS_DEV_ADAPTER=1）は続きのコマンドにも付ける（archon.sh は認証を使う実行のたびに設定を書き直す）
item = os.environ.get("WORKS_KEYCHAIN_ITEM", "")
auth = "WORKS_KEYCHAIN_ITEM={} ".format(shlex.quote(item)) if item else ""
adapter = "WORKS_DEV_ADAPTER=1 " if os.environ.get("WORKS_DEV_ADAPTER") == "1" else ""
go = "cd {} && {}WORKS_DEV_HOME={} WORKS_DEV_MODEL={} CLAUDE_BIN_PATH={} {}sh {} workflow".format(
    shlex.quote(os.environ["DIR"]), auth, shlex.quote(os.environ["WORKS_DEV_HOME"]),
    shlex.quote(os.environ["WORKS_DEV_MODEL"]), shlex.quote(os.environ["CLAUDE_BIN_PATH"]),
    adapter, shlex.quote(os.environ["ARCHON_SH"]))
board = os.path.join(r.get("output_root") or "", "artifacts", "runs", r.get("id") or "", "board")
wp = r.get("working_path") or ""
print("run id:", r.get("id"))
print("状態:", r.get("status"))
print("修正の差分がある worktree:", r.get("working_path"))
if not item:
    print("認証: 下の 3 つは CLAUDE_CODE_OAUTH_TOKEN を export した殻で打つ（値は出さない。keychain なら WORKS_KEYCHAIN_ITEM=<項目名> を sh の直前に足す）")
print("進める（承認するとその場で続きを回す）:", go, "approve", r.get("id"))
print("止める:", go, "reject", r.get("id"))
print("失敗や中断から続ける:", go, "resume", r.get("id"))
if os.environ["BRING_BACK"]:
    # 修正の差分は run の worktree の今の姿と周の頭の版（start の控え r<N>/start.json の base_rev）の差（未追跡も入れる。
    # 盤面の fix.diff は審査の段の物で、手直しの後の姿を持たないので読まない）。一時の index で数え、worktree の index は動かさない
    import glob, tempfile
    base = ""
    for p in sorted(glob.glob(os.path.join(board, "r*", "start.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                base = json.load(f).get("base_rev") or base
        except (OSError, ValueError):
            pass
    diff = os.path.join(os.path.dirname(os.path.abspath(os.environ["DIR"])), "run-{}.diff".format(r.get("id")))
    if os.path.isdir(wp):
        base = base or subprocess.run(["git", "-C", wp, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ, GIT_INDEX_FILE=os.path.join(td, "index"))
            subprocess.run(["git", "-C", wp, "add", "-A"], env=env, capture_output=True)
            got = subprocess.run(["git", "-C", wp, "diff", "--cached", "--binary", base], env=env, capture_output=True)
        with open(diff, "wb") as f:
            f.write(got.stdout)
        print("修正の差分（run の worktree と周の頭の版 {} の差。未追跡も入れる）: {}".format(base[:12], diff))
    else:
        print("修正の差分: run の worktree（{}）が無いので書いていない".format(wp))
    print("差分を元のリポジトリへ取り込む:", "git -C {} apply {}".format(shlex.quote(os.environ["BRING_BACK"]), shlex.quote(diff)))
    touched = False
    if os.path.isfile(diff):
        with open(diff, encoding="utf-8", errors="replace") as f:
            touched = any(l.startswith(("diff --git a/.archon/", "--- a/.archon/", "+++ b/.archon/")) for l in f)
    if touched:
        print("注意: 修正が works/ でなく pack の写し（.archon/）に触れている。その部分は元のリポジトリへ取り込まない")
'
}
