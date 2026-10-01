"""起動の殻の共通の口（設計書 works/docs/specs/2026-09-29-launch-core-design.md の 2.2・2.3）。

python3 -I works/dev/launch.py env --for=<殻> [--claude] [--show] [--target <解いた対象の根>] [--adapter <包みの実パス>]
python3 -I works/dev/launch.py ledger save|load|list|bind …（下の LEDGER_USAGE）

env: 殻 4 本（use.sh・dogfood.sh・real-run.sh・archon.sh）の家の既定・claude の解決・包みの既定とラインの入力 adapter の値
（WORKS_LAUNCH_ADAPTER_MODE）を 1 か所で持ち、sh の代入の行で返す。--show は dogfood.sh --show の時だけ渡す。
殻は guard.sh の works_dev_launch_env で 2 段に受ける（1 段の eval "$(…)" では部品の失敗が消える）。
ledger: run の控え <置き場>/<run-id>.json の形（版の欄 schema）と、起動の後に run を結ぶ規則を 1 か所で持つ。save は書き、
list は lib.sh works_dev_ledgers のタブ区切りの 5 欄で読み、load は use.sh が続きで Archon を起こす値を代入の行で返し、
bind は標準入力の run の一覧から、盤面の依頼がこの起動の依頼の写しと一致する run がちょうど 1 本の時だけ結んで控えを書く。
代入の行を返す動詞の 1 行目は版の行 WORKS_LAUNCH_FORMAT=1。値は shlex.quote で囲み、名は動詞ごとの許した一覧に在る物だけを出す
（shlex.quote は名を守らない）。
claude が見つからなくても WORKS_LAUNCH_CLAUDE を空で返して 0 で終わる。止めるか・どの文言で止めるかは殻の今の場所が決める。
失敗（使い方の誤り・家の根が決まらない・知らない版の控え）は標準出力に何も出さず、標準エラーに 1 行を出して 2 で終わる。
bind が結べない時は標準出力に何も出さず、理由と候補を標準エラーに出して 1 で終わる。
標準ライブラリだけ・Python 3.9 の構文で書き、pack の兄弟を import しない。子のプロセスは起こさない。
"""
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
import time

FORMAT = "1"
NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
ALLOWED_NAMES = frozenset({"WORKS_DEV_HOME", "WORKS_STATE_ROOT", "WORKS_USE_HOME", "WORKS_LAUNCH_CLAUDE",
                           "WORKS_DEV_ADAPTER", "WORKS_LAUNCH_ADAPTER_MODE"})
# 控えから出す名と、結んだ run を渡す名。env の名とは分けて持つ（env が控えの名を出せないように）
LEDGER_LOAD_NAMES = frozenset({"WORKS_DEV_MODEL", "WORKS_MODEL_PINNED", "CLAUDE_BIN_PATH", "WORKS_KEYCHAIN_ITEM",
                               "WORKS_DEV_ADAPTER"})
LEDGER_BIND_NAMES = frozenset({"WORKS_RUN_ROW", "WORKS_RUN_ID", "WORKS_RUN_STATUS"})
LEDGER_SCHEMA = 1
USAGE = ("launch.py env --for=<use.sh|dogfood.sh|real-run.sh|archon.sh> [--claude] [--show] [--target <path>]"
         " [--adapter <path>]")
LEDGER_USAGE = ("launch.py ledger save --dir <置き場> --run-id <id> --target <dir> --model-value <値> --model-from <出どころ>"
                " [--wrap-ref <参照>] [--github-reads <読み出しのファイル>] | ledger list --dir <置き場> [--run-id <id>] | ledger load --dir <置き場> --run-id <id>"
                " | ledger bind --for <呼び手> --dir <置き場> --target <dir> --request <依頼の写し> --model-value <値>"
                " --model-from <出どころ> [--wrap-ref <参照>] [--github-reads <読み出しのファイル>]（標準入力に archon workflow runs --json）")


class Refused(Exception):
    pass


class Unbound(Exception):
    """bind が run を結べない。文はそのまま標準エラーに出す（呼び手の名で始まる）"""


def _get(environ, name):
    """sh の ${X:-} と同じく、空は未設定と同じに扱う"""
    return environ.get(name) or ""


def _dev_home(environ, target):
    # 字を連ねる（os.path.join にしない）: ${TMPDIR:-/tmp}/works-dev は TMPDIR の末尾の / を残す
    return {"WORKS_DEV_HOME": _get(environ, "WORKS_DEV_HOME") or (_get(environ, "TMPDIR") or "/tmp") + "/works-dev"}


def _use_home(environ, target):
    # 既定の家は対象の clone ごと（設計書 2.7）。環境の WORKS_DEV_HOME は継がない
    if not target:
        raise Refused("use.sh は --target <解いた対象の根> が要る")
    state = _get(environ, "XDG_STATE_HOME")
    if not state:
        if not _get(environ, "HOME"):
            raise Refused("HOME も XDG_STATE_HOME も無いので、利用の家の根が決まらない。HOME を設定する")
        state = environ["HOME"] + "/.local/state"
    root = state + "/works"
    home = _get(environ, "WORKS_USE_HOME") or root + "/use-" + hashlib.sha256(target.encode()).hexdigest()[:8]
    return {"WORKS_STATE_ROOT": root, "WORKS_USE_HOME": home, "WORKS_DEV_HOME": home}


def _on_path(environ):
    found = shutil.which("claude", path=environ.get("PATH", os.defpath)) or ""
    return found if found.startswith("/") else ""   # 相対の当たり（PATH の相対の要素）は実行ファイルのパスにしない


def _claude(environ, adapter):
    return _get(environ, "CLAUDE_BIN_PATH") or _on_path(environ)


def _real_claude(environ, adapter):
    # 包みを通す時に CLAUDE_BIN_PATH が包み自身を差していれば、本物として使わない
    named = _get(environ, "CLAUDE_BIN_PATH")
    if named and adapter and os.path.realpath(named) == os.path.realpath(adapter):
        named = ""
    return _get(environ, "WORKS_REAL_CLAUDE") or named or _on_path(environ)


def _adapter_mode(value):
    # ラインの入力 adapter: 包みを通す（1）なら空＝包みを求める、それ以外は optional
    return {"WORKS_LAUNCH_ADAPTER_MODE": "" if value == "1" else "optional"}


def _adapter_default_on(environ, show):
    # sh の ${X-1} と同じく未設定だけに既定を入れ、空・0 の明示は包みを外すのでそのまま出す（値の検査は archon.sh）。
    # --show は続きの行の前置きが包みを通した run にだけ WORKS_DEV_ADAPTER=1 を載せるので、無ければ外した run
    value = environ["WORKS_DEV_ADAPTER"] if "WORKS_DEV_ADAPTER" in environ else ("" if show else "1")
    return {"WORKS_DEV_ADAPTER": value, **_adapter_mode(value)}


def _adapter_inherit(environ, show):
    return _adapter_mode(environ.get("WORKS_DEV_ADAPTER", ""))


def _adapter_none(environ, show):
    return {}


# 殻 → (家の既定, claude の解決の順, 包みの既定)
SHELL_DEFAULTS = {
    "use.sh": (_use_home, _claude, _adapter_default_on),
    "dogfood.sh": (_dev_home, _claude, _adapter_default_on),
    "real-run.sh": (_dev_home, _claude, _adapter_inherit),
    "archon.sh": (_dev_home, _real_claude, _adapter_none),
}


def _parse(args):
    opts = {"for": "", "claude": False, "show": False, "target": "", "adapter": ""}
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        if arg.startswith("--for="):
            opts["for"] = arg[len("--for="):]
        elif arg in ("--claude", "--show"):
            opts[arg[2:]] = True
        elif arg in ("--target", "--adapter") and rest:
            opts[arg[2:]] = rest.pop(0)
        else:
            raise Refused(f"受けない引数 {arg!r}。使い方: {USAGE}")
    if opts["for"] not in SHELL_DEFAULTS:
        raise Refused(f"--for は {'・'.join(SHELL_DEFAULTS)} のどれか（受けた値: {opts['for']!r}）。使い方: {USAGE}")
    if opts["show"] and opts["for"] != "dogfood.sh":
        raise Refused(f"--show は --for=dogfood.sh だけが受ける。使い方: {USAGE}")
    return opts


def env(args, environ):
    opts = _parse(args)
    home, claude, adapter = SHELL_DEFAULTS[opts["for"]]
    values = home(environ, opts["target"])
    values.update(adapter(environ, opts["show"]))
    if opts["claude"]:
        values["WORKS_LAUNCH_CLAUDE"] = claude(environ, opts["adapter"])
    return _assignments(values, ALLOWED_NAMES)


def _assignments(values, allowed, export=False):
    for name in values:
        if name not in allowed or not NAME.match(name):
            raise Refused(f"出さない名 {name!r}")
    tail = (lambda k: f"; export {k}") if export else (lambda k: "")
    return "".join([f"WORKS_LAUNCH_FORMAT={FORMAT}\n"] + [f"{k}={shlex.quote(v)}{tail(k)}\n" for k, v in values.items()])


LEDGER_OPTIONS = {
    "save": ({"dir", "run-id", "target", "model-value", "model-from"}, {"wrap-ref", "github-reads"}),
    "list": ({"dir"}, {"run-id"}),
    "load": ({"dir", "run-id"}, set()),
    "bind": ({"for", "dir", "target", "request", "model-value", "model-from"}, {"wrap-ref", "github-reads"}),
}


def _ledger_parse(args):
    if not args or args[0] not in LEDGER_OPTIONS:
        raise Refused(f"ledger の後は {'・'.join(LEDGER_OPTIONS)} のどれか。使い方: {LEDGER_USAGE}")
    sub, rest, opts = args[0], list(args[1:]), {}
    need, may = LEDGER_OPTIONS[sub]
    while rest:
        arg = rest.pop(0)
        if not (arg.startswith("--") and arg[2:] in need | may and rest):
            raise Refused(f"受けない引数 {arg!r}。使い方: {LEDGER_USAGE}")
        opts[arg[2:]] = rest.pop(0)
    missing = sorted(need - set(opts))
    if missing:
        raise Refused(f"ledger {sub} は --{'・--'.join(missing)} が要る。使い方: {LEDGER_USAGE}")
    run_id = opts.get("run-id")
    if run_id is not None and (not run_id or "/" in run_id or run_id.startswith(".")):
        raise Refused(f"run id {run_id!r} は控えのファイルの名にならない")
    return sub, opts


def _ledger_path(folder, run_id):
    return os.path.join(folder, run_id + ".json")


def _ledger_read(path):
    """控え 1 つを dict で返す。読めない・壊れた・run_id の無い控えは None。版の欄 schema が無い控えは版 1 より前の元の形で、
    欄は版 1 と同じなのでそのまま読む。知らない版は Refused（読み違えた値で Archon を起こさない）"""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not (isinstance(doc, dict) and isinstance(doc.get("run_id"), str) and doc["run_id"]):
        return None
    schema = doc.get("schema", LEDGER_SCHEMA)
    if type(schema) is not int or schema != LEDGER_SCHEMA:
        raise Refused(f"控え {path} の版 schema={schema!r} を知らない（読めるのは {LEDGER_SCHEMA} と欄の無い元の形）。"
                      "works/dev を控えを書いた版にそろえる")
    return doc


def _ledger_write(opts, run_id, environ):
    # 包んだ基の参照と隔離の前に読んだ読み出しのファイル（start が盤面へ写さなかった時に use.sh clean が消す）は殻の変数
    # （export しない）なので旗で受ける
    inside = environ.get("HERDR_ENV") == "1"   # herdr の枠の中で起こしたならその枠とサーバ（works_dev_herdr_sync が送る先）
    doc = {"schema": LEDGER_SCHEMA, "run_id": run_id, "target": opts["target"], "model": environ.get("WORKS_DEV_MODEL", ""),
           "model_resolved": {"value": opts["model-value"], "from": opts["model-from"]},
           "claude_bin": environ.get("CLAUDE_BIN_PATH", ""), "keychain_item": environ.get("WORKS_KEYCHAIN_ITEM", ""),
           "adapter": environ.get("WORKS_DEV_ADAPTER", ""), "started_at": time.time(),
           "wrap_ref": opts.get("wrap-ref", ""), "github_reads": opts.get("github-reads", ""),
           "herdr_pane": environ.get("HERDR_PANE_ID", "") if inside else "",
           "herdr_socket": environ.get("HERDR_SOCKET_PATH", "") if inside else ""}
    folder = opts["dir"]
    os.makedirs(folder, exist_ok=True)
    path = _ledger_path(folder, run_id)
    part = f"{path}.{os.getpid()}.part"
    with open(part, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    os.replace(part, path)   # 組み終えてから 1 回で置く（途中まで書いた控えを読ませない）


def _continuing(folder, run_id):
    """続き中の印 <置き場>/<run-id>.cont の鍵（lib.sh works_dev_continue が flock で持つ）を誰かが持っていれば "1"、無ければ ""。
    持ち手が落ちれば（SIGKILL・再起動も）鍵は外れるので、取れる印は残り物と見る。fcntl の無い所（Windows）は印を見ない"""
    try:
        import fcntl
    except ImportError:
        return ""
    try:
        with open(os.path.join(folder, run_id + ".cont"), "rb") as f:
            fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return "1"
    except OSError:
        pass
    return ""


def _ledger_list(opts):
    run_id = opts.get("run-id")
    paths = [_ledger_path(opts["dir"], run_id)] if run_id else sorted(glob.glob(os.path.join(glob.escape(opts["dir"]),
                                                                                            "*.json")))
    lines = []
    for path in paths:
        try:
            doc = _ledger_read(path)
        except Refused:
            doc = None   # 知らない版も壊れた控えと同じく黙って飛ばす（集計・show・clean の出力に混ぜない）
        if doc is None:
            continue
        s = lambda k: doc.get(k) if isinstance(doc.get(k), str) else ""
        wrap = s("wrap_ref") if s("wrap_ref").startswith("refs/works/wraps/") else ""
        at = doc.get("started_at") if isinstance(doc.get("started_at"), (int, float)) else 0
        target = os.path.realpath(s("target")) if s("target") else ""
        reads = s("github_reads") if os.path.isabs(s("github_reads")) and s("github_reads").endswith(".json") else ""
        lines.append("\t".join([doc["run_id"], target, repr(at), wrap, s("herdr_pane"), s("herdr_socket"),
                                 _continuing(opts["dir"], doc["run_id"]), reads]) + "\n")
    return "".join(lines)


def _ledger_load(opts, err):
    path = _ledger_path(opts["dir"], opts["run-id"])
    if not os.path.isfile(path):
        raise Refused(f"控え {path} が無い")
    doc = _ledger_read(path)
    if doc is None:
        err.write(f"launch.py: 控え {path} が読めない。今の殻の値のまま進む\n")
        return _assignments({}, LEDGER_LOAD_NAMES)
    resolved = doc.get("model_resolved") if isinstance(doc.get("model_resolved"), dict) else {}
    pinned = resolved.get("value") if doc.get("model") == "" else None
    values = {}
    for name, value in (("WORKS_DEV_MODEL", doc.get("model")), ("WORKS_MODEL_PINNED", pinned),
                        ("CLAUDE_BIN_PATH", doc.get("claude_bin")), ("WORKS_KEYCHAIN_ITEM", doc.get("keychain_item")),
                        ("WORKS_DEV_ADAPTER", doc.get("adapter"))):
        # 模型の空は「start で明示しなかった」の控え。殻の値で埋めず、空のまま渡して archon.sh に start の時に解いた
        # 既定（model_resolved の value）で解かせる
        if isinstance(value, str) and (value or name in ("WORKS_DEV_ADAPTER", "WORKS_DEV_MODEL")):
            values[name] = value
    return _assignments(values, LEDGER_LOAD_NAMES, export=True)


def _run_origin(row):
    # 名指しの家は対象をまたいで 1 つなので、起動した対象（metadata.workflow_source.origin）が違う run は採らない
    # （origin の無い行は見分けられないので残す）
    origin = ((row.get("metadata") or {}).get("workflow_source") or {}).get("origin")
    return os.path.realpath(origin) if isinstance(origin, str) and origin else None


def _run_request(row):
    """run の盤面に残った依頼（r1/start.json の request_file か state.json の inputs.request）の realpath。無ければ None"""
    board = os.path.join(row.get("output_root") or "", "artifacts", "runs", row.get("id") or "", "board")
    for name, pick in (("r1/start.json", lambda d: d.get("request_file")),
                       ("state.json", lambda d: (d.get("inputs") or {}).get("request"))):
        try:
            with open(os.path.join(board, name), encoding="utf-8") as f:
                value = pick(json.load(f))
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(value, str) and value:
            return os.path.realpath(value)
    return None


def _ledger_bind(opts, environ, stdin):
    caller, here = opts["for"], os.path.realpath(opts["target"])
    try:
        listed = json.loads(stdin.read())
        rows = [r for r in listed.get("runs", []) if isinstance(r, dict)]
    except (ValueError, AttributeError) as e:
        raise Unbound(f"{caller}: archon workflow runs --json の出力が JSON として読めない（{e}）")
    rows = [r for r in rows if r.get("workflow_name") == "darkfactory" and _run_origin(r) in (None, here)]
    if not rows:
        raise Unbound(f"{caller}: darkfactory の run が見つからない（対象 {here}）")
    show = lambda found: "".join(f"\n  候補 {r.get('id')}（{r.get('status')}）: {caller} show {here} {r.get('id')}"
                                 for r in found)
    if not opts["request"]:
        # 依頼の写しの無い起動（変更だけ）は目印が無いので結ばない（設計書 2.3。2026-10-01 の関所の答え）
        found = [r for r in rows if _run_request(r) is None]
        raise Unbound(f"{caller}: 依頼の写しの無い起動（変更だけ）は run を結ばない。推定では選ばない{show(found)}")
    want = os.path.realpath(opts["request"])
    mine = [r for r in rows if _run_request(r) == want]
    if len(mine) != 1:
        raise Unbound(f"{caller}: この起動の run を 1 つに結べない（依頼 {want} の run の候補が {len(mine)} 本）。"
                      f"推定では選ばない{show(mine)}")
    row = mine[0]
    run_id = row.get("id") if isinstance(row.get("id"), str) else ""
    if not run_id or "/" in run_id or run_id.startswith("."):
        raise Unbound(f"{caller}: 結んだ run の id {run_id!r} は控えのファイルの名にならない")
    _ledger_write(opts, run_id, environ)
    return _assignments({"WORKS_RUN_ROW": json.dumps(row, ensure_ascii=False), "WORKS_RUN_ID": run_id,
                         "WORKS_RUN_STATUS": row.get("status") if isinstance(row.get("status"), str) else ""},
                        LEDGER_BIND_NAMES)


def ledger(args, environ, err, stdin):
    sub, opts = _ledger_parse(args)
    if sub == "save":
        _ledger_write(opts, opts["run-id"], environ)
        return ""
    if sub == "list":
        return _ledger_list(opts)
    if sub == "load":
        return _ledger_load(opts, err)
    return _ledger_bind(opts, environ, stdin)


def main(argv, environ, out, err, stdin=None):
    try:
        if argv[:1] == ["env"]:
            text = env(argv[1:], environ)
        elif argv[:1] == ["ledger"]:
            text = ledger(argv[1:], environ, err, stdin if stdin is not None else sys.stdin)
        else:
            raise Refused(f"動詞は env・ledger のどれか。使い方: {USAGE} | {LEDGER_USAGE}")
    except Refused as e:
        err.write(f"launch.py: {e}\n")
        return 2
    except Unbound as e:
        err.write(f"{e}\n")
        return 1
    except OSError as e:
        err.write(f"launch.py: 控えを読み書きできない（{e}）\n")
        return 2
    out.write(text)   # 組み終えてから 1 回で書く（途中まで出た代入を効かせない）
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:], os.environ, sys.stdout, sys.stderr))
