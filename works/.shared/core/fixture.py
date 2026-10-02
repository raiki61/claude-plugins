"""固定材料（計画 220 Task 5）: h-fix の時の盤面を写し、次の run が同じ所（判定・承認済みの修正案が済み、修正を待つ盤面）から
始める。腕（fix_shape）ごとに同じ依頼を同じ起点から回して比べるのに使う。層 L3。entry・board を import しない（entry が読む）。

語:
- 写し: $ARTIFACTS_DIR/DIR/board/（盤面の置き場の隣）。盤面を丸ごと写した物。
- 控え: $ARTIFACTS_DIR/DIR/MANIFEST。{source_run, head, tree, board_root, repo_root, pack_root, request_sha256, test_cmd,
  files: {写しの中の相対パス: sha256}}。時刻を書かない。
  - head・tree は写した時の対象の `git rev-parse HEAD`・`HEAD^{tree}`。
  - board_root・repo_root・pack_root は写した盤面・対象・works の置き場（取り込みで新しい値に置き換える字）。
  - request_sha256 は盤面の依頼の文（state.inputs.request）の sha256。test_cmd は start の控えの値。
  - snapshots は {版: 木}。盤面の字に現れる commit のうち HEAD でも HEAD の祖先でもない物（写しの engine が作業ツリーを固めた
    版。state.inputs.review_rev など）と、その木。取り込む対象にはその版が無いので、取り込みで同じ木の版を作り直して字を置き換える。

口:
- capture(board_dir, repo, *, run_id, pack_root): 写しと控えを作って控えを返す。控えが既に在れば何も書かずにそれを返す
- adopt(board_dir, src, repo, *, run_id, pack_root, request_text, test_cmd, fix_shape): 写しを board_dir へ取り込み、
  start の控え（fixshape.START_REL）の doc を返す。合わなければ FixtureRefused（何が違うかを名指す 1 行）。拒む時は何も書かない
"""
from __future__ import annotations

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
COPY = "board"                  # DIR の下の写し
TRACE_OP = "fixture_adopted"    # 取り込んだ盤面の trace の行（entry.start が書く）
KEY = "fixture"                 # start の控えの鍵 {source_run, manifest_sha256}
ROOT_KEYS = ("board_root", "repo_root", "pack_root", "head")   # 取り込みで置き換える字


class FixtureRefused(Exception):
    """固定材料を取り込まない。文は何が違うかを名指す 1 行"""

    def __init__(self, msg):
        super().__init__(" ".join(str(msg).split()))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files(root: pathlib.Path) -> dict:
    """root の下の全部のファイルの {相対パス（/ 区切り）: sha256}"""
    return {p.relative_to(root).as_posix(): _sha(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}


def _run(repo, *args, stdin: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", input=stdin,
                          env={**os.environ, **env} if env else None)


def _git(repo, *args, stdin: str | None = None, env: dict | None = None) -> str:
    """対象で git を呼ぶ。引けなければ OSError（写す側は run を止めない・取り込む側は拒みに替える）"""
    got = _run(repo, *args, stdin=stdin, env=env)
    if got.returncode != 0:
        raise OSError(f"git {' '.join(args)} が引けない: {got.stderr.strip() or got.returncode}")
    return got.stdout.strip()


HEX40 = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])")   # 盤面の字の中の commit の名の候補
# 作り直す版の作者（写しの engine の SNAPSHOT_FALLBACK_IDENT と同じ考え。利用者の設定に左右されない）
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


def _snapshots(board: pathlib.Path, repo, head: str) -> dict:
    """盤面の字に現れる commit のうち HEAD でも HEAD の祖先でもない物の {版: 木}"""
    names = sorted({m for _, text in _texts(board) for m in HEX40.findall(text)} - {head})
    if not names:
        return {}
    rows = _git(repo, "cat-file", "--batch-check", stdin="\n".join(names) + "\n").splitlines()
    commits = [r.split()[0] for r in rows if len(r.split()) == 3 and r.split()[1] == "commit"]
    return {c: _git(repo, "rev-parse", f"{c}^{{tree}}") for c in commits
            if _run(repo, "merge-base", "--is-ancestor", c, "HEAD").returncode != 0}


def _write_json(path: pathlib.Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def capture(board_dir, repo, *, run_id: str, pack_root) -> dict:
    """盤面を <board_dir の親>/DIR/COPY へ丸ごと写し、横に MANIFEST を書いて返す。MANIFEST が既に在れば書き直さずに返す。
    写しの途中で落ちた残り（MANIFEST の無い写し）は消して写し直す。控えは最後に置く（控えが在れば写しは揃っている）"""
    board = pathlib.Path(board_dir).resolve()
    dest = board.parent / DIR
    man_path = dest / MANIFEST
    if man_path.is_file():
        return json.loads(man_path.read_text(encoding="utf-8"))
    state = json.loads((board / "state.json").read_text(encoding="utf-8"))
    start = json.loads((board / fixshape.START_REL).read_text(encoding="utf-8"))
    request = str((state.get("inputs") or {}).get("request") or "")
    head, tree = _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "HEAD^{tree}")
    copy = dest / COPY
    if copy.exists():
        shutil.rmtree(copy)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(board, copy)
    man = {"source_run": run_id, "head": head, "tree": tree, "board_root": str(board),
           "repo_root": str(pathlib.Path(repo).resolve()), "pack_root": str(pack_root),
           "request_sha256": _sha(request.encode("utf-8")), "test_cmd": start.get("test_cmd", ""),
           "snapshots": _snapshots(copy, repo, head), "files": _files(copy)}
    _write_json(man_path, man)
    return man


def _manifest(src: pathlib.Path) -> tuple:
    """(控え, 控えのバイトの sha256)。無い・読めない・形が違えば FixtureRefused"""
    path = src / MANIFEST
    try:
        raw = path.read_bytes()
        man = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as e:
        raise FixtureRefused(f"固定材料の控え {path} が無いか読めない（{type(e).__name__}: {e}）") from None
    want = ("source_run", "head", "tree", *ROOT_KEYS[:3], "request_sha256", "test_cmd", "snapshots", "files")
    if (not isinstance(man, dict) or any(k not in man for k in want) or not isinstance(man["files"], dict)
            or not isinstance(man["snapshots"], dict)):
        raise FixtureRefused(f"固定材料の控え {path} の形が違う（欄 {', '.join(want)} が要る）")
    return man, _sha(raw)


def _check_copy(copy: pathlib.Path, man: dict) -> None:
    """写しのファイルが控えの sha256 と同じか。違う・足りない・多いファイルを名指して FixtureRefused"""
    got = _files(copy) if copy.is_dir() else {}
    changed = sorted(p for p in got.keys() & man["files"].keys() if got[p] != man["files"][p])
    missing = sorted(man["files"].keys() - got.keys())
    extra = sorted(got.keys() - man["files"].keys())
    parts = [f"{what}: {', '.join(ps)}" for what, ps in (("書き換わった", changed), ("足りない", missing), ("多い", extra)) if ps]
    if parts:
        raise FixtureRefused(f"固定材料の写し {copy} が控えと違う（{'・'.join(parts)}）——写した後に書き換えた写しは取り込まない")
    if fixshape.START_REL not in man["files"]:
        raise FixtureRefused(f"固定材料の写し {copy} に start の控え {fixshape.START_REL} が無い")


def _check_repo(repo, man: dict) -> str:
    """対象の木が控えの木と同じで、作業ツリーに変更が無いか。通れば今の HEAD を返す"""
    try:
        tree, head = _git(repo, "rev-parse", "HEAD^{tree}"), _git(repo, "rev-parse", "HEAD")
        dirty = _git(repo, "status", "--porcelain", "--untracked-files=normal")
    except OSError as e:
        raise FixtureRefused(f"対象 {repo} の git を読めない: {e}") from None
    if tree != man["tree"]:
        raise FixtureRefused(f"対象の木（HEAD^{{tree}} {tree[:12]}）が固定材料の tree {man['tree'][:12]} と違う"
                             "——works の版か対象の中身が写した時と違う")
    if dirty:
        first = dirty.splitlines()[0].strip()
        raise FixtureRefused(f"対象の作業ツリーに commit していない変更が在る（{first} ほか）——写した時と同じ木で始めない")
    for rev, rev_tree in man["snapshots"].items():
        if _run(repo, "cat-file", "-e", f"{rev}^{{commit}}").returncode != 0 and \
                _run(repo, "cat-file", "-e", f"{rev_tree}^{{tree}}").returncode != 0:
            raise FixtureRefused(f"写した時に固めた版 {rev[:12]} の木 {rev_tree[:12]} が対象に無い——作り直せない")
    return head


def _remade(repo, man: dict, head: str) -> dict:
    """写した時に固めた版（snapshots）のうち対象に無い物を、同じ木・親を今の HEAD にして作り直す。{古い版: 新しい版}"""
    out = {}
    for rev, rev_tree in man["snapshots"].items():
        if _run(repo, "cat-file", "-e", f"{rev}^{{commit}}").returncode == 0:
            continue
        try:
            out[rev] = _git(repo, "commit-tree", rev_tree, "-p", head, "-m", f"works fix-fixture: {rev}", env=SNAPSHOT_IDENT)
        except OSError as e:
            raise FixtureRefused(f"写した時に固めた版 {rev[:12]} を対象に作り直せない: {e}") from None
    return out


def _rewrite(root: pathlib.Path, swap: dict) -> None:
    """root の下の UTF-8 で読めるファイルの中の swap の字（古い値）を新しい値に 1 度で置き換える（長い字から当てる。置き換えた
    字をもう 1 度置き換えない）。読めないファイルはそのまま"""
    olds = sorted((o for o, n in swap.items() if o and o != n), key=len, reverse=True)
    if not olds:
        return
    pat = re.compile("|".join(re.escape(o) for o in olds))
    for p, text in list(_texts(root)):
        new = pat.sub(lambda m: swap[m.group(0)], text)
        if new != text:
            p.write_text(new, encoding="utf-8")


def adopt(board_dir, src, repo, *, run_id: str, pack_root, request_text: str, test_cmd: str, fix_shape: str) -> dict:
    """固定材料 src（DIR のフォルダ）を board_dir へ取り込み、start の控えの doc を返す。拒む物（FixtureRefused。何も書かない）:
    控えが無い・読めない／写しのファイルの sha256 が違う・足りない・多い／board_dir が空でない／今の HEAD^{tree} が控えの tree と
    違う／作業ツリーに変更が在る／写した時に固めた版（snapshots）の木が対象に無い／request_text の sha256 が違う／test_cmd が
    違う。通れば:
    1. 写しを board_dir へ写す
    2. 対象に無い snapshots の版を同じ木で作り直し（親は今の HEAD）、UTF-8 で読めるファイルの中の古い版の名と
       board_root・repo_root・pack_root・head を新しい値に置き換える
    3. 写しに振り分けの控え（fixshape.CHOICE_REL）が在れば消す（腕の形は今の入力で決める）
    4. start の控えの run_id と fix_shape を今の値にし、鍵 KEY {source_run, manifest_sha256} を足す"""
    src = pathlib.Path(src)
    board = pathlib.Path(board_dir).resolve()
    man, man_sha = _manifest(src)
    copy = src / COPY
    _check_copy(copy, man)
    if board.exists() and (not board.is_dir() or any(board.iterdir())):
        raise FixtureRefused(f"取り込む先の盤面の置き場 {board} が空でない——固定材料は空の置き場にだけ取り込む")
    head = _check_repo(repo, man)
    if _sha(request_text.encode("utf-8")) != man["request_sha256"]:
        raise FixtureRefused("依頼の文の sha256 が固定材料と違う——同じ依頼の run だけが固定材料から始める")
    if test_cmd != man["test_cmd"]:
        raise FixtureRefused(f"test_cmd={test_cmd!r} が固定材料の test_cmd={man['test_cmd']!r} と違う")
    remade = _remade(repo, man, head)   # 盤面を書く前に（作れなければ盤面を作らずに拒む）
    board.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(copy, board, dirs_exist_ok=True)
    new = {"board_root": str(board), "repo_root": str(pathlib.Path(repo).resolve()), "pack_root": str(pack_root), "head": head}
    _rewrite(board, {**remade, **{man[k]: new[k] for k in ROOT_KEYS}})
    (board / fixshape.CHOICE_REL).unlink(missing_ok=True)
    start_path = board / fixshape.START_REL
    doc = json.loads(start_path.read_text(encoding="utf-8"))
    doc.update({"run_id": run_id, fixshape.KEY: fix_shape, KEY: {"source_run": man["source_run"], "manifest_sha256": man_sha}})
    _write_json(start_path, doc)
    return doc
