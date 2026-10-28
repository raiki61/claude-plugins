#!/usr/bin/env python3
"""入口の --rent-effect（借りるか買うかの部品〔rent-or-buy〕が効いたかの集計の点）。dispatch.py の一部で、landorder.py と同じ入口の層に置く。

期間を渡すと、会話の記録（会話の口の talk_files・talk_events）を読み、部品が足した・変えた物を、部品の無かった世界（keepalive は
送らない、compact は区切りで文脈が wake.COMPACT_FLOOR 以上のときと自動の compact だけ）と同じ記録の上で比べた差を出す。
指標の定義・分け方・比べる基準・見積もれない物の前提は docs/rent-effect.md。数え方を変えるときはそちらも直す。
閉じた待ちの結果は、部品の判断の記録の鍵（wake_hook.decision_key）に結果の行として足す（rent-or-buy outcome。同じ鍵は重ねない）。
"""

import calendar
import json
import math
import time

import rentx
from ports import chat
from nodes import wake

# 会話の記録の中で、待ち受けが渡した文を見分ける印（試験 test_rentfx が、今の文に含まれることを確かめる）
ASK_MARK = "good time to compact"                      # compact の焦点の問い（wake_hook.CONSULT_TEXT・TURN_CONSULT_TEXT）
PING_HEAD = "keepalive"                                # keepalive の文の頭（role.KEEPALIVE_TEXT。10-23 の版は「（keepalive: …」）
JUDGED_MARK = "費用の判断で会話を compact した"         # 部品の判断で打った compact の後の続き（wake_hook.compact_turn）
CUT_MARK = "区切り〔--compact〕で会話を compact した"   # 区切りで打った compact の後の続き（同じ）
MARKS = (ASK_MARK, PING_HEAD, JUDGED_MARK, CUT_MARK)

FIVE_MIN, HOUR = 300, 3600
WARM_SHARE = 0.5      # 要求の文脈のうち読みがこの割合以上なら、キャッシュが生きていたと見る
BUCKETS = (("≤5分", FIVE_MIN), ("5分〜1時間", HOUR), ("1〜12時間", 12 * HOUR), ("12時間超", math.inf))
OPEN = "終わらなかった"   # 次の本当の要求が記録に無い待ち
BASE_AUTO_LINE = 200000   # 期間に自動の compact が 1 回も無いときの、基準の世界の自動の compact の線の下の端（会社の形の autoCompactWindow）
# 自動の compact の線を書いていない会話の線（1M の窓のモデルの既定。chat.AUTO_COMPACT_SETTING の注の文書の約 967K）
DEFAULT_LINE = 967000


def _stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _ctx(r):
    return r["input"] + r["write_5m"] + r["write_1h"] + r["read"]


def _warm(r):
    return r["read"] >= WARM_SHARE * max(1, _ctx(r))


class Prices:
    """モデルごとの 1 トークンの額（部品の prices）。引けないモデルの要求は数えず、その数を unknown に残す。"""

    def __init__(self, ask=rentx.prices):
        self.ask, self.rates, self.unknown = ask, {}, {}

    def of(self, model):
        if model not in self.rates:
            got, why = self.ask(model)
            self.rates[model] = got.get("rates") if got else None
            if why:
                self.unknown[model] = why
        return self.rates[model]

    def cost(self, r):
        p = self.of(r["model"])
        return 0.0 if p is None else sum(r[k] * p[k] for k in ("input", "write_5m", "write_1h", "read", "output"))

    def rate(self, r, name):
        p = self.of(r["model"])
        return 0.0 if p is None else p[name]


def turns(events):
    """出来事を要求ごとに (要求, そのターンの種類) にする。種類は ping（keepalive の文で始まったターン）・ask（焦点の問いで始まった
    ターン）・real（ほか）。compact は ("compact", 出来事) で並べ、その種類（judged・cut・auto・person）は後に続く文の印で決める。
    /clear は ("clear", 出来事)。要求には life（キャッシュの寿命の秒。その要求か前の要求のうち、最後に書いた物の書き込みの寿命）を足す。"""
    out, kind, pending, life = [], "real", None, HOUR
    for e in events:
        if e["at"] is None:   # 時刻の無い行は待ちの長さを測れない
            continue
        if e["type"] == "said":
            text = e["text"]
            if e["by"] == "hook" and ASK_MARK in text:
                kind = "ask"
            elif e["by"] == "hook" and text.lstrip("（(").startswith(PING_HEAD):
                kind = "ping"
            else:
                kind = "real"
            if pending is not None and e["by"] == "hook":
                pending["how"] = "judged" if JUDGED_MARK in text else "cut" if CUT_MARK in text else pending["how"]
            if e["by"] == "command" and e["text"] == chat.CLEAR:
                out.append(("clear", e))
        elif e["type"] == "compact":
            pending = dict(e, how="auto" if e["trigger"] == "auto" else "person")
            out.append(("compact", pending))
        elif e["type"] == "request":
            pending = None if kind == "real" else pending
            if e["write_1h"] or e["write_5m"]:
                life = HOUR if e["write_1h"] else FIVE_MIN
            out.append((kind, dict(e, life=life)))
    return out


def _bucket(gap):
    return OPEN if gap is None else next(name for name, top in BUCKETS if gap <= top)


def _blank():
    return {"waits": 0, "sent": 0, "sent_cost": 0.0, "avoided": 0.0, "avoided_low": 0.0, "failed": 0, "failed_sent_cost": 0.0}


class Session:
    """1 つの会話の記録の上の比べ。"""

    def __init__(self, sid, rows, prices, since, until):
        self.sid, self.rows, self.p, self.since, self.until = sid, rows, prices, since, until

    def _in(self, t):
        return t is not None and self.since <= t < self.until

    def _write(self, r):
        return self.p.rate(r, "write_1h" if r["life"] == HOUR else "write_5m")

    def waits(self):
        """本当の要求の間の待ちごとに {before, after（次の本当の要求。無ければ None）, gap, warmers（その間の ping・ask の要求）,
        cut（間に compact か /clear が在ったか。在れば after は作り直した文脈を読むので、寿命の比べに使わない）}。"""
        out, last, between, cut = [], None, [], False
        for kind, r in self.rows:
            if kind in ("ping", "ask"):
                between.append((kind, r))
            elif kind in ("compact", "clear"):
                cut = True
            elif kind == "real":
                if last is not None:
                    out.append({"before": last, "after": r, "gap": r["at"] - last["at"], "warmers": between, "cut": cut})
                last, between, cut = r, [], False
        if last is not None:
            out.append({"before": last, "after": None, "gap": None, "warmers": between, "cut": cut})
        return out

    def linger(self):
        """送った keepalive と問いのターンが文脈に足したトークンを、後の本当の要求が読み続けた額（compact・/clear まで）。"""
        total, carried, prev = 0.0, 0, None
        for kind, r in self.rows:
            if kind in ("compact", "clear"):
                carried = 0
            elif kind in ("ping", "ask") and prev is not None:
                carried += max(0, _ctx(r) + r["output"] - _ctx(prev) - prev["output"])
            elif kind == "real" and self._in(r["at"]) and carried:
                total += carried * (self.p.rate(r, "read") if _warm(r) else self._write(r))
            if kind not in ("compact", "clear"):
                prev = r
        return total

    def keepalive(self, table, rewrote):
        """待ちの長さと温めた物ごとの表に足す。rewrote は温めなかった待ちで寿命を超えた物の [書き直した数, 数]。
        - avoided: 寿命を超えた待ちの後の要求が実際は読めた（WARM_SHARE）とき、読んだトークンを書き直さずに済んだ額
        - failed・failed_sent_cost: 寿命を超えた待ちで、送ったのに後の要求が書き直した数と、その待ちで送った額（両方払った分）"""
        for w in self.waits():
            if not self._in(w["before"]["at"]):
                continue
            pings = [r for k, r in w["warmers"] if k == "ping"]
            warmer = "keepalive" if pings else "問いだけ" if w["warmers"] else None
            life, after = w["before"]["life"], w["after"]
            if warmer is None:
                if after is not None and not w["cut"] and w["gap"] > life:
                    rewrote[0] += not _warm(after)
                    rewrote[1] += 1
                continue
            row = table.setdefault(f"{_bucket(w['gap'])}・{warmer}", _blank())
            sent = sum(self.p.cost(r) for r in pings)
            row["waits"] += 1
            row["sent"] += len(pings)
            row["sent_cost"] += sent
            if after is None or w["cut"] or w["gap"] <= life:
                continue
            if _warm(after):
                row["avoided"] += after["read"] * (self._write(w["before"]) - self.p.rate(after, "read"))
            else:
                row["failed"] += 1
                row["failed_sent_cost"] += sent

    def asks(self):
        """問いのターンの数と額（問いの答えで compact したか延ばしたかは数えない。compact は compacts が数える）。"""
        reqs = [r for k, r in self.rows if k == "ask" and self._in(r["at"])]
        return len(reqs), sum(self.p.cost(r) for r in reqs)

    def compacts(self, out, auto_line, auto_post):
        """部品の無かった世界（基準）の文脈を、実際の文脈との差 delta で追い、compact の得失を out に足す（docs/rent-effect.md の「compact」）。
        実際の compact のうち、基準でも同じ所で打つ物（人の compact・基準の文脈が COMPACT_FLOOR 以上の区切り・delta が 0 以上のときの自動）は
        delta を 0 に戻して差に数えない。ほか（部品の判断・基準の文脈が COMPACT_FLOOR 未満の区切り・基準ではまだ線に着かない自動）は、実際
        だけが打つ compact で、delta に pre − post を足す。基準の文脈（実際の文脈 + delta）が auto_line に着いた本当の要求の前で、基準だけが
        自動の compact を打ち、基準の文脈を auto_post とその要求の新しい部分にする（delta は負になりうる。早く縮めた世界は次も早く縮める）。
        - summary・base_summary: 実際だけ・基準だけが打った compact の要約の見積もり（前の文脈を読み、後の文脈を書き出す額）
        - first: 実際だけが compact した後の最初の要求の、基準の額（前の文脈を読み〔寿命の内なら〕、新しい部分を書く）− 実際の額
        - base_first: 基準だけが compact した後の最初の要求の、基準の額（全部を書く）− 実際の額
        - kept: ほかの本当の要求の delta × 単価（読めた要求は読み、書き直した要求は書き込みの単価）
        差はどれも「基準の額 − 実際の額」で、正なら部品が安くした。"""
        delta, fresh_a, fresh_b, prev = 0, None, False, None
        for kind, r in self.rows:
            if kind == "clear":
                delta, fresh_a, fresh_b = 0, None, False
                continue
            if kind == "compact":
                inside = self._in(r["at"])
                if r["how"] == "person" or r["how"] == "cut" and r["pre"] + delta >= wake.COMPACT_FLOOR or r["how"] == "auto" and delta >= 0:
                    out["shared"] += inside
                    delta, fresh_a, fresh_b = 0, None, False
                    continue
                if inside and prev is not None:
                    out["count"][r["how"]] += 1
                    out["summary"] += r["pre"] * self.p.rate(prev, "read") + r["post"] * self.p.rate(prev, "output")
                fresh_a = (r, prev, delta)
                delta += max(0, r["pre"] - r["post"])
                continue
            if kind != "real":
                prev = r
                continue
            inside, ctx, warm = self._in(r["at"]), _ctx(r), _warm(r)
            p_r, p_w = self.p.rate(r, "read"), self._write(r)
            new = r["input"] + r["write_5m"] + r["write_1h"]
            actual = r["input"] * self.p.rate(r, "input") + r["write_5m"] * self.p.rate(r, "write_5m") \
                + r["write_1h"] * self.p.rate(r, "write_1h") + r["read"] * p_r
            if not fresh_b and ctx + delta >= auto_line:
                if inside:
                    out["base_auto"] += 1
                    out["base_summary"] += (ctx + delta) * p_r + auto_post * self.p.rate(r, "output")
                base_ctx = auto_post + (max(0, new - fresh_a[0]["post"]) if fresh_a else new)
                delta, fresh_b = base_ctx - ctx, True
            if fresh_a is not None and not fresh_b:
                c, before, was = fresh_a
                alive = before is not None and r["at"] - before["at"] <= before["life"]
                added = max(0, new - c["post"])
                diff, slot = (c["pre"] + was) * (p_r if alive else p_w) + added * p_w - actual, "first"
            elif fresh_b:
                diff, slot = (ctx + delta) * p_w - actual, "base_first"
            else:
                diff, slot = delta * (p_r if warm else p_w), "kept"
            if inside:
                out[slot] += diff
            fresh_a, fresh_b, prev = None, False, r


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def _comp_blank():
    return {"count": {"judged": 0, "cut": 0, "auto": 0}, "shared": 0, "summary": 0.0, "first": 0.0, "kept": 0.0,
            "base_auto": 0, "base_summary": 0.0, "base_first": 0.0}


def lines_of(s, seen_line):
    """基準の世界の自動の compact の線の幅 (下, 上)。会話に実際の自動の compact が在ればその pre の中央値（上も下も同じ）。無ければ、
    下は全体の中央値 seen_line と、その会話で縮まずに着いた最大の文脈の大きい方（線はそれより上に在る）、上は線を書いていない会話の
    既定 DEFAULT_LINE（線を書いたかは記録から読めない）。"""
    own = _median([r["pre"] for k, r in s.rows if k == "compact" and r["how"] == "auto"])
    if own:
        return own, own
    top = max([_ctx(r) for k, r in s.rows if k == "real"] or [0])
    return max(seen_line, top), max(DEFAULT_LINE, top)


def measure(since, until, home=None, prices=None, files=None):
    """期間 [since, until)（秒）の集計の点。返す表の形は docs/rent-effect.md の「出力」。"""
    p = prices or Prices()
    table, rewrote, asked = {}, [0, 0], [0, 0.0]
    comp = {"low": _comp_blank(), "high": _comp_blank()}
    linger, sessions = 0.0, {}
    for sid, path in sorted((files if files is not None else chat.talk_files(home, since)).items()):
        events = chat.talk_events(path, MARKS)
        if events is not None:
            sessions[sid] = Session(sid, turns(events), p, since, until)
    autos = [r for s in sessions.values() for k, r in s.rows if k == "compact" and r["how"] == "auto"]
    # 基準の世界の自動の compact の後の文脈は、実際の自動の compact の post の中央値（無ければ compact 全部の post の中央値）
    seen_line = _median([c["pre"] for c in autos]) or BASE_AUTO_LINE
    auto_post = _median([c["post"] for c in autos]) or _median(
        [r["post"] for s in sessions.values() for k, r in s.rows if k == "compact"]) or 0
    for s in sessions.values():
        s.keepalive(table, rewrote)
        n, cost = s.asks()
        asked[0] += n
        asked[1] += cost
        low, high = lines_of(s, seen_line)
        s.compacts(comp["low"], low, auto_post)
        s.compacts(comp["high"], high, auto_post)
        linger += s.linger()
    q = rewrote[0] / rewrote[1] if rewrote[1] else None
    for row in table.values():
        row["avoided_low"] = row["avoided"] * (q if q is not None else 0)
    ka = {k: sum(r[k] for r in table.values()) for k in _blank()}
    for c in comp.values():
        c["net"] = c["kept"] + c["first"] + c["base_first"] + c["base_summary"] - c["summary"] - asked[1]
        n_comp = c["count"]["judged"] + c["count"]["cut"]
        c["break_even_redo"] = c["net"] / n_comp if n_comp else None
    comp.update(seen_line=seen_line, auto_post=auto_post, auto_seen=len(autos))
    ka_low, ka_high = ka["avoided_low"] - ka["sent_cost"], ka["avoided"] - ka["sent_cost"]
    nets = sorted((comp["low"]["net"], comp["high"]["net"]))
    return {"since": _stamp(since), "until": _stamp(until), "sessions": len(sessions),
            "keepalive": {"rows": dict(sorted(table.items())), "total": ka, "net": {"low": ka_low, "high": ka_high},
                          "expired_without_warming": {"rewrote": rewrote[0], "waits": rewrote[1], "share": q}},
            "asks": {"turns": asked[0], "cost": asked[1]}, "linger": linger, "compact": comp,
            "net": {"low": ka_low - linger + nets[0], "high": ka_high - linger + nets[1]},
            "unknown_models": p.unknown}, sessions


def outcomes(sessions, records, prices):
    """判断の記録の行（鍵の付いた keepalive と compact）に結ぶ結果の行。閉じた待ちの物だけ。返すのは (行の並び, 鍵の無い判断の数)。"""
    out, keyless = [], 0
    for row in records:
        scene, facts, said = row.get("scene"), row.get("input") or {}, row.get("output") or {}
        if scene not in ("keepalive", "compact") or said.get("error"):
            continue
        key = facts.get("key")
        if not isinstance(key, str):
            keyless += 1
            continue
        s = sessions.get(key.split("/", 1)[0])
        at = _epoch(row.get("ts"))
        if s is None or at is None:
            continue
        got = _outcome(s, scene, said, at, prices)
        if got is not None:
            out.append({"key": key, **got})
    return out, keyless


def _epoch(text):
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def _outcome(s, scene, said, at, p):
    w = next((w for w in s.waits() if w["after"] and w["before"]["at"] <= at < w["after"]["at"]), None)
    if w is None or w["cut"] and scene == "keepalive":
        return None
    after = w["after"]
    if scene == "compact":
        return {"paid": 0.0, "alternative": None, "detail": {"action": said.get("action"), "gap": w["gap"]}}
    prev = max([w["before"]] + [r for _, r in w["warmers"] if r["at"] <= at], key=lambda r: r["at"])
    life = prev["life"]
    w_rate = s._write(prev)
    lapse = after["read"] * (w_rate - p.rate(after, "read")) if after["at"] > prev["at"] + life else 0.0
    if said.get("action") == "rent":
        sent = next((r for k, r in w["warmers"] if k == "ping" and r["at"] > at), None)
        return {"paid": p.cost(sent) if sent else 0.0, "alternative": lapse, "detail": {"action": "rent", "gap": w["gap"]}}
    need = int((after["at"] - prev["at"]) // life)
    rewrite = 0.0 if _warm(after) else p.cost(after)
    rent = said.get("rent") if isinstance(said.get("rent"), (int, float)) else None
    return {"paid": rewrite, "alternative": None if rent is None else need * rent, "detail": {"action": "buy", "gap": w["gap"]}}


def _money(x):
    return f"${x:,.2f}"


def render(got):
    """集計の点を人が読む行にする。"""
    ka, comp = got["keepalive"], got["compact"]
    ex = ka["expired_without_warming"]
    lines = [f"期間 {got['since']} 〜 {got['until']}（読んだ会話 {got['sessions']} 本）", "",
             "keepalive（待ちの長さ・温めた物: 待ち / 送った数 / 送った額 / 避けた書き直し 下〜上 / 送ったのに書き直した数・その待ちで送った額）"]
    for name, r in ka["rows"].items():
        lines.append(f"- {name}: {r['waits']} / {r['sent']} / {_money(r['sent_cost'])} / "
                     f"{_money(r['avoided_low'])}〜{_money(r['avoided'])} / {r['failed']}・{_money(r['failed_sent_cost'])}")
    share = "測れない" if ex["share"] is None else f"{ex['share']:.0%}"
    lines += [f"- 温めずに寿命を超えた待ち {ex['waits']} 本のうち、書き直した割合 {share}（避けた額の下の端に掛ける）",
              f"- keepalive の差（避けた額 − 送った額）: {_money(ka['net']['low'])}〜{_money(ka['net']['high'])}", "",
              f"送った文と答えが文脈に残って読まれた額: {_money(got['linger'])}", "",
              f"compact（基準の世界の自動の compact の線の、下の端 / 上の端。線は会話の実際の自動の compact の中央値か、無ければ下は全体の"
              f"中央値 {comp['seen_line']} とその会話の最大の文脈の大きい方、上は {DEFAULT_LINE}。基準の自動の compact の後の文脈 {comp['auto_post']}）",
              f"- 問いのターン {got['asks']['turns']} 要求・{_money(got['asks']['cost'])}"]
    for name in ("low", "high"):
        c = comp[name]
        lines += [f"- {'下' if name == 'low' else '上'}の端: 実際だけが打った compact（部品の判断 {c['count']['judged']}・区切り "
                  f"{c['count']['cut']}・自動 {c['count']['auto']}。両方で打った {c['shared']}）の要約 {_money(c['summary'])}"
                  f"・基準だけが打った自動の compact {c['base_auto']} 回の要約 {_money(c['base_summary'])}"
                  f"・縮めた後の最初の要求の差 {_money(c['first'])}（基準だけ {_money(c['base_first'])}）"
                  f"・文脈の大きさの差 {_money(c['kept'])}・計 {_money(c['net'])}"
                  + ("" if c["break_even_redo"] is None else f"（部品の compact 1 回あたり {_money(c['break_even_redo'])} を超えるやり直しで損）")]
    lines += ["",
              f"部品が無かった世界との差（得が正）: {_money(got['net']['low'])}〜{_money(got['net']['high'])}"]
    if got["unknown_models"]:
        lines.append("単価を引けず数えなかったモデル: " + "、".join(sorted(got["unknown_models"])))
    if "outcomes" in got:
        o = got["outcomes"]
        lines.append(f"判断の記録の結果の行: 足した {o.get('recorded', 0)}・前から在った {o.get('duplicates', 0)}・"
                     f"鍵の無い昔の判断 {o['keyless']}" + (f"（{o['why']}）" if o.get("why") else ""))
    return "\n".join(lines)


def main(since, until, as_json=False, home=None):
    """--rent-effect の本体。since・until は YYYY-MM-DDTHH:MM:SSZ の字（until を省けば今）。"""
    now = time.time()
    t0 = _epoch(since) if since else now - 7 * 86400
    t1 = _epoch(until) if until else now
    if t0 is None or t1 is None or t0 >= t1:
        print("止めた: --since・--until は YYYY-MM-DDTHH:MM:SSZ の字で、--since が前")
        return 2
    p = Prices()
    got, sessions = measure(t0, t1, home, p)
    records, why = rentx.records(_stamp(t0), _stamp(t1))
    rows, keyless = outcomes(sessions, records or [], p)
    written, why2 = rentx.outcome(rows) if rows else ({"recorded": 0, "duplicates": 0}, None)
    got["outcomes"] = dict(written or {"recorded": 0, "duplicates": 0}, keyless=keyless, why=why or why2)
    print(json.dumps(got, ensure_ascii=False, indent=1) if as_json else render(got))
    return 0
