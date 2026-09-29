"""起動の殻の共通の口（設計書 works/docs/specs/2026-09-29-launch-core-design.md の 2.2・2.3）。

python3 -I works/dev/launch.py env --for=<殻> [--claude] [--show] [--target <解いた対象の根>] [--adapter <包みの実パス>]

殻 4 本（use.sh・dogfood.sh・real-run.sh・archon.sh）の家の既定・claude の解決・包みの既定とラインの入力 adapter の値
（WORKS_LAUNCH_ADAPTER_MODE）を 1 か所で持ち、sh の代入の行で返す。--show は dogfood.sh --show の時だけ渡す。
殻は guard.sh の works_dev_launch_env で 2 段に受ける（1 段の eval "$(…)" では部品の失敗が消える）。
1 行目は版の行 WORKS_LAUNCH_FORMAT=1。値は shlex.quote で囲み、名は ALLOWED_NAMES に在る物だけを出す（shlex.quote は名を守らない）。
claude が見つからなくても WORKS_LAUNCH_CLAUDE を空で返して 0 で終わる。止めるか・どの文言で止めるかは殻の今の場所が決める。
失敗（使い方の誤り・家の根が決まらない）は標準出力に何も出さず、標準エラーに 1 行を出して 2 で終わる。
標準ライブラリだけ・Python 3.9 の構文で書き、pack の兄弟を import しない。子のプロセスは起こさない。
"""
import hashlib
import os
import re
import shlex
import shutil
import sys

FORMAT = "1"
NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
ALLOWED_NAMES = frozenset({"WORKS_DEV_HOME", "WORKS_STATE_ROOT", "WORKS_USE_HOME", "WORKS_LAUNCH_CLAUDE",
                           "WORKS_DEV_ADAPTER", "WORKS_LAUNCH_ADAPTER_MODE"})
USAGE = ("launch.py env --for=<use.sh|dogfood.sh|real-run.sh|archon.sh> [--claude] [--show] [--target <path>]"
         " [--adapter <path>]")


class Refused(Exception):
    pass


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
    for name in values:
        if name not in ALLOWED_NAMES or not NAME.match(name):
            raise Refused(f"出さない名 {name!r}")
    return "".join([f"WORKS_LAUNCH_FORMAT={FORMAT}\n"] + [f"{k}={shlex.quote(v)}\n" for k, v in values.items()])


def main(argv, environ, out, err):
    try:
        if argv[:1] != ["env"]:
            raise Refused(f"動詞は env だけ。使い方: {USAGE}")
        text = env(argv[1:], environ)
    except Refused as e:
        err.write(f"launch.py: {e}\n")
        return 2
    out.write(text)   # 組み終えてから 1 回で書く（途中まで出た代入を効かせない）
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:], os.environ, sys.stdout, sys.stderr))
