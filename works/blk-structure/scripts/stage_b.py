# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""直しの後の実測（段 B。計画 2026-10-09-clean-whole の Task 2.5）。直しの前の版（INPUTS_BASE_REV）と対象の根（INPUTS_ROOT。空なら
cwd）の今の作業ツリーの差分を、同じフォルダの measure.py の差分の形（--diff。コマンド 1 つの口。import しない）と、対象の柵の表
（在れば。core の conceptfence.scan_change）で測り、$ARTIFACTS_DIR/structure/after.json に書く。

after.json: {status: ok|failed, reason, base_rev, changed: [パス], tables: [表のパス], fence_up: [{concept, what, path, before, after}],
new_names: [{name, sites}], dup_blocks_added: int, timing: {wall_s}}
- fence_up は柵の表を持つ対象だけ（表の無い対象は空。表を作らない）。住処の外で知る場所の行が増えた所
- new_names は差分が新しく持ち込んだ大文字の名と現れる場所の数、dup_blocks_added は差分で増えた写しの塊の数（ファイルごとの増えの和）
- 差分の前の像は、対象を変えない一時の clone（--shared。対象の .git は書き換えない）を直しの前の版で取り出した物。差分は
  `git diff --binary <版>` と、まだ追跡されていないファイルの足しの patch
- 実測が落ちても線を止めない（status: failed と reason。0 で終える）
- {"after_file"} を 1 行出して 0。ARTIFACTS_DIR が欠けた（空も欠け）時だけ、標準エラーに名前を出して 2
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
_CORE = Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
import concepthome  # noqa: E402
import conceptfence  # noqa: E402

BASE_ENV = "INPUTS_BASE_REV"
ROOT_ENV = "INPUTS_ROOT"
INPUTS = (BASE_ENV, ROOT_ENV)   # 裁定 TA16: 読む INPUTS_* の組
ARTIFACTS_ENV = "ARTIFACTS_DIR"
OUT_DIR = "structure"
AFTER_FILE = "after.json"
MEASURE = Path(__file__).resolve().parent / "measure.py"
REASON_TAIL = 2000


def _git(repo: Path, *args: str, ok=(0,)) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                       stdin=subprocess.DEVNULL)
    if p.returncode not in ok:
        raise RuntimeError(f"git {' '.join(args[:2])} が終了コード {p.returncode}: {p.stderr.strip()[-REASON_TAIL:]}")
    return p.stdout


def patch_of(root: Path, base: str) -> tuple[str, list]:
    """(base と今の作業ツリーの patch, 変わったパス)。まだ追跡されていないファイルは /dev/null からの足しの patch を足す"""
    text = _git(root, "diff", "--binary", "--no-renames", base, "--")
    changed = [p for p in _git(root, "diff", "--name-only", "-z", "--no-renames", base, "--").split("\0") if p]
    for p in [p for p in _git(root, "ls-files", "-z", "--others", "--exclude-standard").split("\0") if p]:
        text += _git(root, "diff", "--binary", "--no-index", "--", "/dev/null", p, ok=(0, 1))
        changed.append(p)
    return text, list(dict.fromkeys(changed))


def measure_diff(root: Path, base: str, patch: str, paths: list) -> dict:
    """直しの前の版の一時の clone に patch を当てて measure.py --diff で測った出力"""
    with tempfile.TemporaryDirectory(prefix="works-stage-b-") as tmp:
        clone = Path(tmp) / "before"
        _git(Path(tmp), "clone", "-q", "--shared", "--no-checkout", str(root), str(clone))
        _git(clone, "-c", "advice.detachedHead=false", "checkout", "-q", base)
        pf = Path(tmp) / "fix.patch"
        pf.write_text(patch, encoding="utf-8")
        p = subprocess.run([sys.executable, str(MEASURE), "--paths", *paths, "--repo", str(clone), "--diff", str(pf)],
                           cwd=str(clone), capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            raise RuntimeError((p.stderr.strip() or f"measure.py が終了コード {p.returncode}")[-REASON_TAIL:])
        return json.loads(p.stdout)


def summarize(diff: dict) -> tuple[list, int]:
    """(新しい名 [{name, sites}], 増えた写しの塊の数)"""
    names = [{"name": n.get("name"), "sites": len(n.get("sites") or [])} for n in diff.get("names") or [] if isinstance(n, dict)]
    added = 0
    for e in diff.get("paths") or []:
        d = ((e or {}).get("duplicates") or {}).get("delta")
        if isinstance(d, int) and d > 0:
            added += d
    return names, added


def run(root: Path, base: str) -> dict:
    doc = {"status": "ok", "reason": "", "base_rev": base, "changed": [], "tables": [], "fence_up": [], "new_names": [],
           "dup_blocks_added": 0}
    if not base:
        doc.update(status="failed", reason=f"{BASE_ENV} が空（直しの前の版が無い）")
        return doc
    try:
        _git(root, "rev-parse", "--verify", "-q", f"{base}^{{commit}}")
        patch, changed = patch_of(root, base)
    except RuntimeError as e:
        doc.update(status="failed", reason=str(e))
        return doc
    doc["changed"] = changed
    found, bad = conceptfence.tables(root)
    doc["tables"] = ["/".join(x for x in (b, concepthome.TABLE_NAME) if x) for b, _ in found]
    problems = list(bad)
    try:
        for b, table in found:
            doc["fence_up"] += conceptfence.scan_change(root, base, table, b)
    except (subprocess.CalledProcessError, OSError) as e:
        problems.append(f"柵の数えが落ちた: {e}")
    if changed and patch.strip():
        try:
            doc["new_names"], doc["dup_blocks_added"] = summarize(measure_diff(root, base, patch, changed).get("diff") or {})
        except (RuntimeError, ValueError, OSError) as e:
            problems.append(f"差分の実測が落ちた: {e}")
    if problems:
        doc.update(status="failed", reason=" / ".join(problems))
    return doc


def main() -> int:
    art = os.environ.get(ARTIFACTS_ENV)
    if not art:
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    out_dir = Path(art) / OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    root = Path(os.environ.get(ROOT_ENV) or ".").resolve()
    doc = run(root, os.environ.get(BASE_ENV, "").strip())
    doc["timing"] = {"wall_s": round(time.monotonic() - t0, 3)}
    after = out_dir / AFTER_FILE
    after.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"after_file": str(after)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
