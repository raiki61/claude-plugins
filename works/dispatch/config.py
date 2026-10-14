"""dispatch の設定（TOML）を読む。持ち主の環境の値（アカウント・起動のコマンド・置き場）はここから入り、コードには書かない（設計書 D6）。

置き場は、引数 → 環境変数 WORKS_DISPATCH_CONFIG → ~/.config/works/dispatch.toml の順。形は設計書 5 節。
アカウントを書かなければ、`claude` 1 つだけのアカウントとして扱う（D7。普通の利用者の環境でもそのまま動く）。
"""

import os
import tomllib
from typing import NamedTuple

DEFAULT_PATH = "~/.config/works/dispatch.toml"
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
    copy_files: tuple[str, ...] = ()  # git が追わない手元だけのファイル（元の clone からの相対パス）


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


def load(path=None, env=os.environ):
    path = _path(path or env.get(ENV) or DEFAULT_PATH)
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"設定のファイルが無い: {path}（形は works/docs/specs/2026-10-14-catchup-dispatch-design.md の 5 節）")
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
        repos.append(Repo(name, prompt, _path(source) if source else None, _path(root) if root else None, tuple(copy)))
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


def clone_path(repo, number):
    """PR ごとの clone のフォルダ: <clone_root>/<リポジトリの名前>-pr-<番号>。herdr の作業場の名前もこの最後の部分にそろえる。"""
    return os.path.join(repo.clone_root, f"{repo.repo.split('/')[-1]}-pr-{number}")
