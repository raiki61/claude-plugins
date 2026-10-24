"""場面の事実を中心 decide の入力に直す。式は指南 3.5（prices.toml の guide に commit）。

keepalive: 借りる＝1 本の費用、買う＝切れの上乗せ。compact: 借りる＝この 1 回で余分に読む額、買う＝縮める費用。
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import rent_or_buy

from . import prices

_CORE_KEYS = ("hazard", "miss", "policy")
_COMPACT_CORE_KEYS = ("forced", "ask", "deferred", "defer_limit", "answer", "policy")


class FactsError(ValueError):
    """事実の形が違う（足りない鍵・知らない鍵・型の違い）。"""


def version() -> str:
    return json.loads((Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json")
                      .read_text(encoding="utf-8"))["version"]


def _check(facts: dict, required, optional) -> None:
    if not isinstance(facts, dict):
        raise FactsError("入力は表（JSON のオブジェクト）でなければならない")
    unknown = sorted(set(facts) - set(required) - set(optional))
    missing = [k for k in required if k not in facts]
    if unknown:
        raise FactsError("知らない鍵: %s" % ", ".join(unknown))
    if missing:
        raise FactsError("足りない鍵: %s" % ", ".join(missing))


def _count(facts: dict, key: str, default):
    v = facts.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
        raise FactsError("%s は 0 以上の数でなければならない: %r" % (key, v))
    return v


def _write_kind(facts: dict) -> str:
    life = facts["lifetime"]
    if life not in (300, 3600):
        raise FactsError("lifetime は 300 か 3600 でなければならない: %r" % (life,))
    return "write_5m" if life == 300 else "write_1h"


def _stamp(out: dict, price: "prices.Price", rent: float, buy: float, extra: dict) -> dict:
    out = dict(out, rent=rent, buy=buy, **extra)
    out.update(prices=price.info(), version=version(), guide=prices.defaults()["guide"]["commit"])
    return out


def keepalive(facts: dict, price_override=None, env=None, now=None) -> dict:
    """keepalive の判断。facts: model・lifetime・context_tokens・spent・certain（必須）と、
    hazard・miss・policy・last_request_at・write_tokens・output_tokens・margin_s（省ける。後ろの 3 つは prices.toml の既定）。
    """
    _check(facts, ("model", "lifetime", "context_tokens", "spent", "certain"),
           _CORE_KEYS + ("last_request_at", "write_tokens", "output_tokens", "margin_s"))
    d = prices.defaults()["keepalive"]
    kind, n = _write_kind(facts), _count(facts, "context_tokens", None)
    price = _lookup(facts["model"], price_override, env, now)
    write, out_tokens, margin = (_count(facts, k, d[k]) for k in ("write_tokens", "output_tokens", "margin_s"))
    w, r = price.rate(kind, n), price.rate("read", n)
    rent = r * n + w * write + price.rate("output", n) * out_tokens
    buy = (w - r) * n
    inputs = {"rent": rent, "buy": buy, "spent": facts["spent"], "certain": facts["certain"]}
    inputs.update({k: facts[k] for k in _CORE_KEYS if k in facts})
    out = rent_or_buy.decide(inputs)
    at = facts.get("last_request_at")
    next_at = None
    if at is not None:
        try:
            t = datetime.fromisoformat(at).astimezone(timezone.utc)
        except (ValueError, TypeError):
            raise FactsError("last_request_at は ISO 8601 の時刻でなければならない: %r" % (at,))
        next_at = (t + timedelta(seconds=facts["lifetime"] - margin)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return _stamp(out, price, rent, buy, {"next_at": next_at})


def extra_read_cost(contexts, post_tokens, price: "prices.Price") -> float:
    """前の compact から後に余分に読んだ費用の累計。応答ごとに (文脈 − compact の後の文脈) × 読み（負は 0）を足す。"""
    return sum(max(0, c - post_tokens) * price.rate("read", c) for c in contexts)


def compact(facts: dict, price_override=None, env=None, now=None) -> dict:
    """compact の判断。facts: model・lifetime・context_tokens・spent（必須）と、post_tokens・summary_tokens・warm・
    consult_cost・forced・ask・deferred・defer_limit・answer・policy（省ける。前の 2 つは prices.toml の既定）。
    warm（キャッシュが温かいか）は判断に入れず、記録に残すだけ。
    """
    _check(facts, ("model", "lifetime", "context_tokens", "spent"),
           _COMPACT_CORE_KEYS + ("post_tokens", "summary_tokens", "warm", "consult_cost"))
    d = prices.defaults()["compact"]
    kind, n = _write_kind(facts), _count(facts, "context_tokens", None)
    price = _lookup(facts["model"], price_override, env, now)
    post, summary = _count(facts, "post_tokens", d["after_tokens"]), _count(facts, "summary_tokens", d["summary_tokens"])
    ask_cost = _count(facts, "consult_cost", 0)
    rent = max(0, n - post) * price.rate("read", n)
    buy = post * price.rate(kind, n) + summary * price.rate("output", n) + ask_cost
    inputs = {"rent": rent, "buy": buy, "spent": facts["spent"], "certain": True}
    inputs.update({k: facts[k] for k in _COMPACT_CORE_KEYS if k in facts})
    return _stamp(rent_or_buy.decide(inputs), price, rent, buy, {"warm": facts.get("warm")})


def _lookup(model, override, env, now):
    kw = {} if env is None else {"env": env}
    return prices.lookup(model, override, now=now, **kw)
