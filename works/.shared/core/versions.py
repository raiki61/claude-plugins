"""run ごとの版の控え versions.json（持ち主 2026-09-28: run の記録は Archon の DB と盤面が正本。版だけは誰も残していないので、
run と同じ置き場 <ARTIFACTS_DIR>/versions.json に 1 つ書き、Archon の記録の隣で引けるようにする）。層 L1（works の物を何も知らない）。

- snapshot(pack, env=os.environ, *, run_id="", settings=None) -> dict:
  {schema, run_id, at, works: {source, version, pack_sha256, files}, graphloops_copy, borrowed, archon, claude_code,
   model, settings, python, platform, unknown}
  - works.source: dev の殻が pack の写しに置く出どころの控え <pack>/.works-source.json（{rev, dirty, from, version}。
    元の works が git で追跡されていなければ rev・dirty は null で、version は元の .claude-plugin/plugin.json の version）
  - works.version: <pack>/VERSION の 1 行目（まだ無い版もある）
  - works.pack_sha256・files: 走った pack の中身そのものの印（出どころの控え・__pycache__・*.pyc・.DS_Store を除く、
    相対パスとファイルの sha256 を並べた sha256）。出どころが分からない写しでも中身で突き合わせられる
  - graphloops_copy: <pack>/.shared/core/COPIED_FROM の 1 行目
  - borrowed: $CLAUDE_CONFIG_DIR/.works-toolset.json（借りた物の版と sha256。dev/toolset.py が書く）
  - archon・claude_code: env の WORKS_ARCHON_VERSION・WORKS_CLAUDE_VERSION（開発の殻 archon.sh が隔離の前に決めて渡す）
  - model: 全体の模型の要求 {value, from}。value は env の WORKS_DEV_MODEL（明示）か WORKS_MODEL_RESOLVED（archon.sh が
    既定を解いた値）、from は archon.sh が渡す出どころ WORKS_MODEL_FROM。節ごとの模型は包みの起動の記録（adapter.launch_row）
  - settings: 呼び手が渡した run の設定の写し（中身は読まない。線の start は切る機能・入れる機能 {features_off: [語], features_on: [語]} を渡す。
    渡されなければ {}）。run どうしを比べる時に版・模型と並べて引く
  - 分からない値は null にし、unknown[鍵] に理由を書く（推測で埋めない・黙って落とさない）
- write(artifacts_dir, doc) -> Path: <artifacts_dir>/versions.json に一時ファイルから os.replace で書く
"""
import datetime
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Mapping

SCHEMA = 1
FILE = "versions.json"
SOURCE_FILE = ".works-source.json"
TOOLSET_RECORD = ".works-toolset.json"
ENV_ARCHON = "WORKS_ARCHON_VERSION"
ENV_CLAUDE = "WORKS_CLAUDE_VERSION"
ENV_MODEL = ("WORKS_DEV_MODEL", "WORKS_MODEL_RESOLVED")
ENV_MODEL_FROM = "WORKS_MODEL_FROM"
_SKIP_NAMES = frozenset({"__pycache__", ".DS_Store", SOURCE_FILE})


def _files(pack: Path):
    for p in sorted(pack.rglob("*")):
        rel = p.relative_to(pack)
        if any(part in _SKIP_NAMES for part in rel.parts) or p.suffix == ".pyc" or not p.is_file():
            continue
        yield rel.as_posix(), p


def pack_digest(pack: Path) -> str:
    """pack の中身の印（相対パスと中身の sha256 の並びの sha256）"""
    h = hashlib.sha256()
    for rel, p in _files(Path(pack)):
        h.update(f"{rel}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n".encode("utf-8"))
    return h.hexdigest()


def _json_object(path: Path, what: str, unknown: dict, key: str):
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        unknown[key] = f"{what} が無い（{path}）"
        return None
    except (OSError, ValueError) as e:
        unknown[key] = f"{what} が読めない（{path}: {type(e).__name__}）"
        return None
    if not isinstance(doc, dict):
        unknown[key] = f"{what} が JSON のオブジェクトでない（{path}）"
        return None
    return doc


def _first_line(path: Path, what: str, unknown: dict, key: str):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        unknown[key] = f"{what} が無い（{path}）"
        return None
    line = text.splitlines()[0].strip() if text.strip() else ""
    if not line:
        unknown[key] = f"{what} が空（{path}）"
        return None
    return line


def _env(env: Mapping[str, str], name: str, unknown: dict, key: str):
    value = (env.get(name) or "").strip()
    if not value:
        unknown[key] = f"env の {name} が空か無い（開発の殻 archon.sh を通さずに起こした run か、版を引けなかった）"
        return None
    return value


def _model(env: Mapping[str, str], unknown: dict):
    value = next((v for v in ((env.get(n) or "").strip() for n in ENV_MODEL) if v), "")
    if not value:
        unknown["model"] = (f"env の {'・'.join(ENV_MODEL)} が空か無い（開発の殻 archon.sh を通さずに起こした run。"
                            "模型は Archon の設定か CLI の既定）")
        return None
    source = (env.get(ENV_MODEL_FROM) or "").strip()
    if not source:
        unknown["model.from"] = f"env の {ENV_MODEL_FROM} が空か無い（明示か既定かが分からない）"
    return {"value": value, "from": source or None}


def snapshot(pack: Path, env: Mapping[str, str] = os.environ, *, run_id: str = "", settings: dict | None = None) -> dict:
    pack = Path(pack)
    unknown: dict = {}
    source = _json_object(pack / SOURCE_FILE, "pack の出どころの控え", unknown, "works.source")
    files = list(_files(pack))
    cfg = (env.get("CLAUDE_CONFIG_DIR") or "").strip()
    if cfg:
        borrowed = _json_object(Path(cfg) / TOOLSET_RECORD, "借りた物の記録", unknown, "borrowed")
    else:
        borrowed = None
        unknown["borrowed"] = "env の CLAUDE_CONFIG_DIR が無い"
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "works": {"source": source,
                  "version": _first_line(pack / "VERSION", "VERSION", unknown, "works.version"),
                  "pack_sha256": pack_digest(pack), "files": len(files)},
        "graphloops_copy": _first_line(pack / ".shared" / "core" / "COPIED_FROM", "graphloops の写しの控え", unknown,
                                       "graphloops_copy"),
        "borrowed": borrowed,
        "archon": _env(env, ENV_ARCHON, unknown, "archon"),
        "claude_code": _env(env, ENV_CLAUDE, unknown, "claude_code"),
        "model": _model(env, unknown),
        "settings": dict(settings or {}),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "unknown": unknown,
    }


def write(artifacts_dir: Path, doc: dict) -> Path:
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    dest = artifacts_dir / FILE
    tmp = artifacts_dir / f".{FILE}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return dest
