"""受け付けの口。役の返答を、写した graphloops の規則（rules/review-loop.py）と検証器（scripts/review-record.py）に通す。

Archon を知らない関数だけを出す。ブロックの script の節がこれを呼び、結果をそのまま出口にする。
- check_request: 依頼（findings の配列）を rules の add に通し、盤面の request.json に積む
- check_judge:   判定役（p2.diagnose）の返答。作業ツリーと HEAD → 型 → class_query の例（querytest）→ rules の judge_output。通れば盤面に judgment.json
                 （check_fix と同じく、番号で指せという案内は名前を写せに戻す。_name_hints）
- check_fix:     修正役の返答。changes[].unit_key を修正案に読み替えて rules の fix_plan_covers_units（番号で指せという案内は key を写せに戻す。_name_hints）
- check_delta:   審査役（p3.delta_review）の返答。触ったファイルは git から取り、rules の delta_review_output。通れば盤面に delta-review.json
- role_schema:   graph の節の schema を、$ref を開いて注記（note）を落とした JSON Schema にする（役の output_format へ）。
                 番号で指す欄（pointers）は、番号を貼る役（numbered=True）だけ engine の型（番号か名前）に広げ、ほかは名前の型のまま。
                 修正差分のレビューは事前審査だけの kind を落とす
- snapshot_tree: 作業ツリーの写し（git が無視するファイルも入れる。依頼の受け付けと差分を切る節が盤面に置き、
                 check_judge・check_delta が突き合わせる）
- tree_state・tree_change・tree_moved: 読むだけの役（blk-pr・blk-ci・entry.take・rejudge.take）を起こす前後の作業ツリーの姿
                 （snapshot_tree に HEAD・枝を足した物）と、その違いの文（R47。check_judge・check_delta の突き合わせも tree_change で言う）。
                 bytecode=False はバイトコード（_is_bytecode）を姿から除く（測るためにコマンドを走らせる実測役の見張り。premises）
- guard・in_repo・resolve_rev・read_board・write_board・type_errors: 受け付けの部品の公開の名（ブロックの模块の受け付けが使う）
- touched_files: 修正が触ったファイル（差分を切る節と check_delta が同じ物を使う。バイトコードは除く）
- cut_delta:     修正の差分を盤面の fix.diff に切り、作業ツリーの写しを置き、前の周の審査の返答を消す（blk-delta の節 cut）

check_* は全部 dict を返し、例外で拒まない。拒否は {"ok": False, "reason": str}。
git は全部 repo を cwd にして呼ぶ。HEAD をその場で読むのは base_rev が空のときだけ（空なら repo の HEAD を版にする）。
"""
import contextlib
import functools
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

# pack の中に __pycache__ を作らない。ここで立てて止まるのは下で import する engine・rules・検証器の分だけ。
# accept.py 自身の .pyc は、この行が動く前に import の時点で書かれるので、止めるのは呼び手（import する前に立てる。
# ブロックのスクリプトの前置きは script_io の docstring）
sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parent
_GL = CORE / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

import engine.util as _util  # noqa: E402
import gatemarks  # noqa: E402
import structmark  # noqa: E402
import querytest  # noqa: E402
from engine.rules import load_rules, validator_module  # noqa: E402
from engine.schema import expand_refs, validate_schema  # noqa: E402
from engine.util import Reject  # noqa: E402
from board import DiskBoard  # noqa: E402  （規則に渡す入れ物は盤面の層の scratch。仕様 works/docs/specs/2026-09-26-board-layer-design.md 7 節）

GRAPH_PATH = _GL / "graphs" / "review-loop.json"
VALIDATOR = CORE / "scripts" / "review-record.py"
REQUEST_FILE = "request.json"        # 依頼のバッチの一覧（rules の REQUEST_SCHEMA の形）
JUDGMENT_FILE = "judgment.json"      # 受け付けた判定の返答（judge_output が正規化した後の姿。blk-judge は class_query の例を戻す）
SNAPSHOT_FILE = "delta-snapshot.json"   # 差分を切った時の作業ツリー {"porcelain": str, "ignored": [str], "diff_sha256": str}
DIFF_FILE = "fix.diff"                   # 修正の差分（cut_delta が書き、審査役が読む）
DELTA_REVIEW_FILE = "delta-review.json"  # 受け付けた審査の返答（集める節が穴の数を数える）
JUDGE_SNAPSHOT_FILE = "judge-snapshot.json"   # 判定役を起こす前（依頼の受け付けの時）の作業ツリー。形は SNAPSHOT_FILE と同じ
GIT_TIMEOUT = 120
RACY_NS = 2_000_000_000   # ファイルの時刻の細かさの上限（FAT の 2 秒）。これより新しい mtime は印だけでは信じない

# 修正役の返答のうち、受け付けが読む欄だけの型（役の output_format は blk-fix が持つ。ここは読む欄が在るかだけを見る）
FIX_SCHEMA = {"type": "object", "required": ["changes"], "properties": {
    "changes": {"type": "array", "items": {"type": "object", "required": ["unit_key"], "properties": {
        "unit_key": {"type": "string", "minLength": 1}}}}}}
# rules の拒否文のうち、番号で指せという案内（graphloops 0.21.0 の pointers 向け）と、works での言い換え。
# 判定役・修正役には番号を振った一覧を貼らず、その欄は名前（文字列）だけを通す（role_schema・FIX_SCHEMA）。
# 役は拒否文を次の試行で読むので、番号で指せと返すと直す術の無い案内になる
NUMBER_HINTS = (
    ("（写さずに、貼られた単位の no で指せ）", "（判定の key を字面のまま写せ）"),   # fix_plan_covers_units（修正）
    ("写さずに、貼られた行の no で指せ", "削除候補の where を字面のまま写せ"),       # _carried_r1_accounted（判定の carried_r1）
)


def _name_hints(e: Reject) -> Reject:
    """rules の拒否の番号で指せという案内を、名前を写せに言い換えた Reject にする（ほかの文はそのまま）"""
    msg = str(e)
    for by_number, by_name in NUMBER_HINTS:
        msg = msg.replace(by_number, by_name)
    return Reject(msg)


SNAPSHOT_KEYS = ("porcelain", "ignored", "diff_sha256")
SNAPSHOT_SCHEMA = {"type": "object", "required": list(SNAPSHOT_KEYS), "properties": {
    "porcelain": {"type": "string"}, "ignored": {"type": "array", "items": {"type": "string"}},
    "diff_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}}


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


def _unpointed(graph):
    """節の pointers（engine が一覧に振った番号で役に指させる欄。engine/pointers.py）を外した graph の写し。
    番号を貼らない役（判定・修正・差分の審査など。起こす時に番号の控えを固めない）では、番号を名前に戻す控えが無い——
    expand_refs が pointers の位置の型を [integer, string] に広げると、board が必ず拒む整数を型が通す。
    外せば名前（文字列）の型のまま残る"""
    return {**graph, "nodes": {nid: {k: v for k, v in n.items() if k != "pointers"} for nid, n in graph["nodes"].items()}}


def _drop_plan_only_kinds(node, schema):
    """修正差分のレビューの節（rules の DELTA_PASS_OF の review）なら、faces[].kind の enum から事前審査だけの語
    （rules の PLAN_ONLY_FACE_KINDS）を落とす。graph の $defs.face_kind は事前審査と共有の enum で、その語は
    delta_review_output が拒む——役の型に残すと、受け付けが必ず拒む語を型が通す"""
    rules = _rules()
    if not any(node == p.review for p in rules.DELTA_PASSES.values()):
        return schema
    kind = schema["properties"]["faces"]["items"]["properties"]["kind"]
    kind["enum"] = [k for k in kind["enum"] if k not in rules.PLAN_ONLY_FACE_KINDS]
    return schema


@functools.lru_cache(maxsize=None)
def _role_schema_json(node, numbered):
    graph = _graph() if numbered else _unpointed(_graph())
    schema = _drop_plan_only_kinds(node, _strip_notes(expand_refs(graph)["nodes"][node]["schema"]))
    if node in querytest.NODES:
        schema = _strip_notes(querytest.with_examples(schema))
    if node in gatemarks.NODES:
        schema = _strip_notes(gatemarks.with_marks(node, schema))
    if node == structmark.PLAN_NODE:
        schema = structmark.with_kept(schema)
    return json.dumps(schema, ensure_ascii=False)


def role_schema(node: str, numbered: bool = False) -> dict:
    """graph の節（"p2.diagnose" か "p3.delta_review"）の schema。$ref を開き、注記を落とした写しを返す。
    numbered は番号を貼って控えを固める役（mark_launched(pointers=)。board が番号を名前に戻す）で、pointers の位置を
    engine の widen のまま番号か名前の型に開く。ほかは名前（文字列）の型のまま（_unpointed）。修正差分のレビューは
    事前審査だけの語を kind から落とす（_drop_plan_only_kinds）。判定・再審の節（querytest.NODES）は class_query に例の欄
    （hits・misses）を足す（写しの型は持てない。受け付けが盤面へ渡す前に外す）。修正案と事前審査の節（gatemarks.NODES）は
    関所の項目の行に決め手の欄を足す（同じく受け付けが外して盤面の gate-marks.json に置く）"""
    return json.loads(_role_schema_json(node, numbered))


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


# 受け付けの部品の公開の名（ブロックの模块の受け付け——premises など——が私的な名前を借りずに使う。層の決まり private）
guard = _guard
in_repo = _in_repo
resolve_rev = _rev
read_board = _read_board
write_board = _write_board
type_errors = _type_errors


def _entry_digest(p: pathlib.Path, racy_after=None, marks=None) -> bytes:
    """未追跡の 1 本の sha256。symlink はリンク先の名前、ファイルは中身、フォルダ（入れ子の git リポジトリは
    git が `sub/` の 1 行で出す）は中の全部の名前と印を名前の順に続けた物（.git の下は除く）。それ以外（FIFO など）は種類だけ。
    marks（1 つの要素の list）を渡すと、ファイルは中身を読まず stat の印（mode・大きさ・mtime_ns・ino。git の index と
    同じ考え——git の Documentation/technical/racy-git.txt）にし、見た mtime_ns の最大を marks[0] に入れる。ただし
    mtime_ns が racy_after より後（写した時刻に近すぎて、同じ大きさの素早い書き換えを印で見分けられない）のファイルは中身も足す"""
    if p.is_symlink():
        return hashlib.sha256(b"link\0" + os.fsencode(os.readlink(p))).digest()
    if p.is_file():
        if marks is None:
            return hashlib.sha256(b"file\0" + p.read_bytes()).digest()
        st = p.stat()
        marks[0] = max(marks[0], st.st_mtime_ns)
        h = hashlib.sha256(f"stat\0{st.st_mode} {st.st_size} {st.st_mtime_ns} {st.st_ino}".encode())
        if st.st_mtime_ns > racy_after:
            h.update(b"\0racy\0" + p.read_bytes())
        return h.digest()
    if p.is_dir():
        h = hashlib.sha256(b"dir\0")
        for top, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d != ".git")
            for name in sorted(files) + [d for d in dirs if os.path.islink(os.path.join(top, d))]:
                q = pathlib.Path(top) / name
                h.update(os.fsencode(str(q.relative_to(p))) + b"\0" + _entry_digest(q, racy_after, marks))
        return h.digest()
    return hashlib.sha256(b"other\0" if p.exists() else b"gone\0").digest()


def _ignored_digests(repo, names) -> list:
    """git が無視するパス（names）ごとの印（_entry_digest の stat の印。無視されるフォルダ——.venv・node_modules など——は
    大きいので中身を読まない）。写す時刻から RACY_NS 以内に書かれたファイルが在れば、その書き込みから RACY_NS 過ぎるまで
    （上限 RACY_NS）待って印を取り直す。待った後の書き換えは、時刻の細かさ（最大でも 2 秒）を越えて mtime が変わるので、
    印だけで見分けられる。待っても近い物（時計が進んだ mtime）は、racy として中身も足す"""
    for attempt in range(2):
        racy_after = time.time_ns() - RACY_NS
        marks = [0]
        digests = [_entry_digest(repo / name.rstrip("/"), racy_after, marks) for name in names]
        if marks[0] <= racy_after or attempt:
            return digests
        time.sleep(min(marks[0] - racy_after, RACY_NS) / 1e9 + 0.01)


def _ignored_entries(repo) -> list:
    """git が無視するパス（repo の根から。名前の順）。git status --porcelain -z --ignored=matching（git-status(1)）の `!!` の行で、
    丸ごと無視されるフォルダ（`__pycache__/`・`.venv/` など）は `dir/` の 1 本に畳まれる"""
    fields = _git(repo, "status", "--porcelain", "-z", "--ignored=matching", "--untracked-files=all", binary=True).split(b"\0")
    out, skip = [], False
    for f in fields:
        if skip or not f:   # 名前の変わった行（X か Y が R・C）は、元の名前がもう 1 つの欄で続く
            skip = False
            continue
        if f[:1] in (b"R", b"C") or f[1:2] in (b"R", b"C"):   # Y が R は intent-to-add を伴う作業ツリーの rename
            skip = True
        elif f.startswith(b"!! ") and not _cli_owned_only(repo, os.fsdecode(f[3:])):
            out.append(os.fsdecode(f[3:]))
    return sorted(out)


def _cli_owned(path: str) -> bool:
    """path（リポジトリの根からの相対。末尾の / は問わない）が Claude Code の控えのフォルダ CLI_OWNED（深さを問わず
    `<どこか>/.claude/.cc-writes`）か、その下か"""
    parts = path.rstrip("/").split("/")
    return any(parts[i:i + len(CLI_OWNED_PARTS)] == list(CLI_OWNED_PARTS) for i in range(len(parts)))


def _cli_owned_only(repo, entry: str) -> bool:
    """entry（_ignored_entries の 1 本）が CLI_OWNED の下か、中身が全部 CLI_OWNED の下のフォルダ（git が `<dir>/.claude/` に
    畳んだ時）か。空の `<dir>/.claude/` も数えない（Claude Code が控えのフォルダを作る時に先に作る親）"""
    if _cli_owned(entry):
        return True
    if not entry.endswith("/"):
        return False
    root = pathlib.Path(repo)
    leaves = [p.relative_to(root).as_posix() for p in (root / entry).rglob("*") if not p.is_dir() or not any(p.iterdir())]
    if not leaves:
        return entry.rstrip("/").split("/")[-1] == CLI_OWNED_PARTS[0]
    return all(_cli_owned(leaf) for leaf in leaves)


# Claude Code（2.1.283）が作る原子的な書き込みの控えのフォルダ（ensureAtomicWriteStagingDirs。sandbox の Bash の cwd・起動の
# cwd・設定の置き場ごとに `<dir>/.claude/.cc-writes/` を 0700 で作り、全体の除外 ~/.config/git/ignore に **/.claude/.cc-writes/
# を足す。中は書き込みの間だけの `<名>.tmp.<16 進 8 字>` で、ふだんは空）。役の書いた物ではないので、作業ツリーの見張りは
# 深さを問わず数えない（台帳 R62: 自分食い 23 件目で根の、run 30 で works/docs/specs/ の下の物で読むだけの役が 3 回拒まれた）。
# 同じ .claude/ の下のほかの物は見る
CLI_OWNED_PARTS = (".claude", ".cc-writes")
CLI_OWNED = "/".join(CLI_OWNED_PARTS) + "/"


def _porcelain_path(line: str) -> str:
    """git status --porcelain の 1 行のパス（改名は後ろの名。引用符は外す）"""
    path = line[3:].split(" -> ")[-1]
    return path[1:-1] if len(path) >= 2 and path[0] == path[-1] == '"' else path


_NO_BYTECODE = (":(top)", ":(top,exclude,glob)**/*.pyc", ":(top,exclude,glob)**/__pycache__/**")   # git の pathspec で _is_bytecode と同じ物を除く


def snapshot_tree(repo: pathlib.Path, *, bytecode: bool = True) -> dict:
    """作業ツリーの写し {"porcelain": str, "ignored": [str], "diff_sha256": str}。依頼の受け付けが盤面の judge-snapshot.json に、
    差分を切る節が delta-snapshot.json に置き、読むだけの役（判定・審査）の受け付けが今の写しと突き合わせる。
    porcelain は git status --porcelain（未追跡は 1 本ずつ）。ignored は git が無視するパス（_ignored_entries。
    差分には載らないが、後の節——テスト——の緑赤を左右する物も在るので、読むだけの役が足しても見逃さない）。
    diff_sha256 は HEAD からの差分（--binary）と、未追跡のファイルの名前と中身・無視されるパスの名前と stat の印
    （_ignored_digests。中身は読まない）を続けた sha256——名前が同じまま中身だけ変わっても違う値になる。フォルダ（入れ子の
    git リポジトリ・無視されるフォルダ）は中を辿って続ける（_entry_digest）。git が効かなければ Reject を投げる。
    bytecode=False はバイトコード（_is_bytecode。__pycache__/ の下と .pyc）を porcelain・差分・未追跡・無視されるパスの
    どれからも除く（測るために試験を走らせる役が作る物を変化に数えない。修正の差分の側の touched_files と同じ定義）"""
    repo = pathlib.Path(repo)
    porcelain = _git(repo, "status", "--porcelain", "--untracked-files=all")
    porcelain = "".join(f"{ln}\n" for ln in porcelain.splitlines()
                        if not (ln.startswith("?? ") and _cli_owned(_porcelain_path(ln)))
                        and (bytecode or not _is_bytecode(_porcelain_path(ln))))
    h = hashlib.sha256(_git(repo, "diff", "--binary", "--no-ext-diff", "HEAD", *(() if bytecode else ("--", *_NO_BYTECODE)),
                            binary=True))
    for name in sorted(n for n in _git(repo, "ls-files", "--others", "--exclude-standard", "-z", binary=True).split(b"\0") if n):
        if (not bytecode and _is_bytecode(os.fsdecode(name))) or _cli_owned(os.fsdecode(name)):
            continue
        p = repo / os.fsdecode(name).rstrip("/")
        h.update(b"\0untracked\0" + name + b"\0" + _entry_digest(p))
    ignored = [n for n in _ignored_entries(repo) if bytecode or not _is_bytecode(n)]
    for name, digest in zip(ignored, _ignored_digests(repo, ignored)):
        h.update(b"\0ignored\0" + os.fsencode(name) + b"\0" + digest)
    return {"porcelain": porcelain, "ignored": ignored, "diff_sha256": h.hexdigest()}


def _assert_same_tree(repo, snap, name, since, role):
    """盤面の写し snap（name から読んだ snapshot_tree の形）と今の作業ツリーが同じでなければ Reject。since は『〜から』の句、
    role は読むだけの役。違いの文は共通の tree_change（SNAPSHOT_KEYS の欄だけ。R47）"""
    _type_errors(snap, SNAPSHOT_SCHEMA, f"盤面の {name} ")
    moved = tree_change(snap, snapshot_tree(repo), SNAPSHOT_KEYS)
    if moved:
        raise Reject(f"{since}から作業ツリーが変わった——{role}は読むだけの役で、作業ツリーを変えてはいけない（{'・'.join(moved)}）")


TREE_KEYS = ("porcelain", "diff_sha256", "ignored", "head", "ref")
TREE_SCHEMA = {"type": "object", "required": list(TREE_KEYS), "properties": {
    **SNAPSHOT_SCHEMA["properties"], "head": {"type": "string"}, "ref": {"type": "string"}}}


def tree_state(repo: pathlib.Path, *, bytecode: bool = True) -> dict:
    """読むだけの役（blk-pr の並行 PR・blk-ci の CI・entry.take と rejudge.take が受ける役）を起こす前後に比べる作業ツリーの姿 {TREE_KEYS}:
    snapshot_tree（porcelain・git が無視するパスの一覧 ignored・diff_sha256。無視されるパスの stat の印も diff_sha256 に入る——
    無視されるファイルは差分に載らないが、後の節のテストの緑赤を左右しうる）に、HEAD の sha head・枝 ref
    （symbolic-ref。切り離した HEAD は空）を足した物。snapshot_tree は今の HEAD からの差分しか見ないので、枝の切り替え
    （gh pr checkout・git checkout）は head・ref で見る。HEAD が引けない・git が効かなければ Reject。bytecode は snapshot_tree と同じ"""
    repo = pathlib.Path(repo)
    try:
        head = _git(repo, "rev-parse", "--verify", "-q", "HEAD").strip()
    except Reject:
        raise Reject(f"git rev-parse HEAD が引けない（{repo}）") from None
    try:
        ref = _git(repo, "symbolic-ref", "-q", "HEAD").strip()
    except Reject:   # 切り離した HEAD（symbolic-ref -q は 1 で終わる）
        ref = ""
    return {**snapshot_tree(repo, bytecode=bytecode), "head": head, "ref": ref}


def tree_change(before: dict, now: dict, keys=TREE_KEYS) -> list:
    """tree_state（keys を SNAPSHOT_KEYS にすれば snapshot_tree）の 2 つの違いを人に向けた文の一覧で（同じなら空）。keys の欄だけを
    比べる。porcelain は違う時だけ頭の 5 行、head・ref は前と今、ignored は増えた・消えたパスの頭の 5 本。diff_sha256 が違えば
    （porcelain の行が同じままの中身の書き換えも）その 1 行を足す"""
    if all(before.get(k) == now.get(k) for k in keys):
        return []
    out = []
    if "porcelain" in keys and before["porcelain"] != now["porcelain"]:
        out.append(f"git status --porcelain: 役を起こす前 {before['porcelain'].splitlines()[:5]} / 今 {now['porcelain'].splitlines()[:5]}")
    for k in ("head", "ref"):
        if k in keys and before[k] != now[k]:
            out.append(f"{k}: 役を起こす前 {before[k] or '（切り離した HEAD）'} / 今 {now[k] or '（切り離した HEAD）'}")
    if "ignored" in keys:
        added = sorted(set(now["ignored"]) - set(before["ignored"]))
        gone = sorted(set(before["ignored"]) - set(now["ignored"]))
        if added or gone:
            out.append(f"git が無視するパス: 増えた {added[:5]} 消えた {gone[:5]}")
    if "diff_sha256" in keys and before["diff_sha256"] != now["diff_sha256"]:
        out.append("HEAD からの差分・未追跡のファイル・git が無視するパスのどれかの中身が変わった（diff_sha256）")
    return out


def tree_moved(before: dict, repo: pathlib.Path, *, bytecode: bool = True) -> list:
    """役を起こす前の姿 before（tree_state）と今の作業ツリーの違いの文（tree_change）。今の姿が引けない（HEAD が無い・git が
    効かない）ときはその 1 行——起こす前は引けたので、役が HEAD を動かした（checkout --orphan など）。bytecode は before を
    取った時と同じ値を渡す"""
    try:
        now = tree_state(repo, bytecode=bytecode)
    except Reject as e:
        return [f"作業ツリー・HEAD が引けなくなった: {e}"]
    return tree_change(before, now)


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
    盤面に fix.diff と、切った時の作業ツリーの写し delta-snapshot.json（Ruling R3）を置き、前の周の delta-review.json を消す。
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
    (board / DELTA_REVIEW_FILE).unlink(missing_ok=True)   # 前の呼び出しの残り。collect が拾えるのはこの呼び出しの受け付けが書いた物だけ
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
        b = DiskBoard.scratch(board, review_rev="", record=rec)
        _rules().add(b, items, reason)
        _write_board(board, REQUEST_FILE, b.record["process"]["request_findings"])
        return {"ok": True, "reason": ""}
    return _guard(run)


def _head_at_rev(repo, rev, role):
    """HEAD が数える版 rev のままか。動いていれば Reject（写しの無い見張りで、役が作った物を commit して
    git status を空に戻す道を塞ぐ。dogfood run 21）。role は読むだけの役の名"""
    head = _git(repo, "rev-parse", "--verify", "-q", "HEAD").strip()
    if head != rev:
        raise Reject(f"HEAD が数える版から動いた（版 {rev[:12]} / 今 {head[:12]}）——{role}は作業ツリーと履歴を変えてはいけない"
                     "（commit・reset・checkout で履歴を動かさない）")


def _judge_tree_unchanged(repo, board, rev):
    """判定役が作業ツリーを変えていないか（Ruling R3・R14）。盤面に judge-snapshot.json（依頼の受け付けの時の写し）が
    在れば、今の作業ツリーがその写しと同じかを見る（依頼のファイルが対象の中で未追跡・変更中でも通る。git が無視する
    ファイルの増減・書き換えも見る）。写しが tree_state の形（intake が置く。HEAD と枝を持つ）なら共通の tree_moved
    （R47）で HEAD・枝の移動も見る。snapshot_tree の形（前の版の盤面）は porcelain・ignored・diff_sha256 だけを比べる。
    無ければ作業ツリーが綺麗（snapshot_tree の porcelain と git が無視するパスが空）で、HEAD が数える版 rev の
    ままであることを求める（_head_at_rev）。違えば Reject"""
    snap = _read_board(board, JUDGE_SNAPSHOT_FILE)
    if snap is None:
        now = snapshot_tree(repo)   # 共通の姿（Claude Code の控えのフォルダ CLI_OWNED を数えない）
        dirty = now["porcelain"].splitlines() + [f"!! {n}" for n in now["ignored"]]
        if dirty:
            raise Reject("作業ツリーに変更が在る——判定役は読むだけの役で、作業ツリーを変えてはいけない"
                         f"（git status --porcelain --ignored: {dirty[:5]}{' ほか' if len(dirty) > 5 else ''}）")
        _head_at_rev(repo, rev, "判定役")
        return
    if isinstance(snap, dict) and ("head" in snap or "ref" in snap):
        _type_errors(snap, TREE_SCHEMA, f"盤面の {JUDGE_SNAPSHOT_FILE} ")
        moved = tree_moved({k: snap[k] for k in TREE_KEYS}, repo)
        if moved:
            raise Reject("依頼を受け付けた後から作業ツリーが変わった——判定役は読むだけの役で、作業ツリー・HEAD・枝・git が"
                         f"無視するファイルを変えてはいけない（{'・'.join(moved)}）")
        return
    _assert_same_tree(repo, snap, JUDGE_SNAPSHOT_FILE, "依頼を受け付けた後", "判定役")


def check_judge(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """判定役の返答を受け付ける。作業ツリーか HEAD が変わっていれば拒む（_judge_tree_unchanged。判定役は読むだけ）→ 型（graph の p2.diagnose の
    schema）→ class_query の例（querytest）→ rules の judge_output（記録の process.request_findings に盤面の request.json を入れて渡す）。
    通れば盤面の judgment.json に書く（例は外して judge_output に通し、query-examples.json に置いて戻す）。{"ok", "reason", "open_units", "judgment_file"}"""
    def run():
        repo_p = pathlib.Path(repo)
        pathlib.Path(board).mkdir(parents=True, exist_ok=True)
        with _in_repo(repo_p):
            rev = _rev(repo_p, base_rev)
            _judge_tree_unchanged(repo_p, board, rev)
            _type_errors(reply, role_schema("p2.diagnose"), "判定の返答")
            rules = _rules()
            rec = rules.init_record(None, None)
            req = _read_board(board, REQUEST_FILE)
            if req is not None:
                rec["process"]["request_findings"] = req
            b = DiskBoard.scratch(board, review_rev=rev, record=rec)
            V = validator_module(b)
            errs = querytest.problems(reply.get("units"), V.is_open)
            if errs:
                raise Reject("class_query の例が問いと合わない: " + "; ".join(errs))
            out, examples = querytest.split(reply, V.is_open)   # judge_output は 1 行の欄と class_query を正規化する（split の写し。返答の元は触らない）
            try:
                note = rules.POST_CHECKS["judge_output"](b, "p2.diagnose", out, None)
            except Reject as e:
                raise _name_hints(e)
            opened = [u["key"] for u in out["units"] if V.is_open(u)]
            if examples or (pathlib.Path(board) / querytest.EXAMPLES_FILE).is_file():   # 例の無い判定は前の周の例を消すだけ
                querytest.save(board, examples, replace=True)
            path = _write_board(board, JUDGMENT_FILE, querytest.restore(out, board))
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
            b = DiskBoard.scratch(board, review_rev=rev, record=rec)
            plan = {"plan": [{"unit_keys": [c["unit_key"]]} for c in reply["changes"]]}
            try:
                rules.POST_CHECKS["fix_plan_covers_units"](b, "p3.fix", plan, None)
            except Reject as e:
                raise _name_hints(e)
        return {"ok": True, "reason": ""}
    return _guard(run)


def check_delta(reply: dict, board: pathlib.Path, base_rev: str, repo: pathlib.Path) -> dict:
    """審査役の返答を受け付ける。盤面に delta-snapshot.json が在れば、今の作業ツリーがその写しと同じかを先に見る
    （Ruling R3。git が無視するファイルの増減・書き換えも見る。無ければこの突き合わせは飛ばす）→ 型（graph の p3.delta_review の schema）→ rules の delta_review_output。
    触ったファイルは touched_files（git diff --name-only <base_rev> と未追跡のファイル）。
    通れば盤面の delta-review.json に返答を書く。{"ok", "reason", "review_file"}"""
    def run():
        repo_p = pathlib.Path(repo)
        with _in_repo(repo_p):
            rev = _rev(repo_p, base_rev)
            snap = _read_board(board, SNAPSHOT_FILE)
            if snap is not None:
                _assert_same_tree(repo_p, snap, SNAPSHOT_FILE, "差分を切った後", "審査役")
            _type_errors(reply, role_schema("p3.delta_review"), "差分の審査の返答")
            rules = _rules()
            st = rules.DELTA_PASSES[1].state_key
            b = DiskBoard.scratch(board, review_rev=rev, loop_state={st: {"round": 1, "files": touched_files(repo_p, rev)}})
            rules.POST_CHECKS["delta_review_output"](b, "p3.delta_review", reply, None)
            pathlib.Path(board).mkdir(parents=True, exist_ok=True)
            path = _write_board(board, DELTA_REVIEW_FILE, reply)
        return {"ok": True, "reason": "", "review_file": str(path)}
    return _guard(run, review_file="")
