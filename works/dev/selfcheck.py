"""works/dev/selfcheck.py — 柵の軽い自己点検（変異の腕の軽い段。開発の殻。標準ライブラリだけ）。

  python3 dev/selfcheck.py                 # 全部の腕を撃つ（腕ごとに写しを 1 つ作り、名指しの試験 1 本だけを回す）
  python3 dev/selfcheck.py --check         # 字列と名指しの試験が今の版に在るかだけ（写さない・回さない。速い段の test_selfcheck が当てる）
  python3 dev/selfcheck.py --only ro1,fg2  # その腕だけ
  （--root <pack の根>・--arms <腕の一覧> は試験の偽の pack のため。既定は works/ と works/tests/mutations.json）

腕の一覧 tests/mutations.json の 1 行は、柵 1 か所の故意の欠陥（file の中にちょうど 1 か所在る old を new に置き換える）と、
それを捕まえるはずの試験 1 本（本流 tests/mutations.json の行の型。決定 C16。本流の実行器 tests/mutate.py の軽い段で、
suite・expect・marker・並びの実行・結果の持ち越しは持たない）。順は:
1. 写しの置き場 ${WORKS_DEV_HOME:-$TMPDIR/works-dev}/selfcheck を dev/guard.sh の works_dev_refuse_claude_tmp に当てる
   （Claude Code の一時フォルダの下なら何も写さずに 2）。
2. 壊さない写しで、名指しの試験を全部 1 回だけ回す（control）。赤か、当たった本数が違えば CONTROL_RED で 1——赤い試験の
   腕は何の証拠にもならない。
3. 腕ごとに pack を写し、old を new に置き換えて、`nice -n 19 sh tests/run.sh -k <モジュール>.<クラス>.<試験>` を回す。
   CAUGHT = 当たった試験がちょうど 1 本で、その試験が FAIL（assert で落ちた）か、例外（ERROR）の一番奥の行が試験の本文
   （試験が結果を読んで柵の欠けを見た。`st["stop"]` の KeyError など）。NOT_CAUGHT = 緑のまま・pack のコードの中の例外で
   落ちた（柵でなく土台が壊れた）・当たりが 1 本でない。NOT_INJECTED = old がちょうど 1 か所でない（コードが変わって腕が古い）。
4. 腕ごとに 1 行と、最後に `SELFCHECK caught=<n>/<腕の数> … total=<秒> 秒`。CAUGHT でない腕が 1 本でも在れば 1。
NOT_CAUGHT は、その試験が名乗る柵を守っていない（試験の穴）という発見で、腕を弱めて緑にしない。
期限は足さない（試験の待ちの上限を持たない。Global Constraints）。

終了コード: 0 = 撃った腕が全部 CAUGHT（--check なら全部の腕が今の版に合う）/ 1 = そうでない / 2 = 一覧が読めない・置き場の柵
"""
import argparse
import ast
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIELDS = ("id", "title", "file", "old", "new", "tests")
COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")
RAN = re.compile(r"^Ran (\d+) tests? in ", re.MULTILINE)


class RegistryError(Exception):
    """腕の一覧が読めない・行の形が違う（文は 1 行）"""


def load_arms(path) -> list:
    """腕の一覧（{about, arms, dropped} の arms）。形の違いは RegistryError"""
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RegistryError(f"腕の一覧を読めない（{path}: {e}）") from None
    arms = doc.get("arms") if isinstance(doc, dict) else None
    if not isinstance(arms, list):
        raise RegistryError(f"腕の一覧に arms の配列が無い（{path}）")
    for i, a in enumerate(arms):
        if not isinstance(a, dict) or any(not isinstance(a.get(k), str) or not a[k] for k in FIELDS if k != "tests"):
            raise RegistryError(f"腕 {i} の欄が足りない（{', '.join(FIELDS)}。文字列は空でない）")
        t = a.get("tests")
        if not (isinstance(t, dict) and len(t) == 1 and all(isinstance(v, list) and len(v) == 1 and isinstance(v[0], str)
                                                             for v in t.values())):
            raise RegistryError(f"腕 {a['id']} の tests は試験ちょうど 1 本（{{\"tests/<モジュール>.py\": [\"<クラス>.<試験>\"]}}）")
    return arms


def focused(a: dict) -> tuple:
    """腕の名指しの試験 (ファイル, クラス, 試験, -k の型 <モジュール>.<クラス>.<試験>)"""
    (path, (name,)), = a["tests"].items()
    cls, _, meth = name.partition(".")
    return path, cls, meth, f"{pathlib.PurePosixPath(path).stem}.{name}"


def _methods(src: pathlib.Path, cls: str):
    """src のクラス cls に書いた関数の名前（クラスが無い・読めなければ None）"""
    try:
        tree = ast.parse(src.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return None


def check(root, arms: list) -> list:
    """腕が今の版に合うか。問題の文の一覧（空なら揃っている）: id の重なり・old がちょうど 1 か所でない・old と new が同じ・
    名指しの試験がクラスに無い・-k の型が同じクラスのほかの試験にも当たる（名前の頭が同じ）"""
    root = pathlib.Path(root)
    out, seen = [], set()
    for a in arms:
        aid = a["id"]
        if aid in seen:
            out.append(f"{aid}: id が重なる")
        seen.add(aid)
        if a["old"] == a["new"]:
            out.append(f"{aid}: old と new が同じ")
        try:
            n = (root / a["file"]).read_text(encoding="utf-8").count(a["old"])
        except OSError:
            n = None
        if n != 1:
            out.append(f"{aid}: {a['file']} に old が {'無い（ファイルが読めない）' if n is None else f'{n} か所'}"
                       "（ちょうど 1 か所。コードが変わったなら腕を直す）")
        path, cls, meth, _ = focused(a)
        names = _methods(root / path, cls)
        if names is None or meth not in names:
            out.append(f"{aid}: 名指しの試験 {path}::{cls}.{meth} が無い")
        elif any(m != meth and m.startswith(meth) for m in names):
            out.append(f"{aid}: -k {cls}.{meth} が同じクラスのほかの試験にも当たる（名前の頭が同じ）")
    return out


def home() -> pathlib.Path:
    base = os.environ.get("WORKS_DEV_HOME") or os.path.join(tempfile.gettempdir(), "works-dev")
    return pathlib.Path(base) / "selfcheck"


def refuse_claude_tmp(root: pathlib.Path, place: pathlib.Path) -> str:
    """dev/guard.sh の works_dev_refuse_claude_tmp に当てる。止めるなら理由の文（通れば ""）"""
    r = subprocess.run(["sh", "-c", '. "$1"; works_dev_refuse_claude_tmp selfcheck.py 写しの置き場 "$2"', "sh",
                        str(root / "dev" / "guard.sh"), str(place)], capture_output=True, text=True, encoding="utf-8", check=False)
    return "" if r.returncode == 0 else (r.stderr.strip() or f"guard.sh が終了コード {r.returncode}")


def _copy(root: pathlib.Path, base: pathlib.Path) -> tuple:
    td = tempfile.TemporaryDirectory(prefix="selfcheck-", dir=base)
    dest = pathlib.Path(td.name) / root.name
    shutil.copytree(root, dest, symlinks=True, ignore=COPY_IGNORE)
    return td, dest


def run_tests(pack: pathlib.Path, patterns: list) -> tuple:
    """写しの中で `nice -n 19 sh tests/run.sh -k …` を回す。(終了コード, 標準出力と標準エラー)。段の選び WORKS_TESTS は外す"""
    env = {k: v for k, v in os.environ.items() if k != "WORKS_TESTS"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    argv = ["nice", "-n", "19", "sh", "tests/run.sh"]
    for p in patterns:
        argv += ["-k", p]
    r = subprocess.run(argv, cwd=pack, env=env, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, check=False)
    return r.returncode, r.stdout + r.stderr


def ran(out: str):
    m = RAN.findall(out)
    return int(m[-1]) if m else None


def _named(out: str, kind: str, cls: str, meth: str) -> bool:
    """unittest の要約の行 `FAIL: <試験> (<モジュール>.<クラス>[.<試験>])` に、その試験が在るか"""
    return any(ln.startswith(f"{kind}: {meth} (") and f".{cls}" in ln for ln in out.splitlines())


FRAME = re.compile(r'^\s*File "(.+)", line \d+, in (\S+)$', re.MULTILINE)


def _error_in_test_body(out: str, path: str, meth: str) -> bool:
    """ERROR の traceback の一番奥の行が、名指しの試験（path の meth）の本文か。試験が結果を読んで柵の欠けを見た
    （`st["stop"]` の KeyError など）なら真。pack のコードの中で出た例外は偽（柵でなく土台が壊れた）"""
    block = out.split(f"ERROR: {meth} (", 1)[-1].split("\n" + "=" * 70, 1)[0]
    frames = FRAME.findall(block)
    return bool(frames) and frames[-1][0].endswith("/" + path) and frames[-1][1] == meth


def classify(a: dict, code: int, out: str) -> tuple:
    """(状態, 理由)。CAUGHT はちょうど 1 本に当たり、終了コードが 0 でなく、その試験が FAIL（assert）か、試験の本文の行で
    例外（ERROR）になった時だけ"""
    path, cls, meth, _ = focused(a)
    n = ran(out)
    if n != 1:
        return "NOT_CAUGHT", f"-k が {n if n is not None else '0（走らない）'} 本に当たった（ちょうど 1 本のはず）"
    if code == 0:
        return "NOT_CAUGHT", "壊しても試験が緑のまま（その試験はこの柵を守っていない）"
    if _named(out, "FAIL", cls, meth):
        return "CAUGHT", ""
    if _named(out, "ERROR", cls, meth):
        if _error_in_test_body(out, path, meth):
            return "CAUGHT", ""
        return "NOT_CAUGHT", "試験が pack のコードの中の例外（ERROR）で落ちた（柵でなく土台が壊れた。腕の置き換えを見直す）"
    return "NOT_CAUGHT", f"終了コード {code} だが試験の FAIL の行が無い"


def _tail(out: str, n: int = 12) -> str:
    return "\n".join(f"    {ln}" for ln in out.strip().splitlines()[-n:])


def shoot(root: pathlib.Path, base: pathlib.Path, a: dict) -> tuple:
    """腕 1 本を写しに当てて名指しの試験を回す。(状態, 理由, 出力)"""
    td, pack = _copy(root, base)
    try:
        target = pack / a["file"]
        text = target.read_text(encoding="utf-8")
        n = text.count(a["old"])
        if n != 1:
            return "NOT_INJECTED", f"{a['file']} に old が {n} か所（ちょうど 1 か所のはず。腕が古い）", ""
        target.write_text(text.replace(a["old"], a["new"], 1), encoding="utf-8")
        code, out = run_tests(pack, [focused(a)[3]])
        status, why = classify(a, code, out)
        return status, why, out
    finally:
        td.cleanup()


def control(root: pathlib.Path, base: pathlib.Path, arms: list) -> tuple:
    """壊さない写しで名指しの試験を全部 1 回だけ回す。(緑か, 理由, 出力)"""
    pats = sorted({focused(a)[3] for a in arms})
    td, pack = _copy(root, base)
    try:
        code, out = run_tests(pack, pats)
    finally:
        td.cleanup()
    n = ran(out)
    if code != 0 or n != len(pats):
        return False, f"終了コード {code}・当たった試験 {n} 本（名指しは {len(pats)} 本）", out
    return True, "", out


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="selfcheck.py", description="柵の軽い自己点検（変異の腕の軽い段）")
    ap.add_argument("--check", action="store_true", help="字列と名指しの試験が在るかだけ（写さない・回さない）")
    ap.add_argument("--only", default="", help="撃つ腕の id（, 区切り）")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    ap.add_argument("--arms", default="", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    try:
        arms = load_arms(args.arms or root / "tests" / "mutations.json")
    except RegistryError as e:
        print(f"selfcheck.py: {e}", file=sys.stderr)
        return 2
    if args.only:
        want = [s for s in args.only.split(",") if s]
        unknown = sorted(set(want) - {a["id"] for a in arms})
        if unknown:
            print(f"selfcheck.py: 知らない腕 {', '.join(unknown)}", file=sys.stderr)
            return 2
        arms = [a for a in arms if a["id"] in want]
    probs = check(root, arms)
    if args.check:
        for p in probs:
            print(f"STALE {p}")
        if probs:
            return 1
        print(f"SELFCHECK_CHECK_OK arms={len(arms)}")
        return 0
    base = home()
    why = refuse_claude_tmp(root, base)
    if why:
        print(why, file=sys.stderr)
        return 2
    base.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    ok, why, out = control(root, base, [a for a in arms if not any(p.startswith(f"{a['id']}:") for p in probs)])
    if not ok:
        print(f"CONTROL_RED 壊さない写しで名指しの試験が緑でない（{why}）\n{_tail(out)}")
        print(f"SELFCHECK caught=0/{len(arms)} control=red total={time.monotonic() - t0:.1f} 秒")
        return 1
    print(f"CONTROL_OK 壊さない写しで名指しの試験が全部緑（{time.monotonic() - t0:.1f} 秒）")
    counts = {"CAUGHT": 0, "NOT_CAUGHT": 0, "NOT_INJECTED": 0}
    for a in arms:
        t = time.monotonic()
        status, why, out = shoot(root, base, a)
        counts[status] += 1
        _, cls, meth, _ = focused(a)
        print(f"{status} {a['id']} {a['title']}（{cls}.{meth}・{time.monotonic() - t:.1f} 秒）" + (f": {why}" if why else ""))
        if status == "NOT_CAUGHT" and out:
            print(_tail(out))
    print(f"SELFCHECK caught={counts['CAUGHT']}/{len(arms)} not_caught={counts['NOT_CAUGHT']} "
          f"not_injected={counts['NOT_INJECTED']} total={time.monotonic() - t0:.1f} 秒")
    return 0 if counts["CAUGHT"] == len(arms) else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
