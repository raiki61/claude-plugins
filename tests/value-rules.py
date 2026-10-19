#!/usr/bin/env python3
"""機械が読む値の受け渡しの標準（docs/standards/machine-readable-values.md）の決まり 3・4 を、ファイルごとの数で守らせる。

今ある物を一度に直せないので、ファイルごとの数を基準（tests/value-rules-baseline.json）に控え、増えたら止める。減ったときも、
基準を書き直すまで止める（減った分をそのまま残すと、後で同じ数まで増やせてしまう。scripts/terms.py と同じ形。betterer の CI の回と
同じ考え: https://phenomnomnominal.github.io/betterer/docs/running-betterer ）。数え方は標準の「守らせ方」のとおりで、
Python の構文木（ast）と注記の字句（tokenize）だけで決める。

- 見るファイル: attention・convergence-loops・gates・graphloops・tiers・works-dispatch と、ルートの scripts/・tests/ の、git に載った .py。
- rule3: CJK の字（ひらがな・カタカナ・漢字・全角の記号）を含む文字列の定数が、比べる式（==・!=・in・not in）の左右のどちらか
  （右がタプル・リスト・集合ならその中も）、startswith・endswith の引数（タプルの中も）、re.compile・re.search・re.match・
  re.fullmatch・re.findall・re.sub・re.split の 1 つ目の引数（pattern= の名前つきも。`import re as …` の別名と
  `from re import …` の名前で呼んだ物も）、に入る所を 1 件。f-string・変数に入れてから使う物・match 文は数えない。
- rule4: 本体が pass か continue の 1 文だけの except を 1 件。except の行の行末か、本体の文の行末に # の注記があれば数えない。

使い方:
    python3 tests/value-rules.py            # 確かめる（tests/run.sh が呼ぶ）
    python3 tests/value-rules.py --update   # 今の数を基準に書く（直して数が減ったとき）
    python3 tests/value-rules.py --list <パス>...  # そのファイルの当たった行を出す

終了コード: 0 = 基準どおり / 1 = 基準と違う・読めないファイルが在る
"""
import ast
import io
import json
import pathlib
import re
import subprocess
import sys
import tokenize

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "value-rules-baseline.json"
DIRS = ("attention", "convergence-loops", "gates", "graphloops", "tiers", "works-dispatch", "scripts", "tests")
# CJK の記号・句読点・ひらがな・カタカナ（拡張を含む）・漢字（拡張 A・互換漢字・拡張 B 以降）・CJK 互換の形・全角と半角の形
CJK = re.compile("[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
                 "\ufe30-\ufe4f\uff00-\uffef\U00020000-\U0003ffff]")
CMP_OPS = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)
RE_FUNCS = {"compile", "search", "match", "fullmatch", "findall", "sub", "split"}
RULES = ("rule3", "rule4")


def cjk(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(CJK.search(node.value))


def members(node):
    """node が定数なら [node]、タプル・リスト・集合ならその中の要素"""
    return list(node.elts) if isinstance(node, (ast.Tuple, ast.List, ast.Set)) else [node]


def hits(text):
    """(rule3 の行の一覧, rule4 の行の一覧)。構文木にできなければ SyntaxError のまま投げる"""
    tree = ast.parse(text)
    noted = {tok.start[0] for tok in tokenize.generate_tokens(io.StringIO(text).readline) if tok.type == tokenize.COMMENT}
    re_mods, re_names = {"re"}, {}   # re の別名（import re as X）と、from re import で取った名前 → 関数名
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            re_mods.update(a.asname or a.name for a in node.names if a.name == "re")
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            re_names.update({a.asname or a.name: a.name for a in node.names if a.name in RE_FUNCS})
    r3, r4 = {}, []   # r3 は定数のノード → 行（比べる式の連なり a == "x" == b で同じ定数を 2 度数えない）
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if not isinstance(op, CMP_OPS):
                    continue
                left = node.left if i == 0 else node.comparators[i - 1]
                # 左はその物だけ、右はタプル・リスト・集合なら中も（標準の「守らせ方」の書き方どおり）
                r3.update({id(c): c.lineno for c in [left, *members(node.comparators[i])] if cjk(c)})
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in ("startswith", "endswith"):
                r3.update({id(c): c.lineno for a in node.args for c in members(a) if cjk(c)})
            elif (isinstance(f, ast.Attribute) and f.attr in RE_FUNCS and isinstance(f.value, ast.Name) and f.value.id in re_mods) or \
                    (isinstance(f, ast.Name) and f.id in re_names):
                pat = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "pattern"), None)
                if pat is not None and cjk(pat):
                    r3[id(pat)] = pat.lineno
        elif isinstance(node, ast.ExceptHandler):
            body = node.body
            if len(body) == 1 and isinstance(body[0], (ast.Pass, ast.Continue)) and not ({node.lineno, body[0].lineno} & noted):
                r4.append(node.lineno)
    return sorted(r3.values()), sorted(r4)


def files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", *DIRS], capture_output=True, text=True, encoding="utf-8",
                         check=True).stdout
    return sorted(p for p in out.split("\0") if p.endswith(".py"))


def counts():
    """({パス: {rule: 数}}, 読めなかったファイルの一覧)。数が 0 のファイルと規則は載せない"""
    out, unread = {}, []
    for path in files():
        try:
            r3, r4 = hits((ROOT / path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as exc:
            # 読めないファイルを数から黙って外さない（決まり 4）。外すと、そのファイルの数が増えても誰も気づかない
            unread.append(f"{path}（{type(exc).__name__}: {exc}）")
            continue
        got = {k: n for k, n in zip(RULES, (len(r3), len(r4))) if n}
        if got:
            out[path] = got
    return out, unread


def main(argv):
    if argv[:1] == ["--list"]:
        for p in argv[1:]:
            r3, r4 = hits((ROOT / p).read_text(encoding="utf-8"))
            for n in r3:
                print(f"{p}:{n}: rule3 日本語の定数で比べている")
            for n in r4:
                print(f"{p}:{n}: rule4 訳の注記の無い pass・continue だけの except")
        return 0
    now, unread = counts()
    for u in unread:
        print(f"NG 構文木にできない・読めない: {u}")
    if argv[:1] == ["--update"]:
        if unread:
            return 1
        BASELINE.write_text(json.dumps(now, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"VALUE_RULES_UPDATED {len(now)} ファイル")
        return 0
    try:
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"NG 基準 {BASELINE.relative_to(ROOT)} を読めない: {exc}")
        return 1
    up, down = [], []
    for path in sorted(set(now) | set(base)):
        for rule in RULES:
            a, b = base.get(path, {}).get(rule, 0), now.get(path, {}).get(rule, 0)
            if b > a:
                up.append(f"{path}: {rule} {a} → {b}")
            elif b < a:
                down.append(f"{path}: {rule} {a} → {b}")
    for x in up:
        print(f"NG 増えた {x}（python3 tests/value-rules.py --list {x.split(':')[0]} で行を見て、"
              "docs/standards/machine-readable-values.md の決まり 3・4 に合わせて直す）")
    for x in down:
        print(f"NG 減った {x}（直したなら python3 tests/value-rules.py --update で基準を書き直して一緒に commit する）")
    if up or down or unread:
        return 1
    total = {r: sum(v.get(r, 0) for v in now.values()) for r in RULES}
    print(f"VALUE_RULES_OK {len(now)} ファイル・rule3 {total['rule3']} 件・rule4 {total['rule4']} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
