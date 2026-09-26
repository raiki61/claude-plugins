"""盤面の手本の撮り手（仕様 9.2 の 3）。make.py が子の loop.py に PYTHONPATH で読ませる。

働くのは、起こされたのが loop.py（sys.argv[0] の名前）で、環境に WORKS_GOLDEN_OUT が在るときだけ。台本のテストの語・
検証器・engine が走らせる語の子にも PYTHONPATH は継がれるので、それ以外では何もしない（import もしない）。

包み方: 書き出した graphloops の engine の module を loop.py より先に import し、module の属性を替える（loop.py は後で
同じ module を import し、サブコマンドの関数を main() の中で引くので、包んだ物が使われる）。
- engine.commands.Board を RecordingBoard に替える。applicable() の上書きで、条件に当たらない節（na）を {node, why} で撮る
  （advance の中の直の代入で、関数として包めないため）。
- 手として撮る関数: advance.run_driver_node（builtin）・advance.open_next_round と commands.open_next_round（open_round）・
  commands.accept_output（accept）・cmd_init・cmd_add・cmd_answer・cmd_skip・cmd_stop・cmd_patch・cmd_finalize・
  commands.launch_engine_run（engine_run。走らせる語の返りを撮るため commands.run_steps も覗く）。

1 手ごとに撮る物（WORKS_GOLDEN_OUT の下へ。make.py が場面ごとに集めて差分に直す）:
- 手の前後の記憶（盤面を引数に取る関数は記憶の中の b.state・b.record、サブコマンドの関数はディスクの state.json・record.json）
- 手の前後のディスクの目録（盤面の置き場の全部から state.json・record.json・trace.jsonl・prompts/・roles/・*.pgid を除いた物）
- 手の前の対象リポジトリの目録（作業ツリーと .git の objects・refs・HEAD・index、人の方針の文書 .git/graphloops/policy.md）
目録はパス → 中身の sha256 で、中身は blobs/<sha256>.gz。記憶と目録は raw/mem・raw/man に中身の sha で 1 度だけ置く。
起動の終わり（atexit）には、ディスクの記憶と目録を raw/end に撮る（Run の最後の起動の後の盤面。make.py の final）。
入れ子の手（converge や answer の中の open_round・engine_run の中の accept）は parent に親の手の番号を持つ。
絶対パスは中身も記憶も @BOARD@・@REPO@・@RUN@・@CORE@・@PY@・@WORK@・@TMPDIR@・@HOME@ に置き換える（/var と /private/var の両方の綴り）。
"""
import os
import sys


def _main():
    out = os.environ.get("WORKS_GOLDEN_OUT")
    if not out or not sys.argv or os.path.basename(sys.argv[0]) != "loop.py":
        return
    try:
        _install(out)
    except BaseException as e:  # 撮り手が入れないなら、その事実を残して loop.py はそのまま走らせる（作り手が止まる）
        _note_error(out, f"install: {type(e).__name__}: {e}")


def _note_error(out, text):
    try:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "recorder-errors.txt"), "a", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {' '.join(sys.argv[:2])}: {text}\n")
    except OSError:
        pass


def _install(out_dir):
    import fcntl
    import functools
    import gzip
    import hashlib
    import json
    import pathlib
    import tempfile
    import threading

    out = pathlib.Path(out_dir)
    argv = sys.argv[1:]

    def flag(name):
        for i, w in enumerate(argv):
            if w == name and i + 1 < len(argv):
                return argv[i + 1]
            if w.startswith(name + "="):
                return w.split("=", 1)[1]
        return None

    d = flag("--dir")
    if not d:
        return
    board = pathlib.Path(os.path.realpath(d))
    repo = pathlib.Path(os.path.realpath(os.getcwd()))
    plugin = pathlib.Path(sys.argv[0]).resolve().parent.parent
    sys.path.insert(0, str(plugin))
    import engine.advance as A
    import engine.board as EB
    import engine.commands as C
    import engine.util as U

    # ---- パスの置き換え
    def spellings(p):
        got = {str(p), os.path.realpath(str(p))}
        for x in list(got):
            for a, b in (("/private/var/", "/var/"), ("/private/tmp/", "/tmp/")):
                if x.startswith(a):
                    got.add(b + x[len(a):])
                elif x.startswith(b):
                    got.add(a + x[len(b):])
        return got

    places = [("@BOARD@", board), ("@REPO@", repo)]
    if board.parent == repo.parent:
        places.append(("@RUN@", board.parent))
    for token, env in (("@CORE@", "WORKS_GOLDEN_CORE"), ("@PY@", "WORKS_GOLDEN_PY"), ("@WORK@", "WORKS_GOLDEN_WORK")):
        if os.environ.get(env):
            places.append((token, os.environ[env]))
    places += [("@TMPDIR@", tempfile.gettempdir()), ("@HOME@", str(pathlib.Path.home()))]
    pairs = sorted({(s, t) for t, p in places for s in spellings(p) if len(s) > 1}, key=lambda x: -len(x[0]))
    bpairs = [(s.encode("utf-8"), t.encode("utf-8")) for s, t in pairs]

    def norm_text(s):
        for a, b in pairs:
            s = s.replace(a, b)
        return s

    def norm_bytes(data):
        for a, b in bpairs:
            data = data.replace(a, b)
        return data

    # ---- 置き場（中身の sha で 1 度だけ）
    def put(sub, data, name=None):
        name = name or hashlib.sha256(data).hexdigest()
        p = out / sub / f"{name}.gz"
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}")
            tmp.write_bytes(gzip.compress(data, 6))
            os.replace(tmp, p)
        return name

    def put_json(sub, obj):
        return put(sub, json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8"))

    def snap(state, record):
        """記憶の写し（置き換えた JSON）の sha"""
        txt = norm_text(json.dumps({"state": state, "record": record}, ensure_ascii=False))
        return put_json("raw/mem", json.loads(txt))

    def disk_memory():
        try:
            st = json.loads((board / "state.json").read_text(encoding="utf-8"))
            rec = json.loads((board / "record.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return snap(st, rec)

    cache = {}

    def file_sha(p):
        st = p.stat()
        key = (str(p), st.st_size, st.st_mtime_ns)
        got = cache.get(key)
        if got is None:
            got = cache[key] = put("blobs", norm_bytes(p.read_bytes()))
        return got

    def listing(top, keep):
        if not top.is_dir():
            return None
        got = {}
        for root, dirs, files in os.walk(top):
            rel_root = pathlib.Path(root).relative_to(top)
            dirs[:] = sorted(x for x in dirs if keep(rel_root / x, True))
            for f in sorted(files):
                rel = rel_root / f
                if keep(rel, False):
                    p = pathlib.Path(root) / f
                    if p.is_file() and not p.is_symlink():
                        got[rel.as_posix()] = file_sha(p)
        return got

    def keep_board(rel, is_dir):
        parts = rel.parts
        if len(parts) == 1 and parts[0] in (("prompts", "roles") if is_dir else ("state.json", "record.json", "trace.jsonl")):
            return False
        return is_dir or not parts[-1].endswith(".pgid")

    def keep_repo(rel, is_dir):
        parts = rel.parts
        if parts[0] != ".git":
            return True
        if len(parts) == 1:
            return is_dir
        if parts[1] == "graphloops":   # 人の方針の文書の既定の置き場（RL の policy_input が読む。作業ツリーの外）
            return parts[2:] == (() if is_dir else ("policy.md",))
        return parts[1] in (("objects", "refs") if len(parts) > 2 or is_dir else ("HEAD", "index", "objects", "refs"))

    def disk_listing():
        m = listing(board, keep_board)
        return None if m is None else put_json("raw/man", m)

    def repo_listing():
        m = listing(repo, keep_repo)
        return None if m is None else put_json("raw/man", m)

    # ---- 手の番号と行
    tlock = threading.RLock()

    def next_seq():
        with tlock:
            out.mkdir(parents=True, exist_ok=True)
            with open(out / "seq.lock", "a+", encoding="utf-8") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                p = out / "seq.txt"
                n = int(p.read_text(encoding="utf-8") or 0) + 1 if p.exists() else 1
                p.write_text(str(n), encoding="utf-8")
                return n

    base_row = {"scenario": os.environ.get("WORKS_GOLDEN_SCENARIO", ""), "board_raw": str(board),
                "pid": os.getpid(), "cmd": argv[0] if argv else ""}

    def write_row(row):
        row = {**base_row, **row}
        p = out / "raw" / "rows" / f"{row['seq']:09d}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")

    def clean(obj):
        return json.loads(norm_text(json.dumps(obj, ensure_ascii=False, default=str)))

    def raised_of(e, die_before):
        if isinstance(e, SystemExit):
            text = U.LAST_DIE if U.LAST_DIE is not die_before and U.LAST_DIE is not None else f"exit {e.code}"
        else:
            text = getattr(e, "msg", None) or str(e)
        return {"type": type(e).__name__, "text": norm_text(str(text))}

    def guarded(fn):
        """撮り手の中の失敗は置き場に残してから上げる（黙って欠けた手本を作らない）"""
        @functools.wraps(fn)
        def inner(*a, **kw):
            try:
                return fn(*a, **kw)
            except Exception as e:
                _note_error(out_dir, f"{fn.__name__}: {type(e).__name__}: {e}")
                raise
        return inner

    local = threading.local()

    def parent():
        stack = getattr(local, "stack", None)
        return stack[-1] if stack else None

    def push(seq):
        if getattr(local, "stack", None) is None:
            local.stack = []
        local.stack.append(seq)

    def pop():
        local.stack.pop()

    def step(kind, node, args, mem_before, mem_after, call, extra=None):
        """1 手を撮る: 番号を取り、前を撮り、呼び、後を撮って行を書く"""
        seq = next_seq()
        row = {"seq": seq, "parent": parent(), "kind": kind, "node": node, "args": clean(args)}
        row["mem_before"] = guarded(mem_before)()
        row["disk_before"] = guarded(disk_listing)()
        row["repo_before"] = guarded(repo_listing)()
        die_before = U.LAST_DIE
        push(seq)
        try:
            res = call()
        except BaseException as e:
            pop()
            row["raised"] = raised_of(e, die_before)
            after = guarded(mem_after)(True)
            if after is not None:
                row["mem_after"] = after
            row["disk_after"] = guarded(disk_listing)()
            if extra:
                row.update(clean(extra(None)))
            write_row(row)
            raise
        pop()
        row["mem_after"] = guarded(mem_after)(False)
        row["disk_after"] = guarded(disk_listing)()
        if extra:
            row.update(clean(extra(res)))
        write_row(row)
        return res

    def of_board(b):
        """盤面を引数に取る関数: 記憶の中の b.state・b.record。拒んだ（例外）なら後は無し（盤面は捨てられる）"""
        return (lambda: snap(b.state, b.record)), (lambda raised: None if raised else snap(b.state, b.record))

    def of_disk():
        """サブコマンドの関数: ディスクの記憶。例外でも版が進んでいれば（保存した後の exit）後を撮る"""
        seen = {}

        def before():
            seen["rev"] = _rev()
            return disk_memory()

        def after(raised):
            if raised and _rev() == seen.get("rev"):
                return None
            return disk_memory()
        return before, after

    def _rev():
        try:
            return json.loads((board / "state.json").read_text(encoding="utf-8")).get("rev")
        except (OSError, ValueError):
            return None

    # ---- 条件の na（RecordingBoard）
    class RecordingBoard(EB.Board):
        def applicable(self, nid):
            why = super().applicable(nid)
            if why:
                write_row({"seq": next_seq(), "parent": parent(), "kind": "na", "node": nid, "args": {},
                           "na": {"node": nid, "why": norm_text(why)}})
            return why

    C.Board = RecordingBoard

    # ---- 盤面を引数に取る関数
    orig_driver = A.run_driver_node

    def run_driver_node(b, nid, n, notes):
        before, after = of_board(b)
        k = len(notes)
        return step("builtin", nid, {"builtin": n.get("builtin"), "accept_tree_change": getattr(b, "accept_tree_change", None)},
                    before, after, lambda: orig_driver(b, nid, n, notes),
                    extra=lambda res: {"result": {"progressed": res, "notes": notes[k:]}})
    A.run_driver_node = run_driver_node

    def wrap_open(orig):
        def open_next_round(b, nid):
            before, after = of_board(b)
            return step("open_round", nid, {}, before, after, lambda: orig(b, nid),
                        extra=lambda res: {"result": {"opened": res}})
        return open_next_round
    A.open_next_round = wrap_open(A.open_next_round)
    C.open_next_round = wrap_open(C.open_next_round)

    orig_accept = C.accept_output

    def accept_output(b, node, text, read_from, agent_id=None, accept_tree_change=None):
        er = getattr(local, "engine_run", None)
        if er is not None and not er.get("closed"):
            er["close"](snap(b.state, b.record))
        before, after = of_board(b)
        inst = (b.rd.get("instances") or {}).get(node) or {}
        return step("accept", inst.get("node") or node.split("[")[0],
                    {"instance": node, "text": text, "read_from": read_from, "agent_id": agent_id,
                     "accept_tree_change": accept_tree_change},
                    before, after, lambda: orig_accept(b, node, text, read_from, agent_id=agent_id,
                                                       accept_tree_change=accept_tree_change))
    C.accept_output = accept_output

    # ---- engine が走らせる節: 走らせる（engine_run）と受け付け（accept）に分けて撮る
    orig_steps = C.run_steps

    def run_steps(steps, cwd, log_dir, **kw):
        runs = orig_steps(steps, cwd, log_dir, **kw)
        er = getattr(local, "engine_run", None)
        if er is not None:
            got = []
            for r in runs:
                r2 = dict(r)
                for k in ("out", "err"):
                    try:
                        r2[k + "_text"] = pathlib.Path(r[k]).read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        r2[k + "_text"] = None
                got.append(r2)
            er["runs"] = got
        return runs
    C.run_steps = run_steps

    orig_launch = C.launch_engine_run

    def launch_engine_run(d, inst):
        seq = next_seq()
        row = {"seq": seq, "parent": parent(), "kind": "engine_run", "node": inst.get("node"),
               "args": clean({"instance": inst.get("id")})}
        row["mem_before"] = guarded(disk_memory)()
        row["disk_before"] = guarded(disk_listing)()
        row["repo_before"] = guarded(repo_listing)()
        er = {"runs": None, "closed": False}

        def close(mem_after, result=None):
            er["closed"] = True
            row["mem_after"] = mem_after
            row["disk_after"] = guarded(disk_listing)()
            row["engine_run"] = clean({"plan": inst.get("launch"), "runs": er["runs"] or []})
            if result is not None:
                row["result"] = clean(result)
            write_row(row)
        er["close"] = close
        local.engine_run = er
        push(seq)
        try:
            res = orig_launch(d, inst)
        except BaseException as e:
            if not er["closed"]:
                row["raised"] = raised_of(e, None)
                close(guarded(disk_memory)())
            raise
        finally:
            local.engine_run = None
            pop()
        if not er["closed"]:
            close(guarded(disk_memory)(), {k: res.get(k) for k in ("ok", "why", "fell_back", "superseded")})
        else:
            # 受け付けまで進んだ回: 行は受け付けの頭で書いた。結果は受け付けの行の後に要約として足す
            p = out / "raw" / "rows" / f"{seq:09d}.json"
            got = json.loads(p.read_text(encoding="utf-8"))
            got["result"] = clean({k: res.get(k) for k in ("ok", "why", "fell_back", "superseded")})
            p.write_text(json.dumps(got, ensure_ascii=False), encoding="utf-8")
        return res
    C.launch_engine_run = launch_engine_run

    # ---- サブコマンドの関数
    def args_of(a, *drop):
        got = {k: v for k, v in vars(a).items() if k not in ("fn", "dir", *drop)}
        f = got.get("file")
        if f:
            try:
                got["file_text"] = pathlib.Path(f).read_text(encoding="utf-8")
            except OSError:
                got["file_text"] = None
        return got

    def wrap_cmd(name, kind, node_of=lambda a: None):
        orig = getattr(C, name)

        def cmd(a):
            if kind == "init":
                before, after = (lambda: None), (lambda raised: None if raised else disk_memory())
            else:
                before, after = of_disk()
            return step(kind, node_of(a), args_of(a), before, after, lambda: orig(a))
        cmd.__name__ = name
        setattr(C, name, cmd)

    wrap_cmd("cmd_init", "init")
    wrap_cmd("cmd_add", "add")
    wrap_cmd("cmd_answer", "answer")
    wrap_cmd("cmd_skip", "skip", lambda a: a.node)
    wrap_cmd("cmd_stop", "stop")
    wrap_cmd("cmd_patch", "patch")
    wrap_cmd("cmd_finalize", "finalize")

    # ---- 起動の終わりの盤面（Run の最後の起動の分が手の after に入らないため。make.py は Run ごとに番号の最も大きい物を使う）
    import atexit

    def at_end():
        try:
            mem = disk_memory()
            if mem is None:
                return
            row = {**base_row, "seq": next_seq(), "memory": mem, "disk": disk_listing(), "repo": repo_listing()}
            p = out / "raw" / "end" / f"{row['seq']:09d}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            _note_error(out_dir, f"at_end: {type(e).__name__}: {e}")
    atexit.register(at_end)


_main()
