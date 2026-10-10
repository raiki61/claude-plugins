"""修正前の関所（p2.human_gate）の項目の決め手（持ち主 2026-09-28。run 46 の人の答え）。

修正案の狭め（narrows）と事前審査の regression・policy の穴のうち、決め手の出どころ（decided_by）が在り、決め手を当たっても
答えが 1 つに決まらない理由（undecided_because）が空で、柵の印（fences）の無い行は、人に聞かずに通す。判定役の問いの
undecided_because の規律（本流 p2.diagnose.md 8 項）を関所の項目に伸ばし、柵は Renovate の automerge:false と同じ明示の除外。
通した行は出どころつきで state.works.gate_passes に残り、報告の冒頭にいつも並び、最後の関所が開いた時はその文にも並ぶ
（通した行は最後の関所を開く理由に入れない）。欄の無い行は今までどおり聞く。

写しの graph の型は欄を持てない（写しはバイト一致で縛られる）ので、足す・外す・置く・読むの手順は住処 marks（種 gate。役の型の
行にだけ欄を足し、受け付けが盤面へ渡す前に外して盤面の gate-marks.json に置く）に任せる。関所の組み立ては写しの RL の _plan_gate_items を差し替える（entry.CORE_OVERRIDES）。

狭めない案（持ち主 2026-10-01。人が関所で毎回「BASE の動きを残し、黙らずに名指す」形を書き足していたため）: 修正案の役は
narrows を書く前に狭めを避ける形を当たり、無い時だけ narrows に書いて各行に探した結果（NO_NARROW）を書く。欄は決め手の欄と
同じ道で役の型にだけ足して盤面へ渡す前に外し、関所の項目の尾に添えるが、関所を通す条件（decided）には使わない。
- with_marks(node, schema)・split(node, reply)・save(board, node, round, marks): 役の型・受け付け
- narrow_gaps(node, reply): 修正案の narrows の行で狭めない案の欄を欠く・短い行（planblk.take が拒む）
- plan_gate_items(b): 写しの _plan_gate_items の差し替え
- r4_gate_items(rl): 写しの _r4_gate_items の組み手。修正前の関所で人が continue で通した行と種類も本文も同じ行を、修正の後の
  関所（r4.human_gate）で聞き直さず、gate_passes に by human で残す（ADR 0043 の文脈と同じ向き: 答え済みの人の決定を聞き直さない）
- passes(b)・lines(b): 通した行と、最後の関所の文・報告の行

問いの台帳（record.questions）のうち人に聞く状態（検証器の ASKING）の問いも、修正前の関所の項目に 1 件 1 行で載せる（持ち主
2026-09-29。run 119 の人の答え）。人に聞くと名乗る問いが人の口に繋がらないまま、出どころの免除だけが効いて
いたため。この行は決め手の濾しに掛けない。関所の continue はその問いへの答えで、一言が問いに触れなければ修正役は問いの理由の推しで
直す。一言で「保留: <key>」と名指した問いは答えに数えない。無人の run（gatepolicy.unattended）では問いの行を項目に載せない——関所を
開けば無人の殻が stop を返し、問いと関係の無い単位の修正まで飛ぶので、出どころだけを飛ばして報告の冒頭に並べる。関所に載せる問い・
出どころの免除・答えでの戻しは、fork も escalate も同じ asks の 1 つの決まりから作る（免除は works の差し替え
conflict.owed_units_but_asked が withheld で行う。写しの _owed_units は fork だけを外す）。

設計だけの run（入力 design_only）では、修正前の関所を項目の有無に関わらず開け、設計だけの行を 1 行載せる（持ち主 2026-09-30。
調べた改造の案を、直す前の判定・修正案・事前審査・独立設計だけに流して見る）。continue で今どおり修正へ進み、stop で報告へ進む。
この行は決め手の濾しにも無人の濾しにも掛けない（無人の殻は関所で stop を返すので、無人の設計だけの run も止まって報告へ進む）。
直す義務が 0 件の周は関所の節が走らず、修正もしない。設計だけの行の出どころは 2 つ（入力 design_only と、事前審査の壁打ちが
止まった事実＝converge.stuck_reason）。行は design_item の 1 か所で組む（設計だけでない run の止まりは頭を STUCK_ITEM にし、
設計だけの run と名乗らない。種類の kinds は同じ design_only）。
- asks(b)・answered(b, q)・pending(b)・withheld_by(b)・withheld(b): 関所に載せる問い・関所で答えたか・まだ答えていない
  問い・それで直す義務から外す単位と外した問い（conflict.fix_duty が理由に使う）・その単位だけ（義務の数えと held_lines が読む）
- hold_keys(note, keys): 一言の「保留:」から台帳の key を最長一致で拾う（answered が読む）
- unread_holds(note, keys)・unread_hold_lines(b): key を拾えなかった「保留」の文と、拾えた文で並べた項の頭が台帳の key に
  当たらなかった並び（並べ書きの打ち間違い。key の後ろの言葉は並べない）と、報告の冒頭・最後の関所の文に並べる
  「読めなかった保留」の行（直す義務は変えない）
- returned(b): 答えで直す義務に戻る単位（今の周の units に在る物。約束・義務の数えが同じこの集合を読む）
- held_lines(b)・answered_lines(b)・returned_lines(b)・unreturned_lines(b): 最後の関所の文と報告に並べる、関所で答えていない
  聞いたままの問いと戻せなかった単位（保留の件数）・関所で答えた問い（件数に数えない）・修正役に渡す義務に戻った単位・答えたが
  今の周の units に無いので戻せなかった単位
- request_answers(b)・request_answer(b, q)・answer_note(a)・unmatched_answer_lines(b): 依頼の answers（start の控えの欄。依頼者の
  答え）・q の key か出どころ origin と question が字のまま等しく、q だけに当たる答え（answered と _gate_answered が読む。関所の
  continue と同じく答えた扱い。出どころで複数の問いに当たる答えはどれにも答えない）・答えの名乗りの文・答えた行に載らない答えの行
  （台帳のどの問いにも当たらない・複数の問いに当たった・決着済みの問いに当たった。報告の冒頭と最後の関所が名指す。保留の件数に数えない）。
  ANSWERED_HEAD は答えた行の見出し、ANSWER_HOW は保留の行の下に出す答え方の 1 行
- unmeasured(b)・origin_of(b, q)・material_answer(b, name)・measured_materials(b)・material_lines(b): 今の周に測れていない素材
  （not_run・awaiting_human）・答えを結ぶ時の問いの出どころ（台帳の origin。origin を持てない field の問いは、key の頭の測れていない
  素材の名）・素材の名で答えた依頼の答え（問いが立っていなくても当たる）・命令と出力つきで答えた素材（報告が検証器の阻害から外す。
  HAND_CHECKED と名乗る）・答えた行に足す素材の行（利用者の声 10-09 の C2）
- design_only(b)・design_item(b): 設計だけの run か・関所に載せる設計だけの行（載せなければ空）
- PLAIN・named(node)・eye_named(name, status): 関所の文と報告が主語にする平易な名（内部の名は括弧へ。plan・specblk・境の節・報告が使う）
- LANES_NAME・fell_lanes(b): 独立の目の筋が落ちた文の置き場と読み手（blk-eyes が書き、最後の関所の目の行の下に並ぶ）
- quote(question)・QUOTE_NOTE: 盤面の問いの文を引用として載せる行と、関所で添える答え方の読み替えの 1 行
- head3(happened, decide, push)・pushes(texts)・push_of(texts): 関所の文と報告の冒頭 3 行（起きたこと・決めてほしいこと・推し）と、推しを記録から拾う口
- gate_text(asking, *, run_id, node, record_name): 答えを受ける関所の文（修正前の関所と仕様の関所が呼ぶ 1 つの組み立て）
- recommend_gaps(node, reply)・recommend_of(mark): 関所の項目の行の推し recommend {answer, note, why}（実の利用者の run ac9e02ab）の
  形の誤り（受け付けが拒む）と、形の整った推し（人に回す項目の末尾「／推し: …」に載る。照らしの _human_passed はこの尾を外す）
- answer_key(b, q): 依頼の answers でその問いに答える時の question（保留の行の尾 ANSWER_KEY_HEAD と下書きが使う）
- answer_drafts(b)・draft_line(drafts, next_file): 無人の run が関所で止まった項目と、保留のままの台帳の問い・問いの無い測れていない素材への答えの下書き
  （draft: true・source つき。報告が next-request.json の answers に置き、依頼の入口 carry.parts が拒む）と、報告の冒頭 1 の行
グラフの中で決めてよいか（持ち主 2026-10-09 の決め 1。計画 2026-10-09-clean-whole の Task 2.6）: 関所の行を聞かずに通すのは、4 つの軸が
全部揃う時だけ（人がいる run も無人の run も同じ決まり。揃わない行は今どおり人に回し、無人なら止めて答えの下書きを残す）。
自明（決め手の欄が揃い、decided_by の出どころ＝URL・パス:行・依頼の引用「…」・設計の決定の記録のパスが現物に在る。cite.sources_problem）・
世界の解（盤面の根に世界の解の段の控え（worldmark）が在る run は、この軸で見ない——行の外れは下の world_items の項目が 1 度だけ聞く。
控えが無い・段が落ちた run は今どおり world が在るか、決め手が URL）・汚くない（行の単位に構造の目が人に上げた行が無く、汚れる行には修正案の欄 structure の答えが在る）・やりすぎでない
（柵の印が無く、行が修正案の単位の外を名指さない）。揃わない訳は人に回す行の尾「（人に聞く訳: …）」に載る。
- axes(b, mark, units) -> [揃わない軸の訳]: 4 つの軸の確かめ（空ならグラフの中で決める）
世界の解の外れ（計画 2026-10-09-world-solution の W9）: 修正案の欄 structure の世界の解の答えのうち外れ（deviation）は、worldmark.world_ok
が揃わなければ修正前の関所の項目（種類 WORLD_KIND。文は worldmark.gate_line と人に聞く訳）になり、揃えば聞かずに通して通した行に残す。
依頼そのもの（依頼のファイル・目的の文の出典）を出どころにした外れと、web で確かめていない行からの外れは人に回る。人がいる run も
無人の run も同じ（無人なら止めて答えの下書きを残す）。同じ外れを狭め・穴の行の軸と尾には載せない（外れの住処はこの項目の 1 つ）。
構造の目が人に上げた行（structmark の route が人に上げる行）は、修正前の関所の項目になる（種類 DESIGN_KIND。推し＝chosen、捨てた案と
代償＝rejected。DESIGN_HEAD で始まる 1 行。人が continue で答えた同じ文の行は聞き直さない）。
標準ライブラリと core の answer（L1。答えの行）・carry（L1。下書きの印の付け方）・cite（L1。出どころの照らし）・marks（L1）・
converge（L3。事前審査の壁打ち。標準ライブラリだけ）・planmarks（L3）・scopes（L3）・structmark（L3）・worldmark（L3。世界の解の行）だけ。
"""
import json
import pathlib
import re

import answer
import carry   # 下書きの印の付け方（次の run への持ち越しの形の住処）
import cite    # 決め手の出どころが現物に在るかの照らし（食い違いの申し出の引用の照らしと同じ住処）
import gatepolicy   # 無人の run か（人の関所と無人の方針の住処）
import converge
import marks
import planmarks   # 修正案の欄 structure（汚れる行への答え）
import promptsection
import scopes
import startrec   # 始めの記録（盤面の r1/start.json）の読み口
import structmark  # 構造の目の行（汚れる・人に上げる）
import worldmark   # 世界の解の行と、関所の軸「世界の解か」（world_ok）

MARKS_FILE = marks.KINDS["gate"].file
RECOMMEND = "recommend"   # 人に回す行の推し {answer, note, why}（実の利用者の run ac9e02ab。機械が読める推しが無かった）
FIELDS = ("decided_by", "undecided_because", "fences", "world", RECOMMEND)
RECOMMEND_ANSWERS = ("continue", "stop")
RECOMMEND_WORDS = {"continue": "通す", "stop": "止める"}
RECOMMEND_MIN = 4
# 決め手が在っても人に聞く行の印（外への書き込み・取り消せない操作・方針の文書の変更・守り（資格・sandbox）を広げる・web の結果が
# 新しい疑いを出した）
FENCES = ("external_write", "irreversible", "policy_doc", "widen_protection", "web_doubt")
MARK_SCHEMA = {
    "decided_by": {"type": "string",
                   "note": "決め手の出どころ（依頼の引用・URL と節・対象の同じ場面・人の前の決定＝ADR・台帳の行）。無ければ書かない"},
    "undecided_because": {"type": "string",
                          "note": "決め手を当たっても答えが 1 つに決まらない理由。書けないなら空（自明なので人に回さない）"},
    "fences": {"type": "array", "uniqueItems": True, "items": {"type": "string", "enum": list(FENCES)},
               "note": "当たる柵の印。1 つでも在れば決め手が在っても人に聞く"},
    "world": {"type": "string",
              "note": "人に回す行で、世の中の同じ問題の解き方を当たった結果の 1 文（出どころと割れ方、当たらなかったならその理由）"},
    RECOMMEND: {"type": "object", "additionalProperties": False, "required": ["answer", "note", "why"],
                "properties": {"answer": {"type": "string", "enum": list(RECOMMEND_ANSWERS)},
                               "note": {"type": "string", "minLength": RECOMMEND_MIN},
                               "why": {"type": "string", "minLength": RECOMMEND_MIN}},
                "note": "人に回す行の推し: answer＝continue（通す）か stop（止める）・note＝関所の一言に写せる通す範囲と条件か止める理由・"
                        "why＝推す理由。人が答えるまでの下書きで、機械は関所に答えない"},
}
# 狭めない案を探した結果（持ち主の方針 ADR 0002「今ある能力と使い方を減らさない」）。決め手の欄と同じく役の型にだけ足して受け付けが外すが、
# 関所を通す条件（decided）には使わない。修正案の narrows の行では欠け・短いを受け付けが拒み、事前審査の穴では示せる時だけ書く
NO_NARROW = "no_narrow"
NO_NARROW_MIN = 20     # 本流の事前審査が entrance の穴に求める no_add と同じ長さ
NO_NARROW_SCHEMA = {"type": "string", "minLength": NO_NARROW_MIN,
                    "note": "狭めない案（BASE の動きを残し、直したい場合だけ新しい動きを当て、黙らずに名指す形）を探した結果"}
NODES = marks.nodes("gate")
_RULE = ("に、決め手の欄を書け。decided_by＝決め手の出どころ（URL と節・<パス>:<行>（対象の同じ場面・人の前の決定＝ADR）・"
         "設計の決定の記録のパス・依頼の引用「…」（依頼の文を字のまま鉤括弧で）。機械が現物に在るかを照らし、照らせない出どころの行は人に回る）。"
         "undecided_because＝決め手を当たっても答えが 1 つに決まらない理由（書けないなら空にせよ——自明なので人に回さない）。"
         "fences＝当たる柵の印（external_write 外への書き込み・irreversible 取り消せない操作・policy_doc 方針の文書の変更・"
         "widen_protection 守り（資格・sandbox）を広げる・web_doubt web の結果が新しい疑いを出した）。decided_by が在り "
         "undecided_because が空で fences が無く、出どころが現物に在り、世界の解の軸が揃い（頭の『世界の解の行』の節が在る run では、"
         "行の外れは世界の解の外れの項目が 1 度だけ聞き、この行の軸には入れない。節の無い run は world か URL の決め手が在る）、構造の目が人に上げた単位に当たらず、"
         "修正案の単位の外を名指さない行は、修正前の関所で人に聞かずに通り、出どころつきで報告に並ぶ（最後の関所が開けばその文にも）。"
         "決め手が無い・決まらない・柵に当たる行は今までどおり人に聞く。"
         "人に回す前に、世の中が同じ問題をどう解いているかを当たれ——頭の『世界の解の行』の節が在れば、その行（依頼の行ごとの"
         "問題の類・定石・依頼の解き方との比べ）を使え。行の無い問いだけ、標準仕様・著名 OSS・公式の文書の定石を自分で引け。"
         "依頼が示した解き方は決め手にならない（定石と比べて疑う案）。定石で 1 つに決まるなら、その出どころを decided_by に書いて"
         "自分で決めよ。どの行にも "
         "world＝当たった結果の 1 文（出どころと割れ方、当たらなかったならその理由。人の前の決定で決まる行はそう書く）を書け。人に回す行では関所の項目にそのまま載る。"
         "人に回す行には recommend＝お前の推す答え 1 つ {answer: continue（通す）か stop（止める）, note: 関所の一言にそのまま写せる"
         "通す範囲と条件か止める理由, why: 推す理由} も書け。関所の項目の推しとして載り、無人の run が関所で止まった時は次の run の"
         "依頼の下書きの答えの下書きになる（人が見直すまで使われない。機械は関所に答えない）")
_NO_NARROW_PLAN = ("\n\n狭めない案を先に探せ: narrows を書く前に、その狭めを避ける形——直したい場合だけに新しい動きを当て、当てられない"
                   "場合（記録の欄が無い・数えられない・道具が違う等）は BASE の動きを残し、黙らずに報告か標準エラーで名指す形——を"
                   "当たれ。在ればそれを案に採り、その行を narrows に書かない。無い時だけ narrows に書き、各行に "
                   f"{NO_NARROW}＝探した結果（どの狭めない案を当たり、なぜ採れないか。{NO_NARROW_MIN} 字以上）を書け。欠けた行・"
                   "短い行は受け付けが拒み、書いた文は関所の項目にそのまま載る")
_NO_NARROW_REVIEW = ("\n\n狭めない案を添えよ: kind が regression の穴で、BASE の動きを残し、直したい場合だけ新しい動きを当て、"
                     f"当てられない場合は黙らずに名指す形を示せるなら、{NO_NARROW}＝その案（{NO_NARROW_MIN} 字以上）を書け。"
                     "示せなければ書かない。書いた文は関所の項目に添わる")
# 役の指示書の頭に足す文（写しの指示書は欄を知らない）
HEAD = {"p2.fix_plan": "関所の項目の決め手: plan[].narrows の各行" + _RULE + _NO_NARROW_PLAN,
        "p2.plan_review": "関所の項目の決め手: faces のうち kind が regression・policy の各行" + _RULE + _NO_NARROW_REVIEW}
PASSED_BY = "decided"
PASSED_BY_HUMAN = "human"               # 修正の後の関所で、修正前の関所で人が通した行と同じなので聞き直さなかった
GATE_NODE = "p2.human_gate"
R4_GATE_NODE = "r4.human_gate"
# 修正前の関所の行の頭（plan_gate_items と写しの _plan_gate_items が組む形）。r4_gate_items が種類と本文に分ける
NARROW_HEAD = re.compile(r"修正案 \d+ が狭める能力: ")
FACE_HEAD = re.compile(r"事前審査の穴 \[([^\]]+)\] [^\n]*?: ")
CARRIED_HEAD = promptsection.Section("## 直す前の関所で人が通した狭まり（機械が貼った）", source="fn:gatemarks.carried_section")
CARRIED_ASK = ("下の行は、直す前の関所で人が通すと答えた（continue）。同じ能力の消えを capability_inventory.lost に、同じ方針との"
               "ぶつかりを policy_conflicts に書くなら、[ ] の種類（regression は lost・policy は policy_conflicts）に合わせ、本文を"
               "一字も変えずに写せ。通した条件を超える消え・別の能力は自分の言葉で書け")
ASK_HEAD = "問いの台帳の問い"          # 関所の項目の頭。答えの突き合わせもこの頭と key で引く
ASK_KINDS = ("fork", "escalate")       # 関所の項目の kinds（fork の問いと、status が escalate の問い）
HOLD = re.compile(r"保留\s*[:：]\s*([^。；;\n]+)")   # 一言の「保留: <key>」（文の終わりまで。key を並べてよい。key は hold_keys が台帳から拾う）
HOLD_END = re.compile(r"[。；;\n]")   # HOLD が読む文の終わり（unread_holds が一言を文に切る）
KEY_CHAR = re.compile(r"[A-Za-z0-9_-]")   # 台帳の key の一致の前後にこれが続けば、もっと長い key の断片
HOLD_ITEM = re.compile(r"(?:^|[・、,，])\s*([A-Za-z0-9_-]*[A-Za-z0-9][A-Za-z0-9_-]*)")   # 「保留:」に並べた項の頭の key らしい並び
ANSWERED_HEAD = "答えた問い（関所の continue か依頼の answers）"   # 答えた行（answered_lines）の見出し（報告の冒頭と最後の関所）
ANSWER_KEY_HEAD = "答える時の answers の question"   # 保留の行の尾: 依頼の answers に字のまま書く question（answer_key。JSON の文字列で区切る）
HAND_CHECKED = "人が手元で確かめた（実測とは書かない）"   # 命令と出力つきの依頼の答えが当たった測れていない素材の名乗り
ANSWER_HOW = ('答え方: 次の run の依頼を {"findings": [...], "answers": [{"question": "<問いの key か出どころ>", "text": "<答え>"}]} '
              'の形にすれば、その問いを人に聞き直さない（手元で測ったなら "command" と "output" も書く）')
DESIGN_ONLY = "true"                  # 入力 design_only の設計だけの語（entry.DESIGN_ONLY_WORDS）
DESIGN_ONLY_KIND = "design_only"      # 関所の項目の kinds（設計だけの行）
DESIGN_KIND = "design"                # 関所の項目の kinds（構造の目が決めきれなかった設計の問い）
DESIGN_HEAD = "構造の目が決めきれない設計の問い"   # その行の頭
WORLD_KIND = "world"                  # 関所の項目の kinds（世界の解から外れた修正案の項目。worldmark.ANSWER_KEY と同じ語）
_NO_FIX = "修正に進まない（continue で修正へ進む・stop で報告へ。判定・修正案・事前審査・独立設計は報告の見る所に並ぶ）"
DESIGN_ONLY_ITEM = "設計だけの run: " + _NO_FIX
STUCK_ITEM = "事前審査の壁打ちが止まった案: " + _NO_FIX   # 設計だけでない run の止まり（設計だけの run と名乗らない）
ASK_GATE_HEAD = ("判定の役が人に聞くと保留にした問い（問いの台帳）が在る。continue の一言に問いごとに選んだ選択肢を書け。"
                 "一言が問いに触れなければ、修正役はその問いの理由の推しで直す（continue でその問いの出どころ・depends は直す義務に戻る）。"
                 "保留を続けたい問いは一言に「保留: <問いの key>」と書け（複数は「・」で並べてよい。その出どころはこの run では直さず、報告の冒頭に並ぶ）")
# 関所の文と報告が主語にする平易な名（盤面の節 → 流れの図 docs/darkfactory-flow.md の工程の日本語の名）。初めて読む人は盤面の
# 節の名を解けないので、平易な名を主語にし、記録と照らす内部の名は named() が括弧に回す。報告の「見る所」の表もここから引く。
# 図の英語の工程の名はラインの節の id で、層の決まり（下の層はラインの名を書かない）により持たない
PLAIN = {"p2.diagnose": "判定", "p2.fix_plan": "修正案", "p2.plan_review": "事前審査", GATE_NODE: "直す前の関所",
         "p3.fix": "修正", "p3.delta_review": "差分の審査", "p3.delta_fix": "手直し", "p3.delta_review2": "2 回目の審査",
         "p3.delta_fix2": "手直し 2 回目", "p4.ci": "最後のテスト", "r4.human_gate": "独立の目が人に回した問い",
         "spec.approve": "仕様の承認の関所", "r2.design": "独立設計"}
# 独立の目の名 → 何を見る目か（流れの図の 17 項）と、目の判定の状態の語 → 平易な言い方（語は写しの検証器の REVIEW_STATUS）
EYES = {"R1": "直しが最小か・注記が正しいかを見る目", "R2": "独立の設計と構造が合うかを見る目",
        "R3": "前提と全体の筋を見る目", "R4": "依頼の範囲を超えていないかを見る目"}
REVIEW_WORDS = {"pass": "通った", "redesign-needed": "作り直しが要る", "unverifiable": "確かめられない",
                "premise-invalid": "前提が崩れている", "carried_over": "前の周から持ち越した", "not_applicable": "当てはまらない",
                "not_run": "走っていない", "skipped": "軽量で省いた"}
# 素材の状態の語（写しの graph の material.status の enum）→ 平易な言い方。目の判定と共通の語は REVIEW_WORDS から引く
MATERIAL_WORDS = {"found": "赤", "clean": "緑", "awaiting_human": "走らせられず人に諮った",
                  **{k: REVIEW_WORDS[k] for k in ("carried_over", "not_applicable", "not_run")}}
# 修正前のテストの行（entry.baseline_line）が、走らなかった段・走ったかを確かめていない段に添える語
BASELINE_NOT_RUN = "基準の検査が走らなかった（コードの赤ではない）"
BASELINE_UNVERIFIED = "走ったかは確かめていない"
HANDLED_WORDS = {"fixed": "直した", "declared": "直さずに残すと申告した"}   # 手直しの行の handled の語（写しの graph の enum）
# 独立の目のブロックが Archon の節が落ちた筋とその文を置く作業ファイル（入口の周の箱 r<N>/。書き手は blk-eyes の route・collect、
# 読み手は fell_lanes）。ブロックとラインが名前を写し合わないよう、正本はここ
LANES_NAME = "eyes-lanes.json"


# 盤面の問いの文は写しの規則が本線の道具の書き方（continue --note・--detail）で作り、写しは本線とバイト一致で縛られて直せない。
# 関所の文ではそれを引用として置き、この 1 行で読み替える（--detail は答えの行に口が無い）
QUOTE_NOTE = ("（引用の中の continue --note <…> は本線の道具の書き方。この関所では下の continue の行の一言で答える。"
              "--detail（単位を外す）はこの関所に無い——外したい単位と理由を一言に書けば修正役に届くが、直す義務の数からは外れない）")

# 人が読む関所の文と報告の冒頭 3 行の頭（依頼の「冒頭 3 行で完結」。形は BLUF と blk-report の commands/report-write.md の冒頭 3 行）
HAPPENED, DECIDE, PUSH = "起きたこと: ", "決めてほしいこと: ", "推し: "
# 推しは機械が作らない: 判定の役が問いの reason に書いた推しだけを拾い、無ければこの言い方（ask_text の項目と同じ）
NO_PUSH = "判定の役が書いていない"
PUSH_IN = re.compile(r"推し\s*[:：]\s*([^／\n]+)")
PUSH_TAIL = re.compile(r"／推し: [^／\n]*$")   # 関所の項目の末尾の推しの尾（_push が付ける形）
# 関所の項目の種類（写しの RL の human_gate と gatemarks の問いの kinds）→ 平易な言い方
KIND_WORDS = {"regression": "今ある能力を減らす・狭める変更", "policy": "人の方針とぶつかる変更",
              "policy_changed": "人の方針の文書が変わった", ASK_KINDS[0]: "判定の役が人に聞くと保留にした問い",
              ASK_KINDS[1]: "人でないと決められない問い", DESIGN_ONLY_KIND: "修正に進まない行",
              DESIGN_KIND: "構造の目が決めきれなかった設計の問い", WORLD_KIND: "世界の解（定石）から外れる修正案の項目",
              "spec_approval": "仕様（要件と受け入れ条件）の承認", "spec_changed": "承認の後に受け入れ条件のテストが変わった"}


def quote(question) -> list:
    """盤面の問いの文を引用の行（> ）に。文が無ければそう書く"""
    return [f"> {x}".rstrip() for x in str(question or "").splitlines()] or ["> （問いの文が無い）"]


def named(node) -> str:
    """盤面の節を人が読む名に: 「平易な名（記録の名 <節>）」。表に無い節は「盤面の節（記録の名 <節>）」"""
    return f"{PLAIN.get(str(node), '盤面の節')}（記録の名 {node}）"


def eye_named(name: str, status) -> str:
    """独立の目の 1 行の頭: 「何を見る目（R<n>）: 平易な状態（状態の語）」"""
    return f"{EYES.get(name, '独立の目')}（{name}）: {REVIEW_WORDS.get(str(status), '')}（{status}）"


def fell_lanes(b) -> str:
    """今の周の LANES_NAME の文（独立の目の筋が落ちた理由。独立の目の include の scope の根の物も見る: scopes.each の最後）。
    無ければ空"""
    found = scopes.each(b, LANES_NAME)
    try:
        return str(json.loads(found[-1].read_text(encoding="utf-8")).get("why") or "") if found else ""
    except (OSError, ValueError, AttributeError):
        return ""


def pushes(texts) -> str:
    """文の列（問いの理由・関所の項目）に判定の役が書いた推しを「；」で繋ぐ。1 つも無ければ NO_PUSH（機械は推しを作らない）"""
    got = [m.strip() for t in texts for m in PUSH_IN.findall(str(t or "")) if m.strip() and m.strip() != NO_PUSH]
    return "；".join(dict.fromkeys(got)) or NO_PUSH


def head3(happened: str, decide: str, push: str, *, other: str = "") -> list:
    """冒頭 3 行: 起きたこと・決めてほしいこと・推し。決めることが無ければ 2 行目に other（次に大事な事実）を置く
    （「無い」と断る決まり文句は書かない。blk-report の commands/report-write.md の冒頭 3 行の決まり）"""
    return [HAPPENED + happened, DECIDE + decide if decide else other, PUSH + push]


def push_of(texts) -> str:
    """pushes に、推しの無い項目が混じる時の断り（推しの在る項目の推しを全部の項目の推しと読ませない）"""
    got = pushes(texts)
    lacking = [t for t in texts if not PUSH_IN.search(str(t or "")) or PUSH + NO_PUSH in str(t or "")]
    return got + ("（ほかの項目の推しは判定の役が書いていない）" if got != NO_PUSH and lacking else "")


def gate_text(asking: dict, *, run_id: str, node: str, record_name: str) -> str:
    """盤面の問い {node, kinds, question, items, …} を答えを受ける関所の文にする（修正前の関所の line_edge.gate_text と仕様の関所の
    specblk.gate_text が呼ぶ 1 つの組み立て）。冒頭 3 行（起きたこと＝どの関所に何の項目が何件・決めてほしいこと＝通すか
    止めるか・推し＝項目の問いの理由に判定の役が書いた推し）→ 台帳の問いへの答え方（ASK_GATE_HEAD）→ 問いの文の引用と読み替えの
    1 行（QUOTE_NOTE）→ 項目 1 行ずつ → 答え方（answer.line。一言は record_name の記録に残る）。頭は平易な名で、盤面の節の
    名と種類の語は括弧に回す（named）"""
    if not isinstance(asking, dict):
        raise TypeError(f"盤面の問いが dict でない: {type(asking).__name__}")
    kinds = [str(k) for k in asking.get("kinds") or []]
    items = [str(x) for x in asking.get("items") or []]
    what = "・".join(f"{KIND_WORDS.get(k, '人が決める項目')}（{k}）" for k in kinds) or "人が決める項目"
    ask = bool(set(kinds) & set(ASK_KINDS))   # 写しの問いの文は狭め・後退・方針しか名乗らない
    lines = head3(f"{named(asking.get('node') or node)}が開いた。人が決める項目が {len(items)} 件ある——{what}",
                  "下の項目をこのまま通して直しへ進めるか、止めるか（通すなら通す範囲と条件を一言に書く"
                  + ("。台帳の問いには選ぶ選択肢も一言に書く" if ask else "") + "。打つ行は末尾の答え方）",
                  push_of(items)) + [""]
    if ask:
        lines += [ASK_GATE_HEAD, ""]
    lines += ["問いの文（記録のまま引く）:", *quote(asking.get("question")), QUOTE_NOTE, "", f"項目（{len(items)} 件）:"]
    lines += [f"- {x}" for x in items] or ["- （無し）"]
    lines += ["", "答え方（人が決める関所。依頼者に聞いて、その言葉で答える）:",
              f"- 通す: {answer.line(run_id, 'continue', '<通す範囲と条件>')}（一言は run の記録（記録の名 {record_name}）に残り、"
              "修正役に届く）",
              f"- 止める: {answer.line(run_id, 'stop', '<理由>')}（報告は出る）"]
    return "\n".join(lines) + "\n"


def with_marks(node: str, schema: dict) -> dict:
    """役の型に決め手の欄と狭めない案の欄を足した写し（NODES でなければそのまま）。修正案の narrows の行では狭めない案の欄が要る"""
    return marks.add("gate", node, schema, {**MARK_SCHEMA, NO_NARROW: NO_NARROW_SCHEMA},
                     required=(NO_NARROW,) if node == "p2.fix_plan" else ())


def narrow_gaps(node: str, reply: dict) -> list:
    """修正案の narrows の行のうち、狭めない案を探した結果（NO_NARROW）を欠く・NO_NARROW_MIN 字に満たない行の 1 行ずつの文
    （ほかの節は空）"""
    if node != "p2.fix_plan":
        return []
    out = []
    for i, narrows in enumerate(_rows(node, reply)):
        for j, n in enumerate(narrows):
            got = n.get(NO_NARROW) if isinstance(n, dict) else None
            if isinstance(got, str) and len(got.strip()) >= NO_NARROW_MIN:
                continue
            what = n.get("what") if isinstance(n, dict) else n
            out.append(f"plan[{i}].narrows[{j}]（{what}）: {NO_NARROW} が"
                       + (f" {len(got.strip())} 字（{NO_NARROW_MIN} 字以上）" if isinstance(got, str) else "無い（文字列で書く）"))
    return out


def _recommend_gap(got) -> str:
    """recommend の形の誤りの文（正しければ空）"""
    if not isinstance(got, dict):
        return f"{RECOMMEND} が {{answer, note, why}} の object でない"
    extra = sorted(set(got) - {"answer", "note", "why"})
    if extra:
        return f"{RECOMMEND} の知らない欄 {extra}"
    if got.get("answer") not in RECOMMEND_ANSWERS:
        return f"{RECOMMEND}.answer が {'・'.join(RECOMMEND_ANSWERS)} のどれでもない（{got.get('answer')!r}）"
    for k in ("note", "why"):
        if not (isinstance(got.get(k), str) and len(got[k].strip()) >= RECOMMEND_MIN):
            return f"{RECOMMEND}.{k} が {RECOMMEND_MIN} 字に満たない（文字列で書く）"
    return ""


def recommend_gaps(node: str, reply: dict) -> list:
    """関所の項目の行のうち、recommend を書いたが形の崩れた行の 1 行ずつの文（書いていない行は通す。古い返答を拒まない）。
    写しの型は欄を持たず、受け付けが盤面へ渡す前に外すので、形はここで確かめる"""
    if node not in NODES:
        return []
    out = []
    rows = _rows(node, reply)
    pairs = ([(f"plan[{i}].narrows[{j}]", n) for i, narrows in enumerate(rows) for j, n in enumerate(narrows)]
             if node == "p2.fix_plan" else [(f"faces[{j}]", f) for j, f in enumerate(rows)])
    for where, row in pairs:
        if isinstance(row, dict) and RECOMMEND in row:
            gap = _recommend_gap(row[RECOMMEND])
            if gap:
                out.append(f"{where}: {gap}")
    return out


def _rows(node: str, reply: dict) -> list:
    """行の一覧（plan は [[narrow…]…]、plan_review は [face…]）"""
    return marks.rows("gate", node, reply) or []


def split(node: str, reply: dict) -> tuple:
    """（決め手と狭めない案の欄を外した返答の写し, 行と同じ並びの決め手）。NODES でなければ（写し, None）"""
    return marks.split("gate", node, reply, (*FIELDS, NO_NARROW))


def _any(rows) -> bool:
    return any(_any(m) for m in rows) if isinstance(rows, list) else bool(rows)


def save(board, node: str, rnd: int, rows) -> None:
    """盤面の gate-marks.json の節の分を今の返答の分（split の決め手）で置き換える（周を控える）。決め手も狭めない案も 1 つも
    無ければ節の分を消し、ファイルが無ければ作らない（どちらも書かない役の盤面は今までどおりの姿）"""
    p = marks.path_of("gate", board)
    doc = marks.load(p)
    doc = doc if isinstance(doc, dict) else {}
    if _any(rows):
        doc[node] = {"round": rnd, "marks": rows}
    elif node in doc:
        del doc[node]
    else:
        return
    marks.write(p, doc)


def _saved(b, node: str):
    doc = marks.load(marks.path_of("gate", b))
    got = (doc.get(node) if isinstance(doc, dict) else None) or {}
    return got.get("marks") if isinstance(got, dict) and got.get("round") == b.round else None


def _mark(row: dict, saved, *idx) -> dict:
    """行の決め手と狭めない案: 行が欄を持てばそれ、無ければ盤面の控え（idx の位置）"""
    if any(k in row for k in (*FIELDS, NO_NARROW)):
        return {k: row[k] for k in (*FIELDS, NO_NARROW) if k in row}
    try:
        for i in idx:
            saved = saved[i]
    except (TypeError, IndexError, KeyError):
        return {}
    return saved if isinstance(saved, dict) else {}


def decided(mark: dict) -> bool:
    """決め手の出どころが在り、undecided_because が空で、柵の印が無い"""
    return (bool(str(mark.get("decided_by") or "").strip()) and not str(mark.get("undecided_because") or "").strip()
            and not mark.get("fences"))


def _world(mark: dict) -> str:
    """人に回す行の尾: 役が決め手の欄を書いた行だけに、世界の解を当たった結果を付ける（書いていなければそう出す）"""
    if not any(k in mark for k in FIELDS if k != RECOMMEND):
        return ""
    got = str(mark.get("world") or "").strip()
    return f"（世界の解: {got or '役が書いていない'}）"


def _no_narrow(mark: dict) -> str:
    """人に回す行の尾: 役が狭めない案の欄を書いた行だけに、その文を付ける"""
    got = str(mark.get(NO_NARROW) or "").strip()
    return f"（狭めない案: {got}）" if got else ""


def recommend_of(mark: dict):
    """行の推し（形の整った recommend だけ。無い・崩れた物は None。古い盤面の控えは欄を持たない）"""
    got = mark.get(RECOMMEND) if isinstance(mark, dict) else None
    return got if got is not None and not _recommend_gap(got) else None


def _push(mark: dict) -> str:
    """人に回す行の尾: 役が推しを書いた行だけに「／推し: 通す（continue）——<note>（理由: <why>）」（PUSH_IN が拾う形で末尾に置く）"""
    rec = recommend_of(mark)
    if rec is None:
        return ""
    # 推しの文の「／」は「・」に替える（尾の区切り。PUSH_TAIL・PUSH_IN が尾の全文を読む）
    note, why = (_squeeze(rec[k]).replace("／", "・") for k in ("note", "why"))
    return f"／{PUSH}{RECOMMEND_WORDS[rec['answer']]}（{rec['answer']}）——{note}（理由: {why}）"


def _gate_rows(b) -> list:
    """修正前の関所の決め手の濾しに掛ける行 [(kind, 文, 決め手, 節, 単位の key の並び)]（修正案の narrows と事前審査の人に回す種類の穴。
    narrows の単位はその項目の unit_keys、穴の単位は穴の unit_keys）"""
    rows = []
    plan = b.output_of_round("p2.fix_plan", b.round) or {}
    saved = _saved(b, "p2.fix_plan")
    for i, p in enumerate(plan.get("plan") or []):
        keys = [k for k in p.get("unit_keys") or [] if isinstance(k, str)]
        rows += [("regression", f"修正案 {i + 1} が狭める能力: {n['what']}——{n['why']}", _mark(n, saved, i, j), "p2.fix_plan", keys)
                 for j, n in enumerate(p.get("narrows") or [])]
    saved = _saved(b, "p2.plan_review")
    rows += [(f["kind"], f"事前審査の穴 [{f['kind']}] {f['key']}: {f['why']}", _mark(f, saved, j), "p2.plan_review",
              [k for k in f.get("unit_keys") or [] if isinstance(k, str)])
             for j, f in enumerate((b.output_of_round("p2.plan_review", b.round) or {}).get("faces") or [])
             if f["kind"] in b.rules.HUMAN_FACE_KINDS]
    return rows


def _item(text: str, mark: dict, why=()) -> str:
    """人に回す行の関所の項目の文（世界の解・狭めない案・人に聞く訳・推しの尾つき）"""
    tail = f"（人に聞く訳: {' / '.join(why)}）" if why else ""
    return text + _world(mark) + _no_narrow(mark) + tail + _push(mark)


def _plan_keys(b) -> set:
    plan = b.output_of_round("p2.fix_plan", b.round) or {}
    return {k for p in plan.get("plan") or [] if isinstance(p, dict) for k in p.get("unit_keys") or [] if isinstance(k, str)}


def _design_rows(b) -> list:
    """構造の目の行（控えが無い・落ちた周は []）"""
    state = structmark.read(b.dir)
    if not state or state.get("status") != "ok":
        return []
    try:
        return structmark.rows(state.get("design_file") or "")
    except ValueError:
        return []


def _world_rows(b) -> dict | None:
    """{類の id: 世界の解の行}（段が行を出した run だけ。控えが無い・落ちた・読めない run は None＝今どおりの軸）"""
    got = worldmark.stage_rows(b.dir)
    return None if got is None else {r["class_id"]: r for r in got}


def _world_answers(b) -> list:
    """[(項目の番号（1 始まり）, 項目の単位の key の組, 答え)]: 修正案の欄 structure の世界の解の答え（控えが無い・読めない周は []）"""
    try:
        fields = planmarks.read(b)
    except Exception:   # 控えの形の崩れは受け付けと brief が止める（ここは照らさない）
        return []
    plan = (b.output_of_round("p2.fix_plan", b.round) or {}).get("plan") or []
    out = []
    for n, f in enumerate(fields or [], 1):
        keys = set(plan[n - 1].get("unit_keys") or []) if n - 1 < len(plan) and isinstance(plan[n - 1], dict) else set()
        for a in (f.get("structure") if isinstance(f, dict) and isinstance(f.get("structure"), list) else []):
            if isinstance(a, dict) and isinstance(a.get(worldmark.ANSWER_KEY), str):
                out.append((n, keys, a))
    return out


def _cite_check(b):
    """（決め手の文 → 出どころの誤りの 1 文（無ければ ""）の口, 依頼の出どころの組）。出どころの照らしは cite.sources_problem
    （依頼の引用は依頼の文と照らす）。依頼の出どころは依頼のファイルと目的の文の出典（世界の解の外れの決め手にならない物）"""
    req = startrec.read(b.dir).get("request_file") or ""
    quoted = ""
    try:
        quoted = pathlib.Path(req).read_text(encoding="utf-8") if req else ""
        quoted += "\n" + json.dumps(json.loads(quoted), ensure_ascii=False) if quoted else ""   # \u の逃がしを解いた字でも引ける
    except (OSError, UnicodeDecodeError, ValueError):
        pass
    repo = (b.state.get("inputs") or {}).get("cwd") or "."
    roots = [str(pathlib.Path(req).parent) if req else "", str(b.dir)]
    latest = getattr(b, "latest_output", None)
    purpose = latest("p0.purpose") if callable(latest) else None
    own = {req} | {s for s in (purpose or {}).get("source_files") or [] if isinstance(s, str) and s}
    return (lambda text: cite.sources_problem(text, repo, roots, quoted)), {s for s in own if s}


def world_items(b) -> list:
    """世界の解の外れの行 [(文, 決め手の欄の形, 揃わない訳の並び)]（控えの無い run・外れの無い案は []）。揃わない行は修正前の関所の
    項目、揃う行は聞かずに通す行"""
    world = _world_rows(b)
    if world is None:
        return []
    cite_ok, own = _cite_check(b)
    out = []
    for n, _keys, a in _world_answers(b):
        if a.get("follows") is True:
            continue
        row = world.get(a[worldmark.ANSWER_KEY]) or {"class_id": a[worldmark.ANSWER_KEY]}
        ok, why = worldmark.world_ok(a, row, own, cite_ok)
        text = f"修正案 {n} の{worldmark.gate_line(row, a)}"
        out.append((text, {"decided_by": str(a.get("deviation") or ""), "world": worldmark.gate_line(row, a)},
                    [] if ok else [why]))
    return out


def _answered_rows(b) -> set | None:
    """修正案の欄 structure に答えのある汚れる行の単位（控えが読めなければ None＝照らさない。受け付けが欠けを拒む）"""
    try:
        fields = planmarks.read(b)
    except Exception:   # 控えの形の崩れは受け付けと brief が止める（ここは照らさない）
        return None
    if fields is None:
        return None
    return {r.get("row") for f in fields if isinstance(f, dict) for r in f.get("structure") or [] if isinstance(r, dict)}


def axes(b, mark: dict, units) -> list:
    """グラフの中で決めてよいかの 4 つの軸のうち揃わない物の訳（空なら揃う＝聞かずに通す）"""
    out = []
    if not decided(mark):
        return ["決め手の欄が揃わない（decided_by が無いか、undecided_because か柵の印が在る）"]
    got = _cite_check(b)[0](str(mark.get("decided_by") or ""))
    if got:
        out.append(got)
    # 世界の解の段の行の在る run の世界の解の外れは world_items の項目が聞く（ここでは見ない）
    if (_world_rows(b) is None and not str(mark.get("world") or "").strip()
            and not cite.URL.search(str(mark.get("decided_by") or ""))):
        out.append("世界の解を当たった結果（world）が無い")
    ups = {r.get("unit_id") for r in _design_rows(b) if r.get("route") == structmark.ROUTE_UP}
    hit = sorted(set(units) & ups)
    if hit:
        out.append(f"構造の目が人に上げた単位（{'・'.join(hit)}）に当たる")
    dirty = structmark.dirty(b.dir)
    answered = _answered_rows(b)
    if answered is not None:
        miss = sorted(k for k in units if k in dirty and k not in answered)
        if miss:
            out.append(f"構造の目が汚れると見た単位（{'・'.join(miss)}）に修正案の答えが無い")
    outside = sorted(set(units) - _plan_keys(b))
    if outside:
        out.append(f"修正案の単位の外を名指す（{'・'.join(outside)}）")
    return out


def design_items(b) -> list:
    """構造の目が人に上げた行の関所の項目 [(DESIGN_KIND, 文)]（人が continue で答えた同じ文の行は除く）"""
    out = []
    for r in _design_rows(b):
        if r.get("route") != structmark.ROUTE_UP:
            continue
        rej = "・".join(f"{x.get('option')}（代償: {x.get('cost')}）" for x in r.get("rejected") or [] if isinstance(x, dict))
        text = (f"{DESIGN_HEAD} {r.get('unit_id')}: {r.get('undecided_because') or r.get('route_reason') or ''}"
                f"／捨てた案: {rej or '（無し）'}／推し: {r.get('chosen') or '構造の目が書いていない'}"
                + (f"（{r['chosen_reason']}）" if r.get("chosen_reason") else ""))
        if not _continued(b, text):
            out.append((DESIGN_KIND, text))
    return out


def _continued(b, text: str) -> bool:
    return any(isinstance(h, dict) and h.get("node") == GATE_NODE and h.get("answer") == "continue"
               and text in (h.get("asked") or [])
               for h in (b.record.get("process") or {}).get("human_items") or [])


def plan_gate_items(b) -> list:
    """写しの RL の _plan_gate_items の差し替え: 同じ行を組み、決め手の在る行は項目から外して state.works.gate_passes に残す"""
    rows = [(*r, axes(b, r[2], r[4])) for r in _gate_rows(b)]
    _record(b, [(text, m) for _, text, m, _, _, why in rows if not why])
    items = [(kind, _item(text, m, why if decided(m) else ()))
             for kind, text, m, _, _, why in rows if why]
    items += design_items(b)   # 構造の目が決めきれなかった設計の問い（人がいる run も無人の run も同じ）
    devs = world_items(b)      # 世界の解の外れ（揃わない行は人がいる run も無人の run も同じく項目に。揃う行は聞かずに通す）
    _record(b, [(text, m) for text, m, why in devs if not why and m["decided_by"]])
    items += [(WORLD_KIND, item) for text, _, why in devs if why
              for item in [f"{text}（人に聞く訳: {' / '.join(why)}）"] if not _continued(b, item)]
    if not gatepolicy.unattended(b.dir):
        items += [(_ask_kind(q), ask_text(q)) for q in asks(b) if not answered(b, q)]
    item = design_item(b)
    if item and not _design_only_answered(b, item):
        items.append((DESIGN_ONLY_KIND, item))
    return items


def design_only(b) -> bool:
    """run が設計だけの run（start の控えの design_only。読めなければ今どおりの run）"""
    return startrec.read(b.dir).get("design_only") == DESIGN_ONLY


def design_item(b) -> str:
    """関所に載せる設計だけの行。入力 design_only だけなら DESIGN_ONLY_ITEM のまま、事前審査の壁打ちが止まっていれば
    （入力と重なっても 1 行で）尾に止まった理由を付ける。設計だけでない run の止まりは頭を STUCK_ITEM にする。どちらも無ければ空"""
    reason = converge.stuck_reason(b)
    if reason:
        return f"{DESIGN_ONLY_ITEM if design_only(b) else STUCK_ITEM}。理由: {reason}"
    return DESIGN_ONLY_ITEM if design_only(b) else ""


def _design_only_answered(b, item: str) -> bool:
    """修正前の関所がこの設計だけの行（行の全文が同じ物）に continue を受けた（同じ周で関所を評価し直しても 2 度聞かない。
    止まった理由が変われば行が変わるので聞き直す）"""
    return any(isinstance(h, dict) and h.get("node") == GATE_NODE and h.get("answer") == "continue"
               and item in (h.get("asked") or [])
               for h in (b.record.get("process") or {}).get("human_items") or [])


def _asking(b) -> list:
    qs = [q for q in (b.record.get("questions") or []) if isinstance(q, dict)]
    if not qs:
        return []
    states = b.rules.validator_module(b).ASKING
    return [q for q in qs if q.get("status") in states]


def asks(b) -> list:
    """関所に載せる問い: 人に聞く状態の fork と、status が escalate の問い（写しの _precedent_errors と同じ選び方）。直す義務
    から外す（withheld）・戻す（returned）も、この問いだけを見る（写しの _owed_units は fork だけを外すので、works の差し替え
    conflict.owed_units_but_asked がこの選び方で外し直す）"""
    return [q for q in _asking(b) if q.get("kind") == "fork" or q.get("status") == "escalate"]


def _ask_kind(q) -> str:
    return ASK_KINDS[0] if q.get("kind") == "fork" else ASK_KINDS[1]


def _skips(q) -> list:
    return [k for k in [q.get("origin"), *(q.get("depends") or [])] if isinstance(k, str) and k]


def _prefix(q) -> str:
    return f"{ASK_HEAD} {q.get('key')}（"


def ask_text(q) -> str:
    """関所の項目の 1 行: 問い・選択肢・推し（判定の役が reason に書く）・答えが無いと直さない単位"""
    reason = str(q.get("reason") or "")
    return (f"{_prefix(q)}{q.get('kind')}・{q.get('status')}）: {reason}"
            + ("" if "推し" in reason else "／推し: 判定の役が書いていない")
            + f"／選択肢: {'・'.join(str(o) for o in q.get('options') or []) or '（無し）'}"
            + f"／答えが無いと直さない単位: {'・'.join(_skips(q)) or '（無し）'}")


def request_answers(b) -> list:
    """依頼の answers（start の控えの欄。無い・配列でなければ空。dict でない行は読まない）"""
    rows = startrec.read(b.dir).get("answers")
    return [a for a in rows if isinstance(a, dict)] if isinstance(rows, list) else []


def unmeasured(b) -> dict:
    """今の周に測れていない素材 {名: status}: 記録の素材のうち、写しの検証器の表 STATUS で阻害になる status（not_run・
    awaiting_human）の物。記録に素材が無ければ空"""
    mats = (getattr(b, "record", None) or {}).get("materials")
    if not isinstance(mats, dict) or not mats:
        return {}
    table = b.rules.validator_module(b).STATUS
    return {n: m["status"] for n, m in mats.items()
            if isinstance(m, dict) and m.get("status") in table and table[m["status"]].blocks}


def origin_of(b, q) -> str:
    """答えを結ぶ時の問いの出どころ: 台帳の origin。origin が空の問い（field は写しの型で origin を持てない）で、key が今の周に
    測れていない素材の名で始まる（名の直後が終わりか KEY_CHAR でない字）物は、その素材の名（機械が読む出どころ。台帳は変えない。
    判定役は素材から立てる問いの key を素材の名で始める——利用者の run 8cb2ee00 の key「parallel_pr: …」）"""
    got = q.get("origin")
    if isinstance(got, str) and got:
        return got
    key = str(q.get("key") or "")
    return next((n for n in unmeasured(b)
                 if key.startswith(n) and not KEY_CHAR.match(key[len(n):len(n) + 1])), "")


def _hits(b, a) -> list:
    """依頼の答え a が当たる台帳の問い: question と key が字のまま等しい問いが在ればそれだけ、無ければ出どころ（origin_of）が等しい
    問いの全部（同じ単位の fork と escalate のように複数に当たることがある）"""
    qs = [q for q in b.record.get("questions") or [] if isinstance(q, dict)]
    name = a.get("question")
    by_key = [q for q in qs if isinstance(q.get("key"), str) and q.get("key") and q.get("key") == name]
    return by_key or [q for q in qs if name and origin_of(b, q) == name]


def _measured(a: dict) -> bool:
    """命令と出力の両方を持つ答え（人が手元で測った。依頼の入口が片方だけを拒む）"""
    return bool(_squeeze(a.get("command")) and _squeeze(a.get("output")))


def material_answer(b, name: str):
    """依頼の答えのうち question が今の周に測れていない素材の名 name で、台帳の問いに 2 つ以上当たらない最初の物（無ければ None。
    複数の問いに当たる答えは unmatched_answer_lines がどれにも答えないと名指すので、素材にも当てない）"""
    if name not in unmeasured(b):
        return None
    return next((a for a in request_answers(b) if a.get("question") == name and len(_hits(b, a)) <= 1), None)


def measured_materials(b) -> set:
    """依頼の答えが命令と出力つきで答えた、今の周に測れていない素材の名（報告が検証器の阻害から外す。計画 request-answers の
    決め 4 を、命令と出力の在る答えに限って測れなかった素材の代わりにする——実測とは書かず、人が手元で確かめたと名乗る）"""
    if not request_answers(b):
        return set()
    return {n for n in unmeasured(b) if (a := material_answer(b, n)) is not None and _measured(a)}


def material_lines(b) -> list:
    """答えた行（answered_lines）に足す、依頼の答えが当たった測れていない素材の行（1 素材 1 行）。命令と出力が無い答えは、測りの
    代わりにしないと言う"""
    out = []
    for n, st in unmeasured(b).items() if request_answers(b) else ():
        a = material_answer(b, n)
        if a is None:
            continue
        how = (f"{HAND_CHECKED}。検証器の阻害に数えない" if _measured(a)
               else "command と output が無いので測りの代わりにせず、測れていないまま残りに数える")
        out.append(f"素材 {n}（{st}）: {how}——{answer_note(a)}")
    return out


def request_answer(b, q):
    """依頼の答えのうち q だけに当たる（_hits が q 1 つ）最初の物（無ければ None）。複数の問いに当たる答えはどれにも答えない
    （1 つの答えを別の問いの答えとして修正役に渡さない。unmatched_answer_lines が名指す）"""
    return next((a for a in request_answers(b) if (h := _hits(b, a)) and len(h) == 1 and h[0] is q), None)


def answer_note(a: dict) -> str:
    """依頼の答えの名乗り: 依頼者の答え: <text>（手元で測った物は命令と出力を添える。空白は 1 つに詰め、切らない）"""
    text = f"依頼者の答え: {_squeeze(a.get('text'))}"
    if a.get("command"):
        text += f"（人が手元で実行: `{_squeeze(a.get('command'))}`・出力: {_squeeze(a.get('output'))}）"
    return text


def _squeeze(v) -> str:
    return " ".join(str(v or "").split())


DRAFT_HEAD = "人の判断を待つ項目への答えの下書き"


def _draft(question: str, text: str, source: str, note: str = "") -> dict:
    """下書きの 1 行。推しの無い行は text を空にし、人が答えを書く材料を note に置く（draft・source だけを消しても、依頼の入口が
    空の text と知らない欄 note で拒む。置き場の文が答えとして問いに当たらない）"""
    return carry.draft({"question": question, "text": text}, source, note)


def _gate_draft(text: str, mark: dict, node: str) -> dict:
    """関所の項目 1 つの下書き: 推し（recommend）が在ればその答え、無ければ text を空にし、狭めない案・世界の解を note に置く
    （人が答えを書く材料）"""
    who = named(node)
    rec = recommend_of(mark)
    if rec is not None:
        return _draft(text, f"{rec['answer']}: {_squeeze(rec['note'])}（推す理由: {_squeeze(rec['why'])}）", f"{who}の行の {RECOMMEND}")
    parts = [(NO_NARROW, "狭めない案", mark.get(NO_NARROW)), ("world", "世界の解", mark.get("world"))]
    parts = [(k, w, _squeeze(v)) for k, w, v in parts if _squeeze(v)]
    if parts:
        return _draft(text, "", f"{who}の行の {'・'.join(k for k, _, _ in parts)}",
                      "推しを役が書いていない。下の案から人が答えを text に書く: " + "／".join(f"{w}: {v}" for _, w, v in parts))
    return _draft(text, "", f"{who}の行（決め手の欄が無い）", "推しも狭めない案も世界の解も役が書いていない——人が答えを text に書く")


def answer_key(b, q) -> str:
    """依頼の answers でこの問いに答える時の question: 出どころ（origin_of）が今の周に測れていない素材の名で、その名がこの問い
    だけに当たるなら素材の名（短く、字が run ごとに変わらない）、ほかは問いの key"""
    name = origin_of(b, q)
    if name in unmeasured(b) and _hits(b, {"question": name}) == [q]:
        return name
    return str(q.get("key") or "")


def _ask_draft(b, q: dict) -> dict:
    """台帳の問い 1 つの下書き（question は answer_key。見直して draft を外せば次の run の依頼の answers がこの問いに当たる）"""
    key = answer_key(b, q)
    got = [m.strip() for m in PUSH_IN.findall(str(q.get("reason") or "")) if m.strip() and m.strip() != NO_PUSH]
    if got:
        return _draft(key, got[0], f"{ASK_HEAD} {key} の理由の推し（判定の役）")
    opts = "・".join(str(o) for o in q.get("options") or []) or "（無し）"
    return _draft(key, "", f"{ASK_HEAD} {key} の選択肢", f"推しを判定の役が書いていない。選択肢から人が答えを text に書く: {opts}")


def _material_draft(name: str, st: str, reason) -> dict:
    """問いの立っていない測れていない素材の下書き（question は素材の名）。答えは人が手元で確かめて書く"""
    return _draft(name, "", f"素材 {name}（{st}）",
                  f"run の中で測れなかった（{_squeeze(reason) or '理由なし'}）。手元で確かめ、結果を text に、打った命令と出力を "
                  "command と output に書く（両方が在れば、次の run はこの素材を人が手元で確かめた物として残りに数えない）")


def answer_drafts(b) -> list:
    """人の判断を待つ項目を残した時の答えの下書き [{question, text, draft: True, source, note?}]（実の利用者の run ac9e02ab。
    推しの無い行は text が空で、材料が note に在る）: 無人の run だけ、修正前の関所に無人の殻が stop を答えた周の項目ごとに 1 行
    （人の居る run は人が関所で答えた。推しが在ればその答え、無ければ
    狭めない案・世界の解。入力 design_only の設計だけの行は除き、事前審査の壁打ちが止まった行は載せる。控えに当たらない項目は文の
    推しの尾を拾う）と、人の居る run でも無人の run でも、保留のままの台帳の問い（held_lines に並ぶ問い。kind を問わない）ごとに
    1 行（question は answer_key、text は理由の推し）と、問いの立っていない測れていない素材ごとに 1 行（question は素材の名。
    依頼の答えが当たった素材は除く）。人の居る run の下書きは利用者の声 10-09 の C4（下書きが無く、利用者が問いの名を推して書いて
    字が合わなかった）。機械は関所にも問いにも答えない——下書きは依頼の入口が拒むので、人が見直してから使う"""
    out = []
    stops = [h for h in (b.record.get("process") or {}).get("human_items") or []
             if isinstance(h, dict) and h.get("node") == GATE_NODE and h.get("answer") == "stop" and h.get("round") == b.round
             ] if gatepolicy.unattended(b.dir) else []
    rows = {_item(text, m, why if decided(m) else ()): (text, m, node)
            for _, text, m, node, units in _gate_rows(b) for why in [axes(b, m, units)]} if stops else {}
    rows.update({f"{text}（人に聞く訳: {' / '.join(why)}）": (text, {"world": m["world"]}, planmarks.NODE)
                 for text, m, why in world_items(b) if why} if stops else {})
    for a in (stops[-1].get("asked") or []) if stops else []:
        if not isinstance(a, str) or a.startswith(DESIGN_ONLY_ITEM):
            continue
        if a in rows:
            out.append(_gate_draft(*rows[a]))
            continue
        push = PUSH_IN.findall(a) if PUSH_TAIL.search(a) else []
        out.append(_draft(PUSH_TAIL.sub("", a), push[-1].strip(), f"{named(GATE_NODE)}の項目の文の推し") if push
                   else _gate_draft(a, {}, GATE_NODE))
    held = [q for q in _asking(b) if not _gate_answered(b, q)]
    out += [_ask_draft(b, q) for q in held]
    asked = {origin_of(b, q) for q in _asking(b)}
    mats = (b.record.get("materials") or {}) if unmeasured(b) else {}
    out += [_material_draft(n, st, (mats.get(n) or {}).get("reason")) for n, st in unmeasured(b).items()
            if n not in asked and material_answer(b, n) is None]
    return out


def draft_line(drafts: list, next_file: str) -> str:
    """報告の冒頭 1 の 1 行（下書きが無ければ空）"""
    if not drafts:
        return ""
    return (f"{DRAFT_HEAD}: {len(drafts)} 件——次の run の依頼の下書き{f' {next_file}' if next_file else ''} の answers に置いた"
            "（draft: true・出どころ source つき。機械は答えていない。推しの無い行は text が空で、材料は note に在る。見直して、台帳の"
            "問いと素材の行（question が問いの key か素材の名）は採るなら draft と source（と note）を消して text を答えにし、採らないなら行を消す。関所の項目の行（question が関所の項目の文）は次の run の関所の continue の一言の材料で、"
            "依頼ではどの問いにも当たらないので、一言に写してから行を消す）")


def unmatched_answer_lines(b) -> list:
    """答えた行（answered_lines）に載らない依頼の答え（1 件 1 行。黙って答えた扱いにも、黙って捨てもしない）: 台帳のどの問いの
    key にも出どころにも当たらない物・出どころで複数の問いに当たった物（どれにも答えない）・決着済み（人に聞く状態でない）の
    問いに当たった物（答えは直しに使わない）"""
    out = []
    for a in request_answers(b):
        hits, note = _hits(b, a), answer_note(a)
        if not hits and a.get("question") in unmeasured(b):   # 問いの無い測れていない素材に当たった（material_lines が並べる）
            continue
        if not hits:
            out.append(f"依頼の答えに当たる問いが台帳に無い（判定が問いを立てなかったか、字が違う）: {a.get('question')}——{note}")
        elif len(hits) > 1:
            out.append(f"依頼の答えが複数の問いに当たった: {a.get('question')} → {'・'.join(str(q.get('key')) for q in hits)}"
                       f"（どれにも答えた扱いにしない。question に問いの key を書く）——{note}")
        elif hits[0] not in _asking(b):
            out.append(f"決着済みの問いに当たった答え: {a.get('question')} → {hits[0].get('key')}（{hits[0].get('status')}）"
                       f"（答えは直しに使わない）——{note}")
    return out


def answered(b, q) -> bool:
    """依頼の answers がこの問いに当たる（request_answer）か、修正前の関所の continue がこの問いの行を聞いていて、一言が
    「保留: <key>」と名指していない"""
    if request_answer(b, q) is not None:
        return True
    key = str(q.get("key") or "")
    return any(key not in hold_keys(str(h.get("note") or ""), _ledger_keys(b))
               for h in _gate_continues(b) if _asked_in(h, q))


def _gate_continues(b) -> list:
    return [h for h in (b.record.get("process") or {}).get("human_items") or []
            if isinstance(h, dict) and h.get("node") == GATE_NODE and h.get("answer") == "continue"]


def _asked_in(h, q) -> bool:
    return any(isinstance(a, str) and a.startswith(_prefix(q)) for a in h.get("asked") or [])


def unread_holds(note, keys) -> list:
    """一言の文（。；;改行で切る）のうち「保留」を含むのに台帳の key を 1 つも拾えない文の全体（コロン無しの「<key> は保留」・
    打ち間違いの key だけの文）と、key を拾えた文の「保留:」に並べた項の頭で台帳のどの key にも当たらなかった KEY_CHAR の並び
    （並べ書きの打ち間違いの key・台帳に無い key。key の後ろに続く言葉は並べない）。answered はこれを保留と読まないので、問いは答えたものとして扱われる"""
    out = []
    for s in HOLD_END.split(note):
        if "保留" in s:
            found, rest = _hold_scan(s, keys)
            out += rest if found else [s.strip()]
    return out


def unread_hold_lines(b) -> list:
    """報告の冒頭 1 の関所の答えの直後と最後の関所の文に並べる「読めなかった保留」: 一言の断片と、そのせいで答えたものとして
    扱った（推しで直す）問いの key。直す義務は変えない"""
    out = []
    for h in _gate_continues(b):
        frags = unread_holds(str(h.get("note") or ""), _ledger_keys(b))
        if frags:
            took = [str(q.get("key")) for q in asks(b) if _asked_in(h, q) and answered(b, q)]
            out.append(f"読めなかった保留: {'・'.join(f'「{s}」' for s in frags)}（台帳の key を拾えず、保留にならなかった。"
                       f"答えたものとして推しで直す問い: {'・'.join(took) or '無し'}）")
    return out


def _ledger_keys(b) -> set:
    return {str(q.get("key")) for q in b.record.get("questions") or [] if isinstance(q, dict) and q.get("key")}


def hold_keys(note, keys) -> set:
    """一言の「保留:」の後（文の終わりまで）から、台帳の key を最長一致で拾う。区切りの字を推測して割らないので、key の後に
    言葉が続いても key が区切りの字を含んでも読める。前後が KEY_CHAR で続く一致は台帳に無いもっと長い key の断片なので拾わない"""
    return _hold_scan(note, keys)[0]


def _hold_scan(note, keys) -> tuple:
    """hold_keys の拾った key と、並べた項の頭（「保留:」の直後か HOLD_ITEM の並べの字の後）でどの key にも当たらなかった
    KEY_CHAR の並び（unread_holds が見せる）。key の後ろに続く言葉は項の頭でないので見せない"""
    found, rest = set(), []
    for m in HOLD.findall(note):
        i, left = 0, ""
        while i < len(m):
            hit = max((k for k in keys if m.startswith(k, i)
                       and not (i and KEY_CHAR.match(m[i - 1]))
                       and not KEY_CHAR.match(m[i + len(k):i + len(k) + 1])), key=len, default="")
            if hit:
                found.add(hit)
            left += "\0" if hit else m[i]
            i += len(hit) or 1
        rest += HOLD_ITEM.findall(left)
    return found, rest


def _answered_skips(b) -> list:
    """関所で答えた問いごとに (問い, 今の周の units に在る出どころ・depends, 無い出どころ・depends)"""
    keys = {u.get("key") for u in b.record.get("units") or [] if isinstance(u, dict)}
    return [(q, [k for k in _skips(q) if k in keys], [k for k in _skips(q) if k not in keys])
            for q in asks(b) if answered(b, q)]


def pending(b) -> list:
    """関所に載せる問い（asks）のうち、まだ答えていない物（関所を開かない無人の run と「保留: <key>」を含む）"""
    return [q for q in asks(b) if not answered(b, q)]


def withheld_by(b) -> dict:
    """答えが無いので直す義務から外す単位と、外した問い {key: 問い}: まだ答えていない asks の問いの出どころ・depends（fork も
    escalate も。1 単位が複数の問いに当たれば先の問い）。別の問いに答えて戻した単位（returned）は外さない——外した理由
    （conflict.fix_duty）がこの対応を読む"""
    back, out = returned(b), {}
    for q in pending(b):
        for k in _skips(q):
            if k not in back:
                out.setdefault(k, q)
    return out


def withheld(b) -> set:
    """withheld_by の単位だけ——義務の数えと最後の関所の文（held_lines。1 単位が複数の問いに当たれば各問いの行に載せる）が
    同じこの集合を読む"""
    return set(withheld_by(b))


def returned(b) -> set:
    """関所で答えた asks の問い（fork も escalate も）の出どころ・depends のうち今の周の units に在る物（label・disposition を
    問わない）。修正役への約束（returned_lines）・義務の数え（conflict.owed_units_but_asked）が読む 1 つの集合"""
    return {k for _, keep, _ in _answered_skips(b) for k in keep}


def returned_lines(b) -> list:
    """修正役に渡す行: 関所か依頼の answers で答えた問いと、それで直す義務に戻った単位（1 問 1 行。今の周の units に無い単位は
    約束しない）。依頼の答えの問いは推しでなく答えの文で直させる"""
    out = []
    for q, keep, _ in _answered_skips(b):
        if not keep:
            continue
        a = request_answer(b, q)
        how = (f"——答え: {answer_note(a)}" if a is not None else
               f"——一言に案が無ければ問いの理由の推しで直す（問いの理由: {q.get('reason') or ''}）")
        out.append(f"{'依頼' if a is not None else '関所'}で答えた{ASK_HEAD} {q.get('key')} の出どころ・depends は直す義務に戻った"
                   f"（保留の問いの出どころとして飛ばさない）: {'・'.join(keep)}{how}。"
                   "判定者の class_query が無い単位は coverage.how と counts を書け（写しの受け付けが求める）")
    return out


def unreturned_lines(b) -> list:
    """関所で答えたが、今の周の判定の units に無いので直す義務に戻せなかった単位（1 件 1 行）"""
    return [f"関所で答えたが直す単位に入れられなかった: {q.get('key')}・{k}（理由: 今の周の判定に無い）"
            for q, _, gone in _answered_skips(b) for k in gone]


def _gate_answered(b, q) -> bool:
    """保留の行と答えた行の分け目: 依頼の answers が当たるか、関所に載せる問いで答えた（answered と同じ答えを読む）"""
    return request_answer(b, q) is not None or (q in asks(b) and answered(b, q))


def _ledger_line(q, mark: str = "", skip: list | None = None) -> str:
    return (f"{_prefix(q)}{q.get('kind')}・{q.get('status')}{mark}）: {q.get('reason') or ''}"
            + (f"／答えが無いと直さない単位: {'・'.join(skip)}" if skip else ""))


def held_lines(b) -> list:
    """最後の関所の文と報告の冒頭に並べ、「保留にしたままの問い」に数える、台帳で人に聞く状態のまま関所で答えていない問い
    （kind を問わず。1 件 1 行。「答えが無いと直さない単位」は pending の問いの出どころ・depends のうち withheld に在る物だけ）と、
    関所で答えたが直す義務に戻せなかった単位（unreturned_lines。人がまだ決める物なので件数に入れる）"""
    held, kept = pending(b), withheld(b)
    return [_ledger_line(q, skip=[k for k in _skips(q) if k in kept] if q in held else [])
            + f"／{ANSWER_KEY_HEAD}: {json.dumps(answer_key(b, q), ensure_ascii=False)}"
            for q in _asking(b) if not _gate_answered(b, q)] + unreturned_lines(b)


def answered_lines(b) -> list:
    """held_lines と同じ所に別の見出し（ANSWERED_HEAD）で並べ、保留の件数に数えない行: 関所で continue を受けたか、依頼の
    answers が答えた台帳の問い（印は答えの出どころを名乗る）"""
    return [_ledger_line(q, "・" + answer_note(a) if (a := request_answer(b, q)) is not None else "・関所で continue を受けた")
            for q in _asking(b) if _gate_answered(b, q)] + material_lines(b)


def _keep(b, row: dict) -> None:
    kept = b.state.setdefault("works", {}).setdefault("gate_passes", [])
    if row not in kept:
        kept.append(row)


def _record(b, passed) -> None:
    for text, m in passed:
        _keep(b, {"node": GATE_NODE, "round": b.round, "by": PASSED_BY, "item": text, "decided_by": m["decided_by"]})


def _human_passed(b) -> dict:
    """修正前の関所で人が continue で通した行 {(種類, 頭を除いた本文): 答えた周}（台帳の問いの行は数えない）"""
    out = {}
    for h in (b.record.get("process") or {}).get("human_items") or []:
        if not (isinstance(h, dict) and h.get("node") == GATE_NODE and h.get("answer") == "continue"):
            continue
        for a in h.get("asked") or []:
            m = NARROW_HEAD.match(a) if isinstance(a, str) else None
            f = FACE_HEAD.match(a) if isinstance(a, str) and not m else None
            if m or f:   # 推しの尾（_push。いつも末尾）は外して照らす（R4 の自由文に推しまで写させない）
                body = PUSH_TAIL.sub("", a[(m or f).end():])
                out.setdefault(("regression" if m else f.group(1), body), h.get("round"))
    return out


def carried_section(b) -> str:
    """R4（r4.hidden_scope）の指示書の頭に貼る節: 修正前の関所で人が continue で通した行（種類と頭を除いた本文）と、同じ物を書く
    なら本文をそのまま写せという頼み。r4_gate_items は本文の完全一致で照らすので、別の役の自由文を揃える口。無ければ空"""
    rows = [f"- [{kind}] {body}" for kind, body in _human_passed(b)]
    return f"{CARRIED_HEAD}\n\n{CARRIED_ASK}\n\n" + "\n".join(rows) if rows else ""


def r4_gate_items(rl):
    """写しの RL の _r4_gate_items の組み手（board.rl_builder の印で _apply_overrides が開いた RL を渡す）。元の関数の行のうち、
    修正前の関所で人が continue で通した行と種類も頭を除いた本文も同じ物を外し、state.works.gate_passes に by human で残す。
    写しの元は頭込みの文で照らすので、関所ごとに頭の違う同じ狭めを外せない"""
    base, heads = rl._r4_gate_items, {kind: head for kind, _, head in rl.R4_ROWS}

    def items(b):
        passed, out = _human_passed(b), []
        for kind, row in base(b):
            head = heads.get(kind, "")
            key = (kind, row[len(head):]) if row.startswith(head) else None
            if key not in passed:
                out.append((kind, row))
                continue
            _keep(b, {"node": R4_GATE_NODE, "round": b.round, "by": PASSED_BY_HUMAN, "item": row,
                      "passed_at": {"node": GATE_NODE, "round": passed[key]}})
        return out
    return items


def passes(b) -> list:
    return list((b.state.get("works") or {}).get("gate_passes") or [])


def _pass_line(p) -> str:
    if p.get("by") == PASSED_BY_HUMAN:
        at = p.get("passed_at") or {}
        return (f"{named(p['node'])}（周 {p['round']}）で聞き直さなかった——人が通した（周 {at.get('round')}・"
                f"{PLAIN.get(str(at.get('node')), at.get('node'))}）狭まりと同じ: {p['item']}")
    return f"{named(p['node'])}（周 {p['round']}）で決め手が在るので聞かずに通した: {p['item']}（決め手: {p['decided_by']}）"


def lines(b) -> list:
    """最後の関所の文と報告に載せる、決め手で通した行と、修正前の関所で人が通したので聞き直さなかった行（1 件 1 行）"""
    return [_pass_line(p) for p in passes(b)]
