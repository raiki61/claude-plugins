"""場面の事実を中心 decide の入力に直す。

keepalive: 借りる＝1 本の費用（読み × 文脈 + 書き込み × 1 本の書き込み + 出力 × 1 本の出力）、買う＝切れの上乗せ
（(書き込み − 読み) × 文脈）。
compact: 借りる＝この 1 回で余分に読む額（(文脈 − compact の後の文脈) × 読み）、買う＝縮める費用 F' + 借りる + 問い合わせの費用。
F' は compact の後の最初の要求の書き込み × 書き込み + 読み × 読み + 要約の出力 × 出力。要約の要求は今の文脈を読むので
この 1 本は借りるを浮かせられず、買うに借りるを足す（規則 spent + rent ≥ buy は spent ≥ F' + 問い合わせの費用 になる）。
単価の段（10 万トークン超で上がる）は、送る文の大きさで選ぶ。compact の後の書き込みと読みは compact の後の文脈、
出力は縮める前の文脈の大きさで選ぶ。
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import rent_or_buy

from . import prices

_CORE_KEYS = ("hazard", "miss", "policy")
_COMPACT_CORE_KEYS = ("forced", "ask", "deferred", "defer_limit", "answer", "policy")
_AFTER_KEYS = ("after_write_tokens", "after_read_tokens")


class FactsError(ValueError):
    """事実の形が違う（足りない鍵・知らない鍵・型の違い）。"""


def version() -> str:
    return json.loads((Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json")
                      .read_text(encoding="utf-8"))["version"]


def _check(facts: dict, required, optional) -> None:
    if not isinstance(facts, dict):
        raise FactsError("input must be a JSON object")
    unknown = sorted(set(facts) - set(required) - set(optional))
    missing = [k for k in required if k not in facts]
    if unknown:
        raise FactsError("unknown keys: %s" % ", ".join(unknown))
    if missing:
        raise FactsError("missing keys: %s" % ", ".join(missing))


def count(facts: dict, key: str, default):
    """facts[key]（無ければ default）が有限の 0 以上の数か確かめて返す。違えば FactsError。"""
    v = facts.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
        raise FactsError("%s must be a finite number of 0 or more: %r" % (key, v))
    return v


def check_model(model):
    if not isinstance(model, str):
        raise FactsError("model must be a string: %r" % (model,))
    return model


def _time(key: str, value) -> datetime:
    """ISO 8601 で、時差（Z か +09:00 など）付きの時刻を UTC の datetime にする。"""
    try:
        t = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise FactsError("%s must be an ISO 8601 time: %r" % (key, value))
    if t.tzinfo is None:
        raise FactsError("%s must carry a time zone (for example Z or +09:00): %r" % (key, value))
    return t.astimezone(timezone.utc)


def _write_kind(facts: dict) -> str:
    life = facts["lifetime"]
    if life not in (300, 3600):
        raise FactsError("lifetime must be 300 or 3600: %r" % (life,))
    return "write_5m" if life == 300 else "write_1h"


def _stamp(out: dict, price: "prices.Price", rent: float, buy: float, extra: dict) -> dict:
    out = dict(out, rent=rent, buy=buy, **extra)
    out.update(prices=price.info(), version=version())
    return out


def keepalive(facts: dict, price_override=None, env=None, now=None) -> dict:
    """keepalive の判断。facts: model・lifetime・context_tokens・spent・certain（必須）と、
    hazard・miss・policy・last_request_at・write_tokens・output_tokens・margin_s（省ける。後ろの 3 つは prices.toml の既定）と、
    記録だけに残す turn_end_at（ISO 8601。判断には使わず、出力にそのまま添える）。
    """
    _check(facts, ("model", "lifetime", "context_tokens", "spent", "certain"),
           _CORE_KEYS + ("last_request_at", "write_tokens", "output_tokens", "margin_s", "turn_end_at"))
    d = prices.defaults()["keepalive"]
    check_model(facts["model"])
    kind, n = _write_kind(facts), count(facts, "context_tokens", None)
    price = _lookup(facts["model"], price_override, env, now)
    write, out_tokens, margin = (count(facts, k, d[k]) for k in ("write_tokens", "output_tokens", "margin_s"))
    w, r = price.rate(kind, n), price.rate("read", n)
    rent = r * n + w * write + price.rate("output", n) * out_tokens
    buy = (w - r) * n
    inputs = {"rent": rent, "buy": buy, "spent": facts["spent"], "certain": facts["certain"]}
    inputs.update({k: facts[k] for k in _CORE_KEYS if k in facts})
    next_at = None
    if facts.get("last_request_at") is not None:
        t = _time("last_request_at", facts["last_request_at"])
        next_at = (t + timedelta(seconds=facts["lifetime"] - margin)).strftime("%Y-%m-%dT%H:%M:%SZ")
    extra = {"next_at": next_at}
    if facts.get("turn_end_at") is not None:
        extra["turn_end_at"] = _time("turn_end_at", facts["turn_end_at"]).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _stamp(rent_or_buy.decide(inputs), price, rent, buy, extra)


def extra_read_cost(contexts, after, price: "prices.Price") -> float:
    """前の compact から後に余分に読んだ費用の累計。応答ごとに (文脈 − compact の後の文脈 after) × 読み（負は 0）を足す。"""
    return sum(max(0, c - after) * price.rate("read", c) for c in contexts)


def compact(facts: dict, price_override=None, env=None, now=None) -> dict:
    """compact の判断。facts: model・lifetime・context_tokens・spent（必須）と、after_write_tokens・after_read_tokens・
    summary_tokens・warm・consult_cost・forced・ask・deferred・defer_limit・answer・policy（省ける。前の 3 つは prices.toml の既定）。
    after_write_tokens・after_read_tokens は compact の後の最初の要求がキャッシュに書く量と読む量で、和が compact の後の文脈。
    warm（キャッシュが温かいか）は判断に入れず、記録に残すだけ。
    """
    _check(facts, ("model", "lifetime", "context_tokens", "spent"),
           _COMPACT_CORE_KEYS + _AFTER_KEYS + ("summary_tokens", "warm", "consult_cost"))
    d = prices.defaults()["compact"]
    check_model(facts["model"])
    kind, n = _write_kind(facts), count(facts, "context_tokens", None)
    price = _lookup(facts["model"], price_override, env, now)
    after_w, after_r = (count(facts, k, d[k]) for k in _AFTER_KEYS)
    after, summary = after_w + after_r, count(facts, "summary_tokens", d["summary_tokens"])
    ask_cost = count(facts, "consult_cost", 0)
    rent = max(0, n - after) * price.rate("read", n)
    fixed = after_w * price.rate(kind, after) + after_r * price.rate("read", after) + summary * price.rate("output", n)
    buy = fixed + rent + ask_cost
    inputs = {"rent": rent, "buy": buy, "spent": facts["spent"], "certain": True}
    inputs.update({k: facts[k] for k in _COMPACT_CORE_KEYS if k in facts})
    return _stamp(rent_or_buy.decide(inputs), price, rent, buy, {"warm": facts.get("warm"), "compact_cost": fixed})


def after_tokens(facts: dict) -> int:
    """compact の後の文脈（after_write_tokens + after_read_tokens。無い方は prices.toml の既定）。"""
    d = prices.defaults()["compact"]
    return sum(count(facts, k, d[k]) for k in _AFTER_KEYS)


def _lookup(model, override, env, now):
    kw = {} if env is None else {"env": env}
    return prices.lookup(model, override, now=now, **kw)
