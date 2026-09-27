"""読んだ証拠（線 A Task 6。仕様 5.2・〔輪〕5.3）。役の出し直しの輪の後、collect の前の節 `<役>-reads` が、機械が役に渡した
パスを役が読んだかを 2 つの出どころで集め、今の周の `reads-<役>.json` に書く。**受け付けの条件にはしない**（graphloops と同じ。
欠けは報告の冒頭に出す）。

出どころ:
1. 包みのフックの記録: 包み（claude-adapter）が足す PostToolUse:Read のフック（record-read.py）が、読んだファイルの sha を
   `<包みの家>/reads/<cwd の hash>/reads.jsonl` に書く（adapter.reads_dir。計画の `$B/reads.jsonl` から T5 で置き場が替わった:
   Claude の子の env に ARTIFACTS_DIR が来ないので run は cwd で分ける）。状態は写しの RL の hook_evidence（read・stale・
   partial・absent・none）をそのまま使う（書き直さない）。役の cwd はこのスクリプトの cwd（Archon は同じ run の節を同じ
   worktree で起こす）なので、repo を省けば cwd。**前提: run ごとに worktree が違う**（仕様 5.1）。フックの記録は cwd ごとで
   run の時刻では絞らないので、同じ worktree を別の run が使い回すと、前の run が同じ中身を全文読んだ行も read に数える
   （盤面の中のファイルは run ごとにパスが違うので当たらない）。数え直し（recount）の wrote_refs_reads も同じ置き場を読む
   （entry.CORE_OVERRIDES）
2. Archon の出来事: `json.loads($ARCHON_CLI_COMMAND) + ["workflow", "get", <run>, "--verbose", "--events", "--json"]` の
   `events` の tool_called（役には偽れない）。`--verbose` が無いと events が出ない（〔試P: P13〕）。tool_called の行の形は
   Archon v0.11.1 の dag-executor.ts が store に書く形（step_name・data.tool_name・data.tool_input）から写したが、AI の節で
   まだ見ていない。P13 の AI の分（計画 Task 18）で確かめるまで EVENTS_VERIFIED は偽で、偽の間は出来事が取れても出どころを
   "unverified"・各行の event を null にする（「読んでいない」と取り違えない。審査 I6）。P13 の結果で直すのは _read_paths と
   node_path だけ

口:
- events_for(run_id) -> list | None
- failed_nodes(events) -> [{node, error}]（最後の状態が落ちた節。機械の報告の冒頭 3）
- node_path(include, loop, node) -> str
- collect(board_dir, role, node_path, must_read, events, *, repo=None) -> {ok: True, sources, missing, reads_file}
- adapter_seen(board_dir, run_id, *, repo=None) -> {seen, merged, passthrough, whys}
- main_for(role, include, loop, node) -> int（ブロックの `<役>-reads` の節のスクリプトの入口）
"""
import datetime
import json
import os
import pathlib
import subprocess
import sys

sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import adapter  # noqa: E402
from board import BoardGap, rules_module  # noqa: E402  （board が写しの engine を sys.path に足す）
import entry  # noqa: E402
import script_io  # noqa: E402

EVENTS_VERIFIED = False   # tool_called の Read の形を P13 の AI の分（Task 18）で確かめたら真にする
HOOK_SEEN = ("read", "stale", "partial")   # フックで「読んだ跡が在る」状態（missing に数えない）
CLI_ENV = "ARCHON_CLI_COMMAND"
RUN_ENV = "WORKFLOW_ID"
MUST_ENV = "INPUTS_MUST"
READS_LOG = "reads.jsonl"   # hook_evidence が board_dir の下に読む名前（record-read.py が書く名前）


# ---------------------------------------------------------------- Archon の出来事
def events_for(run_id: str):
    """この run の出来事の行の一覧。ARCHON_CLI_COMMAND が無い・JSON の文字列の配列でない・run_id が空・CLI を起こせない・
    終了コードが 0 でない・出力が JSON でない・events が配列でない時は None（例外を出さない。〔試P: P13〕）。
    期限は持たない（works の決まり。入れ子の CLI は P13 で 0.4〜1.2 秒）"""
    raw = os.environ.get(CLI_ENV)
    if not raw or not run_id:
        return None
    try:
        cmd = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) and c for c in cmd):
        return None
    try:
        r = subprocess.run(cmd + ["workflow", "get", run_id, "--verbose", "--events", "--json"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        return None
    events = doc.get("events") if isinstance(doc, dict) else None
    return events if isinstance(events, list) else None


NODE_STATES = ("node_started", "node_completed", "node_failed", "node_skipped", "node_skipped_prior_success")


def failed_nodes(events) -> list:
    """最後の状態が node_failed の節 [{node, error}]（出来事の順。出し直しで後に済んだ節は数えない）。行の形（step_name・
    data.error）は Archon v0.11.1 の run 31（ae78d2fe）の出来事の実物で確かめた。events が None・空なら []"""
    last = {}
    for e in events or []:
        if isinstance(e, dict) and e.get("event_type") in NODE_STATES and e.get("step_name"):
            last.pop(e["step_name"], None)
            last[e["step_name"]] = e
    return [{"node": name, "error": str((e.get("data") or {}).get("error") or "")}
            for name, e in last.items() if e.get("event_type") == "node_failed"]


def node_path(include: str, loop: str, node: str) -> str:
    """出来事の上の節の名前。include の中の節は `<include>__<id>`、輪の本体の節は `<輪の名>.<id>` になる（〔試P: P10・P13〕の
    `blk__inner`・`lp.lb`・`rounds.judging__ja-redo.ja-try`）ので、輪の外の include の中の輪の節は `<include>__<輪>.<節>`。
    推測（AI の節の名前は P13 の AI の分で確かめる）"""
    return f"{include}__{loop}.{node}"


def _read_paths(events, node_path: str) -> set:
    """events のうち節 node_path の tool_called の Read が読んだファイル（realpath の集合）。周の輪（線 B）の中に置いた
    include は `rounds.` のような外の輪の頭が付くので、名前が node_path と同じか `.<node_path>` で終わる行を数える。
    行の形は推測（data.tool_name == "Read"・data.tool_input.file_path。Archon は 500 字を超える値を切ることがある）。
    offset・limit 付きの部分読みも数える（出来事の event の真は全文読みの意味でない。全文かはフックの側の partial が言う）。
    P13 の結果で直すのはここだけ"""
    got = set()
    for e in events or []:
        if not isinstance(e, dict) or e.get("event_type") != "tool_called":
            continue
        step = e.get("step_name")
        if not isinstance(step, str) or not (step == node_path or step.endswith("." + node_path)):
            continue
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        inp = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
        path = inp.get("file_path")
        if data.get("tool_name") == "Read" and isinstance(path, str) and path:
            got.add(os.path.realpath(path))
    return got


# ---------------------------------------------------------------- 集める
def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def collect(board_dir, role: str, node_path: str, must_read: list, events, *, repo=None) -> dict:
    """機械が役 role に渡したパス must_read の 1 つずつについて、フックの状態（hook_evidence の 5 つ）と出来事の有無を
    今の周の reads-<役>.json に {role, node_path, rows: [{path, hook, event}], sources: {hook, events}, missing} で書き、
    {ok: True, sources, missing, reads_file} を返す。ok はいつも真（受け付けの条件にしない）。
    - sources.hook: 包みのフックの記録（repo の reads.jsonl）が在るか。sources.events: events が None なら "none"、
      EVENTS_VERIFIED が偽なら "unverified"（各行の event は None）、真なら "verified"（各行の event は真偽）
    - missing: フックで read・stale・partial のどれでもなく、verified の出来事でも読んでいないパス
    - 相対のパスは repo（省けば cwd。役の worktree）に解決して測る。行の path は渡された綴りのまま"""
    repo = pathlib.Path(repo) if repo is not None else pathlib.Path.cwd()
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    sink = adapter.reads_dir(repo)
    hook_on = (sink / READS_LOG).is_file()
    evidence = rules_module().hook_evidence   # 写しの RL の口（engine の util.hook_evidence が RL の名前空間に入る）
    if events is None:
        ev_src, seen = "none", None
    elif not EVENTS_VERIFIED:
        ev_src, seen = "unverified", None
    else:
        ev_src, seen = "verified", _read_paths(events, node_path)
    cache, rows, missing = {}, [], []
    for p in dict.fromkeys(m for m in must_read if isinstance(m, str) and m):
        full = p if os.path.isabs(p) else str(repo / p)
        hook = evidence(sink, full, cache=cache)[0]
        event = None if seen is None else os.path.realpath(full) in seen
        rows.append({"path": p, "hook": hook, "event": event})
        if hook not in HOOK_SEEN and event is not True:
            missing.append(p)
    sources = {"hook": hook_on, "events": ev_src}
    out = b.work(f"reads-{role}.json")
    _write_json(out, {"role": role, "node_path": node_path, "rows": rows, "sources": sources, "missing": missing})
    return {"ok": True, "sources": sources, "missing": missing, "reads_file": str(out)}


# ---------------------------------------------------------------- 包みが通ったか
def _time(s):
    try:
        t = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def adapter_seen(board_dir, run_id: str, *, repo=None) -> dict:
    """この run の役の起動が包みを通ったか。{seen, merged, passthrough, whys}。
    包みの起動の記録（adapter.read_launches。T5 の形で行に run の id を持たない）の、repo（省けば cwd。run ごとの worktree）の
    行のうち、盤面を作った時（state.created）以後で tools_empty でない物を数える（前の run が同じ worktree に残した行と、
    題の生成の起動は数えない。tools_empty は「題の生成か、道具を持たない役」なので、道具を持たない役の起動も数えない——
    今の darkfactory の役はどれも Read を持つので当たらない）。seen はそういう行が 1 つでも在るか（素通し・拒んだ起動も
    包みが道に居た証拠）。前提は collect と同じ run ごとの worktree（同じ worktree で run が重なって走ると行が混ざる）。
    whys は素通しと拒んだ起動の理由（重ねない）と、seen が偽の時の 1 行"""
    repo = pathlib.Path(repo) if repo is not None else pathlib.Path.cwd()
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    since = _time(b.state.get("created"))
    rows = []
    for r in adapter.read_launches(repo):
        at = _time(r.get("at"))
        if r.get("tools_empty") or at is None or since is None or at < since:
            continue
        rows.append(r)
    count = {m: sum(1 for r in rows if r.get("mode") == m) for m in ("merged", "passthrough")}
    whys = list(dict.fromkeys(str(r["why"]) for r in rows if r.get("mode") != "merged" and r.get("why")))
    if not rows:
        whys.append(f"run {run_id} の役の起動が包みの起動の記録（{adapter.launches_path(repo)}）に無い"
                    f"（盤面を作った {b.state.get('created')} 以後・題の生成を除く）")
    return {"seen": bool(rows), **count, "whys": whys}


# ---------------------------------------------------------------- 節の入口
def _fail(why: str) -> int:
    print(why, file=sys.stderr)
    return 2


def main_for(role: str, include: str, loop: str, node: str, *, more=None) -> int:
    """ブロックの `<役>-reads` の節のスクリプトの入口。ARTIFACTS_DIR（盤面はその下の board/）・WORKFLOW_ID（出来事を読む run）・
    INPUTS_MUST（読むべきパスの JSON の配列）を読み、collect の結果を 1 行の JSON で出して 0。more(盤面) が在れば、その返す
    パスの一覧を読むべきパスに足す（ブロックが盤面の置き場に書いた物。YAML の with: で渡せない輪の中の出力など）。変数が欠けた
    （空も欠け）・INPUTS_MUST が文字列の配列でない・盤面を開けない時は、標準出力に何も出さずに標準エラーに 1 行で 2"""
    env = {k: os.environ.get(k) for k in (script_io.ARTIFACTS_ENV, RUN_ENV, MUST_ENV)}
    lack = [k for k, v in env.items() if not v]
    if lack:
        return _fail(f"環境変数が無い: {', '.join(lack)}")
    try:
        must = json.loads(env[MUST_ENV])
    except ValueError:
        must = None
    if not isinstance(must, list) or not all(isinstance(m, str) for m in must):
        return _fail(f"{MUST_ENV} が文字列の JSON の配列でない: {env[MUST_ENV][:200]!r}")
    board = (pathlib.Path(env[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR).resolve()
    try:
        if more is not None:
            must = must + [m for m in more(board) if m not in must]
        got = collect(board, role, node_path(include, loop, node), must, events_for(env[RUN_ENV]))
    except BoardGap as e:
        return _fail(f"{role}-reads を回せない（{type(e).__name__}）: {' '.join(str(e).split())}")
    script_io._emit(got)
    return 0
