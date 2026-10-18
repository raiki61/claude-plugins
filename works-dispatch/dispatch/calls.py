#!/usr/bin/env python3
"""機械窓口の流れ（受付の設計 docs/specs/2026-10-17-reception-design.md の 5 章）。入口の dispatch.py --call と、--land の合図
（会社の形の [[land.after]]）から呼ぶ。ツールの中身（入力の確かめ・回す頼みの字）は nodes/tools.py、ツールの定義を読むのは role ノード。

--call <会社/役> <ツール>（call）: ツールを origin の既定のブランチの中身（一時の worktree。tools.place）のルートで走らせ、入力の JSON を標準入力に渡す。終了の値 0 なら片づいた（答えを出して
0 で終わる）。0 以外なら外れを受付箱の台帳に残し、その入力を AI への頼みに変えて回す（orders.ask と同じ宛て方。回す役の常設の部署が
在ればその順番待ちに積み、無ければ一度きりの部署を自動で立てる）。回したら受付番号を出して 3 で終わる。
合図（fire）: --land がメインブランチへ push し終えた後に、[[land.after]] の並びの順に同じ走らせ方で呼ぶ。回した頼みの頼み元は、メインブランチに入れた
部署の頼み元。
"""

import argparse
import json
import os
import pathlib
import subprocess

import config
import gitx
import herdr
import orders
from nodes import deliver, role, tools, tree, wake

CALLED = 3   # 片づかず AI に回した --call の終了の値


def run_tool(command, cwd, value):
    """ツールを cwd で走らせる（シェルの字）。入力の JSON を標準入力に渡す。(終了の値, 標準出力, 標準出力と標準エラー)。"""
    p = subprocess.run(command, shell=True, cwd=cwd, input=json.dumps(value, ensure_ascii=False), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=deliver.child_env())
    return p.returncode, p.stdout or "", (p.stdout or "") + (p.stderr or "")


def _company_root(target, ports, cwd, config_path):
    """「会社/役」の会社の (代表の clone のルート, 会社の名前, 役) か、止める訳。会社を省けば打った場所の会社。"""
    company, sep, name = target.strip().rpartition("/")
    if not name:
        return None, f"宛先「{target}」に役が無い（「会社/役」か役で渡す）"
    settings = os.path.dirname(config.path_of(config_path, os.environ))
    if sep and company:
        try:
            *_, companies, _, _ = orders.survey(config_path, ports)
        except herdr.HerdrError as e:
            return None, f"herdr を読めないので会社「{company}」を探せない（{e}）"
        hit = [c for c in companies if c["name"] == company or os.path.basename(os.path.normpath(c["root"])) == company]
        if not hit:
            return None, f"会社「{company}」が herdr に開いていない"
        root = hit[0]["root"]
    else:
        common = ports.git.common_dir(cwd)
        if not common:
            return None, f"{cwd} が git でないので会社が決まらない（「会社/役」で渡す）"
        root = gitx.root_of(common)
    info = tree.read_info(root, settings)
    return (root, tree.company_name(root, info), name, info), None


def _input(text):
    """--input の字（JSON の字か @ファイル。省けば {}）を読む。(値, 訳か None)。"""
    raw = text or "{}"
    try:
        if raw.startswith("@"):
            raw = pathlib.Path(os.path.expanduser(raw[1:])).read_text(encoding="utf-8")
        return json.loads(raw), None
    except (OSError, ValueError) as e:
        return None, f"入力を JSON として読めない（{e}）"


def invoke(root, company, role_name, tool_name, value, roles, ports, a, task, boss=None, cwd=None):
    """ツールを 1 つ走らせ、片づかなければ回す。(終了の値 0・3・1・2, 出す行の並び)。boss は回す頼みの頼み元の属性の上書き。"""
    found, why = tools.find(roles, role_name, tool_name)
    if why:
        return 2, [f"止めた: {why}"]
    the_role, tool = found
    bad = tools.check_input(tool["inputSchema"], value)
    if bad:
        return 2, [f"止めた: ツール {role_name}/{tool_name} の入力が形に合わない: " + "、".join(bad)]
    inbox = deliver.inbox_of(ports.git.common_dir(root))
    with tools.place(root, ports.git) as (here, note):
        code, out, both = run_tool(tool["command"], here, value)
    if code == 0:
        deliver.log(inbox, {"kind": "call", "status": "done", "role": role_name, "tool": tool_name, "at": ports.now()})
        return 0, [x for x in [note, out.rstrip("\n")] if x and x.strip()]
    out_tail = tools.tail(both)
    deliver.log(inbox, {"kind": "miss", "role": role_name, "tool": tool_name, "input": value, "code": code, "tail": out_tail,
                        "at": ports.now()})
    return hand_over(root, company, role_name, tool, value, code, out_tail, ports, a, task, boss, cwd or root)


def hand_over(root, company, role_name, tool, value, code, out_tail, ports, a, task, boss, cwd):
    """片づかなかったツールの仕事を、回す役への頼みに変えて orders.ask に渡す。(終了の値, 出す行)。"""
    ask_id = deliver.new_id(ports.now())
    caller_inbox = deliver.inbox_of(ports.git.common_dir(cwd) or ports.git.common_dir(root))
    brief = deliver.put(caller_inbox, f"{ask_id}-call.md", tools.miss_text(role_name, tool, value, code, out_tail))
    to = tool["fallback_role"]
    try:
        *_, companies, _, _ = orders.survey(a.config, ports)
        target = deliver.find_target(companies, root, f"{company}/{to}")
    except (herdr.HerdrError, deliver.DeliverError) as e:
        return 1, [f"ツール {role_name}/{tool['name']} は片づかなかった（終了の値 {code}）が、{to} に回せなかった（{e}）"]
    auto = target["department"] is None
    ns = argparse.Namespace(**{**vars(a), "ask": f"{company}/{to}", "text": None, "brief": brief, "dry_run": False,
                               "task": tools.auto_name(role_name, tool) if auto else None,
                               "branch": tools.auto_branch(tool, ask_id) if auto else None,
                               "role": None, "resident": False, "ask_id": ask_id, "from_boss": boss,
                               "title": f"ツール {role_name}/{tool['name']} が片づけられなかった仕事"})
    head = f"ツール {role_name}/{tool['name']} は片づかなかった（終了の値 {code}）。{to} に回した"
    rc = orders.ask(ns, ports, cwd, task)
    if rc != 0:
        return 1, [f"{head}が、頼みが通らなかった（終了の値 {rc}。上の出力を見る）"]
    return CALLED, [f"{head}: 受付 {ask_id}" + (f"（部署 {ns.task} を立てた）" if auto else "")]


def call(a, ports, cwd, task):
    """--call。終了の値（0 片づいた・3 AI に回した・1 回せなかった・2 使い方の誤り）。"""
    target, tool_name = a.call
    got, why = _company_root(target, ports, cwd, a.config)
    if why:
        print(f"止めた: {why}")
        return 2
    root, company, role_name, info = got
    value, why = _input(a.input)
    if why:
        print(f"止めた: {why}")
        return 2
    shape = role.load(info["path"], info["text"])
    role_name = role.current(shape, role_name)   # 前の名前（former_names）で呼んでも今の役のツールを引く
    notes = [f"注記: {p}" for p in info.get("problems", []) + shape["problems"]]
    if a.dry_run:
        found, why = tools.find(shape["roles"], role_name, tool_name)
        if why:
            print("\n".join(notes + [f"止めた: {why}"]))
            return 2
        _, tool = found
        bad = tools.check_input(tool["inputSchema"], value)
        print("\n".join(notes + [f"呼ぶツール: {company}/{role_name} の {tool_name}（{tools.label(tool)}）",
                                 f"- 走らせる: {tool['command']}（origin の既定のブランチの中身を一時の worktree に出し、そのルートで。"
                                 f"入力 {json.dumps(value, ensure_ascii=False)}）",
                                 f"- 片づかなければ回す役: {tool['fallback_role']}"]
                         + [f"- 入力が形に合わない: {'、'.join(bad)}"] * bool(bad)))
        return 0
    rc, lines = invoke(root, company, role_name, tool_name, value, shape["roles"], ports, a, task, cwd=cwd)
    print("\n".join(notes + lines))
    return rc


def annotate(companies, settings, g):
    """--tree に受付を足す: 会社ごとにツール（役・名前・title・外れの回数）を tools に、部署ごとに順番待ちの件数と置き場を queue・
    queue_dir に、渡す待ち受けが居なくて止まっているか（wake.stalled）を stalled に、待ち受けは居るが渡さずに待っている訳（wake.held）を
    held に、部署の属性に会話の id（company.session）が無いかを no_talk_id に。外れは受付箱の台帳の kind miss の行で数える。"""
    for c in companies:
        common = g.common_dir(c["root"])
        inbox = deliver.inbox_of(common) if common else None
        info = tree.read_info(c["root"], settings)
        shape = role.load(info["path"], info["text"])
        misses = {}
        for r in deliver.records(inbox) if inbox else []:
            if r.get("kind") == "miss":
                misses[(r.get("role"), r.get("tool"))] = misses.get((r.get("role"), r.get("tool")), 0) + 1
        c["tools"] = [{"role": r["name"], "name": t["name"], "title": t["title"], "fallback_role": t["fallback_role"],
                       "machine": r["machine"], "misses": misses.get((r["name"], t["name"]), 0)}
                      for r in shape["roles"].values() for t in r["tools"]]
        tree.contacts(c, shape)   # 受ける仕事ごとの宛て方と窓口
        c["inbox"] = inbox
        for d in c["departments"]:
            here = g.git_dir(d["path"]) if inbox else None
            d["queue"] = len(wake.queued(inbox, here)) if here else 0
            d["queue_dir"] = wake.queue_dir(inbox, here) if here else None
            d["stalled"] = bool(here) and wake.stalled(inbox, here, d.get("attrs") or {})
            d["held"] = wake.held(inbox, d["path"], here, d.get("attrs") or {}) if here and not d["stalled"] else None
            attrs = d.get("attrs") or {}
            d["no_talk_id"] = bool(attrs.get("role")) and not d.get("head_office") and not attrs.get("session")
    asks_of(companies)
    return companies


def asks_of(companies):
    """会社ごとに、まだ閉じていない頼み（deliver.open_asks。頼み元と宛先の会社の台帳を足し合わせて見るので、会社をまたぐ頼みも
    出る）を、宛先の会社の asks に足す。1 件は {id, at, from, to, state, title}。state は「順番待ち n 件目」か「渡った」か、宛先の
    部署がもう無いときはそう書く（納品も取り下げも無いまま部署が畳まれた頼み。窓口が見て、要れば頼み直す）。"""
    inboxes = list(dict.fromkeys(c["inbox"] for c in companies if c.get("inbox")))
    records = sorted((r for x in inboxes for r in deliver.records(x)), key=lambda r: r.get("at") or 0)
    for c in companies:
        c["asks"] = []
    held = {(d.get("attrs") or {}).get("ask") for c in companies for d in c["departments"]
            if (d.get("attrs") or {}).get("ask") and (d.get("attrs") or {}).get("delivered") != (d.get("attrs") or {}).get("ask")}
    for r in deliver.open_asks(records, held):
        to = r.get("to") or {}
        # 同じ名前の会社（同じリポジトリの別の clone）が並ぶので、宛先の部署の場所を持つ会社を先に、無ければ名前の合う最初の会社
        named = [c for c in companies if c["name"] == to.get("company")]
        here = os.path.realpath(to["path"]) if to.get("path") else None
        c = next((c for c in named if here and any(os.path.realpath(d["path"]) == here for d in c["departments"])), None)
        gone = c is None and bool(here)   # 宛先の部署がもう無い（畳まれた・消えた）
        c = c or (named[0] if named else None)
        if c is None:
            continue
        item = wake.find(c["inbox"], r["id"]) if c.get("inbox") else None
        if item:
            line = [q.get("id") for q in wake.listed(os.path.dirname(item["path"]))]
            state = f"順番待ち {line.index(r['id']) + 1} 件目" if r["id"] in line else "順番待ち"
        else:
            state = "宛先の部署が無い（畳まれたか消えた。閉じる記録が無い）" if gone else "渡った"
        c["asks"].append({"id": r["id"], "at": r.get("at"), "from": (r.get("from") or {}).get("name"), "to": to.get("name"),
                          "state": state, "title": r.get("title") or deliver.ask_title(r.get("file"))})


def fire(after, root, ports, a, task, attrs):
    """--land の合図: メインブランチに入れた後に [[land.after]] のツールを順に呼ぶ。出す行の並び（終了の値は --land に響かせない）。
    attrs はメインブランチに入れた部署の属性で、その頼み元を回す頼みの頼み元に、その頼み（ask）を回す頼みの親（台帳の cause）にする。"""
    if not after:
        return []
    info = tree.read_info(root, os.path.dirname(config.path_of(a.config, os.environ)))
    company = tree.company_name(root, info)
    shape = role.load(info["path"], info["text"])
    boss = {k: attrs.get(k) for k in ("ask", "boss", "boss-account", "boss-session", "boss-pane", "boss-inbox")}
    lines = []
    for x in after:
        rc, out = invoke(root, company, role.current(shape, x["role"]), x["tool"], x.get("input") or {}, shape["roles"], ports, a, task, boss=boss)
        state = {0: "片づいた", CALLED: "AI に回した"}.get(rc, "呼べなかった")
        lines.append(f"合図（メインブランチに入れた後）: {x['role']}/{x['tool']} {state}")
        lines += [f"  {line}" for item in out for line in item.splitlines()]
    return lines
