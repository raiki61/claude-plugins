"""ページの雛形（attention/templates/*.html）の中の JS を、ブラウザ無しに node で呼ぶ試験の部品。

- calc(雛形, 式): 雛形の `<script id="calc">`（DOM に触らない計算の塊。`const CALC = {...}`）だけを node の vm で読み、
  CALC を使う JS の式の値を JSON で返す。式の中で作った物の同一性（`a === b`）も見られる。
- body(雛形, 関数の名前): ページの関数の字。計算を呼ぶか（配線）だけを見るのに使う。
- render(雛形, 材料の id, 材料): 雛形のスクリプト（JSON の塊でない物）を、小さな偽の DOM の上で順に走らせ、
  描いた字を文書の順に並べて返す。偽の DOM が持つのは getElementById（材料の塊と id="app"）・createElement・
  createTextNode・Node・append・className・setAttribute・textContent だけなので、これで足りるページ（reflect）にだけ使う。

node が無ければ NODE は None。使う試験は `@unittest.skipUnless(page_js.NODE, "node が無い")` を付ける。
"""

import json
import pathlib
import re
import shutil
import subprocess

NODE = shutil.which("node")

SCRIPT_RE = re.compile(r"<script(?![^>]*application/json)([^>]*)>(.*?)</script>", re.S)

# 標準入力の JSON（{"mode", "scripts", "expr" か "data_id"・"payload"}）を読み、結果の JSON を 1 行で出す
RUNNER = r"""
const vm = require('vm');
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', c => { raw += c; });
process.stdin.on('end', () => {
  const job = JSON.parse(raw);
  if (job.mode === 'calc') {
    const got = vm.runInNewContext(job.scripts.join('\n;\n') + '\n;(' + job.expr + '\n)', {});
    process.stdout.write(JSON.stringify(got === undefined ? null : got));
    return;
  }
  class Node { constructor() { this.childNodes = []; } append(...ks) { for (const k of ks) this.childNodes.push(k instanceof Node ? k : new Text(String(k))); }
    get textContent() { return this.childNodes.map(c => c.textContent).join(''); } }
  class Text extends Node { constructor(t) { super(); this.data = t; } get textContent() { return this.data; } }
  class Element extends Node { constructor(tag) { super(); this.tagName = tag; this.className = ''; this.attrs = {}; }
    setAttribute(k, v) { this.attrs[k] = String(v); } }
  const app = new Element('main');
  const slot = { textContent: JSON.stringify(job.payload) };
  const document = { createElement: t => new Element(t), createTextNode: t => new Text(String(t)),
    getElementById: id => (id === 'app' ? app : id === job.data_id ? slot : null) };
  const ctx = vm.createContext({ document, Node });
  for (const s of job.scripts) vm.runInContext(s, ctx);
  const runs = [];
  const walk = n => { if (n instanceof Text) { if (n.data.trim()) runs.push(n.data); } else n.childNodes.forEach(walk); };
  walk(app);
  process.stdout.write(JSON.stringify(runs));
});
"""


def _scripts(template):
    return [(attrs, body) for attrs, body in SCRIPT_RE.findall(pathlib.Path(template).read_text(encoding="utf-8"))]


def _run(job):
    got = subprocess.run([NODE, "-e", RUNNER], input=json.dumps(job), capture_output=True, text=True, encoding="utf-8")
    if got.returncode != 0:
        raise AssertionError(f"node が落ちた: {got.stderr.strip()}")
    return json.loads(got.stdout)


def body(template, name):
    """雛形の中の関数 name（`function name(` の行から、同じ字下げの `}` の行まで）の字を返す。

    計算は calc で呼んで確かめ、ページがその計算を本当に呼ぶか（配線）だけをこの字で見る。無ければ AssertionError。
    """
    lines = pathlib.Path(template).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:async )?function " + re.escape(name) + r"\(", line)
        if m:
            end = next((j for j in range(i + 1, len(lines)) if lines[j] == m.group(1) + "}"), None)
            if end is None:
                raise AssertionError(f"{template} の関数 {name} の閉じが見つからない")
            return "\n".join(lines[i:end + 1])
    raise AssertionError(f"{template} に関数 {name} が無い")


def calc(template, expr):
    """雛形の計算の塊（`<script id="calc">`）を読み、JS の式 expr の値を返す。"""
    blocks = [body for attrs, body in _scripts(template) if 'id="calc"' in attrs]
    if len(blocks) != 1:
        raise AssertionError(f'{template} に <script id="calc"> がちょうど 1 つ無い（{len(blocks)} 個）')
    return _run({"mode": "calc", "scripts": blocks, "expr": expr})


def render(template, data_id, payload):
    """雛形のスクリプトを偽の DOM の上で走らせ、id="app" に描いた字の並びを返す。"""
    return _run({"mode": "render", "scripts": [body for _, body in _scripts(template)], "data_id": data_id, "payload": payload})
