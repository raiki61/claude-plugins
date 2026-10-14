"""dispatch の設定（TOML）を読む。持ち主の環境の値（アカウント・起動のコマンド・置き場）はここから入り、コードには書かない（設計書 D6）。

置き場は、引数 → 環境変数 WORKS_DISPATCH_CONFIG → ~/.config/works-dispatch/dispatch.toml の順。形は設計書 5 節。
アカウントを書かなければ、`claude` 1 つだけのアカウントとして扱う（D7。普通の利用者の環境でもそのまま動く）。
"""

import os
import tomllib

from vendor import claude_auth
from typing import NamedTuple

DEFAULT_PATH = "~/.config/works-dispatch/dispatch.toml"
ENV = "WORKS_DISPATCH_CONFIG"
DEFAULT_LIMIT = 95
DEFAULT_LIMITS_DIR = "~/.cache/claude-limits"


class ConfigError(Exception):
    """設定が読めない・形が違う。足りない物を全部 1 つの文にして持つ。"""


class Account(NamedTuple):
    name: str  # 使用率の控えのファイル名（<limits_dir>/<name>.json）
    command: str  # そのアカウントで Claude Code を起こすシェルのコマンド
    config_dir: str | None = None  # Claude Code の設定のフォルダ。None は既定のフォルダ


class Repo(NamedTuple):
    repo: str  # OWNER/NAME
    second_prompt: str  # 2 ターン目の文（second_prompt_file の中身）
    source: str  # 元の clone。PR ごとの clone はここから作る
    clone_root: str  # PR ごとの clone を置く場所
    copy_files: tuple[str, ...] = ()  # git が追わない手元だけのファイル（リポジトリの中の相対パス）
    copy_from: str | None = None  # copy_files を写す元のフォルダ。None は元の clone
    gh_user: str | None = None  # このリポジトリを読む gh のアカウント。None はその人の今の設定（有効なアカウントか GH_TOKEN）


class Config(NamedTuple):
    limit_percent: int
    limits_dir: str
    accounts: tuple[Account, ...]
    repos: tuple[Repo, ...]


def _path(v):
    return os.path.expanduser(v)


def _str(d, key, where, problems):
    v = d.get(key)
    if not isinstance(v, str) or not v:
        problems.append(f"{where}: {key} が文字列で無い")
        return None
    return v


def path_of(path=None, env=os.environ):
    """設定のファイルの場所。引数 → 環境変数 WORKS_DISPATCH_CONFIG → 既定の順。"""
    return _path(path or env.get(ENV) or DEFAULT_PATH)


def load(path=None, env=os.environ):
    path = path_of(path, env)
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"設定のファイルが無い: {path}（python3 dispatch.py --init --repo OWNER/NAME --source <代表の clone> で下書きを作る）")
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"設定のファイルを TOML として読めない: {path}（{e}）")

    problems = []
    limit = raw.get("limit_percent", DEFAULT_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool):
        problems.append("limit_percent が整数で無い")
    limits_dir = raw.get("limits_dir", DEFAULT_LIMITS_DIR)
    if not isinstance(limits_dir, str):
        problems.append("limits_dir が文字列で無い")
        limits_dir = DEFAULT_LIMITS_DIR

    accounts = []
    for i, a in enumerate(raw.get("accounts", [])):
        where = f"accounts[{i}]"
        if not isinstance(a, dict):
            problems.append(f"{where} が表で無い")
            continue
        name, command = _str(a, "name", where, problems), _str(a, "command", where, problems)
        cdir = a.get("config_dir")
        if cdir is not None and not isinstance(cdir, str):
            problems.append(f"{where}: config_dir が文字列で無い")
            cdir = None
        accounts.append(Account(name, command, _path(cdir) if cdir else None))
    if not raw.get("accounts"):
        accounts = [Account("default", "claude", None)]

    repos = []
    for i, r in enumerate(raw.get("repos", [])):
        where = f"repos[{i}]"
        name = _str(r, "repo", where, problems)
        pfile = _str(r, "second_prompt_file", where, problems)
        prompt = None
        if pfile:
            try:
                with open(_path(pfile), encoding="utf-8") as f:
                    prompt = f.read()
            except OSError as e:
                problems.append(f"{where}: second_prompt_file を読めない: {_path(pfile)}（{e.strerror}）")
        source = _str(r, "source", where, problems)
        root = _str(r, "clone_root", where, problems)
        copy = r.get("copy_files", [])
        if not isinstance(copy, list) or not all(isinstance(c, str) for c in copy):
            problems.append(f"{where}: copy_files が文字列の並びで無い")
            copy = []
        copy_from = r.get("copy_from")
        if copy_from is not None and not isinstance(copy_from, str):
            problems.append(f"{where}: copy_from が文字列で無い")
            copy_from = None
        gh_user = r.get("gh_user")
        if gh_user is not None and not isinstance(gh_user, str):
            problems.append(f"{where}: gh_user が文字列で無い")
            gh_user = None
        repos.append(Repo(name, prompt, _path(source) if source else None, _path(root) if root else None, tuple(copy),
                          _path(copy_from) if copy_from else None, gh_user or None))
    if not raw.get("repos"):
        problems.append("repos が 1 つも無い")

    if problems:
        raise ConfigError(f"設定の形が違う（{path}）: " + "／".join(problems))
    return Config(limit, _path(limits_dir), tuple(accounts), tuple(repos))


def pick_repo(cfg, name):
    """名前の repo を返す。名前が None なら設定の最初の repo。"""
    if name is None:
        return cfg.repos[0]
    for r in cfg.repos:
        if r.repo == name:
            return r
    raise ConfigError(f"設定の repos に {name} が無い")


def copy_root(repo):
    """copy_files を写す元のフォルダ。copy_from が無ければ元の clone。"""
    return repo.copy_from or repo.source


def clone_path(repo, number):
    """PR ごとの clone のフォルダ: <clone_root>/<リポジトリの名前>-pr-<番号>。herdr の作業場の名前もこの最後の部分にそろえる。"""
    return os.path.join(repo.clone_root, f"{repo.repo.split('/')[-1]}-pr-{number}")


def effective_config_dir(account, env=os.environ):
    """そのアカウントの Claude Code の設定のフォルダ。設定に書かなければ、利用者の CLAUDE_CONFIG_DIR、無ければ ~/.claude。

    アカウントを切り替えない人は config_dir を書かない。その人の Claude Code がふだん使うフォルダを、そのまま指す。
    決め方の正本はリポジトリ直下の scripts/claude_auth.py の config_dir で、ここは写し（vendor/claude_auth.py）を呼ぶだけ。
    """
    if account.config_dir:
        return account.config_dir
    return claude_auth.config_dir(env)
