#!/usr/bin/env python3
"""自分の番の PR ごとに、そのブランチの作業場（元の clone の git worktree と herdr の作業場）を用意し、選んだアカウントの Claude Code で起動し、
1 ターン目に `/catchup <番号>`、2 ターン目に設定の文を送る。AI は使わない（設計書 works-dispatch/docs/specs/2026-10-14-catchup-dispatch-design.md）。

流れ（どのノードの次に何を呼ぶか）を持つのはこのファイルだけ。ノードは流れを知らない（D3）。
1. 始める前の確かめ。足りない物があれば全部並べて、何も起動せずに終了の値 2 で止まる
2. prs → sessions → （一覧で回すときは fresh）→ accounts → assign（ここまで外には書かない。--dry-run はここで、作業場を作るか使い直すかを
   報告して終える）
3. provision・信頼の印（元の clone を信頼済みのアカウントなら worktree にも付ける）・launch を 1 件ずつ順に全部先に済ませ、turn を 1 件ずつ
   並べて走らせる（1 件の /catchup が長くても、ほかが遅れない）
4. report
止まっている（blocked）・会話が開いている（already_open）などは誤りではないので、終了の値は 0。

一覧で回すとき（--pr・--issue 無し）は、2 の fresh で、自分が作者でレビュアーの付いていない PR を外し、会話の開いている PR を送り直すか決める。
会話の開いていない PR も、前に送った控えが有って、その後に自分以外の動きも head の変化も無ければ開かない（no_news）。
送り直す PR は、provision の前に古い会話を終えて（turn.close_session）ペインの作業場を畳み（clean.release）、同じ場所に立て直す。
前からある場所で 2 ターン目まで送る PR は、新しい会話を起動する前に、その場所で前に開いた会話の報告を残し（_earlier_report）、
2 ターン目の後ろの一言でその場所を渡す（turn.keep_report・with_carry）。
最後に、自分の番でなくなった PR の、dispatch が開いた会話を終えて作業場を閉じ（_step_back。worktree は残す。whose-turn の limited に
入った PR は、自分の番でないという判定が取りこぼしの上に立つので閉じない）、閉じた PR の場所を片付ける（_tidy。--dry-run は並べるだけ）。

片付け（--clean）は、元の clone の linked worktree のうち消してよいものを並べるだけで、--apply を付けた時だけ消す（nodes/clean.py）。

--pr N は自分の番の一覧（whose-turn）を使わず、指した PR だけを開く。止めている実装や、見に行くだけの PR に使う。
--issue N は、issue に結んだブランチの場所を開き（ブランチが無ければ GitHub に作って issue に結ぶ）、1 ターン目の /catchup N まで送って止める。
--no-second は 2 ターン目の文を送らず、/catchup だけで止める。

--task 名前 は、部署を 1 つ立てる（_task）。ブランチの場所を PR と同じ決まりで開き（herdr の、元の clone の子の作業場）、使用率でアカウントを
1 つ選び（会社の形の役か受け持ちが account で名指したアカウントは、使えれば先に選ぶ）、その作業場で Claude Code の裏の会話（claude --bg）を、名前と頼みのファイルを読ませる最初の文を付けて起動し、同じペインで
attach して画面を出す（会社の形の設計 9.1）。最初の文の後ろに、呼んだ会話への連絡の道（同じアカウントなら SendMessage、違えば画面に
書いて止まる）を書き足す。作業の終わりは待たない。作業場の git の設定 company.<名前> に、部署の属性（役・アカウント・会話の名前と
id・頼み元〔呼んだ会話〕）を書く（会社の形の設計 4.2）。--clean は、会話が終わりブランチがメインブランチに入った部署を、claude rm と一緒に片付ける。

--tree は、herdr に開いている会社（リポジトリ）ごとに、会社の情報（名前と受ける仕事）と部署（ブランチ・役・アカウント・頼み元・herdr の
状態）を出す（_company。--json で JSON）。--sync は、部署の属性から herdr のペインの名前・表示名・札を付け直す（何度打っても同じ。会社の形が替わったときは、ターンの終わりの
フック shape_hook.py が、その会社の分を同じ中身で付け直す）。
どちらも dispatch の設定が無くても動く（有れば、会話のアカウントと、設定の置き場の会社の情報を見る）。

使い方: python3 dispatch.py [--config <パス>] [--repo OWNER/NAME] [--pr N ... | --issue N] [--no-second] [--dry-run | --clean [--apply]]
        python3 dispatch.py --task <名前> --branch <ブランチ> --brief <頼みのファイル> [--repo OWNER/NAME か代表の clone] [--base <ブランチ>]
                            [--from-name <呼んだ会話の名前>] [--from-account <アカウントの名>] [--role <役>] [--dry-run]
        python3 dispatch.py --tree [--json] | --sync [--dry-run]
        python3 dispatch.py --ask <会社/役 か部署の名前か会社の名前> (--text <文> | --brief <ファイル>) [--task <名前> --branch <ブランチ>] [--dry-run]
        python3 dispatch.py --deliver <要約のファイル> [--for <受付> | --again] [--dry-run]
        python3 dispatch.py --rest（部署か窓口の場所から。今は会話を空にしてよい区切りと印す）
        python3 dispatch.py --compact [焦点]（部署か窓口の場所から。同じ仕事の前の部分が済んだので、ここで compact してよい区切りと印す）
        python3 dispatch.py --done（畳む部署の場所から。納品してメインブランチに入れ終えたので、ターンの終わりに会話を止めて部屋を片付けてよいと印す）
        python3 dispatch.py --retire <部署>（畳む部署の会話を止めてから、--clean と同じ決まりで片付ける）
        python3 dispatch.py --land <部署> [--repo OWNER/NAME か代表の clone] [--dry-run]
        python3 dispatch.py [--repo 代表の clone] --queue-run -- <コマンド> [<引数> ...]（外のツールが --land と同じ列に並んで走る。queuerun.py）
        python3 dispatch.py --reorg [--name <新しい名前>] [--role <役>] [--persistent | --ephemeral] [--boss <頼み元> [--boss-account <名>]] [--dry-run]
        python3 dispatch.py --desk [<名前>] [--role <役>] [--dry-run]
        python3 dispatch.py --handover <前の名前> [--dry-run]（後継の部署の場所から、そのターンの中で）
        python3 dispatch.py --init --repo OWNER/NAME --source <代表の clone> | --init-company [--local] [--repo <代表の clone>]

部署の回（--task・--ask・--land・--tree）は、設定の [[repos]] が無くても、代表の clone の場所（--repo のパスか打った場所）から
会社を決める（_department_repo）。[[repos]] は PR を開く回と、gh_user・copy_files を会社の形と別に決めたいときだけ要る。

--ask と --deliver（依頼と納品。会社の形の設計 4.5）の流れは orders.py が持つ。
--reorg と --desk（部署と窓口の属性の付け替え）の流れは reorg.py が持つ。
--handover（部署か窓口の受け持ちを同じ会社のほかの部署へ移す）の流れは handover.py が持つ。
--retire（畳む部署の会話を止めて片付ける）の流れは retire.py が持つ。
"""

import argparse
import collections
import concurrent.futures
import json
import os
import pathlib
import re
import sys
import time
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ports import chat, term  # noqa: E402
import wiring  # noqa: E402
from wiring import Ports  # noqa: E402,F401  口の束は wiring が組み立てる（試験と shape_hook は dispatch.Ports で取る）
import config  # noqa: E402
import filex  # noqa: E402
import ghx  # noqa: E402
import gitx  # noqa: E402
import installed  # noqa: E402
import jsonio  # noqa: E402
import calls  # noqa: E402
import landing  # noqa: E402
import landorder  # noqa: E402
import queuerun  # noqa: E402
import move  # noqa: E402
import retire  # noqa: E402
import handover  # noqa: E402
import reorg  # noqa: E402
import limits  # noqa: E402
import rentx  # noqa: E402
import rentfx  # noqa: E402
import tierx  # noqa: E402
from nodes import accounts, assign, clean, cost, deliver, fresh, launch, provision, prs, report, role, sessions, sync, tools, tree, turn, wake  # noqa: E402
import orders  # noqa: E402
import starts  # noqa: E402
import todo  # noqa: E402
import reminds  # noqa: E402

# Windows の既定の標準入出力は cp1252 などで、日本語を書くと UnicodeEncodeError で落ちる。UTF-8 に直す
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

DEFAULT_ROLE = role.DEFAULT   # --role を渡さず、会社の形に default_role も無いときの役


def _key(repo, number):
    return f"{repo.repo}#{number}"


def _sent_record(v):
    """dispatch-sent.json の 1 件を {at, head, listed} にする。前の版は時刻だけを書いた。listed は一覧の回で送った印（via が listing）。
    印の無い控え（--pr・--issue で送った物と、印を書く前の版の物）は、出どころを言い切れないので listed を偽にする。"""
    if isinstance(v, (int, float)):
        return {"at": v, "head": None, "listed": False}
    return {"at": (v or {}).get("at"), "head": (v or {}).get("head"), "listed": (v or {}).get("via") == "listing"}


def _pane_at(h, path):
    """作業フォルダがちょうど path で、herdr が Claude Code の会話を見ているペインの ID（無ければ None）。読めなければ HerdrError。"""
    return next((p["pane_id"] for p in h.panes()
                 if p.get("agent") == chat.AGENT and os.path.realpath(p.get("cwd") or "") == os.path.realpath(path)), None)


def _end_conversation(ports, path):
    """その場所の会話を終える（turn.close_session）。(closed か close_failed, 訳)。herdr に会話のペインが無ければ
    （会話が herdr の外の端末に居るなど）終えない。"""
    try:
        pane = _pane_at(ports.term, path)
    except term.Error as e:
        return "close_failed", f"{term.NAME} のペインを読めない（{e}）"
    if not pane:
        return "close_failed", f"その場所に {term.NAME} の会話のペインが無い（{term.NAME} の外の会話は終えない）"
    got = turn.close_session(pane, ports.term)
    return got, None if got == "closed" else f"ペイン {pane} の会話が /exit で終わらなかった"


def _earlier_report(cfg, ports, r, notes):
    """その PR の場所で前に開いた会話（全アカウントの、その場所の会話の記録。送り直しで終えた会話も、持ち主が閉じた会話も）のうち、
    報告の在るいちばん新しい物（/catchup だけで終えた会話は飛ばす）の報告を、場所の git の置き場（git が追わず、作業ツリーを汚さない。
    worktree を消せば一緒に消える）の works-dispatch/reports に残し（turn.keep_report）、そのパスを返す。前の会話が無いか、どの会話にも
    報告が無ければ None。"""
    talks = sorted(((at, os.path.join(chat.talk_dir(acc.config_dir, r["path"], ports.account_env), name), acc.config_dir)
                    for acc in cfg.accounts for at, name in chat.talks(acc.config_dir, r["path"], ports.account_env) or ()),
                   reverse=True)
    if not talks:
        return None
    try:
        place = ports.git.git_dir(r["path"])
        if not place:
            raise OSError("場所の git の置き場が読めない")
        for _, talk, config_dir in talks:
            kept = turn.keep_report(talk, os.path.join(place, "works-dispatch", "reports"),
                                    ports.catchup_command(config_dir) or ports.catchup_command(r["account"].get("config_dir")))
            if kept:
                return kept
        return None
    except (OSError, gitx.GitError) as e:
        notes.append(f"{_name(r)}: 前に開いた会話の報告を残せなかった（{e}）。新しい会話には渡さない")
        return None


def _at(items, path):
    """会話の並びのうち、その場所かその下を作業フォルダにする物。"""
    return [s for s in items if s.get("cwd") and filex.inside(s["cwd"], path)]


def _local_work(ports, path, branch, rec):
    """手元にしか無い作業が有るか。HEAD が前に送った時の head のままなら、remote に見えない commit は作者の force-push で消えた物
    （手元で積んだ物でない）。"""
    return ports.stashed(path, branch) if rec["head"] and ports.head_sha(path) == rec["head"] else ports.unpushed(path)


def _trust_note(ports, account, source, path, accounts_):
    """元の clone の信頼の印を作業場に付ける。付けば None、付かなければ注記の文。"""
    try:
        trusted = ports.trust(account, source, path, accounts_)
    except OSError as e:
        trusted = f"書けない（{e}）"
    if trusted in ("inherited", "already"):
        return None
    return (f"どのアカウントも元の clone を信頼していないので、{chat.NAME} がフォルダの信頼の確認を出す" if trusted == "source_untrusted"
            else f"信頼の印を付けられない（{trusted}）。{chat.NAME} がフォルダの信頼の確認を出す")


def _candidates(repo, ports, found, cwds, changed):
    """閉じた PR の場所の片付けの候補（clean.candidates）。"""
    return clean.candidates(found, lambda b: ports.pr_for_branch(repo, b), cwds, ports.is_clean, ports.stashed, ports.head_sha,
                            source=repo.source, changed=changed, is_ancestor=ports.is_ancestor)


def _overview(accounts_, ports):
    """アカウントごとの選び方（自動か名指しだけか・名指しで同時に立てる数）とモデルの別名の読み替え先。アカウントが 1 つで、named_only も
    max_open も読み替え先も無ければ空。"""
    shown = accounts.overview(accounts_, ports.account_env)
    return shown if len(shown) > 1 or any(x["named_only"] or x["max_open"] != 1 or x["models"] for x in shown) else []


def _cost_note(est, limit_percent):
    if est is None:
        return ("1 件あたりの使用率をまだ測っていないので、選べるアカウントに 1 件ずつ順に配った"
                "（今回の /catchup の前後で測って覚え、次からはアカウントの残りに合わせて入れる）")
    parts = [f"{label} {round(est[w], 2)}%" for w, label in (("seven_day", "週"), ("five_hour", "5 時間")) if w in est]
    return (f"1 件あたりの使用率の見積もり（{est['runs']} 回の測りの中央値）: {'・'.join(parts)}。"
            f"各アカウントに、使用率が {limit_percent}% に届かない件数まで入れた")


def _branch_places(places):
    """worktree の並びから {ブランチ: 場所のパス}（linked worktree だけ）。"""
    return {p["branch"]: p["path"] for p in places if p.get("linked") and p.get("branch") and not p.get("prunable")}


def _department_places(places, ports, source):
    """worktree の並びのうち、部署の作業場（属性 company.role を持つ linked worktree。元の clone は除く）の {ブランチ: 部署の名前}。"""
    out = {}
    for p in places:
        if not (p.get("linked") and p.get("branch")) or os.path.realpath(p["path"]) == os.path.realpath(source):
            continue
        attrs = ports.attrs(p["path"])
        if attrs.get("role"):
            out[p["branch"]] = attrs.get("name") or p["branch"]
    return out


def _issue_item(repo, number, ports, notes):
    """--issue の 1 件を、prs の 1 件と同じ形（kind が issue）にする。ブランチは issue に結んだブランチ（2 本以上なら最初の 1 本）。
    結んだブランチが見えなければ、issue を閉じる開いた PR のブランチ（ブランチから PR を作ると、GitHub はブランチの結びつきを PR に置き換える）。
    どちらも無ければ head は None で、provision の前に GitHub にブランチを作って結ぶ。"""
    info = ports.issue_info(repo, number)
    if info.get("state") not in (None, "OPEN"):
        return {"number": number, "kind": "issue", "title": info["title"], "head": None, "url": info.get("url"), "closed": True}
    branches = ports.issue_branches(repo, number)
    head = branches[0] if branches else None
    if branches[1:]:
        notes.append(f"issue #{number}: 結んだブランチがほかにも有る（使ったのは {head}）: {', '.join(branches[1:])}")
    for n in ([] if head else info["prs"]):
        pr = ports.pr_info(repo, n)
        if pr.get("state") == "OPEN" and not pr.get("fork"):
            head = pr["head"]
            notes.append(f"issue #{number}: 結んだブランチは見えないので、issue を閉じる PR #{n} のブランチ {head} を使う")
            break
    return {"number": number, "kind": "issue", "title": info["title"], "head": head, "url": info.get("url")}


def _split_queue_run(argv):
    """--queue-run の後ろ（-- から先）は走らせるコマンドなので、argparse に渡す前に切り出す。(dispatch の引数, コマンドか None)。"""
    if "--queue-run" not in argv:
        return argv, None
    i = argv.index("--queue-run")
    rest = argv[i + 1:]
    return argv[:i + 1], rest[1:] if rest[:1] == ["--"] else []


def _queue_run_others(argv):
    """--queue-run の前に書いた、--repo と --config のほかの引数（--queue-run はほかの入口と混ぜると、先に読む入口に黙って飲まれるので止める）。"""
    head, out, i = argv[:-1], [], 0
    while i < len(head):
        if head[i] in ("--repo", "--config"):
            i += 2
            continue
        if not head[i].startswith(("--repo=", "--config=")):
            out.append(head[i])
        i += 1
    return out


def main(argv=None, ports=None):
    argv, command = _split_queue_run(sys.argv[1:] if argv is None else list(argv))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--dry-run", action="store_true", help="することの案までを決めて報告し、何も起動しない（--land では決まりと見立てだけを出し、push しない）")
    ap.add_argument("--pr", type=int, action="append", metavar="N",
                    help="自分の番の一覧を使わず、この番号の PR だけを開く（繰り返して複数）")
    ap.add_argument("--issue", type=int, metavar="N",
                    help="この issue に結んだブランチの場所を開き（無ければブランチを作って結ぶ）、/catchup N まで送って止める")
    ap.add_argument("--no-second", action="store_true", help="2 ターン目の文を送らず、/catchup だけで止める")
    ap.add_argument("--init", action="store_true", help="設定の下書きを書く（--repo と --source が要る。有れば上書きしない）")
    ap.add_argument("--source", help="--init と一緒に: そのリポジトリの代表の clone")
    ap.add_argument("--init-company", action="store_true",
                    help="会社の形（.claude/company.toml）の下書きを書く（--repo に代表の clone のパス。省けば今いる場所。有れば上書きしない）")
    ap.add_argument("--local", action="store_true",
                    help="--init-company と一緒に: リポジトリの中でなく、設定の置き場の companies/ に書く（commit しない側）")
    ap.add_argument("--check", action="store_true", help="始める前の確かめだけを走らせ、足りない物と直し方を出す")
    ap.add_argument("--clean", action="store_true", help="元の clone の worktree のうち消してよいものを並べる")
    ap.add_argument("--apply", action="store_true", help="--clean と一緒に: 並べたものを本当に消す")
    ap.add_argument("--task", metavar="名前", help="部署を 1 つ起動する。名前は会話・ペイン・作業場の名前になる（--branch と --brief が要る）")
    ap.add_argument("--branch", help="--task と一緒に: 部署のブランチ（在れば開き、無ければ作る）")
    ap.add_argument("--brief", help="--task と一緒に: 部署に最初に読ませる頼みのファイル")
    ap.add_argument("--base", help="--task と一緒に: ブランチを新しく作るときの元にする origin のブランチ（省けば既定のブランチ）")
    ap.add_argument("--from-name", help=f"--task か --ask と一緒に: 呼んだ会話の名前（{chat.NAME} の中から走らせれば自分で探す）")
    ap.add_argument("--from-account", help="--task か --ask と一緒に: 呼んだ会話のアカウントの名（同上）")
    ap.add_argument("--role", help=f"--task と一緒に: 部署の役（省けば会社の形の default_role、無ければ {DEFAULT_ROLE}）")
    ap.add_argument("--persistent", action="store_true",
                    help="--task と一緒に: always の部署にする（--clean で畳まず、次の頼みを同じ部署で受ける。省けば畳む部署）")
    ap.add_argument("--tree", action="store_true", help=f"{term.NAME} に開いている会社ごとに、会社の情報と部署の様子を出す")
    ap.add_argument("--json", action="store_true", help="--tree か --todo か --rent-effect と一緒に: JSON で出す")
    ap.add_argument("--todo", metavar="受付", nargs="?", const="",
                    help="受付箱の台帳から頼みの木（頼み → 回した先・出した頼み、と残った疑問の続き）を作って出す。済んだブランチは出さない"
                         "（受付を渡せばその頼みから下を全部。誰のターンかは出さない。作った物は保存せず、開くたびに作り直す）")
    ap.add_argument("--all", action="store_true", help="--todo と一緒に: 済んだブランチも出す")
    ap.add_argument("--state", metavar="状態", help="--todo と一緒に: その状態の頼みだけを、木にせず更新の古い順に出す（カンマで区切って幾つでも。"
                    "queued・working・waiting・done・dropped・failed か、順番待ち・動いている・答え待ち・済・取り下げ・届かず）")
    ap.add_argument("--to", metavar="宛先", help="--todo と一緒に: 宛先がその部署の名前・会社の名前・「会社/名前」の頼みだけを、木にせず"
                    "更新の古い順に出す（--state を省けば開いている物だけ、--all で全部の状態）")
    ap.add_argument("--html", metavar="ファイル", help="--todo と一緒に: 1 枚の HTML のページに書く（--all も受付も無ければ済んだブランチを初めは隠し、ページの中で出せる）")
    ap.add_argument("--sync", action="store_true", help=f"部署の属性から、{term.NAME} のペインの名前・表示名・札を付け直す")
    ap.add_argument("--ask", metavar="宛先", help="「会社/役」か部署の名前の部署か、会社の名前だけならその会社の窓口に頼む（--text か --brief。部署が無ければ --task と --branch で立てる）")
    ap.add_argument("--text", help="--ask か --note と一緒に: 頼みか足しの文（長い物は --brief のファイルで渡す）")
    ap.add_argument("--forward", action="store_true", help="--ask と一緒に: 部署か窓口の場所から、受けている頼みをこの頼みで回したとして"
                    "閉じる（回した先は台帳にだけ書き、頼み元の会話は起動しない。結果と問いは今までどおり --deliver で返す）")
    ap.add_argument("--take", metavar="受付", help="順番待ちの 1 件を、積んだ順を飛ばして取り出す。部署の場所から打てばその部署が今受け、"
                    "--ask <宛先>（と --task・--branch）を添えれば、受付番号と頼み元をそのままにほかの部署へ頼み直す（--text は元の本文の前に置く添え書き）")
    ap.add_argument("--move", metavar="部署か窓口", help="立っている部署か本社の窓口の会話を、ほかのアカウントで起動し直す"
                    "（前の会話を止めてから。--account で名指さなければ、使用率の順で空いている物）")
    ap.add_argument("--account", help="--move と一緒に: 移る先のアカウントの名（今のアカウントを名指せば、同じアカウントのまま"
                    "会社の形の今の起動の設定で起動し直す）")
    ap.add_argument("--if-limited", action="store_true",
                    help="--move と一緒に: 今のアカウントの使用率が上限に達しているときだけ移す（上限で止まったときのフックが付ける）")
    ap.add_argument("--if-changed", action="store_true",
                    help="--move と一緒に: new の部署を、会社の形の model・effort が起動したときと違うときだけ起動し直す"
                    "（今のアカウントに空きがあれば同じアカウントで。頼みを渡す前の待ち受けが付ける）")
    ap.add_argument("--withdraw", metavar="受付", help="順番待ちの 1 件を、渡さずに取り下げる（台帳に残す）。順番待ちに無い受付なら、台帳で開いていると出る頼みを、"
                    "取り下げの行を足して閉じる（受けた部署がまだ受けていれば止まる）")
    ap.add_argument("--nudge", metavar="部署", help="順番待ちが渡らずに止まった部署を動かす（会話が落ちていれば attach で戻し、"
                    "待ち受けが居ないか渡さずに待っていれば、手の空いた窓でプラグインを読み直させてから 1 行打ってターンを回す。台帳に残す）")
    ap.add_argument("--first", metavar="受付", help="順番待ちの 1 件を、その順番待ちの先頭に回す（急ぐ物を先にする。台帳に残す）")
    ap.add_argument("--note", metavar="受付", help="受付の頼みに、変更・足し・取り下げを届ける（--text か --brief。部署がターンの途中でも、"
                    "台帳の知らせでターンの終わりに待ち受けが渡す。順番待ちの頼みなら、渡すときの 1 行に添える）")
    ap.add_argument("--call", nargs=2, metavar=("会社/役", "ツール"),
                    help="役の機械窓口のツールを呼ぶ（会社の形の [[roles.tools]]。片づかなければ同じ役か回す役の AI の部署に回す）")
    ap.add_argument("--input", help="--call と一緒に: ツールへの入力（JSON の字か @ファイル。省けば {}）")
    ap.add_argument("--after-task", metavar="部署の場所", help="部署を立てた後の合図: その部署の会社の形の [[task.after]] のツールを順に呼ぶ"
                    "（部署を新しく立てるたびに裏で打つ。手で打ってもよい）")
    ap.add_argument("--start", metavar="受け持ち", help="会社の形の起動方法（[skills.start]）の有る受け持ちを今起動する（名前か「会社/名前」。"
                    "納品は起動方法の report_to に返る）")
    ap.add_argument("--due", action="store_true", help=f"{term.NAME} に開いている会社の、周期（[skills.start] の every）の来た受け持ちを全部起動し、"
                    "見る時の来たリマインダーを担当者に知らせる（--ask と --deliver が通るたびに裏で打つ。手で打ってもよい）")
    ap.add_argument("--remind", metavar="何を見るか", help="部署か窓口の場所から、後で見ることを台帳にリマインダーとして残す（--on か --after を"
                    "付ける。見る時が来たら --due がこの会話に知らせ、--todo にも出る）")
    ap.add_argument("--on", metavar="日時", help="--remind と一緒に: 見る日（手元の時刻の YYYY-MM-DD か YYYY-MM-DDTHH:MM）。"
                    "条件を文でしか書けない待ちは、見直す日をここに付ける")
    ap.add_argument("--after", metavar="受付", action="append", help="--remind と一緒に: この頼みが閉じたら見る（何度でも付けられ、"
                    "--on と合わせて先に来た方で知らせる）")
    ap.add_argument("--remind-done", metavar="受付", help="見たリマインダーを閉じる")
    ap.add_argument("--deliver", metavar="要約のファイル", help="部署の場所から、要約を頼み元へ返す（項目が足りなければ送らない。- は標準入力）")
    ap.add_argument("--for", dest="for_ask", metavar="受付", help="--deliver と一緒に: --ask … --forward で回して閉じた頼み（回した元か"
                    "回した先の受付）か、cause 付きの --ask で回した子の頼み（子かその元の受付）の、元の頼み元へ返す。--wait --park で保留にした"
                    "頼みの受付なら、その頼みを頼み元へ返して閉じる（どれも今受けている頼みは閉じない）")
    ap.add_argument("--again", action="store_true", help="--deliver と一緒に: 今受けている頼みを納品した後に、同じ頼みの続き（納品の後に"
                    "出た、判断の要ること・直し）をもう一度返す（無ければ、納品済みの頼みへの --deliver は止まる）")
    ap.add_argument("--wait", metavar="訳", help="部署の場所から、今の頼みを人の答え待ちと印す（止まる前のフックが納品を促さない。"
                    "人がその会話に打つか、納品すると外れる）")
    ap.add_argument("--park", action="store_true", help="--wait と一緒に: 答え待ちの頼みを保留にして今の頼みを空ける（順番待ちの次の頼みを"
                    "受けられる。保留の頼みは台帳で答え待ちのまま閉じず、答えは --deliver --for <受付> で返す）")
    ap.add_argument("--handover", metavar="前の名前", help="後継の部署の場所から、そのターンの中で: 同じ会社の部署か窓口（前の名前）の宛先・"
                    "未読の知らせ・順番待ち・保留の頼みをこの部署へ移し、前の場所の属性を消す（受付番号と頼み元は替えない。--dry-run で移す物を出す）")
    ap.add_argument("--rest", action="store_true", help="部署か窓口の場所から、今は会話を空にしてよい区切りと印す（このターンの終わりに、"
                    "入力フィールドが空なら機械が窓に /clear を打つ。人がその会話に打つと外れる）")
    ap.add_argument("--compact", nargs="?", const="", metavar="焦点", help="部署か窓口の場所から、同じ仕事の前の部分が済んだので、ここで"
                    "compact してよい区切りと印す（このターンの終わりに、文脈が大きく入力フィールドが空なら、機械が窓に /compact <焦点> を打ち、"
                    "済んだら続きをさせる 1 行を会話に渡す。納品の前でも印せる。人がその会話に打つと外れる）")
    ap.add_argument("--done", action="store_true", help="畳む部署の場所から、納品してメインブランチに入れ終えたので片付けてよいと印す（このターンの"
                    "終わりに、機械が会話を止めて部屋を --clean と同じ決まりで片付ける。人がその会話に打つと外れる）")
    ap.add_argument("--retire", metavar="部署", help="畳む部署の会話を止めてから、部屋を --clean と同じ決まりで片付ける（--done の"
                    "ターンの終わりに機械が打つ。段取りが残った部屋を止めると決めたときも打つ）")
    ap.add_argument("--land", metavar="部署", help="部署の成果を、会社の形の [land] の決まりでメインブランチに入れる（ゲートを待ち、緑なら fast-forward）")
    ap.add_argument("--land-order", nargs="*", metavar="部署",
                    help="メインブランチへ入れる列（会社の形の [land] の queue）を出す。部署の名前かブランチを並べれば、その順に先に入れる"
                         "（判断役が決める。- だけなら指定を消して申し出た順に戻す。決め手は docs/land.md の「入れる順を決める」）")
    ap.add_argument("--queue-run", action="store_true",
                    help="-- の後ろのコマンドを、メインブランチへ入れる列（会社の形の [land] の queue）の先頭を取ってから走らせ、"
                         "終わったら次に渡す（works-dispatch の外のツールが --land と同じ列に並ぶ口。ほかの引数は --queue-run の前に書く。"
                         "終了の値はコマンドの物で、列に入れなければ 125。docs/land.md の「外のツールが列に並ぶ」）")
    ap.add_argument("--rent-effect", action="store_true",
                    help="借りるか買うかの部品（rent-or-buy）が効いたかの集計の点を出す（--since・--until の期間の会話の記録で、部品の"
                         "無かった世界との差を keepalive・compact の得失に分けて出し、閉じた待ちの結果を部品の判断の記録に足す。定義は docs/rent-effect.md）")
    ap.add_argument("--since", metavar="T", help="--rent-effect と一緒に: 期間の始まり（YYYY-MM-DDTHH:MM:SSZ。省けば 7 日前）")
    ap.add_argument("--until", metavar="T", help="--rent-effect と一緒に: 期間の終わり（含まない。省けば今）")
    ap.add_argument("--keep-removal", action="store_true",
                    help="--land と一緒に: 部署がメインブランチを知った後にほかの部署が入れた行を、このブランチが消していても入れる（わざと消すとき）")
    ap.add_argument("--reorg", action="store_true",
                    help=f"今いる部署の名前・役・always かどうか・頼み元を付け替え、{term.NAME} の表示を付け直す（--name・--role・--persistent か --ephemeral・--boss）")
    ap.add_argument("--name", help="--reorg と一緒に: 部署の新しい名前（前の名前は覚え、--land・--ask は前の名前でも引く）")
    ap.add_argument("--ephemeral", action="store_true",
                    help="--reorg と一緒に: 畳む部署にする（always をやめる）")
    ap.add_argument("--boss", help="--reorg と一緒に: 新しい頼み元（納品を返す会話）の名前")
    ap.add_argument("--boss-account", help="--reorg と一緒に: 新しい頼み元のアカウントの名（省けば名前だけで引く）")
    ap.add_argument("--desk", metavar="名前", nargs="?", const="",
                    help="本社で持ち主と話す今の会話を窓口として名付ける（役は --role、会社の形の desk_role、今の役、窓口 の順。"
                         f"名前を省けば今の名前か役の名前）。{term.NAME} の表示も付け直す")
    a = ap.parse_args(argv)
    ports = ports or Ports()
    if a.handover is not None:
        flag = {x.dest: x.option_strings[0] for x in ap._actions if x.option_strings}
        with_ = [flag.get(k, k) for k, v in vars(a).items() if k not in ("handover", "dry_run", "config") and v != ap.get_default(k)]
        if with_:
            print(f"止めた: --handover は {'・'.join(with_)} と一緒に使えない（引き継ぎだけを打ち、済んでからほかのコマンドを打つ）")
            return 2
    if a.queue_run:
        return _queue_run(a, argv, command, ports)
    if (a.since or a.until) and not a.rent_effect:
        print("止めた: --since と --until は --rent-effect と一緒にだけ使う")
        return 2
    if a.rent_effect:
        return rentfx.main(a.since, a.until, a.json)
    if a.init:
        return _init(a, ports)
    if a.input is not None and a.call is None:
        print("止めた: --input は --call と一緒にだけ使う")
        return 2
    if (a.on is not None or a.after) and a.remind is None:
        print("止めた: --on と --after は --remind と一緒にだけ使う")
        return 2
    if a.remind is not None:
        return reminds.put(a, ports, os.getcwd())
    if a.remind_done is not None:
        return reminds.close(a, ports, os.getcwd())
    if a.call is not None:
        return calls.call(a, ports, os.getcwd(), _task)
    if a.after_task is not None:
        return calls.after_task(a, ports, _task)
    if a.start is not None or a.due:
        if a.start is not None and a.due:
            print("止めた: --start と --due は一緒に使えない（--start は 1 つを今、--due は周期の来た物を全部）")
            return 2
        return starts.start_now(a, ports, os.getcwd(), _task) if a.start is not None else starts.due_all(a, ports, _task)
    if a.move is not None:
        return move.move(a, ports, os.getcwd(), _task)
    if (a.account or a.if_limited or a.if_changed) and a.move is None:
        print("止めた: --account・--if-limited・--if-changed は --move と一緒にだけ使う")
        return 2
    if a.forward and (a.ask is None or a.take is not None):
        print("止めた: --forward は --ask と一緒にだけ使う（--take --ask は受付番号と頼み元をそのまま回すので要らない）")
        return 2
    if a.park and a.wait is None:
        print("止めた: --park は --wait と一緒にだけ使う")
        return 2
    if a.handover is not None:
        return handover.handover(a, ports, ports.cwd())
    if a.for_ask is not None and a.deliver is None:
        print("止めた: --for は --deliver と一緒にだけ使う")
        return 2
    if a.again and a.deliver is None:
        print("止めた: --again は --deliver と一緒にだけ使う")
        return 2
    if a.again and a.for_ask is not None:
        print("止めた: --again と --for は一緒に使わない（--for の返しは今の頼みを閉じないので、--again は要らない）")
        return 2
    if (a.all or a.html or a.state or a.to) and a.todo is None:
        print("止めた: --all・--html・--state・--to は --todo と一緒にだけ使う")
        return 2
    if a.todo is not None:
        return todo.todo(a, ports, os.getcwd())
    if a.take is not None:
        return orders.take(a, ports, os.getcwd(), _task)
    if a.withdraw is not None:
        return orders.withdraw(a, ports, os.getcwd())
    if a.first is not None:
        return orders.first(a, ports, os.getcwd())
    if a.nudge is not None:
        return orders.nudge(a, ports, os.getcwd())
    if a.note is not None:
        return orders.note(a, ports, os.getcwd())
    if a.ask is not None:
        cwd = os.getcwd()
        rc = orders.ask(a, ports, cwd, _task)
        if rc == 0 and not a.dry_run:
            starts.due_later(a, ports, cwd, "頼み")
        return rc
    # 場所に結び付く口は、打った会話の部署の場所で読む（会話がシェルでほかの部署の場所へ移って打っても。orders.own_place）
    if a.deliver is not None or a.wait is not None or a.rest or a.compact is not None or a.done:
        cwd, moved = orders.own_place(ports, os.getcwd())
        if moved:
            print(moved)
    if a.deliver is not None:
        rc = orders.deliver_summary(a, ports, cwd)
        if rc == 0 and not a.dry_run:
            starts.due_later(a, ports, cwd, "納品")
        return rc
    if a.wait is not None:
        return orders.wait_for_input(a, ports, cwd)
    if a.rest:
        return orders.rest_here(a, ports, cwd)
    if a.compact is not None:
        return orders.compact_here(a, ports, cwd)
    if a.done:
        return orders.finish_here(a, ports, cwd)
    if a.retire is not None:
        return retire.retire(a, ports, os.getcwd(), _department_rows, DEPT_REASONS)
    if a.text is not None:
        print("止めた: --text は --ask と一緒にだけ使う")
        return 2
    if a.reorg or a.desk is not None:
        if a.reorg and a.desk is not None:
            print("止めた: --reorg と --desk は一緒に使えない（部署は --reorg、本社の窓口は --desk）")
            return 2
        return reorg.reorg(a, ports, ports.cwd()) if a.reorg else reorg.desk(a, ports, ports.cwd())
    if a.keep_removal and a.land is None:
        print("止めた: --keep-removal は --land と一緒にだけ使う")
        return 2
    reorg_args = [n for n, v in (("--name", a.name), ("--ephemeral", a.ephemeral), ("--boss", a.boss),
                                 ("--boss-account", a.boss_account)) if v]
    if reorg_args:
        print(f"止めた: {', '.join(reorg_args)} は --reorg と一緒にだけ使う")
        return 2
    if a.tree or a.sync or a.json:
        return _company(a, ports)

    if a.local and not a.init_company:
        print("止めた: --local は --init-company と一緒にだけ使う")
        return 2
    if a.init_company:
        return _init_company(a, ports, ports.cwd())
    # 部署の回（--task・--land）は、[[repos]] が無くても、代表の clone の場所から会社を決める（_department_repo）
    # --check は、[[repos]] が無ければ部署の回の前提だけを確かめる（_check）
    # --clean も部署の回と同じに決める（設定が無くても、--repo のパスか今いる場所の代表の clone の部署を片付ける）
    department = a.task is not None or a.land is not None or a.land_order is not None or a.clean
    try:
        cfg = config.load(a.config, os.environ, missing_ok=department or a.check)
        clone = _clone_of(cfg, a.repo, ports) if a.check and cfg.repos else None
        repo = (_department_repo(cfg, a.repo, ports, ports.cwd()) if department else
                None if a.check and (not cfg.repos or clone) else config.pick_repo(cfg, a.repo))
    except config.ConfigError as e:
        print(f"止めた: {e}")
        return 2
    if a.apply and not a.clean:
        print("止めた: --apply は --clean と一緒にだけ使う")
        return 2
    if a.issue is not None and a.pr:
        print("止めた: --issue と --pr は一緒に使えない（1 回に 1 つの入口）")
        return 2
    task_args = [n for n, v in (("--branch", a.branch), ("--brief", a.brief), ("--base", a.base), ("--from-name", a.from_name),
                                ("--from-account", a.from_account), ("--role", a.role), ("--persistent", a.persistent)) if v]
    if a.task is None and task_args:
        print(f"止めた: {', '.join(task_args)} は --task と一緒にだけ使う")
        return 2
    if a.land_order is not None:
        if a.land is not None or a.task is not None or a.pr or a.issue is not None or a.clean or a.check:
            print("止めた: --land-order はほかの入口（--land・--task・--pr・--issue・--clean・--check）と一緒に使えない")
            return 2
        return landorder.main(repo, a.land_order, ports, a.config)
    if a.land is not None:
        if a.task is not None or a.pr or a.issue is not None or a.clean or a.check or a.no_second:
            print("止めた: --land はほかの入口（--task・--pr・--issue・--clean・--check・--no-second）と一緒に使えない")
            return 2
        return landing.main(cfg, repo, a.land, ports, _department_rows, DEPT_REASONS, a.config, dry_run=a.dry_run,
                            keep_removal=a.keep_removal,
                            after=lambda rules, source, attrs, members=(): calls.fire(rules, source, ports, a, _task, attrs, members))
    if a.task is not None:
        if a.pr or a.issue is not None or a.clean or a.check or a.no_second:
            print("止めた: --task は --pr・--issue・--clean・--check・--no-second と一緒に使えない（1 回に 1 つの入口）")
            return 2
        if not (a.task.strip() and a.branch and a.brief):
            print("止めた: --task には、名前と --branch <ブランチ> と --brief <頼みのファイル> が要る")
            return 2
        return _task(cfg, repo, a, ports)
    if a.clean:
        return _clean(cfg, repo, a.apply, ports)
    if a.check:
        if clone and clone not in cfg.repos:
            # 設定の [[repos]] に無い代表の clone のパス。部署の回は [[repos]] 無しで立つので、その clone の部署の前提を確かめる
            # （2026-10-19 に works-factory の会社で「設定の repos に無い」で止まり、要らない [[repos]] を手で書いた）
            return _check(cfg._replace(repos=(clone,)), ports, task=True,
                          lead=f"{clone.source} は設定の [[repos]] に無いので、部署の回（--task・--ask・--land）の前提だけを確かめた"
                               "（部署の回は [[repos]] が無くても立つ。PR を開く回も使うなら [[repos]] に足す）")
        return _check(cfg, ports)
    problems, notes = ports.preflight(cfg)
    notes = list(cfg.notes) + notes
    if problems:
        print("止めた（始める前の確かめで足りない物）:")
        print("\n".join(f"- {p}" for p in problems))
        return 2

    listing = a.issue is None and not a.pr   # 一覧で回す（送り直しと片付けもする）
    limited = set()   # 走査の上限に当たった PR（whose-turn の limited。一覧で回すときだけ読む）
    try:
        if a.issue is not None:
            my_prs = [_issue_item(repo, a.issue, ports, notes)]
        elif a.pr:
            my_prs = [ports.pr_info(repo, n) for n in a.pr]
        else:
            my_prs, limited = ports.fetch_prs(repo)
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
        found = ports.places(repo)
    except (prs.PrsError, chat.Error, ghx.GhError, term.Error) as e:
        print(f"止めた: {e}")
        return 1
    if my_prs and my_prs[0].get("closed"):
        # 閉じた issue にはブランチを作らない（作る前に止める）
        print("\n".join(report.lines([_held_row(my_prs[0], "issue_closed", {}, kind="issue")], {}, notes)))
        return 0
    if listing:
        # 部署の作業場（--task が立てた worktree。属性 company.role を持つ）は部署の会話の物なので、一覧の回の送り直し・自分の番でない会話を
        # 閉じる・閉じた PR の片付けのどれにも使わない（2026-10-29 に guided-resolver で、部署の出した PR が自分の番の一覧に入り、送り直しの
        # /exit が部署の会話の窓を attach から外した）。部署は --clean・--retire が畳む。自分の番でなくなった部署の PR は、会話を残して
        # 窓だけを閉じる（_step_back_departments）
        depts = _department_places(found, ports, repo.source)
        dept_places = [p for p in found if p.get("branch") in depts]
        dept_turn = {p["number"] for p in my_prs if p["head"] in depts}   # 自分の番に居る部署の PR（その窓は閉じない）
        for p in [p for p in my_prs if p["head"] in depts]:
            notes.append(f"#{p['number']}: 部署「{depts[p['head']]}」の作業場のブランチなので開かない（レビューの返しは --ask '{depts[p['head']]}' --text <頼み> で部署へ回す）")
        my_prs = [p for p in my_prs if p["head"] not in depts]
        found = [p for p in found if p.get("branch") not in depts]
    places = _branch_places(found)
    turn_numbers = {p["number"] for p in my_prs}   # 自分の番の PR（片付けで、自分の番でない PR の会話を見分ける）
    sess = sessions.collect(listed, ports.branch, ports.origin)
    # 自分が作者でレビュアーの付いていない PR は、開くが /catchup だけ送る（2 ターン目の文はレビューの進め方なので送らない）
    held, acts, catchup_only = [], {}, set()
    for p in my_prs:
        if p.get("role") == "implementer" and p.get("kind", "pr") == "pr":
            try:
                acts[p["number"]] = ports.activity(repo, p["number"])
            except ghx.GhError as e:
                notes.append(f"#{p['number']}: {e}（レビュアーの有無が分からないので 2 ターン目まで送る）")
            if p["number"] in acts and fresh.own_unreviewed(p, acts[p["number"]]):
                catchup_only.add(p["number"])
    # ブランチの場所の中で会話が開いている PR: 自分以外の動きが前に送った時より後に有れば、会話とペインを畳んで新しく立て直す
    try:
        sent, sent_ok = ports.load_sent(cfg.limits_dir), True
    except ValueError as e:
        sent, sent_ok = {}, False
        notes.append(f"{e}。前に送った時刻が無いものとして読み、控えは書き直さない（直すか消すと、次の回から使う）")
    refresh, verdicts = {}, {}
    quiet = set()
    keys = sessions.open_keys(sess)
    for p in (my_prs if listing else []):
        path = places.get(p["head"])
        inside = _at(sess, path) if path else []
        if not inside:
            # 会話が開いていない PR: 前に送った後に動きが無ければ、開き直さない（返事待ちの PR を、持ち主が会話を閉じただけで
            # もう一度レビューしない。持ち主 2026-10-15）。--pr で名指したときはここを通らない
            sent_rec = sent.get(_key(repo, p["number"]))
            if sent_rec is None or (repo.repo, p["head"]) in keys:
                continue
            try:
                act = acts.get(p["number"]) or ports.activity(repo, p["number"])
            except ghx.GhError as e:
                notes.append(f"#{p['number']}: {e}（前に送った後の動きが分からないので開く）")
                continue
            if fresh.quiet_since_sent(_sent_record(sent_rec), act):
                quiet.add(p["number"])
            continue
        try:
            act = acts.get(p["number"]) or ports.activity(repo, p["number"])
        except ghx.GhError as e:
            notes.append(f"#{p['number']}: {e}（送り直さない）")
            continue
        rec = _sent_record(sent.get(_key(repo, p["number"])))
        local = _local_work(ports, path, p["head"], rec)
        v = "busy" if len(inside) > 1 else fresh.decide(inside[0], act, rec["at"], ports.is_clean(path), local,
                                                        sent_head=rec["head"])
        if v == "refresh":
            refresh[p["number"]] = inside[0]
        else:
            verdicts[p["number"]] = v
    held += [_held_row(p, "no_news", places) for p in my_prs if p["number"] in quiet]
    my_prs = [p for p in my_prs if p["number"] not in quiet]
    staying = [x for x in sess if not any(x is r for r in refresh.values())]
    metered = [x.name for x in cfg.accounts if x.limits]
    if not a.dry_run:
        ports.refresh_limits(cfg, metered)
    before = ports.read_limits(cfg.limits_dir, metered)
    ranked = accounts.rank(cfg.accounts, before, cfg.limit_percent, ports.now(), accounts.count_running(listed),
                           margin_minutes=cfg.hours_margin_minutes)
    try:
        est = cost.estimate(ports.load_cost(cfg.limits_dir))
    except cost.CostError as e:
        est = None
        notes.append(f"{e}（まだ測っていないものとして割り振る）")
    the_plan = assign.plan(repo, my_prs, sessions.open_keys(staying), {s["cwd"] for s in staying if s["cwd"]}, ranked,
                           cfg.limit_percent, est, places)
    if any(r["outcome"] in ("assigned", "no_account") for r in the_plan):
        notes.append(_cost_note(est, cfg.limit_percent))

    results = dict(verdicts)
    assigned = [r for r in the_plan if r["outcome"] == "assigned"]
    # fork の PR（head が別のリポジトリ）は作業場を作らない。whose-turn の一覧は fork かを持たないので、開く PR だけ問う
    for r in assigned:
        if r["kind"] == "pr":
            r["sent_head"] = _sent_record(sent.get(_key(repo, r["number"])))["head"]
        if r["kind"] == "pr" and not a.pr:
            try:
                r["fork"] = bool(ports.pr_info(repo, r["number"]).get("fork"))
            except ghx.GhError as e:
                notes.append(f"#{r['number']}: fork の PR かを読めない（{e}）")
    if a.dry_run:
        for r in assigned:
            results[r["number"]] = "refresh" if r["number"] in refresh else provision.would(r, found)
            if r["kind"] == "issue" and not r["head"]:
                notes.append(f"issue #{r['number']}: 結んだブランチが無いので、既定のブランチからブランチを作って issue に結ぶ（gh issue develop）")
    else:
        ready = []
        for r in assigned:
            if r["number"] in refresh:
                # 古い会話を終え、その場所の作業場を畳む（checkout は残し、下の provision が同じ場所を開き直す）
                closed, why = _end_conversation(ports, r["path"])
                if closed != "closed":
                    results[r["number"]] = "close_failed"
                    notes.append(f"#{r['number']}: 送り直す前に古い会話を終えられなかった（{why}）")
                    continue
                rel = clean.release(repo.source, r["path"], ports.term)
                if rel["status"] == "close_failed":
                    results[r["number"]] = "close_failed"
                    notes.append(f"#{r['number']}: 古い作業場を閉じられなかった（{rel['detail']}）")
                    continue
            if r["kind"] == "issue" and not r["head"]:
                try:
                    linked = provision.link_branch(repo, r["number"], ports.default_branch(repo), ports.gh, ports.gh_env(repo))
                except (ghx.GhError, gitx.GitError) as e:
                    linked, why = [], str(e)
                else:
                    why = "結んだ後の読み戻しで、issue に結んだブランチが見えない"
                if not linked:
                    results[r["number"]] = "provision_failed"
                    notes.append(f"issue #{r['number']}: ブランチを結べなかった（{why}）")
                    continue
                r["head"] = linked[0]
            prov = provision.prepare(r, repo, ports.term, ports.git)
            name = _name(r)
            if prov["detail"]:
                notes.append(f"{name}: {prov['detail']}")
            if prov["status"] != "ready":
                results[r["number"]] = prov["status"]
                continue
            r["path"] = prov["path"]
            if prov["created"]:
                # 作ったばかりの PR の作業場に本社から写った属性を消す（残ると、そこで起動した PR の会話が窓口の役の本文を受ける）。本社が
                # worktree の id を書いた属性なら、読む側は写しを空と読むので、写しを丸ごと消す（drop_copies）。id の無い前の版の属性は、本社と同じ値の物を消す
                try:
                    gone = provision.copied(ports.attrs(repo.source), ports.attrs(prov["path"]))
                    if gone:
                        provision.mark(prov["path"], repo.source, gone, ports.git)
                    else:
                        provision.drop_copies(prov["path"], ports.git)
                except (gitx.GitError, OSError) as e:
                    notes.append(f"{name}: 本社から写った属性を消せなかった（{e}）。この作業場の会話が本社の役の本文を受ける")
            untrusted = _trust_note(ports, r["account"], repo.source, prov["path"], cfg.accounts)
            if untrusted:
                notes.append(f"{name}: {untrusted}")
            if r["kind"] == "pr" and not prov["created"] and not a.no_second and r["number"] not in catchup_only:
                r["earlier"] = _earlier_report(cfg, ports, r, notes)   # 新しい会話を起動する前に（起動すると、それがいちばん新しい記録になる）
            got = launch.start(r, prov["pane"], ports.term)
            if got["status"] == "ready":
                ready.append((r, prov["pane"]))
            else:
                results[r["number"]] = got["status"]
                notes.append(f"{name}: {got['detail']}")
        # issue から始めたものは 1 ターン目の /catchup まで（2 ターン目の文は PR のレビューの文なので送らない）
        second = {r["number"]: None if (a.no_second or r["kind"] == "issue" or r["number"] in catchup_only)
                  else repo.second_prompt for r, _ in ready}
        notes.extend(f"#{r['number']}: 自分が作者でレビュアーの付いていない PR なので、/catchup だけ送った"
                     for r, _ in ready if r["number"] in catchup_only and not a.no_second)
        # 送った時刻は 1 ターン目を送る直前（その後の動きを「新しい返事」と見る）、head はその時の場所の head（force-push の見分け）
        # 自分の番でなくなった PR の会話を閉じる（_step_back）のは、一覧の回で送った物だけなので、その印を付けておく
        stamp = {r["number"]: {"at": ports.now(), "head": ports.head_sha(r["path"]), **({"via": "listing"} if listing else {})}
                 for r, _ in ready}
        if ready:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(ready)) as pool:
                futures = {r["number"]: pool.submit(turn.catchup_then_second, r["number"], pane, second[r["number"]], ports.term,
                                                    catchup=ports.catchup_command(r["account"].get("config_dir")),
                                                    state=(lambda r=r: ports.state(r["account"].get("config_dir"), r["path"])),
                                                    earlier=r.get("earlier"))
                           for r, pane in ready}
                results.update({n: f.result() for n, f in futures.items()})
            for r, _ in ready:
                if results.get(r["number"]) == "sent" and r["kind"] == "pr":
                    sent[_key(repo, r["number"])] = stamp[r["number"]]
                    if r["number"] in refresh:
                        results[r["number"]] = "refreshed"
            if sent_ok:
                ports.save_sent(cfg.limits_dir, sent)
            # 1 件あたりの使用率は、/catchup の終わりまで待った件だけで測る（待たずに送った件は、測る時にまだ使っていない）
            counts = collections.Counter(r["account"]["name"] for r, _ in ready if second[r["number"]] is not None)
            measured = [n for n in counts if n in metered]
            if measured:
                ports.refresh_limits(cfg, measured)
                try:
                    ports.save_cost(cfg.limits_dir, cost.samples(before, ports.read_limits(cfg.limits_dir, measured), counts))
                except cost.CostError as e:
                    notes.append(f"{e}（この回の測った値は書かなかった）")
            # 起動した会話には /catchup のページを開かせていない（launch の ATTENTION_CATCHUP_OPEN=0）。送り終えた件だけ、ここで 1 回開く
            opened = ports.open_pages(repo, [r["number"] for r, _ in ready
                                             if r["kind"] == "pr" and results.get(r["number"]) in ("sent", "refreshed")])
            if opened:
                notes.append(opened)

    if listing:
        notes += _tidy(cfg, repo, ports, a.dry_run, found, turn_numbers, sent, limited)
        notes += _step_back_departments(cfg, repo, ports, a.dry_run, dept_places, depts, dept_turn, limited)
    print("\n".join(report.lines(the_plan + held, results, notes)))
    return 0


def _queue_run(a, argv, command, ports):
    """--queue-run。会社は部署の回と同じに、--repo か打った場所の代表の clone から決める（_department_repo）。"""
    others = _queue_run_others(argv)
    if others:
        print(f"止めた: --queue-run と一緒に使えるのは --repo と --config だけ（{' '.join(others)} は外す）", file=sys.stderr)
        return 2
    try:
        repo = _department_repo(config.load(a.config, os.environ, missing_ok=True), a.repo, ports, ports.cwd())
    except config.ConfigError as e:
        print(f"止めた: メインブランチへ入れる列に入れない: {e}。コマンドは走らせていない", file=sys.stderr)
        return queuerun.QUEUE_FAILED
    return queuerun.main(repo, command, ports, a.config)


def _department_repo(cfg, name, ports, cwd):
    """部署の回（--task・--land）の repo。--repo が設定の [[repos]] の名前か source ならそれ。--repo がフォルダなら、その場所の
    git の共通の .git から代表の clone を決める（config.repo_at。[[repos]] に無ければ最小の repo）。--repo が無ければ今いる場所から
    同じに決め、今いる場所が git でなければ設定の最初の repo。決められなければ config.ConfigError。"""
    if name is not None:
        try:
            return config.pick_repo(cfg, name)
        except config.ConfigError:
            pass
        place = os.path.expanduser(name)
        if not os.path.isdir(place):
            raise config.ConfigError(f"--repo の {name} が、設定の [[repos]] の名前でも、在るフォルダでもない"
                                     "（代表の clone のパスを渡すか、その clone の中から打つ）")
    else:
        place = cwd
    root = ports.common_of(place)
    if root:
        return config.repo_at(cfg, root, ports.origin)
    if name is None and cfg.repos:
        return cfg.repos[0]
    raise config.ConfigError(f"{place} が git のリポジトリでないので、会社（代表の clone）を決められない"
                             "（--repo に代表の clone のパスを渡すか、その clone の中から打つ）")


def _name(row):
    return f"{'issue ' if row.get('kind') == 'issue' else ''}#{row['number']}"


def _held_row(p, outcome, places, kind="pr"):
    return {"number": p["number"], "kind": kind, "title": p["title"], "head": p["head"], "url": p.get("url"), "fork": False,
            "outcome": outcome, "account": None, "path": places.get(p["head"])}


def _where(r):
    return f"#{r['number']} {r['branch']}" if r["number"] is not None else f"- {r['branch'] or '（ブランチ無し）'}"


def _changed(repo):
    return lambda path: clean.changed_copies(path, config.copy_root(repo), repo.copy_files)


def _tidy(cfg, repo, ports, dry_run, found, turn_numbers=None, sent=None, limited=frozenset()):
    """閉じた PR（MERGED・CLOSED）のブランチの場所を片付ける（一覧で回すときだけ）。元の clone の linked worktree だけを見る（clean.candidates）。
    会話が 1 つだけ開いていて、手すきで手元の作業も無ければ、会話を終え、会話の一覧を取り直して居ないことを確かめてから消す。
    作業中・会話が 2 つ以上・手元の作業の有る場所は残して名指す。返すのは報告の頭に置く行。読めない・終えられない物は、その場所の
    行にして続ける。
    開いている PR で自分の番（turn_numbers。whose-turn の一覧。読めなければ main がその前に止まる）でない物は、_step_back で会話を終えて
    作業場を閉じる（worktree は残す）。limited（whose-turn の limited）に入った PR は閉じずに名指す。"""
    try:
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
    except chat.Error as e:
        return [f"片付けを飛ばした（開いている会話を読めない: {e}）"]
    sess = sessions.collect(listed, ports.branch, ports.origin)
    changed = _changed(repo)
    rows = _candidates(repo, ports, found, {x["cwd"] for x in sess if x["cwd"]}, changed)
    out = []
    for r in rows:
        if r["reason"] == "pr_open" and turn_numbers is not None and r["number"] not in turn_numbers:
            out += _step_back(repo, ports, dry_run, r, sess, sent or {}, r["number"] in limited)
            continue
        finished = r["state"] in clean.FINISHED
        if r["reason"] == "session" and finished:
            mine = _at(sess, r["path"])
            files = changed(r["path"])
            head = clean.in_pr(r["path"], r["pr_head"], ports.head_sha, ports.is_ancestor)
            local = (not ports.is_clean(r["path"]) or ports.stashed(r["path"], r["branch"]) or not head or files)
            if len(mine) > 1:
                out.append(f"{_where(r)}: 閉じた PR だが、会話が {len(mine)} つ開いているので残した")
                continue
            if any(x["status"] != "idle" for x in mine) or local:
                out.append(f"{_where(r)}: 閉じた PR だが、会話が作業中か手元の作業が有るので残した")
                continue
            if dry_run:
                out.append(f"{_where(r)}: 閉じた PR なので、会話を終えて片付ける")
                continue
            closed, why = _end_conversation(ports, r["path"])
            if closed != "closed":
                out.append(f"{_where(r)}: 閉じた PR の会話を終えられなかったので残した（{why}）")
                continue
            try:
                left = _at([s for acc in cfg.accounts for s in ports.list_sessions(acc.config_dir)], r["path"])
            except chat.Error as e:
                out.append(f"{_where(r)}: 会話を終えた後の一覧を読めないので残した（{e}）")
                continue
            if left:
                out.append(f"{_where(r)}: 会話を終えた後も、その場所に会話が見えるので残した")
                continue
            r = {**r, "head": head, "removable": True, "reason": None}
        if finished and r["reason"] in ("dirty", "unpushed"):
            out.append(f"{_where(r)}: 閉じた PR だが、手元の作業が有るので残した")
            continue
        if finished and r["reason"] == "local_files":
            out.append(f"{_where(r)}: 閉じた PR だが、写したファイルが写し元と違うので残した: {', '.join(r['files'])}")
            continue
        if not r["removable"]:
            continue
        if dry_run:
            out.append(f"{_where(r)}: 閉じた PR なので片付ける")
            continue
        got = clean.remove(r, repo.source, provision.label(repo, r["branch"]), ports.term, ports.git)
        out.append(f"{_where(r)}: " + ("片付けた" if got["removed"] and got["branch_deleted"] else
                                       f"片付けた（{got['detail']}）" if got["removed"] else f"片付けられなかった（{got['detail']}）"))
    return out


def _step_back(repo, ports, dry_run, r, sess, sent, limited=False):
    """自分の番でなくなった開いている PR の場所で、dispatch が開いた会話を終えて herdr の作業場を閉じる（worktree は残す。自分の番に戻れば、
    一覧の回が同じ場所に新しい会話を立てる）。送り直し（fresh.decide の refresh）と同じく、会話が 1 つだけで手すき・未コミットの変更も
    手元にしか無い commit も無いときだけ。加えて、dispatch が一覧の回で送った会話（控えに一覧の回の印が有り、会話の起動が送った時より前）
    だけを閉じる。持ち主が自分で開いた会話と、--pr・--issue で開いた会話と、印を書く前の版の控えの会話には触らず、触らない訳を報告の
    行に書く（_not_listed_why）。limited（whose-turn がその PR の材料を取り切れなかった）なら、自分の番でないという判定が取りこぼしの上に立つので閉じない。返すのは報告の行。"""
    rec = _sent_record(sent.get(_key(repo, r["number"])))
    mine = _at(sess, r["path"])
    if not mine:
        return []
    why = _not_listed_why(rec, mine)
    if why:
        return [f"{_where(r)}: 自分の番でない PR だが、dispatch が一覧の回で開いた会話と言い切れないので残した（{why}）"]
    if limited:
        return [f"{_where(r)}: 自分の番でないと出たが、whose-turn が材料を取り切れなかった（走査の上限に当たった）ので会話を残した"]
    path = r["path"]
    local = _local_work(ports, path, r["branch"], rec)
    if mine[0]["status"] != "idle" or not ports.is_clean(path) or local:
        return [f"{_where(r)}: 自分の番でない PR だが、会話が作業中か手元の作業が有るので会話を残した"]
    if dry_run:
        return [f"{_where(r)}: 自分の番でない PR なので、会話を終えて作業場を閉じる（worktree は残す）"]
    closed, why = _end_conversation(ports, path)
    if closed != "closed":
        return [f"{_where(r)}: 自分の番でない PR の会話を終えられなかったので残した（{why}）"]
    rel = clean.release(repo.source, path, ports.term)
    if rel["status"] == "close_failed":
        return [f"{_where(r)}: 自分の番でない PR の会話を終えたが、作業場を閉じられなかった（{rel['detail']}）"]
    if rel["status"] == "none":
        return [f"{_where(r)}: 自分の番でない PR なので会話を終えた（{term.NAME} の作業場は開いていなかった）"]
    return [f"{_where(r)}: 自分の番でない PR なので、会話を終えて作業場を閉じた（worktree は残した）"]


def _step_back_departments(cfg, repo, ports, dry_run, places, names, turn_numbers, limited):
    """自分の番でなくなった開いている PR の部署の作業場（herdr の窓）を閉じる（一覧の回だけ）。places は部署の場所（_department_places の
    ブランチの物）、names は {ブランチ: 部署の名前}、turn_numbers は自分の番に居る部署の PR の番号。部署の裏の会話・worktree・ブランチは
    残す（--retire しない。レビューの指摘を、事情を知った同じ会話へ --ask で回すため。次の --ask が作業場を開き直す: orders.revive）。
    閉じるのは、窓が開いていて、部署の場所の会話がどれも手すきか止まっていて、受けた頼みを納品し終え、順番待ちに頼みが無く、未コミットの
    変更も手元にしか無い commit・stash も無いときだけ（2026-10-29 に guided-resolver で、相手の番の PR の部署の窓が 8 つ開いたまま残った。
    持ち主「部署も同じ扱いにして」）。窓の前の attach の画面は Ctrl+Z でシェルに戻してから閉じる（launch.to_shell。裏の会話は止まらない）。
    limited（whose-turn がその PR の材料を取り切れなかった）なら閉じない。返すのは報告の行。"""
    places = [p for p in places if p.get("workspace")]
    if not places:
        return []
    try:
        listed = [s for acc in cfg.accounts for s in ports.list_sessions(acc.config_dir)]
    except chat.Error as e:
        return [f"部署の窓を閉じるのを飛ばした（開いている会話を読めない: {e}）"]
    out = []
    for p in sorted(places, key=lambda p: p["path"]):
        path, where = p["path"], f"部署「{names[p['branch']]}」"
        try:
            got = ports.pr_for_branch(repo, p["branch"])
        except clean.Unknown as e:
            out.append(f"{where}: ブランチの PR を読めないので窓を残した（{e}）")
            continue
        if not got or got.get("state") != "OPEN" or got["number"] in turn_numbers:
            continue
        where = f"#{got['number']} {where}"
        if got["number"] in limited:
            out.append(f"{where}: 自分の番でないと出たが、whose-turn が材料を取り切れなかった（走査の上限に当たった）ので窓を残した")
            continue
        why = _department_busy(ports, path, _at(listed, path))
        if why:
            out.append(f"{where}: 自分の番でない PR だが、{why}ので窓を残した")
            continue
        try:
            panes = [x["pane_id"] for x in ports.term.panes() if x.get("workspace_id") == p["workspace"]]
            other = [x for x in panes if not ports.term.shell_in_front(x)
                     and not any(" attach " in f" {c} " for c in ports.term.foreground(x))]
        except term.Error as e:
            out.append(f"{where}: 自分の番でない PR だが、窓のペインを読めないので残した（{e}）")
            continue
        if other:
            out.append(f"{where}: 自分の番でない PR だが、窓のペイン {', '.join(other)} の前で attach の画面でない物が動いているので残した")
            continue
        if dry_run:
            out.append(f"{where}: 自分の番でない PR なので、部署の窓を閉じる（会話と worktree は残す）")
            continue
        stuck = [x for x in panes if not launch.to_shell(x, ports.term, ports.pause)]
        if stuck:
            out.append(f"{where}: 自分の番でない PR だが、窓のペイン {', '.join(stuck)} の attach の画面をシェルに戻せないので残した")
            continue
        rel = clean.release(repo.source, path, ports.term)
        out.append(f"{where}: " + (f"自分の番でない PR だが、部署の窓を閉じられなかった（{rel['detail']}）" if rel["status"] == "close_failed" else
                                   f"自分の番でない PR だが、部署の窓は {term.NAME} にもう開いていなかった" if rel["status"] == "none" else
                                   f"自分の番でない PR なので、部署の窓を閉じた（会話と worktree は残した。返しは --ask '{names[p['branch']]}' で回す）"))
    return out


def _department_busy(ports, path, mine):
    """部署の窓を閉じない訳（無ければ None）。mine はその場所の会話の一覧の行。"""
    if any(s.get("state") == "blocked" or (s.get("status") or s.get("state")) not in ("idle",) + clean.DONE for s in mine):
        return "会話が作業中か返事待ち"
    attrs = ports.attrs(path)
    if attrs.get("ask") and attrs.get("delivered") != attrs["ask"]:
        return f"納品していない頼み（受付 {attrs['ask']}）が在る"
    common, place = ports.git.common_dir(path), ports.git.git_dir(path)
    if not (common and place) or wake.queued(deliver.inbox_of(common), place):
        return "順番待ちに頼みが在るか、順番待ちを読めない"
    if not ports.is_clean(path):
        return "未コミットの変更が有る"
    if ports.unpushed(path):
        return "手元にしか無い commit か stash が有る"
    return None


def _not_listed_why(rec, mine):
    """その場所の会話（mine。1 つ以上）が、dispatch が一覧の回で送った会話と言い切れない訳。言い切れれば None。
    持ち主に閉じない訳が見えるように、_step_back が報告の行に書く（2026-10-20 に、前の版で送った会話が訳を出さずに残った）。"""
    if len(mine) > 1:
        return f"同じ手元に会話が {len(mine)} つ開いている"
    if not isinstance(rec["at"], (int, float)):
        return "送った記録が無い。持ち主が自分で開いた会話か"
    if not rec["listed"]:
        return "送った記録に一覧の回の印 via: listing が無い。--pr・--issue で開いた会話か、印を書く前の版で送った会話"
    if not isinstance(mine[0]["started"], (int, float)):
        return "会話の起動の時刻が分からない"
    if mine[0]["started"] > rec["at"]:
        return "記録より後に起動された会話。持ち主が自分で開いた会話か"
    return None


def _contact(caller, account):
    """サブエージェントの最初の文の後ろに書き足す、連絡の道の 1 文。呼んだ会話と同じアカウントで、その名前が分かれば SendMessage。
    アカウントが違うと SendMessage が届かない（2026-10-16 に持ち主の手元で、別のアカウントの会話どうしで両方向とも
    「No agent named … is reachable」になり、各会話の一覧にも同じアカウントの会話しか出なかった）ので、画面に書いて止まらせる。"""
    if caller["name"] and caller["account"] == account:
        return f"報告は区切りごとに SendMessage で「{caller['name']}」へ送る（呼んだ会話と同じアカウントなので届く）。"
    if not caller["account"]:
        why = "呼んだ会話が分からず、SendMessage の宛先を決められない"
    elif caller["account"] == account:
        why = "呼んだ会話の名前が分からず、SendMessage の宛先を決められない"
    else:
        why = f"呼んだ会話{'「' + caller['name'] + '」' if caller['name'] else ''}とはアカウントが違い、SendMessage が届かない"
    return f"報告は区切りごとにこの画面に短く書いて止まる（{why}。呼んだ側が {term.NAME} でこの画面を読む）。"


def _brief_text(brief, caller, account, tail=None):
    """サブエージェントに最初に送る文（1 行）。tail は連絡の道の文の代わり（--ask は納品のコマンドでの返し方）。
    「その通りに」とは書かない（頼みに異論を返してよいかは会社の形の役の本文が決める。頼みの文がそれを打ち消さないように）。"""
    return f"作業の頼みです。{brief} を読んで進めてください。" + (tail or _contact(caller, account))


def _task(cfg, repo, a, ports, extra_attrs=None, tail=None, refreshed=False):
    """部署を 1 つ立てる（会社の形の設計 9.1）。場所は PR と同じ決まり（provision.prepare_task。herdr が元の clone の子の作業場として
    worktree を作る）、アカウントは同じ割り振り（accounts.rank と assign.plan。1 件なので、使用率が上限に届かないアカウントのうち
    順の頭）。部署の属性を git に書き（provision.mark）、その作業場のペインで Claude Code の裏の会話を起動し（launch.start_background。
    裏の会話が自分で worktree を作らないよう、templates/department-settings.json で worktree.bgIsolation を none にする）、会話の一覧から
    会話の id を読んで属性に足し、同じペインで attach する（launch.attach）。表示名と札は --sync と同じ組み立て（sync）。

    置き場とブランチを下回りが決めるために、Claude Code に worktree を作らせず、先に作った worktree の中で起動する。WorktreeCreate のフックでも
    置き場とブランチは決められた（2026-10-16 に試した）が、フックはその会話の中の全部の worktree（サブエージェントの isolation など）を
    置き換え、フックの作った worktree は claude rm が消さずに断る。

    会社の形は、読む前に origin の既定のブランチを取り直してから読む（provision.refresh_shape。--dry-run では取り直さない）。refreshed は、
    呼んだ側（--ask）がもう取り直したこと。"""
    brief = os.path.abspath(os.path.expanduser(a.brief))
    if not os.path.isfile(brief):
        print(f"止めた: 頼みのファイルが無い: {brief}")
        return 2
    # 役の項目（会社の形の [[roles]]）と gh のアカウント。会社の形は --tree と同じ読み方（会社の形の設計 4.7・4.8）
    cfg_path = config.path_of(a.config, os.environ)
    fetched = None if a.dry_run or refreshed else provision.refresh_shape(repo.source, ports.git)
    info = tree.read_info(repo.source, os.path.dirname(cfg_path), ports.git)
    shape = role.load(info["path"], info["text"])
    role_name, why = (a.role, None) if a.role else role.default(shape, DEFAULT_ROLE)
    the_role, why = (None, why) if why else role.pick(shape, role_name, a.role is not None)
    if why:
        print(f"止めた: {why}")
        return 2
    # 部署の名前で引いた受け持ち（[[skills]]。名前が同じ物か、「<受け持ち>：<何をするか>」の受け持ちの物。role.duty_of）に model・effort・
    # settings が有れば、役の値より先に効く（settings は役の設定の上に重ねる）。effort の inherit は、呼んだ会話の今の effort
    duty = role.duty_of(info["skills"], a.task)
    # 受け持ちの席の役（担当）は、受け持ちの名前でしか立てない。--persistent を名指した回（--move の起動し直しなど）は問わない
    why = None if a.persistent else role.seat_problem(shape, role_name, the_role, info["skills"], a.task)
    if why:
        print(f"止めた: {why}")
        return 2
    # 寿命が always（役か受け持ちの lifetime。role.lifetime_at）なら --persistent と同じ。on-demand・per-ask の受け持ちの部署は畳む部署で立てる
    persistent = a.persistent or bool(the_role) and role.lifetime_at(the_role, info["skills"], a.task) == role.ALWAYS
    model, effort, flags_note = role.launch_flags(the_role, ports.env, duty)
    gh_user, gh_note = role.gh_user(repo.gh_user, shape)
    repo = repo._replace(gh_user=gh_user)
    # 始める前の確かめは、部署を立てるこの repo だけを見る（設定の [[repos]] に無い repo も、ほかの repo の足りない物で止めない）
    cfg = cfg._replace(repos=(repo,))
    names = [x.name for x in cfg.accounts]
    if a.from_account and a.from_account not in names:
        print(f"止めた: --from-account の {a.from_account} が設定の accounts に無い（{', '.join(names)}）")
        return 2
    problems, notes = ports.preflight(cfg, task=True)
    notes = (list(cfg.notes) + [n for n in [fetched] if n] + info["notes"] + shape["problems"]
             + [p for p in info["problems"] if p not in shape["problems"]]
             + [n for n in [gh_note, flags_note] if n]
             + role.warnings(the_role) + notes)
    if problems:
        print("止めた（始める前の確かめで足りない物）:")
        print("\n".join(f"- {p}" for p in problems))
        return 2
    try:
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
        found = ports.places(repo)
    except (chat.Error, term.Error) as e:
        print(f"止めた: {e}")
        return 1
    # 同じ名前の会話。止めた裏の会話（--move が起動し直す前の会話）は数えない。SendMessage の宛先はアカウントの中で、dispatch の
    # 宛て方（「会社/名前」）は会社の中で 1 つに決まれば足りる。同じ会社の中の重なりは止め、ほかの会社の重なりは、そのアカウントを
    # 避けて振る（部署の名前に会社の名前を付けない決まりのまま、会社ごとに同じ名前の受け持ちを並べて立てるため）
    alive = [(acc, s) for acc, items in listed.items() for s in items
             if s.get("name") == a.task and s.get("state") not in ("done", "failed", "stopped")]
    here = [acc for acc, s in alive if s.get("cwd") and any(filex.inside(s["cwd"], p["path"]) for p in found if p.get("path"))]
    if here:
        print(f"止めた: 「{a.task}」という名前の会話がこの会社にもう開いている（アカウント {', '.join(sorted(set(here)))}）。"
              "宛先が 1 つに決まらないので、別の名前で頼む")
        return 1
    try:
        heir = [w["path"] for w in ports.git.listed_worktrees(repo.source) if a.task in gitx.inherited_names(ports.attrs(w["path"]))]
    except (gitx.GitError, OSError):
        heir = []   # 場所を読めなければ、ここでは止めない（宛先を引く --ask が、同じ名前の場所が 2 つ以上あれば止める）
    if heir:
        print(f"止めた: 「{a.task}」は、この会社の部署（{'、'.join(heir)}）が --handover で継いだ名前。その名前宛ての頼みと納品の返し先は"
              "継いだ部署に当たるので、別の名前で頼む")
        return 1
    taken = {acc for acc, _ in alive}
    found_account, found_name = ports.caller(listed)
    caller = {"account": a.from_account or found_account, "name": a.from_name or found_name}
    if not caller["account"]:
        notes.append(f"呼んだ会話が分からない（{chat.NAME} の外から走らせたか、その会話が一覧に見えない）ので、サブエージェントには画面に報告を"
                     "書かせる。SendMessage で受けたいなら --from-name と --from-account で渡す")
    sess = sessions.collect(listed, ports.branch, ports.origin)
    metered = [x.name for x in cfg.accounts if x.limits]
    if not a.dry_run:
        ports.refresh_limits(cfg, metered)
    # --move はアカウントを名指して起動し直す（only_account）。ほかの回は、使用率の順の頭
    only = getattr(a, "only_account", None)
    pool = [x for x in cfg.accounts if x.name == only] or cfg.accounts
    if taken:
        free = [x for x in pool if x.name not in taken]
        if not free:
            print(f"止めた: 「{a.task}」という名前の会話がほかの会社でもう開いていて（アカウント {', '.join(sorted(taken))}）、"
                  "振れるアカウントがほかに無い。同じアカウントでは SendMessage の宛先が 1 つに決まらないので、"
                  "設定の accounts にアカウントを足すか、その会話が終わってから頼む")
            return 1
        notes.append(f"「{a.task}」という名前の会話がほかの会社でアカウント {', '.join(sorted(taken))} に開いているので、"
                     "そのアカウントを避けて振る")
        pool = free
    ranked = accounts.rank(pool, ports.read_limits(cfg.limits_dir, metered), cfg.limit_percent, ports.now(),
                           accounts.count_running(listed), margin_minutes=cfg.hours_margin_minutes)
    # 会社の形の役か受け持ちが名指したアカウント（account）は、使えれば順の頭へ。使えなければ使用率の順のまま、訳を注記に出す。
    # --move の起動し直し（only_account）では名指しを見ない（アカウントを替えるのは --move の受け持ち）
    wish, wisher = (None, None) if only else role.launch_account(the_role, duty)
    if only:
        ranked = accounts.named(ranked, only)   # --move の名指しは、名指しのときだけ使うアカウントも使う
    wished = next((x for x in cfg.accounts if x.name == wish), None)
    ranked, wish_note = accounts.prefer(ranked, wish, accounts.count_open(listed.get(wish, [])), wisher,
                                        wished.max_open if wished else 1, bool(wished and wished.named_only))
    if wish_note and not ranked:   # 名指しのときだけ使うアカウントの名指しが使えない。ほかのアカウントで立てずに止める
        print("\n".join(notes + [f"止めた: {wish_note}（使えるようになってから頼み直す。会話の数で止まったなら、設定の max_open を上げてもよい）"]))
        return 1
    if wish_note:
        notes.append(wish_note)
    row = assign.plan(repo, [{"number": None, "kind": "task", "title": a.task, "head": a.branch}], sessions.open_keys(sess),
                      {s["cwd"] for s in sess if s["cwd"]}, ranked, cfg.limit_percent, None, _branch_places(found))[0]
    row["label"] = a.task
    if row["outcome"] != "assigned":
        why = {"already_open": "そのブランチの場所で会話がもう開いている（会話を閉じるのは持ち主だけ）",
               "no_account": "使用率が上限に届かず、使える時間帯の中のアカウントが無い"}[row["outcome"]]
        print("\n".join(notes + [f"部署 {a.task}  {a.branch}  -  {row['outcome']}（{why}）"]))
        return 0
    account = row["account"]["name"]
    many = len(cfg.accounts) > 1
    pane_label = sync.label(a.task, account, many)
    # 部署の属性（正本）。頼み元は呼んだ会話。分からない物は書かない
    attrs = {"role": role_name, "lifecycle": gitx.PERSISTENT if persistent else gitx.EPHEMERAL, "fresh": role.FRESH if the_role and the_role["context"] == role.NEW else None,
             "account": account,
             "name": a.task, "boss": caller["name"], "boss-account": caller["account"], "gh-user": gh_user,
             # 既定の置き場でない dispatch の設定を使ったときだけ、その場所（役を足すフックが、設定の置き場の会社の形を探すため）
             "config": None if cfg_path == config.path_of(None, {}) else cfg_path,
             # 起動したときの会社の形の model・effort（new の部署の待ち受けが、今の値と比べて起動し直すかを決める）
             wake.LAUNCHED: role.launch_key(the_role, duty), **{k: v for k, v in (extra_attrs or {}).items() if v}}
    route = ("納品のコマンドで頼み元の窓へ" if tail else f"SendMessage で「{caller['name']}」へ"
             if caller["name"] and caller["account"] == account else "区切りで画面に書いて止まる")
    if a.dry_run:
        print("\n".join(notes + [
            f"部署 {a.task}  {a.branch}  {account}  {provision.would(row, found)}",
            f"- 起動するフォルダ: {row['path'] or '<作る作業場の場所>'}",
            f"- ペインの名前: {pane_label}／会話の名前: {a.task}",
            f"- 部署の属性: " + "、".join(f"company.{k}={v}" for k, v in attrs.items() if v),
            f"- 連絡の道: {route}",
            f"- 会社の形: {info['path'] or '無い'}（--dry-run なので origin を取り直さず、手元の控えで読んだ）",
            f"- 先に使うアカウント: " + (f"{wish}（{wisher}。{'使わない' if wish_note else '使う'}）" if wish else "名指し無し（使用率の順）"),
            f"- 役の起動の設定: モデル {model or '既定'}、effort {effort or '既定'}、--settings の鍵 "
            + ", ".join(role.settings_for(the_role, duty))
            + (f"（受け持ち {duty['name']} の settings を重ねた）" if duty and duty.get("settings") else ""),
            f"- gh のアカウント: " + (f"{gh_user}（会話の Bash がコマンドごとに鍵を取り出し、GH_TOKEN に入れる）" if gh_user else "渡さない"),
            f"- 最初の文: {_brief_text(brief, caller, account, tail)}"]))
        return 0
    existed = bool(provision.find(found, a.branch))
    try:
        base = None if existed else (a.base or ports.default_branch(repo))
    except (ghx.GhError, gitx.GitError) as e:
        print(f"止めた: {e}（ブランチを作る元の既定のブランチを読めない。--base で渡す）")
        return 1
    prov = provision.prepare_task(row, repo, base, ports.term, ports.git)
    if prov["detail"]:
        notes.append(prov["detail"])
    result = prov["status"]
    pane = prov["pane"]
    if prov["status"] == "ready":
        untrusted = _trust_note(ports, row["account"], repo.source, prov["path"], cfg.accounts)
        if untrusted:
            notes.append(untrusted)
        try:
            provision.hide_claude_dir(repo.source, ports.git)
            # 本社の属性が部署に写って残ると、部署が窓口の会話を自分の会話と取り違える（まっさらな環境での 4 回目の試しの 3）。
            # 本社と同じ値のまま残っている属性のうち、今回書かない物は消す（provision.copied）
            # 立っている部署の場所を開き直したとき（--task の打ち直し・--move）は、属性は部署の物なので消さない（頼み元の受付箱
            # company.boss-inbox は、ふつう本社の物と同じ値なので、消されていた。d7d50c）
            office = {} if existed else ports.attrs(repo.source)
            # company.pid は --desk だけが本社に書く（--desk は部署の worktree で止まる）ので、部署の場所に在れば写った物。使い直した
            # 場所（前の版で作った PR の作業場など）でも消す（残ると部署が窓口の席と見られ、役の本文を受けない）
            copied = {**provision.copied(office, ports.attrs(prov["path"]), attrs), "pid": None}
            provision.mark(prov["path"], repo.source, {**copied, **attrs}, ports.git)
            if not ports.attrs(prov["path"]).get("base"):
                # この部署がメインブランチを知った位置（ブランチを作ったときの origin のメインブランチ）。--land の書き換えの取り合いのゲートが、ここより後に
                # ほかの部署が入れた行を、この部署のブランチが消していないかを見る。--land の後は入れた後のメインブランチに進む
                known = ports.git.rev(repo.source, f"refs/remotes/origin/{ports.default_branch(repo)}")
                if known:
                    provision.mark(prov["path"], repo.source, {"base": known}, ports.git)
            if attrs["lifecycle"] == gitx.PERSISTENT and a.branch and not existed and not ports.unpushed(prov["path"]):
                # always の部署の最初のブランチも、入れたブランチと同じに記録する。頼みごとにブランチを移るので、入れずに移った最初のブランチ（--brief で
                # 立てただけのブランチなど）も手元に残る。先頭が今のままなら、部署が移った後の --land か --clean --apply が消す。
                # 書くのは部署を立てたときだけ（開き直し〔--task の打ち直し・--move〕の先頭には、まだ入れていない commit が載りうる）。
                # 立てたときも、手元にしか無い commit の載ったブランチ（前に入れずに移ったブランチを開き直した）は書かない（消すと commit ごと失う）
                first = {**clean.landed_of(ports.attrs(prov["path"]), strict=True), a.branch: ports.git.rev(prov["path"], "HEAD")}
                provision.mark(prov["path"], repo.source, {clean.LANDED_BRANCHES: json.dumps(first, ensure_ascii=False)}, ports.git)
        except (gitx.GitError, OSError) as e:
            notes.append(f"部署の属性を書けなかった（{e}）。--tree に役・頼み元が出ず、--sync で札を付け直せず、--clean が部署を片付けない")
        row["label"] = pane_label
        settings = ports.department_settings()
        if (the_role or {}).get("settings") or (duty or {}).get("settings"):
            try:
                settings = role.write_settings(ports.git.git_dir(prov["path"]), role.settings_for(the_role, duty))
            except (OSError, TypeError) as e:
                notes.append(f"役 {role_name} と受け持ちの設定を書けなかったので、それらの設定なしで起動する（{e}）")
        got = launch.start_background(row, pane, a.task, settings, _brief_text(brief, caller, account, tail),
                                      ports.term, pause=ports.pause, model=model, effort=effort)
        if got["detail"]:
            notes.append(got["detail"])
        result = got["status"]
        if got["status"] == "sent":
            talk, why = _started(ports, row["account"].get("config_dir"), a.task, prov["path"], pane)
            if talk is None:
                result = "launch_failed"
                notes.append(why)
            else:
                sid = chat.attach_id(talk)
                try:
                    provision.mark(prov["path"], repo.source, {"session": talk["sessionId"], "job": sid}, ports.git)
                except (gitx.GitError, OSError) as e:
                    notes.append(f"会話の id を属性に書けなかった（{e}）。--clean がこの部署を片付けない")
                got = launch.attach(row, pane, sid, ports.term)
                result = "started" if got["status"] == "attached" else got["status"]
                if got["detail"]:
                    notes.append(f"裏の会話 {sid} は始まったが、窓につなげなかった（{got['detail']}）")
                # 表示名と札は、書いた属性を git から読み戻して付ける（--sync と同じ組み立て。名前は launch が付けた）
                written = ports.attrs(prov["path"])
                shown = sync.apply([sync.op(pane, written, many, current_label=pane_label)], ports.term)
                notes += [f"ペインに表示名と札を付けられなかった（{x['detail']}）" for x in shown if x["status"] != "done"]
                if prov.get("workspace"):
                    shown = sync.apply_workspaces([sync.kind_op(prov["workspace"], role.seat(written, info["skills"], shape))], ports.term)
                    notes += [f"作業場に席の印（寿命と会話）を付けられなかった（{x['detail']}）" for x in shown if x["status"] != "done"]
                    notes += _order_company(repo.source, info["skills"], shape, ports)
                route += f"（会話 {sid}）"
    if result == "started" and not existed:
        # 部署を新しく立てた後の合図（会社の形の [[task.after]]）。開き直し（--task の打ち直し・--move）では呼ばない
        after, bad = calls.task_rules(info)
        notes += [f"注記: {b}" for b in bad]
        if after:
            notes += [n for n in [calls.task_later(a, ports, repo.source, prov["path"])] if n]
    print("\n".join(notes + [f"部署 {a.task}  {a.branch}  {account}  {result}"] +
                    ([f"- ペイン {pane}（{pane_label}）、作業場 {prov['path']}、連絡の道: {route}"] if pane else [])))
    return 0 if result == "started" else 1   # 起きなかった（launch_failed・blocked など）を、呼んだ側（--ask・台本）に終了の値で知らせる


# 起動した裏の会話が会話の一覧に出るのを見る回数（1 回ごとに ports.pause）。Windows の `claude --bg` は、裏の会話を受ける
# 仕組み（background service）を起動するのに 2〜3 秒かかり、その間もペインの前のプロセスを見る口（shell_in_front）は戻ったと
# 答える（2026-10-16 に Windows 11 ARM64 の Claude Code 2.1.301 で、打ってから一覧に出るまで 2.7 秒を測った）。1 回だけ
# 見ると、立った会話を見落として launch_failed にし、attach を打たなかった（まっさらな環境での 4 回目の試しの 2）。
STARTED_LOOKS = 20
# `claude --bg` が起動した後にペインへ出す行（「backgrounded · <短い id> · <名前>」）。一覧より先に画面に出ることがある
BACKGROUNDED = re.compile(r"backgrounded\s*·\s*([0-9a-f]{6,})\s*·")


def _started(ports, config_dir, name, path, pane):
    """起動した裏の会話を、そのアカウントの会話の一覧（終わった物も）から、名前と場所で探す。(会話の 1 件, None) か
    (None, 訳)。出るまで STARTED_LOOKS 回まで見直す。見つからなければ、ペインの画面の終わりを訳に添える。"""
    tail = ""
    for look in range(STARTED_LOOKS):
        if look:
            ports.pause()
        try:
            items = ports.list_sessions(config_dir, include_done=True)
        except chat.Error as e:
            return None, f"起動した後に会話の一覧を読めない（{e}）"
        mine = [s for s in items if s.get("name") == name and s.get("cwd") and filex.inside(s["cwd"], path)]
        if mine:
            return max(mine, key=lambda s: s.get("startedAt") or 0), None
        try:
            screen = ports.term.read(pane, 6)
        except term.Error as e:
            screen = f"画面も読めない（{e}）"
        tail = " ".join(screen.split())[-300:]
        shown = BACKGROUNDED.search(screen)
        if shown:   # 画面には起きたと出た: 一覧のその id の会話を使う（名前の字が一覧で違って見えるときも拾う）
            hit = [s for s in items if (s.get("id") or "").startswith(shown.group(1))
                   or (s.get("sessionId") or "").startswith(shown.group(1))]
            if hit:
                return hit[0], None
    return None, f"打ち込んだが、会話の一覧に「{name}」の裏の会話が出ない（{STARTED_LOOKS} 回見た。画面の終わり: {tail}）"


def _company(a, ports):
    """--tree と --sync。herdr の作業場から会社を出し、部署と属性と会社の情報を読んで組み立て（survey_companies）、--sync はその
    組み立てから付け直す（sync_companies）。dispatch の設定は無くてよい。有れば、アカウントごとの会話の一覧で部署の会話のアカウントを
    見て、設定の置き場の会社の情報を読む。"""
    if a.tree == a.sync:
        print("止めた: --tree か --sync のどちらか 1 つを付ける（--json は --tree と一緒に）")
        return 2
    if a.json and not a.tree or a.dry_run and not a.sync:
        print("止めた: --json は --tree と、--dry-run は --sync と一緒にだけ使う")
        return 2
    if a.sync:
        lines, rc = sync_companies(a.config, ports, a.dry_run)
        print("\n".join(lines))
        return rc
    try:
        accounts_, _, companies, settings, notes = survey_companies(a.config, ports, plugins=True)
    except term.Error as e:
        print(f"止めた: {term.NAME} を読めない（{e}）")
        return 1
    calls.annotate(companies, settings, ports.git)
    shown = _overview(accounts_, ports)
    if a.json:
        jsonio.dump({"companies": companies, "accounts": shown, "notes": notes}, None)
        return 0
    print("\n".join(notes + tree.lines(companies) + (accounts.overview_lines(shown) if shown else [])))
    return 0


def survey_companies(config_path, ports, only=None, plugins=False):
    """herdr の作業場から会社を出し（tree.roots）、会社ごとに部署（herdr アダプタの worktrees）と属性（git）と会社の情報を読んで
    組み立てる（tree.build）。only を渡せば、その代表の clone の会社だけ。(アカウントの並び, herdr の作業場の並び, 会社の並び,
    設定の置き場, 注記)。plugins が真なら、注記に wiring.setting_notes（使えない版を指す設定など）と limits.expiry_notes
    （Keychain のトークンの期限）も足す（どちらも --tree だけが出す）。herdr を読めなければ term.Error。"""
    notes = []
    path = config.path_of(config_path, os.environ)
    limits_dir = None
    try:
        cfg = config.load(config_path, os.environ, missing_ok=True)
        accounts_, limits_dir = cfg.accounts, cfg.limits_dir
    except config.ConfigError as e:
        accounts_ = (config.Account("default", chat.COMMAND),)
        if os.path.exists(path):
            notes.append(f"dispatch の設定を読めないので、既定のアカウント 1 つとして見る（{e}）")
    if plugins:
        notes += wiring.setting_notes(os.environ, [config.effective_config_dir(a, os.environ) for a in accounts_], limits_dir)
        notes += limits.expiry_notes(accounts_, os.environ)
    if limits_dir:
        notes += limits.problems(accounts_, os.path.expanduser(limits_dir), time.time())
    sessions_ = {}
    for acc in accounts_:
        try:
            sessions_[acc.name] = ports.list_sessions(acc.config_dir, include_done=True)
        except chat.Error as e:
            notes.append(f"アカウント {acc.name} の会話の一覧を読めないので、そのアカウントの会話を見ない（{e}）")
    panes, workspaces_ = ports.term.panes(), ports.term.workspaces()
    roots = tree.roots(workspaces_, panes, ports.common_of,
                       list(dict.fromkeys(s["cwd"] for items in sessions_.values() for s in items if s.get("cwd"))))
    if only:
        roots = [r for r in roots if os.path.realpath(r) == os.path.realpath(only)]
    places_of = {}
    for root in roots:
        try:
            places_of[root] = ports.term.worktrees(root)
        except term.Error as e:
            places_of[root] = []
            notes.append(f"{root}: worktree を並べられない（{e}）")
    settings = os.path.dirname(path)
    companies = tree.build(roots, places_of, panes, ports.attrs, lambda root: tree.read_info(root, settings, ports.git), sessions_)
    for d in (d for c in companies for d in c["departments"]):
        d["tool_place"] = not d["branch"] and tools.is_place(d["path"])   # 機械のツールを走らせる一時の worktree（--tree が「（ブランチ無し）」と分けて出す）
    return accounts_, workspaces_, companies, settings, notes


def _order_company(source, skills, shape, ports):
    """立てた部署の会社の作業場を、仕事の流れの順に並べ直す（sync.flow_order。herdr は新しい作業場を後ろに足すので、always の部署を
    立てたときは前へ動かす）。ほかの会社の作業場は、会社の印を外して渡し、動かさない。並べ直せなかった訳の注記の並び。"""
    root = os.path.realpath(source)
    try:
        listed = [w if w.get("repo_root") and os.path.realpath(w["repo_root"]) == root else {**w, "repo_root": None}
                  for w in ports.term.workspaces()]
    except term.Error as e:
        return [f"作業場を流れの順に並べられなかった（{term.NAME} を読めない: {e}）"]
    def seat_of(path):
        attrs = ports.attrs(path)
        return role.seat(attrs, skills, shape), attrs.get("name")
    done = sync.apply_order(sync.flow_order(listed, seat_of, lambda r: skills), ports.term)
    return [f"作業場を流れの順に並べられなかった（{x['detail']}）" for x in done if x["status"] == "failed"]


def sync_companies(config_path, ports, dry_run=False, only=None):
    """--sync の中身。会社の形の役を部署と本社の属性に写し直し（_sync_roles）、付ける物を決めて（sync.plan）herdr に書く（sync.apply）。
    only を渡せば、その代表の clone の会社だけ（会社の形が替わったときのターンの終わりのフック。shape_hook.py）。(出す行の並び, 終了の値)。"""
    try:
        accounts_, workspaces_, companies, settings, notes = survey_companies(config_path, ports, only)
    except term.Error as e:
        return [f"止めた: {term.NAME} を読めない（{e}）"], 1
    notes += _sync_roles(companies, settings, ports, dry_run)
    ops, why = sync.plan(companies, len(accounts_) > 1)
    ws_ops = sync.workspace_ops(companies, workspaces_)
    moves = sync.flow_order(*_flow_inputs(companies, workspaces_))
    notes += why
    none = [] if ops or ws_ops else ["付け直す部署は無い（属性を持つ部署が無い）"]
    lines = [sync.workspace_line(o) for o in ws_ops] + [_op_line(o) for o in ops] + [sync.order_line(o) for o in moves]
    if dry_run:
        return notes + lines + none, 0
    done = sync.apply_workspaces(ws_ops, ports.term) + sync.apply(ops, ports.term) + sync.apply_order(moves, ports.term)
    return (notes + [f"{line}  {r['status']}" + (f"（{r['detail']}）" if r["detail"] else "") for line, r in zip(lines, done)] + none,
            1 if any(r["status"] != "done" for r in done) else 0)


def _flow_inputs(companies, workspaces_):
    """sync.flow_order に渡す (作業場の並び, 場所 → (席のキー, 部署の名前), ルート → 受け持ちの並び)。会社の並び（tree.build）の部署を使い、並べるのは
    その会社の作業場だけ（ほかの作業場は会社の印を外して渡す。--sync の only で絞った会社のほかは動かさない）。"""
    roots = {os.path.realpath(c["root"]): c for c in companies}
    seats = {os.path.realpath(d["path"]): (d.get("seat"), d["attrs"].get("name")) for c in companies for d in c["departments"] if d.get("path")}
    listed = [w if w.get("repo_root") and os.path.realpath(w["repo_root"]) in roots else {**w, "repo_root": None} for w in workspaces_]
    return (listed, lambda path: seats.get(os.path.realpath(path), (None, None)),
            lambda root: roots[os.path.realpath(root)].get("skills") or [])


def _sync_roles(companies, settings, ports, dry_run):
    """会社の形の役を、今いる部署と本社の属性に写し直す（会社の形を変えたら、--sync 1 回で全部の場所に行き渡らせる。--ask・
    --reorg --role を待たない）。属性 company.role が役の前の名前（former_names）なら今の名前に、company.fresh は役の context に（new なら付け、carry なら消す）。
    companies の中の属性も書き換え、続く表示がそれを使う。出す行の並び。会社の形に無い役の場所は触らない。--dry-run なら書かずに、
    書く物だけを出す。"""
    out = []
    for c in companies:
        info = tree.read_info(c["root"], settings, ports.git)
        shape = role.load(info["path"], info["text"])
        for d in c["departments"]:
            got = shape["roles"].get(role.current(shape, d["attrs"].get("role")))
            changes, why = {}, []
            if got and d["attrs"].get("role") != got["name"]:
                changes["role"] = got["name"]
                why.append(f"company.role {d['attrs'].get('role')} → {got['name']}（役の前の名前を今の名前に）")
            want = role.FRESH if got and got["context"] == role.NEW else None
            if got and (d["attrs"].get("fresh") or None) != want:
                changes["fresh"] = want
                why.append(f"company.fresh {d['attrs'].get('fresh') or '-'} → {want or '（消す）'}（役 {got['name']} の context を写す）")
            if not changes:
                continue
            line = f"{c['name']} {d['attrs'].get('name') or d['branch'] or d['path']}: " + "、".join(why)
            if not dry_run:
                try:
                    provision.mark(d["path"], c["root"], changes, ports.git)
                except (gitx.GitError, OSError) as e:
                    out.append(f"{line}  書けなかった（{e}）")
                    continue
            d["attrs"] = {k: v for k, v in {**d["attrs"], **changes}.items() if v}
            if "role" in changes:
                d["role"] = got["name"]
            d["seat"] = role.seat(d["attrs"], info["skills"], shape)
            out.append(line)
    return out


def _op_line(o):
    shown = [f"名前 {o['label']}" if o["label"] else "名前はそのまま", f"表示名 {o['display_agent'] or '-'}",
             f"題名 {o['title'] or '-'}", "札 " + ("、".join(f"{k}={v}" for k, v in o["tokens"].items()) or "-")]
    return f"ペイン {o['pane']}: " + "  ".join(shown)


def _clone_of(cfg, name, ports):
    """--check の --repo が、設定の [[repos]] の名前でも source でもない、git の中のフォルダなら、その代表の clone の repo（[[repos]] の
    物か、無ければ最小の repo。config.repo_at）。そうでなければ None（今までどおり pick_repo で選ぶか止める）。"""
    if not name or not os.path.isdir(os.path.expanduser(name)):
        return None
    try:
        config.pick_repo(cfg, name)
        return None
    except config.ConfigError:
        pass   # 名前でも source でもないので、フォルダから代表の clone を引く
    root = ports.common_of(os.path.expanduser(name))
    return config.repo_at(cfg, root, ports.origin) if root else None


def _check(cfg, ports, task=None, lead=None):
    """--check。task は部署の回の前提だけを確かめるか（省けば、設定に [[repos]] が無いとき）。lead は注記の先頭に置く 1 行。"""
    if task is None:
        task = not cfg.repos
    # 先に要るツールの段（tiers）を点検する。足りなければ、その案内を出して止まる（設計 4.11）。部品が無ければ注記にして、今までの確かめを続ける
    tier_notes = []
    try:
        tiers = ports.tiers(list(dict.fromkeys(a.command for a in cfg.accounts)))
    except tierx.TierError as e:
        # 段の点検を回せないまま「足りない物は無い」と言わない（herdr が動いていなくても通ってしまう）
        print(f"足りない物（要るツールの段の点検を回せない）:\n- {e}")
        return 2
    if tiers is not None and task:
        tiers, no_gh = tierx.without_gh(tiers)
        tier_notes += [f"{line}（部署の回には要らない。PR を開く回と、gh を使う役の部署に要る）" for line in no_gh]
    if tiers is not None and not tiers.get("ok"):
        print("足りない物（要るツールの段の点検。手で入れてから --check を打ち直す）:")
        print("\n".join(tierx.report(tiers)))
        return 2
    problems, notes = ports.preflight(cfg, task=task)
    # origin/HEAD が無い元の clone は、会社の形を作業ツリーから読む（止めずに直し方を出す）
    heads = [n for n in dict.fromkeys(tree.head_note(r.source, ports.git) for r in cfg.repos if r.source) if n]
    notes = list(cfg.notes) + tier_notes + notes + heads
    rent = rentx.missing_note()
    if rent:
        notes.append(rent)
    if lead:
        notes.insert(0, lead)
    elif not cfg.repos:
        notes.insert(0, "設定に [[repos]] が無いので、部署の回（--task・--ask・--land）の前提だけを確かめた"
                        "（PR を開く回も使うなら python3 dispatch.py --init --repo OWNER/NAME --source <代表の clone> で下書きを作る）")
    for acc in cfg.accounts:
        try:
            ports.list_sessions(acc.config_dir)
        except chat.Error as e:
            problems.append(f"アカウント {acc.name}: {e}（開いている会話を読む {chat.LIST_COMMAND} が通らない。{chat.NAME} を新しくする）")
    shown = _overview(cfg.accounts, ports)
    if shown:
        notes += accounts.overview_lines(shown)
    print("\n".join(notes))
    if problems:
        print("足りない物:")
        print("\n".join(f"- {p}" for p in problems))
        return 2
    print("始める前の確かめ: 足りない物は無い")
    return 0


# 代表の clone の、git が追わないファイルのうち、PR ごとの clone へ写す候補（環境変数・手元だけの設定）
LOCAL_FILE = re.compile(r"(^|/)\.env[^/]*$|\.local(\.[^/]+)?$")


def _init(a, ports):
    if not (a.repo and a.source):
        print("止めた: --init には --repo OWNER/NAME と --source <代表の clone> が要る")
        return 2
    path = config.path_of(a.config, os.environ)
    if os.path.exists(path):
        print(f"設定はもうある: {path}（上書きしない。足すなら手で書く）")
        return 1
    source = os.path.abspath(os.path.expanduser(a.source))
    origin = ports.origin(source)
    if origin != a.repo:
        # --check も同じ所（元の clone が、このリポジトリの clone でない）で止まる。書く前に知らせる
        print(f"止めた: --source の {source} は " + (f"origin が {origin} の clone で" if origin else "origin の在る git の clone でなく")
              + f"、--repo の {a.repo} と合わない（--repo に origin の OWNER/NAME を渡すか、そのリポジトリの clone を --source に渡す）")
        return 2
    local = [f for f in ports.git.ignored_files(source) if LOCAL_FILE.search(f)]
    second = os.path.join(os.path.dirname(path), "dispatch-second-prompt.md")
    home = ports.env.get("HOME") or os.path.expanduser("~")
    seen = chat.config_dirs(home)
    q = json.dumps
    lines = [
        "# works の dispatch の設定（--init が書いた下書き）。直したら --check で確かめる。",
        "# フィールドの書き方: works-dispatch の skills/dispatch/references/setup.md の「初めて」と「アカウントの書き方」（前提の訳は docs/prerequisites.md）",
        "",
        "limit_percent = 95                      # 週か 5 時間の使用率がこれに達したアカウントは使わない",
        '# limits_dir = "~/.cache/claude-limits"   # アカウントごとの使用率の控え（<name>.json）。無ければ使用率は見ない',
        "",
        *chat.accounts_draft(seen),
        "",
        "[[repos]]",
        f"repo = {q(a.repo)}",
        f"second_prompt_file = {q(second)}   # 2 ターン目に送る文。空のままだと --check が止める。後ろに /catchup の調べを引き継ぐ一言を足して送る",
        f"source = {q(source)}   # 代表の clone。ブランチごとの worktree はここから作る（置き場は {term.NAME} の worktrees.directory）",
        "copy_files = [   # git が追わない手元だけのファイル。代表の clone で見つかった候補",
        *[f"  {q(f)}," for f in local],
        "]",
        '# copy_from = "<フォルダ>"   # copy_files を写す元。省けば代表の clone から',
        '# gh_user = "<ログイン名>"   # gh の有効なアカウントでこのリポジトリを読めないときだけ',
        "",
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    if not os.path.exists(second):
        open(second, "w", encoding="utf-8").close()
    print(f"書いた: {path}")
    print(f"2 ターン目の文: {second}（空。送りたい文を書く）")
    print("次: python3 dispatch.py --check")
    return 0


# 会社の形の下書き（--init-company）。フィールドの読み手は nodes/tree.py（name・description・skills）・nodes/role.py（gh_user・roles）・
# nodes/land.py（land）。名前は herdr の画面で読む物から決めた日本語（持ち主 2026-10-16。会社らしい名前・英語はやめた）:
# 役は 窓口・担当（受け持ちごとに keep）・作業（一度きり）・相談 の 4 つで、[[roles]] に書くのは 担当・作業・窓口（窓口は代表の clone の
# 会話で、組織の決まりを届けるために役の本文を持つ。相談は持ち主が直接話す会話で、会社ごとに要るときに足す）。受け持ちは会社ごとに
# 違うので、例を 1 つだけ <…> の置き字で書く
COMPANY_DRAFT = """# 会社の形: このリポジトリで部署（作業ごとの会話）を立てるときの、会社の名前・役・gh のアカウント・メインブランチへの入れ方。
# 読むのは works-dispatch（--tree・--task・--ask・--deliver・--land と、役を足すフック）。--init-company が書いた下書き。
# 書き方: works-dispatch の skills/dispatch/references/roles.md（役）と references/land.md（メインブランチに入れる）。
# 置き場は 2 つ。リポジトリの中（.claude/company.toml）なら commit すると同じリポジトリを使う人に効く。commit しない物は、
# dispatch の設定の置き場の companies/ に置く（--init-company --local）。両方に在れば、リポジトリの中の物を読む。
# <…> は置き字なので、受け持ちの名前と中身に直す（受け持ちを増やすなら、[[skills]] の項目を写して足す）。
# 役の本文の決まり（ブランチの名前・試験の回し方・メインブランチへの入れ方）は既定の例なので、このリポジトリの決まりに合わせて直す。

name = {name}   # 会社の名前（--tree と --ask の「会社/役」に出る。{term} ではリポジトリの親の作業場の名前になる）
description = {description}   # この会社が受ける仕事
gh_user = {gh_user}   # 部署の会話の gh が使うアカウント{gh_note}
default_role = "作業"   # --task で --role を省いたときの役
desk_role = "窓口"   # 本社で持ち主と話す会話の役（--desk で --role を省いたときの役）
# どの役の部署の会話にも、役の本文の前に足す会社の共通の本文（試験の回し方など、役をまたいで同じ決まり。役ごとに写すと、直すときに
# 全部の役を同時に直す要が出る）。本社の窓口の会話には足さない
# shared_instructions = "<どの部署にも効かせる決まり>"   # 長くなれば、ほかの役の本文と同じく 3 つの引用符で囲んで複数行で書く

# 受け持ち。1 つの受け持ちに担当が always で 1 人つき、担当の部署の名前（{term} の作業場の名前）は受け持ちの name にする。
# 担当の会話の始まりに、部署の名前と同じ name の受け持ちの description が足される。--tree にも出る
[[skills]]
id = "duty"
name = "<受け持ち>"
description = "<受け持ちのフォルダかプラグイン>の直し"
role = "担当"
# model = "sonnet"   # この受け持ちの部署を起動するときの --model（役の model より優先する。省けば役の値、それも無ければアカウントの既定）
# effort = "low"     # この受け持ちの部署を起動するときの --effort（役の effort より優先する。書ける値は役の effort と同じ）
# settings = {{ promptCacheTtl = "5m" }}   # この受け持ちの部署の --settings に、役の [roles.settings] の上から重ねる {chat} の設定
# lifetime = "on-demand"   # この受け持ちの部署の寿命（per-ask・on-demand・always。省けば役の lifetime）。on-demand は頼まれたときに立て、手が空いたら畳む
# rent_or_buy = false   # この受け持ちの部署に借りるか買うかの判断（キャッシュの寿命の前に短い文を送る keepalive と、費用で決める compact）を効かせない（省けば効かせる）

[[skills]]
id = "one-off"
name = "一度きりの作業"
description = "受け持ちの無い一度きりの作業と、担当が並べて進めたい作業を、一時の作業の部署で受ける"
role = "作業"

# 受け持ちで分けるか、役で分けるか: 受け持ち（上の [[skills]]）は、同じフォルダの直しを 1 人の担当の下で順番に進める形。受け持ちの
# model・effort・settings は、部署の名前が受け持ちの name と同じ部署と、「<受け持ち>：<何をするか>」の名前の一度きりの部署に効く。
# 同じ名前の部署は 1 つしか立たないので、受け持ちの名前の部署への頼みは同時に走らず、1 件ずつ順に進む。
# 一度きりの仕事を並べて走らせ、仕事の種類（レビュー・直し・下調べなど）でモデルや effort を替えたいなら、受け持ちと担当を消し、
# 種類ごとに役を足す（--role で選び、部署の名前は自由に付ける）。例（# を外して使う。役の本文には、下の作業と同じく納品と --done まで書く）:
# [[roles]]
# name = "レビュー"   # 読むだけの仕事。判断が要るので opus
# model = "opus"
# effort = "medium"
# instructions = "頼まれた所を読んでレビューする。ファイルを直さず、commit もしない。…"
# deliver = ["結論", "差分", "試験", "残った疑問", "ブランチ"]
# [[roles]]
# name = "写し"       # 頼みに書いた機械的な変更だけをする仕事。安いモデルでよい
# model = "sonnet"
# effort = "medium"
# instructions = "頼みに書いた変更だけをする。頼みに無い判断が要る所は変えずに、納品の残った疑問に書く。…"
# deliver = ["結論", "差分", "試験", "残った疑問", "ブランチ"]

# 役。部署を立てるときに --role で選ぶ（省けば default_role）。instructions は、その役の会話の頭に毎回足す役の本文
# deliver は納品する要約の必須の項目。担当と作業はコードの直しなので、差分と試験を返させる（省くと既定の 結論・決め手・残った疑問・ブランチ
# になり、決め手に原典の URL を求める。調べものの役に向く）
# 担当: 受け持ちごとに always で 1 人（lifetime = "always" なので、--persistent を付けなくても always の部署で立つ。片付けで畳まれず、次の頼みを
# 同じ部署で受ける）。context = "new" なので、頼みごとに空の会話で受ける（前の頼みを納品し終えていれば、--ask が新しい頼みを打つ前に
# /clear を打つ。always の値打ちは記憶ではなく受け持ちごとの席〔順番を 1 本にする・宛先の名前・決まった窓〕で、前の頼みの記憶は
# 太るうえ、覚えた中身で書き直すと、ほかの部署が入れた行を消す）。引き継ぐなら context = "carry"（省いたときの値）。
# 最初の頼みと一緒に立てるなら --ask {plain}/担当 --task <受け持ち> --branch <ブランチ> --text <頼み>。
# 頼み無しで立てるなら --task <受け持ち> --branch <ブランチ> --role 担当 --brief <頼みのファイル>（--task には --brief が要る）
[[roles]]
name = "担当"
instructions = {duty}
deliver = ["結論", "差分", "試験", "残った疑問", "ブランチ"]
lifetime = "always"
context = "new"
# model = "opus"   # 部署を起動するときの --model（省けばアカウントの既定）
# effort = "high"  # 部署を起動するときの --effort（low・medium・high・xhigh・max・ultracode。inherit なら頼んだ会話と同じ。省けば既定）
# deliver_check = "<納品の検査のコマンド>"   # --deliver が部署の作業場のルートで走らせ、0 以外で終われば送らない（省けば検査しない）
# 部署の会話にだけ効かせる {chat} の設定（--settings で渡す。要らないプラグインを切るなどもここ）。
# autoMode.allow は、自動の権限の判定（auto mode の classifier）の組み込みの拒否への例外を文で書く（"$defaults" で組み込みの
# 決まりを残す）。--land はメインブランチへ fast-forward するので「Merge Without Review」として止められることがある。人のレビューの代わりに
# 会社の形の [land] のゲートを通す決まりであることを書いて、止めないようにする（https://code.claude.com/docs/en/auto-mode-config）
[roles.settings]
autoMode = {{ allow = ["$defaults", {land_allow}] }}
permissions = {{ deny = ["AskUserQuestion", "EnterWorktree"] }}   # 部署の画面は誰も見ていないので画面で問わせない。作業場からも出さない
# enabledPlugins = {{ "<プラグイン>@<マーケットプレイス>" = false }}

# 作業: 一度きりの作業をする一時の部署（頼みごとに立ち、納品して --done を打つと、そのターンの終わりに畳まれる）。
# --done は、ブランチがメインブランチに入っていない部署を断る（commit の無い部署は入っているとみなす）。[land] が none の会社で
# 入れるのが人なら、断られた部署は --done を打たずに止まり、入った後に窓口が --retire で畳む（本文にそう書いてある）
[[roles]]
name = "作業"
instructions = {work}
deliver = ["結論", "差分", "試験", "残った疑問", "ブランチ"]
[roles.settings]
autoMode = {{ allow = ["$defaults", {land_allow}] }}
permissions = {{ deny = ["AskUserQuestion", "EnterWorktree"] }}   # 部署の画面は誰も見ていないので画面で問わせない。作業場からも出さない

# 相談: 持ち主が直接話して考えを詰める会話。要る会社だけ # を外して足す。always で、話の流れを引き継ぐ（context は省いて carry）
# [[roles]]
# name = "相談"
# instructions = "持ち主と話して考えを詰める。決まったことは頼みに書き直して窓口に渡す。"
# lifetime = "always"

# 窓口: 持ち主と話して頼みを配る、代表の clone の会話（部署ではない）。部署に頼む会話は、最初から本社（代表の clone）で起動して
# --desk で窓口にする（ほかの clone の会話から頼むと、頼みの本文とその納品はその clone の受付箱に置かれる。後で窓口を本社に移しても、
# その clone から頼んだ頼みが全部納品されるまでは、その clone を消さない。消すと、まだ届いていない納品の置き場が無くなる）。
# 窓口の会話から --desk を打つと、この役の本文が次の会話の始まりから足される（組織の決まりを窓口に届けるため。コメントの決まりは、どの会話にも届かない）。本文を替えると、会話を引き継いで
# いる部署と窓口にも、次のターンの頭に今の本文が足される
# 役の名前を替えるときは、前の名前を former_names = ["<前の名前>"] に書く（前の名前で宛てた頼みと、前の名前を持つ部署が今の役に当たる）
[[roles]]
name = "窓口"
instructions = {desk}

# 部署の成果をメインブランチに入れる決まり（--land）。none は何もしない（入れるのは人）。
# pr はメインブランチへの PR を出して止まる。ff-after-ci はゲート（gate。CI のブランチの形か check）が緑ならメインブランチを fast-forward する。
# none 以外にしたら、担当と作業の本文の「push し」を「--land <自分の部署の名前> でメインブランチに入れ」に替える
[land]
mode = "none"
# gate = "check"
# check = "<手元の検証のコマンド>"

# 組織の決まり（この会社の作り方。部署の会話には届かないので、部署に守らせることは役の本文にも書く）
# - 役は 4 つ: 窓口（持ち主と話して頼みを配る、本社の会話。--desk で名付ける）・担当（受け持ちごとに always で 1 人）・作業（一度きりの
#   作業をする一時の部署）・相談（持ち主が直接話して考えを詰める会話。要る会社だけ [[roles]] に足す）。同じ受け持ちの直しは担当の
#   下で順番に進むので、同じファイルの取り合いにならない。
# - 名前は日本語で、{term} の画面で読んで分かる短い言葉にする。担当の部署の名前は受け持ちの名前（例: 「<受け持ち>」）、作業の部署の
#   名前は「<受け持ち>：<何をするか>」（作業場の名前になるので 12 字くらいまで）。会社の名前は {term} の親の作業場にだけ出るので、
#   部署の名前には付けない。
# - ブランチの名前は英小文字とハイフンにする（git と GitHub の URL で崩れないため）。直しは fix/…、足すものは feat/…、調べや下書きは work/…。
# - 担当への頼みは部署の名前で宛てる（--ask <受け持ち>。部署の名前は役より先に当たる）。担当がまだ居ない受け持ちは
#   --ask {plain}/担当 --task <受け持ち> --branch <ブランチ> --text <頼み> で、最初の頼みと一緒に立てる。頼んだ部署が頼み元になり、納品はそこに返る。
# - 担当の受け持ちの中の作業は、担当に頼む（窓口が作業に直に頼まない。同じファイルを 2 つの部署が触ると、後から入れた方が前の変更を消す）。
# - 納品の後に判断が要ることが出たら、画面に書いて止まらず、もう一度納品のコマンド（--deliver に --again を付ける）で返す（画面にだけ書いた問いは届かない）。
"""
# 役の本文の共通の終わり。組織の決まりのうち、部署が守ることを部署の会話に届ける（コメントは部署に届かない）
DRAFT_RETURN = ("済んだら作業のブランチに push し、要約を納品のコマンド（--deliver）で頼み元に返す。納品の後に判断が要ることが出たら、"
                "画面に書いて止まらず、もう一度納品のコマンドで返す（--again を付ける。画面にだけ書いた問いは頼み元に届かない）。")
DRAFT_BRANCH = "ブランチの名前は英小文字とハイフンにし、直しは fix/…、足すものは feat/…、調べや下書きは work/… にする。"
# 自動の権限の判定への例外（役の settings の autoMode.allow）。--land は、ゲートを通した後にメインブランチを fast-forward して push する
DRAFT_LAND_ALLOW = ("この部署が works-dispatch の --land（dispatch.py --land <自分の部署の名前>）で自分のブランチをメインブランチに入れること。"
                    "メインブランチへの取り込みは、人のレビューの代わりに、会社の形（.claude/company.toml）の [land] のゲートを通してから"
                    "fast-forward する決まりで、持ち主がこの会社の部署に許している。")
# 自動の権限の判定に止められたときの手。打ち直しで判定を回り込まず、窓口に入れてもらう
DRAFT_DENIED = ("--land が自動の権限の判定（auto mode）に止められたら、打ち直さず、窓口に --land <部署の名前> を打って入れてほしいと"
                "--ask <会社の名前> で頼み、その受付を納品の残った疑問の担当者に書いて返す（残った疑問に書くだけでは窓口に届かない）。")
# commit に足す物の決まり。git add -A は、試験や検証が作った生成物（__pycache__ など。.gitignore の無いリポジトリ）までメインブランチに入れる
DRAFT_COMMIT = "commit に足すのは自分が触ったファイルだけにする（git add -A や git add . をしない）。"
DRAFT_DUTY = ("受け持ちを keep で預かる。自分の受け持ちは部署の名前で決まる。keep なので、作業場は同じまま、頼みごとに git fetch origin "
              "してから origin の既定のブランチからブランチを切って作業する。" + DRAFT_BRANCH + "ブランチを切った後、触るファイルをメインブランチから読み直してから"
              "書く（前の頼みで覚えた中身で書かない。覚えた中身で書くと、ほかの部署が入れた変更を消してしまう）。" + DRAFT_COMMIT + "並べて進めたい作業は作業に頼む"
              "（--ask {company}/作業 に --task <受け持ち>：<何をするか> --branch <ブランチ> を添える）。試験は触った所の物だけを回す。"
              + DRAFT_RETURN + DRAFT_DENIED + "受け持ちの外のファイルを変える必要が出たら、その受け持ちの担当に部署の名前で頼む（--ask <受け持ち>）。")
# 畳む部署の畳み方。書かないと、納品した部署が会話を残したまま並び続ける（2026-10-19 の works-factory の会社で、持ち主が指摘して足した）
DRAFT_DONE = ("納品し、ブランチがメインブランチに入ったら（commit の無い頼みなら納品の後に）、--done を打ってターンを終える。--done が"
              "「ブランチがメインブランチに入っていない」と断れば、git fetch origin してから打ち直し、それでも断れば --done を打たずに止まる"
              "（ブランチがメインブランチに入った後に窓口が --retire で畳む）。")
DRAFT_WORK = ("一度きりの作業をする。頼まれた所を直す。" + DRAFT_BRANCH + DRAFT_COMMIT + "試験は触った所の物だけを回す。" + DRAFT_RETURN
              + DRAFT_DENIED + DRAFT_DONE)
DRAFT_DESK = ("持ち主と話し、仕事を頼みに変えて部署に配る。自分ではファイルを直さない。受け持ちの中の仕事は、その担当に部署の名前で頼む"
              "（--ask <受け持ち>）。担当がまだ居ない受け持ちは --ask {company}/担当 --task <受け持ち> --branch <ブランチ> --text <頼み> で立てる。"
              "受け持ちの無い一度きりの作業だけを作業に頼む（--ask {company}/作業 --task <受け持ち>：<何をするか> --branch <ブランチ>）。"
              "担当の受け持ちの中の作業を、作業に直に頼まない（同じファイルを 2 つの部署が触ると、後から入れた方が前の変更を消す）。"
              + DRAFT_BRANCH + "担当と作業は、メインブランチに入れる決まり（会社の形の [land]）が none でなければ、自分で --land してメインブランチに入れてから"
              "納品する（窓口から頼まなくてよい）。担当や作業が「--land が自動の権限の判定に止められた」と返したら、窓口から "
              "--land <部署の名前> を打って入れる。納品は要約を読んで持ち主に伝える。納品の後も残っている部署（--clean の一覧に出る）は、"
              "ブランチがメインブランチに入っていれば --retire <部署の名前> で畳む。")


def _draft_gh_user(ports, candidates):
    """下書きに書く gh_user と、その行の注記（1 行）。candidates は (アカウント, 注記) の先に試す並び（設定の [[repos]] の gh_user・origin の
    持ち主）で、鍵を `gh auth token --user` で取り出せる最初の物を書く（部署の会話は gh_user の鍵をそれで取り出す。origin の持ち主が組織なら
    取り出せないので飛ばす）。どれも取り出せなければ gh の今のアカウント。それも読めないか鍵を取り出せない（鍵を GH_TOKEN で渡している人など）
    なら書かず (None, 訳)。注記は TOML の 1 行の注記の中に置くので、gh の誤りの文は 1 行に畳む（複数行のまま入れると、2 行目が # の外に
    出て TOML が壊れる）。2026-10-19 に works-factory の会社で、gh の今のアカウント（会社の仕事のアカウント）が入り、リポジトリの持ち主の
    アカウントに手で直した。"""
    def one_line(e):
        return " ".join(str(e).split())[:160]
    for user, note in candidates:
        if not user:
            continue
        try:
            ports.gh.env_for(user, dict(ports.env))
        except ghx.GhError:
            continue   # 鍵を取り出せない候補（組織の名前など）は書けないので次へ。どれも駄目なら下の今のアカウントの訳を注記に出す
        return user, note
    try:
        user = ports.gh.login()
    except ghx.GhError as e:
        return None, f"。gh の今のアカウントを読めなかったので書かない（{one_line(e)}）。書かなければ、その人の今の gh の設定で動く"
    try:
        ports.gh.env_for(user, dict(ports.env))
    except ghx.GhError as e:
        return None, (f"。gh の今のアカウント {user} の鍵を gh auth token --user で取り出せないので書かない（GH_TOKEN で鍵を渡している"
                      f"ときなど。{one_line(e)}）。書かなければ、その人の今の gh の設定で動く")
    return user, ("（--init-company を打った時の gh の今のアカウント。リポジトリの持ち主のアカウントと違うなら直す）"
                  if any(u for u, _ in candidates) else "（--init-company を打った時の gh の今のアカウント）")


def _init_company(a, ports, cwd):
    """--init-company。会社の形の下書きを、リポジトリの中の .claude/company.toml（--local なら設定の置き場の companies/）に書く。
    在れば上書きしない。commit はしない（するかは利用者が決める）。"""
    place = os.path.expanduser(a.repo) if a.repo else cwd
    root = ports.common_of(place) if os.path.isdir(place) else None
    if not root:
        print(f"止めた: {place} が git のリポジトリでない（--repo に代表の clone のパスを渡すか、その clone の中から打つ）")
        return 2
    settings = os.path.dirname(config.path_of(a.config, os.environ))
    path = tree.settings_info_path(settings, root) if a.local else os.path.join(root, *tree.INFO_FILE)
    if os.path.exists(path):
        print(f"会社の形はもうある: {path}（上書きしない）")
        return 1
    other = os.path.join(root, *tree.INFO_FILE) if a.local else tree.settings_info_path(settings, root)
    # 会社の名前は origin の OWNER/NAME の NAME（clone のフォルダの名前は、同じリポジトリの 2 つ目の clone で works-factory-co のように
    # 違う）。gh_user は設定の [[repos]] の gh_user、次に origin の持ち主を先に試す（2026-10-19 の works-factory の会社で両方を手で直した）
    origin = ports.origin(root) or ""
    owner, _, repo_name = origin.partition("/")
    try:
        configured = config.repo_at(config.load(a.config, os.environ, missing_ok=True), root, ports.origin).gh_user
    except config.ConfigError:
        configured = None   # 設定が読めなくても下書きは書ける（--check が設定の誤りを出す）。gh_user は origin の持ち主から先を試す
    gh_user, gh_note = _draft_gh_user(ports, [(configured, "（dispatch の設定の [[repos]] の gh_user）"),
                                              (owner if repo_name else None, "（origin のリポジトリの持ち主のアカウント）")])
    def q(v):
        return json.dumps(v, ensure_ascii=False)   # TOML の基本の文字列と同じ書き方
    company = repo_name or os.path.basename(os.path.normpath(root))
    text = COMPANY_DRAFT.format(term=term.NAME, chat=chat.NAME, name=q(company), description=q("<この会社が受ける仕事を 1 行で>"), gh_user=q(gh_user or ""),
                                gh_note=gh_note, plain=" ".join(company.split()), duty=q(DRAFT_DUTY.format(company=company)),
                                work=q(DRAFT_WORK), desk=q(DRAFT_DESK.format(company=company)),
                                land_allow=q(DRAFT_LAND_ALLOW))
    if not gh_user:
        text = text.replace('gh_user = ""', '# gh_user = "<ログイン名>"')
    tomllib.loads(text)   # 下書きは必ず TOML として読める形にする（読めなければ書かずに例外で止める。作り手の誤り）
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"書いた: {path}")
    if os.path.exists(other):
        print(f"注意: {other} にも会社の形が在る。読むのはリポジトリの中の物（origin の既定のブランチに commit された物が先）")
    where = "commit しない置き場に書いた。" if a.local else ""
    print(f"{where}名前・説明と、<…> の置き字（受け持ちの名前と中身）・役の本文を直す"
          + ("" if a.local else "。同じリポジトリを使う人にも効かせるなら commit する（commit しないなら --init-company --local で設定の置き場に書く）"))
    return 0


def _department_rows(cfg, repo, ports, found, notes, assume_stopped=()):
    """部署（--task が立てた worktree）の片付けの候補（clean.departments）。会話は全アカウントの一覧（終わった物も）で引く。
    メインブランチは origin の既定のブランチの手元の控え。ブランチが入ったかは orders.landed で見る（マージ済みの PR も入ったとみなす）。
    読めなければ、部署は並べない（消さない側に倒す）。assume_stopped の会話の id
    （sessionId か短い id）は、止まった物とみなす（--retire が、止める前に会話のほかに残す訳が無いかを見る）。"""
    try:
        listed = {acc.name: (acc, ports.list_sessions(acc.config_dir, include_done=True)) for acc in cfg.accounts}
        main = ports.default_branch(repo)
    except (chat.Error, ghx.GhError, gitx.GitError) as e:
        notes.append(f"部署の片付けを飛ばした（会話の一覧か既定のブランチを読めない: {e}）")
        return []

    def entry(acc, s):
        return {**s, "config_dir": acc.config_dir, **({"state": "stopped"} if {s.get("sessionId"), s.get("id")} & set(assume_stopped) else {})}

    def session_of(attrs, path):
        if attrs.get("session"):
            return next((entry(acc, s) for acc, items in listed.values() for s in items if s.get("sessionId") == attrs["session"]), None)
        # 長い id（company.session）が無い部署は、短い id（company.job。会話の一覧の id）で引く。job は前の裏の会話のまま残りうるので、
        # 部署の場所でほかの会話が動いていればそちらを返す（動いているとみなして畳まない）
        here = [entry(acc, s) for acc, items in listed.values() for s in items
                if s.get("cwd") and os.path.realpath(s["cwd"]) == os.path.realpath(path)]
        live = [s for s in here if s.get("state") not in clean.DONE]
        return next(iter(live), None) or next((s for s in here if s.get("id") == attrs.get("job")), None)

    def queued(path):
        common, place = ports.git.common_dir(path), ports.git.git_dir(path)
        return bool(common and place and wake.queued(deliver.inbox_of(common), place))

    merged = {}

    def landed(path):   # gh に問うことがあるので、部署の場所ごとに 1 度だけ
        if path not in merged:
            merged[path] = orders.landed(path, main, ports.attrs(path), ports.git, ports.gh)
        return merged[path]

    return clean.departments(found, ports.attrs, session_of, ports.is_clean,
                             lambda path: ports.unpushed(path, landed=lambda: landed(path)), landed, ports.head_sha,
                             source=repo.source, queued=queued)


DEPT_REASONS = {"persistent": "always の部署は畳まない", "running": "会話がまだ動いている", "dirty": "未コミットの変更が有る", "unpushed": "手元にしか無い commit か stash が有る",
                "not_merged": "ブランチがメインブランチに入っていない", "no_branch": "ブランチに乗っていない",
                "queued": "順番待ちに頼みが在る（待ち受けが渡す次の頼みを済ませてから畳む。会話が止まっていれば --nudge <部署> で戻す）"}


def _running_note(d, attrs, ports):
    """会話がまだ動いているので残す部署の訳に足す、段取りが止めるかを決める手がかり（ほかの訳の部署には足さない）。"""
    if d["reason"] != "running":
        return ""
    if attrs.get(wake.RETIRE_KEPT):
        return f"。終わりの印で畳もうとして残った: {attrs[wake.RETIRE_KEPT]}"
    if attrs.get(wake.FINISHED):
        return "。終わりの印が有る（このターンの終わりに畳む）"
    name = d["name"] or d["branch"]
    got = orders.leftover(d["path"], attrs, ports.git, ports.gh)
    if got is None:
        return ""
    if got[0] == "waiting":
        return f"。頼みは納品済みで、この部署が頼んだ返事を待っている（受付 {'・'.join(got[1])}）"
    if got[0] == "handed":
        return (f"。頼みは納品済みだが、ブランチがメインブランチに入っていない。この部署が頼みを受けてから出した頼みの答えがまだ出ていない"
                f"（受付 {'・'.join(got[1])}。--todo で追える。入れる手を預けたのでなければ --land {name}）")
    if got[0] == "unlanded":
        try:
            # 入れ先のブランチの先頭は GitHub が作った commit（マージの commit など）で手元に無いことがあるので、取ってから比べる
            parked = retire.parked_on(d["path"], d["pr_head"], d["branch"], ports.git, fetch=True)
        except gitx.GitError:
            parked = None   # origin を読めなければ、入れ損ねの訳のまま出す
        if parked == got[1]:
            return (f"。頼みは納品済みで、部署の先頭は origin の {parked} に入っている（手元の origin/{parked} の控えが古い。"
                    f"git fetch origin で揃う）。畳むなら --retire {name}")
        if parked:
            return (f"。頼みは納品済みで、部署の先頭は origin の {parked} に入っている（{got[1]} へはまだ）。"
                    + (f"入れるなら --land {name}。" if parked == d["branch"] else "") + f"入れずに畳むなら --retire {name}（push は要らない）")
        return (f"。頼みは納品済みだが、ブランチがメインブランチ（origin/{got[1]}）に入っていない（入れ損ねか、入れる手を待っている。消すと成果を失う）。"
                f"入れるなら --land {name}。入れずに畳むなら（頼みを取り下げたときなど）、ブランチを origin に push してから --retire {name}"
                "（ブランチは origin に残る）")
    return f"。頼みは納品済みで、終わりの印（--done）が無い。止めて畳むなら --retire {name}"


def _tool_places(repo, ports, apply):
    """機械のツールを走らせる一時の worktree（tools.place）を並べ、apply なら作った処理がもう居ない物を消す（tools.sweep。ツールを走らせる
    たびにも消す）。(消せなかった数, 消せる物が在ったか)。"""
    listed = [e for e in ports.git.listed_worktrees(repo.source) if tools.is_place(e["path"])]
    stale = set(tools.leftovers(listed))
    removable = False
    for e in listed:
        if e["path"] not in stale and (e["locked"] or "").startswith(tools.OWNER):
            print(f"ツールの一時の場所 {e['path']}  残す（ツールが走っている）")
            continue
        if e["path"] not in stale:
            # 鍵が無い（前の版が作った）か、ほかの訳の鍵: 走っているかを確かめられないので消さない。手で消すときも commit を失わない手順を添える
            got = tools.judge(e, ports.git, repo.source)
            print(f"ツールの一時の場所 {e['path']}  残す（" + ("鍵が無い" if e["locked"] is None else f"鍵の訳が「{e['locked']}」")
                  + "。ツールが走っているかもしれないので消さない。走っていなければ"
                  + (f"、{got['why']}ので中を見てから" if got["why"] else "")
                  + (f"、先に git -C {repo.source} update-ref {tools.KEPT_REF}{got['keep']} {got['keep']} で先頭の commit を残してから"
                     if got["keep"] else "")
                  + f" git -C {repo.source} worktree remove -f -f {e['path']} で消す）")
            continue
        got = tools.judge(e, ports.git, repo.source)
        removable = removable or not got["reason"]
        print(f"ツールの一時の場所 {e['path']}  " + (
            f"残す（作った処理はもう居ないが、{got['why']}。中を見て、要らなければ git -C {repo.source} worktree remove -f -f {e['path']}）"
            if got["why"] else "消せる（作った処理がもう居ない" + (f"。どのブランチにも無い先頭の commit を {tools.KEPT_REF}{got['keep']} に残してから消す"
                                                             if got["keep"] else "") + "）"))
    if not apply or not removable:
        return 0, removable
    done, bad = tools.sweep(repo.source, ports.git)
    for got in done:
        print(f"ツールの一時の場所 {got['path']} 消した" + (f"（先頭の commit を {tools.KEPT_REF}{got['keep']} に残した）" if got["keep"] else ""))
    for path, _, why in bad:
        print(f"ツールの一時の場所 {path} 消せなかった: {why}")
    return sum(1 for _, reason, _ in bad if reason != tools.DIRTY), True


def _boards_note(path, ports):
    """消せる場所に graphloops の盤面が在れば、写す先を添える注記（無ければ空の字）。"""
    got = clean.boards_of(path, ports.git)
    return f"（graphloops の盤面は {got[1]} に写してから消す）" if got else ""


def _clean(cfg, repo, apply, ports):
    try:
        listed = {acc.name: ports.list_sessions(acc.config_dir) for acc in cfg.accounts}
        found = ports.places(repo)
    except (chat.Error, term.Error) as e:
        print(f"止めた: {e}（開いている会話か元の clone の worktree を読めないので、何も消さない）")
        return 1
    notes = []
    depts = _department_rows(cfg, repo, ports, found, notes)
    dept_paths = {os.path.realpath(d["path"]) for d in depts}
    swept = landing.sweep_branches(repo, ports, found, apply)
    for d in depts:
        kept = len(clean.tmp_entries(chat.job_tmp(d["config_dir"], d["session"], ports.account_env))) if d["removable"] and d["session"] else 0
        print(f"部署 {d['name'] or '-'} {d['branch'] or '（ブランチ無し）'}  {d['state']}  "
              + (("消せる" + (f"（会話の一時の置き場の {kept} 件は、共通の .git の company/kept-tmp/ に写してから消す）" if kept else "")
                  + _boards_note(d["path"], ports))
                 if d["removable"] else f"残す（{DEPT_REASONS[d['reason']]}{_running_note(d, ports.attrs(d['path']), ports)}）"))
    if notes or swept:
        print("\n".join(notes + swept))
    failed, stale = _tool_places(repo, ports, apply)
    if apply:
        for d in (d for d in depts if d["removable"]):
            got = clean.retire(d, repo.source, provision.label(repo, d["branch"]), ports.term, ports.git, chat, ports.account_env)
            print(f"部署 {d['name'] or '-'} {'消した' if got['removed'] else '消せなかった'}" + (f": {got['detail']}" if got["detail"] else ""))
            failed += not got["removed"]
    found = [p for p in found if os.path.realpath(p.get("path") or "") not in dept_paths and not tools.is_place(p.get("path"))]
    removable = stale or any(d["removable"] for d in depts)
    cwds = {s.get("cwd") for items in listed.values() for s in items if s.get("cwd")}
    # 設定の [[repos]] に無い会社: PR の作業場は見ない（PR の状態を GitHub に問うのは、PR を開く回に使うリポジトリだけ）
    known = any(os.path.realpath(r.source) == os.path.realpath(repo.source) for r in cfg.repos)
    rows = _candidates(repo, ports, found, cwds, _changed(repo)) if known else []
    if not rows:
        if not depts:
            print(f"元の clone {repo.source} の worktree は無い" if known else
                  f"元の clone {repo.source} に部署は無い（設定の [[repos]] に無いので、PR の作業場は見ない）")
        if not apply and removable:
            print("消すには --clean --apply を付けて打ち直す")
        return 1 if failed else 0
    for r in rows:
        mark = ("消せる" + _boards_note(r["path"], ports)) if r["removable"] else f"残す（{r['reason']}{': ' + ', '.join(r['files']) if r['files'] else ''}）"
        print(f"{_where(r)}  {r['state'] or '-'}  {mark}")
    if not apply:
        if removable or any(r["removable"] for r in rows):
            print("消すには --clean --apply を付けて打ち直す")
        return 0
    for r in (r for r in rows if r["removable"]):
        got = clean.remove(r, repo.source, provision.label(repo, r["branch"]), ports.term, ports.git)
        print(f"{_where(r)} {'消した' if got['removed'] else '消せなかった'}" + (f": {got['detail']}" if got["detail"] else ""))
        failed += not got["removed"]
    return 1 if failed else 0


if __name__ == "__main__":
    # 前の版の置き場のパスで打たれたら、今入っている版で打ち直す（installed.py）
    hopped = installed.hop(__file__, sys.argv[1:])
    sys.exit(main() if hopped is None else hopped)
