"""要るツールの段ごとの点検。足りない物と入れ方を返し、何も入れない。

段は、プラグインが要る外のツールで分ける（設計: docs/specs/2026-10-16-company-shape-design.md の 4.11）。
上の段は下の段を含む（段 2 を点検すると、段 0 と段 1 も点検する）。

- 段 0: Claude Code だけ（claude が起動できるか、ログイン済みか）
- 段 1: gh（GitHub の CLI。入っているか、ログイン済みか）
- 段 2: herdr（入っているか、動いているか）と、アカウントの起動コマンド（--launcher で渡す。省けば claude。在るか、そのアカウントで
  ログイン済みか）
- 段 3: Archon（archon が在るか）

ここに書くツールは、どれも利用者が手で入れる物（OS のツール・ログイン・シェルの設定）なので、点検は入れ方を示して止まる。
入れ方のコマンドは、各ツールの公式の README の「install」のセクションから写した（2026-10-16 に読んだ）。
herdr の入れ方と連携の案内は、herdr の v0.9.5 の文書（Install Herdr・Windows support・Integrations）とソース
（src/integration/claude_settings.rs）に拠る（2026-10-16 に読んだ。URL は docs/design.md の「段 2 の案内」のセクション）。

--config-dir（アカウントの Claude Code の設定のフォルダ。繰り返して複数）を渡せば、フォルダごとに次も点検する。
- 段 0: 入れたプラグインの控え（plugins/installed_plugins.json）の installPath が在るか（消えた置き場を指す項目が残ると、どの項目が
  効くかが分からない）
- 段 2: herdr の Claude Code の連携（herdr integration status を、そのフォルダを CLAUDE_CONFIG_DIR にして打つ）と、statusLine が tiers の
  statusline を指すアカウントなら、その印を herdr が見分ける支度（リンクと herdr の判定ルールの上書き。tiers_statusline.py）

使い方:
    tiers [--tier N] [--launcher コマンド ...] [--config-dir フォルダ ...] [--json]

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
import tempfile

import tiers_statusline as statusline

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


def _run_apart(argv, env=None):
    """(終了コード, 標準出力, 標準エラー)。起動できなければ (None, "", 訳)。"""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    except OSError as e:
        return None, "", str(e)
    return p.returncode, p.stdout or "", p.stderr or ""


def _run(argv):
    """(終了コード, 標準出力と標準エラーを合わせた文)。起動できなければ (None, 訳)。"""
    code, out, err = _run_apart(argv)
    return code, out + err


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

    def run_apart(self, argv):
        """機械向けの出力（JSON）を読む口。標準エラーを混ぜない。"""
        return _run_apart(argv)

    def run_in(self, argv, config_dir):
        """CLAUDE_CONFIG_DIR を config_dir にして打つ (終了コード, 標準出力, 標準エラー)。"""
        return _run_apart(argv, env={**self.env, "CLAUDE_CONFIG_DIR": config_dir})

    def read(self, path):
        """ファイルの中身。無ければ None。読めなければ OSError。"""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def isdir(self, path):
        return os.path.isdir(path)

    def auth_status(self, cmd):
        """cmd auth status --json の (終了コード, 出力の JSON の字)。起動コマンドはシェルの関数のことが多く、ログインの鍵もシェルの
        設定が渡すことがある（CLAUDE_CODE_OAUTH_TOKEN）ので、shell_has と同じシェルで打つ。出力は一時のファイルに書かせて読む
        （シェルの設定ファイルが標準出力に出す字を JSON に混ぜない）。起動できなければ (None, 訳)。"""
        fd, out = tempfile.mkstemp(prefix="tiers-auth-", suffix=".json")
        os.close(fd)
        try:
            shell = _posix_shell(self.env, self.platform)
            if shell is not None:
                code, text = _run([shell, "-lic", f"{shlex.quote(cmd)} auth status --json > {shlex.quote(out)}"])
            else:
                code, text = None, f"{cmd} を起動できる PowerShell が無い"
                quoted, target = ("'" + x.replace("'", "''") + "'" for x in (cmd, out))
                for ps in ("pwsh", "powershell"):
                    exe = self.which(ps)
                    if exe:
                        code, text = _run([exe, "-NoLogo", "-NonInteractive", "-Command",
                                           f"& {quoted} auth status --json | Out-File -FilePath {target} -Encoding utf8; "
                                           "exit $LASTEXITCODE"])
                        break
                else:
                    path = self.which(cmd)
                    if path:
                        code, out_text, err_text = _run_apart([path, "auth", "status", "--json"])
                        return code, out_text if out_text.strip() else err_text
            if code is None:
                return code, text
            with open(out, encoding="utf-8-sig") as f:   # Windows PowerShell 5 の utf8 は BOM を付ける
                got = f.read()
            return code, got if got.strip() else text   # 何も書かなければ、シェルの出した訳（コマンドが無いなど）を返す
        except OSError as e:
            return None, str(e)
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass

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


def _login(probe, tier, cmd, label):
    """cmd（claude か起動コマンド）でログインしているか（claude auth status --json の loggedIn）の点検の項目。答えの JSON が読めない
    ときも通さない（前は claude --version しか見ず、ログインが切れていても段 0 を通した）。"""
    code, text = probe.auth_status(cmd)
    fix = [f"{cmd} を起動して /login を打つ（か {cmd} auth login）"]
    try:
        got = json.loads(text or "")
    except ValueError:
        got = None
    if not isinstance(got, dict) or not isinstance(got.get("loggedIn"), bool):
        return _item(tier, label, problem=f"{cmd} auth status --json の答えが読めない（終了コード {code}）: {_first_line(text)[:200]}",
                     fix=fix)
    if not got["loggedIn"]:
        return _item(tier, label, problem=f"{cmd} でログインしていない（{cmd} auth status --json の loggedIn が false）", fix=fix)
    return _item(tier, label, found=f"ログイン済み（{got.get('authMethod') or '方法は不明'}）")


def check_claude(probe):
    item, path = _installed(probe, 0, "claude", "Claude Code", ["--version"])
    return [item] + ([_login(probe, 0, "claude", "Claude Code のログイン")] if path else [])


def check_plugins(probe, config_dirs):
    """フォルダごとの、入れたプラグインの控えが消えた置き場（と、前の版の印 .orphaned_at の付いた消える置き場）を指していないかの点検の項目（段 0）。Claude Code は前の版の置き場を
    14 日で消すが、project の範囲の項目はそのプロジェクトで開き直すまで控えに残る（2026-10-18、~/.claude-p2 に消えた gates 0.7.0・
    attention 0.10.1 を指す項目が残っていた）。"""
    out = []
    for d in config_dirs:
        record = os.path.join(os.path.expanduser(d), "plugins", "installed_plugins.json")
        label = f"プラグインの控え（{d}）"
        if not probe.isdir(os.path.expanduser(d)):   # 打ち間違いを「控えが無い」として通さない
            out.append(_item(0, label, problem=f"{d} が無い", fix=["--config-dir にアカウントの設定のフォルダ（CLAUDE_CONFIG_DIR）を渡す"]))
            continue
        try:
            text = probe.read(record)
            plugins = json.loads(text).get("plugins") if text is not None else {}
        except (OSError, ValueError, AttributeError) as e:
            out.append(_item(0, label, problem=f"{record} が読めない（{e}）", fix=["Claude Code を起動して /plugin で入れた物を見る"]))
            continue
        if not isinstance(plugins, dict):
            out.append(_item(0, label, problem=f"{record} の plugins が表でない（控えの形が変わった）",
                             fix=["tiers の check_plugins を、今の控えの形に合わせて直す"]))
            continue
        gone = []
        for name, entries in plugins.items():
            for e in entries if isinstance(entries, list) else [entries]:
                path = e.get("installPath") if isinstance(e, dict) else None
                # 前の版の印（.orphaned_at）の付いた置き場は、Claude Code が 14 日で消すので、消えた物と同じに扱う
                if not isinstance(path, str) or not probe.isdir(path) or probe.read(os.path.join(path, ".orphaned_at")) is not None:
                    where = f"、{e['projectPath']}" if isinstance(e, dict) and e.get("projectPath") else ""
                    gone.append((name, (e.get("scope") if isinstance(e, dict) else None) or "?", where, path))
        if not gone:
            out.append(_item(0, label, found=f"{sum(len(v) if isinstance(v, list) else 1 for v in plugins.values())} 項目の置き場が在る"))
            continue
        out.append(_item(0, label, problem="消えた（か、前の版として消える）置き場を指す項目がある: "
                         + "、".join(f"{n}（{s}{w}）{p}" for n, s, w, p in gone),
                         fix=[f"CLAUDE_CONFIG_DIR={shlex.quote(d)} claude plugin uninstall {n} --scope {s}"
                              + ("（project・local の範囲は、その projectPath のフォルダで打つ。要るなら入れ直す）" if s != "user" else "（要るなら入れ直す）")
                              for n, s, _, _ in gone]))
    return out


# herdr integration status の claude の行（0.9.3 の形: "claude: current (v10) (<フックのパス>)"）。この版の herdr には JSON の出力が
# 無いので人向けの行を読む。読み方を知らない形・状態は、黙って通さずに「読めない」として出す
HERDR_LINK = re.compile(r"^claude:\s+(current|outdated|not installed|unknown)\b", re.M)


def check_herdr_links(probe, herdr, config_dirs):
    """フォルダごとの、herdr の Claude Code の連携の点検の項目（段 2）。連携はフォルダごとに入れる物で、入っていないアカウントの会話は
    herdr から会話の状態が見えない（待ち受けと部署の様子の元）。"""
    os_key = _os_key(probe.platform)
    out = []
    for d in config_dirs:
        label = f"herdr の連携（{d}）"
        if os_key == "win32":
            fix = [f'$env:CLAUDE_CONFIG_DIR = "{d}"; herdr integration install claude; Remove-Item Env:CLAUDE_CONFIG_DIR   （PowerShell）']
        else:
            fix = [f"CLAUDE_CONFIG_DIR={shlex.quote(d)} herdr integration install claude"]
        code, text, err = probe.run_in([herdr, "integration", "status"], os.path.expanduser(d))
        m = HERDR_LINK.search(text or "")
        if m and m.group(1) == "current":
            out.append(_item(2, label, found="入っている"))
        elif m and m.group(1) in ("outdated", "not installed"):
            out.append(_item(2, label, problem=f"herdr の Claude Code の連携が{'古い' if m.group(1) == 'outdated' else '入っていない'}",
                             fix=fix, guide=herdr_link_guide(os_key)))
        else:
            seen = next((line.strip() for line in (text or "").splitlines() if line.startswith("claude")), "") or _first_line(text + err)
            out.append(_item(2, label, problem=f"herdr integration status の claude の行が読めない（終了コード {code}）: {seen[:200]}",
                             fix=["herdr integration status を手で打って見る。形が変わったなら tiers の HERDR_LINK を直す"]))
    return out


def check_statusline(probe, config_dirs):
    """フォルダごとの、tiers の statusline（印「⧖ バックグラウンド作業中 N 本」を出す）の点検の項目（段 2）。statusLine が tiers の
    statusline を指すアカウントだけ、印を herdr が作業中と見分ける支度がそろっているかを見る（使うかは利用者が tiers-statusline setup で
    決める。statusLine はアカウントに 1 つなので、利用者の物を押しのけない）。"""
    out = []
    over, remote = statusline.herdr_paths(probe.env)
    for d in config_dirs:
        label = f"statusline（{d}）"
        try:
            line = json.loads(probe.read(os.path.join(os.path.expanduser(d), "settings.json")) or "{}").get("statusLine")
        except (OSError, ValueError, AttributeError):
            line = None   # settings.json が読めないのは、使っていないのと同じに扱う（Claude Code の起動が先に止まる）
        if not (isinstance(line, dict) and line.get("command") == statusline.command_for(d)):
            out.append(_item(2, label, found=f"tiers の statusline は使っていない（使うなら tiers-statusline setup --config-dir {shlex.quote(d)}）"))
            continue
        setup = f"tiers-statusline setup --config-dir {shlex.quote(d)}"
        if not probe.isdir(str(statusline.data_link(d))):
            out.append(_item(2, label, problem=f"statusLine の指すリンク {statusline.data_link(d)} が無い（印もステータスラインも出ない）", fix=[setup]))
            continue
        try:
            cur, base = probe.read(str(over)), probe.read(str(remote))
            want = statusline.compose(base, statusline.RULE.read_text(encoding="utf-8")) if base is not None else None
        except (OSError, ValueError) as e:
            out.append(_item(2, label, problem=f"herdr の判定ルールの上書きを作れない（{e}）", fix=["tiers-statusline refresh を打って訳を見る"]))
            continue
        if cur is None or not cur.startswith(statusline.MARK):
            out.append(_item(2, label, problem=f"herdr の判定ルールの上書き {over} が{'無い' if cur is None else 'tiers の作った物でない'}"
                             "（印を herdr が作業中と見分けない）", fix=[setup]))
        elif want is not None and cur != want:
            out.append(_item(2, label, problem=f"herdr の判定ルールの上書き {over} が、herdr の今の配られたルールから作った物でない"
                             "（上書きの間は herdr が配り直したルールが効かない）", fix=["tiers-statusline refresh"]))
        else:
            out.append(_item(2, label, found="tiers の statusline を使い、印を herdr が見分ける支度がそろっている"))
    return out


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


def check_herdr(probe, launchers, config_dirs=()):
    os_key = _os_key(probe.platform)
    item, path = _installed(probe, 2, "herdr", "herdr", ["--version"], guide=herdr_install_guide(os_key))
    out = [item]
    if path:
        # herdr status server --json（0.9.3 で読んだ形: {"status": "running", "running": true, …, "socket": "<パス>"}。動いていなければ
        # status は not_running、running は false）。人向けの「status: running」の行を読まない
        # 止まっているときに 0 以外で終わっても、答えの JSON（running と socket）は読む
        code, text, err = probe.run_apart([path, "status", "server", "--json"])
        try:
            got = json.loads(text)
        except ValueError:
            got = None
        if isinstance(got, dict) and got.get("running") is True:
            out.append(_item(2, "herdr の動き", found="herdr の server が動いている"))
        else:
            # どこの socket を見たか（答えの socket）を添える。HOME や XDG_CONFIG_HOME が違うと、別の置き場の server を見ていることが
            # ある（まっさらな環境での 1 回目の試しの 8）
            sock = got.get("socket") if isinstance(got, dict) else None
            where = f"（見た socket: {sock}）" if isinstance(sock, str) and sock else ""
            said = (f"herdr の server が動いていない{where}" if isinstance(got, dict)
                    else f"herdr status server --json の答えが読めない（終了コード {code}）: {_first_line(text + err)[:200]}")
            out.append(_item(2, "herdr の動き", problem=said,
                             fix=["作業するフォルダで herdr を起動する: herdr"], guide=herdr_start_guide(os_key)))
        out += check_herdr_links(probe, path, config_dirs)
        out += check_statusline(probe, config_dirs)
    for cmd in launchers:
        if probe.shell_has(cmd):
            out.append(_item(2, f"起動コマンド {cmd}", found=f"{cmd} がシェルで見つかる"))
            if cmd != "claude":   # claude のログインは段 0 で見た
                out.append(_login(probe, 2, cmd, f"起動コマンド {cmd} のログイン"))
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


def check(tier, launchers=(), probe=None, config_dirs=()):
    """段 0〜tier を点検した結果（--json の形の dict）。config_dirs を渡せば、フォルダごとの点検も足す。"""
    probe = probe or Probe()
    config_dirs = list(dict.fromkeys(config_dirs))
    items = check_claude(probe) + check_plugins(probe, config_dirs)
    if tier >= 1:
        items += check_gh(probe)
    if tier >= 2:
        items += check_herdr(probe, list(launchers) or ["claude"], config_dirs)
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
    ap.add_argument("--config-dir", action="append", default=[], metavar="フォルダ",
                    help="アカウントの Claude Code の設定のフォルダ（繰り返して複数）。渡せば、プラグインの控え（段 0）と herdr の連携（段 2）を"
                         "フォルダごとに点検する")
    ap.add_argument("--json", action="store_true", help="JSON で出す")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if not 0 <= a.tier <= TOP:
        print(f"止めた: --tier は 0〜{TOP}（渡されたのは {a.tier}）", file=stdout)
        return 2
    result = check(a.tier, a.launcher, probe, a.config_dir)
    if a.json:
        print(json.dumps(result, ensure_ascii=False), file=stdout)
    else:
        again = "tiers --tier " + str(a.tier) + "".join(f" --launcher {shlex.quote(c)}" for c in a.launcher) \
            + "".join(f" --config-dir {shlex.quote(d)}" for d in a.config_dir)
        print("\n".join(lines(result, again)), file=stdout)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
