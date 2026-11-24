// attention/workflows/my-turn-dig.js を、agent() などを偽物に替えて node で空回しする（設計 attention/docs/my-turn-workflow-design.md の 11）。
// 使い方: node tests/my-turn-dig-dry.mjs <case>   case は fixed・grow・same・skips・allot・map・schema・rests・dedup・quotes・prompts・refute・purpose・eyes・redig・ledger・lines・fixes。通れば <CASE>_OK を出す。
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SCRIPT = path.join(ROOT, 'attention/workflows/my-turn-dig.js')
// Windows の clone（core.autocrlf=true）では script が CRLF で出る。行で読む検査（allot の取り出し・prompts の区画）が
// LF を前提にするので、読んだ時に LF へそろえる（run 44027416895 の windows の赤: 「allot: script に allot が無い」）
const SRC = fs.readFileSync(SCRIPT, 'utf8').replace(/\r\n/g, '\n')
const BODY = SRC.replace(/^export const meta\s*=/m, 'const meta =')
const AsyncFunction = (async () => {}).constructor
const fails = []
const check = (ok, what) => { if (!ok) fails.push(what) }

// ---- 偽物 ----
function schemaProblems(schema, where = 'schema') {
  const out = []
  if (!schema || typeof schema !== 'object') return out
  if (schema.type === 'object') {
    const props = schema.properties ?? {}
    for (const r of schema.required ?? []) if (!(r in props)) out.push(`${where}: required の ${r} が properties に無い`)
    for (const [k, v] of Object.entries(props)) out.push(...schemaProblems(v, `${where}.${k}`))
  }
  if (schema.type === 'array') out.push(...schemaProblems(schema.items, `${where}[]`))
  return out
}
async function run(args, respond) {
  const calls = [], logs = []
  const agent = async (prompt, opts = {}) => {
    const call = { prompt, opts, label: opts.label ?? '' }
    calls.push(call)
    const bad = schemaProblems(opts.schema)
    if (bad.length) throw new Error(bad.join('; '))
    return respond(call, calls)
  }
  const parallel = thunks => Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
  const pipeline = async (items, ...stages) => Promise.all(items.map(async (it, i) => {
    let v = it
    try { for (const s of stages) v = await s(v, it, i) } catch { return null }
    return v
  }))
  const fn = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', BODY)
  const out = await fn(agent, parallel, pipeline, () => {}, m => logs.push(String(m)), args, { total: null, spent: () => 0, remaining: () => Infinity },
    async () => { throw new Error('workflow() is not used') })
  return { out, calls, logs }
}

const HEAD = 'h'.repeat(40)
const baseArgs = (extra = {}) => ({
  caller: 'attention:my-turn-deep',
  pr: 7, repo: 'o/r', workdir: '/w', stance: 'reviewer', now: '2026-11-17T00:00:00Z',
  prep: { base: 'b'.repeat(40), head: HEAD, base7: 'bbbbbbb', diff: '/rd/bbbbbbb..hhhhhhh.diff', recordDir: '/rd',
    commits: ['c'.repeat(40)], changed: ['a.py', 'CLAUDE.md'], excluded: [], claudeMdChanged: true,
    rules: [{ path: 'CLAUDE.md', show: 'git show bbbbbbb:CLAUDE.md' }], fingerprints: {},
    quoteCheck: { runPython: '/p/run-python.sh', prep: '/p/my-turn-prep.py' } },
  files: { record: '/rd/7.json', thread: '/rd/7-thread.md', justifications: '/rd/7-just.md' },
  blindJudge: 'convergence-loops:blind-judge',
  ...extra,
})
const ROLE_KEYS = ['Purpose', 'W1', 'W2', 'W3', 'W4', 'W6', 'Redig', 'W7', 'W8', 'Lines', 'W9', 'W10answers', 'W10fixes', 'Quotes']
const ROLES = Object.fromEntries(ROLE_KEYS.map(k => [k, `my-turn-${k}`]))

const nodeId = p => (p.match(/## Your node (N\d+)/) ?? [])[1]
const nodeQ = p => p.split('hand to children only questions whose answer would change yours):\n')[1] ?? ''
// a leaf says "fix" a breakage at its own line (a.py:<node number>), so findings of different leaves do not fold
const leaf = (id, extra = {}) => ({ answer: `ANSWER-${id}`, files: ['a.py'], urls: [],
  evidence: [{ path: 'a.py', line: 1, quote: 'x' }], parts: [], premises: [`PREMISE-${id}`], status: 'leaf', children: [],
  worth: 'fix', findingKind: 'breakage', locations: [{ path: 'a.py', line: Number(String(id).slice(1)) || 1, quote: 'x' }], cost: '', finePremise: '',
  ...extra })
const child = (q, weight = 'big') => ({ question: q, howParentChanges: 'flips it', weight, where: 'a.py' })
const split = (id, qs, weight) => leaf(id, { status: 'split', evidence: [], children: qs.map(q => child(q, weight)) })
const byText = items => ({ clusters: Object.values(items.reduce((m, [id, q]) => { (m[q] ??= { key: q, question: q, ids: [] }).ids.push(id); return m }, {}))
  .map(c => ({ key: c.key, question: c.question, members: c.ids.join(', ') })), dropped: [] })
const w7Items = p => [...p.matchAll(/^- (q\d+): (.*?) \| /gm)].map(m => [m[1], m[2]])
const idOf = (items, text) => items.find(([, t]) => t === text)?.[0]
// the command line of a quote-check prompt, and its words: the header, then <id>:<base64 of [id, path, line, quote, sum]>
const quoteLine = p => p.split('\n').find(l => l.startsWith('bash ') && l.includes(' --quotes --b64 ')) ?? ''
const unb64 = w => Buffer.from(w, 'base64').toString('utf8')
const quoteItems = p => quoteLine(p).split(' ').filter(w => /^Q\d+:/.test(w)).map(w => {
  const [id, b] = w.split(':'), item = JSON.parse(unb64(b))
  if (item[0] !== id) throw new Error(`the word's id ${id} is not its line's ${item[0]}`)
  return item
})
const quotesOk = call => ({ ran: true, checked: quoteItems(call.prompt).length, missing: [], garbled: [], error: '' })

// 既定の答え。over[stage] で替える
function responder(over = {}) {
  const w8 = { n: 0 }
  return (call, calls) => {
    const { label, prompt } = call
    const stage = label.split(' ')[0]
    if (over[label]) return over[label](call, calls)
    if (over[stage]) return over[stage](call, calls, w8)
    switch (stage) {
      case 'Purpose': return { purpose: 'keep the records consistent', means: ['a hand-made checker in a.py'], kind: 'a kind of system',
        claims: [{ claim: 'no tool does this', at: 'a.py:1' }] }
      case 'W1': return { structure: 'parts A and B', standards: [], mechanisms: [{ mechanism: 'M1', premise: 'P1' }],
        selfMade: [{ part: 'checker', files: 'a.py', why: 'hand list' }], extraSmells: [], hiddenChoices: ['Where is the truth?'],
        noParts: false, noPartsReason: '' }
      case 'W2': return { general: 'GENERAL', notFound: false, questionStands: true, whyQuestion: 'it needs a store',
        design: [{ id: 'D1', element: 'one store', adds: 'a store', removes: 'the checker' }] }
      case 'W3': return { comparable: true, whyNotComparable: '', diffs: [{ diff: 'D', decision: 'align', basis: 'industry', ifThreeMore: '', from: 'structure' }] }
      case 'W4': return { verdict: label === 'W4 smell 1' ? 'smell' : 'none', answer: 'A', evidence: [{ path: 'a.py', line: 2, quote: label === 'W4 smell 1' ? 'y' : '' }],
        findingKind: label === 'W4 smell 1' ? 'breakage' : 'none', locations: [], cost: '' }
      case 'W6': case 'Redig': return leaf(nodeId(prompt))
      case 'W7': return byText(w7Items(prompt))
      case 'W8': return { gaps: [], reason: 'compared against the structure' }
      case 'Lines': return { items: [...prompt.matchAll(/^- (L\d+) \[/gm)].map(m => ({ id: m[1], label: 'one finding', level: 'design', route: 'report', into: '', why: 'w', rule: '' })) }
      case 'W9': {
        const ids = [...prompt.matchAll(/^- (L\d+) \[/gm)].map(m => m[1])
        return { fixes: [{ fix: 'F', rung: 'remove', worldSolution: 'https://example.org', items: ids.join(',') }], groups: [], searched: 'words', outside: [] }
      }
      case 'W10': return { verdict: 'stands', reason: 'r', evidence: [{ path: 'a.py', line: 1, quote: 'x' }],
        ...(label.endsWith(' trace') ? { problem: true, scenario: 'input a, then wrong b', cost: '' } : {}),
        ...(label.endsWith(' cost') ? { problem: true, scenario: '', cost: 'two files to keep in step' } : {}),
        ...(/^W10 G\d+$/.test(label) ? { members: [] } : {}) }
      case 'Quotes': return quotesOk(call)
    }
    throw new Error(`unknown label ${label}`)
  }
}
const of = (calls, stage) => calls.filter(c => c.label.split(' ')[0] === stage)
// the ledger item a node went into (stage 11), and whether its first refuter was asked (stage 12)
const itemOf = (out, id) => out.ledger?.find(it => it.from.includes(id))
const refuted = (calls, out, id) => { const it = itemOf(out, id); return !!it && calls.some(c => c.label === `W10 ${it.id}`) }

// ---- 1. 決まった答え ----
async function caseFixed() {
  // 2 本のルート（前提を消す・寄せる違い）が同じ子を返し、その子が深さ 3 まで分かれる。W8 は 1 回目に新しい抜けと既に在る問いを返す
  const tree = (call) => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (q.startsWith('[s11.2]') || q.startsWith("The PR's structure differs")) return split(id, ['D1 shared'])
    if (q === 'D1 shared') return split(id, ['D2 deep'])
    if (q === 'D2 deep') return split(id, ['D3 deep'])
    return leaf(id)
  }
  const W8 = (call, calls, s) => (++s.n === 1 ? { gaps: [{ question: 'GAP new', why: 'w', where: 'b.py' }, { question: 'D2 deep', why: 'w', where: '' }], reason: '' }
    : { gaps: [], reason: 'nothing more' })
  const extraSmells = ['E1', 'E2', 'E3', 'E4'].map(q => ({ question: q, whyNotCovered: 'w' }))
  const W1 = call => ({ ...responder()(call), extraSmells })
  const { out, calls } = await run(baseArgs(), responder({ W6: tree, W8, W1 }))
  check(!out.stopped, `fixed: 止まった ${JSON.stringify(out.stopped)}`)
  // 台本は記録をそのまま返し、ファイルは書かない（書くのは会話か my-turn-headless.py）
  check(out.version === 3 && !('recordPath' in out) && !('recordWritten' in out) && !('recordModel' in out), 'fixed: 返りが記録の形でない')
  // 段ごとに渡したモデルを数えに残す（ヘッドレスの形の台本が、使われなかったモデルを回った段だけで数える）
  check(JSON.stringify(out.counts.stages.W6.models) === '["sonnet"]' && JSON.stringify(out.counts.stages.W1.models) === '["opus"]'
    && JSON.stringify(out.counts.stages.Quotes.models) === '["haiku"]', `fixed: 段のモデルが数えに無い ${JSON.stringify(out.counts.stages.W6)}`)
  // W4: 固定の 5 問と、足した 4 問のうち上限 3 問と、いつも立つ 6 つの目（身元の印が無く、標準が 2 つ未満なので privilege と standards は立たない）
  check(of(calls, 'W4').length === 14, `fixed: W4 の体数 ${of(calls, 'W4').length}（5+3+6 のはず）`)
  check(['rules', 'prior', 'minimal', 'hygiene', 'ratio', 'tests'].every(e => calls.some(c => c.label === `W4 eye ${e}`))
    && !calls.some(c => c.label === 'W4 eye privilege' || c.label === 'W4 eye standards'), 'fixed: 目の立ち方が違う')
  check(out.counts.notSeen.extraSmellsCut.length === 1, 'fixed: 上限を越えた臭いの問いが未確認で返らない')
  // 深さ 3 のノードに、2 本の道の全部の祖先の問い・答え・前提が載る
  const d3 = out.nodes.find(n => n.question === 'D3 deep')
  check(d3 && d3.depth === 3, 'fixed: 深さ 3 のノードが無い')
  const d3call = of(calls, 'W6').find(c => nodeQ(c.prompt) === 'D3 deep')
  const anc = new Set(), stack = [...(d3?.parents ?? [])]
  while (stack.length) { const id = stack.pop(); if (anc.has(id)) continue; anc.add(id); stack.push(...out.nodes.find(n => n.id === id).parents) }
  check(anc.size === 4, `fixed: 深さ 3 の祖先の数 ${anc.size}（2 本のルート + D1 + D2）`)
  for (const id of anc) check(d3call?.prompt.includes(`ANSWER-${id}`) && d3call.prompt.includes(`PREMISE-${id}`), `fixed: 深さ 3 の指示に ${id} の答えか前提が無い`)
  check(d3call?.prompt.includes('Path 2:'), 'fixed: 親を 2 つ持つ道の 2 本目が載らない')
  // 「直す」と言った末端は 1 件ずつ台帳の項目になり（在り処が違うので畳まない）、W9 と W10 に欠けずに渡る
  const leaves = out.nodes.filter(n => n.status === 'leaf')
  const w9 = of(calls, 'W9')[0]
  const itemOfNode = id => out.ledger.find(it => it.from.includes(id))
  check(leaves.length > 0 && leaves.every(n => itemOfNode(n.id)?.from.length === 1), 'fixed: 末端が台帳の項目に 1 件ずつならない')
  for (const n of leaves) { const it = itemOfNode(n.id); check(it && w9.prompt.includes(`- ${it.id} [breakage]: `) && w9.prompt.includes(`ANSWER-${n.id}`), `fixed: W9 に ${n.id} が渡らない`) }
  for (const n of leaves) { const it = itemOfNode(n.id); check(it && calls.some(c => c.label === `W10 ${it.id}`) && calls.some(c => c.label === `W10 ${it.id} trace`), `fixed: ${n.id} の反証が立たない`) }
  check(of(calls, 'W10').filter(c => /^W10 S\d+$/.test(c.label)).length === 14, 'fixed: 臭いの答えの反証が 14 体でない')
  check(of(calls, 'Lines').length === 1 && out.ledger.every(it => it.route === 'report') && out.linesReturned, 'fixed: 線引きの段の返りが台帳に載らない')
  check(calls.some(c => c.label === 'W10 F1'), 'fixed: 直しの案の反証が立たない')
  check(out.nodes.every(n => n.status !== 'pending'), 'fixed: 記録に掘り終えていないノードが残る')
  // 写しの照合: 1 体が prep の --quotes を打ち、根拠を 1 件ずつ印付きの行の base64 の語で渡す。全部の段が読むだけの決まりを持つ
  const qp = of(calls, 'Quotes')
  const items = qp.flatMap(c => quoteItems(c.prompt))
  // 1 行（here-document はヘッドレスの許しの規則に当たらず拒まれた）。頭の語は base64 の {workdir, base, head, recordDir}
  const qWords = quoteLine(qp[0]?.prompt ?? '').split(' ')
  check(qp.length === 1 && quoteLine(qp[0].prompt).startsWith('bash /p/run-python.sh /p/my-turn-prep.py --quotes --b64 ')
    && !qp[0].prompt.includes('<<') && unb64(qWords[5] ?? '').startsWith('{"workdir":"/w","base":"' + 'b'.repeat(40))
    && qWords.length === 6 + items.length,
    'fixed: 写しの照合のコマンドの形が違う')
  check(items.length > 0 && items.every(x => x.length === 5 && /^[0-9a-f]{8}$/.test(x[4])) && /^[\x00-\x7f]*$/.test(qp[0].prompt.split('```bash')[1]),
    `fixed: 写しの照合の行の形が違う ${JSON.stringify(items.slice(0, 2))}`)
  check(out.counts.quotes.checked === items.length && out.counts.quotes.items === items.length && !out.counts.quotes.dropped.length,
    `fixed: 写しの照合の件数が違う ${JSON.stringify(out.counts.quotes)}`)
  check(calls.filter(c => !c.label.startsWith('W2')).every(c => c.prompt.includes('- Read only.')), 'fixed: 読むだけの決まりの無い段が在る')
  // W8: 新しい抜けは区分 8 のルートになり、既に在る問いは seen で落ちる。2 回続けて空で止まる
  const gap = out.nodes.find(n => n.question === 'GAP new')
  check(gap && gap.rootClass === 8 && gap.parents.length === 0, 'fixed: W8 の抜けが区分 8 のルートにならない')
  check(out.gapRounds.length === 3, `fixed: W8 の回数 ${out.gapRounds.length}（抜け 1 回 + 空 2 回）`)
  const outcomes = out.gapRounds[0].gaps.map(g => g.outcome).sort().join(',')
  check(outcomes === 'dug,seen', `fixed: W8 の抜けの行き先 ${outcomes}`)
  check(out.nodes.filter(n => n.question === 'D2 deep').length === 1, 'fixed: seen に在る問いがもう一度掘られた')
  // 段のモデル・既定の形（roles 無し）・CLAUDE.md の書き足し・W2 に PR を渡さない
  const model = s => of(calls, s)[0]?.opts.model
  check(model('W1') === 'opus' && model('W6') === 'sonnet' && model('Quotes') === 'haiku' && model('W4') === 'sonnet', 'fixed: 段のモデルが表と違う')
  check(calls.filter(c => !c.label.startsWith('W2')).every(c => !c.opts.agentType), 'fixed: roles が無いのに agentType が付いた')
  check(of(calls, 'W2')[0].opts.agentType === 'convergence-loops:blind-judge', 'fixed: W2 が blindJudge で立たない')
  check(of(calls, 'W1')[0].prompt.includes('The CLAUDE.md files loaded into you'), 'fixed: PR が CLAUDE.md を変えたのに書き足しが無い')
  const w2 = of(calls, 'W2')[0].prompt
  check(!w2.includes('Shared rules') && !w2.includes('o/r') && !w2.includes('#7') && !w2.includes('a.py'), 'fixed: W2 に PR か決まりが渡った')
  // 件数
  const st = out.counts.stages
  check(st.W6.started === of(calls, 'W6').length && st.W6.returned === st.W6.started && st.W6.null.length === 0, 'fixed: W6 の件数が合わない')
  check(Object.values(st).every(e => e.empty.length === 0), `fixed: 空のフィールドが数えられた ${JSON.stringify(Object.fromEntries(Object.entries(st).map(([k, e]) => [k, e.empty])))}`)

  // roles が在る: 全部の段が agentType 付きで立ち、W2 は roles.W2 が勝ち、CLAUDE.md の書き足しは入らない
  {
    const { out: o2, calls: c2 } = await run(baseArgs({ roles: ROLES }), responder({ W6: tree, W8, W1 }))
    check(!o2.stopped, 'fixed/roles: 止まった')
    check(c2.every(c => c.opts.agentType && c.opts.agentType.startsWith('my-turn-')), 'fixed/roles: agentType の無い段が在る')
    check(of(c2, 'W2')[0].opts.agentType === 'my-turn-W2', 'fixed/roles: W2 で roles.W2 が blindJudge に勝たない')
    check(of(c2, 'W10').some(c => c.opts.agentType === 'my-turn-W10fixes') && of(c2, 'W10').some(c => c.opts.agentType === 'my-turn-W10answers'), 'fixed/roles: 反証の役が分かれない')
    check(!of(c2, 'W1')[0].prompt.includes('The CLAUDE.md files loaded into you'), 'fixed/roles: roles が在るのに書き足しが入った')
  }
  // 起動の合図（caller）が無い・違う: /attention:my-turn-deep 以外からの起動なので、1 体も立てずに止まり、訳を 1 行で返す（頼み 839571）
  {
    const noCaller = baseArgs(); delete noCaller.caller
    for (const [what, a] of [['合図の無い起動', noCaller], ['合図の値が違う起動', baseArgs({ caller: 'attention:my-turn' })],
      ['args の無い起動', undefined], ['文字列の args で合図の無い起動', JSON.stringify(noCaller)], ['文字列の null の args の起動', 'null']]) {
      const { out: oc, calls: cc } = await run(a, responder())
      check(oc?.stopped === 'caller' && cc.length === 0, `fixed/caller: ${what}で止まらないか、エージェントを立てた ${JSON.stringify(oc?.stopped)} ${cc.length}`)
      check(typeof oc?.message === 'string' && oc.message.length > 0 && !oc.message.includes('\n'), `fixed/caller: ${what}で返す訳が 1 行でない`)
    }
    // ヘッドレスの台本が渡す値と、Workflow が受ける値が同じ
    const py = fs.readFileSync(path.join(ROOT, 'attention/scripts/my-turn-headless.py'), 'utf8')
    const pyCaller = (py.match(/^CALLER = "([^"]*)"/m) ?? [])[1]
    const jsCaller = (SRC.match(/^const CALLER = '([^']*)'/m) ?? [])[1]
    check(jsCaller === 'attention:my-turn-deep' && pyCaller === jsCaller, `fixed/caller: 合図の値が台本と Workflow で違う ${pyCaller} ${jsCaller}`)
  }
  // 反証と書いた段が同じモデル: 1 体も立てずに止まる
  {
    const { out: o3, calls: c3 } = await run(baseArgs({ models: { W10answers: { model: 'sonnet' } } }), responder())
    check(o3.stopped && c3.length === 0, 'fixed/same-model: 反証が書いた段と同じモデルでも止まらない')
  }
  // W1 が null: その段だけで止まり、件数を返す
  {
    const { out: o5 } = await run(baseArgs(), responder({ W1: () => null }))
    check(o5.stopped === 'W1' && o5.counts.stages.W1.null.length === 1, 'fixed/W1-null: 止まり方が違う')
  }
  // 比べる相手にならない: 伏せた問いを足して同じ相手に 1 回だけ問い直す
  {
    let n = 0
    const W3 = () => (++n === 1 ? { comparable: false, whyNotComparable: 'generic', diffs: [] } : responder()({ label: 'W3 compare', prompt: '' }))
    const { out: o6, calls: c6 } = await run(baseArgs(), responder({ W3 }))
    check(of(c6, 'W2').length === 2 && of(c6, 'W2')[1].prompt.includes('Where is the truth?'), 'fixed/retry: W2 に伏せた問いで問い直さない')
    check(o6.general.askedAgain && !o6.general.notFound && o6.compare?.diffs?.length === 1, 'fixed/retry: 問い直しの結果が使われない')
  }
  // 一般的すぎて比べられず、問い直しは出なかった: 訳は notComparable のまま（notFound にしない）
  {
    let m = 0
    const W2 = () => (++m === 1 ? responder()({ label: 'W2 general', prompt: '' }) : { general: '', notFound: true })
    const { out: o9 } = await run(baseArgs(), responder({ W2, W3: () => ({ comparable: false, whyNotComparable: 'generic', diffs: [] }) }))
    check(o9.general.askedAgain && o9.general.notFound && o9.general.why === 'notComparable', `fixed/retry: 問い直しが出ない回の訳 ${o9.general.why}`)
  }
  // 前の回の base の印（<旧 base7>:path:行）の根拠も、その path を読んだに数える
  {
    const W6 = () => leaf('x', { files: ['a.py'], urls: [], evidence: [{ path: 'ddddddd:CLAUDE.md', line: 2, quote: 'q' }] })
    const { calls: cU } = await run(baseArgs(), responder({ W6 }))
    const unreadLine = (of(cU, 'W8')[0]?.prompt ?? '').split('\n').find(l => l.startsWith('Changed files no node')) ?? ''
    check(/\(none\)$/.test(unreadLine), `fixed/unread: 古い base の印の根拠を読んだに数えない ${unreadLine}`)
    // PR が消したファイル（head に無い）は、読めないので読んでいないに数えない。消していないファイルは数える
    const del = baseArgs()
    del.prep = { ...del.prep, changed: [...del.prep.changed, 'gone.py', 'kept.py'], fingerprints: { 'gone.py': 'gone', 'kept.py': 'moved' } }
    const { calls: cD } = await run(del, responder({ W6 }))
    const delLine = (of(cD, 'W8')[0]?.prompt ?? '').split('\n').find(l => l.startsWith('Changed files no node')) ?? ''
    check(!delLine.includes('gone.py') && delLine.includes('kept.py'), `fixed/unread: 消したファイルを読んでいないに数えた ${delLine}`)
  }
  // 2 回目の回: 同じ区分の中で、前の回の後に変わったファイルに触れるルートを先にする（path の語の一致で見る）
  {
    const W1two = () => ({ ...responder()({ label: 'W1 structure', prompt: '' }),
      selfMade: [{ part: 'P1', files: 'lib/b.py', why: 'w' }, { part: 'P2', files: 'app/[slug]/p.tsx', why: 'w' }, { part: 'P3', files: '[**/w/b.py**](u), x', why: 'w' }, { part: 'P4', files: '__init__.py', why: 'w' }, { part: 'P5', files: 'lib/c.py_', why: 'w' }, { part: 'P6', files: '[id].tsx', why: 'w' }, { part: 'P7', files: 'lib/c.py?、x', why: 'w' }, { part: 'P8', files: '（app/[slug]/p.tsx）を', why: 'w' }, { part: 'P9', files: 'lib/c.pyの', why: 'w' }] })
    const a = baseArgs()
    a.prep = { ...a.prep, priorHead: 'p'.repeat(40), fingerprints: { 'b.py': 'moved', 'a.py': 'moved', 'app/[slug]/p.tsx': 'moved', '__init__.py': 'moved', 'lib/c.py': 'moved', '[id].tsx': 'moved' } }
    const { out: oT } = await run(a, responder({ W1: W1two }))
    const self = oT.nodes.filter(n => n.depth === 0 && /^Self-made part/.test(n.question)).map(n => n.question.slice(16, 18))
    check(self.join(',') === 'P2,P3,P4,P6,P7,P8,P9,P1,P5', `fixed/order: 変わったファイルに触れるルートが先に来ない ${self}`)
  }
  // 使い回し: 読んだファイルの指紋が同じなら W6 と W2 を立てない。違えば立てる
  {
    const prior = { ...out, nodes: out.nodes }
    const same = baseArgs({ priorRecord: prior })
    same.prep = { ...same.prep, priorHead: 'p'.repeat(40), fingerprints: { 'a.py': 'same' } }
    const { out: o7, calls: c7 } = await run(same, responder({ W6: tree, W8, W1 }))
    check(of(c7, 'W6').length === 0 && of(c7, 'W2').length === 0, `fixed/reuse: 同じ指紋で W6 ${of(c7, 'W6').length} 体・W2 ${of(c7, 'W2').length} 体を立てた`)
    check(o7.nodes.filter(n => n.reused).length === o7.nodes.length, 'fixed/reuse: 使い回しの印が付かない')
    check(of(c7, 'W10').filter(c => /^W10 [LN]\d/.test(c.label)).length === 0, 'fixed/reuse: 使い回した末端の反証をやり直した')
    // 前の回に確かめられなかった判定（unverifiable）は持ち越さず、もう一度反証する
    const shaky = baseArgs({ priorRecord: { ...out, nodes: out.nodes.map(n => (n.verdict ? { ...n, verdict: { ...n.verdict, verdict: 'unverifiable' } } : n)) } })
    shaky.prep = same.prep
    const { calls: c7b } = await run(shaky, responder({ W6: tree, W8, W1 }))
    check(out.nodes.some(n => n.verdict) && of(c7b, 'W10').filter(c => /^W10 [LN]\d/.test(c.label)).length > 0, 'fixed/reuse: 確かめられなかった判定を持ち越した')
    const moved = baseArgs({ priorRecord: prior })
    moved.prep = { ...moved.prep, priorHead: 'p'.repeat(40), fingerprints: { 'a.py': 'moved' } }
    const { calls: c8 } = await run(moved, responder({ W6: tree, W8, W1 }))
    check(of(c8, 'W6').length > 0, 'fixed/reuse: 指紋が変わったのに W6 を立てない')
    const missing = baseArgs({ priorRecord: prior })
    missing.prep = { ...missing.prep, priorHead: 'p'.repeat(40), priorHeadMissing: true, fingerprints: { 'a.py': 'moved' } }
    const { calls: c9 } = await run(missing, responder({ W6: tree, W8, W1 }))
    check(of(c9, 'W6').length > 0 && of(c9, 'W2').length === 1, 'fixed/reuse: 前の回の head が無いのに使い回した')
    // 記録のフォルダの差分は数えず、thread（毎回書き直す）を読んだノードは使い回さない
    const withFile = f => ({ ...out, nodes: out.nodes.map(n => ({ ...n, files: [...(n.files ?? []), f] })) })
    // 差分を読んだノードは、差分の本文が前の回と同じとき（prep.diffSame）だけ使い回す
    const allSame = { 'a.py': 'same', 'CLAUDE.md': 'same' }
    const diffArgs = baseArgs({ priorRecord: withFile('/rd/bbbbbbb..ppppppp.diff') })
    diffArgs.prep = { ...same.prep, fingerprints: allSame, diffSame: true, priorRunDiff: 'bbbbbbb..ppppppp.diff' }
    const { calls: c10 } = await run(diffArgs, responder({ W6: tree, W8, W1 }))
    check(of(c10, 'W6').length === 0, 'fixed/reuse: 記録のフォルダの差分を読んだだけで使い回さなくなった')
    // 使い回したノードの差分のファイルは、今の回の 1 本目（本文が同じ）を指し直す。次の回でも使い回せるように
    const { out: o10 } = await run(diffArgs, responder({ W6: tree, W8, W1 }))
    check(o10.nodes.every(n => !(n.files ?? []).includes('/rd/bbbbbbb..ppppppp.diff'))
      && o10.nodes.some(n => (n.files ?? []).includes('/rd/bbbbbbb..hhhhhhh.diff')), 'fixed/reuse: 使い回したノードが前の回の差分のファイルを指したまま')
    // 根拠（evidence の path）に挙げた差分のファイルも、今の回の 1 本目を指し直す
    const withEv = (p, line = 0) => ({ ...out, nodes: out.nodes.map(n => ({ ...n, evidence: [...(n.evidence ?? []), { path: p, line, quote: 'q' }] })) })
    const hasEv = (o, p, line) => o.nodes.some(n => (n.evidence ?? []).some(e => e.path === p && e.line === line))
    const evDiff = baseArgs({ priorRecord: withEv('/rd/bbbbbbb..ppppppp.diff', 12) })
    evDiff.prep = diffArgs.prep
    const { out: o10h, calls: c10h } = await run(evDiff, responder({ W6: tree, W8, W1 }))
    check(of(c10h, 'W6').length === 0 && hasEv(o10h, '/rd/bbbbbbb..hhhhhhh.diff', 12) && !hasEv(o10h, '/rd/bbbbbbb..ppppppp.diff', 12), 'fixed/reuse: 根拠の差分の位置を指し直さない')
    // 行の無い在り処（差分のファイルだけ）も、files と同じく今の回の 1 本目を指し直す
    const evBare = baseArgs({ priorRecord: withEv('/rd/bbbbbbb..ppppppp.diff') })
    evBare.prep = diffArgs.prep
    const { out: o10l } = await run(evBare, responder({ W6: tree, W8, W1 }))
    check(hasEv(o10l, '/rd/bbbbbbb..hhhhhhh.diff', 0) && !hasEv(o10l, '/rd/bbbbbbb..ppppppp.diff', 0), 'fixed/reuse: 行の無い根拠の差分を指し直さない')
    // 記録のフォルダの path に $ が在っても（$1・$& は置き換えの印）、そのままの綴りで指し直す
    const dollar = baseArgs({ priorRecord: withEv('/r$1$&d/bbbbbbb..ppppppp.diff', 12) })
    dollar.prep = { ...diffArgs.prep, recordDir: '/r$1$&d', diff: '/r$1$&d/bbbbbbb..hhhhhhh.diff' }
    const { out: o10j } = await run(dollar, responder({ W6: tree, W8, W1 }))
    check(hasEv(o10j, '/r$1$&d/bbbbbbb..hhhhhhh.diff', 12), 'fixed/reuse: $ を含む path を指し直しで崩した')
    // 反証の根拠のファイルが変わった末端は、使い回しても判定を持ち越さず、もう一度反証する
    const vMoved = baseArgs({ priorRecord: { ...out, nodes: out.nodes.map(n => (n.verdict ? { ...n, verdict: { ...n.verdict, evidence: [{ path: 'b.py', line: 3, quote: 'q' }] } } : n)) } })
    vMoved.prep = { ...same.prep, fingerprints: { ...allSame, 'b.py': 'moved' } }
    const { calls: c10k } = await run(vMoved, responder({ W6: tree, W8, W1 }))
    check(of(c10k, 'W6').length === 0 && of(c10k, 'W10').filter(c => /^W10 [LN]\d/.test(c.label)).length > 0, 'fixed/reuse: 反証の根拠が変わったのに判定を持ち越した')
    // 根拠に挙げただけのファイル（files に無い）も読んだ物に数え、指紋が変われば使い回さない
    const evMoved = baseArgs({ priorRecord: withEv('b.py', 10) })
    evMoved.prep = { ...same.prep, fingerprints: { ...allSame, 'b.py': 'moved' } }
    const { calls: c10i } = await run(evMoved, responder({ W6: tree, W8, W1 }))
    check(of(c10i, 'W6').length > 0, 'fixed/reuse: 根拠に挙げたファイルが変わったのに使い回した')
    const diffMoved = baseArgs({ priorRecord: withFile('/rd/bbbbbbb..ppppppp.diff') })
    diffMoved.prep = { ...same.prep, fingerprints: allSame, diffSame: false }
    const { calls: c10b } = await run(diffMoved, responder({ W6: tree, W8, W1 }))
    check(of(c10b, 'W6').length > 0, 'fixed/reuse: 差分の本文が変わったのに、差分を読んだノードを使い回した')
    // 前の回の 2 本目の差分（その前の回の後に足された物）を読んだノードは、本文が同じでも使い回さない
    const second = baseArgs({ priorRecord: withFile('/rd/aaaaaaa..ppppppp.diff') })
    second.prep = diffArgs.prep
    const { calls: c10f } = await run(second, responder({ W6: tree, W8, W1 }))
    check(of(c10f, 'W6').length > 0, 'fixed/reuse: 前の回の 2 本目の差分を読んだノードを使い回した')
    // main の clone の記録のフォルダ（<top>/.git/…）を相対の path で挙げても、差分のファイルとして扱う
    const relArgs = baseArgs({ priorRecord: withFile('sub/../.git/./attention/my-turn/bbbbbbb..ppppppp.diff') })
    relArgs.prep = { ...same.prep, recordDir: '/w/.git/attention/my-turn', fingerprints: allSame, diffSame: true, priorRunDiff: 'bbbbbbb..ppppppp.diff' }
    const { calls: c10c } = await run(relArgs, responder({ W6: tree, W8, W1 }))
    check(of(c10c, 'W6').length === 0, 'fixed/reuse: 相対の path の差分のファイルを読んだノードを使い回さない')
    // URL を根拠にし、parts に差分のファイルを挙げたノードも、差分が変わったら使い回さない
    const withUrlDiff = { ...out, nodes: out.nodes.map(n => ({ ...n, urls: ['https://x'], parts: ['/rd/bbbbbbb..ppppppp.diff'] })) }
    const urlDiff = baseArgs({ priorRecord: withUrlDiff })
    urlDiff.prep = { ...same.prep, fingerprints: allSame, diffSame: false }
    const { calls: c10e } = await run(urlDiff, responder({ W6: tree, W8, W1 }))
    check(of(c10e, 'W6').length > 0, 'fixed/reuse: parts の差分が変わったのに URL のノードを使い回した')
    // GitHub の issue・PR・検索に頼った答え（gh で読んだ今の状態）は、ファイルが同じでも使い回さない
    for (const u of ['https://github.com/o/r/pull/9', 'https://github.com/search?q=x']) {
      const gh = baseArgs({ priorRecord: { ...out, nodes: out.nodes.map(n => ({ ...n, urls: [u] })) } })
      gh.prep = { ...same.prep, fingerprints: allSame }
      const { calls: c10h } = await run(gh, responder({ W6: tree, W8, W1 }))
      check(of(c10h, 'W6').length > 0, `fixed/reuse: ${u} に頼ったノードを使い回した`)
    }
    // ./ や .. を含む path も、prep と同じく畳んで指紋を引く
    const dotArgs = baseArgs({ priorRecord: withFile('lib/../a.py') })
    dotArgs.prep = { ...same.prep, fingerprints: allSame }
    const { calls: c10d } = await run(dotArgs, responder({ W6: tree, W8, W1 }))
    check(of(c10d, 'W6').length === 0, 'fixed/reuse: lib/../a.py の指紋を引けずに掘り直した')
    // Windows の共有フォルダ（//srv/share/w）の作業場でも、頭の // を残して指紋を引く
    const unc = baseArgs({ priorRecord: withFile('//srv/share/w/a.py'), workdir: '//srv/share/w' })
    unc.prep = { ...same.prep, fingerprints: allSame }
    const { calls: c10g } = await run(unc, responder({ W6: tree, W8, W1 }))
    check(of(c10g, 'W6').length === 0, 'fixed/reuse: // で始まる作業場の path の指紋を引けずに掘り直した')
    // 持ち越した判定の根拠が差分のファイルを指すときも、今の回の 1 本目を指し直す（次の回も持ち越せるように）
    const vDiff = baseArgs({ priorRecord: { ...out, nodes: out.nodes.map(n => (n.verdict ? { ...n, verdict: { ...n.verdict, evidence: [{ path: '/rd/bbbbbbb..ppppppp.diff', line: 5, quote: 'q' }] } } : n)) } })
    vDiff.prep = diffArgs.prep
    const { out: o10v, calls: c10v } = await run(vDiff, responder({ W6: tree, W8, W1 }))
    const vAts = o10v.nodes.flatMap(n => (n.verdict?.evidence ?? []).map(e => `${e.path}:${e.line}`))
    check(of(c10v, 'W10').filter(c => /^W10 [LN]\d/.test(c.label)).length === 0 && vAts.includes('/rd/bbbbbbb..hhhhhhh.diff:5')
      && !vAts.includes('/rd/bbbbbbb..ppppppp.diff:5'), `fixed/reuse: 持ち越した判定の根拠の差分を指し直さない ${vAts}`)
    // 使い回した一般の構造は、それを出した問い（2 問目の答えなら 2 問とも）と問い直しの印を持ち越す
    const genArgs = baseArgs({ priorRecord: { ...out, general: { ...out.general, questions: ['Q1', 'Q2'], askedAgain: true } } })
    genArgs.prep = same.prep
    const { out: o10q, calls: c10q } = await run(genArgs, responder({ W6: tree, W8, W1 }))
    check(of(c10q, 'W2').length === 0 && JSON.stringify(o10q.general.questions) === '["Q1","Q2"]' && o10q.general.askedAgain === true,
      `fixed/reuse: 使い回した一般の構造の問いが違う ${JSON.stringify(o10q.general)}`)
    const threadArgs = baseArgs({ priorRecord: withFile('/rd/7-thread.md') })
    threadArgs.prep = { ...same.prep }
    const { calls: c11 } = await run(threadArgs, responder({ W6: tree, W8, W1 }))
    check(of(c11, 'W6').length > 0, 'fixed/reuse: thread を読んだノードを使い回した')
    // 形の違う記録（版 1: checked の中の files・evidence の at）は使い回さず、掘り直す
    const v1 = baseArgs({ priorRecord: { ...out, version: 1 } })
    v1.prep = same.prep
    const { calls: c12 } = await run(v1, responder({ W6: tree, W8, W1 }))
    check(of(c12, 'W6').length > 0 && of(c12, 'W2').length === 1, 'fixed/reuse: 版 1 の記録を使い回した')
  }
}

// ---- 確かめていない子に乗るノード ----
// 束ねで既に在るノードに畳まれた問いの親（alsoFrom）も、そのノードの下が確かめられなければ確かめていない物に乗る
async function caseRests() {
  const isRoot = q => q.startsWith('[s11.2]') || q.startsWith("The PR's structure differs")
  const tree = uDirect => call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['D1 shared'])
    if (q === 'D1 shared') return split(id, ['U mid', 'K mid'])
    if (q === 'U mid') return uDirect ? leaf(id, { status: 'unverified', evidence: [] }) : split(id, ['V deep'])
    if (q === 'K mid') return split(id, ['U mid'])
    if (q === 'V deep') return leaf(id, { status: 'unverified', evidence: [] })
    return leaf(id)
  }
  for (const uDirect of [false, true]) {
    const { out } = await run(baseArgs(), responder({ W6: tree(uDirect) }))
    const k = out.nodes.find(n => n.question === 'K mid'), u = out.nodes.find(n => n.question === 'U mid')
    check(k && u && u.alsoFrom.includes(k.id), `rests(${uDirect}): K の問いが U に畳まれない`)
    check(k?.dependsOnUnverified && out.restsOnUnverified.includes(k.id), `rests(${uDirect}): 畳んだ問いの親が確かめていない物に乗らない`)
    check(k?.status === 'split', `rests(${uDirect}): 既に在るノードに畳まれた子しか持たない split を、掘られていない物にした ${k?.status}`)
  }
  // 分けたのに使える子の問いが 1 つも無い（howParentChanges が空）: 末端でないので反証も通らない。確かめていない物にする
  const W6 = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['D1 shared'])
    if (q === 'D1 shared') return leaf(id, { status: 'split', evidence: [], children: [{ question: 'Q', howParentChanges: '', weight: 'big', where: '' }] })
    return leaf(id)
  }
  const { out } = await run(baseArgs(), responder({ W6 }))
  const d1 = out.nodes.find(n => n.question === 'D1 shared')
  check(d1?.status === 'unverified' && out.counts.seenUndecided.unverifiedNodes.includes('D1 shared'), `rests: 子の無い split が確かめていない物にならない ${d1?.status}`)
  check(d1 && d1.parents.length > 0 && d1.parents.every(id => out.restsOnUnverified.includes(id)), 'rests: 子の無い split の親が確かめていない物に乗らない')
  // 子が W7 で全部落ちた・自分の問いを繰り返した: どちらも子の問いが掘られず、問いが開いたまま
  // droppedBefore: W7 drops 'X drop' at depth 1 only; at depth 2 W7 clusters it, so it is dug (a past drop does not block)
  const dropW7 = once => {
    let n = 0
    return call => {
      const items = w7Items(call.prompt), drop = !once || n++ === 0
      const r = byText(items.filter(([, q]) => !(drop && q === 'X drop')))
      r.dropped = items.filter(([, q]) => drop && q === 'X drop').map(([id]) => ({ id, why: 'needs no digging' }))
      return r
    }
  }
  const shapes = { dropped: ['D1 shared'], droppedBefore: ['D1 shared', 'X drop'], self: ['D1 shared'] }
  for (const [name, roots] of Object.entries(shapes)) {
    const W6s = call => {
      const id = nodeId(call.prompt), q = nodeQ(call.prompt)
      if (isRoot(q)) return split(id, roots)
      if (q === 'D1 shared') return split(id, [name === 'self' ? 'D1 shared' : 'X drop'])
      return leaf(id)
    }
    const { out: o } = await run(baseArgs(), responder({ W6: W6s, W7: dropW7(name === 'droppedBefore') }))
    const n = o.nodes.find(x => x.question === 'D1 shared')
    if (name === 'droppedBefore') {
      const x = o.nodes.find(y => y.question === 'X drop')
      check(n?.status === 'split' && x?.parents.includes(n.id), `rests(droppedBefore): 前に落とした問いを W7 が束ねても掘らない ${n?.status}`)
      continue
    }
    check(n?.status === 'unverified' && o.counts.seenUndecided.unverifiedNodes.includes('D1 shared'), `rests(${name}): 子の問いが掘られない split が確かめていない物にならない ${n?.status}`)
    check(n && n.parents.every(id => o.restsOnUnverified.includes(id)), `rests(${name}): その親が確かめていない物に乗らない`)
    check(n && !n.alsoFrom.includes(n.id), `rests(${name}): 自分の問いに自分を畳んだ`)
  }
  // 子が祖先（親の親）の問いを繰り返す: 輪を作らずに件数に出す。親の答えは上でまだ開いている問いに乗るので、ほかに
  // 掘った子が在っても（split のまま）確かめていない物に乗る
  for (const other of [false, true]) {
    const W6a = call => {
      const id = nodeId(call.prompt), q = nodeQ(call.prompt)
      if (isRoot(q)) return split(id, ['D1 shared'])
      if (q === 'D1 shared') return split(id, ['E mid'])
      if (q === 'E mid') return split(id, other ? ['D1 shared', 'F new'] : ['D1 shared'])
      return leaf(id)
    }
    const { out: o } = await run(baseArgs(), responder({ W6: W6a }))
    const d1 = o.nodes.find(x => x.question === 'D1 shared'), e = o.nodes.find(x => x.question === 'E mid')
    check(d1 && e && !d1.alsoFrom.includes(e.id), `rests(ancestor ${other}): 祖先の問いに畳んで親子の輪を作った`)
    check(e?.status === (other ? 'split' : 'unverified') && e?.dependsOnUnverified && d1?.dependsOnUnverified && o.counts.repairs.foldIntoOwnLine.length === 1,
      `rests(ancestor ${other}): 祖先の問いを繰り返した子が件数と印に出ない ${e?.status} ${JSON.stringify(o.counts.repairs.foldIntoOwnLine)}`)
  }
  // 木に在る問いの完全な繰り返しは W7 の前にコードが畳む（dropKnown: W7 は 1 回だけ）。言い替えを W7 が束ね、束の key が
  // 落とした問いで問いの文がノードの在る問い（keyDropped: W7 は 2 回）も、そのノードに畳む
  for (const shape of ['dropKnown', 'keyDropped']) {
    let w7 = 0
    const W7k = call => {
      const items = w7Items(call.prompt)
      if (w7++ === 0) {
        const r = byText(items.filter(([, q]) => q !== 'X drop'))
        r.dropped = items.filter(([, q]) => q === 'X drop').map(([id]) => ({ id, why: 'needs no digging' }))
        return r
      }
      if (shape === 'dropKnown') return { clusters: [], dropped: items.map(([id]) => ({ id, why: 'already asked' })) }
      return { clusters: [{ key: 'X drop', question: 'A known', members: items.map(([id]) => id).join(', ') }], dropped: [] }
    }
    const W6k = call => {
      const id = nodeId(call.prompt), q = nodeQ(call.prompt)
      if (isRoot(q)) return split(id, ['D1 shared', 'A known', 'X drop'])
      if (q === 'D1 shared') return split(id, [shape === 'dropKnown' ? 'A known' : 'A known again'])
      return leaf(id)
    }
    const { out: o, logs } = await run(baseArgs(), responder({ W6: W6k, W7: W7k }))
    const d1 = o.nodes.find(x => x.question === 'D1 shared'), a = o.nodes.find(x => x.question === 'A known')
    check(logs.some(l => l.startsWith(`W7 depth 2: ${shape === 'dropKnown' ? 1 : 0} of 1 `)), `rests(${shape}): 畳んだ数（0 の回も）を log() に出さない ${JSON.stringify(logs)}`)
    check(d1?.status === 'split' && a?.alsoFrom.includes(d1.id) && w7 === (shape === 'dropKnown' ? 1 : 2),
      `rests(${shape}): ノードの在る問いに畳まず、split を掘られていない物にした（W7 ${w7} 回） ${d1?.status}`)
  }
  // W7 の 1 回の答えの中で、同じ問いを束ねた物と落とした物が並ぶ・束の key が短い正規の語・key が祖先で問いの文が別のノード
  const W6f = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['P1 q', 'P2 q', 'Is X safe', 'Y other'])
    if (q === 'P1 q') return split(id, ['SAME q (P1)'], 'small')
    if (q === 'P2 q') return split(id, ['SAME q'])
    return leaf(id)
  }
  const foldW7 = shape => call => {
    const items = w7Items(call.prompt)
    if (items.some(([, q]) => q === 'P1 q')) {   // depth 1
      const r = byText(items.filter(([, q]) => q !== 'Is X safe'))
      r.clusters.push({ key: 'canon k', question: 'Is X safe', members: items.filter(([, q]) => q === 'Is X safe').map(([id]) => id).join(', ') })
      return r
    }
    // 完全に同じ文はコードが先に束ねて W7 に届かないので、W7 が束の key（'SAME q'）と同じ文の問いを落とす形で見る
    if (shape === 'sameBatch') return { clusters: [{ key: 'SAME q', question: 'SAME q', members: idOf(items, 'SAME q (P1)') }], dropped: [{ id: idOf(items, 'SAME q'), why: 'already asked' }] }
    return byText(items)
  }
  const { out: of1 } = await run(baseArgs(), responder({ W6: W6f, W7: foldW7('sameBatch') }))
  const sq = of1.nodes.find(x => x.question === 'SAME q'), p1 = of1.nodes.find(x => x.question === 'P1 q'), p2 = of1.nodes.find(x => x.question === 'P2 q')
  // 落とした方も束の一員にする: 親は parents に入り、重さも束に数える（W6 の道と割り当てに効く）
  check(sq && p1?.status === 'split' && p2?.status === 'split' && sq.parents.includes(p2.id) && sq.weight === 'big' && of1.counts.repairs.droppedKnown.length === 1,
    `rests(sameBatch): 同じ答えの中で落とした同じ問いが、束ねた問いを止めた ${p1?.status} ${p2?.status} ${JSON.stringify(of1.counts.repairs.droppedKnown)}`)
  // 短い key で作ったノードも、問いの文で当たる（次の段の子が同じ文で問う）
  const W6c = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['P1 q', 'Is X safe'])
    if (q === 'P1 q') return split(id, ['Is X safe', 'Z other'])   // 'Is X safe' はコードが畳み、W7 は 'Z other' で呼ばれる
    return leaf(id)
  }
  const { out: of2, calls: calls2 } = await run(baseArgs(), responder({ W6: W6c, W7: foldW7('canon') }))
  const xs = of2.nodes.filter(x => x.question === 'Is X safe'), p1c = of2.nodes.find(x => x.question === 'P1 q')
  // W7 には短い key の問いの文も、別の key として見せる（新しい問いを文で既に在るノードに当てられるように）
  const knownOf = prompt => (prompt.split('Questions already in the tree (keys):\n')[1] ?? '').split('\n\n')[0].split('\n')
  const shown = calls2.some(c => c.label.startsWith('W7') && ['- canon k', '- is x safe'].every(k => knownOf(c.prompt).includes(k)))
  check(shown && xs.length === 1 && xs[0].key === 'canon k' && xs[0].alsoFrom.includes(p1c?.id) && p1c?.status === 'split',
    `rests(canon): 短い key のノードに問いの文で当たらない ${JSON.stringify(xs.map(x => [x.key, x.alsoFrom]))} ${p1c?.status}`)
  // key が祖先の問い、問いの文が別のノード: W7 は 2 つを同じ問いと言ったので、自分の筋の繰り返しに数え、輪にしない
  const W6y = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['D1 shared', 'Y other'])
    if (q === 'D1 shared') return split(id, ['Z'])
    return leaf(id)
  }
  const W7y = call => {
    const items = w7Items(call.prompt)
    if (items.some(([, q]) => q === 'Z')) return { clusters: [{ key: 'D1 shared', question: 'Y other', members: items.map(([id]) => id).join(', ') }], dropped: [] }
    return byText(items)
  }
  const { out: of3 } = await run(baseArgs(), responder({ W6: W6y, W7: W7y }))
  const y = of3.nodes.find(x => x.question === 'Y other'), d1y = of3.nodes.find(x => x.question === 'D1 shared')
  check(y && d1y && !y.alsoFrom.includes(d1y.id) && d1y.dependsOnUnverified && of3.counts.repairs.foldIntoOwnLine.length === 1,
    `rests(keyAncestor): 祖先と同じと言われた問いを、別のノードに乗せた ${d1y?.status} ${JSON.stringify(of3.counts.repairs.foldIntoOwnLine)}`)
  // key と問いの文が別々のノードに当たる束: 親ごとに決める（P1 x は A q の下なので自分の筋の繰り返し、
  // P2 x は Z q の下なので両方へ）
  const W6p = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['A q', 'B q', 'Z q'])
    if (q === 'A q') return split(id, ['P1 x'])
    if (q === 'Z q') return split(id, ['P2 x'])
    if (q === 'P1 x') return split(id, ['C1'])
    if (q === 'P2 x') return split(id, ['C2'])
    return leaf(id)
  }
  const W7p = call => {
    const items = w7Items(call.prompt)
    if (items.some(([, q]) => q === 'C1')) return { clusters: [{ key: 'A q', question: 'B q', members: items.map(([id]) => id).join(', ') }], dropped: [] }
    return byText(items)
  }
  const { out: of4 } = await run(baseArgs(), responder({ W6: W6p, W7: W7p }))
  const pn = q => of4.nodes.find(x => x.question === q)
  const own4 = of4.counts.repairs.foldIntoOwnLine
  check(pn('P1 x') && pn('P1 x').dependsOnUnverified && pn('P2 x')?.status === 'split' && ['A q', 'B q'].every(q => !pn(q)?.alsoFrom.includes(pn('P1 x').id))
    && ['A q', 'B q'].every(q => pn(q)?.alsoFrom.includes(pn('P2 x')?.id)) && own4.length === 1 && own4[0].startsWith(`${pn('P1 x').id}:`) && own4[0].endsWith(`(${pn('A q')?.id})`),
    `rests(perParent): 親ごとに畳める方を選ばない ${JSON.stringify(of4.counts.repairs.foldIntoOwnLine)}`)
  // 同じ親の 2 つの束が同じ問いに当たっても、親を alsoFrom に二重に足さない
  const W7d = call => {
    const items = w7Items(call.prompt), twice = items.filter(([, q]) => q.startsWith('TWICE'))
    const r = byText(items.filter(([, q]) => !q.startsWith('TWICE')))
    r.clusters.push(...twice.map(([id]) => ({ key: 'TWICE', question: 'TWICE', members: id })))
    return r
  }
  const W6d = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['D1 shared'])
    if (q === 'D1 shared') return split(id, ['TWICE a', 'TWICE b'])
    return leaf(id)
  }
  const { out: od } = await run(baseArgs(), responder({ W6: W6d, W7: W7d }))
  const tw = od.nodes.find(x => x.question === 'TWICE')
  check(tw && !tw.alsoFrom.some(id => tw.parents.includes(id)) && new Set(tw.alsoFrom).size === tw.alsoFrom.length, `rests: 親を alsoFrom に二重に足した ${JSON.stringify(tw && [tw.parents, tw.alsoFrom])}`)
  // 1 回の答えの中で同じ key の束が 2 つ: 1 つのノードにし、どちらの親と重さも数える
  const W6s = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['P1 q', 'P2 q'])
    if (q === 'P1 q') return split(id, ['K one'], 'small')
    if (q === 'P2 q') return split(id, ['K two'])
    return leaf(id)
  }
  const W7s = call => {
    const items = w7Items(call.prompt)
    if (!items.some(([, q]) => q.startsWith('K '))) return byText(items)
    return { clusters: items.map(([id]) => ({ key: 'K q', question: 'K q', members: id })), dropped: [] }
  }
  const { out: os } = await run(baseArgs(), responder({ W6: W6s, W7: W7s }))
  const ks = os.nodes.filter(x => x.question === 'K q'), sp = ['P1 q', 'P2 q'].map(q => os.nodes.find(x => x.question === q)?.id)
  check(ks.length === 1 && sp.every(id => ks[0].parents.includes(id)) && ks[0].weight === 'big' && !ks[0].alsoFrom.length,
    `rests(sameKey): 同じ key の 2 つの束の親と重さを 1 つのノードに数えない ${JSON.stringify(ks.map(x => [x.parents, x.alsoFrom, x.weight]))}`)
  // 2 つの束を橋渡しする束（key が片方、問いの文がもう片方）: 3 つを 1 つのノードにし（W7 が先に挙げた束の問いを掘る）、
  // どの束の key でも後で当たる
  const W6b = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['P1 q', 'P2 q', 'P3 q'])
    if (/^P\d q$/.test(q)) return split(id, [`x${q[1]}`])
    if (q === 'a q') return split(id, ['b2 q'])   // the wording of the group the bridge merged in
    return leaf(id)
  }
  const W7b = call => {
    const items = w7Items(call.prompt), q = x => idOf(items, x)
    if (!q('x1')) return byText(items)
    return { clusters: [{ key: 'a q', question: 'a q', members: q('x1') }, { key: 'b q', question: 'b2 q', members: q('x2') },
      { key: 'b q', question: 'a q', members: q('x3') }], dropped: [] }
  }
  const { out: ob } = await run(baseArgs(), responder({ W6: W6b, W7: W7b }))
  const ab = ob.nodes.filter(x => ['a q', 'b q', 'b2 q'].includes(x.question))
  check(ab.length === 1 && ab[0].parents.length === 3 && ob.counts.repairs.foldIntoOwnLine.length === 1,
    `rests(bridge): 橋渡しの束で 1 つのノードにならない ${JSON.stringify(ab.map(x => [x.question, x.parents]))} ${JSON.stringify(ob.counts.repairs.foldIntoOwnLine)}`)
  // 組の 1 つの束が木に在るノードに当たり、もう 1 つは新しい key: 両方そのノードに畳み、新しい key も後の深さで当たる
  const W6e = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['Q known', 'P1 x', 'P2 x', 'P3 x'])
    if (q === 'P1 x' || q === 'P2 x') return split(id, [`c${q[1]}`])
    if (q === 'P3 x') return split(id, ['P3 y'])
    if (q === 'P3 y') return split(id, ['c3'])
    return leaf(id)
  }
  const W7e = call => {
    const items = w7Items(call.prompt), q = x => idOf(items, x)
    if (q('c1')) return { clusters: [{ key: 'Q known', question: 'Q known', members: q('c1') }, { key: 'new k', question: 'Q known', members: q('c2') }, { key: 'P3 y', question: 'P3 y', members: q('P3 y') }], dropped: [] }
    if (q('c3')) return { clusters: [{ key: 'new k', question: 'Third wording', members: q('c3') }], dropped: [] }
    return byText(items)
  }
  const { out: oe } = await run(baseArgs(), responder({ W6: W6e, W7: W7e }))
  const qk = oe.nodes.filter(x => x.question === 'Q known'), pe = q => oe.nodes.find(x => x.question === q)?.id
  check(qk.length === 1 && ['P1 x', 'P2 x', 'P3 y'].every(q => qk[0].alsoFrom.includes(pe(q))) && !pe('Third wording'),
    `rests(existingPlusNew): 木に在るノードに畳んだ組の key が後の深さで当たらない ${JSON.stringify(oe.nodes.map(x => [x.question, x.alsoFrom]))}`)
  // 組が木の 2 つのノードに当たり、親が畳めない方が確かめていない物: 親はそちらにも乗る
  const W6u = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['L known', 'U known', 'P x'])
    if (q === 'U known') return leaf(id, { status: 'unverified' })
    if (q === 'P x') return split(id, ['c'])
    return leaf(id)
  }
  const W7u = call => {
    const items = w7Items(call.prompt), c = idOf(items, 'c')
    return c ? { clusters: [{ key: 'L known', question: 'U known', members: c }], dropped: [] } : byText(items)
  }
  const { out: ou } = await run(baseArgs(), responder({ W6: W6u, W7: W7u }))
  const px = ou.nodes.find(x => x.question === 'P x')
  check(px?.dependsOnUnverified && ou.restsOnUnverified.includes(px.id), `rests(twoNodes): 組が当たった確かめていないノードに、親が乗らない ${px?.status} ${px?.dependsOnUnverified}`)
  // 組が当たった 2 つのノードと組の key は 1 つの類になる: 外の筋の親（R x）は両方に乗り、A q の下の親（P x）と、
  // 後で組の新しい key（'c k'）を問う A q の子孫（Q y）は、どちらも自分の筋の繰り返しに数える
  const W6j = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['A q', 'B q', 'M x'])
    if (q === 'A q') return split(id, ['P x', 'Q x'])
    if (q === 'M x') return split(id, ['R x'])
    if (q === 'R x') return split(id, ['r1'])
    if (q === 'P x') return split(id, ['c1'])
    if (q === 'Q x') return split(id, ['Q y'])
    if (q === 'Q y') return split(id, ['d'])
    return leaf(id)
  }
  const W7j = call => {
    const items = w7Items(call.prompt), q = x => idOf(items, x)
    if (q('c1')) return { clusters: [{ key: 'A q', question: 'B q', members: q('r1') }, { key: 'c k', question: 'B q', members: q('c1') },
      { key: 'Q y', question: 'Q y', members: q('Q y') }], dropped: [] }
    if (q('d')) return { clusters: [{ key: 'c k', question: 'D other', members: q('d') }], dropped: [] }
    return byText(items)
  }
  const { out: oj, calls: callsJ } = await run(baseArgs(), responder({ W6: W6j, W7: W7j }))
  const jn = q => oj.nodes.find(x => x.question === q)
  const ownJ = oj.counts.repairs.foldIntoOwnLine.map(x => x.split(':')[0])
  // W7 に見せる key の一覧は、新しい問いの筋の key（Q y）を、ほかの枝の古い key（P x）より先に置く
  const knownD = knownOf(callsJ.find(c => c.label.startsWith('W7') && idOf(w7Items(c.prompt), 'd'))?.prompt ?? '')
  check(knownD.includes('- q y') && knownD.includes('- p x') && knownD.indexOf('- q y') < knownD.indexOf('- p x'),
    `rests(knownOrder): W7 の key の一覧で、自分の筋の key が後ろにある ${JSON.stringify(knownD.slice(0, 12))}`)
  check(jn('R x') && ['A q', 'B q'].every(q => jn(q)?.alsoFrom.includes(jn('R x').id)) && !jn('D other')
    && ownJ.length === 2 && ['P x', 'Q y'].every(q => ownJ.includes(jn(q)?.id) && jn(q).dependsOnUnverified),
    `rests(joinedAlias): 組の類の key で自分の筋を見逃した ${JSON.stringify(jn('B q')?.alsoFrom)} ${JSON.stringify(oj.counts.repairs.foldIntoOwnLine)}`)
  // 組で A q と B q が同じ類になった後、B q の子孫が B q を問い直しても A q を問うても、A q に乗せず、
  // 自分の筋の繰り返しに数える（W7 がどちらの key を書いても同じ答え）。B q の短い key（'b k'）も類に入るので、
  // A q の子孫（U y）がそれを問うても自分の筋の繰り返し
  const W6v = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['A q', 'B q', 'M x'])
    if (q === 'M x') return split(id, ['R x'])
    if (q === 'R x') return split(id, ['r1'])
    if (q === 'B q') return split(id, ['S x'])
    if (q === 'S x') return split(id, ['T x'])
    if (q === 'T x') return split(id, ['B q', 'A q'])
    if (q === 'A q') return split(id, ['U x'])
    if (q === 'U x') return split(id, ['U y'])
    if (q === 'U y') return split(id, ['U z'])
    return leaf(id)
  }
  const W7v = call => {
    const items = w7Items(call.prompt), r1 = idOf(items, 'r1'), uz = idOf(items, 'U z'), r = byText(items)
    if (r1) return { clusters: [{ key: 'A q', question: 'B q', members: r1 }, ...r.clusters.filter(c => c.key !== 'r1')], dropped: [] }
    r.clusters.forEach(c => { if (c.key === 'B q' && !uz) c.key = 'b k'; if (c.key === 'U z') c.key = 'b k' })
    return r
  }
  const { out: ov } = await run(baseArgs(), responder({ W6: W6v, W7: W7v }))
  const vn = q => ov.nodes.find(x => x.question === q), ownV = ov.counts.repairs.foldIntoOwnLine
  check(vn('R x') && vn('T x') && vn('U y') && vn('B q')?.key === 'b k' && ['A q', 'B q'].every(q => vn(q)?.alsoFrom.includes(vn('R x').id))
    && ownV.length === 3 && ownV.filter(x => x.startsWith(`${vn('T x').id}:`)).length === 2 && ownV.some(x => x.startsWith(`${vn('U y').id}:`))
    && !vn('A q').alsoFrom.includes(vn('T x').id) && !vn('B q').alsoFrom.includes(vn('U y').id) && vn('T x').dependsOnUnverified && vn('U y').dependsOnUnverified,
    `rests(sameClass): 同じ類の問いを問い直した子孫を、別のノードに乗せた ${JSON.stringify(ownV)} ${JSON.stringify(vn('A q')?.alsoFrom)}`)
  // 1 回の W7 の答えが A q と B q を同じ類にするとき、答えの束の並びに関わらず、A q の下の親（P）が B q の短い key
  // （'b k'）を問うのは自分の筋の繰り返し（並びが先の束を、類を合わせる前に B q に乗せない）
  const W6ord = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['A q', 'B q', 'M x'])
    if (q === 'A q') return split(id, ['P'])
    if (q === 'M x') return split(id, ['Mm'])
    if (q === 'P') return split(id, ['px'])
    if (q === 'Mm') return split(id, ['mx'])
    return leaf(id)
  }
  for (const flip of [false, true]) {
    const W7ord = call => {
      const items = w7Items(call.prompt), q = x => idOf(items, x), r = byText(items)
      const two = [{ key: 'b k', question: 'X', members: q('px') }, { key: 'a q', question: 'B q', members: q('mx') }]
      if (q('px')) return { clusters: flip ? two.reverse() : two, dropped: [] }
      r.clusters.forEach(c => { if (c.key === 'B q') c.key = 'b k' })
      return r
    }
    const { out: oOrd } = await run(baseArgs(), responder({ W6: W6ord, W7: W7ord }))
    const ordN = q => oOrd.nodes.find(x => x.question === q), ownOrd = oOrd.counts.repairs.foldIntoOwnLine
    check(ordN('P') && ordN('Mm') && ordN('B q')?.key === 'b k' && !ordN('B q').alsoFrom.includes(ordN('P').id) && ownOrd.length === 1 && ownOrd[0].startsWith(`${ordN('P').id}:`)
      && ordN('P').dependsOnUnverified && ['A q', 'B q'].every(q => ordN(q)?.alsoFrom.includes(ordN('Mm').id)) && ordN('Mm').dependsOnUnverified,
      `rests(answerOrder ${flip}): 束の並びで、自分の筋の繰り返しをほかのノードに乗せた ${JSON.stringify(ordN('B q')?.alsoFrom)} ${JSON.stringify(ownOrd)}`)
  }
  // 前の深さで B q に乗った親は、後の深さで A q と B q が同じ類になると、類のほかのノード（A q）にも乗る。A q が筋に在る親（P）は
  // 自分の筋の繰り返しに数えて確かめていない印を付け、筋に無い親（Nn）は A q にも乗り、A q が確かめていない物に乗れば印を継ぐ。
  // A q に乗った親（Kk）は B q にも乗る。さらに後で C q も同じ類になっても、P の繰り返しを数え直さず、P を C q に乗せない
  const W6late = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['A q', 'B q', 'M x', 'N x', 'K x', 'C q', 'L x'])
    if (q === 'N x') return split(id, ['Nn'])
    if (q === 'Nn') return split(id, ['nx'])
    if (q === 'K x') return split(id, ['Kk'])
    if (q === 'Kk') return split(id, ['kx'])
    if (q === 'L x') return split(id, ['Ll'])
    if (q === 'Ll') return split(id, ['Lm'])
    if (q === 'Lm') return split(id, ['Ln'])
    if (q === 'Ln') return split(id, ['lz'])
    if (q === 'Mm') return split(id, ['Mn'])
    if (q === 'Mn') return split(id, ['mz'])
    return W6ord(call)
  }
  const W7late = call => {
    const items = w7Items(call.prompt), q = x => idOf(items, x), r = byText(items)
    const others = (...ks) => r.clusters.filter(c => !ks.includes(c.key))
    if (q('px')) return { clusters: [{ key: 'b k', question: 'X', members: `${q('px')}, ${q('nx')}` }, { key: 'a q', question: 'A q', members: q('kx') }, ...others('px', 'nx', 'kx')], dropped: [] }
    if (q('mz')) return { clusters: [{ key: 'a q', question: 'B q', members: q('mz') }, ...others('mz')], dropped: [] }
    if (q('lz')) return { clusters: [{ key: 'c q', question: 'B q', members: q('lz') }], dropped: [] }
    r.clusters.forEach(c => { if (c.key === 'B q') c.key = 'b k' })
    return r
  }
  const { out: oLate } = await run(baseArgs(), responder({ W6: W6late, W7: W7late }))
  const lateN = q => oLate.nodes.find(x => x.question === q), ownLate = oLate.counts.repairs.foldIntoOwnLine
  check(lateN('P') && lateN('Mn') && lateN('Nn') && ['P', 'Nn'].every(q => lateN('B q')?.alsoFrom.includes(lateN(q).id)) && !lateN('A q').alsoFrom.includes(lateN('P').id)
    && ownLate.length === 1 && ownLate[0].startsWith(`${lateN('P').id}:`) && ownLate[0].endsWith(`(${lateN('A q').id})`) && lateN('P').dependsOnUnverified
    && lateN('A q').alsoFrom.includes(lateN('Nn').id) && lateN('Nn').dependsOnUnverified && ['A q', 'B q'].every(q => lateN(q)?.alsoFrom.includes(lateN('Mn').id))
    && lateN('Kk') && lateN('B q').alsoFrom.includes(lateN('Kk').id) && lateN('Ln') && lateN('C q')?.alsoFrom.includes(lateN('Ln').id) && !lateN('C q').alsoFrom.includes(lateN('P').id),
    `rests(laterMerge): 後で類が合わさったとき、前に乗った親を類のほかのノードに当て直さない ${JSON.stringify(ownLate)} ${JSON.stringify(lateN('A q')?.alsoFrom)} ${lateN('Nn')?.dependsOnUnverified}`)
  // 句読点だけの key（'?'）は key に使わず、問いの文で見分ける: 違う問いが 1 つのノードにまとまらない
  const W6q = call => isRoot(nodeQ(call.prompt)) ? split(nodeId(call.prompt), ['first different', 'second different']) : leaf(nodeId(call.prompt))
  const W7q = call => {
    const items = w7Items(call.prompt), all = t => items.filter(([, x]) => x === t).map(([id]) => id).join(', ')
    if (!all('first different')) return byText(items)
    return { clusters: [{ key: '?', question: 'first different', members: all('first different') }, { key: '?', question: 'second different', members: all('second different') }], dropped: [] }
  }
  const { out: oq } = await run(baseArgs(), responder({ W6: W6q, W7: W7q }))
  check(['first different', 'second different'].every(q => oq.nodes.some(x => x.question === q)) && oq.nodes.every(x => x.key !== ''),
    `rests(emptyKey): 句読点だけの key で違う問いがまとまった ${JSON.stringify(oq.nodes.map(x => [x.key, x.question]))}`)
  // 組が当たったノードの片方が、同じ段の後で確かめていない物になる（子を全部落とされた split）: 親にも届く
  const W6m = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['L known', 'S later', 'P x'])
    if (q === 'S later') return split(id, ['S child'])
    if (q === 'P x') return split(id, ['c'])
    return leaf(id)
  }
  const W7m = call => {
    const items = w7Items(call.prompt), c = idOf(items, 'c')
    if (!c) return byText(items)
    return { clusters: [{ key: 'L known', question: 'S later', members: c }], dropped: [{ id: idOf(items, 'S child'), why: 'needs no digging' }] }
  }
  const { out: ol } = await run(baseArgs(), responder({ W6: W6m, W7: W7m }))
  const pl = ol.nodes.find(x => x.question === 'P x'), sl = ol.nodes.find(x => x.question === 'S later')
  check(sl?.status === 'unverified' && pl?.dependsOnUnverified, `rests(laterUnsure): 後で確かめていない物になったノードが、組で乗った親に届かない ${sl?.status} ${pl?.dependsOnUnverified}`)
  // W8 の抜けも組にまとめる: 同じ key の 2 つと、落とした同じ問いを、区分 8 の 1 つのルートにする
  let w8g = 0
  // 落とす 3 つ目は束の key と同じ文（'G a' の繰り返しはコードが束ねて W7 に届かない）
  const W8g = () => (w8g++ ? { gaps: [], reason: 'checked' } : { gaps: ['G a', 'G b', 'g'].map(q => ({ question: q, why: 'w', where: '' })), reason: '' })
  const W7g = call => {
    if (!call.label.startsWith('W7 gaps')) return byText(w7Items(call.prompt))
    const [a, b, c] = w7Items(call.prompt).map(([id]) => id)
    return { clusters: [{ key: 'g', question: 'G a', members: a }, { key: 'g', question: 'G b', members: b }], dropped: [{ id: c, why: 'already asked' }] }
  }
  const { out: og } = await run(baseArgs(), responder({ W8: W8g, W7: W7g }))
  const gs = og.nodes.filter(x => ['G a', 'G b', 'g'].includes(x.question))
  check(gs.length === 1 && gs[0].rootClass === 8 && og.gapRounds[0].gaps.every(g => g.outcome === 'dug') && og.counts.repairs.droppedKnown.length === 1,
    `rests(gapGroup): W8 の抜けの組が 1 つのルートにならない ${JSON.stringify(gs.map(x => x.question))} ${JSON.stringify(og.gapRounds[0].gaps)}`)
  // 落とした問いが束に入り、その束が自分の祖先の問い: どちらの件数にも出し、親を確かめていない物にする
  const W6o = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['D1 shared'])
    if (q === 'D1 shared') return split(id, ['E mid'])
    if (q === 'E mid') return split(id, ['D1 shared again', 'D1 restated'])
    return leaf(id)
  }
  // 完全に同じ文（'D1 shared'）はコードが畳む（dedup のケース）。ここは W7 が言い替えを祖先の key に束ね、束の問いの文と同じ問いを落とす
  const W7o = call => {
    const items = w7Items(call.prompt), drop = idOf(items, 'D1 restated')
    if (!drop) return byText(items)   // the roots' children are dug as usual
    return { clusters: [{ key: 'D1 shared', question: 'D1 restated', members: idOf(items, 'D1 shared again') }], dropped: [{ id: drop, why: 'already asked' }] }
  }
  const { out: oo } = await run(baseArgs(), responder({ W6: W6o, W7: W7o }))
  const eo = oo.nodes.find(x => x.question === 'E mid')
  check(eo?.status === 'unverified' && oo.counts.repairs.foldIntoOwnLine.length === 1 && oo.counts.repairs.droppedKnown.length === 1,
    `rests(dropOwnLine): 落として祖先の束に入った問いが件数と印に出ない ${eo?.status} ${JSON.stringify(oo.counts.repairs)}`)
}

// ---- W7 の前のコードの重複落とし（設計のセクション 3 の W7） ----
// 鍵（keyOf: 小文字・空白の並びを 1 つの空白・末尾の空白と . ? ! 。 ？ を落とす）が木の key か、同じ回の前の問いの鍵と
// 同じ問いは W7 に届かず、W7 が完全な繰り返しを置く所（ノードの alsoFrom か、前の問いの束の parents）にコードが置く
async function caseDedup() {
  const isRoot = q => q.startsWith('[s11.2]') || q.startsWith("The PR's structure differs")
  const W6 = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (q.startsWith('[s11.2]')) return split(id, ['DUP q', 'Fresh a'])
    if (q.startsWith("The PR's structure differs")) return split(id, ['dup   Q?', 'Fresh b'])
    if (q === 'DUP q') return split(id, ['Fresh a.'])   // 木に在るノード（兄弟の枝）の繰り返し
    if (q === 'Fresh b') return split(id, ['E mid'])
    if (q === 'E mid') return split(id, ['Fresh B', 'fresh b!'])   // 自分の祖先の問いの繰り返しだけ: 深さ 3 は W7 を呼ばない
    return leaf(id)
  }
  let w8 = 0
  const W8 = () => (w8++ ? { gaps: [], reason: 'checked' } : { gaps: ['fresh A', 'Gap new', 'gap   NEW.'].map(q => ({ question: q, why: 'w', where: '' })), reason: '' })
  const { out, calls, logs } = await run(baseArgs(), responder({ W6, W8 }))
  const w7 = of(calls, 'W7')
  const shown = w7.flatMap(c => w7Items(c.prompt).map(([, q]) => q))
  // 1) 完全な繰り返しは W7 に 1 つも届かず、W7 の 1 回に同じ鍵が 2 つ並ばない
  const held = ['dup   Q?', 'Fresh a.', 'Fresh B', 'fresh b!', 'fresh A', 'gap   NEW.']
  check(held.every(q => !shown.includes(q)), `dedup: 完全な繰り返しが W7 に届いた ${JSON.stringify(shown.filter(q => held.includes(q)))}`)
  check(w7.every(c => { const ks = w7Items(c.prompt).map(([, q]) => q.toLowerCase()); return new Set(ks).size === ks.length }), 'dedup: W7 の 1 回に同じ問いが 2 つ並んだ')
  // 2) 残りが無い回は W7 を呼ばない（深さ 3 は祖先の問いの繰り返しだけ）
  check(!w7.some(c => c.label === 'W7 depth 3'), `dedup: 残りが無いのに W7 を呼んだ ${w7.map(c => c.label)}`)
  // 3) 畳んだ元が記録に残る: 同じ回の繰り返しは束のノードの parents に、木のノードの繰り返しは alsoFrom に入る
  const n = q => out.nodes.find(x => x.question === q)
  const ra = out.nodes.find(x => x.question.startsWith('[s11.2]')), rb = out.nodes.find(x => x.question.startsWith("The PR's structure differs"))
  check(out.nodes.filter(x => x.key === 'dup q').length === 1 && [ra?.id, rb?.id].every(id => n('DUP q')?.parents.includes(id)),
    `dedup: 同じ回の繰り返しの親が束のノードの parents に無い ${JSON.stringify(n('DUP q')?.parents)}`)
  check(n('Fresh a')?.alsoFrom.includes(n('DUP q')?.id) && !out.nodes.some(x => x.question === 'Fresh a.'),
    `dedup: 木のノードの繰り返しの親が alsoFrom に無い ${JSON.stringify(n('Fresh a')?.alsoFrom)}`)
  // 4) 自分の祖先の繰り返しは、W7 を通ったときと同じく件数に出し、親を確かめていない物にする
  check(n('E mid')?.status === 'unverified' && out.counts.repairs.foldIntoOwnLine.some(x => x.startsWith(`${n('E mid')?.id}:`)),
    `dedup: 祖先の繰り返しが件数と印に出ない ${n('E mid')?.status} ${JSON.stringify(out.counts.repairs.foldIntoOwnLine)}`)
  // 5) W8 の抜け: 木に在る問いは seen、同じ回の繰り返しは前の問いと 1 つのルートになる
  const g = out.gapRounds[0]?.gaps ?? []
  check(JSON.stringify(g.map(x => x.outcome)) === '["seen","dug","dug"]' && out.nodes.filter(x => x.key === 'gap new').length === 1 && n('Gap new')?.rootClass === 8,
    `dedup: W8 の抜けの繰り返しが畳まれない ${JSON.stringify(g)}`)
  // 6) コードで落とした数を回ごとに log() に出す
  const want = ['W7 depth 1: 1 of 4 ', 'W7 depth 2: 1 of 2 ', 'W7 depth 3: 2 of 2 ', 'W7 gaps round 1: 2 of 3 ']
  check(want.every(w => logs.some(l => l.startsWith(w))), `dedup: log() に落とした数が出ない ${JSON.stringify(logs)}`)
  check(w7.every(c => logs.some(l => l.startsWith(`${c.label}: `))),
    `dedup: W7 を呼んだ回に log() が無い ${JSON.stringify(logs)}`)
  // 7) W7 が返らない回: コードで畳んだ物は置き、W7 に渡した物（とその繰り返し）だけを見られなかった物にする
  const W6n = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (q.startsWith('[s11.2]')) return split(id, ['Fresh a'])
    if (q === 'Fresh a') return split(id, ['New z', 'new z?', 'Fresh a'])   // 2 つ目は 1 つ目の繰り返し、3 つ目は自分の繰り返し
    return leaf(id)
  }
  const W7n = call => (call.label === 'W7 depth 2' ? null : byText(w7Items(call.prompt)))
  const { out: o2, calls: c2 } = await run(baseArgs(), responder({ W6: W6n, W7: W7n }))
  const fa = o2.nodes.find(x => x.question === 'Fresh a'), sent = of(c2, 'W7').find(c => c.label === 'W7 depth 2')
  check(sent && JSON.stringify(w7Items(sent.prompt).map(([, q]) => q)) === '["New z"]', `dedup(null): W7 に渡した物が違う ${sent && JSON.stringify(w7Items(sent.prompt))}`)
  check(JSON.stringify(o2.counts.notSeen.afterNullMerge) === '["New z","new z?"]', `dedup(null): 見られなかった物が違う ${JSON.stringify(o2.counts.notSeen.afterNullMerge)}`)
  check(fa?.dependsOnUnverified && o2.counts.repairs.foldIntoOwnLine.some(x => x.startsWith(`${fa?.id}:`)),
    `dedup(null): コードで畳んだ自分の繰り返しが W7 の失敗で消えた ${JSON.stringify(o2.counts.repairs.foldIntoOwnLine)}`)
}

// ---- 2. 子を 2 つずつ返し続け、W8 も抜けを返し続ける ----
async function caseGrow() {
  let k = 0
  const W6 = call => split(nodeId(call.prompt), [`grow ${++k}`, `grow ${++k}`])
  const W8 = () => ({ gaps: [{ question: `gap ${++k}`, why: 'w', where: '' }, { question: `gap ${++k}`, why: 'w', where: '' }], reason: '' })
  const { out, calls } = await run(baseArgs({ limits: { nodes: 10 } }), responder({ W6, W8 }))
  check(of(calls, 'W6').length <= 10, `grow: W6 の体数 ${of(calls, 'W6').length} が上限 10 を越えた`)
  check(out.counts.nodesUsed === of(calls, 'W6').length, 'grow: nodesUsed が W6 の体数と合わない')
  const cut = out.nodes.filter(n => n.note === 'not dug: node cap')
  check(cut.length > 0 && cut.every(n => n.status === 'unverified'), 'grow: 上限で掘らなかった問いが未確認で返らない')
  check(out.counts.notSeen.cut.length === cut.length, 'grow: 掘らなかった問いの数が件数に出ない')
  check(out.nodes.filter(n => n.parents.length === 0 && n.rootClass < 8).every(n => n.dependsOnUnverified), 'grow: 未確認の上に乗るルートに印が付かない')
  const last = out.gapRounds.at(-1)
  check(last?.gaps.length && last.gaps.every(g => g.outcome === 'cut') && out.counts.notSeen.gapsAfterCap.length === 2, 'grow: 上限の後の W8 の抜けが未確認で返らない')
  check(out.version === 3 && out.nodes.length > 0, 'grow: 記録が返らない')
}

// ---- 3. 違う親が同じ問いを返す ----
async function caseSame() {
  const W6 = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (q.startsWith('[s11.2]') || q.startsWith("The PR's structure differs")) return split(id, ['SAME'])
    return leaf(id)
  }
  const { out, calls } = await run(baseArgs(), responder({ W6 }))
  const same = out.nodes.filter(n => n.question === 'SAME')
  check(same.length === 1 && same[0].parents.length === 2, 'same: 同じ問いが 1 つの束にならない')
  check(of(calls, 'W6').filter(c => nodeQ(c.prompt) === 'SAME').length === 1, 'same: 同じ問いを 2 回掘った')
  const r = out.counts.repairs
  check(!r.clusterMissing.length && !r.clusterDuplicate.length && !r.clusterUnknown.length, `same: 束の照合が通らない ${JSON.stringify(r)}`)
  // W7 が子を落とす・二重に置く・知らない id を書く: 照合が直して件数に出す
  const W7 = call => {
    const ids = w7Items(call.prompt).map(x => x[0])
    return { clusters: [{ key: 'SAME', question: 'SAME', members: `${ids[0]}, ${ids[0]}, q999` }], dropped: [] }
  }
  // 完全に同じ文の 2 つ目はコードが束ねて W7 に届かないので、2 つ目の親は言い替えた問いを返す
  const W6b = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (q.startsWith('[s11.2]')) return split(id, ['SAME'])
    if (q.startsWith("The PR's structure differs")) return split(id, ['SAME, reworded'])
    return leaf(id)
  }
  const { out: o2 } = await run(baseArgs(), responder({ W6: W6b, W7 }))
  const r2 = o2.counts.repairs
  check(r2.clusterMissing.length === 1 && r2.clusterDuplicate.length === 1 && r2.clusterUnknown.length === 1, `same: 束の崩れが件数に出ない ${JSON.stringify(r2)}`)
}

// ---- 6 の割り当て: script の allot をそのまま取り出して回す ----
async function caseAllot() {
  const m = SRC.match(/function allot\([\s\S]*?\n}\n/)
  check(!!m, 'allot: script に allot が無い')
  if (!m) return
  const WEIGHT = { big: 3, medium: 2, small: 1 }
  const byId = new Map()
  const mk = (id, rootIdx, order) => { const n = { id, rootIdx, order, parents: [] }; byId.set(id, n); return n }
  mk('p1', 0, 0); mk('p2', 1, 1)
  const rootIdx = n => n.rootIdx ?? 0
  const allot = new Function('byId', 'WEIGHT', 'rootIdx', `${m[0]}; return allot`)(byId, WEIGHT, rootIdx)
  let o = 10
  const kid = (parents, weight) => ({ id: `c${o}`, order: o++, parents, weight })
  const p1 = [...Array(6)].map(() => kid(['p1'], 'big')).concat([...Array(3)].map(() => kid(['p1'], 'small')))
  const p2 = [...Array(6)].map(() => kid(['p2'], 'medium'))
  // 設計 6 の例: 残り 12、p1 に 9、p2 に 6 → 6 ずつ、p1 の small 3 つを切る
  const r = allot([...p2, ...p1], 12)
  check(r.kept.length === 12 && r.cut.length === 3 && r.cut.every(n => n.weight === 'small' && n.parents[0] === 'p1'), `allot: 設計 6 の例と違う（cut ${r.cut.map(n => n.weight)}）`)
  // 余りは次の親へ: p1 に 3、p2 に 9、残り 12 → 全部
  const r2 = allot([...p1.slice(0, 3), ...[...Array(9)].map(() => kid(['p2'], 'small'))], 12)
  check(r2.kept.length === 12 && r2.cut.length === 0, 'allot: 親の余りが次の親へ回らない')
  // 親を 2 つ持つ問いは先のルートの親の分に数え、同じ重さなら先に残る
  const both = kid(['p2', 'p1'], 'small')
  const r3 = allot([both, ...[...Array(3)].map(() => kid(['p1'], 'small')), ...[...Array(2)].map(() => kid(['p2'], 'small'))], 4)
  check(r3.kept.includes(both) && r3.kept.filter(n => n.parents[0] === 'p2' && n !== both).length === 2, 'allot: 親を 2 つ持つ問いが先のルートの親の分に数えられない')
}

// ---- 4. 飛ばしを混ぜる ----
async function caseSkips() {
  let firstLeaf = true
  const over = {
    W1: () => ({ structure: 'S', kind: 'K', mechanisms: [{ mechanism: 'M', premise: 'P' }], selfMade: [], extraSmells: [], hiddenChoices: [], noParts: false, noPartsReason: '' }),
    'W4 smell 2': () => null,
    'W4 smell 3': () => ({ verdict: 'none', answer: '', evidence: [{ path: 'a.py', line: 1, quote: '' }] }),
    W6: call => {
      const id = nodeId(call.prompt), q = nodeQ(call.prompt)
      if (q.startsWith('World')) return null
      if (firstLeaf) { firstLeaf = false; return leaf(id, { evidence: [], answer: 'bad \u001b[31mred‮ flip' }) }
      return leaf(id)
    },
    W8: () => ({ gaps: [], reason: '' }),
    W9: () => ({ fixes: [], groups: [], searched: '', outside: [] }),
    W10: () => null,
  }
  const { out, calls } = await run(baseArgs({ unread: ['big.bin'] }), responder(over))
  const st = out.counts.stages
  const has = (s, label, field) => st[s]?.empty.some(e => e.label === label && e.field === field)
  check(of(calls, 'W4').filter(c => c.label.startsWith('W4 smell')).length === 5 && of(calls, 'W4').length === 11, 'skips: W1 が臭いを足さないのに W4 の 5 問と 6 つの目が全部立たない')
  check(st.W4.null.includes('W4 smell 2'), 'skips: W4 の null が件数に出ない')
  check(has('W4', 'W4 smell 3', 'answer'), 'skips: W4 の空の answer が件数に出ない')
  check(has('W1', 'W1 structure', 'selfMade'), 'skips: 訳の無い空の selfMade が件数に出ない')
  check(st.W6.empty.some(e => e.field === 'evidence'), 'skips: 根拠の無い末端が件数に出ない')
  check(st.W6.null.length >= 1 && out.counts.notSeen.nullNodes.length === st.W6.null.length, 'skips: 返らなかったノードが見られなかった物に出ない')
  check(out.nodes.filter(n => n.note.startsWith('not seen')).every(n => n.status === 'unverified'), 'skips: 返らなかったノードが未確認にならない')
  check(has('W8', 'W8 round 1', 'gaps') && has('W8', 'W8 round 1', 'reason'), 'skips: 訳の無い「抜けなし」が件数に出ない')
  check(has('W9', 'W9 fixes', 'fixes') && has('W9', 'W9 fixes', 'searched'), 'skips: W9 の空が件数に出ない')
  check(out.counts.allNull.includes('W10'), 'skips: 全部 null の段が分けて返らない')
  check(!out.counts.allNull.includes('W6'), 'skips: 一部だけ null の段を全部 null に数えた')
  check(out.counts.seenUndecided && out.counts.notSeen, 'skips: 見られなかった物と見て決まらない物が分かれない')
  const bad = out.nodes.find(n => String(n.answer).startsWith('bad'))
  check(bad && !/[\u001b‮]/.test(bad.answer), 'skips: 制御の字が消えない')
  check(of(calls, 'W8')[0].prompt.includes('big.bin'), 'skips: 会話が読めなかった物が W8 に渡らない')
}

// ---- 返す形の自己矛盾と、表の旧の文の行き先 ----
async function caseSchema() {
  const { calls } = await run(baseArgs(), responder())
  const seen = new Set(calls.map(c => c.opts.schema).filter(Boolean))
  check(seen.size >= 9, `schema: 返す形の種類 ${seen.size}`)
  for (const s of seen) for (const p of schemaProblems(s)) fails.push(`schema: ${p}`)
  check(!/Date\.now\(\)|Math\.random\(\)|new Date\(\)/.test(SRC.replace(/\/\/.*$/gm, '')), 'schema: Date.now か Math.random を使っている')
}
async function caseMap() {
  const map = JSON.parse(fs.readFileSync(path.join(ROOT, 'tests/my-turn-dig-map.json'), 'utf8'))
  const norm = t => t.replace(/\s+/g, '')
  const joined = norm(map.sentences.map(e => e.ja).join(''))
  check(crypto.createHash('sha256').update(joined).digest('hex') === map.sha256, 'map: 文を繋いだ物が旧の手順 6〜15 と違う')
  try {
    const [rev, file] = map.source.split(':')
    const old = execFileSync('git', ['-C', ROOT, 'show', `${rev}:${file}`], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).split('\n')
    const a = old.findIndex(l => l.startsWith('6. ')), b = old.findIndex(l => l.startsWith('16. '))
    const block = old.slice(a, b).filter(l => l.trim() && !l.startsWith('###')).join('')
    check(crypto.createHash('sha256').update(norm(block)).digest('hex') === map.sha256, 'map: source の旧の手順と sha256 が合わない')
  } catch { /* 浅い clone で source の commit が無い: sha256 の照合だけにする */ }
  const ids = new Set()
  for (const e of map.sentences) {
    check(!ids.has(e.id), `map: id ${e.id} が二重`)
    ids.add(e.id)
    if (e.to === 'js') check(SRC.includes(`[${e.id}]`), `map: ${e.id} の印が script に無い`)
    else if (e.to === 'md') check(fs.readFileSync(path.join(ROOT, e.file), 'utf8').includes(e.find), `map: ${e.id} の字「${e.find}」が ${e.file} に無い`)
    else if (e.to === 'dropped') check(!!e.why && !SRC.includes(`[${e.id}]`), `map: 外した ${e.id} に訳が無いか、script に印が残る`)
    else fails.push(`map: ${e.id} の to が知らない値 ${e.to}`)
  }
  for (const t of SRC.matchAll(/\[(s\d+\.\d+)\]/g)) check(map.sentences.some(e => e.id === t[1] && e.to === 'js'), `map: script の印 ${t[1]} が表に無い`)
}

// ---- 写しの照合（設計 3）: 合わない写しの根拠を落とし、根拠が尽きた末端と臭いの答えは確かめていない物にして反証しない ----
async function caseQuotes() {
  const fnvT = s => { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 } return h.toString(16).padStart(8, '0') }
  const missingWhere = pred => call => {
    const items = quoteItems(call.prompt)
    return { ran: true, checked: items.length, missing: items.filter(pred).map(x => ({ id: x[0], why: 'not on that line' })), garbled: [], error: '' }
  }
  const isRoot = q => q.startsWith('[s11.2]') || q.startsWith("The PR's structure differs")
  // 1. 末端の写しが全部合わない: 末端は確かめていない物になり、反証も直しの案にも乗らない。ほかの根拠は残る
  {
    const W6 = call => {
      const id = nodeId(call.prompt), q = nodeQ(call.prompt)
      if (isRoot(q)) return leaf(id, { evidence: [{ path: 'bad.py', line: 3, quote: 'nope' }], locations: [] })
      return leaf(id, { evidence: [{ path: 'bad.py', line: 3, quote: 'nope' }, { path: 'a.py', line: 1, quote: 'x' }], locations: [] })
    }
    const { out, calls } = await run(baseArgs(), responder({ W6, Quotes: missingWhere(x => x[1] === 'bad.py') }))
    const roots = out.nodes.filter(n => out.roots.includes(n.id))
    const r1 = roots.find(n => isRoot(n.question)), other = roots.find(n => !isRoot(n.question))
    check(r1?.status === 'unverified' && r1.resultStatus === 'unverified' && r1.evidence.length === 0 && r1.note.includes('quote check') && !refuted(calls, out, r1.id)
      && itemOf(out, r1.id)?.state === 'unverified' && !of(calls, 'W9')[0].prompt.includes(`ANSWER-${r1.id}`), `quotes: 写しが全部合わない末端が、確かめていない物にならないか反証された ${r1?.status}`)
    check(other?.status === 'leaf' && other.evidence.length === 1 && other.evidence[0].path === 'a.py' && refuted(calls, out, other.id),
      `quotes: 合う写しの残る末端を落とした ${other?.status} ${JSON.stringify(other?.evidence)}`)
    const q = out.counts.quotes
    check(q.dropped.length === roots.length && q.dropped.every(d => d.path === 'bad.py' && d.line === 3 && d.why) && q.toUnverified.filter(id => id.startsWith('N')).length === 2,
      `quotes: 落とした根拠が件数に出ない ${JSON.stringify(q)}`)
    // 「このままでよい」の末端の写しが全部合わない: 数え直しに回らないので、台帳に確かめていない物で載る
    {
      const W6f = call => { const id = nodeId(call.prompt), q = nodeQ(call.prompt)
        return leaf(id, { worth: isRoot(q) ? 'fine' : 'fix', evidence: [{ path: isRoot(q) ? 'bad.py' : 'a.py', line: 3, quote: 'nope' }], locations: [] }) }
      const { out: of2 } = await run(baseArgs(), responder({ W6: W6f, Quotes: missingWhere(x => x[1] === 'bad.py') }))
      const rf = of2.nodes.find(n => of2.roots.includes(n.id) && isRoot(n.question))
      check(rf?.status === 'unverified' && itemOf(of2, rf.id)?.state === 'unverified', `quotes: 写しの合わない「このままでよい」の末端が台帳から落ちた ${rf?.status}`)
    }
    // 記録の resultStatus も確かめていない物にする（次の回が末端として使い回さない）
    // 同じ根拠は 1 件にまとめて送り、印は id・path・行・写しから作る
    const items = of(calls, 'Quotes').flatMap(c => quoteItems(c.prompt))
    check(items.length === 3 && items.every(([id, pth, line, quote, sum]) => sum === fnvT(`${id}\n${pth}\n${line}\n${quote}`)), `quotes: 送る行がまとまらないか印が違う ${JSON.stringify(items)}`)
  }
  // 2. 臭いの答えの写しが合わない: 臭いの答えは確かめていない物になり、反証しない
  {
    const { out, calls } = await run(baseArgs(), responder({ Quotes: missingWhere(x => x[3] === 'y') }))
    check(out.smells[0].answer.verdict === 'unverified' && !calls.some(c => c.label === 'W10 S1') && calls.some(c => c.label === 'W10 S2')
      && out.counts.quotes.toUnverified.includes('S1') && out.smells[0].answer.evidence.length === 0, 'quotes: 写しの合わない臭いの答えが反証された')
  }
  // 3. 照合の段が返らない・数が合わない・印の合わない行: 根拠は落とさず、確かめていない件数に出す
  for (const [name, Quotes, field] of [['null', () => null, 'unchecked'], ['count', call => ({ ...quotesOk(call), checked: 0 }), 'unchecked'],
    ['garbled', call => ({ ...quotesOk(call), missing: quoteItems(call.prompt).map(x => ({ id: x[0], why: 'w' })), garbled: quoteItems(call.prompt).map(x => x[0]) }), 'garbled']]) {
    const { out } = await run(baseArgs(), responder({ Quotes }))
    const q = out.counts.quotes
    check(q[field].length === q.items && q.items > 0 && !q.dropped.length && out.nodes.some(n => n.status === 'leaf'), `quotes(${name}): 確かめていない写しの数え方が違う ${JSON.stringify(q)}`)
  }
  // 3b. 照合の役がコマンドを打てなかった（字を足した写しが許しの規則に拒まれた。check-world の取り直しで PR 2560 の回し直し）なら、
  // 訳を添えて 1 回だけ頼み直す。2 回とも打てなければ、確かめていない件数と訳（uncheckedWhy）に出す
  {
    const DENIED = { ran: false, checked: 0, missing: [], garbled: [], error: 'Permission to use Bash was denied' }
    let d = 0
    const { out, calls } = await run(baseArgs(), responder({ Quotes: call => (++d === 1 ? DENIED : quotesOk(call)) }))
    const qs = of(calls, 'Quotes')
    check(qs.length === 2 && qs[1].label === 'Quotes 1 again' && qs[1].prompt.includes('## Why you are asked again') && qs[1].prompt.includes('Permission to use Bash was denied')
      && !qs[0].prompt.includes('## Why you are asked again') && qs[0].prompt.includes('no redirection such as 2>&1') && quoteLine(qs[0].prompt) === quoteLine(qs[1].prompt),
      `quotes(again): 打てなかった照合を、訳を添えて同じコマンドで 1 回だけ頼み直さない ${qs.length} 回`)
    check(out.counts.quotes.checked === out.counts.quotes.items && !out.counts.quotes.unchecked.length && !out.counts.quotes.uncheckedWhy.length,
      `quotes(again): 頼み直した照合の結果が使われない ${JSON.stringify(out.counts.quotes)}`)
    const twice = await run(baseArgs(), responder({ Quotes: () => DENIED }))
    const q2 = twice.out.counts.quotes
    check(of(twice.calls, 'Quotes').length === 2 && q2.unchecked.length === q2.items && q2.items > 0
      && q2.uncheckedWhy.length === 1 && /^Quotes 1: \d+ quotes not checked, not run \(Permission to use Bash was denied\)$/.test(q2.uncheckedWhy[0]),
      `quotes(again): 2 回とも打てなかった照合が、確かめていない件数と訳に出ない ${JSON.stringify(q2)}`)
    // 打てたが数が合わない束は頼み直さない（写しで行が落ちた。訳は数の違い）
    const short = await run(baseArgs(), responder({ Quotes: call => ({ ...quotesOk(call), checked: 0 }) }))
    check(of(short.calls, 'Quotes').length === 1 && /checked 0 of \d+$/.test(short.out.counts.quotes.uncheckedWhy[0] ?? ''),
      `quotes(again): 数の合わない束を頼み直したか、訳が出ない ${JSON.stringify(short.out.counts.quotes)}`)
  }
  // 4. prep.quoteCheck が無い: 段を飛ばし、全部を確かめていない件数に出す
  {
    const a = baseArgs(); delete a.prep.quoteCheck
    const { out, calls } = await run(a, responder())
    check(!of(calls, 'Quotes').length && out.counts.quotes.unchecked.length === out.counts.quotes.items && out.counts.stages.Quotes.skipped.length === 1,
      'quotes(noPrep): 照合の道具が無いのに照合したか、件数に出ない')
  }
  // 5. 件数が多いときは束に分けて並べる。web のページ（line 0）の写しは送らず、それが残る末端は落とさない。日本語の写しは \uXXXX で送る
  {
    const W6 = call => leaf(nodeId(call.prompt), { evidence: [{ path: 'https://example.org/doc', line: 0, quote: 'Exact sentence.' },
      { path: 'b.py', line: 9, quote: `日本語 ${nodeId(call.prompt)}` }] })
    const { out, calls } = await run(baseArgs({ limits: { quoteBatch: 2 } }), responder({ W6, Quotes: missingWhere(x => x[1] === 'b.py') }))
    const qs = of(calls, 'Quotes'), items = qs.flatMap(c => quoteItems(c.prompt))
    check(qs.length === Math.ceil(items.length / 2) && qs.length > 1 && items.every(x => x[1] !== 'https://example.org/doc') && items.some(x => x[3].startsWith('日本語'))
      && qs.every(c => /^[\x00-\x7f]*$/.test(c.prompt.split('```bash')[1])), `quotes(batch): 束の分け方か送る行が違う ${qs.length} ${items.length}`)
    check(out.nodes.filter(n => n.result !== null).every(n => n.status === 'leaf' || n.depth > 0) && out.nodes.filter(n => out.roots.includes(n.id)).every(n => n.status === 'leaf' && n.evidence.length === 1),
      'quotes(batch): web の写しが残る末端を確かめていない物にした')
  }
}

// ---- 段の文（設計 2・3）: attention/prompts/<名>.md から生成器（attention/scripts/gen-prompts.mjs）が script の区画を作る ----
// 1) 区画が md から作り直した物と同じ（作り直し忘れを止める）。2) md ごとに和訳（<名>.ja.md）が在り、その source_sha256 が英語の md の
// sha256 と合う（英語だけを直すと赤）。3) 段の文の定数は区画の中にだけ在る。4) 生成器が、宣言の無い変数・使わない変数・知らないフィルタ・
// 閉じない {{#if}} を止め、生成した関数が足りない値で投げる
async function casePrompts() {
  // Windows では import() に絶対パスを渡すと ERR_UNSUPPORTED_ESM_URL_SCHEME で落ちる（ドライブ名をスキームと読む）。file:// の URL にして渡す（run 44231855113）
  const gen = await import(pathToFileURL(path.join(ROOT, 'attention/scripts/gen-prompts.mjs')).href)
  for (const p of gen.check()) fails.push(`prompts: ${p}`)
  const names = gen.promptNames()
  for (const n of ['RULES', 'SMELL_QUESTIONS', 'W1_PROMPT', 'W2_PROMPT', 'W3_PROMPT', 'W4_PROMPT', 'W5_REMOVE_PREMISE',
    'W6_SHARED', 'W6_PROMPT', 'W7_PROMPT', 'W8_PROMPT', 'W9_PROMPT', 'W10_PROMPT'])
    check(names.includes(n), `prompts: attention/prompts/${n}.md が無い`)
  const lines = SRC.split('\n')
  const a = lines.indexOf(gen.START), b = lines.indexOf(gen.END)
  check(a >= 0 && b > a, 'prompts: 段の文の区画の印が無い')
  const outside = [...lines.slice(0, Math.max(a, 0)), ...lines.slice(b + 1)].join('\n')
  const stray = [...outside.matchAll(/^const (\w+) =/gm)].map(m => m[1]).filter(n => names.includes(n) || /_PROMPT$|^RULES$/.test(n))
  check(!stray.length, `prompts: 段の文の定数が区画の外に在る ${stray}`)
  // 生成器の止め方: 一時の置き場に壊した md を置いて作らせる
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'prompts-'))
  try {
    const bad = {
      undeclared: ['---\nvars:\n  a: text\n---\n{{a}} {{b}}\n', 'is not declared'],
      unused: ['---\nvars:\n  a: text\n  b: list\n---\n{{a}}\n', 'declared but never used'],
      filter: ['---\nvars:\n  a: list\n---\n{{a|upper}}\n', 'unknown or malformed filter'],
      unclosed: ['---\nvars:\n  a: text\n---\n{{#if a}}x {{a}}\n', 'without {{/if}}'],
    }
    for (const [what, [body, want]] of Object.entries(bad)) {
      const dir = path.join(tmp, what)
      fs.mkdirSync(dir)
      fs.writeFileSync(path.join(dir, 'X.md'), body)
      const { problems } = gen.generate(dir)
      check(problems.some(p => p.includes(want)), `prompts: 生成器が ${what} を止めない ${JSON.stringify(problems)}`)
    }
    // 英語だけを直すと和訳の照合が赤になる
    const dir = path.join(tmp, 'stale')
    fs.mkdirSync(dir)
    fs.writeFileSync(path.join(dir, 'X.md'), '---\nvars:\n---\nHello.\n')
    fs.writeFileSync(path.join(dir, 'X.ja.md'), `---\nsource_sha256: ${gen.sha256('---\nvars:\n---\nHello.\n')}\n---\nこんにちは。\n`)
    check(!gen.translationProblems(dir).length, `prompts: 合っている和訳を赤にした ${gen.translationProblems(dir)}`)
    fs.writeFileSync(path.join(dir, 'X.md'), '---\nvars:\n---\nHello again.\n')
    check(gen.translationProblems(dir).some(p => p.includes('changed after the translation')), 'prompts: 英語だけを直したのに和訳の照合が赤にならない')
  } finally { fs.rmSync(tmp, { recursive: true, force: true }) }
  // 写した観点（works-factory）: 台帳は 19 本 × 2 ファイルを過不足なく並べ、各ファイルが在って sha256 が合い、script の LENSES は 19 本で、
  // 載せない見出し（How to report・Example・Works well with）を含まない
  const LENS_NAMES = ['purpose-apart-from-means', 'zero-based-design', 'general-structure-compare', 'ground-every-departure', 'check-against-practice',
    'learn-target-conventions', 'what-counts-as-policy', 'prior-decisions-check', 'change-minimality', 'code-hygiene-review', 'test-double-fidelity',
    'citation-provenance', 'remeasure-premises', 'reinvention-check', 'recount-blind-premise', 'review-finding-bar', 'fix-now-smallest-first',
    'when-to-ask-a-person', 'objection-rejudge']
  const ledger = gen.readLedger()
  check(/^[0-9a-f]{40}$/.test(ledger.commit), `prompts: COPIED_FROM の 1 行目が commit でない ${ledger.commit}`)
  const want = LENS_NAMES.flatMap(n => [`perspectives/${n}/SKILL.md`, `perspectives/${n}/SKILL.ja.md`]).sort()
  check(JSON.stringify(ledger.files.map(e => e.rel).sort()) === JSON.stringify(want), `prompts: COPIED_FROM の一覧が 19 本 × 2 ファイルと違う（${ledger.files.length} 行）`)
  for (const e of ledger.files) {
    const p = path.join(ROOT, 'attention', e.rel)
    if (!fs.existsSync(p)) { fails.push(`prompts: ${e.rel} が無い`); continue }
    check(crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex') === e.sha, `prompts: ${e.rel} の sha256 が COPIED_FROM と違う`)
  }
  const lensBlock = lines.slice(a, b + 1).join('\n')
  const lensObj = new Function(`${lensBlock}\nreturn LENSES`)()
  check(JSON.stringify(Object.keys(lensObj)) === JSON.stringify([...LENS_NAMES].sort()), `prompts: LENSES の名前が 19 本と違う ${Object.keys(lensObj)}`)
  for (const [n, t] of Object.entries(lensObj))
    check(typeof t === 'string' && t.startsWith('### ') && !/^#{1,6}\s+(How to report|Example|Works well with)/m.test(t) && !/^#{1,2} /m.test(t), `prompts: LENSES の ${n} の見出しが決まりと違う`)
  // 生成した関数は、足りない値・型の違う値で投げる（「undefined」を文に混ぜない）
  const block = lines.slice(a, b + 1).join('\n')
  const fns = new Function(`${block}\nreturn { W4_PROMPT, W10_PROMPT }`)()
  const throws = f => { try { f(); return false } catch { return true } }
  check(throws(() => fns.W4_PROMPT({ prFiles: 'F' })) && throws(() => fns.W10_PROMPT({ prFiles: 'F', quoted: 'yes', text: 't' })),
    'prompts: 生成した関数が足りない値か型の違う値で投げない')
}

// ---- 反証の 2 つの目（設計 3 の W10）: 末端と臭いの答えに、誤検出を示す目と、具体の筋書きを組む目を 1 体ずつ立て、
// 票の組み方で決める（2 体とも崩せない→stands・2 体とも崩す→falls・割れる→suspected・票が欠ける→unverifiable）。
// 指摘にならない物の一覧（NOT_A_FINDING）が見つける段と反証の両方に載り、行と写しの無い指摘は指摘にしない ----
async function caseRefute() {
  const isRoot = q => q.startsWith('[s11.2]') || q.startsWith("The PR's structure differs")
  const ok = (extra = {}) => ({ verdict: 'stands', reason: 'r', evidence: [{ path: 'a.py', line: 1, quote: 'x' }], ...extra })
  // 1. 体の数・目ごとの文・スキーマ
  {
    const { out, calls } = await run(baseArgs(), responder())
    const w10 = of(calls, 'W10'), leafT = out.nodes.filter(n => n.verdict).length, smellT = out.smells.filter(x => x.verdict).length
    const fixT = out.fixes.verdicts.length
    check(w10.length === 2 * (leafT + smellT) + fixT && leafT > 0 && smellT > 0 && fixT > 0,
      `refute: W10 の体の数が 2×(末端 ${leafT}+臭い ${smellT})+案 ${fixT} でない ${w10.length}`)
    const tr = w10.filter(c => c.label.endsWith(' trace'))
    check(tr.length === leafT + smellT && tr.every(c => c.opts.schema.required.includes('scenario') && c.prompt.includes('Construct the concrete scenario'))
      && w10.filter(c => /^W10 [LS]\d+$/.test(c.label)).every(c => !c.opts.schema.required.includes('scenario') && c.prompt.includes('false positive'))
      && w10.filter(c => /^W10 F\d+$/.test(c.label)).every(c => c.prompt.includes('how the world builds the same thing'))
      && !w10.some(c => /^W10 [FG]\d+ /.test(c.label)), 'refute: 目ごとの文かスキーマが違うか、案に 2 つ目の目が立った')
    const doctrine = 'It is already prevented elsewhere'
    check([...w10.filter(c => !/^W10 [FG]\d/.test(c.label)), ...of(calls, 'W4'), ...of(calls, 'W6'), ...of(calls, 'Lines')].every(c => c.prompt.includes(doctrine)) && of(calls, 'W6').every(c => c.prompt.includes('if you cannot point at the line, it is not a finding')),
      'refute: 指摘にならない物の一覧が、見つける段か反証のどれかに載らない')
    check(out.nodes.filter(n => n.verdict).every(n => n.verdict.verdict === 'stands' && n.verdict.lenses.length === 2 && n.verdict.scenario),
      `refute: 2 体とも崩せない末端が stands にならない ${JSON.stringify(out.nodes.find(n => n.verdict)?.verdict)}`)
  }
  // 2. 票の組み方。末端 1 つ（ルートの 1 本目）にだけ答えを替え、ほかは stands のまま
  const combos = [
    ['split', ok({ verdict: 'falls' }), ok({ problem: true, scenario: 'in a, out b' }), 'suspected'],
    ['bothFall', ok({ verdict: 'falls' }), ok({ verdict: 'falls', problem: true, scenario: '' }), 'falls'],
    ['traceNull', ok(), null, 'unverifiable'],
    ['traceCannot', ok(), ok({ verdict: 'unverifiable', problem: true, scenario: '', evidence: [] }), 'unverifiable'],
    ['noScenario', ok(), ok({ problem: true, scenario: '' }), 'unverifiable'],
    ['bothNull', null, null, null],
  ]
  for (const [name, refuteV, traceV, want] of combos) {
    let target = null
    const W6 = call => {
      const id = nodeId(call.prompt)
      if (!target && isRoot(nodeQ(call.prompt))) target = id
      return leaf(id)
    }
    // the target leaf is the first root; it becomes ledger item L1 (items follow the order of the nodes)
    const W10 = call => {
      const [, id, lens] = call.label.split(' ')
      if (id === 'L1') return lens === 'trace' ? traceV : refuteV
      return ok(lens === 'trace' ? { problem: true, scenario: 'in a, out b' } : {})
    }
    const { out } = await run(baseArgs(), responder({ W6, W10 }))
    const n = out.nodes.find(x => x.id === target), v = n?.verdict
    check(itemOf(out, target)?.id === 'L1', `refute(${name}): 1 本目のルートが台帳の L1 にならない`)
    check((v?.verdict ?? null) === want && (want === null || (v.lenses.length === 2 && v.reason.includes('refute: ') && v.reason.includes('trace: '))),
      `refute(${name}): 票の組み方が ${want} でない ${JSON.stringify(v)}`)
    // a fallen finding is not handed to W9 (stage 14); the item stays in the ledger with its verdict
    const toW9 = of((await run(baseArgs(), responder({ W6, W10 }))).calls, 'W9')[0].prompt.includes('- L1 [')
    check(toW9 === (want !== 'falls') && itemOf(out, target)?.verdict?.verdict === v?.verdict, `refute(${name}): 崩れた項目だけが直しの案に渡らないのでない`)
    const s = out.counts.seenUndecided
    check(s.refuteSuspected.includes('L1') === (want === 'suspected') && s.refuteUnverifiable.includes('L1') === (want === 'unverifiable'),
      `refute(${name}): 件数に出ない ${JSON.stringify(s)}`)
  }
  // 3. 行と写しの無い指摘: 写しの無い臭いの答えは確かめていない物にして反証しない。問題だと言う末端に行と写しが無ければ unverifiable
  {
    let target = null
    const W4 = call => ({ verdict: 'smell', answer: 'A', evidence: call.label === 'W4 smell 1' ? [{ path: 'a.py', line: 0, quote: '' }] : [{ path: 'a.py', line: 2, quote: 'y' }] })
    const W6 = call => {
      const id = nodeId(call.prompt)
      if (!target && isRoot(nodeQ(call.prompt))) { target = id; return leaf(id, { evidence: [{ path: 'a.py', line: 0, quote: '' }] }) }
      return leaf(id)
    }
    const { out, calls } = await run(baseArgs(), responder({ W4, W6 }))
    check(out.smells[0].answer.verdict === 'unverified' && !calls.some(c => /^W10 S1( |$)/.test(c.label)) && calls.some(c => c.label === 'W10 S2')
      && out.counts.quotes.noQuote.includes('S1') && out.counts.quotes.toUnverified.includes('S1'), `refute(noQuote): 写しの無い臭いの答えを反証した ${JSON.stringify(out.counts.quotes)}`)
    const n = out.nodes.find(x => x.id === target)
    check(n?.status === 'leaf' && n.verdict?.verdict === 'unverifiable' && out.counts.seenUndecided.refuteUnverifiable.includes(itemOf(out, target)?.id),
      `refute(noQuote): 行と写しの無い、問題だと言う末端が unverifiable にならない ${JSON.stringify(n?.verdict)}`)
    // 問題だと言わない末端（見つからなかった、など）は、行と写しが無くても 2 体の票で決める
    const W10 = call => ok(call.label.endsWith(' trace') ? { problem: false, scenario: 'searched a, found nothing' } : {})
    const { out: o2 } = await run(baseArgs(), responder({ W4, W6: call => { const id = nodeId(call.prompt); return leaf(id, { evidence: [] }) }, W10 }))
    const judged = o2.nodes.filter(x => x.verdict)
    check(judged.length > 0 && judged.every(x => x.verdict.verdict === 'stands'), `refute(noQuote): 問題だと言わない、写しの無い末端まで unverifiable にした（判定の付いた末端 ${judged.length} 件）`)
    // 問題だと言うのに写しの無い末端でも、2 体とも崩したら「崩れた」（確かめられないに上書きしない）
    const W10f = call => ok(call.label.endsWith(' trace') ? { verdict: 'falls', problem: true, scenario: '' } : { verdict: 'falls' })
    const W6b = call => { const id = nodeId(call.prompt); return id === target ? leaf(id, { evidence: [{ path: 'a.py', line: 0, quote: '' }] }) : leaf(id) }
    const { out: o3 } = await run(baseArgs(), responder({ W4, W6: W6b, W10: W10f }))
    const n3 = o3.nodes.find(x => x.id === target)
    check(n3?.verdict?.verdict === 'falls', `refute(noQuote): 2 体とも崩した、写しの無い末端を崩れたにしない ${JSON.stringify(n3?.verdict)}`)
  }
  // 4. 使い回し: 2 つの目の票（lenses）の無い前の回の判定は持ち越さず、もう一度 2 体で反証する
  {
    const { out } = await run(baseArgs(), responder())
    const prior = { ...out, nodes: out.nodes.map(n => (n.verdict ? { ...n, verdict: { verdict: n.verdict.verdict, reason: 'r', evidence: n.verdict.evidence } } : n)) }
    const a = baseArgs({ priorRecord: prior })
    a.prep = { ...a.prep, priorHead: 'p'.repeat(40), fingerprints: { 'a.py': 'same' } }
    const { calls } = await run(a, responder())
    check(of(calls, 'W6').length === 0 && of(calls, 'W10').filter(c => /^W10 [LN]\d+ trace$/.test(c.label)).length > 0, 'refute(reuse): 2 つの目の無い前の判定を持ち越した')
    const { out: o2, calls: c2 } = await run({ ...a, priorRecord: out }, responder())
    const carried = o2.nodes.filter(x => x.verdict?.lenses?.length === 2)
    check(of(c2, 'W6').length === 0 && carried.length > 0 && of(c2, 'W10').filter(c => /^W10 [LN]\d/.test(c.label)).length === 0,
      `refute(reuse): 2 つの目の決まった判定を持ち越さない（持ち越した末端 ${carried.length} 件）`)
  }
}

// ---- 17 段の流れ（attention/docs/my-turn-dig-redesign.md）で足した段 ----
const isRootQ = q => q.startsWith('[s11.2]') || q.startsWith("The PR's structure differs")
// 段 1: 目的から手段を抜き、手段の語が目的か種類に漏れたら 1 回だけ問い直す。PR の主張は区分 9 のルートになる
async function casePurpose() {
  {
    const { out, calls } = await run(baseArgs(), responder())
    const p = of(calls, 'Purpose')
    check(p.length === 1 && p[0].prompt.includes('Fix the purpose before the work, apart from the means') && p[0].opts.model === 'opus',
      'purpose: 目的の段が 1 体で、観点の文と表のモデルで立たない')
    check(out.purpose?.purpose === 'keep the records consistent' && out.kind === 'a kind of system' && out.counts.meansLeak.length === 0, `purpose: 記録に目的が載らない ${JSON.stringify(out.purpose)}`)
    const w2 = of(calls, 'W2')[0].prompt
    check(w2.includes('keep the records consistent') && w2.includes('a kind of system') && !w2.includes('hand-made checker'), 'purpose: 遮断の目に目的と種類だけが渡らない')
    check(JSON.stringify(out.general.design) === JSON.stringify([{ id: 'D1', element: 'one store', adds: 'a store', removes: 'the checker' }]) && out.general.questionStands === true,
      'purpose: ゼロからの設計が記録に載らない')
    check(of(calls, 'W3')[0].prompt.includes('one store') && of(calls, 'W3')[0].prompt.includes('hand-made checker'), 'purpose: 比べる段にゼロの設計と手段が渡らない')
    // PR の主張（claims）は区分 9 のルートになり、区分 1 の後・区分 2 の前に並ぶ
    const roots = out.nodes.filter(n => out.roots.includes(n.id))
    const claim = roots.find(n => n.rootClass === 9)
    check(claim && claim.question.includes('The PR says: "no tool does this"') && claim.question.includes('a.py:1'), 'purpose: 主張が区分 9 のルートにならない')
    const rank = roots.map(n => n.rootClass)
    const at9 = rank.indexOf(9)
    check(rank.slice(0, at9).every(c => c === 1) && rank.slice(at9).every(c => c !== 1), `purpose: 区分 9 のルートの並びが違う ${rank}`)
  }
  // 手段の語（a.py）が目的に漏れた: 漏れた語を添えて 1 回だけ問い直し、直った答えを使う
  {
    let n = 0
    const Purpose = () => (++n === 1 ? { purpose: 'keep a.py consistent', means: ['a hand-made checker in a.py'], kind: 'K', claims: [] }
      : { purpose: 'keep the records consistent', means: ['a hand-made checker in a.py'], kind: 'K', claims: [] })
    const { out, calls } = await run(baseArgs(), responder({ Purpose }))
    const p = of(calls, 'Purpose')
    check(p.length === 2 && p[1].label === 'Purpose again' && p[1].prompt.includes('a.py') && p[1].prompt.includes('Rewrite purpose and kind without them')
      && out.purpose.purpose === 'keep the records consistent' && out.counts.meansLeak.length === 0, `purpose(leak): 漏れた語で問い直さない ${p.length}`)
    // 2 回目も漏れた: それ以上は問わず、漏れた語を数えに残す
    const { out: o2, calls: c2 } = await run(baseArgs(), responder({ Purpose: () => ({ purpose: 'keep a.py consistent', means: ['a.py'], kind: 'K', claims: [] }) }))
    check(of(c2, 'Purpose').length === 2 && JSON.stringify(o2.counts.meansLeak) === '["a.py"]', `purpose(leak): 2 回目も漏れたのに数えに残らない ${JSON.stringify(o2.counts.meansLeak)}`)
  }
  // 目的の段が返らない: 比べる段（W2・W3）は飛ばし、訳を残す。ほかの段は回る
  {
    const { out, calls } = await run(baseArgs(), responder({ Purpose: () => null }))
    check(!out.stopped && of(calls, 'W2').length === 0 && of(calls, 'W3').length === 0 && out.general.why === 'no purpose'
      && out.counts.stages.W2.skipped.length === 1 && out.purpose === null && of(calls, 'W6').length > 0, `purpose(null): 目的が無いのに比べたか、ほかの段まで止めた ${out.general.why}`)
  }
}
// 段 5: 観点の目。いつも立つ 6 つと、身元の印・標準が 2 つ以上のときだけ立つ 2 つ。段 0 の値が目に渡る
async function caseEyes() {
  const a = baseArgs()
  a.prep = { ...a.prep, identitySignals: [{ path: 'a.py', line: 3, text: 'if user == "admin":' }],
    lines: { byClass: { impl: { added: 10, deleted: 0, files: 1 }, test: { added: 30, deleted: 2, files: 2 } }, testToImpl: 3.2 },
    deletedTests: { files: ['tests/old.py'], names: [{ path: 'tests/t.py', name: 'test_x' }], uncounted: [] } }
  const W1 = call => ({ ...responder()(call), standards: ['MCP', 'OAuth 2.0'] })
  const W4 = call => (call.label === 'W4 eye hygiene' ? { verdict: 'none', answer: 'nothing', evidence: [{ path: 'a.py', line: 1, quote: '' }], findingKind: 'none', locations: [], cost: '' }
    : { verdict: 'smell', answer: 'A', evidence: [{ path: 'a.py', line: 2, quote: 'y' }], findingKind: 'upkeep', locations: [{ path: 'a.py', line: 2, quote: 'y' }], cost: 'two places to change' })
  const { out, calls } = await run(a, responder({ W1, W4 }))
  const eye = name => calls.find(c => c.label === `W4 eye ${name}`)
  check(['rules', 'prior', 'minimal', 'hygiene', 'ratio', 'tests', 'privilege', 'standards'].every(eye), `eyes: 目が全部立たない ${of(calls, 'W4').map(c => c.label)}`)
  check(eye('privilege').prompt.includes('a.py:3 if user == "admin":') && eye('standards').prompt.includes('MCP, OAuth 2.0'), 'eyes: 身元の印か標準が目に渡らない')
  check(eye('ratio').prompt.includes('impl +10 -0 (1 files); test +30 -2 (2 files)') && eye('ratio').prompt.includes('3.2'), 'eyes: 行数の区分が比の目に渡らない')
  check(eye('minimal').prompt.includes('keep the records consistent') && eye('tests').prompt.includes('tests/t.py: test_x') && eye('tests').prompt.includes('tests/old.py (whole file)'),
    'eyes: 目的か消した試験が目に渡らない')
  check(eye('rules').prompt.includes('Lenses for this stage') && eye('rules').opts.schema.required.includes('findingKind'), 'eyes: 目に観点の文か指摘の項目が無い')
  const s = out.smells.find(x => x.eye === 'hygiene')
  check(s && s.question.startsWith('Lens eye hygiene: ') && of(calls, 'W8')[0].prompt.includes('Lens eyes that found nothing: hygiene'), 'eyes: 何も見つけなかった目が W8 に渡らない')
  // 種類が breakage でない臭いの答えは、2 つ目の反証が筋書きでなく費用を数える
  const upkeep = out.smells.find(x => x.eye === 'rules')
  check(calls.some(c => c.label === `W10 ${upkeep.id} cost`) && !calls.some(c => c.label === `W10 ${upkeep.id} trace`), 'eyes: breakage でない臭いに費用の反証が立たない')
  // 身元の印が無く、標準が 1 つ: 2 つの目は立たない
  const { calls: c2 } = await run(baseArgs(), responder({ W1: call => ({ ...responder()(call), standards: ['MCP'] }) }))
  check(!c2.some(c => c.label === 'W4 eye privilege' || c.label === 'W4 eye standards'), 'eyes: 条件の無い目が立った')
}
// 段 9: 確かめられなかったノードを、前の答えを手がかりに 1 回だけ掘り直す。分かれる答えは取らない
async function caseRedig() {
  for (const [name, again, want] of [['settle', id => leaf(id), 'leaf'], ['split', id => split(id, ['more']), 'unverified'], ['null', () => null, 'unverified']]) {
    let target = null
    const W6 = call => {
      const id = nodeId(call.prompt)
      if (!target && isRootQ(nodeQ(call.prompt))) { target = id; return leaf(id, { status: 'unverified', answer: 'EARLIER-ANSWER', evidence: [], worth: 'undecided' }) }
      return leaf(id)
    }
    const { out, calls } = await run(baseArgs(), responder({ W6, Redig: call => again(nodeId(call.prompt)) }))
    const r = of(calls, 'Redig'), n = out.nodes.find(x => x.id === target)
    check(r.length === 1 && r[0].label === `Redig ${target}` && r[0].prompt.includes('EARLIER-ANSWER') && r[0].opts.model === 'sonnet', `redig(${name}): 掘り直しの体か手がかりが違う ${r.length}`)
    check(n?.status === want && n.redug === (name === 'settle') && out.counts.redig.asked === 1 && out.counts.redig.settled === (name === 'settle' ? 1 : 0),
      `redig(${name}): 掘り直しの結果の取り方が違う ${n?.status} ${JSON.stringify(out.counts.redig)}`)
    check(out.counts.repairs.redigSplit.includes(target) === (name === 'split'), `redig(${name}): 分かれた答えが直しの件数に出ない`)
    check(out.nodes.length === new Set(out.nodes.map(x => x.id)).size && !out.nodes.some(x => x.question === 'more'), `redig(${name}): 掘り直しで子を足した`)
    // 掘り直しても決まらないノードは台帳に「確かめていない」で載り、反証しない
    const it = itemOf(out, target)
    check(name === 'settle' ? it?.state === 'finding' : (it?.state === 'unverified' && !calls.some(c => c.label === `W10 ${it.id}`)), `redig(${name}): 台帳の状態が違う ${it?.state}`)
  }
}
// 段 11・12: 台帳。同じ種類で同じ在り処の指摘は畳み、「直さなくてよい」の末端は前提を数え直し、崩れたら開き直す
async function caseLedger() {
  {
    const W6 = call => leaf(nodeId(call.prompt), { locations: [{ path: './a.py', line: 5, quote: 'x' }] })
    const { out, calls } = await run(baseArgs(), responder({ W6 }))
    const leaves = out.nodes.filter(n => n.status === 'leaf')
    const items = out.ledger.filter(it => it.state === 'finding')
    check(items.length === 1 && items[0].from.length === leaves.length && leaves.length > 1 && items[0].locations.length === 1, `ledger(fold): 同じ在り処の指摘が 1 件に畳まれない ${items.length}`)
    check(of(calls, 'W10').filter(c => /^W10 L\d+$/.test(c.label)).length === 1 && calls.find(c => c.label === 'W10 L1').prompt.includes(`The same finding also came from ${items[0].from.slice(1).join(', ')}`),
      'ledger(fold): 畳んだ項目の反証が 1 体で、畳んだ元を示さない')
    check(leaves.every(n => n.verdict?.verdict === items[0].verdict?.verdict), 'ledger(fold): 畳んだ末端に項目の判定が載らない')
  }
  {
    // 在り処が同じでも種類が違えば畳まない。breakage でない種類は費用の反証で、費用の無い「成り立つ」は票にならない
    let k = 0
    const W6 = call => leaf(nodeId(call.prompt), { findingKind: ++k % 2 ? 'breakage' : 'upkeep', cost: 'two places', locations: [{ path: 'a.py', line: 5, quote: 'x' }] })
    const W10 = call => ({ verdict: 'stands', reason: 'r', evidence: [{ path: 'a.py', line: 1, quote: 'x' }],
      ...(call.label.endsWith(' trace') ? { problem: true, scenario: 's', cost: '' } : {}), ...(call.label.endsWith(' cost') ? { problem: true, scenario: '', cost: '' } : {}) })
    const { out, calls } = await run(baseArgs(), responder({ W6, W10 }))
    const items = out.ledger.filter(it => it.state === 'finding')
    const up = items.find(it => it.findingKind === 'upkeep'), br = items.find(it => it.findingKind === 'breakage')
    check(items.length === 2 && up && br, `ledger(kind): 種類の違う指摘を畳んだ ${items.map(it => it.findingKind)}`)
    check(calls.some(c => c.label === `W10 ${up.id} cost`) && !calls.some(c => c.label === `W10 ${up.id} trace`) && calls.some(c => c.label === `W10 ${br.id} trace`),
      'ledger(kind): 種類ごとの 2 つ目の反証が違う')
    check(up.verdict?.verdict === 'unverifiable' && br.verdict?.verdict === 'stands' && out.counts.stages.W10.empty.some(e => e.label === `W10 ${up.id} cost` && e.field === 'cost'),
      `ledger(kind): 費用の無い費用の反証を票に数えた ${up.verdict?.verdict}`)
  }
  {
    // 「直さなくてよい」の末端: 台帳に載せず、誤検出の目と前提の数え直しの目で反証する。2 体とも崩したら開き直す
    let target = null
    const W6 = call => {
      const id = nodeId(call.prompt)
      if (!target && isRootQ(nodeQ(call.prompt))) { target = id; return leaf(id, { worth: 'fine', finePremise: 'PREMISE-FINE', findingKind: 'none' }) }
      return leaf(id)
    }
    for (const [name, v, reopened] of [['stands', 'stands', false], ['falls', 'falls', true]]) {
      const W10 = call => (call.label.startsWith(`W10 ${target}`) ? { verdict: v, reason: 'r', evidence: [{ path: 'a.py', line: 1, quote: 'x' }] }
        : responder()(call))
      target = null
      const { out, calls } = await run(baseArgs(), responder({ W6, W10 }))
      const rc = calls.find(c => c.label === `W10 ${target} recount`)
      check(rc && rc.prompt.includes('PREMISE-FINE') && rc.prompt.includes('Lenses for this stage') && calls.some(c => c.label === `W10 ${target}`), `ledger(fine ${name}): 前提の数え直しが立たない`)
      const it = itemOf(out, target)
      check(reopened ? (it?.state === 'reopened' && it.route !== 'draft' && it.verdict?.verdict === 'falls') : !it, `ledger(fine ${name}): 開き直しが違う ${it?.state}`)
    }
  }
}
// 段 13: 線引き。番号の取り違え・畳む先の無い畳み・決まりを挙げない落とし・下書きにならない物を、コードが直す
async function caseLines() {
  const base = await run(baseArgs(), responder())
  const ids = base.out.ledger.map(it => it.id)
  check(ids.length >= 4, `lines: 試験に足りる項目が無い ${ids.length}`)
  const [a, b, c, d] = ids
  const entry = (id, route, extra = {}) => ({ id, label: 'l', level: 'design', route, into: '', why: 'w', rule: '', ...extra })
  const Lines = () => ({ items: [entry(a, 'draft'), entry(a, 'report'), entry(b, 'fold', { into: a }), entry(c, 'drop'), entry('L99', 'report'),
    entry(d, 'draft', { level: 'detail' })] })
  const { out, calls } = await run(baseArgs(), responder({ Lines }))
  const it = id => out.ledger.find(x => x.id === id)
  const R = out.counts.repairs.lines
  check(of(calls, 'Lines').length === 1 && of(calls, 'Lines')[0].prompt.includes(`- ${a} [breakage; finding; refute: stands]`), 'lines: 線引きの段に台帳が渡らない')
  check(it(a).route === 'draft' && R.duplicate.includes(a), `lines: 下書きか、2 度目の番号の扱いが違う ${it(a).route}`)
  check(it(b).route === 'fold' && it(b).into === a, 'lines: 畳む先のある畳みを崩した')
  check(it(c).route === 'report' && R.dropNoRule.includes(c), 'lines: 決まりを挙げずに、崩れていない指摘を落とした')
  check(R.unknown.includes('L99'), 'lines: 無い番号が件数に出ない')
  check(it(d).route === 'report' && it(d).level === 'detail' && R.draftToReport.includes(d), 'lines: 細部の breakage を下書きにした（下書きは設計の段だけ）')
  check(ids.slice(4).every(id => it(id).route === 'report' && R.missing.includes(id)), 'lines: 線を引かなかった項目が出さないで残る')
  // 下書きは、設計の段の指摘で、2 体とも崩せず、筋書きか費用のある物だけ。確かめられない判定の項目は出すだけにする
  const W10 = call => (call.label === `W10 ${a} trace` ? { verdict: 'unverifiable', reason: 'r', evidence: [], problem: true, scenario: '', cost: '' } : responder()(call))
  const { out: o2 } = await run(baseArgs(), responder({ Lines, W10 }))
  check(o2.ledger.find(x => x.id === a).route === 'report' && o2.counts.repairs.lines.draftToReport.includes(a), 'lines: 確かめられない項目を下書きにした')
  // 畳む先が無い・自分を指す畳みは出すだけにする。保守・自作・消せるの種類は細部にしない
  const W6 = call => leaf(nodeId(call.prompt), { findingKind: 'upkeep', cost: 'c' })
  const Lines3 = () => ({ items: [entry(a, 'fold', { into: a }), entry(b, 'fold', { into: 'L77' }), entry(c, 'report', { level: 'detail' })] })
  const { out: o3 } = await run(baseArgs(), responder({ W6, Lines: Lines3 }))
  const R3 = o3.counts.repairs.lines
  check(R3.badFold.includes(a) && R3.badFold.includes(b) && o3.ledger.find(x => x.id === a).route === 'report'
    && R3.detailToDesign.includes(c) && o3.ledger.find(x => x.id === c).level === 'design', `lines: 畳みの直しか段の直しが違う ${JSON.stringify(R3)}`)
  // 落とす件へ畳む: 指摘が落とした件に消えないよう、出すだけにする
  const Lines5 = () => ({ items: [entry(a, 'fold', { into: b }), entry(b, 'drop', { rule: 'r' })] })
  const { out: o5 } = await run(baseArgs(), responder({ Lines: Lines5 }))
  check(o5.counts.repairs.lines.badFold.includes(a) && o5.ledger.find(x => x.id === a).route === 'report', 'lines: 落とす件へ畳んだ指摘を出さない')
  // 線引きの段が返らない: 全部を出すだけにする
  const { out: o4 } = await run(baseArgs(), responder({ Lines: () => null }))
  check(o4.counts.repairs.lines.allReport && o4.ledger.every(x => x.route === 'report') && !o4.linesReturned, 'lines(null): 返らないのに全部を出すにしない')
}
// 段 14・15: 直しの案は台帳の番号を指し、崩れた案は外しても指摘は残る。まとまり（group）は 1 件ずつ判定する
async function caseFixes() {
  const base = await run(baseArgs(), responder())
  const [a, b, c] = base.out.ledger.map(it => it.id)
  const W9 = () => ({ fixes: [{ fix: 'FA', rung: 'remove', worldSolution: 'https://example.org/a', items: `${a}, L99` }, { fix: 'FB', rung: 'tool', worldSolution: 'https://example.org/b', items: b },
      { fix: 'FC', rung: 'tool', worldSolution: 'https://example.org/c', items: 'L98' }],
    groups: [{ kind: 'one-fix', members: `F1, ${b}`, why: 'w' }, { kind: 'one-fix', members: `${a}, ${b}, ${c}`, why: 'w' }], searched: 's', outside: [] })
  const W10 = call => {
    if (call.label === 'W10 F1') return { verdict: 'falls', reason: 'not the practice', evidence: [{ path: 'https://example.org/a', line: 0, quote: 'q' }] }
    if (call.label === 'W10 G2') return { verdict: 'stands', reason: 'r', evidence: [{ path: 'a.py', line: 1, quote: 'x' }],
      members: [{ id: a, verdict: 'accept', reason: 'r' }, { id: b, verdict: 'accept', reason: 'r' }, { id: c, verdict: 'falls', reason: 'not settled by it' }] }
    return responder()(call)
  }
  const { out, calls } = await run(baseArgs(), responder({ W9, W10 }))
  const it = id => out.ledger.find(x => x.id === id)
  check(out.fixes.fixes[0].itemIds.join() === a, `fixes: 案の番号に無い番号が残った ${out.fixes.fixes[0].itemIds}`)
  check(out.fixes.removed.some(f => f.id === 'F1' && f.why === 'refuted') && it(a) && it(a).fixes.length === 0 && JSON.stringify(it(b).fixes) === '["F2"]',
    `fixes: 崩れた案で指摘まで消えたか、指摘の案が違う ${JSON.stringify(out.fixes.removed)}`)
  check(calls.find(c => c.label === 'W10 G1').opts.schema.required.includes('members') && calls.find(c => c.label === 'W10 F2').prompt.includes('how the world builds the same thing'),
    'fixes: まとまりと案の反証の形が違う')
  check(out.fixes.removed.some(f => f.id === 'G1' && f.why.startsWith('fewer than two members')), `fixes: 崩れた案を抜いたら 1 件になったまとまりを残した ${JSON.stringify(out.fixes.removed)}`)
  const g2 = out.fixes.groups.find(g => g.id === 'G2')
  check(g2.members === `${a}, ${b}` && JSON.stringify(g2.dropped) === JSON.stringify([c]) && !out.fixes.removed.some(f => f.id === 'G2'), `fixes: まとまりから崩れた 1 件だけを抜かない ${JSON.stringify(g2)}`)
  check(out.fixes.verdicts.length === 4 && out.fixes.verdicts.every(v => v.verdict), 'fixes: 案とまとまりの判定が記録に載らない')
  check(out.fixes.removed.some(f => f.id === 'F3' && f.why.startsWith('rests on no ledger item')) && !of(calls, 'W10').some(c => c.label === 'W10 F3'),
    `fixes: 台帳の件に乗らない案を外さないか、反証に回した ${JSON.stringify(out.fixes.removed)}`)
  check(out.fixes.removed.find(f => f.id === 'G1')?.fix === `one-fix: F1, ${b}`, `fixes: 外したまとまりの元の組が記録に残らない ${JSON.stringify(out.fixes.removed)}`)
  // 直す件が無い: 直し方の段を立てずに飛ばす
  const W6 = call => leaf(nodeId(call.prompt), { worth: 'fine', finePremise: 'p' })
  const { out: o2, calls: c2 } = await run(baseArgs(), responder({ W6 }))
  check(of(c2, 'W9').length === 0 && o2.counts.stages.W9?.skipped?.length === 1 && o2.fixes.fixes.length === 0, `fixes: 直す件が無いのに直し方の段を立てた ${of(c2, 'W9').length}`)
}

const CASES = { dedup: caseDedup, refute: caseRefute, fixed: caseFixed, grow: caseGrow, same: caseSame, allot: caseAllot, skips: caseSkips, schema: caseSchema, map: caseMap, rests: caseRests, quotes: caseQuotes, prompts: casePrompts,
  purpose: casePurpose, eyes: caseEyes, redig: caseRedig, ledger: caseLedger, lines: caseLines, fixes: caseFixes }
const name = process.argv[2]
if (!CASES[name]) { console.log(`使い方: node tests/my-turn-dig-dry.mjs <${Object.keys(CASES).join('|')}>`); process.exit(1) }
try { await CASES[name]() } catch (e) { fails.push(`${name}: 例外 ${e?.stack ?? e}`) }
if (fails.length) { console.log(fails.join('\n')); process.exit(1) }
console.log(`${name.toUpperCase()}_OK`)
