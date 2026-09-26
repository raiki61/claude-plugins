"""特徴づけのテスト（golden）の固定具を、今の engine の呼び方に写す唯一の所。

固定具（golden/fixtures/<loop>/<名前>.json）は、盤面の置き場のファイル（state.json・record.json・out/…）と、
その盤面に当てる CLI の 1 コマンド（無ければ読むだけの評価）と、git の録った答えを持つ。`observe` はそれを一時の置き場に
広げ、締め口（`world`）の中で engine を呼び、2 つの層に分けた素の辞書を返す:

- contract（外の約束）: コマンドの終了コードと出力・記録（record.json）の変化・盤面の周の印（done・na と理由）・
  節ごとの走らせる判断（Board.applicable）と記録の整合（check_record）。手順 3 の作り替えは、これを変えてはならない
- internal（内部の形）: 規則の表の名前ごとの呼ばれ方と返り（calls）・条件の名前ごとの真偽と理由・loop の状態の変化・
  機械の節の出力。作り替えで作り直してよい（差分は審査に出る）

手順 3 の作り替えが呼び方や盤面の形を変えたら、直すのはここ（`upcast` と `observe` の中）と internal の期待値だけにする。
期待値と固定具は `graphloops/tests/golden_make.py` が作る（手で書かない）。
"""
import contextlib
import datetime
import functools
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import types

PLUGIN = pathlib.Path(__file__).resolve().parents[2]
ROOT = PLUGIN.parent
if str(PLUGIN) not in sys.path:
    sys.path.insert(0, str(PLUGIN))

from engine import advance as _advance  # noqa: E402
from engine import commands as _commands  # noqa: E402
from engine import intake as _intake  # noqa: E402
from engine import rules as _rules  # noqa: E402
from engine import util as _util  # noqa: E402
from engine.board import Board  # noqa: E402
from engine.schema import graph_text  # noqa: E402

GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"
LOOPS = ("review-loop", "review-loop-tdd", "research-loop")
TABLES = ("CONDS", "POST_CHECKS", "BUILTINS", "ENGINE_RUNS", "FAN_OUT", "WRITE_OPS")
fixture_format = 1   # 固定具の形の版（整数）。形を変えたら上げ、upcast に前の版からの写し替えを書く
FROZEN_NOW = "2026-01-01T00:00:00+09:00"
SESSION = "golden-session"
# 固定具の中の置き場の印。広げる時に一時の置き場（と今のプラグイン）に置き換え、観察の中の置き場は印に戻す
TOKENS = ("<RUN>", "<REPO>", "<CFG>", "<INPUT>", "<TMP>", "<HOME>", "<TMPPATH>", "<PLUGIN>", "<ROOT>")
REPLAY = ("init", "next", "done", "answer", "add", "stop", "skip", "thicken", "finalize")


def graph_path(loop):
    return PLUGIN / "graphs" / f"{loop}.json"


def validator_path(loop):
    return ROOT / "scripts" / ("research-record.py" if loop == "research-loop" else "review-record.py")


def load_rules(loop):
    """規則の module（engine と同じ読み方）"""
    from engine.schema import load_graph
    g = graph_path(loop)
    return _rules.load_rules(g, load_graph(g)[0])


def population(loop):
    """覆いの母集団 {表: [名前]}——読み込んだ規則の 6 つの表の全部の名前と、engine.rules.HOOKS のうち規則が持つ物。手で並べない"""
    mod = load_rules(loop)
    got = {t: sorted(getattr(mod, t, {}) or {}) for t in TABLES}
    got["HOOKS"] = sorted(h for h in _rules.HOOKS if callable(getattr(mod, h, None)))
    return got


def upcast(fx):
    """固定具を今の形へ写す。版 1 が今の形なので恒等。形を変えたら、ここに『版 n → n+1』を順に足す（Axon の upcaster と同じ）"""
    if fx.get("format") != fixture_format:
        raise ValueError(f"固定具の形の版 {fx.get('format')!r} を今の形（{fixture_format}）へ写す手が無い")
    return fx


# ---------------------------------------------------------------- 置き場の印
def _forms(p):
    p = str(p)
    return {p, p.replace("\\", "/")}


def _subst(obj, pairs):
    """文字列の葉と辞書の鍵の全部で、pairs（(元, 先) を長い順）を置き換える"""
    if isinstance(obj, str):
        for a, b in pairs:
            if a in obj:
                obj = obj.replace(a, b)
        return obj
    if isinstance(obj, list):
        return [_subst(x, pairs) for x in obj]
    if isinstance(obj, dict):
        return {_subst(k, pairs): _subst(v, pairs) for k, v in obj.items()}
    return obj


class Place:
    """固定具を広げた一時の置き場。印 ⇄ 実パスの対応を持つ"""

    def __init__(self, tmp):
        self.tmp = pathlib.Path(tmp).resolve()   # 実体の綴り（macOS の /var は /private/var への symlink。engine は実体の綴りで書く）
        self.paths = {"<RUN>": self.tmp / "board", "<REPO>": self.tmp / "repo", "<CFG>": self.tmp / "config",
                      "<INPUT>": self.tmp / "input", "<TMP>": self.tmp / "t", "<HOME>": self.tmp / "home",
                      "<TMPPATH>": self.tmp / "elsewhere", "<PLUGIN>": PLUGIN, "<ROOT>": ROOT}
        for k in ("<REPO>", "<CFG>", "<INPUT>", "<TMP>", "<HOME>"):   # <RUN> は盤面が在る固定具だけ作る（init は無い置き場に作る）
            self.paths[k].mkdir(parents=True, exist_ok=True)
        self.to_real = sorted(((t, str(p)) for t, p in self.paths.items()), key=lambda x: -len(x[0]))
        given = pathlib.Path(tmp)
        aliases = [(f, t) for t, p in self.paths.items() if self.tmp in p.parents
                   for f in _forms(given / p.relative_to(self.tmp))] if given != self.tmp else []
        self.to_token = sorted([(f, t) for t, p in self.paths.items() for f in _forms(p)] + aliases, key=lambda x: -len(x[0]))
        # 印どうしの並び: 一時の置き場の下（<RUN> など）を先に、PLUGIN・ROOT を後に（ROOT は PLUGIN を含む）
        ver = _intake.plugin_meta(PLUGIN)[1]
        self.version = ver
        if ver:
            self.to_token.append((ver, "<VERSION>"))

    def real(self, obj):
        return _subst(obj, self.to_real)

    def token(self, obj):
        return _subst(obj, self.to_token)


TEXT_KEY = "<text-file>"   # JSON でないファイルの本文の入れ物の鍵（{"text": …} を返す節の出力と取り違えない綴り）


def write_tree(base, files):
    """{相対パス: JSON の値 | {TEXT_KEY: 文字列}} を base の下に書く"""
    for rel, v in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(v, dict) and set(v) == {TEXT_KEY}:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(v[TEXT_KEY])
        else:
            p.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")


def materialize(fx, place):
    """固定具を置き場に広げる。graph の sha と engine の置き場・版は今の物に差し替える——graph や版の変化は規則の振る舞いではない
    （差し替えないと、graph を 1 字直しただけで『graph が変わった』の痕跡が記録に入り、外の約束の層が赤くなる）"""
    fx = upcast(fx)
    loop = fx["loop"]
    if fx.get("files"):
        place.paths["<RUN>"].mkdir(parents=True, exist_ok=True)
    for key, base in (("files", place.paths["<RUN>"]), ("repo", place.paths["<REPO>"]),
                      ("config", place.paths["<CFG>"]), ("input", place.paths["<INPUT>"])):
        write_tree(base, place.real(fx.get(key) or {}))
    st = place.paths["<RUN>"] / "state.json"
    if st.is_file():
        s = json.loads(st.read_text(encoding="utf-8"))
        s["graph"] = str(graph_path(loop))
        s["graph_sha"] = _util.sha(graph_text(s["graph"]))
        s["engine"] = {"root": str(PLUGIN), "version": place.version}
        s["validator"] = str(validator_path(loop))
        st.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 締め口
class Blocked(BaseException):
    """締め口で止めた子プロセス。BaseException にするのは、規則の `except Exception` に握り潰させず、止めた所まで上げるため"""


def _argv(args):
    return [str(x) for x in ([args] if isinstance(args, (str, bytes, os.PathLike)) else list(args))]


def _systmp():
    import tempfile
    d = tempfile.gettempdir()
    return sorted(_forms(d) | _forms(pathlib.Path(d).resolve()), key=len, reverse=True)


def _git_key(argv, kw, place):
    """git の 1 回の呼び出しの鍵（-C の置き場を除いた引数・一時の index・標準入力の sha）。置き場は印に、engine が
    その場で作る一時のファイル（名前が毎回変わる）は <TMPFILE> に揃える"""
    args = argv[1:]
    if args[:1] == ["-C"]:
        args = args[2:]
    env = kw.get("env") or {}
    extra = {k: env[k] for k in ("GIT_INDEX_FILE",) if k in env}
    inp = kw.get("input")
    if inp is not None:
        extra["stdin_sha"] = hashlib.sha256(inp if isinstance(inp, bytes) else str(inp).encode("utf-8")).hexdigest()[:16]
    key = place.token([args, extra])
    tmps = _systmp()

    def tmpfile(s):
        return "<TMPFILE>" if isinstance(s, str) and any(s.startswith(d) for d in tmps) else s
    key = [[tmpfile(a) for a in key[0]], {k: tmpfile(v) for k, v in key[1].items()}]
    return json.dumps(key, ensure_ascii=False)


class World:
    """締め口の中で起きたこと: 規則の呼ばれ方（calls）・git の答えの引き当て（used・missed）・録った答え（recorded）。
    答えは鍵ごとに呼ばれた順の列で持つ（同じ引数の git status が修正の前後で違う答えを返す）。列を使い切ったら最後の答えを返す"""

    def __init__(self, place, git_answers, record_repo):
        self.place, self.answers, self.record_repo = place, git_answers, record_repo
        self.calls, self.used, self.missed, self.recorded, self.seen = [], set(), [], {}, {}


def _outcome(table, name, ret=None, exc=None):
    """呼ばれた結果の種類。名前で分けず、返りの形で決める（真偽の組・decision・ok・一覧・その他）"""
    if isinstance(exc, Blocked):
        return "blocked"
    if exc is not None:
        if isinstance(exc, _util.Reject):
            return "拒む"
        if isinstance(exc, SystemExit):
            return "die"
        return f"例外 {type(exc).__name__}"
    if isinstance(ret, tuple) and len(ret) == 2 and isinstance(ret[0], bool):
        return "真" if ret[0] else "偽"
    if isinstance(ret, dict) and "decision" in ret:
        return f"decision={ret['decision']}"
    if isinstance(ret, dict) and "ok" in ret:
        return f"ok={ret['ok']}"
    if isinstance(ret, dict) and table.endswith(".plan"):
        return "plan=" + (sorted(ret)[0] if ret else "空")
    if isinstance(ret, list):
        return "一覧あり" if ret else "一覧なし"
    return "返った"


def _wrap(w, table, name, fn):
    @functools.wraps(fn)
    def inner(*a, **k):
        try:
            ret = fn(*a, **k)
        except BaseException as e:
            w.calls.append([table, name, _outcome(table, name, exc=e)])
            raise
        w.calls.append([table, name, _outcome(table, name, ret)])
        return ret
    return inner


class _FrozenDateTime(datetime.datetime):
    """時刻を固めた datetime（init が run_id を時計から作る。固めないと同じ固定具が走らせるたびに違う記録になる）"""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 1, 0, 0, 0, tzinfo=tz) if tz else cls(2026, 1, 1, 0, 0, 0)


_FROZEN_DATETIME_MODULE = types.SimpleNamespace(**{k: getattr(datetime, k) for k in dir(datetime) if not k.startswith("_")})
_FROZEN_DATETIME_MODULE.datetime = _FrozenDateTime


@contextlib.contextmanager
def world(place, git_answers=None, record_repo=None, session=SESSION):
    """engine と規則を呼ぶ間だけ効く締め口。

    - 子プロセス: git は録った答え（`git_answers`）から返す（録る回は `record_repo` の本物に走らせて録る）。検証器（ROOT/scripts/*-record.py）
      だけは本物を走らせる——外の約束の正本なので、録画に差し替えない。ほかの子は全部 Blocked で止める
    - 家・PATH・claude の設定の置き場を一時の置き場へ向ける（手元と CI で答えが割れないように。PATH を空にすると gh・claude を探す口は『無い』に倒れる）
    - 時刻を固める。engine の大域 util.GIT_CWD（Board が開くたびに書き換える）を元に戻す
    - 規則の表とフックを包み、呼ばれた名前と返りを calls に残す（覆いの一覧の材料）"""
    w = World(place, git_answers or {}, record_repo)
    real_run, real_popen = subprocess.run, subprocess.Popen
    real_git = shutil.which("git") if record_repo is not None else None   # PATH を空にする前に引く（録る回だけ本物を走らせる）
    validators = {str(validator_path(loop)) for loop in LOOPS}

    def allowed(argv):
        return len(argv) >= 2 and argv[0] == sys.executable and argv[1] in validators

    def blocked(argv):
        # 名前は機械に依らない綴りで（この Python は python3.14 か python かが走らせ方で変わる）
        return Blocked(f"子プロセス {'python' if argv and argv[0] == sys.executable else pathlib.Path(argv[0]).name if argv else '?'}")

    def fake_popen(args, *a, **k):
        argv = _argv(args)
        if allowed(argv):
            return real_popen(args, *a, **k)
        raise blocked(argv)

    def fake_run(args, *a, **k):
        # 許すのは検証器だけ、答えるのは git だけ、ほかは止める（run が中で Popen を引く作りに頼らない）
        argv = _argv(args)
        if allowed(argv):
            return real_run(args, *a, **k)
        if not argv or pathlib.Path(argv[0]).name not in ("git", "git.exe"):
            raise blocked(argv)
        key = _git_key(argv, k, place)
        text = bool(k.get("text") or k.get("encoding"))
        if w.record_repo is not None:
            argv2 = [real_git or "git", *(str(w.record_repo) if x == str(place.paths["<REPO>"]) else x for x in argv[1:])]
            env = {**os.environ, **(k.get("env") or {})} if k.get("env") else None
            inp = k.get("input")
            if isinstance(inp, str):
                inp = inp.encode("utf-8")
            p = real_popen(argv2, stdin=subprocess.PIPE if inp is not None else subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=env, cwd=str(w.record_repo))
            raw, _ = p.communicate(input=inp, timeout=120)
            text_out = raw.decode("utf-8", "replace")
            for f in sorted(_forms(w.record_repo) | _forms(pathlib.Path(w.record_repo).resolve()), key=len, reverse=True):
                text_out = text_out.replace(f, str(place.paths["<REPO>"]))   # 写した対象リポジトリの置き場は、広げた置き場として録る
            w.recorded.setdefault(key, []).append({"rc": p.returncode, "stdout": place.token(text_out)})
        seq = w.answers.get(key) if w.record_repo is None else w.recorded[key]
        i = w.seen[key] = w.seen.get(key, -1) + 1
        if not seq:
            w.missed.append(key)
            got = {"rc": 128, "stdout": ""}
        else:
            got = seq[min(i, len(seq) - 1)]
            w.used.add(key)
        out = place.real(got["stdout"])
        return subprocess.CompletedProcess(argv, got["rc"], out if text else out.encode("utf-8"), "" if text else b"")

    env_keys = ("HOME", "USERPROFILE", "PATH", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_SESSION_ID", "CLAUDE_PLUGIN_ROOT",
                "CLAUDE_PLUGIN_DATA", "GRAPHLOOPS_ROOT")
    saved_env = {k: os.environ.get(k) for k in env_keys}
    saved_cwd = _util.GIT_CWD
    empty_bin = place.tmp / "bin"
    empty_bin.mkdir(exist_ok=True)
    orig_registry, orig_hook = _rules.registry, _rules.hook

    def registry(rules, name):
        d = orig_registry(rules, name)
        if name not in TABLES or not isinstance(d, dict):   # 表でない名前（graphcheck が引く ACCEPT_KEYS など）は包まない
            return d
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):   # ENGINE_RUNS の行は {plan, reply, fallback}
                out[k] = {kk: _wrap(w, f"{name}.{kk}", k, vv) if callable(vv) else vv for kk, vv in v.items()}
            else:
                out[k] = _wrap(w, name, k, v) if callable(v) else v
        return out

    def hook(rules, name):
        fn = orig_hook(rules, name)
        return _wrap(w, "HOOKS", name, fn) if fn else fn

    swaps = []
    for mod in [m for n, m in list(sys.modules.items()) if n == "engine" or n.startswith("engine.")]:
        for attr, new, old in (("registry", registry, orig_registry), ("hook", hook, orig_hook), ("now", lambda: FROZEN_NOW, _util.now),
                               ("datetime", _FROZEN_DATETIME_MODULE, datetime)):
            if getattr(mod, attr, None) is old:
                swaps.append((mod, attr, old))
                setattr(mod, attr, new)
    try:
        os.environ.update({"HOME": str(place.paths["<HOME>"]), "USERPROFILE": str(place.paths["<HOME>"]),
                           "PATH": str(empty_bin), "CLAUDE_CONFIG_DIR": str(place.paths["<CFG>"]),
                           "CLAUDE_CODE_SESSION_ID": session})
        for k in ("CLAUDE_PLUGIN_ROOT", "CLAUDE_PLUGIN_DATA", "GRAPHLOOPS_ROOT"):
            os.environ.pop(k, None)
        subprocess.run, subprocess.Popen = fake_run, fake_popen
        yield w
    finally:
        subprocess.run, subprocess.Popen = real_run, real_popen
        for mod, attr, old in swaps:
            setattr(mod, attr, old)
        _util.GIT_CWD = saved_cwd
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------- 観察
def _read(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def diff(a, b, path=""):
    """a から b への変化を {道: 新しい値}（消えた欄は "<消えた>"）で。辞書は欄ごとに下る、それ以外は丸ごと"""
    out = {}
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in b:
                out[p] = "<消えた>"
            elif k not in a:
                out[p] = b[k]
            else:
                out.update(diff(a[k], b[k], p))
        return out
    if a != b:
        out[path or "$"] = b
    return out


def _board_marks(s):
    """外の約束として見る盤面の欄: 状態・周・止めた印・人に聞いている問いと、今の周の節の印（done・na と理由・skipped・empty・stopped）"""
    if not s:
        return None
    rd = (s.get("rounds") or [{}])[-1]
    return {"status": s.get("status"), "round": s.get("round"), "halted": s.get("halted"), "pending_human": s.get("pending_human"),
            "rd": {k: (sorted(rd.get(k) or {}) if k in ("done", "empty") else rd.get(k)) for k in ("done", "na", "skipped", "empty", "stopped")}}


def _norm_next(text, place):
    try:
        d = json.loads(text)
    except ValueError:
        return text
    keep = {k: v for k, v in d.items() if k not in ("how", "dir", "ready", "notes")}
    keep["ready"] = [{k: i.get(k) for k in ("id", "node", "mode", "item") if i.get(k) is not None} for i in d.get("ready", [])]
    # engine の置き場を名乗る行（どの engine が回したか）は規則の振る舞いではないので落とす
    keep["notes"] = [n for n in d.get("notes", []) if "<PLUGIN>" not in place.token(n)]
    return keep


def _cli(place, argv):
    """loop.py の 1 コマンドを同じプロセスで走らせる ——{exit, out, err}。入口の拒否の扱い（Reject は 1）は loop.py の __main__ と同じ"""
    sys.path.insert(0, str(PLUGIN / "scripts"))
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("golden_loop_cli", PLUGIN / "scripts" / "loop.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(PLUGIN / "scripts"))
    mod.install_stop_handlers = lambda: None   # 信号の口は pytest の主の口を奪うので張らない
    out, err, code = io.StringIO(), io.StringIO(), 0
    old_argv, old_cwd = sys.argv, os.getcwd()
    sys.argv = ["loop.py", *argv]
    os.chdir(place.paths["<REPO>"])   # 回す側は対象リポジトリで呼ぶ（init は cwd を対象として記録する）
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                mod.main()
            except _util.Reject as e:
                print(f"NG {e}", file=sys.stderr)
                code = 1
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
            except Blocked as e:
                return {"blocked": str(e)}
            except Exception as e:  # noqa: BLE001 — 想定外は 2（loop.py の契約）。trace の行番号は載せない
                print(f"想定外の例外（{type(e).__name__}）: {e}", file=sys.stderr)
                code = 2
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)
    return {"exit": code, "out": out.getvalue(), "err": err.getvalue()}


def _pure(place, loop, w):
    """読むだけの評価: 条件の全部の名前（internal）と、節ごとの走らせる判断・記録の整合（contract）"""
    board = place.paths["<RUN>"]
    contract, internal = {}, {}
    if not (board / "state.json").is_file():
        return contract, internal
    try:
        b = Board(board)
    except (Exception, SystemExit, Blocked) as e:  # noqa: BLE001
        return {"open": f"開けない: {type(e).__name__}"}, internal
    conds = {}
    for name in sorted(_rules.registry(b.rules, "CONDS")):
        conds[name] = _guard(lambda: list(b.cond(name)))
    internal["cond"] = conds
    contract["applicable"] = {nid: _guard(lambda: b.applicable(nid)) for nid, n in sorted(b.nodes.items()) if "cond" in n}
    check = _rules.hook(b.rules, "check_record")
    if check:
        done = _guard(lambda: sorted(b.rd.get("done") or {}))
        contract["check_record"] = done if isinstance(done, str) else {nid: _guard(lambda: check(b, nid)) for nid in done}
    return contract, internal


def _guard(f):
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            return f()
    except Blocked as e:
        return f"blocked: {e}"
    except _util.Reject as e:
        return f"拒む: {e}"
    except SystemExit:
        return "die: " + err.getvalue().strip().removeprefix("NG ")
    except Exception as e:  # noqa: BLE001 — 想定外の落ち方も観察の値にする（縮めの途中で欄が欠けた盤面を見分ける）
        return f"例外 {type(e).__name__}: {e}"


def observe(fx, tmp):
    """固定具を tmp に広げて評価する ——(観察, World)。観察は {"contract": …, "internal": …}（置き場は印に戻してある）"""
    fx = upcast(fx)
    place = Place(tmp)
    materialize(fx, place)
    loop = fx["loop"]
    board = place.paths["<RUN>"]
    rec_repo = fx.get("_record_repo")
    with world(place, fx.get("git"), rec_repo, fx.get("session") or SESSION) as w:
        contract, internal = _pure(place, loop, w)
        cmd = fx.get("command")
        if cmd:
            pre_rec, pre_st = _read(board / "record.json"), _read(board / "state.json")
            pre_outs = {p.relative_to(board).as_posix(): p.read_bytes() for p in board.glob("out/**/*.json")}
            argv = place.real(cmd)
            if argv[0] != "init":
                argv = [*argv, "--dir", str(board)]
            got = _cli(place, argv)
            if "blocked" not in got and argv[0] == "next" and got["exit"] == 0:
                got["out"] = _norm_next(got["out"], place)
            contract["command"] = got
            post_rec, post_st = _read(board / "record.json"), _read(board / "state.json")
            contract["record"] = diff(pre_rec or {}, post_rec or {})
            contract["board"] = diff(_board_marks(pre_st) or {}, _board_marks(post_st) or {})
            internal["loop"] = diff((pre_st or {}).get("loop") or {}, (post_st or {}).get("loop") or {})
            outs = {}
            for p in sorted(board.glob("out/**/*.json")):
                rel = p.relative_to(board).as_posix()
                if pre_outs.get(rel) != p.read_bytes():
                    outs[rel] = _read(p)
            internal["outputs"] = outs
        internal["calls"] = sorted({tuple(c) for c in w.calls})
    return platform_norm(place.token({"contract": contract, "internal": internal})), w


def platform_norm(obj):
    """区切りが \\ の OS では、文字列の中の \\ を全部 / に揃える（engine が OS の区切りでパスを書くため）。
    期待値の側にも同じ物を当てて比べる（期待値の中の本物の \\ も同じく / になる）。区切りが / の OS では何もしない"""
    if os.sep == "/":
        return obj
    return json.loads(json.dumps(obj, ensure_ascii=False).replace("\\\\", "/"))


def load_fixture(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def fixture_paths():
    return sorted((GOLDEN / "fixtures").glob("*/*.json"))


def expect_path(layer, fixture):
    fixture = pathlib.Path(fixture)
    return GOLDEN / "expect" / layer / fixture.parent.name / fixture.name


def jsonable(obs):
    """観察を JSON に通した形（tuple→list・鍵の型を JSON に揃える）——期待値のファイルと同じ形で比べるため"""
    return json.loads(json.dumps(obs, ensure_ascii=False))


# ---------------------------------------------------------------- 覆い
PREDICATE_TABLES = frozenset({"CONDS", "POST_CHECKS", "BUILTINS", "FAN_OUT"})   # 真偽・可否・決定・項目を返す口の表


def coverage(loop, internal_expectations):
    """期待値（internal の calls）から、母集団の名前ごとに覆ったか・覆っていないかと理由を機械で出す。

    どの口も、見えた結果が 2 通り以上なら『覆った』（covered。例: 条件の真と偽・受け付けの通すと拒む・check_record の一覧ありとなし）。
    結果が 1 通りのとき、真偽・可否を返す表（PREDICATE_TABLES）の口は『片側だけ』で覆っていない側に置き、手続きの口（フック・書き込み・
    走らせる計画）は、止められずに呼ばれたら『呼ばれた』（called）——呼ばれた後に何を書いたかは
    その固定具の期待値（記録の変化）が固定するが、呼ばれ方の幅（例: 素材の findings が 2 件以上）までは数えないので、覆ったとは名乗らない
    （実測 2026-09-26: material_from_findings の detail の区切りを変えても網は緑だった——固定具の findings が 1 件以下）。
    止められた（blocked）・die は結果に数えない"""
    seen = {}
    for calls in internal_expectations:
        for table, name, outcome in calls:
            t = table.split(".")[0]
            seen.setdefault((t, name), set()).add(outcome)
    out = {}
    for table, names in population(loop).items():
        rows = {}
        for name in names:
            got = seen.get((table, name), set())
            real = sorted(o for o in got if o not in ("blocked", "die"))
            if len(real) >= 2:
                rows[name] = {"covered": real}
            elif real and table not in PREDICATE_TABLES:
                rows[name] = {"called": real}
            elif real:
                rows[name] = {"uncovered": f"片側だけ（見えた結果: {'・'.join(real)}）"}
            elif "blocked" in got:
                rows[name] = {"uncovered": "締め口で止めた（git 以外の子プロセスを起こす・録った git に無い）"}
            elif "die" in got:
                rows[name] = {"uncovered": "固定具の上では die で止まった"}
            else:
                rows[name] = {"uncovered": "どの固定具でも呼ばれていない（入口が固定具に無い）"}
        out[table] = rows
    return out


# ---------------------------------------------------------------- 衛生
size_limit = 64 * 1024   # 固定具 1 つの上限（バイト）


def forbidden_in(text):
    """固定具・期待値に残ってはいけない形（家のパス・一時の置き場・この機械の利用者名・秘密）の当たり。
    利用者名は字面で書かず、走らせた機械の物を引く（字面を書くと、この検査のファイルそのものが写し込みになる）"""
    import getpass
    pats = [r"/(?:Users|home)/[^/<\s\"\\]+", r"(?:/private)?/(?:var/folders|tmp)/", r"[A-Za-z]:\\\\Users\\\\",
            r"sk-an[t]-[A-Za-z0-9]", r"gh[pousr]_[A-Za-z0-9]{20}", r"github_pa[t]_[A-Za-z0-9]"]   # 字面の鍵の頭を書かない（網の走査に当たらないように）
    home = str(pathlib.Path.home())
    hits = [m.group(0) for p in pats for m in re.finditer(p, text)]
    if home and len(home) > 3 and home in text:
        hits.append(home)
    try:
        user = getpass.getuser()
    except (OSError, KeyError, ImportError):
        user = ""
    if len(user) >= 3:
        hits += [m.group(0) for m in re.finditer(rf"[/\\]{re.escape(user)}(?=[/\\\"]|$)", text)]
    return hits
