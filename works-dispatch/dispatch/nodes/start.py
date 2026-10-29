#!/usr/bin/env python3
"""start ノード: 受け持ち（会社の形の [[skills]]）の起動方法 [skills.start] の中身。外には書かない。流れ（--start・--due）は starts.py。

受け持ちに起動方法を書くと、その受け持ちの部署を、窓口の判断に頼らずに起動できる。一度きりの受け持ち（役が keep でない。例: 作業）は
起動するたびに受け持ちの名前の部署が立ち、納品した後に終わりの印（--done）か片付けで畳まれる。keep の受け持ち（例: 担当）は、その部署の順番待ちに頼みを積む。
役の種類は足さない（どの役で起動するかは受け持ちの role）。

フィールド（[skills.start]）:
- report_to（要る）: 納品を返す先の名前。同じ会社なら名前、ほかの会社なら「会社/名前」。起動した者でなくここに返す（見られる側が
  結果の上げ先を決めない。内部監査の、結果を統治する側に直に上げる形）。
- brief か text（どちらか 1 つ）: 頼みの本文。brief はリポジトリの中の相対のパスで、会社の形と同じく origin の既定のブランチから読む。
- every（任意）: 周期。数と単位（m 分・h 時間・d 日・w 週）で書く（例 "7d"）。書けば --due（頼みと納品が通るたびに裏で打たれる）が、
  前に起動した時から周期が過ぎていれば起動する。過ぎた回が幾つ有っても起動するのは 1 回（anacron と同じ。手元の PC は眠り・落ちるので、
  刻みを取りこぼしても次の刻みで追いつく）。省けばコマンド（--start）でだけ起動する。
- by（任意）: --start で起動してよい会話の名前の並び。省けば誰でも。Claude Code の外（人が端末で打つ・OS の予定が打つ）は
  会話の名前が無いので、いつでも起動できる。
前に起動した時は受付箱の台帳の kind start の行（status sent）で数える。
"""

import re

UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
EVERY = re.compile(r"^([1-9][0-9]*)([mhdw])$")


def seconds(every):
    """周期の字（例 "7d"）の秒。形が違えば None。"""
    m = EVERY.match(every) if isinstance(every, str) else None
    return int(m.group(1)) * UNITS[m.group(2)] if m else None


def parse(raw, where, problems):
    """[skills.start] の表を読む。無ければ None。形が違えば problems に書いて None（その受け持ちは起動しない）。"""
    if raw is None:
        return None
    bad = []
    if not isinstance(raw, dict):
        problems.append(f"{where}: start が表で無い。起動しない")
        return None
    report = raw.get("report_to")
    if not (isinstance(report, str) and report.strip()):
        bad.append("report_to（納品を返す先の名前）が要る")
    has = [k for k in ("brief", "text") if k in raw]
    if len(has) != 1 or not (isinstance(raw[has[0]], str) and raw[has[0]].strip()):
        bad.append("brief（リポジトリの中のパス）か text（本文）のどちらか 1 つが要る")
    every = raw.get("every")
    if every is not None and seconds(every) is None:
        bad.append(f"every は数と単位 m・h・d・w（例 \"7d\"）で書く（今 {every!r}）")
    by = raw.get("by")
    if by is not None and not (isinstance(by, list) and all(isinstance(x, str) and x for x in by)):
        bad.append("by は会話の名前の並び")
    if bad:
        problems.append(f"{where}: start の形が違うので起動しない: " + "、".join(bad))
        return None
    return {"report_to": report.strip(), "brief": raw.get("brief"), "text": raw.get("text"), "every": every, "by": by}


def last_started(records, name):
    """受け持ち name を前に起動した時（台帳の kind start・status sent の行の at の最大）。無ければ None。"""
    return max((r.get("at") or 0 for r in records
                if r.get("kind") == "start" and r.get("skill") == name and r.get("status") == "sent"), default=None)


def due(start, last, now):
    """周期の来た受け持ちか。周期の無い物は来ない。一度も起動していなければ来ている。"""
    if not start or not start.get("every"):
        return False
    return last is None or now - last >= seconds(start["every"])


def body(name, by, text):
    """部署に渡す頼みの本文。頭に、どの受け持ちを誰が起動したかの 1 行（周期で起動した物は毎回同じ字になり、同じ中身の頼みを
    2 度積まない見分け〔指紋〕が効く）。"""
    return f"会社の形の受け持ち「{name}」の起動方法（[skills.start]）で、{by}が出した頼みです。\n\n{text.strip()}\n"


def branch(skill, ask_id):
    """起動した部署のブランチ（work/<受け持ちの id を英小文字にし、英数字でない字を - にした物、無ければ start>-<受付番号の末尾 6 字>）。"""
    slug = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", (skill.get("id") or "").lower())).strip("-") or "start"
    return f"work/{slug}-{ask_id[-6:]}"
