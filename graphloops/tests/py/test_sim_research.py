"""research-loop の盤面を端から端まで回す筋書き（S2b で graphloops/tests/simulate.py から移した。対応は MIGRATION.md）。

台本の土台（Run・drive・check・代役の返答・補助の検査）は simulate.py のまま使い、loop.py を呼ぶ口（cli・inproc）は gl_script
（glharness.py）が選ぶ。check の件数は pytest の柵（conftest.py の EXPECTED_SIM_CHECKS）が数える。関数は gl_script の代わりに
「種類 → 台本のモジュール」の関数を受けても回る（golden_make.py の snap が筋書きの途中の盤面を写すときにそう呼ぶ）。"""
import subprocess

import pytest


@pytest.mark.medium
@pytest.mark.layer6
def test_converges(gl_script):
    sim = gl_script("research")
    check = sim.check
    print("台本: 標準・3 周で収束")
    run = sim.Run("std")
    check(run.init.returncode == 0, "init が通る")
    last = sim.drive(run, "std")
    rec, st = run.record(), run.state()
    check(last["status"] == "converged", "status が converged")
    check(rec["convergence"] == {"rounds_total": 3, "consecutive_zero": 2, "outcome": "converged"}, f"convergence が 3 周・連続 2: {rec['convergence']}")
    check([r["verdict"] for r in rec["gates"]["cold_reader"]["rounds"]] == ["redesign-needed", "pass"], "cold_reader が 2 周（redesign→pass）")
    check(rec["gates"]["rederiver"]["verdict"] == "pass", "rederiver は比較係の pass")
    check(rec["gates"]["cartographer"].get("status") == "not_applicable", "標準では cartographer は not_applicable")
    check(rec["sampling"]["status"] == "done" and rec["sampling"]["overturned"] == 0, f"抜き取りが走り覆り 0: {rec['sampling']}")
    check(next(c for c in rec["claims"] if c["id"] == "B")["verdict"] == "確証", "B は再照合で確証に戻った")
    check(next(c for c in rec["claims"] if c["id"] == "A")["refuted"] is True, "荷重の確証 A は反証を経た")
    check([c["no"] for c in rec["corrections"]] == [1, 2], f"訂正の番号は機械が連番で振る: {[c['no'] for c in rec['corrections']]}")
    check((run.dir / "report.md").is_file(), "report.md が保存された")
    # 開いた問いが 0 件の run の収束の文言は、分けた文言を足す前と 1 字も変わらない（回帰）
    check(sim.converge_reasons(run)[-1] == "連続 2 周で新規相違ゼロ、標準 段のゲートは全部 pass",
          f"開いた問いの無い収束の文言は元のまま: {sim.converge_reasons(run)[-1:]}")
    v = subprocess.run([sim.PY, str(sim.VALIDATOR), str(run.dir / "record.json")], capture_output=True, text=True, encoding="utf-8", timeout=600)
    check(v.returncode == 0, f"検証器が exit 0（{v.stdout.strip()[:60]}）")
    r1 = st["rounds"][0]
    check("p0.independence_review" in r1["na"], "独立出典だけなので independence_review は na")
    check(any(i.startswith("p1.refuter[A]") for i in r1["instances"]) and any(i.startswith("p1.refuter[B]") for i in r1["instances"]), "refuter は A（荷重確証）と B（相違）に走った")
    check("p1.checker" in st["rounds"][2]["empty"], "3 周目の checker は項目ゼロ（empty）")
    check(len(rec["process"]["skipped"]) == 0, "省略なし")
    sim.loop_shape_held(run, "標準・収束", {"stuck_ids"}, "sampled_r")
    sim.rm(run.tmp)
