// Generator: attention/prompts/<NAME>.md -> the prompts block of attention/workflows/my-turn-dig.js.
// A Workflow script cannot read files at run time (https://code.claude.com/docs/en/workflows "No direct filesystem
// or shell access from the workflow itself"), so the prompt files are compiled into the script here, at build time.
//
//   node attention/scripts/gen-prompts.mjs           rewrite the block between "// ==== prompts" and the end marker
//   node attention/scripts/gen-prompts.mjs --check   exit 1 when the committed block differs from what the files make
//
// File format: see attention/prompts/README.md. In short:
//   front matter   vars:  <name>: text | list | flag, with "?" after text or list when null is allowed
//                  form: list   (optional) the body is "- " lines and the constant is an array of strings
//   body           {{x}}  {{x|join:", "|or:"none"}}  {{x|bullets}}  {{#if x}}...{{else}}...{{/if}}  {{#if x != null}}
//                  A line holding only {{#if ...}}, {{else}} or {{/if}} disappears together with its newline.
// <NAME>.ja.md is the Japanese translation for the owner; its source_sha256 is the sha256 of <NAME>.md (LF line ends).
// tests/my-turn-dig-dry.mjs (case prompts) runs check() below, so a stale block or translation fails the land gate.
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const PROMPTS_DIR = path.resolve(HERE, '../prompts')
export const SCRIPT = path.resolve(HERE, '../workflows/my-turn-dig.js')
export const START = '// ==== prompts (section 3) ===='
export const END = '// ==== end of prompts ===='

const FILTERS = { join: 1, or: 1, bullets: 0 }   // filter name -> number of arguments
const TYPES = ['text', 'list', 'flag']
const lf = s => s.replace(/\r\n/g, '\n')
export const sha256 = s => crypto.createHash('sha256').update(lf(s)).digest('hex')

// ---- front matter: a small YAML subset (top-level "key: value", and "vars:" with indented "name: type") ----
function parseFile(src, file, problems) {
  const m = lf(src).match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  if (!m) { problems.push(`${file}: no front matter (the file must start with a --- line and close it with another)`); return null }
  const meta = { vars: {} }
  let inVars = false
  for (const raw of m[1].split('\n')) {
    const line = raw.replace(/(^|\s+)#.*$/, '')
    if (!line.trim()) continue
    if (/^vars:\s*$/.test(line)) { inVars = true; continue }
    const top = line.match(/^(\w+):\s*(.*?)\s*$/)
    if (top) { inVars = false; meta[top[1]] = top[2]; continue }
    const v = line.match(/^\s+(\w+):\s*(\w+)(\?)?\s*$/)
    if (inVars && v && TYPES.includes(v[2]) && !(v[3] && v[2] === 'flag')) { meta.vars[v[1]] = { type: v[2], nullable: !!v[3] }; continue }
    problems.push(`${file}: front matter line not understood: ${raw.trim()}`)
  }
  // the body is the text after the closing ---, minus the file's final newline
  return { meta, body: m[2].replace(/\n$/, '') }
}

// a line that is only {{#if ...}}, {{else}} or {{/if}} disappears with its newline
const stripStandalone = body => body.replace(/^[ \t]*(\{\{\s*(?:#if\b[^}]*|else|\/if)\s*\}\})[ \t]*(\n|$)/gm, '$1')

function tokenize(body, file, problems) {
  const out = []
  const re = /\{\{([^{}]*)\}\}/g
  let last = 0, m
  while ((m = re.exec(body))) {
    if (m.index > last) out.push({ t: 'text', v: body.slice(last, m.index) })
    out.push({ t: 'tag', v: m[1].trim() })
    last = re.lastIndex
  }
  if (last < body.length) out.push({ t: 'text', v: body.slice(last) })
  for (const tk of out) if (tk.t === 'text' && /\{\{|\}\}/.test(tk.v)) problems.push(`${file}: stray braces in the text: ${JSON.stringify(tk.v.slice(0, 40))}`)
  return out
}

// text -> the inside of a JS template literal
const lit = s => s.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${')

function compileTemplate(name, meta, body, file, problems) {
  const used = new Set()
  const ref = v => {
    if (!(v in meta.vars)) problems.push(`${file}: {{${v}}} is not declared in vars`)
    used.add(v)
    return `c.${v}`
  }
  // a frame is one literal being built; an {{#if}} opens a frame for its then-part and {{else}} one for its else-part
  const stack = [{ parts: [] }]
  for (const tk of tokenize(stripStandalone(body), file, problems)) {
    const cur = stack[stack.length - 1]
    if (tk.t === 'text') { cur.parts.push(lit(tk.v)); continue }
    let m
    if ((m = tk.v.match(/^#if\s+(\w+)(\s*!=\s*null)?$/))) {
      const v = ref(m[1]), spec = meta.vars[m[1]]
      if (m[2] && spec && !spec.nullable) problems.push(`${file}: {{#if ${m[1]} != null}} on a var that cannot be null`)
      const cond = m[2] ? `${v} !== null` : spec?.type === 'list' ? `${v}.length` : spec?.type === 'flag' ? v : `${v}`
      stack.push({ parts: [], cond, open: tk.v }); continue
    }
    if (tk.v === 'else') {
      if (stack.length < 2 || cur.elseOf) { problems.push(`${file}: {{else}} without {{#if}}`); continue }
      stack.pop()
      stack.push({ parts: [], cond: cur.cond, then: cur.parts, elseOf: cur.open }); continue
    }
    if (tk.v === '/if') {
      if (stack.length < 2) { problems.push(`${file}: {{/if}} without {{#if}}`); continue }
      stack.pop()
      const then = cur.elseOf ? cur.then : cur.parts, other = cur.elseOf ? cur.parts : []
      const q = parts => (parts.length ? `\`${parts.join('')}\`` : "''")
      stack[stack.length - 1].parts.push(`\${${cur.cond} ? ${q(then)} : ${q(other)}}`)
      continue
    }
    const parts = tk.v.split('|').map(s => s.trim())
    if (!/^\w+$/.test(parts[0])) { problems.push(`${file}: tag not understood: {{${tk.v}}}`); continue }
    let expr = ref(parts[0])
    const spec = meta.vars[parts[0]]
    if (spec?.type === 'flag') problems.push(`${file}: flag {{${parts[0]}}} can only be used in {{#if}}`)
    let isList = spec?.type === 'list'
    for (const f of parts.slice(1)) {
      const fm = f.match(/^(\w+)(?::("(?:[^"\\]|\\.)*"))?$/)
      if (!fm || !(fm[1] in FILTERS) || (FILTERS[fm[1]] === 1) !== (fm[2] !== undefined)) { problems.push(`${file}: unknown or malformed filter "${f}" in {{${tk.v}}}`); continue }
      if (fm[1] === 'join') { if (!isList) problems.push(`${file}: join on a non-list in {{${tk.v}}}`); expr = `${expr}.join(${fm[2]})`; isList = false }
      if (fm[1] === 'bullets') { if (!isList) problems.push(`${file}: bullets on a non-list in {{${tk.v}}}`); expr = `_bullets(${expr})`; isList = false }
      if (fm[1] === 'or') { if (isList) problems.push(`${file}: or on a list in {{${tk.v}}} (join it first)`); expr = `_or(${expr}, ${fm[2]})` }
    }
    if (isList) problems.push(`${file}: list {{${parts[0]}}} printed without join or bullets`)
    stack[stack.length - 1].parts.push(`\${${expr}}`)
  }
  if (stack.length !== 1) problems.push(`${file}: {{#if}} without {{/if}}`)
  for (const v of Object.keys(meta.vars)) if (!used.has(v)) problems.push(`${file}: var ${v} is declared but never used`)
  const vars = Object.entries(meta.vars).map(([k, s]) => `${k}: '${s.type}${s.nullable ? '?' : ''}'`).join(', ')
  return `const ${name} = c => (_need('${name}', c, { ${vars} }), \`${stack[0].parts.join('')}\`)`
}

function compileList(name, meta, body, file, problems) {
  if (Object.keys(meta.vars).length) problems.push(`${file}: a form: list file takes no vars`)
  const items = body.split('\n').filter(l => l.trim())
  for (const l of items) if (!l.startsWith('- ')) problems.push(`${file}: a form: list line must start with "- ": ${l.slice(0, 40)}`)
  if (/\{\{|\}\}/.test(body)) problems.push(`${file}: a form: list file takes no {{tags}}`)
  return `const ${name} = [\n${items.map(l => `  \`${lit(l.slice(2))}\`,`).join('\n')}\n]`
}

const HEADER = [
  START,
  '// Generated by attention/scripts/gen-prompts.mjs from attention/prompts/<NAME>.md: do not edit this block by hand.',
  '// To change a prompt, edit its .md, check its Japanese translation <NAME>.ja.md, then run',
  '// `node attention/scripts/gen-prompts.mjs` (how: attention/prompts/README.md). These are the viewpoints: what each stage',
  '// looks at and how it judges. The code after the end marker turns values into the short strings and string lists these',
  '// functions take, and lays out the data parts by itself (the stage frame, the PR file list, the Quotes command text and',
  '// the W10 claims). A function throws when a declared value is missing or of the wrong type.',
  "const _bullets = xs => xs.length ? xs.map(x => `- ${x}`).join('\\n') : '- (none)'",
  "const _or = (v, d) => (v === '' || v === null ? d : v)",
  'const _need = (name, c, vars) => {',
  '  for (const [k, t] of Object.entries(vars)) {',
  '    const v = c?.[k], type = t.replace(/\\?$/, \'\')',
  "    if (v === undefined || (v === null && !t.endsWith('?'))) throw new Error(`${name}: missing ${k}`)",
  "    const ok = v === null || (type === 'list' ? Array.isArray(v) : type === 'flag' ? typeof v === 'boolean' : ['string', 'number'].includes(typeof v))",
  '    if (!ok) throw new Error(`${name}: ${k} is not a ${type}`)',
  '  }',
  '}',
]

export function promptNames(dir = PROMPTS_DIR) {
  return fs.readdirSync(dir).filter(f => f !== 'README.md' && /^[A-Z][A-Z0-9_]*\.md$/.test(f)).map(f => f.slice(0, -3)).sort()
}

// the whole block, from the START line to the END line, or the problems that stop it
export function generate(dir = PROMPTS_DIR) {
  const problems = []
  const out = [...HEADER]
  for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.md') && !f.endsWith('.ja.md') && f !== 'README.md').sort()) {
    if (!/^[A-Z][A-Z0-9_]*\.md$/.test(f)) { problems.push(`${f}: a prompt file name is the constant name in capitals, digits and _`); continue }
    const parsed = parseFile(fs.readFileSync(path.join(dir, f), 'utf8'), f, problems)
    if (!parsed) continue
    const name = f.slice(0, -3)
    const known = new Set(['vars', 'form'])
    for (const k of Object.keys(parsed.meta)) if (!known.has(k)) problems.push(`${f}: unknown front matter key ${k}`)
    if (parsed.meta.form !== undefined && parsed.meta.form !== 'list') problems.push(`${f}: form must be list when given`)
    out.push('', `// ${name}: attention/prompts/${f}`)
    out.push(parsed.meta.form === 'list' ? compileList(name, parsed.meta, parsed.body, f, problems) : compileTemplate(name, parsed.meta, parsed.body, f, problems))
  }
  out.push(END)
  return { block: out.join('\n'), problems }
}

// translations: every prompt has <NAME>.ja.md whose source_sha256 is the sha256 of <NAME>.md
export function translationProblems(dir = PROMPTS_DIR) {
  const problems = []
  const files = new Set(fs.readdirSync(dir))
  for (const name of promptNames(dir)) {
    const ja = `${name}.ja.md`
    if (!files.has(ja)) { problems.push(`${ja}: no Japanese translation for ${name}.md`); continue }
    const src = lf(fs.readFileSync(path.join(dir, ja), 'utf8'))
    const want = sha256(fs.readFileSync(path.join(dir, `${name}.md`), 'utf8'))
    const got = src.match(/^---\n(?:[\s\S]*?\n)?source_sha256:\s*([0-9a-f]+)\s*\n(?:[\s\S]*?\n)?---\n([\s\S]*)$/)
    if (!got) { problems.push(`${ja}: no source_sha256 in the front matter`); continue }
    if (!got[2].trim()) problems.push(`${ja}: the translation is empty`)
    if (got[1] !== want) problems.push(`${ja}: ${name}.md changed after the translation was written. Check the translation, then set source_sha256: ${want}`)
  }
  for (const f of files) if (f.endsWith('.ja.md') && !files.has(f.replace(/\.ja\.md$/, '.md'))) problems.push(`${f}: no English file ${f.replace(/\.ja\.md$/, '.md')}`)
  return problems
}

// replace the block in the script text; null when the markers are missing
export function splice(script, block) {
  const s = lf(script)
  const a = s.indexOf(`${START}\n`), b = s.indexOf(`${END}\n`)
  if (a < 0 || b < a) return null
  return s.slice(0, a) + block + s.slice(b + END.length)
}

// what the land gate checks: the block is current and every translation matches its English file
export function check() {
  const { block, problems } = generate()
  const script = fs.readFileSync(SCRIPT, 'utf8')
  const want = problems.length ? null : splice(script, block)
  if (!problems.length && want === null) problems.push(`${path.basename(SCRIPT)}: the markers "${START}" and "${END}" are missing`)
  if (want !== null && want !== lf(script)) problems.push(`${path.basename(SCRIPT)}: the prompts block is not what attention/prompts/*.md make. Run: node attention/scripts/gen-prompts.mjs`)
  return [...problems, ...translationProblems()]
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes('--check')) {
    const problems = check()
    if (problems.length) { console.error(problems.join('\n')); process.exit(1) }
    console.log('prompts: up to date')
  } else {
    const { block, problems } = generate()
    if (problems.length) { console.error(problems.join('\n')); process.exit(1) }
    const script = fs.readFileSync(SCRIPT, 'utf8')
    const next = splice(script, block)
    if (next === null) { console.error(`${SCRIPT}: the markers "${START}" and "${END}" are missing`); process.exit(1) }
    if (next !== lf(script)) fs.writeFileSync(SCRIPT, next)
    console.log(next === lf(script) ? 'prompts: already up to date' : `prompts: wrote ${path.relative(process.cwd(), SCRIPT)}`)
    // a stale translation does not stop the build, but the dry test fails on it
    for (const p of translationProblems()) console.error(`warning: ${p}`)
  }
}
