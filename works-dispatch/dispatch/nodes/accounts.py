#!/usr/bin/env python3
"""accounts ノード: 使用率の控えと動いている会話の数から、選べるアカウントとその順を決める（設計書のセクション 2 の 3）。外には書かない
（--pick だけは、古い控えを取り直す。limits.py の probe と同じく、古いアカウントにだけ出力 0 トークンで問い合わせる）。

- 週の枠（seven_day）か 5 時間の枠（five_hour）の使用率が上限に達したアカウントは選ばない。使用率は 1% 刻みの整数で届き、ちょうど上限の値は上限を超えている見込みがあるので、上限ちょうども選ばない。
- 切り替わりの時刻（resets_at）が過ぎた枠は、切り替わった後なので使用率 0 とみなす。
- 選べるものを、次の順に並べる（持ち主の決め 2026-10-16）。
  1. 週の枠の切り替わりが近い（設定の reset_soon_hours 以内。既定 24 時間。ちょうども含む）ものを先に、切り替わりの近い順。使わずに切り替わる分を無駄にしないため。
  2. それ以外は、5 時間の枠と週の枠のうち高い方の使用率の低い順。週の切り替わりが十数時間早いだけのアカウントに寄せて、その 5 時間の枠を先に食い潰さないため。
  3. 同じなら、そのアカウントで動いている会話の数の少ない順、次に設定の順。
- 使える時間帯（設定の hours）の外のアカウントと、時間帯の終わりまで設定の hours_margin_minutes（既定 30 分。ちょうども含む）を切ったアカウントは選ばない。
  終わりで要求が断られ、ターンの途中で切られるため。日をまたぐ時間帯は始まった日の物として見る。
- 控えが無い・読めないアカウントは、使用率が分からないものとして選べる側に残し、順の最後に置く（D7）。
- 使用率の枠の無いアカウント（設定の limits = false。Ollama・Foundry など）は控えを読まず、控えの無いものと同じに扱う。
- 動いている会話は、`claude agents --json` の 1 件のうち、背景の会話は state が working・blocked のもの、state の無い対話の会話は status が busy のもの。
  アカウントの一覧を読めなければ 0 件とみなして先へ進み、注記を出す。

使い方:
  python3 nodes/accounts.py [--config <パス>] [--out <パス>] [--now <Unix 時刻>]   … 全部のアカウントの順を JSON で出す
  python3 nodes/accounts.py --pick [--json] [--no-probe] [--config <パス>]          … 1 つ選び、名前と起動コマンドを出す
--pick は、人が読む 1 行（「<名前>: <起動コマンド> — <選んだ訳>」）を標準出力に、注記を標準エラーに出す。--json は、選んだ 1 件（pick）と
全部の順（accounts）と注記（notes）を JSON で出す。選べるアカウントが無ければ、終了の値は 1。
"""

import argparse
import datetime
import json
import math
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ports import chat  # noqa: E402
import config  # noqa: E402
import jsonio  # noqa: E402
import limits as limits_  # noqa: E402

# Windows の既定の標準出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

WINDOWS = ("seven_day", "five_hour")
RUNNING_STATES = ("working", "blocked")  # 背景の会話の state のうち、動いているもの


def _window(raw, now):
    """控えの 1 つの枠を {used, resets_at} にする。切り替わりの過ぎた枠は used 0・resets_at None。"""
    if not isinstance(raw, dict):
        return {"used": None, "resets_at": None}
    used, at = raw.get("used_percentage"), raw.get("resets_at")
    if isinstance(at, (int, float)) and at <= now:
        return {"used": 0, "resets_at": None}
    return {"used": used if isinstance(used, (int, float)) else None,
            "resets_at": int(at) if isinstance(at, (int, float)) else None}


def opening(hours, now):
    """使える時間帯 hours（config.Hours）の今 now の様子。{"open": 中か, "closes_at": 中なら終わりの Unix 時刻, "opens_at": 外なら次の始まり}。"""
    tz = config.zone_of(hours.zone)
    day = datetime.datetime.fromtimestamp(now, tz).date()
    starts = [datetime.datetime(d.year, d.month, d.day, tzinfo=tz) + datetime.timedelta(minutes=hours.start)
              for d in (day - datetime.timedelta(days=1), day, day + datetime.timedelta(days=1))]
    for s in starts:
        begin, end = s.timestamp(), (s + datetime.timedelta(minutes=hours.length)).timestamp()
        if begin <= now < end:
            return {"open": True, "closes_at": int(end), "opens_at": None}
    return {"open": False, "closes_at": None, "opens_at": int(next(s.timestamp() for s in starts if s.timestamp() > now))}


def shut(hours, now, margin_minutes):
    """使える時間帯の外か、終わりまで margin_minutes を切ったなら、訳の文。ほかは None。"""
    if hours is None or hours.length >= 24 * 60:
        return None   # 一日中（00:00-24:00）は、日の境目で終わらない
    got = opening(hours, now)
    if not got["open"]:
        at = datetime.datetime.fromtimestamp(got["opens_at"], config.zone_of(hours.zone)).strftime("%H:%M")
        return f"使える時間帯（{hours.text}）の外（次は {at} {hours.zone} に始まる）"
    if got["closes_at"] - now <= margin_minutes * 60:
        return f"使える時間帯（{hours.text}）が {_left(got['closes_at'] - now)}後に終わる（終わりの {margin_minutes:g} 分前からは選ばない）"
    return None


def _reopens(hours, now):
    """使える時間帯 hours の外か終わる手前なら、次に時間帯が始まる Unix 時刻。"""
    got = opening(hours, now)
    return got["opens_at"] if not got["open"] else opening(hours, got["closes_at"])["opens_at"]


def is_running(item):
    """`claude agents --json` の 1 件が動いている会話か。背景の会話は state、state の無い対話の会話は status で見る。"""
    state = item.get("state")
    if state is not None:
        return state in RUNNING_STATES
    return item.get("status") == "busy"


def count_running(listed):
    """listed: アカウントの名 → そのアカウントの `claude agents --json` の並び。返すのは名 → 動いている会話の数。"""
    return {name: sum(1 for s in items if isinstance(s, dict) and is_running(s)) for name, items in listed.items()}


def gather_running(accounts, list_sessions):
    """アカウントごとに会話の一覧を読み、動いている会話を数える。読めないアカウントは 0 件とみなし、注記を返す。"""
    listed, notes = {}, []
    for a in accounts:
        try:
            listed[a.name] = list_sessions(a.config_dir)
        except (chat.Error, OSError) as e:
            listed[a.name] = []
            notes.append(f"アカウント {a.name} の動いている会話を数えられない（{e}）。0 件とみなした")
    return count_running(listed), notes


def rank(accounts, limits, limit_percent, now, running=None, soon_hours=config.DEFAULT_RESET_SOON_HOURS,
         margin_minutes=config.DEFAULT_HOURS_MARGIN_MINUTES):
    """running は名 → 動いている会話の数（無い名は 0）。soon_hours は、週の枠の切り替わりを「近い」とみなす時間。
    margin_minutes は、使える時間帯の終わりの何分前から選ばないか。時間帯で選ばないアカウントは shut を真にする。
    控えが古い（limits.stale）アカウントは stale にし、known を偽にする（古い値で選ばない）。stale_over は、古い控えの最後の値で
    上限に達していたか（--move --if-limited が、取り直せない間も移るかを最後の値で決める。一時の混み合いで移さない）。
    eligible_at は、選べないアカウントがまた選べるようになる時刻（上限に達した枠の切り替わりと、使える時間帯の始まりの遅い方。
    分からなければ None）。"""
    running = running or {}
    rows = []
    for i, a in enumerate(accounts):
        raw = limits.get(a.name) if a.limits else None
        old = limits_.stale(raw, now)   # 古い控え（取り直せていない）は、使用率が分からない物と同じに扱う
        known = isinstance(raw, dict) and not old
        w = {k: _window(raw.get(k) if known else None, now) for k in WINDOWS}
        over = [k for k in WINDOWS if w[k]["used"] is not None and w[k]["used"] >= limit_percent]
        used = [w[k]["used"] for k in WINDOWS if w[k]["used"] is not None]
        last = [_window(raw.get(k), now)["used"] for k in WINDOWS] if old else []
        at = w["seven_day"]["resets_at"]
        closed = shut(a.hours, now, margin_minutes)
        ends = [w[k]["resets_at"] for k in over] + ([_reopens(a.hours, now)] if closed else [])
        why_not = [f"{k} が {w[k]['used']}% で上限 {limit_percent}% に達した" for k in over] + ([closed] if closed else [])
        rows.append({
            "name": a.name,
            "command": a.command,
            "config_dir": a.config_dir,
            "seven_day": w["seven_day"],
            "five_hour": w["five_hour"],
            "known": known,
            "stale": old,
            "stale_over": any(u is not None and u >= limit_percent for u in last),
            "eligible": not why_not,
            "reason": "、".join(why_not) or None,
            "eligible_at": max(ends) if why_not and None not in ends else None,
            "hours": a.hours.text if a.hours else None,
            "shut": closed is not None,
            "soon": known and at is not None and at - now <= soon_hours * 3600,
            "peak": max(used) if used else None,
            "running": running.get(a.name, 0),
            "_order": i,
        })
    rows.sort(key=lambda r: (
        not r["eligible"],
        not r["known"],
        not r["soon"],
        r["seven_day"]["resets_at"] if r["soon"] else (r["peak"] if r["peak"] is not None else math.inf),
        r["running"],
        r["_order"],
    ))
    for r in rows:
        del r["_order"]
    return rows


def early(rows, old, early_percent, reset_hours, now, wish=None, avoid=None):
    """区切りで早めに移すか（--move --if-changed と待ち受け）。rows は rank の並び、old は今のアカウント、wish は持ち主か窓口が
    --move で名指したが、ターンの途中で移せなかったアカウント（属性 company.move-to）。avoid は前に早めに移そうとして起動できなかった
    アカウント（属性 company.move-kept。選び直すと区切りのたびに止めて戻すのを繰り返す）。
    {"to": 移る先か None, "why": 移す訳か移さない訳, "kind": move・wish・soon・none・bad・hours・hours_none}。移す訳の無いとき（まだ目安に届かない・控えが無い）は None。
    - wish が在れば、それが選べて（上限に届かず、使える時間帯の中で）今のアカウントと違えば移る先にする（使用率の目安を待たない）。
    - 今のアカウントが使える時間帯の外か終わる手前（rank の shut）なら、選べるほかのアカウントのうち rank の順の頭へ移す（kind hours）。
    - 今のアカウントの 5 時間か週の枠が early_percent に達し、達した枠のどれかが reset_hours より先まで戻らなければ、
      使用率が分かり、高い方の枠が early_percent に届かないほかのアカウントのうち、rank の順の頭へ移す。"""
    if wish and wish != old:
        row = next((r for r in rows if r["name"] == wish), None)
        if row and row["eligible"] and wish != avoid:
            return {"to": wish, "why": f"--move で名指したアカウント {wish} へ、区切りまで待って移す", "kind": "wish"}
        bad = ("設定に無い" if row is None else "前に起動できなかった" if wish == avoid
               else "使える時間帯の外か終わる手前な" if row.get("shut") else "使用率が上限に達した")
        mine = next((r for r in rows if r["name"] == old), None)
        if not (mine and mine.get("shut")):   # 今のアカウントが時間帯で選べないなら、名指しが使えなくても下でほかへ移す
            return {"to": None, "why": f"--move で名指したアカウント {wish} は{bad}ので移さない", "kind": "bad"}
    mine = next((r for r in rows if r["name"] == old), None)
    if mine and mine.get("shut"):
        # 使える時間帯の外になる前に移す。移る先は rank の順の頭（使用率の分からないアカウントも、目安を見ずに選べる）
        to = next((r["name"] for r in rows if r["name"] not in (old, avoid) and r["eligible"]), None)
        if to is None:
            return {"to": None, "why": f"アカウント {old} は{mine['reason']}が、選べるほかのアカウントが無いので移さない", "kind": "hours_none"}
        return {"to": to, "why": f"アカウント {old} は{mine['reason']}（時間帯の外になる前に、区切りで移す）", "kind": "hours"}
    if not mine or not mine["known"]:
        return None
    hot = [k for k in WINDOWS if mine[k]["used"] is not None and mine[k]["used"] >= early_percent]
    if not hot:
        return None
    use = "・".join(f"{'週' if k == 'seven_day' else '5 時間'}の枠 {mine[k]['used']:g}%" for k in hot)
    lasting = [k for k in hot if mine[k]["resets_at"] is None or mine[k]["resets_at"] - now > reset_hours * 3600]
    if not lasting:
        return {"to": None, "why": f"アカウント {old} の{use}は目安 {early_percent}% に達したが、{reset_hours:g} 時間以内に戻るので移さない",
                "kind": "soon"}
    to = next((r["name"] for r in rows if r["name"] not in (old, avoid) and r["eligible"] and r["known"]
               and r["peak"] is not None and r["peak"] < early_percent), None)
    if to is None:
        return {"to": None, "why": f"アカウント {old} の{use}が目安 {early_percent}% に達したが、使用率がそれに届かないほかのアカウントが無いので移さない",
                "kind": "none"}
    return {"to": to, "why": f"アカウント {old} の{use}が目安 {early_percent}% に達した（上限に当たる前に、区切りで移す）", "kind": "move"}


def next_look(rows, now, wait):
    """--move --if-limited が、移る先が無いか一時の混み合いと見て待つときに、次に見直す Unix 時刻。選べるアカウントが在れば（待つのは
    今のアカウントが一時の混み合いのときか、使用率の分からない今のアカウントしか選べないとき）now + wait。無ければ、また選べるように
    なる時刻（rank の eligible_at）のうち最も早い物で、now + wait より早くしない（分からなければ now + wait）。"""
    if any(r["eligible"] for r in rows):
        return now + wait
    soon = [r["eligible_at"] for r in rows if r.get("eligible_at") is not None]
    return max(min(soon, default=now + wait), now + wait)


def _pct(v):
    return "不明" if v is None else f"{v:g}%"


def _left(sec):
    h, m = divmod(max(int(sec), 0) // 60, 60)
    return f"{h} 時間 {m} 分" if h else f"{m} 分"


def why(row, now, soon_hours=config.DEFAULT_RESET_SOON_HOURS):
    """順の頭に来た 1 件を選んだ訳を、人が読む 1 文にする。"""
    tail = f"動いている会話 {row['running']} 件"
    if row.get("stale"):
        return f"使用率が分からない（控えが {limits_.TRUST_HOURS} 時間より古い。取り直せていない）。{tail}"
    if not row["known"]:
        return f"使用率が分からない（控えが無いか、使用率の枠の無いアカウント）。{tail}"
    use = f"5 時間 {_pct(row['five_hour']['used'])}・週 {_pct(row['seven_day']['used'])}"
    if row["soon"]:
        return (f"週の枠が {_left(row['seven_day']['resets_at'] - now)}後に切り替わる（{soon_hours:g} 時間以内なので、"
                f"使わずに切り替わる分を先に使う）。{use}。{tail}")
    return f"{use} で、高い方 {_pct(row['peak'])} が選べるものの中で最も低い。{tail}"


def read_limits(limits_dir, names):
    """<limits_dir>/<名>.json を読む。無い・JSON でない・枠が表でないものは None。"""
    out = {}
    for n in names:
        try:
            raw = json.loads((pathlib.Path(limits_dir) / f"{n}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if not isinstance(raw, dict) or not all(isinstance(raw.get(k, {}), dict) for k in WINDOWS):
            raw = None
        out[n] = raw
    return out


def _default_ports(env):
    """会話の一覧・控えの取り直しの口。入口（dispatch.py）と同じ口の束（wiring.Ports）を使う。config_dir の無いアカウントの会話は、
    このコマンドを打った会話のアカウントでなく、作業場のペインで新しく起きるログインのシェルのフォルダで読むため（wiring.Ports.account_env）。"""
    import wiring
    return wiring.Ports(env=env)


def main(argv=None, env=os.environ, ports=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--out")
    ap.add_argument("--now", type=float, help="時刻を固定する（試験用）。省くと今")
    ap.add_argument("--pick", action="store_true", help="1 つ選び、名前と起動コマンドを出す")
    ap.add_argument("--json", action="store_true", help="--pick の結果を JSON で出す")
    ap.add_argument("--no-probe", action="store_true", help="--pick で、古い控えを取り直さない")
    a = ap.parse_args(argv)
    try:
        cfg = config.load(a.config, env)
    except config.ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    ports = ports or _default_ports(env)
    now = a.now or ports.now()
    metered = [x.name for x in cfg.accounts if x.limits]
    if a.pick and not a.no_probe:
        ports.refresh_limits(cfg, metered, force=False)
    running, notes = gather_running(cfg.accounts, ports.list_sessions)
    rows = rank(cfg.accounts, ports.read_limits(cfg.limits_dir, metered), cfg.limit_percent, now, running,
                cfg.reset_soon_hours, cfg.hours_margin_minutes)
    if not a.pick:
        jsonio.dump({"accounts": rows, "notes": notes}, a.out)
        return 0
    head = rows[0] if rows and rows[0]["eligible"] else None
    pick = None if head is None else {"name": head["name"], "command": head["command"], "config_dir": head["config_dir"],
                                      "why": why(head, now, cfg.reset_soon_hours)}
    if a.json:
        jsonio.dump({"pick": pick, "accounts": rows, "notes": notes}, a.out)
    elif pick:
        print(f"{pick['name']}: {pick['command']} — {pick['why']}")
    else:
        print("選べるアカウントが無い: " + "／".join(f"{r['name']}（{r['reason']}）" for r in rows), file=sys.stderr)
    if not a.json:
        for n in notes:
            print(f"注記: {n}", file=sys.stderr)
    return 0 if pick else 1


if __name__ == "__main__":
    sys.exit(main())
