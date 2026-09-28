"""変異の実行器（リポジトリの根の tests/mutate.py）の組（--shard）と和の検算（--merge）。CI の mutation.yml は腕を OS ごとに組に
分けて撃ち、組の報告をまとめてから関門と --same-as に渡すので、欠け・食い違い・重なりを健全と言わないことと、まとめた報告が
1 本で撃った報告と同じ欄を持つことを縛る"""
import copy
import importlib.util
import json
import re
import sys

import conftest
import parallel
import pytest

_spec = importlib.util.spec_from_file_location("mutate_shard_under_test", conftest.REPO / "tests" / "mutate.py")
mutate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutate)

SEL = ["a", "b", "c", "d", "e"]


def _shard(k, n=2, sel=SEL, rev="r1", **over):
    ids = mutate.shard_of(sel, k, n)
    rep = {"schemaVersion": "1", "rev": rev, "at": f"2026-09-28T0{k}:00:00+00:00", "pruned": [],
           "shard": {"k": k, "n": n, "selected": sel},
           "arms": [{"id": i, "title": i, "status": "Killed", "evidence": "印"} for i in ids],
           "control": {"root": {"rc": 0}}, "marker": {"rc": 0, "placed": ids, "seen": ids, "cover": {i: ["s~t"] for i in ids}, "skipped": {}},
           "summary": {"control_ok": True, "green": [], "uncovered": [], "pytest_control_ok": True, "pruned": 0,
                       "pytest_how": {"nodes": len(ids)}, "copies": {"made": 1, "reused": len(ids), "discarded": {"x": 1}}}}
    rep.update(over)
    return (f"s{k}.json", rep)


@pytest.mark.small
@pytest.mark.parametrize("text, want", [("0/1", (0, 1)), ("3/4", (3, 4)), ("4/4", None), ("1/0", None), ("a/2", None), ("", None)])
def test_parse_shard_reads_k_of_n(text, want):
    assert mutate.parse_shard(text) == want


@pytest.mark.small
def test_shards_cover_the_selection_once_round_robin():
    parts = [mutate.shard_of(SEL, k, 3) for k in range(3)]
    assert parts == [["a", "d"], ["b", "e"], ["c"]] and sorted(x for p in parts for x in p) == SEL


@pytest.mark.small
@pytest.mark.parametrize("n", [1, 2, 3, 8])
def test_shard_of_is_the_round_robin_of_the_script_shards(n):
    ids = [f"x{i}" for i in range(11)]
    assert [mutate.shard_of(ids, k, n) for k in range(n)] == [parallel.assign(ids, k, n) for k in range(n)]


@pytest.mark.small
def test_merge_of_all_shards_reads_like_one_report():
    """全部の組がそろえば健全で、腕は選別の順・copies と数の辞書は和・真偽は all（--same-as が使い回しを読める）"""
    res = mutate.merge_reports([_shard(1), _shard(0)])
    assert "merge_problems" not in res and mutate.healthy(res)
    assert [a["id"] for a in res["arms"]] == SEL and res["at"].startswith("2026-09-28T00")
    s = res["summary"]
    assert s["copies"] == {"made": 2, "reused": 5, "discarded": {"x": 2}} and s["pytest_how"] == {"nodes": 5}
    assert s["pytest_control_ok"] is True and s["control_ok"] is True and s["uncovered"] == []
    assert sorted(res["marker"]["seen"]) == SEL and res["marker"]["rc"] == 0 and set(res["control"]) == {"0:root", "1:root"}
    assert mutate.gate_efficacy(res)["material"]["status"] == "clean"


@pytest.mark.small
@pytest.mark.parametrize("reports, want", [
    ([_shard(0)], "組が欠けた"),
    ([_shard(0), _shard(1, n=3)], "組の数 n が揃わない"),
    ([_shard(0), _shard(0), _shard(1)], "同じ組の報告が 2 つ以上"),
    ([_shard(0), _shard(1, sel=SEL[::-1])], "selected が揃わない"),
    ([_shard(0), _shard(1, rev="r2")], "rev が揃わない"),
    ([_shard(0), _shard(1, arms=[])], "割り当てと一致しない"),
    ([_shard(0), _shard(1, partial=True)], "撃ち切っていない"),
    ([_shard(0), ("x.json", {"arms": []})], "組の身元"),
], ids=["missing", "n", "dup-k", "selected", "rev", "assignment", "partial", "not-a-shard"])
def test_merge_names_every_broken_sum(reports, want):
    res = mutate.merge_reports(reports)
    assert any(want in p for p in res["merge_problems"]) and not mutate.healthy(res)


@pytest.mark.small
def test_merge_names_an_arm_shot_by_two_shards():
    _, a = _shard(0)
    _, b = _shard(1)
    b["arms"].append(dict(a["arms"][0]))
    assert any("2 つ以上の組に在る腕" in p for p in mutate.merge_reports([("s0", a), ("s1", b)])["merge_problems"])


@pytest.mark.small
def test_merge_keeps_red_marker_and_uncountable_coverage():
    """1 組の印の写しが赤なら全体も赤（rc は最初の 0 でない値）、1 組が覆いを数えられない（None）なら全体も数えられない"""
    s0, s1 = _shard(0), _shard(1)
    s1[1]["marker"]["rc"] = "timeout"
    s1[1]["summary"]["uncovered"] = None
    res = mutate.merge_reports([s0, s1])
    assert res["marker"]["rc"] == "timeout" and res["summary"]["uncovered"] is None and not mutate.healthy(res)


@pytest.mark.small
def test_red_control_pytest_of_a_shard_does_not_fail_the_whole_run():
    """組の control の pytest が赤でも、まとめた回は健全のまま（evaluate と同じく pytest の赤だけを証拠から外す——組ごとに外してある）。
    台本の control の赤は全体を赤にする"""
    s0, s1 = _shard(0), _shard(1)
    s1[1]["control"]["pytest"] = {"rc": 1}
    s1[1]["summary"]["pytest_control_ok"] = False
    res = mutate.merge_reports([s0, s1])
    assert mutate.healthy(res) and res["summary"]["control_ok"] and res["summary"]["pytest_control_ok"] is False
    s1[1]["control"]["root"] = {"rc": 1}
    assert not mutate.healthy(mutate.merge_reports([s0, s1]))


@pytest.mark.small
def test_empty_shards_are_left_out_of_the_sums():
    sel = ["a"]
    res = mutate.merge_reports([_shard(0, sel=sel), _shard(1, sel=sel, control=None, marker=None, summary=None)])
    assert "merge_problems" not in res and set(res["control"]) == {"0:root"} and [x["assigned"] for x in res["shards"]] == [1, 0]
    empty = mutate.merge_reports([_shard(0, sel=[], arms=[]), _shard(1, sel=[], arms=[])])
    assert empty.get("empty") and not empty["arms"]


@pytest.mark.small
def test_a_shard_of_only_unshootable_arms_merges_healthy_and_keeps_its_skipped():
    """撃てない腕（Ignored）だけの組は control と印の写しを持たないので合わせる母数から外し、その腕は和の summary.skipped に残る
    （1 本で撃った回の summary と同じ）"""
    ign = _shard(1, arms=_arms_of(1, status="Ignored"), control=None, marker=None, summary=None)
    res = mutate.merge_reports([_shard(0), ign])
    assert "merge_problems" not in res and set(res["control"]) == {"0:root"} and mutate.healthy(res)
    assert sorted(res["summary"]["skipped"]) == mutate.shard_of(SEL, 1, 2)


@pytest.mark.small
def test_assigned_is_the_assignment_not_the_rows_received():
    res = mutate.merge_reports([_shard(0), _shard(1, arms=[])])
    assert [x["assigned"] for x in res["shards"]] == [len(mutate.shard_of(SEL, k, 2)) for k in range(2)]


@pytest.mark.small
@pytest.mark.parametrize("field, a, b", [("pytest_stage", "uv が PATH に無い", None), ("pruned", [], [{"id": "x"}])], ids=["pytest_stage", "pruned"])
def test_every_head_field_must_agree_across_shards(field, a, b):
    s0, s1 = _shard(0), _shard(1)
    for s, v in ((s0, a), (s1, b)):
        if v is None:
            s[1].pop(field, None)
        else:
            s[1][field] = v
    assert any(f"組ごとの {field} が揃わない" in p for p in mutate.merge_reports([s0, s1])["merge_problems"])


@pytest.mark.small
def test_one_shard_is_read_as_the_whole_only_through_the_sum():
    """組 1 本は和の検算（欠けた組）を通して読む——健全で腕も同じ今の回と比べても、前の回の不健全だけが食い違いに出る"""
    _, one = _shard(0)
    assert mutate.gate_efficacy(one)["material"]["status"] == "found"
    fresh = {k: v for k, v in copy.deepcopy(one).items() if k != "shard"}
    assert mutate.healthy(fresh) and mutate.same_as_diff(one, fresh) == ["前の回の control か印の写しが赤"]


@pytest.mark.small
@pytest.mark.parametrize("vals, key, want", [
    ([0, 0], "rc", 0), ([0, -9, 1], "rc", -9), ([1, None], None, None), ([True, False], None, False),
    ([1, 2], None, 3), ([[1], [2]], None, [1, 2]), ([{"a": 1}, {"a": 2, "b": [1]}], None, {"a": 3, "b": [1]}), (["x", "y"], None, "x"),
])
def test_merge_values_has_one_rule_per_type(vals, key, want):
    assert mutate.merge_values(vals, key) == want


ROWS = [
    {"id": "a", "title": "a", "status": "Killed", "own": True, "hit": "t.py::a", "attribution": "pytest", "pytest": {"how": "nodes"}},
    {"id": "b", "title": "b", "status": "Survived", "own": False, "pytest_selected": True, "pytest": {"how": "nodes"}},
    {"id": "c", "title": "c", "status": "Killed", "own": True, "attribution": "narrowed"},
    {"id": "d", "title": "d", "status": "Ignored", "own": False},
    {"id": "e", "title": "e", "status": "Killed", "own": False, "attribution": "unrelated"},
    {"id": "f", "title": "f", "status": "Survived", "own": False, "selected": True},
    {"id": "g", "title": "g", "status": "Killed", "own": False, "attribution": "narrowed"},
]
EXPECT = {"a": "t.py::a", "c": "x", "g": "y"}


def _evaluated(ids):
    placed = [i for i in ids if i != "d"]
    res = {"arms": [copy.deepcopy(r) for r in ROWS if r["id"] in ids],
           "marker": {"rc": 0, "placed": placed, "seen": [i for i in placed if i != "f"], "cover": {}, "skipped": {}},
           "control": {"root": {"rc": 0}, "pytest": {"rc": 0}}}
    mutate.evaluate(res, [{"id": i, **({"expect": EXPECT[i]} if i in EXPECT else {})} for i in ids])
    return res


@pytest.mark.small
def test_the_sum_of_the_shards_reads_like_one_run():
    """組ごとに評価して和の規則でまとめた summary が、全腕を 1 回で評価した summary と同じ（和の規則が欄を取り違えない）"""
    ids = [r["id"] for r in ROWS]
    whole = _evaluated(ids)["summary"]
    merged = mutate.merge_reports([(f"s{k}", {**_evaluated(mutate.shard_of(ids, k, 2)), "schemaVersion": "1", "rev": "r", "pruned": [],
                                              "shard": {"k": k, "n": 2, "selected": ids}}) for k in range(2)])
    norm = lambda s: {k: sorted(v) if isinstance(v, list) else v for k, v in s.items()}
    assert "merge_problems" not in merged and norm(merged["summary"]) == norm(whole)
    assert whole["pytest_how"] == {"nodes": 2} and whole["no_evidence"] == ["g"] and whole["green"] == ["b", "f"]


def _main(monkeypatch, *argv):
    """main を argv で起こして終了コードを返す（撃つ段の前で抜ける道だけ。main が書き換える大域は戻す）"""
    for name in ("ARMS_FILE", "CONFIRM", "FRESH", "PYTEST_STAGE"):
        monkeypatch.setattr(mutate, name, getattr(mutate, name))
    monkeypatch.setattr(sys, "argv", ["mutate.py", *argv])
    monkeypatch.delenv(mutate.ENGINE_CHILD, raising=False)
    with pytest.raises(SystemExit) as e:
        mutate.main()
    return e.value.code


def _written(tmp_path, reports):
    for name, r in reports:
        (tmp_path / name).write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    return [str(tmp_path / name) for name, _ in reports]


def _arms_of(k, **row):
    return [{"id": i, "title": i, **row} for i in mutate.shard_of(SEL, k, 2)]


@pytest.mark.small
@pytest.mark.parametrize("reports, want", [
    ([_shard(0), _shard(1)], "clean"),
    ([_shard(0), _shard(1, arms=_arms_of(1, status="Survived", evidence=""))], "found"),
    ([_shard(0), _shard(1, arms=_arms_of(1, status="Killed", evidence=""))], "found"),
    ([_shard(0)], "found"),
    ([_shard(0, arms=_arms_of(0, status="Ignored")), _shard(1, arms=_arms_of(1, status="Ignored"))], "not_run"),
], ids=["all-proven", "survived", "no-evidence", "missing-shard", "all-ignored"])
def test_merge_exit_and_gate_status_read_the_same_passed(tmp_path, monkeypatch, reports, want):
    """--merge の終了コード・--gate-efficacy の status・passed が 1 つの表で揃う"""
    out = tmp_path / "r.json"
    code = _main(monkeypatch, "--merge", *_written(tmp_path, reports), "--out", str(out))
    res = json.loads(out.read_text(encoding="utf-8"))
    assert mutate.gate_efficacy(res)["material"]["status"] == want
    assert (code, mutate.passed(res)) == ((0, True) if want == "clean" else (1, False))


@pytest.mark.small
@pytest.mark.parametrize("flag", ["--merge", "--gate-efficacy", "--same-as"])
def test_unreadable_report_exits_2(tmp_path, monkeypatch, flag):
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert _main(monkeypatch, flag, str(tmp_path / "bad.json")) == 2


@pytest.mark.small
def test_unreadable_previous_report_exits_2(tmp_path):
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        mutate.reusable(str(tmp_path / "bad.json"))
    assert e.value.code == 2


def _arms_file(tmp_path, monkeypatch, ids, **extra):
    """一時の置き場に腕の一覧（root の台本・印つき）を書き、基点と HEAD をそこへ向ける ——一覧の道"""
    (tmp_path / "f.txt").write_text("".join(f"{i}\n" for i in ids), encoding="utf-8")
    arms = [{"id": i, "title": i, "file": "f.txt", "suite": "root", "old": i, "new": "z", "marker": {"where": "before"}, **extra} for i in ids]
    (tmp_path / "arms.json").write_text(json.dumps({"arms": arms}), encoding="utf-8")
    monkeypatch.setattr(mutate, "base", lambda: tmp_path)
    monkeypatch.setattr(mutate, "head_rev", lambda: "r1")
    return str(tmp_path / "arms.json")


@pytest.mark.small
def test_a_shard_of_only_unshootable_arms_writes_the_same_head(tmp_path, monkeypatch):
    """撃てる腕が 0 本の組も、頭（pruned ほか）と割り当ての腕（Ignored の行）を書いて 0 で抜け、兄弟の組と健全にまとまる"""
    arms = _arms_file(tmp_path, monkeypatch, ["A", "B"], python_max="3.0")
    out = tmp_path / "s0.json"
    assert _main(monkeypatch, "--arms-file", arms, "--shard", "0/2", "--out", str(out)) == 0
    s0 = json.loads(out.read_text(encoding="utf-8"))
    res = mutate.merge_reports([("s0", s0), _shard(1, sel=["A", "B"])])
    assert s0["pruned"] == [] and [(r["id"], r["status"]) for r in s0["arms"]] == [("A", "Ignored")]
    assert "merge_problems" not in res and mutate.healthy(res)


def _fake_shoot(seen):
    def shoot(a, res, fire, sel, fps, late, pend):
        seen["fire"] = sorted(x["id"] for x in fire)
        res["arms"] += [{"id": x["id"], "title": x["id"], "status": "Killed", "own": False, "failed": []} for x in fire]
        res["control"], res["marker"] = {"root": {"rc": 0}}, {"rc": 0, "placed": [], "seen": [x["id"] for x in fire], "cover": {}, "skipped": {}}
        return []
    return shoot


@pytest.mark.small
def test_main_shard_shoots_only_its_assignment_and_writes_the_head(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(mutate, "shoot", _fake_shoot(seen))
    monkeypatch.setattr(mutate, "install_stop_handlers", lambda: None)
    arms = _arms_file(tmp_path, monkeypatch, ["A", "B", "C"])
    out = tmp_path / "s1.json"
    assert _main(monkeypatch, "--arms-file", arms, "--shard", "1/2", "--out", str(out)) == 0
    s1 = json.loads(out.read_text(encoding="utf-8"))
    assert seen["fire"] == ["B"] and [r["id"] for r in s1["arms"]] == ["B"]
    assert s1["shard"] == {"k": 1, "n": 2, "selected": ["A", "B", "C"]} and s1["rev"] == "r1" and s1["pruned"] == []


@pytest.mark.small
def test_main_shard_with_no_assignment_writes_its_identity_and_exits_0(tmp_path, monkeypatch):
    monkeypatch.setattr(mutate, "shoot", lambda *a: pytest.fail("割り当て 0 本の組が撃った"))
    arms = _arms_file(tmp_path, monkeypatch, ["A"])
    out = tmp_path / "s1.json"
    assert _main(monkeypatch, "--arms-file", arms, "--shard", "1/2", "--out", str(out)) == 0
    s1 = json.loads(out.read_text(encoding="utf-8"))
    assert s1["arms"] == [] and s1["shard"]["selected"] == ["A"] and "pruned" in s1


@pytest.mark.small
@pytest.mark.parametrize("flags", [["--shard", "0/2"], ["--check"], ["--merge", "x.json"]], ids=["shard", "check", "merge"])
def test_same_as_is_not_combined_with_shard_check_or_merge(tmp_path, monkeypatch, flags):
    _, one = _shard(0)
    rep = _written(tmp_path, [("prev.json", one)])[0]
    monkeypatch.setattr(mutate, "load", lambda: pytest.fail("拒まずに腕の一覧を読んだ（本物の一覧で撃ち始める）"))
    assert _main(monkeypatch, "--same-as", rep, *flags) == 2


WORKFLOWS = conftest.REPO / ".github" / "workflows"


ALWAYS = re.compile(r"^ +if: always\(\)$", re.M)


def mutation_workflow_problems(text, test_yml):
    """mutation.yml の形の問題の一覧（空なら無い）——この workflow の形を縛る唯一の置き場。text は mutation.yml、test_yml は
    SKIP_ALLOW の値の正本 test.yml の本文。見るのは、SKIP_ALLOW が頭の 1 つと Windows の job の上書きだけで値が正本と同じこと、
    まとめる・撃ち比べる job が組とまとめる段の赤でも走り、まとめる段の終了コードを捨てず、撃ち比べの報告を残すこと"""
    probs = []
    allow = dict(re.findall(r'- os: (\S+)\n\s+skip_allow: "([^"]*)"', test_yml))
    jobs = dict(re.findall(r"\n  ([\w-]+):\n((?:(?!\n  [\w-]+:\n).)*)", text[text.index("\njobs:\n"):], re.S))
    posix = {allow.get("ubuntu-latest"), allow.get("macos-latest")}
    if len(posix) != 1 or None in posix:
        probs.append(f"test.yml の ubuntu と macOS の skip_allow が揃わない（頭の 1 つで渡せない）: {sorted(map(str, posix))}")
    top = re.search(r'^env:\n  SKIP_ALLOW: "([^"]*)"$', text, re.M)
    if not top or top.group(1) not in posix:
        probs.append("workflow の頭の env の SKIP_ALLOW が無いか、test.yml の ubuntu・macOS の値と違う")
    declared = bool(top)
    for name, body in jobs.items():
        runs = re.search(r"^    runs-on: (.+)$", body, re.M).group(1)
        oss = re.search(r"^\s+os: \[([^\]]*)\]", body, re.M).group(1).split(", ") if runs.startswith("${{") else [runs]
        own = re.search(r'^    env:\n      SKIP_ALLOW: "([^"]*)"$', body, re.M)
        declared += bool(own)
        win = [o for o in oss if o.startswith("windows")]
        if win and not (own and all(allow.get(o) == own.group(1) for o in oss)):
            probs.append(f"{name}: Windows で走る job の env に test.yml の Windows の SKIP_ALLOW の上書きが無い")
        if own and not win:
            probs.append(f"{name}: Windows でない job が SKIP_ALLOW を上書きする（頭の値を黙って覆う）")
    if len(re.findall(r"^\s*SKIP_ALLOW:", text, re.M)) != declared:
        probs.append("SKIP_ALLOW が workflow の頭と job の env の外（段の env など）に在る")
    for name in ("merge", "same-as"):
        body = jobs.get(name, "")
        if not ALWAYS.search(body.split("\n    steps:")[0]):
            probs.append(f"{name} の job の頭に if: always() が無い（needs の先が赤だと、段の if より先に job ごと飛ばされる）")
        if "continue-on-error" in body:
            probs.append(f"{name} の job に continue-on-error が在る")
    if not re.search(r"^        run: python tests/mutate\.py --merge shards/\*/shard\.json --out mutation-report\.json$", jobs.get("merge", ""), re.M):
        probs.append("まとめる段の run が --merge だけでない（終了コードを捨てると関門が消える）")
    same = jobs.get("same-as", "")
    steps = same.split("\n      - ")[1:]
    if not re.search(r"^    needs: merge$", same, re.M):
        probs.append("撃ち比べの job が needs: merge を持たない")
    if not any("--same-as mutation-report.json" in s and ALWAYS.search(s) for s in steps):
        probs.append("撃ち比べの段が if: always() でない（まとめる段の赤で飛ばされる）")
    if not any("upload-artifact" in s and ALWAYS.search(s) and re.search(r"^ +path: fresh-report\.json$", s, re.M) for s in steps):
        probs.append("撃ち比べの job が撃ち比べの報告（fresh-report.json）を if: always() で残していない")
    return probs


def _workflows():
    return (WORKFLOWS / "mutation.yml").read_text(encoding="utf-8"), (WORKFLOWS / "test.yml").read_text(encoding="utf-8")


@pytest.mark.small
def test_the_mutation_workflow_has_no_shape_problems():
    assert mutation_workflow_problems(*_workflows()) == []


WIN_ALLOW = '    env:\n      SKIP_ALLOW: "posix-mode process-group fifo read-permission version-bump"\n'


@pytest.mark.small
@pytest.mark.parametrize("old, new, where, want", [
    ('env:\n  SKIP_ALLOW: "version-bump"\n', 'env:\n  SKIP_ALLOW: "x"\n', "mutation", "workflow の頭の env の SKIP_ALLOW"),
    ('env:\n  SKIP_ALLOW: "version-bump"\n\njobs:', "jobs:", "mutation", "workflow の頭の env の SKIP_ALLOW"),
    (WIN_ALLOW, "", "mutation", "shard-windows: Windows で走る job"),
    ("  shard-macos:\n    runs-on: macos-latest\n", "  shard-macos:\n    runs-on: macos-latest\n" + WIN_ALLOW, "mutation", "shard-macos: Windows でない job"),
    ("          K: ${{ strategy.job-index }}\n", "          K: ${{ strategy.job-index }}\n          SKIP_ALLOW: \"x\"\n", "mutation", "段の env など"),
    ("    needs: [shard-ubuntu, shard-windows, shard-macos]\n    if: always()\n", "    needs: [shard-ubuntu, shard-windows, shard-macos]\n",
     "mutation", "merge の job の頭に if: always()"),
    ("    needs: merge\n    if: always()\n", "    needs: merge\n", "mutation", "same-as の job の頭に if: always()"),
    ("    needs: merge\n", "    needs: [shard-ubuntu]\n", "mutation", "needs: merge"),
    ("  merge:\n", "  merge:\n    continue-on-error: true\n", "mutation", "merge の job に continue-on-error"),
    ("--out mutation-report.json\n      - name: まとめた", "--out mutation-report.json || true\n      - name: まとめた", "mutation", "まとめる段の run"),
    ("        if: always()\n        shell: bash\n        run: python tests/mutate.py -j 4 --confirm-survivors --same-as",
     "        shell: bash\n        run: python tests/mutate.py -j 4 --confirm-survivors --same-as", "mutation", "撃ち比べの段が if: always()"),
    ("          path: fresh-report.json", "          path: other.json", "mutation", "fresh-report.json"),
    ("      - name: 撃ち比べの報告を残す\n        if: always()\n", "      - name: 撃ち比べの報告を残す\n", "mutation", "fresh-report.json"),
    ('- os: macos-latest\n', '- os: macos-latest\n            skip_allow: "other"\n', "test", "ubuntu と macOS の skip_allow が揃わない"),
], ids=["top-value", "top-gone", "windows-override-gone", "override-outside-windows", "step-env", "merge-always", "same-as-always",
        "same-as-needs", "merge-continue-on-error", "merge-exit-dropped", "same-as-step-always", "same-as-report-path",
        "same-as-report-always", "test-yml-posix-split"])
def test_every_entrance_of_the_workflow_shape_is_red(old, new, where, want):
    """形の検査が縛る入口ごとに本文を 1 か所だけ壊すと、その入口の問題が出る（1 か所の赤は覆いの証拠にならない）"""
    mut, test = _workflows()
    src = mut if where == "mutation" else test
    assert src.count(old) == 1, old
    broken = src.replace(old, new)
    got = mutation_workflow_problems(broken, test) if where == "mutation" else mutation_workflow_problems(mut, broken)
    assert any(want in p for p in got), got
