"""考えの住処の柵の道具（試験 tests/test_concept_fences は works 自身の表に、run の中の構造のブロックは対象の表に当てる）。

表 docs/concepts.json（地図 docs/concepts.md の隣）が、住処の在る考えごとに柵を持つ: 語の形（pattern。正規表現）・
知ってよい所（allowed。fnmatch の形で `*` は `/` もまたぐ）・既知の漏れ（known。"<表の持ち主のフォルダからのパス>" → [行の数, 理由]）・
結んだ写し（bound。任意。[{paths, lines, by, why}]: paths のファイルで lines（正規表現）に当たる行は、源の値を試験 by が縛る写しなので
数えない。流れの道具が値を決まった置き場からしか読まないなど、写しが消せない時の形。どの行が写しかは by の試験が表の行を読んで縛る）。
表の exclude（文書・写し・生成物・試験の材料）と allowed の外の追跡されたファイルで、pattern に当たる行を「ファイル →
行の数」で数え、known とちょうど揃うかを見る（減る向きにだけ動かす）。
地図からは、考えの id と状態（map_ids）・見出しの下の決まった頭の行（map_rows）・行に書いたパス（map_paths）を読む。

対象のリポジトリでは、表は追跡されたファイルの中の決まった名（concepthome.TABLE_NAME。根か、どのフォルダの下でも）で探し、
表の中のパスはその docs/ の親のフォルダ（持ち主のフォルダ）からの相対で読む。表が無い対象では何も数えない（作らない）。

- load(root)・tracked(root)・scan(root, paths, fence, exclude)・verdict(found, known)・map_rows・map_ids・map_paths(md, heads)
- count_lines(text, fence, path) -> int: 1 つのファイルの柵の語の行の数（結んだ写しの行を除く。scan・places・scan_change が使う）
- check_table(doc): 表の形の確かめ（concepts の表・pattern と bound の lines が正規表現・allowed と bound の paths が配列。外れは ValueError か re.error）
- tables(repo, rev=None) -> ([(持ち主のフォルダ, 表)], [読めない表の訳]): 対象の表を探して読む（投げない）。rev を渡せば
  その版の木の表を読む（直しが表を広げても、直しの前の表で数える）
- changed(repo, base_rev) -> [パス]: base_rev と今の作業ツリーで変わった・足したファイル（.archon/ の写しと入れ子のリポジトリは除く）
- places(repo, base, table, paths) -> [{concept, what, path, lines, home, known_places}]: 単位のファイル（repo からの相対）に
  当たる柵ごとの行の数・住処（allowed）か・その考えを知る場所の数（持ち主のフォルダの中で exclude の外の全部。住処を含む）
- scan_change(repo, base_rev, table, base="") -> [{concept, what, path, before, after}]: base_rev と今の作業ツリーの間で変わった
  ファイル（持ち主のフォルダの中だけ）を各柵で数え、住処の外で行の数が増えた物（path は repo からの相対）
- fork_ref(root, ref=MAIN_REF)・main_table(root, ref=MAIN_REF)・growth(main, now): 散らばり（住処の無い考え）の柵は知ってよい所が空で、今の知る場所を全部
  既知の漏れに置く数の歯止め。表そのものも増えない: main の表（ref の同じパス）と比べ、考えごとの既知の漏れの件数の和が増えた・
  main に無いパスが出た所を growth が名指す（main で柵を持たない考えは比べない）

標準ライブラリと concepthome（探し方）だけを使う。
"""
from __future__ import annotations

import fnmatch
import json
import pathlib
import re
import subprocess

import concepthome
from leftovers import ARCHON_PREFIX   # 流れの道具が run の作業ツリーに写す工程の置き場（直しの差分に数えない）

TABLE = concepthome.TABLE_NAME
MAIN_REF = "origin/main"   # 表の件数を比べる相手（CI の works の job は全履歴で取るので在る）
HEADING = re.compile(r"^### `([^`]+)`")
STATUS_WORD = re.compile(r"[^\s（(]+")
CODE = re.compile(r"`([^`]+)`")


def load(root):
    """柵の表（root の docs/concepts.json）"""
    return json.loads((pathlib.Path(root) / TABLE).read_text(encoding="utf-8"))


def fork_ref(root, ref=MAIN_REF):
    """表を比べる版: HEAD と ref の分かれ目（git merge-base）。枝は分かれた時の main より増やさない——分かれた後に main が
    下げた数は、main へ入れる時（分かれ目が main の頭になる）に比べる。分かれ目を引けなければ ref のまま（引けない訳は
    main_table が名指す）"""
    got = subprocess.run(["git", "-C", str(root), "merge-base", "HEAD", ref], capture_output=True, text=True)
    return got.stdout.strip() if got.returncode == 0 and got.stdout.strip() else ref


def main_table(root, ref=MAIN_REF):
    """(ref の柵の表, None) か (None, 引けない理由)。表のパスは root からの相対で引く（git の「<ref>:./<パス>」）"""
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
    """root からのパスの一覧: 追跡された物と、まだ追跡されていない .gitignore に当たらない物（足したファイルを commit の前から数える）"""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return list(dict.fromkeys(f for f in out.split("\0") if f))


def _hit(path, globs):
    return any(fnmatch.fnmatch(path, g) for g in globs)


def _bound(fence, path: str) -> list:
    """path に当たる結んだ写しの行の形（正規表現）の並び"""
    return [re.compile(b["lines"]) for b in fence.get("bound") or [] if _hit(path, b["paths"])]


def count_lines(text: str, fence, path: str) -> int:
    pat, copies = re.compile(fence["pattern"]), _bound(fence, path)
    return sum(1 for line in text.splitlines() if pat.search(line) and not any(c.search(line) for c in copies))


def _text(path: pathlib.Path) -> str | None:
    """テキストの中身（読めない・テキストでない物は None）"""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    return None if "\0" in text else text


def scan(root, paths, fence, exclude):
    """{パス: pattern に当たる行の数}。allowed と exclude に当たるファイル・読めないファイル・テキストでない物は見ない。0 は入れない"""
    found = {}
    for f in paths:
        if _hit(f, fence["allowed"]) or _hit(f, exclude):
            continue
        text = _text(pathlib.Path(root) / f)
        n = count_lines(text, fence, f) if text is not None else 0
        if n:
            found[f] = n
    return found


def verdict(found, known):
    """既知の漏れとのずれの文の一覧（空なら揃っている）: 表に無いファイル・増えた・減った（直ったのに表が残る）。
    known の値は [行の数, 理由]（tuple でも list でもよい）"""
    out = []
    for key in sorted(set(found) | set(known)):
        n, k = found.get(key, 0), known.get(key, (0, ""))[0]
        if n > k:
            out.append(f"増えた {key}: {n} 行（表は {k}）")
        elif n < k:
            out.append(f"減った {key}: {n} 行（表は {k}。表を減らす）")
    return out


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


def map_paths(md, heads):
    """地図の行に書いたパス（重なりは落とす）。「予定」も「枝 `」も含まない行の、`…` で囲まれ heads（パスの頭の並び。地図の
    持ち主のフォルダの並べ方で決まるので呼び手が渡す）のどれかで始まる語。末尾の / は落とす"""
    out = []
    for line in md.splitlines():
        if "予定" in line or "枝 `" in line:
            continue
        for word in CODE.findall(line):
            if word.startswith(tuple(heads)):
                out.append(word.rstrip("/"))
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- 対象のリポジトリに当てる口
def _show(repo, rev: str, name: str) -> bytes | None:
    p = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{name}"], capture_output=True, stdin=subprocess.DEVNULL)
    return p.stdout if p.returncode == 0 else None


def _rev_names(repo, rev: str) -> tuple[list[str], str]:
    p = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-z", "--name-only", rev], capture_output=True,
                       stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        return [], p.stderr.decode("utf-8", "replace").strip()[-300:] or f"git ls-tree が終了コード {p.returncode}"
    return [n for n in p.stdout.decode("utf-8", "surrogateescape").split("\0") if n], ""


def tables(repo, rev: str | None = None) -> tuple[list[tuple[str, dict]], list[str]]:
    """([(持ち主のフォルダ, 表)], [読めない表の訳])。表は追跡されたファイル（rev なら その版の木）の中の concepthome.TABLE_NAME
    （浅い順）。投げない"""
    names, why = _rev_names(repo, rev) if rev else concepthome.tracked_names(pathlib.Path(repo))
    out, bad = [], [f"木を読めなかった: {why}"] if why else []
    for name in concepthome.pick_tables(names):
        try:
            raw = _show(repo, rev, name) if rev else (pathlib.Path(repo) / name).read_bytes()
            if raw is None:
                raise OSError(f"{rev} に読めない")
            doc = json.loads(raw.decode("utf-8"))
            check_table(doc)
        except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError, re.error) as e:
            bad.append(f"{name}: {e}")
            continue
        out.append((concepthome.base_of(name), doc))
    return out, bad


def check_table(doc) -> None:
    if not isinstance(doc, dict) or not isinstance(doc.get("concepts"), dict):
        raise ValueError("concepts の表が無い")
    for k, v in doc["concepts"].items():
        for f in v.get("fences") or []:
            re.compile(f["pattern"])
            if not isinstance(f.get("allowed"), list):
                raise ValueError(f"{k} の allowed が配列でない")
            bound = f.get("bound", [])
            if not isinstance(bound, list):
                raise ValueError(f"{k} の bound が配列でない")
            for b in bound:
                if not (isinstance(b, dict) and isinstance(b.get("paths"), list) and isinstance(b.get("lines"), str)
                        and isinstance(b.get("by"), str) and b["by"]):
                    raise ValueError(f"{k} の bound の行が {{paths: [...], lines: <正規表現>, by: <縛る試験>}} の形でない")
                re.compile(b["lines"])


def _within(path: str, base: str) -> str | None:
    """repo からの相対のパスを、持ち主のフォルダ base からの相対に（外なら None）"""
    if not base:
        return path
    return path[len(base) + 1:] if path.startswith(base + "/") else None


def _fences(table: dict):
    for k, v in (table.get("concepts") or {}).items():
        for f in v.get("fences") or []:
            yield k, f


def places(repo, base: str, table: dict, paths) -> list[dict]:
    """単位のファイル（repo からの相対）に当たる柵ごとの {concept, what, path, lines, home, known_places}。表の exclude に当たる・
    持ち主のフォルダの外・読めないファイルは見ない。known_places は持ち主のフォルダの中で exclude の外の、その柵の語の在るファイルの数"""
    root = pathlib.Path(repo) / base if base else pathlib.Path(repo)
    exclude = table.get("exclude") or []
    rel = [(p, _within(p, base)) for p in paths]
    rel = [(p, r) for p, r in rel if r is not None and not _hit(r, exclude)]
    if not rel:
        return []
    every = None
    out = []
    for k, f in _fences(table):
        hits = []
        for p, r in rel:
            text = _text(root / r)
            n = count_lines(text, f, r) if text is not None else 0
            if n:
                hits.append((p, r, n))
        if not hits:
            continue
        if every is None:
            every = [x for x in tracked(root) if not _hit(x, exclude)]
        total = sum(1 for x in every if (t := _text(root / x)) is not None and count_lines(t, f, x))
        out += [{"concept": k, "what": f["what"], "path": p, "lines": n, "home": _hit(r, f["allowed"]),
                 "known_places": total} for p, r, n in hits]
    return out


def changed(repo, base_rev: str) -> list[str]:
    """base_rev と今の作業ツリー（まだ追跡されていない物を含む）の間で変わった・足したファイル（repo からの相対）。流れの道具の
    写し（ARCHON_PREFIX の下）と、入れ子のリポジトリ（ls-files が / で終わる名で出す）は除く。git が落ちれば CalledProcessError"""
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True,
                              stdin=subprocess.DEVNULL).stdout.decode("utf-8", "surrogateescape")
    diff = git("diff", "--name-only", "-z", "--no-renames", base_rev, "--").split("\0")
    new = git("ls-files", "-z", "--others", "--exclude-standard").split("\0")
    return list(dict.fromkeys(f for f in diff + new if f and not f.endswith("/") and not f.startswith(ARCHON_PREFIX)))


def _old(repo, rev: str, path: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        return ""   # 前の版に無いファイル
    try:
        text = p.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    return "" if "\0" in text else text


def scan_change(repo, base_rev: str, table: dict, base: str = "") -> list[dict]:
    """[{concept, what, path, before, after}]: base_rev と今の作業ツリーで変わったファイルのうち、持ち主のフォルダ base の中で
    exclude と allowed の外の物を各柵で数え、行の数が増えた物（path は repo からの相対）。git が落ちれば CalledProcessError"""
    exclude = table.get("exclude") or []
    files = []
    for p in changed(repo, base_rev):
        r = _within(p, base)
        if r is not None and not _hit(r, exclude):
            files.append((p, r))
    out = []
    olds, news = {}, {}
    for k, f in _fences(table):
        for p, r in files:
            if _hit(r, f["allowed"]):
                continue
            if p not in news:
                news[p] = _text(pathlib.Path(repo) / p) or ""
                olds[p] = _old(repo, base_rev, p)
            after = count_lines(news[p], f, r)
            before = count_lines(olds[p], f, r)
            if after > before:
                out.append({"concept": k, "what": f["what"], "path": p, "before": before, "after": after})
    return out
