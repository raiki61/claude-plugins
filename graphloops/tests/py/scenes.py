"""層 2 の筋書き（T2）: 出来事の列のデータ・回し手 Driver・役の表・前置きの控え。規範は docs/adr/0067。

1 本の列（history）は、台本の関数の中の Run 1 つが打った出来事を元の順に並べたデータで、頭は init。筋書きの行は列の途中の印
（mark）を指し、前置き（given）はその印の手前の出来事の全部、when は印の付いた出来事になる——行が手前の出来事を選んで落とす
口を持たない。列が元の関数の出来事を落としていないことは、被覆の道具（cover_moved.py の --no-cov）が元の関数の Run と
loop.py の呼び出しの列・最後の盤面で突き合わせる。

- **回し手**（Driver）: 出来事を 1 つ受けて（返事, 盤面）を返す。口（port）は glharness.driven の inproc か cli。until は台本の
  drive を名前で引いて回す（台本を消す run で本体を移す——写すと、台本の drive と写しのずれを見る柵が無い）
- **役の表**（ROLES）: 名前 → 台本の返答の表（answers・base_answers）の名前と、節ごとの手直し（返答の上書き・同じ節への先打ちの出来事）
- **控え**（Scenes）: 列の接頭辞ごとに作業場をまるごと控え、行は控えから写し戻して始める。作業場の置き場は列ごとに 1 か所に
  固定する（盤面の中の絶対パスを書き換えない。waves.py と同じ）
- 列を作る手が台本の check を撃ったら例外で止める（準備の段で走った check は件数の柵の数えの外で落ちる）
"""
import copy
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

import glharness
import pytest
import waves

GIVEN_PROPERTY = "gl_given"   # テストが使った前置きの鍵（junitxml に載る。cover_moved.py が読む）
HISTORIES = {}   # 列の名前 → History
ROLES = {}       # 役の表の名前 → {"base": 台本の返答の表の名前, "rules": [手直し]}
ROWS = {}        # 台本の関数 → {(列, 印の位置)}——控えを残す位置と、被覆の道具が突き合わせる列
PROCS = ("init", "cmd", "done", "validate")   # 返事が子の終わり方（rc・標準出力・標準エラー）の出来事
WRITE_ROOTS = ("dir", "repo", "tmp")           # 世界の手が書いてよい run の置き場（盤面・型のリポジトリ・作業場）


def _ev(kind, mark, **kw):
    return {"ev": kind, **kw, **({"mark": mark} if mark else {})}


def init(name, mark=None, graph_drop=(), **run):
    """Run の種（台本の Run の引数）。graph_drop は同梱の graph の写しから落とす頂上の鍵（init の版が古い run の形）"""
    return _ev("init", mark, name=name, run=run, **({"graph_drop": list(graph_drop)} if graph_drop else {}))


def until(roles, stop=None, catch=False, mark=None):
    """役の表 roles で next と答えを回す。stop は {"ready": 節}・{"round": k（以上）}・{"got": 印}。catch は回しの例外を返事にする"""
    return _ev("until", mark, roles=roles, **({"stop": stop} if stop else {}), **({"catch": True} if catch else {}))


def nxt(mark=None):
    return _ev("next", mark)


def cmd(*args, mark=None):
    """loop.py の語。引数の file(...) は run の作業場に書いた JSON のファイルの道に替わる"""
    return _ev("cmd", mark, args=list(args))


def file(name, value=None, ref=None):
    """cmd の引数に置く JSON のファイル。ref は (列, 印, "state"|"record", 道...) ——別の列のその印の盤面から値を読む"""
    return {"file": name, **({"ref": list(ref)} if ref else {"json": value})}


def done(node, value=None, merge=None, agent_id=None, mark=None):
    """節への返答。node の "@" は手直しの中で答えている instance。merge は台本の答えに重ねる（手直しの中だけ）"""
    return _ev("done", mark, node=node, reply={"merge": merge} if merge is not None else {"set": value},
               **({"agent_id": agent_id} if agent_id else {}))


def write(root, path, text):
    """世界の手: run の作業場（dir・repo・tmp）の下にファイルを書く"""
    return _ev("write", None, root=root, path=path, text=text)


def look(mark):
    """盤面（state・record・周の記録）をその時点で控える"""
    return _ev("look", mark)


def prompt(mark):
    """手直しの中で答えている節のプロンプトの本文を控える"""
    return _ev("prompt", mark)


def validate(mark=None):
    """検証器を子プロセスで起こす（台本と同じ口）"""
    return _ev("validate", mark)


def loop(step, answer, times, mark=None):
    """step（until）を人待ちの間だけ繰り返し、そのたびに answer を打つ（times 回まで）。返事は step の返事の並び"""
    return _ev("loop", mark, step=step, answer=answer, times=times)


def merged(value, at=None):
    """返答の手直し: 台本の答えに value を重ねる（at は重ねる先の道。例 ("plan", 0)）"""
    return {"merge": value} if at is None else {"merge_at": list(at), "with": value}


def replaced(value):
    return {"set": value}


def rule(node, round=None, once=None, before=(), reply=None):
    """役の表の手直し 1 つ: 節 node（round の周だけ・once の印がまだ無い間だけ）に、before の出来事を先に打ち、reply で答えを直す"""
    return {"node": node, **({"round": round} if round is not None else {}), **({"once": once} if once else {}),
            "before": list(before), **({"reply": reply} if reply else {})}


def _register(table, name, value, what):
    if name in table and table[name] != value:
        raise ValueError(f"{what} {name} を別の中身で登録し直した")
    table[name] = value
    return value


def roles(name, *rules, base=None):
    """役の表: 台本の返答の表 base（既定は name）と、節ごとの手直し"""
    return _register(ROLES, name, {"base": base or name, "rules": list(rules)}, "役の表")


class History:
    def __init__(self, name, events):
        self.name, self.kind, self.events = name, name.split("/", 1)[0], tuple(events)
        marks = [e["mark"] for e in self.events if "mark" in e]
        if self.kind not in glharness.SCRIPTS or not self.events or self.events[0]["ev"] != "init":
            raise ValueError(f"列 {name}: 名前の頭が review か research で、頭の出来事が init でない")
        if len(set(marks)) != len(marks):
            raise ValueError(f"列 {name}: 同じ印が 2 度在る: {marks}")

    def at(self, mark):
        """印の付いた出来事の位置（1 から）"""
        for i, e in enumerate(self.events, 1):
            if e.get("mark") == mark:
                return i
        raise KeyError(f"列 {self.name} に印 {mark} が無い")

    def __eq__(self, other):
        return isinstance(other, History) and (self.name, self.events) == (other.name, other.events)


def history(name, *events):
    return _register(HISTORIES, name, History(name, events), "列")


def refs(ev):
    """出来事が値を借りる別の列の位置 [(列, 位置)]"""
    return [(a["ref"][0], HISTORIES[a["ref"][0]].at(a["ref"][1])) for a in ev.get("args", ()) if isinstance(a, dict) and "ref" in a]


def lineage(name, k):
    """列 name の 1〜k の接頭辞と、そこが値を借りた列の接頭辞の鍵（被覆の道具が前置きの作りを数える文脈の名前）"""
    out = []
    for j in range(1, k + 1):
        for r in refs(HISTORIES[name].events[j - 1]):
            out += [x for x in lineage(*r) if x not in out]
        out.append(f"{name}@{j}")
    return out


# ---- 返事と盤面 ---------------------------------------------------------------------------------------------------------

class Proc(dict):
    """子の終わり方の返事（rc・out・err。cmd の返事は書いた JSON のファイルの値 files も持つ）"""
    returncode = property(lambda self: self["rc"])
    stdout = property(lambda self: self["out"])
    stderr = property(lambda self: self["err"])

    def json(self):
        return json.loads(self["out"])


def _stored(reply):
    if isinstance(reply, subprocess.CompletedProcess):
        return {"rc": reply.returncode, "out": reply.stdout or "", "err": reply.stderr or ""}
    return json.loads(json.dumps(reply, ensure_ascii=False))


def view(kind, stored):
    return Proc(stored) if kind in PROCS else stored


class Board:
    """盤面を読むだけの口（run の盤面の置き場と型のリポジトリ）"""

    def __init__(self, dir, repo=None):
        self.dir, self.repo = pathlib.Path(dir), repo and pathlib.Path(repo)

    def _json(self, rel):
        return json.loads((self.dir / rel).read_text(encoding="utf-8"))

    def state(self):
        return self._json("state.json")

    def record(self):
        return self._json("record.json")

    def round(self, n):
        return self._json(f"rounds/round-{n}.json")

    def has(self, rel=""):
        return (self.dir / rel).exists()

    def lines(self, rel):
        return (self.dir / rel).read_text(encoding="utf-8").splitlines()

    def read(self, path):
        """盤面が名指すファイル（差分・方針の写しなど）の本文"""
        return pathlib.Path(path).read_text(encoding="utf-8")


def _board(run):
    return Board(run.dir, run.repo)


class Scene:
    """行が見る物: when の返事（reply）・その後の盤面（board）・列の途中で印を付けた出来事の返事（got）"""

    def __init__(self, reply, board, got):
        self.reply, self.board, self.got = reply, board, got


NONE = Proc(rc=None, out="", err="")   # 打たれなかった出来事の返事（got.get(印, NONE)）


def _ends(s, n=160):
    s = str(s or "").strip()
    return s if len(s) <= 2 * n else f"{s[:n]}…{s[-n:]}"


def digest(s):
    """落ちた行の観測値: when の返事の要点と盤面の要点"""
    r = s.reply
    if isinstance(r, Proc):
        head = f"rc={r.returncode} out={_ends(r.stdout)!r} err={_ends(r.stderr)!r}"
    elif isinstance(r, list):
        head = "返事の並び=" + str([(x.get("status"), (x.get("ask") or {}).get("kinds")) for x in r])
    elif isinstance(r, dict):
        head = (f"status={r.get('status')} round={r.get('round')} ask={(r.get('ask') or {}).get('kinds')}"
                + (f" raised={_ends(r['raised'])!r}" if "raised" in r else ""))
    else:
        head = f"返事={_ends(r)!r}"
    try:
        st = s.board.state()
    except OSError:
        return head + " 盤面: 無い"
    return (head + f" 盤面: status={st.get('status')} round={st.get('round')} max_rounds={st.get('max_rounds')} "
            f"halted={st.get('halted')} stop_reason={(st.get('loop') or {}).get('stop_reason')}")


# ---- 回し手 ---------------------------------------------------------------------------------------------------------------

def _graph_copy(kind, drop):
    root = pathlib.Path(tempfile.mkdtemp(prefix=f"gl-{kind}-nostop-"))
    for sub in ("prompts", "rules", "graphs", "blocks"):
        shutil.copytree(glharness.PLUGIN / sub, root / sub)
    gp = root / "graphs" / f"{kind}-loop.json"
    g = json.loads(gp.read_text(encoding="utf-8"))
    for k in drop:
        g.pop(k)
    gp.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    return root, gp


def _reply(spec, out):
    if spec is None:
        return None
    if "set" in spec:
        return copy.deepcopy(spec["set"])
    if "merge" in spec:
        return {**out, **copy.deepcopy(spec["merge"])}
    got = copy.deepcopy(out)
    *head, last = spec["merge_at"]
    at = got
    for k in head:
        at = at[k]
    at[last] = {**at[last], **copy.deepcopy(spec["with"])}
    return got


class Driver:
    """出来事を 1 つ受けて（返事, 盤面）を返す回し手。got は印を付けた出来事の返事（[出来事の種類, 値]）"""

    def __init__(self, kind, port="inproc", scenes=None, run=None, got=None):
        self.kind, self.port, self.scenes = kind, port, scenes
        self.mod = glharness.script(kind)
        self.run, self.got = run, copy.deepcopy(got or {})

    def __enter__(self):
        self._driven = glharness.driven(self.mod, self.port)
        self._driven.__enter__()
        return self

    def __exit__(self, *exc):
        return self._driven.__exit__(*exc)

    def step(self, ev, inst=None, out=None):
        before = glharness.tallies()
        stored = _stored(EVENTS[ev["ev"]](self, ev, inst, out))
        if glharness.tallies() != before:
            raise RuntimeError(f"出来事 {ev['ev']} の間に台本の check が走った（列を作る手は check を撃たない）: {ev}")
        if "mark" in ev:
            self.got[ev["mark"]] = [ev["ev"], stored]
        return stored, self.run and _board(self.run)

    def hook(self, rules):
        """台本の drive に渡す hook: 役の表の手直しを当てる（当たらない節は台本の答えのまま）"""
        def hook(run, inst, out):
            for r in rules:
                if r["node"] != inst["node"] or ("once" in r and r["once"] in self.got):
                    continue
                if "round" in r and run.state()["round"] != r["round"]:
                    continue
                for ev in r["before"]:
                    self.step(ev, inst, out)
                return _reply(r.get("reply"), out)
            return None
        return hook

    def value(self, arg):
        if "json" in arg:
            return arg["json"]
        name, mark, part, *path = arg["ref"]
        got = self.scenes.board_at(name, HISTORIES[name].at(mark))
        v = got.state() if part == "state" else got.record()
        for k in path:
            v = v[k]
        return v


def _init(d, ev, inst, out):
    kw = dict(ev["run"])
    if ev.get("graph_drop"):
        root, kw["graph"] = _graph_copy(d.kind, ev["graph_drop"])
    d.run = d.mod.Run(ev["name"], **kw)
    d.run.graph_root = root if ev.get("graph_drop") else None
    return d.run.init


def _until(d, ev, inst, out):
    role, stop = ROLES[ev["roles"]], ev.get("stop") or {}
    pred = (None if not stop else
            (lambda nx: any(i["node"] == stop["ready"] for i in nx["ready"])) if "ready" in stop else
            (lambda nx: nx["round"] >= stop["round"]) if "round" in stop else
            (lambda nx: stop["got"] in d.got))
    try:
        return d.mod.drive(d.run, role["base"], hook=d.hook(role["rules"]), stop_at=pred)
    except RuntimeError as e:
        if not ev.get("catch"):
            raise
        return {"raised": str(e)[-400:]}


def _cmd(d, ev, inst, out):
    args, files = [], {}
    for a in ev["args"]:
        if isinstance(a, dict):
            files[a["file"]] = d.value(a)
            p = d.run.tmp / a["file"]
            p.write_text(json.dumps(files[a["file"]], ensure_ascii=False), encoding="utf-8")
            a = str(p)
        args.append(a)
    return {**_stored(d.run.cmd(*args)), **({"files": files} if files else {})}


def _done(d, ev, inst, out):
    node = inst["id"] if ev["node"] == "@" else ev["node"]
    return d.run.done(node, _reply(ev["reply"], out), **({"agent_id": ev["agent_id"]} if "agent_id" in ev else {}))


def _write(d, ev, inst, out):
    if ev["root"] not in WRITE_ROOTS:
        raise ValueError(f"write の置き場は {WRITE_ROOTS} のどれか: {ev['root']}")
    p = getattr(d.run, ev["root"]) / ev["path"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(ev["text"], encoding="utf-8")


def _look(d, ev, inst, out):
    b = _board(d.run)
    return {"state": b.state(), "record": b.record(),
            "rounds": {f.stem.split("-", 1)[1]: json.loads(f.read_text(encoding="utf-8")) for f in sorted((b.dir / "rounds").glob("round-*.json"))}}


def _prompt(d, ev, inst, out):
    if inst is None:
        raise ValueError("prompt は役の表の手直しの中でだけ打てる（答えている節が要る）")
    return pathlib.Path(inst["prompt_file"]).read_text(encoding="utf-8")


def _validate(d, ev, inst, out):
    return subprocess.run([sys.executable, str(d.mod.VALIDATOR), str(d.run.dir / "record.json")], capture_output=True, text=True,
                          encoding="utf-8")


def _loop(d, ev, inst, out):
    got = []
    for _ in range(ev["times"]):
        r, _ = d.step(ev["step"])
        got.append(r)
        if r.get("status") != "awaiting_human":
            break
        d.step(ev["answer"])
    return got


def _next(d, ev, inst, out):
    return d.run.next()


EVENTS = {"init": _init, "next": _next, "until": _until, "cmd": _cmd, "done": _done, "write": _write, "look": _look,
          "prompt": _prompt, "validate": _validate, "loop": _loop}


# ---- 前置きの控え ---------------------------------------------------------------------------------------------------------

class Scenes:
    """worker ごとの控えの置き場。列の接頭辞は要ったときに 1 度だけ作り、行の位置（とその手前）・借りられる位置・init の後で控える"""

    def __init__(self, root, port="inproc"):
        self.root, self.port = pathlib.Path(root), port
        self.runs = {}   # 列 → 作業場を持つ Run（置き場は列ごとに 1 か所）
        self.kept = {}   # (列, 位置) → {"got": 印の返事, "reply": [種類, 値]}

    def needed(self):
        got = {(n, j) for rows in ROWS.values() for n, k in rows for j in (k - 1, k) if j >= 1}
        return got | {r for h in HISTORIES.values() for e in h.events for r in refs(e)} | {(n, 1) for n in HISTORIES}

    def _snap(self, name, k):
        return self.root / "snap" / f"{name.replace('/', '__')}@{k}"

    def _restore(self, name, k):
        run = self.runs[name]
        waves._wipe(run.tmp, self.root)
        shutil.copytree(self._snap(name, k), run.tmp, symlinks=True)
        return run

    def _keep(self, d, name, k, reply):
        shutil.copytree(d.run.tmp, self._snap(name, k), symlinks=True)
        self.kept[(name, k)] = {"got": copy.deepcopy(d.got), "reply": [HISTORIES[name].events[k - 1]["ev"], reply]}

    def build(self, name, k):
        if (name, k) in self.kept:
            return
        h = HISTORIES[name]
        for j in range(1, k + 1):
            for r in refs(h.events[j - 1]):
                self.build(*r)
        start = max((j for (n, j) in self.kept if n == name and j < k), default=0)
        need = self.needed()
        d = Driver(h.kind, self.port, self, self._restore(name, start) if start else None,
                   self.kept[(name, start)]["got"] if start else None)
        with d:
            for j in range(start + 1, k + 1):
                if j == 1:
                    live = self.root / "live"
                    live.mkdir(exist_ok=True)
                    with mock.patch.object(tempfile, "tempdir", str(live)):   # 作業場をセッションの置き場の下に作る
                        reply, _ = d.step(h.events[0])
                    self.runs[name] = d.run
                else:
                    reply, _ = d.step(h.events[j - 1])
                if j == k or (name, j) in need:
                    self._keep(d, name, j, reply)

    def board_at(self, name, k):
        """控えた位置の盤面（写し戻さずに控えの置き場から読む）"""
        self.build(name, k)
        run = self.runs[name]
        return Board(self._snap(name, k) / run.dir.relative_to(run.tmp))

    def scene(self, name, k, live=False):
        """列 name の位置 k の行が見る物。live なら位置 k の出来事を今この場で打つ（控えは k-1 まで）"""
        h = HISTORIES[name]
        if not live:
            self.build(name, k)
            run, kept = self._restore(name, k), self.kept[(name, k)]
            return Scene(view(*kept["reply"]), _board(run), {m: view(*v) for m, v in kept["got"].items()})
        if k > 1:
            self.build(name, k - 1)
        d = Driver(h.kind, self.port, self, self._restore(name, k - 1) if k > 1 else None,
                   self.kept[(name, k - 1)]["got"] if k > 1 else None)
        with d:
            reply, board = d.step(h.events[k - 1])
        return Scene(view(h.events[k - 1]["ev"], reply), board, {m: view(*v) for m, v in d.got.items()})


# ---- 筋書きの行 -----------------------------------------------------------------------------------------------------------

def row(script, head, name, at, expect, *, id, kept=None):
    """筋書きの 1 行: 列 name の印 at の出来事を when、その手前の全部を given とし、手で書いた述語 expect（Scene を受ける）で見る。
    印 moved_from で台本の check 1 件を名乗る"""
    ROWS.setdefault(script, set()).add((name, HISTORIES[name].at(at)))
    return pytest.param(name, at, expect, id=id, marks=pytest.mark.moved_from(script, head, **({"kept": kept} if kept else {})))


def play(scene, name, at, expect):
    s = scene(name, at)
    try:
        ok = expect(s)
    except Exception as e:   # 期待の中の KeyError などでも観測値を出す
        raise AssertionError(f"{digest(s)}（期待の中で {e!r}）") from e
    assert ok, digest(s)


def pytest_configure(config):
    config.addinivalue_line("markers", "layer2: 層 2 の筋書き（控えた列から盤面を何周も回す medium。手元の反復は -m 'not layer2' で外せる）")


@pytest.fixture(scope="session")
def gl_scenes(tmp_path_factory, request):
    s = Scenes(tmp_path_factory.mktemp("scenes"))
    if request.config.getoption("--gl-prebuild-waves"):   # 被覆の道具の回: given だけを準備（setup）で作り、when は本体で打つ
        for name, k in sorted({x for rows in ROWS.values() for x in rows}):
            if k > 1:
                s.build(name, k - 1)
    return s


@pytest.fixture
def scene(gl_scenes, gl_tmp, request):
    """scene(列, 印) が Scene を返す。使った前置きの鍵をテストの user_properties に積む（junitxml に載り、cover_moved.py が読む）"""
    live = request.config.getoption("--gl-prebuild-waves")

    def get(name, at):
        k = HISTORIES[name].at(at)
        request.node.user_properties.append((waves.NODE_PROPERTY, request.node.nodeid))
        request.node.user_properties.extend((GIVEN_PROPERTY, key) for key in lineage(name, k - 1))
        return gl_scenes.scene(name, k, live=live)
    return get
