"""履歴から作る読み取り専用の値（hist.<名>）。

周をまたぐ値の正本は履歴——閉じた周の記録（rounds/round-<N>.json）と周ごとの節の出力（out/r<N>/）と周の rd——で、
hist はそれを読む時に作る射影（イベントソーシングの projection。Temporal の Query と同じく状態を見るだけで書き換えない）。
値の定義は rules が名前付きの関数（HIST）で持ち、engine は名前を知らない（ループ固有の知識を持たない）。関数は読む物を
hist_reads で宣言し、engine は宣言した物だけが見える入れ物（History）を渡す。盤面を直接読む人と AI のために、engine は
保存のたびに全部の値を控え（盤面の hist.json。正本でない印つき）に書き出す——控えを読んで盤面へ戻す口は無い。
"""
import copy
import os

from .util import die, get_path, read_json, safe_name, write_json
from .schema import validate_schema

HIST_FILE = "hist.json"
# 値が無い（その周にはまだ作れない。例: 1 周目の前の周の値）。穴は ABSENT で、条件の default で受ける
HIST_ABSENT = object()
LOOKUP_HEADS = ("loop", "record", "inputs")   # hist の関数が宣言して読める盤面の頭（graphcheck も同じ表を引く）


def _rd_of(board, n):
    return next((r for r in board.state["rounds"] if r.get("round") == n), None)


def hist_reads(*paths):
    """hist の関数が読む物の宣言（rules が HIST の関数に付ける）: rounds（閉じた周の記録）・rd（周の rd）・out.<節>（周ごとの出力）・
    loop.<鍵>・record.<欄>・inputs.<欄>・hist.<名>（ほかの hist の値）。宣言の外を読むと History がその場で落とす"""
    def deco(fn):
        fn.hist_reads = tuple(paths)
        return fn
    return deco


class History:
    """hist の関数に渡す入れ物。**宣言した物だけが見え、何も書けない**（返す値は写し）。"""

    def __init__(self, board, name, reads):
        self.__b, self.__name, self.__reads = board, name, tuple(reads)

    def __need(self, what):
        if what not in self.__reads and not any(what.startswith(r + ".") for r in self.__reads):
            die(f"hist '{self.__name}' が宣言していない物 '{what}' を読んだ（宣言: {list(self.__reads)}）——hist_reads に書け")

    @property
    def round(self):
        return self.__b.round

    @property
    def validator(self):
        from .rules import validator_module
        return validator_module(self.__b)

    def round_record(self, n):
        """周 n の記録（rounds/round-<n>.json）。無ければ None。閉じたかどうかは読む側（rules）が決める"""
        self.__need("rounds")
        p = self.__b.dir / "rounds" / f"round-{n}.json"
        return read_json(p) if p.is_file() else None

    def rd(self, n):
        """周 n の rd（done・na・skipped・stopped・instances）の写し。無い周は None"""
        self.__need("rd")
        return copy.deepcopy(_rd_of(self.__b, n))

    def output(self, nid, n):
        """節 nid が周 n に出した出力（無ければ None）。今の周の最新は state.outputs、前の周は rd の instance の出力、
        機械の節は out/r<n>/<節>.json（機械の節は instance を持たない）。書き直された後の値を読むので覚えない"""
        self.__need(f"out.{nid}")
        b = self.__b
        info = b.state["outputs"].get(nid)
        if info and info.get("round") == n:
            return read_json(b._out_path(info["file"]))
        rd = _rd_of(b, n)
        if rd:
            done = [i for i in rd["instances"].values() if i["node"] == nid and i["status"] == "done" and i.get("output_file")]
            if done:
                return read_json(b._out_path(done[-1]["output_file"]))
        if b.nodes.get(nid, {}).get("run_by") == "driver":
            p = b.dir / "out" / f"r{n}" / (safe_name(nid) + ".json")
            if p.is_file():
                return read_json(p)
        return None

    def __call__(self, path, default=None):
        """宣言した loop.<鍵>・record.<欄>・inputs.<欄> の値の写し（無ければ default）"""
        if path.split(".", 1)[0] not in LOOKUP_HEADS:
            die(f"hist '{self.__name}' が読めない頭 '{path}'（読めるのは {'/'.join(LOOKUP_HEADS)}）")
        self.__need(path)
        b = self.__b
        try:
            return copy.deepcopy(get_path({"loop": b.loop_state, "record": b.record, "inputs": b.state["inputs"]}, path))
        except KeyError:
            return default

    def hist(self, name):
        """ほかの hist の値（無ければ HIST_ABSENT）"""
        self.__need(f"hist.{name}")
        return self.__b.hist(name)


class HistView(dict):
    """文脈（Board.ctx）の hist の頭。鍵を引いた時に初めて値を作る——条件と穴は読む鍵だけを作らせる。
    dict を継ぐのは util.get_path が dict の鍵として辿るため（中身は持たない）"""

    def __init__(self, board, names):
        super().__init__()
        self.__b, self.__names = board, tuple(names)

    def __contains__(self, k):
        return k in self.__names

    def __getitem__(self, k):
        if k not in self.__names:
            raise KeyError(k)
        v = self.__b.hist(k)
        if v is HIST_ABSENT:
            raise KeyError(k)
        return v

    def get(self, k, default=None):
        try:
            return self[k]
        except KeyError:
            return default

    def keys(self):
        return list(self.__names)

    def __iter__(self):
        return iter(self.__names)

    def __len__(self):
        return len(self.__names)

    def items(self):
        return [(k, self.get(k)) for k in self.__names]


def repair_routes(fn):
    """hist の関数が読む物（hist_reads）から、値の元を直す道を並べる——手当ての口（loop.py patch）が hist の値を拒むときの案内。
    閉じた周の記録と周の rd は直す口を持たない（過去の周の記録を直す口は足さない）ので、そう言う"""
    routes = []
    for r in getattr(fn, "hist_reads", ()):
        head, _, rest = r.partition(".")
        if head == "out":
            routes.append(f"節 {rest} の最新の出力は loop.py patch --path out.{rest}.<欄>（前の周の出力には届かない）")
        elif head == "record":
            routes.append(f"今の周の記録は loop.py patch --path {rest}")
        elif head == "loop":
            routes.append(f"盤面の run の状態は loop.py patch --path state.loop.{rest}")
        elif head == "hist":
            routes.append(f"元の値 hist.{rest} の元を直す")
        elif r == "rounds":
            routes.append("閉じた周の記録（rounds/round-<N>.json）から作る部分は直す口が無い（過去の周の記録を直す口は無い）")
        elif r == "rd":
            routes.append("周の rd（engine が持つ節の状態）から作る部分は直す口が無い")
        else:   # inputs.<名>（init で固まり書き換えない）と、宣言の検査を通らない頭
            routes.append(f"{r} から作る部分は直す口が無い")
    return routes


def compute(board, name, fn, stack):
    """hist の関数 fn を History で呼ぶ。stack は呼び合いの輪を止める（同じ名前を 2 度呼べば die）"""
    if name in stack:
        die(f"hist '{name}' が自分を呼んでいる（{' → '.join((*stack, name))}）")
    reads = getattr(fn, "hist_reads", None)
    if not isinstance(reads, tuple):
        die(f"hist '{name}' が読む物を宣言していない（rules で hist_reads(...) を付けよ）")
    stack.append(name)
    try:
        return fn(History(board, name, reads))
    finally:
        stack.pop()


def write_control(board, table):
    """控え（<盤面>/hist.json）を書く。**正本でない**——値は保存のたびに履歴から作り直し、控えを読む口は engine に無い。
    値が graph の hist_schema から外れた・作れなかった時は、控えの errors と state.hist_drift（記録と報告へは validator の
    TRACES が写す）に残して止めない。履歴（周の記録・節の出力・trace）には何も足さない"""
    schema = (board.graph.get("hist_schema") or {}).get("properties") or {}
    values, errors = {}, []
    for name, fn in table.items():
        try:
            v = board.hist(name)
        except (Exception, SystemExit) as e:  # noqa: BLE001  die は SystemExit——控えのために保存を止めない
            errors.append(f"{name}: 作れなかった（{type(e).__name__}: {e}）")
            continue
        if v is HIST_ABSENT:
            continue
        values[name] = v
        if name in schema:
            errors += validate_schema(v, schema[name], f"hist.{name}")
    rows = board.state.setdefault("hist_drift", [])
    for e in errors:
        if not any(r.get("round") == board.round and r.get("error") == e for r in rows):
            rows.append({"round": board.round, "error": e})
    body = {"canonical": False,
            "note": "正本でない控え。値は rules の HIST の関数が周の記録（rounds/）と節の出力（out/）から作り、engine が盤面を保存する"
                    "たびに書き直す。直すなら元の履歴（loop.py patch --path out.<節>.<欄> か記録）を直せ——ここを書き換えても何にも効かない",
            "round": board.round, "rev": board.state.get("rev"), "values": values, "errors": errors}
    tmp = board.dir / (HIST_FILE + ".tmp")
    write_json(tmp, body)
    os.replace(tmp, board.dir / HIST_FILE)
