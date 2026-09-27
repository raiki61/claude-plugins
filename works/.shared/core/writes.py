"""作業ツリーの書き込みの出どころの突き合わせ（書く役の受け付け: blk-fix の fix-accept・tdd-step、blk-refix の手直しの受け付け）。

包み（claude-adapter）の PostToolUse:Edit|Write|NotebookEdit のフック（record-write.py）が、書いた後の中身の sha を
adapter.writes_path（読んだ記録と同じ置き場の writes.jsonl）に 1 行ずつ残す。ここは版からの変更を、その記録と役の申告
（返答の欄 bash_writes: [{path, why}]）に突き合わせる。
射程: 見るのは「今の中身と同じ中身を、編集の道具が書いたか役が申告したことがあるか」まで。Bash で書いた後に同じ中身を
Edit で書き直した物は区別しない（出どころの全部は証さない）。
- writes.jsonl が無い run（包みが無い起動。包みは印のある起動の前に空のファイルを作る）は拒否の理由にせず通し、NO_RECORD を
  返す（呼び手が盤面の trace に NO_RECORD_OP で 1 行残し、報告に出る）
- 通った申告は記録に tool_name "declared" の行で足す（後ろの受け付け——fix の後の refix など——が同じ申告を求めない）
- .archon/ の下は数えない（check_pack_copy の持ち場）
標準ライブラリだけ。
"""
import hashlib
import json
import os
import pathlib
import posixpath
import sys
import time

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import adapter  # noqa: E402
from leftovers import git_names  # noqa: E402

FIELD = "bash_writes"
MIN_WHY = 10
ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["path", "why"],
    "properties": {"path": {"type": "string", "minLength": 1}, "why": {"type": "string", "minLength": MIN_WHY}},
}
BASH_WRITES_SCHEMA = {"type": "array", "items": ITEM_SCHEMA}
SKIP = (".archon/",)
NO_RECORD = "書き込みの記録が無い run（包みが無い起動）——書き込みの出どころを突き合わせずに通した"
NO_RECORD_OP = "writes_unrecorded_run"   # 盤面の trace の行（報告が数える）
LEFT_OP = "writes_left"                  # 拒まずに残した記録の無い変更（欄 bash_writes を持たない手直しの役）
REJECT = ("作業ツリーの変更に、書き込みの記録（Edit・Write）も申告（bash_writes）も無い——Edit・Write で書き直すか、返答の "
          "bash_writes にパスと、Bash で書いた理由（実行の権限・バイナリ・大量の機械的な置き換え）を書け（射程: 見るのは今の中身を"
          "編集の道具が書いたか申告したかまでで、Bash で書いた後に同じ中身を Edit で書き直した物は区別しない）: ")


def sink(repo) -> pathlib.Path:
    return adapter.writes_path(repo)


def pop(reply: dict) -> tuple:
    """(欄 bash_writes を外した返答, 申告の一覧)"""
    reply = dict(reply)
    return reply, reply.pop(FIELD, None) or []


def shape_problems(items) -> list:
    if not isinstance(items, list):
        return [f"{FIELD} は {{path, why}} の配列"]
    out = []
    for i in items:
        if not isinstance(i, dict) or not isinstance(i.get("path"), str) or not i["path"].strip():
            out.append(f"{FIELD} の行にパスが無い（{i!r:.120}）")
        elif not isinstance(i.get("why"), str) or len(i["why"].strip()) < MIN_WHY:
            out.append(f"{FIELD} の {i['path']} に理由（{MIN_WHY} 字以上）が無い")
        elif _rel(i["path"]) is None:
            out.append(f"{FIELD} の {i['path']} はリポジトリの根からの相対パスでない")
    return out


def _rel(p: str):
    n = posixpath.normpath(p.strip())
    return None if n.startswith("/") or n == ".." or n.startswith("../") else n


def base_rev(b, given: str = "") -> str:
    """突き合わせの起点の版: 盤面の state.inputs.review_rev（start が固めた修正前の版）。無ければ given、それも空なら HEAD"""
    return (b.state.get("inputs") or {}).get("review_rev") or given or "HEAD"


def changed(repo, rev: str) -> list:
    """版 rev からの変更（追跡中の差分と消した物、git が無視しない未追跡のファイル。リポジトリの根から）"""
    return sorted(set(git_names(repo, "diff", "--name-only", "--no-renames", rev, "--", ":/"))
                  | set(git_names(repo, "ls-files", "--others", "--exclude-standard", "--full-name", "--", ":/")))


def _sha(path: str):
    try:
        return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    except OSError:
        return None   # 消した（か読めない）ファイル


def records(log: pathlib.Path) -> dict:
    """実パス → 記録に在る中身の sha の集まり（消した申告は None）"""
    out = {}
    try:
        text = log.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for ln in text.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("path"), str):
            out.setdefault(os.path.realpath(r["path"]), set()).add(r.get("file_sha"))
    return out


def unrecorded(repo, paths, log: pathlib.Path, declared=()) -> list:
    """paths のうち、今の中身の記録も申告も無い物"""
    rec = records(log)
    decl = {_rel(d["path"]) for d in declared}
    out = []
    for p in paths:
        if p in decl or p.startswith(SKIP):
            continue
        path = os.path.join(str(repo), p)
        real = os.path.realpath(path)
        if os.path.islink(path) or _sha(real) not in rec.get(real, ()):   # symlink は編集の道具では作れない（申告が要る）
            out.append(p)
    return out


def keep_declared(log: pathlib.Path, repo, declared) -> None:
    rows = [json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool_name": "declared",
                        "path": os.path.realpath(os.path.join(str(repo), _rel(d["path"]))),
                        "file_sha": _sha(os.path.join(str(repo), _rel(d["path"]))), "why": d["why"].strip()},
                       ensure_ascii=False) for d in declared]
    if rows:
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n".join(rows) + "\n")


def check(reply: dict, repo, paths, log: pathlib.Path, *, strict: bool = True) -> dict:
    """返りは {reply（欄 bash_writes を外した返答）, problems, note, left}。
    strict でなければ記録の無い変更は拒まずに left に返す（欄を持たない役）"""
    reply, items = pop(reply)
    bad = shape_problems(items)
    if bad:
        return {"reply": reply, "problems": bad, "note": "", "left": []}
    if not log.is_file():
        return {"reply": reply, "problems": [], "note": NO_RECORD, "left": []}
    left = unrecorded(repo, paths, log, items)
    if left and strict:
        return {"reply": reply, "problems": [REJECT + ", ".join(left)], "note": "", "left": left}
    keep_declared(log, repo, items)
    return {"reply": reply, "problems": [], "note": "", "left": left}


def trace(b, node: str, got: dict) -> None:
    """記録の無い run と、拒まずに残した変更を盤面の trace に 1 行（報告が数える）"""
    if got["note"]:
        b.trace(NO_RECORD_OP, node=node, note=got["note"])
    if got["left"]:
        b.trace(LEFT_OP, node=node, paths=got["left"])
