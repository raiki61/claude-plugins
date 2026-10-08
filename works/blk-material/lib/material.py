"""素材集めのブロック（blk-material。本線 BLOCKS.md の R3「素材集め」、差し込み口 material）の芯。

回す役の節は写しの graph の P1 の目 9 本（p1.local_review ほか）と、素材集めに属す P0 の 2 本（p0.prior_decisions・
p0.purpose_review）。回すかどうかは盤面の ready（写しの条件 cond と節の表）だけで決まり、このブロックは条件を持たない
（判定から入る run の 1 周目の na も、条件付きの目の na も、写しの規則が決める）。機械の節 p1.worktree_before・
p1.worktree_after と engine が走らせる p0.parallel_pr は盤面（settle・start）が回す。

- route:   盤面を settle し、ROLES のうち ready の節の役に真を立てる（Archon の when: が読む平らな欄）。回さない節は理由
           （na・skipped・状態）を why に。役を起こす前の作業ツリーの姿（accept.tree_state。R47）を周に 1 度だけ置く。
           包みを宣言した run（adapter 空）で旗 no-tree-write の役を回すなら切符を確かめ、無ければ盤面を止める（blk-ci の
           ci-fence と同じ守り。宣言は YAML の入力 adapter で受ける——役を起こす前に固まる値）
- prep:    本線の指示書（gl-prompts の a1202d0 の写し）を engine と同じ描き方（rolekit.render_body）で
           $B/prompts/r<N>/<節>.md に描き、この周のこの節の拒否が在れば最後の拒否の文を頭に置き（R44）、起こした印を置く。
           p0.purpose がラインに無い盤面では、目的の欄を入力 purpose_file（blk-purpose の出口）か「目的の文が無い」の文で埋める
           （作らない。PURPOSE_MISSING）。本文の後ろに、素材に not_applicable を書けるか（節の条件とこの周の真偽。_na_note）を
           置く。道具を持たない役（PASTE）には本文そのものを prompt_text で渡す
- take:    旗の役の包みの柵（adapter 空の run）→ 作業ツリーを route の姿と比べる →（p1.local_review だけ）fork のレンズ
           （/code-review）の所見が届かなかった空の行を『見ていない』と書く（.shared/core/diverted.py）→ 必須のレンズの起動
           （_lens_gap）→ 盤面の done（写しの schema・post_check・writes・check_record・settle）。拒否は material-rejects.json
           に積み、GIVE_UP_AFTER 回目で done・give_up（輪を max_iterations で落とさない。R50）
- collect: 出口。回した後も待っている節が在れば（3 回とも拒まれた）盤面を止めて ok: False（諦めた目は全部名指す）。
           本線の R3 の出口（snapshot と materials）を組む
- 止まった盤面: 同じ波の 1 本の目が盤面を止めた（包みの柵）後は、並んで走る他の目の prep・take・refuse は盤面を書かずに
           stopped: true を返す（prep は役を起こさせず、受け付けは done で輪を抜けさせ、拒否に数えない）。止めるのは
           stop_once（もう止まった盤面には何も足さない）。輪が落ちずに collect まで届き、collect が止めた理由を返す

盤面を書く口（route の settle・prep の印・take の done・collect の settle）は、盤面の置き場の錠（fcntl.flock）の中で開いて
書く。Archon は同じ層の輪を同時に回すので、受け付けが並んで盤面を保存すると版の突き合わせ（BoardConflict）で落ちる
——graphloops の engine は同じ所を engine の錠と当て直しで守る（役を並べて起こし、done は 1 本ずつ）。
"""
import contextlib
import fcntl
import functools
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from accept import TREE_KEYS, role_schema, tree_moved, tree_state  # noqa: E402
import adapter  # noqa: E402
import diverted  # noqa: E402
from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import engine.util as _util  # noqa: E402
from engine.commands import _refuse_halted  # noqa: E402  （entry.take と同じ入口の拒み。写しの engine の関数）
from engine.util import TERMINAL_STATUS, AnswerReject, now, safe_name  # noqa: E402
import entry  # noqa: E402
import node_marker  # noqa: E402
import rolekit  # noqa: E402
import script_io  # noqa: E402

# 役の名（YAML の節 id・包みの印の名）→ 写しの graph の節。並びは graph の順
ROLES = {
    "prior-decisions": "p0.prior_decisions",
    "purpose-review": "p0.purpose_review",
    "local-review": "p1.local_review",
    "consistency-bypass": "p1.consistency_bypass",
    "hygiene": "p1.hygiene",
    "external-standards": "p1.external_standards",
    "procedure-trace": "p1.procedure_trace",
    "gate-efficacy": "p1.gate_efficacy",
    "test-double-fidelity": "p1.test_double_fidelity",
    "main-path-observation": "p1.main_path_observation",
    "provenance": "p1.provenance",
}
NODE_ROLE = {n: r for r, n in ROLES.items()}

# 役の形（graph の run_by と delegate から。graphloops の engine の起こし方に合わせる）
#   inspector:    Read・Grep・Glob（道具つきの役の plain）
#   isolated:     道具なし・本文を貼る（遮断系。engine は stdin で渡す）
#   investigator: Read・Grep・Glob・Bash・WebSearch・WebFetch。Bash は sandbox の中で網を閉じ（allowedDomains []。Archon が捨てる
#                 strictAllowlist は包みが足す）、読むだけの口 works-gh だけを sandbox の外に出す（graphloops の SANDBOX_BASE の
#                 excludedCommands gh と同じ考え。書く形は口の一覧と旗 no-post が止める）。issue・検索・Web は WebFetch・WebSearch
#   skill:        回す側の会話で skill と agent のレンズを起こす（p1.local_review）。investigator の道具に Skill・Agent を足す
#   delegate:     任せ先（graph の delegate）。engine の DELEGATE_TOOLS と delegate_settings（allowWrite ['/']・網）
POSTURE = {
    "prior-decisions": "investigator", "purpose-review": "inspector", "local-review": "skill",
    "consistency-bypass": "inspector", "hygiene": "isolated", "external-standards": "investigator",
    "procedure-trace": "investigator", "gate-efficacy": "delegate", "test-double-fidelity": "delegate",
    "main-path-observation": "delegate", "provenance": "delegate",
}
_TOOLS = {
    "inspector": ("Read", "Grep", "Glob"),
    "isolated": (),
    "investigator": ("Read", "Grep", "Glob", "Bash", "WebSearch", "WebFetch"),
    "skill": ("Read", "Grep", "Glob", "Bash", "WebSearch", "WebFetch", "Skill", "Agent"),
    "delegate": ("Read", "Grep", "Glob", "Bash", "WebSearch", "WebFetch"),
}
TOOLS = {r: _TOOLS[p] for r, p in POSTURE.items()}
# 網を閉じた Bash の役の sandbox。GitHub の宛先を許すと、sandbox の中のコードが読むだけの口を迂回して書ける（graphloops の role_run の注記）
_CLOSED = {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
           "excludedCommands": ["works-gh:*"], "network": {"allowedDomains": []}}
# YAML の sandbox（tests/test_blk_material.py が YAML と突き合わせる）
SANDBOX = {
    "inspector": {"enabled": True, "allowUnsandboxedCommands": False},
    "isolated": {"enabled": True, "allowUnsandboxedCommands": False},
    "investigator": _CLOSED,
    "skill": _CLOSED,
    "delegate": {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
                 "enableWeakerNetworkIsolation": True, "network": {"allowedDomains": ["*"], "allowLocalBinding": True},
                 "filesystem": {"allowWrite": ["/"]}},
}
# p1.local_review のレンズ（graph の skills）のうち組み込みの skill（Archon の skills: が SDK に選ばせる）。agent のレンズ
# （pr-review-toolkit:*）は Agent の道具で起こす。役はどれも settingSources: [user] で選んだ物だけの隔離した設定（dev/toolset.py）を
# 読む。pr-review-toolkit は利用者が入れた物（許す一覧 .shared/borrow/borrow.json）から入る。レンズが起きなければ
# その行は受け付けが拒んで同じ会話で起こし直させ、上限（GIVE_UP_AFTER 回）に届いた時だけ material は awaiting_human で人に渡る
# （プラグインが隔離した設定に無い時は出し直さずにすぐ渡す。_lens_gap）
SKILLS = {"local-review": ["code-review", "simplify", "security-review"]}
# Bash を持つ役の印の旗: 包みが gh の書き込みを柵に足し（no-post）、役の cwd の作業ツリーを書けなくする（no-tree-write。
# 包みは sandbox・切符の無い起動を起こさない）
# skill のレンズを起こす役（SKILLS）は旗 text-reply も持つ: 包みが返答の型を返答の道具（StructuredOutput）に任せず、本文で受けて
# 確かめ、合わなければ同じ会話で出し直させる（fork で走る skill が返答の道具を継いで所見を書き、役に届かなかったため）
FLAGS = {r: ("no-post", "no-tree-write") + (("text-reply",) if r in SKILLS else ()) for r, p in POSTURE.items() if "Bash" in _TOOLS[p]}
PASTE = frozenset(r for r, p in POSTURE.items() if p == "isolated")   # 指示書の本文を prompt_text で渡す役
SIMPLIFY_LENS = "/simplify"   # 指示書が持ち越しを許すレンズ（返答の simplify_carried）。本流 review-loop.py と同じ
SETTING_SOURCES = dict.fromkeys(POSTURE, ("user",))

GIVE_UP_AFTER = 3                        # 輪の max_iterations と同じ数（試験が YAML と突き合わせる）
# 写しの指示書（書き換えない）は呼び出しの失敗を awaiting_human にせよと言い、受け付け（_lens_gap）はそれを必須のレンズで拒む
LENS_RETRY_NOTE = ("## 必須のレンズの呼び出しの失敗（works の受け付けより。上の指示書の読み替え）\n\n"
                   "上の『skill の呼び出し自体が失敗したら…material を awaiting_human にして理由を書け』は、`required` が false の"
                   "レンズにだけ当てる。`required` が true のレンズの呼び出しが失敗したら、この回のうちに起こし直して "
                   "`invoked: true` を書け。起こせないまま返すなら `failed` に理由を書き、material を awaiting_human にするな——"
                   f"受け付けが拒んで同じ会話で起こし直させ、拒みが {GIVE_UP_AFTER} 回に届いた時と、レンズのプラグインが隔離した"
                   "設定に無い時だけ人に渡す。\n\n"
                   "上の『直前の周から対象差分にロジック変更が無いなら /simplify の再実行は持ち越してよい』は狭めて読め: "
                   "`simplify_carried: true` を受けるのは、この周の頭に固めた版が前の周の頭の版と 1 ファイルも違わない周だけ。"
                   "どれかのファイルが変わった周（ロジックでない変更でも）と 1 周目は `/simplify` を起こして `invoked: true` を書け。")
# 写しの指示書と graph の note（/code-review に --comment も --fix も付けるな）の読み替え。包みの旗 text-reply の起動（この役の印。
# .shared/core/adapter.py の頭の 21）では fork に返答の道具が無いので、/code-review は所見を本文で返す。返答の道具が残った形（包みを
# 外した run など）では fork の所見は親に届かない（実測は .shared/core/diverted.py の頭）ので、受け付けが空の行を『見ていない』と書く。
# どちらの形でも役には起こし直させず、旗の綴りを args に書かせない
LENS_FORK_NOTE = ("## /code-review の返り方（works の受け付けより。上の指示書の読み替え）\n\n"
                  "/code-review は別の会話（fork）で走る。所見を本文で返したら、それを /code-review の行の `items` に写せ"
                  "（どの所見も落とさない）。Skill の結果が『Skill execution completed』だけで所見の本文が無い時は、fork が所見を"
                  "別の口（返答の道具）に書いて親に届かなかった形で、works の受け付けがこの行を『見ていない』と報告に出す。"
                  "どちらでも /code-review を起こし直すな（同じ形で返り、時間だけ掛かる）。本文が無かった行は "
                  "`items` を空、`invoked: true` にして、`failed` に『本文が届かなかった』と渡した対象を書け"
                  "（『起こしたが所見なし』と書くな——見ていない物を 0 件に見せる）。\n\n"
                  "args に旗の綴り（`--comment`・`--fix`）を書くな——『付けない』と否定の文の中に書いても skill は旗として読む"
                  "（実測: 『--comment も --fix も付けない』の --fix が旗に取られた）。修正を禁じるのは『作業ツリーを変えるな』の文で言え。")
# 写しの指示書の素材の書き方は not_applicable（条件に当たらない）を並べるが、受け付け（写しの check_record と works の差し替え
# entry.role_judged_na_works）は、走った節の applies_cond が真なら拒み（役の判定を受ける差し替えが立つ時を除く）、applies_cond を
# 持たない節は graph が na_self_ok を宣言した時だけ受ける。役はそれを知らないので、prep が節の条件とこの周の真偽を書く（_na_note）
NA_HEADING = "## 『条件に当たらない』（not_applicable）を書けるか（works の受け付けより。上の指示書の読み替え）"
NA_REFUSED = ("`not_applicable` は受け付けが拒む——見た結果を found・clean で、確かめられなかったなら not_run（理由つき）で"
              "書け。")
STOP_BY = "works:material"
FENCE_BY = "works:adapter"               # 包みの確かめが通らない時の止め札（blk-ci・線の境の節と同じ by）
ADAPTER_MODES = ("", "optional")         # 入力 adapter の語（線の start の出口 adapter と同じ語）
REJECT_HEADING = "## 前の回の受け付けが拒んだ理由"
READONLY_MOVED = "読むだけの役が作業ツリーを変えた: "
PURPOSE_MISSING = "（目的の文はこの run に無い——目的の節 p0.purpose がこのラインに無く、目的のファイルも渡されていない。目的を推し量って補うな）"
SNAPSHOT = "material-snapshot.json"
REJECTS = "material-rejects.json"
EXIT = "material-exit.json"
LOCK = ".works-material.lock"
PROMPTS_COPY = rolekit.PROMPTS_COPY
EXIT_KEYS = ("ok", "reason", "ran", "skipped", "materials", "snapshot", "exit_file")
PREP_KEYS = ("prompt_file", "prompt_text", "attempt", "out_path", "node", "already", "stopped")   # prep の出口（YAML と突き合わせる）
SNAPSHOT_KEYS = {"rev": "reviewed_revision", "diff_file": "diff_file", "changed_files": "changed_files",
                 "changed_files_file": "changed_files_file", "diff_stat": "diff_stat", "request_wheres": "request_wheres"}


def route_key(role: str) -> str:
    """route の出口の欄の名（Archon の when: が $mat-route.output.<欄> で読む）"""
    return role.replace("-", "_")


def prepared_name(role: str) -> str:
    return f"material-prepared-{role}.json"


def output_format(role: str) -> dict:
    """役の output_format: 写しの schema（accept.role_schema）に印 works-node: <役>[ 旗…] を付けた物"""
    return node_marker.mark(role_schema(ROLES[role]), role, flags=FLAGS.get(role, ()))


def _node(role: str) -> str:
    if role not in ROLES:
        raise BoardGap(f"役 {role!r} は素材集めの役（{' / '.join(ROLES)}）でない——blk-material の with: を確かめる")
    return ROLES[role]


def _mode(mode: str) -> str:
    if mode not in ADAPTER_MODES:
        raise BoardGap(f"入力 adapter={mode!r} は宣言の語（空か optional）でない——blk-material の with: を確かめる")
    return mode


# ---------------------------------------------------------------- 盤面
@contextlib.contextmanager
def _locked(board_dir):
    """盤面の置き場の錠。中で開いて書く（並ぶ受け付けの版の衝突を避ける）"""
    d = pathlib.Path(board_dir)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / LOCK, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _open(board_dir, repo=None, *, allow_halted=False):
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=allow_halted)
    if repo is not None:
        _util.GIT_CWD = str(pathlib.Path(repo).resolve())
    return b


def _stopped(b) -> dict | None:
    st = b.state
    if st.get("halted") or st.get("stop"):
        return st.get("stop") or st.get("halted")
    if st.get("status") in TERMINAL_STATUS:
        return {"by": st.get("status"), "reason": ""}
    return None


def stop_once(b, reason: str, by: str) -> dict:
    """盤面を止める。もう止まっている盤面（同じ波の別の目が先に止めた）には何も足さず、今の止め札を返す——写しの stop は
    2 度目を Reject にするので、並ぶ目の 2 本目の柵の落ちで輪の節が落ちないように。呼ぶのは盤面の錠の中だけ（確かめと止めが
    割り込まれない）"""
    stop = _stopped(b)
    if stop:
        return stop
    b.stop(reason, by=by)
    return _stopped(b) or {}


def _stopped_take(b, nid: str) -> dict:
    """止まった盤面に届いた返答の出口: 受けず・盤面を書かず・拒否に数えず、done で輪を抜けさせる（collect が止めた理由を返す）"""
    stop = _stopped(b) or {}
    return {"ok": False, "done": True, "give_up": False, "stopped": True, "node": nid, "status": "",
            "reason": f"盤面は止まっている（{stop.get('by')}: {stop.get('reason', '')}）——{nid} の返答は受けない"}


def _waiting(b, nid: str) -> dict:
    inst = b.rd["instances"].get(nid)
    if not (inst and inst.get("status") == "pending"):
        raise BoardGap(f"{nid} はこの周に待っていない（{b.rd['na'].get(nid) or b.rd['skipped'].get(nid) or b.node_state(nid)}）"
                       "——blk-material は route が真を立てた役だけを回す")
    return inst


def _write_json(path: pathlib.Path, obj) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def _read_json(path: pathlib.Path, default=None):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"{path} を読めない: {e}") from None


def _why_not(b, nid: str) -> str:
    """回さない節の理由: 条件に当たらない（na）・表で absent（skipped）の理由、無ければ盤面の状態"""
    return b.rd["na"].get(nid) or b.rd["skipped"].get(nid) or f"状態 {b.node_state(nid)}"


# ---------------------------------------------------------------- route
def route(board_dir, repo, mode: str) -> dict:
    """回す役を決める。返り {ok, stopped, why, snapshot_file, <route_key(役)>: bool…}。止まった盤面は全部偽で stopped"""
    mode = _mode(mode)
    off = {route_key(r): False for r in ROLES}
    with _locked(board_dir):
        b = _open(board_dir, repo, allow_halted=True)
        stop = _stopped(b)
        if stop:
            return {"ok": True, "stopped": True, "why": f"盤面は止まっている（{stop.get('by')}）", "snapshot_file": "", **off}
        ready = b.settle()["ready"]
        run = {r: n in ready for r, n in ROLES.items()}
        why = "・".join(f"{n}: {'回す' if run[r] else _why_not(b, n)}" for r, n in ROLES.items())
        if mode == "" and any(run[r] for r in FLAGS):
            try:
                t = adapter.read_ticket(pathlib.Path(repo))
                bad = "" if t is not None else f"切符が無い（{adapter.ticket_path(pathlib.Path(repo))}。線の start が書く）"
            except adapter.BadTicket as e:
                bad = str(e)
            if bad:
                reason = f"包みの確かめが通らない: 旗 no-tree-write の素材集めの役を起こさない（{bad}）"
                stop_once(b, reason, by=FENCE_BY)
                return {"ok": True, "stopped": True, "why": reason, "snapshot_file": "", **off}
        p = b.work(SNAPSHOT)
        doc = _read_json(p)
        if not (isinstance(doc, dict) and set(TREE_KEYS) <= set(doc)):
            _write_json(p, tree_state(pathlib.Path(repo)))   # 周に 1 度（Archon の再開で走り直しても最初の姿を残す）
    return {"ok": True, "stopped": False, "why": why, "snapshot_file": str(p), **{route_key(r): v for r, v in run.items()}}


# ---------------------------------------------------------------- prep
def _purpose(purpose_file: str) -> dict:
    """p0.purpose がラインに無い盤面で、指示書の out.p0.purpose を埋める値。purpose_file（blk-purpose の出口の purpose.json）が
    在ればその中身、空なら PURPOSE_MISSING（目的を作らない）。読めないのは配線の誤り（BoardGap）"""
    if not purpose_file:
        return {"purpose_text": PURPOSE_MISSING, "source": "目的不明", "known_weaknesses": [], "source_files": []}
    p = pathlib.Path(purpose_file)
    doc = _read_json(p if p.is_absolute() else pathlib.Path.cwd() / p)
    if not (isinstance(doc, dict) and isinstance(doc.get("purpose_text"), str)):
        raise BoardGap(f"目的のファイル {purpose_file} が無いか、purpose_text を持たない")
    return doc


def render(b, nid: str, purpose_file: str = "") -> str:
    """engine の emit_instance と同じ描き方の本文（rolekit.render_body。cap なし）。p0.purpose がラインに無い盤面では目的の欄を
    _purpose で埋める。番号の控えは instance に置く。描けなければ BoardGap"""
    inst = _waiting(b, nid)

    def fill_purpose(ctx):
        if "p0.purpose" not in ctx["out"]:
            ctx["out"] = {**ctx["out"], "p0.purpose": _purpose(purpose_file)}
    prompt, snap_ = rolekit.render_body(b, nid, prompts_dir=PROMPTS_COPY, ctx_hook=fill_purpose)
    if snap_ and inst.get("pointers") != snap_:
        inst["pointers"] = snap_
        b.save()
    return prompt


def _na_note(b, nid: str) -> str:
    """節 nid の役が素材に not_applicable を書けるかの段（NA_HEADING）。写しの check_record と同じ決め: applies_cond が在れば
    この周の真偽（b.cond）と役の判定を受ける差し替え（RL の role_judged_na。works は entry.role_judged_na_works）、無ければ
    graph の na_self_ok の宣言"""
    n = b.nodes[nid]
    ap = n.get("applies_cond")
    if ap is None:
        if n.get("na_self_ok"):
            body = (f"この節は条件（applies_cond）を持たず、graph が『条件に当たらない』を名乗れる節と宣言している（na_self_ok: "
                    f"{n['na_self_ok']}）。当たらない時は `not_applicable`（理由を reason に）を書いてよい。")
        else:
            body = ("この節は条件（applies_cond）を持たず、graph も『条件に当たらない』を名乗れる節と宣言していない（na_self_ok が"
                    f"無い）ので、{NA_REFUSED}")
    else:
        ok, why = b.cond(ap)
        if not ok:
            body = f"この節の条件 `{ap}` はこの周に偽（{why}）なので、`not_applicable`（理由を reason に）を書いてよい。"
        elif b.rules.role_judged_na(b, nid):
            body = (f"この節の条件 `{ap}` はこの周に真（{why}）だが、機械が持つ事実はどれも条件を立てていない（works の受け付けは"
                    "この節の役の判定を受ける）。差分を読んで条件に当たらないと判じたら `not_applicable`（理由を reason に）を"
                    "書いてよい。")
        else:
            body = f"この節の条件 `{ap}` はこの周に真（{why}）なので、{NA_REFUSED}"
    return f"{NA_HEADING}\n\n{body}"


def prep(board_dir, role: str, repo, purpose_file: str = "") -> dict:
    """役を起こす前の支度。返り PREP_KEYS（prompt_text は PASTE の役だけ）。盤面が止まっていれば（同じ波の別の目が止めた）
    描かず・印を置かず stopped: true（役の節は when: で飛び、受け付けが止まった旨の done を出す）"""
    nid = _node(role)
    with _locked(board_dir):
        b = _open(board_dir, repo, allow_halted=True)
        if _stopped(b):
            return {"prompt_file": "", "prompt_text": "", "attempt": 0, "out_path": "", "node": nid, "already": False,
                    "stopped": True}
        inst = _waiting(b, nid)
        text = render(b, nid, purpose_file).rstrip("\n") + "\n\n---\n\n" + _na_note(b, nid) + "\n"
        last = _rejects(b, nid)[-1:]
        if last:
            # 拒否の文は指示書に書く（役は読む）。$LOOP_PREV で貼ると、文の中の $<節>.output.<欄> を Archon が置き換え直す（R44）
            text = (f"{REJECT_HEADING}\n\n前の回の返答は受け付けで拒まれた。下の理由のところを直した返答を丸ごと出し直せ"
                    f"（直した所だけを返すな）:\n\n```text\n{last[0]['reason']}\n```\n\n---\n\n" + text)
        if "Skill" in TOOLS[role]:
            text = text.rstrip("\n") + "\n\n---\n\n" + rolekit.skill_overlay()   # 借りたスキルを読める役だけに無人の読み替え
        if nid == ROLES["local-review"]:
            text = text.rstrip("\n") + "\n\n---\n\n" + LENS_RETRY_NOTE + "\n\n---\n\n" + LENS_FORK_NOTE
        path = b.dir / "prompts" / f"r{b.round}" / (safe_name(nid) + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _write_json(b.work(prepared_name(role)), {"node": nid, "at": adapter.now()})
        m = b.mark_launched(nid, inst.get("attempts", 1))
    return {"prompt_file": str(path), "prompt_text": text if role in PASTE else "", "attempt": m["attempt"],
            "out_path": m["out_path"], "node": nid, "already": m["already"], "stopped": False}


# ---------------------------------------------------------------- take
def _rejects(b, nid: str) -> list:
    return [r for r in _read_json(b.work(REJECTS), []) if r.get("node") == nid]


def _reject(b, nid: str, reason: str, give_up: bool = False) -> dict:
    """拒みを積む。give_up が偽なら GIVE_UP_AFTER 回目で人に渡す（真なら上限を待たずに渡す）"""
    rows = _read_json(b.work(REJECTS), [])
    inst = b.rd["instances"].get(nid) or {}
    rows.append({"node": nid, "attempt": inst.get("attempts", 1), "at": now(), "reason": reason})
    _write_json(b.work(REJECTS), rows)
    give_up = give_up or sum(1 for r in rows if r.get("node") == nid) >= GIVE_UP_AFTER
    return {"ok": False, "done": give_up, "give_up": give_up, "stopped": False, "reason": reason, "node": nid, "status": ""}


def _simplify_carry_ok(b) -> bool:
    """本流 graphloops/rules/review-loop.py の _simplify_carry_ok と同じ条件（前の周から 1 ファイルも変わっていない周で、
    周の途中で撮り直していない）。写しの周の頭の節は本流の changed_since_prev_round を出さないので、写しが周ごとに残す
    周の頭の版（loop_state.head_revs）の前の周と今の周の木を比べる。版が無い・git が引けなければ偽（起こし直させる）"""
    if b.round < 2 or b.output_of_round("p1.worktree_after", b.round):
        return False
    revs = b.loop_state.get("head_revs") or {}
    prev, cur = revs.get(str(b.round - 1)), revs.get(str(b.round))
    trees = _util.git("rev-parse", f"{prev}^{{tree}}", f"{cur}^{{tree}}") if prev and cur else None
    trees = (trees or "").split()
    return len(trees) == 2 and trees[0] == trees[1]


def _installed_plugins() -> set | None:
    """役が読む隔離した設定（env の CLAUDE_CONFIG_DIR）に入っているプラグインの名。置き場・ファイルが読めなければ None（分からない）"""
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    doc = _read_json(pathlib.Path(cfg) / "plugins" / "installed_plugins.json") if cfg else None
    plugins = doc.get("plugins") if isinstance(doc, dict) else None
    return {k.split("@", 1)[0] for k in plugins} if isinstance(plugins, dict) else None


def _skills(b, nid: str) -> list:
    """この周の節 nid の宣言のレンズ（engine が instance に置いた skills。無ければ graph の skills）"""
    inst = next((i for i in reversed(list(b.rd["instances"].values())) if i.get("node") == nid and i.get("status") != "done"), None)
    return (inst or {}).get("skills") or b.graph["nodes"][nid].get("skills") or []


def _mark_unseen(b, nid: str, reply: dict) -> tuple:
    """p1.local_review の返答の、fork のレンズ（/code-review）の所見が届かなかった空の行に『見ていない』の印を付けた写しと
    控えを返す（diverted.mark_unseen）。控えは受け付けが通った後に周の作業ファイルへ書く"""
    out, notes = diverted.mark_unseen(reply, _skills(b, nid))
    return out, {"round": b.round, **notes}


def _lens_gap(b, nid: str, reply: dict) -> tuple[str, bool] | None:
    """p1.local_review の返答が必須のレンズを起こしていない・material を awaiting_human にした時の (拒みの文, 出し直さないか)。
    本流 0.23.0 の local_review_covers_lenses の engine の子の枝と同じ条件を、写し（0.21.0）の規則の前に当てる。レンズの
    プラグインが隔離した設定に無い時は起こし直しても毎回落ちるので、出し直さずに人に渡す。条件付きのレンズだけの
    呼び出しの失敗（必須のレンズは全部起きた返答の awaiting_human）は写しの規則のまま受ける"""
    skills = _skills(b, nid)
    rows = {r.get("skill"): r for r in reply.get("findings") or [] if isinstance(r, dict)}
    carry_ok = _simplify_carry_ok(b)
    carried = reply.get("simplify_carried") is True and carry_ok
    missing = [e["skill"] for e in skills if e.get("required", True) and (rows.get(e["skill"]) or {}).get("invoked") is not True
               and not (e["skill"] == SIMPLIFY_LENS and carried)]
    if not missing:
        return None
    errs = [f"'{s}' は必須のレンズなのに invoked が true でない——必須のレンズを起こした行だけを受け付ける。/ で始まるレンズは Skill で、"
            "<plugin>:<役> は定義の置き場を Read で読ませた汎用の子（Agent）で起こし直せ"
            + ("（simplify_carried: true の持ち越しは、この周の頭の版が前の周の頭の版と 1 ファイルも違わない周だけ受ける。"
               + ("この周は当たる——持ち越すなら simplify_carried: true を書け）" if carry_ok else "この周は当たらない）")
               if s == SIMPLIFY_LENS else "")
            for s in missing]
    if _status(reply) == "awaiting_human":
        errs.append("必須のレンズが起きていない返答は material を awaiting_human にできない——起こし直して invoked: true を書け"
                    "（拒みが上限に届けば人に渡る）")
    installed = _installed_plugins()
    absent = sorted({s.split(":", 1)[0] for s in missing if ":" in s and not s.startswith("/")} - installed) \
        if installed is not None else []
    if absent:
        errs.append(f"隔離した設定（{os.environ.get('CLAUDE_CONFIG_DIR')}）にプラグイン {'・'.join(absent)} が入っていない——"
                    "起こし直しても毎回落ちるので出し直さずに人に渡す（dev/toolset.py で入れ直してから続ける）")
    return "宣言したレンズと findings の行が合わない:\n" + "\n".join("  - " + e for e in errs), bool(absent)


def _peers(b, nid: str) -> list:
    """同じ波で起きている（印を置いて待っている）ほかの素材集めの役の節"""
    return sorted(i["node"] for i in b.rd["instances"].values()
                  if i["node"] != nid and i["node"] in NODE_ROLE and i.get("status") == "pending" and i.get("launched_at"))


def _status(reply) -> str:
    for k in ("material", "consistency"):
        v = reply.get(k) if isinstance(reply, dict) else None
        if isinstance(v, dict) and isinstance(v.get("status"), str):
            return v["status"]
    return ""


def take(board_dir, role: str, reply: dict, repo, mode: str) -> dict:
    """役の返答を受け付ける。返り {ok, done, give_up, stopped, reason, node, status}。mode は入力 adapter（YAML の with:）。
    盤面が止まっていれば（同じ波の別の目が止めた）受けずに stopped: true の done（_stopped_take）"""
    nid, mode = _node(role), _mode(mode)
    with _locked(board_dir):
        b = _open(board_dir, repo, allow_halted=True)
        if _stopped(b):
            return _stopped_take(b, nid)
        _refuse_halted(b)
        _waiting(b, nid)
        if mode == "" and role in FLAGS:
            prepared = _read_json(b.work(prepared_name(role)))
            if not (isinstance(prepared, dict) and prepared.get("at")):
                raise BoardGap(f"{b.work(prepared_name(role))} が無い——{role}-prep が先に走る（役の起動の記録と突き合わせられない）")
            why = adapter.fenced_launch(pathlib.Path(repo), role, prepared["at"])
            if why:
                reason = f"包みの柵が素材集めの役（{role}）の起動に掛かっていない: {why}——返答を受けず盤面を止める"
                stop_once(b, reason, by=FENCE_BY)
                return {"ok": False, "done": True, "give_up": False, "stopped": False, "reason": reason, "node": nid,
                        "status": ""}
        snap = _read_json(b.work(SNAPSHOT))
        if not (isinstance(snap, dict) and set(TREE_KEYS) <= set(snap)):
            raise BoardGap(f"{b.work(SNAPSHOT)} が無い・形が違う——mat-route が先に走る")
        moved = tree_moved({k: snap[k] for k in TREE_KEYS}, pathlib.Path(repo))   # 共通の比べ（R47）
        if moved:
            peers = _peers(b, nid)
            who = (f"。同じ波で起きている役が他に {len(peers)} 件在る（{'・'.join(peers)}）——変えたのがこの役とは限らない"
                   if peers else "")
            return _reject(b, nid, f"{READONLY_MOVED}素材集めの役は対象の作業ツリー・HEAD・枝・git が無視するファイルを"
                                   f"変えてはいけない（{'・'.join(moved)}）{who}")
        lens_note = None
        if nid == ROLES["local-review"]:
            reply, lens_note = _mark_unseen(b, nid, reply)
        gap = _lens_gap(b, nid, reply) if nid == ROLES["local-review"] else None
        if gap:
            return _reject(b, nid, *gap)
        try:
            b.done(nid, reply)
        except AnswerReject as e:
            return _reject(b, nid, str(e))
        if lens_note is not None:   # 受け付けが通った返答の分だけ（拒んだ・諦めた回の『見ていない』を報告に出さない）
            _write_json(b.work(diverted.LENS_FILE), lens_note)
    return {"ok": True, "done": True, "give_up": False, "stopped": False, "reason": "", "node": nid, "status": _status(reply)}


def refuse(board_dir, role: str, reason: str) -> dict:
    """返答を受け付けの前に拒む（読めない返答。役の節を飛ばした周の null もここに来る）。拒否の文は take の拒否と同じく
    material-rejects.json に積む。盤面が止まっていれば take と同じく stopped: true の done"""
    nid = _node(role)
    with _locked(board_dir):
        b = _open(board_dir, allow_halted=True)
        if _stopped(b):
            return _stopped_take(b, nid)
        _waiting(b, nid)
        return _reject(b, nid, reason)


# ---------------------------------------------------------------- collect
def collect(board_dir) -> dict:
    """出口 {ok, reason, ran, skipped, materials, snapshot, exit_file}。同じ物を material-exit.json に書く。
    - 回した後も待っている素材集めの節が在れば（3 回とも拒まれた・route の後に ready が変わった）盤面を止めて ok: False
    - 盤面が既に止まっている（包みの確かめ・前のブロック）なら ok: False で止めた理由
    - ran はこの周に受けた節、skipped は回さなかった節と理由。materials は記録の素材の status（p1.worktree_after が埋めた
      15 欄）、snapshot は本線の R3 の出口 snapshot の 6 欄（盤面の loop の値）"""
    with _locked(board_dir):
        b = _open(board_dir, allow_halted=True)
        ok, reason = True, ""
        stop = _stopped(b)
        if stop:
            ok, reason = False, f"盤面は止まっている（{stop.get('by')}: {stop.get('reason', '')}）"
        else:
            ready = b.settle()["ready"]
            waiting = [n for n in ROLES.values() if n in ready]
            if waiting:
                parts, unran = [], []
                for nid in waiting:   # 諦めた目は全部名指す（先頭の 1 本だけにしない）
                    rejects = _rejects(b, nid)
                    if (b.rd["instances"].get(nid) or {}).get("launched_at") and rejects:
                        parts.append(f"{nid} の返答が {len(rejects)} 回とも受け付けで拒まれた（最後の拒否: {rejects[-1]['reason']}）")
                    else:
                        unran.append(nid)
                if unran:
                    parts.append(f"回した後も素材集めの節 {unran} が待っている（route の後に ready が変わったか、輪が回らなかった）")
                reason = "／".join(parts)
                ok = False
                stop_once(b, reason, by=STOP_BY)
        ran = [n for n in ROLES.values() if n in b.rd["done"]]
        skipped = [{"node": n, "why": str(_why_not(b, n))} for n in ROLES.values() if n not in b.rd["done"]]
        mats = {k: (v or {}).get("status", "") for k, v in (b.record.get("materials") or {}).items() if isinstance(v, dict)}
        ls = b.loop_state
        snap = {k: ls.get(src) if ls.get(src) is not None else ([] if k in ("changed_files", "request_wheres") else "")
                for k, src in SNAPSHOT_KEYS.items()}
        p = b.work(EXIT)
        out = {"ok": ok, "reason": reason, "ran": ran, "skipped": skipped, "materials": mats, "snapshot": snap,
               "exit_file": str(p)}
        _write_json(p, out)
    return out


# ---------------------------------------------------------------- スクリプトの入口
# blk-material のスクリプトの入口（rolekit.script_main。盤面のパスに $ の柵）。欠けた環境変数・BoardGap・写しの Reject
# （止めた run への書き込み・git が効かない）・思わぬ誤りは標準エラーに 1 行で 2（標準出力には何も出さない）
script_main = functools.partial(rolekit.script_main, fence=True)


def main_accept() -> int:
    """受け付けのスクリプトの入口: INPUTS_ROLE・INPUTS_REPLY・INPUTS_ADAPTER・ARTIFACTS_DIR。拒否（読めない返答を含む）は
    script_io.emit_result で reason_file（理由の本文のファイル）を足して 0。配線の誤りは 2"""
    names = ("INPUTS_ROLE", "INPUTS_REPLY", "INPUTS_ADAPTER")
    missing = [n for n in names if n not in os.environ]
    if not os.environ.get(script_io.ARTIFACTS_ENV):
        missing.insert(0, script_io.ARTIFACTS_ENV)
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    board = script_io.board_dir()
    if board is None:
        return 2
    role, raw, mode = (os.environ[n] for n in names)
    try:
        reply, why = rolekit.parse_reply(raw)
        out = refuse(board, role, why) if reply is None else take(board, role, reply, pathlib.Path.cwd(), mode)
    except (BoardGap, _util.Reject) as e:
        print(f"{type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    return script_io.emit_result(board, f"take_{route_key(role)}", out)
