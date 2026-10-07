"""works/dev/canary_fixture.py — canary の固定材料（修正の直前から始める canary。canary.sh --request units）を作る・確かめる（開発の殻）。

  python3 canary_fixture.py build <canary の置き場> <run-id> <出す置き場>
  python3 canary_fixture.py check <固定材料の置き場>

固定材料の置き場の形（出す置き場。例 dev/canary-fixture-units/）:
- SEED（seed/）: 元の run の対象の HEAD の中身（canary の種の写し。木は控えの tree と同じ）。canary.sh はこれを対象に commit する
- REQUEST（request.json）: 元の run の依頼の写し（sha256 は控えの request_sha256）。canary.sh はこれを依頼に渡す
- FIXTURE（fix-fixture/）: 元の run の h-fix が $ARTIFACTS_DIR/fix-fixture に写した物（.shared/core/fixture.py の固定材料。
  盤面の写し board/・盤面の外の写し outside/・控え fixture.json）。use.sh に WORKS_USE_FIX_FIXTURE で渡す
取り込み（fixture.adopt）が見る物は、対象の HEAD^{tree} が控えの tree・依頼の文の sha256 が控えの物・start の控えの入力の欄が
今の入力と同じ（fix_shape・run_id・request_file・fix_fixture・features_off を除く）・写しが控えのファイルの sha256 のとおり、と
盤面を開く時の works の表・graph・置き場の版（entry.open_board）。種と依頼が元の run の物なので、今の canary-seed とは別に運ぶ。

build: 置き場（canary.sh が作った物。home/archon-home/workspaces/*/*/artifacts/runs/<run-id>/fix-fixture と repo/）から 3 つを
出す置き場へ写す（出す置き場は無いこと）。写しの中の置き場のパスは、控えの board_root の親（元の $ARTIFACTS_DIR）・repo_root・
pack_root を PORTABLE の下の印に置き換え、控えの 3 つの欄も同じ印にする（取り込みは控えの 3 つの字を新しい置き場に置き換えるので、
印のままで取り込める）。canary の置き場の根と Claude Code の一時の置き場（/private/tmp/claude-<数>）の字は、記録の文に残るだけ
なので PORTABLE の下の印にする。控えの files は書き換えた後の sha256 で書き直す（fixture.py の頭: 写しと控えの両方を揃えて
書き換えた物は見分けない）。置き換えの後にこの機械の置き場の字（MACHINE と家のパス）が残れば、何も出さずに拒む。
check: problems（写しが控えのとおりか・seed/ の木・request.json の sha256・機械の字）と stale（盤面を作った works の表・graph・
置き場の版が今の works と同じか。違えば start が「固定材料と works の版が違う」で拒むので、本物の run で写し直す）を 1 行ずつ出す。
終了コード: 0 = どちらも無い・1 = どちらかが在る・2 = 引数の誤り・build が拒んだ。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

PACK = pathlib.Path(__file__).resolve().parents[1]
for _p in (PACK / ".shared" / "core",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import board  # noqa: E402   表の graph の sha・置き場の版・盤面の層の版
import entry  # noqa: E402   ラインの表（load_table）
import fixshape  # noqa: E402  start の控えの置き場（START_REL）
import fixture  # noqa: E402   固定材料の形（DIR・MANIFEST・COPY）と控えの照らし

SEED, REQUEST, FIXTURE = "seed", "request.json", fixture.DIR
PORTABLE = "/works-canary-fixture"   # 写しの中の置き場のパスの印の根（どの機械にも無い置き場）
MACHINE = ("/Users/", "/private/", "/var/folders/", "/tmp/claude-")   # 残してはいけないこの機械の置き場の字
CLAUDE_TMP = re.compile(r"(?:/private)?/tmp/claude-[0-9]+")   # Claude Code の一時の置き場（記録の文に残る）
WORKSPACES = ("home", "archon-home", "workspaces")   # canary の置き場の下の Archon の作業の置き場
USAGE = "usage: canary_fixture.py build <canary の置き場> <run-id> <出す置き場> | canary_fixture.py check <固定材料の置き場>"


class Refused(Exception):
    """引数・置き場の誤り（終了コード 2）"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


CACHE_NAMES = ("__pycache__", ".pytest_cache", ".DS_Store")   # canary.sh が commit の前に消す物（と *.pyc）


def _tree_entries(folder: pathlib.Path) -> bytes:
    """folder の git の木の hash（再帰。git の木の形: 名の並びは字の順で、フォルダは名に / を足して比べる）"""
    rows = []
    for p in folder.iterdir():
        if p.name == ".git" or p.name in CACHE_NAMES or p.suffix == ".pyc":
            continue
        if p.is_dir():
            rows.append((p.name + "/", b"40000 " + p.name.encode() + b"\0" + _tree_entries(p)))
        else:
            data = p.read_bytes()
            mode = b"100755" if os.access(p, os.X_OK) else b"100644"
            rows.append((p.name, mode + b" " + p.name.encode() + b"\0" + _object(b"blob", data)))
    body = b"".join(r for _, r in sorted(rows, key=lambda r: r[0].encode()))
    return _object(b"tree", body)


def _object(kind: bytes, body: bytes) -> bytes:
    return hashlib.sha1(kind + b" " + str(len(body)).encode() + b"\0" + body).digest()


def tree_of(folder) -> str:
    """folder の中身を canary.sh と同じに commit した時の木の hash（canary.sh が消す CACHE_NAMES と *.pyc を除く。git を起こさず、
    どこにも書かない）"""
    return _tree_entries(pathlib.Path(folder)).hex()


def machine_words(root: pathlib.Path) -> list:
    """root の下のファイルに残ったこの機械の置き場の字 ['<相対パス>: <字>']（家のパスも見る）"""
    words = (*MACHINE, str(pathlib.Path.home()))
    return [f"{p.relative_to(root).as_posix()}: {w}" for p, text in fixture._texts(root) for w in words if w in text]


# ---------------------------------------------------------------- 確かめる
def problems(root) -> list:
    """固定材料の置き場の誤り（1 行ずつ。無ければ []）: 控えが読めない・写しが控えと違う・seed/ の木が控えの tree と違う・
    request.json の sha256 が控えの依頼と違う・この機械の置き場の字が残る"""
    root = pathlib.Path(root)
    out = []
    try:
        man, _ = fixture._manifest(root / FIXTURE)
        fixture._check_copy(root / FIXTURE, man)
    except fixture.FixtureRefused as e:
        return [str(e)]
    seed, request = root / SEED, root / REQUEST
    if not seed.is_dir():
        out.append(f"種の写し {seed} が無い")
    else:
        got = tree_of(seed)
        if got != man["tree"]:
            out.append(f"種の写し {SEED}/ の木（tree {got[:12]}）が控えの tree {man['tree'][:12]} と違う")
    if not request.is_file():
        out.append(f"依頼の写し {request} が無い")
    elif _sha(request.read_bytes()) != man["request_sha256"]:
        out.append(f"依頼の写し {REQUEST} の sha256 が控えの依頼（request_sha256）と違う")
    out += [f"この機械の置き場の字が残る: {w}" for w in machine_words(root)]
    return out


def stale(root) -> list:
    """盤面を作った works と今の works の違い（1 行ずつ。無ければ []）: 表の sha（state.works.table_sha）・graph の sha
    （state.graph_sha）・置き場の版（state.works.layout）・盤面の層の版（state.works.board_version）。どれかが違えば線の start が
    取り込んだ盤面を開けずに拒む（entry._start_from_fixture）"""
    path = pathlib.Path(root) / FIXTURE / fixture.COPY / "state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        works = state["works"]
        table = entry.load_table(works["line"])
    except (OSError, ValueError, KeyError, TypeError, board.BoardGap) as e:
        return [f"盤面の写しの {path} を読めない（{type(e).__name__}: {e}）"]
    pairs = (("表の sha", works.get("table_sha"), table.sha()), ("graph の sha", state.get("graph_sha"), board.graph_sha(table.graph)),
             ("置き場の版", works.get("layout"), board.LAYOUT), ("盤面の層の版", works.get("board_version"), board.BOARD_VERSION))
    return [f"{name}が違う（写し {old!r}・今 {now!r}）" for name, old, now in pairs if old != now]


# ---------------------------------------------------------------- 作る
def _source(place: pathlib.Path, run_id: str) -> pathlib.Path:
    found = sorted(place.joinpath(*WORKSPACES).glob(f"*/*/artifacts/runs/{run_id}/{fixture.DIR}"))
    if len(found) != 1:
        raise Refused(f"置き場 {place} の下に run {run_id} の {fixture.DIR} が 1 つでない（{len(found)} 個）")
    return found[0]


def build(place, run_id: str, out) -> dict:
    """置き場の run の固定材料を、種と依頼の写しを添えて out へ移せる形で写す（モジュールの頭の build）。新しい控えを返す"""
    place, out = pathlib.Path(place).resolve(), pathlib.Path(out)
    if out.exists():
        raise Refused(f"出す置き場 {out} が既に在る")
    src = _source(place, run_id)
    try:
        man, _ = fixture._manifest(src)
        fixture._check_copy(src, man)
    except fixture.FixtureRefused as e:
        raise Refused(str(e)) from None
    start = json.loads((src / fixture.COPY / fixshape.START_REL).read_text(encoding="utf-8"))
    request = pathlib.Path(start.get("request_file") or "")
    if not request.is_file() or _sha(request.read_bytes()) != man["request_sha256"]:
        raise Refused(f"start の控えの依頼 {request} が無いか、sha256 が控えの依頼と違う")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="canary-fixture-build-", dir=out.parent))   # 出す置き場の隣（rename で移す）
    try:
        seed = tmp / SEED
        seed.mkdir()
        blob = subprocess.run(["git", "-C", str(place / "repo"), "archive", "--format=tar", man["head"]], capture_output=True)
        if blob.returncode != 0:
            raise Refused(f"対象 {place / 'repo'} の {man['head'][:12]} を引けない: {blob.stderr.decode(errors='replace').strip()}")
        archive = tmp / "seed.tar"
        archive.write_bytes(blob.stdout)
        with tarfile.open(archive) as tar:
            tar.extractall(seed, filter="data")
        archive.unlink()
        if tree_of(seed) != man["tree"]:
            raise Refused(f"対象の {man['head'][:12]} の中身の木が控えの tree {man['tree'][:12]} と違う")
        shutil.copy2(request, tmp / REQUEST)
        dest = tmp / FIXTURE
        shutil.copytree(src, dest)
        board_root = pathlib.Path(man["board_root"])
        art = f"{PORTABLE}/artifacts/runs/{run_id}"
        roots = {"board_root": f"{art}/{board_root.name}", "repo_root": f"{PORTABLE}/worktree", "pack_root": f"{PORTABLE}/pack"}
        swap = fixture._swapper({str(board_root.parent): art, man["repo_root"]: roots["repo_root"],
                                 man["pack_root"]: roots["pack_root"], str(place): f"{PORTABLE}/place"})
        for p, text in list(fixture._texts(dest)):
            if p.name != fixture.MANIFEST:
                new = CLAUDE_TMP.sub(f"{PORTABLE}/tmp", swap(text))
                if new != text:
                    p.write_text(new, encoding="utf-8")
        man = {**man, **roots}
        man["files"] = fixture._files(dest)
        (dest / fixture.MANIFEST).write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        left = machine_words(tmp)
        if left:
            raise Refused("この機械の置き場の字が残る: " + "・".join(left[:5]))
        tmp.rename(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return man


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):   # 日本語の行を Windows の既定 cp1252 で落とさない
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args[:1] == ["build"] and len(args) == 4:
            man = build(args[1], args[2], args[3])
            print(f"固定材料を写した: {args[3]}（元の run {man['source_run']}・tree {man['tree'][:12]}）")
            return 0
        if args[:1] != ["check"] or len(args) != 2 or not pathlib.Path(args[1]).is_dir():
            raise Refused(USAGE)
    except Refused as e:
        print(f"canary_fixture.py: {e}", file=sys.stderr)
        return 2
    bad = problems(args[1])
    old = [] if bad else stale(args[1])
    for line in bad:
        print(f"固定材料の誤り: {line}")
    for line in old:
        print(f"固定材料が今の works より古い（本物の run で写し直す。README の「canary」の節）: {line}")
    return 1 if bad or old else 0


if __name__ == "__main__":
    sys.exit(main())
