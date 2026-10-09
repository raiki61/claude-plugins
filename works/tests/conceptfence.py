"""考えの住処の柵の中身（試験は test_concept_fences）。

表 docs/concepts.json（地図 docs/concepts.md の隣）が、住処の在る考えごとに柵を持つ: 語の形（pattern。正規表現）・
知ってよい所（allowed。fnmatch の形で `*` は `/` もまたぐ）・既知の漏れ（known。"<works からのパス>" → [行の数, 理由]）。
表の exclude（文書・写し・生成物・試験の材料）と allowed の外の追跡されたファイルで、pattern に当たる行を「ファイル →
行の数」で数え、known とちょうど揃うかを見る（減る向きにだけ動かす。照らしは tests/blockblind.py の verdict を使う）。
地図からは、考えの id と状態（map_ids）・見出しの下の決まった頭の行（map_rows。表の allowed が地図の住処か知ってよい所の行に
在るかを試験が照らす）・行に書いたパス（map_paths）を読む。表を読むのはこのモジュールだけ。
散らばり（住処の無い考え）の柵は知ってよい所が空で、今の知る場所を全部既知の漏れに置く数の歯止め。表そのものも増えない:
main の表（MAIN_REF の同じパス。main_table）と比べ、考えごとの既知の漏れの件数の和が増えた・main に無いパスが出た所を
growth が名指す（main で柵を持たない考えは比べない）。
"""
import fnmatch
import json
import re
import subprocess

from blockblind import verdict as _verdict

TABLE = "docs/concepts.json"
MAIN_REF = "origin/main"   # 表の件数を比べる相手（CI の works の job は全履歴で取るので在る）
PATH_HEADS = (".shared/", "blk-", "darkfactory/", "dev/", "tests/", "skills/")
HEADING = re.compile(r"^### `([^`]+)`")
STATUS_WORD = re.compile(r"[^\s（(]+")
CODE = re.compile(r"`([^`]+)`")


def load(root):
    """柵の表（works の docs/concepts.json）"""
    return json.loads((root / TABLE).read_text(encoding="utf-8"))


def main_table(root, ref=MAIN_REF):
    """(ref の柵の表, None) か (None, 引けない理由)。表のパスは works の根からの相対で引く（git の「<ref>:./<パス>」）"""
    got = subprocess.run(["git", "-C", str(root), "show", f"{ref}:./{TABLE}"],
                         capture_output=True, text=True, encoding="utf-8")
    if got.returncode != 0:
        return None, got.stderr.strip()[-200:] or f"git show の終了コード {got.returncode}"
    return json.loads(got.stdout), None


def _known_of(concept):
    """{パス: 行の数}（考えの柵の全部の既知の漏れの和）"""
    out = {}
    for f in concept["fences"]:
        for path, (n, _why) in f["known"].items():
            out[path] = out.get(path, 0) + n
    return out


def growth(main, now):
    """main の表より増えた所の文の一覧（空なら増えていない）: 考えごとの件数の和が増えた・main に無いパスが出た。
    main で柵を持たない（考えが無い・柵が空の）考えは、初めて柵を掛ける差分なので比べない"""
    out = []
    for k, v in now["concepts"].items():
        before = main["concepts"].get(k)
        if not before or not before["fences"]:
            continue
        old, new = _known_of(before), _known_of(v)
        if sum(new.values()) > sum(old.values()):
            out.append(f"{k}: 既知の漏れの件数が main の {sum(old.values())} から {sum(new.values())} に増えた")
        out += [f"{k}: main の表に無い既知の漏れ {p}" for p in new if p not in old]
    return out


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


def map_rows(md, label):
    """地図の {id: 行の中身}。見出し「### `<id>`」の下の最初の「- <label>: 」の行の、頭の語を除いた残り"""
    head = f"- {label}: "
    out, cur = {}, None
    for line in md.splitlines():
        m = HEADING.match(line)
        if m:
            cur = m.group(1)
        elif cur is not None and cur not in out and line.startswith(head):
            out[cur] = line[len(head):]
    return out


def map_ids(md):
    """地図の {id: 状態}。「- 状態: 」の行の最初の語（括弧の注記は落とす）"""
    out = {}
    for k, rest in map_rows(md, "状態").items():
        word = STATUS_WORD.match(rest)
        out[k] = word.group(0) if word else ""
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
