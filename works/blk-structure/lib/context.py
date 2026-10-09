"""構造の目に見せる対象の決まりと考えの材料（計画 2026-10-09-clean-whole の Task 2.3。段 A が structure.json に置く）。

入力の契約は増やさない（3 つのまま）。地図と柵の表は対象の根の追跡されたファイルから、決まった名で機械が探す（core の
concepthome・conceptfence。対象に無ければ何も足さない。作らない）。

- rules(root, policy_path) -> {policy: {path, text, reason}, maps, reason}: 方針の文書の中身（入力 policy_path。空なら無し）と、
  根の地図の文書（core の design.repo_map と同じ探し方を呼ぶ。写さない）
- concepts(root, paths, found) -> {rows, places}: 単位のパスに当たる考えの地図の行（表の知ってよい所か住処が単位のパスに当たる・
  柵の語が単位のファイルに在る・地図の行が単位のパスを字で名指す、のどれか）と、単位のファイルの知る場所の数（表が在れば）。
  found は find(root) の返り（単位ごとに探し直さない）
- find(root) -> {tables, maps, reason}: 対象の柵の表と地図を探す（投げない）

どれも投げない（読めない物は reason に 1 文で残し、目は残りで判じる。線を止めない）。
"""
from __future__ import annotations

import fnmatch
import pathlib
import re
import sys

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
import concepthome  # noqa: E402
import conceptfence  # noqa: E402

TEXT_CAP = 6000   # 方針の文書と地図の 1 行の字の上限（目の指示書を小さく保つ。切ったら印を付ける）
HEADING = re.compile(r"^### `([^`]+)`")


def _cut(text: str) -> str:
    return text if len(text) <= TEXT_CAP else text[:TEXT_CAP] + f"\n…（{len(text) - TEXT_CAP} 字を切った）"


def rules(root, policy_path: str) -> dict:
    root = pathlib.Path(root)
    out = {"policy": {"path": policy_path or "", "text": "", "reason": ""}, "maps": "", "reason": ""}
    if policy_path:
        p = pathlib.Path(policy_path)
        p = p if p.is_absolute() else root / p
        try:
            out["policy"]["text"] = _cut(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            out["policy"]["reason"] = f"方針の文書が読めない: {e}"
    try:
        import design   # 根の地図の文書の探し方の住処（重い import なので使う時だけ）
        out["maps"] = _cut(design.repo_map(root)[0])
    except Exception as e:   # 地図が読めなくても目は残りで判じる（線を止めない）
        out["reason"] = f"根の地図の文書が読めない: {type(e).__name__}: {e}"
    return out


def _sections(md: str) -> dict:
    """地図の {id: 見出しから次の見出し（### か ## か ---）の前までの文}"""
    out, cur, buf = {}, None, []
    for line in md.splitlines():
        m = HEADING.match(line)
        if m or line.startswith("## ") or line.strip() == "---":
            if cur is not None:
                out[cur] = "\n".join(buf).rstrip()
            cur, buf = (m.group(1), [line]) if m else (None, [])
            continue
        if cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).rstrip()
    return out


def find(root) -> dict:
    """{tables: [(持ち主のフォルダ, 表)], maps: [(持ち主のフォルダ, 地図のパス, {id: 行})], reason}"""
    root = pathlib.Path(root)
    tables, bad = conceptfence.tables(root)
    names, why = concepthome.tracked_names(root)
    maps = []
    for name in concepthome.pick_maps(names)[0]:
        try:
            maps.append((concepthome.base_of(name), name, _sections((root / name).read_text(encoding="utf-8"))))
        except (OSError, UnicodeDecodeError) as e:
            bad.append(f"{name}: {e}")
    if why and not any(b.startswith("木を読めなかった") for b in bad):
        bad.append(f"木を読めなかった: {why}")
    return {"tables": tables, "maps": maps, "reason": " / ".join(bad)}


def _rel(path: str, base: str):
    if not base:
        return path
    return path[len(base) + 1:] if path.startswith(base + "/") else None


def concepts(root, paths, found: dict) -> dict:
    rows, places = [], []
    hit = {}   # (持ち主のフォルダ, 考えの id) → 当たった訳
    for base, table in found.get("tables") or []:
        rel = [r for r in (_rel(p, base) for p in paths) if r is not None]
        for k, v in (table.get("concepts") or {}).items():
            for f in v.get("fences") or []:
                if any(fnmatch.fnmatch(r, g) for r in rel for g in f.get("allowed") or []):
                    hit.setdefault((base, k), True)
        try:
            got = conceptfence.places(root, base, table, paths)
        except Exception:   # 柵の語の形が壊れた表でも、地図の行と実測で判じる
            got = []
        places += got
        for g in got:
            hit.setdefault((base, g["concept"]), True)
    for base, name, sections in found.get("maps") or []:
        rel = [r for r in (_rel(p, base) for p in paths) if r is not None]
        for k, text in sections.items():
            if (base, k) in hit or any(r in text for r in rel):
                rows.append({"id": k, "map": name, "text": _cut(text)})
    return {"rows": rows, "places": places}
