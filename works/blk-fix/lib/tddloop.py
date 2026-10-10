"""修正のブロックの単位ごとの TDD の輪（MVP。設計 2 節 3・案 (i)。graph は変えず、ブロックの中で回す）。

節と関数:
- tdd-start → start: 入力 tdd_suite（JUnit XML の書き先を第 1 引数に受け、リポジトリの根で走る実行ファイル。本線と同じ約束）が
  空なら何もせず go: false（全部の単位を今どおり直す）。在れば一式を 1 回走らせて元の結末を取り、盤面の tdd-<k>/ に状態を置く。
  承認済みの修正案の単位ごとの約束（plan_contract → planmarks.unit_contract。道・受け入れのテストと赤の種類）もここで 1 回だけ
  組んで状態の contract に置く（盤面の無い置き場・欄の控えの無い run・平の run は空で、輪は約束の無い今の動きのまま）。
  run のテストのコマンド（線の入力 test_cmd）の関門（test_cmd_gate）もここで 1 回だけ決める: 空なら off、実行器のファイルが
  そのコマンドの文字列をそのまま含むなら same_as_suite（一式と同じなので 2 度走らせない）、ほかは 1 回走らせて緑なら on、
  赤・走らないなら off にして理由を test_cmd_note に残す（元から赤の test_cmd で毎単位を拒まない）。test_cmd は nice を付けて
  走らせ、既存のファイルを書き換えた回はいつも赤（書き換えた物は戻す。_cmd_run）。関門が on なら直し・整えの段の指示書に
  そのコマンドを書く。
- tdd-loop の中: tdd-prep → prep（今の段の指示書を fixrules で組んで書く。頭に brief の節: 振り分けの段は
  直す義務の単位の全部、ほかの段は今の単位の brief。盤面の無い置き場・修正案の欄の控えの無い run・平の run は無し）→ 役 tdd（修正役。
  単位の中の段は同じ会話で、単位が替わると包みが新しい会話で起こす（支度が書く単位の鍵。依頼 243 の 2）。振り分け・テスト・直し・整えを返す）→
  tdd-step → step（返答を機械が確かめて段を進める）。段は route → 単位ごとに test → fix →（申告の在る単位だけ）refactor → 次の単位。
  step 1 回ごとに状態の calls に 1 行（n・確かめた段（申し出は conflict、実行器・test_cmd が走らずに抜けた回は runner）・単位・
  合否・その回に起こした一式と test_cmd の数・秒）を積む（秒は書くだけで止める条件に使わない）
  - route: 直す義務の単位（_owed: 開いた単位から、答え待ち・ask_human で外れた単位と食い違いで止めた単位を除く）を全部 1 度だけ
    tdd か direct（理由 10 字以上）に振る。約束で tdd の単位は direct に振れない（出口は phase conflict の申し出）
  - test: 申告したテストのファイルの外に触れていない・写しの red_problems（名指しは failure で落ち、元で通っていた物は緑）。
    約束の在る単位は、受け入れのテストの id を全部名指し（走らせる前に見る）、各テストの赤の種類（red_kind。JUnit の failure の
    type・message から機械が分ける）が宣言した名前（adds）の外の名前・import の失敗でなく、案が exception なら断言の失敗でない（_kind_problems。ほかの
    例外の型・unknown は記録だけ）。direct_why でも direct に渡せない。
    修正案が書き換えを名指した既存のテスト（約束の rewrites）も名指しに入れ、同じ赤（宣言した名前（names）の外の名前・import の失敗でない。
    同じ _kind_problems に種類の宣言なしで、declared も渡す）を通す。
    約束の在る単位は、名指しの外の既存のテストの本体（.py の test* 関数。_unnamed_edits）を書き換えたら拒む（走らせる前）。
    単位の頭で通っていたテストが飛ばされた・結末から消えたら拒む（_vanished_problems。単位の頭から変わったテストの
    ファイルのモジュールだけ。居ないは同じ選びの回に居た時だけ数える）。前の単位で赤→緑を確かめた id は名指しを
    強いず、書き換えさせない（_verified）
    名指し全部の赤の種類を単位の red_kinds に残す
  - 同じ修正案の項目の単位（together）: 受け入れのテストは項目の物で、項目の単位の全部の約束に載る。前の単位の段はそれを全部名指して
    緑にするので、項目を共にする後の単位（載る項目が全部前の単位の項目にも在る物）の直しも要る。支度はその単位を「今は直すな」・
    「この後の単位（今は手を付けるな）」に並べず、「今の単位と一緒に直す単位」の節に並べ、brief の行の単位にも入れる。前の単位が
    緑に届けば、後の単位は段を回さずに機械が閉じる（_close_covered: 受け入れのテストが全部確かめ済みの時だけ。赤・緑とも ok、
    covered_by に一緒に直した単位）。別の項目の単位・前の単位に無い項目にも載る単位は今どおり単位ごとに赤→緑を回す
  - fix: その単位のテストのファイルが赤の時から変わっていない・写しの green_problems。約束の在る単位は、ほかのテストのファイル
    （is_test_file: 宣言か名の慣習）の既存の test* 関数の本体（.py でないファイルは行を消した・置き換えた差分）も変えていない（_other_test_edits）・テストを飛ばした・消していない
    （_vanished_problems）。関門が on なら、そのうえで run の test_cmd も緑（_test_cmd_problems。赤は拒み、走らない時は実行器が
    走らない時と同じに輪を抜ける）。refactor の緑の確かめも同じ。
    緑の後、返答の任意の欄 refactor（{declared, why}）で役が理由（10 字以上）つきで申告した単位か、約束の refactor が真（修正案の
    項目の refactor.declared）の単位だけ refactor の段へ進み、理由を単位の refactor_why に残す。declared が true で理由が短ければ
    拒む（一式を走らせる前）。申告が無ければ単位の refactor を skipped にして次の単位へ（緑の木が次の単位の頭）
  - refactor: 緑の時から何も変えていなければ none。変えたなら fix と同じ確かめをもう 1 回
  - test・fix・refactor とも、名指しを絶対パスの node id で実行器の後ろに足し、合図 TDD_SUITE_ONLY=1（ONLY_ENV）を付けて走らせる
    （一式を回さない。解かない実行器は今どおり一式に足して走らせる）。赤の回は名指しだけ。緑の回（fix・変えた refactor）は名指しに、
    単位の頭からの変更に直に関わる試験（impact.select_tests の direct_only: 変えた試験・変えた file を直に読む・言及する試験）の
    うち元の結末に載ったモジュールの pytest のファイルを絶対パスで足す
    （_reached。元で通っていたテストの緑と消えたテストの照らしは、この回でファイルごと走ったモジュールで見る）。地図が引けない・
    分からない物が近くに在る（run_all）時は合図なしの一式。届かない試験・元の結末の外の試験は受け付け（selected_problems）と
    線の最後のテストの段（一式）が確かめる
  - lanes（並べの周。口は節の script が渡す tddlanes。依頼 243 の並べ。docs/plans/2026-10-07-lane-nodes.md）: 形 g3 の輪（状態の
    lanes_on。入力 tdd_lanes が off なら偽）で、振り分けの直後に範囲の引ける tdd の枝（項目を共にする単位の組。範囲が重なってもよい）が 2 本以上なら、
    tddlanes.plan が枝ごとの worktree と控えを置いてこの段へ進め、輪 tdd-loop はこの段で抜ける（step の出口の done が真・phase が
    lanes。状態の done は偽のまま）。
    この段の周は輪の外の節が回す: tdd-fork が枝の輪 tdd-lane-<n> を起こし（枝ごとに Archon の AI の節。包みが単位の worktree を
    cwd に起こす）、枝の輪の確かめ（tddlanes.lane_step）がこの step を単位の worktree に回し、tdd-join（tddlanes.join）が差分を
    当てて緑を確かめ直し、済まなかった単位を順の単位に戻して段 test へ進める（残りは輪 tdd-rest が順に回す）。この段の状態で
    prep・step を呼ぶのは誤り（Broken）。引き継ぎの節には並べで済んだ単位も並ぶ。出口の lanes に単位ごとの結末（枝の番号と合わせの
    結末）・重なりのファイル・重なりの見込みと枝の段の呼び
  拒めば同じ段のまま、理由は次の指示書（と reason_file）に載る。段ごとに RETRY_MAX 回目の拒否で諦める: test・fix は作業ツリーを
  単位の頭に戻して direct へ、refactor は緑の時の木に戻す。実行器が走らない・回数の上限に届いた時は、残りを全部 direct にして抜ける
  （輪は done の印で抜け、max_iterations に届いて落ちない。R50）
- fix-accept → frozen_problems: 輪で緑になった単位のテストのファイルを、輪の後の修正役が変えていないか（裁定 fix_test_scope の
  範囲の中の変更は、輪が済んだ時の木（frozen_tree）との差分の塊の旧い側の行で見て通す。.py に新しい関数・クラス・メソッドを
  足しただけで、既存の文も既存のテストが読む名・枠の掛け金も変えない物は数えない）
- fix-accept → selected_problems: 版からの変更に直に関わる試験（impact.select_tests の direct_only: 変えた・足した試験・変えた file を
  直に読む・言及する試験（深さ 1）と、修正案の受け入れ・書き換えのテストと輪で名指したテストのファイル。分からない物が近くに
  在れば全部）を同じ実行器で
  走らせ（選んだ .py のうち変えた・足したファイルだけを一式を回す時も絶対パスで後ろに足し、一式でない時は -k で絞る。届いただけの
  段の外の試験は手元で走らせない。ADR 0071 の 3 の 1）、元で赤でなかった試験の赤をテストのファイルごとの行で返す（行はそのパスを
  名指す。ファイルの分からない赤は 1 行にまとめてパスを名指さない）。走らせなかった試験は『手元で回さなかった』として
  知らせと状態（ci_left。受け付けが盤面の trace に載せ、最後の関所が並べる）に名前で残す。届くだけで直に関わらない試験は
  受け付けで回さず、『最後のテストの段に任せた』として知らせと状態（final_left。同じ trace の行・最後の関所）に名前で残す
  （一式は線の最後のテストの段で 1 回。そこでの赤は最後の関所と報告・次の依頼の下書きに載る）。分からない物が直に関わる所
  （起点か深さ 1）に在る時だけ一式を回し、深さ 2 以上の分からない物は final_far に残して最後のテストの段に任せる（輪の緑も同じ）。元の結末に無い試験の赤は、版を
  一時の置き場に写して同じ試験を回し、版でも赤なら外す（作業ツリーは動かさない）。1 件も走らなければ「新しい赤なし」にせず
  知らせる（一式の緑は線の最後のテストの段が確かめる。役は一式を回さない）
- collect → exit_fields: 出口の欄 tdd（単位ごとの道・赤・緑・整えとその申告の理由・direct の理由・test_cmd の緑。輪の test_cmd の
  関門と理由・段ごとの呼び出しの記録 calls）
赤・緑の判定は写しの rules（review-loop-tdd.py）の関数を呼ぶ（写さない）。版は一時の index（GIT_INDEX_FILE）で木に固める
（本物の index・HEAD・枝は動かさない。.gitignore に当たる物は載らない）。期限は持たない。
"""
import ast
import difflib
import hashlib
import io
import json
import os
import pathlib
import posixpath
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True

import adapter  # noqa: E402  （.shared/core。包みが会話を切る単位の鍵の置き場 session_key_path）
import board  # noqa: E402
import cite  # noqa: E402  （.shared/core。名指しの形）
import conflict  # noqa: E402  （.shared/core。食い違いの申し出の確かめ・直す義務から外れた単位）
import entry  # noqa: E402  （.shared/core。盤面の入口）
import fixrules  # noqa: E402  （同じブロックの lib。指示書の組み立て）
import impact  # noqa: E402  （.shared/core。変更に当たる試験の選び）
import planbrief  # noqa: E402  （同じブロックの lib。承認済みの修正案の項目ごとの brief の凍結）
import planmarks  # noqa: E402  （.shared/core。修正案の項目の works の欄。単位の約束）
import script_io  # noqa: E402  （.shared/core。入力の切り替えの語 switch_on）
import seat  # noqa: E402  （.shared/core。借りたスキルの座）
import tree_run  # noqa: E402
import writes  # noqa: E402  （.shared/core。書き込みの出どころの突き合わせ）
import leftovers  # noqa: E402
import promptsection  # noqa: E402
import recount  # noqa: E402  （.shared/core。修正役の印の名 ROLE・裁定の後の修正役の印の名 RULED_ROLE）
from leftovers import Unreadable, git, git_names  # noqa: E402

RULES_GRAPH = "review-loop-tdd.json"
PHASES = ("route", "test", "fix", "refactor", "lanes")   # lanes は並べの周（tddlanes。g3 の振り分けの直後に 1 回だけ。輪の外の節が回す）
MAX_ITERATIONS = 40   # YAML の tdd-loop の max_iterations と同じ値（試験が縛る）。この周に届いたら残りを direct にして抜ける
MIN_WHY = 10
STATE, PROMPT, SUMMARY = "state.json", "next.md", "summary.md"
UNIT_NODE = "tdd"   # 輪の役の印の名（包みの adapter.KEYED_NODES の 1 つ。単位の切れ目で会話を切る）
REST_NODE = "tdd-rest"   # 並べの後に残りの単位を順に回す輪 tdd-rest の役の印の名（同じ支度・確かめ。KEYED_NODES の 1 つ）
UNIT_NODES = (UNIT_NODE, REST_NODE)   # 支度が今の単位の鍵を書く印の名の全部
NO_SUITE = "テストの実行器（入力 tdd_suite）が無い run——全部の単位を今どおり直す"
# 実行器への合図（env）: 1 なら後ろに足した試験（ファイル・node id）だけを走らせてよい（既定の一式を集めない）。輪の赤・緑の回だけが
# 付ける（元の結末・受け付け・版の写しは付けない）。解かない実行器は無視してよい（一式に足して走らせても確かめは同じ）
ONLY_ENV = "TDD_SUITE_ONLY"
# run の test_cmd の関門（start が 1 回だけ決める）: on＝緑の後に毎回走らせる・same_as_suite＝実行器がそのコマンドを包んだ物で
# 一式の緑と同じ（走らせない）・off＝空か、輪の頭で赤・走らない（理由は状態の test_cmd_note）。1 行ずつ定義する（根の柵の
# doc-symbols が文書の名指しを `^名前 =` の行で引く）
GATE_ON = "on"
GATE_SAME = "same_as_suite"
GATE_OFF = "off"
# 単位ごとの深さ（入力 unit_depths の値）のうち、緑の後の test_cmd を走らせない語。出口の単位の test_cmd はその時 CMD_LIGHT
LIGHT = "軽量"
CMD_LIGHT = "light"
SUITE_MADE_NOTE = "一式を走らせて出来たファイル"


class Broken(Exception):
    """回す側の誤り（状態が読めない・輪が済んだ後に呼んだ・入力の形が違う）。節は 2 で落ちる"""


class _RunnerDown(Exception):
    """実行器が走らない・JUnit が読めない（テストや直しの誤りではない。やり直しの回数を使わずに輪を抜ける）"""
    head = "テストの実行器が走らない"


class _CmdDown(_RunnerDown):
    """run の test_cmd が走らない（実行器が走らない時と同じ道で輪を抜ける。理由の頭の語だけ違う）"""
    head = "テストのコマンドが走らない"


_RULES = []


def rules():
    """写しの TDD 版の rules（red_problems・green_problems・RETRY_MAX・parse_junit）。1 回だけ読む"""
    if not _RULES:
        _RULES.append(board.rules_module(board.graph_path(RULES_GRAPH)))
    return _RULES[0]


def retry_max() -> int:
    return rules().RETRY_MAX


# ---------------------------------------------------------------- 版を木に固める・戻す
snapshot = leftovers.snapshot   # 作業ツリーの今の姿の木の sha（正本は leftovers。輪の中の名は変えない）


def touched(repo, a: str, b: str) -> list:
    """木 a から木 b で変わったパス（足した・消したを含む）"""
    return sorted(set(git_names(repo, "diff-tree", "-r", "--name-only", "--no-renames", a, b)))


def restore(repo, tree: str) -> list:
    """作業ツリーを木 tree の姿に戻す（その後に変わった・足した・消したファイルだけ）。戻したパスを返す"""
    return restore_paths(repo, tree, touched(repo, tree, snapshot(repo)))


def restore_paths(repo, tree: str, paths) -> list:
    """作業ツリーの paths だけを木 tree の姿に戻す（tree に無いパスは消す）。戻したパスを返す"""
    paths = sorted(set(paths))
    if not paths:
        return []
    keep = set(paths) & set(git_names(repo, "ls-tree", "-r", "--name-only", tree))
    for p in paths:
        if p not in keep:
            f = pathlib.Path(repo) / p
            if f.is_file() or f.is_symlink():
                f.unlink()
    if keep:
        with tempfile.TemporaryDirectory(prefix="works-tdd-index-") as td:
            env = {**os.environ, "GIT_INDEX_FILE": str(pathlib.Path(td) / "index")}
            git(repo, "read-tree", tree, env=env)
            git(repo, "checkout-index", "-f", "--", *sorted(keep), env=env)
    return paths


def hashes(repo, files) -> dict:
    """ファイル → 中身の sha256（無ければ None）"""
    out = {}
    for f in files:
        p = pathlib.Path(repo) / f
        out[f] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    return out


# ---------------------------------------------------------------- 一式を走らせる
def run_suite(exe: str, repo, work: pathlib.Path, n, args=(), only=False):
    """実行器を 1 回走らせる ——（結末の一覧, 終了コード, 問題）。結末が取れなければ一覧は None。
    .py はこの Python で走らせる（写しの rules の run_suite と同じ）。出力は work/suite-<n>.log に丸ごと。
    args は JUnit の書き先の後ろに足す（段の外の試験のファイル・node id を絶対パスで・受け付けの -k。works/dev/tdd-suite.sh は
    pytest に渡し、試験の根（conftest.py の置き場）が違う名指しは根ごとに別のプロセスで流して JUnit を 1 つに合わせる）。同じ鍵の行は 1 つにまとめる（段のファイルと足した node id が重なっても 1 件）。
    輪の元の結末・各段・受け付け・版の写しの全部がここを通るので、nice -n 19 と機械の試験の枠（tree_run.slotted_run）を
    ここで付ける（ADR 0071 の 3 の 1）。枠を待った秒はログの末尾に書く（走った時間と分けて見る）。
    only なら env に合図 ONLY_ENV=1 を付ける（後ろの試験だけでよい。輪の赤・緑の回）。付けない回は外の env の合図も落とす"""
    argv = ["nice", "-n", "19"] + ([sys.executable] if exe.endswith(".py") else []) + [exe]
    junit = work / f"junit-{n}.xml"
    log = work / f"suite-{n}.log"
    env = {k: v for k, v in tree_run.outside_env(os.environ).items() if k != ONLY_ENV}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", **({ONLY_ENV: "1"} if only else {})})
    with open(log, "wb") as out:
        try:
            rc, wait = tree_run.slotted_run([*argv, str(junit), *args], env, stdin=subprocess.DEVNULL, stdout=out,
                                            stderr=subprocess.STDOUT, cwd=str(repo))
        except OSError as e:
            return None, None, [f"テストの実行器を起こせない（{type(e).__name__}: {e}。ログ {log}）"]
        if wait is not None:
            out.write(f"\n（試験の枠を待った秒: {wait}）\n".encode("utf-8"))
    if not junit.is_file():
        return None, rc, [f"テストの実行器が JUnit XML を書かなかった（exit {rc}。ログ {log}）"]
    try:
        text = junit.read_text(encoding="utf-8", errors="replace")
        cases = rules().parse_junit(text)
        fails = _failure_attrs(text)
    except Exception as e:   # ET.ParseError（写しの rules の中の型）
        return None, rc, [f"JUnit XML が読めない（{e}。ログ {log}）"]
    finally:
        junit.unlink(missing_ok=True)
    return _unique([{**c, **fails.get(_key(c), NO_FAILURE)} for c in cases]), rc, []


NO_FAILURE = {"fail_type": "", "fail_message": ""}


def _failure_attrs(text: str) -> dict:
    """JUnit XML の testcase の鍵（_key）→ {fail_type, fail_message}（failure の子の type・message の属性。同じ鍵は最初の行。
    failure の子の無い行は載せない）。写しの parse_junit は属性を返さないので、同じ XML を ElementTree で読み直す"""
    out = {}
    for tc in ET.fromstring(text).iter("testcase"):
        f = tc.find("failure")
        if f is not None:
            out.setdefault(_key({"classname": tc.get("classname") or "", "name": tc.get("name") or ""}),
                           {"fail_type": f.get("type") or "", "fail_message": f.get("message") or ""})
    return out


KIND_UNKNOWN = "unknown"   # 実行器が failure に type も message も書かない（試験の SUITE・pytest でない JUnit）。拒まず記録だけ
_ASSERT_NAMES = ("AssertionFailedError", "ComparisonFailure", "Failed")   # ほかに名前が AssertionError で終わる型（自前の子の型も）
_NOT_RAISED = re.compile(r"DID NOT RAISE|\bnot raised\b|to be thrown, but nothing was thrown")   # 最後は JUnit 5 の assertThrows
NAME_KINDS = ("NameError", "AttributeError", "ImportError", "ModuleNotFoundError")   # 名前・import の失敗（機能が無い・綴りの誤り）
_HEAD_NAME = re.compile(r"^([A-Za-z_][\w.]*)(?::|$)")
_MISSING = re.compile(r"""(?:has no attribute|cannot import name|No module named|\bname) '([^']+)'""")   # 無い名前の引用（CPython の message の形）


def red_kind(case: dict) -> str:
    """結末の 1 行の赤の種類（上から先に当たった物）: type も message も空なら unknown／期待した例外が出ない（DID NOT RAISE・
    not raised・JUnit 5 の to be thrown, but nothing was thrown）なら exception／message が assert で始まるか、例外の名前（type の
    最後の . の後。type が空なら message の頭の『名前:』）が断言の失敗の型（名前が AssertionError で終わる型を含む）なら
    assertion／ほかは例外の名前（NameError など。名前も無ければ unknown）"""
    typ = (case.get("fail_type") or "").strip()
    msg = (case.get("fail_message") or "").strip()
    if not typ and not msg:
        return KIND_UNKNOWN
    if _NOT_RAISED.search(msg):
        return "exception"
    m = _HEAD_NAME.match(msg) if not typ else None
    name = (typ or (m.group(1) if m else "")).rsplit(".", 1)[-1]
    if msg.startswith("assert") or name.endswith("AssertionError") or name in _ASSERT_NAMES:
        return "assertion"
    return name or KIND_UNKNOWN


def _key(c) -> str:
    return f"{c['classname']}::{c['name']}"   # 写しの rules の _key と同じ形（元の結末の鍵）


def _unique(cases) -> list:
    """同じ鍵の行を最初の 1 つにまとめる（名指しの写しを red_problems が名指しの外と数えない）"""
    seen = set()
    return [c for c in cases if not (_key(c) in seen or seen.add(_key(c)))]


def _abs_paths(repo, files) -> list:
    """根からの相対パス（node id の頭も）を絶対パスにする。実行器は自分の置き場へ cd しうるので、相対では解けない"""
    root = pathlib.Path(repo).absolute()
    return [str(root / f) for f in files]


def _abs_ids(repo, ids) -> list:
    """名指し『<相対パス>::…』を『<絶対パス>::…』の node id にする"""
    parts = [i.partition("::") for i in ids]
    return [a + sep + rest for a, (_, sep, rest) in zip(_abs_paths(repo, [p[0] for p in parts]), parts)]


# ---------------------------------------------------------------- 状態
def load_state(state_file) -> dict:
    """輪の状態（frozen・frozen_tree など）を読む口（受け付けが止めた単位の直しを戻す先を決める）"""
    return _load(state_file)


def _load(state_file) -> dict:
    try:
        return json.loads(pathlib.Path(state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Broken(f"TDD の輪の状態が読めない（{state_file}: {e}）")


def _save(state_file, st: dict) -> None:
    p = pathlib.Path(state_file)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _open_units(raw: str) -> list:
    try:
        keys = json.loads(raw)
    except ValueError as e:
        raise Broken(f"open_units が JSON として読めない（{e}）")
    if not isinstance(keys, list) or not all(isinstance(k, str) and k for k in keys):
        raise Broken(f"open_units が単位の key の配列でない（{raw[:200]!r}）")
    return keys


def _duty(board_dir: pathlib.Path):
    """(直す義務 owed か None, 直す義務から外れた単位 {key: 理由})（conflict.fix_duty。受け付けと同じ 1 つの集合）。盤面の無い
    置き場（state.json が無い）は (None, {})。在るのに読めなければ Broken（開いた単位のまま黙って続けない）"""
    try:
        b = entry.open_board(board_dir, allow_halted=True)
    except Exception as e:
        if (board_dir / "state.json").exists():
            raise Broken(f"盤面 {board_dir} が開けず、直す義務が読めない: {e}") from None
        return None, {}
    try:
        owed, excused = conflict.fix_duty(b)
        return set(owed), dict(excused)
    except Exception as e:
        raise Broken(f"盤面 {board_dir} の直す義務が読めない: {e}") from None


def plan_contract(board_dir: pathlib.Path, keys: list[str]) -> dict[str, dict]:
    """単位 → 承認済みの修正案の約束（planmarks.unit_contract。約束の無い単位は載せない）。盤面の無い置き場（state.json が無い）・
    欄の控えが無い run は {}。盤面が在るのに開けない・欄の控えが凍結の印と食い違う（conflict.frozen_fields が盤面を止めて
    BoardGap）なら、理由の文のまま Broken（約束を黙って空にしない）"""
    board_dir = pathlib.Path(board_dir)
    if not (board_dir / "state.json").exists():
        return {}
    try:
        b = entry.open_board(board_dir, allow_halted=True)
    except Exception as e:
        raise Broken(f"盤面 {board_dir} が開けず、修正案の約束が読めない: {e}") from None
    try:
        fields = conflict.frozen_fields(b)
    except board.BoardGap as e:
        raise Broken(str(e)) from None
    return {k: c for k in keys if (c := planmarks.unit_contract(fields, k)) is not None}


def _owed(st) -> list:
    """TDD の直す義務: start が conflict.fix_duty から組んだ単位（open_units）から、外れた単位（excused）と食い違いで止めた
    単位（parked）を除いた物"""
    out = set(st.get("excused", {})) | set(st.get("parked", []))
    return [k for k in st["open_units"] if k not in out]


def _not_owed_why(st, k) -> str:
    if k in st.get("excused", {}):
        return f"直す義務から外れた——{st['excused'][k]}"
    if k in st.get("parked", []):
        return "食い違いで止めた"
    return "直す義務の単位に無い"


def _unit(key, route, why="") -> dict:
    return {"unit_key": key, "route": route, "why": why, "tests": [], "test_files": [], "red": "", "green": "",
            "refactor": "", "gave_up": "", "problems": [], "files": [], "what": "", "red_kinds": {}, "test_cmd": "",
            "refactor_why": ""}


def _light_units(raw: str) -> list:
    """入力 unit_depths（{"<単位の key>": "軽量" | "標準"} の JSON の文字列。空は {}）のうち LIGHT の単位の key。形が違えば Broken"""
    if not (raw or "").strip():
        return []
    try:
        doc = json.loads(raw)
    except ValueError as e:
        raise Broken(f"unit_depths が JSON として読めない（{e}）")
    if not isinstance(doc, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in doc.items()):
        raise Broken(f"unit_depths が単位の key から深さの語への object でない（{raw[:200]!r}）")
    return sorted(k for k, v in doc.items() if v == LIGHT)


def start(board_dir, repo, suite: str, open_units: str, test_cmd: str = "", unit_depths: str = "", lanes: str = "") -> dict:
    """節 tdd-start。{go, reason, suite, state_file, summary_file}。実行器が無ければ何も書かずに go: false（盤面を読まない）。
    test_cmd は run のテストのコマンド（線の入力）で、元の結末を取った後に関門を決める（_test_cmd_gate）。
    unit_depths は単位ごとの深さ（_light_units）。LIGHT の単位は関門が on でも緑の後の test_cmd を走らせない（状態の light）。
    ほかの単位と空は今どおり。
    lanes は並べの周を使うかの切り替えの語（script_io.switch_on。空は on）。off なら状態の lanes_on を偽にする（並べずに
    tdd の単位を順に回す）。知らない語は Broken"""
    suite = (suite or "").strip()
    try:
        lanes_ok = script_io.switch_on(lanes, "tdd_lanes")
    except ValueError as e:
        raise Broken(str(e)) from None
    off = {"go": False, "reason": NO_SUITE, "suite": suite, "state_file": "", "summary_file": ""}
    if not suite:
        return off
    keys = _open_units(open_units)
    light = _light_units(unit_depths)
    exe = pathlib.Path(suite) if pathlib.Path(suite).is_absolute() else pathlib.Path(repo) / suite
    if not exe.is_file() or not (suite.endswith(".py") or os.access(exe, os.X_OK)):
        return {**off, "reason": f"テストの実行器 {suite} が無いか実行できない——全部の単位を今どおり直す"}
    board_dir = pathlib.Path(board_dir)
    owed, excused = _duty(board_dir)
    if owed is not None:   # 振り分ける義務は受け付けと同じ fix_duty の owed（渡された is_open の並びに、関所で答えて戻った単位を足す）
        keys = [k for k in keys if k in owed or k in excused] + sorted(owed - set(keys))   # is_open の並び順を保つ
    excused = {k: why for k, why in excused.items() if k in keys}
    contract = plan_contract(board_dir, keys)   # 輪の頭で 1 回だけ（欄の控えの食い違いは conflict の 1 か所で止める）
    board_dir.mkdir(parents=True, exist_ok=True)
    k = 1
    while (board_dir / f"tdd-{k}").exists():
        k += 1
    work = board_dir / f"tdd-{k}"
    work.mkdir()
    cases, code, why = run_suite(str(exe), repo, work, 0)
    if cases is None:
        return {**off, "reason": f"元の結末が取れない（{'; '.join(why)}）——全部の単位を今どおり直す"}
    test_cmd = (test_cmd or "").strip()
    gate, note, made = _test_cmd_gate(exe, test_cmd, repo, work / "test-cmd-0.log")
    st = {"suite": suite, "exe": str(exe), "work": str(work), "open_units": keys, "excused": excused,
          "baseline": {_key(c): c["outcome"] for c in cases}, "baseline_exit": code,
          "handoff": snapshot(repo), "suite_made": made, "phase": "route", "tries": 0, "reason": "", "iterations": 0,
          "runs": 1, "order": [], "units": {}, "queue": [], "cur": 0, "unit_head": "", "green_tree": "",
          "done": False, "note": "", "frozen": {}, "parked": [], "parked_why": {}, "contract": contract,
          "test_cmd": test_cmd, "test_cmd_gate": gate, "test_cmd_note": note, "light": light, "calls": [],
          "lanes_on": lanes_ok,
          "lanes_off": None if lanes_ok else {"reason": "switch", "why": "入力 tdd_lanes が off（並べの周を切った run）"}}
    state_file = work / STATE
    _save(state_file, st)
    return {"go": True, "reason": "", "suite": suite, "state_file": str(state_file), "summary_file": str(work / SUMMARY)}


def _test_cmd_gate(exe: pathlib.Path, cmd: str, repo, log: pathlib.Path) -> tuple[str, str, list]:
    """(関門, 理由, 走らせて出来たファイル)。空は (off, "", [])。実行器のファイルの中身が cmd をそのまま含めば
    (same_as_suite, "", [])（use.sh が pytest の 1 コマンドから書いた実行器など。一式の緑が同じコマンドの緑）。ほかは機械の
    試験の枠（entry.local_checks_material → tree_run.slotted_run）で 1 回走らせ、緑なら on、赤・走らないなら off と理由。
    既存のファイルを書き換えた回は赤（_cmd_run。書き換えた物は戻す）。出来たファイルは状態の suite_made の頭（段が触った数えから外す）"""
    if not cmd:
        return GATE_OFF, "", []
    try:
        if cmd in exe.read_text(encoding="utf-8", errors="replace"):
            return GATE_SAME, "", []
    except OSError:
        pass   # 読めない実行器は包みと見なさず、走らせて決める
    mat, made = _cmd_run(repo, cmd, log)
    if mat["status"] == "clean":
        return GATE_ON, "", made
    if mat["status"] == "found":
        return GATE_OFF, (f"run の test_cmd（{cmd}）が輪の頭で赤（{mat.get('rewrote') or f'元から赤。ログ {log}'}）——"
                          "単位ごとに確かめると毎単位を拒むのでこの輪では確かめない（一式の緑は線の最後のテストの段が確かめる）"), made
    return GATE_OFF, f"run の test_cmd（{cmd}）を輪の頭で走らせられない（{mat.get('reason', '')}）——この輪では確かめない", made


def _cmd_run(repo, cmd: str, log: pathlib.Path) -> tuple[dict, list[str]]:
    """test_cmd を機械の試験の枠で nice を付けて 1 回走らせる（ADR 0071 の 3 の 1）——（素材, 新しく出来たパス）。
    決まりは 1 つ: 既存のファイルを書き換えた（変えた・消した）test_cmd は緑でない。書き換えたパスは走らせる前の木に戻し
    （restore_paths。緑を出した木と残る木を違えない）、素材を赤（found）にして、書き換えたパスと戻したことを rewrote の文に載せる。
    suite_made に積んでよいのは新しく出来たパスだけ（積むと書き込みの出どころの照合・凍結の照らしから外れる）"""
    pre = snapshot(repo)
    mat = entry.local_checks_material(repo, cmd, log, niced=True)["material"]
    post = snapshot(repo)
    made = sorted(set(git_names(repo, "diff-tree", "-r", "--name-only", "--no-renames", "--diff-filter=A", pre, post)))
    rewrote = sorted(set(touched(repo, pre, post)) - set(made))
    restore_paths(repo, pre, rewrote)
    if rewrote:
        why = (f"test_cmd が作業ツリーの既存のファイルを書き換える（{', '.join(rewrote[:10])}。元に戻した。ログ {log}）——"
               "書き換えた木で出た緑は数えない（書き換えた物を書き込みの出どころの照合から外さない）")
        mat = {**mat, "status": "found", "count": 1, "rewrote": why}
    return mat, made


def _test_cmd_problems(st, repo) -> list[str]:
    """関門が on の時だけ run の test_cmd を 1 回走らせ（ログ work/test-cmd-<runs>.log。runs を 1 進め、出来たファイルを
    suite_made に積む。書き換えた既存のファイルは _cmd_run が戻して積まない）、赤ならログのパスを含む拒否の文。緑なら今の単位の
    test_cmd を ok にする（_green は今の単位にしか呼ばれない）。走らなければ _CmdDown（実行器が走らない時と同じ道）。
    既存のファイルを書き換えた回は赤（_cmd_run）。今の単位が軽量（状態の light）なら走らせず、単位の test_cmd を CMD_LIGHT にする
    （同じコマンドを run の最後のテストが木の全部で走らせるので、確かめは消えない）"""
    if st.get("test_cmd_gate") != GATE_ON:
        return []
    if _cur(st)["unit_key"] in st.get("light", []):
        _cur(st)["test_cmd"] = CMD_LIGHT
        return []
    log = pathlib.Path(st["work"]) / f"test-cmd-{st['runs']}.log"
    mat, made = _cmd_run(repo, st["test_cmd"], log)
    st["runs"] += 1
    st["suite_made"] = sorted(set(st["suite_made"]) | set(made))
    if mat["status"] == "not_run":
        raise _CmdDown(f"run の test_cmd（{st['test_cmd']}）: {mat.get('reason', '')}")
    if mat["status"] == "clean":
        _cur(st)["test_cmd"] = "ok"
        return []
    tail = " ".join(str(mat.get("detail", "")).split())[-400:]
    return [f"名指しのテストと一式は緑だが、run の test_cmd（{st['test_cmd']}）が赤（輪の頭では緑。ログ {log}）——"
            f"これも緑にせよ（赤の元が凍ったテストのファイルなら phase conflict で申し出よ）。{mat.get('rewrote') or '末尾: ' + tail}"]


# ---------------------------------------------------------------- 指示書（節 tdd-prep）
RETURN = {
    "route": '{"phase": "route", "units": [{"unit_key": "<単位の key>", "route": "tdd" か "direct", "why": "<direct の理由。10 字以上>"}]}',
    "test": '{"phase": "test", "unit_key": "<今の単位>", "test_files": ["<書いたテストのファイル>"], '
            '"tests": ["<パス>::<クラス>::<テストの名前>"]}  （先にテストを書けないと分かったら {"phase": "test", '
            '"unit_key": "<今の単位>", "direct_why": "<理由。10 字以上>"}）',
    "fix": '{"phase": "fix", "unit_key": "<今の単位>", "files": ["<直したファイル>"], "what": "<何をどう直したか>", '
           '"refactor": {"declared": true か false, "why": "<整える理由。declared が true なら 10 字以上>"}}',
    "refactor": '{"phase": "refactor", "unit_key": "<今の単位>", "what": "<何を整えたか。整える物が無ければそう書く>"}',
}
RETURN_CONFLICT = ('どの段でも、緑にするためにテスト・依頼・コードのどれかを曲げるしかないと分かった単位は '
                   '{"phase": "conflict", "unit_key": "<単位>", "between": ["<パス>:<行>", "<パス>:<行>"], '
                   '"why_both_cannot_hold": "<なぜ両方は成り立たないか>", "which_is_right": "request か test か code か unknown か query", '
                   '"kind": "<種類: ' + " か ".join(conflict.DIV_KINDS) + '>"}'
                   '（query なら "correct_lines": ["<問いが当たる直した後の正しい行>"] も）'
                   '（振り分けの段なら義務の単位のどれか、ほかの段なら今の単位）。種類の意味は決まりの節「食い違いの申し出」')
DO = {
    "route": "直す義務の単位を全部、ちょうど 1 度ずつ振り分けよ。tdd＝直す前に落ち、直した後に通るテストをリポジトリのテスト一式に"
             "書ける単位。direct＝先にテストを書けない単位（文書・指示書・注記・設定だけの直しなど）で、理由を 10 字以上で書く。"
             "この段では作業ツリーを変えるな。",
    "test": "今の単位の欠陥を再現する、今は落ちるテストだけを書け（実装は直すな。テストのファイルの外を触るな。「今の単位と一緒に"
            "直す単位」の節が在れば、その単位も今の単位に含める）。brief に受け入れの"
            "テスト（tests）が在る単位は、その id の名前でテストを書いて名指しに入れ、brief の red_kind の形で落とせ（assertion＝断言の"
            "失敗・exception＝期待した例外が出ない。宣言した名前（adds）の失敗は赤・宣言の外は赤に数えない）。案どおりに書いて赤にならない・赤の形が違うなら、"
            "テストを曲げず phase conflict で申し出よ。brief に受け入れのテストが無い単位は、テストを今の版に在る名前だけで再現するか、"
            "import をテストの中に入れよ。機械が一式を走らせ、名指しのテストが failure で落ち、元で通っていた"
            "テストが通ることを確かめる（error・もう通る・飛ばされた、は拒む）。",
    "fix": "今の単位だけを直せ（「今の単位と一緒に直す単位」の節が在れば、その単位も）。テストのファイルは変えるな（凍っている。"
           "テストの誤りに気づいたら直さずに what に書け）。機械が一式を"
           "走らせ、名指しのテストと元で通っていたテストが通ることを確かめる。緑の後に整えたい所（重複・名前・不要になったコード）が"
           "在る時だけ refactor の declared を true にし、why に理由を 10 字以上で書け。申告が無ければ整えの段は来ない（brief の "
           "refactor.declared が true の単位は申告なしでも来る）。",
    "refactor": "この段は、fix の段で申告した単位か、brief で申告した単位だけに来る。申告した所を緑のまま整えよ（テストのファイルは"
                "変えない）。整える物が無くなっていれば何も変えずに返せ。変えたなら機械がもう 1 回緑を確かめる。",
}


def _briefs(board_dir: pathlib.Path) -> list:
    """盤面の今の周の brief（planbrief.cut_at。盤面を開き直して凍結する。盤面の無い置き場は []）。控えが壊れていれば盤面を止めて
    （fixrules.brief_halt）理由の Broken（brief の無い指示書として続けない）"""
    try:
        return planbrief.cut_at(board_dir)
    except planbrief.LedgerBroken as e:
        try:
            b = entry.open_board(board_dir, allow_halted=True)
        except board.BoardGap:
            b = None
        raise Broken(fixrules.brief_halt(b, e)) from None


# 前に済んだ単位の引き継ぎ（依頼 243 の 2）。単位ごとに新しい会話で起こしても、前の単位が何を変えたかを会話の履歴でなく
# 機械が状態から書いて渡す（prep の今の単位の節の後。並べの枝の 2 つ目からの単位の決まりのファイルにも）
HANDOFF_HEAD = promptsection.Section("## 前の単位の引き継ぎ（機械が状態から書いた物）", source="fn:tddloop.handoff_lines")


def handoff_lines(st) -> list:
    """今の単位より前に済んだ単位の 1 行ずつ（単位の key・直したファイル・緑にしたテスト・整え・direct に回した理由）。無ければ空"""
    rows = []
    for k in [*(st.get("lanes") or {}).get("done_keys", []), *st["queue"][:st["cur"]]]:
        u = st["units"].get(k)
        if not u:
            continue
        if u.get("gave_up"):
            rows.append(f"- {k}: 諦めて direct に回した（木は単位の頭に戻した。修正役が直す）: {u.get('why', '')[:200]}")
            continue
        if u.get("route") == "parked":
            rows.append(f"- {k}: 食い違いの申し出で止めた（木は単位の頭に戻した）")
            continue
        if u.get("covered_by"):
            rows.append(f"- {k}: 同じ修正案の項目の単位 {'、'.join(u['covered_by'])} の段で一緒に直した（受け入れのテスト "
                        f"{', '.join(u.get('tests') or [])} は輪が赤→緑を確かめ済み）")
            continue
        bits = [f"直したファイル {', '.join(u.get('files') or []) or 'なし'}",
                f"緑にしたテスト {', '.join(u.get('tests') or []) or 'なし'}"]
        if u.get("refactor"):
            bits.append(f"整え {u['refactor']}")
        rows.append(f"- {k}: " + "・".join(bits))
    if not rows:
        return []
    return [HANDOFF_HEAD, "", "前の単位の直しは作業ツリーに在る（緑の木）。戻したり作り直したりするな。", ""] + rows + [""]


# 今の単位と一緒に直す単位（同じ修正案の項目の後の単位。together）の節の見出し（prep と並べの枝の単位の決まりのファイル）
TOGETHER_HEAD = promptsection.Section("## 今の単位と一緒に直す単位（同じ修正案の項目。1 つの brief と 1 つのやり方を共にする）", source="fn:tddloop._together_lines")


def _items(st, k) -> set:
    """単位 k の約束の修正案の項目の番号（約束が無ければ空）"""
    return set((_contract(st, k) or {}).get("items") or [])


def together(st, k) -> list:
    """単位 k の段で一緒に直す単位: 順（queue）で k より後の tdd の単位のうち、約束の受け入れのテストを持ち、載る修正案の項目が
    全部 k の項目にも在る物（順の並び）。k の段は項目の受け入れのテストを全部名指して緑にする（_test の want）ので、その単位の
    直しも要る。k の段が緑に届けば、その単位は機械が閉じる（_close_covered。同じ条件）。k に無い項目にも載る単位・約束の無い
    単位・別の項目の単位は入らない（今どおり「この後の単位（今は手を付けるな）」。その単位は自分の段で赤を書く）"""
    mine = _items(st, k)
    if not mine or k not in st.get("queue", []):
        return []
    later = st["queue"][st["queue"].index(k) + 1:]
    return [q for q in later if (st["units"].get(q) or {}).get("route") == "tdd" and _plan_tests(st, q)
            and _items(st, q) <= mine]


def _together_lines(st, k) -> list:
    """指示書の「今の単位と一緒に直す単位」の節（together が空なら []）"""
    keys = together(st, k)
    if not keys:
        return []
    return [TOGETHER_HEAD, "",
            "次の単位は今の単位と同じ修正案の項目に載る。この単位の段（test・fix・refactor）で今の単位と一緒に扱え: test の段は"
            "項目の受け入れのテストを全部名指して赤にし、fix の段はこれらの単位の直しも含めて名指しを緑にする。緑に届けば機械が"
            "これらの単位を閉じる（別の段は来ない）。", ""] + [f"- {q}" for q in keys] + [""]


DO_HEAD = promptsection.Section("## この段ですること", source="fn:tddloop.prep")
DUTY_HEAD = promptsection.Section("## 直す義務の単位", source="fn:tddloop.prep")
NOW_HEAD = promptsection.Section("## 今の単位", source="fn:tddloop.prep")
RUN_HEAD = promptsection.Section("## テストの回し方", source="fn:tddloop.prep")
REPLY_HEAD = promptsection.Section("## 返す JSON", source="fn:tddloop.prep")
STEP_TITLE = promptsection.Section("# TDD の輪の指示書（{count} 回目・段 {phase}）", source="fn:tddloop.prep")


def prep(state_file, values: dict | None = None, repo=None) -> dict:
    """節 tdd-prep。今の段の指示書を組み（fixrules.tdd_render: 修正の決まりの正本・TDD の決まり・今の段の約束・run の値）、状態の
    置き場の next.md に書き、{prompt_file} を返す。
    values は fixrules.TDD_VALUES の run の値（義務の単位は状態の物を使う。欠けは空）。repo は差分から変更の種類を選ぶ根（None は見ない）。
    題の次に brief の節（planbrief.head_text）: 振り分けの段は直す義務の単位の全部、ほかの段は今の単位 1 つの brief。行の
    「単位」はその段で直す単位だけで、項目のほかの単位には「今は直すな」と添える。
    借りたスキルの座（seat.section）を載せる。写しが壊れていれば Broken。
    輪が済んでいる（状態の done）か段 lanes（並べの周。輪の外の枝の輪が回す）なら、何も書かずに {"prompt_file": "", "go": False}:
    確かめの節が状態にそれを保存した後、Archon が輪の済みを記録する前に止まった run を、Archon の resume は輪の 1 周目から回し直す
    （役の節は when: で飛び、確かめ step は返答 None で何も動かさずに輪を抜ける。並べの枝の輪の tddlanes.lane_prep と同じ形）。
    書いた後に、包みが単位の切れ目で会話を切る鍵（write_key。印 UNIT_NODES の全部）を書く。単位が替わった周の役は新しい会話で起き（依頼 243 の 2）、
    前の単位の物は引き継ぎの節（handoff_lines）だけで渡る"""
    st = _load(state_file)
    if _over(st):   # resume で 1 周目から回し直された済んだ輪: 役を起こさない（YAML の役の when: が go を読む）
        return {"prompt_file": "", "go": False}
    path = pathlib.Path(st["work"]) / PROMPT
    briefs = _briefs(path.parent.parent)   # 状態の置き場は盤面の tdd-<k>
    phase = st["phase"]
    title = STEP_TITLE.format(count=st['iterations'] + 1, phase=phase)
    lines = [DO_HEAD, "", DO[phase], ""]
    if phase in ("fix", "refactor") and st.get("test_cmd_gate") == GATE_ON and _cur(st)["unit_key"] not in st.get("light", []):
        lines += [f"緑の後に機械が run の test_cmd（`{st['test_cmd']}`）も走らせる。これも緑にせよ。", ""]
    if phase == "route":
        lines += [DUTY_HEAD, ""] + [f"- {k}" for k in _owed(st)] + [""]
        brief = planbrief.head_text(planbrief.for_units(briefs, _owed(st)), _owed(st))
    else:
        u = st["units"][st["queue"][st["cur"]]]
        both = together(st, u["unit_key"])
        brief = planbrief.head_text(planbrief.for_units(briefs, [u["unit_key"]]), [u["unit_key"], *both])
        lines += [NOW_HEAD, "", f"- {u['unit_key']}", ""]
        lines += _together_lines(st, u["unit_key"])
        back = ((st.get("lanes") or {}).get("back") or {}).get(u["unit_key"])
        if back:
            lines += [f"- 並べで済まなかった単位（{back['why'][:300]}）。この作業ツリーで最初の段から直せ"
                      + (f"。前の試みの差分 {back['patch']}（当たっていない。参考に読んでよい）" if back.get("patch") else ""), ""]
        if u["tests"]:
            lines += [f"- 名指しのテスト: {', '.join(u['tests'])}", f"- テストのファイル（凍っている）: {', '.join(u['test_files'])}", ""]
        lines += handoff_lines(st)
        left = [q for q in st["queue"][st["cur"] + 1:] if q not in both]
        if left:
            lines += ["この後の tdd の単位（今は手を付けるな）: " + " / ".join(left), ""]
    lines += [RUN_HEAD, "",
              f"リポジトリの根で `{st['exe']} <JUnit XML の書き先>`（書き先は /tmp の下など作業ツリーの外に）。"
              "機械は名指しを実行器の後ろに絶対パスの node id で足して回す（実行器の既定の一覧の外に書いたテストも載る）。"
              "自分で回す時も同じ形で足せる。", "",
              REPLY_HEAD, "", RETURN[phase], "", RETURN_CONFLICT]
    vals = {**{k: "" for k in fixrules.TDD_VALUES}, **(values or {}),
            "open_units": json.dumps(_owed(st), ensure_ascii=False)}
    n = st["iterations"] + 1
    lang = fixrules.lang_at(path.parent.parent)   # 状態の置き場は盤面の tdd-<k>
    try:
        seat_text = seat.section("tdd")
    except ValueError as e:
        raise Broken(f"TDD の輪の座を組めない: {e}") from None

    def build(kinds):
        try:
            return fixrules.tdd_render(vals, phase, "\n".join(lines), title=title, reason=st["reason"], kinds=kinds,
                                       iteration=n, brief=brief, seat=seat_text, lang=lang)
        except fixrules.Unfilled as e:
            raise Broken(f"TDD の輪の指示書を組めない: {e}")
    fixrules.write_prompt(path, repo, vals, build, n)
    key = f"{path.parent.name}:{phase if phase == 'route' else st['queue'][st['cur']]}"
    for node in UNIT_NODES:
        write_key(adapter.session_key_path(str(path.parent.parent), node), key)
    return {"prompt_file": str(path), "go": True}


def _over(st: dict) -> bool:
    """輪を抜けた状態か: 済んだ（done）か、段 lanes（並べの周。輪の外の枝の輪と tdd-join が回す）。確かめ step の出口の done と同じ"""
    return bool(st["done"]) or st["phase"] == "lanes"


def write_key(path, key: str) -> None:
    """包みが読む 1 行の印（run ごとの置き場の下）を書く: 単位の切れ目で会話を切る鍵（adapter.session_key_path。依頼 243 の 2。鍵は
    輪の置き場の名と今の単位、振り分けの段は route）と、並べの枝の役の cwd の単位の worktree（adapter.lane_tree_path）。書けなければ
    古い印を消す（鍵が読めない包みは今どおり会話を継ぎ、worktree の印が読めない包みは枝の役を起こさない。支度は止めない）"""
    path = pathlib.Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(" ".join(key.splitlines()).strip() + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- 返答の確かめ（節 tdd-step）
def _blank(s) -> bool:
    return not isinstance(s, str) or len(s.strip()) < MIN_WHY


def _paths(v, name) -> tuple:
    """空でない文字列の配列 → (正規化したパスの一覧, 問題)"""
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
        return [], [f"{name} は空でない文字列の配列"]
    out = [posixpath.normpath(x.strip()) for x in v]
    bad = [x for x in out if x.startswith("/") or x == ".." or x.startswith("../")]
    return out, ([f"{name} はリポジトリの根からの相対パス（{bad}）"] if bad else [])


def _run(st, repo, named=(), files=(), full=False):
    """実行器を 1 回走らせ、走らせて出来たファイルを suite_made に積む（テストを書く段が触ったファイルの数えから外す）。
    名指しは絶対パスの node id、files（根からの相対の試験のファイル）は絶対パスで実行器の後ろに足す（段の外に書いたテストも
    同じ 1 回で集める。段の中の名指しとの重なりは run_suite が 1 件にまとめる。後ろの引数を解かない実行器なら段の外の名指しは
    居ないままで、赤・緑の確認が今どおり拒む）。full でなければ合図 ONLY_ENV を付ける（後ろの試験だけ）。
    last_run（消えたテストの照らしの元）: outcome・args（名指しと files）・whole（ファイルごと足したモジュール）・full"""
    pre = snapshot(repo)
    cases, code, why = run_suite(st["exe"], repo, pathlib.Path(st["work"]), st["runs"],
                                 _abs_ids(repo, named) + _abs_paths(repo, files), only=not full)
    st["runs"] += 1
    st["suite_made"] = sorted(set(st["suite_made"]) | set(touched(repo, pre, snapshot(repo))))
    if cases is None:
        raise _RunnerDown("; ".join(why))
    st["last_run"] = {"outcome": {_key(c): c["outcome"] for c in cases}, "args": [*named, *files],
                      "whole": sorted({impact._mod(f) for f in files}), "full": bool(full)}
    return cases, code


def _reached(st, repo, seeds=None, direct_only=True) -> tuple[list, bool]:
    """緑の回に足す試験 ——（根からの相対の pytest の試験のファイル, 一式を回すか）。単位の頭からの変更（走らせて出来たファイルを
    除く）を起点に地図を引き（impact.map の seeds。置き場は work/impact）、直に関わる試験（impact.select_tests の direct_only。
    起点か深さ 1。先の試験は受け付けと同じく線の最後のテストの段に任せる）のうち作業ツリーに在り、
    元の結末に載ったモジュール（元の一式が走らせた物。元で赤だった試験が届いただけで拒まれない）のファイル。地図が引けない・
    run_all なら ([], True)（合図なしの一式）。
    seeds（根からの相対のパス）を渡せばそれを起点にし、direct_only が偽なら地図が届く試験の全部を選ぶ（TDD の輪の並べの締めが、
    重なりのファイルを起点に広げる口。依頼 243 の並べの 3 段目）"""
    if seeds is None:
        seeds = set(touched(repo, st["unit_head"], snapshot(repo))) - set(st["suite_made"])
    seeds = sorted(seeds)
    try:
        sel = impact.select_tests(impact.map(repo, seeds=seeds, cache_dir=pathlib.Path(st["work"]) / "impact"),
                                  direct_only=direct_only)
    except (RuntimeError, OSError, ValueError):
        return [], True
    if sel["run_all"]:
        return [], True
    base = {impact._junit_module({"classname": k.partition("::")[0]}) for k in st["baseline"]}
    return [f for f in sel["selected"] if PYTEST_FILE.match(posixpath.basename(f)) and (pathlib.Path(repo) / f).is_file()
            and impact._mod(f) in base], False


def _next_head(prev: dict, run: dict) -> dict:
    """次の単位の頭の回（純粋）: 一式の回（full）はそのまま。絞った回は、前の頭の結末に、その回の結末を重ねた物（ファイルごと
    走ったモジュール（whole）の前の行は捨てる。走っていないモジュールは前の頭の結末のまま）。重ねた回は同じ選びの回に数えない
    （args は None）"""
    if not run or run.get("full", True):
        return run
    whole = set(run.get("whole") or [])
    kept = {k: o for k, o in prev.get("outcome", {}).items()
            if impact._junit_module({"classname": k.partition("::")[0]}) not in whole}
    return {"outcome": {**kept, **run["outcome"]}, "args": None, "whole": [], "full": False}


def _cur(st) -> dict:
    return st["units"][st["queue"][st["cur"]]]


def _covered_by(st, k) -> list:
    """単位 k を一緒に直した、緑に届いた tdd の単位（順の並び）。k の約束の受け入れのテスト（と書き換えの名指し）が在って全部
    輪が赤→緑を確かめ済み（_verified）で、k の修正案の項目を全部持つ緑の単位が在る時だけ（その単位の段が k を together に並べた
    条件と同じ）。ほかは []"""
    ids = {_norm_id(t["id"]) for t in _plan_tests(st, k)} | {_norm_id(i) for i in _plan_rewrites(st, k)}
    mine = _items(st, k)
    if not ids or not mine or not ids <= _verified(st):
        return []
    return [g for g, u in st["units"].items() if g != k and u.get("route") == "tdd" and u.get("green") == "ok"
            and not u.get("covered_by") and mine <= _items(st, g)]


def _close_covered(st) -> None:
    """順の今の単位が、同じ修正案の項目の前の単位の段で一緒に直されていれば（_covered_by）、段を回さずに閉じて次へ進む（続く限り）。
    閉じた単位は赤・緑とも ok で、名指しは約束の受け入れのテスト、テストのファイル・直したファイル・整え・test_cmd は一緒に直した
    単位の物を写し（軽量で走らせなかった印 CMD_LIGHT は、閉じた単位も軽量の時だけ）、赤の種類は名指しを確かめた緑の単位の全部から
    引き、covered_by にその単位を、why に一緒に直したことを書く"""
    while st["cur"] < len(st["queue"]):
        k = st["queue"][st["cur"]]
        by = _covered_by(st, k)
        if not by:
            return
        src = st["units"][by[0]]
        tests = [t["id"] for t in _plan_tests(st, k)] + [i for i in _plan_rewrites(st, k)]
        want = {_norm_id(x) for x in tests}
        kinds = {t: kd for v in st["units"].values() if v.get("route") == "tdd" and v.get("green") == "ok"
                 for t, kd in (v.get("red_kinds") or {}).items() if _norm_id(t) in want}   # 確かめた単位の全部から
        st["units"][k].update(red="ok", green="ok", tests=tests, test_files=list(src.get("test_files") or []),
                              test_hashes=dict(src.get("test_hashes") or {}), red_kinds=kinds,
                              files=list(src.get("files") or []), refactor=src.get("refactor", ""),
                              refactor_why=src.get("refactor_why", ""), covered_by=by,
                              test_cmd="" if src.get("test_cmd") == CMD_LIGHT and k not in st.get("light", []) else src.get("test_cmd", ""),
                              what=f"同じ修正案の項目の単位 {'、'.join(by)} の段で一緒に直した",
                              why=f"同じ修正案の項目の単位 {'、'.join(by)} の段で一緒に直した（受け入れのテストは輪が赤→緑を確かめ済み）")
        st["cur"] += 1


def _next_unit(st, repo) -> None:
    """次の単位の頭を固める。機械が戻した木（諦め・申し出・direct_why）もここを通るので、前の段の印（handoff）もここで進める。
    同じ修正案の項目の前の単位の段で一緒に直された単位は、段を回さずに閉じる（_close_covered）"""
    _close_covered(st)
    if st["cur"] < len(st["queue"]):
        head = snapshot(repo)
        st.update(phase="test", tries=0, reason="", unit_head=head, handoff=head, green_tree="")
    else:
        st["done"] = True


def _to_direct(u, stage, why, probs=()) -> None:
    u.update(route="direct", gave_up=stage, why=why, problems=list(probs)[:10])


def _route(st, reply, repo) -> list:
    rows = reply.get("units")
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("unit_key"), str) for r in rows):
        return ["units は {unit_key（文字列）, route, why} の配列"]
    errs = []
    moved = sorted(set(touched(repo, st["handoff"], snapshot(repo))) - set(st["suite_made"]))
    if moved:
        errs.append(f"振り分けの段で作業ツリーを変えた: {moved[:5]}（この段では何も書かない）")
    keys = [r.get("unit_key") for r in rows]
    owed = _owed(st)
    errs += [f"'{k}' を 2 度以上振った" for k in dict.fromkeys(k for k in keys if keys.count(k) > 1)]
    errs += [f"直す義務の単位 '{k}' を振っていない" for k in owed if k not in keys]
    errs += [f"'{k}' は振らない（{_not_owed_why(st, k)}）" for k in dict.fromkeys(k for k in keys if k not in owed)]
    for r in rows:
        if r.get("route") not in ("tdd", "direct"):
            errs.append(f"'{r.get('unit_key')}' の route は tdd か direct（{r.get('route')!r}）")
        elif r["route"] == "direct" and _blank(r.get("why")):
            errs.append(f"'{r.get('unit_key')}' は direct なのに、先にテストを書けない理由（why。{MIN_WHY} 字以上）が無い")
        bound = _plan_tdd(st, r["unit_key"]) if r.get("route") == "direct" else ""
        if bound:
            errs.append(bound)
    if errs:
        return errs
    st["order"] = keys
    st["units"] = {r["unit_key"]: _unit(r["unit_key"], r["route"], (r.get("why") or "").strip() if r["route"] == "direct" else "")
                   for r in rows}
    st["queue"] = [k for k in keys if st["units"][k]["route"] == "tdd"]
    st["cur"] = 0
    _next_unit(st, repo)
    return []


def _contract(st, k) -> dict | None:
    """単位 k の約束（start が plan_contract で組んだ状態の contract の行）。約束の無い単位・約束の無い run は None"""
    return (st.get("contract") or {}).get(k)


def _plan_tdd(st, k, how="direct に振れない") -> str:
    """約束で tdd の単位を direct へ回す返答を拒む文（約束が無いか tdd でなければ空）"""
    c = _contract(st, k)
    if not c or c.get("route") != "tdd":
        return ""
    return (f"'{k}' は承認済みの修正案で tdd（受け入れのテスト {len(c.get('tests') or [])} 本）——{how}。"
            "案の前提が誤りなら phase conflict で申し出よ")


def _norm_id(test_id: str) -> str:
    """名指しのパスの部分を posixpath.normpath で整えた id（`./a.py::T::t` と `a.py::T::t` を同じに見る）"""
    path, sep, rest = test_id.strip().partition("::")
    return posixpath.normpath(path) + sep + rest


def _plan_tests(st, k) -> list:
    """単位 k の約束の受け入れのテスト [{id, red_kind}]（約束が無ければ空）"""
    return (_contract(st, k) or {}).get("tests") or []


def _plan_rewrites(st, k) -> list:
    """単位 k の約束の書き換えの名指し（修正案の rewrite_tests の id。planmarks.rewrites と同じ行から作った物。約束が無ければ空）"""
    return (_contract(st, k) or {}).get("rewrites") or []


def test_functions(src: str, path: str) -> dict[str, str]:
    """.py の中身 src から、名前が test で始まる関数（モジュールの直下と、クラスの直下のメソッド。入れ子のクラスも辿る）の
    id（pytest の node id の形 `<path>::<クラス>[::<内のクラス>…]::<名前>` か `<path>::<名前>`）→ その関数の源
    （ast.get_source_segment。デコレータの行から）。構文が読めない・path が .py でなければ {}。純粋"""
    if not path.endswith(".py"):
        return {}
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return {}
    out = {}

    def take(node, head):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            top = min([node.lineno] + [d.lineno for d in node.decorator_list])
            span = ast.Constant(value=None, lineno=top, col_offset=node.col_offset, end_lineno=node.end_lineno,
                                end_col_offset=node.end_col_offset)   # デコレータの行から本体の終わりまで
            out[f"{head}::{node.name}"] = ast.get_source_segment(src, span) or ""

    def walk(body, head):
        for node in body:
            take(node, head)
            if isinstance(node, ast.ClassDef):
                walk(node.body, f"{head}::{node.name}")

    walk(tree.body, path)
    return out


def _unnamed_edits(repo, tree: str, files: list[str], allowed: set[str]) -> list[str]:
    """files のうち木 tree に在った .py で、木の時の test_functions に在った id の源が変わった・消えた物のうち、allowed に無い
    id（_id_base で整え、parametrize の `[…]` を落として比べる）。import の行・補助の関数・新しいテストは見ない。今の中身が構文として読めなければ、木の時の
    test* 関数は全部消えた側に数える（拒む側。実行器の結末は消えたテストを数えない）。.py でないファイルは見ない（関数の幅が引けない）"""
    ok = {_id_base(a) for a in allowed}
    py = [f for f in files if f.endswith(".py")]
    there = set(git_names(repo, "ls-tree", "-r", "--name-only", tree, "--", *py)) if py else set()
    out = []
    for f in py:
        if f not in there:
            continue   # 木に無かった（この段で足した）ファイル
        old = git(repo, "show", f"{tree}:{f}")
        p = pathlib.Path(repo) / f
        new = test_functions(p.read_text(encoding="utf-8", errors="replace") if p.is_file() else "", f)
        out += [i for i, body in test_functions(old, f).items() if new.get(i) != body and _id_base(i) not in ok]
    return out


def _id_base(test_id: str) -> str:
    """_norm_id から parametrize の `[…]` を落とした id（`t.py::test_x[1]` の許しは関数 `t.py::test_x` の書き換えを覆う）"""
    return _norm_id(test_id).split("[", 1)[0]


def _verified(st) -> set:
    """輪がもう赤→緑を確かめたテストの id（_norm_id。緑に届いた tdd の単位の名指し）"""
    return {_norm_id(t) for u in st.get("units", {}).values() if u.get("route") == "tdd" and u.get("green") == "ok"
            for t in u.get("tests") or []}


def verified_rewrites(state_file) -> list[str]:
    """約束の書き換えの名指し（修正案の rewrite_tests の id。書いたまま）のうち、輪が赤→緑を確かめた物。受け付けはこれを
    テストの変更の許しから外す（conflict.ruled_test_limits の skip_ids。輪の後の修正役に確かめなしで書き換えさせない）。
    状態が無い（輪の無い run）なら空"""
    if not state_file or not pathlib.Path(state_file).is_file():
        return []
    st = _load(state_file)
    done = _verified(st)
    ids = (i for c in (st.get("contract") or {}).values() for i in c.get("rewrites") or [])
    return [i for i in dict.fromkeys(ids) if _norm_id(i) in done]


def id_path(test_id: str) -> str:
    """名指し（`<パス>::…`）のパスの部分（posixpath.normpath で整えた物）"""
    return posixpath.normpath(test_id.strip().partition("::")[0])


def declared_test_files(st) -> set[str]:
    """宣言されたテストのファイル: 単位ごとの役の申告（test_files）と、承認済みの修正案の約束の受け入れのテスト（tests）・書き換えの
    名指し（rewrites）のパス。テストのファイルの見分け（is_test_file）の正本。純粋"""
    out = set()
    for u in (st.get("units") or {}).values():
        out |= {posixpath.normpath(f) for f in (u or {}).get("test_files") or [] if isinstance(f, str) and f.strip()}
    for c in (st.get("contract") or {}).values():
        ids = [t.get("id") for t in (c or {}).get("tests") or [] if isinstance(t, dict)] + list((c or {}).get("rewrites") or [])
        out |= {id_path(i) for i in ids if isinstance(i, str) and i.strip()}
    return out


def is_test_file(path: str, declared) -> bool:
    """テストのファイルか: 宣言（declared_test_files）に在るか、名の慣習（impact.is_test の module。テストの実行器が探す名の
    形で、言語の表でない。語の尾の形はテストのフォルダの下だけ）に当たるか。どちらにも当たらない実装のファイルは凍らせない。純粋"""
    return posixpath.normpath(path) in declared or impact.is_test(path) == "module"


def _moved_test_files(st, repo, exclude=()) -> list[str]:
    """単位の頭から変わったテストのファイル（is_test_file。走らせて出来たファイルと exclude を除く）"""
    moved = set(touched(repo, st["unit_head"], snapshot(repo))) - set(st["suite_made"]) - set(exclude)
    declared = declared_test_files(st)
    return sorted(f for f in moved if is_test_file(f, declared))


def _cut_lines(repo, tree: str, files: list[str]) -> list[str]:
    """files のうち木 tree に在った .py でないファイルで、tree から今の作業ツリーまでに行を消した・置き換えた物（足すだけは
    数えない。バイナリ・消したファイルは数える）。テストの関数の幅は言語に依らず引けないので、ファイルの単位で見る（.py は
    _unnamed_edits が関数の単位で見る）"""
    other = [f for f in files if not f.endswith(".py")]
    there = sorted(set(git_names(repo, "ls-tree", "-r", "--name-only", tree, "--", *other))) if other else []
    if not there:
        return []
    out = []
    for row in git(repo, "diff-tree", "-r", "-z", "--numstat", "--no-renames", tree, snapshot(repo), "--", *there).split("\0"):
        if row.count("\t") >= 2:
            _added, deleted, path = row.split("\t", 2)
            if deleted != "0":
                out.append(path)
    return sorted(out)


def _syntax_problems(repo, files) -> list[str]:
    """files のうち作業ツリーに在る .py で、構文として読めない物の文（_unnamed_edits が関数を全部『書き換えた』と並べる前に、
    構文の誤りとして名指す）"""
    out = []
    for f in files:
        p = pathlib.Path(repo) / f
        if not f.endswith(".py") or not p.is_file():
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError) as e:
            where = f"{getattr(e, 'lineno', None)} 行" if getattr(e, "lineno", None) else "行は不明"
            out.append(f"{f}: 構文が読めない（{getattr(e, 'msg', e)}・{where}）——テストのファイルを構文として読める形に直して出し直せ")
    return out


def _other_test_edits(st, u, repo) -> list[str]:
    """約束の在る単位の直し・整えの段: 単位の頭から変わったテストのファイル（_moved_test_files。単位のテストのファイルを除く）
    の構文の誤り（_syntax_problems）と、既存の test* 関数の本体の書き換え（_unnamed_edits。許しは無し）の文"""
    if _contract(st, u["unit_key"]) is None:
        return []
    files = _moved_test_files(st, repo, u["test_files"])
    bad = _syntax_problems(repo, files)
    if bad:
        return bad
    edits = _unnamed_edits(repo, st["unit_head"], files, set())
    cut = _cut_lines(repo, st["unit_head"], files)
    return [f"既存のテスト {edits[:10]} の本体を書き換えた——直し・整えの段ではテストを変えない"
            "（テストの誤りは what に書け。変えるしかないなら phase conflict で申し出よ）"] * bool(edits) + \
        [f"既存のテストのファイル {cut[:10]} の行を消した・置き換えた——直し・整えの段ではテストを変えない"
         "（.py でないテストのファイルは行を足すだけを通す。テストの誤りは what に書け。変えるしかないなら phase conflict で申し出よ）"] * bool(cut)


def _vanish_scope(files, declared=frozenset()) -> set | None:
    """消えたテストを照らすモジュール（impact._mod の名）。files のうちテストのファイル（is_test_file）だけを見る。conftest.py か
    .py でないテストのファイルに触れていれば None（一式の全部。.py でないファイルは JUnit の行とモジュールを言語に依らず結べない
    ので、分からない＝全部を照らす）。純粋"""
    files = [f for f in files if is_test_file(f, declared)]
    if any(posixpath.basename(f) == "conftest.py" or not f.endswith(".py") for f in files):
        return None
    return {impact._mod(f) for f in files}


def _vanished(head: dict, refs: list, now: dict, args: list, scope, skip, whole=()) -> list[tuple[str, str]]:
    """単位の頭の回（head: {outcome: 鍵 → 結末, args: 実行器の後ろの引数}）で通っていたテストのうち、今の結末（now）で
    飛ばされた物と、今の回と同じ選び（args）の回（refs のどれか）に居たのに今は居ない物の [(鍵, skipped か missing)]。
    scope（_vanish_scope）の外のモジュールと、skip の id（_id_base で parametrize の `[…]` を落として比べる。修正案の書き換え・
    輪が確かめた id）に当たる鍵は見ない。選びの違う回の居ないは数えない（後ろの node id だけを走らせる実行器）。ただし今の回で
    ファイルごと走ったモジュール（whole。impact._mod の名）の居ないは、選びに依らず数える。args が None の回（重ねた頭）は
    どの回とも同じ選びでない。純粋"""
    same = [r for r in refs if r.get("args") is not None and sorted(r["args"]) == sorted(args)]
    whole = set(whole)
    out = []
    for k, o in head.get("outcome", {}).items():
        cls, _, name = k.partition("::")
        if o != "passed" or (scope is not None and impact._junit_module({"classname": cls}) not in scope):
            continue
        case = {"classname": cls, "name": name.split("[", 1)[0]}
        if any(rules().match_case(_id_base(i), [case]) for i in skip):
            continue
        got = now.get(k)
        if got == "skipped" or (got is None and (any(k in r.get("outcome", {}) for r in same)
                                                  or impact._junit_module({"classname": cls}) in whole)):
            out.append((k, got or "missing"))
    return out


def _head_run(st) -> dict:
    """単位の頭の回（前の単位の緑の回。最初の単位は元の結末。前の版の状態に無ければ元の結末）"""
    return st.get("head_run") or {"outcome": st["baseline"], "args": []}


def _vanished_problems(st, u, cases, args, repo) -> list[str]:
    """約束の在る単位で、単位の頭で通っていたテストが飛ばされた・結末から消えた物の文（クラスの setUp の skipTest・モジュールの
    末尾で消すなど、名指しの外の本体を変えずに外す抜け道。写しの red_problems・green_problems は落ちた物しか見ない）。
    照らすのは単位の頭から変わったテストのファイルのモジュールだけ（conftest.py に触れたら全部）。居ないを数えるのは、同じ
    選びの回（単位の頭の回か、この単位の赤の回）に居た時と、今の回（last_run）でファイルごと走ったモジュールの時"""
    if _contract(st, u["unit_key"]) is None:
        return []
    refs = [_head_run(st)] + ([u["red_run"]] if u.get("red_run") else [])
    skip = [*_plan_rewrites(st, u["unit_key"]), *_verified(st)]
    gone = _vanished(_head_run(st), refs, {_key(c): c["outcome"] for c in cases}, list(args),
                     _vanish_scope(_moved_test_files(st, repo), declared_test_files(st)), skip, st["last_run"].get("whole") or ())
    return [f"単位 '{u['unit_key']}' の段で、単位の頭で通っていたテスト {k} が {o}（飛ばされた・一式の結末から消えた）——"
            "名指しの外の既存のテストを外すな（外すなら phase conflict で申し出よ）" for k, o in gone[:20]]


def _declared_name(d) -> str:
    """adds の名 1 つが宣言する名前（'(' より前を見る）: <パス>::<名前> は :: の後の最後の . の後・.py のファイルの名・パスは
    モジュールの名（__init__.py はディレクトリの名。拡張子 py と比べない。依頼 194c の receivers.py）・ほかは最後の . の後"""
    s = str(d).split("(", 1)[0].strip()
    if "::" in s:
        return s.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
    if s.endswith(".py"):
        p = posixpath.normpath(s[:-3])
        return posixpath.basename(posixpath.dirname(p)) if posixpath.basename(p) == "__init__" else posixpath.basename(p)
    return s.rsplit(".", 1)[-1]


def _declared_hit(case: dict, declared) -> bool:
    """名前・import の失敗の message が引く『無い名前』（'x' の引用の末尾の . の後）が、案が足すと宣言した名前（_declared_name）に
    完全一致するか。名前が引けない・declared が空なら False"""
    m = _MISSING.search(case.get("fail_message") or "")
    if not m:
        return False
    names = {_declared_name(d) for d in declared or ()}
    return m.group(1).rsplit(".", 1)[-1] in names - {""}


def _kind_problems(want: list, cases: list, declared=()) -> list:
    """名指しの各テスト {id, red_kind（案の宣言。書き換えの名指しは None）} の赤の種類（red_kind）を照らし、拒む物の文。
    拒むのは次の 2 つだけ（superpowers の TDD の『error でなく fail で落とす』）:
    - 名前・import の失敗（NAME_KINDS）のうち、無い名前が declared（案が足すと宣言した名前）に無い物（綴りの誤り）
    - 案が exception（期待した例外が出ない）なのに断言の失敗で落ちた
    ほかの例外の型（今のコードが例外で落ちる種類のバグ）と、案が assertion で期待した例外が出ない赤は、記録だけで通す。
    分からない（unknown）は通す"""
    out = []
    for t in want:
        want_kind = t.get("red_kind")
        c = rules().match_case(t["id"], cases)
        got = red_kind(c) if c else KIND_UNKNOWN
        if got in NAME_KINDS:
            if _declared_hit(c, declared):
                continue
            plan = f"案 {want_kind}" if want_kind in planmarks.RED_KINDS else "案に種類の宣言なし"
            out.append(f"{t['id']}: 赤の種類が狙いと違う（{plan}・実際 {got}）——宣言した名前（adds）の外の名前・import の失敗は狙いの赤でない"
                       "（綴りの誤り）。テストの誤りなら直して出し直し、案の前提の誤りならテストを曲げず phase conflict で申し出よ")
        elif want_kind == "exception" and got == "assertion":
            out.append(f"{t['id']}: 赤の種類が案と違う（案 {want_kind}・実際 {got}）——案は期待した例外が出ない赤。"
                       "テストの誤りなら直して出し直し、案の前提の誤りならテストを曲げず phase conflict で申し出よ")
    return out


def _test(st, reply, repo) -> list:
    u = _cur(st)
    if "direct_why" in reply:
        if _blank(reply["direct_why"]):
            return [f"direct_why は {MIN_WHY} 字以上"]
        bound = _plan_tdd(st, u["unit_key"], "direct_why で direct に渡せない")
        if bound:
            return [bound]
        restore(repo, st["unit_head"])
        _to_direct(u, "writer", reply["direct_why"].strip())
        st["cur"] += 1
        _next_unit(st, repo)
        return []
    tests = reply.get("tests")
    ok_tests = isinstance(tests, list) and tests and all(isinstance(t, str) and t.strip() for t in tests)
    errs = [] if ok_tests else ["tests は名指しのテスト（<パス>::<クラス>::<名前>）の空でない配列"]
    files, bad = _paths(reply.get("test_files"), "test_files")
    errs += bad
    # 約束の名指し（形が崩れていても、名指せた分で照らして同じ返答に並べる）
    done = _verified(st)   # 前の単位で赤→緑を確かめた id は名指しを強いず、凍っている（同じ項目が 2 つの単位にまたがる時）
    want = [t for t in _plan_tests(st, u["unit_key"]) if _norm_id(t["id"]) not in done]
    rws = [i for i in _plan_rewrites(st, u["unit_key"]) if _norm_id(i) not in done]
    named = {_norm_id(t) for t in tests if isinstance(t, str) and t.strip()} if isinstance(tests, list) else set()
    miss = [t["id"] for t in want if _norm_id(t["id"]) not in named]
    if miss:
        errs.append(f"承認済みの修正案の受け入れのテストを名指していない: {miss}——brief の tests の id の名前でテストを書き、tests に入れよ。"
                    "案の前提が誤りなら phase conflict で申し出よ")
    errs += [f"{i}: 承認済みの修正案が書き換えを名指した既存のテスト——書き換えて名指しに入れよ" for i in rws if _norm_id(i) not in named]
    if errs:
        return errs
    extra = sorted(set(touched(repo, st["unit_head"], snapshot(repo))) - set(files) - set(st["suite_made"]))
    if extra:
        return [f"申告したテストのファイルの外に触れた: {extra[:5]}——この段はテストだけを書く（実装は次の段）"]
    if _contract(st, u["unit_key"]) is not None:
        bad = _syntax_problems(repo, files)
        if bad:
            return bad
        frozen = _unnamed_edits(repo, st["unit_head"], files, set(rws))
        if frozen:
            return [f"名指しの外の既存のテスト {frozen[:10]} の本体を書き換えた——書き換えてよいのは修正案の rewrite_tests の名指しだけ"
                    "（それ以外を変えるなら phase conflict で申し出よ）"]
    cases, code = _run(st, repo, tests)
    probs = rules().red_problems(tests, cases, code, st["baseline"]) \
        or _kind_problems(want + [{"id": i, "red_kind": None} for i in rws], cases, (_contract(st, u["unit_key"]) or {}).get("names") or ())
    probs = probs or _vanished_problems(st, u, cases, tests, repo)
    if probs:
        return probs
    kinds = {t: red_kind(rules().match_case(t, cases) or {}) for t in tests}
    u.update(tests=tests, test_files=files, red="ok", test_hashes=hashes(repo, files), red_kinds=kinds, red_run=st["last_run"])
    st.update(phase="fix", tries=0, reason="")
    return []


def _frozen_moved(u, repo) -> list:
    now = hashes(repo, u["test_files"])
    return [f for f in u["test_files"] if now[f] != u["test_hashes"][f]]


def _green(st, u, repo) -> list:
    moved = _frozen_moved(u, repo)
    if moved:
        return [f"テストのファイルを赤の時から書き換えた: {moved}——テストは凍っている（テストの誤りは what に書け）"]
    other = _other_test_edits(st, u, repo)
    if other:
        return other
    files, full = _reached(st, repo)
    cases, code = _run(st, repo, u["tests"], files, full)
    return rules().green_problems(u["tests"], cases, code, st["baseline"], st["baseline_exit"]) \
        or _vanished_problems(st, u, cases, st["last_run"]["args"], repo) or _test_cmd_problems(st, repo)


def _plan_refactor_why(st, k) -> str:
    """約束の refactor（申告した項目の [{item, why}]）を「修正案の項目 n: <理由>」でつないだ物。申告が無ければ空の文字列"""
    return "；".join(f"修正案の項目 {r['item']}: {r['why']}" for r in (_contract(st, k) or {}).get("refactor") or [])


def _declared(reply) -> tuple[str, list]:
    """fix の返答の任意の欄 refactor（{declared, why}）→ (申告の理由（申告が無ければ空の文字列）, 問題)"""
    r = reply.get("refactor")
    if r is None:
        return "", []
    if not isinstance(r, dict) or not isinstance(r.get("declared"), bool) or not isinstance(r.get("why"), str):
        return "", ["refactor は {declared（true か false）, why（文字列）}"]
    if not r["declared"]:
        return "", []
    if _blank(r["why"]):
        return "", [f"refactor.declared が true なら why（整える理由）を {MIN_WHY} 字以上で書け（整えないなら declared を false に）"]
    return r["why"].strip(), []


def _fix(st, reply, repo) -> list:
    """緑を確かめ、整えの申告（役の refactor.declared か、約束の refactor）の在る単位だけ refactor の段へ。無ければ skipped で
    次の単位へ（緑の木が次の単位の頭）"""
    u = _cur(st)
    files = reply.get("files")
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files) or not isinstance(reply.get("what"), str) \
            or not reply["what"].strip():
        return ["files（直したファイルの配列）と what（何をどう直したか）が要る"]
    why, probs = _declared(reply)
    if probs:
        return probs   # 一式を走らせる前に拒む
    probs = _green(st, u, repo)
    if probs:
        return probs
    why = "；".join(filter(None, [why, _plan_refactor_why(st, u["unit_key"])]))   # 空でない申告の理由を全部
    u.update(green="ok", files=files, what=reply["what"].strip(), refactor_why=why)
    st.update(tries=0, reason="", green_tree=snapshot(repo), green_run=st["last_run"])
    if why:
        st["phase"] = "refactor"
        return []
    u["refactor"] = "skipped"
    st["head_run"] = _next_head(_head_run(st), st["green_run"])   # 次の単位の頭の回（緑の木の回）
    st["cur"] += 1
    _next_unit(st, repo)
    return []


def _refactor(st, reply, repo) -> list:
    u = _cur(st)
    if not isinstance(reply.get("what"), str) or not reply["what"].strip():
        return ["what（何を整えたか。整える物が無ければそう書く）が要る"]
    moved = set(touched(repo, st["green_tree"], snapshot(repo))) - set(st["suite_made"])
    if moved:
        probs = _green(st, u, repo)
        if probs:
            return probs
        st["green_run"] = st["last_run"]
    u["refactor"] = "ok" if moved else "none"
    st["head_run"] = _next_head(_head_run(st), st.get("green_run"))   # 次の単位の頭の回（緑の木の回）
    st["cur"] += 1
    _next_unit(st, repo)
    return []


def _give_up(st, repo, probs) -> None:
    """段の RETRY_MAX 回目の拒否"""
    head = f"{retry_max()} 回とも通らなかった: {probs[0][:200]}"
    if st["phase"] == "route":
        _abort(st, repo, "振り分けの返答が " + head, "route")
        return
    u = _cur(st)
    if st["phase"] == "refactor":
        restore(repo, st["green_tree"])
        u.update(refactor="reverted", problems=probs[:10])
        st["head_run"] = _next_head(_head_run(st), st.get("green_run"))   # 緑の木に戻したので、次の単位の頭の回は緑の回
    else:
        restore(repo, st["unit_head"])
        stage = "red" if st["phase"] == "test" else "green"
        _to_direct(u, stage, f"TDD の{'赤' if stage == 'red' else '緑'}の確認が " + head, probs)
    st["cur"] += 1
    _next_unit(st, repo)


def _abort(st, repo, why, stage) -> None:
    """残りの tdd の単位を全部 direct にして輪を抜ける（実行器が走らない・回数の上限・振り分けを諦めた）"""
    st["note"] = why
    if st["phase"] == "route":
        st["order"] = _owed(st)
        st["units"] = {k: _unit(k, "direct") for k in st["order"]}
        for u in st["units"].values():
            _to_direct(u, stage, why)
    else:
        u = _cur(st)
        if st["phase"] == "refactor":
            restore(repo, st["green_tree"])
            u["refactor"] = "reverted"
        else:
            restore(repo, st["unit_head"])
            _to_direct(u, stage, why)
        for k in st["queue"][st["cur"] + 1:]:
            _to_direct(st["units"][k], stage, why)
    st["done"] = True


def _conflict(st, reply, repo, try_query=None) -> tuple:
    """phase conflict（どの段でも）: 名指しが現物に在れば拒否に数えず、その単位を止める（振り分けの段は義務から外し、ほかの段は
    作業ツリーを単位の頭に戻して次の単位へ）。try_query は conflict.problems に渡す（query の申し出の correct_lines に判定者の
    問いを当てる。節 tdd-step が盤面から作る）。返り (問題, 申し出の 1 件)。盤面の控えに積むのは節 tdd-step（盤面を開く口）"""
    extra = sorted(set(reply) - {"phase", *conflict.FIELDS, conflict.CORRECT})
    if extra:
        return [f"食い違いの申し出の欄は phase と {list(conflict.FIELDS)}（query なら {conflict.CORRECT} も）だけ（{extra}）"], None
    item = {k: reply.get(k) for k in conflict.FIELDS}
    if conflict.CORRECT in reply:
        item[conflict.CORRECT] = reply[conflict.CORRECT]
    parked = st.setdefault("parked", [])
    if st["phase"] == "route":
        owed = set(_owed(st))
    else:
        owed = {st["queue"][st["cur"]]}
    probs = conflict.problems([item], repo=repo, board_dir=pathlib.Path(st["work"]).parent, owed=owed,
                              try_query=try_query, briefs=planbrief.by_unit_at(pathlib.Path(st["work"]).parent))
    if probs:
        return probs, None
    parked.append(item["unit_key"])
    st.setdefault("parked_why", {})[item["unit_key"]] = item["why_both_cannot_hold"]
    if st["phase"] == "route":
        if not owed - {item["unit_key"]}:   # 振る単位が残らない
            st.update(order=[], units={}, queue=[], cur=0, done=True)
        st["reason"] = ""
        return [], item
    u = _cur(st)
    restore(repo, st["unit_head"])
    u.update(route="parked", why=item["why_both_cannot_hold"])
    st["cur"] += 1
    _next_unit(st, repo)
    return [], item


def step(state_file, reply, repo, try_query=None, lanes=None, log=None) -> dict:
    """節 tdd-step。{ok（この返答を受けた）, done（輪を抜ける）, reason, phase（次の段）, conflict（止めた申し出の 1 件か None。
    節が盤面の控えに積む）, writes（書き込みの出どころの突き合わせの結果。節が盤面の trace に積む）}。
    申し出でない返答は、前の段の後から変わったファイルを書き込みの記録と欄 bash_writes に突き合わせてから段を確かめる。
    lanes は並べの口（tddlanes の module。節の script が渡す。tddloop からは import しない）: 状態の lanes_on が真なら振り分けの後に
    lanes.plan（段 lanes へ進めば輪 tdd-loop は抜け、枝の輪と tdd-join が回す）。無ければ並べない。段 lanes の状態で呼べば Broken。
    輪を抜けた状態（済んだ・段 lanes）に返答 None（支度が go: false を返して役が飛ばされた周。resume）なら、何も動かさずに
    {ok: True, done: True, reason: "", phase}。返答が在れば今どおり Broken。
    lanes を渡されて振り分けを受けた周で枝を切らなければ、出口の lanes_skipped に {reason, why, loop}（理由の語は tddlanes の SKIP_*。
    状態の lanes_off（入力）か lanes.plan の置いた lanes_skipped。loop は輪の盤面の置き場の名 tdd-<k>）を載せる（節が trace に積む）。
    log は書き込みの記録（既定は repo の writes.sink。並べの枝の確かめは単位の worktree を repo に、run の作業ツリーの記録を渡す）。
    前の段の印（handoff）は突き合わせを通った時と、機械が木を単位の頭に戻して次の単位へ移った時（申し出・諦め）だけ進める（拒まれた
    返答の出し直しや、振り分けの段の申し出で、記録の無い書き込みを流さない）"""
    st = _load(state_file)
    if reply is None and _over(st):   # 支度が go: false を返して役が飛ばされた周（resume）: 何も動かさずに輪を抜ける
        return {"ok": True, "done": True, "reason": "", "phase": "done" if st["done"] else st["phase"]}
    if st["done"]:
        raise Broken("TDD の輪は済んでいる（tdd-step を呼ぶ番でない）")
    phase = st["phase"]
    if phase == "lanes":
        raise Broken("並べの周（段 lanes）は輪の外の節（枝の輪と tdd-join）が回す（tdd-step を呼ぶ番でない）")
    t0, runs0 = time.monotonic(), st["runs"]   # 段ごとの呼び出しの記録（calls）の元。秒は書くだけで止める条件に使わない
    call = {"n": st["iterations"] + 1,
            "phase": "conflict" if isinstance(reply, dict) and reply.get("phase") == "conflict" else phase,
            "unit_key": "" if phase == "route" else st["queue"][st["cur"]]}
    item = None
    got = None
    skipped = None   # 振り分けを受けた周で並べなかった理由（lanes を渡された時だけ。出口の lanes_skipped）
    if isinstance(reply, dict) and reply.get("phase") != "conflict":
        moved = sorted(set(touched(repo, st["handoff"], snapshot(repo))) - set(st["suite_made"]))
        got = writes.check(reply, repo, moved, writes.sink(repo) if log is None else pathlib.Path(log))
        reply = got.pop("reply")
    if not isinstance(reply, dict):
        probs = ["返答が JSON のオブジェクトでない"]
    elif got and got["problems"]:
        probs = got["problems"]
    elif reply.get("phase") == "conflict":
        probs, item = _conflict(st, reply, repo, try_query)
    elif reply.get("phase") != phase:
        probs = [f"今の段は {phase}（返答の phase は {reply.get('phase')!r}）"]
    elif phase != "route" and reply.get("unit_key") != st["queue"][st["cur"]]:
        probs = [f"今の単位は '{st['queue'][st['cur']]}'（返答の unit_key は {reply.get('unit_key')!r}）"]
    else:
        try:
            probs = {"route": _route, "test": _test, "fix": _fix, "refactor": _refactor}[phase](st, reply, repo)
        except _RunnerDown as e:
            _abort(st, repo, f"{e.head}: {e}", "runner")
            probs = [st["note"]]
            call["phase"] = "runner"   # 機械の止まり（役の拒否と分ける）
        if phase == "route" and not probs and lanes is not None:
            if st["done"]:
                skipped = {"reason": "units", "why": "振り分けの後に TDD の輪で直す単位が残らない"}
            elif not st.get("lanes_on"):
                skipped = st.get("lanes_off") or {"reason": "off", "why": "並べの周が切られている（状態に理由が無い）"}
            elif not lanes.plan(st, repo):   # 範囲の引ける tdd の枝が 2 本以上なら枝ごとの worktree を切って段 lanes へ（輪はここで抜ける）
                skipped = st.get("lanes_skipped") or {"reason": "unknown", "why": "並べの口が理由を残さなかった"}
            if skipped is not None:
                skipped = {**skipped, "loop": pathlib.Path(st["work"]).name}
    if probs and not st["done"]:
        st["tries"] += 1
        st["reason"] = "\n".join(f"- {p}" for p in probs)
        if st["tries"] >= retry_max():
            _give_up(st, repo, probs)
    st["iterations"] += 1
    if not st["done"] and st["iterations"] >= MAX_ITERATIONS:
        _abort(st, repo, f"TDD の輪の回数の上限（{MAX_ITERATIONS} 回）に届いた", "budget")
    if st["done"]:
        _finish(st, repo)
    if got and not got["problems"]:   # 突き合わせを通った木だけ（機械が単位の頭に戻した木は _next_unit が進める）
        st["handoff"] = snapshot(repo)
    st.setdefault("calls", []).append({**call, "ok": not probs, "runs": st["runs"] - runs0,
                                       "secs": round(time.monotonic() - t0, 1)})
    _save(state_file, st)
    out = {"ok": not probs, "done": st["done"] or st["phase"] == "lanes",   # 段 lanes は輪を抜けて枝の輪へ（状態は済んでいない）
           "reason": "\n".join(probs), "phase": "done" if st["done"] else st["phase"], "conflict": item, "writes": got}
    if skipped is not None and not probs:
        out["lanes_skipped"] = skipped
    return out


RESULT_TITLE = promptsection.Section("# TDD の輪の結果（機械が書いた）", source="fn:tddloop._finish")
FIXED_HEAD = promptsection.Section("## 輪で直した単位（直さず、changes に 1 行を書け。テストのファイルは変えるな——受け付けが拒む。"
                                   "食い違いの裁定 fix_test_scope が範囲に並べた所だけは例外。修正案の rewrite_tests の名指しは輪で書き換えて凍結した）",
                                   source="fn:tddloop._finish")
CONFLICT_HEAD = promptsection.Section("## 食い違いで止めた単位（直すな。輪の後に裁定役が裁き、裁定が理由のファイルで届く）", source="fn:tddloop._finish")
OUT_HEAD = promptsection.Section("## 直す義務から外れた単位（直すな。not_done に理由を書け）", source="fn:tddloop._finish")
DIRECT_HEAD = promptsection.Section("## direct の単位（ここで直せ）", source="fn:tddloop._finish")

# 輪の役は回ごとの指示書を、輪の後の修正役は輪の結果を受ける。輪の役の名はここが持つので、輪の役が受ける決まり・brief・借りた
# スキルの座の節の行もここで組む（fixrules・planbrief はこの lib を import できない）
RECEIVES = [
    *(promptsection.Receive(role, head) for role in UNIT_NODES
      for head in (DO_HEAD, DUTY_HEAD, NOW_HEAD, RUN_HEAD, REPLY_HEAD, STEP_TITLE, HANDOFF_HEAD, TOGETHER_HEAD, seat.HEAD)),
    *(promptsection.Receive(role, fixrules.TDD_REJECT_HEAD) for role in UNIT_NODES),
    *planbrief.receives(UNIT_NODES),
    *(promptsection.Receive(role, head) for role in (recount.ROLE, recount.RULED_ROLE)
      for head in (RESULT_TITLE, FIXED_HEAD, CONFLICT_HEAD, OUT_HEAD, DIRECT_HEAD)),
]


def _finish(st, repo) -> None:
    """輪の後の修正役へ渡す summary.md と、凍ったテストのファイルの控え（frozen）"""
    passed = [st["units"][k] for k in st["order"] if st["units"][k]["route"] == "tdd"]
    st["frozen"] = hashes(repo, sorted({f for u in passed for f in u["test_files"]}))
    st["frozen_tree"] = snapshot(repo)
    lines = [RESULT_TITLE, ""]
    if st["note"]:
        lines += [f"輪を途中で抜けた: {st['note']}", ""]
    lines += [FIXED_HEAD, ""]
    for u in passed:
        lines += [f"- {u['unit_key']}", f"  - 名指しのテスト（機械が赤→緑を確かめた）: {', '.join(u['tests'])}",
                  f"  - テストのファイル: {', '.join(u['test_files'])}", f"  - 直したファイル: {', '.join(u['files'])}",
                  f"  - 直し: {u['what']}",
                  f"  - 整え: {u['refactor']}" + (f"（{u['refactor_why']}）" if u.get("refactor_why") else "")]
    parked = st.get("parked", [])
    if parked:
        lines += ["", CONFLICT_HEAD, ""]
        lines += [f"- {k}: {st.get('parked_why', {}).get(k, '')}" for k in parked]
    if st.get("excused"):
        lines += ["", OUT_HEAD, ""]
        lines += [f"- {k}: {why}" for k, why in st["excused"].items()]
    lines += ["", DIRECT_HEAD, ""]
    lines += [f"- {st['units'][k]['unit_key']}: {st['units'][k]['why']}" for k in st["order"] if st["units"][k]["route"] == "direct"]
    (pathlib.Path(st["work"]) / SUMMARY).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 輪の後
def frozen_problems(state_file, repo, allowed=(), *, since=None, skip_spans=()) -> list:
    """輪で緑になった単位のテストのファイルが、輪が済んだ時から変わっていれば、その文（状態が無ければ空）。
    allowed はテストの変更の許し（承認済みの修正案の rewrite_tests と裁定 fix_test_scope の範囲。conflict.test_permits を
    conflict.ruled_test_limits が引く）で、その中だけの変更は通す。
    since（木の sha）が在れば、凍結の基準を輪が済んだ時の中身でなくその木のファイルにする（後の輪の状態の handoff を渡す。
    後の輪が同じファイルに足したテストは後の輪の凍結で見る）。skip_spans は [(パス, 関数の名)]（名は `<クラス>::<名前>` か
    `<名前>`。test_spans の形）で、基準の木のその関数の範囲（_function_span）の変更だけを通す（直した項目の単位の古い受け入れの
    テストの関数）。
    .py のファイルに足しただけの物（_without_additions。新しい関数・クラス、既存のクラスの新しいメソッド、新しい名の import・代入で、
    既存のテストが読む名にも枠の掛け金にも当たらない物）は凍結に数えない（依頼 195i の 2: 別の項目が測りのテストを足しただけで人の
    関所を通らせない）。足した物を除いた中身が基準の木と同じ（コードの木もコメントの行も。_same_code）なら通し、許しの範囲が在れば
    足した物を除いた中身で範囲の外の塊を見る。既存の文の書き換え・消し・skip の印の追加は今どおり拒む"""
    if not state_file:
        return []
    st = _load(state_file)
    now = hashes(repo, st["frozen"])
    then = _tree_hashes(repo, since, st["frozen"]) if since else st["frozen"]
    moved = [f for f in st["frozen"] if now[f] != then[f]]
    base = since or st.get("frozen_tree") or st.get("handoff")
    scope = {}
    for lim in allowed:
        got = conflict.parse_limit(lim)
        if got:
            m = cite.CITE.match(lim.strip())
            # 1 行の指し（`<パス>:<行>`）だけが関数の幅に広がる。`<行>-<行>` は書いたとおり
            scope.setdefault(got[0], []).append(got[1] and (*got[1], bool(m) and not m["b"]))
    for path, name in skip_spans:
        if path in moved:
            line = _def_line(_tree_text(repo, base, path), name)
            if line:
                scope.setdefault(path, []).append((line, line, True))   # def の行の 1 行の指し（関数の幅に広がる）
    probs, outside = [], {}
    for f in moved:
        spans = scope.get(f)
        if spans and None in spans:
            continue
        was = _tree_text(repo, base, f) if f.endswith(".py") else None
        pruned = _without_additions(was, _now_text(repo, f), f)
        if not spans:
            if not any(_same_code(was, lines) for lines in pruned):
                probs.append(f)
            continue
        # 足した物を除いた中身のどれか（と今どおりの中身）で範囲の外の塊が無ければ通す。並べるのは一番少ない物
        bad = min([_hunks_outside(repo, base, f, spans), *(_hunks_outside(repo, base, f, spans, new=lines) for lines in pruned)],
                  key=len)
        if bad:
            outside[f] = bad
    out = [f"TDD の輪で凍ったテストのファイルを書き換えた: {probs}（輪で直した単位のテストは変えない）"] if probs else []
    out += [f"TDD の輪で凍ったテストのファイル {f} を、テストの変更の許し（修正案の rewrite_tests の名指しまたは裁定 fix_test_scope）"
            f"の範囲の外で書き換えた: 旧い行 {', '.join(bad)}"
            "（範囲に並べた行だけ直してよい。.py の 1 行の指しはその行を含む関数の全体）" for f, bad in outside.items()]
    return out


def _tree_text(repo, tree, path):
    """木 tree の path の中身（無い・読めなければ None）"""
    try:
        return git(repo, "show", f"{tree}:{path}") if tree else None
    except Unreadable:
        return None


def _tree_hashes(repo, tree, files) -> dict:
    """ファイル → 木 tree での中身の sha256（無ければ None。hashes と同じ形で比べる）"""
    out = {}
    for f in files:
        try:
            out[f] = hashlib.sha256(git(repo, "show", f"{tree}:{f}", text=False)).hexdigest()
        except Unreadable:
            out[f] = None
    return out


def _def_line(src, name: str):
    """.py の中身 src の関数 name（`<クラス>::<名前>` か `<名前>`。test_functions の id のパスの後ろ）の頭の行（デコレータが在れば
    その行）。無い・構文が読めなければ None"""
    if src is None:
        return None
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    want = name.split("::")

    def walk(body, chain):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and [*chain, node.name] == want:
                return min([node.lineno] + [d.lineno for d in node.decorator_list])
            if isinstance(node, ast.ClassDef):
                got = walk(node.body, [*chain, node.name])
                if got:
                    return got
        return None
    return walk(tree.body, [])


def test_spans(state_file, keys) -> list:
    """輪が tdd で緑にした単位のうち keys の単位の受け入れのテスト（単位の tests。名指しの id）を [(パス, 関数の名)] に
    （frozen_problems の skip_spans の形。名は id のパスの後ろ。parametrize の `[…]` は落とす）。状態が無ければ空"""
    if not state_file:
        return []
    st = _load(state_file)
    out = []
    for k in keys:
        u = st.get("units", {}).get(k) or {}
        if u.get("route") != "tdd" or u.get("green") != "ok":
            continue
        for t in u.get("tests") or []:
            path, sep, rest = _id_base(t).partition("::")
            if sep and (path, rest) not in out:
                out.append((path, rest))
    return out


def frozen_source(state_file, repo, *, since=None):
    """凍結の検査が行を読む輪の後の木（since が在ればその木。無ければ frozen_tree、それも無ければ handoff。frozen_problems の
    基準の木と同じ）から、パスの中身を読む口（conflict.ruled_test_limits の source。修正案の limit をその木でテストの id から
    引き直す）。状態・木・パスが読めなければ口は None を返す（許しを捨てる側）。状態は口を呼んだ時に読む"""
    def read(path):
        try:
            st = _load(state_file) if state_file else {}
            tree = since or st.get("frozen_tree") or st.get("handoff")
            return git(repo, "show", f"{tree}:{path}") if tree else None
        except (Broken, Unreadable):
            return None
    return read


def _now_text(repo, path):
    """作業ツリーの path の中身（無ければ None）"""
    p = pathlib.Path(repo) / path
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None


def _hunks_outside(repo, tree, path, spans, new=None) -> list:
    """輪が済んだ時の木の path と今のファイル（new が在ればその行の一覧）の差分の塊のうち、旧い側の行が spans のどれにも収まらない物
    （`a-b` の文）。span は (始め, 終わり, 1 行の指しか)。1 行の指しの .py は _function_span で関数の幅に広げる。
    木が無い・木に path が無い時はファイル全体を 1 つの外の塊にする"""
    if new is None:
        new = (_now_text(repo, path) or "").splitlines()
    try:
        old = git(repo, "show", f"{tree}:{path}").splitlines() if tree else None
    except Unreadable:
        old = None
    if old is None:
        return ["（輪が済んだ時の姿が読めない）"]
    wide = []
    for s, e, single in (sp for sp in spans if sp):
        w = _function_span(old, s) if single and path.endswith(".py") else None
        wide.append((*(w or (s, e)), w is not None))
    bad = []
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        ins = i2 == i1
        a, b = (i1 + 1, i2) if not ins else (max(i1, 1), max(i1, 1))   # 足しただけの塊は直前の行（頭なら 1 行目）で見る
        # 関数の幅に広げた span では、足しただけの塊が幅の直前（def・デコレータの真上）に入るのも幅の中
        if not any(s <= a and b <= e or (ins and f and s - 1 <= a <= e) for s, e, f in wide):
            bad.append(f"{a}-{b}" if b != a else str(a))
    return bad


# 凍ったファイルに足しただけの物（frozen_problems）。既存のテストに効く名・枠の掛け金は足した物に数えない
_MODULE_HOOKS = frozenset({"setUpModule", "tearDownModule", "setup_module", "teardown_module", "setup_function",
                           "teardown_function", "setup", "teardown", "load_tests", "pytestmark", "pytest_plugins",
                           "collect_ignore", "collect_ignore_glob"})
_CLASS_HOOKS = frozenset({*dir(unittest.TestCase), "setup_method", "teardown_method", "setup_class",
                          "teardown_class", "setup", "teardown", "pytestmark"})
_DOTTED = re.compile(r"^[A-Za-z_][\w.]*$")


def _old_names(tree) -> set:
    """木の中の名の全部（変数・属性・引数・キーワード・定義・import の名と、識別子か点つきの名の形の文字列の各部。
    fixture の名・getattr・mock.patch の的も含める）"""
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            out.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.alias):
            out.update(n.name.split("."))
            if n.asname:
                out.add(n.asname)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and _DOTTED.match(n.value):
            out.update(n.value.split("."))
    return out


def _bound(node, top: bool):
    """足してよい形の文が縛る名の一覧（足してよい形でなければ None）。モジュールの直下は関数・クラス・import（* と __future__ を
    除く）・名だけへの代入、既存のクラスの直下は関数だけ"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node.name]
    if not top:
        return None
    if isinstance(node, ast.ClassDef):
        return [node.name]
    if isinstance(node, ast.Import):
        return [a.asname or a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.module == "__future__" or any(a.name == "*" for a in node.names):
            return None
        return [a.asname or a.name for a in node.names]
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else None
    if targets is None or not all(isinstance(t, ast.Name) for t in targets):
        return None
    return [t.id for t in targets]


def _addable(node, src: str, names: set, top: bool) -> bool:
    """new の文 node が、既存のテストに効かない足した物か: 縛る名が旧い木の名（names）に無く、枠の掛け金（モジュールなら
    _MODULE_HOOKS・pytest_*、クラスなら _CLASS_HOOKS・_ で始まる名）でも dunder でもなく、デコレータに autouse が無い"""
    got = _bound(node, top)
    if not got:
        return False
    for n in got:
        if n in names or (n.startswith("__") and n.endswith("__")):
            return False
        if top and (n in _MODULE_HOOKS or n.startswith("pytest_")):
            return False
        if not top and (n in _CLASS_HOOKS or n.startswith("_")):
            return False
    return not any("autouse" in (ast.get_source_segment(src, d) or "autouse") for d in getattr(node, "decorator_list", []))


def _without_additions(old_src, new_src, path: str) -> list:
    """凍ったファイルの今の中身 new_src から足しただけの文（_addable。モジュールの直下と、旧い木にも在った直下のクラスの中）を
    除いた行の一覧の候補（足した文の直前に続く同じ字下げのコメントの行と空の行を、それぞれ除いた物と除かない物。足した所の前後の
    空の行が許しの範囲の外の塊にならないように）。.py でない・どちらかが
    読めない・構文が読めない・足した文が無ければ空（足した物を除けない＝今どおりファイルの変更で見る）"""
    if not path.endswith(".py") or old_src is None or new_src is None:
        return []
    try:
        old, new = ast.parse(old_src), ast.parse(new_src)
    except (SyntaxError, ValueError):
        return []
    names = _old_names(old)
    classes = {n.name for n in old.body if isinstance(n, ast.ClassDef)}
    picked = []
    for node in new.body:
        if _addable(node, new_src, names, True):
            picked.append(node)
        elif isinstance(node, ast.ClassDef) and node.name in classes:
            picked += [m for m in node.body if _addable(m, new_src, names, False)]
    if not picked:
        return []
    lines = new_src.splitlines()
    out = []
    for comments, blanks in ((True, True), (True, False), (False, True), (False, False)):
        drop = set()
        for node in picked:
            top = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            while comments and top > 1 and lines[top - 2].startswith(" " * node.col_offset + "#"):
                top -= 1
            while blanks and top > 1 and not lines[top - 2].strip():
                top -= 1
            drop.update(range(top, node.end_lineno + 1))
        got = [x for i, x in enumerate(lines, 1) if i not in drop]
        if got not in out:
            out.append(got)
    return out


def _same_code(old_src, lines) -> bool:
    """行の一覧 lines が旧い中身 old_src と同じコードか: コードの木（ast.dump。文字列の中の空の行も見る）が同じで、空でない行の
    並び（コメントも）が同じ。空の行の数だけの違いは通す"""
    if old_src is None:
        return False
    try:
        same = ast.dump(ast.parse(old_src)) == ast.dump(ast.parse("\n".join(lines)))
    except (SyntaxError, ValueError):
        return False
    return same and [x for x in old_src.splitlines() if x.strip()] == [x for x in lines if x.strip()]


def _function_span(old, line):
    """old（行の一覧）の line を含む最も外側の関数（メソッドも。クラスそのものには広げない）の幅 (始め, 終わり)。
    始めは最初のデコレータの行から、直前に続く def と同じ字下げのコメントの行まで上へ。
    関数の外の行・構文が読めない時は None（1 行のまま＝拒む側）"""
    try:
        tree = ast.parse("\n".join(old))
    except (SyntaxError, ValueError):
        return None
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top = min([node.lineno] + [d.lineno for d in node.decorator_list])
            if top <= line <= node.end_lineno and (best is None or top < best[1]):
                best = (node, top)
    if best is None:
        return None
    node, top = best
    while top > 1 and old[top - 2].startswith(" " * node.col_offset + "#"):   # def と同じ字下げのコメントだけ（前の関数の本体の末尾のコメントは字下げが深い）
        top -= 1
    return top, node.end_lineno


def suite_made(state_file) -> list:
    """実行器を走らせて出来たファイル（書き込みの出どころの突き合わせから外す。状態が無ければ空）"""
    return _load(state_file).get("suite_made", []) if state_file else []


def states(board_dir) -> list:
    """盤面の根の輪の状態 tdd-<k>/state.json を番号の順に（run の全部の輪。2 回目の修正の段の輪は 1 回目の後に起きる）。
    置き場が無ければ空"""
    got = []
    for d in pathlib.Path(board_dir).glob("tdd-*"):
        k = d.name[len("tdd-"):]
        if k.isdigit() and (d / STATE).is_file():
            got.append((int(k), d / STATE))
    return [p for _, p in sorted(got)]


def green_units(summary_file) -> set:
    """輪の要約 summary_file の隣の状態で、輪が緑にした単位（route が tdd・green が ok・諦めていない）の key。要約が空・状態が
    無い・読めない時は空（修正役の下請けを起こす単位を絞る節約の口なので、読めなくても止めず、全部の単位に下請けを起こす。
    依頼 243 の 2）"""
    if not summary_file:
        return set()
    try:
        st = _load(pathlib.Path(summary_file).parent / STATE)
    except Broken:
        return set()
    units = st.get("units") if isinstance(st, dict) else None
    return {k for k, u in (units or {}).items()
            if isinstance(u, dict) and u.get("route") == "tdd" and u.get("green") == "ok" and not u.get("gave_up")}


def suite_made_all(board_dir) -> set:
    """run の全部の輪（states）の suite_made の和（書き込みの出どころの突き合わせと案の項目の照らしが外す）"""
    return {f for p in states(board_dir) for f in suite_made(p)}


ACCEPT_RUN = "accept"   # 受け付けが走らせた回のログ・JUnit の名（suite-accept.log）
NO_SELECTED = "変えたファイルに当たる試験が無い"
PYTEST_FILE = re.compile(r"^(test_.*|.*_test)\.py$")   # pytest の既定の python_files（conftest.py・*-suite.py などは試験のモジュールでない）


def _args(root, files, kexpr) -> list:
    """受け付けが実行器に足す引数: 選んだ試験のうち root の中に在る pytest の試験のモジュール（絶対パス。.sh・.bats を渡すと
    収集器が無く一式ごと止まり、conftest.py・実行器の台本の .py を名指しすると pytest が型に依らず import する）と、段の中を
    絞る -k（一式を回す時は付けない）"""
    py = [f for f in files if PYTEST_FILE.match(posixpath.basename(f)) and (pathlib.Path(root) / f).is_file()]
    return [*_abs_paths(root, py), *(["-k", kexpr] if kexpr else [])]


def selected_problems(state_file, repo, rev) -> tuple:
    """(赤の文の一覧, 知らせ)。選ぶのは変更に直に関わる試験と名指しの試験（_named_files）だけで、届くだけの先の試験は
    final_left に残す。実行器の後ろに足すのは、選んだ試験のうちこの run で変えた・足したファイルだけ（ADR 0071 の
    3 の 1。届いただけの段の外の試験は手元で走らせない）。実行器の既定の一式の中は -k で選んだ全部のモジュールに絞る。
    実行器の無い run（状態が無い）・当たる試験が無い・実行器が走らない・選んだ試験が 1 件も走らなかった時は赤にせず知らせだけ。
    元の結末に無い試験の赤は、版の写しで同じ試験を回して、版でも赤なら外す（版の写しの結末は _base_reds が盤面の根に控え、
    受け付けの回をまたいで使い回す）"""
    if not state_file:
        return [], NO_SUITE
    st = _load(state_file)
    work = pathlib.Path(st["work"])
    m = impact.map(repo, rev=rev, diff=True, cache_dir=work / "impact")
    sel = impact.select_tests(m, direct_only=True, named=_named_files(st))
    st["final_left"], st["final_far"] = sel["left"], sel["far"]
    final = (f"。最後のテストの段に任せた {len(sel['left'])} 件（変更に直には関わらず届くだけ。受け付けは回さない）: "
             f"{', '.join(sel['left'])[:300]}") if sel["left"] else ""
    if sel["far"]:
        final += (f"。最後のテストの段に任せた、地図の遠く（深さ 2 以上）の分からない物 {len(sel['far'])} 件（受け付けは一式を回さない）: "
                  f"{', '.join(sel['far'])[:300]}")
    if not sel["run_all"] and not sel["modules"]:
        st["ci_left"] = []
        _save(state_file, st)
        return [], NO_SELECTED + final
    changed = set(m["seeds"]["from_diff"])
    files = [f for f in sel["selected"] if f in changed]
    kexpr = "" if sel["run_all"] else " or ".join(sel["modules"])
    pre = snapshot(repo)
    cases, code, why = run_suite(st["exe"], repo, work, ACCEPT_RUN, _args(repo, files, kexpr))
    st["suite_made"] = sorted(set(st["suite_made"]) | set(touched(repo, pre, snapshot(repo))))
    st["ci_left"] = _left_to_ci(sel["selected"], files, cases)
    _save(state_file, st)
    what = "一式（" + "・".join(sel["reasons"])[:200] + "）" if sel["run_all"] else \
        f"選んだ試験（ファイル {', '.join(files)[:300]}・-k {kexpr[:300]}）"
    ci = f"。手元で回さなかった {len(st['ci_left'])} 件（run はその緑を確かめない）: {', '.join(st['ci_left'])[:300]}" if st["ci_left"] else ""
    ci += final
    if cases is None:
        return [], f"{what}を走らせられない（{'; '.join(why)}）{ci}"
    if not cases:
        return [], (f"{what}が一式の結末に 0 件——選んだ試験が 1 件も走らなかった（-k が何にも当たらない・実行器が足した試験を"
                    f"拾わない。ログ {work / f'suite-{ACCEPT_RUN}.log'}）。新しい赤が無いことは確かめていない{ci}")
    reds = {_key(c): c for c in cases if c["outcome"] in ("failure", "error")
            and st["baseline"].get(_key(c)) not in ("failure", "error")}
    red = list(reds)
    fresh = [k for k in red if k not in st["baseline"]]
    tail = ""
    if fresh:
        old, why = _base_reds(st, repo, rev, files, kexpr)
        if old is None:
            tail = f"。元の結末に無い {len(fresh)} 件は版の姿で比べられず赤のまま（{'; '.join(why)}）"
        else:
            red = [k for k in red if k not in old]
    if not red:
        return [], f"{what}: {len(cases)} 件で新しい赤なし{ci}"
    # 行はテストのファイルごと（修正の受け付けが最後の回にパスで単位に結ぶ）。頭に選んだファイルの一覧を置かない（ほかの
    # ファイルの赤の行がそのパスを名指して、関わらない単位に結ばないように）
    label = "一式" if sel["run_all"] else f"選んだ試験（-k {kexpr[:300]}）"
    return [f"受け付けが走らせた{label}で、元で赤でなかった試験が赤{where}: {ids[:20]}（{len(ids)} 件。"
            f"ログ {work / f'suite-{ACCEPT_RUN}.log'}{tail}）——直した単位のどこかを直して出し直せ"
            for where, ids in _by_test_file(repo, [reds[k] for k in red]).items()], ""


def _by_test_file(repo, cases) -> dict:
    """赤の case をテストのファイルごとに分けた {「（ファイル <根からのパス>）」: [id]}（現れた順）。ファイルは case のモジュール
    （impact._junit_module）が impact._mod に等しいテストのファイル（impact.tree_files と impact.is_test）で、同じ名のモジュールが
    2 つ以上在れば全部を名指す。見つからない case の鍵は ""（パスを名指さない）"""
    files = {}
    for p in impact.tree_files(repo) or []:
        if impact.is_test(p) == "module":
            files.setdefault(impact._mod(p), []).append(p)
    out = {}
    for c in cases:
        hit = files.get(impact._junit_module(c) or "", [])
        out.setdefault(f"（ファイル {', '.join(hit)}）" if hit else "", []).append(_key(c))
    return out


def _left_to_ci(selected, run_files, cases) -> list:
    """選んだ試験のうち、手元で名指さず（run_files に無く）結末にもモジュールが 1 件も出なかった物（手元で回さなかった）。実行器の
    既定の段は対象ごとに違うので、段の一覧を写さず結末から決める。結末が無ければ名指さなかった物は全部"""
    ran = {impact._junit_module(c) for c in cases or []}
    return [t for t in selected if t not in run_files and impact._mod(t) not in ran]


def _named_files(st) -> list:
    """修正案の約束の受け入れ・書き換えのテストと、輪で名指したテストのファイル（根からの相対。受け付けは直に関わる試験に足す）"""
    ids = [t.get("id", "") if isinstance(t, dict) else str(t)
           for c in (st.get("contract") or {}).values() for t in [*(c.get("tests") or []), *(c.get("rewrites") or [])]]
    ids += [t for u in (st.get("units") or {}).values() for t in [*(u.get("tests") or []), *(u.get("test_files") or [])]]
    return sorted({posixpath.normpath(i.partition("::")[0]) for i in ids if i and i.strip()})


def final_left(state_file) -> list:
    """受け付けが直に関わらないので回さず、線の最後のテストの段に任せた試験（状態が無い・まだ選んでいなければ空）"""
    return _load(state_file).get("final_left", []) if state_file and pathlib.Path(state_file).is_file() else []


def final_far(state_file) -> list:
    """受け付けが一式を回す理由にせず最後のテストの段に任せた、地図の遠く（深さ 2 以上）の分からない物の理由（impact の far）"""
    return _load(state_file).get("final_far", []) if state_file and pathlib.Path(state_file).is_file() else []


def ci_left(state_file) -> list:
    """受け付けが手元で回さず 手元で回さなかった試験（状態が無い・まだ選んでいなければ空）。見せるだけの読み口なので、状態のファイルが
    無ければ空（受け付けの知らせの文にも同じ名が載る）"""
    return _load(state_file).get("ci_left", []) if state_file and pathlib.Path(state_file).is_file() else []


REV_CACHE = "accept-rev-cache.json"   # 版の写しの結末の控え（盤面の根。run の全部の輪と受け付けの回が使い回す）


def rev_id(repo, rev: str) -> str:
    """版 rev の commit の sha（引けなければ rev のまま。控えの鍵に使う: 名前が同じでも指す版が変われば別の鍵）"""
    try:
        return git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip() or rev
    except Unreadable:
        return rev


def exe_id(repo, exe) -> list:
    """実行器の控えの鍵: repo の中なら根からの相対パス（中身は版が決める。版の木の中の同じ物を走らせる）、外なら絶対パスと中身の sha"""
    p = pathlib.Path(exe)
    try:
        return ["repo", p.absolute().relative_to(pathlib.Path(repo).absolute()).as_posix()]
    except ValueError:
        return ["abs", str(p.absolute()), hashes(p.parent, [p.name])[p.name]]


def load_json(path: pathlib.Path, default):
    """控えのファイル（無い・読めない・形が違えば default。控えは使い回しの手がかりで、無くても走らせ直すだけ）"""
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return got if isinstance(got, type(default)) else default


def save_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _base_reds(st, repo, rev, files, kexpr) -> tuple:
    """(版 rev の姿で同じ試験を回して赤だった鍵の集合か None, 問題)。版の姿は一時の置き場に git archive で写して走らせ、
    作業ツリー・index・枝は動かさない。実行器が repo の中に在れば写しの中の同じ物を走らせる（自分の置き場から根を引く実行器が
    写しの根で走るように）。
    写しは版の姿だけ（今の木から何も写さない）なので、結末は版・実行器・後ろの引数（ファイルと -k）で決まる。走らせた結末は
    盤面の根の REV_CACHE に残し、同じ版・同じ実行器・同じ -k で、名指したファイルが前に走らせた回のファイルに含まれれば
    走らせずに使う（run の中で版は動かないので、受け付けの回・2 回目の修正の段をまたいで 1 回で足りる。195g は回ごとに 3 分半）。
    結末が取れなかった回は残さない"""
    cache = pathlib.Path(st["work"]).parent / REV_CACHE
    key = {"rev": rev_id(repo, rev), "exe": exe_id(repo, st["exe"]), "kexpr": kexpr}
    rows = load_json(cache, [])
    for r in rows:
        if isinstance(r, dict) and {k: r.get(k) for k in key} == key and set(files) <= set(r.get("files") or []):
            return set(r.get("reds") or []), []
    with tempfile.TemporaryDirectory(prefix="works-tdd-rev-") as td:
        copy = pathlib.Path(td) / "repo"
        try:
            tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", rev], capture_output=True, check=True).stdout
            with tarfile.open(fileobj=io.BytesIO(tar)) as t:
                t.extractall(copy, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        except (OSError, subprocess.CalledProcessError, tarfile.TarError) as e:
            return None, [f"版 {rev} を写せない（{type(e).__name__}: {e}）"]
        exe = pathlib.Path(st["exe"])
        try:
            inner = copy / exe.absolute().relative_to(pathlib.Path(repo).absolute())
            exe = inner if inner.is_file() else exe
        except ValueError:
            pass
        cases, _, why = run_suite(str(exe), copy, pathlib.Path(st["work"]), f"{ACCEPT_RUN}-rev", _args(copy, files, kexpr))
    if cases is None:
        return None, why
    reds = {_key(c) for c in cases if c["outcome"] in ("failure", "error")}
    save_json(cache, [*rows, {**key, "files": sorted(set(files)), "reds": sorted(reds)}])
    return reds, []


FIELDS = ("unit_key", "route", "why", "tests", "test_files", "red", "green", "refactor", "gave_up", "problems", "red_kinds",
          "test_cmd", "refactor_why")


def exit_fields(start_out: dict) -> dict:
    """出口の欄 tdd: {ran, suite, reason, units: [{unit_key, route, why, tests, test_files, red, green, refactor, gave_up, problems,
    red_kinds（名指しの id → 見た赤の種類）, test_cmd（"ok"＝緑の後に run の test_cmd も走らせて通った・CMD_LIGHT＝軽量の単位
    なので走らせなかった・""）,
    refactor_why（整えの申告の理由）}]}。refactor は ""・skipped（申告が無く整えの段を飛ばした）・none・ok・reverted。
    ran: true の出口には test_cmd: {gate（GATE_ON・GATE_SAME・GATE_OFF）, note（off の理由）} と calls（step 1 回ごとの
    {n, phase, unit_key, ok, runs, secs}。役の費用は Archon の出来事に在り、この行の順（tdd の節の起動の順）で後から結べる）も載る"""
    if not isinstance(start_out, dict) or not start_out.get("go"):
        so = start_out if isinstance(start_out, dict) else {}
        return {"ran": False, "suite": so.get("suite", ""), "reason": so.get("reason", ""), "units": []}
    st = _load(start_out["state_file"])
    if not st["done"]:
        raise Broken("TDD の輪が済んでいない（done の印が無い）")
    rows = [{f: st["units"][k][f] for f in FIELDS} for k in st["order"]]
    rows += [{**{f: _unit(k, "parked")[f] for f in FIELDS}, "why": st.get("parked_why", {}).get(k, "")}
             for k in st.get("parked", []) if k not in st["order"]]   # 振り分けの段で止めた単位
    out = {"ran": True, "suite": st["suite"], "reason": st["note"], "units": rows,
           "test_cmd": {"gate": st.get("test_cmd_gate", GATE_OFF), "note": st.get("test_cmd_note", "")},
           "calls": st.get("calls", [])}
    lanes = st.get("lanes") or {}
    if "out" in lanes:   # 並べの周を締めた run だけ（単位ごとの結末と枝の段の呼び）
        out["lanes"] = {"units": lanes["out"], "calls": lanes.get("calls", []), "reverted": lanes.get("reverted", []),
                        "shared": lanes.get("shared", []), "expect": lanes.get("expect", [])}
    return out


# 事後の関門の束（同じブロックの fixgates。計画 220 Task 4）が輪と同じ決まりで読む口の公開の別名（輪の中の名は変えない。
# 名指しの外の既存のテストの書き換え・赤の種類の照らし・名指しの node id・関数の幅・範囲の外の差分の塊。preflight F11・F13）
unnamed_edits = _unnamed_edits
kind_problems = _kind_problems
abs_ids = _abs_ids
function_span = _function_span
hunks_outside = _hunks_outside
