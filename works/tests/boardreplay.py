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
import copy
import gzip
import hashlib
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

from board import BOARD_VERSION, CORE_DIR, GRAPH_SHA, DiskBoard  # noqa: E402

# ---------------------------------------------------------------- 比べない欄（仕様 9.3）
# 名前 → 理由。試験の出力に毎回並べる。足すときは理由を書いて足す（ずれを見つけたら board.py を直すのが先）
NOT_REPRODUCED = {
    # 時刻
    "at": "時刻（周の箱の done・問いなどに engine が刻む）",
    "t": "時刻（trace の行）",
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
    "instance.launch": "役の起動を持たない（engine_run の steps・sha は比べる）",
    "instance.tree_before": "役ごとの作業ツリーの前後の突合を持たない（v1 の写しが持つ）。突合で拒む手（作業ツリーが変わった）も当てない",
    "instance.attempts": "起こし直しを持たない",
    "instance.attempt_log": "起こし直しを持たない",
    "instance.pointers": "一覧を固めた番号の控えを持たない（番号で書いた返答は engine の文で拒む。仕様 BL17）",
    "instance.delegate": "任せ先の起動を持たない",
    "instance.agent_id": "役の会話の番号は Archon が持つ（accept は受け取らない）",
    "instance.read_from": "返答を読んだ先（accept は返答の dict を受け取る）",
    "state.git_mismatches": "作業ツリーの突合（tree_before）を持たないので、突合を受け入れた控えも残らない",
    # 受け付けの中で持たない物（仕様 4.1。a1202d0 の graph に fan_out・thickness_from の節は無い）
    "扇の被覆（fan_out.cover）": "扇の節の答えの欠けを出し直す所を持たない（a1202d0 の graph に扇の節は無い）",
    "段の昇格（thickness_from）": "段の昇格を持たない（a1202d0 の graph は段を持たない）",
    "disk:report.md": "本文の保存（節の save_text_as）を持たない。報告の本文は works のブロックが書く",
    "disk:count-budget.json#seconds": "RL が数える問いを走らせた時間（回数 calls と周は比べる）",
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
_INSTANCE_KEYS = {k.split(".", 1)[1] for k in NOT_REPRODUCED if k.startswith("instance.")}
_RUN_KEYS = {k.split(".", 1)[1] for k in NOT_REPRODUCED if k.startswith("runs[].")}
_DISK_PATHS = {k.split(":", 1)[1] for k in NOT_REPRODUCED if k.startswith("disk:") and "#" not in k}
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
            inst = len(p) == 6 and p[:2] == ("state", "rounds") and p[3] == "instances"
            if inst and k == "launch":
                v = {x: v[x] for x in ("steps", "sha") if isinstance(v, dict) and x in v}
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


def board_from_memory(mem: dict, board_dir, table) -> DiskBoard:
    """memory_at の返り（手本の印のまま）から盤面を組む: 印を実パスに戻し、state.works = {board_version} を足して
    state.json・record.json を書き、DiskBoard.open で開く（置き場は restore の形）"""
    places = Places.of_board(board_dir)
    mem = places.untokenize(mem)
    state, record = mem["state"], mem["record"]
    state["works"] = {"board_version": BOARD_VERSION}
    d = pathlib.Path(board_dir)
    (d / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (d / "trace.jsonl").touch()
    return DiskBoard.open(d, table=table, repo=places.repo)


def reply(step: Step, board: DiskBoard, names: bool = True) -> dict:
    """accept の手の返答の本文を、accept に渡す dict にする（engine の accept_output と同じ読み方: schema の無い節は本文の
    text）。本文の中の印（役が名指した盤面の置き場など）は、その盤面の置き場の実パスに戻す。
    names=True なら、台本の役が番号で書いた欄を、手の前の instance が固めていた一覧（instance.pointers）で名前に直す
    （engine は控えで読み替えるが、DiskBoard は控えを持たず番号を拒む〔BL17〕。ラインの役は名前で書く。
    NOT_REPRODUCED の instance.pointers）。直せない番号はそのまま残す"""
    from engine.commands import parse_output
    from engine.pointers import resolve
    text = Places.of_board(board.dir).untokenize(step["args"]["text"])
    n = board.nodes[step["node"]]
    if not n.get("schema"):
        return {"text": text}
    out = parse_output(text)
    snap = (board.rd["instances"].get(step["node"]) or {}).get("pointers")
    if names and snap and n.get("pointers"):
        named = copy.deepcopy(out)
        if not resolve(named, n["pointers"], snap):
            return named
    return out


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


def disk_diff(board_dir, expected: dict) -> list:
    """盤面の置き場の目録と、手本の目録 expected の違いの文の一覧（NOT_REPRODUCED のパスと欄を除く。空なら同じ）"""
    places = Places.of_board(board_dir)
    got = disk_listing(board_dir)
    out = []
    for p in sorted((expected.keys() | got.keys()) - _DISK_PATHS):
        if p not in got:
            out.append(f"disk:{p}: 手本に在るが盤面の置き場に無い")
        elif p not in expected:
            out.append(f"disk:{p}: 盤面の置き場に在るが手本に無い")
        elif expected[p] != got[p]:
            drop = _DISK_FIELDS.get(p)
            if drop:
                a = {k: v for k, v in json.loads(blob(expected[p])).items() if k not in drop}
                b = {k: v for k, v in json.loads(places.tokenize_bytes((pathlib.Path(board_dir) / p).read_bytes())).items()
                     if k not in drop}
                if a == b:
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
