#!/usr/bin/env python3
"""--move <部署か窓口>（move）: 立っている部署か本社の窓口の会話を、ほかのアカウントで起こし直す（37f8b1・d7d50c の 3）。

常設の会話は、起こしたアカウントが 5 時間か 1 週間の使用上限に当たると、上限が戻るまで止まる。--move は、移る先のアカウント
（--account で名指すか、使用率の順で今のアカウントの次に空いている物）で、同じ役・名前・場所の会話を起こし直す。同じ役の会話が
同時に 2 つ動かないよう、前の会話を止めてから起こす。会話の記憶は引き継がない（自動の覚え書きにも頼らない）ので、起こした会話への
最初の文で、受けている頼み（属性 company.ask と頼みのファイル）と作業場の枝から続きへ戻らせる。

- 部署（裏の会話。claude --bg）: 窓の attach の画面をシェルに戻し（launch.to_shell）、前の会話を claude stop で止め、--task と同じ道
  （dispatch._task）で同じ名前・枝・役の会話を、移る先のアカウントで起こす。頼み元の属性（company.boss など）はそのまま残す。
- 本社の窓口（持ち主の前で動く会話。--desk で名付けた物）: 窓口の窓に /exit を打って前の会話を終え、同じペインで
  `<移る先のコマンド> --name <窓口の名前> <最初の文>` を打つ。起きた会話は窓口の席に座り（前の会話が終わっていて、名前が窓口の名前なので、
  会話の始まりのフックが役の本文を足す）、最初の文のとおり --desk を打って属性を自分に付け替える。

--if-limited は、上限に当たって止まったときのフック（limit_hook.py）が付ける。今のアカウントの使用率の控えが上限に達していなければ
（一時の混み合いの rate_limit）、移さずに終わる。移したことは会社の受付箱の台帳に kind moved で残す。
"""

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import claudex  # noqa: E402
import config  # noqa: E402
import gitx  # noqa: E402
import herdr  # noqa: E402
import orders  # noqa: E402
from nodes import accounts, deliver, launch, provision  # noqa: E402

RESIDENT = "resident"
LIMITED = "使用上限に当たった"   # 台帳の why（--if-limited で移したとき）
# 起こし直しても残す頼み元の属性（--task が呼んだ会話で書き直す物）
KEEP = ("boss", "boss-account", "boss-session", "boss-pane", "boss-inbox")
# 前の裏の会話が止まったのを会話の一覧で見る回数（1 回ごとに ports.pause）
STOP_LOOKS = 20


def move(a, ports, cwd, task):
    """--move。終了の値。"""
    common = ports.git.common_dir(cwd)
    try:
        cfg, accounts_, sessions_, _, companies, settings, notes = orders.survey(a.config, ports)
        target = deliver.find_target(companies, gitx.root_of(common) if common else None, a.move)
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
        return 1
    except deliver.DeliverError as e:
        print(f"止めた: {e}")
        return 2
    company, dept = target["company"], target["department"]
    if dept is None:
        print("\n".join(notes + [f"止めた: 「{a.move}」という部署も窓口も無い（起こし直すのは立っている部署か、--desk で名付けた窓口）"]))
        return 2
    if cfg is None:
        print("\n".join(notes + ["止めた: 起こし直すには、読める dispatch の設定が要る（アカウントと使用率の上限を読む）"]))
        return 2
    attrs = dept["attrs"]
    old = attrs.get("account")
    names = [x.name for x in cfg.accounts]
    metered = [x.name for x in cfg.accounts if x.limits]
    if not a.dry_run:
        ports.refresh_limits(cfg, metered)
    ranked = accounts.rank(cfg.accounts, ports.read_limits(cfg.limits_dir, metered), cfg.limit_percent, ports.now(),
                           accounts.count_running(sessions_), cfg.reset_soon_hours)
    mine = next((r for r in ranked if r["name"] == old), None)
    if a.if_limited and mine and mine["known"] and mine["eligible"]:
        print("\n".join(notes + [f"移さない: アカウント {old} の使用率は上限 {cfg.limit_percent}% に達していない（一時の混み合いと見る）"]))
        return 0
    if a.account:
        if a.account not in names:
            print(f"止めた: --account の {a.account} が設定の accounts に無い（{', '.join(names)}）")
            return 2
        chosen = a.account
    else:
        chosen = next((r["name"] for r in ranked if r["name"] != old and r["eligible"]), None)
        if chosen is None:
            print("\n".join(notes + [f"止めた: 移れるアカウントが無い（{old or '-'} のほかに、使用率が上限に届かないアカウントが無い）"]))
            return 2
    if chosen == old:
        print(f"止めた: {a.move} はもうアカウント {old} で動いている")
        return 2
    head = bool(dept.get("head_office"))
    where = f"{company['name']}/{attrs.get('name') or dept['branch']}"
    why = LIMITED if a.if_limited else "持ち主か窓口が移した"
    if a.dry_run:
        print("\n".join(notes + [f"{'窓口' if head else '部署'} {where} をアカウント {old or '-'} から {chosen} へ起こし直す（{why}）"]))
        return 0
    acc = {x.name: x for x in cfg.accounts}
    text = _first_text(attrs, dept, old, chosen, why, head)
    if head:
        rc, said = _move_desk(dept, acc[chosen], text, ports)
    else:
        rc, said = _move_dept(a, cfg, company, dept, acc.get(old), chosen, text, ports, task, settings)
    inbox = deliver.inbox_of(ports.git.common_dir(company["root"]))
    deliver.log(inbox, {"kind": "moved", "at": ports.now(), "name": attrs.get("name"), "path": dept["path"], "from": old,
                        "to": chosen, "why": why, "status": "done" if rc == 0 else "failed", "detail": said})
    print("\n".join(notes + [f"{'窓口' if head else '部署'} {where}: アカウント {old or '-'} → {chosen}  "
                             + ("起こし直した" if rc == 0 else "起こし直せなかった") + (f"（{said}）" if said else "")]))
    return rc


def _first_text(attrs, dept, old, chosen, why, head):
    """起こし直した会話への最初の文。会話の記憶は引き継がないので、続きへ戻る手がかり（頼みと枝）を渡す。"""
    ask = attrs.get("ask")
    pending = ask and attrs.get("delivered") != ask
    file = os.path.join(attrs.get("boss-inbox") or "", f"{ask}-ask.md") if pending else None
    head_line = (f"前の会話（アカウント {old or '-'}）が使用上限に当たったので、アカウント {chosen} で起こし直した。" if why == LIMITED else
                 f"前の会話（アカウント {old or '-'}）を、アカウント {chosen} へ移して起こし直した（--move）。") + "前の会話の記憶は引き継いでいない。"
    if head:
        head_line += (f" まず、この会話の中から works-dispatch の --desk {attrs.get('name') or ''} を打って、窓口の席をこの会話に移す。"
                      "次に、受付箱の台帳（log.jsonl）と、本社の属性の頼み（company.ask）から、受けていた仕事の続きへ戻る。")
    if pending:
        head_line += (f" 受けている頼みは受付 {ask}（本文: {file if file and os.path.isfile(file) else '受付箱の ' + ask + '-ask.md'}）。"
                      f"作業場の枝 {dept['branch'] or '-'} の commit と差分（git status・git log）から、続きを再開する。")
    elif not head:
        head_line += " 受けている頼みは無い。次の頼みを待つ。"
    return head_line


def _move_dept(a, cfg, company, dept, old_acc, chosen, text, ports, task, settings):
    """部署の裏の会話を止め、--task と同じ道で移る先のアカウントの会話を起こす。(終了の値, 言葉)。"""
    attrs = dept["attrs"]
    pane = next((p["pane_id"] for p in dept["panes"]), None)
    if pane and not launch.to_shell(pane, ports.herdr, ports.pause):
        return 1, f"部署の窓 {pane} をシェルに戻せない（attach の画面を手で閉じてから打ち直す）"
    job = attrs.get("job") or attrs.get("session")
    if job:
        ok, said = ports.stop_session(old_acc.config_dir if old_acc else None, job)
        if not ok:
            return 1, f"前の会話 {job} を止められない（{said}）"
        for _ in range(STOP_LOOKS):
            try:
                items = ports.list_sessions(old_acc.config_dir if old_acc else None)
            except claudex.ClaudeError:
                break
            if not any(s.get("name") == attrs.get("name") and s.get("state") not in ("done", "failed", "stopped") for s in items):
                break
            ports.pause()
    # 新しい会話の待ち受けが、前の会話の id を見て待たないことの無いよう、会話の id を消してから起こす（--task が新しい id を書く）
    provision.mark(dept["path"], company["root"], {"session": None, "job": None}, ports.git)
    brief = os.path.join(ports.git.git_dir(dept["path"]), "move-brief.md")
    pathlib.Path(brief).write_text(text + "\n", encoding="utf-8")
    ask = attrs.get("ask")
    pending = ask and attrs.get("delivered") != ask
    the_role, _ = orders.shape_role(company["root"], settings, attrs.get("role"))
    tail = deliver.tail(deliver.required_items(the_role), orders.RUN) if pending else None
    ns = argparse.Namespace(**{**vars(a), "task": attrs.get("name"), "branch": dept["branch"], "brief": brief,
                               "role": attrs.get("role"), "resident": attrs.get("residency") == RESIDENT, "from_name": None,
                               "from_account": None, "only_account": chosen, "base": None, "dry_run": False})
    repo = config.repo_at(cfg, company["root"], ports.origin)
    rc = task(cfg, repo, ns, ports, extra_attrs={k: attrs.get(k) for k in KEEP}, tail=tail)
    return (0, None) if rc == 0 else (rc, "--task と同じ道で起こせなかった（上の出力を見る）")


def _move_desk(dept, acc, text, ports):
    """窓口の会話を /exit で終え、同じペインで移る先のアカウントの会話を窓口の名前で起こす。(終了の値, 言葉)。"""
    attrs = dept["attrs"]
    sid = attrs.get("session")
    pane = next((p["pane_id"] for p in dept["panes"] if sid and p.get("agent_session") == sid), None)
    if pane is None:
        return 1, "窓口の会話の居るペインが分からない（属性の会話 company.session の居るペインが無い）"
    if not deliver.exit_talk(pane, ports.herdr, ports.pause):
        return 1, f"窓口の窓 {pane} に /exit を打ったが、シェルに戻らない"
    got = launch.start_named(acc.command, pane, attrs.get("name") or "窓口", text, ports.herdr)
    return (0, None) if got["status"] == "ready" else (1, got["detail"] or got["status"])
