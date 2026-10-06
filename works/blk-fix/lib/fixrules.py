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
  修正の形 g1 と既定の g3 では、借りたスキルの座の代わりに下請けを回す節（seat.g1_section。項目ごとのファイルは g1_values。
  下請けを起こす単位は dispatched: g3 は TDD の輪が緑にした単位を除く。依頼 243 の 2）を載せる。
  g3 の 1 回目の周（side_on）は、範囲（item_ranges）が重ならない項目に単位の worktree を切り（unitlanes）、修正役がその
  下請けを同時に起こして機械の当てるコマンド（merge_line）で作業ツリーへ当てる（依頼 243 の並べ）。
  どちらも指示書の頭（題の次）に、直す義務の単位の brief（planbrief.cut。承認済みの修正案の項目を凍結した物）を名指す節を置く。
  brief の控えが壊れていれば盤面を止める（brief_halt。brief の無い指示書として続けない）
- ruler_prompt: 裁定役の指示書（ruling.prep が書く）
- reads_more: 節 fix-reads が読んだ証拠を集めるパスに足す物（今の周に組んだ指示書と brief のファイル）
- 同じ周に修正役を 2 度起こす段（依頼 226 の 2 回目の修正の段。ブロックの 2 度目の include）の指示書（と隣の .full.md・.delta.md・
  .variants.json・.delivered.json・.rules.md）・裁定の後の尾・拒否の理由・裁定の文・申し出の回の控えは、名を変えずに include の
  名の置き場（scope。盤面の work と script_io.scope_dir）で 1 回目の物と分かれる。2 回目の段は自分の数えから始まり、3 回の諦めを
  回ごとに数え、最初の指示書は新しい役が見ていない会話への差分（delta）にならない
- 1 回目の修正の段で受け付けた返答の控え（conflict.held_reply）が在る時だけ、修正役の指示書の brief の節の後に HELD_HEAD の節
  （HELD_ASK）を置く（2 回目の修正の段）
"""
import json
import os
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
import askplan  # noqa: E402  （同じブロックの lib。範囲の相談の控えと置き場）
import libdocs  # noqa: E402
import planbrief  # noqa: E402  （同じブロックの lib。承認済みの修正案の項目ごとの brief の凍結）
import planmarks  # noqa: E402  （項目の範囲: allowed_paths と受け入れのテストのファイル。並べる項目の分け方）
import unitlanes  # noqa: E402  （同じブロックの lib。範囲の重ならない項目の単位の worktree。依頼 243 の並べ）
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
HELD_HEAD = "## 1 回目の修正の段で受け付けた返答（機械が貼った）"
HELD_ASK = ("控え {path} を Read で読め。直す義務は上の「読む物」の「直す義務の単位の key」（案を直して戻った単位）だけで、"
            "控えの単位の行は機械が足す——changes と not_done に控えの単位を書くな。changes と not_done の外の欄（fix_closure・mechanism_changed・"
            "plan_faces など）は、1 回目と今回を合わせた差分の全体について書け（控えの値から始めよ）。")
HELD_WHY = "1 回目の修正の段で受け付けた返答の控えが在る（2 回目の修正の段）"
KINDS = ("docs", "prompts", "config", "code")   # 変更の種類 → 節 evidence-<種類>
PHASES = ("route", "test", "fix", "refactor", "lanes")   # lanes は並べの周のまとめ役（tddlanes）
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
SEAT_BRIEFS = "seat-briefs.md"   # 修正役の座の型の [BRIEF_FILE]（今の周の作業ファイル。直す義務の単位の brief を名指す節）
G1_IMPL, G1_REVIEW = "g1-impl-{n}.md", "g1-review-{n}.md"   # 修正の形 g1 の下請けのファイル（今の周の作業ファイル。n は項目の番号）
UNITS_FILE = "units.json"   # 並べる項目の単位の worktree の控え（今の周の作業ファイル。unitlanes.plant が書き、締める節が読む）
UNITS_KEPT = "units-kept"    # 当たらなかった並べる項目の差分の置き場（今の周の作業ファイルのフォルダ。締める節 fix-units が書く）
UNITS_OP = "units_settled"   # 締める節が盤面の trace に残す行 {applied, machine, conflict, unmerged, carried}
UNITS_DIR = "units"          # 単位の worktree の置き場（run ごとの置き場の今の scope の下。包みが下請けに書かせる所）
G1_PATCH_FILE = "g1-{n}.patch"   # g1 の審査役の差分のファイル（run ごとの置き場 adapter.run_place_of。修正役が seat.G1_PATCH で書く）
G1_NO_POLICY = seatkit.NONE   # g1 の審査役の型の [GLOBAL_CONSTRAINTS]（人の方針の文書が無い run）
G1_REST = "修正案のどの項目にも無い直す義務の単位 {keys}（判定のファイルが要求の正本）"   # g1 の残りの項目の実装役の型の題
BRIEF_STOP_BY = "works:fix"   # brief の控えが壊れた盤面を止めた口（assert-changed の STOP_BY と同じ修正の段の印）
BRIEF_BROKEN = (f"修正案の brief の控え（今の周の {planbrief.LEDGER}）か欄の控え（盤面の {planbrief.planmarks.FIELDS_FILE}）が壊れているか"
                "凍結の後に書き換えられ、承認した要求の正本が"
                "引けない——brief の無い指示書で役を起こさずに盤面を止める")
FACTCHECKS = pathlib.Path(__file__).resolve().parent / "factchecks.py"   # 事前の確かめのコマンド（import しない: factchecks → tddloop → fixrules の輪）
ASK_DRAFT = "draft-reply.json"   # 修正役が事前の確かめに渡す返答の下書き（相談の置き場。作業ツリーの外）
ASK_WHY = "範囲の相談の控えが在る（相談の相手の会話の印の名 plan_session と承認済みの修正案の項目が在る run）"
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


def _seat(seat: str, shape: str = seatkit.SHAPE) -> list:
    """座の節（seat.section か seat.g1_section の文。空なら載せない）。理由の文は形を名指す"""
    return [("seat", seat, ALWAYS + f"（修正の形 {shape} の座）")] if seat else []


def fix_parts(values: dict, kinds: dict | None = None, libdocs: str = "", seat: str = "", shape: str = seatkit.SHAPE,
              held: str = "", ask: str = "") -> list:
    """直す役の決まりの節 [(id, 本文, 理由)]（順は指示書の順）。libdocs はライブラリの今の文書の節（libdocs.section。空なら載せない）。
    seat は座（g3 は seat.section・g1 は seat.g1_section。空なら載せない）で、返答の欄の直前に置く。shape は座の形（理由の文）。
    held は 1 回目に受け付けた返答の控えの節（held_text。空なら載せない）で、brief の節の後に置く。
    ask は範囲の相談と事前の確かめの節（ask_text。空なら載せない）で、守ることの後に置く"""
    c, d = sections(SHARED), sections(DIRECT)
    kinds = _all_kinds() if kinds is None else kinds
    return [("fix-head", fill(d["fix-head"], _pick(values, FIX_VALUES)), ALWAYS + "（役・読む物・run の値）"),
            ("brief-canon", sections(BRIEF)["brief-canon"], ALWAYS + BRIEF_WHY),
            *([("held", held, HELD_WHY)] if held else []),
            ("core-fix", c["core-fix"], ALWAYS + "（本線の核）"), *_evidence(c, kinds),
            ("core-conflict", c["core-conflict"], ALWAYS + CONFLICT_WHY), ("core-keep", c["core-keep"], ALWAYS + "（本線の核）"),
            ("fix-keep", d["fix-keep"], ALWAYS + "（直す役）"),
            *([("ask", ask, ASK_WHY)] if ask else []),
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


LANE_PHASES = ("test", "fix", "refactor")   # 並べの周の単位の下請けが 1 つの会話で回す段


def tdd_lane_render(values, lane_text, *, title, brief="", seat="", lang="", kinds=None) -> str:
    """並べの周の単位の下請けのファイルの中身（純粋。いつも全文）。並び: 題 → [brief の節] → 決まり（TDD の輪の役と同じ節）→
    下請けの読み替え（tdd.md の節 tdd-lane）→ 3 段（LANE_PHASES）の約束 → この単位の決まり（tddlanes.unit_text）→ [言語の 1 行]"""
    t = sections(TDD)
    phases = join([t["tdd-phase"], *(t[f"tdd-phase-{p}"] for p in LANE_PHASES), t["tdd-phase-all"]])
    return render("tdd", 1, tdd_parts(values, kinds, seat), before=[title, *([brief] if brief else [])],
                  after=[t["tdd-lane"], phases, lane_text.rstrip("\n")], lang=lang)["text"]


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
    """修正役の指示書（今の scope の周の置き場）"""
    return b.work(rolekit.prompt_name(recount.FIX_NODE))


def last_reject(board_dir) -> str:
    """受け付けが今の scope の根に書いた一番新しい拒否の理由のファイル（無ければ空。ほかの scope の物は見ない。script_io.last_reject）"""
    return script_io.last_reject(board_dir, REJECT_FN)


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
    （planbrief.head_text）を今の周の作業ファイル SEAT_BRIEFS（今の scope の周の置き場）に書いて [BRIEF_FILE] にする
    （brief の無い run は判定のファイル）。brief の控えが壊れていれば盤面を止めて BoardGap（briefs_or_halt）"""
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


def item_ranges(b) -> dict:
    """修正案の項目の番号 → 範囲（allowed_paths の glob と受け入れのテストのファイル。planmarks.test_paths）。allowed_paths の欄の
    無い項目は None（範囲で縛らない古い案。並べない）。承認済みの項目が引けない・控えが壊れていれば {}（全部を順にする）"""
    try:
        items = planmarks.approved_items(b)
    except (planmarks.FieldsBroken, BoardGap, OSError, ValueError):
        return {}
    out = {}
    for it in items or []:
        if "allowed_paths" in it:
            out[it["item"]] = [g for g in it.get("allowed_paths") or [] if isinstance(g, str) and g] + planmarks.test_paths(it)
        else:
            out[it["item"]] = None
    return out


def ask_items(items) -> dict:
    """承認済みの修正案の項目 → 相談の控えの items（番号の文字列 → {unit_keys, allowed_paths, out_of_scope の glob, tests の
    ファイル（planmarks.test_paths）}）"""
    return {str(it["item"]): {"unit_keys": [k for k in it.get("unit_keys") or [] if isinstance(k, str)],
                              "allowed_paths": [g for g in it.get("allowed_paths") or [] if isinstance(g, str) and g],
                              "out_of_scope": [r["glob"] for r in it.get("out_of_scope") or []
                                               if isinstance(r, dict) and isinstance(r.get("glob"), str)],
                              "tests": planmarks.test_paths(it)}
            for it in items or []}


def ask_text(config, python: str) -> str:
    """範囲の相談と事前の確かめの節（rules/direct.md の節 fix-ask）を、控え config と実行ファイル python で埋めた文"""
    place = pathlib.Path(config).parent
    return fill(sections(DIRECT)["fix-ask"], {
        "ask_cmd": f"{python} {pathlib.Path(askplan.__file__).resolve()} {config}",
        "check_cmd": f"{python} {FACTCHECKS} {config}",
        "draft": str(place / ASK_DRAFT)})


def ask_config(b, repo, values: dict, pass_: str) -> str:
    """範囲の相談の控えを run ごとの置き場の今の scope の下に書き（askplan.write_config）、節の文（ask_text）を返す。入力
    plan_session（相談の相手の会話の印の名）が空・承認済みの修正案の項目が引けない run は書かずに空。会話の id の記録は包みの
    置き場（adapter.session_path。cwd は repo）、model・effort はその印の最後の起動の記録から。実行ファイルはこの節の
    python（uv が選んだ 3.10 以上。役の sandbox の python3 は 3.9 のことがある）。values の tdd_state は TDD の輪の状態の
    ファイル（支度の script が輪の要約の隣から引く。空は輪の無い run）"""
    node = (values.get("plan_session") or "").strip()
    if not node or repo is None:
        return ""
    try:
        items = planmarks.approved_items(b)
    except (planmarks.FieldsBroken, BoardGap, OSError, ValueError):
        items = None
    if not items:
        return ""
    launch = adapter.last_launch(repo, node) or {}
    doc = {"board": str(b.dir), "repo": str(repo), "scope": entry.peek_here(), "pass": pass_,
           "base_rev": values.get("base_rev") or "",
           "tdd_state": values.get("tdd_state") or "",
           "session_file": str(adapter.session_path(repo, node)),
           "config_dir": os.environ.get("CLAUDE_CONFIG_DIR") or str(pathlib.Path.home() / ".claude"),
           "claude": os.environ.get(adapter.ENV_REAL) or shutil.which("claude") or "claude",
           "model": launch.get("model"), "effort": launch.get("effort"), "items": ask_items(items)}
    path = askplan.write_config(askplan.place_of(b.dir), doc)
    return ask_text(path, sys.executable)


def g1_values(b, values: dict, repo, owed: list[str], base_rev: str, shape: str = seatkit.G1_SHAPE,
              side: bool = False, ask: str = "") -> list[dict]:
    """修正の形 g1 の下請けのファイルを、直す義務の単位の brief の項目ごとに今の周に 2 つ書き、項目の順の
    [{item, impl_file, review_file, base, patch}] を返す（seat.g1_section が並べる）。どの項目にも無い直す義務の単位（brief の無い run は
    全部）は、判定のファイルを [BRIEF_FILE] にした残りの 1 項目（番号は修正案の項目の後。題は G1_REST、brief の無い run は
    implementer_values の題）。
    - G1_IMPL: 216 の implementer の型。[BRIEF_FILE] はその項目の brief、[task name] はその項目の直す義務の単位、[REPORT_FILE] は
      seat.G1_IMPL_REPORT（下請けには返答の欄が無い）、ほかは implementer_values と同じ
    - G1_REVIEW: 216 の task-review の型。[BRIEF_FILE] は同じ brief、[GLOBAL_CONSTRAINTS] は人の方針の文書のパスか G1_NO_POLICY、
      [REPORT_FILE] は seat.G1_REPORT、[BASE_SHA] は修正前の版（writes.base_rev）、[HEAD_SHA] は seat.G1_HEAD_SHA（型の
      `git diff <版>..<HEAD_SHA>` は seat.g1_prompt が作業ツリーとの差分 `git diff <版>` に直す。Preflight F20）、[DIFF_FILE] は
      run ごとの置き場（盤面の隣。adapter.run_place_of。盤面は守る場所で役の Bash が書けない）の今の scope の下の G1_PATCH_FILE の絶対パス
    shape が g1 でない（依頼 243 の 2 の g3）なら、どの項目にも無い単位は 1 単位 1 項目（題は G1_REST でその単位だけを名指す。
    単位ごとに新しい会話の下請けにする）。g1 は前のとおり残りを 1 項目にまとめる（比べの腕を変えない）。
    どちらも seat.g1_prompt（型の後ろに下請けへの works の決まりと検索語の規律の塊。決まりの見出しは shape を名指す）。3 つのファイルは今の scope の下に置く
    （同じブロックの 2 度目の include は 1 度目の物を上書きしない）。写しが固定と違う・穴が埋まらなければ ValueError。
    side（依頼 243 の並べ。prep が g3 の 1 回目だけ立てる）なら、範囲（item_ranges。残りの項目は範囲なし）が互いに重ならない
    項目（unitlanes.lanes）に、run ごとの置き場の今の scope の下の UNITS_DIR へ単位の worktree を切り（unitlanes.plant。控えは今の
    周の作業ファイル UNITS_FILE）、その項目の行に tree を足す。その項目の下請けのファイルは [directory] と決まり（seat の tree）で
    worktree の中だけで働き、審査役の [BASE_SHA] は worktree の base（差分はその項目だけ）。
    ask（範囲の相談と事前の確かめの節。ask_text）が空でなければ、実装役のファイルの終わりに足す（下請けは修正役の指示書を読まない）"""
    common = implementer_values(b, values, repo, owed)
    cut = briefs_or_halt(b)
    briefs = planbrief.for_units(cut, owed)
    items = [(r["item"], r["file"], _g1_task(r, owed)) for r in briefs]
    covered = {k for r in briefs for k in r.get("unit_keys") or []}
    rest = [k for k in owed if k not in covered]
    n = max((r["item"] for r in cut), default=0) + 1
    if rest and shape != seatkit.G1_SHAPE:   # 1 単位 1 項目（判定のファイルを brief に）
        items += [(n + i, values.get("judgment_file") or "", G1_REST.format(keys=k)) for i, k in enumerate(rest)]
    elif rest:   # どの項目にも無い直す義務の単位（brief の無い run は全部）: 判定のファイルを brief にした残りの 1 項目
        items.append((n, values.get("judgment_file") or "", G1_REST.format(keys="、".join(rest)) if briefs else common["[task name]"]))
    base = writes.base_rev(b, base_rev)
    run_place = pathlib.Path(adapter.run_place_of({"board": str(b.dir)}))   # 盤面は守る場所で役の Bash が書けない。run ごとの置き場
    place = script_io.scope_dir(run_place)   # 同じブロックの 2 度目の include の差分は 1 度目の物を上書きしない（最上段なら置き場のまま）
    if place != run_place:
        place.mkdir(parents=True, exist_ok=True)   # 役の Bash の差分のコマンドはフォルダを作らない
    trees = {}
    if side and repo is not None:
        ranges = item_ranges(b)
        brief_items = {r["item"] for r in briefs}
        picked = unitlanes.lanes([(n, ranges.get(n) if n in brief_items else None) for n, _, _ in items])
        if picked:
            trees = unitlanes.plant(repo, picked, place / UNITS_DIR, b.work(UNITS_FILE))
    rows = []
    for n, brief, task in items:
        impl, review = b.work(G1_IMPL.format(n=n)), b.work(G1_REVIEW.format(n=n))
        patch = str(place / G1_PATCH_FILE.format(n=n))
        tree = trees.get(n, {}).get("tree")
        here = {"[directory]": tree} if tree else {}
        item_base = trees[n]["base"] if tree else base
        impl.write_text(seatkit.g1_prompt("implementer", {**common, **here, "[task name]": task, "[BRIEF_FILE]": brief,
                                                           "[REPORT_FILE]": seatkit.G1_IMPL_REPORT}, shape, tree)
                        + (f"\n\n{ask}\n" if ask else ""), encoding="utf-8")
        review.write_text(seatkit.g1_prompt("task-review", {
            "[BRIEF_FILE]": brief, "[GLOBAL_CONSTRAINTS]": values.get("policy_path") or G1_NO_POLICY,
            "[REPORT_FILE]": seatkit.G1_REPORT, "[BASE_SHA]": item_base, "[HEAD_SHA]": seatkit.G1_HEAD_SHA,
            "[DIFF_FILE]": patch}, shape, tree), encoding="utf-8")
        row = {"item": n, "impl_file": str(impl), "review_file": str(review), "base": item_base, "patch": patch}
        rows.append({**row, "tree": tree} if tree else row)
    return rows


def side_on(shape: str, pass_: str, iteration: int) -> bool:
    """範囲の重ならない項目を単位の worktree で並べるか（依頼 243 の並べ）: 既定の形 g3 の 1 回目の修正役（pass first）の、輪の
    1 回目の周だけ。出し直しと裁定の後は前の直しの在る作業ツリーで名指す項目だけを起こし直し、g1 は比べの腕なので順のまま"""
    return shape == seatkit.SHAPE and pass_ == PASSES[0] and iteration == 1


def merge_line(b, rows: list[dict]) -> str:
    """並べる項目（行に tree）が在れば、修正役が走らせる当てるコマンド（unitlanes.command。控えは今の周の UNITS_FILE）。無ければ空"""
    return unitlanes.command(b.work(UNITS_FILE)) if any(r.get("tree") for r in rows) else ""


def _g1_task(brief: dict, owed: list[str]) -> str:
    """g1 の実装役の型の [task name]: 修正案の項目の番号と、その項目のうち今直す単位（ほかの単位は『今は直すな』）"""
    return f"修正案の項目 {brief['item']}（直す義務の単位 {planbrief.unit_note(brief.get('unit_keys'), owed)}）"


def dispatched(shape: str, mark: str, owed: list[str], green=frozenset()) -> list[str]:
    """修正役 mark が下請けを起こす単位（owed の順）。下請けを起こす形（fixshape.AGENT_SHAPES）の修正役（AGENT_NODES）だけ。g1 は
    owed の全部、g3 は TDD の輪が緑にした単位 green（支度の script が tddloop.green_units で引く。tddloop が fixrules を import
    するので、ここでは引かない）を除いた物（依頼 243 の 2）。ほかは []"""
    if shape not in fixshape.AGENT_SHAPES or mark not in fixshape.AGENT_NODES:
        return []
    if shape == seatkit.G1_SHAPE:
        return list(owed)
    return [k for k in owed if k not in green]


def prep(board_dir, repo, values: dict, pass_: str = PASSES[0], green=frozenset()) -> dict:
    """節 fix-prep（pass_ first）と fix-ruled-prep（pass_ ruled）: 2 つの形を書き（prompt_file は full の写し）、起こした印を置く。
    返り {prompt_file, attempt, out_path, node, already, variants_file, iteration}（iteration はこの輪の何回目か。受け付けが
    3 回目の拒否で done を立てる。R50）。同じ試行の出し直し（印が既に在る。通れば輪を抜けるので、前の回の返答は受け付けで
    拒まれた）なら、受け付けが書いた一番新しい拒否の理由のファイルを見出しの次の 1 行で名指す（R44）。
    ruled は指示書を <名>-ruled.md に分け（輪の回を別に数える）、1 回目は裁定の文のファイル（conflict.RULINGS_FILE）を見出しの
    次の 1 行で名指す（裁定の文は貼らない。R44）。盤面が p3.fix を待っていなければ BoardGap。
    full と delta の頭（題の次。ruled の 1 回目は裁定の文のファイルの行の後）に、直す義務の単位の brief を名指す節
    （planbrief.head_text。義務から外れた単位には「今は直すな」）を置く（1 回目も ruled も同じ凍結の中身）。
    brief の控えが壊れていれば盤面を止めて BoardGap（briefs_or_halt。指示書を書かず、起こした印も置かない）。
    同じブロックの 2 度目の include（依頼 226 の 2 回目の修正の段）の指示書・裁定の後の尾・拒否の理由・裁定の文・座の作業ファイルは
    その scope の根に書き、数えと拒否の名指しはその scope の物だけを見る（起こした印は 1 回目の段が置いた物のまま）。1 回目に受け付けた返答の控え
    （conflict.held_reply）が在れば、brief の節の後に控えの節（held_text）を置く。
    green は TDD の輪が緑にした単位（dispatched）。
    修正の形（fixshape.shape_at）が座を載せる形なら、借りたスキルの座（seat.section。型の穴は implementer_values）を full と delta の
    両方に載せる。修正役が下請けを起こす単位（dispatched。g1 は全部、g3 は輪が緑にした単位の外）が在れば、その代わりに下請けを
    回す節（seat.g1_section。下請けのファイルは g1_values。[BASE_SHA] は values の base_rev）を載せる（依頼 243 の 2: g3 も単位
    ごとに新しい会話。g3 で輪が全部を緑にした周は前の座のまま）。g3 の 1 回目の周（side_on）は範囲の重ならない項目に単位の
    worktree を切り、節に当てるコマンド（merge_line）を載せる（依頼 243 の並べ）。写しが固定と違う・穴が埋まらなければ ValueError のまま上げる（指示書を書かず、起こした印も
    置かない。支度の script は 2 で落ちる）"""
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
    path = b.work(name)
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
    ask = ask_config(b, repo, values, pass_)
    subs = dispatched(shape, mark, owed, green)
    if subs:
        seatkit.pinned()   # 写しの照合を、下請けのファイルの書き込みと Context7 の引き（lib_section）より前に
        rows = g1_values(b, values, repo, subs, values.get("base_rev") or "", shape, side_on(shape, pass_, n), ask=ask)
        seat = seatkit.g1_section(rows, shape, merge_line(b, rows))
    elif seatkit.carries(mark, shape):
        seatkit.pinned()   # 写しの照合を、座の作業ファイルの書き込みと Context7 の引き（lib_section）より前に
        seat = seatkit.section(mark, shape, implementer_values(b, values, repo, owed))
    docs = lib_section(b, repo, values)
    lang = rolekit.lang_line(b.state.get("inputs"))
    held, held_path = conflict.held_reply(b)
    held = held_text(held_path if held is not None else "")

    def build(kinds, prior, rules_file):
        return render("fix", n, fix_parts(values, kinds, docs, seat, shape, held, ask), prior=prior, rules_file=rules_file,
                      reject_file=reject, before=before, lang=lang)
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
    """節 fix-reads が読んだ証拠を集めるパスに足す物: 今の scope の周に組んだ指示書（在れば）と今の周の brief の
    ファイル（planbrief.files）。brief の控えが壊れていれば盤面を止めて理由の BoardGap（fix-prep と同じ。reads.main_for が 1 行で
    2 にする）"""
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    p = prompt_path(b)
    try:
        briefs = planbrief.files(b)
    except planbrief.LedgerBroken as e:
        raise BoardGap(brief_halt(b, e)) from None
    return ([str(p)] if p.is_file() else []) + briefs
