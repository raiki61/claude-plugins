"""被覆の道具（cover_moved.py）の選ぶ段と子の数え方。道具そのものの撃ちは CI の job（MIGRATION.md の被覆の包含）。"""
import json
import subprocess
import sys

import cover_moved
import pytest
import scenes
import waves

A, B = ("graphloops/engine/a.py", 1), ("graphloops/engine/a.py", 2)
NEW = {"t.py::mine|run": {A}, "t.py::other|run": {B}, "t.py::mine|setup": {B}, "": set()}
BUILT = {"given:review/x@1": {B}, "given:review/y@1": {B}}


@pytest.mark.small
def test_select_new_counts_only_the_named_tests_and_their_givens():
    got = cover_moved.select_new(NEW, BUILT, {"t.py::mine"}, set())
    assert set(got) == {"t.py::mine|run", ""}
    assert cover_moved.compare({"old:s": {A, B}}, got)["not_covered"] == 1


@pytest.mark.small
def test_select_new_counts_the_used_given_as_setup():
    got = cover_moved.select_new(NEW, BUILT, {"t.py::mine"}, {"given:review/x@1"})
    assert set(got) == {"t.py::mine|run", "", "given:review/x@1|setup"}
    r = cover_moved.compare({"old:s": {A, B}}, got)
    assert r["not_covered"] == 0 and r["covered_only_by_setup"] == 1


@pytest.mark.small
def test_used_contexts_reads_the_node_id_and_the_givens_and_waves_it_stacked():
    xml = ('<testsuites><testsuite><testcase classname="sub.test_scenarios_review" name="test_runaway[stops-at-round-5]"><properties>'
           '<property name="gl_node" value="sub/test_scenarios_review.py::test_runaway[stops-at-round-5]"/>'
           '<property name="gl_given" value="review/runaway@1"/><property name="other" value="x"/></properties></testcase>'
           '<testcase classname="test_rejections_review" name="test_x"><properties><property name="gl_node" value="test_rejections_review.py::test_x"/>'
           '<property name="gl_wave" value="review/neg/p0"/></properties></testcase>'
           '<testcase classname="test_ledger" name="test_y"/></testsuite></testsuites>')
    assert cover_moved.used_contexts(xml) == {
        "sub/test_scenarios_review.py::test_runaway[stops-at-round-5]": {"given:review/runaway@1"},
        "test_rejections_review.py::test_x": {"wave:review/neg/p0", "wave:review/neg/init"}}


@pytest.mark.small
def test_workdir_is_restored_even_when_the_measure_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", "/before")
    monkeypatch.setattr(cover_moved.tempfile, "tempdir", "/before-cached")
    with pytest.raises(RuntimeError), cover_moved._in_workdir(tmp_path):
        assert cover_moved.os.environ["TMPDIR"] == str(tmp_path) and cover_moved.tempfile.tempdir is None
        raise RuntimeError("測りの途中で落ちた")
    assert cover_moved.os.environ["TMPDIR"] == "/before" and cover_moved.tempfile.tempdir == "/before-cached"


@pytest.mark.small
def test_each_given_is_built_once_under_its_own_context_after_what_it_borrows(monkeypatch):
    """前置きの作りの行は自分の文脈にだけ入る: 位置 k は k-1 と借り先を先に作ってから、自分の文脈に替えて作る"""
    for name in ("HISTORIES", "ROLES", "ROWS"):
        monkeypatch.setattr(scenes, name, {})
    monkeypatch.setattr(waves, "WAVES", {"w/a/init": (None, None), "w/a/x": ("w/a/init", None)})
    scenes.history("review/b", scenes.init("b"), scenes.cmd("patch", scenes.file("m.json", ref=("review/a", "asked", "state", "round"))))
    scenes.history("review/a", scenes.init("a"), scenes.nxt(mark="asked"))   # 借り先は後に登録（作る順は借りる側が決める）
    log = []

    class Built:
        kept = {}

        def build(self, name, k=None):
            log.append((ctx[-1], name, k))
            if k is not None:
                self.kept[(name, k)] = True
    ctx = []
    cover_moved.build_in_contexts(ctx.append, Built(), Built())
    assert log == [("wave:w/a/init", "w/a/init", None), ("wave:w/a/x", "w/a/x", None),
                   ("given:review/b@1", "review/b", 1), ("given:review/a@1", "review/a", 1), ("given:review/a@2", "review/a", 2),
                   ("given:review/b@2", "review/b", 2)]


@pytest.mark.small
@pytest.mark.parametrize("argv, kind", [
    (["git", "rev-parse", "HEAD"], "git"), (["/usr/bin/git"], "git"), (["C:\\Git\\cmd\\git.exe", "status"], "git"),
    ([sys.executable, "-c", "pass"], "python"), (["python3.12", "x.py"], "python"), ("git status", "git"), (["sh", "-c", "x"], "other"),
], ids=["git", "git-path", "git-exe", "this-python", "python-name", "string", "other"])
def test_children_are_sorted_by_the_head_word(argv, kind):
    assert cover_moved.kind_of(argv) == kind


@pytest.mark.medium
def test_children_are_counted_through_the_audit_hook(tmp_path):
    """監査の hook は外せないので、数える回は子のプロセスで起こす（この pytest の worker に載せない）"""
    code = ("import json, subprocess, sys\nsys.path.insert(0, sys.argv[1])\nimport cover_moved\n"
            "with cover_moved.children() as box:\n"
            "    subprocess.run(['git', '--version'], capture_output=True)\n"
            "    with cover_moved.children() as inner:\n"
            "        subprocess.run([sys.executable, '-c', 'pass'])\n"
            "print(json.dumps([box, inner]))\n")
    r = subprocess.run([sys.executable, "-c", code, str(cover_moved.HERE)], capture_output=True, text=True, encoding="utf-8", cwd=tmp_path)
    assert r.returncode == 0, r.stderr[-800:]
    box, inner = json.loads(r.stdout.strip().splitlines()[-1])
    assert box == {"git": 1, "python": 0, "other": 0} and inner == {"git": 0, "python": 1, "other": 0}
