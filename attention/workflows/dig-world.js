export const meta = {
  name: 'dig-world',
  description: "World's solution for one PR: restate each request line as a problem class, find how dependencies, products and standards solve it, and compare the PR's means with each",
  whenToUse: 'Only when the user typed /attention:check-world, which builds the args with steps-prep.py and passes them unchanged. Never start it on your own; a start without its caller value stops before any agent',
  phases: [
    { title: 'Restate', detail: 'one agent restates every request line as a problem class without the means; code and a second model check for leaked means (up to 3 rounds)' },
    { title: 'Search', detail: 'per class: one agent searches dependencies, products and standards on the web (up to 3 rounds); one agent runs the excerpt re-fetch script; a blind eye draws the general structure' },
    { title: 'Compare', detail: "per class: one agent compares the PR's means with every row, at the row's own layer" },
  ],
}

// Design: attention/docs/small-workflows-design.md, section 3 (cited as "3.N"). The prompts below are AI-only text, in
// English. They rewrite works-factory's workflows/world/prompts/world-classes.md and parts/world-judge.md, and embed
// workflows/.shared/prompts/query-rule.md and rejected.md word for word (the copies and their sha256 are in
// attention/steps/world/COPIED_FROM; tests/dig-world-dry.mjs checks the embedded text against the copies).

let A = args ?? {}
if (typeof A === 'string') { try { A = JSON.parse(A) ?? {} } catch { A = {} } }
// Section 7: only the skills listed here put their name in args.caller. meta has no field that keeps the model from
// starting a workflow on its own, so a start without it stops here, before any agent. This is a guard against a model
// starting it by mistake, not a lock: a start that copies the value on purpose passes.
const CALLERS = ['attention:check-world']
if (!CALLERS.includes(A.caller)) {
  return { stopped: 'caller', message: 'Not started by /attention:check-world, so no agent was started. Type /attention:check-world to run it.' }
}

// ---- small pure helpers (fnv, shq, asciiJson, clean and meansWords are the same text as in my-turn-dig.js; the dry test checks) ----
const CTRL = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F؜‎‏‪-‮⁦-⁩]/g
const clean = v => typeof v === 'string' ? v.replace(CTRL, '')
  : Array.isArray(v) ? v.map(clean)
  : (v && typeof v === 'object') ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, clean(x)])) : v
const fnv = s => {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 }
  return h.toString(16).padStart(8, '0')
}
const shq = s => (/^[A-Za-z0-9_@%+=:,./-]+$/.test(String(s)) ? String(s) : `'${String(s).replace(/'/g, `'\\''`)}'`)
const asciiJson = v => JSON.stringify(v).replace(/[\u007f-\uffff]/g, ch => `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`)
// base64 of the UTF-8 bytes of a string, by hand (no btoa or TextEncoder is promised in the Workflow runtime)
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const b64 = s => {
  const bytes = []
  for (const ch of String(s)) {
    const c = ch.codePointAt(0)
    if (c < 0x80) bytes.push(c)
    else if (c < 0x800) bytes.push(0xc0 | c >> 6, 0x80 | c & 63)
    else if (c < 0x10000) bytes.push(0xe0 | c >> 12, 0x80 | c >> 6 & 63, 0x80 | c & 63)
    else bytes.push(0xf0 | c >> 18, 0x80 | c >> 12 & 63, 0x80 | c >> 6 & 63, 0x80 | c & 63)
  }
  let out = ''
  for (let i = 0; i < bytes.length; i += 3) {
    const [a, b = 0, c = 0] = bytes.slice(i, i + 3), n = a << 16 | b << 8 | c
    out += B64[n >> 18 & 63] + B64[n >> 12 & 63] + (i + 1 < bytes.length ? B64[n >> 6 & 63] : '=') + (i + 2 < bytes.length ? B64[n & 63] : '=')
  }
  return out
}
const meansWords = means => [...new Set(means.flatMap(m => [
  ...(String(m ?? '').match(/[A-Za-z0-9][\w./-]*/g) ?? []).map(w => w.replace(/[./-]+$/, ''))
    .filter(w => w.length >= 3 && (/[-_\d/.]/.test(w) || /[a-z][A-Z]/.test(w))),
  ...(String(m ?? '').match(/[\p{Script=Han}\p{Script=Katakana}ー]{4,}/gu) ?? []),
]))]
const blank = v => v === undefined || v === null || (typeof v === 'string' && !v.trim())
const str = v => (typeof v === 'string' ? v.trim() : '')
// the sum steps-prep.py puts in args: FNV over the sorted-key JSON with every character above U+007F as \uXXXX
// (Python's json.dumps(sort_keys=True, ensure_ascii=True, separators=(',', ':')))
const canon = v => Array.isArray(v) ? `[${v.map(canon).join(',')}]`
  : (v && typeof v === 'object') ? `{${Object.keys(v).sort().map(k => `${canon(k)}:${canon(v[k])}`).join(',')}}`
  : JSON.stringify(v ?? null).replace(/[\u0080-\uffff]/g, ch => `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`)
const SUM_KEYS = ['lines', 'purpose', 'means', 'deps', 'deps_note', 'lang', 'own_names']
const sumOf = a => fnv(canon(Object.fromEntries(SUM_KEYS.map(k => [k, a[k] ?? null]))))

// identifiers of the request lines (a port of works-factory's excerpts.banned_tokens and text_problems; the dry test
// runs the Python copy on the same input): a word with _ . / - or a digit, or a lower letter followed by an upper one,
// 3 characters or more with a letter; for a word with /, its shaped parts and its last part; and `ticked` text
const WORD = /[A-Za-z0-9_.][A-Za-z0-9_./-]*/g
const TICKED = /`([^`\n]{2,})`/g
const shaped = t => t.length >= 3 && /[A-Za-z]/.test(t) && (/[_./\-0-9]/.test(t) || /[a-z][A-Z]/.test(t))
const tokensOf = text => {
  const out = new Set()
  for (const raw of String(text).match(WORD) ?? []) {
    const tok = raw.replace(/[.\-/]+$/, '').split(':')[0]
    if (shaped(tok)) out.add(tok)
    if (tok.includes('/')) {
      const parts = tok.split('/').filter(Boolean)
      for (const p of parts) if (shaped(p)) out.add(p)
      if (parts.length && parts[parts.length - 1].length >= 3) out.add(parts[parts.length - 1])
    }
  }
  return out
}
const bannedTokens = lines => {
  const out = new Set()
  for (const f of Array.isArray(lines) ? lines : []) {
    if (!f || typeof f !== 'object') continue
    for (const v of Object.values(f)) {
      if (typeof v !== 'string') continue
      for (const t of tokensOf(v)) out.add(t)
      for (const m of v.matchAll(TICKED)) if (m[1].trim()) out.add(m[1].trim())
    }
  }
  return out
}
const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const textProblems = (text, banned) => [...banned].filter(b =>
  new RegExp(`(?<![A-Za-z0-9_])${esc(b)}(?![A-Za-z0-9_])`, 'i').test(typeof text === 'string' ? text : '')).sort()

// ---- args (3.2) ----
const lines = Array.isArray(A.lines) ? A.lines : []
const deps = Array.isArray(A.deps) ? A.deps : []
const means = (Array.isArray(A.means) ? A.means : []).filter(m => typeof m === 'string' && m.trim())
const LANG = str(A.lang) || 'English'
// identifiers of the request lines that the PR's diff or the repository defines (steps-prep.py's own_names). Only these
// count as the target's names: a product or standard named in a request line (PostgreSQL) is not one (3.2, 3.7)
const ownNames = Array.isArray(A.own_names) ? A.own_names : null
const missingArgs = [
  ...(lines.length ? [] : ['lines']),
  ...(lines.every((l, i) => l && l.n === i + 1 && typeof l.text === 'string' && typeof l.where === 'string') ? [] : ['lines[].n is 1..N in order, with text and where']),
  ...(deps.every(d => d && typeof d.name === 'string' && d.name) ? [] : ['deps[].name']),
  ...(ownNames && ownNames.every(t => typeof t === 'string') ? [] : ['own_names (strings)']),
  ...(A.excerptCheck?.runPython && A.excerptCheck?.script ? [] : ['excerptCheck.runPython and excerptCheck.script']),
]
if (missingArgs.length) return { stopped: 'args', missing: missingArgs }
if (A.sum !== sumOf(A)) {
  return { stopped: 'sum', message: 'args.sum does not match the args (a value was changed or copied wrong). Pass the JSON steps-prep.py printed, unchanged.', want: sumOf(A), got: A.sum ?? null }
}

// ---- models (3.9); args.models overrides per stage, args.roles (headless) names a role per stage ----
const MODELS = {
  Restate: { model: 'opus', effort: 'high' },
  Leak: { model: 'sonnet', effort: 'medium' },     // a model other than the restater's (3.3 step 3)
  Search: { model: 'sonnet', effort: 'medium' },
  Recheck: { model: 'haiku', effort: 'medium' },   // copies one command exactly and relays its output (3.6)
  Compare: { model: 'opus', effort: 'high' },
  Generalfallback: { model: 'opus', effort: 'medium' },   // no blind-judge role (the W2fallback of my-turn-dig.js)
}
const M = stage => ({ ...MODELS[stage], ...(A.models?.[stage] ?? {}), ...(A.roles?.[stage] ? { agentType: A.roles[stage] } : {}) })
if (M('Leak').model === M('Restate').model) {
  return { stopped: 'leak model equals restate model', models: { Restate: M('Restate').model, Leak: M('Leak').model } }
}

const LIMITS = { tries: 3, maxQueries: 3, maxExcerpts: 6, minExcerpt: 20, minChallenge: 20 }
const LAYERS = ['architecture', 'contract', 'implementation']
const KINDS = ['dependency', 'product', 'standard']
const VERDICTS = ['same', 'differs', 'none']

// ---- schemas (every field required; required inside properties) ----
const S = { type: 'string' }
const B = { type: 'boolean' }
const I = { type: 'integer' }
const arr = items => ({ type: 'array', items })
const obj = props => ({ type: 'object', properties: props, required: Object.keys(props) })
const oneOf = values => ({ type: 'string', enum: values })
const RESTATE = obj({ classes: arr(obj({ n: I, problem: S, activity: S, proposed: S, arisesFrom: I, queries: arr(S), deps: arr(S), depsWhy: S })) })
const LEAK = obj({ items: arr(obj({ n: I, presupposes: B, why: S })) })
const SEARCH = obj({
  excerpts: arr(obj({ id: S, url: S, excerpt: S })),
  rows: arr(obj({ kind: oneOf(KINDS), name: S, version: S, layer: oneOf(LAYERS), practice: S, sources: arr(S),
    applies: S, not_applies: S, found: B, searched: arr(S) })),
})
const RECHECK = obj({ ran: B, checked: I, kept: arr(S), dropped: arr(obj({ id: S, why: S })), garbled: arr(S), over: I, offline: B, error: S })
const GENERAL = obj({ general: S, layer: oneOf(LAYERS), notFound: B })
const COMPARE = obj({ items: arr(obj({ row: S, n: I, verdict: oneOf(VERDICTS), challenge: S, why: S })) })

// ---- counts ----
const counts = { classes: 0, agents: 0, stages: {} }
const stageCount = s => (counts.stages[s] ??= { started: 0, returned: 0, null: 0, models: [] })
const run = async (stage, label, prompt, opts) => {
  const sc = stageCount(stage)
  sc.started++
  if (opts.model && !sc.models.includes(opts.model)) sc.models.push(opts.model)
  counts.agents++
  const r = await agent(prompt, { label, ...opts })
  if (r) sc.returned++
  else sc.null++
  return r ? clean(r) : null
}

// ---- shared prompt parts ----
// workflows/.shared/prompts/rejected.md, word for word, with {rejection} filled
const REJECTED = rejection => `## Why your previous answer was rejected

The machine's acceptance check rejected your previous answer. Fix every point below, including the points from earlier rounds, and return the whole answer again, not only the parts you changed.

~~~text
${rejection}
~~~`
// workflows/.shared/prompts/query-rule.md, word for word, without its first line (a marker for the factory's tool check)
// and without the "if spawns" block (the searcher starts no sub-agent)
const QUERY_RULE = `Rules for queries to outside services and for the sources you use:

- **Do not put the target's names in queries.** Whatever the tool (web search, web fetch, curl from a shell, a query to a package registry, and so on), a query you send to an outside service that does not hold the target (search words, URLs, command arguments) stays in that service's records. Treat the target (the repository, documents, and diff you were given) as possibly private even when it looks public; do not decide for yourself whether it is public.
  - Write a query as the general problem you want to look up, restated in a few words (look up the general name of the mechanism, not the name of an internal module).
  - Do not include the target owner's names (company names, product names, internal code names, repository names, branch names, paths, the target's own identifiers) or the target's text (code fragments, diffs, sentences from its documents).
  - Third-party names (things made and published outside the target: the open-source software, standards, and vendor products the target uses, and the general form of public error messages) may be included; primary sources need them. Treat a name you cannot place as the owner's name.
  - To check the meaning of a word that is only used inside the target (in-house jargon), look up its definition restated in general words, and the candidate standard terms, not the word itself.
  - Do not run a lookup that cannot be done without the owner's names. Name it in your answer as "a lookup not run because it needs the target's names" and leave it for a person to check (if the answer schema has a field for "missing", "cannot verify", or "not found (what was searched)", write it there).
  - A query to a place that already holds the target (the repository's git, gh against the host that holds the repository, or reading that host's pages with web fetch) is not an outside query, and these rules do not cover it.
- **Go to primary sources first**: standards documents, official documentation and guides, original texts, official repositories, and practitioner documents that are widely cited. Prefer them over blog posts and other secondary sources. Check that a source is not about an old version. If you find only secondary sources, say so.`
const rejectedBlock = reasons => (reasons.length ? `${REJECTED(reasons.join('\n'))}\n\n` : '')
const depLine = d => `- ${d.name}${d.version ? ` ${d.version}` : ''}${d.ecosystem ? ` (${d.ecosystem})` : ''}${d.imported_by_touched ? ' [imported by the changed files]' : ''}`

// ---- 3.3 step 2: restate (rewrites world-classes.md; the added rules are 3.5) ----
const RESTATE_PROMPT = reasons => `${rejectedBlock(reasons)}You are the restater. Your job is to restate each line of a change request as a problem class, with the means the request proposes and the target's names removed, to write search queries that ask how practitioners solve that class, and to pick the target's third-party dependencies that bear on the class.
You have no tools. Do not call any tool. You cannot open files or the repository; this prompt is everything you are given. You are kept away from the target so that you step up from the mechanism the request names to the kind of work it is.

One core rule: **do not ask about the parts of the mechanism the request names, or about the output format of a tool. Ask how practitioners do this kind of work.**

- Step up one level to the kind of work. Even if the request says "add X so that Y is judged", the problem class is neither how to build X nor how to read Y. Write it in the words of the work itself (shape of an example: "in test-first development, how to make a test that calls a not-yet-existing function fail for a target that must be compiled").
- Do not accept a means embedded in the request. Copy it to \`proposed\`, and keep it out of the problem class and the queries. Whether the means is good is decided later against the practice that is found. Write \`proposed\` in words of the means.
- Do not phrase the problem class so that it presupposes the means. Name the need, not the mechanism that answers it. Example: not "a mechanism that pauses processing and resumes it", but "a problem where the processing needs a person's answer partway through". A second reader checks your problem classes for this and sends them back.
- Which component does a part of the work (who raises a question, who starts a step, who holds the state, who waits) is part of the means too, even when the request states it as a given. Copy that split of roles to \`proposed\` and leave it open in the problem class and the queries, so that the practice found can be compared with it at the architecture layer. Example: not "when the build server has to tell the reviewer that a build broke", but "a problem where a reviewer has to learn that a build broke". A part given from outside the problem, which the request could not choose (a condition of the platform such as "a browser cannot keep a secret", or an existing interface the caller has no say over), is a condition of the problem, not a means: keep it in the problem class.
- A line may solve a problem that exists only because of a means the request chose in another line (shape of an example: a line that cleans up orphaned files exists only because another line chose to store an upload before its record is saved). Do not drop such a line, and do not treat the other line's means as a condition given from outside. Set \`arisesFrom\` to the number of the line whose means gives rise to this problem, and restate the problem class with that means stated as the premise it rests on ("when uploads are stored before their record is saved, how to ..."), still without this line's own means. State the premise in general words too: the identifiers and the means words the machine checks are not allowed there either. The line you name must have a means of its own in \`proposed\`. For every other line, set \`arisesFrom\` to 0.
- Do not write the target's names (paths, files, functions, fields, environment variables, component names, run ids) in \`problem\`, \`activity\`, or \`queries\`. The machine checks them against the identifiers in the request lines that the target defines and rejects the answer, naming the identifier it found. Names of third-party products and standards (a database, a protocol, a framework) are not the target's names. The same check rejects the words of the means listed below (names with a hyphen, an underscore, a digit, a dot or an inner capital, and runs of four or more kanji or katakana).
- Write queries in the general wording of the work, asking about practice, convention, and standards. Do not ask about the request's component names or a tool's output format.
- If one line spans two kinds of work, restate it as the one kind above both.
- In \`deps\`, name the dependencies, from the list below only and exactly as written there, whose own documentation would say how this class of problem is solved with them. A name not on the list is rejected. If the list marks some dependencies "imported by the changed files" and you pick none of them for a line, say why in one sentence in \`depsWhy\`; otherwise leave \`depsWhy\` empty.

## Request lines

These were taken by the machine from the request. They are all you are given.

${lines.map(l => `${l.n}. where: ${l.where}\n   text: ${l.text}`).join('\n')}

## Purpose

${str(A.purpose) || '(not given)'}
${means.length ? `
Means the request proposed (split from the purpose):

${means.map(m => `- ${m}`).join('\n')}
` : ''}
## Dependencies of the target

${deps.length ? deps.map(depLine).join('\n') : '(none found)'}
${str(A.deps_note) ? `\nNote from the machine that listed them: ${str(A.deps_note)}\n` : ''}
## How to answer

- In \`classes\`, give one entry for every request line above. \`n\` is the line number, 1 to ${lines.length}.
- \`problem\`: one sentence that restates the line as a problem class in the words of the work practitioners do.
- \`activity\`: a short name for the kind of work.
- \`proposed\`: the means the request proposed for this line, copied from the means above and from the line. Empty if it proposed none.
- \`arisesFrom\`: as above; 0 unless the problem exists only because of another line's means.
- \`queries\`: 1 to ${LIMITS.maxQueries} search queries per line that ask how practitioners solve this class (practice, convention, standards). Write them in English.
- \`deps\` and \`depsWhy\`: as above.
- Write \`problem\`, \`activity\`, \`proposed\`, and \`depsWhy\` in ${LANG}. Keep keys, enum values, identifiers, paths, commands, and error messages as they are.

Return only JSON that matches the output schema.`

// ---- 3.3 step 3: the second reader of the restated classes ----
const LEAK_PROMPT = items => `You check restated problem classes. Each item below has a problem class (problem, activity, queries) and, apart from it, the means a change request chose (proposed). A problem class must name the need without presupposing that means: a reader who sees only the problem class must not be led to the request's mechanism.

For each item, set \`presupposes\` true when the problem, the activity or a query assumes the means: it names the mechanism, its steps or its shape, even in plain words that are not identifiers. Example: "how to pause processing and resume it from where it stopped" presupposes pause-and-resume; "processing that needs a person's answer partway through" does not. A problem class that names which component does a part of the work (who raises a question, who starts a step, who holds the state) also presupposes the means when the request chose that component, even if the request states it as a given: "when the build server has to tell the reviewer that a build broke" fixes who tells; "a reviewer has to learn that a build broke" does not. Two things do not presuppose the means. First, a part given from outside the problem, which the request could not choose (a condition of the platform such as "a browser cannot keep a secret", or an existing interface the caller has no say over), may stay in the problem class. Second, the name of an established practice that names the kind of problem or change ("zero-downtime deployment", "backward-compatible API change", "cache invalidation") is not a means; the name of a mechanism that answers it ("blue-green deployment", "two-phase commit", "pause and resume") is. Third, an item marked "arises from the means of line N" is a problem that exists only because of the means the request chose in line N: that means is the premise the problem rests on and may stay in the problem class. Only the item's own means (proposed) must not be presupposed. When you set \`presupposes\` true, say why in one sentence in \`why\`, quoting the words that carry the means. Otherwise set it false and leave \`why\` empty. Write \`why\` in ${LANG}.
You have no tools. Do not call any tool.

${items.map(c => `## Item ${c.n}

- Problem: ${c.problem}
- Activity: ${c.activity}
${c.queries.map(q => `- Query: ${q}`).join('\n')}
- Means the request chose (proposed): ${c.proposed || '(none)'}${c.origin ? `
- Arises from the means of line ${c.origin.n} (the premise; it may stay): ${c.origin.proposed}` : ''}`).join('\n\n')}

Return one entry in \`items\` for every item above (\`n\` is the item number). Return only JSON that matches the output schema.`

// ---- 3.3 step 5: the searcher (rewrites the search half of parts/world-judge.md; the order and the layers are 3.4) ----
const LAYER_RULES = `## Layers

Every row compares at exactly one layer:
- \`architecture\`: who does what. How the parts are divided and which part owns the work.
- \`contract\`: what crosses a boundary. The shape of requests, responses and state between parts, and when each may be sent.
- \`implementation\`: how one part does its work inside.

If a counterpart has something to say at two layers, give two rows. Do not let one layer's answer stand for another layer's conclusion: what a contract allows does not say which part should do the work, and a general structure does not say what products do.`
const SEARCH_PROMPT = (c, reasons) => `${rejectedBlock(reasons)}You are the searcher. For the problem class below, find on the web how practitioners routinely solve it (practice, convention, standards), bring back excerpts, and return one row per counterpart you looked at.
Your only tools are web search and web fetch. You cannot read the repository or any file; this prompt is everything you are given.
You are given the problem class only: not the request, not the means it chose, not its purpose. Do not guess them, and do not search for them.

${QUERY_RULE}

## Problem class

- Problem: ${c.problem}
- Activity: ${c.activity}
${c.queries.map(q => `- Query: ${q}`).join('\n')}

## Dependencies of the target that bear on this class

${c.deps.length ? c.deps.map(depLine).join('\n') : '(none)'}

## Whom to look at, in this order

1. **Dependencies and upstream**: for each dependency above, look in its official documentation or official repository, for the version given, for the interface it offers to solve this class of problem. Give rows with \`kind\` "dependency" and \`name\` exactly as written above. Look at two layers for each dependency, not only the interface: also find which part its documentation has do the work in this class (which of its parts, or of the parts that use it, starts it, raises a question, holds the state or waits), and give that in a separate row at the \`architecture\` layer, even when you already gave a row for the interface. If it offers none, still give the row, with \`found\` false and, in \`searched\`, the queries you ran and the pages you opened. An upstream specification the class rests on (a protocol or an API that a dependency implements) goes in a row with \`kind\` "standard".
2. **Products of the same kind**: name two or more public products (open source) that have the same kind of problem, and give how each solves it (\`kind\` "product"). If you find none, give one row with \`kind\` "product", \`name\` empty, \`found\` false and the queries you ran in \`searched\`.
3. **Standards**: if a standard (an RFC, a specification, an official guide) covers this class, give the part that says how (\`kind\` "standard"). If there is none, give one row with \`kind\` "standard", \`name\` empty, \`found\` false and the queries you ran.

${LAYER_RULES}

## Excerpts and sources

- Copy each excerpt word for word from the fetched text. When you ask the fetch tool, ask it to "quote the relevant paragraph verbatim", and copy from the quote it returns. The machine fetches the same URL again; an excerpt that is not in the normalized text word for word (a paraphrase or a summary) is dropped, and so are the sources that point to it.
- Put in \`url\` only pages you actually fetched with the fetch tool. Do not write a URL that only appeared in a search result list.
- At most ${LIMITS.maxExcerpts} excerpts in total. Each is at least ${LIMITS.minExcerpt} characters. Spend them on the dependency rows first.
- State the practice from the excerpts. Where you find no source, write the practice from your own knowledge with empty \`sources\`. The machine sets the mark of whether the web confirmed a row from the sources that survive its check.
- \`not_applies\` says where the practice does not fit a problem of this class, shown by facts outside any one project. A row with a non-empty \`not_applies\` must cite at least one excerpt of its own; a row without one is sent back. Never use the current state of a project (its settings, CI, layout, or tools it lacks today) as a reason.
- Do not write the target's names (paths, files, functions, fields, environment variables, component names, run ids) in \`practice\` or in \`searched\`. The machine checks them and rejects the answer, naming what it found.

## How to answer

- \`excerpts\`: \`{id, url, excerpt}\`. \`id\` is a name such as x1, x2, unique within your answer.
- \`rows\`: \`{kind, name, version, layer, practice, sources, applies, not_applies, found, searched}\`.
  - \`version\`: the version of the dependency or the specification you read, or empty.
  - \`practice\`: how this counterpart solves the class at this layer, in 1 to 3 sentences. For a row with \`found\` false, what you looked for.
  - \`sources\`: the ids of the excerpts the row rests on. Empty if you use none.
  - \`applies\`: what kind of situation in this class the practice fits. \`not_applies\`: as above, or empty.
  - \`searched\`: the queries you ran and the URLs you opened for this row. Required when \`found\` is false.
- Write \`practice\`, \`applies\`, and \`not_applies\` in ${LANG}. Keep names, URLs, and excerpts as they are.

Return only JSON that matches the output schema.`

// ---- 3.3 step 6: the re-fetch of the excerpts (one command, relayed) ----
const RECHECK_PROMPT = command => `Run the command below once, exactly as written, and do nothing else. It is one line: keep it on one line and do not change a character of it. Each base64 word is one line of data with a checksum inside, and a word copied wrong is counted, not checked.

\`\`\`bash
${command}
\`\`\`

The command prints one JSON object. Return its ran, checked, kept, dropped (each {id, why}), garbled, over, offline and error as they are. If the command fails or prints no JSON, return ran false, checked 0, kept, dropped and garbled empty, over 0, offline false, and the error text in error.`

// ---- 3.3 step 7: the general structure, by the blind eye (the first half of W2_PROMPT, for one problem class) ----
const GENERAL_PROMPT = (c, noTools) => `In general, how is a system that has the problem below divided into parts, what flows between the parts, where is the source of truth kept, which way do the dependencies point, and where are the boundaries drawn? Give each together with the reason it is placed that way. Describe structure, not solutions or tools.

Problem: ${c.problem}

Write it in \`general\`, in ${LANG}. In \`layer\`, give the layer your description is at: architecture (who does what), contract (what crosses a boundary) or implementation (how one part works inside). If you cannot say anything beyond statements that would fit any system, set \`notFound\` true and say so in general.${noTools ? `

Do not use any tool. Think only from what is given here.` : ''}`

// ---- 3.3 step 8: the comparer (rewrites the judging half of parts/world-judge.md) ----
// The form of a challenge, written in LANG. In run 2 on #2637 (attention/docs/measures/2637-world-result.md) 87 of 103
// Japanese challenges kept the English wording of the form, some with the letters X and Y left in.
const ENGLISH = /^en(glish)?$/i.test(LANG.trim())
const challengeForm = form => ENGLISH
  ? `in the form "${form}"`
  : `in ${LANG}, saying in ${LANG} what this English form says: "${form}". The form is a shape, not words to quote: do not copy its English words, and write out what X, Y and N stand for instead of leaving the letters`
const FORM_WORDS = /\bThe request (does|has to do)\b|\bChoose Y unless\b|\bwhere the problem does not arise\b|\bbecause of the means of line\b/i
const FORM_LETTER = /(^|[^A-Za-z0-9_.\-/])[XY]($|[^A-Za-z0-9_.\-/])/
function challengeProblem(text) {
  if (ENGLISH) return ''
  const t = str(text)
  if (FORM_WORDS.test(t)) return `the challenge copies the English words of the form; write it in ${LANG}`
  if (FORM_LETTER.test(t)) return `the challenge leaves a letter of the form (X or Y); write out what it stands for`
  return ''
}
const rowLine = r => `${r.id} [${r.against.kind}${r.against.name ? ` ${r.against.name}` : ''}${r.against.version ? ` ${r.against.version}` : ''} · ${r.layer} · ${r.found ? r.basis : 'nothing found'}]
   practice: ${r.practice || '(none)'}${r.applies ? `\n   applies: ${r.applies}` : ''}${r.not_applies ? `\n   not_applies: ${r.not_applies}${r.not_applies_unchecked ? ' (its excerpts could not be confirmed)' : ''}` : ''}`
const memberLine = m => m.level === 'origin'
  ? `- line ${m.n} (${m.where}), judged at the level of line ${m.arisesFrom}: its problem, which arises from the means of line ${m.arisesFrom}: ${m.problem}\n   its means: ${m.proposed || '(none proposed)'}`
  : `- line ${m.n} (${m.where}): ${m.proposed || '(none proposed)'}${m.arisesFrom ? ` (this problem arises from the means of line ${m.arisesFrom})` : ''}`
const COMPARE_PROMPT = (c, rows, reasons) => `${rejectedBlock(reasons)}You compare. Below are a problem class, the means a change request chose for it (one or more request lines), and rows that each say how one counterpart solves this class at one layer: a dependency of the target, a product of the same kind, a standard, or a general structure drawn by someone who did not see the request.
You have no tools. Do not call any tool. This prompt is everything you are given.

For every pair of a row and a request line, decide whether the request's means is the same as that row's practice, at that row's layer:
- \`same\`: the means does what the practice does at that layer.
- \`differs\`: the means does it another way at that layer. Write \`challenge\` ${challengeForm('The request does X; <the counterpart> does Y. Choose Y unless …')}, at least ${LIMITS.minChallenge} characters, naming the condition under which X would be the right choice.
- \`none\`: the request line proposes no means, or the row found nothing (marked "nothing found").
Do not decide whether differing is acceptable; a later step asks that. There is no fourth value.

A request line marked "judged at the level of line N" has a problem that exists only because of the means the request chose in line N, and this class is line N's problem. For such a line, decide whether the counterpart, with its practice for this class, has that problem at all. If its practice does not give rise to the problem, the verdict is \`differs\`, with \`challenge\` ${challengeForm('The request has to do X because of the means of line N; <the counterpart> does Y, where the problem does not arise. Choose Y unless …')}. If the counterpart has the same problem, compare the line's means with how the counterpart handles it, as for any other line. "The problem does not arise" is an answer only when the counterpart's practice handles this class (line N's problem) in another way and that way avoids the problem; a counterpart that takes no part in this class (one that only makes values, or that sits on no side of this boundary) does not avoid the problem, it is merely absent: compare the line's means with what that counterpart does, as for any other line.

${LAYER_RULES}

## Problem class

${c.problem}

## Request lines and the means each chose

${c.members.map(memberLine).join('\n')}

## Rows

${rows.map(rowLine).join('\n')}

## How to answer

- \`items\`: one entry for every pair of a row above and a request line above: \`{row, n, verdict, challenge, why}\`. \`row\` is the row id (R1, G, ...), \`n\` the line number.
- \`challenge\`: only for \`differs\`; empty otherwise. \`why\`: one sentence on what decided the verdict.
- Write \`challenge\` and \`why\` in ${LANG}.

Return only JSON that matches the output schema.`

// ---- acceptance (3.7) ----
const depNames = new Map(deps.map(d => [d.name.toLowerCase(), d]))
// third-party names and versions are not the target's names (query-rule.md), so they are not counted as identifiers
// (an npm name such as @scope/pkg is split by the identifier rule into scope/pkg, scope and pkg, so its tokens count too)
const thirdParty = new Set(deps.flatMap(d => [d.name, d.version, ...tokensOf(d.name)].filter(Boolean).map(x => String(x).toLowerCase())))
const OWN = new Set(ownNames ?? [])
const BANNED = new Set([...bannedTokens(lines)].filter(t => OWN.has(t) && !thirdParty.has(t.toLowerCase())))
const MEANS_WORDS = meansWords(means)
const meansHits = text => MEANS_WORDS.filter(w => String(text ?? '').toLowerCase().includes(w.toLowerCase()))
const touchedDeps = deps.filter(d => d.imported_by_touched === true)

const restate = { rounds: 0, identifierHits: 0, meansHits: 0, leakSentBack: 0, leakAgents: 0 }
// problems of one restated line (machine), by line number
function restateProblems(r) {
  const general = [], byN = new Map()
  const add = (n, msg) => { if (!byN.has(n)) byN.set(n, []); byN.get(n).push(msg) }
  const got = Array.isArray(r?.classes) ? r.classes : null
  if (!got) return { general: ['the answer has no classes'], byN, rows: new Map() }
  const rows = new Map()
  got.forEach((c, i) => {
    const n = c?.n
    if (!Number.isInteger(n) || n < 1 || n > lines.length) { general.push(`classes[${i}]: n must be a request line number, 1 to ${lines.length}`); return }
    if (rows.has(n)) { add(n, `line ${n}: a second entry for the same line`); return }
    rows.set(n, c)
    const head = `line ${n}`
    for (const key of ['problem', 'activity']) if (blank(c[key])) add(n, `${head}: ${key} is empty`)
    const qs = Array.isArray(c.queries) ? c.queries.filter(q => !blank(q)) : []
    if (!qs.length || qs.length > LIMITS.maxQueries || qs.length !== (c.queries ?? []).length) add(n, `${head}: queries must be 1 to ${LIMITS.maxQueries} non-empty strings`)
    for (const [key, text] of [['problem', c.problem], ['activity', c.activity], ...qs.map(q => ['queries', q])]) {
      const ids = textProblems(text, BANNED)
      if (ids.length) { restate.identifierHits += ids.length; add(n, `${head}: ${key} has identifiers of the request lines ${JSON.stringify(ids)}`) }
      const mw = meansHits(text)
      if (mw.length) { restate.meansHits += mw.length; add(n, `${head}: ${key} has words of the means ${JSON.stringify(mw)}`) }
    }
    if (!Number.isInteger(c.arisesFrom) || c.arisesFrom < 0 || c.arisesFrom > lines.length || c.arisesFrom === n) {
      add(n, `${head}: arisesFrom must be 0 or the number of another request line, 1 to ${lines.length}`)
    }
    const picked = Array.isArray(c.deps) ? c.deps : []
    const stray = picked.filter(d => !depNames.has(String(d).toLowerCase()))
    if (stray.length) add(n, `${head}: deps ${JSON.stringify(stray)} are not in the dependency list`)
    if (touchedDeps.length && !picked.some(d => touchedDeps.some(t => t.name.toLowerCase() === String(d).toLowerCase())) && blank(c.depsWhy)) {
      add(n, `${head}: no dependency imported by the changed files is picked, and depsWhy does not say why`)
    }
  })
  for (const l of lines) if (!rows.has(l.n)) add(l.n, `line ${l.n}: no entry (give one entry for every request line)`)
  for (const [n, c] of rows) {
    const o = Number.isInteger(c.arisesFrom) && c.arisesFrom > 0 && c.arisesFrom !== n ? rows.get(c.arisesFrom) : null
    if (o === undefined) add(n, `line ${n}: arisesFrom names line ${c.arisesFrom}, which has no entry`)
    else if (o && blank(o.proposed)) add(n, `line ${n}: arisesFrom names line ${c.arisesFrom}, which proposes no means (name the line whose means gives rise to this problem, or set 0)`)
    else if (o && o.arisesFrom === n) add(n, `line ${n}: arisesFrom names line ${c.arisesFrom}, whose arisesFrom names line ${n} back (one of the two must be 0)`)
  }
  return { general, byN, rows }
}

phase('Restate')
const restateReasons = []
let restated = new Map()   // n -> accepted restated line
const restateMissing = new Map()   // n -> why
for (let round = 1; round <= LIMITS.tries; round++) {
  restate.rounds = round
  const r = await run('Restate', `Restate ${round}`, RESTATE_PROMPT(restateReasons), { schema: RESTATE, phase: 'Restate', ...M('Restate') })
  const { general, byN, rows } = r ? restateProblems(r) : { general: ['the restater returned nothing'], byN: new Map(), rows: new Map() }
  // the second reader looks only at lines the machine passed
  const passed = lines.map(l => l.n).filter(n => rows.has(n) && !byN.has(n))
  if (passed.length) {
    restate.leakAgents++
    const items = passed.map(n => {
      const c = rows.get(n), o = c.arisesFrom > 0 ? rows.get(c.arisesFrom) : null
      return { n, ...c, queries: c.queries.map(str), origin: o ? { n: c.arisesFrom, proposed: str(o.proposed) } : null }
    })
    const leak = await run('Leak', `Leak ${round}`, LEAK_PROMPT(items), { schema: LEAK, phase: 'Restate', ...M('Leak') })
    const seen = new Set()
    for (const it of Array.isArray(leak?.items) ? leak.items : []) {
      if (!passed.includes(it?.n) || seen.has(it.n)) continue
      seen.add(it.n)
      if (it.presupposes === true) {
        restate.leakSentBack++
        if (!byN.has(it.n)) byN.set(it.n, [])
        byN.get(it.n).push(`line ${it.n}: the problem class presupposes the means (a second reader): ${str(it.why) || 'no reason given'}`)
      }
    }
    // a line the second reader did not answer is not counted as checked: it is sent back like a failed one
    for (const n of passed) if (!seen.has(n)) {
      if (!byN.has(n)) byN.set(n, [])
      byN.get(n).push(`line ${n}: the second reader did not answer for this line`)
    }
  }
  const bad = lines.map(l => l.n).filter(n => byN.has(n) || !rows.has(n))
  if (!general.length && !bad.length) { restated = new Map(lines.map(l => [l.n, rows.get(l.n)])); break }
  if (round === LIMITS.tries) {
    for (const l of lines) {
      if (rows.has(l.n) && !byN.has(l.n)) restated.set(l.n, rows.get(l.n))
      else restateMissing.set(l.n, `restate gave up after ${LIMITS.tries} rounds: ${[...general, ...(byN.get(l.n) ?? [])].join(' / ') || 'no entry'}`)
    }
    break
  }
  restateReasons.push(...general.map(g => `round ${round}: ${g}`), ...bad.flatMap(n => (byN.get(n) ?? [`line ${n}: no entry`]).map(m => `round ${round}: ${m}`)))
}

// ---- 3.3 step 4: classes, in the order they appear, no cap ----
const normProblem = s => String(s).toLowerCase().replace(/\s+/g, ' ').trim()
const classMap = new Map()
const classOf = new Map()   // n -> class id of the line's own class
for (const l of lines) {
  const c = restated.get(l.n)
  if (!c) continue
  const id = `w-${fnv(normProblem(c.problem))}`
  if (!classMap.has(id)) {
    classMap.set(id, { id, problem: str(c.problem), activity: str(c.activity), queries: c.queries.map(str).filter(Boolean),
      deps: [], members: [] })
  }
  const k = classMap.get(id)
  for (const d of Array.isArray(c.deps) ? c.deps : []) {
    const dep = depNames.get(String(d).toLowerCase())
    if (dep && !k.deps.includes(dep)) k.deps.push(dep)
  }
  k.members.push({ n: l.n, where: l.where, proposed: str(c.proposed), depsWhy: str(c.depsWhy), level: 'line', arisesFrom: c.arisesFrom > 0 ? c.arisesFrom : 0 })
  classOf.set(l.n, id)
}
// a line whose problem arises from another line's means is also compared in that line's class, at its level (3.3 step 4)
const originNotes = []
for (const l of lines) {
  const c = restated.get(l.n), m = c?.arisesFrom > 0 ? c.arisesFrom : 0
  if (!m) continue
  if (!classOf.has(m)) { originNotes.push(`line ${l.n}: arises from line ${m}, which has no class, so it is not compared at that level`); continue }
  if (classOf.get(m) === classOf.get(l.n)) continue   // the same class: already compared there
  classMap.get(classOf.get(m)).members.push({ n: l.n, where: l.where, proposed: str(c.proposed), depsWhy: '', level: 'origin', arisesFrom: m, problem: str(c.problem) })
}
const classes = [...classMap.values()]
counts.classes = classes.length
log(`${classes.length} classes from ${restated.size} of ${lines.length} request lines${restateMissing.size ? ` (${restateMissing.size} lines given up in restate)` : ''}`)

// ---- 3.3 steps 5 and 6 ----
function searchProblems(c, r) {
  const out = []
  const xs = Array.isArray(r?.excerpts) ? r.excerpts : []
  const rows = Array.isArray(r?.rows) ? r.rows : null
  if (!rows) return ['the answer has no rows']
  const ids = new Set()
  xs.forEach((x, i) => {
    if (blank(x?.id) || typeof x?.url !== 'string' || typeof x?.excerpt !== 'string') out.push(`excerpts[${i}] is not {id, url, excerpt} with a non-empty id`)
    else if (ids.has(x.id)) out.push(`excerpts[${i}]: id ${x.id} appears twice`)
    else {
      ids.add(x.id)
      if (x.excerpt.trim().length < LIMITS.minExcerpt) out.push(`excerpts[${i}] (${x.id}) is shorter than ${LIMITS.minExcerpt} characters`)
    }
  })
  rows.forEach((w, i) => {
    const head = `rows[${i}] (${w?.kind} ${w?.name || '-'}, ${w?.layer})`
    if (!KINDS.includes(w?.kind)) out.push(`${head}: kind is one of ${KINDS.join(', ')}`)
    if (!LAYERS.includes(w?.layer)) out.push(`${head}: layer is one of ${LAYERS.join(', ')}`)
    const src = Array.isArray(w?.sources) ? w.sources : []
    const stray = src.filter(s => !ids.has(s))
    if (stray.length) out.push(`${head}: sources ${JSON.stringify(stray)} are not ids of your excerpts`)
    if (!blank(w?.not_applies) && !src.some(s => ids.has(s))) out.push(`${head}: not_applies is not empty, so the row must cite at least one excerpt of its own`)
    const searched = Array.isArray(w?.searched) ? w.searched.filter(s => !blank(s)) : []
    if (w?.found === false && !searched.length) out.push(`${head}: found is false, so searched must list the queries you ran and the pages you opened`)
    if (w?.found === true && blank(w?.practice)) out.push(`${head}: practice is empty`)
    for (const [key, text] of [['practice', w?.practice], ...searched.map(s => ['searched', s])]) {
      const hit = textProblems(text, BANNED)
      if (hit.length) out.push(`${head}: ${key} has identifiers of the request lines ${JSON.stringify(hit)}`)
    }
  })
  for (const d of c.deps) {
    if (!rows.some(w => w?.kind === 'dependency' && String(w?.name).toLowerCase() === d.name.toLowerCase())) {
      out.push(`no row with kind dependency and name ${d.name} (give one even if it offers no interface for this class)`)
    }
  }
  if (!rows.some(w => w?.kind === 'product' && (w.found === true || (Array.isArray(w.searched) && w.searched.some(s => !blank(s)))))) {
    out.push('no product row: name a product of the same kind, or give a product row with found false and the queries you ran')
  }
  return out
}

// one line, each JSON line as one base64 word: the headless run's rule Bash(bash <run-python.sh> <script> --b64 *) matches it
// (a here-document did not match and was denied, run 1 of PR 2555), and a word copied wrong spoils only its own line
const EXCERPT_COMMAND = (c, items) => [
  `bash ${shq(A.excerptCheck.runPython)} ${shq(A.excerptCheck.script)} --b64`,
  b64(JSON.stringify({ class: c.id, count: items.length })),
  ...items.map(x => b64(JSON.stringify([x.id, x.url, x.excerpt, fnv(`${x.id}\n${x.url}\n${x.excerpt}`)]))),
].join(' ')

// status of each excerpt id: kept | dropped | unchecked, with why. A plain object, not a Map: a value returned
// through parallel() or a pipeline stage comes back as JSON, and a Map turns into {} (run 1 of PR 2555)
async function recheck(c, r, round) {
  const all = (r.excerpts ?? []).filter(x => !blank(x?.id))
  const sent = all.slice(0, LIMITS.maxExcerpts)
  const status = Object.fromEntries(all.map(x => [x.id, { state: 'unchecked', why: 'over the excerpt cap' }]))
  const tally = { kept: 0, dropped: 0, unchecked: 0, garbled: 0, over: all.length - Math.min(all.length, LIMITS.maxExcerpts) }
  if (!sent.length) { tally.unchecked = all.length - tally.over; return { status, tally, ran: true } }
  const got = await run('Recheck', `Recheck ${c.id} ${round}`, RECHECK_PROMPT(EXCERPT_COMMAND(c, sent)), { schema: RECHECK, phase: 'Search', ...M('Recheck') })
  const ids = new Set(sent.map(x => x.id))
  for (const x of sent) status[x.id] = { state: 'unchecked', why: 'the re-fetch did not report it' }
  // a run the agent did not make, or whose count differs from what was sent (a line lost in the copy), is not trusted
  if (!got || got.ran !== true || got.checked !== sent.length) {
    tally.unchecked = all.length - tally.over
    return { status, tally, ran: false, error: str(got?.error) || 'the re-fetch did not run' }
  }
  const garbled = new Set((got.garbled ?? []).filter(id => ids.has(id)))
  for (const id of garbled) status[id] = { state: 'unchecked', why: 'the line was copied wrong' }
  for (const id of got.kept ?? []) if (ids.has(id) && !garbled.has(id)) status[id] = { state: 'kept', why: '' }
  for (const d of got.dropped ?? []) {
    if (!ids.has(d?.id) || garbled.has(d.id)) continue
    // no page reached at all: the network is off for the script, so nothing was checked (3.6)
    status[d.id] = got.offline ? { state: 'unchecked', why: `no page could be fetched: ${str(d.why)}` } : { state: 'dropped', why: str(d.why) }
  }
  for (const x of all) {
    const s = status[x.id].state
    tally[s]++
  }
  tally.unchecked -= tally.over   // the over-cap ones are counted in over, not in unchecked
  tally.garbled = garbled.size   // a part of unchecked, not added to the total (kept + dropped + unchecked + over)
  return { status, tally, ran: true, offline: got.offline === true }
}

// rows whose dependency rows' excerpts were all dropped (not unchecked): sent back to the searcher once (3.3 step 6)
const depsAllDropped = (r, status) => {
  const cited = (r.rows ?? []).filter(w => w.kind === 'dependency').flatMap(w => w.sources ?? [])
  return cited.length > 0 && cited.every(id => status[id]?.state === 'dropped')
}

async function searchClass(c) {
  const reasons = []
  let best = null, resent = false
  for (let round = 1; round <= LIMITS.tries; round++) {
    const r = await run('Search', `Search ${c.id} ${round}`, SEARCH_PROMPT(c, reasons), { schema: SEARCH, phase: 'Search', ...M('Search') })
    if (!r) { reasons.push(`round ${round}: the searcher returned nothing`); continue }
    const bad = searchProblems(c, r)
    if (bad.length) { reasons.push(...bad.map(b => `round ${round}: ${b}`)); continue }
    const checked = await recheck(c, r, round)
    best = { r, checked, round }
    if (!resent && round < LIMITS.tries && depsAllDropped(r, checked.status)) {
      resent = true
      const why = Object.entries(checked.status).filter(([, s]) => s.state === 'dropped').map(([id, s]) => `${id}: ${s.why}`)
      reasons.push(`round ${round}: every excerpt cited by the dependency rows was dropped when the machine fetched the same URL again (${why.join('; ')}). Fetch the dependency's own pages again and copy the excerpts word for word.`)
      continue
    }
    break
  }
  return best ? { ...best, reasons } : { missing: `search gave up after ${LIMITS.tries} rounds: ${reasons.join(' / ')}` }
}

async function askGeneral(c) {
  const judge = A.roles?.General ?? A.blindJudge
  // a plugin's blind-judge agent keeps its own model; the headless role and the default agent take the fallback model
  const opts = { schema: GENERAL, phase: 'Search', agentType: judge ?? 'general-purpose', ...(A.blindJudge && !A.roles?.General ? {} : M('Generalfallback')) }
  return run('General', `General ${c.id}`, GENERAL_PROMPT(c, !judge), opts)
}

// ---- 3.3 step 8 ----
function compareProblems(c, rows, r) {
  const out = []
  const got = Array.isArray(r?.items) ? r.items : null
  if (!got) return { out: ['the answer has no items'], pairs: new Map() }
  const byRow = new Map(rows.map(w => [w.id, w]))
  const members = new Map(c.members.map(m => [m.n, m]))
  const pairs = new Map()
  got.forEach((it, i) => {
    const w = byRow.get(it?.row), m = members.get(it?.n)
    if (!w || !m) { out.push(`items[${i}]: row must be one of ${[...byRow.keys()].join(', ')} and n one of ${[...members.keys()].join(', ')}`); return }
    const key = `${w.id}/${m.n}`
    if (pairs.has(key)) { out.push(`items[${i}]: a second entry for row ${w.id} and line ${m.n}`); return }
    pairs.set(key, it)
    const head = `row ${w.id}, line ${m.n}`
    const noneDue = !m.proposed || !w.found
    if (!VERDICTS.includes(it.verdict)) out.push(`${head}: verdict is one of ${VERDICTS.join(', ')}`)
    else if (noneDue && it.verdict !== 'none') out.push(`${head}: verdict must be none (${!m.proposed ? 'the line proposes no means' : 'the row found nothing'})`)
    else if (!noneDue && it.verdict === 'none') out.push(`${head}: verdict none is only for a line that proposes no means or a row that found nothing`)
    else if (it.verdict === 'differs' && str(it.challenge).length < LIMITS.minChallenge) out.push(`${head}: differs needs a challenge ${ENGLISH ? '("The request does X; ... does Y. Choose Y unless …") ' : `(in ${LANG}: what the request does, what the counterpart does, and the condition under which the request's way is right) `}of at least ${LIMITS.minChallenge} characters`)
    else if (it.verdict === 'differs' && challengeProblem(it.challenge)) out.push(`${head}: ${challengeProblem(it.challenge)}`)
  })
  for (const w of rows) for (const m of c.members) if (!pairs.has(`${w.id}/${m.n}`)) out.push(`no entry for row ${w.id} and line ${m.n}`)
  return { out, pairs }
}

const excerptTally = { kept: 0, dropped: 0, unchecked: 0, garbled: 0, over: 0 }
const searchNotes = []
async function classRows(c) {
  const [found, general] = await parallel([() => searchClass(c), () => askGeneral(c)])
  if (!found || found.missing) return { c, missing: found?.missing ?? 'the search stage failed' }
  const { r, checked } = found
  for (const k of Object.keys(excerptTally)) excerptTally[k] += checked.tally[k] ?? 0
  if (checked.ran === false) searchNotes.push(`${c.id}: excerpts not checked (${checked.error})`)
  if (checked.offline) searchNotes.push(`${c.id}: the re-fetch reached no page (network off for the script?)`)
  const byId = new Map((r.excerpts ?? []).map(x => [x.id, x]))
  const rows = r.rows.map((w, i) => {
    const cited = [...new Set(w.sources ?? [])]
    const kept = cited.filter(id => checked.status[id]?.state === 'kept').map(id => ({ id, url: byId.get(id).url, excerpt: byId.get(id).excerpt }))
    return {
      id: `R${i + 1}`,
      against: { kind: w.kind, name: str(w.name), version: str(w.version) },
      layer: w.layer, practice: str(w.practice), sources: kept, basis: kept.length ? 'web' : 'knowledge',
      applies: str(w.applies), not_applies: str(w.not_applies),
      // the row had excerpts, but none survived the re-fetch: verify must not use it as "does not apply" (3.4)
      not_applies_unchecked: !blank(w.not_applies) && kept.length === 0,
      found: w.found === true, searched: (w.searched ?? []).map(str).filter(Boolean),
    }
  })
  if (general && !blank(general.general)) {
    rows.push({ id: 'G', against: { kind: 'general', name: 'blind', version: '' }, layer: LAYERS.includes(general.layer) ? general.layer : 'architecture',
      practice: str(general.general), sources: [], basis: 'knowledge', applies: '', not_applies: '', not_applies_unchecked: false,
      found: general.notFound !== true, searched: [] })
  }
  return { c, rows, searchRounds: found.round, searchReasons: found.reasons }
}

async function compareClass(prev) {
  if (!prev || prev.missing) return prev
  const { c, rows } = prev
  const reasons = []
  for (let round = 1; round <= LIMITS.tries; round++) {
    const r = await run('Compare', `Compare ${c.id} ${round}`, COMPARE_PROMPT(c, rows, reasons), { schema: COMPARE, phase: 'Compare', ...M('Compare') })
    const { out, pairs } = r ? compareProblems(c, rows, r) : { out: ['the comparer returned nothing'], pairs: new Map() }
    if (!out.length) return { ...prev, pairs: Object.fromEntries(pairs) }   // out of the pipeline as JSON: no Map
    reasons.push(...out.map(o => `round ${round}: ${o}`))
  }
  return { c, missing: `compare gave up after ${LIMITS.tries} rounds: ${reasons.join(' / ')}` }
}

phase('Search')
const done = await pipeline(classes, c => classRows(c), prev => compareClass(prev))

// ---- 3.3 step 9: finish (3.8) ----
const outRows = [], missing = []
for (const [n, why] of restateMissing) missing.push({ n, why })
const atOrigin = new Map()   // n -> comparisons made in the class of the line it arises from
const ownFailed = new Map()   // n -> why its own class gave up
const cmpOf = (d, w, m, c) => {
  const p = d.pairs[`${w.id}/${m.n}`]
  return { level: m.level, class_id: c.id, against: w.against, layer: w.layer, practice: w.practice, sources: w.sources, basis: w.basis,
    applies: w.applies, not_applies: w.not_applies, not_applies_unchecked: w.not_applies_unchecked,
    found: w.found, searched: w.searched,
    verdict: p.verdict, challenge: p.verdict === 'differs' ? str(p.challenge) : '', why: str(p.why) }
}
done.forEach((d, i) => {
  const c = classes[i]
  const why = !d ? 'the class stage failed' : d.missing
  for (const m of c.members) {
    if (m.level === 'origin') {
      if (why) originNotes.push(`line ${m.n}: not compared at the level of line ${m.arisesFrom} (${why})`)
      else atOrigin.set(m.n, d.rows.map(w => cmpOf(d, w, m, c)))
      continue
    }
    if (why) { ownFailed.set(m.n, why); continue }
    outRows.push({
      n: m.n, where: m.where, class_id: c.id, problem: c.problem, activity: c.activity, queries: c.queries,
      deps: c.deps.map(x => x.name), depsWhy: m.depsWhy, proposed: m.proposed, arises_from: m.arisesFrom || null,
      comparisons: d.rows.map(w => cmpOf(d, w, m, c)),
    })
  }
})
// a line whose own class gave up still returns, with only the comparisons at the level of the line it arises from
for (const [n, why] of ownFailed) {
  const at = atOrigin.get(n)
  if (!at) { missing.push({ n, why }); continue }
  const c = classes.find(k => k.id === classOf.get(n)), m = c.members.find(x => x.n === n && x.level === 'line')
  originNotes.push(`line ${n}: its own class gave up (${why}); only the comparisons at the level of line ${m.arisesFrom} are returned`)
  outRows.push({ n, where: m.where, class_id: c.id, problem: c.problem, activity: c.activity, queries: c.queries,
    deps: c.deps.map(x => x.name), depsWhy: m.depsWhy, proposed: m.proposed, arises_from: m.arisesFrom, comparisons: [] })
}
for (const r of outRows) if (atOrigin.has(r.n)) r.comparisons.push(...atOrigin.get(r.n))
outRows.sort((a, b) => a.n - b.n)
missing.sort((a, b) => a.n - b.n)
if (missing.length) log(`${missing.length} of ${lines.length} request lines have no rows: ${missing.map(m => m.n).join(', ')}`)
const status = !outRows.length ? 'failed' : missing.length ? 'partial' : 'ok'
const reason = [
  ...(status === 'failed' ? ['no request line got rows'] : []),
  ...(missing.length ? [`${missing.length} request lines given up (see missing)`] : []),
  ...searchNotes,
  ...originNotes,
].join(' / ')
return {
  ok: status === 'ok', status, reason, pr: A.pr ?? null, head: A.head ?? null,
  rows: outRows, missing, excerpts: excerptTally, deps_note: str(A.deps_note), restate, counts,
}
