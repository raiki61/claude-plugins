"""中心 decide。入力を確かめ、決め方で借りるか買うかを決め、強制・延期・問い合わせ口を重ねる。"""
import math
from dataclasses import fields
from typing import Callable, Optional

from .policies import POLICIES, Inputs, fixed


class InputError(ValueError):
    """入力の形が違う。黙って直さず、止めて訳を返す。"""


_NUMBERS = ("rent", "buy", "spent", "miss", "hazard")
_INTS = ("deferred", "defer_limit")
_BOOLS = ("certain", "forced", "ask")
_REQUIRED = ("rent", "buy", "spent", "certain")


def _number(key, v):
    # bool は int の仲間だが、数として受けない
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise InputError("%s は有限の数でなければならない: %r" % (key, v))
    if v < 0:
        raise InputError("%s は 0 以上でなければならない: %r" % (key, v))
    return v


def parse(raw: dict) -> Inputs:
    """表を Inputs に直す。知らない鍵・足りない鍵・型や範囲の違いは InputError。"""
    if not isinstance(raw, dict):
        raise InputError("入力は表（JSON のオブジェクト）でなければならない")
    names = {f.name for f in fields(Inputs)}
    unknown = sorted(set(raw) - names)
    if unknown:
        raise InputError("知らない鍵: %s" % ", ".join(unknown))
    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        raise InputError("足りない鍵: %s" % ", ".join(missing))
    out = dict(raw)
    for k in _NUMBERS:
        if out.get(k) is not None:
            out[k] = _number(k, out[k])
    for k in _INTS:
        if k in out and (isinstance(out[k], bool) or not isinstance(out[k], int) or out[k] < 0):
            raise InputError("%s は 0 以上の整数でなければならない: %r" % (k, out[k]))
    for k in _BOOLS:
        if k in out and not isinstance(out[k], bool):
            raise InputError("%s は真偽でなければならない: %r" % (k, out[k]))
    if out.get("miss", 0) > 1:
        raise InputError("miss は 0 から 1 の割合でなければならない: %r" % out["miss"])
    if out.get("hazard") is not None and out["hazard"] > 1:
        raise InputError("hazard は 0 から 1 の確率でなければならない: %r" % out["hazard"])
    if "answer" in out and out["answer"] is not None and not isinstance(out["answer"], dict):
        raise InputError("answer は表でなければならない: %r" % (out["answer"],))
    if not isinstance(out.get("policy", "fixed"), str):
        raise InputError("policy は文字列でなければならない: %r" % (out["policy"],))
    return Inputs(**out)


def _reply(r):
    """問い合わせ口の返事の形を確かめる。形が違えば None。"""
    if not isinstance(r, dict) or not isinstance(r.get("go"), bool):
        return None
    if r["go"]:
        prep = r.get("prep")
        return r if prep is None or isinstance(prep, dict) else None
    return r if isinstance(r.get("why"), str) else None


def _apply_reply(r, why: str):
    """返事を (action, why, prep) にする。r が None（形が違う・聞けない）なら聞かなかったのと同じ。"""
    reply = _reply(r)
    if reply is None:
        return "buy", why + "。問い合わせの返事を読めず、聞かなかったのと同じに買う", None
    if reply["go"]:
        return "buy", why + "。相手が進めると答えた", reply.get("prep")
    return "rent", "延期: %s（元の判断: %s）" % (reply["why"], why), None


def decide(raw: dict, consult: Optional[Callable[[Inputs], dict]] = None) -> dict:
    """借りるか買うかを決める。出力は {action, why, consult, prep, policy}。

    consult は問い合わせ口。聞くべきときだけ呼ぶ。渡さなければ consult: true を返し、呼ぶ側が相手に聞いて
    answer に入れて 2 回目を呼ぶ（部品は状態を持たない）。
    """
    x = parse(raw)
    policy = x.policy
    policy_fn = POLICIES.get(policy)
    note = ""
    if policy_fn is None:
        policy_fn, policy, note = fixed, "fixed", "知らない決め方 %r のため fixed で決めた。" % x.policy
    action, why = policy_fn(x)
    why, prep, ask_now = note + why, None, False
    if action == "buy":
        if x.forced:
            why += "。強制の上限に着いた"
        elif x.ask and x.deferred < x.defer_limit:
            if x.answer is not None:
                action, why, prep = _apply_reply(x.answer, why)
            elif consult is not None:
                try:
                    reply = consult(x)
                except Exception:  # 相手が落ちても判断は止めない。聞かなかったのと同じに扱い、次の行で買いにする
                    reply = None
                action, why, prep = _apply_reply(reply, why)
            else:
                ask_now = True
        elif x.ask:
            why += "。延期の上限に着いたので聞かずに買う"
    return {"action": action, "why": why, "consult": ask_now, "prep": prep, "policy": policy}
