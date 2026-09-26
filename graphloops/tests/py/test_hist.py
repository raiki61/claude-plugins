"""履歴から作る読み取り専用の値（hist.<名>。engine/hist.py と rules の HIST）の検査。盤面は出荷の review-loop の graph を指す本物の
Board を tmp_path に組む——周の記録（rounds/）と周ごとの節の出力（out/r<N>/・rd の instance）から値が作られ、履歴に何も足さず、
控えは正本でない印を持ち、手当ての口（loop.py patch）が hist の値を拒むことを見る。"""
import json
import subprocess
import sys

import pytest

from conftest import PLUGIN, REVIEW_VALIDATOR
from engine import board as board_mod
from engine import filelock
from engine import hist as hist_mod

GRAPH = PLUGIN / "graphs" / "review-loop.json"
TDD_GRAPH = PLUGIN / "graphs" / "review-loop-tdd.json"


def rd(n, done=(), instances=None, stopped=None):
    return {"round": n, "done": {k: True for k in done}, "na": {}, "skipped": {}, "stopped": stopped or {}, "empty": [],
            "instances": instances or {}, "item_counts": {}}


def make(tmp_path, rnd, rounds, *, loop=None, records=None, outs=None, record=None, graph=GRAPH):
    """rounds は rd の一覧、records は {周: 周の記録}、outs は {(節, 周): 出力}（今の周は state.outputs、前の周は rd の instance）"""
    d = tmp_path / "run"
    (d / "rounds").mkdir(parents=True)
    outputs = {}
    for (nid, n), val in (outs or {}).items():
        f = d / "out" / f"r{n}" / f"{nid}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(val, ensure_ascii=False), encoding="utf-8")
        rel = str(f.relative_to(d))
        if n == rnd:
            outputs[nid] = {"file": rel, "round": n}
        else:
            rounds[n - 1]["instances"][f"{nid}@r{n}"] = {"id": f"{nid}@r{n}", "node": nid, "status": "done", "output_file": rel}
    for n, rec in (records or {}).items():
        (d / "rounds" / f"round-{n}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    state = {"graph": str(graph), "round": rnd, "rounds": rounds, "loop": loop or {}, "rev": 0, "outputs": outputs,
             "inputs": {"cwd": str(tmp_path)}, "validator": str(REVIEW_VALIDATOR), "run_id": "t", "loop_name": "review-loop",
             "thickness": None, "done_ever": {}}
    (d / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    (d / "record.json").write_text(json.dumps(record or {"materials": {}, "units": [], "questions": [], "process": {}},
                                              ensure_ascii=False), encoding="utf-8")
    return board_mod.Board(d)


def rec(n, units=(), reviews=None, materials=None, questions=()):
    return {"base": "b" * 40, "round": n, "materials": materials or {}, "units": list(units), "reviews": reviews or {},
            "questions": list(questions)}


U = lambda key, label, **kw: {"key": key, "label": label, "reason": "r", **kw}   # noqa: E731
SEEN = {"status": "clean", "checked": "見た"}


def test_values_come_from_closed_round_records(tmp_path):
    """前の周の値・積み上げ・最後の判定は閉じた周の記録から作る。今の周の記録は周の締め（p4.record）が済むまで数えない"""
    r1 = rec(1, [U("a", "block"), U("d", "suggest", disposition="defer")],
             {"R1": {"status": "redesign-needed", "reason": "直せ"}}, {"hygiene": SEEN})
    r2 = rec(2, [U("a", "info"), U("b", "block")],
             {"R1": {"status": "redesign-needed", "reason": "直せ" + "（round 1 と同じ。持ち越せない値なので今も諮っている記録として書く）"},
              "R2": {"status": "carried_over", "from_round": 1, "reason": "x"}},
             {"hygiene": {"status": "carried_over", "from_round": 1, "reason": "x"}}, [{"key": "q", "kind": "fork", "status": "held"}])
    cur = {"materials": {"hygiene": {"status": "found", "count": 1, "detail": "今の周"}}, "units": [], "questions": [], "process": {}}
    b = make(tmp_path, 3, [rd(1, ["p4.record"]), rd(2, ["p4.record"]), rd(3)], records={1: r1, 2: r2}, record=cur)
    assert b.hist("prev_units") == r2["units"] and b.hist("prev_questions") == r2["questions"] and b.hist("prev_scalars") == {}
    assert b.hist("block_counts") == [{"round": 1, "n": 1}, {"round": 2, "n": 1}]
    assert b.hist("closed_keys") == ["a"] and b.hist("prev_blocks") == ["a", "b"]
    assert b.hist("defer_ledger") == {"d": {"reason": "r", "round": 1}}
    # 据え置いた行（持ち越せない値を前の周と同じとして書いた行）は最後の判定を書き換えない
    assert b.hist("last_review") == {"R1": {"round": 1, "status": "redesign-needed", "reason": "直せ"}}
    # 素材は閉じた周の記録＋今の周の素材集めの出口
    assert b.hist("last_seen") == {"hygiene": 3} and b.hist("last_material")["hygiene"]["detail"] == "今の周"
    # 今の周の記録を書いても、周の締めが済むまでは閉じた周に入らない（検証器に落ちて組み直しを待つ記録を数えない）
    (b.dir / "rounds" / "round-3.json").write_text(json.dumps(rec(3, [U("c", "block")])), encoding="utf-8")
    assert b.hist("block_counts")[-1]["round"] == 2
    b.state["rounds"][2]["done"]["p4.record"] = True
    assert b.hist("block_counts")[-1] == {"round": 3, "n": 1} and b.hist("prev_blocks") == ["a", "b", "c"]


def test_first_round_has_no_previous_values(tmp_path):
    """1 周目は前の周の値が無い——穴は ABSENT、条件は default で受ける（空の値で埋めない）"""
    b = make(tmp_path, 1, [rd(1)])
    for name in ("prev_units", "prev_questions", "prev_one_shot", "prev_declared_faces", "prev_rejudge"):
        assert b.hist(name) is hist_mod.HIST_ABSENT
        with pytest.raises(KeyError):
            b.ctx()["hist"][name]
    assert b.hist("lines_at_r1") is hist_mod.HIST_ABSENT and b.hist("block_counts") == []


def test_patched_rejudge_reaches_the_next_round(tmp_path):
    """回す側が loop.py patch で出した異議（loop.rejudge_requested）は、同じ周の擦り合わせで決着しなければ次の周の
    hist.prev_rejudge に届く（周の境目で異議を降ろさない）。往復の回数は受け付けた擦り合わせの節の数で、周ごと"""
    ask = {"round": 2, "text": "patch で出した異議"}
    b = make(tmp_path, 2, [rd(1), rd(2, ["p2.rejudge"])], loop={"rejudge_requested": ask})
    assert b.hist("rejudge_rounds") == {"round": 2, "n": 1}
    assert b.cond("rejudge_open")[0] is True
    b.state["rounds"].append(rd(3))
    b.state["round"] = 3
    assert b.hist("prev_rejudge") == ask and b.hist("rejudge_rounds") == {"round": 3, "n": 0}
    assert b.cond("rejudge_open")[0] is False   # 前の周の異議では同じ周の往復は開かない
    b.loop_state.pop("rejudge_requested")    # 採る／退けるで決着した（rejudge_output が降ろす）
    assert b.hist("prev_rejudge") is None


def test_rejudge_from_the_fix_reply_when_the_loop_has_none(tmp_path):
    """旧い版の rules は周の境目で loop から異議を降ろしていた——その盤面でも、前の周の p3.fix の返答の異議が届く。
    擦り合わせで採る／退けるに決着していれば届けない"""
    outs = {("p3.fix", 1): {"rejudge_requested": "返答で出した異議"}}
    b = make(tmp_path, 2, [rd(1), rd(2)], outs=outs)
    assert b.hist("prev_rejudge") == {"round": 1, "text": "返答で出した異議"}
    outs[("p2.rejudge", 1)] = {"verdict": "退ける"}
    assert make(tmp_path / "settled", 2, [rd(1), rd(2)], outs=outs).hist("prev_rejudge") is None


def test_lane_rows_are_read_from_the_ledger_and_old_marks_are_not_counted(tmp_path):
    """線から渡した行は線の台帳に残した周と行から読む。渡した周を持たない旧い印（delivered: true・版だけの文字列）は
    どの周の行にも数えない（true == 1 だが、1 周目には前の周の穴が無い）"""
    lanes = {"a" * 40: {"round": 1, "delivered": True, "delivered_rows": [{"key": "旧い印"}]},
             "b" * 40: {"round": 1, "delivered": 2, "delivered_rows": [{"key": "線の行"}]}}
    bad = ["c" * 40, {"rev": "d" * 40, "round": 2, "row": {"key": "読めない行"}}]
    b = make(tmp_path, 2, [rd(1), rd(2)], loop={"lanes": lanes, "lanes_bad_delivered": bad})
    assert [r["key"] for r in b.hist("prev_declared_faces")] == ["読めない行", "線の行"]


def test_head_revs_prefer_rev_and_read_old_outputs_by_tree(tmp_path):
    """周の頭の版は突合の基準の rev から。rev を持たない旧い出力は木の id で読む（git diff は木でも差を取れる）"""
    outs = {("p1.worktree_before", 1): {"ok": True, "tree_before": {"porcelain": [], "stash": "", "tree": "t" * 40}},
            ("p1.worktree_before", 2): {"ok": True, "tree_before": {"porcelain": [], "stash": "", "tree": "u" * 40, "rev": "r" * 40}}}
    b = make(tmp_path, 2, [rd(1), rd(2)], outs=outs)
    assert b.hist("head_revs") == {"1": "t" * 40, "2": "r" * 40}


def test_tdd_adds_the_gave_up_rows_to_the_declared_faces(tmp_path):
    outs = {("p3.tdd_red", 1): {"ok": True, "gave_up": "red", "problems": ["赤でない"]}}
    b = make(tmp_path, 2, [rd(1), rd(2)], outs=outs, graph=TDD_GRAPH)
    assert b.hist("tdd_gave_up") == [{"round": 1, "step": "red", "problems": ["赤でない"]}]
    assert [r["from"] for r in b.hist("prev_declared_faces")] == ["p3.tdd_red"]


def test_save_writes_a_control_that_is_not_canonical_and_adds_nothing_to_history(tmp_path):
    b = make(tmp_path, 2, [rd(1, ["p4.record"]), rd(2)], records={1: rec(1, [U("a", "block")])})
    before = sorted(p.relative_to(b.dir).as_posix() for p in b.dir.rglob("*"))
    b.save()
    ctl = json.loads((b.dir / "hist.json").read_text(encoding="utf-8"))
    assert ctl["canonical"] is False and "正本でない" in ctl["note"] and ctl["values"]["prev_blocks"] == ["a"] and ctl["errors"] == []
    after = sorted(p.relative_to(b.dir).as_posix() for p in b.dir.rglob("*"))
    # 周の記録・節の出力・trace に何も足さない（盤面の錠のファイルは保存の錠で、履歴ではない——engine/filelock.py）
    assert set(after) - set(before) - {filelock.BOARD_LOCK_NAME} == {"hist.json"}
    assert "hist" not in json.loads((b.dir / "state.json").read_text(encoding="utf-8"))["loop"]


def test_control_records_values_outside_the_hist_schema(tmp_path):
    b = make(tmp_path, 2, [rd(1, ["p4.record"]), rd(2)], records={1: rec(1, [U(7, "block")])})
    b.save()
    st = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
    assert any("hist.prev_blocks" in r["error"] for r in st["hist_drift"])
    assert json.loads((b.dir / "hist.json").read_text(encoding="utf-8"))["errors"]


def test_old_board_keeps_opening_and_hist_does_not_read_the_old_copies(tmp_path):
    """旧い盤面（loop に C2 の写しを持つ）は開けて保存でき、外れは痕跡に残る。hist は写しを読まず履歴から作る"""
    b = make(tmp_path, 2, [rd(1, ["p4.record"]), rd(2)], loop={"prev_units": [{"key": "写し"}], "closed_keys": ["写し"]},
             records={1: rec(1, [U("本物", "info")])})
    b.save()
    st = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
    assert any("prev_units" in r["error"] for r in st["loop_drift"])
    assert b.hist("prev_units")[0]["key"] == "本物" and b.hist("closed_keys") == ["本物"]


def test_history_refuses_undeclared_reads(tmp_path):
    b = make(tmp_path, 2, [rd(1), rd(2)])
    fn = hist_mod.hist_reads("rounds")(lambda h: h.output("p3.fix", 1))
    with pytest.raises(SystemExit):
        hist_mod.compute(b, "x", fn, [])
    loops = hist_mod.hist_reads("hist.y")(lambda h: h.hist("y"))
    b.rules.HIST["y"] = loops
    try:
        with pytest.raises(SystemExit):
            b.hist("y")
    finally:
        del b.rules.HIST["y"]


@pytest.mark.parametrize("path", ["state.loop.closed_keys", "state.loop.prev_units.0", "hist.defer_ledger", "state.loop.prev_one_shot"])
def test_patch_refuses_hist_values(tmp_path, path):
    """hist の値への手当ては、書いても次に引く時に作り直されて効かない——ok と言わずに拒み、元の履歴を直す口を案内する"""
    b = make(tmp_path, 2, [rd(1), rd(2)])
    val = tmp_path / "v.json"
    val.write_text("[]", encoding="utf-8")
    r = subprocess.run([sys.executable, str(PLUGIN / "scripts" / "loop.py"), "patch", "--path", path, "--file", str(val),
                        "--reason", "検査", "--dir", str(b.dir)], capture_output=True, text=True, encoding="utf-8")
    msg = r.stdout + r.stderr
    assert r.returncode != 0 and "書いても次に引くとき作り直されて効かない" in msg
    # 案内は値の元から引く——閉じた周の記録から作る値には直す口が無いと言い、節の出力を読む値にはその節の手当てを名指す
    if "closed_keys" in path or "prev_units" in path:
        assert "閉じた周の記録（rounds/round-<N>.json）から作る部分は直す口が無い" in msg and "out." not in msg.split("直すなら値の元を:")[1].split("（控え")[0]
    elif "prev_one_shot" in path:
        assert "loop.py patch --path out.p2.history.<欄>" in msg and "直す口が無い" not in msg
    else:
        assert "閉じた周の記録" in msg
    assert "patches" not in json.loads((b.dir / "state.json").read_text(encoding="utf-8"))


def test_repair_routes_cover_every_declarable_head():
    """案内は宣言できる頭の全部に 1 行ずつ出る——読む物の宣言から組むので、どの頭を読む値でも案内が空にならない"""
    fn = hist_mod.hist_reads("rounds", "rd", "out.p3.fix", "loop.lanes", "record.materials", "inputs.cwd", "hist.prev_units")(lambda h: None)
    routes = hist_mod.repair_routes(fn)
    assert len(routes) == 7 and "inputs.cwd から作る部分は直す口が無い" in routes


def test_patch_still_writes_run_state(tmp_path):
    """run の状態（B）の鍵は今までどおり手当てできる——異議を patch で出す実運用の口"""
    b = make(tmp_path, 2, [rd(1), rd(2)])
    val = tmp_path / "v.json"
    val.write_text(json.dumps({"round": 2, "text": "異議"}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(PLUGIN / "scripts" / "loop.py"), "patch", "--path", "state.loop.rejudge_requested",
                        "--file", str(val), "--reason", "検査", "--dir", str(b.dir)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert json.loads((b.dir / "state.json").read_text(encoding="utf-8"))["loop"]["rejudge_requested"]["text"] == "異議"
