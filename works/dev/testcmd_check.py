"""use.sh start が test_cmd を Archon に渡す前に、run の worktree と単位の worktree で効かない形を知らせる（止めない）。

python3 -I works/dev/testcmd_check.py <対象の根> <test_cmd>

run の worktree（Archon が --from の commit から切る）と単位の worktree（修正の段が run の worktree の今の姿の commit から切る）には、
対象の git が無視する物（.venv・node_modules・ビルドの出力・.env など）が無い。知らせるのは 2 つ（どちらも 1 行ずつ標準出力へ）:
- 語のパス: test_cmd の最初の段（&&・||・;・|・& の前。後ろの段は前の段が worktree の中で作った物を使えるので見ない）の語
  （shlex で割る。割れなければ空白で割る。- で始まる旗と = を含む語は見ない）のうち、`/` を含み、対象の根の中を指し、対象に
  今在り、git が無視する物（git check-ignore。パスか、その上のどれかの段が無視されていれば無視）。相対なら worktree に無いので
  走らない。絶対なら対象の手元の環境を使い、対象をそこへ editable で入れていれば worktree の直しでなく対象の手元のコードを試す
- 立てた仮想環境: VIRTUAL_ENV が在り、その bin が PATH に在り、その環境に対象が editable で入っていて（site-packages の
  *.dist-info/direct_url.json の editable の url か、*.pth の絶対パスの行が対象の根の中を指す）、test_cmd の最初の段が
  （前の NAME=値 を除いて）`uv run` で始まらない。run の中の python・pytest は PATH のその環境を掴む（uv run は project の
  .venv を使い VIRTUAL_ENV を見ない）ので、worktree の直しでなく対象の手元のコードを試す。対象の入っていない環境（依存だけの
  環境・uv run の使い捨ての環境）は知らせない
終了コードはいつも 0（引数の数の誤りだけ 2）。git が効かなければ語のパスは見ない。標準ライブラリだけ・Python 3.9 の構文。
"""
import glob
import json
import os
import re
import shlex
import subprocess
import sys
from urllib.parse import unquote, urlparse

USAGE = "usage: testcmd_check.py <対象の根> <test_cmd>"
HOW = "worktree の中で環境を作るコマンド（例 uv run pytest -q）にする（works/README.md の「test_cmd と worktree」）"
SEPARATORS = ("&&", "||", ";", "|", "&")
_ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def _first_segment(cmd):
    """最初の段の語（割れなければ空白で割った全部）"""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        words = list(lex)
    except ValueError:
        return cmd.split()
    for i, w in enumerate(words):
        if w in SEPARATORS:
            return words[:i]
    return words


def _path_words(cmd):
    out = []
    for w in _first_segment(cmd):
        if "/" in w and not w.startswith("-") and "=" not in w and w not in out:
            out.append(w)
    return out


def _under(root, path):
    """path（正規化した絶対パス）が根の中なら根からの相対（根そのもの・外は None）"""
    rel = os.path.relpath(path, root)
    if rel in (".", "..") or rel.startswith(".." + os.sep):
        return None
    return rel


def _within(root, path):
    """path（実パス）が根そのものか根の中か"""
    return path == root or _under(root, path) is not None


def _inside(root, word):
    """word が対象の根の中を指すなら根からの相対、外なら None。相対の語は根から読む。絶対の語は上の段を順に実パスに直し、
    根と同じ実パスの段が在ればその下を相対にする（/tmp・/var のようなリンクを通った綴りでも拾う。語そのものは解かない:
    .venv/bin/python はリンクで、解くと外の python を指す）"""
    if not os.path.isabs(word):
        return _under(root, os.path.normpath(os.path.join(root, word)))
    head = os.path.normpath(word)
    tail = []
    while True:
        head, name = os.path.split(head)
        if not name:
            return None
        tail.insert(0, name)
        if os.path.realpath(head) == root:
            return os.path.join(*tail)


def _prefixes(root, rel):
    """rel の上の段から rel まで（リンクの段で止める。git check-ignore はリンクの先のパスを渡すと 128 で全部を落とす）"""
    parts = rel.split(os.sep)
    out = []
    for i in range(1, len(parts) + 1):
        p = os.sep.join(parts[:i])
        out.append(p)
        if os.path.islink(os.path.join(root, p)):
            break
    return out


def _ignored(root, paths):
    """paths のうち git が無視する物。まとめて問い、git が落ちたら（サブモジュールの中のパスなど。1 本が全部を落とす）
    1 本ずつ問い直す（落ちたパスは無視でないと数える）"""
    if not paths:
        return set()
    try:
        r = subprocess.run(["git", "-C", root, "check-ignore", "-z", "--stdin"], input="\0".join(paths) + "\0",
                           capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")
    except OSError:
        return set()
    if r.returncode in (0, 1):
        return set(filter(None, r.stdout.split("\0")))
    if len(paths) == 1:
        return set()
    return set().union(*(_ignored(root, [p]) for p in paths))


def path_notes(root, cmd):
    found = []
    for w in _path_words(cmd):
        rel = _inside(root, w)
        if rel is not None and os.path.lexists(os.path.join(root, rel)):
            found.append((w, _prefixes(root, rel)))
    hit = _ignored(root, sorted({p for _, ps in found for p in ps}))
    notes = []
    for w, ps in found:
        if not hit.intersection(ps):
            continue
        if os.path.isabs(w):
            notes.append(f"test_cmd の {w} は対象の git が無視するパス: run・単位の worktree からも対象の手元の環境を使い、"
                         f"対象をそこへ editable で入れていれば worktree の直しでなく対象の手元のコードを試す。{HOW}")
        else:
            notes.append(f"test_cmd の {w} は対象の git が無視するパスで、run・単位の worktree に無い（commit から切るので"
                         f"写らない。前の段で作らない限り走らない）。{HOW}")
    return notes


def _editable_target(venv, root):
    """venv に対象が editable で入っているか（PEP 610 の direct_url.json の editable の url か、.pth の絶対パスの行が根の中）"""
    sites = glob.glob(os.path.join(venv, "lib", "python*", "site-packages")) + [os.path.join(venv, "Lib", "site-packages")]
    for site in sites:
        for f in glob.glob(os.path.join(site, "*.dist-info", "direct_url.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            info = d.get("dir_info") if isinstance(d, dict) else None
            if not (isinstance(info, dict) and info.get("editable") is True):
                continue
            u = urlparse(str(d.get("url", "")))
            if u.scheme == "file" and _within(root, os.path.realpath(unquote(u.path))):
                return True
        for f in glob.glob(os.path.join(site, "*.pth")):
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    lines = [ln.strip() for ln in fh]
            except OSError:
                continue
            if any(os.path.isabs(ln) and _within(root, os.path.realpath(ln)) for ln in lines):
                return True
    return False


def venv_notes(root, cmd, environ):
    venv = environ.get("VIRTUAL_ENV", "")
    if not venv:
        return []
    bins = {os.path.normpath(p) for p in environ.get("PATH", "").split(os.pathsep) if p}
    if os.path.normpath(os.path.join(venv, "bin")) not in bins:
        return []
    words = _first_segment(cmd)
    while words and _ASSIGN.match(words[0]):
        words = words[1:]
    if words[:2] == ["uv", "run"] or not _editable_target(venv, root):
        return []
    return [f"VIRTUAL_ENV（{venv}）を立てたまま起こし、対象がそこへ editable で入っている: run の中の test_cmd の python・"
            f"pytest はその環境を PATH から掴み、worktree の直しでなく対象の手元のコードを試す。{HOW}"]


def main(argv):
    if len(argv) != 2:
        print(USAGE, file=sys.stderr)
        return 2
    root, cmd = os.path.realpath(argv[0]), argv[1].strip()
    if not cmd:
        return 0
    for line in path_notes(root, cmd) + venv_notes(root, cmd, os.environ):
        print(f"注意（test_cmd）: {line}")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
