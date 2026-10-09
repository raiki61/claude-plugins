"""考えの住処の柵の中身（試験は test_concept_fences）。

表 docs/concepts.json（地図 docs/concepts.md の隣）が、住処の在る考えごとに柵を持つ: 語の形（pattern。正規表現）・
知ってよい所（allowed。fnmatch の形で `*` は `/` もまたぐ）・既知の漏れ（known。"<works からのパス>" → [行の数, 理由]）。
表の exclude（文書・写し・生成物・試験の材料）と allowed の外の追跡されたファイルで、pattern に当たる行を「ファイル →
行の数」で数え、known とちょうど揃うかを見る（減る向きにだけ動かす。照らしは tests/blockblind.py の verdict を使う）。
地図からは、考えの id と状態（map_ids）と、行に書いたパス（map_paths）を読む。表を読むのはこのモジュールだけ。
"""
import fnmatch
import json
import re
import subprocess

from blockblind import verdict as _verdict

TABLE = "docs/concepts.json"
PATH_HEADS = (".shared/", "blk-", "darkfactory/", "dev/", "tests/", "skills/")
HEADING = re.compile(r"^### `([^`]+)`")
STATUS = "- 状態: "
STATUS_WORD = re.compile(r"[^\s（(]+")
CODE = re.compile(r"`([^`]+)`")


def load(root):
    """柵の表（works の docs/concepts.json）"""
    return json.loads((root / TABLE).read_text(encoding="utf-8"))


def tracked(root):
    """works からのパスの一覧: 追跡された物と、まだ追跡されていない .gitignore に当たらない物（足したファイルを commit の前から数える）"""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return list(dict.fromkeys(f for f in out.split("\0") if f))


def _hit(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def scan(root, paths, fence, exclude):
    """{パス: pattern に当たる行の数}。allowed と exclude に当たるファイル・読めないファイル・テキストでない物は見ない。0 は入れない"""
    pat = re.compile(fence["pattern"])
    found = {}
    for f in paths:
        if _hit(f, fence["allowed"]) or _hit(f, exclude):
            continue
        try:
            text = (root / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "\0" in text:
            continue
        n = sum(1 for line in text.splitlines() if pat.search(line))
        if n:
            found[f] = n
    return found


def verdict(found, known):
    """既知の漏れとのずれの文の一覧（空なら揃っている）: 表に無いファイル・増えた・減った（直ったのに表が残る）"""
    return _verdict(found, {k: tuple(v) for k, v in known.items()})


def map_ids(md):
    """地図の {id: 状態}。見出し「### `<id>`」の下の最初の「- 状態: 」の行の最初の語（括弧の注記は落とす）"""
    out, cur = {}, None
    for line in md.splitlines():
        m = HEADING.match(line)
        if m:
            cur = m.group(1)
        elif cur is not None and cur not in out and line.startswith(STATUS):
            word = STATUS_WORD.match(line[len(STATUS):])
            out[cur] = word.group(0) if word else ""
    return out


def map_paths(md):
    """地図の行に書いたパス（重なりは落とす）。「予定」も「枝 `」も含まない行の、`…` で囲まれ PATH_HEADS で始まる語。末尾の / は落とす"""
    out = []
    for line in md.splitlines():
        if "予定" in line or "枝 `" in line:
            continue
        for word in CODE.findall(line):
            if word.startswith(PATH_HEADS):
                out.append(word.rstrip("/"))
    return list(dict.fromkeys(out))
