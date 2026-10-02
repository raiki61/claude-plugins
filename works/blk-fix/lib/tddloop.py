"""修正のブロックの単位ごとの TDD の輪（MVP。設計 2 節 3・案 (i)。graph は変えず、ブロックの中で回す）。

節と関数:
- tdd-start → start: 入力 tdd_suite（JUnit XML の書き先を第 1 引数に受け、リポジトリの根で走る実行ファイル。本線と同じ約束）が
  空なら何もせず go: false（全部の単位を今どおり直す）。在れば一式を 1 回走らせて元の結末を取り、盤面の tdd-<k>/ に状態を置く。
  承認済みの修正案の単位ごとの約束（plan_contract → planmarks.unit_contract。道・受け入れのテストと赤の種類）もここで 1 回だけ
  組んで状態の contract に置く（盤面の無い置き場・欄の控えの無い run は空で、輪は約束の無い今の動きのまま）
- tdd-loop の中: tdd-prep → prep（今の段の指示書を fixrules で組んで書く。full と delta の 2 つの形。頭に brief の節: 振り分けの段は
  直す義務の単位の全部、ほかの段は今の単位の brief。盤面の無い置き場・修正案の欄の控えの無い run は無し）→ 役 tdd（修正役。
  同じ会話で振り分け・テスト・直し・整えを返す）→
  tdd-step → step（返答を機械が確かめて段を進める）。段は route → 単位ごとに test → fix → refactor → 次の単位
  - route: 直す義務の単位（_owed: 開いた単位から、答え待ち・ask_human で外れた単位と食い違いで止めた単位を除く）を全部 1 度だけ
    tdd か direct（理由 10 字以上）に振る。約束で tdd の単位は direct に振れない（出口は phase conflict の申し出）
  - test: 申告したテストのファイルの外に触れていない・写しの red_problems（名指しは failure で落ち、元で通っていた物は緑）。
    約束の在る単位は、受け入れのテストの id を全部名指し（走らせる前に見る）、各テストの赤の種類（red_kind。JUnit の failure の
    type・message から機械が分ける）が名前・import の失敗でなく、案が exception なら断言の失敗でない（_kind_problems。ほかの
    例外の型・unknown は記録だけ）。direct_why でも direct に渡せない。
    名指し全部の赤の種類を単位の red_kinds に残す
  - fix: その単位のテストのファイルが赤の時から変わっていない・写しの green_problems
  - refactor: 緑の時から何も変えていなければ none。変えたなら fix と同じ確かめをもう 1 回
  - test・fix・refactor とも、名指しを絶対パスの node id で実行器の後ろに足して走らせる（段の外に書いたテストも一式の結末に載る）
  拒めば同じ段のまま、理由は次の指示書（と reason_file）に載る。段ごとに RETRY_MAX 回目の拒否で諦める: test・fix は作業ツリーを
  単位の頭に戻して direct へ、refactor は緑の時の木に戻す。実行器が走らない・回数の上限に届いた時は、残りを全部 direct にして抜ける
  （輪は done の印で抜け、max_iterations に届いて落ちない。R50）
- fix-accept → frozen_problems: 輪で緑になった単位のテストのファイルを、輪の後の修正役が変えていないか（裁定 fix_test_scope の
  範囲の中の変更は、輪が済んだ時の木（frozen_tree）との差分の塊の旧い側の行で見て通す）
- fix-accept → selected_problems: 版からの変更に当たる試験（impact.select_tests。分からない物が近くに在れば全部）を同じ実行器で
  走らせ（選んだ .py のうち変えた・足したファイルだけを一式を回す時も絶対パスで後ろに足し、一式でない時は -k で絞る。届いただけの
  段の外の試験は手元で走らせない。ADR 0071 の 3 の 1）、元で赤でなかった試験の赤を返す。走らせなかった試験は『手元で回さなかった』として
  知らせと状態（ci_left。受け付けが盤面の trace に載せ、最後の関所が並べる）に名前で残す。元の結末に無い試験の赤は、版を
  一時の置き場に写して同じ試験を回し、版でも赤なら外す（作業ツリーは動かさない）。1 件も走らなければ「新しい赤なし」にせず
  知らせる（一式の緑は線の最後のテストの段が確かめる。役は一式を回さない）
- collect → exit_fields: 出口の欄 tdd（単位ごとの道・赤・緑・整え・direct の理由）
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
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True

import board  # noqa: E402
import conflict  # noqa: E402  （.shared/core。食い違いの申し出の確かめ・直す義務から外れた単位）
import entry  # noqa: E402  （.shared/core。盤面の入口）
import fixrules  # noqa: E402  （同じブロックの lib。指示書の組み立て）
import impact  # noqa: E402  （.shared/core。変更に当たる試験の選び）
import planbrief  # noqa: E402  （同じブロックの lib。承認済みの修正案の項目ごとの brief の凍結）
import planmarks  # noqa: E402  （.shared/core。修正案の項目の works の欄。単位の約束）
import tree_run  # noqa: E402
import writes  # noqa: E402  （.shared/core。書き込みの出どころの突き合わせ）
from leftovers import Unreadable, git, git_names  # noqa: E402

RULES_GRAPH = "review-loop-tdd.json"
PHASES = ("route", "test", "fix", "refactor")
MAX_ITERATIONS = 40   # YAML の tdd-loop の max_iterations と同じ値（試験が縛る）。この周に届いたら残りを direct にして抜ける
MIN_WHY = 10
STATE, PROMPT, SUMMARY = "state.json", "next.md", "summary.md"
NO_SUITE = "テストの実行器（入力 tdd_suite）が無い run——全部の単位を今どおり直す"
SUITE_MADE_NOTE = "一式を走らせて出来たファイル"


class Broken(Exception):
    """回す側の誤り（状態が読めない・輪が済んだ後に呼んだ・入力の形が違う）。節は 2 で落ちる"""


class _RunnerDown(Exception):
    """実行器が走らない・JUnit が読めない（テストや直しの誤りではない。やり直しの回数を使わずに輪を抜ける）"""


_RULES = []


def rules():
    """写しの TDD 版の rules（red_problems・green_problems・RETRY_MAX・parse_junit）。1 回だけ読む"""
    if not _RULES:
        _RULES.append(board.rules_module(board.graph_path(RULES_GRAPH)))
    return _RULES[0]


def retry_max() -> int:
    return rules().RETRY_MAX


# ---------------------------------------------------------------- 版を木に固める・戻す
def snapshot(repo) -> str:
    """作業ツリーの今の姿（未追跡の新しいファイルも。.gitignore に当たる物は除く）の木の sha。本物の index は触らない"""
    with tempfile.TemporaryDirectory(prefix="works-tdd-index-") as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(pathlib.Path(td) / "index")}
        if _has_head(repo):
            git(repo, "read-tree", "HEAD", env=env)
        git(repo, "add", "-A", "--", ":/", env=env)
        return git(repo, "write-tree", env=env).strip()


def _has_head(repo) -> bool:
    try:
        git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        return True
    except Unreadable:
        return False


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
def run_suite(exe: str, repo, work: pathlib.Path, n, args=()):
    """実行器を 1 回走らせる ——（結末の一覧, 終了コード, 問題）。結末が取れなければ一覧は None。
    .py はこの Python で走らせる（写しの rules の run_suite と同じ）。出力は work/suite-<n>.log に丸ごと。
    args は JUnit の書き先の後ろに足す（段の外の試験のファイル・node id を絶対パスで・受け付けの -k。works/dev/tdd-suite.sh は
    pytest にそのまま渡す）。同じ鍵の行は 1 つにまとめる（段のファイルと足した node id が重なっても 1 件）。
    輪の元の結末・各段・受け付け・版の写しの全部がここを通るので、nice -n 19 と機械の試験の枠（tree_run.slotted_run）を
    ここで付ける（ADR 0071 の 3 の 1）。枠を待った秒はログの末尾に書く（走った時間と分けて見る）"""
    argv = ["nice", "-n", "19"] + ([sys.executable] if exe.endswith(".py") else []) + [exe]
    junit = work / f"junit-{n}.xml"
    log = work / f"suite-{n}.log"
    env = {**tree_run.outside_env(os.environ), "PYTHONDONTWRITEBYTECODE": "1"}
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
            "refactor": "", "gave_up": "", "problems": [], "files": [], "what": "", "red_kinds": {}}


def start(board_dir, repo, suite: str, open_units: str) -> dict:
    """節 tdd-start。{go, reason, suite, state_file, summary_file}。実行器が無ければ何も書かずに go: false"""
    suite = (suite or "").strip()
    off = {"go": False, "reason": NO_SUITE, "suite": suite, "state_file": "", "summary_file": ""}
    if not suite:
        return off
    keys = _open_units(open_units)
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
    st = {"suite": suite, "exe": str(exe), "work": str(work), "open_units": keys, "excused": excused,
          "baseline": {_key(c): c["outcome"] for c in cases}, "baseline_exit": code,
          "handoff": snapshot(repo), "suite_made": [], "phase": "route", "tries": 0, "reason": "", "iterations": 0,
          "runs": 1, "order": [], "units": {}, "queue": [], "cur": 0, "unit_head": "", "green_tree": "",
          "done": False, "note": "", "frozen": {}, "parked": [], "parked_why": {}, "contract": contract}
    state_file = work / STATE
    _save(state_file, st)
    return {"go": True, "reason": "", "suite": suite, "state_file": str(state_file), "summary_file": str(work / SUMMARY)}


# ---------------------------------------------------------------- 指示書（節 tdd-prep）
RETURN = {
    "route": '{"phase": "route", "units": [{"unit_key": "<単位の key>", "route": "tdd" か "direct", "why": "<direct の理由。10 字以上>"}]}',
    "test": '{"phase": "test", "unit_key": "<今の単位>", "test_files": ["<書いたテストのファイル>"], '
            '"tests": ["<パス>::<クラス>::<テストの名前>"]}  （先にテストを書けないと分かったら {"phase": "test", '
            '"unit_key": "<今の単位>", "direct_why": "<理由。10 字以上>"}）',
    "fix": '{"phase": "fix", "unit_key": "<今の単位>", "files": ["<直したファイル>"], "what": "<何をどう直したか>"}',
    "refactor": '{"phase": "refactor", "unit_key": "<今の単位>", "what": "<何を整えたか。整える物が無ければそう書く>"}',
}
RETURN_CONFLICT = ('どの段でも、緑にするためにテスト・依頼・コードのどれかを曲げるしかないと分かった単位は '
                   '{"phase": "conflict", "unit_key": "<単位>", "between": ["<パス>:<行>", "<パス>:<行>"], '
                   '"why_both_cannot_hold": "<なぜ両方は成り立たないか>", "which_is_right": "request か test か code か unknown か query"}（query なら "correct_lines": ["<問いが当たる直した後の正しい行>"] も）'
                   '（振り分けの段なら義務の単位のどれか、ほかの段なら今の単位）')
DO = {
    "route": "直す義務の単位を全部、ちょうど 1 度ずつ振り分けよ。tdd＝直す前に落ち、直した後に通るテストをリポジトリのテスト一式に"
             "書ける単位。direct＝先にテストを書けない単位（文書・指示書・注記・設定だけの直しなど）で、理由を 10 字以上で書く。"
             "この段では作業ツリーを変えるな。",
    "test": "今の単位の欠陥を再現する、今は落ちるテストだけを書け（実装は直すな。テストのファイルの外を触るな）。brief に受け入れの"
            "テスト（tests）が在る単位は、その id の名前でテストを書いて名指しに入れ、brief の red_kind の形で落とせ（assertion＝断言の"
            "失敗・exception＝期待した例外が出ない。名前・import の失敗は赤に数えない）。案どおりに書いて赤にならない・赤の形が違うなら、"
            "テストを曲げず phase conflict で申し出よ。brief に受け入れのテストが無い単位は、テストを今の版に在る名前だけで再現するか、"
            "import をテストの中に入れよ。機械が一式を走らせ、名指しのテストが failure で落ち、元で通っていた"
            "テストが通ることを確かめる（error・もう通る・飛ばされた、は拒む）。",
    "fix": "今の単位だけを直せ。テストのファイルは変えるな（凍っている。テストの誤りに気づいたら直さずに what に書け）。機械が一式を"
           "走らせ、名指しのテストと元で通っていたテストが通ることを確かめる。",
    "refactor": "緑のまま、今の単位の差分を整えよ（重複・名前・不要になったコード。テストのファイルは変えない）。整える物が無ければ"
                "何も変えずに返せ。変えたなら機械がもう 1 回緑を確かめる。",
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


def prep(state_file, values: dict | None = None, repo=None) -> dict:
    """節 tdd-prep。今の段の指示書を組み（fixrules.tdd_render: 修正の決まりの正本・TDD の決まり・今の段の約束・run の値）、状態の
    置き場の next.md（full の写し）と隣の next.full.md・next.delta.md・next.variants.json に書き、{prompt_file} を返す。
    values は fixrules.TDD_VALUES の run の値（義務の単位は状態の物を使う。欠けは空）。repo は差分から変更の種類を選ぶ根（None は見ない）。
    題の次に brief の節（planbrief.head_text）: 振り分けの段は直す義務の単位の全部、ほかの段は今の単位 1 つの brief。行の
    「単位」はその段で直す単位だけで、項目のほかの単位には「今は直すな」と添える"""
    st = _load(state_file)
    if st["done"]:
        raise Broken("TDD の輪は済んでいる（tdd-prep を呼ぶ番でない）")
    path = pathlib.Path(st["work"]) / PROMPT
    briefs = _briefs(path.parent.parent)   # 状態の置き場は盤面の tdd-<k>
    phase = st["phase"]
    title = f"# TDD の輪の指示書（{st['iterations'] + 1} 回目・段 {phase}）"
    lines = ["## この段ですること", "", DO[phase], ""]
    if phase == "route":
        lines += ["## 直す義務の単位", ""] + [f"- {k}" for k in _owed(st)] + [""]
        brief = planbrief.head_text(planbrief.for_units(briefs, _owed(st)), _owed(st))
    else:
        u = st["units"][st["queue"][st["cur"]]]
        brief = planbrief.head_text(planbrief.for_units(briefs, [u["unit_key"]]), [u["unit_key"]])
        lines += ["## 今の単位", "", f"- {u['unit_key']}", ""]
        if u["tests"]:
            lines += [f"- 名指しのテスト: {', '.join(u['tests'])}", f"- テストのファイル（凍っている）: {', '.join(u['test_files'])}", ""]
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

    def build(kinds, prior, rules_file):
        try:
            return fixrules.tdd_render(vals, phase, "\n".join(lines), title=title, reason=st["reason"], kinds=kinds,
                                       prior=prior, iteration=n, brief=brief, rules_file=rules_file, lang=lang)
        except fixrules.Unfilled as e:
            raise Broken(f"TDD の輪の指示書を組めない: {e}")
    fixrules.write_variants(path, repo, vals, build, n)
    return {"prompt_file": str(path)}


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


def _run(st, repo, named=()):
    """一式を走らせ、走らせて出来たファイルを suite_made に積む（テストを書く段が触ったファイルの数えから外す）。
    名指しは絶対パスの node id で実行器の後ろに足し、段の外に書いたテストも同じ 1 回で集める（段の中の名指しとの重なりは
    run_suite が 1 件にまとめる。後ろの引数を解かない実行器なら段の外の名指しは居ないままで、赤・緑の確認が今どおり拒む）"""
    pre = snapshot(repo)
    cases, code, why = run_suite(st["exe"], repo, pathlib.Path(st["work"]), st["runs"], _abs_ids(repo, named))
    st["runs"] += 1
    st["suite_made"] = sorted(set(st["suite_made"]) | set(touched(repo, pre, snapshot(repo))))
    if cases is None:
        raise _RunnerDown("; ".join(why))
    return cases, code


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


def _plan_tdd(st, k, how="direct に振れない") -> str:
    """約束で tdd の単位を direct へ回す返答を拒む文（約束が無いか tdd でなければ空）"""
    c = (st.get("contract") or {}).get(k)
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
    return ((st.get("contract") or {}).get(k) or {}).get("tests") or []


def _kind_problems(want: list, cases: list) -> list:
    """約束の各テストの赤の種類（red_kind）を照らし、拒む物の文。拒むのは次の 2 つだけ（superpowers の TDD の『error でなく
    fail で落とす』）:
    - 名前・import の失敗（NAME_KINDS。機能が無い・綴りの誤り）。案が assertion でも exception でも
    - 案が exception（期待した例外が出ない）なのに断言の失敗で落ちた
    ほかの例外の型（今のコードが例外で落ちる種類のバグ）と、案が assertion で期待した例外が出ない赤は、記録だけで通す。
    分からない（unknown）は通す。案の red_kind が planmarks.RED_KINDS の外（None など）なら見ない"""
    out = []
    for t in want:
        want_kind = t.get("red_kind")
        if want_kind not in planmarks.RED_KINDS:
            continue
        c = rules().match_case(t["id"], cases)
        got = red_kind(c) if c else KIND_UNKNOWN
        if got in NAME_KINDS:
            out.append(f"{t['id']}: 赤の種類が案と違う（案 {want_kind}・実際 {got}）——名前・import の失敗は狙いの赤でない"
                       "（機能が無い・綴りの誤り）。テストの誤りなら直して出し直し、案の前提の誤りならテストを曲げず phase conflict で申し出よ")
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
    errs = [] if isinstance(tests, list) and tests and all(isinstance(t, str) and t.strip() for t in tests) \
        else ["tests は名指しのテスト（<パス>::<クラス>::<名前>）の空でない配列"]
    files, bad = _paths(reply.get("test_files"), "test_files")
    errs += bad
    if errs:
        return errs
    extra = sorted(set(touched(repo, st["unit_head"], snapshot(repo))) - set(files) - set(st["suite_made"]))
    if extra:
        return [f"申告したテストのファイルの外に触れた: {extra[:5]}——この段はテストだけを書く（実装は次の段）"]
    want = _plan_tests(st, u["unit_key"])
    named = {_norm_id(t) for t in tests}
    miss = [t["id"] for t in want if _norm_id(t["id"]) not in named]
    if miss:
        return [f"承認済みの修正案の受け入れのテストを名指していない: {miss}——brief の tests の id の名前でテストを書き、tests に入れよ。"
                "案の前提が誤りなら phase conflict で申し出よ"]
    cases, code = _run(st, repo, tests)
    probs = rules().red_problems(tests, cases, code, st["baseline"]) or _kind_problems(want, cases)
    if probs:
        return probs
    kinds = {t: red_kind(rules().match_case(t, cases) or {}) for t in tests}
    u.update(tests=tests, test_files=files, red="ok", test_hashes=hashes(repo, files), red_kinds=kinds)
    st.update(phase="fix", tries=0, reason="")
    return []


def _frozen_moved(u, repo) -> list:
    now = hashes(repo, u["test_files"])
    return [f for f in u["test_files"] if now[f] != u["test_hashes"][f]]


def _green(st, u, repo) -> list:
    moved = _frozen_moved(u, repo)
    if moved:
        return [f"テストのファイルを赤の時から書き換えた: {moved}——テストは凍っている（テストの誤りは what に書け）"]
    cases, code = _run(st, repo, u["tests"])
    return rules().green_problems(u["tests"], cases, code, st["baseline"], st["baseline_exit"])


def _fix(st, reply, repo) -> list:
    u = _cur(st)
    files = reply.get("files")
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files) or not isinstance(reply.get("what"), str) \
            or not reply["what"].strip():
        return ["files（直したファイルの配列）と what（何をどう直したか）が要る"]
    probs = _green(st, u, repo)
    if probs:
        return probs
    u.update(green="ok", files=files, what=reply["what"].strip())
    st.update(phase="refactor", tries=0, reason="", green_tree=snapshot(repo))
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
    u["refactor"] = "ok" if moved else "none"
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
                              try_query=try_query)
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
            _abort(st, repo, f"テストの実行器が走らない: {e}", "runner")
            probs = [st["note"]]
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
              "食い違いの裁定 fix_test_scope が範囲に並べた所だけは例外）", ""]
    for u in passed:
        lines += [f"- {u['unit_key']}", f"  - 名指しのテスト（機械が赤→緑を確かめた）: {', '.join(u['tests'])}",
                  f"  - テストのファイル: {', '.join(u['test_files'])}", f"  - 直したファイル: {', '.join(u['files'])}",
                  f"  - 直し: {u['what']}", f"  - 整え: {u['refactor']}"]
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
def frozen_problems(state_file, repo, allowed=()) -> list:
    """輪で緑になった単位のテストのファイルが、輪が済んだ時から変わっていれば、その文（状態が無ければ空）。
    allowed はテストの変更の許し（承認済みの修正案の rewrite_tests と裁定 fix_test_scope の範囲。conflict.test_permits を
    conflict.ruled_test_limits が引く）で、その中だけの変更は通す"""
    if not state_file:
        return []
    st = _load(state_file)
    now = hashes(repo, st["frozen"])
    moved = [f for f, h in st["frozen"].items() if now[f] != h]
    scope = {}
    for lim in allowed:
        got = conflict.parse_limit(lim)
        if got:
            m = conflict.CITE.match(lim.strip())
            # 1 行の指し（`<パス>:<行>`）だけが関数の幅に広がる。`<行>-<行>` は書いたとおり
            scope.setdefault(got[0], []).append(got[1] and (*got[1], bool(m) and not m["b"]))
    probs, outside = [], {}
    for f in moved:
        spans = scope.get(f)
        if not spans:
            probs.append(f)
        elif None not in spans:
            bad = _hunks_outside(repo, st.get("frozen_tree") or st.get("handoff"), f, spans)
            if bad:
                outside[f] = bad
    out = [f"TDD の輪で凍ったテストのファイルを書き換えた: {probs}（輪で直した単位のテストは変えない）"] if probs else []
    out += [f"TDD の輪で凍ったテストのファイル {f} を、テストの変更の許し（修正案の rewrite_tests の名指しまたは裁定 fix_test_scope）"
            f"の範囲の外で書き換えた: 旧い行 {', '.join(bad)}"
            "（範囲に並べた行だけ直してよい。.py の 1 行の指しはその行を含む関数の全体）" for f, bad in outside.items()]
    return out


def frozen_source(state_file, repo):
    """凍結の検査が行を読む輪の後の木（frozen_tree、無ければ handoff。_hunks_outside と同じ）から、パスの中身を読む口
    （conflict.ruled_test_limits の source。修正案の limit をその木でテストの id から引き直す）。状態・木・パスが読めなければ
    口は None を返す（許しを捨てる側）。状態は口を呼んだ時に読む"""
    def read(path):
        try:
            st = _load(state_file) if state_file else {}
            tree = st.get("frozen_tree") or st.get("handoff")
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
    元の結末に無い試験の赤は、版の写しで同じ試験を回して、版でも赤なら外す"""
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
    red = [_key(c) for c in cases if c["outcome"] in ("failure", "error")
           and st["baseline"].get(_key(c)) not in ("failure", "error")]
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
    return [f"受け付けが走らせた{what}で、元で赤でなかった試験が赤: {red[:20]}（{len(red)} 件。ログ {work / f'suite-{ACCEPT_RUN}.log'}"
            f"{tail}）——直した単位のどこかを直して出し直せ"], ""


def _left_to_ci(selected, run_files, cases) -> list:
    """選んだ試験のうち、手元で名指さず（run_files に無く）結末にもモジュールが 1 件も出なかった物（手元で回さなかった）。実行器の
    既定の段は対象ごとに違うので、段の一覧を写さず結末から決める。結末が無ければ名指さなかった物は全部"""
    ran = {impact._junit_module(c) for c in cases or []}
    return [t for t in selected if t not in run_files and impact._mod(t) not in ran]


def ci_left(state_file) -> list:
    """受け付けが手元で回さず 手元で回さなかった試験（状態が無い・まだ選んでいなければ空）。見せるだけの読み口なので、状態のファイルが
    無ければ空（受け付けの知らせの文にも同じ名が載る）"""
    return _load(state_file).get("ci_left", []) if state_file and pathlib.Path(state_file).is_file() else []


def _base_reds(st, repo, rev, files, kexpr) -> tuple:
    """(版 rev の姿で同じ試験を回して赤だった鍵の集合か None, 問題)。版の姿は一時の置き場に git archive で写して走らせ、
    作業ツリー・index・枝は動かさない。実行器が repo の中に在れば写しの中の同じ物を走らせる（自分の置き場から根を引く実行器が
    写しの根で走るように）"""
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
    return {_key(c) for c in cases if c["outcome"] in ("failure", "error")}, []


FIELDS = ("unit_key", "route", "why", "tests", "test_files", "red", "green", "refactor", "gave_up", "problems", "red_kinds")


def exit_fields(start_out: dict) -> dict:
    """出口の欄 tdd: {ran, suite, reason, units: [{unit_key, route, why, tests, test_files, red, green, refactor, gave_up, problems,
    red_kinds（名指しの id → 見た赤の種類）}]}"""
    if not isinstance(start_out, dict) or not start_out.get("go"):
        so = start_out if isinstance(start_out, dict) else {}
        return {"ran": False, "suite": so.get("suite", ""), "reason": so.get("reason", ""), "units": []}
    st = _load(start_out["state_file"])
    if not st["done"]:
        raise Broken("TDD の輪が済んでいない（done の印が無い）")
    rows = [{f: st["units"][k][f] for f in FIELDS} for k in st["order"]]
    rows += [{**{f: _unit(k, "parked")[f] for f in FIELDS}, "why": st.get("parked_why", {}).get(k, "")}
             for k in st.get("parked", []) if k not in st["order"]]   # 振り分けの段で止めた単位
    return {"ran": True, "suite": st["suite"], "reason": st["note"], "units": rows}
