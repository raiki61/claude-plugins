"""線 A の試験の手助け（test_* でないので unittest の発見に拾われない）。

- seed_repo: dev/target-seed/ を写した使い捨ての git リポジトリ（初めの commit つき。名前と時刻は固定）
- reply:     tests/replies/<名>.json の役の返答の見本
- git_env:   名前と時刻を固定した git の環境
- work_home: 使い捨ての物を置く家（${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/single/。Claude Code の一時フォルダの下に置かない）
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import hermetic  # noqa: E402

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
SEED = ROOT / "dev" / "target-seed"
REPLIES = TESTS / "replies"
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
GIT_ID = ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "init.defaultBranch=main"]
DECLARATION = {"suite": [{"name": "suite", "argv": ["python3", "-m", "unittest", "test_stats"]}]}
BROKEN_DECLARATION = {"suite": []}   # 宣言の書式の誤り（suite は 1 段以上）。engine は読めずに任せ先へ落とす


def git_env() -> dict:
    """名前と時刻を固定した git の環境（利用者の設定の名前・署名に左右されない）"""
    fixed = {"GIT_AUTHOR_NAME": "works-test", "GIT_AUTHOR_EMAIL": "works-test@example.invalid",
             "GIT_COMMITTER_NAME": "works-test", "GIT_COMMITTER_EMAIL": "works-test@example.invalid",
             "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000"}
    return hermetic.child_env(**fixed)


def git(repo, *args) -> str:
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=True,
                          env=git_env()).stdout.strip()


def seed_repo(into: pathlib.Path, *, declared: bool = False, broken_declaration: bool = False) -> pathlib.Path:
    """into に種（stats.py・test_stats.py）を写し、git の初めの commit を作って、その置き場の絶対パスを返す。
    declared なら .review-checks.json（suite 1 段）も、broken_declaration なら書式の誤った宣言も同じ commit に入れる"""
    if declared and broken_declaration:
        raise ValueError("declared と broken_declaration は片方だけ")
    into = pathlib.Path(into)
    shutil.copytree(SEED, into, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    decl = DECLARATION if declared else BROKEN_DECLARATION if broken_declaration else None
    if decl is not None:
        (into / ".review-checks.json").write_text(json.dumps(decl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    git(into, "init", "-q")
    git(into, "add", "-A")
    git(into, "commit", "-q", "-m", "seed")
    return into.resolve()


def reply(name: str) -> dict:
    """tests/replies/<name>.json"""
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


# 判定の前に盤面が待つ役の節（前提の後。目的の文・判定から入る 1 周目の素材集め）と見本の返答。p2.diagnose はこれらが済むまで待ちにならない
PRE_JUDGE = (("p0.purpose", "purpose_ok"), ("p0.prior_decisions", "prior_decisions_ok"),
             ("p0.purpose_review", "purpose_review_ok"))


def pre_judge(board, repo, only=None) -> list:
    """前提の後・判定の前に盤面が待つ役の節（PRE_JUDGE）を、待っている物だけ見本の返答で渡す（起こした印を置いてから
    entry.take）。盤面を線の順に進める試験の手助け（p2.diagnose を待ちにする）。only を渡せばその節だけ。返りは渡した節"""
    import entry
    done = []
    for nid, name in PRE_JUDGE:
        if only is not None and nid not in only:
            continue
        b = entry.open_board(pathlib.Path(board))
        inst = next((i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending"), None)
        if inst is None:
            continue
        b.mark_launched(nid, inst.get("attempts", 1))
        got = entry.take(pathlib.Path(board), nid, reply(name), pathlib.Path(repo))
        if not got["ok"]:
            raise AssertionError(f"{nid} の見本 {name} を盤面が受けない: {got['reason']}")
        done.append(nid)
    return done


def close_eyes(board, repo, replies=None) -> list:
    """最後のテストの後に盤面が待つ独立の目（R1〜R4・前提の検め直し）と、修正の前に作る独立設計（r2.design。ラインでは境の節
    h-look が控えを渡す）を、待っている物が無くなるまで見本の返答で渡す（起こした印を置いてから entry.take）。最後の目の受け付けの
    settle が周の記録と収束まで回し、1 周の run は周を締める。返答は replies[節]（無ければ test_blk_eyes の見本と design_ok）。
    返りは渡した節の順"""
    import design
    import entry
    if str(ROOT / "blk-eyes" / "lib") not in sys.path:
        sys.path.insert(0, str(ROOT / "blk-eyes" / "lib"))
    import eyes
    import test_blk_eyes as TB
    samples = {**{n: TB.REPLY[r] for n, r in eyes.ROLE_OF.items()}, design.NODE: reply("design_ok")}
    done = []
    while True:
        b = entry.open_board(pathlib.Path(board), allow_halted=True)
        if b.state.get("halted") or b.state.get("pending_human"):
            return done
        todo = [n for n in samples if eyes._pending(b, n)]
        if not todo:
            return done
        for nid in todo:
            b = entry.open_board(pathlib.Path(board))
            b.mark_launched(nid, eyes._pending(b, nid).get("attempts", 1))
            body = (replies or {}).get(nid, samples[nid])
            got = entry.take(pathlib.Path(board), nid, body, pathlib.Path(repo))
            if not got["ok"]:
                raise AssertionError(f"{nid} の見本を盤面が受けない: {got['reason']}")
            done.append(nid)


CLAUDE_TMP = ("/private/tmp/claude-", "/tmp/claude-")   # Claude Code の一時フォルダ（dev/guard.sh と同じ決まり）


def work_home() -> pathlib.Path:
    """${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/single/ を解決した字で返す（作って返す）。盤面は解決した字を返すので、
    解決しない字（macOS の /var → /private/var）を配ると relative_to と文字列比較が割れる。Claude Code の一時フォルダの下に
    解決される置き場は、作る前に BoardGap で拒む（サンドボックスの Bash が書ける所に使い捨ての物を置かない）"""
    from board import BoardGap   # 盤面の層の誤りの型（.shared/core を sys.path に足してある）
    base = os.environ.get("WORKS_DEV_HOME") or str(pathlib.Path.home() / ".cache" / "works-dev")
    given = pathlib.Path(base) / "single"
    home = given.resolve()
    for p in (str(given), str(home)):
        if p.startswith(CLAUDE_TMP):
            raise BoardGap(f"work_home: {given} が Claude Code の一時フォルダの下にある（{home}）。WORKS_DEV_HOME を別の場所にする")
    home.mkdir(parents=True, exist_ok=True)
    # 盤面の置き場は受け付けが一度だけ resolve する（script_io.board_dir）。macOS の /var → /private/var のリンクの下でも
    # 試験が持つパスと受け付けが返すパスの綴りを揃える
    return home.resolve()


# ---------------------------------------------------------------- 線の節の並び（P1 計画 Task 28・〔線A計〕T16。C18 の順）
# darkfactory.yaml はこの並びと同じに書き、tests/test_line.py の test_line_order_matches_linekit が YAML と突き合わせる
# （手で 2 か所に書き写したまま放さない。裁定 TA16）。行は {id, kind: script|include|approval, script?, block?, at?,
# depends_on, trigger_rule?, when?, with: {鍵: 出どころ}}。境の節（script edge）は edge.py の INPUTS を全部受け、使わない物は "null"。
NFMOS = "none_failed_min_one_success"
ALL_DONE = "all_done"
EDGE_INPUTS = ("at", "judged", "premised", "gate", "tests", "adapter", "final_gate")


def _edge(nid, at, deps, **given):
    """境の節の行。edge.py の INPUTS を全部渡す（使わない物は文字列 null。A-T10a の持ち越し 1）"""
    w = {k: "null" for k in EDGE_INPUTS}
    w.update(at=at, adapter="$start.output.adapter", final_gate="$INPUTS.final_gate", **given)
    return {"id": nid, "kind": "script", "script": "edge", "at": at, "depends_on": deps, "trigger_rule": NFMOS, "with": w}


def _skippable(src):
    return {"from": src, "if_skipped": None}


LINE_ORDER = [
    {"id": "launch", "kind": "approval"},
    {"id": "start", "kind": "script", "script": "start", "depends_on": ["launch"],
     "with": {"request": "$INPUTS.request", "base": "$INPUTS.base", "pr": "$INPUTS.pr",
              "test_cmd": "$INPUTS.test_cmd", "thickness": "$INPUTS.thickness",
              "gates": "$INPUTS.gates", "final_gate": "$INPUTS.final_gate", "adapter": "$INPUTS.adapter",
              "policy_md": "$INPUTS.policy_md", "lang": "$INPUTS.lang", "unattended": "$INPUTS.unattended"}},
    {"id": "ci-checking", "kind": "include", "block": "blk-ci", "depends_on": ["start"],
     "when": "$start.output.ci_role_go == true",
     "with": {"node": "p0.local_checks", "base_rev": "$start.output.base_rev"}},
    _edge("h-entry", "entry", ["start", "ci-checking"]),
    {"id": "pr-checking", "kind": "include", "block": "blk-pr", "depends_on": ["h-entry"],
     "when": "$h-entry.output.pr_go == true", "with": {}},
    {"id": "premising", "kind": "include", "block": "blk-premises", "depends_on": ["h-entry", "pr-checking"],
     "trigger_rule": NFMOS, "when": "$h-entry.output.premises_go == true",
     "with": {"request": "$INPUTS.request", "base_rev": "$start.output.base_rev"}},
    _edge("h-judge", "judge", ["start", "h-entry", "premising"], premised=_skippable("$premising.output")),
    {"id": "purposing", "kind": "include", "block": "blk-purpose", "depends_on": ["h-judge"],
     "when": "$h-judge.output.purpose_go == true",
     "with": {"request": "$INPUTS.request", "constraints_file": "$h-judge.output.premises_file",
              "base_rev": "$start.output.base_rev"}},
    _edge("h-mat", "mat", ["start", "h-judge", "purposing"]),
    {"id": "gathering", "kind": "include", "block": "blk-material", "depends_on": ["h-mat"],
     "when": "$h-mat.output.mat_go == true",
     "with": {"base_rev": "$start.output.base_rev", "adapter": "$start.output.adapter",
              "purpose_file": "$h-mat.output.purpose_file"}},
    {"id": "judging", "kind": "include", "block": "blk-judge", "depends_on": ["h-mat", "gathering"], "trigger_rule": NFMOS,
     "when": "$h-mat.output.go == true",
     "with": {"request": "$INPUTS.request", "base_rev": "$start.output.base_rev",
              "policy_paste": "$start.output.policy_paste", "premises_file": "$h-judge.output.premises_file"}},
    _edge("h-plan", "plan", ["start", "h-mat", "judging"], judged=_skippable("$judging.output")),
    {"id": "planning", "kind": "include", "block": "blk-plan", "depends_on": ["h-plan"],
     "when": "$h-plan.output.go == true",
     "with": {"judgment_file": "$h-plan.output.judgment_file", "base_rev": "$start.output.base_rev",
              "policy_paste": "$start.output.policy_paste", "policy_path": "$start.output.policy_path",
              "include_id": "planning"}},
    _edge("h-gate", "gate", ["start", "h-plan", "planning"]),
    {"id": "policy-gate", "kind": "approval", "depends_on": ["h-gate"], "when": "$h-gate.output.ask == true",
     "decisions": ["approve", "continue", "stop", "reject"]},
    _edge("h-fix", "fix", ["start", "h-gate", "policy-gate"], gate=_skippable("$policy-gate.output")),
    {"id": "fixing", "kind": "include", "block": "blk-fix", "depends_on": ["h-fix"],
     "when": "$h-fix.output.go == true",
     "with": {"judgment_file": "$h-fix.output.judgment_file", "open_units": "$h-fix.output.open_units",
              "plan_file": "$h-fix.output.plan_file", "notes_file": "$h-fix.output.notes_file",
              "base_rev": "$start.output.base_rev", "policy_path": "$start.output.policy_path",
              "tdd_suite": "$INPUTS.tdd_suite"}},
    _edge("h-rejudge", "rejudge", ["start", "h-fix", "fixing"]),
    {"id": "rejudging", "kind": "include", "block": "blk-rejudge", "depends_on": ["h-rejudge"],
     "when": "$h-rejudge.output.go == true",
     "with": {"base_rev": "$start.output.base_rev", "policy_paste": "$start.output.policy_paste"}},
    _edge("h-mid", "mid", ["start", "h-rejudge", "rejudging"]),
    _edge("h-review", "review", ["start", "h-mid"]),
    {"id": "reviewing", "kind": "include", "block": "blk-delta", "depends_on": ["h-review"],
     "when": "$h-review.output.go == true", "with": {"base_rev": "$start.output.base_rev"}},
    _edge("h-refix", "refix", ["start", "h-review", "reviewing"]),
    {"id": "refixing", "kind": "include", "block": "blk-refix", "depends_on": ["h-refix"],
     "when": "$h-refix.output.go == true",
     "with": {"base_rev": "$start.output.base_rev", "policy_paste": "$start.output.policy_paste",
              "policy_path": "$start.output.policy_path"}},
    _edge("h-tests", "tests", ["start", "h-refix", "refixing"]),
    {"id": "testing", "kind": "include", "block": "blk-tests", "depends_on": ["h-tests"],
     "when": "$h-tests.output.go == true", "with": {"cmd": "$start.output.test_cmd", "mode": "final"}},
    _edge("h-look", "look", ["start", "h-tests", "testing"]),
    {"id": "eyeing", "kind": "include", "block": "blk-eyes", "depends_on": ["h-look"], "when": "$h-look.output.go == true",
     "with": {"base_rev": "$start.output.base_rev"}},
    _edge("h-final", "final", ["start", "h-tests", "testing", "h-look", "eyeing"], tests=_skippable("$testing.output")),
    {"id": "final-gate", "kind": "approval", "depends_on": ["h-final"], "when": "$h-final.output.ask == true",
     "decisions": ["approve", "continue", "stop", "reject"]},
    _edge("h-eyes", "eyes", ["start", "h-final", "final-gate"], gate=_skippable("$final-gate.output")),
    # 機械の報告は上流の節が落ちた run でも走る（all_done）。start のほかの出力は落ちても飛ばされても null で受ける
    {"id": "report", "kind": "script", "script": "report", "depends_on": ["start", "h-eyes", "eyeing"],
     "trigger_rule": ALL_DONE,
     "with": {"judged": _skippable("$judging.output"), "tests": _skippable("$testing.output"),
              "start": {"from": "$start.output"}, "mid": _skippable("$h-mid.output"),
              "ci": _skippable("$ci-checking.output"), "eyes": _skippable("$h-eyes.output"),
              "eyeing": _skippable("$eyeing.output")}},
    {"id": "reporting", "kind": "include", "block": "blk-report", "depends_on": ["report"],
     "when": "$report.output.ai_report_go == true", "with": {"machine_report": "$report.output.report_file"}},
    # 出口（returns）。AI の報告のブロックが落ちても機械の報告で出口を出す（all_done: 前の節の成否に依らず走る）
    {"id": "result", "kind": "script", "script": "result", "depends_on": ["report", "reporting"], "trigger_rule": ALL_DONE,
     "with": {"machine": {"from": "$report.output"}, "ai": _skippable("$reporting.output")}},
]


# ---------------------------------------------------------------- 線を Archon 無しで通す（P1 計画 Task 28・〔線A計〕T16）
RUN_ID = "run-line-a"
GATES = frozenset(r["id"] for r in LINE_ORDER if r["kind"] == "approval" and r.get("decisions"))


class LineRun:
    """LINE_ORDER の順に、境の節（line_edge.edge）・ブロックの口（受け付け・支度・出口の関数）・関所の答えを本物の盤面の上で回す。
    Archon の置き換え（with: → INPUTS_*）は tests/test_line_inputs.py の test_script_inputs_match_with が静的に縛り、Archon の配線は
    dev/check.sh の模擬実行が見る。ここは線の順と盤面の約束（境の節が次を決め、関所の答えと止め札が盤面へ届き、報告が結末を
    出す）を見る。start へ渡す入力の鍵は LINE_ORDER の start の with から導く（既定は空。adapter だけ optional——この器は
    包みを通さずに回す）。呼び手の inputs はその上に重ねる。役の返答は replies[役]、役が作業ツリーに当てる変更は edits[役]（repo を受ける関数）、関所の答えは
    gates[関所]（無ければ continue・空の一言）、stop_at の境の節の前に止め札を置く。sessions なら start の後に包みの家へ
    判定役の会話の id と起動の行を置く（再審の役が判定役の会話を継げる run。無ければ包みを通らない run と同じ）"""

    def __init__(self, tmp, *, replies, gates=None, inputs=None, stop_at=None, edits=None, sessions=False):
        import entry  # noqa: F401  （.shared/core は頭で sys.path に足してある）
        self.tmp = pathlib.Path(tmp)
        self.replies, self.gates, self.edits = replies, gates or {}, edits or {}
        start_with = next(r for r in LINE_ORDER if r["id"] == "start")["with"]
        self.inputs = {**{k: "" for k in start_with if k != "request"}, "adapter": "optional", **(inputs or {})}
        self.stop_at = stop_at
        self.sessions = sessions
        self.repo = seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True, exist_ok=True)
        req.write_text((SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.request = req
        self.board = self.tmp / "art" / "board"
        self.out, self.trail = {}, []
        self.eyes_roles = []   # blk-eyes が起こした目の役（起こした順）
        self.judge_brief = None   # blk-judge の支度（judge-brief）の出口
        self.judge_takes = []     # blk-judge の受け付け（judge-accept）の返り（回した順）
        self.mat_roles = []    # blk-material が起こした役（起こした順）
        self.rejudge_roles = []   # blk-rejudge が起こした役（起こした順）

    # -- 盤面の口
    def take(self, nid, reply):
        import entry
        b = entry.open_board(self.board)
        inst = next(i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending")
        b.mark_launched(nid, inst.get("attempts", 1))
        got = entry.take(self.board, nid, reply, self.repo)
        if not got["ok"]:
            raise AssertionError(f"{nid} の見本を盤面が受けない: {got['reason']}")
        return got

    def _file(self, name, doc):
        p = self.tmp / "exits" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def _edit(self, role):
        if role in self.edits:
            self.edits[role](self.repo)

    # -- ブロック（出口の形は各ブロックの collect と同じ欄。中の節の分かれ道は盤面が決める）
    def blk_pr(self):
        import prcheck
        prcheck.snapshot(self.board, self.repo)
        got = prcheck.take(self.board, self.replies.get("pr-check", reply("pr_no_conflicts")), self.repo)
        if not got["ok"]:
            raise AssertionError(got["reason"])
        return prcheck.collect(self.board)

    def blk_premises(self):
        f = self._file("premises.json", self.replies.get("premises", {"constraints": []}))
        return {"ok": True, "constraints_file": f, "constraints_summary": ""}

    def blk_purpose(self):
        import purpose
        got = purpose.check_purpose(self.replies.get("purpose", reply("purpose_ok")), self.board, "", self.repo)
        if not got["ok"]:
            raise AssertionError(got["reason"])
        path, obj = purpose.read_purpose(self.board)
        return {"ok": True, "purpose_file": str(path), "purpose_text": obj["purpose_text"], "source": obj["source"]}

    def blk_eyes(self):
        """blk-eyes の中の節の順（入口 → 待っている目ごとに支度・受け付け → 出口）。目の返答は replies[<役>]（無ければ
        test_blk_eyes の見本）"""
        import entry
        if str(ROOT / "blk-eyes" / "lib") not in sys.path:
            sys.path.insert(0, str(ROOT / "blk-eyes" / "lib"))
        import eyes
        import test_blk_eyes as TB
        e = eyes.enter(self.board, self.repo)
        while True:
            b = entry.open_board(self.board, allow_halted=True)
            todo = [r for r, n in eyes.NODE_OF.items() if eyes._pending(b, n)]
            if not todo or eyes._stopped(b):
                break
            for role in todo:
                eyes.prep(self.board, role, e["round"], self.repo)
                got = eyes.accept(self.board, role, json.dumps(self.replies.get(role, TB.REPLY[role]), ensure_ascii=False),
                                  self.repo)
                if not got["ok"]:
                    raise AssertionError(f"{role}: {got.get('reason')}")
            self.eyes_roles += todo
        return eyes.collect(self.board, e["round"])

    def blk_report(self):
        """blk-report の中の節の順（経路 → 支度 → 役 → 受け付け を 3 役 → 出口）。返答は replies[<役>]（無ければ blk-report の
        筋書き pass の見本）。replies["report-give-up"] が真なら書き手を 3 回拒ませる（諦めの道）"""
        import yaml
        if str(ROOT / "blk-report" / "lib") not in sys.path:
            sys.path.insert(0, str(ROOT / "blk-report" / "lib"))
        import report_roles
        stubs = yaml.safe_load((ROOT / "blk-report" / "fixtures" / "pass.stubs.yaml").read_text(encoding="utf-8"))
        machine = self.out["report"]["report_file"]
        for role in report_roles.ROLES:
            if report_roles.route(self.board, role)["next"] != role:
                break
            for _ in range(report_roles.GIVE_UP_AFTER):
                report_roles.prep(self.board, role, self.repo, machine)
                body = self.replies.get(role, stubs[role])
                if role == report_roles.WRITE and self.replies.get("report-give-up"):
                    body = {"text": "| 列 |\n|---|\n| これは説明の文。セルに入れてはいけない |"}
                got = report_roles.accept(self.board, role, json.dumps(body, ensure_ascii=False), self.repo)
                if got["done"]:
                    break
        return report_roles.collect(self.board, machine)

    def blk_material(self):
        """blk-material の中の節の順（経路 → 待っている役ごとに支度・受け付け → 出口）。返答は replies[<節>]（無ければ
        test_blk_material の見本）"""
        if str(ROOT / "blk-material" / "lib") not in sys.path:
            sys.path.insert(0, str(ROOT / "blk-material" / "lib"))
        import material
        import test_blk_material as TM
        adapter = self.out["start"]["adapter"]
        r = material.route(self.board, self.repo, adapter)
        for role, nid in material.ROLES.items():
            if not r.get(material.route_key(role)):
                continue
            material.prep(self.board, role, self.repo, self.out["h-mat"]["purpose_file"])
            default = reply("purpose_review_ok") if nid == "p0.purpose_review" else TM.good_reply(nid)
            got = material.take(self.board, role, self.replies.get(nid, default),
                                self.repo, adapter)
            if not got["ok"]:
                raise AssertionError(f"{role}: {got.get('reason')}")
            self.mat_roles.append(role)
        return material.collect(self.board)

    def blk_judge(self):
        """blk-judge の中の節の順（支度 judge-brief → 判定役と受け付け judge-accept の輪 → 出口 collect）を本物の口で回す。
        判定役の返答は replies["judge"]（1 つか、回ごとの返答の列。列が尽きたら最後の物を繰り返す）。輪は受け付けの done で
        抜ける（R50）。受け付けの返りは judge_takes に積む"""
        if str(ROOT / "blk-judge" / "lib") not in sys.path:
            sys.path.insert(0, str(ROOT / "blk-judge" / "lib"))
        import judgebrief
        import judgetake
        self.judge_brief = judgebrief.brief(self.board, self.repo)
        if not self.judge_brief["go"]:   # 止まった盤面: 判定役の輪は when: で飛ぶ
            return judgetake.collect(self.board)
        bodies = self.replies["judge"] if isinstance(self.replies["judge"], list) else [self.replies["judge"]]
        for i in range(judgetake.GIVE_UP_AFTER):
            body = bodies[min(i, len(bodies) - 1)]
            got = judgetake.accept(self.board, json.dumps(body, ensure_ascii=False), self.repo)
            self.judge_takes.append(got)
            if got["done"]:
                break
        return judgetake.collect(self.board)

    def blk_plan(self):
        """blk-plan の中の節の順（独立設計の輪 → 修正案 → 事前審査）。独立設計は core の design の口で盤面の根に控える（返答は
        replies["r2-design"]、無ければ design_ok）。修正案が待たない周（直す物の無い判定）は設計だけを作る"""
        import design
        import entry
        if design.snap(self.board, self.repo)["go"]:
            design.prep(self.board, self.repo)
            got = design.accept_reply(self.board, json.dumps(self.replies.get("r2-design", reply("design_ok")),
                                                             ensure_ascii=False), self.repo)
            if not got["ok"]:
                raise AssertionError(f"r2-design: {got['reason']}")
        b = entry.open_board(self.board)
        if b.node_state("p2.fix_plan") == "na":
            return {"ok": True, "plan_file": "", "asks_human": False}
        self.take("p2.fix_plan", self.replies["plan"])
        got = self.take("p2.plan_review", self.replies["plan-review"])
        b = entry.open_board(self.board)
        return {"ok": True, "plan_file": str(b.dir / b.state["outputs"]["p2.fix_plan"]["file"]), "asks_human": got["asking"]}

    def blk_fix(self):
        self._edit("fix")
        self.take("p3.fix", self.replies["fix"])
        return {"ok": True, "files": ["stats.py"], "changes_file": "", "removed": []}

    def blk_rejudge(self):
        """blk-rejudge の中の節の順（rj-snap → 段ごとに経路 rj-route<k> → 支度・役・受け付けの輪 → 出口 collect）を本物の口で回す。
        役の返答は replies[<役>]（無ければ盤面の今の単位をそのまま返して異議を退ける見本）。輪は受け付けの done で抜ける（R50）"""
        import entry
        import rejudge
        rejudge.snap(self.board, self.repo)
        for _ in rejudge.passes():
            r = rejudge.route(self.board, self.repo)
            if not r["next"]:
                continue
            for _ in range(rejudge.GIVE_UP_AFTER):
                rejudge.prep(self.board, r["next"], self.repo)
                units = entry.open_board(self.board).record.get("units") or []
                body = self.replies.get(r["next"]) or {
                    "verdict": "退ける", "new_facts": "修正役の異議の文を読み、作業ツリーの stats.py で判定の単位の読みを確かめ直した",
                    "units": [{k: u[k] for k in ("key", "label", "disposition", "reason") if k in u} for u in units]}
                if rejudge.take(self.board, r["node"], body, self.repo)["done"]:
                    break
            self.rejudge_roles.append(r["next"])
        return rejudge.collect(self.board)

    def blk_delta(self):
        import refix
        assert refix.cut(self.board, 1, self.repo)["ok"]
        got = refix.accept_review(self.replies["review"], self.board, "", self.repo, n=1)
        if not got["ok"]:
            raise AssertionError(got["reason"])
        return refix.collect_delta(self.board)

    def blk_refix(self):
        import refix
        for n, role, review in ((1, "refix", None), (2, "refix2", "review2")):
            if review:
                r = refix.route(self.board)
                if not r["review2"]:
                    break
                assert refix.cut(self.board, 2, self.repo)["ok"]
                got = refix.accept_review(self.replies[review], self.board, "", self.repo, n=2)
                if not got["ok"]:
                    raise AssertionError(got["reason"])
                if not refix.route(self.board)["refix2"]:
                    break
            assert refix.prep_fix(self.board, n, self.repo)["ok"]
            self._edit(role)
            got = refix.accept_fix(self.replies[role], self.board, "", self.repo, n=n)
            if not got["ok"]:
                raise AssertionError(got["reason"])
        return refix.collect_refix(self.board)

    def blk_tests(self):
        import entry
        b = entry.open_board(self.board)
        ci = entry.run_ci(b, "p4.ci", test_cmd=self.out["start"]["test_cmd"])
        b.settle()
        b = entry.open_board(self.board, allow_halted=True)
        mat = ((b.record.get("materials") or {}).get("local_checks") or {})
        return {"ok": True, "green": mat.get("status") == "clean", "log": ci["log"], "suites": [], "by": ci["by"]}

    # -- 線
    def _src(self, v):
        """with: の出どころを値に（{from, if_skipped} は走らなかった節で None。文字列 null も None）"""
        if isinstance(v, dict):
            nid = v["from"].split(".")[0].lstrip("$")
            return self.out.get(nid, v.get("if_skipped"))
        return None if v == "null" else v

    def _when(self, row) -> bool:
        w = row.get("when")
        if not w:
            return True
        ref, _, want = w.partition(" == ")
        nid, _, field = ref.lstrip("$").partition(".output.")
        return nid in self.out and self.out[nid].get(field) is (want == "true")

    def run(self):
        import entry
        import halt
        import line_edge
        import report
        blocks = {"blk-pr": self.blk_pr, "blk-premises": self.blk_premises, "blk-purpose": self.blk_purpose,
                  "blk-judge": self.blk_judge, "blk-plan": self.blk_plan, "blk-fix": self.blk_fix, "blk-delta": self.blk_delta,
                  "blk-refix": self.blk_refix, "blk-tests": self.blk_tests, "blk-eyes": self.blk_eyes,
                  "blk-report": self.blk_report, "blk-material": self.blk_material, "blk-rejudge": self.blk_rejudge}
        for row in LINE_ORDER:
            nid = row["id"]
            if nid == "launch":
                self.trail.append(nid)
            elif nid == "start":
                raw = {"request": str(self.request), **self.inputs}
                self.out[nid] = entry.start(self.board, self.repo, raw, run_id=RUN_ID)
                self.trail.append(nid)
                if self.sessions:
                    import rejudgekit
                    rejudgekit.put_session(self.repo)
            elif row.get("script") == "edge":
                if self.stop_at == nid:
                    halt.place(self.board, "止め札の試し", "test")
                kw = {k: self._src(row["with"][k]) for k in ("judged", "premised", "gate", "tests")}
                self.out[nid] = line_edge.edge(self.board, row["at"], self.repo, run_id=RUN_ID,
                                               adapter_mode=self.out["start"]["adapter"],
                                               final_gate=self.inputs["final_gate"], **kw)
                self.trail.append(nid)
            elif row["kind"] == "approval":
                if self._when(row):
                    self.out[nid] = self.gates.get(nid) or {"decision": "continue", "text": ""}
                    self.trail.append(nid)
            elif row["kind"] == "include":
                if not self._when(row):
                    continue
                if row["block"] not in blocks:
                    raise AssertionError(f"LineRun は {row['block']} を回せない（{nid}）")
                self.out[nid] = blocks[row["block"]]()
                self.trail.append(nid)
            elif nid == "report":
                w = row["with"]
                self.out[nid] = report.build(self.board.resolve(), judged=self._src(w["judged"]), tests=self._src(w["tests"]),
                                             start=self._src(w["start"]), mid=self._src(w["mid"]), ci=self._src(w["ci"]),
                                             run_id=RUN_ID, events=[])
                self.trail.append(nid)
            elif nid == "result":
                self.out[nid] = report.final_result(self.out["report"], self.out.get("reporting"))
                self.trail.append(nid)
        rep = self.out["result"]
        return {"outcome": rep["outcome"], "report": rep, "board_dir": self.board, "trail": self.trail, "out": self.out,
                "eyes_roles": self.eyes_roles, "mat_roles": self.mat_roles, "judge_brief": self.judge_brief,
                "judge_takes": self.judge_takes, "rejudge_roles": self.rejudge_roles}


def run_line(tmp, *, replies, gates=None, inputs=None, stop_at=None, edits=None, sessions=False) -> dict:
    """LineRun(...).run()。返り {outcome, report, board_dir, trail, out, eyes_roles, mat_roles, judge_brief, judge_takes,
    rejudge_roles}"""
    return LineRun(tmp, replies=replies, gates=gates, inputs=inputs, stop_at=stop_at, edits=edits, sessions=sessions).run()
