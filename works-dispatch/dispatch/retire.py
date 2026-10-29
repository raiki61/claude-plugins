#!/usr/bin/env python3
"""--retire <部署>（retire）: tmp の部署の会話を止めてから、部屋（作業場・worktree・会話・手元のブランチ）を --clean と同じ決まりで片付ける。

tmp の部署は、納品してメインブランチに入れ終えた後も会話が生きたまま残り、--clean は「会話がまだ動いている」と見て残す。終わったかを機械が
推し量るのは難しいので、部署が自分で終わりの印（--done。属性 company.finished）を打ち、そのターンの終わりに待ち受け（wake_hook.py）が
このコマンドを会話から切り離して裏で走らせる。印の無い部屋は、段取りが --clean の一覧で残った訳を見て、止めると決めたらこのコマンドを打つ。

順:
1. 部署を名前で探す（--move と同じ deliver.find_target）。窓口・永続の部署は畳まない。
2. 止める前に確かめる: 受けた頼みを納品している・順番待ちに頼みが無い・--clean の部署の決まり（clean.departments）で、会話が止まったとみなしたときに
   残す訳が無い（未コミットの変更・手元にしか無い commit・メインブランチに入っていないブランチなど）。訳が有れば何も止めない。
   ただし、メインブランチに入っていないブランチでも、部署の先頭が origin のどれかのブランチに在る（同じ名前のブランチの先頭が同じか、
   ほかのブランチの先頭の祖先。origin に問い合わせて確かめる。parked_on）なら畳み、どのブランチに残っているかを出す。成果は origin のブランチに残る（取り下げた頼みの部署は、入れずにブランチを残せと頼まれる。--done は入れていない部署を断るので、
   頼み元が --retire で畳む。2026-10-20 に、origin に push 済みの取り下げた部署が「メインブランチに入っていない」で残った。受付 d28a74）。
3. 会話が動いていれば、窓の attach の画面をシェルに戻し（launch.to_shell。attach が開いたままだと会話を再開させる）、claude stop で
   止め、--move と同じ回数だけ止まったかを読み戻す。一覧に処理の番号（pid）の無い会話は、動く処理が無いので止まったとみなす。
4. --clean と同じ部品（clean.retire）で片付ける。

止められなかった・消せなかったときは、そのまま残し、残った訳を部署の属性 company.retire-kept に書く（--clean の一覧に出る）。
打ち直しや見直しの回りは持たない。片付けたか残したかは、会社の受付箱の台帳に kind retired で残す。
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ports import chat, term  # noqa: E402
import config  # noqa: E402
import gitx  # noqa: E402
import orders  # noqa: E402
from nodes import clean, deliver, launch, provision, wake  # noqa: E402

# 会話が止まったのを読み戻す回数（1 回ごとに ports.pause。--move と同じ）
STOP_LOOKS = 20


def retire(a, ports, cwd, rows, reasons):
    """--retire。rows は dispatch._department_rows、reasons は dispatch.DEPT_REASONS。終了の値（2 は確かめで断った）。"""
    common = ports.git.common_dir(cwd)
    try:
        cfg, _, _, _, companies, _, notes = orders.survey(a.config, ports)
        target = deliver.find_target(companies, gitx.root_of(common) if common else None, a.retire)
    except term.Error as e:
        print(f"止めた: {term.NAME} を読めない（{e}）")
        return 1
    except deliver.DeliverError as e:
        print(f"止めた: {e}")
        return 2
    company, dept = target["company"], target["department"]
    if dept is None or dept.get("head_office"):
        print("\n".join(notes + [f"止めた: 「{a.retire}」という部署が無い（畳むのは --task が立てた tmp の部署。窓口は畳まない）"]))
        return 2
    if cfg is None:
        print("\n".join(notes + ["止めた: 畳むには、読める dispatch の設定が要る（会話を止めるアカウントを読む）"]))
        return 2
    attrs, path = dept["attrs"], dept["path"]
    where = f"{company['name']}/{attrs.get('name') or dept['branch']}"
    repo = config.repo_at(cfg, company["root"], ports.origin)
    inbox = deliver.inbox_of(ports.git.common_dir(company["root"]))

    def row(assume_stopped=()):
        got = rows(cfg, repo, ports, ports.places(repo), notes, assume_stopped)
        return next((r for r in got if os.path.realpath(r["path"]) == os.path.realpath(path)), None)

    def kept(why, code=1):
        try:
            provision.mark(path, company["root"], {wake.RETIRE_KEPT: why}, ports.git)
        except (gitx.GitError, OSError):
            pass   # 属性に書けなくても、台帳と出力には残す
        deliver.log(inbox, {"kind": "retired", "at": ports.now(), "name": attrs.get("name"), "path": path, "status": "kept",
                            "detail": why})
        print("\n".join(notes + [f"部署 {where} は残した（{why}）"]))
        return code

    # 会話の id。長い id（company.session）が無い部署は短い id（company.job）で見分ける（clean.departments）
    talk = [attrs.get("session") or attrs.get("job")] if attrs.get("session") or attrs.get("job") else []
    try:
        r, before = row(), row(talk)   # before は、会話を止めた後の見立て
    except term.Error as e:
        return kept(f"worktree を読めない: {e}")
    ask = attrs.get("ask")
    if r is None or before is None:
        return kept("片付けの候補にならない（会話の属性 company.session も company.job も無いか、会話の一覧を読めない）", 2)
    if ask and attrs.get("delivered") != ask:
        return kept(f"納品していない頼み（受付 {ask}）が在る", 2)
    parked = None   # 入れずに origin に残したブランチ（メインブランチに入っていないが、origin に同じ先頭が在る）
    if before["reason"] == "not_merged":
        parked, why = on_origin(before, ports.git)
        if not parked:
            return kept(why, 2)
    elif not before["removable"]:
        return kept(reasons[before["reason"]], 2)
    if wake.queued(inbox, ports.git.git_dir(path)):
        return kept("順番待ちに頼みが在る（待ち受けが渡す次の頼みを済ませてから畳む）", 2)
    if r["reason"] == "running":
        for pane in dept["panes"]:
            if not launch.to_shell(pane["pane_id"], ports.term, ports.pause):
                return kept(f"窓 {pane['pane_id']} をシェルに戻せない（窓の前で動いている物を手で閉じてから --retire を打ち直す）")
        ok, said = ports.stop_session(r["config_dir"], r["session"])
        if not ok:
            return kept(f"会話 {r['session']} を止められない（{said}）")
        for _ in range(STOP_LOOKS):
            try:
                r = row()
            except term.Error as e:
                return kept(f"会話を止めた後に worktree を読めない: {e}")
            if r is None or r["reason"] != "running":
                break
            if not r.get("pid"):
                # 一覧に処理の番号が無い: 動く処理は無く、記録の state だけが working のまま残った（2026-10-19、2.1.303。予約した
                # 繰り返しの仕事〔session_cron〕を残して終わった会話は、claude stop の後も working と出続け、7 回残された）
                try:
                    r = row(talk)
                except term.Error as e:
                    return kept(f"会話を止めた後に worktree を読めない: {e}")
                break
            ports.pause()
        if r is None:
            return kept("会話を止めた後、片付けの候補に見えない")
        if wake.queued(inbox, ports.git.git_dir(path)):
            return kept("会話を止めたが、止める間に順番待ちに頼みが積まれた（部署の会話を起動し直すまで渡らない。--tree の部署の行に件数が出る）")
        same = r["pr_head"] == before["pr_head"] and r["branch"] == before["branch"]
        if not r["removable"] and not (parked and r["reason"] == "not_merged" and same):
            return kept(f"会話を止めたが、{reasons[r['reason']]}")
    if r["removable"]:
        parked = None   # 止める間にメインブランチに入った
    elif parked:
        # 止めるのを待つ間に origin のブランチが書き換わっていないかを、消す直前に問い直す（手元の控えとの比べでは分からない）
        parked, why = on_origin(r, ports.git)
        if not parked:
            return kept(f"会話を止めたが、{why}")
    got = clean.retire(r, repo.source, provision.label(repo, r["branch"]), ports.term, ports.git, chat, ports.account_env)
    if not got["removed"]:
        return kept(f"片付けられなかった: {got['detail']}")
    if parked:
        note = (f"ブランチ {parked} はメインブランチに入れずに origin に残した" if parked == r["branch"]
                else f"部署の先頭は origin の {parked} に入っている（"
                + ("手元の控えが古かった）" if parked == _main_of(path, ports.git) else "メインブランチへはまだ）"))
        got["detail"] = f"{note}。{got['detail']}" if got["detail"] else note
    deliver.log(inbox, {"kind": "retired", "at": ports.now(), "name": attrs.get("name"), "path": path, "status": "done",
                        "detail": got["detail"]})
    print("\n".join(notes + [f"部署 {where} を畳んだ" + (f"（{got['detail']}）" if got["detail"] else "")]))
    return 0


def on_origin(row, g):
    """メインブランチに入っていない部署の行（reason が not_merged）の先頭が、origin のどれかのブランチに在るか（parked_on）。
    (ブランチ, None) か (None, 残す訳)。手元の origin/* の控えは古いことがあるので、origin に問い合わせる。"""
    branch = row["branch"]
    try:
        there = parked_on(row["path"], row["pr_head"], branch, g, fetch=True)
    except gitx.GitError as e:
        return None, f"ブランチがメインブランチに入っておらず、origin のブランチを読めない（{e}）"
    if there:
        return there, None
    return None, (f"ブランチがメインブランチに入っておらず、origin のどのブランチにも手元の先頭 {(row['pr_head'] or '-')[:9]} が無い"
                  + f"。入れずに畳むなら、git push origin {branch} で手元の先頭を origin に残してから打ち直す")


def _main_of(path, g):
    try:
        return g.default_branch(path)
    except gitx.GitError:
        return None


def parked_on(path, sha, branch, g, fetch=False):
    """部署の先頭 sha を持つ origin のブランチ（先頭か、その祖先に sha が在る）。部署のブランチ branch が同じ先頭で在れば、それを先に
    返す。ほかはブランチの名前の順で、メインブランチは最後。無ければ None。origin を読めなければ GitError。fetch なら、手元に無い先頭を取ってから比べる（書く口）。
    部署の PR が main でなくほかの部署のブランチに入り（積み重ねた PR）、GitHub が head のブランチを消しても、成果はそのブランチに
    残る（2026-10-29、guided-resolver の #2240 が feat/design-doc-writing-form に入り、--retire が push を求めた。受付 5f175e）。
    squash で入った形（sha がどこからも辿れない）は見つからない。"""
    heads = g.remote_heads(path)
    if not sha:
        return None
    if branch and heads.get(branch) == sha:
        return branch
    if fetch:
        missing = sorted(b for b, top in heads.items() if not g.rev(path, top))
        if missing:
            g.fetch_heads(path, missing)
    main = g.default_branch(path)   # メインブランチは最後に見る（手元の origin/main の控えが古いと、入った部署もここへ来る）
    return next((b for b in sorted(heads, key=lambda b: (b == main, b))
                 if g.rev(path, heads[b]) and g.is_ancestor(path, sha, heads[b])), None)
