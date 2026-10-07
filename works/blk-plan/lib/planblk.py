"""blk-plan の芯（P1 計画 Task 25。〔線A計〕T11 を P1-R10 で書き直した物）。独立設計（r2.design）・修正案（p2.fix_plan）・
事前審査（p2.plan_review）の 3 つの役を、本線の指示書を engine の描き方で描いて回す（rolekit）。人の関所の項目は盤面の p2.human_gate が組む。
独立設計は盤面の節がまだ待っていない（graph では修正の後）ので、支度・受け付け・控えは core の design に任せる（役 r2-design）。
事前審査の指示書の頭には、その設計（無ければ無い理由）を貼る（design_section）。修正案の指示書の頭には、盤面の根の構造のブロックの
控え（core の structmark）から構造の目の行か、行なしで計画した印を貼る（独立設計の役には渡さない）。
事前審査の壁打ち（依頼 231。core の converge）で again の時は、直しの役（REVISE_ROLE。修正案の役の会話の続きで、盤面の節は
p2.fix_plan）が案を直す。直しの役が起きるかは壁打ちの控えの事実（converge.held）だけで決める。どの節の分かれも、直しの役と
独立設計の役を関数の頭に置く。

- snap:     役を起こす前の作業ツリーの写し（accept.tree_state。R47）を今の周の <役>-snapshot.json に置き、節が待っているか
            （go）を返す。待っていなければ（判定が直す物を出さなかった・修正案が諦めた）輪を飛ばす。修正案は、必ず入れるのに
            開いていない単位が在れば（stuck_reason。案の形では閉じない）盤面を止めて（by works:plan）輪を飛ばす
- prep:     rolekit.render_prompt で本線の指示書を描き（頭に役の定義と、並行 PR の外した範囲のパスと、修正案の役なら前の run で
            最後まで通らなかった物の節 prior_part）、番号の控え（pointer_rows）を
            付けて起こした印（mark_launched）を置く。拒否の後の出し直しは、頭の 1 行が前の拒否の理由のファイルを名指す（R44）
- accept:   rolekit.main_accept（take が狭めない案の欄を欠く narrows の行を拒み、関所の項目の決め手の欄を外して盤面に置き（gatemarks）、entry.take・読むだけの役の作業ツリーの比べ・3 回目の拒否で done・give_up。R50）。
            修正案は、項目の works の欄（route・tests・rewrite_tests・refactor・allowed_paths・out_of_scope）の欠けを
            盤面へ渡す前に拒み、欄を外した案を渡して、
            盤面が受けた時だけ欄を盤面の plan-fields.json に控える（with_plan_fields。planmarks）。事前審査の指示書の頭にはその欄も貼る。
            事前審査はどの往復も盤面が settle なしで受けて往復を記録し（with_converge。core の converge）、新しい block が在れば
            役の節 2 つを同じ周の待ちに戻す（rewind_roles）。2 往復目からの指示書の頭には前の往復の block と答えを貼る
            直しの役は block への答え（converge の block_answers）の欠けと誤りを盤面へ渡す前に拒み、答えを外した案を修正案と同じ口
            （with_plan_fields。比べる作業ツリーの写しは直しの役の snap が置いた物）に渡し、盤面が受けたら答えを控えに置く（revise_take）
- converge-check: 壁打ちの出口 {ok, done, outcome, record_file}。抜け方が again でない・今の往復の役が諦めた・盤面が止まった時に
            done（converge_check。輪を max_iterations で落とさない。R50）。replan では壁打ちを回さない（直しの役の snap は
            go: false、converge-check はいつも 1 往復で done）
- ripple:   波及の一覧の節（線の木の段 1。設計 docs/plans/2026-10-06-tree-line.md の 2.3）。stage units は修正案の役の前に
            単位の key の名を引いて今の周の ripple/units.json に、stage items は往復ごとの事前審査の前に盤面の plan-fields.json の
            項目ごとに引いて ripple/pass-<k>.json と最新の写し ripple.json に置く（lib の ripple）。修正案の役・直しの役・事前審査の
            下請けの指示書がそれを貼り、修正の段は線が ripple.json を受け取る。replan では節では作らず、出口の collect が直した
            項目で作り直して ripple/replan.json に置く（replan_ripple。周ごとに書き手は 1 つなので ripple.json は上書きしない）
- 事前審査の木: 事前審査の役は束ね役。支度が開いた項目（converge.open_items）ごとの下請けのファイルと、項目が 2 つ以上なら相乗りの
            審査のファイルを今の周の plan-review-items/pass-<k>/ に書き、束ね役の頼み（AGG_HEAD）でそれを Agent で並べて起こさせる。
            下請けは答えを盤面の外の run ごとの置き場（answers_dir。盤面は守る場所で役が書けない）の機械が決めたファイルに Write で
            書く。受け付け（tree_merge）がそのファイルを項目ごとに確かめ（型・覆っていない当たりの全部の答え・自分の項目の単位だけ・
            前の block の行き先）、faces・shrink・resolved・当たりの答え・相乗りを審査の返答にまとめる。束ね役の返答は項目ごとの判定の
            要約（converge.ITEMS）だけで、答えのファイルと食い違えば拒む。確かめを通らない項目は、出し直しの支度がその項目の下請けの
            ファイルにだけ機械の読める誤りの一覧（ERRORS_HEAD）を貼って起こし直させ、通った項目は起こし直さない。
            修正案と直しを受けたら項目を壁打ちの控えに置き（converge.note_plan）、直しの役が閉じた項目を変えたら拒む（CLOSED_REJECT）。
            入力 review_tree が off（script_io.switch_on）なら支度は木の節（tree_part）を書かず、今の往復の下請けの置き場
            （ITEMS_DIR）が無いので受け付けは木のまとめを飛ばす（_tree_off。審査役 1 つの返答をそのまま受ける）
- 裏取りの申し送り: 入力 verify_file（判定の単位ごとの裏取りと単位どうしの相乗りの JSON。形は verify_part）が在れば、修正案の役の
            頭に貼る（verify_part）。単位は直す義務で申し送りでは減らないので、根本でないと出た単位も案から外させない
- reads:    役の読んだ証拠（reads.collect）を今の周の reads-<役>.json に書き、その一覧を reads-plan-block.json に
- collect:  出口 {ok, plan_file, review_file, asks_human, gate_kinds, reads_file, gave_up, reason_file, ripple_file}。役の節がこの周に
            待ったまま（3 回とも拒まれた）なら、最後の拒否の理由で盤面を止めて（by works:plan）ok: false・gave_up: true。
            独立設計が 3 回とも拒まれたのは止めず、盤面の trace に設計が無いことを書く（最後の R2 が目の層で言う）
- replan:   入力 replan が空でなく文字列 null でもなければ（ラインが同じブロックを 2 度目に include した、同じ run の中の案の直し。
            依頼 226）、snap・prep・main_accept・collect を core の replan の同名の口へ回す（prep は head と、事前審査なら独立設計の節
            design_only を組んで渡す）。独立設計の輪は今どおり design.due で飛ぶ。collect_reads は役の名 replan-<役> で読んだ証拠を
            reads-replan-<役>.json に、索引を replan.READS_INDEX に書く（1 回目の reads-<役>.json・reads-plan-block.json を上書きしない）
"""
import copy
import difflib
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import accept  # noqa: E402
import adapter  # noqa: E402  （L2。run ごとの置き場 run_place_of。事前審査の下請けの答えのファイルの置き場）
from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import converge  # noqa: E402
import design  # noqa: E402
from engine import pointers  # noqa: E402  （board が写しの engine を sys.path に足す）
from engine.schema import validate_schema  # noqa: E402
import entry  # noqa: E402
import gatemarks  # noqa: E402
import libdocs  # noqa: E402
import node_marker  # noqa: E402
import planmarks  # noqa: E402
import reads  # noqa: E402
import replan as replan_mod  # noqa: E402  （入力の名 replan と分ける）
import ripple  # noqa: E402  （blk-plan の lib。波及の一覧）
import rolekit  # noqa: E402
import script_io  # noqa: E402  （L1。入力の切り替えの語 switch_on）
import structmark  # noqa: E402

NODE_OF = {"plan": "p2.fix_plan", "plan-review": "p2.plan_review"}   # 役（YAML の役の節の id・印の名）→ 写しの graph の節
ROLES = tuple(NODE_OF)
DESIGN_ROLE = "r2-design"   # 独立設計の役（盤面の節へは渡さない。core の design）
REVISE_ROLE = "plan-revise"   # 直しの役（事前審査の壁打ちで修正案の役の会話の続き。盤面の節は p2.fix_plan。NODE_OF・ROLES に入れない）
REVISE_PROMPT = "prompt-plan-revise-{k}.md"   # 直しの役の指示書（今の周の作業ファイル。k は次の事前審査の往復の番号）
READS_LOOP = {"plan": "plan-loop", "plan-review": "converge-loop.plan-review-loop",
              REVISE_ROLE: "converge-loop.plan-revise-loop"}   # 役 → 出来事の節の名の輪（入れ子の輪は <外>.<中>）
ISOLATED_FLAG = "isolated"  # 道具ゼロの役の印の旗（包みが Git の外の置き場で起こす）
MAP_FLAG = "map"            # 工程の地図の旗（包みが system prompt に全体のグラフとこの会話の居場所を足す。修正案の役の会話の節に付ける）
STOP_BY = "works:plan"
GIVE_UP_AFTER = rolekit.GIVE_UP_AFTER   # 輪の max_iterations と同じ数（tests/test_blk_plan.py が YAML と突き合わせる）
READS_INDEX = "reads-plan-block.json"
NONE_WORDS = ("", "null")               # 入口の「無し」（Archon の入力の既定の空と、ラインが渡す文字列 null）
EXCLUDED_HEAD = "並行 PR の範囲。触らず、単位に入れない"
NO_NARROW_REJECT = (f"narrows の行に狭めない案を探した結果（{gatemarks.NO_NARROW}）が無いか短い（直して done し直す）。狭めを避ける形が"
                    "在ればそれを案に採ってその行を消し、無い時だけ、どの形を当たりなぜ採れないかを書け:")
NOT_OWED_REJECT = "案に、直す義務の無い単位が入っている（nit・info・defer など。受け付けが受けない）。案から外せ。案に入れてよい no（必ず入れる物を含む）は"
RESOLVED_REJECT = "前の往復の block の行き先が書かれていない（下の行を全部直して出し直せ）:"
ANSWERS_REJECT = "block への答えに誤りが在る（下の行を全部直して出し直せ）:"
TREE_REJECT = "項目ごとの審査の答え（下請けの答えのファイル・束ね役の items）に欠けか誤りが在る（下の行を全部直して出し直せ）:"
CLOSED_REJECT = "閉じた項目を変えた（下の行を直して出し直せ）:"
RIPPLE_UNITS = "ripple/units.json"      # 今の周の作業ファイル（manifest の produces ripple/**）
RIPPLE_PASS = "ripple/pass-{k}.json"
RIPPLE_LATEST = "ripple.json"           # 最後に作った項目ごとの一覧の写し（修正の段へ線が渡す。manifest の produces）
RIPPLE_REPLAN = "ripple/replan.json"    # 案の直しの後に、直した項目で作り直した一覧（replan の collect が書く。manifest の produces ripple/**）
ITEMS_DIR = "plan-review-items/pass-{k}"   # 事前審査の下請けのファイル（manifest の produces plan-review-items/**）
# 下請けの答えのファイルの置き場（run ごとの置き場 adapter.run_place_of の今の scope の下。盤面の外——盤面は守る場所で役が書けない。
# 受け付けが確かめたファイルは往復の控え plan-converge/pass-<k>/ に写す）
ANSWERS_DIR = "plan-review/r{r}/pass-{k}"
ANSWER_FILE = "item-{n}.json"
SYNERGY_FILE = "synergy.json"
AGENT_OP = "plan_review_agents"         # 読んだ証拠の節が盤面の trace に書く、事前審査の下請けの起動の数の行
# 下請けの型は 1 つ（答えのファイルを Write で書ける型。読むだけの Explore は Write を持たない。run 68f35d6b は往復 1 が
# general-purpose・往復 2・3 が Explore で、型ごとに道具と深さが違った）
SUBAGENT_TYPE = "general-purpose"
AGG_HEAD = "## 束ね役の頼み（項目ごとの下請けを並べる。機械が貼った）"
AGG_ASK = ("お前は束ね役。案の項目を自分で見ずに、下の下請けのファイルごとに Agent の道具で下請けを 1 つずつ起こせ。下請けの呼びは"
           " 1 つのメッセージに全部並べよ（同時に走る）。subagent_type は全部 " + SUBAGENT_TYPE + "（相乗りの審査も同じ。ほかの型を"
           "使わない）。各下請けへの頼みは「<ファイル> を Read で読み、その指示に従え」の 1 行でよい。"
           "下請けは読むだけで、答えはファイルに書き（どこに書くかはファイルが名指す。作業ツリーは変えない。変われば受け付けが拒む）、"
           "最後に 1 行の要約を返す。答えのファイルは受け付け（機械）が確かめてまとめるので、お前は答えの中身を写さない。")
AGG_MERGE = ("下請けが全部返ったら、返答は次の形だけにせよ（受け付けが答えのファイルと突き合わせ、食い違えば拒む）: faces と shrink は"
             "空の配列、reason にこの往復のまとめ（20 字以上）、items に開いた項目ごとに 1 行 {item, verdict（下請けの要約が clean なら"
             " clean、block なら block）, blocks（下請けの要約の block の key ごとに {key, why（一言）}。clean なら []）}。"
             "閉じた項目・保留の項目の行は入れない。前の拒否の理由が済んだ項目の答えの中身を名指していれば、その項目の下請けを起こし"
             "直して理由のファイルを読ませ、答えのファイルを直させよ。")
AGG_SYNERGY = ("開いた項目の全部が clean なら、同じ往復の最後に相乗りの下請けを 1 つ起こす（{path}）。block の項目が在れば起こさない。")
OPEN_HEAD = "開いた項目の下請けのファイル:"
DONE_HEAD = "済んだ下請け（答えのファイルが機械の確かめを通った。起こし直さない）:"
REDO_HEAD = "起こし直す下請け（答えのファイルが無いか、機械の確かめを通らなかった。この下請けだけを起こす）:"
BRIEF_TITLE = "# 事前審査の下請け"
ITEM_HEAD = "## お前の項目: 項目 {n}"   # 下請けのファイルの共通の頭（全部の項目で同じバイト。プロンプトのキャッシュ）と項目の節の境
SUB_HEAD = ("お前は修正案の事前審査の下請け（読むだけ。Read・Grep・Glob と web の道具で調べ、Write は下の答えのファイルにだけ使う。"
            "Edit・Bash を使わず、作業ツリーを 1 文字も変えない）。審査の決まり・独立設計・判定者の見立てはこのファイルの頭に、"
            "お前の項目の案・単位・波及の一覧は最後の節に在る。ほかのファイルの指示書を読みに行かなくてよい（根拠のコードは読め）。")
RULES_FROM = "\nリポジトリ: "   # 描いた事前審査の指示書のうち、下請けに貼る審査の決まりの頭（そこから末尾まで）
RULES_MISSING = "審査の決まりを切り出せなかった。指示書 {main} の『見ること』『返し方』『人の方針』を Read で読め（そこの束ね役の頼みと返す型はお前への指示でない）"
SUB_FORMAT = ("## 答え方（全部の下請けで同じ）\n\n項目の下請けは、覆っていない当たりの全部に covered（この項目の範囲で覆っている。"
              "どこで）・no_effect（影響しない。理由）・block（穴。faces に severity block で挙げる）のどれかで答える（why は当たり"
              "ごとに 10 字以上。『同上』で済ませない）。faces の unit_keys は項目の unit_keys を字のまま写す（no の整数でなく）。"
              "resolved は前の往復の block のうち消えた key（無ければ []）。答えは下の JSON Schema に合う JSON 1 つにして、"
              "最後の節が名指すファイルに Write で書く（そのファイルのほかに書かない。書き直す時も同じファイル）。書いたら最後の"
              "メッセージに 1 行だけ返す（答えの中身を写さない）。\n\n```json\n{schema}\n```")
ANSWER_AT = "Write の道具でファイル {answer} に書け"   # 下請けのファイルが答えの置き場を名指す句（answer_in が引く）
DIFF_HEAD = "## 前の往復からのこの項目の案の差分（見るのはこの差分と前の block の行き先だけ）"
DIFF_ASK = ("前の往復でこの項目を見た審査は、下の前の block のほかに直しへ進めない穴を挙げなかった。今の往復で見るのは (1) 前の block が"
            "消えたか（消えたなら resolved、残れば同じ key で faces に block）と (2) 下の差分（- が前・+ が今）が作る新しい穴だけ。"
            "差分の外の所を見直して新しい穴を探さない。穴の重さの決まり（block か suggest か）は変えない。")
CARRIED_HEAD = "## 前の往復で答えた当たり（機械が答えを引き継ぐ。hits に入れなくてよい。差分で答えが変わる物だけ入れ直せ）"
# 先行例の出典の確かめ（見ること 8）は run の中で 1 度だけ: 開く下請けを出典ごとに 1 つに決め、受け付けがその答えの確かめを
# scope の根の PRECEDENT_CACHE に控え、後の往復・後の周の下請けには控えを貼って開かせない（run 68f35d6b は同じ 2 つの出典を
# 往復ごとに WebFetch で開き直した）
PRECEDENT_CACHE = "precedent-checks.json"
PRECEDENT_HEAD = "## この項目の先行例の出典（判定者の先行例のうち adopt・adapt。見ること 8）"
PRECEDENT_FETCH = "WebFetch で 1 度だけ開いて確かめ、答えの precedents に {id, found（在り単位の問題に当たっているか）, quote（確かめた一文）} の行を書け"
PRECEDENT_CACHED = "確かめ済み（控えのとおり。WebFetch で開き直さない。この控えで判定せよ）"
PRECEDENT_OTHER = "この往復は項目 {m} の下請けが開く（お前は開かない。この出典の穴は項目 {m} の下請けが挙げる）"
PRECEDENT_VERDICTS = ("adopt", "adapt")
ERRORS_HEAD = "## 前の答えの誤り（機械の確かめ。この誤りだけを直して同じファイルに書き直せ）"
SUB_ITEM_ASK = ("お前が見るのは下の項目 {n} だけ。この項目が固まる（直しへ進めない穴が無い）まで深く見よ。ほかの項目の穴は挙げない"
                "（項目どうしの関わりは別の下請けが見る）。答えは頭の『答え方』の型で、" + ANSWER_AT + "。書いたら最後のメッセージに"
                " 1 行だけ返せ: `項目 {n}: clean` か `項目 {n}: block <key>、<key>`。")
SUB_SYNERGY_ASK = ("お前は相乗りの審査の下請け。項目どうしの関わりだけを見る（1 つの項目の中の穴は挙げない。頭の『答え方』の当たりの"
                   "答えは要らない）: 同じファイル・同じ試験への食い違う変更・順番の依存・重複した作業・まとめられる所。穴は faces に"
                   "挙げ、unit_keys に関わる項目の単位の名を全部、字のまま入れよ（名指した項目だけが開き直す）。why に見た事と、穴が"
                   "無いならその理由を書く。答えは下の JSON Schema に合う JSON 1 つにして、" + ANSWER_AT + "（このファイルのほかに"
                   "書かない）。書いたら最後のメッセージに 1 行だけ返せ: `相乗り: clean` か `相乗り: block <key>、<key>`。"
                   "\n\n```json\n{schema}\n```")
LATER_NODES = ("p2.human_gate", "p3.lane_merge")   # 役の節 2 つを戻す前に、今の周に受けていてはいけない後ろの節（戻しは後ろへ伝わらない）
PLAN_STUCK = "修正案の行き止まり: 必ず案に入れる単位が開いていない"
STUCK_WHY = ("受け付けの写しは開いていない単位を受けず、義務からも外さないので、案の形では閉じない。人が関所で問いの答えを直すか、"
             "単位を開く")
PLAN_SLOTS_HEAD = ("## 案に入れてよい単位の no（機械が受け付けと同じ述語から作った。下の本文の『今の周に直す単位』の見出しと、"
                   "one_shot_closes に載る単位より、この節が優先する）")
DESIGN_HEAD = "## 独立設計（修正案を見ない別の目が、目的と実測した制約・人の関所の答え・依頼が名指した設計書の節から作った理想解。機械が貼った）"
DESIGN_ASK = ("修正案をこの設計と構造で突き合わせよ——何を固定し何を派生と見るか・どこに継ぎ目を置くか・目的の当事者が日常で回す"
              "動線が閉じるか。構造の本質的な食い違いは faces に kind contract_drift・severity block で挙げ、why を"
              "『独立設計との構造の食い違い: 』で始めよ。表現の違い・設計が触れていない所は食い違いでない（設計は判定の単位も"
              "実装の事情も知らない）。")
DESIGN_NOT_STANDS = ("設計の役は、目的の問いが立たないと返した（{reason}）。問いが立つかは修正の後の独立の目が前提を実態で検算して"
                     "扱うので、ここでは穴に挙げない。設計との突き合わせはせずに審査せよ。")
DESIGN_NONE = "独立設計は無い（{why}）。設計との突き合わせはせずに審査せよ。"
HEAD = {
    "plan": ("お前は修正案の役（読むだけ）。道具は Read・Grep・Glob と web を引く WebSearch・WebFetch だけで、作業ツリーを 1 文字も変えてはいけない（受け付けは起こす前の"
             "作業ツリーの写しと比べ、変わっていれば拒む）。下の指示書に従い、指示書の JSON Schema に合う JSON だけを返せ。"
             "\n\n" + planmarks.HEAD),
    "plan-review": ("お前は修正案の事前審査の役（読むだけ。判定をした役とは別の目）。道具は Read・Grep・Glob と web を引く WebSearch・WebFetch と、"
                    "項目ごとの下請けを起こす Agent と、下請けが答えのファイル（盤面の外の run ごとの置き場）を書く Write だけで、作業ツリーを"
                    " 1 文字も変えてはいけない（受け付けは起こす前の作業ツリーの写しと比べ、変わっていれば拒む）。下の指示書に従い、指示書の"
                    " JSON Schema に合う JSON だけを返せ。"),
}


def role_node(role: str) -> str:
    if role not in NODE_OF:
        raise BoardGap(f"役 {role!r} は blk-plan の盤面へ渡す役（{' / '.join(ROLES)}）でない")
    return NODE_OF[role]


def known_role(role: str) -> str:
    """役の写しの graph の節（独立設計の役・直しの役も含む）。知らない役は BoardGap"""
    if role == REVISE_ROLE:
        return NODE_OF["plan"]
    return design.NODE if role == DESIGN_ROLE else role_node(role)


def snapshot_name(role: str) -> str:
    """役を起こす前の作業ツリーの写しの名（直しの役は自分の snap が置く写し。1 往復目の修正案の写しと比べない）"""
    if role != REVISE_ROLE:
        role_node(role)
    return f"{role}-snapshot.json"


def output_format(role: str) -> dict:
    """役の output_format: 写しの schema（accept.role_schema）に印 works-node: <役> を付けた物（YAML に貼る値）。
    prep が番号の一覧を貼って控えを固める（mark_launched(pointers=)）ので、番号の欄は番号でも返せる型に開く。
    独立設計の役は番号の欄を持たず、道具ゼロの旗 isolated を付ける。直しの役は修正案の印の付いていない型に答えの欄
    （converge.with_fields）を足し、印に continue=plan（修正案の役の会話の続き）を付ける。修正案の役とその会話の続きの直しの役は
    工程の地図の旗 map を持つ（包みが工程の YAML から組んだ地図を渡す。同じ会話の節は旗を揃える）"""
    if role == REVISE_ROLE:
        schema = converge.with_fields(role, accept.role_schema(NODE_OF["plan"], numbered=True))
        return node_marker.mark(schema, role, cont="plan", flags=(MAP_FLAG,))
    if role == DESIGN_ROLE:
        return node_marker.mark(accept.role_schema(design.NODE), role, flags=(ISOLATED_FLAG,))
    flags = (MAP_FLAG,) if role == "plan" else ()
    return converge.with_fields(role, node_marker.mark(accept.role_schema(role_node(role), numbered=True), role, flags=flags))


def _pending(b, nid: str) -> dict | None:
    inst = b.rd["instances"].get(nid)
    return inst if inst and inst.get("status") == "pending" else None


def _given(value) -> str:
    return "" if value is None or str(value).strip() in NONE_WORDS else str(value)


def head(role: str, excluded_file: str = "", lib_docs: str = "", design_part: str = "") -> str:
    """指示書の頭（役の定義と、並行 PR の外した範囲のパスと、ライブラリの今の文書の節 libdocs.section と、事前審査なら
    独立設計の節 design_section・修正案なら構造の目の節 structmark.plan_section と入れてよい no の節 plan_slots_section）。
    修正案の役の定義（HEAD["plan"]）は、項目の works の欄（route・tests・rewrite_tests・refactor・allowed_paths・
    out_of_scope）の節 planmarks.HEAD を含む。
    事前審査の役は、その欄の JSON を design_section の中の planmarks.review_section で受ける"""
    text = HEAD[role] + "\n\n" + gatemarks.HEAD[role_node(role)]
    ex = _given(excluded_file)
    if ex:
        text += f"\n\n{EXCLUDED_HEAD}: {ex}（先に Read で読め。そこに挙がった範囲は、ほかの PR が扱う）"
    if lib_docs:
        text += "\n\n" + lib_docs
    if design_part:
        text += "\n\n" + design_part
    return text


def plan_slots(b) -> tuple[set, set, dict]:
    """(必ず入れる, 入れてよい, 単位の key → 単位)。写しの受け付け fix_plan_covers_units が読むのと同じ物（want＝b.rules._owed_units、
    opened＝validator の is_open）から作る。見せる頭の節と take の事前の拒否が、ここだけを読む"""
    V = b.rules.validator_module(b)
    units = {u["key"]: u for u in b.record["units"]}
    return set(b.rules._owed_units(b)), {k for k, u in units.items() if V.is_open(u)}, units


def _names(b, nid: str) -> list:
    return next((p.get("names") or [] for p in b.pointer_rows(nid)["pointers"] or []), [])


def plan_slots_section(b) -> str:
    """修正案の指示書の頭に貼る、入れてよい no・入れてはいけない no の節（本文の見出し・one_shot_closes より優先する）"""
    owed, opened, units = plan_slots(b)
    names = _names(b, NODE_OF["plan"])
    no = {k: i + 1 for i, k in enumerate(names)}
    must = sorted(no[k] for k in owed if k in no)
    may = sorted(no[k] for k in opened - owed if k in no)
    shut = [f"no {no[k]}（label={u.get('label')}・disposition={u.get('disposition', '無し')}）"
            for k, u in units.items() if k not in opened and k not in owed and k in no]
    if not shut:   # 本文の一覧が受け付けの集合と同じ（全部入れてよい）なら貼らない。行き止まりの盤面は役を起こす前に止める（halt_if_stuck）
        return ""
    return (f"{PLAN_SLOTS_HEAD}\n\n- 必ず案に入れる no: {must}\n- 入れてもよい no（人の答え待ちの問いの出どころ・depends。入れなくてもよい）: {may}\n"
            f"- 入れてはいけない no（受け付けが拒む）: {'、'.join(shut) or '無し'}")


def stuck_reason(b) -> str:
    """必ず入れるのに開いていない単位（関所で答えた問いの出どころが defer など。plan_slots の 必ず入れる − 入れてよい）が在れば、
    盤面を止める理由（PLAN_STUCK・その単位の no と key・STUCK_WHY）。無ければ空。写しの受け付けはこの単位を入れても外しても拒むので、
    役を起こすと同じ拒否を 3 回繰り返して止まる"""
    owed, opened, _ = plan_slots(b)
    stuck = sorted(owed - opened)
    if not stuck:
        return ""
    names = _names(b, NODE_OF["plan"])
    items = "・".join(f"no {names.index(k) + 1}（{k}）" if k in names else f"no の一覧に無い単位（{k}）" for k in stuck)
    return f"{PLAN_STUCK}: {items}。{STUCK_WHY}"


def halt_if_stuck(b) -> str:
    """行き止まりの単位が在れば盤面を止めて（by works:plan。もう止まっていれば止め直さない）理由を返す。無ければ空"""
    why = stuck_reason(b)
    if why and not (b.state.get("halted") or b.state.get("stop")):
        b.stop(why, by=STOP_BY)
    return why


def _resolved(b, nid: str, reply: dict) -> dict:
    """返答の写しの no を engine の pointers.resolve で名前に戻した物（戻せない番号は番号のまま。拒否は entry.take＝engine に任せる）"""
    got = copy.deepcopy(reply)
    pointers.resolve(got, b.nodes[nid].get("pointers"), (b.rd["instances"].get(nid) or {}).get("pointers"))
    return got


def _plan_keys(got) -> list:
    """修正案の返答が案の行に挙げた単位の key（文字列）。形の崩れた行・欄は飛ばす（形の拒否は entry.take＝engine に任せる。再提出の道に乗せる）"""
    rows = got.get("plan") if isinstance(got, dict) else None
    return [k for p in rows if isinstance(p, dict) and isinstance(p.get("unit_keys"), list)
            for k in p["unit_keys"] if isinstance(k, str)] if isinstance(rows, list) else []


def allowed_nos(b, nid: str) -> list:
    """案に入れてよい no（開いている単位の no。必ず入れる単位は開いている＝halt_if_stuck が保つ）"""
    _, opened, _ = plan_slots(b)
    return [i + 1 for i, k in enumerate(_names(b, nid)) if k in opened]


def not_allowed(b, nid: str, reply) -> list[str]:
    """修正案の返答が案に入れた単位のうち、受け付けが受けない物（入れてよくなく、必ず入れる物でもない）の理由の行。no は engine の
    pointers.resolve で名前に戻す（範囲外の番号・判定に無い key の拒否は entry.take＝engine に任せる）"""
    if not isinstance(reply, dict):
        return []
    owed, opened, units = plan_slots(b)
    got = _resolved(b, nid, reply)
    names = _names(b, nid)
    lines = []
    for k in _plan_keys(got):
        if k in units and k in names and k not in opened and k not in owed:   # 判定に無い key・番号に無い名前は受け付けの写しの拒否に任せる
            u = units[k]
            lines.append(f"no {names.index(k) + 1} は label={u.get('label')}（disposition={u.get('disposition', '無し')}）"
                         f"で直す対象でない（{k[:40]}）")
    return lines


def design_section(b) -> str:
    """事前審査の指示書の頭に貼る節: 独立設計の節（design_only）と、修正案の項目の works の欄の節（planmarks.review_section。
    控えが無ければ無し）。欄の控えが凍結の印と食い違えば盤面を止めて（by works:plan）控えを名指す理由の BoardGap"""
    try:
        fields = planmarks.review_section(b)
    except planmarks.FieldsBroken as e:   # 受け付けの後に欄の控えを書き換えた: 書き換えた欄を審査に見せず、盤面を止める
        why = f"修正案の項目の works の欄の控え {planmarks.FIELDS_FILE} が凍結と食い違う: {' '.join(str(e).split())}"
        if not (b.state.get("halted") or b.state.get("stop")):
            b.stop(why, by=STOP_BY)
        raise BoardGap(why) from None
    return design_only(b) + fields


def design_only(b) -> str:
    """独立設計の節だけ（項目の works の欄の節は入れない）。設計が問いは立たないと返した・設計が無い時は、突き合わせない旨と理由。
    同じ run の中の案の直しの事前審査の指示書にも貼る"""
    got, _ = design.made(b.dir)
    if got is None:
        return f"{DESIGN_HEAD}\n\n" + DESIGN_NONE.format(why=design.missing(b))
    if not got["question_stands"]:
        r = got.get("premise_invalid_reason") or got["reason"]
        return f"{DESIGN_HEAD}\n\n" + DESIGN_NOT_STANDS.format(reason=r + design.anchor_note(r))
    return (f"{DESIGN_HEAD}\n\n{DESIGN_ASK}\n\n設計の役の理由: {got['reason']}\n\n=====独立設計ここから=====\n"
            f"{got['design']}\n=====独立設計ここまで=====")


def prior_part(b, role: str) -> str:
    """修正案の役の頭に貼る、前の run で最後まで通らなかった物の節（盤面の根の prior-failures-in.json。manifest の consumes。
    entry.prior_section）。修正案の役だけ（事前審査・独立設計の役には貼らない）。行が無ければ空"""
    return entry.prior_section(b.dir) if role == "plan" else ""


def lib_section(b, repo) -> str:
    """判定の単位のファイルが使うライブラリの今の文書の節（同じ周の 2 つ目の役は盤面の控えを読み、網に出ない）"""
    out = (b.state.get("outputs") or {}).get("p2.diagnose") or {}
    judgment = str(pathlib.Path(b.dir) / out["file"]) if out.get("file") else ""
    files, why = libdocs.unit_files(repo, judgment) if judgment else ([], "判定の出力が盤面に無い")
    text = libdocs.section(b, repo, files)
    return text + (f"\n- 単位のファイルの引き: {why}" if why else "")


def _read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def make_ripple(board_dir, repo, stage: str, replan: str = "") -> dict:
    """ripple の節: stage units は単位の key の名（案に入れてよい単位と必ず入れる単位）を、stage items は盤面の今の周の
    plan-fields.json の項目ごとに波及の一覧を作って今の周に置く（items は RIPPLE_PASS と RIPPLE_LATEST）。返り {ok, ripple_file}
    （作らなかった時は空。replan・欄の控えが無い）。一覧の中の git の誤りは一覧の error に書き、節は落とさない"""
    if replanning(replan):
        return {"ok": True, "ripple_file": ""}
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    if stage == "units":
        owed, opened, _ = plan_slots(b)
        keys = [k for k in _names(b, NODE_OF["plan"]) if k in owed | opened]
        path, doc = b.work(RIPPLE_UNITS), ripple.for_units(repo, keys)
    elif stage == "items":
        fields = planmarks.read(b)
        if not fields:
            return {"ok": True, "ripple_file": ""}
        path, doc = b.work(RIPPLE_PASS.format(k=converge.pass_no(b))), ripple.build(repo, fields)
    else:
        raise BoardGap(f"ripple の stage {stage!r} は units か items")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, doc)
    if stage == "items":
        _write_json(b.work(RIPPLE_LATEST), doc)
    return {"ok": True, "ripple_file": str(path)}


def replan_ripple(b, repo) -> str:
    """案の直しの後の波及の一覧: 直した項目を差し替えた今の周の欄（core の replan.revised_fields）で一覧を作り直し、RIPPLE_REPLAN に
    置いてそのパスを返す（2 回目の修正の段が 1 回目の案の一覧を使い回さないように）。RIPPLE_LATEST は 1 回目の include の物で、
    盤面の柵は周の公開の名の書き手を 1 つにするので上書きしない。直した項目が無ければ何も書かずに空。b は dir・round・work だけを使う"""
    fields = replan_mod.revised_fields(b, repo)
    if not fields:
        return ""
    doc = ripple.build(repo, fields)
    path = b.work(RIPPLE_REPLAN)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, doc)
    return str(path)


def _ripple_of(b, k: int):
    """往復 k の項目ごとの波及の一覧（無ければ None）"""
    return _read_json(b.work(RIPPLE_PASS.format(k=k)))


VERIFY_HEAD = "## 判定の単位の裏取り（判定とは別の目が単位ごとに確かめた申し送り。機械が貼った）"
VERIFY_ASK = ("単位は直す義務で、この申し送りでは減らない。根本でない・場所が違う・証拠が無いと出た単位も、案から外せない（受け付けが"
              "拒む）。そういう単位は本当の根の単位と同じ項目にまとめるか、approach に申し送りへの答え（どう扱うか）を書け。"
              "重複・関わり・順番は項目の組み方と並べ方に使え。確かめられなかった単位は判定のままに読め。")
VERDICT_WORDS = {"root": "根本", "not_root": "根本でない", "unsure": "根本か決められない"}


def _verify_row(u: dict) -> str:
    head = f"- 単位 {u.get('n')} `{u.get('key')}`: "
    if u.get("state") != "checked":
        return head + "確かめられなかった（" + "・".join(str(e) for e in u.get("errors") or []) + "）"
    parts = [VERDICT_WORDS.get(u.get("verdict"), str(u.get("verdict")))]
    if u.get("verdict") == "not_root":
        parts[0] += f"（本当の根: {u.get('real_root')}）"
    parts.append(f"証拠 {'在り' if u.get('evidence_found') else '無し'}（{u.get('evidence')}）")
    parts.append(f"場所 {'合う' if u.get('location_ok') else '違う'}（{u.get('location')}）")
    return head + "・".join(parts) + f"。{u.get('why')}"


def verify_part(verify_file) -> str:
    """修正案の役の頭に貼る判定の単位の裏取りの申し送りの節。入力 verify_file は形 {units: [{n, key, state, verdict,
    evidence_found, evidence, location_ok, location, real_root, why, errors}], synergy: {state, why, duplicates, relations,
    order, errors}} の JSON のパス（出どころは名指さない）。空か文字列 null なら空、読めなければその 1 行"""
    path = _given(verify_file)
    if not path:
        return ""
    doc = _read_json(pathlib.Path(path))
    if not isinstance(doc, dict) or not isinstance(doc.get("units"), list):
        return f"{VERIFY_HEAD}\n\n申し送りのファイル {path} が読めない（判定のままに読め）。"
    lines = [VERIFY_HEAD, "", VERIFY_ASK, ""] + [_verify_row(u) for u in doc["units"] if isinstance(u, dict)]
    syn = doc.get("synergy") if isinstance(doc.get("synergy"), dict) else {}
    if syn.get("state") == "checked":
        lines += ["", f"単位どうしの相乗り: {syn.get('why')}"]
        for label, field in (("重複", "duplicates"), ("関わり", "relations")):
            lines += [f"- {label}: " + "・".join(f"`{k}`" for k in r.get("units") or []) + f"（{r.get('why')}）"
                      for r in syn.get(field) or [] if isinstance(r, dict)]
        lines += [f"- 順番: `{r.get('first')}` を先に、`{r.get('then')}` を後に（{r.get('why')}）"
                  for r in syn.get("order") or [] if isinstance(r, dict)]
    else:
        lines += ["", "単位どうしの相乗り: 確かめられなかった（" + "・".join(str(e) for e in syn.get("errors") or []) + "）"]
    return "\n".join(lines)


def units_ripple_part(b) -> str:
    doc = _read_json(b.work(RIPPLE_UNITS))
    return ripple.units_section(doc) if isinstance(doc, dict) else ""


def _item_rows(b) -> list:
    """今の周の案の項目（盤面の p2.fix_plan の出力の行に、項目の works の欄を重ねた物。番号は並びの順）"""
    doc = b.output_of_round(NODE_OF["plan"], b.round)
    plan = doc.get("plan") if isinstance(doc, dict) else None
    fields = planmarks.read(b) or []
    rows = plan if isinstance(plan, list) else []
    return [{**(r if isinstance(r, dict) else {}), **(f if isinstance(f, dict) else {})}
            for r, f in zip(rows + [{}] * (len(fields) - len(rows)), fields + [{}] * (len(rows) - len(fields)))]


def _item_history(b, unit_keys: list) -> str:
    """前の往復でこの項目に挙がった block と修正案の役の答え（下請けのファイルに貼る）"""
    doc = converge.read(b)
    mine = {str(k) for k in unit_keys}
    lines = []
    replies = [p.get("answers", []) for p in doc["passes"][1:]] + [doc["open"].get("answers", [])]
    for p, answers in zip(doc["passes"], replies):
        units = p.get("face_units") or {}
        keys = [k for k in p.get("blocks", []) if set(units.get(k) or []) & mine or not units.get(k)]
        for f in p.get("faces", []):
            if f.get("key") in keys:
                lines.append(f"- {p['pass']} 往復目の block {f['key']}: {f.get('why')}（{f.get('where')}）")
        lines += [f"  - 修正案の役の答え {a.get('key')}: {a.get('handled')}（{a.get('how')}）" for a in answers
                  if isinstance(a, dict) and a.get("key") in keys]
    if not lines:
        return ""
    return "\n".join([f"## この項目の前の往復の block（{converge.REREVIEW_ASK}）", *lines])


def answers_dir(b, k: int) -> pathlib.Path:
    """往復 k の下請けの答えのファイルの置き場（run ごとの置き場の今の scope の下の ANSWERS_DIR。作らない）"""
    place = pathlib.Path(adapter.run_place_of({"board": str(pathlib.Path(b.dir).resolve())}))
    return (place / b.scope if b.scope else place) / ANSWERS_DIR.format(r=b.round, k=k)


def answer_file(b, k: int, n: int) -> pathlib.Path:
    return answers_dir(b, k) / ANSWER_FILE.format(n=n)


def synergy_file(b, k: int) -> pathlib.Path:
    return answers_dir(b, k) / SYNERGY_FILE


def answer_in(brief: str) -> str:
    """下請けのファイルの文が名指す答えのファイル（ANSWER_AT の句。無ければ空）"""
    head, _, tail = ANSWER_AT.partition("{answer}")
    at = brief.find(head)
    if at < 0:
        return ""
    rest = brief[at + len(head):]
    end = rest.find(tail)
    return rest[:end] if end >= 0 else ""


def _faces_schema() -> tuple[dict, dict]:
    props = output_format("plan-review")["properties"]
    return copy.deepcopy(props["faces"]), copy.deepcopy(props["shrink"])


def item_schema() -> dict:
    """項目の下請けの答えのファイルの型（faces・shrink は事前審査の役の型の物。precedents は開けと言われた先行例の出典の確かめ）"""
    faces, shrink = _faces_schema()
    return {"type": "object", "additionalProperties": False,
            "required": ["item", "checked", "hits", "faces", "shrink", "resolved"],
            "properties": {"item": {"type": "integer", "minimum": 1}, "checked": {"type": "string", "minLength": 10},
                           "hits": copy.deepcopy(converge.HITS_SCHEMA), "faces": faces, "shrink": shrink,
                           "resolved": {"type": "array", "items": {"type": "string"}},
                           "precedents": {"type": "array", "items": {
                               "type": "object", "additionalProperties": False, "required": ["id", "found", "quote"],
                               "properties": {"id": {"type": "string"}, "found": {"type": "boolean"},
                                              "quote": {"type": "string", "minLength": 10}}}}}}


def _precedent_cache(b) -> pathlib.Path:
    return pathlib.Path(b.scope_root) / PRECEDENT_CACHE


def precedent_checks(b) -> dict:
    """控えた先行例の出典の確かめ {出典: {found, quote, round, pass, item}}（無い・読めなければ {}）"""
    doc = _read_json(_precedent_cache(b))
    return doc if isinstance(doc, dict) else {}


def precedent_plan(b, opened: list) -> dict:
    """開いた項目ごとの先行例の出典の行 {項目: [{id, row, cached | None, fetch_by}]}。id は判定の先行例の並びの P<i>。控えの無い
    出典は、それを持つ開いた項目のうち一番小さい番号の項目の下請けが開く（fetch_by）"""
    plan = converge.read(b).get("plan") or []
    rows = (b.record.get("process") or {}).get("precedents") or []
    cache = precedent_checks(b)
    owner: dict = {}
    out: dict = {}
    for n in opened:
        mine = {str(k) for k in plan[n - 1]["unit_keys"]} if 1 <= n <= len(plan) else set()
        for i, r in enumerate(rows, 1):
            if not isinstance(r, dict) or r.get("key") not in mine or r.get("verdict") not in PRECEDENT_VERDICTS:
                continue
            src = str(r.get("source") or "")
            hit = cache.get(src)
            if hit is None:
                owner.setdefault(src, n)
            out.setdefault(n, []).append({"id": f"P{i}", "row": r, "cached": hit, "fetch_by": owner.get(src)})
    return out


def fetch_ids(brief: str) -> list:
    """下請けのファイルが開けと言う先行例の出典の id（PRECEDENT_FETCH の行の頭の `- P<i>`）"""
    return [line.split(":", 1)[0][2:] for line in brief.splitlines()
            if line.startswith("- P") and PRECEDENT_FETCH in line]


def _precedent_part(rows: list, n: int) -> str:
    if not rows:
        return ""
    lines = [PRECEDENT_HEAD, ""]
    for x in rows:
        r = x["row"]
        what = f"{x['id']}: {r.get('source')}（verdict {r.get('verdict')}・単位 {r.get('key')}・判定者の理由 {r.get('reason')}）"
        if x["cached"] is not None:
            c = x["cached"]
            lines.append(f"- {what} — {PRECEDENT_CACHED}: found={str(c.get('found')).lower()}・{c.get('quote')}")
        elif x["fetch_by"] == n:
            lines.append(f"- {what} — {PRECEDENT_FETCH}")
        else:
            lines.append(f"- {what} — {PRECEDENT_OTHER.format(m=x['fetch_by'])}")
    return "\n".join(lines)


def _precedent_gaps(rows: list, n: int, got: dict) -> list[str]:
    want = [x["id"] for x in rows if x["cached"] is None and x["fetch_by"] == n]
    ids = [r.get("id") for r in got.get("precedents") or []]
    return ([f"$.precedents: 先行例の出典 {i} の確かめの行が無い（WebFetch で 1 度開いて {{id, found, quote}} を書け）"
             for i in want if i not in ids]
            + [f"$.precedents: {i} はこの項目の下請けが開く出典でない" for i in ids if i not in want])


def save_precedents(b, plan_rows: dict, answers: dict, k: int) -> None:
    """受けた答えの先行例の出典の確かめを控えに足す（控えに在る出典は書き換えない）"""
    cache = precedent_checks(b)
    for n, got in answers.items():
        by_id = {x["id"]: x["row"] for x in plan_rows.get(n) or []}
        for r in got.get("precedents") or []:
            src = str((by_id.get(r.get("id")) or {}).get("source") or "")
            if src and src not in cache:
                cache[src] = {"found": r.get("found"), "quote": r.get("quote"), "round": b.round, "pass": k, "item": n}
    path = _precedent_cache(b)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, cache)


def synergy_schema() -> dict:
    """相乗りの審査の下請けの答えのファイルの型"""
    faces, _ = _faces_schema()
    return {"type": "object", "additionalProperties": False, "required": ["why", "faces"],
            "properties": {"why": {"type": "string", "minLength": 10}, "faces": faces}}


def _load(path: pathlib.Path, schema: dict) -> tuple:
    """(答え, 誤りの行)。読めない・型に合わない時は誤りの行（型の誤りは engine の validate_schema の $ から始まる行）"""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return None, [f"JSON として読めない（{' '.join(str(e).split())}）"]
    errs = validate_schema(doc, schema)
    return (None, errs) if errs else (doc, [])


def _unit_name(names: list, k) -> str:
    return names[k - 1] if isinstance(k, int) and not isinstance(k, bool) and 1 <= k <= len(names) else str(k)


def carried_hits(b, n: int, rip: dict) -> dict:
    """項目 n の今の往復の覆っていない当たりのうち、前の往復で同じ当たり（種類・場所・名が同じ）に block でない答えが在る物
    {当たりの id: 引き継ぐ答えの行（carried に答えた往復）}"""
    prev = {}
    for h in converge.answered_hits(b, n):
        key = (h.get("kind"), h.get("at"), h.get("name"))
        if key not in prev and h.get("answer") in converge.HIT_ANSWERS:
            prev[key] = h
    out = {}
    for h in ripple.uncovered(rip, n):
        old = prev.get((h["kind"], h["at"], h["name"]))
        if old is not None and old["answer"] != "block":
            out[h["id"]] = {"id": h["id"], "answer": old["answer"], "why": old.get("why", ""), "kind": h["kind"],
                            "at": h["at"], "name": h["name"], "carried": old.get("carried") or old["pass"]}
    return out


def item_answer_gaps(b, n: int, got: dict, rip: dict) -> list[str]:
    """型の合った項目 n の答えの中身の誤り: 覆っていない当たり（前の往復の答えを引き継ぐ物 carried_hits は除く）の全部に
    ちょうど 1 つの答え・block と答えた当たりには block の face・face は項目 n の単位だけを名指す・前の往復の block
    （converge.item_blocks）は resolved か同じ key の face"""
    errs = [] if got.get("item") == n else [f"$.item: {n} でない（{got.get('item')!r}）"]
    want = [h["id"] for h in ripple.uncovered(rip, n)]
    carried = carried_hits(b, n, rip)
    ids = [h.get("id") for h in got["hits"]]
    errs += [f"$.hits: 覆っていない当たり {h} への答えが無い" for h in want if h not in ids and h not in carried]
    errs += [f"$.hits: {h} は波及の一覧の項目 {n} の覆っていない当たりに無い" for h in ids if h not in want]
    errs += [f"$.hits: {h} に答えが {ids.count(h)} つある（1 つだけ）" for h in sorted(set(ids)) if ids.count(h) > 1]
    blocks = converge.block_faces(got)
    if any(h.get("answer") == "block" for h in got["hits"]) and not blocks:
        errs.append("$.faces: 当たりに block と答えたのに severity block の face が無い")
    plan = converge.read(b).get("plan") or []
    mine = {str(k) for k in plan[n - 1]["unit_keys"]} if 1 <= n <= len(plan) else set()
    names = _names(b, NODE_OF["plan-review"])
    for i, f in enumerate(got["faces"]):
        out = [str(k) for k in f["unit_keys"] if _unit_name(names, k) not in mine]
        if out:
            errs.append(f"$.faces[{i}].unit_keys: 項目 {n} の単位でない {out}（項目どうしの穴は相乗りの審査が挙げる。"
                        "unit_keys は項目の unit_keys を字のまま）")
    prev = converge.item_blocks(b, n)
    keys = {f["key"] for f in got["faces"]}
    block_keys = {f["key"] for f in blocks}
    errs += [f"$.resolved: 前の block {k} を resolved に入れるか、同じ key で faces に挙げ直せ"
             for k in prev if k not in got["resolved"] and k not in keys]
    errs += [f"$.resolved: {k} は項目 {n} の前の往復の block に無い" for k in got["resolved"] if k not in prev]
    errs += [f"$.resolved: {k} が resolved と block の face の両方に在る（消えたか残ったかのどちらか 1 つ）"
             for k in got["resolved"] if k in block_keys]
    return errs


def check_item(b, k: int, n: int, rip: dict, pre: list | None = None) -> tuple:
    """(通った答え | None, 誤りの行, ファイルが無いか)。pre は先行例の出典の開き手を決める開いた項目の並び（precedent_plan）"""
    path = answer_file(b, k, n)
    if not path.is_file():
        return None, [], True
    got, errs = _load(path, item_schema())
    if got is not None:
        errs = item_answer_gaps(b, n, got, rip) + _precedent_gaps(precedent_plan(b, [n] if pre is None else pre).get(n) or [], n, got)
    return (None if errs else got), errs, False


def _tree_off(b, k: int, rip: dict) -> bool:
    """項目の控えが無い・支度がこの往復の下請けのファイルを書いていない（入力 review_tree が off。tree_part が置き場 ITEMS_DIR を
    作らない）・1 項目で覆っていない当たりが無く答えのファイルも無い案は木にしない（返答の全体が審査役 1 つの答え）"""
    plan = converge.read(b).get("plan")
    return (not plan or not b.work(ITEMS_DIR.format(k=k)).is_dir()
            or (len(plan) == 1 and converge.open_items(b) == [1] and not ripple.uncovered(rip, 1)
                and not answer_file(b, k, 1).is_file()))


def tree_merge(b, bare: dict, tree: dict, resolved: list) -> dict:
    """事前審査の受け付けの木のまとめ（機械）。束ね役の返答の外した写し bare・束ね役の欄 tree・束ね役の resolved から、
    {review（盤面へ渡す返答）, resolved, synergy（相乗りの審査の face の key）, hits（{項目: 当たりの答え}）, files（往復の控えに
    写す答えのファイル）, gaps（拒む理由の行。在れば他は使わない）} を返す。木にしない案は束ね役の返答のまま"""
    k = converge.pass_no(b)
    rip = _ripple_of(b, k) or {}
    base = {"review": bare, "resolved": resolved, "synergy": [], "hits": {}, "files": {}, "gaps": []}
    if _tree_off(b, k, rip):
        return base
    plan = converge.read(b)["plan"]
    opened = converge.open_items(b)
    gaps, answers = [], {}
    for n in opened:
        got, errs, missing = check_item(b, k, n, rip, opened)
        where = f"項目 {n}（{answer_file(b, k, n)}）"
        if missing:
            gaps.append(f"{where}: 答えのファイルが無い（その項目の下請けを起こせ）")
        gaps += [f"{where}: {e}" for e in errs]
        if got is not None:
            answers[n] = got
    if bare.get("faces") or bare.get("shrink"):
        gaps.append("束ね役の faces・shrink は空にする（項目の穴は下請けの答えのファイルから機械がまとめる。写さない）")
    rows = tree.get(converge.ITEMS)
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    for n in opened:
        mine = [r for r in rows if r.get("item") == n]
        if len(mine) != 1:
            gaps.append(f"束ね役の items に項目 {n} の行が {len(mine)} 行ある（開いた項目ごとに 1 行）")
        elif n in answers:
            keys = [f["key"] for f in converge.block_faces(answers[n])]
            said = [x.get("key") for x in mine[0].get("blocks") or [] if isinstance(x, dict)]
            verdict = converge.VERDICTS[1] if keys else converge.VERDICTS[0]
            if mine[0].get("verdict") != verdict or sorted(map(str, said)) != sorted(keys):
                gaps.append(f"束ね役の items の項目 {n} が答えのファイルと食い違う（ファイルは {verdict}・block "
                            f"{'、'.join(keys) or '無し'}。下請けの要約のとおりに書け）")
    gaps += [f"束ね役の items の項目 {r.get('item')} は審査しない項目（閉じた・保留・案に無い）" for r in rows
             if r.get("item") not in opened]
    syn = None
    if (len(plan) >= 2 and opened and len(answers) == len(opened)
            and not any(converge.block_faces(a) for a in answers.values())):
        path = synergy_file(b, k)
        if not path.is_file():
            gaps.append(f"相乗りの審査（{path}）: 開いた項目の全部が clean の往復は、相乗りの審査の下請けを起こせ")
        else:
            syn, errs = _load(path, synergy_schema())
            gaps += [f"相乗りの審査（{path}）: {e}" for e in errs]
    faces = [f for n in opened if n in answers for f in answers[n]["faces"]] + list((syn or {}).get("faces") or [])
    keys = [f["key"] for f in faces]
    gaps += [f"face の key {key} が 2 つの答えに在る（後に書いた項目の key を変えよ）" for key in sorted(set(keys))
             if keys.count(key) > 1]
    if gaps:
        return {**base, "gaps": gaps}
    now = {f["key"] for f in faces}
    faces += [f for f in converge.carried_notes(b) if f.get("key") not in now]   # suggest は後の往復の返答に残す（修正の段へ）
    review = {**bare, "faces": faces, "shrink": [x for n in opened for x in answers[n]["shrink"]]}
    if not faces and not review.get("faces_none"):
        review["faces_none"] = " / ".join(f"項目 {n}: {answers[n]['checked']}" for n in opened)
    files = {ANSWER_FILE.format(n=n): str(answer_file(b, k, n)) for n in opened}
    if syn is not None:
        files[SYNERGY_FILE] = str(synergy_file(b, k))
    return {"review": review, "resolved": list(dict.fromkeys(x for n in opened for x in answers[n]["resolved"])),
            "synergy": [f["key"] for f in (syn or {}).get("faces") or []],
            "hits": {n: _hit_rows(b, n, rip, answers[n]["hits"]) for n in opened}, "files": files, "gaps": [],
            "precedents": (precedent_plan(b, opened), answers, k)}


def _hit_rows(b, n: int, rip: dict, answered: list) -> list:
    """往復の控えに置く項目 n の当たりの答え（下請けの答えに当たりの種類・場所・名を足し、答えの無い当たりは引き継いだ答え）"""
    where = {h["id"]: {"kind": h["kind"], "at": h["at"], "name": h["name"]} for h in ripple.uncovered(rip, n)}
    got = {h["id"]: {**h, **where.get(h["id"], {})} for h in answered}
    carried = carried_hits(b, n, rip)
    return [got.get(i) or carried[i] for i in where if i in got or i in carried]


def _review_rules(b, main_prompt) -> str:
    """描いた事前審査の指示書の本文のうち RULES_FROM から末尾まで（リポジトリと読む版・審査の決まり・返し方・人の方針・言語）。
    切り出せなければ RULES_MISSING（束ね役の指示書を読ませる）"""
    try:
        body, _ = rolekit.render_body(b, NODE_OF["plan-review"], schema_note=False)
    except BoardGap:
        body = ""
    at = body.find(RULES_FROM)
    return body[at + 1:].strip() if at >= 0 else RULES_MISSING.format(main=main_prompt)


def brief_head(b, main_prompt) -> str:
    """下請けのファイルの共通の頭（全部の項目と相乗りの審査で同じバイト）: 役の定義・関所の項目の決め手・審査の決まり・判定者の
    見立て・独立設計（design_only）・答え方の型"""
    diag = (b.record.get("process") or {}).get("diagnosis") or {}
    framing = {k: diag[k] for k in ("framing", "one_shot") if k in diag}
    return "\n\n".join(x for x in (
        BRIEF_TITLE, SUB_HEAD, gatemarks.HEAD[NODE_OF["plan-review"]], _review_rules(b, main_prompt),
        f"判定者の見立て: {json.dumps(framing, ensure_ascii=False, indent=1)}" if framing else "", design_only(b),
        SUB_FORMAT.format(schema=json.dumps(item_schema(), ensure_ascii=False))) if x)


def _item_units(b, unit_keys) -> list:
    keys = {str(k) for k in unit_keys or []}
    return [{k: u[k] for k in ("key", "label", "disposition", "reason") if k in u}
            for u in b.record.get("units") or [] if u.get("key") in keys]


def _diff_part(b, n: int) -> str:
    """2 往復目から: 前の往復のこの項目の案の行と今の行の差分（unified diff）と DIFF_ASK。前の行が無ければ空（全部を見る）"""
    old = converge.prev_row(b, n)
    plan = converge.read(b).get("plan") or []
    new = plan[n - 1].get("row") if 1 <= n <= len(plan) else None
    if old is None or new is None:
        return ""
    lines = list(difflib.unified_diff(json.dumps(old, ensure_ascii=False, indent=1, sort_keys=True).splitlines(),
                                      json.dumps(new, ensure_ascii=False, indent=1, sort_keys=True).splitlines(),
                                      "前の往復", "今の往復", lineterm="", n=2))
    return f"{DIFF_HEAD}\n\n{DIFF_ASK}\n\n```diff\n" + ("\n".join(lines) or "（変わっていない）") + "\n```"


def _carried_part(b, n: int, rip: dict) -> str:
    rows = carried_hits(b, n, rip)
    if not rows:
        return ""
    return CARRIED_HEAD + "\n\n" + "\n".join(f"- {i}: {h['answer']}（{h['why']}）" for i, h in rows.items())


def _errors_part(n: int, path: pathlib.Path, errs: list) -> str:
    doc = json.dumps({"item": n, "file": str(path), "errors": errs}, ensure_ascii=False, indent=1)
    return f"{ERRORS_HEAD}\n\n前の答え {path} を Read で読み、下の誤りだけを直して同じファイルに書き直せ。\n\n```json\n{doc}\n```"


def tree_part(b, main_prompt: pathlib.Path) -> str:
    """束ね役の頼みの節。開いた項目ごとの下請けのファイルと（項目が 2 つ以上なら）相乗りの審査のファイルを今の往復の
    ITEMS_DIR に書き、その置き場を並べる（下請けの答えの置き場 answers_dir も作る）。下請けのファイルは共通の頭（brief_head）と
    その項目の節（案・単位・波及の一覧・前の往復の block）を字のまま持つ。出し直しでは、答えのファイルが確かめを通った項目を
    済んだ下請けに並べて起こし直させず、通らなかった項目の下請けのファイルに機械の読める誤りの一覧を貼る。項目の控えが無ければ空"""
    rows = _item_rows(b)
    if not rows:
        return ""
    k = converge.pass_no(b)
    doc = _ripple_of(b, k) or {"items": [], "overlaps": [], "error": "波及の一覧の節がこの往復の一覧を置いていない"}
    folder = b.work(ITEMS_DIR.format(k=k))
    folder.mkdir(parents=True, exist_ok=True)
    answers_dir(b, k).mkdir(parents=True, exist_ok=True)
    plan = converge.read(b).get("plan")
    opened = [n for n in (converge.open_items(b) if plan else range(1, len(rows) + 1)) if n <= len(rows)]
    head = brief_head(b, main_prompt)
    pre = precedent_plan(b, opened) if plan else {}
    done, todo, retry = [], [], False
    for n in opened:
        path = folder / f"item-{n}.md"
        got, errs, missing = check_item(b, k, n, doc, opened) if plan else (None, [], True)
        if got is not None:
            done.append(f"- 項目 {n}: {path}")
            continue
        retry = retry or not missing
        it = rows[n - 1]
        body = "\n\n".join(x for x in (
            head, ITEM_HEAD.format(n=n), SUB_ITEM_ASK.format(n=n, answer=answer_file(b, k, n)),
            f"### 項目 {n} の案\n\n```json\n{json.dumps(it, ensure_ascii=False, indent=1)}\n```",
            f"### 項目 {n} の単位（判定）\n\n```json\n{json.dumps(_item_units(b, it.get('unit_keys')), ensure_ascii=False, indent=1)}\n```",
            _precedent_part(pre.get(n) or [], n), ripple.section(doc, n), _carried_part(b, n, doc), _item_history(b, it.get("unit_keys") or []),
            _diff_part(b, n), _errors_part(n, answer_file(b, k, n), errs) if errs else "") if x)
        path.write_text(body + "\n", encoding="utf-8")
        todo.append(f"- 項目 {n}: {path}")
    last = {it["n"]: it for it in (converge.read(b)["passes"][-1].get("items") or [])} if converge.read(b)["passes"] else {}
    parts = [AGG_HEAD, AGG_ASK]
    if done:
        parts.append(DONE_HEAD + "\n" + "\n".join(done))
    if todo:
        parts.append((REDO_HEAD if done or retry else OPEN_HEAD) + "\n" + "\n".join(todo))
    rest = [f"- 項目 {n}（{last[n]['state']}）" for n in range(1, len(rows) + 1) if n not in opened and n in last]
    if rest:
        parts.append("審査しない項目（前の往復で閉じた・保留にした）:\n" + "\n".join(rest))
    parts.append(AGG_MERGE)
    if len(rows) >= 2:
        syn = folder / "synergy.md"
        states = [f"- 項目 {n}（{(last.get(n) or {}).get('state', converge.OPEN)}）: "
                  f"{json.dumps(it, ensure_ascii=False)}" for n, it in enumerate(rows, 1)]
        over = "\n".join(f"- {o['at']}: 項目 {', '.join(map(str, o['items']))}" for o in doc.get("overlaps") or []) or "- 無い"
        syn.write_text("\n\n".join([
            head, "## お前の審査: 相乗りの審査",
            SUB_SYNERGY_ASK.format(answer=synergy_file(b, k), schema=json.dumps(synergy_schema(), ensure_ascii=False)),
            "### 項目の全部（閉じた項目も含む）\n\n" + "\n".join(states),
            "### 項目どうしの重なり（機械が範囲と波及の一覧から引いた）\n\n" + over]) + "\n", encoding="utf-8")
        parts.append(AGG_SYNERGY.format(path=syn))
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 節
def replanning(replan) -> bool:
    """入力 replan が同じ run の中の案の直しの口を指すか（空でも文字列 null でもない）"""
    return bool(_given(replan))


def snap(board_dir, role: str, repo, replan: str = "") -> dict:
    """<役>-snap: 節が待っていれば作業ツリーの写しを置いて go: true。待っていなければ写しを置かずに go: false。修正案の
    行き止まりの盤面（stuck_reason）は止めて go: false。独立設計の役は core の design.snap（起こすかは design.due）。
    直しの役は壁打ちの抜け方が again（converge.held）で p2.fix_plan が待つ時だけ go: true（写しは plan-revise-snapshot.json）。
    replan なら直しの役はいつも go: false（案の直しは壁打ちを回さない。事前審査の穴は関所 replan-gate が項目ごとに読む）、
    ほかの役は core の replan.snap"""
    if role == REVISE_ROLE:
        return {"ok": True, "go": False, "snapshot_file": ""} if replanning(replan) else _revise_snap(board_dir, repo)
    if role == DESIGN_ROLE:
        return design.snap(board_dir, repo)
    if replanning(replan):
        return replan_mod.snap(board_dir, role, repo)
    nid = role_node(role)
    b = entry.open_board(pathlib.Path(board_dir))
    if _pending(b, nid) is None:
        return {"ok": True, "go": False, "snapshot_file": ""}
    if role == "plan" and halt_if_stuck(b):   # 行き止まりの盤面は止めて輪を飛ばす（役を起こさない）
        return {"ok": True, "go": False, "snapshot_file": ""}
    p = entry.snapshot(pathlib.Path(board_dir), snapshot_name(role), pathlib.Path(repo))
    return {"ok": True, "go": True, "snapshot_file": str(p)}


def prep(board_dir, role: str, repo, excluded_file: str = "", replan: str = "", verify_file: str = "",
         review_tree: str = "") -> dict:
    """<役>-prep: 描く → 番号の控え → 起こした印。返り {prompt_file, attempt, out_path, node, already}。
    独立設計の役は core の design.prep（返り {prompt, prompt_file, node, attempt, already, role_def, role_def_missing}。
    道具ゼロなので指示書の本文を返し、commands/r2-design.md が直の参照で貼る）。直しの役は _revise_prep（replan では snap が
    go: false なので届かない）。replan なら core の replan.prep に、頭（head。修正案の頭は planmarks.HEAD を含む）と、事前審査
    なら独立設計の節だけ（design_only）を渡す。verify_file（判定の単位の裏取りの申し送り）は修正案の役の頭にだけ貼る（verify_part。
    直しの役は修正案の役の会話の続きなので、もう読んでいる）。review_tree（入力の切り替えの語。空は on）が off なら事前審査の
    指示書に木の節（tree_part）を載せない（審査役 1 つが案の全体を審査する。受け付けは _tree_off で木のまとめを飛ばす）"""
    tree = script_io.switch_on(review_tree, "review_tree")   # 知らない語は役を問わず指示書を書く前に落とす
    if role == REVISE_ROLE:
        return _revise_prep(board_dir)
    if role == DESIGN_ROLE:
        return design.prep(board_dir, repo)
    nid = role_node(role)
    b = entry.open_board(pathlib.Path(board_dir))
    if replanning(replan):
        return replan_mod.prep(board_dir, role, repo, head=head(role, excluded_file, lib_section(b, pathlib.Path(repo)),
                                                                prior_part(b, role)),
                               design_part=design_only(b) if role == "plan-review" else "")
    if role == "plan":
        why = halt_if_stuck(b)
        if why:   # snap が先に止めて輪を飛ばすので、ここに届くのは配線の誤り。指示書を書かずに 2 で落とす（役を起こさせない）
            raise BoardGap(why)
    main = b.work(rolekit.prompt_name(nid))
    part = "\n\n".join(x for x in ((design_section(b), converge.review_section(b), tree_part(b, main) if tree else "")
                                    if role == "plan-review"
                                    else (prior_part(b, role), structmark.plan_section(b.dir), plan_slots_section(b),
                                          units_ripple_part(b), verify_part(verify_file) if role == "plan" else "")) if x)
    path = rolekit.render_prompt(b, nid, head=head(role, excluded_file, lib_section(b, pathlib.Path(repo)), part))
    ptrs = b.pointer_rows(nid)["pointers"]
    inst = _pending(b, nid)
    m = b.mark_launched(nid, inst.get("attempts", 1), pointers=ptrs)
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid,
            "already": m["already"]}


def _plan_malformed(reply) -> bool:
    """修正案の返答の形が崩れているか（dict でない・plan が list でない・plan の行が dict でない・narrows が list でない。空の narrows は gatemarks と同じく無い物と読む）"""
    if not isinstance(reply, dict) or not isinstance(reply.get("plan"), list):
        return True
    return any(not isinstance(p, dict) or not isinstance(p.get("narrows") or [], list) for p in reply["plan"])


def take(role: str, *, snapshot: str | None = None, settle: bool = True):
    """rolekit.accept_role の take: 関所の項目の行の決め手の欄（gatemarks）を外した返答を entry.take に渡す（写しの型は欄を
    持たない）。決め手は渡す前に盤面の gate-marks.json に置く（事前審査を受けた settle の中で関所が読む）。修正案の narrows の行が
    狭めない案を探した結果を欠けば、盤面へ渡さずに拒む（gatemarks.narrow_gaps）。形の崩れた修正案は前段を飛ばして entry.take に渡す。
    snapshot は entry.take が作業ツリーを比べる写しの名（既定は snapshot_name(role)）、settle はそのまま entry.take へ
    （偽なら盤面は受けるが進めない。事前審査の壁打ち with_converge が往復を記録してから進める）"""
    nid = role_node(role)
    snap_name = snapshot or snapshot_name(role)

    def run(board, reply, repo):
        if role == "plan" and _plan_malformed(reply):   # gatemarks は形の整った返答を前提に読む（変えない部品）。形の拒否は entry.take が言い、再提出の道に乗せる
            return entry.take(pathlib.Path(board), nid, reply, pathlib.Path(repo), snapshot_name=snap_name, settle=settle)
        gaps = gatemarks.narrow_gaps(nid, reply)
        if gaps:
            return {"ok": False, "reason": NO_NARROW_REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
        if role == "plan":
            closed = not_allowed(entry.open_board(pathlib.Path(board)), nid, reply)
            if closed:
                allowed = allowed_nos(entry.open_board(pathlib.Path(board)), nid)
                return {"ok": False, "reason": f"{NOT_OWED_REJECT} {allowed}。外す単位:\n" + "\n".join(f"  - {c}" for c in closed)}
        bare, marks = gatemarks.split(nid, reply)
        gatemarks.save(board, nid, entry.open_board(pathlib.Path(board)).round, marks)
        return entry.take(pathlib.Path(board), nid, bare, pathlib.Path(repo), snapshot_name=snap_name, settle=settle)
    return with_plan_fields(run) if role == "plan" else run


def rewind_roles(b) -> None:
    """壁打ちの again で役の節 2 つ（修正案・事前審査）を同じ周の待ちに戻して settle する（修正案の待ちが出る。事前審査の待ちは
    案を受けるまで出ない）。後ろの節（LATER_NODES）が今の周に受けていれば、戻しは後ろへ伝わらないので戻さずに盤面を止めて
    （by converge.BY。もう止まっていれば止め直さない）BoardGap。機械の節は渡さない（engine が戻さずに落ちる）"""
    later = [n for n in LATER_NODES if n in b.rd["done"]]
    if later:
        why = f"事前審査の壁打ちで修正案と事前審査を戻せない: 後ろの節 {'・'.join(later)} がこの周に受けた後（戻しは後ろへ伝わらない）"
        if not (b.state.get("halted") or b.state.get("stop")):
            b.stop(why, by=converge.BY)
        raise BoardGap(why)
    b.rewind([NODE_OF["plan"], NODE_OF["plan-review"]], by=converge.BY)
    b.settle()


def with_converge(run):
    """事前審査の take の包み（依頼 231 の壁打ち）。run は take("plan-review", settle=False)。どの往復も盤面が settle なしで
    受けてから往復を記録する（again の返答も作業ツリーの比べと盤面の受け付けを通る）:
    1. 形の崩れた返答（dict でない・faces が list でない）は run に渡す（entry.take が拒み、出し直しの道に乗せる）
    2. 壁打ちの欄 resolved と束ね役の欄 items を外し、下請けの答えのファイルを確かめて返答にまとめる（tree_merge。誤りが在れば
       盤面へ渡さずに拒む）。前の往復の block の行き先の欠けと誤り（converge.resolved_gaps。face は名前に戻して読む）が在れば拒む
    3. 外した返答を run に渡す。拒まれたら往復を記録せずに拒否を返す
    4. 受けたら往復を記録する（converge.record_pass。今の周の修正案・事前審査の出力、盤面の根の欄の控え、指示書を写す）。
       記録できなければ盤面を止めて BoardGap（revise_take の答えの控えと同じ）
    5. 抜け方が again なら、今の周の役の節 2 つの拒否の控えを往復の行へ移し（出し直しを往復ごとに数え直す）、役の節 2 つを
       戻す（rewind_roles）。返りの again が真（受け付けは done で、事前審査の輪を抜ける）
    6. ほかの抜け方は settle して（関所が記録を読んで設計だけの行を組む）、その進みを返す"""
    def wrapped(board, reply, repo):
        if not isinstance(reply, dict) or not isinstance(reply.get("faces"), list):
            return run(board, reply, repo)
        bare, resolved = converge.split("plan-review", reply)
        bare, tree = converge.tree_split(bare)
        b0 = entry.open_board(pathlib.Path(board))
        merged = tree_merge(b0, bare, tree, resolved)
        if merged["gaps"]:
            return {"ok": False, "reason": TREE_REJECT + "\n" + "\n".join(f"  - {g}" for g in merged["gaps"])}
        bare, resolved = merged["review"], merged["resolved"]
        named = _resolved(b0, NODE_OF["plan-review"], bare)
        gaps = converge.resolved_gaps(b0, named["faces"], resolved)
        if gaps:
            return {"ok": False, "reason": RESOLVED_REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
        got = run(board, bare, repo)
        if got.get("ok") is not True:
            return got
        b = entry.open_board(pathlib.Path(board))
        plan_out = (b.state["outputs"].get(NODE_OF["plan"]) or {}).get("file")
        files = {"p2.fix_plan.json": str(b.dir / plan_out) if plan_out else "",
                 "p2.plan_review.json": str(b.dir / got["out_file"]),
                 planmarks.FIELDS_FILE: str(b.dir / planmarks.FIELDS_FILE),
                 rolekit.prompt_name(NODE_OF["plan-review"]): str(b.work(rolekit.prompt_name(NODE_OF["plan-review"]))),
                 **merged["files"]}
        try:
            if merged.get("precedents"):
                save_precedents(b, *merged["precedents"])
            row = converge.record_pass(b, named, resolved=resolved, fence=GIVE_UP_AFTER, files=files,
                                       synergy=merged["synergy"], hits=merged["hits"])
        except Exception as e:   # 書けない: 盤面は受けたが往復の行が無い（settle もしない）まま節を抜けさせない
            raise BoardGap(rolekit.halt_unsaved(board, converge.RECORD, e, by=STOP_BY)) from None
        if row["outcome"] == converge.AGAIN:
            converge.stash_rejects(b, rolekit.take_rejects(b, [NODE_OF["plan"], NODE_OF["plan-review"]]))
            rewind_roles(b)
            return {"ok": True, "again": True, "reason": "", "ready": [], "asking": False, "halted": False, "out_file": ""}
        p = b.settle()
        return {**got, "ready": p["ready"], "asking": bool(p["asking"]), "halted": bool(p["halted"])}
    return wrapped


def with_plan_fields(run):
    """修正案の take の包み: 項目の works の欄（planmarks）の欠けと誤りが在れば盤面へ渡さずに拒み（planmarks.REJECT と行）、
    無ければ欄を外した返答を run に渡す。run が受けた（ok）時だけ、欄を盤面の plan-fields.json に控える。控えの周は包みの頭で
    1 度だけ読んだ盤面の周（受けた後に開き直さない）。控えの unit_keys は、返答の no を engine の pointers.resolve で名前に
    戻した物（not_allowed と同じ戻し方。盤面が受けた案と同じ名前）。盤面が受けた後で控えを置けなければ、黙って欄の無い run に
    せず盤面を止めて（by works:plan）控えを名指す理由の BoardGap"""
    def wrapped(board, reply, repo):
        if _plan_malformed(reply):   # 形の崩れた返答は欄を読まずに run へ（run が前段を飛ばして entry.take に拒ませる。再提出の道）
            return run(board, reply, repo)
        gaps = planmarks.gaps(reply, pathlib.Path(repo))
        if gaps:
            return {"ok": False, "reason": planmarks.REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
        if not isinstance(reply, dict):
            return run(board, reply, repo)
        b = entry.open_board(pathlib.Path(board))
        rnd = b.round
        named = _resolved(b, planmarks.NODE, reply)
        _, fields = planmarks.split(named, pathlib.Path(repo))
        bare, _ = planmarks.split(reply, pathlib.Path(repo))
        got = run(board, bare, repo)
        if got.get("ok") is True:
            try:
                planmarks.save(board, rnd, fields, trace=b.trace)
            except Exception as e:   # 書けない・形にできない: 受けた案に欄が無いまま進ませない
                raise BoardGap(rolekit.halt_unsaved(board, planmarks.FIELDS_FILE, e, by=STOP_BY)) from None
            try:   # 項目ごとの壁打ちの控え（閉じた項目の hash を比べる元）
                converge.note_plan(b, named.get("plan") or [])   # 頭で開いた盤面（使うのは周と作業ファイルの置き場だけ）
            except Exception as e:
                raise BoardGap(rolekit.halt_unsaved(board, converge.RECORD, e, by=STOP_BY)) from None
        return got
    return wrapped


def _revise_snap(board_dir, repo) -> dict:
    """直しの役の snap: 壁打ちの抜け方が again で p2.fix_plan が待てば作業ツリーの写しを置いて go: true。ほかは go: false"""
    b = entry.open_board(pathlib.Path(board_dir))
    if converge.held(b) is None or _pending(b, NODE_OF["plan"]) is None:
        return {"ok": True, "go": False, "snapshot_file": ""}
    p = entry.snapshot(pathlib.Path(board_dir), snapshot_name(REVISE_ROLE), pathlib.Path(repo))
    return {"ok": True, "go": True, "snapshot_file": str(p)}


def _revise_prep(board_dir) -> dict:
    """直しの役の prep: 指示書 prompt-plan-revise-<k>.md（読むだけの役の決まり・返した block の節・入れてよい no の節。前の拒否が
    在れば頭の 1 行がその理由のファイルを名指す）を書き、p2.fix_plan に番号の控えつきの起こした印を置く。独立設計の節は貼らない
    （修正案の役の頭と指示書は会話に在る）。返りは修正案の prep と同じ鍵。待ちが無ければ配線の誤り（BoardGap）"""
    nid = NODE_OF["plan"]
    b = entry.open_board(pathlib.Path(board_dir))
    inst = _pending(b, nid)
    section = converge.revise_section(b)
    if inst is None or not section:
        raise BoardGap(f"直しの役（{REVISE_ROLE}）を起こす待ちが無い: 事前審査の壁打ちの抜け方が again でないか、{nid} が待っていない")
    path = b.work(REVISE_PROMPT.format(k=converge.pass_no(b)))
    doc = _ripple_of(b, converge.pass_no(b) - 1)
    path.write_text(rolekit.compose([HEAD["plan"].split("\n\n")[0], section, plan_slots_section(b),
                                     ripple.section(doc) if isinstance(doc, dict) else ""],
                                    reject_file=rolekit.last_reject_file(b, nid)), encoding="utf-8")
    m = b.mark_launched(nid, inst.get("attempts", 1), pointers=b.pointer_rows(nid)["pointers"])
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid,
            "already": m["already"]}


def revise_take():
    """直しの役の take（rolekit.accept_role の take）:
    1. 形の崩れた返答（dict でない）は修正案の口に渡す（entry.take が拒み、出し直しの道に乗せる）
    2. 答えの欄 block_answers を外し（converge.split）、返した block への答えの欠けと誤り（converge.answer_gaps）が在れば
       盤面へ渡さずに拒む（ANSWERS_REJECT と行）
    3. 最後の往復で閉じた項目を変えた・消した直し（converge.closed_gaps。名前に戻して比べる）は拒む（CLOSED_REJECT と行）
    4. 外した返答を修正案の口 take("plan", snapshot=直しの役の写し)（with_plan_fields で包んだ物）に渡す
    5. 盤面が受けたら答えを壁打ちの控えに置く（converge.note_answers。次の往復の行へ移る）。置けなければ盤面を止めて BoardGap"""
    run = take("plan", snapshot=snapshot_name(REVISE_ROLE))

    def wrapped(board, reply, repo):
        if not isinstance(reply, dict):
            return run(board, reply, repo)
        bare, answers = converge.split(REVISE_ROLE, reply)
        b0 = entry.open_board(pathlib.Path(board))
        gaps = converge.answer_gaps(b0, answers)
        if gaps:
            return {"ok": False, "reason": ANSWERS_REJECT + "\n" + "\n".join(f"  - {g}" for g in gaps)}
        if not _plan_malformed(bare):
            closed = converge.closed_gaps(b0, _resolved(b0, NODE_OF["plan"], bare).get("plan") or [])
            if closed:
                return {"ok": False, "reason": CLOSED_REJECT + "\n" + "\n".join(f"  - {g}" for g in closed)}
        got = run(board, bare, repo)
        if got.get("ok") is True:
            try:
                converge.note_answers(entry.open_board(pathlib.Path(board), allow_halted=True), answers)
            except Exception as e:   # 書けない: 答えの無い往復の行にしない
                raise BoardGap(rolekit.halt_unsaved(board, converge.RECORD, e, by=STOP_BY)) from None
        return got
    return wrapped


def converge_check(board_dir, replan: str = "") -> dict:
    """converge-check: 壁打ちの出口。done は「控えの抜け方が again でない」か「今の往復で p2.fix_plan か p2.plan_review の拒否が
    GIVE_UP_AFTER 件に達した」か「盤面が止まっている」（止まった盤面では役が起きず抜け方が again のまま残るので、輪を
    max_iterations で落とさずに抜ける。R50。報告は collect が出す）。止めた盤面でも開ける。
    replan ならいつも 1 往復で done（outcome・record_file は空。同じ周の 1 回目の控えを読まない。案の直しは壁打ちを回さず、
    事前審査の穴は関所 replan-gate が項目ごとに読む）。
    返り {ok: True, done, outcome（控えの語。無ければ ""）, record_file}"""
    if replanning(replan):
        return {"ok": True, "done": True, "outcome": "", "record_file": ""}
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    outcome = converge.read(b)["outcome"]
    gave = any(len(rolekit.rejects(b, nid)) >= GIVE_UP_AFTER for nid in NODE_OF.values())
    stopped = bool(b.state.get("halted") or b.state.get("stop"))
    return {"ok": True, "done": outcome != converge.AGAIN or gave or stopped, "outcome": outcome or "",
            "record_file": str(b.work(converge.RECORD))}


def _accept_args(role: str) -> tuple[str, dict]:
    """役の受け付けの（盤面の節, rolekit.accept_role の引数）。直しの役は盤面の節 p2.fix_plan へ revise_take で渡す（take を
    渡すので作業ツリーの比べは take の中）。事前審査は壁打ちの包み with_converge で渡す"""
    if role == REVISE_ROLE:
        return NODE_OF["plan"], {"take": revise_take()}
    return role_node(role), {"snapshot_name": snapshot_name(role),
                             "take": with_converge(take(role, settle=False)) if role == "plan-review" else take(role)}


def accept_reply(board_dir, role: str, raw: str, repo) -> dict:
    """<役>-accept の本体（rolekit.accept_role。独立設計の役は除く）。main_accept と同じ口を、ラインの試験（tests/linekit.py）が
    子のプロセスを起こさずに回す"""
    nid, kw = _accept_args(role)
    return rolekit.accept_role(pathlib.Path(board_dir), nid, raw, pathlib.Path(repo), give_up_after=GIVE_UP_AFTER, **kw)


def main_accept(role: str, replan: str = "") -> int:
    """<役>-accept の入口（rolekit.main_accept）。独立設計の役は core の design.accept_reply（盤面の節へ渡さない。拒否の理由は
    reason_file に書く）。replan なら core の replan.accept_reply（同じ包み。直しの役は replan では snap が go: false なので
    届かず、役の名の誤りとして落とす）。ほかの役は _accept_args の口"""
    if role == DESIGN_ROLE:
        return rolekit.script_main(lambda board, repo, env: design.accept_reply(board, env["INPUTS_REPLY"], repo),
                                   ("INPUTS_REPLY",), fence=True, take="plan")
    if replanning(replan):
        role_node(role)
        return rolekit.script_main(lambda board, repo, env: replan_mod.accept_reply(board, role, env["INPUTS_REPLY"], repo),
                                   ("INPUTS_REPLY",), fence=True, take="plan")
    nid, kw = _accept_args(role)
    return rolekit.main_accept(nid, give_up_after=GIVE_UP_AFTER, **kw)


def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def collect_reads(board_dir, repo, run_id: str, replan: str = "") -> dict:
    """plan-reads: この周に描いた役ごとに、機械が渡したパス（描いた指示書・方針の文書）を読んだ証拠を reads.collect で集め、
    {役: reads-<役>.json} を reads-plan-block.json に書く。直しの役は今の周に書いた往復ごとの指示書（方針の文書は修正案の
    会話に在るので求めない）。出来事の節の名は READS_LOOP の輪の名で組む（include の名は core の reads.node_here が引く）。受け付けの条件にはしない。返り {ok: True, reads_file}。
    replan なら案の直しの役（直しの役は replan で起きないので数えない）の指示書について、役の名 replan-<役> で
    reads-replan-<役>.json に、索引を replan.READS_INDEX に書く（1 回目の控えを上書きしない）。
    出来事が引ければ（replan でない時）、事前審査の束ね役の Agent の呼びの数・型ごとの数（types）と下請けのファイルの数を trace の
    AGENT_OP に書く"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    events = reads.events_for(run_id) if run_id else None
    policy = _given(b.state["inputs"].get("policy_md"))
    again = replanning(replan)
    files = {}
    for role in ROLES if again else (*ROLES, REVISE_ROLE):
        if role == REVISE_ROLE:
            prompts = [b.work(REVISE_PROMPT.format(k=k)) for k in range(1, converge.pass_no(b) + 1)]
        else:
            prompts = [b.work(rolekit.prompt_name(replan_mod.node_of(role) if again else role_node(role)))]
        must = [str(p) for p in prompts if p.exists()]
        if not must:
            continue
        must += [policy] if policy and role != REVISE_ROLE else []
        name = f"{replan_mod.READS_PREFIX}{role}" if again else role
        got = reads.collect(pathlib.Path(board_dir), name, reads.node_here(READS_LOOP[role], role), must, events,
                            repo=pathlib.Path(repo))
        files[name] = got["reads_file"]
    out = b.work(replan_mod.READS_INDEX if again else READS_INDEX)
    _write_json(out, files)
    if events is not None and not again:   # 束ね役が起こした下請けの数と、機械が書いた下請けのファイルの数（拒まない。測る）
        base = b.work(ITEMS_DIR.format(k=1)).parent
        here = reads.node_here(READS_LOOP["plan-review"], "plan-review")
        types: dict = {}
        for inp in reads.tool_inputs(events, here, "Agent"):
            t = str(inp.get("subagent_type") or "")
            types[t] = types.get(t, 0) + 1
        b.trace(AGENT_OP, launched=reads.tool_count(events, here, "Agent"), types=types,
                item_files=len(list(base.glob("pass-*/item-*.md"))), synergy_files=len(list(base.glob("pass-*/synergy.md"))))
    return {"ok": True, "reads_file": str(out)}


def _first_line(path: str) -> str:
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""
    return (text.strip().splitlines() or [""])[0]


def collect(board_dir, replan: str = "", repo=None) -> dict:
    """出口。役の節がこの周に待ったままなら（3 回とも拒まれた・輪が回らなかった）最後の拒否の理由で盤面を止める。ripple_file は
    最後に作った項目ごとの波及の一覧（RIPPLE_LATEST。無ければ空）。replan なら core の replan.collect（役の諦めは盤面を止めない）で、
    ripple_file は直した項目で作り直した一覧（replan_ripple。repo が無い・直した項目が無ければ空）"""
    if replanning(replan):
        out = replan_mod.collect(board_dir)
        rebuilt = replan_ripple(entry.open_board(pathlib.Path(board_dir), allow_halted=True), repo) if repo else ""
        return {**out, "ripple_file": rebuilt}
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    latest = b.work(RIPPLE_LATEST)
    out = {"ok": True, "plan_file": "", "review_file": "", "asks_human": False, "gate_kinds": [], "reads_file": "",
           "gave_up": False, "reason_file": "", "ripple_file": str(latest) if latest.exists() else ""}
    for role, key in (("plan", "plan_file"), ("plan-review", "review_file")):
        nid = role_node(role)
        inst = b.rd["instances"].get(nid) or {}
        if inst.get("status") == "done":
            out[key] = str(pathlib.Path(board_dir) / b.state["outputs"][nid]["file"])
            continue
        if inst.get("status") != "pending":
            continue
        rows = rolekit.rejects(b, nid)
        rf = rolekit.last_reject_file(b, nid)
        out.update(ok=False, gave_up=len(rows) >= GIVE_UP_AFTER, reason_file=rf)
        why = (f"{nid} の返答が {len(rows)} 回とも受け付けで拒まれた（最後の理由: {_first_line(rf)}。全文 {rf}）" if rows
               else f"{nid} が待ったまま、役の返答を受けていない")
        if not b.state.get("halted"):
            b.stop(why, by=STOP_BY)
        break
    gave = rolekit.given_up_reason(pathlib.Path(board_dir), design.NODE, give_up_after=design.GIVE_UP_AFTER)
    if gave:   # 止めない（事前審査は設計なしで進んだ）。設計が無いことを記録に残し、最後の R2 が目の層で言う
        b.trace(design.MISSING_OP, reason=f"{design.MISSING}: {gave}")
    ph = b.state.get("pending_human") or {}
    out["asks_human"] = bool(ph)
    out["gate_kinds"] = list(ph.get("kinds") or [])
    idx = b.work(READS_INDEX)
    out["reads_file"] = str(idx) if idx.exists() else ""
    return out
