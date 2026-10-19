#!/usr/bin/env python3
"""provision ノード: ブランチごとの作業場（元の clone の git worktree と herdr の作業場）を、無ければ作り、有れば使い直す（設計書のセクション 3）。外に書く。

場所の鍵はブランチ。作る・並べる・開くは herdr アダプタ（herdr.py の worktrees・create_worktree・open_worktree）に任せ、ここは
「ブランチの場所を探す・作る・開く」の言葉だけで書く。
- 場所を探す: 元の clone の worktree のうち、そのブランチを開いている linked worktree。フォルダの名前では探さない。
  元の clone 自身がそのブランチを開いていれば、作らずに branch_busy（元の clone のブランチを勝手に替えない）。
- 無ければ作る: origin のそのブランチを取ってから、origin/<ブランチ> を元に worktree を作り、copy_files（git が追わない手元だけのファイル）を写す。
  置き場は herdr の既定に任せる。依存は入れない。
- 有れば使い直す: origin のそのブランチを取り、作業場が開いていなければ開く。
- どちらでも、手元のブランチが origin のブランチの祖先なら fast-forward だけする（/catchup はブランチを移るときも pull・merge をしないので、origin の今の
  head に揃えてから渡す）。祖先でなくても、HEAD が前に送った時の head（行の sent_head）のままで場所がきれいなら、作者の
  force-push なので `git reset --keep` で origin に揃える。それ以外（手元にしか無い commit が有る）は動かさず、注記に書く。
- fork の PR（head が別のリポジトリ）は origin にブランチが無いので作らず provision_failed。
- 最後に、herdr の worktree の並びにそのブランチの場所が在り、作業場が開いていて、checkout がそのブランチに居ることを読み戻してから返す。

サブエージェント（入口の --task）の場所は prepare_task が用意する。違いはその関数の説明に書いた。部署の属性（役・アカウント・会話の名前・
頼み元）は mark が、その場所の git の設定 company.<名前> に書く（会社の形の設計 4.2）。部署を立てる前には、refresh_shape が
origin の既定のブランチを取り直す（会社の形を読む前に。起動するときの設定と、立てた後に役を足すフックが同じ会社の形を読むように）。

issue から始めるとき（入口の --issue）に、issue に結んだブランチがまだ無ければ、link_branch が GitHub にブランチを作って issue に結ぶ
（gh issue develop。書く口）。作った後に issue に結んだブランチを読み戻して返す。

使い方: python3 nodes/provision.py --plan <plan の JSON> --number <番号> [--config <パス>] [--repo OWNER/NAME] [--out <パス>]
"""

import argparse
import os
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import ghx  # noqa: E402
import gitx  # noqa: E402
from ports import chat, term  # noqa: E402
import jsonio  # noqa: E402


def label(repo, branch):
    """herdr の作業場の名前: <リポジトリの名前>/<ブランチ>。人が見るためだけで、探すのには使わない。
    リポジトリの名前で始めるのは、issue の番号で始まるブランチでも、数字で始まらないようにするため（設計書のセクション 3）。"""
    return f"{repo.repo.split('/')[-1]}/{branch}"


def find(places, branch):
    """worktree の並び（herdr.worktrees）から、そのブランチの場所（linked worktree）を 1 つ。無ければ None。"""
    return next((p for p in places if p.get("linked") and p.get("branch") == branch and not p.get("prunable")), None)


def source_holds(places, branch):
    """元の clone 自身がそのブランチを開いているか。"""
    return any(not p.get("linked") and p.get("branch") == branch for p in places)


def would(row, places):
    """--dry-run の報告用: create（作る）・reuse（使い直す）・branch_busy・provision_failed（fork の PR）のどれか。
    issue でまだブランチが無い行（head が None）は create。"""
    if row.get("fork"):
        return "provision_failed"
    branch = row.get("head")
    if branch is None:
        return "create"
    if source_holds(places, branch):
        return "branch_busy"
    return "reuse" if find(places, branch) else "create"


def link_branch(repo, number, base, gh=ghx, env=None):
    """issue にブランチを結ぶ（GitHub に base からブランチを作る）。作った後に読み戻した、issue に結んだブランチの並びを返す。"""
    gh.issue_develop(repo.repo, number, base, env=env)
    return gh.issue_branches(repo.repo, number, env=env)


def _copy(repo, path):
    notes = []
    for rel in repo.copy_files:
        src = os.path.join(config.copy_root(repo), rel)
        if not os.path.isfile(src):
            notes.append(f"写すファイルが {config.copy_root(repo)} に無い: {rel}")
            continue
        dst = os.path.join(path, rel)
        if os.path.exists(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return notes


def prepare(row, repo, h=term, g=gitx):
    branch = row.get("head")
    out = {"number": row["number"], "branch": branch, "path": None, "pane": None, "workspace": None,
           "created": False, "status": "provision_failed", "detail": None}
    if row.get("fork"):
        out["detail"] = "fork の PR（head が別のリポジトリ）なので、origin にブランチが無く、作業場を作らない"
        return out
    if not branch:
        out["detail"] = "ブランチが決まっていない"
        return out
    notes = []
    try:
        g.fetch(repo.source, branch)
        places = h.worktrees(repo.source)
        if source_holds(places, branch):
            out.update(status="branch_busy", detail=f"元の clone {repo.source} がブランチ {branch} を開いている（ブランチを替えない。"
                                                     "元の clone を別のブランチへ移すか、そこで作業する）")
            return out
        place = find(places, branch)
        if place is None:
            made = h.create_worktree(repo.source, branch, f"origin/{branch}", label(repo, branch))
            out["created"] = True
            notes += _copy(repo, made["path"])
        else:
            made = h.open_worktree(repo.source, place["path"], label(repo, branch))
        moved = g.fast_forward(made["path"], branch)
        if moved == "local_only":
            sent_head = row.get("sent_head")
            if sent_head and g.head_sha(made["path"]) == sent_head and g.is_clean(made["path"]):
                # 手元の HEAD が前に送った時の head のまま（手元で積んだ commit ではない）で、origin の祖先でなくなった:
                # 作者が force-push した。場所がきれいなら origin に揃える（--keep は未コミットの変更と重なれば断る）
                g.reset_keep(made["path"], branch)
                notes.append(f"ブランチ {branch} は前に送った後に origin で書き換えられていた（force-push）ので、origin の head に揃えた")
            else:
                notes.append(f"ブランチ {branch} に手元にしか無い commit が有るので、origin の head へ fast-forward しなかった")
        seen = find(h.worktrees(repo.source), branch)
    except (gitx.GitError, h.Error, OSError) as e:
        out["detail"] = "／".join(notes + [str(e)])
        return out
    return _read_back(out, made, seen, branch, notes, g)


def _read_back(out, made, seen, branch, notes, g):
    """作った・開いた場所を、herdr の worktree の並び（seen）と git から読み戻して、out を ready にするか、外れを detail に書く。"""
    misses = []
    if seen is None or not seen.get("workspace"):
        misses.append(f"作った後の読み戻しで、ブランチ {branch} の場所の作業場が {term.NAME} に見えない")
    elif os.path.realpath(seen["path"]) != os.path.realpath(made["path"]):
        misses.append(f"作った後の読み戻しで、ブランチ {branch} の場所が {seen['path']}（{made['path']} のはず）")
    elif g.branch(made["path"]) != branch:
        misses.append(f"作った後の読み戻しで、{made['path']} のブランチが {g.branch(made['path'])}（{branch} のはず）")
    if misses or not made.get("pane_id"):
        out["detail"] = "／".join(notes + (misses or ["作業場のペインが返らなかった"]))
        return out
    out.update(path=made["path"], pane=made["pane_id"], workspace=seen["workspace"], status="ready",
               detail="／".join(notes) or None)
    return out


def prepare_task(row, repo, default_branch, h=term, g=gitx):
    """サブエージェント（入口の --task）の場所を用意する。row は {head: ブランチ, label: 作業の名前}。PR の場所と同じく、ブランチの場所が在れば開き直し、
    無ければ herdr に作らせる（置き場は herdr の worktrees.directory）。元の clone 自身がそのブランチを開いていれば branch_busy。

    PR と違い、ブランチは origin に無くてよい（作業はこれから始める）。作るときの元は、origin にそのブランチが在れば origin/<ブランチ>、無ければ
    origin の既定のブランチ（default_branch）。手元に同じ名前のブランチが在れば、herdr はそれを開く。在る場所は git で動かさない
    （サブエージェントのブランチは手元で積む物なので、origin へ fast-forward しない）。作業場の名前（herdr の label）は作業の名前にする。"""
    branch, name = row.get("head"), row.get("label")
    out = {"number": None, "branch": branch, "path": None, "pane": None, "workspace": None,
           "created": False, "status": "provision_failed", "detail": None}
    if not branch:
        out["detail"] = "ブランチが決まっていない"
        return out
    notes = []
    try:
        places = h.worktrees(repo.source)
        if source_holds(places, branch):
            out.update(status="branch_busy", detail=f"元の clone {repo.source} がブランチ {branch} を開いている（ブランチを替えない。"
                                                     "元の clone を別のブランチへ移すか、別のブランチの名前で頼む）")
            return out
        place = find(places, branch)
        if place is None:
            try:
                g.fetch(repo.source, branch)
                base = f"origin/{branch}"
            except gitx.GitError:
                g.fetch(repo.source, default_branch)
                base = f"origin/{default_branch}"
            made = h.create_worktree(repo.source, branch, base, name)
            out["created"] = True
            notes += _copy(repo, made["path"])
        else:
            made = h.open_worktree(repo.source, place["path"], name)
        seen = find(h.worktrees(repo.source), branch)
    except (gitx.GitError, h.Error, OSError) as e:
        out["detail"] = "／".join(notes + [str(e)])
        return out
    return _read_back(out, made, seen, branch, notes, g)


def reopen(source, path, name, h=term):
    """閉じた部署の作業場（ペインを閉じると作業場も閉じる）を herdr に開き直し、(新しいペイン, 作業場) を返す。書く口（herdr の
    作業場）。開けなければ HerdrError。"""
    got = h.open_worktree(source, path, name)
    return got.get("pane_id"), got.get("workspace_id")


def refresh_shape(source, g=gitx):
    """部署を立てる前に、会社の形を読む ref（origin の既定のブランチ。origin/HEAD が指す先）だけを origin から取り直す。書く口（手元の
    origin/<ブランチ> を動かす）。取り直せなければ注記を返し、手元の控えのまま読ませる。origin/HEAD が無ければ何もしない（読む側の
    注記が直し方を出す）。

    作業場を作った後に会社の形を読む並びにしないのは、役の名前の誤りを作業場を作る前に止め、--dry-run でも役の起動の設定を
    出すため。作業場を作るときの fetch（prepare_task）の前に読むので、ここで取り直さないと、別の所でメインブランチの会社の形を変えて
    取っていないとき、起動するときの設定（settings・model）は古い形で決まり、立てた後のフックは新しい形を読む。"""
    ref = g.origin_head(source)
    if not ref:
        return None
    try:
        g.fetch(source, ref.split("/", 1)[1])
    except g.GitError as e:
        return f"origin の既定のブランチを取り直せないので、手元の {ref}（最後に取った時の形）で会社の形を読む（{e}）"
    return None


def renew_session(attrs, sid):
    """部署の会話の id が変わった（/clear・compact・resume）ときに書く属性。会話の id（company.session）と、裏の会話の短い id
    （company.job。attach に渡す。/clear の後も変わらない）。job の無い前の版の部署は、古い会話の id の頭の 8 字を job にする
    （短い id は最初の会話の id の頭と同じ字だった。2026-10-17 に 2.1.301 で、/clear の後の割り振りの部署で見た）。"""
    old = attrs.get("session")
    job = attrs.get("job") or (old.split("-")[0][:8] if old else None)
    return {"session": sid, **({"job": job} if job else {})}


def copied(office, here, keep=()):
    """新しく作った worktree の属性（here）のうち、git worktree add が本社から写した物（本社の属性 office と同じ値）を消す、mark に渡す
    値（名前 → None）。keep の名前（これから書く属性）は消さない。git worktree add は、extensions.worktreeConfig のとき、作った元の
    worktree（本社）の config.worktree を新しい worktree に写す（2026-10-16 に git 2.50 と 2.56.0.windows.2 で見た）。本社に --desk が
    書いた窓口の属性が PR の作業場に写って残ると、その場所で起動した PR の会話が役を足すフックから窓口の本文を受け、窓口として振る舞った
    （guided-resolver の PR #1987 の作業場で、自分の居るブランチに部署を立てようとした。my_notes の受付 3d3ccc）。
    本社の属性に書いた worktree の id（gitx.OWN_ID）が在れば、here は写しを空と読み、写しは mark が丸ごと消す。これは id を書く前の版の
    本社から写った属性のための物。"""
    return {k: None for k, v in here.items() if k not in keep and office.get(k) == v}


def desk_seat(place, common, attrs):
    """その場所が窓口の席か: 本社（代表の clone。git の場所と共通の場所が同じ）か、--desk だけが書く属性 company.pid（窓口の会話の
    処理の番号）を持つ場所。席の場所では、--desk が書いた会話（company.session）か、その会話の処理の中の会話だけを窓口と見る。
    worktree に本社の属性が写って残っていても（copied の前の版で作った作業場）、その場所の会話を窓口と取り違えない。"""
    if not place or not common:
        return False
    return os.path.realpath(place) == os.path.realpath(common) or bool(attrs.get("pid"))


def mark(path, source, attrs, g=gitx):
    """部署の属性を、その場所（worktree）の git の設定 company.<名前> に書く。値が None（か空）の属性は、前の回の値が残っていれば消す
    （使い直した場所に、前の回の gh のアカウントや設定の場所が残って効き続けないように）。書けなければ GitError。
    元の clone に extensions.worktreeConfig が無ければ先に入れる（部署ごとの設定は、これが無いと書けない）。
    その場所の属性がほかの worktree から写った物（書いた worktree の id が違う）なら、先に丸ごと消す（gitx.drop_copied_attrs）。"""
    g.enable_worktree_config(source)
    g.drop_copied_attrs(path)
    # 属性を書いた worktree の id も書く。git の worktree add がここから写した物を、読む側（gitx.worktree_attrs）が写しと見分ける。
    # 属性より先に書く（後に書くと、写しの上に書いている間、id の無い属性が前の版の部署に見える）
    own = g.worktree_id(path) if any(attrs.values()) else None
    if own:
        g.set_worktree_attr(path, g.OWN_ID, own)
    for name, value in attrs.items():
        if value:
            g.set_worktree_attr(path, name, value)
        else:
            g.unset_worktree_attr(path, name)


def drop_copies(path, g=gitx):
    """新しく作った worktree の属性が、ほかの worktree から写った物（書いた worktree の id が違う）なら丸ごと消す（gitx.drop_copied_attrs）。
    mark と違い、元の clone の設定（extensions.worktreeConfig）には触らない。消したら真。書けなければ GitError。"""
    return g.drop_copied_attrs(path)


# 元の clone の .git/info/exclude（commit されない、手元だけの無視の決まり。worktree と共有）に足す物
LOCAL_EXCLUDES = (
    chat.LOCAL_SETTINGS,             # 部署の会話が書く許可の記録（会社の形の設計 9.1 で確かめた）。.claude/ を丸ごと隠すと、exclude は
                                     # 全 worktree で共有なので、.claude/ の下に新しく作ったフックの台本などが未追跡に出ず、
                                     # commit し忘れに気づけない（my_notes で見つかった）。Claude Code の手元のファイルは Claude Code が
                                     # 自分で exclude に足す（# claude-code-runtime の行）
    "__pycache__/",   # 部署が試しに走らせた Python が作る控え。.gitignore の無いリポジトリで、--land と --clean が
                      # 「git に足していないファイルが有る」として止まっていた（まっさらな環境での 4 回目の試しの 7）
)


def hide_claude_dir(source, g=gitx):
    """元の clone の .git/info/exclude に LOCAL_EXCLUDES を足す（無い物だけ）。部署の会話と、部署が走らせたツールが作る手元だけの
    ファイルを、勤め先のリポジトリの .gitignore を触らずに git status から隠す。結末の語の並び（gitx.exclude の added・already）。"""
    return [g.exclude(source, pattern) for pattern in LOCAL_EXCLUDES]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--number", type=int, required=True)
    ap.add_argument("--config")
    ap.add_argument("--repo")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    repo = config.pick_repo(config.load(a.config, os.environ), a.repo)
    row = next(r for r in jsonio.load(a.plan)["plan"] if r["number"] == a.number and r["outcome"] == "assigned")
    jsonio.dump({"provision": prepare(row, repo)}, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
