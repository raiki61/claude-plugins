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
  平の run（修正の形 current。fixshape.plain）は比べの基準なので 219 の前の振る舞い: 約束を読まない・test_cmd の関門は
  走らせずに off（理由 PLAIN_NOTE）・fix の段の後はいつも refactor の段へ（指示書の fix・refactor の段は 219 の前の文 PLAIN_DO）。
  形は start が 1 回だけ読んで状態の plain に置く（控えが壊れていれば Broken）
- tdd-loop の中: tdd-prep → prep（今の段の指示書を fixrules で組んで書く。full と delta の 2 つの形。頭に brief の節: 振り分けの段は
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
  - fix: その単位のテストのファイルが赤の時から変わっていない・写しの green_problems。約束の在る単位は、ほかのテストのファイル
    （TEST_FILE の名）の既存の test* 関数の本体も変えていない（_other_test_edits）・テストを飛ばした・消していない
    （_vanished_problems）。関門が on なら、そのうえで run の test_cmd も緑（_test_cmd_problems。赤は拒み、走らない時は実行器が
    走らない時と同じに輪を抜ける）。refactor の緑の確かめも同じ。
    緑の後、返答の任意の欄 refactor（{declared, why}）で役が理由（10 字以上）つきで申告した単位か、約束の refactor が真（修正案の
    項目の refactor.declared）の単位だけ refactor の段へ進み、理由を単位の refactor_why に残す。declared が true で理由が短ければ
    拒む（一式を走らせる前）。申告が無ければ単位の refactor を skipped にして次の単位へ（緑の木が次の単位の頭）
  - refactor: 緑の時から何も変えていなければ none。変えたなら fix と同じ確かめをもう 1 回
  - test・fix・refactor とも、名指しを絶対パスの node id で実行器の後ろに足し、合図 TDD_SUITE_ONLY=1（ONLY_ENV）を付けて走らせる
    （一式を回さない。解かない実行器は今どおり一式に足して走らせる）。赤の回は名指しだけ。緑の回（fix・変えた refactor）は名指しに、
    単位の頭からの変更が届く試験（impact.select_tests）のうち元の結末に載ったモジュールの pytest のファイルを絶対パスで足す
    （_reached。元で通っていたテストの緑と消えたテストの照らしは、この回でファイルごと走ったモジュールで見る）。地図が引けない・
    分からない物が近くに在る（run_all）時は合図なしの一式。届かない試験・元の結末の外の試験は受け付け（selected_problems）と
    線の最後のテストの段（一式）が確かめる
  拒めば同じ段のまま、理由は次の指示書（と reason_file）に載る。段ごとに RETRY_MAX 回目の拒否で諦める: test・fix は作業ツリーを
  単位の頭に戻して direct へ、refactor は緑の時の木に戻す。実行器が走らない・回数の上限に届いた時は、残りを全部 direct にして抜ける
  （輪は done の印で抜け、max_iterations に届いて落ちない。R50）
- fix-accept → frozen_problems: 輪で緑になった単位のテストのファイルを、輪の後の修正役が変えていないか（裁定 fix_test_scope の
  範囲の中の変更は、輪が済んだ時の木（frozen_tree）との差分の塊の旧い側の行で見て通す）
- fix-accept → selected_problems: 版からの変更に当たる試験（impact.select_tests。分からない物が近くに在れば全部）を同じ実行器で
  走らせ（選んだ .py のうち変えた・足したファイルだけを一式を回す時も絶対パスで後ろに足し、一式でない時は -k で絞る。届いただけの
  段の外の試験は手元で走らせない。ADR 0071 の 3 の 1）、元で赤でなかった試験の赤をテストのファイルごとの行で返す（行はそのパスを
  名指す。ファイルの分からない赤は 1 行にまとめてパスを名指さない）。走らせなかった試験は『手元で回さなかった』として
  知らせと状態（ci_left。受け付けが盤面の trace に載せ、最後の関所が並べる）に名前で残す。元の結末に無い試験の赤は、版を
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
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True

import adapter  # noqa: E402  （.shared/core。包みが会話を切る単位の鍵の置き場 session_key_path）
import board  # noqa: E402
import conflict  # noqa: E402  （.shared/core。食い違いの申し出の確かめ・直す義務から外れた単位）
import entry  # noqa: E402  （.shared/core。盤面の入口）
import fixrules  # noqa: E402  （同じブロックの lib。指示書の組み立て）
import fixshape  # noqa: E402  （.shared/core。盤面の修正の形）
import impact  # noqa: E402  （.shared/core。変更に当たる試験の選び）
import planbrief  # noqa: E402  （同じブロックの lib。承認済みの修正案の項目ごとの brief の凍結）
import planmarks  # noqa: E402  （.shared/core。修正案の項目の works の欄。単位の約束）
import seat  # noqa: E402  （.shared/core。借りたスキルの座）
import tree_run  # noqa: E402
import writes  # noqa: E402  （.shared/core。書き込みの出どころの突き合わせ）
import leftovers  # noqa: E402
from leftovers import Unreadable, git, git_names  # noqa: E402

RULES_GRAPH = "review-loop-tdd.json"
PHASES = ("route", "test", "fix", "refactor")
MAX_ITERATIONS = 40   # YAML の tdd-loop の max_iterations と同じ値（試験が縛る）。この周に届いたら残りを direct にして抜ける
MIN_WHY = 10
STATE, PROMPT, SUMMARY = "state.json", "next.md", "summary.md"
UNIT_NODE = "tdd"   # 輪の役の印の名（包みの adapter.KEYED_NODES の 1 つ。単位の切れ目で会話を切る）
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
# 平の run（修正の形 current。fixshape.plain）: 比べの基準なので 219 の前の振る舞い（約束を読まない・整えはいつも・test_cmd の関門を切る）
PLAIN_NOTE = "修正の形 current——test_cmd の関門は回さない（比べの基準）"
# 修正の形 g1（seat.G1_SHAPE）: 輪を回さない（start は元の結末を取って状態を書いた後、輪の出口を go: false にする）
G1_NO_LOOP = "修正の形 g1——TDD の輪は回さない（修正役が下請けを回し、赤緑と凍結は修正の受け付けの束が事後に確かめる）"
# test_cmd の関門を輪の頭で決めずに切る形と、状態の test_cmd_note に残す理由（g1 は輪が無いので関門を使わない。元の結末だけを取る）
GATE_OFF_BY_SHAPE = {fixshape.PLAIN: PLAIN_NOTE, seat.G1_SHAPE: G1_NO_LOOP}


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


def plan_contract(board_dir: pathlib.Path, keys: list[str], plain: bool | None = None) -> dict[str, dict]:
    """単位 → 承認済みの修正案の約束（planmarks.unit_contract。約束の無い単位は載せない）。盤面の無い置き場（state.json が無い）・
    欄の控えが無い run は {}。盤面が在るのに開けない・欄の控えが凍結の印と食い違う（conflict.frozen_fields が盤面を止めて
    BoardGap）なら、理由の文のまま Broken（約束を黙って空にしない）。平の run は欄を読まずに {}（plain は start が読んだ形。
    None なら盤面から読む——_shape）"""
    board_dir = pathlib.Path(board_dir)
    if not (board_dir / "state.json").exists() or (_shape(board_dir) == fixshape.PLAIN if plain is None else plain):
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


def _shape(board_dir: pathlib.Path) -> str:
    """盤面の修正の形（fixshape.shape_at）。形の控えが壊れていれば理由の Broken（traceback にしない）"""
    try:
        return fixshape.shape_at(board_dir)
    except ValueError as e:
        raise Broken(f"盤面 {board_dir} の修正の形が読めない: {e}") from None


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


def start(board_dir, repo, suite: str, open_units: str, test_cmd: str = "", unit_depths: str = "") -> dict:
    """節 tdd-start。{go, reason, suite, state_file, summary_file}。実行器が無ければ何も書かずに go: false（盤面を読まない）。
    test_cmd は run のテストのコマンド（線の入力）で、元の結末を取った後に関門を決める（_test_cmd_gate）。
    unit_depths は単位ごとの深さ（_light_units）。LIGHT の単位は関門が on でも緑の後の test_cmd を走らせない（状態の light）。
    ほかの単位と空は今どおり。
    修正の形 g1 も元の結末を取って状態を書く（受け付けの選んで回す試験 1c が元で緑だった試験の赤を拒むのに要る。強み 6）。
    違いは輪を回さないことだけで、出口は go: false・理由 G1_NO_LOOP・state_file は書いた状態・summary_file は空（輪の要約は無い）"""
    suite = (suite or "").strip()
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
    shape = _shape(board_dir)   # 形は輪の頭で 1 回だけ読む（平の run は状態の plain に置き、段は状態から引く。g1 は出口だけ違う）
    plain = shape == fixshape.PLAIN
    contract = plan_contract(board_dir, keys, plain)   # 輪の頭で 1 回だけ（欄の控えの食い違いは conflict の 1 か所で止める）
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
    gate, note, made = ((GATE_OFF, GATE_OFF_BY_SHAPE[shape], []) if shape in GATE_OFF_BY_SHAPE
                        else _test_cmd_gate(exe, test_cmd, repo, work / "test-cmd-0.log"))
    st = {"suite": suite, "exe": str(exe), "work": str(work), "open_units": keys, "excused": excused,
          "baseline": {_key(c): c["outcome"] for c in cases}, "baseline_exit": code,
          "handoff": snapshot(repo), "suite_made": made, "phase": "route", "tries": 0, "reason": "", "iterations": 0,
          "runs": 1, "order": [], "units": {}, "queue": [], "cur": 0, "unit_head": "", "green_tree": "",
          "done": False, "note": "", "frozen": {}, "parked": [], "parked_why": {}, "contract": contract, "plain": plain,
          "test_cmd": test_cmd, "test_cmd_gate": gate, "test_cmd_note": note, "light": light, "calls": []}
    state_file = work / STATE
    _save(state_file, st)
    if shape == seat.G1_SHAPE:
        return {**off, "reason": G1_NO_LOOP, "state_file": str(state_file)}
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
    "test": "今の単位の欠陥を再現する、今は落ちるテストだけを書け（実装は直すな。テストのファイルの外を触るな）。brief に受け入れの"
            "テスト（tests）が在る単位は、その id の名前でテストを書いて名指しに入れ、brief の red_kind の形で落とせ（assertion＝断言の"
            "失敗・exception＝期待した例外が出ない。宣言した名前（adds）の失敗は赤・宣言の外は赤に数えない）。案どおりに書いて赤にならない・赤の形が違うなら、"
            "テストを曲げず phase conflict で申し出よ。brief に受け入れのテストが無い単位は、テストを今の版に在る名前だけで再現するか、"
            "import をテストの中に入れよ。機械が一式を走らせ、名指しのテストが failure で落ち、元で通っていた"
            "テストが通ることを確かめる（error・もう通る・飛ばされた、は拒む）。",
    "fix": "今の単位だけを直せ。テストのファイルは変えるな（凍っている。テストの誤りに気づいたら直さずに what に書け）。機械が一式を"
           "走らせ、名指しのテストと元で通っていたテストが通ることを確かめる。緑の後に整えたい所（重複・名前・不要になったコード）が"
           "在る時だけ refactor の declared を true にし、why に理由を 10 字以上で書け。申告が無ければ整えの段は来ない（brief の "
           "refactor.declared が true の単位は申告なしでも来る）。",
    "refactor": "この段は、fix の段で申告した単位か、brief で申告した単位だけに来る。申告した所を緑のまま整えよ（テストのファイルは"
                "変えない）。整える物が無くなっていれば何も変えずに返せ。変えたなら機械がもう 1 回緑を確かめる。",
}
# 平の run の fix・refactor の段（219 の前の文と、決まりの申告の行を読まない 1 文。形の名は役に渡さない）
PLAIN_DO = {
    "fix": "今の単位だけを直せ。テストのファイルは変えるな（凍っている。テストの誤りに気づいたら直さずに what に書け）。機械が一式を"
           "走らせ、名指しのテストと元で通っていたテストが通ることを確かめる。この輪では緑の後に整えの段がいつも来る（refactor の"
           "欄は書かなくてよい。決まりの「整えは fix で申告した時だけ」「申告が無ければ整えの段は来ない」は、この輪では読まない）。",
    "refactor": "緑のまま、今の単位の差分を整えよ（重複・名前・不要になったコード。テストのファイルは変えない）。整える物が無ければ"
                "何も変えずに返せ。変えたなら機械がもう 1 回緑を確かめる。この輪ではこの段がどの単位にも来る（決まりの「申告した"
                "単位だけに来る」は、この輪では読まない）。",
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
# 機械が状態から書いて渡す（prep の今の単位の節の後）
HANDOFF_HEAD = "## 前の単位の引き継ぎ（機械が状態から書いた物）"


def handoff_lines(st) -> list:
    """今の単位より前に済んだ単位の 1 行ずつ（単位の key・直したファイル・緑にしたテスト・整え・direct に回した理由）。無ければ空"""
    rows = []
    for k in st["queue"][:st["cur"]]:
        u = st["units"].get(k)
        if not u:
            continue
        if u.get("gave_up"):
            rows.append(f"- {k}: 諦めて direct に回した（木は単位の頭に戻した。修正役が直す）: {u.get('why', '')[:200]}")
            continue
        if u.get("route") == "parked":
            rows.append(f"- {k}: 食い違いの申し出で止めた（木は単位の頭に戻した）")
            continue
        bits = [f"直したファイル {', '.join(u.get('files') or []) or 'なし'}",
                f"緑にしたテスト {', '.join(u.get('tests') or []) or 'なし'}"]
        if u.get("refactor"):
            bits.append(f"整え {u['refactor']}")
        rows.append(f"- {k}: " + "・".join(bits))
    if not rows:
        return []
    return [HANDOFF_HEAD, "", "前の単位の直しは作業ツリーに在る（緑の木）。戻したり作り直したりするな。", ""] + rows + [""]


def prep(state_file, values: dict | None = None, repo=None) -> dict:
    """節 tdd-prep。今の段の指示書を組み（fixrules.tdd_render: 修正の決まりの正本・TDD の決まり・今の段の約束・run の値）、状態の
    置き場の next.md（full の写し）と隣の next.full.md・next.delta.md・next.variants.json に書き、{prompt_file} を返す。
    values は fixrules.TDD_VALUES の run の値（義務の単位は状態の物を使う。欠けは空）。repo は差分から変更の種類を選ぶ根（None は見ない）。
    題の次に brief の節（planbrief.head_text）: 振り分けの段は直す義務の単位の全部、ほかの段は今の単位 1 つの brief。行の
    「単位」はその段で直す単位だけで、項目のほかの単位には「今は直すな」と添える。
    盤面の修正の形（fixshape.shape_at。盤面の無い置き場は記録の無い盤面と同じ af）が座を載せる形なら、借りたスキルの座
    （seat.section）を載せる。形の控え・写しが壊れていれば Broken。
    書いた後に、包みが単位の切れ目で会話を切る鍵（_write_unit_key）を書く。単位が替わった周の役は新しい会話で起き（依頼 243 の 2）、
    前の単位の物は引き継ぎの節（handoff_lines）だけで渡る"""
    st = _load(state_file)
    if st["done"]:
        raise Broken("TDD の輪は済んでいる（tdd-prep を呼ぶ番でない）")
    path = pathlib.Path(st["work"]) / PROMPT
    briefs = _briefs(path.parent.parent)   # 状態の置き場は盤面の tdd-<k>
    phase = st["phase"]
    title = f"# TDD の輪の指示書（{st['iterations'] + 1} 回目・段 {phase}）"
    lines = ["## この段ですること", "", PLAIN_DO.get(phase, DO[phase]) if st.get("plain") else DO[phase], ""]
    if phase in ("fix", "refactor") and st.get("test_cmd_gate") == GATE_ON and _cur(st)["unit_key"] not in st.get("light", []):
        lines += [f"緑の後に機械が run の test_cmd（`{st['test_cmd']}`）も走らせる。これも緑にせよ。", ""]
    if phase == "route":
        lines += ["## 直す義務の単位", ""] + [f"- {k}" for k in _owed(st)] + [""]
        brief = planbrief.head_text(planbrief.for_units(briefs, _owed(st)), _owed(st))
    else:
        u = st["units"][st["queue"][st["cur"]]]
        brief = planbrief.head_text(planbrief.for_units(briefs, [u["unit_key"]]), [u["unit_key"]])
        lines += ["## 今の単位", "", f"- {u['unit_key']}", ""]
        if u["tests"]:
            lines += [f"- 名指しのテスト: {', '.join(u['tests'])}", f"- テストのファイル（凍っている）: {', '.join(u['test_files'])}", ""]
        lines += handoff_lines(st)
        left = st["queue"][st["cur"] + 1:]
        if left:
            lines += ["この後の tdd の単位（今は手を付けるな）: " + " / ".join(left), ""]
    lines += ["## テストの回し方", "",
              f"リポジトリの根で `{st['exe']} <JUnit XML の書き先>`（書き先は /tmp の下など作業ツリーの外に）。"
              "機械は名指しを実行器の後ろに絶対パスの node id で足して回す（実行器の既定の一覧の外に書いたテストも載る）。"
              "自分で回す時も同じ形で足せる。", "",
              "## 返す JSON", "", RETURN[phase], "", RETURN_CONFLICT]
    vals = {**{k: "" for k in fixrules.TDD_VALUES}, **(values or {}),
            "open_units": json.dumps(_owed(st), ensure_ascii=False)}
    n = st["iterations"] + 1
    lang = fixrules.lang_at(path.parent.parent)   # 状態の置き場は盤面の tdd-<k>
    try:
        seat_text = seat.section("tdd", fixshape.shape_at(path.parent.parent))
    except ValueError as e:
        raise Broken(f"TDD の輪の座を組めない: {e}") from None

    def build(kinds, prior, rules_file):
        try:
            return fixrules.tdd_render(vals, phase, "\n".join(lines), title=title, reason=st["reason"], kinds=kinds,
                                       prior=prior, iteration=n, brief=brief, seat=seat_text, rules_file=rules_file, lang=lang)
        except fixrules.Unfilled as e:
            raise Broken(f"TDD の輪の指示書を組めない: {e}")
    fixrules.write_variants(path, repo, vals, build, n)
    _write_unit_key(path.parent.parent, f"{path.parent.name}:{'route' if phase == 'route' else st['queue'][st['cur']]}")
    return {"prompt_file": str(path)}


def _write_unit_key(board_dir: pathlib.Path, key: str) -> None:
    """包みが単位の切れ目で会話を切る鍵（UNIT_NODE の adapter.session_key_path）を書く（依頼 243 の 2）。鍵は輪の置き場の名と
    今の単位（振り分けの段は route）。書けなければ古い鍵を消す（包みは鍵が読めない時に今どおり会話を継ぐ。会話を切るのは節約で
    守りでないので、支度を止めない）"""
    path = pathlib.Path(adapter.session_key_path(str(board_dir), UNIT_NODE))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(" ".join(key.split()) + "\n", encoding="utf-8")
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


def _reached(st, repo) -> tuple[list, bool]:
    """緑の回に足す試験 ——（根からの相対の pytest の試験のファイル, 一式を回すか）。単位の頭からの変更（走らせて出来たファイルを
    除く）を起点に地図を引き（impact.map の seeds。置き場は work/impact）、届いた試験（impact.select_tests）のうち作業ツリーに在り、
    元の結末に載ったモジュール（元の一式が走らせた物。元で赤だった試験が届いただけで拒まれない）のファイル。地図が引けない・
    run_all なら ([], True)（合図なしの一式）"""
    seeds = sorted(set(touched(repo, st["unit_head"], snapshot(repo))) - set(st["suite_made"]))
    try:
        sel = impact.select_tests(impact.map(repo, seeds=seeds, cache_dir=pathlib.Path(st["work"]) / "impact"))
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


def _next_unit(st, repo) -> None:
    """次の単位の頭を固める。機械が戻した木（諦め・申し出・direct_why）もここを通るので、前の段の印（handoff）もここで進める"""
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


TEST_FILE = re.compile(r"^(test_.*|.*_test|conftest)\.py$")   # テストのファイルの名（実装の .py の test* 関数を凍らせない）


def _moved_test_files(st, repo, exclude=()) -> list[str]:
    """単位の頭から変わったテストのファイル（TEST_FILE の名。走らせて出来たファイルと exclude を除く）"""
    moved = set(touched(repo, st["unit_head"], snapshot(repo))) - set(st["suite_made"]) - set(exclude)
    return sorted(f for f in moved if TEST_FILE.match(posixpath.basename(f)))


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
    return [f"既存のテスト {edits[:10]} の本体を書き換えた——直し・整えの段ではテストを変えない"
            "（テストの誤りは what に書け。変えるしかないなら phase conflict で申し出よ）"] if edits else []


def _vanish_scope(files) -> set | None:
    """消えたテストを照らすモジュール（impact._mod の名）。conftest.py に触れていれば None（一式の全部）。純粋"""
    if any(posixpath.basename(f) == "conftest.py" for f in files):
        return None
    return {impact._mod(f) for f in files if TEST_FILE.match(posixpath.basename(f))}


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
                     _vanish_scope(_moved_test_files(st, repo)), skip, st["last_run"].get("whole") or ())
    return [f"単位 '{u['unit_key']}' の段で、単位の頭で通っていたテスト {k} が {o}（飛ばされた・一式の結末から消えた）——"
            "名指しの外の既存のテストを外すな（外すなら phase conflict で申し出よ）" for k, o in gone[:20]]


def _declared_hit(case: dict, declared) -> bool:
    """名前・import の失敗の message が引く『無い名前』（'x' の引用の末尾の . の後）が、案が足すと宣言した名前（'(' より前・
    最後の . の後）に完全一致するか。名前が引けない・declared が空なら False"""
    m = _MISSING.search(case.get("fail_message") or "")
    if not m:
        return False
    names = {str(d).split("(", 1)[0].strip().rsplit(".", 1)[-1] for d in declared or ()}
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
    次の単位へ（緑の木が次の単位の頭）。平の run（状態の plain）は申告に依らず refactor の段へ（refactor_why は申告のまま）"""
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
    if why or st.get("plain"):
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


def step(state_file, reply, repo, try_query=None) -> dict:
    """節 tdd-step。{ok（この返答を受けた）, done（輪を抜ける）, reason, phase（次の段）, conflict（止めた申し出の 1 件か None。
    節が盤面の控えに積む）, writes（書き込みの出どころの突き合わせの結果。節が盤面の trace に積む）}。
    申し出でない返答は、前の段の後から変わったファイルを書き込みの記録と欄 bash_writes に突き合わせてから段を確かめる。
    前の段の印（handoff）は突き合わせを通った時と、機械が木を単位の頭に戻して次の単位へ移った時（申し出・諦め）だけ進める（拒まれた
    返答の出し直しや、振り分けの段の申し出で、記録の無い書き込みを流さない）"""
    st = _load(state_file)
    if st["done"]:
        raise Broken("TDD の輪は済んでいる（tdd-step を呼ぶ番でない）")
    phase = st["phase"]
    t0, runs0 = time.monotonic(), st["runs"]   # 段ごとの呼び出しの記録（calls）の元。秒は書くだけで止める条件に使わない
    call = {"n": st["iterations"] + 1,
            "phase": "conflict" if isinstance(reply, dict) and reply.get("phase") == "conflict" else phase,
            "unit_key": "" if phase == "route" else st["queue"][st["cur"]]}
    item = None
    got = None
    if isinstance(reply, dict) and reply.get("phase") != "conflict":
        moved = sorted(set(touched(repo, st["handoff"], snapshot(repo))) - set(st["suite_made"]))
        got = writes.check(reply, repo, moved, writes.sink(repo))
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
    return {"ok": not probs, "done": st["done"], "reason": "\n".join(probs), "phase": "done" if st["done"] else st["phase"],
            "conflict": item, "writes": got}


def _finish(st, repo) -> None:
    """輪の後の修正役へ渡す summary.md と、凍ったテストのファイルの控え（frozen）"""
    passed = [st["units"][k] for k in st["order"] if st["units"][k]["route"] == "tdd"]
    st["frozen"] = hashes(repo, sorted({f for u in passed for f in u["test_files"]}))
    st["frozen_tree"] = snapshot(repo)
    lines = ["# TDD の輪の結果（機械が書いた）", ""]
    if st["note"]:
        lines += [f"輪を途中で抜けた: {st['note']}", ""]
    lines += ["## 輪で直した単位（直さず、changes に 1 行を書け。テストのファイルは変えるな——受け付けが拒む。"
              "食い違いの裁定 fix_test_scope が範囲に並べた所だけは例外。修正案の rewrite_tests の名指しは輪で書き換えて凍結した）", ""]
    for u in passed:
        lines += [f"- {u['unit_key']}", f"  - 名指しのテスト（機械が赤→緑を確かめた）: {', '.join(u['tests'])}",
                  f"  - テストのファイル: {', '.join(u['test_files'])}", f"  - 直したファイル: {', '.join(u['files'])}",
                  f"  - 直し: {u['what']}",
                  f"  - 整え: {u['refactor']}" + (f"（{u['refactor_why']}）" if u.get("refactor_why") else "")]
    parked = st.get("parked", [])
    if parked:
        lines += ["", "## 食い違いで止めた単位（直すな。輪の後に裁定役が裁き、裁定が理由のファイルで届く）", ""]
        lines += [f"- {k}: {st.get('parked_why', {}).get(k, '')}" for k in parked]
    if st.get("excused"):
        lines += ["", "## 直す義務から外れた単位（直すな。not_done に理由を書け）", ""]
        lines += [f"- {k}: {why}" for k, why in st["excused"].items()]
    lines += ["", "## direct の単位（ここで直せ）", ""]
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
    テストの関数）"""
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
            m = conflict.CITE.match(lim.strip())
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
        if not spans:
            probs.append(f)
        elif None not in spans:
            bad = _hunks_outside(repo, base, f, spans)
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


def _hunks_outside(repo, tree, path, spans) -> list:
    """輪が済んだ時の木の path と今のファイルの差分の塊のうち、旧い側の行が spans のどれにも収まらない物（`a-b` の文）。
    span は (始め, 終わり, 1 行の指しか)。1 行の指しの .py は _function_span で関数の幅に広げる。
    木が無い・木に path が無い時はファイル全体を 1 つの外の塊にする"""
    new = (pathlib.Path(repo) / path).read_text(encoding="utf-8", errors="replace").splitlines() \
        if (pathlib.Path(repo) / path).is_file() else []
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
    """(赤の文の一覧, 知らせ)。実行器の後ろに足すのは、選んだ試験のうちこの run で変えた・足したファイルだけ（ADR 0071 の
    3 の 1。届いただけの段の外の試験は手元で走らせない）。実行器の既定の一式の中は -k で選んだ全部のモジュールに絞る。
    実行器の無い run（状態が無い）・当たる試験が無い・実行器が走らない・選んだ試験が 1 件も走らなかった時は赤にせず知らせだけ。
    元の結末に無い試験の赤は、版の写しで同じ試験を回して、版でも赤なら外す（版の写しの結末は _base_reds が盤面の根に控え、
    受け付けの回をまたいで使い回す）"""
    if not state_file:
        return [], NO_SUITE
    st = _load(state_file)
    work = pathlib.Path(st["work"])
    m = impact.map(repo, rev=rev, diff=True, cache_dir=work / "impact")
    sel = impact.select_tests(m)
    if not sel["run_all"] and not sel["modules"]:
        return [], NO_SELECTED
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
    """赤の case をテストのファイルごとに分けた {「（ファイル <根からのパス>）」: [id]}（現れた順）。ファイルは case の模块
    （impact._junit_module）が impact._mod に等しいテストのファイル（impact.tree_files と impact.is_test）で、同じ名の模块が
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
    return {"ran": True, "suite": st["suite"], "reason": st["note"], "units": rows,
            "test_cmd": {"gate": st.get("test_cmd_gate", GATE_OFF), "note": st.get("test_cmd_note", "")},
            "calls": st.get("calls", [])}


# 事後の関門の束（同じブロックの fixgates。計画 220 Task 4）が輪と同じ決まりで読む口の公開の別名（輪の中の名は変えない。
# 名指しの外の既存のテストの書き換え・赤の種類の照らし・名指しの node id・関数の幅・範囲の外の差分の塊。preflight F11・F13）
unnamed_edits = _unnamed_edits
kind_problems = _kind_problems
abs_ids = _abs_ids
function_span = _function_span
hunks_outside = _hunks_outside
