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


class Slot(NamedTuple):
    workspace: str  # herdr の workspace の名前
    path: str  # その作業場の clone のパス


class Repo(NamedTuple):
    repo: str  # OWNER/NAME
    second_prompt: str  # 2 ターン目の文（second_prompt_file の中身）
    slots: tuple[Slot, ...]


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
        slots = []
        raw_slots = r.get("slots")
        if not isinstance(raw_slots, list):
            problems.append(f"{where}: slots が並びで無い")
            raw_slots = []
        for j, s in enumerate(raw_slots):
            w = f"{where}.slots[{j}]"
            if not isinstance(s, dict):
                problems.append(f"{w} が表で無い")
                continue
            ws, sp = _str(s, "workspace", w, problems), _str(s, "path", w, problems)
            if ws and sp:
                slots.append(Slot(ws, _path(sp)))
        repos.append(Repo(name, prompt, tuple(slots)))
    if not raw.get("repos"):
        problems.append("repos が 1 つも無い")

    if problems:
        raise ConfigError(f"設定の形が違う（{path}）: " + "／".join(problems))
    return Config(limit, _path(limits_dir), tuple(accounts), tuple(repos))
