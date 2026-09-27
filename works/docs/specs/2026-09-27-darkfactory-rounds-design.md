# darkfactory の周の輪（線 B）の設計（2026-09-27。盤面の層に載せ替え）

状態: **改訂 6 まで反映**（線 A の計画の Task 1 と同じ commit でリポジトリに置いた。審査 作業の控え（scratchpad）の `rounds-plan-review.md` の C1・I1〜I7・m1〜m10 を反映した「改訂 5」と、持ち主の朝の 4 つの答えを入れた「改訂 6（持ち主の答え 2026-09-27）」。どちらも末尾）。3 版（作業の控え（scratchpad）の `rounds-spec-draft.v3.md`）は自前の盤面を作る前提だった。いま実装中の「盤面の層」（線 A・B・C の共通の土台）の上に載せ直し、土台と線 A に移った物を外した。持ち主の決定（1.1）は全部そのまま守る。4 版で聞いた 1 つ（12 節の 1: `p2.rejudge`）と前から答え待ちの 2 つ（軽量・並行 PR の申し送り）と目的・前提の持ち方は、2026-09-27 の朝に全部答えが出た（1.3・改訂 6）。実装計画は `works/docs/plans/2026-09-27-darkfactory-rounds.md`。3 版からの対応は末尾の「改訂（盤面の層に載せ替え）」。

## 平易版（3 行）

- いまの darkfactory は「判定 → 修正 → テスト → 審査」を 1 回だけ流す。線 B は、これを「直ったと言えるまで何周も回す」別の入口 `darkfactory-rounds` にする。何周目に何をするかは、graphloops（このリポジトリの既存のプラグイン）の engine と同じ順で盤面の層が決め、線 B は周の間の人への問いと止め方と締め方だけを持つ。
- 人に聞くのは要るときだけ。判定役が人への問いを出したら、その周の残りを飛ばしてすぐ聞く。ほかは周の終わりに、テストが赤・同じ block が 3 周続く・周の上限・変異の関門の記録待ち、のときだけ聞く。答えの後は止まった所から同じ周を続け、「判定からやり直せ」は次の周として回す。
- 周の頭では、並行 PR の交差の検査・前提の実測・目的の文を 1 周目に作り（線 A のブロックと線 B の `blk-purpose`）、修正役が判定に異議を出したら同じ周のうちに判定役の会話の続きで再審する（線 A の包みとブロック）。まだ作っていない工程（P1 の目・R1〜R4 など）は「このラインは集めない」と節の表に書き、毎周の記録と報告の冒頭に出す。変異の検算は線 C（mutgate）の記録を最後の関門として読む。

## 0. 略記と出典

- **盤面**: run の間ずっと残る状態の置き場 `$ARTIFACTS_DIR/board/`。形は graphloops の engine の盤面そのもの（〔土〕3 節）。
- **盤面の層・土台**: 盤面を開いて写した規則を当てる works の部品 `works/.shared/core/board.py` の `DiskBoard`。いま枝 `wip/works-board` で実装中（〔土計〕の Task 1〜5 は済み、Task 6 以降が進行中）。
- **節の表**: ラインごとの 1 ファイル。graph の全部の節（60 個）を、このラインで「役・機械の返答・engine が走らせる・機械の節・このラインに無い（absent）」のどれで持つかに振る（〔土〕4.2）。
- **ready（待ちの節）**: 土台の `settle` が返す `Progress.ready`。依存が済み、条件にも当たり、ラインが次に作るべき節の一覧（〔土〕4.1）。
- **asking（人への問い）**: 土台の `Progress.asking`＝engine の `pending_human`。周の終わりの `converge` と、修正の前の `p2.human_gate` が立てる。
- **一時停止（pause）**: engine には無く線 B が足す「人に聞く所」。判定の直後の問い・テストが赤・同じ block が続く・変異の関門の記録待ち（2.3）。
- **周**: graphloops の 1 ラウンド。周の番号は engine が持つ（線 B は数えない）。
- **ブロック**: Archon の include で入る工程の部品（`blk-*`）。**境の節**: ブロックの間に置く、いつも走る script の節（`h-<段>`）。**関所**: Archon の `approval` の節。**唯一の末端**: 輪の本体で後ろに節を持たない節がそれ 1 つだけの形。
- **線 A・B・C**: 持ち主が並べて回すと決めた 3 本（〔台帳〕Owner decision 2026-09-26）。A＝1 回の run を強くする、B＝この文書、C＝変異の関門のライン `mutgate`。
- **RL**: 写しの規則 `works/.shared/core/graphloops/rules/review-loop.py`。**RR**: 写しの検証器 `works/.shared/core/scripts/review-record.py`。**graph**: 写しの `graphloops/graphs/review-loop.json`（graph_sha `f9897bb07384`）。写し元は graphloops 0.21.0 の commit **a1202d0**（〔土〕BL1）。
- 出典の印:
  - 作業の控え（scratchpad） = 設計の会話の一時フォルダ `/private/tmp/claude-1341252503/-Users-p03623-src-claude-plugins-work1/c495892b-6158-4a8d-ad53-ea7a3361cb23/scratchpad`。リポジトリには入っていない（下の「作業の控え（scratchpad）の …」は出典を辿るための控えで、消えていることがある）
  - 〔土〕= 盤面の層の設計 `/Users/p03623/src/claude-plugins-work1-board/works/docs/specs/2026-09-26-board-layer-design.md`（節の番号・裁定 BL1〜BL29）。〔土計〕= その計画 `…/works/docs/plans/2026-09-26-board-layer.md`
  - 〔A〕= 線 A の設計 `works/docs/specs/2026-09-27-darkfactory-single-run-design.md`。〔A計〕= 線 A の計画 `works/docs/plans/2026-09-27-darkfactory-single-run.md`（裁定 TA1〜TA14 と Task の番号）
  - 〔C〕= mutgate の設計 `/Users/p03623/src/claude-plugins-work1-mutgate/works/docs/specs/2026-09-26-mutgate-design.md`（7 節が記録の形）
  - 〔台帳〕= `/Users/p03623/src/claude-plugins-work1/.superpowers/sdd/2026-09-26-darkfactory-v1/progress.md`（Ruling R1〜R32 と Owner decision）
  - 〔研〕= 作業の控え（scratchpad）の `rounds-research.md`、〔試〕= 作業の控え（scratchpad）の `rounds-probe-summary.md`、〔試d〕= 作業の控え（scratchpad）の `probe-d-summary.md`、〔試P〕= 作業の控え（scratchpad）の `probes-p7-p16-summary.md`（〔試P: P<n>〕はその節）
  - 〔写〕= 写しの中の行（RL・RR・graph・`engine/*.py`。a1202d0 と同じバイト）。〔A/〕= Archon v0.11.1 の源 作業の控え（scratchpad）の `aw/archon-v0.11.1/`
  - 〔3版〕= この文書の前の版 作業の控え（scratchpad）の `rounds-spec-draft.v3.md`
  - 〔継試〕= 包みで後の AI の節が前の AI の節の会話を継ぐ試し 作業の控え（scratchpad）の `resume-probe-summary.md`（2026-09-27。平らな線と `loop_group` の中の両方で動いた）
  - 〔答〕= 持ち主の答え（2026-09-27 の朝）。1: 軽量は案 1（下げない）。2: 並行 PR は案 (a)（読むだけの役・申し送りは報告に）。3: 前提 `p0.premises` を線 A に、目的 `p0.purpose` を線 B に。4: 同じ周の再審は review-graph の上位互換（包みの会話の継ぎ）

## 1. 前提

### 1.1 持ち主の決定（周の輪。〔台帳〕と memory の works-pack）

1. **収束は案 B**: 足りない工程は「このラインは集めない」と明示し、収束を止めない。graphloops の芯（連続 2 周の阻害なし・問いの台帳・defer と開き直しの証拠・3 周続く block・ラチェット）は残す。報告の冒頭に省略を並べる。欠けたブロックを足すたびに省略が 1 つ消え、全部消えれば graphloops と同じ収束（案 A）になる。
2. **人には早く聞く**: 判定役が人への問い（台帳の `escalate`・`fork`）を出したら、周の残りを飛ばしてすぐ関所へ。答えの後は同じ周の止まった所から続ける。
3. **関所は周の終わりに、要るときだけ開く**: テストが赤・人への問いが残る・同じ block が 3 周続く・周の上限。1 本目の「テストの後・審査の前」の関所は周の輪では置かない。3 周ごとの定期の点検は置かない。
4. **役の会話を分ける**: 書く役と採点する役は会話を共有しない。
5. **人が「判定からやり直せ」（rejudge）と答えたら、同じ周の判定を回し直さず、周を締めて次の周の判定として回す**。
6. **p2.history は案 (d)**: 同じ判定役の節を 2 回起こす。1 回目は履歴なしで判定、2 回目は同じ会話の続きに前の周の記録を渡す。予備は案 (c)（新しい会話が 1 回目の返答ファイルを読む）。配布版 v0.11.1 で動くと確かめ済み〔試d〕。
7. **運ぶのは機械で、LLM ではない**: 役が読む物は機械が選んで渡す。
8. **外から止める**: graphloops の後の版の `cmd_stop` の意味（理由は必須・記録する・報告は必ず出す・子は木ごと止める）。作るのは線 A（1.2）。
9. **決め方**: graphloops の review-graph と能力で同等以上の物は推しで決めて台帳に残し、能力が下がる物だけを聞く。費用と外への書き込みは従来どおり聞く。

### 1.2 台帳と土台の裁定で決まったこと（この版の前提）

- **周の輪は別の入口 `darkfactory-rounds/`**（〔台帳〕R25、〔土〕BL12）。既定の `darkfactory` は線 A の 1 周の run のまま。
- **盤面は土台の `DiskBoard`**（〔土〕BL3）。写しは 1 バイトも変えない（BL2）。線 B の足し算は写しの外（`overrides`・`validator_runner`・線 B のモジュール）に置く（BL5）。
- **機械の節は土台の `settle` が engine と同じ順で回す**（BL6）。周の頭の版固め・`on_new_round`・周の記録・`converge` は線 B が自前で持たない。周の番号も engine が上げる。
- **節の表 1 つが「宣言」を兼ねる**（BL4）。3 版の `declarations.json` の `nodes` は、節の表の absent の行そのもの。
- **止め札・Claude の包み・読んだ証拠・修正の後の数え直しは線 A が作る**（BL13）。線 B は使う側。
- **止める意味は土台の `stop()`、人の答えは土台の `answer()`**（BL10・BL11）。`rejudge` は engine に無い語なので線 B が持つ。
- **最後の関門は mutgate の記録を読む**（〔台帳〕R30: 変異は版を出す時にまとめて撃つ持ち主の決定に沿い、収束との連動は線 B が mutgate の記録を読むときに戻る）。
- **下請けは全部 opus**（〔台帳〕R22・R28）。YAML には `model:` を書かない（利用者の選択を残す。開発の殻の既定が opus）。
- **包みの無い環境**: 既定は run を止め、入力 `adapter: optional` のときだけ包み無しで回して報告の冒頭に出す（〔台帳〕2026-09-26 の決定。作るのは線 A）。
- **線 A は 1 本目の中間の関所を入力で残す**（〔台帳〕R26。`always`・`when_needed`、既定 `always`）。線 B は持ち主の決定 1.1 の 3 のとおり置かない（周の輪は別の入口なので両立する）。

### 1.3 持ち主の答え（2026-09-27。〔答〕）

- **軽量**（〔土〕13 節の 1）: 案 1（下げない）。線 B は手厚さの入力を持たず、線 A のブロックを標準で回す。省く配管は作らない。
- **目的と前提**: 前提 `p0.premises` は線 A のブロック `blk-premises` を周の頭で使う（1 周目だけ。graph の `once`）。目的 `p0.purpose` は線 B が新しいブロック `blk-purpose` で足す（4.10）。入るまでは節の表の absent（理由と入る Task つき）で、毎周の添え書きと報告の冒頭に出る。`p0.purpose_review`・`p0.prior_decisions` は absent のまま（11.2）。
- **並行 PR の検査 `p0.parallel_pr`**（〔土〕13 節の 2）: 案 (a)。線 A と同じ行（`engine_run`・`fallback: role`）にし、任せ先の役は線 A の `blk-pr`（読むだけの opus・申し送りは下書き・`handed_over: false`）を周の頭で include する（4.12）。投稿しないことは、ラインの置き場の `darkfactory-rounds/downgrades.json` と報告の冒頭 ② に出す。4 版の「並行 PR の語を表の 1 行の外に置かない」縛りは外した。
- **同じ周の再審 `p2.rejudge`・`p2.rejudge_third`**（4 版の 12 節の 1）: review-graph の上位互換にする。線 A の包みが判定役の会話を継ぎ（〔継試〕。輪の中でも動いた）、線 A のブロック `blk-rejudge` を周の輪の修正の後に置く（4.11）。会話の id が無い時は一時停止で人に聞く。形は回す側の指示（2026-09-27）で本線の 3-6（再審 3 回・修正役の再異議 2 回・第三の目）にし、写し直しの後に入れる（1.5）。それまでは absent（宣言）。

### 1.4 もう在る物（事実）

- 役の節は CLAUDE.md を読まない（`settingSources: []`）〔台帳: f74ddfa〕。テストのコマンドは木ごと止まる `tree_run`〔b555955・64922ec〕。`tree_run` の猶予は 2 秒で、Archon の取り消しの猶予 5 秒より短い〔1ec7894・011567b〕。節のスクリプトの頭に PEP 723〔9db67b1〕。直す物が無い判定は成功〔66b1543、R21〕。
- 土台（枝 `wip/works-board`）: 節の表 `NodeTable`・`DiskBoard` の開く・作る・保存・`accept`・`settle`・`run_engine` まで commit 済み（`2c9350e`〜`5ab66fd`）。`answer`・`skip`・`stop`・`finalize`・周の添え書き・通しの再生・`begin` は進行中（〔土計〕T6〜T8）。
- 線 C（枝 `wip/works-mutgate`、先頭 421ef1e）は仕上がった。記録 `board/mutation/record.json` の形は〔C〕7 節。
- 試し: 〔試〕P1〜P5・〔試d〕・〔試P〕P7〜P13・P16 は済み（AI 費用 0 か数セント）。

### 1.5 本線を待つ物（写し直しへの依存。回す側の指示 2026-09-27）

- 写し直しは本線の 3-5（27a818a）と 3-6（d1b863f の続き）が版に入るまで見送り、入ったら 1 回で写す（作業の控え（scratchpad）の `mainline-blocks-survey.md` 5 の 1）。その時に要る物は線 B の計画の「写し直しへの依存」に控えた（節の表と手本の graph_sha・`p2.fix_units` と再審の 4 節・盤面の層の受け付けを engine の `commands.post_check` に・`accept.py` の `DeltaPass.state_key` が消える・線 C の `mutcore` が `p3.gates_cut` の出力を読む・写す物が増える）。線 B の作業ではない。線 B の再審（4.11）はこの後に入る。
- 受け付けの口は本線の 3-8 まで `accept.py` のまま。線 B も `accept.py` に検査を足さない。線 B の判定 v2 の受け付け（`judge2.check`）・最後の関門（`close.final_gate_reply`）・検証器の包みは線 B のモジュールとブロックのスクリプトに置き、線 A の `accept.py` → `gl.py` の対応表（〔A計〕Task 24）に線 B の行を足す。
- ブロックの置き場と名前は本線の 3-7 の後に決まる。今は works の仮の名（`blk-close`・`blk-purpose`）で作り、3-7 の後に名前と `where` を揃える小さな作業をする（線 A の Task 25 と同じ時に）。
- 止める猶予は works の 2 秒のまま（本線は呼ぶ側が選べる形・既定 5 秒にする）。

## 2. ラインの形

### 2.1 並び

```yaml
# works/darkfactory-rounds/darkfactory-rounds.yaml（線 B の持ち物）
nodes:
  - id: launch        # approval（輪の外）。`archon workflow approve <id> --detach` で越えると取り消しが木ごと効く〔試P: P11〕
  - id: start         # script（輪の外。1 回だけ）: 盤面を DiskBoard.begin で作り、修正前の CI を渡す（4.1）
  - id: rounds
    loop_group:
      max_iterations: 20          # 暴走の柵。本当の上限は盤面の max_rounds（engine の converge が見る）
      fresh_context: true
      until_bash: test -f "$ARTIFACTS_DIR/board/finished"
      nodes:
        - id: open        # script。いつも走る。止め札・前の回の関所の答え・切符・並行 PR の engine の走り（4.2・4.12）
        - id: pr-checking # include: blk-pr（線 A。任せ先に落ちた周だけ）   when: $open.output.run == true
        - id: h-pre       # 境の節
        - id: premising   # include: blk-premises（線 A。1 周目だけ）
        - id: h-purpose
        - id: purposing   # include: blk-purpose（線 B。1 周目だけ。4.10）
        - id: h-judge     # 境の節。包みの確かめ（前提の役の後・判定の前）と、判定役に渡す前提と目的のファイル
        - id: judging     # include: blk-judge（線 B）   when: $h-judge.output.run == true
        - id: h-plan      # 境の節（いつも走る）。判定の直後の一時停止もここで決める（4.4）
        - id: planning    # include: blk-plan（線 A）    when: $h-plan.output.run == true
        - id: h-fix
        - id: fixing      # include: blk-fix（線 A）
        - id: h-rejudge   # 境の節。判定役の会話の id を先に確かめる（4.11）
        - id: rejudging   # include: blk-rejudge（線 A。異議が出た周だけ。本線 3-6 の写し直しの後に入る）
        - id: h-review
        - id: reviewing   # include: blk-delta（線 A）
        - id: h-refix
        - id: refixing    # include: blk-refix（線 A）
        - id: h-tests
        - id: testing     # include: blk-tests（線 A。p4.ci は run_engine）
        - id: h-close
        - id: closing     # include: blk-close（線 B）
        - id: ask         # script。関所を開くか・文を組む（4.8）
        - id: gate        # approval。唯一の末端。when: $ask.output.open == true
                          #   decisions: approve・continue・rejudge・stop・reject
  - id: report            # script（輪の外）。returns（4.9）
```

- 合流する節（境の節・ブロック・`ask`）は `depends_on: [open, <直前の境の節>, <直前のブロック>]` と `trigger_rule: none_failed_min_one_success` を持つ。前のブロックが飛ばされても合流点は走る〔試: P1〕〔試P: P10〕。
- ブロックの `when:` は、直前の境の節の `run` だけを比べる。どのブロックを走らせるかの計算は境の節（盤面の ready）がし、YAML は比べるだけにする（1 本目の仕様 3 節の層）。
- 飛ばされうる節の欄を関所の文面・bash の本文で読まない。script の節の `with:` は `if_skipped` つき〔試P: P7〕。境の節と `open` は `when:` を持たないので、その欄はいつ読んでもよい。
- **ブロックの入口は、いつも走る節の欄か盤面からだけ渡す**（審査 C1）。飛ばされうる節（`judging` など）の欄を `with:` で読むと、関所の `continue` の後や resume の後の回（判定のブロックが飛ぶ回）で、読む側が実行前に落ち、輪ごと落ちる〔試P: P7〕。渡し方:
  - 輪の外の `start`（1 回だけ走り、いつ読んでもよい）の出口: `base_rev`・`test_cmd`・`policy_paste`・`policy_path`（4.1）。
  - 境の節（いつも走る）の出口: 次のブロックが要る物を盤面から組む。周の番号を決め打ちにせず、役の出力は `state.outputs[節]["file"]`、作業ファイルは `b.work(名)` から引く（〔A計〕TA17 と同じ）。`judgment_file`（今の周の `p2.diagnose` の出力。2 回目が在る周は `p2.history` の方）・`open_units`（今の周の記録の開いた単位の数）・`plan_file`（今の周の `p2.fix_plan` の出力。無ければ `""`）・`human_notes`（今の周の `human_items` の一言を並べた文）・`premises_file`（`p0.premises` の出力。`once` なので 1 周目の物）・`purpose_file`（`p0.purpose` の出力。同じ）。
  - 各ブロックの入口と出どころ:
    - `pr-checking`（blk-pr）: `base_rev` ← `$start.output`
    - `premising`（blk-premises）: `request_file`・`base_rev` ← `$start.output`
    - `purposing`（blk-purpose）: `request_file`・`base_rev` ← `$start.output`、`premises_file` ← `$h-purpose.output`
    - `judging`（blk-judge）: `request`・`base_rev`・`policy_paste` ← `$start.output`、`premises_file`・`purpose_file` ← `$h-judge.output`
    - `planning`（blk-plan）: `judgment_file` ← `$h-plan.output`、`base_rev`・`policy_paste`・`policy_path` ← `$start.output`
    - `fixing`（blk-fix）: `judgment_file`・`open_units`・`plan_file`・`human_notes` ← `$h-fix.output`、`base_rev`・`policy_path` ← `$start.output`
    - `rejudging`（blk-rejudge。写し直しの後）: `base_rev`・`policy_paste`・`policy_path` ← `$start.output`
    - `reviewing`（blk-delta）: `policy_paste` ← `$start.output`、ほかは 1 本目の入口に同じ
    - `refixing`（blk-refix）: `base_rev`・`policy_path` ← `$start.output`
    - `testing`（blk-tests）: `mode: final`（明示で渡す定数。blk-tests の既定 `mode: plain` は 1 本目と線 C の mutgate の約束のままで、線 B は使わない〔A計〕TA4・TA5）・`cmd` ← `$start.output.test_cmd`
  - 方針の文書は `start` が線 A と同じ作り方（〔A計〕TA10 の `policy.brief`）で組み、読む役（判定・事前審査・審査）には貼る文、書く役（修正案・修正・手直し）にはパスで届く。review-graph が graph の `prompt_append`（`policy-paste.md`・`policy.md`）で全部の役に届けるのと同じ（土台の手本 `test_policy_reaches_roles` が撮った物）。
- 線 A のブロックの中の節の id は、輪の本体の全部の include をまたいで、筋書きが stub する物だけ一意であればよい（〔台帳〕R19。`collect` のように stub しない script の節は重なってよい）。線 B の筋書きは `collect` を stub しない（10.3）。

### 2.2 どのブロックを走らせるかは盤面が決める

- 境の節 `h-<段>` と `open` は、同じ関数 `rounds.boundary(board_dir, at)` を別の id で呼ぶ。線 A の境の節 `halt.edge`（〔A計〕T10）は線 A のラインの段の名前と中の関所を持つので使わず、同じ部品（`halt.seen`・`reads.adapter_seen`・`entry.take`・`entry.empty_fix_reply`）を線 B の `boundary` から呼ぶ。
- 返り `{ok, stop, run, ask, round, why, judgment_file, open_units, plan_file, human_notes, premises_file, purpose_file}` の決め方（後ろの 6 つは C1 の入口。盤面から組む）:
  1. 盤面が止まった・終わった（`halted` か `status` が `converged`・`stopped`）なら `finished` を書いて `stop: true`。
  2. 線 A の止め札 `halt.seen(board_dir)` が在れば、土台の `b.stop(理由, by)` で止め（最初の理由が正〔A計〕T8・T10）、`finished` を書いて `stop: true`。
  3. `h-judge` だけ: 包みの確かめ（線 A の `reads.adapter_seen`。この run の役の起動が包みを通っていなければ、入力 `adapter` が `optional` でない限り `b.stop("包みが通っていない: …", by="works:adapter")`。〔A計〕TA9 と同じく、前提の役の後・判定と書く役の前で止める。2 周目からは確かめ済みなので見ない）。`h-plan` だけ: 判定の直後の一時停止 `judge_asks`（4.4）。`h-rejudge` だけ: `p2.rejudge` が ready で、線 A の `rejudge.session_ready(repo)` が偽なら一時停止 `rejudge_no_session`（4.11）。`open` だけ: ready の `p0.parallel_pr` を線 A の `prcheck.run_helper(b)` で走らせ、任せ先に落ちた時だけ `run: true`（4.12）。
  4. 直す単位が 0 の周（`p2.fix_plan` が条件で `na`、`p3.fix` が ready）: 線 A と同じく、`p3.fix` に「直す義務 0 件」の空の返答を機械で渡す（`entry.take(board_dir, "p3.fix", entry.empty_fix_reply(), repo)`。〔A計〕TA6・T9）。修正の役は起こさない。
  5. `asking` が在るか、線 B の一時停止が在れば、`run: false, ask: true`。
  6. そうでなければ、ready のうちこの段のブロックが持つ節（節の表の `where`）が 1 つ以上在れば `run: true`。
- どの段のブロックが次に要るかは engine の順（graph の順と依存）で決まる。周の中の順は graph と同じで、周の頭（1 周目: `p0.parallel_pr` の任せ先・`p0.premises`・`p0.purpose`。並行 PR は持ち越しの規則で後の周にも立ちうる）→ 判定（`p2.diagnose`・`p2.history`）→ 修正案と事前審査（`p2.fix_plan`・`p2.plan_review`、修正前の問い `p2.human_gate`）→ 修正（`p3.fix`）→ 同じ周の再審（`p2.rejudge`・`p2.rejudge_third`。異議が出た周だけ）→ 差分の審査（`p3.delta_review`）→ 手直しの 2 往復（`p3.delta_fix`・`p3.delta_review2`・`p3.delta_fix2`）→ テスト（`p4.ci`）→ 周の記録（`p4.record`）→ 最後の関門（`p4.final_gates`）→ `converge`。
- 1 回（iteration）の中で前の段へ戻ることは無い。`converge` が次の周を開いた回は、`closing` の後で回が終わり、次の回の `open` から判定に入る。
- 3 版の「段（stage）」の表と `decide_stage` は要らなくなった。段は ready から出る。これで 3 版の「周の番号が余分に進む」〔試: P1〕の心配も消える（線 B は周の番号を書かない）。

### 2.3 関所を開く時と答え

関所を開くのは次の 2 種類のときだけ。どれでもない回は `gate` が飛ばされ、そのまま次の回へ進む。

- **engine の問い（asking）**: `p2.human_gate`（修正案が能力を狭める・事前審査の穴が regression か policy・方針の文書の変化）、`converge` の `max_rounds`・`work_exhausted`・`premise_escalate`・`ci_unverified`・`final_gate_empty`。
- **線 B の一時停止**:
  - `judge_asks`: 判定の直後、この周の台帳に、人に聞く状態（RR の `ASKING`＝`held`・`escalate`）で、かつ `status` が `escalate` か `kind` が `fork` の問いのうち、まだ答えていない物が在る（1.1 の 2）。決着した（`decided`）`fork` は台帳に書き写され続ける（RR の `TRACKED`）が、開かない（審査 I2）。
  - `tests_red`: 周の終わりに、この周の `local_checks` が `found`（テストが赤）。
  - `stuck`: 周の終わりに、この周で種類 `stuck` の問いが新しく立った（同じ block が 3 周続いた。a1202d0 では判定の受け付けが台帳への記載を要求する〔写: RL `_stuck_unrouted`〕ので、記載された問いで見る）。
  - `questions_open`: 周の終わりに、人に聞く状態（`held`・`escalate`）の問いのうち、まだ答えていない物が在る（持ち主の決定 1.1 の 3「人への問いが残る」をそのまま。`judge_asks` で既に答えた物は除く）。review-graph は `held` を `converge` の `work_exhausted`（他に仕事が無い時）まで聞かないので、線 B は多く・早く聞く側（審査 I3。持ち主の決定どおりなので台帳に残すだけ）。
  - `final_gate`: 最後の関門の節 `p4.final_gates` が ready で、mutgate の記録をまだ受けていない（4.7。`gates` が `in_run` の run だけ）。
  - `rejudge_no_session`: 修正の後に `p2.rejudge` が ready なのに、判定役の会話の id が無い（包み無しの run・包みの置き場が消えた、など。4.11）。再審の役を起こす前に開く。
- 「まだ答えていない」は `works-rounds.json` の `answered`（問いの `key` と `status` の組 → 答えた周）で見る。同じ問いは状態が変わるまで（`held` → `escalate` など）聞き直さない。

答えの意味（`approve` は `continue`、`reject` は `stop` と同じに扱う〔試P: P8〕）:

| 開いた所 | continue | rejudge | stop・reject |
|---|---|---|---|
| judge_asks | 同じ周の続き | 周を締めて次の周 | 報告へ |
| p2.human_gate | 同じ周の続き | 周を締めて次の周 | 報告へ |
| converge の問い（下の 2 つ以外） | 次の周 | 次の周（印つき） | 報告へ |
| max_rounds・final_gate_empty | 次の周（上限＋1 か腕 0 本の同意） | 聞き直す | 報告へ |
| tests_red・stuck・questions_open | 次の周 | 次の周（印つき） | 報告へ |
| final_gate | 記録を受ける | 聞き直す | 報告へ |
| rejudge_no_session | 再審を飛ばして同じ周の続き | 周を締めて次の周 | 報告へ |

- 「周を締めて次の周」は 4.4 の `close_early`。「次の周（印つき）」は、engine の答え `continue` に「判定のやり直しを求める」の一言を足して渡す（次の周の判定役は `process.human_answers` で読む）。
- `rejudge` は `continue` の副作用を持たない（審査 I4）。RL の `on_answer` は `continue` で、`max_rounds` なら上限を 1 周上げ、`final_gate_empty` なら今の木に「腕 0 本で通す」同意を置く〔写: RL:3718-3730〕。「判定からやり直せ」はこのどちらの同意でもないので、この 2 つの問いへの `rejudge` は使えない答えとして聞き直す（文に「上限を延ばすなら continue、やめるなら stop」「腕 0 本を通すなら continue」を出す）。
- engine の問いと線 B の一時停止が同じ回に重なったら（例: 上限の周でテストが赤）、関所は 1 つで、文に両方の項目を並べる。答えは engine の問いに先に `answer` で当て、線 B の一時停止は同じ答えで閉じる（`stop` なら両方止まる）（審査 m9）。
- `tests_red`・`stuck`・`questions_open` は、`converge` が既に次の周を開いた後で開く（周の終わりの関所を、次の周の判定の前に置く形）。`continue` の一言は新しい周の `process.human_answers` に積む。
- `final_gate` の `continue` は一言に `mutgate=<記録の絶対パス>` を要る。無ければ同じ関所を聞き直す。`rejudge` もこの関所では使えないので聞き直す（最後の関門は周の他が全部揃った時だけ開くので、やり直す判定が無い）。
- `rejudge_no_session` の `continue` は、土台の `b.skip("p2.rejudge", 理由)`（graph で optional の節なので engine の `skip` が許す）で再審を飛ばし、同じ周の続き（差分の審査）へ進む。異議は写しの `on_new_round` が `prev_rejudge` に写し、次の周の `p2.history` が再審する（0.21.0 より前の graphloops の形）。飛ばしたことは `process.skipped` と報告の周ごとの行に出る。
- 人は `archon workflow respond <run> <選択肢> "<一言>"` で答える。`reject` は `decisions` に書いてあるので、`archon workflow reject <run> --reason "…"` でも報告が必ず出る〔試P: P8〕。
- 人の一言の行き先: engine の問いへの答えは土台の `answer()` がそのまま記録する（RL の `on_answer`・`on_answer_in_round`）。線 B の一時停止への答えは、RL の `human_gate_answered` と同じ形 `{round, kinds, asked, answer, note, node}` で `record.process.human_items` に積み、`continue` と `rejudge` の一言は `process.human_answers` にも積む（次の判定役が読む。graph の `p2.history` の reads に在る）。

### 2.4 until_bash と上限

- until_bash は `test -f "$ARTIFACTS_DIR/board/finished"` だけ。飛ばされた節の出力を読むと輪ごと落ちる〔試: P1〕。読み込みの検査の警告（「`$gate.output.decision` を見よ」）は受け入れて無視する。
- `finished` を書くのは、盤面が終わった・止まったと見た線 B の節（`open`・境の節・`closing`・`ask`・`report`）だけ。中身は理由の 1 行。
- 周の上限は盤面の `max_rounds`（入力。既定 5＝graph の既定）で、engine の `converge` が `ask max_rounds` を立てる。`continue` は上限を 1 周だけ上げる（RL `on_answer`）。
- `max_iterations: 20` は 1 回の起動の中の暴走の柵。関所の答え 1 つごとに 1 回消える。超えれば run は失敗で止まり、`resume` で続く（盤面は残る）。

### 2.5 止める（線 A の物を使う）

- 止め札（`works/dev/stop.sh <run-id> <理由>`）・境の節での止まり方・取り消し（`launch` を `--detach` で越えた run の `cancel`）・Ctrl-C と `resume` は、線 A が作る物をそのまま使う（〔A〕5.3）。線 B は境の節から `halt.seen` を読み、在れば土台の `stop()` を呼ぶだけ（2.2 の 2）。
- 止めた周の記録は土台の `stop()` が RL の `on_stop` で組む（止めた周の素材は `not_run`。止めた周は収束に数えない）。
- 走っている AI の節は止め札では止まらず、次の境の節で止まる〔試P: P12〕。関所で待っている run には `cancel` が効かないので `respond … stop` で止める〔試P: P11〕。

## 3. 盤面の使い方（土台の上に線 B が足す物）

### 3.1 節の表 `works/darkfactory-rounds/nodes.json`（線 B の持ち物）

- 土台の縛り（〔土〕4.2 の 1〜5）を満たす。graph の 60 節をちょうど 1 度ずつ。
- 持ち方の要点:
  - `machine`: `p0.base`（`begin` が組む）・`p4.final_gates`（mutgate の記録から組む。4.7）
  - `engine_run`: `p0.local_checks`（`start`）・`p4.ci`（blk-tests）。どちらも `fallback: machine`（宣言の無い対象では `test_cmd` を走らせた結果を渡す）。`p0.parallel_pr`（`open` が engine で走らせ、任せ先は blk-pr）は `fallback: role`（〔答〕2。線 A と同じ行）
  - `role`: `p0.premises`（blk-premises。線 A）・`p0.purpose`（blk-purpose。線 B）・`p2.diagnose`・`p2.history`（blk-judge）、`p2.fix_plan`・`p2.plan_review`（blk-plan）、`p3.fix`（blk-fix）、再審の 6 節（blk-rejudge。線 A。写し直しの後）、`p3.delta_review`（blk-delta）、`p3.delta_fix`・`p3.delta_review2`・`p3.delta_fix2`（blk-refix）
  - `builtin`（graph の driver の節全部）: 既定は `auto`。`p4.record` だけ `explicit`（壁。4.5 で宣言を書いてから回すため）
  - `absent`（理由と `comes_with` を必ず書く）: `p0.purpose_review`・`p0.prior_decisions`・P1 の目の全部・`p3.delta_gates`（周の中の変異の線）・R1〜R4 の節・`stop.premise_check`・`report.*`・`spec.*`。〔答〕で入る節（`p0.parallel_pr`・`p0.premises`・`p0.purpose` と再審の節）は、入る Task（計画の T15〜T17。再審の T17 は写し直しの後）までは absent（理由に入る Task）で、その Task が行を替える
- 各行の `where` はブロックの名前（`blk-judge`・`blk-plan`・…・`start`・`blk-close`）。境の節は `where` でブロックの持つ節を引く（2.2 の 4）。
- 線 A の表（`darkfactory/nodes.json`）とは別の持ち物。役の行は線 A と同じにするのを単体テストで見る（線 A の表が在るときだけ。違いは `p2.history`・`p4.record` の `explicit`・`p4.final_gates`・`p0.purpose`（線 A は absent）の 4 つだけのはず）。

### 3.2 線 B が盤面に置くファイル

土台の予約（〔土〕3 節）の中の、線 B の分だけ:

```
$ARTIFACTS_DIR/board/
  finished                  輪を終える印（2.4）
  works-rounds.json         線 B の状態 {version, test_cmd, gate: {seq, kind, source, round, items, applied},
                            answered: {"<key>|<status>": <周>}, rejudge: [<周>], final_gate: {record, tree, checked_at}?}
  r<N>/history.json         判定 2 回目に貼る履歴の束（4.3）
  r<N>/reads-judge.json     読んだ証拠（線 A の reads.py が書く。判定の分は線 B が節を置く）
  final-gate-<tree12>.json  mutgate の記録の突き合わせの結果（4.7）
  r<N>/purpose-snapshot.json 目的の役の前の作業ツリーの写し（4.10）
```

- 盤面の外（ラインの置き場）: `works/darkfactory-rounds/downgrades.json`（下げた物の一覧。今は並行 PR の申し送りの 1 行。線 A の `darkfactory/downgrades.json` と同じ形。報告の部品 `declared_downgrades(line)` が読む）。
- 盤面の外（包みの家）: 線 A の包みが判定役ほかの会話 id を `sessions/<cwd の hash>/<節の名>.id` に書く（〔A計〕T5）。周ごとに判定役が書き直すので、再審はいつも今の周の判定役を継ぐ。

- 盤面の外に、ラインの置き場の `works/darkfactory-rounds/board_hook.py`（`board_kwargs(table) -> dict`。線 B の `overrides` と `validator_runner` を返す）を置く。ブロックが盤面を開くとき、ラインを知らずに線 B の差し替えを付けるための口（5 節の約束 1）。

- `rounds/` の下には置かない（RR は `rounds/` の直下の `round-<N>.json` 以外のファイルで落ちる〔研 §3〕）。
- `works-rounds.json` は一時ファイルから `os.replace`。盤面の `state.json` の後に書く（順は 3.3 の 2 で冪等にする）。

### 3.3 冪等（同じ所を 2 度走っても壊れない）

- 失敗からの resume は輪を 1 回目から、run を始めた時の工程のまま回す〔試〕。
- 決まり:
  1. 周の番号は engine が上げる（`converge` の `next_round`・答えの `continue`・4.4 の `close_early`）。線 B の `open` と境の節は周の番号を書かない。〔3版〕の決まり 1 は不要になった。
  2. 関所の答えは `works-rounds.json` の `gate.seq` と `applied` で 1 度だけ当てる。`applied` が真の答えは当て直さない。答えを当てた後は、盤面の保存 → `applied` を真、の順に書く。間で落ちても、盤面の側に answer の痕（engine の問いなら `pending_human` が消えている・線 B の一時停止なら `human_items` の行）が在れば当てたと見なす。
  3. `open` が、開いた関所（`applied` が偽）なのに前の回の答え（`with: {prev: "$LOOP_PREV.gate.output"}` の文字列）が空（resume で答えを失った）を見たら、ブロックを全部飛ばして同じ関所をもう一度聞く。空の文字列は「前の回に関所が開かなかった」と「答えを失った」の両方で届くので、見分けは `works-rounds.json` の `applied` だけで行う。
  4. 盤面が止まっている・終わっている（`halted`・`converged`・`stopped`）なら、`open` は `finished` を書き直して `stop: true` を返すだけ。
  5. `works-rounds.json` の `version` を知らなければ `open` は終了コード 2（古い run を新しい形で続けて混ぜない）。盤面の形の違いは土台の `open` が `BoardMismatch` で止める（〔土〕4.4）。
- 段の粒はブロック 1 つ。ブロックの途中で落ちたら、その節の instance が待ちのまま残るので、次の回の境の節がそのブロックを頭から回す。
- 判定の 1 回目の後・2 回目の前で落ちた場合だけは、2 回目を新しい会話で起こす（4.3 の「resume の時」）。

## 4. 線 B が作る物

### 4.1 `start`（輪の外。1 回だけ）

- `rounds.start(...)` は次の順（`begin` に渡す差し替えは線 A の `entry.hook_kwargs("darkfactory-rounds")` と同じ物）:
  1. 依頼のファイルを 1 本目と同じ型で確かめる（`accept.check_request`。拒めば `{ok: false, reason}`、run は `start` で落ちる）。
  2. `DiskBoard.begin(board, repo, table, items, origin, base_rev, request_text, max_rounds, inputs, overrides, validator_runner)`（〔土〕5 節）。`stop_after_round` は渡さない。`inputs.gates` は入力 `gates` が `merge` のときだけ `"merge"`、`in_run` なら渡さない（RL の `check_inputs` が知る値は `merge` だけ〔写: RL:67-81〕）。`overrides` と `validator_runner` は 4.6。
  3. ready の engine_run の節（`p0.local_checks`）を全部、線 A の `entry.run_ci(b, nid, test_cmd=…)` で走らせる（`run_engine` の返りを全部扱う: `relaunch` は 1 度だけ呼び直し、任せ先に落ちたら `entry.local_checks_material` の素材を `done`、`why` だけの返りは止める。〔A計〕TA18 の 2・M7）。
  4. 切符を書く（線 A の `ticket.write`）。`works-rounds.json` を初期化し、`test_cmd` を控える（`close` が mutgate の 1 行を組むため。審査 m10）。
  5. 方針の文書を線 A の `policy.brief(board)` で組む（C1）。
- 出口: `{ok, round, base_rev, test_cmd, policy_paste, policy_path, reason?}`。ブロックの入口の出どころ（2.1）。
- `begin` が冪等（同じ依頼なら開いて返す〔土〕5 節）なので、`start` の 2 度目は何もしない。
- 3 版の「3 つのずれ」（依頼が周ごとに重なる・審査の差分が累積・count-cache が 1 周目の版）は、依頼が `begin` の 1 度だけで、周の頭の版を engine の `p1.worktree_before` が周ごとに固めるので、どれも起きない。

### 4.2 `open` と境の節

- `open`: 止め札 → 盤面の終わり → 前の回の関所の答えを当てる（`with: {prev: "$LOOP_PREV.gate.output"}` の文字列の束ねで受ける。`$LOOP_PREV` は節の参照でないので `from:` では読めず、Archon が読み込みで拒む〔A/: loop-nodes.md:757-761〕〔研 §4〕。1 回目と関所が開かなかった回は空。3.3 の 2・3。審査 I1）→ 切符が今の run の物か確かめ、違えば書き直す → ready の `p0.parallel_pr` を `prcheck.run_helper` で走らせる（4.12）→ `rounds.boundary(board, "pr-checking")` と同じ返り。
- 境の節: `rounds.boundary(board, "<段>")`。`h-judge` は包みの確かめ、`h-plan` は判定のブロックが走った直後に `judge_asks` を決め（4.4）、`h-rejudge` は判定役の会話の id を先に確かめる（4.11）。`h-close` の後の `ask` が関所の文を組む。
- 境の節は 10（`h-pre`・`h-purpose`・`h-judge`・`h-plan`・`h-fix`・`h-rejudge`・`h-review`・`h-refix`・`h-tests`・`h-close`。`h-rejudge` は写し直しの後に入るので、それまでは 9）と `open`。同じスクリプトを別の id で呼ぶ（id は裸の名前で筋書きに当たるので重ねない〔台帳 R19〕）。

### 4.3 blk-judge v2（判定の 1 回目と 2 回目。案 d）

- 1 本目の `intake` を外す（依頼は `start` の `begin`）。入口は盤面の場所（`$ARTIFACTS_DIR`）と、線 A が波 2 で足す `policy_paste`・`premises_file`（〔A計〕T2・TA10。〔土〕6 節の「`policy_file` と `brief`」を線 A が改めた）と、線 B が 4.10 で足す `purpose_file`（目的の文。graph の `p2.diagnose` が `out.p0.purpose.purpose_text` を読むのと同じ）。
- 判定役 `judge` の `output_format` は印つき（`node_marker.mark(union_schema, "judge")`。線 A が T2 で 1 本目の型に付けた印を v2 でも残す）。線 A の包みは、内の輪の 1 回目（新しい会話）では自分で作った `--session-id` を、2 回目（Archon が同じ会話を `--resume` で継ぐ）では SDK の id をそのまま、判定役の会話 id として記録する（〔A計〕T5）。どちらも同じ会話なので、再審（4.11）は 1 回目と 2 回目を合わせた判定役の続きになる（graph の `same_context_as: p2.diagnose` と同じ）。resume の時の「新しい会話の 2 回目」では新しい id が記録され、再審はその会話を継ぐ（直近の判定役）。線 A の 1 周のラインが渡す `request`・`base_rev` も入口に残す（受けて使わない。線 A のラインの `with:` を壊さないため）。
- 節の id は 1 本目の物（`judge-loop`・`judge`・`judge-accept`・`collect`）を残し、`judge-stage`・`judge-reads` を足し、`intake` だけを消す（線 A の筋書きと境の節が 1 本目の名前で当たるため）。
- 形（〔試d〕で確かめた形のまま）:

```yaml
- id: judge-loop
  loop_group:
    max_iterations: 6            # 1 回目の出し直し 3 ＋ 2 回目の出し直し 3
    fresh_context: false
    until_bash: test "$judge-accept.output.done" = true
    nodes:
      - id: judge-stage          # script。盤面から今が 1 回目か 2 回目か（AI でない）
      - id: judge                # この輪の中の AI の節はこれ 1 つだけ
      - id: judge-accept         # {ok, done, pass, reason, next}
- id: judge-reads                # script。線 A の reads.py（読んだ証拠）
- id: collect
```

- **盤面の開き方**（審査 I6）: v2 は線 A の 1 周のラインでも走るので、線 B の表を決め打ちにしない。`state.works.line` からラインの表（`works/<line>/nodes.json`）を引き、表の sha が `state.works.table_sha` と違えば `BoardMismatch`、ラインの置き場に `board_hook.py` が在ればその差し替えを渡して開く（線 A の `entry.open_board` と同じ決まり。線 A の合流の後は `entry.open_board` をそのまま使う）。線 A の盤面では `p2.history` が absent なので 2 回目は立たず、線 B の差し替えも付かない。
- どちらの回かは盤面が決める: `p2.diagnose` の instance が待っていれば 1 回目、`p2.diagnose` が済んで `p2.history` の instance が待っていれば 2 回目。`p2.history` は graph の条件 `after_first_round`（周が 2 以上）で立つので、1 周目は 2 回目が無い（engine と同じ）。
- `judge-accept`:
  - 1 回目: `b.done("p2.diagnose", 返答)`。拒否（`Reject`）は `{ok: false, reason}` で盤面を書かない（土台の約束）。通って ready に `p2.history` が在れば `{done: false, pass: "history", next: <履歴の束>}`、無ければ `{done: true}`。
  - 2 回目: `b.done("p2.history", 返答)`。拒否は同じ会話で出し直し。通れば `{done: true}`。
  - 受け付けの規則は写しの `judge_output`（graph の `post_check`）がそのまま当たる。前の周の問いが今の周に在ること・defer の開き直しの証拠・3 周続く block の記載〔写: RL `_stuck_unrouted`〕も、ここで engine と同じ文で拒む。
- 履歴の束（`judge2.history_bundle(b)`。`r<N>/history.json` にも置く）: graph の `p2.history` の reads の全部〔写: graph〕——前の周の検証器の出力・前の周の問いと単位と block・defer 台帳・`process.human_answers`・1 回目の単位と問い・`prev_rejudge`・`prev_one_shot`・`wrote_refs_reads`・`coverage_after`・`prev_declared_faces`・方針の文書。問いの台帳・defer 台帳・人の答えは本文を貼り、検証器の出力の全文はパスで渡す。貼る上限は 40,000 バイト（graphloops の `FILE_CAP`）で、超えた分は先頭と続きのパス（〔台帳〕方針 9）。
- 1 回目に見せない物: 履歴・前の周の台帳・前の周の判定（graph の `p2.diagnose` の `forbidden_inputs`）。指示書の 1 本目の本文は 1 回目の指示で、「末尾の機械の一言が空でなければそれに従え」と書く。
- **出力の型**: Archon の `output_format` は節に 1 つ。1 回目と 2 回目で graph の型が違うので、YAML には 2 つの型の欄の和（`required` は共通の欄だけ）を書き、回ごとの正しい型は受け付け（`b.done` の型の検査）が縛る。和の型を SDK が受けるかは試し P6e で見る（9 節）。
- **resume の時**: 1 回目が済んで 2 回目の前で落ちた run を resume すると、内の輪の 1 回目は必ず新しい会話で起きる〔試d〕ので、同じ会話の続きにならない。このときは `judge-stage` が「新しい会話の 2 回目」と判じ、`next` に 1 回目の返答のファイルのパスを足し、盤面の trace に `p2.history: 新しい会話で 2 回目` を書く。graph の注記も「会話が無ければ新しい context になり記録に残る」としている〔写: graph の p2.history の note〕。同じ周の判定を回し直す（1 回目を捨てる）形は採らない（graph の `per_round_rules`「同一ラウンドで採点する側を回し直して有利な判定を採らない」）。
- 出口（`collect`）: 1 本目の欄を全部残し（`need_fix`・`judgment_file` など。`judgment_file` は盤面の `state.outputs["p2.diagnose"]["file"]`）、`asks_human`（`judge_asks` の条件に当たる問いが在る）と `reads_file` を足す。線 B のラインは道の選びに `need_fix` を使わない（ready が決める）。線 A の境の節の判定の渡し替え（〔A計〕TA3）は、盤面に `p2.diagnose` が既に在れば渡さないので、v2 のままで動く。
- 予備の案 (c)（2 回目を別の節の新しい会話にする）は、試し P6c・P6e が崩れたときだけ。持ち主が決めた予備なので、切り替えは推しで進めて台帳に残す。
- なぜ Archon の `context: {resume: <節>}` を使わないか: 輪の本体の中では読み込みで拒まれる〔試: P4b〕〔A/: loader.ts:1058〕。

### 4.4 早く聞く（`judge_asks`）と、周を締めて次の周（`close_early`）

- `h-plan` が、判定のブロックが走った回に、この周の台帳を見る。2.3 の `judge_asks` の条件（`held`・`escalate` のうち、`escalate` か `fork`）に当たり、`works-rounds.json` の `answered` に `key|status` が無い物が在れば、一時停止 `judge_asks` を立てる（`run: false, ask: true`）。後ろのブロックは全部飛び、`ask` → `gate`。
- `continue`: 問いの `key|status` を `answered` に足し、一言を 2.3 の形で記録する。次の回の境の節は ready（`p2.fix_plan` か `p3.fix`）から同じ周を続ける。`fork` の出どころの単位は修正役が `not_done` で待ってよい（`fix_covers_open_units` が許す〔研 §1〕）。
- `rejudge`（と `p2.human_gate` の問いへの `rejudge`）: `rounds.close_early(b, 理由, 一言)`。engine の `cmd_stop` の盤面の部分から「止める」だけを除いた形を、写しの関数で組む:
  1. `pending_human` が在れば外し、`human_items` に `answer: "rejudge"` の行で残す（人が答えた事実どおり。RL の `on_stop` の「答えの無い問い」の書き方は使わない。RR は `human_items` の `answer` の値を縛らず、RL は `answer == "continue"` の行だけを「通した項目」に数える〔写: RL:4046〕ので、`rejudge` の行は修正前の関所の項目を通したことにならない。審査 m4）。
  2. この周で待っている節を全部 `rd.stopped`（理由つき）にし、待っている instance を `stopped` にする（engine の `cmd_stop` と同じ印）。宣言した目を `close-declare` と同じく記録に置く（4.6）。
  3. 写しの `_stopped_round_record(b, 理由)`〔写: RL:3770〕で止めた周の記録を組む（`fill_materials` → `record_round(stopped_reason)`。検証器を通らなければ盤面を戻して理由を返す）。通らなければ、周を開かずに関所を聞き直す（理由を文に出す）。
  4. 一言を `process.human_answers` に積み（kinds `rejudge`）、`works-rounds.json` の `rejudge` に周の番号を足す。
  5. engine の `open_next_round(b, "converge")`〔写: engine/advance.py:634〕で次の周を開き（`on_new_round` が走る）、保存して `settle`。止めた周の添え書き（`rounds/works/round-<N>.json`）を書く。
- 締めた周は素材が `not_run` で書かれるので阻害に数えられ、収束の「連続 2 周」は次の周から数え直しになる（正直な値。〔3版〕4.3 と同じ意味）。締めた周も 1 周として上限（`max_rounds`）と「3 周続く block」の数に入る（審査 m7。11.3 にも書く）。
- 同じ周の判定を回し直さないので、graph の `per_round_rules` とぶつからない。

### 4.5 blk-close（周の締め）

- 入口: 盤面の場所。中の節は全部 script（AI は無い）。id は輪の本体で一意にする（`close-declare`・`close-record`・`close-collect`）。
  1. `close-declare`: 4.6 の宣言を記録に書く（R1〜R4 の欄を `not_in_line`）。`gates` が `in_run` の run では、この周に `p3.gates_cut` が台帳に載せた線を `abandoned`（理由つき）にする（4.6 の終わり）。止め札・関所の `stop` で止めた周も、境の節と `report` が `b.stop` の後に同じ `abandon_unrun_lanes` を当てる（止めた周に `running` の線を残さない。審査 m3）。
  2. `close-record`: `b.run_builtin("p4.record")`（壁の機械の節）。`settle` がその後の `p4.final_gates` の条件を見て、`converge` まで回す。`p4.final_gates` が ready で止まったら、`works-rounds.json` に受けた mutgate の記録が在れば 4.7 で返答を組んで `b.done("p4.final_gates", …)`、無ければ一時停止 `final_gate`。
  3. `close-collect`: 出口 `{ok, decision, reason, kinds, round}` を組む。`decision` は `finished`（盤面が `converged`・`stopped`。`finished` を書く）・`next_round`（engine が次の周を開いた）・`ask`（asking か線 B の一時停止）。ここで周の終わりの一時停止（`tests_red`・`stuck`）を決める。
- 検証器が exit 2（記録の形の誤り）を返したら、`settle` はそこで止まり理由を `notes` に出す（〔土〕11 節）。線 B は run を失敗で止める（終了コード 2。graphloops の「直して next」に当たり、直した後に `resume`）。役に返しても直らない誤りなので、関所では聞かない。

### 4.6 宣言した省略（収束の案 B）

- **宣言の正本は節の表の absent の行**（BL4）。`rounds.declarations(table, graph)` がそこから次の 3 つを導く（別の一覧を持たない）:
  - `nodes`: absent の節の全部。
  - `materials`: 書く節（graph の `materials` と `writes` の `materials.*`）が全部 absent の素材。今の表では 15 のうち 12（`local_checks`・`base_determination`・`fix_closure` を除く）。
  - `reviews`: 書く節（graph の `writes` の `reviews.*`）が absent の目。今は R1〜R4 の全部（`r1.minimality`・`r2.compare`・`r3.coherence`・`r4.hidden_scope`）。
- 新しい状態 `not_in_line`（`reason` 必須・阻害に数えない・持ち越せない・機械が書く）を、写しの外で持つ:
  - **検証器の包み** `works/.shared/core/rounds_validator.py`: RR を新しい module として読み込み、記憶の中の表（`STATUS`・`REVIEW_STATUS`）に `not_in_line` を足してから RR の `main` を呼ぶ（ファイルは 1 バイトも変えない）。足す縛り（どれも exit 2）: ① `not_in_line` は宣言に名の在る物にだけ書ける ② 宣言に名の在る物に、観測した値（素材は RR の `OBSERVED_STATUS` の値、目は機械が書かない本物の判定）を書かない（ブロックを足した日に表の行を直し忘れると落ちる。`not_run`・`not_applicable`・`not_in_line` は書ける）③ 同じ run の周どうしで宣言が同じ。宣言は引数で受ける。
  - **盤面への差し込み**（土台の口だけで。〔土〕BL5）: `validator_runner` に包みを走らせる関数を渡し、`overrides` で RL の大域の名前 2 つを差し替える。`validator_module` → 包みの module（RL が `V.REVIEW_STATUS["not_in_line"]` を引けるように）。`fill_materials` → 「宣言した素材のうち、まだ記録に無く、書く節がこの周に条件外（`na`）でない物を先に `not_in_line` で置き、それから写しの `fill_materials` を呼ぶ」関数。どちらも `BUILTINS` などの dict の値ではないので差し替えが効く（〔土〕4.4）。`state.works.overrides` に理由つきで残る。写しの `_stopped_round_record`（止めた周の記録）も大域の `fill_materials` を呼ぶので、止めた周・締めた周にも同じ宣言が載る。
  - **目（R1〜R4）**: `record_round` は記録に在る目の値を上書きしない〔写: RL:1914-1918〕ので、`close-declare` が `p4.record` の前に、宣言した目を `{status: "not_in_line", reason: <表の理由>}` で記録に置く（この周に本物の値が無いときだけ）。`close_early` も締める前に同じ物を置く。止め札で止めた周（土台の `stop()`）では置かれず、目は `not_run`（止めた事実）になる。縛り ② はこれを許し、止めた周は収束に数えない（正しい向き）。
- 素材のうち、判定から入る run の 1 周目で engine が `not_applicable` にする物（P1 の素材〔写: RL の `_entry_skipped` の分岐〕）は、engine の値のまま残す（縛り ② が許す）。
- 残す芯（写しそのもの）: 連続 2 周の阻害なし・問いの台帳・defer と `reopen_evidence`・3 周続く block（判定の受け付けで縛る）・ラチェット・上限。
- 省略は毎周の添え書き `rounds/works/round-<N>.json`（土台が書く〔土〕4.5）と報告の冒頭に出る。ラチェットが深さを上げたときの「深さで切った節を走らせる」効き目は、その節が absent なので効かない。これも添え書きの absent の行として出る。
- 周の中の変異の線（`p3.delta_gates`）は absent。`gates` が `in_run` の run では、`p3.gates_cut` が線を台帳に `running` で載せる〔写: RL:716-717〕が、走らせる節が無いので、`close-declare` が graphloops の決まりどおり「止めた回す側が state と理由を書く」（`abandoned`、理由「周の中の変異の線はこのラインに無い（変異は mutgate でまとめて撃つ）」）〔写: RL:671-672 の注記〕。`merge` の run は線を載せない。
- 3 版の「規則がラインにも宣言にも無い節を読んだら `BoardGap`」は、節の表が全部の節を持つ縛り（土台の縛り 1）に置き換わった。

### 4.7 最後の関門（`gates` と mutgate の記録）

- 入力 `gates`: `merge`（既定）か `in_run`。
  - **`merge`**: graphloops の `gates=merge` と同じ。検証器が阻害なし・CI 緑（engine が走らせた物）まで揃った周で、RL の `converge` が `stopped`（`stop_reason: gates_deferred`）を返し、収束を名乗らずに終わる〔写: RL:2029-2037〕。報告は「収束の手前（最後の関門は合流した版で）」と、mutgate を撃つ 1 行と、下の突き合わせの 1 行を出す。持ち主の使い方（変異は版を出す時にまとめて撃つ）と同じなので既定にする（推し。review-graph にも同じ選び方が在り、能力は下がらない）。
  - **`in_run`**: graphloops の既定と同じく、`p4.final_gates` を周の中で受ける。ただし撃つのは run の中の AI でなく、人が別に回す mutgate の run。
- `in_run` の流れ:
  1. 周の他が全部揃うと、graph の条件 `final_gate_due` で `p4.final_gates` が ready になる（`machine`）。
  2. 線 B が一時停止 `final_gate` を開く。関所の文に出す物: 撃つ版（`loop.gates_cut.rev`。engine の `_snapshot` が作った commit）とその木、run の頭の版（`record.base`）、mutgate を撃つ 1 行 `archon workflow run raiki61/works:mutgate --from <gates_cut.rev> --input base_rev=<base> --input head_rev=<gates_cut.rev> --input test_cmd=<test_cmd>`、答え方 `respond <run> continue "mutgate=<record.json の絶対パス>"`。
  3. 答えを受けた `open` が `close.final_gate_reply(b, path)` で記録を確かめ、`p4.final_gates` の返答を組む。確かめる物: `kind` が `works.mutgate/1`・`outcome` が `not_run` でない・`rev` が `gates_cut.rev`・`tree` が `gates_cut.rev` の木で今の作業ツリーの木とも同じ・`from` が `record.base` の版・`gate.human` が `reject` でない。返答は記録の `lane`（〔C〕7 節: G.json の `$defs.lane_reply` そのもの）。
  4. `b.done("p4.final_gates", lane)`。受け付けは写しの `final_gates_output`（`_lane_errors(final=True)`）がそのまま当たる。続く `converge` が写しの `_final_gate_problems`（見逃しが全部 `equivalent`・撃てた腕が 1 本以上・撃った後に作業ツリーが変わっていない）で決める〔写: RL:976-1001〕。`needs_test`・`defect` が在れば `next_round`（次の周の判定へ）、腕 0 本なら `ask final_gate_empty`。
  5. 確かめで拒んだら、理由を文に出して同じ関所を聞き直す。
- **後からの突き合わせ（`merge` の run 用）**: `darkfactory-rounds/scripts/final_gate.py --board <盤面> --mutgate <record.json>` は、同じ 3 の確かめと `_final_gate_problems` と同じ判定を、盤面を変えずに行う。ただし「今の作業ツリーの木」は run の worktree が片付いた後は取れないので、後からの突き合わせでは `gates_cut.rev` の木と記録の `tree` だけを比べる（審査 m5。`gates_deferred` の周の締めで固まった版を正とする）。結果は `final-gate-<tree12>.json` と標準出力に書く。`gates_deferred` で終わった run が、後で撃った mutgate の記録で閉じられるかを機械で言う（graphloops の「合流した版を gates=merge 無しの run で回す」の、撃ち直さない形）。盤面の `status` は書き換えない（報告の結末は `gates_deferred` のまま、突き合わせの結果は別のファイル）。
- 〔C〕13 節の 4（記録を run をまたいで引く口）は、線 B では「人が記録の絶対パスを渡す」で閉じる。木の id から記録を引く置き場は作らない（推し。要るなら後で）。

### 4.8 `ask` と関所の文

- `ask` は盤面と `works-rounds.json` だけから文を組む（関所の文面が飛ばされうる節の欄を読まないため〔試P: P7〕）。返り `{ok, open, message, kind, stop}`。`gate` の文言は `$ask.output.message` だけ（`gate` の `when:` が `ask` の出口を要求するので落ちない）。
- 文に入れる物: 開いた種類と周・問いの項目（engine の `asking` の `question`・`items`・`options`、線 B の一時停止の項目）・選べる答えとその意味（2.3 の表の行）・見るファイル（判定・修正案・差分・検証器の出力のパス、run の worktree の場所〔1 本目の審 I3〕）・止め方の 1 行。
- 開く時は `works-rounds.json` の `gate` に `{seq, kind, source, round, items, applied: false}` を書く。

### 4.9 `report`（輪の外。returns）

- 線 A の報告の部品（`.shared/core/report.py`、線 A の持ち物）を使い、線 B の欄を足す。1 本目の `finish` の欄（`ok・outcome・judgment_file・review_file・diff_file・faces`）を全部残す。
- `outcome`: `converged`・`gates_deferred`・`stopped_by_human`・`stopped_by_request`・`stopped_by_line`（包みが無い等、機械が止めた）・`stopped_at_cap`・`stopped`（ほかの問いへの stop）・`record_invalid`（報告の前の検証器を通らない）・`interrupted`（取り消し・`abandon`・出し直しの上限で落ち、run の外から作った報告）。語は線 A の物（〔A計〕TA12）に揃え、線 B だけの語は `converged`・`gates_deferred`・`stopped_at_cap`・`stopped`。足す欄: `rounds`・`stop_reason`・`gates`・`final_gate_record?`・`report_file`。
- `report.md` の冒頭の並び（機械が組む）: ① 人が決めること（`gates_deferred` なら mutgate を撃つ 1 行と突き合わせの 1 行）② 集めなかった物（節の表の absent と、毎周の添え書きの `in_round`）③ 結末と理由（止めたなら理由・周・段）④ 周ごとの 1 行（検証器の分岐・CI を engine が確かめたか・関所の答え）⑤ 読んだ証拠（線 A の部品）⑥ 見る所。
- **報告の前の検証器**（審査 I5）: graph の `report` は `pre: finalize` を持ち、review-graph（と土台の `_pre_finalize`）は記録を仕上げて検証器に通し、受理集合（graph の `report_accepts_exit`）の外なら報告を出さずに止める（fail closed）。線 B の表では `report.*` が absent なので土台はこの関所を回さない。だから `report` が自分で、線 A の `report.gate_record` と同じ順（〔A計〕TA15: 止めていない盤面は `settle` → `b.finalize()` → `b.run_validator()`（線 B の包み）→ 写しの `report_accepts(b)`）を踏む。外なら結末を `record_invalid` にし（`converged` も `gates_deferred` も名乗らない）、冒頭の 1 行目に検証器の出力の末尾を出す（報告そのものは出す。黙らない）。
- 報告の部品は線 A の `head_decisions`・`head_entry`・`head_stop`・`head_reads`・`head_where`（〔A計〕TA18 の 3）を使う。止めた run は `allow_halted=True` で開く。run の外からも盤面のパスを渡して走る（取り消した run の報告。`uv run works/darkfactory-rounds/scripts/report.py --board <盤面>`）。

### 4.10 目的の文 `p0.purpose`（blk-purpose。〔答〕3）

- graph の `p0.purpose`（`once`・依存は `p0.premises`・`run_by: writer`）を 1 周目の判定の前に回す。書く所は盤面の `process.purpose`（写しの writes のまま）。判定役は凍った目的の文を読む（graph の `p2.diagnose` の reads の `out.p0.purpose.purpose_text`）。
- ブロック `works/blk-purpose/`（線 B の持ち物）: `purpose-snap`（script。作業ツリーの写し）→ `purpose-loop`: 役 `purpose`（`[Read, Grep, Glob]`・sandbox・印 `works-node: purpose`・`output_format` は 0.21.0 の `p0.purpose` の schema そのもの。書く役に見えるが作業ツリーは変えない。graph の `run_by: writer` は「書き手の立場で要約する」の意味）＋受け付け `purpose-accept`（作業ツリーの確かめ → 盤面の `done("p0.purpose", …)`）→ `purpose-reads` → `collect`（`{ok, purpose_file, source, reads_file}`）。
- 指示書は a1202d0 の `prompts/review-loop/p0.purpose.md` を写し、`{{…}}` を入口のファイルを読む形に替える（依頼・作業ツリー・前提の実測 `premises_file`）。
- 出典が「③writer の要約」か「目的不明」の時、graph は `p0.purpose_review`（新しい会話の inspector。optional）で狭めていないかを見る。線 B はこの節を持たない（absent。11.2）。その周の報告の冒頭 ① に「目的の文は役の要約（出典 ③）で、別の目の審査が無い」と出す。
- 境の節: `h-purpose`（`purposing` を回すか・`premises_file` を返す）、`h-judge`（`purpose_file` を返す）。2 周目からは `once` で ready に立たないので飛ぶ。

### 4.11 同じ周の再審（線 A の blk-rejudge。〔答〕4。本線 3-6 の形。写し直しの後）

- 形は線 A と同じ（〔A〕3.7・5.1、〔A計〕T5・T23）。本線の 3-6（d1b863f）の往復: `p3.fix`（修正役が `rejudge_requested` に異議）→ `p2.rejudge`（判定役の続き）→ 決着しなければ `p3.rejudge_reply`（修正役の再異議。新しい会話）→ `p2.rejudge2` → `p3.rejudge_reply2` → `p2.rejudge3` → 3 回とも決着しなければ `p2.rejudge_third`（新しい会話の第三の目）。どの節を回すかは写しの規則（`rejudge*_open`・`rejudge_reply*_due`・`rejudge_exhausted`・`REJUDGE_PASSES`）が盤面の ready で決める。0.21.0 の形（2 節）は第三の目が立たない穴があるので写さない（回す側の指示 2026-09-27）。
- **いつ入るか**: 盤面の写しが 3-6 を含む版になってから（1.5）。それまで再審の節は節の表の absent（宣言）。異議は写しの規則のまま次の周の `p2.history` が再審する（0.21.0 より前の graphloops の形）。
- 再審の役 3 つは包みが判定役の会話の続きとして起こす（印 `continue=judge`・YAML は `context: fresh`）。〔継試〕の B で、`loop_group` の中（周の輪と同じ形）でも継げることを確かめた。周ごとに判定役が会話 id を書き直すので、再審はいつも今の周の判定役（1 回目と履歴の 2 回目を合わせた会話）を継ぐ。再異議と第三の目は新しい会話。
- 境の節 `h-rejudge`: 1 回目の再審が ready で、線 A の `rejudge.session_ready(repo)` が偽なら、ブロックを回さずに一時停止 `rejudge_no_session`（2.3）を立てる。答えは `continue`（`b.skip("p2.rejudge")` で飛ばし、異議は次の周の `p2.history` へ）・`rejudge`（`close_early`）・`stop`。1 周の run の線 A（止めて報告で聞く）と違い、周の輪は同じ関所で聞ける。
- 判定役はどの単位も変えてよく、争点でない単位の変化は線 A の `rejudge-diff.json` に残り、報告の冒頭 ① と周ごとの行 ④ に出る。
- 費用: 報告の費用の行は線 A の `head_cost`（継いだ起動から同じ会話の直前の起動の表示を引く）。周の輪は判定役の会話が周ごとに違うので、引くのは同じ周の中の鎖（判定役 → 再審 1〜3）だけになる。

### 4.12 周の頭の並行 PR と前提（線 A のブロック。〔答〕2・3）

- 並行 PR: `open` が ready の `p0.parallel_pr` を線 A の `prcheck.run_helper(b)` で走らせる（1〜5 段は engine）。任せ先に落ちた時だけ `run: true` で `pr-checking`（線 A の `blk-pr`）を回す。graph の持ち越しの規則（`carry_reason`: 1 周目と、判定から入る run で最初に修正が入った次の周）で後の周にも立ちうる。申し送りは下書きで報告の冒頭 ① に、下げたことは `downgrades.json` と冒頭 ② に出る。
- 前提: `h-pre` が ready の `p0.premises` を見て `premising`（線 A の `blk-premises`）を回す。1 周目だけ（`once`）。依頼の `measured` の測り直しの検査（線 A の `request_claims_covered`）もそのまま効く。
- 周の頭の 3 つ（並行 PR・前提・目的）は、判定より先に盤面で済む。どれかが済まないまま `h-judge` に来たら、線 A の `judge_edge` と同じく止める（`by: "works:premises"` など）。

## 5. 線 A のブロックを使う（約束と申し送り）

線 B は線 A のファイルに触らない（〔土〕6 節）。ラインが線 A の物に頼る約束と、線 A に頼む事を並べる。名前は〔A計〕の物。

- 使う物: `blk-pr`・`blk-premises`・`blk-plan`・`blk-fix`・`blk-rejudge`・`blk-delta`・`blk-refix`・`blk-tests`、`.shared/core/entry.py`（`open_board`・`take`・`empty_fix_reply`）・`halt.py`（`seen`）・`reads.py`（`collect`・`adapter_seen`）・`ticket.py`（`write`・`session_path`）・`node_marker.py`（`mark`・`strip`）・`prcheck.py`（`run_helper`）・`rejudge.py`（`route`・`session_ready`）・`report.py` の部品（`head_*`・`head_cost`・`declared_downgrades`・`gate_record`）、`.shared/adapter/**`（包みの会話の継ぎを含む）、`dev/stop.sh`。
- 約束（線 B の単体テストと筋書きで確かめる。破れていたら直さずに申し送る）:
  1. ブロックのスクリプトは盤面を `entry.open_board` で開く。これは `state.works.line` から節の表を引く（〔A計〕T3）。**加えて、線 B の盤面では線 B の `overrides` と `validator_runner` も渡さなければならない**（渡さないと写しの RR が `not_in_line` を知らずに exit 2 で落ちる。黙りはしないが周が締まらない）。線 B はラインの置き場に `works/darkfactory-rounds/board_hook.py`（`board_kwargs(table) -> dict`）を置くので、`open_board` がラインの置き場のこのファイルを読んで `DiskBoard.open` に渡す形にしてほしい（申し送り 1）。
  2. ブロックの受け付けは `entry.take(board_dir, nid, reply, repo)` で盤面に渡し、周の番号を仮定しない（周 2 以上の盤面でも動く。作業ファイルは `board.work()` の `r<N>/`。〔A計〕の作業ファイルの一覧は `r1/` と書いているので、周 2 で `r2/` に書くかを確かめる）。
  3. `p2.human_gate` の問いは盤面の `asking` に立つ（線 A の輪の外の関所 `policy-gate` と中の関所 `mid-gate` は線 B のラインに置かない。持ち主の決定 1.1 の 3）。
  4. 直す単位 0 の周は `entry.empty_fix_reply()` を `take` で渡せる（〔A計〕TA6）。
  5. 筋書きが stub する節の id（役の節と受け付けの節）が、全部のブロックをまたいで一意（〔台帳〕R19）。
  6. `halt.seen(board_dir)` の返りが止め札の中身（`reason`・`by`）で、止めるのは呼び出し側が土台の `stop()` で行う（〔A計〕T8）。
  7. 修正前の CI の任せ先の分（`p0.local_checks` の `fallback: machine`）の素材を組む関数が、`entry.start` の外から呼べる（申し送り 2）。
  8. `reads.adapter_seen(board_dir, run_id)` と `reads.collect(...)` が周 2 以上の盤面で動く。
  9. `blk-rejudge` の受け付けと `rejudge.route`・`rejudge.session_ready` が周 2 以上の盤面で動き、包みの `sessions/<cwd>/judge.id` が周ごとの判定役で書き直される（〔継試〕の輪の中の形）。
  10. `blk-pr`・`blk-premises` のスクリプトが線 B の盤面（線 B の差し替えつき）で動き、`prcheck.run_helper` が境の節から呼べる。
- 申し送り（線 A へ）: 次の 4 つは〔A計〕TA18（改訂 2）に入った。線 B の計画は、これらが線 A の枝に在ることを着手の前に確かめる（計画の前提と T4 の Step 0）。
  1. `entry.open_board` がラインの置き場の `board_hook.py` を読む。`begin` に渡す物は `entry.hook_kwargs(line)`（約束 1）。
  2. `entry.local_checks_material(repo, test_cmd, log_path)` と `entry.run_ci(b, nid, *, test_cmd, runner=None)` を `start` の外から呼べる（約束 7）。
  3. `report.py` の `head_decisions`・`head_entry`・`head_stop`・`head_reads`・`head_where` と `gate_record`（報告の前の検証器）。
  4. 線 A の T2 の試験（`test_judge_block_policy_entry_only`）と筋書き（`test_judging_stubs_follow_block`）が blk-judge の `intake` に頼らない。
- 申し送り（土台へ。審査 m2。台帳の側で渡す）: 盤面の `state.works.overrides` に名の在る差し替え（線 B の `validator_module`・`fill_materials`）や `validator_runner` を渡さずに `DiskBoard.open` したら、`BoardGap` で止める。今は検証器が `not_in_line` を知らずに exit 2 で落ちるので黙りはしないが、落ちる場所が周の記録まで遅れる。
- 逆向きの依存（線 A が線 B の物を使う）: 線 A の 1 周のラインも `blk-judge` を include し、`request`・`base_rev`・`policy_paste` を渡す（〔A計〕T17）。判定は 1 本目の受け付けで受け、境の節が盤面に渡し替える（〔A計〕TA3。盤面に既に在れば渡さない）。v2 は入口と節の名前と出口の欄を 1 本目と揃えるので（4.3）、線 A のラインは v2 に替わってもそのまま動く。merge の順（A → B）で v2 が後に入っても、線 A の渡し替えが「既に在る」を見て 2 度受けない。
- 着手の順（審査 I7）:
  1. 線 B の枝は、線 A の枝の先から切る。条件は、線 A の T2（blk-judge の `policy_paste`）と TA18 の 4 件（上の申し送り 1〜4）が線 A の枝に commit されていること。これで線 B の T9 は `policy_paste` の上に作れ、線 A の試験が v2 で赤にならない。
  2. 線 B の T4 の前に、TA18 の 4 件が在ることを機械で確かめる段を置く（関数の名前と、線 A のその試験が緑か）。無ければ止めて報告する。
  3. 線 B の T9（blk-judge v2）の後に、線 A の 1 周のラインの試験（線 A の通しの試験と筋書き、`check.sh`）を v2 で回し直す段を置く。赤なら線 B の v2 を直す（線 A のファイルは直さない）。
  4. ライン `darkfactory-rounds.yaml`・報告・筋書きは、線 A のブロックの YAML の切り替え（〔A計〕T17）が入った後に、線 A の枝の先へ載せ直してから作る（merge の順は 写し直し → 土台 → A → B → C〔土〕6 節）。

## 6. 役の会話と、役が読む物

- 役ごとに新しい会話で起こし、役どうしの受け渡しは盤面と機械の出力だけにする（1.1 の 4）。1 本目の実走で役ごとに会話が別だった〔台帳: T10 (7)〕。
- 形: 役の節を、自分のブロックの出し直しの輪の中のただ 1 つの AI の節にする。輪の 1 回目は必ず新しい会話〔A/: dag-executor.ts:5064-5069〕、include の入口の節も前の会話を継がない〔A/: dag-executor.ts:10417-10427〕。
- 輪の本体に、ブロックの輪の外の AI の節を直に置かない。置くなら `context: fresh` を必須にし、YAML の検査で縛る（〔台帳〕方針 9 の置き方）。
- 例外は判定の 2 回目だけ（同じ役の続き。4.3）。
- 読む物の渡し方（貼る・パスを渡す・読んだ証拠）は線 A の部品に揃える（〔A〕5.2）。判定の分の `judge-reads` は線 B が blk-judge に置く。

## 7. 範囲と順

- 入れる: 2 節のライン・3 節の表と置き場・4 節の全部（start・open と境の節・判定 v2・早く聞く・close_early・blk-close・宣言した省略・最後の関門・ask・report）。
- 入れない（線 A が作る）: 止め札・包み・読んだ証拠・数え直し・修正案と事前審査・手直しの 2 往復・手厚さ。
- 入れる（〔答〕の後）: 周の頭の並行 PR と前提（線 A のブロック。4.12）・目的の文（`blk-purpose`。4.10）・同じ周の再審（線 A の `blk-rejudge`。4.11。本線 3-6 の写し直しの後）。
- 下げる（〔答〕2。持ち主が選んだ）: 並行 PR の申し送りを投稿しない（下書きを報告に）。
- 入れない（後の段）: 目的の審査（`p0.purpose_review`）・前の決定の掘り起こし（`p0.prior_decisions`）・P1 の目・R1〜R4・AI が書く報告と初見検査・仕様から入る道・TDD の修正。どれも節の表の absent と報告の冒頭に出る。
- 順（計画の筋）: ① 節の表と宣言の導き → ② 検証器の包みと差し込み → ③ blk-judge v2 と `rounds.py`（start・状態・境の節）と最後の関門 → ④ 答え・一時停止・close_early → ⑤ blk-close → ⑥ 報告・ライン（線 A の合流の後）→ ⑦ 周の頭（並行 PR・前提・目的）と同じ周の再審（〔答〕。ラインに足す）→ ⑧ 筋書きと共有のファイル → ⑨ 実走（持ち主の了承）。Archon の試しの AI 費用 0 の分は ① と並べて先に撃つ。

## 8. 守り（1 本目から変わる所だけ）

- 盤面は run の作業ツリーの外（`$ARTIFACTS_DIR`）。盤面に書くのはつなぎ（script の節）と線 A の包みだけ。役は盤面に書かない。
- 写しは 1 バイトも変えない。線 B が写しの関数を呼ぶ所（`_stopped_round_record`・`open_next_round`・`STOPPED_BY`・`fill_materials`・`report_accepts`・RR の `main`、土台の私的な `_write_round_note`）は、写し直しで名前が変わっても 1 か所で直せるよう、`rounds.py`・`close.py`・`rounds_validator.py` の中の薄い関数 1 つずつから呼ぶ。
- 期限は 1 本目と同じ（AI の節の `idle_timeout`・script の節の `timeout` は `1728000000`〔台帳 R4〕）。新しい期限は足さない。`max_iterations` は有限（判定の内の輪 6・周の輪 20）。
- AI の節は `settingSources: []`・sandbox `{enabled: true, allowUnsandboxedCommands: false}`〔台帳 R12〕・`model:` を書かない。
- 節のスクリプトは全部 PEP 723 の頭を持ち、標準ライブラリだけ。bash の節で `&` を使わない〔試P: P9〕。
- 対象・開発の家・切符の置き場を `/private/tmp/claude-*` の下に置かない（開発の殻が拒む〔66b1543〕）。

## 9. 危うい所

- **今壊れている物**: 無い（線 B はまだ無く、既存の `darkfactory` に触らない）。
- **壊れる余地**:
  - 宣言の差し込み（4.6）は RL の大域の名前 2 つを差し替える。写し直しで `fill_materials` の呼ばれ方や名前が変わると、宣言が黙って効かなくなりうる。単体テストで「宣言した素材が `not_run` でなく `not_in_line` になる」を毎回見る（名前が無くなれば土台の `overrides` が `BoardGap` で落ちる）。
  - `close_early` は engine の `cmd_stop` の盤面の部分を写しの部品で組み直す。engine の止め方と印がずれると、締めた周の記録が検証器で落ちる。落ちたら周を開かずに聞き直す（4.4 の 3）ので黙らないが、手本（土台の撮った `test_stop_midround`）と同じ印になるかを単体テストで見る。
  - 判定の 2 回目の出力の型を和で書く（4.3）。SDK が和の型を受けない・片方の欄を落とすと、受け付けが毎回拒む。試し P6e で先に見る。崩れたら案 (c)（2 回目を別の節にし、型を分ける）に倒す。
  - 判定の内の輪で拒否が上限（6）を超えると run が失敗で止まる。resume は 4.3 の「resume の時」の形になる。試し P6a で見る。
  - 長い履歴の束（40,000 バイト近い）を `next` に貼ったときに差し込みが崩れるか（試し P6c）。崩れたら貼る上限を下げ、それでも読めなければ案 (c)。
  - `in_run` の最後の関門は、撃つ版が engine の `_snapshot` の commit（枝に載らない commit）。mutgate の run が `--from <sha>` で切れるのは同じ object の置き場に在るとき（Archon は同じ codebase の `.git` を共有する）。git の片付け（gc）で消える前に撃つ（既定の猶予は 2 週間）。消えていれば mutgate の `pin` が版を引けずに止まる（黙らない）。
  - `in_run` の関所は mutgate の run（何時間もかかる〔C〕8 節）が終わるまで開いたまま待つ。その間に run の作業ツリーを人が触ると、`_final_gate_problems` が「撃った後に作業ツリーが変わった」で通さない（正しい向き）。
  - 周の輪の 1 回の実走は高い（最短 3 周。上限は既定 5 周で、`continue` で 1 周ずつ延びる）。直す物の無い周は修正の役を起こさず空の返答を渡す（2.2 の 4）が、判定の役は毎周起きる（収束には連続 2 周の判定が要る）。費用は 10.5 で見積もり、持ち主の了承を取ってから撃つ。
  - 線 A のブロックが線 B の盤面を線 B の差し替え無しで開くと、写しの RR が `not_in_line` を知らずに exit 2 で落ち、周が締まらない（黙りはしない）。5 節の申し送り 1 が入るまで、線 B のラインは組めても通しでは回らない。
  - 線 A のブロックの約束（5 節）が破れていると、線 B のラインの筋書きで初めて分かる。線 B の単体テストで先に見られる物（周 2 の盤面でのブロックのスクリプト）は先に見る。
  - 〔答〕で入る節は、入る Task までの間 absent（再審の節は写し直しまで）。毎周の添え書きと報告の冒頭に出るので黙っては欠けない。
  - 本線の 3-5・3-6 を写すと、盤面の層の受け付け・`accept.py`・線 C の `mutcore` が壊れる（今は壊れていない）。写し直しの線が直す（1.5）。線 B の側で直す所は、写しの関数を呼ぶ薄い関数（8 節）と、節の表の graph_sha と行。
  - 再審の会話の継ぎは線 A の包みに頼る（〔継試〕の壊れる余地: 費用の二重計上・id が無い時の 12 回の起こし直し・SDK の版上げ・印は `output_format` に依る・cwd で分ける）。id が無い時は `h-rejudge` が先に一時停止を立てるので、12 回の起こし直しには行かない。
  - 周の輪では判定役が周ごとに会話 id を書き直す。再審が前の周の判定役を継ぐ道は無い（graph も同じ周の判定役を継ぐ）。resume の後に内の輪が新しい会話で 2 回目を起こした周は、その新しい会話を継ぐ（4.3）。
  - 並行 PR の任せ先の役の `gh` の通信が sandbox で拒まれる環境では、役が `not_run` を返し、報告に出る（線 A の P18 で見る）。

## 10. テスト

### 10.1 単体（Archon 不要。`works/tests/run.sh`。お金 0・AI 0）

1. 節の表: 土台の縛り 1〜5 を通る。`where` がブロックの名前（works の仮の名。本線の 3-7 の後に揃える）。absent の行に理由と `comes_with`。〔答〕で入る節の行が、入る Task の前は absent（理由に Task）、後は線 A と同じ行（`p0.purpose` だけ線 B の role）。役の行が線 A の表と同じ（線 A の表が在るときだけ）。
2. 宣言の導き: `materials` が 12・`reviews` が R1〜R4・`nodes` が absent の全部。表の行を 1 つ `role` に替えると、その節が書く素材が宣言から消える。
3. 検証器の包み: 縛り ①〜③ の良い見本と悪い見本（1 本 1 違反。② は宣言した素材に `clean`・宣言した目に本物の判定を書いた見本、`not_run` は通る見本）。`not_in_line` が阻害要因に出ない。包みを通しても写しの RR のファイルの sha が変わらない。止め札で止めた周（目が `not_run`）の記録が通る。
4. 差し込み: `begin` した盤面（使い捨ての git リポジトリ。`.review-checks.json` で CI を engine が走らせる）で、周 1 の `p1.worktree_after` の後に宣言した素材が `not_in_line`（P1 の素材は engine の `not_applicable` のまま）。`close-declare` の後の `p4.record` で R1〜R4 が `not_in_line`、検証器の exit が 0 か 1。
5. 収束の道（手で書いた返答の見本 `tests/replies/rounds/`）: 周 1 に block → 修正 → 周 2・周 3 が阻害なし、で `gates=merge` なら `stopped`・`gates_deferred`、`in_run` で偽の mutgate の記録を渡せば `converged`。上限の周で `ask max_rounds`、`continue` で 1 周だけ延びる。
6. 境の節: ready と段の対応（全部の段）。`asking` が在れば全部の段で `run: false, ask: true`。止め札で `stop: true` と `finished`（理由と `by` が `state.stop` に）。終わった盤面で `finished`。包みの無い run が `h-plan` で止まる（`adapter: optional` なら止まらない）。直す単位 0 の周で `p3.fix` に空の返答が渡り、修正のブロックが走らない。周の番号を書かない。
7. 答え: 2.3 の表の全部の行と `approve`・`reject`。`max_rounds`・`final_gate_empty` への `rejudge` は聞き直しで、上限が上がらず `final_gate_empty_ok` が置かれない。engine の問いと一時停止が重なった回の答え。同じ `seq` の答えを 2 度当てても 1 度だけ記録される。`applied` が偽のまま `$LOOP_PREV` 空なら同じ関所をもう一度開く。
8. `judge_asks`: `escalate` の問い・`held` の `fork` で開く、`decided` の `fork` では開かない、答えた `key|status` では開き直さない（状態が変われば開く）。周の終わりの `questions_open`: `held` の問いが答えの無いまま残れば開く。
9. `close_early`: 締めた周の `rounds/round-<N>.json` の素材と目が `not_run`、次の周が開き `process.human_answers` に一言、`works-rounds.json` の `rejudge` に周。締めた周の次から「連続 2 周」を数え直す（その周の次の周が阻害なしでも収束しない）。検証器が拒む盤面では周を開かない。
10. `tests_red`・`stuck`: CI が `found` の周の後・`stuck` の問いが立った周の後に開く。
11. 最後の関門: mutgate の記録の見本（`tests/fixtures/mutgate-records/`: 良い・版が違う・木が違う・`from` が違う・`not_run`・`gate.human: reject`・見逃しに `needs_test`・腕 0 本）で、受ける・拒む・`next_round`・`final_gate_empty` が写しの規則どおり。`final_gate.py` が盤面を変えない。
12. 判定 v2: 盤面の `state.works.line` の表で開く（線 A の形の表で作った盤面で 1 回目が通り、2 回目を求めず、`state.works.overrides` が増えない。違う表を渡すと `BoardMismatch`）。盤面の instance で 1 回目・2 回目を決める。1 周目は 2 回目を求めない。2 回目で前の周の未決の問いが消えていれば拒む。拒否の回に盤面が 1 バイトも変わらない。履歴の束が graph の `p2.history` の reads の全部を持つ。40,000 バイトを超えると先頭と続きのパス。resume の時に「新しい会話で 2 回目」と trace に残る。YAML の出力の型が 2 つの型の欄を全部持つ。
14. ブロックの入口（C1）: ラインのブロックの `with:` の参照先が `start`・`open`・`h-*` だけ。各 script の `INPUTS` の定数が YAML の `with:` の鍵と同じ（〔A計〕TA16 と同じ縛り）。境の節の出口の `judgment_file`・`open_units`・`plan_file`・`human_notes` が盤面（`state.outputs[節]["file"]`）と合う。`start` の出口に方針の 2 つが在り、方針の無い対象では空。報告の前の検証器（I5）: 受理集合の外の終了コードで結末が `record_invalid`。
15. 周の頭（4.10・4.12）: 1 周目に `open` → `pr-checking`（任せ先に落ちた時だけ）→ `premising` → `purposing` → 判定の順で盤面が進み、2 周目は前提と目的が飛ぶ（`once`）。判定役の入口に `premises_file`・`purpose_file` が届く。`p0.purpose` の返答が写しの schema で拒まれる見本と通る見本。目的の出典が ③ の周に報告の冒頭 ① の 1 行。並行 PR の持ち越しの周に `pr-checking` がもう一度立つ（写しの規則どおり）。
16. 同じ周の再審（4.11。写し直しの後）: 周 2 の盤面で異議 → `h-rejudge` → `rejudging` が 3-6 の往復を回し、`record.process.rejudge` に行。会話の id が無ければ一時停止 `rejudge_no_session`、`continue` で `p2.rejudge` が skipped・異議は次の周の `p2.history` へ、`rejudge` で `close_early`、`stop` で止まる。周ごとに判定役の id が書き直される（包みの偽の起動で）。写し直しの前は、異議の在る周でも再審の節が absent で走らず、添え書きと報告に出る。
17. 下げた物: `downgrades.json` の 1 行が報告の冒頭 ② に出る。
13. 線 A のブロックの約束（5 節の 1〜10）: 周 2 の盤面で線 A の各ブロックの受け付けのスクリプトが `entry.open_board` で線 B の差し替えつきで開き、`r2/` に書き、`take` で盤面を進める。直す単位 0 の周で `empty_fix_reply` が通る（線 A のブロックが合流した後の Task で見る）。

### 10.2 Archon の試し

- 済み: P1〜P5〔試〕・案 (d)〔試d〕・P7〜P13・P16〔試P〕・包みの会話の継ぎ（平らな線と `loop_group` の中。〔継試〕）。線 A に移った物: P11 の AI の節の分・P13 の `tool_called`・P14・P15（〔A〕9.3）。
- 残り（線 B の分）:
  - P6a（AI 費用 0。受け付けを常に拒む bash）: 判定の内の輪が上限を超えた run の止まり方と、resume の後に 4.3 の「resume の時」の形になるか。
  - P17（AI 費用 0。新規）: この版の形そのもの——ブロック 10（中身は bash の代役。周の頭の 3 つを含む。再審は写し直しの後に同じ形で足す）と境の節 9・`open`・`ask`・`gate` を並べた輪で、`gate` が唯一の末端と認められるか・ブロックの `when:` が境の節の `run` だけで選ばれるか・答えの後に同じ周の続きへ入るか・途中の Ctrl-C → resume で同じブロックから回るか。加えて（審査 m1）: `with: {prev: "$LOOP_PREV.gate.output"}` が JSON の文字列で届き、1 回目は空で、人の一言に引用符・改行・`$(x)` が在っても壊れないか。`when:` で飛ばされた `gate` が回を終え、次の回に入るか。include の `with:` が境の節と `start` の欄を読む形（2.1 の C1 の配線）が、判定のブロックが飛ぶ回でも落ちないか。
  - P6b（数セント）: 内の輪より後ろに `context: fresh` 無しの AI の節を置くと判定の会話を継ぐか（継ぐなら YAML の検査の裏付け）。
  - P6c（数セント）: `next` に 40,000 バイト近い文を入れても差し込みが崩れないか。
  - P6e（数セント。新規）: 判定の節の `output_format` を 2 つの型の和にしたとき、SDK が受け、1 回目と 2 回目でそれぞれの型の欄を返すか。あわせて、内の輪で script の節 `judge-stage` が `judge` の前に在っても、2 回目が 1 回目の会話を継ぐか（〔試d〕は `judge`＋受け付けだけの形で見た。審査 m1）。
- AI を使う 3 つは合わせて 1 ドル未満の見込み（名目）。**撃つ前に持ち主の費用の了承を取る**（線 A の P14・P15 と一緒に聞く）。

### 10.3 筋書き（`--dry-run`、お金 0）

- `--dry-run` は until_bash を評価しない（輪は 1 回で終わる）〔台帳 R11〕。見るのは 1 回の中の道だけ: 周の頭（並行 PR の任せ先・前提・目的）→ 判定 → `judge_asks` → 関所／判定 → 修正案 → `p2.human_gate` の問い → 関所／1 周の全部 → 締め → 次の周／締め → `tests_red`／締め → `final_gate`／境の節で止め札 → report／`start` が依頼を拒む。写し直しの後に足す: 修正 → 異議 → 再審 → 審査／修正 → 異議・会話が無い → `rejudge_no_session` → 関所。
- stub するのは役の節と受け付けの節だけ（id は全部のブロックで一意）。`collect` 系と境の節は本物を走らせ、盤面の見本（`fixtures/boards/`）を `ARTIFACTS_DIR` に置いて道を選ばせる。

### 10.4 共有のファイルの検査（線 B の最後の commit）

- `test_yaml_rules.py` に足す決まり（1 本 1 違反の悪い見本つき）: 輪の中の関所は唯一の末端・`decisions` を持つ関所は `reject` を持つ・until_bash は盤面のファイルだけ・関所の文面と bash の本文は飛ばされうる節の欄を読まない・script の節の `with:` の `from:` は `if_skipped` つき・bash の本文に `&` を書かない・AI の節は出し直しの輪の中のただ 1 つの AI の節か `context: fresh`・`max_iterations` は 3・6・20 のどれか・AI の節に `model:` が無い。線 A が同じ決まりを先に足していれば、線 B は足りない分だけ足す。

### 10.5 実走（持ち主の費用の了承を取ってから）

- 使い捨ての対象に、周 1 で block が出て周 2・3 で消えるバグを仕込む（最短 3 周）。加えて判定の後に問いを出させる筋を 1 本（`continue` と `rejudge` を 1 回ずつ）。止め札は途中で 1 回。`gates=merge` で回し、`gates_deferred` の後に `final_gate.py` を小さな偽の mutgate の記録で当てる（本物の mutgate は撃たない）。
- 見ること: 周の番号と段の移り・関所が要る時だけ開く・`close_early` の後の周・報告の冒頭（省略・理由・読んだ証拠）・役の会話が役ごとに新しい（`binding.sessionOrigin`）・所要と費用。
- 費用の見込み: 1 本目は opus で 1 回 0.6 ドル前後〔台帳: Task 10〕。線 A の 1 周が 1〜1.5 ドル（〔A〕9.4 の推測）で、周の輪は 3 周以上なので **1 回 3〜5 ドル**（推測）。推しは opus で 2 回、合わせて 10 ドルを上限の目安（12 節の 2）。

## 11. review-graph（0.21.0）との能力の差

基準は判定から入る run を上限まで回す review-graph（a1202d0）。黙った欠け（報告に出ず機械も気づかない欠け）は 0 にする。

### 11.1 同じか上

- 周を回す芯（連続 2 周・問いの台帳・defer と開き直し・3 周続く block・ラチェット・上限）: 写しの規則と検証器そのもの。
- 周の中の順と機械の節（版固め・周の記録・`converge`・次の周の頭）: 土台の `settle` が engine と同じ順（〔土〕12 節）。
- CI を engine が確かめた印（`by: "engine"`）: 土台の `run_engine`。
- 判定の 2 回（`p2.diagnose` → `p2.history` を同じ会話で）: 案 (d)。resume の時だけ graph が許す新しい会話。
- 人への問い: engine の問いは同じ。線 B は `judge_asks`・`tests_red`・`stuck` を足す（早く・多く聞く側で、上）。
- 最後の関門: `merge` は review-graph の `gates=merge` と同じ。`in_run` は同じ節・同じ規則（`_lane_errors`・`_final_gate_problems`）で mutgate の記録を読む。撃つ所は mutgate（決まった script が撃ち、等価の申告を人が必ず見る〔C〕10 節）。
- 外から止める・子を木ごと止める・読んだ証拠・起動ごとの柵・数え直し・修正案と事前審査・手直しの 2 往復: 線 A の物（〔A〕10 節の表で同〜上）。
- 同じ周の再審: 写し直しの後に上（本線 3-6 の 3 往復と第三の目。0.21.0 の review-graph は 1 往復で止まり第三の目が立たない。包みで判定役の会話を継ぐ。〔継試〕で輪の中でも確かめた）。争点でない単位の変化を記録と報告に出す分も上。会話の id が無い時は条件付き（一時停止で人に聞く。`continue` なら次の周の `p2.history` が再審する）。写し直しまでは 11.2（宣言）。
- 前提の実測（`p0.premises`）: 同〜上（線 A の物。依頼の `measured` の測り直しの検査が上）。
- 目的の文（`p0.purpose`）: 同（写しの schema のまま。4.10）。
- 並行 PR の交差の検査: 同（engine の 1〜5 段と任せ先の役の 6 段の読み）。

### 11.2 宣言して集めない（毎周の添え書きと報告の冒頭に出る）

- 目的の審査（`p0.purpose_review`。出典が ③ の周に立つ optional の目）・前の決定の掘り起こし（`p0.prior_decisions`）と P1 の目の全部（素材 12 のうち並行 PR を除く 11 と同じ節）。
- R1〜R4 と `r4.human_gate` の問い・`stop.premise_check`（R2 が無いので立たない）。
- 周の中の変異の線（`p3.delta_gates`）: 持ち主の決定（変異はまとめて撃つ）のとおり（〔台帳〕R30）。
- AI が書く報告と初見検査（`report.*`）・仕様から入る道（`spec.*`）。
- 同じ周の再審の節（写し直しまで。本線 3-6 の形で入れるため）。〔答〕で入るほかの節の、入る Task までの間。

### 11.3 形を変えて持つ（能力は同じ、仕組みが違う）

- 周を締めて次の周（`close_early`）: review-graph に同じ口は無く、近いのは「止める」。線 B は止めずに次の周を開く（上か同じ）。締めた周も上限と「3 周続く block」の 1 周に数える（人には見えにくいので報告の周ごとの行に「締めた周」と出す）。
- 報告の前の検証器: review-graph は受理集合の外で報告を出さない。線 B は報告を出したうえで結末を `record_invalid` にし、冒頭に出す（収束を名乗らない点は同じ。4.9）。
- `merge` の run の後始末: review-graph は「合流した版を gates=merge 無しの run で回す」。線 B はそれに加えて、撃ち直さずに mutgate の記録で突き合わせる `final_gate.py` を持つ。
- 起こし直しの記録（attempt_log）: Archon の run が 1 つの持ち主で、失敗は resume と盤面の冪等（3.3）に任せる。

### 11.4 持ち主の決定で下げた物（〔答〕）

- 並行 PR の申し送りを担当の PR へ投稿しない（〔答〕2）。下書きは報告の冒頭 ① に出るので、人が投稿すれば review-graph と同じになる。`darkfactory-rounds/downgrades.json` と報告の冒頭 ② に出る。
- 4 版のこの節に在った `p2.rejudge` の「答え待ちで下がる」は、〔答〕4 で 11.1（写し直しの後に上）へ移った。

## 12. 持ち主に聞くこと

1. **`p2.rejudge` の持ち方**: 決まった（〔答〕4）。4 版の案 1〜3 のどれでもなく、review-graph と同じ「判定役の会話の続き」を線 A の包みで作る（〔継試〕で Archon の輪の中でも継げると確かめた。4 版の「Archon では判定役の会話を修正のブロックの後で継げない」は Archon の `context.resume` の話で、包みの `--resume` には当たらない）。形は回す側の指示（2026-09-27）で本線の 3-6（3 往復と第三の目）にし、写し直しの後に入れる。会話の id が無い時は一時停止で聞く（4.11）。
2. **実走の了承**（10.5）: 推しは opus で 2 回、合わせて 10 ドルを上限の目安（名目）。Archon の試しの AI の分（P6b・P6c・P6e、合わせて 1 ドル未満）は線 A の P14・P15 と一緒に先に聞く。

（軽量・並行 PR・目的と前提も決まった。1.3。新しく聞く物は無い。本線を待つ物は 1.5。）

## 13. 1 本目と台帳から引き継ぐ注意

- include の id とブロックの中の節の id を重ねない〔台帳 R17〕。受け付けの節の名前は役ごとに分ける〔R19〕。
- 指示書の中の `$LOOP_PREV.<役>-accept.output.*` は include のときだけ置き換わる〔R16〕。判定の 2 回目の `next` も同じ形で読む。ブロックの `inputs:` に無い `$INPUTS.<名>` を指示書に書かない〔R16〕。
- `$LOOP_PREV` は直前の回だけ・1 回目は空・`with:` の `from:` では読めない〔研 §4〕。周をまたぐ値は盤面に置き、`$LOOP_PREV` は関所の答えと受け付けの一言にだけ使う。
- 関所の `decisions` には `reject` を書く〔R32〕。
- 実走は前景で回し、止めるときは pid と cwd を確かめる。`pkill -f` を使わない。

## 改訂（盤面の層に載せ替え）（2026-09-27）

3 版は自前の盤面（`DiskBoard` を線 B が作る）と写しへの足し算を前提にしていた。盤面の層（〔土〕）が実装中になったので、その上に載せ直した。

- **外した物（土台へ）**: 3 版の 3 節（盤面の置き方・`DiskBoard`・黙った None を `BoardGap` で落とす縛り・`transaction()`）。土台の `DiskBoard`・節の表・`settle`・`run_engine` に置き換えた。「黙った None」は、節の表が graph の全部の節を持つ縛りに替わった（BL4）。
- **外した物（線 A へ）**: 3 版の 1 節の 10〜12・2.5 の止め札の作り・4.5 の数え直し・5.3 の読んだ証拠・12 節の Claude の包み・11 節の 1（包みの無い環境。台帳で決定済み）。線 B は使う側になり、約束を 5 節に並べた（BL13）。
- **写しへの足し算をやめた**: 3 版の「検証器の STATUS に `not_in_line`・RL の `converge` の最後の関門の宣言・`COPIED_FROM` に works の足し算」は、検証器の包み（`rounds_validator.py`）と `overrides` 2 つ（`validator_module`・`fill_materials`）と、`p4.record` の前に目を記録に置く `close-declare` に替えた（BL2・BL5）。最後の関門の宣言（`final_gate: true`）は無くなり、graphloops の `gates=merge` をそのまま使う（`merge`）か、mutgate の記録を `p4.final_gates` の返答として受ける（`in_run`）の 2 つにした（〔台帳〕R30。4.7）。
- **段の決め方**: 3 版の `open` の段（stage）の表と、周の番号を `open` が上げる決まりをやめた。どのブロックを走らせるかは盤面の ready から境の節が決め（2.2）、周の番号は engine が上げる（3.3）。
- **関所**: 開く所に engine の問い（`p2.human_gate`・`converge` の 5 種）と `final_gate` を足し、答えの表を 5 行にした（2.3）。`stuck` は a1202d0 の判定の受け付けが台帳への記載を要求するので、検証器の exit 2 を拾う形から「`stuck` の問いが立った周」を見る形に替えた。
- **rejudge**: 3 版の「`open` が stage=close にして `closing` が締める」を、写しの `_stopped_round_record` と engine の `open_next_round` で組む `close_early` に替えた（4.4）。
- **判定 v2**: 受け付けを土台の `b.done` に替え、1 回目か 2 回目かを盤面の instance で決める形にした。出力の型の和・resume の時の新しい会話の 2 回目を足した（4.3）。
- **ライン**: `darkfactory/` を書き換える形から、別の入口 `darkfactory-rounds/` に替えた（R25）。ブロックは線 A の `blk-plan`・`blk-fix`・`blk-delta`・`blk-refix`・`blk-tests` を並べる（2.1）。1 本目の順（修正の直後にテスト）でなく graph の順（手直しの後にテスト）。
- **基準の版**: fbd40e3 から a1202d0（graphloops 0.21.0）に替えた（BL1）。
- **線 A の計画（〔A計〕）に揃えた**: 線 B の境の節は線 A の部品（`halt.seen`・`reads.adapter_seen`・`entry.take`・`entry.empty_fix_reply`）を呼ぶ。直す単位 0 の周は修正の役を起こさず空の返答を渡す（〔A計〕TA6）。blk-judge v2 は線 A のライン（`request`・`base_rev`・`policy_paste` を渡し、判定を境の節で盤面へ渡し替える〔A計〕TA3）を壊さないよう、入口・節の名前・出口の欄を 1 本目と揃えた（4.3・5 節）。線 A のブロックが線 B の盤面を開く時に線 B の差し替えを渡す口（`board_hook.py`）を申し送りにした（5 節）。
- **聞くこと**: 3 版の 11 節の 1（包みの無い環境）は台帳で決まった。3・4（P6c・P11 が崩れたとき）は推しのまま本文へ入れた。新しく 12 節の 1（`p2.rejudge`）を足した。軽量と並行 PR は土台の 13 節の答え待ちとして 1.3 に書いた。

3 版の節との対応:

- 1 節の 1〜9 → 1.1（そのまま）。10〜12 → 1.2（線 A）。1.1 → 1.4
- 2.1 → 2.1・2.2。2.2 → 2.3。2.3・2.4 → 2.4。2.5 → 2.5（線 A を使う）
- 3.1〜3.2 → 土台（〔土〕3・4 節）と 3.1・3.2。3.3 → 3.3。3.4 → 4.1 の最後
- 4.1 → 4.2。4.2 → 4.3。4.3 → 4.5。4.4 → 4.6・4.7。4.5・4.6 → 5 節（線 A）。4.7 → 4.9
- 5.1・5.2 → 6 節。5.3 → 線 A（6 節の最後）
- 6 → 7。7 → 8。8 → 9。9.1 → 10.1。9.2 → 10.2。9.3 → 10.3。9.4 → 10.5
- 10 → 13。11 → 12。12 → 線 A（〔A〕5.1）。13 → 11

## 改訂 5（審査 作業の控え（scratchpad）の `rounds-plan-review.md`「Approve with changes」への対応。2026-09-27）

回す側の裁定（C1・I3・I4・I5・I6・I7・m2）に従った。線 A の計画と仕様の改訂 2（`works/docs/plans/2026-09-27-darkfactory-single-run.md`・`works/docs/specs/2026-09-27-darkfactory-single-run-design.md`）の口にも揃えた。前の版は 作業の控え（scratchpad）の `rounds-spec-draft.v4.md`。

- **C1**（線 A のブロックの入口の配線）: 2.1 に「ブロックの入口は、いつも走る節の欄か盤面からだけ渡す」を足し、ブロックごとの入口と出どころを並べた（`start` の出口に `base_rev`・`test_cmd`・`policy_paste`・`policy_path`、境の節の出口に `judgment_file`・`open_units`・`plan_file`・`human_notes`）。方針の文書は線 A の `policy.brief` で組み、読む役に貼る文・書く役にパスで届く。2.2・4.1 の返りを直し、10.1 の 14 に試験を足した。
- **I1**（`$LOOP_PREV` の読み方）: `with: {prev: "$LOOP_PREV.gate.output"}` の文字列の束ねに替えた（`from:` は Archon が読み込みで拒む）。空は「開かなかった」か「答えを失った」で、見分けは `works-rounds.json` の `applied` だけ（3.3 の 3・4.2）。P17 に確かめる物を足した。
- **I2**（決着した `fork`）: `judge_asks` の条件を「`held`・`escalate` のうち、`escalate` か `fork`」にし、`answered` を `key|status` の組で持つ形にした（2.3・3.2・4.4）。
- **I3**（`held` の問い）: 持ち主の決定 1.1 の 3「人への問いが残る」のとおり、周の終わりの一時停止 `questions_open` を足した（2.3）。持ち主の決定の字面どおりなので持ち主に聞く物ではない（台帳に残すだけ）。
- **I4**（`rejudge` が `continue` の副作用を持つ）: `max_rounds`・`final_gate_empty` への `rejudge` は聞き直しにした（上限を上げない・腕 0 本の同意を置かない）。2.3 の表を 6 行にした。
- **I5**（報告の前の検証器）: `report` が線 A の `gate_record` と同じ順で `finalize` → `run_validator` → `report_accepts` を踏み、外なら `record_invalid`（収束を名乗らない）。4.9・11.3・10.1 の 14。
- **I6**（判定 v2 の盤面の開き方）: `state.works.line` から表を引き、表の sha を突き合わせ、`board_hook.py` が在れば読む形にした（線 A の `entry.open_board` と同じ決まり）。違う表は `BoardMismatch`（4.3・10.1 の 12）。
- **I7**（線 A との並べ方）: 5 節の「着手の順」を 4 段にした（線 A の T2 と TA18 の後に線 A の枝の先から切る・T4 の前に TA18 を確かめる・v2 の後に線 A の 1 周の試験を回し直す・ラインは線 A の T17 の後）。
- **m1**: P17 と P6e に確かめる物を足した（10.2）。**m2**: 土台への申し送り（差し替え無しで開いたら `BoardGap`）を 5 節に分けて書いた。**m3**: 止めた周にも `abandon_unrun_lanes`、薄い関数の一覧に `_write_round_note`・`STOPPED_BY`・`report_accepts`（4.5・8 節）。**m4**: `p2.human_gate` への `rejudge` は `answer: "rejudge"` の行（4.4）。**m5**: 後からの突き合わせは `gates_cut.rev` の木と記録の `tree` だけで比べる（4.7）。**m7**: 締めた周も上限と 3 周の数に入る（4.4・11.3）。**m8**: `entry.take(board_dir, nid, reply, repo)` の引数（2.2）。**m9**: engine の問いと一時停止が重なった回（2.3）。**m10**: `start` が `test_cmd` を控え、線 A の名前（`entry.local_checks_material`・`entry.run_ci`）に揃えた（4.1・5 節）。**m6** は計画の側（手掛かりの無い Step 3）。
- **線 A の改訂 2 に揃えた所**: blk-tests は `mode: final` を明示で渡す（既定の `plain` は 1 本目と mutgate の約束のまま）。`start` は `entry.run_ci` を使う。報告の部品は `head_*` と `gate_record`、結末の語に `stopped_by_line`・`record_invalid`・`interrupted` を足して線 A と揃えた。役の出力と作業ファイルは周の番号を決め打ちにせず `state.outputs[節]["file"]`・`b.work` から引く。各 script の `INPUTS` の定数を YAML の `with:` と突き合わせる（線 A の TA16 と同じ縛り）。
- 持ち主に聞く物は増えていない（12 節の 1 の `p2.rejudge` は仮の扱い absent のまま）。

## 改訂 6（持ち主の答え 2026-09-27）

朝の 4 つの答え（〔答〕）と、回す側の指示（本線の調べ 作業の控え（scratchpad）の `mainline-blocks-survey.md` と本線からの知らせ）を入れた。計画の側の直しは計画の同じ名の節。線 A の仕様と計画の「改訂（持ち主の答え 2026-09-27）」の口に揃えた。

- **1. 軽量は案 1（下げない）**: 1.3。線 B は手厚さの入力を持たないまま。変わる所は無い。
- **2. 並行 PR は案 (a)**: 1.3・3.1・4.12・11。`p0.parallel_pr` を線 A と同じ行（`engine_run`・`fallback: role`）にし、`open` が線 A の `prcheck.run_helper` で engine の 1〜5 段を走らせ、任せ先に落ちた周だけ線 A の `blk-pr`（読むだけの opus・申し送りは下書き）を回す。投稿しないことは `darkfactory-rounds/downgrades.json` と報告の冒頭 ② と 11.4 に出す。4 版の「並行 PR の語を表の 1 行の外に置かない」縛りを外した。
- **3. 前提と目的**: 1.3・4.10・4.12。前提は線 A の `blk-premises` を周の頭で使い（1 周目だけ）、目的の文は線 B の新しいブロック `blk-purpose` で足す。判定役の入口に `premises_file`（線 A が足す）と `purpose_file`（線 B が足す）。目的の審査 `p0.purpose_review` と前の決定の掘り起こし `p0.prior_decisions` は absent のまま（11.2）。
- **4. 同じ周の再審は上位互換**: 1.3・2.3・4.3・4.11・11。線 A の包みが判定役の会話を継ぐ（〔継試〕。輪の中でも動いた）。判定 v2 の判定役に印 `works-node: judge` を残し、包みが内の輪の 1 回目は自分で作った id、2 回目は SDK の id を記録する。会話の id が無い周は一時停止 `rejudge_no_session`（`continue` は `b.skip("p2.rejudge")` で飛ばして異議を次の周へ・`rejudge` は `close_early`・`stop`）。12 節の 1 を決まったにした。
- **回す側の指示**: 再審の形は本線の 3-6（再審 3 回・修正役の再異議 2 回・第三の目）にし、写し直しの後に入れる（4.11。0.21.0 の形は第三の目が立たない穴がある）。写し直しは本線の 3-5・3-6 が版に入ってから 1 回で、その時に要る物は計画の「写し直しへの依存」（1.5）。受け付けの口は本線の 3-8 まで `accept.py` のままで検査を足さず、線 B の受け付けは線 B のモジュールとブロックのスクリプトに置き、線 A の `gl` への対応表に線 B の行を足す（1.5）。ブロックの名前と `where` は works の仮の名で作り、本線の 3-7 の後に揃える（1.5）。止める猶予は works の 2 秒のまま。
- **ラインの形**（2.1・2.2・4.2）: 周の頭に `pr-checking`・`h-pre`・`premising`・`h-purpose`・`purposing`・`h-judge` を、修正の後に `h-rejudge`・`rejudging`（写し直しの後）を足した。`open` は並行 PR の境、包みの確かめは `h-plan` から `h-judge`（前提の役の後・判定の前）へ移した（線 A の TA9 と同じ）。境の節の返りに `premises_file`・`purpose_file` を足した。
- **能力の差**（11 節）: 再審は写し直しの後に上（それまでは宣言）・前提は同〜上・目的の文は同・並行 PR の交差の検査は同、申し送りを投稿しない所だけ下（11.4）。
- **試験**（10 節）: 単体の 15〜17、P17 の形、筋書きの道を足した。今壊れている物は無いまま。
