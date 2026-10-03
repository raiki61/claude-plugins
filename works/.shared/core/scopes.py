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

名の形は段ごとに当てる（* が / をまたぐ fnmatch のままだと、rejects-*.json が rejects-a/b.json のような scope の下の私物まで
公開の名に数える）。形の字は manifest を読む時に照らす: 空の段・"."・".."・頭の "/" を持たず、** は末尾の段そのものだけ。
"""
from __future__ import annotations

import copy
import fcntl
import functools
import json
import pathlib
import sys

_CORE = pathlib.Path(__file__).resolve().parent
_GL = _CORE / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

from board import BoardGap, name_matches  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

PACK = _CORE.parents[1]                       # works/（.shared/core の 2 つ上）
MANIFEST = "manifest.json"                    # owner のフォルダの宣言のファイル
SCHEMA_PATH = _CORE / "manifest.schema.json"  # manifest の形の正本
BLOCK_GLOB = "blk-*"                          # ブロックのフォルダ
LINE_MARK = "nodes.json"                      # 線のフォルダの印（tests/test_layers の L7 と同じ見分け）
ANY_BELOW = "**"                              # 名の形の末尾の段だけに置ける「下の全部」
REGISTRY = "scopes.json"                      # 周の置き場の scope の登録 {<scope>: {"block": <名>, "order": <登録の順>}}
REGISTRY_LOCK = "scopes.json.lock"            # 登録の読み書きの錠（fcntl.flock。待つ上限は持たない）
SCRIPTS_DIR = "scripts"                       # ブロックのスクリプトの置き場（<pack>/<名>/scripts/<x>.py）
# core が書き、どの scope の窓でも同じ周の置き場 r<N>/ に置く共有の記録（測り M2 の class shared のうち where が work の物）
SHARED_ROUND = frozenset({"conflicts.json", "libdocs.json", "libdocs/**"})
# 盤面の根に core・engine・rules・部品が作るフォルダの名の形（測り M2 の class shared の where が root のフォルダと、修正の
# ブロックの試験の輪の置き場 tdd-<k>）。scope の名がこれに当たると、私物が根の記録に混ざるので登録しない
ROOT_DIRS = frozenset({"out", "runs", "rounds", "prompts", "roles", "items", "policy", "lanes", "tdd-*"})


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
    """周の scopes.json（無ければ空。読めない・形が違えば BoardGap）"""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise BoardGap(f"scope の登録 {path} が読めない: {e}") from None
    if not isinstance(doc, dict) or not all(isinstance(v, dict) and isinstance(v.get("order"), int) for v in doc.values()):
        raise BoardGap(f"scope の登録 {path} の形が違う（{{<scope>: {{block, order}}}}）")
    return doc


def _rounds(board_dir: pathlib.Path) -> list[int]:
    """盤面の根の周の置き場 r<N> の番号（小さい順）"""
    return sorted(int(p.name[1:]) for p in pathlib.Path(board_dir).glob("r*") if p.is_dir() and p.name[1:].isdigit())


def _registered(board_dir: pathlib.Path, round_: int) -> list[str]:
    """周 round_ に登録した scope（登録の順）"""
    doc = _read_registry(pathlib.Path(board_dir) / f"r{round_}" / REGISTRY)
    return [k for k, _ in sorted(doc.items(), key=lambda kv: kv[1]["order"])]


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
            doc[scope] = {"block": block, "order": 1 + max((v["order"] for v in doc.values()), default=0)}
            tmp = box / (REGISTRY + ".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            tmp.replace(box / REGISTRY)
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
