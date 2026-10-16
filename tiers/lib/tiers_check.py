"""要る道具の段ごとの点検。足りない物と入れ方を返し、何も入れない。

段は、プラグインが要る外の道具で分ける（設計: docs/specs/2026-10-16-company-shape-design.md の 4.11）。
上の段は下の段を含む（段 2 を点検すると、段 0 と段 1 も点検する）。

- 段 0: Claude Code だけ（claude が起こせるか）
- 段 1: gh（GitHub の CLI。入っているか、ログイン済みか）
- 段 2: herdr（入っているか、動いているか）と、アカウントの起こし方の命令（--launcher で渡す。省けば claude）
- 段 3: Archon（archon が在るか）

ここに書く道具は、どれも利用者が手で入れる物（OS の道具・ログイン・シェルの設定）なので、点検は入れ方を示して止まる。
入れ方の命令は、各道具の公式の README の「install」の節から写した（2026-10-16 に読んだ）。

使い方:
    tiers [--tier N] [--launcher 命令 ...] [--json]

終了コード: 0 = そろっている / 1 = 足りない物がある / 2 = 使い方が違う

--json の形（schema 1）:
    {"schema": 1, "tier": N, "ok": bool, "missing": 足りない数,
     "checks": [{"tier": 段, "name": 名前, "ok": bool, "found": 見つけた物か null,
                 "problem": 足りない訳か null, "fix": [入れ方の行], "manual": true}]}
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

SCHEMA = 1
TOP = 3
TIERS = {0: "Claude Code だけ", 1: "gh（GitHub の CLI）", 2: "herdr と、アカウントの起こし方の命令", 3: "Archon"}

# 入れ方。キーは sys.platform の頭（darwin・win32・それ以外は linux の扱い）
INSTALL = {
    "claude": {
        "darwin": ["curl -fsSL https://claude.ai/install.sh | bash"],
        "linux": ["curl -fsSL https://claude.ai/install.sh | bash"],
        "win32": ["irm https://claude.ai/install.ps1 | iex   （PowerShell）"],
    },
    "gh": {
        "darwin": ["brew install gh"],
        "linux": ["sudo apt install gh   （Debian・Ubuntu。ほかは https://github.com/cli/cli#installation ）"],
        "win32": ["winget install --id GitHub.cli"],
    },
    "herdr": {
        "darwin": ["curl -fsSL https://herdr.dev/install.sh | sh   （か brew install herdr）"],
        "linux": ["curl -fsSL https://herdr.dev/install.sh | sh"],
        "win32": ['powershell -ExecutionPolicy Bypass -c "irm https://herdr.dev/install.ps1 | iex"'],
    },
    "archon": {
        "darwin": ["curl -fsSL https://archon.diy/install | bash   （か brew install coleam00/archon/archon）"],
        "linux": ["curl -fsSL https://archon.diy/install | bash"],
        "win32": ["irm https://archon.diy/install.ps1 | iex   （PowerShell）"],
    },
}


def _os_key(platform):
    if platform.startswith("darwin"):
        return "darwin"
    if platform.startswith("win"):
        return "win32"
    return "linux"


def _run(argv):
    """(終了コード, 標準出力と標準エラーを合わせた文)。起こせなければ (None, 訳)。"""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        return None, str(e)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _posix_shell(env, platform):
    """利用者のログインのシェル。POSIX のシェルが無い所（Windows）では None。"""
    if _os_key(platform) == "win32":
        return None
    return env.get("SHELL") or "/bin/sh"


class Probe:
    """外への口。試験は同じ名前の口を持つ偽物を渡す。"""

    def __init__(self, env=None, platform=None):
        self.env = os.environ if env is None else env
        self.platform = platform or sys.platform

    def which(self, cmd):
        return shutil.which(cmd, path=self.env.get("PATH"))

    def run(self, argv):
        return _run(argv)

    def shell_has(self, cmd):
        """ログインかつ対話のシェル（-lic）でその命令が見つかるか。シェルの関数と別名も数える。
        アカウントの起こし方の命令は、シェルの設定に書いた関数であることが多く、PATH を探すだけでは見つからないため。"""
        shell = _posix_shell(self.env, self.platform)
        if shell is None:
            return self.which(cmd) is not None
        code, _ = _run([shell, "-lic", f"command -v {shlex.quote(cmd)}"])
        return code == 0


def _item(tier, name, found=None, problem=None, fix=()):
    return {"tier": tier, "name": name, "ok": problem is None, "found": found, "problem": problem,
            "fix": list(fix), "manual": True}


def _first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _installed(probe, tier, cmd, label, version_args):
    """命令が PATH に在り、版を出せるか。(点検の項目, 命令のパスか None)"""
    path = probe.which(cmd)
    install = INSTALL[cmd][_os_key(probe.platform)]
    if not path:
        return _item(tier, label, problem=f"{cmd} が PATH に無い", fix=install), None
    code, out = probe.run([path, *version_args])
    if code != 0:
        return _item(tier, label, found=path, problem=f"{cmd} {' '.join(version_args)} が通らない: {_first_line(out)[:200]}",
                     fix=install), None
    return _item(tier, label, found=_first_line(out) or path), path


def check_claude(probe):
    return [_installed(probe, 0, "claude", "Claude Code", ["--version"])[0]]


def check_gh(probe):
    item, path = _installed(probe, 1, "gh", "gh", ["--version"])
    out = [item]
    if path:
        code, text = probe.run([path, "auth", "status"])
        if code != 0:
            out.append(_item(1, "gh のログイン", problem=f"gh auth status が通らない（ログインしていない）: {_first_line(text)[:200]}",
                             fix=["gh auth login"]))
        else:
            out.append(_item(1, "gh のログイン", found="gh auth status が通る"))
    return out


RUNNING = re.compile(r"^\s*status:\s*running\s*$", re.M)


def check_herdr(probe, launchers):
    item, path = _installed(probe, 2, "herdr", "herdr", ["--version"])
    out = [item]
    if path:
        # herdr status server の server の節（0.9.3 で読んだ形: 「status: running」の行）
        code, text = probe.run([path, "status", "server"])
        if code == 0 and RUNNING.search(text):
            out.append(_item(2, "herdr の動き", found="herdr の server が動いている"))
        else:
            out.append(_item(2, "herdr の動き", problem=f"herdr の server が動いていない: {_first_line(text)[:200]}",
                             fix=["作業するフォルダで herdr を起こす: herdr"]))
    for cmd in launchers:
        if probe.shell_has(cmd):
            out.append(_item(2, f"起こし方の命令 {cmd}", found=f"{cmd} がシェルで見つかる"))
        else:
            out.append(_item(2, f"起こし方の命令 {cmd}", problem=f"アカウントの起こし方の命令 {cmd} がシェルで見つからない",
                             fix=[f"ログインのシェルが読む設定に {cmd} を足す（中身は、そのアカウントの CLAUDE_CONFIG_DIR を決めて claude を起こす関数か別名）。"
                                  "アカウントが 1 つなら claude のままでよい"]))
    return out


def check_archon(probe):
    path = probe.which("archon")
    if not path:
        return [_item(3, "Archon", problem="archon が PATH に無い", fix=INSTALL["archon"][_os_key(probe.platform)])]
    return [_item(3, "Archon", found=path)]


def check(tier, launchers=(), probe=None):
    """段 0〜tier を点検した結果（--json の形の dict）。"""
    probe = probe or Probe()
    items = check_claude(probe)
    if tier >= 1:
        items += check_gh(probe)
    if tier >= 2:
        items += check_herdr(probe, list(launchers) or ["claude"])
    if tier >= 3:
        items += check_archon(probe)
    missing = sum(1 for x in items if not x["ok"])
    return {"schema": SCHEMA, "tier": tier, "ok": missing == 0, "missing": missing, "checks": items}


def lines(result, again):
    """人の読む形。again は、済ませた後に打ち直す命令。"""
    out = [f"要る道具の点検（段 0〜{result['tier']}）"]
    for x in result["checks"]:
        mark = " ok " if x["ok"] else " NG "
        out.append(f"{mark} 段 {x['tier']} {x['name']}: {x['found'] if x['ok'] else x['problem']}")
        for f in x["fix"] if not x["ok"] else []:
            out.append(f"        入れ方（手で）: {f}")
    if result["ok"]:
        out.append("結果: 足りない物は無い")
    else:
        out.append(f"結果: 足りない物が {result['missing']} つ。上の入れ方を手で済ませてから、もう一度走らせる: {again}")
    return out


def main(argv=None, probe=None, stdout=None):
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(prog="tiers", description="要る道具の段ごとの点検。足りない物と入れ方を返し、何も入れない。")
    ap.add_argument("--tier", type=int, default=0, help=f"点検する段（0〜{TOP}。下の段も含む）。" +
                    "、".join(f"{k}: {v}" for k, v in TIERS.items()))
    ap.add_argument("--launcher", action="append", default=[], metavar="命令",
                    help="段 2: アカウントの起こし方の命令（繰り返して複数。省けば claude）")
    ap.add_argument("--json", action="store_true", help="JSON で出す")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if not 0 <= a.tier <= TOP:
        print(f"止めた: --tier は 0〜{TOP}（渡されたのは {a.tier}）", file=stdout)
        return 2
    result = check(a.tier, a.launcher, probe)
    if a.json:
        print(json.dumps(result, ensure_ascii=False), file=stdout)
    else:
        again = "tiers --tier " + str(a.tier) + "".join(f" --launcher {shlex.quote(c)}" for c in a.launcher)
        print("\n".join(lines(result, again)), file=stdout)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
