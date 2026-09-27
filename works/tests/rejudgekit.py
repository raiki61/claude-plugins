"""同じ周の再審の試験の道具（tests/test_rejudge.py・test_blk_rejudge.py が使う）。

盤面は手本 test_rejudge_path の Run 1（graphloops 0.21.0 の台本を engine の中で撮った物）から作る:
- objection: 手 32（p3.fix の受け付け）の前まで戻し、修正の返答に異議を足した見本 fix2_rejudge_requested を done する
  （写しの規則 fix_covers_open_units が loop.rejudge_requested を書き、settle が p2.rejudge を出す）
- none:      手 32 の後（異議の無い修正を受けた盤面）から settle する（p2.rejudge・p2.rejudge_third は na）
- exhausted: 手 33（台本が loop.py patch で異議を置いた手）の後に、往復の数 loop.rejudge_rounds を今の周の 3 に、record.process.rejudge に 3 行を置いて settle する
  （0.21.0 の規則でも第三の目が出る盤面。規則が出す時だけ第三の目の段が回ることを見る）
表は 1 本目のラインの本物の表（darkfactory/nodes.json。再審の 2 節は role・where blk-rejudge）。作った盤面の state.works に
line・table_sha を置くので、rejudge は本物の entry.open_board で開く（試験の差し替えの口は無い）。修正役の返答は、盤面の決まり
（役の返答の前に mark_launched(節, 試行)）どおり、起こした印を置いてから受ける。1 つの盤面を作るのに 5〜10 秒かかる（p3.fix の受け付けと settle の機械の節）ので、
種類ごとに 1 度だけ作って置き場ごと控え、試験ごとに同じパスへ戻す（盤面は絶対パスを持つので別の置き場へは写せない）。

包みの家（WORKS_ADAPTER_HOME）は試験ごとの一時の置き場。put_session が判定役の会話の id と起動の行を置く。
"""
import datetime
import json
import os
import pathlib
import shutil
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
CORE = HERE.parent / ".shared" / "core"
REPLIES = HERE / "replies"
for _p in (str(HERE), str(CORE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import boardreplay as br  # noqa: E402
import entry  # noqa: E402
import rejudge  # noqa: E402

TABLE = entry.load_table("darkfactory")
SCENARIO, RUN, FIX_SEQ, PATCH_SEQ = "test_rejudge_path", "1", 32, 33
UNIT_A = "src/a.py:f — 上限が効かない経路がある"
UNIT_B = "src/b.py:g — 定数の重複"


def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


def _run_steps():
    return br.load_runs(SCENARIO)[RUN]


def _build(kind, into):
    rs = _run_steps()
    if kind == "objection":
        board_dir, repo = br.restore(rs, FIX_SEQ, "before", into)
        b = br.board_from_memory(br.memory_at(rs, FIX_SEQ, "before"), board_dir, TABLE)
        b.mark_launched("p3.fix", b.rd["instances"]["p3.fix"]["attempts"])
        b.done("p3.fix", load("fix2_rejudge_requested"))
    elif kind == "none":
        board_dir, repo = br.restore(rs, FIX_SEQ, "after", into)
        br.board_from_memory(br.memory_at(rs, FIX_SEQ, "after"), board_dir, TABLE).settle()
    elif kind == "exhausted":
        board_dir, repo = br.restore(rs, PATCH_SEQ, "after", into)
        mem = br.memory_at(rs, PATCH_SEQ, "after")
        mem["state"]["loop"]["rejudge_rounds"] = {"round": mem["state"]["round"], "n": 3}
        # 往復 3 回の記録（第三の目の指示書が {{record.process.rejudge}} を貼る。0.21.0 の規則では実際には積まれない）
        mem["record"].setdefault("process", {})["rejudge"] = [load("rejudge_partial")] * 3
        br.board_from_memory(mem, board_dir, TABLE).settle()
    else:
        raise ValueError(kind)
    patch_state(board_dir, lambda st: st["works"].update(line=TABLE.line, table_sha=TABLE.sha()))
    return board_dir, repo


class Boards:
    """種類ごとに 1 度だけ作った盤面を控え、fresh(kind) で同じパスに戻して (盤面, 対象リポジトリ) を返す"""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.made = {}

    def fresh(self, kind):
        into = self.root / kind
        snap = self.root / f"{kind}.snap"
        if kind not in self.made:
            self.made[kind] = _build(kind, into)
            shutil.copytree(into / "work", snap, symlinks=True)
        else:
            shutil.rmtree(into / "work")
            shutil.copytree(snap, into / "work", symlinks=True)
        return self.made[kind]

    def cleanup(self):
        self._tmp.cleanup()


def state(board_dir):
    return json.loads((pathlib.Path(board_dir) / "state.json").read_text(encoding="utf-8"))


def record(board_dir):
    return json.loads((pathlib.Path(board_dir) / "record.json").read_text(encoding="utf-8"))


def patch_state(board_dir, fn):
    """state.json を読んで fn(state) で書き換えて書き戻す（台本の loop.py patch に当たる手）"""
    p = pathlib.Path(board_dir) / "state.json"
    st = json.loads(p.read_text(encoding="utf-8"))
    fn(st)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iso(dt):
    return dt.astimezone().isoformat(timespec="microseconds")


def put_session(repo, *, sid=None, at=None, row_id=None, node="judge", mode="new", write_id=True):
    """包みの家に判定役の会話の id（sessions/<cwd>/judge.id）と起動の行（launches/<cwd>.jsonl）を置く。返りは id。
    at は起動の行の時刻（既定は今）、row_id は行の session.id（既定は id と同じ）"""
    ad = rejudge.adapter_module()
    sid = sid or str(uuid.uuid4())
    if write_id:
        p = ad.session_path(repo, "judge")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(sid + "\n", encoding="utf-8")
    lp = ad.launches_path(repo)
    lp.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": iso(at or datetime.datetime.now()), "pid": 1, "cwd": os.path.realpath(str(repo)), "node": node,
           "continue": None, "mode": "merged", "session": {"mode": mode, "id": row_id or sid}}
    with lp.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return sid


def board_files(board_dir):
    """盤面の層が書くファイル（state・record・trace・out/）の中身の写し。拒んだ受け付けが盤面を書かないことを見る"""
    d = pathlib.Path(board_dir)
    got = {n: (d / n).read_bytes() for n in ("state.json", "record.json", "trace.jsonl")}
    for p in sorted((d / "out").rglob("*")):
        if p.is_file():
            got[str(p.relative_to(d))] = p.read_bytes()
    return got
