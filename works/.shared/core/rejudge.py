"""同じ周の再審（修正役が判定に異議を出した時、同じ run の中で判定役に考え直させる）の芯。rejudge 設計の 4.6 の口。

段 1（写しの graphloops 0.21.0 の規則）と段 2（本線 3-6 を写し直した後）で口は変えない。どちらの形かは写しの規則から引き
（shape）、節の数・名・順も写しから引く（passes）。works が持つのは節から役の名への対応（ROLE_OF）だけ。

- route:          盤面を settle し、ready の再審の節のうち最初の 1 つの役を返す。判定役の会話の続きで起こす役
                  （cont == "judge"）なら、起こす前に毎回 session_ready で会話を確かめ、確かめられなければ盤面を止める
                  （by works:rejudge-session）。黙って新しい会話で回す道は無い
- session_ready:  包みの judge.id が UUID 1 つ・包みの起動の記録の最後の判定役の行が同じ id・その起動が盤面を作った後
- snap:           役を起こす前の作業ツリーの写し（読むだけの役が変えていないかを take が比べる）
- render:         engine と同じ描き方（rolekit.render_body）で指示書を $B/prompts/r<N>/<節>.md に
- prep:           描く → 1 回目の試行の前だけ単位の写し（rejudge-units-before-<役>.json）→ 起こした印（mark_launched）
- take:           作業ツリーの比べ → class_query の例で問いを試して例を外す（querytest。例は query-examples.json に足す）→ 盤面の done（写しの schema・post_check・writes・check_record）。写しの AnswerReject だけを
                  {ok: False, reason} にして返し、他の Reject・BoardGap は投げる（回す側の誤り）。通れば単位の差分を 1 行
- diff_units:     前後の単位を key で比べ、異議に名指されていない変化（unnamed_changed）とラベルを下げた単位（lowered）を出す。柵は足さない
- unsettled:      決着しなかった異議の文（段 1 は loop.rejudge_requested、段 2 は写しの _rejudge_trail）
- collect:        出口。回した後も再審の節が ready のまま（輪が 3 回とも拒まれた・engine の順とずれた）なら盤面を止める（by works:rejudge）
- actual_costs:   継いだ起動の表示の費用から、同じ会話のそれまでの実額を引く（再開した会話の total_cost_usd は累積）

盤面は entry.open_board（Task 3）で開き、印は node_marker（Task 2）で付ける。まだこの枝に無い部品の代わり（入った時に差し替える）:
- 包みの置き場: adapter.session_path・launches_path・read_launches（Task 5）が在ればそれ、無ければ _AdapterShim（同じ式。家の既定も
  ${XDG_STATE_HOME:-~/.local/state}/works/adapter）
- 受け付けの口: entry.take（Task 9）が入ったら take はそれに委ねる
- 指示書: 写し（graphloops/）の指示書は TDD 版の tdd/ だけなので、同じ commit から写した gl-prompts/ を使う。写しに同じ指示書が在れば写しを先に使う
"""
import datetime
import functools
import json
import os
import pathlib
import re
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap, DiskBoard, graph_expanded, rules_module  # noqa: E402  （写しの engine を sys.path に入れる。engine より先に）
import engine.util as _util  # noqa: E402
from engine.rules import validator_module  # noqa: E402
from engine.util import TERMINAL_STATUS, AnswerReject, now, safe_name  # noqa: E402
import accept as _accept  # noqa: E402
import entry  # noqa: E402
import node_marker  # noqa: E402
import querytest  # noqa: E402
import rolekit  # noqa: E402
import script_io  # noqa: E402

CONT = "judge"   # 再審の役が続きとして起きる会話（包みの印の continue=）
# 写しの再審の節 → 役の名（YAML の節 id と包みの印の名）。数と順は持たない（passes が写しから引く）
ROLE_OF = {"p2.rejudge": "rejudge", "p3.rejudge_reply": "rejudge-reply", "p2.rejudge2": "rejudge2",
           "p3.rejudge_reply2": "rejudge-reply2", "p2.rejudge3": "rejudge3", "p2.rejudge_third": "rejudge-third"}
POST_CHECK = "rejudge_output"   # 0.21.0 の写しで再審の節を見分ける印（写しの post_check の名）
STOP_BY_SESSION = "works:rejudge-session"
STOP_BY = "works:rejudge"
# 盤面の今の周の作業ファイル（b.work）
SNAPSHOT_NAME = "rejudge-snapshot.json"
SESSION_NAME = "rejudge-session.json"
DIFF_NAME = "rejudge-diff.json"
REJECTS_NAME = "rejudge-rejects.json"
EXIT_NAME = "rejudge-exit.json"
READS_NAME = "reads-rejudge.json"
BEFORE_PREFIX = "rejudge-units-before-"
# 輪（loop_group）の max_iterations と同じ数。受け付けがこの数だけ拒んだら give_up（done）を出し、輪を失敗で抜けさせずに
# collect へ渡す（Archon は max_iterations に達した輪を failed にし、後ろの節を全部止めるため。裁定 R50）。
# tests/test_blk_rejudge.py が YAML の max_iterations と同じかを見る
GIVE_UP_AFTER = 3
REJECT_HEADING = "## 前の回の受け付けが拒んだ理由"
ADAPTER_HOME_ENV = "WORKS_ADAPTER_HOME"
PROMPTS_COPY = rolekit.PROMPTS_COPY
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# 修正役に貼った番号の書き方（no N・No.N・#N・N 番）。全角の数字も \d に当たる
_NUMBERS = (re.compile(r"(?<![A-Za-z])no\.?\s*(\d+)", re.IGNORECASE), re.compile(r"[#＃]\s*(\d+)"), re.compile(r"(\d+)\s*番"))


# ---------------------------------------------------------------- まだこの枝に無い部品の代わり
class _AdapterShim:
    """包み（adapter.py、Task 5）の置き場の式の写し。包みが入ったら adapter_module は本物を返す"""

    @staticmethod
    def _home(home_dir=None):
        if home_dir is not None:
            return pathlib.Path(home_dir)
        if os.environ.get(ADAPTER_HOME_ENV):
            return pathlib.Path(os.environ[ADAPTER_HOME_ENV])
        state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.environ.get("HOME") or os.path.expanduser("~"),
                                                                  ".local", "state")
        return pathlib.Path(state) / "works" / "adapter"

    @staticmethod
    def cwd_key(cwd):
        import hashlib
        return hashlib.sha256(os.path.realpath(str(cwd)).encode("utf-8")).hexdigest()[:16]

    @classmethod
    def session_path(cls, cwd, node, home_dir=None):
        return cls._home(home_dir) / "sessions" / cls.cwd_key(cwd) / f"{node}.id"

    @classmethod
    def launches_path(cls, cwd, home_dir=None):
        return cls._home(home_dir) / "launches" / f"{cls.cwd_key(cwd)}.jsonl"

    @classmethod
    def read_launches(cls, cwd, home_dir=None):
        try:
            text = cls.launches_path(cwd, home_dir).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        out = []
        for ln in text.splitlines():
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out


def adapter_module():
    """包みの芯（adapter.py）。まだ無ければ同じ式の _AdapterShim"""
    try:
        import adapter
    except ImportError:
        return _AdapterShim
    return adapter


def open_board(board_dir, *, repo=None, allow_halted=False) -> DiskBoard:
    """盤面を開く（entry.open_board: ラインの表・表の sha・board_hook）。repo を渡せば写しの git の置き場（util.GIT_CWD）をそこに
    向ける（entry.open_board は盤面の inputs.cwd に向ける）"""
    b = entry.open_board(board_dir, allow_halted=allow_halted)
    if repo is not None:
        _util.GIT_CWD = str(pathlib.Path(repo).resolve())
    return b


# ---------------------------------------------------------------- 写しの形
@functools.lru_cache(maxsize=None)
def _copy_rules():
    return rules_module()


@functools.lru_cache(maxsize=None)
def _copy_graph():
    return graph_expanded()


def shape(rules=None) -> str:
    """写しの規則の形: REJUDGE_PASSES が在れば "3-6"、REJUDGE_MAX だけなら "0.21.0"。どちらも無ければ BoardGap"""
    rules = _copy_rules() if rules is None else rules
    if hasattr(rules, "REJUDGE_PASSES"):
        return "3-6"
    if hasattr(rules, "REJUDGE_MAX"):
        return "0.21.0"
    raise BoardGap("写しの規則に REJUDGE_PASSES も REJUDGE_MAX も無い——同じ周の再審の形が分からない（写しを見直す）")


def passes(rules=None, graph=None) -> list:
    """再審の節をラインの順に [{node, role, cont, source}]。source はその節が答える異議を書く節。
    3-6 は写しの REJUDGE_PASSES（回ごとの (異議を書く節, 再審の節)）と REJUDGE_THIRD から、0.21.0 は写しの post_check が
    rejudge_output の節を graph の順に。cont は graph で判定役の会話を継ぐ節（same_context_as）だけ "judge"。
    写しの節が ROLE_OF に無い・graph に無いなら BoardGap"""
    rules = _copy_rules() if rules is None else rules
    nodes = (_copy_graph() if graph is None else graph)["nodes"]
    if shape(rules) == "3-6":
        order, prev = [], None
        for k in sorted(rules.REJUDGE_PASSES):
            src, judge = rules.REJUDGE_PASSES[k]
            if prev is not None:
                order.append((src, prev))   # 再異議の節は前の再審の答えに言い返す
            order.append((judge, src))
            prev = judge
        order.append((rules.REJUDGE_THIRD, prev))
    else:
        order = [(nid, (n.get("deps") or [None])[0]) for nid, n in nodes.items() if n.get("post_check") == POST_CHECK]
    if not order:
        raise BoardGap("写しに再審の節が 1 つも無い")
    missing = [nid for nid, _ in order if nid not in ROLE_OF]
    if missing:
        raise BoardGap(f"写しの再審の節 {missing} が rejudge.ROLE_OF に無い（写し直しで増えた節に役の名を付ける）")
    absent = [nid for nid, _ in order if nid not in nodes]
    if absent:
        raise BoardGap(f"写しの規則が名指す再審の節 {absent} が graph に無い")
    return [{"node": nid, "role": ROLE_OF[nid], "cont": CONT if "same_context_as" in nodes[nid] else None, "source": src}
            for nid, src in order]


def node_of(role, rules=None, graph=None) -> str:
    for p in passes(rules, graph):
        if p["role"] == role:
            return p["node"]
    raise BoardGap(f"役 {role!r} は写しの再審の節に無い")


def output_format(node) -> dict:
    """役の output_format: 写しの schema（accept.role_schema）に印 works-node: <役>[ continue=judge] を付けた物"""
    p = next((x for x in passes() if x["node"] == node), None)
    if p is None:
        raise BoardGap(f"節 {node} は写しの再審の節に無い")
    return node_marker.mark(_accept.role_schema(node), p["role"], cont=p["cont"])


def unit_fields(graph=None, node=None) -> list:
    """再審が単位を置き換える時に残す欄（graph の writes の to: units の pick）。単位の差分はこの欄だけを比べる"""
    g = _copy_graph() if graph is None else graph
    nid = node or passes(graph=g)[0]["node"]
    for w in g["nodes"][nid].get("writes") or []:
        if w.get("to") == "units" and w.get("pick"):
            return list(w["pick"])
    raise BoardGap(f"節 {nid} の writes に units の pick が無い")


# ---------------------------------------------------------------- 回す
def _parse_time(s):
    try:
        t = datetime.datetime.fromisoformat(str(s))
    except ValueError:
        return None
    return t if t.tzinfo else None


def session_ready(b, repo) -> dict:
    """判定役の会話を継げるか。{ok, path, id, launch_at, why}。条件（全部）:
    1. 包みの judge.id が在り、中身が UUID 1 つ
    2. 包みの起動の記録（同じ cwd）の node == judge の最後の行の session.id が同じ id（fork なら新しい id が書かれる）
    3. その行の at が盤面を作った時（state.created）より後（前の run の判定役を継がない）"""
    ad = adapter_module()
    path = ad.session_path(repo, CONT)
    got = {"ok": False, "path": str(path), "id": None, "launch_at": None, "why": ""}
    try:
        sid = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        got["why"] = f"判定役の会話の id のファイル {path} が無い（包みを通らない run か、判定役に印が無い）"
        return got
    if not _UUID.fullmatch(sid):
        got["why"] = f"{path} の中身が UUID 1 つでない（{sid[:60]!r}）"
        return got
    got["id"] = sid
    rows = [r for r in ad.read_launches(repo) if r.get("node") == CONT]
    if not rows:
        got["why"] = f"包みの起動の記録（{ad.launches_path(repo)}）に判定役の行が無い"
        return got
    last = rows[-1]
    row_id = (last.get("session") or {}).get("id")
    if row_id != sid:
        got["why"] = f"包みの起動の記録の最後の判定役の会話 {row_id} が id のファイルの {sid} と違う"
        return got
    at, created = _parse_time(last.get("at")), _parse_time(b.state.get("created"))
    if at is None or created is None:
        got["why"] = f"時刻が読めない（起動 {last.get('at')!r}・盤面 {b.state.get('created')!r}）"
        return got
    if not at > created:
        got["why"] = f"判定役の起動（{last.get('at')}）が盤面を作る前（{b.state.get('created')}）——前の run の会話は継がない"
        return got
    got.update(ok=True, launch_at=last.get("at"))
    return got


def _write_json(path, obj):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _read_json(path, default=None):
    path = pathlib.Path(path)
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"{path} を読めない: {e}") from None


def _stopped(b):
    st = b.state
    return bool(st.get("halted") or st.get("stop") or st.get("status") in TERMINAL_STATUS)


def route(board_dir, repo) -> dict:
    """次に回す再審の役。{next: 役 | "", node, why, stopped}。盤面が止まっていれば stopped。判定役の続きの役なら先に
    session_ready を見て、偽なら盤面を止めて stopped（役を起こさない）。通れば rejudge-session.json に確かめた会話を書く"""
    b = open_board(board_dir, repo=repo)
    if _stopped(b):
        by = (b.state.get("stop") or b.state.get("halted") or {}).get("by") or b.state.get("status")
        return {"next": "", "node": "", "why": f"盤面は止まっている（{by}）", "stopped": True}
    ready = b.settle()["ready"]
    ps = passes(b.rules, b.graph)
    hit = next((p for p in ps if p["node"] in ready), None)
    if hit is None:
        why = "・".join(f"{p['node']}: {b.rd['na'].get(p['node']) or b.node_state(p['node'])}" for p in ps)
        return {"next": "", "node": "", "why": f"再審の節が ready に無い（{why}）", "stopped": False}
    if hit["cont"] == CONT:
        s = session_ready(b, repo)
        if not s["ok"]:
            b.stop(f"判定役の会話が見つからない（{s['why']}）。再審せずに止めた", by=STOP_BY_SESSION)
            return {"next": "", "node": hit["node"], "why": s["why"], "stopped": True}
        _write_json(b.work(SESSION_NAME), {"id": s["id"], "path": s["path"], "launch_at": s["launch_at"]})
    return {"next": hit["role"], "node": hit["node"], "why": f"{hit['node']} が ready", "stopped": False}


def snap(board_dir, repo) -> dict:
    """役を起こす前の作業ツリーの姿（accept.tree_state。R47）を rejudge-snapshot.json に（git が効かなければ写しの Reject）"""
    b = open_board(board_dir, repo=repo)
    p = _write_json(b.work(SNAPSHOT_NAME), _accept.tree_state(pathlib.Path(repo)))
    return {"ok": True, "snapshot_file": str(p)}


# ---------------------------------------------------------------- 描く・印
def prompt_graph_path(b, n) -> pathlib.Path:
    """node_prompt に渡す graph のパス（rolekit.prompt_graph_path。写しが指示書を持てば写しの graph、無ければ gl-prompts/）"""
    return rolekit.prompt_graph_path(b, n, PROMPTS_COPY)


def render(b, nid) -> pathlib.Path:
    """engine の emit_instance と同じ描き方（rolekit.render_body）で指示書を $B/prompts/r<N>/<節>.md に書く（cap なし。
    指示書は役がファイルで読む）。番号の控え（pointers）が在れば instance に置く。描けない（reads に無い穴・盤面の欄の欠け）は BoardGap。
    言語の 1 行は置かない（engine と同じ本文のまま。prep が末尾に足す）"""
    inst = b.rd["instances"].get(nid)
    prompt, snap_ = rolekit.render_body(b, nid, prompts_dir=PROMPTS_COPY, lang=False)
    p = b.dir / "prompts" / f"r{b.round}" / (safe_name(nid) + ".md")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(prompt, encoding="utf-8")
    if snap_ and inst.get("pointers") != snap_:
        inst["pointers"] = snap_
        b.save()
    return p


def _pass_of(b, nid):
    p = next((x for x in passes(b.rules, b.graph) if x["node"] == nid), None)
    if p is None:
        raise BoardGap(f"節 {nid} は写しの再審の節に無い")
    return p


def objection(b, nid) -> str:
    """その回の異議の文。段 1 は今の周の loop.rejudge_requested、段 2 は異議を書いた節の出力の rejudge_requested。
    第三の目（会話を継がない最後の節）は、その周の異議を全部つないだ文"""
    ps = passes(b.rules, b.graph)
    if shape(b.rules) == "0.21.0":
        r = b.loop_state.get("rejudge_requested") or {}
        return (r.get("text") or "") if r.get("round") == b.round else ""
    if nid == ps[-1]["node"]:
        srcs = [p["source"] for p in ps if p["cont"] == CONT]
    else:
        srcs = [_pass_of(b, nid)["source"]]
    texts = [(b.output_of_round(s, b.round) or {}).get("rejudge_requested") for s in srcs]
    return "\n".join(t for t in texts if t)


def numbered_keys(b) -> list:
    """修正役に貼った単位の番号の並び（i 番目 = 番号 i+1 の key）。修正役の instance の番号の控え（pointers の from が
    record.units の欄）が在ればそれ、無ければ今の単位の並び（engine の番号の振り方と同じ順）"""
    src = passes(b.rules, b.graph)[0]["source"]
    inst = b.rd["instances"].get(src) or {}
    for i, r in enumerate(b.nodes.get(src, {}).get("pointers") or []):
        snap_ = inst.get("pointers") or []
        if r.get("from") == ["record.units"] and i < len(snap_) and snap_[i].get("at") == r.get("at"):
            return list(snap_[i]["names"])
    return [u.get("key") for u in b.record.get("units") or []]


def prep(board_dir, role, repo) -> dict:
    """役を起こす前の支度: 指示書を描き、1 回目の試行の前だけ単位の写し（と異議の文・番号の並び）を置き、起こした印を置く。
    返り {prompt_file, attempt, out_path, node, already}。拒否の後の出し直しは同じ試行なので印は前の物（already: true）。
    この周にこの節の拒否が在れば、最後の拒否の文を指示書の頭に置く（REJECT_HEADING の節）。末尾に言語の 1 行（rolekit.lang_line）"""
    b = open_board(board_dir, repo=repo)
    nid = node_of(role, b.rules, b.graph)
    path = render(b, nid)
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + rolekit.lang_line(b.state.get("inputs")) + "\n",
                    encoding="utf-8")
    last = _rejects(b, nid)[-1:]
    if last:
        # 拒否の文は指示書のファイルに書く（役は Read で読む）。$LOOP_PREV で指示に貼ると、文の中の $<節>.output.<欄> を
        # Archon が置き換え直して輪ごと落ちる（裁定 R44）。文は役の返答の頭や git のパスを含みうる
        path.write_text(f"{REJECT_HEADING}\n\n前の回の返答は受け付けで拒まれた。下の理由のところを直した返答を丸ごと出し直せ"
                        f"（直した所だけを返すな）:\n\n```text\n{last[0]['reason']}\n```\n\n---\n\n"
                        + path.read_text(encoding="utf-8"), encoding="utf-8")
    inst = b.rd["instances"][nid]
    before = b.work(f"{BEFORE_PREFIX}{role}.json")
    if not before.exists():
        _write_json(before, {"node": nid, "units": b.record.get("units") or [], "objection": objection(b, nid),
                             "numbered_keys": numbered_keys(b)})
    m = b.mark_launched(nid, inst["attempts"])   # 描いた試行に印（盤面は印の無い返答を受けない）
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid,
            "already": m["already"]}


# ---------------------------------------------------------------- 受け付け
def _rejects(b, nid):
    return [r for r in _read_json(b.work(REJECTS_NAME), []) if r.get("node") == nid]


def _reject(b, nid, reason):
    """拒否の文を rejudge-rejects.json に積んで {ok: False, done, give_up, reason} を返す。この周のこの節の拒否が
    GIVE_UP_AFTER 回に達したら give_up（done）——輪はそこで抜け、collect が最後の拒否の文で盤面を止める"""
    rows = _read_json(b.work(REJECTS_NAME), [])
    inst = b.rd["instances"].get(nid) or {}
    rows.append({"node": nid, "attempt": inst.get("attempts", 1), "at": now(), "reason": reason})
    _write_json(b.work(REJECTS_NAME), rows)
    give_up = sum(1 for r in rows if r.get("node") == nid) >= GIVE_UP_AFTER
    return {"ok": False, "done": give_up, "give_up": give_up, "reason": reason, "node": nid, "verdict": ""}


def take(board_dir, nid, reply, repo, *, snapshot_name=SNAPSHOT_NAME) -> dict:
    """役の返答を受け付ける（entry.take と同じ約束）。順: 作業ツリーを snapshot_name の写しと比べる → 盤面の done
    （写しの schema → post_check → writes → check_record → settle）。拒否（写しの AnswerReject と作業ツリーの変化）は
    {ok: False, done, give_up, reason} で返し（done は GIVE_UP_AFTER 回目の拒否で真。輪の抜ける条件）、盤面の層のファイルは書かない（拒否の文は作業ファイル rejudge-rejects.json に積む）。
    ほかの Reject（止めた run など）・BoardGap は投げる。通ったら、単位を書く節なら単位の差分を rejudge-diff.json に 1 行足す"""
    b = open_board(board_dir, repo=repo)
    p = _pass_of(b, nid)
    saved = _read_json(b.work(snapshot_name))
    if not isinstance(saved, dict) or not set(_accept.TREE_KEYS) <= set(saved):
        raise BoardGap(f"作業ツリーの写し {b.work(snapshot_name)} が無い・形が違う（rj-snap が先に走る）")
    moved = _accept.tree_moved({k: saved[k] for k in _accept.TREE_KEYS}, pathlib.Path(repo))   # 共通の比べ（R47）
    if moved:
        return _reject(b, nid, "読むだけの役が作業ツリーを変えた: 再審の役は読むだけの役で、作業ツリー・HEAD・枝・git が無視する"
                               "ファイルを変えてはいけない（" + "・".join(moved) + "）")
    before_doc = _read_json(b.work(f"{BEFORE_PREFIX}{p['role']}.json"))
    writes_units = "units" in ((b.nodes[nid].get("schema") or {}).get("properties") or {})
    if writes_units and before_doc is None:
        raise BoardGap(f"{p['role']} の前の単位の写しが無い（prep が先に走る）")
    examples = {}
    if nid in querytest.NODES and isinstance(reply, dict):
        is_open = validator_module(b).is_open
        errs = querytest.problems(reply.get("units"), is_open)
        if errs:
            return _reject(b, nid, "class_query の例が問いと合わない: " + "; ".join(errs))
        reply, examples = querytest.split(reply, is_open)   # 写しの型は例と理由の欄を持たない
    try:
        progress = b.done(nid, reply)
    except AnswerReject as e:
        return _reject(b, nid, str(e))   # 記憶の入れ物は汚れうるが、使うのは周の番号と試行の数だけ（受け付けの前から変わらない）
    if examples:
        querytest.save(board_dir, examples)
    verdict = reply.get("verdict", "") if isinstance(reply, dict) else ""
    if writes_units:
        row = {"round": b.round, "pass": p["role"], "node": nid, "verdict": verdict,
               **diff_units(before_doc["units"], b.record.get("units") or [], before_doc.get("objection") or "",
                            before_doc.get("numbered_keys") or [], unit_fields(b.graph, nid))}
        rows = _read_json(b.work(DIFF_NAME), [])
        rows.append(row)
        _write_json(b.work(DIFF_NAME), rows)
    return {"ok": True, "done": True, "give_up": False, "reason": "。".join(progress["notes"]), "node": nid,
            "verdict": verdict}


# ---------------------------------------------------------------- 単位の差分
def _named_numbers(text):
    got = set()
    for rx in _NUMBERS:
        for m in rx.finditer(text or ""):
            got.add(int(m.group(1)))
    return got


def diff_units(before, after, objection_text, numbered, fields=None) -> dict:
    """前後の単位を key で比べる。{changed: [{key, kind, field?, before?, after?, named}], unnamed_changed: [key], lowered: [key]}
    - kind: changed（fields の欄が変わった。欄ごとに 1 行）・added・removed
    - named: key が異議の文に部分一致で現れるか、修正役に貼った番号（numbered の i 番目が番号 i+1）が no N・#N・N 番の形で
      現れるか。名指しを読み取れなければ偽（変化は争点外として強調する側に倒す）
    - lowered: block から他のラベルに下げた単位（指示書は禁じるが写しの規則は拒まない）"""
    fields = [f for f in (fields or unit_fields()) if f != "key"]
    bmap = {u.get("key"): u for u in before or []}
    amap = {u.get("key"): u for u in after or []}
    nums = _named_numbers(objection_text)
    by_number = {numbered[n - 1] for n in nums if 1 <= n <= len(numbered or [])}

    def named(k):
        return bool(objection_text) and (k in objection_text or k in by_number)

    def pick(u):
        return {f: u[f] for f in ["key", *fields] if f in u}

    changed, unnamed, lowered = [], [], []
    for k in [*bmap, *(k for k in amap if k not in bmap)]:
        nm = named(k)
        rows = []
        if k not in amap:
            rows.append({"key": k, "kind": "removed", "before": pick(bmap[k]), "named": nm})
        elif k not in bmap:
            rows.append({"key": k, "kind": "added", "after": pick(amap[k]), "named": nm})
        else:
            for f in fields:
                if bmap[k].get(f) != amap[k].get(f):
                    rows.append({"key": k, "kind": "changed", "field": f, "before": bmap[k].get(f), "after": amap[k].get(f),
                                 "named": nm})
            if bmap[k].get("label") == "block" and amap[k].get("label") != "block":
                lowered.append(k)
        changed += rows
        if rows and not nm:
            unnamed.append(k)
    return {"changed": changed, "unnamed_changed": unnamed, "lowered": lowered}


# ---------------------------------------------------------------- 出口
def unsettled(b) -> dict:
    """決着しなかった異議 {text, settled}。段 1 は今の周の loop.rejudge_requested が残っていれば未決（写しの規則は採る・退けるで
    降ろす）。段 2 は写しの _rejudge_trail を今の周の出力に当てる"""
    if shape(b.rules) == "0.21.0":
        r = b.loop_state.get("rejudge_requested") or {}
        if r.get("round") == b.round and r.get("text"):
            return {"text": r["text"], "settled": False}
        return {"text": "", "settled": True}
    text, settled = b.rules._rejudge_trail(lambda nid: b.output_of_round(nid, b.round))
    return {"text": text or "", "settled": bool(settled)}


def collect(board_dir) -> dict:
    """ブロックの出口 {ok, reason, passes, verdicts, unsettled, new_open_units, unnamed_changed, diff_file, reads_file}。
    同じ物を rejudge-exit.json に書く。回した後も再審の節が ready のまま（輪が 3 回とも拒まれた・engine の順と段の順が
    ずれた）なら盤面を止めて（by works:rejudge）ok: False。盤面が既に止まっている（会話を確かめられなかった）なら ok: True
    （次の境の節が止まった盤面を見てラインを止める）"""
    b = open_board(board_dir, allow_halted=True)
    ps = passes(b.rules, b.graph)
    ok, reason = True, ""
    if not _stopped(b):
        waiting = [p["node"] for p in ps if p["node"] in b.settle()["ready"]]
        if waiting:
            ok = False
            nid = waiting[0]
            rejects = _rejects(b, nid)
            if (b.rd["instances"].get(nid) or {}).get("launched_at") and rejects:
                reason = f"{nid} の返答が {len(rejects)} 回とも受け付けで拒まれた（最後の拒否: {rejects[-1]['reason']}）"
            else:
                reason = (f"回した後も再審の節 {waiting} が ready のまま（engine の順とブロックの段の順がずれた——"
                          "写し直しで増えた節の段が無い）")
            b.stop(reason, by=STOP_BY)
    done = [p for p in ps if p["node"] in b.rd["done"]]
    verdicts = [(b.output_of_round(p["node"], b.round) or {}).get("verdict", "") for p in done]
    rows = _read_json(b.work(DIFF_NAME), [])
    first = next((d for d in (_read_json(b.work(f"{BEFORE_PREFIX}{p['role']}.json")) for p in ps) if d), None)
    new_open = []
    if first is not None:
        V = validator_module(b)
        was = {u.get("key"): u for u in first["units"]}
        new_open = [u["key"] for u in b.record.get("units") or []
                    if V.is_open(u) and not (u["key"] in was and V.is_open(was[u["key"]]))]
    unnamed = list(dict.fromkeys(k for r in rows for k in r.get("unnamed_changed") or []))
    diff_p, reads_p = b.work(DIFF_NAME), b.work(READS_NAME)
    out = {"ok": ok, "reason": reason, "passes": len(done), "verdicts": verdicts, "unsettled": unsettled(b),
           "new_open_units": new_open, "unnamed_changed": unnamed, "diff_file": str(diff_p) if diff_p.exists() else "",
           "reads_file": str(reads_p) if reads_p.exists() else ""}
    _write_json(b.work(EXIT_NAME), out)
    return out


# ---------------------------------------------------------------- ブロックのスクリプトの入口
ARTIFACTS_ENV = script_io.ARTIFACTS_ENV


script_main = rolekit.script_main   # blk-rejudge のスクリプトの入口（rolekit。環境変数の欠け・BoardGap・写しの Reject は 2）


def refuse(board_dir, nid, reason) -> dict:
    """返答を受け付けの前に拒む（読めない返答）。拒否の文は take の拒否と同じく rejudge-rejects.json に積む"""
    return _reject(open_board(board_dir), nid, reason)


parse_reply = rolekit.parse_reply   # 読めない返答は (None, 理由)。拒否は rejudge-rejects.json に積んで give_up を数える（refuse）


# ---------------------------------------------------------------- 費用
def actual_costs(launches, shown) -> list:
    """起動ごとの実額。launches は包みの起動の行（{at, node, session: {mode, id, of?, from?}}。順は問わない。拒んだ起動
    mode refused は子を起こしていないので除く）、shown は Archon の表示（{node: 印の名, cost_usd}。節ごとに時刻の順）。
    同じ印の名の起動と表示を順に組む。会話 id ごとに「その会話のそれまでの実額の合計」を持ち:
    - continued（包みが判定役の会話を継いだ）: 実額 ＝ 表示 − その会話の合計
    - sdk-fork: 実額 ＝ 表示 − 元の会話（from）の合計。新しい会話の合計は表示
    - それ以外（new・sdk-resume・sdk-session）: 実額 ＝ 表示（Archon が知っている再開は Archon が引く）
    引けない（表示が無い・元の会話の合計が取れない）起動は actual None・note に「取れない」。表示が 1 つも無ければ 1 行だけ返す。
    返り [{node, at, session, mode, shown, actual, note}]"""
    vals = [s for s in (shown or []) if isinstance(s, dict) and isinstance(s.get("cost_usd"), (int, float))]
    if not vals:
        return [{"node": None, "at": None, "session": None, "mode": None, "shown": None, "actual": None,
                 "note": "費用: 取れない（Archon の出来事に cost_usd が無い）"}]
    queues = {}
    for s in shown:
        queues.setdefault(s.get("node"), []).append(s.get("cost_usd") if isinstance(s.get("cost_usd"), (int, float)) else None)
    rows = [r for r in launches or [] if (r.get("session") or {}).get("mode") != "refused"]
    rows.sort(key=lambda r: _parse_time(r.get("at")) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc))
    totals, out = {}, []
    for r in rows:
        s = r.get("session") or {}
        mode, sid = s.get("mode"), s.get("id")
        q = queues.get(r.get("node")) or []
        v = q.pop(0) if q else None
        actual, note = None, ""
        if v is None:
            note = "費用: 取れない（この起動の表示が無い）"
            totals[sid] = None
        elif mode in ("continued", "sdk-fork"):
            base_id = sid if mode == "continued" else s.get("from")
            base = totals.get(base_id)
            if base is None:
                note = f"費用: 取れない（元の会話 {base_id} の費用が分からず、累積を引けない）"
                totals[sid] = None
            else:
                actual = round(v - base, 6)
                note = f"会話の累積を引いた（表示 {v} − それまでの累積 {round(base, 6)}）"
                totals[sid] = v
        else:
            actual = v
            prev = totals.get(sid, 0)
            totals[sid] = None if prev is None else prev + v
        out.append({"node": r.get("node"), "at": r.get("at"), "session": sid, "mode": mode, "shown": v, "actual": actual,
                    "note": note})
    return out


def strip_mark(schema):
    """印の description を外した写し（node_marker.strip）"""
    return node_marker.strip(schema)
