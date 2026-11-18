"""台本を組（shard）に分けて CI の別々の job で回す口（graphloops/tests/parallel.py の shard_spec・assign・aggregate・merge）の単体の検査。
組に分けた実物の回（CI の test job と shards job）は push したブランチの CI で見る。"""
import json

import parallel
import pytest

ENV = {"GL_SHARD_TOTAL": "2", "GL_SHARD_INDEX": "1", "GL_SHARD_GROUP": "g1"}


@pytest.fixture
def sharded(monkeypatch, tmp_path):
    """GL_TEST_ONLY を外すのは、collect が組の指定と同時の指定を拒むから"""
    for k, v in {**ENV, "GL_SHARD_MANIFEST": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GL_TEST_ONLY", raising=False)
    monkeypatch.setattr(parallel, "_deferred", [])
    monkeypatch.setattr(parallel, "_all", [])
    return tmp_path


def test_assign_round_robin_is_disjoint_and_complete():
    names = [f"t{i}" for i in range(11)]
    parts = [parallel.assign(names, i, 4) for i in range(4)]
    assert parts[1] == ["t1", "t5", "t9"]
    assert sorted(sum(parts, [])) == sorted(names)
    assert len(sum(parts, [])) == len(names)


@pytest.mark.parametrize("env", [{}, {"GL_SHARD_TOTAL": ""}, {"GL_SHARD_TOTAL": "1", "GL_SHARD_INDEX": "5"}])
def test_shard_spec_absent_means_whole_suite(env):
    assert parallel.shard_spec(env) is None


@pytest.mark.parametrize("env", [
    {**ENV, "GL_SHARD_MANIFEST": "m", "GL_SHARD_INDEX": "x"},
    {**ENV, "GL_SHARD_MANIFEST": "m", "GL_SHARD_INDEX": "2"},
    {**ENV, "GL_SHARD_MANIFEST": "m", "GL_SHARD_INDEX": "-1"},
    dict(ENV),                                             # 名簿の置き場が無い
    {**ENV, "GL_SHARD_MANIFEST": "m", "GL_SHARD_GROUP": ""},
])
def test_shard_spec_rejects_broken_spec(env, capsys):
    with pytest.raises(SystemExit) as e:
        parallel.shard_spec(env)
    assert e.value.code == 2
    assert "FAIL" in capsys.readouterr().out


def _ns(n):
    ns = {"__name__": "fake_sim"}
    for i in range(n):
        def fn():
            pass
        fn.__name__ = f"test_{i}"
        fn.__module__ = "fake_sim"
        ns[fn.__name__] = fn
    return ns


def test_collect_takes_only_its_shard(sharded):
    assert [f.__name__ for f in parallel.collect(_ns(5))] == ["test_1", "test_3"]
    assert parallel._all == [f"test_{i}" for i in range(5)]   # 組に分ける前の全台本（まとめの口が覆いを見る母集団）


def test_collect_refuses_shard_with_test_only(sharded, monkeypatch, capsys):
    monkeypatch.setenv("GL_TEST_ONLY", "test_1")
    with pytest.raises(SystemExit) as e:
        parallel.collect(_ns(5))
    assert e.value.code == 1 and "同時に使えない" in capsys.readouterr().out


def test_aggregate_judges_in_place_without_shard(monkeypatch):
    for k in parallel.SHARD_ENV:
        monkeypatch.delenv(k, raising=False)
    assert parallel.aggregate("d", "superset", {"a", "b"}, ["a"]) is True
    assert parallel.aggregate("d", "count", ["a", "b"], 3) is False
    assert parallel.aggregate("d", "count", ["a", "b", "c"], 2) is False   # 等値（下限に緩めると上げ忘れが黙って通る）
    assert parallel.aggregate("d", "count", ["a", "a"], 1) is True


def test_aggregate_defers_and_finish_writes_manifest(sharded):
    assert parallel.aggregate("到達", "count", ["b", "a", "a"], 2) is None
    tests = parallel.collect(_ns(4))
    parallel.finish("/x/simulate.py", tests)
    doc = json.loads((sharded / "simulate.json").read_text(encoding="utf-8"))
    assert doc == {"group": "g1", "total": 2, "index": 1, "tests": 2, "ran": ["test_1", "test_3"],
                   "all": ["test_0", "test_1", "test_2", "test_3"],
                   "deferred": [{"desc": "到達", "kind": "count", "seen": ["a", "b"], "want": 2}]}


def _docs(total=2, group="g1"):
    """全組がそろった名簿（台本 6 本を round-robin で分け、どの台本もちょうど 1 組で走った）"""
    out = []
    names = [f"t{j}" for j in range(6)]
    for i in range(total):
        ran = parallel.assign(names, i, total)
        out.append({"name": "counts", "group": group, "total": total, "index": i, "checks": 5, "tests": len(ran)})
        out.append({"name": "sim", "group": group, "total": total, "index": i, "tests": len(ran), "ran": ran, "all": names, "deferred": [
            {"desc": "到達", "kind": "count", "seen": [f"v{i}"], "want": total},
            {"desc": "渡し方", "kind": "superset", "seen": [f"n{i}"], "want": [f"n{j}" for j in range(total)]}]})
    return out


def test_merge_green_when_union_matches():
    assert parallel.merge(_docs() + _docs(group="g2"), ["g1", "g2"]) == []
    assert parallel.merge(_docs(total=3), ["g1"]) == []


def _without(docs, pred):
    return [d for d in docs if not pred(d)]


@pytest.mark.parametrize("name, docs, want", [
    ("組の欠け", lambda: _without(_docs(), lambda d: d["index"] == 1), "0..1 と一致しない"),
    ("範囲の外の組", lambda: _docs() + [{**d, "index": 2} for d in _docs() if d["index"] == 1], "0..1 と一致しない"),
    ("同じ組の名簿の重なり", lambda: _docs() + [_docs()[0]], "重なっている"),
    ("総数の食い違い", lambda: [{**d, "total": 3} if d["index"] == 1 else d for d in _docs()], "総数が揃わない"),
    ("counts の欠け", lambda: _without(_docs(), lambda d: d["name"] == "counts" and d["index"] == 0), "揃いが崩れている"),
    ("台本の名簿の欠け", lambda: _without(_docs(), lambda d: d["name"] == "sim" and d["index"] == 0), "揃いが崩れている"),
    ("どの組でも走らない台本", lambda: [{**d, "ran": d["ran"][1:]} if d["name"] == "sim" and d["index"] == 0 else d for d in _docs()],
     "どの組でも走っていない: t0"),
    ("2 組で走った台本", lambda: [{**d, "ran": d["ran"] + ["t0"]} if d["name"] == "sim" and d["index"] == 1 else d for d in _docs()],
     "2 つ以上の組で走った: t0"),
    ("全台本に無い台本", lambda: [{**d, "ran": d["ran"] + ["tx"]} if d["name"] == "sim" and d["index"] == 1 else d for d in _docs()],
     "全台本の名前に無い台本が走った: tx"),
    ("全台本の名前の食い違い", lambda: [{**d, "all": d["all"][:-1]} if d["name"] == "sim" and d["index"] == 1 else d for d in _docs()],
     "組ごとに違うか空"),
    ("全台本の名前の欠け", lambda: [{k: v for k, v in d.items() if k != "all"} if d["name"] == "sim" else d for d in _docs()],
     "組ごとに違うか空"),
    ("counts と台本の本数の食い違い", lambda: [{**d, "tests": 1} if d["name"] == "sim" and d["index"] == 0 else d for d in _docs()], "台本の名簿の和"),
    ("和集合で届かない到達", lambda: [{**d, "deferred": [{**x, "seen": ["v0"]} for x in d["deferred"]]} if d["name"] == "sim" else d
                                      for d in _docs()], "和集合で通らない"),
    ("1 組にしか無い和の検査", lambda: [{**d, "deferred": d["deferred"][:1]} if d["name"] == "sim" and d["index"] == 1 else d
                                        for d in _docs()], "同じ形で無い"),
    ("知らない group", lambda: _docs() + _docs(group="gx"), "知らない group"),
])
def test_merge_red_arms(name, docs, want):
    bad = parallel.merge(docs(), ["g1"])
    assert any(want in b for b in bad), (name, bad)


def test_merge_red_when_group_missing():
    assert any("1 つも無い" in b for b in parallel.merge(_docs(), ["g1", "g2"]))


def test_cli_merge_reads_dirs(tmp_path, capsys, monkeypatch):
    for i in range(2):
        d = tmp_path / f"gl-shard-g1-{i}"
        d.mkdir()
        (d / "counts.json").write_text(json.dumps({"group": "g1", "total": 2, "index": i, "checks": 3, "tests": 1}), encoding="utf-8")
        (d / "sim.json").write_text(json.dumps({"group": "g1", "total": 2, "index": i, "tests": 1, "ran": [f"t{i}"], "all": ["t0", "t1"],
                                                "deferred": [{"desc": "到達", "kind": "count", "seen": ["a"], "want": 1}]}),
                                    encoding="utf-8")
    assert parallel.main(["merge", "--groups", "g1", *map(str, sorted(tmp_path.iterdir()))]) == 0
    assert "SHARDS_OK" in capsys.readouterr().out
    assert parallel.main(["merge", "--groups", "g1,g2", *map(str, sorted(tmp_path.iterdir()))]) == 1


def test_cli_counts_only_in_shard(sharded, monkeypatch):
    assert parallel.main(["counts", "--checks", "3", "--tests", "1"]) == 0
    assert json.loads((sharded / "counts.json").read_text(encoding="utf-8"))["checks"] == 3
    monkeypatch.delenv("GL_SHARD_TOTAL")
    assert parallel.main(["counts", "--checks", "3", "--tests", "1"]) == 2
