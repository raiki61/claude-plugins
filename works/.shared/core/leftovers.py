"""修正役の後始末（blk-fix の節 ignored_before・clean・assert_changed が import する模块。節ではないので scripts/ でなくここに置く）。

- ARCHON_PREFIX:      .archon/ の下は修正役の仕事でない（assert_changed は数えず、clean は消さない、fix-accept は変えた返答を拒む。
                      決まりはここの 1 本。自分食いの run では pack の写し .archon/workflows/works/** が在る——protected.json の copies の pack-copy）
- archon_digests・archon_changes: .archon/ の下の姿（パスと中身の sha256）と、修正役の前の控えからの違い（fix-accept が拒む）
- git・git_names:     git を呼ぶ手続き（-z で読むパスの一覧も。Unreadable・GIT_TIMEOUT と合わせて、blk-fix の正本はここの 1 本）
- record_ignored:     修正役の前の git が無視するファイル・丸ごと無視されるフォルダと未追跡のフォルダを盤面の fix-ignored-before.json に
                      控える（節 ignored-before）
- remove_new_ignored: 控えに無かった無視されるファイルだけを消す。前から在った丸ごと無視されるフォルダ（.venv など）の下は触らない。
                      消した全件は盤面の fix-removed.json に書き、件数とそのパスだけを返す（節 clean）
失敗は Unreadable を投げる。git は全部 repo を cwd にして呼ぶ。標準ライブラリだけ（core の他の模块も読まない。tests/test_blk_fix が縛る）。
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

GIT_TIMEOUT = 120
ARCHON_PREFIX = ".archon/"   # Archon が run の作業ツリーに写す工程の置き場（自分食いでは線を動かしている pack の写しもここ）
IGNORED_BEFORE_FILE = "fix-ignored-before.json"   # {"ignored": [str], "ignored_dirs": [str], "dirs": [str], "archon": {str: str}}
REMOVED_FILE = "fix-removed.json"   # {"removed": [str]}（clean が消したパスの全件）


class Unreadable(Exception):
    pass


def git(repo, *args, text=True, env=None):
    """repo を cwd にして git <args> を呼び、標準出力を返す（text なら文字列、でなければ bytes）。呼べない・失敗は Unreadable。
    env は子の環境を丸ごと替える（一時の index を GIT_INDEX_FILE で渡すなど。None はこのプロセスの環境のまま）"""
    try:
        r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT,
                           env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unreadable(f"git {' '.join(args)} を呼べない（{type(e).__name__}: {e}）")
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().replace("\n", " ")[-300:]
        raise Unreadable(f"git {' '.join(args)} が失敗した（{err or f'exit {r.returncode}'}）")
    return r.stdout.decode("utf-8", "replace") if text else r.stdout


def git_names(repo, *args) -> list:
    """repo を cwd にして git <args[0]> -z <args[1:]> を呼び、出るパスの一覧（NUL 区切り。日本語などの名前も引用無しのまま）"""
    return [os.fsdecode(n) for n in git(repo, args[0], "-z", *args[1:], text=False).split(b"\0") if n]


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


def _board_path(board) -> pathlib.Path:
    return pathlib.Path(board) / IGNORED_BEFORE_FILE


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


def record_ignored(board, repo) -> dict:
    """修正役を起こす前の ignored_files と丸ごと無視されるフォルダと untracked_dirs と .archon/ の下の姿（archon_digests）を
    盤面の fix-ignored-before.json に控える。{"ok": True, "count", "file"} を返す（count は無視されるファイルの数）"""
    before = {"ignored": ignored_files(repo), "ignored_dirs": _ignored_dirs(repo), "dirs": untracked_dirs(repo),
              "archon": archon_digests(repo)}
    return {"ok": True, "count": len(before["ignored"]), "file": _write_json(_board_path(board), before)}


def _write_json(path: pathlib.Path, data) -> str:
    """盤面に JSON を書く（tmp に書いて os.replace。途中で切れた書きかけを残さない）。書いたパスの字を返す"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return str(path)


def _read_before(board) -> dict:
    path = _board_path(board)
    if not path.is_file():
        raise Unreadable(f"盤面に {IGNORED_BEFORE_FILE} が無い——修正役の前の控えが無いので、どれが修正役の生成物か分からない")
    try:
        before = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unreadable(f"盤面の {IGNORED_BEFORE_FILE} が読めない（{e}）")
    # 古い形（dirs・ignored_dirs の無い控え）も拒む。フォルダの控えが無いと、前から在った空のフォルダや .venv の中身を消しうる
    for key in ("ignored", "ignored_dirs", "dirs"):
        v = before.get(key) if isinstance(before, dict) else None
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
            raise Unreadable(f"盤面の {IGNORED_BEFORE_FILE} の型が合わない（{key} が文字列の配列でない）")
    return before


def archon_changes(board, repo) -> list:
    """修正役の前の控え（record_ignored の archon）から .archon/ の下で中身が変わった・足した・消したパス（名前の順）。
    控えが無い・読めない・archon の欄が無い（古い形）なら Unreadable"""
    before = _read_before(board).get("archon")
    if not isinstance(before, dict):
        raise Unreadable(f"盤面の {IGNORED_BEFORE_FILE} に .archon/ の姿（archon）が無い——修正役の前の控えが古い形")
    now = archon_digests(repo)
    return sorted(k for k in set(before) | set(now) if before.get(k) != now.get(k))


def remove_new_ignored(board, repo) -> dict:
    """修正役が残した、git が無視するファイルを消す（テストの節を生成物の無い木で回すため）。
    今の ignored_files のうち、控えに無かった物（ARCHON_PREFIX の下と、控えの ignored_dirs——前から在った丸ごと無視される
    フォルダ——の下を除く）だけを消し、それで空になった親のフォルダも消す。ただし控えの dirs のどれか（前から在った
    未追跡のフォルダ）かその下に来たら、そこで止める。前から在った物は、中身が増えた・変わっていても消さない（元に戻す
    写しが無い。git clean -ffdX を丸ごと走らせると、対象の .venv など前から在った物まで消えてテストが走らなくなる）。
    消したパスの全件（名前の順）は盤面の fix-removed.json に {"removed": [...]} で書き、{"ok": True, "count", "file"} を返す
    （件数に上限が無いので、子の stdout・節の出口には載せない）。控えが無い・読めない・git が効かなければ Unreadable（何も消さない）"""
    repo = pathlib.Path(repo)
    before = _read_before(board)
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
    return {"ok": True, "count": len(removed), "file": _write_json(pathlib.Path(board) / REMOVED_FILE, {"removed": removed})}
