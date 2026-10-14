#!/usr/bin/env python3
"""自分の番の PR ごとに作業場（元の clone から作る clone と herdr の作業場）を用意し、選んだアカウントの Claude Code で起こし、
1 ターン目に `/catchup <番号>`、2 ターン目に設定の文を送る。AI は使わない（設計書 works/docs/specs/2026-10-14-catchup-dispatch-design.md）。

流れ（どのノードの次に何を呼ぶか）を持つのはこのファイルだけ。ノードは流れを知らない（D3）。
1. 始める前の確かめ。足りない物があれば全部並べて、何も起こさずに終了の値 2 で止まる
2. prs → sessions → accounts → assign（ここまで外には書かない。--dry-run はここで、作業場を作るか使い直すかを報告して終える）
3. provision と launch を PR ごとに順に全部先に済ませ、turn を PR ごとに並べて走らせる（1 件の /catchup が長くても、ほかが遅れない）
4. report
止まっている（blocked）・会話が開いている（already_open）などは誤りではないので、終了の値は 0。

片付け（--clean）は、PR ごとの clone のうち消してよいものを並べるだけで、--apply を付けた時だけ消す（nodes/clean.py）。

使い方: python3 dispatch.py [--config <パス>] [--repo OWNER/NAME] [--dry-run | --clean [--apply]]
"""

import argparse
import concurrent.futures
import json
import os
import pathlib
import shlex
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import claudex  # noqa: E402
import config  # noqa: E402
import ghx  # noqa: E402
import gitx  # noqa: E402
import herdr  # noqa: E402
from nodes import accounts, assign, clean, launch, provision, prs, report, sessions, turn  # noqa: E402

# 手元の herdr の API に要るメソッド（herdr の文書は、手元の版の API を api schema で確かめるよう求めている）
HERDR_METHODS = {"agent.prompt", "agent.get", "agent.wait", "pane.list", "pane.send_text", "workspace.list", "workspace.create"}


def _shell_has(cmd):
    """作業場と同じ種類のシェル（利用者のログインのシェル）で、そのコマンドが見つかるか。シェルの関数も数える。"""
    shell = os.environ.get("SHELL") or "/bin/sh"
    p = subprocess.run([shell, "-ic", f"command -v {shlex.quote(cmd)}"], capture_output=True, text=True)
    return p.returncode == 0


def _gh_ok():
    try:
        return subprocess.run(["gh", "auth", "status"], capture_output=True, text=True).returncode == 0
    except FileNotFoundError:
        return False


def _has_attention(config_dir):
    p = pathlib.Path(config_dir) / "plugins" / "installed_plugins.json"
    try:
        names = json.loads(p.read_text(encoding="utf-8")).get("plugins", {})
    except (OSError, ValueError, AttributeError):
        return False
    return any(str(k).startswith("attention@") for k in names)


class Ports:
    """外への口を 1 つに束ねる。試験は同じ名前の口を持つ偽物を渡す。書く口は herdr のモジュールそのもので、launch と turn だけが使う。"""

    def __init__(self, herdr_methods=None, shell_has=None, gh_ok=None, env=None):
        self._herdr_methods = herdr_methods or herdr.methods
        self._shell_has = shell_has or _shell_has
        self._gh_ok = gh_ok or _gh_ok
        self.env = os.environ if env is None else env
        self.herdr = herdr
        self.git = gitx

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
            cdir = config.effective_config_dir(a, self.env)
            if not _has_attention(cdir):
                problems.append(f"アカウント {a.name}（{cdir}）に attention プラグインが入っていない（/catchup が無い）")
            if not (pathlib.Path(cfg.limits_dir) / f"{a.name}.json").is_file():
                notes.append(f"アカウント {a.name} の使用率の控えが無い（使用率が分からないものとして順の最後に置く）")
        for repo in cfg.repos:
            if gitx.origin_repo(repo.source) != repo.repo:
                problems.append(f"{repo.repo}: 元の clone {repo.source} が、このリポジトリの clone でない")
            if not os.path.isdir(repo.clone_root):
                problems.append(f"{repo.repo}: clone を置く場所 {repo.clone_root} が無い")
            for rel in repo.copy_files:
                if not os.path.isfile(os.path.join(config.copy_root(repo), rel)):
                    notes.append(f"{repo.repo}: 写すファイルが {config.copy_root(repo)} に無い: {rel}")
        if not self._gh_ok():
            problems.append("gh が使えない（gh auth status が失敗）。whose-turn が GitHub を読めない")
        return problems, notes

    def fetch_prs(self, repo):
        return prs.read(repo)

    def list_sessions(self, config_dir):
        return claudex.sessions(config_dir)

    def branch(self, cwd):
        return gitx.branch(cwd)

    def origin(self, cwd):
        return gitx.origin_repo(cwd)

    def is_clean(self, cwd):
        return gitx.is_clean(cwd)

    def unpushed(self, cwd):
        return gitx.unpushed(cwd)

    def pr_state(self, repo, number):
        return ghx.pr_state(repo, number)

    def read_limits(self, limits_dir, names):
        return accounts.read_limits(limits_dir, names)

    def now(self):
        return time.time()


def main(argv=None, ports=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--dry-run", action="store_true", help="割り振りの案までを決めて報告し、何も起こさない")
    ap.add_argument("--clean", action="store_true", help="PR ごとの clone のうち消してよいものを並べる")
    ap.add_argument("--apply", action="store_true", help="--clean と一緒に: 並べたものを本当に消す")
    a = ap.parse_args(argv)
    ports = ports or Ports()

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
    problems, notes = ports.preflight(cfg)
    if problems:
        print("止めた（始める前の確かめで足りない物）:")
        print("\n".join(f"- {p}" for p in problems))
        return 2

    my_prs = ports.fetch_prs(repo.repo)
    listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
    sess = sessions.collect(listed, ports.branch, ports.origin)
    ranked = accounts.rank(cfg.accounts, ports.read_limits(cfg.limits_dir, [x.name for x in cfg.accounts]),
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
            got = launch.start(r, prov["pane"], ports.herdr)
            if got["status"] == "ready":
                ready.append((r, prov["pane"]))
            else:
                results[r["number"]] = "launch_failed"
                notes.append(f"#{r['number']}: {got['detail']}")
        if ready:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(ready)) as pool:
                futures = {r["number"]: pool.submit(turn.catchup_then_second, r["number"], pane,
                                                    repo.second_prompt, ports.herdr) for r, pane in ready}
                results.update({n: f.result() for n, f in futures.items()})

    print("\n".join(report.lines(the_plan, results, notes)))
    return 0


def _clean(cfg, repo, apply, ports):
    listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
    cwds = {s.get("cwd") for items in listed.values() for s in items if s.get("cwd")}
    root = repo.clone_root
    folders = [os.path.join(root, n) for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    rows = clean.candidates(repo, folders, lambda n: ports.pr_state(repo.repo, n), cwds, ports.is_clean, ports.unpushed)
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
