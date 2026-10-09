"""起動の殻の共通の口（設計書 works/docs/specs/2026-09-29-launch-core-design.md の 2.2・2.3）。

python3 -I works/dev/launch.py env --for=<殻> [--claude] [--show] [--target <解いた対象の根>] [--adapter <包みの実パス>]
python3 -I works/dev/launch.py ledger save|load|list|bind|unbound-save|unbound-release|live …（下の LEDGER_USAGE）

env: 殻 3 本（use.sh・dogfood.sh・archon.sh）の家の既定・claude の解決・包みの既定とラインの入力 adapter の値
（WORKS_LAUNCH_ADAPTER_MODE）を 1 か所で持ち、sh の代入の行で返す。--show は dogfood.sh --show の時だけ渡す。
殻は guard.sh の works_dev_launch_env で 2 段に受ける（1 段の eval "$(…)" では部品の失敗が消える）。
ledger: run の控え <置き場>/<run-id>.json の形（版の欄 schema）と、起動の後に run を結ぶ規則を 1 か所で持つ。save は書き、
list は lib.sh works_dev_ledgers のタブ区切りの 7 欄で読み、load は use.sh が続きで Archon を起こす値を代入の行で返し、
bind は標準入力の run の一覧から、起動の印 --launch-mark が Archon の残した入力 launch_mark と一致するか、盤面の依頼がこの起動の
依頼の写しと一致する run がちょうど 1 本の時だけ結んで控えを書く。殻（use.sh・dogfood.sh）はどの入口
の起動にも起動ごとに一意の印を付けるので、結び方は入口の種類で分かれない（計画
docs/plans/2026-10-09-clean-whole.md の段 4.1）。
unbound-save は結べなかった起動の後に、標準入力の run の一覧の候補（依頼の写しも起動の印も持たない run のうち生きた状態の物）が
在れば、起動が使う包んだ基を候補と一緒に結べない控え <置き場>/<印>.json に書いて候補を空白区切りの 1 行で出す。
unbound-release は候補にその run を持ちその対象の結べない控えを全部回り、控えごとにパス・包んだ基・まだ生きている
ほかの候補をタブ区切りの 1 行で出す（生きた候補が在れば包んだ基は空にし、控えの候補からその run だけを外す）。live は状態が生きた状態（LIVE_STATUSES）、done は終わった状態（DONE_STATUSES）なら 1 を出す。
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
# 生きた run の状態（走っている・関所で待つ）。use.sh clean の拒みも ledger live でここを読む（一覧を 1 か所に）
LIVE_STATUSES = ("running", "paused", "pending")
# 終わった run の状態（正常に終わった・取り消した）。use.sh の is_done（wait・show の自動の片付けと stop の拒み）と lib.sh の
# works_dev_show_run（clean の行を勧めるか）が ledger done でここを読む。
# failed は含めない（Archon の resume が前の worktree を使い直すので、次の use.sh start の sweep_old_runs まで残す）
DONE_STATUSES = ("completed", "cancelled")
USAGE = ("launch.py env --for=<use.sh|dogfood.sh|archon.sh> [--claude] [--show] [--target <path>]"
         " [--adapter <path>]")
LEDGER_USAGE = ("launch.py ledger save --dir <置き場> --run-id <id> --target <dir> --model-value <値> --model-from <出どころ>"
                " [--wrap-ref <参照>] | ledger list --dir <置き場> [--run-id <id>] | ledger load --dir <置き場> --run-id <id>"
                " | ledger bind --for <呼び手> --dir <置き場> --target <dir> --request <依頼の写し> --model-value <値>"
                " --model-from <出どころ> [--wrap-ref <参照>] [--launch-mark <起動の印>]（標準入力に archon workflow runs --json）"
                " | ledger unbound-save --dir <置き場> --target <dir> --stamp <印> [--wrap-ref <参照>]"
                "（標準入力に archon workflow runs --json） | ledger unbound-release --dir <置き場> --target <dir> --run-id <id>"
                "（標準入力に archon workflow runs --json） | ledger live --status <状態> | ledger done --status <状態>")


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


def _adapter_none(environ, show):
    return {}


# 殻 → (家の既定, claude の解決の順, 包みの既定)
SHELL_DEFAULTS = {
    "use.sh": (_use_home, _claude, _adapter_default_on),
    "dogfood.sh": (_dev_home, _claude, _adapter_default_on),
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
    "save": ({"dir", "run-id", "target", "model-value", "model-from"}, {"wrap-ref"}),
    "list": ({"dir"}, {"run-id"}),
    "load": ({"dir", "run-id"}, set()),
    "bind": ({"for", "dir", "target", "request", "model-value", "model-from"}, {"wrap-ref", "launch-mark"}),
    "unbound-save": ({"dir", "target", "stamp"}, {"wrap-ref"}),
    "unbound-release": ({"dir", "target", "run-id"}, set()),
    "live": ({"status"}, set()),
    "done": ({"status"}, set()),
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
    for name, what in (("run-id", "run id"), ("stamp", "印")):
        value = opts.get(name)
        if value is not None and (not value or "/" in value or value.startswith(".")):
            raise Refused(f"{what} {value!r} は控えのファイルの名にならない")
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
    # 包んだ基の参照（use.sh clean が消す）は殻の変数（export しない）なので旗で受ける
    inside = environ.get("HERDR_ENV") == "1"   # herdr の枠の中で起こしたならその枠とサーバ（works_dev_herdr_sync が送る先）
    doc = {"schema": LEDGER_SCHEMA, "run_id": run_id, "target": opts["target"], "model": environ.get("WORKS_DEV_MODEL", ""),
           "model_resolved": {"value": opts["model-value"], "from": opts["model-from"]},
           "claude_bin": environ.get("CLAUDE_BIN_PATH", ""), "keychain_item": environ.get("WORKS_KEYCHAIN_ITEM", ""),
           "adapter": environ.get("WORKS_DEV_ADAPTER", ""), "started_at": time.time(),
           "wrap_ref": opts.get("wrap-ref", ""),
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


def _kept_wrap(doc):
    """控えの包んだ基の参照（refs/works/wraps/ の下の時だけ）。外れは空"""
    wrap = doc.get("wrap_ref") if isinstance(doc.get("wrap_ref"), str) else ""
    return wrap if wrap.startswith("refs/works/wraps/") else ""


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
        wrap = _kept_wrap(doc)
        at = doc.get("started_at") if isinstance(doc.get("started_at"), (int, float)) else 0
        target = os.path.realpath(s("target")) if s("target") else ""
        lines.append("\t".join([doc["run_id"], target, repr(at), wrap, s("herdr_pane"), s("herdr_socket"),
                                 _continuing(opts["dir"], doc["run_id"])]) + "\n")
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


def _run_meta(row):
    """runs --json の行の metadata を dict で（JSON の文字列でも読む。読めない・dict でなければ空）"""
    meta = row.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            return {}
    return meta if isinstance(meta, dict) else {}


def _run_origin(row):
    # 名指しの家は対象をまたいで 1 つなので、起動した対象（metadata.workflow_source.origin）が違う run は採らない
    # （origin の無い行は見分けられないので残す）
    source = _run_meta(row).get("workflow_source")
    origin = source.get("origin") if isinstance(source, dict) else None
    return os.path.realpath(origin) if isinstance(origin, str) and origin else None


def _run_request(row):
    """run の依頼の realpath。無ければ None。先に Archon が run に残した入力（runs --json の metadata.inputs.request）を見る——
    起動の直後は最初の関所（launch）で止まっていて start の節がまだ走らず、盤面がまだ無い。次に盤面に残った依頼（r1/start.json の
    request_file か state.json の inputs.request）を見る"""
    inputs = _run_meta(row).get("inputs")
    value = inputs.get("request") if isinstance(inputs, dict) else None
    if isinstance(value, str) and value:
        return os.path.realpath(value)
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


def _run_mark(row):
    """run の起動の印（Archon が run に残した入力 metadata.inputs.launch_mark。殻がどの起動にも付ける生の事実）。
    無ければ None"""
    inputs = _run_meta(row).get("inputs")
    value = inputs.get("launch_mark") if isinstance(inputs, dict) else None
    return value if isinstance(value, str) and value else None


def _runs_list(doc):
    """runs --json の runs の一覧。鍵が無い・list でない（null・dict・文字列）なら ValueError——読めた 0 本と読めないを分ける"""
    runs = doc.get("runs") if isinstance(doc, dict) else None
    if not isinstance(runs, list):
        raise ValueError("runs の一覧が無い")
    return runs


def _darkfactory_rows(stdin, here):
    """標準入力の runs --json のうち、この対象（origin の無い行は見分けられないので残す）の darkfactory の run の行。
    JSON として読めなければ（runs の一覧が無い・list でないのも）ValueError"""
    rows = [r for r in _runs_list(json.loads(stdin.read())) if isinstance(r, dict)]
    return [r for r in rows if r.get("workflow_name") == "darkfactory" and _run_origin(r) in (None, here)]


def _unmarked(rows):
    """結ぶ印（依頼の写しも起動の印も）を持たない run。印の無い起動の run はこの中に在る（推定では選ばない）"""
    return [r for r in rows if _run_request(r) is None and _run_mark(r) is None]


def _ledger_bind(opts, environ, stdin):
    caller, here = opts["for"], os.path.realpath(opts["target"])
    try:
        rows = _darkfactory_rows(stdin, here)
    except ValueError as e:
        raise Unbound(f"{caller}: archon workflow runs --json の出力が JSON として読めない（{e}）")
    if not rows:
        raise Unbound(f"{caller}: darkfactory の run が見つからない（対象 {here}）")
    show = lambda found: "".join(f"\n  候補 {r.get('id')}（{r.get('status')}）: {caller} show {here} {r.get('id')}"
                                 for r in found)
    mark_want = opts.get("launch-mark") or ""
    req_want = os.path.realpath(opts["request"]) if opts["request"] else ""
    if not mark_want and not req_want:
        # 起動の印も依頼の写しも無い起動は目印が無いので結ばない（設計書 2.3。2026-10-01 の関所の答え）
        found = _unmarked(rows)
        raise Unbound(f"{caller}: 起動の印も依頼の写しも無い起動は run を結ばない。推定では選ばない{show(found)}")
    # 起動の印（殻の <日時>-<pid>。殻はどの入口の起動にも付ける）と依頼の写し（起動ごとに一意の絶対パス）は、どちらもこの起動
    # だけを指す目印。どちらかが一致する run を結ぶ——入口の種類（依頼の写しが在るか）で結び方を分けない（段 4.1）
    mine = [r for r in rows if (mark_want and _run_mark(r) == mark_want) or (req_want and _run_request(r) == req_want)]
    want = "・".join(x for x in (mark_want, req_want) if x)
    mark = "・".join(n for n, x in (("起動の印", mark_want), ("依頼", req_want)) if x)
    if len(mine) != 1:
        raise Unbound(f"{caller}: この起動の run を 1 つに結べない（{mark} {want} の run の候補が {len(mine)} 本）。"
                      f"推定では選ばない{show(mine)}")
    row = mine[0]
    run_id = row.get("id") if isinstance(row.get("id"), str) else ""
    if not run_id or "/" in run_id or run_id.startswith("."):
        raise Unbound(f"{caller}: 結んだ run の id {run_id!r} は控えのファイルの名にならない")
    _ledger_write(opts, run_id, environ)
    return _assignments({"WORKS_RUN_ROW": json.dumps(row, ensure_ascii=False), "WORKS_RUN_ID": run_id,
                         "WORKS_RUN_STATUS": row.get("status") if isinstance(row.get("status"), str) else ""},
                        LEDGER_BIND_NAMES)


def _replace_json(path, doc):
    part = f"{path}.{os.getpid()}.part"
    with open(part, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")
    os.replace(part, path)


def _unbound_save(opts, stdin):
    # 結べなかった起動の run は起動の関所で生きていて、包んだ基を使う（消すと承認した run が落ちる。2026-10-01）。
    # 結ばずに（設計書 2.3）候補と一緒に残し、use.sh clean が候補の run の片付けと一緒に消す。候補は生きた状態の物だけ（終わった
    # 古い run を載せない）。読めた一覧で候補が 0 本なら何も書かずに空を返す（呼び手が包んだ基の参照をその場で外す）。一覧が
    # 読めなければ生きた run が在るか分からないので消さず、候補の無い控え（unknown）に残して止める（clean と同じく迷ったら残す）
    here = os.path.realpath(opts["target"])
    doc = {"wrap_ref": opts.get("wrap-ref", ""), "target": here}
    path = os.path.join(opts["dir"], opts["stamp"] + ".json")
    try:
        rows = _darkfactory_rows(stdin, here)
    except ValueError as e:
        os.makedirs(opts["dir"], exist_ok=True)
        _replace_json(path, dict(doc, candidates=[], unknown=True))
        raise Refused(f"archon workflow runs --json の出力が JSON として読めない（{e}）。生きた run が使うかもしれないので"
                      f"包んだ基は消さず、控え {path} に残した")
    found = [r["id"] for r in _unmarked(rows)
             if isinstance(r.get("id"), str) and r["id"] and r.get("status") in LIVE_STATUSES]
    if not found:
        return ""
    os.makedirs(opts["dir"], exist_ok=True)
    _replace_json(path, dict(doc, candidates=found))
    return " ".join(found) + "\n"


def _unbound_release(opts, stdin):
    # clean <対象> <run-id> が呼ぶ。ほかの候補がまだ生きている間はその run が包んだ基を使うかもしれないので返さず、
    # 控えの候補からこの run だけを外して書き戻す。最後の候補の時だけ返す（消すのと控えを消すのは呼び手）。この run を候補に
    # 持つ控えは全部回り、控えごとに 1 行を出す（印の無い起動を並べると後の控えに前の run も載る）。候補の無い控え（unknown。
    # start が一覧を読めずに残した）は、この対象の生きた run が 1 本も無い時に返す（どの run の物か分からないので）。
    # 一覧が読めなければ生きているかが分からないので止める
    here, run_id = os.path.realpath(opts["target"]), opts["run-id"]
    try:
        rows = _darkfactory_rows(stdin, here)
    except ValueError as e:
        raise Refused(f"archon workflow runs --json の出力が JSON として読めない（{e}）")
    live = {r.get("id") for r in rows if r.get("status") in LIVE_STATUSES}
    lines = []
    for path in sorted(glob.glob(os.path.join(glob.escape(opts["dir"]), "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if not (isinstance(doc, dict) and doc.get("target") == here and isinstance(doc.get("candidates"), list)):
            continue
        if doc.get("unknown") is True:
            if not live:
                lines.append("\t".join((path, _kept_wrap(doc), "")) + "\n")
            continue
        if run_id not in doc["candidates"]:
            continue
        rest = [c for c in doc["candidates"] if c != run_id]
        alive = [c for c in rest if c in live]
        if not alive:
            lines.append("\t".join((path, _kept_wrap(doc), "")) + "\n")
            continue
        _replace_json(path, dict(doc, candidates=rest))
        lines.append("\t".join((path, "", " ".join(alive))) + "\n")
    return "".join(lines)


def ledger(args, environ, err, stdin):
    sub, opts = _ledger_parse(args)
    if sub == "save":
        _ledger_write(opts, opts["run-id"], environ)
        return ""
    if sub == "list":
        return _ledger_list(opts)
    if sub == "load":
        return _ledger_load(opts, err)
    if sub == "unbound-save":
        return _unbound_save(opts, stdin)
    if sub == "unbound-release":
        return _unbound_release(opts, stdin)
    if sub == "live":
        return "1\n" if opts["status"] in LIVE_STATUSES else ""
    if sub == "done":
        return "1\n" if opts["status"] in DONE_STATUSES else ""
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
