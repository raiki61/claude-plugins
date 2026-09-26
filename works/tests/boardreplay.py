"""盤面の手本（tests/boards/golden-a1202d0/）を DiskBoard に当てる道具（仕様 9.3）。

手本は graphloops 0.21.0（a1202d0）の台本を engine の中で撮った物（作り手は dev/board-goldens/make.py、形は同じ置き場の
README）。ここは手本を読む・手の前後の記憶と目録を組む・一時の場所に戻す・記憶から DiskBoard を組む・比べる、を持つ。

置き場の形（restore の into の下。印はこの形から一意に決まるので、盤面の置き場だけから戻せる）:
  into/work                @WORK@（作り手の作業場）
  into/work/tmp            @TMPDIR@（台本の子の一時の置き場）
  into/work/tmp/run        @RUN@（盤面と対象リポジトリの親）
  into/work/tmp/run/board  @BOARD@
  into/work/tmp/run/repo   @REPO@
  @CORE@ は写し（works/.shared/core。graphloops/ と scripts/review-record.py の親）、@PY@ は今の Python、@HOME@ は今のホーム。

手の行は Step（dict の子。属性 run_steps に同じ Run の手の並びを持つ）で渡す。compare は手 1 つから手の後を引くため。
"""
import contextlib
import copy
import gzip
import hashlib
import importlib.machinery
import json
import os
import pathlib
import shutil
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
GOLD = HERE / "boards" / "golden-a1202d0"
CORE = HERE.parent / ".shared" / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from board import BOARD_VERSION, CORE_DIR, GRAPH_SHA, BoardGap, DiskBoard  # noqa: E402
from engine.rules import registry  # noqa: E402
from engine.util import Reject  # noqa: E402


# ---------------------------------------------------------------- 再生の中だけの compile の控え
# 盤面を開くたびに engine の load_rules が写しの RL（と RL が読む policy_input.py）を読み直す。bytecode を書かない決まり
# なので毎回 compile し直し、手本の再生では 1 盤面あたりの時間の 3 割近くがここだった（Task 4b の測り）。
# 再生の試験のプロセスでだけ、compile の結果（code object）をパスと元のバイトの sha256 で控えて使い回す。
# module は盤面ごとに新しく exec する（engine の INJECT も毎回入り、overrides の大域の差し替えは他の盤面に漏れない）。
# 控えるのは写しの rules/ の下のファイルだけ。bytecode のファイルは書かない。board.py と写しは変えない
CODE_CACHE = {}     # (パス, 元のバイトの sha256, _optimize) → code object
_RULES_DIR = (CORE_DIR / "graphloops" / "rules").resolve()


def _install_compile_cache():
    loader = importlib.machinery.SourceFileLoader
    if getattr(loader.__dict__.get("source_to_code"), "_works_replay_cache", False):
        return
    orig = importlib.machinery.SourceFileLoader.source_to_code

    def source_to_code(self, data, path, *, _optimize=-1):
        p = pathlib.Path(path).resolve()
        if p.parent != _RULES_DIR:
            return orig(self, data, path, _optimize=_optimize)
        key = (str(p), hashlib.sha256(data).hexdigest(), _optimize)
        code = CODE_CACHE.get(key)
        if code is None:
            code = CODE_CACHE[key] = orig(self, data, path, _optimize=_optimize)
        return code
    source_to_code._works_replay_cache = True
    loader.source_to_code = source_to_code


_install_compile_cache()

# ---------------------------------------------------------------- 比べない欄（仕様 9.3）
# 名前 → 理由。試験の出力に毎回並べる。足すときは理由を書いて足す（ずれを見つけたら board.py を直すのが先）
NOT_REPRODUCED = {
    # 時刻
    "at": "時刻（周の箱の done・問いなどに engine が刻む）",
    "t": "時刻（trace の行。trace そのものも比べない: disk:trace.jsonl）",
    "created": "時刻（盤面を作った時）",
    "done_at": "時刻（instance を受けた時）",
    "emitted_at": "時刻（instance を出した時）",
    "launched_at": "時刻（役を起こした時）",
    # 盤面の版
    "state.rev": "盤面の版（保存の回数。手本の engine と保存の回数が違いうる）",
    "run_id": "盤面を作った時刻から engine が決める名前",
    # engine の周の頭の痕跡（graph_changed・engine_changed・frozen_outputs_stale を持たない）
    "state.engine": "engine の版の控え（DiskBoard は engine_changed を持たず state.works.core で代える）",
    "state.engine_changes": "engine の版の変わり目の控え（engine_changed を持たない）",
    "stale_frozen": "固めた出力が古くなった印（frozen_outputs_stale を持たない）",
    "state.graph_changes": "graph の変わり目の控え（graph_changed を持たない）",
    # instance の描画・起動の欄（描画・起動は Archon と works のブロックが持つ）
    "instance.prompt_sha": "プロンプトの描画を持たない",
    "instance.prompt_file": "プロンプトの描画を持たない",
    "instance.launch": "役の起動を持たない（engine_run の steps・sha は比べる。engine が役の節に置く空の {} も比べない）",
    "instance.mode（engine_run でない値）": "役の起こし方（agent・runner・cli・agent_continue）は Archon とブロックが持つ。"
                                         "engine が走らせた節の mode: engine_run は比べる",
    "instance.agent_type": "役の定義の名前（役を起こすのは Archon とブロック。描画・起動を持たない）",
    "instance.deliver": "プロンプトの渡し方（描画を持たない）",
    "instance.prompt_bytes": "プロンプトの大きさ（描画を持たない）",
    "instance.item": "扇の項目（a1202d0 の graph に扇の節は無く、engine は扇でない節に null を置く。扇の節は BoardGap）",
    "instance.tree_before": "役ごとの作業ツリーの前後の突合を持たない（v1 の写しが持つ）。突合で拒む手（作業ツリーが変わった）も当てない",
    "instance.attempt_log": "試行の控えは前の試行を出した時刻（prev_emitted_at）を持つ。試行の数 attempts と出し直した置き場 out_path は比べる",
    "instance.pointers": "一覧を固めた番号の控えを持たない（番号で書いた返答は engine の文で拒む。仕様 BL17）",
    "instance.delegate": "任せ先の起動を持たない",
    "instance.launch_state": "engine の launch の起こし済みの印（launched_at と対。running → ended）。run_engine はその場で走らせて"
                             "受けるまで返らず、役を起こすのは Archon とブロックなので、起こし中の印を持たない",
    "instance.continue_of": "同じ役の会話を続ける控え（graph の same_context_as を engine が起こす時に解く）。役の会話を起こすのは"
                            "Archon とブロック（same_context_as は graph から読む）",
    "instance.role_def_missing": "役の定義（agents/<役>.md）がこの環境に無かった印。役の定義を解くのは役を起こす Archon とブロック"
                                 "（描画・起動を持たない。state.role_def_missing・record.process.role_def_missing も同じ）",
    "state.role_def_missing": "instance.role_def_missing の盤面の控え（同じ理由）",
    "record.process.role_def_missing": "state.role_def_missing を finalize が記録に写した痕跡（同じ理由。engine の validator の痕跡の欄）",
    "instance.agent_id": "役の会話の番号は Archon が持つ（accept は受け取らない）",
    "instance.read_from": "返答を読んだ先（accept は返答の dict を受け取る）",
    "state.git_mismatches（accept の突合の行）": "受け付けの作業ツリーの突合（tree_before）を持たないので、突合を受け入れた控え"
                                                "（instance を持つ行）も残らない。機械の節 worktree_compare が書く行（where: P1）は比べる",
    # 受け付けの中で持たない物（仕様 4.1。a1202d0 の graph に fan_out・thickness_from の節は無い）
    "扇の被覆（fan_out.cover）": "扇の節の答えの欠けを出し直す所を持たない（a1202d0 の graph に扇の節は無い）",
    "段の昇格（thickness_from）": "段の昇格を持たない（a1202d0 の graph は段を持たない）",
    "disk:report.md": "本文の保存（節の save_text_as）を持たない。報告の本文は works のブロックが書く",
    "disk:rounds/works/": "works の周の添え書き（仕様 4.5。engine の盤面に無い。RR は rounds/ の下のディレクトリを読み飛ばす）",
    "disk:trace.jsonl": "手本が撮っていない（時刻の痕跡。作り手の目録の範囲の外）。DiskBoard も engine と同じ行の形で書くが比べない",
    "trace の done の行の sha（schema の節）": "engine は役が返した生の本文の sha、DiskBoard は本文を受け取らず返答の dict を"
                                          "並べ直した JSON の sha（本文を返す節は同じ本文の sha）。trace は比べない（disk:trace.jsonl）",
    "disk:count-budget.json#seconds": "RL が数える問いを走らせた時間（回数 calls と周は比べる）",
    "JSON のファイルの鍵の順（disk の *.json）": "手本の記憶は鍵を並べ直して撮った（作り手の sort_keys）ので、記憶から組んだ盤面が"
                                          "書く JSON（rounds/round-<N>.json など）は鍵の順だけ違いうる。中身の sha が違う *.json は読んだ値で比べる",
    # engine が走らせる節
    "checks_fallback の時機": "engine は next の計画の時に書き、DiskBoard は run_engine の中で書く（周の終わりの値は比べる）",
    "runs[].wall_s": "実行の時間",
    "runs[].out": "ログのパス",
    "runs[].err": "ログのパス",
    # works だけの欄
    "state.works": "works だけの欄（engine の盤面に無い）",
}

_ANY_KEYS = {k for k in NOT_REPRODUCED if "." not in k and ":" not in k and "（" not in k and " " not in k}
_STATE_KEYS = {k.split(".", 1)[1] for k in NOT_REPRODUCED if k.startswith("state.")}
_RECORD_PATHS = {tuple(k.split(".")) for k in NOT_REPRODUCED if k.startswith("record.")}   # 記録の中の 1 か所
_INSTANCE_KEYS = {k.split(".", 1)[1] for k in NOT_REPRODUCED if k.startswith("instance.")}
_RUN_KEYS = {k.split(".", 1)[1] for k in NOT_REPRODUCED if k.startswith("runs[].")}
_DISK_PATHS = {k.split(":", 1)[1] for k in NOT_REPRODUCED if k.startswith("disk:") and "#" not in k and not k.endswith("/")}
_DISK_DIRS = tuple(k.split(":", 1)[1] for k in NOT_REPRODUCED if k.startswith("disk:") and k.endswith("/"))   # 下の全部を比べない置き場
_DISK_FIELDS = {}
for _k in NOT_REPRODUCED:
    if _k.startswith("disk:") and "#" in _k:
        _p, _f = _k.split(":", 1)[1].split("#", 1)
        _DISK_FIELDS.setdefault(_p, set()).add(_f)


def normalize(obj, _path=()):
    """比べない欄（NOT_REPRODUCED）を除いた写し。{state, record} の記憶も、その一部も受ける
    （state の直下の欄と instance の欄は、記憶の丸ごと {state, record} から降りた時だけ見分ける）"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            p = (*_path, k)
            if k in _ANY_KEYS:
                continue
            if len(p) == 2 and p[0] == "state" and k in _STATE_KEYS:
                continue
            if p in _RECORD_PATHS:
                continue
            if p == ("state", "git_mismatches") and isinstance(v, list):
                # 受け付けの突合の行（instance を持つ）だけ落とす。worktree_compare の行（where: P1）は比べる
                v = [x for x in v if not (isinstance(x, dict) and "instance" in x)]
            inst = len(p) == 6 and p[:2] == ("state", "rounds") and p[3] == "instances"
            if inst and k == "launch":
                v = {x: v[x] for x in ("steps", "sha") if isinstance(v, dict) and x in v}
                if not v:
                    continue
            elif inst and k == "mode" and v != "engine_run":
                continue
            elif inst and k in _INSTANCE_KEYS:
                continue
            if len(_path) >= 2 and _path[-2] == "runs" and isinstance(_path[-1], int) and k in _RUN_KEYS:
                continue
            out[k] = normalize(v, p)
        return out
    if isinstance(obj, list):
        return [normalize(v, (*_path, i)) for i, v in enumerate(obj)]
    return obj


# ---------------------------------------------------------------- 手本を読む
def manifest() -> dict:
    return json.loads((GOLD / "MANIFEST.json").read_text(encoding="utf-8"))


def git_env() -> dict:
    """手本を撮った時の git の名前・時刻・設定の固定（再生も同じ環境で回す。仕様 9.2 の 4）"""
    return dict(manifest()["git_env"])


_BLOBS = {}


def blob(sha: str) -> bytes:
    got = _BLOBS.get(sha)
    if got is None:
        got = _BLOBS[sha] = gzip.decompress((GOLD / "blobs" / f"{sha}.gz").read_bytes())
    return got


class Step(dict):
    """手本の手の 1 行。run_steps は同じ Run の手の並び（seq の順）"""
    run_steps = None


class RunSteps(list):
    """1 本の Run の手の並び。scenario・run・meta（MANIFEST の Run の項）を持つ"""
    scenario = run = meta = None


def load_runs(scenario: str) -> dict:
    """{Run の番号: RunSteps}（手は seq の順）"""
    meta = manifest()["scenarios"][scenario]["runs"]
    rows = json.loads(gzip.decompress((GOLD / "steps" / f"{scenario}.json.gz").read_bytes()))
    got = {}
    for r in rows:
        k = str(r["run"])
        if k not in got:
            rs = got[k] = RunSteps()
            rs.scenario, rs.run, rs.meta = scenario, k, meta[k]
        s = Step(r)
        s.run_steps = got[k]
        got[k].append(s)
    for rs in got.values():
        rs.sort(key=lambda s: s["seq"])
    return got


def replayable(rs: "RunSteps") -> bool:
    """再生に当てる Run か: init が通り、graph が写しと同じ（graph を手で直した test_stop_midround の stop-nodecl を外す）"""
    return not rs.meta["init_rejected"] and rs.meta.get("graph_sha") == GRAPH_SHA


def every_run():
    """手本の全部の場面の、再生に当てる Run（RunSteps）"""
    for scen in manifest()["scenarios"]:
        for rs in load_runs(scen).values():
            if replayable(rs):
                yield rs


# ---------------------------------------------------------------- 記憶と目録を組む
def _apply_ops(obj, ops):
    """記憶の差分 [{path, op: set|del, value?}] をその場で当てる"""
    for o in ops:
        *head, last = o["path"]
        cur = obj
        for k in head:
            cur = cur[k]
        if o["op"] == "set":
            if isinstance(cur, list) and last == len(cur):
                cur.append(copy.deepcopy(o["value"]))
            else:
                cur[last] = copy.deepcopy(o["value"])
        elif o["op"] == "del":
            del cur[last]
        else:
            raise ValueError(f"知らない op: {o}")
    return obj


def _find(run_steps, seq):
    for i, s in enumerate(run_steps):
        if s["seq"] == seq:
            return i
    raise KeyError(f"手 {seq} が Run に無い")


def _check_which(which):
    if which not in ("before", "after"):
        raise ValueError(f"which は before か after: {which!r}")


def memory_at(run_steps: list, seq: int, which: str) -> dict | None:
    """Run の頭の memory.base に差分を順に当て、手 seq の前か後の {state, record} を返す（手本の印のまま）。
    拒まれた手の後は前と同じ（記憶の入れ物は捨てるので盤面は前のまま）。na の手は前の記憶に rd.na[node] = why を足した物。
    init の前は None"""
    _check_which(which)
    target = _find(run_steps, seq)
    cur, nas = None, []
    for i, s in enumerate(run_steps[:target + 1]):
        hit = i == target
        if s["kind"] == "na":
            if hit:
                got = _with_na(cur, nas)
                return _with_na(got, [s["na"]]) if which == "after" else got
            nas.append(s["na"])
            continue
        m = s.get("memory")
        if not m:
            if hit:
                got = _with_na(cur, nas)
                return got
            continue
        nas = []
        if "base" in m:
            if s["kind"] == "init":
                if hit and which == "before":
                    return None
                cur = copy.deepcopy(m["base"])
            else:
                cur = copy.deepcopy(m["base"])
                if hit and which == "before":
                    return copy.deepcopy(cur)
                if "after" in m:
                    _apply_ops(cur, m["after"])
        else:
            _apply_ops(cur, m["before"])
            if hit and which == "before":
                return copy.deepcopy(cur)
            if "after" in m:
                _apply_ops(cur, m["after"])
        if hit:
            return copy.deepcopy(cur)
    raise AssertionError("届かない")


def _with_na(mem, nas):
    got = copy.deepcopy(mem)
    for na in nas:
        got["state"]["rounds"][-1]["na"][na["node"]] = na["why"]
    return got


def _apply_listing(base, diff):
    got = dict(base)
    got.update((diff or {}).get("add") or {})
    for p in (diff or {}).get("drop") or []:
        got.pop(p, None)
    return got


def manifest_at(run_steps, seq, which, kind) -> dict:
    """手 seq の前か後の目録 {パス: 中身の sha256}。kind は disk（盤面の置き場）か repo（対象リポジトリ）。
    repo は手の前だけが撮ってあるので、後も前と同じ物を返す（engine の手は対象リポジトリを変えない。変えるのは役）"""
    _check_which(which)
    if kind not in ("disk", "repo"):
        raise ValueError(f"kind は disk か repo: {kind!r}")
    target = _find(run_steps, seq)
    cur = {}
    for i, s in enumerate(run_steps[:target + 1]):
        hit = i == target
        if kind == "repo":
            r = s.get("repo_before")
            if r is not None:
                cur = dict(r["base"]) if "base" in r else _apply_listing(cur, r)
            if hit:
                return cur
            continue
        d = s.get("disk")
        if d is None:
            before = after = cur
        elif "base" in d:
            before = {} if s["kind"] == "init" else dict(d["base"])
            after = dict(d["base"]) if s["kind"] == "init" else _apply_listing(before, d.get("after"))
        else:
            before = _apply_listing(cur, d.get("before"))
            after = _apply_listing(before, d.get("after"))
        if hit:
            return dict(before if which == "before" else after)
        cur = after
    raise AssertionError("届かない")


# ---------------------------------------------------------------- 印と実パス
class Places:
    """印 → 実パス（置き場の形は頭の文書）"""

    def __init__(self, into):
        into = pathlib.Path(into).resolve()
        self.work = into / "work"
        self.tmp = self.work / "tmp"
        self.run = self.tmp / "run"
        self.board = self.run / "board"
        self.repo = self.run / "repo"
        self.paths = {"@BOARD@": self.board, "@REPO@": self.repo, "@RUN@": self.run, "@CORE@": CORE_DIR.resolve(),
                      "@PY@": pathlib.Path(sys.executable), "@WORK@": self.work, "@TMPDIR@": self.tmp,
                      "@HOME@": pathlib.Path.home()}
        pairs = {(s, t) for t, p in self.paths.items() for s in _spellings(p) if len(s) > 1}
        self._tok = sorted(pairs, key=lambda x: -len(x[0]))
        self._btok = [(s.encode("utf-8"), t.encode("utf-8")) for s, t in self._tok]
        self._untok = [(t, str(p)) for t, p in self.paths.items()]
        self._buntok = [(t.encode("utf-8"), str(p).encode("utf-8")) for t, p in self._untok]

    @classmethod
    def of_board(cls, board_dir):
        b = pathlib.Path(board_dir).resolve()
        if b.name != "board" or b.parent.name != "run" or b.parents[1].name != "tmp" or b.parents[2].name != "work":
            raise ValueError(f"{b} は restore の置き場の形（<into>/work/tmp/run/board）でない")
        return cls(b.parents[3])

    def tokenize(self, obj):
        if isinstance(obj, str):
            for a, b in self._tok:
                obj = obj.replace(a, b)
            return obj
        if isinstance(obj, dict):
            return {self.tokenize(k): self.tokenize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.tokenize(v) for v in obj]
        return obj

    def untokenize(self, obj):
        if isinstance(obj, str):
            if "@" in obj:
                for a, b in self._untok:
                    obj = obj.replace(a, b)
            return obj
        if isinstance(obj, dict):
            return {self.untokenize(k): self.untokenize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.untokenize(v) for v in obj]
        return obj

    def tokenize_bytes(self, data):
        for a, b in self._btok:
            data = data.replace(a, b)
        return data

    def untokenize_bytes(self, data):
        if b"@" in data:
            for a, b in self._buntok:
                data = data.replace(a, b)
        return data


def _spellings(p):
    """手本の作り手と同じ綴りの集まり（実体のパスと、/var・/private/var、/tmp・/private/tmp の両方）"""
    got = {str(p), os.path.realpath(str(p))}
    for x in list(got):
        for a, b in (("/private/var/", "/var/"), ("/private/tmp/", "/tmp/")):
            if x.startswith(a):
                got.add(b + x[len(a):])
            elif x.startswith(b):
                got.add(a + x[len(b):])
    return got


# ---------------------------------------------------------------- 戻す・組む・比べる
def _keep_board(rel, is_dir):
    parts = rel.parts
    if len(parts) == 1 and parts[0] in (("prompts", "roles") if is_dir else ("state.json", "record.json", "trace.jsonl")):
        return False
    return is_dir or not parts[-1].endswith(".pgid")


def _keep_repo(rel, is_dir):
    parts = rel.parts
    if parts[0] != ".git":
        return True
    if len(parts) == 1:
        return is_dir
    if parts[1] == "graphloops":   # 人の方針の文書の既定の置き場（RL の policy_input が読む。作業ツリーの外）
        return parts[2:] == (() if is_dir else ("policy.md",))
    return parts[1] in (("objects", "refs") if len(parts) > 2 or is_dir else ("HEAD", "index", "objects", "refs"))


def listing(top, keep, places: Places) -> dict:
    """置き場の目録 {パス: 印に置き換えた中身の sha256}（手本の作り手と同じ範囲と求め方）"""
    top = pathlib.Path(top)
    got = {}
    for root, dirs, files in os.walk(top):
        rel_root = pathlib.Path(root).relative_to(top)
        dirs[:] = sorted(x for x in dirs if keep(rel_root / x, True))
        for f in sorted(files):
            rel = rel_root / f
            p = pathlib.Path(root) / f
            if keep(rel, False) and p.is_file() and not p.is_symlink():
                got[rel.as_posix()] = hashlib.sha256(places.tokenize_bytes(p.read_bytes())).hexdigest()
    return got


def disk_listing(board_dir) -> dict:
    return listing(board_dir, _keep_board, Places.of_board(board_dir))


def _write_tree(top, files, places):
    for rel, sha in files.items():
        p = top / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(places.untokenize_bytes(blob(sha)))


def restore(run_steps, seq, which, into) -> tuple:
    """手 seq の前か後の盤面の置き場（state.json・record.json 以外）と対象リポジトリを into の下に戻す（在れば消して作り直す）。
    返りは (盤面の置き場, 対象リポジトリ)。盤面の記憶は board_from_memory が書く"""
    places = Places(into)
    if places.work.exists():
        shutil.rmtree(places.work)
    places.board.mkdir(parents=True)
    places.repo.mkdir(parents=True)
    _write_tree(places.board, manifest_at(run_steps, seq, which, "disk"), places)
    _write_tree(places.repo, manifest_at(run_steps, seq, which, "repo"), places)
    return places.board, places.repo


def board_from_memory(mem: dict, board_dir, table, allow_halted: bool = False) -> DiskBoard:
    """memory_at の返り（手本の印のまま）から盤面を組む: 印を実パスに戻し、state.works = {board_version} を足して
    state.json・record.json を書き、DiskBoard.open で開く（置き場は restore の形。allow_halted は止めた run の仕上げの手）"""
    places = Places.of_board(board_dir)
    mem = places.untokenize(mem)
    state, record = mem["state"], mem["record"]
    state["works"] = {"board_version": BOARD_VERSION}
    d = pathlib.Path(board_dir)
    (d / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "trace.jsonl").touch()
    return DiskBoard.open(d, table=table, repo=places.repo, allow_halted=allow_halted)


def reply(step: Step, board: DiskBoard, names: bool = True) -> dict:
    """accept の手の返答の本文を、accept に渡す dict にする（engine の accept_output と同じ読み方: schema の無い節は本文の
    text）。本文の中の印（役が名指した盤面の置き場など）は、その盤面の置き場の実パスに戻す。
    names=True なら、台本の役が番号で書いた欄を、手本の engine の手の前の instance が固めていた一覧（instance.pointers）で名前に直す
    （engine は控えで読み替えるが、DiskBoard は控えを持たず番号を拒む〔BL17〕。ラインの役は名前で書く。
    NOT_REPRODUCED の instance.pointers）。直せない番号はそのまま残す"""
    from engine.commands import parse_output
    from engine.pointers import resolve
    text = Places.of_board(board.dir).untokenize(step["args"]["text"])
    n = board.nodes[step["node"]]
    if not n.get("schema"):
        return {"text": text}
    out = parse_output(text)
    snap = None
    if names and n.get("pointers"):
        # 控えは手本の engine の手の前の instance から取る（盤面の instance は控えを持たない。通しの再生でも同じ控えで直す）
        mem = memory_at(step.run_steps, step["seq"], "before")
        snap = (mem["state"]["rounds"][-1]["instances"].get(step["node"]) or {}).get("pointers")
    if snap:
        named = copy.deepcopy(out)
        if not resolve(named, n["pointers"], snap):
            return named
    return out


def engine_run_plan(step: Step, board: DiskBoard) -> dict:
    """engine_run の手の撮った計画（instance の launch）を、RL の ENGINE_RUNS[..].plan の返りの形にする
    （DiskBoard.run_engine の plan= に差し込む。印は盤面の置き場の実パスに戻す）"""
    launch = Places.of_board(board.dir).untokenize(step["engine_run"]["plan"])
    if launch.get("blocked"):
        return {"blocked": launch["blocked"]}
    return {"steps": launch["steps"], "sha": launch["sha"]}


def captured_runner(step: Step, board: DiskBoard, seen: list | None = None):
    """engine_run の手の撮った runs を返す偽の runner（DiskBoard.run_engine の runner=）。log_dir の下に撮った標準出力・
    標準エラーを engine と同じ名前（<段>.out・.err）で書き、返りの行の out・err はそのパス。seen を渡せば受けた
    (steps, cwd, log_dir) を足す"""
    places = Places.of_board(board.dir)

    def runner(steps, cwd, log_dir):
        if seen is not None:
            seen.append((steps, cwd, log_dir))
        log_dir = pathlib.Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        rows = []
        for i, r in enumerate(step["engine_run"]["runs"]):
            base = log_dir / f"{i + 1}"
            row = {k: places.untokenize(r[k]) for k in ("name", "argv", "exit", "wall_s", "tail", "error") if k in r}
            row["out"], row["err"] = str(base) + ".out", str(base) + ".err"
            for k in ("out", "err"):
                pathlib.Path(row[k]).write_bytes(places.untokenize_bytes((r.get(k + "_text") or "").encode("utf-8")))
            rows.append(row)
        return rows
    return runner


def _diff(exp, got, path, out):
    if isinstance(exp, dict) and isinstance(got, dict):
        for k in exp.keys() | got.keys():
            p = f"{path}.{k}" if path else str(k)
            if k not in got:
                out.append(f"{p}: 手本に在るが盤面に無い（{_short(exp[k])}）")
            elif k not in exp:
                out.append(f"{p}: 盤面に在るが手本に無い（{_short(got[k])}）")
            else:
                _diff(exp[k], got[k], p, out)
    elif isinstance(exp, list) and isinstance(got, list) and len(exp) == len(got):
        for i, (a, b) in enumerate(zip(exp, got)):
            _diff(a, b, f"{path}[{i}]", out)
    elif exp != got:
        out.append(f"{path}: 手本 {_short(exp)} ／ 盤面 {_short(got)}")


def _short(v):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 160 else s[:157] + "..."


def _canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_same(path, exp: bytes, got: bytes) -> bool:
    """JSON のファイルを鍵を並べ直した書き方で比べる（鍵の順だけを問わない。true と 1、1 と 1.0 は違う。
    disk:<path>#<欄> の欄は最上位から落とす）"""
    try:
        a, b = json.loads(exp), json.loads(got)
    except ValueError:
        return False
    drop = _DISK_FIELDS.get(path)
    if drop and isinstance(a, dict) and isinstance(b, dict):
        a = {k: v for k, v in a.items() if k not in drop}
        b = {k: v for k, v in b.items() if k not in drop}
    return _canon(a) == _canon(b)


def disk_diff(board_dir, expected: dict) -> list:
    """盤面の置き場の目録と、手本の目録 expected の違いの文の一覧（NOT_REPRODUCED のパスと欄を除く。空なら同じ）"""
    places = Places.of_board(board_dir)
    got = disk_listing(board_dir)
    out = []
    for p in sorted((expected.keys() | got.keys()) - _DISK_PATHS):
        if p.startswith(_DISK_DIRS):
            continue
        if p not in got:
            out.append(f"disk:{p}: 手本に在るが盤面の置き場に無い")
        elif p not in expected:
            out.append(f"disk:{p}: 盤面の置き場に在るが手本に無い")
        elif expected[p] != got[p]:
            if p.endswith(".json") and _json_same(p, blob(expected[p]), places.tokenize_bytes((pathlib.Path(board_dir) / p).read_bytes())):
                continue
            out.append(f"disk:{p}: 中身が違う")
    return out


def compare(board: DiskBoard, step: Step) -> list:
    """手の後の記憶（手本）と盤面の記憶、手の後のディスクの目録（手本）と盤面の置き場の目録の違いの文の一覧
    （NOT_REPRODUCED の欄とパスを除く。空なら同じ）。拒まれた手の後は手の前と比べる"""
    rs = step.run_steps
    if rs is None:
        raise TypeError("compare は load_runs が返す Step を受ける（手の後を Run の頭から組むため）")
    places = Places.of_board(board.dir)
    out = []
    exp = memory_at(rs, step["seq"], "after")
    got = places.tokenize({"state": board.state, "record": board.record})
    _diff(normalize(exp), normalize(got), "", out)
    return out + disk_diff(board.dir, manifest_at(rs, step["seq"], "after", "disk"))


# ---------------------------------------------------------------- 通しの再生（仕様 9.3 の「通し」）
# 台本が手の環境を変えて回した手（手本は手の環境を撮らない）。再生は同じ環境を作って当てる
NO_GIT_STEPS = {("test_rejections", "1", 33): "台本が PATH を空の置き場にして git の無い場を作った next（突合が『測れない』で止まる手）"}

# 台本が engine のコマンドを通さずに盤面を手で書いてから打った手（手本の手として撮られない書き込みに結果が懸かる）。
# 盤面は同じ書き込みを受ける口を持たず（仕様 4.1: 役を起こすのは Archon とブロックで、instance は起こした印 launched_at を
# 持たない。返答の置き場 out_path は受けるまで在らない＝RL の _started は偽）、再生は盤面へ手本を書かない（写し直さない）ので、
# 通しの再生はこの手の前で止め、手本の engine のこの手の前の記憶と比べる。値は (印の種類, 節)——test_board_replay が、
# 手本の手の前に本当にその書き込みが在ることを確かめる
HAND_EDITED_STEPS = {
    ("test_request_entry", "8", 455): ("out_file", "p0.prior_decisions",
                                       "台本が描き直した p0.prior_decisions の返答の置き場（.a2）にファイルを書いてから add した"
                                       "（RL は起きた役と読んで描き直さない。盤面は受けるまで置き場が無いので描き直す）"),
    ("test_request_entry", "9", 482): ("launched_at", "p2.diagnose",
                                       "台本が state.json の p2.diagnose の instance に launched_at を手で書いてから add した"
                                       "（RL は判定役が起きたと読んで拒む。盤面は起こした印を持たない）"),
    ("test_request_entry", "10", 509): ("out_file", "p2.diagnose",
                                        "台本が p2.diagnose の返答の置き場にファイルを書いてから add した"
                                        "（RL は判定役が起きたと読んで拒む。盤面は受けるまで置き場が無い）"),
}


class ReplayDivergence(AssertionError):
    """通しの再生で、盤面が手本の engine と違う動きをした（拒むべき手を通した・違う文で拒んだ・出ているべき節が無い など）"""


def restore_repo(run_steps, seq, into) -> pathlib.Path:
    """手 seq の前の対象リポジトリだけを into の下に戻す（盤面の置き場は触らない。通しの再生が各手の前に呼ぶ）"""
    places = Places(into)
    if places.repo.exists():
        shutil.rmtree(places.repo)
    places.repo.mkdir(parents=True)
    _write_tree(places.repo, manifest_at(run_steps, seq, "before", "repo"), places)
    return places.repo


def _view(state, record, n):
    """周 n の終わりの見え方 {rd, loop, record}（写し）"""
    return copy.deepcopy({"rd": state["rounds"][n - 1], "loop": state.get("loop"), "record": record})


def cut_step(run_steps):
    """HAND_EDITED_STEPS に載った手（通しの再生はその手の前で止める）。無ければ None"""
    return next((s for s in run_steps if (run_steps.scenario, run_steps.run, s["seq"]) in HAND_EDITED_STEPS), None)


def golden_result(run_steps) -> dict:
    """手本の engine の ReplayResult（印のまま）: 周の終わりは周を開く口（open_next_round）に入った時の記憶（open_round の手の前。
    stop_after_round で開かずに止めた締めも含む）。最後は Run の最後の起動の後の盤面（MANIFEST の final）で、最後の周の終わりが
    まだ無ければそこから取る。HAND_EDITED_STEPS の手が在る Run は、その手の前の記憶を最後とする"""
    cut = cut_step(run_steps)
    rounds = {}
    for s in run_steps:
        if cut is not None and s["seq"] >= cut["seq"]:
            break
        if s["kind"] == "open_round":
            m = memory_at(run_steps, s["seq"], "before")
            rounds[m["state"]["round"]] = _view(m["state"], m["record"], m["state"]["round"])
    fin = memory_at(run_steps, cut["seq"], "before") if cut else json.loads(blob(run_steps.meta["final"]["memory"]))
    n = fin["state"]["round"]
    if n not in rounds:
        rounds[n] = _view(fin["state"], fin["record"], n)
    return {"rounds": rounds, "final": {"state": fin["state"], "record": fin["record"]}}


def golden_disk(run_steps) -> dict:
    """手本の engine の最後のディスクの目録（MANIFEST の final）。HAND_EDITED_STEPS の手が在る Run は、その手の前の目録から
    台本が手で書いた返答の置き場のファイルを除いた物（盤面へは書かない。書き込みそのものが再生に無い）"""
    cut = cut_step(run_steps)
    if cut is None:
        return json.loads(blob(run_steps.meta["final"]["disk"]))
    got = manifest_at(run_steps, cut["seq"], "before", "disk")
    kind, node, _ = HAND_EDITED_STEPS[(run_steps.scenario, run_steps.run, cut["seq"])]
    if kind == "out_file":
        inst = memory_at(run_steps, cut["seq"], "before")["state"]["rounds"][-1]["instances"][node]
        del got[inst["out_path"].removeprefix("@BOARD@/")]
    return got


def _norm_view(v):
    got = normalize({"state": {"rounds": [v["rd"]], "loop": v["loop"]}, "record": v["record"]})
    return {"rd": got["state"]["rounds"][0], "loop": got["state"].get("loop"), "record": got["record"]}


def result_diff(expected: dict, got: dict) -> list:
    """ReplayResult の違いの文の一覧（NOT_REPRODUCED を除く。空なら同じ）: 周ごとの rd・loop・record と、最後の state・record"""
    out = []
    for n in sorted(expected["rounds"].keys() | got["rounds"].keys()):
        if n not in got["rounds"]:
            out.append(f"周 {n}: 手本に在るが再生に無い")
        elif n not in expected["rounds"]:
            out.append(f"周 {n}: 再生に在るが手本に無い")
        else:
            _diff(_norm_view(expected["rounds"][n]), _norm_view(got["rounds"][n]), f"周{n}", out)
    _diff(normalize(expected["final"]), normalize(got["final"]), "最後", out)
    return out


class _Replay:
    """1 本の Run を頭（init の手の後）の盤面から通しで当てる（replay の中身）。盤面は DiskBoard の口だけで進め、手本の記憶を
    盤面へ書くのは頭の 1 度（restore と board_from_memory）だけ。各手の前に対象リポジトリだけを撮った物に戻す"""

    def __init__(self, run_steps, into, table):
        self.rs = run_steps
        self.into = pathlib.Path(into)
        self.places = Places(into)
        self.table = table
        self.rounds = {}
        self.planned = set()      # 計画を見た engine_run の instance（周・節・試行）
        self.counts = {"steps": 0, "settle": 0, "fallback": 0, "reject": 0, "gap": 0, "tree": 0, "cut": 0}
        self.b = None

    # -- 盤面の入れ物
    def reopen(self, allow_halted=False):
        """拒まれた手の後の入れ物は捨てる（仕様 4.1 の M11）。開き直すのは盤面自身のディスク（手本の記憶ではない）"""
        self.b = DiskBoard.open(self.b.dir, table=self.table, repo=self.places.repo, allow_halted=allow_halted)

    def pending_inst(self, nid):
        return next((i for i in self.b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending"), None)

    def settle(self, accept_tree_change=None):
        """台本の next に当たる所: settle して、出たばかりの engine_run の節の計画を見る"""
        self.counts["settle"] += 1
        self.b.settle(accept_tree_change)
        self.plan_now()

    def plan_now(self):
        """engine は engine_run の節を出す時（next の中）に計画し、任せ先へ落ちる計画ならその場で落とす（手として撮られない。
        p0.parallel_pr は remote が無いので毎周、宣言の無いリポジトリの p0.local_checks も）。盤面では計画は run_engine の中なので、
        出たばかりの engine_run の節の計画を見て、落ちる物だけその場で run_engine に渡す（走らせる計画は手本の engine_run の手を待つ）"""
        b = self.b
        if b.state.get("halted") or b.state.get("pending_human"):
            return
        for inst in list(b.rd["instances"].values()):
            nid = inst["node"]
            key = (b.round, nid, inst.get("attempts", 1))
            if (inst["status"] != "pending" or inst.get("engine_fallback") or key in self.planned
                    or self.table.nodes[nid].by != "engine_run"):
                continue
            self.planned.add(key)
            er = registry(b.rules, "ENGINE_RUNS")[b.nodes[nid]["engine_run"]["builtin"]]
            plan = er["plan"](b, nid)
            if "fallback" in plan:
                self.counts["fallback"] += 1
                b.run_engine(nid, plan=plan, runner=_refuse_runner)

    # -- 周の終わりを撮る（手本の作り手が open_next_round を包んだのと同じ点）
    @contextlib.contextmanager
    def round_hooks(self):
        import board as board_mod
        import engine.advance as advance_mod
        orig = advance_mod.open_next_round

        def wrapped(b, nid):
            if b is self.b:
                self.rounds[b.round] = self.places.tokenize(_view(b.state, b.record, b.round))
            return orig(b, nid)
        advance_mod.open_next_round = board_mod.open_next_round = wrapped
        try:
            yield
        finally:
            advance_mod.open_next_round = board_mod.open_next_round = orig

    # -- 手
    def expect_reject(self, s, call, gap=False):
        """engine が拒んだ手: 同じ文の Reject（依存の拒否は BoardGap）。その後の入れ物は捨てて開き直す"""
        want = s["raised"]
        try:
            call()
        except BoardGap as e:
            if not gap:
                raise ReplayDivergence(f"seq {s['seq']} {s['kind']} {s.get('node')}: 手本は {want['type']}（{want['text'][:200]}）、"
                                       f"盤面は BoardGap（{e}）") from e
            self.counts["gap"] += 1
        except Reject as e:
            if gap or self.places.tokenize(str(e)) != want["text"]:
                raise ReplayDivergence(f"seq {s['seq']} {s['kind']} {s.get('node')}: 拒みの文が違う——手本 {want['text'][:300]!r} ／ "
                                       f"盤面 {self.places.tokenize(str(e))[:300]!r}") from e
            self.counts["reject"] += 1
        else:
            raise ReplayDivergence(f"seq {s['seq']} {s['kind']} {s.get('node')}: 手本は拒んだ（{want['text'][:200]}）が盤面は通した")
        self.reopen()

    def ensure_emitted(self, s):
        """手の節が待っていなければ settle する（engine の next がこの手の前に出した——機械の節も na も無い next は手に残らない）"""
        if self.pending_inst(s["node"]) is None:
            self.settle()
        if self.pending_inst(s["node"]) is None:
            raise ReplayDivergence(f"seq {s['seq']} {s['kind']} {s['node']}: 手本では待っている節が、盤面で待っていない"
                                   f"（{self.b.node_state(s['node'])}）")

    def step(self, s):
        k, nid = s["kind"], s.get("node")
        if s.get("parent") or k in ("init", "open_round"):
            return      # 入れ子の手（engine_run の中の受け付け・周の開き）は親の手の中で起きる
        self.counts["steps"] += 1
        if k in ("builtin", "na"):
            # engine の next の中の手。盤面がその節をまだ回していなければ、ここで台本が next を打った
            if self.b.node_state(nid) == "pending":
                if s.get("repo_before") is not None:
                    restore_repo(self.rs, s["seq"], self.into)
                no_git = (self.rs.scenario, self.rs.run, s["seq"]) in NO_GIT_STEPS
                with _no_git(self.into) if no_git else contextlib.nullcontext():
                    self.settle((s.get("args") or {}).get("accept_tree_change"))
            return
        restore_repo(self.rs, s["seq"], self.into)
        raised = s.get("raised")
        if k == "accept":
            if raised and raised["type"] == "Reject" and "作業ツリーが変わっている" in raised["text"]:
                self.counts["tree"] += 1     # instance.tree_before（NOT_REPRODUCED）: 突合を持たないので当てない
                return
            gap = bool(raised) and raised["type"] == "Reject" and "deps" in raised["text"]
            if not gap:
                self.ensure_emitted(s)
            out = reply(s, self.b)
            if raised:
                self.expect_reject(s, lambda: self.b.accept(nid, out), gap=gap)
            else:
                self.b.accept(nid, out)
        elif k == "engine_run":
            self.ensure_emitted(s)
            got = self.b.run_engine(nid, runner=captured_runner(s, self.b), plan=engine_run_plan(s, self.b))
            if bool(got.get("ok")) != bool(s["result"].get("ok")):
                raise ReplayDivergence(f"seq {s['seq']} engine_run {nid}: 返り {got} ／ 手本 {s['result']}")
        elif k == "answer":
            a = s["args"]
            call = lambda: self.b._answer_record(a["text"], a.get("note") or "")
            self.expect_reject(s, call) if raised else call()
        elif k == "skip":
            call = lambda: self.b._skip_record(nid, s["args"]["reason"])
            self.expect_reject(s, call) if raised else call()
        elif k == "add":
            items = self.places.untokenize(json.loads(s["args"]["file_text"]))
            call = lambda: self.b.add_request(items, s["args"]["reason"])
            self.expect_reject(s, call) if raised else call()
        elif k == "stop":
            call = lambda: self.b.stop(s["args"]["reason"], "stop")
            self.expect_reject(s, call) if raised else call()
        elif k == "patch":
            # works の口を持たない（仕様 9.3）: 人が盤面を手で書いた事実だけを、撮った差分（その手の after）で写す。
            # 盤面の版（state.rev）は盤面自身の保存が数える
            ops = [o for o in self.places.untokenize(s["memory"].get("after") or []) if o["path"] != ["state", "rev"]]
            _apply_ops({"state": self.b.state, "record": self.b.record}, ops)
            self.b.save()
        elif k == "finalize":
            if self.b.state.get("halted"):
                self.reopen(allow_halted=True)     # engine の cmd_finalize と同じく止めた run にも仕上げを書く
            self.b.finalize()
        else:
            raise ReplayDivergence(f"seq {s['seq']}: 知らない手の種類 {k}")

    def run(self) -> dict:
        rs = self.rs
        head = rs[0]
        if head["kind"] != "init" or head.get("raised"):
            raise ValueError(f"{rs.scenario} run {rs.run} は init の通った Run でない")
        d, _ = restore(rs, head["seq"], "after", self.into)
        self.b = board_from_memory(memory_at(rs, head["seq"], "after"), d, self.table)
        cut = cut_step(rs)
        with self.round_hooks():
            for s in rs[1:]:
                if cut is not None and s["seq"] >= cut["seq"]:
                    self.counts["cut"] += 1
                    break
                self.step(s)
            else:
                # 最後の手の後にも台本の next が盤面を保存した（手として撮られない）なら、同じく settle する
                last = memory_at(rs, rs[-1]["seq"], "after")
                fin = json.loads(blob(rs.meta["final"]["memory"]))
                if fin["state"].get("rev", 0) > last["state"].get("rev", 0):
                    self.settle()
        b = self.b
        got = self.places.tokenize({"state": b.state, "record": b.record})
        rounds = dict(self.rounds)
        if b.round not in rounds:
            rounds[b.round] = _view(got["state"], got["record"], b.round)
        return {"rounds": rounds, "final": copy.deepcopy(got)}


def _refuse_runner(steps, cwd, log_dir):
    raise ReplayDivergence(f"通しの再生が手本に無い語を走らせようとした: {steps}")


@contextlib.contextmanager
def _no_git(into):
    empty = pathlib.Path(into) / "empty-bin"
    empty.mkdir(exist_ok=True)
    old = os.environ.get("PATH")
    os.environ["PATH"] = str(empty)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old


def replay(scenario: str, run, into, *, table=None, counts: dict | None = None) -> dict:
    """手本の Run を頭（init の手の後）の盤面から通しで当て、ReplayResult {rounds: {N: {rd, loop, record}}, final: {state, record}}
    （手本の印に戻した写し）を返す（仕様 9.3 の「通し」）。表は NodeTable.everything（渡せば差し替え）。
    - 撮った手の順に、受け付け（accept）・engine が走らせる節（撮った計画と runs で run_engine）・答え・省く（_answer_record・
      _skip_record。done・answer・skip の記録の部分）・依頼（add_request）・止める（stop）・仕上げ（finalize）を当てる。patch の手は
      撮った差分を記憶に当てて保存する。拒まれた手は同じ文で拒むことを確かめ、入れ物を開き直す
    - 機械の節と na は settle に任せる。settle は台本の next に当たる所で打つ: 手本の next の中の手（builtin・na）の節を盤面が
      まだ回していない時、手の節がまだ出ていない時、最後の手の後に台本の next が保存した時（done の後に毎回 settle すると、台本が
      next を打たずに挟んだ patch・stop より前に条件を評価してしまう）。settle の後、出た engine_run の節の計画が任せ先へ落ちる物は
      その場で run_engine（engine は next の中で落とす）
    - 各手の前に対象リポジトリだけを撮った物に戻す。盤面を engine の側から写し直さない（手本の記憶を盤面へ書くのは頭の 1 度だけ）
    - HAND_EDITED_STEPS の手が在る Run は、その手の前で止める
    counts を渡せば、当てた手・settle・計画の落ち・拒み・BoardGap・当てない手（作業ツリーの突合）・止めた手の数を足す"""
    from board import GRAPH_PATH, NodeTable
    rs = load_runs(scenario)[str(run)]
    if not replayable(rs):
        raise ValueError(f"{scenario} run {run} は再生に当てない Run（init で拒まれた・graph が違う）")
    if table is None:
        table = NodeTable.everything(json.loads(GRAPH_PATH.read_text(encoding="utf-8")), GRAPH_SHA)
    r = _Replay(rs, into, table)
    got = r.run()
    if counts is not None:
        for k, v in r.counts.items():
            counts[k] = counts.get(k, 0) + v
    return got
