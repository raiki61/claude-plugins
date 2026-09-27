"""途中の盤面を作る口（T1: 否定検査を「控えた波・1 手・手で書いた期待」へ移す土台。層 2 の筋書きの前置きは scenes.py）。

盤面を端から歩いて 1 か所を見る台本（simulate.py・simulate_review.py）の前半を、同じプロセスで 1 度だけ回して狙いの波ごとに
控え、検査ごとに控えから始めて 1 手だけ打てるようにする。

- **作り方**: 台本の Run・answers・base_answers・settle を import して借り（写さない）、glharness.driven(台本, "inproc") の下で
  回す——loop.py は同じプロセスの ``loop.cli()`` に回り、git は本物（型のリポジトリ。Run がセッションで 1 度だけ作る）。
- **控え**: 波ごとに Run の作業場（型のリポジトリ・盤面・設定）をまるごとセッションの置き場へ写す。作業場の置き場は
  Run が作った 1 か所に固定し、検査はそこへ控えを写し戻して始める（置き場が動かないので、盤面の中の絶対パスを書き換えない）。
  1 つの worker の検査は順に走るので、同じ置き場を順に使ってよい。控えは worker ごとの session の fixture で 1 度だけ作る
  （pytest-xdist の worker の間では分けない——作り手が消えたときに待ち手が待ち続ける形と、-n 無しの回にセッションをまたいで
  古い控えを使う形を作らないため）。
- **前半の歩きは check を呼ばない**。台本の check は fixture の中で落ちても数えられないので、前提が崩れたら例外で止める。
- **検査の中の 1 手**も台本の Run の口（run.done・run.next・run.cmd）をそのまま使い、fixture ``wave`` が張る
  driven(…, "inproc") の下で同じプロセスで走る。同じプロセスでは見えない物（argv・終了コードの写像・標準入力の文字コード・
  PYTHONIOENCODING）は、移した先のテストの印 ``moved_from(…, kept=理由)`` で台帳に「通しに残す」と書く。

前半の手順のうち、台本の関数の中だけに在る物（test_rejections の主張 A を太らせる・stray.txt と --accept-tree-change・拒ませて
から通す done）は、台本の本文から下の波の手に書き写してある。台本を消す run まで台本も残るので、台本の前半を直したらここも直す
（ずれを見る柵は無い——README の test_schema_graphcheck.py の写しと同じ扱い）。

大きさ: これを使うテストは medium（glharness.SIZES）。
"""
import contextlib
import json
import os
import pathlib
import shutil
import stat
import tempfile
from unittest import mock

import glharness
import pytest

TESTS = glharness.TESTS
review = glharness.script("review")
research = glharness.script("research")
# テストの user_properties に積む名前（junitxml に載り、被覆の道具 cover_moved.py が読む）: 使った波・積んだテストの node id
WAVE_PROPERTY, NODE_PROPERTY = "gl_wave", "gl_node"


def pending(run):
    """今の周に出ていて済んでいない instance を節の名前で（next の ready と同じ集合。done の相手を引く口）"""
    rd = run.state()["rounds"][-1]
    return {i["node"]: i for i in rd["instances"].values() if i["status"] == "pending"}


def _ok(r, what):
    if r.returncode != 0:
        raise RuntimeError(f"波の前提が崩れた: {what} が {r.returncode}: {(r.stderr or '')[-400:]}")
    return r


# ---- 波の作り方（名前: (親, 手)）。手は (run, values) を受けて進め、values（JSON の値の控え）に足してよい ------------------

T_NODES = ("p0.prior_decisions", "p1.local_review", "p1.consistency_bypass", "p1.external_standards", "p1.provenance",
           "p1.hygiene", "p2.diagnose", "p3.fix")


def _r_p0(run, v):
    run.next()
    # review の test_rejections は返答の表（answers）を P0 の最初の波で 1 度だけ引き、P1・撃ち直し・判定・修正の拒みの土台に
    # 使い回す——同じ時点で引いた値を控える（後で引き直すと、表が記録を読む節の値が変わる）
    t = review.answers(run, "std", 1)
    v["t"] = {n: t[n](None) for n in T_NODES}


def _settle(run, inst, make):
    """台本の settle（走らせる節は launch——ok でなければ settle が例外。ほかは done）の done の側も、崩れたら止める"""
    got = review.settle(run, inst, make)
    if not isinstance(got, dict):
        _ok(got, inst["node"])


def _r_p0_settled(run, v):
    t = review.answers(run, "std", 1)
    by = pending(run)
    for n in ("p0.base", "p0.local_checks", "p0.premises"):
        _settle(run, by[n], t[n])


def _r_next(run, v):
    run.next()


def _r_p0b_settled(run, v):
    t = review.answers(run, "std", 1)
    by = pending(run)
    for n in ("p0.purpose", "p0.parallel_pr", "p0.prior_decisions"):
        _settle(run, by[n], t[n])


def _r_p1_done(run, v):
    by = pending(run)
    for n in ("p1.local_review", "p1.consistency_bypass", "p1.external_standards", "p1.provenance", "p1.hygiene"):
        _ok(run.done(by[n]["id"], v["t"][n]), n)


def _r_p2_pre(run, v):
    """P1 の後の作業ツリーの突合で止め、writer の変更として受け付け、撃ち直しの節を済ませる（stray.txt は残したまま）"""
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    nx = run.next()
    if nx["ready"]:
        raise RuntimeError(f"波の前提が崩れた: 作業ツリーを汚した next が止まらない: {nx['ready'][:1]}")
    r = _ok(run.cmd("next", "--accept-tree-change", "writer の変更（検査用）"), "next --accept-tree-change")
    for i in json.loads(r.stdout).get("ready", []):
        _ok(run.done(i["id"], v["t"][i["node"]]), f"撃ち直した {i['node']}")


def _r_p2(run, v):
    run.next()
    (run.repo / "stray.txt").unlink()


def _r_p3(run, v):
    """判定役の返答を台本と同じ形（置き場に古い返答・標準入力で件数を書き違えた新しい返答）で通し、修正案と事前審査を済ませる"""
    jd = pending(run)["p2.diagnose"]
    good = v["t"]["p2.diagnose"]
    pathlib.Path(jd["out_path"]).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(jd["out_path"]).write_text(json.dumps({**good, "framing": "STALE"}, ensure_ascii=False), encoding="utf-8")
    _ok(run.cmd("done", "--node", jd["id"], "--stdin", "--agent-id", "judge-1",
                input=json.dumps(fresh_judge_reply(good), ensure_ascii=False)), "p2.diagnose")
    nx = run.next()
    for node in ("p2.fix_plan", "p2.plan_review"):
        it = next(i for i in nx["ready"] if i["node"] == node)
        _ok(run.done(it["id"], review.answers(run, "std", nx["round"])[node](None)), node)
        nx = run.next()
    v["fix"] = review.answers(run, "std", nx["round"])["p3.fix"](None)
    v["round"] = nx["round"]


# 判定者の件数の置き換えを見る腕の class_query（台本の test_rejections と同じ値）
ZERO_QUERY = {"how": {"patterns": ["no-such-word"], "paths": ["src/a.py"], "count": "lines"}, "counts": "population", "total": 1}


def fresh_judge_reply(good):
    """台本が標準入力で渡す judge の返答: unit 0 の件数を 3 と書き違え（engine が 1 に置き換える）、unit 1 は 0 件を数える問い"""
    return {**good, "framing": "FRESH", "units": [{**good["units"][0], "class_query": {**good["units"][0]["class_query"], "total": 3}},
                                                  {**good["units"][1], "class_query": ZERO_QUERY}] + good["units"][2:]}


def _s_q_done(run, v):
    q = pending(run)["p0.question"]
    _ok(run.done(q["id"], research.base_answers(run, "std")["p0.question"](None, 1)), "p0.question")


def _s_w3(run, v):
    """調べ役の前後で作業ツリーを汚して拒ませ、理由つきで通し、P0 の残りを済ませる（主張 A だけを太らせる）"""
    by = pending(run)
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    if run.done(by["p0.prior_decisions"]["id"], research.base_answers(run, "std")["p0.prior_decisions"](None, 1)).returncode != 1:
        raise RuntimeError("波の前提が崩れた: 作業ツリーを汚した調べ役の done が拒まれない")
    _ok(run.cmd("done", "--node", by["p0.prior_decisions"]["id"], "--output", str(run.tmp / "out.json"),
                "--accept-tree-change", "自分で作った"), "p0.prior_decisions --accept-tree-change")
    (run.repo / "stray.txt").unlink()
    for node in ("p0.claims", "p0.terms", "p5.internal", "p3.rederiver"):
        out = research.base_answers(run, "std")[node](None, 1)
        if node == "p0.claims":
            out = json.loads(json.dumps(out, ensure_ascii=False))
            out["claims"][0]["claim"] += "。" + "あ" * 350
        _ok(run.done(by[node]["id"], out), node)
    run.next()


def _s_w4(run, v):
    cl = pending(run)["p0.clusters"]
    _ok(run.done(cl["id"], research.base_answers(run, "std")["p0.clusters"](None, 1)), "p0.clusters")


def _s_w5b(run, v):
    _ok(run.done("p1.checker[c1]", CHECKER_A_ONLY), "p1.checker[c1]")


# 主張 A だけに判定を返す checker の返答（B が欠けて p1.checker[c1]#2 が出る）
CHECKER_A_ONLY = {"cluster": "c1", "findings": [{"id": "A", "verdict": "確証", "evidence": "e", "sources": ["https://x"], "conditions": "c"}]}
CHECKER_B_CORRECTED = {"cluster": "c1", "findings": [{"id": "B", "verdict": "相違", "evidence": "e", "sources": ["https://x"], "correction": "c"}]}


def _s_w7(run, v):
    _ok(run.done("p1.checker[c1]#2", CHECKER_B_CORRECTED), "p1.checker[c1]#2")


WAVES = {
    # review の test_rejections（Run("neg")）
    "review/neg/init": (None, None),
    "review/neg/p0": ("review/neg/init", _r_p0),               # 最初の波が出た（P0 の 1 波目）
    "review/neg/p0-settled": ("review/neg/p0", _r_p0_settled),  # 1 波目を済ませ、next の前
    "review/neg/p0b": ("review/neg/p0-settled", _r_next),       # P0 の 2 波目が出た
    "review/neg/p0b-settled": ("review/neg/p0b", _r_p0b_settled),  # 2 波目を済ませ、next の前
    "review/neg/p1": ("review/neg/p0b-settled", _r_next),       # P1 の役の波が出た
    "review/neg/p1-done": ("review/neg/p1", _r_p1_done),        # P1 の役を全部済ませ、next の前
    "review/neg/p2-pre": ("review/neg/p1-done", _r_p2_pre),     # 突合を writer の変更として通し、撃ち直しも済ませた
    "review/neg/p2": ("review/neg/p2-pre", _r_p2),              # 判定役（p2.diagnose）が出た
    "review/neg/p3": ("review/neg/p2", _r_p3),                  # 修正（p3.fix）が出た
    # review の宣言の無いリポジトリ（Run("neg-nodecl", checks=None)）
    "review/nodecl/init": (None, None),
    # research の test_rejections（Run("neg")）
    "research/neg/init": (None, None),
    "research/neg/q": ("research/neg/init", _r_next),           # p0.question が出た
    "research/neg/q-done": ("research/neg/q", _s_q_done),       # p0.question を済ませ、next の前
    "research/neg/w2": ("research/neg/q-done", _r_next),        # P0 の 2 波目が出た
    "research/neg/w3": ("research/neg/w2", _s_w3),              # p0.clusters が出た
    "research/neg/w4": ("research/neg/w3", _s_w4),              # クラスタを済ませ、next の前
    "research/neg/w5": ("research/neg/w4", _r_next),            # checker がクラスタごとに出た
    "research/neg/w5b": ("research/neg/w5", _s_w5b),            # checker[c1] が A だけ返した
    "research/neg/w6": ("research/neg/w5b", _r_next),           # 欠けた分の checker と refuter が出た
    "research/neg/w7": ("research/neg/w6", _s_w7),              # 欠けた分の checker も済んだ
}

ROOTS = {
    "review/neg/init": lambda: review.Run("neg"),
    "review/nodecl/init": lambda: review.Run("neg-nodecl", checks=None),
    "research/neg/init": lambda: research.Run("neg"),
}


def lineage(name):
    """波とその祖先——被覆の道具（cover_moved.py）が、テストが使った波の作りの行を集めるのに使う"""
    out = []
    while name is not None:
        out.append(name)
        name = WAVES[name][0]
    return out


def _kind(name):
    return name.split("/", 1)[0]


def _module(name):
    return review if _kind(name) == "review" else research


def _chain(name):
    return "/".join(name.split("/")[:2])


def _clear_readonly(func, path, _):
    """windows は git の object を読み取り専用で置く——印を外して消し直す（Python の shutil.rmtree の文書の例）"""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _wipe(path, root):
    """写し戻す直前に作業場を消す。控えの置き場（root）より深いパスだけを消し、外を指したら例外にする。

    parallel.rm は使えない: 基点の gettempdir を、wave の fixture が張る gl_tmp がテストごとの tmp_path に動かし、作業場は
    その外（セッションの置き場）に在る。parallel.rm と違い消し損ねを握り潰さない——残った物があると続く copytree が
    FileExistsError で落ちるか、前の検査の残りが控えに混じる"""
    real, base = os.path.realpath(path), os.path.realpath(root)
    if real == base or os.path.commonpath([real, base]) != base:
        raise ValueError(f"_wipe: 控えの置き場（{base}）より深いパスでないので消さない: {path}")
    shutil.rmtree(path, onexc=_clear_readonly)


class Wave:
    """控えから始めた 1 つの波: 台本の Run（run）と、作るときに控えた JSON の値（values）"""

    def __init__(self, run, values):
        self.run, self.values = run, values

    def pending(self):
        return pending(self.run)


class Waves:
    """worker ごとの控えの置き場。波は要ったときに 1 度だけ作る（親の波の控えから始めて手を 1 つ進める）"""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.runs = {}      # 筋書き（review/neg など）→ 作業場を持つ Run（作業場の置き場は筋書きごとに 1 か所）
        self.values = {}    # 波 → JSON の値の控え

    def _snap(self, name):
        return self.root / "snap" / name.replace("/", "__")

    def _restore(self, name):
        run = self.runs[_chain(name)]
        _wipe(run.tmp, self.root)
        shutil.copytree(self._snap(name), run.tmp, symlinks=True)
        return run

    def build(self, name):
        if name in self.values:
            return
        parent, step = WAVES[name]
        mod = _module(name)
        with glharness.driven(mod, "inproc"):
            if parent is None:
                live = self.root / "live"
                live.mkdir(exist_ok=True)
                with mock.patch.object(tempfile, "tempdir", str(live)):   # 台本の作業場（parallel.workspace）をセッションの置き場の下に作る
                    run = ROOTS[name]()
                _ok(run.init, f"{name} の init")
                self.runs[_chain(name)] = run
                values = {}
            else:
                self.build(parent)
                run = self._restore(parent)
                values = json.loads(json.dumps(self.values[parent]))
                step(run, values)
        shutil.copytree(run.tmp, self._snap(name), symlinks=True)
        self.values[name] = values

    def get(self, name):
        self.build(name)
        return Wave(self._restore(name), json.loads(json.dumps(self.values[name])))


def pytest_addoption(parser):
    parser.addoption("--gl-prebuild-waves", action="store_true", default=False,
                     help="波と層 2 の筋書きの前置き（given）を、最初にそれを使うテストの準備（setup）の段で作る（既定は要ったときに作る）。"
                          "被覆を測る道具（cover_moved.py）が、前置きを作る行を検査の本体（run）と分けて数えるために使う")


@pytest.fixture(scope="session")
def gl_waves(tmp_path_factory, request):
    w = Waves(tmp_path_factory.mktemp("waves"))
    if request.config.getoption("--gl-prebuild-waves"):
        for name in WAVES:
            w.build(name)
    return w


@pytest.fixture
def wave(gl_waves, gl_tmp, request):
    """控えた波から始める: wave("review/neg/p2") が Wave を返す。検査の間は台本 2 本とも inproc の口で loop.py を呼ぶ"""
    def get(name):
        request.node.user_properties += [(NODE_PROPERTY, request.node.nodeid), (WAVE_PROPERTY, name)]
        return gl_waves.get(name)
    with contextlib.ExitStack() as stack:
        stack.enter_context(glharness.driven(review, "inproc"))
        stack.enter_context(glharness.driven(research, "inproc"))
        yield get
