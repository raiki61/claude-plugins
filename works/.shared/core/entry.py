"""線の入口の口（線 A の仕様 4 節。盤面の層の仕様 4.2・4.4）: ラインの節の表を読み、盤面をラインの名前を知らずに開く。

- load_table(line):   PACK/<line>/nodes.json を読み、盤面の層の縛り 1〜5（NodeTable.check）を当てる。破れは全部を 1 つの BoardGap に
- open_board(dir):    盤面の state.works.line から表を引き、表の sha が state.works.table_sha と合わなければ BoardMismatch。
                      open_kwargs(line, table)（board_hook.py の返りと核の差し替え）を DiskBoard.open に渡す。include の中の
                      script なら scope（flow_adapter.current_scope）を登録して渡し、部品の私物を盤面の <scope>/ の下に分ける
- hook_kwargs(line):  board_hook.py の読み込みだけ（無ければ {}）
- peek_here() / peek_as(here): 節の script が今の置き場の印を控えに写し、役の sandbox の中の読むだけの開きがそれで盤面を開く
                      （部品のコードが scope を知らずに運ぶ口）
- open_kwargs(line):  hook_kwargs に線 A の核の差し替え CORE_OVERRIDES（読んだ記録の置き場・直す義務・関所の項目の決め手・R3・R4 の起動条件）を重ねた物。open_board と start が
                      同じ物を DiskBoard.open・begin に渡す（開くたびに同じ overrides。BL-R3）
- check_inputs(raw, repo, *, reads): ラインの入力を確かめる（線 A の仕様 4 節）。拒めば InputRefused（人に向けた 1 行）
- local_checks_material(repo, test_cmd, log_path): 任せ先に落ちた CI の節（p0.local_checks・p4.ci）に渡す素材を組む公開の口
  （盤面なしで呼べる。線 B の申し送り 2）
- run_ci(b, nid, *, test_cmd): CI の節を run_engine で走らせ、返りを全部扱う（start と blk-tests の final が使う）
- suites_line(tests, *, role_status): 最後のテストが走らせた一式と走らせなかった物の 1 行（報告の冒頭と最後の関所が使う）
- start(board_dir, repo, raw, *, run_id): 入力の確かめ → 盤面を開く → 修正前のテストの記録 → 方針の文 → 切符
  （入力 fix_fixture が在れば、core の fixture.adopt で修正を待つ盤面の写しを取り込み、判定・修正案を作り直さずに修正の前から）
- resume_after_ci(b): 任せ先の CI の役が p0.local_checks を渡した後、ラインが start の輪（run_engine → settle）に戻る口
- snapshot(board_dir, name, repo): 読むだけの役を起こす前に、作業ツリーの姿（accept.tree_state）を今の周の b.work(name) に
- take(board_dir, nid, reply, repo, *, snapshot_name, commit): 各ブロックの受け付けが使う 1 つの口。役の返答を盤面の done に渡す
  （写しの AnswerReject だけを {ok: False} で役に返す。裁定 TA19）
- hand(b, board_dir, nid, reply, repo): 機械が返答を渡す 1 つの口（待っている試行 board.pending_instance に起こした印を置いてから take）
- empty_fix_reply(b, why): 直す義務 0 件の周（と、修正の輪の最後の回に義務の全部を止めた周）に機械が渡す p3.fix の空の返答
  （裁定 TA6）。trace_empty_fix(b) がその印を trace に 1 行（EMPTY_FIX_OP・EMPTY_FIX_BY）

ブロックのスクリプトは open_board で盤面を開く。線 B のライン（darkfactory-rounds）でも同じブロックが同じ口で動く。
"""
import importlib.util
import json
import os
import pathlib
import re
import shlex
import shutil
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
from engine.role_run import _tail  # noqa: E402  （素材の detail に写すログの末尾。board.py と同じ写しの engine の関数）
from engine.rules import cond_reads  # noqa: E402
from engine.util import AnswerReject, Reject, safe_name  # noqa: E402
import accept  # noqa: E402
import carry  # noqa: E402  （L1。次の run への持ち越しの形の住処）
import conflict  # noqa: E402
import fixture  # noqa: E402
import flow_adapter  # noqa: E402
import forge  # noqa: E402
import gatemarks  # noqa: E402
import ghreads  # noqa: E402
import policy  # noqa: E402
import prcheck  # noqa: E402
import scopes  # noqa: E402
import script_io  # noqa: E402  （L1。機能の切り替えの語 SWITCH_ON・SWITCH_OFF）
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


# forge（PR を持つホスト）の無い remote の決め（持ち主 2026-10-07: core は git だけ、gh・GitHub は外側の forge の層）。
# 決めは run の初めに 1 度だけ機械がして盤面の loop に置き（on_init）、並行 PR の節の条件がそれを読んで条件外にし（役を起こさない）、
# 素材は機械が not_applicable で埋める（fill_materials）。写しの graph は p0.parallel_pr に na_self_ok を持たない（走った役が
# not_applicable を名乗れば拒む）ので、走らない節の素材を埋める側で書く。決めの無い盤面（前の版）と GitHub の remote は今どおり
@board.rl_builder
def on_init_forge(rl):
    """写しの RL の on_init の組み手: 写しの on_init の後に、対象（inputs.cwd）の forge の決め forge.detect を loop に置く"""
    base = rl.on_init

    def on_init(b, args):
        base(b, args)
        b.loop_state[forge.LOOP_KEY] = forge.detect(b.state["inputs"]["cwd"])
    return on_init


def parallel_pr_due_forge(rl):
    """写しの RL の parallel_pr_due の組み手（CONDS の差し替え）: loop の forge の決めが forge の無い種類なら偽（理由は
    no_forge: <種類>）。それ以外は写しの条件のまま"""
    base = rl.parallel_pr_due

    @cond_reads(*dict.fromkeys(base.reads + (f"loop.{forge.LOOP_KEY}",)))
    def parallel_pr_due(v):
        why = forge.reason(v(f"loop.{forge.LOOP_KEY}", None))
        return (False, why) if why else base(v)
    return parallel_pr_due


@board.rl_builder
def fill_materials_forge(rl):
    """写しの RL の fill_materials の組み手: forge の無い run で並行 PR の節が条件外（na）の周は、その素材を not_applicable
    （reason は no_forge: <種類>）で先に埋めてから写しを呼ぶ（写しは埋まった素材を飛ばす。走らせなかった節を not_run と書かない）"""
    base = rl.fill_materials

    def fill_materials(b):
        why = forge.reason(b.loop_state.get(forge.LOOP_KEY))
        if why and b.node_state(prcheck.NODE) == "na":
            mats = b.record["materials"]
            for mat in b.nodes[prcheck.NODE].get("materials", []):
                mats.setdefault(mat, {"status": "not_applicable", "reason": why})
        base(b)
    return fill_materials


@board.rl_builder
def github_repo_redacted(rl):
    """写しの RL の _github_repo の組み手: 引けない理由の文から URL の userinfo（トークン）を落とす（写しは形の合わない remote の
    URL を理由に書き、それが盤面の engine_fallback と任せ先の役への渡し物に載る）"""
    base = rl._github_repo

    def _github_repo():
        repo, why = base()
        return repo, forge.redact(why)
    return _github_repo


# ゲートの検算の役（p1.gate_efficacy）の『条件に当たらない』（canary の run e91112dd）。線 A の p0.base は機械が組み
# （board.base_output）、touches_gates を判定せずに真へ倒す——機械には差分の柵（分岐）がゲートかを決められないので、役を起こす
# 側に倒す。写しの check_record はその値を機械の事実として読み、ゲートに触れない差分でも役の not_applicable を拒むので、
# 0 腕の役は not_run（検証器の阻害）しか名乗れず、結末が round_limit になった。本線では p0.base の役が差分を読んで決める判定を、
# 線 A では差分を読むゲートの検算の役がする。役の判定を受けるのは、機械が持つ事実がどれも『ゲートに触れる』と言わない時だけ:
# 前の周の修正がゲートを変えたと申告していない（写しの条件を、倒した p0.base の値を外して評価する）、差分に機械が見るゲートの印
# （GATE_FILE_PATTERNS のファイル・assert を足す・消す行）が無い。印が 1 つでも在れば写しのまま拒む（測らせる）
GATE_NODE = "p1.gate_efficacy"
GATES_COND = "gates_touched"
# 検証ゲートの定義のファイル（テスト・CI・pre-commit・フック・lint・試験の設定・変異の腕の一覧）。広めに当てる——当たり過ぎは
# 役に測らせる（今まで通り）だけで、当たり漏れが役の『条件外』を通す
GATE_FILE_PATTERNS = (
    r"(^|/)tests?/", r"(^|/)__tests__/", r"(^|/)spec/", r"(^|/)test_[^/]*$", r"_test\.[^/]+$", r"\.(test|spec)\.[^/]+$",
    r"(^|/)conftest\.py$", r"^\.github/", r"(^|/)\.gitlab-ci\.ya?ml$", r"^\.circleci/", r"(^|/)Jenkinsfile$",
    r"(^|/)\.travis\.ya?ml$", r"(^|/)azure-pipelines\.ya?ml$", r"^\.buildkite/", r"(^|/)\.pre-commit-config\.ya?ml$",
    r"^\.husky/", r"(^|/)lefthook\.ya?ml$", r"(^|/)\.?githooks/", r"(^|/)hooks/", r"(^|/)\.review-checks\.json$",
    r"(^|/)(tox\.ini|noxfile\.py|pytest\.ini|setup\.cfg|pyproject\.toml|Makefile|justfile|package\.json)$",
    r"(^|/)(\.flake8|mypy\.ini|\.?ruff\.toml|\.pylintrc|\.eslintrc[^/]*|eslint\.config\.[^/]+|\.shellcheckrc|\.golangci\.ya?ml)$",
)
_GATE_FILES = tuple(re.compile(p) for p in GATE_FILE_PATTERNS)
_ASSERT_LINE = re.compile(r"^[+-](?![+-]{2} ).*\bassert", re.M)   # 足す・消す行（ファイルの頭の +++ / --- を除く）


def gate_signals(changed_files, diff_text: str) -> list:
    """差分に機械が見るゲートの印の一覧（空なら印が無い）: ゲートの定義のファイルと、assert を足す・消す行"""
    hits = [f"ゲートの定義のファイル {f}" for f in changed_files if any(p.search(f) for p in _GATE_FILES)]
    hits += [f"assert の行 {m.group(0)[:80]!r}" for m in _ASSERT_LINE.finditer(diff_text or "")]
    return hits


def role_judged_na_works(b, nid) -> bool:
    """写しの RL の role_judged_na の差し替え: 走ったゲートの検算の役の『条件外』を、機械が持つ事実がどれも『ゲートに触れる』と
    言わない時だけ受ける（頭の注記）。p0.base を機械の節にしない表（本線の形）・ほかの節・変更ファイルの一覧の無い盤面は写しのまま"""
    if (b.nodes.get(nid) or {}).get("applies_cond") != GATES_COND:
        return False
    base = b.table.nodes.get("p0.base") if b.table is not None else None
    if base is None or base.by != "machine":
        return False
    if b.cond(GATES_COND, overlay={"out.p0.base.touches_gates": False})[0]:
        return False
    files = b.loop_state.get("changed_files")
    if not isinstance(files, list):
        return False
    try:
        diff = pathlib.Path(b.loop_state["diff_file"]).read_text(encoding="utf-8", errors="replace")
    except (KeyError, TypeError, OSError):
        return False
    return not gate_signals(files, diff)


@board.rl_builder
def entry_opens_by_diff(rl):
    """写しの RL の entry_opens（いま add すれば入口の印が立つか）を包む組み手: 写しの条件（1 周目の P1 より前で印がまだ無い）が
    真で、かつ start が測った入口の差分が空（state.works.begin.diff_empty が真）の時だけ真。diff_empty が None（測りを渡さない
    begin。本流の振る舞い）なら写しのまま。印は「入力の差分が空」の意味になり、写しの核の印を読む所は全部が入力の中身で決まる"""
    orig = rl.entry_opens

    def entry_opens(b):
        if not orig(b):
            return False
        flag = ((b.state.get("works") or {}).get("begin") or {}).get("diff_empty")
        return flag is None or flag is True
    return entry_opens


# 線 A の核が写しの RL に当てる差し替え（名前 → (関数, 理由)）。ラインの board_hook.py の overrides が同じ名前を持てば、そちらが勝つ
CORE_OVERRIDES = {
    "hook_evidence": (_hook_evidence_at_adapter,
                      "読んだ記録は盤面の隣でなく包みの置き場 adapter.reads_dir(run の worktree)/reads.jsonl に在る（Task 6 の直し 1）"),
    "_owed_units": (conflict.owed_units_but_asked,
                    "食い違いの申し出に直す裁定でない裁定（ask_human・fix_plan_item）を受けた単位は、直す義務から外す（ask_human は"
                    "最後の人の関所で人が決め、fix_plan_item は同じ run の中で案の項目を直すまで外す。conflict.held_by_rulings）。関所に載せる問い（fork・escalate）の出どころ・depends は、答えるまで外し"
                    "（gatemarks.withheld）、修正前の関所で答えたら直す義務に戻す（gatemarks.returned）"),
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
    "on_init": (on_init_forge,
                "対象の remote が forge（PR を持つホスト。GitHub）かを run の初めに機械が決めて盤面の loop.forge に置く"
                "（forge.detect。core は git だけ、gh・GitHub は外側の forge の層。持ち主 2026-10-07）"),
    "parallel_pr_due": (parallel_pr_due_forge,
                        "forge の無い remote（origin が無い・ローカルのパス・GitHub でないホスト）では並行 PR の節を条件外にし、"
                        "任せ先の役に確かめるかを決めさせない（canary の run 5318f732 で役が awaiting_human と書き round_limit になった）"),
    "_github_repo": (github_repo_redacted,
                     "写しは GitHub の形に合わない remote の URL を任せ先に落ちた理由に書き、userinfo のトークンが盤面と役への渡し物に"
                     "載る。理由の文から userinfo を落とす（forge.redact）"),
    "fill_materials": (fill_materials_forge,
                       "forge の無い run で条件外にした並行 PR の節の素材を not_applicable（reason は no_forge: <種類>）で埋める"
                       "（写しは走らなかった節を not_run と書き、検証器の阻害になる）"),
    "entry_opens": (entry_opens_by_diff,
                    "入口の印（判定から入る run。P1 の役を起こさない）を、依頼を P1 の前に積んだかでなく、start が測った入力の差分が"
                    "空かで立てる（持ち主 2026-10-09「入口は 1 つの入力の形にそろえる」。差分の在る run に依頼を足しても P1 は"
                    "差分を見る。依頼はいつも盤面を作る時に積む。計画 docs/plans/2026-10-09-one-entry-shape.md の 2.3）"),
    "role_judged_na": (role_judged_na_works,
                       "線 A の p0.base は機械が touches_gates を判定せずに真へ倒すので、ゲートの検算の役の『条件外』は、前の周の修正が"
                       "ゲートを変えたと申告しておらず、差分に機械が見るゲートの印（定義のファイル・assert の行）が無い時だけ受ける"
                       "（写しは拒み、0 腕の役は阻害の not_run しか名乗れなかった。canary の run e91112dd）"),
}


def open_kwargs(line: str, table: NodeTable | None = None) -> dict:
    """DiskBoard.open・begin に渡す引数: hook_kwargs(line, table) の返りに、overrides として CORE_OVERRIDES を重ねた物
    （board_hook.py の overrides が同じ名前なら board_hook の方）。open_board と start がこれを使う（開くたびに同じ。BL-R3）"""
    kw = hook_kwargs(line, table)
    return {**kw, "overrides": {**CORE_OVERRIDES, **(kw.get("overrides") or {})}}


PEEK_ENV = "WORKS_BOARD_PEEK"   # 1 なら open_board は盤面を書かない（scope の登録・窓の照らしを飛ばす）


def peek_here() -> str:
    """読むだけの開き（peek_as）へ運ぶ今の置き場の印（今の script が居る include の名。線の最上段は空）。部品は中身を
    知らずに運ぶだけ（役の Bash には節の env が無いので、節の script が控えに写して役の側の peek_as に渡す）"""
    return flow_adapter.current_scope()


def peek_as(here: str) -> None:
    """これから開く盤面を読むだけの開き（PEEK_ENV）にし、今の置き場を peek_here の返り here にする（空なら線の最上段）。
    役の sandbox の中で受け付けの確かめを回す時の口（scope の登録も窓の照らしもしない）"""
    os.environ[PEEK_ENV] = "1"
    if here:
        os.environ[flow_adapter.NODE_EXECUTION_ENV] = json.dumps({"path": f"{here}{flow_adapter.INCLUDE_SEP}precheck"})
    else:
        os.environ.pop(flow_adapter.NODE_EXECUTION_ENV, None)


def open_board(board_dir: pathlib.Path, *, allow_halted: bool = False) -> DiskBoard:
    """盤面を開く。表は state.works.line のラインの nodes.json。表の sha が盤面を作った時の state.works.table_sha と違えば
    BoardMismatch（run の途中で表が替わった盤面を、替わった表で回さない）。open_kwargs の返りを DiskBoard.open に渡す。
    scope は今の script が居る include の名（flow_adapter.current_scope。線の最上段は空）。空でなければ、部品の私物を scope の根に
    分ける置き場の版（state.works.layout が board.LAYOUT）でない盤面は BoardMismatch（この版より前に始めた盤面。移し替えない）、
    そうなら今の周の scopes.json に scope と起こされたブロックを登録し（scopes.claim）、周の置き場に置く名（scopes.round_names）
    と一緒に盤面に渡す（盤面の work が私物を <scope>/r<N>/ に置く）。部品のコードは scope を知らない。
    流れの道具の節（flow_adapter.in_flow_node）が置き場の版の盤面を開く時だけ、scope が空でも scopes.enter を呼ぶ: 前の scope の
    窓（盤面を開いてから次の scope が開くまで）の盤面の変化を前の部品の宣言に照らし、今の scope の窓を開く。宣言の外の書き込み・
    公開の名の持ち主の重なり・Schema の外れが在れば盤面を止め（_halt_scope_check。by SCOPE_CHECK_BY）、allow_halted で開いて
    いなければ BoardGap（開いた節が落ちる。報告と結果の節は allow_halted で開くので走る）。run の外の道具（dev/report.sh・
    dev/fixmeasure.py）と試験の手は窓に触らない。env の PEEK_ENV が 1 の時（役の sandbox の中で受け付けの確かめを読むだけで
    回す修正役の事前の確かめ。盤面は柵で書けない）は scope の登録も窓の照らしもしない（どちらも盤面を書く）"""
    d = pathlib.Path(board_dir)
    scope = flow_adapter.current_scope()
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
    names = frozenset()
    block = scopes.running_block()
    peek = os.environ.get(PEEK_ENV) == "1"   # 読むだけの開き（sandbox の中の事前の確かめ。盤面に書けない）
    if scope:
        if works.get("layout") != board.LAYOUT:
            raise BoardMismatch(f"盤面 {d} はこの版より前の盤面（state.works.layout {works.get('layout')!r}。今は {board.LAYOUT!r}）"
                                f"——include {scope!r} の私物を分けて置けない。移し替えない（この版で run を始め直す）")
        if not peek:
            scopes.claim(d, state["round"], scope, block)
        names = scopes.round_names()
    errs = []
    if not peek and flow_adapter.in_flow_node() and works.get("layout") == board.LAYOUT:   # 前の窓を閉じて照らし、今の scope の窓を開く
        errs = scopes.enter(d, state["round"], scope, block)
    b = DiskBoard.open(d, table=table, allow_halted=allow_halted, scope=scope, published=names, **open_kwargs(line, table))
    if errs:
        reason = (f"部品が宣言の外に書いた（{len(errs)} 件。manifest.json に宣言するか、書き先を scope の根へ移す）:\n"
                  + "\n".join(f"  - {e}" for e in errs))
        _halt_scope_check(b, scope or LINE, reason)
        if not allow_halted:
            raise BoardGap(reason)
    return b


def _halt_scope_check(b: DiskBoard, at: str, reason: str) -> None:
    """窓の照らしの誤りで盤面を止める（by scopes.SCOPE_CHECK_BY）。止められない盤面（周を締めた・もう止まった・終わった run。
    b.stop が Reject）には止めた事実を trace に 1 行（scopes.STOP_AFTER_END_OP。at・reason・by。line_edge と同じ逃げ）"""
    try:
        b.stop(reason, by=scopes.SCOPE_CHECK_BY)
    except Reject:
        b.trace(scopes.STOP_AFTER_END_OP, at=at, reason=reason, by=scopes.SCOPE_CHECK_BY)



# ---------------------------------------------------------------- 入力の確かめ（線 A の仕様 4 節）
LINE = "darkfactory"
ORIGIN = "works/darkfactory"   # 依頼の出どころ（record.process.request_entry.origin）
# 手厚さ（深さ）の語。自動（既定）は線が判定の単位ごとに機械で決める・軽量と標準は全部の単位をその深さに固定する（持ち主の
# 依頼 2026-10-06。計画 docs/plans/2026-10-06-variable-depth.md の決め 1。決めと上げは darkfactory/lib/depth.py）。重厚は受けない
THICKNESS = ("自動", "軽量", "標準", "重厚")
THICKNESS_DEFAULT = "自動"
FINAL_GATES = ("always", "when_needed", "protected_only")   # 最後の人の関所の開き方（C18・P1-R3。line_edge.FINAL_GATES と同じ語）
ADAPTER_MODES = ("", "optional")
UNATTENDED_WORDS = ("", gatemarks.UNATTENDED)   # 入力 unattended（空は人の居る run。true は無人の殻 use.sh の WORKS_USE_UNATTENDED=1）
DESIGN_ONLY_WORDS = ("", gatemarks.DESIGN_ONLY)   # 入力 design_only（空は今どおり。true は修正前の関所を必ず開ける設計だけの run）
# 入力 features_off が切る機能・features_on が入れる機能（持ち主の依頼 2026-10-07: 同じ依頼を機能を替えて回して比べる）。
# 語は線の入力の語で、線がブロックへ on・off・auto の平の入力（start の出口の同じ名の欄）に写す。並びは語の順（控えと報告の並びも同じ）
FEATURES = {
    "fix_lanes": "修正役の並べの枝（範囲の在る項目を修正の輪の前の枝の輪で単位の worktree ごとに同時に直す。切ると項目を作業ツリーで順に直す）",
    "graph_map": "工程の地図（印の旗 map の役の system prompt に、包みが全体のグラフとその役の居場所を足す。切ると足さない。"
                 "ブロックへは写さず、包みが start の控えを読む）",
    "judge_verify": "判定の裏取り（単位ごとの裏取りと単位どうしの相乗りの下請け。切ると申し送りを作らない。既定は off）",
    "review_tree": "事前審査の項目ごとの木（項目ごとの下請けと相乗りの審査。切ると審査役 1 つが案の全体を審査する。既定は auto＝"
                   "開いた項目が 2 つ以上の往復だけ木）",
    "tdd_lanes": "TDD の輪の並べの周（枝ごとの worktree で枝の単位を同時に直す。切ると単位を順に回す）",
}
# 名指さない機能の既定（持ち主の決め 2026-10-08。測り: 判定の裏取りは 27 単位の 11 run で後の段を 1 度も変えず 1 run に
# 0.6〜3 USD と 1〜2 分、事前審査の木は審査役 1 つの 2〜3 倍の費用で審査役 1 つが見逃した本物の穴を出さなかった）。ほかの機能は on。
# auto はブロックが自分の材料で決める語（事前審査の木: 開いた項目が 2 つ以上の往復だけ木）。名指した語（features_on・features_off）は既定に勝つ
FEATURE_DEFAULTS = {"judge_verify": script_io.SWITCH_OFF, "review_tree": script_io.SWITCH_AUTO}
FEATURES_KEY = "features_off"   # check_inputs の返りと start の控えの欄（語の順の配列）
FEATURES_ON_KEY = "features_on"   # 同じく入れる機能の欄（欄の無い控えは前の版の run。features_on_of が読む）
# start の控えの実効で off の機能の欄（既定で off の機能を含む語の順の配列。包みが工程の地図で読む。欄の無い控えは前の版で、
# 前の版の既定は全部 on なので features_off の語だけが off）
FEATURES_CUT_KEY = "features_cut"
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


def _feature_list(word: str, key: str) -> list:
    """入力 key（機能の語をカンマか空白で区切った 1 行）を、語の順に重ねずに並べた配列にする。FEATURES の外の語は名を言って
    InputRefused（黙って切らずに・入れずに回さない）"""
    words = [w for w in re.split(r"[\s,、・]+", word or "") if w]
    bad = [w for w in dict.fromkeys(words) if w not in FEATURES]
    if bad:
        raise InputRefused(f"{key} に知らない機能 {', '.join(bad)}（名指せるのは {' / '.join(FEATURES)}）")
    return sorted(set(words))


def features_off(word: str) -> list:
    """入力 features_off（切る機能。空は既定 FEATURE_DEFAULTS のまま）の語の配列"""
    return _feature_list(word, FEATURES_KEY)


def features_on(word: str) -> list:
    """入力 features_on（入れる機能。既定で off・auto の機能を on にする。空は既定のまま）の語の配列"""
    return _feature_list(word, FEATURES_ON_KEY)


def feature_words(off, on=()) -> dict:
    """start の出口の機能ごとの欄 {<機能>: on | off | auto}（線がブロックの切り替えの入力へ写す）。名指した語が既定に勝つ:
    features_on の語は on・features_off の語は off・どちらにも無ければ FEATURE_DEFAULTS（無ければ on）。両方に在る語は
    check_inputs が拒むので届かない"""
    off, on = set(off or ()), set(on or ())
    return {name: script_io.SWITCH_ON if name in on else script_io.SWITCH_OFF if name in off
            else FEATURE_DEFAULTS.get(name, script_io.SWITCH_ON) for name in FEATURES}


def features_cut(off, on=()) -> list:
    """実効で off の機能の語（語の順。start の控えの FEATURES_CUT_KEY）"""
    return [k for k, v in feature_words(off, on).items() if v == script_io.SWITCH_OFF]


def features_on_of(doc: dict) -> list:
    """start の控え doc の入れた機能。features_on の欄の無い控えは前の版の run で、その版の既定は全部 on なので、既定で
    on でない機能のうち features_off に無い物を入れた物と読む（呼び直しと報告で腕を黙って替えない）"""
    if FEATURES_ON_KEY in doc:
        return list(doc.get(FEATURES_ON_KEY) or [])
    off = set(doc.get(FEATURES_KEY) or [])
    return sorted(k for k in FEATURE_DEFAULTS if k not in off)


def features_part(off, on=()) -> str:
    """頭の行と報告の冒頭 2 の機能の語: on でない機能を語の順に「<機能> <off|auto>」で並べる（全部 on なら「機能: 全部 on」）"""
    rest = [f"{k} {v}" for k, v in feature_words(off, on).items() if v != script_io.SWITCH_ON]
    return f"機能: {'・'.join(rest)}" if rest else "機能: 全部 on"


def _resumed_features(prev: dict, off: list, on: list) -> list:
    """呼び直し（Archon の再開）で前の控えの切った機能・入れた機能と今の入力が違えば InputRefused（run の途中で比べの腕を黙って
    替えない）。返りはこの run の入れた機能。run は start の時に写した works で回るので、控えは同じ版の start が書いた物"""
    was = prev.get(FEATURES_KEY) or []
    if list(was) != list(off):
        raise InputRefused(f"この盤面は {FEATURES_KEY}={','.join(was) or '空'} で始めた——呼び直しの {FEATURES_KEY}="
                           f"{','.join(off) or '空'} で機能を替えない（同じ入力で呼び直す）")
    keep = list(prev.get(FEATURES_ON_KEY) or [])
    if list(on) != sorted(keep):
        raise InputRefused(f"この盤面は {FEATURES_ON_KEY}={','.join(keep) or '空'} で始めた——呼び直しの {FEATURES_ON_KEY}="
                           f"{','.join(on) or '空'} で機能を替えない（同じ入力で呼び直す）")
    return keep


def check_inputs(raw: dict, repo: pathlib.Path, *, reads=None) -> dict:
    """ラインの入力を確かめて {request_file, items, request_text, test_cmd, thickness, gates, final_gate, adapter, policy_md, lang,
    unattended, design_only, fix_fixture, features_off, features_on, answers} を返す（features_off・features_on は切る機能・入れる機能の語の配列で、features_off()・features_on() が確かめ、両方に在る語は拒む。unattended・design_only は start の控え r1/start.json に残り、gatemarks が修正前の関所で読む。
    fix_fixture は固定材料のフォルダ
    （core の fixture。修正を待つ盤面の写し）で、空か在るフォルダの絶対パス。相対なら対象の根から）。
    差分の根（base の版か pr の番号）を名指せば {base_rev, base, pr} も足す（_change_base。base_rev は base と HEAD の merge-base）。
    依頼が無ければ request_file・request_text は空・items と answers は []。依頼の行が空なら差分を測り（board.diff_of。名指しが
    無ければ HEAD から）、差分も空なら拒む（EMPTY_REFUSED。依頼の行が在れば git を測らない）。answers は依頼の欄 answers
    （依頼者の答え。配列の形の依頼は []）で、start の控えに残り、gatemarks が問いの答えたかで読む。
    盤面は作らない。拒む物（InputRefused）: 依頼の行も差分も無い・base と pr の両方・版や PR が引けない・PR の head が HEAD でない、
    依頼が読めない・findings の配列でも {findings, pr, issue, answers} の形でもない・answers の形が違う・findings が依頼の型（写しの RL の REQUEST_SCHEMA）に
    合わない、thickness が重厚・知らない値、final_gate・adapter・unattended・design_only・gates が語の外（gates の文は写しの RL の check_inputs）、
    名指した方針の文書・固定材料のフォルダが無い。test_cmd が空で宣言（.review-checks.json）も無い run は拒まない（裁定 R52: graphloops と同じく
    p0.local_checks・p4.ci が任せ先の役に落ち、役がリポジトリを読んでテストの走らせ方を探す）。
    相対のパス（依頼・方針の文書）は対象の根 repo から。reads は start が run の中で読んだ PR・issue（_github_reads の返り。pr が読む）"""
    repo = pathlib.Path(repo)
    thickness = _word(raw, "thickness") or THICKNESS_DEFAULT
    if thickness == "重厚":
        raise InputRefused(HEAVY_REFUSED)
    if thickness not in THICKNESS:
        raise InputRefused(f"thickness={thickness!r} は知らない値（{' / '.join(THICKNESS)}。重厚は受けない）")
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
    off = features_off(_word(raw, FEATURES_KEY))
    on = features_on(_word(raw, FEATURES_ON_KEY))
    both = [w for w in on if w in off]
    if both:
        raise InputRefused(f"{FEATURES_ON_KEY} と {FEATURES_KEY} の両方に {', '.join(both)}（入れるか切るかのどちらか 1 つに名指す）")
    gates = _word(raw, "gates")
    rules = board_rules()
    try:
        rules.check_inputs({"gates": gates} if gates else {})
    except Reject as e:
        raise InputRefused(f"gates: {e}") from None
    change = _change_base(raw, repo, reads)
    rel = _word(raw, "request")
    if not rel:
        path, text, items, answers, prior = None, "", [], [], []
    else:
        path, text, items, answers, prior = _read_request(rel, repo, rules)
    if not items and _diff(repo, change["base_rev"] if change else _git(repo, "rev-parse", "HEAD"))["empty"]:
        raise InputRefused(f"{EMPTY_REFUSED}——依頼（request）を名指すか、差分の在る base・PR を名指す（差分の根から作業ツリーまでが空で、"
                           "依頼の行も無い）")
    pol = _word(raw, "policy_md")
    if pol:
        pp = pathlib.Path(pol) if pathlib.Path(pol).is_absolute() else repo / pol
        if not pp.is_file():
            raise InputRefused(f"名指した方針の文書 {pol} が無い（policy_md。人の方針の文書を名指すなら先に置く）")
        pol = str(pp)
    fx = _word(raw, "fix_fixture")
    if fx:
        fp = pathlib.Path(fx) if pathlib.Path(fx).is_absolute() else repo / fx
        if not fp.is_dir():
            raise InputRefused(f"名指した固定材料のフォルダ {fx} が無い（fix_fixture。前の run が修正の前に $ARTIFACTS_DIR/{fixture.DIR} に写した物）")
        fx = str(fp)
    out = {"request_file": str(path.resolve()) if path else "", "items": items, "request_text": text,
           "test_cmd": _word(raw, "test_cmd"), "thickness": thickness, "gates": gates, "final_gate": final_gate,
           "adapter": adapter, "policy_md": pol, "lang": _word(raw, "lang"), "unattended": unattended,
           "design_only": design_only, "fix_fixture": fx, FEATURES_KEY: off,
           FEATURES_ON_KEY: on,
           carry.ANSWERS: answers, carry.PRIOR: prior}
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
    """差分の根を名指す入口（base か pr）を解いて {base_rev, base: {rev, from, name}, pr: {number, title, body} | None} を返す。
    どちらも無ければ None（差分の根は HEAD。build_input が埋める）。両方は拒む。base.from は誰が根を決めたかの名札（base・pr）で、
    後ろの段は分岐に使わない（頭の行と報告に書くだけ）。
    pr は gh を呼ばず、start が run の中で読んだ読み出し reads（ghreads.read_named の返りか、再開では盤面の github.json）の
    pr[<番号>] を読む（設計書 2.8）。読み出しに無い・読めなかった項・head が今の HEAD と違えば拒む（別の版を
    黙って見ない）。差分の根は GitHub が持つ base の版（baseRefOid）と HEAD の merge-base——fetch しないローカルの枝は古いことが
    あるので名前では引かない。pr の題と本文は添え物（_request_text が盤面の依頼の文に並べる）"""
    base, pr = _word(raw, "base"), _word(raw, "pr")
    if base and pr:
        raise InputRefused(f"base={base!r} と pr={pr!r} を両方名指した——どちらの差分か決まらない（片方だけ）")
    if base:
        rev = _merge_base(repo, base)
        return {"base_rev": rev, "base": {"rev": rev, "from": "base", "name": base}, "pr": None}
    if not pr:
        return None
    if not pr.isdigit():
        raise InputRefused(f"pr={pr!r} は PR の番号でない")
    doc = ((reads or {}).get("pr") or {}).get(pr)
    if not isinstance(doc, dict) or not doc.get("baseRefOid") or not doc.get("headRefOid"):
        why = " ".join(str((doc.get("reason") if isinstance(doc, dict) else "") or "読み出しにこの PR の base・head が無い").split())
        if isinstance(doc, dict) and doc.get("status") == ghreads.NOT_APPLICABLE:   # forge の無い対象で gh も GitHub を見つけなかった
            raise InputRefused(f"PR #{pr} の base・head を読めない——対象の remote に PR を持つホストが無い（{why}）。base を名指して回す")
        raise InputRefused(f"PR #{pr} の base・head を読めない（{why}）——利用者の gh でログインしてから回す")
    head = _git(repo, "rev-parse", "HEAD")
    if doc["headRefOid"] != head:
        raise InputRefused(f"PR #{pr} の head {doc['headRefOid'][:12]} が対象の HEAD {head[:12]} と違う——PR の head を"
                           "取り出した所で始める")
    oid = doc["baseRefOid"]
    if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{oid}^{{commit}}"], capture_output=True).returncode:
        raise InputRefused(f"PR #{pr} の base の版 {oid[:12]} が対象に無い——fetch してから始める")
    rev = _merge_base(repo, oid)
    return {"base_rev": rev, "base": {"rev": rev, "from": "pr", "name": pr},
            "pr": {"number": pr, "title": str(doc.get("title") or "").strip(), "body": str(doc.get("body") or "").strip()}}


EMPTY_REFUSED = "直す物も審査する物も無い"   # 差分が空で依頼の行も空の入力を start が拒む文の頭


def _diff(repo: pathlib.Path, base_rev: str) -> dict:
    """board.diff_of の Reject を InputRefused にした物"""
    try:
        return board.diff_of(repo, base_rev)
    except Reject as e:
        raise InputRefused(f"差分を測れない: {e}") from None


def build_input(inp: dict, repo: pathlib.Path) -> dict:
    """check_inputs の返りから、入口の入力の形（r1/start.json の欄 input。schema は darkfactory/schemas/input.schema.json）を作る:
    {base: {rev, from, name}, head_rev, diff: {empty, files, stat}, requests, request_file, pr: {number, title} | None, spec}。
    base は差分の根（名指しが無ければ HEAD・from head）、diff は差分の根から作業ツリーの今の姿までの測り（board.diff_of）、
    requests は依頼の行の数、pr は PR の番号と題（本文は盤面の依頼の文と github.json に在るので写さない）。
    後ろの段（盤面・ブロック・境の節・報告）はこの形の中身（diff.empty・requests・pr・spec）だけを読み、入口の種類を見ない"""
    repo = pathlib.Path(repo)
    head = _git(repo, "rev-parse", "HEAD")
    base = inp.get("base") or {"rev": head, "from": "head", "name": ""}
    pr = inp.get("pr")
    return {"base": dict(base), "head_rev": head, "diff": _diff(repo, base["rev"]), "requests": len(inp["items"]),
            "request_file": inp["request_file"], "pr": {"number": pr["number"], "title": pr["title"]} if pr else None,
            "spec": False}


def _read_request(rel: str, repo: pathlib.Path, rules):
    """依頼のファイルを読んで (path, text, items, answers, prior_failures)。items は findings の行、answers は依頼者の答え、
    prior_failures は前の run で最後まで通らなかった物（配列の形も
    {findings, pr, issue, answers} の形も carry.parts で解く）。読めない・どちらの形でもない・依頼の型に合わない は InputRefused"""
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
        parts = carry.parts(doc)
    except ValueError as e:
        raise InputRefused(f"依頼のファイル {rel} の形: {e}") from None
    items = parts[carry.FINDINGS]
    errs = validate_schema([{"round": 1, "origin": ORIGIN, "findings": items}], rules.REQUEST_SCHEMA)
    if errs:
        raise InputRefused(f"依頼のファイル {rel} の形: findings の配列か {{findings, pr, issue, answers}} の形で、findings は "
                           "[{where, text, mechanism?, measured?, false_positive_if?}] の配列（空でない）: " + "; ".join(errs))
    return path, text, items, parts[carry.ANSWERS], parts[carry.PRIOR]


def board_rules():
    """写しの RL（盤面なし。入口の検査に使う）"""
    from board import rules_module
    return rules_module()


# ---------------------------------------------------------------- CI の節（p0.local_checks・p4.ci）


def local_checks_material(repo: pathlib.Path, test_cmd: str, log_path: pathlib.Path, *, launched: dict | None = None,
                          niced: bool = False) -> dict:
    """任せ先に落ちた CI の節に渡す素材 {"material": …} を組む（盤面なしで呼べる公開の口。線 B の申し送り 2）。
    test_cmd を tree_run.command_argv の形（direct か shell）で tree_run.slotted_run に走らせ（機械全体の試験の枠を通す・対象の根で・
    標準入力は空・環境は tree_run.outside_env。
    標準出力と標準エラーを log_path に）、終了コード 0 なら clean（写しの RR の規則で checked が要る）、他は found・count 1。
    detail はログの末尾（engine の段の末尾と同じ切り方）。起こせなければ（shell の先頭の語が tree_run.prove_launchable の証明を
    通らない回も）not_run。test_cmd が空なら走らせずに not_run。
    止められたら（tree_run.Stopped）捕まえない。launched（dict）を渡せば、起こす前に決めた起こし方を launched["how"] に置く
    （返りの素材の形は変えない）。niced が真なら、起こすプロセス（枠の台本とその下の木）の優先度を nice -n 19 と同じだけ下げる
    （TDD の輪の中の test_cmd。ADR 0071 の 3 の 1。argv・起こし方・起こせなさの証明は変えない）"""
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
                                           stdout=f, stderr=subprocess.STDOUT, cwd=str(repo),
                                           **({"preexec_fn": _nice19} if niced else {}))
        except OSError as e:
            return {"material": {"status": "not_run", "reason": f"{_launched(argv, how)} でテストのコマンドを起こせない: {e}"}}
    return _cmd_material(code, log_path, argv, how)


def _nice19() -> None:
    """子の中で exec の前に呼ぶ（Popen の preexec_fn）: nice -n 19 と同じだけ優先度を下げる"""
    os.nice(19)


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
    return {"material": {"status": "found", "count": 1,
                         "detail": f"{ran} ／ 末尾: {tail} ／ {gatemarks.BASELINE_UNVERIFIED}（test_cmd は shell の文字列で、試験の報告を宣言できない）"}}


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
    if status in ("not_run", "awaiting_human"):
        return f"修正前のテスト: {word}（{told}・{base.get('reason') or '理由なし'}）——{gatemarks.BASELINE_NOT_RUN}"
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


def role_waits(b, nid: str) -> bool:
    """CI の節 nid（p0.local_checks・p4.ci）が任せ先に落ちて待っている（instance が pending で engine_fallback を持つ）。
    任せ先の CI の役を回すかの正本: start の ci_role_go（p0.local_checks）・線が最後のテストの後に p4.ci を回すかの go・任せ先の CI の役の
    入口（ci_role）が同じこれを読む"""
    return _is_ci(b, nid) and _fell_back(b, nid)


def _fell_back(b, nid: str) -> bool:
    """nid の instance が任せ先に落ちて待っている（CI の節かは見ない。run_ci は CI の節を受け取る口なので、これだけを見る）"""
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
            left = [n for n in p["ready"] if role_waits(b, n) and n not in ran] if test_cmd.strip() else []
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
    return {"ci_role_go": any(role_waits(b, n) for n in p["ready"]), "pr_go": _pr_go(b, pr)}


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


def _request_text(inp: dict) -> str:
    """盤面の依頼の文（DiskBoard.begin の request_text。固定材料の依頼の sha256 もこの文で照らす）。依頼のファイルの文と PR の題・
    本文の在る物を並べる: 両方なら見出し「## 依頼」「## PR #N の題と本文」つき、片方だけならその文のまま（固定材料の sha256 を
    変えない）、どちらも無ければ差分の審査の 1 行"""
    pr = inp.get("pr")
    pr_text = "\n\n".join(x for x in (pr["title"], pr["body"]) if x) if pr else ""
    req = inp["request_text"]
    if req and pr_text:
        return f"## 依頼\n\n{req.strip()}\n\n## PR #{pr['number']} の題と本文\n\n{pr_text}\n"
    if req or pr_text:
        return req or pr_text
    base = inp.get("base") or {"from": "head", "name": "HEAD"}
    return f"変更（{base['from']} {base['name']}）の審査"


def _kept(inp: dict) -> dict:
    """check_inputs の返りのうち start の控えに残す欄（依頼の行と文は控えに残さない。prior_failures は盤面の根の
    carry.PRIOR_IN_FILE が運ぶ）"""
    return {k: v for k, v in inp.items() if k not in ("items", "request_text", carry.PRIOR)}


def adopt_inputs(inp: dict) -> dict:
    """固定材料の取り込み（fixture.adopt）が start の控えと照らす今の入力の欄: _kept から base_rev と answers を除いた物（start は控えの
    base_rev を修正の起点の版で上書きするので、入力の base_rev は控えに残らない。answers は依頼の文の sha256 が照らすので二重に
    照らさず、欄の無い前の版の固定材料も読める）"""
    return {k: v for k, v in _kept(inp).items() if k not in ("base_rev", "answers")}


def _fixture_words(doc: dict) -> str:
    """固定材料の控えの入口の文（input の無い前の版の控えは、その事実を書く）"""
    shape = doc.get("input")
    return input_words(shape) if isinstance(shape, dict) else "控えに入口の入力の形が無い（前の版の固定材料）"


FIXTURE_MISMATCH = "固定材料と works の版が違う"   # 取り込んだ盤面を今の表・graph で開けない時の拒みの頭


def _start_from_fixture(board_dir: pathlib.Path, repo: pathlib.Path, raw: dict, inp: dict, *, run_id: str) -> dict:
    """入力 fix_fixture の start（DiskBoard.begin・_drain の代わり）。順:
    1. fixture.adopted が在れば（前の start が取り込んだ）、取り込み直さない（Archon の呼び直し。取り込みは空でない置き場を
       拒むので、ここで分けないと固定材料の run を続けられない）。前の控えの test_cmd と違えば InputRefused（通常の
       呼び直しと同じ）。無ければ fixture.adopt（入力は adopt_inputs。FixtureRefused は InputRefused。盤面は作らない）
    2. open_board。表・graph が違う、か部品の置き場の版（state.works.layout）が今の board.LAYOUT でなければ（BoardMismatch）
       取り込んだ盤面を消して InputRefused（FIXTURE_MISMATCH）
    3. 取り込んだ時だけ盤面の trace に fixture.TRACE_OP の 1 行
    4. ticket.write、start の控えに ci_role_go（偽）・pr_go（控えの値）・頭の行を書き足す
    返りは start と同じ形。取り込みは start の控えの入力の欄を今の入力と照らすので、入力の欄は控えの値も今の値も同じ"""
    work = board_dir / fixture.START_REL
    resumed = fixture.adopted(board_dir) is not None
    if resumed:
        prev = json.loads(work.read_text(encoding="utf-8"))
        if prev.get("test_cmd") != inp["test_cmd"]:
            raise InputRefused(f"この盤面は test_cmd={prev.get('test_cmd')!r} の固定材料から始めた——呼び直しの "
                               f"test_cmd={inp['test_cmd']!r} で道を替えない（同じ入力で呼び直す）")
        on = _resumed_features(prev, inp[FEATURES_KEY], inp[FEATURES_ON_KEY])
        doc = prev
    else:
        try:
            doc = fixture.adopt(board_dir, inp["fix_fixture"], repo, run_id=run_id, pack_root=PACK,
                                request_text=_request_text(inp), inputs=adopt_inputs(inp))
        except fixture.FixtureRefused as e:
            raise InputRefused(f"固定材料を取り込まない: {e}") from None
        on = inp[FEATURES_ON_KEY]
    try:
        b = open_board(board_dir)
        layout = b.state["works"].get("layout")
        if layout != board.LAYOUT:   # 線の最上段は scope なしで開けるので、後の include の中で開けなくなる前にここで止める
            raise BoardMismatch(f"盤面 {board_dir} はこの版より前の固定材料（state.works.layout {layout!r}。今は "
                                f"{board.LAYOUT!r}）——部品の私物を include の置き場に分けていない。この版で写し直す")
    except BoardMismatch as e:
        if not resumed:
            shutil.rmtree(board_dir, ignore_errors=True)   # 取り込んだ盤面を残さない（直して呼び直せるように）
        raise InputRefused(f"{FIXTURE_MISMATCH}: {e}") from None
    if not resumed:
        b.trace(fixture.TRACE_OP, source=inp["fix_fixture"], source_run=doc[fixture.KEY]["source_run"],
                manifest_sha256=doc[fixture.KEY]["manifest_sha256"])
    try:
        ticket.write(board_dir, repo, run_id)
    except ticket.TicketError as e:
        raise InputRefused(f"包みの切符を書けない: {e}") from None
    pol = policy.brief(b)
    head = (f"入口: 固定材料から（run {doc[fixture.KEY]['source_run']} の修正の前。判定と修正案は写しの物）・"
            f"{_fixture_words(doc)}・{features_part(inp[FEATURES_KEY], on)}・"
            f"{prcheck.head_downgrades(LINE)}")
    go = {"ci_role_go": False, "pr_go": doc.get("pr_go", False)}
    _write_json(work, {**doc, **go, FEATURES_CUT_KEY: features_cut(inp[FEATURES_KEY], on), "head_line": head})
    return {"ok": True, "input": doc.get("input"), "base_rev": doc["base_rev"], "test_cmd": doc["test_cmd"],
            "policy_paste": pol["paste"], "policy_path": pol["path"], "final_gate": doc["final_gate"], "adapter": doc["adapter"],
            "thickness": doc["thickness"], "gates": doc["gates"], **feature_words(inp[FEATURES_KEY], on), **go,
            "head_line": head}


# 認証の要らない起動（開発の殻 dev/archon.sh。テスト・validate・workflow test）の印。この run の中の gh は利用者の gh の
# ログインを継がない（dev/hostgh.py の口を置かない）ので、名指した PR・issue を読めない
NO_AUTH_ENV = "WORKS_DEV_NO_AUTH"


def _named(raw: dict, repo: pathlib.Path):
    """入力 pr と依頼の欄 pr・issue が名指した (PR の番号の並び, issue の番号の並び)。依頼が読めない・形の外なら依頼の分は
    無しにする（形の誤りは check_inputs が拒む）"""
    pr = _word(raw, "pr")
    prs, issues = ([int(pr)] if pr.isdigit() else []), []
    rel = _word(raw, "request")
    if rel:
        path = pathlib.Path(rel) if pathlib.Path(rel).is_absolute() else repo / rel
        try:
            parts = carry.parts(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, ValueError):
            return prs, issues
        prs, issues = list(dict.fromkeys(parts[carry.PR] + prs)), list(parts[carry.ISSUE])
    return prs, issues


def _github_reads(board_dir: pathlib.Path, repo: pathlib.Path, raw: dict):
    """名指した PR・issue を run の中で gh で読んだ読み出し（ghreads.read_named。読めない項も記録して返す）。名指しが無ければ
    None。盤面の根に github.json が在れば（Archon の再開）それを使い、読み直さない（run の中で同じ版を見る）。
    認証の要らない起動（NO_AUTH_ENV）で名指せば、gh を呼ばずに 1 行で拒む（読めないと黙って記録しない）"""
    try:
        kept = ghreads.load_board(board_dir)
    except (OSError, ValueError) as e:
        raise InputRefused(f"盤面の {ghreads.BOARD_FILE} を読めない（{type(e).__name__}: {e}）") from None
    if kept is not None:
        return kept
    prs, issues = _named(raw, repo)
    if not prs and not issues:
        return None
    if os.environ.get(NO_AUTH_ENV) == "1":
        named = "・".join([f"PR #{n}" for n in prs] + [f"issue #{n}" for n in issues])
        raise InputRefused(f"{named} を名指したが、この run は {NO_AUTH_ENV}=1 で起こしたので run の中の gh が利用者のログインを"
                           "継がず読めない——認証を使う起動（use.sh start・dogfood.sh）で回す")
    return ghreads.read_named(repo, prs, issues)


P1_OFF_WORDS = "P1 の役は起こさない"   # 差分が空の run の頭の行の尻（印が立ち、1 周目の P1 の役を起こさない）


def input_words(shape: dict) -> str:
    """頭の行と報告の冒頭 2 の入口の文を、入口の入力の形（build_input の返り）から作る 1 本。例:
    差分 1a2b3c4d5e6f..HEAD（3 ファイル・base main）・依頼 2 件 ／ 差分なし（HEAD）・依頼 2 件——P1 の役は起こさない ／
    差分 …（PR #12「題」）・依頼 0 件・仕様の段あり。base.from は誰が差分の根を決めたかの表示にだけ使う"""
    base, diff, pr = shape["base"], shape["diff"], shape.get("pr")
    origin = (f"PR #{pr['number']}「{pr['title']}」" if pr else f"PR #{base['name']}") if base["from"] == "pr" else \
        f"base {base['name']}" if base["from"] == "base" else "HEAD"
    if diff["empty"]:
        out = f"差分なし（{origin}）・依頼 {shape['requests']} 件——{P1_OFF_WORDS}"
    else:
        out = f"差分 {base['rev'][:12]}..HEAD（{diff['files']} ファイル・{origin}）・依頼 {shape['requests']} 件"
    return out + ("・仕様の段あり" if shape.get("spec") else "")


def _kept_input(board_dir: pathlib.Path):
    """呼び直し（Archon の再開）の時、最初の start が控えた入口の入力の形（r1/start.json の欄 input）。控えが無ければ None。
    控えは在るのに input が無い・dict でなければ InputRefused（測り直さない。修正が作業ツリーを進めた後に測ると別の値になる）"""
    path = board_dir / fixture.START_REL
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InputRefused(f"start の控え {path} を読めない（{type(e).__name__}: {e}）") from None
    shape = doc.get("input") if isinstance(doc, dict) else None
    if not isinstance(shape, dict):
        raise InputRefused(f"start の控え {path} に入口の入力の形（input）が無い——この版より前の盤面は続けない（新しい置き場で始める）")
    return shape


def start(board_dir: pathlib.Path, repo: pathlib.Path, raw: dict, *, run_id: str, runner=None) -> dict:
    """ラインの入口。順:
    1. _github_reads（名指した PR・issue を run の中で gh で読む。再開では盤面の根の github.json を先に）→ check_inputs（拒めば
       盤面を作らずに InputRefused。差分も依頼の行も無い入力もここで拒む）。盤面を作った後に読み出しを盤面の根の github.json に置く。
       入力 fix_fixture（固定材料）が在れば、ここから先は _start_from_fixture（取り込み → 盤面を開く → trace → 切符。begin と
       CI の輪を回さない）
    2. 入口の入力の形（build_input。差分の根・差分・依頼の行・PR）を作る。呼び直しでは最初の控えの input を使い、測り直さない
    3. DiskBoard.begin（1 周の run。origin works/darkfactory・stop_after_round=1・board_hook.py の overrides・validator_runner）。
       依頼の行が在ればいつも盤面を作る時に積み、入口の測り diff_empty を渡す。入口の印（P1 の役を起こさない）は差し替え
       entry_opens_by_diff が「差分が空」の時だけ立てる——差分が在れば P1 の役が差分に回り、依頼は 1 周目の判定に届く。
       P1 の差分の根（record.base）は input.base.rev（名指しが無ければ HEAD）。lang が空でなければ inputs.lang に渡す（本線
       loop.py の --lang。空は盤面の既定 LANG_DEFAULT＝依頼文の言語）。入口の Reject は InputRefused
    4. テストを走らせる前に r1/start.json に入力の控え（入口の入力の形 input を含む）と、宣言が無い時の道 ci_fallback（test_cmd か
       role）を置く。呼び直し（Archon の再開）で前の控えの test_cmd と違えば InputRefused（止められた run を別の道で黙って続けない）
    5. _drain（盤面の約束 1 の輪。CI の節は run_ci、p0.parallel_pr は prcheck.run_helper。止められた test_cmd は走らせ直す）
    6. 切符（ticket.write）を書き、r1/start.json を結果つきで書き直す
    返り {ok, input, base_rev, test_cmd, policy_paste, policy_path, final_gate, adapter, thickness, gates, ci_role_go,
    pr_go, head_line}。
    input は入口の入力の形（後ろの段は入口の種類を見ず、この中身だけを読む）。base_rev は修正の起点（修正前の HEAD）で、下流の差分・
    受け付けが「修正が触った物」を切る版。P1 の差分の根（merge-base）は盤面の record.base と input.base にだけ置き、
    ここには出さない（PR にもとからある変更を修正の変更と取り違えない）。
    ci_role_go は CI の節（p0.local_checks）が任せ先に落ちたまま待っている（test_cmd も宣言も無い。裁定 R52）。pr_go は _pr_go の
    3 値——"pending" の run は、CI の役の後に resume_after_ci が測る"""
    repo = pathlib.Path(repo).resolve()
    board_dir = pathlib.Path(board_dir)
    reads = _github_reads(board_dir, repo, raw)
    inp = check_inputs(raw, repo, reads=reads)
    if inp["fix_fixture"]:
        return _start_from_fixture(board_dir, repo, raw, inp, run_id=run_id)
    shape = _kept_input(board_dir) or build_input(inp, repo)
    table = load_table(LINE)
    try:
        b, p = DiskBoard.begin(board_dir, repo=repo, table=table, items=inp["items"] or None, origin=ORIGIN,
                               base_rev=inp.get("base_rev", ""), request_text=_request_text(inp),
                               inputs={"gates": inp["gates"] or None, "policy_md": inp["policy_md"] or None,
                                       **({"lang": inp["lang"]} if inp["lang"] else {})},
                               stop_after_round=1, diff_empty=shape["diff"]["empty"], **open_kwargs(LINE, table))
    except Reject as e:
        raise InputRefused(f"盤面が入力を受けない: {e}") from None
    if reads is not None and not (board_dir / ghreads.BOARD_FILE).is_file():
        try:
            ghreads.place(board_dir, reads)
        except OSError as e:
            raise InputRefused(f"読んだ PR・issue を盤面の {ghreads.BOARD_FILE} に置けない（{type(e).__name__}: {e}）——"
                               "resume で読み直す") from None
    carry.place_prior(board_dir, inp[carry.PRIOR])
    keep = _kept(inp)
    work = b.work(START_FILE)
    prev = {}
    if work.is_file():
        prev = json.loads(work.read_text(encoding="utf-8"))
        if prev.get("test_cmd") != inp["test_cmd"]:
            raise InputRefused(f"この盤面は test_cmd={prev.get('test_cmd')!r}（宣言が無い時の道: {prev.get('ci_fallback')}）で"
                               f"始めた——呼び直しの test_cmd={inp['test_cmd']!r} で道を替えない（同じ入力で呼び直す）")
        on = _resumed_features(prev, inp[FEATURES_KEY], inp[FEATURES_ON_KEY])
    else:
        on = inp[FEATURES_ON_KEY]
    # 呼び直し（Archon の再開）では、修正が HEAD を進めていても最初の控えの起点を使う
    base_rev = prev.get("base_rev") or shape["head_rev"]
    doc = {**keep, "run_id": run_id, "requests": len(inp["items"]), "base_rev": base_rev, "input": shape,
           "ci_fallback": "test_cmd" if inp["test_cmd"] else "role", FEATURES_CUT_KEY: features_cut(inp[FEATURES_KEY], on)}
    _write_json(work, doc)
    go = _drain(b, p, test_cmd=inp["test_cmd"], runner=runner)
    try:
        ticket.write(board_dir, repo, run_id)
    except ticket.TicketError as e:
        raise InputRefused(f"包みの切符を書けない: {e}") from None
    pol = policy.brief(b)
    absent = len(b.state["works"].get("not_in_line") or [])
    thick = inp["thickness"] + ("（既定）" if not _word(raw, "thickness") else "")
    head = (f"入口: {input_words(shape)}・段: {thick}・gates: {inp['gates'] or '空'}・"
            f"{features_part(inp[FEATURES_KEY], on)}・このラインに無い節: {absent} 個・{prcheck.head_downgrades(LINE)}")
    if go["ci_role_go"]:
        head += "・修正前のテスト: 宣言も test_cmd も無い——任せ先の役がリポジトリから走らせ方を探す"
    out = {"ok": True, "input": shape, "base_rev": base_rev, "test_cmd": inp["test_cmd"], "policy_paste": pol["paste"],
           "policy_path": pol["path"], "final_gate": inp["final_gate"], "adapter": inp["adapter"], "thickness": inp["thickness"],
           "gates": inp["gates"], **feature_words(inp[FEATURES_KEY], on), **go, "head_line": head}
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


def take(board_dir: pathlib.Path, nid: str, reply: dict, repo: pathlib.Path, *, snapshot_name: str | None = None,
         commit: bool = True, settle: bool = True) -> dict:
    """役の返答を盤面に渡す（各ブロックの受け付けが使う 1 つの口）。順:
    1. 盤面を開く（open_board）。止めた run はここで Reject（役に返さない。作業ツリーの比べより先）
    2. snapshot_name が在れば、役を起こす前の写し（snapshot）と今の作業ツリーを比べ、違えば
       {"ok": False, "reason": "読むだけの役が作業ツリーを変えた: …"}（盤面は書かない。TA11）
    3. b.done(nid, reply)（写しの schema → 番号の読み替え → post_check → writes → check_record → 保存 → settle）。
       settle が偽なら b.accept(nid, reply)（同じ順で保存まで。settle しない＝後ろの節は進めない。呼び手が後で settle する）
    通れば {"ok": True, "reason": "", "ready", "asking", "halted", "out_file"}（out_file は state.outputs[nid]["file"]。
    盤面の置き場からの相対。周を仮定しない。settle が偽なら進んだ物は無いので ready は空・asking と halted は偽）。写しの AnswerReject（返答の中身の誤り）だけを {"ok": False, "reason": 文} に
    する（盤面は書かれない。入れ物は捨てる——盤仕様 4.1）。ほかの Reject（止めた run への書き込みなど）と BoardGap（表で
    受けない節・印の無い試行・写しの欠け）は投げ直す（回す側の誤りで、役に返しても直らない。TA19）。
    commit が偽なら 3 の代わりに b.vet(nid, reply)（同じ検査を当てて保存しない。開いた入れ物は捨てる）で、返りは
    {"ok", "reason", "dry": True}。拒否なら problems（AnswerReject の problems。空なら [reason]）も。1・2 は commit に依らず当てる。
    DiskBoard.edit は使わない（done の中で保存される）。起こした印（mark_launched）は役を起こす前にブロックの snap の節が置く"""
    b = open_board(board_dir)
    _refuse_halted(b)
    if snapshot_name is not None:
        moved = _tree_moved(b, snapshot_name, repo)
        if moved:
            return {"ok": False, "reason": READONLY_MOVED + moved}
    if not commit:
        e = b.vet(nid, reply)
        if e is None:
            return {"ok": True, "reason": "", "dry": True}
        return {"ok": False, "reason": str(e), "dry": True, "problems": e.problems or [str(e)]}
    try:
        if settle:
            p = b.done(nid, reply)
        else:
            b.accept(nid, reply)
            p = {"ready": [], "asking": False, "halted": False}
    except AnswerReject as e:
        return {"ok": False, "reason": str(e), **({"problems": e.problems} if e.problems else {})}
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
EMPTY_FIX_OP = "empty_fix"                   # 機械が p3.fix の空の返答を渡した印の trace の行（TA6）
EMPTY_FIX_BY = "works:empty-fix"


def empty_fix_reply(b=None, why: str = EMPTY_FIX_REASON) -> dict:
    """機械が渡す p3.fix の空の返答（TA6）。changes は空、fix_closure は not_applicable で理由は why（写しの graph の
    p3.fix は na_self_ok を宣言し、fix_covers_open_units は changes が空なら義務 0 件の周を通す）、他の必須の欄は空の値。
    盤面 b が在り、今の周の p2.plan_review の出力が在れば、plan_faces にその faces と shrink の key ごとに declared の行
    （how は why。写しの型は how に 20 字以上を求める）。呼ぶたびに新しい dict"""
    review = b.output_of_round("p2.plan_review", b.round) if b is not None else None
    faces = [{"key": r["key"], "handled": "declared", "how": why}
             for r in ((review or {}).get("faces") or []) + ((review or {}).get("shrink") or [])
             if isinstance(r, dict) and isinstance(r.get("key"), str)]
    return {"changes": [], "fix_closure": {"status": "not_applicable", "reason": why},
            "gates_changed": False, "interactions": [], "mechanism_changed": False, "not_done": [], "path_changed": False,
            "plan_faces": faces, "premise_drift": False, "seams_changed": False, "security_surface_changed": False,
            "wrote_refs": []}


def trace_empty_fix(b) -> None:
    """機械が p3.fix の空の返答を渡した印を trace に 1 行（空の返答を渡した側——線と修正の受け付け——が take の後に呼ぶ。TA6）。
    at mid は、この印の在る周の p3.fix を「役が出した修正」と数えない"""
    b.trace(EMPTY_FIX_OP, node="p3.fix", by=EMPTY_FIX_BY, round=b.round)
