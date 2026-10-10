"""借りる superpowers（Claude Code のプラグインのスキル集）の写しを固定と照らし、節（seam: 借りた物を works の役に載せる 1 項目）
の契約を確かめ、部品の型を埋める部品。

言葉:
- 版のフォルダ: superpowers の 1 つの版の中身（.shared/borrow/superpowers/<版> の写し、または利用者のキャッシュの版の置き場）
- 包むファイル: 版のフォルダのうち works が使う物。借りるスキルの skills/<名>/ の下の全ファイル・部品（parts）・LICENSE
- 固定（pin）: borrow.json の superpowers.pin。{version, commit, checked, files: {相対パス: sha256}}
- 錨（anchor）: 読み替えの決まりの根拠になる原文の引用。引用を含む行がちょうど 1 行で、その段落の sha256 が固定の時と同じこと
- 穴（placeholder）: 部品の型（```` ``` ```` の囲みの中の prompt: | の本文）の [名]。fill が全部を値に置き換える
- 埋めない語（literals）: 型の本文の角括弧の語のうち穴でない物（役が返答に書く欄の見本など）。本文の角括弧の語（BRACKETED。
  小文字の [task name] の類いも、行をまたぐ物も数える）は、どれも穴か埋めない語でなければならない
- 出口の語（words）: 原文の役が返す状態の語（DONE・BLOCKED など）と works の語の対応。無い語は推して埋めない

口:
- wrapped_files・pin_of・pin_problems: 包むファイルの sha256 を集める・固定を作る・固定との食い違いをパスの順に名指す
- copy_problems: 版のフォルダを写し元として写せない理由（読まないパスと、版のフォルダに無い借りる一覧のファイル）をパスの順に名指す
- paragraph・para_sha256: 引用を含む行がちょうど 1 行の時、その段落（とその sha256）
- prompt_body: 部品の型の本文
- listed_files: 借りる一覧と部品が名指す、固定に在るべきファイル
- seam_problems: 節ごとの契約の破れ（錨・読み替えの決まり・穴・出口の語・固定に無いファイル）を 1 行ずつ
- contract_problems: pin_problems と seam_problems をつないだ物
- fill・word: 部品の型の穴を埋めた文・出口の語の対応

Claude Code が版のフォルダに置く印（MARKERS）と .DS_Store（IGNORED）は数えない。版のフォルダの外を指すパス（絶対のパス・..）と
symlink は読まずに 1 行で名指す（たどらない）。標準ライブラリだけを使い、works のほかのモジュールを
import しない。層は L3（盤面と受け付けの層。rolekit と同じく .shared/borrow を読む）。
"""
import hashlib
import json
import os
import pathlib
import re
import textwrap

BORROW_DIR = pathlib.Path(__file__).resolve().parent.parent / "borrow"
SEAMS_FILE = "seams.json"          # 節の契約（BORROW_DIR の下）
OVERLAY_FILE = "unattended.md"     # 無人の読み替え（BORROW_DIR の下）
MARKERS = frozenset({".in_use", ".orphaned_at"})   # Claude Code がプラグインのキャッシュの版の置き場に置く印（使っている pid・捨てた時刻）
IGNORED = frozenset({".DS_Store"})
BRACKETED = re.compile(r"\[[^\[\]]+\]")   # 型の本文の角括弧の語（行をまたぐ物も 1 つに数える）。穴か埋めない語でなければ破れ
FENCE = "```"
PROMPT_LINE = "  prompt: |"


def vendored_dir(item: dict, borrow_dir: pathlib.Path = BORROW_DIR) -> pathlib.Path:
    """固定した版の写しの置き場 <borrow_dir>/superpowers/<pin の版>"""
    return borrow_dir / "superpowers" / item["pin"]["version"]


def load_seams(borrow_dir: pathlib.Path = BORROW_DIR) -> dict:
    """節の契約 <borrow_dir>/seams.json を読む"""
    return json.loads((borrow_dir / SEAMS_FILE).read_text(encoding="utf-8"))


OUTSIDE = "版のフォルダの外を指す（絶対のパスか ..）"
LINKED = "symlink が在る（たどらない）"


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _bad_path(src: pathlib.Path, rel: str) -> str | None:
    """rel が版のフォルダの外を指す・途中か先が symlink なら理由（OUTSIDE・LINKED）。読んでよければ None"""
    pure = pathlib.PurePosixPath(rel)
    if not rel or pure.is_absolute() or pathlib.PureWindowsPath(rel).is_absolute() or ".." in pure.parts:
        return OUTSIDE
    at = src
    for part in pure.parts:
        at = at / part
        if at.is_symlink():
            return LINKED
    return None


def _scan(src: pathlib.Path, item: dict) -> tuple[dict[str, str], dict[str, str]]:
    """包むファイルの ({相対パス: sha256}, {読まなかったパス: 理由})。symlink はたどらず、外を指すパスは読まない"""
    files, bad = {}, {}
    for name in item["skills"]:
        rel = f"skills/{name}"
        why = _bad_path(src, rel)
        if why:
            bad[rel] = why
            continue
        root = src / rel
        if not root.is_dir():
            continue
        for here, dirs, names in os.walk(root, followlinks=False):
            for n in [*dirs, *names]:
                p = pathlib.Path(here) / n
                r = p.relative_to(src)
                if MARKERS & set(r.parts) or n in IGNORED:
                    continue
                if p.is_symlink():
                    bad[r.as_posix()] = LINKED
                elif n in names and p.is_file():
                    files[r.as_posix()] = _sha(p)
            dirs[:] = [d for d in dirs if not (pathlib.Path(here) / d).is_symlink() and d not in MARKERS]
    for rel in [*item.get("parts", []), *([item["licence_file"]] if item.get("licence_file") else [])]:
        why = _bad_path(src, rel)
        if why:
            bad[rel] = why
        elif (src / rel).is_file():
            files[rel] = _sha(src / rel)
    return dict(sorted(files.items())), bad


def wrapped_files(src: pathlib.Path, item: dict) -> dict[str, str]:
    """版のフォルダ src の包むファイルの {相対パス（/ 区切り）: sha256}。在る物だけを数える（symlink と外を指すパスは数えない）"""
    return _scan(src, item)[0]


def copy_problems(src: pathlib.Path, item: dict) -> list[str]:
    """版のフォルダ src を写し元として写せない理由の行（パスの順）。読まなかったパス（symlink・外を指すパス）と、版のフォルダに
    無い借りる一覧の SKILL.md・部品。symlink か外を指すパスの下の物は、その上の行が名指しているので数えない"""
    files, bad = _scan(src, item)
    absent = {rel for rel in listed_files(item)
              if rel not in files and not any(rel == k or rel.startswith(f"{k}/") for k in bad)}
    return [f"{rel}: {bad[rel]}" if rel in bad else f"{rel}: 写し元の版のフォルダに無い（借りる一覧 borrow.json の skills・parts が名指す）"
            for rel in sorted(set(bad) | absent)]


def pin_of(src: pathlib.Path, item: dict, version: str, commit: str | None, checked: str) -> dict:
    """版のフォルダ src から固定（pin）を作る"""
    return {"version": version, "commit": commit, "checked": checked, "files": wrapped_files(src, item)}


def listed_files(item: dict) -> list[str]:
    """借りる一覧が名指す包むファイル（各スキルの skills/<名>/SKILL.md と部品 parts）。どれも固定（pin.files）に在るべき物"""
    return [*(f"skills/{s}/SKILL.md" for s in item["skills"]), *item.get("parts", [])]


def pin_problems(src: pathlib.Path, item: dict) -> list[str]:
    """固定の files と版のフォルダ src の包むファイルの食い違いの行（パスの順）。借りる一覧と部品（listed_files）が固定に
    無ければ、それも名指す（固定に在る物は手元に在ることを下の照合が見る）。空なら写しは固定と同じ"""
    pin = item.get("pin")
    if not pin:
        return ["borrow.json の superpowers に pin が無い"]
    want = pin.get("files", {})
    have, bad = _scan(src, item)
    for rel in want:
        why = rel not in bad and _bad_path(src, rel)
        if why:
            bad[rel] = why
    unpinned = {rel for rel in listed_files(item) if rel not in want}
    out = []
    for rel in sorted(set(want) | set(have) | set(bad) | unpinned):
        if rel in bad:
            out.append(f"{rel}: {bad[rel]}")
        elif rel in unpinned:
            out.append(f"{rel}: 借りる一覧（borrow.json の skills・parts）が名指すのに、固定（pin.files）にその sha256 が無い"
                       "（dev/toolset.py vendor で写し直す）")
        elif rel not in have:
            out.append(f"{rel}: 固定に在るのに手元に無い")
        elif rel not in want:
            out.append(f"{rel}: 固定に無いファイルが手元に在る")
        elif want[rel] != have[rel]:
            out.append(f"{rel}: 中身が固定と違う（固定 {want[rel][:12]} / 手元 {have[rel][:12]}）")
    return out


def _lines(text: str) -> list[str]:
    """行に割る。割るのは \n だけ（U+2028・\x0c などでは割らない。段落の sha256 を原文のバイトに沿わせる）"""
    return text.split("\n")


def _hits(text: str, quote: str) -> list[int]:
    return [i for i, line in enumerate(_lines(text)) if quote in line]


def paragraph(text: str, quote: str) -> str | None:
    """quote を含む行がちょうど 1 行の時、その行を含む段落（前後の空白だけの行の手前まで）。0 行・2 行以上なら None"""
    hits = _hits(text, quote)
    if len(hits) != 1:
        return None
    lines = _lines(text)
    lo = hi = hits[0]
    while lo > 0 and lines[lo - 1].strip():
        lo -= 1
    while hi + 1 < len(lines) and lines[hi + 1].strip():
        hi += 1
    return "\n".join(lines[lo:hi + 1])


def para_sha256(text: str, quote: str) -> str | None:
    """paragraph の UTF-8 の sha256。段落が決まらなければ None"""
    para = paragraph(text, quote)
    return None if para is None else hashlib.sha256(para.encode("utf-8")).hexdigest()


def prompt_body(text: str) -> str:
    """型の最初の ``` の囲みの中の「  prompt: |」の次の行から囲みの終わりまでを dedent した物。無ければ ValueError"""
    lines = _lines(text)
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(FENCE))
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith(FENCE))
    except StopIteration:
        raise ValueError("``` の囲みが無い（開きか閉じが欠けている）") from None
    head = [i for i in range(start + 1, end) if lines[i].rstrip() == PROMPT_LINE]
    if not head:
        raise ValueError(f"最初の ``` の囲みに「{PROMPT_LINE.strip()}」の行が無い")
    return textwrap.dedent("\n".join(lines[head[0] + 1:end]) + "\n")


def _read(src: pathlib.Path, rel: str) -> str | None:
    """版のフォルダの中の在るファイルだけを読む（外を指すパス・symlink は読まずに None）"""
    p = src / rel
    return p.read_text(encoding="utf-8") if not _bad_path(src, rel) and p.is_file() else None


def _norm(token: str) -> str:
    """角括弧の語の空白の続きを 1 つの空白にした形（行をまたぐ語を 1 行で書いた literals と比べる）"""
    return " ".join(token.split())


def _stray(text: str, sec: dict) -> list[str]:
    """text の角括弧の語のうち、節の穴でも埋めない語（literals）でもない物（_norm した形・重なりなし・順に並べて）"""
    known = {_norm(t) for t in [*sec.get("placeholders", []), *sec.get("literals", [])]}
    return sorted({_norm(t) for t in BRACKETED.findall(text)} - known)


def _section(seams: dict, seam_id: str) -> dict:
    if seam_id not in seams:
        raise ValueError(f"節 {seam_id} が {SEAMS_FILE} に無い")
    return seams[seam_id]


def contract_problems(src: pathlib.Path, item: dict, seams: dict, overlay_text: str) -> list[str]:
    """固定との食い違い（pin_problems）と節の契約の破れ（seam_problems）をこの順につないだ行。空なら契約が成り立つ"""
    return pin_problems(src, item) + seam_problems(src, item, seams, overlay_text)


def _has_word(text: str, word: str) -> bool:
    """word が語として在るか（前後が英大文字・_ でない。DONE は DONE_WITH_CONCERNS の中に数えない）"""
    return re.search(rf"(?<![A-Z_]){re.escape(word)}(?![A-Z_])", text) is not None


def seam_problems(src: pathlib.Path, item: dict, seams: dict, overlay_text: str) -> list[str]:
    """節ごとの契約の破れの行（錨・読み替えの決まり・穴・出口の語・pin.files に無い節のファイル）。固定との食い違いは
    含めない（それは pin_problems）"""
    out = []
    pinned = (item.get("pin") or {}).get("files", {})
    for sid, sec in seams.items():
        files = sec.get("files", [])
        texts = {}
        for rel in files:
            why = _bad_path(src, rel)
            if why:
                out.append(f"{sid}: {rel} が{why}")
                continue
            if rel not in pinned:
                out.append(f"{sid}: {rel} が pin.files に無い")
            text = _read(src, rel)
            if text is None:
                out.append(f"{sid}: ファイル {rel} が無い（版のフォルダ {src.name} の下）")
            else:
                texts[rel] = text
        if sec.get("use_as") not in ("skill", "prompt"):
            out.append(f"{sid}: use_as {sec.get('use_as')!r} が skill でも prompt でもない")
        for a in sec.get("anchors", []):
            rule, rel, quote = a["rule"], a["file"], a["quote"]
            why = _bad_path(src, rel)
            if rel not in pinned and not why:
                out.append(f"{sid}: 錨 {rule} の {rel} が pin.files に無い")
            text = None if why else texts[rel] if rel in texts else _read(src, rel)
            n = len(_hits(text, quote)) if text is not None else 0
            if why:
                out.append(f"{sid}: 錨 {rule} の {rel} が{why}")
            elif n != 1:
                out.append(f"{sid}: 錨 {rule}「{quote}」が {rel} に" + ("無い" if n == 0 else f" {n} 回在る"))
            elif para_sha256(text, quote) != a.get("para_sha256"):
                out.append(f"{sid}: 錨 {rule}「{quote}」の段落が固定の時と違う")
            if not re.search(rf"^## {re.escape(rule)} ", overlay_text, re.M):
                out.append(f"{sid}: 読み替えの決まり {rule} が {OVERLAY_FILE} に無い")
        if sec.get("use_as") == "prompt" and files and files[0] in texts:
            out += _prompt_problems(sid, sec, src, item, texts[files[0]], files[0])
        for said in sec.get("words", {}):
            if not any(_has_word(t, said) for t in texts.values()):
                out.append(f"{sid}: 語 {said} が {'・'.join(files)} に無い")
    return out


def _prompt_problems(sid: str, sec: dict, src: pathlib.Path, item: dict, text: str, rel: str) -> list[str]:
    """部品の節の穴の破れ: 型の本文に無い穴・穴でも埋めない語でもない角括弧の語・本文に無い埋めない語と、全部の穴をダミーの
    値で埋めた後に残る穴（角括弧の語の行が在れば、同じ語を 2 度名指さないよう埋めて確かめない）"""
    try:
        body = prompt_body(text)
    except ValueError as e:
        return [f"{sid}: {rel} の prompt の型が読めない（{e}）"]
    holes = sec.get("placeholders", [])
    out = [f"{sid}: 穴 {h} が {rel} の prompt の本文に無い" for h in holes if h not in body]
    stray = _stray(body, sec)
    out += [f"{sid}: 穴でも literals でもない角括弧の語 {t} が {rel} の prompt の本文に在る" for t in stray]
    found = {_norm(t) for t in BRACKETED.findall(body)}
    out += [f"{sid}: literals {t} が本文に無い（{rel} の prompt）" for t in sorted({_norm(t) for t in sec.get("literals", [])} - found)]
    if not stray and (item.get("pin") or {}).get("files", {}).get(rel) == _sha(src / rel):   # 固定と違えば上の行が名指している
        try:
            fill(sid, {h: "x" for h in holes}, src, item, {sid: sec})
        except ValueError as e:
            out.append(str(e))
    return out


def fill(seam_id: str, values: dict[str, str], src: pathlib.Path, item: dict, seams: dict | None = None) -> str:
    """部品の節（use_as が prompt）の型の穴を全部 values で置き換えた本文。型の sha256 が固定と合うことを先に確かめる。

    値の鍵が placeholders とちょうど同じでない・sha256 が固定と合わない・置き換えの後に穴でも埋めない語（literals）でもない
    角括弧の語（BRACKETED。小文字の語も）が残る、のどれかで ValueError（名指す）。値の中の角括弧は置き換えも残りの検査も
    しない（穴を除いた本文を検査し、1 回の置き換えで組む）。
    """
    sec = _section(load_seams() if seams is None else seams, seam_id)
    if sec.get("use_as") != "prompt":
        raise ValueError(f"{seam_id}: 部品の節でない（use_as {sec.get('use_as')!r}）")
    holes = list(sec.get("placeholders", []))
    lack, extra = sorted(set(holes) - set(values)), sorted(set(values) - set(holes))
    if lack or extra:
        raise ValueError(f"{seam_id}: 値の鍵が穴と違う（足りない {lack} / 余る {extra}）")
    rel = sec["files"][0]
    p = src / rel
    why = _bad_path(src, rel)
    if why:
        raise ValueError(f"{seam_id}: 型 {rel} が{why}")
    if not p.is_file():
        raise ValueError(f"{seam_id}: 型 {rel} が無い（版のフォルダ {src.name} の下）")
    want = (item.get("pin") or {}).get("files", {}).get(rel)
    have = _sha(p)
    if want != have:
        raise ValueError(f"{seam_id}: 型 {rel} の sha256 が固定と違う（固定 {str(want)[:12]} / 手元 {have[:12]}）")
    body = prompt_body(p.read_text(encoding="utf-8"))
    if holes:
        pat = re.compile("|".join(re.escape(h) for h in sorted(holes, key=len, reverse=True)))
        left = _stray(pat.sub("", body), sec)
        body = pat.sub(lambda m: values[m.group(0)], body)
    else:
        left = _stray(body, sec)
    if left:
        raise ValueError(f"{seam_id}: 埋めていない穴 {' '.join(left)} が {rel} の prompt の本文に残る")
    return body


def word(seam_id: str, said: str, seams: dict | None = None) -> str:
    """原文の出口の語 said を works の語に読む。対応に無い語は ValueError（推して埋めない）"""
    words = _section(load_seams() if seams is None else seams, seam_id).get("words", {})
    if said not in words:
        raise ValueError(f"{seam_id}: 出口の語 {said} の対応が無い（推して埋めない）")
    return words[said]
