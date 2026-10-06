"""範囲の相談（blk-fix。持ち主 2026-10-06。設計 docs/plans/2026-10-06-ask-planner.md）: 修正役か下請けが sandbox の中の Bash で
走らせ、修正案を書いた役の会話を再開して「この項目の範囲を広げてよいか」を 1 問 1 答する機械のコマンド。

語:
- 相談の控え（CONFIG）: 支度の節が run ごとの置き場（盤面の隣。盤面は役の Bash が書けない）の今の scope の下の PLACE に書く
  {board, repo, session_file, config_dir, claude, model, effort, items, scope, python, base_rev, tdd_state, pass}。
  session_file は包みが記録した相談の相手の会話の id（<包みの家>/sessions/<cwd の hash>/<印の名>.id）、config_dir は元の
  Claude の設定の置き場、items は項目の番号（文字列）→ {unit_keys, allowed_paths, out_of_scope, tests}
- 写しの会話: 元の transcript（<config_dir>/projects/<cwd の名>/<id>.jsonl）を置き場の HOME（私物の設定の置き場）の同じ所へ写した物。
  元の設定の置き場は柵で書けず、元の会話を変えない約束なので、写しで `--resume` する（fork しない）。返った会話の id を
  STATE に控え、次の相談はそれを継ぐ。元の id が替われば写し直す
- 記録（LOG）: 1 相談 1 行 {id, at, item, unit_keys, paths, tests, why, status, decision, granted_paths, granted_tests, spec, reason,
  notes, session, auth, why_refused?, why_unavailable?}。status は REFUSED（先の確かめで断った）・ANSWERED・INVALID（答えの形が
  崩れた）・UNAVAILABLE（聞けない）。受け付けが settle で盤面の trace（conflict.ASKED_OP）へ写す

口:
- write_config・load_config: 控え
- screen(cfg, item, paths, tests): 先の確かめ（断る文か None）
- judge(answer, paths, tests): 答えの確かめ（(行の欄 | None, 注記)）。許すのは頼んだ物の中だけ
- ask(cfg, item, paths, tests, why, *, env, run, resolve): 1 相談（錠の下で 1 つずつ）。返りは記録の行
- exchanges(place)・settle(b, place): 記録を読む・盤面の trace へまだ無い行を写す
- main(argv): コマンド。答えの 1 行の JSON を出し、終了コード 0（答えた・断った）・3（聞けない・形の崩れた答え）・2（使い方）

トークンは子の環境にだけ置き、記録・標準出力に出さない（出どころの名だけ）。認証は works の殻と同じ auth_launch.resolve。
期限は持たない。Python 3.9 でも動く形で書く（役の sandbox の python3 で走りうる）。
"""
import argparse
import datetime
import fcntl
import json
import os
import pathlib
import posixpath
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
for _p in (_CORE, _CORE / "graphloops"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

import auth_launch  # noqa: E402   L1。works の殻が Archon を起こす時と同じ認証の順
import planmarks  # noqa: E402   glob の当て方の正本
from engine import role_run  # noqa: E402   L0 の写し。--output-format json の包みの読み（unwrap）

CONFIG = "ask-plan.json"
PLACE = "ask-plan"          # run ごとの置き場の今の scope の下
LOG = "exchanges.jsonl"
STATE = "session.json"      # {source, head}
HOME = "claude-home"        # 私物の設定の置き場
LOCK = "ask.lock"
REFUSED, ANSWERED, INVALID, UNAVAILABLE = "refused", "answered", "invalid", "unavailable"
ALLOW, DENY, DEFER = "allow", "deny", "defer"
DECISIONS = (ALLOW, DENY, DEFER)
MIN_WHY = 10
TOOLS = "Read,Grep,Glob"    # 相談の相手は読むだけ

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["decision", "paths", "tests", "spec", "reason"],
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "paths": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "tests": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "spec": {"type": "string"},
        "reason": {"type": "string", "minLength": MIN_WHY},
    },
}

QUESTION = """\
# 範囲の相談（修正の段から）

あなたがこの会話で書いた修正案の項目 {item}（単位: {units}）を直している側から、範囲の相談が来た。範囲を広げるかは仕様の判断で、
決めるのはあなた。案を書いた時の考えと、今のリポジトリ（Read・Grep・Glob で読める）で決めよ。

- 項目の今の範囲（allowed_paths）: {allowed}
- 触らない物（out_of_scope）: {oos}
- 足したいパス: {paths}
- 書き換えたい既存のテストの範囲（<パス> か <パス>:<行>）: {tests}
- 理由（直している側の文）:
{why}

答えは次の JSON だけ:
- decision: allow（範囲に足してよい）・deny（足さない。範囲の中で直せ）・defer（今の run では直さない。次の run の仕事）
- paths: 足してよいパス（頼まれた物の中から。allow の時だけ）
- tests: 書き換えてよいテストの範囲（頼まれた物の中から。allow の時だけ。期待を実装に合わせるための書き換えは許すな）
- spec: 直す側が従う仕様の補い（無ければ空）
- reason: 決めた理由（10 字以上）
"""


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_config(place, doc: dict) -> pathlib.Path:
    """控えを place/CONFIG に書く（一時のファイルから置き換える）。返りはそのパス"""
    place = pathlib.Path(place)
    place.mkdir(parents=True, exist_ok=True)
    path = place / CONFIG
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(path))
    return path


def load_config(path) -> dict:
    """控えを読み、置き場（place。控えの在るフォルダ）を足す。読めなければ ValueError"""
    path = pathlib.Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"相談の控え {path} を読めない: {e}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), dict):
        raise ValueError(f"相談の控え {path} の形が違う（items が無い）")
    return {**doc, "place": str(path.parent)}


def _norm(p: str) -> str:
    return posixpath.normpath(str(p).strip())


def _limit_path(lim: str) -> str:
    """テストの範囲 <パス>[:<行>[-<行>]] のパス"""
    head, sep, tail = lim.rpartition(":")
    return _norm(head) if sep and tail.replace("-", "").isdigit() else _norm(lim)


def _inside(path: str, it: dict) -> bool:
    return path in [_norm(t.split("::")[0]) for t in it.get("tests") or []] or \
        any(planmarks.glob_match(path, g) for g in it.get("allowed_paths") or [])


def screen(cfg: dict, item: str, paths: list, tests: list):
    """AI に聞く前に断る文（通れば None）: 知らない項目・頼む物が無い・根の外のパス・out_of_scope に当たる（修正案が明示に
    外したパス。外すのは案の誤りの道で、相談でない）・足したいパスがもう範囲の中"""
    it = (cfg.get("items") or {}).get(str(item))
    if it is None:
        return f"項目 {item} は承認済みの修正案に無い（在る項目: {sorted(cfg.get('items') or {})}）"
    if not paths and not tests:
        return "足したいパスも書き換えたいテストも無い（何も頼んでいない）"
    for p in [_norm(x) for x in paths] + [_limit_path(x) for x in tests]:
        if planmarks.climbs(p):
            return f"{p} はリポジトリの根の外"
        hit = next((g for g in it.get("out_of_scope") or [] if planmarks.glob_match(p, g)), None)
        if hit:
            return (f"{p} は項目 {item} の out_of_scope（{hit}）に当たる——修正案が明示に外したパスで、相談では足さない。要るなら"
                    "食い違いの申し出で返せ（案の項目そのものの誤り）")
    inside = [p for p in (_norm(x) for x in paths) if _inside(p, it)]
    if inside:
        return f"{inside} はもう項目 {item} の範囲の中（聞かずに直してよい）"
    return None


def judge(answer, paths: list, tests: list):
    """答えの確かめ。返り (行の欄 {decision, granted_paths, granted_tests, spec, reason} | None, 注記の文の列)。
    allow は頼んだ物の中だけを許し（足した物は捨てて注記）、何も残らなければ形の崩れ。deny・defer は何も許さない"""
    if not isinstance(answer, dict):
        return None, ["答えが JSON のオブジェクトでない"]
    d, reason = answer.get("decision"), answer.get("reason")
    notes = []
    if d not in DECISIONS:
        notes.append(f"decision が {list(DECISIONS)} のどれでもない: {d!r}")
    if not isinstance(reason, str) or len(reason.strip()) < MIN_WHY:
        notes.append(f"reason が無いか {MIN_WHY} 字に満たない")
    if notes:
        return None, notes
    out = {"decision": d, "granted_paths": [], "granted_tests": [], "spec": answer.get("spec") or "", "reason": reason}
    if d != ALLOW:
        return out, []
    want_p, want_t = [_norm(p) for p in paths], [str(t).strip() for t in tests]
    for field, want, key in (("paths", want_p, "granted_paths"), ("tests", want_t, "granted_tests")):
        for x in answer.get(field) or []:
            x = _norm(x) if field == "paths" else str(x).strip()
            if x in want:
                if x not in out[key]:
                    out[key].append(x)
            else:
                notes.append(f"頼んでいない {field} の {x} を許した答え（捨てた）")
    if not out["granted_paths"] and not out["granted_tests"]:
        return None, notes + ["allow なのに頼んだ物の中で許した物が無い"]
    return out, notes


def question(cfg: dict, item: str, paths: list, tests: list, why: str) -> str:
    it = cfg["items"][str(item)]
    show = lambda xs: "・".join(xs) if xs else "（無し）"   # noqa: E731
    return QUESTION.format(item=item, units=show(it.get("unit_keys") or []), allowed=show(it.get("allowed_paths") or []),
                           oos=show(it.get("out_of_scope") or []), paths=show(paths), tests=show(tests),
                           why="\n".join("  " + line for line in why.strip().splitlines()))


def exchanges(place) -> list:
    """記録の行（古い順。壊れた行は飛ばす）"""
    try:
        text = (pathlib.Path(place) / LOG).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _append(place: pathlib.Path, row: dict) -> None:
    with open(str(place / LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


class Unavailable(Exception):
    """聞けない（会話の記録が無い・認証が無い・claude が落ちた）"""


def _read_state(place: pathlib.Path) -> dict:
    try:
        doc = json.loads((place / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _session(cfg: dict, place: pathlib.Path) -> tuple:
    """(再開する会話の id, 私物の設定の置き場, 元の id)。元の id の写しが無ければ写す（元の transcript は読むだけ）"""
    try:
        source = pathlib.Path(cfg["session_file"]).read_text(encoding="utf-8").strip()
    except (OSError, KeyError, TypeError) as e:
        raise Unavailable(f"相談の相手の会話の id の記録を読めない（{cfg.get('session_file')}: {e}）") from None
    if not source:
        raise Unavailable(f"相談の相手の会話の id の記録が空（{cfg.get('session_file')}）")
    home = place / HOME
    state = _read_state(place)
    if state.get("source") == source and state.get("head"):
        return state["head"], home, source
    hits = sorted((pathlib.Path(cfg.get("config_dir") or "") / "projects").glob(f"*/{source}.jsonl"))
    if not hits:
        raise Unavailable(f"相談の相手の会話の記録（{cfg.get('config_dir')}/projects/*/{source}.jsonl）が無い")
    dest = home / "projects" / hits[0].parent.name / hits[0].name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(hits[0]), str(dest))
    _write_state(place, {"source": source, "head": source})
    return source, home, source


def _write_state(place: pathlib.Path, doc: dict) -> None:
    tmp = place / (STATE + ".tmp")
    tmp.write_text(json.dumps(doc) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(place / STATE))


def _argv(cfg: dict, head: str) -> list:
    argv = [cfg.get("claude") or "claude", "-p", "--resume", head, "--output-format", "json",
            "--json-schema", json.dumps(ANSWER_SCHEMA, ensure_ascii=False), "--tools", TOOLS, "--allowedTools", TOOLS,
            "--setting-sources", "user"]
    for flag in ("model", "effort"):
        if cfg.get(flag):
            argv += [f"--{flag}", str(cfg[flag])]
    return argv


def _answer(stdout: bytes):
    """(答えの dict か None, 返った会話の id, 読めない理由)。包みの structured_output を先に、無ければ result の文を JSON で読む"""
    try:
        env = json.loads(stdout.decode("utf-8", "replace"))
    except ValueError:
        env = None
    text, summary, why = role_run.unwrap(stdout)
    sid = summary.get("session_id")
    if why:
        return None, sid, why
    if isinstance(env, dict) and isinstance(env.get("structured_output"), dict):
        return env["structured_output"], sid, None
    try:
        return json.loads(text or ""), sid, None
    except ValueError:
        return None, sid, "答えが JSON でない"


def ask(cfg: dict, item, paths: list, tests: list, why: str, *, env=None, run=subprocess.run,
        resolve=auth_launch.resolve) -> dict:
    """1 相談（模块の頭）。錠（置き場の LOCK）の下で 1 つずつ。返りは記録に積んだ行"""
    place = pathlib.Path(cfg["place"])
    place.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ if env is None else env)
    item = str(item)
    with open(str(place / LOCK), "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        n = 1 + max((r.get("id", 0) for r in exchanges(place) if isinstance(r.get("id"), int)), default=0)
        it = (cfg.get("items") or {}).get(item) or {}
        row = {"id": n, "at": _now(), "item": item, "unit_keys": list(it.get("unit_keys") or []), "paths": list(paths),
               "tests": list(tests), "why": why, "decision": None, "granted_paths": [], "granted_tests": [], "spec": "",
               "reason": "", "notes": [], "session": None, "auth": None}
        refusal = screen(cfg, item, paths, tests)
        if refusal:
            row.update(status=REFUSED, why_refused=refusal)
        else:
            row.update(_ask(cfg, place, item, paths, tests, why, env, run, resolve))
        _append(place, row)
        return row


def _ask(cfg, place, item, paths, tests, why, env, run, resolve) -> dict:
    try:
        head, home, source = _session(cfg, place)
        got, name, missing = resolve(env, env.get("HOME") or str(pathlib.Path.home()), cfg.get("config_dir") or "")
        if got is None:
            raise Unavailable(f"認証が無い: {missing}")
        child = auth_launch.child_env(env, got, bool(env.get("WORKS_KEYCHAIN_ITEM")))
        child["CLAUDE_CONFIG_DIR"] = str(home)
        p = run(_argv(cfg, head), input=question(cfg, item, paths, tests, why).encode("utf-8"), capture_output=True,
                cwd=cfg.get("repo") or None, env=child)
        if p.returncode != 0:
            raise Unavailable(f"claude が終了コード {p.returncode} で終わった: {(p.stderr or b'').decode('utf-8', 'replace')[-300:]}")
        answer, sid, bad = _answer(p.stdout or b"")
    except (Unavailable, OSError) as e:
        return {"status": UNAVAILABLE, "why_unavailable": str(e)}
    if sid:
        _write_state(place, {"source": source, "head": sid})
    out = {"session": {"from": head, "id": sid}, "auth": name}
    if bad:
        return {**out, "status": INVALID, "notes": [bad]}
    fields, notes = judge(answer, paths, tests)
    if fields is None:
        return {**out, "status": INVALID, "notes": notes}
    return {**out, **fields, "status": ANSWERED, "notes": notes}


def settle(b, place) -> list:
    """記録の行のうち、盤面の trace（conflict.ASKED_OP）にまだ無い id の行を写す（受け付けの頭。sandbox の外）。返りは写した行"""
    import conflict   # L3（遅らせて読む: コマンドの python3 では盤面の模块を読まない）
    known = {r.get("id") for r in conflict.plan_asks(b)}
    new = [r for r in exchanges(place) if r.get("id") not in known]
    for r in new:
        b.trace(conflict.ASKED_OP, **{k: v for k, v in r.items() if k != "op"})
    return new


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="askplan.py", description="範囲の相談（修正案を書いた役の会話を再開して 1 問 1 答）")
    ap.add_argument("config", help="相談の控え（指示書に書かれたパス）")
    ap.add_argument("--item", required=True, help="修正案の項目の番号")
    ap.add_argument("--paths", default="", help="足したいパス（リポジトリの根からの相対。カンマ区切り）")
    ap.add_argument("--tests", default="", help="書き換えたい既存のテストの範囲 <パス>[:<行>]（カンマ区切り）")
    ap.add_argument("--why", required=True, help=f"理由（{MIN_WHY} 字以上）")
    a = ap.parse_args(argv)
    if len(a.why.strip()) < MIN_WHY:
        print(f"askplan: --why は {MIN_WHY} 字以上（なぜ範囲の外が要るか・何を変えるか）", file=sys.stderr)
        return 2
    try:
        cfg = load_config(a.config)
    except ValueError as e:
        print(f"askplan: {e}", file=sys.stderr)
        return 2
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]   # noqa: E731
    row = ask(cfg, a.item, split(a.paths), split(a.tests), a.why)
    shown = {k: row.get(k) for k in ("id", "status", "decision", "granted_paths", "granted_tests", "spec", "reason", "notes",
                                     "why_refused", "why_unavailable") if row.get(k) not in (None, [], "")}
    print(json.dumps(shown, ensure_ascii=False))
    return 3 if row["status"] in (UNAVAILABLE, INVALID) else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
