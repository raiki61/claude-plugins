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
  python3 limits.py [--config <パス> | --accounts <写し>] show <名前>   … 控えを読んで 1 行出す（herdr のタブ欄が呼ぶ）
  python3 limits.py [--config <パス> | --accounts <写し>] probe         … 取り直しが要るアカウントだけ API に問い合わせる
  python3 limits.py [--config <パス> | --accounts <写し>] record        … statusline の JSON を標準入力から読んで控えに取り込む
  python3 limits.py [--config <パス>] herdr-config  … アカウントの写しを書き、herdr の config.toml の [ui] に置く tab_bar_right を出す

アカウントの写し（<limits_dir>/accounts.json）は、herdr-config が dispatch の設定から書く JSON。herdr のタブ欄から呼ぶ道は
設定の TOML を読まずにこれを読む。herdr がタブ欄のコマンドに渡す PATH の python3 は、macOS では OS に付いてくる 3.9 のことがあり、
TOML を読む tomllib（3.11 から）が無いため。タブ欄から呼ぶ道（このファイルと vendor/claude_auth.py）は 3.9 の文法で書く。

こちらからは打ち切らない。herdr のタブ欄から呼ぶときは、herdr の設定の秒（雛形 templates/herdr-tab-bar.toml）が打ち切る。
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
from vendor import claude_auth  # noqa: E402

# 写しから読んだアカウント。dispatch の設定の Account と同じ名前の欄を持つ（config は tomllib を引くので、ここでは import しない）
Snap = collections.namedtuple("Snap", "name command config_dir keychain_service limits")
SNAPSHOT_NAME = "accounts.json"

# Windows の既定の標準入出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
TEMPLATE = HERE / "templates" / "herdr-tab-bar.toml"
PICKER = HERE.parent / "hooks" / "run-python.sh"   # Python を選ぶ入口（フックと同じ決まり。Store へ誘う代わりの物を飛ばす）

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
BODY = json.dumps({"model": "claude-haiku-4-5-20251001", "max_tokens": 0,
                   "messages": [{"role": "user", "content": "."}]}).encode()
HEADER_PREFIX = "anthropic-ratelimit-unified-"


def from_headers(text, now):
    """応答ヘッダの文字列から控えを作る。ratelimit のヘッダが 1 つも枠にならなければ None。

    弾かれた（status=rejected）枠に自分のヘッダが無いときは、弾いた枠（representative-claim）を 100% として、
    全体の戻り時刻（reset）で埋める。埋めないと、弾かれる前の値が出続ける。
    """
    h = {}
    for line in text.splitlines():
        k, sep, v = line.partition(":")
        k = k.strip().lower()
        if sep and k.startswith(HEADER_PREFIX):
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
    return snap if snap["five_hour"] or snap["seven_day"] else None


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


def render(name, snap, now):
    """1 アカウントぶんの 1 行。例: "p1 5h 38% 1h4m  7d 32% 2d4h"。控えが無ければ空。

    80% 以上の枠は "%!"。切り替わりの過ぎた枠は 0% と読み、取り直すまで残り時間を付けない。
    枠の中は 1 空白、枠の境は 2 空白（herdr はアカウントの境に tab_bar_right_separator を入れる）。
    """
    if not isinstance(snap, dict):
        return ""
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
    return f"{name} " + "  ".join(parts) if parts else ""


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
    return {"five_hour": w5, "seven_day": w7, "updated_at": now}


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


def _read(path):
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _write(path, data):
    path = pathlib.Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _log(d, text):
    log = pathlib.Path(d) / "probe.log"
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"{stamp} {text}\n")
    lines = log.read_text(encoding="utf-8").splitlines()
    if len(lines) > 500:  # 育ちすぎないよう末尾だけ残す
        log.write_text("\n".join(lines[-200:]) + "\n", encoding="utf-8")


def _header_text(headers):
    return "".join(f"{k}: {v}\n" for k, v in headers.items())


def fetch(tok):
    """API に出力 0 トークンの要求を 1 回投げ、応答ヘッダを文字列で返す。枠切れの 429 でもヘッダは付くので、状態は見ない。

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
            return _header_text(r.headers)
    except urllib.error.HTTPError as e:
        return _header_text(e.headers)


def probe_env(env):
    """鍵を探すときの環境。シェル全体に効く上書き CLAUDE_KEYCHAIN_SERVICE を外す（残すと全アカウントが同じ鍵になる）。"""
    return {k: v for k, v in env.items() if k != "CLAUDE_KEYCHAIN_SERVICE"}


def probe_all(accounts, limits_dir, env, now, token=None, fetch=fetch, force=False):
    """取り直しの要るアカウントだけ、順に問い合わせて控えを書く。失敗は probe.log に残し、黙って落とさない。
    force は古さと試み直しの待ちを見ずに全部に問い合わせる（dispatch が、始める前と /catchup の後の今の値を取るのに使う）。

    token(user_config, explicit) は (トークン, 出どころ) か (None, 探した所) を返す。既定は scripts/claude_auth.py の account_token。
    試みた時刻を .probe-<名前> に残し、失敗しても PROBE_RETRY_MIN の間は投げ直さない。時刻は試みた後に書く。
    """
    if token is None:
        def token(user_config, explicit):
            return claude_auth.account_token(user_config, probe_env(env), explicit)
    d = pathlib.Path(limits_dir)
    d.mkdir(parents=True, exist_ok=True)
    for a in accounts:
        if not a.limits or not (force or need_probe(_read(d / f"{a.name}.json"), now)):
            continue
        stamp = d / f".probe-{a.name}"
        try:
            last = float(stamp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = None
        if not force and last is not None and now - last < PROBE_RETRY_MIN * 60:
            continue
        tok, note = token(a.config_dir, a.keychain_service)
        if not tok:
            _log(d, f"{a.name}: 鍵が無い: {note}")
        else:
            try:
                snap = from_headers(fetch(tok), now)
            except (OSError, http.client.HTTPException) as e:
                _log(d, f"{a.name}: 通信に失敗（プロキシの設定か通信断）: {e!r}")
            else:
                if snap is None:
                    _log(d, f"{a.name}: 応答に ratelimit のヘッダが無い（鍵の期限切れか、使用率の枠の無いアカウント）")
                else:
                    _write(d / f"{a.name}.json", snap)
        stamp.write_text(str(now), encoding="utf-8")


def write_snapshot(path, accounts, limits_dir):
    """タブ欄から呼ぶ道が読むアカウントの写しを書く。"""
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


def herdr_entries(accounts, script, snapshot_path):
    """herdr の tab_bar_right に並べる行。使用率の枠のあるアカウントごとに表示を 1 つ、最後に取り直しを 1 つ。"""
    shown = [a for a in accounts if a.limits]
    if len(shown) + 1 > HERDR_MAX_ENTRIES:
        raise ValueError(f"herdr のタブ欄に並べられるのは {HERDR_MAX_ENTRIES - 1} アカウントまで（{len(shown)} ある）")
    show, probe = [line for line in TEMPLATE.read_text(encoding="utf-8").splitlines() if line.startswith("{{")]

    def fill(s):
        # 雛形の command は TOML の "…" の中なので、埋める値の \ と " をエスケープする（Windows のパスは \ を含む）
        return shlex.quote(s).replace("\\", "\\\\").replace('"', '\\"')
    q = {"script": fill(script), "accounts": fill(str(snapshot_path)), "picker": fill(str(PICKER))}
    return [show.format(name=fill(a.name), **q) for a in shown] + [probe.format(**q)]


def main(argv=None, env=os.environ, stdin=sys.stdin):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--accounts", help="herdr-config が書いたアカウントの写し。渡すと設定の TOML を読まない")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show").add_argument("name")
    sub.add_parser("probe")
    sub.add_parser("record")
    sub.add_parser("herdr-config")
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
        line = render(a.name, _read(pathlib.Path(limits_dir) / f"{a.name}.json"), now)
        if line:
            print(line)
    elif a.cmd == "probe":
        probe_all(accts, limits_dir, env, now)
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
            lines = herdr_entries(accts, str(HERE / "limits.py"), snapshot)
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
