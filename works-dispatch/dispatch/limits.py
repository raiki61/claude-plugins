#!/usr/bin/env python3
"""アカウントごとの使用率の控え（<limits_dir>/<アカウント名>.json）を作り、読んで 1 行にする。dispatch はこの控えでアカウントを選ぶ。

控えの形: {"five_hour": {used_percentage, resets_at, updated_at}, "seven_day": {...}, "updated_at", "source"?}
アカウントの数と名前は dispatch の設定（accounts）から読む。1 つでも 7 つでも同じに動く。
使用率の枠の無いアカウント（limits = false。Ollama・Foundry など）は、取り直しも表示もしない。

書き手は 2 つある。
- probe: 控えが古い・欠けているアカウントだけ、Haiku に出力 0 トークンの要求を 1 回投げ、応答ヘッダ
  anthropic-ratelimit-unified-{5h,7d}-* を読む。Claude Code 自身が rate_limits を作るのと同じヘッダ。
  入力は 8 トークンほどで、出力は 0。
- record: Claude Code の statusline に渡る JSON の rate_limits を取り込む。使っているアカウントの 5 時間の枠がすぐ動く。

使い方:
  python3 limits.py [--config <パス> | --accounts <写し>] show <名前>   … 控えを読んで 1 行出す（herdr のタブバーが呼ぶ）
  python3 limits.py [--config <パス> | --accounts <写し>] probe         … 取り直しが要るアカウントだけ API に問い合わせる
  python3 limits.py [--config <パス> | --accounts <写し>] record        … statusline の JSON を標準入力から読んで控えに取り込む
  python3 limits.py [--config <パス>] herdr-config  … アカウントの写しと版に依らない入口を書き、herdr の config.toml の [ui] に置く
                                                    tab_bar_right を出す
  python3 limits.py [--config <パス>] plan [--json] … アカウントごとの契約の段（Max 20x など）を出す。引けないアカウントは理由を出す

アカウントの写し（<limits_dir>/accounts.json）は、herdr-config が dispatch の設定から書く JSON。herdr のタブバーから呼ぶ道は
設定の TOML を読まずにこれを読む。herdr がタブバーのコマンドに渡す PATH の python3 は、macOS では OS に付いてくる 3.9 のことがあり、
TOML を読む tomllib（3.11 から）が無いため。タブバーから呼ぶ道（このファイルと vendor/claude_auth.py）は 3.9 の文法で書く。

タブバーの行は、版ごとのフォルダのこのファイルでなく、herdr-config が limits_dir に写した入口（limits_entry.py。起動のたびに
今入っている版のこのファイルを探して起動する）を指す。プラグインを上げても行を書き直さなくてよい。

こちらからは打ち切らない。herdr のタブバーから呼ぶときは、herdr の設定の秒（雛形 templates/herdr-tab-bar.toml）が打ち切る。
"""

import argparse
import collections
import datetime
import http.client
import json
import math
import os
import pathlib
import shlex
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import filex  # noqa: E402
from vendor import claude_auth  # noqa: E402

# 写しから読んだアカウント。dispatch の設定の Account と同じ名前のフィールドを持つ（config は tomllib を引くので、ここでは import しない）
Snap = collections.namedtuple("Snap", "name command config_dir keychain_service limits")
SNAPSHOT_NAME = "accounts.json"

# Windows の既定の標準入出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE / "templates" / "herdr-tab-bar.toml"
PICKER = HERE.parent / "hooks" / "run-python.sh"   # Python を選ぶ入口（フックと同じ決まり。Store へ誘う代わりの物を飛ばす）
ENTRY = HERE / "limits_entry.py"   # タブバーが呼ぶ、版に依らない入口（herdr-config が limits_dir に写す）
# herdr-config が limits_dir に写すファイル: 写した先の名前 → プラグインの中の元
ENTRY_COPIES = {"limits-entry.py": ENTRY, "run-python.sh": PICKER}

# 取り直しの間隔（分）。使っていないアカウントの値は claude.ai など外で使わない限り動かないので、5 時間の枠は長く取る。
# 7 日の枠は statusline が大きさで採らず（放置した会話の古い高い値が今の値を潰すため）、書き手が probe だけなので短く取る。
PROBE_STALE_MIN = 60
PROBE_7D_STALE_MIN = 15
# 失敗の後に投げ直さない間（分）。通信が落ちている間に投げ続けないため
PROBE_RETRY_MIN = 10
# herdr の tab_bar_right は 16 個まで。アカウントの表示と、取り直しの 1 個
HERDR_MAX_ENTRIES = 16

API = "https://api.anthropic.com/v1/messages"
# 2026-09-23 に max_tokens 0 で 200 とヘッダが返ると確かめた形。Opus・Sonnet で投げると 429 でヘッダが付かなかった
MODEL = "claude-haiku-4-5-20251001"
BODY = json.dumps({"model": MODEL, "max_tokens": 0,
                   "messages": [{"role": "user", "content": "."}]}).encode()
HEADER_PREFIX = "anthropic-ratelimit-unified-"
# 状態のヘッダ（anthropic-ratelimit-unified-status と <枠>-status）の、知っている値。ほかの値は控えの unknown に残し、--tree に出す
# （外の形が変わったのを黙って読み落とさない。tests/samples/ratelimit-headers.json は 2026-10-19 に採った実物の応答ヘッダ）
KNOWN_STATUS = ("allowed", "allowed_warning", "rejected")
STATUS, ERROR = ":status", ":error"   # fetch が応答ヘッダに添える HTTP の状態と、誤りの応答の本文の頭（ヘッダの名前と重ならない）
TRUST_HOURS = 3   # 控えがこれより古ければ当てにしない（取り直しは 15〜60 分ごとなので、何回も続けて取れていない）
FAILED = "probe-failed-{}.json"   # 取り直しに失敗したアカウントの {at, reason}。取れたら消す


def from_headers(headers, now):
    """応答ヘッダ（鍵 → 値の表。fetch の返り）から控えを作る。ratelimit のヘッダが 1 つも枠にならなければ None。

    弾かれた（status=rejected）枠に自分のヘッダが無いときは、弾いた枠（representative-claim）を 100% として、
    全体の戻り時刻（reset）で埋める。埋めないと、弾かれる前の値が出続ける。
    """
    h = {}
    for k, v in headers.items():
        k = k.lower()   # HTTP のヘッダの名前は大文字と小文字を区別しない（RFC 9110 の 5.1）
        if k.startswith(HEADER_PREFIX):
            h[k[len(HEADER_PREFIX):]] = v.strip()

    def num(k):
        try:
            return float(h[k])
        except (KeyError, ValueError):
            return None

    def win(k, claim):
        used = num(f"{k}-utilization")
        if used is not None:
            reset = num(f"{k}-reset")
            return {"used_percentage": round(used * 100, 6), "resets_at": int(reset) if reset is not None else None,
                    "updated_at": now}
        if h.get("status") == "rejected" and h.get("representative-claim") == claim and num("reset") is not None:
            return {"used_percentage": 100, "resets_at": int(num("reset")), "updated_at": now}
        return None

    snap = {"five_hour": win("5h", "five_hour"), "seven_day": win("7d", "seven_day"), "updated_at": now, "source": "probe"}
    unknown = sorted(f"{k}={v}" for k, v in h.items() if (k == "status" or k.endswith("-status")) and v not in KNOWN_STATUS)
    if unknown:
        snap["unknown"] = unknown
    return snap if snap["five_hour"] or snap["seven_day"] else None


def stale(snap, now):
    """控えが古くて当てにならないか: どれかの枠の updated_at が TRUST_HOURS より古い。100% の枠がまだ切り替わっていない間は、
    取り直さない（need_probe）ので古くない。控えが無ければ False（無いことは呼ぶ側が見る）。"""
    if not isinstance(snap, dict):
        return False
    ws = _windows(snap)
    if any(_num(w.get("used_percentage")) and w["used_percentage"] >= 100 and _num(w.get("resets_at")) and w["resets_at"] > now
           for w in ws):
        return False
    times = [w["updated_at"] for w in ws if _num(w.get("updated_at"))]
    return bool(times) and now - min(times) > TRUST_HOURS * 3600   # 時刻の無い控え（試験の形など）は古さが分からないので信じる


def failure(limits_dir, name):
    """取り直しの失敗の控え {at, reason}。無ければ None。"""
    got = _read(pathlib.Path(limits_dir) / FAILED.format(name))
    return got if isinstance(got, dict) else None


def problems(accounts, limits_dir, now):
    """使用率の控えの、当てにならない所の注記の並び（取り直しの失敗・古い控え・知らない状態の値）。--tree と --check が出す。"""
    out = []
    for a in accounts:
        if not a.limits:
            continue
        snap, fail = _read(pathlib.Path(limits_dir) / f"{a.name}.json"), failure(limits_dir, a.name)
        if fail:
            at = fail.get("at")
            when = time.strftime("%m-%d %H:%M", time.localtime(at)) if _num(at) else "?"
            out.append(f"アカウント {a.name} の使用率の取り直しが失敗している（{when}: {fail.get('reason')}。probe.log に続きがある）")
        if stale(snap, now):
            out.append(f"アカウント {a.name} の使用率の控えが {TRUST_HOURS} 時間より古い（使用率が分からない物として選ぶ順の最後に置く）")
        if isinstance(snap, dict) and snap.get("unknown"):
            out.append(f"アカウント {a.name} の使用率の応答に、知らない状態の値がある: {', '.join(map(str, snap['unknown']))}"
                       "（limits.py の KNOWN_STATUS と読み方を見直す）")
    return out


def _windows(snap):
    return [w for w in (snap.get("five_hour"), snap.get("seven_day")) if isinstance(w, dict)]


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def need_probe(snap, now):
    """取り直すか。控えが無い・枠が欠けている・どれかの枠の切り替わりが過ぎた・古い（100% の枠がある間は除く）のどれか。

    切り替わりの過ぎた枠は、次の切り替わりの時刻が取り直すまで分からないので、古さに関係なく取り直す。
    100% の枠がある間は、すべての要求が弾かれて値が動かないので投げない。古さは枠ごとの updated_at で測る。
    """
    if not isinstance(snap, dict):
        return True
    ws = _windows(snap)
    if len(ws) < 2:
        return True
    if any(_num(w.get("resets_at")) and w["resets_at"] <= now for w in ws):
        return True
    if any(_num(w.get("used_percentage")) and w["used_percentage"] >= 100 for w in ws):
        return False
    age5 = now - (snap["five_hour"].get("updated_at") or 0)
    age7 = now - (snap["seven_day"].get("updated_at") or 0)
    return age5 > PROBE_STALE_MIN * 60 or age7 > PROBE_7D_STALE_MIN * 60


def _left(sec):
    sec = math.floor(sec)
    if sec <= 0:
        return "0m"
    d, h, m = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60
    return f"{d}d{h}h" if d else f"{h}h{m}m" if h else f"{m}m"


def render(name, snap, now, fail=None):
    """1 アカウントぶんの 1 行。例: "p1 5h 38% 1h4m  7d 32% 2d4h"。控えが無ければ空（取り直しに失敗していれば、その印だけ）。

    80% 以上の枠は "%!"。切り替わりの過ぎた枠は 0% と読み、取り直すまで残り時間を付けない。
    枠の中は 1 空白、枠の境は 2 空白（herdr はアカウントの境に tab_bar_right_separator を入れる）。
    控えが古い（stale）と後ろに「古い」、取り直しの失敗（fail）が控えより新しいと「取り直し失敗」を足す（訳は --tree が出す）。
    """
    tags = (["古い"] if stale(snap, now) else []) + (
        ["取り直し失敗"] if fail and _num(fail.get("at"))
        and fail["at"] >= ((snap.get("updated_at") or 0) if isinstance(snap, dict) else 0) else [])
    if not isinstance(snap, dict):
        return f"{name} {' '.join(tags)}" if tags else ""
    parts = []
    for label, key in (("5h", "five_hour"), ("7d", "seven_day")):
        w = snap.get(key)
        if not isinstance(w, dict) or not _num(w.get("used_percentage")):
            continue
        at = w.get("resets_at")
        live = _num(at) and at > now
        p = 0 if _num(at) and not live else math.floor(w["used_percentage"] + 0.5)
        text = f"{label} {p}{'%!' if p >= 80 else '%'}"
        parts.append(text + (f" {_left(at - now)}" if live else ""))
    return f"{name} " + "  ".join(parts + tags) if parts else ""


def _newer(o, n):
    """5 時間の枠の新しい方。切り替わりの後の枠が新しい。同じ枠なら高い方（枠の中で使用率は下がらない）。"""
    if n is None:
        return o
    if o is None or not _num(o.get("resets_at")):
        return n
    if not _num(n.get("resets_at")):
        return o
    if n["resets_at"] > o["resets_at"]:
        return n
    if n["resets_at"] == o["resets_at"] and n.get("used_percentage", 0) > o.get("used_percentage", 0):
        return n
    return o


def merge_statusline(old, rate_limits, now):
    """statusline の rate_limits を控えに取り込んだ形を返す。何も変わらなければ None（書かない）。

    statusline の値は、その会話が最後に受けた応答の値で、放置した会話は古い値を渡し続ける。そこで上書きせず枠ごとに見る。
    - 5 時間の枠: 新しい方（_newer）を採り、採った値が変わったときだけ updated_at を今にする。
    - 7 日の枠: 大きさで採らない。移動する窓なので古い使用が抜けると下がり、放置した会話の古い高い値が
      probe の測った今の値を潰すため。枠が進んだときと、控えに無いときだけ書く。
    updated_at は「値が最後に動いた時刻」で、probe はこれで古さを測る。
    """
    rl = rate_limits if isinstance(rate_limits, dict) else {}
    n5, n7 = rl.get("five_hour"), rl.get("seven_day")
    if not n5 and not n7:
        return None
    o = old if isinstance(old, dict) else {}
    o5, o7 = o.get("five_hour"), o.get("seven_day")

    def strip(w):
        return {"used_percentage": w.get("used_percentage"), "resets_at": w.get("resets_at")}

    n5 = strip(n5) if isinstance(n5, dict) else None
    n7 = strip(n7) if isinstance(n7, dict) else None

    w5 = _newer(o5, n5)
    if w5 is not None and (o5 is None or w5.get("resets_at") != o5.get("resets_at")
                           or w5.get("used_percentage") != o5.get("used_percentage")):
        w5 = {**w5, "updated_at": now}

    if o7 is None:
        w7 = {**n7, "updated_at": now} if n7 else None
    elif n7 and _num(n7.get("resets_at")) and _num(o7.get("resets_at")) and n7["resets_at"] > o7["resets_at"]:
        w7 = {**n7, "updated_at": now}
    else:
        w7 = o7

    if w5 == o5 and w7 == o7:
        return None
    got = {"five_hour": w5, "seven_day": w7, "updated_at": now}
    if o.get("unknown"):
        got["unknown"] = o["unknown"]   # probe の見た知らない状態の値。statusline は状態を渡さないので、次の probe まで残す
    return got


def account_for(accounts, env):
    """statusline を動かしている Claude Code の設定のフォルダ（CLAUDE_CONFIG_DIR、無ければ ~/.claude）から、アカウントの名前を返す。

    設定に config_dir を書かないアカウントは、既定のフォルダ（~/.claude）のアカウントとして数える。どれにも当たらなければ None。
    """
    home = env.get("HOME") or str(pathlib.Path.home())
    default = os.path.join(home, ".claude")
    current = os.path.normpath(os.path.expanduser(env.get("CLAUDE_CONFIG_DIR") or default))
    for a in accounts:
        if os.path.normpath(a.config_dir or default) == current:
            return a.name
    return None


# 契約の段が引けないときの理由。setup-token のトークンはモデルへの要求しかできず（Claude Code の文書の「Generate a long-lived
# token」）、契約の段を返す口（/api/oauth/profile）は user:profile の権限が要ると 403 で断る（2026-10-18 に p2・p3 の鍵で確かめた）。
# 応答ヘッダ（anthropic-ratelimit-unified-*）にも段は出ない。そのため Claude Code がログインのときに書く記録だけを読む。
# 一度ログインしたフォルダは、その後 setup-token の鍵で動かしても記録が残る（2026-10-18 に p3 で見た。setup-token の鍵を環境変数で渡すと、
# ログインより先に使われる。Claude Code の文書の「Authentication precedence」）
NO_PLAN = ("{record} から契約の段（Claude Code のログインの記録 oauthAccount の organizationRateLimitTier）が読めない。"
           "setup-token や API キーだけで入るアカウントはこの記録を作らず、setup-token の鍵では契約の段を問い合わせられないので、"
           "ツールからは引けない。引けるようにするには、同じアカウントでそのフォルダに一度ログインする（{login}。"
           "書かれるのはそのフォルダのログインだけ）")


def plan_record(account, env):
    """Claude Code がログインの記録（oauthAccount）を書くファイル。設定のフォルダの .claude.json、フォルダを書かないアカウントは
    ~/.claude.json（account_for と同じく、既定のフォルダのアカウントとして数える）。"""
    if account.config_dir:
        return os.path.join(os.path.expanduser(account.config_dir), ".claude.json")
    return os.path.join(env.get("HOME") or str(pathlib.Path.home()), ".claude.json")


def plan_of(account, env):
    """1 アカウントの契約の段。{"name", "tier", "type", "fetched_at", "record", "reason"}。tier が None なら reason に訳を書く。

    tier は Claude Code が記録する organizationRateLimitTier（例 default_claude_max_20x）、type は organizationType（例 claude_max）。
    fetched_at は Claude Code が段を問い合わせた時刻（手元の時差を付けた ISO 8601。記録に無いか読めなければ None）。記録は Claude Code が問い合わせ直す
    まで古いまま（setup-token の鍵で動かしているアカウントは問い合わせ直せない）なので、契約を変えた後は時点を見る。
    """
    record = plan_record(account, env)
    out = {"name": account.name, "tier": None, "type": None, "fetched_at": None, "record": record, "reason": None}
    if not account.limits:
        out["reason"] = "使用率の枠の無いアカウント（設定の limits = false）で、契約の段は無い"
        return out
    o = (_read(record) or {}).get("oauthAccount")
    tier = o.get("organizationRateLimitTier") if isinstance(o, dict) else None
    if not tier or not isinstance(tier, str):
        login = (f"CLAUDE_CONFIG_DIR={account.config_dir} " if account.config_dir else "") + "claude auth login"
        out["reason"] = NO_PLAN.format(record=record, login=login)
        return out
    at = o.get("profileFetchedAt")
    try:
        fetched = datetime.datetime.fromtimestamp(at / 1000).astimezone().isoformat(timespec="seconds") if _num(at) else None
    except (OverflowError, OSError, ValueError):
        fetched = None   # 壊れた時刻で、ほかのアカウントの行まで落とさない
    out.update(tier=tier, type=o.get("organizationType"), fetched_at=fetched)
    return out


def render_plan(p):
    """plan_of の 1 件を 1 行にする。例: "p1 default_claude_max_20x（claude_max） 2026-10-15T09:00:00+09:00 時点"。"""
    if not p["tier"]:
        return f"{p['name']} 分からない: {p['reason']}"
    kind = f"（{p['type']}）" if p["type"] else ""
    when = f" {p['fetched_at']} 時点" if p["fetched_at"] else ""
    return f"{p['name']} {p['tier']}{kind}{when}"


def _read(path):
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _write(path, data):
    filex.replace(path, json.dumps(data, ensure_ascii=False) + "\n")


def _log(d, text):
    log = pathlib.Path(d) / "probe.log"
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {text}\n")
    lines = log.read_text(encoding="utf-8").splitlines()
    if len(lines) > 500:  # 育ちすぎないよう末尾だけ残す
        log.write_text("\n".join(lines[-200:]) + "\n", encoding="utf-8")


def fetch(tok):
    """API に出力 0 トークンの要求を 1 回投げ、応答ヘッダを {名前: 値} で返す（前は 1 つの文に直してから from_headers が行に
    切り直していた）。枠切れの 429 でもヘッダは付くので、状態で止めない。HTTP の状態を STATUS に、誤りの応答なら本文の頭を ERROR に
    添える（ヘッダが無いときの訳。モデルの名前が使えなくなったときの 404 など）。

    プロキシは環境変数（HTTPS_PROXY）に従う（urllib の既定）。通信の失敗は OSError で上がる。
    """
    req = urllib.request.Request(API, data=BODY, method="POST", headers={
        "Authorization": f"Bearer {tok}",
        "anthropic-beta": "oauth-2025-04-20",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as r:
            return {**dict(r.headers.items()), STATUS: str(r.status)}
    except urllib.error.HTTPError as e:
        try:
            body = " ".join(e.read(300).decode("utf-8", "replace").split())
        except OSError:
            body = ""
        return {**dict(e.headers.items()), STATUS: str(e.code), ERROR: body}


def probe_env(env):
    """鍵を探すときの環境。シェル全体に効く上書き CLAUDE_KEYCHAIN_SERVICE を外す（残すと全アカウントが同じ鍵になる）。"""
    return {k: v for k, v in env.items() if k != "CLAUDE_KEYCHAIN_SERVICE"}


def probe_all(accounts, limits_dir, env, now, token=None, fetch=fetch, force=False):
    """取り直しの要るアカウントだけ、順に問い合わせて控えを書く。失敗は probe.log に残し、黙って落とさない。
    force は古さと試み直しの待ちを見ずに全部に問い合わせる（dispatch が、始める前と /catchup の後の今の値を取るのに使う）。

    token(user_config, explicit) は (トークン, 出どころ) か (None, 探した所) を返す。既定は scripts/claude_auth.py の account_token。
    取れた時刻を .probe-<名前> に、失敗した時刻と訳を probe-failed-<名前>.json に残し、どちらからも PROBE_RETRY_MIN の間は投げ直さない。
    時刻は試みた後に書く。失敗は .probe-<名前> に書かない（取れたように見せない。--tree とタブバーが失敗を出す）。
    """
    if token is None:
        def token(user_config, explicit):
            return claude_auth.account_token(user_config, probe_env(env), explicit)
    d = pathlib.Path(limits_dir)
    d.mkdir(parents=True, exist_ok=True)
    for a in accounts:
        if not a.limits or not (force or need_probe(_read(d / f"{a.name}.json"), now)):
            continue
        stamp, failed = d / f".probe-{a.name}", d / FAILED.format(a.name)
        try:
            last = float(stamp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = None
        tried = (failure(d, a.name) or {}).get("at")
        last = max([x for x in (last, tried) if _num(x)], default=None)
        if not force and last is not None and now - last < PROBE_RETRY_MIN * 60:
            continue
        tok, note = token(a.config_dir, a.keychain_service)
        reason = None
        if not tok:
            reason = f"鍵が無い: {note}"
        else:
            try:
                headers = fetch(tok)
            except (OSError, http.client.HTTPException) as e:
                reason = f"通信に失敗（プロキシの設定か通信断）: {e!r}"
            else:
                snap = from_headers(headers, now)
                if snap is None:
                    reason = (f"応答に ratelimit のヘッダが無い（HTTP {headers.get(STATUS, '?')}。鍵の期限切れか、使用率の枠の無い"
                              f"アカウントか、問い合わせのモデル {MODEL} が使えなくなった）" + (f": {headers[ERROR]}" if headers.get(ERROR) else ""))
                else:
                    _write(d / f"{a.name}.json", snap)
        if reason:
            _log(d, f"{a.name}: {reason}")
            _write(failed, {"at": now, "reason": reason})
            continue
        stamp.write_text(str(now), encoding="utf-8")
        try:
            failed.unlink()
        except FileNotFoundError:
            pass


def write_snapshot(path, accounts, limits_dir):
    """タブバーから呼ぶ道が読むアカウントの写しを書く。"""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, {"schema": 1, "limits_dir": str(limits_dir),
                  "accounts": [{"name": a.name, "command": a.command, "config_dir": a.config_dir,
                                "keychain_service": a.keychain_service, "limits": a.limits} for a in accounts]})


def read_snapshot(path):
    """(アカウントの並び, limits_dir)。写しが読めなければ ValueError。"""
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        accts = tuple(Snap(a["name"], a.get("command"), a.get("config_dir"), a.get("keychain_service"), a.get("limits", True))
                      for a in raw["accounts"])
        return accts, raw["limits_dir"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"アカウントの写し {path} が読めない（{e}）。limits.py herdr-config を走らせ直す") from e


def herdr_entries(accounts, script, snapshot_path, picker=PICKER):
    """herdr の tab_bar_right に並べる行。使用率の枠のあるアカウントごとに表示を 1 つ、最後に取り直しを 1 つ。"""
    shown = [a for a in accounts if a.limits]
    if len(shown) + 1 > HERDR_MAX_ENTRIES:
        raise ValueError(f"herdr のタブバーに並べられるのは {HERDR_MAX_ENTRIES - 1} アカウントまで（{len(shown)} ある）")
    show, probe = [line for line in TEMPLATE.read_text(encoding="utf-8").splitlines() if line.startswith("{{")]

    def fill(s):
        # 雛形の command は TOML の "…" の中なので、埋める値の \ と " をエスケープする（名前などに混じったとき）
        return shlex.quote(s).replace("\\", "\\\\").replace('"', '\\"')

    def path(p):
        # パスは / 区切りで書く（bash が読む。Windows の \ 区切りは引用符と \\ に化けた。activity.settings と同じ形）
        return fill(pathlib.PurePath(p).as_posix())
    q = {"script": path(script), "accounts": path(snapshot_path), "picker": path(picker)}
    lines = [show.format(name=fill(a.name), **q) for a in shown] + [probe.format(**q)]
    # 組んだ行を TOML として読み直して確かめる（エスケープの漏れで herdr が設定ごと読めなくなるのを、書く前に止める）。
    # herdr-config は設定の TOML を読む道なので 3.11 以上で走る（tomllib はここでだけ読み込む。show・probe は 3.9 でも走る）
    import tomllib
    try:
        got = tomllib.loads("x = [\n" + "\n".join(lines) + "\n]")["x"]
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"herdr のタブバーの行が TOML として読めない（{e}）: {lines}") from e
    if len(got) != len(lines) or not all(isinstance(x, dict) and isinstance(x.get("command"), str) for x in got):
        raise ValueError(f"herdr のタブバーの行が 1 行 1 つの command の表になっていない: {lines}")
    return lines


def copy_entry(limits_dir):
    """版に依らない入口（limits-entry.py と run-python.sh）を limits_dir に写し、(入口, Python を選ぶ入口) のパス。写せなければ OSError。"""
    d = pathlib.Path(limits_dir)
    d.mkdir(parents=True, exist_ok=True)
    for name, src in ENTRY_COPIES.items():
        filex.replace(str(d / name), src.read_text(encoding="utf-8"))
    return d / "limits-entry.py", d / "run-python.sh"


def entry_drift(limits_dir):
    """limits_dir に写した入口のうち、今の版の元と中身の違うファイルの名前の並び（写していなければ空）。"""
    d = pathlib.Path(limits_dir)
    out = []
    for name, src in ENTRY_COPIES.items():
        try:
            if (d / name).read_text(encoding="utf-8") != src.read_text(encoding="utf-8"):
                out.append(name)
        except OSError:
            continue
    return out


def main(argv=None, env=os.environ, stdin=sys.stdin):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--accounts", help="herdr-config が書いたアカウントの写し。渡すと設定の TOML を読まない")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show").add_argument("name")
    sub.add_parser("probe")
    sub.add_parser("record")
    sub.add_parser("herdr-config")
    sub.add_parser("plan").add_argument("--json", action="store_true", help="機械向けに JSON の並びで出す")
    a = ap.parse_args(argv)
    if a.accounts and a.cmd != "herdr-config":
        try:
            accts, limits_dir = read_snapshot(a.accounts)
        except ValueError as e:
            print(e, file=sys.stderr)
            return 1
    else:
        import config  # TOML を読む道だけが引く（tomllib は 3.11 から）
        try:
            cfg = config.load(a.config, env)
        except config.ConfigError as e:
            print(e, file=sys.stderr)
            return 1
        accts, limits_dir = cfg.accounts, cfg.limits_dir
    now = time.time()
    if a.cmd == "show":
        line = render(a.name, _read(pathlib.Path(limits_dir) / f"{a.name}.json"), now, failure(limits_dir, a.name))
        if line:
            print(line)
    elif a.cmd == "probe":
        probe_all(accts, limits_dir, env, now)
    elif a.cmd == "plan":
        plans = [plan_of(x, env) for x in accts]
        print(json.dumps(plans, ensure_ascii=False, indent=2) if a.json else "\n".join(render_plan(p) for p in plans))
    elif a.cmd == "record":
        try:
            rate_limits = json.load(stdin).get("rate_limits")
        except (ValueError, AttributeError):
            return 0  # statusline の入力が読めない回は書かない。statusline の表示を止めない
        name = account_for(accts, env)
        acct = next((x for x in accts if x.name == name), None)
        if acct is None or not acct.limits:
            return 0
        path = pathlib.Path(limits_dir) / f"{name}.json"
        snap = merge_statusline(_read(path), rate_limits, now)
        if snap is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write(path, snap)
    else:
        try:
            snapshot = pathlib.Path(limits_dir) / SNAPSHOT_NAME
            herdr_entries(accts, str(HERE / "limits.py"), snapshot)   # 写す前に、行が組めるか（アカウントの数）を確かめる
            entry, picker = copy_entry(limits_dir)
            lines = herdr_entries(accts, str(entry), snapshot, picker)
            write_snapshot(snapshot, accts, limits_dir)
        except (ValueError, OSError) as e:
            print(e, file=sys.stderr)
            return 1
        print("tab_bar_right = [")
        print("\n".join("  " + x for x in lines))
        print("]")
        print('tab_bar_right_separator = " | "')
    return 0


if __name__ == "__main__":
    sys.exit(main())
