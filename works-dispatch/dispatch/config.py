"""dispatch の設定（TOML）を読む。持ち主の環境の値（アカウント・起動のコマンド・置き場）はここから入り、コードには書かない（設計書 D6）。

置き場は、引数 → 環境変数 WORKS_DISPATCH_CONFIG → ~/.config/works-dispatch/dispatch.toml の順。形は設計書のセクション 5。
知らない鍵は読み飛ばす（前の版の clone_root が残っていても止めない）。
外した鍵のうち、書いた人の思う動きと違ってしまう物（task_cwd）は、止めずに注記（Config.notes）を出して無視する。
アカウントを書かなければ、`claude` 1 つだけのアカウントとして扱う（D7。普通の利用者の環境でもそのまま動く）。
[[repos]] は PR を開く回（pick_repo）にだけ要る。部署の回（--task・--ask・--land・--tree）は、代表の clone の場所から会社を決め
（repo_at）、設定の [[repos]] は gh_user・copy_files などを上書きしたいときだけ書く。second_prompt_file も PR を開く回だけの物で、
書かなければ 2 ターン目の文は空（PR を開く回は始める前の確かめが止める）。
"""

import datetime
import os
import re
import tomllib
import zoneinfo

from ports import chat
from vendor import claude_auth
from typing import NamedTuple

DEFAULT_PATH = "~/.config/works-dispatch/dispatch.toml"
ENV = "WORKS_DISPATCH_CONFIG"
DEFAULT_LIMIT = 95
DEFAULT_RESET_SOON_HOURS = 24  # 週の枠の切り替わりがこの時間以内のアカウントを先に使う（accounts ノード）
DEFAULT_LIMITS_DIR = "~/.cache/claude-limits"
# 区切りで早めに移す（--move --if-changed）目安。今のアカウントの 5 時間か週の枠がこの使用率に達し、その枠が DEFAULT_EARLY_RESET_HOURS より
# 先まで戻らなければ、使用率がこれに届かないほかのアカウントへ移す。limit_percent より手前で、上限に当たってターンの途中で切られる前に移す
DEFAULT_EARLY_PERCENT = 90
DEFAULT_EARLY_RESET_HOURS = 1.0   # 達した枠がこの時間以内に戻るなら移さない（移すと会話の記憶を失い、移る先の週の枠も使う）
# 使える時間帯（アカウントの hours）の終わりのこの分数より手前から、そのアカウントを選ばず、区切りでほかへ移す。終わりで要求が断られ、
# ターンの途中で切られる前に移すため
DEFAULT_HOURS_MARGIN_MINUTES = 30
HOURS_FORM = re.compile(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2}) +(\S+)")
HOURS_EXAMPLE = 'hours = "08:00-16:00 UTC" か hours = "17:00-25:00 Asia/Tokyo"'


class ConfigError(Exception):
    """設定が読めない・形が違う。足りない物を全部 1 つの文にして持つ。"""


class Hours(NamedTuple):
    """アカウントの使える時間帯。毎日 start 分（0 時からの分）から length 分の間。zone は時刻の基準（UTC か IANA の地域の名前）。"""
    start: int
    length: int
    zone: str
    text: str  # 設定に書いた字のまま（表示と訳に使う）


class Account(NamedTuple):
    name: str  # 使用率の控えのファイル名（<limits_dir>/<name>.json）
    command: str  # そのアカウントで Claude Code を起動するシェルのコマンド
    config_dir: str | None = None  # Claude Code の設定のフォルダ。None は既定のフォルダ
    keychain_service: str | None = None  # 鍵を置いた Keychain の項目の名前。None は共通の決まり（scripts/claude_auth.py）で探す
    limits: bool = True  # 使用率の枠があるか。false は Ollama・Foundry のような枠の無いアカウントで、控えを読まず使用率で外さない
    plan: str | None = None  # 持ち主が教えたプラン（例 default_claude_max_20x）。ログインの記録からプランが読めないときだけ limits.plan_of が使う
    hours: Hours | None = None  # 使える時間帯。None は一日中使える。外では部署の起動にも移し先にも選ばない（accounts.rank）


class Repo(NamedTuple):
    repo: str  # OWNER/NAME
    second_prompt: str  # 2 ターン目の文（second_prompt_file の中身）
    source: str  # 元の clone。ブランチごとの worktree はここから作る（置き場は herdr の worktrees.directory）
    copy_files: tuple[str, ...] = ()  # git が追わない手元だけのファイル（リポジトリの中の相対パス）
    copy_from: str | None = None  # copy_files を写す元のフォルダ。None は元の clone
    gh_user: str | None = None  # このリポジトリを読む gh のアカウント。None はその人の今の設定（有効なアカウントか GH_TOKEN）


class Config(NamedTuple):
    limit_percent: int
    limits_dir: str
    accounts: tuple[Account, ...]
    repos: tuple[Repo, ...]
    notes: tuple[str, ...] = ()  # 止めはしないが、書いた人に伝える事（外した鍵が書かれているなど）
    reset_soon_hours: float = DEFAULT_RESET_SOON_HOURS
    early_percent: int = DEFAULT_EARLY_PERCENT
    early_reset_hours: float = DEFAULT_EARLY_RESET_HOURS
    hours_margin_minutes: float = DEFAULT_HOURS_MARGIN_MINUTES


def _path(v):
    return os.path.expanduser(v)


def _str(d, key, where, problems):
    v = d.get(key)
    if not isinstance(v, str) or not v:
        problems.append(f"{where}: {key} が文字列で無い")
        return None
    return v


def zone_of(name):
    """時刻の基準の名前の tzinfo。UTC は地域の表（tzdata）の無い環境〔Windows など〕でも読めるよう、表を引かない。読めなければ None。"""
    if name == "UTC":
        return datetime.timezone.utc
    # 地域の名前（「/」を含み、表にちょうど同じ字で在る物）だけ受ける。EST・Japan のような略や別名は、夏時間の有無などで書き手の思う
    # 基準とずれうる。大文字と小文字の違う名前は、macOS では通り Linux では止まるので、表の字と比べて揃える
    if "/" not in name or name not in zoneinfo.available_timezones():
        return None
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return None   # 表に在っても読めない物は、読めない基準として呼び手が止める


def parse_hours(text):
    """「HH:MM-HH:MM <時刻の基準>」を Hours にする。形が違えば、直し方を添えた訳の文（str）を返す。
    時刻の基準は書き落としを許さない（日本時間か UTC かを書き手が取り違えないため）。終わりが始まり以下か 24:00 を超えれば、翌日にまたぐ。"""
    m = HOURS_FORM.fullmatch(text.strip()) if isinstance(text, str) else None
    if not m:
        return f"hours が「HH:MM-HH:MM <時刻の基準>」の形で無い（時刻の基準は UTC か Asia/Tokyo などの地域の名前を必ず書く。例 {HOURS_EXAMPLE}）"
    sh, sm, eh, em, zone = int(m[1]), int(m[2]), int(m[3]), int(m[4]), m[5]
    if sh > 23 or sm > 59 or em > 59 or eh > 48:
        return f"hours の時刻が範囲の外（始まりは 00:00〜23:59、終わりは 48:00 まで。例 {HOURS_EXAMPLE}）"
    start, end = sh * 60 + sm, eh * 60 + em
    length = end - start if end > start else end + 24 * 60 - start if end < start else 0   # 同じ時刻は長さ 0（一日中は 00:00-24:00）
    if not 0 < length <= 24 * 60:
        return f"hours の長さが 0 分か 24 時間を超える（例 {HOURS_EXAMPLE}）"
    if zone_of(zone) is None:
        if not zoneinfo.available_timezones():
            return f"hours の時刻の基準 {zone} を読めない（この機械には地域の時刻の表〔tzdata〕が無いので、UTC で書く）"
        return f"hours の時刻の基準 {zone} を読めない（UTC か Asia/Tokyo などの IANA の地域の名前を書く。JST・EST のような略は読まない）"
    return Hours(start, length, zone, text.strip())


def path_of(path=None, env=os.environ):
    """設定のファイルの場所。引数 → 環境変数 WORKS_DISPATCH_CONFIG → 既定の順。"""
    return _path(path or env.get(ENV) or DEFAULT_PATH)


def load(path=None, env=os.environ, missing_ok=False):
    """missing_ok が真なら、設定のファイルが無いときに、何も書いていない設定（既定の値・アカウント 1 つ・repos 無し）を返す（部署の回）。"""
    path = path_of(path, env)
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        if missing_ok:
            raw = {}
        else:
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
    soon = raw.get("reset_soon_hours", DEFAULT_RESET_SOON_HOURS)
    if not isinstance(soon, (int, float)) or isinstance(soon, bool) or soon < 0:
        problems.append("reset_soon_hours が 0 以上の数で無い")
        soon = DEFAULT_RESET_SOON_HOURS
    early = raw.get("move_early_percent", DEFAULT_EARLY_PERCENT)
    if not isinstance(early, int) or isinstance(early, bool):
        problems.append("move_early_percent が整数で無い")
        early = DEFAULT_EARLY_PERCENT
    early_hours = raw.get("move_early_reset_hours", DEFAULT_EARLY_RESET_HOURS)
    if not isinstance(early_hours, (int, float)) or isinstance(early_hours, bool) or early_hours < 0:
        problems.append("move_early_reset_hours が 0 以上の数で無い")
        early_hours = DEFAULT_EARLY_RESET_HOURS
    margin = raw.get("hours_margin_minutes", DEFAULT_HOURS_MARGIN_MINUTES)
    if not isinstance(margin, (int, float)) or isinstance(margin, bool) or margin < 0:
        problems.append("hours_margin_minutes が 0 以上の数で無い")
        margin = DEFAULT_HOURS_MARGIN_MINUTES

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
        service = a.get("keychain_service")
        if service is not None and not isinstance(service, str):
            problems.append(f"{where}: keychain_service が文字列で無い")
            service = None
        has_limits = a.get("limits", True)
        if not isinstance(has_limits, bool):
            problems.append(f"{where}: limits が true か false で無い")
            has_limits = True
        plan = a.get("plan")
        if plan is not None and (not isinstance(plan, str) or not re.fullmatch(r"[a-z0-9_]+", plan)):
            problems.append(f"{where}: plan がログインの記録と同じ形（英小文字・数字・_ の語。例 default_claude_max_20x）で無い")
            plan = None
        elif plan is not None and not has_limits:
            problems.append(f"{where}: limits = false のアカウントにはプランが無いので、plan は書かない")
            plan = None
        hours = a.get("hours")
        if hours is not None:
            hours = parse_hours(hours)
            if isinstance(hours, str):
                problems.append(f"{where}: {hours}")
                hours = None
        if hours is not None and hours.length < 24 * 60 and margin >= hours.length:
            problems.append(f"{where}: hours_margin_minutes（{margin:g} 分）が hours の長さ以上なので、このアカウントは一度も選ばれない")
        accounts.append(Account(name, command, _path(cdir) if cdir else None, service or None, has_limits, plan, hours))
    if not raw.get("accounts"):
        accounts = [Account("default", chat.COMMAND, None)]

    repos, notes = [], []
    for i, r in enumerate(raw.get("repos", [])):
        where = f"repos[{i}]"
        name = _str(r, "repo", where, problems)
        pfile = r.get("second_prompt_file")
        prompt = ""
        if pfile is not None and not (isinstance(pfile, str) and pfile):
            problems.append(f"{where}: second_prompt_file が文字列で無い")
        elif pfile:
            try:
                with open(_path(pfile), encoding="utf-8") as f:
                    prompt = f.read()
            except OSError as e:
                problems.append(f"{where}: second_prompt_file を読めない: {_path(pfile)}（{e.strerror}）")
        source = _str(r, "source", where, problems)
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
        if "task_cwd" in r:
            # サブエージェントは自分の作業場で起動する（その会社の AGENTS.md・CLAUDE.md とフックを効かせるため。会社の形の設計 4.1）
            notes.append(f"{where}（{name}）: task_cwd は使わなくなったので無視した（サブエージェントは自分の作業場で起動する）。設定から消してよい")
        repos.append(Repo(name, prompt, _path(source) if source else None, tuple(copy),
                          _path(copy_from) if copy_from else None, gh_user or None))
    if problems:
        raise ConfigError(f"設定の形が違う（{path}）: " + "／".join(problems))
    return Config(limit, _path(limits_dir), tuple(accounts), tuple(repos), tuple(notes), soon, early, early_hours, margin)


def pick_repo(cfg, name):
    """名前（OWNER/NAME）か代表の clone のパスの repo を返す。名前が None なら設定の最初の repo。PR を開く回の選び方。"""
    if not cfg.repos:
        raise ConfigError("設定に [[repos]] が 1 つも無い（PR を開く回には要る。python3 dispatch.py --init --repo OWNER/NAME "
                          "--source <代表の clone> で下書きを作る）")
    if name is None:
        return cfg.repos[0]
    for r in cfg.repos:
        if r.repo == name:
            return r
    for r in cfg.repos:
        if r.source and os.path.realpath(_path(name)) == os.path.realpath(r.source):
            return r
    raise ConfigError(f"設定の repos に {name} が無い（OWNER/NAME か、source に書いた代表の clone のパスで指す）")


def repo_at(cfg, root, origin):
    """代表の clone のルート root の repo。設定の [[repos]] に source がそのルートの物が有ればそれ、無ければそのルートを代表の clone とする
    最小の repo（名前は origin の OWNER/NAME、無ければフォルダの名前。gh_user などは会社の形から読む）。部署の回の選び方。"""
    for r in cfg.repos:
        if r.source and os.path.realpath(r.source) == os.path.realpath(root):
            return r
    return Repo(origin(root) or os.path.basename(os.path.normpath(root)), "", root)


def copy_root(repo):
    """copy_files を写す元のフォルダ。copy_from が無ければ元の clone。"""
    return repo.copy_from or repo.source


def effective_config_dir(account, env=os.environ):
    """そのアカウントの Claude Code の設定のフォルダ。設定に書かなければ、利用者の CLAUDE_CONFIG_DIR、無ければ ~/.claude。

    アカウントを切り替えない人は config_dir を書かない。その人の Claude Code がふだん使うフォルダを、そのまま指す。
    決め方の正本はリポジトリ直下の scripts/claude_auth.py の config_dir で、ここは写し（vendor/claude_auth.py）を呼ぶだけ。
    """
    if account.config_dir:
        return account.config_dir
    return claude_auth.config_dir(env)
