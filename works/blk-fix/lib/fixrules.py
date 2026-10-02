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
  修正の形 g1 では、借りたスキルの座の代わりに下請けを回す節（seat.g1_section。項目ごとのファイルは g1_values）を載せる。
  どちらも指示書の頭（題の次）に、直す義務の単位の brief（planbrief.cut。承認済みの修正案の項目を凍結した物）を名指す節を置く。
  brief の控えが壊れていれば盤面を止める（brief_halt。brief の無い指示書として続けない）
- ruler_prompt: 裁定役の指示書（ruling.prep が書く）
- reads_more: 節 fix-reads が読んだ証拠を集めるパスに足す物（今の周に組んだ指示書と brief のファイル）
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
import fixshape  # noqa: E402
from leftovers import Unreadable, git_names  # noqa: E402
import libdocs  # noqa: E402
import planbrief  # noqa: E402  （同じブロックの lib。承認済みの修正案の項目ごとの brief の凍結）
import recount  # noqa: E402
import rolekit  # noqa: E402
import rulebook  # noqa: E402
from rulebook import EMPTY, MARK, RULES_SAME, WHY_DELTA, Unfilled, fill, join, render, shared  # noqa: E402,F401
import script_io  # noqa: E402
import seat as seatkit  # noqa: E402  （借りたスキルの座。引数の名 seat と分ける）
import writes  # noqa: E402  （修正前の版。g1 の審査役の型の [BASE_SHA]）
import adapter  # noqa: E402  （L2。run ごとの置き場 run_place_of。g1 の審査役の差分のファイルの置き場）
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
REJECT_GLOB = f"{script_io.REJECT_PREFIX}accept_fix-*.txt"
# 並べて書く形の名の尾（<名>.md の隣）
FULL, DELTA, RULES, VARIANTS, DELIVERED = ".full.md", ".delta.md", ".rules.md", ".variants.json", ".delivered.json"
WHY_FIRST = "1 回目（この輪でまだ決まりを渡していない。delta は full と同じ）"
SEAT_BRIEFS = "seat-briefs.md"   # 修正役の座の型の [BRIEF_FILE]（今の周の作業ファイル。直す義務の単位の brief を名指す節）
G1_IMPL, G1_REVIEW = "g1-impl-{n}.md", "g1-review-{n}.md"   # 修正の形 g1 の下請けのファイル（今の周の作業ファイル。n は項目の番号）
G1_PATCH_FILE = "g1-{n}.patch"   # g1 の審査役の差分のファイル（run ごとの置き場 adapter.run_place_of。修正役が seat.G1_PATCH で書く）
G1_NO_POLICY = "（無し）"   # g1 の審査役の型の [GLOBAL_CONSTRAINTS]（人の方針の文書が無い run）
G1_REST = "修正案のどの項目にも無い直す義務の単位 {keys}（判定のファイルが要求の正本）"   # g1 の残りの項目の実装役の型の題
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


def _seat(seat: str, shape: str = seatkit.SHAPE) -> list:
    """座の節（seat.section か seat.g1_section の文。空なら載せない）。理由の文は形を名指す"""
    return [("seat", seat, ALWAYS + f"（修正の形 {shape} の座）")] if seat else []


def fix_parts(values: dict, kinds: dict | None = None, libdocs: str = "", seat: str = "", shape: str = seatkit.SHAPE) -> list:
    """直す役の決まりの節 [(id, 本文, 理由)]（順は指示書の順）。libdocs はライブラリの今の文書の節（libdocs.section。空なら載せない）。
    seat は座（g3 は seat.section・g1 は seat.g1_section。空なら載せない）で、返答の欄の直前に置く。shape は座の形（理由の文）"""
    c, d = sections(SHARED), sections(DIRECT)
    kinds = _all_kinds() if kinds is None else kinds
    return [("fix-head", fill(d["fix-head"], _pick(values, FIX_VALUES)), ALWAYS + "（役・読む物・run の値）"),
            ("brief-canon", sections(BRIEF)["brief-canon"], ALWAYS + BRIEF_WHY),
            ("core-fix", c["core-fix"], ALWAYS + "（本線の核）"), *_evidence(c, kinds),
            ("core-conflict", c["core-conflict"], ALWAYS + CONFLICT_WHY), ("core-keep", c["core-keep"], ALWAYS + "（本線の核）"),
            ("fix-keep", d["fix-keep"], ALWAYS + "（直す役）"),
            *([("libdocs", libdocs, "機械が引いた（Context7。見つけた数と取れた数は節の頭）")] if libdocs else []),
            *_seat(seat, shape), ("fix-reply", d["fix-reply"], ALWAYS + "（返答の欄）")]


def tdd_parts(values: dict, kinds: dict | None = None, seat: str = "") -> list:
    """TDD の輪の役の決まりの節（段によらない物）。seat は借りたスキルの座（空なら載せない）で、この輪での読み替えの後に置く"""
    c, t = sections(SHARED), sections(TDD)
    kinds = _all_kinds() if kinds is None else kinds
    return [("tdd-head", fill(t["tdd-head"], _pick(values, TDD_VALUES)), ALWAYS + "（役・読む物・run の値）"),
            ("brief-canon", sections(BRIEF)["brief-canon"], ALWAYS + BRIEF_WHY),
            ("core-fix", c["core-fix"], ALWAYS + "（本線の核）"), *_evidence(c, kinds),
            ("core-conflict", c["core-conflict"], ALWAYS + CONFLICT_WHY), ("core-keep", c["core-keep"], ALWAYS + "（本線の核）"),
            ("tdd-remap", t["tdd-remap"], ALWAYS + "（この輪での読み替え）"), *_seat(seat)]


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
               rules_file: str = "", libdocs: str = "", seat: str = "") -> str:
    """直す役の指示書の 1 つの形（純粋）"""
    return render("fix", iteration, fix_parts(values, kinds, libdocs, seat), prior=prior, rules_file=rules_file,
                  reject_file=reject_file)["text"]


def tdd_prompt(values: dict, phase: str, phase_text: str, *, title: str, reason: str = "", kinds: dict | None = None,
               prior=None, iteration: int = 1, rules_file: str = "", brief: str = "", seat: str = "") -> str:
    """TDD の輪の役の指示書の 1 つの形（純粋）"""
    return tdd_render(values, phase, phase_text, title=title, reason=reason, kinds=kinds, prior=prior, iteration=iteration,
                      rules_file=rules_file, brief=brief, seat=seat)["text"]


def tdd_render(values, phase, phase_text, *, title, reason="", kinds=None, prior=None, iteration=1, rules_file="",
               lang="", brief="", seat="") -> dict:
    """tdd_prompt の形 {text, delivered, rules_text, head}。並び: 題 → [brief の節（planbrief.head_text）] → [拒んだ理由] → 決まり
    → 今の段の約束 → 今の段（tddloop が書く）→ 結び → [言語の 1 行（lang_at）]"""
    before = [title, *([brief] if brief else [])]
    if reason:
        before.append("## 前の回の返答を機械が拒んだ理由（直して、この段の返答を丸ごと出し直せ）\n\n" + reason.rstrip("\n"))
    after = [tdd_phase_rules(phase), phase_text.rstrip("\n"), sections(TDD)["tdd-end"]]
    return render("tdd", iteration, tdd_parts(values, kinds, seat), prior=prior, rules_file=rules_file, before=before, after=after,
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


def prompt_path(b) -> pathlib.Path:
    return b.work(rolekit.prompt_name(recount.FIX_NODE))


def last_reject(board_dir) -> str:
    """受け付けが書いた一番新しい拒否の理由のファイル（無ければ空）"""
    def n(p):
        tail = p.stem.rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else -1
    got = sorted(pathlib.Path(board_dir).glob(REJECT_GLOB), key=n)
    return str(got[-1]) if got else ""


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


def implementer_values(b, values: dict, repo, owed: list[str]) -> dict[str, str]:
    """修正役の座（216 の節 implementer の型）の 5 つの穴の値。owed は今直す単位の key。直す義務の単位の brief を名指す節
    （planbrief.head_text）を今の周の作業ファイル SEAT_BRIEFS に書いて [BRIEF_FILE] にする（brief の無い run は判定のファイル）。
    brief の控えが壊れていれば盤面を止めて BoardGap（briefs_or_halt）"""
    briefs = planbrief.for_units(briefs_or_halt(b), owed)
    head = planbrief.head_text(briefs, owed)
    brief_file = values.get("judgment_file") or ""
    if head:
        path = b.work(SEAT_BRIEFS)
        path.write_text(head + "\n", encoding="utf-8")
        brief_file = str(path)
    items = "、".join(str(r["item"]) for r in briefs)
    summary = values.get("summary_file") or ""
    return {"[task name]": f"直す義務の単位 {len(owed)} 件" + (f"（修正案の項目 {items}）" if items else ""),
            "[BRIEF_FILE]": brief_file,
            "[Scene-setting: where this fits, dependencies, architectural context]":
                seatkit.SCENE + (f"。輪の要約のファイル: {summary}" if summary else ""),
            "[directory]": "" if repo is None else str(repo),
            "[REPORT_FILE]": seatkit.NO_REPORT_FILE}


def g1_values(b, values: dict, repo, owed: list[str], base_rev: str) -> list[dict]:
    """修正の形 g1 の下請けのファイルを、直す義務の単位の brief の項目ごとに今の周に 2 つ書き、項目の順の
    [{item, impl_file, review_file, base, patch}] を返す（seat.g1_section が並べる）。どの項目にも無い直す義務の単位（brief の無い run は
    全部）は、判定のファイルを [BRIEF_FILE] にした残りの 1 項目（番号は修正案の項目の後。題は G1_REST、brief の無い run は
    implementer_values の題）。
    - G1_IMPL: 216 の implementer の型。[BRIEF_FILE] はその項目の brief、[task name] はその項目の直す義務の単位、[REPORT_FILE] は
      seat.G1_IMPL_REPORT（下請けには返答の欄が無い）、ほかは implementer_values と同じ
    - G1_REVIEW: 216 の task-review の型。[BRIEF_FILE] は同じ brief、[GLOBAL_CONSTRAINTS] は人の方針の文書のパスか G1_NO_POLICY、
      [REPORT_FILE] は seat.G1_REPORT、[BASE_SHA] は修正前の版（writes.base_rev）、[HEAD_SHA] は seat.G1_HEAD_SHA（型の
      `git diff <版>..<HEAD_SHA>` は seat.g1_prompt が作業ツリーとの差分 `git diff <版>` に直す。Preflight F20）、[DIFF_FILE] は
      run ごとの置き場（盤面の隣。adapter.run_place_of。盤面は守る場所で役の Bash が書けない）の G1_PATCH_FILE の絶対パス
    どちらも seat.g1_prompt（型の後ろに下請けへの works の決まりと検索語の規律の塊）。写しが固定と違う・穴が埋まらなければ ValueError"""
    common = implementer_values(b, values, repo, owed)
    cut = briefs_or_halt(b)
    briefs = planbrief.for_units(cut, owed)
    items = [(r["item"], r["file"], _g1_task(r, owed)) for r in briefs]
    covered = {k for r in briefs for k in r.get("unit_keys") or []}
    rest = [k for k in owed if k not in covered]
    if rest:   # どの項目にも無い直す義務の単位（brief の無い run は全部）: 判定のファイルを brief にした残りの 1 項目
        n = max((r["item"] for r in cut), default=0) + 1
        items.append((n, values.get("judgment_file") or "", G1_REST.format(keys="、".join(rest)) if briefs else common["[task name]"]))
    base = writes.base_rev(b, base_rev)
    place = pathlib.Path(adapter.run_place_of({"board": str(b.dir)}))   # 盤面は守る場所で役の Bash が書けない。run ごとの置き場
    rows = []
    for n, brief, task in items:
        impl, review = b.work(G1_IMPL.format(n=n)), b.work(G1_REVIEW.format(n=n))
        patch = str(place / G1_PATCH_FILE.format(n=n))
        impl.write_text(seatkit.g1_prompt("implementer", {**common, "[task name]": task, "[BRIEF_FILE]": brief,
                                                           "[REPORT_FILE]": seatkit.G1_IMPL_REPORT}), encoding="utf-8")
        review.write_text(seatkit.g1_prompt("task-review", {
            "[BRIEF_FILE]": brief, "[GLOBAL_CONSTRAINTS]": values.get("policy_path") or G1_NO_POLICY,
            "[REPORT_FILE]": seatkit.G1_REPORT, "[BASE_SHA]": base, "[HEAD_SHA]": seatkit.G1_HEAD_SHA,
            "[DIFF_FILE]": patch}), encoding="utf-8")
        rows.append({"item": n, "impl_file": str(impl), "review_file": str(review), "base": base, "patch": patch})
    return rows


def _g1_task(brief: dict, owed: list[str]) -> str:
    """g1 の実装役の型の [task name]: 修正案の項目の番号と、その項目のうち今直す単位（ほかの単位は『今は直すな』）"""
    return f"修正案の項目 {brief['item']}（直す義務の単位 {planbrief.unit_note(brief.get('unit_keys'), owed)}）"


def prep(board_dir, repo, values: dict, pass_: str = PASSES[0]) -> dict:
    """節 fix-prep（pass_ first）と fix-ruled-prep（pass_ ruled）: 2 つの形を書き（prompt_file は full の写し）、起こした印を置く。
    返り {prompt_file, attempt, out_path, node, already, variants_file, iteration}（iteration はこの輪の何回目か。受け付けが
    3 回目の拒否で done を立てる。R50）。同じ試行の出し直し（印が既に在る。通れば輪を抜けるので、前の回の返答は受け付けで
    拒まれた）なら、受け付けが書いた一番新しい拒否の理由のファイルを見出しの次の 1 行で名指す（R44）。
    ruled は指示書を <名>-ruled.md に分け（輪の回を別に数える）、1 回目は裁定の文のファイル（conflict.RULINGS_FILE）を見出しの
    次の 1 行で名指す（裁定の文は貼らない。R44）。盤面が p3.fix を待っていなければ BoardGap。
    full と delta の頭（題の次。ruled の 1 回目は裁定の文のファイルの行の後）に、直す義務の単位の brief を名指す節
    （planbrief.head_text。義務から外れた単位には「今は直すな」）を置く（1 回目も ruled も同じ凍結の中身）。
    brief の控えが壊れていれば盤面を止めて BoardGap（briefs_or_halt。指示書を書かず、起こした印も置かない）。
    修正の形（fixshape.shape_at）が座を載せる形なら、借りたスキルの座（seat.section。型の穴は implementer_values）を full と delta の
    両方に載せる。形が g1 なら、その代わりに下請けを回す節（seat.g1_section。下請けのファイルは g1_values。[BASE_SHA] は
    values の base_rev）を載せる。写しが固定と違う・穴が埋まらなければ ValueError のまま上げる（指示書を書かず、起こした印も
    置かない。支度の script は 2 で落ちる）"""
    if pass_ not in PASSES:
        raise Unfilled(f"pass {pass_!r} は {PASSES} のどれでもない")
    nid = recount.FIX_NODE
    b = entry.open_board(pathlib.Path(board_dir))
    inst = b.rd["instances"].get(nid)
    if not inst or inst.get("status") != "pending":
        raise BoardGap(f"この周に節 {nid} の待っている instance が無い（修正役を起こす番でない）")
    briefs = briefs_or_halt(b)   # 開いたばかりの盤面で（裁定の文を書く・起こした印を置くより前に）凍結する
    path = prompt_path(b)
    before = ()
    if pass_ == "ruled":
        path = path.with_name(path.name[:-len(".md")] + RULED_TAIL)
    n = iteration_next(path)
    reject = last_reject(board_dir) if inst.get("launched_at") else ""
    if pass_ == "ruled" and n == 1:
        rulings = b.work(conflict.RULINGS_FILE)
        if not rulings.is_file():
            rulings = conflict.write_rulings(b)
        reject, before = "", (RULINGS_LINE.format(path=rulings),)
    values = owed_values(b, values)
    owed = json.loads(values["open_units"])
    head = planbrief.head_text(planbrief.for_units(briefs, owed), owed)
    before = tuple(x for x in (*before, head) if x)   # ruled の裁定の文の行は見出しの次の 1 行のまま（R44）。brief はその後
    mark, shape = ("fix" if pass_ == PASSES[0] else "fix-ruled"), fixshape.shape_at(board_dir)
    seat = ""
    if shape == seatkit.G1_SHAPE and mark in fixshape.AGENT_NODES:
        seatkit.pinned()   # 写しの照合を、下請けのファイルの書き込みと Context7 の引き（lib_section）より前に
        seat = seatkit.g1_section(g1_values(b, values, repo, owed, values.get("base_rev") or ""))
    elif seatkit.carries(mark, shape):
        seatkit.pinned()   # 写しの照合を、座の作業ファイルの書き込みと Context7 の引き（lib_section）より前に
        seat = seatkit.section(mark, shape, implementer_values(b, values, repo, owed))
    docs = lib_section(b, repo, values)
    lang = rolekit.lang_line(b.state.get("inputs"))

    def build(kinds, prior, rules_file):
        return render("fix", n, fix_parts(values, kinds, docs, seat, shape), prior=prior, rules_file=rules_file, reject_file=reject,
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


def reads_more(board_dir) -> list:
    """節 fix-reads が読んだ証拠を集めるパスに足す物: 今の周に組んだ指示書（在れば）と今の周の brief のファイル（planbrief.files）。
    brief の控えが壊れていれば盤面を止めて理由の BoardGap（fix-prep と同じ。reads.main_for が 1 行で 2 にする）"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    p = prompt_path(b)
    try:
        briefs = planbrief.files(b)
    except planbrief.LedgerBroken as e:
        raise BoardGap(brief_halt(b, e)) from None
    return ([str(p)] if p.is_file() else []) + briefs
