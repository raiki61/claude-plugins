"""works の層と依存の向き（裁定 R59）の検査。この試験が層の正本（README の「層と依存の向き」は要約）。

層（下から。上の層は下の層だけを知ってよい）:
- L0 写し: .shared/core/graphloops・.shared/core/scripts（works の物を何も知らない）
- L1 基礎: tree_run・script_io・node_marker
- L2 包み: adapter・ticket・claude-adapter・record-read.py・no-post-bin/works-gh
- L3 盤面と受け付け: board・accept・policy・entry（共有の部分）・halt（止め札）・refix・recount・rolekit（役の節の共通の口）・protect（守りのファイル）
- L4 ブロックの模块: 持ち主のブロックが 1 つの模块（core に在る物は MOD の表・<blk>/lib/*.py）
- L5 ブロック: blk-*/（scripts など）
- L6 ラインの模块: 持ち主のラインが 1 つの模块（<line>/lib/*.py・<line>/*.py・MOD の表で 6 の物・PARTS の名前）
- L7 ライン: <line>/（nodes.json を持つフォルダ。scripts など）
- L8 dev・L9 tests: pack の全部を知ってよい。pack の中の誰からも参照されない（ここでは走査しない）

縛る決まり（§7 の 1〜8。破れの語は各行の頭。直し方の案内は VIOLATIONS・MARKERS）:
1. up: import（遅らせた import・importlib.import_module("定数")・`import X as Y` の別名を含む）は同じ層か下の層へ。
   ブロックの YAML は include を持たず、ラインの include は在るブロックだけを指す（yaml-include）
2. owner: L4 の模块を使ってよいのは持ち主のブロックと L6・L7 だけ。L6 の模块は持ち主のラインだけ。
   private: 別の模块から `from X import _名` で私的な名前を借りない（L0 の写しからは除く。`X._名` の属性の形は見ない）
3. name: L1〜L5 のコードの文字列の定数（docstring を除く。字のまま一致か、パスの形の文字列の 1 区切り。f-string・%・.format の
   破片は穴と端の / を落としてから区切る）に、ラインの名前・ラインの include の id・自分以外の blk-* の名前が現れない
   （L6・L7 はほかのラインの名前）。docstring・コメント・YAML・md の散文の blk-<名> は test_block_blind が見る
4. cycle: works の模块の import のグラフに輪が無い
5. script: */scripts/*.py はどれも自分の YAML の `script: <名>` の節で、ほかから import されない。未配線の節は PLANNED_SCRIPTS に載せる
6. dynamic: importlib.import_module・__import__ の引数は文字列の定数だけ。runpy・exec・eval は使わない
   （spec_from_file_location で場所から読むのは許す）
7. packref: pack（L1〜L7）のコードの文字列が dev/・tests/・docs/ を指さない（/ と join の項の "dev" なども）
8. 許可表: 今ある破れは KNOWN に載せ、減らす方向にしか変えない。直ったのに行が残っていれば赤（PLANNED_* も同じ）。
   KNOWN に置けるのは破れの組（VIOLATIONS の語）だけ。層・置き場・表が決まっていない印（MARKERS の語: 解けない import の
   unresolved・層の無い core の模块の unassigned・名前の重なりの shadow・置き場の外の unplaced など）は KNOWN に在っても赤
   （置けると模块ごと検査から外れ、中の破れが隠れる）

L0 は import だけを見る（バイト単位の写しなので、文字列の決まりは当てない。写しの一致は test_core_copy・test_core_verbatim）。
"""
import ast
import pathlib
import re
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

# core の模块の層と持ち主（.shared/core からの相対。.py は除く）。表に無い core の模块は unassigned で赤
MOD = {
    "tree_run": (1, None), "script_io": (1, None), "node_marker": (1, None), "versions": (1, None),
    "answer": (1, None),      # 関所の文の答えの行（起動の殻が env に置いた頭で組む。works の物を何も知らない）
    "hold_lock": (1, None),   # 殻が開いた fd を flock で取る（dev/lib.sh の続き中の印。works の物を何も知らない）
    "changemap": (1, None),   # attention の変更の地図の部品の写し（COPIED_FROM.changemap。works の物を何も知らない）
    "copyledger": (1, None),  # 写しの台帳の読み口（写し直しの道具と写しの一致の試験が読む。works の物を何も知らない）
    "claude_auth": (1, None),  # 本流 scripts/claude_auth.py の写し（shared-copies.py が同一を縛る。works の物を何も知らない）
    "auth_launch": (1, None),  # 殻の認証の起こし役（claude_auth の写しだけを import する。works の物を何も知らない）
    "forge": (1, None),       # 対象の remote が forge（PR を持つホスト。GitHub）かを git だけで決める（ghreads と entry・report が読む。works の物を何も知らない）
    "ghreads": (1, None),     # 依頼のファイルの形（findings の配列か {findings, pr, issue}）を解く 1 か所（works の物を何も知らない）
    "flow_adapter": (1, None),  # 流れの道具（Archon）に触る口（依頼 239。scope・置き場・入力・聞き直しの口。works の物を何も知らない）
    "unittrees": (1, None),   # 修正の単位ごとの小さい git worktree（切る・差分・当てる・片付け。works の物を何も知らない）
    "graphmap": (1, None),    # 工程の地図（Archon の YAML から全体のグラフと節の居場所を組んで描く。works の物を何も知らない）
    "adapter": (2, None), "ticket": (2, None), "claude-adapter": (2, None), "record-read": (2, None),
    "record-write": (2, None),   # 包みが足す書き込みの記録のフック（writes が読む記録を書く）
    "record-output": (2, None),  # 包みが足す下請けの返答の記録のフック（diverted が読む記録を書く）
    "replycontract": (2, None),  # 包みの旗 text-reply の返答の契約（返答の形・本文の読みと型の検査・同じ会話での出し直し。adapter が使う）
    "no-post-bin/works-gh": (2, None),
    "fixshape": (2, None),    # 修正の形の語と盤面からの 1 つの読み口（包みが読む。標準ライブラリだけ）
    "fixture": (3, None),     # 固定材料（h-fix の盤面の写しと取り込み。entry と境の節が使う。entry・board を import しない）
    "board": (3, None), "accept": (3, None), "policy": (3, None), "entry": (3, None), "halt": (3, None),
    "refix": (3, None), "recount": (3, None), "reads": (3, None), "leftovers": (3, None), "rolekit": (3, None), "report": (3, None),
    "impact": (3, None),      # 変更の周りの地図（役が共有して読む。地図はまだどのブロックにも配線しない。libdocs が import の読み取りを使う）
    "libdocs": (3, None),     # ライブラリの今の文書（Context7）を支度の節が引いて指示書に貼る（blk-fix・blk-plan が使う）
    "protect": (3, None),
    "writes": (3, None),      # 書き込みの出どころの突き合わせ（blk-fix・blk-refix の受け付けと報告が使う）
    "outpurpose": (3, None),  # 判定が凍結した目的の外として単位にしなかった材料の所見の欄・確かめ・控え・次の run の依頼の行（accept の役の型・blk-judge・報告が使う）
    "querytest": (3, None),   # 判定・再審の class_query の問いを例（hits・misses）で試す（accept の役の型・blk-judge・rejudge・境の節が使う）
    "conflict": (3, None),    # 食い違いの申し出の控え・名指しの確かめ・写しの RL の _owed_units の差し替え（blk-fix と境の節と報告が使う）
    "design": (3, None),      # 修正の前に先に作る独立設計（r2.design）の支度・受け付け・控え・盤面への渡し（blk-plan・blk-eyes・境の節が使う）
    "diverted": (3, None),    # 下請けの会話が親の返答の道具に書いた返答の拾い口（局所レビューの受け付けが /code-review の所見を戻し、報告が読む）
    "lens": (3, None),        # 修正の後のレンズの控え（盤面の今の周の lens.json。レンズのブロックが書き、差分の審査の支度と報告が読む）
    "structmark": (3, None),  # 構造のブロックの出口の控え（盤面の根の structure-state.json。境の節が書き、blk-plan・報告・最後の関所が読む）
    "rulebook": (3, None),    # 書く役の決まりの正本（writerules/common.md）と、節に切る・穴を埋める・形を描く口（blk-fix・blk-refix が使う）
    "gatemarks": (3, None),   # 修正前の関所の項目の決め手・写しの RL の _plan_gate_items の差し替え（accept の役の型・blk-plan・境の節・報告が使う）
    "spseam": (3, None),      # 借りる superpowers の写しの固定の照合・錨・穴の埋め・出口の語の対応（rolekit と同じく .shared/borrow を読む。toolset と、節を載せるブロックが共有する）
    "seat": (3, None),        # 借りたスキルの座（修正の形 g3 の時だけ、節を役の指示書に載せる文を組む。blk-fix の支度が使う）
    "planmarks": (3, None),   # 修正案の項目の works の欄（受け入れのテスト・書き換える既存のテスト・整えの申告）の型・検査・盤面の控え（accept の役の型・blk-plan・conflict・blk-fix が使う）
    "converge": (3, None),    # 事前審査の壁打ち（依頼 231）の決まり・往復の控え・役の型の欄・関所と報告の文（標準ライブラリだけ。gatemarks・修正案のブロックが使う）
    "replan": (3, None),      # 同じ run の中の案の直し（依頼 226）: 待つ fix_plan_item の行を締めて ask_human の道に載せる（境の節 h-rejudge と報告が使う）
    "holeties": (3, None),    # 差分の審査の穴の枝の名札（純粋な関数。refix が集め、手直しの支度・報告・最後の関所の文が読む）
    "deltamarks": (3, None),  # 差分の審査の返答の準拠と品質の 2 判定の欄の型・検査・盤面の外の控え（accept の役の型・refix の審査の受け付けが使う）
    "scopes": (3, None),      # 部品の置き場と宣言（依頼 239。manifest の読み・公開の名・持ち主・scope の登録と集め）
    "ci_role": (4, "blk-ci"), "purpose": (4, "blk-purpose"), "rejudge": (4, "blk-rejudge"), "prcheck": (4, "blk-pr"),
    "premises": (4, "blk-premises"),
}
# 共有の模块の中に居る上の層の名前（割る前の当座。V2）: 模块 → (層, 持ち主, 名前の組)
PARTS = {
    "entry": (6, "darkfactory", frozenset({"check_inputs", "start", "_drain", "_pr_go", "resume_after_ci",
                                           "declared_adapter", "LINE", "ORIGIN"})),
}
L0_TOPS = frozenset({"engine", "rules", "graphs"})   # 写しの graphloops の頭の名（core の模块が sys.path に足す）
OUTSIDE = frozenset({"dev", "tests", "docs"})        # pack に入らないフォルダ（dev/lib.sh が除く物）

# ラインが配線する予定の include の id（線 A の仕様 2 節。T17 で darkfactory.yaml に入る）。YAML に入ったら消す
PLANNED_INCLUDE_IDS = frozenset()
# 未配線の節のスクリプト（T17 で YAML の script: に入る）。配線したら消す
PLANNED_SCRIPTS = frozenset({"blk-structure/scripts/measure.py"})   # 実測の単体 CLI（段 B の口）。段 A は blk-structure.yaml の節が子で起こす

# 破れ（元と先の組）の語と、直し方の案内。KNOWN に置けるのはこの語の行だけ
VIOLATIONS = {
    "up": "上向きの依存。先を下の層へ移すか、上の層から引数で渡す形にする。当座に許すなら V 番号つきで KNOWN に足す",
    "owner": "持ち主の外から使っている。共有の層へ移すか、持ち主の中に閉じる。当座に許すなら V 番号つきで KNOWN に足す",
    "private": "別の模块の私的な名前（_名）を借りている。公開の名前にする。当座に許すなら V 番号つきで KNOWN に足す",
    "name": "下の層がライン・include の id・ほかのブロックの名前を書いている。入力か引数で受ける形にする。"
            "当座に許すなら V 番号つきで KNOWN に足す",
    "cycle": "import の輪。どれか 1 本の辺を消す。当座に許すなら V 番号つきで KNOWN に足す",
    "script": "scripts/ の .py が YAML の節でない（か、ほかから import されている）。節なら YAML の script: に配線するか、"
              "配線の予定なら PLANNED_SCRIPTS に足す。模块なら lib/ か core へ移す。当座に許すなら V 番号つきで KNOWN に足す",
    "dynamic": "定数でない動的な読み込み（import_module・__import__・runpy・exec・eval）。定数の import にする。"
               "当座に許すなら V 番号つきで KNOWN に足す",
    "packref": "pack が dev/・tests/・docs/ を指している（pack の写しに入らない）。参照を消す。当座に許すなら V 番号つきで KNOWN に足す",
    "yaml-include": "ブロックが include を持つか、ラインが無いブロックを include している。YAML を直す。"
                    "当座に許すなら V 番号つきで KNOWN に足す",
}
# 層・置き場・表が決まっていない印。KNOWN には置けない（置くと模块ごと検査から外れ、中の破れが隠れる。審査 Important 1）
MARKERS = {
    "unassigned": "core の模块の層が決まっていない。MOD に (層, 持ち主) を足す（KNOWN には置けない）",
    "unresolved": "import の先が解けない。先の模块の層が決まっていない（core なら MOD に足す・ブロックかラインの物なら lib/ に置く）"
                  "か、名前の誤りか、相対の import（KNOWN には置けない）",
    "unparsable": "Python として読めない。直す（KNOWN には置けない）",
    "shadow": "core と lib で模块の名前が重なる（sys.path の順で取り違える）。どちらかの名前を変える（KNOWN には置けない）",
    "unplaced": "層の決まった置き場（.shared/core・blk-*/・nodes.json を持つラインのフォルダ）の外の .py。置き場へ移す"
                "（KNOWN には置けない）",
    "mod-gone": "MOD の行に当たる模块が core に無い。MOD から消す（KNOWN には置けない）",
    "planned-wired": "YAML に配線済み。PLANNED_SCRIPTS か PLANNED_INCLUDE_IDS から消す（KNOWN には置けない）",
    "planned-gone": "ファイルが無い。PLANNED_SCRIPTS から消す（KNOWN には置けない）",
}

# 今ある破れ（減らす方向にだけ変える）。値は structure-survey の V 番号
KNOWN = {
    "name entry:LINE 'darkfactory'": "V2",
    "name entry:ORIGIN 'works/darkfactory'": "V2",
    "name ci_role:PROMPTS 'blk-ci'": "V8",
    "up ci_role -> entry.resume_after_ci": "V10",
    "up ci_role -> entry.declared_adapter": "V10",   # 調べ（survey）に無かった同じ形の辺（start の控えを blk-ci が読む）
    "up entry -> prcheck": "V11",
    "cycle entry prcheck": "V11",
    "private purpose -> accept": "V12",
}


# ---------------------------------------------------------------- 走査
class Unit:
    """走査する 1 本のファイル: id（報告の名）・層・持ち主・import の名（無ければ None）"""

    def __init__(self, path, uid, layer, owner, name=None):
        self.path, self.id, self.layer, self.owner, self.name = path, uid, layer, owner, name


def _is_python(p: pathlib.Path) -> bool:
    if p.suffix == ".py":
        return True
    if p.suffix or not p.is_file():
        return False
    try:
        head = p.read_bytes()[:64]
    except OSError:
        return False
    return head.startswith(b"#!") and b"python" in head.split(b"\n", 1)[0]


class Pack:
    """root（works/）を読んだ結果: units・findings"""

    def __init__(self, root: pathlib.Path, mod=MOD, parts=PARTS, planned_scripts=PLANNED_SCRIPTS,
                 planned_ids=PLANNED_INCLUDE_IDS):
        self.root = pathlib.Path(root)
        self.mod, self.parts = mod, parts
        self.planned_scripts, self.planned_ids = planned_scripts, planned_ids
        self.core = self.root / ".shared" / "core"
        self.lines = sorted(p.parent.name for p in self.root.glob("*/nodes.json"))
        self.blocks = sorted(p.name for p in self.root.glob("blk-*") if p.is_dir())
        self.found = {}   # 破れの文 → 在り処（file:line）
        self.units = []
        self._collect()
        self.include_ids = self._include_ids()
        self.named = {}   # import の名 → Unit（core と lib の模块）
        for u in self.units:
            if u.name is None or u.layer == 0:
                continue
            if u.name in self.named:
                self._hit(f"shadow {u.name}", f"{self.named[u.name].id} と {u.id}")
            self.named.setdefault(u.name, u)
        self.edges = {}   # (元の id, 先の id) → 在り処
        for u in self.units:
            self._scan(u)
        self._cycles()
        self._scripts()
        self._yaml_includes()

    def _hit(self, key, where):
        self.found.setdefault(key, where)

    # -- どのファイルがどの層か
    def _collect(self):
        for p in sorted(self.core.rglob("*")):
            rel = p.relative_to(self.core)
            if "__pycache__" in rel.parts or not p.is_file() or not _is_python(p):
                continue
            if rel.parts[0] in ("graphloops", "scripts"):
                self.units.append(Unit(p, f"L0:{rel}", 0, None))
                continue
            key = str(rel.with_suffix("")) if p.suffix == ".py" else str(rel)
            name = rel.stem if p.suffix == ".py" and len(rel.parts) == 1 and "-" not in rel.stem else None
            if key not in self.mod:
                self._hit(f"unassigned {key}", str(p.relative_to(self.root)))
                continue
            layer, owner = self.mod[key]
            self.units.append(Unit(p, key, layer, owner, name))
        for key in sorted(set(self.mod) - {u.id for u in self.units}):
            self._hit(f"mod-gone {key}", "MOD")
        placed = {*self.blocks, *self.lines, *OUTSIDE, ".git"}
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if (rel.parts[0] in placed or rel.parts[:2] == (".shared", "core") or "__pycache__" in rel.parts
                    or not p.is_file() or not _is_python(p)):
                continue
            self._hit(f"unplaced {rel}", str(rel))
        for kind, names, mod_layer, node_layer in (("blk", self.blocks, 4, 5), ("line", self.lines, 6, 7)):
            for owner in names:
                for p in sorted((self.root / owner).rglob("*.py")):
                    rel = p.relative_to(self.root / owner)
                    if "__pycache__" in rel.parts:
                        continue
                    is_mod = rel.parts[0] == "lib" or (kind == "line" and len(rel.parts) == 1)
                    uid = f"{owner}/{rel.with_suffix('')}"
                    self.units.append(Unit(p, uid, mod_layer if is_mod else node_layer, owner,
                                           rel.stem if is_mod else None))

    def _include_ids(self):
        ids = set()
        for line in self.lines:
            doc = _yaml(self.root / line / f"{line}.yaml")
            ids |= {n["id"] for n in _nodes(doc) if "include" in n and "id" in n}
        return ids

    # -- import と文字列
    def _resolve(self, u: Unit, top: str):
        """import の頭の名 top を Unit にする。標準ライブラリは None、写しは "L0"、解けなければ False"""
        if top in sys.stdlib_module_names or top == "__future__":
            return None
        if top in L0_TOPS:
            return "L0"
        t = self.named.get(top)
        if u.layer == 0:
            return t or None   # 写しが works の模块を引けば上向き。ほかの名は写しの中の物
        if t is not None and t.path.parent == self.core:
            return t   # 節のスクリプト・lib は core を sys.path の 0 番に足す（core が勝つ）
        sib = u.path.parent / f"{top}.py"
        if sib.is_file() and sib != u.path:
            return next((v for v in self.units if v.path == sib), False)
        if sib == u.path:
            return u
        return self.named.get(top, False)

    def _scan(self, u: Unit):
        rel = u.path.relative_to(self.root)
        try:
            tree = ast.parse(u.path.read_text(encoding="utf-8"), filename=str(rel))
        except (SyntaxError, UnicodeDecodeError) as e:
            self._hit(f"unparsable {u.id}", f"{rel}: {e}")
            return
        docs = _docstrings(tree)
        alias = {a.asname: a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names if a.asname}
        pieces, operands = _pieces_and_operands(tree)
        for node, scope in _walk(tree):
            at = f"{rel}:{getattr(node, 'lineno', '?')}"
            for top, attr in _imports(node):
                if top is None:
                    self._hit(f"dynamic {u.id}:{scope}", at)
                    continue
                self._edge(u, top, attr, at)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                mod = alias.get(node.value.id, node.value.id)
                if mod in self.parts:
                    self._part(u, mod, node.attr, at)
            if (u.layer and isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docs):
                self._strings(u, node, scope, at, id(node) in pieces)
                if id(node) in operands and node.value in OUTSIDE:
                    self._hit(f"packref {u.id}:{scope} {node.value!r}", at)

    def _edge(self, u, name, attrs, at):
        if name.startswith("."):   # 相対の import: 写しの package の中は写しの物。works は package を持たないので先を決められない
            if u.layer:
                self._hit(f"unresolved {u.id} {name}", at)
            return
        top = name.split(".")[0]
        t = self._resolve(u, top)
        if t is None or t == "L0":
            return
        if t is False:
            self._hit(f"unresolved {u.id} {name}", at)
            return
        if t is u:
            return
        self.edges.setdefault((u.id, t.id), at)
        if t.layer > u.layer:
            self._hit(f"up {u.id} -> {t.id}", at)
        elif t.layer in (4, 5, 6, 7) and t.owner != u.owner and not (t.layer in (4, 5) and u.layer in (6, 7)):
            self._hit(f"owner {u.id} -> {t.id}", at)
        for a in attrs:
            if t.name in self.parts:
                self._part(u, t.name, a, at)
            if a.startswith("_") and not a.startswith("__") and u.layer:
                self._hit(f"private {u.id} -> {t.id}", at)

    def _part(self, u, mod, attr, at):
        _layer, owner, names = self.parts[mod]
        if attr in names and u.name != mod and u.owner != owner and u.layer:
            self._hit(f"up {u.id} -> {mod}.{attr}", at)

    def _strings(self, u, node, scope, at, piece=False):
        v = node.value
        # パスの形（英数字・_・.・-・/ だけで / を含む相対の物）は区切りごとにも見る。/dev/null のような絶対のパスは見ない。
        # f-string・%・.format で組む文字列の破片は、穴（%s・{}）と端の / を落としてから見る（f"{PACK}/blk-x/prompts" など）
        w = re.sub(r"%[-#0 +]*\d*[a-z]|\{[^}]*\}", "", v).strip("/") if piece else v
        segs = w.split("/") if re.fullmatch(r"[A-Za-z0-9_.\-][A-Za-z0-9_.\-/]*", w) and "/" in w else []
        words = {v, *segs}
        if u.layer <= 5:
            # 自分のブロックの名前を書いてよいのはブロックのフォルダの中だけ（core に在る L4 の模块は持ち主の名前も書かない）
            here = u.owner if u.path.is_relative_to(self.root / str(u.owner)) else None
            bad = set(self.lines) | self.include_ids | self.planned_ids | (set(self.blocks) - {here})
        else:
            bad = set(self.lines) - {u.owner}
        if words & bad:
            self._hit(f"name {u.id}:{scope} {v!r}", at)
        if set(segs[:-1]) & OUTSIDE:
            self._hit(f"packref {u.id}:{scope} {v!r}", at)

    # -- 輪・節のスクリプト・YAML の include
    def _cycles(self):
        graph = {}
        for a, b in self.edges:
            graph.setdefault(a, set()).add(b)
        for comp in _sccs(graph):
            if len(comp) > 1:
                self._hit("cycle " + " ".join(sorted(comp)), "")

    def _scripts(self):
        wired = set()
        for owner in (*self.blocks, *self.lines):
            doc = _yaml(self.root / owner / f"{owner}.yaml")
            names = {n["script"] for n in _nodes(doc) if isinstance(n.get("script"), str)}
            wired |= {f"{owner}/scripts/{s}.py" for s in names}
        have = {str(p.relative_to(self.root)) for p in self.root.glob("*/scripts/*.py")}
        imported = {f"{b}.py" for a, b in self.edges if a != b} & have   # 節は import されない（されるなら模块）
        for s in sorted((have - wired - self.planned_scripts) | imported):
            self._hit(f"script {s}", s)
        for s in sorted(self.planned_scripts & wired):
            self._hit(f"planned-wired {s}", "PLANNED_SCRIPTS")
        for s in sorted(self.planned_scripts - have):
            self._hit(f"planned-gone {s}", "PLANNED_SCRIPTS")
        for i in sorted(self.planned_ids & self.include_ids):
            self._hit(f"planned-wired {i}", "PLANNED_INCLUDE_IDS")

    def _yaml_includes(self):
        for owner in self.blocks:
            for n in _nodes(_yaml(self.root / owner / f"{owner}.yaml")):
                if "include" in n:
                    self._hit(f"yaml-include {owner} -> {n['include']}", f"{owner}/{owner}.yaml")
        for line in self.lines:
            for n in _nodes(_yaml(self.root / line / f"{line}.yaml")):
                if "include" in n and n["include"] not in self.blocks:
                    self._hit(f"yaml-include {line} -> {n['include']}", f"{line}/{line}.yaml")


def _yaml(p: pathlib.Path):
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else None


def _nodes(doc):
    """YAML の中の節（id か script か include を持つ dict）を入れ子（loop の中）まで全部"""
    if isinstance(doc, dict):
        if any(k in doc for k in ("script", "include")) or ("id" in doc and "nodes" not in doc):
            yield doc
        for v in doc.values():
            yield from _nodes(v)
    elif isinstance(doc, list):
        for v in doc:
            yield from _nodes(v)


def _docstrings(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            b = n.body[0]
            if isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant) and isinstance(b.value.value, str):
                out.add(id(b.value))
    return out


def _pieces_and_operands(tree):
    """(書式で組む文字列の破片の定数の id, パスを組む演算の項の定数の id)。破片は f-string の中・% の左・.format の受け手。
    項は / の両辺と join・joinpath の引数"""
    pieces, operands = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.JoinedStr):
            pieces |= {id(v) for v in n.values if isinstance(v, ast.Constant)}
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod) and isinstance(n.left, ast.Constant):
            pieces.add(id(n.left))
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            operands |= {id(n.left), id(n.right)}
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == "format" and isinstance(n.func.value, ast.Constant):
                pieces.add(id(n.func.value))
            if n.func.attr in ("join", "joinpath"):
                operands |= {id(a) for a in n.args}
    return pieces, operands


def _walk(tree):
    """(節, 在る所の名) を全部。在る所は囲む def・class の名（入れ子は . で繋ぐ）、一番上の代入はその左辺、ほかは <module>"""
    def go(node, scope):
        yield node, scope
        for child in ast.iter_child_nodes(node):
            s = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                s = child.name if scope == "<module>" else f"{scope}.{child.name}"
            elif scope == "<module>" and isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                s = names[0] if names else scope
            yield from go(child, s)
    yield from go(tree, "<module>")


def _imports(node):
    """節が import なら (名, 引いた属性の組) を返す。引数が定数でない動的な import は (None, ())"""
    if isinstance(node, ast.Import):
        return [(a.name, ()) for a in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [(node.module, tuple(a.name for a in node.names))]
    if isinstance(node, ast.ImportFrom):   # 相対の import
        return [("." * node.level + (node.module or ",".join(a.name for a in node.names)), ())]
    if isinstance(node, ast.Call):
        f = node.func
        fname = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        if fname in ("run_path", "run_module", "exec", "eval"):
            return [(None, ())]
        if fname in ("import_module", "__import__"):
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return [(arg.value, ())]
            return [(None, ())]
    return []


def _sccs(graph):
    """Tarjan の強連結成分"""
    index, low, stack, on, out, n = {}, {}, [], set(), [], [0]

    def visit(v):
        index[v] = low[v] = n[0]
        n[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = set()
            while True:
                w = stack.pop()
                on.discard(w)
                comp.add(w)
                if w == v:
                    break
            out.append(comp)
    for v in sorted(graph):
        if v not in index:
            visit(v)
    return out


def kind(key: str) -> str:
    return key.split(" ", 1)[0]


def verdict(pack: Pack, known=KNOWN):
    """(新しい破れ, 直ったのに残っている KNOWN の行, KNOWN に置けない行)。印の行（MARKERS）と知らない語の行は KNOWN に
    在っても許さない（新しい破れにも残る）"""
    refused = sorted(k for k in known if kind(k) not in VIOLATIONS)
    new = sorted(k for k in pack.found if k not in known or kind(k) not in VIOLATIONS)
    stale = sorted(k for k in known if k not in pack.found and kind(k) in VIOLATIONS)
    return new, stale, refused


def report(pack: Pack, known=KNOWN) -> str:
    """失敗の文（揃っていれば ""）。節は空行で分け、どの節も 1 行目が直し方で、2 行目から行"""
    new, stale, refused = verdict(pack, known)
    out = []
    if refused:
        out.append("KNOWN に置けない印の行（KNOWN から消し、各行の語の直し方に従う）:\n"
                   + "\n".join(f"  {k}" for k in refused))
    for kd in [*VIOLATIONS, *MARKERS, *sorted({kind(k) for k in new} - set(VIOLATIONS) - set(MARKERS))]:
        rows = [k for k in new if kind(k) == kd]
        if rows:
            advice = VIOLATIONS.get(kd) or MARKERS.get(kd) or "知らない語"
            out.append(f"{kd}: {advice}:\n" + "\n".join(f"  {k}  [{pack.found[k]}]" for k in rows))
    if stale:
        out.append("直ったのに KNOWN に残っている行（消す。許可表は減らす方向にだけ変える）:\n"
                   + "\n".join(f"  {k}  ({known[k]})" for k in stale))
    return "\n\n".join(out)


# ---------------------------------------------------------------- 試験
class LayersCase(unittest.TestCase):
    def test_tree_matches_known(self):
        pack = Pack(ROOT)
        self.assertGreaterEqual(len(pack.units), 40, "走査したファイルが少なすぎる（数え間違いで空を見て緑にしない）")
        msg = report(pack)
        self.assertFalse(msg, "\n" + msg)

    def test_script_io_does_not_reach_up_to_conflict(self):
        """下の層の script_io は、start の控えを読む conflict（上の層）を import しない（KNOWN で許すのでなく依存を移す）"""
        pack = Pack(ROOT)
        self.assertEqual([k for k in pack.found if k.startswith("up script_io -> ")], [])

    def test_known_rows_name_a_violation_number(self):
        for k, v in KNOWN.items():
            with self.subTest(row=k):
                self.assertRegex(v, r"^[VW]\d+$")
                self.assertIn(k.split(" ", 1)[0], VIOLATIONS, "KNOWN に置けるのは破れの組だけ（層・置き場の印は置けない）")

    def test_tree_has_lines_blocks_and_ids(self):
        pack = Pack(ROOT)
        self.assertTrue(pack.lines and pack.blocks and pack.include_ids, (pack.lines, pack.blocks, pack.include_ids))


class CheckerCase(unittest.TestCase):
    """走査そのものの検査: 使い捨ての pack に破れを 1 つずつ植えて、決まりの語で捕まえること"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        core = self.root / ".shared" / "core"
        (core / "graphloops" / "engine").mkdir(parents=True)
        (core / "graphloops" / "engine" / "util.py").write_text("import json\n")
        self.put(".shared/core/base.py", "import json\n")
        self.put(".shared/core/shared.py", "import base\nfrom engine.util import x\n")
        self.put(".shared/core/own.py", "import shared\n")
        self.put("blk-a/blk-a.yaml", "name: a\nnodes:\n  - id: s\n    script: s\n")
        self.put("blk-a/scripts/s.py", "import own\nimport shared\n")
        self.put("blk-b/blk-b.yaml", "name: b\nnodes: []\n")
        self.put("ln/nodes.json", "{}")
        self.put("ln/ln.yaml", "name: ln\nnodes:\n  - id: doing\n    include: blk-a\n")
        self.put("ln/lib/lmod.py", "import own\n")
        self.mod = {"base": (1, None), "shared": (3, None), "own": (4, "blk-a")}

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def pack(self, **kw):
        kw = {"mod": self.mod, "parts": {}, "planned_scripts": frozenset(), "planned_ids": frozenset(), **kw}
        return Pack(self.root, **kw)

    def found(self, known=(), **kw):
        return verdict(self.pack(**kw), {k: "V0" for k in known})

    def test_clean_pack_is_green(self):
        self.assertEqual(self.found(), ([], [], []))

    def test_upward_import(self):
        self.put(".shared/core/base.py", "def f():\n    import shared\n")
        self.assertIn("up base -> shared", self.found()[0])

    def test_dynamic_import_constant_and_not(self):
        self.put(".shared/core/base.py", "import importlib\nimportlib.import_module('own')\n"
                                        "def g(n):\n    return importlib.import_module(n)\n")
        new = self.found()[0]
        self.assertIn("up base -> own", new)
        self.assertIn("dynamic base:g", new)

    def test_owner(self):
        self.put("blk-b/scripts/t.py", "import own\n")
        self.put("blk-b/blk-b.yaml", "name: b\nnodes:\n  - id: t\n    script: t\n")
        self.assertEqual(self.found()[0], ["owner blk-b/scripts/t -> own"])

    def test_names_line_include_and_other_block(self):
        self.put(".shared/core/shared.py", '"""darkfactory ln doing は docstring なので数えない"""\n'
                                          "LINE = 'ln'\nIDS = ('doing',)\ndef f(p='x/blk-b/y'):\n    return p\n")
        self.put("blk-a/scripts/s.py", "OWN = 'blk-a'\nMSG = 'ln の中で落ちた'\n")   # 自分のフォルダの中は自分の名を書いてよい
        self.put(".shared/core/own.py", "import shared\nP = 'blk-a'\n")   # core に在る L4 は持ち主の名も書かない
        new = self.found()[0]
        self.assertEqual(new, ["name own:P 'blk-a'", "name shared:IDS 'doing'", "name shared:LINE 'ln'",
                               "name shared:f 'x/blk-b/y'"])

    def test_cycle_and_private(self):
        self.put(".shared/core/base.py", "import json\n")
        self.put(".shared/core/other.py", "import shared\nfrom shared import _p\n")
        self.put(".shared/core/shared.py", "def f():\n    import other\n")
        self.mod["other"] = (3, None)
        new = self.found()[0]
        self.assertIn("cycle other shared", new)
        self.assertIn("private other -> shared", new)

    def test_script_not_a_node_and_packref(self):
        self.put("blk-a/scripts/helper.py", "import json\nP = 'tests/boards'\n")
        new = self.found()[0]
        self.assertIn("script blk-a/scripts/helper.py", new)
        self.assertIn("packref blk-a/scripts/helper:P 'tests/boards'", new)

    def test_unassigned_unresolved_and_block_include(self):
        self.put(".shared/core/stray.py", "import json\n")
        self.put("blk-a/scripts/s.py", "import nowhere\n")
        self.put("blk-b/blk-b.yaml", "name: b\nnodes:\n  - id: x\n    include: blk-a\n")
        new = self.found()[0]
        self.assertIn("unassigned stray", new)
        self.assertIn("unresolved blk-a/scripts/s nowhere", new)
        self.assertIn("yaml-include blk-b -> blk-a", new)

    def test_mod_row_without_module_is_red(self):
        self.mod["moved"] = (3, None)
        self.assertEqual(self.found()[0], ["mod-gone moved"])

    def test_known_row_left_after_fix_is_red(self):
        self.assertEqual(self.found(known=["up base -> shared"]), ([], ["up base -> shared"], []))

    # -- 印（層・置き場が決まっていない）の行は KNOWN に置けない（審査 Important 1）
    def test_marker_row_in_known_is_refused(self):
        self.put(".shared/core/stray.py", "import json\n")
        self.put("blk-a/scripts/s.py", "import nowhere\n")
        new, stale, refused = self.found(known=["unassigned stray", "unresolved blk-a/scripts/s nowhere"])
        self.assertEqual(new, ["unassigned stray", "unresolved blk-a/scripts/s nowhere"])   # 許可表に在っても赤のまま
        self.assertEqual(refused, ["unassigned stray", "unresolved blk-a/scripts/s nowhere"])
        self.assertEqual(stale, [])

    def test_unknown_kind_in_known_is_refused(self):
        self.assertEqual(self.found(known=["whatever a -> b"])[2], ["whatever a -> b"])

    def test_messages_name_the_fix(self):
        self.put(".shared/core/stray.py", "import json\n")
        self.put(".shared/core/base.py", "import shared\n")
        self.put("blk-a/scripts/helper.py", "import json\n")
        self.put("blk-a/scripts/s.py", "import own\nimport nowhere\n")
        text = report(self.pack(), {"unassigned stray": "V0"})
        sections = {sec.splitlines()[1].split()[0]: sec for sec in text.split("\n\n") if len(sec.splitlines()) > 1}
        self.assertIn("MOD に", sections["unassigned"].splitlines()[0])
        self.assertNotIn("KNOWN に足す", sections["unassigned"].splitlines()[0])
        self.assertIn("PLANNED_SCRIPTS", sections["script"].splitlines()[0])
        self.assertIn("MOD", sections["unresolved"].splitlines()[0])
        self.assertIn("KNOWN", sections["up"].splitlines()[0])
        self.assertIn("KNOWN に置けない印", text)
        self.assertIn("unassigned stray", text.split("KNOWN に置けない印")[1])

    # -- 審査の Minor（抜け道を塞ぐ）
    def test_formatted_path_pieces(self):
        self.put(".shared/core/shared.py", "import os\nX = 1\nP = f'{X}/blk-b/prompts'\nQ = '%s/blk-b/q' % X\n"
                                          "R = '{}/blk-b/r'.format(X)\nD = os.path.join(X, 'dev')\n")
        new = self.found()[0]
        self.assertEqual(new, ["name shared:P '/blk-b/prompts'", "name shared:Q '%s/blk-b/q'",
                               "name shared:R '{}/blk-b/r'", "packref shared:D 'dev'"])

    def test_relative_alias_and_runpy(self):
        self.put(".shared/core/base.py", "from . import x\nimport runpy\nrunpy.run_path('p')\n")
        self.put("blk-a/scripts/s.py", "import shared as sh\nsh.start()\n")
        new = self.found(parts={"shared": (6, "ln", frozenset({"start"}))})[0]
        self.assertIn("unresolved base .x", new)
        self.assertIn("dynamic base:<module>", new)
        self.assertIn("up blk-a/scripts/s -> shared.start", new)

    def test_imported_script_is_not_a_node_even_if_planned(self):
        self.put("blk-a/scripts/p.py", "import json\n")
        self.put("blk-a/scripts/s.py", "import own\nimport p\n")
        self.assertEqual(self.found(planned_scripts=frozenset({"blk-a/scripts/p.py"}))[0], ["script blk-a/scripts/p.py"])

    def test_planned_wired_gone_and_ids(self):
        new = self.found(planned_scripts=frozenset({"blk-a/scripts/s.py", "blk-a/scripts/gone.py"}),
                         planned_ids=frozenset({"doing"}))[0]
        self.assertEqual(new, ["planned-gone blk-a/scripts/gone.py", "planned-wired blk-a/scripts/s.py",
                               "planned-wired doing"])

    def test_shadow_unplaced_and_line_include_to_missing_block(self):
        self.put("ln/lib/own.py", "import json\n")
        self.put("skills/x.py", "import json\n")
        self.put("ln/ln.yaml", "name: ln\nnodes:\n  - id: doing\n    include: blk-a\n  - id: z\n    include: blk-z\n")
        new = self.found()[0]
        self.assertIn("shadow own", new)
        self.assertIn("unplaced skills/x.py", new)
        self.assertIn("yaml-include ln -> blk-z", new)


if __name__ == "__main__":
    unittest.main()
