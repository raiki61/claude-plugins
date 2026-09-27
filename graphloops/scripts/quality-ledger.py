#!/usr/bin/env python3
"""盤面を横断して、run ごとの質の数を engine の版ごとに束ねる（読むだけ。盤面にも plugin の置き場にも何も書かない）。

使い方:
    quality-ledger.py [根 ...] [--runs | --json]

根（既定は cwd のリポジトリの共有の git ディレクトリ——`git rev-parse --git-common-dir`）の下を辿り、state.json か
trace.jsonl を持つディレクトリを 1 本の run の盤面として読む。本体の盤面（<共有>/graphloops/<loop>/<run_id>/）も
linked worktree の盤面（<共有>/worktrees/<名>/graphloops/<loop>/<run_id>/）もこの規則で拾う。`init --dir` で外に作った
盤面は、その置き場の親を根に渡したときだけ数える（渡さなければ数えない）。worktree を消すと盤面も消えるので数えられない。

数える物は盤面に書かれた値そのもので、台本は語彙を持たない（engine が語を足しても黙って狭くならない）:
- 周の判定（rounds/round-<N>.json の reviews）: 盤面の周に在る R の行を 1 行ずつ、重ならない 3 つに分ける。本物（役が
  返した判定）・除いた行（機械が埋めた行＝検証器の REVIEW_STATUS の machine_written と、持ち越せない値の据え置き＝rules
  の据え置きの句）・数えられない行（今の検証器の REVIEWS に無い鍵・REVIEW_STATUS に無い値・辞書でない行・述語を
  引けない graph の周の行。R の鍵→値→数で出す）。周に鍵の無い R はどれにも入らない。R ごとの数の分母はその R の
  本物の行の数で、閉じた周の数ではない。述語は plugin の検証器と rules から引く（写さない）。述語は今の plugin の
  物で、旧い版の盤面の周にも同じ述語を当てる（据え置きの句の文言が版で変わっていても見分けられない）
- 版: 周の判定は周ごとの版（state.engine_changes）に、trace の行は直前の engine_changed の版に帰属させる。
  run の数と状態は最後の版（state.engine）に数え、版をまたいだ run は「版が混在」に数える
- 関所の答え: trace の answer の値と kinds をそのまま数える。答えを打った者は盤面に記録が無い
- 受け付け: trace の role_run の accepted の値（True / False / None / 欄なし）をそのまま数え、False の行は why の頭の句で数える
  （頭の句は、絶対パス・家の置き場・ログイン名を伏せてから切って束ねる——パスだけ違う頭は 1 つに束ねられる）
- 費用: role_run の total_cost_usd は会話の累計なので、会話（session_id）ごとの最大を足す
- 時間: 経過（trace の最初と最後の時刻の差。人待ち・止めた間を含む）と、役の実行の合計（role_run の wall_s の和）
- 走っている run: status が running でも生きているとは限らないので、最後の痕跡（trace の最後の時刻）からの経過を出す

読めない盤面（state.json が無い・JSON でない・形が違う）は落とさずに「読めない」と数え、run の中の一部のファイル・行が
読めないときはその部分だけを数えない（読めなかった部分は run の行の unreadable_parts に出す）。
置き場は根からの相対で出し、盤面の絶対パスの欄（state.graph・engine.root・trace の root・stderr）は写さない。自由文を出す
所（拒否の理由の頭・launch が ok でない行の頭・述語が引けない注意）は、絶対パスを <絶対パス>、ログイン名を <利用者> に伏せる。
"""
import argparse
import collections
import contextlib
import datetime
import getpass
import importlib.util
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys

sys.dont_write_bytecode = True  # engine・rules・検証器を読むときに plugin の置き場へ __pycache__ を書かない
PLUGIN = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN))

from engine import schema as schema_mod  # noqa: E402
from engine import role_run as role_run_mod  # noqa: E402
from engine import rules as rules_mod  # noqa: E402
from engine import util as util_mod  # noqa: E402
from engine import validator as validator_mod  # noqa: E402

NO_ENGINE = "版なし（engine の欄が無い盤面）"
UNREAD_VERSION = "版が読めない"
UNREADABLE = "読めない盤面"
HEAD_MAX = 60
NOT_DICT = "（行が辞書でない）"
NO_STATUS = "（status の欄が無い）"


# ---------------------------------------------------------------- 周の判定の述語（plugin の検証器と rules から引く）
class Verdicts:
    """graph ごとに、検証器の REVIEWS・REVIEW_STATUS と rules の据え置きの句を引く。引けなければ why に理由を持つ"""

    def __init__(self):
        self._cache = {}

    def for_graph(self, name, loop):
        key = name or loop
        if key not in self._cache:
            self._cache[key] = self._load(name, loop)
        return self._cache[key]

    @staticmethod
    def _load(name, loop):
        path = PLUGIN / "graphs" / (name or f"{loop}.json")
        if not path.is_file():
            return {"why": redact(f"{path.name} が plugin に無い")}
        util_mod.LAST_DIE = None  # 前の graph で die した文面を、この graph の理由として出さない
        try:
            # 1 本の graph が読めなくても集計を止めない（docstring の『読めない物は落とさず数える』）。engine の die は SystemExit
            # （Exception の受けを抜ける）で stderr に絶対パス入りの 1 行を印字するので、stderr は捨てて die の文面を伏せて出す。
            # die を通らない例外（engine の実装の誤りを含む）も同じ注意に丸め、手がかりは例外の型名だけ——追うなら engine を直に呼ぶ
            with open(os.devnull, "w", encoding="utf-8") as null, contextlib.redirect_stderr(null):
                graph, err = schema_mod.load_graph(path)
                if graph is None:
                    return {"why": redact(err)}
                vpath = validator_mod.find_validator(loop or path.stem, graph.get("plugin"))
                rules = rules_mod.load_rules(path, graph)
        except (SystemExit, Exception) as e:
            return {"why": f"graph か検証器か rules が読めない（{redact(util_mod.LAST_DIE or type(e).__name__)}）"}
        if not vpath:
            return {"why": "検証器が見つからない"}
        spec = importlib.util.spec_from_file_location("graphloops_ledger_validator", vpath)
        V = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(V)
        except Exception as e:
            return {"why": f"検証器が import できない（{type(e).__name__}）"}
        if not hasattr(V, "REVIEWS"):
            return {"why": "このループの検証器は周の判定を持たない"}
        # 据え置きの句は rules の述語（hist_last_review が使う物）をそのまま引く——写さない
        tail = getattr(rules, "_CARRIED_REVIEW_TAIL", None)
        return {"reviews": V.REVIEWS, "status": V.REVIEW_STATUS, "tail": tail,
                "why": None if tail else "据え置きの句を rules から引けない（据え置きの行を除けていない）"}


# ---------------------------------------------------------------- 盤面を探す・読む
def default_root():
    r = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        sys.exit(f"git rev-parse --git-common-dir が exit {r.returncode}——根を位置引数で渡せ")
    return pathlib.Path(r.stdout.strip()).resolve()


def find_boards(root):
    """根の下で state.json か trace.jsonl を持つディレクトリ（見つけた盤面の中へは降りない。リンクは辿らない）"""
    out = []
    for d, dirs, files in os.walk(root, followlinks=False):
        if "state.json" in files or "trace.jsonl" in files:
            out.append(pathlib.Path(d))
            dirs[:] = []
        else:
            dirs.sort()
    return sorted(out)


def _read_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _ts(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


_HOME = os.path.expanduser("~")
try:
    _USER = getpass.getuser()
except (OSError, KeyError, ImportError):
    _USER = ""
_PATH_CHAR = r"[^\s:：（）()「」『』、，,;\"'`<>\[\]{}]"
# 前が英数字・_・.・~・- でない / から始まる経路（日本語の直後も当てる）・~/ の経路・ドライブ文字の経路
_ABS_PATH = re.compile(rf"(?<![A-Za-z0-9_.~-])(?:/{_PATH_CHAR}+|~/{_PATH_CHAR}*|[A-Za-z]:[\\/]{_PATH_CHAR}*)")
# ログイン名は前後が英数字・_ でない所で伏せる（- は境界に数える: -Users-<名>-src- の形の置き場がある）。短すぎる名は語を壊すので当てない
_LOGIN = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(_USER)}(?![A-Za-z0-9_])") if len(_USER) >= 3 else None


def redact(text):
    """出力に載せる自由文から、家の置き場・絶対パス・ログイン名を伏せる（束ねる前に当てる）"""
    s = _ABS_PATH.sub("<絶対パス>", str(text))
    if len(_HOME) > 1:  # 前が英数字で経路の形に当たらなかった家の置き場
        s = s.replace(_HOME, "<絶対パス>")
    return _LOGIN.sub("<利用者>", s) if _LOGIN else s


def head_of(why):
    """拒否の理由の頭の句（伏せた最初の行を『（』の手前で切り、『: 』で区切った先頭 2 つ）——語彙を持たずに種類を束ねる"""
    line = redact(str(why or "").splitlines()[0]) if why else ""
    for mark in ("（", "("):
        line = line.split(mark, 1)[0]
    return ": ".join(line.split(": ")[:2]).strip()[:HEAD_MAX] or "（理由が空）"


def _version_of(engine):
    if not isinstance(engine, dict):
        return NO_ENGINE
    return engine.get("version") or UNREAD_VERSION


def read_run(d, where, verdicts, now=None):
    """盤面 1 本を 1 行にする。state.json が読めなければ読めない行。一部が読めなければその部分だけ数えない。
    欄の形が想定と違う盤面（旧い形・手で壊した盤面）で落ちた例外はここ 1 か所で受け、読めない行にする"""
    try:
        return _read_run(d, where, verdicts, now)
    except Exception as e:
        return {"where": where, "unreadable": f"盤面の形が違う（{type(e).__name__}）"}


def _read_run(d, where, verdicts, now):
    row = {"where": where}
    try:
        state = _read_json(d / "state.json")
        if not isinstance(state, dict) or not isinstance(state.get("rounds", []), list):
            raise ValueError("形が違う")
    except FileNotFoundError:
        return {**row, "unreadable": "state.json が無い"}
    except (OSError, ValueError) as e:
        return {**row, "unreadable": f"state.json が読めない（{type(e).__name__}）"}
    parts = []
    changes = [c for c in (state.get("engine_changes") or []) if isinstance(c, dict)]
    last = _version_of(state.get("engine")) if "engine" in state else NO_ENGINE
    first = _version_of(changes[0].get("to")) if changes else last

    def version_at(n):
        v = first
        for c in changes:
            if isinstance(c.get("round"), int) and c["round"] <= n:
                v = _version_of(c.get("to"))
        return v

    halted = state.get("halted") if isinstance(state.get("halted"), dict) else {}
    row.update({"loop": state.get("loop_name"), "run_id": state.get("run_id"), "version": last,
                "versions": sorted({first, last, *(_version_of(c.get("to")) for c in changes)}),
                "status": state.get("status"), "halted_by": halted.get("by"),
                "pending_human": bool(state.get("pending_human")), "round": state.get("round")})

    # 周の判定
    vd = verdicts.for_graph(pathlib.Path(str(state.get("graph") or "")).name or None, state.get("loop_name"))
    rounds = []
    for f in sorted((d / "rounds").glob("round-*.json")):
        try:
            rec = _read_json(f)
            n = int(f.stem.split("-", 1)[1])
        except (OSError, ValueError) as e:
            parts.append(f"rounds/{f.name}（{type(e).__name__}）")
            continue
        reviews = rec.get("reviews") if isinstance(rec, dict) else None
        real, held, uncountable = {}, 0, collections.defaultdict(collections.Counter)
        if isinstance(reviews, dict):
            for name, rv in reviews.items():  # 盤面に在る鍵だけ（周に鍵の無い R はどれにも入らない）
                status = rv.get("status", NO_STATUS) if isinstance(rv, dict) else NOT_DICT
                st = vd["status"].get(status) if vd.get("reviews") and isinstance(status, str) else None
                if name not in (vd.get("reviews") or ()) or st is None:
                    uncountable[str(name)][status if isinstance(status, str) else str(status)] += 1
                elif st.machine_written or (vd["tail"] and vd["tail"].search(str(rv.get("reason") or ""))):
                    held += 1
                else:
                    real[name] = status
        rounds.append({"round": n, "version": version_at(n), "reviews": real, "held": held,
                       "uncountable": {k: dict(c) for k, c in uncountable.items()}})
    row["rounds_closed"] = len(rounds)
    row["round_rows"] = rounds
    row["review_filter"] = vd.get("why")

    # trace
    ev = collections.defaultdict(lambda: {"answers": collections.Counter(), "answer_kinds": collections.Counter(),
                                          "accepted": collections.Counter(), "reject_heads": collections.Counter(),
                                          "relaunched": 0, "launch_not_ok": collections.Counter(), "role_wall_s": 0.0})
    role_rows = []   # op=role_run の行（その時点の版を添える）——費用の数え方は engine の role_run.session_costs が正本
    times, bad = [], 0
    cur = first
    try:
        with open(d / "trace.jsonl", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    t = json.loads(line)
                    if not isinstance(t, dict):
                        raise ValueError
                except ValueError:
                    bad += 1  # 走っている run の書きかけの最後の行もここに落ちる
                    continue
                ts = _ts(t.get("t"))
                if ts:
                    times.append(ts)
                op = t.get("op")
                if op == "engine_changed":
                    cur = t.get("version") or UNREAD_VERSION
                e = ev[cur]
                if op == "answer":
                    e["answers"][str(t.get("answer"))] += 1
                    e["answer_kinds"].update(str(k) for k in (t.get("kinds") or []))
                elif op == "role_run":
                    e["accepted"][f"accepted={t['accepted']}" if "accepted" in t else "accepted の欄なし"] += 1
                    if t.get("accepted") is False:
                        e["reject_heads"][head_of(t.get("why"))] += 1
                    if isinstance(t.get("wall_s"), (int, float)):
                        e["role_wall_s"] += t["wall_s"]
                    role_rows.append({**t, "_version": cur})
                elif op == "relaunched":
                    e["relaunched"] += 1
                elif op == "launched" and t.get("ok") is False:
                    e["launch_not_ok"][head_of(t.get("why"))] += 1
    except FileNotFoundError:
        parts.append("trace.jsonl が無い")
    except OSError as e:
        parts.append(f"trace.jsonl（{type(e).__name__}）")
    if bad:
        parts.append(f"trace.jsonl の読めない行 {bad}")
    cost = role_run_mod.session_costs(role_rows, group=lambda r: r["_version"])
    row["events"] = {v: {k: (dict(x) if isinstance(x, collections.Counter) else round(x, 1) if isinstance(x, float) else x)
                         for k, x in e.items()} for v, e in ev.items()}
    row["cost_usd"] = {v: round(c, 4) for v, c in cost.items()}
    if times:
        row["elapsed_min"] = round((max(times) - min(times)).total_seconds() / 60, 1)
        if row["status"] == "running":
            now = now or datetime.datetime.now(max(times).tzinfo)
            row["since_last_trace_min"] = round((now - max(times)).total_seconds() / 60, 1)
    row["unreadable_parts"] = parts
    return row


# ---------------------------------------------------------------- 版ごとに束ねる
def aggregate(rows):
    """run の行を版ごとに束ねる（盤面は読み直さない）"""
    agg = collections.defaultdict(lambda: {
        "runs": 0, "mixed_versions": 0, "status": collections.Counter(), "halted_by": collections.Counter(),
        "pending_human": 0, "elapsed_min": [], "since_last_trace_min": [], "rounds_closed": 0,
        "reviews": collections.defaultdict(collections.Counter), "held_review_rows": 0,
        "uncountable_reviews": collections.defaultdict(collections.Counter), "uncountable_review_rows": 0,
        "answers": collections.Counter(), "answer_kinds": collections.Counter(), "accepted": collections.Counter(),
        "reject_heads": collections.Counter(), "relaunched": 0, "launch_not_ok": collections.Counter(),
        "role_wall_s": 0.0, "cost_usd": 0.0, "unreadable_parts": 0, "review_filter": set()})
    for r in rows:
        if "unreadable" in r:
            a = agg[UNREADABLE]
            a["runs"] += 1
            a["status"][r["unreadable"]] += 1
            continue
        a = agg[r["version"]]
        a["runs"] += 1
        a["mixed_versions"] += len(r["versions"]) > 1
        a["status"][str(r["status"])] += 1
        if r.get("halted_by"):
            a["halted_by"][r["halted_by"]] += 1
        a["pending_human"] += r["pending_human"]
        a["unreadable_parts"] += bool(r["unreadable_parts"])
        if r.get("review_filter"):
            a["review_filter"].add(r["review_filter"])
        for k in ("elapsed_min", "since_last_trace_min"):
            if k in r:
                a[k].append(r[k])
        for rr in r["round_rows"]:
            b = agg[rr["version"]]
            b["rounds_closed"] += 1
            b["held_review_rows"] += rr["held"]
            for name, st in rr["reviews"].items():
                b["reviews"][name][str(st)] += 1
            for name, c in rr["uncountable"].items():
                b["uncountable_reviews"][name].update(c)
                b["uncountable_review_rows"] += sum(c.values())
        for v, e in r["events"].items():
            b = agg[v]
            for k in ("answers", "answer_kinds", "accepted", "reject_heads", "launch_not_ok"):
                b[k].update(e[k])
            b["relaunched"] += e["relaunched"]
            b["role_wall_s"] += e["role_wall_s"]
        for v, c in r["cost_usd"].items():
            agg[v]["cost_usd"] += c
    out = {}
    for v, a in agg.items():
        out[v] = {k: (sorted(x) if isinstance(x, set) else {n: dict(c) for n, c in sorted(x.items())} if k in ("reviews", "uncountable_reviews")
                      else dict(x.most_common()) if isinstance(x, collections.Counter) else x) for k, x in a.items()}
        for k in ("elapsed_min", "since_last_trace_min"):
            xs = a[k]
            out[v][k] = {"n": len(xs), "median": round(statistics.median(xs), 1) if xs else None}
        out[v]["cost_usd"] = round(a["cost_usd"], 2)
        out[v]["role_wall_s"] = round(a["role_wall_s"], 1)
    return out


def _vkey(v):
    return [(0, int(x)) if x.isdigit() else (1, x) for x in v.replace("-", ".").split(".")]


def _c(counter, top=None):
    items = list(counter.items())[:top] if top else list(counter.items())
    return " / ".join(f"{k} {n}" for k, n in items) or "なし"


def render(agg, total, roots_note):
    lines = [f"盤面 {total} 本（{roots_note}）。版は周の判定を周ごとの版、trace の行をその時の版、run の数を最後の版に数える"]
    for v in sorted(agg, key=_vkey):
        a = agg[v]
        lines.append(f"\n== {v} ==（run {a['runs']}・閉じた周 {a['rounds_closed']}・版が混在 {a['mixed_versions']}）")
        lines.append(f"状態: {_c(a['status'])}（止めた訳: {_c(a['halted_by'])}・今人待ち {a['pending_human']}）")
        for name, c in a["reviews"].items():
            lines.append(f"{name}（判定 {sum(c.values())}）: {_c(c)}")
        if a["held_review_rows"]:
            lines.append(f"判定から除いた機械の行・据え置きの行: {a['held_review_rows']}")
        if a["uncountable_review_rows"]:
            per = " / ".join(f"{name} {_c(c)}" for name, c in a["uncountable_reviews"].items())
            lines.append(f"数えられない R の行（今の述語が知らない鍵・値・辞書でない行・述語を引けない周）: "
                         f"{a['uncountable_review_rows']}（{per}）")
        for why in a["review_filter"]:
            lines.append(f"注意: {why}")
        lines.append(f"関所の答え（打った者は記録に無い）: {_c(a['answers'])}（kinds: {_c(a['answer_kinds'])}）")
        lines.append(f"受け付け: {_c(a['accepted'])}")
        if a["reject_heads"]:
            lines.append(f"拒否の頭（多い順 5）: {_c(a['reject_heads'], 5)}")
        lines.append(f"起こし直し {a['relaunched']}・launch が ok でない {sum(a['launch_not_ok'].values())}"
                     "（拒否が上限まで続いた試行を含む）")
        el, idle = a["elapsed_min"], a["since_last_trace_min"]
        lines.append(f"時間: 経過の中央値 {el['median']} 分（{el['n']} 本。人待ち・止めた間を含む）・役の実行の合計 "
                     f"{round(a['role_wall_s'] / 3600, 1)} 時間・running の最後の痕跡からの経過の中央値 {idle['median']} 分（{idle['n']} 本）")
        lines.append(f"費用: {a['cost_usd']} USD（会話ごとの最大の和）")
        if a["unreadable_parts"]:
            lines.append(f"一部が読めない run: {a['unreadable_parts']}（--runs の unreadable_parts）")
    return "\n".join(lines)


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="盤面を横断して run の質の数を engine の版ごとに束ねる（読むだけ）")
    ap.add_argument("roots", nargs="*", help="辿る根（既定: cwd のリポジトリの共有の git ディレクトリ）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--runs", action="store_true", help="run ごとの行を JSON Lines で出す")
    g.add_argument("--json", action="store_true", help="版ごとの集計を JSON で出す")
    a = ap.parse_args(argv)
    roots = [pathlib.Path(r).resolve() for r in a.roots] or [default_root()]
    verdicts = Verdicts()
    rows = []
    for i, root in enumerate(roots, 1):
        for d in find_boards(root):
            rel = d.relative_to(root).as_posix()
            rows.append(read_run(d, f"根{i}:{rel}" if len(roots) > 1 else rel, verdicts))
    if a.runs:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return 0
    agg = aggregate(rows)
    if a.json:
        print(json.dumps(agg, ensure_ascii=False, indent=1))
        return 0
    note = "根は共有の git ディレクトリ" if not a.roots else f"根 {len(roots)} 個"
    print(render(agg, len(rows), note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
