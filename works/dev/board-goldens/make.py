# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""盤面の手本の作り手（仕様 9.2）。graphloops の写しの commit を使い捨ての場所に書き出し、台本 simulate_review.py の場面を
1 つずつ同じプロセスで呼び、子の loop.py に sitecustomize.py（同じフォルダ）を読ませて engine の中の手を撮り、
tests/boards/golden-a1202d0/ に置く。お金 0・AI 0（実物の claude を起こしたら印を書いて 97 で落ちる偽の claude を
PATH の頭に置く）。graphloops の追跡ファイルには触らない。

使い方: uv run works/dev/board-goldens/make.py [--graphloops-rev <commit>] [--out <置き場>] [--work <置き場>] [場面 ...]
--graphloops-rev の既定は写しの commit（works/.shared/core/COPIED_FROM の 1 行目）。
作業場（書き出し・台本の作業場・撮った生の物）は ${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/board-goldens/ の下に作って
終わったら消す。台本の子の TMPDIR もその下に向ける。Claude Code の一時フォルダ（/private/tmp/claude-*・/tmp/claude-*）の
下に解ける作業場は拒む（works/dev/guard.sh と同じ決まり。サンドボックスの Bash が書けるため）。
場面を絞って回すと、置き場の他の場面はそのまま残し、渡した場面だけを差し替える。
終了コード: 0 = 撮れた / 1 = init が通った Run で init の後の手が 0（台本が init の返りだけを見る、下の表の Run を除く）か、
手が 1 つも撮れない場面が在る（包み方が効いていない） / 2 = それ以外の失敗（書き出し・台本の検査の失敗・偽の claude が
起こされた・撮り手の中の失敗・絶対パスの残り）
"""
import argparse
import collections
import datetime
import gzip
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_OUT = ROOT / "works" / "tests" / "boards" / "golden-a1202d0"
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(ROOT / "works" / ".shared" / "core"))
import copyledger  # noqa: E402

SCENARIOS = ["test_converges", "test_runaway", "test_awaiting", "test_rejections", "test_request_entry",
             "test_fix_plan_review", "test_human_gate", "test_policy_reaches_roles", "test_stop_midround",
             "test_stop_after_round", "test_gates_merge", "test_rejudge_path"]
SKIPPED = {
    "test_delta_conditions": "loop.py を通らず、偽の盤面で規則（RL）を直に呼ぶ——engine の中の手が無い",
    "test_fix_counts_by_engine": "loop.py を通らず、偽の盤面で規則（RL）を直に呼ぶ——engine の中の手が無い",
    "test_lane_end_to_end": "変異の実行器（tests/mutate.py の線）を起こす——変異テストを回さない決まり",
}
# 台本が init の返りだけを見て閉じる Run（init の後の手が無くても失敗にしない）。(場面, Run の名前): 理由
INIT_ONLY = {
    ("test_rejections", "neg-nodecl"): "宣言の無いリポジトリの最初の next が p0.local_checks を任せ先に落とした ready だけを見る"
                                       "（その next の中に機械の節も条件の na も無い）",
    ("test_gates_merge", "gfar-GATES"): "宣言に無い鍵を init が受け付けて notes に出すことだけを見る（next を呼ばない）",
    ("test_gates_merge", "gfar-gates_mode"): "宣言に無い鍵を init が受け付けて notes に出すことだけを見る（next を呼ばない）",
}
# 線 A・B が使う機械の節と engine が走らせる節（手本が 1 度も通らない物を uncovered に出す）
LINE_NODES = ["p1.worktree_before", "p1.worktree_after", "p2.human_gate", "p3.lane_merge", "p3.fix_delta", "p3.fix_delta2",
              "p3.delta_owed", "p3.delta_owed2", "p3.gates_cut", "p4.scalars", "p4.assemble", "p4.record", "converge",
              "p0.local_checks", "p4.ci", "p0.parallel_pr"]
# 版の id を揃える（仕様 9.2 の 4）。再生も同じ環境で回す
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
}
TOKENS = {
    "@BOARD@": "Run の盤面の置き場（--dir）",
    "@REPO@": "Run の対象リポジトリ（loop.py の cwd）",
    "@RUN@": "Run の作業場（盤面と対象リポジトリの親。台本の返答の置き場 out.txt など）",
    "@CORE@": "書き出した graphloops の根（graphloops/ と scripts/review-record.py の親）",
    "@WORK@": "作り手の作業場（偽の claude の置き場 guard/ など）",
    "@PY@": "撮った機械の Python（台本の宣言の語が sys.executable のため。再生は今の Python で宣言の sha を計算し直す）",
    "@TMPDIR@": "台本の子の一時の置き場（@WORK@/tmp。台本の作業場 gl-review-*・engine の道具ゼロの役の置き場 graphloops-isolated-*）",
    "@HOME@": "撮った機械のホーム",
}
RAW_MARKS = ["/Users/", "/var/folders", "/private/var", "/private/tmp", str(pathlib.Path.home())]
# 台本のリポジトリの宣言（.review-checks.json）の走らせる語の頭。台本は sys.executable を書くので、撮った機械の Python の
# パスが seed の commit（zlib で縮めた git の object）に入る。機械に依らない名前に替えて、PATH から引かせる
NEUTRAL_PY = "python3"
CLAUDE_TMP = ("/private/tmp/claude-", "/tmp/claude-")


# ---------------------------------------------------------------- 差分
def jdiff(a, b, path=()):
    """記憶の差分 [{path, op: set|del, value?}]（深い所の 1 欄の変更は 1 行）"""
    if isinstance(a, dict) and isinstance(b, dict):
        ops = [{"path": [*path, k], "op": "del"} for k in a if k not in b]
        for k, v in b.items():
            if k not in a:
                ops.append({"path": [*path, k], "op": "set", "value": v})
            else:
                ops += jdiff(a[k], v, (*path, k))
        return ops
    if isinstance(a, list) and isinstance(b, list):
        n = min(len(a), len(b))
        ops = []
        for i in range(n):
            ops += jdiff(a[i], b[i], (*path, i))
        ops += [{"path": [*path, i], "op": "del"} for i in range(len(a) - 1, len(b) - 1, -1)]
        ops += [{"path": [*path, i], "op": "set", "value": b[i]} for i in range(n, len(b))]
        return ops
    if type(a) is type(b) and a == b:
        return []
    return [{"path": list(path), "op": "set", "value": b}]


def ldiff(a, b):
    """目録の差分 {add: {パス: sha}, drop: [パス]}（変わらなければ空）"""
    got = {}
    add = {p: s for p, s in b.items() if a.get(p) != s}
    drop = sorted(p for p in a if p not in b)
    if add:
        got["add"] = add
    if drop:
        got["drop"] = drop
    return got


# ---------------------------------------------------------------- 撮った物を読む
class Raw:
    def __init__(self, rec):
        self.rec = rec
        self._cache = {}

    def load(self, sub, sha):
        if sha is None:
            return None
        key = (sub, sha)
        if key not in self._cache:
            self._cache[key] = json.loads(gzip.decompress((self.rec / sub / f"{sha}.gz").read_bytes()))
        return self._cache[key]

    def rows(self):
        d = self.rec / "raw" / "rows"
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.is_dir() else []

    def ends(self):
        d = self.rec / "raw" / "end"
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.is_dir() else []

    def reset(self):
        shutil.rmtree(self.rec / "raw", ignore_errors=True)
        for p in ("seq.txt", "seq.lock"):
            (self.rec / p).unlink(missing_ok=True)
        self._cache.clear()


def run_label(board_raw):
    """目録に書く Run の名前: 作業場の名前（gl-review-<名前>-<乱数 8 字>）の乱数を * にした物 ＋ 盤面の名前"""
    p = pathlib.PurePosixPath(board_raw)
    head = re.sub(r"[a-z0-9_]{8}$", "*", p.parent.name)
    return f"{head}/{p.name}"


def encode_run(rows, raw, blob_json):
    """1 本の Run の撮った行を、仕様 9.2 の 5 の形（Run の頭だけ丸ごと、以後は差分）に直す"""
    out = []
    mem_ref = disk_ref = repo_ref = None
    for r in rows:
        s = {"seq": None, "run": None, "raw_seq": r["seq"], "parent": r.get("parent"), "kind": r["kind"]}
        if r.get("node") is not None:
            s["node"] = r["node"]
        s["args"] = r.get("args") or {}
        for k in ("raised", "na", "engine_run", "result"):
            if k in r:
                s[k] = r[k]
        if r["kind"] == "na":
            out.append(s)
            continue
        mb, ma = raw.load("raw/mem", r.get("mem_before")), raw.load("raw/mem", r.get("mem_after"))
        if r["kind"] == "init" or mem_ref is None:
            if mb is None and ma is not None:
                s["memory"] = {"base": ma}
            elif mb is not None:
                s["memory"] = {"base": mb, **({"after": jdiff(mb, ma)} if ma is not None else {})}
        else:
            s["memory"] = {"before": jdiff(mem_ref, mb)}
            if ma is not None:
                s["memory"]["after"] = jdiff(mb, ma)
        if "memory" in s:
            mem_ref = ma if ma is not None else mb
        db, da = raw.load("raw/man", r.get("disk_before")), raw.load("raw/man", r.get("disk_after"))
        if disk_ref is None:
            if db is None and da is not None:
                s["disk"] = {"base": da}
            elif db is not None:
                s["disk"] = {"base": db, **({"after": ldiff(db, da)} if da is not None and ldiff(db, da) else {})}
        else:
            s["disk"] = {k: v for k, v in (("before", ldiff(disk_ref, db or {})),
                                           ("after", ldiff(db or {}, da) if da is not None else {})) if v}
        if "disk" in s:
            disk_ref = da if da is not None else (db if db is not None else disk_ref)
        rb = raw.load("raw/man", r.get("repo_before"))
        if rb is not None:
            if repo_ref is None:
                s["repo_before"] = {"base": rb}
            else:
                d = ldiff(repo_ref, rb)
                if d:
                    s["repo_before"] = d
            repo_ref = rb
        out.append(s)
    last = None
    if mem_ref is not None:
        last = {"memory": blob_json(mem_ref), "disk": blob_json(disk_ref or {}), "repo": blob_json(repo_ref or {})}
    return out, last


def shas_of(steps):
    got = set()
    for s in steps:
        d = s.get("disk") or {}
        got.update((d.get("base") or {}).values())
        for k in ("before", "after"):
            got.update(((d.get(k) or {}).get("add") or {}).values())
        r = s.get("repo_before") or {}
        got.update((r.get("base") or {}).values())
        got.update((r.get("add") or {}).values())
    return got


# ---------------------------------------------------------------- 回す
def dev_home():
    return pathlib.Path(os.environ.get("WORKS_DEV_HOME") or pathlib.Path.home() / ".cache" / "works-dev")


def refuse_claude_tmp(what, path):
    """Claude Code の一時フォルダの下に解ける場所は使わない（works/dev/guard.sh の works_dev_refuse_claude_tmp と同じ決まり）"""
    real = os.path.realpath(path)
    if real.startswith(CLAUDE_TMP):
        print(f"make.py: {what} が Claude Code の一時フォルダの下にある（{real}。/private/tmp/claude-* はサンドボックスの Bash が"
              "書ける）。別の場所を使う（WORKS_DEV_HOME の既定は $HOME/.cache/works-dev）", file=sys.stderr)
        sys.exit(2)


def export(rev, dest):
    dest.mkdir(parents=True)
    arc = subprocess.run(["git", "-C", str(ROOT), "archive", rev], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=arc, check=True)
    return dest


def prepare_env(work, core, rec):
    guard = work / "guard"
    guard.mkdir()
    marker = work / "CLAUDE_CALLED"
    (guard / "claude").write_text(f"#!/bin/sh\necho \"$@\" >> '{marker}'\nexit 97\n", encoding="utf-8")
    (guard / "claude").chmod(0o755)
    (work / "claude-config").mkdir()
    tmp = work / "tmp"   # 台本の作業場（gl-review-*）と engine の道具ゼロの役の置き場も作業場の下へ
    tmp.mkdir()
    tempfile.tempdir = str(tmp)   # 台本は同じプロセスで tempfile を使う（読み直させる）
    for k in ("CONVERGENCE_LOOPS_ROOT", "GRAPHLOOPS_ROOT", "CLAUDE_PLUGIN_DATA", "GL_TEST_ONLY", "PYTHONHOME"):
        os.environ.pop(k, None)
    os.environ.update(GIT_ENV)
    os.environ.update({
        "PATH": f"{guard}{os.pathsep}{os.environ['PATH']}",
        "TMPDIR": str(tmp),
        "PYTHONPATH": str(HERE),
        "PYTHONDONTWRITEBYTECODE": "1",
        "CLAUDE_CONFIG_DIR": str(work / "claude-config"),   # 入れた plugin の置き場（~/.claude）を引かせない
        "GL_TEST_WORKERS": "1",
        "WORKS_GOLDEN_OUT": str(rec),
        "WORKS_GOLDEN_CORE": str(core),
        "WORKS_GOLDEN_PY": sys.executable,
        "WORKS_GOLDEN_WORK": str(work),
    })
    return marker


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--graphloops-rev", default=copyledger.core_commit())
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--work", help="書き出しと撮った生の物の置き場（渡せば消さない。既定は "
                                  "${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/board-goldens/ の下の使い捨て）")
    p.add_argument("scenarios", nargs="*")
    a = p.parse_args()
    names = a.scenarios or SCENARIOS
    bad = [n for n in names if n in SKIPPED]
    if bad:
        print(f"撮らない場面: {bad}（{[SKIPPED[n] for n in bad]}）", file=sys.stderr)
        return 2
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        print(f"撮る場面の表に無い: {unknown}（撮るのは {SCENARIOS}）", file=sys.stderr)
        return 2
    if not shutil.which(NEUTRAL_PY):
        print(f"{NEUTRAL_PY} が PATH に無い（台本のリポジトリの宣言の語の頭に使う）", file=sys.stderr)
        return 2
    keep = bool(a.work)
    if a.work:
        work = pathlib.Path(a.work).resolve()
        refuse_claude_tmp("--work", work)
        work.mkdir(parents=True, exist_ok=True)
    else:
        base = dev_home() / "board-goldens"
        refuse_claude_tmp("作業場の親（WORKS_DEV_HOME）", base)
        base.mkdir(parents=True, exist_ok=True)
        work = pathlib.Path(tempfile.mkdtemp(prefix="run-", dir=base))
    try:
        return run(a, names, work)
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def run(a, names, work):
    import hashlib
    import zlib
    core = export(a.graphloops_rev, work / "export")
    rec = work / "rec"
    rec.mkdir()
    marker = prepare_env(work, core, rec)
    sys.path.insert(0, str(core / "graphloops" / "tests"))
    import simulate_review as S  # noqa: E402 —— 書き出した台本（engine も sys.path に入る）
    from engine.schema import graph_text  # noqa: E402
    from engine.util import sha  # noqa: E402
    graph_sha = sha(graph_text(core / "graphloops" / "graphs" / "review-loop.json"))
    # Run の既定の宣言（関数の既定値が同じ list を指す）の頭を機械に依らない名前にする
    S.CHECKS_OK[0]["argv"][0] = NEUTRAL_PY

    raw = Raw(rec)
    extra_blobs = {}   # 目録・記憶の丸ごと（last・final）の中身

    def blob_json(obj):
        data = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
        h = hashlib.sha256(data).hexdigest()
        extra_blobs[h] = data
        return h

    new_steps, new_meta, empty_scen, lonely = {}, {}, [], []
    for name in names:
        raw.reset()
        os.environ["WORKS_GOLDEN_SCENARIO"] = name
        fails0, ran0 = len(S.fails), S.ran
        print(f"=== {name}", flush=True)
        getattr(S, name)()
        rows = [r for r in raw.rows() if r.get("scenario") == name]
        ends = {}
        for e in raw.ends():
            if e.get("scenario") == name and e["seq"] > ends.get(e["board_raw"], {}).get("seq", 0):
                ends[e["board_raw"]] = e
        if not rows:
            empty_scen.append(name)
        by_run = collections.OrderedDict()
        for r in sorted(rows, key=lambda r: r["seq"]):
            by_run.setdefault(r["board_raw"], []).append(r)
        steps, runs = [], {}
        for n, (board_raw, rs) in enumerate(by_run.items(), 1):
            enc, last = encode_run(rs, raw, blob_json)
            label = run_label(board_raw)
            first = enc[0] if enc else {}
            rejected = first.get("kind") == "init" and "raised" in first and "memory" not in first
            for s in enc:
                s["run"] = n
            meta = {"dir": label, "steps": len(enc), "kinds": dict(collections.Counter(s["kind"] for s in enc)),
                    "init_rejected": rejected}
            mem = raw.load("raw/mem", next((r.get("mem_after") or r.get("mem_before") for r in rs
                                            if r.get("mem_after") or r.get("mem_before")), None))
            if mem:
                meta["graph_sha"] = mem["state"].get("graph_sha")
            if last:
                meta["last"] = last
            end = ends.get(board_raw)
            if end and not rejected:
                meta["final"] = {"memory": blob_json(raw.load("raw/mem", end["memory"])),
                                 "disk": blob_json(raw.load("raw/man", end["disk"]) or {}),
                                 "repo": blob_json(raw.load("raw/man", end["repo"]) or {})}
            why = INIT_ONLY.get((name, label.split("/")[0].removeprefix("gl-review-").removesuffix("-*")))
            if not rejected and len(enc) <= 1:
                if why:
                    meta["init_only"] = why
                else:
                    lonely.append(f"{name} の run {n}（{label}）")
            runs[str(n)] = meta
            steps += enc
        renum = {}
        for i, s in enumerate(steps, 1):
            s["seq"] = i
            renum[s.pop("raw_seq")] = i
        for s in steps:
            if s.get("parent") is not None:
                s["parent"] = renum[s["parent"]]
            else:
                s.pop("parent", None)
        failed = S.fails[fails0:]
        new_steps[name] = steps
        new_meta[name] = {"runs": runs, "simulator": {"checks": S.ran - ran0, "failed": failed}}
        print(f"    Run {len(runs)} 本・手 {len(steps)}・台本の検査の失敗 {len(failed)}", flush=True)
    raw.reset()
    errors = (rec / "recorder-errors.txt").read_text(encoding="utf-8") if (rec / "recorder-errors.txt").exists() else ""

    # ---- 置く（場面を絞った回は、置き場の他の場面をそのまま残す）
    out = pathlib.Path(a.out).resolve()
    old_meta = {}
    if a.scenarios and (out / "MANIFEST.json").is_file():
        old_meta = {k: v for k, v in json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))["scenarios"].items()
                    if k not in new_steps}
    stage = out.with_name(out.name + ".new")
    if stage.exists():
        shutil.rmtree(stage)
    (stage / "blobs").mkdir(parents=True)
    (stage / "steps").mkdir()
    seen, all_steps, scen_meta = set(), {}, {}
    for name in [n for n in SCENARIOS if n in new_steps or n in old_meta]:
        if name in new_steps:
            steps, meta = new_steps[name], new_meta[name]
            data = gzip.compress(json.dumps(steps, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9, mtime=0)
        else:
            data = (out / "steps" / f"{name}.json.gz").read_bytes()
            steps, meta = json.loads(gzip.decompress(data)), old_meta[name]
        (stage / "steps" / f"{name}.json.gz").write_bytes(data)
        for rn, rmeta in meta["runs"].items():
            mine = [s for s in steps if str(s["run"]) == rn]
            size = len(gzip.compress(json.dumps(mine, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9, mtime=0))
            refs = shas_of(mine) | set((rmeta.get("last") or {}).values()) | set((rmeta.get("final") or {}).values())
            for h in sorted(refs - seen):
                dst = stage / "blobs" / f"{h}.gz"
                if h in extra_blobs:
                    dst.write_bytes(gzip.compress(extra_blobs[h], 9, mtime=0))
                elif (rec / "blobs" / f"{h}.gz").is_file():
                    dst.write_bytes((rec / "blobs" / f"{h}.gz").read_bytes())
                else:
                    dst.write_bytes((out / "blobs" / f"{h}.gz").read_bytes())
                size += dst.stat().st_size
            seen |= refs
            if name in new_steps:
                rmeta["bytes"] = size
        all_steps[name], scen_meta[name] = steps, meta

    covered = {s["node"] for st in all_steps.values() for s in st if s["kind"] in ("builtin", "engine_run")}
    total = sum(p.stat().st_size for p in (stage / "blobs").glob("*.gz")) + sum(p.stat().st_size for p in (stage / "steps").glob("*.gz"))
    sims = [m.get("simulator") or {} for m in scen_meta.values()]
    manifest = {
        "graphloops_rev": a.graphloops_rev,
        "graph_sha": graph_sha,
        "made_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "git_env": GIT_ENV,
        "neutral_interpreter": NEUTRAL_PY,
        "tokens": TOKENS,
        "scenarios": scen_meta,
        "skipped_scenarios": SKIPPED,
        "uncovered": [n for n in LINE_NODES if n not in covered],
        "total_bytes": total,
        "simulator": {"checks": sum(x.get("checks", 0) for x in sims), "failed": [f for x in sims for f in x.get("failed", [])]},
    }
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if out.exists():
        shutil.rmtree(out)
    stage.rename(out)

    # ---- 見届け
    print(f"\n置いた: {out}（{total / 1024 / 1024:.2f} MB。場面 {len(all_steps)}（今回 {len(new_steps)}）・中身 {len(seen)}）")
    print(f"uncovered: {manifest['uncovered']}")
    code = 0
    leaks = []
    for p in sorted(out.rglob("*")):
        if not p.is_file():
            continue
        data = gzip.decompress(p.read_bytes()) if p.suffix == ".gz" else p.read_bytes()
        texts = [data]
        try:
            texts.append(zlib.decompress(data))   # git の object（zlib で縮めてある）の中まで見る
        except zlib.error:
            pass
        leaks += [f"{p.relative_to(out)}: {m}" for t in texts for m in RAW_MARKS if m.encode("utf-8") in t]
    for what, bad in (("偽の claude が起こされた", marker.exists()), ("撮り手の中の失敗", errors),
                      ("台本の検査の失敗", manifest["simulator"]["failed"]), ("絶対パスの残り", leaks[:20])):
        if bad:
            print(f"NG {what}: {bad}", file=sys.stderr)
            code = 2
    if empty_scen or lonely:
        print(f"NG 手が撮れない場面 {empty_scen}・init の後の手が 0 の Run {lonely}", file=sys.stderr)
        code = code or 1
    return code


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
