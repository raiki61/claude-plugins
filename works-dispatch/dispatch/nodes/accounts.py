#!/usr/bin/env python3
"""accounts ノード: 使用率の控えと動いている会話の数から、選べるアカウントとその順を決める（設計書のセクション 2 の 3）。外には書かない
（--pick だけは、古い控えを取り直す。limits.py の probe と同じく、古いアカウントにだけ出力 0 トークンで問い合わせる）。

- 週の枠（seven_day）か 5 時間の枠（five_hour）の使用率が上限に達したアカウントは選ばない。使用率は 1% 刻みの整数で届き、ちょうど上限の値は上限を超えている見込みがあるので、上限ちょうども選ばない。
- 切り替わりの時刻（resets_at）が過ぎた枠は、切り替わった後なので使用率 0 とみなす。
- 選べるものを、1 つの点数（score）の高い順に並べる（持ち主の決め 2026-10-29「アルゴリズム化か単純計算でもっと勾配つけたいね」。
  前の 2026-10-16 の段の決まり〔週の切り替わりが 24 時間以内なら先、ほかは使用率の低い順〕を置き換えた）。点数は pace の式で、
  週の枠の上限までの残り（上限 − 使用率）を週の切り替わりまでの時間で割った「1 時間あたり使ってよい量」に、5 時間の枠の上限までの残りの
  割合を掛けた物。残りが多く切り替わりの近いアカウントほど高く（使わずに切り替わる分を残さない）、残りが少なく切り替わりの遠いアカウントほど
  低い（切り替わりの前に上限に当たらない）。5 時間の枠を使うほど滑らかに下がる（先に食い潰さない）。
  同じ点数なら、そのアカウントで動いている会話の数の少ない順、次に設定の順。
- 使える時間帯（設定の hours）の外のアカウントと、時間帯の終わりまで設定の hours_margin_minutes（既定 30 分。ちょうども含む）を切ったアカウントは選ばない。
  終わりで要求が断られ、ターンの途中で切られるため。日をまたぐ時間帯は始まった日の物として見る。
- 控えが無い・読めないアカウントは、使用率が分からないものとして選べる側に残し、順の最後に置く（D7）。
- 使用率の枠の無いアカウント（設定の limits = false。Ollama・Foundry など）は控えを読まず、控えの無いものと同じに扱う。
- 名指しのときだけ使うアカウント（設定の named_only = true。弱いモデルへ読み替わる中継など）は、自動では選ばない（eligible を偽にする）。
  使用率と時間帯で外れていなければ named_ok を真にし（訳は NAMED_ONLY）、会社の形の役か受け持ちが account で名指したとき（prefer）と、
  --move --account・区切りの名指し（early の wish）で名指したときだけ使う。会社の形の名指しが使えなければ、ほかのアカウントへ回さない（prefer の strict）。
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
WEEK_HOURS = 7 * 24   # 週の枠の長さ。切り替わりの時刻が分からない週の枠は、今から 1 週間で切り替わるとみなす
MIN_HOURS = 1   # 週の切り替わりまでの時間の下限。切り替わりの直前で点数が際限なく大きくならないため
RUNNING_STATES = ("working", "blocked")  # 背景の会話の state のうち、動いているもの
NAMED_ONLY = "名指しのときだけ使うアカウント（設定の named_only = true）"   # 自動で選ばない訳


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


def pace(seven_day, five_hour, limit_percent, now):
    """選ぶ順の点数。週の枠の上限までの残り（%）÷ 週の切り替わりまでの時間（MIN_HOURS より短くしない）× 5 時間の枠の上限までの残りの割合。
    枠は _window の形。使用率の分からない枠は 0% とみなす。上限に達した枠が在れば 0。"""
    used7, used5 = seven_day["used"] or 0, five_hour["used"] or 0
    at = seven_day["resets_at"]
    left = WEEK_HOURS if at is None else max((at - now) / 3600, MIN_HOURS)
    return (max(limit_percent - used7, 0) / left) * (max(limit_percent - used5, 0) / limit_percent)


def rank(accounts, limits, limit_percent, now, running=None, margin_minutes=config.DEFAULT_HOURS_MARGIN_MINUTES):
    """running は名 → 動いている会話の数（無い名は 0）。点数（score）は pace。使用率の分からないアカウントは None で、選べる物の後に並ぶ。
    margin_minutes は、使える時間帯の終わりの何分前から選ばないか。時間帯で選ばないアカウントは shut を真にする。
    控えが古い（limits.stale）アカウントは stale にし、known を偽にする（古い値で選ばない）。stale_over は、古い控えの最後の値で
    上限に達していたか（--move --if-limited が、取り直せない間も移るかを最後の値で決める。一時の混み合いで移さない）。
    eligible_at は、選べないアカウントがまた選べるようになる時刻（上限に達した枠の切り替わりと、使える時間帯の始まりの遅い方。
    分からなければ None。名指しのときだけ使うアカウントは自動では選べるようにならないので None）。
    named_only は設定の named_only。named_ok は、名指せば使える（named_only で、上限にも時間帯にも外れていない）か。"""
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
        closed = shut(a.hours, now, margin_minutes)
        ends = [w[k]["resets_at"] for k in over] + ([_reopens(a.hours, now)] if closed else [])
        why_not = [f"{k} が {w[k]['used']}% で上限 {limit_percent}% に達した" for k in over] + ([closed] if closed else [])
        named_only = getattr(a, "named_only", False)
        rows.append({
            "name": a.name,
            "command": a.command,
            "config_dir": a.config_dir,
            "seven_day": w["seven_day"],
            "five_hour": w["five_hour"],
            "known": known,
            "stale": old,
            "stale_over": any(u is not None and u >= limit_percent for u in last),
            "eligible": not why_not and not named_only,
            "reason": "、".join(why_not) or (NAMED_ONLY if named_only else None),
            "named_only": named_only,
            "named_ok": named_only and not why_not,
            "eligible_at": max(ends) if why_not and None not in ends and not named_only else None,
            "hours": a.hours.text if a.hours else None,
            "shut": closed is not None,
            "score": pace(w["seven_day"], w["five_hour"], limit_percent, now) if known else None,
            "peak": max(used) if used else None,
            "running": running.get(a.name, 0),
            "_order": i,
        })
    rows.sort(key=lambda r: (
        not r["eligible"],
        not r["known"],
        -(r["score"] or 0),
        r["running"],
        r["_order"],
    ))
    for r in rows:
        del r["_order"]
    return rows


def count_open(items):
    """1 つのアカウントの `claude agents --json` の並びのうち、終わっていない会話の数。背景の会話は state が done・failed・stopped の
    どれでもないもの（待機中も数える。次の頼みでいつ動き出すか分からない）、state の無い対話の会話は動いているもの（is_running）。"""
    return sum(1 for s in items if isinstance(s, dict) and (s.get("state") not in (None, "done", "failed", "stopped")
                                                             if s.get("state") is not None else is_running(s)))


def prefer(rows, wish, open_count, who, max_open=1, strict=False):
    """会社の形の役か受け持ちが名指したアカウント wish（role.launch_account）を、使えるなら rows（rank の並び）の頭に出す。(並び, 注記)。
    open_count は wish のアカウントの終わっていない会話の数（count_open）、who は名指した所（注記に出す。例「役 写しの後始末」）。
    max_open は wish のアカウントに開いていてよい終わっていない会話の数（設定の max_open。既定 1 は、同時に 1 件しか走らない口に合わせた数）。
    使えないと見るのは、rows に無い（設定に無いか、同じ名前の会話が在って避けた）・選べない（使用率の上限か、使える時間帯の外か終わる
    手前。rank の eligible。名指しのときだけ使うアカウントは named_ok）・終わっていない会話が max_open 件以上在る、とき。そのときは rows のまま
    （今の選び方の順）にし、名指しを使わなかった訳を注記にする。strict（wish が名指しのときだけ使うアカウント）なら、ほかのアカウントへ
    回さずに空の並びを返す（そのアカウントでしか動かないモデルを名指した役が、黙って別のモデルで立たないため）。名指しが無ければ (rows, None)。"""
    if not wish:
        return rows, None
    row = next((r for r in rows if r["name"] == wish), None)
    bad = ("振れるアカウントの中に無い（設定の accounts に無いか、同じ名前の会話が在るので避けた）" if row is None
           else row["reason"] if not (row["eligible"] or row.get("named_ok"))
           else f"終わっていない会話が {open_count} 件在り、設定の max_open（{max_open}）に達した" if open_count >= max_open else None)
    if bad and strict:
        return [], (f"{who} が名指したアカウント {wish} は{bad}。名指しのときだけ使うアカウント（named_only）なので、"
                    "ほかのアカウントでは立てない")
    if bad:
        return rows, f"{who} が名指したアカウント {wish} は{bad}ので、使用率の順で選ぶ"
    return named(rows, wish), None


def named(rows, name):
    """名指したアカウント name を rows（rank の並び）の頭に出す。名指しのときだけ使うアカウントで名指せば使える（named_ok）なら、
    その行を選べる（eligible）にする（--move の起動し直し〔only_account〕と prefer が使う）。ほかの行はそのまま。"""
    row = next((r for r in rows if r["name"] == name), None)
    if row is None:
        return rows
    return [{**row, "eligible": True} if row.get("named_ok") else row] + [r for r in rows if r is not row]


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
        if row and (row["eligible"] or row.get("named_ok")) and wish != avoid:
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


def why(row, now):
    """順の頭に来た 1 件を選んだ訳を、人が読む 1 文にする。"""
    tail = f"動いている会話 {row['running']} 件"
    if row.get("stale"):
        return f"使用率が分からない（控えが {limits_.TRUST_HOURS} 時間より古い。取り直せていない）。{tail}"
    if not row["known"]:
        return f"使用率が分からない（控えが無いか、使用率の枠の無いアカウント）。{tail}"
    at = row["seven_day"]["resets_at"]
    reset = "週の枠の切り替わりの時刻は不明" if at is None else f"週の枠は {_left(at - now)}後に切り替わる"
    return (f"5 時間 {_pct(row['five_hour']['used'])}・週 {_pct(row['seven_day']['used'])}（{reset}）で、"
            f"点数 {row['score']:.2f}（週の残り ÷ 切り替わりまでの時間 × 5 時間の残りの割合）が"
            f"選べるものの中で最も高い。{tail}")


def overview(accts, env):
    """アカウントの一覧の 1 件ずつの {name, named_only, max_open, limits, hours, models}。models はモデルの別名の読み替え先
    （chat.model_aliases。正本はそのアカウントの設定のフォルダの settings.json で、ここでは読むだけ）。--tree と --check が出す。"""
    return [{"name": a.name, "named_only": getattr(a, "named_only", False), "max_open": getattr(a, "max_open", 1), "limits": a.limits,
             "hours": a.hours.text if a.hours else None,
             "models": chat.model_aliases(config.effective_config_dir(a, env), env)} for a in accts]


ALIAS_LABEL = {"subagent": "サブエージェント", "default": "既定"}   # overview の models のキーで、別名（opus など）でない物の出し方


def overview_lines(items):
    """overview の人が読む行。見出しと 1 アカウント 1 行。読み替え先は、同じモデルに読み替わる別名をまとめて出す。"""
    out = ["アカウント（選び方: 自動 は使用率の順で選ぶ、名指しだけ は会社の形の account か --move --account で名指したときだけ。"
           "モデルは別名の読み替え先と既定のモデルで、各アカウントの設定のフォルダの settings.json の env と model から読む。そこに書いていない物は出さない）:"]
    for x in items:
        to = {}
        for alias, model in x["models"].items():
            to.setdefault(model, []).append(ALIAS_LABEL.get(alias, alias))
        out.append("  " + "  ".join([x["name"], "名指しだけ" if x["named_only"] else "自動"]
                                    + ([f"名指しで同時 {x['max_open']} 件まで"] if x.get("max_open", 1) != 1 else [])
                                    + ([] if x["limits"] else ["使用率の枠なし"])
                                    + ([f"時間帯 {x['hours']}"] if x["hours"] else [])
                                    + (["モデル " + "、".join(f"{'・'.join(a)} → {m}" for m, a in to.items())] if to else [])))
    return out


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
                margin_minutes=cfg.hours_margin_minutes)
    if not a.pick:
        jsonio.dump({"accounts": rows, "notes": notes}, a.out)
        return 0
    head = rows[0] if rows and rows[0]["eligible"] else None
    pick = None if head is None else {"name": head["name"], "command": head["command"], "config_dir": head["config_dir"],
                                      "why": why(head, now)}
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
