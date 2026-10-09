# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の返答の受け付け（blk-fix の節 fix-accept）。確かめは返さずに表 CHECKS の id で積み（note）、最後に 1 回だけ拒む
（rejected。見出しごとに並べた本文 reason と行ごとの id の rejects）。下の段の「拒む」は積んで先へ進む意味。
積んだ行が在れば写しの照らし（3）も乾いた形（commit=False。盤面を書かない）で当てて並べる。
範囲の相談の周（確かめの節の consulted。INPUTS_CONSULTED が true）は回さない: 返答も盤面も見ずに {ok: false, done: false,
consulted: true} を出す（拒否の理由のファイルも最後の結果の控えも書かない。次の周の修正役が答えを読んで続けた返答を受ける）。順は
-4. 範囲の相談の枠（id consult）: 相談の周でないのに返答が consult を持つのは枠（consult.BUDGET）を使い切った後の頼みで、拒む
   （欄を外して後の確かめに当てる）
-3. TDD の輪で凍ったテストのファイル（下の 1b。id frozen）
-2. 書き込みの出どころ（check_writes。writes.check。id writes）: 版からの変更に、Edit・Write の
   書き込みの記録か返答の欄 bash_writes の申告が在るか。無ければ拒む。記録の無い run（包みが無い）は通し、受けた時に
   盤面の trace に 1 行。盤面に渡す返答からは（拒む時も）bash_writes を外す。
   実行器が作ったファイル（run の全部の輪の suite_made。tddloop.suite_made_all）は数えない。2 回目の修正の段では、1 回目に受け付けた
   返答の控えの bash_writes（conflict.held_writes）も申告に足す（1 回目の Bash の書き込みを 2 回目で拒まない）
-1. 食い違いの申し出（欄 conflicts。INPUTS_PASS が first か ruled。id conflict）: take_conflicts。積んだ誤りに依らず回す。
   名指しが現物に無ければ普通の拒否、在れば拒否に数えずその単位を止める。1 回目（first）で裁かれていない申し出が在れば、
   積んだ誤りが在っても盤面に渡さずに {ok: true, parked: true}（輪を抜け、裁定の輪 → 2 回目の修正役 fix-ruled が渡す。
   積んだ誤りはその受け付けがもう一度当てる）。ruled の新しい申し出は拒否の後も積んだまま残す。裁定がもう外した単位の
   申し出は、出し直されても知っている申し出として確かめずに外す。盤面に渡す返答からは conflicts を外す（写しの schema に無い欄）
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
     直さない裁定の decision と id）を名指して拒む（最後の回は下の決まりで数えず、行だけを changes から外す）
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
   外れた単位の項目も範囲を与える（裁定の後の段は外れた単位の 1 回目の直しを戻さない。依頼 241）。裁定の後
   （ruled）に範囲が広がるのは直す裁定の limits のパスだけで、裁定を受けた単位の全部を外さない。out_of_scope はテストの許しと
   裁定の limits にも勝つ（案が外したパスが要るのは範囲の相談で案を書いた役が考え直すか、案の項目の誤りで fix_plan_item の道。
   相談で許したパスは字のまま同じパスに限ってその項目の out_of_scope から外れる。planscope.with_agreed）。ほかの項目の out_of_scope は、行の単位の
   項目が明示に許したパスを拒まない（run 249b。単位に結べない変更は全部の項目の out_of_scope で照らす）。
   控えに範囲の欄が無い・修正案の無い run は回さない。受けた時に trace に 1 行（SCOPE_OP）
1e. 事後の関門の束（fixgates.problems。計画 220 Task 4）: base から今の木までを相手に、承認済みの修正案の
   受け入れのテストの赤→緑（INPUTS_TDD_SUITE の実行器。無い run は帳面に飛ばした理由だけ）と、名指しの外の既存のテストの
   本体の変更を確かめる。行が在れば行ごとの文（fixgates.reject_lines。" / " でつないで 1 つの理由に全部の行が並ぶ）で拒む
   （今の拒否の道。最後の回はほかの行と同じ決まりで単位に結ぶ）。盤面に done を書く 3 の前に置く
   （拒否では盤面を前のままにする。束の帳面 fixgates.LEDGER と一式のログは残す）。受けた回に束が赤緑を確かめずに飛ばした
   理由（fixgates.unchecked。義務の外の項目を見なかった理由は除く）は盤面の trace の fixgates.SKIPPED_OP の行に載せる
   （報告と最後の人の関所の文が数える）。2 回目の修正の段（同じブロックの 2 度目の include）の帳面はその scope の物で、
   裁定の範囲は 1 回目の段の物をいつも許す（fixgates.problems が conflict.second_pass で引く）
2 の前. 2 回目の修正の段（1 回目に受け付けた返答の控えが在る）: 返答を名前に戻し、控えの行を単位で合わせる（conflict.with_held）。
   -3〜1e の検査は役の返答そのものに当て、合わせた返答を 2・2a・3 と盤面に渡す。2 回目の段の受け付けは控えの単位を changes か
   not_done に書いた返答を、直しを戻させない自分の文（ACCEPTED_ROWS。check_accepted_rows。id accepted）で拒み、輪の最後の回でもその直しを
   作業ツリーから戻さない。その単位の役の行は積んだ後に返答から外し（drop_accepted_rows）、後の確かめと合わせた返答の照らしに当てない
2. unitrows.take: 閉鎖の数え直しの前段。判定者の class_query（replace_query の裁定を受けた単位は置き換えた問い）を修正前の版と
   修正後の作業ツリーで機械が数え、単位ごとの表（querytest.CLOSURE_FILE。最後の関所と報告が読む）に closed と、修正役の申告
   （closure.sites の path が覆う問いの当たりの件数・remaining・作り直した how）との食い違いを記録する。食い違いは拒否でなく記録で、写しに渡す返答は
   写しの数え合わせの拒否が発火しないように揃える
2a. 案の直しを待つ単位（conflict.waiting。裁定 fix_plan_item の WAITING の行）が在り、盤面が p3.fix を待っていれば（named_reply）、
   積んだ行が無く写しの照らしを乾いた形（3 の commit=False）で通る時だけ盤面に渡さずに控える（hold_fix。積んだ行か照らしの
   誤りが在れば控えずに並べて拒む。控えた返答を後で replan.settle の hand_held が渡して拒まれ盤面が止まる前に役へ返す）: 2 で揃える前の
   役が書いた形の返答（番号は名前に戻す。site の path と役の coverage が在る）に、盤面に渡す形の changes（欄 conflict.HANDED）と
   役が申告した bash_writes を残して conflict.HELD_REPLY に置き、受けた時と同じ trace（書き込みの出どころ・TESTS_OP・SCOPE_OP・fixgates.SKIPPED_OP・CLOSURE_OP）と HELD_OP を書いて
   {ok: true, done: true, parked: true, changes: 1 本目の行}。盤面へは修正の段を抜ける所の replan.settle（hand_held）が渡す
3. recount.accept_fix: 盤面の done("p3.fix")。写しの fix_covers_open_units が同じ問いで数え直す（仕様 3.2）。通れば 1 本目の
   出口のための changes（unit_key・files・what）を足し、表を盤面に置く
loop_group の外の節は中の節の出力を引けず、輪の出力は最後の周の末端（この節）の出力なので、受け付けた changes を
ここで出口へ運ぶ（collect が今の周の changes.json に書く）。拒んだときの changes は空。
中身の拒否は終了コード 0 の {"ok": false, "reason", "rejects", "reason_file", "changes": [], "done"} を 1 行。回す側の誤りは 2。
done は輪を抜ける旗（通った時か輪の 3 回目の拒否。R50: max_iterations に当てて run を落とさない）。3 回目（最後の回）の積んだ行と写しの
拒否の行は parking.settle で単位に結ぶ: 形の誤りで拒んだ食い違いの申し出の行は申し出た単位（take_conflicts が行ごとに渡す unit_key。
読めない時だけ文の名指しへ）に、ほかの行は文が名指す単位（unit_key・足跡・届く試験のパス）に、結べない行は直す義務の全部の単位に結び、
義務の外の単位にだけ結んだ行は数えない（その単位の行を changes から外し、直しは作業ツリーに残す。trace に ABSORBED_OP）。
結んだ義務の単位は足跡を共にする単位と一緒に止め、足跡を段の頭の木（leftovers.head_tree）に戻して控えの patch に移し、ask_human に
裁いて（trace に PARKED_OP）残りの単位で受け付けを頭から通し直す（park_units）。止めた単位は義務の外になるので通し直しは終わる。
止める単位が無いのに写しが拒めば（義務の全部を止めた後も返答の欄が写しの型・規則に合わない。run 222f の型）、役の返答の代わりに
機械の空の返答を渡す（hand_empty。盤面を止めない）
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402
import posixpath  # noqa: E402

import conflict  # noqa: E402   食い違いの申し出（.shared/core）
import fixgates  # noqa: E402   事後の関門の束（blk-fix/lib）
import impact  # noqa: E402   変更に当たる試験の選び（.shared/core）
import planbrief  # noqa: E402   今の周の brief の行（blk-fix/lib。申し出 brief_vs_judgment の確かめ）
import leftovers  # noqa: E402   .archon/ の決まりと修正役の前の控え（.shared/core）
import planscope  # noqa: E402   承認済みの修正案の項目と差分の照らし（blk-fix/lib）
import querytest  # noqa: E402   判定者の問いを例に当てる（.shared/core）
import recount  # noqa: E402
import tddloop  # noqa: E402
import unitrows  # noqa: E402   閉鎖の数え直しの前段（blk-fix/lib）
import entry  # noqa: E402
import parking  # noqa: E402   最後の回に止める単位を選ぶ（blk-fix/lib）
import script_io  # noqa: E402   盤面の今の scope の根（.shared/core）
import writes  # noqa: E402   書き込みの出どころの突き合わせ（.shared/core）
from leftovers import git  # noqa: E402
import consult  # noqa: E402   範囲の相談の周と枠（blk-fix/lib）
from factchecks import (  # noqa: E402   事実の確かめの口（blk-fix/lib。修正役の事前の確かめと同じ口）
    check_frozen, check_plan_scope, check_writes, fix_unit_keys, named_reply, resolved_changes,
    declared_files)

# INPUTS_CONSULTED は範囲の相談の周の印（無い・true でなければ回す。前の版の with: で再開した run は渡さない）
INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_TDD_STATE", "INPUTS_ITERATION", "INPUTS_PASS", "INPUTS_TDD_SUITE",
          "INPUTS_CONSULTED")
GIVE_UP_AFTER = 3   # 諦める拒否の回。輪 fix-loop の max_iterations はこれと相談の枠 consult.BUDGET の和（tests/test_blk_fix.py が YAML と突き合わせる）
CONSULTED_ENV = "INPUTS_CONSULTED"   # 確かめの節の consulted（true ならこの周は範囲の相談の周で、受け付けを回さない）
CONSULTED = ("範囲の相談の周（返答の consult に答えの節が答えた）。受け付けは回さず、次の周の修正役が答えを読んで続けた返答を"
             "受け付ける")
CONSULT_SPENT = ("範囲の相談の枠（この段の輪で {n} 回）を使い切った後の consult を受けない。consult の欄を外し、範囲の中で直すか、"
                 "変えずに食い違いの申し出（kind は scope_needed）で返せ")
TESTS_OP = impact.ACCEPT_TRACE_OP   # 受け付けが選んだ試験を走らせた盤面の trace の行（ci_left・final_left を最後の関所が読む）
DUPLICATE = "同じ unit_key を 2 行以上に分けた（直した単位ごとにちょうど 1 行。1 つの単位が複数のファイルに及ぶなら files に並べよ）: "
NOT_OPENED = ("今の周に直す単位に無い unit_key を changes に書いた（開いた単位と、関所で答えた問いの出どころ・depends のほかは直さない。"
              "単位を切り直さず、貼られた単位の no か key で指せ。判定への異議は rejudge_requested に書く）: ")
EXCUSED = ("直す義務から外れた単位を changes に書いた（答えが届くまで・人が決めるまで直さない。changes から外し、not_done に"
           "理由を書け）: ")
ACCEPTED_ROWS = ("1 回目の修正の段で受け付けた単位を changes か not_done に書いた（その単位の行は機械が 1 回目の控えから足す。"
                 "changes からも not_done からも外せ。作業ツリーのその単位の直しはそのまま残せ）: ")
ABSORBED_OP = "fix_excused_dropped"   # 最後の回に、義務の外の単位の行を changes から外した・数えなかった拒否の文の盤面の trace の行
HELD_OP = "fix_held"   # 待つ単位が在る間、盤面に渡さずに返答を控えた（conflict.HELD_REPLY）盤面の trace の行


CONFLICT_BAD = "食い違いの申し出を受けない（名指した所が現物に無いか、形が違う。直して丸ごと出し直せ）: "
CLOSURE_OP = "fix_unit_rows"   # 受けた返答の単位ごとの閉鎖の表（querytest.CLOSURE_FILE）を置いた盤面の trace の行
BOUND_PARKED = ("修正の輪の最後の回も、この単位に結んだ拒否が残った（文がこの単位か、その足跡・届く試験を名指す。どの単位にも"
                "結べない拒否は直す義務の全部の単位に結ぶ）。返答全体を拒んで盤面を止める代わりに、機械がこの単位の直しを段の頭の木に"
                "戻して控えの patch に移し、人に回し、ほかの単位の直しを受けた。拒否の文: ")
PARKED_OP = conflict.ACCEPT_PARKED_OP   # 最後の回に止めた単位の盤面の trace の行（unit_keys・patch・reasons {key: [文]}・unbound {文: 理由}・how {文: 結び方}）
PARKED_PATCH = "fix-parked"            # 止めた単位の戻した直しの控え（盤面の今の周の fix-parked-<n>.patch）
EMPTY_HANDED = ("修正の輪の最後の回に、直す義務の単位を全部止めても返答が写しの受け付けを通らなかったので、役の返答の代わりに"
                "機械の空の返答を渡した: ")   # 後ろに残った行を " / " でつなぐ（hand_empty。盤面の p3.fix の fix_closure.reason）
SECOND_CONFLICT = ("裁定の後の出し直しで新しく申し出た食い違い——裁定の輪は 1 周に 1 回だけなので、機械が人に回した"
                   "（最後の人の関所で人が決める）")


PACK_COPY = ("修正役は .archon/ の下を変えてはいけない（Archon の置き場で、この run を動かしている線の写しが在りうる。"
             "写しは次の run が作り直す）: ")

# 修正の受け付けの確かめの id → 拒否の見出しの短い名。並びは受け付けが回す順。
# 拒否の見出しと確かめの id の表はここ 1 か所（role-rejects の行の id もここから引く。依頼 236）
CHECKS = {
    "consult": "範囲の相談の枠",
    "frozen": "TDD の輪で凍ったテストのファイル",
    "writes": "書き込みの出どころ",
    "conflict": "食い違いの申し出の形",
    "pack": ".archon/ の下の変更",
    "duplicate": "同じ unit_key の重なり",
    "not_opened": "今の周に直す単位に無い unit_key",
    "accepted": "1 回目の修正の段で受け付けた単位の行",
    "excused": "直す義務から外れた単位",
    "scope": "承認済みの修正案の範囲",
    "tests": "変更に当たる試験の赤",
    "gates": "事後の関門の束",
    "copy": "写しの受け付け（graph の p3.fix の型と規則）",
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
    for check, head in CHECKS.items():
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
    changed = leftovers.archon_changes(board, repo)
    parts = []
    if declared:
        parts.append(f"changes[].files に申告した {sorted(declared)}（申告から外す）")
    if changed:
        parts.append(f"修正役の前の控え（節 ignored-before）から変わった {changed[:20]}（.archon/ の下は元の姿に戻してから"
                     "出し直す: 追跡している物は git checkout -- <パス>、足した物は消す）")
    return PACK_COPY + " / ".join(parts) if parts else ""


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


def take_conflicts(reply: dict, board: Path, repo: Path, pass_: str):
    """食い違いの申し出（欄 conflicts）を外した返答と、拒否の文か止めた印。返り (返答, 結果 | None)。結果が None なら受け付けを続ける。
    - 裁定がもう外した単位（conflict.held_by_rulings）の申し出は知っている申し出として先に外す（確かめも積み増しもしない。
      拒まれた返答の申し出は積まれて残り、「丸ごと出し直せ」で同じ単位に出し直されるので。run 195d）
    - 申し出が在れば機械が確かめる（conflict.problems: 形・今の直す義務の単位か・名指した所が現物に在るか・kind brief_vs_judgment
      ならその単位の今の周の brief の行を名指すか（planbrief.by_unit_at））。外れれば普通の拒否
    - first: 通った申し出を盤面の控えに積み（拒否に数えない）、裁かれていない申し出が在れば（TDD の輪の分も）盤面に渡さずに
      {ok: true, parked: true, changes: []}（裁定の輪の後、2 回目の修正役が渡す）。返答は盤面の置き場に控える（PARKED_REPLY。
      今の scope の周の置き場）
    - ruled: 裁定の後の新しい申し出は、裁定の輪がもう無いので機械が ask_human に裁いて積む（その単位を直した返答は
      check_excused_units が拒む）"""
    reply = dict(reply)
    items = reply.pop("conflicts", None) or []
    b = entry.open_board(board)
    if isinstance(items, list) and items:   # 形の崩れた欄は problems に任せる
        known = conflict.held_by_rulings(b)
        items = [i for i in items if not (isinstance(i, dict) and i.get("unit_key") in known)]
    owed = conflict.owed_units_but_asked(b)
    if items:
        entries = conflict.problems_by_entry(items, repo=repo, board_dir=board, owed=owed,
                                             try_query=querytest.judge_hits(b.record["units"]), briefs=planbrief.by_unit_at(board))
        # 結果の lines: [(申し出た単位の key か None, 文)]。key が読める申し出は 1 件 1 行（最後の回に止める単位を結ぶ）
        lines = [(key, CONFLICT_BAD + " / ".join(texts)) for _, key, texts in entries if key and texts] \
            + [(None, CONFLICT_BAD + t) for _, key, texts in entries if not key for t in texts]
        both = sorted({i.get("unit_key") for i in items if isinstance(i, dict)}
                      & {c.get("unit_key") for c in reply.get("changes") or [] if isinstance(c, dict)})
        bad = [t for _, _, texts in entries for t in texts]
        if both:
            bad.append(f"申し出た単位を changes にも書いた: {both}（申し出た単位は直さない）")
            lines += [(k if k in owed else None, f"{CONFLICT_BAD}申し出た単位を changes にも書いた: {k}（申し出た単位は直さない）")
                      for k in both]
        if bad:
            return reply, {**_reject(CONFLICT_BAD + " / ".join(bad)), "lines": lines}
        if pass_ == "first":
            conflict.park(b, items, source="fix")
        else:
            conflict.park(b, items, source="fix", ruling={"decision": conflict.ASK, "text": SECOND_CONFLICT, "limits": [],
                                                          "by": "works:fix-accept"})
            conflict.write_rulings(b)
    if pass_ == "first" and conflict.unruled(b):
        _put_parked(b.work(conflict.PARKED_REPLY), {**reply, "conflicts": items})
        return reply, {"ok": True, "parked": True, "reason": "", "changes": []}
    return reply, None


def _put_parked(path: Path, reply: dict) -> None:
    """控えの返答（conflict.PARKED_REPLY・HELD_REPLY）を書く（一時のファイルから置き換える）"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(reply, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def check_tests(board: Path, base_rev: str, repo: Path, state: str) -> tuple:
    """版からの変更に当たる試験を機械が走らせた赤（tddloop.selected_problems）。返り (赤の文, 知らせ)。盤面は書かない"""
    return tddloop.selected_problems(state, repo, writes.base_rev(entry.open_board(board), base_rev))


def _named_rows(reply: dict, board) -> list:
    """changes の行（番号の unit_key は盤面の控えで名前に戻す。戻せなければ返答の行のまま。dict でない行は外す）"""
    named = resolved_changes(reply, board)
    return named if named is not None else [c for c in reply.get("changes") or [] if isinstance(c, dict)]


def _rows_without(reply: dict, board, drop: set) -> list:
    """changes から、名前（_named_rows と同じ戻し）が drop に在る行を外した列（返答の行のまま）"""
    raw = reply.get("changes") or []
    named = resolved_changes(reply, board)
    names = [c.get("unit_key") for c in named] if named is not None else \
        [c.get("unit_key") if isinstance(c, dict) else None for c in raw]
    return [c for c, k in zip(raw, names) if k not in drop]


def last_settle(texts: list, reply: dict, board, base_rev, repo, state, parked: set, by_copy: bool = False,
                declared: dict = None) -> tuple:
    """輪の最後の回の拒否の文 texts を単位に結ぶ（parking.settle）。返り (Settlement, 義務の外の単位の key の集合)。
    by_copy が真（写しの拒否）で止める単位が無いのに義務の残りが在れば、その全部を止める（parking.park_owed。写しは受けないので
    空の返答へ落ちて受けた直しを捨てない）。
    足跡は返答の行（名前に戻した changes）と今の段の輪の状態（state。前の周・1 回目の段の輪は入れない）、届く試験は単位ごとの impact の地図（版は writes.base_rev、
    置き場は今の輪の work の下の impact。輪が無ければ盤面の今の scope の impact）。義務の外は conflict.fix_duty の外れた単位と、
    この受け付けがもう止めた単位（parked。止めた単位を同じ受け付けで 2 度止めない）。単位の key は盤面の単位と返答の行の和"""
    b = entry.open_board(board)
    rev = writes.base_rev(b, base_rev)
    rows = _named_rows(reply, board)
    feet = parking.footprint(rows, [state] if state else [], repo)
    cache = (Path(tddloop.load_state(state)["work"]) if state else script_io.scope_dir(board)) / "impact"
    reached = {k: parking.reach(repo, rev, f, cache) for k, f in feet.items()}
    owed, excused = conflict.fix_duty(b)
    out = set(excused) | parked
    keys = {u.get("key") for u in b.record.get("units") or [] if isinstance(u, dict)} | {c.get("unit_key") for c in rows}
    got = parking.settle(texts, keys={k for k in keys if isinstance(k, str)}, feet=feet, reached=reached, owed=owed - out,
                         out_of_duty=out, changed=set(writes.changed(repo, rev)), declared=declared)
    if by_copy and not got.park and owed - out:
        got = parking.park_owed(texts, feet=feet, owed=owed, out_of_duty=out)
    return got, out


def revert_units(board, repo, files: set) -> str:
    """止めた単位の足跡 files を段の頭の木（leftovers.head_tree）に戻す。先に、その木から
    今の作業ツリー（未追跡の新しいファイルも。一時の index で固めた木）への files の差分を盤面の fix-parked-<n>.patch に控える
    （戻した木に当てれば戻す前の姿になる）。返りは控えのパス"""
    b = entry.open_board(board, allow_halted=True)
    head = leftovers.head_tree(board)
    files = sorted(files)
    n = 1
    while b.work(f"{PARKED_PATCH}-{n}.patch").exists():
        n += 1
    patch = b.work(f"{PARKED_PATCH}-{n}.patch")
    now = leftovers.snapshot(repo)
    patch.write_bytes(git(repo, "diff", "--binary", "--no-renames", head, now, "--", *files, text=False) if files else b"")
    tddloop.restore_paths(repo, head, files)
    return str(patch)


def _without_rows(reply: dict, rest: list, mine: set, repo) -> dict:
    """changes を rest にし、外した行のファイル（mine）の bash_writes の申告も外した返答"""
    out = {**reply, "changes": rest}
    if isinstance(reply.get(writes.FIELD), list):
        out[writes.FIELD] = [w for w in reply[writes.FIELD]
                             if not (isinstance(w, dict) and declared_files([{"files": [w.get("path")]}], repo) & mine)]
    return out


def park_units(settled, out: set, whole: dict, board, base_rev, repo, parked: set) -> dict:
    """最後の回に結んだ単位を止める: 足跡（settled.files）を段の頭の木に戻して控えの patch に移し（revert_units）、単位ごとに
    ask_human の裁定つきの申し出を積み（conflict.park）、trace に PARKED_OP。止めた単位と義務の外の単位（out）の行と、戻した
    パスの bash_writes の申告を外した返答で受け付けを頭から通し直し、その返りを返す"""
    b = entry.open_board(board)
    patch = revert_units(board, repo, settled.files)
    for key, texts in settled.park.items():
        why = " / ".join(texts)
        conflict.park(b, [{"unit_key": key, "between": [], "why_both_cannot_hold": why, "which_is_right": conflict.UNKNOWN,
                           "kind": conflict.NEEDS_CONTEXT}],
                      source="fix", ruling={"decision": conflict.ASK, "text": f"{BOUND_PARKED}{why}（戻した直しの控え {patch}）",
                                            "limits": [], "by": "works:fix-accept"})
    conflict.write_rulings(b)
    b.trace(PARKED_OP, node=recount.ROLE, unit_keys=list(settled.park), patch=patch, reasons=settled.park,
            unbound=settled.unbound, how=settled.how)
    now = parked | set(settled.park)
    rest = _rows_without(whole, board, out | now)
    return accept_fix(_without_rows(whole, rest, settled.files, repo), board, base_rev, repo, parked=now)


def hand_empty(found: list, board, base_rev, repo) -> dict:
    """最後の回に止める単位が無いのに写しが拒んだ（義務の単位は全部止めた）: 役の返答の代わりに機械の空の返答
    （entry.empty_fix_reply。理由は EMPTY_HANDED と残った行）を盤面に渡す。2 回目の修正の段は 1 回目に受け付けた返答の控えの
    行を合わせる（conflict.with_held の as_handed。数え直しを通さないので控えの行は写しに渡す形。写しの義務は 1 回目の単位を
    引かない）。控えに changes が在れば、行の外の欄（fix_closure など。plan_faces と works だけの欄は除く）も控えの物にする（残る差分は 1 回目の直しだけなので、その返答が
    差分の全体を述べている）。合わせた changes が空の時だけ trace に
    entry.trace_empty_fix の印（1 回目の単位の行が在れば役の直しを含むので印を付けない）。
    返りは写しの受け付けの返り。それも写しが受けなければ回す側の誤り（ValueError。入口が 2 にする）"""
    why = EMPTY_HANDED + " / ".join(t for _, t in reject_rows(found))
    b = entry.open_board(board)
    reply = entry.empty_fix_reply(b, why=why)
    held, _ = conflict.held_reply(b)
    if held is not None and held.get("changes"):
        reply.update({k: v for k, v in conflict.handed(held).items() if k != "plan_faces"})
    reply = conflict.with_held(b, reply, as_handed=True)   # 数え直しを通さずに渡すので、控えの行は写しに渡す形
    out = recount.accept_fix(reply, board, base_rev, repo, commit=True)
    if out.get("ok") is not True:
        raise ValueError(f"機械の空の返答も写しが受けない（回す側の誤り）: {' '.join(str(out.get('reason') or '').split())}")
    if not reply.get("changes"):
        entry.trace_empty_fix(entry.open_board(board))
    return out


def hold_fix(named: dict, written: dict, whole: dict, b, traced) -> dict:
    """待つ単位（conflict.waiting）が在る間の受け付け: 役が書いた形の返答（written。番号は名前に戻した。unitrows.take が揃える前の
    物で、site の path と役の coverage が在る）に、盤面に渡す形の changes（named の物。欄 conflict.HANDED）と役が申告した
    bash_writes（whole の欄。前の控えの申告 conflict.held_writes を先に）を残して 1 回目に受け付けた返答の控え
    （conflict.HELD_REPLY）に置き、受けた時と同じ trace（traced）と HELD_OP を書く。盤面には渡さない（修正の段を抜ける所の replan.settle が
    渡す形 conflict.handed で渡す）。2 回目の修正の段は控えの行を書いた形のまま数え直しに当て直す（揃えた後の行では site を
    当たりのファイルに結べない）。返りは輪を抜ける {ok, done, parked}"""
    held = {k: v for k, v in written.items() if k != writes.FIELD}
    held[conflict.HANDED] = list(named.get("changes") or [])
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


def accept_fix(reply, board, base_rev, repo, *, parked=frozenset()):
    """修正役の返答の受け付け（模块の頭の手順）。parked はこの受け付けが最後の回にもう止めた単位（park_units の通し直しが渡す）"""
    state = os.environ.get("INPUTS_TDD_STATE", "")
    pass_ = os.environ.get("INPUTS_PASS") or "first"
    attempt = int(os.environ.get("INPUTS_ITERATION") or 0)
    last = attempt >= GIVE_UP_AFTER and isinstance(reply, dict)
    whole = reply
    scope_note = None   # 承認済みの修正案の項目と差分を照らした記録（受けた時に trace へ）
    absorbed = {"dropped": [], "absorbed": []}   # 最後の回に数えなかった物（受けた時に trace へ）

    found = []   # 積んだ拒否の行 (確かめの id, 文)。申し出より後の確かめは返さずにここへ積み、最後に 1 回だけ拒む
    # 範囲の相談の周（確かめの節の consulted）はここに来ない（入口が回さない）。来た consult は枠を使い切った後の物で、拒否に積む。
    # 合意は確かめの節が盤面の trace に書いた物（conflict.agreed）を後の確かめが読む
    if isinstance(reply, dict) and conflict.CONSULT_FIELD in reply:
        note(found, "consult", CONSULT_SPENT.format(n=consult.BUDGET))
        reply = {k: v for k, v in reply.items() if k != conflict.CONSULT_FIELD}
        whole = reply
    declared = {}   # 文 → 結び先の単位 key（申し出の行。申し出た単位を最後の回に止める）

    def settle(texts, by_copy=False):
        """最後の回: 行を単位に結ぶ。止める単位が在れば止めて通し直した返り、無ければ None（義務の外の単位の行を外した返答で先へ）。
        by_copy は写しの拒否の行（止める単位が無くても義務の残りが在れば止める。last_settle）"""
        nonlocal reply
        extra = {"declared": declared} if declared else {}   # 申し出の行が無い回は last_settle の既定のまま
        settled, out = last_settle(texts, whole, board, base_rev, repo, state, set(parked), by_copy=by_copy, **extra)
        if settled.park:
            return park_units(settled, out, whole, board, base_rev, repo, set(parked))
        rest = _rows_without(reply, board, out)
        dropped = [c.get("unit_key") for c in _named_rows(reply, board) if c.get("unit_key") in out]
        reply = {**reply, "changes": rest}
        absorbed.update(dropped=dropped, absorbed=settled.absorbed)
        return None

    note(found, "frozen", check_frozen(board, state, repo, pass_))
    wrote = check_writes(reply, board, base_rev, repo, state)
    note(found, "writes", wrote["problems"])
    reply = wrote["reply"]   # 誤りが在っても bash_writes を外した返答（後の確かめはこれを使う）
    # 申し出は積んだ誤りに依らず確かめて積む（裁定へ渡す。ruled の新しい申し出は ask_human の裁定つきで拒否の後も残る）
    reply, done = take_conflicts(reply, board, repo, pass_)
    if done is not None:
        if done.get("ok") is not False:   # 1 回目に裁かれていない申し出を止めた出口（積んだ誤りが在っても返す）
            return done
        for key, text in done.get("lines") or [(None, done["reason"])]:
            note(found, "conflict", text)
            if key:
                declared.setdefault(text, set()).add(key)
    got = fix_unit_keys(reply, board)
    if got is not None:
        note(found, "pack", check_pack_copy(reply, board, repo))
        keys, owed, excused = got
        note(found, "duplicate", [DUPLICATE + k for k in check_unique_units(keys)])
        note(found, "not_opened", [NOT_OPENED + k for k in check_opened_units(keys, owed | set(excused))])
        # 1 回目に受け付けた単位の直しは戻させない（並べるだけ）。その単位の役の行は外して後へ渡す
        mine = check_accepted_rows(reply, board)
        note(found, "accepted", [ACCEPTED_ROWS + k for k in mine])
        if mine:
            reply, keys = drop_accepted_rows(reply, keys, mine, board)
        note(found, "excused", [f"{EXCUSED}{k}（{why}）" for k, why in check_excused_units(keys, owed, excused).items()])
        scope, scope_note = check_plan_scope(reply, keys, board, base_rev, repo, state, pass_)
        note(found, "scope", scope)
    red, tests_note = check_tests(board, base_rev, repo, state)
    note(found, "tests", red)
    gates = fixgates.problems(board, repo, base_rev, os.environ.get("INPUTS_TDD_SUITE", ""), attempt, pass_=pass_)
    note(found, "gates", fixgates.reject_lines(gates) if gates else [])
    if last and found:
        out = settle([t for _, t in reject_rows(found)])
        if out is not None:
            return out
        found = []
    b = entry.open_board(board)
    if conflict.held_reply(b)[0] is not None:   # 2 回目の修正の段: 名前に戻して 1 回目の控えの行を合わせる（検査は済んだ役の返答に当てた）
        named = named_reply(reply, board)
        reply = conflict.with_held(b, named if named is not None else reply)
    own = reply   # 写しに渡す形に揃える前の返答（控える時は控えの行をこの形で残す。take は渡した返答を変えない）
    reply, rows = unitrows.take(reply, b, repo)

    def traced():   # 受けた時だけ盤面の trace と表に積む（拒否・回す側の誤りでは盤面を前のままにする）
        tb = entry.open_board(board, allow_halted=True)
        writes.trace(tb, recount.ROLE, wrote)
        tb.trace(TESTS_OP, node=recount.ROLE, note=tests_note, ci_left=tddloop.ci_left(state),
                 final_left=tddloop.final_left(state), final_far=tddloop.final_far(state))
        if scope_note is not None:
            tb.trace(planscope.SCOPE_OP, node=recount.ROLE, **scope_note)
        gaps = fixgates.unchecked(board, pass_=pass_, attempt=attempt)
        if gaps:   # 束が赤緑を確かめずに受けた回（拒まないが、報告で見えるように）
            tb.trace(fixgates.SKIPPED_OP, node=recount.ROLE, why=gaps)
        if rows:
            tb.trace(CLOSURE_OP, node=recount.ROLE, file=str(querytest.save_closure(tb, rows)))
        if absorbed["dropped"] or absorbed["absorbed"]:
            tb.trace(ABSORBED_OP, node=recount.ROLE, **absorbed)
        return tb

    # 待つ単位が在れば控える返答（named）。積んだ行が在るか控える時は、写しの照らしを乾いた形（commit=False。盤面を書かない）で
    # 当ててその誤りも並べる（控えた返答を後で replan.settle の hand_held が渡して拒まれ盤面が止まる前に、役へ返す）。
    # どちらでもなければ盤面に done("p3.fix") を書く（事後の関門の束の後。preflight F12）
    named = named_reply(reply, board) if conflict.waiting(b) else None
    own_named = (named_reply(own, board) or own) if named is not None else None
    out = recount.accept_fix(reply, board, base_rev, repo, commit=not found and named is None)
    if out.get("ok") is not True:
        note(found, "copy", out.get("problems") or [str(out.get("reason") or "")])
    if last and found:   # 最後の回の写しの拒否も同じ決まりで結ぶ（止める単位が無ければ機械の空の返答を渡す）
        got = settle([t for _, t in reject_rows(found)], by_copy=True)
        return got if got is not None else hand_empty(found, board, base_rev, repo)
    if found:
        return rejected(found)
    if out.get("ok") is not True:   # 文の無い拒否（積む行が無い）はそのまま返す
        return out
    if named is not None:
        return hold_fix(named, own_named, whole, b, traced)
    traced()
    return out


def with_done(out: dict) -> dict:
    """輪を抜ける旗 done（R50）: 通った時か、この周の輪の 3 回目（fix-prep の iteration。INPUTS_ITERATION。範囲の相談の周は数えない）
    の拒否。iteration が数でなければ ValueError（回す側の誤り。main_accept が 2 にする）"""
    it = int(os.environ["INPUTS_ITERATION"])
    return {**out, "done": out.get("ok") is True or it >= GIVE_UP_AFTER}


def consulted_out() -> dict:
    """範囲の相談の周の出口（盤面にも拒否の理由のファイルにも書かない。done は立てない）"""
    return {"ok": False, "done": False, "consulted": True, "reason": CONSULTED, "reason_file": "", "changes": []}


def main() -> int:
    """入口。確かめの節が相談の周と言えば（INPUTS_CONSULTED が true）、返答を見ずに consulted_out の 1 行を出して 0"""
    if os.environ.get(CONSULTED_ENV, "").strip().lower() == "true":
        print(json.dumps(consulted_out(), ensure_ascii=False))
        return 0
    return recount.main_accept(accept_fix, finish=with_done)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # 相談の周の 1 行は script_io を通らずに出す（日本語の理由の文）
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
