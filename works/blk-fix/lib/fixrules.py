"""修正役の指示書の組み立て（blk-fix。裁定 R65）。AI を通さず、機械が決まりの正本と道ごとの決まりと run の値を繋いで書く。
節に切る・穴を埋める・形を描く口は .shared/core/rulebook（ほかのブロックの書く役も同じ正本から組む）。

置き場。どれも `<!-- 節 <id> -->` の行で節に切り、組むときに節を選ぶ（印の行は指示書に入れない）:
- 修正の決まりの正本（SHARED = rulebook.CANON。.shared/core/writerules/common.md）: core-fix（直し方）・core-keep（守ること）は
  本線の核でいつも載せる。evidence・evidence-<種類>（テストで赤→緑を示せない直しの証拠。決定 C8）は、単位のファイルと差分に在る
  変更の種類（KINDS）の物だけを載せる
- rules/brief.md: 要求の正本の決まり（節 brief-canon）。頭に並んだ brief（承認済みの修正案の項目を planbrief が切り出して凍結した物）を
  要求の正本とし、判定のファイルを背景に下げる。修正役と TDD の輪の役にだけ、頭の節の次にいつも載せる（裁定役と手直しの役には
  載せない。頭に brief の節が無い run では、節の 6 で判定のファイルが正本のまま）
- rules/direct.md: 直す役（節 fix）の道。fix-head（役・読む物。run の値の穴 <<名>>）・fix-keep・fix-reply（返答の欄の書き方）
- rules/tdd.md: TDD の輪の役（節 tdd）の道。tdd-head・tdd-remap（この輪での読み替え）・tdd-phase-<段>（今の段の約束だけ）・tdd-end
- rules/ruler.md・principles.md: 食い違いの申し出の裁定役（節 rule。読むだけ）の道と、持ち主の決まり（裁定の拠り所）。
  修正役と TDD の輪の役の両方に、正本の core-conflict（緑にするために曲げず、食い違いとして返す）をいつも載せる

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
- prep: 節 fix-prep・fix-ruled-prep の中身（盤面が p3.fix を待っていれば書き、起こした印を置く）。tddloop.prep は tdd_render を使う。
  どちらも指示書の頭（題の次）に、直す義務の単位の brief（planbrief.cut。承認済みの修正案の項目を凍結した物）を名指す節を置く。
  brief の控えが壊れていれば盤面を止める（brief_halt。brief の無い指示書として続けない）
- ruler_prompt: 裁定役の指示書（ruling.prep が書く）
- reads_more: 節 fix-reads が読んだ証拠を集めるパスに足す物（今の周に組んだ指示書と brief のファイル）
- tagged: 回の印（pass_tag。依頼 226 の 2 回目の修正の段は refit）をファイルの名の拡張子の前に足す唯一の口（script_io.tagged。
  core の conflict の裁定の文・申し出の回の控えと、拒否の理由のファイルも同じ決まり）。同じ周に修正役を 2 度起こす段が、指示書
  （と隣の .full.md・.delta.md・.variants.json・.delivered.json・.rules.md）・裁定の後の尾・拒否の理由・裁定の文・申し出の回の
  控えの名を分ける。印が空なら今の名のまま。2 回目の段は自分の数えから始まり、3 回の諦めを回ごとに数え、最初の指示書は
  新しい役が見ていない会話への差分（delta）にならない
- 1 回目の修正の段で受け付けた返答の控え（conflict.held_reply）が在る時だけ、修正役の指示書の brief の節の後に HELD_HEAD の節
  （HELD_ASK）を置く（2 回目の修正の段）
"""
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
import conflict  # noqa: E402
import entry  # noqa: E402
from leftovers import Unreadable, git_names  # noqa: E402
import libdocs  # noqa: E402
import planbrief  # noqa: E402  （同じブロックの lib。承認済みの修正案の項目ごとの brief の凍結）
import recount  # noqa: E402
import rolekit  # noqa: E402
import rulebook  # noqa: E402
from rulebook import EMPTY, MARK, RULES_SAME, WHY_DELTA, Unfilled, fill, join, render, shared  # noqa: E402,F401
import script_io  # noqa: E402
from engine.util import Reject  # noqa: E402

RULES_DIR = pathlib.Path(__file__).resolve().parents[1] / "rules"
SHARED = rulebook.CANON
DIRECT, TDD = "direct.md", "tdd.md"
BRIEF = "brief.md"   # brief の決まり（要求の正本と背景）（修正役と TDD の輪の役にだけ載せる）
BRIEF_WHY = "（要求の正本と背景）"
RULER, PRINCIPLES = "ruler.md", "principles.md"   # 裁定役の道と、持ち主の決まり（裁定の拠り所）
FIX_VALUES = ("judgment_file", "open_units", "plan_file", "policy_path", "notes_file", "summary_file")
TDD_VALUES = ("judgment_file", "open_units", "plan_file", "policy_path", "notes_file")
RULER_VALUES = ("conflicts_file", "ids", "judgment_file", "request_file", "policy_path")
CONFLICT_WHY = "（食い違いの申し出。緑にするために曲げない）"
PASSES = ("first", "ruled")   # 修正役の 1 回目と、裁定の後の 2 回目（印 continue=fix の会話の続き）
RULED_TAIL = "-ruled.md"      # 2 回目の指示書の名の尾（1 回目の <名>.md の隣。輪の控えを分ける）
RULINGS_LINE = ("食い違いの申し出への裁定を書いたファイル {path} を、先に Read で全部読め。裁定に従って直し、返答を丸ごと出し直せ"
                "（裁定の文そのものはここに貼らない）")
tagged = script_io.tagged   # 回の印をファイルの名に足す唯一の口（tagged(name, pass_tag)。core も同じ決まりを使うので本体は script_io）
HELD_HEAD = "## 1 回目の修正の段で受け付けた返答（機械が貼った）"
HELD_ASK = ("控え {path} を Read で読め。直す義務は上の「読む物」の「直す義務の単位の key」（案を直して戻った単位）だけで、"
            "控えの単位の行は機械が足す——changes と not_done に控えの単位を書くな。changes と not_done の外の欄（fix_closure・mechanism_changed・"
            "plan_faces など）は、1 回目と今回を合わせた差分の全体について書け（控えの値から始めよ）。")
HELD_WHY = "1 回目の修正の段で受け付けた返答の控えが在る（2 回目の修正の段）"
KINDS = ("docs", "prompts", "config", "code")   # 変更の種類 → 節 evidence-<種類>
PHASES = ("route", "test", "fix", "refactor")
# 種類の見分け（パスの形だけで決める。当たらない物は種類なし）
PROMPT_DIRS = frozenset({"commands", "prompts", "agents", "skills", "rules", rulebook.CANON.parent.name})
PROMPT_NAMES = frozenset({"CLAUDE.md", "AGENTS.md", "SKILL.md", "GEMINI.md"})
DOC_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".txt", ".adoc"})
CONFIG_SUFFIXES = frozenset({".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".conf"})
CONFIG_NAMES = frozenset({"Dockerfile", "Makefile", ".gitignore", ".gitattributes", ".editorconfig"})
CODE_SUFFIXES = frozenset({".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rs", ".java", ".kt", ".rb",
                           ".sh", ".bash", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift", ".php", ".scala", ".lua"})
PATH_TOKEN = re.compile(r"[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.[A-Za-z][A-Za-z0-9]*")
# 受け付け（scripts/accept.py の accept_fix を script_io.main が回す）が拒否の理由を書くファイル（script_io の名の決まり）
REJECT_FN = "accept_fix"   # 受け付けの関数の名（拒否の理由のファイルの名。script_io.reject_name）
REJECT_GLOB = script_io.reject_name(REJECT_FN, "*")
# 並べて書く形の名の尾（<名>.md の隣）
FULL, DELTA, RULES, VARIANTS, DELIVERED = ".full.md", ".delta.md", ".rules.md", ".variants.json", ".delivered.json"
WHY_FIRST = "1 回目（この輪でまだ決まりを渡していない。delta は full と同じ）"
BRIEF_STOP_BY = "works:fix"   # brief の控えが壊れた盤面を止めた口（assert-changed の STOP_BY と同じ修正の段の印）
BRIEF_BROKEN = (f"修正案の brief の控え（今の周の {planbrief.LEDGER}）か欄の控え（盤面の {planbrief.planmarks.FIELDS_FILE}）が壊れているか"
                "凍結の後に書き換えられ、承認した要求の正本が"
                "引けない——brief の無い指示書で役を起こさずに盤面を止める")
_sha = rulebook.sha
_pick = rulebook.pick


# ---------------------------------------------------------------- 節
def sections(name) -> dict:
    """rules/<name> の節 {id: 本文}。SHARED は .shared/core の正本（rulebook.sections）"""
    return rulebook.sections(SHARED if name == SHARED else RULES_DIR / name)


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


def held_text(held_path) -> str:
    """1 回目に受け付けた返答の控えの節（HELD_HEAD と HELD_ASK。held_path が空なら空）"""
    return f"{HELD_HEAD}\n\n{HELD_ASK.format(path=held_path)}" if held_path else ""


def fix_parts(values: dict, kinds: dict | None = None, libdocs: str = "", held: str = "") -> list:
    """直す役の決まりの節 [(id, 本文, 理由)]（順は指示書の順）。libdocs はライブラリの今の文書の節（libdocs.section。空なら載せない）。
    held は 1 回目に受け付けた返答の控えの節（held_text。空なら載せない）で、brief の節の後に置く"""
    c, d = sections(SHARED), sections(DIRECT)
    kinds = _all_kinds() if kinds is None else kinds
    return [("fix-head", fill(d["fix-head"], _pick(values, FIX_VALUES)), ALWAYS + "（役・読む物・run の値）"),
            ("brief-canon", sections(BRIEF)["brief-canon"], ALWAYS + BRIEF_WHY),
            *([("held", held, HELD_WHY)] if held else []),
            ("core-fix", c["core-fix"], ALWAYS + "（本線の核）"), *_evidence(c, kinds),
            ("core-conflict", c["core-conflict"], ALWAYS + CONFLICT_WHY), ("core-keep", c["core-keep"], ALWAYS + "（本線の核）"),
            ("fix-keep", d["fix-keep"], ALWAYS + "（直す役）"),
            *([("libdocs", libdocs, "機械が引いた（Context7。見つけた数と取れた数は節の頭）")] if libdocs else []),
            ("fix-reply", d["fix-reply"], ALWAYS + "（返答の欄）")]


def tdd_parts(values: dict, kinds: dict | None = None) -> list:
    """TDD の輪の役の決まりの節（段によらない物）"""
    c, t = sections(SHARED), sections(TDD)
    kinds = _all_kinds() if kinds is None else kinds
    return [("tdd-head", fill(t["tdd-head"], _pick(values, TDD_VALUES)), ALWAYS + "（役・読む物・run の値）"),
            ("brief-canon", sections(BRIEF)["brief-canon"], ALWAYS + BRIEF_WHY),
            ("core-fix", c["core-fix"], ALWAYS + "（本線の核）"), *_evidence(c, kinds),
            ("core-conflict", c["core-conflict"], ALWAYS + CONFLICT_WHY), ("core-keep", c["core-keep"], ALWAYS + "（本線の核）"),
            ("tdd-remap", t["tdd-remap"], ALWAYS + "（この輪での読み替え）")]


def tdd_phase_rules(phase: str) -> str:
    """今の段の約束（その段の行と、どの段にも当たる行だけ）"""
    if phase not in PHASES:
        raise Unfilled(f"段 {phase!r} は {PHASES} のどれでもない")
    t = sections(TDD)
    return join([t["tdd-phase"], t[f"tdd-phase-{phase}"], t["tdd-phase-all"]])


def ruler_parts(values: dict) -> list:
    """裁定役の決まりの節（役・読む物・run の値 → 持ち主の決まり → 返す JSON）"""
    r, pr = sections(RULER), sections(PRINCIPLES)
    return [("ruler-head", fill(r["ruler-head"], _pick(values, RULER_VALUES)), ALWAYS + "（役・読む物・run の値）"),
            ("principles", pr["principles"], ALWAYS + "（持ち主の決まり）"), ("ruler-reply", r["ruler-reply"], ALWAYS + "（返答の欄）")]


def ruler_prompt(values: dict, *, reject_file: str = "", iteration: int = 1, lang: str = "") -> str:
    """裁定役の指示書（純粋。いつも全部——輪は 3 回までで、出し直しは同じ会話）。lang は言語の 1 行（lang_at）"""
    return render("rule", iteration, ruler_parts(values), reject_file=reject_file, lang=lang)["text"]


def fix_prompt(values: dict, *, kinds: dict | None = None, reject_file: str = "", prior=None, iteration: int = 1,
               rules_file: str = "", libdocs: str = "") -> str:
    """直す役の指示書の 1 つの形（純粋）"""
    return render("fix", iteration, fix_parts(values, kinds, libdocs), prior=prior, rules_file=rules_file,
                  reject_file=reject_file)["text"]


def tdd_prompt(values: dict, phase: str, phase_text: str, *, title: str, reason: str = "", kinds: dict | None = None,
               prior=None, iteration: int = 1, rules_file: str = "", brief: str = "") -> str:
    """TDD の輪の役の指示書の 1 つの形（純粋）"""
    return tdd_render(values, phase, phase_text, title=title, reason=reason, kinds=kinds, prior=prior, iteration=iteration,
                      rules_file=rules_file, brief=brief)["text"]


def tdd_render(values, phase, phase_text, *, title, reason="", kinds=None, prior=None, iteration=1, rules_file="",
               lang="", brief="") -> dict:
    """tdd_prompt の形 {text, delivered, rules_text, head}。並び: 題 → [brief の節（planbrief.head_text）] → [拒んだ理由] → 決まり
    → 今の段の約束 → 今の段（tddloop が書く）→ 結び → [言語の 1 行（lang_at）]"""
    before = [title, *([brief] if brief else [])]
    if reason:
        before.append("## 前の回の返答を機械が拒んだ理由（直して、この段の返答を丸ごと出し直せ）\n\n" + reason.rstrip("\n"))
    after = [tdd_phase_rules(phase), phase_text.rstrip("\n"), sections(TDD)["tdd-end"]]
    return render("tdd", iteration, tdd_parts(values, kinds), prior=prior, rules_file=rules_file, before=before, after=after,
                  lang=lang)


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
def lib_section(b, repo, values: dict) -> str:
    """ライブラリの今の文書の節（libdocs.section）: 直す義務の単位のファイルと今の差分のファイルが使うライブラリ"""
    try:
        keys = set(json.loads(values.get("open_units") or "[]"))
    except (ValueError, TypeError):
        keys = None
    files, why = libdocs.unit_files(repo, values.get("judgment_file") or "", keys) if repo is not None else ([], "")
    text = libdocs.section(b, repo, files + (changed_paths(repo) if repo is not None else []))
    return text + (f"\n- 単位のファイルの引き: {why}" if why else "")


def prompt_path(b, pass_tag: str = "") -> pathlib.Path:
    """修正役の指示書（回の印 pass_tag で名を分ける）"""
    return b.work(tagged(rolekit.prompt_name(recount.FIX_NODE), pass_tag))


def last_reject(board_dir, pass_tag: str = "") -> str:
    """受け付けが回の印 pass_tag で書いた一番新しい拒否の理由のファイル（無ければ空。ほかの回の印の物は見ない。script_io.last_reject）"""
    return script_io.last_reject(board_dir, REJECT_FN, pass_tag)


def owed_values(b, values: dict) -> dict:
    """指示書に埋める値の open_units を、受け付けと同じ conflict.fix_duty の owed に替えた物（判定の出口の is_open の並びを
    保ち、関所で答えて直す義務に戻った単位を後ろに足す）。出口の値が読めなければ owed の並べ替えだけ"""
    try:
        keys = json.loads(values.get("open_units") or "[]")
    except (ValueError, TypeError):
        keys = []
    owed, _ = conflict.fix_duty(b)
    seen = [k for k in keys if k in owed] if isinstance(keys, list) else []
    return {**values, "open_units": json.dumps(seen + sorted(owed - set(seen)), ensure_ascii=False)}


def brief_halt(b, err) -> str:
    """brief の控えが壊れた（planbrief.LedgerBroken の err）盤面を止め（by BRIEF_STOP_BY。もう止まった盤面は止め直さない。b が None
    なら止めない）、控えを名指す理由の 1 行を返す。止められなければ、そのわけを理由に足す"""
    why = f"{BRIEF_BROKEN}: {' '.join(str(err).split())}"
    if b is not None and not (b.state.get("halted") or b.state.get("stop")):
        try:
            b.stop(why, by=BRIEF_STOP_BY)
        except Reject as e:
            why += f"（盤面を止められない: {' '.join(str(e).split())}）"
    return why


def briefs_or_halt(b) -> list:
    """今の周の brief（planbrief.cut。修正案の欄の控えが無い run は []）。控えが壊れていれば盤面を止めて理由の BoardGap（黙って
    brief の無い指示書にしない）。cut は凍結の印を trace に書くので、開いたばかりの盤面で、起こした印（mark_launched）より前に呼ぶ"""
    try:
        return planbrief.cut(b)
    except planbrief.LedgerBroken as e:
        raise BoardGap(brief_halt(b, e)) from None


def prep(board_dir, repo, values: dict, pass_: str = PASSES[0], pass_tag: str = "") -> dict:
    """節 fix-prep（pass_ first）と fix-ruled-prep（pass_ ruled）: 2 つの形を書き（prompt_file は full の写し）、起こした印を置く。
    返り {prompt_file, attempt, out_path, node, already, variants_file, iteration}（iteration はこの輪の何回目か。受け付けが
    3 回目の拒否で done を立てる。R50）。同じ試行の出し直し（印が既に在る。通れば輪を抜けるので、前の回の返答は受け付けで
    拒まれた）なら、受け付けが書いた一番新しい拒否の理由のファイルを見出しの次の 1 行で名指す（R44）。
    ruled は指示書を <名>-ruled.md に分け（輪の回を別に数える）、1 回目は裁定の文のファイル（conflict.RULINGS_FILE）を見出しの
    次の 1 行で名指す（裁定の文は貼らない。R44）。盤面が p3.fix を待っていなければ BoardGap。
    full と delta の頭（題の次。ruled の 1 回目は裁定の文のファイルの行の後）に、直す義務の単位の brief を名指す節
    （planbrief.head_text。義務から外れた単位には「今は直すな」）を置く（1 回目も ruled も同じ凍結の中身）。
    brief の控えが壊れていれば盤面を止めて BoardGap（briefs_or_halt。指示書を書かず、起こした印も置かない）。
    pass_tag は回の印（tagged。依頼 226 の 2 回目の修正の段）: 指示書・裁定の後の尾・拒否の理由・裁定の文の名を分け、数えと
    拒否の名指しはその印の物だけを見る（起こした印は 1 回目の段が置いた物のまま）。1 回目に受け付けた返答の控え
    （conflict.held_reply）が在れば、brief の節の後に控えの節（held_text）を置く"""
    if pass_ not in PASSES:
        raise Unfilled(f"pass {pass_!r} は {PASSES} のどれでもない")
    nid = recount.FIX_NODE
    b = entry.open_board(pathlib.Path(board_dir))
    inst = b.rd["instances"].get(nid)
    if not inst or inst.get("status") != "pending":
        raise BoardGap(f"この周に節 {nid} の待っている instance が無い（修正役を起こす番でない）")
    briefs = briefs_or_halt(b)   # 開いたばかりの盤面で（裁定の文を書く・起こした印を置くより前に）凍結する
    name = rolekit.prompt_name(nid)
    before = ()
    if pass_ == "ruled":
        name = name[:-len(".md")] + RULED_TAIL
    path = b.work(tagged(name, pass_tag))
    n = iteration_next(path)
    reject = last_reject(board_dir, pass_tag) if inst.get("launched_at") else ""
    if pass_ == "ruled" and n == 1:
        rulings = b.work(tagged(conflict.RULINGS_FILE, pass_tag))
        if not rulings.is_file():
            rulings = conflict.write_rulings(b, pass_tag)
        reject, before = "", (RULINGS_LINE.format(path=rulings),)
    values = owed_values(b, values)
    owed = json.loads(values["open_units"])
    head = planbrief.head_text(planbrief.for_units(briefs, owed), owed)
    before = tuple(x for x in (*before, head) if x)   # ruled の裁定の文の行は見出しの次の 1 行のまま（R44）。brief はその後
    docs = lib_section(b, repo, values)
    lang = rolekit.lang_line(b.state.get("inputs"))
    held, held_path = conflict.held_reply(b)
    held = held_text(held_path if held is not None else "")

    def build(kinds, prior, rules_file):
        return render("fix", n, fix_parts(values, kinds, docs, held), prior=prior, rules_file=rules_file, reject_file=reject,
                      before=before, lang=lang)
    write_variants(path, repo, values, build, n)
    m = b.mark_launched(nid, inst.get("attempts", 1))
    return {"prompt_file": str(path), "attempt": m["attempt"], "out_path": m["out_path"], "node": nid, "already": m["already"],
            "variants_file": str(beside(path, VARIANTS)), "iteration": n}


def lang_at(board_dir) -> str:
    """盤面の言語の 1 行（rolekit.lang_line）。盤面が開けなければ空（盤面の外で組む指示書には置かない）"""
    try:
        b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    except BoardGap:
        return ""
    return rolekit.lang_line(b.state.get("inputs"))


def reads_more(board_dir, pass_tag: str = "") -> list:
    """節 fix-reads が読んだ証拠を集めるパスに足す物: 今の周に組んだ指示書（回の印 pass_tag の物。在れば）と今の周の brief の
    ファイル（planbrief.files）。brief の控えが壊れていれば盤面を止めて理由の BoardGap（fix-prep と同じ。reads.main_for が 1 行で
    2 にする）"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    p = prompt_path(b, pass_tag)
    try:
        briefs = planbrief.files(b)
    except planbrief.LedgerBroken as e:
        raise BoardGap(brief_halt(b, e)) from None
    return ([str(p)] if p.is_file() else []) + briefs
