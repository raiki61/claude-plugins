// attention/workflows/dig-world.js（世界の解の DW）を、agent() などを偽物に替えて node で空回しする（設計 attention/docs/small-workflows-design.md の 3）。
// 使い方: node tests/dig-world-dry.mjs <case>   case は stops・flow・restate・search・compare・texts・banned・excerpts・prep・copies・score。通れば <CASE>_OK を出す。
// Python を使うケース（banned・excerpts・prep・copies・score と flow の sum）は、環境変数 PY_BIN の Python（無ければ python3）で打つ。
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SCRIPT = path.join(ROOT, 'attention/workflows/dig-world.js')
const WORLD = path.join(ROOT, 'attention/steps/world')
const PREP = path.join(ROOT, 'attention/scripts/steps-prep.py')
const PY = process.env.PY_BIN || 'python3'
// Windows の clone（core.autocrlf=true）でも行で読む検査が合うよう、LF へそろえる
const read = p => fs.readFileSync(p, 'utf8').replace(/\r\n/g, '\n')
const SRC = read(SCRIPT)
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
    for (const k of Object.keys(props)) if (!(schema.required ?? []).includes(k)) out.push(`${where}: ${k} が required に無い`)
    for (const [k, v] of Object.entries(props)) out.push(...schemaProblems(v, `${where}.${k}`))
  }
  if (schema.type === 'array') out.push(...schemaProblems(schema.items, `${where}[]`))
  return out
}
async function run(args, respond) {
  const calls = [], logs = []
  const agent = async (prompt, opts = {}) => {
    const call = { prompt, opts, label: opts.label ?? '', stage: String(opts.label ?? '').split(' ')[0] }
    calls.push(call)
    const bad = schemaProblems(opts.schema)
    if (bad.length) throw new Error(bad.join('; '))
    return respond(call, calls)
  }
  // 本物の Workflow は parallel と pipeline の段の返りを JSON で渡すので、Map などは {} になる（PR 2555 の 1 回目）。同じにする
  const asJson = v => (v === undefined ? null : JSON.parse(JSON.stringify(v)))
  const parallel = thunks => Promise.all(thunks.map(t => Promise.resolve().then(t).then(asJson).catch(() => null)))
  const pipeline = async (items, ...stages) => Promise.all(items.map(async (it, i) => {
    let v = it
    try { for (const s of stages) v = asJson(await s(v, it, i)) } catch (e) { fails.push(`pipeline の段が投げた: ${e.message}`); return null }
    return v
  }))
  const fn = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', BODY)
  const out = await fn(agent, parallel, pipeline, () => {}, m => logs.push(String(m)), args, { total: null, spent: () => 0, remaining: () => Infinity },
    async () => { throw new Error('workflow() is not used') })
  return { out, calls, logs }
}

// script の中の関数を、定義の文を切り出して評価する（中の関数は外から呼べないため）
const defText = (src, name) => {
  const ls = src.split('\n')
  const i = ls.findIndex(l => l.startsWith(`const ${name} =`))
  if (i < 0) return null
  const out = [ls[i]]
  for (let j = i + 1; j < ls.length && /^(\s|\}|\])/.test(ls[j]); j++) out.push(ls[j])
  return out.join('\n')
}
const between = (src, from, to) => {
  const a = src.indexOf(from), b = src.indexOf(to, a + 1)
  return a < 0 || b < 0 ? null : src.slice(a, b)
}
const evalDefs = (text, names) => new Function(`${text}\nreturn { ${names.join(', ')} }`)()
const H = evalDefs(['fnv', 'shq', 'asciiJson'].map(n => defText(SRC, n)).join('\n'), ['fnv', 'shq', 'asciiJson'])
const canonText = between(SRC, 'const canon =', '\n\n')
const { sumOf } = evalDefs(`${defText(SRC, 'fnv')}\n${canonText}`, ['sumOf'])

const py = (code, input) => execFileSync(PY, ['-c', code], { input, encoding: 'utf8' })
// 標準入力は UTF-8 のバイトで読む（Windows の Python は管の標準入力を ANSI のコードページで読み、日本語の args の sum が変わる。main の CI の run 44695969416）
const pySum = a => py(`import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("sp", ${JSON.stringify(PREP)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.args_sum(json.loads(sys.stdin.buffer.read().decode("utf-8"))))`, JSON.stringify(a)).trim()

// ---- 材料 ----
const LINES = [
  { n: 1, where: 'mechanism 1', text: 'A tool adapter in `mcp_tool_wrapper.py` turns InputRequiredResult into a pause of the graph, using @assistant-ui/react cards.', kind: 'mechanism' },
  { n: 2, where: 'mechanism 2', text: 'A resume guard checks that the answer matches the pending call (resume_token).', kind: 'mechanism' },
]
const MEANS = ['HumanInTheLoopMiddleware を使わず自前の止めを作る', '再開の照合を状態機械で持つ']
const DEPS = [
  { name: 'langgraph', version: '1.2.20', ecosystem: 'pypi', imported_by_touched: false },
  { name: '@assistant-ui/react', version: '0.15.32', ecosystem: 'npm', imported_by_touched: false },
]
const XC = { runPython: '/p/run-python.sh', script: '/p/world-excerpts.py' }
const baseArgs = (extra = {}) => {
  const a = { caller: 'attention:check-world', pr: 7, head: 'h'.repeat(40), lines: LINES, purpose: '人の答えを待つ処理を作る',
    means: MEANS, deps: DEPS, deps_note: '', lang: 'Japanese', excerptCheck: XC, ...extra }
  if (!('sum' in extra)) a.sum = sumOf(a)
  return a
}
const PROBLEM = '処理の途中で人の答えが要る対話の仕事で、誰が問いを出すかを決める問題'
const goodClass = (n, extra = {}) => ({ n, problem: PROBLEM, activity: '対話の仕事の設計', proposed: `手段 ${n}`,
  queries: ['how do agent frameworks ask a human for input during a run'], deps: ['langgraph', '@assistant-ui/react'], depsWhy: '', ...extra })
const goodSearch = () => ({
  excerpts: [
    { id: 'x1', url: 'https://docs.example.org/interrupt', excerpt: 'Use interrupt inside a tool to pause and wait for a human answer.' },
    { id: 'x2', url: 'https://ui.example.org/tools', excerpt: 'A tool call can be resumed with the answer the user gave in the UI.' },
    { id: 'x3', url: 'https://product.example.org/ask', excerpt: 'The ask tool lets the model request input from the user directly.' },
  ],
  rows: [
    { kind: 'dependency', name: 'langgraph', version: '1.2.20', layer: 'architecture', practice: 'ツールの中で interrupt を呼んで止める', sources: ['x1'], applies: '対話', not_applies: '', found: true, searched: [] },
    { kind: 'dependency', name: '@assistant-ui/react', version: '0.15.32', layer: 'contract', practice: 'ツールの呼び出しを UI の答えで再開する', sources: ['x2'], applies: '', not_applies: '一度きりの処理', found: true, searched: [] },
    { kind: 'product', name: 'Open WebUI', version: '', layer: 'architecture', practice: '聞く専用のツールを持つ', sources: ['x3'], applies: '', not_applies: '', found: true, searched: [] },
    { kind: 'standard', name: '', version: '', layer: 'contract', practice: '', sources: [], applies: '', not_applies: '', found: false, searched: ['human input standard for agents'] },
  ],
})
// 取り直しの段: コマンドの行を読み、sum を確かめ、kept と dropped を言う（dropIds の id は落とす）
const recheckFrom = (prompt, { dropIds = [], lie = false } = {}) => {
  const words = prompt.match(/^bash \S+ \S+ --b64 (.*)$/m)?.[1]?.split(' ')
  if (!words) return { ran: false, checked: 0, kept: [], dropped: [], garbled: [], over: 0, offline: false, error: 'no command' }
  const [head, ...rows] = words.map(w => JSON.parse(Buffer.from(w, 'base64').toString('utf8')))
  const garbled = rows.filter(r => H.fnv(`${r[0]}\n${r[1]}\n${r[2]}`) !== r[3]).map(r => r[0])
  const ok = rows.filter(r => !garbled.includes(r[0]))
  return { ran: true, checked: lie ? rows.length + 1 : head.count, kept: ok.filter(r => !dropIds.includes(r[0])).map(r => r[0]),
    dropped: ok.filter(r => dropIds.includes(r[0])).map(r => ({ id: r[0], why: '本文に無い' })), garbled, over: 0, offline: false, error: '' }
}
const compareAll = (prompt, verdictOf = () => 'differs') => {
  const rows = [...prompt.matchAll(/^(R\d+|G) \[([^\]]*)\]/gm)].map(m => ({ id: m[1], found: !m[2].includes('nothing found') }))
  const ns = [...prompt.matchAll(/^- line (\d+) \(/gm)].map(m => Number(m[1]))
  return { items: rows.flatMap(r => ns.map(n => {
    const v = r.found ? verdictOf(r.id, n) : 'none'
    return { row: r.id, n, verdict: v, challenge: v === 'differs' ? 'The request does X; the counterpart does Y. Choose Y unless Z.' : '', why: 'w' }
  })) }
}
const happy = (opts = {}) => call => {
  switch (call.stage) {
    case 'Restate': return { classes: LINES.map(l => goodClass(l.n)) }
    case 'Leak': return { items: [...call.prompt.matchAll(/^## Item (\d+)/gm)].map(m => ({ n: Number(m[1]), presupposes: false, why: '' })) }
    case 'Search': return goodSearch()
    case 'Recheck': return recheckFrom(call.prompt, opts.recheck)
    case 'General': return { general: '問いを出す部品と答えを受ける部品を分ける', layer: 'architecture', notFound: false }
    case 'Compare': return compareAll(call.prompt)
  }
  throw new Error(`知らない段 ${call.label}`)
}

const cases = {
  async stops() {
    for (const [what, a, want] of [
      ['caller が無い', baseArgs({ caller: undefined }), 'caller'],
      ['caller が違う', baseArgs({ caller: 'attention:my-turn-deep' }), 'caller'],
      ['sum が違う', baseArgs({ sum: '00000000' }), 'sum'],
      ['値を変えた（sum は前の値）', { ...baseArgs(), purpose: '別の目的' }, 'sum'],
      ['excerptCheck が無い', baseArgs({ excerptCheck: undefined }), 'args'],
      ['行の番号が順でない', baseArgs({ lines: [{ ...LINES[0], n: 2 }] }), 'args'],
      ['漏れの照合が言い直しと同じモデル', baseArgs({ models: { Leak: { model: 'opus' } } }), 'leak model equals restate model'],
    ]) {
      const { out, calls } = await run(a, () => { throw new Error('agent を立てた') })
      check(out?.stopped === want, `${what}: stopped が ${want} でない（${JSON.stringify(out).slice(0, 200)}）`)
      check(calls.length === 0, `${what}: agent を立てた`)
    }
    // 文字列で渡された args も読む
    const { out } = await run(JSON.stringify(baseArgs()), happy())
    check(out?.status === 'ok', `文字列の args: status が ok でない（${out?.status} ${out?.stopped}）`)
  },

  async flow() {
    const args = baseArgs()
    check(pySum(args) === args.sum, `Python の args_sum（${pySum(args)}）と JS の sumOf（${args.sum}）が違う（日本語を含む args）`)
    const roles = { Restate: 'r-restate', Leak: 'r-leak', Search: 'r-search', Recheck: 'r-recheck', General: 'r-general', Compare: 'r-compare' }
    const { out, calls } = await run({ ...args, roles }, happy({ recheck: { dropIds: ['x3'] } }))
    check(out.status === 'ok' && out.ok === true, `status が ok でない: ${out.status} ${out.reason}`)
    check(out.rows.length === 2 && out.missing.length === 0, `行が 2 つでない（${out.rows.length}・missing ${out.missing.length}）`)
    check(out.counts.classes === 1, `同じ問題の 2 行が 1 つの類にならない（${out.counts.classes}）`)
    const r1 = out.rows[0]
    check(r1.class_id === out.rows[1].class_id && /^w-[0-9a-f]{8}$/.test(r1.class_id), `class_id の形か共有が違う: ${r1.class_id}`)
    check(r1.comparisons.length === 5, `比べの行が 5（相手 4 と一般の構造）でない: ${r1.comparisons.length}`)
    const by = k => r1.comparisons.find(c => c.against.kind === k.kind && c.against.name === k.name)
    const lg = by({ kind: 'dependency', name: 'langgraph' })
    check(lg?.basis === 'web' && lg.sources.length === 1 && lg.sources[0].url === 'https://docs.example.org/interrupt', '残った抜き書きの行が web の印と抜き書きを持たない')
    check(lg?.verdict === 'differs' && lg.challenge.length >= 20 && lg.layer === 'architecture', 'differs と challenge と層が行に乗らない')
    const prod = by({ kind: 'product', name: 'Open WebUI' })
    check(prod?.basis === 'knowledge' && prod.sources.length === 0, '落ちた抜き書きだけの行が knowledge にならない')
    const std = by({ kind: 'standard', name: '' })
    check(std?.found === false && std.verdict === 'none' && std.searched.length === 1, '見つからなかった行が none と searched を持たない')
    const g = by({ kind: 'general', name: 'blind' })
    check(g?.basis === 'knowledge' && g.verdict === 'differs', '一般の構造の行が knowledge で比べられていない')
    check(out.excerpts.kept === 2 && out.excerpts.dropped === 1 && out.excerpts.unchecked === 0, `抜き書きの数が違う: ${JSON.stringify(out.excerpts)}`)
    // 段ごとのモデル・役・見せる物
    const st = s => calls.filter(c => c.stage === s)
    check(st('Restate')[0].opts.model === 'opus' && st('Leak')[0].opts.model === 'sonnet' && st('Search')[0].opts.model === 'sonnet'
      && st('Recheck')[0].opts.model === 'haiku' && st('Compare')[0].opts.model === 'opus' && st('General')[0].opts.model === 'opus',
    '段ごとのモデルが設計の 3.9 と違う')
    for (const s of Object.keys(roles)) check(st(s)[0]?.opts.agentType === roles[s], `${s} に役 ${roles[s]} が渡らない`)
    const search = st('Search')[0].prompt
    for (const leak of [LINES[0].text, LINES[1].text, '手段 1', args.purpose, MEANS[0], 'mechanism 1']) {
      check(!search.includes(leak), `探す役に依頼の行・手段・目的が見える: ${leak}`)
    }
    check(search.includes('- langgraph 1.2.20 (pypi)') && search.includes(PROBLEM), '探す役に依存の名と版と類の文が渡らない')
    check(search.includes('Do not put the target\'s names in queries.'), '探す役に検索の決まりが無い')
    const general = st('General')[0].prompt
    check(general.includes(PROBLEM) && !general.includes('langgraph') && !general.includes('手段'), '一般の構造に類の文だけが渡っていない')
    check(!general.includes('Do not use any tool'), '役のある一般の構造に、道具を使うなの足しが付いた（役の本文が持つ）')
    const restate = st('Restate')[0].prompt
    check(restate.includes(LINES[0].text) && restate.includes(MEANS[0]) && restate.includes('- @assistant-ui/react 0.15.32 (npm)'), '言い直しに行・手段・依存が渡らない')
    const compare = st('Compare')[0].prompt
    check(compare.includes('line 1 (mechanism 1): 手段 1') && compare.includes('R1 [dependency langgraph 1.2.20 · architecture · web]'), '比べる役に手段と相手の行が渡らない')
    const rc = st('Recheck')[0].prompt
    // ヘッドレスの許しの規則 Bash(bash <run-python.sh> <台本> --b64 *) に当たる 1 行（here-document は当たらず拒まれた。PR 2555 の 1 回目）
    const cmd = rc.split('\n').filter(l => l.startsWith('bash '))
    check(cmd.length === 1 && cmd[0].startsWith('bash /p/run-python.sh /p/world-excerpts.py --b64 ') && /^[A-Za-z0-9+/= ]+$/.test(cmd[0].slice(cmd[0].indexOf('--b64 ') + 6)),
      `取り直しのコマンドが、許しの規則に当たる 1 行の base64 の形でない: ${cmd[0]?.slice(0, 120)}`)
    // 日本語の字も UTF-8 の base64 で字のまま戻る（台本の b64 は手書き）
    const { b64 } = evalDefs(`${defText(SRC, 'B64')}\n${defText(SRC, 'b64')}`, ['b64'])
    for (const t of ['', 'a', 'ab', 'abc', '聞く専用のツール', '😀 emoji', JSON.stringify(['x1', 'https://e.org/ä', '本文', 'deadbeef'])])
      check(Buffer.from(b64(t), 'base64').toString('utf8') === t && b64(t) === Buffer.from(t, 'utf8').toString('base64'), `b64 が Node の base64 と違う: ${t}`)
    check(out.counts.stages.Restate.models.includes('opus') && out.counts.agents === calls.length, 'counts の段ごとのモデルかエージェントの数が違う')
    // 役の無い一般の構造は、道具を使うなを足す
    const plain = await run(args, happy())
    check(plain.calls.find(c => c.stage === 'General').prompt.includes('Do not use any tool'), '役の無い一般の構造に、道具を使うなが無い')
    check(plain.calls.find(c => c.stage === 'General').opts.agentType === 'general-purpose', '役の無い一般の構造が general-purpose でない')
  },

  async restate() {
    // 1 回目: 行 1 に識別子、行 2 に手段の語。2 回目: 行 2 を漏れの照合が差し戻す。3 回目: 行 2 がまだ差し戻される → missing
    let restates = 0
    const { out, calls } = await run(baseArgs(), call => {
      if (call.stage === 'Restate') {
        restates++
        if (restates === 1) return { classes: [goodClass(1, { problem: 'mcp_tool_wrapper.py の止め方', proposed: '' }), goodClass(2, { queries: ['HumanInTheLoopMiddleware alternatives'] })] }
        return { classes: [goodClass(1), goodClass(2, { problem: '処理を止めて後で再開する仕組みの作り方' })] }
      }
      if (call.stage === 'Leak') {
        return { items: [...call.prompt.matchAll(/^## Item (\d+)/gm)].map(m => ({ n: Number(m[1]), presupposes: m[1] === '2', why: m[1] === '2' ? '「止めて再開」が手段' : '' })) }
      }
      return happy()(call)
    })
    const rs = calls.filter(c => c.stage === 'Restate')
    check(rs.length === 3, `言い直しが 3 回でない: ${rs.length}`)
    check(rs[1].prompt.includes('## Why your previous answer was rejected') && rs[1].prompt.includes('["mcp_tool_wrapper.py"]')
      && rs[1].prompt.includes('words of the means ["HumanInTheLoopMiddleware"]'), '2 回目に識別子と手段の語の差し戻しの訳が無い')
    check(rs[2].prompt.includes('presupposes the means (a second reader): 「止めて再開」が手段') && rs[2].prompt.includes('["mcp_tool_wrapper.py"]'),
      '3 回目に漏れの差し戻しと前の回の訳が残らない')
    check(out.status === 'partial' && out.rows.length === 1 && out.rows[0].n === 1, `行 1 だけ返して partial にならない: ${out.status} ${out.rows.map(r => r.n)}`)
    check(out.missing.length === 1 && out.missing[0].n === 2 && /restate gave up/.test(out.missing[0].why), `行 2 が missing にならない: ${JSON.stringify(out.missing)}`)
    check(out.restate.identifierHits >= 1 && out.restate.meansHits >= 1 && out.restate.leakSentBack === 2 && out.restate.rounds === 3,
      `restate の数えが違う: ${JSON.stringify(out.restate)}`)
    // 1 回目は 2 行とも機械の照合に落ちたので、漏れの照合を立てない
    check(calls.filter(c => c.stage === 'Leak')[0]?.label === 'Leak 2', '機械の照合に落ちた行が漏れの照合に渡った')
    // 第三者の名（依存の名・版・@ の付いた名の段）は識別子に数えない
    const tp = await run(baseArgs(), call => call.stage === 'Restate'
      ? { classes: LINES.map(l => goodClass(l.n, { queries: ['how does langgraph 1.2.20 or assistant-ui/react pause for human input'] })) }
      : happy()(call))
    check(tp.out.status === 'ok', `第三者の名を識別子として差し戻した: ${tp.out.reason} ${JSON.stringify(tp.out.missing)}`)
    // 変えたファイルが import する依存を選ばず、訳も無ければ差し戻す
    const deps = [{ ...DEPS[0], imported_by_touched: true }, DEPS[1]]
    let n = 0
    const im = await run(baseArgs({ deps }), call => {
      if (call.stage === 'Restate') { n++; return { classes: LINES.map(l => goodClass(l.n, { deps: ['@assistant-ui/react'], depsWhy: n === 1 ? '' : '画面の部品だけが関わる' })) } }
      return happy()(call)
    })
    check(n === 2 && im.calls.filter(c => c.stage === 'Restate')[1]?.prompt.includes('depsWhy does not say why'),
      '変えたファイルが import する依存を選ばず訳も無い答えが差し戻されない')
    check(im.out.status === 'ok', `depsWhy を書いた 2 回目が通らない: ${im.out.reason}`)
    // 一覧に無い依存の名は差し戻す
    let k = 0
    const st = await run(baseArgs(), call => {
      if (call.stage === 'Restate') { k++; return { classes: LINES.map(l => goodClass(l.n, { deps: k === 1 ? ['react-query'] : ['langgraph'] })) } }
      return happy()(call)
    })
    check(st.calls.filter(c => c.stage === 'Restate')[1]?.prompt.includes('deps ["react-query"] are not in the dependency list'), '一覧に無い依存の名を差し戻さない')
  },

  async search() {
    // 1 回目: 依存の行が足りない・not_applies に自分の抜き書きが無い・定石に識別子・found false で searched が空・製品の行が無い
    let s = 0
    const { out, calls } = await run(baseArgs(), call => {
      if (call.stage === 'Search') {
        s++
        if (s === 1) {
          const r = goodSearch()
          r.rows = [{ ...r.rows[0], practice: 'resume_token で照合する', not_applies: '小さな仕事', sources: [] },
            { ...r.rows[3], searched: [] }]
          return r
        }
        return goodSearch()
      }
      if (call.stage === 'Recheck') return recheckFrom(call.prompt, { lie: true })
      return happy()(call)
    })
    const ss = calls.filter(c => c.stage === 'Search')
    check(ss.length === 2, `探す役が 2 回でない: ${ss.length}`)
    const p2 = ss[1]?.prompt ?? ''
    for (const want of ['no row with kind dependency and name @assistant-ui/react', 'must cite at least one excerpt of its own',
      'practice has identifiers of the request lines ["resume_token"]', 'found is false, so searched must list', 'no product row']) {
      check(p2.includes(want), `2 回目の訳に「${want}」が無い`)
    }
    // 取り直しの数が送った数と違う（写しの行が落ちた）なら信じず、全部を照合できなかった物にする
    check(out.excerpts.unchecked === 3 && out.excerpts.kept === 0, `数の合わない取り直しを信じた: ${JSON.stringify(out.excerpts)}`)
    const c = out.rows[0].comparisons
    check(c.every(x => x.basis === 'knowledge' && x.sources.length === 0), '照合できなかった抜き書きの行が web の印を持った')
    const ui = c.find(x => x.against.name === '@assistant-ui/react')
    check(ui?.not_applies_unchecked === true, '抜き書きが残らない not_applies に印が付かない')
    check(/excerpts not checked/.test(out.reason), `照合できなかったことが reason に出ない: ${out.reason}`)

    // 依存の行の抜き書きが全部落ちたら 1 回だけ探し直させる
    let t = 0
    const re = await run(baseArgs(), call => {
      if (call.stage === 'Search') { t++; return goodSearch() }
      if (call.stage === 'Recheck') return recheckFrom(call.prompt, { dropIds: t === 1 ? ['x1', 'x2'] : [] })
      return happy()(call)
    })
    const rs = re.calls.filter(c => c.stage === 'Search')
    check(rs.length === 2 && rs[1].prompt.includes('every excerpt cited by the dependency rows was dropped'), '依存の抜き書きが全部落ちても探し直させない')
    check(re.out.excerpts.kept === 3, `探し直した回の抜き書きが使われない: ${JSON.stringify(re.out.excerpts)}`)
    // 7 つ目からの抜き書きは送らずに over に数える
    const many = await run(baseArgs(), call => {
      if (call.stage === 'Search') {
        const r = goodSearch()
        for (let i = 4; i <= 8; i++) r.excerpts.push({ id: `x${i}`, url: `https://e.example.org/${i}`, excerpt: `an excerpt long enough number ${i}` })
        return r
      }
      return happy()(call)
    })
    const sent = many.calls.find(c => c.stage === 'Recheck').prompt.match(/--b64 (.*)$/m)[1].split(' ').slice(1)
    check(sent.length === 6 && many.out.excerpts.over === 2, `抜き書きの上限が 6 でない: 送った ${sent.length}・over ${many.out.excerpts.over}`)
    // 3 回とも受け付けに外れたら、その類の行を missing にする
    const bad = await run(baseArgs(), call => call.stage === 'Search' ? { excerpts: [], rows: [] } : happy()(call))
    check(bad.out.status === 'failed' && bad.out.missing.length === 2 && /search gave up/.test(bad.out.missing[0].why), `探す役が諦めた類が missing にならない: ${bad.out.status}`)
  },

  async compare() {
    let c = 0
    const { out, calls } = await run(baseArgs(), call => {
      if (call.stage === 'Compare') {
        c++
        const r = compareAll(call.prompt)
        if (c === 1) {
          r.items = r.items.filter(i => !(i.row === 'G' && i.n === 2))
          const std = r.items.find(i => i.row === 'R4'); std.verdict = 'same'
          const r1 = r.items.find(i => i.row === 'R1'); r1.challenge = 'short'
        }
        return r
      }
      return happy()(call)
    })
    const cs = calls.filter(x => x.stage === 'Compare')
    check(cs.length === 2, `比べる役が 2 回でない: ${cs.length}`)
    for (const want of ['no entry for row G and line 2', 'verdict must be none (the row found nothing)', 'differs needs a challenge']) {
      check(cs[1]?.prompt.includes(want), `2 回目の訳に「${want}」が無い`)
    }
    check(out.status === 'ok', `2 回目が通らない: ${out.reason}`)
    // 手段の無い行は none だけを受ける
    const nn = await run(baseArgs(), call => {
      if (call.stage === 'Restate') return { classes: LINES.map(l => goodClass(l.n, { proposed: l.n === 2 ? '' : '手段' })) }
      if (call.stage === 'Compare') return compareAll(call.prompt, (row, n) => (n === 2 ? 'none' : 'same'))
      return happy()(call)
    })
    check(nn.out.status === 'ok' && nn.out.rows[1].comparisons.every(x => x.verdict === 'none'), '手段の無い行の none を受けない')
    check(nn.calls.find(x => x.stage === 'Compare').prompt.includes('line 2 (mechanism 2): (none proposed)'), '手段の無い行が比べる役に (none proposed) で渡らない')
    // 3 回とも外れたら missing
    const bad = await run(baseArgs(), call => call.stage === 'Compare' ? { items: [] } : happy()(call))
    check(bad.out.status === 'failed' && bad.out.missing.every(m => /compare gave up/.test(m.why)), '比べる役が諦めた類が missing にならない')
  },

  async texts() {
    // 工場の query-rule.md（1 行目の道具の印と、子を立てるときの区画を除く）と rejected.md が字のまま埋まっている
    const qr = read(path.join(WORLD, 'copied/query-rule.md')).split('\n').slice(1).join('\n')
      .replace(/<!-- if spawns -->\n[\s\S]*?<!-- end spawns -->\n/, '').trim()
    const embedded = between(SRC, 'const QUERY_RULE = `', '`\nconst rejectedBlock')?.slice('const QUERY_RULE = `'.length)
    check(embedded === qr, 'QUERY_RULE が copied/query-rule.md と違う')
    const rj = read(path.join(WORLD, 'copied/rejected.md')).trim()
    const { REJECTED } = evalDefs(between(SRC, 'const REJECTED =', '\n// workflows/.shared/prompts/query-rule.md'), ['REJECTED'])
    check(REJECTED('{rejection}') === rj, 'REJECTED が copied/rejected.md と違う')
    // 重い版と同じ文で写した小さな関数
    const heavy = read(path.join(ROOT, 'attention/workflows/my-turn-dig.js'))
    for (const n of ['fnv', 'shq', 'asciiJson', 'CTRL', 'clean', 'meansWords']) {
      const a = defText(SRC, n), b = defText(heavy, n)
      check(a && a === b, `${n} が my-turn-dig.js の文と違う`)
    }
    // AI に渡す文は英語（日本語の字は、受け付けの訳と固有の語の引用の外に無い）
    const prompts = between(SRC, '// ---- shared prompt parts ----', '// ---- acceptance (3.7) ----')
    check(prompts && !/[぀-ヿ一-鿿]/.test(prompts), '指示文に日本語の字が在る')
    // 起動の合図は台本と DW で同じ
    const prep = read(PREP)
    check(/CALLERS = \["attention:check-world"\]/.test(prep) && /const CALLERS = \['attention:check-world'\]/.test(SRC), 'CALLERS が台本と DW で違う')
    check(/SUM_KEYS = \["lines", "purpose", "means", "deps", "deps_note", "lang"\]/.test(prep)
      && SRC.includes("const SUM_KEYS = ['lines', 'purpose', 'means', 'deps', 'deps_note', 'lang']"), 'SUM_KEYS が台本と DW で違う')
    // meta は純粋な字の並び
    const meta = between(SRC, 'export const meta = {', '\n}\n')
    check(meta && !/\$\{|\.\.\.|\(\)/.test(meta), 'meta が純粋な字の並びでない')
  },

  async banned() {
    // 識別子の取り出し（工場の excerpts.banned_tokens・text_problems の JS への移し）が Python の写しと同じ
    const { bannedTokens, textProblems } = evalDefs(between(SRC, 'const WORD =', '\n// ---- args (3.2) ----'), ['bannedTokens', 'textProblems'])
    const lines = [...LINES, { n: 3, where: 'src/app/ToolCard.tsx:42', text: 'uses `card state` and STATE_V2, a.b, x/y/zz, README.md., camelCase, tenant-id, v2 and 12ab', kind: 'k' }]
    const texts = ['the ToolCard view', 'mcp_tool_wrapper.py is', 'STATE_V2!', 'card state', 'camelcase here', 'zz top', 'README.md', 'nothing']
    const js = { banned: [...bannedTokens(lines)].sort(), hits: texts.map(t => textProblems(t, bannedTokens(lines))) }
    const pyOut = JSON.parse(py(`import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(WORLD, 'copied'))})
import excerpts
d = json.load(sys.stdin)
b = excerpts.banned_tokens(d["lines"])
print(json.dumps({"banned": sorted(b), "hits": [excerpts.text_problems(t, b) for t in d["texts"]]}))`, JSON.stringify({ lines, texts })))
    check(JSON.stringify(js.banned) === JSON.stringify(pyOut.banned), `識別子が Python と違う: JS ${JSON.stringify(js.banned)} / Python ${JSON.stringify(pyOut.banned)}`)
    check(JSON.stringify(js.hits) === JSON.stringify(pyOut.hits), `当たりが Python と違う: JS ${JSON.stringify(js.hits)} / Python ${JSON.stringify(pyOut.hits)}`)
  },

  async excerpts() {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'dig-world-x-'))
    const pages = path.join(tmp, 'pages.json')
    fs.writeFileSync(pages, JSON.stringify({
      'https://a.example.org/doc': [200, '<html><body><p>Use <b>interrupt</b> inside a tool to pause and wait for a human answer.</p></body></html>'],
      'https://b.example.org/gone': [404, 'not found'],
    }))
    const xs = [
      ['x1', 'https://a.example.org/doc', 'Use interrupt inside a tool to pause and wait for a human answer.'],
      ['x2', 'https://a.example.org/doc#part', 'A sentence that is not on the page at all, said differently.'],
      ['x3', 'https://b.example.org/gone', 'Anything long enough to be checked here.'],
      ['x4', 'http://a.example.org/doc', 'Use interrupt inside a tool to pause and wait.'],
    ].map(r => [...r, H.fnv(`${r[0]}\n${r[1]}\n${r[2]}`)])
    xs.push(['x5', 'https://a.example.org/doc', 'Use interrupt inside a tool to pause.', 'deadbeef'])
    const input = [JSON.stringify({ class: 'w-1', count: xs.length }), ...xs.map(x => H.asciiJson(x))].join('\n')
    const scr = path.join(WORLD, 'world-excerpts.py')
    const out = JSON.parse(execFileSync(PY, [scr, '--pages', pages], { input, encoding: 'utf8' }))
    // DW の 1 行の形（--b64 の後に 1 行ずつの base64）でも同じ答え。base64 として読めない語は garbled
    const words = input.split('\n').map(l => Buffer.from(l, 'utf8').toString('base64'))
    const viaB64 = JSON.parse(execFileSync(PY, [scr, '--pages', pages, '--b64', ...words, '!!not-base64'], { input: '', encoding: 'utf8' }))
    check(viaB64.checked === 6 && JSON.stringify(viaB64.kept) === '["x1"]' && JSON.stringify(viaB64.garbled) === '["x5","?"]',
      `--b64 の形の答えが標準入力の形と違う: ${JSON.stringify(viaB64)}`)
    check(out.ran === true && out.checked === 5 && out.class === 'w-1', `ran・checked・class が違う: ${JSON.stringify(out)}`)
    check(JSON.stringify(out.kept) === '["x1"]', `字のままの抜き書きだけが残らない: ${JSON.stringify(out.kept)}`)
    check(JSON.stringify(out.dropped.map(d => d.id)) === '["x2","x3","x4"]', `言い換え・404・http の行が落ちない: ${JSON.stringify(out.dropped)}`)
    check(JSON.stringify(out.garbled) === '["x5"]' && out.offline === false, `写し違いの行が garbled にならない: ${JSON.stringify(out.garbled)}`)
    // DW の b64 で組んだ生の UTF-8 の JSON（日本語・絵文字）も、台本が同じ字に戻して照合する
    const { b64: jsB64, fnv: jsFnv } = evalDefs(`${defText(SRC, 'B64')}\n${defText(SRC, 'b64')}\n${defText(SRC, 'fnv')}`, ['b64', 'fnv'])
    const ja = ['j1', 'https://ja.example.org/doc', '世の中の普通の作りは、聞く専用のツールの中で止める 😀']
    fs.writeFileSync(path.join(tmp, 'ja.json'), JSON.stringify({ [ja[1]]: [200, `前置き。${ja[2]}。後書き。`] }))
    const viaJs = JSON.parse(execFileSync(PY, [scr, '--pages', path.join(tmp, 'ja.json'), '--b64',
      jsB64(JSON.stringify({ class: 'w-ja', count: 1 })), jsB64(JSON.stringify([...ja, jsFnv(`${ja[0]}\n${ja[1]}\n${ja[2]}`)]))], { input: '', encoding: 'utf8' }))
    check(JSON.stringify(viaJs.kept) === '["j1"]' && viaJs.garbled.length === 0, `DW の b64 の日本語の行が照合されない: ${JSON.stringify(viaJs)}`)
    // ヘッドレスの許しの規則は、shq が囲まない path だけで組み、囲む path（日本語の字など）では組まない
    const rule = xc => execFileSync(PY, ['-c', `import importlib.util,json,sys
spec = importlib.util.spec_from_file_location('h', sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(json.dumps(m.recheck_rule(json.loads(sys.argv[2]))))`, path.join(ROOT, 'attention/scripts/steps-headless.py'), JSON.stringify(xc)], { encoding: 'utf8' }).trim()
    check(rule({ runPython: '/p/run-python.sh', script: '/p/world-excerpts.py' }) === '"Bash(bash /p/run-python.sh /p/world-excerpts.py --b64 *)"', 'ヘッドレスの許しの規則が --b64 の形でない')
    check(rule({ runPython: '/ユーザー/run-python.sh', script: '/p/world-excerpts.py' }) === 'null' && rule({ runPython: '/p/$x/run-python.sh', script: '/p/w.py' }) === 'null',
      'shq が囲む path でも許しの規則を組んだ（命令と字が揃わない）')
    // ネットワークで 1 つも届かなければ offline
    fs.writeFileSync(path.join(tmp, 'none.json'), '{}')
    const off = JSON.parse(execFileSync(PY, [scr, '--pages', path.join(tmp, 'none.json')],
      { input: [JSON.stringify({ class: 'w-2', count: 1 }), H.asciiJson(xs[0])].join('\n'), encoding: 'utf8' }))
    check(off.offline === true && off.kept.length === 0, `どこにも届かない回が offline にならない: ${JSON.stringify(off)}`)
    // 知らない引数は止める
    let bad
    try { execFileSync(PY, [scr, '--what'], { input: '', encoding: 'utf8' }) } catch (e) { bad = JSON.parse(e.stdout) }
    check(bad?.ran === false, '知らない引数で止まらない')
    // 定数は工場の steps.py と同じ値
    const src = read(scr)
    check(/MAX_EXCERPTS = 6\b/.test(src) && /MAX_BODY = 2 \* 1024 \* 1024/.test(src) && src.includes('"User-Agent": "works-world/1"'), '定数が工場の steps.py の値と違う')
    check(/maxExcerpts: 6\b/.test(SRC) && /minExcerpt: 20\b/.test(SRC), 'DW の抜き書きの上限・下限が台本・工場と違う')
    fs.rmSync(tmp, { recursive: true, force: true })
  },

  async prep() {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'dig-world-p-'))
    const g = (...a) => execFileSync('git', a, { cwd: tmp, encoding: 'utf8' }).trim()
    const put = (p, s) => { fs.mkdirSync(path.dirname(path.join(tmp, p)), { recursive: true }); fs.writeFileSync(path.join(tmp, p), s) }
    g('init', '-q'); g('config', 'user.email', 't@e'); g('config', 'user.name', 't'); g('config', 'commit.gpgsign', 'false')
    put('pyproject.toml', '[project]\nname = "ws"\ndependencies = []\n\n[tool.uv.workspace]\nmembers = ["backend", "pkg"]\n')
    put('backend/pyproject.toml', '[project]\nname = "backend"\ndependencies = [\n  "langgraph==1.2.20",  # pinned\n  "fastmcp>=3.4.5,<4",\n  "pkg",\n  "pydantic[email]>=2 ; python_version > \'3.9\'",\n]\n\n[dependency-groups]\ndev = ["pytest"]\n')
    put('pkg/pyproject.toml', '[project]\nname = "pkg"\ndependencies = ["mcp>=1.27"]\n')
    put('uv.lock', 'version = 1\n\n[[package]]\nname = "langgraph"\nversion = "1.2.20"\nsource = { registry = "https://pypi.org/simple" }\n\n[[package]]\nname = "fastmcp"\nversion = "3.4.8"\nsource = { registry = "https://pypi.org/simple" }\n\n[[package]]\nname = "mcp"\nversion = "1.30.0"\nsource = { registry = "https://pypi.org/simple" }\n\n[[package]]\nname = "pkg"\nversion = "0.1.0"\nsource = { editable = "pkg" }\n\n[[package]]\nname = "ws"\nversion = "0.1.0"\nsource = { virtual = "." }\n\n[[package]]\nname = "pydantic"\nversion = "2.14.1"\nsource = { registry = "https://pypi.org/simple" }\n')
    put('frontend/package.json', JSON.stringify({ dependencies: { '@assistant-ui/react': '^0.15.32', local: 'file:../x' }, devDependencies: { vitest: '1' } }))
    put('frontend/package-lock.json', JSON.stringify({ packages: { '': {}, 'node_modules/@assistant-ui/react': { version: '0.15.40' }, 'node_modules/vitest': { version: '1.0.0' } } }))
    put('docs/a.adoc', 'a\n')
    put('backend/app.py', 'x = 1\n')
    g('add', '-A'); g('commit', '-qm', 'base')
    const base = g('rev-parse', 'HEAD')
    put('docs/a.adoc', 'b\n')
    g('commit', '-qam', 'docs')
    const head = g('rev-parse', 'HEAD')
    const rec = path.join(tmp, 'rec.json')
    const record = { version: 3, pr: 7, base, head, purpose: { purpose: '人の答えを待つ', means: ['自前の止め', 3] },
      kind: 'これは渡さない', structure: { mechanisms: [{ mechanism: 'A pause adapter.', premise: 'The runtime does not stop.' }, { mechanism: 'No check.', premise: '' }] } }
    fs.writeFileSync(rec, JSON.stringify(record))
    const prepRun = (...a) => {
      try { return JSON.parse(execFileSync(PY, [PREP, ...a], { cwd: tmp, encoding: 'utf8' })) } catch (e) { return JSON.parse(e.stdout) }
    }
    check(prepRun('--next', 'world', '7').code === 'no-record', '--record の無い --next world が止まらない')
    const r = prepRun('--next', 'world', '7', '--record', rec)
    check(r.ok === true && r.lines === 2 && r.means === 1, `--next world が通らない: ${JSON.stringify(r)}`)
    const a = JSON.parse(fs.readFileSync(r.argsFile, 'utf8'))
    // .native で比べる（Windows の一時のフォルダは短い名前〔RUNNER~1〕で渡り、JS の realpathSync は長い名前に直さないが、Python の realpath は直す。run 44695969416）
    check(fs.realpathSync.native(r.argsFile) === fs.realpathSync.native(path.join(tmp, '.git/attention/my-turn/7-steps/world-args.json')), `args の置き場が違う: ${r.argsFile}`)
    const names = a.deps.map(d => `${d.ecosystem}:${d.name}@${d.version}`)
    check(JSON.stringify(names) === JSON.stringify(['npm:@assistant-ui/react@0.15.40', 'pypi:fastmcp@3.4.8', 'pypi:langgraph@1.2.20', 'pypi:mcp@1.30.0', 'pypi:pydantic@2.14.1']),
      `文書だけの差分の依存が、全部のマニフェストの直の依存（自前・dev を除き、版はロックから）でない: ${JSON.stringify(names)}`)
    check(/declare no direct dependencies/.test(a.deps_note), `全部のマニフェストに広げた訳が deps_note に無い: ${a.deps_note}`)
    check(a.lines[0].text === 'A pause adapter. Premise: The runtime does not stop.' && a.lines[1].text === 'No check.' && a.lines[0].where === 'mechanism 1', '依頼の行の組み方が違う')
    check(!JSON.stringify(a).includes('これは渡さない'), '記録の種類の 1 文が args に入った')
    check(a.caller === 'attention:check-world' && a.excerptCheck.script.endsWith(path.join('steps', 'world', 'world-excerpts.py')), 'caller か excerptCheck が違う')
    check(a.sum === sumOf(a), 'steps-prep の sum が DW の sumOf と違う')
    const dry = await run(a, () => null)
    check(!dry.out.stopped && dry.out.status === 'failed', `steps-prep の args で DW が止まった: ${JSON.stringify(dry.out).slice(0, 200)}`)
    // 変えたコードのファイルの近くのマニフェストがあれば、それだけを見て、import を印にする
    put('backend/app.py', 'from langgraph.types import interrupt\nimport fastmcp\n')
    g('commit', '-qam', 'code')
    const head2 = g('rev-parse', 'HEAD')
    fs.writeFileSync(rec, JSON.stringify({ ...record, base: head, head: head2 }))
    const r2 = prepRun('--next', 'world', '7', '--record', rec)
    const a2 = JSON.parse(fs.readFileSync(r2.argsFile, 'utf8'))
    check(JSON.stringify(a2.deps.map(d => `${d.name}:${d.imported_by_touched}`)) === JSON.stringify(['fastmcp:true', 'langgraph:true', 'pydantic:false']) && a2.deps_note === '',
      `近いマニフェストの依存と import の印が違う: ${JSON.stringify(a2.deps)}`)
    // head の違う作業場では止める
    fs.writeFileSync(rec, JSON.stringify({ ...record, head }))
    check(prepRun('--next', 'world', '7', '--record', rec).code === 'head-mismatch', 'head の違う作業場で止まらない')
    // --save: 形の違う返りは書かず、包みを外して書く
    const outBad = path.join(tmp, 'bad.json'), outGood = path.join(tmp, 'good.json')
    fs.writeFileSync(outBad, JSON.stringify({ result: { ok: true, status: 'ok', rows: [{ n: 1 }], missing: [], excerpts: {}, counts: {} } }))
    check(prepRun('--save', 'world', '7', outBad).code === 'shape', '形の違う返りを書いた')
    const good = (await run(baseArgs(), happy())).out
    fs.writeFileSync(outGood, JSON.stringify({ result: JSON.stringify(good) }))
    const sv = prepRun('--save', 'world', '7', outGood)
    check(sv.ok === true && sv.rows === 2 && fs.existsSync(path.join(tmp, '.git/attention/my-turn/7-steps/world.json')), `形の合う返りを書かない: ${JSON.stringify(sv)}`)
    fs.writeFileSync(outBad, JSON.stringify({ stopped: 'caller' }))
    check(prepRun('--save', 'world', '7', outBad).code === 'shape', '止まった回の返りを書いた')
    fs.rmSync(tmp, { recursive: true, force: true })
  },

  async copies() {
    // 台帳 COPIED_FROM の「字のまま」の写しの sha256 が台帳と同じ。書き替えた物は写した先が在る
    const ledger = read(path.join(WORLD, 'COPIED_FROM')).split('\n').filter(Boolean)
    check(/^[0-9a-f]{40}  works-factory/.test(ledger[0]), '台帳の 1 行目が工場の commit でない')
    let verbatim = 0
    for (const l of ledger.slice(1)) {
      const [src, sha, how, ...where] = l.split(/ {2}/)
      const want = sha.replace('sha256=', '')
      if (how === '字のまま') {
        verbatim++
        const p = path.join(WORLD, where[0])
        const got = fs.existsSync(p) ? crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex') : 'missing'
        check(got === want, `${where[0]}（${src}）の sha256 が台帳と違う: ${got}`)
      } else {
        check(how === '書き替えた' && /^[0-9a-f]{64}$/.test(want) && where.join('  ').length > 0, `台帳の行の形が違う: ${l}`)
      }
    }
    const files = fs.readdirSync(path.join(WORLD, 'copied')).filter(f => f !== '__pycache__')
    check(verbatim === files.length, `copied/ のファイル（${files.length}）と台帳の字のままの行（${verbatim}）の数が違う`)
  },

  async score() {
    // attention/scripts/score-world.py: 札の 3 つの条件（相手・層・判定）と文の正規表現が揃った比べだけを拾えたとし、
    // 外れた比べは訳を付けて near に出す。検索語に対象の名前が出たら数える。読めない入力は止める
    const SCORE = path.join(ROOT, 'attention/scripts/score-world.py')
    const KEY = path.join(ROOT, 'attention/docs/measures/2555-world-key.json')
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'dig-world-s-'))
    const put = (p, v) => { fs.mkdirSync(path.dirname(path.join(tmp, p)), { recursive: true }); fs.writeFileSync(path.join(tmp, p), typeof v === 'string' ? v : JSON.stringify(v)); return path.join(tmp, p) }
    const score = (...a) => {
      try { return JSON.parse(execFileSync(PY, [SCORE, '--key', KEY, ...a], { encoding: 'utf8' })) } catch (e) { return JSON.parse(e.stdout) }
    }
    const cmp = (kind, name, layer, verdict, practice) => ({ against: { kind, name, version: '' }, layer, verdict, practice, challenge: '', why: '', applies: '', basis: 'web' })
    const world = (rows, head = 'c0c1848ca2f5b139834c14343f09a022ac8835ac') => ({ status: 'ok', head, rows, missing: [{ n: 3, why: 'x' }], excerpts: { kept: 3, dropped: 1, unchecked: 2, garbled: 0, over: 0 }, counts: { agents: 9, classes: 2, stages: {} } })
    const hitRow = { n: 1, class_id: 'w-1', comparisons: [cmp('dependency', 'langgraph', 'architecture', 'differs', 'The model calls an ask tool and interrupt() pauses inside it.')] }
    const nearRow = { n: 2, class_id: 'w-2', comparisons: [cmp('dependency', '@assistant-ui/react', 'architecture', 'same', 'onResumeToolCall resumes the tool.'), cmp('dependency', 'langgraph', 'contract', 'differs', 'interrupt')] }
    const args = put('args.json', { lines: [{ n: 1, where: 'mechanism 1', text: 'The mcp_tool_wrapper.py adapter and the langgraph runtime.' }, { n: 2, where: 'mechanism 2', text: 'b' }, { n: 3, where: 'mechanism 3', text: 'c' }], deps: [{ name: 'langgraph', version: '1.2.20' }] })
    put('tr/s/subagents/agent-1.jsonl', [
      { message: { content: [{ type: 'tool_use', name: 'WebSearch', input: { query: 'mcp_tool_wrapper.py pause' } }] } },
      { type: 'assistant', message: { content: [{ type: 'tool_use', id: 'toolu_a', name: 'WebSearch', input: { query: 'langgraph interrupt tool' } }, { type: 'tool_use', id: 'toolu_b', name: 'WebFetch', input: { url: 'https://x' } }] } },
      // the transcript repeats the same calls in an api-request-blob line; counted once by id
      { type: 'api-request-blob', message: { content: [{ type: 'tool_use', id: 'toolu_a', name: 'WebSearch', input: { query: 'langgraph interrupt tool' } }, { type: 'tool_use', id: 'toolu_b', name: 'WebFetch', input: { url: 'https://x' } }] } },
    ].map(x => JSON.stringify(x)).join('\n') + '\n{"cut')
    const good = score('--world', put('w1.json', world([hitRow, nearRow])), '--args', args, '--transcripts', path.join(tmp, 'tr'))
    check(good.ok === true && good.gate === true && good.keys[0].hit && good.keys[0].hits.length === 1, `札 1 に当たる比べを拾わない: ${JSON.stringify(good).slice(0, 300)}`)
    const missed = good.keys?.[0]?.near?.map(n => `${n.name}:${n.missed.join('+')}`)
    check(JSON.stringify(missed) === JSON.stringify(['@assistant-ui/react:verdict', 'langgraph:layer']), `外れた比べの訳が違う: ${JSON.stringify(missed)}`)
    check(good.lines.answered === 2 && good.lines.missing === 1 && good.lines.total === 3, `答えた数が違う: ${JSON.stringify(good.lines)}`)
    check(good.excerpts.keptOfChecked === 0.75 && good.excerpts.webShare === 1, `抜き書きの割合が違う: ${JSON.stringify(good.excerpts)}`)
    check(good.queries.searches === 2 && good.queries.fetches === 1 && good.queries.leaks === 1 && good.queries.leakQueries[0].names.includes('mcp_tool_wrapper.py') && good.queries.unreadableLines === 1,
      `検索語の漏れの数が違う（依存の名 langgraph は漏れに数えない）: ${JSON.stringify(good.queries)}`)
    const bad = score('--world', put('w2.json', world([nearRow])), '--args', args)
    check(bad.ok === true && bad.gate === false && bad.queries === null, '札 1 に当たる比べが無いのに合になる')
    const other = score('--world', put('w4.json', world([hitRow], 'h'.repeat(40))))
    check(other.ok === true && other.keys[0].hit && other.headMatches === false && other.gate === false, '札と別の head の返りが合になる')
    check(score('--world', put('w3.json', { stopped: 'caller' })).ok === false, 'rows の無い返りで止まらない')
    check(score('--world', path.join(tmp, 'none.json')).ok === false, '無いファイルで止まらない')
    fs.rmSync(tmp, { recursive: true, force: true })
  },
}

const name = process.argv[2]
if (!cases[name]) {
  console.log(`使い方: node tests/dig-world-dry.mjs <${Object.keys(cases).join('|')}>`)
  process.exit(1)
}
try {
  await cases[name]()
} catch (e) {
  fails.push(`投げた: ${e.stack}`)
}
if (fails.length) {
  for (const f of fails) console.log(`FAIL ${f}`)
  process.exit(1)
}
console.log(`${name.toUpperCase()}_OK`)
