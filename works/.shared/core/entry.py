"""線の入口の口（線 A の仕様 4 節。盤面の層の仕様 4.2・4.4）: ラインの節の表を読み、盤面をラインの名前を知らずに開く。

- load_table(line):   PACK/<line>/nodes.json を読み、盤面の層の縛り 1〜5（NodeTable.check）を当てる。破れは全部を 1 つの BoardGap に
- open_board(dir):    盤面の state.works.line から表を引き、表の sha が state.works.table_sha と合わなければ BoardMismatch。
                      open_kwargs(line, table)（board_hook.py の返りと核の差し替え）を DiskBoard.open に渡す
- hook_kwargs(line):  board_hook.py の読み込みだけ（無ければ {}）
- open_kwargs(line):  hook_kwargs に線 A の核の差し替え CORE_OVERRIDES（読んだ記録の置き場・直す義務・関所の項目の決め手・R3・R4 の起動条件）を重ねた物。open_board と start が
                      同じ物を DiskBoard.open・begin に渡す（開くたびに同じ overrides。BL-R3）
- check_inputs(raw, repo, *, reads): ラインの入力を確かめる（線 A の仕様 4 節）。拒めば InputRefused（人に向けた 1 行）
- local_checks_material(repo, test_cmd, log_path): 任せ先に落ちた CI の節（p0.local_checks・p4.ci）に渡す素材を組む公開の口
  （盤面なしで呼べる。線 B の申し送り 2）
- run_ci(b, nid, *, test_cmd): CI の節を run_engine で走らせ、返りを全部扱う（start と blk-tests の final が使う）
- suites_line(tests, *, role_status): 最後のテストが走らせた一式と走らせなかった物の 1 行（報告の冒頭と最後の関所が使う）
- start(board_dir, repo, raw, *, run_id): 入力の確かめ → 盤面を開く → 修正前のテストの記録 → 方針の文 → 切符
- resume_after_ci(b): 任せ先の CI の役が p0.local_checks を渡した後、ラインが start の輪（run_engine → settle）に戻る口
- snapshot(board_dir, name, repo): 読むだけの役を起こす前に、作業ツリーの姿（accept.tree_state）を今の周の b.work(name) に
- take(board_dir, nid, reply, repo, *, snapshot_name): 各ブロックの受け付けが使う 1 つの口。役の返答を盤面の done に渡す
  （写しの AnswerReject だけを {ok: False} で役に返す。裁定 TA19）
- hand(b, board_dir, nid, reply, repo): 機械が返答を渡す 1 つの口（待っている試行 board.pending_instance に起こした印を置いてから take）
- empty_fix_reply(): 直す義務 0 件の周に機械が渡す p3.fix の空の返答（裁定 TA6）

ブロックのスクリプトは open_board で盤面を開く。線 B のライン（darkfactory-rounds）でも同じブロックが同じ口で動く。
"""
import importlib.util
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys

sys.dont_write_bytecode = True   # board_hook.py の読み込みで pack の中に __pycache__ を作らない

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import board  # noqa: E402  （run_ci の既定の runner board.tree_runner を呼ぶ時に引く）
from board import BoardGap, BoardMismatch, DiskBoard, NodeTable, graph_expanded, graph_path, graph_sha  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import engine.util as _util  # noqa: E402
from engine.commands import _refuse_halted  # noqa: E402  （board.py と同じ入口の拒み。写しの engine の関数）
from engine.rules import cond_reads  # noqa: E402
from engine.util import AnswerReject, Reject, safe_name  # noqa: E402
import accept  # noqa: E402
import conflict  # noqa: E402
import gatemarks  # noqa: E402
import ghreads  # noqa: E402
from ghreads import request_parts  # noqa: E402
import policy  # noqa: E402
import prcheck  # noqa: E402
import ticket  # noqa: E402
import tree_run  # noqa: E402

PACK = pathlib.Path(__file__).resolve().parents[2]   # works/（Archon は run ごとに pack を写すので、今の写しの置き場）
TABLE_NAME = "nodes.json"
HOOK_NAME = "board_hook.py"
HOOK_KEYS = ("overrides", "validator_runner")      # board_kwargs が返してよい鍵（DiskBoard.open・create の引数）
_LINE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _line_dir(line) -> pathlib.Path:
    """ラインの置き場。名前は盤面から来るので、pack の外を指す名前（/・..・空）を拒む"""
    if not isinstance(line, str) or not _LINE_NAME.fullmatch(line):
        raise BoardGap(f"ラインの名前 {line!r} が読めない（英数字・_・- だけ）")
    return PACK / line


def load_table(line: str) -> NodeTable:
    """PACK/<line>/nodes.json を読む。形の誤りは NodeTable.load の BoardGap、縛り 1〜5 の破れと line の違いは全部を並べた BoardGap"""
    path = _line_dir(line) / TABLE_NAME
    table = NodeTable.load(path)
    errs = table.check(graph_expanded(graph_path(table.graph)), graph_sha(table.graph))   # 表が名指す graph（無ければ既定）
    if table.line != line:
        errs.append(f"表の line {table.line} がラインの置き場の名前 {line} と違う")
    if errs:
        raise BoardGap(f"節の表 {path} が縛りに当たる（{len(errs)} 件）: " + "; ".join(errs))
    return table


def hook_kwargs(line: str, table: NodeTable | None = None) -> dict:
    """PACK/<line>/board_hook.py の board_kwargs(table) の返り（無ければ {}）。毎回新しく読み、sys.modules に残さない。
    返りは dict で、鍵は overrides・validator_runner だけ（ほかの鍵・読めない hook は BoardGap）。table を渡さなければ load_table(line)"""
    path = _line_dir(line) / HOOK_NAME
    if not path.is_file():
        return {}
    if table is None:
        table = load_table(line)
    try:
        spec = importlib.util.spec_from_file_location(f"_works_board_hook_{line.replace('-', '_')}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        raise BoardGap(f"{path} を読み込めない: {e!r}") from e
    fn = getattr(mod, "board_kwargs", None)
    if not callable(fn):
        raise BoardGap(f"{path} に board_kwargs(table) が無い")
    try:
        kw = fn(table)
    except BoardGap:
        raise
    except Exception as e:   # hook の中の誤りも内部の誤り（スクリプトは終了コード 2。TA19）
        raise BoardGap(f"{path} の board_kwargs が落ちた: {e!r}") from e
    if not isinstance(kw, dict):
        raise BoardGap(f"{path} の board_kwargs の返りが dict でない: {type(kw).__name__}")
    unknown = sorted(set(kw) - set(HOOK_KEYS))
    if unknown:
        raise BoardGap(f"{path} の board_kwargs が知らない鍵を返した: {', '.join(map(str, unknown))}（{' / '.join(HOOK_KEYS)} だけ）")
    return kw


def _hook_evidence_at_adapter(board_dir, doc, cache=None, data=None):
    """写しの RL の hook_evidence の差し替え。受けた board_dir（盤面の置き場）を捨て、包みのフックが書く置き場
    adapter.reads_dir(run の worktree) を写しの util.hook_evidence に渡す（残りの引数はそのまま）。run の worktree は
    盤面を開いた時の util.GIT_CWD（DiskBoard.open が inputs.cwd か repo を入れる）、無ければ cwd。包みの子の env には
    ARTIFACTS_DIR が来ないので、フックは盤面の隣に書けない（adapter.py の頭）"""
    import adapter
    return _util.hook_evidence(adapter.reads_dir(_util.GIT_CWD or os.getcwd()), doc, cache, data)


def _overview_due_after_fix(rl):
    """写しの RL の overview_due の組み手（CONDS の差し替え。DiskBoard._apply_overrides が開いた RL を渡す）。元の条件が偽でも、
    この周の p3.fix_delta が測った修正の差分が 1 ファイル以上なら真。式は写さず、RL の overview_due と fix_delta_nonempty を呼ぶ"""
    base, delta = rl.overview_due, rl.fix_delta_nonempty

    @cond_reads(*dict.fromkeys(base.reads + delta.reads))
    def overview_due(v):
        ok, why = base(v)
        if ok:
            return ok, why
        ok, fixed = delta(v)
        return ok, f"{why}・{fixed}"
    return overview_due


# 線 A の核が写しの RL に当てる差し替え（名前 → (関数, 理由)）。ラインの board_hook.py の overrides が同じ名前を持てば、そちらが勝つ
CORE_OVERRIDES = {
    "hook_evidence": (_hook_evidence_at_adapter,
                      "読んだ記録は盤面の隣でなく包みの置き場 adapter.reads_dir(run の worktree)/reads.jsonl に在る（Task 6 の直し 1）"),
    "_owed_units": (conflict.owed_units_but_asked,
                    "食い違いの申し出を裁定役か機械が ask_human に裁いた単位は、直す義務から外す（最後の人の関所で人が決める。"
                    "conflict.py）。修正前の関所で答えた fork の出どころ・depends は直す義務に戻す（gatemarks.returned）"),
    "_plan_gate_items": (gatemarks.plan_gate_items,
                         "決め手の出どころが在り undecided_because が空で柵の印の無い狭め・穴は、修正前の関所で人に聞かずに通し、"
                         "state.works.gate_passes に残す（持ち主 2026-09-28。gatemarks.py）。問いの台帳で人に聞く状態の fork・"
                         "escalate は、無人の run でなければ項目に載せる（持ち主 2026-09-29）。設計だけの run（入力 design_only）は"
                         "項目の有無に関わらず設計だけの行を載せて関所を開ける（持ち主 2026-09-30）"),
    "_r4_gate_items": (board.rl_builder(gatemarks.r4_gate_items),
                       "写しの元は人が通した行を頭込みの文で照らし、修正前の関所の行（修正案 N が狭める能力: …）と R4 の行"
                       "（R4 が BASE から消えたと見た能力: …）は頭が違うので、人が continue で通した同じ狭めを聞き直す。頭を除いた本文と"
                       "種類で照らして外し、gate_passes に by human で残す（gatemarks.py）"),
    "overview_due": (_overview_due_after_fix,
                     "works の run は同じ周で修正してから R3・R4 を回すので、前の周の P3 だけを引き金にすると 1 周の run では目が"
                     "起きない。この周の修正の差分（p3.fix_delta が差分から測った実測。自己申告でない）が空でない周も起こす。"
                     "p4.assemble が修正の後の差分を取り直してから R3・R4 に渡す"),
}


def open_kwargs(line: str, table: NodeTable | None = None) -> dict:
    """DiskBoard.open・begin に渡す引数: hook_kwargs(line, table) の返りに、overrides として CORE_OVERRIDES を重ねた物
    （board_hook.py の overrides が同じ名前なら board_hook の方）。open_board と start がこれを使う（開くたびに同じ。BL-R3）"""
    kw = hook_kwargs(line, table)
    return {**kw, "overrides": {**CORE_OVERRIDES, **(kw.get("overrides") or {})}}


def open_board(board_dir: pathlib.Path, *, allow_halted: bool = False) -> DiskBoard:
    """盤面を開く。表は state.works.line のラインの nodes.json。表の sha が盤面を作った時の state.works.table_sha と違えば
    BoardMismatch（run の途中で表が替わった盤面を、替わった表で回さない）。open_kwargs の返りを DiskBoard.open に渡す"""
    d = pathlib.Path(board_dir)
    try:
        state = json.loads((d / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"{d / 'state.json'} を読めない: {e}") from None
    works = state.get("works") if isinstance(state, dict) else None
    line = works.get("line") if isinstance(works, dict) else None
    if line is None:
        raise BoardGap(f"盤面 {d} に state.works.line が無い（works の盤面でない）")
    table = load_table(line)
    want, got = works.get("table_sha"), table.sha()
    if want != got:
        raise BoardMismatch(f"盤面 {d} の表の sha {want} が今のライン {line} の表の {got} と違う"
                            f"（盤面を作った後に {line}/{TABLE_NAME} が替わった。替わった表で回さない）")
    return DiskBoard.open(d, table=table, allow_halted=allow_halted, **open_kwargs(line, table))



# ---------------------------------------------------------------- 入力の確かめ（線 A の仕様 4 節）
LINE = "darkfactory"
ORIGIN = "works/darkfactory"   # 依頼の出どころ（record.process.request_entry.origin）
THICKNESS = ("軽量", "標準", "重厚")
THICKNESS_DEFAULT = "標準"
FINAL_GATES = ("always", "when_needed", "protected_only")   # 最後の人の関所の開き方（C18・P1-R3。line_edge.FINAL_GATES と同じ語）
ADAPTER_MODES = ("", "optional")
UNATTENDED_WORDS = ("", gatemarks.UNATTENDED)   # 入力 unattended（空は人の居る run。true は無人の殻 use.sh の WORKS_USE_UNATTENDED=1）
DESIGN_ONLY_WORDS = ("", gatemarks.DESIGN_ONLY)   # 入力 design_only（空は今どおり。true は修正前の関所を必ず開ける設計だけの run）
GATES = ("", "merge")
LIGHT_REFUSED = "軽量は受けない: graph で省けない節を省くことになる（持ち主の決定 2026-09-27）"
HEAVY_REFUSED = "重厚で足す工程がまだ無い"
CI_BUILTIN = "declared_checks"   # 写しの graph の engine_run.builtin のうち、CI の節（p0.local_checks・p4.ci）の語


class InputRefused(Exception):
    """入力を受けない（AI を起こす前に run を止める）。文は人に向けた 1 行"""

    def __init__(self, msg):
        super().__init__(" ".join(str(msg).split()))


class CiRefused(InputRefused):
    """CI の節を engine で走らせられない（2 度とも計画が拒まれた・why だけの返り）。start では入力の拒みと同じく AI の前で止める"""


def _word(raw: dict, key: str) -> str:
    v = raw.get(key)
    return "" if v is None else str(v).strip()


def check_inputs(raw: dict, repo: pathlib.Path, *, reads=None) -> dict:
    """ラインの入力を確かめて {request_file, items, request_text, test_cmd, thickness, gates, final_gate, adapter, policy_md, lang,
    unattended, design_only} を返す（unattended・design_only は start の控え r1/start.json に残り、gatemarks が修正前の関所で読む）。
    変更（base の版か pr の番号）を名指せば {base_rev, change} も足す（base_rev は base と HEAD の merge-base）。依頼と変更は
    少なくとも 1 つが要り、依頼が無ければ request_file・request_text は空・items は []。
    盤面は作らない。拒む物（InputRefused）: 依頼も変更も無い・base と pr の両方・版や PR が引けない・PR の head が HEAD でない、
    依頼が読めない・findings の配列でも {findings, pr, issue} の形でもない・findings が依頼の型（写しの RL の REQUEST_SCHEMA）に
    合わない、thickness が軽量・重厚・知らない値、final_gate・adapter・unattended・design_only・gates が語の外（gates の文は写しの RL の check_inputs）、
    名指した方針の文書が無い。test_cmd が空で宣言（.review-checks.json）も無い run は拒まない（裁定 R52: graphloops と同じく
    p0.local_checks・p4.ci が任せ先の役に落ち、役がリポジトリを読んでテストの走らせ方を探す）。
    相対のパス（依頼・方針の文書）は対象の根 repo から。reads は殻が隔離の前に読んだ写し（ghreads.load の返り。pr が読む）"""
    repo = pathlib.Path(repo)
    thickness = _word(raw, "thickness") or THICKNESS_DEFAULT
    if thickness == "軽量":
        raise InputRefused(LIGHT_REFUSED)
    if thickness == "重厚":
        raise InputRefused(HEAVY_REFUSED)
    if thickness not in THICKNESS:
        raise InputRefused(f"thickness={thickness!r} は知らない値（{' / '.join(THICKNESS)}。受けるのは {THICKNESS_DEFAULT} だけ）")
    final_gate = _word(raw, "final_gate") or FINAL_GATES[0]
    if final_gate not in FINAL_GATES:
        raise InputRefused(f"final_gate={final_gate!r} は知らない値（{' / '.join(FINAL_GATES)}）")
    adapter = _word(raw, "adapter")
    if adapter not in ADAPTER_MODES:
        raise InputRefused(f"adapter={adapter!r} は知らない値（空か optional）")
    unattended = _word(raw, "unattended")
    if unattended not in UNATTENDED_WORDS:
        raise InputRefused(f"unattended={unattended!r} は知らない値（空か {gatemarks.UNATTENDED}）")
    design_only = _word(raw, "design_only")
    if design_only not in DESIGN_ONLY_WORDS:
        raise InputRefused(f"design_only={design_only!r} は知らない値（空か {gatemarks.DESIGN_ONLY}）")
    gates = _word(raw, "gates")
    rules = board_rules()
    try:
        rules.check_inputs({"gates": gates} if gates else {})
    except Reject as e:
        raise InputRefused(f"gates: {e}") from None
    change = _change_base(raw, repo, reads)
    rel = _word(raw, "request")
    if not rel:
        if change is None:
            raise InputRefused("依頼（request）も変更（base・pr）も名指されていない——少なくとも 1 つを名指す")
        path, text, items = None, "", []
    else:
        path, text, items = _read_request(rel, repo, rules)
    pol = _word(raw, "policy_md")
    if pol:
        pp = pathlib.Path(pol) if pathlib.Path(pol).is_absolute() else repo / pol
        if not pp.is_file():
            raise InputRefused(f"名指した方針の文書 {pol} が無い（policy_md。人の方針の文書を名指すなら先に置く）")
        pol = str(pp)
    out = {"request_file": str(path.resolve()) if path else "", "items": items, "request_text": text,
           "test_cmd": _word(raw, "test_cmd"), "thickness": thickness, "gates": gates, "final_gate": final_gate,
           "adapter": adapter, "policy_md": pol, "lang": _word(raw, "lang"), "unattended": unattended,
           "design_only": design_only}
    if change is not None:
        out.update(change)
    return out


def _git(repo: pathlib.Path, *args) -> str:
    """repo で git を読むだけ呼ぶ。引けなければ InputRefused（1 行）"""
    got = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if got.returncode != 0:
        raise InputRefused(f"git {' '.join(args)} が引けない: {got.stderr.strip() or got.returncode}")
    return got.stdout.strip()


def _merge_base(repo: pathlib.Path, ref: str) -> str:
    """ref と HEAD の merge-base（GitHub の PR の three-dot と同じ差分の根）"""
    rev = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return _git(repo, "merge-base", rev, "HEAD")


def _change_base(raw: dict, repo: pathlib.Path, reads=None):
    """変更の入口（base か pr）を解いて {base_rev, change} を返す。どちらも無ければ None。両方は拒む。
    pr は gh を呼ばず、殻が隔離の前に読んだ写し reads（ghreads の読み出しのファイル）の pr[<番号>] を読む——隔離した Archon の
    中からは利用者の gh のログインが見えない（設計書 2.8）。写しに無い・読めなかった項・head が今の HEAD と違えば拒む（別の版を
    黙って見ない）。差分の根は GitHub が持つ base の版（baseRefOid）と HEAD の merge-base——fetch しないローカルの枝は古いことが
    あるので名前では引かない。change.text は PR の題と本文（目的の文の出典の PR 説明として盤面の依頼の文に渡す）"""
    base, pr = _word(raw, "base"), _word(raw, "pr")
    if base and pr:
        raise InputRefused(f"base={base!r} と pr={pr!r} を両方名指した——どちらの差分か決まらない（片方だけ）")
    if base:
        return {"base_rev": _merge_base(repo, base), "change": {"from": "base", "name": base, "text": ""}}
    if not pr:
        return None
    if not pr.isdigit():
        raise InputRefused(f"pr={pr!r} は PR の番号でない")
    doc = ((reads or {}).get("pr") or {}).get(pr)
    if not isinstance(doc, dict) or not doc.get("baseRefOid") or not doc.get("headRefOid"):
        why = (doc.get("reason") if isinstance(doc, dict) else "") or "隔離の前の読み出し（github_reads）にこの PR の base・head が無い"
        why = " ".join(str(why).split())
        raise InputRefused(f"PR #{pr} を読めない（{why}）——use.sh start --pr か ghreads.py read で読んでから"
                           " --input github_reads で渡す")
    head = _git(repo, "rev-parse", "HEAD")
    if doc["headRefOid"] != head:
        raise InputRefused(f"PR #{pr} の head {doc['headRefOid'][:12]} が対象の HEAD {head[:12]} と違う——PR の head を"
                           "取り出した所で始める")
    oid = doc["baseRefOid"]
    if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{oid}^{{commit}}"], capture_output=True).returncode:
        raise InputRefused(f"PR #{pr} の base の版 {oid[:12]} が対象に無い——fetch してから始める")
    text = "\n\n".join(s for s in (str(doc.get("title") or "").strip(), str(doc.get("body") or "").strip()) if s)
    return {"base_rev": _merge_base(repo, oid), "change": {"from": "pr", "name": pr, "text": text}}


def _read_request(rel: str, repo: pathlib.Path, rules):
    """依頼のファイルを読んで (path, text, items)。items は findings の行（配列の形も {findings, pr, issue} の形も
    request_parts で解く）。読めない・どちらの形でもない・依頼の型に合わない は InputRefused"""
    path = pathlib.Path(rel) if pathlib.Path(rel).is_absolute() else repo / rel
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise InputRefused(f"依頼のファイル {rel} が読めない（{type(e).__name__}: {e}）") from None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise InputRefused(f"依頼のファイル {rel} が JSON として読めない（{e}）") from None
    try:
        items = request_parts(doc)["findings"]
    except ValueError as e:
        raise InputRefused(f"依頼のファイル {rel} の形: {e}") from None
    errs = validate_schema([{"round": 1, "origin": ORIGIN, "findings": items}], rules.REQUEST_SCHEMA)
    if errs:
        raise InputRefused(f"依頼のファイル {rel} の形: findings の配列か {{findings, pr, issue}} の形で、findings は "
                           "[{where, text, mechanism?, measured?, false_positive_if?}] の配列（空でない）: " + "; ".join(errs))
    return path, text, items


def board_rules():
    """写しの RL（盤面なし。入口の検査に使う）"""
    from board import rules_module
    return rules_module()


# ---------------------------------------------------------------- CI の節（p0.local_checks・p4.ci）
TAIL_LINES = 20     # 素材の detail に写すログの末尾の行数（engine の role_run.TAIL_LINES と同じ値。private の _tail を import しない）
TAIL_BYTES = 2000   # その上限（バイト。role_run.TAIL_BYTES と同じ）


def _tail(data: bytes) -> str:
    """ログの末尾（engine の role_run._tail と同じ切り方: 末尾 TAIL_LINES 行の、さらに末尾 TAIL_BYTES 文字）"""
    text = data.decode("utf-8", "replace").rstrip()
    return "\n".join(text.splitlines()[-TAIL_LINES:])[-TAIL_BYTES:]


def local_checks_material(repo: pathlib.Path, test_cmd: str, log_path: pathlib.Path, *, launched: dict | None = None) -> dict:
    """任せ先に落ちた CI の節に渡す素材 {"material": …} を組む（盤面なしで呼べる公開の口。線 B の申し送り 2）。
    test_cmd を tree_run.command_argv の形（direct か shell）で tree_run.slotted_run に走らせ（機械全体の試験の枠を通す・対象の根で・
    標準入力は空・環境は tree_run.outside_env。
    標準出力と標準エラーを log_path に）、終了コード 0 なら clean（写しの RR の規則で checked が要る）、他は found・count 1。
    detail はログの末尾（engine の段の末尾と同じ切り方）。起こせなければ（shell の先頭の語が tree_run.prove_launchable の証明を
    通らない回も）not_run。test_cmd が空なら走らせずに not_run。
    止められたら（tree_run.Stopped）捕まえない。launched（dict）を渡せば、起こす前に決めた起こし方を launched["how"] に置く
    （返りの素材の形は変えない）"""
    cmd = (test_cmd or "").strip()
    if not cmd:
        return {"material": {"status": "not_run", "reason": "テストのコマンド（test_cmd）が空で、走らせる物が無い"}}
    log_path = pathlib.Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    argv, how = tree_run.command_argv(cmd)
    if launched is not None:
        launched["how"] = how
    with open(log_path, "wb") as f:
        try:
            code, _ = tree_run.slotted_run(argv, tree_run.outside_env(os.environ), stdin=subprocess.DEVNULL,
                                           stdout=f, stderr=subprocess.STDOUT, cwd=str(repo))
        except OSError as e:
            return {"material": {"status": "not_run", "reason": f"{_launched(argv, how)} でテストのコマンドを起こせない: {e}"}}
    return _cmd_material(code, log_path, argv, how)


def _launched(argv: list, how: str) -> str:
    return f"{shlex.join(argv)}（起こし方 {how}{'。' + tree_run.DIRECT_HINT if how == 'direct' else ''}）"


def _cmd_material(code: int | None, log_path: pathlib.Path, argv: list, how: str) -> dict:
    """走らせ終えた test_cmd の終了コードとログから素材を組む（local_checks_material と、engine が既に走らせた test_cmd の段を
    使い回す _ci_by_cmd の共通）。argv・how は起こした時に決めた値（読む時に規則で作り直さない）。
    分け方は tree_run.launch_kind: 起こせない（exit None）は not_run"""
    argv = list(argv)
    tail = _tail(log_path.read_bytes())
    kind = tree_run.launch_kind(code)
    if kind == "broken":
        return {"material": {"status": "not_run",
                             "reason": f"{_launched(argv, how)} でテストのコマンドを起こせない（exit None。ログ {log_path}）"}}
    ran = f"{shlex.join(argv)}（起こし方 {how}）を対象の根で走らせた: exit {code}（ログ {log_path}）"
    if kind == "clean":
        return {"material": {"status": "clean", "count": 0, "checked": ran, "detail": tail}}
    return {"material": {"status": "found", "count": 1, "detail": f"{ran} ／ 末尾: {tail}"}}


def _engine_log(b, nid: str, runs: list) -> pathlib.Path:
    """engine が走らせた全部の段の標準出力と標準エラーを 1 つのログ r<N>/<節>.log に並べる（2 段目の赤・標準エラーだけの出力も
    見えるように。段ごとの元のファイルは runs[].out・err のまま残る）。走らせなかった回（宣言が読めない）は素材の理由を書く"""
    log = b.work(safe_name(nid) + ".log")
    parts = []
    for i, r in enumerate(runs, 1):
        how = f"（起こし方 {r['how']}）" if r.get("how") else ""
        parts.append(f"== 段 {i} {r.get('name')}{how}: {json.dumps(r.get('argv'), ensure_ascii=False)} → exit {r.get('exit')}\n")
        if r.get("error"):
            parts.append(f"起こせない: {r['error']}\n")
        for key in ("out", "err"):
            src = r.get(key)
            body = pathlib.Path(src).read_text(encoding="utf-8", errors="replace") if src and pathlib.Path(src).is_file() else ""
            parts.append(f"--- {'標準出力' if key == 'out' else '標準エラー'}（{src}）\n{body}")
            if body and not body.endswith("\n"):
                parts.append("\n")
    if not runs:
        m = (b.record.get("materials") or {}).get("local_checks") or {}
        parts.append(f"engine は宣言の段を走らせなかった: {m.get('reason') or m.get('detail') or m.get('checked') or ''}\n")
    log.write_text("".join(parts), encoding="utf-8")
    return log


TEST_CMD_STEP = "test_cmd"


def _same_step(steps: list, argv: list, how: str) -> str | None:
    """test_cmd を直に起こす形（how が direct）の argv が宣言の段の argv と同じなら、その段の名（同じコマンドを
    2 度走らせない）。シェルを通す test_cmd は宣言の段（シェルを通さない）と同じにならない"""
    if how != "direct":
        return None
    return next((s.get("name") for s in steps if list(s.get("argv") or []) == argv), None)


def _with_test_cmd(runner, test_cmd: str, note: dict):
    """board.run_engine の runner (steps, cwd, log_dir) -> runs を包み、宣言の段の後に test_cmd の段を 1 つ足す。宣言の sha の
    照合は runner の前に宣言の steps だけに掛かるので変わらない。runner は steps + [test_cmd の段] で 1 度だけ呼ぶ（ログは段の
    番号で分かれる）。test_cmd が宣言の段と同じコマンドなら足さず、note["same_as"] にその段の名を置く。test_cmd が空なら足さない。
    段の起こし方 how は起こす前に決め（足す段は tree_run.command_argv の値、宣言の段は engine が shell を通さないので direct）、
    走った行に写す（runner の行の形は engine の run_steps と同じに保つので、写すのはこの包みの側）"""
    cmd = (test_cmd or "").strip()
    argv, how = tree_run.command_argv(cmd) if cmd else (None, None)

    def run(steps, cwd, log_dir):
        note["same_as"] = _same_step(steps, argv, how) if cmd else None
        extra = [{"name": TEST_CMD_STEP, "argv": argv, "how": how}] if cmd and not note["same_as"] else []
        hows = ["direct"] * len(steps) + [s["how"] for s in extra]
        rows = (runner or board.tree_runner)(list(steps) + extra, cwd, log_dir)
        return [{**r, "how": h} for r, h in zip(rows, hows)]
    return run


def env_only_red(tests: dict | None) -> bool:
    """最後のテストの赤が、全部起こせなかった段（tree_run.launch_kind の broken）だけから来ているか"""
    kinds = [_suite_kind(s) for s in (tests or {}).get("suites") or []]
    bad = [k for k in kinds if k != "clean"]
    return bool(bad) and all(k == "broken" for k in bad)


def _suite_kind(s: dict) -> str:
    """段 {name, exit, how?, launch?} の分類（tree_run.launch_kind。exit None は broken、他は clean・red）。前の版の記録に残る
    launch の値は読まない（分類は終了コードだけで決まる）"""
    return tree_run.launch_kind(s.get("exit"))


def role_ci_status(b, tests: dict | None) -> str | None:
    """最後のテストが by role_needed で、任せ先の CI の役が p4.ci を渡し終えていれば素材 materials.local_checks の status
    （無ければ ""）、それ以外は None。報告の冒頭と最後の関所が同じ盤面を読む"""
    if (tests or {}).get("by") != "role_needed" or b.node_state("p4.ci") != "done":
        return None
    return ((b.record.get("materials") or {}).get("local_checks") or {}).get("status") or ""


def baseline_line(b) -> str:
    """修正前の CI（P0 の結果。写しの graph が process.baseline_checks に残し、materials.local_checks は P4 で書き直される）の 1 行。
    報告の冒頭と最後の関所が最後のテストの行と並べて出す——最後の赤が修正の後に出た赤か、基の版からの赤かを人が見分ける手がかり。
    修正前の CI と最後のテスト（test_cmd の段なども走る）は同じ一式とは限らないので、どちらとも言い切らない"""
    named = "記録の名 process.baseline_checks"
    process = b.record.get("process") or {}
    if "baseline_checks" not in process:
        return f"修正前のテスト: 記録が無い（{named}）"
    base = process["baseline_checks"]
    if not isinstance(base, dict) or not isinstance(base.get("status"), str) or not base["status"]:
        return f"修正前のテスト: 記録が壊れている（{named} に文字列の status が無い: {json.dumps(base, ensure_ascii=False)[:80]}）"
    status = base["status"]
    word = gatemarks.MATERIAL_WORDS.get(status, "表に無い状態")
    told = f"{named} の status {status}" + (f"・走らせた物 {base['checked']}" if base.get("checked") else "")
    if status == "clean":
        return (f"修正前のテスト: {word}（{told}）——最後のテストの赤は修正の後に出た赤でありうる"
                "（同じ一式とは限らない。最後のテストの一式と照らして決める）")
    if status == "found":
        return (f"修正前のテスト: {word}（{told}）——最後のテストの赤は修正前から在りうる"
                "（同じ一式とは限らない。最後のテストの一式と照らして決める）")
    return f"修正前のテスト: {word}（{told}・{base.get('reason') or '理由なし'}）"


def suites_line(tests: dict | None, *, role_status: str | None = None) -> str:
    """最後のテスト（blk-tests の final の出口 {suites, by, test_cmd_same_as, test_cmd_how}）が走らせた一式・環境で起こせなかった段・
    走らせなかった物の 1 行。起こし方（段の how か、test_cmd の段なら test_cmd_how の direct・shell）が在れば添える。報告の冒頭と最後の関所が同じ物を出す（何を根拠にした緑かを人に見せる。無い物はログからは読めない）。
    role_status は role_ci_status の返り。走らせたと書くのは素材が clean・found の時だけ（not_run などは走らせなかった側に）"""
    tests = tests or {}
    by = tests.get("by")
    suites = tests.get("suites") or []
    same = tests.get("test_cmd_same_as")
    kinds = [_suite_kind(s) for s in suites]

    def how(s):
        got = s.get("how") or (tests.get("test_cmd_how") if s.get("name") == TEST_CMD_STEP else None)
        return f"・{got}" if got else ""

    ran = [f"{s.get('name')}（exit {s.get('exit')}{how(s)}）" for s, k in zip(suites, kinds) if k != "broken"]
    broken = [f"{s.get('name')}（起こせない{how(s)}）" for s, k in zip(suites, kinds) if k == "broken"]
    direct_broken = any(k == "broken" and s.get("how") == "direct" for s, k in zip(suites, kinds))
    if same:
        ran.append(f"{TEST_CMD_STEP}（宣言の段 {same} と同じコマンドなので 1 度だけ走らせた）")
    unrun = []
    if by == "engine" and not suites:
        unrun.append(f"宣言の段・{TEST_CMD_STEP}（宣言が読めないので engine が走らせなかった）")
    elif by == "engine" and not same and not any(s.get("name") == TEST_CMD_STEP for s in suites):
        unrun.append(f"{TEST_CMD_STEP}（渡されていない）")
    elif by == "role":
        ran = ran or [f"{TEST_CMD_STEP}（{tests['test_cmd_how']}）" if tests.get("test_cmd_how") else TEST_CMD_STEP]
        unrun.append("宣言の段（宣言が無いか、engine が任せ先に落ちた）")
    elif by == "role_needed" and role_status in ("clean", "found"):
        ran = [f"任せ先の CI の役 blk-ci が選んだ一式（素材の status {role_status}）"]
    elif by == "role_needed" and role_status is not None:
        unrun.append(f"宣言の段・{TEST_CMD_STEP}（任せ先の CI の役 blk-ci が走らせなかった: 素材の status {role_status or '無い'}）")
    elif by == "role_needed":
        unrun.append(f"宣言の段・{TEST_CMD_STEP}（任せ先の CI の役 blk-ci が走らせる）")
    env = f"／環境で起こせなかった（コードの赤ではない）: {'・'.join(broken)}" if broken else ""
    if direct_broken:
        env += f"（{tree_run.DIRECT_HINT}）"
    return f"走らせた: {'・'.join(ran) or '無い'}{env}／走らせなかった: {'・'.join(unrun) or '無い'}"


def run_ci(b, nid: str, *, test_cmd: str, runner=None) -> dict:
    """CI の節 nid（p0.local_checks・p4.ci）を b.run_engine で走らせ、返りを全部扱う（start と blk-tests の final が使う）。
    - relaunch（宣言が計画の後に変わった）は 1 度だけ呼び直す。2 度目も同じなら CiRefused（文に why）
    - test_cmd が在れば、宣言が在っても捨てない: engine が宣言の段を走らせた後に test_cmd の段（TEST_CMD_STEP）を足し
      （_with_test_cmd）、素材は runs の全部から組まれる——宣言の一式と test_cmd の両方が緑の時だけ clean（AND の合成）。
      test_cmd が宣言の段と同じコマンドなら 1 度だけ走らせ、返りの same_as にその段の名
    - ok: engine が受け付けまで済ませた → {by: "engine", log: 全部の段のログ, runs: 段ごとの {name, exit, how}, same_as?}。
      how は _with_test_cmd が起こす前に決めて走った行に写した値のまま
    - fallback（宣言が無い・engine の返答を受け付けが拒んだ）で任せ先に落ちた: test_cmd が在れば _ci_by_cmd（起こした印 →
      git の根で test_cmd → done。engine が既に test_cmd の段を走らせていればその結果を使い、2 度走らせない）→ {by: "role", log, how?}
    - fallback で test_cmd が空 → {by: "role_needed", log: "", why}。意味は「この節の素材はこの呼び出しで何も渡していない。
      呼び手が任せ先の役を回して渡す」だけ——**前の結果（記録に残る p0 の local_checks など）を使ってよい、ではない**。
      節は任せ先に落ちたまま待ち、印も置かない（裁定 R52。役のブロックは blk-ci。役が渡した後の続きは resume_after_ci——blk-ci の collect が呼ぶ）
    - ok: False で relaunch も fallback も無い（why だけ。対象の根が引けない）→ CiRefused"""
    note = {}
    runner = _with_test_cmd(runner, test_cmd, note)
    got = b.run_engine(nid, runner=runner)
    if got.get("relaunch"):
        got = b.run_engine(nid, runner=runner)
        if got.get("relaunch"):
            raise CiRefused(f"{nid}: 宣言が計画の後に 2 度変わった（呼び直しても同じ）: {got.get('why')}")
    if got.get("ok"):
        same = {"same_as": note["same_as"]} if note.get("same_as") else {}
        runs = got.get("runs") or []
        rows = [{k: r.get(k) for k in ("name", "exit", "how")} for r in runs]
        return {"by": "engine", "log": str(_engine_log(b, nid, runs)), "runs": rows, **same}
    if "fallback" not in got:
        raise CiRefused(f"{nid} を engine で走らせられない: {got.get('why')}")
    if not _fell_back(b, nid):
        raise BoardGap(f"{nid} は任せ先に落ちたが待っていない（表の fallback が absent）——CI の節は任せ先を持つ表で回す")
    if not (test_cmd or "").strip():
        return {"by": "role_needed", "log": "", "why": got["fallback"]}
    ran = next((r for r in got.get("runs") or [] if r.get("name") in (TEST_CMD_STEP, note.get("same_as"))
                and r.get("exit") is not None), None)
    return _ci_by_cmd(b, nid, test_cmd, ran=ran)


def _ci_by_cmd(b, nid: str, test_cmd: str, *, ran: dict | None = None) -> dict:
    """任せ先に落ちて待っている CI の節に、test_cmd を走らせた素材を渡す。印（mark_launched）を先に置く（board.py の頭のラインの
    約束 2。同じ試行の 2 度目は前の印を返すので、止められた後の呼び直しでもそのまま走らせ直せる）。走らせる所は engine と同じ
    git の根（--show-toplevel。引けなければ入力の cwd）。ran（engine が同じ呼び出しで走らせた test_cmd の段）が在れば走らせ直さず、
    その終了コードと標準出力・標準エラーと、走った行の argv・how から素材を組む。返りの how は走った時の起こし方"""
    inst = b.rd["instances"][nid]
    b.mark_launched(nid, inst.get("attempts", 1))
    log = b.work(safe_name(nid) + ".log")
    if ran:
        log.write_bytes(b"".join(pathlib.Path(ran[k]).read_bytes() for k in ("out", "err")
                                 if ran.get(k) and pathlib.Path(ran[k]).is_file()))
        launched = {"how": ran.get("how")}
        b.done(nid, _cmd_material(ran["exit"], log, ran["argv"], launched["how"]))
    else:
        root = pathlib.Path(_util.repo_root() or b.state["inputs"]["cwd"])
        launched = {}
        b.done(nid, local_checks_material(root, test_cmd, log, launched=launched))
    return {"by": "role", "log": str(log), **({"how": launched["how"]} if launched.get("how") else {})}


def _is_ci(b, nid: str) -> bool:
    return ((b.nodes.get(nid) or {}).get("engine_run") or {}).get("builtin") == CI_BUILTIN


def _fell_back(b, nid: str) -> bool:
    inst = b.rd["instances"].get(nid)
    return bool(inst and inst.get("status") == "pending" and inst.get("engine_fallback"))


def _pr_go(b, got: dict):
    """pr_go の 3 値: True（任せ先に落ちた。blk-pr を回す）・False（engine で済んだ・このラインに無い）・"pending"（p0.parallel_pr は
    まだ出ていない——依存の p0.local_checks が任せ先の CI の役を待っている。測っていないので偽と言わない）"""
    if got["role_needed"]:
        return True
    if not got["by"] and b.node_state(prcheck.NODE) == "pending":
        return "pending"
    return False


def _drain(b, p, *, test_cmd: str, runner=None) -> dict:
    """盤面の約束 1 の輪: Progress.run_engine の節を全部走らせて settle する、を空になるまで。CI の節は run_ci、p0.parallel_pr は
    prcheck.run_helper（印は置かない。blk-pr の pr-snap が置く）。任せ先に落ちて待っている CI の節は、test_cmd が在れば
    走らせて渡す（止められた run の呼び直しで、test_cmd の道を任せ先の役に黙って替えない）。
    返り {ci_role_go, pr_go}。CiRefused・prcheck.Refused（InputRefused にする）は AI の前で止める"""
    ran = set()
    pr = None
    try:
        while True:
            left = [n for n in p["ready"] if _is_ci(b, n) and _fell_back(b, n) and n not in ran] if test_cmd.strip() else []
            if not p["run_engine"] and not left:
                break
            if left:
                for nid in left:
                    ran.add(nid)
                    _ci_by_cmd(b, nid, test_cmd)
                p = b.settle()
                continue
            for nid in p["run_engine"]:
                if nid in ran:
                    raise BoardGap(f"{nid} を走らせた後も run_engine に残る（盤面の欠陥）")
                ran.add(nid)
                if nid == prcheck.NODE:
                    pr = prcheck.run_helper(b, runner=runner)
                elif _is_ci(b, nid):
                    run_ci(b, nid, test_cmd=test_cmd, runner=runner)
                else:
                    raise BoardGap(f"start は engine_run の節 {nid} の回し方を知らない（CI の節と {prcheck.NODE} だけ）")
            p = b.settle()
        if pr is None:   # 前に落ちていた・まだ出ていない: 走らせずに盤面から読む
            pr = prcheck.run_helper(b, runner=runner)
    except prcheck.Refused as e:
        raise InputRefused(str(e)) from None
    add_pending_request(b)
    return {"ci_role_go": any(_is_ci(b, n) and _fell_back(b, n) for n in p["ready"]), "pr_go": _pr_go(b, pr)}


PENDING_WAIT_NODE = "p1.worktree_before"   # これが済む前の add は入口の印を立てる（写しの RL の entry_opens）


def add_pending_request(b) -> str:
    """依頼と変更の両方で始めた run の依頼を、1 周目の版が固まった後（入口の印を立てない所）に RL の add で積む。
    本線で通常の run の途中に add するのと同じで、P1 の目は外れず、依頼は origin 付きのバッチで判定に届く。
    返り: "none"（積む依頼が無い・もう積んだ）・"added"（今積んだ）・"waiting"（版がまだ固まっていない）。
    積んだかは記録の request_findings（origin のバッチ）だけで見る（呼び直しても 2 度積まない）"""
    try:
        doc = json.loads(b.work(START_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "none"
    if doc.get("entry") != "both":
        return "none"
    batches = (b.record.get("process") or {}).get("request_findings") or []
    if any(x.get("origin") == ORIGIN for x in batches):
        return "none"
    if b.node_state(PENDING_WAIT_NODE) == "pending":
        return "waiting"
    b.add_request(request_parts(json.loads(pathlib.Path(doc["request_file"]).read_text(encoding="utf-8")))["findings"], ORIGIN)
    return "added"


def resume_after_ci(b, *, test_cmd: str = "", runner=None) -> dict:
    """ラインの約束（裁定 R52 の続き）: start が ci_role_go 真で返した run では、任せ先の CI の役のブロックが p0.local_checks を
    mark_launched → done で渡した後、ラインはこれで start の輪に戻る（settle → run_engine の節を走らせて settle を空になるまで。
    p0.parallel_pr は prcheck.run_helper）。返り {ci_role_go, pr_go}（start の返りの同じ欄と同じ意味。pr_go は True・False・
    "pending"）。役がまだ渡していなければ何も走らせずに同じ値を返す。呼び直しても走らせ直さない"""
    return _drain(b, b.settle(), test_cmd=test_cmd, runner=runner)


# ---------------------------------------------------------------- start（線 A の仕様 4 節）
START_FILE = "start.json"


def declared_adapter(b) -> str:
    """run が宣言した包みの形: start が今の周の START_FILE に控えた入力 adapter（ADAPTER_MODES の値。"" は包みを通す run、
    "optional" は包み無しで回す run）。控えが無い・読めない・鍵が無い・語の外は ValueError（読む側が fail closed で止める）"""
    path = b.work(START_FILE)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"start の控え {path} から adapter を読めない（{type(e).__name__}: {e}）") from None
    mode = doc.get("adapter") if isinstance(doc, dict) else None
    if not isinstance(mode, str) or mode not in ADAPTER_MODES:
        raise ValueError(f"start の控え {path} の adapter={mode!r} は宣言の語（空か optional）でない")
    return mode


def _write_json(path: pathlib.Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


ENTRIES = ("request", "change", "both")


def _entry_words(kind: str, inp: dict) -> str:
    """頭の行の入口の文"""
    if kind == "request":
        return f"判定から（依頼 {len(inp['items'])} 件）"
    ch = inp["change"]
    what = f"変更から（{inp['base_rev'][:12]}..HEAD・{'PR #' if ch['from'] == 'pr' else 'base '}{ch['name']}）"
    return what if kind == "change" else f"{what}と依頼 {len(inp['items'])} 件（版が固まった後に積む）"


def start(board_dir: pathlib.Path, repo: pathlib.Path, raw: dict, *, run_id: str, runner=None) -> dict:
    """ラインの入口。順:
    1. ghreads.load（殻が隔離の前に読んだ github_reads。再開では盤面の根の github.json を先に）→ check_inputs（拒めば盤面を
       作らずに InputRefused）。盤面を作った後に ghreads.adopt が github_reads を盤面の根の github.json へ写して元を消す
    2. DiskBoard.begin（1 周の run。origin works/darkfactory・stop_after_round=1・board_hook.py の overrides・validator_runner）。
       入口は本線の engine の分かれ方に揃える: 依頼だけ → 依頼を積んで判定から入る run（base_rev は空＝HEAD）。変更（base・pr）
       が在る → base_rev＝解いた merge-base で依頼を積まずに始める通常の run（入口の印が立たず、P1 の目が差分に回る）。依頼も
       在れば、1 周目の版が固まった後に add_pending_request が積む（途中の add は P1 を外さない）。
       lang が空でなければ inputs.lang に渡す（本線 loop.py の --lang。空は盤面の
       既定 LANG_DEFAULT＝依頼文の言語）。入口の Reject は InputRefused
    3. テストを走らせる前に r1/start.json に入力の控えと、宣言が無い時の道 ci_fallback（test_cmd か role）を置く。呼び直し
       （Archon の再開）で前の控えの test_cmd と違えば InputRefused（止められた run を別の道で黙って続けない）
    4. _drain（盤面の約束 1 の輪。CI の節は run_ci、p0.parallel_pr は prcheck.run_helper。止められた test_cmd は走らせ直す）
    5. 切符（ticket.write）を書き、r1/start.json を結果つきで書き直す
    返り {ok, entry, base_rev, test_cmd, policy_paste, policy_path, final_gate, adapter, thickness, gates, ci_role_go, pr_go,
    head_line}。entry は ENTRIES の語（依頼だけ・変更だけ・両方）。base_rev は修正の起点（修正前の HEAD）で、下流の差分・
    受け付けが「修正が触った物」を切る版。変更から入る run の P1 の差分の根（merge-base）は盤面の record.base にだけ置き、
    ここには出さない（PR にもとからある変更を修正の変更と取り違えない）。
    ci_role_go は CI の節（p0.local_checks）が任せ先に落ちたまま待っている（test_cmd も宣言も無い。裁定 R52）。pr_go は _pr_go の
    3 値——"pending" の run は、CI の役の後に resume_after_ci が測る"""
    repo = pathlib.Path(repo).resolve()
    board_dir = pathlib.Path(board_dir)
    reads_src = _word(raw, "github_reads")
    try:
        reads = ghreads.load(board_dir, reads_src)
    except (OSError, ValueError) as e:
        raise InputRefused(f"隔離の前の読み出し（github_reads）を読めない（{type(e).__name__}: {e}）") from None
    inp = check_inputs(raw, repo, reads=reads)
    change = inp.get("change")
    kind = "both" if change and inp["items"] else "change" if change else "request"
    table = load_table(LINE)
    head_rev = _git(repo, "rev-parse", "HEAD") if change else ""
    try:
        b, p = DiskBoard.begin(board_dir, repo=repo, table=table, items=None if change else inp["items"], origin=ORIGIN,
                               base_rev=inp.get("base_rev", ""),
                               request_text=inp["request_text"] or change["text"]
                               or f"変更（{change['from']} {change['name']}）の審査",
                               inputs={"gates": inp["gates"] or None, "policy_md": inp["policy_md"] or None,
                                       **({"lang": inp["lang"]} if inp["lang"] else {})},
                               stop_after_round=1, **open_kwargs(LINE, table))
    except Reject as e:
        raise InputRefused(f"盤面が入力を受けない: {e}") from None
    try:
        ghreads.adopt(board_dir, reads_src)
    except OSError as e:
        raise InputRefused(f"隔離の前の読み出し（github_reads）を盤面へ写せない（{type(e).__name__}: {e}）") from None
    keep = {k: v for k, v in inp.items() if k not in ("items", "request_text")}
    work = b.work(START_FILE)
    prev = {}
    if work.is_file():
        prev = json.loads(work.read_text(encoding="utf-8"))
        if prev.get("test_cmd") != inp["test_cmd"]:
            raise InputRefused(f"この盤面は test_cmd={prev.get('test_cmd')!r}（宣言が無い時の道: {prev.get('ci_fallback')}）で"
                               f"始めた——呼び直しの test_cmd={inp['test_cmd']!r} で道を替えない（同じ入力で呼び直す）")
    # 呼び直し（Archon の再開）では、修正が HEAD を進めていても最初の控えの起点を使う
    base_rev = prev.get("base_rev") or head_rev or (b.record.get("base") or "")
    doc = {**keep, "run_id": run_id, "requests": len(inp["items"]), "base_rev": base_rev, "entry": kind,
           "entry_words": _entry_words(kind, inp), "change": change,
           "ci_fallback": "test_cmd" if inp["test_cmd"] else "role"}
    _write_json(work, doc)
    go = _drain(b, p, test_cmd=inp["test_cmd"], runner=runner)
    try:
        ticket.write(board_dir, repo, run_id)
    except ticket.TicketError as e:
        raise InputRefused(f"包みの切符を書けない: {e}") from None
    pol = policy.brief(b)
    absent = len(b.state["works"].get("not_in_line") or [])
    thick = inp["thickness"] + ("（既定）" if not _word(raw, "thickness") else "")
    head = (f"入口: {doc['entry_words']}・段: {thick}・gates: {inp['gates'] or '空'}・"
            f"このラインに無い節: {absent} 個・{prcheck.head_downgrades(LINE)}")
    if go["ci_role_go"]:
        head += "・修正前のテスト: 宣言も test_cmd も無い——任せ先の役がリポジトリから走らせ方を探す"
    out = {"ok": True, "entry": kind, "base_rev": base_rev, "test_cmd": inp["test_cmd"], "policy_paste": pol["paste"],
           "policy_path": pol["path"], "final_gate": inp["final_gate"], "adapter": inp["adapter"], "thickness": inp["thickness"],
           "gates": inp["gates"], **go, "head_line": head}
    _write_json(work, {**doc, **go, "head_line": head})
    return out



# ---------------------------------------------------------------- 盤面に受ける共通の口（計画 Task 9。裁定 TA6・TA11・TA19）
READONLY_MOVED = "読むだけの役が作業ツリーを変えた: "   # take の作業ツリーの拒否の文の頭（1 本目の読むだけの役の拒否の文を後ろに続ける）


def snapshot(board_dir: pathlib.Path, name: str, repo: pathlib.Path) -> pathlib.Path:
    """読むだけの役を起こす前に、作業ツリーの姿（accept.tree_state。blk-pr・blk-ci と同じ共通の姿。R47）を今の周の作業ファイル
    b.work(name) に書き、そのパスを返す。take(…, snapshot_name=name) がこれと今の作業ツリーを比べる。git が効かなければ Reject"""
    b = open_board(board_dir)
    p = b.work(name)
    _write_json(p, accept.tree_state(pathlib.Path(repo)))
    return p


def _tree_moved(b, name: str, repo: pathlib.Path) -> str:
    """b.work(name) の写しと今の作業ツリーの違いを述べる文（同じなら空）。比べと違いの文は共通の accept.tree_moved（R47。
    porcelain・差分・git が無視するパスの増減・HEAD・枝のどれが変わったかを言う）。写しが無い・形が違うのは
    snapshot が走っていない回す側の誤りで BoardGap"""
    p = b.work(name)
    try:
        snap = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BoardGap(f"作業ツリーの写し {p} が読めない（読むだけの役を起こす前に snapshot が走っていない）: {e}") from None
    errs = validate_schema(snap, accept.TREE_SCHEMA)
    if errs:
        raise BoardGap(f"作業ツリーの写し {p} の形が違う: " + "; ".join(errs))
    moved = accept.tree_moved({k: snap[k] for k in accept.TREE_KEYS}, pathlib.Path(repo))
    if not moved:
        return ""
    return "この役は読むだけの役で、作業ツリー・HEAD・枝・git が無視するファイルを変えてはいけない（" + "・".join(moved) + "）"


tree_moved_since = _tree_moved   # 盤面の節へ渡さない受け付け（先に起こす役）が同じ比べを使う公開の名（層の決まり private）


def take(board_dir: pathlib.Path, nid: str, reply: dict, repo: pathlib.Path, *, snapshot_name: str | None = None) -> dict:
    """役の返答を盤面に渡す（各ブロックの受け付けが使う 1 つの口）。順:
    1. 盤面を開く（open_board）。止めた run はここで Reject（役に返さない。作業ツリーの比べより先）
    2. snapshot_name が在れば、役を起こす前の写し（snapshot）と今の作業ツリーを比べ、違えば
       {"ok": False, "reason": "読むだけの役が作業ツリーを変えた: …"}（盤面は書かない。TA11）
    3. b.done(nid, reply)（写しの schema → 番号の読み替え → post_check → writes → check_record → 保存 → settle）
    通れば {"ok": True, "reason": "", "ready", "asking", "halted", "out_file"}（out_file は state.outputs[nid]["file"]。
    盤面の置き場からの相対。周を仮定しない）。写しの AnswerReject（返答の中身の誤り）だけを {"ok": False, "reason": 文} に
    する（盤面は書かれない。入れ物は捨てる——盤仕様 4.1）。ほかの Reject（止めた run への書き込みなど）と BoardGap（表で
    受けない節・印の無い試行・写しの欠け）は投げ直す（回す側の誤りで、役に返しても直らない。TA19）。
    DiskBoard.edit は使わない（done の中で保存される）。起こした印（mark_launched）は役を起こす前にブロックの snap の節が置く"""
    b = open_board(board_dir)
    _refuse_halted(b)
    if snapshot_name is not None:
        moved = _tree_moved(b, snapshot_name, repo)
        if moved:
            return {"ok": False, "reason": READONLY_MOVED + moved}
    try:
        p = b.done(nid, reply)
    except AnswerReject as e:
        return {"ok": False, "reason": str(e)}
    return {"ok": True, "reason": "", "ready": p["ready"], "asking": bool(p["asking"]), "halted": bool(p["halted"]),
            "out_file": b.state["outputs"][nid]["file"]}


def hand(b, board_dir: pathlib.Path, nid: str, reply: dict, repo: pathlib.Path) -> dict:
    """機械が役の返答を盤面へ渡す 1 つの口（判定のブロックが受けた判定・直す物が無い周の空の修正・先に作った独立設計）。待っている
    試行に起こした印を置いてから take（盤面の決まり 2）。待っている試行が無ければ BoardGap（呼ぶ側の順の誤り）"""
    inst = board.pending_instance(b, nid)
    if inst is None:
        raise BoardGap(f"{nid} が盤面で待っていない（線の順の誤り。state: {b.node_state(nid)}）")
    b.mark_launched(nid, inst.get("attempts", 1))
    return take(board_dir, nid, reply, repo)


EMPTY_FIX_REASON = "直す義務 0 件の周（p2.fix_plan が条件で na）——修正の役を起こさず、機械が空の返答を渡した"


def empty_fix_reply() -> dict:
    """直す義務 0 件の周に機械が渡す p3.fix の返答（TA6）。changes は空、fix_closure は not_applicable（写しの graph の
    p3.fix は na_self_ok を宣言し、fix_covers_open_units は changes が空なら義務 0 件の周を通す）、他の必須の欄は空の値。
    呼ぶたびに新しい dict"""
    return {"changes": [], "fix_closure": {"status": "not_applicable", "reason": EMPTY_FIX_REASON},
            "gates_changed": False, "interactions": [], "mechanism_changed": False, "not_done": [], "path_changed": False,
            "plan_faces": [], "premise_drift": False, "seams_changed": False, "security_surface_changed": False,
            "wrote_refs": []}
