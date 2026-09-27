"""宣言した検査の一式の結果の使い回し（engine/checks_cache.py と role_run.run_steps の入口・出口）。関数を直に呼ぶ。
段は外の印のファイルに 1 字足すので、印の長さが実際に走った回数になる"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from conftest import PLUGIN, REPO
from engine import checks_cache, declared
from engine.role_run import Superseded, run_steps
from engine.rules import load_rules
from engine.schema import load_graph

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]


@pytest.fixture(autouse=True)
def _no_flag(monkeypatch):
    monkeypatch.delenv(checks_cache.RERUN_ENV, raising=False)   # 旗を付けて launch した一式の中でも同じ結果になる


def git(repo, *args):
    subprocess.run([*GIT, "-C", str(repo), *args], check=True, capture_output=True)


def step(mark, code="", name="suite"):
    return {"name": name, "argv": [sys.executable, "-c", f"open({str(mark)!r}, 'a').write('x'){code}"]}


def setup(tmp_path, steps=None, extra=None):
    """宣言を持つ commit 済みのリポジトリ ——（リポジトリ, 段, 印）"""
    repo, mark = tmp_path / "repo", tmp_path / "mark"
    repo.mkdir()
    git(repo, "init", "-q")
    steps = steps or [step(mark)]
    (repo / declared.DECL_NAME).write_text(json.dumps({"suite": steps, **(extra or {})}), encoding="utf-8")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "x")
    return repo, declared.read(repo)["steps"], mark


def ran(mark):
    return len(mark.read_text(encoding="utf-8")) if mark.exists() else 0


def twice(repo, steps, tmp_path, between=None):
    first = run_steps(steps, str(repo), tmp_path / "log1")
    if between:
        between()
    return first, run_steps(steps, str(repo), tmp_path / "log2")


def test_same_tree_reuses_green_with_origin(tmp_path):
    repo, steps, mark = setup(tmp_path, [step(tmp_path / "mark", "; print('1 passed')")])
    first, second = twice(repo, steps, tmp_path)
    assert ran(mark) == 1 and first[0]["exit"] == 0 and "reused" not in first[0] and "書いた" in first[0]["cache"]
    r = second[0]["reused"]
    assert r["from"] == str(tmp_path / "log1") and r["at"] and r["wall_s"] == first[0]["wall_s"]
    assert pathlib.Path(r["entry"]).parent == repo / ".git" / "graphloops" / "checks-cache"
    # 出力は盤面の log_dir に写す——置き場を消しても盤面の行は切れない
    assert second[0]["out"] == str(tmp_path / "log2" / "1.out")
    assert pathlib.Path(second[0]["out"]).read_text(encoding="utf-8").strip() == "1 passed"
    assert second[0]["cache"].startswith("使い回し") and second[0]["exit"] == 0


@pytest.mark.skipif(os.name != "posix", reason="SKIP posix-mode: 段の道具をシェバンの台本として PATH に置く形と実行の印（exec_bit）は POSIX の物")
@pytest.mark.parametrize("change", ["tracked", "untracked", "exec_bit", "decl", "path", "tool", "env", "kernel"])
def test_any_input_change_misses(tmp_path, monkeypatch, change):
    tools = tmp_path / "tools"
    tools.mkdir()
    tool = tools / "gltool"
    tool.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n", encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")
    mark = tmp_path / "mark"
    repo, steps, _ = setup(tmp_path, [{"name": "suite", "argv": ["gltool", "-c", f"open({str(mark)!r}, 'a').write('x')"]}])

    def mutate():
        nonlocal steps
        if change == "tracked":
            (repo / "a.txt").write_text("b\n", encoding="utf-8")
        elif change == "untracked":
            (repo / "new.txt").write_text("", encoding="utf-8")
        elif change == "exec_bit":
            (repo / "a.txt").chmod(0o755)
        elif change == "decl":
            steps = [{**steps[0], "argv": [*steps[0]["argv"], "--x"]}]
            (repo / declared.DECL_NAME).write_text(json.dumps({"suite": steps}), encoding="utf-8")
        elif change == "path":
            monkeypatch.setenv("PATH", os.environ["PATH"] + os.pathsep + str(tmp_path))
        elif change == "tool":
            os.utime(tool, ns=(tool.stat().st_atime_ns, tool.stat().st_mtime_ns + 10**9))
        elif change == "env":
            monkeypatch.setenv("FAIL_ON_SKIP", "1")   # 子の結果を変えうる変数（IGNORED_ENV に無い物）
        elif change == "kernel":
            monkeypatch.setattr(checks_cache.platform, "release", lambda: "other-kernel")

    run_steps(steps, str(repo), tmp_path / "log1")
    mutate()
    second = run_steps(steps, str(repo), tmp_path / "log2")
    assert ran(mark) == 2 and "reused" not in second[0] and second[0]["cache"].startswith("外れ")


def test_ignored_file_change_still_reuses(tmp_path):
    repo, steps, mark = setup(tmp_path)
    (repo / "ignored").mkdir()
    _first, second = twice(repo, steps, tmp_path, lambda: (repo / "ignored" / "x").write_text("x", encoding="utf-8"))
    assert ran(mark) == 1 and second[0].get("reused")


def test_ignored_env_changes_still_reuse(tmp_path, monkeypatch):
    repo, steps, mark = setup(tmp_path)
    run_steps(steps, str(repo), tmp_path / "log1")
    for name in checks_cache.IGNORED_ENV:
        monkeypatch.setenv(name, "changed-between-launches")
    second = run_steps(steps, str(repo), tmp_path / "log2")
    assert ran(mark) == 1 and second[0].get("reused")


def test_env_values_are_not_written_in_plain_text(tmp_path, monkeypatch):
    monkeypatch.setenv("GL_CACHE_SECRET", "s3cret-value-9f2c")
    repo, steps, _mark = setup(tmp_path)
    first = run_steps(steps, str(repo), tmp_path / "log1")
    entry = pathlib.Path(first[0]["cache"].split("書いた: ", 1)[1]) / "entry.json"
    text = entry.read_text(encoding="utf-8")
    assert "s3cret-value-9f2c" not in text and "GL_CACHE_SECRET" in json.loads(text)["material"]["env"]


def test_red_and_unstartable_suites_are_not_stored(tmp_path):
    mark = tmp_path / "mark"
    repo, steps, _ = setup(tmp_path, [step(mark, "; import sys; sys.exit(1)")])
    first, second = twice(repo, steps, tmp_path)
    assert ran(mark) == 2 and "赤か起こせない" in first[0]["cache"] and "reused" not in second[0]
    repo2 = tmp_path / "r2"
    repo2.mkdir()
    git(repo2, "init", "-q")
    bad = [{"name": "missing", "argv": ["no-such-command-gl-cache"]}]
    (repo2 / declared.DECL_NAME).write_text(json.dumps({"suite": bad}), encoding="utf-8")
    run_steps(bad, str(repo2), tmp_path / "l3")
    assert not (repo2 / ".git" / "graphloops" / "checks-cache").exists()


def test_keep_background_suite_always_runs(tmp_path):
    mark = tmp_path / "mark"
    repo, steps, _ = setup(tmp_path, [{**step(mark), "keep_background": True}])
    first, second = twice(repo, steps, tmp_path)
    assert ran(mark) == 2 and first[0]["cache"].startswith("対象外") and "reused" not in second[0]


def test_undeclared_steps_and_non_repo_are_not_cached(tmp_path):
    repo, steps, mark = setup(tmp_path)
    other = [step(mark, name="helper")]   # 宣言に無い語（engine 同梱の語と同じ扱い）
    _a, b = twice(repo, other, tmp_path)
    assert ran(mark) == 2 and b[0]["cache"].startswith("対象外")
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / declared.DECL_NAME).write_text(json.dumps({"suite": steps}), encoding="utf-8")
    _a, b = twice(plain, steps, tmp_path)
    assert ran(mark) == 4 and b[0]["cache"].startswith("対象外")


def test_flag_skips_lookup_keeps_store_and_is_not_passed_to_suite(tmp_path, monkeypatch):
    mark, seen = tmp_path / "mark", tmp_path / "seen"
    code = f"; import os; open({str(seen)!r}, 'w').write(str(os.environ.get({checks_cache.RERUN_ENV!r})))"
    repo, steps, _ = setup(tmp_path, [step(mark, code)])
    monkeypatch.setenv(checks_cache.RERUN_ENV, "1")
    first, second = twice(repo, steps, tmp_path)
    assert ran(mark) == 2 and "旗" in second[0]["cache"] and "書いた" in first[0]["cache"]
    assert seen.read_text(encoding="utf-8") == "None"
    monkeypatch.delenv(checks_cache.RERUN_ENV)
    third = run_steps(steps, str(repo), tmp_path / "log3")
    assert ran(mark) == 2 and third[0].get("reused")


def test_tree_changed_while_running_is_not_stored(tmp_path):
    mark = tmp_path / "mark"
    repo, steps, _ = setup(tmp_path, [step(mark, "; open('side-effect.txt', 'a').write('x')")])
    first = run_steps(steps, str(repo), tmp_path / "log1")
    assert "作業ツリーが変わった" in first[0]["cache"]
    assert not any((repo / ".git" / "graphloops" / "checks-cache").glob("*/entry.json"))


@pytest.mark.parametrize("damage", ["json", "log", "material"])
def test_damaged_entry_is_a_miss_and_is_repaired(tmp_path, damage):
    repo, steps, mark = setup(tmp_path)
    first = run_steps(steps, str(repo), tmp_path / "log1")
    entry = pathlib.Path(first[0]["cache"].split("書いた: ", 1)[1])
    if damage == "json":
        (entry / "entry.json").write_text("{", encoding="utf-8")
    elif damage == "log":
        (entry / "1.out").unlink()
    else:
        e = json.loads((entry / "entry.json").read_text(encoding="utf-8"))
        e["material"]["tree"] = "0" * 40
        (entry / "entry.json").write_text(json.dumps(e), encoding="utf-8")
    second = run_steps(steps, str(repo), tmp_path / "log2")
    third = run_steps(steps, str(repo), tmp_path / "log3")
    assert ran(mark) == 2 and second[0]["cache"].startswith("外れ") and third[0].get("reused")


def test_superseded_attempt_does_not_return_reused_rows(tmp_path):
    repo, steps, _mark = setup(tmp_path)
    run_steps(steps, str(repo), tmp_path / "log1")
    with pytest.raises(Superseded):
        run_steps(steps, str(repo), tmp_path / "log2", still_mine=lambda: False)


def test_second_worktree_in_another_process_reuses(tmp_path):
    """目的の主経路"""
    repo, steps, mark = setup(tmp_path)
    wt = tmp_path / "wt2"
    git(repo, "worktree", "add", "-q", str(wt))
    code = ("import json, sys; sys.path.insert(0, sys.argv[1]); from engine.role_run import run_steps; "
            "print(json.dumps(run_steps(json.loads(sys.argv[2]), sys.argv[3], sys.argv[4])))")
    env = {k: v for k, v in os.environ.items() if k != checks_cache.RERUN_ENV}
    outs = [json.loads(subprocess.run([sys.executable, "-c", code, str(PLUGIN), json.dumps(steps), str(cwd), str(tmp_path / f"l{i}")],
                                      check=True, capture_output=True, text=True, encoding="utf-8", env=env).stdout)
            for i, cwd in enumerate((repo, wt))]
    assert ran(mark) == 1 and outs[1][0]["reused"]["from"] == str(tmp_path / "l0")


RULES = load_rules(PLUGIN / "graphs" / "review-loop.json", load_graph(PLUGIN / "graphs" / "review-loop.json")[0])


def test_checks_reply_names_reuse_with_time_and_run(tmp_path):
    import types
    b = types.SimpleNamespace(round=1, record={"process": {}, "materials": {}, "questions": []},
                              state={"validator": str(REPO / "scripts" / "review-record.py")})
    reused = {"at": "2026-09-27T09:00:00+09:00", "wall_s": 1200.5, "key": "k", "entry": "/c/k", "from": "/board/runs/r1/p0.local_checks.a1"}
    runs = [{"name": "suite", "argv": ["x"], "exit": 0, "wall_s": 0.1, "out": "o", "err": "e", "tail": "", "reused": reused, "cache": "使い回し"}]
    m = RULES.checks_reply(b, "p4.ci", {"sha": "0" * 64}, runs)["reply"]["material"]
    assert m["status"] == "clean" and "使い回し" in m["checked"] and "走らせた" not in m["checked"]
    assert reused["at"] in m["checked"] and reused["from"] in m["checked"] and "1200.5 秒" in m["checked"]
    c = b.record["process"]["checks"]["p4.ci"]
    assert c["reused"] is True and c["runs"][0]["reused"] == reused
