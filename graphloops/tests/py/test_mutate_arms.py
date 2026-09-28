"""変異の実行器（リポジトリの根の tests/mutate.py）の一覧の腕が、tests に pytest の置き場（PYDIR）の node id を名指す口。
台本を消す条件の 2（新しい層だけで殺す）はこの口の赤で読むので、撃ち分け・証拠・control・--check の入口・--map の結び直しを縛る。
撃つのは CI だけ（人の方針）——small は子を起こさず、台本と pytest の走らせ方を差し替えて見る。medium は一時の置き場で実物の
pytest を起こし、要約の行と収集の node id の形を見る（差し替えは主張どおりの形を返すので、形の食い違いを見られない）"""
import contextlib
import importlib.util
import json
import os
import subprocess
import sys

import conftest
import pytest

_spec = importlib.util.spec_from_file_location("mutate_arms_under_test", conftest.REPO / "tests" / "mutate.py")
mutate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutate)

NODE = "test_x.py::test_y[case-a]"
SCRIPT = "graphloops/tests/simulate_review.py"


def _arm(tests, expect="台本の検査の名前"):
    return {"id": "L1", "title": "t", "file": "graphloops/engine/x.py", "suite": "graphloops", "old": "a", "new": "b",
            "expect": expect, "tests": tests}


@pytest.fixture
def shoot(tmp_path, monkeypatch):
    """one を子を起こさずに撃つ: 写し・壊し・pytest・台本を差し替え、呼ばれた順（calls）を返す"""
    calls, state = [], {"py": 0, "pyall": 0, "sel": 0, "full": 0, "ready": ""}

    @contextlib.contextmanager
    def lease(tag, a=None):
        yield tmp_path, tmp_path

    def run_pytest(repo, args, failfast=False):
        whole = args == [mutate.WHOLE]
        calls.append(("pyall" if whole else "py", tuple(args)))
        rc = state["pyall" if whole else "py"]
        return {"rc": rc, "failed": state.get("failed", [NODE]) if rc == 1 else [], "tail": [],
                **({"why": "pytest が赤でない終わり方をした（rc=4）"} if rc == "no-test" else {})}

    def run_selected(repo, tests, failfast=False):
        calls.append(("sel", tuple(tests)))
        return {"rc": state["sel"], "failed": ["台本の検査の名前が落ちた"] if state["sel"] else [], "tail": [], "selected": True}

    def run_suite(repo, suite, failfast=False, env=None, detail=False):
        calls.append(("full", suite))
        return {"rc": state["full"], "failed": ["F full"] if state["full"] else [], "tail": []}
    for name, fn in (("lease", lease), ("mutate", lambda repo, a: None), ("run_pytest", run_pytest),
                     ("run_selected", run_selected), ("run_suite", run_suite), ("pytest_ready", lambda: state["ready"])):
        monkeypatch.setattr(mutate, name, fn)
    monkeypatch.setattr(mutate, "PYTEST_STAGE", False)
    monkeypatch.setattr(mutate, "CONFIRM", False)

    def go(arm, **k):
        calls.clear()
        state.update(k)
        return mutate.one(arm), [c[0] for c in calls]
    go.calls = calls
    return go


@pytest.mark.small
def test_named_node_red_kills_first_with_the_named_node_as_evidence(shoot):
    """名指した node id が落ちれば台本を撃たずに Killed（attribution pytest）で、名指しに当たる落ちたテストが証拠"""
    r, calls = shoot(_arm({SCRIPT: ["test_rejections"], mutate.PYDIR: [NODE]}), py=1)
    assert calls == ["py"] and shoot.calls[0][1] == (NODE,)
    assert (r["status"], r["attribution"], r["own"], r["hit"]) == ("Killed", "pytest", True, NODE)
    res = {"marker": {"placed": [], "seen": [], "rc": 0}, "control": {"root": {"rc": 0}, "pytest": {"rc": 0}}, "arms": [r]}
    s = mutate.evaluate(res, [_arm({})])
    assert r["evidence"].startswith("killedBy に名指した node id") and s["by_pytest"] == ["L1"] and mutate.proven(r)


@pytest.mark.small
@pytest.mark.parametrize("failed, own", [(["test_other.py::t"], False), (["pytest の柵（fence）が赤"], False),
                                         (["test_x.py::test_y[case-a]"], True)])
def test_named_node_red_is_evidence_only_when_the_named_node_fell(shoot, failed, own):
    """名指しの外のテスト・柵の赤で落ちた回は証拠にしない（expect が台本の名前の腕は、名指しの node id だけが当たり）"""
    r, _ = shoot(_arm({mutate.PYDIR: [NODE]}), py=1, failed=failed)
    assert r["status"] == "Killed" and r["own"] is own


@pytest.mark.small
def test_node_id_expect_is_evidence_too(shoot):
    """expect を node id で書いた腕は、落ちたテストが expect かその parametrize なら当たり"""
    r, _ = shoot(_arm({mutate.PYDIR: ["test_x.py::test_y"]}, expect="test_x.py::test_y"), py=1, failed=["test_x.py::test_y[case-b]"])
    assert r["own"] and r["hit"] == "test_x.py::test_y[case-b]"


@pytest.mark.small
def test_named_node_green_falls_through_to_the_scripts(shoot):
    """pytest が緑なら台本の道も撃つ（台本だけが殺す腕を台本で殺す——網を狭めない）。台本の証拠は今までどおり expect"""
    r, calls = shoot(_arm({SCRIPT: ["test_rejections"], mutate.PYDIR: [NODE]}), sel=1)
    assert calls == ["py", "sel"] and (r["status"], r["attribution"], r["own"]) == ("Killed", "narrowed", True)
    assert r["pytest"]["rc"] == 0


@pytest.mark.small
def test_only_named_nodes_do_not_run_the_whole_suite(shoot):
    """台本の名指しの無い腕は、pytest が緑なら台本一式を撃たずに Survived（名指しの pytest だけで緑）"""
    r, calls = shoot(_arm({mutate.PYDIR: [NODE]}))
    assert calls == ["py"] and r["status"] == "Survived" and r.get("pytest_selected") and not r.get("pytest_only")


@pytest.mark.small
@pytest.mark.parametrize("state, why", [({"py": "no-test"}, "rc=4"), ({"ready": "uv が PATH に無い（pytest を起こせない）"}, "uv が PATH に無い")])
def test_unrunnable_named_nodes_say_why(shoot, state, why):
    """名指しの pytest を撃てない回は走り切らない（RuntimeError）で、理由は pytest の側を言う（台本の関数名の --map の話にしない）"""
    r, calls = shoot(_arm({mutate.PYDIR: [NODE]}), **state)
    assert r["status"] == "RuntimeError" and why in r["unrunnable"] and "--map" not in r["unrunnable"]
    assert calls == ([] if "ready" in state else ["py"])


@pytest.mark.small
def test_unrunnable_named_nodes_still_shoot_the_scripts(shoot):
    """pytest を撃てなくても、台本の名指しが在れば台本で撃つ"""
    r, calls = shoot(_arm({SCRIPT: ["test_rejections"], mutate.PYDIR: [NODE]}), py="no-test", sel=1)
    assert calls == ["py", "sel"] and r["status"] == "Killed" and r["pytest"]["rc"] == "no-test"


@pytest.mark.small
def test_confirm_survivors_reruns_the_whole_pytest_place(shoot, monkeypatch):
    """--confirm-survivors の回は、名指しの pytest が緑の腕を pytest 一式で確かめ直す（自動の腕と同じ）"""
    monkeypatch.setattr(mutate, "CONFIRM", True)
    r, calls = shoot(_arm({mutate.PYDIR: [NODE]}), pyall=1)
    assert calls == ["py", "pyall"] and r["attribution"] == "pytest_unrelated"


@pytest.mark.small
def test_red_control_pytest_drops_only_the_pytest_evidence():
    """control の pytest が赤の回は、pytest の赤だけを証拠にしない——台本の赤の証拠と回の健全さ（control_ok）は残る"""
    res = {"marker": {"placed": [], "seen": [], "rc": 0}, "control": {"root": {"rc": 0}, "selected": {"rc": 0}, "pytest": {"rc": 1}},
           "arms": [{"id": "p", "title": "t", "status": "Killed", "own": True, "hit": NODE, "attribution": "pytest"},
                    {"id": "s", "title": "t", "status": "Killed", "own": True, "attribution": "narrowed"}]}
    s = mutate.evaluate(res, [{"id": "p", "expect": "x"}, {"id": "s", "expect": "x"}])
    assert s["control_ok"] and not s["pytest_control_ok"]
    assert [bool(r["evidence"]) for r in res["arms"]] == [False, True]


@pytest.mark.small
def test_control_runs_named_node_files_as_pytest_not_as_scripts(monkeypatch):
    got = {}

    def control(suites, selected=None, pytest=None):
        got.update(selected=selected, pytest=pytest)
        return {"root": {"rc": 0}}
    monkeypatch.setattr(mutate, "control", control)
    monkeypatch.setattr(mutate, "marker_run", lambda fire: {"rc": 0, "placed": [], "seen": [], "cover": {}, "skipped": {}})
    monkeypatch.setattr(mutate, "one", lambda a: {"id": a["id"], "title": "t", "status": "Survived", "own": False})
    monkeypatch.setattr(mutate, "write_out", lambda out, res: None)
    monkeypatch.setattr(mutate, "PYTEST_STAGE", False)
    arm = _arm({SCRIPT: ["test_rejections"], mutate.PYDIR: [NODE, "test_z.py::t"]})
    mutate.shoot(type("A", (), {"j": 1, "out": None})(), {"arms": []}, [arm], [arm], {"L1": "f"}, lambda: False, lambda xs: [])
    assert got["selected"] == {SCRIPT: ["test_rejections"]}
    assert got["pytest"] == ["test_x.py", "test_z.py"]


@pytest.fixture
def place(tmp_path):
    d = tmp_path / mutate.PYDIR
    d.mkdir(parents=True)
    (d / "test_x.py").write_text('@pytest.mark.parametrize("c", ["case-a"])\ndef test_y(c):\n    pass\n\n\nclass TestK:\n    def test_m(self):\n        pass\n',
                                 encoding="utf-8")
    (tmp_path / "graphloops/engine").mkdir(parents=True)
    (tmp_path / "graphloops/engine/x.py").write_text("a\n", encoding="utf-8")
    return tmp_path


@pytest.mark.small
@pytest.mark.parametrize("tests, expect, want", [
    ({mutate.PYDIR: [NODE]}, "x", ""),
    ({mutate.PYDIR: ["test_x.py::test_y"]}, "test_x.py::test_y[case-a]", ""),
    ({"graphloops/tests/other.py": ["test_a"]}, "x", "でも pytest の置き場"),
    ({mutate.PYDIR: ["test_gone.py::test_y"]}, "x", "のファイルが"),
    ({mutate.PYDIR: ["test_x.py::test_gone"]}, "x", "の関数 test_gone が"),
    ({mutate.PYDIR: ["test_x.py::test_y[case-renamed]"]}, "x", "の id 'case-renamed' が"),
    ({mutate.PYDIR: [NODE]}, "test_x.py::test_gone", "expect の pytest の node id"),
    ({mutate.PYDIR: ["test_x.py::TestK::test_m"]}, "x", ""),
    ({mutate.PYDIR: ["test_x.py::TestGone::test_m"]}, "x", "の class TestGone が"),
    ({mutate.PYDIR: []}, "x", "の node id が空"),
    ({}, NODE, "の名指しが無い"),
    ({mutate.PYDIR: ["test_x.py::TestK::test_m"]}, "test_x.py::test_y", "のどれにも当たらない"),
], ids=["named", "node-expect", "unknown-key", "file-gone", "function-gone", "param-id-gone", "expect-gone", "class-method", "class-gone",
        "empty-named", "expect-without-named", "expect-outside-named"])
def test_check_reds_every_entrance_of_a_named_node(place, tests, expect, want):
    """--check（anchor_problem）は、名指しの鍵・node id のファイル・class・関数・parametrize の id・node id の expect のどれが消えても、
    名指しが空でも、node id の expect が名指しの外でも赤"""
    why = mutate.anchor_problem(place, _arm(tests, expect), src="x")
    assert (want in why and why) if want else why == ""


@pytest.mark.small
def test_check_reds_a_script_key_on_a_root_arm(place):
    arm = {**_arm({SCRIPT: ["test_rejections"]}), "suite": "root"}
    assert "root の腕は台本の鍵" in mutate.anchor_problem(place, arm, src="台本の検査の名前")


@pytest.mark.small
@pytest.mark.parametrize("named, got, want", [
    ("f.py::t", "f.py::t", True), ("f.py::t", "f.py::t[a]", True), ("f.py::t[a]", "f.py::t[a]", True),
    ("f.py::t", "f.py::tt", False), ("f.py::t[case-a]", "f.py::t[case-a-2]", False), ("f.py::t[a]", "f.py::t", False),
])
def test_node_hit_takes_only_the_node_or_its_parameters(named, got, want):
    assert mutate.node_hit(named, got) is want


@pytest.mark.small
def test_map_keeps_the_pytest_place_and_leaves_node_id_expects(monkeypatch, tmp_path):
    """--map（build_map）は台本の名指しだけを結び直す——pytest の置き場の名指しは残し、node id の expect の腕は台本から引かない
    （頭の数字だけが台本のどこかの行に当たり、無関係の関数を結ぶ）"""
    for s in mutate.SCRIPTS:
        (tmp_path / s).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / s).write_text('def test_a():\n    check("台本の検査の名前が落ちた test_x.py")\n', encoding="utf-8")
    monkeypatch.setattr(mutate, "ROOT", tmp_path)
    both = _arm({SCRIPT: ["test_old"], mutate.PYDIR: [NODE]})
    node = _arm({mutate.PYDIR: [NODE]}, expect="test_x.py::test_y")
    assert mutate.build_map([both, node]) == 1
    assert both["tests"] == {**{s: ["test_a"] for s in mutate.SCRIPTS}, mutate.PYDIR: [NODE]}
    assert node["tests"] == {mutate.PYDIR: [NODE]}


@pytest.mark.small
def test_named_node_arms_carry_the_pytest_files_in_their_fingerprint(place):
    named, plain = _arm({mutate.PYDIR: [NODE]}), {**_arm({}), "tests": {}}
    before = (mutate.fingerprint(place, named), mutate.fingerprint(place, plain))
    (place / mutate.PYDIR / "test_x.py").write_text("def test_y():\n    assert False\n", encoding="utf-8")
    after = (mutate.fingerprint(place, named), mutate.fingerprint(place, plain))
    assert before[0] != after[0] and before[1] == after[1]


REAL_TESTS = '''import pytest


@pytest.mark.parametrize("c", ["case-a", "case-a-2"])
def test_y(c):
    assert c != "case-a-2"


@pytest.mark.parametrize("v", [None, 1])
def test_v(v):
    pass


class TestK:
    def test_m(self):
        assert False
'''


@pytest.fixture
def real_place(tmp_path):
    d = tmp_path / mutate.PYDIR
    d.mkdir(parents=True)
    (d / "pytest.ini").write_text("[pytest]\ntestpaths = .\naddopts = -ra\n", encoding="utf-8")
    (d / "test_x.py").write_text(REAL_TESTS, encoding="utf-8")
    return tmp_path


def _collected(d):
    """d（pytest.ini の置き場）を実物の pytest --collect-only で集めた node id の集合"""
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=d, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    return {ln for ln in r.stdout.splitlines() if "::" in ln}


@pytest.fixture
def real_pytest(monkeypatch):
    monkeypatch.setattr(mutate, "PYTEST", [sys.executable, "-m", "pytest"])


@pytest.mark.medium
def test_real_pytest_reports_failures_as_the_named_node_ids(real_place, real_pytest):
    r = mutate.run_pytest(real_place, ["test_x.py::test_y", "test_x.py::TestK::test_m"])
    assert r["rc"] == 1 and sorted(r["failed"]) == ["test_x.py::TestK::test_m", "test_x.py::test_y[case-a-2]"]


@pytest.mark.medium
@pytest.mark.parametrize("named, status, hit", [
    ("test_x.py::test_y[case-a-2]", "Killed", "test_x.py::test_y[case-a-2]"),
    ("test_x.py::test_y", "Killed", "test_x.py::test_y[case-a-2]"),
    ("test_x.py::TestK::test_m", "Killed", "test_x.py::TestK::test_m"),
    ("test_x.py::test_y[case-a]", "Survived", None),
], ids=["param", "function", "class-method", "green-param"])
def test_named_arm_is_proven_on_the_real_pytest(real_place, real_pytest, monkeypatch, named, status, hit):
    """実物の pytest を 1 回起こし、名指しの腕の赤が名指しの node id を当たりの証拠にすること（形が食い違えば own が偽になる）"""
    @contextlib.contextmanager
    def lease(tag, a=None):
        yield real_place, real_place
    for name, fn in (("lease", lease), ("mutate", lambda repo, a: None), ("pytest_ready", lambda: "")):
        monkeypatch.setattr(mutate, name, fn)
    monkeypatch.setattr(mutate, "CONFIRM", False)
    r = mutate.one(_arm({mutate.PYDIR: [named]}))
    assert (r["status"], r.get("hit"), r["own"]) == (status, hit, hit is not None)


@pytest.mark.medium
@pytest.mark.parametrize("named, expect, want", [
    ("test_x.py::test_y[case-a]", "x", ""),
    ("test_x.py::test_y", "x", ""),
    ("test_x.py::TestK::test_m", "x", ""),
    ("test_x.py::test_y[case]", "x", "pytest の収集に無い"),
    ("test_x.py::test_y[None]", "x", "pytest の収集に無い"),
    ("test_x.py::test_m", "x", "pytest の収集に無い"),
    ("test_x.py::TestK::test_m", "test_x.py::test_y", "のどれにも当たらない"),
], ids=["param", "function", "class-method", "short-id", "id-elsewhere-in-file", "method-outside-its-class", "expect-outside-named"])
def test_collection_reds_the_names_the_text_lets_through(real_place, named, expect, want):
    why = mutate.named_problem(real_place, _arm({mutate.PYDIR: [named]}, expect), _collected(real_place / mutate.PYDIR))
    assert (want in why and why) if want else why == ""


@pytest.mark.medium
def test_every_named_node_of_the_arms_is_collected():
    """tests/mutations.json の名指し（node id の expect も）が、この置き場の実物の収集に在る（--check は子を起こさず字面で見る）"""
    nodes = _collected(conftest.HERE)
    arms = json.loads((conftest.REPO / "tests" / "mutations.json").read_text(encoding="utf-8"))["arms"]
    bad = [f"{a['id']}: {why}" for a in arms if "auto" not in a and (why := mutate.named_problem(conftest.REPO, a, nodes))]
    assert not bad, bad
