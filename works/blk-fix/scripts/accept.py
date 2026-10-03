# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の返答の受け付け（blk-fix の節 fix-accept）。確かめは返さずに表 CHECKS の id で積み（note）、最後に 1 回だけ拒む
（rejected。見出しごとに並べた本文 reason と行ごとの id の rejects）。下の段の「拒む」は積んで先へ進む意味。
積んだ行が在れば写しの照らし（3）も乾いた形（commit=False。盤面を書かない）で当てて並べる。順は
-3. TDD の輪で凍ったテストのファイル（下の 1b。id frozen）
-2. 書き込みの出どころ（check_writes。writes.check。id writes）: 版からの変更に、Edit・Write の
   書き込みの記録か返答の欄 bash_writes の申告が在るか。無ければ拒む。記録の無い run（包みが無い）は通し、受けた時に
   盤面の trace に 1 行。盤面に渡す返答からは（拒む時も）bash_writes を外す。
   実行器が作ったファイル（run の全部の輪の suite_made。tddloop.suite_made_all）は数えない。2 回目の修正の段では、1 回目に受け付けた
   返答の控えの bash_writes（conflict.held_writes）も申告に足す（1 回目の Bash の書き込みを 2 回目で拒まない）
-1. 食い違いの申し出（欄 conflicts。INPUTS_PASS が first か ruled。id conflict）: take_conflicts。積んだ誤りに依らず回す。
   名指しが現物に無ければ普通の拒否、在れば拒否に数えずその単位を止める。1 回目（first）で裁かれていない申し出が在れば、
   積んだ誤りが在っても盤面に渡さずに {ok: true, parked: true}（輪を抜け、裁定の輪 → 2 回目の修正役 fix-ruled が渡す。
   積んだ誤りはその受け付けがもう一度当てる）。ruled の新しい申し出は拒否の後も積んだまま残す。盤面に渡す返答からは
   conflicts を外す（写しの schema に無い欄）
0. 盤面が p3.fix を待っている（instance が待ち・起こした印が在る・依存が済んだ）ときだけ、返答の changes[].unit_key を盤面の
   控え（graph の pointers。mark_launched が固めた一覧）で名前に戻した列を作り、次の 2 つの works だけの検査に当てる。
   待っていない・番号を名前に戻せないときは検査せず 2 に進む（entry.take が回す側の誤り（2）か型・番号の文で拒む）
1. works だけの 2 つの検査（TA25 で .shared/core/accept.py には足さない。写しの fix_covers_open_units はどちらも見ない。
   1 本目は check_fix が fix_plan_covers_units に読み替えてどちらも拒んでいた。works は graphloops の上にこの拒否を残す）
   - check_unique_units: 同じ unit_key を 2 行に分けた返答を拒む
   - check_opened_units: 直す義務（conflict.fix_duty の owed。検証器の is_open の単位と、関所で答えた問いの出どころ・depends
     から、答え待ちの問いの出どころ・depends と直す裁定でない裁定（ask_human・fix_plan_item）を受けた単位を外した物）にも、そこから外れた単位にも無い unit_key を拒む
     （関所で答えていない defer の単位・判定に無い key。1 本目の unknown = got - opened）
   - check_excused_units: 直す義務から外れた単位（fix_duty の excused）の unit_key を、外れた理由（答え待ちの問いの key・
     直さない裁定の decision と id）を名指して拒む。輪の最後の回だけは、その単位の直しを作業ツリーから戻して changes から外し
     （drop_excused_units。控えの patch を盤面に置く）、残りの単位で受け付けを頭から通し直し、通れば trace に 1 行
     （EXCUSED_DROPPED_OP）。通らなければ戻した直しを元に戻す。止めてよくない確かめの行が既に積まれていれば戻さずに拒む
   - 裁定の後（INPUTS_PASS が ruled）は、凍ったテストの検査の次に revert_ruled_units: 1 回目に申し出を返した回の返答の控え
     （conflict.PARKED_REPLY）の行のうち、裁定が今は直す義務から外した単位（conflict.held_by_rulings。fix_plan_item が止めた同じ
     項目の単位）の直しを作業ツリーから戻し（drop_excused_units と同じ手）、控えからその行を外して、受け付けを頭から通し直す。
     通れば trace に 1 行（RULED_REVERTED_OP）、通らなければ戻した直しと控えを元に戻す（止めた単位の直しは changes から外した
     だけでは残らない。決まりは輪の最後の回と同じ）
1a. check_pack_copy: .archon/ の下（自分食いの run では動いている線の pack の写し）を申告した・変えた返答を拒む（run 26）
1b. TDD の輪で緑になった単位のテストのファイルを、輪の後の修正役が変えていないか（INPUTS_TDD_STATE。tddloop.frozen_problems。
   空・欠けは輪の無い run で見ない。check_frozen）。凍結は run の全部の輪で効く（盤面の tdd-<k>。tddloop.states）: 今の輪の状態は
   今どおり、前の輪（1 回目の修正の段の輪）の状態は今の輪の状態の handoff の木（since）からの変更で見て、直した項目の単位
   （conflict.amended_keys）の前の輪の受け入れのテストの関数（tddloop.test_spans）の中だけの変更は通す。前の輪の許しの行は
   since の木で引き直す（比べる木と行を引く木を揃える）。テストの変更の許し（承認済みの修正案の rewrite_tests と裁定 fix_test_scope の範囲。
   conflict.test_permits を conflict.ruled_test_limits が引く）の中の変更を通す。修正案の名指しは 1 回目から、今の輪の裁定の範囲は
   裁定の後（ruled）だけ（前の輪は前の段の裁定の範囲をいつも許す）。修正案の範囲は、凍結の検査が読む輪の後の木でテストの id から引き直す（tddloop.frozen_source）。
   輪が赤→緑を確かめた修正案の書き換え（tddloop.verified_rewrites）は許しから外す（skip_ids。輪の後に確かめなしで書き換えさせない）
1c. check_tests: 版からの変更に当たる試験を、TDD の輪と同じ実行器で機械が走らせ、元で赤でなかった試験の赤を拒む
   （tddloop.selected_problems。実行器の無い run は走らせない。一式の緑は線の最後のテストの段が確かめる）
1d. check_plan_scope: 承認済みの修正案の項目（planmarks.approved_items）と差分を照らす（planscope.check）。範囲（allowed_paths・
   out_of_scope・テストの許し）の外・adds の識別子が差分に無い・canonical の外の同名の定義・removes の識別子が残る・tests に
   無いテストを足した・tests のテストが無い、を拒む。欠けは版からの差分の全部で見て、修正役に問う外れと余分は TDD の輪が
   凍らせたファイルなら凍った後に変えた分だけで見る。
   単位の全部が直す義務から外れた項目（conflict.held_by_rulings。fix_plan_item ならその項目）は範囲を与えない。裁定の後
   （ruled）に範囲が広がるのは直す裁定の limits のパスだけで、裁定を受けた単位の全部を外さない。out_of_scope はテストの許しと
   裁定の limits にも勝つ（案が外したパスが要るのは案の項目の誤りで、fix_plan_item の道）。
   控えに範囲の欄が無い・修正案の無い run・平の run（修正の形 current）は回さない。受けた時に trace に 1 行（SCOPE_OP）
1e. 事後の関門の束（fixgates.problems。計画 220 Task 4）: 修正の形に依らず、base から今の木までを相手に、承認済みの修正案の
   受け入れのテストの赤→緑（INPUTS_TDD_SUITE の実行器。無い run は帳面に飛ばした理由だけ）と、名指しの外の既存のテストの
   本体の変更を確かめる。行が在れば行ごとの文（fixgates.reject_lines。" / " でつないで 1 つの理由に全部の行が並ぶ）で拒む
   （今の拒否の道。最後の回は文ごとに unit_key か名指しのファイルで単位に結べれば止める）。盤面に done を書く 3 の前に置く
   （拒否では盤面を前のままにする。束の帳面 fixgates.LEDGER と一式のログは残す）。受けた回に束が赤緑を確かめずに飛ばした
   理由（fixgates.unchecked。義務の外の項目を見なかった理由は除く）は盤面の trace の fixgates.SKIPPED_OP の行に載せる
   （報告と最後の人の関所の文が数える）。2 回目の修正の段は回の印（INPUTS_PASS_TAG）で帳面の回を分け、裁定の範囲は
   1 回目の段の物をいつも許す（fixgates.problems の tag）
2 の前. 2 回目の修正の段（1 回目に受け付けた返答の控えが在る）: 返答を名前に戻し、控えの行を単位で合わせる（conflict.with_held）。
   -3〜1e の検査は役の返答そのものに当て、合わせた返答を 2・2a・3 と盤面に渡す。2 回目の段の受け付けは控えの単位を changes か
   not_done に書いた返答を、直しを戻させない自分の文（ACCEPTED_ROWS。check_accepted_rows。id accepted）で拒み、輪の最後の回でもその直しを
   作業ツリーから戻さない。その単位の役の行は積んだ後に返答から外し（drop_accepted_rows）、後の確かめと合わせた返答の照らしに当てない。止める単位の直しを戻す時（drop_excused_units・park_bound_units）、控えの行のファイルを共にする単位は戻さない
2. unitrows.take: 閉鎖の数え直しの前段。判定者の class_query（replace_query の裁定を受けた単位は置き換えた問い）を修正前の版と
   修正後の作業ツリーで機械が数え、単位ごとの表（querytest.CLOSURE_FILE。最後の関所と報告が読む）に closed と、修正役の申告
   （closure.sites の path が覆う問いの当たりの件数・remaining・作り直した how）との食い違いを記録する。食い違いは拒否でなく記録で、写しに渡す返答は
   写しの数え合わせの拒否が発火しないように揃える
2a. 案の直しを待つ単位（conflict.waiting。裁定 fix_plan_item の WAITING の行）が在り、盤面が p3.fix を待っていれば（named_reply）、
   積んだ行が無く写しの照らしを乾いた形（3 の commit=False）で通る時だけ盤面に渡さずに控える（hold_fix。積んだ行か照らしの
   誤りが在れば控えずに並べて拒む。控えた返答を h-rejudge の hand_held が渡して拒まれ盤面が止まる前に役へ返す）: 盤面に渡す形の返答（番号は名前に戻す）に役が申告した bash_writes を残して
   conflict.HELD_REPLY に置き、受けた時と同じ trace（書き込みの出どころ・TESTS_OP・SCOPE_OP・fixgates.SKIPPED_OP・CLOSURE_OP）と HELD_OP を書いて
   {ok: true, done: true, parked: true, changes: 1 本目の行}。盤面へは h-rejudge の replan.settle（hand_held）が渡す
3. recount.accept_fix: 盤面の done("p3.fix")。写しの fix_covers_open_units が同じ問いで数え直す（仕様 3.2）。通れば 1 本目の
   出口のための changes（unit_key・files・what）を足し、表を盤面に置く
loop_group の外の節は中の節の出力を引けず、輪の出力は最後の周の末端（この節）の出力なので、受け付けた changes を
ここで出口へ運ぶ（collect が今の周の changes.json に書く）。拒んだときの changes は空。
中身の拒否は終了コード 0 の {"ok": false, "reason", "rejects", "reason_file", "changes": [], "done"} を 1 行。回す側の誤りは 2。
done は輪を抜ける旗（通った時か輪の 3 回目の拒否。R50: max_iterations に当てて run を落とさない）。3 回目は、積んだ行の確かめが
全部、表 CHECKS で止めてよい物（-3・-2・1b・1c・1d・1e・写しの受け付け）で、どの行も changes[].files か unit_key（写しの文の頭の
unit_key[:60] も）でちょうど 1 単位に結べれば、その単位の直しを戻して（控えの patch を盤面に置く）ask_human に止め、残りの単位で
受け付けを頭から通し直す（park_bound_units。fail-fast: false）。通し直しが通らなければ、止めた単位の直し・食い違いの控え・
裁定の文を止める前に戻す（拒否では盤面を前のままにする）。諦めるのは、どの単位にも結べない行か、止める単位のファイルをほかの
単位と共有する返答か、止めてよくない確かめ（申し出の形・1a・重なり・開いていない key・1 回目に受け付けた単位・直す義務から外れた単位）の行が 1 つでも
在る時（key の形の拒否は 3 回目でも単位に結んで止めない。開いた単位を 2 行に分けた返答も丸ごと諦め、並べた全部の行を返す）。
諦めた輪の後は assert-changed が盤面を止め、collect が ok: false の出口を出す
"""
import copy
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402
import posixpath  # noqa: E402
import re  # noqa: E402

import conflict  # noqa: E402   食い違いの申し出（.shared/core）
import fixgates  # noqa: E402   事後の関門の束（blk-fix/lib）
import fixrules  # noqa: E402   回の印の口 tagged（blk-fix/lib）
import impact  # noqa: E402   変更に当たる試験の選び（.shared/core）
import planbrief  # noqa: E402   今の周の brief の行（blk-fix/lib。申し出 brief_vs_judgment の確かめ）
import leftovers  # noqa: E402   .archon/ の決まりと修正役の前の控え（.shared/core）
import planscope  # noqa: E402   承認済みの修正案の項目と差分の照らし（blk-fix/lib）
import querytest  # noqa: E402   判定者の問いを例に当てる（.shared/core）
import recount  # noqa: E402
import tddloop  # noqa: E402
import unitrows  # noqa: E402   閉鎖の数え直しの前段（blk-fix/lib）
import entry  # noqa: E402
import writes  # noqa: E402   書き込みの出どころの突き合わせ（.shared/core）
from leftovers import git  # noqa: E402
from engine import pointers  # noqa: E402  （recount が import した board が写しの engine を sys.path に足す）

INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_TDD_STATE", "INPUTS_ITERATION", "INPUTS_PASS", "INPUTS_TDD_SUITE",
          "INPUTS_PASS_TAG")
# 無くても欠けに数えない入力（依頼 226 で後から足した回の印。前の版の with: で再開した run は渡さない。無い・空は今どおり）。
# 回の印（INPUTS_PASS_TAG）は申し出の回の控え・裁定の文・拒否の理由のファイルの名を分ける（fixrules.tagged）
OPTIONAL = frozenset({"INPUTS_PASS_TAG"})
GIVE_UP_AFTER = 3   # 輪 fix-loop の max_iterations と同じ（tests/test_blk_fix.py が YAML と突き合わせる）
TESTS_OP = impact.ACCEPT_TRACE_OP   # 受け付けが選んだ試験を走らせた盤面の trace の行（ci_left を最後の関所が読む）
PARK_UNDONE_OP = "fix_mismatch_park_undone"   # 最後の回に止めた単位を、返答が通らなかったので戻した盤面の trace の行
DUPLICATE = "同じ unit_key を 2 行以上に分けた（直した単位ごとにちょうど 1 行。1 つの単位が複数のファイルに及ぶなら files に並べよ）: "
NOT_OPENED = ("今の周に直す単位に無い unit_key を changes に書いた（開いた単位と、関所で答えた問いの出どころ・depends のほかは直さない。"
              "単位を切り直さず、貼られた単位の no か key で指せ。判定への異議は rejudge_requested に書く）: ")
EXCUSED = ("直す義務から外れた単位を changes に書いた（答えが届くまで・人が決めるまで直さない。changes から外し、作業ツリーの"
           "その単位の直しを戻し、not_done に理由を書け）: ")
ACCEPTED_ROWS = ("1 回目の修正の段で受け付けた単位を changes か not_done に書いた（その単位の行は機械が 1 回目の控えから足す。"
                 "changes からも not_done からも外せ。作業ツリーのその単位の直しはそのまま残せ）: ")
EXCUSED_DROPPED_OP = "fix_excused_dropped"   # 最後の回に、直す義務から外れた単位の直しを戻して changes から外した盤面の trace の行
RULED_REVERTED_OP = "fix_ruled_reverted"     # 裁定の後の受け付けで、控えの返答の行のうち裁定が止めた単位の直しを戻した盤面の trace の行
HELD_OP = "fix_held"   # 待つ単位が在る間、盤面に渡さずに返答を控えた（conflict.HELD_REPLY）盤面の trace の行


CONFLICT_BAD = "食い違いの申し出を受けない（名指した所が現物に無いか、形が違う。直して丸ごと出し直せ）: "
CLOSURE_OP = "fix_unit_rows"   # 受けた返答の単位ごとの閉鎖の表（querytest.CLOSURE_FILE）を置いた盤面の trace の行
BOUND_PARKED = ("修正の輪の最後の回も、この単位に結べる拒否（凍ったテストの書き換え・書き込みの出どころ・元で赤でなかった試験の赤・"
                "事後の関門の束の行・承認済みの修正案の項目からの外れ・写しの受け付けの拒否）が残った。返答全体を拒んで盤面を止める代わりに、"
                "機械がこの単位の直しを作業ツリーから戻して人に回し、ほかの単位の直しを受けた。拒否の文: ")
BOUND_PARKED_OP = "fix_bound_parked"   # 最後の回に単位に結べた拒否でその単位を止めた盤面の trace の行（止めた単位と控えの patch）
PARKED_PATCH = "fix-parked"            # 止めた単位の戻した直しの控え（盤面の今の周の fix-parked-<n>.patch）
SECOND_CONFLICT = ("裁定の後の出し直しで新しく申し出た食い違い——裁定の輪は 1 周に 1 回だけなので、機械が人に回した"
                   "（最後の人の関所で人が決める）")


PACK_COPY = ("修正役は .archon/ の下を変えてはいけない（Archon の置き場で、この run を動かしている線の写しが在りうる。"
             "写しは次の run が作り直す）: ")

# 修正の受け付けの確かめの id → (拒否の見出しの短い名, 最後の回に単位に結んで止めてよいか)。並びは受け付けが回す順。
# 拒否の見出しと確かめの id の表はここ 1 か所（role-rejects の行の id もここから引く。依頼 236）
CHECKS = {
    "frozen": ("TDD の輪で凍ったテストのファイル", True),
    "writes": ("書き込みの出どころ", True),
    "conflict": ("食い違いの申し出の形", False),
    "pack": (".archon/ の下の変更", False),
    "duplicate": ("同じ unit_key の重なり", False),
    "not_opened": ("今の周に直す単位に無い unit_key", False),
    "accepted": ("1 回目の修正の段で受け付けた単位の行", False),
    "excused": ("直す義務から外れた単位", False),
    "scope": ("承認済みの修正案の範囲", True),
    "tests": ("変更に当たる試験の赤", True),
    "gates": ("事後の関門の束", True),
    "copy": ("写しの受け付け（graph の p3.fix の型と規則）", True),
}
REJECT_HEAD = ("受け付けは確かめを全部回した。見出しごとに並べた行を全部直した返答を丸ごと出し直せ（直した所だけを返すな。"
               "1 回の出し直しで全部を直せ）:")


def note(found: list, check: str, texts) -> None:
    """found に (check, 文) を足す（texts は文の列か文 1 つ）。空の文は足さない。表 CHECKS に無い id は ValueError
    （配線の誤り。入口が 2 にする）"""
    if check not in CHECKS:
        raise ValueError(f"修正の受け付けの表 CHECKS に無い確かめの id: {check!r}")
    for text in [texts] if isinstance(texts, str) else texts:
        if text and text.strip():
            found.append((check, text))


def reject_rows(found: list) -> list:
    """found を表 CHECKS の順に並べ、同じ (id, 文) を 1 つにした列（確かめの中は積んだ順）"""
    seen = dict.fromkeys(found)
    return [row for check in CHECKS for row in seen if row[0] == check]


def render_rejects(found: list) -> str:
    """拒否の本文: REJECT_HEAD の後に、行の在る確かめごとに見出し `## <見出し>（確かめ <id>・<件数> 件）` と行 `  - <文>`。
    文の中の改行は次の行の頭に 4 字の空白を置いて続ける"""
    rows = reject_rows(found)
    lines = [REJECT_HEAD]
    for check, (head, _) in CHECKS.items():
        texts = [text for c, text in rows if c == check]
        if texts:
            lines.append(f"## {head}（確かめ {check}・{len(texts)} 件）")
            lines += ["  - " + text.replace("\n", "\n    ") for text in texts]
    return "\n".join(lines)


def rejected(found: list) -> dict:
    """拒否の出力。rejects は本文の `  - ` の行と同じ数・同じ順で、行ごとの確かめの id と文"""
    return {"ok": False, "reason": render_rejects(found),
            "rejects": [{"check": c, "text": t} for c, t in reject_rows(found)], "changes": []}


def check_pack_copy(reply: dict, board: Path, repo: Path) -> str:
    """.archon/ の下（leftovers.ARCHON_PREFIX）を changes[].files に申告した・修正役の前の控え（節 ignored-before）から
    .archon/ の下の中身が変わった返答を拒む文（通れば空）。控えが無いのは回す側の誤り（Unreadable → 2）"""
    declared = set()
    for c in reply.get("changes") or []:
        for f in (c.get("files") if isinstance(c, dict) else None) or []:
            if not isinstance(f, str) or not f.strip():
                continue
            f = f.strip()
            if os.path.isabs(f):
                f = os.path.relpath(f, repo)
            f = posixpath.normpath(f)
            if f == leftovers.ARCHON_PREFIX.rstrip("/") or f.startswith(leftovers.ARCHON_PREFIX):
                declared.add(f)
    changed = leftovers.archon_changes(board, repo, fixrules.tagged(leftovers.IGNORED_BEFORE_FILE, _tag()))
    parts = []
    if declared:
        parts.append(f"changes[].files に申告した {sorted(declared)}（申告から外す）")
    if changed:
        parts.append(f"修正役の前の控え（節 ignored-before）から変わった {changed[:20]}（.archon/ の下は元の姿に戻してから"
                     "出し直す: 追跡している物は git checkout -- <パス>、足した物は消す）")
    return PACK_COPY + " / ".join(parts) if parts else ""


def named_reply(reply: dict, board: Path):
    """盤面が p3.fix を待っていれば、返答の番号（changes・not_done の unit_key と plan_faces の key）を盤面の控えで名前に戻した写し
    （resolved_changes と同じ engine の pointers.resolve の 1 本）。待っていない・番号を名前に戻せないときは None（盤面に渡して
    盤面に拒ませる）"""
    b = entry.open_board(board)
    inst = b.rd["instances"].get(recount.FIX_NODE)
    if not inst or inst["status"] != "pending" or not inst.get("launched_at") or not b.deps_met(recount.FIX_NODE):
        return None
    out = copy.deepcopy(reply)
    if pointers.resolve(out, b.nodes[recount.FIX_NODE].get("pointers"), inst.get("pointers")):
        return None
    return out


def resolved_changes(reply: dict, board: Path):
    """盤面が p3.fix を待っていれば、changes の行（番号の unit_key を盤面の控えで名前に戻した写し）。待っていない・changes の形が
    崩れている・番号を名前に戻せないときは None。番号を名前に戻す仕事は engine の pointers.resolve の 1 本で、ここに別の戻しを書かない"""
    rows = reply.get("changes") if isinstance(reply, dict) else None
    if not isinstance(rows, list) or not all(isinstance(c, dict) for c in rows):
        return None
    out = named_reply({"changes": rows}, board)
    return None if out is None else out["changes"]


def fix_unit_keys(reply: dict, board: Path):
    """盤面が p3.fix を待っていれば (changes[].unit_key を名前に戻した列（changes と同じ順）, 直す義務の key の集合,
    直す義務から外れた単位 {key: 理由})（conflict.fix_duty）。待っていない・changes の形が崩れている・番号を名前に戻せない
    ときは None（検査せず entry.take に任せる）"""
    rows = resolved_changes(reply, board)
    if rows is None:
        return None
    keys = [c.get("unit_key") for c in rows]
    if not all(isinstance(k, str) for k in keys):
        return None
    return (keys, *conflict.fix_duty(entry.open_board(board)))


def check_unique_units(keys: list) -> list:
    """2 度以上現れる unit_key（現れた順）"""
    seen, dup = set(), []
    for k in keys:
        if k in seen and k not in dup:
            dup.append(k)
        seen.add(k)
    return dup


def check_opened_units(keys: list, opened: set) -> list:
    """直す義務にもそこから外れた単位にも無い unit_key（現れた順・重なりは 1 つ）"""
    return list(dict.fromkeys(k for k in keys if k not in opened))


def check_accepted_rows(reply: dict, board) -> list:
    """2 回目の修正の段: 1 回目に受け付けた返答の控えの単位（conflict.accepted_units）を changes か not_done に書いた unit_key
    （名前に戻して見る。現れた順・重なりは 1 つ）。控えが無ければ空。合わせる（conflict.with_held）前に見る——合わせると控えの
    行が役の行に負けて落ちる"""
    kept = conflict.accepted_units(entry.open_board(board))
    if not kept:
        return []
    named = named_reply(reply, board) or reply
    keys = [r.get("unit_key") for f in ("changes", "not_done") for r in named.get(f) or [] if isinstance(r, dict)]
    return [k for k in dict.fromkeys(keys) if k in kept]


def drop_accepted_rows(reply: dict, keys: list, mine: list, board) -> tuple:
    """2 回目の修正の段: 1 回目に受け付けた単位（mine。check_accepted_rows）の役の行を changes と not_done から外した返答と、
    changes と同じ順の名前の keys。その単位の拒否は accepted の行だけに並べ、後の確かめ（外れた単位・範囲）と、控えの行を
    合わせた（conflict.with_held）写しの照らしに役の行を当てない。not_done は check_accepted_rows と同じく名前に戻して見る"""
    out = {**reply, "changes": [c for c, k in zip(reply.get("changes") or [], keys) if k not in mine]}
    if isinstance(reply.get("not_done"), list):
        named = (named_reply(reply, board) or reply).get("not_done") or []
        out["not_done"] = [r for r, n in zip(reply["not_done"], named)
                           if not (isinstance(n, dict) and n.get("unit_key") in mine)]
    return out, [k for k in keys if k not in mine]


def check_excused_units(keys: list, owed: set, excused: dict) -> dict:
    """直す義務から外れた単位の unit_key と理由 {key: 理由}（現れた順）"""
    return {k: excused[k] for k in keys if k not in owed and k in excused}


def _reject(reason: str) -> dict:
    return {"ok": False, "reason": reason, "changes": []}


def _tag() -> str:
    """修正の段の回の印（INPUTS_PASS_TAG。無い・空は 1 回目の段）"""
    return os.environ.get("INPUTS_PASS_TAG", "")


def take_conflicts(reply: dict, board: Path, repo: Path, pass_: str):
    """食い違いの申し出（欄 conflicts）を外した返答と、拒否の文か止めた印。返り (返答, 結果 | None)。結果が None なら受け付けを続ける。
    - 申し出が在れば機械が確かめる（conflict.problems: 形・今の直す義務の単位か・名指した所が現物に在るか・kind brief_vs_judgment
      ならその単位の今の周の brief の行を名指すか（planbrief.by_unit_at））。外れれば普通の拒否
    - first: 通った申し出を盤面の控えに積み（拒否に数えない）、裁かれていない申し出が在れば（TDD の輪の分も）盤面に渡さずに
      {ok: true, parked: true, changes: []}（裁定の輪の後、2 回目の修正役が渡す）。返答は盤面の置き場に控える（PARKED_REPLY。
      名は回の印で分ける）
    - ruled: 裁定の後の新しい申し出は、裁定の輪がもう無いので機械が ask_human に裁いて積む（その単位を直した返答は
      check_excused_units が拒む）"""
    reply = dict(reply)
    items = reply.pop("conflicts", None) or []
    b = entry.open_board(board)
    owed = conflict.owed_units_but_asked(b)
    if items:
        bad = conflict.problems(items, repo=repo, board_dir=board, owed=owed, try_query=querytest.judge_hits(b.record["units"]),
                                briefs=planbrief.by_unit_at(board))
        both = sorted({i.get("unit_key") for i in items if isinstance(i, dict)}
                      & {c.get("unit_key") for c in reply.get("changes") or [] if isinstance(c, dict)})
        if both:
            bad.append(f"申し出た単位を changes にも書いた: {both}（申し出た単位は直さない）")
        if bad:
            return reply, _reject(CONFLICT_BAD + " / ".join(bad))
        if pass_ == "first":
            conflict.park(b, items, source="fix")
        else:
            conflict.park(b, items, source="fix", ruling={"decision": conflict.ASK, "text": SECOND_CONFLICT, "limits": [],
                                                          "by": "works:fix-accept"})
            conflict.write_rulings(b)
    if pass_ == "first" and conflict.unruled(b):
        _put_parked(b.work(fixrules.tagged(conflict.PARKED_REPLY, _tag())), {**reply, "conflicts": items})
        return reply, {"ok": True, "parked": True, "reason": "", "changes": []}
    return reply, None


def _put_parked(path: Path, reply: dict) -> None:
    """控えの返答（conflict.PARKED_REPLY・HELD_REPLY）を書く（一時のファイルから置き換える）"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(reply, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def check_writes(reply: dict, board: Path, base_rev: str, repo: Path, state: str) -> dict:
    """書き込みの出どころ（writes.check。欄 bash_writes を外した返答は reply に）。実行器が作ったファイルは run の全部の輪の物を
    外す（tddloop.suite_made_all）。1 回目に受け付けた返答の控えの bash_writes（conflict.held_writes）を役の申告に足す（役の欄の
    形が崩れていれば足さずに形の拒否に任せる）。盤面は書かない（申告の記録は writes.check が足す）"""
    made = set(tddloop.suite_made(state)) | tddloop.suite_made_all(board)
    b = entry.open_board(board)
    rev = writes.base_rev(b, base_rev)
    held, own = conflict.held_writes(b), reply.get(writes.FIELD)
    if held and (own is None or isinstance(own, list)):
        reply = {**reply, writes.FIELD: [*(own or []), *(w for w in held if w not in (own or []))]}
    return writes.check(reply, repo, [p for p in writes.changed(repo, rev) if p not in made], writes.sink(repo))


def _loop_states(board, state) -> list:
    """run の全部の輪の状態のファイル（盤面の tdd-<k> の番号の順。今の輪 state は最後。無ければ空）"""
    if not state:
        return tddloop.states(board)
    return [p for p in tddloop.states(board) if p.resolve() != Path(state).resolve()] + [state]


def check_frozen(board: Path, state: str, repo: Path, pass_: str) -> list:
    """手順 1b: 凍ったテストのファイル（tddloop.frozen_problems）を run の全部の輪で見た拒否の文。今の輪（state）は今どおり、前の輪
    （1 回目の修正の段の輪）は今の輪の状態の handoff の木（since）からの変更で見て、直した項目の単位（conflict.amended_keys）の前の
    輪の受け入れのテストの関数（tddloop.test_spans）の中の変更は通す。テストの変更の許し（conflict.ruled_test_limits）は輪ごとに、
    凍結の検査が比べる木で修正案の行を引き直す（今の輪は輪の後の木、前の輪は since の木。tddloop.frozen_source）。輪が赤→緑を
    確かめた書き換えは、どの輪の物でも許しから外す。今の輪が無い（2 回目の段の輪が走らなかった）時、前の輪は輪の後の木で見る。
    裁定の範囲は今の輪だけ pass_ で決め（1 回目の受け付けは含めない）、前の輪はいつも含める（前の段で裁いた fix_test_scope の
    直しは、今の段の受け付けが first でも許し）。輪が 1 つも無ければ空。盤面は書かない"""
    loops = _loop_states(board, state)
    if not loops:
        return []
    b = entry.open_board(board)
    skip = [i for p in loops for i in tddloop.verified_rewrites(p)]

    def allowed(source, rulings):
        return conflict.ruled_test_limits(b, rulings=rulings, source=source, skip_ids=skip)
    out = tddloop.frozen_problems(state, repo, allowed(tddloop.frozen_source(state, repo), pass_ == "ruled")) if state else []
    old = loops[:-1] if state else loops
    if old:
        since = tddloop.load_state(state).get("handoff") if state else None
        amended = conflict.amended_keys(b)
        for p in old:
            out += tddloop.frozen_problems(p, repo, allowed(tddloop.frozen_source(p, repo, since=since), True), since=since,
                                           skip_spans=tddloop.test_spans(p, amended))
    return out


def _loop_freeze(board, state) -> tuple:
    """(一番後の輪の frozen_tree, run の全部の輪が凍らせたファイル)。輪が無ければ (None, [])"""
    tree, files = None, set()
    for p in _loop_states(board, state):
        st = tddloop.load_state(p)
        files |= set(st.get("frozen") or {})
        tree = st.get("frozen_tree") or tree
    return tree, sorted(files)


def check_tests(board: Path, base_rev: str, repo: Path, state: str) -> tuple:
    """版からの変更に当たる試験を機械が走らせた赤（tddloop.selected_problems）。返り (赤の文, 知らせ)。盤面は書かない"""
    return tddloop.selected_problems(state, repo, writes.base_rev(entry.open_board(board), base_rev))


def check_plan_scope(reply: dict, keys: list, board: Path, base_rev: str, repo: Path, state: str, pass_: str) -> tuple:
    """承認済みの修正案の項目と差分の照らし（planscope.check）。行は changes と keys（単位の名前）を並べ、files を根からの相対に
    揃えた物。変わったパスは版からの変更（writes.changed）から実行器が作ったファイル（tddloop.suite_made）を除いた物。TDD の輪が
    凍らせたファイル（輪の状態の frozen と frozen_tree。revert_units と同じ読み口）は planscope.check に渡し、欠けは版からの
    差分の全部で、修正役に問う外れと余分は凍った後に変えた分だけで見させる。
    返り (拒否の行（最初の行の頭に planscope.REJECT）, 記録)。盤面は書かない（控えの食い違いで止めるのは planscope.check）。
    凍らせたファイルと実行器が作ったファイルは run の全部の輪の物（_loop_freeze・tddloop.suite_made_all）で、凍った後は一番後の
    輪の frozen_tree から見る（前の輪の後に 1 回目の段と後の輪が書いた物を、2 回目の修正役のせいにしない）"""
    b = entry.open_board(board)
    rows = [{"unit_key": k, "files": sorted(_files([c], repo))} for c, k in zip(reply.get("changes") or [], keys)]
    tree, frozen = _loop_freeze(board, state)
    made = set(tddloop.suite_made(state)) | tddloop.suite_made_all(board)
    rev = writes.base_rev(b, base_rev)
    paths = [p for p in writes.changed(repo, rev) if p not in made]
    problems, note = planscope.check(rows, b, repo, rev, paths, pass_=pass_, loop_tree=tree, frozen=frozen)
    if problems:
        problems = [planscope.REJECT + problems[0], *problems[1:]]
    return problems, note


def _files(rows, repo) -> set:
    """changes の行の files を、リポジトリの根からの相対パスに揃えた集合"""
    out = set()
    for c in rows:
        for f in c.get("files") or []:
            if isinstance(f, str) and f.strip():
                f = f.strip()
                out.add(posixpath.normpath(os.path.relpath(f, repo) if os.path.isabs(f) else f))
    return out


def bind_problems(problems: list, rows: list, repo) -> tuple:
    """拒否の文を単位に結ぶ: 文が名指す unit_key（写しの受け付けが文の頭に置く unit_key[:60] も）か、それが無ければパス
    （changes[].files。前後がパスの字でない所）が、ちょうど 1 つの単位に当たれば結べた。unit_key を先に見るのは、key の頭の
    パスがほかの単位の files にも在りうるから。返り ({unit_key: [文]}, [どの単位にも結べない文])"""
    bound, unbound = {}, []
    for text in problems:
        hit = [c.get("unit_key") for c in rows
               if isinstance(c.get("unit_key"), str) and (c["unit_key"] in text or c["unit_key"][:60] in text)]
        if not hit:
            hit = [c.get("unit_key") for c in rows
                   if any(re.search(rf"(?<![\w./-]){re.escape(f)}(?![\w/-])", text) for f in _files([c], repo))]
        if len(set(hit)) == 1 and isinstance(hit[0], str):
            bound.setdefault(hit[0], []).append(text)
        else:
            unbound.append(text)
    return bound, unbound


def revert_units(board, base_rev, repo, state, rows) -> str:
    """止めた単位（rows）の直しを作業ツリーから戻す。先に、その単位のファイルの版からの差分（未追跡の新しいファイルも。一時の
    index で固めた木と比べる）を盤面の fix-parked-<n>.patch に控える。戻す先は、TDD の輪が凍らせたファイルは凍った時の木
    （輪が作って緑にしたテストを消さない。run の全部の輪のうち、そのファイルを凍らせた一番後の輪の木）、ほかは修正前の版。
    返りは控えのパス"""
    b = entry.open_board(board, allow_halted=True)
    rev = writes.base_rev(b, base_rev)
    files = sorted(_files(rows, repo))
    now = tddloop.snapshot(repo)
    n = 1
    while b.work(f"{PARKED_PATCH}-{n}.patch").exists():
        n += 1
    patch = b.work(f"{PARKED_PATCH}-{n}.patch")
    patch.write_bytes(git(repo, "diff", "--binary", "--no-renames", f"{rev}^{{tree}}", now, "--", *files, text=False))
    trees = {}   # 凍ったファイル → 凍らせた一番後の輪の木
    for p in _loop_states(board, state):
        st = tddloop.load_state(p)
        if st.get("frozen_tree"):
            trees.update({f: st["frozen_tree"] for f in st.get("frozen") or {}})
    for tree in dict.fromkeys(trees.values()):
        tddloop.restore_paths(repo, tree, [f for f in files if trees.get(f) == tree])
    tddloop.restore_paths(repo, f"{rev}^{{tree}}", [f for f in files if f not in trees])
    return str(patch)


def unrevert_units(board, base_rev, repo, patch: str, rows) -> None:
    """revert_units の取り消し: その単位のファイルを修正前の版に揃えてから控えの patch を当て、戻す前の姿にする"""
    rev = writes.base_rev(entry.open_board(board, allow_halted=True), base_rev)
    tddloop.restore_paths(repo, f"{rev}^{{tree}}", sorted(_files(rows, repo)))
    if Path(patch).stat().st_size:
        git(repo, "apply", "--binary", "--whitespace=nowarn", patch)


def _without_rows(reply: dict, rest: list, mine: set, repo) -> dict:
    """changes を rest にし、外した行のファイル（mine）の bash_writes の申告も外した返答"""
    out = {**reply, "changes": rest}
    if isinstance(reply.get(writes.FIELD), list):
        out[writes.FIELD] = [w for w in reply[writes.FIELD]
                             if not (isinstance(w, dict) and _files([{"files": [w.get("path")]}], repo) & mine)]
    return out


def _held_files(board, repo) -> set:
    """1 回目に受け付けた返答の控え（conflict.held_reply）の changes の行のファイル（控えが無ければ空）。2 回目の修正の段で止める
    単位の直しを戻す時、控えの単位の直しを巻き添えに戻さない"""
    held, _ = conflict.held_reply(entry.open_board(board, allow_halted=True))
    return _files([c for c in (held or {}).get("changes") or [] if isinstance(c, dict)], repo)


def drop_excused_units(reply: dict, keys: list, held: dict, board, base_rev, repo, state):
    """輪の最後の回: 直す義務から外れた単位（held。keys は changes と同じ順の名前）の行の直しを戻し（revert_units）、その行を
    外した返答・控えの patch・戻す手（undo: 直しを元に戻して控えを消す）を返す。外す行のファイルをほかの行か、1 回目に受け付けた
    返答の控えの行（_held_files）と共有していれば None（返答全体を拒む）"""
    rows = reply.get("changes") or []
    gone = [c for c, k in zip(rows, keys) if k in held]
    rest = [c for c, k in zip(rows, keys) if k not in held]
    mine = _files(gone, repo)
    if mine & (_files(rest, repo) | _held_files(board, repo)):
        return None
    patch = revert_units(board, base_rev, repo, state, gone)

    def undo():
        unrevert_units(board, base_rev, repo, patch, gone)
        Path(patch).unlink(missing_ok=True)
    return _without_rows(reply, rest, mine, repo), patch, undo


def revert_ruled_units(reply: dict, board, base_rev, repo, state):
    """裁定の後の受け付け（pass ruled）: 控えの返答（conflict.PARKED_REPLY。1 回目に申し出を返した回の返答）の行のうち、裁定が
    今は直す義務から外した単位（conflict.held_by_rulings。申し出の単位は控えの changes に無いので、fix_plan_item が止めた同じ
    項目の単位）の直しを作業ツリーから戻し（drop_excused_units）、控えからその行を外す。返りは (戻した単位 {key: 理由}, 控えの
    patch, 戻す手（直しと控えを元に戻す）) か None（控えが無い・戻す行が無い・戻すファイルを控えのほかの行か今の返答の行と
    共有する）"""
    b = entry.open_board(board)
    path = b.work(fixrules.tagged(conflict.PARKED_REPLY, _tag()))
    try:
        parked = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    got = fix_unit_keys(parked, board)
    if got is None:
        return None
    keys = got[0]
    ruled = conflict.held_by_rulings(b)
    held = {k: ruled[k] for k in keys if k in ruled}
    now = [c for c in reply.get("changes") or [] if isinstance(c, dict)] if isinstance(reply, dict) else []
    if not held or _files([c for c, k in zip(parked["changes"], keys) if k in held], repo) & _files(now, repo):
        return None
    dropped = drop_excused_units(parked, keys, held, board, base_rev, repo, state)
    if dropped is None:
        return None
    rest, patch, undo_tree = dropped
    saved = path.read_bytes()
    _put_parked(path, rest)

    def undo():
        undo_tree()
        path.write_bytes(saved)
    return held, patch, undo


def park_bound_units(reply: dict, problems: list, board, base_rev, repo, state):
    """輪の最後の回の拒否: 文が全部どれかの単位に結べ、止める単位のファイルをほかの単位と共有していなければ、その単位の直しを
    戻して（revert_units）ask_human に裁いて止め（conflict.park）、その行（と bash_writes の申告）を外した返答と、止める前に
    戻す手（undo: 直し・食い違いの控え・裁定の文を戻し、trace に PARK_UNDONE_OP）を返す。結べない文が在る・共有のファイルが
    在る（1 回目に受け付けた返答の控えの行のファイルも。_held_files）時は None（今までどおり返答全体を拒む）"""
    named = resolved_changes(reply, board)   # 拒否の行は名前の unit_key[:60] を頭に持つので、番号で答えた行も名前に戻して結ぶ
    rows = named if named is not None else [c for c in reply.get("changes") or [] if isinstance(c, dict)]
    bound, unbound = bind_problems(problems, rows, repo)
    if unbound or not bound:
        return None
    parked = [c for c in rows if c.get("unit_key") in bound]
    rest = [c for c in rows if c.get("unit_key") not in bound]
    mine = _files(parked, repo)
    if mine & (_files(rest, repo) | _held_files(board, repo)):
        return None
    b = entry.open_board(board)
    rulings = b.work(fixrules.tagged(conflict.RULINGS_FILE, _tag()))
    saved = {p: p.read_bytes() if p.is_file() else None for p in (b.work(conflict.FILE), rulings)}
    patch = revert_units(board, base_rev, repo, state, parked)
    for key in bound:
        why = " / ".join(bound[key])
        conflict.park(b, [{"unit_key": key, "between": [], "why_both_cannot_hold": why, "which_is_right": conflict.UNKNOWN,
                           "kind": conflict.NEEDS_CONTEXT}],
                      source="fix", ruling={"decision": conflict.ASK, "text": f"{BOUND_PARKED}{why}（戻した直しの控え {patch}）",
                                            "limits": [], "by": "works:fix-accept"})
    conflict.write_rulings(b)
    b.trace(BOUND_PARKED_OP, node=recount.ROLE, unit_keys=list(bound), patch=patch)
    out = _without_rows(reply, rest, mine, repo)

    def undo():
        unrevert_units(board, base_rev, repo, patch, parked)
        for p, body in saved.items():
            if body is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(body)
        b.trace(PARK_UNDONE_OP, node=recount.ROLE, unit_keys=list(bound))
    return out, undo


def hold_fix(named: dict, whole: dict, b, traced) -> dict:
    """待つ単位（conflict.waiting）が在る間の受け付け: 盤面に渡す形の返答（named。番号は名前に戻した）に、役が申告した
    bash_writes（whole の欄。前の控えの申告 conflict.held_writes を先に）を残して 1 回目に受け付けた返答の控え
    （conflict.HELD_REPLY）に置き、受けた時と同じ trace（traced）と HELD_OP を書く。盤面には渡さない（h-rejudge の replan.settle が渡す）。返りは輪を抜ける {ok, done, parked}"""
    held = dict(named)
    own = whole.get(writes.FIELD) if isinstance(whole, dict) else None
    prior = conflict.held_writes(b)   # 2 回目の段がまた控える時（同じ単位が再び fix_plan_item）、1 回目の申告を落とさない
    if isinstance(own, list) or prior:
        own = own if isinstance(own, list) else []
        held[writes.FIELD] = [*prior, *(w for w in own if w not in prior)]
    path = b.work(conflict.HELD_REPLY)
    _put_parked(path, held)
    changes = recount.v1_changes(named.get("changes") or [])
    traced().trace(HELD_OP, node=recount.ROLE, file=str(path), unit_keys=[c["unit_key"] for c in changes])
    return {"ok": True, "done": True, "parked": True, "reason": "", "reason_file": "", "changes": changes}


def accept_fix(reply, board, base_rev, repo):
    state = os.environ.get("INPUTS_TDD_STATE", "")
    pass_ = os.environ.get("INPUTS_PASS") or "first"
    attempt = int(os.environ.get("INPUTS_ITERATION") or 0)
    last = attempt >= GIVE_UP_AFTER
    whole = reply
    scope_note = None   # 承認済みの修正案の項目と差分を照らした記録（受けた時に trace へ）

    found = []   # 積んだ拒否の行 (確かめの id, 文)。申し出より後の確かめは返さずにここへ積み、最後に 1 回だけ拒む

    def parkable():
        """輪の最後の回で、積んだ行の確かめが全部止めてよい物（表 CHECKS）か（単位を止める・外して通し直してよいか）"""
        return last and isinstance(whole, dict) and all(CHECKS[c][1] for c, _ in found)

    def refuse():
        """積んだ行で拒む。parkable なら、単位に結べる行の単位だけを止めて残りで受け付けを通し直し、通らなければ止めた
        単位を戻す（fail-fast: false）"""
        if parkable():
            got = park_bound_units(whole, [t for _, t in reject_rows(found)], board, base_rev, repo, state)
            if got is not None:
                rest, undo = got
                out = accept_fix(rest, board, base_rev, repo)
                if out.get("ok") is not True:
                    undo()
                return out
        return rejected(found)

    note(found, "frozen", check_frozen(board, state, repo, pass_))
    got = revert_ruled_units(whole, board, base_rev, repo, state) if pass_ == "ruled" else None
    if got is not None:   # 控えから行を外したので、通し直しの中ではもう当たらない（積んだ凍結の行は通し直しがもう一度当てる）
        held, patch, undo = got
        out = accept_fix(whole, board, base_rev, repo)
        if out.get("ok") is True:
            entry.open_board(board, allow_halted=True).trace(RULED_REVERTED_OP, node=recount.ROLE, excused=held, patch=patch)
        else:
            undo()
        return out
    wrote = check_writes(reply, board, base_rev, repo, state)
    note(found, "writes", wrote["problems"])
    reply = wrote["reply"]   # 誤りが在っても bash_writes を外した返答（後の確かめはこれを使う）
    # 申し出は積んだ誤りに依らず確かめて積む（裁定へ渡す。ruled の新しい申し出は ask_human の裁定つきで拒否の後も残る）
    reply, done = take_conflicts(reply, board, repo, pass_)
    if done is not None:
        if done.get("ok") is not False:   # 1 回目に裁かれていない申し出を止めた出口（積んだ誤りが在っても返す）
            return done
        note(found, "conflict", [done["reason"]])
    got = fix_unit_keys(reply, board)
    if got is not None:
        note(found, "pack", check_pack_copy(reply, board, repo))
        keys, owed, excused = got
        # key の形の行は単位に結んで止めない（開いていない単位を ask_human に積まない。表 CHECKS で止めてよくない物）
        note(found, "duplicate", [DUPLICATE + k for k in check_unique_units(keys)])
        note(found, "not_opened", [NOT_OPENED + k for k in check_opened_units(keys, owed | set(excused))])
        # 1 回目に受け付けた単位の直しは戻させない（並べるだけで、最後の回も止めない）。その単位の役の行は外して後へ渡す
        mine = check_accepted_rows(reply, board)
        note(found, "accepted", [ACCEPTED_ROWS + k for k in mine])
        if mine:
            reply, keys = drop_accepted_rows(reply, keys, mine, board)
        held = check_excused_units(keys, owed, excused)
        if held:
            # 止めてよくない行が既に在れば外さない（通し直しても同じ行で拒むので、直しを戻さずに並べる）
            got = drop_excused_units(whole, keys, held, board, base_rev, repo, state) if parkable() else None
            if got is None:
                note(found, "excused", [f"{EXCUSED}{k}（{why}）" for k, why in held.items()])
            else:   # 通し直しの結果をそのまま返す（ここまでに積んだ行は通し直しがもう一度当てる）
                rest, patch, undo = got
                out = accept_fix(rest, board, base_rev, repo)
                if out.get("ok") is True:
                    entry.open_board(board, allow_halted=True).trace(EXCUSED_DROPPED_OP, node=recount.ROLE, excused=held,
                                                                      patch=patch)
                else:
                    undo()
                return out
        scope, scope_note = check_plan_scope(reply, keys, board, base_rev, repo, state, pass_)
        note(found, "scope", scope)
    red, tests_note = check_tests(board, base_rev, repo, state)
    note(found, "tests", red)
    gates = fixgates.problems(board, repo, base_rev, os.environ.get("INPUTS_TDD_SUITE", ""), attempt, pass_=pass_, tag=_tag())
    note(found, "gates", fixgates.reject_lines(gates) if gates else [])
    b = entry.open_board(board)
    if conflict.held_reply(b)[0] is not None:   # 2 回目の修正の段: 名前に戻して 1 回目の控えの行を合わせる（検査は済んだ役の返答に当てた）
        named = named_reply(reply, board)
        reply = conflict.with_held(b, named if named is not None else reply)
    reply, rows = unitrows.take(reply, b, repo)

    def traced():   # 受けた時だけ盤面の trace と表に積む（拒否・回す側の誤りでは盤面を前のままにする）
        tb = entry.open_board(board, allow_halted=True)
        writes.trace(tb, recount.ROLE, wrote)
        tb.trace(TESTS_OP, node=recount.ROLE, note=tests_note, ci_left=tddloop.ci_left(state))
        if scope_note is not None:
            tb.trace(planscope.SCOPE_OP, node=recount.ROLE, **scope_note)
        gaps = fixgates.unchecked(board, pass_=pass_, attempt=attempt, tag=_tag())
        if gaps:   # 束が赤緑を確かめずに受けた回（拒まないが、報告で見えるように）
            tb.trace(fixgates.SKIPPED_OP, node=recount.ROLE, why=gaps)
        if rows:
            tb.trace(CLOSURE_OP, node=recount.ROLE, file=str(querytest.save_closure(tb, rows)))
        return tb

    # 待つ単位が在れば控える返答（named）。積んだ行が在るか控える時は、写しの照らしを乾いた形（commit=False。盤面を書かない）で
    # 当ててその誤りも並べる（控えた返答を h-rejudge の hand_held が渡して拒まれ盤面が止まる前に、役へ返す）。
    # どちらでもなければ盤面に done("p3.fix") を書く（事後の関門の束の後。preflight F12）
    named = named_reply(reply, board) if conflict.waiting(b) else None
    out = recount.accept_fix(reply, board, base_rev, repo, commit=not found and named is None)
    if out.get("ok") is not True:
        note(found, "copy", out.get("problems") or [str(out.get("reason") or "")])
    if found:
        return refuse()
    if out.get("ok") is not True:   # 文の無い拒否（積む行が無い）はそのまま返す
        return out
    if named is not None:
        return hold_fix(named, whole, b, traced)
    traced()
    return out


def with_done(out: dict) -> dict:
    """輪を抜ける旗 done（R50）: 通った時か、この周の輪の 3 回目（fix-prep の iteration。INPUTS_ITERATION）の拒否。
    iteration が数でなければ ValueError（回す側の誤り。main_accept が 2 にする）"""
    it = int(os.environ["INPUTS_ITERATION"])
    return {**out, "done": out.get("ok") is True or it >= GIVE_UP_AFTER}


if __name__ == "__main__":
    sys.exit(recount.main_accept(accept_fix, finish=with_done))
