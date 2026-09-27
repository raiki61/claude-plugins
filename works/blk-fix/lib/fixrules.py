"""修正役の指示書の組み立て（blk-fix。裁定 R65）。AI を通さず、機械が決まりの正本と道ごとの決まりと run の値を繋いで書く。

置き場（blk-fix/rules/）。どれも `<!-- 節 <id> -->` の行で節に切り、組むときに節を選ぶ（印の行は指示書に入れない）:
- common.md: 修正の決まりの正本。core-fix（直し方）・core-keep（守ること）は本線の核でいつも載せる。evidence・evidence-<種類>
  （テストで赤→緑を示せない直しの証拠。決定 C8）は、単位のファイルと差分に在る変更の種類（KINDS）の物だけを載せる。
  本線（p3.fix.md）から書き直した文は 1 本目の commands/fix.md から字のまま移した。ほかの置き場に写さない（tests/test_fix_rules.py）
- direct.md: 直す役（節 fix）の道。fix-head（役・読む物。run の値の穴 <<名>>）・fix-keep・fix-reply（返答の欄の書き方）
- tdd.md: TDD の輪の役（節 tdd）の道。tdd-head・tdd-remap（この輪での読み替え）・tdd-phase-<段>（今の段の約束だけ）・tdd-end

量を減らす 2 つの形（持ち主 2026-09-28）: 役は輪の周をまたいで 1 つの会話で起きる（fresh_context: false）。支度の節は毎回
2 つの形を並べて書く（write_variants）:
- <名>.full.md: 決まりを全部。<名>.md（役の節の 1 行が Read させるパス）はこの写し（包みが無い・会話の続きでない起動の既定）
- <名>.delta.md: 変わった物だけ（拒否の理由・今の段・この輪でまだ渡していない節）と、渡した決まりの sha256 の 1 行（この会話で
  まだ読んでいなければ決まりのファイル <名>.rules.md を Read せよ）。1 回目は full と同じ。どちらを渡すかは起動の時に包みが
  決める（--resume の起動だけ delta に差し替える。別の線）
- <名>.variants.json: {full, delta, rules_sha, iteration, sections}（機械が読む控え）
どの節を載せたか・なぜかは、各形の 1 行目（HEADER）にも機械の事実として書く（役ごとの量を前後で測る）。この輪で渡した節は
<名>.delivered.json に積む（どちらの形で起こしても、会話の続きはそれまでの回の決まりを全部読んでいる）。

型の穴は <<名>>。run の値は `値`（空は EMPTY）。埋めた値はもう一度読まない（1 回の置き換え）。穴に値が無い時は Unfilled。
同じ入力からはバイト単位で同じ指示書になる（時刻を書かない）。

- fix_prompt / tdd_prompt: 2 つの道の指示書（純粋な関数。prior を渡せば delta の形）
- prep: 節 fix-prep の中身（盤面が p3.fix を待っていれば書き、起こした印を置く）。tddloop.prep は tdd_render を使う
- reads_more: 節 fix-reads が読んだ証拠を集めるパスに足す物（今の周に組んだ指示書）
"""
import hashlib
import json
import pathlib
import posixpath
import re
import shutil
import sys

sys.dont_write_bytecode = True

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap  # noqa: E402  （board が写しの engine を sys.path に足す）
import entry  # noqa: E402
from leftovers import Unreadable, git_names  # noqa: E402
import recount  # noqa: E402
import rolekit  # noqa: E402
import script_io  # noqa: E402

RULES_DIR = pathlib.Path(__file__).resolve().parents[1] / "rules"
SHARED, DIRECT, TDD = "common.md", "direct.md", "tdd.md"
FIX_VALUES = ("judgment_file", "open_units", "plan_file", "policy_path", "notes_file", "summary_file")
TDD_VALUES = ("judgment_file", "open_units", "plan_file", "policy_path", "notes_file")
EMPTY = "（空）"
HOLE = re.compile(r"<<([a-z_]+)>>")
MARK = re.compile(r"^<!-- 節 ([a-z0-9-]+) -->$")
HEADER = "<!-- works-prompt {} -->"
KINDS = ("docs", "prompts", "config", "code")   # 変更の種類 → 節 evidence-<種類>
PHASES = ("route", "test", "fix", "refactor")
# 種類の見分け（パスの形だけで決める。当たらない物は種類なし）
PROMPT_DIRS = frozenset({"commands", "prompts", "agents", "skills", "rules"})
PROMPT_NAMES = frozenset({"CLAUDE.md", "AGENTS.md", "SKILL.md", "GEMINI.md"})
DOC_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".txt", ".adoc"})
CONFIG_SUFFIXES = frozenset({".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".conf"})
CONFIG_NAMES = frozenset({"Dockerfile", "Makefile", ".gitignore", ".gitattributes", ".editorconfig"})
CODE_SUFFIXES = frozenset({".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt", ".rb",
                           ".sh", ".bash", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift", ".php", ".scala", ".lua"})
PATH_TOKEN = re.compile(r"[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.[A-Za-z][A-Za-z0-9]*")
# 受け付け（scripts/accept.py の accept_fix を script_io.main が回す）が拒否の理由を書くファイル（script_io の名の決まり）
REJECT_GLOB = f"{script_io.REJECT_PREFIX}accept_fix-*.txt"
# 並べて書く形の名の尾（<名>.md の隣）
FULL, DELTA, RULES, VARIANTS, DELIVERED = ".full.md", ".delta.md", ".rules.md", ".variants.json", ".delivered.json"
WHY_FULL = "全部（包みが会話の続きと見ない起動の既定）"
WHY_DELTA = "変わった物だけ（会話の続きの起動で包みが差し替える）"
WHY_FIRST = "1 回目（この輪でまだ決まりを渡していない。delta は full と同じ）"
RULES_SAME = ("決まりは、この会話で前の回までに渡した物（sha256 {sha}）から変わっていない。この会話でまだ読んでいなければ、"
              "先に {path} を Read で全部読め。")
RULES_ADDED = ("決まりに下の節を足した（足した後の全体は sha256 {sha}。{path}）。ほかは、この会話で前の回までに渡した物から"
               "変わっていない（この会話でまだ読んでいなければ、先に {path} を Read で全部読め）。")


class Unfilled(ValueError):
    """型の穴に値が無い・値の名が要る物と違う（回す側の誤り）"""


# ---------------------------------------------------------------- 節
def sections(name: str) -> dict:
    """rules/<name> の節 {id: 本文}（ファイルの順。本文の前後の空行は落とす。印の行は入れない）"""
    out, cur = {}, None
    for line in (RULES_DIR / name).read_text(encoding="utf-8").split("\n"):
        m = MARK.match(line)
        if m:
            cur = m.group(1)
            if cur in out:
                raise Unfilled(f"{name}: 節 {cur} が 2 つ在る")
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
        elif line.strip():
            raise Unfilled(f"{name}: 節の印より前に文が在る: {line[:60]!r}")
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def join(texts) -> str:
    """節を繋ぐ: 箇条の行の後に箇条で始まる節が来れば改行 1 つ（同じ箇条を続ける）、ほかは空行 1 つ"""
    out = ""
    for t in texts:
        if not t:
            continue
        if out:
            last = out.rsplit("\n", 1)[-1]
            out += "\n" if t.startswith("- ") and (last.startswith("- ") or last.startswith("  ")) else "\n\n"
        out += t
    return out


def shared() -> str:
    """修正の決まりの正本の全文（全部の節。印の行を除いた字）"""
    return join(sections(SHARED).values())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 値の穴
def _value(v) -> str:
    v = "" if v is None else str(v)
    return f"`{v}`" if v else EMPTY


def fill(template: str, values: dict) -> str:
    """型の穴 <<名>> を `値`（空は EMPTY）で埋める。1 回の置き換え（埋めた字を読み直さない）"""
    lack = sorted(set(HOLE.findall(template)) - set(values))
    if lack:
        raise Unfilled(f"型の穴に値が無い: {lack}")
    return HOLE.sub(lambda m: _value(values[m.group(1)]), template)


def _pick(values: dict, names: tuple) -> dict:
    lack = [k for k in names if k not in values]
    if lack:
        raise Unfilled(f"run の値が無い: {lack}")
    return {k: values[k] for k in names}


# ---------------------------------------------------------------- 変更の種類
def kind_of(path: str):
    """パスの形から変更の種類（KINDS のどれか。分からなければ None）"""
    p = posixpath.normpath(str(path).strip())
    name = posixpath.basename(p)
    suffix = posixpath.splitext(name)[1].lower()
    dirs = set(p.split("/")[:-1])
    if name in PROMPT_NAMES or (suffix in DOC_SUFFIXES and dirs & PROMPT_DIRS):
        return "prompts"
    if suffix in DOC_SUFFIXES:
        return "docs"
    if suffix in CONFIG_SUFFIXES or name in CONFIG_NAMES or "/.github/workflows/" in f"/{p}":
        return "config"
    if suffix in CODE_SUFFIXES:
        return "code"
    return None


def unit_paths(judgment_file: str, open_units: str) -> tuple:
    """判定の直す義務の単位が指すパス（class_query の how の paths と、key の中のパスの形の語）。(パスの一覧, 読めない理由)"""
    try:
        doc = json.loads(pathlib.Path(judgment_file).read_text(encoding="utf-8"))
        keys = set(json.loads(open_units))
    except (OSError, ValueError, TypeError) as e:
        return [], f"判定か義務の単位が読めない（{type(e).__name__}）"
    out = []
    for u in (doc.get("units") if isinstance(doc, dict) else None) or []:
        if not isinstance(u, dict) or u.get("key") not in keys:
            continue
        how = (u.get("class_query") or {}).get("how") or {}
        out += [p for p in how.get("paths") or [] if isinstance(p, str)]
        out += PATH_TOKEN.findall(u["key"])
    return list(dict.fromkeys(out)), ""


def changed_paths(repo) -> list:
    """作業ツリーの今の差分（HEAD からの変更と未追跡。.gitignore に当たる物は除く）のパス。git が効かなければ空"""
    try:
        got = git_names(repo, "diff", "--name-only", "--no-renames", "HEAD", "--")
        got += git_names(repo, "ls-files", "--others", "--exclude-standard", "--full-name", "--", ":/")
    except Unreadable:
        return []
    return list(dict.fromkeys(got))


def select_kinds(sources: dict) -> dict:
    """{出どころ: パスの一覧} から {種類: 理由}（理由はどの出どころのどのパスか。機械の事実）。どの種類も見つからなければ
    全部の種類を「分からない」の理由で選ぶ（証拠の決まりを落とさない側）"""
    got = {}
    for src, paths in sources.items():
        for p in paths:
            k = kind_of(p)
            if k:
                got.setdefault(k, []).append(f"{src} {p}")
    if not got:
        seen = sum(len(v) for v in sources.values())
        return {k: f"変更の種類が分からない（パス {seen} 本から見分けられない）——全部載せる" for k in KINDS}
    return {k: "; ".join(got[k][:5]) + (f" ほか {len(got[k]) - 5} 本" if len(got[k]) > 5 else "") for k in KINDS if k in got}



# ---------------------------------------------------------------- 組み立て（純粋）
ALWAYS = "いつも"


def _evidence(common: dict, kinds: dict) -> list:
    if not kinds:
        return []
    return [("evidence", common["evidence"], "変更の種類: " + "・".join(k for k in KINDS if k in kinds))] + \
           [(f"evidence-{k}", common[f"evidence-{k}"], kinds[k]) for k in KINDS if k in kinds]


def _all_kinds() -> dict:
    return {k: "種類を選ばない組み立て（全部）" for k in KINDS}


def fix_parts(values: dict, kinds: dict | None = None) -> list:
    """直す役の決まりの節 [(id, 本文, 理由)]（順は指示書の順）"""
    c, d = sections(SHARED), sections(DIRECT)
    kinds = _all_kinds() if kinds is None else kinds
    return [("fix-head", fill(d["fix-head"], _pick(values, FIX_VALUES)), ALWAYS + "（役・読む物・run の値）"),
            ("core-fix", c["core-fix"], ALWAYS + "（本線の核）"), *_evidence(c, kinds),
            ("core-keep", c["core-keep"], ALWAYS + "（本線の核）"), ("fix-keep", d["fix-keep"], ALWAYS + "（直す役）"),
            ("fix-reply", d["fix-reply"], ALWAYS + "（返答の欄）")]


def tdd_parts(values: dict, kinds: dict | None = None) -> list:
    """TDD の輪の役の決まりの節（段によらない物）"""
    c, t = sections(SHARED), sections(TDD)
    kinds = _all_kinds() if kinds is None else kinds
    return [("tdd-head", fill(t["tdd-head"], _pick(values, TDD_VALUES)), ALWAYS + "（役・読む物・run の値）"),
            ("core-fix", c["core-fix"], ALWAYS + "（本線の核）"), *_evidence(c, kinds),
            ("core-keep", c["core-keep"], ALWAYS + "（本線の核）"), ("tdd-remap", t["tdd-remap"], ALWAYS + "（この輪での読み替え）")]


def tdd_phase_rules(phase: str) -> str:
    """今の段の約束（その段の行と、どの段にも当たる行だけ）"""
    if phase not in PHASES:
        raise Unfilled(f"段 {phase!r} は {PHASES} のどれでもない")
    t = sections(TDD)
    return join([t["tdd-phase"], t[f"tdd-phase-{phase}"], t["tdd-phase-all"]])


def render(role: str, iteration: int, parts: list, *, prior=None, rules_file: str = "", before=(), after=(),
           reject_file: str = "") -> dict:
    """1 つの形 {text, delivered, rules_text, head}。prior が None なら決まりの節を全部（full）、{delivered: {id: sha}} なら
    まだ渡していない・中身が替わった節だけと RULES_SAME / RULES_ADDED の 1 行（delta）。delivered は渡した後の {id: sha}。
    並び: HEADER → [拒否の理由のファイルの 1 行] → before → 決まり → after"""
    shas = {pid: _sha(text) for pid, text, _ in parts}
    rules_text = join(text for _, text, _ in parts)
    rules_sha = _sha(rules_text)
    old = None if prior is None else (prior.get("delivered") or {})
    if old is None:
        sent, body, mode, why = [pid for pid, _, _ in parts], [rules_text], "full", WHY_FULL
    else:
        sent = [pid for pid, _, _ in parts if old.get(pid) != shas[pid]]
        line = (RULES_ADDED if sent else RULES_SAME).format(sha=rules_sha, path=rules_file or EMPTY)
        body, mode, why = [line, join(text for pid, text, _ in parts if pid in sent)], "delta", WHY_DELTA
    head = {"role": role, "iteration": iteration, "mode": mode, "why": why, "rules_sha": rules_sha, "rules_file": rules_file,
            "sections": [{"id": pid, "why": w, "sent": pid in sent} for pid, _, w in parts]}
    text = rolekit.compose([*before, *body, *after], reject_file=reject_file)
    text = HEADER.format(json.dumps(head, ensure_ascii=False)) + "\n" + text.rstrip("\n") + "\n"
    return {"text": text, "delivered": {**(old or {}), **shas}, "rules_text": rules_text, "head": head}


def fix_prompt(values: dict, *, kinds: dict | None = None, reject_file: str = "", prior=None, iteration: int = 1,
               rules_file: str = "") -> str:
    """直す役の指示書の 1 つの形（純粋）"""
    return render("fix", iteration, fix_parts(values, kinds), prior=prior, rules_file=rules_file, reject_file=reject_file)["text"]


def tdd_prompt(values: dict, phase: str, phase_text: str, *, title: str, reason: str = "", kinds: dict | None = None,
               prior=None, iteration: int = 1, rules_file: str = "") -> str:
    """TDD の輪の役の指示書の 1 つの形（純粋）"""
    return tdd_render(values, phase, phase_text, title=title, reason=reason, kinds=kinds, prior=prior, iteration=iteration,
                      rules_file=rules_file)["text"]


def tdd_render(values, phase, phase_text, *, title, reason="", kinds=None, prior=None, iteration=1, rules_file="") -> dict:
    """tdd_prompt の形 {text, delivered, rules_text, head}。並び: 題 → [拒んだ理由] → 決まり → 今の段の約束 → 今の段（tddloop が書く）→ 結び"""
    before = [title]
    if reason:
        before.append("## 前の回の返答を機械が拒んだ理由（直して、この段の返答を丸ごと出し直せ）\n\n" + reason.rstrip("\n"))
    after = [tdd_phase_rules(phase), phase_text.rstrip("\n"), sections(TDD)["tdd-end"]]
    return render("tdd", iteration, tdd_parts(values, kinds), prior=prior, rules_file=rules_file, before=before, after=after)


# ---------------------------------------------------------------- 2 つの形を並べて書く（支度の節）
def _read_json(path: pathlib.Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def beside(prompt: pathlib.Path, tail: str) -> pathlib.Path:
    """<名>.md の隣の <名><tail>"""
    return prompt.with_name(prompt.name[:-len(".md")] + tail if prompt.name.endswith(".md") else prompt.name + tail)


def kinds_now(values: dict, repo, before=()) -> dict:
    """今の組み立てで載せる証拠の種類: 判定の単位のパスと今の差分から選び、この輪で前に渡した種類を足す（輪の中で減らさない）"""
    paths, why = unit_paths(values.get("judgment_file") or "", values.get("open_units") or "")
    sources = {"判定": paths, "差分": changed_paths(repo) if repo is not None else []}
    got = select_kinds(sources)
    if why and not any(sources.values()):
        got = {k: f"{why}——全部載せる" for k in KINDS}
    for k in before:
        got.setdefault(k, "この輪で前に渡した")
    return got


def iteration_next(prompt: pathlib.Path) -> int:
    """この輪で次に組む回の番号（<名>.delivered.json の iterations の数 + 1）"""
    return len((_read_json(beside(prompt, DELIVERED)) or {}).get("iterations") or []) + 1


def write_variants(prompt: pathlib.Path, repo, values: dict, build, iteration: int) -> dict:
    """2 つの形を prompt の隣に書き、prompt は full の写しにする。build(kinds, prior, rules_file) -> render の返り。
    この輪で前に渡した節（<名>.delivered.json）を prior にして delta を組み、渡した後の節・種類・回を積む。repo が None なら
    差分を見ない。返り（<名>.variants.json と同じ）{full, delta, rules_sha, iteration, delta_is_full, why, sections}"""
    ledger = beside(prompt, DELIVERED)
    done = _read_json(ledger)
    done = done if isinstance(done, dict) and isinstance(done.get("delivered"), dict) else {}
    prior = done or None
    kinds = kinds_now(values, repo, done.get("kinds") or ())
    rules = beside(prompt, RULES)
    full = build(kinds, None, str(rules))
    delta = full if prior is None else build(kinds, prior, str(rules))
    paths = {"full": beside(prompt, FULL), "delta": beside(prompt, DELTA)}
    paths["full"].write_text(full["text"], encoding="utf-8")
    paths["delta"].write_text(delta["text"], encoding="utf-8")
    shutil.copyfile(paths["full"], prompt)
    rules.write_text(full["rules_text"] + "\n", encoding="utf-8")
    got = {"full": str(paths["full"]), "delta": str(paths["delta"]), "rules_sha": full["head"]["rules_sha"],
           "iteration": iteration, "delta_is_full": prior is None, "why": WHY_FIRST if prior is None else WHY_DELTA,
           "sections": delta["head"]["sections"]}
    _write_json(beside(prompt, VARIANTS), got)
    _write_json(ledger, {**done, "delivered": {**(done.get("delivered") or {}), **full["delivered"]}, "kinds": sorted(kinds),
                         "iterations": [*(done.get("iterations") or []), iteration]})
    return got


# ---------------------------------------------------------------- 節 fix-prep
def prompt_path(b) -> pathlib.Path:
    return b.work(rolekit.prompt_name(recount.FIX_NODE))


def last_reject(board_dir) -> str:
    """受け付けが書いた一番新しい拒否の理由のファイル（無ければ空）"""
    def n(p):
        tail = p.stem.rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else -1
    got = sorted(pathlib.Path(board_dir).glob(REJECT_GLOB), key=n)
    return str(got[-1]) if got else ""


def prep(board_dir, repo, values: dict) -> dict:
    """節 fix-prep: 2 つの形を書き（prompt_file は full の写し）、起こした印を置く。返り {prompt_file, attempt, out_path, node,
    already, variants_file, iteration}（iteration はこの周の輪の何回目か。fix-accept が 3 回目の拒否で done を立てる。R50）。同じ試行の出し直し（印が既に在る。通れば輪を抜けるので、前の回の返答は受け付けで拒まれた）なら、
    受け付けが書いた一番新しい拒否の理由のファイルを見出しの次の 1 行で名指す（R44）。盤面が p3.fix を待っていなければ BoardGap"""
    nid = recount.FIX_NODE
    b = entry.open_board(pathlib.Path(board_dir))
    inst = b.rd["instances"].get(nid)
    if not inst or inst.get("status") != "pending":
        raise BoardGap(f"この周に節 {nid} の待っている instance が無い（修正役を起こす番でない）")
    reject = last_reject(board_dir) if inst.get("launched_at") else ""
    path = prompt_path(b)
    n = iteration_next(path)

    def build(kinds, prior, rules_file):
        return render("fix", n, fix_parts(values, kinds), prior=prior, rules_file=rules_file, reject_file=reject)
    write_variants(path, repo, values, build, n)
    m = b.mark_launched(nid, inst.get("attempts", 1))
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid, "already": m["already"],
            "variants_file": str(beside(path, VARIANTS)), "iteration": n}


def reads_more(board_dir) -> list:
    """節 fix-reads が読んだ証拠を集めるパスに足す物: 今の周に組んだ指示書（在れば）"""
    p = prompt_path(entry.open_board(pathlib.Path(board_dir), allow_halted=True))
    return [str(p)] if p.is_file() else []
