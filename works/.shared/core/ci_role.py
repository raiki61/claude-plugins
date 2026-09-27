"""CI の任せ先の役（ブロック blk-ci。線 A Task 27。裁定 R52）。

graphloops の p0.local_checks（修正前）と p4.ci（修正後）は、engine が宣言（.review-checks.json）を走らせられない時、graph の役
（run_by: writer。a1202d0 の指示書 p0.local_checks.md・p4.ci.md）に落ちる。works では test_cmd も空の run で、entry.run_ci が
role_needed を返し（start の ci_role_go・blk-tests の final の by）、ラインがこのブロックを node: <節> で回す。役は opus で、
Read・Grep・Glob とテストを走らせる Bash を持ち、Edit・Write は持たない。

走らせる場所は graphloops の任せ先と同じく作業ツリーの写し（写しの engine の util.copy_worktree。本物と同じ commit に未コミットの
変更と未追跡のファイルを載せた独立の clone）。写しは run ごとに利用者の一時の置き場（tempfile.gettempdir()）の直下の
COPY_PREFIX で始まるフォルダに作る。

守り（裁定 R56。graphloops の任せ先と同じ能力）: YAML の役の sandbox は graphloops の delegate_settings と同じ形（allowWrite ['/']・
網・failIfUnavailable）で、依存の導入（~/.cache・網）と localhost のテストが通る。書き込みの守りは全部包み（claude-adapter）が
足す: 役の印の旗 no-tree-write を見て、役の cwd の worktree の根と切符の守る場所（盤面・共通の .git・ほかの worktree・
git とシェルと Claude の設定・Archon の家の設定と DB・pack）を起動ごとに denyWrite・permissions.deny に足し、sandbox・切符の
無い起動は起こさない。包みが居なければ、役の Bash は Claude Code の既定の拒否（.gitconfig・シェルの起動ファイル・.git/hooks・
.git/config など。macOS は全域、Linux は cwd の下だけ）の外の全部——本物の作業ツリー・盤面・共通の .git の refs と objects・
~/.config・~/.claude・Archon の家・Linux では ~/.gitconfig も——に書ける。これは graphloops の任せ先と同じ晒され方（sandbox だけ）で、
包み無しの run はそれを宣言して回す（裁定 R58。仕様 5.1）。包みが起動の道に在るかを script から写して見ることはしない（Archon の
claude の解決と食い違い、居ないのに居ると言う形と、写しの pack で居るのに居ないと言う形が両方ある。再審査 N4〜N6）。見るのは
run が宣言した包みの形（start の控えの adapter。entry.declared_adapter）だけで、読むのは役を起こす前の ci-fence の 1 回だけ。
読んだ形は ci-fence の出力 adapter に出し、YAML の with: で ci-accept と collect へ渡す（Archon の節の出力は役から書き換えられない。
役を起こした後に start の控えを読み直すと、包みの居ない起動の役が控えを書き換えて柵の確かめを飛ばせる。再審査 N8）:
- fence:    ci-fence。包みを宣言した run（adapter が空）は切符を見て進む（無ければ盤面を止める。包みは切符の無い旗の役を起こさない）。
            包み無しを宣言した run（adapter: optional）は進み、知らせ NO_ADAPTER_NOTE を出す。宣言が読めなければ盤面を止め
            （by works:adapter）、YAML が役の輪を飛ばす（fail closed。出力 adapter は厳しい方の空）
- take の頭: with: で届いた形が包みを宣言した run（空）なら、包みの起動の記録で、この試行の役の起動が包みを通り柵 no_tree_write が
            掛かったか（adapter.fenced_launch）を見る。無ければ・届いた形が宣言の語でなければ、拒否でなく盤面を止める（起きた後で
            気づく線。包みの無い起動は記録も書き換えうるので確証ではない）。包み無しの run では柵を求めない
受け付けの作業ツリーの比べ（accept.tree_state: porcelain・差分・git が無視するパス・HEAD・枝）は、どちらの run でも偽の緑を防ぐ。

- fence:    ci-fence（上）。返り {go, reason, note, adapter}
- snapshot: ci-snap。節が任せ先に落ちて待っているか確かめ、作業ツリーの姿（と写しの置き場）を今の周の ci-snapshot-<節>.json に
- prep:     ci-prep。blk-ci/prompts/<節>.md の穴（<<名>>）を埋めた指示書を描き、この周のこの節の拒否が在れば最後の拒否の文を
            頭に置き（REJECT_HEADING。$LOOP_PREV で貼らない——裁定 R44）、起こした印（mark_launched）を置く
- take:     ci-accept。作業ツリーの比べ → 盤面の done（写しの schema・post_check・check_record がそのまま当たる）。拒否は
            ci-rejects.json に積み、GIVE_UP_AFTER 回目の拒否で done・give_up（輪を max_iterations で落とさない。裁定 R50）
- collect:  出口。写しを消す。with: で届いた形が包み無し（optional）なら知らせ NO_ADAPTER_NOTE を note に出す。節を受けていれば素材の status と green、p0.local_checks なら
            entry.resume_after_ci で start の輪に戻って pr_go。受けていなければ（3 回とも拒まれた）最後の拒否の文で盤面を止めて
            （by works:ci）ok: false
スクリプトの入口は rejudge.script_main（環境変数の欠け・BoardGap・写しの Reject は終了コード 2）。
"""
import json
import os
import pathlib
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True

CORE = pathlib.Path(__file__).resolve().parent
PACK = CORE.parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from accept import TREE_KEYS, role_schema, tree_moved, tree_state  # noqa: E402
import adapter  # noqa: E402
from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import engine.util as _util  # noqa: E402
from engine.rules import validator_module  # noqa: E402
from engine.util import AnswerReject, now, safe_name  # noqa: E402
import entry  # noqa: E402
import node_marker  # noqa: E402
from rejudge import parse_reply, script_main  # noqa: E402,F401  （スクリプトの入口と返答の読み方は再審のブロックと同じ物）

NODES = ("p0.local_checks", "p4.ci")   # 写しの graph の CI の節（engine_run.builtin が declared_checks）
ROLE = "ci"                             # YAML の役の節の id と包みの印の名
NO_TREE_WRITE = "no-tree-write"         # 印の旗: 包みが役の cwd の作業ツリーを柵に足す（裁定 R56）
OUTPUT_FORMAT = node_marker.mark(role_schema(NODES[0]), ROLE, flags=(NO_TREE_WRITE,))   # 2 つの節の schema は同じ形
GIVE_UP_AFTER = 3                       # 輪の max_iterations と同じ数（tests/test_blk_ci.py が YAML と突き合わせる）
STOP_BY = "works:ci"
FENCE_BY = "works:adapter"               # 包みの宣言が読めない・柵が掛かっていない時の止め札の by（線の h-judge の包みの確かめと同じ）
NO_ADAPTER_NOTE = ("包み無し（adapter: optional）: CI の任せ先の役は graphloops の任せ先と同じ守り（sandbox だけ。作業ツリーの柵は"
                   "無い）で走った")
REJECT_HEADING = "## 前の回の受け付けが拒んだ理由"
COPY_PREFIX = "works-ci-"               # 写しの置き場（一時の置き場の直下の <COPY_PREFIX><節>-XXXX）の頭。出口はこの形の物だけ消す
PROMPTS = PACK / "blk-ci" / "prompts"
HOLES = ("node", "root", "copy", "tmp", "fallback")   # 2 つの指示書が両方持つ穴（<<名>>）
P4_HOLES = ("base", "answers", "questions")          # p4.ci の指示書だけの穴
REJECTS = "ci-rejects.json"


def prepared_name(node: str) -> str:
    """ci-prep が試行ごとに書き直す、役を起こす直前の時刻（adapter.now の形）。受け付けはこれより後の包みの起動を見る"""
    return f"ci-prepared-{safe_name(node)}.json"


def snapshot_name(node: str) -> str:
    return f"ci-snapshot-{safe_name(node)}.json"


# ---------------------------------------------------------------- 盤面
def _node(node: str) -> str:
    if node not in NODES:
        raise BoardGap(f"節 {node!r} は CI の節（{' / '.join(NODES)}）でない——blk-ci の node を確かめる")
    return node


def _open(board_dir, repo=None, *, allow_halted=False):
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=allow_halted)
    if repo is not None:
        _util.GIT_CWD = str(pathlib.Path(repo).resolve())   # 写しの engine の git（copy_worktree・規則）を対象に向ける
    return b


def _waiting(b, node: str) -> dict:
    """任せ先に落ちて待っている node の instance。無ければ BoardGap（blk-ci は start の ci_role_go・final の role_needed の時だけ開く）"""
    inst = b.rd["instances"].get(_node(node))
    if not (inst and inst.get("status") == "pending" and inst.get("engine_fallback")):
        raise BoardGap(f"{node} は任せ先に落ちて待っていない——blk-ci は start の ci_role_go が真の時（p0.local_checks）と、"
                       "blk-tests の final の by が role_needed の時（p4.ci）だけ開く")
    return inst


def _write_json(path: pathlib.Path, obj) -> pathlib.Path:
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


def _snap(b, node: str) -> dict:
    doc = _read_json(b.work(snapshot_name(node)))
    if not (isinstance(doc, dict) and set(TREE_KEYS) <= set(doc) and doc.get("copy")):
        raise BoardGap(f"{b.work(snapshot_name(node))} が無い・形が違う——ci-snap が先に走る（役を起こす前の作業ツリーと比べられない）")
    return doc


# ---------------------------------------------------------------- ci-fence
def _declared(b):
    """(run が宣言した包みの形, 読めない理由)。読めれば理由は ""（entry.declared_adapter）"""
    try:
        return entry.declared_adapter(b), ""
    except ValueError as e:
        return None, f"run が宣言した包みの形（adapter）が読めない: {e}"


def fence(board_dir, node: str, repo) -> dict:
    """役を起こす前に、run が宣言した包みの形を読む（起こす claude の道は見ない。裁定 R58）。出力 adapter は読んだ形で、YAML が
    with: で ci-accept と collect に渡す（役を起こした後に控えを読み直さない。再審査 N8）。
    - 包みを宣言した run（adapter が空）: 切符が在れば {go: True, reason: "", note: "", adapter: ""}。無ければ盤面を止める
    - 包み無しを宣言した run（adapter: optional）: {go: True, reason: "", note: NO_ADAPTER_NOTE, adapter: "optional"}
    - 宣言が読めない: 盤面を止めて（by FENCE_BY）{go: False, reason, note: "", adapter: ""}。YAML は go が偽なら役の輪を飛ばす"""
    b = _open(board_dir, repo)
    _waiting(b, node)
    mode, why = _declared(b)
    if mode == "":
        try:
            if adapter.read_ticket(pathlib.Path(repo)) is None:
                why = f"切符が無い（{adapter.ticket_path(pathlib.Path(repo))}。線の start が書く）——包みは旗 no-tree-write の役を起こさない"
        except adapter.BadTicket as e:
            why = str(e)
    if why:
        reason = f"包みの確かめが通らない: CI の任せ先の役（{node}）を起こさない（{why}）"
        b.stop(reason, by=FENCE_BY)
        return {"go": False, "reason": reason, "note": "", "adapter": ""}
    return {"go": True, "reason": "", "note": _note(mode), "adapter": mode}


def _note(mode: str) -> str:
    return NO_ADAPTER_NOTE if mode == "optional" else ""


# ---------------------------------------------------------------- ci-snap
def _make_copy(node: str) -> dict:
    """写しの置き場 <一時の置き場>/<COPY_PREFIX><節>-XXXX/ に work（copy_worktree の写し）と tmp を作る。写せなければ写しの Reject"""
    top = pathlib.Path(tempfile.mkdtemp(prefix=f"{COPY_PREFIX}{safe_name(node)}-"))
    try:
        work = _util.copy_worktree(top / "work")
        (top / "tmp").mkdir()
    except BaseException:
        shutil.rmtree(top, ignore_errors=True)
        raise
    return {"top": str(top), "copy": str(work), "tmp": str(top / "tmp")}


def snapshot(board_dir, node: str, repo) -> dict:
    """役を起こす前: 本物の作業ツリーの姿（accept.tree_state）と写しの置き場を ci-snapshot-<節>.json に。Archon の再開で走り直しても
    最初の姿を残す（役が変えた後の姿で置き換えない）。写しが消えていれば作り直す。返り {ok, snapshot_file, copy_dir}"""
    b = _open(board_dir, repo)
    _waiting(b, node)
    p = b.work(snapshot_name(node))
    doc = _read_json(p)
    if not (isinstance(doc, dict) and set(TREE_KEYS) <= set(doc)):
        doc = {"node": node, **tree_state(pathlib.Path(repo))}
    if not (doc.get("copy") and pathlib.Path(doc["copy"]).is_dir()):
        doc.update(_make_copy(node))
    _write_json(p, doc)
    return {"ok": True, "snapshot_file": str(p), "copy_dir": doc["copy"]}


# ---------------------------------------------------------------- ci-prep
def _asking(b) -> list:
    """台帳の kind=awaiting・origin=local_checks の未決の問い（p4.ci の指示書の穴。写しの check_record と同じ引き方）"""
    V = validator_module(b)
    return [q for q in b.record.get("questions") or []
            if q.get("kind") == "awaiting" and q.get("origin") == "local_checks" and q.get("status") in V.ASKING]


def render(b, node: str, repo, snap: dict, fallback: str) -> str:
    """blk-ci/prompts/<節>.md の穴を埋めた本文。穴の無い指示書・埋まらない穴は BoardGap"""
    text = (PROMPTS / f"{node}.md").read_text(encoding="utf-8")
    holes = {"node": node, "root": str(pathlib.Path(repo).resolve()), "copy": snap["copy"], "tmp": snap["tmp"],
             "fallback": fallback}
    if node == "p4.ci":
        answers = (b.record.get("process") or {}).get("human_answers") or []
        asking = _asking(b)
        holes.update(base=b.record.get("base") or "（無し）",
                     answers=json.dumps(answers, ensure_ascii=False) if answers else "（無し）",
                     questions=json.dumps(asking, ensure_ascii=False) if asking else "（無し）")
    for k, v in holes.items():
        if f"<<{k}>>" not in text:
            raise BoardGap(f"指示書 {node}.md に穴 <<{k}>> が無い")
        text = text.replace(f"<<{k}>>", str(v))
    return text


def prep(board_dir, node: str, repo) -> dict:
    """役を起こす前の支度: 指示書を描き（この周のこの節の拒否が在れば最後の拒否の文を頭に）、起こした印を置く。
    拒否の後の出し直しは同じ試行なので印は前の物（already: true）。返り {prompt_file, attempt, out_path, node, already}"""
    b = _open(board_dir, repo)
    inst = _waiting(b, node)
    text = render(b, node, repo, _snap(b, node), inst["engine_fallback"])
    last = _rejects(b, node)[-1:]
    if last:
        # 拒否の文は指示書のファイルに書く（役は Read で読む）。$LOOP_PREV で貼ると、文の中の $<節>.output.<欄> を Archon が
        # 置き換え直して輪ごと落ちる（裁定 R44）
        text = (f"{REJECT_HEADING}\n\n前の回の返答は受け付けで拒まれた。下の理由のところを直した返答を丸ごと出し直せ"
                f"（直した所だけを返すな）:\n\n```text\n{last[0]['reason']}\n```\n\n---\n\n" + text)
    path = b.dir / "prompts" / f"r{b.round}" / (safe_name(node) + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _write_json(b.work(prepared_name(node)), {"node": node, "at": adapter.now()})
    m = b.mark_launched(node, inst.get("attempts", 1))
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": node,
            "already": m["already"]}


# ---------------------------------------------------------------- ci-accept
def _rejects(b, node: str) -> list:
    return [r for r in _read_json(b.work(REJECTS), []) if r.get("node") == node]


def _reject(b, node: str, reason: str) -> dict:
    """拒否の文を ci-rejects.json に積んで {ok: False, done, give_up, reason, node, status} を返す。この周のこの節の拒否が
    GIVE_UP_AFTER 回に達したら give_up（done）——輪はそこで抜け、collect が最後の拒否の文で盤面を止める"""
    rows = _read_json(b.work(REJECTS), [])
    inst = b.rd["instances"].get(node) or {}
    rows.append({"node": node, "attempt": inst.get("attempts", 1), "at": now(), "reason": reason})
    _write_json(b.work(REJECTS), rows)
    give_up = sum(1 for r in rows if r.get("node") == node) >= GIVE_UP_AFTER
    return {"ok": False, "done": give_up, "give_up": give_up, "reason": reason, "node": node, "status": ""}


def take(board_dir, node: str, reply: dict, repo, mode: str) -> dict:
    """役の返答を受け付ける。mode は ci-fence が読んだ包みの形（YAML の with: で届く。start の控えは読み直さない——再審査 N8）。
    順: 包みを宣言した run（mode が空）ならこの試行の役の起動に包みの柵が掛かったか（無ければ・mode が宣言の語でなければ
    盤面を止めて done。包み無しの run では見ない） → 本物の作業ツリーを
    ci-snap の姿と比べる → 盤面の done（写しの schema・post_check・check_record）。
    拒否（作業ツリーの変化・写しの AnswerReject）は {ok: False, done, give_up, reason} で返し、盤面の層のファイルは書かない
    （拒否の文は作業ファイル ci-rejects.json に積む）。ほかの Reject（止めた run など）・BoardGap は投げる（回す側の誤り）。
    通れば {ok: True, done: True, give_up: False, reason: "", node, status}"""
    b = _open(board_dir, repo)
    _waiting(b, node)
    snap = _snap(b, node)
    prepared = _read_json(b.work(prepared_name(node)))
    if not (isinstance(prepared, dict) and prepared.get("at")):
        raise BoardGap(f"{b.work(prepared_name(node))} が無い——ci-prep が先に走る（役の起動の記録と突き合わせられない）")
    why = ""
    if mode not in entry.ADAPTER_MODES:
        why = f"ci-fence が渡した包みの形 adapter={mode!r} は宣言の語（空か optional）でない"
    elif mode == "":
        why = adapter.fenced_launch(pathlib.Path(repo), ROLE, prepared["at"])
        if why:
            why = f"包みの柵が CI の任せ先の役の起動に掛かっていない: {why}"
    if why:
        reason = f"{why}——返答を受けず盤面を止める"
        b.stop(reason, by=FENCE_BY)
        return {"ok": False, "done": True, "give_up": False, "reason": reason, "node": node, "status": ""}
    before = {k: snap[k] for k in TREE_KEYS}
    moved = tree_moved(before, pathlib.Path(repo))   # 共通の比べ（R47。HEAD が引けなくなったのもここで 1 行になる）
    if moved:
        return _reject(b, node, f"読むだけの役が作業ツリーを変えた: CI の任せ先はテストを写し {snap['copy']} の上で走らせ、対象の"
                                "作業ツリー・HEAD・枝・git が無視するファイルを変えてはいけない（変えた物を元に戻し、写しの上で走らせ直せ）（"
                       + "・".join(moved) + "）")
    try:
        b.done(node, reply)
    except AnswerReject as e:
        return _reject(b, node, str(e))
    return {"ok": True, "done": True, "give_up": False, "reason": "", "node": node,
            "status": reply["material"]["status"]}


def refuse(board_dir, node: str, reason: str) -> dict:
    """返答を受け付けの前に拒む（読めない返答）。拒否の文は take の拒否と同じく ci-rejects.json に積む"""
    b = _open(board_dir)
    _waiting(b, node)
    return _reject(b, node, reason)


# ---------------------------------------------------------------- collect
def _drop_copy(snap) -> None:
    """写しの置き場を消す（一時の置き場の直下の COPY_PREFIX で始まるフォルダだけ。symlink は辿らない）"""
    top = (snap or {}).get("top")
    if not top or os.path.islink(top):
        return
    real = os.path.realpath(top)
    if os.path.dirname(real) == os.path.realpath(tempfile.gettempdir()) and os.path.basename(real).startswith(COPY_PREFIX):
        shutil.rmtree(real, ignore_errors=True)


def collect(board_dir, node: str, mode: str) -> dict:
    """ブロックの出口 {ok, reason, node, status, green, pr_go, note}。写しを消す。mode は ci-fence が読んだ包みの形（YAML の with: で
    届く。再審査 N8）で、note は包み無し（optional）の知らせ NO_ADAPTER_NOTE か空。mode が宣言の語でなければ BoardGap（配線の誤り）。
    - 節を受けた: status は素材の status、green は clean か。p0.local_checks なら entry.resume_after_ci で start の輪に戻り
      （p0.parallel_pr などを走らせて settle）、pr_go（True・False・"pending"）をラインに渡す。p4.ci の pr_go は False
    - 受けていない（輪が 3 回とも拒まれた）: 最後の拒否の文で盤面を止めて（by works:ci）ok: false
    - 受けていないのに盤面が既に止まっている: ok: false（止めた理由を reason に）。受けた後に止まった（p4.ci の後の
      stop_after_round）は受けた扱い"""
    if mode not in entry.ADAPTER_MODES:
        raise BoardGap(f"ci-fence が渡した包みの形 adapter={mode!r} は宣言の語（空か optional）でない——blk-ci の with: を確かめる")
    b = _open(board_dir, allow_halted=True)
    _node(node)
    _drop_copy(_read_json(b.work(snapshot_name(node))))
    out = {"ok": False, "reason": "", "node": node, "status": "", "green": False, "pr_go": False, "note": _note(mode)}
    inst = b.rd["instances"].get(node) or {}
    stop = b.state.get("stop") or b.state.get("halted")
    if inst.get("status") != "done" and stop:
        return {**out, "reason": f"盤面は止まっている（{stop.get('by')}: {stop.get('reason')}）"}
    if inst.get("status") != "done":
        rejects = _rejects(b, node)
        if inst.get("launched_at") and rejects:
            reason = f"{node} の返答が {len(rejects)} 回とも受け付けで拒まれた（最後の拒否: {rejects[-1]['reason']}）"
        else:
            reason = f"{node} の任せ先の役の返答を受けていない（輪が回らなかった）"
        b.stop(reason, by=STOP_BY)
        return {**out, "reason": reason}
    status = ((b.record.get("materials") or {}).get("local_checks") or {}).get("status", "")
    out.update(ok=True, status=status, green=status == "clean")
    if node == "p0.local_checks" and not stop:
        try:
            out["pr_go"] = entry.resume_after_ci(b)["pr_go"]
        except entry.InputRefused as e:
            b.stop(f"CI の役の後に start の輪へ戻れない: {e}", by=STOP_BY)
            return {**out, "ok": False, "reason": f"CI の役の後に start の輪へ戻れない: {e}"}
    return out
