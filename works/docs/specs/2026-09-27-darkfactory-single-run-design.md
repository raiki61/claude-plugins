# darkfactory の 1 回の run を強くする（線 A）の設計（2026-09-26）

状態: **改訂 3 まで反映**（2026-09-27。計画と同じ commit でリポジトリに置いた。盤面の層の設計と台帳の裁定 R25〜R32・BL27・BL28 に合わせて直した「改訂 1」、計画の審査 作業の控え（scratchpad）の `trackA-plan-review.md` に合わせた「改訂 2」、持ち主の朝の 4 つの答えを入れた「改訂 3（持ち主の答え 2026-09-27）」。どれも末尾）。持ち主が原則を決めた 7 項目（1 節）を形にした物。方針「graphloops の review-graph と能力で同等以上の物は推しで決め、能力が下がる物だけを聞く」で決めた所は推しとして書き、聞く物は 12 節に集めた。基準は graphloops の最新の release **0.21.0**（`claude-plugins` の枝 `release/0.21.0`、a1202d0）。0.20.3（fbd40e3）ではない。実装計画は `works/docs/plans/2026-09-27-darkfactory-single-run.md`（裁定 TA1〜TA24 はそちらに在り、この文書より優先する）。
AI 費用 0 の試し P11〜P13・P16 の結果を書き込んだ（〔試P〕。直した段落の末尾に印）。AI を使う分（P11 の AI の節・P13 の `tool_called`・P14・P15）は未確認のまま。〔試し P11〜P16 2026-09-26〕
前の文書: `works/docs/specs/2026-09-26-darkfactory-design.md`（以下「1 本目の仕様」）。共通の土台（盤面の層）の設計は `works/docs/specs/2026-09-26-board-layer-design.md`（以下〔盤〕。枝 `wip/works-board`）で、ここでは作り直さずにその口（`DiskBoard`）を使う。〔輪〕3 節の盤面の設計は〔盤〕に置き換わった。

## 平易版（3 行）

- 持ち主の実際の使い方は「人の依頼 → 判定 → 修正」を 1 回の run で 1 周だけ回し、2 回目は新しい run として回す形である。変異テストはリリースの時にまとめて撃つ。いまの darkfactory はこの 1 周を判定から回せるが、graphloops の review-graph の 1 周より薄い。
- 線 A では、この 1 周に graphloops と同じ工程を足す。判定の前に「依頼の数字や事実を作業ツリーで測り直す役」と「並行 PR との交差の検査」を置く。修正の前に「修正案 → 別の目の事前審査 → 能力を減らす案なら人に聞く」を置く。修正の後は、判定役が書いた数え方で機械が数え直し、修正役が判定に異議を出したら同じ判定役の会話の続きで同じ周のうちに再審する。差分の審査と手直しは 2 往復にする。加えて、止め札、Claude の包み（読んだファイルの記録・書いてはいけない場所の柵・判定役の会話を継ぐ口）を入れる。手厚さは標準だけ（持ち主の決定）。1 本目の「テストの後に人が止められる関所」は残す。
- 入らない物（graphloops の目的の文・P1 の目・R1〜R4・変異の検算・AI が書く報告と初見検査）と、持ち主の決定で下げた物（並行 PR の担当への申し送りを投稿しない）は黙って欠かさない。ラインの節の表と下げた物の一覧に理由つきで書き、毎周の記録の隣と報告の冒頭に機械が出す。

## 0. 略記と出典

- 用語は 1 本目の仕様と〔輪〕の 0 節に揃える（節・ブロック・役・受け付け・関所・盤面・包み・止め札・境の節・切符）。
- **線 A・B・C**: 持ち主の決定（〔台帳〕の最後の順）で並べて回す 3 本の作業。A はこの文書（1 回の run を強くする）、B は周の輪（〔輪〕の 2・4 節）、C は変異の検算のライン（リリースの時にまとめて撃つ）。3 本の前に**共通の土台**（盤面の層。〔盤〕）を作る。
- **1 周の run**: 周の輪を持たず、判定から報告までを 1 回だけ流す darkfactory の run。graphloops で言えば、判定から入る run（`add` で依頼を置いて始める）を `--stop-after-round 1` で回した形。
- **手厚さ**: 入力 `thickness`（軽量・標準・重厚）。受けるのは標準だけ（持ち主の決定 2026-09-27: graph で optional でない節は省かない。4 節）。
- **印（works-node）**: 役の節の `output_format`（JSON Schema）の一番上の `description` に書く 1 行 `works-node: <節の名>[ continue=<継ぐ節の名>][ no-post]`。SDK がこれを argv の `--json-schema` にそのまま載せるので、包みが argv だけでどの節かを見分ける（作業の控え（scratchpad）の `resume-probe-summary.md`。以下〔継試〕）。
- **会話の継ぎ**: 包みが、印に `continue=judge` を持つ節（再審 `p2.rejudge`）を、判定役の Claude の会話の続きとして起こすこと（5.1）。
- **省いた印**: ラインの節の表（`darkfactory/nodes.json`）の absent の行（理由と入る予定）。盤面が `state.works.not_in_line` と毎周の添え書きに出す（〔盤〕4.5）。条件に当たって省いた節は、graphloops と同じく記録の `process.skipped` の `{node, reason}`。
- **境の節**: ブロックとブロックの間に置く、いつも走る script の節（`darkfactory/scripts/edge.py`）。止め札と関所の答えを盤面に書き、次のブロックを回すかを盤面から決める（2 節）。
- 出典の印:
  - 〔輪〕 = `works/docs/specs/2026-09-27-darkfactory-rounds-design.md`（3 版）の節の番号
  - 〔盤〕 = `works/docs/specs/2026-09-26-board-layer-design.md`（盤面の層）の節の番号と裁定 BL1〜BL29
  - 〔計〕 = `works/docs/plans/2026-09-27-darkfactory-single-run.md`（この文書の実装計画。裁定 TA1〜TA24）
  - 〔台帳〕 = `.superpowers/sdd/2026-09-26-darkfactory-v1/progress.md`（Ruling R1〜R32 と Owner decision）
  - 〔0.21〕 = `/Users/p03623/src/claude-plugins` の `release/0.21.0` の `graphloops/`（graph は `graphs/review-loop.json`、規則は `rules/review-loop.py`＝RL、指示書は `prompts/review-loop/`）
  - 〔試P〕 = AI 費用 0 の試し P7〜P13・P16 の要点 作業の控え（scratchpad）の `probes-p7-p16-summary.md`（v0.11.1、2026-09-26）。〔試P: P<n>〕はその節。〔試し P7〜P16 2026-09-26〕
  - 〔手〕 = 作業の控え（scratchpad）の `effort-entry-research.md`、〔包試〕 = 作業の控え（scratchpad）の `claude-adapter-probe.md`、〔隙A〕 = 作業の控え（scratchpad）の `gap-archon-side.md`、〔隙G〕 = 作業の控え（scratchpad）の `gap-graphloops-side.md`
  - 〔継試〕 = 作業の控え（scratchpad）の `resume-probe-summary.md`（包みで後の AI の節が前の AI の節の会話を継ぐ試し。2026-09-27、v0.11.1・SDK 0.3.282・claude 2.1.283。平らな線と `loop_group` の中の両方で動いた）
  - 〔本〕 = 本線の graphloops（`/Users/p03623/src/claude-plugins`）のブロック化の調べ 作業の控え（scratchpad）の `mainline-blocks-survey.md`（2026-09-27）。3-5 = 27a818a（release/0.21.3 の候補）、3-6 = d1b863f（まだ版に無い）、ブロックの宣言 3-7 は作業ツリー wt-blocks7（27a818a の上）
  - 〔答〕 = 持ち主の答え（2026-09-27 の朝）。1: 軽量は案 1（下げない）。2: 並行 PR は案 (a)（読むだけの役・申し送りは報告に）。3: 前提 `p0.premises` を線 A に、目的 `p0.purpose` を線 B に足す。4: 同じ周の再審は review-graph の上位互換にする（包みの会話の継ぎ）
  - 作業の控え（scratchpad） = 設計の会話の一時フォルダ `/private/tmp/claude-1341252503/-Users-p03623-src-claude-plugins-work1/c495892b-6158-4a8d-ad53-ea7a3361cb23/scratchpad`。リポジトリには入っていない（下の「作業の控え（scratchpad）の …」は出典を辿るための控えで、消えていることがある）

## 1. 前提（決まっている物）

1. **範囲は 7 項目＋〔答〕の 3 項目**（持ち主が原則を決めた）: ① 修正案と事前審査と修正前の人の関所（ブロック `blk-plan`）② 修正の受け付けを機械の数え直しに替える ③ 差分の審査と手直しの 2 往復目 ④ 手厚さと入口のつまみ ⑤ Claude の包みと読んだ証拠 ⑥ 外から止める ⑦ 短い報告の節。〔答〕で足した物: ⑧ 前提の実測（`blk-premises`。3.6）⑨ 判定への異議の同じ周の再審（`blk-rejudge` と包みの会話の継ぎ。3.7・5.1）⑩ 並行 PR の検査（`blk-pr`。読むだけの役。3.8）。
2. **共通の土台が先**（〔台帳〕Owner decision: parallel tracks）。盤面 `$ARTIFACTS_DIR/board/` と `DiskBoard`（engine の `Board` を継ぎ、engine と同じ控えと機械の節の順で盤面を進める）は土台が作る（〔盤〕）。線 A は `DiskBoard.begin(..., stop_after_round=1)` で 1 周の run を開き（〔盤〕BL19）、役の返答は `done`、テストは `run_engine("p4.ci")`、人の答えは `answer`、止めるのは `stop` で渡す（〔盤〕8.1）。版を固める・差分を切る・義務を組む・関所の項目・周の記録と検証器・収束は、盤面の `settle` が写しの規則の機械の節で回す。線 A は自前で持たない（〔盤〕BL6）。
3. **写しの取り直しは済んだ**: `works/.shared/core/` は graphloops 0.21.0（a1202d0）の写し（枝 `wip/works-core-021`、先頭 1833773）。`p2.human_gate`・`policy_input.py`・`DELTA_PASSES` を持つ。本線は 0.21.1（0fd3032）を出したが、次の写し直しは本線の 3-5・3-6 が版に入るまで見送り、入ったら 1 回で写す（〔本〕5 の 1。7 節の「写し直しへの依存」）。名前の読み替えは〔盤〕の口と線 A の 1 か所（`refix.passes()` など）で受ける。
4. 1 本目の約束はそのまま守る。YAML は並べるだけ、計算はコード、判断は AI。役の節は `settingSources: []`・sandbox・期限 20 日を持ち、`model:` を書かない（既定の opus。〔台帳〕R18・R22）。役は自分の出し直しの輪の中のただ 1 つの AI の節にする（〔輪〕5.2。〔計〕TA13）。節のスクリプトは PEP 723 の頭を持つ。include の id は重ねない（R17・R19）。
5. 決め方の方針（〔台帳〕Owner policy）: review-graph（0.21.0）と比べて同等以上の物は推しで決め、下がる物は 10 節の表に必ず出す。

## 2. ラインの形

```
launch(関所) → start → pr-checking(blk-pr。任せ先に落ちた時だけ) → premising(blk-premises) → [h-judge] → judging(blk-judge)
   → [h-plan] → planning(blk-plan) → [h-gate] → policy-gate(関所。要るときだけ)
   → [h-fix] → fixing(blk-fix) → [h-rejudge] → rejudging(blk-rejudge。異議が出た時だけ。本線 3-6 の写し直しの後に入る)
   → [h-mid] → mid-testing(blk-tests の mid) → [h-midgate] → mid-gate(中の関所)
   → [h-review] → reviewing(blk-delta) → [h-refix] → refixing(blk-refix) → [h-tests] → testing(blk-tests の final) → report
[h-*] = 境の節（darkfactory/scripts/edge.py を at を替えて使う script の節。写し直しの前は 9、`h-rejudge` が入って 10。when: を持たず、いつも走る）
```

- 境の節がすること（〔計〕TA1。順に）: 盤面が既に止まっていれば `stop`。関所の答えを盤面に書く（`policy-gate` の答えは `b.answer`、中の関所の `stop` は `b.stop`）。止め札を見る。`h-judge` は包みの確かめ（5.1。前提の役の後・判定の前）と、前提の実測が盤面に在るかの確かめもする。`h-plan` は判定の渡し替え（下）と、直す物が無い判定の周の締め（下）もする。`h-rejudge` は判定役の会話の id が在るかを先に確かめる（3.7）。最後に、盤面の `ready`（次に待っている節）から次のブロックを回すかを `go` の 1 つの真偽で返す（`h-judge` は判定のブロック、`h-plan` は `p2.fix_plan`、`h-fix` は `p3.fix`、`h-rejudge` は再審の節のどれか（3.7。写し直しの後）、`h-review` は `p3.delta_review`、`h-refix` は `p3.delta_fix`、`h-tests` は `p4.ci`）。`h-gate` と `h-midgate` は関所を開くかを `ask` と文 `gate_text` で返す。
- `pr-checking` と `premising` の `when:` は `start` の欄（`pr_go`・`premises_go`）だけを読む。`start` は盤面を作った後の `ready` から決める（`p0.parallel_pr` が任せ先に落ちたか・`p0.premises` が待っているか）。
- `when:` と関所の文面は、いつも走る節（`start`・境の節）の欄だけを読む（〔計〕TA1）。盤面が正本なので、分かれ道は engine の条件そのものになる。飛ばされうる節の欄を読んで落ちる道（〔試P: P7〕）は作らない。境の節・`report` など script の節は、飛ばされうる節の出力を全部 `with: {from: …, if_skipped: null}` で受け、届いた文字列 `null` を「開かなかった・走らなかった」と読む〔試P: P16〕。〔試し P7・P16 2026-09-26〕
- 合流する節（境の節・`report`）は `depends_on: [start, <前の境の節>, <前のブロック>]` と `trigger_rule: none_failed_min_one_success` を持つ。前の段が飛ばされても走る（〔輪〕2.1 と同じ作り）。
- **判定は盤面へ渡し替える**（〔計〕TA3）: `blk-judge` は線 B の持ち物で、1 本目の受け付け（偽の盤面）で受けたまま。`h-plan` が `judgment.json` を `done("p2.diagnose", …)` で盤面に渡す。盤面に既に在れば渡さない（線 B の判定 v2 が盤面で受けた後でも同じ線で動く）。盤面が拒めば、書く役を起こす前に理由つきで止める（結末 `stopped_by_line`）。
- **1 本目の関所（テストの後・審査の前）は残す**（〔台帳〕R26。〔計〕TA4）: 修正の後にテストを 1 度走らせ（`blk-tests` の `mid`。盤面の `p4.ci` とは別で、盤面の節に書かない）、中の関所 `mid-gate` を開く。入力 `mid_gate` は `always`（既定。1 本目と同じくいつも開く）か `when_needed`（中のテストが赤か走れなかった時だけ開く）。`stop`・`reject` は `b.stop` で止め、結末 `stopped_by_human`。review-graph に無い止める所なので、1 本目より能力は下がらず、既定のままなら人の手間も 1 本目と同じ。
- **最後のテストは最後の手直しの後**（`blk-tests` の `final` が `run_engine("p4.ci")`）。graphloops の `p4.ci` も修正と手直しの全部の後に走る。
- **直す物が無い判定の run も周を締める**（〔計〕TA6）: `p2.fix_plan` が条件で `na` になった run では、`h-plan` が「直す義務 0 件」の `p3.fix` の空の返答を機械で渡す。盤面が差分の審査を `na` にし、最後のテスト・周の記録と検証器・収束まで回して `report` へ行く。結末は `no_fix_needed`（1 本目と同じ語）。1 本目は修正から後を全部飛ばしていた（R21）が、周の記録と検証器を通る分 review-graph に近い。

## 3. ブロックの約束（入口 → 出口）

### 3.1 blk-plan（新規。R5: `p2.fix_plan`・`p2.plan_review`・`p2.human_gate` の項目組み）

- 入口: `judgment_file`・`base_rev`・`policy_paste`・`policy_path`（どちらも空なら方針なし）。事前審査はいつも回す（手厚さは標準だけ。4 節）。
- 中の節:
  1. `plan-snap`（script）→ `plan-loop`: 修正案の役 `plan`（読むだけ。`[Read, Grep, Glob]`。graphloops の `p2.fix_plan` は「まだ手を動かさない」）＋受け付け `plan-accept`。受け付けは盤面の `done("p2.fix_plan", …)` で、写した `fix_plan_covers_units`（直す義務の単位を全部どれか 1 案に入れる・1 単位 1 案）と 0.21.0 の `p2.fix_plan` の schema（`plan[].unit_keys・approach・adds・removes・shrink_first・narrows`）が盤面の上で当たる。作業ツリーを変えていないことは、1 本目と同じ写しとの比べで、盤面に渡す前に見る（R14。〔計〕TA11）。
  2. `review-snap`（script）→ `plan-review-loop`: 事前審査の役 `plan-review`（読むだけ）＋受け付け `plan-review-accept`（盤面の `done("p2.plan_review", …)`。写した `plan_review_output`: 穴は案の単位を指す・key は一意・入口の穴には `no_add`・何も無ければ `faces_none`）。輪の 1 回目は新しい会話で起きるので、判定役とも修正案の役とも別の目になる（graphloops の `fresh_context: true` に当たる。〔輪〕5.1）。
  3. 人に聞く項目は盤面の機械の節 `p2.human_gate`（写しの `human_gate`・`_plan_gate_items`）が、事前審査を受けた後の `settle` で組む。項目は 3 つ: 修正案の `narrows`（狭める能力）、事前審査の穴のうち `regression`・`policy` の物、方針の文書が固定した版から変わったこと。1 件でも在れば盤面は人に聞いている状態（`pending_human`）で止まる。関所の文は境の節 `h-gate` が盤面の問いから組み、`r1/gate.md` にも置く。ブロックは項目を自前で組まない（〔盤〕8.1）。
  4. `plan-reads`（script。5.2）→ `collect`。
- 出口: `{ok, plan_file, review_file, asks_human, gate_kinds, reads_file}`。
- 修正案・事前審査の役の `output_format` には印（`works-node: plan`・`works-node: plan-review`）を付ける。包みが起動を節の名で記録するため（5.1）。ほかの役も同じ（`fix`・`review`・`refix`・`review2`・`refix2`）。
- 方針の文書（0.21.0 の `policy_md`）: 盤面を作る時に写しの規則の `on_init` が `policy_input.resolve` で場所を決め、版を固め、写しを盤面の `policy/` に置く（〔盤〕1 の 13。`start` は入力 `policy_md` を渡すだけ）。既定は対象リポジトリの `git rev-parse --git-common-dir` の下の `graphloops/policy.md` で、graphloops と同じ文書を読む（持ち主の方針を 2 つの道具で分けない）。役への届け方は 0.21.0 と同じ: 読む役（判定・事前審査・審査）には本文を貼り、書く役（修正案・修正・手直し）にはパスを渡す。`start` が盤面の写しから `policy_paste`（4 万バイトまで。超えたら先頭と続きのパス）と `policy_path` を組み、ブロックの入力で届ける。`blk-judge` には入力 `policy_paste` と指示書の 1 段落だけを足す（節は足さない。〔計〕TA10）。
- **関所 `policy-gate`**: Archon の `approval` に `decisions: [approve, continue, stop, reject]`（`approve` は `continue` と、`reject` は `stop` と同じに扱う。〔台帳〕R32）。`when: $h-gate.output.ask == true`、文言は `$h-gate.output.gate_text`。人は `archon workflow respond <run> continue "<通す範囲と条件>"` か `stop "<理由>"` で答える。`archon workflow reject <run> --reason "<理由>"` でも `stop` と同じになる。答えは次の境の節 `h-fix` が `with: {gate: {from: "$policy-gate.output", if_skipped: null}}` で受け、盤面の `answer("continue" | "stop", 一言)` で渡す（写しの `on_answer_in_round` → `human_gate_answered` が `record.process.human_items` に積み、方針の文書の変化を通したら、その版を固定し直す）。`stop` なら盤面は `halted.by == "answer"` で止まり、`report` が `stopped_by_human` を出す。〔試し P8・P16 2026-09-26〕
  - 確かめたこと〔試P: P16〕: 輪の外の関所でも `respond … continue／stop` でその場で続く。後ろの script の節は `with:` で答えを受ける（丸ごとなら `{"decision":"stop","text":"…"}`）。関所が飛ばされた run では文字列 `null` で届き、落ちない。だから `h-fix` は `"null"` を「関所が開かなかった」と読む。書いていない選択肢は拒まれる。〔試し P16 2026-09-26〕
  - `reject` を足す理由〔試P: P8・P16〕: `decisions` に `reject` が無い関所で `reject` すると、run は `cancelled` で終わり、`report` が走らない。書けば `reject` はほかの選択肢と同じ答えになる。人が反射で `reject` を打っても報告が必ず出る。〔試し P8・P16 2026-09-26〕
- 人の一言は修正役に届ける。境の節 `h-fix` が今の周の `human_items` の一言を並べた文を出し、blk-fix の入力 `human_notes` で指示書に貼る（写しの `p3.fix` も `record.process.human_items` を読む）。

### 3.2 blk-fix（変える。数え直しに替える）

- 受け付けを、今の `fix_plan_covers_units` を変更の行に読み替える形（`accept.py` の `check_fix`）から、盤面の `done("p3.fix", …)` に替える。graph の `p3.fix` の受け付けの検査が写しの `fix_covers_open_units` なので、盤面の上で判定役の `class_query` を修正前の版と修正後の作業ツリーで機械が数え直し、`closure.sites` の数と母数が合わない返答・`coverage_after` が減っていない返答を拒む。修正は判定の後に 1 回だけで、盤面は `stop_after_round=1`。
- この規則が読む物は、盤面が engine と同じ所に持つ（〔盤〕3 節）: 単位と先行例は `record.json`、修正前の版は `state.inputs.review_rev`（`begin` が固める）、事前審査は `out/r1/p2.plan_review.json`、人の答えは `record.process.human_items`、読んだ記録は盤面の `reads.jsonl`（包みが書く）。
- 修正役の返答の型は 0.21.0 の `p3.fix` の schema に替わる（`changes[].closure・bypass_tried・breaks・precedent・root_or_symptom`・`plan_faces`・`not_done`・`fix_closure`・`wrote_refs` など）。指示書は 0.21.0 の `p3.fix.md` から、盤面に無い物を削って書き直す（1 本目の仕様 6 節と同じやり方）。
- 入口に `plan_file`・`human_notes`・`policy_path`（どれも空でよい）を足す。出口は 1 本目の欄（`ok・files・changes_file`）を全部残し、`fix_file`・`not_done`・`coverage`（単位ごとの前後の件数）・`reads_file` を足すだけにする（持ち主の上位互換の条件〔台帳〕）。`assert-changed` はそのまま。`fix-reads` を `collect` の前に足す。

### 3.3 blk-delta（変える。1 往復目の審査と義務の組み立て）

- 修正後の姿を版に固めて差分を切るのは、盤面の機械の節 `p3.fix_delta`（写しの `fix_delta`）が修正を受けた後の `settle` で行い、`loop.fix_delta`（`{round, file, files, rev}`。0.21.0 の `DELTA_PASSES[1].state_key`）に書く（〔盤〕BL6）。ブロックの `cut` は、盤面のそのファイルのパスと触ったファイルを審査役に出し、読むだけの役を起こす前の作業ツリーの写しを撮るだけにする（ファイルの名前は写しの規則が決め、works は組み立てない）。
- 審査役に、事前審査の穴と修正役の `plan_faces` の答えを見せる（0.21.0 の `p3.delta_review` が読む物）。受け付けは盤面の `done("p3.delta_review", …)` で、写した `delta_review_output`（事前審査の穴のうち修正が「塞いだ」と言う物を 1 件ずつ検算させる。`regression`・`policy` の語は拒む）が当たる。
- 義務の組み立て（写しの `delta_owed`。差分の審査の穴と、塞がっていない検算を `loop.delta_owed` に）も、受け付けの後の `settle` で盤面の機械の節 `p3.delta_owed` が行う。ブロックは持たない。
- 出口: 1 本目の欄（`faces・review_file・diff_file`）に `owed`（手直しが答える件数）・`fix_rev`・`reads_file` を足す。`review-reads` を足す。

### 3.4 blk-refix（新規。R7 の続き: `p3.delta_fix` → `p3.fix_delta2` → `p3.delta_review2` → `p3.delta_fix2`）

- 入口: `base_rev`・`policy_paste`・`policy_path`。規則の側の対応は写した `DELTA_PASSES` の表だけから引く（節の名前を自前で持たない）。
- 中の節（輪の中の id は全部の include をまたいで一意。R19）:
  1. `refix-loop`: 手直しの役 `refix`（書く）＋ `refix-accept`（盤面の `done("p3.delta_fix", …)`。写した `delta_fix_output`: 義務の全部に key ごとに 1 度だけ `fixed` か `declared` で答える。`fixed` には触ったファイルが要る）。受けた後の `settle` で、盤面の機械の節 `p3.fix_delta2`（条件 `delta_fixed`）が `loop.fix_delta.rev` から今の作業ツリーまでの差分（手直しだけ）を切って `loop.fix_delta2` に書き、`p3.delta_review2` を出すかを条件で決める。
  2. `route1`（script）: 盤面の `ready` から `{review2, refix2, owed, owed2}` を出す。後ろの `when:` はこの欄だけを読む。
  3. `cut2`（script）→ `review2-loop`（`when: $route1.output.review2 == true`）: 審査役 `review2`（読むだけ）＋ `review2-accept`（`done("p3.delta_review2", …)`。`delta_review_output` の 2 回目。手直しが `fixed` と言う穴を 1 件ずつ検算）。義務（`loop.delta_owed2`）は盤面の `p3.delta_owed2` が組む。
  4. `route2`（script。`trigger_rule: none_failed_min_one_success`）→ `refix2-loop`（`when: $route2.output.refix2 == true`）: 手直しの役 `refix2` ＋ `refix2-accept`（`done("p3.delta_fix2", …)`。同じ規則）。**3 往復目は無い**（graphloops と同じ）。
  5. `refix-reads` → `collect`。
- **手直し 2 回目の検算の行き先**: graphloops では、`p3.delta_fix2` が直した物は「次の周の判定者が検算する」（`DeltaPass.last`）。1 周の run には次の周が無いので、`report` がそれを**次の run の依頼の下書き**（`next-request.json`。1 本目の依頼と同じ findings の型）に書き出す。人がそのまま次の run に渡せば、次の run の判定役が検算する。持ち主の使い方（2 回目は新しい run）に合わせた、形を変えた同等（10 節）。
- 出口: `{ok, handled_file, review2_file, owed2, fixed2, files, reads_file}`（`review2_file` は 2 回目の審査を回さなかった run では空）。

### 3.5 blk-tests（変える。2 つの形。0.21.0 の engine が走らせるテストに揃える）

- 入力 `mode`（`plain`・`mid`・`final`。**既定 `plain`**）と `cmd`（必須のまま）。`plain` は 1 本目と同じ（盤面なし・`bash -c` で `cmd`・ログは `board/tests.log`・出口 `{ok, green, log}`）で、線 C の `mutgate` の `control` がこの形で include している（〔計〕審査 I1）。線 A のラインは `mid`・`final` を明示で渡す（`cmd` は空でよい）。ラインの入力 `test_cmd` は任意になる。宣言も `test_cmd` も無ければ `start` が起動の前に止める（テストを飛ばさない）。
- `final`（最後のテスト。〔計〕TA5）: 盤面の `run_engine("p4.ci")`（〔盤〕4.3）。対象の根の宣言 `.review-checks.json` が在れば engine と同じ読み方で段を走らせ、`process.checks["p4.ci"] = {by: "engine", …}` を残す（宣言が計画の後に変われば走らせずに計画し直す）。宣言が無く任せ先に落ちたら、`cmd` を走らせた結果を `done("p4.ci", {"material": …})` で渡す（`by: "role"`。表の `fallback: machine`）。受けた後の `settle` が周の記録と検証器・収束まで回し、`stop_after_round=1` で止まる。
- `mid`（中の関所のためのテスト。〔計〕TA4）: 宣言の `suite` の段を shell を通さずに `tree_run` で、無ければ `cmd` を 1 本目と同じく走らせる。盤面の節には書かず、`r1/mid-tests.log`・`r1/mid-tests.json` に置く。
- 0.21.0 は宣言の語を走らせる前の人の承認を外した（持ち主の決定 2026-09-25）。works では宣言をそのまま走らせる（engine と同じ）。**他人のリポジトリの宣言は人が先に読む**、という 0.21.0 の注意をスキルに写す。
- 出口は 1 本目の欄（`ok・green・log`）に `suites`（段ごとの終了コード）と `by`（`engine`・`role`・`mid`）を足す。

### 3.6 blk-premises（新規。〔答〕3: `p0.premises`）

- graph の `p0.premises`（`once`・依存なし・`post_check: measured_needs_output`）を、判定より前に 1 度だけ回す。書く所は盤面の `process.constraints`（写しの writes のまま）。
- 入口: `request_file`（依頼のファイル）・`base_rev`。
- 中の節: `premises-snap`（script。作業ツリーの写しを撮る）→ `premises-loop`: 役 `premises`（`[Read, Grep, Glob, Bash]`・sandbox・印 `works-node: premises`・`output_format` は 0.21.0 の `p0.premises` の schema そのもの）＋受け付け `premises-accept` → `premises-reads` → `collect`。
- 指示書は a1202d0 の `prompts/review-loop/p0.premises.md` を写し、1 段落だけ足す: 「依頼の行に `measured`（依頼者が測った値）が在れば、その値を作業ツリーで測り直し、制約の 1 行にせよ。`text` に依頼の `where` をそのまま入れよ。測り直せなければ `kind=仮説` にし、測り直せなかったと書け」。
- 受け付けの検査（順に。どれも拒否の理由は役に返る）:
  1. 読むだけの役が作業ツリーを変えていない（1 本目の写しとの比べ。〔計〕TA11。Bash を持つので必ず見る）。
  2. works が足す検査 `request_claims_covered`（ブロックの受け付けのスクリプト `blk-premises/scripts/accept.py` に置く。`accept.py` には足さない。7 節）: 依頼の `measured` を持つ行の全部について、`text` に依頼の `where` を含む制約が 1 行以上在る。無ければ拒む（依頼者の数字が検算なしで判定役に渡らないように）。
  3. 盤面の `done("p0.premises", …)`: 写しの `measured_needs_output`（`kind=実測` はコマンドと出力が要る）と schema。
- 出口: `{ok, premises_file, constraints, measured, hypotheses, claims, claims_hypothesis, reads_file}`（`claims_hypothesis` は依頼の `measured` のうち測り直せず `仮説` になった件数）。
- 判定役への届け方: 境の節 `h-judge` が盤面の `state.outputs["p0.premises"]["file"]` を `premises_file` として返し、`blk-judge` の入口 `premises_file` へ渡す（入口と指示書の 1 段落は線 A が波 2 の 1 度の手入れで足す。〔計〕Task 2）。指示書の段落の芯: 「前提（実測）: `$INPUTS.premises_file` を読め。`kind=仮説` の行を所与にするな。依頼の数字と測り直した値が違えば、測り直した値を採り、違いを単位の `reason` に書け」。graph の `p2.diagnose` が `record.process.constraints` を読むのと同じ。
- 目的の文 `p0.purpose` は線 A に入らない（〔答〕3: 線 B に足す）。節の表の absent のまま、毎周の添え書きと報告の冒頭に出る。

### 3.7 blk-rejudge（新規。〔答〕4。本線の 3-6 の形。写し直しの後に入る）

- **形は本線の 3-6（d1b863f。まだ版に入っていない）に揃える**（〔本〕3.3。回す側の指示 2026-09-27）。0.21.0（a1202d0）の形（`p2.rejudge` と `p2.rejudge_third` の 2 節）は、engine が 1 周に同じ節を 1 度しか出さないので往復が 1 回で止まり、第三の目が実際の盤面で立たない穴がある（本線の merge-request「wip/exit-fields の残り」）。この穴を写さない。
- **3-6 の往復**（1 周の中。どの節も graph で optional）: `p3.fix`（修正役が `rejudge_requested` に異議）→ `p2.rejudge`（判定役の続き）→ 決着しなければ（`一部採る`）`p3.rejudge_reply`（修正役の再異議。新しい会話）→ `p2.rejudge2`（判定役の続き）→ `p3.rejudge_reply2` → `p2.rejudge3`（判定役の続き）→ 3 回とも決着しなければ `p2.rejudge_third`（新しい会話の第三の目）。条件は写しの `rejudge_open`・`rejudge2_open`・`rejudge3_open`・`rejudge_reply_due`・`rejudge_reply2_due`・`rejudge_exhausted`、往復の数は写しの `REJUDGE_PASSES`（3）。works は数も順も持たず、盤面の `ready` を読むだけ。
- **いつ入るか**: 盤面の写しが 3-6 を含む版になってから（「写し直しへの依存」。〔計〕の同じ名の節）。それまで 6 節は節の表の absent（理由「同じ周の再審は本線 3-6 の写しの後に入る」）で、毎周の添え書きと報告の冒頭に出る。包みの会話の継ぎ（5.1）はその前に作って試験で縛っておく（写しに依らない）。
- **判定役の会話の続き**（graph の `same_context_as: p2.diagnose`）: 役 `rejudge`・`rejudge2`・`rejudge3` の印は `works-node: <名> continue=judge`。包みが判定役の Claude の会話 id で `--resume` して起こす（5.1）。fork しないので会話 id は変わらず、3 回とも同じ会話に積まれる。YAML の節は `context: fresh`（Archon には何も継がせない。継ぐのは包みだけ）。〔継試〕で、再審が判定役だけが知る値を答え、修正役には見えず、型つきの返答と sandbox がそのまま効くことを、平らな線と `loop_group` の中の両方で確かめた。
- **修正役の再異議**（`rejudge-reply`・`rejudge-reply2`）: 新しい会話（本線も `same_context_as` を持たない。works の「書く役と採点する役は会話を分ける」とも合う）。`[Read, Grep, Glob]`・印 `works-node: rejudge-reply`。返答は `rejudge_requested`（任意）と `reason` だけで、作業ツリーは変えない（写しで確かめる）。
- **第三の目**（`rejudge-third`）: 新しい会話（`fresh_context: true`）。印は `works-node: rejudge-third`（`continue` を持たない）。
- **会話の id が無い時**（判定役が包み無しで走った・包みの置き場が消えた・別の worktree で走った）: 境の節 `h-rejudge` が役を起こす前に、`adapter.session_path(run の worktree, "judge")` が在るかを見る。無ければ盤面を `b.stop("判定役の会話が見つからない: …", by="works:rejudge-session")` で止め、報告の冒頭 1 で人に聞く（「異議の再審ができなかった。次の run に異議を渡すか」。異議の文は `next-request.json` に入る）。1 周の run なので「止めて聞く」。包み自身も id が無ければ起動を拒む（exit 3）が、そこまで行くと Archon が約 12 回起こし直して約 40 秒後に節が落ちる（AI の費用は 0。〔継試〕）ので、先に script の節で止める。2 回目・3 回目の再審は 1 回目と同じ id を継ぐので、確かめは 1 回目の前だけでよい。
- 中の節: 段ごとに `rj-route<k>`（script。盤面の `ready` から次の段を返す）を置き、その後に役の輪を 1 つ（`rejudge`・`rejudge-reply`・`rejudge2`・`rejudge-reply2`・`rejudge3`・`rejudge-third` の 6 つ。どれも `when:` は直前の `rj-route<k>` の欄だけ、`trigger_rule: none_failed_min_one_success`）→ `rejudge-reads` → `collect`。役の前に `rejudge-snap`（作業ツリーの写しと、再審の前の単位の一覧と材料の束 `rejudge-brief.json`）。`collect` の時点でまだ再審の節のどれかが ready なら `ok: false`（engine の順で起きない形。黙って飛ばさない）。
- 受け付け: 読むだけの役の作業ツリーの確かめ（〔計〕TA11）→ 盤面の `done(<節>, …)`（写しの `rejudge_output`: `new_facts` が空同然なら拒む・defer の再浮上の証拠）。再異議の 2 節は graph に `post_check` が無く、schema だけが当たる。works は検査を足さない。
- **判定役はどの単位も変えてよい**（柵を足さない。graph の writes は units を丸ごと置き換える）。ただし受け付けの後に、再審の前後の単位を比べて `rejudge-diff.json`（往復ごとに `{pass, disputed, changed[], undisputed_changed}`）を書く。争点の単位（`disputed`）は、その回の異議の文に key がそのまま現れる単位。争点でない単位の変化は報告の冒頭 1 に必ず出す。争点の単位が 1 つも引けなければ、変化の全部を「争点でない」側に並べる。
- 指示書: 写し直しで入る本線の `p2.rejudge.md`・`p2.rejudge2.md`・`p2.rejudge3.md`・`p3.rejudge_reply.md`・`p3.rejudge_reply2.md`・`p2.rejudge_third.md` を写し、`{{…}}` の差し込みを `rejudge-brief.json` のパスを読む形に替える（異議・今の周の単位と台帳・判定の見立て・これまでの往復）。方針の文書は読む役（判定役・第三の目）には本文を貼り、再異議の役にはパスを渡す。
- 出口: `{ok, passes, verdicts, undisputed_changed, diff_file, reads_file}`。
- 費用: 再開した会話の `total_cost_usd` は累積なので、Archon の節の費用の表示は判定役の分を重ねて数える〔継試〕。報告の費用の行は、包みが継いだ起動について、同じ会話の直前の起動の表示を引いた値を出す（6 節）。判定役 → 再審 1 → 再審 2 → 再審 3 の鎖でも、1 つ前を引けば各々の実額になる。

### 3.8 blk-pr（新規。〔答〕2: `p0.parallel_pr` の任せ先）

- 節の表で `p0.parallel_pr` は `engine_run`・`fallback: role`（〔盤〕BL25・BL28）。`start` が `run_engine("p0.parallel_pr")` で写しの `parallel-pr.py`（1〜5 段: owner/repo の解決・自分の PR の除外・打ち切り・変更ファイルの交差）を走らせ、交差が 0 なら engine の返答で済む（`by: "engine"`）。交差が在る・remote が GitHub でない・`gh` が無い時だけ任せ先に落ち、`start` の `pr_go` が真になる。
- 任せ先の役 `pr-check`（opus・`[Read, Grep, Glob, Bash]`・sandbox・印 `works-node: pr-check no-post`）は、0.21.0 の `p0.parallel_pr.md` の 6 段の全部をする。**6 段目だけ替える**: 担当の PR へ投稿せず、申し送りの下書きを `conflicts[].note` に書き、`handed_over: false` で返す（〔答〕2）。
- 受け付け: 作業ツリーの確かめ → works が足す検査 `check_no_post`（`blk-pr/scripts/accept.py` に置く。`conflicts[].handed_over` が 1 つでも真なら拒む。「このラインは申し送りを投稿しない。下書きを note に書け」）→ 盤面の `done("p0.parallel_pr", …)`。
- 包みの柵（補助）: 印の `no-post` を見た起動には、`permissions.deny` に `gh` の書き込みの語（`gh pr comment`・`gh pr review`・`gh pr edit`・`gh pr create`・`gh pr close`・`gh pr merge`・`gh issue comment`・`gh issue create`・`gh api -X`・`gh api --method`）を足す。効くかは P14 の結果しだいなので、本体は指示書と受け付けの検査。
- 報告: 冒頭 1 に申し送りの下書き（PR・ファイル・下書きの文。人が担当の PR へ渡す）。冒頭 2 に「下げている所: 並行 PR の申し送りを投稿しない（review-graph は gh で投稿する）」。下げた物の一覧はラインの置き場の `darkfactory/downgrades.json`（`[{node, what, versus}]`）に 1 行で持ち、報告の部品が読む。
- 並ぶ所: `start` の後・`premising` の前。`p1.consistency_bypass` が `p0.parallel_pr` に依存するので、盤面の P1 の `na` と `p2.diagnose` の ready はこの節が済んだ後に付く。

## 4. 手厚さと入口

入力（`start` が確かめ、`r1/start.json` と報告に固定する。〔手〕の推しをそのまま採る）:

- `thickness`: `軽量`・`標準`・`重厚`。既定は `標準`。**受けるのは `標準` だけ**（〔答〕1: 案 1。graph で optional でない節は省かない。〔計〕TA7）。`軽量` は「軽量は受けない: graph で省けない節を省くことになる（持ち主の決定 2026-09-27）」、`重厚` は「重厚で足す工程がまだ無い」の 1 行で、`start` が AI を起こす前に止める。省く配管（節の表の `downgrade` の欄・`state.works.downgrades`）は作らない。
- 1 版に在った `thickness_decider`（`軽量` を依頼者が言った時だけ受ける）は消した。軽量を受けないので効かない入力になるため（効かない入力を先に置かない）。
- `mid_gate`: `always`（既定）・`when_needed`（2 節。〔台帳〕R26）。
- `adapter`: 空（既定。包みが無ければ止める）か `optional`（5.1）。
- `gates`: 空か `merge`。`merge` は「変異の検算を合流の後にまとめる」（0.21.0 の `GATES_MERGE`）。変異の検算は線 C が作るまでこのラインに無いので、どちらの値でも撃たない。省いた理由の文が変わる: `merge` のときは 0.21.0 の `GATES_MERGE_WHY`（残る義務: 合流した版で撃つ）、空のときは「このラインに変異の検算が無い（線 C 待ち）」。

- **重厚は今は受けない**。重厚で足す物（P1 の目・R1〜R4）がこのラインに 1 つも無いので、`start` が「重厚で足す工程がまだ無い」と 1 行で止める。選べるのに中身が標準と同じ、という形を作らない。R 系のブロックが 1 つ入った日に受け始める。
- 1 版に在った「段ごとに回すブロック」の表（軽量で事前審査と差分の審査・手直しを省く形）は、〔答〕1 で要らなくなったので消した。
- 入口: `darkfactory` は判定から入る（`DiskBoard.begin` が graphloops の `add` と同じ依頼の型で記録し、`request_entry = {origin}` を置く。〔盤〕5 節）。P1 の目は graphloops でも判定から入る run の 1 周目には起きないので、これは差ではない。仕様から入る道は別の入口 `darkfactory-spec` として後で足す（0.21.0 の `flow=spec`）。TDD の修正は `blk-fix-tdd` ができた時に入力 `tdd_suite` を足す。効かない入力を先に置かない。
- 省いた印: **ラインの節の表 `darkfactory/nodes.json`**（〔盤〕4.2。BL4）が、graph の全部の節をこのラインでどう持つかを run の前に固める。このラインに無い節は表の absent（理由と入る予定の線 `comes_with`）で、盤面が `state.works.not_in_line` と毎周の添え書き `rounds/works/round-1.json` に必ず出す（条件で `na` の周も。〔盤〕4.5・BL22）。`process.skipped` は engine と同じ意味のまま（条件に当たって省いた節だけ）。表の縛りは盤面を開く時と単体テストで見る（graph の全部の節がちょうど 1 度ずつ）。報告の冒頭に 1 行: 「入口: 判定から（依頼 N 件）・段: 標準・gates: 空・このラインに無い節: M 個（一覧は …）・下げている所: K 個」。
- 並行 PR の検査 `p0.parallel_pr` は `engine_run`・`fallback: role` で持つ（〔答〕2。3.8。〔計〕Task 21）。申し送りを投稿しないことは、下げた物の一覧 `darkfactory/downgrades.json` に書き、毎周の添え書きの隣と報告の冒頭 2 に出す。
- 節の表の行（〔答〕の後）: `p0.premises` は role（blk-premises）、`p0.parallel_pr` は engine_run（任せ先 blk-pr）、再審の節（写し直しの後の 6 節）は role（blk-rejudge。それまで absent）。`p0.purpose`・`p0.purpose_review`・`p0.prior_decisions` は absent（目的の文は線 B の `blk-purpose` で入る。線 A のラインへの取り込みは未定）。

## 5. 包み・読んだ証拠・止め方

設計は〔輪〕の 12 節（包み）・5.3（読んだ証拠）・2.5（止める）をそのまま使う。1 周の run で変わる所だけ書く。

### 5.1 Claude の包み（〔輪〕12 節）

- 包み `works/.shared/core/claude-adapter` が足すのは 4 つだけ。Read のフック（盤面の `reads.jsonl` に sha つきで書く）、起動ごとに守る場所（`sandbox.filesystem.denyWrite` と `permissions.deny`）、本物の claude を自分のプロセスグループで起こして止める時はグループごと止めること、判定役の会話の継ぎ（下）の 4 つ。CLAUDE.md は YAML の `settingSources: []` のまま止める〔包試〕。
- 切符（盤面の場所・守る場所・run の id。`.shared/core/ticket.py`）は `start` が 1 回だけ書く（周の輪が無いので `open` の書き直しは無い）。守る場所は git から引く（共通の `.git`・この worktree の gitdir・ほかの worktree と元の作業ツリー・盤面・切符の置き場・works 自身・git とシェルの設定・Claude の設定）。役の cwd の worktree 自身は除く。
- 包みが無い環境の扱いは〔台帳〕の決定（包みの無い run は既定で拒む）と同じにする。境の節 `h-judge`（前提の役の後・判定の前）が「この run の役の起動が `launches.jsonl` に無い」と見た時点で run を止める（結末 `stopped_by_line`）。前提の役と並行 PR の任せ先の役（どちらも Bash を持つが読むだけ。作業ツリーの写しで確かめる）は確かめより先に走るが、判定役と書く役は必ず確かめた後に走る（〔計〕TA9。1 版は `h-plan` で見ていた）。入力 `adapter: optional` を渡した run だけ包み無しで回し、報告の冒頭に「包み無し」と出す。包み無しの run では判定役の会話を継げないので、異議が出たら `h-rejudge` で止めて聞く（3.7）。CI の任せ先の役（blk-ci の節 `ci`）は、sandbox が graphloops の任せ先と同じ `allowWrite ['/']`（依存の導入・網を今までどおり使う。裁定 R56）なので、書き込みの守りは全部包みが足す——印の旗 `no-tree-write` を見て、役の cwd の worktree の根（全部の綴り）と切符の守る場所（盤面・共通の `.git`・ほかの worktree・git とシェルと Claude の設定・Archon の家の設定と DB・pack）を `denyWrite`・`permissions.deny` に足し、sandbox の塊（`enabled`・`allowUnsandboxedCommands: false`・`failIfUnavailable: true`）か切符の無い起動は起こさない。**包みが居ないと、この役の Bash は Claude Code の既定の拒否（`.gitconfig`・シェルの起動ファイル・`.git/hooks`・`.git/config` など。macOS は全域、Linux は cwd の下だけ）の外の全部に書ける**——本物の作業ツリー・盤面・共通の `.git` の refs と objects・`~/.config`・`~/.claude`・Archon の家、Linux では `~/.gitconfig` も。これは graphloops の任せ先（`delegate_settings` の sandbox だけで走る）と同じ晒され方で、包み無しの run はそれを宣言して回す（裁定 R58）。包みが Archon の起動の道に在るかを script から写して見ることはしない（Archon の claude の解決を写すと、居ないのに居ると言う形と、写しの pack——dogfood・real-run・`archon plugin install`——で居るのに居ないと言って CI の役を止める形が両方ある。再審査 N4〜N6）。blk-ci の最初の節 `ci-fence` が見るのは run が宣言した包みの形（`start` の控え `r<N>/start.json` の `adapter`。`entry.declared_adapter`）だけ: 包みを宣言した run（`adapter` が空）は切符を見て進み（無ければ盤面を止める。包みは切符の無い旗の役を起こさない）、受け付けが包みの起動の記録（`adapter.fenced_launch`）でこの試行の役の起動に柵 `no_tree_write` が掛かったかを見て、無ければ盤面を止める（起きた後で気づく線。包みの無い起動は記録も書き換えうるので確証ではない）。包み無しを宣言した run（`adapter: optional`）は進み、「包み無し: CI の役は graphloops と同じ守り（sandbox だけ・作業ツリーの柵無し）で走った」の知らせを盤面の作業ファイル `ci-note-<節>.json` と blk-ci の出口の `note` に残す（報告の冒頭の「包み無し」に並べる。黙って下げない）。受け付けは柵を求めない。宣言が読めなければ（控えが無い・壊れた・語の外）`ci-fence` も受け付けも盤面を止める（by `works:adapter`。fail closed）。受け付けの作業ツリーの比べ（`accept.tree_state`）は、どちらの run でも偽の緑を防ぐ。
- **判定役の会話の継ぎ**（〔答〕4。〔継試〕の形のまま）:
  1. **どの節か**: argv の `--json-schema`（`--json-schema <値>` と `--json-schema=<値>` の両方の綴り）の JSON の一番上の `description` を `node_marker.parse` で読む。印の無い起動（Archon の題の生成＝`--tools ""` の起動など）は触らずに素通し。指示書の 1 行目では見分けない（SDK は claude が initialize に答えるまで指示書を stdin に書かない〔継試〕）。
  2. **印あり・`continue` なし**（判定役 `judge` ほか全部の役）: SDK が既に `--resume <id>`（`--resume=<id>`）を付けていればその id を、`--session-id` を付けていればその id を記録する（Archon 自身が継いだ回。線 B の判定の 2 回目）。どちらも無ければ包みが UUID を作って `--session-id=<uuid>` を足し、記録する。記録の場所は `adapter.session_path(cwd, 節の名)` ＝ `<包みの家>/sessions/<cwd の realpath の sha256 の先頭 16 字>/<節の名>.id`（一時ファイルから `os.replace`）。cwd は run ごとの worktree なので run の間で混ざらない。同じ節名の後の起動が書き直すので、いつも「直近の判定役」を継ぐ（graphloops の意味と同じ）。
  3. **`continue=X`**（再審 `rejudge`）: SDK が付けた `--resume`・`--resume=`・`--session-id`・`--session-id=`・`--fork-session` を外し、`--resume <X の id>` を足す。`--settings`（sandbox）と `--setting-sources` は触らない（〔継試〕の (3)）。`--fork-session` は使わない（継ぐだけなら要らない〔継試〕）。X の id のファイルが無ければ、stderr に 1 行（`works: 会話 X の id が無い: <path>`）を出して exit 3 で止まる（fail closed。子を起こさない）。
  4. 会話の継ぎは切符に依らない（id の置き場は cwd で引く）。切符が無くて `--settings` を素通しにする起動でも、継ぎは行う（継がずに新しい会話で再審すると、黙って別の目になるため）。
  5. `launches.jsonl` の行に `node`（印の名）と `session: {mode: "new"|"sdk-resume"|"sdk-session"|"continued"|"refused", id, of?}` を足す（`of` は継いだ節の名）。費用の引き算（6 節）がこの行を使う。
  6. **印 `no-post`**（並行 PR の任せ先の役）: `permissions.deny` に `gh` の書き込みの語を足す（3.8）。
- 壊れる余地（今は壊れていない。〔継試〕）: SDK が `--resume=` の綴りや `--json-schema` の渡し方を変えると見分け・差し替えが外れる（版上げの試験で見る。実物の argv の見本を持つ）。印は `output_format` に依るので、`output_format` を持たない AI の節には置けない（線 A・B の役は全部持つ）。同じ worktree で同じ節名の run が並ぶと id が上書きされる（run ごとに worktree が違うので今は起きない）。

### 5.2 読んだ証拠（〔輪〕5.3）

- 各ブロックの出し直しの輪の後、`collect` の前に `<役>-reads`（`.shared/core/reads.py`）を置く: `pr-reads`（並行 PR の任せ先）・`premises-reads`・`plan-reads`（修正案と事前審査）・`fix-reads`・`rejudge-reads`（再審と第三の目）・`review-reads`・`refix-reads`（手直し 2 回と 2 回目の審査）。判定の `judge-reads` は blk-judge の中なので線 B が置く（8 節）。それまで判定の読んだ証拠は無く、報告の冒頭 4 に「判定: 読んだ証拠の節が無い（線 B）」と出す。
- 出どころは 2 つ。包みのフックの記録（sha つき）と、Archon 自身の `tool_called` の出来事（役には偽れない）。出来事は script の節から `json.loads(os.environ["ARCHON_CLI_COMMAND"]) + ["workflow", "get", os.environ["WORKFLOW_ID"], "--verbose", "--events", "--json"]` で読む（`--verbose` が無いと出来事が出ない。実行ファイルは PATH に `archon` を持たない）〔試P: P13〕。節の名前は include の付け替えで引く（輪の外の include `fixing` の中の輪 `fix-loop` の節 `fix` なら `fixing__fix-loop.fix` の形。推測で、〔試P〕が見たのは輪の中の `rounds.judging__ja-redo.ja-try`）。`tool_called` の Read に `file_path` が載るかは未確認（AI 要・費用の了承待ち）。〔試し P13 2026-09-26〕機械が渡したパスの 1 つずつについて 5 つの状態（read・stale・partial・absent・none）と出来事の有無を `r1/reads-<役>.json` に書く。受け付けの条件にはしない（graphloops と同じ）。欠けは報告の冒頭に出す。
- 数え直し（3.2）の `wrote_refs_reads` は盤面の `reads.jsonl` をそのまま読む。

### 5.3 外から止める（〔輪〕2.5）

- **止め札**: `works/dev/stop.sh <run-id> <理由>` が盤面に `STOP`（`{reason, by, at}`）を置く。盤面の場所は `archon workflow get <run> --json` の `output_root` に `artifacts/runs/<run-id>` を足して組み、`board/` が在ることを確かめてから書く（走っている run には `$ARTIFACTS_DIR` の欄が無い）〔試P: P12〕〔試し P12 2026-09-26〕。理由が空なら置かずに終了コード 2 で止まる。既に在れば上書きせず、後の理由は trace にだけ積む（最初の理由が正）。止め札を見た境の節は盤面の `stop(理由, by)`（〔盤〕BL10。engine の `cmd_stop` の盤面の部分と同じ記録）を呼び、`{stop: true}` を返す。後ろの段は `when:` で全部飛び、`report` が必ず走る（`outcome: stopped_by_request`、理由と止めた境の節を冒頭に）。止め方の意味は `a2695cf` の `cmd_stop` と同じにし、0.21.0 で入った `loop.py stop` とも同じになる（理由は必須・記録に残す・報告は出す・下流だけを走らせない。graph の `stop.node` は `converge` で、1 周の run では `report` に当たる）。
- 走っている AI の節は、止め札では最後まで走る（次の境で止まる。ブロックの中の出し直しの輪も次の境まで回りきる〔試P: P12〕）。すぐ止めたいときは取り消しを使う。起動の関所 `launch` を `archon workflow approve <id> --detach` で越えた run は、`archon workflow cancel <id>` で持ち主の木ごと止まる（〔隙A〕1）。〔試し P12 2026-09-26〕
- 取り消しの試しの結果〔試P: P11〕〔試し P11 2026-09-26〕:
  - bash・script の節と、tree_run の下の別グループの孫まで止まった。
  - 直した（1ec7894。〔台帳〕R31）: SIGTERM を無視する孫が tree_run の下にいると残る道は、tree_run の猶予を 5 秒から 2 秒（`KILL_GRACE`）にして塞いだ。包みも同じ `KILL_GRACE` を使う（〔輪〕12.4）。
  - AI の節の分（包みの下の claude と Bash の孫）は未確認（AI 要・費用の了承待ち）。届かなければ取り消しは「非常用」と書き、止め札を普段の道にする（〔輪〕11 節の 4 と同じ推し）。
  - `cancel` が効かない run が 2 つある。関所（`launch`・`policy-gate`）で待っている run は拒まれるので、`respond … stop` か `reject --reason`（報告が出る）か `abandon` で止める。前景の run も拒まれるので Ctrl-C で止める。SKILL に「関所で待っている run は `cancel` でなく `respond … stop`」と書く。
- `dev/report.sh <run-id>` が盤面から報告を作るのは、`cancel` と `abandon` の後だけ。関所の `stop`・`reject` では `report` が run の中で走る（3.1）ので要らない〔試P: P16〕。〔試し P16 2026-09-26〕
- Ctrl-C と `archon workflow resume` はそのまま使える。bash の節で `&` を使わない（背景の子は Ctrl-C で止まらず残る。〔輪〕7 節）。〔試し P9 2026-09-26〕

## 6. 報告の節（1 本目の finish を継ぐ）

- `report`（script、`returns`）は、`finish` の欄（`ok・outcome・judgment_file・review_file・diff_file・faces`）を全部残す。足すのは `outcome` の値 `stopped_by_request`（止め札）・`stopped_by_human`（関所の `stop`・`reject`）・`stopped_by_line`（包みが無い・判定の渡し替えが拒まれた・前提の実測が盤面に無い・判定役の会話が無くて再審できない、など機械が止めた）・`needs_human`（最後に盤面が人に聞いたまま終わった。例: run の途中で方針の文書が変わり R4 の関所の項目が立った）・`record_invalid`（記録が報告の前の検証器を通らない）・`interrupted`（取り消し等で落ちた run に `dev/report.sh` で後から作った報告）と、`report_file`（盤面の `report.md`）・`next_request_file`・`tests_green` である（〔計〕TA12）。報告の前に、engine の `loop.py finalize` と同じ関所を必ず通す（〔計〕TA15）: 止めていない盤面を `settle` → `finalize`（〔盤〕4.1）→ 盤面の `run_validator`（線 B の包みも効く口）→ 終了コードが graph の受理集合（`report_accepts`）に入るか。入らない・周の記録（`p4.record`・`converge`）が今の周に済んでいない（止めた run を除く）なら、結末は `record_invalid` で、冒頭 1 に検証器の出力の末尾と記録の痕跡の欄（`traces`）を出す。**記録が検証器を通らない run に `fixed`・`no_fix_needed` を出す道は無い**。表で graph の `report` を absent にするので、盤面の `settle` の報告の前の関所（`pre: finalize` → `RecordInvalid`）は線 A では起きず、この関所がその代わりになる。取り消し・`abandon`・役の出し直しの上限で落ちた run は `dev/report.sh` が同じ関所を通して報告を作り、結末は `interrupted`。
- `report.md` の冒頭の並び（機械が組む。AI は書かない）:
  1. 人が決めること（修正前の関所と中の関所の答え・テストの赤・次の run に渡す物の件数・`needs_human` の問い・並行 PR の申し送りの下書き・再審で争点でない単位が変わった物・依頼の実測のうち測り直せなかった物・再審できずに止めた時の問い）
  2. 入口・段・gates と、このラインに無い節の数と一覧のパス、下げている所の数と一覧（4 節）
  3. 止めたか（止め札・関所の stop・機械の止め。理由と止めた境の節）
  4. 読んだ証拠（包みの記録と出来事の有無・素通しの起動の数・会話を継いだ起動の数）
  5. 見る所（前提・判定・修正案・事前審査・再審・審査・差分のファイルと、run の worktree の場所）
- 冒頭の後に「費用」の行を置く: 役の節ごとの費用。包みが会話を継いだ起動（`launches.jsonl` の `session.mode == "continued"`）は、Archon の表示が再開した会話の累積なので、同じ会話の直前の起動の表示を引いた値を出し、引いたことを行に書く〔継試〕。費用を Archon の出来事から取れなければ「費用: 取れない（Archon の表示は再開した節で判定役の分を重ねて数える）」と 1 行出す。
- `next-request.json` に入れる物: 2 回目の審査が挙げて手直し 2 回目が `fixed` と言った穴（検算が要る）、`declared` で残した穴、修正の `not_done`、テストが赤なら赤の事実、再審できずに止めた run の異議の文、第三の目が「方針の岐路」と書いた争点。どれも `start` の依頼の型の検査を通る形で書く（9.1 で往復を縛る）。
- **最小にした理由と欠け**: graphloops の報告は、writer の役が履歴を全部写して利用者の言語で書き（`report`）、人に聞く所だけを文脈の無い読み手に読ませて詰まりを直す（`report.human_items`・`report.cold_check`）。線 A は機械の要約だけにし、この 3 つは節の表の absent（理由「AI が書く報告と初見検査は後。review-graph と同等と言う前に要る」。〔台帳〕R27）で宣言する。人に聞く文は機械の定型なので、初見検査の効き目は graphloops より小さい見込み（推測）。後で足すなら、`report` の後ろに初見の読み手の役を 1 つ置く形になる（12 節の 4）。

## 7. 揃える物（0.21.0）

0.21.0 で入った物の 1 つずつについて、works のどこで持つかを示す（出典は 0.21.0 の commit 82deb2e の本文と 〔0.21〕）。0.21.1（作業中）の物は写し直しの時に読み直す。

| 0.21.0 の能力 | works での持ち方 | 線 |
|---|---|---|
| 1 周で止める（`--stop-after-round`） | 1 周の run はいつも 1 周 | A（形） |
| 変異の検算を合流でまとめる（`gates=merge`） | 入力 `gates`・節の表 | A 入力／C 本体 |
| engine が走らせるテストの節（`.review-checks.json`） | 盤面の `run_engine` | A |
| テストを走らせる前の承認を外した | 承認は元から無い | 済 |
| 任せ先の柵・Bash を持つ役を sandbox で | 全役に sandbox＋包みの柵 | A |
| 人の方針の関所（`p2.human_gate`） | blk-plan＋`policy-gate` | A |
| 人の方針の関所（`r4.human_gate`） | 機械の節は走る・R4 の役は無い | 後 |
| 方針の文書を全部の役に | 盤面が固め、`start` が貼る文とパスを組む | A |
| 止める口（`loop.py stop`） | 止め札＋境の節＋取り消し | A |
| 記録器（`intake.jsonl`） | 無い（宣言） | 後 |
| 変異の見逃しを塞ぐテスト | graphloops 自身の試験 | 対象外 |

- 0.21.1 で入る予定の物: 2 周目の直し・pytest の土台・Google 流の変異（→ 線 C）・CI を飛ばす所の直し・止める層（→ 5.3 の意味を読み直す）・ブロック分け 3-1/3-3（→ 規則の関数の形が変わりうる。土台の DiskBoard が受ける）・流れの土台（→ `darkfactory-spec`）。
- **写し直しへの依存（本線 3-5・3-6。〔本〕）**: 写し直しは本線の 3-5（27a818a）と 3-6（d1b863f）が版に入るまで見送り、入ったら 1 回で写す（0.21.1 だけへの写し直しはしない）。その時に要る物（線 A の作業ではなく、写し直しの線と盤面の層と線 C の作業。〔計〕の「写し直しへの依存」に一覧）: 節の表と手本の graph_sha の直し・新しい機械の節 `p2.fix_units` と再審の 4 節の行・盤面の層の受け付け（`board.py` の 701〜712 行）を engine の `commands.post_check` を通す形へ（新しい返り `{ok: false}`）・`accept.py` の `DeltaPass.state_key` が消える・線 C の `mutcore` が `loop.gates_cut` でなく `p3.gates_cut` の出力を読む・`engine/hist.py`・`effects.py`・`filelock.py`・`graphloops/blocks/**`・`scripts/gl.py` を写す。線 A の再審（3.7）はこの後に入る。
- **本線のブロックの名前**（〔本〕3.2・3.4。回す側の指示 2026-09-27）: 本線のブロックの置き場と名前は 3-7 が落ち着いてから決まる。今は works の仮の名（`blk-plan`・`blk-refix`・`blk-premises`・`blk-pr`・`blk-rejudge`）で作り、節の表の `where` も works の置き場だけを書く。3-7 が版に入ったら、名前と `where`（本線のブロック名を足す）を揃える小さな作業をする（〔計〕Task 25）。今の見込みでは `blk-plan`・`blk-rejudge` は本線の plan・rejudge と 1 対 1、`blk-premises`・`blk-pr`・`blk-refix` は本線の prereq・material・delta の一部。
- **受け付けの口は本線の 3-8 まで `accept.py` のまま、検査を足さない**（回す側の指示 2026-09-27。本線からの知らせ）: 本線の `gl.py`（`cond`・`accept`・`machine`・`exit`）はまだ `accept.py` を置き換えられない（依頼に依らない検査の口・役の schema から注記を外す口・判定の受け付け・差分を切る段が無く、盤面の前提も違う。3-6 の続きと 3-8 で入る）。線 A が足す works だけの検査（依頼の実測の測り直し `request_claims_covered`・申し送りを投稿しない `check_no_post`）は、そのブロックの受け付けのスクリプトに置く。読むだけの役の作業ツリーの確かめは、共通の姿 `accept.tree_state`（`snapshot_tree` に HEAD・枝を足した物）と違いの文 `tree_change`・`tree_moved` を使うだけ（裁定 R47。blk-pr・blk-ci・`entry.take`・`rejudge.take` が同じ 1 本を使う）。`accept.py` から `gl` への対応表（足りない 4 つと works だけの検査）は〔計〕Task 24。
- 名前が変わりうる所: `DELTA_PASSES`・`human_gate`・`_plan_gate_items`・`delta_owed`・`on_stop`。線 A のスクリプトはこれらを直に呼ばない（機械の節は盤面の `settle` が回す）。`DELTA_PASSES` の節の名前だけは `refix.passes()` の 1 か所で引く。写し直しで変わっても、盤面の層とこの 1 か所で直せる。

## 8. 持ち物（並べる線とのファイルの分け方）

持ち物は〔盤〕6 節の表が正本。ここは線 A に関わる所だけを写し、〔計〕の決め方を足す。

- **線 A だけが触る**: `blk-plan/**`・`blk-refix/**`・`blk-premises/**`・`blk-rejudge/**`・`blk-pr/**`（新規）、`blk-fix/**`・`blk-delta/**`・`blk-tests/**`、`darkfactory/**`（1 周のライン・節の表 `nodes.json`・下げた物の一覧 `downgrades.json`・`start`・境の節 `edge`・`report`・筋書き）、`.shared/core/{claude-adapter,adapter.py,record-read.py}`、`.shared/core/{recount,halt,reads,plan,refix,entry,policy,report,ticket,node_marker,premises,rejudge,prcheck}.py`・`.shared/core/gl_map.json`（線 B も最後の共有の commit で行を足す）、`dev/stop.sh`・`dev/report.sh`、`tests/replies/fix2_*`・`tests/replies/plan*`・`tests/replies/premises_*`・`tests/replies/rejudge_*`・`tests/replies/pr_*`。
- **線 A の新しい試験のファイル**（〔盤〕の表に名前は無いが、他の線と重ならない）: `tests/test_{entry,ticket,adapter,reads,halt,policy,node_marker,blk_plan,blk_refix,blk_premises,blk_rejudge,blk_pr,report,line_a,gl_map}.py`・`tests/linekit.py`・`tests/adapter/**`・`tests/events/**`。v1 の試験のうち線 A のブロックを見る `tests/test_blk_fix.py`・`tests/test_blk_tests_delta.py` も線 A が直す。
- **線 B の物で、A が 1 度だけ触る**: `blk-judge/blk-judge.yaml`（入力 `policy_paste`・`premises_file` を足し、判定役の `output_format` に印 `works-node: judge` を付ける）と `blk-judge/commands/diagnose.md`（その 2 つの入力を読む 2 段落）と `tests/test_blk_judge.py`（`output_format` を比べる 1 つの試験を、印を外して比べる形にする）。B が判定 v2 に着手する前に入れる（波 2。〔計〕Task 2）。節は足さない（1 本目のラインと `test_line.py` を壊さないため。〔計〕TA10）。`judge-reads` は B が置く。印は、線 A の再審が判定役の会話を継ぐのに要る（B の v2 の前でも継げるように、ここで付ける）。
- **周の輪のラインは別の入口**（〔台帳〕R25 で決めた）: B は `darkfactory-rounds/` に周の輪のラインと自分の節の表を作り、ブロックは共有する。ブロックのスクリプトは、盤面の `state.works.line` から表を引いて開く（`entry.open_board`）ので、どちらのラインでも同じブロックが動く。
- **〔輪〕の計画から線 A へ移った物**: T7（数え直し）・T9（止め札）・T10（包み）・T11（読んだ証拠）（〔盤〕BL13）。
- **土台だけが触る**: `.shared/core/board.py`・`.shared/core/accept.py`（1 度の移し替えの後は凍る）・写し（`.shared/core/graphloops/**`・`.shared/core/scripts/**`・`COPIED_FROM`）・盤面の層の試験。線 A は読む・import するだけ。
- **共有のファイル**（〔盤〕6 節の一覧: `tests/test_yaml_rules.py`・`yaml_good/bad`・`test_line.py`・`test_script_headers.py`・`run.sh`・`dev/check.sh`・`mktarget.sh`・`real-run.sh`・`archon.sh`・`guard.sh`・`skills/works/SKILL.md`・`README.md`・`archon-plugin.json`・1 本目の仕様の冒頭の 1 行）: 線 A の最後の 1 commit（〔計〕Task 17「切り替え」）でだけ触る。1 本目の試験 `test_line.py` が 1 本目のラインの形と役の見本を縛り、`test_yaml_rules.py` が書く役を `blk-fix` の `fix` だけに許すので、ブロックの YAML の入れ替え・書く役を持つ `blk-refix`・線の YAML の入れ替えも同じ commit に入れる（〔計〕TA2）。merge の順は 写し直し → 土台 → A → B → C。

## 9. テスト

### 9.1 単体テスト（Archon 不要。`works/tests/run.sh`）

1. 修正案と事前審査: 0.21.0 の規則に良い返答と悪い返答（単位の書き落とし・2 案に入った単位・案に無い単位を指す穴・`no_add` の無い入口の穴・`faces_none` の無い空・番号で書いた `unit_keys`）を盤面の `done` で通し、悪い方を拒むこと（〔計〕Task 11）。
2. 修正前の関所の項目: `narrows`・`regression`／`policy` の穴・方針の文書の変化のそれぞれ 1 つで盤面が人に聞く状態になり、どれも無ければならないこと。前に `continue` で通した同じ行は再び聞かない。方針の変化を通すと版を固め直す（どれも写しの規則を盤面の上で当てた結果として見る）。
3. 数え直し: 種のリポジトリ（`dev/target-seed`）と見本の返答で、`class_query` を修正前後で数えること。件数が減っていない返答・`closure.sites` が母数と合わない返答・修正が在るのに閉鎖の実証が黙る返答を拒むこと（〔計〕Task 12）。
4. 2 往復: 盤面の `p3.fix_delta2` が手直しだけの差分を切ること。`delta_owed`／`delta_owed2` が穴と塞がっていない検算を組むこと。義務の全部に答えない手直しを拒むこと。3 往復目が無いこと（〔計〕Task 13）。
5. 手厚さと入口: `軽量`（持ち主の決定の文）・`重厚` を理由つきで拒むこと。`gates`・`mid_gate`・`adapter` に知らない値を渡すと拒むこと。宣言も `test_cmd` も無ければ盤面を作らずに拒むこと。**graph の全部の節が、周の箱の done・na・skipped のどれかに在るか、止めた後の待ちとして止めた理由を持つこと**、節の表の absent の全部が毎周の添え書きに在ること（黙った欠けを機械で 0 にする検査。〔計〕Task 16 `test_no_silent_gap`）。
6. 止め札・読んだ証拠・包み: 〔輪〕9.1 の 9〜11 と 12.6 と同じ（1 周に固定した盤面で。〔計〕Task 5・6・8・10）。
7. 境の節: 関所の答えの 4 つの語と文字列 `null`、一言の往復、判定の渡し替えの 3 つの場合（渡す・既に在る・拒まれる）、包みの確かめ、直す物が無い周の締め、中の関所の `always`／`when_needed`（〔計〕Task 10）。
8. 報告: 冒頭の 5 つの並び。6 つの結末。`next-request.json` が 1 本目の依頼の検査（`check_request`）を通ること（次の run にそのまま渡せる往復。〔計〕Task 15）。
9. 返答の型のずれ: 新しい役の節の `output_format` が 0.21.0 の graph の schema と一致すること（1 本目の仕様 5.4 の検査を広げる）。ブロックの出口が 1 本目の欄を含むこと。YAML の検査に 3 つ足す: `decisions` を持つ関所は `reject` を持つ・関所の文面と bash の本文はいつも走る節の欄だけを読む・script の節の `with:` が飛ばされうる節を読むなら `if_skipped` を持つ。〔試し P7・P8・P16 2026-09-26〕
10. 通し（Archon 不要）: スクリプトを線の順に子のプロセスで回し、全部の道（標準・直す物なし・関所の continue／stop／reject・中の関所・止め札を 9 つの境の節で 1 つずつ・拒否の後の出し直し・並行 PR が任せ先に落ちる・写し直しの前の異議が次の run の依頼に回る）を本物の盤面で通す（〔計〕Task 16）。写し直しの後は異議 → 再審・会話の id が無くて止まる道と 10 番目の境の節を足す（〔計〕Task 23）。
11. 前提（〔計〕Task 22）: `kind=実測` で出力の無い制約を拒む（写しの `measured_needs_output`）。依頼の `measured` を持つ行を制約が拾わない返答を拒む（`request_claims_covered`）。Bash で作業ツリーを変えた返答を拒む。判定役の入口に前提のファイルが届く。前提が盤面に無いまま `h-judge` に来たら止まる。
12. 再審（〔計〕Task 23。写し直しの後）: 異議の在る周で `p2.rejudge` が ready になり、会話の id が在れば回り、無ければ `h-rejudge` が役を起こす前に止める。`一部採る` → 再異議 → 2 回目 → 再異議 → 3 回目 → 第三の目の全部の道と、途中で決着する道・再異議を取り下げる道。`new_facts` が空同然の返答を拒む。争点でない単位の変化が `rejudge-diff.json` と報告の冒頭 1 に出る。回した後に再審の節のどれかが ready のまま残ればブロックが `ok: false`。
13. 包みの会話の継ぎ（〔計〕Task 5）: 印の読み方（2 つの綴り）、判定役の id の記録（包みが作る・SDK の `--resume` をそのまま記録）、`continue` の差し替え（SDK の 5 つの旗を外して `--resume <id>`・`--settings` と `--setting-sources` はそのまま）、id が無い時の exit 3（子を起こさない）、印の無い起動は 1 バイトも変えない、切符が無くても継ぐ、cwd ごとに分かれる、`no-post` の柵。〔継試〕の実物の argv を見本にする。
14. 並行 PR（〔計〕Task 21）: 交差 0 は engine で済み役を起こさない。交差が在れば `pr_go`。`handed_over: true` を拒む。下書きが報告の冒頭 1、下げた物が冒頭 2 に出る。
15. 費用（〔計〕Task 15）: 継いだ起動の費用から直前の起動の表示を引く。費用が取れなければその 1 行。

### 9.2 筋書き（`--dry-run`、お金を使わない。`works/dev/check.sh`）

- ブロックごと: blk-plan（通過／案の拒否の輪の形）、blk-refix（1 往復で終わる／2 往復目まで）、blk-fix（数え直しの拒否の輪の形）。模擬実行は輪を 1 回で済んだと見なす（線 C の MG25）ので、拒否 → 出し直し → 通過の中身は 9.1 で見る。
- ライン全体（切り替えの時 10 本、写し直しの後 12 本）: 直す物なし ／ 標準の全部の道 ／ 関所で `continue` ／ 関所で `stop` → report ／ 関所で `reject` → report ／ 中の関所が `when_needed` で緑なら開かない ／ 中の関所で `stop` ／ 境の節で止め札 → report ／ 入口の拒否（`start` で止まる）／ 並行 PR が任せ先に落ちる（`pr-checking` が走る）／ 写し直しの後: 異議 → 再審（`rejudging` が走る）／ 会話の id が無い（`h-rejudge` の stub が `stop: true` → report）。`standard` と入口の拒否の 2 本は `start` を stub せず本物で回し、`with:` が環境変数に届くことを模擬実行で見る（1 本目の `finish` と同じ役目。〔計〕TA16）。関所は模擬実行で自動で通るので、答えは境の節の stub で差す。輪の中の id を全部の include で一意に保つ（R19。`test_line.py` の重複の検査）。

### 9.3 Archon の試し（〔輪〕9.2 から、線 A に要る物だけ）

- P11（起動の関所 → `approve --detach` → cancel で木ごと止まるか）・P12（止め札の盤面の場所の引き方）・P13（script の節から出来事を取れるか）・P14（包みの柵が Edit・Write にも効くか）・P15（包みのプロセスグループで claude の孫まで止まるか）。どれも〔輪〕に書いた形のまま撃つ。
  - 結果（2026-09-26、〔試P〕）〔試し P11〜P13 2026-09-26〕:
    - P11 の AI 費用 0 の分: 条件付き。bash・script の節までは止まる。tree_run の猶予は 2 秒に直した（1ec7894）。関所で待つ run と前景の run には効かない（5.3）。AI の節の分は未確認（AI 要・費用の了承待ち）。
    - P12: 動く。盤面は `output_root` から組む（5.3）。
    - P13 の AI 費用 0 の分: 条件付き。呼び方が決まった（5.2）。`tool_called` の分は未確認（AI 要・費用の了承待ち）。
    - P14・P15: 未確認（AI 要・費用の了承待ち）。
  - AI を使う分（P11 の AI の節・P13 の `tool_called`・P14・P15）は〔計〕Task 18 にまとめ、持ち主の了承の後に撃つ。結果が出るまでの予備の道: P13 が不可なら読んだ証拠はフックだけ、P14 が不可なら柵は「Archon の sandbox だけ」と報告に出す、P15 が不可なら取り消しは非常用で止め札が普段の道。
- P16（新規。AI 費用 0）: 輪の外の `approval` の `decisions` に `respond … continue／stop` で答えられるか（〔輪〕の P1 は輪の中で確かめた）。飛ばした関所の出力を `with: {from:, if_skipped: null}` で読んでも落ちないか。
  - 結果: 動く。飛ばした関所は文字列 `null` で届く。`decisions` に無い `reject` は run を `cancelled` にするので、`reject` を足す（3.1）。〔試し P16 2026-09-26〕
- 包みの会話の継ぎ（〔継試〕2026-09-27）: 済み。平らな線でも `loop_group` の中でも、再審が判定役の会話を継ぎ、修正役には見えず、型つきの返答・sandbox・`--setting-sources` が残り、Archon の記録に会話の食い違いの警告が出ない。条件付きの 2 つ: 節の費用の表示が再開した節で判定役の分を重ねる（6 節で引く）・id が無い時に Archon が約 12 回起こし直す（`h-rejudge` の先の確かめで避ける）。実額は約 0.18 ドル（題の生成を足して 0.3 ドル弱）。
- 新しい試し（〔計〕Task 18 にまとめる）: P18（AI 要）並行 PR の任せ先の役が sandbox の下で `gh pr list`・`gh pr view` を読めるか、`no-post` の柵で `gh pr comment` が拒まれるか。P19（AI 費用 0）`archon workflow get --verbose --events --json` の出来事に節ごとの費用（`cost_usd`）が載るか（載らなければ報告の費用の行は「取れない」）。P20（AI 要。再審が入る写し直しの後）本物の修正役が `rejudge_requested` を書いた run で、再審が判定役の会話を継ぐか（〔継試〕は代役の役で見た）。
- AI を使う試しは合わせて 1 ドル未満の見込み（名目）。

### 9.4 実走（持ち主に費用を聞いてから。〔計〕Task 19）

- 使い捨ての対象に 2 本: ① 修正が今ある能力を狭めるバグを仕込み、修正前の関所が開く筋（`continue` で通す）② 標準で 2 往復目まで行く筋。止め札は ② の途中で 1 回置く。どちらも包みを通し、読んだ証拠が 2 つの出どころで出ることを見る。
- 費用の見込み: 1 本目は opus で 1 回 0.6 ドル前後（〔台帳〕Task 10。自分食いの 2 回は 1.00 と 0.75 ドル）。線 A は役が 3 つから最大 8 つに増え、修正の返答も重くなるので、1 回 1〜1.5 ドル（推測）。**上限の目安は 2 回で合わせて 3 ドル**（12 節の 1）。

## 10. review-graph（0.21.0）との能力の差

基準は、判定から入る run を 1 周で止めた review-graph（実物の盤面 wt-ci-skip・wt-layer1 の 1 周目で走った節と比べた）。表のあとに、残る欠けを全部並べる。

| 能力 | review-graph | 線 A の後 | 差 |
|---|---|---|---|
| 判定 | 有 | 有 | 同 |
| 判定への異議の往復 | 1 往復 | 3 往復（写し直し後） | 今は下・後に上 |
| 異議の会話が無い時 | 起きにくい | 止めて聞く | 条件付き |
| 前提の実測 | 有 | 有 | 同 |
| 依頼の実測の測り直し | 無い | 有 | 上 |
| 目的の文 | 有 | 無い（線 B） | 下 |
| 修正案・事前審査 | 有 | 有 | 同 |
| 修正前の人の関所 | 有 | 有 | 同 |
| 方針の文書を役へ | 全役 | 全役 | 同 |
| 修正後の数え直し | 有 | 有 | 同 |
| 中の関所（テストの後） | 無い | 有 | 上 |
| 審査・手直しの 2 往復 | 有 | 有 | 同 |
| 手直し 2 回目の検算 | 次の周 | 次の run | 形 |
| テストの宣言を走らす | 有 | 有 | 同 |
| CI を engine が確かめた印 | 有 | 有 | 同 |
| 周の記録と検証器 | 有 | 有 | 同 |
| 報告の前の検証器 | 有 | 有 | 同 |
| 直す物が無い周の締め | 有 | 有 | 同 |
| 外から止める | 有 | 有＋取り消し | 同〜上 |
| 子を木ごと止める | 有 | P15 待ち | 同か下 |
| 読んだ証拠 | フック | P13 待ち | 上か同 |
| 起動ごとの柵 | 任せ先・Bash 役 | P14 待ち | 上か下 |
| 手厚さの段 | 無い | 標準だけ | 同 |
| 並行 PR の交差の検査 | 有 | 有 | 同 |
| 並行 PR の申し送り | 投稿 | 下書きを報告に | 下 |
| P1 の目 | 1 周目は無い | 無い | 同 |
| R1〜R4 | 有 | 無い | 下 |
| 修正後の人の関所 | 有 | 無い | 下 |
| 変異の検算 | 有／merge | 無い | 下 |
| AI が書く報告 | 有 | 機械の要約 | 下 |
| 報告の初見検査 | 有 | 無い | 下 |
| 記録器 | 有 | 無い | 下 |
| 仕様から入る | 有 | 無い | 下 |
| TDD の修正 | 有 | 無い | 下 |
| 無人で回す | 有 | 無い | 下 |

試しの結果で評価が決まる 3 行（〔計〕審査 I6。試しは〔計〕Task 18、費用の了承待ち）:

- **読んだ証拠**: P13（`tool_called` の Read に `file_path` が載る）が可なら「フック＋出来事」で上。不可か未確認ならフックだけで同（review-graph と同じ）。未確認の間、出来事の出どころは `unverified` と書き、報告の冒頭 4 に「出来事: 未確認（P13）」と出す。
- **起動ごとの柵**: P14（包みの `denyWrite`・`permissions.deny` が Edit・Write に効く）が可なら全役で上。不可なら柵は Archon の sandbox だけになり、review-graph の任せ先の柵（起動ごとに守る場所を組む）より下。
- **子を木ごと止める**: P15（包みのプロセスグループで claude の孫まで止まる）が可なら同。不可なら AI の節の孫が取り消しの後に残りうるので下（止め札は次の境の節で効くので、普段の止め方は変わらない）。

〔答〕で決まった 3 行の読み方:

- **判定への異議の往復**: 写し直しの後に上。本線の 3-6 の形（再審 3 回・修正役の再異議 2 回・第三の目）で入れる（3.7）。0.21.0 の review-graph は往復が 1 回で止まり第三の目が立たないので、3-6 の形はそれより上。写し直しまでは absent（下・宣言）。異議を出すのは修正役の返答の `rejudge_requested`（graph の `p3.fix` の欄と同じ）。再審は判定役の会話の続き（包み）、3 回とも決着しなければ新しい会話の第三の目で、どれも盤面の規則が ready を決める。判定役はどの単位も変えてよく、争点でない単位の変化は記録と報告の冒頭に出す（review-graph は出さないので、ここは上）。会話の id が無い時だけ、再審せずに止めて人に聞く（「異議の会話が無い時」の行。条件付き。review-graph は engine が会話の番号を盤面の instance に持つので、盤面が残る限り起きにくい）。包み無しの run（`adapter: optional`）はいつもこの行に当たる。
- **前提の実測**: 同。写しの schema と `measured_needs_output` そのもの。加えて、依頼者が `measured` に書いた値を作業ツリーで測り直させ、拾わない返答を拒む（「依頼の実測の測り直し」。review-graph の `p0.premises` は依頼の本文を読むだけで、`measured` を行ごとに拾わせる検査は無い）。
- **並行 PR**: 交差の検査（1〜5 段の engine と、任せ先の役の 6 段の読み）は同。担当の PR へ申し送りを投稿しない所だけ下（〔答〕2。持ち主が選んだ下げ方）。下書きは報告の冒頭 1 に出るので、人が投稿すれば review-graph と同じになる。

残る欠け（どれも節の表の absent か下げた物の一覧・毎周の添え書き・報告の冒頭に出す。黙った欠けは 0 にする）:

- **目的の文**（`p0.purpose`、optional の `p0.purpose_review`・`p0.prior_decisions`）: review-graph は判定から入る 1 周目でも走らせ、判定役は凍った目的の文を読む。〔答〕3 で線 B に入る（線 B の計画の `blk-purpose`）。線 A のラインへの取り込みは未定で、それまで absent（1 本目にも無いので、今ある能力は減らない）。
- **並行 PR の申し送りの投稿**: 上の 3 行目。`darkfactory/downgrades.json` の 1 行。
- **R1〜R4 と、R4 の後の人の関所の中身**: 修正の後に消えた能力と方針とのぶつかりを人に上げる所が無い。修正の前の関所（修正案の `narrows` と事前審査）が、書く前の予測としてだけ受ける。盤面の機械の節 `r4.human_gate` は走るが、R4 の役が無いので項目は方針の文書の変化だけになる。R 系のブロックが入るまで残る。
- **変異の検算**: 線 C（`mutgate`。リリースの時にまとめて撃つ）。`gates=merge` の run は graphloops でも撃たない（残る義務として報告に出る）。
- **AI が書く報告と初見検査**（`report`・`report.human_items`・`report.cold_check`）: 6 節。線 A は一歩で、review-graph と同等と言う前に足す（〔台帳〕R27）。
- **記録器**（0.21.0 の `intake.jsonl` と `/graphloops:intake`）: 踏んだ問題を利用者の環境に残す所が無い。Archon の run の記録は残る。
- **仕様から入る道・TDD の修正**: 別の入口 `darkfactory-spec` と `blk-fix-tdd` で後に入る。
- **無人で回す**（`--unattended`）: Archon の関所は答えを待ち続ける。修正前の関所が開いた run は人が答えるまで止まる。graphloops の無人の run も、この関所では保守的に止まる。止まった後に答えを待つか、止まって終わるかが違う。
- 「周の記録と検証器」は 1 版で下にしていたが、盤面の `settle` が `p4.record`・`converge` まで engine と同じに回すので同になった（〔盤〕8.1 の「足される能力」）。

## 11. 危うい所

- **今壊れている物**: 無い。この文書は今の 1 本目の線を壊さない（出口の欄は全部残す）。
- **壊れる余地**:
  - `blk-tests` の既定の形を変えると、線 C の `mutgate`（盤面を使わず `cmd` だけで include する）が merge の後に壊れ、模擬実行では見えない（筋書きが `control` を stub するため）。既定 `plain` を 1 本目のまま残し、約束を単体テストで固定する（〔計〕Task 14 `test_plain_mode_is_mutgate_contract`）。
  - 線 A のブロックは線 B の周 2 以上の盤面でも使われる。周の番号を仮定したパスを書くと周 2 で壊れる。作業ファイルは `b.work`、役の出力は `state.outputs`、engine の走りのログは `run_engine` の返りから引く（〔計〕TA17）。
  - 途中の枝で 1 本目のラインを本物で走らせると止まる（〔計〕Task 12〜15 の後、Task 17 の切り替えまで。ブロックの受け付けが盤面を要るため）。試験と模擬実行は緑のまま。途中の枝で実走しない。
  - 切り替え（〔計〕Task 17）は 1 つの commit が大きい（ブロックの YAML 4 本・線の YAML・筋書き・共有の試験・スキル）。〔計〕Task 16 の通しの試験で、スクリプトの側の全部の道を切り替えの前に通しておく。
  - 判定の渡し替え: 1 本目の受け付け（偽の盤面）が通した `judgment.json` を盤面の受け付けが拒む道が在る（`check_record`・番号の読み替えは偽の盤面に無い）。拒まれたら書く役の前で止まり、理由が報告に出る。線 B の判定 v2 が盤面で受けるようになれば消える。
  - 0.21.1 で規則の関数の形・名前が変わる（ブロック分け 3-1/3-3）。盤面の口と、線 A の 1 か所（`refix.passes()` など）で受ける。
  - 修正役の返答の型が大きくなり（0.21.0 の `p3.fix` は必須の欄 12）、出し直しと費用が増える。1 本目の実走で修正の出し直しの道は一度も通っていない（〔台帳〕Task 10）。実走で必ず通す。
  - 数え直しは、判定役が書いた `class_query` を script の節が作業ツリーで走らせる（graphloops の engine と同じ）。script の節は Claude の sandbox の外で走る。形の検査は写した規則の `_run_query` に任せる。
  - 関所の `decisions` に `reject` を書き忘れると、`reject` で run が `cancelled` になり `report` が走らない。YAML の検査で縛る（9.1 の 9）〔試P: P8・P16〕。〔試し P8・P16 2026-09-26〕
  - 関所の文面と bash の本文が、飛ばされうる節の欄を読むと落ちる〔試P: P7〕。境の節の欄だけを読む決まりを同じ YAML の検査で縛る。〔試し P7 2026-09-26〕
  - 直す物が無い周を締めるため、機械が `p3.fix` の空の返答を渡す（〔計〕TA6）。写しの `p3.fix` の型が変わると通らなくなる。単体テスト（〔計〕Task 9 `test_empty_fix_passes_rule`）で縛る。
  - 最後のテストの後に run の途中で方針の文書が変わっていると、盤面の `r4.human_gate` が人に聞いたまま終わる（結末 `needs_human`）。Archon の関所はそこに無いので、答えは次の run で扱う（報告の冒頭 1 に問いを出す）。
  - 中の関所の既定 `always` のままなら、人の関所は起動の関所と合わせて 1 run に 2 つ以上になる（1 本目と同じ手間）。
  - 包みの版上げでの壊れ方・出来事の遅れ・取り消しが AI の節の子まで届くか: 〔輪〕8 節と同じ（P13 の `tool_called` の分・P14・P15・P11 の AI の節の分。どれも未確認（AI 要・費用の了承待ち））。〔試し P11・P13 2026-09-26〕
  - 線 A と線 B が `blk-judge`・`darkfactory/` を同時に触るとぶつかる。8 節の分け方で避ける。
  - 会話の継ぎ（〔継試〕の「壊れる余地」）: ① 費用の二重計上（報告の費用の行で引く。Archon の run の合計の表示は重なったまま。SKILL に書く）② id が無い時の 12 回の起こし直し（`h-rejudge` の先の確かめで避ける。確かめの後に id が消える競合だけが残り、その時は約 40 秒・AI の費用 0 で節が落ち、`dev/report.sh` の報告になる）③ SDK の版上げで `--resume=` の綴りや `--json-schema` の渡し方が変わる（実物の argv の見本の試験で見る）④ 印は `output_format` に依る ⑤ cwd で分けている（同じ worktree で同じ節名の run が並ぶと上書き）。
  - 前提の役と並行 PR の任せ先の役は Bash を持ち、包みの確かめ（`h-judge`）より先に走る。包みの無い環境では、この 2 つの起動に包みの柵（`denyWrite`）が付かない。作業ツリーの変化は受け付けの写しの比べで拒むが、盤面や `.git` への書き込みは Archon の sandbox だけで守る（書く役ではないので、指示書でも書かせない）。CI の任せ先の役（blk-ci。これも `h-judge` より先に走る）はこれより広い: sandbox が `allowWrite ['/']`（graphloops の任せ先と同じ）なので、包みの無い起動では盤面も `.git` も Archon の sandbox では守れない。包みを宣言した run では受け付けが包みの起動の記録で柵を確かめ、包み無しの run（`adapter: optional`）は graphloops と同じ晒され方で回して、その旨を報告に出す（5.1。裁定 R58）。
  - 並行 PR の任せ先の役が sandbox の下で `gh` の通信をできない環境がある（P18 で見る）。できなければ役は `material.status` を `not_run` か `awaiting_human` で返し、報告の冒頭 1 に出る（黙らない）。
  - 本線の 3-5・3-6 を写すと、盤面の層の受け付け・`accept.py`・線 C の `mutcore` が壊れる（今は壊れていない。〔本〕3.5）。写し直しの線が直す（7 節の「写し直しへの依存」）。線 A のスクリプトは写しの規則の関数を直に呼ばない（盤面の口と `refix.passes()` の 1 か所だけ）ので、線 A の側で直す所は `refix.passes()`（`DeltaPass.state_key` が消える）と、再審の節の名前の表だけの見込み。
  - 前提の役が依頼の `where` を制約の `text` に写す決まり（`request_claims_covered`）は文字列の含みで見るので、`where` を言い換えた行は拾えない。指示書で「そのまま入れよ」と書き、拒否の文に拾えなかった `where` を並べる。

## 12. 聞くこと（推しつき）

1. **実走の費用**（9.4）: 推し: opus で 2 回、合わせて 3 ドルを上限の目安にする（名目）。9.3 の試しが通ってから撃つ。**持ち主の答え待ち**（〔台帳〕Pending owner）。
2. **周の輪のラインを別の入口にするか**: 決まった（〔台帳〕R25）。線 B は `darkfactory-rounds/` に作る。既定の `darkfactory` は 1 周の run のまま。入れ替えは B が終わってから決める。
3. **1 本目の関所（テストの後・審査の前）を外すか**: 決まった（〔台帳〕R26）。外さない。入力 `mid_gate`（`always`・`when_needed`、既定 `always`）で残す（2 節）。
4. **初見検査をいつ足すか**: 決まった（〔台帳〕R27）。線 A には入れず、欠けの表に「同等と言う前に要る」として載せる（6 節・10 節）。
5. **「軽量」で optional でない節を省いてよいか**（〔盤〕13 節の 1）: 決まった（〔答〕1: 案 1）。省かない。標準だけを受け、`軽量`・`重厚` は理由つきで拒む（4 節）。〔計〕Task 20 は「下げない」で閉じた。
6. **並行 PR の任せ先の役に、他人の PR へ申し送りを投稿させるか**（〔盤〕13 節の 2）: 決まった（〔答〕2: 案 (a)）。読むだけの opus の役にし、申し送りの下書きは報告に載せ、投稿しない。下げたことは 10 節の表と報告の冒頭に出す（3.8。〔計〕Task 21）。
7. **AI を使う試し P13・P14・P15 の費用**（9.3）: 合わせて 1 ドル未満の見込み。**持ち主の答え待ち**。答えまでは予備の道（9.3）。10 節の 3 行の評価はこの結果で決まる。〔答〕で P18・P20（AI 要）を足した。見込みは合わせて 1 ドル未満のまま（P20 は実走の 1 本に寄せられる）。
8. **判定への異議の往復（`p2.rejudge`）の持ち方**: 決まった（〔答〕4）。review-graph の上位互換にする。包みが判定役の会話を継ぎ（〔継試〕で確かめた形）、第三の目は新しい会話、会話が無い時は止めて聞く（3.7・5.1。〔計〕Task 5・23）。回す側の指示（2026-09-27）で、形は本線の 3-6（3 往復）にし、写し直しの後に入れる。それまでは absent（宣言）。
9. **目的と前提**: 決まった（〔答〕3）。前提 `p0.premises` は線 A（3.6。〔計〕Task 22）、目的 `p0.purpose` は線 B（線 B の計画）。線 A では目的の文は absent のまま。

## 改訂 1（2026-09-27。盤面の層の設計・台帳の裁定・実装計画に合わせた）

- **土台の差し替え**: 共通の土台を〔輪〕3 節から〔盤〕（`DiskBoard`）に替えた（冒頭・0 節・1 節の 2）。版を固める・差分を切る・義務を組む・人の関所の項目・周の記録と検証器・収束は盤面の `settle` が写しの機械の節で回し、線 A は自前で持たない。これに合わせて 3.1 の `mode`・`gate-items`、3.3 の版固めと `owe`、3.4 の `cut2` の切り方と `owe2` を消し、ブロックは役の返答を `done` で渡して盤面の `ready` を読むだけにした。
- **写し直しは済んだ**（1 節の 3）: 0.21.0（a1202d0。0.21.1 は出ていない）。
- **ラインの形**（2 節）: 境の節を 8 つ（`h-plan`・`h-gate`・`h-fix`・`h-mid`・`h-midgate`・`h-review`・`h-refix`・`h-tests`）にし、`when:` と関所の文面は境の節の欄だけを読む形にした（〔計〕TA1）。判定は `h-plan` が盤面へ渡し替える（〔計〕TA3）。
- **中の関所を残した**（2 節・4 節・12 節の 3）: 〔台帳〕R26 のとおり、入力 `mid_gate`（`always`・`when_needed`、既定 `always`）と、修正の後のテスト（`blk-tests` の `mid`）。1 版の「1 本目の関所は外す」を取り下げた。
- **直す物が無い run も周を締める**（2 節。〔計〕TA6）: 1 版の「`planning` 以降を飛ばして `report` へ」を改めた。
- **テスト**（3.5）: 最後のテストは盤面の `run_engine("p4.ci")`、中の関所のためのテストは `mid` の形。
- **方針の届け方**（3.1・8 節）: 方針の文書の固定は盤面を作る時の `on_init`。役へは `start` が組んだ `policy_paste`・`policy_path` をブロックの入力で届け、`blk-judge` には節を足さず入力 1 つと指示書の 1 段落だけにした（〔計〕TA10）。
- **手厚さ**（4 節）: 持ち主の答えまで「標準」だけ（〔盤〕BL27）。軽量の表は答えが案 2 の時の参考として残した。
- **省いた印**（4 節）: `start` が `process.skipped` に書く形から、節の表の absent と毎周の添え書きに替えた（〔盤〕BL4・BL22）。`p0.parallel_pr` は答えまで absent（〔盤〕BL28）。
- **包みの確かめの時機**（5.1）: 最初の `<役>-reads` から、最初の境の節 `h-plan` に替えた（書く役の前に必ず確かめる。〔計〕TA9）。
- **止め札の記録**（5.3）: 盤面の `stop(理由, by)` で記録する形にした（〔盤〕BL10）。tree_run の猶予の直しは済んだ（1ec7894、〔台帳〕R31）。
- **報告**（6 節）: 結末に `stopped_by_line`・`needs_human` を足し、`finalize` の後に組む形にした（〔計〕TA12）。報告の節の absent の理由に〔台帳〕R27 を書いた。
- **持ち物**（8 節）: 〔盤〕6 節の表を正本にし、線 A の新しい試験のファイルの名前を足した。共有のファイルとブロック・線の YAML の入れ替えを最後の 1 commit にまとめる理由を書いた（〔計〕TA2）。
- **テスト**（9 節）: 境の節・通しの試験・筋書き 8 本を足し、AI を使う試しの予備の道を書いた。
- **能力の差**（10 節）: 「目的と前提の確認」（下。〔計〕TA14）・「並行 PR の検査」（答え待ち）・「中の関所」（上）・「CI を engine が確かめた印」（同）・「直す物が無い周の締め」（同）を足し、「周の記録と検証器」を下から同に、「手厚さの段」を「標準だけ・同」に直した。
- **聞くこと**（12 節）: 2・3・4 は台帳 R25・R26・R27 で決まった。〔盤〕13 節の 2 つと AI の試しの費用を足した。新しく聞く事は無い。
- **平易版・0 節・7 節**: 平易版の手厚さと省いた印の書き方を今の形に直し、0 節に「境の節」を足し、7 節の表の持ち方（テストは盤面の `run_engine`、方針は盤面が固める、`r4.human_gate` の機械の節は走る）と、名前が変わりうる所の受け方（`refix.passes()` の 1 か所）を直した。

## 改訂 2（2026-09-27。計画の審査 作業の控え（scratchpad）の `trackA-plan-review.md` への対応）

計画の側の直しは〔計〕の「改訂 2」に全部ある。この文書で直した所だけを並べる。

- **I1**（3.5・11 節）: `blk-tests` の既定を `plain`（1 本目と線 C の `mutgate` の約束のまま）にし、`mid`・`final` は明示で渡す形にした。壊れる余地に線 C の include を足した。
- **I2**（11 節）: ブロックは周の番号を仮定しない、を壊れる余地に足した。線 B の申し送り 1〜4 は〔計〕TA18（`board_hook.py`・`local_checks_material`・報告の部品・判定の試験の緩め）。
- **I3**（6 節・10 節）: 報告の前に `settle` → `finalize` → `run_validator` → `report_accepts` の関所を必ず通し、通らなければ結末 `record_invalid`、とした。`fixed`・`no_fix_needed` はこの関所を通った時だけ。10 節の表に「報告の前の検証器 | 同」を足した。取り消し等で落ちた run の結末 `interrupted` を足した。
- **I4**: 仕様の形は変えない（配線の突き合わせは〔計〕TA16 と Task 17 の試験）。
- **I5**（10 節・12 節）: 表と「残る欠け」に「判定への異議の往復（`p2.rejudge`・`p2.rejudge_third`）」を足し、持ち主の答え待ち（線 B が聞いた。案 3 つ。答えまで absent）と書いた。12 節の 8 に同じ件を「線 A から新しく聞く事ではない」として足した。
- **I6**（10 節）: 読んだ証拠・起動ごとの柵・子を木ごと止める、の 3 行を試しの結果しだいの評価（「上か同」「上か下」「同か下」）にし、不可の時の評価と、未確認の間の報告の出し方を書いた。
- **M2**: 役に返すのは中身の誤り（`AnswerReject`）だけ、は〔計〕TA19。〔盤〕8.1 の「Reject のまま」の文の直しは盤面の層の持ち物なので、回す側から渡してほしい。

## 改訂（持ち主の答え 2026-09-27）

朝の 4 つの答え（〔答〕）を入れた。改訂 3 と呼ぶ。計画の側の直しは〔計〕の同じ名の節。

- **1. 軽量は案 1（下げない）**: 4 節。受けるのは標準だけ。`軽量` は「graph で省けない節を省くことになる（持ち主の決定）」、`重厚` は「重厚で足す工程がまだ無い」で、`start` が AI を起こす前に拒む。省く配管（表の `downgrade`・`state.works.downgrades`）は作らない。効かなくなった入力 `thickness_decider` と「段ごとに回すブロック」の表を消した。12 節の 5 を決まったにした。〔計〕Task 20 は「下げない」で閉じた。
- **2. 並行 PR は案 (a)**: 3.8 を足した。`p0.parallel_pr` は `engine_run`・`fallback: role`。交差 0 は engine で済み、任せ先に落ちた時だけ読むだけの opus の役 `pr-check`（ブロック `blk-pr`）が 6 段をし、申し送りは下書きとして報告の冒頭 1 に載せ、`handed_over: false` で返す（真は拒む）。投稿しないことは 10 節の表（「並行 PR の申し送り」が下）と、下げた物の一覧 `darkfactory/downgrades.json` と、報告の冒頭 2 に出す。包みの印 `no-post` で `gh` の書き込みの語を柵に足す（補助）。12 節の 6 を決まったにした。
- **3. 前提と目的**: 3.6 を足した。`p0.premises` を判定の前のブロック `blk-premises` で回す。写しの schema と `measured_needs_output`（`kind=実測` はコマンドと出力が要る）に加え、依頼の `measured` を測り直させ、拾わない返答を拒む（`request_claims_covered`）。判定役には `blk-judge` の入口 `premises_file` で届ける（線 A の波 2 の 1 度の手入れに足した）。目的 `p0.purpose` は線 B に入り、線 A では absent のまま（10 節）。12 節の 9 を足した。
- **回す側の指示（本線の調べ〔本〕から。2026-09-27）**: 再審は本線の 3-6 の形（再審 3 回・修正役の再異議 2 回・第三の目）にし、写し直しの後に入れる（3.7。0.21.0 の形は第三の目が立たない穴がある）。写し直しは 3-5・3-6 が版に入ってからで、その時に要る物を 7 節と〔計〕の「写し直しへの依存」に書いた（線 A の作業ではない）。ブロックの名前と `where` は今は works の仮の名で、本線の 3-7 の後に揃える（7 節。〔計〕Task 25）。受け付けの口は本線の 3-8 まで `accept.py` のままで検査を足さず、works だけの検査はブロックのスクリプトに置き、`gl` への対応表を〔計〕Task 24 で作る（7 節）。止める猶予は works の 2 秒のまま（本線は呼ぶ側が選べる形・既定 5 秒にする）。10 節の表の「判定への異議の往復」を「今は下・後に上」にした。
- **4. 同じ周の再審は上位互換**: 3.7 と 5.1 の「判定役の会話の継ぎ」を足した（〔継試〕の形）。印 `works-node: <名>[ continue=<名>]` を `output_format` の `description` に置き、包みが argv の `--json-schema` から読む。判定役は包みが作る `--session-id` で起こして `sessions/<cwd の hash>/judge.id` に記録し、再審は SDK の会話の旗を外して `--resume <id>` で起こす。YAML は `context: fresh`。id が無ければ包みは exit 3 で止まるが、先に境の節 `h-rejudge` が確かめて盤面を止め、報告で人に聞く。第三の目は新しい会話。判定役はどの単位も変えてよく、争点でない単位の変化は `rejudge-diff.json` と報告の冒頭 1 に出す。費用は、継いだ起動から同じ会話の直前の起動の表示を引く（6 節）。10 節の表の「判定への異議の往復」を（上の回す側の指示で）「今は下・写し直しの後に上」に、「異議の会話が無い時」を条件付き（止めて聞く）にした。12 節の 8 を決まったにした。
- **ラインの形**（2 節）: `pr-checking`・`premising`・`h-judge`・`h-rejudge`・`rejudging` を足した。境の節は 10 になった。包みの確かめは `h-plan` から `h-judge`（前提の役の後・判定の前）へ移した（5.1）。
- **持ち物**（8 節）: 新しいブロック 3 つとモジュール 4 つ（`node_marker`・`premises`・`rejudge`・`prcheck`）を足した。線 B の `blk-judge` への 1 度の手入れに、入口 `premises_file`・判定役の印・`test_blk_judge.py` の 1 つの試験の比べ方を足した。
- **試験と試し**（9 節）: 単体の 11〜15、筋書き 3 本、試し P18〜P20 を足した。〔継試〕の結果を 9.3 に書いた。
- **危うい所**（11 節）: 会話の継ぎの 5 つの壊れる余地、Bash を持つ読む役が包みの確かめの前に走ること、`gh` の通信、`where` の文字列の含みを足した。今壊れている物は無いまま。
