"""修正の前に作る独立設計（写しの graph の節 r2.design）の先行。役を起こす支度・受け付け・控え・盤面への渡しを 1 か所に置く。
Archon を知らない関数だけを出す。

写しの graph の r2.design は deps に p4.assemble を持つので、盤面では修正と最後のテストの後にしか待たない。周を重ねない線では、
そこで出た作り直しの要否（R2 の redesign-needed）を拾う周が無い。graph は写しのまま（graph_sha を固めた手本と実物の盤面が
それに乗る）にして、設計の役だけを修正の前に先に起こし、受け付けた返答を盤面の根の design.json に控える。盤面が r2.design を
待った時（p4.assemble の後）に、線がその控えを渡す（目的の文の purpose.json と同じ形）。設計の役の入力は目的の文と実測した
制約・人の方針・人の関所の答え・依頼が名指した設計書の節なので、先に起こしても独立は崩れない（修正案・差分を読む口が無い）。

- unusable(b):   目的の出典が R2 に使えない理由（目的不明・狭めている。無ければ None）。式は写しの rules の purpose_unusable
                 （p4.assemble と同じ 1 本）を呼ぶ
- due(b):        設計の役を今起こすか（表に役として在り・控えが無く・諦めていず・盤面で済んでいず・再発火の周で・目的が使える）と理由
- snap:          起こす前の作業ツリーの写し（今の周の design-snapshot.json）。起こさないなら写しを置かずに go: false
- prep:          r2.design の指示書を engine と同じ描き方で描き（節はまだ待っていない。rolekit.render_body の ahead）、役の定義を
                 頭に置く。人が決めた前提（premises）と前の拒否の文は頭に貼る（役は道具を持たないのでファイルを読めない）。
                 貼った入力の控えを盤面の根の design-premises.json に書く
- premises:      R2 の 2 つの役（r2.design・r2.compare）に共通して貼る節の並び（人の答え → 名指しの節 → 地図）と、貼った入力の控え {given, withheld, seen}（kind は PREMISE_KINDS の中だけ）。
                 human_answers（人の関所の答え。asked は写さず、answer の無い機械の行は withheld。seen は貼った答えの数と
                 最後の round の印で、突き合わせの側が独立設計の後に来た答えを分けて並べる）と named_sections（依頼が
                 名指した設計書の節の本文。文書の拡張子（impact.DOC_EXT）のパスのリンク・`<path>#<見出し>`・`<path>` N 節と、
                 パスの無い <名前> N 節・<名前> の「見出し」（追跡の文書の名で引く）・パスの無い N 節（依頼が名指した設計書が
                 ただ 1 本の時だけそれに結び付ける）の名指しを、固めた版 HEAD のファイルから、当たった行の形（行頭の記号の並び・
                 次の行の下線・上線と下線。.md・.markdown は囲いの外の # の見出し）で切る。貼る見出しに出どころのパス:行を添える。引けなかった・結び付けられなかった名指しは理由の
                 1 行で withheld。1 節は engine が役に貼る本文の上限 FILE_CAP バイトまで。超えた残りは行の範囲で withheld）と
                 repo_map（対象のリポジトリの根の MAP_NAMES を地図として毎回貼る。無ければ「地図なし」の 1 行と withheld）
- claims_unpassed: R2 の返答のうち『渡されていない』『渡っていない』と書いた文（独立の目の出口が控えと並べる）
- anchors・anchor_misses・anchor_note: 問いが立たない根拠の文の名指し（パス:行。拡張子が ANCHOR_EXT の物）を拾い、固めた版で検算し、
                 無ければ名指しなしと添える
- accept:        返答を型（写しの schema）と作業ツリーの比べと根拠の名指しの検算に通し、通れば design.json。拒否は盤面の根の控えに積み、
                 GIVE_UP_AFTER 回目で done（輪を抜ける。諦めても線は止めない——事前審査は設計なしで進み、最後の R2 が言う）
- read_design:   design.json（無ければ None。壊れていれば Reject）。made は (中身 か None, 壊れている理由) で拒まない
- missing(b):    設計が無い理由の 1 文（諦めた・目的が使えない・控えが無い）。事前審査の指示書と独立の目の出口が使う
- hand(b, …):    盤面が r2.design を待っていて控えが在れば渡す（渡しの手順は line_edge と同じ entry.hand の 1 か所）
"""
import pathlib
import re
import subprocess
import sys
import urllib.parse

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように（必ず import より前）

_CORE = pathlib.Path(__file__).resolve().parent
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from board import BoardGap, pending_instance  # noqa: E402  （board が写しの engine を sys.path に足す。engine より先に）
from engine.render import FILE_CAP, cap_bytes  # noqa: E402
from engine.util import Reject, safe_name  # noqa: E402
import accept  # noqa: E402
import entry  # noqa: E402
import impact  # noqa: E402
import promptsection  # noqa: E402
import rolekit  # noqa: E402

NODE = "r2.design"
DESIGN_FILE = "design.json"             # 受け付けた設計の返答（盤面の根。run に 1 つ）
SNAPSHOT_NAME = "design-snapshot.json"  # 役を起こす前の作業ツリー（今の周の作業ファイル）
PROMPT_NAME = f"prompt-{safe_name(NODE)}.md"
GIVE_UP_AFTER = rolekit.GIVE_UP_AFTER
MISSING = "独立設計が取れなかった"
REJECT_HEADING = rolekit.REJECT_HEADING
UNUSABLE = {"目的不明": "目的の出典が取れない（目的不明）——独立設計を回さない",
            "狭めている": "目的の文を監査が『狭めている』と判定した——狭められた目的で独立設計を回さない"}
HANDED_OP = "r2_design_handed"          # 控えを盤面へ渡した trace の行
MISSING_OP = "r2_design_missing"        # 設計が無いまま先へ進んだ trace の行
HUMAN_HEAD = promptsection.Section("### 人の関所の答え", source="fn:design.human_answers")
HUMAN_ASK = ("人が関所で答えた前提（run の中で人が決めた物）。ほかの節より先に読め。答えが目的の文や前の要求を取り下げ・変えていれば、"
             "取り下げ・変えた後の要求を前提にせよ（取り下げた要求を固定の契約にしない）。設計が取り下げた要求を置いていても、"
             "そのことだけでは差にも前提の崩れにも数えず、答えに照らした目的で突き合わせよ。")
DESIGN_PREMISE_HEAD = promptsection.Section("## 人が決めた前提（機械が貼った）", source="fn:design.prep")
# 写しの指示書は 1 バイトも変えない（gl-prompts/COPIED_FROM）ので、入力を言う写しの文をこの節で読み替える
DESIGN_PREMISE_REREAD = ("下の指示書の「渡すのは元の目的と実測した制約だけである」は、この run では、この節（人の関所の答え・"
                         "依頼が名指した設計書の節・対象のリポジトリの地図）も渡していると読み替えよ。")
NAMED_HEAD = promptsection.Section("### 依頼が名指した設計書の節", source="fn:design.named_sections")
NAMED_ASK = "依頼が名指した設計書の節の本文（依頼を固めた版のファイルから機械が抜いた）。目的の文と同じく依頼の一部として読め。"
CODE_SPAN_ANCHOR = re.compile(r"`([^`\s]+\.[A-Za-z0-9]+#[^`\s]+)`")
# 持ち主の地の文の名指し: 「`<path>` 3 節」「`<path>` の §3」（見出しの頭の番号で引く。パスは拡張子つき）
CODE_SPAN_NUM = re.compile(r"`([^`\s#]+\.[A-Za-z0-9]+)`\s*(?:の\s*)?(?:§\s*(\d+(?:\.\d+)*)|(\d+(?:\.\d+)*)\s*節)")
# パスの無い名前の名指し: 「<名前> 3 節」「<名前> の §3」「<名前> の「<見出し>」」。名前は ASCII の英数字で始まる [\w.-] の並びで、前が
# ASCII の英数字・/・.・- でない（パスの途中を拾わない。仮名・漢字は頭にも前にも数えないので、日本語の地の文に続けて書いた名前
# 「詳しくはstructure-design 2 節」から地の文を名に混ぜない）。名前は追跡の文書の名から引く（_docs_named）
_NAME = r"(?<![A-Za-z0-9/.\-])([A-Za-z0-9][\w.\-]*?)"
NAME_NUM = re.compile(_NAME + r"(?:\s+|\s*の\s*)(?:§\s*(\d+(?:\.\d+)*)|(\d+(?:\.\d+)*)\s*節)")
NAME_QUOTE = re.compile(_NAME + r"\s*の\s*「([^」\n]+)」")
# パスの無い「§3」「8 節」（依頼が別の所で名指した設計書がただ 1 本の時だけ、それの節に結び付ける）
BARE_NUM = re.compile(r"§\s*(\d+(?:\.\d+)*)|(\d+(?:\.\d+)*)\s*節")
# 問いが立たない根拠の名指し「<パス>:<行>」「<パス>:<開始>-<終了>」。パスは拡張子つきで / 区切りの段を持ってよい。前が英数字・/・.・:・-
# の当たりは拾わない（URL の host:port を外す。拡張子の無い時刻 10:15 も、拡張子が英字で始まらない版の番号 3.12:1 も拾わない）。パスの字は ASCII に限る（日本語の地の文に続けて
# 書いたパスの頭に地の文を混ぜない）。当たりのうち拡張子が ANCHOR_EXT（impact のコード・設定・文書の拡張子の表）に在る物だけを名指しに
# 数える（db.internal:5432・foo.bar:12 のような host:port やドット付きの名を、固めた版に無いファイルとして拒み続けない）
ANCHOR = re.compile(r"(?<![A-Za-z0-9_/.:\-])((?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_.\-]*[A-Za-z0-9_\-]\.[A-Za-z][A-Za-z0-9]*):(\d+)(?:-(\d+))?(?![\d:])")
ANCHOR_EXT = impact.PY_EXT | impact.PATHREF_EXT | impact.DOC_EXT | impact.OTHER_CODE_EXT
UNANCHORED = "根拠の実物の名指しなし"
PREMISE_MISS = "premise_invalid_reason の名指しが固めた版の実物に当たらない（追跡されたファイルと、その行の範囲を名指せ）: "
# Markdown として見出しを数える拡張子（_md_heads）と ATX 見出しの行（写しの rules の _md_slugs と同じ形）
MD_SUFFIXES = (".md", ".markdown")
MD_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
UNPASSED = re.compile(r"渡されていない|渡っていない")
# 『渡されていない』の文が控えの given の kind を指す語。制約・前提のずれは「目的と実測した制約しか渡されていない」のような
# 地の文によく出て無関係の行まで当たるので語では当てず、what そのものが文に在る時だけ当てる。設計書の節も「設計書」の語は
# 別の設計書の文にも出るので語では当てず、what のパスか節番号が文に在る時だけ当てる（_named_hit）
# 地図は「地図」の語か、what のパスの部分（`:` の前）が文に在る時に当てる
CLAIM_WORDS = {"human_answer": ("人の答え", "関所"), "repo_map": ("地図",)}
PREMISES_FILE = "design-premises.json"   # r2.design に渡した前提の入力の控え（盤面の根。design.json と同じく run に 1 つ）
# 独立設計の指示書の頭に機械が貼ってよい前提の種類（premises の控えの kind の許す一覧）。一覧の外（ほかのブロックの出力など）を
# 貼る口は作らない（独立設計の隔て。設計書 structure-block-design 7 節）。graph の reads で描く本文はこの柵の外（graph の reads が縛り、
# その reads と prompt_append などの入口は tests/test_blk_eyes.py の test_r2_design_inputs_are_exactly_the_allowlist が許可の一覧の等式で縛る）
PREMISE_KINDS = ("human_answer", "named_section", "repo_map")
# 対象のリポジトリの地図として根から読む名（関所の決め: 根の 2 つだけ。docs/ の下や README は読まない）。中身は分類せず丸ごと貼る。
# AGENTS.md は blk-fix の fixrules.PROMPT_NAMES（役の指示書として読む名）とも重なる（core から blk-fix へは依らないので別に置く）
MAP_NAMES = ("ARCHITECTURE.md", "AGENTS.md")
MAP_HEAD = promptsection.Section("### 対象のリポジトリの地図", source="fn:design.repo_map")
MAP_FILE_HEAD = promptsection.Section("#### {name}:1-{total}", source="fn:design.repo_map")
NAMED_BODY_HEAD = promptsection.Section("#### {name}（{src}）", source="fn:design.named_sections")
SLUG_LINE = promptsection.Section("# {title}", human="見出しのアンカーの重複を数えるために組む行（指示書には貼らない）")
MAP_ASK = ("対象のリポジトリの根に在る地図の文書（依頼を固めた版のファイルから機械が貼った。見出しは出どころのパス:行）。"
           "依頼が名指していなくても、仕組みの中に既に在る実物（信用の起点・外との通信の経路・守る物）から設計を始めよ。")


def human_answers(b) -> tuple:
    """(R2 の 2 つの役に貼る人の関所の答え（record.process.human_items）の節 か 空, 貼った行, 機械の行, 見た印 {count, last_round})。
    聞いた項目の本文（asked）は判定の一覧・決着済み論点に当たるので写さず、round・node・kinds・answer・note だけを取る。
    answer の無い行（守りのファイル・食い違い・無人の停止で機械が積んだ行）は人の答えでないので貼らず、控えの withheld に回す"""
    rows, machine, last = [], [], None
    for h in (b.record.get("process") or {}).get("human_items") or []:
        if not isinstance(h, dict):
            continue
        at = f"周 {h.get('round')}" + (f"・{h['node']}" if h.get("node") else "")
        kinds = "・".join(str(k) for k in h.get("kinds") or []) or "種類なし"
        if h.get("answer") is None:
            machine.append(f"{at}（{kinds}）")
            continue
        note = h.get("note") or "（一言なし）"
        rows.append(f"{at}（{kinds}）: {h['answer']}（一言: {note}）")
        last = h.get("round")
    text = (f"{HUMAN_HEAD}\n\n{HUMAN_ASK}\n\n" + "\n".join(f"- {r}" for r in rows)) if rows else ""
    return text, rows, machine, {"count": len(rows), "last_round": last}


def _is_doc(path) -> bool:
    """名指しのパスを設計書に数えるか: URL でなく、拡張子が文書の拡張子（impact.DOC_EXT。コードを含まない）に在る"""
    return "://" not in path and pathlib.PurePosixPath(path).suffix[1:].lower() in impact.DOC_EXT


def _tracked(repo) -> list:
    """固めた版 HEAD の追跡ファイルの名（根からの相対。並べた順）"""
    got = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "-z", "HEAD"], capture_output=True)
    return [n for n in got.stdout.decode("utf-8", "replace").split("\0") if n] if got.returncode == 0 else []


def _docs_named(repo, name) -> list:
    """固めた版の追跡ファイルのうち、設計書に数える拡張子で、拡張子を除いた名が name と等しいか -・_・. の後に name で終わる物
    （日付を頭に付けた設計書に届くため）"""
    return [n for n in _tracked(repo) if _is_doc(n)
            and ((stem := pathlib.PurePosixPath(n).stem) == name or any(stem.endswith(f"{c}{name}") for c in "-_."))]


def _named_targets(b, text, repo) -> tuple:
    """(依頼の文が設計書の節を名指す相対の指し先, 結び付けられなかった名指しの [(元の文字列, 理由)])。設計書は拡張子が文書の物
    （_is_doc）だけで、コードへのリンクは数えない。拾う順は Markdown のリンク・コードスパンの `<path>#<見出し>` → コードスパンの後の
    「N 節」「§N」→ パスの無い名前の「<名前> N 節」「<名前> の「<見出し>」」（名の一致する追跡の文書がただ 1 本ならそれ。2 本以上は
    推測せずに理由と返し、0 本は名前に数えない）→ パスの無い「N 節」「§N」。番号の名指しは `<path> N 節` の形で返す。パスの無い番号は、
    依頼が名指した設計書のパスがただ 1 本の時だけそれに結び付け、0 本か 2 本以上なら推測せずに理由と返す（_head_file が末尾の一致が
    複数の時に決めないのと同じ）。出た順・重複なし"""
    found = [m.group(1) or m.group(2) for m in b.rules.MD_LINK.finditer(text)] + CODE_SPAN_ANCHOR.findall(text)
    out, docs, unbound = [], [], []

    def add(t, path):
        if path not in docs:
            docs.append(path)
        if t and t not in out:
            out.append(t)

    for t in found:
        path, _, anchor = t.partition("#")
        if _is_doc(path):
            add(t if anchor else "", path)
    for m in CODE_SPAN_NUM.finditer(text):
        if _is_doc(m.group(1)):
            add(f"{m.group(1)} {m.group(2) or m.group(3)} 節", m.group(1))
    rest = list(CODE_SPAN_NUM.sub("", b.rules.MD_LINK.sub("", text)))
    plain = "".join(rest)
    for rx in (NAME_NUM, NAME_QUOTE):
        for m in rx.finditer(plain):
            name = m.group(1)
            cands = [] if re.fullmatch(r"[\d.]+", name) else _docs_named(repo, name)
            if not cands:
                continue
            rest[m.start():m.end()] = " " * (m.end() - m.start())   # パスの無い番号に回さない
            if len(cands) > 1:
                unbound.append((m.group(0), f"名の一致する追跡の文書が {len(cands)} 本あって決められない（候補: {', '.join(cands)}）"))
            elif rx is NAME_NUM:
                add(f"{cands[0]} {m.group(2) or m.group(3)} 節", cands[0])
            else:
                add(f"{cands[0]}#{m.group(2)}", cands[0])
    bare = list(BARE_NUM.finditer("".join(rest)))
    if len(docs) == 1:
        for m in bare:
            add(f"{docs[0]} {m.group(1) or m.group(2)} 節", docs[0])
        return out, unbound
    why = (f"依頼が名指した設計書のパスが {len(docs)} 本あって決められない" if docs else
           "結び付けられる形の設計書の名指しが依頼に無い（リンク・`<path>#<見出し>`・`<path>` N 節・<名前> N 節 の形だけを数える）")
    return out, unbound + [(w, why) for w in dict.fromkeys(m.group(0) for m in bare)]


def _head_file(repo, path) -> str:
    """名指しのパスを固めた版 HEAD の追跡ファイルに解く。根から無ければ、末尾が一致する追跡ファイルがただ 1 つの時だけそれ
    （持ち主は pack の下から見た相対で書くことがある）。引けなければ ValueError（理由）"""
    rel = pathlib.PurePosixPath(urllib.parse.unquote(path))
    if rel.is_absolute() or ".." in rel.parts or ".git" in rel.parts:
        raise ValueError("作業ツリーの根の外か .git を指す")
    names = _tracked(repo)
    if str(rel) in names:
        return str(rel)
    tail = [n for n in names if n.endswith(f"/{rel}")]
    if len(tail) == 1:
        return tail[0]
    raise ValueError("固めた版にファイルが無い" if not tail else f"同じ末尾の追跡ファイルが {len(tail)} 本あって決められない")


def _marks(line) -> tuple:
    """(記号 1 文字, 並びの長さ, 並びの後の残り)。行頭の空白 3 つまでを除いた後が英数字でも空白でもない同じ文字の連なりで
    なければ ("", 0, "")"""
    s = line[len(line) - len(line.lstrip(" ")):] if len(line) - len(line.lstrip(" ")) <= 3 else ""
    if not s or s[0].isalnum() or s[0].isspace():
        return "", 0, ""
    n = len(s) - len(s.lstrip(s[0]))
    return s[0], n, s[n:]


def _md_heads(text, md_lines) -> list:
    """Markdown の見出しの行（_heads と同じ形）。写しの rules の _md_lines（``` / ~~~ の囲いの外の行）の ATX 見出しだけを数える
    （下線の見出しも箇条・引用・表の行も数えない。依頼 238 の前の .md の数え方と同じ）"""
    out = []
    for n, line in md_lines(text):
        m = MD_HEAD.match(line)
        if m:
            out.append({"line": n, "kind": "prefix", "mark": "#", "depth": len(m.group(1)), "title": m.group(2)})
    return out


def _heads(lines) -> list:
    """見出しの行 [{line（1 始まり）, kind（prefix: 行頭の同じ記号の並びと空白と題 / under: 題の行の次の行が 1 種類の記号の
    3 文字以上だけ。上線と下線が同じ記号で 1 行を挟む題も under で、mark は記号を 2 つ重ねた物）, mark, depth, title}]。
    Markdown でない文書に使う（Markdown は _md_heads）。形式の名前は持たない。記号だけの行が挟む区間（囲み）の中は数えず、
    隣の行と同じ記号・同じ長さの前置きの行は列（箇条・表）とみなして数えない。depth は前置きなら並びの長さ、下線なら下線の
    mark が文書の中で初めて現れた順（0 始まり）。囲みと列の見分けは形式に依る推測（docs/language-neutral-inventory.md 7-7）"""
    marks = [_marks(x) for x in lines]
    only = [n >= 3 and not rest.strip() for _, n, rest in marks]

    def body(i):
        return bool(lines[i].strip()) and not only[i]

    def over(i):   # 上線つきの題: 記号だけの行・題の 1 行・同じ記号だけの行（前の行が本文なら上線でなく前の題の下線）
        return (only[i] and i + 2 < len(lines) and only[i + 2] and marks[i + 2][0] == marks[i][0] and body(i + 1)
                and not (i > 0 and body(i - 1)))

    inside, titled, i = set(), set(), 0
    while i < len(lines):   # 囲み: 3 文字以上の記号の並び（と空白の無い 1 語）で開き、下線でなく、次の行が空でない
        if over(i):
            titled.add(i)
            i += 3
            continue
        c, n, rest = marks[i]
        word = rest.rstrip()   # 並びの直後に空白を挟む行（`### A`）は前置きの形で、囲みを開かない
        opens = (n >= 3 and not any(ch.isspace() for ch in word) and not (only[i] and i > 0 and body(i - 1))
                 and i + 1 < len(lines) and lines[i + 1].strip())
        close = next((j for j in range(i + 1, len(lines)) if only[j] and marks[j][0] == c and marks[j][1] >= n),
                     None) if opens else None
        if close is None:
            i += 1
            continue
        inside.update(range(i, close + 1))
        i = close + 1

    def prefix(i):
        c, n, rest = marks[i]
        return n > 0 and i not in inside and rest[:1].isspace() and bool(rest.strip())

    out, order, skip = [], [], set()
    for i in range(len(lines)):
        if i in inside or i in skip:
            continue
        if i in titled:
            c = marks[i][0] * 2
            if c not in order:
                order.append(c)
            out.append({"line": i + 1, "kind": "under", "mark": c, "depth": order.index(c), "title": lines[i + 1].strip()})
            skip.update((i + 1, i + 2))
            continue
        if prefix(i):
            c, n, rest = marks[i]
            if any(0 <= j < len(lines) and prefix(j) and marks[j][:2] == (c, n) for j in (i - 1, i + 1)):
                continue
            out.append({"line": i + 1, "kind": "prefix", "mark": c, "depth": n, "title": rest.strip().rstrip(c).strip()})
        elif (i + 1 < len(lines) and i + 1 not in inside and i + 1 not in titled and only[i + 1] and body(i)
              and not prefix(i)):
            c = marks[i + 1][0]
            if c not in order:
                order.append(c)
            out.append({"line": i + 1, "kind": "under", "mark": c, "depth": order.index(c), "title": lines[i].strip()})
    return out


def _section_lines(text, *, num="", anchor="", slugs=None, md_lines=None) -> tuple:
    """名指し（番号 num か見出しのアンカー anchor）に当たる節の (開始行, 終了行)。1 始まりで両端を含む。引けなければ ValueError（理由）。
    アンカーは slugs（写しの rules の _md_slugs。GitHub の書き方で重複は -1）で作った物と等しい見出し、無ければ題がアンカーを含む見出し。
    md_lines（写しの rules の _md_lines）を渡せば Markdown として _md_heads で、渡さなければ行の形の推測 _heads で見出しを数える"""
    lines = text.splitlines()
    heads = _md_heads(text, md_lines) if md_lines else _heads(lines)
    if num:
        by_num = re.compile(rf"(?:第)?{re.escape(num)}(?:\.?(?:\s|$)|節)")
        hits = [h for h in heads if by_num.match(h["title"].lstrip("§ \t"))]
    else:
        want = urllib.parse.unquote(anchor).lower()
        hits = []
        if slugs is not None:
            for k, h in enumerate(heads):
                before = "\n".join(SLUG_LINE.format(title=x['title']) for x in heads[:k])
                if want in slugs(before + "\n# " + h["title"]) - slugs(before):
                    hits.append(h)
        if not hits:
            hits = [h for h in heads if want and want in h["title"].lower()]
    if not hits:
        raise ValueError("見出しが無い")
    if len(hits) > 1:
        raise ValueError(f"当たる見出しが {len(hits)} 個あって決められない（行 {', '.join(str(h['line']) for h in hits)}）")
    hit = hits[0]

    def ends(h):
        if hit["kind"] == "prefix":
            return h["kind"] == "prefix" and h["mark"] == hit["mark"] and h["depth"] <= hit["depth"]
        return h["kind"] == "under" and (h["mark"] == hit["mark"] or h["depth"] < hit["depth"])
    end = next((h["line"] - 1 for h in heads if h["line"] > hit["line"] and ends(h)), len(lines))
    while end > hit["line"] and not lines[end - 1].strip():
        end -= 1
    return hit["line"], end


def _split_target(target) -> tuple:
    """名指しの文字列 `<path>#<anchor>` か `<path> <N> 節` を (path, anchor, num) に分ける（path の拡張子は問わない）"""
    num = re.fullmatch(r"(.+) (\S+) 節", target)
    if num:
        return num.group(1), "", num.group(2)
    path, _, anchor = target.partition("#")
    return path, anchor, ""


def _section(b, repo, target) -> tuple:
    """(名指し 1 つの節の本文（依頼を固めた版 HEAD のファイルから）, 出どころ `<パス>:<開始>-<終了>`,
    engine の FILE_CAP で切った残りの範囲 `<パス>:<k>-<終了>` か "")。引けなければ ValueError（理由）"""
    path, anchor, num = _split_target(target)
    rel = _head_file(repo, path)
    got = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{rel}"],
                         capture_output=True, text=True, encoding="utf-8")
    if got.returncode != 0:
        raise ValueError("固めた版にファイルが無い")
    md = b.rules._md_lines if pathlib.PurePosixPath(rel).suffix.lower() in MD_SUFFIXES else None
    start, end = _section_lines(got.stdout, num=num, anchor=anchor, slugs=b.rules._md_slugs, md_lines=md)
    body = "\n".join(got.stdout.splitlines()[start - 1:end])
    cut = []
    capped = cap_bytes(body, target, cut)
    rest = ""
    if cut:   # 切った後の本文に丸ごと残った行の数の次の行から
        kept = body.encode("utf-8")[:FILE_CAP].decode("utf-8", "ignore").count("\n")
        rest = f"{rel}:{start + kept}-{end}"
    return capped, f"{rel}:{start}-{end}", rest


def named_sections(b, repo) -> tuple:
    """(R2 の 2 つの役に貼る、依頼（盤面の inputs.request）が名指した設計書の節の本文 か 空, 控えの given, 控えの withheld)。
    引けなかった名指しは本文を貼らずに理由の 1 行にする。貼る見出しと切った残りには出どころの行の範囲を添える"""
    parts, given, withheld = [], [], []
    targets, unbound = _named_targets(b, (b.state.get("inputs") or {}).get("request") or "", repo)
    for t, why in unbound:
        parts.append(f"- 依頼が名指したが引けなかった: {t}（{why}）")
        withheld.append({"kind": "named_section", "what": t, "why": why})
    for t in targets:
        try:
            body, src, rest = _section(b, repo, t)
        except ValueError as e:
            parts.append(f"- 依頼が名指したが引けなかった: {t}（{e}）")
            withheld.append({"kind": "named_section", "what": t, "why": str(e)})
            continue
        parts.append(f"{NAMED_BODY_HEAD.format(name=t, src=src)}\n\n{body}")
        given.append({"kind": "named_section", "what": t})
        if rest:
            withheld.append({"kind": "named_section", "what": t, "why": f"{FILE_CAP} バイトを超えた残り（{rest}）"})
    text = (f"{NAMED_HEAD}\n\n{NAMED_ASK}\n\n" + "\n\n".join(parts)) if parts else ""
    return text, given, withheld


def repo_map(repo) -> tuple:
    """(R2 の 2 つの役に貼る対象のリポジトリの地図の節（空にならない）, 控えの given, 控えの withheld)。固めた版 HEAD の根に追跡されて
    いる MAP_NAMES を出どころのパス:行つきで丸ごと貼る。FILE_CAP を超えたら切り、切った行の範囲を withheld に書く。1 つも無ければ
    「地図なし」の 1 行を貼る。根のパスだけを読む（_head_file の末尾の一致は使わない）"""
    names = set(_tracked(repo))
    parts, given, withheld = [], [], []
    for n in MAP_NAMES:
        if n not in names:
            continue
        got = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{n}"], capture_output=True, text=True, encoding="utf-8")
        if got.returncode != 0:
            continue
        body = got.stdout.rstrip("\n")
        total = len(body.splitlines())
        if not total:
            withheld.append({"kind": "repo_map", "what": n, "why": "空のファイル"})
            continue
        cut = []
        parts.append(f"{MAP_FILE_HEAD.format(name=n, total=total)}\n\n{cap_bytes(body, n, cut)}")
        given.append({"kind": "repo_map", "what": f"{n}:1-{total}"})
        if cut:   # 切った後の本文に丸ごと残った行の数の次の行から
            k = 1 + body.encode("utf-8")[:FILE_CAP].decode("utf-8", "ignore").count("\n")
            withheld.append({"kind": "repo_map", "what": n, "why": f"{FILE_CAP} バイトを超えた残り（{n}:{k}-{total}）"})
    if not parts:
        parts.append(f"- 地図なし: 根の {'・'.join(MAP_NAMES)} は固めた版に無い")
        if not withheld:
            withheld.append({"kind": "repo_map", "what": "・".join(MAP_NAMES), "why": "対象のリポジトリの根に追跡されていない"})
    return f"{MAP_HEAD}\n\n{MAP_ASK}\n\n" + "\n\n".join(parts), given, withheld


def premises(b, repo) -> tuple:
    """(R2 の 2 つの役に共通して貼る、人が決めた前提の節の並び（人の関所の答え・依頼が名指した設計書の節・対象のリポジトリの地図。
    空の節は除く。地図の節は空にならない）,
    控え {given, withheld, seen})。控えは貼った本文と同じ呼び出しから作る（別の源から組み直さない）"""
    human, rows, machine, seen = human_answers(b)
    named, given, withheld = named_sections(b, repo)
    mapped, map_given, map_withheld = repo_map(repo)
    given = [{"kind": "human_answer", "what": r} for r in rows] + given + map_given
    outside = sorted({g["kind"] for g in given} - set(PREMISE_KINDS))
    if outside:   # 一覧の外の源（ほかのブロックの出力など）から貼る口を作らない
        raise BoardGap(f"独立設計に渡す入力の種類が許す一覧（{' / '.join(PREMISE_KINDS)}）の外: {', '.join(outside)}")
    withheld = [{"kind": "human_item", "what": m, "why": "answer の無い行（機械が積んだ。人の答えでない）"} for m in machine] + withheld + map_withheld
    return [s for s in (human, named, mapped) if s], {"given": given, "withheld": withheld, "seen": seen}


def claims_unpassed(reply) -> list:
    """R2 の返答（reason と differences の text）のうち、入力が渡されていない・渡っていないと書いた文（。と改行で切る）"""
    texts = [str((reply or {}).get("reason") or "")] + [str(d.get("text") or "") for d in (reply or {}).get("differences") or []
                                                         if isinstance(d, dict)]
    return [s.strip() for t in texts for s in re.split(r"[。\n]", t) if UNPASSED.search(s)]


def claims_given(claims, given) -> list:
    """claims_unpassed の文のうち、控えの given（渡した前提の入力）に当たる物の [{claim, kind, what}]。claim が what そのもの
    （設計書の節は what のパスか節番号）か given の kind の語（CLAIM_WORDS）を含めば当たる。判定はせず、並べて人に突き合わせさせる"""
    return [{"claim": c, "kind": g.get("kind"), "what": g.get("what")} for c in claims for g in given or []
            if isinstance(g, dict) and (str(g.get("what")) in c or any(w in c for w in CLAIM_WORDS.get(g.get("kind"), ()))
                                        or g.get("kind") == "named_section" and _named_hit(str(g.get("what")), c)
                                        or g.get("kind") == "repo_map" and str(g.get("what")).partition(":")[0] in c)]


def _named_hit(what, claim) -> bool:
    """設計書の節の what（`<path>#<見出し>` か `<path> N 節`）のパスか節番号（見出しの頭の番号）が claim に在るか"""
    path, anchor, num = _split_target(what)
    n = num or (re.match(r"\d+", anchor) or [""])[0]
    return path in claim or bool(n and re.search(rf"§\s*{re.escape(n)}(?![\d.])|(?<![\d.]){re.escape(n)}\s*節", claim))


def unusable(b):
    """目的の出典が R2 に使えない理由（None／目的不明／狭めている）。写しの p4.assemble が loop.purpose_unusable に置くのと同じ
    1 本（写しの rules の purpose_unusable）を、p4.assemble より前に呼ぶ"""
    return b.rules.purpose_unusable(b)


def read_design(board_dir):
    """盤面の根の design.json（無ければ None）。読めない・型に合わなければ Reject"""
    obj = accept.read_board(board_dir, DESIGN_FILE)
    if obj is not None:
        accept.type_errors(obj, accept.role_schema(NODE), f"盤面の {DESIGN_FILE} ")
    return obj


def made(board_dir) -> tuple:
    """(控えの中身 か None, 控えが壊れている時の理由)"""
    try:
        return read_design(board_dir), ""
    except Reject as e:
        return None, f"{MISSING}: {e}"


def due(b) -> tuple:
    """(起こすか, 理由)"""
    row = b.table.nodes.get(NODE) if b.table is not None else None
    if row is None or row.by != "role":
        return False, f"節の表に {NODE} の役が無い"
    got, broken = made(b.dir)
    if got is not None or broken:
        return False, broken or f"独立設計はもう {DESIGN_FILE} に在る"   # 壊れた控えも作り直さない（設計を 2 度作らない）
    gave = rolekit.given_up_reason(b.dir, NODE, give_up_after=GIVE_UP_AFTER)
    if gave:
        return False, gave
    st = b.node_state(NODE)
    if st != "pending":   # 済んだ・条件外（na）・省いた。まだ依存を待つ節も pending
        return False, f"盤面で {NODE} はこの周に {st}"
    if b.loop_state.get("r2_refire", True) is not True:
        return False, "R2 の再発火条件に当たらない"
    why = unusable(b)
    if why:
        return False, UNUSABLE[why]
    return True, f"{NODE} をこの周の修正の前に作る"


def snap(board_dir, repo) -> dict:
    """{ok, go, snapshot_file}。起こすなら作業ツリーの写しを置く"""
    b = entry.open_board(pathlib.Path(board_dir))
    go, _ = due(b)
    if not go:
        return {"ok": True, "go": False, "snapshot_file": ""}
    return {"ok": True, "go": True, "snapshot_file": str(entry.snapshot(pathlib.Path(board_dir), SNAPSHOT_NAME, pathlib.Path(repo)))}


def _rejects(board_dir) -> list:
    rows = accept.read_board(board_dir, rolekit.rejects_path(board_dir, NODE).name) or []
    return [r for r in rows if isinstance(r, dict)]


def prep(board_dir, repo) -> dict:
    """返り {prompt, prompt_file, node, attempt, already, role_def, role_def_missing}。起こさない盤面は BoardGap（snap が go の時だけ）"""
    b = entry.open_board(pathlib.Path(board_dir))
    go, why = due(b)
    if not go:
        raise BoardGap(f"{NODE} を今は起こさない（{why}）——snap が go の時だけ支度する")
    body, _ = rolekit.render_body(b, NODE, ahead=True)
    parts, ledger = premises(b, repo)
    accept.write_board(board_dir, PREMISES_FILE, {"node": NODE, **ledger})
    if parts:   # graph の reads は関所の答えも依頼の名指しも持たない。写しの graph は変えずに頭に貼る
        body = f"{DESIGN_PREMISE_HEAD}\n\n{DESIGN_PREMISE_REREAD}\n\n" + "\n\n".join(parts) + f"\n\n---\n\n{body}"
    prompt, def_file, missing = rolekit.with_role_definition(b, NODE, body)
    rows = _rejects(board_dir)
    if rows:   # 役は道具を持たないので、理由のファイルでなく文を貼る
        prompt = rolekit.with_reject(prompt, rows[-1].get("reason", ""))
    p = b.work(PROMPT_NAME)
    p.write_text(prompt, encoding="utf-8")
    return {"prompt": prompt, "prompt_file": str(p), "node": NODE, "attempt": len(rows) + 1, "already": False,
            "role_def": def_file, "role_def_missing": missing}


def _anchor_matches(text) -> list:
    """ANCHOR の当たりのうち、拡張子が ANCHOR_EXT に在る物（出た順）"""
    return [m for m in ANCHOR.finditer(str(text or ""))
            if pathlib.PurePosixPath(m.group(1)).suffix[1:].lower() in ANCHOR_EXT]


def anchors(text) -> list:
    """文の中の `パス:行` と `パス:開始-終了` を (パス, 開始, 終了) で出た順に（`パス:行` は開始と終了が同じ。_anchor_matches の物だけ）"""
    return [(m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))) for m in _anchor_matches(text)]


def anchor_misses(text, repo) -> list:
    """anchors のうち固めた版 HEAD の追跡ファイルと行の範囲に当たらない物ごとに「<パス>:<開始>[-<終了>]（<理由>）」（字は文のまま）"""
    out = []
    for m in _anchor_matches(text):
        start, end = int(m.group(2)), int(m.group(3) or m.group(2))
        try:
            rel = _head_file(repo, m.group(1))
            got = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{rel}"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            if got.returncode != 0:
                raise ValueError("固めた版にファイルが無い")
            n = len(got.stdout.splitlines())
            if not 1 <= start <= end <= n:
                raise ValueError(f"行の範囲の外（ファイルは {n} 行）")
        except ValueError as e:
            row = f"{m.group(0)}（{e}）"
            if row not in out:
                out.append(row)
    return out


def anchor_note(text) -> str:
    """根拠の文に名指し（anchors）が無ければ「（根拠の実物の名指しなし）」、在れば ""（事前審査の指示書と報告が添える）"""
    return "" if anchors(text) else f"（{UNANCHORED}）"


def check_design(reply, board_dir, repo) -> dict:
    """型（写しの r2.design の schema）→ 作業ツリー（役を起こす前の写しと同じ）→ 問いが立たない時は根拠の名指し（パス:行）が固めた版の
    追跡ファイルと行の範囲に当たるか（名指しが無ければ拒まない）。通れば design.json。{ok, reason, design_file}"""
    def run():
        b = entry.open_board(pathlib.Path(board_dir))
        moved = entry.tree_moved_since(b, SNAPSHOT_NAME, pathlib.Path(repo))
        if moved:
            raise Reject(entry.READONLY_MOVED + moved)
        accept.type_errors(reply, accept.role_schema(NODE), "独立設計の返答")
        if not reply["question_stands"]:
            misses = anchor_misses(reply.get("premise_invalid_reason") or reply["reason"], repo)
            if misses:
                raise Reject(PREMISE_MISS + "・".join(misses))
        return {"ok": True, "reason": "", "design_file": str(accept.write_board(board_dir, DESIGN_FILE, reply))}
    return accept.guard(run, design_file="")


def accept_reply(board_dir, raw, repo) -> dict:
    """返り {ok, done, give_up, skipped, reason, node}。拒否は盤面の根の控えに積み、GIVE_UP_AFTER 回目で done・give_up"""
    reply, why = rolekit.parse_reply(raw)
    got = {"ok": False, "reason": why} if reply is None else check_design(reply, board_dir, repo)
    out = rolekit.with_done(pathlib.Path(board_dir), NODE, {"ok": got["ok"], "reason": got.get("reason", "")},
                            give_up_after=GIVE_UP_AFTER)
    return {"ok": out["ok"], "done": out["done"], "give_up": bool(out["done"] and not out["ok"]), "skipped": False,
            "reason": out["reason"], "node": NODE}


def missing(b) -> str:
    """設計が無い理由の 1 文（控えが在れば空）"""
    got, broken = made(b.dir)
    if got is not None or broken:
        return broken
    gave = rolekit.given_up_reason(b.dir, NODE, give_up_after=GIVE_UP_AFTER)
    if gave:
        return f"{MISSING}: {gave}"
    why = unusable(b)
    if why:
        return UNUSABLE[why]
    return f"{MISSING}: 修正の前に設計の役を起こしていない（{DESIGN_FILE} が無い）"


def hand(b, board_dir, repo) -> dict:
    """盤面が r2.design を待っていて控えが在れば渡す。返り {handed, reason}。渡さない時は handed: False と理由（止めない——
    設計が無いことは独立の目の出口が言う）"""
    if b.state.get("halted") or b.state.get("stop"):
        return {"handed": False, "reason": "盤面は止まっている（周を締めた・止めた）"}
    if pending_instance(b, NODE) is None:
        return {"handed": False, "reason": f"{NODE} は盤面で待っていない（{b.node_state(NODE)}）"}
    reply, _ = made(board_dir)
    if reply is None:   # 控えが無い・壊れている（受け付けの後に書き換わった）: 渡さず、目の層に理由を残す
        why = missing(b)
        b.trace(MISSING_OP, reason=why)
        return {"handed": False, "reason": why}
    got = entry.hand(b, pathlib.Path(board_dir), NODE, reply, pathlib.Path(repo))
    if not got["ok"]:
        why = f"{MISSING}: 盤面が {DESIGN_FILE} を受けない（{got['reason']}）"
        entry.open_board(pathlib.Path(board_dir)).trace(MISSING_OP, reason=why)
        return {"handed": False, "reason": why}
    entry.open_board(pathlib.Path(board_dir)).trace(HANDED_OP, file=DESIGN_FILE)
    return {"handed": True, "reason": ""}
