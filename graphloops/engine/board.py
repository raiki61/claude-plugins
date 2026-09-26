"""盤面——どの節が終わったか・何周目か・いま走らせてよいか。ディスク（state.json / record.json）が正本。"""
import json
import os
import pathlib

from .rules import load_rules, registry, validator_module
from . import util
from .util import BoardConflict, Reject, die, get_path, read_json, write_json, now
from .schema import load_graph, validate_schema
from .validator import run_validator
from .render import Renderer


def empty_round(n):
    return {"round": n, "done": {}, "na": {}, "skipped": {}, "stopped": {}, "empty": [], "instances": {}, "item_counts": {}}


# 節の条件（cond）は rules の名前付きの関数（CONDS）で、graph には名前だけを書く。関数は読む欄を宣言し（cond_reads）、
# engine は宣言した欄だけが見える入れ物（CondView）を渡して（真偽, 理由の文）を受け取る。以前は graph の JSON の上の
# 小さな言語（all / any / not / path+op+default / builtin）を engine が解釈し、graphcheck が同じ言語を検査していた
# ——綴り違い・default の読み落とし・prev. の検査漏れのたびに検査を継ぎ足し、loop.・record. の葉は最後まで検査の外だった。
# 条件の文脈で読める前置き。Board.cond はこの表から条件の文脈を組み（engine の ctx から引き、cur だけ足す）、graphcheck が
# import して宣言の頭がこの中に在るかを見る（写しを作らない）。cur.<節> は「今の周にその節が出した出力」（out.<節> は周を問わない
# 最新、prev.<節> は前の周までの最新）。照らす宣言を持たない前置き（inputs・run・thickness・item）は条件から読ませない
COND_NODE_HEADS = ("out", "prev", "cur")   # 下に <節>.<欄> を持つ前置き（graphcheck が節の schema で照らす）
COND_HEADS = ("record", *COND_NODE_HEADS, "round", "rd", "loop")
_MISSING = object()


class CondView:
    """条件の関数に渡す入れ物。**宣言した欄だけが見える。**

    `v(path, default)` で読む。宣言した path そのものか、その下（宣言 `loop.last_material` は
    `loop.last_material.x.status` を読める）だけ通し、宣言の外は die。解決できない path は default を
    渡していれば default、無ければ die——偽に倒すと綴り違いが『条件が成り立たない』に化け、走らなかった節の
    素材に事実と逆の理由が書かれたまま収束まで通る（実測: cond の path を 1 文字変えても graphcheck は exit 0、
    回すと gate_efficacy が『検証ゲートを新設していない』で not_applicable になった）。
    `validator` は検証器の module（状態ではなくコード）——読むときに初めて引く（検証器の無い run では、読んだ条件だけが
    Reject で落ちる。Reject は loop.py が制御された拒否として出す）。`unevaluable(trigger, why)` は『この条件は測れなかった』の痕跡を
    周ごとに 1 行だけ state に残す口（偽を返すのは同じでも、測れなかった事実を残す）。

    内部の欄は下線 2 本の名前（名前の変換が掛かる）に置く: 条件の関数が `v._ctx` のような自然な綴りで文脈を直に読むと
    AttributeError で落ち、宣言の検査をすり抜けない。Python は属性を封じられないので、`getattr(v, "_CondView__ctx")`・
    `vars(v)` のような意図した迂回までは止めない（ruff の SLF001 も属性の綴りしか見ない）"""

    def __init__(self, name, reads, ctx, validator=None, state=None, overlay=None):
        self.__name, self.__reads, self.__ctx = name, tuple(reads), ctx
        self.__validator = validator     # module か、module を返す引き手（Board.cond は引き手を渡す）
        self.__state = state
        self.__overlay = overlay or {}   # {path: 値}——その path（と下の欄）だけ、盤面の値の代わりにこの値を見せる

    def __call__(self, path, default=_MISSING):
        if not Renderer({}, self.__reads).allowed(path):   # 前置き一致は Renderer が正本（pointers.widen と同じ）
            die(f"cond '{self.__name}' が宣言していない欄 '{path}' を読んだ（宣言: {list(self.__reads)}）"
                "——読む欄は cond_reads に書け（graphcheck が宣言を前の節の出力と突き合わせる）")
        # 重ね書きした path の下は重ね書きの値だけで解決する（引けなければ default か die——盤面の本物の値へ落とさない）
        over = [(k, val) for k, val in self.__overlay.items() if path == k or path.startswith(k + ".")]
        try:
            if over:
                k, val = over[0]
                return val if path == k else get_path(val, path[len(k) + 1:])
            return get_path(self.__ctx, path)
        except KeyError:
            if default is _MISSING:
                die(f"cond '{self.__name}' の欄 '{path}' が解決できない（綴り違いか、その欄をまだ誰も書いていない。"
                    "意図して未書き込みを見るなら default を渡せ）")
            return default

    @property
    def validator(self):
        if callable(self.__validator):
            self.__validator = self.__validator()
        return self.__validator

    def unevaluable(self, trigger, why):
        """条件の部品 trigger が測れなかった痕跡（同じ周に同じ trigger は 1 行だけ——1 回の next で条件は何度も評価される）"""
        if self.__state is None:
            return
        rnd, seen = self.__state.get("round"), self.__state.setdefault("unevaluable", [])
        if not any(u["trigger"] == trigger and u["round"] == rnd for u in seen):
            seen.append({"trigger": trigger, "round": rnd, "why": why})


def run_cond(name, fn, ctx, validator=None, state=None, overlay=None):
    """条件の関数 fn を、宣言した欄だけが見える入れ物で呼ぶ唯一の口 ——(真偽, 理由の文)。
    Board.cond と台本の真偽表が同じ 1 本を通る（宣言の有無・返りの形の検査を台本の側で写さない）"""
    reads = getattr(fn, "reads", None)
    if not isinstance(reads, tuple):
        die(f"cond '{name}' が読む欄を宣言していない（rules で cond_reads(...) を付けよ）")
    r = fn(CondView(name, reads, ctx, validator, state, overlay))
    if not (isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], bool) and isinstance(r[1], str) and r[1].strip()):
        die(f"cond '{name}' の返りが（真偽, 理由の文）でない: {r!r}")
    return r


def refuse_expression_conds(graph_path, nodes):
    """**条件を式（JSON の木）で書いていた版の graph を指す盤面は開かない。** 盤面は graph のパスを持つので、
    旧い engine の置き場で init した run を条件を関数に移した engine で開くと、旧い rules の読み込みか Board.cond の
    『CONDS に無い』で止まり、graph の書き手向けの案内になる。load_rules より前に形式で見分け、開く engine を名指して止める"""
    old = sorted(nid for nid, n in nodes.items() for k in ("cond", "applies_cond") if k in n and not isinstance(n[k], str))
    if not old:
        return
    loop = pathlib.Path(graph_path).resolve().parent.parent / "scripts" / "loop.py"
    where = f"graph と同じ置き場の engine（{loop}）で続けるか" if loop.is_file() else "この graph を作った版の engine で続けるか"
    die(f"この盤面の graph（{graph_path}）は条件を式で書いていた版の形式で（節 {', '.join(old[:3])}{' ほか' if len(old) > 3 else ''}）、"
        f"条件を rules の関数に移したこの engine では開けない。{where}、この engine で init し直せ（盤面は書き換えていない）")


def node_of(path, nodes):
    """<節>.<欄> の <節> を、節名に点があっても最長一致で取る（無ければ None）。"""
    best = None
    for nid in nodes:
        if path == nid or path.startswith(nid + "."):
            if best is None or len(nid) > len(best):
                best = nid
    return best


class Board:
    def __init__(self, d):
        self.dir = pathlib.Path(d)
        self.state = read_json(self.dir / "state.json")
        # **この run の対象リポジトリを git に固定する。** init が記録した inputs.cwd を使う——以前は git を
        # プロセスの cwd で実行していたので、`--dir` を明示すると run と対象リポジトリの結び付きが外れた
        # （実測 2026-09-13: 別リポジトリの cwd から done を実行して record.base が別リポジトリの HEAD になった）
        util.GIT_CWD = (self.state.get("inputs") or {}).get("cwd")
        self.seen_rev = self.state.get("rev", 0)  # 読んだ時点の版。save がこれと突き合わせる
        self.halted_at_read = bool(self.state.get("halted"))  # 読んだ時点で止めた run か（save が見る）
        self.record = read_json(self.dir / "record.json")
        self.graph, why = load_graph(self.state["graph"])
        if why:
            die(why)
        self.nodes = self.graph["nodes"]
        refuse_expression_conds(self.state["graph"], self.nodes)
        self.rules = load_rules(self.state["graph"], self.graph)

    # -- 保存と痕跡
    allow_halted = False   # 止めた run（halted）の盤面に書いてよい呼び出しの印（手当ての patch・記録の仕上げ・launch の締め）

    def save(self):
        """**読んでから書くまでに別のプロセスが盤面を進めていたら、上書きせず落とす。** 周の途中の問いで止めた run（halted）
        への書き込みも、ここで拒む（add・skip・thicken・launch・done・relaunch の全部がこの 1 か所を通る。印の立つ呼び出しだけ通す）。

        state も record も丸ごと読んで丸ごと書き戻すので、2 つの回す側が同じ run に付くと後勝ちで
        先の完了が消える。実測: 3 本の done を同時に呼んだところ 3 本とも exit 0・「受け付けた」を
        返しながら、1 本ぶんの instance が pending のまま・記録への書き込みも state.outputs の項目も
        残らなかった。手順書は「ready の全部を同時に始めてよい」と書いていて done を直列にしろとは
        書いていないので、塞ぐのは呼ぶ側の作法ではなくここ。

        record を先に書くのは、版の繰り上げを commit の印にするため——先に state を書くと、記録の
        書き込みが落ちた run を次のプロセスが「進んだ」と読む。
        """
        if self.halted_at_read and not self.allow_halted:
            raise Reject(f"この run は周の途中の問いで止めた（halted: {(self.state.get('halted') or {}).get('node')}）——盤面は書かない"
                         "（止めた run の記録は進めない。手当ては loop.py patch）")
        cur = read_json(self.dir / "state.json").get("rev", 0)
        if cur != self.seen_rev:
            # **名乗る範囲は保護できる範囲まで。** 守っているのは盤面の 2 本（state.json / record.json）で、
            # cmd_done はここへ来るまでに out/r<N>/<節>.json・save_text_as の本文・trace.jsonl を既に書いている
            # ——「この呼び出しは何も書いていない」と書いていたとき、読み手には副作用が無いと読めた（実測 2026-09-13）
            raise BoardConflict(f"盤面が読んだ後に進んでいる（読んだ版 {self.seen_rev} ／ いまの版 {cur}）——別のプロセスが"
                                "同じ run を回している。**盤面（state.json / record.json）は書いていない**が、out/ には"
                                "この呼び出しの書き込みが残りうる（trace.jsonl の行は、保存まで控えた呼び出しなら書いていない）。"
                                "1 つの盤面に 2 人で付くな（続けるなら next からやり直せ）")
        self.seen_rev += 1
        self.state["rev"] = self.seen_rev
        self._loop_drift()
        write_json(self.dir / "record.json", self.record)
        write_json(self.dir / "state.json", self.state)
        # 保存まで控えていた trace の行（_board_update が当て直す間は書かない——当て直しのたびに行が重なる）
        for row in self.held_trace or []:
            self._write_trace(row)
        self.held_trace = None

    def _loop_drift(self):
        """盤面の loop を graph の state_schema（在れば）で照らし、外れを state.loop_drift に積む——**痕跡だけで止めない**
        （走っている run・今の rules が書かない鍵を持つ旧い盤面を開けて進めるため。人の決定 2026-09-26）。同じ周の同じ外れは
        1 行だけ（save は 1 回の呼び出しで何度も通る）。照らし自体が落ちても保存は続け、落ちたことを同じ欄に残す。
        記録と報告へは validator の TRACES が写す"""
        sch = self.graph.get("state_schema")
        if not isinstance(sch, dict):
            return
        try:
            errs = validate_schema(self.state.get("loop") or {}, sch, "loop")
        except Exception as e:  # noqa: BLE001 — 照らせなかったことも痕跡にする（黙って 0 件にしない）
            errs = [f"loop を state_schema で照らせなかった（{type(e).__name__}: {e}）"]
        rows = self.state.setdefault("loop_drift", [])
        for e in errs:
            if not any(r.get("round") == self.state.get("round") and r.get("error") == e for r in rows):
                rows.append({"round": self.state.get("round"), "error": e})
                self.trace("loop_drift", round=self.state.get("round"), error=e)

    def run_validator(self, target=None):
        """検証器を回す（rules からも呼ぶ。INJECT の道具と同じ公開面に揃える——無名関数を属性に束ねない）。"""
        return run_validator(self, target)

    held_trace = None   # list なら trace の行を save まで控える（commands._board_update が当て直しの間だけ立てる）

    def trace(self, op, **kw):
        row = {"t": now(), "op": op, **kw}
        if self.held_trace is not None:
            self.held_trace.append(row)
        else:
            self._write_trace(row)

    def _write_trace(self, row):
        with open(self.dir / "trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # -- graph が宣言する語（engine は持たない）
    @property
    def plugin(self):
        return self.graph.get("plugin")

    @property
    def runners(self):
        return self.graph.get("runners", [])

    @property
    def tiers(self):
        return self.graph.get("thickness", {}).get("tiers") or []

    def is_runner(self, n):
        # 役の名前は engine に書かない——graph の runners が正本（util.py の宣言）。以前は "skill" をここで足していたので、
        # 回す側の集合が engine（runners ∪ {skill}）と graphcheck（runners だけ）でずれ、柵の対象が 1 語ぶん狭かった
        return n["run_by"] in self.runners

    # -- 周
    @property
    def round(self):
        return self.state["round"]

    @property
    def rd(self):
        return self.state["rounds"][-1]

    @property
    def loop_state(self):
        """rules が自分の都合で持つ状態の置き場。engine は中身を解さず、形を graph の state_schema で照らして外れを痕跡に残すだけ（save）。"""
        return self.state.setdefault("loop", {})

    def new_round(self):
        self.state["round"] += 1
        self.state["rounds"].append(empty_round(self.state["round"]))

    # -- 節の状態
    def rewind(self, nids, by):
        """節を今の周の待ちに戻す（rules が『この節の出力はもう古い』と決めたときの engine の口）——{節: {記録の欄: 外した値}}。

        節の状態の持ち方は engine だけが知るので、戻し方はここ 1 か所に置く。**外すのは今の周にその節が出した物だけ**:
        instance と返答の置き場（同じ iid・同じ out_path で出直すので、残すと新しい返答を書かずに打った done が古い返答で
        通る。消さずに .stale-r<周> へ退ける）・今の周の出力の指し（out.<節>）・set の writes が書いた記録の欄。append・
        merge_by_id と rules の独自の op が書いた物は外さない（前の周の分も積んでいるか、意味を engine が知らない）——外さなかった
        事実を痕跡に残す。条件外（na）の節は印だけを外して条件を測り直させ、前の周の出力には触らない。once の節は done_ever も外す。
        **機械の節（driver）は戻さない**"""
        rd, removed = self.rd, {}
        for nid in nids:
            n = self.nodes[nid]
            if n.get("run_by") == "driver":
                die(f"rewind: 機械の節 {nid} は戻せない（rules の欠陥）")
            ran = nid in rd["done"] or nid in rd["skipped"] or nid in rd["empty"]
            for box in ("done", "na", "skipped"):
                rd[box].pop(nid, None)
            if nid in rd["empty"]:
                rd["empty"].remove(nid)
            if n.get("once"):
                self.state["done_ever"].pop(nid, None)
            got, kept = {}, []
            if ran:
                for iid in [i for i, x in rd["instances"].items() if x["node"] == nid]:
                    op = pathlib.Path(rd["instances"].pop(iid).get("out_path") or "")
                    if op.name and op.is_file():
                        op.replace(op.with_name(op.name + f".stale-r{self.round}"))
                if (self.state["outputs"].get(nid) or {}).get("round") == self.round:
                    self.state["outputs"].pop(nid)
                for w in n.get("writes", []):
                    if w.get("op") != "set" or not w.get("to"):
                        kept.append(f"{w.get('op')}:{w.get('to', '')}")
                        continue
                    head, _, key = w["to"].rpartition(".")
                    try:
                        parent = get_path(self.record, head) if head else self.record
                    except KeyError:
                        continue   # まだ書かれていない欄
                    if isinstance(parent, dict) and key in parent:
                        got[w["to"]] = parent.pop(key)
            removed[nid] = got
            self.trace("rewind", node=nid, by=by, ran=ran, removed=sorted(got), kept=kept)
        return removed

    def node_state(self, nid):
        """done / skipped / stopped / empty / na は依存を満たす。pending は満たさない。
        stopped は人が止めた（loop.py stop）ので走らせない節——省いた（skipped）と別の印で持つ（報告の『省略した機構』に混ぜない）。

        **once の節は done_ever に載っていれば done を返す**——done_ever は『もう出さない節』の集合で、
        終わり方（done か skipped か）は持たない。周をまたぐと done と skipped の区別は消える（素材の
        帰結は fill_materials が rd の skipped から書くので正しい）。
        """
        rd = self.rd
        if nid in rd["done"]:
            return "done"
        if nid in rd["na"]:
            return "na"
        if nid in rd["skipped"]:
            return "skipped"
        if nid in rd.get("stopped", {}):   # 止める口より前に作った周は欄を持たない
            return "stopped"
        if nid in rd["empty"]:
            return "empty"
        if self.nodes[nid].get("once") and nid in self.state["done_ever"]:
            return "done"
        return "pending"

    def deps_ok(self, nid, which="deps"):
        deps = self.nodes[nid].get(which, self.nodes[nid].get("deps", []))
        return all(self.node_state(d) != "pending" for d in deps)

    def deps_met(self, nid):
        """節の項目を出してよい依存が揃っているか——節の deps か、扇の節なら instance_deps（項目を先に出す pipeline。
        全部の checker を待たない）。**出す時（advance）と受け付ける時（done）が同じ 1 本を使う**——出した後に graph が変わっても、
        今の graph で出せない返答は受け付けない。扇の項目が節の deps より先に通るのは、今の graph でも先に出す設計どおり"""
        n = self.nodes[nid]
        return self.deps_ok(nid) or ("fan_out" in n and "instance_deps" in n and self.deps_ok(nid, "instance_deps"))

    def applicable(self, nid):
        """依存が揃った節に、この周で走らせるかを聞く。走らせないなら理由を返す。"""
        n = self.nodes[nid]
        tiers = n.get("active_in")
        if tiers and self.state["thickness"] not in tiers:
            return f"active_in: {self.state['thickness']} 段では走らせない（{'/'.join(tiers)} だけ）"
        if n.get("cond") is not None:
            ok, why = self.cond(n["cond"])
            if not ok:
                return f"cond {n['cond']}: {why}"
        return None

    def cond(self, name, overlay=None):
        """rules の条件の関数 name（CONDS の名前）を、宣言した欄だけが見える入れ物で呼ぶ ——(真偽, 理由の文)。
        engine は中身を知らない（名前で呼び、宣言した欄を渡し、返りの形だけ見る）。overlay（{path: 値}）は rules が
        『この欄が違っていたら』を測るための重ね書き（例: 入口の印を外した文脈）——盤面は書き換えない"""
        fn = registry(self.rules, "CONDS").get(name)
        if fn is None:
            die(f"cond '{name}' が rules の CONDS に無い（graph の cond には関数の名前だけを書く）")
        full = {**self.ctx(), "cur": {nid: self.output_of_round(nid, self.round) for nid, info in self.state["outputs"].items()
                                     if info.get("round") == self.round}}
        ctx = {h: full[h] for h in COND_HEADS}
        return run_cond(name, fn, ctx, lambda: validator_module(self), self.state, overlay)

    # -- プロンプトと条件の文脈
    def output_of_round(self, nid, rnd):
        """節 nid の、周 rnd に出した出力（その周に出していなければ None）。

        outputs() は周を落として各節の最新を返すので、optional の節を省いた周に前の周の値を『この周の値』と読む。
        """
        info = self.state["outputs"].get(nid)
        if not info or info.get("round") != rnd:
            return None
        return self.read_out(info["file"], board_relative=True)

    def latest_output(self, nid):
        """節 nid の最新の出力（周を問わない）。once の節のように、前の周の値を読むのが正しい所だけで使う
        ——今の周の値を読むなら output_of_round"""
        info = self.state["outputs"].get(nid)
        return self.read_out(info["file"], board_relative=True) if info else None

    def outputs(self, before_round=None):
        """節ごとの最新の出力。before_round を渡すと、それより前の周の出力だけ（prev）。

        ファイル 1 本につき 1 度しか読まない（同じ Board の間）。条件の関数を呼ぶたびに ctx を組み直すので、
        memo が無いと 1 回の next で同じ本文を何度も通る（実測 2026-09-12: 出力 29 件・463 KB の周で
        read_json が 1,404 回）。盤面はこのプロセスの中では engine しか書かないので、読み直す必要が無い。
        """
        out = {}
        for nid, info in self.state["outputs"].items():
            if before_round is not None and info["round"] >= before_round:
                continue
            out[nid] = self.read_out(info["file"], board_relative=True)
        return out

    def _out_path(self, stored):
        """instance の `output_file` を実パスに直す。**推し量らず、実在する方を採る。**

        いまは書く側（commands.py / advance.py）が盤面からの相対で書く。**この run より前に作られた盤面は
        `--dir` をそのまま前に付けた綴りで持っている**ので、そのまま前置きすると `<dir>/<dir>/…` に繋がる
        （実測 2026-09-13: 最終報告の ref:raw がその形で exit 2）。

        **見分けを文字列の前方一致でやらない。** `str(p).startswith(str(self.dir))` は区切りを見ないので
        `o` と `outputs`・`run1` と `run10` を取り違えるうえ、**絶対の `--dir` で旧盤面を開くと旧い相対の
        綴りが前方一致にも絶対にも当たらず、当の `<dir>/<dir>/…` に戻る**（実測 2026-09-14: 旧盤面
        20260912-214912 の output_file は `.git/graphloops/…` の相対で、絶対の --dir で開くと二重になる）。
        移行の下駄は推測でなく**実在**で決められる——どちらの綴りで置かれているかはディスクが知っている。
        既存の run が全部終わったら消してよい（消す条件: 下の 2 通り目が 1 度も選ばれないこと）。
        """
        p = pathlib.Path(stored)
        if p.is_absolute():
            return str(p)
        joined = self.dir / p            # いまの綴り: 盤面からの相対
        if joined.exists() or not p.exists():
            return str(joined)           # 無い時も盤面の下として返し、読む側に「無い」と言わせる
        return str(p)                    # 旧い綴り: --dir をそのまま前に付けた形

    def read_out(self, path, *, board_relative=False):
        """出力ファイルを 1 度だけ読む（同じ Board の間）。

        **どちらの綴りで持っているかは、渡す側が知っている**——`state["outputs"]["file"]` は盤面からの相対
        （commands.py が `f.relative_to(b.dir)` で書く）、instance の `output_file` は `--dir` をそのまま
        前に付けた綴り（同じ行の `str(f)`）。ここで `is_absolute` を見て「絶対でなければ盤面からの相対」と
        推し量ると、`--dir` を相対で渡した run では output_file が盤面の下にもう一度繋がる
        （実測 2026-09-13: 最終報告の `ref:raw` が `<dir>/<dir>/out/r1/p1.hygiene.json` を読みに行って exit 2。
        5 周のうち ref:raw を使う節がこの 1 本だけだったので、最後の節まで出なかった）。
        **綴りの正本は書いた側にしか無いので、引数で受け取る。**

        鍵は abspath——綴りが違っても同じファイルなら memo を共有する（実測 2026-09-12: 揃えないと重複 314 回）。
        resolve() は毎回 realpath を引くので使わない（実測: 1 回の next で 7,640 回）。
        """
        cache = self.__dict__.setdefault("_out_cache", {})
        if board_relative:
            path = self._out_path(path)
        key = os.path.normpath(os.path.abspath(path))
        if key not in cache:
            cache[key] = read_json(key)
        return cache[key]

    def node_of(self, path):
        return node_of(path, self.nodes)

    def ref(self, path):
        """ref:<path> の中身——[(見出し, 置き場のファイル, 値)]。record・out.<節>・prev.<節>・raw だけ。
        out.<節> は**その節が最後に走った周**の instance 全部（穴埋めの {{out.<節>}} と同じ意味——once の節や
        今の周に走らなかった節は前の周の出力を返す。周で切ると p2.history が p0.purpose を読めない）。
        prev.<節> は『その節が最後に走った前の周』の instance 全部。"""
        if path == "record" or path.startswith("record."):
            return [(path, str(self.dir / "record.json"), get_path({"record": self.record}, path))]
        if path == "raw":
            nodes = set(self.graph.get("raw_for_report", []))
            return [(f"r{rd['round']}/{iid}", self._out_path(inst["output_file"]), self.read_out(inst["output_file"], board_relative=True))
                    for rd in self.state["rounds"] for iid, inst in rd["instances"].items()
                    if inst["status"] == "done" and inst["node"] in nodes and inst.get("output_file")]
        if path.startswith("out.") or path.startswith("prev."):
            prev = path.startswith("prev.")
            nid = self.node_of(path[5:] if prev else path[4:])
            if nid is None:
                raise KeyError(f"{path}: 節が無い")
            # out も prev も「その節が最後に走った周」だけ——穴埋めの {{out.<節>}} / {{prev.<節>}} と同じ意味に揃える。
            # 以前は out が今の周だけを見ており、同じ接頭が穴と ref: で別の範囲を指していた（実測: 2 周目に na の節の
            # 1 周目の出力が穴では貼られ ref: では出なかった）。周で切らないのは、once の節を後の周が読むため。
            rounds = [rd for rd in self.state["rounds"] if rd["round"] < self.round] if prev else self.state["rounds"]
            ran = [rd for rd in rounds if any(i["status"] == "done" and i["node"] == nid for i in rd["instances"].values())]
            rounds = ran[-1:]
            return [(f"r{rd['round']}/{iid}", self._out_path(inst["output_file"]), self.read_out(inst["output_file"], board_relative=True))
                    for rd in rounds for iid, inst in rd["instances"].items()
                    if inst["status"] == "done" and inst["node"] == nid and inst.get("output_file")]
        raise KeyError(f"{path}: ref: にできるのは record・out.<節>・prev.<節>・raw だけ")

    def ctx(self, item=None):
        return {
            "record": self.record, "inputs": self.state["inputs"], "item": item or {}, "out": self.outputs(),
            "prev": self.outputs(before_round=self.round),
            "thickness": self.state["thickness"], "round": self.round, "rd": self.rd, "loop": self.loop_state,
            "run": {"id": self.state["run_id"], "dir": str(self.dir), "loop": self.state["loop_name"]},
            "validator": self.validator_tables(),
        }

    def porcelain(self):
        """作業ツリーの写し（**この盤面＝この 1 プロセスの中では 1 回だけ取る**）。

        `next` と `done` は別プロセスなので、P1 の前後の突合は元から別の写しを見る——memo は前後を
        混ぜない。混ぜるのは同じ next の中で何度も引く経路（周の頭の基準と、守る役の instance ごと）だけで、
        engine は盤面の下にしか書かないので同じ走査の中で結果は変わらない。
        以前は engine が `emit_instance` の中だけで memo を持ち、rules は素の `porcelain()` を呼んでいた
        ——周が変わる next で同じ `git status` が 2 回走っていた（実測 2026-09-13: 1 回 15 ミリ秒）。
        """
        if "_porcelain" not in self.__dict__:
            from .util import porcelain as _p
            self.__dict__["_porcelain"] = _p()
        return self.__dict__["_porcelain"]

    def validator_tables(self):
        """検証器が「プロンプトに貼る用」として宣言した表（`PROMPT_TABLES`）。**写させないための口。**

        役に渡す散文へ語彙の表を手で写すと、正本を直した周に写しだけが古くなり、しかも役は写しの方を読む
        （実測 2026-09-13: p2.diagnose.md の写しから問いの種類 3 つの origin の要求が落ちていた。graph は
        同じ表について「ここに写さない。手順書も列挙を持たない」と宣言していた面）。

        **engine は中身を知らない**——検証器が名前を決め、プロンプトが `{{validator.<名前>}}` で引く。
        検証器が無い／宣言していない run では空の dict——貼れないことは穴埋めの KeyError で分かる
        （静かに空文字で埋めない）。
        """
        cache = self.__dict__.get("_vtables")
        if cache is None:
            from .rules import Reject, validator_module
            try:
                cache = dict(getattr(validator_module(self), "PROMPT_TABLES", {}) or {})
            except (Reject, OSError, ImportError):
                cache = {}
            self.__dict__["_vtables"] = cache
        return cache
