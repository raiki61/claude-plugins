# research-loop の P1（校正——外部照合）

目次（この段は 1 つのセクションで、中の太字の段落の順）:

- P1: 校正 ── 外部照合（checker → refuter。**系統的レビュー＋ファクトチェック**の段）（中の太字の段落は、下の順）
- 武器の使い分け（閉じた主張だけを検証する）
- Workflow に渡す script の全文（claim-audit）
- 固定の判定語彙と出典の格
- 件数突合・再ラウンドの経済・高価な相違の増し掛け
- 負荷確証の反証探索・生存者バイアスの点検・雪だるま式追跡

## P1: 校正 ── 外部照合（checker → refuter。**系統的レビュー＋ファクトチェック**の段）

**武器の使い分け**: P1 は「閉じた主張の検証」専用。**開いた問い**（地図がまだ無い・選択肢の洗い出し・領域全体の調査）はここで解けない ── 既存の deep-research（多角検索→取得→敵対検証→統合）に委譲しろ。再実装するな。deep-research が持ち帰った事実主張を文書に採るときは、次ラウンドの P1 の検証対象に入れろ。

P0 で作ったクラスタを args に載せ、**下記スクリプト全文を Workflow の script に、{clusters: [{key, claims}]} を args に渡して起動しろ**。ワークフローが使えない状況なら、同じ構造（checker=`investigator` → 相違と【荷重】確証に refuter=`judge`・同じ判定語彙と schema）を Agent の並列起動で再現しろ。

```js
export const meta = {
  name: 'claim-audit',
  description: '主張クラスタを一次情報で監査し、相違の再検証と荷重確証への反証を敵対検証で行う（research-loop P1）',
  phases: [
    { title: 'Fact-check', detail: 'クラスタ並列・一次ソース突合（investigator）' },
    { title: 'Verify', detail: '相違の再検証＋【荷重】確証への反証（judge）' },
  ],
}

// harness によっては args が JSON 文字列のまま届くことがある（実走で確認済み）ため両対応
const input = typeof args === 'string' ? JSON.parse(args) : args
if (!input || !Array.isArray(input.clusters) || !input.clusters.length) {
  throw new Error('args.clusters が必要: [{key: string, claims: string}] の配列')
}

const FINDINGS = {
  type: 'object',
  additionalProperties: false,
  required: ['cluster', 'findings'],
  properties: {
    cluster: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['claim', 'verdict', 'evidence', 'sources'],
        properties: {
          claim: { type: 'string', description: '検証対象の主張（要約可）' },
          verdict: { type: 'string', enum: ['confirmed', 'contradicted', 'qualified', 'unverifiable'], description: 'キーで返す。confirmed=確証・contradicted=相違・qualified=留保・unverifiable=検証不能' },
          evidence: { type: 'string', description: '一次情報で確認した内容' },
          sources: { type: 'array', items: { type: 'string' }, description: '出典 URL' },
          conditions: { type: 'string', description: '確証の場合: この主張が成立する適用条件・限界（必須で書く）' },
          loadBearing: { type: 'boolean', description: '主張に【荷重】印が付いていた場合 true' },
          correction: { type: 'string', description: '相違/留保の場合: 文書に書くべき正しい記述' },
        },
      },
    },
  },
}

const VERDICT = {
  type: 'object',
  additionalProperties: false,
  required: ['isRealDiscrepancy', 'reasoning'],
  properties: {
    isRealDiscrepancy: { type: 'boolean' },
    reasoning: { type: 'string' },
    correctedStatement: { type: 'string', description: '真の相違の場合: 文書へ書くべき正しい記述の確定版' },
  },
}

const COMMON = [
  'あなたは設計文書のファクトチェッカー。ウェブ検索と取得で必ず一次情報（公式ドキュメント・標準文書・原典・公式リポジトリ）に当たり、以下の各主張を検証しろ。',
  'ファイルの作成・編集・削除を自らに禁じる。Bash は読み取りにだけ使え。',
  '判定基準（verdict はキーで返す）: confirmed（確証）=一次情報が主張どおり（conditions に適用条件・限界を必ず書く。適用条件のない確証は不完全）／contradicted（相違）=一次情報と食い違う（correction に正しい記述を書く）／qualified（留保）=概ね正しいが重要な限定・精密化が要る（correction に限定を書く）／unverifiable（検証不能）=一次情報に到達できない。',
  '引用は文脈込みで当たれ: 切り出す一文の前後、その文書自身の問い・対象・条件・限定節（limitations）を確認し、主張への転用が原文の射程内かを判定しろ。都合のよい断片だけの切り出し（文脈剥ぎ取り引用）を禁ずる。evidence と conditions には原文の射程（誰が・何を対象に・どの条件で言っているか）を書け。',
  '重要: 主張を好意的に読み替えるな。書かれた文言がそのまま正しいかを判定しろ。二次ブログしか根拠が見つからないなら verdict を下げろ。数値・年号・固有名詞は特に厳密に。クラスタ内の全主張に1件ずつ必ず判定を返せ（検証不能も明示しろ・無言の省略を禁ずる）。主張に【荷重】印が付いていたら loadBearing=true を返せ。sources は URL。全て日本語で書け。',
].join('\n')

phase('Fact-check')
const results = await pipeline(
  input.clusters,
  c => agent(COMMON + '\n\n【クラスタ: ' + c.key + '】\n' + c.claims, {
    label: 'fact:' + c.key,
    phase: 'Fact-check',
    // モデル・effort・道具は agents/investigator.md が正本（ここに model を書くな）
    agentType: 'convergence-loops:investigator',
    schema: FINDINGS,
  }),
  (res, c) => {
    if (!res) return null
    const disputed = res.findings.filter(f => f.verdict === 'contradicted')
    const loaded = res.findings.filter(f => f.verdict === 'confirmed' && f.loadBearing)
    if (!disputed.length && !loaded.length) return res
    const refute = (f, mode) => () =>
      agent([
        mode === 'dispute'
          ? 'あなたは敵対的検証者。あるファクトチェッカーが次の主張を「相違（一次情報と食い違う）」と判定した。この判定自体が誤検出でないか、自分で一次情報をウェブ検索・取得して再検証しろ。'
          : 'あなたは敵対的検証者。次の主張はチェッカーが「確証」と判定したが、結論が乗る【荷重】主張なので反証を試みろ。一次情報を自分で検索・取得し、この確証を崩す証拠（反例・より新しい一次情報・原文の射程の限定）を本気で探せ。見つからなければ isRealDiscrepancy=false を返せ。',
        '誤検出・見落としの典型: 読み違い／古い情報／留保の見落とし／別エディション・別バージョンの混同／引用の文脈剥ぎ取り（原文の射程外への転用 ── チェッカー側と主張側の双方を疑え）。',
        '元の主張: ' + f.claim,
        'チェッカーの根拠: ' + f.evidence,
        'チェッカーの出典: ' + f.sources.join(' / '),
        'チェッカーの訂正案: ' + (f.correction || 'なし'),
        '実質的な問題が見つかったら isRealDiscrepancy=true とし、correctedStatement に文書へ書くべき正しい記述を書け。日本語で。',
      ].join('\n'), { label: 'verify:' + c.key, phase: 'Verify', agentType: 'convergence-loops:judge', schema: VERDICT })
        .then(v => Object.assign({}, f, { verified: v }))
    return parallel([
      ...disputed.map(f => refute(f, 'dispute')),
      ...loaded.map(f => refute(f, 'confirm')),
    ]).then(vs => Object.assign({}, res, { verifiedFindings: vs.filter(Boolean) }))
  }
)
log('全クラスタ完了')
return results.filter(Boolean)
```

固定の判定語彙（変えるな・増やすな）:

- **確証** = 一次情報が主張どおり（＋適用条件を添える）
- **相違** = 一次情報と食い違う（正しい記述を添える）→ **refuter の敵対検証を経て初めて確定**
- **留保** = 概ね正しいが重要な限定・精密化が要る
- **検証不能** = 一次情報に到達できない（二次情報しか無い場合はここに落とすか格を下げる）

出典の格（**GRADE 流のエビデンス階層**・強い順）: 国際標準・法規 ＞ 査読論文 ＞ ベンダー/プロジェクト公式一次 ＞ コミュニティ標準 ＞ 実務二次（ブログ・ベンチ記事） ＞ 匿名・出典不明。**判定の根拠にできるのはベンダー公式一次まで**。実務二次は「複数が独立に一致」した場合のみ solid 扱い、匿名は参考止まり。

**件数突合（無言の省略を「なし」と誤認するな）**: 照合は実行記録の検証器が行う——記録のクラスタフィールドに入れた主張数を書き、判定数との等式は `${CLAUDE_PLUGIN_ROOT}/scripts/research-record.py` が検査する。**記録は最終報告のためだけの物ではない——クラスタフィールドと claims を書いた時点で検証器を回せ**（記録は途中で何度書き直してもよい）。欠けていたら当該クラスタだけ再実行してから P2 に入れ。

**再ラウンドの経済**: 2ラウンド目以降は「新規の主張」と「訂正の波及で前提が変わった主張」だけを P1 にかけろ。確定済みの確証・確定済みの相違を引き直すな ── 全量の引き直しは純粋な無駄で、精度も上がらない。

**高価な相違の増し掛け**: 反映すると結論の芯を書き換える相違は、refuter を独立3票（観点を変えて）に増やし 2/3 で確定させてよい。既定は1票 ── refuter の誤りは P3 と収束ラウンドが後段で捕まえるので、全件3票は過剰。

**負荷確証の反証探索**: refuter を相違だけに走らせるな ── **結論が乗っている確証**（これが崩れると本文の芯が崩れるもの）にも回せ。検証者の甘い確認（確証バイアス・出版バイアスの同族）は、相違より静かに生き残る。全確証に回すのは過剰、荷重で選べ ── 選定は P0-3 の**【荷重】印**で行い（スクリプトが同じ並列扇の中で自動実行・後追いの往復を作るな）、**どの主張に印を付けたか（0件ならその旨と理由）を最終報告に明示しろ**。選定ゼロで素通りする降格を禁ずる。

**生存者バイアスの点検**: 「業界に無い＝空白」と結論する前に、**死んだ試み**（廃止された製品・撤回された機能・クローズした議論）を探せ。空白が「誰もやっていない」でなく「やって死んだ」なら意味が逆転する ── 帰還した爆撃機の弾痕だけ見るな（Wald）。

**雪だるま式追跡**: 当たった一次情報の参考文献（後方）と被引用（前方）を1段だけ辿れ ── 主張単位の検索では届かない隣の一次情報が安く手に入る（系統的レビューの標準手技）。
