"""要るツールの段ごとの点検。足りない物と入れ方を返し、何も入れない。

段は、プラグインが要る外のツールで分ける（設計: docs/specs/2026-10-16-company-shape-design.md の 4.11）。
上の段は下の段を含む（段 2 を点検すると、段 0 と段 1 も点検する）。

- 段 0: Claude Code だけ（claude が起動できるか）
- 段 1: gh（GitHub の CLI。入っているか、ログイン済みか）
- 段 2: herdr（入っているか、動いているか）と、アカウントの起動コマンド（--launcher で渡す。省けば claude）
- 段 3: Archon（archon が在るか）

ここに書くツールは、どれも利用者が手で入れる物（OS のツール・ログイン・シェルの設定）なので、点検は入れ方を示して止まる。
入れ方のコマンドは、各ツールの公式の README の「install」のセクションから写した（2026-10-16 に読んだ）。
herdr の入れ方と連携の案内は、herdr の v0.9.5 の文書（Install Herdr・Windows support・Integrations）とソース
（src/integration/claude_settings.rs）に拠る（2026-10-16 に読んだ。URL は docs/design.md の「段 2 の案内」のセクション）。

使い方:
    tiers [--tier N] [--launcher コマンド ...] [--json]

終了コード: 0 = そろっている / 1 = 足りない物がある / 2 = 使い方が違う

--json の形（schema 1）:
    {"schema": 1, "tier": N, "ok": bool, "missing": 足りない数,
     "checks": [{"tier": 段, "name": 名前, "ok": bool, "found": 見つけた物か null,
                 "problem": 足りない訳か null, "fix": [入れ方の行], "guide": [案内の行], "manual": true}]}
    guide は、初めての人が自分で準備するための説明（fix のコマンドの前後に要ること）。足りない項目だけが持ち、
    人の読む形にも同じ行を出す。0.1.x の後で足したフィールドで、無いフィールドを読まない呼び手はそのまま動くので schema は 1 のまま。
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
TIERS = {0: "Claude Code だけ", 1: "gh（GitHub の CLI）", 2: "herdr と、アカウントの起動コマンド", 3: "Archon"}

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
    """(終了コード, 標準出力と標準エラーを合わせた文)。起動できなければ (None, 訳)。"""
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
        """ログインかつ対話のシェル（-lic）でそのコマンドが見つかるか。シェルの関数と別名も数える。
        アカウントの起動コマンドは、シェルの設定に書いた関数であることが多く、PATH を探すだけでは見つからないため。
        Windows では PATH の上と、PowerShell（pwsh と Windows PowerShell の在る方。どちらも $PROFILE を読む）の関数を探す。"""
        shell = _posix_shell(self.env, self.platform)
        if shell is None:
            if self.which(cmd) is not None:
                return True
            quoted = "'" + cmd.replace("'", "''") + "'"
            for ps in ("pwsh", "powershell"):
                exe = self.which(ps)
                if exe:
                    code, _ = _run([exe, "-NoLogo", "-NonInteractive", "-Command",
                                    f"if (Get-Command -Name {quoted} -ErrorAction SilentlyContinue) {{ exit 0 }} else {{ exit 1 }}"])
                    if code == 0:
                        return True
            return False
        code, _ = _run([shell, "-lic", f"command -v {shlex.quote(cmd)}"])
        return code == 0


def _item(tier, name, found=None, problem=None, fix=(), guide=()):
    return {"tier": tier, "name": name, "ok": problem is None, "found": found, "problem": problem,
            "fix": list(fix), "guide": list(guide), "manual": True}


def _first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _installed(probe, tier, cmd, label, version_args, guide=()):
    """コマンドが PATH に在り、版を出せるか。(点検の項目, コマンドのパスか None)"""
    path = probe.which(cmd)
    install = INSTALL[cmd][_os_key(probe.platform)]
    if not path:
        return _item(tier, label, problem=f"{cmd} が PATH に無い", fix=install, guide=guide), None
    code, out = probe.run([path, *version_args])
    if code != 0:
        return _item(tier, label, found=path, problem=f"{cmd} {' '.join(version_args)} が通らない: {_first_line(out)[:200]}",
                     fix=install, guide=guide), None
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
SOCKET = re.compile(r"^\s*socket:\s*(\S.*)$", re.M)   # herdr status server が出す、見た socket の行


def herdr_link_guide(os_key):
    """Claude Code の連携（herdr integration install claude）の案内。herdr が無いときも動いていないときも出す。"""
    if os_key == "win32":
        per_dir = ('$env:CLAUDE_CONFIG_DIR = "$HOME\\.claude-p2"; herdr integration install claude; '
                   "Remove-Item Env:CLAUDE_CONFIG_DIR   （PowerShell）")
    else:
        per_dir = 'CLAUDE_CONFIG_DIR="$HOME/.claude-p2" herdr integration install claude'
    return [
        "Claude Code の連携: herdr integration install claude を打つ。Claude Code の会話が始まると、その会話の識別子を herdr に"
        "知らせるフックを、Claude Code の設定のフォルダ（環境変数 CLAUDE_CONFIG_DIR、無ければ ~/.claude）に足す。"
        "同じ物が既に在れば何も書き換えない。入っているかは herdr integration status で見る",
        "アカウントごとに設定のフォルダを分けているなら、フォルダごとに入れる（~/.claude-p2 は例）: " + per_dir,
    ]


def herdr_install_guide(os_key):
    """herdr が無い（版を出せない）ときの案内。入れ方のコマンド（fix）の前後に要ること。"""
    if os_key == "win32":
        out = [
            "Windows は WSL を通さずにネイティブで動く（一般提供。Linux・macOS と違う所は herdr の文書の Windows support に在る）。"
            "Windows の ARM64 は x86_64 の版をエミュレーションで動かす",
            "エンドポイントのセキュリティが PowerShell のインストーラを止めるときは、コマンドプロンプトで: "
            "curl.exe -fsSLo install.cmd https://herdr.dev/install.cmd && install.cmd && del install.cmd",
            "インストーラは版ごとのフォルダを %USERPROFILE%\\.herdr\\packages\\standalone\\releases の下に置き、今の版のフォルダを PATH に入れる。"
            "シェルが herdr を見つけないときは端末を開き直す",
            "手で落とすなら GitHub の releases の herdr-windows-x86_64.zip。中の herdr.exe だけを写さず、展開したフォルダごと置く"
            "（同じフォルダの ConPTY の実行時のファイルが要る）",
        ]
    else:
        out = [
            "インストーラは herdr を ~/.local/bin に置く（環境変数 HERDR_INSTALL_DIR で替えられる）。"
            "シェルが herdr を見つけないときは、端末を開き直すか、そのフォルダが PATH に在るかを見る",
            "ほかの入れ方: Homebrew（brew install herdr）・mise（mise use -g herdr）・Nix。"
            "更新は、インストーラで入れた物は herdr update、パッケージマネージャで入れた物はそのパッケージマネージャで",
        ]
    return out + ["入ったかは herdr --version で確かめる"] + herdr_link_guide(os_key)


def herdr_start_guide(os_key):
    """herdr が動いていないときの案内。"""
    return ["初めて起動すると初回の案内が出る。進めると設定の integrations のタブが開き、PATH に在るエージェントの連携を入れられる"] \
        + herdr_link_guide(os_key)


# アカウントの起動コマンドの案内。名前（claude-p2）とフォルダ（~/.claude-p2）は例で、点検は決め打ちしない
LAUNCHER_GUIDE = [
    "アカウントが 1 つなら、このコマンドは作らなくてよい。--launcher を省けば claude をそのまま見る"
    "（呼んだプラグインの設定でも、アカウントを 1 つにして起動するコマンドを claude にすれば動く）",
    "アカウントを分けるなら、アカウントごとに Claude Code の設定のフォルダを分け、そのフォルダを環境変数 CLAUDE_CONFIG_DIR に"
    "入れて claude を起動するコマンド（シェルの関数か別名）を作る。下の claude-p2 と ~/.claude-p2 は例で、名前とフォルダは自由。"
    "作った名前を --launcher で渡す",
    'bash: ~/.bashrc に claude-p2() { CLAUDE_CONFIG_DIR="$HOME/.claude-p2" claude "$@"; } を書く。'
    "点検はログインのシェルで探すので、~/.bash_profile が ~/.bashrc を読まないなら、~/.bash_profile に "
    "[ -f ~/.bashrc ] && . ~/.bashrc も足す",
    'zsh: ~/.zshrc に同じ関数 claude-p2() { CLAUDE_CONFIG_DIR="$HOME/.claude-p2" claude "$@"; } を書く',
    "bash・zsh で別名にするなら: alias claude-p2='CLAUDE_CONFIG_DIR=\"$HOME/.claude-p2\" claude'",
    "PowerShell: $PROFILE のファイル（無ければ New-Item -ItemType File -Force $PROFILE で作る）に "
    'function claude-p2 { $old = $env:CLAUDE_CONFIG_DIR; $env:CLAUDE_CONFIG_DIR = Join-Path $HOME .claude-p2; '
    "try { claude @args } finally { $env:CLAUDE_CONFIG_DIR = $old } } を書く。"
    "PowerShell の別名（Set-Alias）は引数や環境変数を持てないので、関数にする",
    "新しい設定のフォルダで初めて起動すると、ログインを求められる。そのアカウントでログインする",
    "書いたら端末を開き直してから点検し直す",
]


def check_herdr(probe, launchers):
    os_key = _os_key(probe.platform)
    item, path = _installed(probe, 2, "herdr", "herdr", ["--version"], guide=herdr_install_guide(os_key))
    out = [item]
    if path:
        # herdr status server の server のセクション（0.9.3 で読んだ形: 「status: running」の行）
        code, text = probe.run([path, "status", "server"])
        if code == 0 and RUNNING.search(text):
            out.append(_item(2, "herdr の動き", found="herdr の server が動いている"))
        else:
            # どこの socket を見たか（herdr status server の「socket:」の行）を添える。HOME や XDG_CONFIG_HOME が違うと、別の
            # 置き場の server を見ていることがある（まっさらな環境での 1 回目の試しの 8）
            sock = SOCKET.search(text or "")
            where = f"（見た socket: {sock.group(1).strip()}）" if sock else ""
            out.append(_item(2, "herdr の動き", problem=f"herdr の server が動いていない{where}: {_first_line(text)[:200]}",
                             fix=["作業するフォルダで herdr を起動する: herdr"], guide=herdr_start_guide(os_key)))
    for cmd in launchers:
        if probe.shell_has(cmd):
            out.append(_item(2, f"起動コマンド {cmd}", found=f"{cmd} がシェルで見つかる"))
        else:
            out.append(_item(2, f"起動コマンド {cmd}", problem=f"アカウントの起動コマンド {cmd} がシェルで見つからない",
                             fix=[f"シェルの設定に {cmd} を足す（中身は、そのアカウントの CLAUDE_CONFIG_DIR を決めて claude を起動する関数か別名）。"
                                  "アカウントが 1 つなら claude のままでよい"],
                             guide=LAUNCHER_GUIDE))
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
    """人の読む形。again は、済ませた後に打ち直すコマンド。"""
    out = [f"要るツールの点検（段 0〜{result['tier']}）"]
    for x in result["checks"]:
        mark = " ok " if x["ok"] else " NG "
        out.append(f"{mark} 段 {x['tier']} {x['name']}: {x['found'] if x['ok'] else x['problem']}")
        for f in x["fix"] if not x["ok"] else []:
            out.append(f"        入れ方（手で）: {f}")
        if not x["ok"] and x["guide"]:
            out.append("        案内:")
            out.extend(f"          - {g}" for g in x["guide"])
    if result["ok"]:
        out.append("結果: 足りない物は無い")
    else:
        out.append(f"結果: 足りない物が {result['missing']} つ。上の入れ方を手で済ませてから、もう一度走らせる: {again}")
    return out


def main(argv=None, probe=None, stdout=None):
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(prog="tiers", description="要るツールの段ごとの点検。足りない物と入れ方を返し、何も入れない。")
    ap.add_argument("--tier", type=int, default=0, help=f"点検する段（0〜{TOP}。下の段も含む）。" +
                    "、".join(f"{k}: {v}" for k, v in TIERS.items()))
    ap.add_argument("--launcher", action="append", default=[], metavar="コマンド",
                    help="段 2: アカウントの起動コマンド（繰り返して複数。省けば claude）")
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
