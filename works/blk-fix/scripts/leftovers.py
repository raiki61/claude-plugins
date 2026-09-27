# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の後始末（blk-fix だけの物。節ではなく、ignored_before・clean・assert_changed・collect が import する模块）。

- ARCHON_PREFIX:      .archon/ の下は修正役の仕事でない（assert_changed は数えず、clean は消さない。決まりはここの 1 本）
- git・git_names:     git を呼ぶ手続き（-z で読むパスの一覧も。Unreadable・GIT_TIMEOUT と合わせて、blk-fix の正本はここの 1 本）
- record_ignored:     修正役の前の git が無視するファイルと未追跡のフォルダを盤面の fix-ignored-before.json に控える（節 ignored-before）
- remove_new_ignored: 控えに無かった無視されるファイルだけを消す（節 clean）
失敗は Unreadable を投げる。git は全部 repo を cwd にして呼ぶ。標準ライブラリだけ（pack の core を読まない）。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

GIT_TIMEOUT = 120
ARCHON_PREFIX = ".archon/"   # Archon が run の作業ツリーに写す工程の置き場
IGNORED_BEFORE_FILE = "fix-ignored-before.json"   # {"ignored": [str], "dirs": [str]}


class Unreadable(Exception):
    pass


def git(repo, *args, text=True):
    """repo を cwd にして git <args> を呼び、標準出力を返す（text なら文字列、でなければ bytes）。呼べない・失敗は Unreadable"""
    try:
        r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
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


def _board_path(board) -> pathlib.Path:
    return pathlib.Path(board) / IGNORED_BEFORE_FILE


def record_ignored(board, repo) -> dict:
    """修正役を起こす前の ignored_files と untracked_dirs を盤面の fix-ignored-before.json に控える。
    {"ok": True, "count", "file"} を返す（count は無視されるファイルの数）"""
    before = {"ignored": ignored_files(repo), "dirs": untracked_dirs(repo)}
    path = _board_path(board)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(before, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return {"ok": True, "count": len(before["ignored"]), "file": str(path)}


def _read_before(board) -> dict:
    path = _board_path(board)
    if not path.is_file():
        raise Unreadable(f"盤面に {IGNORED_BEFORE_FILE} が無い——修正役の前の控えが無いので、どれが修正役の生成物か分からない")
    try:
        before = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unreadable(f"盤面の {IGNORED_BEFORE_FILE} が読めない（{e}）")
    for key in ("ignored", "dirs"):   # 古い形（dirs の無い控え）も拒む。フォルダの控えが無いと、前から在った空のフォルダを消しうる
        v = before.get(key) if isinstance(before, dict) else None
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
            raise Unreadable(f"盤面の {IGNORED_BEFORE_FILE} の型が合わない（{key} が文字列の配列でない）")
    return before


def remove_new_ignored(board, repo) -> dict:
    """修正役が残した、git が無視するファイルを消す（テストの節を生成物の無い木で回すため）。
    今の ignored_files のうち、控えに無かった物（ARCHON_PREFIX の下を除く）だけを消し、それで空になった親のフォルダも
    消す。ただし控えの dirs のどれか（前から在った未追跡のフォルダ）かその下に来たら、そこで止める。前から在った物は、
    中身が変わっていても消さない（元に戻す写しが無い。git clean -ffdX を丸ごと走らせると、対象の .venv など前から
    在った物まで消えてテストが走らなくなる）。
    {"ok": True, "removed": [消したパス、名前の順]} を返す。控えが無い・読めない・git が効かなければ Unreadable（何も消さない）"""
    repo = pathlib.Path(repo)
    before = _read_before(board)
    root = repo.resolve()
    kept_dirs = tuple(before["dirs"])
    new = sorted(set(ignored_files(repo)) - set(before["ignored"]))
    removed = []
    for name in new:
        if name.startswith(ARCHON_PREFIX):
            continue
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
    return {"ok": True, "removed": removed}
