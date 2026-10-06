"""部品の置き場（scope）と宣言（manifest）の読み口（依頼 239）。層 L3。

部品（ブロック）が盤面で読み書きしてよいのは、自分の scope の根・宣言した入力（consumes）・宣言した出力（produces）の 3 つだけ。
宣言はブロックか線のフォルダごとの manifest.json（形の正本は同じ置き場の manifest.schema.json）。ここはそれを読んで照らし、
公開の名（scope の外の周の置き場 r<N>/ に置く名）と持ち主を引く口、scope の登録（r<N>/scopes.json）と、scope の根に分かれた
同じ名のファイルを集める口を持つ。盤面を開く口 entry.open_board が scope を決めて登録し、盤面の作業ファイルの置き場を分ける。

- PACK: works の pack の根（blk-*/ と線のフォルダ＝nodes.json を持つフォルダの親）
- ManifestBroken(BoardGap): manifest が無い・読めない・形が合わない（パスと誤りの全部を文に載せる）
- manifest(owner_dir): 1 つの owner の manifest を読んで照らした dict
- manifests(pack): 全部の owner（blk-*/ と線のフォルダ）の名 → manifest（読んで照らすのはプロセスごとに 1 度）
- published(pack): per_include でなく周の置き場（at が round）に置く produces の名（fnmatch の形を含む）の集合
- SHARED: 共有の記録（core・engine・rules が書き、どの scope の窓で変わってもよい物）の形。SHARED_ROUND と ROOT_DIRS はここから引く
- SHARED_ROUND: core が書き、どの scope からも同じ周の置き場 r<N>/ に置く共有の記録の名（scope の根に分けない）
- round_names(pack): 盤面の work が scope の根でなく r<N>/ に置く名（published と SHARED_ROUND の和。entry.open_board が渡す）
- owner_of(name, pack): その名を per_include でなく出す owner（無ければ None）
- matches(name, pattern): "/" で区切った段ごとの fnmatch（* は段をまたがない。末尾の ** は 1 段以上の残りの全部。board.name_matches）
- running_block(): 今のプロセスが起こされたスクリプトのブロックの名（<pack>/<名>/scripts/<x>.py の <名>。ほかは ""）
- claim(board_dir, round_, scope, block): r<N>/scopes.json に scope とブロックを登録する（同じ scope を別のブロックが名乗る・
  scope の名が盤面の根の物とぶつかれば BoardGap）
- all_rounds(board_dir, pattern): 全部の周の r<N>/<pattern> と <scope>/r<N>/<pattern>（周の順、同じ周は線・登録の順）
- scope_roots(b): 盤面の根と、今の周に登録した scope の根（線・登録の順。盤面の根に置く per_include の物を集める口）
- each(b, name): 今の周の r<N>/<name> と、登録した scope の根の r<N>/<name> のうち在る物（線・登録の順。最後が一番新しい include）
- shared(path): 盤面の根からのパスが共有の記録に当たるか
- snapshot(board_dir): 盤面の下の全部のファイルの相対パス → [大きさ, mtime_ns]（窓の控え）
- check_window(board_dir, window, pack): 窓を開いてからの盤面の変化を窓の scope のブロックの宣言に照らした誤りの全部
  （宣言の外の書き込み・公開の名の持ち主の重なり・JSON の出力の Schema。線の窓は照らさない。opener の
  scope の根は、盤面を開く前に書いたその scope の物として通す）
- reads_outside(board_dir, window, pack): 窓の間の読んだ証拠のうち、宣言の外の盤面のパス（落とさない。外れ D4）
- missing_required(board_dir, window, pack): 窓の終わりに無い必須の出力（止めない。trace と報告に載せる）
- window_key(scope): 窓の鍵（fan_out の子は同じ fan の子の全部に当たる形 <fan の節>--*。ほかは scope のまま）
- enter(board_dir, round_, scope, block): 盤面を開く口が節の中で呼ぶ。窓の鍵が替われば前の窓を照らして誤りを返し（呼び手が
  盤面を止める）、必須の出力の欠けと宣言の外の読みを trace に積み、今の鍵の窓 scope-window.json を開く

fan_out の子（flow_adapter.fan_node）: 同じ fan の子は同時に走り、1 つの盤面の窓を分け合う。窓を子ごとに分けると、後から開いた子が
前の子の窓を閉じ、前の子が後で書く自分の scope の根の物を後の子の宣言の外の書き込みと読む（盤面の変化を書いた子に結び付ける
手が無い）。なので窓は fan ごとに 1 つ（鍵 <fan の節>--*）にし、子の全部の scope の根を窓の scope の根として通し、公開の名の持ち主も
鍵で記録する。照らすのは fan の子の全部を合わせた変化と、子が差し込む部品の宣言（同じ fan の子は同じ部品）。子の間は照らさない:
子がほかの子の scope の根に書く・同じ周の同じ公開の名を 2 つの子が書く、は見えない（docs/darkfactory-flow.md の死角）。

名の形は段ごとに当てる（* が / をまたぐ fnmatch のままだと、rejects-*.json が rejects-a/b.json のような scope の下の私物まで
公開の名に数える）。形の字は manifest を読む時に照らす: 空の段・"."・".."・頭の "/" を持たず、** は末尾の段そのものだけ。
"""
from __future__ import annotations

import copy
import fcntl
import functools
import json
import os
import pathlib
import re
import sys

_CORE = pathlib.Path(__file__).resolve().parent
_GL = _CORE / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

import flow_adapter  # noqa: E402
from board import SAVE_LOCK, BoardGap, name_matches  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from engine.util import now  # noqa: E402

PACK = _CORE.parents[1]                       # works/（.shared/core の 2 つ上）
MANIFEST = "manifest.json"                    # owner のフォルダの宣言のファイル
SCHEMA_PATH = _CORE / "manifest.schema.json"  # manifest の形の正本
BLOCK_GLOB = "blk-*"                          # ブロックのフォルダ
LINE_MARK = "nodes.json"                      # 線のフォルダの印（tests/test_layers の L7 と同じ見分け）
ANY_BELOW = "**"                              # 名の形の末尾の段だけに置ける「下の全部」
REGISTRY = "scopes.json"                      # 周の置き場の scope の登録 {<scope>: {"block": <名>, "order": <登録の順>}}
REGISTRY_LOCK = "scopes.json.lock"            # 登録の読み書きの錠（fcntl.flock。待つ上限は持たない）
SCRIPTS_DIR = "scripts"                       # ブロックのスクリプトの置き場（<pack>/<名>/scripts/<x>.py）
WINDOW = "scope-window.json"                  # 盤面の根の今の窓 {scope, block, round, files: snapshot}（enter が書く）
WINDOW_LOCK = "scope-window.json.lock"        # 窓の読み書きの錠（fcntl.flock。待つ上限は持たない）
READ_OUTSIDE_OP = "scope_read_outside"        # 窓の宣言の外の読みの trace の行 {scope, paths}（落とさない。外れ D4）
REQUIRED_MISSING_OP = "scope_required_missing"  # 窓の終わりに無かった必須の出力の trace の行 {scope, names}（止めない）
SCOPE_CHECK_BY = "works:scope-check"          # 窓の照らしが盤面を止めた state.stop.by
STOP_AFTER_END_OP = "stop_after_round_end"    # 周を締めた盤面に止めが来た印の trace の行（line_edge・report と同じ語。b.stop は拒む）
OWNS = "owns"                                 # 周の scopes.json の鍵: 公開の名 → それを書いた scope（周ごとに持ち主は 1 つ）
_ROUND_DIR = "r[0-9]*"                        # 周の置き場 r<N> の段の形（共有の記録の形の頭）
_ROUND_NAME = re.compile(r"r\d+")              # 周の置き場 r<N> の段そのもの（board._ROUND_NAME と同じ字）
# 共有の記録: core・engine・rules が書き、どの scope の窓で変わってもよい物の形（測り M2 の class shared と scope の登録・窓。
# 盤面の根からのパスに段ごとに当てる。/ を持たない形は盤面の根の名にしか当たらない）。照らし・周の置き場の名・根のフォルダの 1 つの組
SHARED = ("state.json", "record.json", "trace.jsonl", "STOP", "query-examples.json", "count-cache.json", "count-budget.json",
          "accept-rev-cache.json", f"{_ROUND_DIR}/fixgates-base.json",   # 受け付けの試験の結末の控え（どの scope の受け付けも使い回す）
          "diff-r*.patch", "changed-r*.txt", "*-r*.patch",
          "out/**", "runs/**", "rounds/**", "prompts/**", "roles/**", "items/**", "policy/**", "lanes/**", "tdd-*/**",
          f"{_ROUND_DIR}/conflicts.json", f"{_ROUND_DIR}/libdocs.json", f"{_ROUND_DIR}/libdocs/**",
          f"{_ROUND_DIR}/{REGISTRY}", f"{_ROUND_DIR}/{REGISTRY_LOCK}", f"{_ROUND_DIR}/{REGISTRY}.tmp",
          WINDOW, WINDOW_LOCK, f"{WINDOW}.tmp", SAVE_LOCK)
# 共有の記録のうち周の置き場 r<N>/ に置く名（scope の根に分けない。盤面の work が r<N>/ に置く）
SHARED_ROUND = frozenset(p.split("/", 1)[1] for p in SHARED if p.startswith(_ROUND_DIR + "/"))
# 盤面の根に core・engine・rules・部品が作るフォルダの名の形（共有の記録の <頭>/** の頭）。scope の名がこれに当たると、私物が
# 根の記録に混ざるので登録しない
ROOT_DIRS = frozenset(p.split("/")[0] for p in SHARED if p.count("/") == 1 and p.endswith("/" + ANY_BELOW))


class ManifestBroken(BoardGap):
    """manifest が無い・読めない・形が合わない・owner がフォルダの名と違う。文にパスと誤りの全部を載せる"""


matches = name_matches   # name が pattern に当たるか（段ごとの fnmatchcase。盤面の work と同じ 1 つの当て方）


def _name_errors(name: str, where: str) -> list[str]:
    """名の形の誤り（空の段・"."・".."・頭の "/"・"\\"・末尾の段そのものでない **）"""
    segs = name.split("/")
    bad = name.startswith("/") or "\\" in name or any(s in ("", ".", "..") for s in segs) \
        or any(ANY_BELOW in s and (s != ANY_BELOW or i != len(segs) - 1) for i, s in enumerate(segs))
    return [f"{where}: 名の形 {name!r} が使えない（/ で区切った段に空・.・.. を持たず、** は末尾の段そのものだけ）"] if bad else []


def _conditions(value, schema: dict, path: str = "$") -> list[str]:
    """validate_schema が見ない allOf の if／then を当てた誤り（manifest.schema.json の条件。properties と items の下も辿る）"""
    errs = []
    for c in schema.get("allOf", []):
        if "if" in c and not validate_schema(value, c["if"], path):
            errs += validate_schema(value, c.get("then", {}), path)
    if isinstance(value, dict):
        for k, s in schema.get("properties", {}).items():
            if k in value:
                errs += _conditions(value[k], s, f"{path}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errs += _conditions(v, schema["items"], f"{path}[{i}]")
    return errs


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def manifest(owner_dir: pathlib.Path) -> dict:
    """owner_dir/manifest.json を読み、manifest.schema.json と名の形と owner の名と schema のファイルに照らした dict。
    無い・読めない・合わないは ManifestBroken（パスと誤りの全部）"""
    owner_dir = pathlib.Path(owner_dir)
    path = owner_dir / MANIFEST
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ManifestBroken(f"manifest {path} が読めない: {type(e).__name__}: {e}") from None
    schema = _schema()
    errs = validate_schema(doc, schema) + _conditions(doc, schema)
    if isinstance(doc, dict):
        if doc.get("owner") != owner_dir.name:
            errs.append(f"$.owner: {doc.get('owner')!r} がフォルダの名 {owner_dir.name!r} と違う")
        seen = set()
        for key in ("consumes", "produces"):
            rows = doc.get(key)
            for i, row in enumerate(rows if isinstance(rows, list) else []):
                name = row.get("name") if isinstance(row, dict) else None
                if not isinstance(name, str):
                    continue
                errs += _name_errors(name, f"$.{key}[{i}].name")
                if key == "produces":
                    if name in seen:
                        errs.append(f"$.produces[{i}].name: {name!r} を 2 度宣言している")
                    seen.add(name)
                    rel = row.get("schema")
                    if isinstance(rel, str):   # core が書く形（reads-<役>.json など）は core の Schema を owner から指す
                        target = (owner_dir / rel).resolve()
                        if not (target.is_relative_to(owner_dir.resolve().parent) and target.is_file()):
                            errs.append(f"$.produces[{i}].schema: {rel!r} が pack の下のファイルでない（{owner_dir} から）")
    if errs:
        raise ManifestBroken(f"manifest {path} が合わない:\n" + "\n".join(f"  - {e}" for e in errs))
    return doc


def _owner_dirs(pack: pathlib.Path) -> list[pathlib.Path]:
    pack = pathlib.Path(pack)
    blocks = [p for p in pack.glob(BLOCK_GLOB) if p.is_dir()]
    lines = [p.parent for p in pack.glob(f"*/{LINE_MARK}")]
    return sorted(set(blocks) | set(lines))


@functools.lru_cache(maxsize=None)
def _loaded(pack: str) -> dict[str, dict]:
    """pack の全部の manifest を読んで照らした物（プロセスごとに 1 度。盤面を開くたびに読み直さない。呼び手は書き換えない）"""
    out, broken = {}, []
    for d in _owner_dirs(pathlib.Path(pack)):
        try:
            out[d.name] = manifest(d)
        except ManifestBroken as e:
            broken.append(str(e))
    if broken:
        raise ManifestBroken("\n".join(broken))
    return out


def manifests(pack: pathlib.Path = PACK) -> dict[str, dict]:
    """pack の全部の owner（blk-*/ と nodes.json を持つ線のフォルダ）の名 → manifest。壊れた物が在れば、全部の文を 1 つの
    ManifestBroken に並べる。読むのはプロセスごとに 1 度（_loaded）で、返すのは写し（呼び手が書き換えても控えは変わらない）"""
    return copy.deepcopy(_loaded(str(pathlib.Path(pack).resolve())))


def published(pack: pathlib.Path = PACK) -> frozenset[str]:
    """per_include でなく at が round（既定）の produces の名（形を含む）の和。盤面の公開の置き場 r<N>/ に置く名
    （at が root の名は盤面の根に書かれ、work を通らない）"""
    return frozenset(p["name"] for m in _loaded(str(pathlib.Path(pack).resolve())).values() for p in m["produces"]
                     if not p.get("per_include") and p.get("at", "round") == "round")


def round_names(pack: pathlib.Path = PACK) -> frozenset[str]:
    """盤面の work が scope の根でなく周の置き場 r<N>/ に置く名（published と共有の記録 SHARED_ROUND の和）"""
    return published(pack) | SHARED_ROUND


def owner_of(name: str, pack: pathlib.Path = PACK) -> str | None:
    """name を per_include でなく出す owner（どの produces の形にも当たらなければ None）。2 つの owner の形に当たれば
    ManifestBroken（持ち主は 1 つ）"""
    hits = sorted({owner for owner, m in _loaded(str(pathlib.Path(pack).resolve())).items() for p in m["produces"]
                   if not p.get("per_include") and matches(name, p["name"])})
    if len(hits) > 1:
        raise ManifestBroken(f"名 {name!r} を 2 つ以上の owner が公開の名に宣言している: {', '.join(hits)}")
    return hits[0] if hits else None


# ---------------------------------------------------------------- scope の登録と集め
def running_block() -> str:
    """今のプロセスが起こされたスクリプトのブロックの名（sys.argv[0] が <pack>/<名>/scripts/<x>.py なら <名>、ほかは ""）"""
    argv0 = sys.argv[0] if sys.argv and sys.argv[0] else ""
    p = pathlib.Path(argv0)
    if p.suffix != ".py" or p.parent.name != SCRIPTS_DIR or len(p.parents) < 3:
        return ""
    return p.parent.parent.name


def _read_registry(path: pathlib.Path) -> dict:
    """周の scopes.json（無ければ空。読めない・形が違えば BoardGap）。鍵 OWNS は公開の名の持ち主 {<名>: <scope>}（照らしが書く）"""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise BoardGap(f"scope の登録 {path} が読めない: {e}") from None
    owns = doc.get(OWNS, {}) if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or not isinstance(owns, dict) or not all(isinstance(v, str) for v in owns.values()) \
            or not all(isinstance(v, dict) and isinstance(v.get("order"), int) for k, v in doc.items() if k != OWNS):
        raise BoardGap(f"scope の登録 {path} の形が違う（{{<scope>: {{block, order}}, {OWNS}: {{<名>: <scope>}}}}）")
    return doc


def _write_registry(box: pathlib.Path, doc: dict) -> None:
    tmp = box / (REGISTRY + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(box / REGISTRY)


def _rounds(board_dir: pathlib.Path) -> list[int]:
    """盤面の根の周の置き場 r<N> の番号（小さい順）"""
    return sorted(int(p.name[1:]) for p in pathlib.Path(board_dir).glob("r*") if p.is_dir() and p.name[1:].isdigit())


def _registered(board_dir: pathlib.Path, round_: int) -> list[str]:
    """周 round_ に登録した scope（登録の順）"""
    doc = _read_registry(pathlib.Path(board_dir) / f"r{round_}" / REGISTRY)
    return [k for k, _ in sorted(((k, v) for k, v in doc.items() if k != OWNS), key=lambda kv: kv[1]["order"])]


def _all_registered(board_dir: pathlib.Path) -> list[str]:
    """どれかの周に登録した scope（周の順、同じ周は登録の順。重ねない）"""
    return list(dict.fromkeys(s for n in _rounds(board_dir) for s in _registered(board_dir, n)))


def _root_entry(scope: str) -> bool:
    """scope の名が盤面の根に作るフォルダの形（ROOT_DIRS と、manifest の at: root の produces の頭の段）に当たるか"""
    heads = {p["name"].split("/")[0] for m in _loaded(str(PACK.resolve())).values() for p in m["produces"]
             if p.get("at") == "root" and "/" in p["name"]}
    return any(matches(scope, pat) for pat in ROOT_DIRS | heads)


def claim(board_dir: pathlib.Path, round_: int, scope: str, block: str) -> None:
    """盤面の周 round_ の scopes.json に scope とブロック block を登録する（錠 scopes.json.lock の下。待つ上限は持たない）。
    同じ scope・同じ block は何もしない（Archon の再開で同じ include が走り直す）。同じ scope を別の block が名乗れば BoardGap
    （両方の block の名）。scope の名が盤面の根の物とぶつかれば BoardGap: 根に作るフォルダの形（ROOT_DIRS と、manifest の
    at: root の produces のフォルダ）に当たるか、根に同じ名のフォルダでない物が在る。根に同じ名のフォルダが在るだけでは拒まない
    （盤面を開かない節——依頼の受け付けの intake など——が script_io.scope_dir に先に書いて作る）"""
    if scope == OWNS:
        raise BoardGap(f"scope の名 {OWNS!r} は登録の持ち主の鍵に使っている（include の名を替える）")
    d = pathlib.Path(board_dir)
    root_entry = _root_entry(scope)   # 錠の外で（manifest はプロセスごとに 1 度読む）
    box = d / f"r{round_}"
    box.mkdir(parents=True, exist_ok=True)
    with open(box / REGISTRY_LOCK, "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            doc = _read_registry(box / REGISTRY)
            mine = doc.get(scope)
            if mine is not None:
                if mine.get("block") != block:
                    raise BoardGap(f"scope {scope!r} を 2 つのブロックが名乗った（登録済み {mine.get('block')!r}・今 {block!r}）"
                                   f"——include の名が重なっている（{box / REGISTRY}）")
                return
            for n in _rounds(d):
                other = _read_registry(d / f"r{n}" / REGISTRY).get(scope)
                if other is not None and other.get("block") != block:
                    raise BoardGap(f"scope {scope!r} を 2 つのブロックが名乗った（周 {n} に {other.get('block')!r}・今 {block!r}）"
                                   "——include の名が重なっている")
            if root_entry or ((d / scope).exists() and not (d / scope).is_dir()):
                raise BoardGap(f"scope {scope!r} が盤面の根の物 {d / scope} とぶつかる（根の記録のフォルダか、フォルダでない物）")
            doc[scope] = {"block": block, "order": 1 + max((v["order"] for k, v in doc.items() if k != OWNS), default=0)}
            _write_registry(box, doc)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def all_rounds(board_dir: pathlib.Path, pattern: str) -> list[pathlib.Path]:
    """全部の周の線と公開の置き場 r<N>/<pattern> と、登録した scope の根の <scope>/r<N>/<pattern> のファイル（周の順、同じ周は
    線・公開の置き場が先で、scope は登録の順。pattern は glob の形）"""
    d = pathlib.Path(board_dir)
    rows = []
    for i, root in enumerate([d] + [d / s for s in _all_registered(d)]):
        for p in root.glob(f"r*/{pattern}"):
            tail = p.relative_to(root).parts[0][1:]   # 周の置き場 r<N> の番号（r で始まる scope の名などは数でない）
            if tail.isdigit() and p.is_file():
                rows.append((int(tail), i, str(p), p))
    return [p for *_, p in sorted(rows)]


def scope_roots(b) -> list[pathlib.Path]:
    """盤面の根と、今の周に登録した scope の根（線が先で、scope は登録の順。最後が一番新しく登録した include の物）"""
    d = pathlib.Path(b.dir)
    return [d] + [d / s for s in _registered(d, b.round)]


def each(b, name: str) -> list[pathlib.Path]:
    """今の周の線と公開の置き場 r<N>/<name> と、今の周に登録した scope の根の <scope>/r<N>/<name> のうち在る物（scope_roots の
    順。最後が一番新しく登録した include の物）。同じブロックの 2 つの include がそれぞれ書く物（per_include）を、ほかの
    include や線が読む口"""
    return [p for p in (root / f"r{b.round}" / name for root in scope_roots(b)) if p.is_file()]


# ---------------------------------------------------------------- 窓の照らし（宣言の外の書き込み）
def shared(path: str) -> bool:
    """盤面の根からのパス path（posix）が共有の記録（SHARED のどれかの形）に当たるか"""
    return any(matches(path, pat) for pat in SHARED)


def snapshot(board_dir: pathlib.Path) -> dict[str, list[int]]:
    """盤面の下の全部のファイルの相対パス（posix）→ [大きさ, mtime_ns]（リンクは辿らずにそのものを測る。無い盤面は空）"""
    d = str(pathlib.Path(board_dir))
    out = {}
    for root, _, files in os.walk(d):
        for f in files:
            full = os.path.join(root, f)
            try:
                st = os.lstat(full)
            except FileNotFoundError:   # 測る間に消えた（窓の間の変化として次の照らしが見る）
                continue
            out[pathlib.PurePath(os.path.relpath(full, d)).as_posix()] = [st.st_size, st.st_mtime_ns]
    return out


def _changed(before: dict, after: dict) -> list[str]:
    """2 つの snapshot の間で変わった・増えた・消えたパス（名の順）"""
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def _pick(rows: list, name: str) -> dict | None:
    """rows（produces の行）のうち name に当たる物。字のままの名が形より勝つ（blk-plan の reads-plan-block.json と reads-*.json）"""
    return next((r for r in rows if r["name"] == name), None) or next((r for r in rows if matches(name, r["name"])), None)


def _rows(block: str, name: str, pack, *, per_include: bool, at: str) -> tuple[str, dict] | None:
    """name に当たる (owner, produces の行)（per_include と置き場 at が合う物だけ）。block が空（起こされたブロックが分からない）
    なら公開の名から持ち主を引き、ブロックの名に頼らない（per_include の物は引かない）"""
    all_ = _loaded(str(pathlib.Path(pack).resolve()))
    owner = block or (None if per_include else owner_of(name, pack))
    if owner not in all_:
        return None
    row = _pick([p for p in all_[owner]["produces"]
                 if bool(p.get("per_include")) is per_include and p.get("at", "round") == at], name)
    return (owner, row) if row else None


def _declared(block: str, pack) -> str:
    """誤りの文に載せる宣言（ブロックの produces の名の並び）"""
    if not block:
        return "（起こされたブロックが分からない。公開の名の持ち主で照らした）"
    rows = _loaded(str(pathlib.Path(pack).resolve())).get(block, {}).get("produces", [])
    return ", ".join(p["name"] for p in rows) or "なし"


def _schema_errors(board_dir: pathlib.Path, rel: str, owner: str, row: dict, pack) -> list[str]:
    """format が json の produces のファイル rel が読めない・Schema に合わない誤り（json でない・消えた物は照らさない）"""
    p = pathlib.Path(board_dir) / rel
    if row["format"] != "json" or not p.is_file():
        return []
    schema_path = pathlib.Path(pack) / owner / row["schema"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return [f"JSON として読めない: {type(e).__name__}: {e}"]
    return [f"Schema {schema_path} に合わない: " + "; ".join(errs)
            for errs in [validate_schema(doc, json.loads(schema_path.read_text(encoding="utf-8")))] if errs]


def _own(board_dir: pathlib.Path, n: int, name: str, scope: str) -> str | None:
    """周 n の公開の名 name の持ち主を scope にする（錠 scopes.json.lock の下）。別の scope が持ち主ならその名を返し、書き換えない"""
    box = pathlib.Path(board_dir) / f"r{n}"
    box.mkdir(parents=True, exist_ok=True)
    with open(box / REGISTRY_LOCK, "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            doc = _read_registry(box / REGISTRY)
            owns = doc.setdefault(OWNS, {})
            if owns.get(name, scope) != scope:
                return owns[name]
            if owns.get(name) != scope:
                owns[name] = scope
                _write_registry(box, doc)
            return None
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def check_window(board_dir: pathlib.Path, window: dict, pack: pathlib.Path = PACK, *, opener: str = "") -> list[str]:
    """窓 window（{scope, block, round, files: snapshot}）を開いてからの盤面の変化を、窓の scope のブロックの宣言に照らした誤りの
    全部（最初の 1 つで止めない。無ければ []）。scope が空（線）の窓は照らさない（外れ D5）。変わった・増えた・消えたパスごとに:
    scope の根の下・共有の記録は可。周の置き場 r<N>/<名> はブロックの per_include でなく at が round の produces なら可で、
    r<N>/scopes.json の owns に持ち主の scope を記録し、別の scope が持ち主なら誤り（周ごとに書き手は 1 つ）。盤面の根の <名> は
    at が root の produces なら可（周を持たないので持ち主は記録しない）。ほかは誤り。あわせて、format が json の produces（scope の
    根の per_include の物も）が読めないか Schema に合わない、も誤り（required の欠けは誤りにしない: missing_required）。
    opener は今盤面を開いて窓を閉じる scope の窓の鍵（enter が渡す）で、その scope の根の変化は照らさない: 盤面を開く前に自分の
    scope の根に書く節（依頼の受け付けの intake・テストの走らせ（script_io.scope_dir））の物で、閉じる窓の物ではない。
    窓の scope と opener は窓の鍵（window_key）で、fan_out の子の鍵 <fan の節>--* はその fan の子の全部の scope の根に当たる"""
    scope, block, n = window.get("scope") or "", window.get("block") or "", window.get("round")
    if not scope:
        return []
    d = pathlib.Path(board_dir)
    now_files = snapshot(d)
    who = f"scope {scope}（{block or 'ブロック不明'}）"
    decl = _declared(block, pack)
    errs = []
    for rel in _changed(window.get("files") or {}, now_files):
        segs = rel.split("/")
        if opener and matches(segs[0], opener):
            continue
        if matches(segs[0], scope):
            inner = "/".join(segs[1:])
            at, name = ("round", "/".join(segs[2:])) if len(segs) > 2 and _ROUND_NAME.fullmatch(segs[1]) else ("root", inner)
            hit = _rows(block, name, pack, per_include=True, at=at) if block else None
            errs += [f"{rel}: {who} の {name} が {e}" for e in (_schema_errors(d, rel, *hit, pack) if hit else [])]
            continue
        if shared(rel):
            continue
        in_round = len(segs) > 1 and _ROUND_NAME.fullmatch(segs[0])
        name = "/".join(segs[1:]) if in_round else rel
        hit = _rows(block, name, pack, per_include=False, at="round" if in_round else "root")
        if hit is None:
            errs.append(f"{rel}: {who} が宣言の外に書いた。宣言: {decl}")
            continue
        if in_round:
            other = _own(d, int(segs[0][1:]), name, scope)
            if other is not None:
                errs.append(f"{rel}: {who} が宣言の外に書いた（この周の持ち主は scope {other}。周ごとに書き手は 1 つ）。宣言: {decl}")
                continue
        errs += [f"{rel}: {who} の {name} が {e}" for e in _schema_errors(d, rel, *hit, pack)]
    return errs


def missing_required(board_dir: pathlib.Path, window: dict, pack: pathlib.Path = PACK) -> list[str]:
    """窓の scope のブロックの required の produces のうち、窓の周の置き場に今無い物の盤面の根からの名（形のままの名も）。止めない:
    役が落ちた・諦めた部品の出力は無くなるので、止めると落ちた理由が BoardGap の陰に隠れ報告も書けない。呼び手（enter）が trace の
    行 REQUIRED_MISSING_OP と報告に載せる。scope が空の窓・ブロックが分からない窓は []"""
    scope, block, n = window.get("scope") or "", window.get("block") or "", window.get("round")
    if not (scope and block):
        return []
    now_files = snapshot(board_dir)
    out = []
    for p in _loaded(str(pathlib.Path(pack).resolve())).get(block, {}).get("produces", []):   # fan の窓はどれかの子に在れば足りる
        if not p.get("required"):
            continue
        place = (f"{scope}/" if p.get("per_include") else "") + (f"r{n}/" if p.get("at", "round") == "round" else "")
        if not any(matches(rel, place + p["name"]) for rel in now_files):
            out.append(place + p["name"])
    return out


def _consumed(block: str, pack, name: str) -> bool:
    """block の consumes か per_include でない produces が name に当たるか（block が空なら公開の名の全部）"""
    if not block:
        return owner_of(name, pack) is not None
    m = _loaded(str(pathlib.Path(pack).resolve())).get(block, {"consumes": [], "produces": []})
    pats = [c["name"] for c in m["consumes"]] + [p["name"] for p in m["produces"] if not p.get("per_include")]
    return any(matches(name, pat) for pat in pats)


def reads_outside(board_dir: pathlib.Path, window: dict, pack: pathlib.Path = PACK) -> list[str]:
    """窓の間に scope の根の下で書かれた読んだ証拠（reads-*.json の rows）のうち、盤面の下のパスで、scope の根・consumes の名・
    自分の produces・共有の記録（out/ を含む）のどれでもない物の盤面の根からのパス（名の順・重ねない）。落とさない（外れ D4。
    呼び手が trace の行 scope_read_outside と報告に載せる）。scope が空の窓は []"""
    scope, block = window.get("scope") or "", window.get("block") or ""
    if not scope:
        return []
    d = pathlib.Path(board_dir)
    real = pathlib.Path(os.path.realpath(d))
    changed = _changed(window.get("files") or {}, snapshot(d))
    out = set()
    for rel in changed:
        segs = rel.split("/")
        if not (len(segs) == 3 and matches(segs[0], scope) and _ROUND_NAME.fullmatch(segs[1]) and matches(segs[2], "reads-*.json")):
            continue
        try:
            doc = json.loads((d / rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue   # 消えた・読めない読んだ証拠は照らしの誤り（Schema）の方が見る
        rows = doc.get("rows") if isinstance(doc, dict) else None
        for row in rows if isinstance(rows, list) else []:
            path = row.get("path") if isinstance(row, dict) else None
            if not isinstance(path, str) or not os.path.isabs(path):
                continue
            full = pathlib.Path(os.path.realpath(path))
            if not full.is_relative_to(real):
                continue
            got = full.relative_to(real).as_posix()
            gsegs = got.split("/")
            name = "/".join(gsegs[1:]) if len(gsegs) > 1 and _ROUND_NAME.fullmatch(gsegs[0]) else got
            if matches(gsegs[0], scope) or shared(got) or _consumed(block, pack, name):
                continue
            out.add(got)
    return sorted(out)


def _read_window(d: pathlib.Path) -> dict | None:
    """盤面の根の今の窓（無ければ None。読めない・形が違えば BoardGap）"""
    p = d / WINDOW
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise BoardGap(f"scope の窓 {p} が読めない: {e}") from None
    if not (isinstance(doc, dict) and isinstance(doc.get("scope"), str) and isinstance(doc.get("block"), str)
            and isinstance(doc.get("round"), int) and isinstance(doc.get("files"), dict)):
        raise BoardGap(f"scope の窓 {p} の形が違う（{{scope, block, round, files}}）")
    return doc


def window_key(scope: str) -> str:
    """窓の鍵: fan_out の子の scope（flow_adapter.fan_node が名を返す物）は同じ fan の子の全部に当たる形 <fan の節>--*、ほかは
    scope のまま（ふつうの scope の名は glob の字を持たないので、matches は字のままの一致）"""
    fan = flow_adapter.fan_node(scope)
    return f"{fan}{flow_adapter.FAN_SEP}*" if fan else scope


def enter(board_dir: pathlib.Path, round_: int, scope: str, block: str) -> list[str]:
    """盤面を開く口（entry.open_board）が流れの道具の節として scope（線の最上段は空）で開くたびに呼ぶ。錠 scope-window.json.lock
    の下で、盤面の根の今の窓 scope-window.json を読み、窓の scope が今の scope と違えば（窓が閉じる）前の窓を照らす:
    check_window の誤りを返し（呼び手が盤面を止める）、必須の出力の欠け（missing_required）を trace の行 REQUIRED_MISSING_OP
    {scope, names} に、宣言の外の読み（reads_outside）を READ_OUTSIDE_OP {scope, paths} に積み、誤りが在っても今の scope の窓を
    snapshot で開き直す（後の開きが同じ誤りで落ち続けない。止めた事実は盤面に残る）。同じ scope なら何もせず []（Archon の再開で
    同じ include が走り直しても 1 回目からの書き込みを照らし続ける。照らすのは窓ごとに 1 度——外れ D3）。
    比べるのは scope でなく窓の鍵（window_key）: 同じ fan の子が同時に開いても、最初の子が開いた窓を後の子は閉じない（モジュールの
    docstring の「fan_out の子」）"""
    d = pathlib.Path(board_dir)
    mine = window_key(scope)
    with open(d / WINDOW_LOCK, "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            window = _read_window(d)
            if window is not None and window["scope"] == mine:
                return []
            errs = []
            if window is not None:
                errs = check_window(d, window, opener=mine)
                rows = [(REQUIRED_MISSING_OP, "names", missing_required(d, window)),
                        (READ_OUTSIDE_OP, "paths", reads_outside(d, window))]
                with open(d / "trace.jsonl", "a", encoding="utf-8") as f:
                    for op, key, got in rows:
                        if got:
                            f.write(json.dumps({"t": now(), "op": op, "scope": window["scope"], key: got},
                                               ensure_ascii=False) + "\n")
            doc = {"scope": mine, "block": block, "round": round_, "files": snapshot(d)}
            tmp = d / (WINDOW + ".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(d / WINDOW)
            return errs
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
