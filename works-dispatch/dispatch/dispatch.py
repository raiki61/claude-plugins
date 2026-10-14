#!/usr/bin/env python3
"""自分の番の PR ごとに作業場（元の clone から作る clone と herdr の作業場）を用意し、選んだアカウントの Claude Code で起こし、
1 ターン目に `/catchup <番号>`、2 ターン目に設定の文を送る。AI は使わない（設計書 works-dispatch/docs/specs/2026-10-14-catchup-dispatch-design.md）。

流れ（どのノードの次に何を呼ぶか）を持つのはこのファイルだけ。ノードは流れを知らない（D3）。
1. 始める前の確かめ。足りない物があれば全部並べて、何も起こさずに終了の値 2 で止まる
2. prs → sessions → accounts → assign（ここまで外には書かない。--dry-run はここで、作業場を作るか使い直すかを報告して終える）
3. provision・信頼の印（元の clone を信頼済みのアカウントなら clone にも付ける）・launch を PR ごとに順に全部先に済ませ、turn を PR ごとに並べて走らせる（1 件の /catchup が長くても、ほかが遅れない）
4. report
止まっている（blocked）・会話が開いている（already_open）などは誤りではないので、終了の値は 0。

片付け（--clean）は、PR ごとの clone のうち消してよいものを並べるだけで、--apply を付けた時だけ消す（nodes/clean.py）。

--pr N は自分の番の一覧（whose-turn）を使わず、指した PR だけを開く。止めている実装や、見に行くだけの PR に使う。
--no-second は 2 ターン目の文を送らず、/catchup だけで止める。

使い方: python3 dispatch.py [--config <パス>] [--repo OWNER/NAME] [--pr N ...] [--no-second] [--dry-run | --clean [--apply]]
"""

import argparse
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
from nodes import accounts, assign, clean, launch, provision, prs, report, sessions, turn  # noqa: E402

# Windows の既定の標準入出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

# 手元の herdr の API に要るメソッド（herdr の文書は、手元の版の API を api schema で確かめるよう求めている）
HERDR_METHODS = {"agent.prompt", "agent.get", "agent.wait", "pane.list", "pane.send_text", "workspace.list", "workspace.create"}


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
                 login_config_dir=None):
        self._herdr_methods = herdr_methods or herdr.methods
        self._herdr_integration = herdr_integration or (lambda cdir: herdr.claude_integration(cdir, dict(self.env)))
        self._login_config_dir = login_config_dir or (lambda: _login_config_dir(self.env))
        self._account_env = None
        self._shell_has = shell_has or _shell_has
        self._gh_ok = gh_ok or _gh_ok
        self.env = os.environ if env is None else env
        self._gh_env = gh_env
        self._gh_envs = {}
        self.herdr = herdr
        self.git = gitx

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
                    notes.append(f"アカウント {a.name} は {repo.source} を信頼していない（PR ごとの作業場で毎回フォルダの信頼の確認が出る。"
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
            if not os.path.isdir(repo.clone_root):
                problems.append(f"{repo.repo}: clone を置く場所 {repo.clone_root} が無い")
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

    def pr_state(self, repo, number):
        try:
            return ghx.pr_state(repo.repo, number, env=self.gh_env(repo))
        except ghx.GhError:
            return None  # 読めないものは消さない側に倒す

    def read_limits(self, limits_dir, names):
        return accounts.read_limits(limits_dir, names)

    def catchup_command(self, config_dir):
        """そのアカウントで送る catchup の命令の名前。始める前の確かめで 1 つに決まることを見てある。"""
        cdir = config.effective_config_dir(config.Account("", "", config_dir), self.account_env)
        found = claudex.catchup_commands(cdir)
        return found[0] if len(found) == 1 else None

    def trust(self, account, source, clone):
        """元の clone を信頼済みのアカウントなら、clone にも信頼の印を付ける（claudex.inherit_trust）。"""
        return claudex.inherit_trust(claudex.trust_file(account.get("config_dir"), self.account_env), source, clone)

    def now(self):
        return time.time()


def main(argv=None, ports=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--dry-run", action="store_true", help="割り振りの案までを決めて報告し、何も起こさない")
    ap.add_argument("--pr", type=int, action="append", metavar="N",
                    help="自分の番の一覧を使わず、この番号の PR だけを開く（繰り返して複数）")
    ap.add_argument("--no-second", action="store_true", help="2 ターン目の文を送らず、/catchup だけで止める")
    ap.add_argument("--init", action="store_true", help="設定の下書きを書く（--repo と --source が要る。有れば上書きしない）")
    ap.add_argument("--source", help="--init と一緒に: そのリポジトリの代表の clone")
    ap.add_argument("--check", action="store_true", help="始める前の確かめだけを走らせ、足りない物と直し方を出す")
    ap.add_argument("--clean", action="store_true", help="PR ごとの clone のうち消してよいものを並べる")
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
    if a.clean:
        return _clean(cfg, repo, a.apply, ports)
    if a.check:
        return _check(cfg, ports)
    problems, notes = ports.preflight(cfg)
    if problems:
        print("止めた（始める前の確かめで足りない物）:")
        print("\n".join(f"- {p}" for p in problems))
        return 2

    try:
        my_prs = [ports.pr_info(repo, n) for n in a.pr] if a.pr else ports.fetch_prs(repo)
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
    except (prs.PrsError, claudex.ClaudeError, ghx.GhError) as e:
        print(f"止めた: {e}")
        return 1
    sess = sessions.collect(listed, ports.branch, ports.origin)
    ranked = accounts.rank(cfg.accounts, ports.read_limits(cfg.limits_dir, [x.name for x in cfg.accounts if x.limits]),
                           cfg.limit_percent, ports.now())
    the_plan = assign.plan(repo, my_prs, sessions.open_keys(sess), {s["cwd"] for s in sess if s["cwd"]}, ranked)

    results = {}
    assigned = [r for r in the_plan if r["outcome"] == "assigned"]
    if a.dry_run:
        results = {r["number"]: provision.would(repo, r["number"]) for r in assigned}
    else:
        ready = []
        for r in assigned:
            prov = provision.prepare(r, repo, ports.herdr, ports.git)
            if prov["detail"]:
                notes.append(f"#{r['number']}: {prov['detail']}")
            if prov["status"] != "ready":
                results[r["number"]] = "provision_failed"
                continue
            try:
                trusted = ports.trust(r["account"], repo.source, prov["path"])
            except OSError as e:
                trusted = f"書けない（{e}）"
            if trusted not in ("inherited", "already"):
                notes.append(f"#{r['number']}: アカウント {r['account']['name']} は元の clone を信頼していないので、"
                             "Claude Code がフォルダの信頼の確認を出す" if trusted == "source_untrusted" else
                             f"#{r['number']}: 信頼の印を付けられない（{trusted}）。Claude Code がフォルダの信頼の確認を出す")
            got = launch.start(r, prov["pane"], ports.herdr)
            if got["status"] == "ready":
                ready.append((r, prov["pane"]))
            else:
                results[r["number"]] = got["status"]
                notes.append(f"#{r['number']}: {got['detail']}")
        if ready:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(ready)) as pool:
                futures = {r["number"]: pool.submit(turn.catchup_then_second, r["number"], pane,
                                                    None if a.no_second else repo.second_prompt, ports.herdr,
                                                    catchup=ports.catchup_command(r["account"].get("config_dir")))
                           for r, pane in ready}
                results.update({n: f.result() for n, f in futures.items()})

    print("\n".join(report.lines(the_plan, results, notes)))
    return 0


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
        f"source = {q(source)}   # 代表の clone。PR ごとの clone はここから作る",
        f"clone_root = {q(os.path.dirname(source))}   # PR ごとの clone を置く場所（<clone_root>/<名前>-pr-<番号>）",
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
    listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
    cwds = {s.get("cwd") for items in listed.values() for s in items if s.get("cwd")}
    root = repo.clone_root
    folders = [os.path.join(root, n) for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    rows = clean.candidates(repo, folders, lambda n: ports.pr_state(repo, n), cwds, ports.is_clean, ports.unpushed,
                            origin=ports.origin)
    if not rows:
        print("PR ごとの clone は無い")
        return 0
    for r in rows:
        mark = "消せる" if r["removable"] else f"残す（{r['reason']}）"
        print(f"#{r['number']} {os.path.basename(r['path'])}  {r['state'] or '-'}  {mark}")
    if not apply:
        if any(r["removable"] for r in rows):
            print("消すには --clean --apply を付けて打ち直す")
        return 0
    for r in (r for r in rows if r["removable"]):
        got = clean.remove(r, ports.herdr)
        print(f"#{r['number']} {'消した' if got['removed'] else '消せなかった: ' + (got['detail'] or '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
