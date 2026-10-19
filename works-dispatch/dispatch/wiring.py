"""口の束（Ports）の組み立て（composition root）。入口（dispatch.py）と単独で呼ばれるノード（nodes/accounts.py の main）が、外への口
（ports の term・chat と gitx・ghx・tierx・vscode）をここで束ねて流れに渡す。流れとノードは束を引数で受け、どのツールが口の向こうに
居るかを知らない。

始める前の確かめ（Ports.preflight）は、口の向こうのツールそれぞれの版・設定・連携を見るので、ツールの名前と設定の場所を知ってよい
（チェック D9〔tests/fences.py〕の外す所）。ツールを替えるときは ports とここを直す。
"""

import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import time
import tomllib

import config
import filex
import ghx
import gitx
import limits
import limits_entry
import tierx
import vscode
from nodes import accounts, clean, cost, fresh, prs
from ports import chat, term

# 手元の herdr の API に要るメソッド（herdr の文書は、手元の版の API を api schema で確かめるよう求めている）。PR を開く道が使う物。
# pane.process_info はコマンドを打つ前にペインの前がシェルかを見る口（herdr pane process-info）
HERDR_METHODS = {"agent.prompt", "agent.get", "agent.wait", "pane.list", "pane.send_text", "pane.process_info", "workspace.list",
                 "workspace.close", "worktree.list", "worktree.create", "worktree.open", "worktree.remove"}
# 部署（--task・--ask・--sync）にだけ要るメソッド（ペインと作業場に名前と札を付ける・画面を読む・入力フィールドに残った字に Enter を足し、
# 止まった attach を Ctrl+Z で戻す）
TASK_HERDR_METHODS = {"pane.rename", "pane.report_metadata", "pane.read", "pane.send_keys", "workspace.rename"}


def _posix_shell(env, posix=None):
    """作業場のペインと同じログインのシェル。POSIX のシェルの無い所（Windows の native の herdr）では None。"""
    if not (os.name != "nt" if posix is None else posix):
        return None
    return env.get("SHELL") or "/bin/sh"


def _shell_has(cmd, env=os.environ, runner=subprocess.run, which=shutil.which, posix=None):
    """作業場と同じ種類のシェル（利用者のログインかつ対話のシェル。-lic）で、そのコマンドが見つかるか。シェルの関数も数える。
    POSIX のシェルが無ければ、PATH の上で探す。"""
    shell = _posix_shell(env, posix)
    if shell is None:
        return which(cmd) is not None
    p = runner([shell, "-lic", f"command -v {shlex.quote(cmd)}"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode == 0


# タブバーの行とサイドバーのフックが指す、このプラグインのスクリプト。プラグインを更新すると、入った場所（版ごとのフォルダ）が変わる
PLUGIN_SCRIPT = re.compile(r"""[^\s"'=]+[/\\]dispatch[/\\](?:limits|activity)\.py""")
ENTRY_SCRIPT = re.compile(r"""[^\s"'=]+[/\\](?:limits-entry\.py|run-python\.sh)""")   # limits_dir に写した版に依らない入口


def gone_plugin_paths(texts, installed=None):
    """設定の文字列のなかの、このプラグインのスクリプトを指すパスのうち、使えないもの（重なりは 1 つ）の (パス, 訳) の並び。
    使えないのは、もう無い・版のフォルダに .orphaned_at が付いた（前の版。Claude Code が 14 日で消す）・installed（今入っている
    場所の並び）を渡したとき、版の置き場（plugins/cache/ の下）に在ってそのどれでもない、の 3 つ。"""
    found, seen = [], set()
    roots = {os.path.normcase(os.path.realpath(x)) for x in installed or ()}
    for text in texts:
        for m in PLUGIN_SCRIPT.findall(text):
            path = os.path.expanduser(m)
            if path in seen:
                continue
            seen.add(path)
            version = pathlib.Path(path).parent.parent
            if not os.path.isfile(path):
                found.append((path, "もう無い"))
            elif (version / limits_entry.ORPHANED).exists():
                found.append((path, f"前の版（{limits_entry.ORPHANED} が付き、Claude Code が消す）"))
            elif roots and version.parent.parent.parent.name == "cache" and os.path.normcase(os.path.realpath(version)) not in roots:
                found.append((path, "今入っていない版"))
    return found


def herdr_config_path(env):
    home = env.get("HOME") or os.path.expanduser("~")
    return pathlib.Path(env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")) / "herdr" / "config.toml"


def plugin_notes(herdr_toml, config_dirs, limits_dir=None):
    """herdr の設定とアカウントの settings.json が、使えない版のこのプラグインを指していれば、その注記の並び。入れた物の控えが
    消えた置き場を指していれば、それも足す。設定が指す写した入口（limits-entry.py・run-python.sh）が無ければ、それも足す。limits_dir に写した
    タブバーの入口（limits.py herdr-config）が今の版とずれていれば写し直し、写し直せなかった物を足す。--check と --tree が出す。"""
    files = [herdr_toml] + [pathlib.Path(d) / "settings.json" for d in config_dirs]
    installed = [x for d in config_dirs for x in limits_entry.install_paths(os.path.expanduser(d))]
    texts = [s for f in files for s in setting_strings(f)]
    notes = [f"herdr の設定かフックが、使えない版のスクリプトを指している: {path}（{why}。プラグインの更新で場所が変わった。"
             "skills/dispatch/references/setup.md の「任意: herdr の見た目を整える」で行を出し直す）"
             for path, why in gone_plugin_paths(texts, installed)]
    lost = sorted({os.path.expanduser(m) for t in texts for m in ENTRY_SCRIPT.findall(t)} - {""})
    notes += [f"herdr の設定が指すタブバーの入口 {p} が無い（消された。limits.py herdr-config を打ち直すと写し直す）"
              for p in lost if not os.path.isfile(p)]
    for d in config_dirs:
        gone = limits_entry.gone_installs(os.path.expanduser(d))
        if gone:
            notes.append(f"{d} の入れたプラグインの控え（plugins/installed_plugins.json）が、消えた置き場を指している: "
                         + "、".join(f"{n}（{s}）" for n, s, _ in gone)
                         + "（どの項目が効くかが分からない。要らなければ CLAUDE_CONFIG_DIR を合わせて claude plugin uninstall <名前> --scope <範囲> を、"
                           "project の範囲はそのフォルダで打つ。tiers --config-dir でも見られる）")
    drift = limits.sync_entry(limits_dir) if limits_dir else []   # 違えば写し直す。写し直せなかった物だけ言う
    if drift:
        notes.append(f"{limits_dir} に写したタブバーの入口（{'・'.join(drift)}）が今の版と違い、写し直せなかった（limits.py herdr-config を打ち直す）")
    return notes


def _leaves(value):
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return [s for v in value for s in _leaves(v)]
    return [value] if isinstance(value, str) else []


def setting_strings(path):
    """設定のファイル（.json か .toml）の中の文字列を、書くときのエスケープ（\\ など）を解いて返す。
    その形で読めなければ中身をそのまま 1 つ、ファイルが無ければ空。"""
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        return _leaves(json.loads(text) if str(path).endswith(".json") else tomllib.loads(text))
    except ValueError:
        return [text]


# herdr の設定に足す作業場の行（$kind に部署の席の見え方を出す。herdr の既定の行〔state_icon・workspace と branch・git_status〕に足した形）
SPACES_ROWS = ('[ui.sidebar.spaces]\n'
               'rows = [\n'
               '  ["state_icon", "workspace", { token = "$kind" }],\n'
               '  ["branch", "git_status"],\n'
               ']')


def spaces_show_kind(path):
    """herdr の設定（config.toml）の作業場の行（[ui.sidebar.spaces] の rows）に $kind が在るか。字のまま（"$kind"）でも
    表（{ token = "$kind" }）でもよい。ファイルが無い・読めないときも無いとする。"""
    try:
        rows = tomllib.loads(pathlib.Path(path).read_text(encoding="utf-8"))["ui"]["sidebar"]["spaces"]["rows"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    cells = [c for row in rows if isinstance(row, list) for c in row] if isinstance(rows, list) else []
    return any((c.get("token") if isinstance(c, dict) else c) == "$kind" for c in cells)


MARK = "@@CLAUDE_CONFIG_DIR="
COST_FILE = "dispatch-cost.json"  # 1 件あたりの使用率の測り（cost ノード）。使用率の控えと同じ置き場
SENT_FILE = "dispatch-sent.json"  # PR ごとに最後に /catchup を送った時刻と、その時の場所の head（送り直しの判断。fresh ノード）


def _login_config_dir(env=os.environ, runner=subprocess.run, posix=None):
    """作業場のペインで新しく起きるログインのシェルが持つ CLAUDE_CONFIG_DIR（無ければ None）。

    config_dir を書かないアカウントは、ペインのシェルで素のまま起きる。dispatch を走らせている会話の CLAUDE_CONFIG_DIR は
    その会話のアカウントのもので、ペインのものではないので、渡さずにシェルを起動し、シェルの設定が入れる値だけを読む。
    シェルが起動のときに出す挨拶などと混ざらないよう、印で挟んだ所だけを読む。
    POSIX のシェルが無い所（Windows）では、ペインのシェルの値を外から読む手が無いので、既定のフォルダ（None）とする。
    """
    shell = _posix_shell(env, posix)
    if shell is None:
        return None
    child = {k: v for k, v in env.items() if k != "CLAUDE_CONFIG_DIR"}
    p = runner([shell, "-lic", f'printf "\\n{MARK}%s@@\\n" "${{CLAUDE_CONFIG_DIR-}}"'], capture_output=True, text=True, encoding="utf-8", errors="replace", env=child)
    for line in (p.stdout or "").splitlines():
        if line.startswith(MARK) and line.endswith("@@"):
            return line[len(MARK):-2] or None
    return None


def env_command(name, value, command, windows=None):
    """環境変数を 1 つ入れてコマンドを打つ 1 行。Windows（の PowerShell）は `名前=値 コマンド` の形を打てないので、`$env:名前` に入れてから打つ
    形にする（入れた値はその PowerShell の窓に残る）。"""
    if os.name == "nt" if windows is None else windows:
        return f"$env:{name}='{value}'; {command}"
    return f"{name}={shlex.quote(str(value))} {command}"


# 会話から切り離してコマンドを走らせ、出力を書き足す殻（POSIX。nodes/wake.py の DETACH の、終わりの値を書かず出力を書き足す形）
APPEND_DETACH = 'log=$1; shift; ( "$@" >>"$log" 2>&1 </dev/null ) &'


class Ports:
    """外への口を 1 つに束ねる。試験は同じ名前の口を持つ偽物を渡す。書く口は herdr のモジュールそのもので、launch と turn だけが使う。"""

    def __init__(self, herdr_methods=None, shell_has=None, gh_ok=None, env=None, gh_env=None, herdr_integration=None,
                 login_config_dir=None, worktrees=None, task_flags=None, tier_check=None):
        self._herdr_methods = herdr_methods or term.methods
        self._task_flags = task_flags or chat.missing_flags
        self._tier_check = tier_check or (lambda launchers: tierx.check(launchers, env=self.env))
        self._herdr_integration = herdr_integration or (lambda cdir: term.claude_integration(cdir, dict(self.env)))
        self._login_config_dir = login_config_dir or (lambda: _login_config_dir(self.env))
        self._account_env = None
        self._shell_has = shell_has or _shell_has
        self._gh_ok = gh_ok or ghx.can_read
        self.env = os.environ if env is None else env
        self._gh_env = gh_env
        self._gh_envs = {}
        self._worktrees = worktrees
        self.term = term
        self.git = gitx
        self.gh = ghx

    @property
    def account_env(self):
        """アカウントの設定のフォルダを決めるための環境。CLAUDE_CONFIG_DIR だけを、ペインの新しいログインのシェルの値に替える（_login_config_dir）。"""
        if self._account_env is None:
            env = {k: v for k, v in self.env.items() if k != "CLAUDE_CONFIG_DIR"}
            found = self._login_config_dir()
            if found:
                env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(found)
            self._account_env = env
        return self._account_env

    def gh_env(self, repo):
        """そのリポジトリで gh を呼ぶ子の環境。gh_user が無ければ None（このプロセスの環境のまま）。鍵はアカウントごとに 1 度だけ取り出す。"""
        if self._gh_env:
            return self._gh_env(repo)
        if not repo.gh_user:
            return None
        if repo.gh_user not in self._gh_envs:
            self._gh_envs[repo.gh_user] = ghx.env_for(repo.gh_user, dict(self.env))
        return self._gh_envs[repo.gh_user]

    def preflight(self, cfg, task=False):
        """始める前の確かめ。(足りない物, 注記)。task はサブエージェント（--task）の回で、/catchup と 2 ターン目の文を見ない代わりに、
        サブエージェントに要る物（ペインの名前・会話の名前）を足りない物にする。ほかの回では、それらは注記にとどめる。"""
        problems, notes = [], []
        task_only = problems if task else notes
        try:
            have = self._herdr_methods()
            missing = HERDR_METHODS - have
            if missing:
                problems.append(f"手元の herdr の API に {', '.join(sorted(missing))} が無い（herdr の版を確かめる）")
            if TASK_HERDR_METHODS - have:
                task_only.append(f"手元の herdr の API に {', '.join(sorted(TASK_HERDR_METHODS - have))} が無い"
                                 "（部署（--task）のペインに名前と札を付けられない。herdr を新しくする）")
        except (term.Error, OSError, ValueError) as e:
            problems.append(f"herdr に届かない: {e}")
        missing_flags = self._task_flags()
        if missing_flags:
            task_only.append(f"PATH の claude が {', '.join(missing_flags)} を持たない（部署（--task）は、名前を付けた裏の会話として、"
                             "その会話にだけ効く設定を渡して起動する。Claude Code を新しくする）")
        for repo in cfg.repos:
            if not task and not (repo.second_prompt or "").strip():
                problems.append(f"{repo.repo}: 2 ターン目の文が空（設定の [[repos]] の second_prompt_file に書いたファイルに、送る文を書く）")
        for a in cfg.accounts:
            if not self._shell_has(a.command):
                problems.append(f"アカウント {a.name} の起動のコマンド {a.command} がシェルで見つからない")
            cdir = config.effective_config_dir(a, self.account_env)
            try:
                state = self._herdr_integration(cdir)
            except (term.Error, OSError) as e:
                state = f"読めない（{e}）"
            if not state.startswith("current"):
                notes.append(f"アカウント {a.name} に herdr の連携が入っていない: {state}（作業中の判定は無くても動く。"
                             f"herdr を立ち上げ直したときに会話を戻すのに要る。入れる: {env_command('CLAUDE_CONFIG_DIR', cdir, 'herdr integration install claude')}）")
            found = chat.catchup_commands(cdir)
            if not task and len(found) != 1:
                problems.append(f"アカウント {a.name}（{cdir}）で /catchup のコマンドが 1 つに決まらない"
                                f"（skills/catchup/SKILL.md か commands/catchup.md を持つプラグイン: {', '.join(found) or '無し'}）")
            if a.limits and not (pathlib.Path(cfg.limits_dir) / f"{a.name}.json").is_file():
                notes.append(f"アカウント {a.name} の使用率の控えが無い（使用率が分からないものとして順の最後に置く）")
        notes += limits.problems(cfg.accounts, cfg.limits_dir, time.time())
        # 信頼はアカウントをまたいで広げる（Ports.trust）ので、知らせるのはどのアカウントも信頼していない元の clone だけ
        for repo in cfg.repos:
            if not any(chat.is_trusted(chat.trust_file(a.config_dir, self.account_env), repo.source) for a in cfg.accounts):
                notes.append(f"どのアカウントも {repo.source} を信頼していない（ブランチごとの作業場で毎回フォルダの信頼の確認が出る。"
                             f"どれか 1 つのアカウントで一度 {repo.source} に Claude Code を起動し、信頼すると、ほかのアカウントにも広げて出なくなる）")
        herdr_toml = herdr_config_path(self.env)
        if not spaces_show_kind(herdr_toml):
            task_only.append(f"herdr の設定 {herdr_toml} の作業場の行（[ui.sidebar.spaces] の rows）に $kind が無い（部署の作業場の行に、"
                             "永続・毎回クリア／永続・引き継ぎ／エフェメラルの印が出ない）。rows のどこかに { token = \"$kind\" } を置く。"
                             f"[ui.sidebar.spaces] が無ければ、次を足して herdr server reload-config を打つ:\n{SPACES_ROWS}")
        notes += plugin_notes(herdr_toml, [config.effective_config_dir(a, self.account_env) for a in cfg.accounts], cfg.limits_dir)
        for repo in cfg.repos:
            if gitx.origin_repo(repo.source) != repo.repo:
                problems.append(f"{repo.repo}: 元の clone {repo.source} が、このリポジトリの clone でない")
            elif not gitx.is_main_worktree(repo.source):
                problems.append(f"{repo.repo}: 元の clone {repo.source} が linked worktree で、本体の checkout でない"
                                "（git rev-parse の git-dir と git-common-dir が違う。source には本体の clone を書く）")
            else:
                try:
                    self.places(repo)
                except (term.Error, OSError) as e:
                    problems.append(f"{repo.repo}: herdr が元の clone {repo.source} の worktree を並べられない（{e}）")
            for rel in repo.copy_files:
                if not os.path.isfile(os.path.join(config.copy_root(repo), rel)):
                    notes.append(f"{repo.repo}: 写すファイルが {config.copy_root(repo)} に無い: {rel}")
        for repo in cfg.repos:
            try:
                env = self.gh_env(repo)
            except ghx.GhError as e:
                problems.append(f"{repo.repo}: {e}" + ("。部署の会話に渡す gh のアカウント（会社の形か設定の gh_user）の鍵が要る。"
                                                       "鍵を GH_TOKEN で渡しているなら gh_user を書かない" if task else ""))
                continue
            if task:
                continue   # 部署の回は GitHub を読まない（メインブランチの名前は手元の origin/HEAD から。手元の bare リポジトリでも立つ）
            if not self._gh_ok(repo.repo, env=env):
                problems.append(f"gh が {repo.repo} を読めない。whose-turn が自分の番の PR を集められない"
                                "（gh auth status で、このリポジトリを読めるアカウントが有効かを確かめる）")
        return problems, notes

    def tiers(self, launchers):
        """要るツールの段の点検（tiers プラグイン）の結果。部品が無ければ tierx.TierError。"""
        return self._tier_check(launchers)

    def fetch_prs(self, repo):
        """(自分の番の PR の並び, whose-turn の limited の番号の集合)。"""
        return prs.read(repo.repo, env=self.gh_env(repo))

    def list_sessions(self, config_dir, include_done=False):
        return chat.sessions(config_dir, base_env=self.account_env, include_done=include_done)

    def pause(self):
        """部署の裏の会話を打ち込んだ後に、シェルが前に戻るのを見る間。"""
        time.sleep(1)

    def department_settings(self):
        """部署の裏の会話にだけ効かせる設定のファイル（--settings。worktree.bgIsolation を none にし、先に作った作業場で働かせる）。"""
        return str(pathlib.Path(__file__).resolve().parent / "templates" / "department-settings.json")

    def branch(self, cwd):
        return gitx.branch(cwd)

    def origin(self, cwd):
        return gitx.origin_repo(cwd)

    def is_clean(self, cwd):
        return gitx.is_clean(cwd)

    def unpushed(self, cwd, landed=None):
        return gitx.unpushed(cwd, landed=landed)

    def pr_info(self, repo, number):
        return ghx.pr_info(repo.repo, number, env=self.gh_env(repo))

    def places(self, repo):
        """元の clone の worktree の並び（herdr アダプタの worktrees。元の clone 自身も linked=False で入る）。"""
        if self._worktrees:
            return self._worktrees(repo.source)
        return self.term.worktrees(repo.source)

    def stashed(self, cwd, branch):
        return gitx.stashed(cwd, branch)

    def head_sha(self, cwd):
        return gitx.head_sha(cwd)

    def pr_for_branch(self, repo, branch):
        """そのブランチの PR（{number, state, head_sha}・None）。読めなければ clean.Unknown（片付けは消さない側に倒す）。"""
        try:
            return ghx.pr_for_branch(repo.repo, branch, env=self.gh_env(repo))
        except ghx.GhError as e:
            raise clean.Unknown(str(e))

    def issue_info(self, repo, number):
        return ghx.issue_info(repo.repo, number, env=self.gh_env(repo))

    def issue_branches(self, repo, number):
        return ghx.issue_branches(repo.repo, number, env=self.gh_env(repo))

    def default_branch(self, repo):
        """メインブランチの名前。GitHub に問わず、代表の clone の手元の origin/HEAD（無ければ origin に問う）から取る（gitx.default_branch。
        部署の回を手元の bare リポジトリでも動かすため）。読めなければ gitx.GitError。"""
        return gitx.default_branch(repo.source)

    def read_limits(self, limits_dir, names):
        return accounts.read_limits(limits_dir, names)

    def refresh_limits(self, cfg, names, force=True):
        """名指したアカウントの使用率を API に問い合わせて取り直す（出力 0 トークン。失敗は probe.log）。
        force は控えの古さに依らず全部。偽なら、古いアカウントだけ（limits.py の probe と同じ）。"""
        limits.probe_all([a for a in cfg.accounts if a.name in names], cfg.limits_dir, self.env, self.now(), force=force)

    def load_cost(self, limits_dir):
        return cost.load(pathlib.Path(limits_dir) / COST_FILE)

    def save_cost(self, limits_dir, samples):
        cost.save(pathlib.Path(limits_dir) / COST_FILE, samples)

    def catchup_command(self, config_dir):
        """そのアカウントで送る catchup のコマンドの名前。始める前の確かめで 1 つに決まることを見てある。"""
        cdir = config.effective_config_dir(config.Account("", "", config_dir), self.account_env)
        found = chat.catchup_commands(cdir)
        return found[0] if len(found) == 1 else None

    def open_pages(self, repo, numbers):
        """送り終えた PR の /catchup のページのうち書かれているものを、VS Code の窓にタブで開く（vscode.open_pages）。"""
        return vscode.open_pages([p for p in (vscode.page_path(repo.repo, n) for n in numbers) if p.is_file()], self.env)

    def trusted(self, account, folder):
        """そのアカウントがフォルダを信頼済みか（claudex.is_trusted）。"""
        return chat.is_trusted(chat.trust_file(account.get("config_dir"), self.account_env), folder)

    def caller(self, listed):
        """このコマンドを走らせている会話の (アカウントの名, 会話の名前)。Claude Code の中から走っていなければ (None, None)。"""
        return chat.caller(listed, self.env.get("CLAUDE_CODE_SESSION_ID"), chat.ancestors())

    def caller_pid(self, listed):
        """このコマンドを走らせている会話の処理（Claude Code）の番号。一覧に見えなければ None。"""
        return chat.caller_pid(listed, self.env.get("CLAUDE_CODE_SESSION_ID"), chat.ancestors())

    def stop_session(self, config_dir, job):
        """そのアカウントの裏の会話を止める（--move が起動し直す前に）。(止まったか, claude の言葉)。"""
        return chat.stop_session(config_dir, job, base_env=self.account_env)

    def same_process(self, pid):
        """その番号の処理が、このコマンドを走らせている処理の親をたどった中に在るか（claudex.in_process）。"""
        return chat.in_process(pid)

    def running_chat(self, pid):
        """その番号の処理が今動いている Claude Code か（--desk が、窓口の席に座っている会話が動いているかを見る）。"""
        return chat.running(pid)

    def trust(self, account, source, clone, others=()):
        """元の clone をこのアカウントかほかのアカウント（others。設定の accounts）のどれかが信頼済みなら、ブランチの場所（worktree）にも
        信頼の印を付ける（claudex.inherit_trust）。"""
        return chat.inherit_trust(chat.trust_file(account.get("config_dir"), self.account_env), source, clone,
                                     [chat.trust_file(o.config_dir, self.account_env) for o in others])

    def activity(self, repo, number):
        """PR の動き（ghx.pr_activity）。自分のログイン名は 1 度だけ問い合わせる。"""
        env = self.gh_env(repo)
        if not hasattr(self, "_me"):
            self._me = ghx.login(env=env)
        return ghx.pr_activity(repo.repo, number, self._me, env=env)

    def load_sent(self, limits_dir):
        """前に送った時刻の控え {PR の鍵: 時刻}。ファイルが無ければ空。読めない・表でなければ ValueError（空として読んで
        save_sent が上書きすると、前に送った時刻が全部消える）。"""
        path = pathlib.Path(limits_dir) / SENT_FILE
        try:
            got = jsonio_load(path)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            raise ValueError(f"前に送った時刻の控え {path} が読めない（{e}）") from e
        if not isinstance(got, dict):
            raise ValueError(f"前に送った時刻の控え {path} が JSON の表でない（{type(got).__name__}）")
        return got

    def save_sent(self, limits_dir, sent):
        filex.replace(pathlib.Path(limits_dir) / SENT_FILE, json.dumps(sent, ensure_ascii=False, indent=1, sort_keys=True))

    def state(self, config_dir, path):
        """そのフォルダの中の会話の状態を Claude Code 自身に問う（claude agents --json の status。idle・busy など）。
        会話が見えない・読めなければ None。"""
        try:
            items = self.list_sessions(config_dir)
        except chat.Error:
            return None
        got = [i.get("status") or i.get("state") for i in items if fresh.inside(i.get("cwd") or "", path)]
        return got[0] if len(got) == 1 else None

    def now(self):
        return time.time()

    def spawn(self, argv, cwd, log, env):
        """argv を打った会話から切り離して走らせ、終わりを待たない。出力はファイル log に書き足す。POSIX では外の sh がすぐ終わり、
        中の処理は init の子になる（会話の処理が止まっても一緒に止まらない。nodes/wake.py の DETACH と同じ形）。"""
        if os.name != "nt":
            subprocess.Popen(["/bin/sh", "-c", APPEND_DETACH, "sh", log, *argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True).wait()
            return
        with open(log, "a", encoding="utf-8") as f:
            subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT)

    def cwd(self):
        """このコマンドを打った場所（部署の回と --init-company が、--repo の無いときに会社を決める所）。"""
        return os.getcwd()

    def common_of(self, cwd):
        """その場所の属するリポジトリの元の clone のルート（git の共通の .git から）。git でなければ None。"""
        got = gitx.common_dir(cwd)
        return gitx.root_of(got) if got else None

    def attrs(self, path):
        """部署（worktree）の git の属性 company.<名前>。"""
        return gitx.worktree_attrs(path)


def jsonio_load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def setting_notes(env, config_dirs, limits_dir=None):
    """端末の口の設定とアカウントの settings.json の注記（plugin_notes）。端末の口の設定の場所は env から決める。--tree が出す。"""
    return plugin_notes(herdr_config_path(env), config_dirs, limits_dir)
