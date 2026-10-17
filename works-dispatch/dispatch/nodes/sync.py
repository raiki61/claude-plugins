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
- 作業場には、席の見え方（常設・毎回空、常設・持ち越し、都度）を印 kind として付ける（サイドバーの作業場の行に herdr の設定の
  $kind で出す。会話の行でなく作業場の行で見せる。持ち主 2026-10-16・17）。名前と同じく、今の値と同じなら付け直さず、属性を持つ
  場所が 2 つ以上居る作業場は触らない。
- 会社ごとの部署の作業場（元の clone の linked worktree の作業場）は、仕事の流れの順に並べる（flow_order。順の鍵は role.flow_rank で、
  --tree の部署の並びと同じ。持ち主 2026-10-17 の案 A）。
  常設・持ち越し（相談の社長室など）、常設・毎回空（担当。この中は会社の形の [[skills]] の書き順）、都度（作業。この中は今の並び。
  herdr は新しい作業場を後ろに足すので、起こした順）、属性の無い作業場（手で開いた場所）の順。順は属性と会社の形から毎回出し、
  順の表は持たない。本社（元の clone）の作業場は herdr が会社のまとまりの頭に置くので動かさない。会社の部署の作業場が herdr の
  並びで占める位置の中だけで入れ替え、ほかの会社とまとまりの無い作業場の位置は変えない。
- ペインの表示名は役、題名は会話の名前、札は role（役）・account（アカウント）・boss（頼み元）。出どころ SOURCE の分として付けるので、
  打ち直すと置き換わる。属性に無い物は消す。

入口の dispatch.py --sync（と、会社の形が替わったときの番の終わりのフック shape_hook.py）が tree ノードの組み立てを渡して plan を呼び、
apply で herdr に書く（--dry-run は plan だけ）。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from nodes import role  # noqa: E402

SOURCE = "company"  # herdr pane report-metadata・workspace report-metadata の出どころ
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


def kind(attrs):
    """作業場の印 kind の値。役を持つ部署の席の見え方（常設・毎回空、常設・持ち越し、都度）。役が無ければ None。"""
    return role.seat(attrs.get("residency"), attrs.get("fresh")) if attrs.get("role") else None


def kind_op(workspace, attrs):
    """1 つの作業場に印 kind だけを付ける物（名前は付け直さない。部署を立てたとき・開き直したときに、--sync と同じ値を付ける）。"""
    return {"workspace": workspace, "label": None, "kind": kind(attrs)}


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


def workspace_ops(companies, workspaces):
    """作業場に付ける物の並び。1 件は {workspace, label, kind}（付け直さない物は None）。workspaces は herdr の作業場の並び
    （1 件は {workspace_id, label, tokens}。今の名前と印 kind を比べる）。"""
    now = {w["workspace_id"]: (w.get("label"), (w.get("tokens") or {}).get("kind")) for w in workspaces}
    claims = {}
    for c in companies:
        for d in c["departments"]:
            if d["attrs"] and d.get("workspace"):
                # 本社（元の clone）の作業場は herdr の木の親なので、会社の名前にする（会社の名前は親の作業場にだけ出す）
                name = c["name"] if d.get("head_office") else d["attrs"].get("name")
                claims.setdefault(d["workspace"], []).append((name, kind(d["attrs"])))
    out = []
    for ws, got in claims.items():
        if len(got) != 1 or ws not in now:
            continue
        (name, want), (label, kind_now) = got[0], now[ws]
        o = {"workspace": ws, "label": name if name and label != name else None, "kind": want if want and kind_now != want else None}
        if o["label"] or o["kind"]:
            out.append(o)
    return out


def workspace_line(o):
    """作業場に付ける物の 1 行（--sync・--reorg の報告と --dry-run）。"""
    return f"作業場 {o['workspace']}: 名前 {o['label'] or 'そのまま'}  印 {o['kind'] or 'そのまま'}"


def apply_workspaces(ops, h):
    """作業場の名前と印を herdr に書く。1 件ごとに {workspace, status: done|failed, detail}。1 件の失敗で残りを止めない。"""
    out = []
    for o in ops:
        try:
            if o["label"]:
                h.rename_workspace(o["workspace"], o["label"])
            if o["kind"]:
                h.report_workspace_metadata(o["workspace"], SOURCE, {"kind": o["kind"]})
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


def flow_order(workspaces, attrs_of, skills_of):
    """部署の作業場を仕事の流れの順にする動かし方の並び。1 件は {workspace, index, label}（herdr.move_workspace に渡す。順に当てる）。
    workspaces は herdr の作業場の並び（herdr.workspaces の形。並びの順）、attrs_of は worktree の場所 → 部署の属性、skills_of は
    元の clone の根 → 会社の形の受け持ちの並び（[[skills]] の書き順）。もう流れの順なら空。"""
    ids = [w["workspace_id"] for w in workspaces]
    want = list(ids)
    slots = {}
    for i, w in enumerate(workspaces):
        if w.get("repo_root") and w.get("linked") and w.get("path"):
            slots.setdefault(w["repo_root"], []).append(i)
    for root, places in slots.items():
        names = [x.get("name") for x in skills_of(root)]
        for place, i in zip(places, sorted(places, key=lambda i: (*role.flow_rank(attrs_of(workspaces[i]["path"]), names), i))):
            want[place] = ids[i]
    labels = {w["workspace_id"]: w.get("label") for w in workspaces}
    now, out = list(ids), []
    for i, ws in enumerate(want):
        if now[i] != ws:
            now.insert(i, now.pop(now.index(ws)))
            out.append({"workspace": ws, "index": i, "label": labels.get(ws)})
    return out


def order_line(o):
    """作業場を動かす 1 行（--sync の報告と --dry-run）。"""
    return f"作業場 {o['workspace']}（{o['label'] or '-'}）: 並びの {o['index'] + 1} 番目へ"


def apply_order(moves, h):
    """flow_order の動かし方を herdr に当てる。1 件ごとに {workspace, status: done|failed|skipped, detail}。位置は前の動かしの後の並びで
    数えるので、1 件が失敗したら残りは当てない（skipped）。"""
    out, failed = [], None
    for o in moves:
        if failed:
            out.append({"workspace": o["workspace"], "status": "skipped", "detail": "前の作業場を動かせなかった"})
            continue
        try:
            h.move_workspace(o["workspace"], o["index"])
            out.append({"workspace": o["workspace"], "status": "done", "detail": None})
        except h.HerdrError as e:
            failed = str(e)
            out.append({"workspace": o["workspace"], "status": "failed", "detail": failed})
    return out
