#!/usr/bin/env python3
"""特徴づけのテスト（graphloops/tests/py/test_golden_rules.py）の固定具と期待値を作る台本。期待値を手で書かない。

使い方:
    python3 golden_make.py expect              # 今の固定具から internal の層と覆いの一覧（coverage.json）を作り直す
    python3 golden_make.py expect --contract   # 外の約束（contract）の層も作り直す。作り直した理由は commit の文に書く
    python3 golden_make.py collect --real <盤面の置き場>... [--simulate] [--work <作業場>]
                                               # 盤面から固定具を作り直す（固定具を足す・入れ替えるとき。盤面はこの機械の上にしか無い）

手順 3 の作り替えの run が回すのは `expect` だけ。contract の層が変わったら、その差分が審査に出る（層は置き場で分けてある）。

collect のすること（どの固定具も同じ道を通る）:
1. 盤面を集める。実在の盤面（--real。固定具では origin=real）は最後の状態のまま読むだけで評価する——周で切って組み直さない
   （切り戻す材料が盤面に無く、切ると engine が一度も持たなかった状態になる）。筋書きの台本（--simulate: simulate.py・
   simulate_review.py）は、台本が loop.py を呼ぶ直前の盤面・対象リポジトリ・返答のファイルを写し（origin=simulate）、
   そのコマンドを固定具に持たせる——本物の途中の状態で、engine の入口（CLI）を通して当て直す
2. 記録する時点の置き換え（vcrpy の before_record と同じ考え方）: 盤面・対象リポジトリ・プラグインの置き場を印（<RUN> など）に、
   家・一時の置き場のパスの形を <HOME>・<TMPPATH> に、秘密の形を <SECRET> に置き換える
3. 基準の観察: 置き換えた盤面を一時の置き場に広げ、git だけは写した対象リポジトリで本物を走らせて答えを録る（ほかの子は締め口で止める）
4. 当て直しの確かめ: 録った答えだけで同じ観察になるか。ならない固定具は捨て、理由を出す
5. 選ぶ: 実在の盤面は全部、台本の写しは覆い（規則の名前ごとの結果）を新しく足す物を貪欲に選ぶ
6. 縮める: ファイル・欄・リストの要素を 1 つずつ外し、観察が変わらない物は落とす。続けて、残った文字列を 1 つずつ印に
   置き換え（同じ文字列は全部の所で同じ印に）、観察が同じ置き換えを受けるだけなら印のままにする——長さでなく評価の結果で決める
7. 1 つ 64 KB を超える固定具、禁じる形（家のパス・利用者名・秘密）が残る固定具は捨てる
"""
import argparse
import ast
import copy
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "py"))
sys.path.insert(0, str(HERE))
import golden_adapter as ga  # noqa: E402

SKIP_DIRS = {"prompts", "roles", "runs"}   # 盤面の下で規則が読まない物（役に渡したプロンプト・役の定義の写し・子の記録）


# ---------------------------------------------------------------- 置き換え
def generic_filters():
    home = str(pathlib.Path.home())
    return [(re.compile(r"sk-ant-[A-Za-z0-9_\-]+"), "<SECRET>"), (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "<SECRET>"),
            (re.compile(r"github_pat_[A-Za-z0-9_]+"), "<SECRET>"),
            (re.compile(re.escape(home)), "<HOME>"),
            (re.compile(r"(?:/private)?/(?:var/folders|tmp)/[^\s\"'`）)\]}>,;]*"), "<TMPPATH>"),
            (re.compile(r"/(?:Users|home)/[^/\s\"'`）)\]}>,;]+"), "<HOME>")]


def sanitize(obj, roots):
    """roots（(実パス, 印) を長い順）と、家・一時の置き場・秘密の形を置き換える"""
    # 実体の綴り（macOS の /var → /private/var）も同じ印に——engine は実体の綴りで書くので、片方だけだと "/private<REPO>" が残る
    pairs = sorted({(f, t) for p, t in roots for q in (p, pathlib.Path(p).resolve()) for f in ga._forms(q)}, key=lambda x: -len(x[0]))
    obj = ga._subst(obj, pairs)
    filters = generic_filters()

    def walk(o):
        if isinstance(o, str):
            for rx, rep in filters:
                o = rx.sub(rep, o)
            return o
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {walk(k): walk(v) for k, v in o.items()}
        return o
    return walk(obj)


def read_tree(base, skip=()):
    """base の下のファイルを {相対パス: JSON の値 | {ga.TEXT_KEY: 文字列}} に（.git と skip の置き場は読まない）"""
    out = {}
    if not base or not pathlib.Path(base).is_dir():
        return out
    base = pathlib.Path(base)
    for p in sorted(base.rglob("*")):
        rel = p.relative_to(base)
        if not p.is_file() or p.is_symlink() or rel.parts[0] in skip or ".git" in rel.parts:
            continue
        raw = p.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if p.suffix == ".json":
            try:
                out[rel.as_posix()] = json.loads(text)
                continue
            except ValueError:
                pass
        out[rel.as_posix()] = {ga.TEXT_KEY: text}
    return out


# ---------------------------------------------------------------- 集める
def real_candidates(dirs):
    got = []
    for d in dirs:
        d = pathlib.Path(d).resolve()
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
        loop = pathlib.Path(st["graph"]).stem   # 盤面の loop_name は TDD の流れでも review-loop（graph が引き継ぐ）
        roots = [(d, "<RUN>")]
        cwd = (st.get("inputs") or {}).get("cwd")
        if cwd:
            roots.append((cwd, "<REPO>"))
        eng = (st.get("engine") or {}).get("root")
        if eng:
            roots += [(eng, "<PLUGIN>"), (str(pathlib.Path(eng).parent), "<ROOT>")]
        roots += [(ga.PLUGIN, "<PLUGIN>"), (ga.ROOT, "<ROOT>")]
        files = sanitize(read_tree(d, SKIP_DIRS | {"current"}), roots)
        name = f"real-{st['run_id']}"
        got.append({"format": ga.fixture_format, "loop": loop, "origin": "real", "source": f"実在の盤面 {name[5:]}（{loop}）",
                    "files": files, "_name": name})
    return got


SIM_TESTS = {
    "simulate_review": ["test_converges", "test_request_entry", "test_gates_merge", "test_stop_after_round", "test_awaiting",
                        "test_rejections", "test_fix_plan_review", "test_rejudge_path", "test_human_gate", "test_spec_flow",
                        "test_stop_midround", "test_tdd_flow"],
    "simulate": ["test_converges", "test_attended_stuck_answer", "test_unattended_stuck", "test_light", "test_rejections"],
}


def snapshot_simulate(work):
    """台本を直列に回し、loop.py を呼ぶ直前の盤面・対象リポジトリ・返答のファイル・コマンドを work の下に写す"""
    snaps = []
    for modname, tests in SIM_TESTS.items():
        mod = __import__(modname)
        orig = mod.Run.cmd

        def cmd(self, *args, _orig=orig, _mod=modname, **kw):
            if args and args[0] in ga.REPLAY:
                n = len(snaps)
                d = work / f"snap-{n:05d}"
                d.mkdir(parents=True)
                if pathlib.Path(self.dir).is_dir():
                    shutil.copytree(self.dir, d / "board", symlinks=True, ignore=shutil.ignore_patterns("current"))
                shutil.copytree(self.repo, d / "repo", symlinks=True)
                if getattr(self, "cfg", None) and pathlib.Path(self.cfg).is_dir():
                    shutil.copytree(self.cfg, d / "config", symlinks=True)
                argv = [str(x) for x in args]
                for flag in ("--output", "--file"):
                    if flag in argv:
                        i = argv.index(flag) + 1
                        src = pathlib.Path(argv[i])
                        (d / "input").mkdir(exist_ok=True)
                        if src.is_file():
                            shutil.copy(src, d / "input" / src.name)
                        argv[i] = f"<INPUT>/{src.name}"
                env = kw.get("env") or getattr(self, "env", None) or {}
                meta = {"module": _mod, "test": CURRENT[0], "n": n, "argv": argv, "tmp": str(self.tmp), "dir": str(self.dir),
                        "repo": str(self.repo), "cfg": str(getattr(self, "cfg", "") or ""),
                        "session": (env or {}).get("CLAUDE_CODE_SESSION_ID") or ga.SESSION,
                        "loop": json.loads((pathlib.Path(self.dir) / "state.json").read_text(encoding="utf-8"))["loop_name"]
                        if (pathlib.Path(self.dir) / "state.json").is_file() else _loop_of_init(argv)}
                (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
                snaps.append(d)
            return _orig(self, *args, **kw)
        mod.Run.cmd = cmd
        for t in tests:
            CURRENT[0] = f"{modname}.{t}"
            print(f"  台本 {CURRENT[0]} を回す", flush=True)
            try:
                getattr(mod, t)()
            except Exception as e:  # noqa: BLE001 — 台本の失敗は写しの材料の欠けで、ここでは止めない
                print(f"    台本が例外で終わった（写しはそこまで）: {type(e).__name__}: {e}")
        mod.Run.cmd = orig
    return snaps


CURRENT = [""]


def _loop_of_init(argv):
    return argv[argv.index("--loop") + 1] if "--loop" in argv else "research-loop"


def sim_candidate(d):
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    st = d / "board" / "state.json"
    if st.is_file():   # 盤面の loop_name は TDD の流れでも review-loop——どの graph で回したかで決める
        meta["loop"] = pathlib.Path(json.loads(st.read_text(encoding="utf-8"))["graph"]).stem
    elif "--graph" in meta["argv"]:
        meta["loop"] = pathlib.Path(meta["argv"][meta["argv"].index("--graph") + 1]).stem
    roots = [(meta["dir"], "<RUN>"), (meta["repo"], "<REPO>")]
    if meta["cfg"]:
        roots.append((meta["cfg"], "<CFG>"))
    roots += [(meta["tmp"], "<TMP>"), (ga.PLUGIN, "<PLUGIN>"), (ga.ROOT, "<ROOT>")]
    fx = {"format": ga.fixture_format, "loop": meta["loop"], "origin": "simulate",
          "source": f"{meta['module']}.py の {meta['test'].split('.', 1)[1]} が loop.py {meta['argv'][0]} を呼ぶ直前（{meta['n']}）",
          "command": sanitize(meta["argv"], roots),
          "files": sanitize(read_tree(d / "board", SKIP_DIRS), roots), "repo": sanitize(read_tree(d / "repo"), roots),
          "config": sanitize(read_tree(d / "config"), roots), "input": sanitize(read_tree(d / "input"), roots),
          "_record_repo": d / "repo", "_name": f"sim-{meta['test'].split('.', 1)[1].removeprefix('test_')}-{meta['n']:05d}-{meta['argv'][0]}"}
    if meta["session"] != ga.SESSION:
        fx["session"] = meta["session"]
    if meta["loop"] == "review-loop-tdd":
        fx["_name"] = fx["_name"].replace("sim-", "sim-tdd-", 1)
    return fx


# ---------------------------------------------------------------- 観察
def run(fx, work):
    tmp = pathlib.Path(tempfile.mkdtemp(dir=work))
    try:
        return ga.observe(fx, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def clean(fx):
    return {k: v for k, v in fx.items() if not k.startswith("_")}


# ---------------------------------------------------------------- 縮める
class Shrinker:
    def __init__(self, fx, ref, work, budget):
        self.fx, self.ref, self.work, self.left = fx, ref, work, budget

    def same(self, cand, expect=None):
        if self.left <= 0:
            return False
        self.left -= 1
        obs, _ = run(cand, self.work)
        return ga.jsonable(obs) == ga.jsonable(expect if expect is not None else self.ref)

    def prune(self, root_key):
        """fx[root_key]（ファイルの表）の、ファイル・欄・要素を外せるだけ外す（盤面の state.json と record.json は残す）"""
        keep = {"state.json", "record.json"} if root_key == "files" else set()
        names = [k for k in (self.fx.get(root_key) or {}) if k not in keep]
        size = max(1, len(names) // 2)
        while size >= 1 and names and self.left > 0:
            i = 0
            while i < len(names) and self.left > 0:
                cand = copy.deepcopy(self.fx)
                for k in names[i:i + size]:
                    del cand[root_key][k]
                if self.same(cand):
                    self.fx = cand
                    names = names[:i] + names[i + size:]
                else:
                    i += size
            size //= 2
        for rel in list(self.fx.get(root_key) or {}):
            self._prune_at([root_key, rel], 0)

    def _get(self, path, fx=None):
        cur = fx if fx is not None else self.fx
        for k in path:
            cur = cur[k]
        return cur

    def _prune_at(self, path, depth):
        """path の下の欄・要素を、半分ずつ・4 分の 1 ずつ…1 つずつの塊で外す（ddmin と同じ刻み方）。外せなかった物の中へ下る"""
        node = self._get(path)
        if depth > 8 or not isinstance(node, (dict, list)) or not node or self.left <= 0:
            return
        size = max(1, len(node) // 2)
        while size >= 1 and self.left > 0:
            i = 0
            while i < len(self._get(path)) and self.left > 0:
                cand = copy.deepcopy(self.fx)
                target = self._get(path, cand)
                if isinstance(target, dict):
                    for k in list(target)[i:i + size]:
                        del target[k]
                else:
                    del target[i:i + size]
                if self.same(cand):
                    self.fx = cand
                else:
                    i += size
            size //= 2
        node = self._get(path)
        for k in (list(node) if isinstance(node, dict) else range(len(node))):
            if isinstance(self._get(path)[k], (dict, list)):
                self._prune_at(path + [k], depth + 1)

    def strings(self, protected):
        """残った文字列（葉と鍵）を 1 つずつ印に置き換え、観察が同じ置き換えを受けるだけなら印のままにする"""
        seen = {}

        def walk(o):
            if isinstance(o, str):
                seen[o] = seen.get(o, 0) + 1
            elif isinstance(o, list):
                for x in o:
                    walk(x)
            elif isinstance(o, dict):
                for k, v in o.items():
                    walk(k)
                    walk(v)
        names = set()
        for key in ("files", "repo", "config", "input", "git"):
            tree = self.fx.get(key) or {}
            if key != "git":
                names |= set(tree) | {ga.TEXT_KEY}   # ファイルの名前と本文の入れ物の鍵は置き換えない（盤面の欄がファイルを名指す）
                for v in tree.values():
                    walk(v)
            else:
                walk(tree)
        cands = sorted((s for s in seen if len(s) >= 4 and s not in protected and s not in names
                        and not any(t in s for t in ga.TOKENS)), key=lambda s: -len(s))
        mapping = {}
        for i, s in enumerate(cands):
            # 印は OS を問わずファイル名に使える字だけで作り、長さは保つ（型の最小長の検査に当たらないように）
            tok = f"_s{i}_"
            mapping[s] = tok + "x" * max(0, len(s) - len(tok))
        self._accept_groups(cands, mapping)

    def _apply(self, fx, group, mapping):
        m = {s: mapping[s] for s in group}

        def walk(o):
            if isinstance(o, str):
                return m.get(o, o)
            if isinstance(o, list):
                return [walk(x) for x in o]
            if isinstance(o, dict):
                return {walk(k): walk(v) for k, v in o.items()}
            return o
        out = dict(fx)
        for key in ("files", "repo", "config", "input", "git"):
            if key in fx:
                out[key] = {k: walk(v) for k, v in fx[key].items()} if key != "git" else walk(fx[key])
        return out

    def _accept_groups(self, cands, mapping):
        stack = [cands]
        while stack and self.left > 0:
            group = stack.pop()
            if not group:
                continue
            cand = self._apply(self.fx, group, mapping)
            pairs = sorted(((s, mapping[s]) for s in group), key=lambda x: -len(x[0]))
            expect = ga._subst(copy.deepcopy(self.ref), pairs)
            if self.same(cand, expect):
                self.fx, self.ref = cand, expect
            elif len(group) > 1:
                mid = len(group) // 2
                stack += [group[mid:], group[:mid]]


def protected_strings():
    """規則・graph・検証器・engine が字面で持つ文字列（語彙・節の名前・欄の名前）。これは置き換えの候補にしない"""
    got = set()
    for p in list((ga.PLUGIN / "rules").glob("*.py")) + list((ga.PLUGIN / "engine").glob("*.py")) + list((ga.ROOT / "scripts").glob("*-record.py")) + [ga.ROOT / "scripts" / "record_common.py"]:
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                got.add(n.value)

    def walk(o):
        if isinstance(o, str):
            got.add(o)
        elif isinstance(o, list):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            for k, v in o.items():
                got.add(k)
                walk(v)
    for g in (ga.PLUGIN / "graphs").glob("*.json"):
        walk(json.loads(g.read_text(encoding="utf-8")))
    return got


def forbidden_hits(fx):
    return ga.forbidden_in(json.dumps(clean(fx), ensure_ascii=False))


# ---------------------------------------------------------------- 書く
def write_expectations(contract_too):
    per_loop = {}
    work = pathlib.Path(tempfile.mkdtemp(prefix="golden-expect-"))
    for f in ga.fixture_paths():
        fx = ga.load_fixture(f)
        obs, _ = run(fx, work)
        obs = ga.jsonable(obs)
        for layer in ("internal",) + (("contract",) if contract_too else ()):
            p = ga.expect_path(layer, f)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(obs[layer], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        per_loop.setdefault(fx["loop"], []).append(obs["internal"].get("calls", []))
    shutil.rmtree(work, ignore_errors=True)
    cov = {loop: ga.coverage(loop, per_loop.get(loop, [])) for loop in ga.LOOPS}
    (ga.GOLDEN / "expect" / "coverage.json").write_text(json.dumps(cov, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for loop in ga.LOOPS:
        rows = [(t, n, r) for t, names in cov[loop].items() for n, r in names.items()]
        c = sum(1 for *_, r in rows if "covered" in r)
        called = sum(1 for *_, r in rows if "called" in r)
        print(f"{loop}: 覆った {c}・呼ばれた（手続き）{called}・覆っていない {len(rows) - c - called} / {len(rows)}")


def check():
    work = pathlib.Path(tempfile.mkdtemp(prefix="golden-check-"))
    bad = 0
    for f in ga.fixture_paths():
        obs = ga.jsonable(run(ga.load_fixture(f), work)[0])
        for layer in ("contract", "internal"):
            want = json.loads(ga.expect_path(layer, f).read_text(encoding="utf-8"))
            if obs[layer] != want:
                bad += 1
                print(f"違う {f.parent.name}/{f.name} {layer}: {json.dumps(ga.diff(want, obs[layer]), ensure_ascii=False)[:400]}")
    shutil.rmtree(work, ignore_errors=True)
    print(f"突き合わせ {len(ga.fixture_paths())} 件・違い {bad}")
    return bad


def _reference(fx, work):
    """基準の観察と、録った git の答えだけでの当て直しの確かめ ——(固定具, 基準, 覆いの組) か (None, 捨てた理由)"""
    work = pathlib.Path(work)
    if "<TMPPATH>" in json.dumps(fx.get("command") or [], ensure_ascii=False):
        return None, "コマンドが固定具の外の一時のファイルを名指す（写していないので当て直せない）"
    ref, w = run(fx, work)
    if fx.get("_record_repo") is not None:
        fx["git"] = {k: v for k, v in w.recorded.items() if k in w.used}
        fx.pop("_record_repo")
        again, w2 = run(fx, work)
        if ga.jsonable(again) != ga.jsonable(ref) or w2.missed:
            return None, f"録った git の答えだけでは同じ観察にならない（引き当て損ね {len(w2.missed)}）"
    ref = ga.jsonable(ref)
    pairs = {(fx["loop"], t, n, o) for t, n, o in ref["internal"].get("calls", [])}
    cmd = ref["contract"].get("command")
    if cmd is not None:   # 入口（CLI のコマンド）と終わり方の組も覆いに数える
        pairs.add((fx["loop"], "CLI", fx["command"][0], str(cmd.get("exit", "blocked"))))
    return fx, (ref, sorted(pairs))


def _shrink(fx, ref, work, budget, protected):
    """縮めて確かめる ——(書く本文, None) か (None, 捨てた理由)"""
    t0 = time.time()
    s = Shrinker(fx, ref, pathlib.Path(work), budget)
    for key in ("files", "repo", "config", "input"):
        s.prune(key)
    s.strings(protected)
    final = clean(s.fx)
    runs = [ga.jsonable(run(final, pathlib.Path(work))[0]) for _ in range(3)]
    body = json.dumps(final, ensure_ascii=False, indent=1) + "\n"
    if any(r != s.ref for r in runs):
        return None, "縮めた後の観察が基準と違う（3 回のどれかで。走らせるたびに変わる物を読んでいる）"
    if len(body.encode("utf-8")) > ga.size_limit:
        return None, f"縮めても {len(body.encode('utf-8'))} バイト（上限 {ga.size_limit}）"
    if forbidden_hits(final):
        return None, f"禁じる形が残る: {forbidden_hits(final)[:3]}"
    return body, f"{len(body.encode('utf-8'))} バイト（{time.time() - t0:.0f} 秒・残りの試行 {s.left}）"


def collect(args):
    import concurrent.futures
    import multiprocessing
    work = pathlib.Path(args.work or tempfile.mkdtemp(prefix="golden-make-")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    cands = real_candidates(args.real or [])
    if args.snaps:
        snaps = sorted(d for s in args.snaps for d in pathlib.Path(s).iterdir() if (d / "meta.json").is_file())
        cands += [sim_candidate(d) for d in snaps]
    elif args.simulate:
        snaps = snapshot_simulate(work / "snaps")
        cands += [sim_candidate(d) for d in snaps]
    print(f"候補 {len(cands)}", flush=True)
    pool_ex = concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs, mp_context=multiprocessing.get_context("spawn"))
    cache = work / "refs"
    cache.mkdir(exist_ok=True)
    kept, todo = [], []
    for fx in cands:
        c = cache / f"{fx['_name']}.json"
        if c.is_file():   # 前の collect が作った基準を使い直す（実在の盤面は動くので、--real の物は毎回作り直す）
            got = json.loads(c.read_text(encoding="utf-8"))
            if fx["origin"] != "real":
                if got.get("dropped"):
                    continue
                kept.append((got["fx"], got["ref"], {tuple(x) for x in got["pairs"]}))
                continue
        todo.append(fx)
    futs = {pool_ex.submit(_reference, fx, str(work)): fx for fx in todo}
    for f in concurrent.futures.as_completed(futs):
        fx0 = futs[f]
        fx, got = f.result()
        c = cache / f"{fx0['_name']}.json"
        if fx is None:
            print(f"  捨てる {fx0['_name']}: {got}", flush=True)
            c.write_text(json.dumps({"dropped": got}, ensure_ascii=False), encoding="utf-8")
            continue
        ref, pairs = got
        c.write_text(json.dumps({"fx": fx, "ref": ref, "pairs": pairs}, ensure_ascii=False, default=str), encoding="utf-8")
        kept.append((fx, ref, {tuple(x) for x in pairs}))
    # 選ぶ: 実在は全部、写しは覆いを新しく足す物を貪欲に
    chosen = [k for k in kept if k[0]["origin"] == "real"]
    have = set().union(*(k[2] for k in chosen)) if chosen else set()
    pool = sorted((k for k in kept if k[0]["origin"] != "real"), key=lambda k: k[0]["_name"])
    while pool and (not args.max_fixtures or len(chosen) < args.max_fixtures):
        best = max(pool, key=lambda k: (len(k[2] - have), -len(json.dumps(clean(k[0]), ensure_ascii=False))))
        gain = best[2] - have
        if not gain:
            break
        chosen.append(best)
        have |= gain
        pool.remove(best)
    print(f"選んだ {len(chosen)}（実在 {sum(1 for k in chosen if k[0]['origin'] == 'real')}）", flush=True)
    protected = protected_strings()
    out_dir = ga.GOLDEN / "fixtures"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    futs = {pool_ex.submit(_shrink, fx, ref, str(work), args.budget, protected): fx for fx, ref, _ in chosen}
    for f in concurrent.futures.as_completed(futs):
        fx = futs[f]
        body, why = f.result()
        if body is None:
            print(f"  捨てる {fx['_name']}: {why}", flush=True)
            continue
        p = out_dir / fx["loop"] / f"{fx['_name']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        print(f"  {p.relative_to(ga.GOLDEN)}: {why}", flush=True)
    pool_ex.shutdown()
    for layer in ("contract", "internal"):
        d = ga.GOLDEN / "expect" / layer
        if d.exists():
            shutil.rmtree(d)
    write_expectations(True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("expect")
    e.add_argument("--contract", action="store_true", help="外の約束の層も作り直す")
    c = sub.add_parser("collect")
    c.add_argument("--real", nargs="*", help="実在の盤面の置き場")
    c.add_argument("--simulate", action="store_true", help="筋書きの台本の途中の状態も写す")
    c.add_argument("--work", help="作業場（写しを置く。既定は一時の置き場）")
    c.add_argument("--snaps", nargs="*", help="snap が写した置き場（<作業場>/snaps）を使い直す（いくつでも）")
    c.add_argument("--budget", type=int, default=1500, help="固定具 1 つを縮める試行の上限")
    c.add_argument("--max-fixtures", type=int, default=0, help="固定具の数の上限（0 は上限なし——覆いが増えなくなるまで選ぶ）")
    c.add_argument("--jobs", type=int, default=4, help="基準の観察と縮めを並べるプロセスの数")
    sub.add_parser("check", help="今の固定具を評価し直して期待値と突き合わせる（別の PYTHONHASHSEED で回すと、走らせるたびに変わる物が分かる）")
    s = sub.add_parser("snap")
    s.add_argument("--work", required=True, help="台本の途中の状態を写す置き場（<work>/snaps）")
    s.add_argument("--tests", help="台本を絞る（simulate_review.test_x,simulate.test_y）。既定は SIM_TESTS の全部")
    a = p.parse_args()
    if a.cmd == "expect":
        write_expectations(a.contract)
    elif a.cmd == "check":
        bad = check()
        sys.exit(1 if bad else 0)
    elif a.cmd == "snap":
        if a.tests:
            SIM_TESTS.clear()
            for x in a.tests.split(","):
                m, name = x.split(".")
                SIM_TESTS.setdefault(m, []).append(name)
        snaps = snapshot_simulate(pathlib.Path(a.work).resolve() / "snaps")
        print(f"写した {len(snaps)}")
    else:
        collect(a)


if __name__ == "__main__":
    main()
