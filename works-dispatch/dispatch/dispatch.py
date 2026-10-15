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

使い方: python3 dispatch.py [--config <パス>] [--repo OWNER/NAME] [--pr N ... | --issue N] [--no-second] [--dry-run | --clean [--apply]]
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
import time
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import claudex  # noqa: E402
import config  # noqa: E402
import ghx  # noqa: E402
import gitx  # noqa: E402
import herdr  # noqa: E402
import limits  # noqa: E402
import vscode  # noqa: E402
from nodes import accounts, assign, clean, cost, fresh, launch, provision, prs, report, sessions, turn  # noqa: E402

# Windows の既定の標準入出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

# 手元の herdr の API に要るメソッド（herdr の文書は、手元の版の API を api schema で確かめるよう求めている）
HERDR_METHODS = {"agent.prompt", "agent.get", "agent.wait", "pane.list", "pane.send_text", "workspace.list", "workspace.close",
                 "worktree.list", "worktree.create", "worktree.open", "worktree.remove"}


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


def _gh_ok(repo, env=None):
    """gh がそのリポジトリを読めるか。ログインしていても、有効なアカウントが読めないリポジトリはある。"""
    try:
        return subprocess.run(["gh", "repo", "view", repo, "--json", "name"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env).returncode == 0
    except FileNotFoundError:
        return False


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


class Ports:
    """外への口を 1 つに束ねる。試験は同じ名前の口を持つ偽物を渡す。書く口は herdr のモジュールそのもので、launch と turn だけが使う。"""

    def __init__(self, herdr_methods=None, shell_has=None, gh_ok=None, env=None, gh_env=None, herdr_integration=None,
                 login_config_dir=None, worktrees=None):
        self._herdr_methods = herdr_methods or herdr.methods
        self._herdr_integration = herdr_integration or (lambda cdir: herdr.claude_integration(cdir, dict(self.env)))
        self._login_config_dir = login_config_dir or (lambda: _login_config_dir(self.env))
        self._account_env = None
        self._shell_has = shell_has or _shell_has
        self._gh_ok = gh_ok or _gh_ok
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

    def preflight(self, cfg):
        problems, notes = [], []
        try:
            missing = HERDR_METHODS - self._herdr_methods()
            if missing:
                problems.append(f"手元の herdr の API に {', '.join(sorted(missing))} が無い（herdr の版を確かめる）")
        except (herdr.HerdrError, OSError, ValueError) as e:
            problems.append(f"herdr に届かない: {e}")
        for repo in cfg.repos:
            if not (repo.second_prompt or "").strip():
                problems.append(f"{repo.repo}: 2 ターン目の文が空")
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
                             f"herdr を立ち上げ直したときに会話を戻すのに要る。入れる: CLAUDE_CONFIG_DIR={cdir} herdr integration install claude）")
            found = claudex.catchup_commands(cdir)
            if len(found) != 1:
                problems.append(f"アカウント {a.name}（{cdir}）で /catchup の命令が 1 つに決まらない"
                                f"（commands/catchup.md を持つプラグイン: {', '.join(found) or '無し'}）")
            for repo in cfg.repos:
                if not claudex.is_trusted(claudex.trust_file(a.config_dir, self.account_env), repo.source):
                    notes.append(f"アカウント {a.name} は {repo.source} を信頼していない（枝ごとの作業場で毎回フォルダの信頼の確認が出る。"
                                 f"一度 {repo.source} で {a.command} を起こし、信頼すると出なくなる）")
            if a.limits and not (pathlib.Path(cfg.limits_dir) / f"{a.name}.json").is_file():
                notes.append(f"アカウント {a.name} の使用率の控えが無い（使用率が分からないものとして順の最後に置く）")
        home = self.env.get("HOME") or os.path.expanduser("~")
        herdr_toml = pathlib.Path(self.env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")) / "herdr" / "config.toml"
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
                problems.append(f"{repo.repo}: {e}")
                continue
            if not self._gh_ok(repo.repo, env):
                problems.append(f"gh が {repo.repo} を読めない。whose-turn が自分の番の PR を集められない"
                                "（gh auth status で、このリポジトリを読めるアカウントが有効かを確かめる）")
        return problems, notes

    def fetch_prs(self, repo):
        return prs.read(repo.repo, env=self.gh_env(repo))

    def list_sessions(self, config_dir):
        return claudex.sessions(config_dir, base_env=self.account_env)

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
        return ghx.default_branch(repo.repo, env=self.gh_env(repo))

    def read_limits(self, limits_dir, names):
        return accounts.read_limits(limits_dir, names)

    def refresh_limits(self, cfg, names):
        """名指したアカウントの使用率を、控えの古さに依らず API に問い合わせて取り直す（出力 0 トークン。失敗は probe.log）。"""
        limits.probe_all([a for a in cfg.accounts if a.name in names], cfg.limits_dir, self.env, self.now(), force=True)

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

    def trust(self, account, source, clone):
        """元の clone を信頼済みのアカウントなら、枝の場所（worktree）にも信頼の印を付ける（claudex.inherit_trust）。"""
        return claudex.inherit_trust(claudex.trust_file(account.get("config_dir"), self.account_env), source, clone)

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
    ap.add_argument("--dry-run", action="store_true", help="割り振りの案までを決めて報告し、何も起こさない")
    ap.add_argument("--pr", type=int, action="append", metavar="N",
                    help="自分の番の一覧を使わず、この番号の PR だけを開く（繰り返して複数）")
    ap.add_argument("--issue", type=int, metavar="N",
                    help="この issue に結んだ枝の場所を開き（無ければ枝を作って結ぶ）、/catchup N まで送って止める")
    ap.add_argument("--no-second", action="store_true", help="2 ターン目の文を送らず、/catchup だけで止める")
    ap.add_argument("--init", action="store_true", help="設定の下書きを書く（--repo と --source が要る。有れば上書きしない）")
    ap.add_argument("--source", help="--init と一緒に: そのリポジトリの代表の clone")
    ap.add_argument("--check", action="store_true", help="始める前の確かめだけを走らせ、足りない物と直し方を出す")
    ap.add_argument("--clean", action="store_true", help="元の clone の worktree のうち消してよいものを並べる")
    ap.add_argument("--apply", action="store_true", help="--clean と一緒に: 並べたものを本当に消す")
    a = ap.parse_args(argv)
    ports = ports or Ports()
    if a.init:
        return _init(a, ports)

    try:
        cfg = config.load(a.config, os.environ)
        repo = config.pick_repo(cfg, a.repo)
    except config.ConfigError as e:
        print(f"止めた: {e}")
        return 2
    if a.apply and not a.clean:
        print("止めた: --apply は --clean と一緒にだけ使う")
        return 2
    if a.issue is not None and a.pr:
        print("止めた: --issue と --pr は一緒に使えない（1 回に 1 つの入口）")
        return 2
    if a.clean:
        return _clean(cfg, repo, a.apply, ports)
    if a.check:
        return _check(cfg, ports)
    problems, notes = ports.preflight(cfg)
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
    # 自分が作者でレビュアーの付いていない PR は、一覧からは開かない（--pr で指したものは開く）
    held, acts = [], {}
    if listing:
        kept = []
        for p in my_prs:
            if p.get("role") == "implementer":
                try:
                    acts[p["number"]] = ports.activity(repo, p["number"])
                except ghx.GhError as e:
                    notes.append(f"#{p['number']}: {e}（レビュアーの有無が分からないので開く）")
                if p["number"] in acts and fresh.own_unreviewed(p, acts[p["number"]]):
                    held.append(_held_row(p, "own_unreviewed", places))
                    continue
            kept.append(p)
        my_prs = kept
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
    ranked = accounts.rank(cfg.accounts, before, cfg.limit_percent, ports.now())
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
                except ghx.GhError as e:
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
                trusted = ports.trust(r["account"], repo.source, prov["path"])
            except OSError as e:
                trusted = f"書けない（{e}）"
            if trusted not in ("inherited", "already"):
                notes.append(f"{name}: アカウント {r['account']['name']} は元の clone を信頼していないので、"
                             "Claude Code がフォルダの信頼の確認を出す" if trusted == "source_untrusted" else
                             f"{name}: 信頼の印を付けられない（{trusted}）。Claude Code がフォルダの信頼の確認を出す")
            got = launch.start(r, prov["pane"], ports.herdr)
            if got["status"] == "ready":
                ready.append((r, prov["pane"]))
            else:
                results[r["number"]] = got["status"]
                notes.append(f"{name}: {got['detail']}")
        # issue から始めたものは 1 ターン目の /catchup まで（2 ターン目の文は PR のレビューの文なので送らない）
        second = {r["number"]: None if (a.no_second or r["kind"] == "issue") else repo.second_prompt for r, _ in ready}
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


def _check(cfg, ports):
    problems, notes = ports.preflight(cfg)
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
    local = [f for f in ports.git.ignored_files(source) if LOCAL_FILE.search(f)]
    second = os.path.join(os.path.dirname(path), "dispatch-second-prompt.md")
    home = ports.env.get("HOME") or os.path.expanduser("~")
    seen = sorted("~/" + n for n in os.listdir(home)
                  if n.startswith(".claude") and os.path.isfile(os.path.join(home, n, "plugins", "installed_plugins.json")))
    q = json.dumps
    lines = [
        "# works の dispatch の設定（--init が書いた下書き）。直したら --check で確かめる。",
        "# 欄の意味: works-dispatch プラグインの README",
        "",
        "limit_percent = 95                      # 週か 5 時間の使用率がこれに達したアカウントは使わない",
        '# limits_dir = "~/.cache/claude-limits"   # アカウントごとの使用率の控え（<name>.json）。無ければ使用率は見ない',
        "",
        "# アカウントを切り替えないなら accounts は書かない（claude を 1 つだけ使う）。",
        "# 切り替えるなら、名前・そのアカウントで Claude Code を起こすコマンド・そのコマンドが CLAUDE_CONFIG_DIR に入れるフォルダを並べる。",
        "# 鍵を自分で決めた名前の Keychain の項目に置いたなら keychain_service、使用率の枠の無いアカウント（Ollama など）は limits = false:",
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


def _clean(cfg, repo, apply, ports):
    try:
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
        found = ports.places(repo)
    except (claudex.ClaudeError, herdr.HerdrError) as e:
        print(f"止めた: {e}（開いている会話か元の clone の worktree を読めないので、何も消さない）")
        return 1
    cwds = {s.get("cwd") for items in listed.values() for s in items if s.get("cwd")}
    rows = clean.candidates(found, lambda b: ports.pr_for_branch(repo, b), cwds, ports.is_clean, ports.stashed, ports.head_sha,
                            source=repo.source, changed=_changed(repo))
    if not rows:
        print(f"元の clone {repo.source} の worktree は無い")
        return 0
    for r in rows:
        mark = "消せる" if r["removable"] else f"残す（{r['reason']}{': ' + ', '.join(r['files']) if r['files'] else ''}）"
        print(f"{_where(r)}  {r['state'] or '-'}  {mark}")
    if not apply:
        if any(r["removable"] for r in rows):
            print("消すには --clean --apply を付けて打ち直す")
        return 0
    failed = 0
    for r in (r for r in rows if r["removable"]):
        got = clean.remove(r, repo.source, provision.label(repo, r["branch"]), ports.herdr, ports.git)
        print(f"{_where(r)} {'消した' if got['removed'] else '消せなかった'}" + (f": {got['detail']}" if got["detail"] else ""))
        failed += not got["removed"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
