"""review-loop の TDD 版の修正の流れ（graphs/review-loop-tdd.json）だけが使う rules。

今の流れ（graphs/review-loop.json と rules/review-loop.py）には手を入れず、その rules を読み込んで公開名をそのまま出し、
TDD の節の関数を表（CONDS・BUILTINS・POST_CHECKS）に足した写しを出す。TDD を選ばない run はこのファイルを 1 度も読まない。

流れ（SWE-bench の FAIL_TO_PASS / PASS_TO_PASS と同じ形）:
  p3.tdd_start（版を固め、一式を 1 回走らせて元の結末を取る）→ p3.tdd_tests（テストだけを書く）→ p3.tdd_red（赤の確認）
  → p3.fix（実装。今の流れの節のまま）→ p3.tdd_green（緑の確認）
赤・緑の確認は LLM を挟まない。テスト一式は run の開始時に人が渡した実行ファイル（init --input tdd_suite=<パス>）を
JUnit XML の書き先 1 つを引数にして走らせ、XML を読む——テスト 1 件ごとの結末（passed・failure・error・skipped）が
機械で分かるので、「名指ししたテストの失敗として落ちたか（failure）」と「読み込み・準備で落ちたか（error・一式に居ない）」
を分けられる。「ほか」は元の結末で通っていたテスト（と、元に無かった名指しの外のテスト）で、元から落ちていたテストは問わない。
"""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# engine が差し込んだ道具（Reject・git など）。**import より前に取る**——この時点の globals は engine が差し込んだ物と
# モジュールの属性だけで、今の流れの rules にも同じ物を差し込む（engine を import しない約束はこのファイルも同じ）
_INJECTED = {k: v for k, v in globals().items() if not k.startswith("__")}

_spec = importlib.util.spec_from_file_location("graphloops_rules_review_loop", pathlib.Path(__file__).with_name("review-loop.py"))
base = importlib.util.module_from_spec(_spec)
base.__dict__.update(_INJECTED)
_spec.loader.exec_module(base)
# 今の流れの rules の公開名（フック・表・関数）を**全部**そのまま出す——engine はフックと表を名前で引き、出し忘れた名前は
# 「このループは持たない」に黙って倒れるので、名前を選んで並べない。下で定義し直す名前（record_round・finalize・on_new_round と
# 3 つの表）だけが差し替わる（tests/py/test_review_tdd.py が、それ以外が同じ物であることを見る）
globals().update({k: v for k, v in vars(base).items() if not k.startswith("__") and k not in _INJECTED})

SUITE_INPUT = "tdd_suite"   # init --input tdd_suite=<実行ファイル>。JUnit XML の書き先を第 1 引数に受け、リポジトリのルートで走る
SUITE_TIMEOUT = 1800        # 一式 1 回の上限（秒）。超えたら結末が決まらない＝確認は通らない
RETRY_MAX = 3               # 赤・緑の確認が同じ周に差し戻す上限。越えたら TDD を諦めて今の流れで進め、次の周の判定役に渡す
FRICTION_FLAGS = ("setup_heavy", "reaches_internals", "name_unclear")


# ---------------------------------------------------------------- テスト一式を走らせて結末を読む
def parse_junit(text):
    """JUnit XML → [{classname, name, outcome}]。outcome は passed / failure / error / skipped。読めなければ ET.ParseError"""
    root = ET.fromstring(text)
    cases = []
    for tc in root.iter("testcase"):
        kinds = [c.tag for c in tc if c.tag in ("failure", "error", "skipped")]
        outcome = "error" if "error" in kinds else "failure" if "failure" in kinds else "skipped" if "skipped" in kinds else "passed"
        cases.append({"classname": tc.get("classname") or "", "name": tc.get("name") or "", "outcome": outcome})
    return cases


def _id_parts(test_id):
    """『path/test_x.py::Class::test_y』→（[path, test_x, Class], test_y）。JUnit の classname は実行器の根で頭が変わるので、
    後ろ側の一致で引く"""
    parts = test_id.split("::")
    head = list(pathlib.PurePosixPath(parts[0]).with_suffix("").parts) + parts[1:-1]
    return head, parts[-1]


def match_case(test_id, cases):
    """名指しの 1 件に当たる JUnit の行（無ければ None）。名前が同じで、classname と識別子の頭の短い方が長い方の末尾"""
    head, name = _id_parts(test_id)
    for c in cases:
        cls = [x for x in c["classname"].split(".") if x]
        n = min(len(cls), len(head))
        if c["name"] == name and n and cls[-n:] == head[-n:]:
            return c
    return None


def run_suite(b):
    """人が渡した実行ファイルでテスト一式を 1 回走らせる ——（結末の一覧, 終了コード, 問題）。結末が取れなければ一覧は None。
    .py はこの Python で走らせる（検証器と同じ。Windows は .py を実行ファイルとして起こせない）"""
    exe = b.state["inputs"].get(SUITE_INPUT) or ""
    argv = ([sys.executable] if exe.endswith(".py") else []) + [exe]
    with tempfile.TemporaryDirectory(prefix="graphloops-tdd-") as td:
        junit = pathlib.Path(td) / "junit.xml"
        try:
            # 時間切れは木ごと止める（engine の run_tree）——実行器の子や孫が作業ツリーに書き続けない
            r = run_tree([*argv, str(junit)], cwd=repo_root(git), timeout=SUITE_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as e:
            return None, None, [f"テスト一式を走らせられない（{type(e).__name__}: {e}）"]
        if not junit.is_file():
            return None, r.returncode, [f"テスト一式が JUnit XML を書かなかった（exit {r.returncode}）: {(r.stdout + r.stderr)[-600:]}"]
        try:
            return parse_junit(junit.read_text(encoding="utf-8", errors="replace")), r.returncode, []
        except ET.ParseError as e:
            return None, r.returncode, [f"JUnit XML が読めない（{e}）"]


def _key(c):
    return f"{c['classname']}::{c['name']}"


def _must_pass(c, baseline):
    """名指しの外で通っていなければならないテストか——元の結末で通っていた物と、元に無かった物（この周に足した名指しの外）。
    元から落ちていた・飛ばされていた物は問わない（周の頭で赤い一式でも、TDD の確認が必ず落ちる形にしない）"""
    return baseline is None or baseline.get(_key(c), "passed") == "passed"


def red_problems(named, cases, exit_code, baseline=None):
    """赤の確認: 名指しのテストが全部 failure で落ち、名指しの外で通っていなければならない物（_must_pass）は通る。
    一式は 0 以外で終わる（名指しが落ちたのに 0 を返す実行器は結末を映していない）。baseline＝元の結末（_key → outcome）"""
    probs, hit = [], set()
    if not named:
        probs.append("名指しのテストが無い")
    if exit_code == 0:
        probs.append("テスト一式が exit 0 で終わった——名指しのテストが落ちたなら 0 にはならない（実行器が結末を映していない）")
    for t in named:
        c = match_case(t, cases)
        if c is None:
            probs.append(f"{t}: 一式の結末に居ない——読み込み（import・構文）で落ちたか、名指しが実行器の識別子と違う")
            continue
        hit.add(id(c))
        if c["outcome"] == "error":
            probs.append(f"{t}: error で落ちた——読み込みの失敗・準備の例外は狙いどおりの赤でない（テストの中の検査で落とせ）")
        elif c["outcome"] == "passed":
            probs.append(f"{t}: もう通る——直す前に赤でないテストは修正の証拠にならない")
        elif c["outcome"] == "skipped":
            probs.append(f"{t}: 飛ばされた——赤でも緑でもない")
    probs += [f"名指しの外の {_key(c)} が {c['outcome']}——テストだけを書く段がほかを壊した（元は通っていた・この周に足した物は緑のまま）"
              for c in cases if id(c) not in hit and c["outcome"] in ("failure", "error") and _must_pass(c, baseline)]
    return probs


def green_problems(named, cases, exit_code, baseline=None, baseline_exit=0):
    """緑の確認: 名指しのテストが全部通り、名指しの外で通っていなければならない物（_must_pass）も通る。一式が 0 で終わる
    （JUnit に載らない失敗——件数の柵など——も拾う）。元の一式が 0 で終わっていなかったなら終了コードは問わない"""
    probs = [] if exit_code == 0 or baseline_exit != 0 else [
        f"テスト一式が exit {exit_code} で終わった——JUnit の結末が全部通っていても、一式としては緑でない"]
    for t in named:
        c = match_case(t, cases)
        if c is None or c["outcome"] != "passed":
            probs.append(f"{t}: {'一式の結末に居ない' if c is None else c['outcome']}——名指しのテストが緑でない")
    probs += [f"{_key(c)} が {c['outcome']}——ほかのテストが緑でない（元は通っていた・この周に足した物）"
              for c in cases if c["outcome"] in ("failure", "error") and _must_pass(c, baseline)]
    return probs


# ---------------------------------------------------------------- 周ごとの TDD の盤面（loop.tdd）と記録（process.tdd）
def _tdd(b):
    """この周の TDD の盤面（前の周の値は捨てる）"""
    t = b.loop_state.get("tdd") or {}
    if t.get("round") != b.round:
        t = {"round": b.round, "red_tries": 0, "green_tries": 0}
        b.loop_state["tdd"] = t
    return t


def _snap():
    try:
        return base._snapshot("graphloops tdd")
    except Reject:
        return None


def _diff_names(frm, to):
    """版 frm から版 to までに変わったファイル。取れなければ None"""
    names = git("diff", "--name-only", "-z", frm, to) if frm and to else None
    return None if names is None else [x for x in names.split("\0") if x]


def _run_and_note(b, t):
    """一式を走らせ、走らせたことで作業ツリーに出来た・変わったファイル（.gitignore の外に書く実行器の副産物）を
    t["suite_made"] に積む——テストだけを書く段が触ったファイルの数えから外すため（外さないと、前の試行の実行が
    作ったファイルを次の試行が『触った』ことにされる）"""
    pre = _snap()
    cases, code, why = run_suite(b)
    made = _diff_names(pre, _snap())
    t["suite_made"] = sorted(set(t.get("suite_made") or []) | set(made or []))
    return cases, code, why


def _row(b):
    return b.record["process"].setdefault("tdd", {"suite": b.state["inputs"].get(SUITE_INPUT), "rounds": {}})["rounds"].setdefault(str(b.round), {})


def tdd_start(b, nid):
    """テストを書く前の版を固め、一式を 1 回走らせて元の結末を取る——テストだけを書く段が触ったファイルはこの版からの差で測り、
    『ほかは緑のまま』は元の結末で通っていた物に当てる"""
    t = _tdd(b)
    t["start"] = _snap()
    if t["start"] is None:
        return {"ok": False, "problems": ["テストを書く前の版を固められない（git を確かめよ）"]}
    cases, code, why = _run_and_note(b, t)
    if why:
        return {"ok": False, "problems": [f"元の結末を取れない: {w}" for w in why]}
    t["baseline"] = {_key(c): c["outcome"] for c in cases}
    t["baseline_exit"] = code
    red_before = sorted(k for k, v in t["baseline"].items() if v in ("failure", "error"))
    _row(b).update(baseline_red=red_before)
    return {"ok": True, "rev": t["start"], "cases": len(cases), "red_before": red_before[:20]}


def _named_in(out):
    """テストだけを書く段の返答から名指しのテストを引く式の正本（盤面の側 _named と条件の側が同じ物を呼ぶ）"""
    return [t for u in (out or {}).get("units") or [] if u.get("route") == "tdd" for t in u.get("tests") or []]


def _named(b):
    return _named_in(b.output_of_round("p3.tdd_tests", b.round))


@cond_reads("cur.p3.tdd_tests")
def tdd_named(v):
    """赤の確認を撃つか（条件の関数）: この周のテストだけを書く段が、名指しのテストを 1 件以上出した"""
    n = len(_named_in(v("cur.p3.tdd_tests", None)))
    return bool(n), f"この周のテストだけを書く段が名指ししたテストは {n} 件"


@cond_reads("cur.p3.tdd_tests", "loop.tdd", "round")
def tdd_red_passed(v):
    """緑の確認を撃つか（条件の関数）: 名指しのテストがあり、赤の確認が通った（上限で諦めた周は撃たない——実装は今の流れで直した）"""
    ok, why = tdd_named(v)
    if not ok:
        return ok, why
    t = v("loop.tdd", None) or {}
    red = t.get("red") if t.get("round") == v("round") else None
    return red not in (None, "failed"), f"{why}、この周の赤の確認は {red}"


def _give_up(b, t, step, probs):
    """上限を越えた: TDD を諦めて今の流れで進め、理由を記録と次の周の判定役に残す（止めない——止めると出口が patch しか無い）"""
    t[step] = "failed"
    t["problems"] = probs
    _row(b)[step] = "failed"
    _row(b)[f"{step}_problems"] = probs[:10]
    b.loop_state.setdefault("tdd_gave_up", []).append({"round": b.round, "step": step, "problems": probs[:10]})
    return {"ok": True, "gave_up": step, "problems": probs}


def _retry(b, t, step, back, probs):
    t[f"{step}_tries"] += 1
    t["problems"] = probs
    if t[f"{step}_tries"] >= RETRY_MAX:
        return _give_up(b, t, step, probs)
    if back == "p3.fix":
        # 落ちた試行が process.fixes に残ると、読む側（R1・報告）がどれを採ったか区別できない——この周の行を外してから差し戻す
        fixes = b.record["process"].get("fixes") or []
        b.record["process"]["fixes"] = [r for r in fixes if not (isinstance(r, dict) and r.get("round") == b.round)]
    b.rewind([back], by=f"p3.tdd_{step}")
    return {"ok": False, "problems": probs, "rewound": [back]}


def tdd_red(b, nid):
    """赤の確認。テストだけを書く段が触ったのは申告したテストのファイルだけで、名指しのテストが failure で落ち、ほかは緑のまま。
    通らなければテストだけを書く段を差し戻す（理由は loop.tdd.problems でプロンプトに戻る）"""
    t = _tdd(b)
    out = b.output_of_round("p3.tdd_tests", b.round) or {}
    named = _named(b)
    now = _snap()
    changed = _diff_names(t.get("start"), now)
    probs = []
    if changed is None:
        probs.append("テストを書く前の版からの差が取れない")
    else:
        extra = sorted(set(changed) - set(out.get("test_files") or []) - set(t.get("suite_made") or []))
        if extra:
            probs.append(f"テストだけを書く段が、申告したテストのファイルの外に触れた: {extra[:5]}——実装は次の段でやる")
    cases, code, why = _run_and_note(b, t)
    probs += why or red_problems(named, cases, code, t.get("baseline"))
    if probs:
        return _retry(b, t, "red", "p3.tdd_tests", probs)
    t.update(red=now, named=named, problems=[])
    units = out.get("units") or []
    _row(b).update(named=named, direct=[u["unit_key"] for u in units if u.get("route") == "direct"],
                   friction=[u["unit_key"] for u in units if any((u.get("friction") or {}).get(k) for k in FRICTION_FLAGS)],
                   red="ok")
    return {"ok": True, "named": len(named)}


def tdd_green(b, nid):
    """緑の確認。名指しのテストもほかも通り、実装の段が申告したテストのファイルを赤の確認の版から書き換えていない"""
    t = _tdd(b)
    out = b.output_of_round("p3.tdd_tests", b.round) or {}
    # 版どうしで比べる（作業ツリーと版の git diff は本物の index に無い新規のテストのファイルを『消えた』と数える）
    changed = _diff_names(t.get("red"), _snap())
    touched = None if changed is None else sorted(set(changed) & set(out.get("test_files") or []))
    probs = []
    if touched is None:
        probs.append("赤を確かめた版からテストのファイルの差が取れない")
    elif touched:
        probs.append(f"実装の段が申告したテストのファイルを書き換えた: {touched[:5]}——テストは凍っている（誤りなら rejudge_requested へ）")
    cases, code, why = _run_and_note(b, t)
    probs += why or green_problems(t.get("named") or [], cases, code, t.get("baseline"), t.get("baseline_exit", 0))
    if probs:
        return _retry(b, t, "green", "p3.fix", probs)
    t["green"] = "ok"
    _row(b)["green"] = "ok"
    return {"ok": True}


def tdd_tests_output(b, nid, out, item):
    """テストだけを書く段の返答: 直す義務の単位を全部 1 度だけ、tdd（名指しのテストが 1 件以上）か direct（理由）に振る。
    書きにくさの旗を立てたなら note を書く"""
    owed = base._owed_units(b)
    rows = out.get("units") or []
    errs = base._keys_once([{"key": r["unit_key"]} for r in rows], "units")
    got = {r["unit_key"] for r in rows}
    errs += [f"直す義務の単位 '{k[:60]}' をどちらの道にも振っていない" for k in sorted(owed - got)]
    errs += [f"'{k[:60]}' は今の周に直す義務の単位に無い" for k in sorted(got - owed)]
    for r in rows:
        if r["route"] == "tdd" and not r.get("tests"):
            errs.append(f"'{r['unit_key'][:60]}': tdd の道なのに名指しのテストが無い")
        if r["route"] == "direct" and base.blank(r.get("why"), 10):
            errs.append(f"'{r['unit_key'][:60]}': direct の道に回す理由（テストを先に書けない理由）が無い")
        f = r.get("friction") or {}
        if any(f.get(k) for k in FRICTION_FLAGS) and base.blank(f.get("note"), 10):
            errs.append(f"'{r['unit_key'][:60]}': 書きにくさの旗を立てたのに、何が書きにくいか（note）が無い")
    if errs:
        raise Reject("; ".join(errs))


# ---------------------------------------------------------------- 周の頭・周の締め・報告の前
def on_new_round(b):
    """今の流れの周の頭のあとで、前の周に TDD を諦めた理由（上限を越えた赤・緑の確認）を、次の周の判定役へ渡す穴の行に足す"""
    base.on_new_round(b)
    ls = b.loop_state
    rows = [{"key": f"TDD の{'赤' if g['step'] == 'red' else '緑'}の確認が上限で通らなかった（round {g['round']}）",
             "from": f"p3.tdd_{g['step']}", "how": "; ".join(g["problems"])[:600]}
            for g in ls.get("tdd_gave_up") or [] if g["round"] == b.round - 1]
    if rows:
        ls["prev_declared_faces"] = (ls.get("prev_declared_faces") or []) + rows


def tdd_effect(b):
    """TDD を使った周ごとに、比べる 2 つの量を記録へ（record.process.tdd.rounds）。数え方は今の rules のまま（写さない）:
    lane_missed＝その周の修正差分への変異の見逃しの本数（線の結果の腕を _unproven で数える。線が書き終えるまで None）／
    faces_created_by_this_fix＝その周の修正が作った指摘の件数（次の周の周の記録の scalars.faces_created_by_prev_fix。まだなら None）"""
    rows = (b.record["process"].get("tdd") or {}).get("rounds") or {}
    lanes = {l["round"]: l for l in (b.loop_state.get("lanes") or {}).values()}
    for rnd, row in rows.items():
        lane = lanes.get(int(rnd))
        res, errs = base._lane_result(b, lane) if lane else (None, [])
        row["lane_missed"] = len(base._unproven(res.get("arms") or [])) if res and not errs else None
        nxt = b.dir / "rounds" / f"round-{int(rnd) + 1}.json"
        row["faces_created_by_this_fix"] = ((read_json(nxt).get("scalars") or {}) if nxt.is_file() else {}).get("faces_created_by_prev_fix")


def record_round(b, nid):
    """周の記録を組んだ後に効き目を測り直す（次の周の記録が書けた分・線が書き終えた分が埋まる）"""
    out = base.record_round(b, nid)
    tdd_effect(b)
    return out


def finalize(b):
    base.finalize(b)
    tdd_effect(b)


CONDS = {**base.CONDS, "tdd_named": tdd_named, "tdd_red_passed": tdd_red_passed}
LOOP_KEYS = base.LOOP_KEYS | {"tdd", "tdd_gave_up"}   # TDD の節が盤面の loop に足す鍵（graphcheck が条件と節の loop.<鍵> を照らす正本）
BUILTINS = {**base.BUILTINS, "tdd_start": tdd_start, "tdd_red": tdd_red, "tdd_green": tdd_green, "record_round": record_round}
POST_CHECKS = {**base.POST_CHECKS, "tdd_tests_output": tdd_tests_output}
