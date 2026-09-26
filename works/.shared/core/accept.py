"""受け付けの口。役の返答を、写した graphloops の規則（rules/review-loop.py）と検証器（scripts/review-record.py）に通す。

Archon を知らない関数だけを出す。ブロックの script の節がこれを呼び、結果をそのまま出口にする。
- check_request: 依頼（findings の配列）を rules の add に通し、盤面の request.json に積む
- check_judge:   判定役（p2.diagnose）の返答。作業ツリー → 型 → rules の judge_output。通れば盤面に judgment.json
- check_fix:     修正役の返答。changes[].unit_key を修正案に読み替えて rules の fix_plan_covers_units
- check_delta:   審査役（p3.delta_review）の返答。触ったファイルは git から取り、rules の delta_review_output。通れば盤面に delta-review.json
- role_schema:   graph の節の schema を、$ref を開いて注記（note）を落とした JSON Schema にする（役の output_format へ）
- snapshot_tree: 作業ツリーの写し（差分を切る節が盤面の delta-snapshot.json に置き、check_delta が突き合わせる）
- touched_files: 修正が触ったファイル（差分を切る節と check_delta が同じ物を使う。バイトコードは除く）
- cut_delta:     修正の差分を盤面の fix.diff に切り、作業ツリーの写しを置く（blk-delta の節 cut）

check_* は全部 dict を返し、例外で拒まない。拒否は {"ok": False, "reason": str}。
git は全部 repo を cwd にして呼ぶ。HEAD をその場で読むのは base_rev が空のときだけ（空なら repo の HEAD を版にする）。
"""
import contextlib
import copy
import functools
import hashlib
import json
import os
import pathlib
import subprocess
import sys

# pack の中に __pycache__ を作らない。ここで立てて止まるのは下で import する engine・rules・検証器の分だけ。
# accept.py 自身の .pyc は、この行が動く前に import の時点で書かれるので、止めるのは呼び手（import する前に立てる。
# ブロックのスクリプトの前置きは script_io の docstring）
sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parent
_GL = CORE / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

import engine.util as _util  # noqa: E402
from engine.rules import load_rules, validator_module  # noqa: E402
from engine.schema import expand_refs, validate_schema  # noqa: E402
from engine.util import Reject  # noqa: E402

GRAPH_PATH = _GL / "graphs" / "review-loop.json"
VALIDATOR = CORE / "scripts" / "review-record.py"
REQUEST_FILE = "request.json"        # 依頼のバッチの一覧（rules の REQUEST_SCHEMA の形）
JUDGMENT_FILE = "judgment.json"      # 受け付けた判定の返答（judge_output が正規化した後の姿）
SNAPSHOT_FILE = "delta-snapshot.json"   # 差分を切った時の作業ツリー {"porcelain": str, "diff_sha256": str}
DIFF_FILE = "fix.diff"                   # 修正の差分（cut_delta が書き、審査役が読む）
DELTA_REVIEW_FILE = "delta-review.json"  # 受け付けた審査の返答（集める節が穴の数を数える）
JUDGE_SNAPSHOT_FILE = "judge-snapshot.json"   # 判定役を起こす前（依頼の受け付けの時）の作業ツリー。形は SNAPSHOT_FILE と同じ
GIT_TIMEOUT = 120

# 修正役の返答のうち、受け付けが読む欄だけの型（役の output_format は blk-fix が持つ。ここは読む欄が在るかだけを見る）
FIX_SCHEMA = {"type": "object", "required": ["changes"], "properties": {
    "changes": {"type": "array", "items": {"type": "object", "required": ["unit_key"], "properties": {
        "unit_key": {"type": "string", "minLength": 1}}}}}}
SNAPSHOT_SCHEMA = {"type": "object", "required": ["porcelain", "diff_sha256"], "properties": {
    "porcelain": {"type": "string"}, "diff_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}}


# ---------------------------------------------------------------- graph と rules
@functools.lru_cache(maxsize=None)
def _graph():
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def _rules():
    return load_rules(GRAPH_PATH, _graph())


def _strip_notes(x):
    """注記の語 note を落とす。properties / patternProperties の下の鍵は欄の名前なので、note という名前の欄は残す"""
    if isinstance(x, list):
        return [_strip_notes(v) for v in x]
    if not isinstance(x, dict):
        return x
    out = {}
    for k, v in x.items():
        if k == "note":
            continue
        if k in ("properties", "patternProperties") and isinstance(v, dict):
            out[k] = {name: _strip_notes(s) for name, s in v.items()}
        else:
            out[k] = _strip_notes(v)
    return out


@functools.lru_cache(maxsize=None)
def _role_schema_json(node):
    return json.dumps(_strip_notes(expand_refs(_graph())["nodes"][node]["schema"]), ensure_ascii=False)


def role_schema(node: str) -> dict:
    """graph の節（"p2.diagnose" か "p3.delta_review"）の schema。$ref を開き、注記を落とした写しを返す"""
    return json.loads(_role_schema_json(node))


# ---------------------------------------------------------------- 盤面の入れ物
class _Board:
    """rules が読む盤面の口だけを持つ入れ物（dir・round・state・record・loop_state・graph・rd・node_state・output_of_round）。
    1 本目は 1 周だけ回すので round は 1、判定役はまだ起きていない（node_state は pending）"""

    def __init__(self, board, review_rev, record=None, loop_state=None, outputs=None):
        self.dir = pathlib.Path(board)
        self.round = 1
        self.state = {"validator": str(VALIDATOR), "inputs": {"review_rev": review_rev}}
        self.record = record if record is not None else _rules().init_record(None, None)
        self.loop_state = loop_state or {}
        self._outputs = outputs or {}
        self.graph = _graph()
        self.rd = {"instances": {}}

    def node_state(self, nid):
        return "pending"

    def output_of_round(self, nid, rnd):
        return self._outputs.get(nid) if rnd == self.round else None


# ---------------------------------------------------------------- git と盤面のファイル
def _git(repo, *args, binary=False):
    """repo を cwd にして git を呼ぶ。失敗は Reject（受け付けは『分からない』を合格に倒さない）"""
    try:
        r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Reject(f"git {' '.join(args)} を呼べない（{type(e).__name__}: {e}）")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()[-300:]
        raise Reject(f"git {' '.join(args)} が失敗した（{err or f'exit {r.returncode}'}）")
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


@contextlib.contextmanager
def _in_repo(repo):
    """rules に差し込まれた git（engine/util.py の git）を repo に向ける。呼び終えたら戻す"""
    old = _util.GIT_CWD
    _util.GIT_CWD = str(repo)
    try:
        yield
    finally:
        _util.GIT_CWD = old


def _rev(repo, base_rev):
    """数える・差分を取る版。空なら repo の HEAD（Ruling R2）。版として引けなければ拒む"""
    name = base_rev or "HEAD"
    if name.startswith("-"):
        raise Reject(f"base_rev {base_rev!r} は版の名前でない")
    try:
        return _git(repo, "rev-parse", "--verify", "--quiet", f"{name}^{{commit}}").strip()
    except Reject:
        raise Reject(f"base_rev {base_rev!r} が repo {repo} の版として引けない")


def _read_board(board, name):
    p = pathlib.Path(board) / name
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Reject(f"盤面の {name} が読めない（{e}）")


def _write_board(board, name, obj):
    p = pathlib.Path(board) / name
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p


def _type_errors(value, schema, what):
    errs = validate_schema(value, schema)
    if errs:
        raise Reject(f"{what}の型が合わない: " + "; ".join(errs[:10]) + (f"（ほか {len(errs) - 10} 件）" if len(errs) > 10 else ""))


def _guard(fn, **on_reject):
    """rules の Reject を ok: False に写す。規則の中の想定外の例外（die の SystemExit を含む）も拒否として返す"""
    try:
        return fn()
    except KeyboardInterrupt:
        raise
    except Reject as e:
        return {"ok": False, "reason": str(e), **on_reject}
    except BaseException as e:
        return {"ok": False, "reason": f"受け付けの中で例外（{type(e).__name__}: {e}）", **on_reject}


def _entry_digest(p: pathlib.Path) -> bytes:
    """未追跡の 1 本の中身の sha256。symlink はリンク先の名前、ファイルは中身、フォルダ（入れ子の git リポジトリは
    git が `sub/` の 1 行で出す）は中の全部の名前と中身を名前の順に続けた物（.git の下は除く）。それ以外（FIFO など）は種類だけ"""
    if p.is_symlink():
        return hashlib.sha256(b"link\0" + os.fsencode(os.readlink(p))).digest()
    if p.is_file():
        return hashlib.sha256(b"file\0" + p.read_bytes()).digest()
    if p.is_dir():
        h = hashlib.sha256(b"dir\0")
        for top, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d != ".git")
            for name in sorted(files) + [d for d in dirs if os.path.islink(os.path.join(top, d))]:
                q = pathlib.Path(top) / name
                h.update(os.fsencode(str(q.relative_to(p))) + b"\0" + _entry_digest(q))
        return h.digest()
    return hashlib.sha256(b"other\0" if p.exists() else b"gone\0").digest()


def snapshot_tree(repo: pathlib.Path) -> dict:
    """作業ツリーの写し {"porcelain": str, "diff_sha256": str}。差分を切る節が盤面の delta-snapshot.json に置く。
    porcelain は git status --porcelain（未追跡は 1 本ずつ）。diff_sha256 は HEAD からの差分（--binary）と、未追跡の
    ファイルの名前と中身を続けた sha256——名前が同じまま中身だけ変わっても違う値になる。未追跡のフォルダ（入れ子の
    git リポジトリ）は中身を辿って続ける（_entry_digest）。git が効かなければ Reject を投げる"""
    porcelain = _git(repo, "status", "--porcelain", "--untracked-files=all")
    h = hashlib.sha256(_git(repo, "diff", "--binary", "--no-ext-diff", "HEAD", binary=True))
    for name in sorted(n for n in _git(repo, "ls-files", "--others", "--exclude-standard", "-z", binary=True).split(b"\0") if n):
        p = pathlib.Path(repo) / os.fsdecode(name).rstrip("/")
        h.update(b"\0untracked\0" + name + b"\0" + _entry_digest(p))
    return {"porcelain": porcelain, "diff_sha256": h.hexdigest()}


def _names(repo, cmd, *args) -> list:
    """git <cmd> -z <args> が出すパスの一覧（NUL 区切り。日本語などの名前も引用符や \\ の書き換え無しでそのまま）"""
    return [os.fsdecode(n) for n in _git(repo, cmd, "-z", *args, binary=True).split(b"\0") if n]


def _is_bytecode(name: str) -> bool:
    """Python のバイトコードの置き場（__pycache__/ の下）か .pyc。テストを走らせただけで出来る物で、修正ではない"""
    return name.endswith(".pyc") or "__pycache__" in name.rstrip("/").split("/")


def _touched(repo, rev) -> tuple:
    """(追跡しているファイルで rev から変わった物, 未追跡のファイル)。どちらもバイトコードを除き、名前の順"""
    tracked = _names(repo, "diff", "--name-only", "--no-renames", rev)
    untracked = _names(repo, "ls-files", "--others", "--exclude-standard", "--full-name", "--", ":/")
    return (sorted(n for n in set(tracked) if not _is_bytecode(n)),
            sorted(n for n in set(untracked) if not _is_bytecode(n)))


def touched_files(repo: pathlib.Path, rev: str) -> list:
    """修正が触ったファイル（repo の根からのパス、名前の順）。git diff --name-only <rev> と未追跡のファイル
    （入れ子の git リポジトリは `sub/` の 1 本）。__pycache__/ と .pyc は除く。差分を切る節と check_delta が同じ物を使う"""
    tracked, untracked = _touched(repo, rev)
    return sorted(set(tracked) | set(untracked))


def cut_delta(board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """修正の差分を盤面に切る（blk-delta の節 cut）。touched_files と同じファイルだけを差分に載せる:
    追跡しているファイルは git diff --binary <rev>、未追跡のファイルは 1 本ずつ git diff --no-index /dev/null <名>
    （どちらも core.quotePath=false で、日本語の名前を \\346… に書き換えずに載せる）
    （未追跡のフォルダ＝入れ子の git リポジトリは差分に載せず、files に `sub/` の 1 本で出す）。
    盤面に fix.diff と、切った時の作業ツリーの写し delta-snapshot.json（Ruling R3）を置く。
    {"ok": True, "files", "diff_file"} を返す。版が引けない・git が効かないときは Reject を投げる（拒否を dict で返さない）"""
    repo = pathlib.Path(repo)
    rev = _rev(repo, base_rev)
    tracked, untracked = _touched(repo, rev)
    diff = b""
    if tracked:   # パスを渡さないと全部の差分になるので、空なら呼ばない
        diff = _git(repo, "-c", "core.quotePath=false", "diff", "--binary", "--no-ext-diff", "--no-renames", rev, "--",
                    *[f":(top,literal){n}" for n in tracked], binary=True)
    for name in untracked:
        if name.endswith("/"):
            continue
        try:   # --no-index は差が在れば 1 で終わるので _git（0 以外は Reject）を通さない
            r = subprocess.run(["git", "-c", "core.quotePath=false", "diff", "--no-index", "--binary", "--no-ext-diff", "--", "/dev/null", name],
                               cwd=str(repo), capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Reject(f"git diff --no-index {name} を呼べない（{type(e).__name__}: {e}）")
        if r.returncode not in (0, 1):
            raise Reject(f"git diff --no-index {name} が失敗した（{r.stderr.decode('utf-8', 'replace').strip()[-300:]}）")
        diff += r.stdout
    board = pathlib.Path(board)
    board.mkdir(parents=True, exist_ok=True)
    path = board / DIFF_FILE
    path.write_bytes(diff)
    _write_board(board, SNAPSHOT_FILE, snapshot_tree(repo))
    return {"ok": True, "files": sorted(set(tracked) | set(untracked)), "diff_file": str(path)}


# ---------------------------------------------------------------- 受け付け
def check_request(items: list, board: pathlib.Path, reason: str) -> dict:
    """依頼を rules の add（graphloops の loop.py add と同じ型: [{where, text, mechanism?, measured?, false_positive_if?}]）に通す。
    通れば盤面の request.json（依頼のバッチの一覧）に積む。{"ok", "reason"}"""
    def run():
        pathlib.Path(board).mkdir(parents=True, exist_ok=True)
        rec = _rules().init_record(None, None)
        cur = _read_board(board, REQUEST_FILE)
        if cur is not None:
            rec["process"]["request_findings"] = cur
        b = _Board(board, "", record=rec)
        _rules().add(b, items, reason)
        _write_board(board, REQUEST_FILE, b.record["process"]["request_findings"])
        return {"ok": True, "reason": ""}
    return _guard(run)


def _judge_tree_unchanged(repo, board):
    """判定役が作業ツリーを変えていないか（Ruling R3・R14）。盤面に judge-snapshot.json（依頼の受け付けの時の写し）が
    在れば、今の作業ツリーがその写しと同じかを見る（依頼のファイルが対象の中で未追跡・変更中でも通る）。
    無ければ作業ツリーが綺麗（git status --porcelain が空）であることを求める。違えば Reject"""
    snap = _read_board(board, JUDGE_SNAPSHOT_FILE)
    if snap is None:
        dirty = _git(repo, "status", "--porcelain").splitlines()
        if dirty:
            raise Reject("作業ツリーに変更が在る——判定役は読むだけの役で、作業ツリーを変えてはいけない"
                         f"（git status --porcelain: {dirty[:5]}{' ほか' if len(dirty) > 5 else ''}）")
        return
    _type_errors(snap, SNAPSHOT_SCHEMA, f"盤面の {JUDGE_SNAPSHOT_FILE} ")
    now = snapshot_tree(repo)
    if now != {k: snap[k] for k in ("porcelain", "diff_sha256")}:
        raise Reject("依頼を受け付けた後から作業ツリーが変わった——判定役は読むだけの役で、作業ツリーを変えてはいけない"
                     f"（git status --porcelain: 受け付けた時 {snap['porcelain'].splitlines()[:5]} / 今 {now['porcelain'].splitlines()[:5]}）")


def check_judge(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """判定役の返答を受け付ける。作業ツリーが変わっていれば拒む（_judge_tree_unchanged。判定役は読むだけ）→ 型（graph の p2.diagnose の
    schema）→ rules の judge_output（記録の process.request_findings に盤面の request.json を入れて渡す）。
    通れば盤面の judgment.json に書く。{"ok", "reason", "open_units", "judgment_file"}"""
    def run():
        repo_p = pathlib.Path(repo)
        pathlib.Path(board).mkdir(parents=True, exist_ok=True)
        with _in_repo(repo_p):
            rev = _rev(repo_p, base_rev)
            _judge_tree_unchanged(repo_p, board)
            _type_errors(reply, role_schema("p2.diagnose"), "判定の返答")
            rules = _rules()
            rec = rules.init_record(None, None)
            req = _read_board(board, REQUEST_FILE)
            if req is not None:
                rec["process"]["request_findings"] = req
            b = _Board(board, rev, record=rec)
            out = copy.deepcopy(reply)   # judge_output は 1 行の欄と class_query を正規化する（返答の元は触らない）
            note = rules.POST_CHECKS["judge_output"](b, "p2.diagnose", out, None)
            V = validator_module(b)
            opened = [u["key"] for u in out["units"] if V.is_open(u)]
            path = _write_board(board, JUDGMENT_FILE, out)
        return {"ok": True, "reason": note or "", "open_units": opened, "judgment_file": str(path)}
    return _guard(run, open_units=[], judgment_file="")


def check_fix(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """修正役の返答を受け付ける。changes[].unit_key を修正案（1 変更 = 1 案）に読み替えて rules の fix_plan_covers_units。
    直す義務の単位は盤面の judgment.json から取る。{"ok", "reason"}"""
    def run():
        repo_p = pathlib.Path(repo)
        with _in_repo(repo_p):
            rev = _rev(repo_p, base_rev)
            _type_errors(reply, FIX_SCHEMA, "修正の返答")
            judgment = _read_board(board, JUDGMENT_FILE)
            if judgment is None:
                raise Reject(f"盤面に {JUDGMENT_FILE} が無い——判定を先に受け付けよ")
            rules = _rules()
            rec = rules.init_record(None, None)
            rec["units"], rec["questions"] = judgment.get("units") or [], judgment.get("questions") or []
            b = _Board(board, rev, record=rec)
            plan = {"plan": [{"unit_keys": [c["unit_key"]]} for c in reply["changes"]]}
            rules.POST_CHECKS["fix_plan_covers_units"](b, "p3.fix", plan, None)
        return {"ok": True, "reason": ""}
    return _guard(run)


def check_delta(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """審査役の返答を受け付ける。盤面に delta-snapshot.json が在れば、今の作業ツリーがその写しと同じかを先に見る
    （Ruling R3。無ければこの突き合わせは飛ばす）→ 型（graph の p3.delta_review の schema）→ rules の delta_review_output。
    触ったファイルは touched_files（git diff --name-only <base_rev> と未追跡のファイル）。
    通れば盤面の delta-review.json に返答を書く。{"ok", "reason", "review_file"}"""
    def run():
        repo_p = pathlib.Path(repo)
        with _in_repo(repo_p):
            rev = _rev(repo_p, base_rev)
            snap = _read_board(board, SNAPSHOT_FILE)
            if snap is not None:
                _type_errors(snap, SNAPSHOT_SCHEMA, f"盤面の {SNAPSHOT_FILE} ")
                now = snapshot_tree(repo_p)
                if now != {k: snap[k] for k in ("porcelain", "diff_sha256")}:
                    raise Reject("差分を切った後から作業ツリーが変わった——審査役は読むだけの役で、作業ツリーを変えてはいけない"
                                 f"（git status --porcelain: 切った時 {snap['porcelain'].splitlines()[:5]} / 今 {now['porcelain'].splitlines()[:5]}）")
            _type_errors(reply, role_schema("p3.delta_review"), "差分の審査の返答")
            rules = _rules()
            st = rules.DELTA_PASSES[1].state_key
            b = _Board(board, rev, loop_state={st: {"round": 1, "files": touched_files(repo_p, rev)}}, outputs={"p3.fix": {}})
            rules.POST_CHECKS["delta_review_output"](b, "p3.delta_review", reply, None)
            pathlib.Path(board).mkdir(parents=True, exist_ok=True)
            path = _write_board(board, DELTA_REVIEW_FILE, reply)
        return {"ok": True, "reason": "", "review_file": str(path)}
    return _guard(run, review_file="")
