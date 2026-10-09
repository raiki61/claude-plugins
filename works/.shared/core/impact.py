"""変更の周りの地図（impact map）。変える所（起点）から、どの source とどのテストに届くかを機械だけで出す。層 L3（共有）。

〈立場〉写しの changemap（attention の変更の地図の部品。COPIED_FROM.changemap）と同じ: 機械は事実だけを出し、判断しない。
行は 1 文字も変えずに持つ（当たりの行・import の行・変更の枠）。上限は数で言い、切った物と読めなかった物は
「見ていないもの」（not_seen）に数と理由で書く。字の一致は当たり（候補）でしかないので candidate の印を付ける。
AI に探させず、1 回作って使い回す（鍵 = rev・起点・作業ツリーの差分の sha。置き場に同じ鍵の file が在れば読むだけ）。

口（標準ライブラリだけ）:
- map(repo, rev="HEAD", seeds=(), diff=False, cache_dir=None) -> dict
  seeds は追跡中の file のパス（リポジトリの根から）・フォルダ（下の file 全部）・一意な basename・名前（関数名など。
  パスの形でない物）。diff=True なら rev と作業ツリーの差（未追跡を含む）の file も起点に足す。
  cache_dir を渡すと <cache_dir>/map-<鍵>.json に書き、同じ鍵なら読むだけ（stats.cache = "hit"）。file ごとの
  読み取りの結果は中身の sha で <cache_dir>/scan.json に持ち、中身の変わった file だけ読み直す（stats.scanned）。
- select_tests(m, fast=(), scope=None, all_modules=None, direct_only=False, named=()) -> dict: 回すテストのモジュール
  （速い段 ∪ 選んだ物）。all_tests_required なら全部（all_modules を渡せばその一覧、無ければ modules は None）。
  direct_only なら直に関わる試験（direct: 起点か深さ 1）と名指しの試験だけを選び、先の試験は left に残す。
  その時の全部は分からない物が直に関わる所に在る時だけで、深さ 2 以上の分からない物は far に理由の形で残す
- direct(m, path) -> bool: 起点そのものか、起点から辺 1 本（深さ 1）で届いた file か
- seeds_from_units(repo, units) -> list: 判定の単位の文（key・reason・class_query・prescriptions など全部の字）に
  現れる追跡中の file（パスそのものか、一意な basename）
- py_imports(text) -> list | None: Python の file の import の一覧（地図の import の辺と同じ読み取り。libdocs が使う）
- tree_files(repo) -> list | None: 作業ツリーの file の一覧（追跡中と無視されていない未追跡。git が使えなければ None。libdocs が使う）

地図の JSON（schema works-impact/1）の欄:
- key・rev（commit の sha）・rev_name・seeds {given, files, names, from_diff, missing}
- reach {path: {depth, lang, test, candidate, parent {from, kind, key, line}}}: 起点から届いた file（起点は含まない）
- edges [{path, dep, kind, key, candidate, count, hits [[行番号, 行]], resolution?}]: path が dep に依る
  （kind: import・path（basename の言及）・stem（拡張子を除いた名が引用符か YAML の値）・module（点の付いた模块名）・
  symbol（起点の関数・クラスの名、起点の名前））
- reverse_imports・tests・mentions・refs: reach の分類（パスの一覧）。mentions はコードの file、refs は
  YAML・JSON・MD などの設定と文書
- unanalysable [{path, reason, line?, text?, in_neighbourhood}]・all_tests_required・all_tests_reasons
- counts・not_seen・limits・heuristics・stats（stats だけはその回の値）

使い手: blk-fix（受け付け・TDD の輪・止める単位の結び。map と select_tests で回す試験を選ぶ）、libdocs・design・report、境の節。
"""
import argparse
import ast
import hashlib
import heapq
import json
import os
import pathlib
import re
import sys

import changemap

SCHEMA = "works-impact/1"
ACCEPT_TRACE_OP = "fix_tests_selected"   # 修正の受け付けが選んだ試験を走らせた盤面の trace の行（書くのは blk-fix、読むのは最後の関所）
ACCEPT_GATES_SKIPPED_OP = "fix_gates_skipped"   # 修正の受け付けの事後の関門の束が赤緑を確かめずに受けた回の盤面の trace の行（書くのは blk-fix、読むのは報告）

# 数で言う上限（not_seen と limits に同じ数を書く）
MAX_BYTES = 2_000_000    # これより大きい file は字を切り分けない（too-large）
HITS_KEEP = 20           # 1 file・1 鍵あたり JSON に残す当たりの行（数は全部数える）
KEY_MIN = 4              # basename・拡張子を除いた名を鍵にする最短の字数
SYMBOL_MIN = 8           # 起点の関数・クラスの名を鍵にする最短（_ を含む名は字数を問わない。含まない名は大文字も要る）
NAME_HOPS = 3            # sys.path・動的 import の引数の名前を代入に辿る深さ
MENTION_HOPS = 2         # 起点から辿る言及の辺の数の上限（import の辺は数えない）。超えた先は not_seen.beyond_mention_hops

PY_EXT = frozenset({"py", "pyi"})
# パスで呼ばれる・読まれる物（中の言及を読めば依り先が分かる）。言及は先へ伸ばす
PATHREF_EXT = frozenset({"sh", "bash", "zsh", "bats", "yml", "yaml", "json", "jsonc", "toml", "ini", "cfg", "conf",
                         "mk", "env", "tmpl"})
PATHREF_NAMES = frozenset({"makefile", "gnumakefile", "dockerfile", "justfile"})
# 文書・データ。言及は拾うが先へは伸ばさない（実行されない）
DOC_EXT = frozenset({"md", "markdown", "txt", "rst", "adoc", "csv", "lock", "html", "htm", "xml", "svg", "patch",
                     "diff", "log", "example", "sample", "tsv"})
# import を読まない言語のコード（依る側を字の一致でしか辿れない。近くに在れば全部を回す）。ほかの知らない拡張子は文書・データ扱い
OTHER_CODE_EXT = frozenset({"js", "jsx", "mjs", "cjs", "ts", "tsx", "go", "rb", "rs", "java", "kt", "kts", "scala", "c",
                            "h", "cc", "cpp", "cxx", "hpp", "cs", "swift", "php", "pl", "pm", "lua", "r", "dart",
                            "groovy", "gradle", "ex", "exs", "hs", "elm", "clj", "vue", "svelte", "ps1", "m", "mm"})
# refs（設定・文書）に数える拡張子。ほかの届いた file は mentions（コード）
REF_EXT = PATHREF_EXT - {"sh", "bash", "zsh", "bats", "mk"} | DOC_EXT
TEST_DIRS = frozenset({"tests", "test", "__tests__", "spec"})
TEST_NAME = re.compile(r"(^test_.*\.py$|.*_test\.(py|go)$|.*\.bats$|.*\.(test|spec)\.[jt]sx?$|.*-(case|suite)\.(py|sh)$"
                       r"|^conftest\.py$)")
# 拡張子を除いた名で呼ばれる物（YAML の script の値・include の値・名で起こすスクリプト）。JSON などの名は節の id と重なるので見ない
STEM_EXT = frozenset({"py", "sh", "bash", "zsh", "bats", "yml", "yaml"})
# project の根の印（名の言及を同じ project の中に限る。無いリポジトリは全体が 1 つの project）
MANIFESTS = frozenset({"pyproject.toml", "setup.py", "setup.cfg", "package.json", "go.mod", "Cargo.toml", "pom.xml",
                       "build.gradle", "Gemfile", "composer.json", "archon-plugin.json"})
STOP_KEYS = frozenset({"__init__.py", "__main__.py", "__init__", "__main__", "action.yml", "action.yaml"})
DYNAMIC = {"import_module": 0, "__import__": 0, "spec_from_file_location": 1, "run_path": 0, "run_module": 0,
           "load_source": 1, "SourceFileLoader": 1, "exec": 0}
UNANALYSABLE_TRIGGERS = frozenset({"unknown-language", "py-parse-error", "dynamic-import", "too-large", "symlink"})
HEURISTICS = [
    "file の一覧は git ls-files（追跡中）と ls-files -o --exclude-standard（無視されていない未追跡）。中身は作業ツリーの物",
    "Python の模块名は、パスの後ろから数えた点の名。根は __init__.py を持たないフォルダ（sys.path の入口とみなす）。"
    "sys.path.insert・append の引数に在る字（代入を 3 段まで辿る）で終わるフォルダを先に、次に自分のフォルダを見る。"
    "それでも複数なら全部に辺を張り、resolution を ambiguous・candidate にする",
    "言及は語の一致（basename・引用符か YAML の値の、拡張子を除いた名・点の付いた模块名・起点の関数とクラスの名）。"
    "同じ basename が複数あれば、当たりの行のパスの形で絞り、残りは言及した file に一番近い（共通のフォルダが深い）物",
    "Python・シェル・YAML・JSON などの設定からは先へ伸ばす。文書（md・txt など）・テストのモジュール・テストのフォルダの下の"
    "Python でない file（fixture・golden）で止める"
    "（テストはほかのテストの import だけで伸ばす）。言及の辺は起点から MENTION_HOPS 本まで（import の辺は数えない）。"
    "超えた先は not_seen.beyond_mention_hops に数え、そこのテストの名を tests_beyond_mention_hops に並べる",
    "起点の関数・クラスの名は、_ を含む名か、SYMBOL_MIN 字以上で大文字を含む名（DiskBoard など）だけを鍵にする。"
    "テストのモジュールの名は鍵にしない。起点の関数・クラスの名の言及（symbol）と拡張子を除いた名の言及（stem）は、起点と同じ project（manifest を持つ"
    "一番近い祖先のフォルダ。無ければリポジトリ全体）の中だけ。symbol の当たりは葉（先へ伸ばさない。名前の起点は伸ばす）。"
    "点の付いた模块名の言及（module）は Python でない file だけ（python -m など。Python の file は import の読み取りが正）。"
    "stem は py（import で読まれていない物＝スクリプト）・シェル・YAML の file だけ。同じ名の file が複数あり、言及した file と"
    "共有するフォルダが 1 段も無ければ、どれとも決めない（not_seen.ambiguous_mentions に数える）",
    "テストのモジュールは名前の型（test_*.py・*_test.py・*.bats・*.test.js・*-case.py など）。tests/ の下の他は支え",
    "動的 import（import_module・__import__・spec_from_file_location・runpy・exec など）は、引数の字が追跡中の"
    "file 名・フォルダ名に当たれば言及で辿れるとみなし、当たらなければ読めない物に数える",
    "起点とその届いた先（近く）に読めない物（分からない言語・Python の構文の誤り・字の当たらない動的 import・"
    "大きすぎる file・シンボリックリンク）が在れば all_tests_required（分からないなら全部を回す）",
]


# ---------------------------------------------------------------- 小さな道具
def _sha(data: bytes) -> str:
    """git の blob と同じ形の sha1（filter の無い file なら git hash-object と同じ）"""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _ext(path):
    return changemap._ext(path)


def _base(path):
    return path.rsplit("/", 1)[-1]


def _dir(path):
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _stem(path):
    b = _base(path)
    return b.rsplit(".", 1)[0] if "." in b.lstrip(".") else b


def _git(repo, *args):
    return changemap.git("-c", "core.quotePath=false", *args, cwd=str(repo))


def _code_sha():
    h = hashlib.sha256()
    for p in (pathlib.Path(__file__), pathlib.Path(changemap.__file__)):
        h.update(p.read_bytes())
    return h.hexdigest()


def is_test(path):
    """"module"（回すテスト）・"support"（テストのフォルダの下の他の file）・None"""
    if TEST_NAME.match(_base(path)):
        return "module"
    if any(part in TEST_DIRS for part in path.split("/")[:-1]):
        return "support"
    return None


def _lang(path, rec):
    """file の種類: python・pathref・doc・binary・unknown（分からない言語）"""
    if rec.get("bin"):
        return "binary"
    ext = _ext(path)
    base = _base(path).lower()
    sheb = rec.get("shebang") or ""
    if ext in PY_EXT or (not ext and "python" in sheb):
        return "python"
    if ext in PATHREF_EXT or base in PATHREF_NAMES or (not ext and sheb):
        return "pathref"
    if ext in OTHER_CODE_EXT:
        return "unknown"
    return "doc"


# ---------------------------------------------------------------- file ごとの読み取り（中身だけに依る。sha で使い回す）
WORD = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*")


def _words(text):
    out = set()
    for w in WORD.findall(text):
        w = w.rstrip(".-")
        if len(w) < 3:
            continue
        out.add(w)
        if "." in w:
            parts = [p for p in w.split(".") if p]
            out.update(p for p in parts if len(p) >= 3)
            for i in range(2, len(parts)):
                out.add(".".join(parts[:i]))
    return out


def _consts(node, assigns, depth=0):
    """式の中の文字列の定数（左から）。名前は代入を NAME_HOPS 段まで辿る"""
    out = []
    if node is None:
        return out
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        if depth < NAME_HOPS:
            for v in assigns.get(node.id, ())[:3]:
                out += _consts(v, assigns, depth + 1)
        return out
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    if isinstance(node, ast.BinOp):
        return _consts(node.left, assigns, depth) + _consts(node.right, assigns, depth)
    if isinstance(node, ast.Call):
        out = _consts(node.func.value, assigns, depth) if isinstance(node.func, ast.Attribute) else []
        for a in node.args:
            out += _consts(a, assigns, depth)
        for k in node.keywords:
            out += _consts(k.value, assigns, depth)
        return out
    if isinstance(node, (ast.Attribute, ast.Subscript, ast.Starred)):
        return _consts(node.value, assigns, depth)
    if isinstance(node, (ast.List, ast.Tuple)):
        for e in node.elts:
            out += _consts(e, assigns, depth)
    return out


def _py_facts(text):
    """import（名・段・行・from の名・行の字）・sys.path に足す字・動的 import・一番上の def と class の名"""
    lines = text.split("\n")
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as e:
        return {"error": f"{type(e).__name__}: {e}", "imports": [], "syspath": [], "dyn": [], "defs": []}
    assigns = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    assigns.setdefault(t.id, []).append(n.value)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value is not None:
            assigns.setdefault(n.target.id, []).append(n.value)

    def line_of(n):
        i = getattr(n, "lineno", 0)
        return i, (lines[i - 1] if 0 < i <= len(lines) else "")

    imports, syspath, dyn = [], [], []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                imports.append([a.name, 0, *line_of(n), []])
        elif isinstance(n, ast.ImportFrom):
            imports.append([n.module or "", n.level, *line_of(n), [a.name for a in n.names]])
        elif isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            if (name in ("insert", "append") and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute)
                    and f.value.attr == "path" and isinstance(f.value.value, ast.Name) and f.value.value.id == "sys"
                    and n.args):
                syspath.append(_consts(n.args[-1], assigns))
            elif name in DYNAMIC:
                idx = DYNAMIC[name]
                arg = n.args[idx] if len(n.args) > idx else (n.keywords[0].value if n.keywords else None)
                if (name in ("import_module", "__import__") and isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str) and not arg.value.startswith(".")):
                    imports.append([arg.value, 0, *line_of(n), []])
                elif not (name == "exec" and isinstance(arg, ast.Constant)):
                    dyn.append([*line_of(n), _consts(arg, assigns)])
    defs = sorted({n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))})
    imports.sort(key=lambda x: (x[2], x[0]))
    dyn.sort(key=lambda x: x[0])
    return {"error": None, "imports": imports, "syspath": syspath, "dyn": dyn, "defs": defs}


def py_imports(text):
    """Python の file の import の一覧 [[名, 段, 行番号, 行の字, from の名の一覧]]（_py_facts の imports と同じ形）。
    構文の誤りで読めなければ None（ほかの模块が import の読み取りを 2 か所に持たないための公開の口）"""
    facts = _py_facts(text)
    return None if facts["error"] else facts["imports"]


def _scan(data: bytes, want_py: bool):
    """1 つの中身の読み取り（パスに依らない）"""
    rec = {"bin": b"\0" in data[:8192], "large": len(data) > MAX_BYTES, "hits": {}}
    if rec["bin"] or rec["large"]:
        rec["words"] = []
        return rec
    text = data.decode("utf-8", errors="replace")
    first = text.split("\n", 1)[0]
    rec["shebang"] = first if first.startswith("#!") else None
    rec["words"] = sorted(_words(text))
    if want_py:
        rec["py"] = _py_facts(text)
    return rec


# ---------------------------------------------------------------- 言及の当たり
def _hit_re(kind, key):
    k = re.escape(key)
    if kind == "path":
        return re.compile(r"(?<![A-Za-z0-9_.\-/])((?:[A-Za-z0-9_.\-]+/)*)" + k + r"(?![A-Za-z0-9_\-])")
    if kind == "stem":
        return re.compile(r"[\"'`]" + k + r"[\"'`]|^\s*(?:-\s+|[\w.\-]+:\s+)" + k + r"\s*$")
    if kind == "module":
        return re.compile(r"(?<![A-Za-z0-9_.])" + k + r"(?![A-Za-z0-9_])")
    return re.compile(r"(?<![A-Za-z0-9_])" + k + r"(?![A-Za-z0-9_])")


def _hits(text, kind, key):
    """[数, 残す行 [[行番号, 行]], パスの形の字（path の時だけ）]。行は 1 文字も変えない"""
    rx = _hit_re(kind, key)
    count, kept, tokens = 0, [], set()
    for i, ln in enumerate(text.split("\n"), 1):
        found = list(rx.finditer(ln))
        if not found:
            continue
        count += 1
        if len(kept) < HITS_KEEP:
            kept.append([i, ln])
        if kind == "path":
            tokens.update((m.group(1) or "") + key for m in found)
    return [count, kept, sorted(tokens)]


def _common(a, b):
    """2 つのパスが共有するフォルダの段の数"""
    n = 0
    for x, y in zip(a.split("/")[:-1], b.split("/")[:-1]):
        if x != y:
            break
        n += 1
    return n


def _owners_for(f, owners, tokens):
    """同じ名の file が複数ある時、f の言及がどれを指すか。パスの形で絞れればそれ、無ければ f に一番近い物"""
    if len(owners) <= 1:
        return set(owners)
    narrowed = set()
    for t in tokens:
        t = re.sub(r"^(?:\.{1,2}/)+", "", t)
        m = [o for o in owners if o == t or o.endswith("/" + t)]
        if m and len(m) < len(owners):
            narrowed.update(m)
    if narrowed:
        return narrowed
    best = max(_common(f, o) for o in owners)
    if best == 0:
        return set()   # 共有するフォルダが無い同名の複数: どれを指すか決められない（not_seen.ambiguous_mentions に数える）
    return {o for o in owners if _common(f, o) == best}


# ---------------------------------------------------------------- 本体
class _Index:
    """1 回の map の中で使う表（file・中身の読み取り・模块名・語の索引）"""

    def __init__(self, repo, cache_dir, scan=True):
        self.repo = pathlib.Path(repo)
        self.scan = scan
        self.cache_path = pathlib.Path(cache_dir) / "scan.json" if cache_dir else None
        self.cache = {}
        if self.cache_path and self.cache_path.is_file():
            try:
                self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.cache = {}
        self.dirty = False
        self.files, self.special, self.untracked, self.data = {}, {}, set(), {}
        self.scanned = self.reused = 0
        self._list()

    def _list(self):
        out = _git(self.repo, "ls-files", "-s", "-z")
        if out is None:
            raise RuntimeError(f"git ls-files が失敗した: {self.repo}")
        paths = []
        for row in filter(None, out.split("\0")):
            meta, _, path = row.partition("\t")
            mode = meta.split()[0]
            if mode == "160000":
                self.special[path] = "submodule"
            elif mode == "120000":
                self.special[path] = "symlink"
            else:
                paths.append(path)
        others = _git(self.repo, "ls-files", "-o", "--exclude-standard", "-z") or ""
        self.untracked = set(filter(None, others.split("\0")))
        for path in sorted(set(paths) | self.untracked):
            full = self.repo / path
            if not self.scan:
                self.files[path] = None   # 一覧だけ（seeds_from_units）。中身は読まない
                continue
            if full.is_symlink():
                self.special[path] = "symlink"
                continue
            try:
                data = full.read_bytes()
            except OSError:
                self.special.setdefault(path, "missing")
                continue
            sha = _sha(data)
            rec = self.cache.get(sha)
            want_py = _ext(path) in PY_EXT or data.startswith(b"#!") and b"python" in data.split(b"\n", 1)[0]
            if rec is None or (want_py and "py" not in rec and not rec.get("bin") and not rec.get("large")):
                rec = _scan(data, want_py)
                self.cache[sha] = rec
                self.dirty = True
                self.scanned += 1
            else:
                self.reused += 1
            self.files[path] = sha
            if not rec.get("bin") and not rec.get("large"):
                self.data[path] = data   # 当たりの行はハッシュを取った同じ中身から取る（読み直すと鍵と中身がずれうる）
        self.lang = {p: _lang(p, self.cache[s]) for p, s in self.files.items()} if self.scan else {}
        self.by_base, self.by_stem = {}, {}
        for p in self.files:
            self.by_base.setdefault(_base(p), []).append(p)
            self.by_stem.setdefault(_stem(p), []).append(p)
        self.dirs = {d for p in self.files for d in _dirs(p)}
        self.projects = sorted({_dir(p) for p in self.files if _base(p) in MANIFESTS}
                               | {_dir(_dir(p)) for p in self.files if p.endswith(".claude-plugin/plugin.json")},
                               key=len, reverse=True)

    def project(self, path):
        """path を持つ project の根（manifest を持つ一番近い祖先のフォルダ。無ければ ""）"""
        for d in self.projects:
            if d and path.startswith(d + "/"):
                return d
        return ""

    def rec(self, path):
        return self.cache[self.files[path]]

    def text(self, path):
        return self.data[path].decode("utf-8", errors="replace")

    def word_index(self):
        idx = {}
        for p, s in self.files.items():
            for w in self.cache[s]["words"]:
                idx.setdefault(w, []).append(p)
        return idx

    def hits(self, path, kind, key):
        rec = self.rec(path)
        slot = f"{kind}\t{key}"
        if slot not in rec["hits"]:
            rec["hits"][slot] = _hits(self.text(path), kind, key)
            self.dirty = True
        return rec["hits"][slot]

    def save(self):
        if not (self.cache_path and self.dirty):
            return
        # 今の木に無い中身の読み取りも残す（前の版・別の枝の地図が使う。中身の sha が鍵なので古くならない）
        _write_json(self.cache_path, self.cache)


def _dirs(path):
    parts = path.split("/")[:-1]
    return {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}


def _write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _names_of(path, pkgdirs):
    """(点の模块名, 根のフォルダ) の列。根は __init__.py を持たないフォルダだけ"""
    parts = path.split("/")
    stem = parts[-1].rsplit(".", 1)[0]
    comps = parts[:-1] + ([] if stem == "__init__" else [stem])
    out = []
    for i in range(len(comps) - 1, -1, -1):
        name = comps[i:]
        if not all(c.isidentifier() for c in name):
            break
        root = "/".join(parts[:i])
        out.append((".".join(name), root))
    return out


class _Modules:
    def __init__(self, ix, ghosts):
        self.ix = ix
        pys = [p for p, lang in ix.lang.items() if lang == "python"] + [g for g in ghosts if _ext(g) in PY_EXT]
        self.pys = set(pys)
        self.pkgdirs = {_dir(p) for p in pys if _base(p) == "__init__.py"}
        self.table = {}
        for p in sorted(pys):
            for name, root in _names_of(p, self.pkgdirs):
                self.table.setdefault(name, []).append((p, root))
        self.external = set()

    def _pick(self, importer, name, declared):
        """先の候補を 1 つの組に絞る: sys.path に足した字 → 自分のフォルダ → package でない根。組の中は importer に
        一番近い（共有するフォルダが深い）物。それでも複数なら全部（ambiguous）"""
        cands = self.table.get(name, [])
        if not cands:
            return [], None
        own = _dir(importer)
        for how, group in (
                ("sys.path", [c for c in cands if any(c[1] == d or c[1].endswith("/" + d) for d in declared)]),
                ("same-dir", [c for c in cands if c[1] == own and c[0] != importer]),
                ("unique", [c for c in cands if c[1] not in self.pkgdirs])):
            if group:
                best = max(_common(importer, c[0]) for c in group)
                group = [c for c in group if _common(importer, c[0]) == best]
                return group, how if len(group) == 1 else "ambiguous"
        return [], None

    def _file(self, parts):
        base = "/".join(parts)
        for cand in (base + ".py", base + "/__init__.py", base + ".pyi"):
            if cand in self.pys:
                return cand
        return None

    def resolve(self, importer, imp, declared):
        """1 つの import の行 → [(先の file, resolution)]"""
        name, level, _line, _text, froms = imp
        out = []
        if level:
            base = importer.split("/")[:-1]
            if level > 1:
                base = base[:-(level - 1)] if level - 1 <= len(base) else None
            if base is None:
                return out
            mod = base + (name.split(".") if name else [])
            f = self._file(mod) if mod else None
            if f:
                out.append((f, "relative"))
            for fr in froms:
                g = self._file(mod + [fr]) if fr != "*" else None
                if g:
                    out.append((g, "relative"))
            return out
        tries = [name] + [f"{name}.{fr}" for fr in froms if fr != "*"]
        for t in tries:
            picked, how = self._pick(importer, t, declared)
            for p, root in picked:
                out.append((p, how))
                # a.b.c を読むと a と a.b の __init__ も走る
                comps = t.split(".")
                for i in range(1, len(comps)):
                    init = "/".join(filter(None, [root, *comps[:i], "__init__.py"]))
                    if init in self.pys:
                        out.append((init, how))
        if not out:
            top = name.split(".")[0]
            if top and top not in sys.stdlib_module_names and top != "__future__":
                self.external.add(top)
        return out


def _declared_roots(facts):
    out = []
    for consts in facts.get("syspath", []):
        pieces = [p for c in consts for p in c.split("/") if p and p not in (".", "..")]
        if pieces:
            out.append("/".join(pieces))
    return out


def _normalize_seeds(ix, seeds):
    files, names, missing = set(), set(), set()
    for s in seeds:
        s = str(s).strip()
        s = re.sub(r"^\./", "", s).rstrip("/")
        if not s:
            continue
        if s in ix.files or s in ix.special:
            files.add(s)
            if ix.special.get(s) == "missing":
                missing.add(s)   # 作業ツリーで消した file: import する側はまだ名を書いているので、模块の表に残す
        elif s in ix.dirs:
            files.update(p for p in ix.files if p.startswith(s + "/"))
        elif "/" not in s and len(ix.by_base.get(s, [])) == 1:
            files.add(ix.by_base[s][0])
        elif "/" in s or re.search(r"\.[A-Za-z0-9]+$", s):
            files.add(s)
            missing.add(s)
        else:
            names.add(s)
    return files, names, missing


def _diff_paths(repo, rev, ix):
    pairs = changemap.changed_pairs(cwd=str(repo), rev=rev)
    if pairs is None:
        raise RuntimeError(f"git diff {rev} が失敗した: {repo}")
    # 改名は新旧の両方（旧の名を import している側が残る）
    return sorted({n for _p, group in pairs for n in group} | ix.untracked)


def _keys(ix, mods, path, is_seed, imported=frozenset()):
    """file が依られる時の鍵 [(kind, key)]。imported は import で読まれている file（その名の言及は import で足りる）"""
    out = []
    base = _base(path)
    if base in ("action.yml", "action.yaml") and "/" in path:
        out.append(("path", _base(_dir(path))))
    if len(base) >= KEY_MIN and base not in STOP_KEYS:
        out.append(("path", base))
    stem = _stem(path)
    if (len(stem) >= KEY_MIN and stem != base and stem not in STOP_KEYS
            and (_ext(path) in STEM_EXT or ix.lang.get(path) == "python")
            and path not in imported):
        out.append(("stem", stem))
    if path in mods.pys:
        for name, root in _names_of(path, mods.pkgdirs):
            if "." in name and root not in mods.pkgdirs:
                out.append(("module", name))
    if is_seed and path in ix.files and ix.lang.get(path) == "python":
        facts = ix.rec(path).get("py") or {}
        for d in facts.get("defs", []):
            if not d.startswith("_") and ("_" in d or (len(d) >= SYMBOL_MIN and d[1:] != d[1:].lower())):
                out.append(("symbol", d))
    return out


def _owner_pool(ix, mods, kind, key, path):
    """同じ鍵を持つ file の全部（言及がどれを指すかを _owners_for で決める）"""
    if kind == "path":
        return ix.by_base.get(key) or [path]
    if kind == "stem":
        return ix.by_stem.get(key) or [path]
    if kind == "module":
        return sorted({p for p, _root in mods.table.get(key, [])}) or [path]
    return [path]


def _build(repo, rev, rev_sha, changed, seeds, diff, ix):
    from_diff = list(changed) if diff else []
    files, names, missing = _normalize_seeds(ix, list(seeds) + from_diff)
    mods = _Modules(ix, missing)

    # 逆向きの import の表: 先 → [(元, resolution, 行, 字)]
    importers = {}
    for p in sorted(mods.pys & set(ix.files)):
        facts = ix.rec(p).get("py") or {}
        declared = _declared_roots(facts)
        for imp in facts.get("imports", []):
            for tgt, how in mods.resolve(p, imp, declared):
                if tgt != p:
                    importers.setdefault(tgt, []).append((p, how, imp[2], imp[3], imp[0] or "." * imp[1]))

    words = ix.word_index()
    edges = {}   # (path, dep, kind, key) → edge

    def add_edge(path, dep, kind, key, hits, candidate, resolution=None):
        """辺を 1 本にまとめる（2 回の辿りで同じ辺に来ても数を重ねない）。import は行ごとに 1 つ数える"""
        k = (path, dep, kind, key)
        e = edges.get(k)
        if e is None:
            e = edges[k] = {"path": path, "dep": dep, "kind": kind, "key": key, "candidate": candidate,
                            "count": hits[0], "hits": list(hits[1])}
            if resolution:
                e["resolution"] = resolution
            return
        if kind == "import":
            for h in hits[1]:
                if h not in e["hits"]:
                    e["hits"].append(h)
                    e["count"] += 1
            e["hits"].sort()
            e["candidate"] = e["candidate"] and candidate

    def import_deps(x):
        out = []
        for p, how, line, text, name in importers.get(x, []):
            cand = how == "ambiguous"
            add_edge(p, x, "import", name, [1, [[line, text]]], cand, how)
            out.append((p, "import", name, line, cand))
        return out

    def mention_deps(x, keys):
        out = []
        for kind, key in keys:
            for f in words.get(key, ()):
                if f == x or ix.lang.get(f) == "binary" or (kind == "module" and ix.lang.get(f) == "python"):
                    continue   # Python の file の模块名は import の読み取りが正（字の一致を重ねない）
                h = ix.hits(f, kind, key)
                if not h[0]:
                    continue
                if kind in ("symbol", "stem") and x in ix.files and ix.project(f) != ix.project(x):
                    ambiguous.add((f, kind, key))   # 名の言及は同じ project の中だけ（同じリポジトリの別の project の同名を拾わない）
                    continue
                if x in ix.files or x in missing:
                    owners = _owners_for(f, _owner_pool(ix, mods, kind, key, x), h[2])
                    if not owners:
                        ambiguous.add((f, kind, key))
                    if x not in owners:
                        continue
                add_edge(f, x, kind, key, h, True)
                out.append((f, kind, key, h[1][0][0] if h[1] else None, True))
        return out

    reach = {}
    seed_set = set(files)
    ambiguous = set()

    # 辿り: 言及の段の数（mention hops）が少ない順、同じなら深さの浅い順に 1 度だけ決める（0-1 の最短路）。
    # import は段を足さず、言及は 1 段足す。MENTION_HOPS を超える先は reach に入れず、beyond に数える
    beyond = {}
    heap = [(0, 0, 0, x) for x in sorted(seed_set)] + [(0, 0, 1, f"name:{n}") for n in sorted(names)]
    heapq.heapify(heap)
    settled = set()
    while heap:
        hops, depth, _o, x = heapq.heappop(heap)
        if x in settled:
            continue
        settled.add(x)
        is_name = x.startswith("name:")
        node = x[5:] if is_name else x
        deps = import_deps(node) if node in mods.pys else []
        if is_name:
            keys = [("symbol", node)]
        elif is_test(node) == "module":
            keys = []   # テストに依る物は無い（テストの名の言及は依りではない）。テストどうしは import だけ
        else:
            keys = _keys(ix, mods, node, node in seed_set, importers)
        deps += mention_deps(node, keys) if keys else []
        for f, kind, key, line, cand in sorted(deps, key=lambda d: (d[0], d[1] != "import", d[1], d[2])):
            if f in seed_set:
                continue
            h2 = hops + (0 if kind == "import" else 1)
            if h2 > MENTION_HOPS:
                if f not in reach:
                    beyond.setdefault(f, {"from": node, "kind": kind, "key": key})
                continue
            parent_cand = reach.get(node, {}).get("candidate", False)
            info = {"depth": depth + 1, "mention_hops": h2, "lang": ix.lang.get(f, "unknown"), "test": is_test(f),
                    "candidate": bool(cand or parent_cand or h2),
                    "parent": {"from": node, "kind": kind, "key": key, "line": line}}
            old = reach.get(f)
            if old is None or (old["mention_hops"], old["depth"]) > (h2, depth + 1):
                reach[f] = info
                beyond.pop(f, None)
                # 起点の file の関数名の言及は葉（使う側は import で辿れる。名の一致だけで先へ伸ばさない）
                # テストのフォルダの下の Python でない file（fixture・golden などのデータ）も葉
                if (ix.lang.get(f) in ("python", "pathref", "unknown") and (kind != "symbol" or is_name)
                        and not (is_test(f) == "support" and ix.lang.get(f) != "python")):
                    heapq.heappush(heap, (h2, depth + 1, 1, f))

    # 分類
    imp_any = {e["path"] for e in edges.values() if e["kind"] == "import"}
    reverse_imports = sorted(p for p in reach if p in imp_any)
    tests = sorted(p for p in reach.keys() | seed_set if is_test(p) == "module")
    rest = [p for p in reach if p not in imp_any]
    refs = sorted(p for p in rest if _ext(p) in REF_EXT or ix.lang.get(p) == "doc")
    mentions = sorted(p for p in rest if p not in refs)

    # 読めない物
    near = seed_set | set(reach)
    module_words = set()
    for p in near:
        if p in mods.pys:
            for name, _root in _names_of(p, mods.pkgdirs):
                module_words.add(name)
                module_words.add(name.rsplit(".", 1)[-1])
    unanalysable = []
    hint_words = set(ix.by_base) | {d.rsplit("/", 1)[-1] for d in ix.dirs} | {
        s for s in ix.by_stem if len(s) >= KEY_MIN}
    for p in sorted(ix.files):
        rec = ix.rec(p)
        lang = ix.lang[p]
        if rec.get("large"):
            unanalysable.append({"path": p, "reason": "too-large",
                                 "in_neighbourhood": p in near or _ext(p) not in DOC_EXT})
            continue
        if lang == "binary":
            unanalysable.append({"path": p, "reason": "binary", "in_neighbourhood": False})
            continue
        if lang == "unknown":
            unanalysable.append({"path": p, "reason": "unknown-language", "in_neighbourhood": p in near})
            continue
        if lang != "python":
            continue
        facts = rec.get("py") or {}
        if facts.get("error"):
            may = p in near or bool(module_words & set(rec["words"]))
            unanalysable.append({"path": p, "reason": "py-parse-error", "text": facts["error"],
                                 "in_neighbourhood": may})
            continue
        for line, text, consts in facts.get("dyn", []):
            pieces = {q for c in consts for q in c.split("/") if q}
            if pieces & hint_words:
                continue
            unanalysable.append({"path": p, "reason": "dynamic-import", "line": line, "text": text,
                                 "in_neighbourhood": p in near})
    for p, why in sorted(ix.special.items()):
        unanalysable.append({"path": p, "reason": why, "in_neighbourhood": p in near and why != "missing"})
    for p in sorted(missing):
        if p not in ix.special:
            unanalysable.append({"path": p, "reason": "missing", "in_neighbourhood": False})
    reasons = sorted({f"{u['reason']}: {u['path']}" + (f":{u['line']}" if u.get("line") else "")
                      for u in unanalysable if u["in_neighbourhood"] and u["reason"] in UNANALYSABLE_TRIGGERS})

    by_reason = {}
    for u in unanalysable:
        by_reason[u["reason"]] = by_reason.get(u["reason"], 0) + 1
    edge_list = sorted(edges.values(), key=lambda e: (e["path"], e["dep"], e["kind"], e["key"]))
    cut = sum(max(e["count"] - len(e["hits"]), 0) for e in edge_list if e["kind"] != "import")
    return {
        "schema": SCHEMA, "rev": rev_sha, "rev_name": rev,
        "seeds": {"given": sorted(str(s) for s in seeds), "files": sorted(files), "names": sorted(names),
                  "from_diff": from_diff, "missing": sorted(missing)},
        "counts": {"files": len(ix.files), "python": len(mods.pys & set(ix.files)), "reached": len(reach),
                   "reverse_imports": len(reverse_imports), "tests": len(tests), "mentions": len(mentions),
                   "refs": len(refs), "unanalysable": len(unanalysable),
                   "unanalysable_near": sum(1 for u in unanalysable if u["in_neighbourhood"])},
        "reach": {p: reach[p] for p in sorted(reach)},
        "edges": edge_list,
        "reverse_imports": reverse_imports, "tests": tests, "mentions": mentions, "refs": refs,
        "unanalysable": unanalysable,
        "all_tests_required": bool(reasons), "all_tests_reasons": reasons,
        "not_seen": {"unanalysable": dict(sorted(by_reason.items())),
                     "external_imports": sorted(mods.external),
                     "hit_lines_not_kept": cut,
                     "beyond_mention_hops": len(beyond),
                     "tests_beyond_mention_hops": sorted(p for p in beyond if is_test(p) == "module"),
                     "ambiguous_mentions": len(ambiguous),
                     "ignored_files": "git の無視（.gitignore）に当たる file は見ていない"},
        "limits": {"max_bytes": MAX_BYTES, "hits_keep": HITS_KEEP, "key_min": KEY_MIN, "symbol_min": SYMBOL_MIN,
                   "name_hops": NAME_HOPS, "mention_hops": MENTION_HOPS},
        "heuristics": HEURISTICS,
    }


def map(repo, rev="HEAD", seeds=(), diff=False, cache_dir=None):   # noqa: A001 — 口の名は依頼の形のまま
    """変更の周りの地図（冒頭の説明）。cache_dir があれば同じ鍵の地図を読むだけにし、無ければ作って書く"""
    repo = pathlib.Path(repo)
    ix = _Index(repo, cache_dir)
    rev_sha = changemap.commit_oid(rev, cwd=str(repo))
    if rev_sha is None:
        raise RuntimeError(f"rev が commit でない: {rev}")
    changed = _diff_paths(repo, rev_sha, ix)
    diff_sha = hashlib.sha256(json.dumps(
        [[p, ix.files.get(p) or ix.special.get(p) or "-"] for p in changed]).encode()).hexdigest()
    key = hashlib.sha256(json.dumps([SCHEMA, _code_sha(), rev_sha, sorted(str(s) for s in seeds), bool(diff),
                                     diff_sha]).encode()).hexdigest()[:32]
    stats = {"scanned": ix.scanned, "reused": ix.reused}
    out_path = pathlib.Path(cache_dir) / f"map-{key}.json" if cache_dir else None
    if out_path and out_path.is_file():
        try:
            m = json.loads(out_path.read_text(encoding="utf-8"))
            ix.save()
            m["stats"] = {**stats, "cache": "hit"}
            return m
        except (OSError, ValueError):
            pass
    m = _build(repo, rev, rev_sha, changed, seeds, diff, ix)
    m["key"] = key
    m["diff_sha"] = diff_sha
    ix.save()
    if out_path:
        m["path"] = str(out_path)
        _write_json(out_path, m)
    m["stats"] = {**stats, "cache": "miss" if out_path else "none"}
    return m


def _mod(name):
    return _stem(name) if "/" in name or name.endswith(".py") else name


def direct(m, path) -> bool:
    """path が変更に直に関わるか: 起点そのものか、起点から辺 1 本（import か言及。深さ 1）で届いた file"""
    return path in m["seeds"]["files"] or m["reach"].get(path, {}).get("depth") == 1


def select_tests(m, fast=(), scope=None, all_modules=None, direct_only=False, named=()):
    """回すテストのモジュール。run_all（分からない物が近くに在る）なら全部。direct_only なら直に関わる試験（direct）と
    名指しの試験（named。根からのパス）だけを選び、届いただけの先の試験は left に名前で残す（回さない。run_all の時は空）。
    direct_only の run_all は、分からない物が直に関わる所（起点か深さ 1。地図の reach に無く置き場の分からない物も含める）に
    在る時だけで、深さ 2 以上の物は far に理由の形のまま残す（一式は線の最後のテストの段が回す。持ち主の決定 2026-10-06）"""
    sel = [t for t in m["tests"] if scope is None or t.startswith(scope)]
    run_all = bool(m["all_tests_required"])
    reasons, far = list(m["all_tests_reasons"]), []
    if direct_only and run_all:
        trig = [u for u in m["unanalysable"] if u["in_neighbourhood"] and u["reason"] in UNANALYSABLE_TRIGGERS]
        far = sorted({f"{u['reason']}: {u['path']}" + (f":{u['line']}" if u.get("line") else "")
                      for u in trig if u["path"] in m["reach"] and not direct(m, u["path"])})
        reasons = [r for r in reasons if r not in far]
        run_all = bool(reasons)
        far = [] if run_all else far
    left = []
    if direct_only and not run_all:
        named = set(named)
        left = [t for t in sel if t not in named and not direct(m, t)]
        sel = sorted((set(sel) - set(left)) | {t for t in named if scope is None or t.startswith(scope)})
    mods = sorted({_mod(t) for t in sel} | {_mod(f) for f in fast})
    if run_all:
        mods = sorted({_mod(x) for x in all_modules}) if all_modules is not None else None
    return {"key": m["key"], "run_all": run_all, "reasons": reasons, "far": far, "selected": sel,
            "outside_scope": [t for t in m["tests"] if t not in sel and t not in left], "fast": sorted({_mod(f) for f in fast}),
            "modules": mods, "left": left}


def _junit_module(case):
    f = case.get("file")
    if f:
        return _mod(f)
    for part in (case.get("classname") or "").split("."):
        if TEST_NAME.match(part + ".py") or part.startswith("test_"):
            return part
    return None


def tree_files(repo):
    """作業ツリーの file の一覧（追跡中と、無視されていない未追跡。submodule・symlink は除く）。git が使えなければ None"""
    try:
        return sorted(_Index(repo, None, scan=False).files)
    except RuntimeError:
        return None


def seeds_from_units(repo, units):
    """判定の単位の字に現れる追跡中の file（パスそのものか、一意な basename）"""
    ix = _Index(repo, None, scan=False)
    texts = []

    def walk(o):
        if isinstance(o, str):
            texts.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(units)
    text = "\n".join(texts)
    out = {p for p in ix.files if p in text}
    for base, owners in ix.by_base.items():
        if len(owners) == 1 and len(base) >= KEY_MIN and base not in STOP_KEYS and _hit_re("path", base).search(text):
            out.add(owners[0])
    return sorted(out)


# ---------------------------------------------------------------- 手で回す口
def main(argv=None):
    ap = argparse.ArgumentParser(prog="impact.py", description="変更の周りの地図")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("map")
    a.add_argument("repo")
    a.add_argument("--rev", default="HEAD")
    a.add_argument("--seed", action="append", default=[])
    a.add_argument("--units", help="判定の JSON（units を持つ）。単位の字から起点を足す")
    a.add_argument("--diff", action="store_true")
    a.add_argument("--cache")
    a.add_argument("--summary", action="store_true", help="数だけを出す")
    s = sub.add_parser("select")
    s.add_argument("map_json")
    s.add_argument("--fast", default="")
    s.add_argument("--scope")
    ns = ap.parse_args(argv)
    if ns.cmd == "map":
        seeds = list(ns.seed)
        if ns.units:
            doc = json.loads(pathlib.Path(ns.units).read_text(encoding="utf-8"))
            seeds += seeds_from_units(ns.repo, doc.get("units", doc))
        m = map(ns.repo, rev=ns.rev, seeds=seeds, diff=ns.diff, cache_dir=ns.cache)
        doc = {"key": m["key"], "counts": m["counts"], "all_tests_required": m["all_tests_required"],
               "stats": m["stats"], "path": m.get("path")} if ns.summary else m
        print(json.dumps(doc, ensure_ascii=False, indent=1))
        return 0
    m = json.loads(pathlib.Path(ns.map_json).read_text(encoding="utf-8"))
    fast = [f for f in ns.fast.split(",") if f] if getattr(ns, "fast", "") else []
    print(json.dumps(select_tests(m, fast=fast, scope=ns.scope), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
