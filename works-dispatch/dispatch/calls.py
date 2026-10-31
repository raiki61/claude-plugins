#!/usr/bin/env python3
"""機械窓口の流れ（受付の設計 docs/specs/2026-10-17-reception-design.md の 5 章）。入口の dispatch.py --call と、--land の合図
（会社の形の [[land.after]]）と、部署を立てた後の合図（[[task.after]]）から呼ぶ。ツールの中身（入力の確かめ・回す頼みの字）は nodes/tools.py、ツールの定義を読むのは role ノード。

--call <会社/役> <ツール>（call）: ツールを origin の既定のブランチの中身（一時の worktree。tools.place）のルートで走らせ、入力の JSON を標準入力に渡す。終了の値 0 なら片づいた（答えを出して
0 で終わる）。0 以外なら外れを受付箱の台帳に残し、その入力を AI への頼みに変えて回す（orders.ask と同じ宛て方。回す役の always の部署が
在ればその順番待ちに積み、無ければ一度きりの部署を自動で立てる）。回したら受付番号を出して 3 で終わる。ただし、打った部署が受けている
頼みが、同じツールの同じ入力が片づかずに回った頼みなら（その頼みの中での打ち直し）、回さずに失敗を出して 1 で終わる（rerun_of）。
入力の dry_run が true の呼び（空打ち）も、片づかなければ回さずに 1 で終わる（DRY_RUN）。
合図（fire）: --land がメインブランチへ push し終えた後に、[[land.after]] の並びの順に同じ走らせ方で呼ぶ。回した頼みの頼み元は、メインブランチに入れた
部署の頼み元。
部署を立てた後の合図（task_later・after_task）: 部署を新しく立てたら（dispatch._task）、[[task.after]] の並びを --after-task で会話から
切り離して裏で同じ走らせ方で呼ぶ。回した頼みの頼み元は、その会社の窓口（orders.lent_boss）。
"""

import argparse
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import time
import tomllib

import config
import filex
import gitx
from ports import term
import orders
import health
import starts
from nodes import clean, deliver, land, role, tools, tree, wake

CALLED = 3   # 片づかず AI に回した --call の終了の値
# ツールの入力のうち、空打ち（知らせる物を出すだけで、覚えず何も打たない）を頼む鍵。この鍵が true の呼びは、片づかなくても AI に回さない
# （ツールは知らせる物が在ると 1 で終わるので、回すと空打ちのたびに部署が立つ）
DRY_RUN = "dry_run"
TASK_AFTER_LOG = "task-after.log"     # 受付箱の下の、部署を立てた後の合図の出力の置き場（打つたびに書き足す。task_later）
TASK_AFTER_LOCK = "task-after.lock"   # 受付箱の下の、部署を立てた後の合図が会社ごとに掛ける錠（after_task）
DISPATCH_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatch.py")
WORKS_LAND_MEMBERS = "WORKS_LAND_MEMBERS"   # 束の合図でツールに渡す、束の部署の名前の並び（改行で区切る。束の設計 9）
# ツールに渡す環境変数の名（ツールが works-dispatch を打ち返すため。docs/land.md の「外のツールが列に並ぶ」）
WORKS_DISPATCH, WORKS_DISPATCH_PYTHON = "WORKS_DISPATCH", "WORKS_DISPATCH_PYTHON"


def tool_env():
    """ツールに渡す環境。ツールが works-dispatch を打ち返せるよう（--queue-run で --land と同じ列に並ぶなど）、今走っている dispatch.py の
    パスを WORKS_DISPATCH に、それを走らせている Python を WORKS_DISPATCH_PYTHON に入れる。"""
    return {**deliver.child_env(), WORKS_DISPATCH: str(pathlib.Path(__file__).resolve().with_name("dispatch.py")),
            WORKS_DISPATCH_PYTHON: sys.executable}


def run_tool(command, cwd, value, env=None):
    """ツールを cwd で走らせる（シェルの字）。入力の JSON を標準入力に渡す。env はツールの環境に足す変数。
    (終了の値, 標準出力, 標準出力と標準エラー)。"""
    p = subprocess.run(command, shell=True, cwd=cwd, input=json.dumps(value, ensure_ascii=False), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env={**tool_env(), **(env or {})})
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
        except term.Error as e:
            return None, f"{term.NAME} を読めないので会社「{company}」を探せない（{e}）"
        hit = [c for c in companies if c["name"] == company or os.path.basename(os.path.normpath(c["root"])) == company]
        if not hit:
            return None, f"会社「{company}」が {term.NAME} に開いていない"
        try:
            root = deliver.one_company(hit, company)["root"]
        except deliver.DeliverError as e:
            return None, str(e)
    else:
        common = ports.git.common_dir(cwd)
        if not common:
            return None, f"{cwd} が git でないので会社が決まらない（「会社/役」で渡す）"
        root = gitx.root_of(common)
    info = tree.read_info(root, settings, ports.git)
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


def invoke(root, company, role_name, tool_name, value, roles, ports, a, task, boss=None, cwd=None, env=None, causes=()):
    """ツールを 1 つ走らせ、片づかなければ回す。(終了の値 0・3・1・2, 出す行の並び)。boss は回す頼みの頼み元の属性の上書き。
    env はツールの環境に足す変数、causes は回す頼みの台帳の親に足す頼みの受付の並び（束の合図。calls.fire）。"""
    found, why = tools.find(roles, role_name, tool_name)
    if why:
        return 2, [f"止めた: {why}"]
    the_role, tool = found
    bad = tools.check_input(tool["inputSchema"], value)
    if bad:
        return 2, [f"止めた: ツール {role_name}/{tool_name} の入力が形に合わない: " + "、".join(bad)]
    inbox = deliver.inbox_of(ports.git.common_dir(root))
    try:
        with tools.place(root, ports.git) as (here, note):
            code, out, both = run_tool(tool["command"], here, value, env)
    except (gitx.GitError, OSError) as e:
        # 一時の worktree を作れない（残ったパス・index.lock など）。--land の後の合図（fire）も、残りのツールと片付けまで進める。
        # ツールは走っていないので外れ（miss）とは数えず、ほかの部署へも回さない。後から追えるように失敗の行だけ台帳に残す
        lines = [f"止めた: ツールを走らせる場所を作れない（{e}）"]
        try:   # 台帳にも書けないときは行で知らせ、合図の残りのツールを止めない
            deliver.log(inbox, {"kind": "call", "status": "failed", "role": role_name, "tool": tool_name, "input": value,
                                "why": f"ツールを走らせる場所を作れない（{e}）", "at": ports.now()})
        except OSError as e2:
            lines.append(f"失敗の行を台帳に書けなかった（{e2}）")
        return 1, lines
    if code == 0:
        deliver.log(inbox, {"kind": "call", "status": "done", "role": role_name, "tool": tool_name, "at": ports.now()})
        return 0, [x for x in [note, out.rstrip("\n")] if x and x.strip()]
    if isinstance(value, dict) and value.get(DRY_RUN) is True:
        # 空打ちの外れは回さず、外れとも数えない（台帳に残さない。ツールは何も打っていない）
        return 1, [x for x in [note, out.rstrip("\n")] if x and x.strip()] + [
            f"ツール {role_name}/{tool_name} は片づかなかった（終了の値 {code}）が、空打ち（入力の {DRY_RUN} が true）なので AI に回さない"]
    out_tail = tools.tail(both)
    again = rerun_of(inbox, cwd or root, role_name, tool_name, value, ports, a) if boss is None else None
    ask_id = None if again else deliver.new_id(ports.now())
    deliver.log(inbox, {"kind": "miss", "role": role_name, "tool": tool_name, "input": value, "code": code, "tail": out_tail,
                        "at": ports.now(), **({"rerun_of": again} if again else {"ask": ask_id})})
    if again:
        # 片づかずに回った頼みを受けた部署が、その頼みの中で同じ入力を打ち直した: 回すと同じ頼みがもう 1 つ積まれるので、失敗を打った会話に返す
        return 1, [f"ツール {role_name}/{tool_name} は片づかなかった（終了の値 {code}）。この会話が受けている頼み（受付 {again}）が、"
                   "同じ入力でこのツールが片づかずに回った頼みなので、もう一度は回さない。ツールの出力の終わり:", out_tail]
    return hand_over(root, company, role_name, tool, value, code, out_tail, ports, a, task, boss, cwd or root, ask_id, causes)


def rerun_of(inbox, cwd, role_name, tool_name, value, ports, a):
    """打った場所が受けている、まだ納品していない頼み（台帳の cause と同じ物）が、このツールのこの入力が片づかずに回った頼み
    （外れの行の ask がその受付で、role・tool・input が同じ）なら、その受付。でなければ None。入力は JSON の値で比べる（鍵の順は見ない）。"""
    held = orders.cause_of(a, cwd, ports)
    if not held:
        return None
    hit = any(r.get("kind") == "miss" and r.get("ask") == held and (r.get("role"), r.get("tool"), r.get("input")) == (role_name, tool_name, value)
              for r in deliver.records(inbox))
    return held if hit else None


def hand_over(root, company, role_name, tool, value, code, out_tail, ports, a, task, boss, cwd, ask_id=None, causes=()):
    """片づかなかったツールの仕事を、回す役への頼みに変えて orders.ask に渡す。(終了の値, 出す行)。ask_id は回す頼みの受付（外れの行の ask）。
    causes は頼みの行の causes（台帳の親の頼み〔cause〕に並べて結ぶ頼み）。"""
    ask_id = ask_id or deliver.new_id(ports.now())
    caller_inbox = deliver.inbox_of(ports.git.common_dir(cwd) or ports.git.common_dir(root))
    brief = deliver.put(caller_inbox, f"{ask_id}-call.md", tools.miss_text(role_name, tool, value, code, out_tail))
    to = tool["fallback_role"]
    try:
        *_, companies, settings, _ = orders.survey(a.config, ports)
        # 前の役の名前（former_names）を属性に持つ部署にも当たるように、--ask と同じく今の役の名前に引き直して探す
        target = deliver.find_target(companies, root, f"{company}/{to}", None, orders.current_role(settings, ports.git))
    except (term.Error, deliver.DeliverError) as e:
        return 1, [f"ツール {role_name}/{tool['name']} は片づかなかった（終了の値 {code}）が、{to} に回せなかった（{e}）"]
    ask, task_name = f"{company}/{to}", tools.auto_name(role_name, tool)
    duty = next((s for s in target["company"].get("skills", []) if s.get("name") == to), None)
    if target["department"] is None and duty and not target.get("on_demand") and duty.get("role"):
        # 立っていない受け持ちの部署には、--tree の宛て方（--ask 会社/<役> --task <受け持ち>）と同じく、受け持ちの役でその名前の部署を立てる
        ask, task_name = f"{company}/{duty['role']}", to
    auto = target["department"] is None and not target.get("on_demand")   # on-demand の受け持ちは orders.ask が部署の名前とブランチを決める
    ns = argparse.Namespace(**{**vars(a), "ask": ask, "text": None, "brief": brief, "dry_run": False,
                               "task": task_name if auto else None,
                               "branch": tools.auto_branch(tool, ask_id) if auto else None,
                               "role": None, "persistent": False, "ask_id": ask_id, "from_boss": boss, "causes": list(causes),
                               "self_queue": True, "title": f"ツール {role_name}/{tool['name']} が片づけられなかった仕事"})
    head = f"ツール {role_name}/{tool['name']} は片づかなかった（終了の値 {code}）。{to} に回した"
    # --ask の出す行（止めた訳・積んだ先）は、この行の下に並べて返す。そのまま書かせると、--land の合図では合図の行より前の、
    # 離れた所に出て、「頼みが通らなかった」の訳が読めなかった（受付 20261031-122658-baff87。頼み c02eef）
    said = io.StringIO()
    try:
        with contextlib.redirect_stdout(said):
            rc = orders.ask(ns, ports, cwd, task)
    except BaseException:
        sys.stdout.write(said.getvalue())   # 誤りで抜けても、そこまでに書いた物を捨てない
        raise
    told = [x for x in said.getvalue().splitlines() if x.strip()]
    if rc != 0:
        return 1, [f"{head}が、頼みが通らなかった（終了の値 {rc}）。--ask の出力:"] + [f"  {x}" for x in told]
    return CALLED, [f"{head}: 受付 {ask_id}" + (f"（部署 {ns.task} を立てた）" if auto else "")] + [f"  {x}" for x in told]


def call(a, ports, cwd, task):
    """--call。終了の値（0 片づいた・3 AI に回した・1 回せなかったか、打ち直しか空打ちなので回さなかった・2 使い方の誤り）。"""
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
    queue_dir に、渡す待ち受けが居なくて止まっているか（wake.stalled）を stalled に、そのうち受けたままの頼みを持つ会話がもう居ない
    物（tree.talk_gone）を holder_gone に、待ち受けは居るが渡さずに待っている訳（wake.held）を
    held に、部署の属性に会話の id（company.session）が無いかを no_talk_id に、裏の処理を残したターンの終わりから同じ頼みのまま
    長く動いていないか（wake.long_wait）を long_wait に。外れは受付箱の台帳の kind miss の行で数える。
    会社ごとの壊れの注記（裏の処理の失敗・誰も受けない頼み・台帳の大きさ・周期の遅れ・一時の置き場の控え。health.py）を health に。
    会社の形の役を読んで外した物（role.load の problems）を problems に足す。"""
    for c in companies:
        common = g.common_dir(c["root"])
        inbox = deliver.inbox_of(common) if common else None
        info = tree.read_info(c["root"], settings, g)
        shape = role.load(info["path"], info["text"])
        # 会社の形の役で外した物（回す先の無いツールなど）も注記に出す。外しただけでは --land の合図が黙って呼ばれなくなるため
        c["problems"] = c.get("problems", []) + [p for p in shape["problems"] if p not in c.get("problems", [])]
        misses, records = {}, deliver.records(inbox) if inbox else []
        for r in records:
            if r.get("kind") == "miss":
                misses[(r.get("role"), r.get("tool"))] = misses.get((r.get("role"), r.get("tool")), 0) + 1
        c["tools"] = [{"role": r["name"], "name": t["name"], "title": t["title"], "fallback_role": t["fallback_role"],
                       "machine": r["machine"], "misses": misses.get((r["name"], t["name"]), 0),
                       "account": _fallback_account(shape, c.get("skills", []), t["fallback_role"])}
                      for r in shape["roles"].values() for t in r["tools"]]
        tree.contacts(c, shape)   # 受ける仕事ごとの宛て方と窓口
        c["inbox"] = inbox
        now = time.time()
        c["health"] = (health.inbox_notes(inbox, now) + health.due(c["skills"], records, now)
                       + (health.kept_tmp(os.path.join(common, *clean.KEPT_TMP), now)
                          + health.boards_archive(os.path.join(common, *clean.BOARDS_ARCHIVE)) if common else []))
        for d in c["departments"]:
            here = g.git_dir(d["path"]) if inbox else None
            d["queue"] = len(wake.queued(inbox, here)) if here else 0
            d["queue_dir"] = wake.queue_dir(inbox, here) if here else None
            attrs = d.get("attrs") or {}
            d["stalled"] = bool(here) and wake.stalled(inbox, here, attrs, gone=d.get("talk_gone"))
            d["held"] = wake.held(inbox, d["path"], here, attrs, d.get("talk_gone")) if here and not d["stalled"] else None
            d["holder_gone"] = bool(d["stalled"] and d.get("talk_gone") and wake.pending(attrs))
            d["no_talk_id"] = bool(attrs.get("role")) and not d.get("head_office") and not attrs.get("session")
            d["long_wait"] = wake.long_wait(inbox, here, attrs, now) if here else None
    asks_of(companies)
    return companies


def _fallback_account(shape, skills, to):
    """片づかなかった仕事を回す先 to（役か受け持ちの名前）の部署を立てるときに、先に使うアカウント（role.launch_account）。hand_over と
    同じく、to が役を持つ受け持ちの名前ならその受け持ちとその役、ほかは役で引く（役の無い受け持ちへは hand_over が役 to で
    ツールの名前の部署を立てるので、受け持ちの値は効かない）。--tree のツールの行に出す。"""
    duty = next((s for s in skills if s.get("name") == to and s.get("role")), None)
    the_role = shape["roles"].get(role.current(shape, duty["role"] if duty and duty.get("role") else to))
    return role.launch_account(the_role, duty)[0]


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


def fire(after, root, ports, a, task, attrs, members=()):
    """--land の合図: メインブランチに入れた後に [[land.after]] のツールを順に呼ぶ。出す行の並び（終了の値は --land に響かせない）。
    attrs はメインブランチに入れた部署の属性で、その頼み元を回す頼みの頼み元に、その頼み（ask）を回す頼みの親（台帳の cause）にする。
    members は束（束の設計 9）で一緒に入れた部署の属性の並び。ツールに部署の名前の並び（$WORKS_LAND_MEMBERS。改行で区切る）を渡し、
    どの部署の変更が原因か分からないので、乗った部署の受けている頼みも回す頼みの親に並べる（頼みの行の causes）。"""
    if not after:
        return []
    info = tree.read_info(root, os.path.dirname(config.path_of(a.config, os.environ)), ports.git)
    company = tree.company_name(root, info)
    shape = role.load(info["path"], info["text"])
    boss = {k: attrs.get(k) for k in ("ask", "boss", "boss-account", "boss-session", "boss-pane", "boss-inbox")}
    env = {WORKS_LAND_MEMBERS: "\n".join(m.get("name") or "" for m in [attrs, *members])} if members else None
    causes = [m["ask"] for m in members if m.get("ask") and m.get("delivered") != m["ask"] and m["ask"] != attrs.get("ask")]
    return _signal(after, "メインブランチに入れた後", root, company, shape, ports, a, task, boss, env, causes)


def _signal(after, when, root, company, shape, ports, a, task, boss, env=None, causes=()):
    """合図の並び after のツールを順に呼んだ出す行の並び。when は行の頭に書く、いつの合図か。"""
    lines = []
    for x in after:
        rc, out = invoke(root, company, role.current(shape, x["role"]), x["tool"], x.get("input") or {}, shape["roles"], ports, a, task,
                         boss=boss, env=env, causes=causes)
        # 1 は、ツールが片づけず（知らせる物が在る、など。ツールの正しい終わり方）AI に回そうとして回せなかったか、空打ちなので回さなかったか、
        # ツールを走らせる場所を作れなかった。どれも訳は下の行に在る。前は 1 も「呼べなかった」と出し、ツールが壊れたように読めた（頼み c02eef）
        state = {0: "片づいた", CALLED: "AI に回した", 2: "呼べなかった"}.get(rc, "AI に回さなかったか回せなかった（訳は下の行）")
        lines.append(f"合図（{when}）: {x['role']}/{x['tool']} {state}")
        lines += [f"  {line}" for item in out for line in item.splitlines()]
    return lines


def task_rules(info):
    """会社の形の [[task.after]]（部署を立てた後に呼ぶツールの並び。形は [[land.after]] と同じ）。(並び, 注記の並び)。
    info は tree.read_info の答え。形の違う項目は注記に書いて外す。"""
    try:
        raw = tomllib.loads(info["text"]).get("task") if info.get("text") else None
    except tomllib.TOMLDecodeError:
        return [], []   # 読めない会社の形は tree.read_info が problems に書いている
    if raw is None:
        return [], []
    if not isinstance(raw, dict):
        return [], [f"{info.get('path')}: task が表で無い"]
    problems = []
    return land._after(raw.get("after", []), info.get("path"), problems, "task.after"), problems


def task_later(a, ports, source, place):
    """部署を新しく立てた後に、会社の形の [[task.after]] を、--after-task <部署の場所> で会話から切り離して裏で呼ぶ（終わりを待たない。
    ツールが --land まで打つと何分もかかるので、部署を立てる --task・--ask を待たせない。starts.due_later と同じ形）。出力は会社の受付箱の
    task-after.log に書き足す。打った会話の印（starts.CALLER_ENV）は渡さない。打てなければ注記の 1 行、打てたら None を返す。"""
    try:
        common = ports.git.common_dir(source)
        log = os.path.join(deliver.inbox_of(common), TASK_AFTER_LOG)
        argv = [sys.executable, DISPATCH_PY, "--after-task", place] + (["--config", a.config] if a.config else [])
        env = {k: v for k, v in ports.env.items() if k not in starts.CALLER_ENV}
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ports.now()))} 部署 {os.path.basename(place)} を立てた後\n")
        ports.spawn(argv, source, log, env)
    except Exception as e:  # 部署はもう立った。合図を打てなくても、--task の終了の値を変えない
        return f"注記: 部署を立てた後の合図（[[task.after]]）を裏で打てなかった（{e}）。要れば dispatch.py --after-task {place} を手で打つ"
    return None


def after_task(a, ports, task):
    """--after-task <部署の場所>: その部署の会社の [[task.after]] のツールを順に呼ぶ。終了の値（0 呼んだか呼ぶ物が無い・2 場所が違う）。
    回した頼みの頼み元はその会社の窓口（頼み元を空で渡し、orders.lent_boss が窓口に決める。立った部署の頼み元は、この合図を頼んでいない）。
    同じ会社の合図が裏で並んだら、待たずに後の方を飛ばす（先の方が同じツールを呼んでいる）。"""
    place = os.path.abspath(a.after_task)
    common = ports.git.common_dir(place)
    if not common:
        print(f"止めた: {place} は git の作業場で無い")
        return 2
    root = gitx.root_of(common)
    info = tree.read_info(root, os.path.dirname(config.path_of(a.config, os.environ)), ports.git)
    after, notes = task_rules(info)
    lines = [f"注記: {n}" for n in notes]
    if not after:
        print("\n".join(lines + ["呼ぶ物は無い（会社の形に [[task.after]] が無い）"]))
        return 0
    inbox = deliver.inbox_of(common)
    os.makedirs(inbox, exist_ok=True)
    with filex.lock(os.path.join(inbox, TASK_AFTER_LOCK), wait=False) as got:
        if not got:
            print("\n".join(lines + ["飛ばした: 同じ会社の、部署を立てた後のほかの合図が呼んでいる"]))
            return 0
        shape = role.load(info["path"], info["text"])
        name = (ports.attrs(place) or {}).get("name") or os.path.basename(place)
        lines += _signal(after, f"部署 {name} を立てた後", root, tree.company_name(root, info), shape, ports, a, task,
                         boss={"boss": None})
    print("\n".join(lines))
    return 0
