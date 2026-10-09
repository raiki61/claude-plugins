"""線 A の試験の手助け（test_* でないので unittest の発見に拾われない）。

- seed_repo: dev/target-seed/ を写した使い捨ての git リポジトリ（初めの commit つき。名前と時刻は固定）
- reply:     tests/replies/<名>.json の役の返答の見本
- git_env:   名前と時刻を固定した git の環境
- github_crossing: 種の origin を GitHub の形にし、交差する PR を 1 件返す偽の gh を置く（並行 PR の任せ先の役の道を通す run）
- work_home: 使い捨ての物を置く家（${WORKS_RUN_PLACE:-${WORKS_DEV_HOME:-$HOME/.cache/works-dev}}/single/。Claude Code の一時フォルダの下に置かない）
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


def set_final_gate(board, mode: str) -> None:
    """入口が始めの記録に置いた最後の関所の開き方を mode に替える（境の節は入力で受けず、住処 gatepolicy で記録を読む）"""
    import gatepolicy
    import startrec
    path = startrec.path(board)
    doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    doc[gatepolicy.FINAL_KEY] = mode
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


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


GITHUB_ORIGIN = "git@github.com:o/r.git"


def github_crossing(repo, top) -> str:
    """repo の origin を GitHub の形（GITHUB_ORIGIN）にし、top/fake-gh/bin に偽の gh を置いて、その bin を頭に足した PATH の値を返す
    （呼び手が os.environ の PATH に置く）。偽の gh は pr list で番号 7 の PR を 1 件（head は誰の HEAD でもない版）、
    pr view でその cwd の追跡中のファイルの全部を返す——engine の並行 PR の helper は必ず交差を見て任せ先の役に落ちる。
    種（seed_repo）は remote を持たない（forge の無い run。並行 PR は機械が条件外にする）ので、役の道を試す run はこれを使う"""
    repo, top = pathlib.Path(repo), pathlib.Path(top) / "fake-gh"
    names = git(repo, "remote").split()
    git(repo, "remote", "set-url" if "origin" in names else "add", "origin", GITHUB_ORIGIN)
    (top / "bin").mkdir(parents=True, exist_ok=True)
    (top / "list.json").write_text(json.dumps([{"number": 7, "headRefName": "other", "headRefOid": "0" * 40}]),
                                   encoding="utf-8")
    gh = top / "bin" / "gh"
    gh.write_text("#!/bin/sh\n"
                  f'if [ "$1" = pr ] && [ "$2" = list ]; then cat "{top}/list.json"; exit 0; fi\n'
                  'if [ "$1" = pr ] && [ "$2" = view ]; then git ls-files; exit 0; fi\n'
                  'echo "fake gh: $*" >&2; exit 9\n', encoding="utf-8")
    gh.chmod(0o755)
    return f"{top / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"


def reply(name: str) -> dict:
    """tests/replies/<name>.json"""
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


TREE_CHECKED = "項目の案を stats.py と test_stats.py で読み、呼び出し元と試験の期待を確かめた"
TREE_NO_EFFECT = "直した後の値だけを断言していて期待は変わらない"


def tree_review(board, k: int = 1, synergy_why: str = "2 つの項目は stats.py の別の関数を直し、順番の依存も重複も無い") -> dict:
    """事前審査の束ね役の見本（線の木の段 1）: 往復 k の下請けのファイル（盤面の plan-review-items/pass-<k>/）が名指す答えの
    ファイルに、下請けの代わりに答えを書き（覆っていない当たりは全部 no_effect・faces は空・開けと言われた先行例の出典は
    在ると答える。相乗りの審査も穴なし）、項目ごとの
    判定の要約（全部 clean）を返す。当たりは節 review-ripple が盤面に置いた往復 k の波及の一覧から引く"""
    board = pathlib.Path(board)
    if str(ROOT / "blk-plan" / "lib") not in sys.path:
        sys.path.insert(0, str(ROOT / "blk-plan" / "lib"))
    import planblk
    doc = json.loads(max(board.rglob(f"ripple/pass-{k}.json")).read_text(encoding="utf-8"))
    hits = {it["item"]: it["uncovered"] for it in doc["items"]}
    rows = []
    for brief in sorted(board.rglob(f"plan-review-items/pass-{k}/*.md")):
        path = pathlib.Path(planblk.answer_in(brief.read_text(encoding="utf-8")))
        path.parent.mkdir(parents=True, exist_ok=True)
        if brief.stem == "synergy":
            body = {"why": synergy_why, "faces": []}
        else:
            n = int(brief.stem.split("-")[1])
            rows.append(n)
            body = {"item": n, "checked": TREE_CHECKED, "faces": [], "shrink": [], "resolved": [],
                    "hits": [{"id": h["id"], "answer": "no_effect", "why": TREE_NO_EFFECT} for h in hits.get(n, [])],
                    "precedents": [{"id": i, "found": True, "quote": "出典は在り、単位の問題に当たっている"}
                                   for i in planblk.fetch_ids(brief.read_text(encoding="utf-8"))]}
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return {"faces": [], "shrink": [], "reason": "項目ごとの下請けの答えのファイルを受け、項目ごとの判定をまとめた",
            "items": [{"item": n, "verdict": "clean", "blocks": []} for n in rows]}


VERIFY_EVIDENCE = "stats.py の該当の行を読み、判定の理由が言う式がそのまま在ることを確かめた"


def verify_answers(board) -> dict:
    """判定の裏取りの束ね役の見本（線の木の段 3）: 盤面の今の周の束ね役の指示書（verify/prompt.md）が名指す下請けのファイルごとに、
    下請けの代わりに答えのファイルを書き（単位は全部 root・証拠と場所は合う。相乗りは重複・関わり・順番なし）、要約を返す"""
    board = pathlib.Path(board)
    if str(ROOT / "blk-judge" / "lib") not in sys.path:
        sys.path.insert(0, str(ROOT / "blk-judge" / "lib"))
    import judgeverify
    prompt = max(board.rglob(f"{judgeverify.BRIEF_DIR}/prompt.md"), key=lambda p: p.stat().st_mtime)
    said = []
    for brief in sorted(prompt.parent.glob("*.md")):
        if brief.name == "prompt.md":
            continue
        path = pathlib.Path(judgeverify.answer_in(brief.read_text(encoding="utf-8")))
        path.parent.mkdir(parents=True, exist_ok=True)
        if brief.stem == "synergy":
            body = {"why": "単位は別の関数を直し、重複も順番の依存も無い", "duplicates": [], "relations": [], "order": []}
            said.append("相乗り: 重複 0・関わり 0・順番 0")
        else:
            n = int(brief.stem.split("-")[1])
            body = {"unit": n, "verdict": "root", "evidence_found": True, "evidence": VERIFY_EVIDENCE, "location_ok": True,
                    "location": "stats.py", "why": "その式を直せば試験の期待どおりの値になる"}
            said.append(f"単位 {n}: root")
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return {"summary": "・".join(said)}


def structure_eye_reply(structure_file) -> dict:
    """構造の目の見本の返答: structure.json の実測できた単位ごとに、根拠つきの汚れないの 1 行（単位の id は run ごとに決まる）"""
    doc = json.loads(pathlib.Path(structure_file).read_text(encoding="utf-8"))
    return {"rows": [{"unit_id": u["id"], "verdict": "汚れない", "faces": [], "evidence": [f"/units/{i}/measure"],
                      "reason": "足す形が増えない"} for i, u in enumerate(doc.get("units") or []) if u.get("status") == "measured"]}


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


LENS_DEF_BODY = "お前は黙った失敗を探す。握りつぶした例外・既定値で黙って続ける枝を挙げる。"
LENS_REPLY = {"findings": [], "findings_none": "stats.py の差分を読んだ。例外を握りつぶす枝も既定値で黙って続ける枝も無い"}


def lens_plugin(into) -> dict:
    """レンズの定義を引く置き場の偽物（pr-review-toolkit の agents/<レンズ>.md を置き、<PLUGIN>_ROOT で指す）。返りは env に重ねる値"""
    root = pathlib.Path(into) / "lens-plugin"
    (root / "agents").mkdir(parents=True, exist_ok=True)
    (root / "agents" / "silent-failure-hunter.md").write_text(
        f"---\nname: silent-failure-hunter\nmodel: inherit\n---\n\n{LENS_DEF_BODY}\n", encoding="utf-8")
    return {"PR_REVIEW_TOOLKIT_ROOT": str(root)}


RUN_PLACE_ENV = "WORKS_RUN_PLACE"   # 包みが Bash を持つ役の子に立てる名（adapter.RUN_PLACE_ENV。test_adapter が照合する）
CLAUDE_TMP = ("/private/tmp/claude-", "/tmp/claude-")   # Claude Code の一時フォルダ（dev/guard.sh と同じ決まり）


def work_home() -> pathlib.Path:
    """${WORKS_RUN_PLACE:-${WORKS_DEV_HOME:-$HOME/.cache/works-dev}}/single/ を解決した字で返す（作って返す）。WORKS_RUN_PLACE は
    包みが Bash を持つ役の子に立てる run ごとの書ける置き場で、在れば WORKS_DEV_HOME より先に見る（sandbox の役が書ける所へ向ける
    細い口）。盤面は解決した字を返すので、解決しない字（macOS の /var → /private/var）を配ると relative_to と文字列比較が割れる。
    Claude Code の一時フォルダの下に解決される置き場は、どちらの根でも作る前に BoardGap で拒む
    （サンドボックスの Bash が書ける所に使い捨ての物を置かない）"""
    from board import BoardGap   # 盤面の層の誤りの型（.shared/core を sys.path に足してある）
    name = RUN_PLACE_ENV if os.environ.get(RUN_PLACE_ENV) else "WORKS_DEV_HOME"
    base = os.environ.get(name) or str(pathlib.Path.home() / ".cache" / "works-dev")
    given = pathlib.Path(base) / "single"
    home = given.resolve()
    for p in (str(given), str(home)):
        if p.startswith(CLAUDE_TMP):
            raise BoardGap(f"work_home: {given} が Claude Code の一時フォルダの下にある（{home}）。{name} を別の場所にする")
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
EDGE_INPUTS = ("at", "judged", "premised", "gate", "tests", "adapter")


def _edge(nid, at, deps, **given):
    """境の節の行。edge.py の INPUTS を全部渡す（使わない物は文字列 null。A-T10a の持ち越し 1）"""
    w = {k: "null" for k in EDGE_INPUTS}
    w.update(at=at, adapter="$entering.output.adapter", **given)
    return {"id": nid, "kind": "script", "script": "edge", "at": at, "depends_on": deps, "trigger_rule": NFMOS, "with": w}


def _depth(nid, at, deps, **given):
    """深さの節の行（darkfactory/scripts/depth.py の INPUTS を全部渡す。使わない物は空か字の false）"""
    w = {"at": at, "open_units": "", "tdd_suite": "", "replanned": "false", "rejudged": "false"}
    w.update(given)
    return {"id": nid, "kind": "script", "script": "depth", "at": at, "depends_on": deps, "trigger_rule": NFMOS, "with": w}


def _skippable(src):
    return {"from": src, "if_skipped": None}


LINE_ORDER = [
    {"id": "entering", "kind": "include", "block": "blk-entry",
     "with": {"request": "$INPUTS.request", "base": "$INPUTS.base", "pr": "$INPUTS.pr", "test_cmd": "$INPUTS.test_cmd", "thickness": "$INPUTS.thickness",
              "gates": "$INPUTS.gates", "final_gate": "$INPUTS.final_gate", "adapter": "$INPUTS.adapter",
              "policy_md": "$INPUTS.policy_md", "lang": "$INPUTS.lang", "unattended": "$INPUTS.unattended",
              "design_only": "$INPUTS.design_only",
              "fix_fixture": "$INPUTS.fix_fixture", "features_off": "$INPUTS.features_off",
              "features_on": "$INPUTS.features_on", "launch_mark": "$INPUTS.launch_mark", "spec": "$INPUTS.spec"}},
    {"id": "ci-checking", "kind": "include", "block": "blk-ci", "depends_on": ["entering"],
     "when": "$entering.output.ci_role_go == true",
     "with": {"node": "p0.local_checks"}},
    _edge("h-entry", "entry", ["entering", "ci-checking"]),
    {"id": "speccing", "kind": "include", "block": "blk-spec", "depends_on": ["h-entry"],
     "when": "$h-entry.output.spec_go == true", "with": {"base_rev": "$entering.output.base_rev"}},
    _edge("h-spec", "spec", ["entering", "h-entry", "speccing"]),
    {"id": "pr-checking", "kind": "include", "block": "blk-pr", "depends_on": ["h-spec"],
     "when": "$h-spec.output.pr_go == true", "with": {}},
    {"id": "premising", "kind": "include", "block": "blk-premises", "depends_on": ["h-entry", "pr-checking"],
     "trigger_rule": NFMOS, "when": "$h-entry.output.premises_go == true",
     "with": {"request": "$INPUTS.request", "base_rev": "$entering.output.base_rev"}},
    _edge("h-judge", "judge", ["entering", "h-entry", "premising"], premised=_skippable("$premising.output")),
    {"id": "purposing", "kind": "include", "block": "blk-purpose", "depends_on": ["h-judge"],
     "when": "$h-judge.output.purpose_go == true",
     "with": {"request": "$INPUTS.request", "constraints_file": "$h-judge.output.premises_file",
              "base_rev": "$entering.output.base_rev", "pr_file": "$entering.output.pr_file"}},
    _edge("h-mat", "mat", ["entering", "h-judge", "purposing"]),
    {"id": "worlding", "kind": "include", "block": "blk-world", "depends_on": ["h-mat"],
     "when": "$h-mat.output.world_go == true",
     "with": {"request": "$INPUTS.request", "purpose_file": "$h-mat.output.world_purpose_file"}},
    {"id": "h-world", "kind": "script", "script": "world", "depends_on": ["h-mat", "worlding"], "trigger_rule": ALL_DONE,
     "with": {"worlded": _skippable("$worlding.output"),
              "world_go": {"from": "$h-mat.output.world_go", "if_skipped": False}}},
    {"id": "gathering", "kind": "include", "block": "blk-material", "depends_on": ["h-mat", "h-world"],
     "when": "$h-mat.output.mat_go == true",
     "with": {"adapter": "$entering.output.adapter"}},
    {"id": "judging", "kind": "include", "block": "blk-judge", "depends_on": ["h-mat", "gathering", "h-world"], "trigger_rule": NFMOS,
     "when": "$h-mat.output.go == true",
     "with": {"request": "$INPUTS.request", "base_rev": "$entering.output.base_rev",
              "policy_paste": "$entering.output.policy_paste", "premises_file": "$h-judge.output.premises_file",
              "verify": "$entering.output.judge_verify"}},
    _edge("h-plan", "plan", ["entering", "h-mat", "judging"], judged=_skippable("$judging.output")),
    {"id": "structuring", "kind": "include", "block": "blk-structure", "depends_on": ["h-plan"],
     "when": "$h-plan.output.go == true",
     "with": {"units": "$h-plan.output.structure_units_file", "policy_path": "$entering.output.policy_path"}},
    {"id": "h-structure", "kind": "script", "script": "structure", "depends_on": ["h-plan", "structuring"],
     "trigger_rule": ALL_DONE,
     "with": {"structured": _skippable("$structuring.output"),
              "plan_go": {"from": "$h-plan.output.go", "if_skipped": False}}},
    {"id": "planning", "kind": "include", "block": "blk-plan", "depends_on": ["h-plan", "h-structure"],
     "when": "$h-plan.output.go == true",
     "with": {"verify_file": "$h-plan.output.verify_file", "review_tree": "$entering.output.review_tree"}},
    _edge("h-gate", "gate", ["entering", "h-plan", "h-structure", "planning"]),
    {"id": "policy-gate", "kind": "approval", "depends_on": ["h-gate"], "when": "$h-gate.output.ask == true",
     "decisions": ["approve", "continue", "stop", "reject"]},
    _edge("h-fix", "fix", ["entering", "h-gate", "policy-gate"], gate=_skippable("$policy-gate.output")),
    # 単位ごとの深さ（計画 2026-10-06-variable-depth）: 修正の前に決め（h-depth）、修正の後に信号で上げる（h-redepth）。いつも走る
    _depth("h-depth", "decide", ["entering", "h-fix"], open_units="$h-fix.output.open_units", tdd_suite="$INPUTS.tdd_suite"),
    {"id": "fixing", "kind": "include", "block": "blk-fix", "depends_on": ["h-fix", "h-depth"],
     "when": "$h-fix.output.go == true",
     "with": {"judgment_file": "$h-fix.output.judgment_file", "open_units": "$h-fix.output.open_units",
              "plan_file": "$h-fix.output.plan_file", "notes_file": "$h-fix.output.notes_file",
              "base_rev": "$entering.output.base_rev", "policy_path": "$entering.output.policy_path",
              "tdd_suite": "$INPUTS.tdd_suite", "test_cmd": "$entering.output.test_cmd",
              "unit_depths": "$h-depth.output.unit_depths", "ripple_file": "$h-fix.output.ripple_file",
              "plan_session": "plan", "tdd_lanes": "$entering.output.tdd_lanes", "fix_lanes": "$entering.output.fix_lanes"}},
    # 同じ run の中の案の直し（依頼 226。1 run に 1 回）: blk-plan と blk-fix の 2 度目の include
    _edge("h-replan", "replan", ["entering", "h-fix", "fixing"]),
    {"id": "replanning", "kind": "include", "block": "blk-plan", "depends_on": ["h-replan"],
     "when": "$h-replan.output.go == true",
     "with": {"replan": "true", "review_tree": "$entering.output.review_tree"}},
    _edge("h-regate", "regate", ["entering", "h-replan", "replanning"]),
    {"id": "replan-gate", "kind": "approval", "depends_on": ["h-regate"], "when": "$h-regate.output.ask == true",
     "decisions": ["approve", "continue", "stop", "reject"]},
    _edge("h-refit", "refit", ["entering", "h-regate", "replan-gate"], gate=_skippable("$replan-gate.output")),
    {"id": "refitting", "kind": "include", "block": "blk-fix", "depends_on": ["h-refit"],
     "when": "$h-refit.output.go == true",
     "with": {"judgment_file": "$h-refit.output.judgment_file", "open_units": "$h-refit.output.open_units",
              "plan_file": "$h-refit.output.plan_file", "notes_file": "$h-refit.output.notes_file",
              "base_rev": "$entering.output.base_rev", "policy_path": "$entering.output.policy_path",
              "tdd_suite": "$INPUTS.tdd_suite", "test_cmd": "$entering.output.test_cmd",
              "ripple_file": "$h-refit.output.ripple_file", "plan_session": "plan",
              "tdd_lanes": "$entering.output.tdd_lanes", "fix_lanes": "$entering.output.fix_lanes"}},
    _edge("h-rejudge", "rejudge", ["entering", "h-fix", "fixing", "h-refit", "refitting"]),
    {"id": "rejudging", "kind": "include", "block": "blk-rejudge", "depends_on": ["h-rejudge"],
     "when": "$h-rejudge.output.go == true",
     "with": {}},
    _depth("h-redepth", "raise", ["entering", "h-rejudge", "rejudging", "h-depth"],
           replanned={"from": "$h-replan.output.go", "if_skipped": False},
           rejudged={"from": "$h-rejudge.output.go", "if_skipped": False}),
    _edge("h-review", "review", ["entering", "h-rejudge", "rejudging", "h-redepth"]),
    {"id": "lensing", "kind": "include", "block": "blk-lens", "depends_on": ["h-review"],
     "when": "$h-review.output.go == true", "with": {}},
    {"id": "reviewing", "kind": "include", "block": "blk-delta", "depends_on": ["h-review", "lensing"], "trigger_rule": NFMOS,
     "when": "$h-review.output.go == true", "with": {"base_rev": "$entering.output.base_rev"}},
    _edge("h-refix", "refix", ["entering", "h-review", "reviewing"]),
    {"id": "refixing", "kind": "include", "block": "blk-refix", "depends_on": ["h-refix"],
     "when": "$h-refix.output.go == true",
     "with": {"base_rev": "$entering.output.base_rev", "policy_paste": "$entering.output.policy_paste",
              "policy_path": "$entering.output.policy_path"}},
    _edge("h-tests", "tests", ["entering", "h-refix", "refixing"]),
    {"id": "testing", "kind": "include", "block": "blk-tests", "depends_on": ["h-tests"],
     "when": "$h-tests.output.go == true", "with": {"cmd": "$entering.output.test_cmd"}},
    # 最後のテストが任せ先に落ちた（test_cmd も宣言も無い）時だけ、任せ先の CI の役のブロックが p4.ci を渡す
    _edge("h-ci", "ci", ["entering", "h-tests", "testing"]),
    {"id": "ci-final", "kind": "include", "block": "blk-ci", "depends_on": ["h-ci"], "when": "$h-ci.output.go == true",
     "with": {"node": "p4.ci"}},
    # 直しの後の実測（構造のブロックの 2 度目の include。計画 2026-10-09-clean-whole の Task 2.5）と、その境の節（控えを書く）
    {"id": "measuring-after", "kind": "include", "block": "blk-structure", "depends_on": ["h-ci", "ci-final"],
     "trigger_rule": NFMOS, "with": {"base_rev": "$entering.output.base_rev"}},
    {"id": "h-after", "kind": "script", "script": "after", "depends_on": ["h-ci", "measuring-after"], "trigger_rule": ALL_DONE,
     "with": {"measured": _skippable("$measuring-after.output")}},
    _edge("h-look", "look", ["entering", "h-tests", "testing", "h-ci", "ci-final", "h-after"]),
    {"id": "eyeing", "kind": "include", "block": "blk-eyes", "depends_on": ["h-look"], "when": "$h-look.output.go == true",
     "with": {"skip_optional": "$h-redepth.output.skip"}},
    _edge("h-final", "final", ["entering", "h-tests", "testing", "h-look", "eyeing"], tests=_skippable("$testing.output")),
    {"id": "final-gate", "kind": "approval", "depends_on": ["h-final"], "when": "$h-final.output.ask == true",
     "decisions": ["approve", "continue", "stop", "reject"]},
    _edge("h-eyes", "eyes", ["entering", "h-final", "final-gate"], gate=_skippable("$final-gate.output")),
    # 機械の報告は上流の節が落ちた run でも走る（all_done）。start のほかの出力は落ちても飛ばされても null で受ける
    {"id": "report", "kind": "script", "script": "report", "depends_on": ["entering", "h-eyes", "eyeing"],
     "trigger_rule": ALL_DONE,
     "with": {"judged": _skippable("$judging.output"), "tests": _skippable("$testing.output"),
              "start": {"from": "$entering.output"},
              "ci": _skippable("$ci-checking.output"), "eyes": _skippable("$h-eyes.output"),
              "eyeing": _skippable("$eyeing.output"), "cleaned_runs": "$INPUTS.cleaned_runs",
              "depth": _skippable("$h-redepth.output"),
              "fix_tdd": _skippable("$fixing.output.tdd"), "refit_tdd": _skippable("$refitting.output.tdd")}},
    {"id": "reporting", "kind": "include", "block": "blk-report", "depends_on": ["report"],
     "when": "$report.output.ai_report_go == true", "with": {"machine_report": "$report.output.report_file"}},
    # 出口（returns）。AI の報告のブロックが落ちても機械の報告で出口を出す（all_done: 前の節の成否に依らず走る）
    {"id": "result", "kind": "script", "script": "result", "depends_on": ["report", "reporting"], "trigger_rule": ALL_DONE,
     "with": {"machine": {"from": "$report.output"}, "ai": _skippable("$reporting.output")}},
]


# ---------------------------------------------------------------- 線を Archon 無しで通す（P1 計画 Task 28・〔線A計〕T16）
RUN_ID = "run-line-a"
# 同じブロックの 2 度目の include（依頼 226 の案の直し）。LineRun の筋書きは修正の段で fix_plan_item に裁かないので届かない
# （届けば赤）。中身は境の節と口の関数で test_replan.TestLineReplay が回す
SECOND_INCLUDES = {"replanning": "案の直し", "refitting": "2 回目の修正の段"}
GATES = frozenset(r["id"] for r in LINE_ORDER if r["kind"] == "approval" and r.get("decisions"))


class LineRun:
    """LINE_ORDER の順に、境の節（line_edge.edge）・ブロックの口（受け付け・支度・出口の関数）・関所の答えを本物の盤面の上で回す。
    Archon の置き換え（with: → INPUTS_*）は tests/test_line_inputs.py の test_script_inputs_match_with が静的に縛り、Archon の配線は
    dev/check.sh の模擬実行が見る。ここは線の順と盤面の約束（境の節が次を決め、関所の答えと止め札が盤面へ届き、報告が結末を
    出す）を見る。start へ渡す入力の鍵は LINE_ORDER の start の with から導く（既定は空。adapter だけ optional——この器は
    包みを通さずに回す）。呼び手の inputs はその上に重ねる。役の返答は replies[役]、役が作業ツリーに当てる変更は edits[役]（repo を受ける関数）、関所の答えは
    gates[関所]（無ければ continue・空の一言）、stop_at の境の節の前に止め札を置く。sessions なら start の後に包みの家へ
    判定役の会話の id と起動の行を置く（再審の役が判定役の会話を継げる run。無ければ包みを通らない run と同じ）。request は依頼の
    ファイルに書く中身（JSON の値。無ければ種の request_ok.json）。declared が偽なら種にテストの宣言を置かない（test_cmd も
    空なら CI の節が任せ先に落ち、任せ先の CI の役のブロック blk-ci が回る。役の返答は replies["ci"]、無ければ ci_found）"""

    def __init__(self, tmp, *, replies, gates=None, inputs=None, stop_at=None, edits=None, sessions=False, request=None,
                 github=False, declared=True):
        import entry  # noqa: F401  （.shared/core は頭で sys.path に足してある）
        self.tmp = pathlib.Path(tmp)
        self.replies, self.gates, self.edits = replies, gates or {}, edits or {}
        start_with = next(r for r in LINE_ORDER if r["id"] == "entering")["with"]
        self.inputs = {**{k: "" for k in start_with if k != "request"}, "adapter": "optional", **(inputs or {})}
        self.stop_at = stop_at
        self.sessions = sessions
        self.repo = seed_repo(self.tmp / "repo", declared=declared)
        self.row = None        # 回している線の行（include の with: を読むブロックの口が使う）
        self.ci_nodes = []     # blk-ci が渡した CI の節（回した順）
        # github なら origin を GitHub の形にして交差する偽の gh を置く（並行 PR の任せ先の役 blk-pr が回る run）。無ければ種は
        # remote を持たず forge の無い run（並行 PR は機械が条件外にし、blk-pr は回らない）
        self.path = github_crossing(self.repo, self.tmp) if github else None
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True, exist_ok=True)
        req.write_text((SEED / "request_ok.json").read_text(encoding="utf-8") if request is None
                       else json.dumps(request, ensure_ascii=False), encoding="utf-8")
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

    def blk_ci(self):
        """blk-ci の中の節の順（ci-fence → ci-snap → 支度・受け付けの輪 → 出口 collect）を ci_role の口で回す。節は線の行の
        with: の node。役の返答は replies["ci"]（無ければ ci_found の見本）"""
        import ci_role
        node = self.row["with"]["node"]
        fence = ci_role.fence(self.board, node, self.repo)
        if fence["go"]:
            ci_role.snapshot(self.board, node, self.repo)
            for _ in range(ci_role.GIVE_UP_AFTER):
                ci_role.prep(self.board, node, self.repo)
                if ci_role.take(self.board, node, self.replies.get("ci", reply("ci_found")), self.repo,
                                fence["adapter"])["done"]:
                    break
        self.ci_nodes.append(node)
        return ci_role.collect(self.board, node, fence["adapter"])

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
        skip = (self.out.get("h-redepth") or {}).get("skip") or ""
        while True:
            b = entry.open_board(self.board, allow_halted=True)
            todo = [r for r, n in eyes.NODE_OF.items() if eyes._pending(b, n)]
            if not todo or eyes._stopped(b):
                break
            todo = [r for r in todo if eyes.route(self.board, r, e["round"], skip=skip)["go"]]
            for role in todo:
                eyes.prep(self.board, role, e["round"], self.repo)
                got = eyes.accept(self.board, role, json.dumps(self.replies.get(role, TB.REPLY[role]), ensure_ascii=False),
                                  self.repo)
                if not got["ok"]:
                    raise AssertionError(f"{role}: {got.get('reason')}")
            self.eyes_roles += todo
        return eyes.collect(self.board, e["round"])

    def blk_report(self):
        """blk-report の中の節の順（経路 → 支度 → 書き手 → 受け付け（書き手の頭を読んだ初見の読み手の返答つき）→ 出口）。返答は
        replies[<役>]（無ければ blk-report の筋書き pass の見本）。replies["report-give-up"] が真なら書き手を 3 回拒ませる（諦めの道）"""
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
                got = report_roles.accept(self.board, role, json.dumps(body, ensure_ascii=False), self.repo,
                                          cold=json.dumps(self.replies.get(report_roles.WRITE_COLD, stubs[report_roles.WRITE_COLD])))
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
        adapter = self.out["entering"]["adapter"]
        r = material.route(self.board, self.repo, adapter)
        for role, nid in material.ROLES.items():
            if not r.get(material.route_key(role)):
                continue
            material.prep(self.board, role, self.repo)
            default = reply("purpose_review_ok") if nid == "p0.purpose_review" else TM.good_reply(nid)
            got = material.take(self.board, role, self.replies.get(nid, default),
                                self.repo, adapter)
            if not got["ok"]:
                raise AssertionError(f"{role}: {got.get('reason')}")
            self.mat_roles.append(role)
        return material.collect(self.board)

    def blk_judge(self):
        """blk-judge の中の節の順（支度 judge-brief → 判定役と受け付け judge-accept の輪 → 裏取りの支度・束ね役・まとめ → 出口 collect）を本物の口で回す。
        判定役の返答は replies["judge"]（1 つか、回ごとの返答の列。列が尽きたら最後の物を繰り返す）。輪は受け付けの done で
        抜ける（R50）。受け付けの返りは judge_takes に積む"""
        if str(ROOT / "blk-judge" / "lib") not in sys.path:
            sys.path.insert(0, str(ROOT / "blk-judge" / "lib"))
        import judgebrief
        import judgetake
        import judgeverify
        self.judge_brief = judgebrief.brief(self.board, self.repo)
        if self.judge_brief["go"]:   # 止まった盤面: 判定役の輪は when: で飛ぶ
            bodies = self.replies["judge"] if isinstance(self.replies["judge"], list) else [self.replies["judge"]]
            for i in range(judgetake.GIVE_UP_AFTER):
                body = bodies[min(i, len(bodies) - 1)]
                got = judgetake.accept(self.board, json.dumps(body, ensure_ascii=False), self.repo)
                self.judge_takes.append(got)
                if got["done"]:
                    break
        # 判定の根を開く（線の木の段 3）: 支度 → go なら束ね役（replies["judge-verify"]（盤面を受ける関数）か見本 verify_answers）→ まとめ
        # 線は裏取りの切り替えに start の出口の judge_verify（既定で off。入力 features_on・features_off）を渡す
        if judgeverify.prep(self.board, self.repo, verify=(self.out.get("entering") or {}).get("judge_verify", ""))["go"]:
            answer = self.replies.get("judge-verify", verify_answers)
            if callable(answer):
                answer(self.board)   # 下請けの代わりに答えのファイルを書く（束ね役の要約はまとめが読まない）
            judgeverify.merge(self.board, self.repo)
        return judgetake.collect(self.board)

    def _nth(self, role, k):
        """役の k 番目（0 から）の返答。replies[役] は 1 つか列で、列が尽きたら最後の物を繰り返す（blk_judge と同じ読み方）"""
        got = self.replies[role]
        return got[min(k, len(got) - 1)] if isinstance(got, list) else got

    def _revise_body(self) -> dict:
        """直しの役の既定の返答: 修正案の見本に、返された block の key ごとの disputed の答えを足した物"""
        import converge
        import entry
        held = converge.held(entry.open_board(self.board)) or {}
        return {**self._nth("plan", 0), converge.ANSWERS: [
            {"key": k, "handled": "disputed", "how": "案のままで穴にならない（見本の直しの役は異を唱える）"}
            for k in held.get("blocks") or []]}

    def _plan_role(self, role, body) -> None:
        """blk-plan の役の輪 1 つ（snap → go なら支度・受け付けを done まで。輪は受け付けの done で抜ける。R50）。返答は body()"""
        import planblk
        if not planblk.snap(self.board, role, self.repo)["go"]:
            return
        for _ in range(planblk.GIVE_UP_AFTER):
            # 線は修正案のブロックの支度に h-plan の verify_file（判定の単位の裏取りの申し送り。線の木の段 3）を渡す
            # 事前審査の木の切り替えは start の出口の review_tree（既定で auto。入力 features_on・features_off）
            planblk.prep(self.board, role, self.repo, verify_file=(self.out.get("h-plan") or {}).get("verify_file", ""),
                         review_tree=(self.out.get("entering") or {}).get("review_tree", ""))
            if planblk.accept_reply(self.board, role, json.dumps(body(), ensure_ascii=False), self.repo)["done"]:
                return

    def blk_plan(self):
        """blk-plan の中の節の順（独立設計の輪 → 波及の一覧 → 修正案の輪 → 壁打ちの輪 converge-loop〔直しの役の輪 → 波及の一覧 →
        事前審査の輪 → converge-check〕→ 出口 collect）を planblk の支度と受け付けの口で回す。独立設計は core の design の口で盤面の根に控える
        （返答は replies["r2-design"]、無ければ design_ok）。事前審査の返答は replies["plan-review"]（1 つか往復ごとの列）、直しの
        役は replies["plan-revise"]（同じ。無ければ _revise_body）。壁打ちの輪は converge-check の done で抜ける。
        修正案が待たない周（直す物の無い判定）は設計だけを作る"""
        if str(ROOT / "blk-plan" / "lib") not in sys.path:
            sys.path.insert(0, str(ROOT / "blk-plan" / "lib"))
        import design
        import planblk
        if design.snap(self.board, self.repo)["go"]:
            design.prep(self.board, self.repo)
            got = design.accept_reply(self.board, json.dumps(self.replies.get("r2-design", reply("design_ok")),
                                                             ensure_ascii=False), self.repo)
            if not got["ok"]:
                raise AssertionError(f"r2-design: {got['reason']}")
        import entry
        if planblk._pending(entry.open_board(self.board), "p2.fix_plan"):   # 節 plan-ripple（when は plan-snap の go）
            planblk.make_ripple(self.board, self.repo, "units")
        self._plan_role("plan", lambda: self._nth("plan", 0))
        for k in range(planblk.GIVE_UP_AFTER):   # converge-loop の max_iterations（tests/test_blk_plan.py が YAML と突き合わせる）
            # 直しの役は 2 往復目から（1 往復目は snap が go 偽）。k 番目の往復の直しは replies["plan-revise"] の k-1 番目
            self._plan_role(planblk.REVISE_ROLE, lambda: self._nth("plan-revise", k - 1) if "plan-revise" in self.replies
                            else self._revise_body())
            planblk.make_ripple(self.board, self.repo, "items")   # 節 review-ripple（往復ごとの事前審査の前）
            self._plan_role("plan-review", lambda: self._nth("plan-review", k))
            if planblk.converge_check(self.board)["done"]:
                break
        return planblk.collect(self.board)

    def blk_structure(self):
        """blk-structure の節の順（stage-a → 目を起こす周なら eye_prep・目の返答・eye_accept → collect）。本物のスクリプトを子の
        プロセスで回す（ARTIFACTS_DIR は盤面の置き場の親。cwd は対象）。目の返答は replies["structure-eye"] か、実測できた単位
        ごとの汚れないの 1 行（structure_eye_reply）"""
        after = "base_rev" in (self.row.get("with") or {})   # 直しの後の 2 度目の include（段 B だけ）
        env = hermetic.child_env(ARTIFACTS_DIR=str(self.board.parent), PYTHONDONTWRITEBYTECODE="1",
                                 INPUTS_UNITS="" if after else self.out["h-plan"]["structure_units_file"], INPUTS_ROOT="",
                                 INPUTS_POLICY_PATH="" if after else self.out["entering"].get("policy_path") or "",
                                 INPUTS_BASE_REV=self.out["entering"].get("base_rev") or "" if after else "")

        def run(script, **inputs):
            p = subprocess.run([sys.executable, str(ROOT / "blk-structure" / "scripts" / f"{script}.py")], cwd=str(self.repo),
                               env={**env, **{f"INPUTS_{k.upper()}": v for k, v in inputs.items()}},
                               capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
            if p.returncode != 0:
                raise AssertionError(f"blk-structure {script}: {p.stderr}")
            return json.loads(p.stdout)
        a = run("stage_a")
        files = {"structure_file": a["structure_file"], "design_file": a["design_file"]}
        eye = "null"
        if a["eye"]:
            run("eye_prep", structure_file=a["structure_file"])
            reply = (self.replies or {}).get("structure-eye") or structure_eye_reply(a["structure_file"])
            eye = json.dumps(run("eye_accept", **files, reply=json.dumps(reply, ensure_ascii=False)), ensure_ascii=False)
        b = json.dumps(run("stage_b"), ensure_ascii=False) if a["after"] else "null"
        return run("collect", **files, eye_due=json.dumps(a["eye"]), eye=eye, after_due=json.dumps(a["after"]), after=b)

    def blk_world(self):
        """blk-world の出口（collect の形）。行は replies["world"]（世界の解の行の並び。無ければ行の無い段）を行のファイルに書いた物。
        中の役（言い直す・集める・判断する）と照らしは test_blk_world が見る"""
        import worldmark
        rows = self.replies.get("world") or []
        p = self.tmp / "exits" / "world" / worldmark.WORLD_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        return {"ok": True, "world_file": str(p), "status": "ok", "reason": "", "classes": len(rows), "cached": 0,
                "skipped": 0, "dropped": 0}

    def blk_fix(self):
        self._edit("fix")
        self.take("p3.fix", self.replies["fix"])
        return {"ok": True, "files": ["stats.py"], "changes_file": "", "removed": {"count": 0, "file": ""}}

    def blk_rejudge(self):
        """blk-rejudge の中の節の順（rj-snap → 経路 rj-route1 → 支度・役・受け付けの輪 → 出口 collect）を本物の口で回す。
        役の返答は replies[<役>]（無ければ盤面の今の単位をそのまま返して異議を退ける見本）。輪は受け付けの done で抜ける（R50）"""
        import entry
        import rejudge
        rejudge.snap(self.board, self.repo)
        r = rejudge.route(self.board, self.repo)   # 段は 1 つ（第三の目の段はブロックに無い）
        if r["next"]:
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

    def blk_lens(self):
        """blk-lens の中の節の順（振り分け → go のレンズの節 → 集め役 → 境）を本物の口で回す。レンズの返答は replies[<レンズの節>]
        （None は節が落ちた形。無ければ LENS_REPLY）。replies["lens-collect"] が "fail" なら集め役が落ちた形（境へ null）。
        定義は lens_plugin の偽の置き場から引く"""
        from unittest import mock
        if str(ROOT / "blk-lens" / "lib") not in sys.path:
            sys.path.insert(0, str(ROOT / "blk-lens" / "lib"))
        import lenses
        with mock.patch.dict(os.environ, lens_plugin(self.tmp)):
            r = lenses.route(self.board)
        env = {}
        for row in lenses.LENSES:
            node = f"lens-{row['lens']}"
            body = self.replies.get(node, LENS_REPLY) if r[f"{lenses.key(row)}_go"] else None
            env[lenses.input_name(row)] = json.dumps(body, ensure_ascii=False)
        collected = None if self.replies.get("lens-collect") == "fail" else lenses.collect(self.board, env)
        return lenses.exit_(self.board, collected)

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
        ci = entry.run_ci(b, "p4.ci", test_cmd=self.out["entering"]["test_cmd"])
        b.settle()
        b = entry.open_board(self.board, allow_halted=True)
        if ci["by"] == "role_needed":   # blk-tests の run_final と同じ: 素材はまだ修正前の物なので読まない
            return {"ok": True, "green": False, "log": "", "suites": [], "by": "role_needed"}
        mat = ((b.record.get("materials") or {}).get("local_checks") or {})
        return {"ok": True, "green": mat.get("status") == "clean", "log": ci["log"], "suites": [], "by": ci["by"]}

    # -- 線
    def _src(self, v):
        """with: の出どころを値に（{from, if_skipped} は走らなかった節で None。文字列 null も None）"""
        if isinstance(v, dict):
            nid, _, field = v["from"].lstrip("$").partition(".output")
            if nid not in self.out:
                return v.get("if_skipped")
            got = self.out[nid]
            return got.get(field.lstrip(".")) if field and isinstance(got, dict) else got
        return None if v == "null" else v

    def _when(self, row) -> bool:
        w = row.get("when")
        if not w:
            return True
        ref, _, want = w.partition(" == ")
        nid, _, field = ref.lstrip("$").partition(".output.")
        return nid in self.out and self.out[nid].get(field) is (want == "true")

    def _after_failed(self, row) -> bool:
        """all_done でない節は、出口が ok: false の include（outcome_field ok で落ちた節）に依れば飛ぶ"""
        includes = {r["id"] for r in LINE_ORDER if r["kind"] == "include"}
        return row.get("trigger_rule") != ALL_DONE and any(
            d in includes and isinstance(self.out.get(d), dict) and self.out[d].get("ok") is False
            for d in row.get("depends_on") or [])

    def run(self):
        if self.path is None:
            return self._run()
        from unittest import mock
        with mock.patch.dict(os.environ, {"PATH": self.path}):
            return self._run()

    def _run(self):
        import entry
        import halt
        import line_edge
        import report
        blocks = {"blk-ci": self.blk_ci, "blk-pr": self.blk_pr, "blk-premises": self.blk_premises, "blk-purpose": self.blk_purpose,
                  "blk-judge": self.blk_judge, "blk-plan": self.blk_plan, "blk-fix": self.blk_fix, "blk-lens": self.blk_lens,
                  "blk-delta": self.blk_delta,
                  "blk-refix": self.blk_refix, "blk-tests": self.blk_tests, "blk-eyes": self.blk_eyes,
                  "blk-report": self.blk_report, "blk-material": self.blk_material, "blk-rejudge": self.blk_rejudge,
                  "blk-structure": self.blk_structure, "blk-world": self.blk_world}
        for row in LINE_ORDER:
            nid = row["id"]
            self.row = row
            if row.get("block") == "blk-entry":   # 入口のブロック（起動の関所を越えた後の open の節。中身は entry.start）
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
                                               adapter_mode=self.out["entering"]["adapter"], **kw)
                self.trail.append(nid)
            elif row.get("script") == "depth":
                import depth
                fix = self.out.get("h-fix") or {}
                self.out[nid] = depth.node(self.board, row["at"], open_units=fix.get("open_units") or "",
                                           tdd_suite=self.inputs.get("tdd_suite") or "",
                                           replanned=(self.out.get("h-replan") or {}).get("go") is True,
                                           rejudged=(self.out.get("h-rejudge") or {}).get("go") is True)
                self.trail.append(nid)
            elif nid == "h-world":
                self.out[nid] = line_edge.world_edge(self.board, self._src(row["with"]["worlded"]),
                                                     (self.out.get("h-mat") or {}).get("world_go") is True)
                self.trail.append(nid)
            elif nid == "h-structure":
                self.out[nid] = line_edge.structure_edge(self.board, self._src(row["with"]["structured"]),
                                                         self.out["h-plan"].get("go") is not False)
                self.trail.append(nid)
            elif nid == "h-after":
                self.out[nid] = line_edge.after_edge(self.board, self._src(row["with"]["measured"]))
                self.trail.append(nid)
            elif row["kind"] == "approval":
                if self._when(row):
                    self.out[nid] = self.gates.get(nid) or {"decision": "continue", "text": ""}
                    self.trail.append(nid)
            elif row["kind"] == "include":
                if not self._when(row) or self._after_failed(row):
                    continue
                if nid in SECOND_INCLUDES:   # 同じブロックの 2 度目の include は、1 度目の口で回さない
                    raise AssertionError(f"LineRun は {nid}（{SECOND_INCLUDES[nid]}）を回さない")
                if row["block"] not in blocks:
                    raise AssertionError(f"LineRun は {row['block']} を回せない（{nid}）")
                self.out[nid] = blocks[row["block"]]()
                self.trail.append(nid)
            elif nid == "report":
                w = row["with"]
                self.out[nid] = report.build(self.board.resolve(), judged=self._src(w["judged"]), tests=self._src(w["tests"]),
                                             start=self._src(w["start"]), ci=self._src(w["ci"]),
                                             run_id=RUN_ID, events=[],
                                             depth_lines=(self._src(w["depth"]) or {}).get("lines") or (),
                                             tdd=[self._src(w["fix_tdd"]), self._src(w["refit_tdd"])])
                self.trail.append(nid)
            elif nid == "result":
                self.out[nid] = report.final_result(self.out["report"], self.out.get("reporting"))
                self.trail.append(nid)
        rep = self.out["result"]
        return {"outcome": rep["outcome"], "report": rep, "board_dir": self.board, "trail": self.trail, "out": self.out,
                "eyes_roles": self.eyes_roles, "mat_roles": self.mat_roles, "judge_brief": self.judge_brief,
                "judge_takes": self.judge_takes, "rejudge_roles": self.rejudge_roles, "ci_nodes": self.ci_nodes}


def run_line(tmp, *, replies, gates=None, inputs=None, stop_at=None, edits=None, sessions=False, request=None,
             github=False, declared=True) -> dict:
    """LineRun(...).run()。返り {outcome, report, board_dir, trail, out, eyes_roles, mat_roles, judge_brief, judge_takes,
    rejudge_roles, ci_nodes}"""
    return LineRun(tmp, replies=replies, gates=gates, inputs=inputs, stop_at=stop_at, edits=edits, sessions=sessions,
                   request=request, github=github, declared=declared).run()
