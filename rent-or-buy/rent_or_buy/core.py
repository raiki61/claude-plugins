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
        raise InputError("%s must be a finite number: %r" % (key, v))
    if v < 0:
        raise InputError("%s must be 0 or more: %r" % (key, v))
    return v


def parse(raw: dict) -> Inputs:
    """表を Inputs に直す。知らない鍵・足りない鍵・型や範囲の違いは InputError。"""
    if not isinstance(raw, dict):
        raise InputError("input must be a JSON object")
    names = {f.name for f in fields(Inputs)}
    unknown = sorted(set(raw) - names)
    if unknown:
        raise InputError("unknown keys: %s" % ", ".join(unknown))
    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        raise InputError("missing keys: %s" % ", ".join(missing))
    out = dict(raw)
    for k in _NUMBERS:
        # null を受けるのは hazard だけ（無い、の意味）。ほかの数の null は黙って直さず止める
        if k in out and not (k == "hazard" and out[k] is None):
            out[k] = _number(k, out[k])
    for k in _INTS:
        if k in out and (isinstance(out[k], bool) or not isinstance(out[k], int) or out[k] < 0):
            raise InputError("%s must be an integer of 0 or more: %r" % (k, out[k]))
    for k in _BOOLS:
        if k in out and not isinstance(out[k], bool):
            raise InputError("%s must be true or false: %r" % (k, out[k]))
    if out.get("miss", 0) > 1:
        raise InputError("miss must be a share from 0 to 1: %r" % out["miss"])
    if out.get("hazard") is not None and out["hazard"] > 1:
        raise InputError("hazard must be a probability from 0 to 1: %r" % out["hazard"])
    if out.get("answer") is not None and _reply(out["answer"]) is None:
        # コマンドで渡された answer の形の違いは黙って買いにせず止める（関数の返事の形の違いだけは買いにする）
        raise InputError("answer must be {\"go\": true, \"prep\": {...}} or {\"go\": false, \"why\": \"...\"}: %r" % (out["answer"],))
    if not isinstance(out.get("policy", "fixed"), str):
        raise InputError("policy must be a string: %r" % (out["policy"],))
    return Inputs(**out)


def _reply(r):
    """問い合わせ口の返事の形を確かめる。形が違えば None。"""
    if not isinstance(r, dict) or not isinstance(r.get("go"), bool):
        return None
    if r["go"]:
        prep = r.get("prep")
        return r if prep is None or isinstance(prep, dict) else None
    return r if isinstance(r.get("why"), str) else None


def _apply_reply(r):
    """返事を (action, reason, why 追記, prep) にする。r が None（形が違う・聞けない）なら聞かなかったのと同じに買う。"""
    reply = _reply(r)
    if reply is None:
        return "buy", "consult_unreadable", "the consult reply was unreadable, so buy as if not asked", None
    if reply["go"]:
        return "buy", "consult_go", "the other side said go", reply.get("prep")
    return "rent", "consult_deferred", "deferred by the other side: %s" % reply["why"], None


def decide(raw: dict, consult: Optional[Callable[[Inputs], dict]] = None) -> dict:
    """借りるか買うかを決める。出力は {action, reason, why, consult, prep, policy}。

    reason は機械の読む短い鍵、why は英語の訳。consult は問い合わせ口。聞くべきときだけ呼ぶ。渡さなければ
    consult: true を返し、呼ぶ側が相手に聞いて answer に入れて 2 回目を呼ぶ（部品は状態を持たない）。
    """
    x = parse(raw)
    policy = x.policy
    policy_fn = POLICIES.get(policy)
    note = ""
    if policy_fn is None:
        policy_fn, policy, note = fixed, "fixed", "unknown policy %r, decided with fixed. " % x.policy
    action, reason, why = policy_fn(x)
    if policy_fn is fixed and note:
        reason = "unknown_policy_fallback"
    why, prep, ask_now = note + why, None, False
    if x.forced:
        # 強制の上限は決め方の結果によらず買う
        action, reason, why = "buy", "forced", why + "; forced to buy at the caller's hard limit"
    elif action == "buy":
        if x.ask and x.deferred < x.defer_limit:
            if x.answer is not None:
                action, reason, add, prep = _apply_reply(x.answer)
                why += "; " + add
            elif consult is not None:
                try:
                    reply = consult(x)
                except Exception:  # 相手が落ちても判断は止めない。聞かなかったのと同じに扱い、次の行で買いにする
                    reply = None
                action, reason, add, prep = _apply_reply(reply)
                why += "; " + add
            else:
                ask_now = True
        elif x.ask:
            reason, why = "defer_limit_reached", why + "; defer limit reached, so buy without asking"
    return {"action": action, "reason": reason, "why": why, "consult": ask_now, "prep": prep, "policy": policy}
