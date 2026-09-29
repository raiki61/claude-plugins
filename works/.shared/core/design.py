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
- premises:      R2 の 2 つの役（r2.design・r2.compare）に共通して貼る節の並びと、貼った入力の控え {given, withheld, seen}（kind は PREMISE_KINDS の中だけ）。
                 human_answers（人の関所の答え。asked は写さず、answer の無い機械の行は withheld。seen は貼った答えの数と
                 最後の round の印で、突き合わせの側が独立設計の後に来た答えを分けて並べる）と named_sections（依頼が
                 名指した設計書の節の本文。リンク・`<path>.md#<見出し>`・`<path>.md` N 節・パスの無い N 節（依頼が名指した設計書が
                 ただ 1 本の時だけそれに結び付ける）の名指しを、固めた版 HEAD のファイルから見出しで抜く。引けなかった・結び付け
                 られなかった名指しは理由の 1 行で withheld。1 節は engine が役に貼る本文の上限 FILE_CAP バイトまで）
- claims_unpassed: R2 の返答のうち『渡されていない』『渡っていない』と書いた文（独立の目の出口が控えと並べる）
- accept:        返答を型（写しの schema）と作業ツリーの比べに通し、通れば design.json。拒否は盤面の根の控えに積み、
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
HUMAN_HEAD = "### 人の関所の答え"
HUMAN_ASK = ("人が関所で答えた前提（run の中で人が決めた物）。ほかの節より先に読め。答えが目的の文や前の要求を取り下げ・変えていれば、"
             "取り下げ・変えた後の要求を前提にせよ（取り下げた要求を固定の契約にしない）。設計が取り下げた要求を置いていても、"
             "そのことだけでは差にも前提の崩れにも数えず、答えに照らした目的で突き合わせよ。")
DESIGN_PREMISE_HEAD = "## 人が決めた前提（機械が貼った）"
# 写しの指示書は 1 バイトも変えない（gl-prompts/COPIED_FROM）ので、入力を言う写しの文をこの節で読み替える
DESIGN_PREMISE_REREAD = ("下の指示書の「渡すのは元の目的と実測した制約だけである」は、この run では、この節（人の関所の答え・"
                         "依頼が名指した設計書の節）も渡していると読み替えよ。")
NAMED_HEAD = "### 依頼が名指した設計書の節"
NAMED_ASK = "依頼が名指した設計書の節の本文（依頼を固めた版のファイルから機械が抜いた）。目的の文と同じく依頼の一部として読め。"
CODE_SPAN_MD = re.compile(r"`([^`\s]+\.md#[^`\s]+)`")
# 持ち主の地の文の名指し: 「`<path>.md` 3 節」「`<path>.md` の §3」（見出しの頭の番号で引く）
CODE_SPAN_NUM = re.compile(r"`([^`\s#]+\.md)`\s*(?:の\s*)?(?:§\s*(\d+(?:\.\d+)*)|(\d+(?:\.\d+)*)\s*節)")
# パスの無い「§3」「8 節」（依頼が別の所で名指した設計書がただ 1 本の時だけ、それの節に結び付ける）
BARE_NUM = re.compile(r"§\s*(\d+(?:\.\d+)*)|(\d+(?:\.\d+)*)\s*節")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s")
UNPASSED = re.compile(r"渡されていない|渡っていない")
# 『渡されていない』の文が控えの given の kind を指す語。制約・前提のずれは「目的と実測した制約しか渡されていない」のような
# 地の文によく出て無関係の行まで当たるので語では当てず、what そのものが文に在る時だけ当てる。設計書の節も「設計書」の語は
# 別の設計書の文にも出るので語では当てず、what のパスか節番号が文に在る時だけ当てる（_named_hit）
CLAIM_WORDS = {"human_answer": ("人の答え", "関所")}
PREMISES_FILE = "design-premises.json"   # r2.design に渡した前提の入力の控え（盤面の根。design.json と同じく run に 1 つ）
# 独立設計の指示書の頭に機械が貼ってよい前提の種類（premises の控えの kind の許す一覧）。一覧の外（ほかのブロックの出力など）を
# 貼る口は作らない（独立設計の隔て。設計書 structure-block-design 7 節）。graph の reads で描く本文はこの柵の外（graph の reads が縛る）
PREMISE_KINDS = ("human_answer", "named_section")


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


def _named_targets(b, text) -> tuple:
    """(依頼の文が .md の見出しを名指す相対の指し先, 結び付けられなかった名指しの [(元の文字列, 理由)])。指し先は
    Markdown のリンク・コードスパンの `<path>.md#<見出し>` と、コードスパンの後の「N 節」「§N」とパスの無い「N 節」「§N」。
    番号の名指しは `<path>.md N 節` の形で返す。パスの無い名指しは、依頼が名指した設計書のパスがただ 1 本の時だけそれに
    結び付け、0 本か 2 本以上なら推測せずに理由と返す（_head_file が末尾の一致が複数の時に決めないのと同じ）。出た順・重複なし"""
    found = [m.group(1) or m.group(2) for m in b.rules.MD_LINK.finditer(text)] + CODE_SPAN_MD.findall(text)
    out, docs = [], []

    def add(t, path):
        if path not in docs:
            docs.append(path)
        if t and t not in out:
            out.append(t)

    for t in found:
        path, _, anchor = t.partition("#")
        if path.endswith(".md") and "://" not in path:
            add(t if anchor else "", path)
    for m in CODE_SPAN_NUM.finditer(text):
        if "://" not in m.group(1):
            add(f"{m.group(1)} {m.group(2) or m.group(3)} 節", m.group(1))
    bare = list(BARE_NUM.finditer(CODE_SPAN_NUM.sub("", b.rules.MD_LINK.sub("", text))))
    if len(docs) == 1:
        for m in bare:
            add(f"{docs[0]} {m.group(1) or m.group(2)} 節", docs[0])
        return out, []
    why = (f"依頼が名指した設計書のパスが {len(docs)} 本あって決められない" if docs else
           "結び付けられる形の設計書のパスの名指しが依頼に無い（リンク・`<path>.md#<見出し>`・`<path>.md` N 節 の形だけを数える）")
    return out, [(w, why) for w in dict.fromkeys(m.group(0) for m in bare)]


def _head_file(repo, path) -> str:
    """名指しのパスを固めた版 HEAD の追跡ファイルに解く。根から無ければ、末尾が一致する追跡ファイルがただ 1 つの時だけそれ
    （持ち主は pack の下から見た相対で書くことがある）。引けなければ ValueError（理由）"""
    rel = pathlib.PurePosixPath(urllib.parse.unquote(path))
    if rel.is_absolute() or ".." in rel.parts or ".git" in rel.parts:
        raise ValueError("作業ツリーの根の外か .git を指す")
    got = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "-z", "HEAD"], capture_output=True)
    names = got.stdout.decode("utf-8", "replace").split("\0") if got.returncode == 0 else []
    if str(rel) in names:
        return str(rel)
    tail = [n for n in names if n.endswith(f"/{rel}")]
    if len(tail) == 1:
        return tail[0]
    raise ValueError("固めた版にファイルが無い" if not tail else f"同じ末尾の追跡ファイルが {len(tail)} 本あって決められない")


def _section(b, repo, target) -> tuple:
    """(名指し 1 つの節の本文（依頼を固めた版 HEAD のファイルから）, engine の FILE_CAP で切ったか)。引けなければ ValueError（理由）"""
    num = re.fullmatch(r"(.+\.md) (\S+) 節", target)
    path, _, anchor = (num.group(1), "", "") if num else target.partition("#")
    got = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{_head_file(repo, path)}"],
                         capture_output=True, text=True, encoding="utf-8")
    if got.returncode != 0:
        raise ValueError("固めた版にファイルが無い")
    text, slug = got.stdout, urllib.parse.unquote(anchor).lower()
    # 見出しの形は CommonMark の ATX 見出しで、写しの rules と同じ囲いの外の行だけ。節の境（同じか浅い次の見出しの前まで）は
    # CommonMark に無く works が決めた規則
    heads = [(i, len(m.group(1)), line) for i, line in b.rules._md_lines(text) if (m := HEADING.match(line))]
    lines = text.splitlines()
    by_num = num and re.compile(rf"^\s{{0,3}}#{{1,6}}\s+(?:§\s*)?{re.escape(num.group(2))}(?:\.?(?:\s|$)|節)")
    for k, (i, level, line) in enumerate(heads):   # アンカーは写しの rules と同じ GitHub の書き方（重複の -1 も同じ数え方）
        before = "\n".join(h for _, _, h in heads[:k])
        if (by_num.match(line) if by_num else
                slug in b.rules._md_slugs(before + "\n" + line) - b.rules._md_slugs(before)):
            end = next((j for j, lv, _ in heads[k + 1:] if lv <= level), len(lines) + 1)
            body = "\n".join(lines[i - 1:end - 1]).strip()
            cut = []
            return cap_bytes(body, target, cut), bool(cut)
    raise ValueError("見出しが無い")


def named_sections(b, repo) -> tuple:
    """(R2 の 2 つの役に貼る、依頼（盤面の inputs.request）が名指した設計書の節の本文 か 空, 控えの given, 控えの withheld)。
    引けなかった名指しは本文を貼らずに理由の 1 行にする"""
    parts, given, withheld = [], [], []
    targets, unbound = _named_targets(b, (b.state.get("inputs") or {}).get("request") or "")
    for t, why in unbound:
        parts.append(f"- 依頼が名指したが引けなかった: {t}（{why}）")
        withheld.append({"kind": "named_section", "what": t, "why": why})
    for t in targets:
        try:
            body, cut = _section(b, repo, t)
        except ValueError as e:
            parts.append(f"- 依頼が名指したが引けなかった: {t}（{e}）")
            withheld.append({"kind": "named_section", "what": t, "why": str(e)})
            continue
        parts.append(f"#### {t}\n\n{body}")
        given.append({"kind": "named_section", "what": t})
        if cut:
            withheld.append({"kind": "named_section", "what": t, "why": f"{FILE_CAP} バイトを超えた残り"})
    text = (f"{NAMED_HEAD}\n\n{NAMED_ASK}\n\n" + "\n\n".join(parts)) if parts else ""
    return text, given, withheld


def premises(b, repo) -> tuple:
    """(R2 の 2 つの役に共通して貼る、人が決めた前提の節の並び（人の関所の答え・依頼が名指した設計書の節。空の節は除く）,
    控え {given, withheld, seen})。控えは貼った本文と同じ呼び出しから作る（別の源から組み直さない）"""
    human, rows, machine, seen = human_answers(b)
    named, given, withheld = named_sections(b, repo)
    given = [{"kind": "human_answer", "what": r} for r in rows] + given
    outside = sorted({g["kind"] for g in given} - set(PREMISE_KINDS))
    if outside:   # 一覧の外の源（ほかのブロックの出力など）から貼る口を作らない
        raise BoardGap(f"独立設計に渡す入力の種類が許す一覧（{' / '.join(PREMISE_KINDS)}）の外: {', '.join(outside)}")
    withheld = [{"kind": "human_item", "what": m, "why": "answer の無い行（機械が積んだ。人の答えでない）"} for m in machine] + withheld
    return [s for s in (human, named) if s], {"given": given, "withheld": withheld, "seen": seen}


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
                                        or g.get("kind") == "named_section" and _named_hit(str(g.get("what")), c))]


def _named_hit(what, claim) -> bool:
    """設計書の節の what（`<path>.md#<見出し>` か `<path>.md N 節`）のパスか節番号（見出しの頭の番号）が claim に在るか"""
    num = re.fullmatch(r"(.+\.md) (\S+) 節", what)
    path, _, anchor = (num.group(1), "", "") if num else what.partition("#")
    n = num.group(2) if num else (re.match(r"\d+", anchor) or [""])[0]
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


def check_design(reply, board_dir, repo) -> dict:
    """型（写しの r2.design の schema）→ 作業ツリー（役を起こす前の写しと同じ）。通れば design.json。{ok, reason, design_file}"""
    def run():
        b = entry.open_board(pathlib.Path(board_dir))
        moved = entry.tree_moved_since(b, SNAPSHOT_NAME, pathlib.Path(repo))
        if moved:
            raise Reject(entry.READONLY_MOVED + moved)
        accept.type_errors(reply, accept.role_schema(NODE), "独立設計の返答")
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
