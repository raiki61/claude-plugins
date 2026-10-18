#!/usr/bin/env python3
"""自分の番の PR ごとに、その枝の作業場（元の clone の git worktree と herdr の作業場）を用意し、選んだアカウントの Claude Code で起こし、
1 ターン目に `/catchup <番号>`、2 ターン目に設定の文を送る。AI は使わない（設計書 works-dispatch/docs/specs/2026-10-14-catchup-dispatch-design.md）。

流れ（どのノードの次に何を呼ぶか）を持つのはこのファイルだけ。ノードは流れを知らない（D3）。
1. 始める前の確かめ。足りない物があれば全部並べて、何も起こさずに終了の値 2 で止まる
2. prs → sessions → （一覧で回すときは fresh）→ accounts → assign（ここまで外には書かない。--dry-run はここで、作業場を作るか使い直すかを
   報告して終える）
3. provision・信頼の印（元の clone を信頼済みのアカウントなら worktree にも付ける）・launch を 1 件ずつ順に全部先に済ませ、turn を 1 件ずつ
   並べて走らせる（1 件の /catchup が長くても、ほかが遅れない）
4. report
止まっている（blocked）・会話が開いている（already_open）などは誤りではないので、終了の値は 0。

一覧で回すとき（--pr・--issue 無し）は、2 の fresh で、自分が作者でレビュアーの付いていない PR を外し、会話の開いている PR を送り直すか決める。
会話の開いていない PR も、前に送った控えが有って、その後に自分以外の動きも head の変化も無ければ開かない（no_news）。
送り直す PR は、provision の前に古い会話を終えて（turn.close_session）ペインの作業場を畳み（clean.release）、同じ場所に立て直す。
最後に、閉じた PR の場所を片付ける（_tidy。--dry-run は並べるだけ）。

片付け（--clean）は、元の clone の linked worktree のうち消してよいものを並べるだけで、--apply を付けた時だけ消す（nodes/clean.py）。

--pr N は自分の番の一覧（whose-turn）を使わず、指した PR だけを開く。止めている実装や、見に行くだけの PR に使う。
--issue N は、issue に結んだ枝の場所を開き（枝が無ければ GitHub に作って issue に結ぶ）、1 ターン目の /catchup N まで送って止める。
--no-second は 2 ターン目の文を送らず、/catchup だけで止める。

--task 名前 は、部署を 1 つ立てる（_task）。枝の場所を PR と同じ決まりで開き（herdr の、元の clone の子の作業場）、使用率でアカウントを
1 つ選び、その作業場で Claude Code の裏の会話（claude --bg）を、名前と頼みのファイルを読ませる最初の文を付けて起こし、同じペインで
attach して画面を出す（会社の形の設計 9.1）。最初の文の後ろに、呼んだ会話への連絡の道（同じアカウントなら SendMessage、違えば画面に
書いて止まる）を書き足す。作業の終わりは待たない。作業場の git の設定 company.<名前> に、部署の属性（役・アカウント・会話の名前と
id・頼み元〔呼んだ会話〕）を書く（会社の形の設計 4.2）。--clean は、会話が終わり枝が本流に入った部署を、claude rm と一緒に片付ける。

--tree は、herdr に開いている会社（リポジトリ）ごとに、会社の情報（名前と受ける仕事）と部署（枝・役・アカウント・頼み元・herdr の
状態）を出す（_company。--json で JSON）。--sync は、部署の属性から herdr のペインの名前・表示名・札を付け直す（何度打っても同じ。会社の形が替わったときは、番の終わりの
フック shape_hook.py が、その会社の分を同じ中身で付け直す）。
どちらも dispatch の設定が無くても動く（有れば、会話のアカウントと、設定の置き場の会社の情報を見る）。

使い方: python3 dispatch.py [--config <パス>] [--repo OWNER/NAME] [--pr N ... | --issue N] [--no-second] [--dry-run | --clean [--apply]]
        python3 dispatch.py --task <名前> --branch <枝> --brief <頼みのファイル> [--repo OWNER/NAME か代表の clone] [--base <枝>]
                            [--from-name <呼んだ会話の名前>] [--from-account <アカウントの名>] [--role <役>] [--dry-run]
        python3 dispatch.py --tree [--json] | --sync [--dry-run]
        python3 dispatch.py --ask <会社/役 か部署の名前か会社の名前> (--text <文> | --brief <ファイル>) [--task <名前> --branch <枝>] [--dry-run]
        python3 dispatch.py --deliver <要約のファイル> [--dry-run]
        python3 dispatch.py --rest（部署か窓口の場所から。今は会話を空にしてよい区切りと印す）
        python3 dispatch.py --done（都度の部署の場所から。納品して本流に入れ終えたので、番の終わりに会話を止めて部屋を片付けてよいと印す）
        python3 dispatch.py --retire <部署>（都度の部署の会話を止めてから、--clean と同じ決まりで片付ける）
        python3 dispatch.py --land <部署> [--repo OWNER/NAME か代表の clone] [--dry-run]
        python3 dispatch.py --reorg [--name <新しい名前>] [--role <役>] [--resident | --per-task] [--boss <頼み元> [--boss-account <名>]] [--dry-run]
        python3 dispatch.py --desk [<名前>] [--role <役>] [--dry-run]
        python3 dispatch.py --init --repo OWNER/NAME --source <代表の clone> | --init-company [--local] [--repo <代表の clone>]

部署の回（--task・--ask・--land・--tree）は、設定の [[repos]] が無くても、代表の clone の場所（--repo のパスか打った場所）から
会社を決める（_department_repo）。[[repos]] は PR を開く回と、gh_user・copy_files を会社の形と別に決めたいときだけ要る。

--ask と --deliver（依頼と納品。会社の形の設計 4.5）の流れは orders.py が持つ。
--reorg と --desk（部署と窓口の属性の付け替え）の流れは reorg.py が持つ。
--retire（都度の部署の会話を止めて片付ける）の流れは retire.py が持つ。
"""

import argparse
import collections
import concurrent.futures
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import claudex  # noqa: E402
import config  # noqa: E402
import ghx  # noqa: E402
import gitx  # noqa: E402
import herdr  # noqa: E402
import installed  # noqa: E402
import jsonio  # noqa: E402
import calls  # noqa: E402
import landing  # noqa: E402
import move  # noqa: E402
import retire  # noqa: E402
import reorg  # noqa: E402
import limits  # noqa: E402
import tierx  # noqa: E402
import vscode  # noqa: E402
from nodes import accounts, assign, clean, cost, fresh, launch, provision, prs, report, role, sessions, sync, tools, tree, turn, wake  # noqa: E402
import orders  # noqa: E402
import starts  # noqa: E402

# Windows の既定の標準入出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

# 手元の herdr の API に要るメソッド（herdr の文書は、手元の版の API を api schema で確かめるよう求めている）。PR を開く道が使う物。
# pane.process_info はコマンドを打つ前にペインの前がシェルかを見る口（herdr pane process-info）
HERDR_METHODS = {"agent.prompt", "agent.get", "agent.wait", "pane.list", "pane.send_text", "pane.process_info", "workspace.list",
                 "workspace.close", "worktree.list", "worktree.create", "worktree.open", "worktree.remove"}
# 部署（--task・--ask・--sync）にだけ要るメソッド（ペインと作業場に名前と札を付ける・画面を読む・入力欄に残った字に Enter を足し、
# 止まった attach を Ctrl+Z で戻す）
TASK_HERDR_METHODS = {"pane.rename", "pane.report_metadata", "pane.read", "pane.send_keys", "workspace.rename"}
# --role を渡さず、会社の形に default_role も無いときの役（一度きりの作業をする役。持ち主 2026-10-16 に作業役から改名）
DEFAULT_ROLE = "作業"
# 部署の常設か都度か（属性 company.residency の値）。常設の部署は片付けで畳まない（会社の形の設計 4.10 の 1）
RESIDENT, PER_TASK = "resident", "per-task"


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


# タブ欄の行とサイドバーのフックが指す、このプラグインのスクリプト。プラグインを更新すると、入った場所（版ごとのフォルダ）が変わる
PLUGIN_SCRIPT = re.compile(r"""[^\s"'=]+[/\\]dispatch[/\\](?:limits|activity)\.py""")


def gone_plugin_paths(texts):
    """設定の文字列のなかの、このプラグインのスクリプトを指すパスのうち、もう無いもの（重なりは 1 つ）。"""
    found = []
    for text in texts:
        for m in PLUGIN_SCRIPT.findall(text):
            path = os.path.expanduser(m)
            if not os.path.isfile(path) and path not in found:
                found.append(path)
    return found


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
    その会話のアカウントのもので、ペインのものではないので、渡さずにシェルを起こし、シェルの設定が入れる値だけを読む。
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
    """環境変数を 1 つ入れて命令を打つ 1 行。Windows（の PowerShell）は `名前=値 命令` の形を打てないので、`$env:名前` に入れてから打つ
    形にする（入れた値はその PowerShell の窓に残る）。"""
    if os.name == "nt" if windows is None else windows:
        return f"$env:{name}='{value}'; {command}"
    return f"{name}={shlex.quote(str(value))} {command}"


class Ports:
    """外への口を 1 つに束ねる。試験は同じ名前の口を持つ偽物を渡す。書く口は herdr のモジュールそのもので、launch と turn だけが使う。"""

    def __init__(self, herdr_methods=None, shell_has=None, gh_ok=None, env=None, gh_env=None, herdr_integration=None,
                 login_config_dir=None, worktrees=None, task_flags=None, tier_check=None):
        self._herdr_methods = herdr_methods or herdr.methods
        self._task_flags = task_flags or claudex.missing_flags
        self._tier_check = tier_check or (lambda launchers: tierx.check(launchers, env=self.env))
        self._herdr_integration = herdr_integration or (lambda cdir: herdr.claude_integration(cdir, dict(self.env)))
        self._login_config_dir = login_config_dir or (lambda: _login_config_dir(self.env))
        self._account_env = None
        self._shell_has = shell_has or _shell_has
        self._gh_ok = gh_ok or ghx.can_read
        self.env = os.environ if env is None else env
        self._gh_env = gh_env
        self._gh_envs = {}
        self._worktrees = worktrees
        self.herdr = herdr
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
        """始める前の確かめ。(足りない物, 注記)。task は作業役（--task）の回で、/catchup と 2 ターン目の文を見ない代わりに、
        作業役に要る物（ペインの名前・会話の名前）を足りない物にする。ほかの回では、それらは注記にとどめる。"""
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
        except (herdr.HerdrError, OSError, ValueError) as e:
            problems.append(f"herdr に届かない: {e}")
        missing_flags = self._task_flags()
        if missing_flags:
            task_only.append(f"PATH の claude が {', '.join(missing_flags)} を持たない（部署（--task）は、名前を付けた裏の会話として、"
                             "その会話にだけ効く設定を渡して起こす。Claude Code を新しくする）")
        for repo in cfg.repos:
            if not task and not (repo.second_prompt or "").strip():
                problems.append(f"{repo.repo}: 2 ターン目の文が空（設定の [[repos]] の second_prompt_file に書いたファイルに、送る文を書く）")
        for a in cfg.accounts:
            if not self._shell_has(a.command):
                problems.append(f"アカウント {a.name} の起動のコマンド {a.command} がシェルで見つからない")
            cdir = config.effective_config_dir(a, self.account_env)
            try:
                state = self._herdr_integration(cdir)
            except (herdr.HerdrError, OSError) as e:
                state = f"読めない（{e}）"
            if not state.startswith("current"):
                notes.append(f"アカウント {a.name} に herdr の連携が入っていない: {state}（作業中の判定は無くても動く。"
                             f"herdr を立ち上げ直したときに会話を戻すのに要る。入れる: {env_command('CLAUDE_CONFIG_DIR', cdir, 'herdr integration install claude')}）")
            found = claudex.catchup_commands(cdir)
            if not task and len(found) != 1:
                problems.append(f"アカウント {a.name}（{cdir}）で /catchup の命令が 1 つに決まらない"
                                f"（commands/catchup.md を持つプラグイン: {', '.join(found) or '無し'}）")
            if a.limits and not (pathlib.Path(cfg.limits_dir) / f"{a.name}.json").is_file():
                notes.append(f"アカウント {a.name} の使用率の控えが無い（使用率が分からないものとして順の最後に置く）")
        # 信頼はアカウントをまたいで広げる（Ports.trust）ので、知らせるのはどのアカウントも信頼していない元の clone だけ
        for repo in cfg.repos:
            if not any(claudex.is_trusted(claudex.trust_file(a.config_dir, self.account_env), repo.source) for a in cfg.accounts):
                notes.append(f"どのアカウントも {repo.source} を信頼していない（枝ごとの作業場で毎回フォルダの信頼の確認が出る。"
                             f"どれか 1 つのアカウントで一度 {repo.source} に Claude Code を起こし、信頼すると、ほかのアカウントにも広げて出なくなる）")
        home = self.env.get("HOME") or os.path.expanduser("~")
        herdr_toml = pathlib.Path(self.env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")) / "herdr" / "config.toml"
        if not spaces_show_kind(herdr_toml):
            task_only.append(f"herdr の設定 {herdr_toml} の作業場の行（[ui.sidebar.spaces] の rows）に $kind が無い（部署の作業場の行に、"
                             "常設・毎回空／常設・持ち越し／都度の印が出ない）。rows のどこかに { token = \"$kind\" } を置く。"
                             f"[ui.sidebar.spaces] が無ければ、次を足して herdr server reload-config を打つ:\n{SPACES_ROWS}")
        files = [herdr_toml] + [pathlib.Path(config.effective_config_dir(a, self.account_env)) / "settings.json" for a in cfg.accounts]
        for path in gone_plugin_paths([s for f in files for s in setting_strings(f)]):
            notes.append(f"herdr の設定かフックが、もう無いスクリプトを指している: {path}（プラグインの更新で場所が変わった。"
                         "SKILL.md の任意の手順で行を出し直す）")
        for repo in cfg.repos:
            if gitx.origin_repo(repo.source) != repo.repo:
                problems.append(f"{repo.repo}: 元の clone {repo.source} が、このリポジトリの clone でない")
            elif not gitx.is_main_worktree(repo.source):
                problems.append(f"{repo.repo}: 元の clone {repo.source} が linked worktree で、本体の checkout でない"
                                "（git rev-parse の git-dir と git-common-dir が違う。source には本体の clone を書く）")
            else:
                try:
                    self.places(repo)
                except (herdr.HerdrError, OSError) as e:
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
                continue   # 部署の回は GitHub を読まない（本流の枝の名前は手元の origin/HEAD から。手元の bare リポジトリでも立つ）
            if not self._gh_ok(repo.repo, env=env):
                problems.append(f"gh が {repo.repo} を読めない。whose-turn が自分の番の PR を集められない"
                                "（gh auth status で、このリポジトリを読めるアカウントが有効かを確かめる）")
        return problems, notes

    def tiers(self, launchers):
        """要る道具の段の点検（tiers プラグイン）の結果。部品が無ければ tierx.TierError。"""
        return self._tier_check(launchers)

    def fetch_prs(self, repo):
        return prs.read(repo.repo, env=self.gh_env(repo))

    def list_sessions(self, config_dir, include_done=False):
        return claudex.sessions(config_dir, base_env=self.account_env, include_done=include_done)

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

    def unpushed(self, cwd):
        return gitx.unpushed(cwd)

    def pr_info(self, repo, number):
        return ghx.pr_info(repo.repo, number, env=self.gh_env(repo))

    def places(self, repo):
        """元の clone の worktree の並び（herdr アダプタの worktrees。元の clone 自身も linked=False で入る）。"""
        if self._worktrees:
            return self._worktrees(repo.source)
        return self.herdr.worktrees(repo.source)

    def stashed(self, cwd, branch):
        return gitx.stashed(cwd, branch)

    def head_sha(self, cwd):
        return gitx.head_sha(cwd)

    def pr_for_branch(self, repo, branch):
        """その枝の PR（{number, state, head_sha}・None）。読めなければ clean.Unknown（片付けは消さない側に倒す）。"""
        try:
            return ghx.pr_for_branch(repo.repo, branch, env=self.gh_env(repo))
        except ghx.GhError as e:
            raise clean.Unknown(str(e))

    def issue_info(self, repo, number):
        return ghx.issue_info(repo.repo, number, env=self.gh_env(repo))

    def issue_branches(self, repo, number):
        return ghx.issue_branches(repo.repo, number, env=self.gh_env(repo))

    def default_branch(self, repo):
        """本流の枝の名前。GitHub に問わず、代表の clone の手元の origin/HEAD（無ければ origin に問う）から取る（gitx.default_branch。
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
        """そのアカウントで送る catchup の命令の名前。始める前の確かめで 1 つに決まることを見てある。"""
        cdir = config.effective_config_dir(config.Account("", "", config_dir), self.account_env)
        found = claudex.catchup_commands(cdir)
        return found[0] if len(found) == 1 else None

    def open_pages(self, repo, numbers):
        """送り終えた PR の /catchup のページのうち書かれているものを、VS Code の窓にタブで開く（vscode.open_pages）。"""
        return vscode.open_pages([p for p in (vscode.page_path(repo.repo, n) for n in numbers) if p.is_file()], self.env)

    def trusted(self, account, folder):
        """そのアカウントがフォルダを信頼済みか（claudex.is_trusted）。"""
        return claudex.is_trusted(claudex.trust_file(account.get("config_dir"), self.account_env), folder)

    def caller(self, listed):
        """この命令を走らせている会話の (アカウントの名, 会話の名前)。Claude Code の中から走っていなければ (None, None)。"""
        return claudex.caller(listed, self.env.get("CLAUDE_CODE_SESSION_ID"), claudex.ancestors())

    def caller_pid(self, listed):
        """この命令を走らせている会話の処理（Claude Code）の番号。一覧に見えなければ None。"""
        return claudex.caller_pid(listed, self.env.get("CLAUDE_CODE_SESSION_ID"), claudex.ancestors())

    def stop_session(self, config_dir, job):
        """そのアカウントの裏の会話を止める（--move が起こし直す前に）。(止まったか, claude の言葉)。"""
        return claudex.stop_session(config_dir, job, base_env=self.account_env)

    def same_process(self, pid):
        """その番号の処理が、この命令を走らせている処理の親をたどった中に在るか（claudex.in_process）。"""
        return claudex.in_process(pid)

    def running_claude(self, pid):
        """その番号の処理が今動いている Claude Code か（--desk が、窓口の席に座っている会話が動いているかを見る）。"""
        return claudex.running_claude(pid)

    def trust(self, account, source, clone, others=()):
        """元の clone をこのアカウントかほかのアカウント（others。設定の accounts）のどれかが信頼済みなら、枝の場所（worktree）にも
        信頼の印を付ける（claudex.inherit_trust）。"""
        return claudex.inherit_trust(claudex.trust_file(account.get("config_dir"), self.account_env), source, clone,
                                     [claudex.trust_file(o.config_dir, self.account_env) for o in others])

    def activity(self, repo, number):
        """PR の動き（ghx.pr_activity）。自分のログイン名は 1 度だけ問い合わせる。"""
        env = self.gh_env(repo)
        if not hasattr(self, "_me"):
            self._me = ghx.login(env=env)
        return ghx.pr_activity(repo.repo, number, self._me, env=env)

    def load_sent(self, limits_dir):
        try:
            got = jsonio_load(pathlib.Path(limits_dir) / SENT_FILE)
        except (OSError, ValueError):
            return {}
        return got if isinstance(got, dict) else {}

    def save_sent(self, limits_dir, sent):
        path = pathlib.Path(limits_dir) / SENT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sent, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def state(self, config_dir, path):
        """そのフォルダの中の会話の状態を Claude Code 自身に問う（claude agents --json の status。idle・busy など）。
        会話が見えない・読めなければ None。"""
        try:
            items = self.list_sessions(config_dir)
        except claudex.ClaudeError:
            return None
        got = [i.get("status") or i.get("state") for i in items if fresh.inside(i.get("cwd") or "", path)]
        return got[0] if len(got) == 1 else None

    def now(self):
        return time.time()

    def cwd(self):
        """この命令を打った場所（部署の回と --init-company が、--repo の無いときに会社を決める所）。"""
        return os.getcwd()

    def common_of(self, cwd):
        """その場所の属するリポジトリの元の clone の根（git の共通の .git から）。git でなければ None。"""
        got = gitx.common_dir(cwd)
        return gitx.root_of(got) if got else None

    def attrs(self, path):
        """部署（worktree）の git の属性 company.<名前>。"""
        return gitx.worktree_attrs(path)


def jsonio_load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _key(repo, number):
    return f"{repo.repo}#{number}"


def _sent_record(v):
    """dispatch-sent.json の 1 件を {at, head} にする。前の版は時刻だけを書いた。"""
    if isinstance(v, (int, float)):
        return {"at": v, "head": None}
    return {"at": (v or {}).get("at"), "head": (v or {}).get("head")}


def _pane_at(h, path):
    """作業フォルダがちょうど path で、herdr が Claude Code の会話を見ているペインの ID（無ければ None）。読めなければ HerdrError。"""
    return next((p["pane_id"] for p in h.panes()
                 if p.get("agent") == "claude" and os.path.realpath(p.get("cwd") or "") == os.path.realpath(path)), None)


def _end_conversation(ports, path):
    """その場所の会話を終える（turn.close_session）。(closed か close_failed, 訳)。herdr に会話のペインが無ければ
    （会話が herdr の外の端末に居るなど）終えない。"""
    try:
        pane = _pane_at(ports.herdr, path)
    except herdr.HerdrError as e:
        return "close_failed", f"herdr のペインを読めない（{e}）"
    if not pane:
        return "close_failed", "その場所に herdr の会話のペインが無い（herdr の外の会話は終えない）"
    got = turn.close_session(pane, ports.herdr)
    return got, None if got == "closed" else f"ペイン {pane} の会話が /exit で終わらなかった"


def _sessions_in(cfg, ports, path):
    """その場所かその下を作業フォルダにする会話（全アカウント）。読めなければ ClaudeError。"""
    return [s for acc in cfg.accounts for s in ports.list_sessions(acc.config_dir)
            if s.get("cwd") and fresh.inside(s["cwd"], path)]


def _cost_note(est, limit_percent):
    if est is None:
        return ("1 件あたりの使用率をまだ測っていないので、選べるアカウントに 1 件ずつ順に配った"
                "（今回の /catchup の前後で測って覚え、次からはアカウントの残りに合わせて入れる）")
    parts = [f"{label} {round(est[w], 2)}%" for w, label in (("seven_day", "週"), ("five_hour", "5 時間")) if w in est]
    return (f"1 件あたりの使用率の見積もり（{est['runs']} 回の測りの中央値）: {'・'.join(parts)}。"
            f"各アカウントに、使用率が {limit_percent}% に届かない件数まで入れた")


def _branch_places(places):
    """worktree の並びから {枝: 場所のパス}（linked worktree だけ）。"""
    return {p["branch"]: p["path"] for p in places if p.get("linked") and p.get("branch") and not p.get("prunable")}


def _issue_item(repo, number, ports, notes):
    """--issue の 1 件を、prs の 1 件と同じ形（kind が issue）にする。枝は issue に結んだ枝（2 本以上なら最初の 1 本）。
    結んだ枝が見えなければ、issue を閉じる開いた PR の枝（枝から PR を作ると、GitHub は枝の結びつきを PR に置き換える）。
    どちらも無ければ head は None で、provision の前に GitHub に枝を作って結ぶ。"""
    info = ports.issue_info(repo, number)
    if info.get("state") not in (None, "OPEN"):
        return {"number": number, "kind": "issue", "title": info["title"], "head": None, "url": info.get("url"), "closed": True}
    branches = ports.issue_branches(repo, number)
    head = branches[0] if branches else None
    if branches[1:]:
        notes.append(f"issue #{number}: 結んだ枝がほかにも有る（使ったのは {head}）: {', '.join(branches[1:])}")
    for n in ([] if head else info["prs"]):
        pr = ports.pr_info(repo, n)
        if pr.get("state") == "OPEN" and not pr.get("fork"):
            head = pr["head"]
            notes.append(f"issue #{number}: 結んだ枝は見えないので、issue を閉じる PR #{n} の枝 {head} を使う")
            break
    return {"number": number, "kind": "issue", "title": info["title"], "head": head, "url": info.get("url")}


def main(argv=None, ports=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--dry-run", action="store_true", help="することの案までを決めて報告し、何も起こさない（--land では決まりと見立てだけを出し、push しない）")
    ap.add_argument("--pr", type=int, action="append", metavar="N",
                    help="自分の番の一覧を使わず、この番号の PR だけを開く（繰り返して複数）")
    ap.add_argument("--issue", type=int, metavar="N",
                    help="この issue に結んだ枝の場所を開き（無ければ枝を作って結ぶ）、/catchup N まで送って止める")
    ap.add_argument("--no-second", action="store_true", help="2 ターン目の文を送らず、/catchup だけで止める")
    ap.add_argument("--init", action="store_true", help="設定の下書きを書く（--repo と --source が要る。有れば上書きしない）")
    ap.add_argument("--source", help="--init と一緒に: そのリポジトリの代表の clone")
    ap.add_argument("--init-company", action="store_true",
                    help="会社の形（.claude/company.toml）の下書きを書く（--repo に代表の clone のパス。省けば今いる場所。有れば上書きしない）")
    ap.add_argument("--local", action="store_true",
                    help="--init-company と一緒に: リポジトリの中でなく、設定の置き場の companies/ に書く（commit しない側）")
    ap.add_argument("--check", action="store_true", help="始める前の確かめだけを走らせ、足りない物と直し方を出す")
    ap.add_argument("--clean", action="store_true", help="元の clone の worktree のうち消してよいものを並べる")
    ap.add_argument("--apply", action="store_true", help="--clean と一緒に: 並べたものを本当に消す")
    ap.add_argument("--task", metavar="名前", help="部署を 1 つ起こす。名前は会話・ペイン・作業場の名前になる（--branch と --brief が要る）")
    ap.add_argument("--branch", help="--task と一緒に: 部署の枝（在れば開き、無ければ作る）")
    ap.add_argument("--brief", help="--task と一緒に: 部署に最初に読ませる頼みのファイル")
    ap.add_argument("--base", help="--task と一緒に: 枝を新しく作るときの元にする origin の枝（省けば既定の枝）")
    ap.add_argument("--from-name", help="--task か --ask と一緒に: 呼んだ会話の名前（Claude Code の中から走らせれば自分で探す）")
    ap.add_argument("--from-account", help="--task か --ask と一緒に: 呼んだ会話のアカウントの名（同上）")
    ap.add_argument("--role", help=f"--task と一緒に: 部署の役（省けば会社の形の default_role、無ければ {DEFAULT_ROLE}）")
    ap.add_argument("--resident", action="store_true",
                    help="--task と一緒に: 常設の部署にする（--clean で畳まず、次の頼みを同じ部署で受ける。省けば都度の部署）")
    ap.add_argument("--tree", action="store_true", help="herdr に開いている会社ごとに、会社の情報と部署の様子を出す")
    ap.add_argument("--json", action="store_true", help="--tree と一緒に: JSON で出す")
    ap.add_argument("--sync", action="store_true", help="部署の属性から、herdr のペインの名前・表示名・札を付け直す")
    ap.add_argument("--ask", metavar="宛先", help="「会社/役」か部署の名前の部署か、会社の名前だけならその会社の窓口に頼む（--text か --brief。部署が無ければ --task と --branch で立てる）")
    ap.add_argument("--text", help="--ask か --note と一緒に: 頼みか足しの文（長い物は --brief のファイルで渡す）")
    ap.add_argument("--forward", action="store_true", help="--ask と一緒に: 部署か窓口の場所から、受けている頼みをこの頼みで回したとして"
                    "閉じる（回した先は台帳にだけ書き、頼み元の会話は起こさない。結果と問いは今までどおり --deliver で返す）")
    ap.add_argument("--take", metavar="受付", help="順番待ちの 1 件を、積んだ順を飛ばして取り出す。部署の場所から打てばその部署が今受け、"
                    "--ask <宛先>（と --task・--branch）を添えれば、受付番号と頼み元をそのままにほかの部署へ頼み直す（--text は元の本文の前に置く添え書き）")
    ap.add_argument("--move", metavar="部署か窓口", help="立っている部署か本社の窓口の会話を、ほかのアカウントで起こし直す"
                    "（前の会話を止めてから。--account で名指さなければ、使用率の順で空いている物）")
    ap.add_argument("--account", help="--move と一緒に: 移る先のアカウントの名（今のアカウントを名指せば、同じアカウントのまま"
                    "会社の形の今の起動の設定で起こし直す）")
    ap.add_argument("--if-limited", action="store_true",
                    help="--move と一緒に: 今のアカウントの使用率が上限に達しているときだけ移す（上限で止まったときのフックが付ける）")
    ap.add_argument("--if-changed", action="store_true",
                    help="--move と一緒に: 毎回空にする部署を、会社の形の model・effort が起こしたときと違うときだけ起こし直す"
                    "（今のアカウントに空きがあれば同じアカウントで。頼みを渡す前の待ち受けが付ける）")
    ap.add_argument("--withdraw", metavar="受付", help="順番待ちの 1 件を、渡さずに取り下げる（台帳に残す）")
    ap.add_argument("--nudge", metavar="部署", help="順番待ちが渡らずに止まった部署を動かす（会話が落ちていれば attach で戻し、"
                    "待ち受けが居ないか渡さずに待っていれば、手の空いた窓に 1 行打って番を回す。台帳に残す）")
    ap.add_argument("--first", metavar="受付", help="順番待ちの 1 件を、その順番待ちの先頭に回す（急ぐ物を先にする。台帳に残す）")
    ap.add_argument("--note", metavar="受付", help="受付の頼みに、変更・足し・取り下げを届ける（--text か --brief。部署が番の途中でも、"
                    "台帳の知らせで番の終わりに待ち受けが渡す。順番待ちの頼みなら、渡すときの 1 行に添える）")
    ap.add_argument("--call", nargs=2, metavar=("会社/役", "道具"),
                    help="役の機械窓口の道具を呼ぶ（会社の形の [[roles.tools]]。片づかなければ同じ役か回す役の AI の部署に回す）")
    ap.add_argument("--input", help="--call と一緒に: 道具への入力（JSON の字か @ファイル。省けば {}）")
    ap.add_argument("--start", metavar="受け持ち", help="会社の形の起こし方（[skills.start]）の有る受け持ちを今起こす（名前か「会社/名前」。"
                    "納品は起こし方の report_to に返る）")
    ap.add_argument("--due", action="store_true", help="herdr に開いている会社の、周期（[skills.start] の every）の来た受け持ちを全部起こす"
                    "（手元の OS の予定から刻む）")
    ap.add_argument("--deliver", metavar="要約のファイル", help="部署の場所から、要約を頼み元へ返す（項目が足りなければ送らない。- は標準入力）")
    ap.add_argument("--for", dest="for_ask", metavar="受付", help="--deliver と一緒に: --ask … --forward で回して閉じた頼み（回した元か"
                    "回した先の受付）の頼み元へ返す（今受けている頼みは閉じない）")
    ap.add_argument("--wait", metavar="訳", help="部署の場所から、今の頼みを人の答え待ちと印す（止まる前のフックが納品を促さない。"
                    "人がその会話に打つか、納品すると外れる）")
    ap.add_argument("--rest", action="store_true", help="部署か窓口の場所から、今は会話を空にしてよい区切りと印す（この番の終わりに、"
                    "入力欄が空なら機械が窓に /clear を打つ。人がその会話に打つと外れる）")
    ap.add_argument("--done", action="store_true", help="都度の部署の場所から、納品して本流に入れ終えたので片付けてよいと印す（この番の"
                    "終わりに、機械が会話を止めて部屋を --clean と同じ決まりで片付ける。人がその会話に打つと外れる）")
    ap.add_argument("--retire", metavar="部署", help="都度の部署の会話を止めてから、部屋を --clean と同じ決まりで片付ける（--done の"
                    "番の終わりに機械が打つ。段取りが残った部屋を止めると決めたときも打つ）")
    ap.add_argument("--land", metavar="部署", help="部署の成果を、会社の形の [land] の決まりで本流に入れる（関門を待ち、緑なら早送り）")
    ap.add_argument("--keep-removal", action="store_true",
                    help="--land と一緒に: 部署が本流を知った後にほかの部署が入れた行を、この枝が消していても入れる（わざと消すとき）")
    ap.add_argument("--reorg", action="store_true",
                    help="今いる部署の名前・役・常設か都度か・頼み元を付け替え、herdr の表示を付け直す（--name・--role・--resident か --per-task・--boss）")
    ap.add_argument("--name", help="--reorg と一緒に: 部署の新しい名前（前の名前は覚え、--land・--ask は前の名前でも引く）")
    ap.add_argument("--per-task", action="store_true", help="--reorg と一緒に: 都度の部署にする（常設をやめる）")
    ap.add_argument("--boss", help="--reorg と一緒に: 新しい頼み元（納品を返す会話）の名前")
    ap.add_argument("--boss-account", help="--reorg と一緒に: 新しい頼み元のアカウントの名（省けば名前だけで引く）")
    ap.add_argument("--desk", metavar="名前", nargs="?", const="",
                    help="本社で持ち主と話す今の会話を窓口として名付ける（役は --role、会社の形の desk_role、今の役、窓口 の順。"
                         "名前を省けば今の名前か役の名前）。herdr の表示も付け直す")
    a = ap.parse_args(argv)
    ports = ports or Ports()
    if a.init:
        return _init(a, ports)
    if a.input is not None and a.call is None:
        print("止めた: --input は --call と一緒にだけ使う")
        return 2
    if a.call is not None:
        return calls.call(a, ports, os.getcwd(), _task)
    if a.start is not None or a.due:
        if a.start is not None and a.due:
            print("止めた: --start と --due は一緒に使えない（--start は 1 つを今、--due は周期の来た物を全部）")
            return 2
        return starts.start_now(a, ports, os.getcwd(), _task) if a.start is not None else starts.due_all(a, ports, _task)
    if a.move is not None:
        return move.move(a, ports, os.getcwd(), _task)
    if (a.account or a.if_limited or a.if_changed) and a.move is None:
        print("止めた: --account・--if-limited・--if-changed は --move と一緒にだけ使う")
        return 2
    if a.forward and (a.ask is None or a.take is not None):
        print("止めた: --forward は --ask と一緒にだけ使う（--take --ask は受付番号と頼み元をそのまま回すので要らない）")
        return 2
    if a.for_ask is not None and a.deliver is None:
        print("止めた: --for は --deliver と一緒にだけ使う")
        return 2
    if a.take is not None:
        return orders.take(a, ports, os.getcwd(), _task)
    if a.withdraw is not None:
        return orders.withdraw(a, ports, os.getcwd())
    if a.first is not None:
        return orders.first(a, ports, os.getcwd())
    if a.nudge is not None:
        return orders.nudge(a, ports, os.getcwd())
    if a.note is not None:
        return orders.note(a, ports, os.getcwd())
    if a.ask is not None:
        return orders.ask(a, ports, os.getcwd(), _task)
    if a.deliver is not None:
        return orders.deliver_summary(a, ports, os.getcwd())
    if a.wait is not None:
        return orders.wait_for_input(a, ports, os.getcwd())
    if a.rest:
        return orders.rest_here(a, ports, os.getcwd())
    if a.done:
        return orders.finish_here(a, ports, os.getcwd())
    if a.retire is not None:
        return retire.retire(a, ports, os.getcwd(), _department_rows, DEPT_REASONS)
    if a.text is not None:
        print("止めた: --text は --ask と一緒にだけ使う")
        return 2
    if a.reorg or a.desk is not None:
        if a.reorg and a.desk is not None:
            print("止めた: --reorg と --desk は一緒に使えない（部署は --reorg、本社の窓口は --desk）")
            return 2
        return reorg.reorg(a, ports, ports.cwd()) if a.reorg else reorg.desk(a, ports, ports.cwd())
    if a.keep_removal and a.land is None:
        print("止めた: --keep-removal は --land と一緒にだけ使う")
        return 2
    reorg_args = [n for n, v in (("--name", a.name), ("--per-task", a.per_task), ("--boss", a.boss),
                                 ("--boss-account", a.boss_account)) if v]
    if reorg_args:
        print(f"止めた: {', '.join(reorg_args)} は --reorg と一緒にだけ使う")
        return 2
    if a.tree or a.sync or a.json:
        return _company(a, ports)

    if a.local and not a.init_company:
        print("止めた: --local は --init-company と一緒にだけ使う")
        return 2
    if a.init_company:
        return _init_company(a, ports, ports.cwd())
    # 部署の回（--task・--land）は、[[repos]] が無くても、代表の clone の場所から会社を決める（_department_repo）
    # --check は、[[repos]] が無ければ部署の回の前提だけを確かめる（_check）
    # --clean も部署の回と同じに決める（設定が無くても、--repo のパスか今いる場所の代表の clone の部署を片付ける）
    department = a.task is not None or a.land is not None or a.clean
    try:
        cfg = config.load(a.config, os.environ, missing_ok=department or a.check)
        repo = (_department_repo(cfg, a.repo, ports, ports.cwd()) if department else
                None if a.check and not cfg.repos else config.pick_repo(cfg, a.repo))
    except config.ConfigError as e:
        print(f"止めた: {e}")
        return 2
    if a.apply and not a.clean:
        print("止めた: --apply は --clean と一緒にだけ使う")
        return 2
    if a.issue is not None and a.pr:
        print("止めた: --issue と --pr は一緒に使えない（1 回に 1 つの入口）")
        return 2
    task_args = [n for n, v in (("--branch", a.branch), ("--brief", a.brief), ("--base", a.base), ("--from-name", a.from_name),
                                ("--from-account", a.from_account), ("--role", a.role), ("--resident", a.resident)) if v]
    if a.task is None and task_args:
        print(f"止めた: {', '.join(task_args)} は --task と一緒にだけ使う")
        return 2
    if a.land is not None:
        if a.task is not None or a.pr or a.issue is not None or a.clean or a.check or a.no_second:
            print("止めた: --land はほかの入口（--task・--pr・--issue・--clean・--check・--no-second）と一緒に使えない")
            return 2
        return landing.main(cfg, repo, a.land, ports, _department_rows, DEPT_REASONS, a.config, dry_run=a.dry_run,
                            keep_removal=a.keep_removal,
                            after=lambda rules, source, attrs: calls.fire(rules, source, ports, a, _task, attrs))
    if a.task is not None:
        if a.pr or a.issue is not None or a.clean or a.check or a.no_second:
            print("止めた: --task は --pr・--issue・--clean・--check・--no-second と一緒に使えない（1 回に 1 つの入口）")
            return 2
        if not (a.task.strip() and a.branch and a.brief):
            print("止めた: --task には、名前と --branch <枝> と --brief <頼みのファイル> が要る")
            return 2
        return _task(cfg, repo, a, ports)
    if a.clean:
        return _clean(cfg, repo, a.apply, ports)
    if a.check:
        return _check(cfg, ports)
    problems, notes = ports.preflight(cfg)
    notes = list(cfg.notes) + notes
    if problems:
        print("止めた（始める前の確かめで足りない物）:")
        print("\n".join(f"- {p}" for p in problems))
        return 2

    listing = a.issue is None and not a.pr   # 一覧で回す（送り直しと片付けもする）
    try:
        if a.issue is not None:
            my_prs = [_issue_item(repo, a.issue, ports, notes)]
        else:
            my_prs = [ports.pr_info(repo, n) for n in a.pr] if a.pr else ports.fetch_prs(repo)
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
        found = ports.places(repo)
    except (prs.PrsError, claudex.ClaudeError, ghx.GhError, herdr.HerdrError) as e:
        print(f"止めた: {e}")
        return 1
    if my_prs and my_prs[0].get("closed"):
        # 閉じた issue には枝を作らない（作る前に止める）
        print("\n".join(report.lines([_held_row(my_prs[0], "issue_closed", {}, kind="issue")], {}, notes)))
        return 0
    places = _branch_places(found)
    sess = sessions.collect(listed, ports.branch, ports.origin)
    # 自分が作者でレビュアーの付いていない PR は、開くが /catchup だけ送る（2 ターン目の文はレビューの進め方なので送らない）
    held, acts, catchup_only = [], {}, set()
    for p in my_prs:
        if p.get("role") == "implementer" and p.get("kind", "pr") == "pr":
            try:
                acts[p["number"]] = ports.activity(repo, p["number"])
            except ghx.GhError as e:
                notes.append(f"#{p['number']}: {e}（レビュアーの有無が分からないので 2 ターン目まで送る）")
            if p["number"] in acts and fresh.own_unreviewed(p, acts[p["number"]]):
                catchup_only.add(p["number"])
    # 枝の場所の中で会話が開いている PR: 自分以外の動きが前に送った時より後に有れば、会話とペインを畳んで新しく立て直す
    sent = ports.load_sent(cfg.limits_dir)
    refresh, verdicts = {}, {}
    quiet = set()
    keys = sessions.open_keys(sess)
    for p in (my_prs if listing else []):
        path = places.get(p["head"])
        inside = [x for x in sess if x["cwd"] and path and fresh.inside(x["cwd"], path)]
        if not inside:
            # 会話が開いていない PR: 前に送った後に動きが無ければ、開き直さない（返事待ちの PR を、持ち主が会話を閉じただけで
            # もう一度レビューしない。持ち主 2026-10-15）。--pr で名指したときはここを通らない
            sent_rec = sent.get(_key(repo, p["number"]))
            if sent_rec is None or (repo.repo, p["head"]) in keys:
                continue
            try:
                act = acts.get(p["number"]) or ports.activity(repo, p["number"])
            except ghx.GhError as e:
                notes.append(f"#{p['number']}: {e}（前に送った後の動きが分からないので開く）")
                continue
            if fresh.quiet_since_sent(_sent_record(sent_rec), act):
                quiet.add(p["number"])
            continue
        try:
            act = acts.get(p["number"]) or ports.activity(repo, p["number"])
        except ghx.GhError as e:
            notes.append(f"#{p['number']}: {e}（送り直さない）")
            continue
        rec = _sent_record(sent.get(_key(repo, p["number"])))
        # HEAD が前に送った時の head のままなら、remote に見えない commit は作者の force-push で消えた物（手元で積んだ物でない）
        local = (ports.stashed(path, p["head"]) if rec["head"] and ports.head_sha(path) == rec["head"]
                 else ports.unpushed(path))
        v = "busy" if len(inside) > 1 else fresh.decide(inside[0], act, rec["at"], ports.is_clean(path), local,
                                                        sent_head=rec["head"])
        if v == "refresh":
            refresh[p["number"]] = inside[0]
        else:
            verdicts[p["number"]] = v
    held += [_held_row(p, "no_news", places) for p in my_prs if p["number"] in quiet]
    my_prs = [p for p in my_prs if p["number"] not in quiet]
    staying = [x for x in sess if not any(x is r for r in refresh.values())]
    metered = [x.name for x in cfg.accounts if x.limits]
    if not a.dry_run:
        ports.refresh_limits(cfg, metered)
    before = ports.read_limits(cfg.limits_dir, metered)
    ranked = accounts.rank(cfg.accounts, before, cfg.limit_percent, ports.now(), accounts.count_running(listed),
                           cfg.reset_soon_hours)
    est = cost.estimate(ports.load_cost(cfg.limits_dir))
    the_plan = assign.plan(repo, my_prs, sessions.open_keys(staying), {s["cwd"] for s in staying if s["cwd"]}, ranked,
                           cfg.limit_percent, est, places)
    if any(r["outcome"] in ("assigned", "no_account") for r in the_plan):
        notes.append(_cost_note(est, cfg.limit_percent))

    results = {n: v for n, v in verdicts.items()}
    assigned = [r for r in the_plan if r["outcome"] == "assigned"]
    # fork の PR（head が別のリポジトリ）は作業場を作らない。whose-turn の一覧は fork かを持たないので、開く PR だけ問う
    for r in assigned:
        if r["kind"] == "pr":
            r["sent_head"] = _sent_record(sent.get(_key(repo, r["number"])))["head"]
        if r["kind"] == "pr" and not a.pr:
            try:
                r["fork"] = bool(ports.pr_info(repo, r["number"]).get("fork"))
            except ghx.GhError as e:
                notes.append(f"#{r['number']}: fork の PR かを読めない（{e}）")
    if a.dry_run:
        for r in assigned:
            results[r["number"]] = "refresh" if r["number"] in refresh else provision.would(r, found)
            if r["kind"] == "issue" and not r["head"]:
                notes.append(f"issue #{r['number']}: 結んだ枝が無いので、既定の枝から枝を作って issue に結ぶ（gh issue develop）")
    else:
        ready = []
        for r in assigned:
            if r["number"] in refresh:
                # 古い会話を終え、その場所の作業場を畳む（checkout は残し、下の provision が同じ場所を開き直す）
                closed, why = _end_conversation(ports, r["path"])
                if closed != "closed":
                    results[r["number"]] = "close_failed"
                    notes.append(f"#{r['number']}: 送り直す前に古い会話を終えられなかった（{why}）")
                    continue
                rel = clean.release(repo.source, r["path"], ports.herdr)
                if rel["status"] == "close_failed":
                    results[r["number"]] = "close_failed"
                    notes.append(f"#{r['number']}: 古い作業場を閉じられなかった（{rel['detail']}）")
                    continue
            if r["kind"] == "issue" and not r["head"]:
                try:
                    linked = provision.link_branch(repo, r["number"], ports.default_branch(repo), ports.gh, ports.gh_env(repo))
                except (ghx.GhError, gitx.GitError) as e:
                    linked, why = [], str(e)
                else:
                    why = "結んだ後の読み戻しで、issue に結んだ枝が見えない"
                if not linked:
                    results[r["number"]] = "provision_failed"
                    notes.append(f"issue #{r['number']}: 枝を結べなかった（{why}）")
                    continue
                r["head"] = linked[0]
            prov = provision.prepare(r, repo, ports.herdr, ports.git)
            name = _name(r)
            if prov["detail"]:
                notes.append(f"{name}: {prov['detail']}")
            if prov["status"] != "ready":
                results[r["number"]] = prov["status"]
                continue
            r["path"] = prov["path"]
            try:
                trusted = ports.trust(r["account"], repo.source, prov["path"], cfg.accounts)
            except OSError as e:
                trusted = f"書けない（{e}）"
            if trusted not in ("inherited", "already"):
                notes.append(f"{name}: どのアカウントも元の clone を信頼していないので、"
                             "Claude Code がフォルダの信頼の確認を出す" if trusted == "source_untrusted" else
                             f"{name}: 信頼の印を付けられない（{trusted}）。Claude Code がフォルダの信頼の確認を出す")
            got = launch.start(r, prov["pane"], ports.herdr)
            if got["status"] == "ready":
                ready.append((r, prov["pane"]))
            else:
                results[r["number"]] = got["status"]
                notes.append(f"{name}: {got['detail']}")
        # issue から始めたものは 1 ターン目の /catchup まで（2 ターン目の文は PR のレビューの文なので送らない）
        second = {r["number"]: None if (a.no_second or r["kind"] == "issue" or r["number"] in catchup_only)
                  else repo.second_prompt for r, _ in ready}
        notes.extend(f"#{r['number']}: 自分が作者でレビュアーの付いていない PR なので、/catchup だけ送った"
                     for r, _ in ready if r["number"] in catchup_only and not a.no_second)
        # 送った時刻は 1 ターン目を送る直前（その後の動きを「新しい返事」と見る）、head はその時の場所の head（force-push の見分け）
        stamp = {r["number"]: {"at": ports.now(), "head": ports.head_sha(r["path"])} for r, _ in ready}
        if ready:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(ready)) as pool:
                futures = {r["number"]: pool.submit(turn.catchup_then_second, r["number"], pane, second[r["number"]], ports.herdr,
                                                    catchup=ports.catchup_command(r["account"].get("config_dir")),
                                                    state=(lambda r=r: ports.state(r["account"].get("config_dir"), r["path"])))
                           for r, pane in ready}
                results.update({n: f.result() for n, f in futures.items()})
            for r, _ in ready:
                if results.get(r["number"]) == "sent" and r["kind"] == "pr":
                    sent[_key(repo, r["number"])] = stamp[r["number"]]
                    if r["number"] in refresh:
                        results[r["number"]] = "refreshed"
            ports.save_sent(cfg.limits_dir, sent)
            # 1 件あたりの使用率は、/catchup の終わりまで待った件だけで測る（待たずに送った件は、測る時にまだ使っていない）
            counts = collections.Counter(r["account"]["name"] for r, _ in ready if second[r["number"]] is not None)
            measured = [n for n in counts if n in metered]
            if measured:
                ports.refresh_limits(cfg, measured)
                ports.save_cost(cfg.limits_dir, cost.samples(before, ports.read_limits(cfg.limits_dir, measured), counts))
            # 起こした会話には /catchup のページを開かせていない（launch の ATTENTION_CATCHUP_OPEN=0）。送り終えた件だけ、ここで 1 回開く
            opened = ports.open_pages(repo, [r["number"] for r, _ in ready
                                             if r["kind"] == "pr" and results.get(r["number"]) in ("sent", "refreshed")])
            if opened:
                notes.append(opened)

    if listing:
        notes += _tidy(cfg, repo, ports, a.dry_run, found)
    print("\n".join(report.lines(the_plan + held, results, notes)))
    return 0


def _department_repo(cfg, name, ports, cwd):
    """部署の回（--task・--land）の repo。--repo が設定の [[repos]] の名前か source ならそれ。--repo がフォルダなら、その場所の
    git の共通の .git から代表の clone を決める（config.repo_at。[[repos]] に無ければ最小の repo）。--repo が無ければ今いる場所から
    同じに決め、今いる場所が git でなければ設定の最初の repo。決められなければ config.ConfigError。"""
    if name is not None:
        try:
            return config.pick_repo(cfg, name)
        except config.ConfigError:
            pass
        place = os.path.expanduser(name)
        if not os.path.isdir(place):
            raise config.ConfigError(f"--repo の {name} が、設定の [[repos]] の名前でも、在るフォルダでもない"
                                     "（代表の clone のパスを渡すか、その clone の中から打つ）")
    else:
        place = cwd
    root = ports.common_of(place)
    if root:
        return config.repo_at(cfg, root, ports.origin)
    if name is None and cfg.repos:
        return cfg.repos[0]
    raise config.ConfigError(f"{place} が git のリポジトリでないので、会社（代表の clone）を決められない"
                             "（--repo に代表の clone のパスを渡すか、その clone の中から打つ）")


def _name(row):
    return f"{'issue ' if row.get('kind') == 'issue' else ''}#{row['number']}"


def _held_row(p, outcome, places, kind="pr"):
    return {"number": p["number"], "kind": kind, "title": p["title"], "head": p["head"], "url": p.get("url"), "fork": False,
            "outcome": outcome, "account": None, "path": places.get(p["head"])}


def _where(r):
    return f"#{r['number']} {r['branch']}" if r["number"] is not None else f"- {r['branch'] or '（枝無し）'}"


def _changed(repo):
    return lambda path: clean.changed_copies(path, config.copy_root(repo), repo.copy_files)


def _tidy(cfg, repo, ports, dry_run, found):
    """閉じた PR（MERGED・CLOSED）の枝の場所を片付ける（一覧で回すときだけ）。元の clone の linked worktree だけを見る（clean.candidates）。
    会話が 1 つだけ開いていて、手すきで手元の作業も無ければ、会話を終え、会話の一覧を取り直して居ないことを確かめてから消す。
    作業中・会話が 2 つ以上・手元の作業の有る場所は残して名指す。返すのは報告の頭に置く行。読めない・終えられない物は、その場所の
    行にして続ける。"""
    try:
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
    except claudex.ClaudeError as e:
        return [f"片付けを飛ばした（開いている会話を読めない: {e}）"]
    sess = sessions.collect(listed, ports.branch, ports.origin)
    changed = _changed(repo)
    rows = clean.candidates(found, lambda b: ports.pr_for_branch(repo, b), {x["cwd"] for x in sess if x["cwd"]},
                            ports.is_clean, ports.stashed, ports.head_sha, source=repo.source, changed=changed)
    out = []
    for r in rows:
        finished = r["state"] in clean.FINISHED
        if r["reason"] == "session" and finished:
            mine = [x for x in sess if x["cwd"] and fresh.inside(x["cwd"], r["path"])]
            files = changed(r["path"])
            local = (not ports.is_clean(r["path"]) or ports.stashed(r["path"], r["branch"])
                     or ports.head_sha(r["path"]) != r["pr_head"] or files)
            if len(mine) > 1:
                out.append(f"{_where(r)}: 閉じた PR だが、会話が {len(mine)} つ開いているので残した")
                continue
            if any(x["status"] != "idle" for x in mine) or local:
                out.append(f"{_where(r)}: 閉じた PR だが、会話が作業中か手元の作業が有るので残した")
                continue
            if dry_run:
                out.append(f"{_where(r)}: 閉じた PR なので、会話を終えて片付ける")
                continue
            closed, why = _end_conversation(ports, r["path"])
            if closed != "closed":
                out.append(f"{_where(r)}: 閉じた PR の会話を終えられなかったので残した（{why}）")
                continue
            try:
                left = _sessions_in(cfg, ports, r["path"])
            except claudex.ClaudeError as e:
                out.append(f"{_where(r)}: 会話を終えた後の一覧を読めないので残した（{e}）")
                continue
            if left:
                out.append(f"{_where(r)}: 会話を終えた後も、その場所に会話が見えるので残した")
                continue
            r = {**r, "removable": True, "reason": None}
        if finished and r["reason"] in ("dirty", "unpushed"):
            out.append(f"{_where(r)}: 閉じた PR だが、手元の作業が有るので残した")
            continue
        if finished and r["reason"] == "local_files":
            out.append(f"{_where(r)}: 閉じた PR だが、写したファイルが写し元と違うので残した: {', '.join(r['files'])}")
            continue
        if not r["removable"]:
            continue
        if dry_run:
            out.append(f"{_where(r)}: 閉じた PR なので片付ける")
            continue
        got = clean.remove(r, repo.source, provision.label(repo, r["branch"]), ports.herdr, ports.git)
        out.append(f"{_where(r)}: " + ("片付けた" if got["removed"] and got["branch_deleted"] else
                                       f"片付けた（{got['detail']}）" if got["removed"] else f"片付けられなかった（{got['detail']}）"))
    return out


def _contact(caller, account):
    """作業役の最初の文の後ろに書き足す、連絡の道の 1 文。呼んだ会話と同じアカウントで、その名前が分かれば SendMessage。
    アカウントが違うと SendMessage が届かない（2026-10-16 に持ち主の手元で、別のアカウントの会話どうしで両方向とも
    「No agent named … is reachable」になり、各会話の一覧にも同じアカウントの会話しか出なかった）ので、画面に書いて止まらせる。"""
    if caller["name"] and caller["account"] == account:
        return f"報告は区切りごとに SendMessage で「{caller['name']}」へ送る（呼んだ会話と同じアカウントなので届く）。"
    if not caller["account"]:
        why = "呼んだ会話が分からず、SendMessage の宛先を決められない"
    elif caller["account"] == account:
        why = "呼んだ会話の名前が分からず、SendMessage の宛先を決められない"
    else:
        why = f"呼んだ会話{'「' + caller['name'] + '」' if caller['name'] else ''}とはアカウントが違い、SendMessage が届かない"
    return f"報告は区切りごとにこの画面に短く書いて止まる（{why}。呼んだ側が herdr でこの画面を読む）。"


def _brief_text(brief, caller, account, tail=None):
    """作業役に最初に送る文（1 行）。tail は連絡の道の文の代わり（--ask は納品の命令での返し方）。
    「その通りに」とは書かない（頼みに異論を返してよいかは会社の形の役の本文が決める。頼みの文がそれを打ち消さないように）。"""
    return f"作業の頼みです。{brief} を読んで進めてください。" + (tail or _contact(caller, account))


def _task(cfg, repo, a, ports, extra_attrs=None, tail=None, refreshed=False):
    """部署を 1 つ立てる（会社の形の設計 9.1）。場所は PR と同じ決まり（provision.prepare_task。herdr が元の clone の子の作業場として
    worktree を作る）、アカウントは同じ割り振り（accounts.rank と assign.plan。1 件なので、使用率が上限に届かないアカウントのうち
    順の頭）。部署の属性を git に書き（provision.mark）、その作業場のペインで Claude Code の裏の会話を起こし（launch.start_background。
    裏の会話が自分で worktree を作らないよう、templates/department-settings.json で worktree.bgIsolation を none にする）、会話の一覧から
    会話の id を読んで属性に足し、同じペインで attach する（launch.attach）。表示名と札は --sync と同じ組み立て（sync）。

    置き場と枝を下回りが決めるために、Claude Code に worktree を作らせず、先に作った worktree の中で起こす。WorktreeCreate のフックでも
    置き場と枝は決められた（2026-10-16 に試した）が、フックはその会話の中の全部の worktree（サブエージェントの isolation など）を
    置き換え、フックの作った worktree は claude rm が消さずに断る。

    会社の形は、読む前に origin の既定の枝を取り直してから読む（provision.refresh_shape。--dry-run では取り直さない）。refreshed は、
    呼んだ側（--ask）がもう取り直したこと。"""
    brief = os.path.abspath(os.path.expanduser(a.brief))
    if not os.path.isfile(brief):
        print(f"止めた: 頼みのファイルが無い: {brief}")
        return 2
    # 役の項目（会社の形の [[roles]]）と gh のアカウント。会社の形は --tree と同じ読み方（会社の形の設計 4.7・4.8）
    cfg_path = config.path_of(a.config, os.environ)
    fetched = None if a.dry_run or refreshed else provision.refresh_shape(repo.source, ports.git)
    info = tree.read_info(repo.source, os.path.dirname(cfg_path))
    shape = role.load(info["path"], info["text"])
    role_name, default_note = (a.role, None) if a.role else role.default(shape, DEFAULT_ROLE)
    the_role, why = role.pick(shape, role_name, a.role is not None)
    if why:
        print(f"止めた: {why}")
        return 2
    # 部署の名前と同じ name の受け持ち（[[skills]]）に model・effort が有れば、役の値より先に効く。effort の inherit は、呼んだ会話の今の effort
    duty = next((x for x in info["skills"] if x["name"] == a.task), None)
    # 役の resident = true は --resident と同じ。ただし受け持ちが standing = false（頼まれたときだけ立てる）なら都度の部署で立てる
    resident = a.resident or (bool(the_role and the_role["resident"]) and not (duty and duty.get("standing") is False))
    model, effort, flags_note = role.launch_flags(the_role, ports.env, duty)
    gh_user, gh_note = role.gh_user(repo.gh_user, shape)
    repo = repo._replace(gh_user=gh_user)
    # 始める前の確かめは、部署を立てるこの repo だけを見る（設定の [[repos]] に無い repo も、ほかの repo の足りない物で止めない）
    cfg = cfg._replace(repos=(repo,))
    names = [x.name for x in cfg.accounts]
    if a.from_account and a.from_account not in names:
        print(f"止めた: --from-account の {a.from_account} が設定の accounts に無い（{', '.join(names)}）")
        return 2
    problems, notes = ports.preflight(cfg, task=True)
    notes = (list(cfg.notes) + [n for n in [fetched] if n] + info["notes"] + shape["problems"]
             + [p for p in info["problems"] if p not in shape["problems"]]
             + [n for n in [gh_note, default_note, flags_note] if n]
             + role.warnings(the_role) + notes)
    if problems:
        print("止めた（始める前の確かめで足りない物）:")
        print("\n".join(f"- {p}" for p in problems))
        return 2
    try:
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
        found = ports.places(repo)
    except (claudex.ClaudeError, herdr.HerdrError) as e:
        print(f"止めた: {e}")
        return 1
    # 同じ名前の会話。止めた裏の会話（--move が起こし直す前の会話）は数えない。SendMessage の宛先はアカウントの中で、dispatch の
    # 宛て方（「会社/名前」）は会社の中で 1 つに決まれば足りる。同じ会社の中の重なりは止め、ほかの会社の重なりは、そのアカウントを
    # 避けて振る（部署の名前に会社の名前を付けない決まりのまま、会社ごとに同じ名前の受け持ちを並べて立てるため）
    alive = [(acc, s) for acc, items in listed.items() for s in items
             if s.get("name") == a.task and s.get("state") not in ("done", "failed", "stopped")]
    here = [acc for acc, s in alive if s.get("cwd") and any(fresh.inside(s["cwd"], p["path"]) for p in found if p.get("path"))]
    if here:
        print(f"止めた: 「{a.task}」という名前の会話がこの会社にもう開いている（アカウント {', '.join(sorted(set(here)))}）。"
              "宛先が 1 つに決まらないので、別の名前で頼む")
        return 1
    taken = {acc for acc, _ in alive}
    found_account, found_name = ports.caller(listed)
    caller = {"account": a.from_account or found_account, "name": a.from_name or found_name}
    if not caller["account"]:
        notes.append("呼んだ会話が分からない（Claude Code の外から走らせたか、その会話が一覧に見えない）ので、作業役には画面に報告を"
                     "書かせる。SendMessage で受けたいなら --from-name と --from-account で渡す")
    sess = sessions.collect(listed, ports.branch, ports.origin)
    metered = [x.name for x in cfg.accounts if x.limits]
    if not a.dry_run:
        ports.refresh_limits(cfg, metered)
    # --move はアカウントを名指して起こし直す（only_account）。ほかの回は、使用率の順の頭
    pool = [x for x in cfg.accounts if x.name == getattr(a, "only_account", None)] or cfg.accounts
    if taken:
        free = [x for x in pool if x.name not in taken]
        if not free:
            print(f"止めた: 「{a.task}」という名前の会話がほかの会社でもう開いていて（アカウント {', '.join(sorted(taken))}）、"
                  "振れるアカウントがほかに無い。同じアカウントでは SendMessage の宛先が 1 つに決まらないので、"
                  "設定の accounts にアカウントを足すか、その会話が終わってから頼む")
            return 1
        notes.append(f"「{a.task}」という名前の会話がほかの会社でアカウント {', '.join(sorted(taken))} に開いているので、"
                     "そのアカウントを避けて振る")
        pool = free
    ranked = accounts.rank(pool, ports.read_limits(cfg.limits_dir, metered), cfg.limit_percent, ports.now(),
                           accounts.count_running(listed), cfg.reset_soon_hours)
    row = assign.plan(repo, [{"number": None, "kind": "task", "title": a.task, "head": a.branch}], sessions.open_keys(sess),
                      {s["cwd"] for s in sess if s["cwd"]}, ranked, cfg.limit_percent, None, _branch_places(found))[0]
    row["label"] = a.task
    if row["outcome"] != "assigned":
        why = {"already_open": "その枝の場所で会話がもう開いている（会話を閉じるのは持ち主だけ）",
               "no_account": "使用率が上限に届かないアカウントが無い"}[row["outcome"]]
        print("\n".join(notes + [f"部署 {a.task}  {a.branch}  -  {row['outcome']}（{why}）"]))
        return 0
    account = row["account"]["name"]
    many = len(cfg.accounts) > 1
    pane_label = sync.label(a.task, account, many)
    # 部署の属性（正本）。頼み元は呼んだ会話。分からない物は書かない
    attrs = {"role": role_name, "residency": RESIDENT if resident else PER_TASK, "fresh": role.FRESH if the_role and the_role["fresh"] else None,
             "account": account,
             "name": a.task, "boss": caller["name"], "boss-account": caller["account"], "gh-user": gh_user,
             # 既定の置き場でない dispatch の設定を使ったときだけ、その場所（役を足すフックが、設定の置き場の会社の形を探すため）
             "config": None if cfg_path == config.path_of(None, {}) else cfg_path,
             # 起こしたときの会社の形の model・effort（毎回空にする部署の待ち受けが、今の値と比べて起こし直すかを決める）
             wake.LAUNCHED: role.launch_key(the_role, duty), **{k: v for k, v in (extra_attrs or {}).items() if v}}
    route = ("納品の命令で頼み元の窓へ" if tail else f"SendMessage で「{caller['name']}」へ"
             if caller["name"] and caller["account"] == account else "区切りで画面に書いて止まる")
    if a.dry_run:
        print("\n".join(notes + [
            f"部署 {a.task}  {a.branch}  {account}  {provision.would(row, found)}",
            f"- 起こすフォルダ: {row['path'] or '<作る作業場の場所>'}",
            f"- ペインの名前: {pane_label}／会話の名前: {a.task}",
            f"- 部署の属性: " + "、".join(f"company.{k}={v}" for k, v in attrs.items() if v),
            f"- 連絡の道: {route}",
            f"- 会社の形: {info['path'] or '無い'}（--dry-run なので origin を取り直さず、手元の控えで読んだ）",
            f"- 役の起動の設定: モデル {model or '既定'}、effort {effort or '既定'}、--settings の鍵 "
            + ", ".join(role.settings_for(the_role)),
            f"- gh のアカウント: " + (f"{gh_user}（会話の Bash がコマンドごとに鍵を取り出し、GH_TOKEN に入れる）" if gh_user else "渡さない"),
            f"- 最初の文: {_brief_text(brief, caller, account, tail)}"]))
        return 0
    existed = bool(provision.find(found, a.branch))
    try:
        base = None if existed else (a.base or ports.default_branch(repo))
    except (ghx.GhError, gitx.GitError) as e:
        print(f"止めた: {e}（枝を作る元の既定の枝を読めない。--base で渡す）")
        return 1
    prov = provision.prepare_task(row, repo, base, ports.herdr, ports.git)
    if prov["detail"]:
        notes.append(prov["detail"])
    result = prov["status"]
    pane = prov["pane"]
    if prov["status"] == "ready":
        try:
            trusted = ports.trust(row["account"], repo.source, prov["path"], cfg.accounts)
        except OSError as e:
            trusted = f"書けない（{e}）"
        if trusted not in ("inherited", "already"):
            notes.append("どのアカウントも元の clone を信頼していないので、Claude Code がフォルダの信頼の確認を出す"
                         if trusted == "source_untrusted" else
                         f"信頼の印を付けられない（{trusted}）。Claude Code がフォルダの信頼の確認を出す")
        try:
            provision.hide_claude_dir(repo.source, ports.git)
            # git worktree add は、extensions.worktreeConfig のとき、作った元の worktree（本社）の config.worktree を新しい
            # worktree に写す（2026-10-16 に git 2.50 と 2.56.0.windows.2 で見た）。本社に --desk が書いた窓口の属性（会話の id・
            # 前の名前など）が部署に写って残ると、部署が窓口の会話を自分の会話と取り違える（まっさらな環境での 4 回目の試しの 3）。
            # 本社と同じ値のまま残っている属性のうち、今回書かない物は消す
            # 立っている部署の場所を開き直したとき（--task の打ち直し・--move）は、属性は部署の物なので消さない（頼み元の受付箱
            # company.boss-inbox は、ふつう本社の物と同じ値なので、消されていた。d7d50c）
            office = {} if existed else ports.attrs(repo.source)
            copied = {k: None for k, v in ports.attrs(prov["path"]).items() if k not in attrs and office.get(k) == v}
            provision.mark(prov["path"], repo.source, {**copied, **attrs}, ports.git)
            if not ports.attrs(prov["path"]).get("base"):
                # この部署が本流を知った位置（枝を作ったときの origin の本流）。--land の書き換えの取り合いの関門が、ここより後に
                # ほかの部署が入れた行を、この部署の枝が消していないかを見る。--land の後は入れた後の本流に進む
                known = ports.git.rev(repo.source, f"refs/remotes/origin/{ports.default_branch(repo)}")
                if known:
                    provision.mark(prov["path"], repo.source, {"base": known}, ports.git)
            if attrs["residency"] == RESIDENT and a.branch:
                # 常設の部署の最初の枝も、入れた枝と同じに記録する。頼みごとに枝を移るので、入れずに移った最初の枝（--brief で
                # 立てただけの枝など）も手元に残る。先頭が今のままなら、部署が移った後の --land か --clean --apply が消す
                first = {**clean.landed_of(ports.attrs(prov["path"])), a.branch: ports.git.rev(prov["path"], "HEAD")}
                provision.mark(prov["path"], repo.source, {clean.LANDED_BRANCHES: json.dumps(first, ensure_ascii=False)}, ports.git)
        except (gitx.GitError, OSError) as e:
            notes.append(f"部署の属性を書けなかった（{e}）。--tree に役・頼み元が出ず、--sync で札を付け直せず、--clean が部署を片付けない")
        row["label"] = pane_label
        settings = ports.department_settings()
        if (the_role or {}).get("settings"):
            try:
                settings = role.write_settings(ports.git.git_dir(prov["path"]), role.settings_for(the_role))
            except (OSError, TypeError) as e:
                notes.append(f"役 {role_name} の設定を書けなかったので、役の設定なしで起こす（{e}）")
        got = launch.start_background(row, pane, a.task, settings, _brief_text(brief, caller, account, tail),
                                      ports.herdr, pause=ports.pause, model=model, effort=effort)
        if got["detail"]:
            notes.append(got["detail"])
        result = got["status"]
        if got["status"] == "sent":
            talk, why = _started(ports, row["account"].get("config_dir"), a.task, prov["path"], pane)
            if talk is None:
                result = "launch_failed"
                notes.append(why)
            else:
                sid = claudex.attach_id(talk)
                try:
                    provision.mark(prov["path"], repo.source, {"session": talk["sessionId"], "job": sid}, ports.git)
                except (gitx.GitError, OSError) as e:
                    notes.append(f"会話の id を属性に書けなかった（{e}）。--clean がこの部署を片付けない")
                got = launch.attach(row, pane, sid, ports.herdr)
                result = "started" if got["status"] == "attached" else got["status"]
                if got["detail"]:
                    notes.append(f"裏の会話 {sid} は始まったが、窓につなげなかった（{got['detail']}）")
                # 表示名と札は、書いた属性を git から読み戻して付ける（--sync と同じ組み立て。名前は launch が付けた）
                written = ports.attrs(prov["path"])
                shown = sync.apply([sync.op(pane, written, many, current_label=pane_label)], ports.herdr)
                notes += [f"ペインに表示名と札を付けられなかった（{x['detail']}）" for x in shown if x["status"] != "done"]
                if prov.get("workspace"):
                    shown = sync.apply_workspaces([sync.kind_op(prov["workspace"], written)], ports.herdr)
                    notes += [f"作業場に常設か都度かの印を付けられなかった（{x['detail']}）" for x in shown if x["status"] != "done"]
                    notes += _order_company(repo.source, info["skills"], ports)
                route += f"（会話 {sid}）"
    print("\n".join(notes + [f"部署 {a.task}  {a.branch}  {account}  {result}"] +
                    ([f"- ペイン {pane}（{pane_label}）、作業場 {prov['path']}、連絡の道: {route}"] if pane else [])))
    return 0 if result == "started" else 1   # 起きなかった（launch_failed・blocked など）を、呼んだ側（--ask・台本）に終了の値で知らせる


# 起こした裏の会話が会話の一覧に出るのを見る回数（1 回ごとに ports.pause）。Windows の `claude --bg` は、裏の会話を受ける
# 仕組み（background service）を起こすのに 2〜3 秒かかり、その間もペインの前のプロセスを見る口（shell_in_front）は戻ったと
# 答える（2026-10-16 に Windows 11 ARM64 の Claude Code 2.1.301 で、打ってから一覧に出るまで 2.7 秒を測った）。1 回だけ
# 見ると、立った会話を見落として launch_failed にし、attach を打たなかった（まっさらな環境での 4 回目の試しの 2）。
STARTED_LOOKS = 20
# `claude --bg` が起こした後にペインへ出す行（「backgrounded · <短い id> · <名前>」）。一覧より先に画面に出ることがある
BACKGROUNDED = re.compile(r"backgrounded\s*·\s*([0-9a-f]{6,})\s*·")


def _started(ports, config_dir, name, path, pane):
    """起こした裏の会話を、そのアカウントの会話の一覧（終わった物も）から、名前と場所で探す。(会話の 1 件, None) か
    (None, 訳)。出るまで STARTED_LOOKS 回まで見直す。見つからなければ、ペインの画面の終わりを訳に添える。"""
    tail = ""
    for look in range(STARTED_LOOKS):
        if look:
            ports.pause()
        try:
            items = ports.list_sessions(config_dir, include_done=True)
        except claudex.ClaudeError as e:
            return None, f"起こした後に会話の一覧を読めない（{e}）"
        mine = [s for s in items if s.get("name") == name and s.get("cwd") and fresh.inside(s["cwd"], path)]
        if mine:
            return max(mine, key=lambda s: s.get("startedAt") or 0), None
        try:
            screen = ports.herdr.read(pane, 6)
        except herdr.HerdrError as e:
            screen = f"画面も読めない（{e}）"
        tail = " ".join(screen.split())[-300:]
        shown = BACKGROUNDED.search(screen)
        if shown:   # 画面には起きたと出た: 一覧のその id の会話を使う（名前の字が一覧で違って見えるときも拾う）
            hit = [s for s in items if (s.get("id") or "").startswith(shown.group(1))
                   or (s.get("sessionId") or "").startswith(shown.group(1))]
            if hit:
                return hit[0], None
    return None, f"打ち込んだが、会話の一覧に「{name}」の裏の会話が出ない（{STARTED_LOOKS} 回見た。画面の終わり: {tail}）"


def _company(a, ports):
    """--tree と --sync。herdr の作業場から会社を出し、部署と属性と会社の情報を読んで組み立て（survey_companies）、--sync はその
    組み立てから付け直す（sync_companies）。dispatch の設定は無くてよい。有れば、アカウントごとの会話の一覧で部署の会話のアカウントを
    見て、設定の置き場の会社の情報を読む。"""
    if a.tree == a.sync:
        print("止めた: --tree か --sync のどちらか 1 つを付ける（--json は --tree と一緒に）")
        return 2
    if a.json and not a.tree or a.dry_run and not a.sync:
        print("止めた: --json は --tree と、--dry-run は --sync と一緒にだけ使う")
        return 2
    if a.sync:
        lines, rc = sync_companies(a.config, ports, a.dry_run)
        print("\n".join(lines))
        return rc
    try:
        _, _, companies, settings, notes = survey_companies(a.config, ports)
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
        return 1
    calls.annotate(companies, settings, ports.git)
    if a.json:
        jsonio.dump({"companies": companies, "notes": notes}, None)
        return 0
    print("\n".join(notes + tree.lines(companies)))
    return 0


def survey_companies(config_path, ports, only=None):
    """herdr の作業場から会社を出し（tree.roots）、会社ごとに部署（herdr アダプタの worktrees）と属性（git）と会社の情報を読んで
    組み立てる（tree.build）。only を渡せば、その代表の clone の会社だけ。(アカウントの並び, herdr の作業場の並び, 会社の並び,
    設定の置き場, 注記)。herdr を読めなければ herdr.HerdrError。"""
    notes = []
    path = config.path_of(config_path, os.environ)
    try:
        accounts_ = config.load(config_path, os.environ, missing_ok=True).accounts
    except config.ConfigError as e:
        accounts_ = (config.Account("default", "claude"),)
        if os.path.exists(path):
            notes.append(f"dispatch の設定を読めないので、既定のアカウント 1 つとして見る（{e}）")
    sessions_ = {}
    for acc in accounts_:
        try:
            sessions_[acc.name] = ports.list_sessions(acc.config_dir, include_done=True)
        except claudex.ClaudeError as e:
            notes.append(f"アカウント {acc.name} の会話の一覧を読めないので、そのアカウントの会話を見ない（{e}）")
    panes, workspaces_ = ports.herdr.panes(), ports.herdr.workspaces()
    roots = tree.roots(workspaces_, panes, ports.common_of,
                       list(dict.fromkeys(s["cwd"] for items in sessions_.values() for s in items if s.get("cwd"))))
    if only:
        roots = [r for r in roots if os.path.realpath(r) == os.path.realpath(only)]
    places_of = {}
    for root in roots:
        try:
            places_of[root] = ports.herdr.worktrees(root)
        except herdr.HerdrError as e:
            places_of[root] = []
            notes.append(f"{root}: worktree を並べられない（{e}）")
    settings = os.path.dirname(path)
    companies = tree.build(roots, places_of, panes, ports.attrs, lambda root: tree.read_info(root, settings), sessions_)
    for d in (d for c in companies for d in c["departments"]):
        d["tool_place"] = not d["branch"] and tools.is_place(d["path"])   # 機械の道具を走らせる一時の worktree（--tree が「（枝無し）」と分けて出す）
    return accounts_, workspaces_, companies, settings, notes


def _order_company(source, skills, ports):
    """立てた部署の会社の作業場を、仕事の流れの順に並べ直す（sync.flow_order。herdr は新しい作業場を後ろに足すので、常設の部署を
    立てたときは前へ動かす）。ほかの会社の作業場は、会社の印を外して渡し、動かさない。並べ直せなかった訳の注記の並び。"""
    root = os.path.realpath(source)
    try:
        listed = [w if w.get("repo_root") and os.path.realpath(w["repo_root"]) == root else {**w, "repo_root": None}
                  for w in ports.herdr.workspaces()]
    except herdr.HerdrError as e:
        return [f"作業場を流れの順に並べられなかった（herdr を読めない: {e}）"]
    done = sync.apply_order(sync.flow_order(listed, ports.attrs, lambda r: skills), ports.herdr)
    return [f"作業場を流れの順に並べられなかった（{x['detail']}）" for x in done if x["status"] == "failed"]


def sync_companies(config_path, ports, dry_run=False, only=None):
    """--sync の中身。会社の形の役を部署と本社の属性に写し直し（_sync_roles）、付ける物を決めて（sync.plan）herdr に書く（sync.apply）。
    only を渡せば、その代表の clone の会社だけ（会社の形が替わったときの番の終わりのフック。shape_hook.py）。(出す行の並び, 終了の値)。"""
    try:
        accounts_, workspaces_, companies, settings, notes = survey_companies(config_path, ports, only)
    except herdr.HerdrError as e:
        return [f"止めた: herdr を読めない（{e}）"], 1
    notes += _sync_roles(companies, settings, ports, dry_run)
    ops, why = sync.plan(companies, len(accounts_) > 1, orders.waiting_of(tempfile.gettempdir()))
    ws_ops = sync.workspace_ops(companies, workspaces_)
    moves = sync.flow_order(*_flow_inputs(companies, workspaces_))
    notes += why
    none = [] if ops or ws_ops else ["付け直す部署は無い（属性を持つ部署が無い）"]
    lines = [sync.workspace_line(o) for o in ws_ops] + [_op_line(o) for o in ops] + [sync.order_line(o) for o in moves]
    if dry_run:
        return notes + lines + none, 0
    done = sync.apply_workspaces(ws_ops, ports.herdr) + sync.apply(ops, ports.herdr) + sync.apply_order(moves, ports.herdr)
    return (notes + [f"{line}  {r['status']}" + (f"（{r['detail']}）" if r["detail"] else "") for line, r in zip(lines, done)] + none,
            1 if any(r["status"] != "done" for r in done) else 0)


def _flow_inputs(companies, workspaces_):
    """sync.flow_order に渡す (作業場の並び, 場所 → 属性, 根 → 受け持ちの並び)。会社の並び（tree.build）の部署の属性を使い、並べるのは
    その会社の作業場だけ（ほかの作業場は会社の印を外して渡す。--sync の only で絞った会社のほかは動かさない）。"""
    roots = {os.path.realpath(c["root"]): c for c in companies}
    attrs = {os.path.realpath(d["path"]): d["attrs"] for c in companies for d in c["departments"] if d.get("path")}
    listed = [w if w.get("repo_root") and os.path.realpath(w["repo_root"]) in roots else {**w, "repo_root": None} for w in workspaces_]
    return (listed, lambda path: attrs.get(os.path.realpath(path), {}),
            lambda root: roots[os.path.realpath(root)].get("skills") or [])


def _sync_roles(companies, settings, ports, dry_run):
    """会社の形の役を、今いる部署と本社の属性に写し直す（会社の形を変えたら、--sync 1 回で全部の場所に行き渡らせる。--ask・
    --reorg --role を待たない）。属性 company.role が役の前の名前（former_names）なら今の名前に、company.fresh は役の fresh に。
    companies の中の属性も書き換え、続く表示がそれを使う。出す行の並び。会社の形に無い役の場所は触らない。--dry-run なら書かずに、
    書く物だけを出す。"""
    out = []
    for c in companies:
        info = tree.read_info(c["root"], settings)
        shape = role.load(info["path"], info["text"])
        for d in c["departments"]:
            got = shape["roles"].get(role.current(shape, d["attrs"].get("role")))
            if not got:
                continue
            changes, why = {}, []
            if d["attrs"].get("role") != got["name"]:
                changes["role"] = got["name"]
                why.append(f"company.role {d['attrs'].get('role')} → {got['name']}（役の前の名前を今の名前に）")
            want = role.FRESH if got["fresh"] else None
            if (d["attrs"].get("fresh") or None) != want:
                changes["fresh"] = want
                why.append(f"company.fresh {d['attrs'].get('fresh') or '-'} → {want or '（消す）'}（役 {got['name']} の fresh を写す）")
            if not changes:
                continue
            line = f"{c['name']} {d['attrs'].get('name') or d['branch'] or d['path']}: " + "、".join(why)
            if not dry_run:
                try:
                    provision.mark(d["path"], c["root"], changes, ports.git)
                except (gitx.GitError, OSError) as e:
                    out.append(f"{line}  書けなかった（{e}）")
                    continue
            d["attrs"] = {k: v for k, v in {**d["attrs"], **changes}.items() if v}
            if "role" in changes:
                d["role"] = got["name"]
            out.append(line)
    return out


def _op_line(o):
    shown = [f"名前 {o['label']}" if o["label"] else "名前はそのまま", f"表示名 {o['display_agent'] or '-'}",
             f"題名 {o['title'] or '-'}", "札 " + ("、".join(f"{k}={v}" for k, v in o["tokens"].items()) or "-")]
    return f"ペイン {o['pane']}: " + "  ".join(shown)


def _check(cfg, ports):
    # 先に要る道具の段（tiers）を点検する。足りなければ、その案内を出して止まる（設計 4.11）。部品が無ければ注記にして、今までの確かめを続ける
    tier_notes = []
    try:
        tiers = ports.tiers(list(dict.fromkeys(a.command for a in cfg.accounts)))
    except tierx.TierError as e:
        # 段の点検を回せないまま「足りない物は無い」と言わない（herdr が動いていなくても通ってしまう）
        print(f"足りない物（要る道具の段の点検を回せない）:\n- {e}")
        return 2
    if tiers is not None and not cfg.repos:
        tiers, no_gh = tierx.without_gh(tiers)
        tier_notes += [f"{line}（部署の回には要らない。PR を開く回と、gh を使う役の部署に要る）" for line in no_gh]
    if tiers is not None and not tiers.get("ok"):
        print("足りない物（要る道具の段の点検。手で入れてから --check を打ち直す）:")
        print("\n".join(tierx.report(tiers)))
        return 2
    problems, notes = ports.preflight(cfg, task=not cfg.repos)
    # origin/HEAD が無い元の clone は、会社の形を作業ツリーから読む（止めずに直し方を出す）
    heads = [n for n in dict.fromkeys(tree.head_note(r.source) for r in cfg.repos if r.source) if n]
    notes = list(cfg.notes) + tier_notes + notes + heads
    if not cfg.repos:
        notes.insert(0, "設定に [[repos]] が無いので、部署の回（--task・--ask・--land）の前提だけを確かめた"
                        "（PR を開く回も使うなら python3 dispatch.py --init --repo OWNER/NAME --source <代表の clone> で下書きを作る）")
    for acc in cfg.accounts:
        try:
            ports.list_sessions(acc.config_dir)
        except claudex.ClaudeError as e:
            problems.append(f"アカウント {acc.name}: {e}（開いている会話を読む claude agents --json が通らない。Claude Code を新しくする）")
    print("\n".join(notes))
    if problems:
        print("足りない物:")
        print("\n".join(f"- {p}" for p in problems))
        return 2
    print("始める前の確かめ: 足りない物は無い")
    return 0


# 代表の clone の、git が追わないファイルのうち、PR ごとの clone へ写す候補（環境変数・手元だけの設定）
LOCAL_FILE = re.compile(r"(^|/)\.env[^/]*$|\.local(\.[^/]+)?$")


def _init(a, ports):
    if not (a.repo and a.source):
        print("止めた: --init には --repo OWNER/NAME と --source <代表の clone> が要る")
        return 2
    path = config.path_of(a.config, os.environ)
    if os.path.exists(path):
        print(f"設定はもうある: {path}（上書きしない。足すなら手で書く）")
        return 1
    source = os.path.abspath(os.path.expanduser(a.source))
    origin = ports.origin(source)
    if origin != a.repo:
        # --check も同じ所（元の clone が、このリポジトリの clone でない）で止まる。書く前に知らせる
        print(f"止めた: --source の {source} は " + (f"origin が {origin} の clone で" if origin else "origin の在る git の clone でなく")
              + f"、--repo の {a.repo} と合わない（--repo に origin の OWNER/NAME を渡すか、そのリポジトリの clone を --source に渡す）")
        return 2
    local = [f for f in ports.git.ignored_files(source) if LOCAL_FILE.search(f)]
    second = os.path.join(os.path.dirname(path), "dispatch-second-prompt.md")
    home = ports.env.get("HOME") or os.path.expanduser("~")
    seen = sorted("~/" + n for n in os.listdir(home)
                  if n.startswith(".claude") and os.path.isfile(os.path.join(home, n, "plugins", "installed_plugins.json")))
    q = json.dumps
    lines = [
        "# works の dispatch の設定（--init が書いた下書き）。直したら --check で確かめる。",
        "# 欄の書き方: works-dispatch の skills/dispatch/SKILL.md の「初めて」と「アカウントの書き方」（前提の訳は docs/prerequisites.md）",
        "",
        "limit_percent = 95                      # 週か 5 時間の使用率がこれに達したアカウントは使わない",
        "# reset_soon_hours = 24                 # 週の枠の切り替わりがこの時間以内のアカウントを先に使う（使わずに切り替わる分を無駄にしない）",
        '# limits_dir = "~/.cache/claude-limits"   # アカウントごとの使用率の控え（<name>.json）。無ければ使用率は見ない',
        "",
        "# アカウントを切り替えないなら accounts は書かない（claude を 1 つだけ使う）。",
        "# 切り替えるなら、名前・そのアカウントで Claude Code を起こすコマンド・そのコマンドが CLAUDE_CONFIG_DIR に入れるフォルダを並べる。",
        "# 鍵を自分で決めた名前の Keychain の項目に置いたなら keychain_service、使用率の枠の無いアカウント（Ollama など）は limits = false。",
        "# CLAUDE_CONFIG_DIR をシェルの環境でだけ入れて claude を起こす人も、そのフォルダを config_dir に書く（書かないと ~/.claude を見る）:",
        "# accounts = [",
        '#   { name = "main", command = "claude" },',
        '#   { name = "sub",  command = "<別のアカウントで起こすコマンド>", config_dir = "~/.claude-sub" },',
        '#   { name = "mine", command = "<コマンド>", config_dir = "~/.claude-mine", keychain_service = "<Keychain の項目の名前>" },',
        '#   { name = "local", command = "<Ollama などで起こすコマンド>", limits = false },',
        "# ]",
        f"# この機械で見つかった Claude Code の設定のフォルダ: {', '.join(seen) or '無し'}",
        "",
        "[[repos]]",
        f"repo = {q(a.repo)}",
        f"second_prompt_file = {q(second)}   # 2 ターン目に送る文。空のままだと --check が止める",
        f"source = {q(source)}   # 代表の clone。枝ごとの worktree はここから作る（置き場は herdr の worktrees.directory）",
        "copy_files = [   # git が追わない手元だけのファイル。代表の clone で見つかった候補",
        *[f"  {q(f)}," for f in local],
        "]",
        '# copy_from = "<フォルダ>"   # copy_files を写す元。省けば代表の clone から',
        '# gh_user = "<ログイン名>"   # gh の有効なアカウントでこのリポジトリを読めないときだけ',
        "",
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    if not os.path.exists(second):
        open(second, "w", encoding="utf-8").close()
    print(f"書いた: {path}")
    print(f"2 ターン目の文: {second}（空。送りたい文を書く）")
    print("次: python3 dispatch.py --check")
    return 0


# 会社の形の下書き（--init-company）。欄の読み手は nodes/tree.py（name・description・skills）・nodes/role.py（gh_user・roles）・
# nodes/land.py（land）。名前は herdr の画面で読む物から決めた日本語（持ち主 2026-10-16。会社らしい名前・英語はやめた）:
# 役は 窓口・担当（受け持ちに常設）・作業（一度きり）・相談 の 4 つで、[[roles]] に書くのは 担当・作業・窓口（窓口は代表の clone の
# 会話で、組織の決まりを届けるために役の本文を持つ。相談は持ち主が直接話す会話で、会社ごとに要るときに足す）。受け持ちは会社ごとに
# 違うので、例を 1 つだけ <…> の置き字で書く
COMPANY_DRAFT = """# 会社の形: このリポジトリで部署（作業ごとの会話）を立てるときの、会社の名前・役・gh のアカウント・本流への入れ方。
# 読むのは works-dispatch（--tree・--task・--ask・--deliver・--land と、役を足すフック）。--init-company が書いた下書き。
# 書き方: works-dispatch の skills/dispatch/SKILL.md の「役の中身と起こし方」と「本流に入れる」。
# 置き場は 2 つ。リポジトリの中（.claude/company.toml）なら commit すると同じリポジトリを使う人に効く。commit しない物は、
# dispatch の設定の置き場の companies/ に置く（--init-company --local）。両方に在れば、リポジトリの中の物を読む。
# <…> は置き字なので、受け持ちの名前と中身に直す（受け持ちを増やすなら、[[skills]] の項目を写して足す）。

name = {name}   # 会社の名前（--tree と --ask の「会社/役」に出る。herdr ではリポジトリの親の作業場の名前になる）
description = {description}   # この会社が受ける仕事
gh_user = {gh_user}   # 部署の会話の gh が使うアカウント{gh_note}
default_role = "作業"   # --task で --role を省いたときの役
desk_role = "窓口"   # 本社で持ち主と話す会話の役（--desk で --role を省いたときの役）

# 受け持ち。1 つの受け持ちに担当が常設で 1 人つき、担当の部署の名前（herdr の作業場の名前）は受け持ちの name にする。
# 担当の会話の始まりに、部署の名前と同じ name の受け持ちの description が足される。--tree にも出る
[[skills]]
id = "duty"
name = "<受け持ち>"
description = "<受け持ちのフォルダかプラグイン>の直し"
role = "担当"
# model = "sonnet"   # この受け持ちの部署を起こすときの --model（役の model より優先する。省けば役の値、それも無ければアカウントの既定）
# effort = "low"     # この受け持ちの部署を起こすときの --effort（役の effort より優先する。書ける値は役の effort と同じ）

[[skills]]
id = "one-off"
name = "一度きりの作業"
description = "受け持ちの無い一度きりの作業と、担当が並べて進めたい作業を、一時の作業の部署で受ける"
role = "作業"

# 役。部署を立てるときに --role で選ぶ（省けば default_role）。instructions は、その役の会話の頭に毎回足す役の本文
# deliver は納品する要約の必須の項目。担当と作業はコードの直しなので、差分と試験を返させる（省くと既定の 結論・決め手・残った疑問・枝
# になり、決め手に原典の URL を求める。調べものの役に向く）
# 担当: 受け持ちに常設で 1 人（resident = true なので、--resident を付けなくても常設の部署で立つ。片付けで畳まれず、次の頼みを
# 同じ部署で受ける）。fresh = true なので、頼みごとに空の会話で受ける（前の頼みを納品し終えていれば、--ask が新しい頼みを打つ前に
# /clear を打つ。常設の値打ちは記憶ではなく受け持ちごとの席〔順番を 1 本にする・宛先の名前・決まった窓〕で、前の頼みの記憶は
# 太るうえ、覚えた中身で書き直すと、ほかの部署が入れた行を消す）。持ち越すなら fresh を消す。
# 最初の頼みと一緒に立てるなら --ask {plain}/担当 --task <受け持ち> --branch <枝> --text <頼み>。
# 頼み無しで立てるなら --task <受け持ち> --branch <枝> --role 担当 --brief <頼みのファイル>（--task には --brief が要る）
[[roles]]
name = "担当"
instructions = {duty}
deliver = ["結論", "差分", "試験", "残った疑問", "枝"]
resident = true
fresh = true
# model = "opus"   # 部署を起こすときの --model（省けばアカウントの既定）
# effort = "high"  # 部署を起こすときの --effort（low・medium・high・xhigh・max・ultracode。inherit なら頼んだ会話と同じ。省けば既定）
# deliver_check = "<納品の検査の命令>"   # --deliver が部署の作業場の根で走らせ、0 以外で終われば送らない（省けば検査しない）
# 部署の会話にだけ効かせる Claude Code の設定（--settings で渡す。要らないプラグインを切るなどもここ）。
# autoMode.allow は、自動の権限の判定（auto mode の classifier）の組み込みの拒否への例外を文で書く（"$defaults" で組み込みの
# 決まりを残す）。--land は本流へ早送りするので「Merge Without Review」として止められることがある。人のレビューの代わりに
# 会社の形の [land] の関門を通す決まりであることを書いて、止めないようにする（https://code.claude.com/docs/en/auto-mode-config）
[roles.settings]
autoMode = {{ allow = ["$defaults", {land_allow}] }}
# enabledPlugins = {{ "<プラグイン>@<マーケットプレイス>" = false }}

# 作業: 一度きりの作業をする一時の部署（頼みごとに立ち、本流に入れたら畳まれる）
[[roles]]
name = "作業"
instructions = {work}
deliver = ["結論", "差分", "試験", "残った疑問", "枝"]
[roles.settings]
autoMode = {{ allow = ["$defaults", {land_allow}] }}

# 相談: 持ち主が直接話して考えを詰める会話。要る会社だけ # を外して足す。常設で、話の流れを持ち越す（fresh は書かない）
# [[roles]]
# name = "相談"
# instructions = "持ち主と話して考えを詰める。決まったことは頼みに書き直して窓口に渡す。"
# resident = true

# 窓口: 持ち主と話して頼みを配る、代表の clone の会話（部署ではない）。窓口の会話から --desk を打つと、この役の本文が次の会話の
# 始まりから足される（組織の決まりを窓口に届けるため。コメントの決まりは、どの会話にも届かない）。本文を替えると、会話を持ち越して
# いる部署と窓口にも、次の番の頭に今の本文が足される
# 役の名前を替えるときは、前の名前を former_names = ["<前の名前>"] に書く（前の名前で宛てた頼みと、前の名前を持つ部署が今の役に当たる）
[[roles]]
name = "窓口"
instructions = {desk}

# 部署の成果を本流に入れる決まり（--land）。none は何もしない（入れるのは人）。
# pr は本流への PR を出して止まる。ff-after-ci は関門（gate。CI の枝の形か check）が緑なら本流を早送りする。
# none 以外にしたら、担当と作業の本文の「push し」を「--land <自分の部署の名前> で本流に入れ」に替える
[land]
mode = "none"
# gate = "check"
# check = "<手元の検証のコマンド>"

# 組織の決まり（この会社の作り方。部署の会話には届かないので、部署に守らせることは役の本文にも書く）
# - 役は 4 つ: 窓口（持ち主と話して頼みを配る、本社の会話。--desk で名付ける）・担当（受け持ちに常設で 1 人）・作業（一度きりの
#   作業をする一時の部署）・相談（持ち主が直接話して考えを詰める会話。要る会社だけ [[roles]] に足す）。同じ受け持ちの直しは担当の
#   下で順番に進むので、同じファイルの取り合いにならない。
# - 名前は日本語で、herdr の画面で読んで分かる短い言葉にする。担当の部署の名前は受け持ちの名前（例: 「<受け持ち>」）、作業の部署の
#   名前は「<受け持ち>：<何をするか>」（作業場の名前になるので 12 字くらいまで）。会社の名前は herdr の親の作業場にだけ出るので、
#   部署の名前には付けない。
# - 枝の名前は英小文字とハイフンにする（git と GitHub の URL で崩れないため）。直しは fix/…、足すものは feat/…、調べや下書きは work/…。
# - 担当への頼みは部署の名前で宛てる（--ask <受け持ち>。部署の名前は役より先に当たる）。担当がまだ居ない受け持ちは
#   --ask {plain}/担当 --task <受け持ち> --branch <枝> --text <頼み> で、最初の頼みと一緒に立てる。頼んだ部署が頼み元になり、納品はそこに返る。
# - 担当の受け持ちの中の作業は、担当に頼む（窓口が作業に直に頼まない。同じファイルを 2 つの部署が触ると、後から入れた方が前の変更を消す）。
# - 納品の後に判断が要ることが出たら、画面に書いて止まらず、もう一度納品の命令（--deliver）で返す（画面にだけ書いた問いは届かない）。
"""
# 役の本文の共通の終わり。組織の決まりのうち、部署が守ることを部署の会話に届ける（コメントは部署に届かない）
DRAFT_RETURN = ("済んだら作業の枝に push し、要約を納品の命令（--deliver）で頼み元に返す。納品の後に判断が要ることが出たら、"
                "画面に書いて止まらず、もう一度納品の命令で返す（画面にだけ書いた問いは頼み元に届かない）。")
DRAFT_BRANCH = "枝の名前は英小文字とハイフンにし、直しは fix/…、足すものは feat/…、調べや下書きは work/… にする。"
# 自動の権限の判定への例外（役の settings の autoMode.allow）。--land は、関門を通した後に本流を早送りして push する
DRAFT_LAND_ALLOW = ("この部署が works-dispatch の --land（dispatch.py --land <自分の部署の名前>）で自分の枝を本流に入れること。"
                    "本流への取り込みは、人のレビューの代わりに、会社の形（.claude/company.toml）の [land] の関門を通してから"
                    "早送りする決まりで、持ち主がこの会社の部署に許している。")
# 自動の権限の判定に止められたときの手。打ち直しで判定を回り込まず、窓口に入れてもらう
DRAFT_DENIED = ("--land が自動の権限の判定（auto mode）に止められたら、打ち直さず、窓口に --land <部署の名前> を打って入れてほしいと"
                "--ask <会社の名前> で頼み、その受付を納品の残った疑問の持ち手に書いて返す（残った疑問に書くだけでは窓口に届かない）。")
# commit に足す物の決まり。git add -A は、試験や検証が作った生成物（__pycache__ など。.gitignore の無いリポジトリ）まで本流に入れる
DRAFT_COMMIT = "commit に足すのは自分が触ったファイルだけにする（git add -A や git add . をしない）。"
DRAFT_DUTY = ("受け持ちを常設で預かる。自分の受け持ちは部署の名前で決まる。常設なので、作業場は同じまま、頼みごとに git fetch origin "
              "してから origin の既定の枝から枝を切って作業する。" + DRAFT_BRANCH + "枝を切った後、触るファイルを本流から読み直してから"
              "書く（前の頼みで覚えた中身で書かない。覚えた中身で書くと、ほかの部署が入れた変更を消してしまう）。" + DRAFT_COMMIT + "並べて進めたい作業は作業に頼む"
              "（--ask {company}/作業 に --task <受け持ち>：<何をするか> --branch <枝> を添える）。試験は触った所の物だけを回す。"
              + DRAFT_RETURN + DRAFT_DENIED + "受け持ちの外のファイルを変える必要が出たら、その受け持ちの担当に部署の名前で頼む（--ask <受け持ち>）。")
DRAFT_WORK = "一度きりの作業をする。頼まれた所を直す。" + DRAFT_BRANCH + DRAFT_COMMIT + "試験は触った所の物だけを回す。" + DRAFT_RETURN + DRAFT_DENIED
DRAFT_DESK = ("持ち主と話し、仕事を頼みに変えて部署に配る。自分ではファイルを直さない。受け持ちの中の仕事は、その担当に部署の名前で頼む"
              "（--ask <受け持ち>）。担当がまだ居ない受け持ちは --ask {company}/担当 --task <受け持ち> --branch <枝> --text <頼み> で立てる。"
              "受け持ちの無い一度きりの作業だけを作業に頼む（--ask {company}/作業 --task <受け持ち>：<何をするか> --branch <枝>）。"
              "担当の受け持ちの中の作業を、作業に直に頼まない（同じファイルを 2 つの部署が触ると、後から入れた方が前の変更を消す）。"
              + DRAFT_BRANCH + "担当と作業は、本流に入れる決まり（会社の形の [land]）が none でなければ、自分で --land して本流に入れてから"
              "納品する（窓口から頼まなくてよい）。担当や作業が「--land が自動の権限の判定に止められた」と返したら、窓口から "
              "--land <部署の名前> を打って入れる。納品は要約を読んで持ち主に伝える。")


def _draft_gh_user(ports):
    """下書きに書く gh_user と、その行の注記（1 行）。gh の今のアカウントを読めないか、その鍵を `gh auth token --user` で取り出せない
    （鍵を GH_TOKEN で渡している人など。部署の会話は gh_user の鍵をそれで取り出す）なら書かず (None, 訳)。注記は TOML の
    1 行の注記の中に置くので、gh の誤りの文は 1 行に畳む（複数行のまま入れると、2 行目が # の外に出て TOML が壊れる）。"""
    def one_line(e):
        return " ".join(str(e).split())[:160]
    try:
        user = ports.gh.login()
    except ghx.GhError as e:
        return None, f"。gh の今のアカウントを読めなかったので書かない（{one_line(e)}）。書かなければ、その人の今の gh の設定で動く"
    try:
        ports.gh.env_for(user, dict(ports.env))
    except ghx.GhError as e:
        return None, (f"。gh の今のアカウント {user} の鍵を gh auth token --user で取り出せないので書かない（GH_TOKEN で鍵を渡している"
                      f"ときなど。{one_line(e)}）。書かなければ、その人の今の gh の設定で動く")
    return user, "（--init-company を打った時の gh の今のアカウント）"


def _init_company(a, ports, cwd):
    """--init-company。会社の形の下書きを、リポジトリの中の .claude/company.toml（--local なら設定の置き場の companies/）に書く。
    在れば上書きしない。commit はしない（するかは利用者が決める）。"""
    place = os.path.expanduser(a.repo) if a.repo else cwd
    root = ports.common_of(place) if os.path.isdir(place) else None
    if not root:
        print(f"止めた: {place} が git のリポジトリでない（--repo に代表の clone のパスを渡すか、その clone の中から打つ）")
        return 2
    settings = os.path.dirname(config.path_of(a.config, os.environ))
    path = tree.settings_info_path(settings, root) if a.local else os.path.join(root, *tree.INFO_FILE)
    if os.path.exists(path):
        print(f"会社の形はもうある: {path}（上書きしない）")
        return 1
    other = os.path.join(root, *tree.INFO_FILE) if a.local else tree.settings_info_path(settings, root)
    gh_user, gh_note = _draft_gh_user(ports)
    def q(v):
        return json.dumps(v, ensure_ascii=False)   # TOML の基本の文字列と同じ書き方
    company = os.path.basename(os.path.normpath(root))
    text = COMPANY_DRAFT.format(name=q(company), description=q("<この会社が受ける仕事を 1 行で>"), gh_user=q(gh_user or ""),
                                gh_note=gh_note, plain=" ".join(company.split()), duty=q(DRAFT_DUTY.format(company=company)),
                                work=q(DRAFT_WORK), desk=q(DRAFT_DESK.format(company=company)),
                                land_allow=q(DRAFT_LAND_ALLOW))
    if not gh_user:
        text = text.replace('gh_user = ""', '# gh_user = "<ログイン名>"')
    tomllib.loads(text)   # 下書きは必ず TOML として読める形にする（読めなければ書かずに例外で止める。作り手の誤り）
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"書いた: {path}")
    if os.path.exists(other):
        print(f"注意: {other} にも会社の形が在る。読むのはリポジトリの中の物（origin の既定の枝に commit された物が先）")
    where = "commit しない置き場に書いた。" if a.local else ""
    print(f"{where}名前・説明と、<…> の置き字（受け持ちの名前と中身）・役の本文を直す"
          + ("" if a.local else "。同じリポジトリを使う人にも効かせるなら commit する（commit しないなら --init-company --local で設定の置き場に書く）"))
    return 0


def _department_rows(cfg, repo, ports, found, notes, assume_stopped=()):
    """部署（--task が立てた worktree）の片付けの候補（clean.departments）。会話は全アカウントの一覧（終わった物も）で引く。
    本流は origin の既定の枝の手元の控え。読めなければ、部署は並べない（消さない側に倒す）。assume_stopped の会話の id
    （sessionId）は、止まった物とみなす（--retire が、止める前に会話のほかに残す訳が無いかを見る）。"""
    try:
        listed = {acc.name: (acc, ports.list_sessions(acc.config_dir, include_done=True)) for acc in cfg.accounts}
        target = f"refs/remotes/origin/{ports.default_branch(repo)}"
    except (claudex.ClaudeError, ghx.GhError, gitx.GitError) as e:
        notes.append(f"部署の片付けを飛ばした（会話の一覧か既定の枝を読めない: {e}）")
        return []

    def session_of(attrs):
        return next(({**s, "config_dir": acc.config_dir, **({"state": "stopped"} if s.get("sessionId") in assume_stopped else {})}
                     for acc, items in listed.values() for s in items if s.get("sessionId") == attrs["session"]), None)

    return clean.departments(found, ports.attrs, session_of, ports.is_clean, ports.unpushed,
                             lambda path: gitx.is_merged(path, target), ports.head_sha, source=repo.source)


DEPT_REASONS = {"resident": "常設の部署は畳まない", "running": "会話がまだ動いている", "dirty": "未コミットの変更が有る", "unpushed": "手元にしか無い commit か stash が有る",
                "not_merged": "枝が本流に入っていない", "no_branch": "枝に乗っていない"}


def _running_note(d, attrs):
    """会話がまだ動いているので残す部署の訳に足す、段取りが止めるかを決める手がかり（ほかの訳の部署には足さない）。"""
    if d["reason"] != "running":
        return ""
    if attrs.get(wake.RETIRE_KEPT):
        return f"。終わりの印で畳もうとして残った: {attrs[wake.RETIRE_KEPT]}"
    if attrs.get(wake.FINISHED):
        return "。終わりの印が有る（この番の終わりに畳む）"
    name = d["name"] or d["branch"]
    got = orders.leftover(d["path"], attrs)
    if got is None:
        return ""
    if got[0] == "waiting":
        return f"。頼みは納品済みで、この部署が頼んだ返事を待っている（受付 {'・'.join(got[1])}）"
    if got[0] == "unlanded":
        return (f"。頼みは納品済みだが、枝が本流（origin/{got[1]}）に入っていない（入れ損ねか、入れる手を待っている。消すと成果を失う）。"
                f"入れるなら --land {name}")
    return f"。頼みは納品済みで、終わりの印（--done）が無い。止めて畳むなら --retire {name}"


def _tool_places(repo, ports, apply):
    """機械の道具を走らせる一時の worktree（tools.place）を並べ、apply なら作った処理がもう居ない物を消す（tools.sweep。道具を走らせる
    たびにも消す）。(消せなかった数, 消せる物が在ったか)。"""
    listed = [e for e in ports.git.listed_worktrees(repo.source) if tools.is_place(e["path"])]
    stale = set(tools.leftovers(listed))
    removable = False
    for e in listed:
        if e["path"] not in stale and (e["locked"] or "").startswith(tools.OWNER):
            print(f"道具の一時の場所 {e['path']}  残す（道具が走っている）")
            continue
        if e["path"] not in stale:
            # 鍵が無い（前の版が作った）か、ほかの訳の鍵: 走っているかを確かめられないので消さない。手で消すときも commit を失わない手順を添える
            got = tools.judge(e, ports.git, repo.source)
            print(f"道具の一時の場所 {e['path']}  残す（" + ("鍵が無い" if e["locked"] is None else f"鍵の訳が「{e['locked']}」")
                  + "。道具が走っているかもしれないので消さない。走っていなければ"
                  + (f"、{got['why']}ので中を見てから" if got["why"] else "")
                  + (f"、先に git -C {repo.source} update-ref {tools.KEPT_REF}{got['keep']} {got['keep']} で先頭の commit を残してから"
                     if got["keep"] else "")
                  + f" git -C {repo.source} worktree remove -f -f {e['path']} で消す）")
            continue
        got = tools.judge(e, ports.git, repo.source)
        removable = removable or not got["why"]
        print(f"道具の一時の場所 {e['path']}  " + (
            f"残す（作った処理はもう居ないが、{got['why']}。中を見て、要らなければ git -C {repo.source} worktree remove -f -f {e['path']}）"
            if got["why"] else "消せる（作った処理がもう居ない" + (f"。どの枝にも無い先頭の commit を {tools.KEPT_REF}{got['keep']} に残してから消す"
                                                             if got["keep"] else "") + "）"))
    if not apply or not removable:
        return 0, removable
    done, bad = tools.sweep(repo.source, ports.git)
    for got in done:
        print(f"道具の一時の場所 {got['path']} 消した" + (f"（先頭の commit を {tools.KEPT_REF}{got['keep']} に残した）" if got["keep"] else ""))
    for path, why in bad:
        print(f"道具の一時の場所 {path} 消せなかった: {why}")
    return sum(1 for _, why in bad if why != "未コミットの変更が在る"), True


def _clean(cfg, repo, apply, ports):
    try:
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
        found = ports.places(repo)
    except (claudex.ClaudeError, herdr.HerdrError) as e:
        print(f"止めた: {e}（開いている会話か元の clone の worktree を読めないので、何も消さない）")
        return 1
    notes = []
    depts = _department_rows(cfg, repo, ports, found, notes)
    dept_paths = {os.path.realpath(d["path"]) for d in depts}
    swept = landing.sweep_branches(repo, ports, found, apply)
    for d in depts:
        kept = len(clean.tmp_entries(claudex.job_tmp(d["config_dir"], d["session"], ports.account_env))) if d["removable"] and d["session"] else 0
        print(f"部署 {d['name'] or '-'} {d['branch'] or '（枝無し）'}  {d['state']}  "
              + (("消せる" + (f"（会話の一時の置き場の {kept} 件は、共通の .git の company/kept-tmp/ に写してから消す）" if kept else ""))
                 if d["removable"] else f"残す（{DEPT_REASONS[d['reason']]}{_running_note(d, ports.attrs(d['path']))}）"))
    print("\n".join(notes + swept) if notes or swept else "", end="\n" if notes or swept else "")
    failed, stale = _tool_places(repo, ports, apply)
    if apply:
        for d in (d for d in depts if d["removable"]):
            got = clean.retire(d, repo.source, provision.label(repo, d["branch"]), ports.herdr, ports.git, claudex, ports.account_env)
            print(f"部署 {d['name'] or '-'} {'消した' if got['removed'] else '消せなかった'}" + (f": {got['detail']}" if got["detail"] else ""))
            failed += not got["removed"]
    found = [p for p in found if os.path.realpath(p.get("path") or "") not in dept_paths and not tools.is_place(p.get("path"))]
    removable = stale or any(d["removable"] for d in depts)
    cwds = {s.get("cwd") for items in listed.values() for s in items if s.get("cwd")}
    if not any(os.path.realpath(r.source) == os.path.realpath(repo.source) for r in cfg.repos):
        # 設定の [[repos]] に無い会社: PR の作業場は見ない（PR の状態を GitHub に問うのは、PR を開く回に使うリポジトリだけ）
        if not depts:
            print(f"元の clone {repo.source} に部署は無い（設定の [[repos]] に無いので、PR の作業場は見ない）")
        if not apply and removable:
            print("消すには --clean --apply を付けて打ち直す")
        return 1 if failed else 0
    rows = clean.candidates(found, lambda b: ports.pr_for_branch(repo, b), cwds, ports.is_clean, ports.stashed, ports.head_sha,
                            source=repo.source, changed=_changed(repo))
    if not rows:
        if not depts:
            print(f"元の clone {repo.source} の worktree は無い")
        if not apply and removable:
            print("消すには --clean --apply を付けて打ち直す")
        return 1 if failed else 0
    for r in rows:
        mark = "消せる" if r["removable"] else f"残す（{r['reason']}{': ' + ', '.join(r['files']) if r['files'] else ''}）"
        print(f"{_where(r)}  {r['state'] or '-'}  {mark}")
    if not apply:
        if removable or any(r["removable"] for r in rows):
            print("消すには --clean --apply を付けて打ち直す")
        return 0
    for r in (r for r in rows if r["removable"]):
        got = clean.remove(r, repo.source, provision.label(repo, r["branch"]), ports.herdr, ports.git)
        print(f"{_where(r)} {'消した' if got['removed'] else '消せなかった'}" + (f": {got['detail']}" if got["detail"] else ""))
        failed += not got["removed"]
    return 1 if failed else 0


if __name__ == "__main__":
    # 前の版の置き場のパスで打たれたら、今入っている版で打ち直す（installed.py）
    hopped = installed.hop(__file__, sys.argv[1:])
    sys.exit(main() if hopped is None else hopped)
