#!/usr/bin/env python3
"""sync ノード: 部署の git の属性（正本）から、herdr の表示（ペインの名前・表示名・題名・札）を組み立て直す。外に書く。

会社の形の設計 4.2 の「herdr は表示と操作の場所。下回りが正本を読み、表示を組み立て直す。何度実行しても同じ結果」に当たる。
- 付けるのは、属性（company.*）を 1 つでも持つ部署だけ。属性の無い部署（手で開いた場所）は触らない。
- 付ける先は、部署の中で会話の居るペイン。属性の会話（company.session）の居るペインが分かれば、そのペインだけ。会話が居なくて、
  ペインが 1 つだけならそのペイン（herdr を立ち上げ直した後など）。本社（元の clone。--desk で窓口の属性を書く）は持ち主の
  ほかの会話も居るので、会話の居るペインが 2 つ以上あって属性の会話と結べなければ付けない。
- ペインの名前は 会話の名前（アカウントが 2 つ以上なら、後ろにアカウントの名）。--task が付ける名前と同じ決まり（label）。
  今の名前と同じなら付け直さない。
- 作業場の名前も 会話の名前（属性の name。アカウントの名は添えない）。herdr のサイドバーの 1 行目はペインでなく作業場の名前を
  出すため。本社（元の clone。--desk で窓口の属性を書く）の作業場は herdr の木の親なので、属性を持てば会社の名前を付ける（会社の
  名前は親の作業場にだけ出し、部署の名前には付けない。持ち主 2026-10-16）。今の名前と同じなら付け直さず、属性を持つ場所が
  2 つ以上居る作業場は触らない。
- 表示名は役に席の見え方（常設・毎回空、常設・持ち越し、都度）を添えた物、題名は会話の名前、札は role（役）・account（アカウント）・boss（上役）。出どころ SOURCE の分として付けるので、打ち直すと置き換わる。
  属性に無い物は消す。

入口の dispatch.py --sync（と、会社の形が替わったときの番の終わりのフック shape_hook.py）が tree ノードの組み立てを渡して plan を呼び、
apply で herdr に書く（--dry-run は plan だけ）。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from nodes import role  # noqa: E402

SOURCE = "company"  # herdr pane report-metadata の出どころ
TOKENS = ("role", "account", "boss")  # 札に出す属性


def label(name, account, many_accounts):
    """ペインの名前。アカウントが 2 つ以上なら、どのアカウントの会話かを名前の後ろに添える（例: catchup作り直し p2）。"""
    return f"{name} {account}" if many_accounts and account else name


def op(pane, attrs, many_accounts, current_label=None):
    """1 つのペインに付ける物。{pane, label（付け直さないなら None）, display_agent, title, tokens, clear_tokens}。
    属性に無い表示名・題名・札は消す側に回す（正本から消えた物を表示に残さない）。"""
    name = attrs.get("name")
    want = label(name, attrs.get("account"), many_accounts) if name else None
    return {"pane": pane, "label": want if want and want != current_label else None,
            "display_agent": shown_role(attrs), "title": name,
            "tokens": {k: attrs[k] for k in TOKENS if attrs.get(k)}, "clear_tokens": [k for k in TOKENS if not attrs.get(k)]}


def shown_role(attrs):
    """herdr の表示名（会話の行の agent の欄）。役に、常設か都度かと会話の持ち越し方を添える（例: 担当（常設・毎回空））。
    herdr の設定の行の並びを変えずに見えるよう、札ではなく表示名に入れる。"""
    name = attrs.get("role")
    return f"{name}（{role.seat(attrs.get('residency'), attrs.get('fresh'))}）" if name else None


WAITING = "裏の処理待ち"   # 番を終えて、裏で走らせた処理の終わりを待っている部署の表示名に添える字


def waiting_op(pane, attrs, waiting):
    """部署の会話の番の終わりに付け直す物。裏の処理（run_in_background の Bash）を待っていれば、表示名に WAITING を添える。
    herdr の状態は番が終わると done になり、裏の処理を待っている会話も終わったように見えた（持ち主が見誤った）。
    ペインの名前は付け直さない（アカウントの数が分からないので）。"""
    return _waiting({**op(pane, attrs, False), "label": None}, waiting)


def _waiting(o, waiting):
    if waiting and o["display_agent"]:
        o["display_agent"] += f"・{WAITING}"
    return o


def _target(dept):
    talking = [p for p in dept["panes"] if p.get("agent")]
    sid = dept["attrs"].get("session")
    mine = [p for p in talking if sid and p.get("agent_session") == sid]
    if mine:
        return mine
    if dept.get("head_office") and len(talking) > 1:
        return []   # 本社には持ち主の会話がほかにも居る。窓口の会話（company.session）と結べないペインには付けない
    if talking:
        return talking
    return dept["panes"] if len(dept["panes"]) == 1 else []


def plan(companies, many_accounts, waiting=lambda attrs: False):
    """(付ける物の並び, 付けられない部署の注記)。companies は tree ノードの build の結果。waiting は部署の属性を受けて、その会話が
    裏の処理を待っているか（待っていれば表示名に WAITING を添えたままにする。付け直しで番の終わりの印を消さない）。"""
    ops, notes = [], []
    for c in companies:
        for d in c["departments"]:
            if not d["attrs"]:
                continue
            panes = _target(d)
            if not panes:
                talking = sum(1 for p in d["panes"] if p.get("agent"))
                why = ("作業場が開いていない" if not d["panes"] else
                       "本社に会話の居るペインが 2 つ以上あり、属性の会話（company.session）の居るペインが分からない" if talking > 1 else
                       "会話の居ないペインが 2 つ以上")
                notes.append(f"{c['name']} {d['branch'] or d['path']}: 付ける先のペインが無い（{why}）")
                continue
            ops += [_waiting(op(p["pane_id"], d["attrs"], many_accounts, p.get("label")), waiting(d["attrs"])) for p in panes]
    return ops, notes


def workspace_ops(companies, labels):
    """作業場に付ける名前の並び。1 件は {workspace, label}。labels は 作業場の id → 今の名前（herdr の作業場の並び）。"""
    claims = {}
    for c in companies:
        for d in c["departments"]:
            if d["attrs"] and d.get("workspace"):
                # 本社（元の clone）の作業場は herdr の木の親なので、会社の名前にする（会社の名前は親の作業場にだけ出す）
                claims.setdefault(d["workspace"], []).append(c["name"] if d.get("head_office") else d["attrs"].get("name"))
    return [{"workspace": ws, "label": names[0]} for ws, names in claims.items()
            if len(names) == 1 and names[0] and ws in labels and labels[ws] != names[0]]


def apply_workspaces(ops, h):
    """作業場の名前を herdr に書く。1 件ごとに {workspace, status: done|failed, detail}。1 件の失敗で残りを止めない。"""
    out = []
    for o in ops:
        try:
            h.rename_workspace(o["workspace"], o["label"])
            out.append({"workspace": o["workspace"], "status": "done", "detail": None})
        except h.HerdrError as e:
            out.append({"workspace": o["workspace"], "status": "failed", "detail": str(e)})
    return out


def apply(ops, h):
    """herdr に書く。1 件ごとに {pane, status: done|failed, detail}。1 件の失敗で残りを止めない。"""
    out = []
    for o in ops:
        try:
            if o["label"]:
                h.rename_pane(o["pane"], o["label"])
            h.report_pane_metadata(o["pane"], SOURCE, o["display_agent"], o["title"], o["tokens"], o["clear_tokens"])
            out.append({"pane": o["pane"], "status": "done", "detail": None})
        except h.HerdrError as e:
            out.append({"pane": o["pane"], "status": "failed", "detail": str(e)})
    return out
