"""固定材料（計画 220 Task 5）: h-fix の時の盤面を写し、次の run が同じ所（判定・承認済みの修正案が済み、修正を待つ盤面）から
始める。腕（fix_shape）ごとに同じ依頼を同じ起点から回して比べるのに使う。層 L3。entry・board を import しない（entry が読む）。

語:
- 固定材料: $ARTIFACTS_DIR/DIR/ のフォルダ。中身は次の 3 つ。
  - COPY（board/）: 盤面を丸ごと写した物。
  - OUTSIDE（outside/）: 盤面の外で $ARTIFACTS_DIR の下に在るファイル（DIR 自身を除く）のうち、絶対パスが盤面の字（UTF-8 で
    読める盤面のファイルの中身）に現れる物だけの写し（例: 構造のブロックの設計の行のファイル）。元の run の置き場が消えても
    読めるように運ぶ。盤面の字が指さない物（run ごとの置き場 run-place の uv の cache など）は運ばない。フォルダは、その
    絶対パスに / を足した字が盤面の字に現れる時だけ降りる（指されないフォルダの下は見もしない）。
  - MANIFEST（fixture.json）: 控え。{source_run, head, tree, board_root, repo_root, pack_root, request_sha256, test_cmd,
    commits: {commit: 木}, files: {DIR からの相対パス: sha256}}。時刻を書かない。
    - head・tree は写した時の対象の `git rev-parse HEAD`・`HEAD^{tree}`。
    - board_root・repo_root・pack_root は写した盤面・対象・works の置き場。$ARTIFACTS_DIR は board_root の親。
    - request_sha256 は盤面の依頼の文（state.inputs.request）の sha256。test_cmd は start の控えの値。
    - commits は盤面の字に現れる commit（HEAD を除く）とその木。
- 取り込みの決まりは 1 つ: 盤面の字が指す物のうち取り込み先に無い物は、写しから運んで名を置き換える。
  - 置き場のパス: 盤面・$ARTIFACTS_DIR・対象・works の置き場の字を新しい置き場にする。OUTSIDE の写しは取り込んだ盤面の
    BOARD_OUTSIDE の下へ写し、元の $ARTIFACTS_DIR の下のパスの字をそこへ向ける。
  - commit: 対象に無い commit は同じ木で作り直し（親は今の HEAD）、名を置き換える。木も無ければ拒む。HEAD は今の HEAD にする。
- 控えの照らしは手の誤り（写しの書き換え・欠け）を防ぐ物。写しと控えの両方を揃えて書き換えた物は見分けない。

口:
- capture(board_dir, repo, *, run_id, pack_root): 固定材料を作って控えを返す。控えが既に在れば何も書かずにそれを返す。
  固定材料から始めた盤面（adopted が在る）は写さずに None
- adopt(board_dir, src, repo, *, run_id, pack_root, request_text, inputs): 固定材料 src を board_dir へ取り込み、start の控え
  （fixshape.START_REL）の doc を返す。合わなければ FixtureRefused（何が違うかを名指す 1 行）。拒む時は盤面を書かない
- adopted(board_dir): 固定材料から始めた盤面なら start の控えの KEY の欄 {source_run, manifest_sha256, at}、でなければ None
  （固定材料の印の読み口はこれ 1 つ）
- since(board_dir, created): 包みの起動の記録を数え始める時刻（取り込んだ盤面は取り込んだ時刻、ほかは created）
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess

import fixshape

DIR = "fix-fixture"             # $ARTIFACTS_DIR の下（盤面の隣）
MANIFEST = "fixture.json"       # DIR の下の控え
COPY = "board"                  # DIR の下の盤面の写し
OUTSIDE = "outside"             # DIR の下の、盤面の外のファイルの写し
BOARD_OUTSIDE = "fixture-outside"   # 取り込んだ盤面の下の、OUTSIDE の写しの置き場
TRACE_OP = "fixture_adopted"    # 取り込んだ盤面の trace の行（entry.start が書く）
KEY = fixshape.FIXTURE_KEY       # start の控えの鍵 {source_run, manifest_sha256, at}
# 取り込みで今の値にする入力の欄（ほかの入力の欄は start の控えと今の入力が同じでなければ拒む）。features_off・features_on
# （切る機能・入れる機能）は腕と同じく同じ所から替えて比べる欄（判定・修正案の側の機能は写しの物のままで、修正の段の機能だけが効く）
CURRENT = ("fix_shape", "run_id", "request_file", "fix_fixture", "features_off", "features_on")
_STR_KEYS = ("source_run", "head", "tree", "board_root", "repo_root", "pack_root", "request_sha256", "test_cmd")
_MAP_KEYS = ("commits", "files")


class FixtureRefused(Exception):
    """固定材料を取り込まない。文は何が違うかを名指す 1 行"""

    def __init__(self, msg):
        super().__init__(" ".join(str(msg).split()))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files(root: pathlib.Path) -> dict:
    """root の下の全部のファイル（MANIFEST を除く）の {相対パス（/ 区切り）: sha256}"""
    return {p.relative_to(root).as_posix(): _sha(p.read_bytes()) for p in sorted(root.rglob("*"))
            if p.is_file() and p.relative_to(root).as_posix() != MANIFEST}


def _run(repo, *args, stdin: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", input=stdin,
                          env={**os.environ, **env} if env else None)


def _git(repo, *args, stdin: str | None = None, env: dict | None = None) -> str:
    """対象で git を呼ぶ。引けなければ OSError（写す側は run を止めない・取り込む側は拒みに替える）"""
    got = _run(repo, *args, stdin=stdin, env=env)
    if got.returncode != 0:
        raise OSError(f"git {' '.join(args)} が引けない: {got.stderr.strip() or got.returncode}")
    return got.stdout.strip()


def _lacking(repo, names: list) -> set:
    """names（`<名>^{commit}` などの git の名）のうち対象に無い物（git cat-file --batch-check を 1 回）"""
    if not names:
        return set()
    rows = _git(repo, "cat-file", "--batch-check", stdin="\n".join(names) + "\n").splitlines()
    return {n for n, r in zip(names, rows) if r.endswith(" missing")}


HEX40 = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")   # 盤面の字の中の commit の名の候補
# 作り直す commit の作者（写しの engine の SNAPSHOT_FALLBACK_IDENT と同じ考え。利用者の設定に左右されない）
SNAPSHOT_IDENT = {"GIT_AUTHOR_NAME": "works-fixture", "GIT_AUTHOR_EMAIL": "works-fixture@localhost",
                  "GIT_COMMITTER_NAME": "works-fixture", "GIT_COMMITTER_EMAIL": "works-fixture@localhost"}


def _texts(root: pathlib.Path):
    """root の下の UTF-8 で読めるファイルの (パス, 文)"""
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            yield p, p.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue


def _commits(board: pathlib.Path, repo, head: str) -> dict:
    """盤面の字に現れる commit（HEAD を除く）の {commit: 木}"""
    names = [f"{n}^{{commit}}" for n in sorted({m for _, text in _texts(board) for m in HEX40.findall(text)} - {head})]
    lack = _lacking(repo, names)
    return {n[:40]: _git(repo, "rev-parse", f"{n[:40]}^{{tree}}") for n in names if n not in lack}


def _write_json(path: pathlib.Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def adopted(board_dir) -> dict | None:
    """固定材料から始めた盤面なら start の控えの KEY の欄、でなければ None（控えが無い・読めない・鍵が無いも None）。
    読むのは fixshape.recorded（start の控えの記録の読み口は 1 つ）"""
    try:
        return fixshape.recorded(board_dir)["fixture"]
    except ValueError:
        return None


def since(board_dir, created):
    """包みの起動の記録を数え始める時刻: 取り込んだ盤面は取り込んだ時刻（盤面の state.created は元の run の時刻）、ほかは created"""
    return (adopted(board_dir) or {}).get("at") or created


def _named(art: pathlib.Path, board: pathlib.Path, dest: pathlib.Path) -> list:
    """art の下で board と dest の外のファイルのうち、絶対パスが盤面の字に現れる物（パスの順）。フォルダは絶対パスに / を足した
    字が盤面の字に現れる時だけ降りる（モジュールの頭の OUTSIDE）"""
    text = "\n".join(t for _, t in _texts(board))
    out = []
    for top, dirs, files in os.walk(art):
        here = pathlib.Path(top)
        dirs[:] = sorted(d for d in dirs if (here / d) not in (board, dest) and f"{here / d}/" in text)
        out += [here / f for f in files if str(here / f) in text and (here / f).is_file()]
    return sorted(out)


def capture(board_dir, repo, *, run_id: str, pack_root) -> dict | None:
    """盤面を <board_dir の親>/DIR/COPY へ、盤面の外の $ARTIFACTS_DIR の下のファイル（DIR を除く）のうち盤面の字が指す物を
    DIR/OUTSIDE へ写し（_named）、MANIFEST を書いて返す。MANIFEST が既に在れば書き直さずに返す。固定材料から始めた盤面は
    写さずに None。写しの途中で落ちた残り（MANIFEST の無い DIR）は消して写し直す。控えは最後に置く（控えが在れば写しは揃っている）"""
    board = pathlib.Path(board_dir).resolve()
    if adopted(board) is not None:
        return None
    art = board.parent
    dest = art / DIR
    man_path = dest / MANIFEST
    if man_path.is_file():
        return json.loads(man_path.read_text(encoding="utf-8"))
    state = json.loads((board / "state.json").read_text(encoding="utf-8"))
    start = json.loads((board / fixshape.START_REL).read_text(encoding="utf-8"))
    request = str((state.get("inputs") or {}).get("request") or "")
    head, tree = _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "HEAD^{tree}")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(board, dest / COPY)
    for p in _named(art, board, dest):
        out = dest / OUTSIDE / p.relative_to(art)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
    man = {"source_run": run_id, "head": head, "tree": tree, "board_root": str(board),
           "repo_root": str(pathlib.Path(repo).resolve()), "pack_root": str(pack_root),
           "request_sha256": _sha(request.encode("utf-8")), "test_cmd": start.get("test_cmd", ""),
           "commits": _commits(dest / COPY, repo, head), "files": _files(dest)}
    _write_json(man_path, man)
    return man


def _manifest(src: pathlib.Path) -> tuple:
    """(控え, 控えのバイトの sha256)。無い・読めない・欄の型が違えば FixtureRefused"""
    path = src / MANIFEST
    try:
        raw = path.read_bytes()
        man = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as e:
        raise FixtureRefused(f"固定材料の控え {path} が無いか読めない（{type(e).__name__}: {e}）") from None
    ok = isinstance(man, dict) and all(isinstance(man.get(k), str) for k in _STR_KEYS) and all(
        isinstance(man.get(k), dict) and all(isinstance(a, str) and isinstance(b, str) for a, b in man[k].items())
        for k in _MAP_KEYS)
    if not ok:
        raise FixtureRefused(f"固定材料の控え {path} の欄の型が違う（{', '.join(_STR_KEYS)} は文字列、"
                             f"{', '.join(_MAP_KEYS)} は文字列から文字列への辞書）")
    return man, _sha(raw)


def _check_copy(src: pathlib.Path, man: dict) -> None:
    """固定材料のファイルが控えの sha256 と同じか。違う・足りない・多いファイルを名指して FixtureRefused"""
    got = _files(src)
    changed = sorted(p for p in got.keys() & man["files"].keys() if got[p] != man["files"][p])
    missing = sorted(man["files"].keys() - got.keys())
    extra = sorted(got.keys() - man["files"].keys())
    parts = [f"{what}: {', '.join(ps)}" for what, ps in (("書き換わった", changed), ("足りない", missing), ("多い", extra)) if ps]
    if parts:
        raise FixtureRefused(f"固定材料 {src} が控えと違う（{'・'.join(parts)}）——写した後に書き換えた写しは取り込まない")
    if f"{COPY}/{fixshape.START_REL}" not in man["files"]:
        raise FixtureRefused(f"固定材料 {src} に start の控え {COPY}/{fixshape.START_REL} が無い")


def _check_repo(repo, man: dict) -> tuple:
    """対象の木が控えの木と同じで、作業ツリーに変更が無く、作り直せない commit が無いか。通れば (今の HEAD, 作り直す commit)"""
    try:
        tree, head = _git(repo, "rev-parse", "HEAD^{tree}"), _git(repo, "rev-parse", "HEAD")
        dirty = _git(repo, "status", "--porcelain", "--untracked-files=normal")
        lack = _lacking(repo, [f"{c}^{{commit}}" for c in man["commits"]] + [f"{t}^{{tree}}" for t in man["commits"].values()])
    except OSError as e:
        raise FixtureRefused(f"対象 {repo} の git を読めない: {e}") from None
    if tree != man["tree"]:
        raise FixtureRefused(f"対象の木（HEAD^{{tree}} {tree[:12]}）が固定材料の tree {man['tree'][:12]} と違う"
                             "——works の版か対象の中身が写した時と違う")
    if dirty:
        first = dirty.splitlines()[0].strip()
        raise FixtureRefused(f"対象の作業ツリーに commit していない変更が在る（{first} ほか）——写した時と同じ木で始めない")
    remake = {c: t for c, t in man["commits"].items() if f"{c}^{{commit}}" in lack}
    stuck = sorted(c for c, t in remake.items() if f"{t}^{{tree}}" in lack)
    if stuck:
        raise FixtureRefused(f"盤面が指す commit {', '.join(c[:12] for c in stuck)} もその木も対象に無い——作り直せない")
    return head, remake


def _remade(repo, remake: dict, head: str) -> dict:
    """対象に無い commit を同じ木・親を今の HEAD にして作り直す。{古い commit: 新しい commit}"""
    out = {}
    for rev, rev_tree in remake.items():
        try:
            out[rev] = _git(repo, "commit-tree", rev_tree, "-p", head, "-m", f"works fix-fixture: {rev}", env=SNAPSHOT_IDENT)
        except OSError as e:
            raise FixtureRefused(f"盤面が指す commit {rev[:12]} を対象に作り直せない: {e}") from None
    return out


def _swapper(swap: dict):
    """文の中の swap の字（古い値）を新しい値に 1 度で置き換える関数（長い字から当てる。置き換えた字をもう 1 度置き換えない）"""
    olds = sorted((o for o, n in swap.items() if o and o != n), key=len, reverse=True)
    if not olds:
        return lambda text: text
    pat = re.compile("|".join(re.escape(o) for o in olds))
    return lambda text: pat.sub(lambda m: swap[m.group(0)], text)


def _rewrite(root: pathlib.Path, swap: dict) -> None:
    """root の下の UTF-8 で読めるファイルの中の字を _swapper で置き換える。読めないファイルはそのまま"""
    fn = _swapper(swap)
    for p, text in list(_texts(root)):
        new = fn(text)
        if new != text:
            p.write_text(new, encoding="utf-8")


def _differs(doc: dict, inputs: dict) -> list:
    """start の控え doc と今の入力 inputs の違う欄（CURRENT を除く）"""
    return sorted(k for k, v in inputs.items() if k not in CURRENT and doc.get(k) != v)


def adopt(board_dir, src, repo, *, run_id: str, pack_root, request_text: str, inputs: dict) -> dict:
    """固定材料 src（DIR のフォルダ）を board_dir へ取り込み、start の控えの doc を返す。inputs は今の run の入力の欄
    （start の控えに残す形。entry.adopt_inputs）。拒む物（FixtureRefused。盤面を書かない）:
    控えが無い・読めない・欄の型が違う／ファイルの sha256 が違う・足りない・多い／board_dir が空でない／今の HEAD^{tree} が
    控えの tree と違う／作業ツリーに変更が在る／盤面が指す commit もその木も対象に無い／request_text の sha256 が違う／
    start の控えの入力の欄が inputs と違う（CURRENT の欄を除く。名指す）。通れば:
    1. 対象に無い commit を作り直し、写しを board_dir へ、OUTSIDE を board_dir/BOARD_OUTSIDE へ写す
    2. UTF-8 で読めるファイルの中の置き場のパス・HEAD・作り直した commit の字を新しい値に置き換える
    3. 写しに振り分けの控え（fixshape.CHOICE_REL）が在れば消す（腕の形は今の入力で決める）
    4. start の控えの CURRENT の欄を今の値にし、鍵 KEY {source_run, manifest_sha256, at（取り込んだ時刻）} を足す"""
    src = pathlib.Path(src)
    board = pathlib.Path(board_dir).resolve()
    man, man_sha = _manifest(src)
    _check_copy(src, man)
    if board.exists() and (not board.is_dir() or any(board.iterdir())):
        raise FixtureRefused(f"取り込む先の盤面の置き場 {board} が空でない——固定材料は空の置き場にだけ取り込む")
    head, remake = _check_repo(repo, man)
    if _sha(request_text.encode("utf-8")) != man["request_sha256"]:
        raise FixtureRefused("依頼の文の sha256 が固定材料と違う——同じ依頼の run だけが固定材料から始める")
    old_board = pathlib.Path(man["board_root"])
    old_art, outside = old_board.parent, src / OUTSIDE
    rels = [p.relative_to(outside).as_posix() for p in sorted(outside.rglob("*")) if p.is_file()] if outside.is_dir() else []
    swap = {man["board_root"]: str(board), str(old_art): str(board.parent),
            **{str(old_art / r): str(board / BOARD_OUTSIDE / r) for r in rels},
            man["repo_root"]: str(pathlib.Path(repo).resolve()), man["pack_root"]: str(pack_root), man["head"]: head}
    doc = json.loads(_swapper(swap)((src / COPY / fixshape.START_REL).read_text(encoding="utf-8")))
    bad = _differs(doc, inputs)
    if bad:
        raise FixtureRefused("start の控えの入力が今の入力と違う: " + "・".join(f"{k}={doc.get(k)!r}→{inputs[k]!r}" for k in bad)
                             + "（同じ入力の run だけが固定材料から始める。今の値にするのは " + "・".join(CURRENT) + " だけ）")
    swap.update(_remade(repo, remake, head))
    board.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src / COPY, board, dirs_exist_ok=True)
    if rels:
        shutil.copytree(outside, board / BOARD_OUTSIDE)
    _rewrite(board, swap)
    (board / fixshape.CHOICE_REL).unlink(missing_ok=True)
    start_path = board / fixshape.START_REL
    doc = json.loads(start_path.read_text(encoding="utf-8"))
    doc.update({k: inputs[k] for k in CURRENT if k in inputs})
    doc.update({"run_id": run_id, KEY: {"source_run": man["source_run"], "manifest_sha256": man_sha,
                                        "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}})
    _write_json(start_path, doc)
    return doc
