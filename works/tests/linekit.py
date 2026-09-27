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
    return {**os.environ, **fixed}


def git(repo, *args) -> str:
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True,
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


CLAUDE_TMP = ("/private/tmp/claude-", "/tmp/claude-")   # Claude Code の一時フォルダ（dev/guard.sh と同じ決まり）


def work_home() -> pathlib.Path:
    """${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/single/（作って返す）。Claude Code の一時フォルダの下に解決される置き場は、
    作る前に BoardGap で拒む（サンドボックスの Bash が書ける所に使い捨ての物を置かない）"""
    from board import BoardGap   # 盤面の層の誤りの型（.shared/core を sys.path に足してある）
    base = os.environ.get("WORKS_DEV_HOME") or str(pathlib.Path.home() / ".cache" / "works-dev")
    home = pathlib.Path(base) / "single"
    for p in (str(home), str(home.resolve())):
        if p.startswith(CLAUDE_TMP):
            raise BoardGap(f"work_home: {home} が Claude Code の一時フォルダの下にある（{home.resolve()}）。WORKS_DEV_HOME を別の場所にする")
    home.mkdir(parents=True, exist_ok=True)
    return home


# ---------------------------------------------------------------- 線の節の並び（P1 計画 Task 28・〔線A計〕T16。C18 の順）
# darkfactory.yaml はこの並びと同じに書き、tests/test_line.py の test_line_order_matches_linekit が YAML と突き合わせる
# （手で 2 か所に書き写したまま放さない。裁定 TA16）。行は {id, kind: script|include|approval, script?, block?, at?,
# depends_on, trigger_rule?, when?, with: {鍵: 出どころ}}。境の節（script edge）は edge.py の INPUTS を全部受け、使わない物は "null"。
NFMOS = "none_failed_min_one_success"
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
     "with": {"request": "$INPUTS.request", "test_cmd": "$INPUTS.test_cmd", "thickness": "$INPUTS.thickness",
              "gates": "$INPUTS.gates", "final_gate": "$INPUTS.final_gate", "adapter": "$INPUTS.adapter",
              "policy_md": "$INPUTS.policy_md"}},
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
    {"id": "judging", "kind": "include", "block": "blk-judge", "depends_on": ["h-judge"],
     "when": "$h-judge.output.go == true",
     "with": {"request": "$INPUTS.request", "base_rev": "$start.output.base_rev",
              "policy_paste": "$start.output.policy_paste", "premises_file": "$h-judge.output.premises_file"}},
    _edge("h-plan", "plan", ["start", "h-judge", "judging"], judged=_skippable("$judging.output")),
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
    _edge("h-mid", "mid", ["start", "h-fix", "fixing"]),
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
    _edge("h-final", "final", ["start", "h-tests", "testing"], tests=_skippable("$testing.output")),
    {"id": "final-gate", "kind": "approval", "depends_on": ["h-final"], "when": "$h-final.output.ask == true",
     "decisions": ["approve", "continue", "stop", "reject"]},
    _edge("h-eyes", "eyes", ["start", "h-final", "final-gate"], gate=_skippable("$final-gate.output")),
    {"id": "report", "kind": "script", "script": "report", "depends_on": ["start", "h-eyes"], "trigger_rule": NFMOS,
     "with": {"judged": _skippable("$judging.output"), "tests": _skippable("$testing.output"),
              "start": {"from": "$start.output"}, "mid": {"from": "$h-mid.output"},
              "ci": _skippable("$ci-checking.output")}},
]


# ---------------------------------------------------------------- 線を Archon 無しで通す（P1 計画 Task 28・〔線A計〕T16）
RUN_ID = "run-line-a"
GATES = frozenset(r["id"] for r in LINE_ORDER if r["kind"] == "approval" and r.get("decisions"))


class LineRun:
    """LINE_ORDER の順に、境の節（line_edge.edge）・ブロックの口（受け付け・支度・出口の関数）・関所の答えを本物の盤面の上で回す。
    Archon の置き換え（with: → INPUTS_*）は tests/test_line.py の test_script_inputs_match_with が静的に縛り、Archon の配線は
    dev/check.sh の模擬実行が見る。ここは線の順と盤面の約束（境の節が次を決め、関所の答えと止め札が盤面へ届き、報告が結末を
    出す）を見る。役の返答は replies[役]、役が作業ツリーに当てる変更は edits[役]（repo を受ける関数）、関所の答えは
    gates[関所]（無ければ continue・空の一言）、stop_at の境の節の前に止め札を置く"""

    def __init__(self, tmp, *, replies, gates=None, inputs=None, stop_at=None, edits=None):
        import entry  # noqa: F401  （.shared/core は頭で sys.path に足してある）
        self.tmp = pathlib.Path(tmp)
        self.replies, self.gates, self.edits = replies, gates or {}, edits or {}
        self.inputs = {"test_cmd": "", "thickness": "", "gates": "", "final_gate": "", "adapter": "optional", "policy_md": "",
                       **(inputs or {})}
        self.stop_at = stop_at
        self.repo = seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True, exist_ok=True)
        req.write_text((SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.request = req
        self.board = self.tmp / "art" / "board"
        self.out, self.trail = {}, []

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

    def blk_judge(self):
        body = self.replies["judge"]
        units = [u["key"] for u in body.get("units") or [] if u.get("label") != "info"]
        return {"ok": True, "open_units": units, "need_fix": bool(units), "judgment_file": self._file("judgment.json", body),
                "one_shot": body.get("one_shot", "")}

    def blk_plan(self):
        import entry
        self.take("p2.fix_plan", self.replies["plan"])
        got = self.take("p2.plan_review", self.replies["plan-review"])
        b = entry.open_board(self.board)
        return {"ok": True, "plan_file": str(b.dir / b.state["outputs"]["p2.fix_plan"]["file"]), "asks_human": got["asking"]}

    def blk_fix(self):
        self._edit("fix")
        self.take("p3.fix", self.replies["fix"])
        return {"ok": True, "files": ["stats.py"], "changes_file": "", "removed": []}

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
        blocks = {"blk-pr": self.blk_pr, "blk-premises": self.blk_premises, "blk-judge": self.blk_judge, "blk-plan": self.blk_plan,
                  "blk-fix": self.blk_fix, "blk-delta": self.blk_delta, "blk-refix": self.blk_refix, "blk-tests": self.blk_tests}
        for row in LINE_ORDER:
            nid = row["id"]
            if nid == "launch":
                self.trail.append(nid)
            elif nid == "start":
                raw = {"request": str(self.request), **self.inputs}
                self.out[nid] = entry.start(self.board, self.repo, raw, run_id=RUN_ID)
                self.trail.append(nid)
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
        rep = self.out["report"]
        return {"outcome": rep["outcome"], "report": rep, "board_dir": self.board, "trail": self.trail, "out": self.out}


def run_line(tmp, *, replies, gates=None, inputs=None, stop_at=None, edits=None) -> dict:
    """LineRun(...).run()。返り {outcome, report, board_dir, trail, out}"""
    return LineRun(tmp, replies=replies, gates=gates, inputs=inputs, stop_at=stop_at, edits=edits).run()
