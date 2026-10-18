#!/usr/bin/env bash
# 配布物の検証。CI と手元で同じものを回す（/review-loop の P0-2 が「CI のテスト・lint を
# ローカル実行し緑を確認」を要求するので、その実体がこれ）。
#
# set -e は使わない——各ケースの終了コードを検査するのが目的で、
# 非ゼロで即死すると検査そのものが成立しない。
#
# graphloops の engine が起動した子（役・任せ先・書く子。環境に GRAPHLOOPS_ENGINE_CHILD が立つ）からは走らせない——人の方針
# 『テスト（今だけ）』: 手元で e2e の一式を回さない（CI で回す）。宣言の deny は sh -c や絶対パスの呼びに当たらないので入口でも拒む。
# 方針を解くときにこの段を消す（docs/adr/0069-engine-launches-skill-node-and-lanes.md の結果）
if [ -n "${GRAPHLOOPS_ENGINE_CHILD:-}" ]; then
    echo "tests/run.sh: engine が起動した子からは走らせない（人の方針: 手元で e2e の一式を回さない。CI で回る）——手元は pytest の一式か、変更に関わる筋書きを GL_TEST_ONLY で数件" >&2
    exit 2
fi
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CL="$ROOT/convergence-loops"   # convergence-loops の置き場（marketplace.json の source が指す）
# 置き場は TMPDIR から明示で取る——macOS の mktemp -d（型なし）は TMPDIR を見ずに利用者の一時ディレクトリ（/var/folders/…）へ
# 作る（実測 2026-09-25・macOS 26.6.2）。engine が sandbox の中で起動する役（investigator）が書けるのは TMPDIR だけなので、
# 型なしのままだとこの台本が mkdtemp の Operation not permitted で崩れる
WORK="$(mktemp -d "${TMPDIR:-/tmp}/run.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

PY_BIN=$(command -v python3 || command -v python || true)
[ -n "$PY_BIN" ] || { echo "python3 / python が PATH に無い"; exit 2; }
# **この中の Python 検査は判定を `assert` に載せている。** `PYTHONOPTIMIZE`（`python -O` 相当）が
# 効いていると `assert` が 1 つ残らず消え、**全部が無条件に緑になる**。環境変数 1 つで検証が
# 丸ごと空振りする形なので、外して、外れたことを確かめる。
unset PYTHONOPTIMIZE
# **組（shard）の指定は graphloops の 1 検査にだけ渡す。** CI の組の job が段の env で渡すが、環境に残すと、写しの上で
# graphloops/tests/run.sh や台本を起動する他の検査（tests/mutate.py の実行器ほか）まで組の回になって名簿を汚す
GL_SHARD_ENV=()
for v in GL_SHARD_TOTAL GL_SHARD_INDEX GL_SHARD_GROUP GL_SHARD_MANIFEST; do
    [ -n "${!v+x}" ] && GL_SHARD_ENV+=("$v=${!v}")
    unset "$v"
done
# 止める猶予の環境変数（graphloops/engine/role_run.py の GRACE_ENV）は外して走る——外の土台の下で engine がこの一式を
# 走らせると値を継ぎ、既定の 5 秒を前提に子を止める検査がその下でだけ崩れる（読めない値なら engine の import で全部落ちる）
unset GL_KILL_GRACE
# Claude Code の会話の中で回すと、会話の入口(cli・sdk-cli)と会話の一時の置き場を継ぐ。gates の手元の文書の初見読みは
# これで親の Stop を待って読むか裏で読むか・どこを一時の置き場と見るかを変えるので、外して CI と同じ前提で走る(要る検査は自分で渡す)
unset CLAUDE_CODE_ENTRYPOINT CLAUDE_JOB_DIR
# **番人自身に `assert` を使うな。** 最適化が効いていると `assert __debug__` ごと消えるので、
# 番人が常に通る（実測: この形で書いたとき、最適化を効かせた写しが 529 件すべて緑になった）。
# 検査したい当のものを、検査のツールに使わない——値を印字して外から見る。
# 版も見る。Python 2 だと f-string が構文エラーになり、終了コード 1（＝「阻害要因あり」）で
# 落ちて、壊れているのか未収束なのかが区別できない——契約の 3 値が 1 つ潰れる。
"$PY_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 6) else 1)' 2>/dev/null || {
    echo "$PY_BIN が Python 3.6 未満——この検査一式は f-string を使うので構文エラーになり、"
    echo "終了コード 1（阻害要因あり）と区別が付かない。python3 を PATH に入れてから走らせろ"
    exit 2
}
[ "$("$PY_BIN" -c 'print(__debug__)' 2>/dev/null)" = "True" ] || {
    echo "assert が無効（PYTHONOPTIMIZE か -O）——この検査一式は判定を assert に載せているので、"
    echo "このまま走らせると全件緑になる。無効化を外してから走らせろ"
    exit 2
}

fail=0
ran=0
# **環境で走れなかった検査（見送り）は合格と別に数える。** 各台本は見送りを 1 行ずつ「  ok   <検査> # SKIP <能力>: <理由>」
# （TAP 14 の SKIP 指示子。説明文の頭に欠けた能力の名前。Python の側の正本は graphloops/tests/parallel.py の skip_line）で出すだけで、
# 拾う・数える・一覧にする・名前で許すか決めて FAIL_ON_SKIP=1 で失敗に数えるのはここ 1 か所——層ごとに一覧を作ると同じ見送りを二重に数える。
# 合格と同じ「ok」だけで出していたとき、ツールや OS の機能の無い CI は走らないまま緑になり、止める口が無かった
SKIP_MARK=' # SKIP'
SKIPS=()
note_skips() {
    [[ "$1" == *"$SKIP_MARK"* ]] || return 0
    local l
    while IFS= read -r l; do
        l=${l%$'\r'}   # Windows の Python の出力の CRLF（expect_output を通らない呼びもここに来る）
        [[ "$l" == "  ok   "*"$SKIP_MARK"* ]] && SKIPS+=("${l#  ok   }")
    done <<< "$1"
}
# 拾った見送りの行から能力の名前を出す。名前の形（小文字・数字・-）でなければ空——名前の無い見送りは許しようが無いので、
# FAIL_ON_SKIP=1 の下では必ず失敗に数える（名前の打ち間違いも同じく失敗に倒れる）
skip_capability() {
    local rest=${1#*"$SKIP_MARK"}
    rest=${rest# }
    [[ "$rest" == *:* ]] || return 0
    local cap=${rest%%:*}
    [[ "$cap" =~ ^[a-z0-9][a-z0-9-]*$ ]] && printf '%s' "$cap"
}
# どの OS で見送りを許すかは実装側で決めない——CI の定義か人が渡す
report_skips() {
    [ "${#SKIPS[@]}" -gt 0 ] || return 0
    local list=${SKIP_ALLOW:-} allow=() s cap a allowed denied=0
    list=${list//$'\n'/ }
    read -ra allow <<< "${list//,/ }"
    echo "見送り ${#SKIPS[@]} 件（この環境で走らなかった検査。FAIL_ON_SKIP=1 で、SKIP_ALLOW に能力の名前が無いものを失敗に数える）:"
    for s in "${SKIPS[@]}"; do
        cap=$(skip_capability "$s"); allowed=0
        if [ -n "$cap" ]; then
            for a in ${allow[@]+"${allow[@]}"}; do [ "$a" = "$cap" ] && allowed=1; done
        fi
        if [ "$allowed" = 1 ]; then
            echo "  - ${s}（SKIP_ALLOW で許した）"
        else
            echo "  - $s"
            denied=$((denied + 1))
        fi
    done
    if [ "${FAIL_ON_SKIP:-}" = 1 ] && [ "$denied" -gt 0 ]; then
        echo "見送りを失敗に数えた: $denied 件（FAIL_ON_SKIP=1。SKIP_ALLOW に無い能力か、名前の無い見送り）"
        fail=1
    fi
}

# 出力と終了コードの**両方**を検査する。終了コードを見ないと、対象が異常終了しても
# そのエラーメッセージが期待文字列を偶然含んでいれば ok になる（fail-open）。
# REVIEW.md のコード衛生観点が「検査自体が実行不能に終わったとき赤くなるか」を
# 要求しているので、それを配るスイート自身が満たしていなければならない。
#
# **期待メッセージを指定できることが要件。** スクリプトは末尾の例外境界で想定外の例外も
# exit 2 に倒すので、終了コードだけを見る検査は個別の型検査を消しても緑のまま通る
# （＝恒真）。どの検査が発火したかはメッセージでしか区別できない。
# 出力を見ないことが意図の呼び出しが渡す番兵。空文字を「見ない」の合図に使うと、
# 表の行から `|` が落ちて空文字で来たものと区別が付かない。
ANY_OUTPUT='__any_output__'

expect_output() {
    local want_exit=$1 want=$2 desc=$3
    shift 3
    # **期待メッセージが空の呼び出しをここで赤にする。** 空だと下の部分一致が恒真になり、
    # 終了コードだけを見る検査に静かに退化する（冒頭のとおり、その形は個別の検査を消しても
    # 緑のまま通る）。表駆動のループは 9 箇所あって、どの行から `|` が落ちても必ず空文字で
    # ここへ来る——**ガードを入口ごとに書き足すのでなく、全部が通るこの 1 本に持たせる**
    # （入口の片方だけを塞いで残りから通られたのが、この差分が 2 周かけて直した形である）。
    if [ -z "$want" ]; then
        echo "  FAIL $desc — 期待メッセージが空（表の行から | が落ちていないか）"
        fail=1; ran=$((ran + 1)); return
    fi
    local got
    got=$("$@" 2>&1)
    local got_exit=$?
    # **CRLF は差ではない。** 複数行の期待文字列（$'…\n…'）が windows でだけ 1 件も一致しなくなる
    # ので、CRLF を畳んでから比べる（実測 2026-09-16: これで記録レンズの 2 件が緑になった。中身は
    # 同じで、見えない \r が行末に付いていた）。**なぜ \r が付くかは未確定**——「Windows の Python は
    # 標準出力の \n を \r\n にする」だけでは、同じ python の出力を行末アンカーの sed で拾っている
    # graphloops/tests/run.sh が windows で緑なことを説明できない。CR を全部落とすのではなく CRLF
    # だけを畳むのは、行の中に \r が残ること自体を見ている腕（CRLF で届く本文の検査）を消さないため。
    # 末尾の 1 つは別に見る（$() が改行を落とした後なので \r だけが残る）。**後置パターン除去
    # `${got%…}` は使わない**——bash では文字列長の 2 乗で効き、出力の大きい 1 ケースだけで 200ms
    # 使っていた（実測: 35,803 字で 201ms → 0.5ms）。
    got=${got//$'\r'$'\n'/$'\n'}
    case $got in *$'\r') got=${got:0:${#got} - 1};; esac
    ran=$((ran + 1))
    note_skips "$got"
    # **赤の行は検査の名前と食い違いだけにし、捕った出力は次の行から貼る。** 同じ行に続けると、出力の
    # 1 行目（多くは先に走った台本の見出し）が赤の中身に読める（実測: 0.21.4 の取りまとめ）。字下げしない
    # のは、行頭の「  FAIL 」で名前を拾う tests/mutate.py の読み方を、今までの 2 行目以降と同じに保つため
    if [ "$got_exit" != "$want_exit" ]; then
        echo "  FAIL $desc — exit $want_exit を期待したが $got_exit$(got_where "$got")"
        [ -n "$got" ] && printf '%s\n' "$got"
        fail=1
    elif [ "$want" = "$ANY_OUTPUT" ] || [[ "$got" == *"$want"* ]]; then
        echo "  ok   $desc"
    else
        echo "  FAIL $desc — 出力に '$want' が無い$(got_where "$got")"
        [ -n "$got" ] && printf '%s\n' "$got"
        fail=1
    fi
}

got_where() {
    if [ -n "$1" ]; then echo "（出力は下の行）"; else echo "（出力は空）"; fi
}

# 終了コードだけを見る検査。`expect_output` に番兵を渡して委譲する（実行・集計・出力整形を二重に持たない。番兵の理由は上の定義位置）。
expect_exit() {
    local want=$1 desc=$2
    shift 2
    expect_output "$want" "$ANY_OUTPUT" "$desc" "$@"
}

# **空期待ガード自身の腕。** このガードは表駆動ループ 9 箇所すべての恒真化を 1 本で塞いで
# いるのに、それを守るものが何も無かった——検査を守る最後の 1 枚を誰も守っていない形で、
# この差分が 3 周かけて直してきたものと同じである。**副シェルで呼ぶ**——本体の fail / ran を
# 汚さずに、ガードの出力と副作用（実行せずに 1 件だけ赤で数える）だけを見る。
guard_probe=$( fail=0; ran=0; expect_output 2 "" "空期待の番人（この行の出力を検査する）" true
               printf '|ran=%s|fail=%s' "$ran" "$fail" )
ran=$((ran + 1))
case "$guard_probe" in
    *"期待メッセージが空"*"|ran=1|fail=1")
        echo "  ok   期待メッセージが空の呼び出しは、対象を実行せずに赤くなる（恒真に退化しない）" ;;
    *)
        echo "  FAIL 期待メッセージが空の呼び出しが赤にならない: $guard_probe"
        fail=1 ;;
esac

# **赤の行の形の腕。** 赤の 1 行目に捕った出力の本文が続かず、本文は次の行から行頭で出る。副シェルで本体を汚さない。
fail_probe=$( fail=0; ran=0
              expect_output 1 "x" "終了コードの腕" printf '別の台本の見出し\n'
              expect_output 0 "無い語" "出力の腕" printf '別の台本の見出し\n'
              expect_output 1 "x" "空の腕" true )
ran=$((ran + 1))
want_probe=$'  FAIL 終了コードの腕 — exit 1 を期待したが 0（出力は下の行）\n別の台本の見出し\n'
want_probe+=$'  FAIL 出力の腕 — 出力に \'無い語\' が無い（出力は下の行）\n別の台本の見出し\n'
want_probe+='  FAIL 空の腕 — exit 1 を期待したが 0（出力は空）'
if [ "$fail_probe" = "$want_probe" ]; then
    echo "  ok   赤の行は検査の名前と食い違いだけで、捕った出力は次の行から出る"
else
    echo "  FAIL 赤の行の形が違う（出力は下の行）"
    printf '%s\n' "$fail_probe"
    fail=1
fi

# **見送りの拾い手自身の腕。** 行頭が「  ok   」で印を含む行だけを拾い（理由の無い印も拾う——拾い損ねは合格に化ける）、
# 行の途中の印は拾わない。副シェルで本体を汚さない。
# 引数: FAIL_ON_SKIP・SKIP_ALLOW・台本の出力（見送りの行の並び）。返り: |拾った件数|fail|失敗に数えた件数|許した印の件数|拾った行
skip_probe() {
    ( SKIPS=(); fail=0; ran=0; FAIL_ON_SKIP=$1; SKIP_ALLOW=$2
      expect_output 0 "終わり" "見送りの拾い手の腕" printf '%s終わり\n' "$3" >/dev/null
      report_skips > "$WORK/skip-probe.out"
      rep=$(cat "$WORK/skip-probe.out")
      denied=0
      [[ "$rep" =~ 失敗に数えた:\ ([0-9]+)\ 件 ]] && denied=${BASH_REMATCH[1]}
      marked=$(grep -c "（SKIP_ALLOW で許した）" "$WORK/skip-probe.out")
      printf '|n=%s|fail=%s|denied=%s|allowed=%s|%s' "${#SKIPS[@]}" "$fail" "$denied" "$marked" "${SKIPS[*]}" )
}
skip_in=$'  ok   甲 # SKIP 理由\n  ok   乙\nx  ok   丙 # SKIP fifo: 理由\n  ok   丁 # SKIP\n  ok   戊 # SKIP fifo: 理由\n  ok   己 # SKIP sh: 理由\n  ok   庚 # SKIP Fifo: 理由\n  ok   辛 # SKIP symlink: 理由\n'
skip_all="甲 # SKIP 理由 丁 # SKIP 戊 # SKIP fifo: 理由 己 # SKIP sh: 理由 庚 # SKIP Fifo: 理由 辛 # SKIP symlink: 理由"
skip_off=$(skip_probe "" "" "$skip_in")                 # 既定: 一覧に出すだけ
skip_on=$(skip_probe 1 "" "$skip_in")                   # 一覧が空: 全部を失敗に数える
skip_part=$(skip_probe 1 "fifo, sh,Fifo" "$skip_in")    # 許した名前だけ除く。名前無し・形でない名前（一覧に在っても Fifo）・一覧に無い名前は失敗
skip_off_allow=$(skip_probe "" "fifo,sh" "$skip_in")    # 一覧だけ渡しても FAIL_ON_SKIP が無ければ失敗にしない
skip_ok=$(skip_probe 1 "sh fifo" $'  ok   戊 # SKIP fifo: 理由\n  ok   己 # SKIP sh: 理由\n')   # 全部許せば緑
ran=$((ran + 1))
if [ "$skip_off" = "|n=6|fail=0|denied=0|allowed=0|$skip_all" ] && [ "$skip_on" = "|n=6|fail=1|denied=6|allowed=0|$skip_all" ] \
    && [ "$skip_part" = "|n=6|fail=1|denied=4|allowed=2|$skip_all" ] && [ "$skip_off_allow" = "|n=6|fail=0|denied=0|allowed=2|$skip_all" ] \
    && [ "$skip_ok" = "|n=2|fail=0|denied=0|allowed=2|戊 # SKIP fifo: 理由 己 # SKIP sh: 理由" ]; then
    echo "  ok   見送りの行は行頭の印で拾われ、既定では失敗にせず、FAIL_ON_SKIP=1 のとき SKIP_ALLOW に能力の名前が無い見送りだけを失敗に数える"
else
    echo "  FAIL 見送りの拾い手が期待と違う: 既定 $skip_off / 一覧が空 $skip_on / 一部許す $skip_part / 一覧だけ $skip_off_allow / 全部許す $skip_ok"
    fail=1
fi
# Python の台本の見送りの行（graphloops/tests/parallel.py の skip_line）が、ここの拾い手の印と能力の名前の形に当たる——片方だけ
# 変えると、見送りが一覧から黙って消えて合格に化けるか、名前が読めずに許しの一覧が効かなくなる
skip_py=$( SKIPS=(); note_skips "$(PYTHONIOENCODING=utf-8 "$PY_BIN" -c 'import sys; sys.path.insert(0, sys.argv[1]); import parallel; print(parallel.skip_line("検査", "fifo", "理由"))' "$ROOT/graphloops/tests" 2>&1)"
           printf '|n=%s|%s|cap=%s' "${#SKIPS[@]}" "${SKIPS[*]}" "$(skip_capability "${SKIPS[0]:-}")" )
ran=$((ran + 1))
if [ "$skip_py" = "|n=1|検査 # SKIP fifo: 理由|cap=fifo" ]; then
    echo "  ok   Python の台本の見送りの行（parallel.skip_line）を、root の拾い手が 1 件として拾い、能力の名前を読む"
else
    echo "  FAIL Python の台本の見送りの行を root の拾い手が拾えないか、能力の名前が読めない: $skip_py"
    fail=1
fi

# **数えるだけの回（TESTS_COUNT_ONLY=1）。** 検査を走らせずに件数だけを数え、下の件数の基準（EXPECTED_CHECKS）だけを当てる。
# メインブランチに入れるコマンドのゲート（tests/count-fences.sh）が回す。検査を足して件数の基準を上げ忘れた変更が、メインブランチに入った後の CI で初めて
# 赤になる形が、別々の部署で続いた（2026-10-16 に 3 件。e43b0a39・46fbcc99 と graphloops の 9f9da74e）。検査の間の下ごしらえは
# 今までどおり走るので、件数は全部を回した回と同じになる（揃いは下の COUNT_ONLY_OK が縛る）。ここより上の番人の腕は
# expect_output 自身を検査するので、差し替えはその後に置く
if [ "${TESTS_COUNT_ONLY:-}" = 1 ]; then
    expect_output() { ran=$((ran + 1)); }
fi

# 記録の一部を壊した JSON を**まとめて 1 プロセスで**書き出す。「壊すと落ちる」ことまで
# 確かめないと、検証が空振りしても合格になる（fail-open）。
#
# **束ねてよいのは素材の生成だけ。** 検査そのものはケースごとに分けたまま——合否が個別に
# 報告されることが要件で、束ねると失敗の切り分けができなくなる。生成を 1 ケース 1 プロセスに
# すると Python の起動コストだけで 26 秒かかる（実測。まとめて 1.2 秒）。
write_broken_records() {
    "$PY_BIN" - "$ROOT" "$WORK" <<'PY'
import json, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

# 手書きの deep copy を 1 本に寄せる（同じ形が 20 箇所に散っていた）。`copy.deepcopy` でなく
# JSON 往復にするのは、**JSON にできない値をここで落とすためではなく、そこで失敗させるため**
# ——固定具は記録として書き出されるので、JSON 化できない値が混ざったら複製の時点で
# TypeError で止まる方がよい（deepcopy は通してしまい、書き出しの段で初めて落ちる）。
def clone(x):
    return json.loads(json.dumps(x))

root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
templates = {
    n: json.loads((root / "convergence-loops" / f"templates/{n}.example.json").read_text(encoding="utf-8"))
    for n in ("round-1", "round-2", "round-3")
}


def defer_unit(rec):
    return next(u for u in rec["units"] if u.get("disposition") == "defer")


# 値を書き換えるだけの mutation（round-2 を壊し、round-1 と突合する）。個別のフィールドの検査を発火させる。
VALUE = {
    "drop-material": lambda r: r["materials"].pop("hygiene"),
    "drop-defer-reason": lambda r: defer_unit(r).pop("reason"),
    "drop-base": lambda r: r.pop("base"),
    "drop-round": lambda r: r.pop("round"),
    "bad-base": lambda r: r.update(base="1" * 40),
    "bad-round": lambda r: r.update(round=9),
    "bad-status": lambda r: r["materials"]["hygiene"].update(status="probably-fine"),
    "clean-without-checked": lambda r: r["materials"]["hygiene"].pop("checked"),
    # ラベルと key の検査は、消えても記録が「阻害要因なし（exit 0）」で通ってしまう
    # ——[block] が黙って数えられなくなる、このツールの存在理由そのものの穴。
    "bad-label": lambda r: r["units"][0].update(label="blocker"),
    "drop-key": lambda r: r["units"][0].pop("key"),
    # R1〜R4 の verdict。フィールドごと無い・1 つ欠ける・語彙外・役に許されない値。
    "drop-reviews": lambda r: r.pop("reviews"),
    "drop-review-R3": lambda r: r["reviews"].pop("R3"),
    "bad-review-status": lambda r: r["reviews"]["R1"].update(status="looks-fine"),
    "review-only-R2": lambda r: r["reviews"]["R1"].update(status="premise-invalid"),
    "review-only-R34": lambda r: r["reviews"]["R1"].update(status="not_applicable"),
    "pass-without-reason": lambda r: r["reviews"]["R3"].pop("reason"),
    # 持ち越し。from_round が無い・今ラウンド以降を指す・前ラウンドに判定が無い素材から持ち越す。
    "carry-without-from": lambda r: r["materials"]["prior_decisions"].pop("from_round"),
    "carry-from-future": lambda r: r["materials"]["prior_decisions"].update(from_round=2),
    "carry-from-not-applicable": lambda r: r["materials"]["procedure_trace"].update(
        status="carried_over", from_round=1, reason="前と同じ"
    ),
}
# 「型が違う」系。値の書き換えだけでは個別の型検査が一度も発火しない。
TYPE = {
    "bad-round-type": lambda r: r.update(round="2"),
    "bad-round-bool": lambda r: r.update(round=True),
    "round-below-one": lambda r: r.update(round=-100),
    "bad-materials-type": lambda r: r.update(materials=[]),
    "bad-units-type": lambda r: r.update(units={}),
    "bad-unit-type": lambda r: r["units"].__setitem__(0, "not-an-object"),
    "bad-reviews-type": lambda r: r.update(reviews=[]),
    "bad-from-round-type": lambda r: r["materials"]["prior_decisions"].update(from_round="1"),
}
# 個別の検査を通り抜け、末尾の例外境界だけが受け止めるもの。
BOUNDARY = {
    "bad-scalars-type": lambda r: r.update(scalars=["oops"]),
    # `"scalars": null` は JSON として正当なので、falsy 正規化をやめた後は境界の
    # 「想定外の例外」に倒れていた。書き手に何を直せばよいかを伝える診断が要る。
    "null-scalars": lambda r: r.update(scalars=None),
    "unhashable-status": lambda r: r["materials"]["hygiene"].update(status=["found"]),
}


def write(name, rec, num=2, prevs=None):
    """壊した記録を、記録のディレクトリ 1 つとして書き出す（入口はディレクトリだけ）。

    前のラウンドを無傷のテンプレートで埋めるのは、突合（base の一致・持ち越しの連鎖・
    defer 台帳・残存）を発火させる mutation があるため。`prevs` を渡すとその番号だけ差し替える。
    round フィールドそのものを壊した mutation も、ファイル名は round-<num> に置く——load_dir が
    「ファイル名の番号と中身の round が違う」で落とす前に validate が走るので、狙った検査は
    変わらず発火する。
    """
    d = work / name
    d.mkdir(exist_ok=True)
    for i in range(1, num):
        r = (prevs or {}).get(i, templates[f"round-{i}"])
        (d / f"round-{i}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    (d / f"round-{num}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


for name, mutate in {**VALUE, **TYPE, **BOUNDARY}.items():
    rec = clone((templates["round-2"]))
    mutate(rec)
    write(name, rec)

# 最上位が object でない記録は mutate 関数の形（rec を書き換える）に乗らないので別に書く。
write("not-object", ["not", "an", "object"], num=1)

# 突合（集合演算）は prev だけを走査するので、前ラウンド側の記録を壊す必要がある。
prev = clone((templates["round-1"]))
prev["units"][0]["key"] = ["not", "a", "string"]
write("unhashable-key", templates["round-2"], prevs={1: prev})

# round-1 単独。初回に持ち越しは書けない（from_round が指せるラウンドが無い）。
r1 = clone((templates["round-1"]))
r1["reviews"]["R1"].update(status="carried_over", from_round=1, reason="前と同じ")
write("r1-carry", r1, num=1)

# round-3 を壊し、round-2 と突合する——連鎖・defer 台帳・P-R の飛ばし・停止条件は
# 2 ラウンド目以降の記録でしか発火しない。
def r3(mutate):
    rec = clone((templates["round-3"]))
    mutate(rec)
    return rec

deferred_key = defer_unit(templates["round-2"])["key"]
for name, mutate in {
    # 前ラウンドが round 1 から持ち越しているのに、今ラウンドが round 2 からと書く。
    "carry-chain-broken": lambda r: r["materials"]["prior_decisions"].update(from_round=2),
    # R1 は「台帳に問いが載った周」なので round-3 の実例では pass。持ち越しの連鎖は R2 で見る。
    "review-carry-chain-broken": lambda r: r["reviews"]["R2"].update(from_round=1),
    # 前ラウンドで defer と確定したキーが、新証拠なしに [block] へ上がる。
    "reopen-without-evidence": lambda r: defer_unit(r).update(label="block"),
    # 新証拠つきの再審は記録として正しく、阻害要因（exit 1）として出る。
    "reopen-with-evidence": lambda r: defer_unit(r).update(
        label="block", reopen_evidence="本番ログで上限超過のクエリを 3 件観測"
    ),
    # 阻害要因ゼロなのに R3 が未実施——P-R を飛ばした形。
    "skip-PR": lambda r: r["reviews"]["R3"].update(status="not_applicable", reason="到達せず"),
    "redesign": lambda r: r["reviews"]["R2"].update(status="redesign-needed", reason="機構の規模が実態に対して大きい"),
    # 人に諮る verdict は台帳に問いとして載っていること（載っていない形は q-review-unlisted）。
    "premise-invalid": lambda r: (r["reviews"]["R2"].update(status="premise-invalid", reason="1 デプロイ 1 リポジトリなので記録する問いが無い"),
        r["questions"].append({"key": "解くべき問いが立っているか", "kind": "premise", "origin": "R2",
                               "status": "held", "reason": "judge が仮定を検算中"})),
    "unverifiable": lambda r: (r["reviews"]["R2"].update(status="unverifiable", reason="目的テキストの出典が無い"),
        r["questions"].append({"key": "元の目的をどこから取るか", "kind": "unverifiable", "origin": "R2",
                               "status": "held", "reason": "出典が無い"})),
    "review-not-run": lambda r: r["reviews"]["R4"].update(status="not_run", reason="時間切れ"),
    # 前ラウンドの [block] キーがそのまま残る（stuck）。3 周続くので台帳への記載も要る（無い形は q-stuck-unlisted）。
    "stuck": lambda r: (r["units"].append({"key": templates["round-1"]["units"][0]["key"], "label": "block"}),
        r["questions"].append({"key": "分岐の統合が 2 周直しても残る——処方の誤りか設計か", "kind": "stuck",
                               "origin": templates["round-1"]["units"][0]["key"], "status": "held",
                               "reason": "2 周連続で残った"})),
    # defer のキーが今ラウンドの記録から消えた——台帳には残ることを出力で知らせる。
    "defer-dropped": lambda r: r["units"].remove(defer_unit(r)),
    # 素材の「人の起動待ち」「やるべきだったが飛ばした」。このループが塞いだと主張する穴
    # （無言の省略を「なし」と誤認する）の当の腕で、記録の実例が 1 件も無かった。
    "material-awaiting": lambda r: (r["materials"]["consistency"].update(
        status="awaiting_human", reason="grader が権限エラーで起動できなかった"),
        r["questions"].append({"key": "整合性の grader を誰が起動するか", "kind": "awaiting",
                               "origin": "consistency", "status": "held", "reason": "権限エラー"})),
    "material-not-run": lambda r: r["materials"]["hygiene"].update(
        status="not_run", reason="時間切れで飛ばした"),
    # 同じ key が 1 ラウンドに 2 つ在ると、履歴も台帳も後勝ちで潰れる。
    "dup-key": lambda r: r["units"].append(clone((r["units"][0]))),
    # 「見つけた」と書いた素材が在るのに units が空。
    "found-no-units": lambda r: (
        r["materials"]["local_review"].update(
            status="found", count=3, detail="欠陥レビューが 3 件返した"),
        r["units"].clear(),
        # units を空にすると、今ラウンドに初出の defer（split の origin）は台帳にも無くなる。
        # 見たいのは「found なのに units が空」なので、その問いだけ外す（前ラウンドから
        # 続く fork は defer 台帳に origin が在るので残せる）。
        r["questions"].__setitem__(slice(None), [q for q in r["questions"] if q["kind"] != "split"])),
}.items():
    # stuck は round-2 側にも同じ [block] が在ることが前提なので、そこだけ差し替える。
    r2 = clone((templates["round-2"]))
    r2["units"].append({"key": templates["round-1"]["units"][0]["key"], "label": "block"})
    write(name, r3(mutate), num=3, prevs={2: r2} if name == "stuck" else None)

# 問いの台帳（1 ラウンド内）。何が不正かは下の CASES 表と review-record.py の診断文が持つ。
def add_q(r, **q):
    r["questions"].append(q)
# このセクションと、下の周またぎのセクションの両方で使う（同じ値を 2 度定義しない）。
BK = "src/api/limit.py:apply — 上限が効かない"
NIT_KEY = next(u["key"] for u in templates["round-2"]["units"] if u["label"] == "nit")
for name, mutate in {
    "q-split-on-do-now": lambda r: (add_q(r, key="別 PR に積むか", kind="split", origin=defer_unit(r)["key"],
                                          status="held", reason="目的の外"),
                                    defer_unit(r).update(disposition="do-now")),
    # do-now でなく **label が block** の腕。上の q-split-on-do-now は suggest/do-now しか通さない。
    "q-split-on-block": lambda r: (r["units"].append({"key": BK, "label": "block"}),
        add_q(r, key="別 PR に積むか", kind="split", origin=BK, status="held", reason="目的の外")),
    "q-bad-kind": lambda r: add_q(r, key="x", kind="skip", origin=NIT_KEY, status="held", reason="r"),
    "q-bad-status": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="pending", reason="r"),
    "q-without-reason": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held"),
    "q-fork-one-option": lambda r: add_q(r, key="x", kind="fork", origin=defer_unit(r)["key"],
                                         status="held", reason="r", options=["(A) だけ"]),
    "q-resolved-without-resolution": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY,
                                                     status="resolved", reason="r"),
    "q-origin-missing": lambda r: add_q(r, key="x", kind="fork", origin="src/none.py — 無い",
                                        status="held", reason="r", options=["(A) a", "(B) b"]),
    "q-awaiting-unlisted": lambda r: (r["questions"].clear(),
        r["materials"]["main_path_observation"].update(status="awaiting_human", reason="実機が要る")),
    "q-awaiting-origin-clean": lambda r: add_q(r, key="x", kind="awaiting", origin="hygiene", status="held", reason="r"),
    "q-review-unlisted": lambda r: r["reviews"]["R1"].update(status="unverifiable", reason="出典が無い"),
    "q-premise-origin-mismatch": lambda r: add_q(r, key="x", kind="premise", origin="R2", status="held", reason="r"),
    "q-dup-key": lambda r: (add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held", reason="r"),
                            add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held", reason="r")),
    "q-legacy-ask-human": lambda r: next(u for u in r["units"] if u["label"] == "nit").update(ask_human="rule", reason="r"),
    "q-not-list": lambda r: r.update(questions={}),
    "q-drop": lambda r: r.pop("questions"),
    # 以下は 0.28 で足した検査のうち、腕が無かったもの。腕が無いと、検査を消しても全件緑になる
    # （実測で 6 本がそうだった）。どれも「記録を静かに間違わせる」向きなので、1 本ずつ赤を見る。
    "q-not-object": lambda r: r["questions"].append("問い"),
    "q-no-key": lambda r: add_q(r, kind="rule", origin=NIT_KEY, status="held", reason="r"),
    "q-empty-reason": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held", reason=""),
    "q-depends-type": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held",
                                      reason="r", depends="まとめて 1 本の文字列"),
    "q-fork-options-type": lambda r: add_q(r, key="x", kind="fork", origin=defer_unit(r)["key"],
                                           status="held", reason="r", options="(A) と (B)"),
    "q-origin-field-missing": lambda r: add_q(r, key="x", kind="stuck", status="held", reason="r"),
    "q-awaiting-origin-not-material": lambda r: add_q(r, key="x", kind="awaiting",
                                                      origin="main_path", status="held", reason="r"),
    "q-review-origin-not-r": lambda r: add_q(r, key="x", kind="premise", origin="R9",
                                             status="held", reason="r"),
    # thrash は出どころを持たない種類。origin を許すと、帰属と stuck の縛りをそこから外せる。
    # **depends も同じ入口**——origin だけ塞いでいたとき、ここから開いた [block] 全件に帰属が付いた。
    "q-thrash-with-origin": lambda r: add_q(r, key="x", kind="thrash", origin=NIT_KEY,
                                            status="held", reason="r"),
    "q-thrash-with-depends": lambda r: (r["units"].append({"key": BK, "label": "block"}),
        add_q(r, key="x", kind="thrash", status="held", reason="r", depends=[BK])),
    # 非 unit 域の depends も実在検査に掛かる（綴り違いが黙って無効にならない）。
    # options / depends の「要素の型・空文字」（len < 2 と「配列でない」には腕が在った）。
    "q-fork-options-empty-item": lambda r: add_q(r, key="x", kind="fork", origin=defer_unit(r)["key"],
                                                 status="held", reason="r", options=["(A) a", ""]),
    "q-depends-item-type": lambda r: add_q(r, key="x", kind="rule", origin=NIT_KEY, status="held",
                                           reason="r", depends=[1]),
    # 逆向きの掲載要求の premise 側（unverifiable 側だけ腕が在った。表 1 つに畳んだのは
    # 「逆向きだけ直し忘れたときに落ちない穴」を塞ぐためなのに、順方向の片腕が空いていた）。
    "q-premise-unlisted": lambda r: r["reviews"]["R2"].update(
        status="premise-invalid", reason="解くべき問いが立っていない"),
    "q-awaiting-depends-missing": lambda r: (
        r["materials"]["main_path_observation"].update(status="awaiting_human", reason="実機が要る"),
        add_q(r, key="主経路を誰がどこで動かすか", kind="awaiting", origin="main_path_observation",
              status="held", reason="動かせない", depends=["src/typo.py — 存在しないキー"])),
    # 逆向きの対応表のうち unverifiable 側（premise 側は q-premise-origin-mismatch が見ている）。
    "q-review-origin-status-unverifiable": lambda r: add_q(r, key="x", kind="unverifiable",
                                                           origin="R2", status="held", reason="r"),
    # 問いの key が unhashable。契約（2）を担保するのは末尾の境界だけなので、units 側と同じ
    # 形が questions 側にも要る（非対称のまま放置すると、どちらかだけが守られていると読める）。
    "q-unhashable-key": lambda r: add_q(r, key=["x"], kind="thrash", status="held", reason="r"),
    # 開いたユニットへの帰属禁止は origin だけでなく depends にも当たる。origin を許される先
    # （nit）にしておいて depends から開いた [block] を掴むのが、塞ぎ残しの当の形。
    "q-no-open-via-depends": lambda r: (r["units"].append({"key": BK, "label": "block"}),
        add_q(r, key="どの観点を見直すか", kind="rule", origin=NIT_KEY, status="held",
              reason="同じ指摘が新証拠なく再燃", depends=[BK])),
    # 逆向きの掲載要求も未決で数える。閉じた問いを置いても、素材が人の起動待ちなら満たされない。
    "q-awaiting-listed-resolved": lambda r: (
        r["materials"]["main_path_observation"].update(status="awaiting_human", reason="実機が要る"),
        add_q(r, key="主経路を誰がどこで動かすか", kind="awaiting", origin="main_path_observation",
              status="resolved", reason="起動できなかった", resolution="テスト用設定で起動できる")),
}.items():
    rec = clone((templates["round-2"]))
    mutate(rec)
    write(name, rec)

# ディレクトリ渡し（履歴）。何を見る組かは各 expect_output の説明文が持つ。
def hist(name, recs):
    d = work / name
    d.mkdir()
    for rec in recs:
        (d / f"round-{rec['round']}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

hist("tmpl-1", [templates["round-1"]])
hist("tmpl-12", [templates["round-1"], templates["round-2"]])
full = [templates["round-1"], templates["round-2"], templates["round-3"]]
hist("hist", full)
hist("hist-gap", [templates["round-1"], templates["round-3"]])
back = clone((templates["round-3"]))
back["units"].append({"key": templates["round-1"]["units"][0]["key"], "label": "nit"})
hist("hist-return", [templates["round-1"], templates["round-2"], back])

def r1_at(n, units):
    r = clone((templates["round-1"]))
    r["round"] = n
    r["units"] = units
    # 中立な土台にする。round-1 の実例が持つ「人の起動待ちの素材と、その問い」を外し、
    # **found の素材も落とす**——found が残ると、units を空にした fixture に「素材が found なのに
    # units が空」という 2 つ目の阻害が常に立ち、帰属を狙った検査が狙いの分岐に決して入らない
    # （実測: その形で、当の欠陥を注入しても全件緑のままだった）。
    for name, m in r["materials"].items():
        if m["status"] in ("found", "awaiting_human"):
            r["materials"][name] = {"status": "clean", "checked": "見たが無かった"}
    r["questions"] = []
    return r

LK = "src/db/pool.py — 接続プールの上限を設定に出す"
# 別のレビュー（基準点が違う）の記録が同じディレクトリに残っている。
mixed = clone((templates["round-2"]))
mixed["base"] = "f" * 40
hist("mixed-base", [templates["round-1"], mixed])

hist("block-dropped", [r1_at(1, [{"key": BK, "label": "block"}]), r1_at(2, [])])

# `human-repeat` と、下の問いのセクションの `q-review-attribution` は同一内容だった（定数 QU / RUQ も
# 全フィールド一致）。実体が 1 つなので、1 つのディレクトリに腕を 2 本掛ける形に畳んである。
QU = {"key": "元の目的をどこから取るか", "kind": "unverifiable", "origin": "R1",
      "status": "held", "reason": "出典①②③のどれも無い"}
ch = r1_at(1, [])
ch["reviews"]["R1"] = {"status": "unverifiable", "reason": "目的テキストの出典が取れない"}
ch["questions"] = [QU]
ch2 = r1_at(2, [])
ch2["reviews"]["R1"] = {"status": "carried_over", "from_round": 1,
                        "reason": "再発火条件に当たらないので round 1 の判定を流用"}
hist("carry-from-human", [ch, ch2])
# 正直な書き方＝同じ値をもう一度書く。諮る義務が続いていることが毎ラウンド数えられる。
ch3 = r1_at(2, [])
ch3["reviews"]["R1"] = {"status": "unverifiable", "reason": "出典は今ラウンドも取れていない"}
ch3["questions"] = [QU]
hist("human-repeat", [ch, ch3])

# 問いの台帳の周またぎと帰属。
def with_q(rec, *qs):
    rec["questions"] = list(qs)
    return rec
FQ = {"key": "上限をどこで掛けるか", "kind": "fork", "origin": BK, "status": "held",
      "reason": "共有面に及ぶ", "options": ["(A) 入口 → 全経路に効く", "(B) 各経路 → 漏れる"]}
BK2 = "src/api/sort.py:order — 並び順が指定を無視する"
TWO = [{"key": BK, "label": "block"}, {"key": BK2, "label": "block"}]
STUCK3 = [{"key": BK, "label": "block"}]
hist("q-dropped", [with_q(r1_at(1, [{"key": BK, "label": "block"}]), FQ),
                   r1_at(2, [{"key": BK, "label": "block"}])])
hist("q-dropped-escalate", [
    with_q(r1_at(1, [{"key": BK, "label": "block"}]), dict(FQ, status="escalate")),
    r1_at(2, [{"key": BK, "label": "block"}])])
hist("q-depends-missing", [
    with_q(r1_at(1, TWO), dict(FQ, depends=["src/api/typo.py — 存在しないキー"])),
    with_q(r1_at(2, TWO), dict(FQ, depends=["src/api/typo.py — 存在しないキー"]))])
# 決着しても出どころが開いているうちは `decided`。**これは台帳から降りていないので要求を満たす**
# （判断の付いた問いを「未決」と書かされる形が、2 軸に割ったことで消えた）。
hist("q-stuck-decided", [
    r1_at(1, STUCK3), r1_at(2, STUCK3),
    with_q(r1_at(3, STUCK3), dict(FQ, status="decided", resolution="入口に寄せると決めた"))])
# 出どころが開いたまま `resolved` と書くのは記録の不正（2 軸目は記録から判定する）。
hist("q-resolved-while-open", [
    r1_at(1, STUCK3), r1_at(2, STUCK3),
    with_q(r1_at(3, STUCK3), dict(FQ, status="resolved", resolution="入口に寄せると決めた"))])
hist("q-stuck-other-kind", [
    r1_at(1, STUCK3), r1_at(2, STUCK3),
    with_q(r1_at(3, STUCK3), {"key": "新規が出続ける", "kind": "thrash",
                              "status": "held", "reason": "件数が落ちない"})])
# ここだけ検査がゼロだと、unverifiable だけが残る周が永久に聞かれない形を誰も止められない。
# `human-repeat` と同じ内容の固定具がここにもう 1 つ在った（定数まで全フィールド一致）。実体が
# 1 つなので、1 つのディレクトリに腕を 2 本掛ける形に畳んである（片方だけ直しても検査が
# 変わらない形を残さない）。
# awaiting は雛形に実在する最も普通の問いなのに、ここだけ腕が無かった。
am1 = r1_at(1, [])
am1["materials"]["main_path_observation"] = {"status": "awaiting_human", "reason": "実機が要る"}
am2 = r1_at(2, [])
am2["materials"]["main_path_observation"] = {"status": "awaiting_human", "reason": "今も実機が要る"}
AMQ = {"key": "主経路を誰がどこで動かすか", "kind": "awaiting", "origin": "main_path_observation",
       "status": "held", "reason": "この環境では動かせない"}
hist("q-material-attribution", [with_q(am1, AMQ), with_q(am2, AMQ)])
# 2 周目以降だけに掛けると初回が素通りする。
hist("q-origin-missing-round1", [with_q(r1_at(1, [{"key": BK, "label": "block"}]),
                                        dict(FQ, origin="src/none.py — 無い"))])
PMQ = {"key": "解くべき問いが立っているか", "kind": "premise", "origin": "R2",
       "status": "held", "reason": "judge が仮定を検算中"}
def premise_round(n):
    r = r1_at(n, [{"key": BK, "label": "block"}])
    r["reviews"]["R2"] = {"status": "premise-invalid", "reason": "問いが立っていない"}
    return with_q(r, PMQ)
# 短絡すると文言が「前提不成立が確定（escalate）」に変わるので、この期待で status 条件を縛れる。
hist("q-premise-not-escalate", [premise_round(1), premise_round(2)])
def esc_round(n):
    return with_q(r1_at(n, [{"key": BK, "label": "block"}]), dict(FQ, status="escalate"))
hist("q-escalate-not-premise", [esc_round(1), esc_round(2)])
hist("q-stuck-unlisted", [r1_at(n, [{"key": BK, "label": "block"}]) for n in (1, 2, 3)])
# 帰属は前の周から持ち越した保留にだけ付くので、聞く時を見る fixture は 2 周以上にする。
hist("q-stuck-listed", [r1_at(1, [{"key": BK, "label": "block"}]),
                        with_q(r1_at(2, [{"key": BK, "label": "block"}]), FQ),
                        with_q(r1_at(3, [{"key": BK, "label": "block"}]), FQ)])
hist("q-mixed", [with_q(r1_at(n, TWO), FQ) for n in (1, 2)])
hist("q-depends", [with_q(r1_at(n, TWO), dict(FQ, depends=[BK2])) for n in (1, 2)])
# 立った周には聞かない。同じ形を 1 周だけにすると、帰属でなく「今ラウンドに立った問い」の印が付く。
hist("q-fresh", [with_q(r1_at(1, TWO), dict(FQ, depends=[BK2]))])
pe = r1_at(1, [{"key": BK2, "label": "block"}])
pe["reviews"]["R2"] = {"status": "premise-invalid", "reason": "1 デプロイ＝1 リポジトリなら識別子は要らない"}
hist("q-premise-escalate", [with_q(pe, {"key": "解くべき問いが立っているか", "kind": "premise", "origin": "R2",
                                        "status": "escalate", "reason": "judge が仮定を実態で確かめた——真"})])
# ループが決めた問い（resolved）は帰属しない＝その阻害は「仕事」。**肯定の文言で確かめる**——
# 「出ないこと」を見る形にすると、対象が消えても異常終了しても緑になる（実測でそうなった）。
# 2 周とも held の Q1 は帰属するので、resolved の Q2 が帰属したら「帰属しない 0 件」になって
# 文言が変わる。つまりこの 1 本で、resolved を数えたら赤くなる。
RQ = {"key": "並び順をどう直すか", "kind": "fork", "origin": BK2,
      "reason": "候補が 2 つ", "options": ["(A) 入口", "(B) 各経路"]}
hist("q-resolved-is-work", [
    with_q(r1_at(1, TWO), FQ, dict(RQ, status="held")),
    with_q(r1_at(2, TWO), FQ, dict(RQ, status="decided", resolution="入口に寄せると決めた")),
])

# 出どころの域が違えば、値が文字列として同じでも別物である。unit の key をリテラル "R2" に
# しても、別の域の問い（premise の origin="R2"）はそのユニットを指したことにならない。
# 平坦な文字列で突き合わせていたとき、これが 3 周続いた [block] の振り分け要求を黙らせる
# 逃げ道だった（実測で再現）。名前を禁じるチェックでなく、域を持ち回る構造で保証している。
kc = [r1_at(n, [{"key": "R2", "label": "block"}]) for n in (1, 2, 3)]
kc[2]["reviews"]["R2"] = {"status": "premise-invalid", "reason": "解くべき問いが立っていない"}
kc[2]["questions"] = [{"key": "前提が立っているか", "kind": "premise", "origin": "R2",
                       "status": "held", "reason": "judge が検算中"}]
hist("domain-separation", kc)

nq1 = r1_at(1, [{"key": BK, "label": "block"}])
nq2 = r1_at(2, [{"key": BK, "label": "block"}])
nq2["questions"] = [FQ]
nq2["reviews"]["R1"] = {"status": "carried_over", "from_round": 1, "reason": "機構の追加なし"}
hist("q-new-r1-carried", [nq1, nq2])
nq2b = clone((nq2))
nq2b["reviews"]["R1"] = {"status": "pass", "reason": "台帳に問いが載ったので再発火。監査した"}
hist("q-new-r1-ran", [nq1, nq2b])
nq1c = clone((nq1)); nq1c["questions"] = [FQ]
hist("q-carried-r1-carried", [nq1c, nq2])
# 同じ key のまま kind / origin / options を総取り替えする（key の新規性では捕まらない形）。
sw2 = clone((nq2))
sw2["questions"] = [dict(FQ, kind="stuck", origin=BK)]
sw2["questions"][0].pop("options")
hist("q-swap-r1-carried", [nq1c, sw2])
# ループが決めた問いが次の周に未決へ戻る（再燃。key は既出なので「新規」では捕まらない）。
rp1 = clone((nq1))
rp1["questions"] = [dict(FQ, status="decided", resolution="入口に寄せると決めた")]
hist("q-reopen-r1-carried", [rp1, nq2])

nc = work / "name-case"; nc.mkdir()
(nc / "round-1.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
(nc / "round-2.JSON").write_text(json.dumps(r1_at(2, []), ensure_ascii=False), encoding="utf-8")
# 同じ欠陥の鏡像。受理側を ASCII に狭めただけだと、桁の異体字は「そもそも記録でない」として
# 黙って捨てられる側へ移るだけで、欠陥が入口を移動して残る。
nu = work / "name-unidigit"; nu.mkdir()
(nu / "round-\u0661.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
# 正規表現の軸（桁・英字の大小）では拾えない綴り。区切り・語・拡張子の軸から通る形で、
# **最新ラウンドがこの形だと、記録が 1 つ短いまま「連続 2 ラウンド」の判定に乗る。**
# from_round の下限。**外すと「素材を一度も見ずに連続 2 ラウンド成立」が exit 0 で通る**
# （実測: 全素材と R1/R2 を from_round: 0 にした記録が「round 0 の判定を流用」で収束した）。
# このツールが存在する理由そのものの穴なのに、塞いでいる 1 行に腕が無かった。
fz = work / "from-round-zero"; fz.mkdir()
fz1 = r1_at(1, []); fz2 = r1_at(2, [])
fz2["materials"]["consistency"] = {"status": "carried_over", "from_round": 0, "reason": "流用"}
(fz / "round-1.json").write_text(json.dumps(fz1, ensure_ascii=False), encoding="utf-8")
(fz / "round-2.json").write_text(json.dumps(fz2, ensure_ascii=False), encoding="utf-8")
# 3 周の窓の**幅**。連鎖が r2・r3 だけなので、窓が 3 周なら要求は立たない（exit 1）。
# 窓を 2 周に狭めると要求が立って exit 2 になる＝この 1 本が幅を測る。「対照」と名乗っていた
# stuck-two-rounds は記録が 2 件しか無く、range(2, len(rounds)) に一度も入らなかった。
ww = [r1_at(1, []), r1_at(2, [{"key": BK, "label": "block"}]),
      r1_at(3, [{"key": BK, "label": "block"}])]
hist("stuck-window-width", ww)
# 窓は滑る。同じ連鎖を 1 周のばすと、4 周目の組で初めて要求が立つ。
hist("stuck-window-slide", ww + [r1_at(4, [{"key": BK, "label": "block"}])])
# UTF-8 として読めない記録（「開けない」「JSON でない」と別の診断になることを縛る）。
(work / "badenc").mkdir()
(work / "badenc" / "round-1.json").write_bytes(b'{"base": "\xff\xfe"}')
nt = work / "name-tail"; nt.mkdir()
(nt / "round-1.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
(nt / "round_2.json").write_text(json.dumps(r1_at(2, []), ensure_ascii=False), encoding="utf-8")
# 退避先のディレクトリとドットファイルは鳴らさない（下位は読まない規約・OS の成果物）。
nok = work / "name-ok"; nok.mkdir()
(nok / "round-1.json").write_text(json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
(nok / "archive-deadbeef").mkdir()
(nok / ".DS_Store").write_text("x", encoding="utf-8")

th2 = r1_at(2, [{"key": BK, "label": "block"}])
th2["questions"] = [{"key": "新規が出続ける", "kind": "thrash", "status": "held", "reason": "件数が落ちない"}]
hist("q-thrash-silent", [r1_at(1, [{"key": BK, "label": "block"}]), th2])

sd = [r1_at(n, TWO) for n in (1, 2, 3)]
sd[2]["questions"] = [dict(FQ, origin=BK2, depends=[BK])]
hist("q-stuck-via-depends", sd)

hist("stuck-two-rounds", [r1_at(1, [{"key": BK, "label": "block"}]),
                          r1_at(2, [{"key": BK, "label": "block"}])])

# 縛るのは「まだ聞く気がある問い」だけで、resolved には何も要求しない（緩める向きの 2 本）。
rog = r1_at(1, [{"key": BK, "label": "block"}])
rog["questions"] = [dict(FQ, origin="src/gone.py — 直って消えたキー", status="resolved",
                         resolution="修正で形が変わり岐路が消えた")]
hist("q-resolved-origin-gone", [rog])
rso = r1_at(1, [{"key": BK, "label": "block"}])
rso["questions"] = [{"key": "別 PR に積むか", "kind": "split", "origin": BK, "status": "decided",
                     "reason": "目的の外に見えた", "resolution": "目的の内側と分かったので本 PR で直す"}]
hist("q-resolved-split-open", [rso])

mid = [r1_at(n, TWO) for n in (1, 2, 3)]
mid[1]["questions"] = [dict(FQ, origin="src/none.py — 無い")]
mid[2]["questions"] = [dict(FQ, origin="src/none.py — 無い")]
hist("q-origin-missing-mid", mid)

hist("round-zero", [r1_at(1, [])])
hist("round-dup", [r1_at(1, []), r1_at(2, [])])
(work / "round-dup" / "round-01.json").write_text(
    json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")
(work / "round-zero" / "round-0.json").write_text(
    json.dumps(r1_at(1, []), ensure_ascii=False), encoding="utf-8")

cz = clone((templates["round-1"]))
cz["materials"]["local_review"] = {"status": "found", "count": 0, "detail": "0 件だった"}
write("count-zero", cz, num=1)
ce = clone((templates["round-1"]))
ce["materials"]["consistency"] = {"status": "clean", "checked": ""}
write("checked-empty", ce, num=1)
cf = clone((templates["round-1"]))
# **整数は別**——`count: 0` は「見たが 0 件」で正当（その腕は count-zero）。
cf["materials"]["consistency"] = {"status": "clean", "checked": False}
cn = clone((templates["round-1"]))
cn["materials"]["consistency"] = {"status": "clean", "checked": 0}
write("checked-number", cn, num=1)
write("checked-false", cf, num=1)

# defer が 1 ラウンド記録から消えてから [block] で戻る。台帳が隣の 1 ラウンドしか見ないと
# 新証拠なしで素通りし、しかも「（新規）」と事実に反する注記が付いていた。
hist("ledger-gap", [
    r1_at(1, [{"key": LK, "label": "suggest", "disposition": "defer",
               "reason": "共有面を触るので別の変更で扱う"}]),
    r1_at(2, []),
    r1_at(3, [{"key": LK, "label": "block"}]),
])

# JSON として読めない記録と、深いネスト（json モジュールが JSONDecodeError 以外を投げる例）。
for nm, body in (("truncated", '{ "base": '), ("deep", "[" * 100000 + "]" * 100000)):
    (work / nm).mkdir(exist_ok=True)
    (work / nm / "round-1.json").write_text(body, encoding="utf-8")
# 研究記録・診断記録はファイル渡しなので、同じ深いネストを**単体のファイルとしても**置く。
# `$WORK/deep.json` はどこでも作られておらず、それを渡す 2 本の腕は「開けない」で exit 2 に
# なって緑だった——名乗った性質（深いネストでも 1 と区別して落ちる）を一度も測っていない。
(work / "deep.json").write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
# 「開けない」の腕。round-1.json がディレクトリだと open が OSError を投げる。
(work / "unreadable" / "round-1.json").mkdir(parents=True)
PY
}

echo "review-record.py"
R1="$CL/templates/round-1.example.json"   # 下の「引数が多すぎる」の腕で 2 つ目の引数に使う
# 変数に詰めて展開すると、python のパスにスペースがあるだけで壊れる（Windows で起きる）。
RECORD="$CL/scripts/review-record.py"


write_broken_records || { echo "  FAIL 壊した記録を作れない"; fail=1; }

expect_output 1 "前ラウンドの記録が無い" "round-1 だけの記録は、比較の欠落を阻害要因に数える" \
    "$PY_BIN" "$RECORD" "$WORK/tmpl-1"
expect_output 1 "前ラウンドに阻害要因が 4 件あった" "解消した直後のラウンドは連続 2 ラウンドの 1 ラウンド目" \
    "$PY_BIN" "$RECORD" "$WORK/tmpl-12"
# 人に聞く時は機械が帰属で決める。**立った周には帰属しない**ので、round-1 だけの記録では
# 「聞く時」の行がどれも出ず、問いが指している阻害要因に「今ラウンドに立った問い」の印が付く。
expect_output 1 "（今ラウンドに立った問い——再審は次の周）" \
    "問いが立った周には帰属せず、印だけが付く" "$PY_BIN" "$RECORD" "$WORK/tmpl-1"
# **セクションごと、行数まで縛る。** 「scalar 'doc_lines': 120 → 135」という綴りは `scalar_changes` と
# `history` の 2 経路から出るので、その 1 行だけを見る形は**どちらを殺しても緑**だった（実測:
# scalar_changes を丸ごと無効化しても、`now > before` を `>=` や `!=` にしても全件緑）。セクションの
# 見出しは片方しか出さず、直後の 2 行までを期待に含めれば「増えていないものが混ざる」退行も赤になる。
expect_output 1 $'増えた scalar（阻害要因ではない。相殺する削除があるか R1 に見せろ）:\n  - scalar \'doc_lines\': 120 → 135\n  - scalar \'comment_ratio_pct\': 18 → 21\n持ち越し' \
    "増えた scalar だけを、増えた scalar のセクションに出す" "$PY_BIN" "$RECORD" "$WORK/tmpl-12"
expect_output 0 "連続 2 ラウンド" "2 ラウンド続けて阻害なしなら exit 0" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "これは収束の宣言ではない" "阻害なしを収束と名乗らない" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "素材 prior_decisions: round 1 の判定を流用（2 ラウンド前）" "持ち越しは実際に見たラウンドと古さを見せる" \
    "$PY_BIN" "$RECORD" "$WORK/hist"


# 記録が不正（exit 2）。1 と混ざると「非収束」と誤読され、収束を永久に宣言できなくなる。
# **期待メッセージまで検査する**（理由は冒頭の expect_output の段）。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "不正な記録は 1 と区別して落ちる: $m" "$PY_BIN" "$RECORD" "$WORK/$m"
done <<'CASES'
drop-material|素材 'hygiene' の返答が無い
drop-defer-reason|defer に構造的理由が無い
drop-base|必須のフィールド 'base' が無い
drop-round|必須のフィールド 'round' が無い
bad-base|base が違う
bad-round|ファイル名の番号と違う
bad-status|status が不正
clean-without-checked|'checked' が要る
bad-label|label が不正
drop-key|key が無い
drop-reviews|必須のフィールド 'reviews' が無い
drop-review-R3|R3 の verdict が無い
bad-review-status|R1 の status が不正
review-only-R2|R1 は premise-invalid にできない
review-only-R34|R1 は not_applicable にできない
pass-without-reason|R3 は status=pass なので 'reason' が要る
carry-without-from|'from_round' が要る
carry-from-future|今ラウンド（2）より前でない
carry-from-not-applicable|前ラウンドが not_applicable なので持ち越せない
not-object|記録の最上位が object でない
bad-round-type|'round' が整数でない
bad-round-bool|'round' が整数でない
round-below-one|'round' が 1 以上でない
bad-materials-type|'materials' が object でない
bad-units-type|'units' が配列でない
bad-unit-type|units[0] が object でない
bad-reviews-type|'reviews' が object でない
bad-from-round-type|'from_round' は数で書け
bad-scalars-type|'scalars' が object でない
null-scalars|'scalars' が object でない
unhashable-status|想定外の例外（TypeError）
CASES

expect_output 2 "想定外の例外（TypeError）" "前ラウンドの key が unhashable でも 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/unhashable-key"
expect_output 2 "今ラウンド（1）より前でない" "初回ラウンドに持ち越しは書けない" \
    "$PY_BIN" "$RECORD" "$WORK/r1-carry"

# 2 ラウンド目以降でしか発火しない突合（round-3 を壊し round-2 と比べる）。
while IFS='|' read -r code m msg; do
    [ -n "$m" ] || continue
    expect_output "$code" "$msg" "前ラウンドとの突合: $m" "$PY_BIN" "$RECORD" "$WORK/$m"
done <<'CASES'
2|carry-chain-broken|持ち越しが連鎖していない
2|review-carry-chain-broken|R2 の from_round（1）が前ラウンド（2）でない
2|reopen-without-evidence|reopen_evidence が無い
1|reopen-with-evidence|既受容 defer の再審。新証拠: 本番ログで上限超過のクエリを 3 件観測
1|skip-PR|R3 が not_applicable だが、P-R への到達を妨げる阻害要因が記録に無い
1|redesign|R2 が redesign-needed
1|premise-invalid|収束を宣言せずユーザーに諮れ
1|unverifiable|収束を宣言せずユーザーに諮れ
1|review-not-run|R4 が not_run
0|defer-dropped|台帳には残る
0|defer-dropped|[人へ] fork
1|material-awaiting|素材 'consistency' が人の起動待ち
1|material-not-run|素材 'hygiene' が未実施
2|dup-key|突合の識別子なので 1 ラウンドに 1 つ
1|found-no-units|素材が found なのに units が空
CASES
expect_output 1 "残存——過去のラウンドにも在った" "同じ [block] キーが 2 ラウンド残れば残存の印を出す" \
    "$PY_BIN" "$RECORD" "$WORK/stuck"

# 問いの台帳（1 ラウンド内）。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "問いの台帳: $m" "$PY_BIN" "$RECORD" "$WORK/$m"
done <<'CASES'
q-split-on-do-now|split の origin / depends が [block] / do-now
q-split-on-block|split の origin / depends が [block] / do-now
q-bad-kind|kind が不正
q-bad-status|status が不正
q-without-reason|'reason' が要る
q-fork-one-option|options は選択肢 2 つ以上の配列
q-resolved-without-resolution|'resolution' が要る
q-origin-missing|origin が今ラウンドの units にも defer 台帳にも無い
q-awaiting-unlisted|素材 'main_path_observation' が awaiting_human なのに問いの台帳に無い
q-awaiting-origin-clean|awaiting の origin 'hygiene' が awaiting_human でない
q-review-unlisted|R1 が unverifiable なのに問いの台帳に無い
q-premise-origin-mismatch|premise の origin R2 が premise-invalid でない
q-dup-key|の key が重複: x
q-legacy-ask-human|人に聞く候補は questions（問いの台帳）に
q-not-list|'questions' が配列でない
q-drop|必須のフィールド 'questions' が無い
q-not-object|questions[2] が object でない
q-no-key|に key が無い（周をまたぐ突合に使う
q-empty-reason|'reason' が空（きっかけ・根拠を書け）
q-depends-type|depends は、この答え待ちで手を止めるユニットの key の配列
q-fork-options-type|options は選択肢 2 つ以上の配列
q-origin-field-missing|なので origin（units の key）が要る
q-awaiting-origin-not-material|なので origin は素材名
q-review-origin-not-r|なので origin は R1〜R4
q-thrash-with-origin|なので origin / depends を持てない
q-thrash-with-depends|なので origin / depends を持てない
q-awaiting-depends-missing|depends が今ラウンドの units にも defer 台帳にも無い
q-fork-options-empty-item|options は選択肢 2 つ以上の配列
q-depends-item-type|depends は、この答え待ちで手を止めるユニットの key の配列
q-premise-unlisted|R2 が premise-invalid なのに問いの台帳に無い
q-review-origin-status-unverifiable|の origin R2 が unverifiable でない
q-no-open-via-depends|rule の origin / depends が [block] / do-now
q-awaiting-listed-resolved|が awaiting_human なのに問いの台帳に無い
q-unhashable-key|想定外の例外（TypeError）
CASES
# 問いの台帳（周またぎ）と、人に聞く時の判定。
expect_output 2 "前ラウンドの問い（held）が今ラウンドの台帳に無い" "保留した問いは黙って落とせない" \
    "$PY_BIN" "$RECORD" "$WORK/q-dropped"
expect_output 2 "前ラウンドの問い（escalate）が今ラウンドの台帳に無い" "人へ回した問いも黙って落とせない" \
    "$PY_BIN" "$RECORD" "$WORK/q-dropped-escalate"
expect_output 2 "depends が今ラウンドの units にも defer 台帳にも無い" \
    "出どころの実在検査は depends にも当たる（綴り違いが黙って無効にならない）" \
    "$PY_BIN" "$RECORD" "$WORK/q-depends-missing"
# 期待は長い文言で。「問いの台帳に無い」は「素材が awaiting_human なのに」「R が … なのに」の
# 2 つの診断にも出るので、短いままだと別の理由で落ちても通る（実測: 中立化を止めた記録では、
# stuck の検査を完全に殺しても exit 2 かつこの語を含んで検査が通った）。
expect_output 1 "[block] 未解消" \
    "決着しても出どころが開いているうちは decided で、台帳から降りない（要求を満たす）" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-decided"
expect_output 2 "出どころが [block] / do-now のまま resolved" \
    "出どころが開いたまま resolved と書けない（1 件置いて要求を永久に黙らせる形を塞ぐ）" \
    "$PY_BIN" "$RECORD" "$WORK/q-resolved-while-open"
# この腕が落ちる理由は「kind が違う」ではなく「出どころを持たない種類は origin を書けない」。
# **種類による絞りは機械にもう無い**——出どころの key 空間を分けたので恒真になり、削ってある。
expect_output 2 "2 ラウンド連続の残存＝stuck）のに問いの台帳に無い" \
    "出どころを持たない種類を置いても stuck の振り分け要求は満たされない" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-other-kind"
expect_output 1 "残る阻害要因は保留の問いに帰属するものだけ（1 件）" \
    "R1〜R4 の人に諮る verdict も保留の問いに帰属する" \
    "$PY_BIN" "$RECORD" "$WORK/human-repeat"
expect_output 1 "（保留の問いに帰属——答えを待っている）" \
    "人の起動待ちの素材も保留の問いに帰属する" \
    "$PY_BIN" "$RECORD" "$WORK/q-material-attribution"
expect_output 2 "origin が今ラウンドの units にも defer 台帳にも無い" \
    "出どころの実在検査は round 1 にも掛かる" \
    "$PY_BIN" "$RECORD" "$WORK/q-origin-missing-round1"
# 前提不成立の短絡は「premise」かつ「escalate」の両方が要る。**載せた周には聞かない**が
# ここでも効く——held のうちは出さない。これはこの設計の要で、どちらの条件も腕が無かった。
expect_output 1 "保留の問いに帰属する阻害要因 1 件は聞くのを待て——帰属しない 1 件を先に直せ" \
    "前提不成立でも、問いが held のうちは短絡しない（載せた周には聞かない）" \
    "$PY_BIN" "$RECORD" "$WORK/q-premise-not-escalate"
expect_output 1 "残る阻害要因は保留の問いに帰属するものだけ（1 件）" \
    "premise 以外の escalate では前提不成立を出さない" \
    "$PY_BIN" "$RECORD" "$WORK/q-escalate-not-premise"
expect_output 2 "2 ラウンド連続の残存＝stuck）のに問いの台帳に無い" "同じ [block] が 3 周続けば台帳への記載を要求する" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-unlisted"
expect_output 1 "残る阻害要因は保留の問いに帰属するものだけ（1 件）" "残る阻害が保留の問いだけなら「聞く時」を出す" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-listed"
expect_output 1 "（今ラウンドに立った問い——再審は次の周）" \
    "同じ形でも、問いが立った周には帰属せず印だけが付く（立った周には聞かない）" \
    "$PY_BIN" "$RECORD" "$WORK/q-fresh"
expect_output 1 "帰属しない 1 件を先に直せ" \
    "ループが決めた問い（decided）の阻害要因は仕事であって、聞く時ではない" \
    "$PY_BIN" "$RECORD" "$WORK/q-resolved-is-work"
expect_output 1 "（保留の問いに帰属——答えを待っている）" "帰属する阻害要因の行に印が付く" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-listed"
expect_output 1 "帰属しない 1 件を先に直せ" "帰属しない阻害が残るうちは聞かない" \
    "$PY_BIN" "$RECORD" "$WORK/q-mixed"
# do-now の見出しを縛る腕が 1 本も無く、[block] の見出しに潰しても全件緑だった。
expect_output 1 "[suggest] do-now 未対応" "do-now の行は [block] と別の見出しで出る" \
    "$PY_BIN" "$RECORD" "$WORK/tmpl-1"
expect_output 1 "残る阻害要因は保留の問いに帰属するものだけ（2 件）" "depends に挙げたユニットの阻害も問いに帰属する" \
    "$PY_BIN" "$RECORD" "$WORK/q-depends"
expect_output 1 "前提不成立が確定（escalate）" "premise の escalate は他の阻害の帰属を問わず「聞く時」" \
    "$PY_BIN" "$RECORD" "$WORK/q-premise-escalate"
expect_output 2 "2 ラウンド連続の残存＝stuck）のに問いの台帳に無い: R2" \
    "unit の key が R の名前と同じでも、別の域の問いはそのユニットを指したことにならない" \
    "$PY_BIN" "$RECORD" "$WORK/domain-separation"
# 台帳を監査する経路は R1 しか無いので、問いが新しく載った周に R1 を持ち越すと監査が走らない。
expect_output 2 "台帳の未決の問いが前ラウンドから変わったのに R1 が carried_over" \
    "問いが載った周に R1 を持ち越した記録は不正" "$PY_BIN" "$RECORD" "$WORK/q-new-r1-carried"
# **key の新規性だけを見ていたとき素通りした 2 形。** どちらも台帳の中身は動いている。
expect_output 2 "台帳の未決の問いが前ラウンドから変わったのに R1 が carried_over" \
    "同じ key のまま中身を総取り替えした周も、R1 を持ち越せない" \
    "$PY_BIN" "$RECORD" "$WORK/q-swap-r1-carried"
expect_output 2 "台帳の未決の問いが前ラウンドから変わったのに R1 が carried_over" \
    "ループが決めた問いが未決に戻った周も、R1 を持ち越せない" \
    "$PY_BIN" "$RECORD" "$WORK/q-reopen-r1-carried"
expect_output 1 "[block] 未解消" "同じ形でも R1 を走らせていれば通る（対照）" \
    "$PY_BIN" "$RECORD" "$WORK/q-new-r1-ran"
expect_output 1 "[block] 未解消" "持ち越した問いだけの周は R1 も持ち越してよい（縛るのは新しく載った問い）" \
    "$PY_BIN" "$RECORD" "$WORK/q-carried-r1-carried"
expect_output 2 "は記録の名前でない" "大小が違うだけのファイルを黙って捨てない" \
    "$PY_BIN" "$RECORD" "$WORK/name-case"
# 受理は厳しく（ASCII の桁だけ）、見逃しの検知は広く（Unicode の桁も拾う）。入口の片方を
# 狭めただけだと、欠陥はもう片方の入口へ移動して残る。
expect_output 2 "は記録の名前でない" "桁の異体字のファイル名も黙って受理せず、黙って捨てもしない" \
    "$PY_BIN" "$RECORD" "$WORK/name-unidigit"
# **最新ラウンドが消える形。** 欠番検査は 1..max しか見ないので、末尾の欠落は赤くならない。
expect_output 2 "は記録の名前でない" "正規表現の軸に載らない綴りでも、最新ラウンドを黙って捨てない" \
    "$PY_BIN" "$RECORD" "$WORK/name-tail"
expect_output 1 "前ラウンドの記録が無い" "退避先のディレクトリと OS の成果物では鳴らさない（対照）" \
    "$PY_BIN" "$RECORD" "$WORK/name-ok"
# 「聞く時」の 3 分岐はどれも通らない周。台帳の数え直しが exit 1 側にも要る。
expect_output 1 "台帳に未決の問いが 1 件（うち人へ 0 件）" \
    "出どころで手を止めない問いだけが残る周も、台帳が黙って終わらない" \
    "$PY_BIN" "$RECORD" "$WORK/q-thrash-silent"
expect_output 2 "2 ラウンド連続の残存＝stuck）のに問いの台帳に無い" \
    "連鎖のキーを depends に並べても stuck の振り分け要求は満たされない（見るのは origin）" \
    "$PY_BIN" "$RECORD" "$WORK/q-stuck-via-depends"
expect_output 2 "round 4: 同じ [block] が 3 ラウンドの記録に続けて在る" \
    "3 周の窓は滑る（連鎖が 1 周のびると、次の組で要求が立つ）" \
    "$PY_BIN" "$RECORD" "$WORK/stuck-window-slide"
expect_output 1 "（残存——過去のラウンドにも在った）" \
    "2 周の残存では、まだ台帳への記載を要求しない（対照）" "$PY_BIN" "$RECORD" "$WORK/stuck-two-rounds"
# 未決だけを縛る絞りを、緩める向きで 2 本。resolved はループが決めた跡なので、機械は縛らない。
expect_output 1 "[block] 未解消" "ループが決めた問いの出どころは、記録から消えていてよい" \
    "$PY_BIN" "$RECORD" "$WORK/q-resolved-origin-gone"
expect_output 1 "[block] 未解消" "ループが決めた split（decided）は、開いた [block] を指していてよい" \
    "$PY_BIN" "$RECORD" "$WORK/q-resolved-split-open"
expect_output 2 "round 2: questions[0] の origin" "出どころの実在検査は中間のラウンドにも掛かる" \
    "$PY_BIN" "$RECORD" "$WORK/q-origin-missing-mid"

# 前のレビューの記録が同じディレクトリに残っている形。手順書は消すなと言っているので、
# 止まるだけでなく退避先を案内できていることまで縛る。
expect_output 2 "混ざっていないか" "別レビューの記録が混ざったら、退避の案内を出して止まる" \
    "$PY_BIN" "$RECORD" "$WORK/mixed-base"
# 消えた [block] の報告。defer 側にだけ在って block 側に無いと、未解消の [block] を
# 記録から落とすだけで阻害要因が 0 になり、収束の分岐に乗る。
expect_output 1 "過去のラウンドの [block] で今ラウンドの記録に無いキー" \
    "前ラウンドの [block] が記録から消えたら報告する（defer 側との非対称を消す）" \
    "$PY_BIN" "$RECORD" "$WORK/block-dropped"
expect_output 2 "前ラウンドが unverifiable なので持ち越せない" \
    "人に諮る verdict を持ち越すと記録の不正になる（阻害要因から消えるため）" \
    "$PY_BIN" "$RECORD" "$WORK/carry-from-human"
# 正直な書き方＝同じ値をもう一度書く。これなら毎ラウンド阻害要因として数えられる。
expect_output 1 "R1 が unverifiable（収束を宣言せずユーザーに諮れ）" \
    "人に諮る verdict は、同じ値を書き直せば毎ラウンド数えられる" \
    "$PY_BIN" "$RECORD" "$WORK/human-repeat"
expect_output 2 "1 から始まる番号でない" "round-0.json を黙って捨てない" \
    "$PY_BIN" "$RECORD" "$WORK/round-zero"
expect_output 2 "同じ番号" "ゼロ詰めの別名が同じ番号に潰れるのを落とす" \
    "$PY_BIN" "$RECORD" "$WORK/round-dup"
expect_output 1 "収束を妨げるもの" "count: 0 を「値が無い」と言わない" \
    "$PY_BIN" "$RECORD" "$WORK/count-zero"
expect_output 2 "が空（何を見たかを書け）" "空文字は欠落と分けて診断する" \
    "$PY_BIN" "$RECORD" "$WORK/checked-empty"
expect_output 2 "from_round が 1 以上でない" \
    "存在しないラウンド 0 からの流用を落とす（外すと素材を一度も見ずに収束できる）" \
    "$PY_BIN" "$RECORD" "$WORK/from-round-zero"
expect_output 1 "（残存——過去のラウンドにも在った）" \
    "連鎖が 2 周ぶんなら、3 周の窓では台帳への記載を要求しない（窓の幅を測る）" \
    "$PY_BIN" "$RECORD" "$WORK/stuck-window-width"
expect_output 2 "UTF-8 として読めない" "UTF-8 でない記録は「開けない」「JSON でない」と別の診断で落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/badenc"
expect_output 2 "が空（何を見たかを書け）" "縮退値（false / [] / {}）で明示返答のフィールドを埋められない" \
    "$PY_BIN" "$RECORD" "$WORK/checked-false"
# 免除を**型**（整数なら通す）で持っていたとき、文を要求するフィールドに 0 を書いて全部素通りした。
# 免除の単位はフィールドの名前（NUMERIC_FIELDS）で、count / from_round だけが数で埋まる。
expect_output 2 "が空（何を見たかを書け）" "文を要求するフィールドに数を書いても「埋まっている」にならない" \
    "$PY_BIN" "$RECORD" "$WORK/checked-number"
expect_output 2 "reopen_evidence が無い" "1 ラウンド記録から落としても、台帳は全ラウンドの和なので再審を止める" \
    "$PY_BIN" "$RECORD" "$WORK/ledger-gap"
expect_output 0 "履歴（round 1〜3" "ディレクトリを渡すと全ラウンドの履歴を出す" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "問いの台帳（人に聞く候補。載せた周には聞かない" "台帳の問いは阻害要因にせず、人に聞く候補として出す" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "r1:held(awaiting) → r2:resolved(awaiting) → r3:—" "問いの推移を履歴に出す（決めた問いは次の周から消えてよい）" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "問いの台帳の件数（保留・人へ・ループが決めた）: 1・0・0 → 1・0・1 → 1・1・0" "台帳の件数の推移を出す" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "台帳に未決の問いが 2 件（うち人へ 1 件）" \
    "阻害要因が 0 でも、台帳に未決が残っていれば判定行がそう言う" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 0 "要対応（[block]＋do-now）の件数: 3 → 0 → 0" "要対応の件数の推移を出す" "$PY_BIN" "$RECORD" "$WORK/hist"
expect_output 2 "round-2.json が無い" "連番に穴があれば履歴を出さずに落ちる" "$PY_BIN" "$RECORD" "$WORK/hist-gap"
expect_output 0 "r1:block → r2:— → r3:nit（消えて 1 回戻った）" "直したはずのキーが戻れば履歴に印を付ける" \
    "$PY_BIN" "$RECORD" "$WORK/hist-return"
# 2 ラウンド目に初出しただけのキーは「戻った」ではない。**行末の改行まで期待に含める**ことで
# 「注記が付いていない」を肯定で言う——「出ないこと」を grep で見る形は、対象が消えても
# 異常終了しても緑になる（このセクションでもう 1 本が実際にそうなっていた）。
# **引用は ANSI-C（$'…'）でなければならない。** `"$(printf '…\n')"` はコマンド置換が末尾の
# 改行を落とすので期待からも改行が消え、注記が付いた出力にも一致する——実測: この形にして
# いたとき、初出を「戻った」と数える変異を当てても全件緑のままだった（肯定形に直したつもりが、
# 同じ恒真をもう 1 本作っていた）。
expect_output 0 $'r1:— → r2:suggest/defer → r3:suggest/defer\n' \
    "初出のキーを「戻った」と数えない（注記が付かない）" "$PY_BIN" "$RECORD" "$WORK/hist"

# 記録に到達できない場合も 2（契約は冒頭 `review-record.py` の docstring が正本）。
expect_output 2 "JSON として読めない" "壊れた JSON は 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/truncated"
expect_output 2 "ディレクトリでない" "記録のディレクトリでないものを渡したら 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/does-not-exist"
expect_output 2 "開けない" "読めない記録は 1 と区別して落ちる" \
    "$PY_BIN" "$RECORD" "$WORK/unreadable"
expect_exit 2 "引数なしは 1 と区別して落ちる" "$PY_BIN" "$RECORD"
expect_exit 2 "引数が多すぎる場合も 1 と区別して落ちる" "$PY_BIN" "$RECORD" "$WORK/tmpl-12" "$R1"
# **ここは終了コードだけを見る。** どの経路で 2 になるかは環境で変わる——再帰上限に達すれば
# 境界が受け、達しなければ最上位の型検査が受ける（macOS は 10 万段でも読み切る）。例外名を
# 検査すると、緑が環境の性質を映すだけになる。境界そのものは上の unhashable-status と
# q-unhashable-key が例外名（TypeError）まで検査している。
expect_exit 2 "深いネストの JSON も 1 と区別して落ちる（経路は環境で変わる）" \
    "$PY_BIN" "$RECORD" "$WORK/deep"

echo "research-record.py"
RR="$CL/scripts/research-record.py"
RR_EX="$CL/templates/research-record.example.json"

expect_output 0 "これは品質・飽和の宣言ではない" "阻害なしを品質・飽和と名乗らない" \
    "$PY_BIN" "$RR" "$RR_EX"

# 記録の一部を壊した JSON をまとめて 1 プロセスで書き出す（生成のみ束ねる。理由は上の
# write_broken_records と同じ——検査はケースごとに分けたままにする）。
"$PY_BIN" - "$ROOT" "$WORK" <<'PY' || { echo "  FAIL 壊した研究記録を作れない"; fail=1; }
import json, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

# 手書きの deep copy を 1 本に寄せる（理由は上の `write_broken_records` の clone と同じ）。
def clone(x):
    return json.loads(json.dumps(x))
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
base = json.loads((root / "convergence-loops" / "templates/research-record.example.json").read_text(encoding="utf-8"))

NOT_RUN = {"status": "not_run", "reason": "収束しないまま報告の仕上げに来た"}


def all_unloaded(r):
    for c in r["claims"]:
        c["load_bearing"] = False
    r["process"]["unrefuted_load_bearing"] = []
    r["process"].pop("reason", None)


MUT = {
    # 記録の不正（exit 2）
    "rr-drop-claims": lambda r: r.pop("claims"),
    "rr-bad-verdict": lambda r: r["claims"][0].update(verdict="たぶん確証"),
    "rr-conf-without-conditions": lambda r: r["claims"][0].pop("conditions"),
    "rr-count-mismatch": lambda r: r["clusters"][0].update(claims_submitted=3),
    "rr-corrections-gap": lambda r: r.update(
        corrections=[{"no": 7, "text": "a"}, {"no": 9, "text": "b"}]
    ),
    "rr-corrections-bool": lambda r: r["corrections"][0].update(no=True),
    "rr-undeclared-unrefuted": lambda r: r["process"].update(unrefuted_load_bearing=[]),
    "rr-na-without-reason": lambda r: r.update(sampling={"status": "not_applicable"}),
    "rr-number-without-source": lambda r: r["numbers"][0].pop("source"),
    "rr-origin-missing": lambda r: r["constraints"][0].pop("origin"),
    "rr-heavy-without-cartographer": lambda r: r.update(thickness="重厚"),
    "rr-stopped-without-reason": lambda r: r["convergence"].update(outcome="stopped"),
    "rr-load-zero-undeclared": all_unloaded,
    "rr-decisions-empty": lambda r: r.update(
        decisions={"decide_now": [], "poc": [], "human_only": []}
    ),
    # 個別の検査を通り抜け、末尾の例外境界だけが受け止めるもの
    "rr-unhashable-declared": lambda r: r["process"].update(unrefuted_load_bearing=[["L2"]]),
    # 発行の阻害（exit 1）——記録としては正しいが、収束を名乗ったまま出してはいけない状態
    "rr-overturned": lambda r: r["sampling"].update(overturned=1),
    "rr-rederiver-fail": lambda r: r["gates"]["rederiver"].update(verdict="redesign-needed"),
    "rr-unrefuted-disagreement": lambda r: r["claims"][1].update(verdict="相違"),
    "rr-coldreader-fail": lambda r: r["gates"]["cold_reader"].update(
        rounds=[
            {"verdict": "redesign-needed", "findings": 8},
            {"verdict": "redesign-needed", "findings": 7},
        ]
    ),
    # 停止（未収束）の正直な申告は発行できる（exit 0）——収束の偽装だけを塞ぐ
    "rr-stopped-ok": lambda r: (
        r["gates"]["rederiver"].update(verdict="unverifiable"),
        r["convergence"].update(
            outcome="stopped", stopped_reason="独立出典が取れず rederiver が unverifiable"
        ),
    ),
    # 一度も走らずに止まった必須のゲートは not_run と理由で書ける（exit 0）。受けるのは止まった記録の必須のゲートだけ
    "rr-stopped-not-run-ok": lambda r: (
        r["gates"].update(cold_reader=dict(NOT_RUN)),
        r["convergence"].update(outcome="stopped", stopped_reason="上限に達した"),
    ),
    "rr-converged-not-run": lambda r: r["gates"].update(cold_reader=dict(NOT_RUN)),
    "rr-not-run-without-reason": lambda r: (
        r["gates"].update(cold_reader={"status": "not_run"}),
        r["convergence"].update(outcome="stopped", stopped_reason="上限に達した"),
    ),
    "rr-not-run-unrequired": lambda r: (
        r["gates"].update(cartographer=dict(NOT_RUN)),
        r["convergence"].update(outcome="stopped", stopped_reason="上限に達した"),
    ),
    # outcome の語彙は not_run の腕より先に確かめる（語彙外の outcome を「収束を名乗る」と読み違えない）
    "rr-outcome-unknown-with-not-run": lambda r: (
        r["gates"].update(cold_reader=dict(NOT_RUN)),
        r["convergence"].update(outcome="done"),
    ),
    # 結末が未決の記録（走っている run の途中の仕上げ。主張もクラスタも作りかけ）は、作りかけのフィールドより先に未決で落ちる
    "rr-outcome-undecided-midway": lambda r: (
        r.update(claims=[], clusters=[]),
        r["convergence"].update(outcome=None),
    ),
    # convergence とゲートの形の検査。形が崩れた記録を末尾の例外境界（想定外の例外）に落とさず、名指しで落とす
    "rr-convergence-not-object": lambda r: r.update(convergence=[]),
    "rr-rounds-total-zero": lambda r: r["convergence"].update(rounds_total=0),
    "rr-consecutive-zero-missing": lambda r: r["convergence"].pop("consecutive_zero"),
    "rr-gate-not-object": lambda r: r["gates"].update(rederiver="pass"),
}
for name, mutate in MUT.items():
    rec = clone((base))
    mutate(rec)
    (work / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
PY

# 記録の不正（exit 2）。期待メッセージまで検査する理由は review-record.py のセクションと同じ。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "不正な研究記録は 1 と区別して落ちる: $m" "$PY_BIN" "$RR" "$WORK/$m.json"
done <<'CASES'
rr-drop-claims|必須のフィールド 'claims' が無い
rr-bad-verdict|verdict が不正
rr-conf-without-conditions|'conditions' が空か文字列でない
rr-count-mismatch|判定の欠落を「なし」と読むな
rr-corrections-gap|連番でない
rr-corrections-bool|'no' が 1 以上の整数でない
rr-undeclared-unrefuted|申告も無い
rr-na-without-reason|「該当なし+理由」
rr-number-without-source|'source' が空か文字列でない
rr-origin-missing|origin が不正
rr-heavy-without-cartographer|盲点ゼロを名乗るな
rr-stopped-without-reason|'stopped_reason' が空か文字列でない
rr-load-zero-undeclared|'load_zero_reason' が空か文字列でない
rr-decisions-empty|3 分類に仕分けろ
rr-unhashable-declared|想定外の例外（TypeError）
rr-converged-not-run|収束を名乗りながらゲート 'cold_reader' を飛ばしている
rr-not-run-without-reason|'reason' が空か文字列でない
rr-not-run-unrequired|走らせないゲート 'cartographer' を飛ばしたと名乗っている
rr-outcome-unknown-with-not-run|convergence.outcome が不正
rr-outcome-undecided-midway|convergence.outcome が未決
rr-convergence-not-object|'convergence' が object でない
rr-rounds-total-zero|convergence: 'rounds_total' が 1 以上の整数でない
rr-consecutive-zero-missing|convergence: 'consecutive_zero' が 0 以上の整数でない
rr-gate-not-object|gates.rederiver が object でない
CASES

# 発行の阻害（exit 1）。記録の不正（2）と混ぜない——直すべき対象が違う。
while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 1 "$msg" "発行を妨げる状態は 2 と区別して報せる: $m" "$PY_BIN" "$RR" "$WORK/$m.json"
done <<'CASES'
rr-overturned|飽和ではない
rr-rederiver-fail|収束を名乗っている
rr-unrefuted-disagreement|反証を経ていない
rr-coldreader-fail|cold-reader が pass していない
CASES

expect_output 0 "停止（未収束）の申告つきで発行できる" "非収束の停止は記録を偽らずに出せる" \
    "$PY_BIN" "$RR" "$WORK/rr-stopped-ok.json"
expect_output 0 "停止（未収束）の申告つきで発行できる" "止まった記録は走らなかった必須のゲートを not_run と理由で出せる" \
    "$PY_BIN" "$RR" "$WORK/rr-stopped-not-run-ok.json"

expect_exit 2 "引数なしは 1 と区別して落ちる" "$PY_BIN" "$RR"
expect_exit 2 "引数が多すぎる場合も 1 と区別して落ちる（研究記録）" "$PY_BIN" "$RR" "$RR_EX" "$RR_EX"
expect_output 2 "開けない" "存在しない研究記録は 1 と区別して落ちる" \
    "$PY_BIN" "$RR" "$WORK/rr-does-not-exist.json"
expect_exit 2 "深いネストの研究記録も 1 と区別して落ちる（経路は環境で変わる）" \
    "$PY_BIN" "$RR" "$WORK/deep.json"

echo "doctor-record.py"
DR="$CL/scripts/doctor-record.py"
DR_EX="$CL/templates/doctor-record.example.json"

expect_output 0 "これは品質・飽和の宣言ではない" "阻害なしを品質・飽和と名乗らない（診断記録）" \
    "$PY_BIN" "$DR" "$DR_EX"

"$PY_BIN" - "$ROOT" "$WORK" <<'PY' || { echo "  FAIL 壊した診断記録を作れない"; fail=1; }
import json, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

def clone(x):
    return json.loads(json.dumps(x))
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
base = json.loads((root / "convergence-loops" / "templates/doctor-record.example.json").read_text(encoding="utf-8"))

UNVERIFIED = {
    "key": "断面から生えた新候補（次ラウンド対象）",
    "height": 1,
    "verdict": "未検証",
    "confidence": "仮説",
    "weight": None,
    "parent": None,
    "evidence": "走査の断面で観測",
}

MUT = {
    # 記録の不正（exit 2）
    "dr-drop-nodes": lambda r: r.pop("nodes"),
    "dr-bad-verdict": lambda r: r["nodes"][0].update(verdict="たぶん推奨"),
    "dr-conditional-without-condition": lambda r: r["nodes"][1].pop("condition"),
    "dr-parent-missing": lambda r: r["nodes"][1].update(parent="存在しない親"),
    "dr-scout-unreturned-not-unseen": lambda r: r["scouts"][0].update(candidates_returned=False),
    "dr-height-five": lambda r: r["nodes"][0].update(height=5),
    "dr-oneshot-on-rejected": lambda r: r["oneshot"].update(
        key="log_service/logger 置換案: 例外の握り潰しを logger 化する"
    ),
    "dr-votes-two": lambda r: r["oneshot"].update(votes=["票1", "票2"]),
    "dr-escalation-stale": lambda r: r["nodes"][0].update(weight="ライブラリ級"),
    "dr-modcheck-restored-without-note": lambda r: r.update(mod_check={"status": "restored"}),
    "dr-rescan-empty": lambda r: r["rescan"].update(coverage=" "),
    # 発行の阻害（exit 1）——飽和を名乗ったまま出してはいけない状態
    "dr-unverified-node": lambda r: r["nodes"].append(dict(UNVERIFIED)),
    "dr-sampling-na": lambda r: r.update(
        sampling={"status": "not_applicable", "reason": "新規ゼロが自明なので省いた"}
    ),
    "dr-cart-fail": lambda r: r["gates"]["cartographer_comparison"].update(verdict="redesign-needed"),
    "dr-overturned": lambda r: r["sampling"].update(overturned=2),
    # 停止（未飽和）の正直な申告は発行できる（exit 0）
    "dr-stopped-ok": lambda r: (
        r["gates"]["cold_reader"]["rounds"].append({"verdict": "redesign-needed", "findings": 4}),
        r["convergence"].update(outcome="stopped", stopped_reason="軽量段の 1 ラウンド打ち切り（設計どおり）"),
    ),
}
for name, mutate in MUT.items():
    rec = clone((base))
    mutate(rec)
    (work / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
PY

while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "不正な診断記録は 1 と区別して落ちる: $m" "$PY_BIN" "$DR" "$WORK/$m.json"
done <<'CASES'
dr-drop-nodes|必須のフィールド 'nodes' が無い
dr-bad-verdict|verdict が不正
dr-conditional-without-condition|'condition' が空か文字列でない
dr-parent-missing|が nodes に無い
dr-scout-unreturned-not-unseen|「見つからなかった」と読むな
dr-height-five|高さは固定 4 段
dr-oneshot-on-rejected|一撃に選べるのは推奨・条件付きのノードだけ
dr-votes-two|3 票
dr-escalation-stale|申告の腐り
dr-modcheck-restored-without-note|'note' が空か文字列でない
dr-rescan-empty|'coverage' が空か文字列でない
CASES

while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 1 "$msg" "飽和の偽装は 2 と区別して報せる: $m" "$PY_BIN" "$DR" "$WORK/$m.json"
done <<'CASES'
dr-unverified-node|飽和は全ノードに判定が付いてから
dr-sampling-na|抜き取り検査が要る
dr-cart-fail|pass していないのに飽和を名乗っている
dr-overturned|飽和ではない
CASES

expect_output 0 "停止（未飽和）の申告つきで発行できる" "非飽和の停止は記録を偽らずに出せる" \
    "$PY_BIN" "$DR" "$WORK/dr-stopped-ok.json"
expect_exit 2 "引数なしは 1 と区別して落ちる（診断記録）" "$PY_BIN" "$DR"
expect_exit 2 "深いネストの診断記録も 1 と区別して落ちる（経路は環境で変わる）" \
    "$PY_BIN" "$DR" "$WORK/deep.json"

echo "firstread-record.py"
FR="$CL/scripts/firstread-record.py"

# `pre_answers` は実在パスを要求する（**頭の中に置くのを許さない**のがこのフィールドの趣旨）。
# テンプレートは雛形であって実行可能な記録ではないので、ここで実在パスへ差し替える。
"$PY_BIN" - "$ROOT" "$WORK" <<'PY' || { echo "  FAIL 壊した初読記録を作れない"; fail=1; }
import json, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

def clone(x):
    return json.loads(json.dumps(x))
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])

pre = work / "pre-answers.md"
pre.write_text("先に書いた答え（読み役の答えを見る前に書いたもの）\n", encoding="utf-8")

def read(n):
    r = json.loads((root / "convergence-loops" / f"templates/firstread-round-{n}.example.json").read_text(encoding="utf-8"))
    r["pre_answers"] = str(pre)
    return r

r1, r2 = read(1), read(2)
(work / "fr-1.json").write_text(json.dumps(r1, ensure_ascii=False), encoding="utf-8")
(work / "fr-2.json").write_text(json.dumps(r2, ensure_ascii=False), encoding="utf-8")

MUT = {
    # 記録の不正（exit 2）
    "fr-drop-materials": lambda r: r.pop("materials"),
    "fr-drop-skipped": lambda r: r["materials"].pop("skipped"),
    "fr-none-without-asked": lambda r: r["materials"].__setitem__("ideas", {"status": "none"}),
    "fr-item-no-key": lambda r: r["materials"]["stopped"]["items"][0].pop("key"),
    "fr-item-no-verbatim": lambda r: r["materials"]["stopped"]["items"][0].pop("verbatim"),
    "fr-pre-answers-gone": lambda r: r.update(pre_answers=str(work / "書いていない.md")),
    "fr-no-profile": lambda r: r.update(reader_profile=""),
    "fr-no-scope": lambda r: r.update(scope=[]),
    "fr-no-in-scope": lambda r: r["materials"]["stopped"]["items"][0].pop("in_scope"),
    "fr-outside-no-disposition": lambda r: r["materials"]["stopped"]["items"][1].pop("disposition"),
    "fr-bad-verdict": lambda r: r["unresolved"][0].update(verdict="たぶん書き落とし"),
    "fr-round-zero": lambda r: r.update(round=0),
    "fr-no-size": lambda r: r.pop("size"),
    "fr-empty-errands": lambda r: r.update(errands=[]),
    "fr-writeup-no-written": lambda r: r["unresolved"][0].update(verdict="missing_writeup"),
    # 収束の阻害（exit 1）
    "fr-not-asked": lambda r: r["materials"].__setitem__(
        "skipped", {"status": "not_asked", "reason": "聞き忘れた"}
    ),
    "fr-errand-lost": lambda r: r["errands"][0].update(found=False, reached=""),
    "fr-writeup-unwritten": lambda r: r["unresolved"][0].update(
        verdict="missing_writeup", written=False
    ),
    "fr-git-unchecked": lambda r: r.update(git_status_match=False),
}
for name, mutate in MUT.items():
    rec = clone((r1))
    mutate(rec)
    (work / f"{name}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")

# 周をまたぐ検査は 2 周目の側を壊す。
same = clone((r1)); same["round"] = 2
(work / "fr-same-stuck.json").write_text(json.dumps(same, ensure_ascii=False), encoding="utf-8")

new = clone((r2))
new["materials"]["stopped"]["items"].append(
    {"key": "rollback/前提が逆順", "verbatim": "戻す手順が、出す手順を読んだ前提で書かれていた",
     "in_scope": True}
)
(work / "fr-new-stuck.json").write_text(json.dumps(new, ensure_ascii=False), encoding="utf-8")

# 削除も移動も無いまま行数だけ増えた周。**阻害要因ではないが報せる。**
grew = clone((r2))
grew["size"] = {"lines_before": 138, "lines_after": 150}
grew["removed"] = []
grew["moved"] = []
(work / "fr-grew-only.json").write_text(json.dumps(grew, ensure_ascii=False), encoding="utf-8")
PY

expect_output 0 "これは収束の宣言ではない" "阻害なしを収束と名乗らない（初読記録）" \
    "$PY_BIN" "$FR" "$WORK/fr-2.json" "$WORK/fr-1.json"

while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 2 "$msg" "不正な初読記録は 1 と区別して落ちる: $m" "$PY_BIN" "$FR" "$WORK/$m.json"
done <<'CASES'
fr-drop-materials|必須のフィールド 'materials' が無い
fr-drop-skipped|素材 'skipped' の返答が無い
fr-none-without-asked|status=none なので 'asked' が要る
fr-item-no-key|key が無い
fr-item-no-verbatim|読み役の原文
fr-pre-answers-gone|'pre_answers' の指す先が無い
fr-no-profile|前提の線を引かない
fr-no-scope|'scope' が空
fr-no-in-scope|'in_scope' が真偽値でない
fr-outside-no-disposition|'disposition'（行き先
fr-bad-verdict|verdict が不正
fr-round-zero|'round' が 1 以上でない
fr-no-size|'size' が object でない
fr-empty-errands|'errands' が空
fr-writeup-no-written|書き足したかの 'written' が要る
CASES

while IFS='|' read -r m msg; do
    [ -n "$m" ] || continue
    expect_output 1 "$msg" "収束の偽装は 2 と区別して報せる: $m" "$PY_BIN" "$FR" "$WORK/$m.json"
done <<'CASES'
fr-not-asked|素材 'skipped' を聞いていない
fr-errand-lost|用事が片づいていない
fr-writeup-unwritten|書き落としのまま
fr-git-unchecked|書き換えていないことを確かめていない
CASES

expect_output 0 "範囲の外へ出したもの" "範囲外の詰まりは 2 周続いても収束を妨げない（行き先だけ報せる）" \
    "$PY_BIN" "$FR" "$WORK/fr-2.json" "$WORK/fr-1.json"
expect_output 1 "同じ場所でまた詰まった" "直し方が効いていないことを報せる" \
    "$PY_BIN" "$FR" "$WORK/fr-same-stuck.json" "$WORK/fr-1.json"
expect_output 1 "新しい詰まり" "新規の詰まりは収束を妨げる" \
    "$PY_BIN" "$FR" "$WORK/fr-new-stuck.json" "$WORK/fr-1.json"
expect_output 0 "足す側に偏っている" "削除も移動も無い増加を報せる（阻害要因にはしない）" \
    "$PY_BIN" "$FR" "$WORK/fr-grew-only.json" "$WORK/fr-1.json"
expect_exit 2 "引数なしは 1 と区別して落ちる（初読記録）" "$PY_BIN" "$FR"

# review-loop の手順書は、本文（skills/review-loop/SKILL.md）と段ごとの別ファイル（references/）に分けてある。
# 文言のチェックは、全部を繋いだ写しに当てる（どの段のファイルに在っても落ちたら赤）。
cat "$CL/skills/review-loop/SKILL.md" "$CL"/skills/review-loop/references/*.md > "$WORK/review-loop-all.md"
expect_output 0 "ok" "閉鎖の実証とゲートの赤の確認が、腕ごと・箇所ごとを要求している" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '不変条件を共有する箇所を先に全部挙げ' in t, '閉鎖の実証が「1 つ」で止まってよい文面に戻っている'
assert '条件の腕ごとに 1 つずつ' in t, 'ゲートの赤の確認が腕ごとを要求していない'
assert '退行を 1 つ注入して' not in t, '古い「退行を 1 つ」の文面が残っている'
print('ok')" "$WORK/review-loop-all.md"
# 実走で出た 3 つの穴（別セッションと私が独立に踏んだ）。ツールを渡して隔離を指示に落とす・品質の
# ツールが木を動かす・仕掛けが壊れて全腕が同じ色に出る、のどれも「空振りが合格に見える」形。
expect_output 0 "ok" "実走で出た 3 つの穴（貼れない差分・品質のツール・対照の緑）が手順書に書いてある" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert 'この役にツールを渡して解決するな——貼る側を割れ' in t, '貼り切れない差分の扱いが無い（道具を渡す形に倒れる）'
assert 'P1 では指摘だけ返す形で呼べ' in t, '品質のツールが P1 で木を動かす形のまま'
assert '壊していない写しでも 1 本走らせて緑を確認しろ' in t, '対照の緑が無い（仕掛けの空振りを合格と読める）'
print('ok')" "$WORK/review-loop-all.md"
# 「見つけた周に直したものをどう書くか」が無いと、実行者は「直したのに阻害が残る」を不具合と読んで
# ラベルを軽い側へ倒す＝writer が採点する形になる（実測: 別の実行者が、どこにも書かれていない慣習として
# その倒し方を踏襲していた）。設計どおりだと明記した一文が落ちないよう縛る。
expect_output 0 "ok" "見つけた周に直しても記録は判定どおり書く、と手順書が言っている" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '見つけた周の記録は、その周に直していても判定どおり書け' in t, '直した周の記録の書き方が無い'
assert '直した周が阻害要因ありで終わるのは設計どおり' in t, '阻害が残るのが設計どおりだと書かれていない'
print('ok')" "$WORK/review-loop-all.md"
# 入口の説明（README）と手順書がずれると、読者はもう無い検証を信じたまま使う。実測: 手順書を
# 差し替えたのに README だけ旧方式の現在形（「剥がした写しを精読させ、削る」）で残っていた——
# チェックが手順書にしか掛かっておらず、README は素通りだった。
expect_output 0 "ok" "README の入口の説明が、今の前段（名指しさせる形）と揃っている" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '剥がした写しを精読' not in t, 'README が落とした仕掛けを現在形で説明している'
assert 'name where the same content already lives' in t, 'README が今の前段を説明していない'
print('ok')" "$CL/README.md"
# 前段が取れないと R1 の verdict ごと not_run に倒す形は、not_run が阻害要因なので「安全側に
# 倒したつもりが収束不能」になる（実測）。前段の仕掛けを差し替えたときにこの規定も一緒に落ちた——
# 仕掛けが変わっても壊れ方は同じなので、一般の形で縛り直す。
expect_output 0 "ok" "前段が取れなくても R1 の verdict までは倒さない規定が在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert 'verdict まで \`not_run\` に倒すな' in t, '前段の失敗で verdict ごと倒す形に戻っている'
assert '収束できなかった' in t, '倒すと収束不能になる実測が落ちている'
print('ok')" "$WORK/review-loop-all.md"
# 「差分だけを見るな」は依頼者の逐語（「差分にしか触れないのはダメ」）に対する規定で、0.22.0 まで
# R1 前段に在った。自作の仕掛けを消したときに一文ごと落ちた——**視野を狭めるなと書いた同じ差分で、
# 視野を狭める削除をしていた**。落ちても何も赤くならなかったので、ここで縛る。
expect_output 0 "ok" "対象差分が視野の線でないこと（差分だけを貼るな）が手順書に在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '「どこまで見るか」の線ではない' in t, '対象差分を視野の線と読める状態に戻っている'
assert '差分だけを貼って済ませるな' in t, 'リポジトリを読める役に差分だけを渡す禁止が無い'
assert '理解に要る限り依存先・近傍・呼び元まで読ませろ' in t, '差分の外まで読ませる指示が無い'
print('ok')" "$WORK/review-loop-all.md"
# 集める側で範囲を切ると、切った外は判定役の目に一度も入らない。実測: 「import している依存に
# 限れ」と書いていたため、自分で依存に宣言していた役が集合の外に落ち、3 ラウンド続けて
# 「再発明は該当なし」が返った。線を動かすのでなく、線を引くのをやめて範囲の申告に替えたことを縛る。
expect_output 0 "ok" "探す役に見るなの線を引かず、見た範囲と見ていない範囲を返させる規律が在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '探す役に「ここは見るな」の線を writer が引くな' in t, '集める側で範囲を切らない規律が無い'
assert '見た範囲と、見ていない範囲を返させろ' in t, '範囲の申告を求めていない'
assert '限れ**——差分から機械的に導ける集合で' not in t, '古い「import している依存に限れ」が残っている'
print('ok')" "$WORK/review-loop-all.md"
# 人はラウンドの間ずっと別の作業をしていて、報告を読む時点で文脈を持っていない。内部の語彙で
# 書かれた問いは決められないし、急ぎと後回しを混ぜて並べるとどれも決まらない。この規定が
# 落ちると、聞く側は書けたつもりで出し、聞かれた側は初見で読めないまま放置になる。
expect_output 0 "ok" "人に聞くところを、初見で決められる形にする規定が手順書に在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert 'ループを見ていない人が初見で読んで決められる形' in t, '初見で決められる形にする要求が無い'
assert '急ぐものと後でよいものを分け、件数を先に言え' in t, '急ぎと後回しを分ける要求が無い'
assert '内部の語彙を使わずに言えないなら、まだ問いになっていない' in t, '内部語彙の禁止が無い'
assert 'cold-reader' in t and '人に聞くところの本文だけ' in t, '出す前に文脈ゼロの読み手に当てる検査が無い'
print('ok')" "$WORK/review-loop-all.md"
# この規定が落ちると、writer が「もう聞くしかない」と決めてループを止める形に戻る
# （なぜ立った周に聞かないかの実測は、手順書の「停止条件」が正本）。
expect_output 0 "ok" "人に聞く候補を立った周に聞かず、台帳に載せて次の周の judge に再審させる規定が手順書に在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '問いの台帳の再審' in t, '保留した問いを次の周の judge が再審する段が無い'
assert '答え無しに進める仕事' in t, '人に聞く時を機械の帰属で決める規定が無い'
assert '決定を待て' not in t, '岐路で止めて決定を待つ古い文面が残っている'
assert 'ユーザーに判断を仰げ' not in t, '停止条件が「立った周に聞く」形のまま'
assert 'ループが自分で決めたこと' in t, 'ループが決めた問いを人が覆せる形で見せる規定が無い'
assert '台帳全体を並べてブランチ同士を見ろ' in t, '問い同士のシナジー（横断の突合）を見る段が無い'
assert 'ask_human' not in t, '0.27 までの unit.ask_human が手順書に残っている'
print('ok')" "$WORK/review-loop-all.md"
# **観点の正本（REVIEW.md）も対象に入れる。** 0.28.0 ではここだけチェックの外で、手順書が split の正本として
# 名指ししている段が 0.27 の機構（人に諮る印・ループは止めず最終報告で聞く）のまま残っていた——
# 正本どおりに書くと記録が不正になる形が、唯一見られていないファイルに残っていた。
expect_output 0 "ok" "README・customize・観点の正本が、問いの台帳（立った周に聞かない）を説明している" "$PY_BIN" -c "
import sys, pathlib
# 対象が 0 件なら本体が一度も回らず ok を出す形（隣のチェックは sys.argv[1] を直接引くので
# 引数欠落で落ちる）。同じ差分の中で防御の向きを揃える。
assert sys.argv[1:], '検査の対象が渡されていない'
for f in sys.argv[1:]:
    t = pathlib.Path(f).read_text(encoding='utf-8')
    assert '問いの台帳' in t, f + ' が問いの台帳を説明していない'
    assert 'ask_human' not in t, f + ' に 0.27 までの ask_human が残っている'
print('ok')" "$CL/README.md" "$CL/docs/customize.md" "$CL/REVIEW.md"
# R1 の前段は、既に依存に入っている comment-analyzer に寄せた。呼び出し時に足す 3 つが
# 落ちると、削除の提案が意見のままになり（在り処を名指ししない）、迷ったときに残す側へ倒れる
# （残す判断に義務が無い）。自作の剥がす仕掛けに戻っていないことも同時に縛る。
expect_output 0 "ok" "R1 の前段が comment-analyzer に寄せてあり、足すべき 3 つが落ちていない" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert 'comment-analyzer' in t, 'R1 の前段が既存の役に寄せられていない'
assert '同じ内容がどこにあるかを名指しさせる' in t, '削除候補に在り処を名指しさせる要求が無い'
assert '運んでいる事実を一文で言わせる' in t, '残す判断の側に義務が無い（残す側に倒れる）'
assert 'strip-comments' not in t, '自作の剥がす仕掛けに戻っている'
print('ok')" "$WORK/review-loop-all.md"
# 「過去の [block] が記録から消えた」は機械が数えられない（和なら永久に残り、隣接なら 1
# ラウンドで会計から落ちる。どちらも実測）。数えない代わりに judge に振り分けさせる義務が
# 手順書から落ちると、未閉鎖の [block] が無言で記録から抜ける（実測 3 件）。
expect_output 0 "ok" "過去ラウンドの [block] の一覧を、台帳と同じルーターに掛ける義務が手順書に在る" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '同じルーターを、過去ラウンドの \`[block]\` キーにも課せ' in t, '過去の [block] の振り分けが judge の義務になっていない'
assert '機械はこの一覧を数えない' in t, '数えない理由が書かれていない（次に「積め」と直される）'
print('ok')" "$WORK/review-loop-all.md"
# ゲートの赤の確認を共有の木でやると、同時に読んでいる役が壊れた瞬間を踏む。順序の約束は
# 守ったかを確かめられないので、写しの上で壊す形に固定した。戻ると赤くする。
expect_output 0 "ok" "ゲートの赤の確認が、本物でなく写しの上で壊すことを要求している" "$PY_BIN" -c "
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')
assert '腕ごとにリポジトリの写しを' in t and 'の下に作り、写しの上で壊して' in t, '写しの上で壊す指示が無い'
assert 'mktemp -d' in t, '写しの置き場所が指定されていない（リポジトリ内に作ると突合が汚れる）'
assert '並行起動した grader が全部返ったあとに行え' not in t, '順序の約束だけで塞ぐ古い文面が残っている'
print('ok')" "$WORK/review-loop-all.md"

# Python の docstring 判定を、綴りでなく**判定結果**で突く。以前は剥がす側（自作の
# strip-comments.py）と条件が同じかを正規表現で見ていたが、剥がす側ごと落としたので、
# 数える側の挙動そのものを固定する。
DSREPO="$WORK/docstring-cross"
mkdir -p "$DSREPO"
(
    cd "$DSREPO" || exit 1
    git init -q . && git config user.email t@t && git config user.name t
    : > .keep && git add -A && git commit -qm base
    printf '"""mod doc"""\ndef f():\n    """doc\n    two"""\n    s = """not doc"""\n    return s\n# tail comment\n' > d.py
    git add -A
) >/dev/null 2>&1
DSBASE=$(git -C "$DSREPO" rev-parse HEAD)
# 数える側: 追加 7 行のうち注釈は 4 行（module docstring 1・関数 docstring 2・# 行 1）。
# 代入の右辺の文字列は注釈ではない。
expect_output 0 "追加行 7 / 注釈 4 (57%)" "数える側の docstring 判定（代入の文字列は注釈にしない）" \
    bash -c "cd '$DSREPO' && bash '$CL/scripts/comment-ratio.sh' '$DSBASE'"

echo "comment-ratio.sh"
REPO="$WORK/repo"
mkdir -p "$REPO"
(
    cd "$REPO" || exit 1
    git init -q . && git config user.email t@t && git config user.name t
    echo "x = 1" > a.py
    git add -A && git commit -qm base
    # Python は tokenize、Go は C 系コメントとして数える。既存行 x = 1 は差分に載らない。
    printf '"""docstring は注釈。"""\n# 行コメントも注釈。\nx = 1\n' > a.py
    printf '// Go の行コメント\nfunc f() {}\n' > b.go
    git add -A
) >/dev/null 2>&1
BASE=$(git -C "$REPO" rev-parse HEAD)
expect_output 0 "追加行 4 / 注釈 3 (75%)" "Python と C 系の注釈を数える" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' '$BASE'"
expect_output 0 "scalars: added_lines=4 comment_lines=3 comment_ratio_pct=75" "規模の数値を名前つきで出す（写す側が名付けない）" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' '$BASE'"

# 対象言語の追加行が無い正常系。**$ROOT でなく使い捨てリポジトリで測る**——$ROOT だと
# 開発中の未コミット変更の有無で結果が変わり、検査が環境依存になる。
git -C "$REPO" commit -qm change >/dev/null 2>&1
expect_output 0 "追加行なし" "対象言語の追加行が無ければそう言う" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' HEAD"
expect_output 0 "scalars: added_lines=0 comment_lines=0" "追加行が無い回も規模の数値を名前つきで出す（比は定義できないので出さない）" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' HEAD"

# 未追跡の対象言語ファイルは計測漏れ。**止めるのは「計測漏れの 0」と「本当に 0」が
# 原理的に区別できない場合だけ**——数えられているなら列挙して見せる（無関係な下書きで
# P4 が毎回止まると、手順そのものが成立しない）。
printf 'y = 2\n' > "$REPO/untracked.py"
expect_output 2 "計測漏れと区別できない" "追加行が無く未追跡の対象ファイルがあれば落ちる" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' HEAD"
expect_output 0 "未計測（未追跡・差分に載っていない）: untracked.py" \
    "数えられるなら止めずに未計測分を列挙する" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' '$BASE'"
# ref 間比較は作業ツリーを見ないので、未追跡ファイルが在っても対象外（短絡が効いているか）。
expect_output 0 "追加行なし" "ref を指定した比較では未追跡ファイルを見ない" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' HEAD HEAD"
rm -f "$REPO/untracked.py"

# 計測不成立は必ず 2。**旧版はここが exit 1 だった**（`raise SystemExit(str)` の既定）ので、
# 「測れなかった」と「注釈 0%」が終了コードで区別できなかった。
# 引数の誤りも計測不成立なので 2。bash の `${1:?...}` は exit 1 になるため使えない。
expect_output 2 "usage" "引数なしは 1 と区別して落ちる" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh'"
expect_output 2 "usage" "引数が多すぎる場合も 1 と区別して落ちる" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' HEAD HEAD extra"
expect_output 2 "が失敗" "不正な ref は 1 と区別して落ちる" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
printf 'def f(\n' > "$REPO/broken.py"
git -C "$REPO" add -A >/dev/null 2>&1
expect_output 2 "解析できない（構文エラー）" "解析できない Python は 1 と区別して落ちる" \
    bash -c "cd '$REPO' && bash '$CL/scripts/comment-ratio.sh' HEAD"
git -C "$REPO" rm -q -f --cached broken.py >/dev/null 2>&1
rm -f "$REPO/broken.py"

echo "マニフェストと参照の整合"
# ルートの README の表は marketplace.json の要約。プラグインを足した周に表を忘れると、数と表がずれたまま残った
# （実測 2026-10-14: 「配るプラグインは 5 本」のまま works・works-factory・works-dispatch が載っていなかった）
# 本数の文は日本語の形と英語の形（README を英語にする周、受付 da159a）の両方を認める
expect_output 0 "README_PLUGINS_OK" "ルートの README の表と本数が、marketplace.json のプラグインと揃う" "$PY_BIN" - "$ROOT" <<'PY'
import json, re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
names = [p["name"] for p in json.loads((root/".claude-plugin/marketplace.json").read_text(encoding="utf-8"))["plugins"]]
readme = (root/"README.md").read_text(encoding="utf-8")
rows = re.findall(r"^\| \*\*([^*]+)\*\* \|", readme, re.M)
count = re.search(r"配るプラグインは (\d+) 本", readme) or re.search(r"ships (\d+) plugins", readme)
assert sorted(rows) == sorted(names), f"README の表 {sorted(rows)} と marketplace.json {sorted(names)} が違う"
assert count and int(count.group(1)) == len(names), f"README の本数 {count and count.group(1)} と marketplace.json の {len(names)} 本が違う"
print("README_PLUGINS_OK", len(names))
PY
# 依存と借り物は、リポジトリの実物で照合する。coldwrite を退かせた周（0.2.0 でフックを外した）に、works の依存と借りる一覧
# （borrow.json。PreToolUse:Write のフックを名指していた）が残り、works の実行が AI を起動する前の確かめで止まった。works の試験は
# 偽のプラグインで回るので見えず、CI は緑だった（実測 2026-10-15）
expect_output 0 "DEPS_REAL_OK" "raiki61 の依存は中身の在るプラグインを指し、works が借りる名前（hook・agent）はリポジトリの実物に在り、依存と一致する" "$PY_BIN" - "$ROOT" <<'PY'
import importlib.util, json, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.dont_write_bytecode = True
root = pathlib.Path(sys.argv[1])
mk = json.loads((root/".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
src = {p["name"]: root / p["source"] for p in mk["plugins"]}
def plugin(name):
    return json.loads((src[name]/".claude-plugin/plugin.json").read_text(encoding="utf-8"))
def hollow(d):
    """フックも agent・command・skill も持たない（退いた最終版の形）"""
    hooks = d/"hooks"/"hooks.json"
    has_hooks = hooks.is_file() and bool(json.loads(hooks.read_text(encoding="utf-8")).get("hooks"))
    return not has_hooks and not any((d/k).is_dir() and any((d/k).rglob("*.md")) for k in ("agents", "commands", "skills"))
bad = []
for name in src:
    for dep in plugin(name).get("dependencies") or []:
        if dep.get("marketplace") != mk["name"]:
            continue
        if dep["name"] not in src:
            bad.append(f"{name} の依存 {dep['name']} が marketplace.json に無い")
        elif hollow(src[dep["name"]]):
            bad.append(f"{name} の依存 {dep['name']} は中身の無いプラグイン（退いた版）")
spec = importlib.util.spec_from_file_location("toolset", root/"works/dev/toolset.py")
toolset = importlib.util.module_from_spec(spec); spec.loader.exec_module(toolset)
borrow = toolset.load_borrow(root/"works")
plugins = {n: i for n, i in borrow.items() if i["kind"] == "plugin"}
deps = {d["name"] for d in plugin("works").get("dependencies") or []}
if set(plugins) != deps:
    bad.append(f"works の借りる plugin {sorted(plugins)} と依存 {sorted(deps)} が違う")
for n, item in sorted(plugins.items()):
    if item["marketplace"] == mk["name"]:
        missing = toolset._missing_names(n, item, src[n]) if n in src else [f"marketplace.json に {n} が無い"]
        bad += [f"works が借りる {n} に {m} が無い" for m in missing]
assert not bad, "\n".join(bad)
print("DEPS_REAL_OK", len(plugins))
PY
expect_exit 0 "marketplace.json / plugin.json が必須のフィールドを持つ" "$PY_BIN" - "$ROOT" <<'PY'
import json, re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
mk = json.loads((root/".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
# owner はこれが無いと `claude plugin marketplace add` が schema 違反で落ちる（実測）。
for key in ("name", "owner", "plugins"):
    assert key in mk, f"marketplace.json に {key} が無い"
assert isinstance(mk["owner"], dict) and mk["owner"].get("name"), "owner は name を持つ object"
assert mk["plugins"], "plugins が空"
# 一覧から外した plugin の名前は、残した名前か null へ付け替えて残す（公式 code.claude.com/docs/en/plugins/host-marketplace
# 「Rename or remove a plugin」: 無いと入れていた利用者に "not found in marketplace" が出る。行き先が一覧に無い鎖は
# `claude plugin validate` が "chain does not resolve" で弾くが、CI に claude は無いのでここで同じ形を見る）
listed = {p["name"] for p in mk["plugins"]}
renames = mk.get("renames") or {}
for old_name, to in renames.items():
    assert old_name not in listed, f"renames の {old_name} が plugins にまだ在る"
    seen_names = {old_name}
    while to is not None and to not in listed:
        assert to in renames and to not in seen_names, f"renames.{old_name}: 行き先が plugins にも null にも着かない"
        seen_names.add(to); to = renames[to]
pl = json.loads((root/"convergence-loops/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
for key in ("name", "version", "description"):
    assert key in pl, f"plugin.json に {key} が無い"

# **同梱プラグインも版を宣言する。** 利用者が『手元の実体と配布の実体が同じか』を見分ける手段は
# version だけで、docs/loop-graph/README.md はその見分け方を読者に約束している。宣言が欠けると
# 見分けようがない（挙動を変えたのに版を上げ忘れる形は、履歴を見る下の VERSION_BUMP_OK が止める。
# ここで見るのは宣言の実在まで）。
import re as _re
def _bad_version(d):
    """版の宣言として受け取れない理由（無ければ None）。**チェックの射程を標本で示す**ためにここに切り出す。"""
    if not d.get("version"):
        return "version が無い"
    if not _re.fullmatch(r"\d+\.\d+\.\d+", d["version"]):
        return f"version が x.y.z でない: {d['version']!r}"
    return None
# **チェックそのものを標本で測る**（違反が今 0 件でも、チェックが生きていることを毎回踏む）
assert _bad_version({}) and _bad_version({"version": ""}) and _bad_version({"version": "1.2"}) \
    and _bad_version({"version": "v1.2.3"}), "版のチェックが、宣言の欠けや形の違いを拾えていない"
assert _bad_version({"version": "0.15.0"}) is None, "版のチェックが、正しい宣言まで拾っている"
# **配る plugin の一覧は marketplace.json の plugins[] から導く。** glob の列挙も残し、一覧に無い置き場も照合する。
_dist = {}
for p in mk["plugins"]:
    src = p.get("source")
    assert isinstance(src, str) and src.startswith("./"), \
        f"marketplace.json の {p.get('name')} の source が ./ で始まる置き場でない: {src!r}（検査は手元の置き場だけを照合できる）"
    # ルートを source にすると、キャッシュに写るのがリポジトリの木の全部になる（他の plugin・tests/・docs/ まで。2026-10-15 に 1 版 35MB を実測）
    assert (root/src).resolve() != root.resolve(), \
        f"marketplace.json の {p.get('name')} の source がリポジトリのルートを指している: {src!r}（plugin は自分のフォルダに置く）"
    _dist[p["name"]] = (root/src).resolve()
for sub in sorted({*_dist.values(), *(p2.parent.parent.resolve() for p2 in root.glob("*/.claude-plugin/plugin.json"))}):
    _pj = (sub/".claude-plugin/plugin.json").relative_to(root.resolve()).as_posix()
    d = json.loads((sub/".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    why = _bad_version(d)
    assert why is None, f"{_pj}: {why}"

# **配る plugin の今の版は、それぞれのルートの変更の記録（CHANGELOG.md）に見出しを持つ。** 版を上げて記録を書き忘れると、
# 利用者が手元の版の番号から中身へ辿れない（手順は docs/releasing.md）。射程は見出しが在ることまで——中身が Unreleased
# に残った形は見ない。
def _changelog_gap(version, text):
    """版 version の見出しが記録の本文 text に無い理由（在れば None）。ファイルが無いときは空の本文を渡す。"""
    if not _re.search(rf"^## \[{_re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}(?: \[YANKED\])?[ \t]*$", text, _re.M):
        return f"## [{version}] - YYYY-MM-DD の見出しが無い"
    return None
assert _changelog_gap("0.2.0", "") and _changelog_gap("0.2.0", "## [0.2.0]\n") \
    and _changelog_gap("0.2.0", "## [Unreleased]\n") and _changelog_gap("0.2.0", "## [0.1.0] - 2026-01-01\n") \
    and _changelog_gap("0.2.0", "## [0x2x0] - 2026-01-01\n") and _changelog_gap("0.2.0", "- ## [0.2.0] - 2026-01-01\n"), \
    "記録の見出しのチェックが、見出しの欠け・日付の欠け・別の版を拾えていない"
assert _changelog_gap("0.2.0", "# t\n\n## [Unreleased]\n\n## [0.2.0] - 2026-01-01\n") is None \
    and _changelog_gap("0.2.0", "## [0.2.0] - 2026-01-01 [YANKED]\n") is None, \
    "記録の見出しのチェックが、正しい見出しまで拾っている"
for name, sub in sorted(_dist.items()):
    d = json.loads((sub/".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert d.get("name") == name, \
        f"marketplace.json の {name} の source が指す plugin.json の name が {d.get('name')!r}（記録と tag の名前を取り違える）"
    _cl = sub/"CHANGELOG.md"
    why = _changelog_gap(d["version"], _cl.read_text(encoding="utf-8") if _cl.is_file() else "")
    assert why is None, \
        f"{_cl.relative_to(root.resolve()).as_posix()}（{name}）: {why}（版を上げた commit で見出しを足す。手順は docs/releasing.md）"

# 局所レビューの依存は公式の宣言機構で入れる。宣言が消えると pr-review-toolkit が
# 入らないまま「欠陥の観点が 1 つ静かに欠けたレビュー」が通るので、宣言の実在を検査する。
deps = [d for d in (pl.get("dependencies") or []) if isinstance(d, dict)]
assert any(d.get("name") == "pr-review-toolkit" for d in deps), \
    "plugin.json が pr-review-toolkit を dependencies で宣言していない"
# **配る plugin 全部の、別 marketplace への依存は、ルートの marketplace の許可リストに要る。** 効くのはルートの一覧だけで、無いと
# marketplace の項目の宣言なら install が拒まれ、plugin.json の宣言なら install は通って plugin が黙って読み込まれない
# （https://code.claude.com/docs/en/plugins/dependencies「Depend on a plugin from another marketplace」）。
# 依存の項は dict（marketplace フィールド）と文字列 "name@marketplace" の両方の形を取る。自分の marketplace は許可が要らない。
def _cross_needed(deps, own):
    """依存の項の並び deps が要る、own でない marketplace の名の集合。"""
    out = set()
    for d in deps or []:
        m = d.get("marketplace") if isinstance(d, dict) else (d.rsplit("@", 1)[1] if isinstance(d, str) and "@" in d else None)
        if m and m != own:
            out.add(m)
    return out
assert _cross_needed([{"name": "a", "marketplace": "x"}, "b@y", {"name": "c", "marketplace": "own"}, "d@own", "e", {"name": "f"}],
                     "own") == {"x", "y"}, \
    "依存の許可のチェックが、dict と name@marketplace の形の別 marketplace を拾えていないか、自分の marketplace・フィールド無しまで拾っている"
allowed = set(mk.get("allowCrossMarketplaceDependenciesOn") or [])
for name, sub in sorted(_dist.items()):
    miss = _cross_needed(json.loads((sub/".claude-plugin/plugin.json").read_text(encoding="utf-8")).get("dependencies"),
                         mk["name"]) - allowed
    assert not miss, f"{name} の plugin.json の依存の {sorted(miss)} が marketplace.json の allowCrossMarketplaceDependenciesOn に無い"
for p in mk["plugins"]:
    miss = _cross_needed(p.get("dependencies"), mk["name"]) - allowed
    assert not miss, f"marketplace.json の {p['name']} の項目の依存の {sorted(miss)} が allowCrossMarketplaceDependenciesOn に無い"
# 宣言に移した以上、手順書側に導入コマンドを戻すな（宣言と自作導入は排他——宣言が
# 解決できない環境ではプラグイン自体がロードされず、導入コマンドに到達しない）。
# **語の間の空白は緩めて見る**——`claude plugin \`＋改行＋`  install` のように整形を
# 変えるだけで完全一致は外れ、検査が素通りする。
rl = root/"convergence-loops/skills/review-loop"
body = "\n".join(f.read_text(encoding="utf-8") for f in [rl/"SKILL.md", *sorted((rl/"references").glob("*.md"))])
install_cmd = re.compile(r"claude\s+plugin\s+(?:\S+\s+)*install")
assert not install_cmd.search(body), \
    "review-loop.md に自作の導入コマンドが戻っている（依存は plugin.json の dependencies が正本）"

# 手順書の文言が `-R` 無しに戻ったことを検知できるのはこの検査だけ（実行時の付け忘れは
# 縛れない）。`-R` を要求する理由は `docs/customize.md`「fork 運用・複数アカウント」が正本。
bare_gh = [
    line.strip()
    for line in body.splitlines()
    if re.search(r"`gh (pr list|pr view|pr diff)", line) and "-R " not in line
]
assert not bare_gh, "gh の呼び出しに -R が無い行がある: " + " / ".join(bare_gh)

# テンプレートは写される前提で読まれる。手順書 P0-5 が「恒真になる」と禁じた `gh repo view` の
# 突き合わせが実例に載っていると、手順書側の禁止が無効になる（実際に載っていた）。
for t in sorted((root/"convergence-loops/templates").glob("round-*.example.json")):
    assert "gh repo view" not in t.read_text(encoding="utf-8"), \
        f"{t.name} が手順書の禁じ手（gh repo view で owner/repo を確認）を実例として見せている"
PY
# 配る形の標準（docs/standards/plugin-manifest.md）の決まり 2〜4 を、公式の検査 `claude plugin validate .` と同じ形で見る。
# 公式の検査は CI に無い（claude が無い）ので、警告「No author information provided」・項目と plugin.json の
# 説明の食い違い（利用者の画面に出るのは項目の方。https://code.claude.com/docs/en/plugins/marketplace-reference#display-fields）・
# README の入れ方の行の助言を、ここで止める。
expect_output 0 "MANIFEST_STANDARD_OK" "配る形の標準: plugin.json に作者と説明・説明と版は plugin.json の 1 か所・README に入れ方の 2 行" "$PY_BIN" - "$ROOT" <<'PY'
import json, re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
mk = json.loads((root/".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
owner = mk["owner"]["name"]
REPO = "raiki61/claude-plugins"   # README で marketplace を足す行の宛先（標準の決まり 4 の例）
# 標準の対象から外す物（docs/standards/README.md の「対象」）。works と works-factory は誰の受け持ちでもなく、直す担当がいない。
EXEMPT = {"works", "works-factory"}

def _entry_gap(entry):
    """marketplace の項目が、説明か版を自分で持つ理由（無ければ None）。決まり 3。"""
    held = [k for k in ("description", "version") if k in entry]
    return f"項目が {'・'.join(held)} を持つ（plugin.json の 1 か所に書く）" if held else None
def _manifest_gap(d):
    """plugin.json が説明を持たない理由（持てば None）。決まり 3 の「plugin.json の 1 か所」の側。"""
    return None if isinstance(d.get("description"), str) and d["description"].strip() else "plugin.json に description が無い"
def _author_gap(d, owner):
    """plugin.json の作者の欠け（在れば None）。決まり 2。"""
    a = d.get("author")
    if not isinstance(a, dict) or not a.get("name"):
        return "author.name が無い"
    return None if a["name"] == owner else f"author.name が {a['name']!r}（marketplace の owner.name {owner!r} と揃える）"
def _install_gap(name, mk_name, text):
    """README の本文 text に、入れ方の 2 行の欠け（揃えば None）。/plugin の形とシェルの形の両方を認める。決まり 4。"""
    lines = [
        (r"marketplace を足す行", rf"(?<![\w./-])(?:/plugin|claude\s+plugin)\s+marketplace\s+add\s+{re.escape(REPO)}(?![\w./-])"),
        (f"{name}@{mk_name} で入れる行", rf"(?<![\w./-])(?:/plugin|claude\s+plugin)\s+install\s+{re.escape(name)}@{re.escape(mk_name)}(?![\w.@-])"),
    ]
    miss = [what for what, pat in lines if not re.search(pat, text)]
    return f"README に {'・'.join(miss)} が無い" if miss else None

# **チェックそのものを標本で測る**（違反が今 0 件でも、チェックが生きていることを毎回踏む）
assert _entry_gap({"name": "a", "description": "x"}) and _entry_gap({"name": "a", "version": "1.0.0"}), \
    "配る形のチェックが、項目の説明・版を拾えていない"
assert _entry_gap({"name": "a", "source": "./a", "strict": False}) is None, "配る形のチェックが、説明の無い項目まで拾っている"
assert _manifest_gap({}) and _manifest_gap({"description": " "}) and _manifest_gap({"description": 1}) \
    and _manifest_gap({"description": "x"}) is None, "配る形のチェックが、plugin.json の説明の欠けを見分けられていない"
assert _author_gap({}, "o") and _author_gap({"author": "o"}, "o") and _author_gap({"author": {}}, "o") \
    and _author_gap({"author": {"name": "x"}}, "o"), "配る形のチェックが、作者の欠け・形の違い・別の名前を拾えていない"
assert _author_gap({"author": {"name": "o", "email": "e"}}, "o") is None, "配る形のチェックが、正しい作者まで拾っている"
_ok_slash = f"```\n/plugin marketplace add {REPO}\n/plugin install g@m\n```\n"
_ok_shell = f"1. 足す\n   claude plugin marketplace add {REPO}\n   claude  plugin install g@m\n"
assert _install_gap("g", "m", _ok_slash) is None and _install_gap("g", "m", _ok_shell) is None, \
    "配る形のチェックが、/plugin の形かシェルの形の正しい入れ方まで拾っている"
assert _install_gap("g", "m", "") and _install_gap("g", "m", "/plugin install g@m\n") \
    and _install_gap("g", "m", f"/plugin marketplace add {REPO}\n") \
    and _install_gap("g", "m", f"/plugin marketplace add {REPO}\n/plugin install gx@m\n") \
    and _install_gap("g", "m", f"/plugin marketplace add {REPO}\n/plugin install g@mx\n") \
    and _install_gap("g", "m", f"/plugin marketplace add {REPO}\n/plugin install h@m\n") \
    and _install_gap("g", "m", f"/plugin marketplace add {REPO}x\n/plugin install g@m\n") \
    and _install_gap("g", "m", f"/plugin marketplace add {REPO}\nfoo/plugin install g@m\n") \
    and _install_gap("g", "m", f"claude plugin marketplace add {REPO}\nx-claude plugin install g@m\n"), \
    "配る形のチェックが、入れ方の行の欠け・別の名前・別の marketplace を拾えていない"

listed = {p["name"]: p for p in mk["plugins"]}
assert EXEMPT <= set(listed), f"外す物 {sorted(EXEMPT - set(listed))} が marketplace.json に無い（外す一覧から消す）"
bad, checked = [], 0
for name, entry in sorted(listed.items()):
    sub = root/entry["source"]
    d = json.loads((sub/".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    readme = sub/"README.md"
    gaps = [g for g in (_entry_gap(entry), _manifest_gap(d), _author_gap(d, owner),
                        _install_gap(name, mk["name"], readme.read_text(encoding="utf-8") if readme.is_file() else "")) if g]
    if name in EXEMPT:
        # 外した物が標準を満たしたら、外す一覧に残る理由が無い（残すと、後で崩れても見えない）
        assert gaps, f"{name} は配る形の標準を満たしたので、外す一覧 EXEMPT から消す"
        continue
    checked += 1
    bad += [f"{name}: {g}（docs/standards/plugin-manifest.md）" for g in gaps]
assert not bad, "\n".join(bad)
assert checked, "配る形のチェックが 1 つのプラグインも見ていない"
print("MANIFEST_STANDARD_OK", checked)
PY

# **中身を変えたら版も上げる。** marketplace の更新は plugin の version が変わった時だけ中身を取り直すので、中身だけ変えて版を
# 据え置くと、利用者の手元は古い中身のまま残る（実測 2026-09-27: 検証器 scripts/review-record.py に関数を足したのに
# convergence-loops が 0.40.0 のままで、graphloops 0.21.5 の engine がその関数を見つけられずに止まった）。
# 見るのは commit 済みの履歴だけ——作業ツリーの未 commit の変更は見ない。
# **据え置きを赤にするのは、CI が main か release/* のブランチを見ているとき（GITHUB_REF_NAME）と、手元で VERSION_BUMP_STRICT=1 を
# 渡したときだけ。** 作業ブランチ（wip）は版を上げずに手で CI を起動する（test.yml の workflow_dispatch）ので、そこで赤にすると毎回赤になる。それ以外では
# チェックの標本だけを走らせ、据え置きの一覧を「# SKIP version-bump:」の見送りの行で出す（CI はどの OS も SKIP_ALLOW でこの能力を許す）。
# 赤にするブランチで浅い clone（履歴の無い checkout）なら測れないので、黙って緑にせず赤にする（CI の test の job は fetch-depth: 0 で取る）。
expect_output 0 "VERSION_BUMP_OK" "配る plugin の置き場のファイルが、その plugin.json の version を最後に変えた commit より後に変わっていれば、version も上がっている（main・release/* の CI と VERSION_BUMP_STRICT=1 のときだけ赤）" \
    "$PY_BIN" - "$ROOT" <<'PYBUMP'
import json, pathlib, posixpath, subprocess, sys, tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
def git(repo, *a):
    r = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"git {' '.join(a)} が失敗（{r.returncode}）: {r.stderr.strip()}"
    return r.stdout

def stale(repo, plugins):
    """版が据え置きの plugin の {名前: 版を最後に変えた commit より後に置き場を変えた commit の短い id の一覧}。
    plugins は marketplace.json の plugins[]（name と source）"""
    srcs = {p["name"]: posixpath.normpath(p["source"]) for p in plugins}
    out = {}
    for name, src in sorted(srcs.items()):
        pjpath = posixpath.join(src, ".claude-plugin/plugin.json")
        pj = json.loads((pathlib.Path(repo) / pjpath).read_text(encoding="utf-8"))
        # 今の版を持つ commit が続く一番古い物が、版をその値にした commit。作業ツリーの版がどの commit にも無ければ上げ途中で、据え置きでない
        bump = None
        for c in git(repo, "log", "--format=%H", "--", pjpath).split():
            # ./ を付けて -C の場所からの相対にする（別のリポジトリの下に取り込まれても同じ物を指す）
            if json.loads(git(repo, "show", f"{c}:./{pjpath}")).get("version") != pj.get("version"):
                break
            bump = c
        if bump is None:
            continue
        after = git(repo, "log", "--format=%h", f"{bump}..HEAD", "--", src).split()
        if after:
            out[name] = after
    return out

# **チェックそのものを標本で測る**（据え置きが今 0 件でも、チェックが生きていることを毎回踏む）。置き場を持つ plugin の 2 本で、
# 置き場の外（tests/・docs/・catalog・他の plugin の置き場）の変更は据え置きに数えず、中身の変更は数え、版を上げれば消える
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
    t = pathlib.Path(d)
    def put(rel, text):
        (t / rel).parent.mkdir(parents=True, exist_ok=True)
        (t / rel).write_text(text, encoding="utf-8")
    def commit():
        git(t, "add", "-A")
        git(t, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-qm", "x")
    git(t, "init", "-q")
    pls = [{"name": "one", "source": "./one"}, {"name": "two", "source": "./two"}]
    for rel in ("one/.claude-plugin/plugin.json", "two/.claude-plugin/plugin.json"):
        put(rel, '{"version": "0.1.0"}')
    for rel in ("one/scripts/a.py", "tests/t.sh", "docs/d.md", "two/x.md"):
        put(rel, "1")
    commit()
    assert stale(t, pls) == {}, f"チェックが、版を付けたばかりの plugin を据え置きと拾う: {stale(t, pls)}"
    put(".claude-plugin/marketplace.json", "{}")
    for rel in ("tests/t.sh", "docs/d.md", "two/x.md"):
        put(rel, "2")
    commit()
    got = stale(t, pls)
    assert set(got) == {"two"}, f"チェックが、置き場の中の変更を拾わないか、置き場の外（tests/・docs/・catalog・他の plugin）の変更を据え置きに数える: {got}"
    put("one/scripts/a.py", "2")
    commit()
    assert set(stale(t, pls)) == {"one", "two"}, f"チェックが、置き場の中の scripts の変更を拾わない: {stale(t, pls)}"
    put("one/.claude-plugin/plugin.json", '{"version": "0.1.1"}')
    put("two/.claude-plugin/plugin.json", '{"version": "0.1.1"}')
    commit()
    assert stale(t, pls) == {}, f"チェックが、版を上げた後も据え置きと拾う: {stale(t, pls)}"

import os
ref = os.environ.get("GITHUB_REF_NAME", "")
in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
# CI の上でブランチの名前が取れないなら、赤にすべきブランチかを決められない——見送りに倒さず赤にする
assert ref or not in_ci, "CI の上なのに GITHUB_REF_NAME が空で、据え置きを赤にするブランチ（main・release/*）かを決められない"
strict = os.environ.get("VERSION_BUMP_STRICT") == "1" or (in_ci and (ref == "main" or ref.startswith("release/")))
shallow = git(root, "rev-parse", "--is-shallow-repository").strip() != "false"
assert not (strict and shallow), "浅い clone で、版を最後に変えた commit を辿れない（CI は actions/checkout に fetch-depth: 0 を渡す）"
mk = json.loads((root / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
bad = {} if shallow else stale(root, mk["plugins"])
listed = " / ".join(f"{n}（版を最後に変えた後の commit: {' '.join(cs[:5])}{' ほか' if len(cs) > 5 else ''}）" for n, cs in sorted(bad.items()))
if strict:
    assert not bad, f"中身を変えたのに version が据え置きの plugin: {listed}——plugin.json の version を上げる（手順は docs/releasing.md）"
    print(f"VERSION_BUMP_OK（{len(mk['plugins'])} 本の版が中身の変更に追いついている）")
else:
    why = f"CI のブランチ {ref} は main でも release/* でもない" if in_ci else "手元では VERSION_BUMP_STRICT=1 を渡したときだけ赤にする"
    what = "浅い clone で一覧を出せない" if shallow else (f"据え置き {len(bad)} 本: {listed}" if bad else "据え置き 0 本")
    print(f"  ok   据え置きの版を赤にする # SKIP version-bump: {why}ので、チェックの標本だけを走らせた（{what}）")
    print("VERSION_BUMP_OK（チェックの標本だけ。据え置きは見送りの行に出した）")
PYBUMP

# **番人を置く。** 隣の定数実在検査は出力（末尾の合図の語）まで見るのに、ここだけ終了コード
# しか見ていなかった。**引用を拾う正規表現を絶対に一致しない形に変えても全件緑**になる（実測）
# ——照合が 0 件なら missing は空で assert が通るため。拾った件数まで出させて縛る。
expect_output 0 "DOC_HEADINGS_OK" "手順書が名指しする REVIEW.md のセクションが実在する" \
    "$PY_BIN" - "$ROOT" <<'PYHEAD'
import re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
review = (root/"convergence-loops/REVIEW.md").read_text(encoding="utf-8")
known = set(re.findall(r"^##+ (.+)$", review, re.M)) | set(re.findall(r"\*\*(.+?)\*\*", review))
# **「実在する」の定義が崩れていないことも見る。** 見出しと太字の集合を本文 1 個に潰すと、
# 照合が本文への部分一致に戻ってセクションを丸ごと削っても緑になる（今周それを 1 度やった）。
# 入口を数えて 1 つずつ壊したとき、この入口だけ腕が無かった。下限は走らせた実測値。
assert len(known) >= 72, f"見出し・太字を {len(known)} 個しか拾えていない（72 個以上を期待）"
missing, found = set(), 0
# **手書きの列挙を持たない**（隣の定数検査と同じ理由）。対象集合が狭いと、チェックは緑のまま
# 文書だけが消えた名前を指す——機械のコメントから引く箇所が増えたのに対象が commands /
# agents だけで、実在しない見出しを引いた行が 1 周素通りした。backtick も任意にする。
SCAN = [f for f in sorted(root.rglob("*.md")) if ".git" not in f.parts] + \
       sorted((root/"convergence-loops/scripts").glob("*.py"))
assert len(SCAN) >= 28, f"走査対象が {len(SCAN)} 件しかない（28 件以上を期待）"
for f in SCAN:
    body = f.read_text(encoding="utf-8")
    # 内側の『』で途中で切れないよう、同じ種類の鉤で閉じるまでを 1 つの名前として取る。
    # **助詞を「の」に限るな**——`REVIEW.md`**が**「…」という引用が 1 件在って、**1 度も
    # 走査されていなかった**（しかもその引用は正本と逐語一致しない＝走査されていれば赤く
    # なる側だった）。覆いを軸ごとに足していくと、足していない軸から必ず漏れる。
    for name in re.findall(r"`?REVIEW\.md`?\s*[のがにはをも]?\s*「((?:[^「」]|『[^『』]*』)+)」", body):
        found += 1
        # 入れ子のときは内側の鉤が『』に置き換わるので、比較の前に揃える。
        name = name.replace("『", "「").replace("』", "」")
        # **本文への部分一致を合格に足すな。** 一度足したとき、`REVIEW.md` のセクションを見出しごと
        # 8 行まるごと削っても全件緑になった（実測）——同じ語が散文に 1 度でも残っていれば
        # 通るため。本文の一文を引いていた 2 箇所（README と review-record.py）は、セクション名・
        # 太字の見出しで指す形に書き換えた。**チェックの名乗りに覆いを揃える。**
        if not any(name in k for k in known):
            missing.add(f"{f.name}: 「{name}」")
assert not missing, "REVIEW.md に無いセクションを参照している: " + " / ".join(sorted(missing))
# **拾った件数の下限。** 正規表現が壊れて 0 件になっても missing は空で通る（自分の空振りで
# 合格になる形）。下限は走らせた実測値だけを書く。
assert found >= 26, f"引用を {found} 件しか拾えていない（26 件以上を期待。走らせた実測値だけを書け）"
print(f"DOC_HEADINGS_OK {found}")
PYHEAD

# **呼ぶ前に見える面が、手順書の入口のセクションを名指しする。** コマンドを選ぶときに見えるのは frontmatter の description
# だけで、本文は呼んだ後にしか読まれない（公式: code.claude.com/docs/en/skills）。判定から入る入口が本文のセクションにしか
# 無かった版では、別のリポジトリの AI が入口に気づかなかった（人の報告 2026-09-25）。見出しを改名しても description が
# 古い名前のままなら赤。
expect_output 0 "ENTRY_SURFACE_OK" "review-graph の description が判定から入る入口のセクションを名指しする" \
    "$PY_BIN" - "$ROOT" <<'PYENTRY'
import re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sk = pathlib.Path(sys.argv[1]) / "graphloops/skills/review-graph"
m = re.match(r"---\n(.*?)\n---\n(.*)", (sk / "SKILL.md").read_text(encoding="utf-8"), re.S)
assert m, "review-graph の SKILL.md: frontmatter が無い"
desc = re.search(r"^description:[ \t]*(.*)$", m.group(1), re.M)
assert desc and desc.group(1).strip(), "review-graph の SKILL.md: description が無い"
# 入口のセクションは本文か、本文が指す別ファイル（references/）のどこかに 1 つだけ在る
text = m.group(2) + "".join(f.read_text(encoding="utf-8") for f in sorted((sk / "references").glob("*.md")))
heads = re.findall(r"^## (判定から入る.*?)\s*$", text, re.M)
assert len(heads) == 1, f"review-graph: 判定から入る入口の見出しが 1 つでない（{heads}）"
assert f"「{heads[0]}」" in desc.group(1), f"description が入口のセクション「{heads[0]}」を名指ししていない"
print(f"ENTRY_SURFACE_OK {heads[0]}")
PYENTRY

# **重い工程のコマンドは人の指示のときだけ起動する**（人の決定 2026-09-25。トークンをかなり使うので人が決めたときだけ
# 回す）。AI が起動前に見るのは description だけなので、決定は description に書く（本文には写さない——写しの正本を
# 1 つにする）。走査の母数は convergence-loops と graphloops の commands/*.md と skills/*/SKILL.md のファイル集合から導く。
# 見るのは条件の文が在ることだけで、自分から起動する合図の句（「…に使用する」等）が無いことは語が揺れるので縛らない。
expect_output 0 "HUMAN_ONLY_OK" "重い工程のコマンドの description が、起動は人の指示のときだけと言う" \
    "$PY_BIN" - "$ROOT" <<'PYHUMAN'
import re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
cmds = []
for d in ("convergence-loops", "graphloops"):
    # 手順書は commands/<名前>.md か、別ファイルを持つなら skills/<名前>/SKILL.md（呼び出しの名前は同じ）
    found = sorted((pathlib.Path(sys.argv[1]) / d).glob("commands/*.md")) + sorted((pathlib.Path(sys.argv[1]) / d).glob("skills/*/SKILL.md"))
    assert found, f"{d} に手順書が無い（走査の母数が 0）"
    cmds += found
def cmd_name(p):
    return p.parent.name if p.name == "SKILL.md" else p.stem
# 重い工程でない口（工程を回さず、利用者の環境に 1 行残すだけの /graphloops:intake）は母数から外す——名指しで外し、黙って減らさない
LIGHT = {"intake"}
cmds = [p for p in cmds if cmd_name(p) not in LIGHT]
for p in cmds:
    m = re.match(r"---\n(.*?)\n---\n", p.read_text(encoding="utf-8"), re.S)
    desc = re.search(r"^description:[ \t]*(.*)$", m.group(1), re.M) if m else None
    assert desc, f"{cmd_name(p)}: description が無い"
    assert f"人が /{cmd_name(p)} と打ったときか「工程に回して」と言ったときだけ" in desc.group(1) and "AI は自分から起動せず" in desc.group(1), \
        f"{cmd_name(p)}: description が『起動は人の指示のときだけ・AI は自分から起動しない』を言っていない"
print(f"HUMAN_ONLY_OK {len(cmds)}")
PYHUMAN

expect_exit 0 "役割 agent の定義と手順書の参照が整合する" "$PY_BIN" - "$ROOT" <<'PY'
import re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
# 遮断系はツールゼロで起動する。`tools: []` が「ツールなし」、行ごと省くと全ツールを継承、
# 列挙した全部が解決できないときだけ起動拒否——という区別は実測で確かめた
# （2026-08-21・Claude Code 2.1.238・`claude -p` で `tools: []` の agent は Read に失敗、
# `tools: Read` の agent は読めた）。
BLIND = {"cold-reader", "blind-judge"}
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}
agents = {}
for f in sorted((root / "convergence-loops/agents").glob("*.md")):
    m = re.match(r"---\n(.*?)\n---\n", f.read_text(encoding="utf-8"), re.S)
    assert m, f"{f.name}: frontmatter が無い"
    fm = dict(re.findall(r"^([a-zA-Z-]+):[ \t]*(.*)$", m.group(1), re.M))
    for key in ("name", "description", "model", "effort", "tools"):
        assert fm.get(key) is not None, f"{f.name}: frontmatter に {key} が無い"
    assert fm["name"] == f.stem, f"{f.name}: name '{fm['name']}' が filename と違う"
    assert fm["model"] in ("sonnet", "opus", "haiku"), f"{f.name}: model が不正: {fm['model']}"
    assert fm["effort"] in ("low", "medium", "high", "xhigh", "max"), f"{f.name}: effort が不正: {fm['effort']}"
    raw = fm["tools"].strip()
    assert raw, f"{f.name}: tools が空文字——省略と同じで全ツールを継承する。ツールなしは `tools: []` と 1 行で書け（複数行の配列も不可）"
    # CSV（`Read, Glob`）と YAML 配列（`["Read", "Glob"]`）はどちらも Claude Code が受ける。片方だけ
    # 解くと、もう片方で書いた書くツールが素通りする。スコープ付き（`Write(docs/*)`）は括弧の前で切る。
    tools = [t for t in (re.sub(r"\(.*", "", x.strip().strip("\"'")).strip() for x in raw.strip("[]").split(",")) if t]
    # 「書き換えるな」を言い渡しでなく定義で担保する——どの役にも書くツールを渡さない
    assert not (WRITE_TOOLS & set(tools)), f"{f.name}: 書くツールを持っている: {sorted(WRITE_TOOLS & set(tools))}"
    agents[fm["name"]] = tools
assert agents, "agents/ が空"
for n in sorted(BLIND):
    assert n in agents, f"遮断系の役 {n} が無い"
    assert agents[n] == [], f"{n} はツールを持ってはいけない: {agents[n]}"

# 外のサービスへ問い合わせを出せる役は、検索語の規律を役の定義の本文に持つ。どの起動方法（engine の
# role_file・Agent の subagent）でも役に届く面は定義の本文だけなので、規律はここに置き、写しは字面で揃える。
# 選ぶのはツールの名前でなく「外へ出せるか」——Bash からも curl で外を引ける
OUTBOUND = {"Bash", "WebSearch", "WebFetch"}
WEB_RULE = "- **検索語に対象の名前を載せるな。**"
rule_blocks = {}
for f in sorted((root / "convergence-loops/agents").glob("*.md")):
    if not OUTBOUND & set(agents[f.stem]):
        continue
    lines = f.read_text(encoding="utf-8").splitlines()
    head = [i for i, line in enumerate(lines) if line.startswith(WEB_RULE)]
    assert len(head) == 1, f"{f.name}: 外へ問い合わせを出せる役なのに、検索語の規律（{WEB_RULE}）が 1 項だけ無い（{len(head)} 項）"
    end = next((j for j in range(head[0] + 1, len(lines)) if lines[j].startswith("- ")), len(lines))
    rule_blocks[f.name] = "\n".join(lines[head[0]:end]).rstrip()
# 下限は走らせた実測値（investigator・judge）。選び方が壊れて 0 本になっても上の assert は空振りする
assert len(rule_blocks) >= 2, f"外へ問い合わせを出せる役を {len(rule_blocks)} 本しか拾えていない（2 本以上を期待）"
assert len(set(rule_blocks.values())) == 1, "検索語の規律の字面が役ごとに割れている: " + ", ".join(sorted(rule_blocks))

# 存在検査は手順書と文書のどこに識別子が出ても効かせる。使用検査（孤児の検出）は手順書だけ——
# README は全役の一覧表を持つので、含めると孤児が原理的に出なくなる。手順書側の語彙宣言行
# （「以降 `X` と書いたものは…」）も全役を列挙するので、同じ理由で使用に数えない。
# 手順書は commands/*.md と、skills/<名前>/ の本文（SKILL.md）と別ファイル（references/）
cl = root / "convergence-loops"
commands = [*cl.glob("commands/*.md"), *cl.glob("skills/*/SKILL.md"), *cl.glob("skills/*/references/*.md")]
for f in [*commands, root / "convergence-loops/docs/customize.md", root / "convergence-loops/README.md"]:
    for name in re.findall(r"convergence-loops:([a-z][a-z-]*)", f.read_text(encoding="utf-8")):
        assert name in agents, f"{f.name}: 存在しない役割 convergence-loops:{name} を参照している"
referenced = set()
for f in commands:
    body = f.read_text(encoding="utf-8")
    for line in body.splitlines():
        if "と書いたものは" in line:
            continue
        referenced |= {n for n in re.findall(r"`([a-z][a-z-]*)`", line) if n in agents}
    # 役割に寄せた以上、汎用 agent とモデル名の写し（`model:` の形でも散文でも）を手順書に戻すな（正本は agents/）
    assert "general-purpose" not in body, f"{f.name}: subagent_type: general-purpose が戻っている"
    hit = re.search(r"(?i)\b(sonnet|opus|haiku|fable)\b", body)
    assert not hit, f"{f.name}: モデル名の写しが戻っている: {hit.group(0)}"
    # 役名の無い起動は既定 subagent に落ち、モデルもツールも継承する（遮断が崩れる）。孤児検査は
    # 「役が一度も使われない」しか見ないので、「X を起動」の X が役名であることを別に見る。
    # 見るのはこの語形だけ——doctor / research は「checker＝`inspector`」の形で役を束ねる。
    for tok in re.findall(r"([^\s、。」（(]+)\s*を起動", body):
        assert tok.strip("*") in {f"`{n}`" for n in agents}, f"{f.name}: 役名の付いていない起動がある: 「{tok} を起動」"
orphans = set(agents) - referenced
assert not orphans, "どの手順書からも使われない役割がある: " + ", ".join(sorted(orphans))
PY

expect_exit 0 "配布物に固有の技術名・このリポジトリの検証のツールの名前が混ざっていない" "$PY_BIN" - "$ROOT" <<'PY'
import ast, json, re, subprocess, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
# 特定プロジェクト由来の名前が観点側に残ると、そのリポジトリでしか意味を持たない写しになる。
banned = re.compile(r"FastAPI|next-intl|config_kit|DeepAgents|asyncio_mode|guided-resolver")
hits = []
for f in [*(root/"convergence-loops").glob("*.md"), *(root/"convergence-loops/commands").glob("*.md"), *(root/"convergence-loops/skills").rglob("*.md"), *(root/"convergence-loops/agents").glob("*.md"), *(root/"convergence-loops/docs").glob("*.md")]:
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if banned.search(line):
            hits.append(f"{f.name}:{i}")
# **このリポジトリの検証のツール（CONTRIBUTING.md の「review-loop が読む検証の道具」のセクション）を、役が読む配布物に書かない。**
# ほかのリポジトリでは無いツールを呼べと指示し、このリポジトリでもツールを足した周に指示の側だけが古くなる
# （pytest の土台を足した周に、指示書のテスト一式から漏れた）。語は手で並べず導く——手で持った一覧はツールの追加に遅れる:
# ツールの語はルートの宣言（.review-checks.json の suite と mutation。ruff の banned-api と同じく禁止の正本を設定に置く）から、
# 引数は宣言が名指す実行器自身の --help から、件数のチェックは定数の接頭辞で、ツールのパスは tests/ の成分と、その下に在るファイルの名前で当てる。
# 宣言に無いツール（graphloops/README の手で回す変異のツール）だけ手で持つ。
# 境界は ASCII で切る——`\w` は日本語も語に数えるので、『は--reuse』のように和文に接した綴りを見逃す。
def derive(decl):
    argvs = [s["argv"] for s in decl["suite"]] + ([decl["mutation"]["argv"]] if "mutation" in decl else [])
    paths, mods = set(), set()
    for argv in argvs:
        for prev, a in zip([None, *argv], argv):
            if prev == "-m":
                mods.add(a)
            elif prev == "--with":
                mods.add(re.split(r"[=<>!~\[]", a, maxsplit=1)[0])
            elif "/" in a or re.search(r"\.[A-Za-z]{1,4}$", a):
                paths.add(a)
    if "mutation" in decl:
        paths.add(decl["mutation"]["arms"])
    return paths, mods
decl = json.loads((root / ".review-checks.json").read_text(encoding="utf-8"))
decl_paths, decl_mods = derive(decl)
assert decl_paths and decl_mods and "mutation" in decl, \
    f"宣言からツールの語が取れない（パス {decl_paths}・モジュール {decl_mods}・mutation の段 {'mutation' in decl}）——走査が空回りする"
# 導き方の入口ごとの検算: tests/ の外のパス・-m と --with の語・腕の一覧（宣言を差し替えても同じ道で拾う）
probe_paths, probe_mods = derive({"suite": [{"argv": ["bash", "scripts/check.sh"]}, {"argv": ["uv", "run", "--with", "gl-probe>=1", "python", "-m", "gl_mod"]}],
                                  "mutation": {"argv": ["runner"], "arms": "conf/arms.json"}})
assert probe_paths == {"scripts/check.sh", "conf/arms.json"} and probe_mods == {"gl-probe", "gl_mod"}, \
    f"宣言から語を導く道が壊れた（{probe_paths}・{probe_mods}）"
assert derive({"suite": [{"argv": ["bash", "Check.SH"]}]})[0] == {"Check.SH"}, "宣言の語の拡張子を大小を畳まずに見ている"
margv = decl["mutation"]["argv"]
runner = [sys.executable if re.fullmatch(r"python3?(\.exe)?", margv[0]) else margv[0], *margv[1:]]
helptext = subprocess.run([*runner, "--help"], cwd=root, capture_output=True, text=True, encoding="utf-8").stdout
flags = sorted(set(re.findall(r"--[a-z][a-z0-9-]*", helptext)) - {"--help"})
assert len(flags) >= 5, f"実行器の --help から引数が取れない（{flags}）——走査が空回りする"
names = sorted({f.name for d in [root/"tests", *root.glob("*/tests")] for f in d.iterdir()
                if f.is_file() and f.suffix.lower() in (".py", ".sh", ".json")})
assert "mutate.py" in names, f"テストの置き場のファイルの名前が取れない（{names}）——走査が空回りする"
A = r"A-Za-z0-9_"
END = rf"(?![{A}]|-(?!-))"   # 語の終わり: 英数字が続かず、1 つの - でつないだ語でもない（-- でつないだ引数は拾う）
# パス・ファイル名・モジュール名は大小を畳んで当てる（大小を区別しないファイルシステムでは Tests/Run.SH も同じツール。
# パッケージ名も正規化で小文字に畳む——PEP 503）。大小に意味のある定数の接頭辞と実行器の旗は区別したまま
tool = re.compile(
    rf"(?i:(?<![{A}./-])(?:[{A}.-]+/)*tests/[{A}./-]*"
    rf"|(?<![{A}])mutmut(?![{A}])"
    + "".join(rf"|(?<![{A}]){re.escape(m)}(?![{A}])" for m in sorted(decl_mods))
    + "".join(rf"|(?<![{A}./-]){re.escape(p)}{END}" for p in sorted(decl_paths))
    + "".join(rf"|(?<![{A}./-]){re.escape(n)}{END}" for n in names)
    + rf")|(?<![{A}])(?:EXPECTED|VOCAB)_[A-Z_]*"
    + "".join(rf"|(?<![{A}-]){re.escape(f)}(?![{A}-])" for f in flags))
for probe in ("は mutate.py--reuse で撃つ", "は--reuse で", "python -m pytest で回す", "腕は mutations.json に", "tests/run.sh を",
              "は MUTATE.PY で撃つ", "Tests/Run.sh を", "Mutmut で"):
    assert tool.search(probe), f"チェックが {probe!r} を拾わない——境界か導く元が壊れた"
for probe in ("pre-commit の hook", "x-mutate.py-y", "a-reuse"):
    assert not tool.search(probe), f"チェックがツール名でない {probe!r} を拾う（{tool.search(probe).group(0)}）"
texts = [root/"convergence-loops/REVIEW.md", *sorted((root/"convergence-loops/commands").glob("*.md")), *sorted((root/"convergence-loops/skills").rglob("*.md")), *sorted((root/"convergence-loops/agents").glob("*.md"))]
for d in ("graphloops/prompts", "graphloops/graphs", "graphloops/commands", "graphloops/skills"):
    texts += [f for f in sorted((root/d).rglob("*")) if f.is_file()]
# engine が組んで役へ渡す値も同じ面——文字列の定数を見る（注記と docstring は役に渡らないので外す）
codes = [f for d in ("graphloops/rules", "graphloops/engine", "graphloops/scripts") for f in sorted((root/d).glob("*.py"))]
assert len(texts) > 10 and codes, f"走査の対象が空（文 {len(texts)}・コード {len(codes)}）"
def literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    # git 自身へ渡す引数（`git("apply", "--check", …)`）も外す——役に渡らず、綴りは git の物で実行器の口と同名なだけ
    docs |= {id(a) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("git", "git_bytes")
             for a in n.args}
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
for f in texts:
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        hits += [f"{f.relative_to(root).as_posix()}:{i}: {m.group(0)}" for m in tool.finditer(line)]
for f in codes:
    for i, s in literals(f):
        hits += [f"{f.relative_to(root).as_posix()}:{i}: {m.group(0)}" for m in tool.finditer(s)]
assert not hits, "固有の技術名・このリポジトリの検証のツールの名前が残っている: " + " / ".join(hits)
PY

# 検査が空振りした場合を「合格」と区別する（対象が空でも緑になる穴を塞ぐ）。
# **これは下限で、総数の台帳ではない**——「意味のある検査を消して些末なものを足す」形の
# 劣化は検知しない（それを見るのは人のレビュー）。件数を他所に書き写すな（腐る）。
# **検査を足したらこの数も上げろ。**下限が実数から離れると、このチェック自体が空振りする——
# 実測（commit 935b205。下限が 225 のまま実件数が 448 件まで増えていた時点）: review-record と
# 実行件数の一致検査（下の `-ne`）が見るのはこの数。**走らせた実測値だけを書け**——数える前に
# 書いた数はどのコミットでも再現しなかった（前は「457 件」と書いてあった）。残る注記の仕事は 1 つ
# だけで、**検査面を捨てて数を下げるときは、下げた理由をここに残す**こと。数を下げる操作自体は
# 機械が止められない（削った本人が数も一緒に下げれば一致するので通る）。増やす側と、下げ忘れ・
# 上げ忘れは `-ne` が止めるので、ここには書かない。下げた実例は commit 4bb8d62（自作の剥がす
# 仕掛けを落として検査面が対象ごと消えた周）。
EXPECTED_CHECKS=713
# ---- coldread ゲート ------------------------------------------------------
# 読み役は COLDREAD_READER_CMD のスタブに差し替えて検査する(CI に claude も Keychain も無い)。
# allow 系は「出力が空」を ALLOW_EMPTY の目印に変換して検査する(空文字の contains は恒真のため)。
# 実際の LLM 読み役を通した実測は配布前に手元で行う。
CR_CASE="$ROOT/tests/coldread-case.sh"
CR_CFG="$WORK/coldread-cfg"; mkdir -p "$CR_CFG"
CR_PAD=$("$PY_BIN" -c "print('x'*420)")
# 生成側の stdout を UTF-8 に固定する。Windows の既定 code page(cp1252/cp932)では
# 日本語が UnicodeEncodeError で落ち、CR_BODY が空のまま以降のテストが走っていた
# (日本語本文の検査が実質 x の羅列になる)。
CR_BODY=$(PYTHONIOENCODING=utf-8 "$PY_BIN" -c "print('これは検査対象の本文です。'*20)")
if [ "${#CR_BODY}" -lt 200 ]; then
    echo "  FAIL テスト土台: CR_BODY が生成できていない(長さ ${#CR_BODY})"
    fail=1
fi
CR_POST="gh issue comment 1 --body-file - <<'EOF'
$CR_BODY
$CR_PAD
EOF"
CR_STUB_CLEAN='cat >/dev/null; echo CLEAN'
CR_STUB_BLOCK='cat >/dev/null; printf "詰まり: F3 が何か本文で解決できない\n疑問: 期限はいつか\n"'
CR_STUB_QUEST='cat >/dev/null; printf "疑問: 期限はいつか\n"'
# 3 回目からは前の回から残った詰まりだけが止める。続けて止まる数を見る検査は、前の回の印の付いた詰まりを返す代役を使う
CR_STUB_CARRY='cat >/dev/null; printf "詰まり: (前の回) F3 が何か本文で解決できない\n疑問: 期限はいつか\n"'
# 直した本文では止める数が前の回より 1 つ減るので、直しながら止まり続ける検査は 2 件返す代役を使う
CR_STUB_CARRY2='cat >/dev/null; printf "詰まり: (前の回) F3 が何か本文で解決できない\n詰まり: (前の回) F4 が何か本文で解決できない\n"'
CR_STUB_FAIL='cat >/dev/null; exit 1'
# 読み役の代役: 届いた依頼文+本文に印(ASCII)が在るかで返す文言を変える(本文が実際に届いたことまで見る)
cr_stub_sees() { printf 'b=$(cat); case "$b" in *%s*) printf "詰まり: %s が届いた\\n";; *) printf "詰まり: %s が届いていない\\n";; esac' "$1" "$1" "$1"; }
# ゲートを module として読む前置き(-c の頭に付ける)
CR_LOAD='import importlib.util,sys
spec=importlib.util.spec_from_file_location("g", sys.argv[1]); g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g)'
# deny 理由そのものを読む検査の口。ケースの stdout（フックの JSON）をパイプで受ける。
#
# **Python から bash を起動して引数で渡すな。** 改行を含む引数（ヒアドキュメントの投稿）は
# Windows で切り落とされ、ゲートは本文の無いコマンドを見て「投稿でない」と素通しにする
# （実測 2026-09-16: windows-latest だけでこの口を使う 2 件が赤く、同じケースを直に起動する
# 隣の検査は緑だった。JSON でなく ALLOW_EMPTY が返っていた）。
#
# **判定は file に置き、argv は ASCII だけにする。** 印字も ascii() で ASCII に落とす——Windows の
# stdio は locale 既定の code page（cp1252 を実測）で、日本語をそのまま印字すると化けるか落ちる。
# **落ちるときは長さを添える**: 語が見つからないのか理由そのものが短いのかは、長さを見ないと
# 切り分けられない（実測 2026-09-16: 理由が 49 字で届いていたのに『HEAD_OK が無い』しか出ず、
# 切り分けに CI を 1 周余計に使った）。
cat > "$WORK/cr-reason.py" <<'PY'
import json
import sys

# 埋め込みの script は自分で標準出力を直す（Windows の既定は cp1252。印字は ascii() で
# ASCII に落としているが、例外の文言は日本語なので、直さないと落ち方が化ける）
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

RAW = sys.stdin.buffer.read()
try:
    # 化けても落とさずに印字できる形で読む（backslashreplace）。復号で落とすと、
    # 「JSON が来ていない」のか「文字が化けた」のかが分からない
    reason = json.loads(RAW.decode("utf-8", "backslashreplace"))[
        "hookSpecificOutput"]["permissionDecisionReason"]
except Exception as exc:
    sys.exit("deny の JSON が読めない(%s): bytes=%d %s" % (exc, len(RAW), ascii(RAW[:200])))

CHECKS = {
    # 連続の案内は書き手（session）ごと。他のセッションの deny は自分の 1 回目に出さない
    "no-streak": ("SID_ISOLATED", lambda r: "回続けて" not in r),
    # 続けて止まった知らせは deny 理由の先頭に在る（末尾に置いた案内は 36 回無視された）
    "streak-head": ("HEAD_OK", lambda r: r.startswith("【") and "回続けて止まった" in r[:40]),
    # 逃げ道（COLDREAD_SKIP=1）を付けて出せと案内しない（持ち主の判断 2026-10-16）
    "no-skip-advice": ("NO_SKIP_ADVICE", lambda r: "COLDREAD_SKIP=1 を付け" not in r and "でその本文を出す" not in r),
}
mode = sys.argv[1]
if mode not in CHECKS:
    sys.exit("知らない mode: %s（在るのは %s）" % (mode, "/".join(CHECKS)))
mark, ok = CHECKS[mode]
print(mark if ok(reason) else "BAD: mode=%s bytes=%d chars=%d head=%s tail=%s"
      % (mode, len(RAW), len(reason), ascii(reason[:80]), ascii(reason[-40:])))
PY

# 使い方: cr_reason <session|-> <mode> <ケースの起動...>
# 本体（()）を副シェルにして、session の環境変数を後続の検査に残さない。
cr_reason() (
    sid=$1 mode=$2
    shift 2
    [ "$sid" = "-" ] || export COLDREAD_TEST_SESSION="$sid"
    "$@" | "$PY_BIN" "$WORK/cr-reason.py" "$mode"
)

echo "coldread ゲート:"
expect_output 0 "ALLOW_EMPTY" "投稿以外の長いコマンドは素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "git status && echo $CR_PAD"
expect_output 0 "ALLOW_EMPTY" "gh の読み取りは素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr view 12 --json state # $CR_PAD"
expect_output 0 "ALLOW_EMPTY" "400 文字未満の返信は素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body 'ありがとうございます'"
# 逃げ道 COLDREAD_SKIP=1 はエージェントに使わせない(持ち主の判断 2026-10-16)。書かれていても検査を外さず、
# 書いた事実だけを記録に残す。持ち主が自分で出すときは Claude Code の ! か自分の端末で打つ(gates/README.md)
expect_output 0 "詰まり" "COLDREAD_SKIP=1 を付けても検査は外れない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "COLDREAD_SKIP=1 $CR_POST"
expect_output 0 "refused" "効かせなかった逃げ道も記録に残る" \
    cat "$CR_CFG/coldread-gate/skip.log"
expect_output 0 "NO_SKIP_ADVICE" "止めた理由の文は、逃げ道を付けて出せと案内しない" \
    cr_reason - no-skip-advice \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "COLDREAD_SKIP=1 $CR_POST"
# 本文や旗の値に逃げ道の文字列が入っていても、検査は外れない。「詰まり」を期待するのは、deny になった事実でなく
# 読み役が実際に本文を読んだことまで見るため($CR_STUB_FAIL だと「coldreader の起動に失敗」でも緑になる)
CR_BODY_MENTIONS="gh issue comment 1 --body-file - <<'EOF'
$CR_BODY
検査を飛ばすときは COLDREAD_SKIP=1 を付けて再実行します。
$CR_PAD
EOF"
expect_output 0 "詰まり" "本文が COLDREAD_SKIP=1 に言及するだけでは外れない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_BODY_MENTIONS"
expect_output 0 "詰まり" "旗の値としての COLDREAD_SKIP=1 でも外れない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body 'COLDREAD_SKIP=1 $CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "cd の次の行に逃げ道を前置しても外れない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "cd /tmp
COLDREAD_SKIP=1 $CR_POST"
expect_output 0 "詰まり" "&& の先に逃げ道を前置しても外れない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "cd /tmp && COLDREAD_SKIP=1 $CR_POST"
expect_output 0 "解析できない" "解析できないコマンドは、逃げ道を前置しても止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "COLDREAD_SKIP=1 gh issue comment 1 --body '引用が閉じない $CR_BODY $CR_PAD"
expect_output 0 "取り出せない" "本文ファイルが無ければ deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file /tmp/real.md # $CR_PAD"
expect_output 0 "通じやすさのみ" "読み役が CLEAN なら通り、保証範囲の注が載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_CLEAN" "$CR_POST"
expect_output 0 "詰まり" "読み役の詰まりで deny になり指摘が載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_POST"
expect_output 0 "残った疑問" "疑問のみなら通り、申し送りが載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_QUEST" "$CR_POST"
expect_output 0 "coldreader(文脈ゼロの読み手)の起動に失敗" "読み役の故障は止めて、持ち主に渡す案内を出す" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "$CR_POST"
expect_output 0 "NO_SKIP_ADVICE" "読み役の故障の理由の文も、逃げ道を案内しない" \
    cr_reason - no-skip-advice \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "$CR_POST"
# 行継続(`\` + 改行)。tokenize は改行を区切りの演算子として残すので、正規化しないと 1 つの
# gh 呼び出しが複数の単純コマンドに割れる。旗だけが載った断片は gh 呼び出しと認識されず、
# 本文旗が引数列から消えて「投稿でない」として無検査・無記録で素通しになっていた。
# 2026-09-03 の issue 3 本は逃げ道で通った(記録は残る)が、同じ 3 本から逃げ道を外すと
# この経路で記録の無い素通しになることを実測した——同じコマンドに独立した穴が 2 つ在った。
# 4 形を張るのは折り返す位置で壊れ方が変わるため。期待を「詰まり」にするのは、
# deny になった事実でなく読み役が実際に本文を読んだことまで見るため。
expect_output 0 "詰まり" "行継続: 旗の前で折り返してもゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 \\
  --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "行継続: サブコマンドの後で折り返してもゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue \\
  comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "行継続: gh api + ヒアドキュメント(事故の形)もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api repos/o/r/issues -X POST \\
  -f title='t' \\
  -F body=@- <<'EOF'
$CR_BODY
$CR_PAD
EOF"
CR_CONT_CRLF=$(printf "gh issue comment 1 \\\\\r\n  --body '%s %s'" "$CR_BODY" "$CR_PAD")
expect_output 0 "詰まり" "行継続: CRLF で届いてもゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_CONT_CRLF"
# 単一引用の中の `\`+改行 は行継続ではない(シェルが畳まない)。畳んでしまうと本文が
# 書かれたとおりに読み役へ渡らないので、こちらは保つ側を張る。
# 期待を「詰まり」にすると畳んでも緑になる(どちらでも読み役は走る)ので、読み役の側で
# 本文を実際に見て、畳まれたかどうかで返す文言を変える。
#
# **読み役の代役は file に置く（日本語を argv に載せない）。** grep の綴りを sh の引数で渡すと、
# 引用の層が 3 つ（run.sh → ケース → sh -c）重なった上に OS ごとの引数の受け渡しが混ざり、
# 空振りしても「畳まれてしまった」としか分からない。**何が届いたかを印字させる**——届いた
# バイト数と印の周りの生の姿を添える（実測 2026-09-16: windows-latest だけ赤く、畳まれたのか
# 行末に \r が付いたのかが分からず、切り分けに CI を 1 周余計に使った）。
cat > "$WORK/fold-stub.py" <<'PY'
import sys

# 埋め込みの script は自分で標準出力を直す（報告は UTF-8 の bytes で書くが、例外の文言は
# 日本語なので、Windows の既定 cp1252 のままだと落ち方が化ける）
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

RAW = sys.stdin.buffer.read()          # 依頼文＋本文（読み役に届くものそのまま）
MARK = "まえ".encode("utf-8")
at = RAW.find(MARK)
# 畳まずに届いたなら、印の直後は `\` と改行がそのまま在る（\r が挟まっていれば畳まれていない
# が「書かれたとおり」でもないので、こちらも落とす側に数える）
kept = at >= 0 and RAW[at + len(MARK):at + len(MARK) + 2] == b"\\\n"
near = ascii(RAW[at:at + 16].decode("utf-8", "backslashreplace")) if at >= 0 else "印が無い"
# 出力は UTF-8 の bytes で書く（stdout の code page に依らせない。ゲートは UTF-8 strict で読む）
sys.stdout.buffer.write(("詰まり: 行継続が畳まれ%s [%d バイト届いた・印の周り %s]\n"
                         % ("ずに届いた" if kept else "てしまった", len(RAW), near)).encode("utf-8"))
PY
CR_STUB_FOLD="'$PY_BIN' '$WORK/fold-stub.py'"
expect_output 0 "畳まれずに届いた" "単一引用の中の改行は畳まず、本文が書かれたとおり読み役へ渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FOLD" "gh issue comment 1 --body 'まえ\\
うしろ $CR_BODY $CR_PAD'"

# 注釈(#)。shlex の既定は行末まで読み捨てるので、区切りにしている改行まで消えて
# 単純コマンドが融合し、先頭語が cd や echo になって gh が見えなくなる。
# 行継続を畳むようにしたぶん融合の射程が「物理行」から「論理行」へ広がるので、
# 塞ぐ側を張る(1 件目は今回の変更が入れた退行、2 件目は元から在った穴)
expect_output 0 "詰まり" "語中の # があっても行継続の先の本文旗を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue create -R o/r --title fix#123 \\
  --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "注釈行の次の行の gh を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "cd /tmp  # 作業場所
gh issue comment 1 --body '$CR_BODY $CR_PAD'"

# 注釈と行継続は 1 パスで落とす。2 パスだと順序をどちらに置いても、bash が実行する gh を
# 片方で見失う(どちらも gh スタブを PATH に置いた bash で「実行される」ことを実測):
#   注釈が先   → 1 件目を落とす(行が連結されるので #y は語中の # であって注釈ではない)
#   行継続が先 → 2 件目を落とす(注釈は行末で切れるので、その \ は注釈の一部)
# 2 件同時に緑になるのは 1 パスのときだけなので、この 2 本で順序への逆戻りを縛る
expect_output 0 "詰まり" "行継続で連結した後の # は語中(注釈にせず、後ろの gh を残す)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "echo x\\
#y; gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "注釈の中の \\ は行継続にしない(次の行の gh を残す)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "echo a # メモ \\
gh issue comment 1 --body '$CR_BODY $CR_PAD'"

# シェルの予約語。( gh … ) は元からゲートに掛かるのに { gh …; } は抜ける、という
# 「書き方だけで片方が抜ける」状態だった
expect_output 0 "詰まり" "{ } で括った gh もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "{ gh issue comment 1 --body '$CR_BODY $CR_PAD'; }"
expect_output 0 "詰まり" "if の then に置いた gh もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "if true; then gh issue comment 1 --body '$CR_BODY $CR_PAD'; fi"
expect_output 0 "詰まり" "while の do に置いた gh もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "while true; do gh issue comment 1 --body '$CR_BODY $CR_PAD'; break; done"

# ゲートから漏れた投稿を数えられるようにする。sh -c は受容済みの限界(gates/README.md)だが、
# 落ちた事実が 0 行なのは「投稿でなかった」と区別が付かず、押し出しの量を測れない
expect_output 0 "ALLOW_EMPTY" "sh -c の中の gh は今も素通し(受容済みの限界)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "sh -c 'gh issue comment 1 --body \"$CR_BODY $CR_PAD\"'"
expect_output 0 "--body" "ゲートから漏れた投稿は旗の綴りだけ misses.log に残る" \
    cat "$CR_CFG/coldread-gate/misses.log"

# 補完(読み手が推測で埋めた箇所)。詰まり 0 件で通る自信のある誤読を書き手に返すためのフィールドで、
# 投稿は止めない。事故で最悪だった誤読(「いま CI が壊れている」)がこの型
CR_STUB_FILL='cat >/dev/null; printf "補完: 障害は今起きていると読んだ\nCLEAN\n"'
CR_STUB_BLOCK_FILL='cat >/dev/null; printf "詰まり: F3 が何か本文で解決できない\n補完: 障害は今起きていると読んだ\n"'
CR_STUB_PROSE='cat >/dev/null; printf "詰まりは無い。本文は将来の話をしている。\nCLEAN\n"'
expect_output 0 "推測で埋めた箇所" "補完のみなら通り、埋めた中身が載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FILL" "$CR_POST"
expect_output 0 "補完: 障害は今起きている" "補完は deny の指摘にも載る(直す機会があるのは deny の側)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK_FILL" "$CR_POST"
# 期待は allow にしか出ない語にする。「通じやすさのみ」(SCOPE_NOTE)は deny にも載るので
# 恒真になる——実際に恒真だったのを変異で検出して直した
expect_output 0 "検査を通過" "ラベルはコロンまで見る(「詰まりは無い」の地の文で deny にしない)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_PROSE" "$CR_POST"
expect_output 0 "止めてはいないが" "deny の指摘は見出しで分ける(直す詰まりと、直さなくてよい補完)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK_FILL" "$CR_POST"
# 末尾の CLEAN で詰まりが上書きされないこと。読み役に自由文のフィールド(補完)を足したぶん、
# 「指摘を並べた後に CLEAN と書く」形が出やすくなっている
CR_STUB_BLOCK_CLEAN='cat >/dev/null; printf "詰まり: F3 が何か本文で解決できない\nCLEAN\n"'
expect_output 0 "投稿を止めている詰まり" "詰まりを並べた後に CLEAN と書かれても通さない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK_CLEAN" "$CR_POST"
# misses.log は当たった旗の綴りだけを残す。gh secret set は投稿でない(NON_POSTING)ので
# 必ず miss の分岐に落ちるため、コマンドの抜粋を残すと秘密そのものが平文で溜まる
expect_output 0 "ALLOW_EMPTY" "gh secret set は投稿でないので素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh secret set MY_TOKEN --body 'sk-secret-value-$CR_PAD'"
expect_output 1 "0" "misses.log に秘密の値を残さない" \
    grep -c "sk-secret-value" "$CR_CFG/coldread-gate/misses.log"

# ゲートの掛け方: 「本文を運ぶ旗」を、ヒアドキュメント盾置換+shlex トークン化+単純コマンド単位の帰属で見る
CR_NOTES="gh release create v9.9.9 --notes-file - <<'EOF'
$CR_BODY
$CR_PAD
EOF"
expect_output 0 "詰まり" "release create --notes-file もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_NOTES"
expect_output 0 "詰まり" "issue close --comment もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue close 9 --comment '$CR_BODY $CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "gh api graphql の長い読み取りは巻き込まない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api graphql -f query='query { repository { pullRequest { comments(first: 50) { nodes { body } } } } } # $CR_PAD'"
expect_output 0 "詰まり" "--body の長文が読み役に届く" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "-b 短縮形もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh pr comment 1 -b '$CR_BODY $CR_PAD'"
CR_FDASH="gh issue comment 1 -F - <<'EOF'
$CR_BODY
$CR_PAD
EOF"
expect_output 0 "詰まり" "-F - (--body-file 短縮形)のヒアドキュメントもゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_FDASH"
expect_output 0 "詰まり" "release create -n 短縮形もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh release create v1 -n '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "gh api -f body= もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api repos/o/r/issues/1/comments -f body='$CR_BODY $CR_PAD'"
# gh api は自分の旗を endpoint の前に置ける。読むだけの形を「サブコマンドを特定できない」で止めない（2026-10-15 に実測した誤り）。
# 前に旗を置いた投稿は、旗の値ごと読み飛ばしたうえでゲートに掛かる
expect_output 0 "ALLOW_EMPTY" "gh api の読み取りは、endpoint の前に値を取らない旗が在っても素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "for j in 1 2; do gh api --allow-escape-sequences repos/o/r/actions/jobs/\$j/logs > w\$j.log; done # $CR_PAD"
expect_output 0 "ALLOW_EMPTY" "gh api の読み取りは、endpoint の前に値を取る旗が在っても素通し" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api -X GET --jq .name --paginate repos/o/r/actions/jobs/1 # $CR_PAD"
expect_output 0 "詰まり" "endpoint の前に旗を置いた gh api の投稿もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api --silent -XPOST repos/o/r/issues/1/comments -f body='$CR_BODY $CR_PAD'"
expect_output 0 "取り出せない" "gh api の知らない旗は今までどおり検査できない側に倒す" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api --no-such-flag repos/o/r/issues/1/comments -f body='$CR_BODY $CR_PAD'"
CR_JSON_POST="gh api repos/o/r/issues/1/comments --input - <<'EOF'
{\"body\": \"$CR_BODY $CR_PAD\"}
EOF"
expect_output 0 "詰まり" "--input - の JSON 本文もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_JSON_POST"
expect_output 0 "詰まり" "graphql の mutation は body: の文字列を本文として読ませる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api graphql -f query='mutation { addComment(input:{subjectId:\"x\", body:\"$CR_BODY $CR_PAD\"}) }'"
expect_output 0 "詰まり" "列挙に無いサブコマンドでも本文の旗があればゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh discussion comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "複合コマンド中の gh も判定する" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "cd /tmp && gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "小文字・数字入りの環境変数前置でも gh を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "x1=1 gh issue comment 1 --body '$CR_BODY $CR_PAD'"
CR_GIST="gh gist create - <<'EOF'
$CR_BODY
$CR_PAD
EOF"
expect_output 0 "詰まり" "gist create - のヒアドキュメントもゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_GIST"
# 帰属の負例: 旗が gh 以外のコマンドに付いていても巻き込まない
expect_output 0 "ALLOW_EMPTY" "別コマンドの -b を gh の旗と誤認しない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr list --limit 100 && git checkout -b feature/x && echo '$CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "引用の中の gh はコマンドと見なさない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "grep -r 'gh issue comment --body' . # $CR_PAD"
# --comment が真偽旗と分かっていないと、次の -b を値として食い、本文が位置引数に落ちて取りこぼす
expect_output 0 "詰まり" "pr review の --comment は真偽旗なので後続の -b を本文として拾う" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh pr review 12 --comment -b '$CR_BODY $CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "pr review の --comment 自体は本文扱いしない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr review 12 --comment # $CR_PAD"
# 検査できない本文は fail-closed で止める
# 表そのものを走査して、各項目が実際に効いていることを確かめる(表が増えれば検査も増える)
expect_output 0 "TABLE_OK" "判定表の全項目が効いている" "$PY_BIN" "$ROOT/tests/coldread-table-case.py"
# 手元の文書の口（書いた後に記録し、ターンの終わりにまとめて読む）。読み手は差し替え（COLDREAD_READER_CMD）で、
# 呼ばれた回数と渡った依頼文をファイルに残させて数える——指摘を返すかだけを見ると、読まずに通す形も緑になる
expect_output 0 "DOCS_GATE_OK" "coldread の手元の文書: 文書だけを記録し、ターンの終わりに 1 本 1 回だけ投稿と同じ依頼文で読み、親には指摘をファイルに書いて短い知らせだけを返す" \
    "$PY_BIN" - "$ROOT" "$WORK/docs-gate" <<'PY'
import importlib.util, json, os, pathlib, re, subprocess, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
gate = root / "gates/hooks/coldread-gate.py"
work.mkdir(parents=True)
cfg, calls = work / "cfg", work / "calls"
calls.mkdir()
spec = importlib.util.spec_from_file_location("gate_docs", gate)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

def run(mode, payload, reader=None, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("COLDREAD_")}
    # 文書は一時フォルダの下(WORK)に置くので、一時の置き場のルートを別の所に向けて、git の外の文書として読ませる
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_TMP_DIRS=str(work / "tmp-root"), **env)
    if reader:
        e["COLDREAD_READER_CMD"] = reader
    r = subprocess.run([sys.executable, str(gate), mode], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, env=e, timeout=60)
    assert r.returncode == 0, (mode, r.returncode, r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8")

# 読み手の差し替え: 呼ばれるたびに受けた依頼文を calls/ に 1 本ずつ残し、決まった報告を返す
def stub(report):
    return ('n=$(ls "%s" | wc -l | tr -d " "); cat > "%s/$n.txt"; printf "%s\n"' % (calls, calls, report))
FIND = stub("詰まり: 『例の方針』が何か分からない\\n補完: 方針は決まっていると読んだ")
CLEAN = stub("CLEAN")

def doc(name, text):
    f = work / name
    f.write_text(text, encoding="utf-8")
    return str(f)

long_text = "# 手順\n\n" + "例の方針どおりに進める。" * 40
a = doc("a.md", long_text)
b = doc("b.txt", "短い")
c = doc("c.md", "coldwrite:skip\n" + "あ" * 400)
d = doc("d.rst", "coldread:skip\n" + "あ" * 400)
code = doc("e.py", "x = 1\n" * 200)
for f in (a, b, c, d, code):
    run("docs-record", {"session_id": "s1", "tool_input": {"file_path": f}})
run("docs-record", {"session_id": "s1", "tool_input": {"file_path": a}})   # 同じ文書を 2 度書いても読むのは 1 回
pending = (cfg / "coldread-gate/docs/s1.pending").read_text(encoding="utf-8").split()
assert code not in pending and a in pending, f"記録が文書の拡張子だけを拾っていない: {pending}"

out = json.loads(run("docs-check", {"session_id": "s1", "hook_event_name": "Stop"}, FIND))
ctx = out["hookSpecificOutput"]
assert ctx["hookEventName"] == "Stop" and "decision" not in out, f"止めずに続けさせる形でない: {out}"
# 親の会話には指摘の全文を積まない: 全文はファイルに書き、知らせは本数・件数・場所・サブエージェントに渡す指示だけ
note = ctx["additionalContext"]
assert "例の方針" not in note and "1 本" in note and "詰まり 1 件" in note and "推測で埋めた箇所 1 件" in note, note
assert "サブエージェント" in note and "意図と違う" in note, f"サブエージェントに渡して直させ、推測で埋めた箇所だけ親が見る、の指示が無い: {note}"
written = list((cfg / "coldread-gate/docs/findings").iterdir())
assert len(written) == 1 and str(written[0]) in note, (written, note)
full = written[0].read_text(encoding="utf-8")
assert "例の方針" in full and a in full and "方針は決まっていると読んだ" in full, f"書き出したファイルに指摘の全文が無い: {full}"
got = sorted(calls.iterdir())
assert len(got) == 1, f"読んだのは a.md の 1 本だけのはず（300 字未満・2 つの印・同じ文書の 2 度目は読まない）: {len(got)} 回"
prompt = got[0].read_text(encoding="utf-8")
assert prompt == g.COLD_PROMPT + long_text, "投稿と同じ依頼文（COLD_PROMPT）に本文を足した物が読み手に渡っていない"
assert not (cfg / "coldread-gate/docs/s1.pending").exists(), "読んだ後に待ちの一覧が残る（次のターンにまた読む）"

# 同じ中身は読み直さない。変えたら読む
run("docs-record", {"session_id": "s1", "tool_input": {"file_path": a}})
assert run("docs-check", {"session_id": "s1"}, FIND) == "" and len(list(calls.iterdir())) == 1, "同じ中身を読み直した"
pathlib.Path(a).write_text(long_text + "\n直した。", encoding="utf-8")
run("docs-record", {"session_id": "s1", "tool_input": {"file_path": a}})
assert run("docs-check", {"session_id": "s1"}, CLEAN) == "" and len(list(calls.iterdir())) == 2, "直した文書を読まないか、CLEAN で何かを返した"

# 読み手が起きなくても作業は止めない（終了コード 0）。読めなかった文書を名指す
pathlib.Path(a).write_text(long_text + "\n2 度目。", encoding="utf-8")
run("docs-record", {"session_id": "s1", "tool_input": {"file_path": a}})
down = json.loads(run("docs-check", {"session_id": "s1"}, "cat >/dev/null; exit 3"))
assert "読めなかった" in down["hookSpecificOutput"]["additionalContext"], down
# 報告の形でない出力（認証切れ）を CLEAN と読まない
pathlib.Path(a).write_text(long_text + "\n3 度目。", encoding="utf-8")
run("docs-record", {"session_id": "s1", "tool_input": {"file_path": a}})
odd = json.loads(run("docs-check", {"session_id": "s1"}, "cat >/dev/null; echo 'Failed to authenticate'"))
assert "読めなかった" in odd["hookSpecificOutput"]["additionalContext"], odd
# 読めなかった訳が書き手に分かる(時間切れなら上限の秒、ほかは起動できなかった訳)
assert "読み手を起動できなかった" in down["hookSpecificOutput"]["additionalContext"], down
assert "420 秒で時間切れ" in g._down_reason(subprocess.TimeoutExpired(["claude"], 420)), g._down_reason(subprocess.TimeoutExpired(["claude"], 420))

# 切る口と、読み手の中での入れ子
run("docs-record", {"session_id": "s2", "tool_input": {"file_path": a}}, COLDREAD_DOCS_OFF="1")
run("docs-record", {"session_id": "s3", "tool_input": {"file_path": a}}, COLDREAD_IN_READER="1")
assert not any((cfg / "coldread-gate/docs").glob("s[23].pending")), "COLDREAD_DOCS_OFF か読み手の中で記録した"

# docs.log に読みにかかった秒が残る(読めた・読めなかったの両方)
log = (cfg / "coldread-gate/docs.log").read_text(encoding="utf-8")
assert re.search(r"^\S+ \S+\tfinding\t\d+\t\d+s\te=%s\tsid=" % g.DOC_EFFORT, log, re.M) and re.search(r"^\S+ \S+\tclean\t\d+\t\d+s\te=", log, re.M), log
assert re.search(r"^\S+ \S+\treader-down\t.*\t\d+s\te=%s\tsid=" % g.DOC_EFFORT, log, re.M), log

# ターンの終わりを塞がない: 対話の会話(入口 cli)の親の Stop は、待つ口(docs-check)は読まずに、裏の口(docs-check-async)が
# 読み、指摘を標準エラーに書いて 2 で終わる(asyncRewake が会話を呼び起こす)。画面の無い会話(sdk-cli)と入口の分からない会話は
# 待つ口が読み、裏の口は読まない。サブエージェントの終わりは裏の口では読まない
def raw(mode, payload, reader, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("COLDREAD_")}
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_TMP_DIRS=str(work / "tmp-root"), COLDREAD_READER_CMD=reader, **env)
    return subprocess.run([sys.executable, str(gate), mode], input=json.dumps(payload).encode("utf-8"),
                          capture_output=True, env=e, timeout=60)
def touch(session, n, agent=None):
    pathlib.Path(a).write_text(long_text + "\n%s の %d 度目。" % (session, n), encoding="utf-8")
    run("docs-record", {"session_id": session, "tool_input": {"file_path": a}, **({"agent_id": agent} if agent else {})})
before = len(list(calls.iterdir()))
touch("s5", 1)
quiet = raw("docs-check", {"session_id": "s5", "hook_event_name": "Stop"}, FIND, CLAUDE_CODE_ENTRYPOINT="cli")
assert quiet.returncode == 0 and quiet.stdout == b"" and (cfg / "coldread-gate/docs/s5.pending").exists(), "対話の会話で待つ口が読んだ"
woke = raw("docs-check-async", {"session_id": "s5", "hook_event_name": "Stop"}, FIND, CLAUDE_CODE_ENTRYPOINT="cli")
told = woke.stderr.decode("utf-8")
assert woke.returncode == 2 and woke.stdout == b"" and "直前のターン" in told and "詰まり 1 件" in told, (woke.returncode, told)
assert len(list(calls.iterdir())) == before + 1 and not (cfg / "coldread-gate/docs/s5.pending").exists()
touch("s5", 2)
calm = raw("docs-check-async", {"session_id": "s5", "hook_event_name": "Stop"}, CLEAN, CLAUDE_CODE_ENTRYPOINT="cli")
assert calm.returncode == 0 and calm.stderr == b"" and len(list(calls.iterdir())) == before + 2, "裏の口が CLEAN で会話を呼び起こした"
# /clear で終わった会話の分の知らせは、前の会話の id と、意図を確かめられない推測の扱いを書く(終わり方が clear でなければ今までどおり)
run("docs-session-end", {"session_id": "s5", "hook_event_name": "SessionEnd", "reason": "other"})
assert not (cfg / "coldread-gate/docs/cleared").exists(), "/clear でない終わりを覚えた"
run("docs-session-end", {"session_id": "s5", "hook_event_name": "SessionEnd", "reason": "clear"})
touch("s5", 9)
gone = raw("docs-check-async", {"session_id": "s5", "hook_event_name": "Stop"}, FIND, CLAUDE_CODE_ENTRYPOINT="cli").stderr.decode("utf-8")
assert "/clear で終わった前の会話(id s5)" in gone and "確かめられないものは直さずに残す" in gone and "この会話で見て" not in gone, gone
assert "この会話で見て" in told and "/clear" not in told, "/clear の前でない会話の知らせが変わった"
for entry in ("sdk-cli", None):
    touch("s6", 3 if entry else 4)
    env = {"CLAUDE_CODE_ENTRYPOINT": entry} if entry else {}
    idle = raw("docs-check-async", {"session_id": "s6", "hook_event_name": "Stop"}, FIND, **env)
    assert idle.returncode == 0 and (cfg / "coldread-gate/docs/s6.pending").exists(), f"画面の無い会話({entry})で裏の口が読んだ"
    waited = raw("docs-check", {"session_id": "s6", "hook_event_name": "Stop"}, FIND, **env)
    assert waited.returncode == 0 and "詰まり 1 件" in json.loads(waited.stdout)["hookSpecificOutput"]["additionalContext"], entry
touch("s7", 5, agent="agent-q")
sub_bg = raw("docs-check-async", {"session_id": "s7", "agent_id": "agent-q", "hook_event_name": "SubagentStop"}, FIND, CLAUDE_CODE_ENTRYPOINT="cli")
assert sub_bg.returncode == 0 and (cfg / "coldread-gate/docs/s7.agent-q.pending").exists(), "裏の口がサブエージェントの終わりに読んだ"
sub = raw("docs-check", {"session_id": "s7", "agent_id": "agent-q", "hook_event_name": "SubagentStop"}, FIND, CLAUDE_CODE_ENTRYPOINT="cli")
assert "例の方針" in json.loads(sub.stdout)["hookSpecificOutput"]["additionalContext"], "対話の会話でサブエージェントの終わりに待って読まない"

# 推測で埋めた箇所と疑問だけなら、書いた役を呼び起こさない(親の待つ口・裏の口・サブエージェントの終わりのどれも)。docs.log に件数は残す
GUESS = stub("補完: 方針は決まっていると読んだ\\n疑問: 期限はいつか")
touch("s6", 6)
assert raw("docs-check", {"session_id": "s6", "hook_event_name": "Stop"}, GUESS, CLAUDE_CODE_ENTRYPOINT="sdk-cli").stdout == b"", "推測だけで親を呼び起こした"
touch("s5", 7)
lull = raw("docs-check-async", {"session_id": "s5", "hook_event_name": "Stop"}, GUESS, CLAUDE_CODE_ENTRYPOINT="cli")
assert lull.returncode == 0 and lull.stderr == b"", "推測だけで裏の口が会話を呼び起こした"
touch("s7", 8, agent="agent-q")
assert raw("docs-check", {"session_id": "s7", "agent_id": "agent-q", "hook_event_name": "SubagentStop"}, GUESS).stdout == b"", "推測だけでサブエージェントを続けさせた"
assert len(re.findall(r"^\S+ \S+\tguess=1\t", (cfg / "coldread-gate/docs.log").read_text(encoding="utf-8"), re.M)) == 3

# 読み手のモデルと effort: 手元の文書は既定 haiku・high、投稿は既定 sonnet・medium のまま。既定は環境変数を外した子で見る
def loaded(**env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("COLDREAD_")}
    r = subprocess.run([sys.executable, "-c", "import importlib.util as u, sys; s = u.spec_from_file_location('g', sys.argv[1]); m = u.module_from_spec(s); "
                        "s.loader.exec_module(m); a = m.reader_argv('claude'); print(m.DOC_MODEL, m.DOC_EFFORT, a[a.index('--model') + 1], a[a.index('--effort') + 1])", str(gate)],
                       capture_output=True, text=True, env=dict(e, CLAUDE_CONFIG_DIR=str(cfg), **env))
    return r.stdout.split()
assert loaded() == ["haiku", "high", "sonnet", "medium"], loaded()
assert loaded(COLDREAD_DOC_EFFORT="low")[1] == "low", "COLDREAD_DOC_EFFORT で手元の文書の effort を替えられない"
# 実際に読み手へ渡る引数も見る(read_doc が effort を渡し忘れても、上の値の検査だけでは通る)。起動と認証は差し替える
pick = lambda a, flag: a[a.index(flag) + 1]
seen_argv, saved = [], (g.subprocess.run, g.claude_auth.auth_env, os.environ.pop("COLDREAD_READER_CMD", None))
g.claude_auth.auth_env = lambda env, **kw: (dict(env), None)
g.subprocess.run = lambda argv, **kw: (seen_argv.append(argv), subprocess.CompletedProcess(argv, 0, b"CLEAN", b""))[1]
try:
    g.read_doc("本文")
finally:
    g.subprocess.run, g.claude_auth.auth_env = saved[:2]
assert seen_argv and (pick(seen_argv[0], "--model"), pick(seen_argv[0], "--effort")) == (g.DOC_MODEL, g.DOC_EFFORT), seen_argv

# フックの宣言: 書いた後は記録だけ、ターンの終わりに読む
hooks = json.loads((root / "gates/hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
post = [h for grp in hooks.get("PostToolUse", []) if grp.get("matcher") == "Write|Edit|MultiEdit" for h in grp["hooks"]]
stop = [h for grp in hooks.get("Stop", []) for h in grp["hooks"]]
assert any(h["command"].endswith("coldread-gate.py\" docs-record") for h in post), post
# 待つ口・裏の口・サブエージェントの終わりの口の timeout は、どれも読み役の 2 巡(DOC_WORKERS 本ずつ、1 回 DOC_READ_TIMEOUT)より長い。
# 裏の口は asyncRewake(指摘が在れば 2 で会話を呼び起こす)
assert any(h["command"].endswith("coldread-gate.py\" docs-check") and h.get("timeout", 0) > 2 * g.DOC_READ_TIMEOUT for h in stop), stop
assert any(h["command"].endswith("coldread-gate.py\" docs-check-async") and h.get("asyncRewake") is True
           and h.get("timeout", 0) > 2 * g.DOC_READ_TIMEOUT for h in stop), stop
sub = [h for grp in hooks.get("SubagentStop", []) if not grp.get("matcher") for h in grp["hooks"]]
assert any(h["command"].endswith("coldread-gate.py\" docs-check") and h.get("timeout", 0) > 2 * g.DOC_READ_TIMEOUT for h in sub), f"サブエージェントの終わりに読む口が無いか、timeout が読み役の 2 巡に足りない（matcher 無しで全部のサブエージェントに効かせる）: {sub}"
# 手元の文書の読み役は、待って読む口でも投稿の読み役の上限(READER_TIMEOUT)より長く待つ
assert g.DOC_READ_TIMEOUT > g.READER_TIMEOUT and g.read_doc.__defaults__[-1] == g._read_pending.__defaults__[-1] == g.DOC_READ_TIMEOUT
ends = [h for e in hooks["SessionEnd"] if e.get("matcher") == "clear" for h in e["hooks"]]
assert any(h["command"].endswith("coldread-gate.py\" docs-session-end") for h in ends), f"/clear で終わる会話を覚える口が無い: {ends}"

# 初見で読む観点の正本は 1 か所。skill の手順は依頼文を写して持たない
skill = (root / "gates/skills/coldread/SKILL.md").read_text(encoding="utf-8")
views = [ln.split(")", 1)[1].strip() for ln in g.COLD_PROMPT.splitlines() if ln[:1] == "(" and ")" in ln]
assert len(views) == 5, f"COLD_PROMPT の観点の行を拾えない（チェックが空回り）: {views}"
copied = [v for v in views if v in skill]
assert not copied, f"skill『coldread』が依頼文の観点を写して持っている: {copied}"
assert "coldread-gate.py\" read" in skill, "skill『coldread』の手で検査する手順が、ゲートの read の口を呼んでいない"
r = subprocess.run([sys.executable, str(gate), "prompt"], capture_output=True)
assert r.stdout.decode("utf-8") == g.COLD_PROMPT, "prompt の口が COLD_PROMPT をそのまま出していない"
print("DOCS_GATE_OK")
PY
# Bash・MCP のツールで書いた文書も拾う(持ち主の方針「防ぐより、ひっかける幅を増やす」)。Write・Edit の記録だけでは、
# cat > x.md <<EOF・tee・sed -i・python で書く・mv/cp で置く文書が 1 本も読まれなかった。Bash の前(PreToolUse)に
# git の変更一覧の文書の mtime と大きさを控え、後(PostToolUse)で取り直して、増えた・変わった文書を記録に載せる。
# git の外ではコマンドの中の書き込み先を静的に拾う
expect_output 0 "DOCS_BASH_OK" "coldread の手元の文書: Bash が書いた文書を git の変更一覧の差と書き込み先の静的な読みで拾い、MCP の書くツールの path も拾う" \
    "$PY_BIN" - "$ROOT" "$WORK/docs-bash" <<'PY'
import json, os, pathlib, subprocess, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
gate = root / "gates/hooks/coldread-gate.py"
work.mkdir(parents=True)
cfg = work / "cfg"
repo, plain = work / "repo", work / "plain"
repo.mkdir()
plain.mkdir()

def run(mode, payload, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("COLDREAD_")}
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_READER_CMD="cat >/dev/null; exit 1", **env)
    r = subprocess.run([sys.executable, str(gate), *([mode] if mode else [])], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, env=e, timeout=60)
    assert r.returncode == 0, (mode, r.returncode, r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8")

def git(*a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

def pending(sid):
    f = cfg / "coldread-gate/docs" / (sid + ".pending")
    return sorted(set(f.read_text(encoding="utf-8").split())) if f.exists() else []

real = lambda p: os.path.realpath(str(p))
git("init", "-q")
git("config", "user.email", "t@example.com")
git("config", "user.name", "t")
(repo / "t.md").write_text("tracked\n", encoding="utf-8")
(repo / "m.md").write_text("tracked\n", encoding="utf-8")
git("add", ".")
git("commit", "-q", "-m", "init")
(repo / "m.md").write_text("changed before the command\n", encoding="utf-8")   # 前から変わっている文書は拾わない

def bash(sid, tid, cwd, command, effect):
    """PreToolUse(投稿のゲートと同じ口) → コマンドの効果 → PostToolUse(docs-record) を流す。"""
    pay = {"session_id": sid, "tool_name": "Bash", "tool_use_id": tid, "cwd": str(cwd), "tool_input": {"command": command}}
    run("", dict(pay, hook_event_name="PreToolUse"))
    effect()
    run("docs-record", dict(pay, hook_event_name="PostToolUse"))

def in_repo():
    (repo / "new.md").write_text("new\n", encoding="utf-8")
    (repo / "t.md").write_text("tracked and edited by python\n", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub/deep.txt").write_text("deep\n", encoding="utf-8")
    (repo / "x.py").write_text("x = 1\n", encoding="utf-8")
bash("s1", "tu1", repo, "python3 tools/write_docs.py", in_repo)
got = pending("s1")
want = sorted(real(repo / n) for n in ("new.md", "t.md", "sub/deep.txt"))
assert got == want, f"git の変更一覧の差で拾った文書が違う: {got} / 期待 {want}"
assert not list((cfg / "coldread-gate/docs/snap").glob("*.json")), "Bash の後に控えが残る"

def in_plain():
    (plain / "a.md").write_text("a\n", encoding="utf-8")
    (plain / "b.md").write_text("b\n", encoding="utf-8")
    (plain / "c.md").write_text("c\n", encoding="utf-8")
    (plain / "d").mkdir()
    (plain / "d/c.md").write_text("c\n", encoding="utf-8")
    (plain / "e.rst").write_text("e\n", encoding="utf-8")
    for n in ("p.md", "ex.txt", "py.md", "h.txt"):
        (plain / n).write_text(n + "\n", encoding="utf-8")
# 中身が字面に在る書き込み先(ヒアドキュメント・echo/printf をパイプで受けた tee・printf・ヒア文字列・sed -i)は拾い、
# ほかのコマンドの出力のリダイレクト先(sed -n … >・ヒアドキュメントを台本として走らせた python の出力)と cp/mv の行き先は拾わない
cmd = ("cat > %s/a.md <<'EOF'\nhello\nEOF\necho hi | tee b.md >/dev/null && cp a.md c.md && mv c.md d/ "
       "&& sed -i.bak s/x/y/ e.rst && cat untouched.md > /dev/null && printf '%%s\\n' p > p.md "
       "&& sed -n 1,5p ci.log > ex.txt && cat <<< h > h.txt\npython3 - > py.md <<'EOF'\nprint(1)\nEOF" % plain.as_posix())   # \ 区切りは Git Bash に落とされる
bash("s2", "tu2", plain, cmd, in_plain)
got = pending("s2")
want = sorted(real(plain / n) for n in ("a.md", "b.md", "e.rst", "p.md", "h.txt"))
assert got == want, f"git の外で、中身が字面に在る書き込み先だけを拾えていない: {got} / 期待 {want}"

# git の中でも、ほかのコマンドの出力をリダイレクトした写し(git の変更一覧には出る)は外す。python が書いた文書は差で拾う
def in_repo_copy():
    (repo / "log.txt").write_text("log\n", encoding="utf-8")
    (repo / "py2.md").write_text("py\n", encoding="utf-8")
bash("s5", "tu5", repo, "git log > log.txt; python3 tools/write.py", in_repo_copy)
assert pending("s5") == [real(repo / "py2.md")], pending("s5")

# MCP の書くツールの path は拾い、読むだけのツールの path は拾わない
(plain / "mcp.md").write_text("m\n", encoding="utf-8")
run("docs-record", {"session_id": "s3", "tool_name": "mcp__fs__write_file", "tool_input": {"path": str(plain / "mcp.md")}})
run("docs-record", {"session_id": "s4", "tool_name": "mcp__fs__read_file", "tool_input": {"path": str(plain / "mcp.md")}})
assert pending("s3") == [real(plain / "mcp.md")] and pending("s4") == [], (pending("s3"), pending("s4"))

# フックの宣言: Bash の後と失敗の後、MCP のツールの後にも記録の口が在る(前は Write|Edit|MultiEdit だけ)
hooks = json.loads((root / "gates/hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
import re
def fires(event, tool):
    return any(re.search(grp.get("matcher", ""), tool) and any(h["command"].endswith("docs-record") for h in grp["hooks"])
               for grp in hooks.get(event, []))
assert all(fires("PostToolUse", t) for t in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "mcp__fs__write_file")), "PostToolUse の記録の口が足りない"
assert fires("PostToolUseFailure", "Bash"), "失敗した Bash(書いてから落ちたもの)の記録の口が無い"
assert not fires("PostToolUse", "BashOutput"), "Bash の matcher が BashOutput にも当たる(^…$ で囲む)"
print("DOCS_BASH_OK")
PY
# リベース・merge・checkout などで git が作業ツリーに持ち込んだ文書は、書いた役の書いた文書として拾わない。
# 2026-10-16 に、割り振りの部署が origin/main の上にリベースしたとき、メインブランチから入った文書 6 本を読み、書いていない役に直せない
# 指摘を返した(走る前と後の HEAD の差を丸ごと拾っていた)。HEAD の移動の記録(reflog)の見出しが commit の分だけを拾う
expect_output 0 "DOCS_GIT_OK" "coldread の手元の文書: リベース・merge・checkout で入った文書は拾わず、同じコマンドで書いて commit した文書は拾う" \
    "$PY_BIN" - "$ROOT" "$WORK/docs-git" <<'PY'
import json, os, pathlib, subprocess, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
gate = root / "gates/hooks/coldread-gate.py"
work.mkdir(parents=True)
cfg, repo, fresh = work / "cfg", work / "repo", work / "fresh"
repo.mkdir()
fresh.mkdir()

def run(mode, payload):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("COLDREAD_", "GIT_"))}
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_READER_CMD="cat >/dev/null; exit 1")
    r = subprocess.run([sys.executable, str(gate), *([mode] if mode else [])], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, env=e, timeout=60)
    assert r.returncode == 0, (mode, r.returncode, r.stderr.decode("utf-8", "replace"))

def git(*a, cwd=repo, check=True):
    return subprocess.run(["git", "-C", str(cwd), *a], check=check, capture_output=True)

def pending(sid):
    f = cfg / "coldread-gate/docs" / (sid + ".pending")
    return sorted(set(f.read_text(encoding="utf-8").split())) if f.exists() else []

def bash(sid, command, effect, cwd=repo):
    pay = {"session_id": sid, "tool_name": "Bash", "tool_use_id": "tu-" + sid, "cwd": str(cwd), "tool_input": {"command": command}}
    run("", dict(pay, hook_event_name="PreToolUse"))
    effect()
    run("docs-record", dict(pay, hook_event_name="PostToolUse"))

def write(name, text, at=repo):
    (at / name).write_text(text, encoding="utf-8")

real = lambda p: os.path.realpath(str(p))
for d in (repo, fresh):
    git("init", "-q", "-b", "main", cwd=d)
    git("config", "user.email", "t@example.com", cwd=d)
    git("config", "user.name", "t", cwd=d)
    git("config", "core.autocrlf", "false", cwd=d)
for n in ("up.md", "own.md", "clash.md"):
    write(n, n + " の初めの版\n")
git("add", ".")
git("commit", "-q", "-m", "init")
git("switch", "-q", "-c", "feat")
write("own.md", "部署が書いた版\n")
git("commit", "-q", "-am", "own")
git("switch", "-q", "main")
write("up.md", "メインブランチで書き換えた版\n")
write("clash.md", "メインブランチの側の版\n")
write("other.md", "メインブランチで足した文書\n")
git("add", ".")
git("commit", "-q", "-m", "upstream")
git("switch", "-q", "feat")

# 1) リベース: メインブランチから入った up.md・other.md は拾わない
bash("s1", "git rebase main", lambda: git("rebase", "-q", "main"))
assert pending("s1") == [], f"リベースで入った文書を拾った: {pending('s1')}"

# 2) 同じコマンドで書いて commit してからリベースする: 書いた文書だけを拾い、前の版は commit の前
git("switch", "-q", "-c", "feat2", "main~1")
def write_commit_rebase():
    write("mine.md", "部署が新しく書いた文書\n")
    git("add", "mine.md")
    git("commit", "-q", "-m", "mine")
    git("rebase", "-q", "main")
bash("s2", "python3 tools/w.py && git commit -m mine && git rebase main", write_commit_rebase)
assert pending("s2") == [real(repo / "mine.md")], f"書いて commit した文書だけを拾えていない: {pending('s2')}"

# 3) ブランチの切り替え・merge(fast-forward): 入った文書は拾わない
git("switch", "-q", "-c", "old", "main~1")
bash("s3", "git checkout main", lambda: git("checkout", "-q", "main"))
bash("s4", "git switch old && git merge --ff-only main", lambda: (git("switch", "-q", "old"), git("merge", "-q", "--ff-only", "main")))
assert pending("s3") == [] and pending("s4") == [], (pending("s3"), pending("s4"))

# 4) 衝突して止まった merge: 衝突した文書(UU)と、メインブランチから入って index に載った文書は拾わない。直して git add した後は拾う
git("switch", "-q", "-c", "clash", "main~1")
write("clash.md", "部署の側の版\n")
git("commit", "-q", "-am", "clash")
bash("s5", "git merge main", lambda: git("merge", "-q", "main", check=False))
assert git("status", "--porcelain").stdout.decode().count("UU clash.md") == 1, "試験の前提: clash.md が衝突していない"
assert pending("s5") == [], f"merge で入った文書を拾った: {pending('s5')}"
def resolve():
    write("clash.md", "部署が衝突を直した版\n")
    git("add", "clash.md")
bash("s6", "python3 tools/fix.py && git add clash.md", resolve)
assert pending("s6") == [real(repo / "clash.md")], f"衝突を直して git add した文書を拾えていない: {pending('s6')}"
git("merge", "--abort")

# 5) stash を戻す: git が戻した文書は拾わない(書いたときに記録してある)
git("switch", "-q", "main")
write("up.md", "部署が書きかけた版\n")
git("stash", "-q")
bash("s7", "git stash pop", lambda: git("stash", "pop", "-q"))
assert pending("s7") == [], f"stash から戻した文書を拾った: {pending('s7')}"
git("checkout", "-q", "--", "up.md")

# 6) 最初の commit(走る前に HEAD が無い)で書いて commit した文書は拾う
def first_commit():
    write("first.md", "最初の文書\n", at=fresh)
    git("add", "first.md", cwd=fresh)
    git("commit", "-q", "-m", "first", cwd=fresh)
bash("s8", "python3 tools/w.py && git commit -m first", first_commit, cwd=fresh)
assert pending("s8") == [real(fresh / "first.md")], f"最初の commit で書いた文書を拾えていない: {pending('s8')}"

# 7) commit の amend は、amend で変えた文書だけ
write("amend.md", "直す前\n", at=fresh)
git("add", "amend.md", cwd=fresh)
git("commit", "-q", "-m", "a", cwd=fresh)
def amend():
    write("amend.md", "amend で直した\n", at=fresh)
    git("commit", "-q", "-a", "--amend", "--no-edit", cwd=fresh)
bash("s9", "python3 tools/w.py && git commit -a --amend --no-edit", amend, cwd=fresh)
assert pending("s9") == [real(fresh / "amend.md")], f"amend で変えた文書だけを拾えていない: {pending('s9')}"
print("DOCS_GIT_OK")
PY
# サブエージェントが書いた文書は、その役の終わり（SubagentStop）に読んで、指摘の全文をその役に返す。記録は PostToolUse の
# 入力の agent_id で分け、親の Stop はサブエージェントの記録を読まない（前は親の Stop で読み、指摘が親に届いて親の文脈を食った）
expect_output 0 "DOCS_AGENT_OK" "coldread の手元の文書: 書いた役ごとに記録し、サブエージェントの分はその役の終わりに読んで全文をその役に返し、親の Stop は読まない" \
    "$PY_BIN" - "$ROOT" "$WORK/docs-agent" <<'PY'
import json, os, pathlib, subprocess, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
gate = root / "gates/hooks/coldread-gate.py"
work.mkdir(parents=True)
cfg, calls = work / "cfg", work / "calls"
calls.mkdir()

def run(mode, payload, reader=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("COLDREAD_")}
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_TMP_DIRS=str(work / "tmp-root"))   # WORK の下の文書を読ませる
    if reader:
        e["COLDREAD_READER_CMD"] = reader
    r = subprocess.run([sys.executable, str(gate), mode], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, env=e, timeout=60)
    assert r.returncode == 0, (mode, r.returncode, r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8")

# 読み手の差し替え: 受けた依頼文を calls/ に 1 本ずつ残し、本文に在る印をそのまま指摘に写す（どの文書を読んだかを指摘から引く）
FIND = ('n=$(ls "%s" | wc -l | tr -d " "); cat > "%s/$n.txt"; '
        'printf "詰まり: 『%%s』が何か分からない\\n" "$(grep -o "印[A-Z]" "%s/$n.txt" | head -1)"' % (calls, calls, calls))

def doc(name):
    f = work / name
    f.write_text("# 手順\n\n" + ("印%s の方針どおりに進める。" % name[0].upper()) * 30, encoding="utf-8")
    return str(f)

m, x, y = doc("m.md"), doc("x.md"), doc("y.md")
run("docs-record", {"session_id": "s1", "tool_input": {"file_path": m}})
run("docs-record", {"session_id": "s1", "agent_id": "agent-x", "agent_type": "general-purpose", "tool_input": {"file_path": x}})
run("docs-record", {"session_id": "s1", "agent_id": "agent-y", "agent_type": "general-purpose", "tool_input": {"file_path": y}})
pend = cfg / "coldread-gate/docs"
assert sorted(p.name for p in pend.glob("*.pending")) == ["s1.agent-x.pending", "s1.agent-y.pending", "s1.pending"], list(pend.iterdir())
assert (pend / "s1.agent-x.pending").read_text(encoding="utf-8").split() == [x], "サブエージェントの記録にほかの役の文書が混ざる"

# サブエージェント x の終わり: x の分だけを読み、指摘の全文を x に返す（SubagentStop の additionalContext はその役を続けさせる）
out = json.loads(run("docs-check", {"session_id": "s1", "agent_id": "agent-x", "hook_event_name": "SubagentStop",
                                    "stop_hook_active": False}, FIND))
ctx = out["hookSpecificOutput"]
assert ctx["hookEventName"] == "SubagentStop" and "decision" not in out, out
assert "印X" in ctx["additionalContext"] and x in ctx["additionalContext"], ctx
assert "印Y" not in ctx["additionalContext"] and "印M" not in ctx["additionalContext"], f"ほかの役の文書を読んだ: {ctx}"
assert len(list(calls.iterdir())) == 1 and not (pend / "s1.agent-x.pending").exists(), list(calls.iterdir())
assert not (pend / "findings").exists(), "サブエージェントの指摘をファイルに書き出した（その役に全文を返せば足りる）"

# 親の終わり: 親の分だけを読む。サブエージェント y の記録はまだ終わっていないので触らない
note = json.loads(run("docs-check", {"session_id": "s1", "hook_event_name": "Stop"}, FIND))["hookSpecificOutput"]["additionalContext"]
assert "印M" not in note and len(list(calls.iterdir())) == 2, f"親の分が 1 本だけ読まれていない: {note}"
written = list((pend / "findings").iterdir())
assert len(written) == 1 and "印M" in written[0].read_text(encoding="utf-8") and "印Y" not in written[0].read_text(encoding="utf-8"), written
assert (pend / "s1.agent-y.pending").exists(), "親の Stop がサブエージェントの記録を読んだか消した"

# 直さずに終えた x がもう一度終わっても、同じ中身は読み直さない（終わりが来る）
run("docs-record", {"session_id": "s1", "agent_id": "agent-x", "tool_input": {"file_path": x}})
assert run("docs-check", {"session_id": "s1", "agent_id": "agent-x", "hook_event_name": "SubagentStop", "stop_hook_active": True}, FIND) == ""
assert len(list(calls.iterdir())) == 2, "同じ中身を読み直した"
# 書いた記録の無い役の終わり（Claude Code の内部の役も SubagentStop を撃つ）は何もしない
assert run("docs-check", {"session_id": "s1", "agent_id": "agent-z", "hook_event_name": "SubagentStop"}, FIND) == ""
# y の終わりで y を読む
y_ctx = json.loads(run("docs-check", {"session_id": "s1", "agent_id": "agent-y", "hook_event_name": "SubagentStop"}, FIND))
assert "印Y" in y_ctx["hookSpecificOutput"]["additionalContext"], y_ctx
print("DOCS_AGENT_OK")
PY
# 同じ checkout に並べた役は、ほかの役が書いた文書を自分の物にしない。2026-10-17 に、サブエージェント 7 本を並べた調べものの部署で、
# 3 分かかる検査を走らせたサブエージェントに、その間にほかのサブエージェントが書いたノートの指摘が届いた(Bash の前と後の変更一覧の差を、
# 走った役の物にしていた)。書いた印と Bash の窓で見分け、読む前にも最後に書いた役を確かめる
expect_output 0 "DOCS_SIBLINGS_OK" "coldread の手元の文書: 並べたサブエージェントの Bash が走る間にほかのサブエージェントが書いた文書は、その Bash の役に載せず、書いた役に載せる" \
    "$PY_BIN" - "$ROOT" "$WORK/docs-siblings" <<'PY'
import json, os, pathlib, subprocess, sys, time
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
gate = root / "gates/hooks/coldread-gate.py"
work.mkdir(parents=True)
cfg, repo = work / "cfg", work / "repo"
repo.mkdir()

def run(mode, payload):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("COLDREAD_", "GIT_"))}
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_READER_CMD="cat >/dev/null; exit 1")
    r = subprocess.run([sys.executable, str(gate), *([mode] if mode else [])], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, env=e, timeout=60)
    assert r.returncode == 0, (mode, r.returncode, r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8")

def git(*a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

def pending(agent=""):
    f = cfg / "coldread-gate/docs" / ("s1" + ("." + agent if agent else "") + ".pending")
    return sorted({os.path.realpath(p) for p in f.read_text(encoding="utf-8").split()}) if f.exists() else []

def pay(agent, tid, command):
    return dict({"session_id": "s1", "tool_name": "Bash", "tool_use_id": tid, "cwd": str(repo),
                 "tool_input": {"command": command}}, **({"agent_id": agent} if agent else {}))

def start(agent, tid, command):
    run("", dict(pay(agent, tid, command), hook_event_name="PreToolUse"))

def end(agent, tid, command):
    run("docs-record", dict(pay(agent, tid, command), hook_event_name="PostToolUse"))

def write(name, text="本文\n"):
    (repo / name).write_text(text, encoding="utf-8")
    time.sleep(0.05)   # mtime と窓の時刻の前後をはっきりさせる

real = lambda n: os.path.realpath(str(repo / n))
git("init", "-q", "-b", "main")
git("config", "user.email", "t@example.com")
git("config", "user.name", "t")
write("base.md")
git("add", ".")
git("commit", "-q", "-m", "init")

# サブエージェント A が長い検査を走らせる間に、B は Write で、C は python の中で、D は走り終わらない Bash の中で、それぞれのノートを書く
CHECK = "python3 tools/check.py"
start("agent-a", "ta", CHECK)
write("a.md")                                        # A の検査の中で A が書いた文書(ほかの役の窓が始まる前)
time.sleep(0.05)
write("b.md")
run("docs-record", {"session_id": "s1", "agent_id": "agent-b", "tool_name": "Write", "tool_input": {"file_path": str(repo / "b.md")},
                    "tool_response": {"type": "create"}})
C_CMD = "python3 - <<'EOF'\np='c.md'\nopen(p,'w').write('x')\nEOF"
start("agent-c", "tc", C_CMD)
write("c.md")
end("agent-c", "tc", C_CMD)
D_CMD = "python3 tools/fetch.py"
start("agent-d", "td", D_CMD)
write("d.md")                                        # D の窓は A より後に始まり、A が終わる時もまだ走っている
end("agent-a", "ta", CHECK)
end("agent-d", "td", D_CMD)
assert pending("agent-a") == [real("a.md")], f"A の Bash の間にほかの役が書いた文書を A に載せた: {pending('agent-a')}"
assert pending("agent-b") == [real("b.md")], pending("agent-b")
assert pending("agent-c") == [real("c.md")], pending("agent-c")
assert pending("agent-d") == [real("d.md")], f"走っている間に書いた D の文書が D に載っていない: {pending('agent-d')}"

# 親が全部を commit しても、サブエージェントの印の在る文書は親に載せない。親が書いて commit した文書は載せる
write("p.md")
G_CMD = "python3 tools/p.py && git add -A && git commit -m notes"
start("", "tp", G_CMD)
git("add", "-A")
git("commit", "-q", "-m", "notes")
end("", "tp", G_CMD)
assert pending() == [real("p.md")], f"親の commit でサブエージェントの文書を親に載せた: {pending()}"

# 後のフックが来なかった Bash(投稿のゲートに止められた)の控えは、その役が終わったら走っている窓と見ない。見続けると、
# 後から走り始めた窓として、ほかの役が走る間に書いた文書を取る
H_CMD = "python3 tools/h.py"
start("agent-h", "th", H_CMD)
time.sleep(0.05)
start("agent-g", "tg", "gh issue comment 1 --body-file x.md")
run("docs-check", {"session_id": "s1", "agent_id": "agent-g", "hook_event_name": "SubagentStop"})
write("h.md")
end("agent-h", "th", H_CMD)
assert pending("agent-h") == [real("h.md")], f"終わった役の残った控えに文書を取られた: {pending('agent-h')}"

# 前に書いた役より後から別の役が同じ文書を書いたら、前の役の終わりには読まない(最後に書いた役が読む)
write("e.md", "e の本文" * 100)
run("docs-record", {"session_id": "s1", "agent_id": "agent-e", "tool_name": "Write", "tool_input": {"file_path": str(repo / "e.md")}})
time.sleep(0.05)
run("docs-record", {"session_id": "s1", "agent_id": "agent-f", "tool_name": "Edit", "tool_input": {"file_path": str(repo / "e.md")}})
run("docs-check", {"session_id": "s1", "agent_id": "agent-e", "hook_event_name": "SubagentStop"})
log = (cfg / "coldread-gate/docs.log").read_text(encoding="utf-8")
assert "後からほかの役が書いた" in log and "reader-down" not in log, log
assert pending("agent-f") == [real("e.md")], pending("agent-f")
print("DOCS_SIBLINGS_OK")
PY
# 前から在る文書は、書き換えた所を含むセクションと冒頭だけを読ませる(全体を読ませていた頃は、長い文書に数行足すと読み手が時間切れになり、
# 直していないセクションの前からの疑問が毎回返った)。新しい文書は全体。linguist-generated の印が付いた文書(生成物)は読まない
expect_output 0 "DOCS_FOCUS_OK" "coldread の手元の文書: 前から在る文書は書き換えたセクションと冒頭だけを読ませ、新しい文書は全体を読ませ、生成物の印の付いた文書は読まない" \
    "$PY_BIN" - "$ROOT" "$WORK/docs-focus" <<'PY'
import importlib.util, json, os, pathlib, subprocess, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
gate = root / "gates/hooks/coldread-gate.py"
work.mkdir(parents=True)
cfg, calls, repo = work / "cfg", work / "calls", work / "repo"
calls.mkdir()
repo.mkdir()
spec = importlib.util.spec_from_file_location("gate_focus", gate)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

def run(mode, payload, reader=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith("COLDREAD_")}
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_READER_CMD=reader or "cat >/dev/null; exit 1",
             COLDREAD_TMP_DIRS=str(work / "tmp-root"))   # WORK の下の git の外の文書も読ませる
    r = subprocess.run([sys.executable, str(gate), *([mode] if mode else [])], input=json.dumps(payload).encode("utf-8"),
                       capture_output=True, env=e, timeout=60)
    assert r.returncode == 0, (mode, r.returncode, r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8")

def git(*a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

# 読み手の差し替え: 受けた依頼文を calls/ に 1 本ずつ残す。返すのは CLEAN(渡った本文だけを見る)。
# 1 回の終わりに複数の文書を並べて読むので、名前は mktemp で分ける(数えて名付けると、並んだ読み手が同じ名前に書く)
READER = 'f=$(mktemp "%s/c.XXXXXX") && cat > "$f"; echo CLEAN' % calls.as_posix()
def prompts():
    return [f.read_text(encoding="utf-8") for f in sorted(calls.iterdir(), key=lambda f: f.stat().st_mtime_ns)]
def last_prompt():
    got = prompts()
    return got[-1], len(got)

def design(mark_c="", mark_e=""):
    secs = "".join("## セクション%s\n\n%s\n\n" % (k, "".join("印%s の %d 行目。\n" % (k, i) for i in range(12)) + (mark_c if k == "C" else mark_e if k == "E" else ""))
                   for k in "ABCDE")
    return "# 設計の題\n\nこの文書は印T の設計を書く。\n\n" + secs

git("init", "-q")
git("config", "user.email", "t@example.com")
git("config", "user.name", "t")
git("config", "core.autocrlf", "false")
(repo / ".gitattributes").write_text("gen/*.txt linguist-generated\nsnap.md linguist-generated=true\nkeep.md -linguist-generated\nno.md linguist-generated=false\nprim.md -coldread\nkept.md coldread\n", encoding="utf-8")
doc = repo / "design.md"
doc.write_text(design(), encoding="utf-8")
(repo / "gen").mkdir()
for name in ("gen/a.txt", "snap.md", "keep.md", "no.md", "prim.md", "kept.md"):
    (repo / name).write_text("写しの原文。" * 100, encoding="utf-8")
git("add", ".")
git("commit", "-q", "-m", "init")

# 1) Edit: 前の版は PostToolUse の tool_response の originalFile。セクションC を書き換えると、冒頭とセクションC だけが渡る
before = doc.read_text(encoding="utf-8")
doc.write_text(design(mark_c="印X を足した。\n"), encoding="utf-8")
run("docs-record", {"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": str(doc)},
                    "tool_response": {"filePath": str(doc), "originalFile": before}})
# 同じ回に 2 度目の Edit(セクションE)。前の版は最初の記録のまま(2 つの書き換えが両方渡る)
mid = doc.read_text(encoding="utf-8")
doc.write_text(design(mark_c="印X を足した。\n", mark_e="印Y を足した。\n"), encoding="utf-8")
run("docs-record", {"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": str(doc)},
                    "tool_response": {"filePath": str(doc), "originalFile": mid}})
run("docs-check", {"session_id": "s1", "hook_event_name": "Stop"}, READER)
prompt, n = last_prompt()
assert n == 1, n
assert prompt.startswith(g.COLD_PROMPT[:-len(g.BODY_MARK)] + g.DOC_FOCUS_NOTE + g.BODY_MARK), "抜き出しの補足が本文の印の手前に無い"
body = prompt[len(g.COLD_PROMPT) + len(g.DOC_FOCUS_NOTE):]
assert "印T" in body and g.DOC_LEAD_LABEL in body, f"冒頭(題と最初の段落)が添えられていない: {body[:300]}"
assert "印X" in body and "印C の 0 行目" in body and "印Y" in body and "印E の 0 行目" in body, f"書き換えたセクションが丸ごと渡っていない: {body}"
assert "印A" not in body and "印B" not in body and "印D" not in body, f"書き換えていないセクションまで渡った: {body}"
assert not list((cfg / "coldread-gate/docs/base").iterdir()), "読んだ後に前の版の控えが残る"
assert "\t%d/%d\t" % (len(body), len(doc.read_text(encoding="utf-8"))) in (cfg / "coldread-gate/docs.log").read_text(encoding="utf-8"), "docs.log に渡した字数/全体の字数が無い"

# 2) Bash: 前の版は走る前の HEAD。commit したあとに書き換え、同じコマンドで commit しても、走る前の HEAD と比べる
git("add", ".")
git("commit", "-q", "-m", "c")
def bash(sid, tid, command, effect):
    pay = {"session_id": sid, "tool_name": "Bash", "tool_use_id": tid, "cwd": str(repo), "tool_input": {"command": command}}
    run("", dict(pay, hook_event_name="PreToolUse"))
    effect()
    run("docs-record", dict(pay, hook_event_name="PostToolUse"))
def edit_b_and_commit():
    doc.write_text(doc.read_text(encoding="utf-8").replace("印B の 5 行目。", "印B の 5 行目を印Z に直した。"), encoding="utf-8")
    git("commit", "-q", "-am", "b")
bash("s2", "tu1", "python3 tools/edit.py && git commit -am b", edit_b_and_commit)
run("docs-check", {"session_id": "s2", "hook_event_name": "Stop"}, READER)
prompt, n = last_prompt()
assert n == 2, n
body = prompt[len(g.COLD_PROMPT) + len(g.DOC_FOCUS_NOTE):]
assert "印Z" in body and "印B の 0 行目" in body and "印C" not in body and "印A" not in body, f"Bash で書き換えたセクションだけが渡っていない: {body}"

# 3) 新しい文書は全体: Write の新規(type create)と、Bash で作った HEAD に無い文書
new = repo / "new.md"
new_text = design()
new.write_text(new_text, encoding="utf-8")
run("docs-record", {"session_id": "s3", "tool_name": "Write", "tool_input": {"file_path": str(new)},
                    "tool_response": {"type": "create", "filePath": str(new), "originalFile": None}})
run("docs-check", {"session_id": "s3", "hook_event_name": "Stop"}, READER)
prompt, n = last_prompt()
assert n == 3 and prompt == g.COLD_PROMPT + new_text, "新しく作った文書が全体のまま(投稿と同じ依頼文)で渡っていない"
new2 = repo / "new2.md"
bash("s4", "tu2", "python3 tools/make.py", lambda: new2.write_text(design(mark_c="印W\n"), encoding="utf-8"))
run("docs-check", {"session_id": "s4", "hook_event_name": "Stop"}, READER)
prompt, n = last_prompt()
assert n == 4 and prompt == g.COLD_PROMPT + new2.read_text(encoding="utf-8"), "HEAD に無い文書を全体で読んでいない"

# 4) 書く前と同じ中身は読まない(読み手を起動しない)。まだ読んでいない中身で、同じ中身を書き直した形
doc.write_text(doc.read_text(encoding="utf-8") + "印S\n", encoding="utf-8")
run("docs-record", {"session_id": "s6", "tool_name": "Edit", "tool_input": {"file_path": str(doc)},
                    "tool_response": {"filePath": str(doc), "originalFile": doc.read_text(encoding="utf-8")}})
run("docs-check", {"session_id": "s6", "hook_event_name": "Stop"}, READER)
assert last_prompt()[1] == 4, "書く前と同じ中身の文書で読み手を起動した"
assert "書く前と同じ中身" in (cfg / "coldread-gate/docs.log").read_text(encoding="utf-8")

# 5) 生成物の印(linguist-generated。値なし・=true)と -coldread の付いた文書は読まない。-linguist-generated・=false・coldread(値なし)は読む
for name in ("gen/a.txt", "snap.md", "keep.md", "no.md", "prim.md", "kept.md"):
    f = repo / name
    f.write_text(name + " の写しの原文を取り直した。" * 100, encoding="utf-8")   # 中身を分ける(同じ中身は 1 回しか読まない)
    run("docs-record", {"session_id": "s7", "tool_name": "Write", "tool_input": {"file_path": str(f)},
                        "tool_response": {"type": "create", "filePath": str(f), "originalFile": None}})
run("docs-check", {"session_id": "s7", "hook_event_name": "Stop"}, READER)
got = prompts()[4:]
assert len(got) == 3, f"読まない印の付いた文書を読んだか、印を外した文書を読まなかった: {len(got)} 回"
log = (cfg / "coldread-gate/docs.log").read_text(encoding="utf-8")
skipped = [ln for ln in log.splitlines() if "読まない印" in ln]
assert len(skipped) == 3 and all(any(ln.endswith(n) for ln in skipped) for n in ("a.txt", "snap.md", "prim.md")), skipped

# 6) 見出しの無い文書(txt)は、書き換えた行の前後を段落の切れ目まで
plain = repo / "plain.txt"
paras = "\n\n".join("段落%d の文。\n続き%d。" % (i, i) for i in range(40)) + "\n"
plain.write_text(paras.replace("段落20 の文", "段落20 を印V に直した文"), encoding="utf-8")
run("docs-record", {"session_id": "s8", "tool_name": "Edit", "tool_input": {"file_path": str(plain)},
                    "tool_response": {"filePath": str(plain), "originalFile": paras}})
run("docs-check", {"session_id": "s8", "hook_event_name": "Stop"}, READER)
body = last_prompt()[0][len(g.COLD_PROMPT) + len(g.DOC_FOCUS_NOTE):]
assert "印V" in body and "段落0 の文" in body and "段落5 の文" not in body and "段落35 の文" not in body, body

# 7) 前の版を返さないツール(MCP の書くツール)は、記録したときの HEAD の版と比べる
doc.write_text(doc.read_text(encoding="utf-8").replace("印D の 3 行目。", "印D の 3 行目を印U に直した。"), encoding="utf-8")
run("docs-record", {"session_id": "s9", "tool_name": "mcp__fs__write_file", "tool_input": {"path": str(doc)}, "tool_response": [{"type": "text"}]})
run("docs-check", {"session_id": "s9", "hook_event_name": "Stop"}, READER)
body = last_prompt()[0][len(g.COLD_PROMPT) + len(g.DOC_FOCUS_NOTE):]
assert "印U" in body and "印D の 0 行目" in body and "印A" not in body and "印C" not in body, f"HEAD の版と比べたセクションだけが渡っていない: {body}"

# 8) DOC_SECTION_MAX 字を超えるセクションは、セクションの見出しと、書き換えた箇条(字下げした子の箇条と、字下げした囲みを含む。囲みの中の
#    字下げの無い行・空行では切らない)だけ
def long_doc(mark=""):
    items = "".join("- **箇条%d**: %s\n" % (i, "印L%d の文。" % i * 30) for i in range(12))
    child = "- **親の箇条**: 印P の文。\n  - 子の箇条: 印Q の文%s。\n\n  ```\n- 囲みの中: 印R\n\n続き: 印S\n  ```\n" % mark
    return "# 長い文書\n\nこの文書は印T の長いセクションを持つ。\n\n## 短いセクション\n\n印A の文。\n\n## 長いセクション\n\n" + items + child + "- **後の箇条**: 印N の文。\n"
big = repo / "big.md"
big.write_text(long_doc(), encoding="utf-8")
before = big.read_text(encoding="utf-8")
assert len(before.split("## 長いセクション")[1]) > g.DOC_SECTION_MAX
big.write_text(long_doc("を印K に直した"), encoding="utf-8")
run("docs-record", {"session_id": "s10", "tool_name": "Edit", "tool_input": {"file_path": str(big)},
                    "tool_response": {"filePath": str(big), "originalFile": before}})
run("docs-check", {"session_id": "s10", "hook_event_name": "Stop"}, READER)
body = last_prompt()[0][len(g.COLD_PROMPT) + len(g.DOC_FOCUS_NOTE):]
assert g.DOC_HEAD_LABEL + "\n## 長いセクション" in body, f"長いセクションの見出しが添えられていない: {body}"
assert all(s in body for s in ("印K", "印P", "印R", "印S")), f"書き換えた箇条が親と囲みごと渡っていない: {body}"
assert not any(s in body for s in ("印L0", "印L11", "印N", "印A")), f"長いセクションの書き換えていない箇条まで渡った: {body}"
print("DOCS_FOCUS_OK")
PY
# 読む前に読む中身を覚え、読めなかった物だけ外す。読み終えてから覚えていた頃は、裏の読み(1 回 2〜4 分)の間に同じ文書が
# commit で記録し直され、次のターンの終わりの読みが同じ中身をもう一度読んだ(2026-10-17 に説明書の部署で、同じ 11 本を 2 回)
expect_output 0 "DOCS_RACE_OK" "coldread の手元の文書: 読みの最中に同じ中身が記録し直されても、次の終わりの読みは読み直さず、読めなかった中身は次の終わりにまた読む" \
    "$PY_BIN" - "$ROOT" "$WORK/docs-race" <<'PY'
import json, os, pathlib, subprocess, sys, time
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
gate = root / "gates/hooks/coldread-gate.py"
work.mkdir(parents=True)
cfg, calls, docs = work / "cfg", work / "calls", work / "docs"
calls.mkdir()
docs.mkdir()

def env(reader):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("COLDREAD_", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_JOB_DIR"))}
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_READER_CMD=reader, COLDREAD_TMP_DIRS=str(work / "tmp-root"))
    return e

def hook(mode, payload, reader="cat >/dev/null; exit 1", wait=True):
    p = subprocess.Popen([sys.executable, str(gate), mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env(reader))
    p.stdin.write(json.dumps(payload).encode("utf-8"))
    p.stdin.close()
    if not wait:
        return p
    p.wait(timeout=60)
    assert p.returncode == 0, (mode, p.returncode, p.stderr.read().decode("utf-8", "replace"))

def record(sid, path):
    hook("docs-record", {"session_id": sid, "tool_name": "Write", "tool_input": {"file_path": str(path)},
                         "tool_response": {"type": "create", "filePath": str(path), "originalFile": None}})

def stop(sid, reader, wait=True):
    return hook("docs-check", {"session_id": sid, "hook_event_name": "Stop"}, reader, wait)

READER = 'f=$(mktemp "%s/c.XXXXXX") && cat > "$f"; echo CLEAN' % calls.as_posix()
started = work / "started"
SLOW = "touch %s; sleep 3; " % started.as_posix() + READER   # 動き出した印を置いてから、読み終えるまで 3 秒かかる読み手
n_calls = lambda: len(list(calls.iterdir()))

# 1) 読みの最中に同じ中身が記録し直されても、次の終わりは読み直さない
a = docs / "a.md"
a.write_text("# 題\n\n" + "読みの最中に記録し直される文書の本文。" * 40 + "\n", encoding="utf-8")
record("s1", a)
first = stop("s1", SLOW, wait=False)
deadline = time.time() + 20
while not started.exists() and time.time() < deadline:
    time.sleep(0.1)   # 1 つ目の読みが読み手を起動するまで待つ
assert first.poll() is None, "1 つ目の読みが、試験の前提より早く終わった(読み手の sleep が効いていない)"
record("s1", a)   # 同じ中身を commit で記録し直した形
stop("s1", READER)
first.wait(timeout=60)
assert first.returncode == 0, first.stderr.read().decode("utf-8", "replace")
assert n_calls() == 1, f"同じ中身を 2 回読んだ: {n_calls()} 回"
log = (cfg / "coldread-gate/docs.log").read_text(encoding="utf-8")
assert "同じ中身を前に読んだ" in log, log

# 2) 読めなかった中身は覚えから外れ、次の終わりにまた読む
b = docs / "b.md"
b.write_text("# 題\n\n" + "読み手が落ちた文書の本文。" * 40 + "\n", encoding="utf-8")
record("s2", b)
stop("s2", "cat >/dev/null; exit 1")
assert "reader-down" in (cfg / "coldread-gate/docs.log").read_text(encoding="utf-8")
record("s2", b)
stop("s2", READER)
assert n_calls() == 2, f"読めなかった中身を次の終わりに読み直していない: {n_calls()} 回"
print("DOCS_RACE_OK")
PY
# メインブランチに入れる前のゲート(--land の check から呼ぶ branch-check): ブランチが足した・変えた文書だけを読み、詰まりが在れば 1 で止める。
# 前は手元の文書の読みがターンの終わりに裏で走るだけで、部署が同じターンで --land まで済ませると、指摘はメインブランチに入った後に届いた
expect_output 0 "DOCS_BRANCH_OK" "coldread のブランチのゲート: メインブランチとの分かれ目からブランチが書いた文書だけを読み、詰まりで止め、推測だけなら通し、同じ依頼文は読み直さず、読めなければ止める" \
    "$PY_BIN" - "$ROOT" "$WORK/docs-branch" <<'PY'
import json, os, pathlib, subprocess, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
gate = root / "gates/hooks/coldread-gate.py"
work.mkdir(parents=True)
cfg, calls, repo = work / "cfg", work / "calls", work / "repo"
calls.mkdir()
repo.mkdir()

def git(*a):
    return subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True).stdout.decode("utf-8").strip()

# 読み手の差し替え: 依頼文を calls/ に残し、印「印STUCK」が在れば詰まり、「印GUESS」が在れば推測だけ、ほかは CLEAN を返す
READER = ('f=$(mktemp "%s/c.XXXXXX") && cat > "$f"; if grep -q 印STUCK "$f"; then echo "詰まり: 印STUCK の語が分からない"; '
          'elif grep -q 印GUESS "$f"; then echo "補完: 印GUESS を推測で読んだ"; else echo CLEAN; fi') % calls.as_posix()

def check(reader=READER):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("COLDREAD_", "CLAUDE_JOB_DIR"))}
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_READER_CMD=reader)
    r = subprocess.run([sys.executable, str(gate), "branch-check"], cwd=str(repo), capture_output=True, env=e, timeout=120)
    return r.returncode, r.stdout.decode("utf-8")

def prompts():
    return [f.read_text(encoding="utf-8") for f in sorted(calls.iterdir(), key=lambda f: f.stat().st_mtime_ns)]

def doc(*secs):
    return "# 題\n\nこの文書は印T の設計を書く。\n\n" + "".join("## セクション%s\n\n%s\n\n" % (k, "".join("印%s の %d 行目。\n" % (k, i) for i in range(40)) + extra)
                                                  for k, extra in secs)   # 1 つのセクションで 300 字(DOC_MIN_LEN)を超える

git("init", "-q", "-b", "main")
git("config", "user.email", "t@example.com")
git("config", "user.name", "t")
git("config", "core.autocrlf", "false")
(repo / ".gitattributes").write_text("gen.md linguist-generated\n", encoding="utf-8")
(repo / "old.md").write_text(doc(("A", ""), ("B", ""), ("C", "")), encoding="utf-8")
(repo / "untouched.md").write_text(doc(("U", "")), encoding="utf-8")
git("add", ".")
git("commit", "-q", "-m", "base")
git("update-ref", "refs/remotes/origin/main", "HEAD")
git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
git("switch", "-q", "-c", "feat")
(repo / "old.md").write_text(doc(("A", ""), ("B", "印STUCK を足した。\n"), ("C", "")), encoding="utf-8")
(repo / "new.md").write_text(doc(("N", "印GUESS の語。\n")), encoding="utf-8")
(repo / "gen.md").write_text(doc(("G", "")), encoding="utf-8")
(repo / "short.md").write_text("印SHORT\n", encoding="utf-8")
git("add", ".")
git("commit", "-q", "-m", "feat")

# 1) ブランチが変えた old.md は書き換えたセクションだけ、足した new.md は全体を読む(移した行は題と冒頭だけで、抜き出しが 8 割を超える)。生成物・短い文書・ブランチが触っていない文書は読まない。
#    詰まりが在るので 1。詰まりの行に作業ツリーのルートからのパスが付き、末尾の行に件数と全文の場所が出る
rc, out = check()
got = prompts()
assert rc == 1, (rc, out)
assert len(got) == 2, f"読んだ文書の数が違う: {len(got)}"
body = next(p for p in got if "印STUCK" in p)
assert "印B の 0 行目" in body and "印A" not in body and "印C" not in body, "old.md の書き換えたセクションだけを読んでいない"
assert any("印N の 0 行目" in p for p in got) and not any("印G の" in p or "印U の" in p or "印SHORT" in p for p in got), "読む文書の選び方が違う"
assert "old.md — 詰まり: 印STUCK の語が分からない" in out, out
last = out.strip().splitlines()[-1]
assert "2 本を読んだ" in last and "詰まり 1 件・推測で埋めた箇所 1 件" in last and "全文: " in last, last
assert "new.md" in pathlib.Path(last.split("全文: ")[1]).read_text(encoding="utf-8"), "全文に推測の指摘が無い"

# 2) 同じ依頼文は読み直さず、覚えた判定で同じく止める(メインブランチが進んでリベースしたときの打ち直し)
rc, out = check()
assert rc == 1 and len(prompts()) == 2 and "新しく読んだ 0 本" in out, (rc, len(prompts()), out)

# 3) 詰まりを直せば、推測で埋めた箇所が残っていても通す(直したセクションだけを新しく読む)
(repo / "old.md").write_text(doc(("A", ""), ("B", "語の意味を書いた。\n"), ("C", "")), encoding="utf-8")
git("commit", "-q", "-am", "fix")
rc, out = check()
assert rc == 0 and len(prompts()) == 3 and "詰まり 0 件・推測で埋めた箇所 1 件" in out, (rc, len(prompts()), out)

# 4) 読み手を起動できない文書が在れば止める(読まずに通すとゲートが黙って空になる)
(repo / "new2.md").write_text(doc(("M", "")), encoding="utf-8")
git("add", "new2.md")
git("commit", "-q", "-m", "more")
rc, out = check("cat >/dev/null; exit 1")
assert rc == 1 and "読めなかった文書" in out and "new2.md" in out, (rc, out)
git("rm", "-q", "new2.md")
git("commit", "-q", "-m", "drop")

# 5) ブランチが足した文書のうち、ブランチが消した・変えた文書の分かれ目の版に在った行は移しただけとして読まない(スキルの本文のセクションを
#    references/ へ移す分け)。見出しの深さが変わっても移した行。新しく書いた行を含むセクションだけを読み、全部が移した行なら読まない
before = len(prompts())
(repo / "old.md").write_text(doc(("A", "")), encoding="utf-8")   # セクション B・C を old.md から削った
(repo / "moved.md").write_text("# 移した先\n\n移したセクション。\n\n" + "".join("### セクション%s\n\n%s\n" % (k, "".join("印%s の %d 行目。\n" % (k, i) for i in range(40)))
                                                           for k in "BC") + "印MOVEDNEW を足した。\n", encoding="utf-8")
(repo / "copied.md").write_text("## セクションB\n\n" + "".join("印B の %d 行目。\n" % i for i in range(40)), encoding="utf-8")
git("add", ".")
git("commit", "-q", "-m", "split")
rc, out = check()
got = prompts()[before:]
assert rc == 0 and len(got) == 2, (rc, len(got), out)   # old.md(削った所)と moved.md(新しい行のセクション)。copied.md は読まない
moved = next(p for p in got if "印MOVEDNEW" in p)
assert "印C の 39 行目" in moved and "印B の 39 行目" not in moved, "moved.md の新しい行のセクションだけを読んでいない"

# 6) 移した元を消した(diff の D。リネームもここ)ときも同じ。移した行が 1 つも無い足した文書は全体を読む
before = len(prompts())
git("mv", "untouched.md", "renamed.md")
(repo / "fresh.md").write_text("# 別\n\n" + "".join("印F の %d 行目。\n" % i for i in range(40)), encoding="utf-8")
git("add", ".")
git("commit", "-q", "-m", "rename")
rc, out = check()
got = prompts()[before:]
assert rc == 0 and len(got) == 1 and "印F の 0 行目" in got[0] and "印F の 39 行目" in got[0], (rc, len(got), out)   # renamed.md は読まない
print("DOCS_BRANCH_OK")
PY
# 一時の置き場に書いた git の外のファイル(書いた役が自分のために置いた写し・窓口が渡した頼みの文書)は読まない。
# 2026-10-16 に、scratchpad(/private/tmp/claude-<uid>/…)と /private/tmp の写しを読み、毎回「直さずに残す」で終わる指摘を出した。
# 一時フォルダの下でも git の中は読み、一時フォルダの外は今どおり読む。綴りと実体の違うルート(macOS の /var → /private/var)も効かせる
expect_output 0 "DOCS_TMP_OK" "coldread の手元の文書: 一時の置き場の下の git の外のファイルは読まず、git の中と一時の置き場の外は読む" \
    "$PY_BIN" - "$ROOT" "$WORK/docs-tmp" <<'PY'
import json, os, pathlib, subprocess, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root, work = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
gate = root / "gates/hooks/coldread-gate.py"
work.mkdir(parents=True)
cfg, calls = work / "cfg", work / "calls"
calls.mkdir()
# 読み手の差し替え: 受けた依頼文を calls/ に 1 本ずつ残す(並んで読むので名前は mktemp で分ける)
READER = 'f=$(mktemp "%s/c.XXXXXX") && cat > "$f"; echo CLEAN' % calls.as_posix()

def read_marks(docs, **env):
    """docs を 1 回の記録と終わりに流し、読み手に渡った文書の印を返す。"""
    for f in calls.iterdir():
        f.unlink()
    e = {k: v for k, v in os.environ.items() if not k.startswith("COLDREAD_")}
    e.update(CLAUDE_CONFIG_DIR=str(cfg), COLDREAD_READER_CMD=READER, **env)
    for mode, payload in [*(("docs-record", {"session_id": "s1", "tool_name": "Write", "tool_input": {"file_path": str(p)}})
                            for p in docs), ("docs-check", {"session_id": "s1", "hook_event_name": "Stop"})]:
        r = subprocess.run([sys.executable, str(gate), mode], input=json.dumps(payload).encode("utf-8"),
                           capture_output=True, env=e, timeout=60)
        assert r.returncode == 0, (mode, r.returncode, r.stderr.decode("utf-8", "replace"))
    got = [f.read_text(encoding="utf-8") for f in calls.iterdir()]
    return sorted(m for m in (pathlib.Path(p).stem for p in docs) if any("印" + m + "。" in t for t in got))

def doc(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 題\n\n" + ("印%s。" % path.stem) * 60, encoding="utf-8")   # 300 字を超える。印は名前ごとに変える
    return path

def git_init(d):
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True, capture_output=True)

# 1) 既定のルート: Python の一時フォルダ(TMPDIR が決める tempfile.gettempdir())の下の git の外は読まず、git の中は読む
tmp = work / "t"
git_init(tmp / "repo")
plain, tracked = doc(tmp / "plain.md"), doc(tmp / "repo" / "tracked.md")
assert read_marks([plain, tracked], TMPDIR=str(tmp), TEMP=str(tmp), TMP=str(tmp)) == ["tracked"], "既定の一時フォルダの下の git の外を読んだか、git の中を読まない"
# 実パスの綴りで渡しても同じ(macOS では一時フォルダが /var/folders/… で、実体は /private/var/folders/…)
real = doc(pathlib.Path(os.path.realpath(tmp)) / "real.md")
assert read_marks([real], TMPDIR=str(tmp), TEMP=str(tmp), TMP=str(tmp)) == [], "実パスの綴りの一時フォルダの下を読んだ"

# 2) ルートを COLDREAD_TMP_DIRS で替える: ルートの下の git の外は読まず、ルートの外は読む(試験の WORK 自体が一時フォルダの下に在るので、外はルートを替えて作る)
roots = work / "k"
inner, outer = doc(roots / "inner.md"), doc(work / "out" / "outer.md")
assert read_marks([inner, outer], COLDREAD_TMP_DIRS=str(roots)) == ["outer"], "ルートの下の git の外を読んだか、ルートの外を読まない"

# 3) 綴りと実体の違うルート: ルートを symlink の綴りで書いても、実体の綴りで書いても、もう片方の綴りのファイルを読まない
link = work / "k-link"
try:
    os.symlink(str(roots), str(link), target_is_directory=True)
except (OSError, NotImplementedError) as exc:
    print("  ok   一時の置き場のルートの綴りと実体の違い # SKIP symlink: %s" % exc)
else:
    via_link, via_real = doc(link / "vialink.md"), doc(roots / "viareal.md")
    assert read_marks([via_real], COLDREAD_TMP_DIRS=str(link)) == [], "ルートを symlink で書いたとき、実体の綴りのファイルを読んだ"
    assert read_marks([via_link], COLDREAD_TMP_DIRS=str(roots)) == [], "ルートを実体で書いたとき、symlink の綴りのファイルを読んだ"
# 4) Claude Code の会話ごとの一時の置き場(<設定の置き場>/jobs/<会話の id>/tmp と $CLAUDE_JOB_DIR/tmp)の下は読まない。
# jobs の下でも tmp の外は読む
job_doc, job_side = doc(cfg / "jobs" / "abc123" / "tmp" / "summary.md"), doc(cfg / "jobs" / "abc123" / "side.md")
own_doc = doc(work / "own-job" / "tmp" / "deliver.md")
assert read_marks([job_doc, job_side, own_doc], COLDREAD_TMP_DIRS=str(roots)) == ["deliver", "side"], "jobs/<id>/tmp の下を読んだか、tmp の外を読まない"
own_doc2 = doc(work / "own-job" / "tmp" / "deliver2.md")   # 上で読んだ中身は覚えられて読まれないので、別の中身で見る
assert read_marks([own_doc2], COLDREAD_TMP_DIRS=str(roots), CLAUDE_JOB_DIR=str(work / "own-job")) == [], "$CLAUDE_JOB_DIR/tmp の下を読んだ"
log = (cfg / "coldread-gate/docs.log").read_text(encoding="utf-8")
assert "一時の置き場(git の外)" in log and str(plain) in log, "読まなかった理由が docs.log に無い"
print("DOCS_TMP_OK")
PY
# 旗表・帰属の各分岐を個別に殺すテスト(消すとどれか 1 件だけが赤くなる形にする)
expect_output 0 "詰まり" "--旗=値 の密着形もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body='$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "-b 値 の密着形もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 -b'$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "release create --notes 長形もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh release create v1 --notes '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "issue close -c 短縮形もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue close 9 -c '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "command 前置越しの gh もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "command gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "絶対パス起動の gh もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "/usr/local/bin/gh issue comment 1 --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "-R 前置があってもサブコマンドを見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh -R o/r pr review 12 --comment -b '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "-H 前置があっても graphql の mutation を見逃さない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api -H 'X-Foo: bar' graphql -f query='mutation { addComment(input:{body:\"$CR_BODY $CR_PAD\"}) }'"
# リダイレクトは区切りではない(演算子と行き先だけを除く)。挟まれた本文を見失えば無検査で通る
expect_output 0 "詰まり" "本文旗の直後のリダイレクトで本文を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 5 --body >&2 '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "2>&1 を挟んでも本文を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh pr comment 123 --body 2>&1 '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "出力リダイレクト付きでも本文を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 5 --body '$CR_BODY $CR_PAD' >/dev/null"
# ヒアドキュメントのデリミタ記法(gh --help や人が実際に書く形)
expect_output 0 "詰まり" '二重引用符デリミタのヒアドキュメントもゲートに掛かる' \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body-file - <<\"EOF\"
$CR_BODY
$CR_PAD
EOF"
expect_output 0 "詰まり" "ハイフン入りデリミタのヒアドキュメントもゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body-file - <<'JSON-EOF'
$CR_BODY
$CR_PAD
JSON-EOF"
# 本文でない値を読み役へ送らない・投稿でない gh を止めない
# 読み役に渡るのが JSON の殻だと、初見の読み手は本文でなくエスケープ済みの構造を読まされる
CR_STUB_SHELL='if grep -q body; then printf "詰まり: JSON の殻が読み役に渡った\\n"; else echo CLEAN; fi'
expect_output 0 "検査を通過" "--input - の JSON は殻でなく .body が読み役に届く" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SHELL" "$CR_JSON_POST"
# 解析を打ち切る上限。超える入力を素通しにすると、長さで検査を外せる。
# あわせて「解析中の想定外の例外は deny に倒す」も検査する(上限超過は ValueError 以外で投がる)
expect_output 0 "COLDREAD_MAX_LEN" "上限を超える長さのコマンドは deny し、上げ方を案内する" \
    env COLDREAD_MAX_LEN=300 "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body '$CR_BODY $CR_PAD'"
# 引用が閉じない形は解析器が None を返す経路(例外ではない)
expect_output 0 "解析できない" "引用が閉じないコマンドは deny(fail-closed)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body '$CR_BODY $CR_PAD"
# 解析器が例外を投げる経路。実物の入力で非 ValueError を発生させる手段は Python の版に依存する
# ため、解析器を代役に差し替えて倒れ先だけを固定する
expect_output 0 "解析できない" "解析が例外で落ちても deny(fail-closed)" \
    "$PY_BIN" "$ROOT/tests/coldread-raise-case.py"
# 読み役の中で発火すると、読み役が読み役を起動する入れ子になる(外側はタイムアウトで無検査通過)
expect_output 0 "ALLOW_EMPTY" "読み役の中では発火しない(入れ子を作らない)" \
    env COLDREAD_IN_READER=1 "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body '$CR_BODY $CR_PAD'"
# 引用の中の ` や $( は展開されないので、本文の一部として読ませる(止めると普通の文章が通らない)
expect_output 0 "詰まり" "コードフェンスで始まる本文も読み役に届く" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body '\`\`\`
$CR_BODY $CR_PAD
\`\`\`'"
expect_output 0 "詰まり" "単一引用の中の \$( は展開されないので本文として読ませる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body '\$(cat x) と書く。$CR_BODY $CR_PAD'"
# ヒアドキュメントは付いた単純コマンドに帰属させる(同じ行の別コマンドの中身を巻き込まない)
expect_output 0 "ALLOW_EMPTY" "別コマンドのヒアドキュメントを gh の本文に混ぜない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cat > /tmp/cfg.json <<'SEC'
{\"api_key\": \"$CR_BODY $CR_PAD\"}
SEC
gh pr comment 123 -F - <<'BODY'
短い本文
BODY"
# 解析器が読めなかったものは「投稿でない」ではなく「検査できない」に倒す(素通りにしない)
expect_output 0 "詰まり" "融合形の global 旗(--repo=)でもサブコマンドを見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh --repo=o/r issue comment 1 -b '$CR_BODY $CR_PAD'"
expect_output 0 "取り出せない" "未クォートのコマンド置換は検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body \$(cat /tmp/x) # $CR_PAD"
expect_output 0 "取り出せない" "バッククォートのコマンド置換も検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body \`cat /tmp/x\` # $CR_PAD"
expect_output 0 "取り出せない" "知らない旗でサブコマンドを特定できないときは deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh --unknown-flag=x issue comment 1 -b '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "project edit の --readme もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh project edit 1 --readme '$CR_BODY $CR_PAD'"
# mutation は body 以外のフィールドにもブロック文字列を書ける。中身を丸ごと本文として抜くと ID・
# トークン・設定値まで読み役(外部プロセス)へ渡るので、body: のフィールドの値だけを抜く
CR_STUB_NO_SECRET='if grep -q DB_PASSWORD; then printf "詰まり: body 以外のフィールドの値が読み役に渡った\n"; else echo CLEAN; fi'
expect_output 0 "検査を通過" "graphql の mutation は body: のフィールドだけを読ませ、ほかのフィールドの値は読み役へ送らない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NO_SECRET" "gh api graphql -f query='mutation { addComment(input:{subjectId: \"\"\"DB_PASSWORD=$CR_PAD\"\"\", body: \"\"\"$CR_BODY\"\"\"}) }'"
# body のフィールドを持たない mutation(resolveReviewThread など)は投稿ではない。止めていた 57 件の往復の元
expect_output 0 "ALLOW_EMPTY" "body のフィールドを持たない graphql の mutation は止めない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api graphql -f query='mutation { resolveReviewThread(input:{threadId:\"PRRT_x\"}) { thread { isResolved } } }' # $CR_PAD"
CR_STUB_SEES_V=$(cr_stub_sees MARK_V)
expect_output 0 "MARK_V が届いた" "graphql の mutation の body: \$変数 は、-f で渡した値を読ませる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_V" "gh api graphql -f query='mutation(\$b: String!) { addComment(input:{subjectId:\"x\", body: \$b}) { clientMutationId } }' -f b='MARK_V $CR_BODY $CR_PAD'"
expect_output 0 "取り出せない" "graphql の mutation の body: \$変数 の値が無ければ止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api graphql -f query='mutation(\$b: String!) { addComment(input:{subjectId:\"x\", body: \$b}) { clientMutationId } }' # $CR_PAD"
# 短縮形は綴りが同じでも意味が違う。投稿でないサブコマンドの -b/-c/-n を本文と誤認すると、
# ローカル操作の引数が読み役(外部プロセス)へ渡り、的外れな deny で作業も止まる
expect_output 0 "ALLOW_EMPTY" "pr checkout の -b(ブランチ名)は本文扱いしない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr checkout 123 -b $CR_BODY$CR_PAD"
expect_output 0 "ALLOW_EMPTY" "issue develop の -n(ブランチ名)は本文扱いしない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue develop 5 -n $CR_BODY$CR_PAD"
expect_output 0 "ALLOW_EMPTY" "issue view の -c(--comments)は本文扱いしない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue view 12 -c # $CR_PAD $CR_BODY"
expect_output 0 "詰まり" "close の -c(--comment)は本文として拾う" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue close 9 -c '$CR_BODY $CR_PAD'"
# gh api --input の中身は本文とは限らない(secrets の暗号値等)。.body を持つときだけ読ませる
expect_output 0 "取り出せない" "api --input の .body でない長い JSON は読み役に送らず deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api -X PUT /repos/o/r/actions/secrets/K --input - <<'EOF'
{\"encrypted_value\": \"$CR_PAD$CR_PAD\", \"key_id\": \"1\"}
EOF"
# secret/variable set は長い旗まで --body なので、綴りだけでは投稿と見分けられない
expect_output 0 "ALLOW_EMPTY" "secret set の値(--body)は読み役に送らない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh secret set DEPLOY_KEY --body '$CR_BODY $CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "variable set の値(--body)は読み役に送らない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh variable set CONF --body '$CR_BODY $CR_PAD'"
expect_output 0 "ALLOW_EMPTY" "workflow run の -F は本文ではないので止めない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh workflow run deploy.yml -F name=scully -F greeting=hello # $CR_PAD"
expect_output 0 "ALLOW_EMPTY" "gist create の説明文(-d)だけでは本文と見なさない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh gist create -d '$CR_BODY $CR_PAD' # $CR_PAD"
# 部分文字列で拾うと、gh コマンドの無い長文が「解析できない」で止まる(引用未終端で判別できる)
expect_output 0 "ALLOW_EMPTY" "gh を含む語(highlight 等)だけでは解析に入らない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "echo it's a highlight of the day # $CR_PAD"
# 検査できない本文は、読める本文が同居していても握り潰さない
expect_output 0 "取り出せない" "読める本文と同居しても、読めない本文ファイルは止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body '$CR_BODY $CR_PAD' && gh pr comment 2 --body-file /tmp/x.md"
expect_output 0 "取り出せない" "--input の JSON ファイルが無ければ止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh api repos/o/r/issues/1/comments --input /tmp/payload.json # $CR_PAD"
# --input - でヒアドキュメントを取り損ねると候補ゼロ・止めた理由ゼロになり、「投稿でない」と
# 読まれて無検査で通る。兄弟の --body-file - と同じ向きに倒すことの検査
expect_output 0 "取り出せない" "--input - にヒアドキュメントが無ければ検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cat /tmp/payload.json | gh api repos/o/r/issues/1/comments --input - # $CR_PAD"
# 行末が CRLF のヒアドキュメント。\n 固定で照合すると開始行・終端行ともマッチせず、正しく書いた
# 投稿が「stdin 渡し」という嘘の理由で止まる(--body-file)か、無検査で通る(--input)
CR_CRLF_FILE=$(printf 'gh issue comment 1 --body-file - <<'\''EOF'\''\r\n%s\r\n%s\r\nEOF\r\n' "$CR_BODY" "$CR_PAD")
expect_output 0 "詰まり" "行末が CRLF のヒアドキュメントでも本文を取り出す" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_CRLF_FILE"
CR_CRLF_INPUT=$(printf 'gh api repos/o/r/issues/1/comments --input - <<'\''EOF'\''\r\n{"body": "%s%s"}\r\nEOF\r\n' "$CR_BODY" "$CR_PAD")
expect_output 0 "詰まり" "CRLF のヒアドキュメントを --input - で渡しても本文を検査する" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_CRLF_INPUT"
expect_output 0 "取り出せない" "-F(--body-file 短縮形)の本文ファイルが無ければ止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr create -t T -F /tmp/body.md # $CR_PAD"
expect_output 0 "取り出せない" "パイプの stdin は検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cat /tmp/b.md | gh issue comment 1 --body-file - # $CR_PAD"
expect_output 0 "取り出せない" "変数渡しの本文は検査できないので deny" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body \"\$BODY\" # $CR_PAD"
expect_output 0 "解析できない" "引用が閉じない gh コマンドは deny(fail-closed)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body 'これは閉じない引用 $CR_PAD"

# 倒れ先の検査: 読み役出力が UTF-8 で読めないときは deny に倒す(復号を errors="replace" に
# 緩めると詰まりマーカーが化けて無音 allow になる——それを赤くする回帰テスト)
CR_STUB_SJIS='cat >/dev/null; printf "\213\154\202\334\202\350\072\040\223\307\202\337\202\310\202\242\012"'
expect_output 0 "coldreader(文脈ゼロの読み手)の起動に失敗" "読み役出力が UTF-8 でないときは deny に倒す" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SJIS" "$CR_POST"
# stdio の UTF-8 固定を OS 非依存で検査する(reconfigure が消えると cp1252 強制下で
# UnicodeEncodeError → exit 1 = フック素通りになり、この 1 件が赤くなる)
expect_output 0 "詰まり" "stdio を cp1252 に強制しても deny 文言が出る" \
    env PYTHONIOENCODING=cp1252 "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_POST"

# 連続 deny: 専用 config で履歴を隔離し「ちょうど 3 回目」で知らせる境界を検査する。往復の上限は置かない(持ち主 2026-10-17)
# (共有 config だと先行テストの deny が積まれ、見る回数が先行テストの増減で揺れる)
CR_STREAK_CFG="$WORK/coldread-cfg-streak"; mkdir -p "$CR_STREAK_CFG"
env COLDREAD_TEST_SESSION=streak1 "$CR_CASE" "$CR_STREAK_CFG" "$CR_STUB_CARRY" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=streak1 "$CR_CASE" "$CR_STREAK_CFG" "$CR_STUB_CARRY" "$CR_POST" >/dev/null 2>&1
expect_output 0 "3 回続けて止まった" "同じ投稿が 3 回止まると、続けて止まったことと、この先の止まり方を知らせる(ちょうど 3 で発火)" \
    env COLDREAD_TEST_SESSION=streak1 "$CR_CASE" "$CR_STREAK_CFG" "$CR_STUB_CARRY" "$CR_POST"
# 続けて止まったことは別の記録(stuck.log)に残す。本文は写さない(宛先の種類と止めた理由の並びだけ)
expect_output 0 "STUCK_OK" "3 回続けて止まった投稿は stuck.log に宛先の種類と止めた理由の並びを残し、本文は写さない" \
    "$PY_BIN" -c 'import sys
t = open(sys.argv[1], encoding="utf-8").read()
ok = "kind=issue" in t and "why=finding,finding,finding" in t and "x" * 100 not in t
print("STUCK_OK" if ok else "BAD %r" % t[:300])' "$CR_STREAK_CFG/coldread-gate/stuck.log"
# 3 回の後も読み役を起動する(上限で読まずに止めない。CR_STUB_FAIL が起動したので「起動に失敗」になる)
expect_output 0 "coldreader(文脈ゼロの読み手)の起動に失敗" "3 回止まった後の書き直しも、読み役が読む(往復の上限は無い)" \
    env COLDREAD_TEST_SESSION=streak1 "$CR_CASE" "$CR_STREAK_CFG" "$CR_STUB_FAIL" "$CR_POST"
# 同じ書き手・同じ宛先でも、本文が似ていなければ別の投稿として数える
expect_output 0 "NO_STREAK_OTHER_BODY" "宛先が同じでも、本文の似ていない別の投稿は続けて止まった数に入れない" \
    sh -c '"$@" | grep -q "回続けて止まった" && echo BAD || echo NO_STREAK_OTHER_BODY' sh \
    env COLDREAD_TEST_SESSION=streak1 "$CR_CASE" "$CR_STREAK_CFG" "$CR_STUB_CARRY" "gh issue comment 1 --body '$(printf 'まったく別の話題の文章です。%.0s' $(seq 1 30)) $CR_PAD'"
# 連続 deny は書き手(session)ごと。log は profile 共有なので、並行セッションの deny を数えると
# 1 回目の書き手に「3 回連続」の案内が出て、他所の skip が自分の案内を消す(2026-09-07 に PR 1429 で実測:
# 7 回目の deny で案内が消えたのは、2 分前に別セッションが skip したため)
CR_SID_CFG="$WORK/coldread-cfg-sid"; mkdir -p "$CR_SID_CFG"
COLDREAD_TEST_SESSION=aaaa1111 "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_CARRY" "$CR_POST" >/dev/null 2>&1
COLDREAD_TEST_SESSION=aaaa1111 "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_CARRY" "$CR_POST" >/dev/null 2>&1
expect_output 0 "SID_ISOLATED" "他セッションの deny 2 回の後でも、自分の 1 回目に連続の案内は出ない" \
    cr_reason bbbb2222 no-streak \
    "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_BLOCK" "$CR_POST"
COLDREAD_TEST_SESSION=bbbb2222 "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_CLEAN" "$CR_POST" >/dev/null 2>&1
expect_output 0 "3 回続けて止まった" "他セッションの通過を挟んでも、自分の 3 回目で知らせる" \
    env COLDREAD_TEST_SESSION=aaaa1111 "$CR_CASE" "$CR_SID_CFG" "$CR_STUB_CARRY" "$CR_POST"
expect_output 0 "to=issue:cwd:1" "log の各行に session・版・投稿先が残る(どの版のどのセッションがどこへ出したかを grep で引く)" \
    grep -E $'deny\tfinding\t[0-9]+\tcold\tsid=aaaa1111\tv=[0-9.]+\tto=issue:cwd:1' "$CR_SID_CFG/coldread-gate/denies.log"
# 本文を読めずに止めた回(本文を取り出せない形など)は、書き直しの回に数えない。読めた回の連続も切らない。前は本文ファイルを
# 同じコマンドの中で書き換えて止まった回が「4 回続けて止まった」に数えられた(2026-10-17 の works-factory)
CR_UNREAD_CFG="$WORK/coldread-cfg-unread"; mkdir -p "$CR_UNREAD_CFG"
CR_UNREAD_POST="gh issue comment 1 --body \"\$BODY\" # $CR_PAD"
env COLDREAD_TEST_SESSION=unread1 "$CR_CASE" "$CR_UNREAD_CFG" "$CR_STUB_CARRY" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=unread1 "$CR_CASE" "$CR_UNREAD_CFG" "$CR_STUB_CARRY" "$CR_POST" >/dev/null 2>&1
expect_output 0 "SID_ISOLATED" "読めた回が 2 回続いた後の、本文を読めずに止めた回は、続けて止まった数に入れない" \
    cr_reason unread1 no-streak "$CR_CASE" "$CR_UNREAD_CFG" "$CR_STUB_FAIL" "$CR_UNREAD_POST"
# 読み手が動かない回(本文の指紋が有る)も、読めた回の連続に足さず、切りもしない。前は足されて「4 回」と出た
env COLDREAD_TEST_SESSION=unread1 "$CR_CASE" "$CR_UNREAD_CFG" "$CR_STUB_FAIL" "$CR_POST" >/dev/null 2>&1
expect_output 0 "【同じ投稿が 3 回続けて止まった" "本文を読めずに止めた回・読み手が動かない回を挟んでも、読めた回の連続は切れず、足されもしない" \
    env COLDREAD_TEST_SESSION=unread1 "$CR_CASE" "$CR_UNREAD_CFG" "$CR_STUB_CARRY" "$CR_POST"
env COLDREAD_TEST_SESSION=unread2 "$CR_CASE" "$CR_UNREAD_CFG" "$CR_STUB_FAIL" "$CR_UNREAD_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=unread2 "$CR_CASE" "$CR_UNREAD_CFG" "$CR_STUB_FAIL" "$CR_UNREAD_POST" >/dev/null 2>&1
expect_output 0 "3 回続けて、本文を読めずに止まった" "本文を読めずに止めた回だけが 3 回続けば、そのことを知らせる" \
    env COLDREAD_TEST_SESSION=unread2 "$CR_CASE" "$CR_UNREAD_CFG" "$CR_STUB_FAIL" "$CR_UNREAD_POST"
# 別の版の回は数えず、前の回の記録も引き継がない。前は 0.22.3 で止まった回が 0.23.0 の回に足され、新しい版の 2 回目で
# 「3 回続けて」と出た(2026-10-17 の works-factory)。前の版で止まった記録の版を書き換えて模す
CR_VER_CFG="$WORK/coldread-cfg-ver"; mkdir -p "$CR_VER_CFG"
env COLDREAD_TEST_SESSION=ver1 "$CR_CASE" "$CR_VER_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=ver1 "$CR_CASE" "$CR_VER_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
"$PY_BIN" -c 'import glob,json,re,sys
d = sys.argv[1]
p = d + "/denies.log"; t = open(p, encoding="utf-8").read(); open(p, "w", encoding="utf-8").write(re.sub(r"\tv=[^\t]+", "\tv=0.0.0", t))
for f in glob.glob(d + "/rounds/*.json"):
    r = json.load(open(f, encoding="utf-8")); r["v"] = "0.0.0"; json.dump(r, open(f, "w", encoding="utf-8"))' "$CR_VER_CFG/coldread-gate"
expect_output 0 "SID_ISOLATED" "前の版で止まった回は、今の版の続けて止まった数に入れない" \
    cr_reason ver1 no-streak "$CR_CASE" "$CR_VER_CFG" "$CR_STUB_BLOCK" "$CR_POST"
"$PY_BIN" -c 'import glob,json,sys
for f in glob.glob(sys.argv[1] + "/rounds/*.json"):
    r = json.load(open(f, encoding="utf-8")); r["v"] = "0.0.0"; json.dump(r, open(f, "w", encoding="utf-8"))' "$CR_VER_CFG/coldread-gate"
expect_output 0 "F3 が届いていない" "前の版の回の記録は引き継がず、1 回目として全体を読む" \
    env COLDREAD_TEST_SESSION=ver1 "$CR_CASE" "$CR_VER_CFG" "$(cr_stub_sees F3)" "$CR_POST"
# この検査が見るのは通じやすさだけ。中身の審査の問い(判断の材料・根拠・実例)は止める詰まりでなく疑問に回すよう、
# どの依頼文にも書く。前は 3 回目の読み手が「許していない範囲は前の点検と同じか」で止め、根拠を足すたびに足した文が
# また問われて、本文が 473 → 1,351 字に膨らんだ(2026-10-17 の works-factory の PR #677)
expect_output 0 "CLARITY_ONLY_OK" "依頼文は詰まりを語・指す先・筋の 3 つに絞り、中身の審査の問いを疑問に回す" \
    "$PY_BIN" -c "$CR_LOAD"$'\n''prompts = [g.COLD_PROMPT, g.reader_prompt("画面", "PR"), g.reader_prompt("画面")]
ok = all(all(w in p for w in ("(語)", "(指す先)", "(筋)", "判断の材料", "疑問")) for p in prompts) and "判断の材料" in g.FOLLOWUP_NOTE
print("CLARITY_ONLY_OK" if ok else "BAD")' "$ROOT/gates/hooks/coldread-gate.py"

# ---- coldread: 返信の読み手には画面(投稿先のスレッド)を渡す ----------------------------
# 文脈ゼロで読ませると、画面に有るもの(相手の名前・PR 番号・相手の印・相手の語)が全部詰まりに出て、
# 書き手が宛先本人に本人の名前を説明する返信を書く(2026-09-06 に PR 1583 で実測、39 回 deny)。
# gh は代役に差し替える(CI に gh も認証も無い)。引数列で応答を選び、知らない呼び方は失敗させる
CR_GHSTUB="$WORK/ghstub.sh"
cat > "$CR_GHSTUB" <<'SH'
#!/bin/sh
case "$*" in
  "api repos/o/r/pulls/comments/77") printf '%s' '{"id":77,"in_reply_to_id":null,"path":"docs/a.adoc","line":32,"diff_hunk":"@@ -0,0 +1,3 @@\n+= 題\n+本文の行","body":"[block] F3 の行が抜けています。F3 は fixture 3 の略です。","user":{"login":"reviewer_x"},"created_at":"2026-09-04T11:21:40Z","pull_request_url":"https://api.github.com/repos/o/r/pulls/9"}' ;;
  "api repos/o/r/pulls/comments/78") printf '%s' '{"id":78,"in_reply_to_id":77,"path":"docs/a.adoc","line":32,"diff_hunk":"@@ -0,0 +1,3 @@\n+= 題\n+本文の行","body":"先の返信です","user":{"login":"author_y"},"created_at":"2026-09-05T00:00:00Z","pull_request_url":"https://api.github.com/repos/o/r/pulls/9"}' ;;
  "api repos/o/r/pulls/9") printf '%s' '{"number":9,"title":"docs: F3 の説明を足す","body":"PR の説明"}' ;;
  "api repos/o/r/pulls/9/comments?per_page=100&page=1") printf '%s' '[{"id":77,"in_reply_to_id":null,"body":"[block] F3 の行が抜けています。F3 は fixture 3 の略です。","user":{"login":"reviewer_x"},"created_at":"2026-09-04T11:21:40Z"},{"id":78,"in_reply_to_id":77,"body":"先の返信です","user":{"login":"author_y"},"created_at":"2026-09-05T00:00:00Z"},{"id":90,"in_reply_to_id":null,"body":"別スレッドの指摘","user":{"login":"reviewer_x"},"created_at":"2026-09-04T11:22:00Z"}]' ;;
  "pr view 9 --json number,title,body,comments,url,state,isDraft,files") printf '%s' '{"number":9,"title":"docs: F3 の説明を足す","body":"PR の説明","url":"https://github.com/o/r/pull/9","state":"OPEN","isDraft":false,"files":[{"path":"docs/a.adoc"},{"path":"src/f3.py"}],"comments":[{"author":{"login":"reviewer_x"},"body":"レビューしました。F3 は fixture 3 の略です。","createdAt":"2026-09-04T11:19:54Z"}]}' ;;
  "api repos/o/r/issues/5") printf '%s' '{"number":5,"title":"issue 5 の題","body":"issue の本文"}' ;;
  "repo view o/r --json nameWithOwner,defaultBranchRef"|"repo view --json nameWithOwner,defaultBranchRef") printf '%s' '{"nameWithOwner":"o/r","defaultBranchRef":{"name":"main"}}' ;;
  "api repos/o/r/compare/main...feat") printf '%s' '{"files":[{"filename":"src/f3.py"},{"filename":"docs/a.adoc"}]}' ;;
  "api repos/o/r/issues/5/comments?per_page=100&page=1") printf '%s' '[{"id":501,"body":"issue への先のコメント。F3 は fixture 3 の略です。","user":{"login":"reviewer_x"},"created_at":"2026-09-04T00:00:00Z"}]' ;;
  *) echo "ghstub: 知らない呼び方: $*" >&2; exit 1 ;;
esac
SH
# sh で明示的に起動する(実行ビットと shebang の解釈に依らない——Windows の Git Bash でも同じ形で動く)
CR_GH="sh $CR_GHSTUB \"\$@\""
# REST の正式形(PR 番号入り)。2026-09-06 の実物の投稿 16 件がこの形で、PR 番号無しの形を
# 前提にした版はこれを取りこぼして文脈ゼロに落ちていた(自分の変更の実測で発見)
CR_REPLY="gh api repos/o/r/pulls/9/comments/77/replies -X POST --jq .html_url --input - <<'EOF'
{\"body\": \"$CR_BODY $CR_PAD\"}
EOF"
# 読み役の代役が stdin(依頼文+本文)を見て、画面が渡ったかどうかで返す文言を変える
CR_STUB_SEES_SCREEN='if grep -q "fixture 3 の略"; then echo CLEAN; else printf "詰まり: 画面(元の指摘)が読み手に渡っていない\n"; fi'
CR_STUB_SEES_PRIOR='if grep -q "先の返信です"; then echo CLEAN; else printf "詰まり: これまでの返信が渡っていない\n"; fi'
CR_STUB_OTHER_THREAD='if grep -q "別スレッドの指摘"; then printf "詰まり: 別スレッドの指摘まで渡された\n"; else echo CLEAN; fi'
CR_STUB_NO_SCREEN='if grep -q "画面に既に見えているもの"; then printf "詰まり: 新規作成なのに画面が渡された\n"; else echo CLEAN; fi'
CR_STUB_REDUNDANT='cat >/dev/null; printf "冗長: 冒頭で PR 番号とリポジトリ名を説明している\n"'
expect_output 0 "検査を通過" "review スレッドへの返信では元の指摘と PR の題が読み手に渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "$CR_REPLY" "$CR_GH"
expect_output 0 "検査を通過" "同じスレッドのこれまでの返信も渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_PRIOR" "$CR_REPLY" "$CR_GH"
expect_output 0 "検査を通過" "PR 番号無しの replies の形も同じスレッドと読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "gh api repos/o/r/pulls/comments/77/replies -f body='$CR_BODY $CR_PAD'" "$CR_GH"
# 読み役の代役は stdin を一度読んでから 2 条件を見る(grep を 2 回掛けると 2 回目の stdin は空)
CR_STUB_EDIT='b=$(cat); case "$b" in *"fixture 3 の略"*) case "$b" in *"先の返信です"*) printf "詰まり: 直す当のコメントが画面に残った\n";; *) echo CLEAN;; esac;; *) printf "詰まり: 元の指摘が画面に無い\n";; esac'
expect_output 0 "検査を通過" "編集(PATCH)では元の指摘は見え、直す当の返信は画面から除く" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_EDIT" "gh api repos/o/r/pulls/comments/78 -X PATCH -f body='$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "旗が先でも後ろの番号を位置引数として読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "gh pr comment --body '$CR_BODY $CR_PAD' 9" "$CR_GH"
expect_output 0 "検査を通過" "別スレッドの指摘は渡さない(画面に無いもの)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_OTHER_THREAD" "$CR_REPLY" "$CR_GH"
expect_output 0 "検査を通過" "gh pr comment は PR の題と会話が読み手に渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "gh api issues/N/comments は issue の題と会話が読み手に渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_SCREEN" "gh api repos/o/r/issues/5/comments -f body='$CR_BODY $CR_PAD'" "$CR_GH"
# 新しい PR・issue の読み手も本文だけを見ているのではない。GitHub が本文の周りに出す題・リポジトリ・ブランチ・
# 変更ファイル・本文が指す #番号 の題を渡す。渡さないと「Closes #660」まで「何の issue か分からない」で止まった
# (2026-10-17 に実測。works-factory の新しい PR 3 本の本文が、合わせて 7 回止まった)
CR_STUB_NEW_PR='b=$(cat); case "$b" in *"初めて開いた"*"新しい PR「F3 を足す」(o/r)"*"main ← feat"*"src/f3.py"*"#5「issue 5 の題」(?)"*"語の意味ではない"*"画面と本文を合わせても"*) echo CLEAN;; *) printf "詰まり: 新しい PR の画面(題・ブランチ・変更ファイル・参照番号の題)が渡っていない\n";; esac'
expect_output 0 "検査を通過" "新しい PR は題・リポジトリ・ブランチ・変更ファイル・本文が指す番号の題が読み手に渡る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NEW_PR" "gh pr create -R o/r --title 'F3 を足す' -H feat --body 'Closes #5
$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "新しい PR の -R・-B を省いても、gh が走る場所でリポジトリと既定のブランチを引いて渡す" \
    env COLDREAD_TEST_CWD="$ROOT" "$CR_CASE" "$CR_CFG" "$CR_STUB_NEW_PR" "gh pr create --title 'F3 を足す' --head=feat --body 'Closes #5
$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "新しい PR の旗は短縮形・つないだ形でも読み、本文の値が「-t」で始まっても題に読まない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NEW_PR" "gh pr create -R o/r -t 'F3 を足す' -Bmain -H feat --body '-t 偽の題 Closes #5
$CR_BODY $CR_PAD'" "$CR_GH"
# 前の cd で gh の走る場所が変わるなら、フックの場所でリポジトリを引かない(別のブランチの中身を画面として渡さない)
CR_STUB_NEW_ELSEWHERE='b=$(cat); case "$b" in *"新しい PR「F3 を足す」(このリポジトリ)"*) echo CLEAN;; *) printf "詰まり: cd した先でなくフックの場所のリポジトリを画面に出した\n";; esac'
expect_output 0 "検査を通過" "cd で場所を変えた gh pr create は、フックの場所のリポジトリとブランチを画面に出さない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NEW_ELSEWHERE" "cd sub && gh pr create --title 'F3 を足す' --body '$CR_BODY $CR_PAD'" "$CR_GH"
CR_STUB_NEW_ISSUE='b=$(cat); case "$b" in *"この issue を初めて開いた"*"新しい issue「t」(o/r)"*"#5「issue 5 の題」"*) case "$b" in *"取り込む先 ← 元のブランチ"*|*"PR"*) printf "詰まり: issue に PR のブランチか呼び名が載った\n";; *) echo CLEAN;; esac;; *) printf "詰まり: 新しい issue の画面が渡っていない\n";; esac'
expect_output 0 "検査を通過" "新しい issue は題・リポジトリ・本文が指す番号の題が読み手に渡る(ブランチは載せない)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NEW_ISSUE" "gh issue create -R o/r --title t --body '#5 の続き $CR_BODY $CR_PAD'" "$CR_GH"
# gh が使えなくても、コマンドに書いた題は渡し、取れなかった物は書き手に伝える(文脈ゼロに戻さない)
CR_STUB_NEW_TITLE_ONLY='b=$(cat); case "$b" in *"新しい PR「F3 を足す」(o/r)"*) echo CLEAN;; *) printf "詰まり: コマンドに書いた題が渡っていない\n";; esac'
expect_output 0 "変更ファイルの一覧・本文が参照している番号の題 を gh で取れなかった" "新しい PR の画面の一部を取れないときは、有る分で読ませ、取れなかった物を伝える" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NEW_TITLE_ONLY" "gh pr create -R o/r --title 'F3 を足す' -H feat --body 'Closes #5
$CR_BODY $CR_PAD'" "exit 1"
expect_output 0 "検査を通過" "題もリポジトリも分からない新しい PR は文脈ゼロで読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NO_SCREEN" "gh pr create --fill --body '$CR_BODY $CR_PAD'" "exit 1"
expect_output 0 "検査を通過" "gist の新規作成も文脈ゼロのまま" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NO_SCREEN" "$CR_GIST" "$CR_GH"
# 画面を取れないときは止めずに文脈ゼロで読み、書き手には「画面に有るものへの詰まりは無視してよい」と伝える
expect_output 0 "取れなかった" "画面を取れないときは文脈ゼロで読み、その旨を書き手に伝える(通過側)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_CLEAN" "$CR_REPLY" "exit 1"
expect_output 0 "取れなかった" "画面を取れないときの deny にもその旨が載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_REPLY" "exit 1"
# 画面は参加者が実際に見ているものまで: 状態・変更ファイル・本文が参照する #番号 の題(2026-09-07 の
# PR 1429 で、用語集 19 語を生んだ最初の詰まりは「#1231 #1581 #1283 が何か」だった)
CR_STUB_SEES_STATE='if grep -q "、open)"; then echo CLEAN; else printf "詰まり: PR の状態が画面に無い\n"; fi'
CR_STUB_SEES_FILES='if grep -q "src/f3.py"; then echo CLEAN; else printf "詰まり: 変更ファイルの一覧が画面に無い\n"; fi'
CR_STUB_SEES_REF='if grep -q "issue 5 の題"; then echo CLEAN; else printf "詰まり: 本文が参照する #5 の題が画面に無い\n"; fi'
expect_output 0 "検査を通過" "PR の状態(open/merged/draft)が画面に載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_STATE" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "PR の変更ファイルの一覧が画面に載る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILES" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "検査を通過" "本文が参照する #番号 の題を引いて画面に載せる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_REF" "gh pr comment 9 --body '$CR_BODY #5 を閉じる $CR_PAD'" "$CR_GH"
# 画面が既知にするのは「何を指しているか」で、「どう書くか」ではない。画面を語彙の辞書にすると、
# スレッドの癖のある書き方に読み手が引っ張られ、本文がその癖を写す向きに働く
CR_STUB_VOCAB='if grep -q "なぞり: 」"; then echo CLEAN; else printf "詰まり: 画面を語彙の辞書にしない規則(なぞりのフィールド)が依頼文に無い\n"; fi'
expect_output 0 "検査を通過" "画面モードの依頼文は、画面を語彙の辞書にしない(相手の語を地の文で使えば「なぞり」)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_VOCAB" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
# なぞりは詰まりと同じく止める。詰まりの条件文に埋めた形は実物の読み手に 1 件も拾われなかった(2026-09-07 に実測)
CR_STUB_TRACED='cat >/dev/null; printf "なぞり: 「ニアバイして」は reviewer_x の語をそのまま地の文に使っている\n"'
expect_output 0 "自分の言葉に直せば通る" "相手の言い回しを地の文に写した箇所(なぞり)は投稿を止め、直し方は説明を足すことではないと言う" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_TRACED" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
CR_STUB_AUTHFAIL='cat >/dev/null; printf "Failed to authenticate: OAuth session expired and could not be refreshed\n"'
expect_output 0 "報告の形" "認証切れの 1 行(終了コード 0・ラベル無し)は allow にせず止める(実測 2026-09-15 の形)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_AUTHFAIL" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
CR_STUB_CLEAN_ONLY='cat >/dev/null; printf "CLEAN\n"'
expect_output 0 "検査を通過" "報告が CLEAN の 1 語だけでも通る(チェックは正しい形まで巻き込まない)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_CLEAN_ONLY" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
CR_STUB_TRACED_NONE='cat >/dev/null; printf "なぞり: なし\n"'
expect_output 0 "検査を通過" "「なぞり: なし」は 0 件として通る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_TRACED_NONE" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "相手の語で書かない" "返信の deny の直し方に「相手の語は指してよいが、相手の語で書かない」が在る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh pr comment 9 --body '$CR_BODY $CR_PAD'" "$CR_GH"
# 予算を超えたら古いコメントから落とす。旧版は組んだ後に末尾を切り、本文を長く見せるほど最新の返信が落ちた
expect_output 0 "ASSEMBLE_OK" "画面が予算を超えたら古いコメントから落とし、最後の 1 件(答える相手)と本文は残る" \
    "$PY_BIN" -c "$CR_LOAD"$'\n''blocks=[["[c%d]"%i, "x"*g.SCREEN_BODY_MAX] for i in range(20)]
out=g.assemble(["title","[本文]"], "b"*3000, blocks, ["tail"])
ok = len(out)<=g.SCREEN_MAX and "[c19]" in out and "[c0]" not in out and "省略" in out and "tail" in out and "b"*3000 in out
print("ASSEMBLE_OK" if ok else "BAD len=%d" % len(out))' "$ROOT/gates/hooks/coldread-gate.py"
# 古い版で走り続けるセッションに、新しい版が cache に在ることを伝える(フックの版はセッション開始時に固定。
# 2026-09-07 に実測: 0.9.0 導入前に開始したセッションが 16 時間 0.8.0 のまま検査していた)
CR_VCACHE="$WORK/vcache/gates"
mkdir -p "$CR_VCACHE/0.1.0/hooks" "$CR_VCACHE/0.1.0/.claude-plugin" "$CR_VCACHE/0.2.0/hooks" "$CR_VCACHE/0.10.0/hooks"
# 本体と、その隣の共有の本文(認証の段)を置く。配られるのは hooks/ ごとなので、ここも同じ形にする
cp "$ROOT/gates/hooks/coldread-gate.py" "$ROOT/gates/hooks/claude_auth.py" "$CR_VCACHE/0.1.0/hooks/"
echo '{"name":"gates","version":"0.1.0"}' > "$CR_VCACHE/0.1.0/.claude-plugin/plugin.json"
: > "$CR_VCACHE/0.2.0/hooks/coldread-gate.py"
expect_output 0 "0.2.0 が在る" "cache に新しい版が在れば検査結果にその旨が載る(本体の無い 0.10.0 は入りかけなので拾わない)" \
    env COLDREAD_GATE="$CR_VCACHE/0.1.0/hooks/coldread-gate.py" "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_POST"
expect_output 0 "NO_NOTE" "開発 checkout(兄弟が版名でない)では版の注記を出さない" \
    "$PY_BIN" -c "$CR_LOAD"$'\n''print("NO_NOTE" if g.VERSION_NOTE == "" else "BAD: " + g.VERSION_NOTE)' "$ROOT/gates/hooks/coldread-gate.py"
# 冗長(画面に有るものの説明)は止めない申し送り。詰まりと同じフィールドに混ぜると「直せ」と読まれる
expect_output 0 "削ってよい" "冗長は止めずに申し送る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_REDUNDANT" "$CR_REPLY" "$CR_GH"
# 直し方は読み方で変える。画面モードで「同型を掃討」と言うと、画面に有るものの説明を足す向きに働く
expect_output 0 "足すより削る" "スレッドへの返信の deny は「足すより削る」と案内する" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "$CR_REPLY" "$CR_GH"
expect_output 0 "掃討" "新規作成の deny は従来の「同型を掃討」の案内のまま" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue create --title t --body '$CR_BODY $CR_PAD'" "$CR_GH"
expect_output 0 "それらを本文で説明し直さなくてよい" "新しい PR・issue の deny は、画面に出る物を本文で説明し直さなくてよいと添える" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue create -R o/r --title t --body '$CR_BODY $CR_PAD'" "$CR_GH"
# 「詰まり: なし」は 0 件であって 1 件ではない。依頼文で省けと言っても読み手は書く(2026-09-06 に実測:
# 画面モードの読み手が書き、837 字の返信が止まった)。落とさないと無いフィールドが投稿を止める
CR_STUB_NONE='cat >/dev/null; printf "詰まり: なし\n補完: 無し。\n疑問: 期限はいつか\n"'
expect_output 0 "検査を通過" "「詰まり: なし」は詰まりに数えない(疑問だけ残って通る)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NONE" "$CR_POST"
CR_STUB_NONE_ONLY='cat >/dev/null; printf "詰まり: なし\n"'
expect_output 0 "検査を通過" "「詰まり: なし」だけの出力は CLEAN と同じに通る" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_NONE_ONLY" "$CR_POST"
# 読み役は利用者の CLAUDE.md を読まない(--setting-sources を空で起動)。2026-09-06 に実測: 無しだと
# 利用者の CLAUDE.md の見出しをそのまま引用し、有りだと NONE。CI に claude は無いので起動引数で縛る。
# **本文が argv に戻らないことも形で見る**——Windows のコマンドラインは 32,767 字が上限で、超えると
# 起動ごと落ちて投稿が全部止まる。reader_argv が受け取るのは起動する相手だけ(本文は stdin)。
# -c に渡す script は ASCII だけにする(日本語の argv は windows で届かなかった面が未確定のまま)
expect_output 0 "READER_ARGV_OK" "読み役の起動引数は遮断の旗を持ち、本文は argv に載らない" \
    "$PY_BIN" -c "$CR_LOAD"$'\n''import inspect
a = g.reader_argv("claude")
flags = all(f in a and a[a.index(f) + 1] == "" for f in ("--setting-sources", "--tools"))
body_free = list(inspect.signature(g.reader_argv).parameters) == ["claude_bin", "model", "effort"]   # 本文を受ける引数を持たない（モデルと effort は手元の文書の読み手が替える）
print("READER_ARGV_OK" if flags and body_free else "BAD %r body_free=%r" % (a, body_free))' "$ROOT/gates/hooks/coldread-gate.py"
# 連続 deny の案内は先頭に置き、本文の膨れ方を数字で示す(末尾の案内は 36 回無視された)
CR_GROW_CFG="$WORK/coldread-cfg-grow"; mkdir -p "$CR_GROW_CFG"
env COLDREAD_TEST_SESSION=grow1 "$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_CARRY2" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=grow1 "$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_CARRY2" "$CR_POST" >/dev/null 2>&1
CR_POST_LONGER="gh issue comment 1 --body-file - <<'EOF'
$CR_BODY
$CR_BODY
$CR_PAD
EOF"
expect_output 0 " → " "3 回続けて止まったとき、本文が増えていれば 1 回ごとの字数の数列を知らせに載せる" \
    env COLDREAD_TEST_SESSION=grow1 "$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_CARRY2" "$CR_POST_LONGER"
expect_output 0 "前の回から残った詰まり・なぞりだけが投稿を止め、止める数は直すたびに減る" "続けて止まった知らせは、この先は前の回から残った物だけで止まると言う" \
    env COLDREAD_TEST_SESSION=grow1 "$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_CARRY2" "$CR_POST_LONGER"
expect_output 0 "HEAD_OK" "続けて止まった知らせは deny 理由の先頭に在る" \
    cr_reason grow1 streak-head \
    env COLDREAD_TEST_SESSION=grow1 "$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_CARRY2" "$CR_POST_LONGER"
# 持ち主に通させる口は無い(持ち主 2026-10-17「人からパスを売ってもらう運用はやめて」)。知らせに持ち主の許しの番号を載せない
expect_output 0 "NO_OWNER_PASS" "続けて止まった知らせは、持ち主に許しを打たせる道を案内しない" \
    sh -c '"$@" | grep -q "coldread-pass" && echo BAD || echo NO_OWNER_PASS' sh \
    env COLDREAD_TEST_SESSION=grow1 "$CR_CASE" "$CR_GROW_CFG" "$CR_STUB_CARRY2" "$CR_POST_LONGER"

# 書き直しの 2 回目からは、前の回の指摘と直した差分を読み手に渡す。毎回まっさらな読み手は前の回を知らず、逆の注文を出し、
# 前の読み手が言わなかった端の所を拾い続けた(2026-10-17 の works-factory で 5 本が 3 回止まった)
CR_ROUND_CFG="$WORK/coldread-cfg-round"; mkdir -p "$CR_ROUND_CFG"
CR_POST_FIXED="gh issue comment 1 --body-file - <<'EOF'
$CR_BODY
ZZFIXED
$CR_PAD
EOF"
env COLDREAD_TEST_SESSION=round1 "$CR_CASE" "$CR_ROUND_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "F3 が届いた" "2 回目の読み手には、前の回の指摘が届く" \
    env COLDREAD_TEST_SESSION=round1 "$CR_CASE" "$CR_ROUND_CFG" "$(cr_stub_sees F3)" "$CR_POST_FIXED"
env COLDREAD_TEST_SESSION=round2 "$CR_CASE" "$CR_ROUND_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "+ZZFIXED が届いた" "2 回目の読み手には、書き手が足した行が差分として届く" \
    env COLDREAD_TEST_SESSION=round2 "$CR_CASE" "$CR_ROUND_CFG" "$(cr_stub_sees +ZZFIXED)" "$CR_POST_FIXED"
expect_output 0 "2 回目の検査" "2 回目の止めた理由は、前の回の指摘と直しだけを見た回だと言う" \
    env COLDREAD_TEST_SESSION=round2b sh -c '"$@" >/dev/null 2>&1; "$@"' sh "$CR_CASE" "$CR_ROUND_CFG" "$CR_STUB_BLOCK" "$CR_POST"
# 通ったら前の回の記録は消え、次の投稿はまた 1 回目として全体を読む(前の回の指摘を渡さない)
env COLDREAD_TEST_SESSION=round3 "$CR_CASE" "$CR_ROUND_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=round3 "$CR_CASE" "$CR_ROUND_CFG" "$CR_STUB_CLEAN" "$CR_POST" >/dev/null 2>&1
expect_output 0 "F3 が届いていない" "通った後の投稿は 1 回目として読み、前の回の指摘を渡さない" \
    env COLDREAD_TEST_SESSION=round3 "$CR_CASE" "$CR_ROUND_CFG" "$(cr_stub_sees F3)" "$CR_POST"
# 別の書き手(session)の前の回は渡さない
expect_output 0 "F3 が届いていない" "前の回の指摘は書き手(session)ごとで、ほかの会話の分を渡さない" \
    env COLDREAD_TEST_SESSION=round4 "$CR_CASE" "$CR_ROUND_CFG" "$(cr_stub_sees F3)" "$CR_POST"

# 同じ宛先でも、半分を超えて違う本文は前の回を引き継がない(引き継ぐと書き換えていない所で止めなくなり、別の投稿の検査が甘くなる)
env COLDREAD_TEST_SESSION=round5 "$CR_CASE" "$CR_ROUND_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "F3 が届いていない" "同じ宛先への別の本文には、前の回の指摘を渡さない" \
    env COLDREAD_TEST_SESSION=round5 "$CR_CASE" "$CR_ROUND_CFG" "$(cr_stub_sees F3)" "gh issue comment 1 --body '$(printf 'まったく別の話題の文章です。%.0s' $(seq 1 30)) $CR_PAD'"
# 前の回の記録が壊れていてもゲートは落ちず(落ちると無検査で通る)、1 回目として読む
env COLDREAD_TEST_SESSION=round6 "$CR_CASE" "$CR_ROUND_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
for f in "$CR_ROUND_CFG"/coldread-gate/rounds/*.json; do printf '[]' > "$f"; done
expect_output 0 "F3 が届いていない" "壊れた前の回の記録は無いものとして、1 回目として読む" \
    env COLDREAD_TEST_SESSION=round6 "$CR_CASE" "$CR_ROUND_CFG" "$(cr_stub_sees F3)" "$CR_POST"

# 3 回目からは、前の回から残った詰まり・なぞりだけで止める。読み手が印((前の回))を付けずに止めるフィールドに書いた物は疑問に移す
# (ゲートが自分で収まる形。持ち主 2026-10-17「ある程度出たと判断したら進む形にしよう」)
CR_CARRY_CFG="$WORK/coldread-cfg-carry"; mkdir -p "$CR_CARRY_CFG"
CR_STUB_NEW_ONLY='cat >/dev/null; printf "詰まり: (語) 直しで足した ZZNEW が分からない\n"'
CR_STUB_CARRIED='cat >/dev/null; printf "詰まり: (前の回) (語) F3 が何かまだ解けていない\n"'
env COLDREAD_TEST_SESSION=carry1 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "詰まり: (語) 直しで足した ZZNEW" "2 回目は、直しが新しく生んだ詰まりでも止める" \
    env COLDREAD_TEST_SESSION=carry1 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_NEW_ONLY" "$CR_POST"
expect_output 0 "まだ解けていないものだけ が届いた" "3 回目の読み手には、前の回から残った物だけを止めよと頼む" \
    env COLDREAD_TEST_SESSION=carry1 "$CR_CASE" "$CR_CARRY_CFG" "$(cr_stub_sees 'まだ解けていないものだけ')" "$CR_POST"
env COLDREAD_TEST_SESSION=carry3 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=carry3 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "検査を通過" "3 回目からは、前の回の印の無い詰まりでは止めない" \
    env COLDREAD_TEST_SESSION=carry3 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_NEW_ONLY" "$CR_POST"
env COLDREAD_TEST_SESSION=carry3b "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=carry3b "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "疑問: (止めない) 詰まり: (語) 直しで足した ZZNEW" "印の無い詰まりは、疑問として書き手に返す" \
    env COLDREAD_TEST_SESSION=carry3b "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_NEW_ONLY" "$CR_POST"
# 印はラベルの直後で見る。新しい指摘が地の文で「前の回」と書いても止める側に残さない。印の後ろが「なし」なら落とす
CR_STUB_LOOSE='cat >/dev/null; printf "詰まり: (語) 前の回の直しで足した ZZLOOSE が分からない\n詰まり: (前の回) なし\n"'
env COLDREAD_TEST_SESSION=carry4 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=carry4 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "検査を通過" "印が地の文に在るだけの詰まりと、印の後ろが「なし」の行では止めない" \
    env COLDREAD_TEST_SESSION=carry4 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_LOOSE" "$CR_POST"
# 止める数は、本文を直すたびに前の回の止めた数より減る。前の回が 1 件なら、直した本文の 3 回目は印付きでも止めない
env COLDREAD_TEST_SESSION=carry5 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=carry5 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "検査を通過" "直した本文では、止める数が前の回の止めた数より減る(1 件なら 0 になって通る)" \
    env COLDREAD_TEST_SESSION=carry5 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_CARRIED" "$CR_POST_FIXED"
env COLDREAD_TEST_SESSION=carry2 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
env COLDREAD_TEST_SESSION=carry2 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_BLOCK" "$CR_POST" >/dev/null 2>&1
expect_output 0 "投稿を止めている詰まり" "3 回目からも、前の回から残った詰まりでは止める" \
    env COLDREAD_TEST_SESSION=carry2 "$CR_CASE" "$CR_CARRY_CFG" "$CR_STUB_CARRIED" "$CR_POST"
# 持ち主の許しの口は外した。入力欄で撃たれるフックは無い
expect_output 0 "NO_PASS_MODE" "持ち主の許しの口はゲートにもフックの設定にも無い" \
    "$PY_BIN" -c "$CR_LOAD"$'\n''import os
h = open(os.path.join(os.path.dirname(sys.argv[1]), "hooks.json"), encoding="utf-8").read()
print("NO_PASS_MODE" if not hasattr(g, "owner_pass_main") and "UserPromptSubmit" not in h else "BAD")' "$ROOT/gates/hooks/coldread-gate.py"

# ---- coldread: 取りこぼしの穴(2026-10-16 に記録と会話の記録を突き合わせて見つけた) ----------------
# 方針は「出来る限りフックで止める。本文が読めない形は止める(fail-closed)。読める形は止めずに読む」。
# 読み役の代役は、届いた依頼文+本文に印(ASCII)が在るかで返す文言を変える——deny になった事実でなく、
# 本文が実際に読み役へ届いたことまで見るため
CR_STUB_SEES_FILE=$(cr_stub_sees MARK_FILE)
CR_FDIR="$WORK/cr-files"; mkdir -p "$CR_FDIR"
printf 'MARK_FILE %s %s\n' "$CR_BODY" "$CR_PAD" > "$CR_FDIR/body.md"
printf '{"body": "MARK_FILE %s %s"}\n' "$CR_BODY" "$CR_PAD" > "$CR_FDIR/payload.json"
# 1. 400 字未満のコマンドを解析の前に通していた。本文ファイル・変数を運ぶ短いコマンドが読まれずに出ていた
expect_output 0 "MARK_FILE が届いた" "400 字未満のコマンドでも、--body-file の実ファイルを読んで読み役に渡す" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "gh issue comment 1 --body-file $CR_FDIR/body.md"
expect_output 0 "取り出せない" "400 字未満のコマンドでも、変数で渡す本文は止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body \"\$MSG\""
# 短いコマンドも解析するので、投稿しない短い gh(--version・--help)を「サブコマンドを特定できない」で止めない
expect_output 0 "ALLOW_EMPTY" "gh --version は止めない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh --version"
expect_output 0 "ALLOW_EMPTY" "--help の付いた gh は本文旗が在っても投稿しないので止めない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh pr --help && gh issue comment 1 --help --body-file /no/such.md"
# 2. review の JSON で .body が在ると comments[].body を見ていなかった
CR_STUB_SEES_C=$(cr_stub_sees MARK_C)
expect_output 0 "MARK_C が届いた" "review の JSON は .body が空でも comments[].body を読ませる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_C" "gh api repos/o/r/pulls/9/reviews --input - <<'EOF'
{\"body\": \"\", \"event\": \"COMMENT\", \"comments\": [{\"path\": \"a.py\", \"line\": 1, \"body\": \"MARK_C $CR_BODY $CR_PAD\"}]}
EOF"
expect_output 0 "MARK_C が届いた" "review の JSON は長い .body と並ぶ comments[].body も読ませる(最長の 1 本で落とさない)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_C" "gh api repos/o/r/pulls/9/reviews --input - <<'EOF'
{\"body\": \"$CR_BODY $CR_PAD $CR_PAD\", \"event\": \"COMMENT\", \"comments\": [{\"path\": \"a.py\", \"line\": 1, \"body\": \"MARK_C は短い\"}]}
EOF"
# 3. 本文がファイルに在る形は止めて書き直させていた(往復 124 回)。フックが自分で読む
expect_output 0 "MARK_FILE が届いた" "gh api -F body=@<絶対パス> はファイルを読んで読み役に渡す" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "gh api repos/o/r/issues/1/comments -F body=@$CR_FDIR/body.md"
expect_output 0 "MARK_FILE が届いた" "gh api --input <絶対パス> は JSON を読んで .body を読み役に渡す" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "gh api repos/o/r/issues/1/comments --input $CR_FDIR/payload.json"
expect_output 0 "MARK_FILE が届いた" "gh pr create -F <絶対パス>(--body-file の短縮形)も読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "gh pr create -t T -F $CR_FDIR/body.md"
expect_output 0 "MARK_FILE が届いた" "相対パスはフックの入力の cwd で解いて読む" \
    env COLDREAD_TEST_CWD="$CR_FDIR" "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "gh issue comment 1 --body-file body.md"
expect_output 0 "取り出せない" "cwd の無い相対パスは決まらないので止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file body.md"
expect_output 0 "MARK_FILE が届いた" "cd <絶対パス> && の後の相対パスは、cd の先で解いて読む" \
    env COLDREAD_TEST_CWD=/ "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "cd $CR_FDIR && gh issue comment 1 --body-file body.md"
expect_output 0 "取り出せない" "cd の後 ; で続く相対パスは、cd の成否で指す先が変わるので止める" \
    env COLDREAD_TEST_CWD=/ "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cd $CR_FDIR; gh issue comment 1 --body-file body.md"
expect_output 0 "MARK_FILE が届いた" "同じコマンドの中で絶対パスを代入した変数のパスは、静的に解いて読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "S=$CR_FDIR/body.md; gh issue comment 1 --body-file \"\$S\""
expect_output 0 "MARK_FILE が届いた" "代入と gh の間に \$( … ) が在っても、変数のパスを解いて読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "S=$CR_FDIR; N=\$(wc -c < \"\$S/body.md\"); gh issue comment 1 --body-file \"\$S/body.md\""
expect_output 0 "取り出せない" "サブシェルの中の代入は gh に届かないので止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "( S=$CR_FDIR ); gh issue comment 1 --body-file \"\$S/body.md\""
expect_output 0 "取り出せない" "パイプの中の代入は gh に届かないので止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "S=$CR_FDIR | true; gh issue comment 1 --body-file \"\$S/body.md\""
expect_output 0 "MARK_FILE が届いた" "ホームの下を ~/ で書いたパスは HOME で解いて読む" \
    env HOME="$CR_FDIR" "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "gh issue comment 1 --body-file ~/body.md"
expect_output 0 "取り出せない" "解けない変数のパスは止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file \"\$NOPE\""
printf 'MARK_OLD %s %s\n' "$CR_BODY" "$CR_PAD" > "$CR_FDIR/w.md"
CR_STUB_SEES_HD=$(cr_stub_sees MARK_HD)
expect_output 0 "MARK_HD が届いた" "同じコマンドで cat > f <<EOF と書いてから渡す本文は、ディスクの古い中身でなくヒアドキュメントを読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_HD" "cat > $CR_FDIR/w.md <<'EOF'
MARK_HD $CR_BODY $CR_PAD
EOF
gh issue comment 1 --body-file $CR_FDIR/w.md"
expect_output 0 "取り出せない" "同じコマンドの中で別のコマンドが本文ファイルを書き換えうるなら止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "cp $CR_FDIR/w.md $CR_FDIR/body.md && gh issue comment 1 --body-file $CR_FDIR/body.md"
expect_output 0 "MARK_FILE が届いた" "gh の後に走る後片付け(&& rm f)は書き手に数えない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_FILE" "gh issue comment 1 --body-file $CR_FDIR/body.md && rm -f $CR_FDIR/no-such-copy/body.md"
printf '\377\376 not utf-8 %s\n' "$CR_PAD" > "$CR_FDIR/latin.md"
expect_output 0 "UTF-8 でない" "UTF-8 でない本文ファイルは止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file $CR_FDIR/latin.md"
expect_output 0 "上限より大きい" "上限より大きい本文ファイルは止める" \
    env COLDREAD_MAX_LEN=300 "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file $CR_FDIR/body.md"
expect_output 0 "読めない" "無い本文ファイルは止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file $CR_FDIR/no-such.md"
# FIFO は書き手を待ってフックを止める(止まるとフックの timeout で無検査で通る)。O_NONBLOCK で開き、fstat で通常のファイルかを見る。
# 走らせるのはフックの Python から FIFO に見えるときだけ——Windows の Git Bash の mkfifo が作る物は、ネイティブの Python からは
# FIFO に見えない(run 38840103784 で実測。読むと UTF-8 でない中身が返った)。gh もネイティブなので待たされない
if mkfifo "$CR_FDIR/fifo.md" 2>/dev/null \
    && "$PY_BIN" -c 'import os, stat, sys; sys.exit(not stat.S_ISFIFO(os.stat(sys.argv[1]).st_mode))' "$CR_FDIR/fifo.md"; then
    expect_output 0 "通常のファイルでない" "FIFO の本文ファイルは待たずに止める" \
        "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file $CR_FDIR/fifo.md"
else
    cr_fifo_skip="  ok   FIFO の本文ファイルは待たずに止める # SKIP fifo: mkfifo が無いか、フックの Python から FIFO に見えない"
    echo "$cr_fifo_skip"; note_skips "$cr_fifo_skip"; ran=$((ran + 1))
fi
# Windows の Bash のツールは Git Bash なので、コマンドの中のパスは /c/…・/tmp/… の形で来る。ネイティブの Python のフックは
# cygpath で直して読む(上の本文ファイルの検査が Windows でこの道を通る)。cygpath が無いときの倒れ方は、ここで os.name を
# 差し替えてどの OS でも見る: ドライブの形だけを直し、/tmp のような割り当ては推し量らずに止める側(None)へ
expect_output 0 "NATIVE_PATH_OK" "Windows では Git Bash の形のパスを cygpath で直し、無ければドライブの形だけを直して、ほかは止める側に倒す" \
    "$PY_BIN" -c "$CR_LOAD"$'\n''import os, shutil
same = all(g.native_path(p) == p for p in ("/tmp/x.md", "C:/x.md", "rel/x.md"))
real, os.name = os.name, "nt"
try:
    g._native_cache.clear()
    drive = g.native_path("/c/Users/a b/x.md") == "C:\\Users\\a b\\x.md" and g.native_path("/d") == "D:\\"
    kept = all(g.native_path(p) == p for p in ("C:/x.md", "rel/x.md", "//srv/share/x.md"))
    tmp = g.native_path("/tmp/x.md")
finally:
    os.name = real
tmp_ok = tmp is None if shutil.which("cygpath") is None else bool(tmp) and not tmp.startswith("/")
print("NATIVE_PATH_OK" if (same or real == "nt") and drive and kept and tmp_ok else "BAD same=%r drive=%r kept=%r tmp=%r" % (same, drive, kept, tmp))' "$ROOT/gates/hooks/coldread-gate.py"
# 別の目のレビュー(2026-10-16)が見つけた、読んだ中身と gh が読む中身がずれる形。どれも「読めない」に倒す
mkdir -p "$CR_FDIR/b"
printf 'MARK_OTHER %s %s\n' "$CR_BODY" "$CR_PAD" > "$CR_FDIR/b/body.md"
expect_output 0 "取り出せない" "if の条件の cd の後の相対パスは止める(cd が先頭の語でなくても見る)" \
    env COLDREAD_TEST_CWD="$CR_FDIR" "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "if cd $CR_FDIR/b; then gh issue comment 1 --body-file body.md; fi"
expect_output 0 "取り出せない" "builtin cd の後の相対パスも止める" \
    env COLDREAD_TEST_CWD="$CR_FDIR" "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "builtin cd $CR_FDIR/b && gh issue comment 1 --body-file body.md"
expect_output 0 "取り出せない" "|| の先の cd(走るかどうかが決まらない)の後の相対パスは止める" \
    env COLDREAD_TEST_CWD="$CR_FDIR" "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "true || cd $CR_FDIR/b && gh issue comment 1 --body-file body.md"
expect_output 0 "取り出せない" "env -C<dir> の 1 語の形の後の相対パスも止める" \
    env COLDREAD_TEST_CWD="$CR_FDIR" "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "env -C$CR_FDIR/b gh issue comment 1 --body-file body.md"
expect_output 0 "取り出せない" "走るかどうかが決まらない cat > f <<EOF の書き手は、ヒアドキュメントを本文と見なさずに止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "[ -e $CR_FDIR/body.md ] || cat > $CR_FDIR/body.md <<'EOF'
$CR_BODY $CR_PAD
EOF
gh issue comment 1 --body-file $CR_FDIR/body.md"
expect_output 0 "取り出せない" "if の中の cat > f <<EOF は走るとは限らないので、ヒアドキュメントを本文と見なさずに止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "if false; then cat > $CR_FDIR/body.md <<'EOF'
$CR_BODY $CR_PAD
EOF
fi; gh issue comment 1 --body-file $CR_FDIR/body.md"
expect_output 0 "MARK_HD が届いた" "cat > f <<EOF の後の \$(gh …) の中の gh も、ヒアドキュメントを本文として読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_HD" "cat > $CR_FDIR/w.md <<'EOF'
MARK_HD $CR_BODY $CR_PAD
EOF
URL=\$(gh pr create -t t --body-file $CR_FDIR/w.md)"
expect_output 0 "取り出せない" "区切りを引用しないヒアドキュメントの中の \$ や \` は展開されるので止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "gh issue comment 1 --body-file - <<EOF
$CR_BODY \$(cat $CR_FDIR/b/body.md) $CR_PAD
EOF"
expect_output 0 "取り出せない" "+= で書き足す変数の本文は、最初の代入だけで読まずに止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "B='$CR_BODY $CR_PAD'; B+=' more'; gh issue comment 1 --body \"\$B\""
expect_output 0 "取り出せない" "read で入れ直す変数の本文は止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "B='$CR_BODY $CR_PAD'; read -r B < $CR_FDIR/b/body.md; gh issue comment 1 --body \"\$B\""
expect_output 0 "取り出せない" "|| の先の代入は効くかどうかが決まらないので止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "true || B='$CR_BODY $CR_PAD'; gh issue comment 1 --body \"\$B\""
expect_output 0 "取り出せない" "本文の一部に変数が混じる二重引用の本文(\"See: \$B\")は止める" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "B=\"\$(cat $CR_FDIR/b/body.md)\"; gh issue comment 1 --body \"See: \$B\""
expect_output 0 "詰まり" "単一引用の中の \$ は字のままなので、本文として読ませる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body '\$HOME は展開されない。$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "if・while・until の直後の gh もゲートに掛かる" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "if gh issue comment 1 --body '$CR_BODY $CR_PAD'; then echo ok; fi"
CR_STUB_SEES_TAIL=$(cr_stub_sees MARK_TAIL)
expect_output 0 "MARK_TAIL が届いた" "<<EOF(- の無い形)は字下げした区切りの行で終わらない(本文の続きまで読ませる)" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_TAIL" "gh issue comment 1 --body-file - <<'EOF'
$CR_BODY $CR_PAD
  EOF
MARK_TAIL
EOF"
expect_output 0 "取り出せない" "繰り返しの中では、gh の後のコマンドも次の gh の前に走るので書き手に数える" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_FAIL" "for i in 1 2; do gh issue comment 1 --body-file $CR_FDIR/body.md; cp $CR_FDIR/b/body.md $CR_FDIR/body.md; done"
# 4. ヒアドキュメントの開始行で、区切りの後ろに同じ行で文字が続く形を見落とし、「別プロセスからの stdin」で誤って止めていた
expect_output 0 "詰まり" "区切りの後ろに旗が続くヒアドキュメント(<<'J' -q .html_url)も本文として読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh api repos/o/r/issues/1/comments --input - <<'J' -q .html_url
{\"body\": \"$CR_BODY $CR_PAD\"}
J"
expect_output 0 "詰まり" "区切りの後ろにパイプが続くヒアドキュメント(<<'EOF' | tail)も本文として読む" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "gh issue comment 1 --body-file - <<'EOF' | tail -1
$CR_BODY $CR_PAD
EOF"
CR_STUB_SEES_B=$(cr_stub_sees MARK_B)
expect_output 0 "MARK_B が届いた" "1 行に 2 つのヒアドキュメントが在っても、gh に付いた方を本文にする" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_SEES_B" "cat <<'A' > /dev/null; gh issue comment 1 --body-file - <<'B'
MARK_A $CR_PAD
A
MARK_B $CR_BODY $CR_PAD
B"
# 5. timeout の前置で gh が見えず素通しだった
expect_output 0 "詰まり" "timeout 180 の前置でも gh を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "timeout 180 gh pr create --title t --body '$CR_BODY $CR_PAD'"
expect_output 0 "詰まり" "timeout の -s・-k の値と長さを読み飛ばしても gh を見失わない" \
    "$CR_CASE" "$CR_CFG" "$CR_STUB_BLOCK" "timeout -s KILL -k 5 2m gh pr create --title t --body '$CR_BODY $CR_PAD'"
# 6. misses.log: 短いコマンドも記録し、ヒアドキュメントの中身は見ず、当たった単純コマンドの先頭の語を添える
CR_MISS_CFG="$WORK/coldread-cfg-miss"; mkdir -p "$CR_MISS_CFG"
"$CR_CASE" "$CR_MISS_CFG" "$CR_STUB_FAIL" "sh -c 'gh issue comment 1 --body hi'" >/dev/null 2>&1
"$CR_CASE" "$CR_MISS_CFG" "$CR_STUB_FAIL" "cat > /dev/null <<'EOF'
gh issue comment 1 --body の書き方の説明
EOF
gh pr view 1" >/dev/null 2>&1
expect_output 0 "MISS_OK" "misses.log は短いコマンドの落ちも旗と先頭の語で残し、ヒアドキュメントの中身の綴りは数えない" \
    "$PY_BIN" -c 'import sys
rows = [l.rstrip("\n").split("\t")[1:] for l in open(sys.argv[1], encoding="utf-8")]
print("MISS_OK" if rows == [["--body", "sh"]] else "BAD %r" % rows)' "$CR_MISS_CFG/coldread-gate/misses.log"
# 7. 試験が本物の記録(~/.claude*/coldread-gate/denies.log)に書いていた(セッション ID の空の parse-fail の塊)
mkdir -p "$WORK/cr-home"
expect_output 0 "NO_LEAK" "解析の例外の検査は、本物の設定フォルダに記録を書かない" \
    env -u CLAUDE_CONFIG_DIR HOME="$WORK/cr-home" sh -c '"$1" "$2" >/dev/null; if [ -e "$3/.claude/coldread-gate" ]; then echo LEAKED; else echo NO_LEAK; fi' sh "$PY_BIN" "$ROOT/tests/coldread-raise-case.py" "$WORK/cr-home"

# ---- destgate: 投稿先の許可一覧(coldread と独立の軸。一覧が無ければ眠る) ----
DG_CASE="$ROOT/tests/destgate-case.sh"
DG_CFG="$WORK/destgate-cfg"; mkdir -p "$DG_CFG/destgate"
printf 'good/*\nallowed/repo\n' > "$DG_CFG/destgate/allowlist"
DG_NOCFG="$WORK/destgate-nocfg"; mkdir -p "$DG_NOCFG"
DG_POST_EVIL="gh issue comment 1 -R evil/place --body 'こんにちは、これは宛先検査のテスト本文です'"

expect_output 0 "ALLOW_EMPTY" "destgate: 一覧が無ければ眠る(投稿でも素通し)" \
    "$DG_CASE" "$DG_NOCFG" "$WORK" "$DG_POST_EVIL"
expect_output 0 "ALLOW_EMPTY" "destgate: 一覧内の宛先(完全一致)は通る" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh issue comment 1 -R allowed/repo --body 'テストの本文です'"
expect_output 0 "ALLOW_EMPTY" "destgate: owner/* パターンで通る" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh pr comment 2 -R good/anything --body 'テストの本文です'"
expect_output 0 "許可一覧に無い" "destgate: 一覧外の宛先は deny" \
    "$DG_CASE" "$DG_CFG" "$WORK" "$DG_POST_EVIL"
expect_output 0 "許可一覧に無い" "destgate: COLDREAD_SKIP=1 でも宛先検査は外れない" \
    "$DG_CASE" "$DG_CFG" "$WORK" "COLDREAD_SKIP=1 $DG_POST_EVIL"
expect_output 0 "許可一覧に無い" "destgate: 行継続で折り返しても宛先検査は外れない" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh issue comment 1 -R evil/place \\
  --body 'こんにちは、これは宛先検査のテスト本文です'"
expect_output 0 "ALLOW_EMPTY" "destgate: 読み取り系は宛先が一覧外でも素通し" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh pr list -R evil/place --limit 5"
expect_output 0 "許可一覧に無い" "destgate: gh api の repos/ パスから宛先を取る" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh api repos/evil/place/issues/1/comments -f body='宛先検査のテスト本文です'"
expect_output 0 "特定できない" "destgate: 宛先を特定できない投稿は deny(-R の明示を促す)" \
    "$DG_CASE" "$DG_CFG" "$WORK" "gh api graphql -f query='mutation { m }' -f body='宛先検査のテスト本文です'"

# 明示の -R が無い投稿は、gh と同じくカレントの git remote を宛先とみなす
DG_REPO_OK="$WORK/dg-repo-ok"; git init -q "$DG_REPO_OK"; git -C "$DG_REPO_OK" remote add origin git@github.com:good/things.git
DG_REPO_NG="$WORK/dg-repo-ng"; git init -q "$DG_REPO_NG"; git -C "$DG_REPO_NG" remote add origin https://github.com/evil/place.git
expect_output 0 "ALLOW_EMPTY" "destgate: -R 無しは git remote を宛先にする(一覧内)" \
    "$DG_CASE" "$DG_CFG" "$DG_REPO_OK" "gh issue comment 1 --body 'テストの本文です'"
expect_output 0 "許可一覧に無い" "destgate: -R 無しの git remote が一覧外なら deny" \
    "$DG_CASE" "$DG_CFG" "$DG_REPO_NG" "gh issue comment 1 --body 'テストの本文です'"
# `\` 区切りの remote（Windows の checkout の形）。`/` 固定で末尾 2 セグメントを取っていたので、
# 宛先が読めず「宛先不明」で deny していた——止まる側なので気づきにくい。同じ規則の姉妹は
# attention の changemap.py の REPO_TAIL で、そちらだけ直して写しが残っていた（2026-09-16）。
# **どの OS でも赤くなる形で固定する**: git は remote の URL を検査しないので、この綴りは mac でも置ける
DG_REPO_WIN="$WORK/dg-repo-win"; git init -q "$DG_REPO_WIN"
git -C "$DG_REPO_WIN" remote add origin 'C:\src\good\things.git'
expect_output 0 "ALLOW_EMPTY" "destgate: \ 区切りの remote でも宛先を読む（Windows の checkout の形）" \
    "$DG_CASE" "$DG_CFG" "$DG_REPO_WIN" "gh issue comment 1 --body 'テストの本文です'"

# ---- attention/catchup: 1 件の PR / issue の「前回から何が起きたか」 ----
# 取得(gh / GraphQL)はテストの外。ここで検査するのは材料 → 出力の規則だけで、取得をモックすると
# 検査対象が自分で書いたモックになる
CU_CASE="$ROOT/tests/catchup-case.py"

expect_output 0 "レビュー結果です。block が 1 件あります" \
    "catchup: 自分の最後の発言が「私が最後にしたこと」になる" "$PY_BIN" "$CU_CASE" mine
expect_output 0 "私宛の依頼が来ていて、その後に私は発言していない" \
    "catchup: 依頼ボタンも未解決スレッドも無い名指しの依頼をターンとして拾う" \
    "$PY_BIN" "$CU_CASE" mine
expect_output 0 "人にしか判断できない 3 点" \
    "catchup: 依頼が「渡された時点」より前でも拾う" "$PY_BIN" "$CU_CASE" ask-before-handover
expect_output 0 "で私に渡された" \
    "catchup: 未発言の件はそう言う（作成時に落とさず、渡された時点を出す）" \
    "$PY_BIN" "$CU_CASE" ask-before-handover
expect_output 0 "レビュアー · ● 私の番" \
    "catchup: レビュー依頼が来ていれば立場はレビュアー" "$PY_BIN" "$CU_CASE" ask-before-handover
expect_output 0 "レビュー依頼 を出している" \
    "catchup: 本文の依頼を優先しつつ、後から押された依頼ボタンも申し送る" \
    "$PY_BIN" "$CU_CASE" ask-prefers-text
expect_output 0 "未参加 · ○ 待ち — レビュー待ち: someone" \
    "catchup: 依頼も担当も発言も無ければ「私の番」ではなく、立場は未参加" "$PY_BIN" "$CU_CASE" waiting
expect_output 0 "実装者（作者） · ● 私の番" \
    "catchup: 作者なら立場は実装者" "$PY_BIN" "$CU_CASE" ci-unknown-conclusion
expect_output 0 "    - CI 赤は作者（私）しか外せない" \
    "catchup: 知らない conclusion は赤に倒す。理由が複数なら箇条書き" \
    "$PY_BIN" "$CU_CASE" ci-unknown-conclusion
expect_output 0 "赤 1 件（deploy）" \
    "catchup: 赤いチェックの名前を出す" "$PY_BIN" "$CU_CASE" ci-unknown-conclusion
expect_output 0 "lint  https://example.invalid/runs/1" \
    "catchup: 赤いチェックに行き先の URL を添える" "$PY_BIN" "$CU_CASE" ci-red-url
expect_output 0 "CI が落ちた理由（上の URL か gh pr checks で見る）" \
    "catchup: 焦点で CI の材料を外したときは、落ちた理由は見ていないと断り、CI を付ける口を書く" \
    "$PY_BIN" "$CU_CASE" ci-red-url
expect_output 0 "実行中 1 件" \
    "catchup: 走っている最中は赤にも緑にも数えない" "$PY_BIN" "$CU_CASE" ci-running
expect_output 0 "書きかけのレビューが未送信" \
    "catchup: 未送信レビューを自分の宿題として出す" "$PY_BIN" "$CU_CASE" pending-review
expect_output 0 "その後に起きたこと — 0 件" \
    "catchup: 未送信レビューを時系列に混ぜない（相手には届いていない）" \
    "$PY_BIN" "$CU_CASE" pending-review
expect_output 0 "未解決スレッド 1 件で相手が返している（私が返す番）" \
    "catchup: 自分が入っている未解決スレッドの返答をターンとして拾う" \
    "$PY_BIN" "$CU_CASE" thread-turn
expect_output 0 "CI: 報告なし" \
    "catchup: チェックが 1 本も無い状態を「全 pass」と言わない" "$PY_BIN" "$CU_CASE" no-checks
expect_output 0 "この件で私はまだ何もしていない" \
    "catchup: 触っていない件はそう言う" "$PY_BIN" "$CU_CASE" no-checks
expect_output 0 "まだ承認されていない（REVIEW_REQUIRED）" \
    "catchup: API の値をそのまま出さず、中身を先に書いて原語を括弧で添える" \
    "$PY_BIN" "$CU_CASE" waiting
expect_output 0 "コメントの古い方 139 件（140 件中、新しい 1 件だけ取った）" \
    "catchup: 取得上限に当たったら黙って切らず、何を見落としうるかまで申告する" \
    "$PY_BIN" "$CU_CASE" cap
expect_output 0 "（本文なし）" \
    "catchup: 引用だけの本文を発言の中身として扱わない" "$PY_BIN" "$CU_CASE" quote-only
expect_output 0 "その後に起きたこと — 0 件" \
    "catchup: login に結び付いていない commit を、手元の git config の user.email と照合して自分の push にする" \
    "$PY_BIN" "$CU_CASE" push-alias
expect_output 0 "me-git が push" \
    "catchup: メールが一致しなければ、結び付いていない commit は名前のまま他人として出す（名前では照合しない）" \
    "$PY_BIN" "$CU_CASE" push-stranger
expect_output 0 "結び付いていない commit（名前: me-git）が誰のものか" \
    "catchup: 照合に外れた結び付き無しの commit を末尾で申告する" \
    "$PY_BIN" "$CU_CASE" push-stranger
expect_output 0 "私の最後の発言（" \
    "catchup: 自分の件で本文なしの承認と解決済みスレッドは「求められていること」に拾わない" \
    "$PY_BIN" "$CU_CASE" ask-on-my-item-empty
expect_output 0 "レビュー依頼が誰にも出ていない（依頼先を決めるのは私）" \
    "catchup: 自分の PR でレビュー依頼が誰にも出ていなければ、渡すのは私" \
    "$PY_BIN" "$CU_CASE" own-pr-unrequested
expect_output 0 "未参加 · ● 私の番 — 私宛の依頼が来ていて" \
    "catchup: 名指しで呼ばれただけの件は「未参加 · 私の番」（どちらでもないと断定しない）" \
    "$PY_BIN" "$CU_CASE" mentioned-outsider
expect_output 0 "再確認をお願いします" \
    "catchup: push は返事ではない——最後の痕跡が push でも、依頼は最後の発言より後から探す" \
    "$PY_BIN" "$CU_CASE" push-not-cutoff
expect_output 0 "名指しは無い。私の件への発言" \
    "catchup: 自分の件では名指しの無い発言も最後の 1 件を拾い、名指しが無いと断る" \
    "$PY_BIN" "$CU_CASE" ask-on-my-item
expect_output 0 "問いかは本文で確かめる" \
    "catchup: 名指しの無い発言は、問いかどうかを機械で決めずにターンの理由に書く" \
    "$PY_BIN" "$CU_CASE" ask-on-my-item
expect_output 0 "その後に起きたこと — 0 件" \
    "catchup: 参照（他の PR がこの番号を書いた）を出来事に数えない" \
    "$PY_BIN" "$CU_CASE" refs-not-events
expect_output 0 "#99 別の PR" \
    "catchup: 参照はつながっている先に置く" "$PY_BIN" "$CU_CASE" refs-not-events
expect_output 0 "○ 待ち — レビュー待ち: someone" \
    "catchup: 自分の PR の assignee は、それだけでは「私の番」の理由にならない" \
    "$PY_BIN" "$CU_CASE" assignee-own-pr
expect_output 0 "担当 · ● 私の番 — 私が担当（assignee）" \
    "catchup: issue では担当がターンの根拠で、立場も担当" "$PY_BIN" "$CU_CASE" issue-assignee
expect_output 0 "ISSUE_UNSEEN_OK" \
    "catchup: issue の「見ていないもの」に diff を書かず、本文は上限で切れた分だけ申告する" \
    "$PY_BIN" "$CU_CASE" issue-not-seen
expect_output 1 "使い方" \
    "catchup: 知らないケース名は落ちる（検査自体の空振りを防ぐ）" "$PY_BIN" "$CU_CASE"
expect_output 1 "番号か PR / issue の URL、手元の commit を渡す" \
    "catchup: 番号でも URL でもない引数は、gh を叩く前に落とす" \
    "$PY_BIN" "$ROOT/attention/scripts/catchup.py" abc
expect_output 1 "対象は 1 つだけ渡す" \
    "catchup: 対象を 2 つ渡したら gh を叩く前に落とす" \
    "$PY_BIN" "$ROOT/attention/scripts/catchup.py" 1 2
expect_output 0 "SPLIT_OK" \
    "catchup: 引数の語を対象と焦点（指摘・地図・CI）に分ける。焦点だけ・引数なしは今のブランチ" \
    "$PY_BIN" "$CU_CASE" split-words
expect_output 0 "TAILS_OK" \
    "catchup: 末尾の材料は有れば全部出す（自分の PR にも地図）。焦点はその 1 つに絞り、issue には無い" \
    "$PY_BIN" "$CU_CASE" tails-by-existence
expect_output 0 "WORDING_OK" \
    "catchup: 焦点なしの既定では、赤なら CI の材料が付くので「見ていない」と断らず、PR なら地図が付くと言う" \
    "$PY_BIN" "$CU_CASE" tails-default-wording
expect_output 0 "THREADS_OK" \
    "catchup: 指摘の材料は相手の発言がある未解決スレッドだけ。相手の最後の発言と head の前後の行、file の外の行はそう言う" \
    "$PY_BIN" "$CU_CASE" threads-material
expect_output 0 "SINCE_OK" \
    "catchup: 私が返すターンで相手が私の発言の後に返した件は、私の発言以降の変更を今の姿に帯で出す。共通の字下げは落とし、代入の文字列リテラルの中は畳む。字下げのある def も関数の境目" \
    "$PY_BIN" "$CU_CASE" threads-since
expect_output 0 "BRANCH_OK" \
    "catchup: ブランチ名の番号は区切りに挟まれた数字だけ（版の数字を番号にせず、1 桁は通す）" \
    "$PY_BIN" "$CU_CASE" branch-number
expect_output 0 "CI_OK" \
    "catchup: CI の材料は Actions の run だけログを取り、行頭の印を落として最後の ##[error] までにする" \
    "$PY_BIN" "$CU_CASE" ci-material
expect_output 0 "BODY_OK" \
    "catchup: 本文の材料は作者の本文を 60 行まで（--full で全部）、閉じる issue は冒頭 12 行。行は 1 文字も変えない" \
    "$PY_BIN" "$CU_CASE" body-material
expect_output 0 "REFS_OK" \
    "catchup: 本文が # で指す番号の冒頭を 3 件まで出す（自分・閉じる issue・URL の fragment は除く。PR は PR と言う）" \
    "$PY_BIN" "$CU_CASE" body-refs
expect_output 0 "STACKED_OK" \
    "catchup: 取り込み先が既定ブランチでなければそのブランチとブランチの PR（fork の同名は除く）を出し、上に積む open PR は 3 件＋「他にもある」" \
    "$PY_BIN" "$CU_CASE" stacked
expect_output 0 "STACKED_OK" \
    "catchup: 取り込み先が既定ブランチなら取り込み先の行は出ない" \
    "$PY_BIN" "$CU_CASE" stacked-default
expect_output 0 "SUGGESTED_OK" \
    "catchup: 依頼先の候補（GitHub の提案）は自分の PR で依頼が誰にも出ていないときだけ根拠つきで出し、空なら「なし」、依頼があれば出ない" \
    "$PY_BIN" "$CU_CASE" suggested
expect_output 0 "SINCE_OK" \
    "catchup: 私の痕跡以降に変わった file——基準がレビューなら厳密、作者側の commit だけ file を取り取り込みは数だけ、status は git の 1 文字で最後の commit のもの" \
    "$PY_BIN" "$CU_CASE" since-review
expect_output 0 "SINCE_OK" \
    "catchup: 基準が本文コメントなら commit の日付で置いた近似と断り、最初の commit より前ならセクションを出さない" \
    "$PY_BIN" "$CU_CASE" since-approx
expect_output 0 "SINCE_OK" \
    "catchup: 基準の commit が履歴に無ければ（rebase / amend）その 1 行だけで、file は取りに行かない" \
    "$PY_BIN" "$CU_CASE" since-rewritten
expect_output 0 "SINCE_OK" \
    "catchup: allCommits が 100 本で切れていて基準が窓に無ければ「書き換え」と断定せず、取っていないと言う" \
    "$PY_BIN" "$CU_CASE" since-outside
expect_output 0 "MAP_JUMPS_OK" \
    "catchup: 地図の変更に、各枠の前の飛び先 path:行 と見出しの断り。散文（md）も枠、新規は path:1、削除 file だけ飛び先が無い" \
    "$PY_BIN" "$CU_CASE" map-jumps

expect_output 0 "OK" \
    "catchup: ブランチ名で呼ぶと移る（手元のブランチ／origin にだけ有るブランチは作って／既に居る／未コミットで移らない）。移ったブランチでは既定ブランチより先の commit の変更が木と枠で出て、main では出ない" \
    "$PY_BIN" "$ROOT/tests/catchup-switch-case.py" branch-name

expect_output 0 "WIRING_OK" \
    "catchup: main() の受け口の配線——焦点の断りは人の語（内部 key を出さない）、commit の 地図 は断らない、none の --frame は PR か commit に案内して止まる、commit の --switch は移る先が無いと言う" \
    "$PY_BIN" "$CU_CASE" main-wiring

expect_output 0 "COMMIT_OK" \
    "catchup: commit（sha・HEAD~2・タグ）を渡すと GitHub に聞かず、題と本文・木・変更の中身（枠と飛び先）を出す。--frame は 1 file を全部" \
    "$PY_BIN" "$CU_CASE" commit

expect_output 0 "RANGE_OK" \
    "catchup: commit の範囲 A..B（A...B は merge-base から）を渡すと、commit の一覧（古い順）・木・変更の中身（枠と飛び先は B の版）を 1 commit と同じ形で出す。--frame は 1 file を全部" \
    "$PY_BIN" "$CU_CASE" range

expect_output 0 "NO_TARGET_OK" \
    "catchup: PR も番号も無いブランチ（main 等）でも止まらず、GitHub に聞かずに手元のブランチと未コミットの中身（枠と飛び先）を出す" \
    "$PY_BIN" "$CU_CASE" no-target
# UnicodeEncodeError になり、日本語の報告そのものが出せない＝ツールが丸ごと使えなくなる。
# GitHub Actions の windows-latest で実測して赤くなった)
expect_output 0 "○ 待ち" \
    "catchup: stdio を cp1252 に強制しても日本語の報告が出る" \
    env PYTHONIOENCODING=cp1252 "$PY_BIN" "$CU_CASE" waiting
expect_output 1 "番号か PR / issue の URL、手元の commit を渡す" \
    "catchup: cp1252 強制下でも引数エラーの日本語が出る" \
    env PYTHONIOENCODING=cp1252 "$PY_BIN" "$ROOT/attention/scripts/catchup.py" abc

# ---- attention/catchup --switch: 該当ブランチへ移る（一時の git リポジトリで実際に動かす） ----
# GitHub には触らない。guard は「git 自身が止めない状態」で組む（ブランチで中身が違う file で汚すと guard を
# 消しても git が拒んで緑のまま）。合否は行の文言と git の状態（branch --show-current 等）の両方で見る
CS_CASE="$ROOT/tests/catchup-switch-case.py"
expect_output 0 "--switch" "catchup: --switch の口がある（コマンドの本文が番号か URL の呼び方に付ける）" \
    "$PY_BIN" "$ROOT/attention/scripts/catchup.py" --help
expect_output 0 "ISSUE_OK" \
    "catchup --switch: issue の移る先は名前に番号を持つ手元のブランチが 1 本のときだけ（純関数。0 本・2 本以上は候補名）" \
    "$PY_BIN" "$CU_CASE" issue-branch
expect_output 0 "SWITCH_OK" "catchup --switch: きれいな木なら移り、元のブランチ名を行に残す" \
    "$PY_BIN" "$CS_CASE" moved
expect_output 0 "SWITCH_OK" "catchup --switch: 追跡ファイルの未コミット（git は持ち越せる）があれば移らず、変更もそのまま" \
    "$PY_BIN" "$CS_CASE" dirty
expect_output 0 "SWITCH_OK" "catchup --switch: 未追跡だけなら移り、持ち越した数を行に書く" \
    "$PY_BIN" "$CS_CASE" untracked
expect_output 0 "SWITCH_OK" "catchup --switch: ignored の file を対象のブランチが追跡していれば上書きせず止まる（--no-overwrite-ignore）" \
    "$PY_BIN" "$CS_CASE" ignored
expect_output 0 "SWITCH_OK" "catchup --switch: 既に居れば移らず、居る扱い（手元のセクションが付く）" \
    "$PY_BIN" "$CS_CASE" already
expect_output 0 "SWITCH_OK" "catchup --switch: 別の worktree に checkout 済みのブランチには移らず、機械の言葉でその旨" \
    "$PY_BIN" "$CS_CASE" worktree
expect_output 0 "SWITCH_OK" "catchup --switch: origin にだけあるブランチは、その 1 本を fetch して作って移る（手元の古い追跡 ref からは作らない。追跡先は origin/<ブランチ>）" \
    "$PY_BIN" "$CS_CASE" remote-only
expect_output 0 "SWITCH_OK" "catchup --switch: 手元に無いブランチでも guard が先——未コミットがあれば fetch もせず止まり、一手は git switch でなく「もう一度 /catchup」、行に今どこに居るかが添う" \
    "$PY_BIN" "$CS_CASE" remote-dirty
expect_output 0 "SWITCH_OK" "catchup --switch: origin から作るときも ignored の file を上書きせず、拒まれたらブランチを作らない" \
    "$PY_BIN" "$CS_CASE" remote-ignored
expect_output 0 "SWITCH_OK" "catchup --switch: 手元にも origin にも無ければ作らずそう言う（merge 済みなら削除済みと取り方、届かなければ git の言い分、応答が無ければ timeout）" \
    "$PY_BIN" "$CS_CASE" none
expect_output 0 "SWITCH_OK" "catchup --switch: fork の PR のブランチが手元に無ければ origin の refs/pull/N/head から作って移り、追跡先は gh pr checkout と同じ" \
    "$PY_BIN" "$CS_CASE" fork-remote
expect_output 0 "SWITCH_OK" "catchup --switch: origin が別のリポジトリ・origin 無しなら移らない（その行にも今どこに居るかが付く）" \
    "$PY_BIN" "$CS_CASE" origin-mismatch
expect_output 0 "SWITCH_OK" "catchup --switch: git の checkout でない場所では移らない（落ちない）" \
    "$PY_BIN" "$CS_CASE" no-git
expect_output 0 "SWITCH_OK" "catchup --switch: guard の git status が読めなければ（None）止める。空と同じにしない（純関数）" \
    "$PY_BIN" "$CS_CASE" status-none
expect_output 0 "SWITCH_OK" "catchup --switch: fork の PR は名前だけでは移らず、手元のブランチが head の commit を含むときだけ移る（手元が古い・無関係なら移らない）" \
    "$PY_BIN" "$CS_CASE" fork
expect_output 0 "SWITCH_OK" "catchup --switch: head が main の fork PR で手元の main に移らず、<owner>/main を無ければ refs/pull/N/head から作り、あればそれに移る。消えた fork は名前だけでは移らない" \
    "$PY_BIN" "$CS_CASE" fork-main
expect_output 0 "SWITCH_OK" "catchup --switch: origin が自分の fork（三角 workflow）なら、その fork からの PR は名前一致で移る" \
    "$PY_BIN" "$CS_CASE" triangular
expect_output 0 "SWITCH_OK" "catchup --switch: 解決済みの merge（MERGE_HEAD あり）は「途中」と言って移らない（stash は MERGE_HEAD を消す）" \
    "$PY_BIN" "$CS_CASE" merge
expect_output 0 "LINE_OK" "catchup --switch: 結果の行は見出しの URL の直下（コマンドの本文が位置に依存する）。無ければ足さない" \
    "$PY_BIN" "$CU_CASE" branch-line
expect_output 0 "SWITCH_OK" "catchup --switch: post-checkout hook が非 0 でも HEAD は移っているので移った扱い（終了コードで判定しない）" \
    "$PY_BIN" "$CS_CASE" hook
expect_output 0 "SWITCH_OK" "catchup --switch: index.lock（他のセッションが git を動かしている最中）なら移れず、その名前が行に出る" \
    "$PY_BIN" "$CS_CASE" lock
expect_output 0 "SWITCH_OK" "catchup --switch: 同名のタグがあってもブランチを見失わない" \
    "$PY_BIN" "$CS_CASE" tag-shadow
expect_output 0 "SWITCH_OK" "catchup --switch: - で始まるブランチ名をオプションと取り違えない" \
    "$PY_BIN" "$CS_CASE" dash-name
expect_output 0 "SWITCH_OK" "catchup --switch: detached から移れ、置き去りの commit の警告を行に添える" \
    "$PY_BIN" "$CS_CASE" detached
expect_output 0 "SWITCH_OK" "catchup --switch: 衝突した rebase の途中なら「途中」と言って移らない（commit か stash とは言わない）" \
    "$PY_BIN" "$CS_CASE" rebase
expect_output 0 "SWITCH_OK" "catchup --switch: issue は名前に番号を持つ手元のブランチが 1 本のときだけ移る（0 本・2 本以上は候補名）" \
    "$PY_BIN" "$CS_CASE" issue
expect_output 0 "SWITCH_OK" "catchup --switch: 手元のセクションで、PR の head より後ろなら数え、head を持っていなければそう言う" \
    "$PY_BIN" "$CS_CASE" behind
expect_exit 1 "catchup --switch: 知らないケース名は落ちる（検査自体の空振りを防ぐ）" "$PY_BIN" "$CS_CASE"

# ---- attention/scripts/lib/changemap: 変更の地図の部品（/catchup と /what-am-i-doing が共用） ----
# git にも GitHub にも触らない。diff の分解・骨組み・木の描画を固定の材料で叩く
expect_output 0 "OK" "changemap: 変更の地図の部品の回帰（unittest。引用形の日本語 path・改名・木の周辺）" \
    "$PY_BIN" "$ROOT/tests/changemap-suite.py"

# ---- attention/scripts/lib/catchup_html: /catchup の報告を 1 枚の HTML に描く部品と catchup.py --render ----
# GitHub にも git にも VS Code にも触らない。VS Code の CLI は差し替え、置き場と設定は一時の階層に書く
expect_output 0 "OK" "catchup_html: フィールドの検査・雛形への差し込み・index の組み直し・socket の選び方・Machine の設定の足し方・PR の材料のターンと止めているもの・--render の出力・雛形の作り（unittest）" \
    "$PY_BIN" "$ROOT/tests/catchup-html-suite.py"

# ---- attention/reflect: ある期間を振り返り、改善の提案と気づきを 1 枚の HTML に出す ----
# 本物の会話の記録・GitHub・VS Code には触らない。設定のフォルダ・git・台帳・日記は一時の階層に作る
expect_output 0 "OK" "reflect: 期間・人と裏の会話の見分け・トークンを返答ごとに 1 回・起動した元ごとのまとめ・commit の引き方・GitHub の絞り方・フィールドの検査・台帳（却下は落とす）・日記のセクションの置き換え・持ち主の値を書かない（unittest）" \
    "$PY_BIN" "$ROOT/tests/reflect-suite.py"

# ---- scripts/spread-plugins.py: 会社の形の役「配布」のツール（全アカウントに配る） ----
# claude・herdr・git は偽物の runner で回す。/reload-plugins を部署と窓口の会話にだけ打つのはこの組織の決まりで、works-dispatch には置かない
SPREAD_CASE="$ROOT/tests/spread-plugins-case.py"
expect_output 0 "ONLY_COMPANY_TALKS_OK" \
    "spread-plugins: 手の空いた部署と窓口の会話にだけ打ち、ターンの途中・打ちかけの会話と手元の除外は飛ばす。自分の marketplace の物だけ更新" \
    "$PY_BIN" "$SPREAD_CASE" only-company-talks
expect_output 0 "FAILURE_IS_NONZERO_OK" \
    "spread-plugins: 1 つでも失敗したら 0 以外で終わる（works-dispatch が AI の部署に回す）。marketplace の更新は落ちたら 1 回だけ打ち直し、なお落ちても入った版がメインブランチとそろえば数えない" \
    "$PY_BIN" "$SPREAD_CASE" failure-is-nonzero
expect_output 0 "LOCAL_ACCOUNTS_OK" \
    "spread-plugins: 手元の設定の accounts（部署を起動しないアカウント）にも配り、同じ設定のフォルダは 1 回だけ" \
    "$PY_BIN" "$SPREAD_CASE" local-accounts
expect_output 0 "BROKEN_COPY_OK" \
    "spread-plugins: 更新が 0 で終わっても入った写しに plugin.json が無いか版がメインブランチ（全アカウントに配った後に読む）と違えば、ずれたアカウントだけ 1 回配り直してなお違うときに失敗に数え、失敗の行を出力の終わりに並べ直す" \
    "$PY_BIN" "$SPREAD_CASE" broken-copy
expect_output 0 "MEND_CLONE_OK" \
    "spread-plugins: marketplace の clone の作業ツリーから消えたファイルを、プラグインの更新の前に戻す" \
    "$PY_BIN" "$SPREAD_CASE" mend-clone

# ---- attention/what-am-i-doing: いま居るセッションで何が起きたか ----
# 本物のセッション記録には触らない。作業用の設定ディレクトリを毎回作って差し替える
WAI_CASE="$ROOT/tests/what-am-i-doing-case.py"

expect_output 0 "→ 直して push しました" \
    "what-am-i-doing: 依頼と返答を対で並べる（片方だけでは追いつけない）" \
    "$PY_BIN" "$WAI_CASE" pairs
expect_output 0 "やり取り 1 往復" \
    "what-am-i-doing: ツールの出力を依頼に数えない（tool_result も user レコードで落ちる）" \
    "$PY_BIN" "$WAI_CASE" ignores-tool-results
expect_output 0 "テスト実行・コミット・push" \
    "what-am-i-doing: 区切りになる操作を Bash の中身から拾う" "$PY_BIN" "$WAI_CASE" landmarks
expect_output 0 "道具 Bash×2, WebSearch×1" \
    "what-am-i-doing: 何のツールを何回使ったかを添える" "$PY_BIN" "$WAI_CASE" tool-counts
expect_output 0 "ONLY_FIRST_OK" \
    "what-am-i-doing: 返答は最初のひとまとまりだけ（全文だと記録の写しになる）" \
    "$PY_BIN" "$WAI_CASE" first-reply-only
expect_output 0 "（題が付いていない）" \
    "what-am-i-doing: 題が無いセッションはそう言う" "$PY_BIN" "$WAI_CASE" no-title
expect_output 0 "開始 01-05" \
    "what-am-i-doing: 開始は記録の 1 件目から取る（ctime は追記のたび動く）" \
    "$PY_BIN" "$WAI_CASE" start-time
expect_output 0 "間の 21 往復は省いた" \
    "what-am-i-doing: 上限を超えたら黙って切らずに省いた数を書く" "$PY_BIN" "$WAI_CASE" elide
expect_output 0 "29 番目のお願いです" \
    "what-am-i-doing: --full なら省かない" "$PY_BIN" "$WAI_CASE" full
expect_output 1 "セッション記録が見つからない" \
    "what-am-i-doing: 記録が無ければ落ちる（黙って空を出さない）" "$PY_BIN" "$WAI_CASE" missing
expect_output 0 "→ 直して push しました" \
    "what-am-i-doing: stdio を cp1252 に強制しても日本語の報告が出る" \
    env PYTHONIOENCODING=cp1252 "$PY_BIN" "$WAI_CASE" pairs
expect_output 0 "PICK_OK" \
    "what-am-i-doing: 立場の対象は会話で一番呼ばれている番号から当てる（ブランチ頼みは別件を拾う）" \
    "$PY_BIN" "$WAI_CASE" pick-reference
expect_output 0 "DIRTY_OK" \
    "what-am-i-doing: 未コミットのパスを位置で切らない（strip で桁がずれる）" \
    "$PY_BIN" "$WAI_CASE" dirty-paths
expect_output 0 "TREE_OK" \
    "what-am-i-doing: 未コミットの変更を木で出す（周辺つき、新規は行頭 +、変更は ~）" \
    "$PY_BIN" "$WAI_CASE" dirty-tree
expect_output 0 "FRAMES_OK" \
    "what-am-i-doing: 未コミットの中身は今の姿に機械が帯を入れた枠（コードは関数まるごと・散文は文脈 3 行。前の行はコメント）。各枠の前に飛び先 path:行。改名は新規に化けない。未追跡は先頭と骨組み。--frame は 1 file を全部。git diff が失敗したら断る" \
    "$PY_BIN" "$WAI_CASE" frames
expect_output 0 "TOPIC_OK" \
    "what-am-i-doing: --topic はその語が出た往復だけを出す（/catchup が会話の話題を追う背骨）" \
    "$PY_BIN" "$WAI_CASE" topic
expect_output 0 "UNSEEN_OK" \
    "what-am-i-doing: 見ていないものを実際の状態に合わせる（省いた・外した往復は件数と見落としうるものを書く）" \
    "$PY_BIN" "$WAI_CASE" unseen-wording
expect_output 0 "STANCE_OK" \
    "what-am-i-doing: 立場の判定は /catchup と共用の純関数。送ったレビューも数え、「どちらでもない」とは言わない" \
    "$PY_BIN" "$WAI_CASE" stance
expect_output 1 "使い方" \
    "what-am-i-doing: 知らないケース名は落ちる（検査自体の空振りを防ぐ）" "$PY_BIN" "$WAI_CASE"

# ---- attention/whose-turn: open 全件から誰のターンか ----
# GitHub には触らない。判定は純粋関数で、固定の材料が規則を 1 行ずつ固定する
WT="$ROOT/attention/scripts/whose-turn.py"
expect_output 0 "OK" "whose-turn: 判定規則の回帰（unittest 115 件。時刻はローカル、検査は UTC 固定）" \
    "$PY_BIN" "$ROOT/tests/whose-turn-suite.py"
expect_output 0 "見ていないもの" "whose-turn: --help に判定の定義と見ていないものが出る" \
    "$PY_BIN" "$WT" --help

# ---- works-dispatch/dispatch: 自分の番の PR を herdr の作業場に広げるライン ----
# 旧 works の試験の殻（works/tests/run.sh）には載せない（設計書 works-dispatch/docs/specs/2026-10-14-catchup-dispatch-design.md の D1）。
# 試験と、設計書のセクション 4 の決まりのチェック（works-dispatch/dispatch/tests/test_rules.py）を 1 本で回す。herdr・gh・claude には触らない
expect_output 0 "OK" "works-dispatch/dispatch: ノードの試験と決まりのチェック（D1〜D6・D8）" \
    "$PY_BIN" -B -m unittest discover -s "$ROOT/works-dispatch/dispatch/tests" -t "$ROOT"

# ---- tiers: 要るツールの段ごとの点検（ほかのプラグインが依存として入れ、使い始めに bin/tiers を呼ぶ）----
# 外のツール（claude・gh・herdr・archon）は起動せず、口（Probe）を偽物に替える
expect_output 0 "OK" "tiers: 段ごとの点検が足りない物と入れ方を返し、--json の形と終了コードを守る" \
    "$PY_BIN" -B -m unittest discover -s "$ROOT/tiers/tests"
# --out に値を取らせると `<位置引数> --out` の並びで位置引数を吸う。3 本とも並びごと固定する
expect_output 0 "OUT_FLAG_OK" \
    "attention 3 本: --out は値を取らず位置引数を吸わない。一時ファイルは 0600。セクションの行番号は材料の中の ## を拾わない。手順書が同じ並びで呼び、読み戻しの Read を allowed-tools に持つ" \
    "$PY_BIN" - "$ROOT" <<'PY'
import importlib.util, pathlib, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])


def load(stem):
    spec = importlib.util.spec_from_file_location(stem, root / f"attention/scripts/{stem}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# (script, 並び, 吸われては困るフィールドと期待値, 手順書, 手順書に在るべき呼び)
cases = [
    ("whose-turn", ["--materials", "taro", "--out"], "login", "taro",
     "whose-turn.md", "--materials $ARGUMENTS --out"),
    ("catchup", ["--switch", "1569", "指摘", "--out"], "words", ["1569", "指摘"],
     "catchup.md", "`catchup.py --switch <それ> --out`"),
    ("what-am-i-doing", ["--topic", "今の修正", "--out"], "topic", ["今の修正"],
     "what-am-i-doing.md", "what-am-i-doing.py --out"),
]
for stem, argv, field, want, doc, call in cases:
    a = load(stem).parser().parse_args(argv)
    assert a.out is True, f"{stem}: --out が立たない"
    assert getattr(a, field) == want, f"{stem}: {field} を吸われた（{getattr(a, field)!r}）"
    text = (root / "attention/commands" / doc).read_text(encoding="utf-8")
    assert "allowed-tools: Bash, Read" in text, f"{doc}: 読み戻しの Read が allowed-tools に無い"
    assert call in text, f"{doc}: 手順書の呼びが {call} になっていない"

# セクションの行番号は Read の offset に直接使う。材料の本文は行頭に ## を持つことがあるので、
# 印を渡した script はそこで止める（実測: issue の本文が `## 評価方法` で始まっていた）
sys.path.insert(0, str(root / "attention/scripts/lib"))
import outfile  # noqa: E402
body = "# 題\n## 経過（依頼と）\n本文\n## いま手元\n==== 印 ====\n## 人の本文が持つ見出し"
assert outfile.index(body) == ["2 経過", "4 いま手元", "6 人の本文が持つ見出し"], outfile.index(body)
assert outfile.index(body, stop=("==== 印", "材料")) == ["2 経過", "4 いま手元", "5 材料"], \
    outfile.index(body, stop=("==== 印", "材料"))
assert outfile.label("## " + "あ" * 30).endswith("…"), "長い見出しが畳まれない"

# 一時ファイルは 0600。open() で作ると umask 任せ（既定 0022）で 0644 になり、Linux の
# gettempdir()（= /tmp）では同じ機の別の利用者が PR / issue の中身を読める
import contextlib, io, os, re, stat  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    outfile.run_to_file(lambda: print("# 題\n## セクション"), "検査")
out = buf.getvalue()
m = re.search(r"報告は (\S+) に書いた", out)
assert m, out
if os.name == "posix":
    mode = stat.S_IMODE(os.stat(m.group(1)).st_mode)
    assert mode == 0o600, f"一時ファイルが {oct(mode)}（/tmp では他の利用者が読める）"
else:
    print("  ok   outfile の一時ファイルは 0600 # SKIP posix-mode: posix でない OS はファイルの mode を持たない")
assert "節（Read の offset）: 2 節" in out, out
os.unlink(m.group(1))
print("OUT_FLAG_OK")
PY

# ---- attention/scripts/figure-check: 絵（系の前後の図）の幅・行数・縦線・箱の検査 ----
# gh にも git にも触らない。通る図はコマンドの本文の例（14 行）そのもの。合否は落ちる／通るだけでなく行と桁が出ることで見る
FC_CASE="$ROOT/tests/figure-check-case.py"
expect_output 0 "FIGURE_OK" "figure-check: コマンドの本文の例（14 行）が通り、行数と最大桁が出る（file でも stdin でも同じ 1 行、exit 0）" \
    "$PY_BIN" "$FC_CASE" pass
expect_output 0 "FIGURE_OK" "figure-check: 60 桁を超える行は行番号と実際の幅で落ちる（東アジア幅は 2。縦線が揃っていれば幅の 1 件だけ）" \
    "$PY_BIN" "$FC_CASE" width
expect_output 0 "FIGURE_OK" "figure-check: 15 行目（空行でも）があれば行数で落ちる" \
    "$PY_BIN" "$FC_CASE" lines
expect_output 0 "FIGURE_OK" "figure-check: 縦線の列（2 行以上に立つ桁）以外の │ は行と桁で落ち、縦線の列が添う" \
    "$PY_BIN" "$FC_CASE" bar
expect_output 0 "FIGURE_OK" "figure-check: 縦線の列が 1 つも無ければ、その │ がずれとして出て列は「無い」" \
    "$PY_BIN" "$FC_CASE" bar-lone
expect_output 0 "FIGURE_OK" "figure-check: ┌┐ と └┘ の幅が違えば箱がずれ（行と桁と両辺の幅）。対の罫線が無い行もそう言う" \
    "$PY_BIN" "$FC_CASE" box
expect_output 0 "FIGURE_OK" "figure-check: 空の入力は「通った」と言わない" \
    "$PY_BIN" "$FC_CASE" empty
expect_exit 1 "figure-check: 知らないケース名は落ちる（検査自体の空振りを防ぐ）" "$PY_BIN" "$FC_CASE"

# ---- 全部のプラグインのスキル・コマンド・役の説明（頭の YAML の description） ----
# 説明は会話の始めに読み込まれ、壊れても読み込みは失敗しない（dispatch の説明が「 #」から後ろを YAML の注釈として読み捨てられていた）。
# 見ることと出典は台本の頭。YAML の読み手（PyYAML）は CI がどの OS にも入れる。手元に無ければ見送りにし、CI の FAIL_ON_SKIP=1 が
# SKIP_ALLOW に無い名前（pyyaml）として赤にするので、入れる段を消しても黙って緑には戻らない
SD_CASE="$ROOT/tests/skill-descriptions-case.py"
if "$PY_BIN" -c 'import yaml' >/dev/null 2>&1; then
    expect_output 0 "SKILL_DESCRIPTION_ARMS_OK" "スキルの説明のチェック: 空白の後の # で切れる・引用符の後ろの注釈・値の中の ---・読めない YAML・1 行目でない頭・空の説明・SKILL.md の 1,025 字・スキルとコマンドの description と when_to_use の合わせて 1,537 字・置き場を変えたプラグイン・何も見つからないプラグインを落とし、引用符や畳む書き方の中の # と CRLF・BOM・フィールドと同じ深さの注釈の行は通す" \
        "$PY_BIN" "$SD_CASE" arms
    expect_output 0 "SKILL_DESCRIPTIONS_OK" "スキルの説明のチェック: 全部のプラグインのスキル・コマンド・役の説明が YAML で黙って切れず、公式の字数の上限（SKILL.md 1,024 字・一覧 1,536 字）に収まる" \
        "$PY_BIN" "$SD_CASE" tree
else
    sd_skip="  ok   スキルの説明のチェック（2 件） # SKIP pyyaml: YAML の読み手（PyYAML）が手元に無い（CI はどの OS にも入れる）"
    echo "$sd_skip"
    note_skips "$sd_skip"
    ran=$((ran + 2))
fi

# ---- 全部のプラグインのスキル・コマンドの本文（スキルの書き方の標準 docs/standards/skill-authoring.md の決まり 1・4・5） ----
# 本文は呼ばれたときに丸ごと会話に載り、圧縮の後は頭の 5,000 トークンだけが残る。見ることと出典は台本の頭。
# 今 標準を満たさない物は台本の EXEMPT に載せて緑で始め、満たしたら赤で知らせて一覧から消させる（MANIFEST_STANDARD_OK と同じ形）
SB_CASE="$ROOT/tests/skill-body-case.py"
expect_output 0 "SKILL_BODY_ARMS_OK" "スキルの本文のチェック: 5,001 字・500 行の本文・無いリンクの先・ルートの外を指すリンク・目次の無い 100 行超えの別ファイル・外す一覧に残った満たした物と無い物・置き場を変えたプラグイン・空の走査を落とし、頭の YAML・コードの中のリンクの形・URL と変数・スクリプトは見ない" \
    "$PY_BIN" "$SB_CASE" arms
expect_output 0 "SKILL_BODY_OK" "スキルの本文のチェック: 全部のプラグインのスキルとコマンドの本文が 5,000 字以下かつ 500 行未満で、指したリンクの先がプラグインの中に在り、100 行を超える別ファイルに目次が有る（外す一覧の物を除く）" \
    "$PY_BIN" "$SB_CASE" tree

# ---- shell の静的検査（shellcheck） ----
# **定番解を入れて、自作の regex を落とした。** 自作のチェックは for の位置しか見ず、同じ問題クラス
# （SC2086 系の無引用展開）の他の位置は誰も見ていなかった——「射程が狭い」と注記で断る零処方を
# 3 周続けた結果、同じ断り書きが 3 か所に増えただけで母数は 1 件も減らなかった。
# **配布の必須依存は増えない**: shellcheck は利用者が入れる物ではなく、CI と開発者の手元で動くツールである
# （README の「必須」は git / python3 / bash のまま）。
# 手元に在れば回す。無ければ回さないが、**黙って消えない**——下の CI_LINT_OK が「CI が回す設定か」を見る。
if command -v shellcheck >/dev/null 2>&1; then
    sc_bad=0
    while IFS= read -r f; do
        shellcheck -S warning "$f" || sc_bad=1
    # 写した第三者の文（superpowers の写し）は直さない写しなのでチェックの外。写しの一致は works/tests/test_sp_skills.py の VendoredCopyCase が縛る
    done < <(find "$ROOT" -name "*.sh" -not -path "*/.git/*" -not -path "*/.shared/borrow/superpowers/*" | sort)
    if [ "$sc_bad" -eq 0 ]; then
        echo "  ok   SHELLCHECK_OK リポジトリの .sh が shellcheck -S warning を通る"
    else
        echo "  FAIL shellcheck が指摘を出した"
        fail=1
    fi
else
    sc_skip="  ok   リポジトリの .sh が shellcheck -S warning を通る # SKIP shellcheck: shellcheck が手元に無い（CI はどの OS にも入れる。下の CI_LINT_OK がその設定を見る）"
    echo "$sc_skip"
    note_skips "$sc_skip"
fi
# 見送りも計画の件数に入れる——回した分岐でだけ数えていたとき、ツールの無い環境で件数の照合が合わなくなった。合格とは別の印で出し、末尾の一覧に載る
ran=$((ran + 1))

# **チェックが CI から消えないことを見る。** 手元にツールが無い環境では上が回らないので、
# 「CI が回す設定になっている」ことだけは必ず測る（設定ごと消せば静かに覆いが無くなる形を塞ぐ）
expect_output 0 "CI_LINT_OK" "CI の設定が shellcheck を回す（手元にツールが無い環境でも覆いが消えない）。どの OS にも同じ版の shellcheck を入れ、tests/run.sh の段に FAIL_ON_SKIP=1 と OS ごとの SKIP_ALLOW を渡す。engine が走らせる宣言（.review-checks.json）の段の名前が CI の run を持つ段に在る。台本の組（shard）は 0..N-1 を欠けなく並べて組の数を段に渡し、名簿を組ごとに上げ、shards の job が全組を待って全 OS の和を検算する。works の job が全履歴で取り、works/tests/run.sh を 0..N-1 の組に分けて組の数を段に渡し、FAIL_ON_SKIP=1 で回す。どの job の頭にも if: と continue-on-error: が無い。起動するのは main と release/** への push と手での起動だけで、同じブランチで待つ run は 1 つまで（走っている run は止めない）" \
    "$PY_BIN" - "$ROOT" <<'PYCI'
import pathlib, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
wf = pathlib.Path(sys.argv[1]) / ".github" / "workflows" / "test.yml"
txt = wf.read_text(encoding="utf-8")
# **語が在るかでなく、回す段が在るかを見る。** 語だけを見ていたとき、段を消しても**注記に残った同じ語**で
# チェックが通った（実測 2026-09-21: 腕 f5 が緑のまま素通りした）。実際に走る行（run:）だけを対象にする
import re
runs = [l.split("run:", 1)[1] for l in txt.splitlines() if l.strip().startswith("run:")]
# ツールそのものを起動する run: だけを数える（入れる段の shellcheck-py は語が続くので当たらない）
hits = [r for r in runs if re.search(r"(^|[\s|;&])shellcheck(\s|$)", r)]
assert hits, f"{wf}: shellcheck を実際に回す run: の段が無い（注記に語が在るだけでは通さない）"
assert all("-S warning" in r for r in hits), f"{wf}: shellcheck の深さ（-S warning）が手元の検査と揃っていない: {hits}"
# job ごと・段ごとに切って、注記の行を除いた中身だけを見る——env: と if: は run: の行でないので、全文の部分一致だと注記の語で通る。
jobs, cur, in_jobs = {}, None, False
for l in txt.splitlines():
    t = l.strip()
    if not t or t.startswith("#"):
        continue
    if l.rstrip() == "jobs:":
        in_jobs = True
        continue
    m = re.fullmatch(r"  ([A-Za-z0-9_-]+):", l.rstrip())
    if in_jobs and m:
        cur = jobs.setdefault(m.group(1), {"head": [], "steps": []})
        continue
    if cur is None:
        continue
    if t.startswith("- name:") or t.startswith("- uses:"):
        cur["steps"].append([t])
    elif cur["steps"]:
        cur["steps"][-1].append(t)
    else:
        cur["head"].append(t)
# **走らせるのは main と release/** への push と手での起動。** push のブランチの絞りが外れると wip の push のたびに全部が走り、main が外れると
# 取り込みのコマンド（--land）が手元の検証で入れた main で CI が起きず、release/** が外れるとゲートのブランチ（VERSION_BUMP_OK の release/*）で起きない
on_block, in_on = [], False
for l in txt.splitlines():
    if l.rstrip() == "on:":
        in_on = True
    elif in_on and l and not l[0].isspace() and not l.startswith("#"):
        break
    if in_on and l.strip() and not l.strip().startswith("#"):
        on_block.append(l.rstrip())
want_on = ["on:", "  push:", '    branches: [main, "release/**"]', "  workflow_dispatch:"]
assert on_block == want_on, f"{wf}: 起動する条件が main と release/** への push と手での起動だけの形（{want_on}）でない: {on_block}"
# **同じブランチで待つ run は 1 つまで、走っている run は止めない。** 外れると main の --land が続いた日に待ちの列が積み上がる（2026-10-16 に
# 10 本並んだ）。cancel-in-progress を true にすると、入れた後の赤を見つける run が次の push で毎回止まる
conc = [l.rstrip() for l in txt.splitlines()]
conc = conc[conc.index("concurrency:"):][:3] if "concurrency:" in conc else []
want_conc = ["concurrency:", "  group: test-${{ github.ref }}", "  cancel-in-progress: false"]
assert conc == want_conc, f"{wf}: 同じブランチで待つ run を 1 つにする形（{want_conc}）でない: {conc}"
assert {"test", "pytest", "shards"} <= set(jobs), f"{wf}: job の test・pytest・shards が揃っていない（{sorted(jobs)}）"
steps = [s for j in jobs.values() for s in j["steps"]]
def step(name):
    got = [s for s in steps if s[0] == f"- name: {name}"]
    assert len(got) == 1, f"{wf}: 段 {name} がちょうど 1 つでない（{len(got)} 個）"
    return got[0]
# **見送り自体を無くすツールはどの OS にも同じ版で入れる。** OS の条件（if:）を付けると、条件から外れた OS で tests/run.sh の中の
# shellcheck が見送りになり、SKIP_ALLOW に無い名前なので赤になる——黙って緑には戻らないが、原因が遠い
inst = [s for s in steps if any(re.fullmatch(r"run: python -m pip install shellcheck-py==[0-9][0-9.]*", x) for x in s)]
assert inst, f"{wf}: shellcheck を版を固定して入れる段（run: python -m pip install shellcheck-py==<版>）が無い"
assert not any(x.startswith("if:") for s in inst for x in s), f"{wf}: shellcheck を入れる段に OS の条件（if:）が付いている: {inst}"
# **組（shard）の形**: 番号は 0..N-1 を欠けなく並べ、N を段の GL_SHARD_TOTAL と揃える（欠けた組は shards の検算も赤にするが、原因が遠い）
sh = re.search(r"^\s+shard: \[([0-9, ]+)\]\s*$", txt, re.M)
assert sh, f"{wf}: test の matrix に組の一覧（shard: [0, 1, ...]）が無い"
shards = [int(x) for x in sh.group(1).split(",")]
assert shards == list(range(len(shards))) and len(shards) >= 2, f"{wf}: 組の一覧 {shards} が 0..N-1 の並びでない"
rs = step("tests/run.sh")
want = ["- name: tests/run.sh", "shell: bash", "env:", f'GL_SHARD_TOTAL: "{len(shards)}"', "GL_SHARD_INDEX: ${{ matrix.shard }}",
        "GL_SHARD_GROUP: ${{ matrix.os }}", "GL_SHARD_MANIFEST: ${{ runner.temp }}/gl-shard",
        'FAIL_ON_SKIP: "1"', "SKIP_ALLOW: ${{ matrix.skip_allow }}", "run: bash tests/run.sh"]
assert rs == want, (f"{wf}: tests/run.sh の段が、組を渡し、見送りを失敗に数えて OS ごとの許しの一覧を渡す形（{want}）と違う——"
                    f"env の値・run: の頭の代入・shell:・if:・continue-on-error: のどれでも見送りが黙って緑になる: {rs}")
assert rs in jobs["test"]["steps"], f"{wf}: tests/run.sh の段が test の job に無い"
up = step("upload shard manifest")
assert up in jobs["test"]["steps"] and up == ["- name: upload shard manifest", "uses: actions/upload-artifact@v4", "with:",
    "name: gl-shard-${{ matrix.os }}-${{ matrix.shard }}", "path: ${{ runner.temp }}/gl-shard", "if-no-files-found: error"], (
    f"{wf}: 組の名簿を上げる段が、組ごとの名前・名簿の置き場・無ければ赤（if-no-files-found: error）の形でない: {up}")
os_line = re.search(r"^\s+os: &os \[([^\]]+)\]\s*$", txt, re.M)
assert os_line, f"{wf}: test の matrix の os が錨（&os）付きの一覧でない（pytest の job が同じ一覧を *os で引く）"
oses = [x.strip() for x in os_line.group(1).split(",")]
assert "os: *os" in jobs["pytest"]["head"] and "include: *skip_allow" in jobs["pytest"]["head"], (
    f"{wf}: pytest の job が test の os と許しの一覧を錨（*os・*skip_allow）で引いていない——写しは片方だけ直る: {jobs['pytest']['head']}")
assert "needs: test" in jobs["shards"]["head"], f"{wf}: shards の job が needs: test を持たない（組を待たずに検算する）"
mg = step("shards")
merge = f"run: python graphloops/tests/parallel.py merge --groups {','.join(oses)} gl-shards/*"
assert mg in jobs["shards"]["steps"] and merge in mg, f"{wf}: shards の段が、test の os の全部（{oses}）を --groups に渡して検算していない: {mg}"
dl = step("download shard manifests")
assert "pattern: gl-shard-*" in dl and "path: gl-shards" in dl and not any(x.startswith("merge-multiple") for x in dl), (
    f"{wf}: 名簿を組ごとの置き場に落としていない（merge-multiple は組どうしの同名の名簿を上書きする）: {dl}")
# job の頭の if: と continue-on-error: は全 job で禁じる（skipped の job も、落ちても緑の job も、失敗に数えられない）。段の continue-on-error: も同じ
for name, j in jobs.items():
    assert not any(x.startswith(("if:", "continue-on-error:")) for x in j["head"]), f"{wf}: job {name} の頭に if: か continue-on-error: が在る（その job の検査ごと外れる）: {j['head']}"
assert not any(x.startswith("continue-on-error:") for s in steps for x in s), f"{wf}: continue-on-error: の段が在る（落ちても緑になる）"
# pytest のチェック（graphloops/tests/py/fence.py）も同じ許しの一覧で宣言つきの見送りを許す——同じ matrix の値を渡し、写しを持たない
ps = step("pytest")
assert "env:" in ps and "SKIP_ALLOW: ${{ matrix.skip_allow }}" in ps, (f"{wf}: pytest の段が OS ごとの許しの一覧"
    f"（SKIP_ALLOW: ${{{{ matrix.skip_allow }}}}）を渡していない——Windows の宣言つきの見送りが失敗に数えられる／固定の値だと他の OS で許しすぎる: {ps}")
# **works の試験の全段を回す job。** 見るのは要の 3 つだけ（2026-10-09 の掃除: 段の並びを丸ごと写して見ていた頃は、版の上げや
# 段の足し引きのたびに写しも直すだけで、捕まえた食い違いは無かった）: 全履歴を取る（works の試験は git の全履歴を引く）・
# 見送りを失敗に数える（FAIL_ON_SKIP=1）・組（shard）の番号を 0..N-1 で欠けなく並べ、N を段の WORKS_SHARD の「/N」と揃える
# （欠けた組のモジュールはどの runner でも回らない）
assert "works" in jobs, f"{wf}: works の試験の全段を回す job works が無い（{sorted(jobs)}）"
wk = jobs["works"]
wco = [s for s in wk["steps"] if s[0] == "- uses: actions/checkout@v5"]
assert len(wco) == 1 and "fetch-depth: 0" in wco[0], f"{wf}: works の job が全履歴（fetch-depth: 0）で取っていない: {wco}"
wrun = [s for s in wk["steps"] if "run: sh works/tests/run.sh" in s]
assert len(wrun) == 1, f"{wf}: works の job に works/tests/run.sh を回す段がちょうど 1 つ無い: {wk['steps']}"
assert 'FAIL_ON_SKIP: "1"' in wrun[0], f"{wf}: works の段が見送りを失敗に数えていない（FAIL_ON_SKIP: \"1\"）: {wrun[0]}"
wsh = [x for x in wk["head"] if x.startswith("shard:")]
assert len(wsh) == 1 and re.fullmatch(r"shard: \[[0-9, ]+\]", wsh[0]), f"{wf}: works の job の matrix に組の一覧（shard: [0, 1, ...]）が無い: {wk['head']}"
wshards = [int(x) for x in wsh[0][len("shard: ["):-1].split(",")]
assert wshards == list(range(len(wshards))) and len(wshards) >= 2, f"{wf}: works の組の一覧 {wshards} が 0..N-1 の並びでない"
assert f"WORKS_SHARD: ${{{{ matrix.shard }}}}/{len(wshards)}" in wrun[0], (
    f"{wf}: works の段の WORKS_SHARD が組の数 {len(wshards)} と揃っていない: {wrun[0]}")
# **engine が走らせる宣言は CI の段の写し**（手元は pytest を uv で入れ、CI は pip で入れるので語は揃わない）。名前だけ突き合わせる
# ——宣言に在って CI に無い段は、CI が回していない物を engine だけが回している。逆向き（CI の段を宣言が持たない）は許す:
# shellcheck は CI だけが段として回し、手元では tests/run.sh が在れば回す任意のツール
import json
named, last = set(), None
for l in txt.splitlines():
    t = l.strip()
    if t.startswith("- name:"):
        last = t.split(":", 1)[1].strip()
    elif t.startswith("run:") and last:
        named.add(last)
decl = json.loads((pathlib.Path(sys.argv[1]) / ".review-checks.json").read_text(encoding="utf-8"))
missing = sorted({s["name"] for s in decl["suite"]} - named)
assert not missing, f".review-checks.json の段 {missing} が {wf} の run を持つ段（{sorted(named)}）に無い"
print("CI_LINT_OK")
PYCI

# ---- attention のコマンドの本文と README: 機械の出力語を同じ綴りで持つ（絵の例が規則を通るかは figure-check の pass が /what-am-i-doing のコマンドの本文から読む） ----
# /catchup は 2026-10-15 から HTML のページを機械が描き、AI はフィールドの JSON だけを書く。端末の枠（飛び先・言語名）と絵の検査を
# 使うのは /what-am-i-doing だけになったので、その語は /what-am-i-doing のコマンドの本文と README に。/catchup の側は、AI が材料から
# 読む語（取り込み先など）と、描く口（--render・ATTENTION_CATCHUP_OPEN）をコマンドの本文・README・仕様書が同じ綴りで持つ
expect_output 0 "DOC_WORDS_OK" "コマンドの本文 2 本と README と仕様書が、機械の出力行の語（/what-am-i-doing の飛び先・言語名・figure-check.py、/catchup の取り込み先・上に積む・依頼先の候補・私の痕跡以降に変わった file・--render・ATTENTION_CATCHUP_OPEN）を同じ綴りで持つ（綴り違いは AI が探せない）" \
    "$PY_BIN" - "$ROOT" <<'PY'
import sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
docs = {n: (root / n).read_text(encoding="utf-8") for n in
        ["attention/commands/catchup.md", "attention/commands/what-am-i-doing.md", "attention/README.md",
         "attention/docs/catchup-spec.md"]}
others = docs.keys() - {"attention/commands/what-am-i-doing.md"}  # /what-am-i-doing は PR の材料を持たない
frames = {"attention/commands/what-am-i-doing.md", "attention/README.md"}  # 端末に枠と絵を出すのは /what-am-i-doing だけ
for word, files in [("飛び先", frames), ("figure-check.py", frames), ("（言語名 X）", frames), ("取り込み先", others),
                    ("上に積む", others), ("依頼先の候補", others), ("私の痕跡以降に変わった file", others),
                    ("--render", others), ("ATTENTION_CATCHUP_OPEN", others)]:
    for f in files:
        assert word in docs[f], f"{f}: 「{word}」が無い"
print("DOC_WORDS_OK")
PY

expect_output 0 "DOC_NUMBERS_OK" "仕様書のセクション 7 の上限の表が、機械の定数と同じ数値を持つ（数値の正本は仕様書。ずれたら片方が古い）" \
    "$PY_BIN" - "$ROOT" <<'PYNUM'
import sys, pathlib, importlib.util
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
spec = (root / "attention/docs/catchup-spec.md").read_text(encoding="utf-8")
table = spec[spec.index("## 7."):spec.index("## 8.")]
sys.path.insert(0, str(root / "attention/scripts"))
def load(name, rel):
    s = importlib.util.spec_from_file_location(name, root / rel); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
cm = load("changemap", "attention/scripts/lib/changemap.py")
cu = load("catchup", "attention/scripts/catchup.py")
for label, value in [("本文", f"{cu.BODY_CAP} 行"), ("冒頭", f"{cu.ISSUE_HEAD_LINES} 行"), ("件数", f"{cu.ISSUE_CAP} 件"),
                     ("スレッド", f"{cu.THREAD_BODY_CAP} 行"), ("1 file", f"{cm.FRAME_FILE_CAP} 行"), ("合計", f"{cm.FRAME_TOTAL_CAP} 行"),
                     ("指摘の件数", f"{cu.THREAD_CAP} 件"), ("帯", f"{cm.FRAME_WIDTH} 桁"), ("畳む", f"{cm.FRAME_WHOLE} 行"),
                     ("残す", f"{cm.FOLD_KEEP} 行"), ("散文", f"前後 {cm.PROSE_CONTEXT} 行"), ("指摘の前後", f"前後 {cu.THREAD_CONTEXT} 行"),
                     ("まとめる間", f"{cm.FRAME_GAP} 行")]:
    assert value in table, f"仕様書のセクション 7 に {label} の {value} が無い"
print("DOC_NUMBERS_OK")
PYNUM

# 文書が名指しする機械の定数の実在検査。手順書・README は「正本は `QUESTION_KINDS`」の形で
# 写しを持たない作りにしてあるが、**名指しした先が在るかを誰も見ていなかった**——改名すれば、
# 文書だけが消えた名前を指したまま残り、読む人はそこへ探しに行って何も見つけられない。
cat > "$WORK/doc-symbols.py" <<'PYSYM'
import pathlib, re, sys
# **Windows の既定の標準出力は cp1252**（日本語 Windows なら cp932）で、日本語を print すると
# UnicodeEncodeError で落ちる。このリポジトリの検証器は同じ 3 行を既に持っている——**読む側だけ直して
# 書く側を直していなかった**（実測 2026-09-13: 今日足したチェック 4 本が windows-latest だけで落ちた。
# しかも落ちたのは合格の行を print するところ）。
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
# **除外は明示の表で持つ**——表に無い名前を名指しした瞬間に赤くなるので、足し忘れは
# fail-closed 側に倒れる。接頭辞はホストの環境変数、名前は git の用語。
EXTERNAL_PREFIX = ("CLAUDE_CODE_", "COLDREAD_")
EXTERNAL_NAMES = {"PYTHONOPTIMIZE", "PYTHONPATH", "CLAUDE_KEYCHAIN_SERVICE", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                  # Archon がノードと子に渡す環境変数・Archon の設定の環境変数
                  "ARTIFACTS_DIR", "TITLE_GENERATION_MODEL",
                  # 包みが Bash の役の子に向け直す・向け直さない外のツールの環境変数
                  "UV_CACHE_DIR", "TMPDIR",
                  # Python の tempfile が TMPDIR の次に一時フォルダの候補に見る環境変数（gates の coldread-gate.py が同じ順に読む）
                  "TEMP", "TMP",
                  # 外のツール（mise・gh・herdr のインストーラ）の設定の環境変数
                  "MISE_TRUSTED_CONFIG_PATHS", "GH_REPO", "GH_CONFIG_DIR", "GH_TOKEN", "HERDR_INSTALL_DIR",
                  # Claude Code がフックに渡す、Bash のコマンドごとに先に走らせるファイルの環境変数（works-dispatch の role_hook.py が読む）
                  "CLAUDE_ENV_FILE",
                  # Claude Code が会話とその子に渡す環境変数（works-dispatch が effort の継ぎと待ち受けの窓の確かめに読む）
                  "CLAUDE_EFFORT", "CLAUDE_JOB_DIR",
                  # Claude Code がプラグインのスキルの本文で置き換える、プラグインの入った場所の変数（スキルがコマンドの中のパスに書く。
                  # https://code.claude.com/docs/en/plugins-reference#environment-variables）
                  "CLAUDE_PLUGIN_ROOT",
                  # herdr がペインの中の殻に渡す環境変数（works-dispatch は HERDR_SOCKET_PATH を herdr への問い合わせに読み、HERDR_PANE_ID は
                  # 「継いだ値が別のペインを指すことがあるので使わない」と文書で名指す）・OS の PATH
                  "HERDR_PANE_ID", "HERDR_SOCKET_PATH", "PATH",
                  # プロキシの環境変数（works-dispatch の limits.py の問い合わせが urllib の既定で従う）
                  "HTTPS_PROXY",
                  # works-dispatch の設定の置き場を替える環境変数（CLAUDE_KEYCHAIN_SERVICE と同じく、モジュールの定数でなく os.environ から読む）
                  "WORKS_DISPATCH_CONFIG",
                  # attention の /reflect が読む環境変数（読む設定のフォルダを足す・日記の置き場。同じく os.environ から読む）
                  "ATTENTION_REFLECT_CONFIG_DIRS", "ATTENTION_REFLECT_DIARY_DIR",
                  # works のファイル名（写しの印・pack の版・盤面の止め札）
                  "COPIED_FROM", "VERSION", "STOP",
                  # プラグインの直下のファイル名（works-dispatch の --land が版の上げ幅を決めるとき文書に数える。docs/releasing.md も書く）
                  "LICENSE"}
# HEAD と CLAUDE_CONFIG_DIR は表から外した——works の python・shell が同じ名前を定数に持つので定義の在る
# 名前として通る（下の未使用の検査が表に残すことを拒む）。CLAUDE_KEYCHAIN_SERVICE は
# このリポジトリが定める環境変数で、モジュールの定数ではない（os.environ から読む）——COLDREAD_* が
# 接頭辞で外れているのと同じ理由で、接頭辞を持たないぶん名前で外す
# **名指しする側は文書だけではない。** 削除した定数を「正本」と呼ぶコメントが `tests/run.sh` に、
# 削除したチェックを「今も効いている」と述べたコメントが `scripts/*.py` に残ったことがある。
# **定義を持つ側も `scripts/*.py` だけではない**——検査スイートの定数も shell の定数も名指しされる。
# **定義の置き場を「どのプラグインか」で絞らない。** graphloops だけを足していたので、
# attention の `REPO_TAIL` を文書が名指しした周に「在るべき場所に無い」と出た（実測 2026-09-16）——
# 名指しは正しく、定義も在り、チェックの見る面だけが狭かった。プラグインの python は全部見る。
# **名前を並べない**（下の「手書きの列挙を持たない」と同じ理由）——プラグインの在り処は
# `*/.claude-plugin` が持っているので、そこから導く。1 つ足した周に黙って外れない。
CODE = sorted((root / "scripts").glob("*.py")) + sorted((root / "scripts").glob("*.sh")) + [
    root / "tests/run.sh"] + [q for d in sorted(m.parent for m in root.glob("*/.claude-plugin"))
                              for q in sorted(d.rglob("*.py")) + sorted(d.rglob("*.sh"))]
# **手書きの列挙を持たない。** 以前ここに 6 ファイルを並べていたとき、名指しの置き場が
# 増えた周にチェックが黙って外れた（実測: 列挙の外の 2 ファイルに実在しない名前を書いても全件緑）。
# 対象は「文書とコメントが在る場所」全部から導く。除外は名前の表でなく**接頭辞**で持つので、
# 別プラグインの環境変数（`COLDREAD_*` 7 個）が 1 項で収まる。
NAMED_IN = tuple(
    p for p in sorted(root.rglob("*.md")) if ".git" not in p.parts
    # 写した第三者の文（superpowers の写し）は直さない写しなのでチェックの外。写しの一致は works/tests/test_sp_skills.py の VendoredCopyCase が縛る
    and ".shared/borrow/superpowers/" not in p.as_posix()
    # works の計画と変更の記録は書いた日の名指しを残す歴史の文書なのでチェックの外（後で名を替えても書き直さない。2026-10-09 の掃除:
    # この 2 つだけを直す commit が名を足すだけで、本物の食い違いを 1 件も捕まえなかった）
    and not p.relative_to(root).as_posix().startswith(("works/docs/plans/", "works-dispatch/docs/plans/"))
    # 試しの記録（docs/trials/ の日付で始まる物）も、試した日の環境と名指しを残す歴史の文書なのでチェックの外。2026-10-16 の 3 回目の記録が
    # Windows の VM の台本（docs/trials/windows-vm/vm.sh）の環境変数 CLAUDE_ACCOUNT を名指しして、main の CI を赤にした。
    # 今の手順を書く docs/trials/windows-vm.md はチェックの中に残す
    and not p.relative_to(root).as_posix().startswith("docs/trials/2")
    and p.relative_to(root).as_posix() != "works/CHANGELOG.md"
) + tuple(sorted((root / "scripts").glob("*.py"))) + (root / "tests/run.sh",)
# **アンダースコアを要求するな。** 要求していたとき、`MATERIALS` / `REVIEWS` / `LABELS` /
# `STATUS` を同じ体裁で名指ししている箇所が 1 つも検査されなかった。
TOKEN = r"`([A-Z][A-Z0-9_]{2,})`"
# **ファイル名つきの名指しは、そのファイルに在ることを要求する。** 定義を全ファイル横断の
# 平坦な集合で持っていたとき、`review-record.py` の `MATERIALS` を改名しても
# `firstread-record.py` の同名定数で満たされて全件緑だった（実測。同名の定義は 10 個ある）。
# `targets()` が今周採った「域を持ち回って組で照合する」と同じ形にする。
# **行単位でなく隣接で取る**——同じ行に別のファイル名が在るだけで組にすると誤検出になる
# （実測: `comment-ratio.sh` に触れた行の `EXPECTED_CHECKS` が「そのファイルに無い」と出た）。
PAIR = r"`([A-Za-z0-9_.-]+\.(?:py|sh))`\s*(?:の)?\s*`([A-Z][A-Z0-9_]{2,})`"

def defined(text):
    """行頭の代入が定める大文字の名。**組の代入（`A, B = 1, 2`）も定義に数える**——1 つずつの代入だけを見ていたとき、
    chain.py の `KIND_CLOSED, KIND_HALTED, … = …` を名指した concepts.md が「在るべき場所に無い」と出た（定義は在った）"""
    return {n.strip() for m in re.findall(r"^([A-Z][A-Z0-9_]*(?:\s*,\s*[A-Z][A-Z0-9_]*)*)\s*=(?!=)", text, re.M)
            for n in m.split(",")}
assert defined("A_B, C_D = 1, 2\nE_F = 3\nG_H == 4\n") == {"A_B", "C_D", "E_F"}, "自己検査: 定義の拾い方が組の代入を外す"

by_file = {}
for p in CODE:
    # 同じ名前のファイル（tests/run.sh と graphloops/tests/run.sh）は和で持つ——上書きすると先に読んだ方の定数が消える
    by_file.setdefault(p.name, set()).update(defined(p.read_text(encoding="utf-8")))
names = set().union(*by_file.values())
# この台本の検査の合格の印（`expect_output 0 "VERSION_BUMP_OK" …` の期待文字列）も、文書が検査を指す名として名指す。
# 代入の行は無いので、印として台本に在れば実在と見る（除外の表に足さない——印を改名すれば文書の側が赤くなる）。
# 拾うのは `_OK` で終わる印だけ——期待文字列には環境変数の名（`COLDREAD_MAX_LEN`）も並ぶので、全部を拾うと接頭辞の除外と重なる
markers = set(re.findall(r'^expect_output \d+ "([A-Z][A-Z0-9_]*_OK)"', (root / "tests/run.sh").read_text(encoding="utf-8"), re.M))
assert "DOC_SYMBOLS_OK" in markers, "自己検査: 台本の合格の印の拾い方が、この検査自身の印を外す"
names |= markers
# works の WORKS_ で始まる名は環境変数で、殻と python が `${WORKS_X:-}`・`os.environ.get("WORKS_X")` の形で読むので、代入の行が
# 無いことが多い。works のコード（.py・.sh・.yaml）のどこかに字で在れば実在と見る（除外の表に 1 つずつ足さない）
WORKS_CODE = [q for q in sorted((root / "works").rglob("*")) if q.suffix in (".py", ".sh", ".yaml") and q.is_file()]
works_env = set().union(*(re.findall(r"\bWORKS_[A-Z0-9_]+", q.read_text(encoding="utf-8", errors="replace")) for q in WORKS_CODE))
assert len(works_env) >= 20, f"works のコードから WORKS_ の名を {len(works_env)} 個しか拾えていない（走査が壊れている）"

def wrong_pairs(pairs, label):
    """名指しされたファイルにその定数が無い組を返す。**自己検査のために関数にしてある**
    ——リポジトリには現に 1 件も無いので、外からは論理が効いているか測れない。"""
    return [f"{label}: {tok}（{fn} に無い）" for fn, tok in pairs
            if fn in by_file and tok not in by_file[fn]]

# 自己検査: 実在する「他所にだけ在る」組（`REQUIRED` は doctor / research にだけ在る）を
# 同じ関数に通し、必ず 1 件返ることを見る。平坦な集合なら通ってしまう組である。
# **測れない残りを明記する**——上の呼び出しを消す退行は、リポジトリに実際に落ちる組が
# 無い限りどんな腕でも捕まらない。捕まえられるのは抽出（下の件数の下限）と論理（ここ）。
PROBE = ("review-record.py", "REQUIRED")
assert PROBE[1] in names, "自己検査の前提が崩れた（この名前がどこにも定義されていない）"
assert wrong_pairs([PROBE], "self"), "自己検査: 組の照合が効いていない"

missing, used, paired = [], set(), 0
for f in NAMED_IN:
    body = f.read_text(encoding="utf-8")
    pairs = re.findall(PAIR, body)
    paired += len(pairs)
    missing += wrong_pairs(pairs, f.name)
    for tok in sorted(set(re.findall(TOKEN, body))):
        used.add(tok)
        if tok.startswith(EXTERNAL_PREFIX) or tok in EXTERNAL_NAMES or tok in names or tok in works_env:
            continue
        missing.append(f"{f.name}: {tok}")
assert not missing, "名指しされた定数が在るべき場所に無い: " + ", ".join(missing)
# 組の下限。正規表現が壊れて 0 件になると、上の組の検査が黙って空振りする。
assert paired >= 4, f"ファイル名つきの名指しを {paired} 件しか拾えていない（4 件以上を期待）"
# 走査対象の下限。rglob が 0 件を返しても missing は空で通る（自分の空振りで合格になる形）。
assert len(NAMED_IN) >= 29, f"走査対象が {len(NAMED_IN)} 件しかない（29 件以上を期待）"

# **除外表の未使用項目を赤にする。** これは未使用項の剪定であって、**誤った抑制は検知しない**
# ——表に「今も名指しされていて、かつ定義が無い名前」を 1 つ足せば、真の破れをそのまま
# 恒久的に隠せる（実測）。隠す使い方を止める仕掛けではない、と読める形で書いておく。
stale = sorted(n for n in EXTERNAL_NAMES if n not in used or n in names)
# 接頭辞は面で黙らせるので、**定義が在る名前を覆っていないか**も見る。`"MATERIAL"` を足せば
# `MATERIALS` の破れをそのまま隠せた（実測。名前の表と同じ穴が接頭辞側に残っていた）。
stale += [p for p in EXTERNAL_PREFIX if not any(t.startswith(p) for t in used)]
stale += [f"{p}（定義の在る名前を覆っている）" for p in EXTERNAL_PREFIX
          if any(t.startswith(p) and t in names for t in used)]
assert not stale, "除外表に使われていない項目が在る: " + ", ".join(stale)
print("DOC_SYMBOLS_OK")
PYSYM
expect_output 0 "DOC_SYMBOLS_OK" "文書が名指しする機械の定数が実在する（改名で片方だけ動かない）" \
    "$PY_BIN" "$WORK/doc-symbols.py" "$ROOT"

# **`-ne` であること。** 以前は `-lt` で、下限を上げ忘れても下げ忘れても黙って通った（実測:
# 実数 501 に対して下限が 491 のまま走り、検査を 10 件消しても「491 件すべて緑」で exit 0）。
# 注記で「上げるときは実測値を書け」と書いてあっても、注記は赤くならない——③仕組みに置き換える。
# ---- graphloops: graph の形と、台本で役を差し替えた模擬実行 ----
# 期待文字列は「件すべて緑」——「0 件失敗」だと母数 0（台本が 1 本も走らない）でも同じ部分文字列に
# 当たる。件数の突合（-ne）は graphloops/tests/run.sh が自分の EXPECTED_CHECKS で持ち、ここは
# 終了コードとその 1 行だけを見る（件数の正本を 2 か所にしない）。
expect_output 0 "件すべて緑" "graphloops: graphcheck（在る graph 全部）と模擬実行（収束・停止・諮り・軽量・拒否・チェックの腕）が通り、件数が期待どおり" \
    env ${GL_SHARD_ENV[@]+"${GL_SHARD_ENV[@]}"} bash "$ROOT/graphloops/tests/run.sh"

# **変異の腕の字列が、今の版に 1 か所ずつ在る。** 腕の一覧（tests/mutations.json）はリポジトリに置き、チェックを直す差分が
# 同じ変更で腕も直す（経緯は tests/mutate.py の docstring）。撃つのは重いので台本では走らせず、字列と証拠の口
# （expect か marker）の在る・無いだけを見る（撃つのは review-loop の gate_efficacy が tests/mutate.py で行う）
expect_output 0 "字列か証拠の口の無い腕 0・id の重複 0" "変異の腕の字列と証拠の口が今の版に在る（tests/mutate.py --check）" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --check
# 起動の口の reconfigure が実際に走る（呼びが在るだけの静的なチェックでは、呼びを飛ばす条件の崩れを拾えない）
expect_output 0 "字列か証拠の口の無い腕 0・id の重複 0" "tests/mutate.py: stdio を cp1252 に強制しても日本語の報告が出る" \
    env PYTHONIOENCODING=cp1252 "$PY_BIN" "$ROOT/tests/mutate.py" --check
printf '%s' '{"arms": [{"id": "x1", "title": "消えた字列", "file": "tests/mutate.py", "suite": "root", "old": "この字列はどこにも無い-7f3a", "new": "", "expect": "x"}]}' > "$WORK/arms-gone.json"
expect_output 1 "NG 腕 x1: old が 0 か所" "字列の消えた腕は --check で赤（黙って外れない）" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --check --arms-file "$WORK/arms-gone.json"
printf '%s' '{"arms": [{"id": "x2", "title": "a", "file": "tests/mutate.py", "suite": "root", "old": "def anchor_problem(", "new": "", "expect": "x"}, {"id": "x2", "title": "b", "file": "tests/mutate.py", "suite": "root", "old": "def marker_run(", "new": "", "expect": "x"}]}' > "$WORK/arms-dup.json"
expect_output 1 "NG 腕の id x2 が重複" "id の重複も --check で赤（結果を腕へ結べなくなる）" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --check --arms-file "$WORK/arms-dup.json"
printf '%s' '{"arms": [{"id": "x3", "title": "証拠の口なし", "file": "tests/mutate.py", "suite": "root", "old": "def anchor_problem(", "new": ""}]}' > "$WORK/arms-noev.json"
expect_output 1 "NG 腕 x3: expect も marker も無い" "expect も marker も持たない腕は --check で赤（赤が狙いの検査から出たかを見られない）" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --check --arms-file "$WORK/arms-noev.json"
printf '%s' '{"arms": [{"id": "x4", "title": "json の消えた値", "file": "tests/mutations.json", "suite": "root", "json": {"path": ["arms"], "remove": "この値はどこにも無い-7f3a"}, "expect": "x"}, {"id": "x5", "title": "json の消えた鍵", "file": "tests/mutations.json", "suite": "root", "json": {"path": [], "del": "この鍵はどこにも無い-7f3a"}, "expect": "x"}]}' > "$WORK/arms-json.json"
expect_output 1 "NG 腕 x5: json の 頂点 に鍵" "json の腕も、消す値・鍵が無ければ --check で赤" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --check --arms-file "$WORK/arms-json.json"
expect_output 1 "NG 腕 x4: json の arms に" "json の腕の値の消失も --check で赤" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --check --arms-file "$WORK/arms-json.json"
expect_output 1 "撃つ腕が 0 本" "絞りに当たる腕が 0 本なら撃たずに赤（0 本を合格と言わない）" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --only no-such-arm
expect_output 0 "rc=no-test" "絞った名前が台本に無い腕は赤と数えない（壊した行と無関係の exit 1 を、撃てないと言う）" \
    "$PY_BIN" -c "import sys; sys.path.insert(0, sys.argv[1]); import mutate; print('rc=' + str(mutate.run_selected(mutate.ROOT, {'graphloops/tests/simulate.py': ['no_such_test']})['rc']))" "$ROOT/tests"
# expect は JSON の \u 書き（☃）で渡す——字面のまま書くと、この行そのものが台本の本文に在って恒真になる
printf '%s' '{"arms": [{"id": "x6", "title": "古い expect", "file": "tests/mutate.py", "suite": "root", "old": "def anchor_problem(", "new": "", "expect": "\u2603\u2603\u2603\u2603 消えた検査"}]}' > "$WORK/arms-stale.json"
expect_output 1 "NG 腕 x6: expect の頭" "expect の頭が台本の本文に無い腕は --check で赤（検査の文言が変わった・消えた宣言を、撃つ前に拾う）" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --check --arms-file "$WORK/arms-stale.json"
# 頭 8 字は台本に在るが 16 字は無い expect——8 字で見ていた頃は、別の検査名と頭を共有するだけで通った
printf '%s' '{"arms": [{"id": "x8", "title": "頭だけ一致", "file": "tests/mutate.py", "suite": "root", "old": "def anchor_problem(", "new": "", "expect": "走らせない: 知\u2603\u2603\u2603\u2603\u2603\u2603\u2603\u2603"}]}' > "$WORK/arms-head.json"
expect_output 1 "NG 腕 x8: expect の頭" "expect の頭は 16 字で見る（頭 8 字だけが別の検査名と同じ宣言を拾う）" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --check --arms-file "$WORK/arms-head.json"
printf '%s' '{"arms": [{"id": "x7", "title": "撃てない腕だけ", "file": "tests/mutate.py", "suite": "root", "old": "def anchor_problem(", "new": "def anchor_problem_x(", "expect": "expect も marker も持たない腕は --check で赤", "python_max": "3.0"}]}' > "$WORK/arms-ignored.json"
expect_output 1 "撃てる腕が 0 本" "撃てる腕が 0 本（全部 python_max より新しい Python）なら、写しを走らせずに赤（0 本を合格と言わない）" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --arms-file "$WORK/arms-ignored.json"
# 当たりの証拠: expect を宣言した腕は、実際に落ちた検査（killedBy）に expect が在ることだけが証拠（印では代えない）
cat > "$WORK/mut-eval.py" <<'PYEVAL'
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
arms = [{"id": "a", "expect": "狙いの検査"}, {"id": "b", "expect": "狙いの検査"}, {"id": "c"}, {"id": "d"}, {"id": "e"}]
res = {"arms": [{"id": "a", "status": "Killed", "own": True},
                {"id": "b", "status": "Killed", "own": False},
                {"id": "c", "status": "Killed", "own": False},
                {"id": "d", "status": "Survived", "own": False},
                {"id": "e", "status": "Killed", "own": False}],
       "marker": {"placed": ["b", "c", "d"], "seen": ["b", "c"], "rc": 0}, "control": {"root": {"rc": 0}}}
s = mutate.evaluate(res, arms)
st = {r["id"]: (r["status"], bool(r["evidence"])) for r in res["arms"]}
print("no_evidence=" + ",".join(s["no_evidence"]), "d=" + st["d"][0], "a=" + str(st["a"][1]), "c=" + str(st["c"][1]))
PYEVAL
expect_output 0 "no_evidence=b,e d=NoCoverage a=True c=True" "expect を宣言した腕は別の検査の赤と印では証拠にならず、宣言しない腕は印で証拠になり、印を通らない生存は NoCoverage" \
    "$PY_BIN" "$WORK/mut-eval.py" "$ROOT/tests"
# 時間切れの腕は赤でなく『走り切らない』（壊した行と無関係の打ち切りを赤と数えない）
cat > "$WORK/mut-timeout.py" <<'PYTO'
import contextlib, pathlib, sys, tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
d = pathlib.Path(tempfile.mkdtemp()); (d / "repo" / "t").mkdir(parents=True); (d / "repo" / "t" / "f.py").write_text("x = 1\n")
leased = []
# one が写しを得る口（lease）を差し替える——差し替えが経路から外れれば leased=0 で赤
@contextlib.contextmanager
def fake_lease(tag, a=None):
    leased.append(tag)
    yield d / "repo", d
mutate.lease = fake_lease
mutate.run_group = lambda *a, **k: ("timeout", "")
r = mutate.one({"id": "t1", "title": "t", "file": "t/f.py", "suite": "root", "old": "x = 1", "new": "x = 2"})
print(f"status={r['status']} killed={r['status'] == 'Killed'} unrunnable={r.get('unrunnable')} leased={len(leased)}")
PYTO
expect_output 0 "status=Timeout killed=False unrunnable=時間切れ leased=1" "時間切れの腕は赤でなく走り切らない（Timeout）" \
    "$PY_BIN" "$WORK/mut-timeout.py" "$ROOT/tests"
# 版から変わったファイルには、未追跡の新しいファイルも入る（git diff は未追跡を出さない）
mkdir -p "$WORK/chg" && git -C "$WORK/chg" init -q && printf 'a\n' > "$WORK/chg/a.txt" && git -C "$WORK/chg" add -A \
    && git -C "$WORK/chg" -c user.name=t -c user.email=t@t commit -qm x && printf 'n\n' > "$WORK/chg/new.txt"
expect_output 0 "['new.txt']" "--changed-since は未追跡の新しいファイルも拾う" \
    "$PY_BIN" -c "import sys, pathlib; sys.path.insert(0, sys.argv[1]); import mutate; print(sorted(mutate.changed_since('HEAD', pathlib.Path(sys.argv[2]))))" "$ROOT/tests" "$WORK/chg"
# 持ち越し: 前回の結果から、赤で当たりの証拠つき・control 緑の回の腕だけを、指紋が同じときに持ち越す
cat > "$WORK/mut-reuse.py" <<'PYRU'
import json, pathlib, sys, tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
d = pathlib.Path(tempfile.mkdtemp()); (d / "f.py").write_text("x = 1\n")
a = {"id": "r1", "file": "f.py", "suite": "root", "old": "x = 1", "new": "x = 2"}
fp = mutate.fingerprint(d, a)
prev = d / "prev.json"
prev.write_text(json.dumps({"summary": {"control_ok": True}, "marker": {"rc": 0}, "arms": [
    {"id": "r1", "status": "Killed", "evidence": "印", "fingerprint": fp},
    {"id": "r2", "status": "Survived", "evidence": "", "fingerprint": fp},
    {"id": "r3", "status": "Killed", "evidence": "", "fingerprint": fp}]}))
ok = sorted(mutate.reusable(prev))
(d / "f.py").write_text("x = 3\n")
moved = mutate.fingerprint(d, a) != fp
fp2 = mutate.fingerprint(d, a)
(d / "tests").mkdir(); (d / "tests" / "run.sh").write_text("echo changed\n")
moved = moved and mutate.fingerprint(d, a) != fp2   # 台本一式（DRIVERS）が変わっても撃ち直す
prev.write_text(json.dumps({"summary": {"control_ok": False}, "marker": {"rc": 0}, "arms": [{"id": "r1", "status": "Killed", "evidence": "印", "fingerprint": fp}]}))
red_ctrl = sorted(mutate.reusable(prev))
prev.write_text(json.dumps({"summary": {"control_ok": True}, "marker": {"rc": 1}, "arms": [{"id": "r1", "status": "Killed", "evidence": "印", "fingerprint": fp}]}))
print(f"reusable={ok} moved={moved} ctrl_red={red_ctrl} marker_red={sorted(mutate.reusable(prev))}")
PYRU
expect_output 0 "reusable=['r1'] moved=True ctrl_red=[] marker_red=[]" "持ち越すのは赤で証拠つきの腕だけ・壊すファイルが変われば指紋が変わる・control か印の写しが赤の回は何も持ち越さない" \
    "$PY_BIN" "$WORK/mut-reuse.py" "$ROOT/tests"
# gate_efficacy の返答を --out の結果から組む（回す側が周ごとに使い捨ての台本を書かない）
printf '%s' '{"summary": {"control_ok": true}, "marker": {"rc": 0}, "arms": [{"id": "g1", "title": "t1", "file": "a.py", "status": "Killed", "evidence": "印 g1 が写しの出力に現れた"}, {"id": "g2", "title": "t2", "file": "a.py", "status": "Survived", "evidence": ""}]}' > "$WORK/mut-out.json"
expect_output 0 '"status": "found"' "--gate-efficacy は赤・control 緑・証拠のそろわない腕を found に数える" \
    "$PY_BIN" "$ROOT/tests/mutate.py" --gate-efficacy "$WORK/mut-out.json"
# 終了コード・--gate-efficacy・--reuse は同じ判定（proven と healthy）を使う——印の写しが赤の回・腕 0 本・撃てない腕だけの回
cat > "$WORK/mut-gate.py" <<'PYGATE'
import sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
ok = {"id": "g1", "title": "t", "file": "a.py", "status": "Killed", "evidence": "印"}
ign = {"id": "g9", "title": "t", "file": "a.py", "status": "Ignored", "evidence": ""}
st = lambda res: mutate.gate_efficacy(res)["material"]["status"]
base = {"summary": {"control_ok": True}, "marker": {"rc": 0}}
print("marker_red=" + st({**base, "marker": {"rc": 1}, "arms": [ok]}), "empty=" + st({**base, "arms": []}),
      "only_ignored=" + st({**base, "arms": [ign]}), "with_ignored=" + st({**base, "arms": [ok, ign]}),
      "rows=" + str(len(mutate.gate_efficacy({**base, "arms": [ok, ign]})["arms"])),
      "ctrl_row=" + str(mutate.gate_efficacy({**base, "marker": {"rc": 1}, "arms": [ok]})["arms"][0]["control_green"]))
PYGATE
expect_output 0 "marker_red=found empty=not_run only_ignored=not_run with_ignored=clean rows=1 ctrl_row=False" "--gate-efficacy は印の写しが赤の回を found・撃てた腕 0 本を not_run にし、撃てない腕は行に入れない（終了コードと同じ判定）" \
    "$PY_BIN" "$WORK/mut-gate.py" "$ROOT/tests"
# 返させる形の揃いは 1 本の台本で縛る——mutate.py の出力（found / clean / 撃てた腕 0 本で本体が書いた --out からの not_run）を、
# engine の型検査で graph の p1.gate_efficacy の schema に通す。形が mutate.py・graph・プロンプトで別々に決まり、0 本の not_run が
# 型（minItems: 1）で落ちていた（2026-09-24 の review-graph 3 周目）。0 本の --out は本体の main を通して作る（書かずに抜けていた）
"$PY_BIN" "$ROOT/tests/mutate.py" --only no-such-arm-7f3a --out "$WORK/mut-empty.json" >/dev/null 2>&1
cat > "$WORK/mut-gate-schema.py" <<'PYGS'
import json, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])
import mutate
from engine.schema import load_graph, validate_schema
g, why = load_graph(sys.argv[3])
sch = g["nodes"]["p1.gate_efficacy"]["schema"]
ok = {"id": "g1", "title": "t", "file": "a.py", "status": "Killed", "evidence": "印"}
bad = {"id": "g2", "title": "t", "file": "a.py", "status": "Survived", "evidence": ""}
base = {"summary": {"control_ok": True}, "marker": {"rc": 0}}
outs = {"found": mutate.gate_efficacy({**base, "arms": [ok, bad]}), "clean": mutate.gate_efficacy({**base, "arms": [ok]}),
        "not_run": mutate.gate_efficacy(json.loads(open(sys.argv[4], encoding="utf-8").read()))}
print(" ".join(f"{k}={v['material']['status']}:{len(validate_schema(v, sch))}" for k, v in outs.items()), [validate_schema(v, sch)[:1] for v in outs.values()])
PYGS
expect_output 0 "found=found:0 clean=clean:0 not_run=not_run:0" "--gate-efficacy の出力は found・clean・撃てた腕 0 本の not_run とも graph の p1.gate_efficacy の型を通る（0 本の回も本体が --out を書く）" \
    "$PY_BIN" "$WORK/mut-gate-schema.py" "$ROOT/tests" "$ROOT/graphloops" "$ROOT/graphloops/graphs/review-loop.json" "$WORK/mut-empty.json"
# 自動の腕（--auto）: 差分が足した Python の文と式から ast の 1 本の規則で作り、位置で当てる。作った変異も印の包みも構文が壊れない
cat > "$WORK/mut-auto.py" <<'PYAUTO'
import pathlib, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
src = "def f(x, y, errs):\n    if x > 1 and y:\n        raise ValueError('x')\n    errs.append(x)\n    errs += [1]\n    z = 1 if x else 2\n    if x: raise KeyError\n    w = x or y\n"
arms = mutate.auto_arms_for("graphloops/engine/x.py", src, {2, 3, 4, 5, 6, 7, 8}, every=True)   # 畳む前の全部のセクション（畳みは mut-narrow）
# graphloops/tests/ でない graphloops 配下の相対パスなら suite は graphloops のはず（graphloops/tests/run.sh を撃つ側）
assert all(a["suite"] == "graphloops" for a in arms), "graphloops 配下の相対パスから作った腕の suite が graphloops になっていない"
# or/and の項は種類のラベルだけでなく、置く値（and は True・or は False）も種類ごとに正しいはず
and_news = sorted({a["auto"]["new"] for a in arms if a["title"].startswith("and:")})
or_news = sorted({a["auto"]["new"] for a in arms if a["title"].startswith("or:")})
kinds = sorted({a["title"].split(":")[0] for a in arms})
ok = 0
for a in arms:
    x = a["auto"]
    compile(src[:x["start"]] + x["new"] + src[x["end"]:], "m", "exec")
    ok += 1
ins = [i for a in arms for i in mutate.auto_marker(src, a, pathlib.Path("/tmp/h"))]
t = src
for pos, _, _, s in sorted(ins, key=lambda x: (-x[0], x[1], x[2])):
    t = t[:pos] + s + t[pos:]
compile(t, "mk", "exec")
line2 = t.splitlines()[1]
outer = line2.index(":2:7:cond") < line2.index(":2:7:and")
mid = [a["id"] for a in arms if not mutate.auto_marker(src, a, pathlib.Path("/tmp/h"))]
sd = mutate.scratch_dir(arms[0]["id"])  # 撃つ段の作業場: id の / と : で mkdtemp が落ちない
scratch = sd.is_dir() and sd.parent.resolve() == mutate.run_root().resolve()
sd.rmdir()
print("kinds=" + ",".join(kinds), f"compiled={ok}/{len(arms)}", f"outer_first={outer}", "unmarked=" + ",".join(i.split(":", 2)[2] for i in mid),
      "anchor=" + repr(mutate.anchor_problem(mutate.ROOT, arms[0])), f"scratch={scratch}",
      f"and_new={and_news} or_new={or_news}")
PYAUTO
expect_output 0 "kinds=and,cond,ifexp,or,stmt compiled=11/11 outer_first=True unmarked=7:10:stmt anchor='' scratch=True and_new=['True'] or_new=['False']" "--auto: 条件・and/or の項・条件式・文から腕を作り、変異も印の包みも構文を壊さず、同じ位置では外側の式の印が外に来る（行の途中の文には印を差さない）。graphloops 配下の相対パスは suite も graphloops。撃つ段の作業場も id から作れる" \
    "$PY_BIN" "$WORK/mut-auto.py" "$ROOT/tests"
# 印の帰属: 印の行を『どの台本が通したか』に帰属させる書式は graphloops/tests/parallel.py が正本で、tests/mutate.py が読む。
# 同じプロセスの中はスレッドの名前、子のプロセスは作業場の名前の印（印の写しの回だけ挟む）。どちらも無い印は帰属できない（?）
cat > "$WORK/mut-owner.py" <<'PYOWN'
import os, pathlib, subprocess, sys, tempfile, threading
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import mutate, parallel
assert (parallel.TEST_THREAD, parallel.TAG) == (mutate.OWNER_THREAD, "GLT~"), "parallel.py と mutate.py の印の書式が揃っていない"
# 普段の回を見るので、印の写しの中で走る回（外側の marker_run が GL_MARK_OWNERS を立てて台本一式を回す）に継いだ値を落とす——
# 継いだまま見ると、印の写しがこの検査で赤になり、赤い印の写しの回として撃つ腕の選び方が崩れる（実測 2026-09-27: 固めた基点の印の写しの赤はこの 1 件だけ）
os.environ.pop("GL_MARK_OWNERS", None)
d = pathlib.Path(tempfile.mkdtemp())
hits = d / "hits.txt"
src = "def f(x):\n    if x:\n        return 1\n    return 0\n"
arm = mutate.auto_arms_for("graphloops/engine/x.py", src, {2})[0]
t = src
for pos, _, _, s in sorted(mutate.auto_marker(src, arm, hits), key=lambda x: (-x[0], x[1], x[2])):
    t = t[:pos] + s + t[pos:]
(d / "m.py").write_text(t + "import sys\nf(1)\n", encoding="utf-8")
seen = {}


def in_thread():
    exec(compile(t, "m", "exec"), g := {})
    g["f"](1)


# 1) 台本のスレッド（parallel.run_all が名前を付ける）の中で通った印は、その台本に帰属する。作業場の名前の印は GL_MARK_OWNERS の回だけ
def test_probe():
    in_thread()
    _td, ws = parallel.workspace("gl-probe-")
    seen["ws_plain"] = "GLT~" in ws.name
    os.environ["GL_MARK_OWNERS"] = "1"
    try:
        _td2, ws2 = parallel.workspace("gl-probe-")
        seen["ws"] = ws2
        # 2) 子のプロセスは作業場を cwd に起動すれば帰属する（呼び元は何も渡さない）
        subprocess.run([sys.executable, str(d / "m.py")], cwd=ws2, check=True)
    finally:
        del os.environ["GL_MARK_OWNERS"]


test_probe.__code__ = test_probe.__code__.replace(co_filename=str(d / "simulate.py"))
parallel.run_all([test_probe])
# 3) 作業場の外の子・台本の外のスレッドは帰属できない
subprocess.run([sys.executable, str(d / "m.py")], cwd=d, check=True)
th = threading.Thread(target=in_thread)
th.start(); th.join()
ids, cover = mutate.read_hits(hits)
(d / "red.py").write_text("print('  FAIL red-for-test')\nraise SystemExit(1)\n", encoding="utf-8")
(d / "late.py").write_text(f"import pathlib\npathlib.Path({str(d / 'late-ran')!r}).touch()\n", encoding="utf-8")
ff = mutate.run_selected(d, {"red.py": ["t"], "late.py": ["t"]}, failfast=True)
ff_stops = ff["rc"] != 0 and not (d / "late-ran").exists()
# 結果は 1 行に書く: Windows では下の見送りの行が間に入り、2 行に割った期待が続きの行として当たらなかった（実測 2026-09-26: windows-latest）
head = (f"ids={ids == [arm['id']]} cover={cover.get(arm['id'])} ws_plain={seen['ws_plain']} tagged={'GLT~simulate.py~test_probe~' in seen['ws'].name}"
        f" name_back={threading.current_thread().name == 'MainThread'}"
        # スレッドの名前だけで帰属する（作業場の印の無い cwd でも）——上の台本の印は子の作業場の印でも帰属するので、別に見る
        f" by_thread={mutate.owner_of(mutate.OWNER_THREAD + 'a.py~t', str(d)) == 'a.py~t'} ff_stops={ff_stops}")
# 止める信号の後の run_group は、起動した最中に止められた子も・その後に起動する子も『stopped』で返し、赤（Killed）と読ませない
if os.name == "posix":
    import time
    lock = parallel.creator_lock(d)   # 眠る子の寿命をこの台本に縛る（止める側が壊れた回にも子が残らない）
    rdy, got = d / "ready", {}
    th = threading.Thread(target=lambda: got.update(r=mutate.run_group(
        [sys.executable, "-c", parallel.hold_code(600, f"import pathlib; pathlib.Path({str(rdy)!r}).touch(); "), lock], cwd=d)))
    th.start()
    while th.is_alive() and not rdy.exists():
        time.sleep(0.05)
    mutate.STOPPING.set()
    mutate.stop_groups()
    th.join()
    t0 = time.monotonic()
    after = mutate.run_group([sys.executable, "-c", parallel.hold_code(600), lock], cwd=d)
    after = (after, time.monotonic() - t0 < 300)
    try:
        mutate.run_selected(d, {"x.py": ["t"]})
        raised = False
    except mutate.Stopped:
        raised = True
    # 止める信号の後に取り出された腕は、写しを作らずに Stopped で抜ける
    try:
        mutate.one({"id": "x", "title": "検査用", "file": "tests/run.sh", "suite": "root"})
        one_stopped = False
    except mutate.Stopped:
        one_stopped = True
    print(f"{head} stop={got.get('r')} after={after} raised={raised} one_stopped={one_stopped}")
else:
    print("  ok   run_group の止める信号 # SKIP process-group: posix のプロセスグループ（killpg）に頼る")
    print(f"{head} stop=('stopped', '') after=(('stopped', ''), True) raised=True one_stopped=True")
PYOWN
expect_output 0 "ids=True cover=['?', 'simulate.py~test_probe'] ws_plain=False tagged=True name_back=True by_thread=True ff_stops=True stop=('stopped', '') after=(('stopped', ''), True) raised=True one_stopped=True" "印の帰属: 台本のスレッドの中の印と、印の写しの回に台本の作業場で起動した子の印はその台本に、台本の外のスレッド・作業場の外の子の印は ? に帰属する（普段の回は作業場の名前を変えない）。止める信号の後の run_group は stopped を返し、腕は Stopped で抜ける" \
    "$PY_BIN" "$WORK/mut-owner.py" "$ROOT/tests" "$ROOT/graphloops/tests"
# Google 型の絞り（1 行 1 本・効かない行）と、行を通した台本だけで撃つ・一式での確かめ直しは --confirm-survivors の回だけ・赤の出どころ
cat > "$WORK/mut-narrow.py" <<'PYNAR'
import contextlib, pathlib, sys, tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
src = ("import logging, time\nX = 1 if time else 2\n\n\ndef f(a, b, log):\n    if a and b:\n        raise ValueError('x')\n"
       "    logging.info('hi')\n    time.sleep(0)\n    log.debug('d')\n    if a: raise KeyError\n    print('kept')\n")
lines = set(range(1, 13))
pruned = []
arms = mutate.auto_arms_for("graphloops/engine/x.py", src, lines, pruned=pruned)
every = mutate.auto_arms_for("graphloops/engine/x.py", src, lines, every=True)
per_line = {}
for x in arms:
    per_line[x["id"].split(":")[2]] = per_line.get(x["id"].split(":")[2], 0) + 1
kinds6 = [x["title"].split(":")[0] for x in arms if x["id"].split(":")[2] == "6"]
why = sorted({p["reason"].split("（")[0] for p in pruned})
arid = sorted(p["title"].split(": ")[1].split("(")[0] for p in pruned if p["reason"].startswith("効かない"))
infn = {x["id"].split(":")[2]: x["auto"]["in_function"] for x in arms}
print(f"one_per_line={max(per_line.values()) == 1} line6={kinds6} every={len(every)}>{len(arms)} pruned={len(pruned)}=={len(every) - len(arms)}"
      f" why={why} arid={arid} module_line={infn['2']} fn_line={infn['6']}")

# one の撃ち分け: 台本の走らせ方を差し替え、どちらが呼ばれたかを見る
d = pathlib.Path(tempfile.mkdtemp())
(d / "repo").mkdir()
calls = []
leased = []
@contextlib.contextmanager
def fake_lease(tag, a=None):
    leased.append(tag)
    yield d / "repo", d
mutate.lease = fake_lease
mutate.mutate = lambda repo, a: None
state = {"sel": 0, "full": 1}
mutate.run_selected = lambda repo, tests, failfast=False: calls.append(("sel", tests, failfast)) or {"rc": state["sel"], "failed": ["F sel"] if state["sel"] else [], "tail": [], "selected": True}
mutate.run_suite = lambda repo, suite, failfast=False, env=None: calls.append(("full", suite, failfast)) or {"rc": state["full"], "failed": ["F full"] if state["full"] else [], "tail": []}
base = {"id": "auto:graphloops/engine/x.py:6:7:cond", "title": "cond: a", "file": "graphloops/engine/x.py", "suite": "graphloops",
        "auto": {"start": 0, "end": 0, "new": "False", "stmt": False, "in_function": True}}
out = []
def shot(cover, in_fn=True, confirm=False, sel=0, full=1):
    calls.clear(); mutate.CONFIRM = confirm; state.update(sel=sel, full=full)
    a = {**base, "cover": cover, "auto": {**base["auto"], "in_function": in_fn}}
    r = mutate.one(a)
    return [c[0] for c in calls], r
c, r = shot(["simulate_review.py~test_b", "simulate.py~test_a"])
out.append(f"narrow={c} tests={calls[0][1]} failfast={calls[0][2]} status={r['status']} selected={r.get('selected')}")
c, r = shot(["simulate.py~test_a", "?"])
out.append(f"unknown={c}")
c, r = shot(["simulate.py~test_a"], in_fn=False)
out.append(f"module={c}")
c, r = shot(["other.py~test_z"])
out.append(f"outside={c}")
c, r = shot(["simulate.py~test_a"], confirm=True)
out.append(f"confirm={c} {r['status']} {r.get('attribution')}")
c, r = shot(["simulate.py~test_a"], sel=1)
out.append(f"red_narrow={c} {r.get('attribution')}")
c, r = shot(["?"])
out.append(f"red_full={r.get('attribution')}")
# 証拠は帰属で外さない（unrelated も印が現れていれば証拠）。記録には一覧で見える
res = {"marker": {"placed": ["u1", "g1"], "seen": ["u1", "g1"], "rc": 0}, "control": {"root": {"rc": 0}}, "pruned": [{"id": "p1"}],
       "arms": [{"id": "u1", "title": "u", "status": "Killed", "own": False, "attribution": "unrelated"},
                {"id": "g1", "title": "g", "status": "Survived", "own": False, "selected": True}]}
s = mutate.evaluate(res, [{"id": "u1"}, {"id": "g1"}])
g = mutate.gate_efficacy({**res, "summary": s})
out.append(f"evidence={bool(res['arms'][0]['evidence'])} unrelated={s['unrelated']} narrowed_green={s['narrowed_green']} pruned={s['pruned']}"
           f" note={'確かめていない' in g['arms'][1].get('note', '')} material={'pruned' in g['material'].get('detail', '')}")
out.append(f"leased={len(leased)}")
print(" ".join(out))
PYNAR
expect_output 0 "one_per_line=True line6=['cond'] every=11>5 pruned=6==6 why=['1 行 1 本', '効かない行'] arid=['log.debug', 'logging.info', 'time.sleep'] module_line=False fn_line=True
narrow=['sel'] tests={'graphloops/tests/simulate.py': ['test_a'], 'graphloops/tests/simulate_review.py': ['test_b']} failfast=True status=Survived selected=True unknown=['full'] module=['full'] outside=['full'] confirm=['sel', 'full'] Killed unrelated red_narrow=['sel'] narrowed red_full=unattributed evidence=True unrelated=['u1'] narrowed_green=['g1'] pruned=1 note=True material=True leased=7" "Google 型の絞り: 自動の腕は 1 行 1 本（cond を残す）・効かない行（ログ・待ち）は作らず pruned に理由つき（--every-node 相当で全部）。行を通した台本が全部分かる関数の中の行だけ、その台本で撃つ（? ・import の時の行・一覧の外の台本は一式）。一式の確かめ直しは --confirm-survivors の回だけで、赤の出どころは記録に残り証拠は外さない。--gate-efficacy は一式で確かめていない緑と pruned を言う" \
    "$PY_BIN" "$WORK/mut-narrow.py" "$ROOT/tests"
cat > "$WORK/mut-pytest.py" <<'PYPYT'
import json, os, pathlib, sys, tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
out = []
# 1) 起動方法の頭（版の固定）は、宣言の suite の段のどれかの頭と同じで、その段は置き場を丸ごと渡す
decl = json.loads((pathlib.Path(sys.argv[2]) / ".review-checks.json").read_text(encoding="utf-8"))
out.append("decl_bound=" + str(any(s["argv"][:len(mutate.PYTEST)] == mutate.PYTEST and s["argv"][-1] == mutate.PYDIR for s in decl["suite"])))
# 2) 撃ち方の選び方（基点に置き場のテストのファイルが 2 本）
b = pathlib.Path(tempfile.mkdtemp())
(b / mutate.PYDIR).mkdir(parents=True)
for f in ("test_a.py", "test_b.py"):
    (b / mutate.PYDIR / f).write_text("", encoding="utf-8")
mutate.base = lambda: b
auto = {"start": 0, "end": 0, "new": "False", "stmt": False, "in_function": True}
arm = lambda pc, cover=None, **k: {"id": "auto:graphloops/engine/x.py:6:7:cond", "title": "cond: a", "file": "graphloops/engine/x.py",
                                   "suite": "graphloops", "auto": {**auto, **k}, **({"pytest_cover": pc} if pc else {}),
                                   **({"cover": cover} if cover else {})}
pick = lambda *a, **k: mutate.pytest_pick(arm(*a, **k))
out.append(f"nodes={pick(['test_a.py::t1', 'test_a.py::t2'])} all_files={pick(['test_a.py::t1', 'test_b.py::u'])[1]}"
           f" long={pick(['test_a.py::t' + 'x' * 9000])} unknown={pick(['test_a.py::t1', '?'])} import={pick(['test_a.py::t1'], in_function=False)}"
           f" none={pick(None)} list={mutate.pytest_pick({'id': 'l1'})}")
# 3) pytest の赤の読み方と起動方法（node id なら -n を付けない、-x は failfast の回だけ、印の変数は子に渡さない、子は置き場を cwd に起動する）
seen = {}
def fake_group(argv, cwd, env=None, failfast=False, sub=""):
    seen.update(argv=argv, env=env, sub=sub)
    return seen["ret"]
mutate.run_group = fake_group
os.environ[mutate.PYTEST_MARK] = "?"
reads = []
for ret in ((1, "x\nFAILED test_a.py::t1 - AssertionError: y\nERROR test_b.py::u\n"), (1, "件数のチェック\n"), (2, "ERROR test_a.py\n"), (2, ""), (5, ""), (4, ""),
            (4, "ERROR test_a.py\n"), (0, "")):
    seen["ret"] = ret
    r = mutate.run_pytest(pathlib.Path("."), ["test_a.py::t1"], failfast=True)
    reads.append(f"{r['rc']}:{','.join(r['failed'])}")
del os.environ[mutate.PYTEST_MARK]
n_nodes, x_nodes, mark_env = "-n" in seen["argv"], "-x" in seen["argv"], mutate.PYTEST_MARK in seen["env"]
mutate.run_pytest(pathlib.Path("."), [mutate.WHOLE])
out.append(f"reads={reads} n_nodes={n_nodes} x={x_nodes} n_whole={seen['argv'][seen['argv'].index('-n') + 1]} x_whole={'-x' in seen['argv']}"
           f" mark_env={mark_env} sub={seen['sub']}")
# 4) one の撃ち分け: 台本と pytest の走らせ方を差し替え、呼ばれた順を見る
d = pathlib.Path(tempfile.mkdtemp())
(d / "repo").mkdir()
calls, state = [], {}
mutate.copy = lambda tag: (d / "repo", d)
mutate.mutate = lambda repo, a: None
def fake_py(repo, args, failfast=False):
    whole = args == [mutate.WHOLE]
    calls.append("pyall" if whole else "py")
    rc = state["pyall" if whole else "py"]
    return {"rc": rc, "failed": ["test_a.py::t1"] if rc == 1 else [], "tail": []}
mutate.run_pytest = fake_py
mutate.run_selected = lambda repo, tests, failfast=False: calls.append("sel") or {"rc": state["sel"], "failed": ["F sel"] if state["sel"] else [], "tail": [], "selected": True}
mutate.run_suite = lambda repo, suite, failfast=False, env=None: calls.append("full") or {"rc": state["full"], "failed": ["F full"] if state["full"] else [], "tail": []}
def shot(pc, cover=("simulate.py~test_a",), stage=True, confirm=False, py=0, pyall=0, sel=0, full=0):
    calls.clear(); mutate.PYTEST_STAGE = stage; mutate.CONFIRM = confirm; state.update(py=py, pyall=pyall, sel=sel, full=full)
    r = mutate.one(arm(pc, list(cover) if cover else None))
    return f"{'+'.join(calls)}:{r['status']}:{r.get('attribution')}"
P = ["test_a.py::t1"]
out.append("one=" + " ".join([
    shot(P, py=1),                                    # pytest が赤 → 打ち切り
    shot(["?"], pyall=1),                             # 帰属できない → pytest 一式で赤
    shot(P, sel=1),                                   # pytest が緑 → 台本の道も撃つ（台本だけが殺す腕を残す）
    shot(P),                                          # 両方緑
    shot(P, confirm=True, pyall=1),                   # 確かめ直し: 台本一式も緑 → pytest 一式で赤
    shot(P, cover=None),                              # 台本は通らない → 台本は撃たない
    shot(P, cover=None, py="no-test"),                # 台本は通らず pytest も撃てない
    shot(P, py="no-test", sel=1),                     # pytest が撃てない → 台本の道
    shot(P, stage=False, sel=1),                      # pytest の段を足さない回は今のまま
]))
calls.clear(); mutate.PYTEST_STAGE = True; mutate.CONFIRM = False; state.update(py=0, pyall=0, sel=0, full=0)
g = mutate.one(arm(P, ["simulate.py~test_a"]))
o = mutate.one(arm(P, None))
out.append(f"flags=sel:{g.get('selected')}/pysel:{g.get('pytest_selected')}/how:{g['pytest']['how']} only:{o.get('pytest_only')}/pysel:{o.get('pytest_selected')}")
# 5) evaluate: control の pytest が赤の回は、pytest の赤だけを証拠にしない（台本の赤は残し、回は健全のまま）
res = {"marker": {"placed": ["k1", "k2", "g1", "n1"], "seen": ["k1", "k2", "g1"], "script_seen": ["k1"], "pytest_seen": ["k2", "g1"], "rc": 0},
       "control": {"root": {"rc": 0}, "pytest": {"rc": 1}},
       "arms": [{"id": "k1", "title": "t", "status": "Killed", "own": False, "attribution": "narrowed"},
                {"id": "k2", "title": "t", "status": "Killed", "own": False, "attribution": "pytest"},
                {"id": "g1", "title": "t", "status": "Survived", "own": False, "pytest_only": True, "pytest_selected": True,
                 "pytest": {"how": "nodes"}},
                {"id": "n1", "title": "t", "status": "Survived", "own": False}]}
s = mutate.evaluate(res, [{"id": i} for i in ("k1", "k2", "g1", "n1")])
st = {r["id"]: (r["status"], bool(r["evidence"])) for r in res["arms"]}
gate = {x["arm"].split()[0]: x.get("note", "") for x in mutate.gate_efficacy(res)["arms"]}
out.append(f"eval={st} control_ok={s['control_ok']} py_ctl={s['pytest_control_ok']} by_pytest={s['by_pytest']} only={s['pytest_only']}"
           f" how={s['pytest_how']} pysel_green={s['pytest_narrowed_green']} narrowed_green={s['narrowed_green']}")
py_off = [("pytest の段を使っていない" in mutate.gate_efficacy(r)["material"].get("detail", "")) for r in
          ({**res, "pytest_stage": "uv が PATH に無い"}, {**res, "marker": {**res["marker"], "pytest": {"rc": 1, "why": "印の写しの pytest が緑でない"}}}, res)]
out.append(f"gate_g1={gate['g1']} gate_k2={gate['k2']} py_off={py_off}")
# 6) 持ち越しの指紋: pytest の置き場と宣言を直すと自動の腕だけ撃ち直す（node id を名指さない一覧の腕は pytest を撃たないので持ち越す）
fr = pathlib.Path(tempfile.mkdtemp())
(fr / mutate.PYDIR).mkdir(parents=True)
(fr / "x.py").write_text("x = 1\n", encoding="utf-8")
la, aa = {"id": "l1", "file": "x.py"}, {"id": "a1", "file": "x.py", "auto": dict(auto)}
fps = lambda: (mutate.fingerprint(fr, la), mutate.fingerprint(fr, aa))
f0 = fps()
(fr / mutate.PYDIR / "test_z.py").write_text("", encoding="utf-8")
f1 = fps()
(fr / ".review-checks.json").write_text("{}", encoding="utf-8")
f2 = fps()
out.append(f"fp_list_kept={f0[0] == f1[0] == f2[0]} fp_auto_moved={f0[1] != f1[1] != f2[1]}")
print("\n".join(out))
PYPYT
expect_output 0 "decl_bound=True
nodes=(['test_a.py::t1', 'test_a.py::t2'], 'nodes') all_files=files long=(['test_a.py'], 'files') unknown=(['.'], 'unknown_owner') import=(['.'], 'import_time') none=(None, 'no_cover') list=(None, 'not_auto')
reads=['1:test_a.py::t1,test_b.py::u', '1:pytest の柵（fence）が赤', '2:test_a.py', 'no-test:', 'no-test:', 'no-test:', '4:test_a.py', '0:'] n_nodes=False x=True n_whole=4 x_whole=False mark_env=False sub=graphloops/tests/py
one=py:Killed:pytest pyall:Killed:pytest_whole py+sel:Killed:narrowed py+sel:Survived:None py+sel+full+pyall:Killed:pytest_unrelated py:Survived:None py:RuntimeError:None py+sel:Killed:narrowed sel:Killed:narrowed
flags=sel:True/pysel:True/how:nodes only:True/pysel:True
eval={'k1': ('Killed', True), 'k2': ('Killed', False), 'g1': ('Survived', False), 'n1': ('NoCoverage', False)} control_ok=True py_ctl=False by_pytest=['k2'] only=['g1', 'k2'] how={'nodes': 1} pysel_green=['g1'] narrowed_green=[]
gate_g1=Survived（台本は行を通さないので撃っていない。絞った pytest だけで緑。pytest 一式では確かめていない——--confirm-survivors で確かめ直せる） gate_k2=pytest の赤だが、壊していない写しの pytest も赤（control） py_off=[True, True, False]
fp_list_kept=True fp_auto_moved=True" "pytest の段: 起動方法の頭は宣言の pytest の段と同じ版で、子は置き場を cwd にして置き場から見た node id で撃つ。行を通したテストの node id で絞り（長すぎる・全ファイルに及ぶならファイル単位、帰属できない・import の時の行は一式）、赤と読むのは rc 1 と、ERROR の行の在る rc 2・rc 4 だけ。自動の腕は pytest が赤なら打ち切り、緑・撃てないなら今の台本の道を必ず撃つ（台本が通らない行は撃たない）。確かめ直しは pytest 一式も。control の pytest が赤の回は pytest の赤だけを証拠にせず、--gate-efficacy は台本を撃っていない緑と、pytest の段が外れた回をそう言う。pytest の置き場と宣言は自動の腕の指紋にだけ入る" \
    "$PY_BIN" "$WORK/mut-pytest.py" "$ROOT/tests" "$ROOT"
# 腕の写しは版に入るファイルだけで、写しの腕の一覧は空（写しの --check が壊した字列で赤になり、生き残りを Killed と書かない）
cat > "$WORK/mut-copy.py" <<'PYCOPY'
import json, pathlib, subprocess, sys, tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
# 写しの元は自前の小さなリポジトリ（腕の一覧が空でない）——本物を元にすると、外側の実行器が既に空にした一覧を写して見分けられない
src = pathlib.Path(tempfile.mkdtemp()) / "src"
(src / "tests").mkdir(parents=True)
(src / "tests" / "mutations.json").write_text('{"arms": [{"id": "z1"}]}\n', encoding="utf-8")
(src / "tests" / "mutate.py").write_text("def anchor_problem(): pass\n", encoding="utf-8")
(src / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
(src / "ignored.txt").write_text("x\n", encoding="utf-8")
subprocess.run(["git", "init", "-q"], cwd=src, capture_output=True)
mutate.ROOT = src
seen = {}
def fake_suite(repo, suite, **_kw):
    seen["arms"] = json.loads((repo / "tests" / "mutations.json").read_text(encoding="utf-8"))["arms"]
    seen["git"] = (repo / ".git").is_dir() and not (repo / "ignored.txt").exists()
    return {"rc": 1, "failed": ["x"], "tail": []}
mutate.run_suite = fake_suite
r = mutate.one({"id": "c1", "title": "t", "file": "tests/mutate.py", "suite": "root", "old": "def anchor_problem(", "new": "def anchor_problem_x("})
print(f"arms_in_copy={len(seen['arms'])} git={seen['git']} status={r['status']}")
PYCOPY
expect_output 0 "arms_in_copy=0 git=True status=Killed" "腕の写しは腕の一覧を空にして台本を走らせ、.gitignore に当たる物は写さない（写しの --check で赤を作らない）" \
    "$PY_BIN" "$WORK/mut-copy.py" "$ROOT/tests"
# 写しの使い回し（lease）: 腕を撃った写しは基点に戻して照合し、次の腕へ渡す。前の腕の状態（壊した字列・.pyc・一時物）が次の腕に
# 漏れれば偽の赤・偽の緑になるので、漏れの道ごとに、使い回すか捨てるかを見る
cat > "$WORK/mut-lease.py" <<'PYLEASE'
import os, pathlib, subprocess, sys, tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
tempfile.tempdir = str(pathlib.Path(tempfile.mkdtemp()))
src = pathlib.Path(tempfile.mkdtemp()) / "src"
(src / "tests").mkdir(parents=True)
(src / "tests" / "mutations.json").write_text('{"arms": [{"id": "z1"}]}\n', encoding="utf-8")
(src / "a.py").write_text("X = 1\n", encoding="utf-8")
(src / "b.txt").write_text("p\n", encoding="utf-8")
(src / ".gitignore").write_text(".pytest_cache/\n__pycache__/\n", encoding="utf-8")
# 写しの台本: 前の腕の一時物が見えたら赤、a.X が 1 でなければ赤（読んだ値を出す）
py = pathlib.Path(sys.executable).as_posix()
(src / "tests" / "run.sh").write_text(
    'if [ -e "$TMPDIR/leak" ]; then echo "  FAIL leak"; exit 1; fi\n: > "$TMPDIR/leak"\n'
    f'"{py}" -c "import a, sys; a.X == 1 or print(\'  FAIL got=%d\' % a.X); sys.exit(a.X != 1)"\n', encoding="utf-8", newline="\n")
subprocess.run(["git", "init", "-q"], cwd=src, capture_output=True)
mutate.ROOT = src
arm = lambda i, f, old, new: {"id": i, "title": i, "file": f, "suite": "root", "old": old, "new": new}
# 同じファイルに同じ大きさの腕を続ける——.pyc が写しの木に残れば、2 本目は前の腕のバイトコードを読みうる（mtime の秒とサイズが同じ）
rs = [mutate.one(x) for x in (arm("a1", "a.py", "X = 1", "X = 2"), arm("a2", "a.py", "X = 1", "X = 3"), arm("a3", "b.txt", "p", "q"))]
out = [" ".join(f"{r['id']}={r['status']}:{','.join(r['killedBy']) or '-'}" for r in rs),
       f"made={mutate.COPIES['made']} reused={mutate.COPIES['reused']}"]
def after(fn):
    mutate.COPIES.clear()
    try:
        with mutate.lease("t") as (repo, d):
            fn(repo, d)
    except RuntimeError:
        pass
    k = [k for k in mutate.COPIES if k.startswith("discarded:")]
    return k[0].split(":", 1)[1].split("（")[0] if k else "kept"
git = lambda *a: (lambda repo, d: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, capture_output=True, check=True))
def boom(repo, d):
    raise RuntimeError("検査用")
def stray_proc(repo, d):
    stray_proc.p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=repo,
                                    **({"start_new_session": True} if os.name == "posix" else {}))
cases = {"stray": lambda repo, d: (repo / "stray.txt").write_text("x", encoding="utf-8"),
         "emptydir": lambda repo, d: (repo / "emptydir").mkdir(),
         "edit": lambda repo, d: (repo / "b.txt").write_text("z\n", encoding="utf-8"),
         "pytest_cache": lambda repo, d: ((repo / ".pytest_cache" / "v").mkdir(parents=True), (repo / ".pytest_cache" / "v" / "x").write_text("1")),
         "branch": git("checkout", "-q", "-b", "other"), "config": git("config", "x.y", "z"), "tag": git("tag", "t1"),
         "failfast": lambda repo, d: mutate.run_group([mutate.BASH, "-c", "echo '  FAIL x'; sleep 30"], repo, failfast=True),
         "raise": boom}
out.append(" ".join(f"{k}={after(f)}" for k, f in cases.items()))
# cwd を読む口の無い OS（Windows）は確かめない（tests/mutate.py の docstring が照合の外と書く）。実行の許可も Windows には無い
left = after(stray_proc)
stray_proc.p.kill()
mode = after(lambda repo, d: os.chmod(repo / "b.txt", 0o755))
out.append(f"lingering_ok={left.startswith('写しの置き場を cwd に') if os.name == 'posix' else True}"
           f" mode_ok={mode.startswith('写しの中身が基点と違う') if os.name == 'posix' else True}")
with mutate.lease("f"):   # 棚に使い回せる写しを 1 つ置いてから、--fresh-copy がそれを使わないことを見る
    pass
mutate.FRESH = True
mutate.COPIES.clear()
for _ in range(2):
    with mutate.lease("f"):
        pass
out.append(f"fresh_made={mutate.COPIES['made']} fresh_reused={mutate.COPIES['reused']} line={mutate.copies_line()}")
print("\n".join(out))
PYLEASE
expect_output 0 "a1=Killed:got=2 a2=Killed:got=3 a3=Survived:-
made=1 reused=2
stray=写しの中身が基点と違う emptydir=写しの中身が基点と違う edit=写しの中身が基点と違う pytest_cache=kept branch=写しの .git が作った時と違う config=写しの .git が作った時と違う tag=写しの .git が作った時と違う failfast=子のグループを殺した raise=例外か止める信号で抜けた
lingering_ok=True mode_ok=True
fresh_made=2 fresh_reused=0 line=写し: 作った 2 / 使い回した 0 / 捨てた（--fresh-copy） 2" "写しの使い回し: 腕の写しは基点に戻して次の腕へ渡し（.pyc と一時物は写しの外で腕ごとに消え、同じ大きさの腕が続いても前の腕を読まない）、余分な項目・空のディレクトリ・戻していない字列・.git の refs と config・子のグループを殺した腕・例外・残ったプロセスでは捨てる。.pytest_cache は消して使い回す。--fresh-copy は毎回作る" \
    "$PY_BIN" "$WORK/mut-lease.py" "$ROOT/tests"
# 撃ち比べ（--same-as）: 使い回しで撃った報告と、腕ごとに作り直して撃った結果を突き合わせる。撃たずに、選び方・比べ方・main の配線を見る
cat > "$WORK/mut-sameas.py" <<'PYSAME'
import json, os, pathlib, subprocess, sys, tempfile
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
ok = {"summary": {"control_ok": True, "copies": {"made": 2, "reused": 5}}, "control": {"root": {"rc": 0}}, "marker": {"rc": 0}}
row = lambda i, st, f="a.py", ev="印": {"id": i, "status": st, "file": f, "evidence": ev if st == "Killed" else ""}
# 選ばない腕（揺れうる t1・持ち越しの c1・撃てない i1・今の一覧に無い x9）を、選ぶ腕より前に置く——並びで選んでいれば当たる
prev = {**ok, "arms": [row("k1", "Killed"), row("t1", "Timeout"), {**row("c1", "Killed"), "carried": True}, row("i1", "Ignored"),
                       row("x9", "Killed"), row("s1", "Survived"), row("k2", "Killed", "b.py"), row("k3", "Killed")]}
out = [f"pick={mutate.same_as_pick(prev, {'k1', 's1', 'k2', 'k3', 'i1', 't1', 'c1'})}"]
same = {**ok, "arms": [row("k1", "Killed"), row("s1", "Survived")]}
out.append(f"same={mutate.same_as_diff(prev, same)}")
cases = {"status": {**ok, "arms": [row("k1", "Survived")]},
         "evidence": {**ok, "arms": [row("k1", "Killed", ev="")]},
         "missing": {**ok, "arms": [row("zz", "Killed")]},
         "none_shot": {**ok, "arms": [{**row("k1", "Killed"), "carried": True}]},
         "unhealthy_now": {**same, "summary": {"control_ok": False}}}
for k, res in cases.items():
    out.append(f"{k}={len(mutate.same_as_diff(prev, res))}")
for k, pv in {"partial": {**prev, "partial": True}, "no_reuse": {**prev, "summary": {"control_ok": True, "copies": {"made": 7, "reused": 0}}},
              "old_report": {**prev, "summary": {"control_ok": True}},
              "unhealthy_prev": {**prev, "summary": {"control_ok": False, "copies": {"made": 2, "reused": 5}}}}.items():
    out.append(f"{k}={len(mutate.same_as_diff(pv, same))}")
# main の配線: --same-as は FRESH を立て、--only が無ければ前の報告から選んだ腕だけを撃ち、突き合わせで終了コードを決める
src = pathlib.Path(tempfile.mkdtemp()) / "src"
(src / "tests").mkdir(parents=True)
(src / "a.py").write_text("A = 1\nB = 2\n", encoding="utf-8")
arms = [{"id": i, "title": i, "file": "a.py", "suite": "root", "old": o, "new": "Z = 0", "marker": {"where": "before"}} for i, o in (("k1", "A = 1"), ("s1", "B = 2"))]
(src / "tests" / "mutations.json").write_text(json.dumps({"arms": arms}), encoding="utf-8")
subprocess.run(["git", "init", "-q"], cwd=src, capture_output=True)
tempfile.tempdir = str(pathlib.Path(tempfile.mkdtemp()))
mutate.ROOT, mutate.ARMS_FILE = src, src / "tests" / "mutations.json"
seen = {}
def fake_shoot(a, res, fire, sel, fps, late, pend):
    seen.update(fresh=mutate.FRESH, fire=sorted(x["id"] for x in fire))
    res["arms"] += [{**row(x["id"], {"k1": "Killed", "s1": flip}[x["id"]]), "title": x["id"], "own": False, "failed": []} for x in fire]
    res["control"], res["marker"] = {"root": {"rc": 0}}, {"rc": 0, "placed": [], "seen": ["k1"], "cover": {}, "skipped": {}}
    return []
mutate.shoot = fake_shoot
rep = pathlib.Path(tempfile.mkdtemp()) / "prev.json"
rep.write_text(json.dumps({**ok, "arms": [row("k1", "Killed"), row("s1", "Survived")]}), encoding="utf-8")
codes = []
for flip in ("Survived", "Killed"):
    sys.argv = ["mutate.py", "--same-as", str(rep), "--out", str(rep.with_name("fresh.json"))]
    mutate.FRESH = False
    try:
        mutate.main()
    except SystemExit as e:
        codes.append(e.code)
out.append(f"main_fresh={seen['fresh']} fire={seen['fire']} codes={codes}")
print(" ".join(out))
PYSAME
expect_output 0 "pick=['k1', 'k3', 's1', 'k2'] same=[] status=1 evidence=1 missing=1 none_shot=1 unhealthy_now=1 partial=1 no_reuse=1 old_report=1 unhealthy_prev=1 main_fresh=True fire=['k1', 's1'] codes=[0, 1]" "撃ち比べ: 同じファイルを壊す赤の組・生き残り・赤を 4 本まで選び（持ち越し・撃てない・揺れうる腕・今の一覧に無い腕は選ばない）、status と当たりの証拠の有無が食い違う・腕が欠ける・撃てた腕が 0 本・どちらかが不健全・前の報告が途中か使い回していないなら食い違い。--same-as は腕ごとに作り直して選んだ腕だけを撃ち、一致で 0" \
    "$PY_BIN" "$WORK/mut-sameas.py" "$ROOT/tests"

cat > "$WORK/mut-root.py" <<'PYROOT'
import contextlib, io, json, os, pathlib, subprocess, sys, tempfile, time
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
T = sys.argv[1]
sys.path.insert(0, T)
import mutate
PY = sys.executable
tmp = pathlib.Path(tempfile.mkdtemp())
ctl = pathlib.Path(tempfile.mkdtemp())
env = {**os.environ, "TMPDIR": str(tmp), "TMP": str(tmp), "TEMP": str(tmp)}
head = f"import os, pathlib, sys, time\nsys.path.insert(0, {T!r})\nimport mutate\n"
live = subprocess.Popen([PY, "-c", head + f"r = mutate.run_root()\npathlib.Path({str(ctl / 'live')!r}).write_text(str(r))\n"
                         f"while not pathlib.Path({str(ctl / 'go')!r}).exists():\n    time.sleep(0.05)\n"], env=env)
t0 = time.monotonic()
while not (ctl / "live").exists() and live.poll() is None and time.monotonic() - t0 < 120:
    time.sleep(0.05)
live_root = pathlib.Path((ctl / "live").read_text())
# atexit を通らずに死んだ起動（SIGKILL と同じく後片付けが走らない）のルートと、消しかけの残り（ロックの無いルート）と、旧形式の写し
subprocess.run([PY, "-c", head + "r = mutate.run_root()\n(r / 'x').write_text('x')\nprint(r)\nos._exit(0)\n"], env=env, check=True,
               capture_output=True, text=True)
dead = [p for p in tmp.glob("mutate-run-*") if p.name.split(".")[0] != live_root.name]
(tmp / "mutate-run-zzzzzzzz").mkdir()
(tmp / "mutate-x-legacy").mkdir()
third = subprocess.run([PY, "-c", head + "print(mutate.run_root())\n"], env=env, capture_output=True, text=True, check=True)
after = {p.name for p in tmp.iterdir()}
(ctl / "go").touch()
live.wait(timeout=120)
end = {p.name for p in tmp.iterdir()}
out = [f"dead_seen={len(dead) == 2} dead_swept={not any(p.exists() for p in dead)} live_kept={live_root.name in after and live_root.name + '.lock' in after}"
       f" lockless_swept={'mutate-run-zzzzzzzz' not in after} legacy_kept={'mutate-x-legacy' in after}"
       f" exit_clean={pathlib.Path(third.stdout.strip()).name not in after} live_clean={end == {'mutate-x-legacy'}}"]
tempfile.tempdir = str(pathlib.Path(tempfile.mkdtemp()))
src = pathlib.Path(tempfile.mkdtemp()) / "src"
src.mkdir()
(src / "a.txt").write_text("old\n", encoding="utf-8")
(src / "b.py").write_text("x = 1\n", encoding="utf-8")
subprocess.run(["git", "init", "-q"], cwd=src, capture_output=True)
mutate.ROOT = src
repo, d = mutate.copy("t1")
(src / "a.txt").write_text("new\n", encoding="utf-8")
repo2, d2 = mutate.copy("t2")
probe = [PY, "-c", "import tempfile; print(tempfile.gettempdir())"]
in_copy = pathlib.Path(mutate.run_group(probe, cwd=repo)[1].strip())
outside = pathlib.Path(mutate.run_group(probe, cwd=src)[1].strip())
out.append(f"under_root={d.parent == mutate.run_root()} same_base={(repo2 / 'a.txt').read_text(encoding='utf-8') == 'old' + chr(10)}"
           f" child_tmp={in_copy.resolve() == (d / 'tmp').resolve()}"
           f" outside_tmp={outside == pathlib.Path(subprocess.run(probe, cwd=src, capture_output=True, text=True).stdout.strip())}")
real = mutate.shutil.copytree
for exc in (OSError("検査用"), mutate.Stopped(15)):
    def boom(*_a, **_k):
        raise exc
    mutate.shutil.copytree = boom
    before = set(mutate.run_root().iterdir())
    try:
        mutate.copy("t3")
        raised = None
    except BaseException as e:
        raised = type(e).__name__
    out.append(f"{raised}_left={sorted(p.name for p in set(mutate.run_root().iterdir()) - before)}")
mutate.shutil.copytree = real
# 基点を写した直後に作業ツリーを動かす（a.txt と b.py を HEAD の中身へ戻す）。assume-unchanged の印の付いた c.py は基点の前に変える
src = pathlib.Path(tempfile.mkdtemp()) / "src2"
src.mkdir()
git = lambda *a: subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t", *a], capture_output=True, check=True)
for name, body in (("a.txt", "orig\n"), ("b.py", "x = 1\n"), ("c.py", "y = 1\n")):
    (src / name).write_text(body, encoding="utf-8")
git("init", "-q"); git("add", "-A"); git("commit", "-qm", "x"); git("update-index", "--assume-unchanged", "c.py")
(src / "a.txt").write_text("changed\n", encoding="utf-8")
(src / "b.py").write_text("x = 1\nif x:\n    f()\n", encoding="utf-8")
(src / "c.py").write_text("y = 1\ng()\n", encoding="utf-8")
real_index = (src / ".git" / "index").read_bytes()
mutate.ROOT = src
real_git = mutate.base_git
def moving_git():
    (src / "a.txt").write_text("orig\n", encoding="utf-8")
    (src / "b.py").write_text("x = 1\n", encoding="utf-8")
    return real_git()
mutate.base_git = moving_git
fired = []
def fake_shoot(_a, res, fire, sel, fps, late, pend):
    fired.extend(x["id"] for x in fire)
    res["control"] = {"root": {"rc": 0}}
    res["marker"] = {"rc": 0, "failed": [], "tail": [], "placed": [], "seen": [], "cover": {}, "skipped": {}}
    return []
mutate.shoot = fake_shoot
arms = pathlib.Path(tempfile.mkdtemp()) / "arms.json"
arms.write_text('{"arms": [{"id": "l1", "title": "l", "file": "a.txt", "suite": "root", "old": "changed", "new": "x", "marker": {"where": "at"}}]}',
                encoding="utf-8")
rep_out = arms.with_name("out.json")
sys.argv = ["mutate.py", "--arms-file", str(arms), "--auto", "HEAD", "--changed-since", "HEAD", "--out", str(rep_out)]
err = io.StringIO()
try:
    with contextlib.redirect_stderr(err):
        mutate.main()
    code = None
except SystemExit as e:
    code = e.code
got = json.loads(rep_out.read_text(encoding="utf-8"))
out.append(f"moved_code={code} fired={sorted(fired)} worktree_moved={got.get('worktree_moved')} moved_named={'b.py' in err.getvalue()}"
           f" real_index_kept={(src / '.git' / 'index').read_bytes() == real_index}")
print(" ".join(out))
PYROOT
expect_output 0 "dead_seen=True dead_swept=True live_kept=True lockless_swept=True legacy_kept=True exit_clean=True live_clean=True under_root=True same_base=True child_tmp=True outside_tmp=True OSError_left=[] Stopped_left=[] moved_code=1 fired=['auto:b.py:2:3:cond', 'auto:b.py:3:4:stmt', 'auto:c.py:2:0:stmt', 'l1'] worktree_moved=['a.txt', 'b.py'] moved_named=True real_index_kept=True" "写しのルート: 次の起動はロックの解けたルートとロックの無いルートだけを消し、生きたルート・旧形式の写しは触らない。写しは基点から作り、作る途中の例外・止める信号で置き場を残さず、写しの中の子だけ TMPDIR を作業場の下に向ける。--auto・--changed-since の差分と字列の検査は基点から取り（assume-unchanged の印も見ずに、本物の index は書かない）、基点の後に動いた作業ツリーは止めずに worktree_moved に残す" \
    "$PY_BIN" "$WORK/mut-root.py" "$ROOT/tests"

cat > "$WORK/mut-red.py" <<'PYRED'
import pathlib, sys, types
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate
out = []
mutate.control = lambda suites, selected=None: {"root": {"rc": 0, "failed": [], "tail": []}}
mutate.one = lambda x: {"id": x["id"], "title": x["title"], "status": "Survived", "own": False, "rc": 0, "failed": [], "killedBy": [], "tail": []}
auto = {"start": 0, "end": 1, "new": "False", "stmt": False, "in_function": True}
for rc in (2, 0):
    mutate.marker_run = lambda arms, rc=rc: {"rc": rc, "failed": [], "tail": [], "placed": ["a1", "a2"], "seen": ["a1"],
                                             "cover": {"a1": ["simulate.py~test_a"]}, "skipped": {}}
    fire = [{"id": i, "title": i, "file": "f.py", "suite": "root", "auto": dict(auto)} for i in ("a1", "a2")]
    res = {"schemaVersion": "1", "arms": [], "pruned": []}
    mutate.shoot(types.SimpleNamespace(j=1, out=None), res, list(fire), fire, {"a1": "f", "a2": "f"}, lambda: False, lambda xs: [])
    s = mutate.evaluate(res, fire)
    st = {r["id"]: r["status"] for r in res["arms"]}
    g = mutate.gate_efficacy(res)
    a2 = next(x for x in g["arms"] if x["arm"].startswith("a2"))
    out.append(f"rc{rc}: a1={st['a1']} a2={st['a2']} unrunnable={s['unrunnable']} unhealthy={'marker_unhealthy' in res}"
               f" note={'印の写しが赤' in a2.get('note', '')} healthy={mutate.healthy(res)}")
# 撃った腕の Survived も、印の写しが赤の回は NoCoverage に書き換えない
for rc in (2, 0):
    res = {"marker": {"placed": ["m1"], "seen": [], "rc": rc}, "control": {"root": {"rc": 0}},
           "arms": [{"id": "m1", "title": "m", "status": "Survived", "own": False}]}
    mutate.evaluate(res, [{"id": "m1"}])
    out.append(f"eval_rc{rc}={res['arms'][0]['status']}")
# 通ったが台本一式で撃つ腕の理由別の数と、差せない腕の数
au = lambda i, **k: {"id": i, "auto": {**auto, **k}}
sel = [au("n1"), au("u1"), au("i1", in_function=False), au("o1"), au("h1"), au("z1"), {"id": "l1"}]
cover = {"n1": ["simulate.py~test_a"], "u1": ["?"], "i1": ["simulate.py~test_a"], "o1": ["other.py~test_b"], "z1": ["simulate.py~test_a"]}
for x in sel:
    if x["id"] in cover:
        x["cover"] = cover[x["id"]]
res = {"marker": {"placed": [x["id"] for x in sel[:6]] + ["s1"], "seen": ["n1", "u1", "i1", "o1", "l1"], "rc": 0, "skipped": {"s1": "式の途中の行"}},
       "control": {"root": {"rc": 0}}, "arms": []}
s = mutate.evaluate(res, sel)
out.append(f"why={s['whole_suite_why']} unplaced={s['unplaced']}")
body = "  ok   a\n  FAIL b — x\n  line after\n  ok   c\nTraceback (most recent call last):\nZeroDivisionError\n"
mutate.run_group = lambda argv, cwd, env=None, failfast=False: (1, body)
r = mutate.run_suite(pathlib.Path("."), "root", detail=True)
plain = mutate.run_suite(pathlib.Path("."), "root")
f = r["detail"]["fails"]
out.append(f"detail={f[0]['line'] == 'FAIL b — x' and f[0]['after'] == ['  line after'] and r['detail']['end'][-1] == 'ZeroDivisionError'}"
           f" plain_no_detail={'detail' not in plain}")
print(" ".join(out))
PYRED
expect_output 0 "rc2: a1=Survived a2=Pending unrunnable=['a2'] unhealthy=True note=True healthy=False rc0: a1=Survived a2=NoCoverage unrunnable=[] unhealthy=False note=False healthy=True eval_rc2=Survived eval_rc0=NoCoverage why={'import_time': 1, 'outside_scripts': 1, 'unknown_owner': 1} unplaced=1 detail=True plain_no_detail=True" "印の写しが赤の回は、通らなかった自動の腕を撃たずに Pending（unrunnable に理由）にし、NoCoverage に書き換えない（緑の回は今のまま）。理由は marker_unhealthy に、赤の本文は detail に残る。通ったが台本一式で撃つ腕は理由別に、差せない腕は数で summary に出る" \
    "$PY_BIN" "$WORK/mut-red.py" "$ROOT/tests"

# auto_targets の差分読み: git そのものを差し替えて、数え無し／数え有りの @@ 見出し・削除だけの見出し・
# +++ /dev/null（cur 無し）の後の見出し・diff には出るがディスクに無いファイル・未追跡の新しい .py は全行・
# tests/ 配下の除外（tests/mutate.py だけは例外）・空白だけの名前・git 自体の失敗（None を返す）を 1 本で見る。
# 実物の git repo でなく subprocess.run を差し替えるのは、実物の git では作れない組み合わせ
# （+++ /dev/null の直後に件数を騙る見出し）まで狙って直に投げるため。
cat > "$WORK/mut-auto-targets.py" <<'PYAT'
import pathlib, sys, tempfile
from types import SimpleNamespace
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate

root = pathlib.Path(tempfile.mkdtemp())
(root / "one.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
(root / "many.py").write_text("a=1\nb=2\nc=3\nd=4\ne=5\n", encoding="utf-8")
(root / "whole.py").write_text("p=1\nq=2\np2=3\n", encoding="utf-8")
(root / "empty_add.py").write_text("x = 1\n", encoding="utf-8")
(root / "tests").mkdir()
(root / "tests" / "skip.py").write_text("q = 1\n", encoding="utf-8")
(root / "tests" / "mutate.py").write_text("# dummy\n", encoding="utf-8")
# 空白だけの行を strip すると空になる名前。全角空白 1 字にするのは、Windows が末尾の空白（U+0020）を名前に持てず、
# ASCII の空白だけの名前は作れないため（実測 2026-09-26: windows-latest で PermissionError）。U+3000 は str.strip() が落とす
BLANK = "\u3000"
(root / BLANK).write_text("blank name\n", encoding="utf-8")

DIFF = """diff --git a/one.py b/one.py
--- a/one.py
+++ b/one.py
@@ -1,0 +2 @@ x = 1
+y = 2
diff --git a/many.py b/many.py
--- a/many.py
+++ b/many.py
@@ -3,0 +4,2 @@ c = 3
+d = 4
+e = 5
diff --git a/empty_add.py b/empty_add.py
--- a/empty_add.py
+++ b/empty_add.py
@@ -3,1 +3,0 @@
-old line
diff --git a/phantom.py b/phantom.py
--- a/phantom.py
+++ b/phantom.py
@@ -1,0 +2 @@
+z = 1
diff --git a/tests/mutate.py b/tests/mutate.py
--- a/tests/mutate.py
+++ b/tests/mutate.py
@@ -10,0 +11,2 @@ def x():
+p = 1
+q = 2
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1 +5,3 @@
-z = 1
"""


def fake_run(argv, **kw):
    if argv[5] == "diff":
        return SimpleNamespace(returncode=0, stdout=DIFF)
    if argv[5] == "ls-files":
        return SimpleNamespace(returncode=0, stdout=f"whole.py\ntests/skip.py\nghost.py\n{BLANK}\n")
    raise AssertionError(f"想定外の git 呼び出し: {argv}")


mutate.subprocess.run = fake_run
tg = mutate.auto_targets("HEAD", root=root)
whole_n = (root / "whole.py").read_text(encoding="utf-8").count("\n") + 1
assert tg["one.py"] == {2}, f"数え無しの @@ 見出しが 1 行だけを拾えていない: {tg.get('one.py')}"
assert tg["many.py"] == {4, 5}, f"数え有りの @@ 見出しが複数行を拾えていない: {tg.get('many.py')}"
assert tg["tests/mutate.py"] == {11, 12}, f"tests/mutate.py 自身は tests/ の除外の例外のはずが: {tg.get('tests/mutate.py')}"
assert "gone.py" not in tg, "+++ /dev/null（cur 無し）の後の見出しの件数を、消えたファイルの行として拾ってしまった"
assert "empty_add.py" not in tg, "足す行が 0 本の見出し（削除だけ）を腕の対象に残してしまった"
assert "phantom.py" not in tg, "diff には出るがディスクに無いファイルを対象に残してしまった（is_file のチェック）"
assert tg["whole.py"] == set(range(1, whole_n + 1)), f"未追跡の新しい .py は全行のはずが: {tg.get('whole.py')}"
assert "tests/skip.py" not in tg, "tests/ 配下の未追跡 .py が対象から除外されていない"
assert "ghost.py" not in tg, "ls-files には出るがディスクに無い未追跡ファイルを対象に残してしまった（is_file のチェック）"
assert BLANK not in tg, "空白だけの名前（strip すると空）を対象に残してしまった"


def fail_diff(argv, **kw):
    if argv[5] == "diff":
        return SimpleNamespace(returncode=1, stdout="")
    return SimpleNamespace(returncode=0, stdout="")


mutate.subprocess.run = fail_diff
assert mutate.auto_targets("HEAD", root=root) is None, "git diff が失敗した回で None を返さない"


def fail_ls(argv, **kw):
    if argv[5] == "diff":
        return SimpleNamespace(returncode=0, stdout="")
    return SimpleNamespace(returncode=1, stdout="")


mutate.subprocess.run = fail_ls
assert mutate.auto_targets("HEAD", root=root) is None, "git ls-files が失敗した回で None を返さない"
print("AUTO_TARGETS_OK")
PYAT
expect_output 0 "AUTO_TARGETS_OK" "auto_targets: 数え無し・数え有りの @@ 見出し、削除だけの見出しは対象外、+++ /dev/null の後の見出しも対象外、diff には出るがディスクに無いファイルも対象外、未追跡の新しい .py は全行、tests/ 配下は未追跡でも対象外（tests/mutate.py だけ例外）、git 自体が失敗すれば None" \
    "$PY_BIN" "$WORK/mut-auto-targets.py" "$ROOT/tests"

# run_group: 時間切れでグループごと殺す・標準出力が先に閉じても子の終了を待つ（p.wait）・failfast は
# 最初の「  FAIL 」の行だけで止めて rc を 1 にする（NO_TEST を含む行は対象外）・failfast=False では
# 止めない・timer.cancel が効いて通常終了の後に時間切れの kill を撃たない、を実物の子プロセスで見る。
cat > "$WORK/mut-rungroup.py" <<'PYRG'
import os, sys, tempfile, time
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
sys.path.insert(0, sys.argv[1])
import mutate

# Windows の分岐が taskkill に渡す argv を、どの OS でも見る: mutate の os と subprocess だけを差し替え（モジュールそのものは
# 書き換えない）、止める信号の後に起動した子へ run_group が送る語を記録する。本物の木が止まるかは Windows の実機の CI が見る
import subprocess, types
sent, born = [], []


class Recorded(subprocess.Popen):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        born.append(self.pid)


real_os, real_sp = mutate.os, mutate.subprocess
mutate.os = types.SimpleNamespace(name="nt")
mutate.subprocess = types.SimpleNamespace(**{**vars(subprocess), "Popen": Recorded,
                                            "run": lambda argv, **k: sent.append(argv)})
mutate.STOPPING.set()
try:
    got = mutate.run_group([sys.executable, "-c", "pass"], cwd=tempfile.gettempdir())
finally:
    mutate.os, mutate.subprocess = real_os, real_sp
    mutate.STOPPING.clear()
assert got == ("stopped", "") and sent == [["taskkill", "/T", "/F", "/PID", str(born[0])]], f"Windows の分岐の止め方: {got} {sent} {born}"

if os.name != "posix":
    print("  ok   run_group の腕 # SKIP process-group: この腕の時間切れと failfast の止め方は posix のプロセスグループ（killpg）で組んである（Windows の taskkill /T が本物の木を止めるかは実機で確かめていない。渡す argv は上で見た）")
    print("RUNGROUP_OK")
    sys.exit(0)

root = tempfile.mkdtemp()
import pathlib
GL_TESTS = pathlib.Path(sys.argv[1]).resolve().parent / "graphloops" / "tests"
sys.path.insert(0, str(GL_TESTS))
import parallel
lock = parallel.creator_lock(root)   # 下で起動する眠る子の寿命をこの台本に縛る


def gone(pid, within=30):
    """居なくなったか（回収待ちのゾンビも居ないと数える）。止まった子の消滅は非同期なので数え直す"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < within:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        if not st or st.startswith("Z"):
            return True
        time.sleep(0.1)
    return False


# 変異の腕が赤で台本を止める回（failfast のグループへの SIGKILL）: 台本の後始末（finally・ExitStack）は走らず、グループや
# セッションを抜けた固定具の子に killpg は届かない。固定具の子の寿命を台本の生存に縛る 2 つの形（台本が握るロックを待つ
# parallel.hold_code と、台本が握る標準入力の管の EOF）なら、台本が消えた時点で子も孫も終わる
pids, own = pathlib.Path(root) / "fixture.pids", pathlib.Path(root) / "creator"
own.mkdir()   # 台本のロックは自分の置き場に（この台本が root に握るロックと別の物）
creator = f"""import os, subprocess, sys, time
sys.path.insert(0, {str(GL_TESTS)!r})
import parallel
lock = parallel.creator_lock({str(own)!r})
a = subprocess.Popen([sys.executable, "-c", parallel.hold_code(600, "os.setsid(); "), lock], stdout=subprocess.DEVNULL)
b = subprocess.Popen([sys.executable, "-c", "import os, subprocess, sys; os.setsid(); g = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()']); print(g.pid, flush=True); sys.stdin.read()"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
g = b.stdout.readline().strip()
open({str(pids)!r}, "w").write(f"{{a.pid}} {{b.pid}} {{g}}")
print("  FAIL 固定具の子と孫を起動した台本", flush=True)
time.sleep(600)
"""
rc, out = mutate.run_group([sys.executable, "-c", creator], cwd=root, failfast=True)
left = [int(x) for x in pids.read_text(encoding="utf-8").split()]
assert rc == 1 and len(left) == 3 and all(gone(x) for x in left), f"SIGKILL で消えた台本の固定具の子が残った: rc={rc} {left}"

# **時計に頼らない。** 本物の threading.Timer と固定の短い上限（0.1〜2 秒）で見ていたとき、機械の負荷で子の起動が
# 遅れると上限を越えて赤くなった（実測 2026-09-25: load average 60〜112 の下で、この台本だけが差分と無関係に赤）。
# 時間切れの仕掛けは偽の Timer に差し替え、発火は台本が決める（run_group は関数の中で import threading するので、
# モジュールの属性を差し替えれば効く）。偽物は本物の Timer を作らないので、timer.cancel が抜けた写しでも
# 生き残った Timer が検査を止めることも、古い pid に killpg を撃つことも無い
import threading
timers = []


class FakeTimer:
    """start と cancel を記録する。fire=True なら start の直後に別スレッドで一度だけ発火する（子は起動した後）"""
    fire = False

    def __init__(self, interval, fn):
        self.fn, self.cancelled, self.started = fn, False, False
        timers.append(self)

    def start(self):
        self.started = True
        if FakeTimer.fire:
            threading.Thread(target=self.fn, daemon=True).start()

    def cancel(self):
        self.cancelled = True


threading.Timer = FakeTimer

# 時間切れ: 発火する偽の Timer で、60 秒眠る子をグループごと殺して ("timeout", "") を返す。殺せていなければ
# p.wait が子の自然終了（60 秒）まで返らないので、その半分より十分早く返ったことで殺したと言える
FakeTimer.fire = True
t0 = time.time()
rc, out = mutate.run_group([sys.executable, "-c", parallel.hold_code(60), lock], cwd=root)
dt = time.time() - t0
assert (rc, out) == ("timeout", ""), f"時間切れが (\"timeout\", \"\") でない: {(rc, out)!r}"
assert dt < 30, f"時間切れの後に子の自然終了まで待った（{dt:.2f}s）——グループを殺せていない疑い"
FakeTimer.fire = False

# p.wait(): 標準出力を先に閉じても、子が本当に終わるまで待って終了コードを取る（下限だけを見るので負荷では落ちない）
child_close = "import sys, os, time\nsys.stdout.write('hi\\n'); sys.stdout.flush(); os.close(1)\ntime.sleep(0.3)\nsys.exit(7)\n"
t0 = time.time()
rc, out = mutate.run_group([sys.executable, "-c", child_close], cwd=root)
dt = time.time() - t0
assert rc == 7, f"標準出力が先に閉じた子の終了コードを取れていない（p.wait が抜けている疑い）: rc={rc!r}"
assert dt >= 0.25, f"子の終了を待たずに返った（p.wait が抜けている疑い）: {dt:.2f}s"

# failfast: 最初の「  FAIL 」の行だけを見てグループごと止め、rc は子の終了コードでなく 1
child_fail = "print('  FAIL real')\nprint('should not appear')\nimport sys; sys.exit(3)\n"
rc, out = mutate.run_group([sys.executable, "-c", child_fail], cwd=root, failfast=True)
assert rc == 1, f"failfast で止めた回の rc は 1 のはずが: {rc!r}（子の終了コードをそのまま返している疑い）"
assert "should not appear" not in out, "failfast が最初の FAIL 行で止まっていない（後の行まで読んでいる）"
assert "  FAIL real" in out, "failfast で止める前に、当の FAIL 行自体を読み損ねている"

# failfast=False なら「  FAIL 」の行が在っても止めず、子の終了コードをそのまま返す
child_nofail = "print('  FAIL not stopped')\nprint('more output')\nimport sys; sys.exit(4)\n"
rc, out = mutate.run_group([sys.executable, "-c", child_nofail], cwd=root, failfast=False)
assert rc == 4, f"failfast=False なのに rc が子の終了コードでない: {rc!r}"
assert "more output" in out, "failfast=False なのに FAIL 行で止まった（failfast の判定に懸かっていない）"

# NO_TEST を含む「  FAIL 」行は「壊した行と無関係の拒否」なので failfast の対象にしない
child_notest = f"print('  FAIL ' + {mutate.NO_TEST!r})\nprint('second line')\nimport sys; sys.exit(0)\n"
rc, out = mutate.run_group([sys.executable, "-c", child_notest], cwd=root, failfast=True)
assert rc == 0, f"NO_TEST を含む FAIL 行で誤って止めた（rc が子の終了コードでない）: rc={rc!r}"
assert "second line" in out, "NO_TEST を含む FAIL 行で誤って早期に止めた（後の行を読んでいない）"

# timer.cancel(): 通常終了のあとに、時間切れ用の Timer を取り消す（生き残ると後から kill を撃つ）。
# **時間の源を差し替えて見る**（unittest.mock.patch）——本物の Timer と短い窓で見ていたとき、負荷の高い機械では子の
# 起動が窓より遅れて Timer が先に撃ち、通常終了が timeout に倒れて赤になった（実測 2026-09-25: 負荷 88〜102 で 8 回中 6 回）
import threading
from unittest import mock
with mock.patch.object(threading, "Timer") as timer_cls:
    rc, out = mutate.run_group([sys.executable, "-c", "print('quick')"], cwd=root)
assert rc == 0, f"通常終了の rc が 0 でない: {rc!r}"
timer = timer_cls.return_value
assert timer.start.called, "時間切れ用の Timer を起動していない（差し替えが run_group に届いていない疑い）"
assert timer.cancel.called, "timer.cancel() が呼ばれず、通常終了の後に時間切れの kill が撃てる形で残る"

print("RUNGROUP_OK")
PYRG
expect_output 0 "RUNGROUP_OK" "run_group: Windows の分岐は taskkill /T /F /PID <子> を送る・時間切れでグループごと殺す・標準出力が先に閉じても子の終了を待つ・failfast は最初の FAIL 行だけで rc を 1 にする（NO_TEST を含む行や failfast=False では止めない）・timer.cancel が通常終了後の時間切れ kill を防ぐ" \
    "$PY_BIN" "$WORK/mut-rungroup.py" "$ROOT/tests"

# 自動の腕（--auto）の本命: 使い捨ての小さな git repo を tests/mutate.py の写しごと作り、base から
# 見て「if を割ると検査が拾う行」「if を割っても誰も拾わない行」「誰も通らない行」「未追跡の新しい
# .py」を足して撃つ。一覧の通常の腕（expect 持ち・marker 持ち）も同じ回で --files / --only /
# --changed-since を通す。差分 0 本・存在しない rev・--gate-efficacy も同じ写しの上で見る。
cat > "$WORK/mut-auto-e2e.py" <<'PYE2E'
import json, pathlib, shlex, subprocess, sys, tempfile

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

REAL_TESTS = pathlib.Path(sys.argv[1])
PY = sys.executable

mini = pathlib.Path(tempfile.mkdtemp()) / "mini"
mini.mkdir()
(mini / "tests").mkdir()


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(mini), *args], capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} が失敗: {r.stderr}")
    return r


def w(rel, text):
    # bash が読む台本も書くので、Windows の text モードの改行の変換（\n → \r\n）を通さない
    p = mini / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


# --- BASE 状態: calc.py はしきい値と classify だけ。run.sh は classify の検査だけ ---
w("calc.py", "THRESHOLD = 0\n\n\ndef classify(n):\n    if n > THRESHOLD:\n        return \"pos\"\n    return \"non-pos\"\n")
w("tests/mutate.py", (REAL_TESTS / "mutate.py").read_text(encoding="utf-8"))
w("tests/mutations.json", json.dumps({"arms": [
    {"id": "norm1", "title": "しきい値を壊す", "file": "calc.py", "suite": "root",
     "old": "THRESHOLD = 0", "new": "THRESHOLD = 999", "expect": "classify は閾値超えで pos"},
    # expect でなく marker で証拠を持つ通常の腕（marker_run の通常腕の分岐 = auto でない a.get("marker") の側を通す）
    {"id": "norm2", "title": "pos の値をすり替える", "file": "calc.py", "suite": "root",
     "old": 'return "pos"', "new": 'return "WRONG"', "marker": {"where": "before"}},
]}, ensure_ascii=False))
w("tests/check_classify.py",
  "import sys, pathlib\n"
  "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
  "import calc\n"
  "sys.exit(0 if calc.classify(5) == \"pos\" else 1)\n")


def run_sh(checks):
    body = "#!/usr/bin/env bash\nset -uo pipefail\nROOT=\"$(cd \"$(dirname \"$0\")/..\" && pwd)\"\n" \
           f"PY={shlex.quote(PY)}\nfail=0; ran=0\n" \
           "check() {\n  local desc=\"$1\"; shift\n  \"$@\" >/dev/null 2>&1\n  local rc=$?\n" \
           "  ran=$((ran+1))\n  if [ \"$rc\" = 0 ]; then\n    echo \"  ok   $desc\"\n  else\n" \
           "    echo \"  FAIL $desc\"\n    fail=1\n  fi\n}\n"
    for desc, script in checks:
        body += f'check "{desc}" "$PY" "$ROOT/tests/{script}"\n'
    body += 'if [ "$fail" = 0 ]; then\n  echo "$ran 件すべて緑"\nelse\n  echo "$ran 件のうち失敗あり"\nfi\nexit "$fail"\n'
    return body


w("tests/run.sh", run_sh([("classify は閾値超えで pos", "check_classify.py")]))

git("init", "-q")
git("-c", "user.name=m", "-c", "user.email=m@m", "add", "-A")
git("-c", "user.name=m", "-c", "user.email=m@m", "commit", "-qm", "base")
BASE = git("rev-parse", "HEAD").stdout.strip()

MUT = str(mini / "tests" / "mutate.py")


def run_mutate(*args, out=None):
    cmd = [PY, MUT, *args]
    if out:
        cmd += ["--out", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=mini, timeout=120)
    return r


# --- (2) 絞りに当たる一覧の腕も、--auto <rev> の Python の差分も 0 本 ---
empty_out = mini / "empty.json"
r = run_mutate("--only", "no-such-arm-7f3a", "--auto", BASE, out=empty_out)
assert r.returncode == 1, f"差分 0 本のはずが exit {r.returncode}: {r.stdout}{r.stderr}"
assert "撃つ腕が 0 本" in r.stderr, f"0 本の理由がエラーに出ていない: {r.stderr!r}"
empty_doc = json.loads(empty_out.read_text(encoding="utf-8"))
assert empty_doc["arms"] == [] and "empty" in empty_doc, f"--out に空の結果が書かれていない: {empty_doc}"

# 絞り（--only）を添えると、同じ「差分 0 本」の rev でも auto 専用の「0 本」判定はバイパスされ、
# 絞りが選んだ通常の腕（norm1）だけで撃つ（filtered が立っているときは autos の空を理由に止めない）
r = run_mutate("--only", "norm1", "--auto", BASE)


def direct_run():
    """写しの台本を実行器と同じ起動方法（SUITES と run_group）で走らせた終了コードと出力の頭。実行器の要約は『件失敗』などの
    行しか拾わず、bash が起きない・台本を読み違える回の理由が見えないので、赤の回の切り分けに添える（assert の文の中でだけ
    呼ぶ）。run_group を通すので、止まらない台本も実行器と同じ時間切れと木ごとの止め方で止まる"""
    sys.path.insert(0, str(REAL_TESTS))
    import mutate as real
    rc, out = real.run_group(real.SUITES["root"], mini)
    return f"写しの台本を直接: rc={rc} 出力の頭 {out[:600]!r}"


assert r.returncode == 0, f"絞りが在るのに auto の 0 本判定に止められた: exit {r.returncode}: {r.stdout}{r.stderr} / {direct_run()}"
assert "撃つ腕が 0 本" not in r.stderr, f"絞りが在るのに auto の 0 本エラーが出た: {r.stderr!r}"

# --- (3) --auto に存在しない rev ---
r = run_mutate("--auto", "not-a-real-rev-zzz999")
assert r.returncode == 2, f"存在しない rev のはずが exit {r.returncode}: {r.stdout}{r.stderr}"
assert "git diff が取れない" in r.stderr, f"取れない理由がエラーに出ていない: {r.stderr!r}"

# --- ここから差分を足す（BASE から見て未コミット）: if の生き死にが割れる 3 本 + 未追跡の 1 ファイル ---
calc_ext = (
    "\n\n"
    "def guard(n):\n"
    "    if n < 0:\n"
    "        raise ValueError(\"negative\")\n"
    "    return n\n"
    "\n\n"
    "def loud_but_uncaught(n):\n"
    "    if n > 100:\n"
    "        return \"big\"\n"
    "    return \"small\"\n"
    "\n\n"
    "def dead_code(n):\n"
    "    \"\"\"誰も呼ばない（裸の式の文は腕にしない）\"\"\"\n"
    "    if n == 42:\n"
    "        return \"meaning\"\n"
    "    return \"none\"\n"
    "\n\n"
    "def seven(n):\n"
    "    if n == 7: raise ValueError(\"seven\")\n"
    "    return n\n"
)
with (mini / "calc.py").open("a", encoding="utf-8", newline="\n") as f:
    f.write(calc_ext)
w("extra.py", "def add_one(n):\n    if n is None:\n        raise ValueError(\"n required\")\n    return n + 1\n")
w("tests/check_guard1.py",
  "import sys, pathlib\n"
  "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
  "import calc\n"
  "try:\n    calc.guard(-1)\nexcept ValueError:\n    sys.exit(0)\nsys.exit(1)\n")
w("tests/check_guard2.py",
  "import sys, pathlib\n"
  "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
  "import calc\n"
  "try:\n    calc.guard(-2)\nexcept ValueError:\n    sys.exit(0)\nsys.exit(1)\n")
w("tests/check_loud.py",
  "import sys, pathlib\n"
  "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
  "import calc\n"
  "calc.loud_but_uncaught(200)\n"
  "sys.exit(0)\n")
w("tests/check_extra.py",
  "import sys, pathlib\n"
  "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
  "import extra\n"
  "try:\n    extra.add_one(None)\nexcept ValueError:\n    sys.exit(0)\nsys.exit(1)\n")
w("tests/check_seven.py",
  "import sys, pathlib\n"
  "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"
  "import calc\n"
  "try:\n    calc.seven(7)\nexcept ValueError:\n    sys.exit(0)\nsys.exit(1)\n")
w("tests/run.sh", run_sh([
    ("classify は閾値超えで pos", "check_classify.py"),
    ("seven(7) は例外", "check_seven.py"),
    ("guard(-1) は例外", "check_guard1.py"),
    ("guard(-2) は例外", "check_guard2.py"),
    ("loud_but_uncaught は落ちない", "check_loud.py"),
    ("add_one(None) は例外", "check_extra.py"),
]))

# --- (1) 本命: --files で通常の腕（norm1）も選び、--auto で足した行から機械の腕も作って、まとめて 1 回で撃つ ---
r_out = mini / "r.json"
r = run_mutate("-j", "2", "--files", "calc.py", "--auto", BASE, out=r_out)
res = json.loads(r_out.read_text(encoding="utf-8"))
by_title = {(a["file"], a["title"]): a for a in res["arms"]}


def find(file, title_prefix):
    hits = [a for (f, t), a in by_title.items() if f == file and t.startswith(title_prefix)]
    assert len(hits) == 1, f"{file} の {title_prefix!r} に当たる腕が {len(hits)} 本: {list(by_title)}"
    return hits[0]


norm1 = next(a for a in res["arms"] if a["id"] == "norm1")
norm2 = next(a for a in res["arms"] if a["id"] == "norm2")
guard_cond = find("calc.py", "cond: n < 0")
guard_stmt = find("calc.py", "stmt: raise ValueError(\"negative\")")
loud_cond = find("calc.py", "cond: n > 100")
dead_cond = find("calc.py", "cond: n == 42")
extra_cond = find("extra.py", "cond: n is None")
extra_stmt = find("extra.py", "stmt: raise ValueError")
seven_cond = find("calc.py", "cond: n == 7")

assert r.returncode == 1, f"生存・未到達を含む撃ちの exit は 1 のはずが {r.returncode}"
assert norm1["status"] == "Killed" and norm1["own"], f"norm1 は Killed・own のはずが: {norm1['status']}, own={norm1.get('own')}"
# norm2 は expect でなく marker だけを持つ——own は False だが、印が写しの出力に現れたことが証拠になる
assert norm2["status"] == "Killed" and not norm2["own"], f"norm2 は Killed・own=False のはずが: {norm2['status']}, own={norm2.get('own')}"
assert norm2["evidence"] == "印 norm2 が写しの出力に現れた", f"norm2 の証拠が印によるものになっていない: {norm2.get('evidence')!r}"
assert guard_cond["status"] == "Killed", f"guard の cond は Killed のはずが: {guard_cond['status']}"
assert guard_stmt["status"] == "Killed", f"guard の raise は Killed のはずが: {guard_stmt['status']}"
assert extra_cond["status"] == "Killed", f"extra の cond は Killed のはずが: {extra_cond['status']}"
assert extra_stmt["status"] == "Killed", f"extra の raise は Killed のはずが: {extra_stmt['status']}"
assert loud_cond["status"] == "Survived", f"loud_but_uncaught の cond は Survived のはずが: {loud_cond['status']}"
assert dead_cond["status"] == "NoCoverage", f"dead_code の cond は NoCoverage のはずが: {dead_cond['status']}"
# 1 行 1 本（Google 型）: 同じ行の条件と文（if n == 7: raise …）は条件だけを撃ち、文は撃たずに pruned に理由つきで残る
assert seven_cond["status"] == "Killed", f"同じ行の条件の腕は撃つはずが: {seven_cond['status']}"
pr = {x["title"]: x["reason"] for x in res.get("pruned") or []}
assert pr.get("stmt: raise ValueError(\"seven\")", "").startswith("1 行 1 本"), f"同じ行の 2 本目の腕が pruned に理由つきで残っていない: {pr}"
assert not any(t.startswith("stmt: \"\"\"") for (_, t) in by_title), f"docstring（裸の式の文）が腕になった: {list(by_title)}"
assert dead_cond["rc"] is None, f"到達しない腕は撃たずに済ませるはずが rc={dead_cond['rc']!r}（一度動かしてしまった）"
assert "撃たずに生き残り" in " ".join(dead_cond["tail"]), f"未到達の理由が tail に無い: {dead_cond['tail']}"
assert len(guard_cond["killedBy"]) == 1, f"failfast で最初の FAIL だけのはずが: {guard_cond['killedBy']}"
assert guard_cond["killedBy"] == ["guard(-1) は例外"], f"failfast が止めた場所が違う: {guard_cond['killedBy']}"
# 印の写しが実物の結果（5 本通った・6 本差した）を持つこと——素通りの既定値（0/0）にすり替わっていないか
assert "印の写しで通った 6 本を撃つ" in r.stdout and "通らない 1 本は撃たない" in r.stdout, f"自動の腕の通過数の行が無いか数が違う: {r.stdout}"
assert "印: 7 / 8 本が通った" in r.stdout, f"印の写しの通過数（seen/placed。norm2 の通常 marker も数えるはず）が出ていないか違う: {r.stdout}"

# --files/--only を付けずに --auto だけで撃つと、一覧の腕（全部）と自動の腕の和を 1 回で撃つ（次の周の頭のゲートの実効性の撃ち方）。
# --every-node なら 1 行 1 本に畳まない（Google 型に絞る前の撃ち方）
r_out2 = mini / "r2.json"
r2 = run_mutate("-j", "2", "--auto", BASE, "--every-node", out=r_out2)
assert "撃つ腕が 0 本" not in r2.stderr, f"autos が非 0 なのに 0 本判定に止められた: {r2.stderr!r}"
res2 = json.loads(r_out2.read_text(encoding="utf-8"))
ids2 = {a["id"] for a in res2["arms"]}
assert {"norm1", "norm2"} <= ids2, f"--auto だけの回に、一覧の腕が入っていない: {ids2}"
assert len(ids2) == 10 and not res2.get("pruned"), f"--every-node の回は畳まずに 10 本（一覧 2・自動の発火 7・未到達 1）のはずが: {ids2}"
# 行の途中から始まる文（if x: raise …）には印を差せない——印が無いのは『通らない』ではないので撃つ
seven_stmt = next(a for a in res2["arms"] if a["title"] == "stmt: raise ValueError(\"seven\")")
assert seven_stmt["status"] == "Killed" and seven_stmt["rc"] is not None, f"印の無い行途中の文も撃つはずが: {seven_stmt['status']} rc={seven_stmt['rc']!r}"

# 絞りに当たる一覧の腕が 0 本でも、自動の腕が在れば撃つ（0 本の判定は和の後の 1 か所）——一覧に腕の無いファイルだけを
# 直した周に、自動の腕が撃たれずに抜けていた
r_out5 = mini / "r5.json"
r5 = run_mutate("-j", "2", "--files", "extra.py", "--auto", BASE, out=r_out5)
assert "撃つ腕が 0 本" not in r5.stderr, f"一覧が 0 本・自動の腕ありなのに 0 本判定に止められた: {r5.stderr!r}"
ids5 = {a["id"] for a in json.loads(r_out5.read_text(encoding="utf-8"))["arms"]}
assert ids5 and not ids5 & {"norm1", "norm2"}, f"一覧 0 本の回に自動の腕が撃たれていない（または一覧の腕が紛れた）: {ids5}"

# --- 期限（--deadline-at）: 期限を過ぎていれば新しい腕を始めず、残りを pending にして --out を書き、exit 1 ---
dl_out = mini / "dl.json"
r = run_mutate("--only", "norm1,norm2", "--deadline-at", "2000-01-01T00:00:00+00:00", out=dl_out)
dl = json.loads(dl_out.read_text(encoding="utf-8"))
assert r.returncode == 1 and dl["arms"] == [] and {x["id"] for x in dl.get("pending") or []} == {"norm1", "norm2"}, \
    f"期限切れの回は腕を始めず、全部を pending にして書くはずが: exit {r.returncode} {dl}"
assert "期限で撃たずに残った腕 2 本" in r.stdout, f"残った腕を名乗っていない: {r.stdout}"
g = json.loads(subprocess.run([PY, MUT, "--gate-efficacy", str(dl_out)], capture_output=True, text=True, encoding="utf-8", timeout=30).stdout)
assert g["material"]["status"] == "found" and len(g["arms"]) == 2 and all(not x["red_confirmed"] and "期限" in x.get("note", "") for x in g["arms"]), \
    f"--gate-efficacy は期限で残った腕を証拠にならない行にし、clean にしない: {g}"
# 途中まで撃った結果を --reuse に渡すと、撃てた腕を持ち越し、残りだけ撃つ
full_out = mini / "full.json"
run_mutate("--only", "norm1,norm2", out=full_out)
part = json.loads(full_out.read_text(encoding="utf-8"))
n2row = next(x for x in part["arms"] if x["id"] == "norm2")
part["arms"] = [x for x in part["arms"] if x["id"] != "norm2"]
part["pending"] = [{"id": "norm2", "title": n2row["title"], "file": n2row["file"], "status": "Pending"}]
part_out = mini / "part.json"
part_out.write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
r = run_mutate("--only", "norm1,norm2", "--reuse", str(part_out), out=mini / "cont.json")
assert r.returncode == 0 and "撃つ腕 1 本" in r.stdout and "持ち越し 1 本" in r.stdout, \
    f"pending を持つ結果から続きを撃つはずが: exit {r.returncode} {r.stdout}"
# **撃つ途中で期限が来る**: 期限を過ぎた後に始まる腕は撃たずに pending に、走っている腕は待って結果に入れる。-j 1 で
# [速い腕・止めておく腕・速い腕] を撃つ。**切り替わりは時計でなく印のファイルで起動する**——mutate.py の期限の判定は時刻の口 now の
# 1 本で、包み（clock.py）がそれを『切り替えのファイルが在れば 1 年先』に差し替える。台本は、止めておく腕が始まった印（held）を
# 見てから切り替え、それから解放する。-j 1 なので、それまでに control・印の写し・速い腕 1 本目は済んでおり、2 本目は切り替えの後に
# 始まる（以前は 30 秒の壁時計の窓に 3 つが収まる前提で、負荷の下で割れた）。選んだ腕は、撃った腕か pending のどちらかに
# ちょうど 1 度ずつ載る（取り消した腕を結果として読む・撃った腕を 2 度載せる・走っていた腕を落とす、のどれでも崩れる）
sys.path.insert(0, str(REAL_TESTS))
import datetime, os, time, mutate as _M
held, release, switch = mini / "slow-started", mini / "slow-release", mini.parent / "clock-switch"


def slow_arm(aid, started, rel):
    """始まったら自分の pid を started に書き、rel が在るまで台本を止めておく腕"""
    return {"id": aid, "title": "台本を解放まで止めておく", "file": "tests/run.sh", "suite": "root", "old": "set -uo pipefail",
            "new": f"set -uo pipefail\necho $$ > '{started.as_posix()}'\nwhile [ ! -e '{rel.as_posix()}' ]; do sleep 0.1; done",
            "expect": "classify は閾値超えで pos"}


slow_doc = json.loads((mini / "tests" / "mutations.json").read_text(encoding="utf-8"))
slow_doc["arms"] = [slow_doc["arms"][0], slow_arm("slow1", held, release), slow_doc["arms"][1]]
(mini / "slow-arms.json").write_text(json.dumps(slow_doc, ensure_ascii=False), encoding="utf-8")
clock = mini.parent / "clock.py"
clock.write_text("import datetime, pathlib, sys\n"
                 f"sys.path.insert(0, {str(mini / 'tests')!r})\n"
                 "import mutate\n"
                 "switch = pathlib.Path(sys.argv.pop(1))\n"
                 "real = mutate.now\n"
                 "mutate.now = lambda tz: real(tz) + datetime.timedelta(days=365 if switch.exists() else 0)\n"
                 "for s in (sys.stdout, sys.stderr):\n    s.reconfigure(encoding='utf-8')\n"
                 "mutate.main()\n", encoding="utf-8")
cut = datetime.datetime.now().astimezone() + datetime.timedelta(seconds=_M.TIMEOUT + _M.TAIL, days=1)
sl_out = mini / "slow.json"
proc = subprocess.Popen([PY, str(clock), str(switch), "-j", "1", "--arms-file", str(mini / "slow-arms.json"), "--deadline-at", cut.isoformat(),
                         "--out", str(sl_out)], cwd=mini, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
while proc.poll() is None and not held.exists():
    time.sleep(0.1)
switch.touch()
release.touch()
out_, err_ = proc.communicate(timeout=120)
r = subprocess.CompletedProcess(proc.args, proc.returncode, out_, err_)
sl = json.loads(sl_out.read_text(encoding="utf-8"))
shot_ids = [x["id"] for x in sl["arms"]]
pend_ids = [x["id"] for x in sl.get("pending") or []]
assert r.returncode == 1 and "Traceback" not in r.stderr, f"途中で期限が来た回は exit 1 で、例外を出さない: exit {r.returncode} {r.stderr[-300:]}"
assert sorted(shot_ids + pend_ids) == ["norm1", "norm2", "slow1"], f"選んだ腕が撃った腕か pending にちょうど 1 度ずつ載らない: 撃った {shot_ids} / pending {pend_ids}"
assert "norm2" in pend_ids and "norm1" in shot_ids and "slow1" in shot_ids, f"期限の後に始まる腕は pending に、前に始まった腕は結果に: 撃った {shot_ids} / pending {pend_ids}"
# 撃つ段の頭で期限を過ぎていた回は、写しで control も印の写しも走らせず、選んだ腕を全部 pending に置く（期限の後に仕事を始めない）
past = (datetime.datetime.now().astimezone() - datetime.timedelta(days=1)).isoformat()
pa_out = mini / "past.json"
r = subprocess.run([PY, MUT, "-j", "1", "--only", "norm1,norm2", "--deadline-at", past, "--out", str(pa_out)], cwd=mini,
                   capture_output=True, text=True, encoding="utf-8", timeout=600)
pa = json.loads(pa_out.read_text(encoding="utf-8"))
assert r.returncode == 1 and not pa["arms"] and sorted(x["id"] for x in pa.get("pending") or []) == ["norm1", "norm2"] \
    and pa.get("control") == {"carried": {"rc": 0}} and not (pa.get("marker") or {}).get("placed"), \
    f"期限を過ぎてから撃ち始めた回は control も腕も走らせず全部 pending に: exit {r.returncode} control={pa.get('control')} {r.stderr[-200:]}"


def gone(pid, within=10):
    """pid が居なくなるまで問い直す（止めた子は親の回収の前に一瞬残るので、1 回だけ見るとゾンビを生きていると数える）"""
    t0 = time.monotonic()
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        if time.monotonic() - t0 > within:
            return False
        time.sleep(0.05)


# **止める信号で子と写しを残さない**: 止めておく腕の台本が走っている最中に SIGTERM を送ると、mutate.py は子のグループ（写しの中の台本）を
# 止め、写しの置き場を消し、128＋15 で抜ける。止めた腕は Killed と書かない（撃った腕に載らず pending に残る）
if os.name == "posix":
    tmpd = mini.parent / "tmp-stop"
    tmpd.mkdir()
    held2, rel2 = mini / "stop-started", mini / "stop-release"
    (mini / "stop-arms.json").write_text(json.dumps({"arms": [slow_arm("slow2", held2, rel2)]}, ensure_ascii=False), encoding="utf-8")
    st_out = mini / "stop.json"
    proc = subprocess.Popen([PY, MUT, "-j", "1", "--arms-file", str(mini / "stop-arms.json"), "--out", str(st_out)], cwd=mini,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env={**os.environ, "TMPDIR": str(tmpd)})
    while proc.poll() is None and not (held2.exists() and held2.read_text(encoding="utf-8").strip()):
        time.sleep(0.1)
    child = int(held2.read_text(encoding="utf-8"))
    proc.terminate()
    out_, err_ = proc.communicate(timeout=120)
    st = json.loads(st_out.read_text(encoding="utf-8"))
    left = sorted(p.name for p in tmpd.glob("mutate-*"))
    assert proc.returncode == 143 and "Traceback" not in err_, f"SIGTERM で 128+15 で抜け、例外を出さない: exit {proc.returncode} {err_[-300:]}"
    assert gone(child), f"止めた mutate.py の子（写しの中の台本 pid {child}）が残っている"
    assert not left, f"止めた mutate.py の写しの置き場が残っている: {left}"
    assert "slow2" not in [x["id"] for x in st["arms"]] and "slow2" in [x["id"] for x in st.get("pending") or []], \
        f"止めた腕を結果に載せた（Killed と読ませない）: {st}"

# **腕 1 本ごとに --out を書き直す**——撃つ途中で止めても、撃てた腕と残りの腕が読める形で残り、写しの置き場も残らない。
# -j 1 で [速い腕・止めておく腕] を撃ち、止めておく腕が始まって（印が在り）、途中の --out に撃てた腕が載るまで待ってから止める
# ——途中の姿を時間の窓で覗かない（0.1 秒ごとに覗いていたとき、速い機械では 2 本とも済んで途中の姿を見逃し、負荷の高い機械では
# 120 秒で諦めて赤になった。実測 2026-09-26: macOS の CI で 1 回赤）
tmpm = mini.parent / "tmp-mid"
tmpm.mkdir()
held3, release3 = mini / "mid-started", mini / "mid-release"
mid_doc = json.loads((mini / "tests" / "mutations.json").read_text(encoding="utf-8"))
mid_doc["arms"] = [mid_doc["arms"][0], slow_arm("slow3", held3, release3)]
(mini / "mid-arms.json").write_text(json.dumps(mid_doc, ensure_ascii=False), encoding="utf-8")
mid_out = mini / "mid.json"
proc = subprocess.Popen([PY, MUT, "-j", "1", "--arms-file", str(mini / "mid-arms.json"), "--out", str(mid_out)], cwd=mini,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "TMPDIR": str(tmpm)})
seen_mid = None
deadline = time.monotonic() + 1200   # 止めておく腕が始まるまでの上限（control と速い腕が済む幅。負荷の下でも尽きない長さ）
while time.monotonic() < deadline and proc.poll() is None:
    if held3.exists():
        try:
            doc = json.loads(mid_out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        if doc.get("partial") and doc.get("arms"):
            seen_mid = doc
            break
    time.sleep(0.1)
proc.terminate()
proc.wait()
release3.touch()   # 止める信号で子を片付けない OS（Windows）でも、止めておいた台本を抜けさせる
assert seen_mid and len(seen_mid["arms"]) == 1 and len(seen_mid["pending"]) == 1, \
    f"撃つ途中の --out に、撃てた腕 1 本と残り 1 本が載っていない: {seen_mid}"
assert os.name != "posix" or not list(tmpm.glob("mutate-*")), f"止めた mutate.py の写しの置き場が残っている: {sorted(tmpm.iterdir())}"

# --auto を付けない回は、印の写しを撃つのと同じ波で回し、その結果を証拠に使う（自動の腕の先回りの印は無い）
r_out4 = mini / "r4.json"
run_mutate("--only", "norm2", out=r_out4)
n2 = next(a for a in json.loads(r_out4.read_text(encoding="utf-8"))["arms"] if a["id"] == "norm2")
assert n2.get("evidence") == "印 norm2 が写しの出力に現れた", f"--auto の無い回で印の写しの結果が証拠に届かない: {n2.get('evidence')!r}"

# --changed-since も filtered を立てる側（or の 3 本目）——calc.py はコミット後に書き換えたので「変わった」側に入る
r3 = run_mutate("--changed-since", BASE, "--auto", BASE)
assert "撃つ腕が 0 本" not in r3.stderr, f"--changed-since で絞れているのに auto の 0 本判定に止められた: {r3.stderr!r}"
assert "norm1" in r3.stdout or "norm2" in r3.stdout, f"--changed-since が一覧の通常の腕を選べていない: {r3.stdout}"

# --- --gate-efficacy: found（生存・未到達が混ざる回）・行数は撃てた腕の数 ---
r = subprocess.run([PY, MUT, "--gate-efficacy", str(r_out)], capture_output=True, text=True, encoding="utf-8", timeout=30)
assert r.returncode == 0, f"--gate-efficacy 自体は exit 0 のはずが {r.returncode}: {r.stderr}"
gate = json.loads(r.stdout)
assert gate["material"]["status"] == "found", f"生存・未到達が混ざる回は found のはずが: {gate['material']}"
assert len(gate["arms"]) == len(res["arms"]), f"gate の行数が撃てた腕の数と合わない: {len(gate['arms'])} vs {len(res['arms'])}"

print("E2E_AUTO_OK")
PYE2E
expect_output 0 "E2E_AUTO_OK" "自動の腕の本命: 使い捨ての git repo で if の生死が割れる行・誰も通らない行・未追跡の新ファイルを足して撃ち、Killed/Survived/NoCoverage・failfast・未到達を撃たない・--files/--only/--changed-since・差分 0 本・存在しない rev・--gate-efficacy を通して見る" \
    "$PY_BIN" "$WORK/mut-auto-e2e.py" "$ROOT/tests"

# **宣言した下限と、CI が測る版を機械で突き合わせる。** 版を固定した周に、固定と宣言を結ぶ検査を足さなかった
# ——README を上げれば CI は古い版を測り続け、workflow だけ上げれば宣言した下限を誰も測らなくなる。どちらも
# 赤くならない（実測 2026-09-13: tests/run.sh に python-version を照合する行が 0 件）。近傍の doc-symbols.py が
# 同型の突合（文書の名指しする定数の実在）を既に持っており、そこに揃える。
cat > "$WORK/py-floor.py" <<'PYFLOOR'
import re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
wf = (root / ".github/workflows/test.yml").read_text(encoding="utf-8")
m = re.search(r'python-version:\s*"([0-9.]+)"', wf)
if not m:
    print("NG .github/workflows/test.yml に python-version の固定が無い"); sys.exit(1)
ci = m.group(1)
readme = (root / "convergence-loops/README.md").read_text(encoding="utf-8")
want = [ln for ln in readme.splitlines() if "**Required**" in ln]
if not want:
    print("NG convergence-loops/README.md に「**Required**」の行が無い（宣言した下限が読めない）"); sys.exit(1)
# **一致箇所が 1 つであることまで見る。** `want[0]` だけを見ていたので、宣言が 2 行に増えた周は
# 2 行目が誰にも測られないまま食い違える——「最初の一致だけを見る」は母数を 1 に決め打つのと同じ。
if len(want) != 1:
    print(f"NG README.md の「**Required**」の行が {len(want)} 行ある（宣言は 1 か所に。"
          f"どれが正本か決まらないまま片方だけ測ることになる）: {[w[:60] for w in want]}"); sys.exit(1)
if f"**{ci} or later**" not in want[0]:
    print(f"NG CI が測る版 {ci} と README の宣言が食い違う: {want[0][:120]}"); sys.exit(1)
# **workflow は全部見る。** test.yml だけを見ていた頃、週 1 回の全腕（mutation.yml）の版を上げ下げしても赤くならなかった。
# 版の書き方は引用符の有無・単引用符・一覧（[..]）のどれでも拾い、setup-python を使うのに版を読めない workflow は赤にする
# （二重引用符の形だけを拾っていた頃は、ほかの書き方の workflow を黙って飛ばした）
for f in sorted(list((root / ".github/workflows").glob("*.yml")) + list((root / ".github/workflows").glob("*.yaml"))):
    body = f.read_text(encoding="utf-8")
    vals = []
    for raw in re.findall(r"python-version:\s*(.+)", body):
        vals += re.findall(r"[0-9]+(?:\.[0-9]+)+", raw) or ["<読めない: " + raw.strip()[:30] + ">"]
    if "setup-python" in body and not vals:
        print(f"NG {f.name} は setup-python を使うのに python-version を読めない"); sys.exit(1)
    for v in vals:
        if v != ci:
            print(f"NG {f.name} の python-version {v} が test.yml（README の宣言）の {ci} と違う"); sys.exit(1)
# **写した側まで数えるチェックは、ここには置かない。** 一度置いたが、**発火しえない形だった**——語（「名乗る下限」）で
# 母数を取る走査を足した同じ周に、その語を含む注記の側を書き替えてしまい、母数が 0 になった。にもかかわらず
# コメントは「母数はこの下限を名乗る箇所すべて」と名乗っていた（実測 2026-09-13: 判定者が、語の出現が
# run.sh 自身の 2 行だけであることを grep で示した）。**発火しえないチェックは、無いチェックより悪い**——守られていると
# 誤認させる。母数を「実装より広い範囲を名乗る箇所の一覧」で取る形は、その一覧を誰がどう作るかが未決なので
# （台帳の held）、決まるまでチェックを置かない。今そこに残る 3.9 の言及はいずれも過去形の経緯（「下限が 3.9 だった頃」）で、
# 宣言ではない。
print("PY_FLOOR_OK")
PYFLOOR
expect_output 0 "PY_FLOOR_OK" "README が宣言した Python の下限と、CI が測る python-version が一致する（片方だけ動かすと赤）" \
    "$PY_BIN" "$WORK/py-floor.py" "$ROOT"
mkdir -p "$WORK/pyf/.github/workflows" && mkdir -p "$WORK/pyf/convergence-loops" && cp "$CL/README.md" "$WORK/pyf/convergence-loops/" && cp "$ROOT/.github/workflows/test.yml" "$WORK/pyf/.github/workflows/" \
    && printf 'jobs:\n  m:\n    steps:\n      - uses: actions/setup-python@v5\n        with:\n          python-version: "3.11"\n' > "$WORK/pyf/.github/workflows/other.yml"
expect_output 1 "NG other.yml の python-version 3.11" "test.yml 以外の workflow の python-version も README の下限と突き合わせる" \
    "$PY_BIN" "$WORK/py-floor.py" "$WORK/pyf"
printf 'jobs:\n  m:\n    steps:\n      - uses: actions/setup-python@v5\n        with:\n          python-version: 3.11\n' > "$WORK/pyf/.github/workflows/other.yml"
expect_output 1 "NG other.yml の python-version 3.11" "引用符の無い python-version も拾う" \
    "$PY_BIN" "$WORK/py-floor.py" "$WORK/pyf"
rm "$WORK/pyf/.github/workflows/other.yml"
printf 'jobs:\n  m:\n    strategy:\n      matrix:\n        py: [x]\n    steps:\n      - uses: actions/setup-python@v5\n        with:\n          python-version: ${{ matrix.py }}\n' > "$WORK/pyf/.github/workflows/m.yaml"
expect_output 1 "NG m.yaml の python-version" "版を読めない workflow（.yaml・matrix の式）は黙って飛ばさず赤" \
    "$PY_BIN" "$WORK/py-floor.py" "$WORK/pyf"

# **ラチェットの突合が等値であること。** これが外から要るのは、**緩めた側は自分では赤くならない**から
# ——検査は自分の断言が緩んだことを検知できない（実測 2026-09-13: 台本の到達数の突合を `>= 0 or` に
# 緩める退行を注入したら、その台本は全件緑のまま exit 0 だった）。下限（`-lt` / `>=`）にすると、
# 上げ忘れも下げ忘れも黙って通る（実測: 実数 501 に対して下限が 491 のままで、検査を 10 件消しても
# 「491 件すべて緑」だった）。**注記は赤くならないので、仕組みで見る。**
cat > "$WORK/ratchet.py" <<'RATCHET'
import re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
# 表を足すときは「定数の宣言」と「突合の現物（その 1 行まるごと）」の両方を書く。
# **部分一致では足りない。** 最初に `reached == VOCAB_REACHED` の存在だけを見ていたが、
# `reached >= 0 or reached == VOCAB_REACHED` に緩める退行はその部分文字列を残したまま通った
# （実測 2026-09-13: このチェックを足した当日、自分で注入して緑だった）——**チェックが、自分が測るものより
# 広いことを名乗っていた**形そのもの。突合の式ぜんぶを固定し、加えて緩い比較の同居を禁ずる。
# **走査対象は宣言から導く。** 4 行を手で並べていたので、新しいラチェット定数を足した周にその 1 本だけ
# 表の外へ静かに落ちた（今日時点の漏れは 0 だが、形は『走査対象のファイルを手で列挙している』そのもの）。
# 表が持つのは**定数ごとに要求する突合の式**だけで、どのファイルを見るかは宣言（`^名前 =` / `^名前=`）を探す。
FORMS = {
    "EXPECTED_CHECKS": 'if [ "$ran" -ne "$EXPECTED_CHECKS" ]; then',
    # 到達の等値は parallel.judge の count（組の回はまとめの口が和集合で同じ関数を当てる。緩めた退行は test_shards.py が赤にする）
    "VOCAB_REACHED": '        ok = parallel.aggregate("判定語彙の到達", "count", keys, VOCAB_REACHED)',
    "EXPECTED_TESTS": 'if [ "$tests" -ne "$EXPECTED_TESTS" ]; then',
    # pytest の置き場の件数の定数。突合の != は fence.py の中で、ここは定数をチェックに渡す 1 行を固定する
    # （fence.py の != を緩めた退行は、graphloops/tests/py/test_fence.py が両向きの不一致で赤にする）
    "EXPECTED_ITEMS": "    fence.install(config, HERE, EXPECTED_ITEMS)",
    # 盤面を回す台本の検査の件数と到達の数。突合の != は fence.py の中で、ここは期待値をチェックに渡す 1 行を固定する
    "EXPECTED_SIM_CHECKS": "    fence.expect_sim(config, EXPECTED_SIM_CHECKS, EXPECTED_SIM_REACHED)",
    "EXPECTED_SIM_REACHED": "    fence.expect_sim(config, EXPECTED_SIM_CHECKS, EXPECTED_SIM_REACHED)",
}
# **母数は宣言から取り、表に無い名前には理由を要求する。** FORMS に名前を 2 つ手で並べていたので、
# 新しいラチェットを足した周にその 1 本が黙って表の外へ落ちる形だった。検査の置き場に在る整数の定数を
# 全部数え、FORMS でも NOT_RATCHET でもない名前が 1 つでも在れば赤——**残すなら理由を書く**。
NOT_RATCHET = {
    "BIG_ROWS": "材料の大きさ（分割の挙動を出すための寸法で、周ごとに上げ下げしない）",
    "COLDREAD_SKIP": "子へ渡す環境変数の既定値",
    "MIN": "table-copies.py が『並べ直し』と見なす語数の閾値",
    "NUM": "catchup の分岐表の期待値（switch-case の網羅で、件数のラチェットではない）",
    "TIMEOUT": "tests/mutate.py が写しで台本一式を走らせる時間切れ（秒）。件数の突合ではない",
    "EXPECT_HEAD": "tests/mutate.py が expect の頭を台本の本文に探す字数。件数の突合ではない",
    "TAIL": "tests/mutate.py が --deadline-at の期限の手前に残す幅（秒）。件数の突合ではない",
    "STOP_GRACE": "tests/mutate.py が止める信号で子のグループへ送る信号の間の猶予（秒）。件数の突合ではない",
    "ARGV_MAX": "tests/mutate.py が pytest の node id を並べる引数の字数の上限（超えればテストのファイル単位に落とす）。件数の突合ではない",
    "NOW": "works-dispatch の試験が固定する今の時刻（Unix 時刻）。件数の突合ではない",
    "T0": "works-dispatch の試験が固定する会話の処理が起きた時刻（Unix 時刻）。件数の突合ではない",
    "ME": "works-dispatch の試験の中の、この会話の処理の番号（pid）。件数の突合ではない",
    "SKILL_MAX": "tests/skill-descriptions-case.py の SKILL.md の description の字数の上限（Agent Skills の仕様の 1,024 字）。件数の突合ではない",
    "LISTING_MAX": "tests/skill-descriptions-case.py の description と when_to_use の合わせた字数の上限（Claude Code の一覧の 1,536 字）。件数の突合ではない",
    "BODY_CHARS_MAX": "tests/skill-body-case.py の本文の字数の上限（スキルの書き方の標準の決まり 1）。件数の突合ではない",
    "BODY_LINES_LIMIT": "tests/skill-body-case.py の本文の行数の上限（スキルの書き方の標準の決まり 1）。件数の突合ではない",
    "TOC_OVER": "tests/skill-body-case.py が別ファイルに目次を求める行数（スキルの書き方の標準の決まり 5）。件数の突合ではない",
    "TOC_HEAD": "tests/skill-body-case.py が目次を探す頭の行数（スキルの書き方の標準の決まり 5）。件数の突合ではない",
}
DECLARED = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*[0-9]+", re.M)
RATCHETS = []
universe = {}
for f in sorted(root.rglob("*.py")) + sorted(root.rglob("*.sh")):
    # **区切りは `/` に正規化する。** `str(f)` は Windows で `tests\\run.sh` になるので、
    # `".git/" in str(f)` は .git の中を除外できず、下の `rel == "tests/run.sh"`（自分の表を
    # 数えない口）も一致しない——**チェックが自分の表を別の突合と数えて windows-latest だけ赤くなった**
    # （実測 2026-09-14: commit b64936d の windows-latest が「2 か所」で NG。macOS と Linux は緑で手元では見えない）
    rel = f.relative_to(root).as_posix()
    # works は自分の試験の一式（works/tests/run.sh）を持ち、ここの件数のチェックを使わないので走査の外（2026-10-09 の掃除: works の
    # 整数の定数を 1 つずつ NOT_RATCHET に理由つきで足すだけで、突合の要る物は 1 つも無かった）
    if ".git" in f.relative_to(root).parts or "node_modules" in f.relative_to(root).parts or f.relative_to(root).parts[0] == "works":
        continue
    body = f.read_text(encoding="utf-8", errors="replace")
    for const, form in FORMS.items():
        if re.search(rf"^{const}\s*=", body, re.M):
            RATCHETS.append((rel, const, form))
    if "tests" in f.relative_to(root).parts:
        for name in DECLARED.findall(body):
            universe.setdefault(name, []).append(rel)
if not RATCHETS:
    print("NG ラチェットの定数を宣言しているファイルが 1 つも無い（走査が空回り）")
    sys.exit(1)
unclaimed = {n: w for n, w in universe.items() if n not in FORMS and n not in NOT_RATCHET}
if unclaimed:
    for n, w in sorted(unclaimed.items()):
        print(f"NG {n}（{', '.join(w)}）が FORMS にも NOT_RATCHET にも無い"
              "——ラチェットなら突合の式を、違うなら理由を書け")
    sys.exit(1)
stale = sorted(set(NOT_RATCHET) - set(universe))
if stale:
    print(f"NG NOT_RATCHET に、もう宣言が無い名前が残っている（{stale}）——消したら表からも消せ")
    sys.exit(1)
LOOSE = ("-lt", "-gt", "-le", "-ge", ">=", "<=", " > ", " < ")


def source(rel):
    """突合を数える対象の本文。**このチェックは自分の表を数えない。**

    チェックは tests/run.sh の中に在り、表に突合の文字列そのものを持つ。素で数えると自分の 2 行を
    「別の突合」と数えて常に赤くなる（実測 2026-09-13: 無傷の木で control が「3 か所」で NG）。
    """
    t = (root / rel).read_text(encoding="utf-8")
    if rel == "tests/run.sh":
        t = re.sub(r"cat > \"\$WORK/ratchet\.py\" <<'RATCHET'\n.*?\nRATCHET\n", "", t, flags=re.S)
    return t


bad = 0
for rel, const, exact in RATCHETS:
    t = source(rel)
    if not re.search(rf'^{const}\s*=', t, re.M):
        print(f"NG {rel}: ラチェットの定数 {const} の宣言が無い（改名したら、この表も直せ）")
        bad = 1
        continue
    n = t.count(exact)
    if n != 1:
        print(f"NG {rel}: {const} の突合がこの形で 1 か所でない（{n} か所）: {exact}"
              "——下限に緩めると、上げ忘れも下げ忘れも黙って通る")
        bad = 1
    for ln in t.splitlines():
        if const in ln and not ln.lstrip().startswith("#") and any(op in ln for op in LOOSE):
            print(f"NG {rel}: {const} が緩い比較と同居している（等値の行を残したまま横に足せる）: {ln.strip()[:100]}")
            bad = 1
if bad:
    sys.exit(1)
# **CONTRIBUTING.md の宣言（「review-loop が読む検証の道具」）の「件数の柵」の行は、この表が導いた名前と両方向で一致する。**
# 宣言は役が読む写しなので、ラチェットを足した・消した周に宣言だけが古くなる形を赤にする。置き場は宣言に書かない（ここが導く）
readme = (root / "CONTRIBUTING.md").read_text(encoding="utf-8")
sec = re.search(r"^### review-loop が読む検証の道具（このリポジトリの宣言）\n(.*?)(?=^#{1,3} |\Z)", readme, re.M | re.S)
fence = re.search(r"^- \*\*件数の柵\*\*:(.*)$", sec.group(1), re.M) if sec else None
if not fence:
    print("NG CONTRIBUTING.md に「review-loop が読む検証の道具」のセクションか、その「件数の柵」の行が無い（宣言の見出しを変えたら、このチェックも直せ）")
    sys.exit(1)
declared = set(re.findall(r"`([A-Z][A-Z0-9_]+)`", fence.group(1)))
derived = {c for _, c, _ in RATCHETS}
if declared != derived:
    print(f"NG CONTRIBUTING.md の宣言の件数のチェックがラチェットの表とずれている（宣言にだけ在る {sorted(declared - derived)}"
          f"・表にだけ在る {sorted(derived - declared)}）")
    sys.exit(1)
print(f"RATCHET_OK（検査の置き場の整数の定数 {len(universe)} 名・突合を要求 {len(FORMS)} 名"
      f"・理由つきで対象外 {len(NOT_RATCHET)} 名・突合した宣言 {len(RATCHETS)} 件）")
RATCHET
expect_output 0 "RATCHET_OK" "ラチェット（件数・語彙の到達）の突合が等値で、緩められていない" \
    "$PY_BIN" "$WORK/ratchet.py" "$ROOT"

# **手順書が案内する呼び出しが、実物の CLI に在ること。** 同じ事実（サブコマンドとフラグ）が engine と
# 手順書に分かれて宣言されており、engine 側を動かした周に手順書だけが古くなる——そして手順書は回す側が
# 読む唯一の導線なので、**案内どおりに打つと落ちる**状態が誰にも赤くならないまま残る。doc-symbols.py が
# 文書の名指しする定数の実在を見ているのと同型で、こちらは「打てる形か」を見る。
# 走査対象は commands/*.md と skills/ の下の .md（本文と別ファイル）をファイル集合から導く——名前を並べると、足した手順書だけ誰も見ない。
cat > "$WORK/doc-cli.py" <<'DOCCLI'
import re, subprocess, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
loop = root / "graphloops/scripts/loop.py"
# timeout: 決着済みの規約（issue #5「無制限ハングを塞ぐ」）が今日の新設に当たっていなかった。
# `--help` は即返るので近傍の 600 より短くてよい
top = subprocess.run([sys.executable, str(loop), "--help"], capture_output=True, text=True,
                     encoding="utf-8", errors="replace", timeout=60)
m = re.search(r"\{([a-z,-]+)\}", top.stdout)
if not m:
    print("NG loop.py --help からサブコマンドの一覧が読めない")
    sys.exit(1)
real = {}
for s in m.group(1).split(","):
    h = subprocess.run([sys.executable, str(loop), s, "--help"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    real[s] = set(re.findall(r"(--[a-z][a-z-]+)", h.stdout))
docs = [f for d in ("convergence-loops", "graphloops") for f in sorted((root / d).glob("commands/*.md")) + sorted((root / d / "skills").rglob("*.md"))]
if not docs:
    print("NG 手順書が 1 本も見つからない（走査の母数が 0）")
    sys.exit(1)
bad = 0
# **数えるのは容れ物でなく当たり。** 手順書の本数だけを見ていたとき、手順書から loop.py の綴りを
# 全部消しても `DOC_CLI_OK（手順書 6 本）` で通った（実測 2026-09-13）——走査が空回りしても合格の顔になる。
# REVIEW.md コード衛生観点③②『検査対象が空・縮退したとき合格と区別できるか』。
# **当たりの数だけでは、まだ合格の顔をする。** 照合 8 件を印字して緑だったとき、手順書に在る綴りは
# 20 件で、**12 件が母数の外に居た**（実測 2026-09-14: 手順書は `python3 "…/loop.py" init` と
# 引用符を閉じてから書くのに、正規表現が `loop\.py\s+` と閉じ引用符を許さなかった。存在しない
# サブコマンドを同じ引用符付きの形で足しても緑のまま）。**母数と当たりの差を出し、差の全部に
# 理由のフィールド（下の BARE）が要る。** 理由の無い残りが 1 件でも在れば赤。
ALL = re.compile(r"(?<![-\w])loop\.py")            # 母数（`review-loop.py` 等の別ファイルは除く）
CALL = re.compile(r"""(?<![-\w])loop\.py["'`]?\s+([a-z][a-z-]*)((?:\s+(?:--[a-z-]+|[^\s`|]+))*)""")
BARE = re.compile(r"""["'`]?(?:[）)、。,]|\s|$)""")  # 残してよい残り: 引数を伴わない綴りだけの言及
universe = matched = bare = 0
for d in docs:
    text = d.read_text(encoding="utf-8")
    hit = {mm.start() for mm in CALL.finditer(text)}
    for occ in ALL.finditer(text):
        universe += 1
        if occ.start() in hit:
            continue
        if BARE.match(text[occ.end():]):
            bare += 1
            continue
        print(f"NG {d.relative_to(root)}:{text.count(chr(10), 0, occ.start()) + 1}: "
              "loop.py の綴りが照合にも『綴りだけの言及』にも当たらない"
              f"（母数の外に落ちている）: {text[occ.start():occ.end() + 30]!r}")
        bad = 1
    for mm in CALL.finditer(text):
        sub, rest = mm.group(1), mm.group(2)
        if sub not in real:
            print(f"NG {d.relative_to(root)}: loop.py に '{sub}' というサブコマンドは無い（{sorted(real)}）")
            bad = 1
            continue
        matched += 1
        for f in re.findall(r"(--[a-z][a-z-]+)", rest):
            if f not in real[sub]:
                print(f"NG {d.relative_to(root)}: loop.py {sub} に {f} は無い（案内どおりに打つと落ちる）")
                bad = 1
if bad:
    sys.exit(1)
if not matched:
    print(f"NG 手順書 {len(docs)} 本のどれも loop.py の呼び出しを書いていない"
          "（照合が 0 件——このチェックは何も測っていない）")
    sys.exit(1)
print(f"DOC_CLI_OK（母数 {universe} 件・照合 {matched} 件・綴りだけの言及 {bare} 件"
      f"／手順書 {len(docs)} 本）")
DOCCLI
expect_output 0 "DOC_CLI_OK" "手順書が案内する loop.py の呼び出しが実物に在る（engine を動かした周に案内だけ古くならない）" \
    "$PY_BIN" "$WORK/doc-cli.py" "$ROOT"

# **子の出力を文字で読むなら encoding を明示しろ。** Windows の既定は cp1252（日本語 Windows なら cp932）で、
# このリポジトリの子プロセスはほぼ日本語を出す——`text=True` だけ付けると UnicodeDecodeError で落ちる。
# 同じ欠陥をこのリポジトリは既に 2 度直しており（出力ストリームの reconfigure、検査の subprocess）、
# **3 度目を新しいチェック自身がやった**（実測 2026-09-13: 今日足した doc-cli.py が windows-latest だけで落ちた。
# 知識はリポジトリに在ったのに、新しい場所に適用されなかった）。母数を機械で持つ。
# バイトで読む呼び（text= を付けない）は対象外——復号が起きないので既定コーデックに依らない。
cat > "$WORK/sub-encoding.py" <<'SUBENC'
import ast, re, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
# **構文は ast で見る。** 自作の正規表現で `subprocess.…(…)` を拾っていたとき、括弧の入れ子を 1 段しか
# 許さず、`str(pathlib.Path(x).resolve())` を含む呼びが母数から静かに落ちた（実測 2026-09-13:
# AST で 68 件・正規表現で 67 件。落ちた 1 件は graphloops/tests/simulate.py の `Run.cmd` で、
# **チェックが防ぐと名乗った当の事故（台本の全 engine 呼びを通す 1 行）が母数の外**だった）。
# 同じ差分の table-copies.py は同種の走査を ast で解いている——定番解はこの中に在った。
RUNNERS = ("run", "check_output", "Popen")
bad = []
# **区切りは `/` に正規化する。** `str(p)` は Windows で `\\` になるので `".git/" in str(p)` が
# 一致せず、除外したはずの .git の中まで走査に入る（実測 2026-09-14: 同じ形が ratchet.py で
# windows-latest だけ赤くした。除外が効かない側は静かに母数が広がるので、緑のまま気づかない）
# works は CI を macOS だけで回し（.github/workflows/test.yml の works の job）、利用者も macOS の keychain でログインする
# ので、Windows の既定コーデックのチェックの外（2026-10-09 の掃除）
def skip(p):
    parts = p.relative_to(root).parts
    return ".git" in parts or "node_modules" in parts or parts[0] == "works"


files = [p for p in root.rglob("*.py") if not skip(p)]
if not files:
    print("NG 走査対象が 0 件（母数が取れていない）")
    sys.exit(1)
calls = 0
textual = 0
for p in files:
    src = p.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    # **module の綴りを決め打ちしない。** `mod != "subprocess"` で見ていたとき、
    # `import subprocess as sp` → `sp.run(...)` が母数から静かに落ちた（実測 2026-09-14: 修正を
    # 残したまま破りに行って見つけた——チェックが名乗るのは「子の出力を文字で読む呼び」であって
    # 「subprocess と綴られた呼び」ではない）。import の別名を先に集める
    mods, funcs = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {(a.asname or a.name) for a in node.names if a.name == "subprocess"}
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            funcs |= {(a.asname or a.name) for a in node.names if a.name in RUNNERS}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute):
            if f.attr not in RUNNERS or getattr(f.value, "id", "") not in mods:
                continue
        elif isinstance(f, ast.Name):
            if f.id not in funcs:
                continue
        else:
            continue
        calls += 1
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        textish = any(isinstance(kw.get(a), ast.Constant) and kw[a].value is True
                      for a in ("text", "universal_newlines"))
        # **母数と当たりの差を印字する。** 呼びの総数だけを出していたので、そのうち何件が
        # この不変条件の当たる面（文字で読む呼び）かが緑の顔からは見えなかった
        textual += 1 if textish else 0
        if textish and "encoding" not in kw:
            bad.append(f"{p.relative_to(root)}:{node.lineno}")
if not calls:
    print("NG subprocess の呼びが 1 件も見つからない（走査が空回り）")
    sys.exit(1)
# **書く側も見る。** 読む側だけを見ていたので、今日足したチェック 4 本が「合格の行に日本語を print する」
# ところで windows-latest だけ落ちた（実測 2026-09-13）——**チェックの名乗り（encoding を明示している）が、
# 測る面（読む側だけ）より広かった**。埋め込みの script は自分で標準出力を直せるので、そこを要求する。
# **母数は tests/run.sh のヒアドキュメントの 2 つの形**——ファイルに書く形（cat > "$WORK/<名前>" <<'<印>'）と、標準入力で
# 渡す形（"$PY_BIN" - <引数> <<'<印>'）。前者だけを数えていたとき、後者の 1 本（ENTRY_SURFACE_OK）が日本語の合格行を
# print して windows-latest だけで落ちた（実測 2026-09-26、run 36206449136）。`"$PY_BIN" -c` の 1 行形は数えない——
# 合格の出力は ASCII か、PYTHONIOENCODING=utf-8 を前置した呼びだけで、日本語を stdout に出す形はここに来ない
run_sh = (root / "tests/run.sh").read_text(encoding="utf-8")
here = re.findall(r"cat > \"\$WORK/([\w.-]+)\" <<'(\w+)'\n(.*?)\n\2\n", run_sh, re.S)
stdin_here = [(f"標準入力の {m.group(1)}（{run_sh.count(chr(10), 0, m.start()) + 1} 行）", m.group(1), m.group(2))
              for m in re.finditer(r"\"\$PY_BIN\" - [^\n]*<<'(\w+)'[^\n]*\n(.*?)\n\1\n", run_sh, re.S)]
if not here or not stdin_here:
    print(f"NG tests/run.sh の埋め込みの script を拾えない（ファイルに書く形 {len(here)} 本・標準入力の形 {len(stdin_here)} 本。走査が壊れている）")
    sys.exit(1)
for name, _tag, body in here + stdin_here:
    # **平坦な部分一致で見ない。** `"reconfigure" not in body` で見ていたとき、実コードを消して
    # コメントに語だけ残す退行が通った（実測 2026-09-13）——**呼びの形まで見る**。
    # 同じ commit が stdout-shape.py で潰した `"def bullet" not in t` と同型の穴だった。
    if not re.search(r"^\s*_s\.reconfigure\(encoding=", body, re.M):
        bad.append(f"tests/run.sh の {name}: 標準出力の encoding を直す呼びが無い"
                   "（Windows の既定 cp1252 で、日本語を print した時点で落ちる。語がコメントに在るだけでは足りない）")
# **起動の口を持つ .py も書く側に入れる。** 埋め込みの script だけを見ていたとき、単体の入口（tests/mutate.py）が
# 日本語を print して windows-latest だけで落ちた（実測: 25d6338 以降の Windows の run すべて）。母数は
# `if __name__ == "__main__"` を持ち、print か sys.stdout / sys.stderr に触れるファイル。呼びの形は ast で見る
entries = 0
for p in files:
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        continue
    if not any(isinstance(n, ast.If) and "__main__" in ast.unparse(n.test) for n in tree.body):
        continue
    writes = any((isinstance(n, ast.Call) and getattr(n.func, "id", "") == "print")
                 or (isinstance(n, ast.Attribute) and n.attr in ("stdout", "stderr") and getattr(n.value, "id", "") == "sys")
                 for n in ast.walk(tree))
    if not writes:
        continue
    entries += 1
    if not any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "reconfigure"
               and any(k.arg == "encoding" for k in n.keywords) for n in ast.walk(tree)):
        bad.append(f"{p.relative_to(root).as_posix()}: 起動の口を持ち標準出力に書くのに、encoding を直す呼び（reconfigure）が無い")
if not entries:
    print("NG 起動の口を持つ .py が 1 本も見つからない（走査が空回り）")
    sys.exit(1)
if bad:
    for b in bad:
        print(f"NG {b}" if b.startswith("tests/run.sh") or "起動の口" in b else f"NG {b}: 子の出力を文字で読むのに encoding が無い（Windows の既定 cp1252 で日本語が落ちる）")
    sys.exit(1)
print(f"SUB_ENCODING_OK（走査した呼び {calls} 件のうち文字で読む {textual} 件を突合／対象外 {calls - textual} 件: バイトで読むので既定コーデックに依らない"
      f"・{len(files)} ファイル・書く側 ファイルに書く形 {len(here)} 本・標準入力の形 {len(stdin_here)} 本と起動の口 {entries} 本）")
SUBENC
expect_output 0 "SUB_ENCODING_OK" "子の出力を文字で読む呼びは encoding を明示している（Windows の既定コーデックに依らない）" \
    "$PY_BIN" "$WORK/sub-encoding.py" "$ROOT"

# **名前表の要素を、読む側が文字列で並べ直していないこと。** 6 周目に閉じた塊のうち 4 つが同じ形だった
# ——engine か検証器が正本の集合を持つのに、読む側がその要素を手で並べ、**並べた側が本家より狭い**まま
# 誰も気づかない（値を足した周に、その 1 値だけ静かに腕の外へ落ちる）。1 件ずつ人が見つけていたので母数を機械で取る。
# **見るのは所属の判定（`x in (…)` / `not in`）だけ。** 素朴に「本家の部分集合である文字列の並び」を全部
# 落とすと 80 件出て、ほぼ全部が検査の中の普通のデータだった（実測 2026-09-13）——**チェックが自分の測るものより
# 広いことを名乗る**形になるので、今日それを 3 回直した当の周に作らない。
cat > "$WORK/table-copies.py" <<'TBLCOPY'
import ast, pathlib, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
MIN = 2  # 1 語の一致は普通の参照。2 語以上そろって初めて「並べ直し」と見なす


def members(node):
    """そのセクションから文字列の集合を取れるなら取る（tuple / list / set / dict の鍵 / 包む呼び出しの引数）。"""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        v = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return set(v) if node.elts and len(v) == len(node.elts) else None
    if isinstance(node, ast.Dict):
        k = [x.value for x in node.keys if isinstance(x, ast.Constant) and isinstance(x.value, str)]
        return set(k) if node.keys and len(k) == len(node.keys) else None
    if isinstance(node, ast.Lambda):
        # **包む関数の中まで見る。** 表を `_tables("…", lambda: {…})` の形で例外境界の中へ入れた周に、
        # このチェックから 2 つの表が黙って落ちた（実測 2026-09-14: 母数 51 → 49。チェックの母数が狭くなった側は
        # 自分では赤くならないので、退行注入で気づいた）——同じ周の別の修正が、このチェックの面を削っていた
        return members(node.body)
    if isinstance(node, ast.Call):
        for a in node.args:
            m = members(a)
            if m:
                return m
    return None


def pick(globs):
    out = []
    for g in globs:
        out += [p for p in root.glob(g) if p.is_file()]
    return sorted(set(out))


owners = {}  # 正本を持つ側: engine と検証器の module 直下の大文字の名前表
declared = 0
for p in pick(["graphloops/engine/*.py", "scripts/*-record.py"]):
    for n in ast.parse(p.read_text(encoding="utf-8")).body:
        if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id.isupper()):
            m = members(n.value)
            if m and len(m) >= MIN:
                declared += 1
                # **鍵はファイルと名前の組。** 名前だけを鍵にしていたとき、検証器 4 本が同じ名前の表を
                # 持つので後勝ちで潰れ、宣言 51 個のうち 10 個（VERDICT_FIELDS ほか）が黙って母数の外に
                # 落ちていた（実測 2026-09-14）——**チェックが名乗った面より狭い**形そのもの。
                owners[(p, n.targets[0].id)] = m
if not owners:
    print("NG 名前表が 1 つも取れない（母数が 0——走査が壊れている）")
    sys.exit(1)
if len(owners) != declared:
    print(f"NG 名前表の宣言 {declared} 個に対し、表に載ったのは {len(owners)} 個"
          "（鍵が潰れて母数が狭くなっている）")
    sys.exit(1)
bad = []
scanned = 0  # **数えるのは容れ物でなく当たり**——走査が空回りしても合格の顔にならないように
for p in pick(["graphloops/**/*.py", "scripts/*.py", "tests/*.py"]):
    src = p.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Compare) or not any(isinstance(o, (ast.In, ast.NotIn)) for o in node.ops):
            continue
        scanned += 1
        for comp in node.comparators:
            m = members(comp)
            if not m or len(m) < MIN:
                continue
            for (op, name), om in owners.items():
                if op != p and m <= om:
                    bad.append(f"{p.relative_to(root)}:{node.lineno}: {name}（{op.name} の {len(om)} 語）"
                               f"のうち {sorted(m)} を並べ直している——表から導け")
if bad:
    for b in sorted(set(bad)):
        print("NG " + b)
    sys.exit(1)
if not scanned:
    print("NG 走査したファイルが 0 件（このチェックは何も測っていない）")
    sys.exit(1)
print(f"TABLE_COPIES_OK（名前表の宣言 {declared} 個・表に載った {len(owners)} 個"
      f"・走査した所属の判定 {scanned} か所）")
TBLCOPY
expect_output 0 "TABLE_COPIES_OK" "名前表の要素を読む側が文字列で並べ直していない（並べた側だけ狭くなる形）" \
    "$PY_BIN" "$WORK/table-copies.py" "$ROOT"

# **検証器の標準出力を行頭で読むループは、その検証器に行頭の偽造を塞ぐ印字口が要る。** review の rules は
# 「行頭が空白でない行」だけを判定行として読む（stop_branch）。その成立条件は「印字に埋まる役の自由文が
# 行頭を作らないこと」で、満たす場所は検証器の `bullet()` 1 か所——**改行 1 文字で周の分岐を倒せる**
# （実測 2026-09-13: 書く側の覆いは judge のセクション 2 だけで、4 つの入口が外に在った）。
# 4 本の検証器のうち `bullet` を持つのは review だけだが、**他の 3 本は行頭で読む消費者を持たない**ので
# 今は穴ではない。危ないのは「後から行頭で読み始めたのに、その検証器に口が無い」形なので、その組を落とす。
cat > "$WORK/stdout-shape.py" <<'STDOUTSHAPE'
import ast, pathlib, re, sys
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
# 行頭で読む印（engine 側の書き方に依らず、`ln[0].isspace()` で判定行を絞る形を探す）
READS_LINE_HEAD = re.compile(r"\[0\]\.isspace\(\)")


def defs_and_calls(text, name):
    """**Python の構造は ast で見る。** 定義の数と呼びの数を返す。

    正規表現（`^def bullet\\(` と `(?<!def )\\bbullet\\(`）でも今日の木は読めたが、**行頭に無い定義**
    （class の中・条件つきの定義）と、**文字列やコメントの中の綴り**を取り違える向きが逆に開く。
    同じ差分の table-copies.py は既に ast で解いており、定番解はこのファイルの内側に在った。
    """
    tree = ast.parse(text)
    # **定義は module の直下だけ数える。** ast.walk で木ぜんぶを見ると、class の中の同名メソッドが
    # 「印字口が在る」に化ける——消費する側（`bullet(...)` の素の呼び）から見えない定義なので、
    # 名乗りより広い側へ外れる（実測 2026-09-14: 定義を class へ隠す注入が緑で通った）。
    # 呼びの側は入れ子の深さに意味が無いので木ぜんぶを見る
    defined = sum(1 for n in tree.body
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    called = sum(1 for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name)
    return defined, called
rules = sorted((root / "graphloops/rules").glob("*.py"))
if not rules:
    print("NG rules が 1 本も無い（走査の母数が 0）")
    sys.exit(1)
bad = 0
checked = 0
reads = []   # 行頭で読む rules（この不変条件が当たる側）
skipped = []  # 当たらない側。**母数と当たりの差は理由つきで印字する**——差が見えないと狭さが緑で残る
for r in rules:
    if not READS_LINE_HEAD.search(r.read_text(encoding="utf-8")):
        skipped.append(r.stem)
        continue
    reads.append(r.stem)
    loop = r.stem[:-5] if r.stem.endswith("-loop") else r.stem
    v = root / "convergence-loops/scripts" / f"{loop}-record.py"
    if not v.is_file():
        print(f"NG {r.relative_to(root)} は検証器の出力を行頭で読むのに、{v.relative_to(root)} が無い")
        bad = 1
        continue
    # **部分一致で見ない。** 最初は `"def bullet" not in …` で見ており、`def bullet_removed` に改名する
    # 退行がその部分文字列を残して通った（実測 2026-09-13: 今日 3 度目の同じ形）——名前の境界まで見る
    vt = v.read_text(encoding="utf-8")
    defined, used = defs_and_calls(vt, "bullet")
    if not defined:
        print(f"NG {r.relative_to(root)} は検証器の出力を行頭で読むのに、{v.relative_to(root)} に "
              "行頭の偽造を塞ぐ印字口（bullet）が無い——役の自由文の改行 1 文字で判定行を作れる")
        bad = 1
        continue
    # **存在だけでは足りない——通っていることを見る。** `def bullet` が在るかだけを見ていたとき、
    # 呼び 7 か所を全部外して def を残す退行が通った（実測 2026-09-13）。守ると名乗っているのは
    # 印字口の存在でなく『役の自由文が行頭を作らない』ことで、1 か所素通しになれば周の分岐を倒せる。
    if used < 1:
        print(f"NG {v.relative_to(root)}: bullet() の呼びが 1 か所も無い（定義だけ在って通っていない）")
        bad = 1
        continue
    checked += used
if bad:
    sys.exit(1)
if not checked:
    print("NG 行頭で読む rules が 1 本も見つからない（走査が空回り——このチェックは何も測っていない）")
    sys.exit(1)
print(f"STDOUT_SHAPE_OK（rules {len(rules)} 本のうち行頭で読む {len(reads)} 本を突合"
      f"・bullet の呼び {checked} か所／対象外 {len(skipped)} 本={skipped}: 行頭で読む消費者が無い）")
STDOUTSHAPE
expect_output 0 "STDOUT_SHAPE_OK" "検証器の出力を行頭で読むループは、その検証器に行頭の偽造を塞ぐ印字口を持つ" \
    "$PY_BIN" "$WORK/stdout-shape.py" "$ROOT"

# **プラグインに写した本文は、バイトまで同一であること。** プラグインは 1 つずつ配られ、インストール後の
# 実体は自分のサブディレクトリだけになる(実測 2026-09-15: `~/.claude/plugins/cache/raiki61/gates/<版>/` に
# 在るのは `hooks/ README.md skills/` だけで、リポジトリの他の場所は無い)。だから共有の本文——今は
# 認証の段(claude_auth.py)——は**実行時に共有できず、写して配るしかない**。写しは黙って割れるので機械で縛る。
# **確かめる口と配る口は同じ 1 本**（scripts/shared-copies.py --sync で配る）——チェックをここに写すと、
# 直す側と見る側が別々に古くなる。走査対象は印から導く（名前を手で並べない）。
expect_output 0 "SHARED_COPIES_OK" "プラグインへ写した共有の本文(認証の段)が、写し先を持ちバイト単位で同一" \
    "$PY_BIN" "$ROOT/scripts/shared-copies.py"
# **リポジトリの文の、IT の定着語でない言い方の件数が、ファイルごとに基準どおりであること。** 見る口は scripts/terms.py の 1 本
# （基準は scripts/terms-baseline.json）。--land のゲート（会社の形 .claude/company.toml の [land] の check）でも回すが、main は
# GitHub で保護しておらず、--land を通さずに手で push する道もある（docs/releasing.md）ので、main に入った後の CI でも同じ口で見る
expect_output 0 "TERMS_OK" "リポジトリの文の IT の定着語でない言い方の件数が、ファイルごとに基準（scripts/terms-baseline.json）と同じ" \
    "$PY_BIN" "$ROOT/scripts/terms.py"
# 共有の認証の部品のうち、アカウントの OAuth トークンを探す口（account_token）。Keychain と資格情報のファイルは偽物
expect_output 0 "OK" "共有の認証の部品: アカウントのトークンを、作った項目・Claude Code の項目・資格情報のファイルの順に探す" \
    "$PY_BIN" -B "$ROOT/tests/claude-auth-suite.py"

# **検証器の同型部分は、順序まで揃っていること。** 検証器は 1 本ずつ配る前提で共有モジュールを持たないので
# `_rows`（表の組み立て）と `fail`（exit 2 で落とす口）が各本に写される。**写しは中身でなく順序で割れた**
# ——`_rows` は import 時に呼ばれるので `fail` が後ろに在ると、属性の書き忘れが NameError → 未処理例外の
# exit 1 になり、`_rows` の docstring が名乗る当の壊れ方になる（実測 2026-09-14: research 側だけ exit 1、
# review 側は exit 2）。注記は赤くならないので順序を機械で縛る。
cat > "$WORK/validator-order.py" <<'VORDER'
import ast, sys, pathlib
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")
root = pathlib.Path(sys.argv[1])
# **同型部分は record_common.py に寄せた**（2026-09-15）。順序の不変条件はそこに 1 回だけ在るので、
# 走査は scripts/*.py 全部から導く——検証器側に写しが戻ってきた周も、このチェックが拾う。
vals = sorted((root / "convergence-loops/scripts").glob("*.py"))
if not vals:
    print("NG 検証器が 1 本も無い（走査の母数が 0）")
    sys.exit(1)
checked = 0
bad = 0
outside = []  # **母数と当たりの差は理由つきで印字する**——差が見えないと狭さが緑のまま残る
for v in vals:
    # **Python の構造は ast で見る。** 行頭の正規表現（`^def fail\(`）では、条件つきの定義や
    # class の中の定義を見落とし、文字列・コメントの中の綴りを拾う。位置も lineno で直に取れる
    tree = ast.parse(v.read_text(encoding="utf-8"))
    at = {n.name: n.lineno for n in tree.body
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if "_rows" not in at:
        outside.append(v.stem)  # _rows を持たない検証器はこの不変条件の外
        continue
    checked += 1
    if "fail" not in at:
        print(f"NG {v.relative_to(root)}: _rows が在るのに fail が無い（表の組み立ての失敗を exit 2 で落とせない）")
        bad = 1
    elif at["fail"] > at["_rows"]:
        print(f"NG {v.relative_to(root)}: fail（{at['fail']} 行目）が "
              f"_rows（{at['_rows']} 行目）より後ろ——_rows は import 時に呼ばれるので、"
              "属性の書き忘れが NameError の exit 1 になり、記録の不正（exit 2）と区別が付かない")
        bad = 1
if bad:
    sys.exit(1)
if not checked:
    print("NG _rows を持つ検証器が 1 本も無い（走査が空回り——このチェックは何も測っていない）")
    sys.exit(1)
print(f"VALIDATOR_ORDER_OK（検証器 {len(vals)} 本のうち _rows を持つ {checked} 本を突合"
      f"／対象外 {len(outside)} 本={outside}: 表の組み立てを持たない）")
VORDER
# 説明文に ` を書くな——ここはシェルの二重引用符の中なので、`fail` がコマンド置換として**実行される**
# （実測 2026-09-14: 説明が「検証器の  が  より前に在る」と穴あきで出て、stderr に `fail: command not found`
# と `_rows: command not found` の 2 行が出た。検査自体は緑のままなので、印字を読まないと気づかない）
expect_output 0 "VALIDATOR_ORDER_OK" "検証器の fail() が _rows() より前に在る（表の組み立ての失敗が exit 2 で落ちる）" \
    "$PY_BIN" "$WORK/validator-order.py" "$ROOT"

# 数えるだけの回の件数が、全部を回したこの回の件数（下のチェック）と合う。合わなくなるのは、前の検査の結果で検査を足し引きする書き方を
# 入れたとき（数えるだけの回は結果を作らない）。数えるだけの回では、この検査自身も走らずに 1 件に数える
expect_output 0 "COUNT_ONLY_MATCH" "数えるだけの回（TESTS_COUNT_ONLY=1）の検査の件数が、全部を回した回の件数のチェックと合う" \
    env TESTS_COUNT_ONLY=1 bash "$ROOT/tests/run.sh"

if [ "$ran" -ne "$EXPECTED_CHECKS" ]; then
    echo "検査が $ran 件走った（$EXPECTED_CHECKS 件を期待）——検証の空振りか、件数の更新漏れ"
    exit 2
fi
if [ "${TESTS_COUNT_ONLY:-}" = 1 ]; then
    echo "COUNT_ONLY_MATCH 検査は $ran 件で、件数のチェック（EXPECTED_CHECKS）と合う（数えるだけの回。検査は走らせていない）"
    exit 0
fi

echo
report_skips
if [ "$fail" = 0 ]; then
    echo "$ran 件すべて緑${SKIPS[0]+（見送り ${#SKIPS[@]} 件は上の一覧）}"
else
    echo "$ran 件のうち失敗あり"
fi
exit "$fail"
