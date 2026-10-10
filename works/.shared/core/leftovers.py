"""修正役の後始末（blk-fix の節 ignored_before・clean・assert_changed が import するモジュール。節ではないので scripts/ でなくここに置く）。

- ARCHON_PREFIX:      .archon/ の下は修正役の仕事でない（assert_changed は数えず、clean は消さない、fix-accept は変えた返答を拒む。
                      決まりはここの 1 本。自分食いの run では pack の写し .archon/workflows/works/** が在る——protected.json の copies の pack-copy）
- archon_digests・archon_changes: .archon/ の下の姿（パスと中身の sha256）と、修正役の前の控えからの違い（fix-accept が拒む）
- git・git_names:     git を呼ぶ手続き（-z で読むパスの一覧も。Unreadable と合わせて、blk-fix の正本はここの 1 本。期限は付けない）
- snapshot:           作業ツリーの今の姿（未追跡の新しいファイルも）を一時の index で固めた木の sha（本物の index は触らない）
- record_ignored:     修正役の前の git が無視するファイル・丸ごと無視されるフォルダと未追跡のフォルダと、段の頭の木（snapshot）を
                      盤面の fix-ignored-before.json に控える（節 ignored-before）
- head_tree:          控えた段の頭の木（修正の受け付けが最後の回に止めた単位の足跡を戻す先）
- remove_new_ignored: 控えに無かった無視されるファイルだけを消す。前から在った丸ごと無視されるフォルダ（.venv など）の下は触らない。
                      消した全件は盤面の fix-removed.json に書き、件数とそのパスだけを返す（節 clean）
- removed:            scope の環境の無い所（報告・最後の関所）から、盤面の根とその直下の scope の根の fix-removed.json を全部読み、
                      件数・全パス・scope ごとのパスを返す。ファイルが 1 つも無ければ走らせていない（0 本と分ける）。読めなければ
                      投げずに読めないと理由を返す
控えと消した物のファイルの名は呼ぶ側が渡せる（before_name・removed_name。既定は IGNORED_BEFORE_FILE・REMOVED_FILE）。控えと消した物のファイルは
盤面の今の scope の根（script_io.scope_dir。include の中なら <盤面>/<include の名>/）に置く（同じブロックの 2 度目の include が
1 度目の控えを上書きしない）。
失敗は Unreadable を投げる。git は全部 repo を cwd にして呼ぶ。標準ライブラリと層 L1 の script_io だけ（core のほかのモジュールは読まない。
tests/test_blk_fix が縛る）。
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

from script_io import scope_dir  # noqa: E402  （盤面の今の scope の根。層 L1・標準ライブラリと流れの道具の口だけ）

ARCHON_PREFIX = ".archon/"   # Archon が run の作業ツリーに写す工程の置き場（自分食いでは線を動かしている pack の写しもここ）
IGNORED_BEFORE_FILE = "fix-ignored-before.json"   # {"ignored": [str], "ignored_dirs": [str], "dirs": [str], "archon": {str: str},
                                                  #  "head_tree": str}
REMOVED_FILE = "fix-removed.json"   # {"removed": [str]}（clean が消したパスの全件）


class Unreadable(Exception):
    pass


def git(repo, *args, text=True, env=None):
    """repo を cwd にして git <args> を呼び、標準出力を返す（text なら文字列、でなければ bytes）。呼べない・失敗は Unreadable。
    env は子の環境を丸ごと替える（一時の index を GIT_INDEX_FILE で渡すなど。None はこのプロセスの環境のまま）"""
    try:
        r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, stdin=subprocess.DEVNULL, env=env)
    except OSError as e:
        raise Unreadable(f"git {' '.join(args)} を呼べない（{type(e).__name__}: {e}）")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().replace("\n", " ")[-300:]
        raise Unreadable(f"git {' '.join(args)} が失敗した（{err or f'exit {r.returncode}'}）")
    return r.stdout.decode("utf-8", "replace") if text else r.stdout


def git_names(repo, *args) -> list:
    """repo を cwd にして git <args[0]> -z <args[1:]> を呼び、出るパスの一覧（NUL 区切り。日本語などの名前も引用無しのまま）"""
    return [os.fsdecode(n) for n in git(repo, args[0], "-z", *args[1:], text=False).split(b"\0") if n]


def _has_head(repo) -> bool:
    try:
        git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        return True
    except Unreadable:
        return False


def snapshot(repo) -> str:
    """作業ツリーの今の姿（未追跡の新しいファイルも。.gitignore に当たる物は除く）の木の sha。本物の index は触らない"""
    with tempfile.TemporaryDirectory(prefix="works-tdd-index-") as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(pathlib.Path(td) / "index")}
        if _has_head(repo):
            git(repo, "read-tree", "HEAD", env=env)
        git(repo, "add", "-A", "--", ":/", env=env)
        return git(repo, "write-tree", env=env).strip()


def ignored_files(repo) -> list:
    """git が無視する未追跡のファイル（repo の根から。1 本ずつで、フォルダに畳まない。名前の順）。
    git ls-files --others --ignored --exclude-standard（git-ls-files(1)）。入れ子の git リポジトリは `sub/` の 1 本"""
    return sorted(set(git_names(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "--full-name", "--", ":/")))


def untracked_dirs(repo) -> list:
    """丸ごと未追跡のフォルダ（無視されるか否かを問わない。末尾が / の名前、名前の順）。git ls-files --others --directory
    （除外の規則を読まないので無視される物も出る）は、丸ごと未追跡のフォルダを 1 本に畳み、--no-empty-directory を付けない
    ので空のフォルダも出す（git-ls-files(1)）。フォルダは ignored_files に載らないので、前から在ったかはこれで控える"""
    return sorted({n for n in git_names(repo, "ls-files", "--others", "--directory", "--full-name", "--", ":/") if n.endswith("/")})


def _ignored_dirs(repo) -> list:
    """丸ごと無視されるフォルダ（末尾が / の名前、名前の順。対象の .venv・node_modules・__pycache__ など）。
    git ls-files --others --ignored --exclude-standard --directory は、中身が全部無視されるフォルダを 1 本に畳む（git-ls-files(1)）"""
    return sorted({n for n in git_names(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory",
                                        "--full-name", "--", ":/") if n.endswith("/")})


def _board_path(board, before: str = IGNORED_BEFORE_FILE) -> pathlib.Path:
    """盤面 board の今の scope の根の before（script_io.scope_dir）"""
    return scope_dir(board) / before


def _is_bytecode(rel: str) -> bool:
    return rel.endswith(".pyc") or "/__pycache__/" in f"/{rel}"


def archon_digests(repo) -> dict:
    """repo の .archon/ の下の全部のファイルの {リポジトリの根からの相対パス: 中身の sha256}（symlink は辿らず "link:<先>"。
    バイトコード——__pycache__/ の下と .pyc——は数えない。git の追跡・無視に依らない。.archon/ が無ければ空）"""
    repo = pathlib.Path(repo)
    top = repo / ARCHON_PREFIX.rstrip("/")
    if top.is_symlink():
        return {ARCHON_PREFIX.rstrip("/"): "link:" + os.readlink(top)}
    out = {}
    for dirpath, dirnames, filenames in os.walk(top):
        here = pathlib.Path(dirpath)
        for name in filenames + [d for d in dirnames if (here / d).is_symlink()]:
            p = here / name
            rel = p.relative_to(repo).as_posix()
            if _is_bytecode(rel):
                continue
            out[rel] = "link:" + os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def record_ignored(board, repo, before_name: str = IGNORED_BEFORE_FILE) -> dict:
    """修正役を起こす前の ignored_files と丸ごと無視されるフォルダと untracked_dirs と .archon/ の下の姿（archon_digests）と
    段の頭の木（snapshot。欄 head_tree）を盤面の fix-ignored-before.json（before_name）に控える。{"ok": True, "count", "file"} を
    返す（count は無視されるファイルの数）"""
    before = {"ignored": ignored_files(repo), "ignored_dirs": _ignored_dirs(repo), "dirs": untracked_dirs(repo),
              "archon": archon_digests(repo), "head_tree": snapshot(repo)}
    return {"ok": True, "count": len(before["ignored"]), "file": _write_json(_board_path(board, before_name), before)}


def _write_json(path: pathlib.Path, data) -> str:
    """盤面に JSON を書く（tmp に書いて os.replace。途中で切れた書きかけを残さない）。書いたパスの字を返す"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return str(path)


def _read_before(board, before_name: str = IGNORED_BEFORE_FILE) -> dict:
    path = _board_path(board, before_name)
    if not path.is_file():
        raise Unreadable(f"盤面に {before_name} が無い——修正役の前の控えが無いので、どれが修正役の生成物か分からない")
    try:
        before = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unreadable(f"盤面の {before_name} が読めない（{e}）")
    # 古い形（dirs・ignored_dirs の無い控え）も拒む。フォルダの控えが無いと、前から在った空のフォルダや .venv の中身を消しうる
    for key in ("ignored", "ignored_dirs", "dirs"):
        v = before.get(key) if isinstance(before, dict) else None
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
            raise Unreadable(f"盤面の {before_name} の型が合わない（{key} が文字列の配列でない）")
    return before


def head_tree(board, before_name: str = IGNORED_BEFORE_FILE) -> str:
    """record_ignored が控えた段の頭の木（欄 head_tree）。控えが無い・読めない・欄が空でない文字列でなければ Unreadable"""
    tree = _read_before(board, before_name).get("head_tree")
    if not isinstance(tree, str) or not tree:
        raise Unreadable(f"盤面の {before_name} に段の頭の木（head_tree）が無い")
    return tree


def archon_changes(board, repo, before_name: str = IGNORED_BEFORE_FILE) -> list:
    """修正役の前の控え（record_ignored の archon。before_name）から .archon/ の下で中身が変わった・足した・消したパス（名前の順）。
    控えが無い・読めない・archon の欄が無い（古い形）なら Unreadable"""
    before = _read_before(board, before_name).get("archon")
    if not isinstance(before, dict):
        raise Unreadable(f"盤面の {before_name} に .archon/ の姿（archon）が無い——修正役の前の控えが古い形")
    now = archon_digests(repo)
    return sorted(k for k in set(before) | set(now) if before.get(k) != now.get(k))


def remove_new_ignored(board, repo, before_name: str = IGNORED_BEFORE_FILE, removed_name: str = REMOVED_FILE) -> dict:
    """修正役が残した、git が無視するファイルを消す（テストの節を生成物の無い木で回すため）。
    今の ignored_files のうち、控えに無かった物（ARCHON_PREFIX の下と、控えの ignored_dirs——前から在った丸ごと無視される
    フォルダ——の下を除く）だけを消し、それで空になった親のフォルダも消す。ただし控えの dirs のどれか（前から在った
    未追跡のフォルダ）かその下に来たら、そこで止める。前から在った物は、中身が増えた・変わっていても消さない（元に戻す
    写しが無い。git clean -ffdX を丸ごと走らせると、対象の .venv など前から在った物まで消えてテストが走らなくなる）。
    控えは盤面の before_name を読む。消したパスの全件（名前の順）は盤面の fix-removed.json（removed_name）に {"removed": [...]}
    で書き、{"ok": True, "count", "file"} を返す（件数に上限が無いので、子の stdout・節の出口には載せない）。控えが無い・読めない・git が効かなければ Unreadable（何も消さない）"""
    repo = pathlib.Path(repo)
    before = _read_before(board, before_name)
    root = repo.resolve()
    kept_dirs = tuple(before["dirs"])
    kept = (ARCHON_PREFIX, *before["ignored_dirs"])
    new = sorted(n for n in set(ignored_files(repo)) - set(before["ignored"]) if not n.startswith(kept))
    removed = []
    for name in new:
        p = repo / name.rstrip("/")
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)
        else:
            continue
        removed.append(name)
        parent = p.parent
        while parent.resolve() != root and parent.is_dir() and not any(parent.iterdir()):
            if (parent.relative_to(repo).as_posix() + "/").startswith(kept_dirs):
                break
            parent.rmdir()
            parent = parent.parent
    return {"ok": True, "count": len(removed), "file": _write_json(_board_path(board, removed_name), {"removed": removed})}


def removed(board, removed_name: str = REMOVED_FILE) -> dict:
    """盤面 board の根とその直下のフォルダ（include の scope の根）に clean が書いた removed_name を全部読む。投げない。
    返り {ran, readable, reason, count, paths, by_scope}: ran はファイルが 1 つでも在る（clean が走った）。readable が偽なら
    reason に読めないファイルと理由（0 本に見せない）。by_scope は {scope の名（盤面の直下は ""）: [消したパス]}（名前の順）、
    paths はその全部をつないだ物、count はその数。scope ごとに最後に clean が走った周の分だけ（前の周の分は上書きで残らない）"""
    out = {"ran": False, "readable": True, "reason": "", "count": 0, "paths": [], "by_scope": {}}
    board = pathlib.Path(board)
    try:
        found = sorted(p for p in [board / removed_name, *board.glob(f"*/{removed_name}")] if p.is_file())
    except OSError as e:
        return {**out, "ran": True, "readable": False, "reason": f"盤面の {removed_name} を探せない（{e}）"}
    bad = []
    for p in found:
        scope = "" if p.parent == board else p.parent.name
        try:
            names = json.loads(p.read_text(encoding="utf-8")).get("removed")
        except (OSError, ValueError, AttributeError) as e:
            bad.append(f"{p}: {type(e).__name__}: {e}")
            continue
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            bad.append(f"{p}: removed が文字列の配列でない")
            continue
        out["by_scope"][scope] = names
    paths = [n for names in out["by_scope"].values() for n in names]
    out.update(ran=bool(found), count=len(paths), paths=paths)
    if bad:
        out.update(readable=False, reason=f"{removed_name} が読めない（" + "／".join(bad) + "）")
    return out
