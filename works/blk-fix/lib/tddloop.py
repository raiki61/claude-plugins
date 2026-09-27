"""修正のブロックの単位ごとの TDD の輪（MVP。設計 2 節 3・案 (i)。graph は変えず、ブロックの中で回す）。

節と関数:
- tdd-start → start: 入力 tdd_suite（JUnit XML の書き先を第 1 引数に受け、リポジトリの根で走る実行ファイル。本線と同じ約束）が
  空なら何もせず go: false（全部の単位を今どおり直す）。在れば一式を 1 回走らせて元の結末を取り、盤面の tdd-<k>/ に状態を置く
- tdd-loop の中: tdd-prep → prep（今の段の指示書を fixrules で組んで書く。full と delta の 2 つの形）→ 役 tdd（修正役。
  同じ会話で振り分け・テスト・直し・整えを返す）→
  tdd-step → step（返答を機械が確かめて段を進める）。段は route → 単位ごとに test → fix → refactor → 次の単位
  - route: 直す義務の単位を全部 1 度だけ tdd か direct（理由 10 字以上）に振る
  - test: 申告したテストのファイルの外に触れていない・写しの red_problems（名指しは failure で落ち、元で通っていた物は緑）
  - fix: その単位のテストのファイルが赤の時から変わっていない・写しの green_problems
  - refactor: 緑の時から何も変えていなければ none。変えたなら fix と同じ確かめをもう 1 回
  拒めば同じ段のまま、理由は次の指示書（と reason_file）に載る。段ごとに RETRY_MAX 回目の拒否で諦める: test・fix は作業ツリーを
  単位の頭に戻して direct へ、refactor は緑の時の木に戻す。実行器が走らない・回数の上限に届いた時は、残りを全部 direct にして抜ける
  （輪は done の印で抜け、max_iterations に届いて落ちない。R50）
- fix-accept → frozen_problems: 輪で緑になった単位のテストのファイルを、輪の後の修正役が変えていないか
- collect → exit_fields: 出口の欄 tdd（単位ごとの道・赤・緑・整え・direct の理由）
赤・緑の判定は写しの rules（review-loop-tdd.py）の関数を呼ぶ（写さない）。版は一時の index（GIT_INDEX_FILE）で木に固める
（本物の index・HEAD・枝は動かさない。.gitignore に当たる物は載らない）。期限は持たない。
"""
import hashlib
import json
import os
import pathlib
import posixpath
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

import board  # noqa: E402
import fixrules  # noqa: E402  （同じブロックの lib。指示書の組み立て）
import tree_run  # noqa: E402
from leftovers import Unreadable, git, git_names  # noqa: E402

RULES_GRAPH = "review-loop-tdd.json"
PHASES = ("route", "test", "fix", "refactor")
MAX_ITERATIONS = 40   # YAML の tdd-loop の max_iterations と同じ値（試験が縛る）。この周に届いたら残りを direct にして抜ける
MIN_WHY = 10
STATE, PROMPT, SUMMARY = "state.json", "next.md", "summary.md"
NO_SUITE = "テストの実行器（入力 tdd_suite）が無い run——全部の単位を今どおり直す"
SUITE_MADE_NOTE = "一式を走らせて出来たファイル"


class Broken(Exception):
    """回す側の誤り（状態が読めない・輪が済んだ後に呼んだ・入力の形が違う）。節は 2 で落ちる"""


class _RunnerDown(Exception):
    """実行器が走らない・JUnit が読めない（テストや直しの誤りではない。やり直しの回数を使わずに輪を抜ける）"""


_RULES = []


def rules():
    """写しの TDD 版の rules（red_problems・green_problems・RETRY_MAX・parse_junit）。1 回だけ読む"""
    if not _RULES:
        _RULES.append(board.rules_module(board.graph_path(RULES_GRAPH)))
    return _RULES[0]


def retry_max() -> int:
    return rules().RETRY_MAX


# ---------------------------------------------------------------- 版を木に固める・戻す
def snapshot(repo) -> str:
    """作業ツリーの今の姿（未追跡の新しいファイルも。.gitignore に当たる物は除く）の木の sha。本物の index は触らない"""
    with tempfile.TemporaryDirectory(prefix="works-tdd-index-") as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(pathlib.Path(td) / "index")}
        if _has_head(repo):
            git(repo, "read-tree", "HEAD", env=env)
        git(repo, "add", "-A", "--", ":/", env=env)
        return git(repo, "write-tree", env=env).strip()


def _has_head(repo) -> bool:
    try:
        git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        return True
    except Unreadable:
        return False


def touched(repo, a: str, b: str) -> list:
    """木 a から木 b で変わったパス（足した・消したを含む）"""
    return sorted(set(git_names(repo, "diff-tree", "-r", "--name-only", "--no-renames", a, b)))


def restore(repo, tree: str) -> list:
    """作業ツリーを木 tree の姿に戻す（その後に変わった・足した・消したファイルだけ）。戻したパスを返す"""
    paths = touched(repo, tree, snapshot(repo))
    if not paths:
        return []
    keep = set(paths) & set(git_names(repo, "ls-tree", "-r", "--name-only", tree))
    for p in paths:
        if p not in keep:
            f = pathlib.Path(repo) / p
            if f.is_file() or f.is_symlink():
                f.unlink()
    if keep:
        with tempfile.TemporaryDirectory(prefix="works-tdd-index-") as td:
            env = {**os.environ, "GIT_INDEX_FILE": str(pathlib.Path(td) / "index")}
            git(repo, "read-tree", tree, env=env)
            git(repo, "checkout-index", "-f", "--", *sorted(keep), env=env)
    return paths


def hashes(repo, files) -> dict:
    """ファイル → 中身の sha256（無ければ None）"""
    out = {}
    for f in files:
        p = pathlib.Path(repo) / f
        out[f] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    return out


# ---------------------------------------------------------------- 一式を走らせる
def run_suite(exe: str, repo, work: pathlib.Path, n: int):
    """実行器を 1 回走らせる ——（結末の一覧, 終了コード, 問題）。結末が取れなければ一覧は None。
    .py はこの Python で走らせる（写しの rules の run_suite と同じ）。出力は work/suite-<n>.log に丸ごと"""
    argv = ([sys.executable] if exe.endswith(".py") else []) + [exe]
    junit = work / f"junit-{n}.xml"
    log = work / f"suite-{n}.log"
    env = {**tree_run.outside_env(os.environ), "PYTHONDONTWRITEBYTECODE": "1"}
    with open(log, "wb") as out:
        try:
            rc = tree_run.run([*argv, str(junit)], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                              cwd=str(repo), env=env)
        except OSError as e:
            return None, None, [f"テストの実行器を起こせない（{type(e).__name__}: {e}。ログ {log}）"]
    if not junit.is_file():
        return None, rc, [f"テストの実行器が JUnit XML を書かなかった（exit {rc}。ログ {log}）"]
    try:
        cases = rules().parse_junit(junit.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:   # ET.ParseError（写しの rules の中の型）
        return None, rc, [f"JUnit XML が読めない（{e}。ログ {log}）"]
    finally:
        junit.unlink(missing_ok=True)
    return cases, rc, []


def _key(c) -> str:
    return f"{c['classname']}::{c['name']}"   # 写しの rules の _key と同じ形（元の結末の鍵）


# ---------------------------------------------------------------- 状態
def _load(state_file) -> dict:
    try:
        return json.loads(pathlib.Path(state_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Broken(f"TDD の輪の状態が読めない（{state_file}: {e}）")


def _save(state_file, st: dict) -> None:
    p = pathlib.Path(state_file)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _open_units(raw: str) -> list:
    try:
        keys = json.loads(raw)
    except ValueError as e:
        raise Broken(f"open_units が JSON として読めない（{e}）")
    if not isinstance(keys, list) or not all(isinstance(k, str) and k for k in keys):
        raise Broken(f"open_units が単位の key の配列でない（{raw[:200]!r}）")
    return keys


def _unit(key, route, why="") -> dict:
    return {"unit_key": key, "route": route, "why": why, "tests": [], "test_files": [], "red": "", "green": "",
            "refactor": "", "gave_up": "", "problems": [], "files": [], "what": ""}


def start(board_dir, repo, suite: str, open_units: str) -> dict:
    """節 tdd-start。{go, reason, suite, state_file, summary_file}。実行器が無ければ何も書かずに go: false"""
    suite = (suite or "").strip()
    off = {"go": False, "reason": NO_SUITE, "suite": suite, "state_file": "", "summary_file": ""}
    if not suite:
        return off
    keys = _open_units(open_units)
    exe = pathlib.Path(suite) if pathlib.Path(suite).is_absolute() else pathlib.Path(repo) / suite
    if not exe.is_file() or not (suite.endswith(".py") or os.access(exe, os.X_OK)):
        return {**off, "reason": f"テストの実行器 {suite} が無いか実行できない——全部の単位を今どおり直す"}
    board_dir = pathlib.Path(board_dir)
    board_dir.mkdir(parents=True, exist_ok=True)
    k = 1
    while (board_dir / f"tdd-{k}").exists():
        k += 1
    work = board_dir / f"tdd-{k}"
    work.mkdir()
    cases, code, why = run_suite(str(exe), repo, work, 0)
    if cases is None:
        return {**off, "reason": f"元の結末が取れない（{'; '.join(why)}）——全部の単位を今どおり直す"}
    st = {"suite": suite, "exe": str(exe), "work": str(work), "open_units": keys,
          "baseline": {_key(c): c["outcome"] for c in cases}, "baseline_exit": code,
          "handoff": snapshot(repo), "suite_made": [], "phase": "route", "tries": 0, "reason": "", "iterations": 0,
          "runs": 1, "order": [], "units": {}, "queue": [], "cur": 0, "unit_head": "", "green_tree": "",
          "done": False, "note": "", "frozen": {}}
    state_file = work / STATE
    _save(state_file, st)
    return {"go": True, "reason": "", "suite": suite, "state_file": str(state_file), "summary_file": str(work / SUMMARY)}


# ---------------------------------------------------------------- 指示書（節 tdd-prep）
RETURN = {
    "route": '{"phase": "route", "units": [{"unit_key": "<単位の key>", "route": "tdd" か "direct", "why": "<direct の理由。10 字以上>"}]}',
    "test": '{"phase": "test", "unit_key": "<今の単位>", "test_files": ["<書いたテストのファイル>"], '
            '"tests": ["<パス>::<クラス>::<テストの名前>"]}  （先にテストを書けないと分かったら {"phase": "test", '
            '"unit_key": "<今の単位>", "direct_why": "<理由。10 字以上>"}）',
    "fix": '{"phase": "fix", "unit_key": "<今の単位>", "files": ["<直したファイル>"], "what": "<何をどう直したか>"}',
    "refactor": '{"phase": "refactor", "unit_key": "<今の単位>", "what": "<何を整えたか。整える物が無ければそう書く>"}',
}
DO = {
    "route": "直す義務の単位を全部、ちょうど 1 度ずつ振り分けよ。tdd＝直す前に落ち、直した後に通るテストをリポジトリのテスト一式に"
             "書ける単位。direct＝先にテストを書けない単位（文書・指示書・注記・設定だけの直しなど）で、理由を 10 字以上で書く。"
             "この段では作業ツリーを変えるな。",
    "test": "今の単位の欠陥を再現する、今は落ちるテストだけを書け（実装は直すな。テストのファイルの外を触るな）。テストは今の版に在る"
            "名前だけで再現するか、import をテストの中に入れよ。機械が一式を走らせ、名指しのテストが failure で落ち、元で通っていた"
            "テストが通ることを確かめる（error・もう通る・飛ばされた、は拒む）。",
    "fix": "今の単位だけを直せ。テストのファイルは変えるな（凍っている。テストの誤りに気づいたら直さずに what に書け）。機械が一式を"
           "走らせ、名指しのテストと元で通っていたテストが通ることを確かめる。",
    "refactor": "緑のまま、今の単位の差分を整えよ（重複・名前・不要になったコード。テストのファイルは変えない）。整える物が無ければ"
                "何も変えずに返せ。変えたなら機械がもう 1 回緑を確かめる。",
}


def prep(state_file, values: dict | None = None, repo=None) -> dict:
    """節 tdd-prep。今の段の指示書を組み（fixrules.tdd_render: 修正の決まりの正本・TDD の決まり・今の段の約束・run の値）、状態の
    置き場の next.md（full の写し）と隣の next.full.md・next.delta.md・next.variants.json に書き、{prompt_file} を返す。
    values は fixrules.TDD_VALUES の run の値（義務の単位は状態の物を使う。欠けは空）。repo は差分から変更の種類を選ぶ根（None は見ない）"""
    st = _load(state_file)
    if st["done"]:
        raise Broken("TDD の輪は済んでいる（tdd-prep を呼ぶ番でない）")
    phase = st["phase"]
    title = f"# TDD の輪の指示書（{st['iterations'] + 1} 回目・段 {phase}）"
    lines = ["## この段ですること", "", DO[phase], ""]
    if phase == "route":
        lines += ["## 直す義務の単位", ""] + [f"- {k}" for k in st["open_units"]] + [""]
    else:
        u = st["units"][st["queue"][st["cur"]]]
        lines += ["## 今の単位", "", f"- {u['unit_key']}", ""]
        if u["tests"]:
            lines += [f"- 名指しのテスト: {', '.join(u['tests'])}", f"- テストのファイル（凍っている）: {', '.join(u['test_files'])}", ""]
        left = st["queue"][st["cur"] + 1:]
        if left:
            lines += ["この後の tdd の単位（今は手を付けるな）: " + " / ".join(left), ""]
    lines += ["## テストの回し方", "",
              f"リポジトリの根で `{st['exe']} <JUnit XML の書き先>`（書き先は /tmp の下など作業ツリーの外に）。", "",
              "## 返す JSON", "", RETURN[phase]]
    vals = {**{k: "" for k in fixrules.TDD_VALUES}, **(values or {}),
            "open_units": json.dumps(st["open_units"], ensure_ascii=False)}
    path = pathlib.Path(st["work"]) / PROMPT
    n = st["iterations"] + 1

    def build(kinds, prior, rules_file):
        try:
            return fixrules.tdd_render(vals, phase, "\n".join(lines), title=title, reason=st["reason"], kinds=kinds,
                                       prior=prior, iteration=n, rules_file=rules_file)
        except fixrules.Unfilled as e:
            raise Broken(f"TDD の輪の指示書を組めない: {e}")
    fixrules.write_variants(path, repo, vals, build, n)
    return {"prompt_file": str(path)}


# ---------------------------------------------------------------- 返答の確かめ（節 tdd-step）
def _blank(s) -> bool:
    return not isinstance(s, str) or len(s.strip()) < MIN_WHY


def _paths(v, name) -> tuple:
    """空でない文字列の配列 → (正規化したパスの一覧, 問題)"""
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
        return [], [f"{name} は空でない文字列の配列"]
    out = [posixpath.normpath(x.strip()) for x in v]
    bad = [x for x in out if x.startswith("/") or x == ".." or x.startswith("../")]
    return out, ([f"{name} はリポジトリの根からの相対パス（{bad}）"] if bad else [])


def _run(st, repo):
    """一式を走らせ、走らせて出来たファイルを suite_made に積む（テストを書く段が触ったファイルの数えから外す）"""
    pre = snapshot(repo)
    cases, code, why = run_suite(st["exe"], repo, pathlib.Path(st["work"]), st["runs"])
    st["runs"] += 1
    st["suite_made"] = sorted(set(st["suite_made"]) | set(touched(repo, pre, snapshot(repo))))
    if cases is None:
        raise _RunnerDown("; ".join(why))
    return cases, code


def _cur(st) -> dict:
    return st["units"][st["queue"][st["cur"]]]


def _next_unit(st, repo) -> None:
    if st["cur"] < len(st["queue"]):
        st.update(phase="test", tries=0, reason="", unit_head=snapshot(repo), green_tree="")
    else:
        st["done"] = True


def _to_direct(u, stage, why, probs=()) -> None:
    u.update(route="direct", gave_up=stage, why=why, problems=list(probs)[:10])


def _route(st, reply, repo) -> list:
    rows = reply.get("units")
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("unit_key"), str) for r in rows):
        return ["units は {unit_key（文字列）, route, why} の配列"]
    errs = []
    moved = sorted(set(touched(repo, st["handoff"], snapshot(repo))) - set(st["suite_made"]))
    if moved:
        errs.append(f"振り分けの段で作業ツリーを変えた: {moved[:5]}（この段では何も書かない）")
    keys = [r.get("unit_key") for r in rows]
    owed = st["open_units"]
    errs += [f"'{k}' を 2 度以上振った" for k in dict.fromkeys(k for k in keys if keys.count(k) > 1)]
    errs += [f"直す義務の単位 '{k}' を振っていない" for k in owed if k not in keys]
    errs += [f"'{k}' は直す義務の単位に無い" for k in dict.fromkeys(k for k in keys if k not in owed)]
    for r in rows:
        if r.get("route") not in ("tdd", "direct"):
            errs.append(f"'{r.get('unit_key')}' の route は tdd か direct（{r.get('route')!r}）")
        elif r["route"] == "direct" and _blank(r.get("why")):
            errs.append(f"'{r.get('unit_key')}' は direct なのに、先にテストを書けない理由（why。{MIN_WHY} 字以上）が無い")
    if errs:
        return errs
    st["order"] = keys
    st["units"] = {r["unit_key"]: _unit(r["unit_key"], r["route"], (r.get("why") or "").strip() if r["route"] == "direct" else "")
                   for r in rows}
    st["queue"] = [k for k in keys if st["units"][k]["route"] == "tdd"]
    st["cur"] = 0
    _next_unit(st, repo)
    return []


def _test(st, reply, repo) -> list:
    u = _cur(st)
    if "direct_why" in reply:
        if _blank(reply["direct_why"]):
            return [f"direct_why は {MIN_WHY} 字以上"]
        restore(repo, st["unit_head"])
        _to_direct(u, "writer", reply["direct_why"].strip())
        st["cur"] += 1
        _next_unit(st, repo)
        return []
    tests = reply.get("tests")
    errs = [] if isinstance(tests, list) and tests and all(isinstance(t, str) and t.strip() for t in tests) \
        else ["tests は名指しのテスト（<パス>::<クラス>::<名前>）の空でない配列"]
    files, bad = _paths(reply.get("test_files"), "test_files")
    errs += bad
    if errs:
        return errs
    extra = sorted(set(touched(repo, st["unit_head"], snapshot(repo))) - set(files) - set(st["suite_made"]))
    if extra:
        return [f"申告したテストのファイルの外に触れた: {extra[:5]}——この段はテストだけを書く（実装は次の段）"]
    cases, code = _run(st, repo)
    probs = rules().red_problems(tests, cases, code, st["baseline"])
    if probs:
        return probs
    u.update(tests=tests, test_files=files, red="ok", test_hashes=hashes(repo, files))
    st.update(phase="fix", tries=0, reason="")
    return []


def _frozen_moved(u, repo) -> list:
    now = hashes(repo, u["test_files"])
    return [f for f in u["test_files"] if now[f] != u["test_hashes"][f]]


def _green(st, u, repo) -> list:
    moved = _frozen_moved(u, repo)
    if moved:
        return [f"テストのファイルを赤の時から書き換えた: {moved}——テストは凍っている（テストの誤りは what に書け）"]
    cases, code = _run(st, repo)
    return rules().green_problems(u["tests"], cases, code, st["baseline"], st["baseline_exit"])


def _fix(st, reply, repo) -> list:
    u = _cur(st)
    files = reply.get("files")
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files) or not isinstance(reply.get("what"), str) \
            or not reply["what"].strip():
        return ["files（直したファイルの配列）と what（何をどう直したか）が要る"]
    probs = _green(st, u, repo)
    if probs:
        return probs
    u.update(green="ok", files=files, what=reply["what"].strip())
    st.update(phase="refactor", tries=0, reason="", green_tree=snapshot(repo))
    return []


def _refactor(st, reply, repo) -> list:
    u = _cur(st)
    if not isinstance(reply.get("what"), str) or not reply["what"].strip():
        return ["what（何を整えたか。整える物が無ければそう書く）が要る"]
    moved = set(touched(repo, st["green_tree"], snapshot(repo))) - set(st["suite_made"])
    if moved:
        probs = _green(st, u, repo)
        if probs:
            return probs
    u["refactor"] = "ok" if moved else "none"
    st["cur"] += 1
    _next_unit(st, repo)
    return []


def _give_up(st, repo, probs) -> None:
    """段の RETRY_MAX 回目の拒否"""
    head = f"{retry_max()} 回とも通らなかった: {probs[0][:200]}"
    if st["phase"] == "route":
        _abort(st, repo, "振り分けの返答が " + head, "route")
        return
    u = _cur(st)
    if st["phase"] == "refactor":
        restore(repo, st["green_tree"])
        u.update(refactor="reverted", problems=probs[:10])
    else:
        restore(repo, st["unit_head"])
        stage = "red" if st["phase"] == "test" else "green"
        _to_direct(u, stage, f"TDD の{'赤' if stage == 'red' else '緑'}の確認が " + head, probs)
    st["cur"] += 1
    _next_unit(st, repo)


def _abort(st, repo, why, stage) -> None:
    """残りの tdd の単位を全部 direct にして輪を抜ける（実行器が走らない・回数の上限・振り分けを諦めた）"""
    st["note"] = why
    if st["phase"] == "route":
        st["order"] = list(st["open_units"])
        st["units"] = {k: _unit(k, "direct") for k in st["order"]}
        for u in st["units"].values():
            _to_direct(u, stage, why)
    else:
        u = _cur(st)
        if st["phase"] == "refactor":
            restore(repo, st["green_tree"])
            u["refactor"] = "reverted"
        else:
            restore(repo, st["unit_head"])
            _to_direct(u, stage, why)
        for k in st["queue"][st["cur"] + 1:]:
            _to_direct(st["units"][k], stage, why)
    st["done"] = True


def step(state_file, reply, repo) -> dict:
    """節 tdd-step。{ok（この返答を受けた）, done（輪を抜ける）, reason, phase（次の段）}"""
    st = _load(state_file)
    if st["done"]:
        raise Broken("TDD の輪は済んでいる（tdd-step を呼ぶ番でない）")
    phase = st["phase"]
    if not isinstance(reply, dict):
        probs = ["返答が JSON のオブジェクトでない"]
    elif reply.get("phase") != phase:
        probs = [f"今の段は {phase}（返答の phase は {reply.get('phase')!r}）"]
    elif phase != "route" and reply.get("unit_key") != st["queue"][st["cur"]]:
        probs = [f"今の単位は '{st['queue'][st['cur']]}'（返答の unit_key は {reply.get('unit_key')!r}）"]
    else:
        try:
            probs = {"route": _route, "test": _test, "fix": _fix, "refactor": _refactor}[phase](st, reply, repo)
        except _RunnerDown as e:
            _abort(st, repo, f"テストの実行器が走らない: {e}", "runner")
            probs = [st["note"]]
    if probs and not st["done"]:
        st["tries"] += 1
        st["reason"] = "\n".join(f"- {p}" for p in probs)
        if st["tries"] >= retry_max():
            _give_up(st, repo, probs)
    st["iterations"] += 1
    if not st["done"] and st["iterations"] >= MAX_ITERATIONS:
        _abort(st, repo, f"TDD の輪の回数の上限（{MAX_ITERATIONS} 回）に届いた", "budget")
    if st["done"]:
        _finish(st, repo)
    st["handoff"] = snapshot(repo)
    _save(state_file, st)
    return {"ok": not probs, "done": st["done"], "reason": "\n".join(probs), "phase": "done" if st["done"] else st["phase"]}


def _finish(st, repo) -> None:
    """輪の後の修正役へ渡す summary.md と、凍ったテストのファイルの控え（frozen）"""
    passed = [st["units"][k] for k in st["order"] if st["units"][k]["route"] == "tdd"]
    st["frozen"] = hashes(repo, sorted({f for u in passed for f in u["test_files"]}))
    lines = ["# TDD の輪の結果（機械が書いた）", ""]
    if st["note"]:
        lines += [f"輪を途中で抜けた: {st['note']}", ""]
    lines += ["## 輪で直した単位（直さず、changes に 1 行を書け。テストのファイルは変えるな——受け付けが拒む）", ""]
    for u in passed:
        lines += [f"- {u['unit_key']}", f"  - 名指しのテスト（機械が赤→緑を確かめた）: {', '.join(u['tests'])}",
                  f"  - テストのファイル: {', '.join(u['test_files'])}", f"  - 直したファイル: {', '.join(u['files'])}",
                  f"  - 直し: {u['what']}", f"  - 整え: {u['refactor']}"]
    lines += ["", "## direct の単位（ここで直せ）", ""]
    lines += [f"- {st['units'][k]['unit_key']}: {st['units'][k]['why']}" for k in st["order"] if st["units"][k]["route"] == "direct"]
    (pathlib.Path(st["work"]) / SUMMARY).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 輪の後
def frozen_problems(state_file, repo) -> list:
    """輪で緑になった単位のテストのファイルが、輪が済んだ時から変わっていれば、その文（状態が無ければ空）"""
    if not state_file:
        return []
    st = _load(state_file)
    now = hashes(repo, st["frozen"])
    moved = [f for f, h in st["frozen"].items() if now[f] != h]
    return [f"TDD の輪で凍ったテストのファイルを書き換えた: {moved}（輪で直した単位のテストは変えない）"] if moved else []


FIELDS = ("unit_key", "route", "why", "tests", "test_files", "red", "green", "refactor", "gave_up", "problems")


def exit_fields(start_out: dict) -> dict:
    """出口の欄 tdd: {ran, suite, reason, units: [{unit_key, route, why, tests, test_files, red, green, refactor, gave_up, problems}]}"""
    if not isinstance(start_out, dict) or not start_out.get("go"):
        so = start_out if isinstance(start_out, dict) else {}
        return {"ran": False, "suite": so.get("suite", ""), "reason": so.get("reason", ""), "units": []}
    st = _load(start_out["state_file"])
    if not st["done"]:
        raise Broken("TDD の輪が済んでいない（done の印が無い）")
    return {"ran": True, "suite": st["suite"], "reason": st["note"],
            "units": [{f: st["units"][k][f] for f in FIELDS} for k in st["order"]]}
