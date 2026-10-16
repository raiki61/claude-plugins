#!/usr/bin/env python3
"""sync ノード: 部署の git の属性（正本）から、herdr の表示（ペインの名前・表示名・題名・札）を組み立て直す。外に書く。

会社の形の設計 4.2 の「herdr は表示と操作の場所。下回りが正本を読み、表示を組み立て直す。何度実行しても同じ結果」に当たる。
- 付けるのは、属性（company.*）を 1 つでも持つ部署だけ。属性の無い部署（手で開いた場所）は触らない。
- 付ける先は、部署の中で会話の居るペイン。会話が居なくて、ペインが 1 つだけならそのペイン（herdr を立ち上げ直した後など）。
- ペインの名前は 会話の名前（アカウントが 2 つ以上なら、後ろにアカウントの名）。--task が付ける名前と同じ決まり（label）。
  今の名前と同じなら付け直さない。
- 表示名は役、題名は会話の名前、札は role（役）・account（アカウント）・boss（上役）。出どころ SOURCE の分として付けるので、打ち直すと置き換わる。
  属性に無い物は消す。

入口の dispatch.py --sync が tree ノードの組み立てを渡して plan を呼び、apply で herdr に書く（--dry-run は plan だけ）。
"""

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
            "display_agent": attrs.get("role"), "title": name,
            "tokens": {k: attrs[k] for k in TOKENS if attrs.get(k)}, "clear_tokens": [k for k in TOKENS if not attrs.get(k)]}


def _target(dept):
    talking = [p for p in dept["panes"] if p.get("agent")]
    if talking:
        return talking
    return dept["panes"] if len(dept["panes"]) == 1 else []


def plan(companies, many_accounts):
    """(付ける物の並び, 付けられない部署の注記)。companies は tree ノードの build の結果。"""
    ops, notes = [], []
    for c in companies:
        for d in c["departments"]:
            if not d["attrs"]:
                continue
            panes = _target(d)
            if not panes:
                notes.append(f"{c['name']} {d['branch'] or d['path']}: 付ける先のペインが無い"
                             f"（{'作業場が開いていない' if not d['panes'] else '会話の居ないペインが 2 つ以上'}）")
                continue
            ops += [op(p["pane_id"], d["attrs"], many_accounts, p.get("label")) for p in panes]
    return ops, notes


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
