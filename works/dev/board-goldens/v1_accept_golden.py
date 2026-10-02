# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""v1 の受け付け（works/.shared/core/accept.py の check_*）の返りの手本の作り手（仕様 7 節・9.4）。

tests/replies/ の全部の返答と依頼を、test_accept.py の AcceptCase と同じ種（dev/target-seed を git に写した使い捨ての
対象リポジトリと空の盤面）で、依頼 → 判定 → 修正 → 差分の審査の順に check_* に通し、返りを撮る。受け付けの入れ物を
偽の盤面（_Board）から DiskBoard.scratch に替える前に撮り、替えた後に tests/test_accept_v1_golden.py が同じ場面を
回して比べる（場面の表 CASES と回し方 run_case はここが正本で、試験はこのファイルを読み込んで使う）。

使い方: nice -n 19 uv run works/dev/board-goldens/v1_accept_golden.py --out works/tests/boards/v1-accept-golden.json
作業場は ${WORKS_DEV_HOME:-$HOME/.cache/works-dev}/board-goldens/v1-accept-* に作って終わったら消す
（Claude Code の一時フォルダ /private/tmp/claude-*・/tmp/claude-* の下に解ける作業場は拒む。make.py と同じ決まり）。
お金 0・AI 0（git と写しの規則を呼ぶだけ）。

手本の 1 行: {name, fn, input: {reply, base_rev, before}, result, files, written}
- reply は tests/replies/ の名前（形を変えた物は「名前+変え方」。変え方は VARIANTS）。base_rev は "<base>"（種の commit）か ""
- before は前の手（BEFORE の名前。依頼・判定の受け付け、作業ツリーの変更、写しを置く）を順に
- result は check_* の返りの全部の鍵。パスは <board>・<repo>・<tmp> に、種の commit の id は <base> に置き換える
- files は最後の手の後の盤面の置き場の中のファイルの名前（入れ子は / で。名前の順）
- written は受け付けが盤面に書く JSON（request.json・judgment.json・delta-review.json）の中身
終了コード: 0 = 撮れた / 2 = 失敗（作業場が一時フォルダの下・前の手が通らない）
"""
import argparse
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
WORKS = HERE.parents[1]
CORE = WORKS / ".shared" / "core"
REPLIES = WORKS / "tests" / "replies"
SEED = WORKS / "dev" / "target-seed"
DEFAULT_OUT = WORKS / "tests" / "boards" / "v1-accept-golden.json"
CLAUDE_TMP = ("/private/tmp/claude-", "/tmp/claude-")
# 版の id を揃える（make.py の GIT_ENV と同じ。利用者と機械の git の設定を読ませない）
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
}
GIT_ID = ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
WRITTEN = ("request.json", "judgment.json", "delta-review.json")
# 修正の後の stats.py（test_accept.py の FIXED_STATS と同じ）
FIXED_STATS = '''"""直した後の姿。"""


def mean(xs):
    return sum(xs) / len(xs)


def clamp(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
'''
HELPER = "def helper():\n    return 1\n"

sys.dont_write_bytecode = True
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))


def _accept():
    import accept
    return accept


def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


def _verdicts():
    """穴の在る 1 回目の差分の審査の返答の 2 判定の欄（準拠は delta_ok の not_applicable、品質は穴が在るので delta_bad_cite の fail）"""
    return {"compliance": load("delta_ok")["compliance"], "quality": load("delta_bad_cite")["quality"]}


def _plan_only(kind):
    return {"faces": [{"key": f"stats.py の {kind} の穴", "kind": kind, "where": "stats.py", "cite": "def clamp(x, lo, hi):",
                       "why": "修正差分のレビューが事前審査だけの語で穴を挙げている"}], "checks": [], **_verdicts()}


def _without(name, key):
    r = load(name)
    del r[key]
    return r


def _unit_key_typo():
    r = load("fix_ok")
    r["changes"][0]["unit_key"] += "（写し違い）"
    return r


def _carried_r1():
    r = load("judge_ok")
    r["carried_r1"] = [{"where": "stats.py:4", "disposition": "decline", "why": "削除すると mean が壊れる"}]
    return r


# 形を変えた返答（名前 → 作り方）。tests/replies/ の見本を test_accept.py と同じ形に変える
VARIANTS = {
    "request_ok+not_list": lambda: {"where": "stats.py", "text": "x"},
    "judge_ok+no_units": lambda: _without("judge_ok", "units"),
    "judge_ok+not_object": lambda: "units",
    "judge_ok+carried_r1": _carried_r1,
    "fix_ok+unit_key_typo": _unit_key_typo,
    "fix_ok+not_object": lambda: ["changes"],
    "delta_ok+helper_face": lambda: {"faces": [{"key": "helper.py 使われない関数", "kind": "dead_path", "where": "helper.py",
                                                "cite": "def helper():", "why": "どこからも呼ばれない関数を修正が足している"}],
                                     "checks": [], **_verdicts()},
    "delta_ok+stray_check": lambda: {**load("delta_ok"), "checks": [{"key": "stats.py 塞いだと言われていない穴", "closed": True,
                                                                      "why": "修正が塞いだと言っていない穴を審査役が検算している"}]},
    "delta_ok+no_faces_none": lambda: _without("delta_ok", "faces_none"),
    "delta_ok+regression": lambda: _plan_only("regression"),
    "delta_ok+policy": lambda: _plan_only("policy"),
    "delta_ok+precedent": lambda: _plan_only("precedent"),
}


def reply_of(name):
    return VARIANTS[name]() if name in VARIANTS else load(name)


# 前の手（名前 → (盤面, 対象, 種の commit) を受けて何かする）。受け付けの手は通らなければ落とす
def _must(r, what):
    if not r.get("ok"):
        raise RuntimeError(f"前の手 {what} が通らない: {r.get('reason')}")


def _append(path, text):
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def _snapshot(board, repo, name):
    (board / name).write_text(json.dumps(_accept().snapshot_tree(repo)), encoding="utf-8")


BEFORE = {
    "request:request_ok": lambda b, r, base: _must(_accept().check_request(load("request_ok"), b, "持ち主"), "request_ok"),
    "judge:judge_ok": lambda b, r, base: _must(_accept().check_judge(load("judge_ok"), b, base, r), "judge_ok"),
    "judge:judge_no_fix": lambda b, r, base: _must(_accept().check_judge(load("judge_no_fix"), b, base, r), "judge_no_fix"),
    "tree:fix_stats": lambda b, r, base: (r / "stats.py").write_text(FIXED_STATS, encoding="utf-8"),
    "tree:add_helper": lambda b, r, base: (r / "helper.py").write_text(HELPER, encoding="utf-8"),
    "tree:dirty_extra": lambda b, r, base: (r / "extra.txt").write_text("読むだけの役が書いた\n", encoding="utf-8"),
    "tree:append_stats": lambda b, r, base: _append(r / "stats.py", "# 審査役が書いた\n"),
    "snapshot:judge": lambda b, r, base: _snapshot(b, r, _accept().JUDGE_SNAPSHOT_FILE),
    "snapshot:delta": lambda b, r, base: _snapshot(b, r, _accept().SNAPSHOT_FILE),
}


def _case(name, fn, reply, before=(), base_rev="<base>"):
    return {"name": name, "fn": fn, "input": {"reply": reply, "base_rev": base_rev, "before": list(before)}}


# 場面の表。test_accept.py の組（依頼 → 判定 → 修正 → 差分の審査）の順で、tests/replies/ の全部を 1 度以上通す
CASES = [
    _case("request_ok", "check_request", "request_ok"),
    _case("request_ok_twice", "check_request", "request_ok", ["request:request_ok"]),
    _case("request_extra_key", "check_request", "request_extra_key"),
    _case("request_not_list", "check_request", "request_ok+not_list"),
    _case("judge_ok_after_request", "check_judge", "judge_ok", ["request:request_ok"]),
    _case("judge_ok_no_request", "check_judge", "judge_ok"),
    _case("judge_ok_empty_base_rev", "check_judge", "judge_ok", base_rev=""),
    _case("judge_missing_units", "check_judge", "judge_ok+no_units", ["request:request_ok"]),
    _case("judge_notfound_no_searched", "check_judge", "judge_notfound_no_searched", ["request:request_ok"]),
    _case("judge_no_fix", "check_judge", "judge_no_fix", ["request:request_ok"]),
    _case("judge_dirty_tree", "check_judge", "judge_ok", ["request:request_ok", "tree:dirty_extra"]),
    _case("judge_snapshot_same", "check_judge", "judge_ok", ["tree:dirty_extra", "request:request_ok", "snapshot:judge"]),
    _case("judge_snapshot_changed", "check_judge", "judge_ok", ["request:request_ok", "snapshot:judge", "tree:dirty_extra"]),
    _case("judge_carried_r1_round1", "check_judge", "judge_ok+carried_r1", ["request:request_ok"]),
    _case("judge_not_object", "check_judge", "judge_ok+not_object"),
    _case("fix_ok", "check_fix", "fix_ok", ["request:request_ok", "judge:judge_ok"]),
    _case("fix_missing_unit", "check_fix", "fix_missing_unit", ["request:request_ok", "judge:judge_ok"]),
    _case("fix_unit_key_typo", "check_fix", "fix_ok+unit_key_typo", ["request:request_ok", "judge:judge_ok"]),
    _case("fix_without_judgment", "check_fix", "fix_ok"),
    _case("fix_after_no_fix", "check_fix", "fix_ok", ["request:request_ok", "judge:judge_no_fix"]),
    _case("fix_not_object", "check_fix", "fix_ok+not_object", ["request:request_ok", "judge:judge_ok"]),
    _case("delta_ok", "check_delta", "delta_ok", ["tree:fix_stats"]),
    _case("delta_ok_empty_base_rev", "check_delta", "delta_ok", ["tree:fix_stats"], base_rev=""),
    _case("delta_ok_untouched", "check_delta", "delta_ok"),
    _case("delta_bad_cite", "check_delta", "delta_bad_cite", ["tree:fix_stats"]),
    _case("delta_stray_check", "check_delta", "delta_ok+stray_check", ["tree:fix_stats"]),   # 塞いだと言われた穴（p3.fix の出力）を読む道
    _case("delta_no_faces_none", "check_delta", "delta_ok+no_faces_none", ["tree:fix_stats"]),
    _case("delta_face_on_untracked", "check_delta", "delta_ok+helper_face", ["tree:fix_stats", "tree:add_helper"]),
    _case("delta_snapshot_same", "check_delta", "delta_ok", ["tree:fix_stats", "snapshot:delta"]),
    _case("delta_snapshot_changed", "check_delta", "delta_ok", ["tree:fix_stats", "snapshot:delta", "tree:append_stats"]),
    _case("delta_plan_only_regression", "check_delta", "delta_ok+regression", ["tree:fix_stats"]),
    _case("delta_plan_only_policy", "check_delta", "delta_ok+policy", ["tree:fix_stats"]),
    _case("delta_plan_only_precedent", "check_delta", "delta_ok+precedent", ["tree:fix_stats"]),
    _case("delta_after_full_run", "check_delta", "delta_ok",
          ["request:request_ok", "judge:judge_ok", "tree:fix_stats"]),
]


def _git(repo, *args):
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=True,
                          env=env, stdin=subprocess.DEVNULL).stdout.strip()


def _scrub(x, subs):
    if isinstance(x, str):
        for old, new in subs:
            x = x.replace(old, new)
        return x
    if isinstance(x, list):
        return [_scrub(v, subs) for v in x]
    if isinstance(x, dict):
        return {k: _scrub(v, subs) for k, v in x.items()}
    return x


def run_case(case, work: pathlib.Path) -> dict:
    """場面を 1 つ、work の下の新しい対象と盤面で回し、手本の 1 行を返す（work は空の使い捨ての置き場）"""
    accept = _accept()
    repo, board = work / "repo", work / "board"
    shutil.copytree(SEED, repo)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    base = _git(repo, "rev-parse", "HEAD")
    board.mkdir()
    for step in case["input"]["before"]:
        BEFORE[step](board, repo, base)
    rev = base if case["input"]["base_rev"] == "<base>" else case["input"]["base_rev"]
    reply = reply_of(case["input"]["reply"])
    fn = getattr(accept, case["fn"])
    if case["fn"] == "check_request":
        result = fn(copy.deepcopy(reply), board, "持ち主")
    else:
        result = fn(copy.deepcopy(reply), board, rev, repo)
    files = sorted(str(p.relative_to(board)) for p in board.rglob("*") if p.is_file())
    written = {n: json.loads((board / n).read_text(encoding="utf-8")) for n in WRITTEN if (board / n).is_file()}
    subs = [(str(board), "<board>"), (str(repo), "<repo>"), (os.path.realpath(board), "<board>"),
            (os.path.realpath(repo), "<repo>"), (str(work), "<tmp>"), (os.path.realpath(work), "<tmp>"), (base, "<base>")]
    return _scrub({**case, "result": result, "files": files, "written": written}, subs)


def run_all(root: pathlib.Path) -> list:
    """全部の場面を root の下で 1 つずつ別の置き場で回す"""
    rows = []
    for i, case in enumerate(CASES):
        work = root / f"{i:02d}"
        work.mkdir()
        rows.append(run_case(case, work))
    return rows


def refuse_claude_tmp(what, path):
    real = os.path.realpath(path)
    if real.startswith(CLAUDE_TMP):
        print(f"v1_accept_golden.py: {what} が Claude Code の一時フォルダの下にある（{real}）。別の場所を使う"
              "（WORKS_DEV_HOME の既定は $HOME/.cache/works-dev）", file=sys.stderr)
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    base = pathlib.Path(os.environ.get("WORKS_DEV_HOME") or pathlib.Path.home() / ".cache" / "works-dev") / "board-goldens"
    refuse_claude_tmp("作業場の親（WORKS_DEV_HOME）", base)
    base.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(tempfile.mkdtemp(prefix="v1-accept-", dir=base))
    try:
        try:
            rows = run_all(work)
        except RuntimeError as e:
            print(f"v1_accept_golden.py: {e}", file=sys.stderr)
            return 2
    finally:
        shutil.rmtree(work, ignore_errors=True)
    out = pathlib.Path(a.out)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} 場面を {out} に撮った（通った {sum(1 for r in rows if r['result'].get('ok'))}）")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
