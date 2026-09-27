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
    for name in ("prev_units", "prev_questions", "prev_one_shot", "prev_declared_faces", "prev_rejudge", "prev_own_precedents"):
        assert b.hist(name) is hist_mod.HIST_ABSENT
        with pytest.raises(KeyError):
            b.ctx()["hist"][name]
    assert b.hist("lines_at_r1") is hist_mod.HIST_ABSENT and b.hist("block_counts") == []


def test_own_precedents_carry_over_rounds_that_skipped_history(tmp_path):
    """修正役が自分で当たった先行例は次の周の p2.history へ渡る。p2.history を省いた周に渡るはずだった行は次の周へ持ち越し、
    読まれた周より前の行は落とす。判定者の行を採った先行例（from_judge_row）は渡さない"""
    own = lambda k: {"unit_key": k, "precedent": {"url": f"https://example.org/{k}"}}   # noqa: E731
    fix = lambda *ks: {"changes": [own(k) for k in ks] + [{"unit_key": "j", "precedent": {"from_judge_row": True}}]}   # noqa: E731
    outs = {("p3.fix", 1): fix("a"), ("p3.fix", 2): fix("b"), ("p2.history", 3): {"units": []}, ("p3.fix", 3): fix("c"),
            ("p3.fix", 4): fix("d")}
    b = make(tmp_path, 5, [rd(n) for n in range(1, 6)], outs=outs)
    # 周 4 は p2.history を省いた——周 3 の行（c）を持ち越し、周 3 に読まれた周 1・2 の行は落とす
    assert b.hist("prev_own_precedents") == [own("c"), own("d")]
    b2 = make(tmp_path / "x", 3, [rd(n) for n in range(1, 4)], outs={("p3.fix", 1): fix("a"), ("p3.fix", 2): fix("b")})
    assert b2.hist("prev_own_precedents") == [own("a"), own("b")]   # 1 周目は p2.history が無い（p2.diagnose）ので持ち越す


FIX_OK = {"changes": [], "fix_closure": {"status": "not_applicable", "reason": "修正なし"}, "gates_changed": False, "interactions": [],
          "mechanism_changed": False, "not_done": [], "path_changed": False, "plan_faces": [], "premise_drift": False,
          "seams_changed": False, "security_surface_changed": False, "wrote_refs": []}


def _patch(b, path, value, tmp_path):
    val = tmp_path / "v.json"
    val.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return subprocess.run([sys.executable, str(PLUGIN / "scripts" / "loop.py"), "patch", "--path", path, "--file", str(val),
                           "--reason", "検査", "--dir", str(b.dir)], capture_output=True, text=True, encoding="utf-8")


def test_patched_rejudge_reaches_the_next_round(tmp_path):
    """回す側が loop.py patch で出した異議（修正の出口 out.p3.fix.rejudge_requested）は、同じ周の擦り合わせを開き、決着しなければ
    次の周の hist.prev_rejudge に届く。往復の回数は受け付けた擦り合わせの節の数で、周ごと"""
    b = make(tmp_path, 2, [rd(1), rd(2)], outs={("p3.fix", 2): FIX_OK})
    r = _patch(b, "out.p3.fix.rejudge_requested", "patch で出した異議", tmp_path)
    assert r.returncode == 0, r.stderr
    b = board_mod.Board(b.dir)
    assert b.cond("rejudge_open")[0] is True
    b.state["rounds"][1]["done"]["p2.rejudge"] = True
    assert b.hist("rejudge_rounds") == {"round": 2, "n": 1}
    b.state["rounds"].append(rd(3))
    b.state["round"] = 3
    assert b.hist("prev_rejudge") == {"round": 2, "text": "patch で出した異議"} and b.hist("rejudge_rounds") == {"round": 3, "n": 0}
    assert b.cond("rejudge_open")[0] is False   # 前の周の異議では同じ周の往復は開かない


def test_rejudge_from_the_fix_reply_until_settled(tmp_path):
    """前の周の p3.fix の返答の異議が届く。擦り合わせで採る／退けるに決着していれば届けない。旧い盤面の loop の異議は読まない
    （保存の時の照らしが state_schema の外の鍵として警告を残す）"""
    outs = {("p3.fix", 1): {"rejudge_requested": "返答で出した異議"}}
    b = make(tmp_path, 2, [rd(1), rd(2)], outs=outs, loop={"rejudge_requested": {"round": 1, "text": "旧い loop の異議"}})
    assert b.hist("prev_rejudge") == {"round": 1, "text": "返答で出した異議"}
    outs[("p2.rejudge", 1)] = {"verdict": "退ける"}
    assert make(tmp_path / "settled", 2, [rd(1), rd(2)], outs=outs).hist("prev_rejudge") is None


def test_lane_rows_are_read_from_the_round_head_output(tmp_path):
    """線から渡した行は、渡した周の頭の節（p1.worktree_before）の出力の lane_rows から読む。線の台帳（loop.lanes）に旧い版の
    rules が残した行は読まない——台帳は patch で書き換えられる run の状態で、過去の周の値の元にしない"""
    lanes = {"b" * 40: {"round": 1, "delivered": 2, "delivered_rows": [{"key": "台帳の旧い行"}]}}
    outs = {("p1.worktree_before", 2): {"ok": True, "lane_rows": [{"key": "線の行", "from": "p3.delta_gates", "how": "needs_test: x"}]}}
    b = make(tmp_path, 2, [rd(1), rd(2)], loop={"lanes": lanes}, outs=outs)
    assert [r["key"] for r in b.hist("prev_declared_faces")] == ["線の行"]


def test_snapshot_and_after_fix_are_separate_exits(tmp_path):
    """周の頭の審査対象（hist.snapshot）と修正後の審査対象（hist.after_fix）は別の節の出力の別の欄——同じ鍵を上書きしない。
    撮り直した回の p1.worktree_after の snapshot が在ればそちらが効く。入口の周だけ依頼の where が範囲になる"""
    head = {"rev": "h" * 40, "diff_file": "/d/diff-r2.patch", "changed_files": ["a.py"], "changed_files_file": "/d/changed-r2.txt",
            "stat": "1 files", "diff_lines": 3, "entry": True}
    after = {**head, "rev": "f" * 40, "diff_file": "/d/diff-r2-after-fix.patch", "changed_files": ["a.py", "b.py"]}
    outs = {("p1.worktree_before", 2): {"ok": True, "snapshot": head}, ("p4.assemble", 2): {"ok": True, "after_fix": after}}
    record = {"materials": {}, "units": [], "questions": [], "process": {"request_findings": [
        {"round": 2, "origin": "人", "findings": [{"where": "x.py: f", "text": "t"}]}]}}
    b = make(tmp_path, 2, [rd(1), rd(2)], outs=outs, record=record)
    assert b.hist("snapshot")["rev"] == "h" * 40 and b.hist("after_fix")["rev"] == "f" * 40
    assert b.hist("request_wheres") == ["x.py: f"]
    # 本文を貼る写し（paste_file）を持たない出力（貼る写しを作る前の版）は全文の写しを貼る。持つ出力はそれを返す
    assert b.hist("snapshot")["paste_file"] == head["diff_file"] and b.hist("after_fix")["paste_file"] == after["diff_file"]
    outs[("p4.assemble", 2)] = {"ok": True, "after_fix": {**after, "paste_file": "/d/diff-r2-after-fix.paste.patch"}}
    assert make(tmp_path / "paste", 2, [rd(1), rd(2)], outs=outs, record=record).hist("after_fix")["paste_file"].endswith(".paste.patch")
    retaken = {**head, "rev": "r" * 40, "entry": False}
    outs[("p1.worktree_after", 2)] = {"ok": True, "snapshot": retaken}
    b = make(tmp_path / "retaken", 2, [rd(1), rd(2)], outs=outs, record=record)
    assert b.hist("snapshot")["rev"] == "r" * 40 and b.hist("request_wheres") == []


def test_old_outputs_are_read_as_exits_with_a_mark(tmp_path):
    """旧い版の rules が書いた出力（差分の一式が出力の上の段・p4.assemble の写しの痕跡だけ）は、印 from_old_output を付けて
    読み替える（人の決定 2026-09-27: 旧い盤面は警告して通す）。旧い loop の差分の鍵は読まない"""
    d = tmp_path / "files"
    d.mkdir()
    (d / "changed-r2-after-fix.txt").write_text("a.py\nb.py\n", encoding="utf-8")
    outs = {("p1.worktree_before", 2): {"ok": True, "diff_file": str(d / "diff-r2.patch"), "changed_files": ["a.py"], "stat": "s",
                                        "tree_before": {"porcelain": [], "stash": "", "tree": "t" * 40, "rev": "h" * 40}},
            ("p4.assemble", 2): {"ok": True, "retaken": {"file": str(d / "diff-r2-after-fix.patch")}}}
    b = make(tmp_path, 2, [rd(1), rd(2)], outs=outs, loop={"diff_file": "旧い loop の値"})
    snap, fixed = b.hist("snapshot"), b.hist("after_fix")
    assert snap["from_old_output"] and snap["rev"] == "h" * 40 and snap["changed_files_file"] == str(d / "changed-r2.txt")
    assert fixed["from_old_output"] and fixed["changed_files"] == ["a.py", "b.py"] and fixed["diff_file"].endswith("-after-fix.patch")
    assert snap["paste_file"] == snap["diff_file"] and fixed["paste_file"] == fixed["diff_file"]


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
    fn = hist_mod.hist_reads("rounds", "rd", "out.p3.fix", "record.materials", "inputs.cwd", "hist.prev_units")(lambda h: None)
    routes = hist_mod.repair_routes(fn)
    assert len(routes) == 6 and "inputs.cwd から作る部分は直す口が無い" in routes


def test_patch_still_writes_run_state(tmp_path):
    """run の状態（B）の鍵は今までどおり手当てできる（線を止める印）"""
    b = make(tmp_path, 2, [rd(1), rd(2)], loop={"lanes": {"a" * 40: {"round": 1, "result": "x", "state": "running"}}})
    r = _patch(b, f"state.loop.lanes.{'a' * 40}.state", "abandoned", tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads((b.dir / "state.json").read_text(encoding="utf-8"))["loop"]["lanes"]["a" * 40]["state"] == "abandoned"


@pytest.mark.parametrize("key", ["rejudge_requested", "diff_file", "prev_fix_files"])
def test_patch_refuses_keys_moved_to_node_outputs(tmp_path, key):
    """ブロックの出口の値は節の出力に移った——state_schema に無い鍵への手当ては書いても効かないので、ok と言わずに拒み、
    節の出力を直す口を案内する（旧い patch の綴りが黙って効かなくなる形を作らない）"""
    b = make(tmp_path, 2, [rd(1), rd(2)])
    r = _patch(b, f"state.loop.{key}", {"round": 2, "text": "異議"}, tmp_path)
    msg = r.stdout + r.stderr
    assert r.returncode != 0 and "state_schema に無い" in msg and "loop.py patch --path out.<節>.<欄>" in msg
    assert key not in json.loads((b.dir / "state.json").read_text(encoding="utf-8"))["loop"]
