#!/usr/bin/env python3
"""--retire <部署>（retire）: 都度の部署の会話を止めてから、部屋（作業場・worktree・会話・手元のブランチ）を --clean と同じ決まりで片付ける。

都度の部署は、納品してメインブランチに入れ終えた後も会話が生きたまま残り、--clean は「会話がまだ動いている」と見て残す。終わったかを機械が
推し量るのは難しいので、部署が自分で終わりの印（--done。属性 company.finished）を打ち、そのターンの終わりに待ち受け（wake_hook.py）が
このコマンドを会話から切り離して裏で走らせる。印の無い部屋は、段取りが --clean の一覧で残った訳を見て、止めると決めたらこのコマンドを打つ。

順:
1. 部署を名前で探す（--move と同じ deliver.find_target）。窓口・常設の部署は畳まない。
2. 止める前に確かめる: 受けた頼みを納品している・順番待ちに頼みが無い・--clean の部署の決まり（clean.departments）で、会話が止まったとみなしたときに
   残す訳が無い（未コミットの変更・手元にしか無い commit・メインブランチに入っていないブランチなど）。訳が有れば何も止めない。
3. 会話が動いていれば、窓の attach の画面をシェルに戻し（launch.to_shell。attach が開いたままだと会話を再開させる）、claude stop で
   止め、--move と同じ回数だけ止まったかを読み戻す。
4. --clean と同じ部品（clean.retire）で片付ける。

止められなかった・消せなかったときは、そのまま残し、残った訳を部署の属性 company.retire-kept に書く（--clean の一覧に出る）。
打ち直しや見直しの回りは持たない。片付けたか残したかは、会社の受付箱の台帳に kind retired で残す。
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import claudex  # noqa: E402
import config  # noqa: E402
import gitx  # noqa: E402
import herdr  # noqa: E402
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
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
        return 1
    except deliver.DeliverError as e:
        print(f"止めた: {e}")
        return 2
    company, dept = target["company"], target["department"]
    if dept is None or dept.get("head_office"):
        print("\n".join(notes + [f"止めた: 「{a.retire}」という部署が無い（畳むのは --task が立てた都度の部署。窓口は畳まない）"]))
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

    try:
        r, before = row(), row([attrs["session"]] if attrs.get("session") else [])   # before は、会話を止めた後の見立て
    except herdr.HerdrError as e:
        return kept(f"worktree を読めない: {e}")
    ask = attrs.get("ask")
    if r is None or before is None:
        return kept("片付けの候補にならない（会話の属性 company.session が無いか、会話の一覧を読めない）", 2)
    if ask and attrs.get("delivered") != ask:
        return kept(f"納品していない頼み（受付 {ask}）が在る", 2)
    if not before["removable"]:
        return kept(reasons[before["reason"]], 2)
    if wake.queued(inbox, ports.git.git_dir(path)):
        return kept("順番待ちに頼みが在る（待ち受けが渡す次の頼みを済ませてから畳む）", 2)
    if r["reason"] == "running":
        for pane in dept["panes"]:
            if not launch.to_shell(pane["pane_id"], ports.herdr, ports.pause):
                return kept(f"窓 {pane['pane_id']} をシェルに戻せない（窓の前で動いている物を手で閉じてから --retire を打ち直す）")
        ok, said = ports.stop_session(r["config_dir"], r["session"])
        if not ok:
            return kept(f"会話 {r['session']} を止められない（{said}）")
        for _ in range(STOP_LOOKS):
            try:
                r = row()
            except herdr.HerdrError as e:
                return kept(f"会話を止めた後に worktree を読めない: {e}")
            if r is None or r["reason"] != "running":
                break
            ports.pause()
        if r is None:
            return kept("会話を止めた後、片付けの候補に見えない")
        if not r["removable"]:
            return kept(f"会話を止めたが、{reasons[r['reason']]}")
        if wake.queued(inbox, ports.git.git_dir(path)):
            return kept("会話を止めたが、止める間に順番待ちに頼みが積まれた（部署の会話を起動し直すまで渡らない。--tree の部署の行に件数が出る）")
    got = clean.retire(r, repo.source, provision.label(repo, r["branch"]), ports.herdr, ports.git, claudex, ports.account_env)
    if not got["removed"]:
        return kept(f"片付けられなかった: {got['detail']}")
    deliver.log(inbox, {"kind": "retired", "at": ports.now(), "name": attrs.get("name"), "path": path, "status": "done",
                        "detail": got["detail"]})
    print("\n".join(notes + [f"部署 {where} を畳んだ" + (f"（{got['detail']}）" if got["detail"] else "")]))
    return 0
