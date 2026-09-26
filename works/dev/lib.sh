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

# works_dev_show_run <archon を呼ぶ殻> <対象の dir> [<差分を取り込むリポジトリ>]:
# 一番新しい darkfactory の run を引き、run id・状態・修正の差分がある worktree・次に打つコマンド（承認・拒否・続き）・
# 審査した修正の差分（fix.diff。承認して審査が終わった後に在る）を出す。3 つめを渡せば、その差分を git apply で
# 取り込むコマンドも出す。問い合わせは認証が要らないので認証を読ませない。
# 修正は対象ではなく、Archon が run ごとに切った worktree の中にある。関所の文面の「テストのログ」の行が、テストの出力のファイル。
# WORKS_DEV_HOME・WORKS_DEV_MODEL・CLAUDE_BIN_PATH を export 済みで呼ぶ。
works_dev_show_run() {
  WORKS_DEV_NO_AUTH=1 sh "$1" workflow runs --json 2>/dev/null |
    ARCHON_SH="$1" DIR="$2" BRING_BACK="${3:-}" python3 -c '
import json, os, sys
runs = [r for r in json.load(sys.stdin).get("runs", []) if r.get("workflow_name") == "darkfactory"]
if not runs:
    sys.exit("darkfactory の run が見つからない")
r = runs[0]
# 承認・続きも AI の節を回すので、認証（CLAUDE_CODE_OAUTH_TOKEN か WORKS_KEYCHAIN_ITEM）を設定した殻で打つ
go = "cd {} && WORKS_DEV_HOME={} WORKS_DEV_MODEL={} CLAUDE_BIN_PATH={} sh {} workflow".format(
    os.environ["DIR"], os.environ["WORKS_DEV_HOME"], os.environ["WORKS_DEV_MODEL"], os.environ["CLAUDE_BIN_PATH"],
    os.environ["ARCHON_SH"])
diff = os.path.join(r.get("output_root") or "", "artifacts", "runs", r.get("id") or "", "board", "fix.diff")
print("run id:", r.get("id"))
print("状態:", r.get("status"))
print("修正の差分がある worktree:", r.get("working_path"))
print("進める（承認するとその場で続きを回す）:", go, "approve", r.get("id"))
print("止める:", go, "reject", r.get("id"))
print("失敗や中断から続ける:", go, "resume", r.get("id"))
print("審査した修正の差分（承認して審査が終わった後に在る）:", diff)
if os.environ["BRING_BACK"]:
    print("差分を元のリポジトリへ取り込む:", "git -C {} apply {}".format(os.environ["BRING_BACK"], diff))
'
}
