"""判定の根を開く（線の木の段 3。設計 docs/plans/2026-10-06-judge-verify.md）。判定役が切った開いた単位ごとに、判定役とは別の目の
下請けが「本当に根本か・証拠は在るか・場所は合っているか」を確かめ、別の 1 つの下請けが単位どうしの重複・関わり・順番を見る。
束ね役（AI の節 judge-verify）が下請けを Agent の道具で 1 つのメッセージに並べて起こし、下請けは答えを盤面の外の run ごとの
置き場（answers_dir。盤面は役が書けない）に Write で書く。機械（merge）が答えを型で確かめて申し送り（今の周の VERIFY_FILE。
manifest の produces）にまとめる。単位は消さない（直す義務。根本でないと出ても申し送りと報告の行になるだけ）。

- prep(board_dir, repo, verify="") / prep_on(b, judgment, repo, verify=""): ラインの盤面で、止まっておらず、入力 verify が off でなく
  （script_io.switch_on。空は on）、判定の開いた単位が MIN_UNITS 以上の時だけ go 真。単位ごとの下請けのファイル（scope の根の verify/unit-<n>.md）・相乗りのファイル（verify/synergy.md）・束ね役の指示書
  （verify/prompt.md）・番号の控え（PLAN_FILE）・作業ツリーの姿（TREE_FILE）を書き、前の起動の答えを消し、申し送りの初めの形
  （全部が UNVERIFIED）を置く。go 偽なら前の残りの申し送りと番号の控えを消す
- merge(board_dir, repo) / merge_on(b, repo): 番号の控えの単位ごとに答えのファイルを確かめ（型・番号・not_root の本当の根）、相乗りの
  番号を単位の key に戻して申し送りを書く。作業ツリーが変わっていれば盤面を止める（読むだけの役の決まり）。trace に TRACE_OP
- output_format(): 束ね役の返答の型（1 行の要約だけ。答えの中身は写さない）に印 works-node: judge-verify
"""
import copy
import json
import pathlib
import shutil
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import accept as core_accept  # noqa: E402
import adapter  # noqa: E402  （L2。run ごとの置き場 run_place_of。下請けの答えのファイルの置き場）
import entry  # noqa: E402
import judgetake  # noqa: E402
import node_marker  # noqa: E402
import script_io  # noqa: E402  （L1。入力の切り替えの語 switch_on）
from engine.schema import validate_schema  # noqa: E402  （board が写しの engine を sys.path に足した後）

ROLE = "judge-verify"                  # 束ね役の節の id と印の名
VERIFY_FILE = "judge-verify.json"      # 申し送り（今の周。manifest の produces。境の節が修正案のブロックへパスで渡し、報告が読む）
BRIEF_DIR = "verify"                   # 下請けのファイルと束ね役の指示書の置き場（scope の根の今の周）
PLAN_FILE = "verify/plan.json"         # 番号の控え {units: [{n, key}], answers}（支度が書き、まとめが読む）
TREE_FILE = "verify-tree.json"         # 束ね役を起こす前の作業ツリーの姿（accept.tree_state）
ANSWERS_DIR = "judge-verify/r{r}"      # 答えの置き場（run ごとの置き場の今の scope の下）
ANSWER_FILE = "unit-{n}.json"
SYNERGY_FILE = "synergy.json"
MIN_UNITS = 2                          # 裏取りを回す開いた単位の数の下限（1 単位は相乗りが無く、事前審査の下請けと重なる。設計書）
SUBAGENT_TYPE = "general-purpose"      # 下請けの型は 1 つ（答えのファイルを書ける型。線の木の段 1 の教訓）
STOP_BY = "works:judge-verify"         # 作業ツリーを変えた時の盤面の state.stop.by
TRACE_OP = "judge_verify"
OFF_OP = "judge_verify_off"           # 入力 verify が off で裏取りを回さなかった周の trace の行
CHECKED, UNVERIFIED = "checked", "unverified"
VERDICTS = ("root", "not_root", "unsure")
NOT_GO = {"ok": True, "go": False, "prompt_file": ""}
EMPTY_MERGE = {"ok": True, "verify_file": "", "verified": 0, "unverified": 0}
WAITING = "裏取りの答えがまだ無い（束ね役が落ちたか、下請けを起こさなかった）"

UNIT_HEAD = "## お前の単位: 単位 {n}"   # 下請けのファイルの共通の頭（全部の単位と相乗りで同じバイト）とその単位の節の境
ANSWER_AT = "Write の道具でファイル {answer} に書け"   # 下請けのファイルが答えの置き場を名指す句（answer_in が引く）
TITLE = "# 判定の単位の裏取りの下請け"
SUB_HEAD = ("お前は判定の単位の裏取りの下請け（読むだけ。Read・Grep・Glob で根拠のコードを調べ、Write は最後の節が名指す答えの"
            "ファイルにだけ使う。Edit・Bash を使わず、作業ツリーを 1 文字も変えない）。判定役が人の修正依頼を根本の単位に切った。"
            "お前はその切り方を判定役とは別の目で確かめる。ほかのファイルの指示書を読みに行かなくてよい（根拠のコードは読め）。")
RULES = ("## 決まり（全部の下請けで同じ）\n\n"
         "- 直し方は書かない（案は別の役が作る）。\n"
         "- 単位を消す・足す・ラベルを変える提案はしない。単位は直す義務で、この確かめでは減らない。根本でないと出ても、"
         "申し送りとして案を書く役と報告に届くだけ。\n"
         "- web（WebSearch・WebFetch）は根拠のコードで決まらない時だけ使う。判定の先行例の出典は開き直さない。\n"
         "- why・evidence は見た事実（パス:行と、そこに在った物）で書く。推測は unsure にする。")
UNIT_ASK = ("見ること: (1) 根本か（verdict）: この単位を直せば依頼の症状が消えるか。ほかの単位か単位に無い所の結果（症状の 1 つの"
            "現れ）でないか。root・not_root・unsure のどれか。not_root なら real_root に本当の根（見つけた所のパスと名と、そこが根と"
            "言える理由）を書く。単位どうしの重なりは別の下請けが見る。(2) 証拠（evidence_found・evidence）: 判定の理由が言う事実を根拠のコードで確かめたか。確かめた所と見た事を"
            "書く。(3) 場所（location_ok・location）: 単位の key が名指すパスと名が直す所か。違えば正しい場所を location に書く"
            "（合っていれば同じ場所）。答えは下の JSON Schema に合う JSON 1 つにして、" + ANSWER_AT + "（このファイルのほかに書かない）。"
            "書いたら最後のメッセージに 1 行だけ返せ: `単位 {n}: <verdict>`。\n\n```json\n{schema}\n```")
SYNERGY_HEAD = "## お前の確かめ: 単位どうしの相乗り"
SYNERGY_ASK = ("1 つの単位の中の確かめは別の下請けがする。お前は単位どうしの関わりだけを見る: duplicates（同じ根の別の現れ・同じ直しで"
               "閉じる）・relations（同じファイル・同じ名・同じ試験を触る、片方の直しがもう片方の前提を変える）・order（片方を先に"
               "直さないともう片方を直せない・試せない）。単位は下の番号で名指す。無ければ空の配列にし、why に見た事と無い理由を"
               "書く。答えは下の JSON Schema に合う JSON 1 つにして、" + ANSWER_AT + "（このファイルのほかに書かない）。書いたら"
               "最後のメッセージに 1 行だけ返せ: `相乗り: 重複 <数>・関わり <数>・順番 <数>`。\n\n```json\n{schema}\n```")
AGG = ("# 判定の単位の裏取りの束ね役（機械が書いた）\n\n"
       "お前は束ね役。単位を自分で見ずに、下の下請けのファイルごとに Agent の道具で下請けを 1 つずつ起こせ。下請けの呼びは"
       " 1 つのメッセージに全部並べよ（同時に走る）。subagent_type は全部 " + SUBAGENT_TYPE + "（ほかの型を使わない）。各下請けへの"
       "頼みは「<ファイル> を Read で読み、その指示に従え」の 1 行でよい。下請けは読むだけで、答えはファイルに書き（どこに書くかは"
       "ファイルが名指す。作業ツリーは変えない）、最後に 1 行の要約を返す。答えのファイルは機械が確かめてまとめるので、お前は"
       "答えの中身を写さない。")
AGG_REPLY = "下請けが全部返ったら、返答は次の JSON Schema に合う JSON だけにせよ（summary に下請けの 1 行の要約を並べる）:"


def output_format() -> dict:
    """束ね役の返答の型（印つき）。答えの中身は答えのファイルにあり、返答は要約だけ（線の木の段 1 の教訓: 束ね役に写させない）"""
    return node_marker.mark({"type": "object", "additionalProperties": False, "required": ["summary"],
                             "properties": {"summary": {"type": "string", "minLength": 10}}}, ROLE)


def unit_schema() -> dict:
    """単位の下請けの答えのファイルの型（not_root の本当の根 real_root はまとめが確かめる）"""
    return {"type": "object", "additionalProperties": False,
            "required": ["unit", "verdict", "evidence_found", "evidence", "location_ok", "location", "why"],
            "properties": {"unit": {"type": "integer", "minimum": 1}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                           "evidence_found": {"type": "boolean"}, "evidence": {"type": "string", "minLength": 10},
                           "location_ok": {"type": "boolean"}, "location": {"type": "string", "minLength": 1},
                           "why": {"type": "string", "minLength": 10}, "real_root": {"type": "string"}}}


def synergy_schema() -> dict:
    pair = {"type": "object", "additionalProperties": False, "required": ["units", "why"],
            "properties": {"units": {"type": "array", "minItems": 2, "items": {"type": "integer", "minimum": 1}},
                           "why": {"type": "string", "minLength": 4}}}
    order = {"type": "object", "additionalProperties": False, "required": ["first", "then", "why"],
             "properties": {"first": {"type": "integer", "minimum": 1}, "then": {"type": "integer", "minimum": 1},
                            "why": {"type": "string", "minLength": 4}}}
    return {"type": "object", "additionalProperties": False, "required": ["why", "duplicates", "relations", "order"],
            "properties": {"why": {"type": "string", "minLength": 10}, "duplicates": {"type": "array", "items": pair},
                           "relations": {"type": "array", "items": copy.deepcopy(pair)},
                           "order": {"type": "array", "items": order}}}


def answers_dir(b) -> pathlib.Path:
    """今の周の下請けの答えのファイルの置き場（run ごとの置き場の今の scope の下。作らない）"""
    place = pathlib.Path(adapter.run_place_of({"board": str(pathlib.Path(b.dir).resolve())}))
    return (place / b.scope if b.scope else place) / ANSWERS_DIR.format(r=b.round)


def answer_file(b, n: int) -> pathlib.Path:
    return answers_dir(b) / ANSWER_FILE.format(n=n)


def synergy_file(b) -> pathlib.Path:
    return answers_dir(b) / SYNERGY_FILE


def answer_in(brief: str) -> str:
    """下請けのファイルの文が名指す答えのファイル（ANSWER_AT の句。無ければ空）"""
    head, _, tail = ANSWER_AT.partition("{answer}")
    at = brief.find(head)
    if at < 0:
        return ""
    rest = brief[at + len(head):]
    end = rest.find(tail)
    return rest[:end] if end >= 0 else ""


def _read_json(path: pathlib.Path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _write_json(path: pathlib.Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def _halted(b) -> bool:
    return bool(b.state.get("halted") or b.state.get("stop"))


def open_units(judgment) -> list:
    """判定の開いた単位（直す義務の残る物。検証器の is_open）"""
    units = judgment.get("units") if isinstance(judgment, dict) else None
    return [u for u in units or [] if isinstance(u, dict) and isinstance(u.get("key"), str) and judgetake.is_open(u)]


def _unit_row(u: dict) -> dict:
    return {k: u[k] for k in ("key", "label", "disposition", "reason", "origin_analysis", "why_chain", "prescriptions")
            if k in u}


def _head(judgment: dict) -> str:
    view = {k: judgment[k] for k in ("framing", "one_shot") if isinstance(judgment.get(k), str)}
    return "\n\n".join(x for x in (TITLE, SUB_HEAD, RULES, f"## 判定者の見立て\n\n```json\n{json.dumps(view, ensure_ascii=False, indent=1)}\n```"
                                   if view else "") if x)


def _initial(units: list) -> dict:
    return {"units": [{"n": n, "key": u["key"], "state": UNVERIFIED, "errors": [WAITING]} for n, u in enumerate(units, 1)],
            "synergy": {"state": UNVERIFIED, "errors": [WAITING]}}


def _clear(b) -> None:
    for name in (VERIFY_FILE, PLAN_FILE):
        b.work(name).unlink(missing_ok=True)


def prep_on(b, judgment, repo, verify: str = "") -> dict:
    """支度の芯（b は開いた盤面か同じ口の物）。返り {ok, go, prompt_file}。verify が off なら単位の数に依らず go 偽（trace に
    OFF_OP の 1 行）"""
    units = open_units(judgment)
    if not script_io.switch_on(verify, "verify"):
        _clear(b)
        if not _halted(b):
            b.trace(OFF_OP, units=len(units))
        return dict(NOT_GO)
    if _halted(b) or len(units) < MIN_UNITS:
        _clear(b)
        return dict(NOT_GO)
    answers = answers_dir(b)
    shutil.rmtree(answers, ignore_errors=True)   # 前の起動の答えを今の判定の答えに数えない
    answers.mkdir(parents=True, exist_ok=True)
    head = _head(judgment)
    files = []
    for n, u in enumerate(units, 1):
        path = b.work(f"{BRIEF_DIR}/unit-{n}.md")
        body = "\n\n".join([head, UNIT_HEAD.format(n=n),
                            f"```json\n{json.dumps(_unit_row(u), ensure_ascii=False, indent=1)}\n```",
                            UNIT_ASK.format(n=n, answer=answer_file(b, n),
                                            schema=json.dumps(unit_schema(), ensure_ascii=False))])
        path.write_text(body + "\n", encoding="utf-8")
        files.append(f"- 単位 {n}: {path}")
    syn = b.work(f"{BRIEF_DIR}/synergy.md")
    rows = "\n".join(f"- 単位 {n}: {json.dumps(_unit_row(u), ensure_ascii=False)}" for n, u in enumerate(units, 1))
    syn.write_text("\n\n".join([head, SYNERGY_HEAD, "### 単位の全部\n\n" + rows,
                                SYNERGY_ASK.format(answer=synergy_file(b), schema=json.dumps(synergy_schema(), ensure_ascii=False))])
                   + "\n", encoding="utf-8")
    files.append(f"- 相乗り: {syn}")
    prompt = b.work(f"{BRIEF_DIR}/prompt.md")
    reply = {k: v for k, v in output_format().items() if k != "description"}
    prompt.write_text("\n\n".join([AGG, "下請けのファイル:\n" + "\n".join(files),
                                   f"{AGG_REPLY}\n\n```json\n{json.dumps(reply, ensure_ascii=False)}\n```"]) + "\n", encoding="utf-8")
    _write_json(b.work(TREE_FILE), core_accept.tree_state(pathlib.Path(repo)))
    _write_json(b.work(PLAN_FILE), {"units": [{"n": n, "key": u["key"]} for n, u in enumerate(units, 1)], "answers": str(answers)})
    _write_json(b.work(VERIFY_FILE), _initial(units))
    return {"ok": True, "go": True, "prompt_file": str(prompt)}


def _load(path: pathlib.Path, schema: dict) -> tuple:
    """(答え, 誤りの行)"""
    if not path.is_file():
        return None, [f"答えのファイルが無い（{path}）"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return None, [f"答えのファイルが JSON として読めない（{' '.join(str(e).split())}）"]
    errs = validate_schema(doc, schema)
    return (None, errs) if errs else (doc, [])


def _check_unit(b, n: int, key: str) -> dict:
    got, errs = _load(answer_file(b, n), unit_schema())
    if got is not None:
        if got["unit"] != n:
            errs.append(f"$.unit: {n} でない（{got['unit']}）")
        if got["verdict"] == "not_root" and len(str(got.get("real_root") or "").strip()) < 4:
            errs.append("$.real_root: not_root なのに本当の根が書かれていない")
    if errs:
        return {"n": n, "key": key, "state": UNVERIFIED, "errors": errs}
    return {"n": n, "key": key, "state": CHECKED, **{k: v for k, v in got.items() if k != "unit"}}


def _check_synergy(b, keys: dict) -> dict:
    got, errs = _load(synergy_file(b), synergy_schema())
    if got is not None:
        nums = [x for row in got["duplicates"] + got["relations"] for x in row["units"]]
        nums += [x for row in got["order"] for x in (row["first"], row["then"])]
        errs += [f"単位 {x} は無い（単位は 1〜{len(keys)}）" for x in sorted(set(nums)) if x not in keys]
        errs += [f"$.duplicates・relations: 同じ単位だけを並べた行（{row['units']}）" for row in got["duplicates"] + got["relations"]
                 if len(set(row["units"])) < 2]
    if errs:
        return {"state": UNVERIFIED, "errors": errs}

    def group(rows):
        return [{"units": [keys[x] for x in dict.fromkeys(r["units"])], "why": r["why"]} for r in rows]
    return {"state": CHECKED, "why": got["why"], "duplicates": group(got["duplicates"]), "relations": group(got["relations"]),
            "order": [{"first": keys[r["first"]], "then": keys[r["then"]], "why": r["why"]} for r in got["order"]]}


def merge_on(b, repo) -> dict:
    """まとめの芯。返り {ok, verify_file, verified, unverified}。番号の控えが無ければ（支度が go 偽）空"""
    plan = _read_json(b.work(PLAN_FILE))
    if not isinstance(plan, dict) or not isinstance(plan.get("units"), list):
        return dict(EMPTY_MERGE)
    snap = _read_json(b.work(TREE_FILE))
    moved = core_accept.tree_moved({k: snap[k] for k in core_accept.TREE_KEYS}, pathlib.Path(repo)) \
        if isinstance(snap, dict) and all(k in snap for k in core_accept.TREE_KEYS) else ["作業ツリーの写しが読めない"]
    keys = {r["n"]: r["key"] for r in plan["units"]}
    rows = [_check_unit(b, n, key) for n, key in keys.items()]
    syn = _check_synergy(b, keys)
    path = b.work(VERIFY_FILE)
    _write_json(path, {"units": rows, "synergy": syn})
    verified = sum(r["state"] == CHECKED for r in rows)
    if not _halted(b):
        b.trace(TRACE_OP, verified=verified, unverified=len(rows) - verified, synergy=syn["state"] == CHECKED)
        if moved:
            b.stop("判定の裏取りの束ね役か下請けが作業ツリーを変えた（読むだけの役）: " + "・".join(moved), by=STOP_BY)
    return {"ok": True, "verify_file": str(path), "verified": verified, "unverified": len(rows) - verified}


def prep(board_dir, repo, verify: str = "") -> dict:
    """節 verify-prep。ラインの盤面が無ければ（ブロックを単独で回した）go 偽。verify は入力の切り替えの語（空は on）"""
    d = pathlib.Path(board_dir)
    script_io.switch_on(verify, "verify")   # 知らない語は盤面を開く前に落とす
    if not judgetake.on_line(d):
        return dict(NOT_GO)
    b = entry.open_board(d, allow_halted=True)
    return prep_on(b, _read_json(d / core_accept.JUDGMENT_FILE), repo, verify)


def merge(board_dir, repo) -> dict:
    """節 verify-merge。ラインの盤面が無ければ空"""
    d = pathlib.Path(board_dir)
    if not judgetake.on_line(d):
        return dict(EMPTY_MERGE)
    return merge_on(entry.open_board(d, allow_halted=True), repo)
