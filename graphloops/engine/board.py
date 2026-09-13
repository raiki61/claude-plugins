"""盤面——どの節が終わったか・何周目か・いま走らせてよいか。ディスク（state.json / record.json）が正本。"""
import json
import os
import pathlib

from .rules import load_rules, registry
from . import util
from .util import die, get_path, read_json, write_json, now
from .validator import run_validator


def empty_round(n):
    return {"round": n, "done": {}, "na": {}, "skipped": {}, "empty": [], "instances": {}, "item_counts": {}}


# cond の op → その op に**要る鍵**。op の一覧と必須鍵を別々に持っていたとき、any_field_eq の field 欠落と
# in の value 欠落が graphcheck を 0 件で通り、実行時に素の KeyError か恒偽になった。1 本の表を engine が持ち、
# eval_cond と graphcheck の check_cond が同じ物を読む（写しを作らない）
COND_OP_KEYS = {"eq": ("value",), "ne": ("value",), "gt": ("value",), "lt": ("value",),
                "nonempty": (), "empty": (), "in": ("value",), "any_field_eq": ("value", "field")}
COND_OPS = tuple(COND_OP_KEYS)  # 使える op の一覧（die の文面で「使えるのは」を出すため。照合は COND_OP_KEYS 側）
COND_KEYS = frozenset({"all", "any", "not", "builtin", "path", "op", "value", "default", "field"})  # eval_cond が読む鍵。graphcheck が import


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
        self.record = read_json(self.dir / "record.json")
        self.graph = read_json(self.state["graph"])
        self.nodes = self.graph["nodes"]
        self.rules = load_rules(self.state["graph"], self.graph)

    # -- 保存と痕跡
    def save(self):
        """**読んでから書くまでに別のプロセスが盤面を進めていたら、上書きせず落とす。**

        state も record も丸ごと読んで丸ごと書き戻すので、2 つの回す側が同じ run に付くと後勝ちで
        先の完了が消える。実測: 3 本の done を同時に呼んだところ 3 本とも exit 0・「受け付けた」を
        返しながら、1 本ぶんの instance が pending のまま・記録への書き込みも state.outputs の項目も
        残らなかった。手順書は「ready の全部を同時に始めてよい」と書いていて done を直列にしろとは
        書いていないので、塞ぐのは呼ぶ側の作法ではなくここ。

        record を先に書くのは、版の繰り上げを commit の印にするため——先に state を書くと、記録の
        書き込みが落ちた run を次のプロセスが「進んだ」と読む。
        """
        cur = read_json(self.dir / "state.json").get("rev", 0)
        if cur != self.seen_rev:
            # **名乗る範囲は保護できる範囲まで。** 守っているのは盤面の 2 本（state.json / record.json）で、
            # cmd_done はここへ来るまでに out/r<N>/<節>.json・save_text_as の本文・trace.jsonl を既に書いている
            # ——「この呼び出しは何も書いていない」と書いていたとき、読み手には副作用が無いと読めた（実測 2026-09-13）
            die(f"盤面が読んだ後に進んでいる（読んだ版 {self.seen_rev} ／ いまの版 {cur}）——別のプロセスが"
                "同じ run を回している。**盤面（state.json / record.json）は書いていない**が、out/ と trace.jsonl には"
                "この呼び出しの書き込みが残っている。1 つの盤面に 2 人で付くな（続けるなら next からやり直せ）")
        self.seen_rev += 1
        self.state["rev"] = self.seen_rev
        write_json(self.dir / "record.json", self.record)
        write_json(self.dir / "state.json", self.state)

    def run_validator(self, target=None):
        """検証器を回す（rules からも呼ぶ。INJECT の道具と同じ公開面に揃える——無名関数を属性に束ねない）。"""
        return run_validator(self, target)

    def trace(self, op, **kw):
        with open(self.dir / "trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": now(), "op": op, **kw}, ensure_ascii=False) + "\n")

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
        """rules が自分の都合で持つ状態の置き場（engine は中を見ない）。"""
        return self.state.setdefault("loop", {})

    def new_round(self):
        self.state["round"] += 1
        self.state["rounds"].append(empty_round(self.state["round"]))

    # -- 節の状態
    def node_state(self, nid):
        """done / skipped / empty / na は依存を満たす。pending は満たさない。

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
        if nid in rd["empty"]:
            return "empty"
        if self.nodes[nid].get("once") and nid in self.state["done_ever"]:
            return "done"
        return "pending"

    def deps_ok(self, nid, which="deps"):
        deps = self.nodes[nid].get(which, self.nodes[nid].get("deps", []))
        return all(self.node_state(d) != "pending" for d in deps)

    def applicable(self, nid):
        """依存が揃った節に、この周で走らせるかを聞く。走らせないなら理由を返す。"""
        n = self.nodes[nid]
        tiers = n.get("active_in")
        if tiers and self.state["thickness"] not in tiers:
            return f"active_in: {self.state['thickness']} 段では走らせない（{'/'.join(tiers)} だけ）"
        cond = n.get("cond")
        if cond is not None and not self.eval_cond(cond):
            return f"cond: {n.get('when', json.dumps(cond, ensure_ascii=False))} が成り立たない"
        return None

    def eval_cond(self, c):
        if "all" in c:
            return all(self.eval_cond(x) for x in c["all"])
        if "any" in c:
            return any(self.eval_cond(x) for x in c["any"])
        if "not" in c:
            return not self.eval_cond(c["not"])
        if "builtin" in c:
            fn = registry(self.rules, "CONDS").get(c["builtin"])
            if not fn:
                die(f"cond.builtin '{c['builtin']}' が rules に無い")
            return bool(fn(self))
        # 解決できない path は die。偽に倒すと graph の綴り違い・欄の改名が『条件が成り立たない』に化け、
        # 走らなかった節の素材に事実と逆の理由が書かれたまま収束まで通る（実測: cond の path を 1 文字変えても
        # graphcheck は exit 0、回すと gate_efficacy が『検証ゲートを新設していない』で not_applicable になった）。
        # 未書き込みの欄を意図して見る節は cond に default を書く。
        try:
            v = get_path(self.ctx(), c["path"])
        except KeyError:
            if "default" not in c:
                die(f"cond の path '{c['path']}' が解決できない（綴り違いか、その欄をまだ誰も書いていない。"
                    f"意図して未書き込みを見るなら cond に \"default\" を書け）")
            v = c["default"]
        op, want = c.get("op", "eq"), c.get("value")
        if op not in COND_OP_KEYS:
            die(f"cond の op が不明: {op}（使えるのは {'/'.join(COND_OPS)}）")
        missing = [k for k in COND_OP_KEYS[op] if k not in c]
        if missing:
            die(f"cond の op '{op}' に要る鍵が無い: {missing}（graphcheck が静的に落とすのと同じ表）")
        if op == "eq":
            return v == want
        if op == "ne":
            return v != want
        if op == "gt":
            return isinstance(v, (int, float)) and v > want
        if op == "lt":
            return isinstance(v, (int, float)) and v < want
        if op == "nonempty":
            return bool(v)
        if op == "empty":
            return not v
        if op == "in":
            return v in (want or [])
        if op == "any_field_eq":
            return isinstance(v, list) and any(isinstance(x, dict) and x.get(c["field"]) == want for x in v)
        # **最後の腕に op 名を書く。** 無印の return を受け皿にしていたとき、表（COND_OP_KEYS）に op を足して
        # この連鎖に足し忘れると、例外でなく any_field_eq の意味で静かに評価された（表は 8 個・連鎖は 7 個を
        # 明示）。:162-165 が path の解決失敗を偽でなく die にしたのと同じ理由——「知らない」を「成り立たない」に
        # 倒すと、綴り違いが条件の不成立に化けて収束まで通る。表と連鎖のずれは、ここで初めて音が出る
        die(f"cond の op '{op}' は表（COND_OP_KEYS）に在るが eval_cond の分岐に無い——engine の表と実装がずれている")

    # -- プロンプトと条件の文脈
    def outputs(self, before_round=None):
        """節ごとの最新の出力。before_round を渡すと、それより前の周の出力だけ（prev）。

        ファイル 1 本につき 1 度しか読まない（同じ Board の間）。cond の葉ごとに ctx を組み直すので、
        memo が無いと 1 回の next で同じ本文を何度も通る（実測 2026-09-12: 出力 29 件・463 KB の周で
        read_json が 1,404 回）。盤面はこのプロセスの中では engine しか書かないので、読み直す必要が無い。
        """
        out = {}
        for nid, info in self.state["outputs"].items():
            if before_round is not None and info["round"] >= before_round:
                continue
            out[nid] = self.read_out(info["file"], board_relative=True)
        return out

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
        if board_relative and not os.path.isabs(path):
            path = os.path.join(str(self.dir), path)
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
            return [(f"r{rd['round']}/{iid}", inst["output_file"], self.read_out(inst["output_file"]))
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
            return [(f"r{rd['round']}/{iid}", inst["output_file"], self.read_out(inst["output_file"]))
                    for rd in rounds for iid, inst in rd["instances"].items()
                    if inst["status"] == "done" and inst["node"] == nid and inst.get("output_file")]
        raise KeyError(f"{path}: ref: にできるのは record・out.<節>・prev.<節>・raw だけ")

    def ctx(self, item=None):
        return {
            "record": self.record, "inputs": self.state["inputs"], "item": item or {}, "out": self.outputs(),
            "prev": self.outputs(before_round=self.round),
            "thickness": self.state["thickness"], "round": self.round, "rd": self.rd, "loop": self.loop_state,
            "run": {"id": self.state["run_id"], "dir": str(self.dir), "loop": self.state["loop_name"]},
        }
