// attention/workflows/my-turn-dig.js を、agent() などを偽物に替えて node で空回しする（設計 attention/docs/my-turn-workflow-design.md の 11）。
// 使い方: node tests/my-turn-dig-dry.mjs <case>   case は fixed・grow・same・skips・allot・map・schema・rests。通れば <CASE>_OK を出す。
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SCRIPT = path.join(ROOT, 'attention/workflows/my-turn-dig.js')
const SRC = fs.readFileSync(SCRIPT, 'utf8')
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
  const calls = []
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
  const out = await fn(agent, parallel, pipeline, () => {}, () => {}, args, { total: null, spent: () => 0, remaining: () => Infinity },
    async () => { throw new Error('workflow() is not used') })
  return { out, calls }
}

const HEAD = 'h'.repeat(40)
const baseArgs = (extra = {}) => ({
  pr: 7, repo: 'o/r', workdir: '/w', stance: 'reviewer', now: '2026-11-17T00:00:00Z',
  prep: { base: 'b'.repeat(40), head: HEAD, base7: 'bbbbbbb', diff: '/rd/bbbbbbb..hhhhhhh.diff', recordDir: '/rd',
    commits: ['c'.repeat(40)], changed: ['a.py', 'CLAUDE.md'], excluded: [], claudeMdChanged: true,
    rules: [{ path: 'CLAUDE.md', show: 'git show bbbbbbb:CLAUDE.md' }], fingerprints: {} },
  files: { record: '/rd/7.json', thread: '/rd/7-thread.md', justifications: '/rd/7-just.md' },
  blindJudge: 'convergence-loops:blind-judge',
  ...extra,
})
const ROLE_KEYS = ['W1', 'W2', 'W3', 'W4', 'W6', 'W7', 'W8', 'W9', 'W10answers', 'W10fixes', 'W11']
const ROLES = Object.fromEntries(ROLE_KEYS.map(k => [k, `my-turn-${k}`]))

const nodeId = p => (p.match(/## Your node (N\d+)/) ?? [])[1]
const nodeQ = p => p.split('hand to children only questions whose answer would change yours):\n')[1] ?? ''
const leaf = (id, extra = {}) => ({ answer: `ANSWER-${id}`, checked: { files: ['a.py'], commands: [], urls: [] },
  evidence: [{ at: 'a.py:1', quote: 'x' }], parts: [], premises: [`PREMISE-${id}`], status: 'leaf', children: [], ...extra })
const split = (id, qs) => leaf(id, { status: 'split', evidence: [],
  children: qs.map(q => ({ question: q, howParentChanges: 'flips it', weight: 'big', where: 'a.py' })) })
const byText = items => ({ clusters: Object.values(items.reduce((m, [id, q]) => { (m[q] ??= { key: q, question: q, ids: [] }).ids.push(id); return m }, {}))
  .map(c => ({ key: c.key, question: c.question, members: c.ids.join(', ') })), dropped: [] })
const w7Items = p => [...p.matchAll(/^- (q\d+): (.*?) \| /gm)].map(m => [m[1], m[2]])
const recordOf = p => JSON.parse(p.slice(p.indexOf('\n\n{') + 2))

// 既定の答え。over[stage] で替える
function responder(over = {}) {
  const w8 = { n: 0 }
  return (call, calls) => {
    const { label, prompt } = call
    const stage = label.split(' ')[0]
    if (over[label]) return over[label](call, calls)
    if (over[stage]) return over[stage](call, calls, w8)
    switch (stage) {
      case 'W1': return { structure: 'parts A and B', kind: 'a kind of system', mechanisms: [{ mechanism: 'M1', premise: 'P1' }],
        selfMade: [{ part: 'checker', files: 'a.py', why: 'hand list' }], extraSmells: [], hiddenChoices: ['Where is the truth?'],
        noParts: false, noPartsReason: '' }
      case 'W2': return { general: 'GENERAL', notFound: false }
      case 'W3': return { comparable: true, whyNotComparable: '', diffs: [{ diff: 'D', decision: 'align', basis: 'industry', ifThreeMore: '' }] }
      case 'W4': return { verdict: label === 'W4 smell 1' ? 'smell' : 'none', answer: 'A', evidence: [{ at: 'a.py:2', quote: label === 'W4 smell 1' ? 'y' : '' }] }
      case 'W6': return leaf(nodeId(prompt))
      case 'W7': return byText(w7Items(prompt))
      case 'W8': return { gaps: [], reason: 'compared against the structure' }
      case 'W9': {
        const ids = [...prompt.matchAll(/^- (N\d+): /gm)].map(m => m[1])
        return { fixes: [{ fix: 'F', rung: 'remove', worldSolution: 'https://example.org', leaves: ids.join(',') }], groups: [], searched: 'words', outside: [] }
      }
      case 'W10': return { verdict: 'stands', reason: 'r', evidence: [{ at: 'a.py:1', quote: 'x' }] }
      case 'W11': { const r = recordOf(prompt); return { wrote: true, nodeCount: r.nodes.length, head: r.head } }
    }
    throw new Error(`unknown label ${label}`)
  }
}
const of = (calls, stage) => calls.filter(c => c.label.split(' ')[0] === stage)

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
  check(out.recordWritten === true && out.recordPath === '/rd/7.json', 'fixed: 記録の照合が通らない')
  // 段ごとに渡したモデルを数えに残す（ヘッドレスの形の台本が、使われなかったモデルを回った段だけで数える）
  check(JSON.stringify(out.counts.stages.W6.models) === '["sonnet"]' && JSON.stringify(out.counts.stages.W1.models) === '["opus"]'
    && out.recordModel === 'haiku', `fixed: 段のモデルが数えに無い ${JSON.stringify(out.counts.stages.W6)}`)
  // W4: 固定の 5 問と、足した 4 問のうち上限 3 問
  check(of(calls, 'W4').length === 8, `fixed: W4 の体数 ${of(calls, 'W4').length}（5+3 のはず）`)
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
  // W9 と W10 と W11 にノードの返りが欠けずに渡る
  const leaves = out.nodes.filter(n => n.status === 'leaf')
  const w9 = of(calls, 'W9')[0]
  for (const n of leaves) check(w9.prompt.includes(`- ${n.id}: `) && w9.prompt.includes(`ANSWER-${n.id}`), `fixed: W9 に ${n.id} が渡らない`)
  for (const n of leaves) check(calls.some(c => c.label === `W10 ${n.id}`), `fixed: ${n.id} の反証が立たない`)
  check(of(calls, 'W10').filter(c => /^W10 S\d+$/.test(c.label)).length === 8, 'fixed: 臭いの答えの反証が 8 体でない')
  check(calls.some(c => c.label === 'W10 F1'), 'fixed: 直しの案の反証が立たない')
  const rec = recordOf(of(calls, 'W11')[0].prompt)
  // W11 だけは記録を書く段: 共通の決まりの「読むだけ」を、記録のファイルだけ書く決まりに替える
  const w11p = of(calls, 'W11')[0].prompt, w6p = of(calls, 'W6')[0].prompt
  check(!w11p.includes('- Read only.') && w11p.includes('- Write only the record file') && w6p.includes('- Read only.'),
    'fixed: W11 に読むだけの決まりが残るか、ほかの段から消えた')
  check(rec.nodes.length === out.nodes.length && rec.nodes.every(n => n.status !== 'pending'), 'fixed: W11 の記録にノードが欠ける')
  // W8: 新しい抜けは区分 8 のルートになり、既に在る問いは seen で落ちる。2 回続けて空で止まる
  const gap = out.nodes.find(n => n.question === 'GAP new')
  check(gap && gap.rootClass === 8 && gap.parents.length === 0, 'fixed: W8 の抜けが区分 8 のルートにならない')
  check(out.gapRounds.length === 3, `fixed: W8 の回数 ${out.gapRounds.length}（抜け 1 回 + 空 2 回）`)
  const outcomes = out.gapRounds[0].gaps.map(g => g.outcome).sort().join(',')
  check(outcomes === 'dug,seen', `fixed: W8 の抜けの行き先 ${outcomes}`)
  check(out.nodes.filter(n => n.question === 'D2 deep').length === 1, 'fixed: seen に在る問いがもう一度掘られた')
  // 段のモデル・既定の形（roles 無し）・CLAUDE.md の書き足し・W2 に PR を渡さない
  const model = s => of(calls, s)[0]?.opts.model
  check(model('W1') === 'opus' && model('W6') === 'sonnet' && model('W11') === 'haiku' && model('W4') === 'sonnet', 'fixed: 段のモデルが表と違う')
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
  // 反証と書いた段が同じモデル: 1 体も立てずに止まる
  {
    const { out: o3, calls: c3 } = await run(baseArgs({ models: { W10answers: { model: 'sonnet' } } }), responder())
    check(o3.stopped && c3.length === 0, 'fixed/same-model: 反証が書いた段と同じモデルでも止まらない')
  }
  // W11 が null でも材料が返る
  {
    const { out: o4 } = await run(baseArgs(), responder({ W11: () => null }))
    check(o4.recordWritten === false && o4.recordPath === null && o4.recordError && o4.nodes?.length > 0, 'fixed/W11-null: 材料が返らない')
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
    const W6 = () => leaf('x', { checked: { files: ['a.py'], commands: [], urls: [] }, evidence: [{ at: 'ddddddd:CLAUDE.md:2', quote: 'q' }] })
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
    check(of(c7, 'W10').filter(c => /^W10 N/.test(c.label)).length === 0, 'fixed/reuse: 使い回した末端の反証をやり直した')
    // 前の回に確かめられなかった判定（unverifiable）は持ち越さず、もう一度反証する
    const shaky = baseArgs({ priorRecord: { ...out, nodes: out.nodes.map(n => (n.verdict ? { ...n, verdict: { ...n.verdict, verdict: 'unverifiable' } } : n)) } })
    shaky.prep = same.prep
    const { calls: c7b } = await run(shaky, responder({ W6: tree, W8, W1 }))
    check(out.nodes.some(n => n.verdict) && of(c7b, 'W10').filter(c => /^W10 N/.test(c.label)).length > 0, 'fixed/reuse: 確かめられなかった判定を持ち越した')
    const moved = baseArgs({ priorRecord: prior })
    moved.prep = { ...moved.prep, priorHead: 'p'.repeat(40), fingerprints: { 'a.py': 'moved' } }
    const { calls: c8 } = await run(moved, responder({ W6: tree, W8, W1 }))
    check(of(c8, 'W6').length > 0, 'fixed/reuse: 指紋が変わったのに W6 を立てない')
    const missing = baseArgs({ priorRecord: prior })
    missing.prep = { ...missing.prep, priorHead: 'p'.repeat(40), priorHeadMissing: true, fingerprints: { 'a.py': 'moved' } }
    const { calls: c9 } = await run(missing, responder({ W6: tree, W8, W1 }))
    check(of(c9, 'W6').length > 0 && of(c9, 'W2').length === 1, 'fixed/reuse: 前の回の head が無いのに使い回した')
    // 記録のフォルダの差分は数えず、thread（毎回書き直す）を読んだノードは使い回さない
    const withFile = f => ({ ...out, nodes: out.nodes.map(n => ({ ...n, checked: { ...n.checked, files: [...(n.checked?.files ?? []), f] } })) })
    // 差分を読んだノードは、差分の本文が前の回と同じとき（prep.diffSame）だけ使い回す
    const allSame = { 'a.py': 'same', 'CLAUDE.md': 'same' }
    const diffArgs = baseArgs({ priorRecord: withFile('/rd/bbbbbbb..ppppppp.diff') })
    diffArgs.prep = { ...same.prep, fingerprints: allSame, diffSame: true, priorRunDiff: 'bbbbbbb..ppppppp.diff' }
    const { calls: c10 } = await run(diffArgs, responder({ W6: tree, W8, W1 }))
    check(of(c10, 'W6').length === 0, 'fixed/reuse: 記録のフォルダの差分を読んだだけで使い回さなくなった')
    // 使い回したノードの差分のファイルは、今の回の 1 本目（本文が同じ）を指し直す。次の回でも使い回せるように
    const { out: o10 } = await run(diffArgs, responder({ W6: tree, W8, W1 }))
    check(o10.nodes.every(n => !(n.checked?.files ?? []).includes('/rd/bbbbbbb..ppppppp.diff'))
      && o10.nodes.some(n => (n.checked?.files ?? []).includes('/rd/bbbbbbb..hhhhhhh.diff')), 'fixed/reuse: 使い回したノードが前の回の差分のファイルを指したまま')
    // 根拠（evidence の at）に挙げた差分のファイルも、今の回の 1 本目を指し直す
    const withEv = at => ({ ...out, nodes: out.nodes.map(n => ({ ...n, evidence: [...(n.evidence ?? []), { at, quote: 'q' }] })) })
    const evDiff = baseArgs({ priorRecord: withEv('/rd/bbbbbbb..ppppppp.diff:12') })
    evDiff.prep = diffArgs.prep
    const { out: o10h, calls: c10h } = await run(evDiff, responder({ W6: tree, W8, W1 }))
    check(of(c10h, 'W6').length === 0 && o10h.nodes.some(n => (n.evidence ?? []).some(e => e.at === '/rd/bbbbbbb..hhhhhhh.diff:12'))
      && !o10h.nodes.some(n => (n.evidence ?? []).some(e => e.at === '/rd/bbbbbbb..ppppppp.diff:12')), 'fixed/reuse: 根拠の差分の位置を指し直さない')
    // 行の無い在り処（差分のファイルだけ）も、checked.files と同じく今の回の 1 本目を指し直す
    const evBare = baseArgs({ priorRecord: withEv('/rd/bbbbbbb..ppppppp.diff') })
    evBare.prep = diffArgs.prep
    const { out: o10l } = await run(evBare, responder({ W6: tree, W8, W1 }))
    check(o10l.nodes.some(n => (n.evidence ?? []).some(e => e.at === '/rd/bbbbbbb..hhhhhhh.diff'))
      && !o10l.nodes.some(n => (n.evidence ?? []).some(e => e.at === '/rd/bbbbbbb..ppppppp.diff')), 'fixed/reuse: 行の無い根拠の差分を指し直さない')
    // 記録のフォルダの path に $ が在っても（$1・$& は置き換えの印）、そのままの綴りで指し直す
    const dollar = baseArgs({ priorRecord: withEv('/r$1$&d/bbbbbbb..ppppppp.diff:12') })
    dollar.prep = { ...diffArgs.prep, recordDir: '/r$1$&d', diff: '/r$1$&d/bbbbbbb..hhhhhhh.diff' }
    const { out: o10j } = await run(dollar, responder({ W6: tree, W8, W1 }))
    check(o10j.nodes.some(n => (n.evidence ?? []).some(e => e.at === '/r$1$&d/bbbbbbb..hhhhhhh.diff:12')), 'fixed/reuse: $ を含む path を指し直しで崩した')
    // 反証の根拠のファイルが変わった末端は、使い回しても判定を持ち越さず、もう一度反証する
    const vMoved = baseArgs({ priorRecord: { ...out, nodes: out.nodes.map(n => (n.verdict ? { ...n, verdict: { ...n.verdict, evidence: [{ at: 'b.py:3', quote: 'q' }] } } : n)) } })
    vMoved.prep = { ...same.prep, fingerprints: { ...allSame, 'b.py': 'moved' } }
    const { calls: c10k } = await run(vMoved, responder({ W6: tree, W8, W1 }))
    check(of(c10k, 'W6').length === 0 && of(c10k, 'W10').filter(c => /^W10 N/.test(c.label)).length > 0, 'fixed/reuse: 反証の根拠が変わったのに判定を持ち越した')
    // 根拠に挙げただけのファイル（checked.files に無い）も読んだ物に数え、指紋が変われば使い回さない
    const evMoved = baseArgs({ priorRecord: withEv('b.py:10') })
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
    const withUrlDiff = { ...out, nodes: out.nodes.map(n => ({ ...n, checked: { ...n.checked, urls: ['https://x'] }, parts: ['/rd/bbbbbbb..ppppppp.diff'] })) }
    const urlDiff = baseArgs({ priorRecord: withUrlDiff })
    urlDiff.prep = { ...same.prep, fingerprints: allSame, diffSame: false }
    const { calls: c10e } = await run(urlDiff, responder({ W6: tree, W8, W1 }))
    check(of(c10e, 'W6').length > 0, 'fixed/reuse: parts の差分が変わったのに URL のノードを使い回した')
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
    const vDiff = baseArgs({ priorRecord: { ...out, nodes: out.nodes.map(n => (n.verdict ? { ...n, verdict: { ...n.verdict, evidence: [{ at: '/rd/bbbbbbb..ppppppp.diff:5', quote: 'q' }] } } : n)) } })
    vDiff.prep = diffArgs.prep
    const { out: o10v, calls: c10v } = await run(vDiff, responder({ W6: tree, W8, W1 }))
    const vAts = o10v.nodes.flatMap(n => (n.verdict?.evidence ?? []).map(e => e.at))
    check(of(c10v, 'W10').filter(c => /^W10 N/.test(c.label)).length === 0 && vAts.includes('/rd/bbbbbbb..hhhhhhh.diff:5')
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
  // W7 が既にノードの在る問いを落とした・束の key が落とした問いで、問いの文がノードの在る問い: どちらもそのノードに畳む
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
      if (q === 'D1 shared') return split(id, ['A known'])
      return leaf(id)
    }
    const { out: o } = await run(baseArgs(), responder({ W6: W6k, W7: W7k }))
    const d1 = o.nodes.find(x => x.question === 'D1 shared'), a = o.nodes.find(x => x.question === 'A known')
    check(d1?.status === 'split' && a?.alsoFrom.includes(d1.id), `rests(${shape}): ノードの在る問いに畳まず、split を掘られていない物にした ${d1?.status}`)
  }
  // W7 の 1 回の答えの中で、同じ問いを束ねた物と落とした物が並ぶ・束の key が短い正規の語・key が祖先で問いの文が別のノード
  const W6f = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['P1 q', 'P2 q', 'Is X safe', 'Y other'])
    if (q === 'P1 q') return leaf(id, { status: 'split', evidence: [], children: [{ question: 'SAME q', howParentChanges: 'flips it', weight: 'small', where: 'a.py' }] })
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
    const same = items.filter(([, q]) => q === 'SAME q')
    if (shape === 'sameBatch') return { clusters: [{ key: 'SAME q', question: 'SAME q', members: same[0][0] }], dropped: same.slice(1).map(([id]) => ({ id, why: 'already asked' })) }
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
    if (q === 'P1 q') return split(id, ['Is X safe'])
    return leaf(id)
  }
  const { out: of2, calls: calls2 } = await run(baseArgs(), responder({ W6: W6c, W7: foldW7('canon') }))
  const xs = of2.nodes.filter(x => x.question === 'Is X safe'), p1c = of2.nodes.find(x => x.question === 'P1 q')
  // W7 には短い key の問いの文も見せる（新しい問いを文で既に在るノードに当てられるように）
  const shown = calls2.some(c => c.label.startsWith('W7') && c.prompt.includes('- canon k | asks: Is X safe'))
  check(shown && xs.length === 1 && xs[0].key === 'canon k' && xs[0].alsoFrom.includes(p1c?.id) && p1c?.status === 'split',
    `rests(canon): 短い key のノードに問いの文で当たらない ${JSON.stringify(xs.map(x => [x.key, x.alsoFrom]))} ${p1c?.status}`)
  // key が祖先の問い、問いの文が別のノード: 輪にせず、別のノードに畳む
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
  check(y && d1y && y.alsoFrom.includes(d1y.id) && d1y.status === 'split' && !of3.counts.repairs.foldIntoOwnLine.length,
    `rests(keyAncestor): 祖先の key に当てて、畳める別のノードを見逃した ${d1y?.status} ${JSON.stringify(of3.counts.repairs.foldIntoOwnLine)}`)
  // key と問いの文が別々のノードに当たる束: 親ごとに、輪にならない方に畳む（P1 x は A q の下なので B q へ、
  // P2 x は Z q の下なので先に当たる A q へ）
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
  check(pn('P1 x')?.status === 'split' && pn('P2 x')?.status === 'split' && pn('B q')?.alsoFrom.includes(pn('P1 x')?.id)
    && pn('A q')?.alsoFrom.includes(pn('P2 x')?.id) && !of4.counts.repairs.foldIntoOwnLine.length,
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
  const child = (q, weight) => ({ question: q, howParentChanges: 'flips it', weight, where: 'a.py' })
  const W6s = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['P1 q', 'P2 q'])
    if (q === 'P1 q') return leaf(id, { status: 'split', evidence: [], children: [child('K one', 'small')] })
    if (q === 'P2 q') return leaf(id, { status: 'split', evidence: [], children: [child('K two', 'big')] })
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
  // 2 つの束を橋渡しする束（key が片方、問いの文がもう片方）: 3 つを 1 つのノードにし、どの束の key でも後で当たる
  const W6b = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['P1 q', 'P2 q', 'P3 q'])
    if (/^P\d q$/.test(q)) return split(id, [`x${q[1]}`])
    if (q === 'a q') return split(id, ['b q'])
    return leaf(id)
  }
  const W7b = call => {
    const items = w7Items(call.prompt), q = x => items.find(([, t]) => t === x)?.[0]
    if (!q('x1')) return byText(items)
    return { clusters: [{ key: 'a q', question: 'a q', members: q('x1') }, { key: 'b q', question: 'b q', members: q('x2') },
      { key: 'a q', question: 'b q', members: q('x3') }], dropped: [] }
  }
  const { out: ob } = await run(baseArgs(), responder({ W6: W6b, W7: W7b }))
  const ab = ob.nodes.filter(x => ['a q', 'b q'].includes(x.question))
  check(ab.length === 1 && ab[0].parents.length === 3 && ob.counts.repairs.foldIntoOwnLine.length === 1,
    `rests(bridge): 橋渡しの束で 1 つのノードにならない ${JSON.stringify(ab.map(x => [x.question, x.parents]))} ${JSON.stringify(ob.counts.repairs.foldIntoOwnLine)}`)
  // 落とした問いが束に入り、その束が自分の祖先の問い: どちらの件数にも出し、親を確かめていない物にする
  const W6o = call => {
    const id = nodeId(call.prompt), q = nodeQ(call.prompt)
    if (isRoot(q)) return split(id, ['D1 shared'])
    if (q === 'D1 shared') return split(id, ['E mid'])
    if (q === 'E mid') return split(id, ['D1 shared', 'D1 shared'])
    return leaf(id)
  }
  let w7o = 0
  const W7o = call => {
    const items = w7Items(call.prompt), ds = items.filter(([, q]) => q === 'D1 shared')
    if (++w7o !== 3) return byText(items)   // the third W7 sees E mid's two children
    return { clusters: [{ key: 'D1 shared', question: 'D1 shared', members: ds[0][0] }], dropped: [{ id: ds[1][0], why: 'already asked' }] }
  }
  const { out: oo } = await run(baseArgs(), responder({ W6: W6o, W7: W7o }))
  const eo = oo.nodes.find(x => x.question === 'E mid')
  check(eo?.status === 'unverified' && oo.counts.repairs.foldIntoOwnLine.length === 1 && oo.counts.repairs.droppedKnown.length === 1,
    `rests(dropOwnLine): 落として祖先の束に入った問いが件数と印に出ない ${eo?.status} ${JSON.stringify(oo.counts.repairs)}`)
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
  check(out.recordWritten, 'grow: 記録が書けない')
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
  const { out: o2 } = await run(baseArgs(), responder({ W6, W7 }))
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
    'W4 smell 3': () => ({ verdict: 'none', answer: '', evidence: [{ at: 'a.py:1', quote: '' }] }),
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
  check(of(calls, 'W4').length === 5, 'skips: W1 が臭いを足さないのに W4 の 5 問が全部立たない')
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

const CASES = { fixed: caseFixed, grow: caseGrow, same: caseSame, allot: caseAllot, skips: caseSkips, schema: caseSchema, map: caseMap, rests: caseRests }
const name = process.argv[2]
if (!CASES[name]) { console.log(`使い方: node tests/my-turn-dig-dry.mjs <${Object.keys(CASES).join('|')}>`); process.exit(1) }
try { await CASES[name]() } catch (e) { fails.push(`${name}: 例外 ${e?.stack ?? e}`) }
if (fails.length) { console.log(fails.join('\n')); process.exit(1) }
console.log(`${name.toUpperCase()}_OK`)
