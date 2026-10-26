#!/usr/bin/env python3
"""clean ノード: ブランチごとの場所（元の clone の linked worktree）のうち、消してよいものを選び、消す（設計書のセクション 3 の片付け）。外に書く。

見るのは、元の clone の linked worktree だけ（元の clone 自身は、herdr が linked と返しても見ない）。並びは herdr アダプタの
worktrees が返す、元の clone と中身を共有する worktree なので、関係ないリポジトリの場所は並びにも入らない。
消してよいのは、次の全部を満たす場所だけ。
- ブランチに居る（ブランチに乗っていない checkout は消さない）
- そのブランチの PR が閉じている（MERGED か CLOSED）。PR の無いブランチ（issue から始めて PR をまだ作っていないもの）は消さない。
  PR が読めなければ消さない
- その場所かその下を作業フォルダにする会話が、どのアカウントにも無い（入口は、閉じた PR の会話が手すきで手元の作業も無ければ、
  先に会話を終え（turn.close_session）、会話の一覧を取り直して無いことを確かめてから消す）
- 未コミットの変更も、git にまだ足していない新しいファイルも、そのブランチの上の stash も無い
- 手元のブランチの先頭が PR の head の commit と同じか、その祖先（origin より遅れているだけで、手元にしか無い commit が無い。in_pr）
- 設定の copy_files に書いたファイルのうち、写し元と中身が違うもの（その場所で書き換えた手元だけのファイル）が無い
git が追わないファイルのうち、それ以外（依存・生成物など）は場所と一緒に捨ててよい（作り直せる）。
パスはリンクを辿った実際のパスで比べる（会話の作業フォルダを見落とさない）。
消す時は herdr の worktree の口で checkout と作業場を消し（--force は付けない）、消えたことを読み戻してから、手元のブランチも消す
（先頭が候補に選んだ時の先頭と同じときだけ）。消す前に、場所の git の置き場に graphloops の盤面（run の記録）が在れば、共通の .git の
graphloops/boards-archive/ に写す（keep_boards。写せなければ消さない。部署を消すときも同じ remove を通る）。前の版の PR ごとの clone（<リポジトリの名前>-pr-<番号>）は扱わない。

部署（入口の --task が立て、属性 company.session を持つ linked worktree）は、別の決まりで選ぶ（departments・retire）。
- エフェメラルの部署である（属性 company.lifecycle が persistent の永続の部署は畳まない。属性が無ければエフェメラルとみなす。会社の形の設計 4.10 の 1）
- 部署の会話が終わっている（state が done・stopped・failed）か、会話の一覧にもう無い
- 未コミットの変更も git に足していないファイルも、手元にしか無い commit や stash も無い
- 部署のブランチの先頭がメインブランチ（origin の既定のブランチの手元の控え）に入っている（ブランチに乗っていない部署も、先頭が入っていれば消す）
消す時は、会話を `claude rm` で消し（会話の worktree は下回りが作ったので、rm は worktree を残す。rm が一緒に消す会話の一時の
置き場は、物が在れば先に共通の .git の下の company/kept-tmp/<会話の id> に写す）、続けて上と同じく herdr の
worktree の口で場所と作業場（attach の窓）を消し、手元のブランチも消す。メインブランチに入れる方法は会社ごとに決める（設計の 8 章）ので、
ここは「入っていれば消す」だけを持つ。

永続の部署は作業場を残したまま、頼みごとにブランチを切り替える。入れ終えた前のブランチは手元に残るので、--land が入れたブランチとその commit を
属性 company.landed-branches（JSON の ブランチ → commit）に書き、--clean --apply と次の --land が sweep_landed で消す。消すのは、
どの worktree も開いていないブランチで、先頭がまだ入れた commit と同じ物だけ（入れた後に commit を積んだブランチは消さず、記録から外す）。
部署の会話に「切り替えるときに前のブランチを消す」と任せず機械で消すのは、会話は前のブランチを消し忘れても止まらず、消してよいかの見極め
（入れた commit と同じか）を機械が確かに持つため。

使い方は入口から: python3 dispatch.py --clean [--apply]
"""

import filecmp
import json
import os
import pathlib
import shutil
import stat
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import filex  # noqa: E402
import gitx  # noqa: E402
from ports import chat, term  # noqa: E402

FINISHED = ("MERGED", "CLOSED")


def _same(a, b):
    return os.path.realpath(a or "") == os.path.realpath(b or "")


class Unknown(Exception):
    """PR が読めない（pr_for_branch が投げる）。その場所は消さない。"""


def changed_copies(path, copy_root, copy_files):
    """copy_files のうち、場所に在って、写し元（copy_root）と中身が違うもの（写し元が無いものも含む）。"""
    out = []
    for rel in copy_files:
        here, there = os.path.join(path, rel), os.path.join(copy_root, rel)
        if os.path.isfile(here) and not (os.path.isfile(there) and filecmp.cmp(here, there, shallow=False)):
            out.append(rel)
    return out


def in_pr(path, pr_head, head_sha, is_ancestor):
    """手元の先頭が PR の head と同じか、その祖先（origin より遅れているだけ）なら、その先頭の commit。手元にしか無い commit が有る・
    読めない（PR の head の commit が手元に無いときも含む）なら None（消さない側に倒す）。is_ancestor(場所, a, b) は a が b の祖先か。
    2026-10-20 に、遅れているだけのマージ済みの PR の手元（behind 10 と 2）を、先頭が PR の head と違うだけで手元の作業と数えて残し続けた。"""
    head = head_sha(path)
    if head and pr_head and (head == pr_head or is_ancestor(path, head, pr_head)):
        return head
    return None


def candidates(places, pr_for_branch, open_cwds, is_clean, stashed, head_sha, source=None, changed=lambda p: [],
               is_ancestor=lambda path, a, b: False):
    """places は herdr.worktrees の並び。pr_for_branch(ブランチ) は {number, state, head_sha}・None（PR が無い）・Unknown を投げる。
    changed(場所) は、写し元と中身の違う copy_files の並び（changed_copies）。is_ancestor は in_pr に渡す。
    返す 1 行は {path, branch, number, state, pr_head, head, removable, reason, files}。head は、手元の先頭が PR の head と同じかその祖先と
    確かめた先頭（in_pr）で、消す時に手元のブランチの先頭と比べる。確かめていなければ None。"""
    rows = []
    for place in sorted((p for p in places if p.get("linked")), key=lambda p: p.get("path") or ""):
        path, branch = place["path"], place.get("branch")
        if source and _same(path, source):
            continue
        row = {"path": path, "branch": branch, "number": None, "state": None, "pr_head": None, "head": None,
               "removable": False, "reason": None, "files": []}
        rows.append(row)
        if not branch:
            row["reason"] = "no_branch"
            continue
        try:
            pr = pr_for_branch(branch)
        except Unknown:
            row["reason"] = "pr_state_unknown"
            continue
        if pr is None:
            row["reason"] = "no_pr"
            continue
        row.update(number=pr["number"], state=pr["state"], pr_head=pr.get("head_sha"))
        if pr["state"] not in FINISHED:
            row["reason"] = "pr_open"
        elif any(filex.inside(c, path) for c in open_cwds if c):
            row["reason"] = "session"
        elif not is_clean(path):
            row["reason"] = "dirty"
        elif stashed(path, branch) or not (head := in_pr(path, pr.get("head_sha"), head_sha, is_ancestor)):
            row["reason"] = "unpushed"
        else:
            row["head"] = head
            row["files"] = changed(path)
            if row["files"]:
                row["reason"] = "local_files"
            else:
                row["removable"] = True
    return rows


def release(source, path, h=term):
    """その場所の worktree の作業場（herdr がその場所に返す open_workspace_id）を閉じる（checkout は残す）。
    送り直す前に古い作業場を畳むのに使う。{status, workspace, detail}。status は closed・none（開いていない）・close_failed。
    閉じる前に、その作業場の全部のペインの前がシェルかを確かめ、シェルでない物（会話・エディタ・dev server）が居れば閉じない。
    同じフォルダに cd しただけのほかの作業場には触らない（そのペインを探して閉じると、持ち主の別の作業場ごと閉じてしまう）。"""
    out = {"status": "close_failed", "workspace": None, "detail": None}
    try:
        place = next((p for p in h.worktrees(source) if _same(p.get("path"), path)), None)
        ws = (place or {}).get("workspace")
        if not ws:
            out["status"] = "none"
            return out
        out["workspace"] = ws
        busy = [p["pane_id"] for p in h.panes() if p.get("workspace_id") == ws and not h.shell_in_front(p["pane_id"])]
        if busy:
            out["detail"] = f"作業場 {ws} のペイン {', '.join(busy)} の前でシェルでない物が動いている（閉じない）"
            return out
        h.close_workspace(ws)
    except h.Error as e:
        out["detail"] = str(e)
        return out
    out["status"] = "closed"
    return out


DONE = ("done", "stopped", "failed")


def departments(places, attrs_of, session_of, is_clean, unpushed, merged, head_sha, source=None, queued=lambda path: False):
    """部署ごとに、消してよいか。attrs_of(場所) は部署の git の属性。session_of(属性, 場所) は会話の 1 件（{id, sessionId, state, …,
    config_dir}）か、一覧に無ければ None。会話は属性の長い id（company.session）で見分け、無ければ短い id（company.job）で見分ける
    （部署を立てた直後に会話のフックと書き込みがぶつかり、company.session だけが書かれなかった部署が在った）。どちらも無い部署と、短い id の会話が一覧に無い部署は並べない。merged(場所) はブランチの先頭がメインブランチに入っているか。queued(場所) は部署の
    順番待ちに頼みが在るか（在る部署を消すと、積まれた頼みを渡す者が居なくなり、頼み元が返事を待ち続ける。2026-10-18 に点検の
    部署が順番待ちの 2 件を残して消え、見渡しが半日返事を待った）。
    返す 1 行は {path, branch, name, account, session, config_dir, state, pid, pr_head, removable, reason}。pid は会話の一覧の処理の番号で、
    動く処理の無い会話には無い。pr_head は消す時に手元のブランチの先頭と比べる commit で、今の先頭。reason は persistent・running・queued・dirty・unpushed・not_merged・no_branch。"""
    rows = []
    for place in sorted((p for p in places if p.get("linked") and not p.get("prunable")), key=lambda p: p.get("path") or ""):
        path, branch = place["path"], place.get("branch")
        if source and _same(path, source):
            continue
        attrs = attrs_of(path)
        if not (attrs.get("session") or attrs.get("job")):
            continue   # 会話を見分ける id が無い。止まったかを読めないので並べない（消さない側に倒す）
        s = session_of(attrs, path)
        if s is None and not attrs.get("session"):
            continue   # 短い id の会話が一覧に無い（id が古いか、一覧を読めない）。止まったと決められないので並べない
        row = {"path": path, "branch": branch, "name": attrs.get("name"), "account": attrs.get("account"),
               "session": (s or {}).get("id") or (s or {}).get("sessionId"), "config_dir": (s or {}).get("config_dir"),
               "state": (s or {}).get("state") or (s or {}).get("status") or "gone", "pid": (s or {}).get("pid"), "pr_head": head_sha(path),
               "removable": False, "reason": None}
        rows.append(row)
        if attrs.get("lifecycle") == gitx.PERSISTENT:
            row["reason"] = "persistent"
        elif s is not None and s.get("state") not in DONE:
            row["reason"] = "running"
        elif queued(path):
            row["reason"] = "queued"
        elif not branch and not merged(path):
            # ブランチに乗っていなくても、先頭がメインブランチに入っていれば失う物は無い（読むために main の commit を開いた
            # 部署が、そのまま残った。2026-10-19 の claude-plugins の見渡し）
            row["reason"] = "no_branch"
        elif not is_clean(path):
            row["reason"] = "dirty"
        elif unpushed(path):
            row["reason"] = "unpushed"
        elif not merged(path):
            row["reason"] = "not_merged"
        else:
            row["removable"] = True
    return rows


KEPT_TMP = ("company", "kept-tmp")   # 共通の .git の下の、消した部署の会話の一時の置き場の写し
# 写しの片付け: 写すたびに、KEPT_DAYS 日より古い物と、合計が KEPT_LIMIT を超えた分の古い物を消す（誰も消さず、3 日で claude-plugins に
# 223MB、my_notes に 132MB 溜まった。2026-10-19）。写しは消した部署の一時のファイルを後で拾うための物で、要るかは数日で分かる
KEPT_DAYS = 14
KEPT_LIMIT = 1024 * 1024 * 1024
BOARDS = "graphloops"   # graphloops が linked worktree の git の置き場（.git/worktrees/<名前>）に作る、run の記録（盤面）の置き場
BOARDS_ARCHIVE = ("graphloops", "boards-archive")   # 共通の .git の下の、消した場所の盤面の写し（graphloops の replay_boards.py と quality-ledger.py が読む）
ARCHIVED = ".works-dispatch-archived"   # 写しに works-dispatch が置く印。片付けは印の有る写しだけを消し、手で写した物には触らない
# 盤面の写しの片付け: 写すたびに、印の有る写しの合計が ARCHIVE_LIMIT を超えた分の古い物を消す（年齢では消さない。写しは盤面の再生と
# engine の版ごとの質の数に使うので、古い版の盤面ほど要る。盤面 1 つは 1〜7 MB〔graphloops の engine/commands.py の測り〕で、2 GiB で数百本）
ARCHIVE_LIMIT = 2 * 1024 * 1024 * 1024


def tmp_entries(path):
    """会話の一時の置き場の中の名前の並び（無ければ空）。"""
    try:
        return os.listdir(path)
    except OSError:
        return []


def keep_tmp(tmp, source, session, g=gitx):
    """会話の一時の置き場 tmp に物が在れば <共通の .git>/company/kept-tmp/<会話の id> に写し、(写した数, 写した先) を返す
    （空か無ければ (0, None)）。写せなければ OSError。"""
    n = len(tmp_entries(tmp))
    if not n:
        return 0, None
    common = g.common_dir(source)
    if not common:
        raise OSError(f"{source} の共通の .git を読めない")
    dest = os.path.join(common, *KEPT_TMP, session)
    _copy_over(tmp, dest)
    prune_kept(os.path.dirname(dest), time.time(), keep=(dest,))
    return n, dest


def kept_entries(kept):
    """写しの置き場 kept の (更新の時刻, パス) の古い順。"""
    try:
        names = os.listdir(kept)
    except OSError:
        return []
    got = []
    for n in names:
        p = os.path.join(kept, n)
        try:
            got.append((os.stat(p).st_mtime, p))
        except FileNotFoundError:
            continue   # 並べた後に消えた（ほかの片付けが先に消した）
        except OSError as e:
            filex.warn(f"注記: 写しの置き場の {p} の時刻を読めない（{e}）。古さで消すかと --tree の古い物の数から外した")
            continue
    return sorted(got)


def _tree_size(path):
    total = 0
    for top, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(top, f)).st_size
            except FileNotFoundError:
                continue   # 歩く間に消えた（消えた物は大きさに入れない）
            except OSError as e:
                filex.warn(f"注記: {os.path.join(top, f)} の大きさを読めない（{e}）。写しの大きさの合計から外した")
                continue
    return total


def prune_kept(kept, now, keep=(), days=None, limit=None, listed=kept_entries):
    """写しの置き場 kept から、days 日（既定は KEPT_DAYS。0 なら年齢では消さない）より古い物と、合計が limit（既定は KEPT_LIMIT）を
    超えた分の古い物を消す（keep に挙げた物は残す）。並べるのは listed（既定は置き場の中の全部）。消した数。消せなかった物は残し、
    --tree が古い物か大きさの超えとして出す。"""
    days = KEPT_DAYS if days is None else days
    limit = KEPT_LIMIT if limit is None else limit
    entries = [(t, p, _tree_size(p)) for t, p in listed(kept) if p not in keep]
    total = sum(s for _, _, s in entries) + sum(_tree_size(p) for p in keep)
    gone = 0
    for t, p, size in entries:
        if (not days or now - t <= days * 86400) and total <= limit:
            continue
        shutil.rmtree(p, ignore_errors=True)
        if not os.path.exists(p):
            gone += 1
            total -= size
    return gone


def archived_entries(archive):
    """盤面の写しの置き場 archive のうち、works-dispatch が写した物（印 ARCHIVED が有る）の (印の更新の時刻, パス) の古い順。"""
    try:
        names = os.listdir(archive)
    except OSError:
        return []
    got = []
    for n in names:
        p = os.path.join(archive, n)
        try:
            got.append((os.stat(os.path.join(p, ARCHIVED)).st_mtime, p))
        except OSError:   # 印が無い物は手で写した物（INDEX.md などのファイルも）。片付けの外に置く
            continue
    return sorted(got)


def archived_size(archive):
    """盤面の写しの置き場 archive のうち、works-dispatch が写した物の合計の大きさ。写したときに印へ書いた大きさを足す（--tree が
    打つたびに数百本の盤面を辿らない）。印の中身が読めなければ、その写しだけ辿って測る。"""
    total = 0
    for _, p in archived_entries(archive):
        try:
            total += int(pathlib.Path(p, ARCHIVED).read_text(encoding="utf-8"))
        except (OSError, ValueError):   # 印の中身が無い・壊れている。辿って測る
            total += _tree_size(p)
    return total


def boards_of(path, g=gitx):
    """場所 path（元の clone の linked worktree）の git の置き場に在る graphloops の盤面の置き場と、写す先の組 (盤面, 写す先)。
    無ければ None。写す先は <共通の .git>/graphloops/boards-archive/<git の置き場の名前>/graphloops で、graphloops の init と status が
    出す写し方と同じ先（手で写した物と同じ名前なら、その上に写す。印は付けないので片付けの外のまま）。"""
    here, common = g.git_dir(path), g.common_dir(path)
    if not here or not common or os.path.realpath(here) == os.path.realpath(common):
        return None
    boards = os.path.join(here, BOARDS)
    if not os.path.isdir(boards):
        return None
    return boards, os.path.join(common, *BOARDS_ARCHIVE, os.path.basename(here), BOARDS)


def keep_boards(path, g=gitx):
    """場所 path の git の置き場に graphloops の盤面（graphloops/）が在れば、git worktree remove が一緒に消す前に共通の .git の
    boards-archive へ写し、写した先を返す（無ければ None）。写せなければ OSError。graphloops は works-dispatch の無いリポジトリでも
    動くので、消す側のこちらが写す（2026-10-19、受付 5f414f）。写すたびに印の有る写しを ARCHIVE_LIMIT に収める（標準の決まり 5）。"""
    got = boards_of(path, g)
    if not got:
        return None
    boards, dest = got
    top = os.path.dirname(dest)
    mine = not os.path.lexists(top) or os.path.exists(os.path.join(top, ARCHIVED))   # 手で写した物には印を足さない
    _copy_over(boards, dest)
    if mine:
        pathlib.Path(top, ARCHIVED).write_text(str(_tree_size(top)), encoding="utf-8")   # 大きさは archived_size が読む
    prune_kept(os.path.dirname(top), time.time(), keep=(top,) if mine else (), days=0, limit=ARCHIVE_LIMIT, listed=archived_entries)
    return dest


def _unlink(path):
    """ファイルを消す。Windows は読み取り専用のファイルを消せない（WinError 5。POSIX はフォルダの権限で決まる）ので、書ける印に
    してから消し直す。"""
    try:
        os.unlink(path)
    except PermissionError:
        if os.name != "nt":
            raise
        os.chmod(path, stat.S_IWRITE)
        os.unlink(path)


def _again_writable(func, path, err):
    """shutil.rmtree の失敗の受け口（err は 3.12 からの onexc なら例外、前の onerror なら sys.exc_info の組）: 読み取り専用で
    消せなかった物を、書ける印にしてから消し直す（_unlink と同じ訳。使用中で消せない物は、消し直しでもう一度 PermissionError になって止まる）。"""
    err = err[1] if isinstance(err, tuple) else err
    if os.name != "nt" or not isinstance(err, PermissionError):
        raise err
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _copy_over(src, dest):
    """src の木を dest に写す。前の回が途中で止まって dest に写しが残っていても、打ち直せば写し終える: 写し先に在る物は
    消してから写し直す（git の objects は読み取り専用で写るので、上に書けず Errno 13 になる。前の回が写したシンボリックリンクは、
    在ると作れず Errno 17 になる。2026-10-17 の --retire 点検で 701 件と 5 件）。写し先の同じ名前の物が、写し元と種類が違えば
    （ファイルとフォルダ、リンクとフォルダ）、それも消す（リンクを辿って外へ書かない）。フォルダの権限は写さない（読み取り専用の
    フォルダに写すと、次の回が中に書けない）。名前付きパイプ（FIFO）は中身を持たないので、同じ名前のパイプを作り直す（同じ日の
    点検の置き場に 9 個在った）。読めないフォルダやソケットなど、写せない物が有れば OSError（読めないフォルダを飛ばさない）。"""
    def stop(e):
        raise e
    for root, dirs, files in os.walk(src, onerror=stop):
        here = os.path.join(dest, os.path.relpath(root, src))
        if os.path.islink(here) or (os.path.lexists(here) and not os.path.isdir(here)):
            _unlink(here)
        os.makedirs(here, exist_ok=True)
        for name in dirs + files:
            s, d = os.path.join(root, name), os.path.join(here, name)
            mode = os.lstat(s).st_mode
            if stat.S_ISDIR(mode):
                continue
            if os.path.isdir(d) and not os.path.islink(d):
                shutil.rmtree(d, **{"onexc" if sys.version_info >= (3, 12) else "onerror": _again_writable})
            elif os.path.lexists(d):
                _unlink(d)
            if stat.S_ISLNK(mode):
                os.symlink(os.readlink(s), d)
            elif stat.S_ISFIFO(mode):
                os.mkfifo(d, stat.S_IMODE(mode))
            else:
                shutil.copy2(s, d)


def retire(row, source, label, h=term, g=gitx, c=None, env=None):
    """部署の 1 行を消す: 会話が一覧に在れば c.remove_session（claude rm）で消し、続けて remove で場所と窓と手元のブランチを消す。
    env は claude を呼ぶ環境で、config_dir を書かないアカウントの置き場をこの環境の CLAUDE_CONFIG_DIR で決める。打った会話の
    環境のままにせず、会話の一覧を読んだのと同じ環境を渡す（2026-10-17 に p2 の会話から打った --clean --apply が、main の会話を
    p2 の置き場で探して「No job matching」で断られた）。
    rm は会話の一時の置き場（c.job_tmp）も消す。部署はそこに残すと書いた物を置くことがあるので、物が在れば先に keep_tmp で写し、
    写せなければ消さない。graphloops の盤面も rm の前に写す（keep_boards。写せなければ会話も場所も消さない）。rm が断れば
    （未 push の commit など）、場所も消さない。{path, branch, removed, branch_deleted, detail}。"""
    note = None
    try:
        boards = keep_boards(row["path"], g)
    except OSError as e:
        return {"path": row["path"], "branch": row["branch"], "removed": False, "branch_deleted": False,
                "detail": f"graphloops の盤面を写せないので消さない（{e}）"}
    if row.get("session"):
        try:
            n, dest = keep_tmp(c.job_tmp(row["config_dir"], row["session"], env), source, row["session"], g)
        except OSError as e:
            return {"path": row["path"], "branch": row["branch"], "removed": False, "branch_deleted": False,
                    "detail": f"会話の一時の置き場を写せないので消さない（{e}）"}
        note = f"会話の一時の置き場の {n} 件を {dest} に写した" if n else None
        ok, said = c.remove_session(row["config_dir"], row["session"], base_env=env)
        if not ok:
            return {"path": row["path"], "branch": row["branch"], "removed": False, "branch_deleted": False,
                    "detail": f"{chat.REMOVE_COMMAND} が断った（{said}）"}
    out = remove(row, source, label, h, g, boards=boards)
    if note:
        out["detail"] = f"{note}。{out['detail']}" if out["detail"] else note
    return out


UNCOPIED = object()   # remove の boards の既定: 盤面をまだ写していない


def remove(row, source, label, h=term, g=gitx, boards=UNCOPIED):
    """候補の 1 行の場所を消し、手元のブランチも消す（先頭が行の head〔無ければ pr_head〕と同じときだけ）。消す前に graphloops の盤面を写す（keep_boards。写せなければ消さない）。
    boards は呼び手が先に写した keep_boards の返り値（retire が rm の前に写す）。{path, branch, removed, branch_deleted, detail}。"""
    path = row["path"]
    out = {"path": path, "branch": row["branch"], "removed": False, "branch_deleted": False, "detail": None}
    if boards is UNCOPIED:
        try:
            boards = keep_boards(path, g)
        except OSError as e:
            out["detail"] = f"graphloops の盤面を写せないので消さない（{e}）"
            return out
    try:
        h.remove_worktree(source, path, label)
    except (h.Error, OSError) as e:
        out["detail"] = str(e)
    out["removed"] = not os.path.exists(path) and all(not _same(p.get("path"), path) for p in _safe_list(h, source))
    if not out["removed"]:
        out["detail"] = out["detail"] or "消した後の読み戻しで、場所がまだ在る"
        return out
    try:
        # ブランチに乗っていない場所は、消す手元のブランチが無い
        out["branch_deleted"] = not row["branch"] or g.delete_branch(source, row["branch"], row.get("head") or row["pr_head"]) in (
            "deleted", "absent")
    except gitx.GitError as e:
        out["detail"] = f"場所は消したが、手元のブランチ {row['branch']} を消せなかった（{e}）"
    if not out["branch_deleted"] and not out["detail"]:
        out["detail"] = f"場所は消したが、手元のブランチ {row['branch']} の先頭が片付けを決めた時と違うので残した"
    if boards:
        out["detail"] = f"graphloops の盤面を {boards} に写した" + (f"。{out['detail']}" if out["detail"] else "")
    return out


def _safe_list(h, source):
    try:
        return h.worktrees(source)
    except h.Error:
        return []


LANDED_BRANCHES = "landed-branches"   # 永続の部署の属性: 入れたブランチ → 入れた commit（JSON）


def landed_of(attrs, strict=False):
    """属性 company.landed-branches の {ブランチ: commit}。読めない（JSON でない・文字列から文字列への表でない）とき、strict なら
    gitx.AttrError（書き足す道が、空として上書きして前に入れたブランチの記録を消さない）、ほかは標準エラーに知らせて空。"""
    raw = attrs.get(LANDED_BRANCHES) or "{}"
    try:
        got = json.loads(raw)
        ok = isinstance(got, dict) and all(isinstance(b, str) and isinstance(c, str) for b, c in got.items())
    except ValueError:
        ok = False
    if ok:
        return got
    why = f"部署 {attrs.get('name') or '?'} の属性 company.{LANDED_BRANCHES} が文字列の JSON の表でない（{raw[:120]}）"
    if strict:
        raise gitx.AttrError(why + f"。git config --worktree company.{LANDED_BRANCHES} で直してから打ち直す")
    filex.warn(f"注記: {why}。入れたブランチの記録は無いものとして読んだ")
    return {}


def sweep_landed(places, attrs_of, source, apply, g=gitx):
    """永続の部署が入れ終えた前の手元のブランチを消す（apply が偽なら見立てだけ）。1 行は {path, name, branch, status, keep}。
    status は deleted（消した・もう無い）・open（どこかの worktree が開いている。次に回す）・moved（入れた後に commit が有るので
    消さず、記録から外す）・would（apply が偽で、消せる）・failed（git が断った。次に回す）。keep はその部署の記録に残す {ブランチ: commit}
    （呼んだ側が属性に書き戻す。同じ部署の行は同じ keep を持つ）。"""
    opened = {p.get("branch") for p in places if p.get("branch") and not p.get("prunable")}
    out = []
    for place in places:
        if not place.get("linked") or place.get("prunable"):
            continue
        attrs = attrs_of(place["path"])
        landed = landed_of(attrs)
        if not landed:
            continue
        keep, rows = {}, []
        for branch, sha in sorted(landed.items()):
            if branch in opened:
                status = "open"
            elif not apply:
                status = "would"
            else:
                try:
                    status = {"deleted": "deleted", "absent": "deleted", "moved": "moved"}[g.delete_branch(source, branch, sha)]
                except gitx.GitError:
                    status = "failed"
            if status in ("open", "would", "failed"):
                keep[branch] = sha
            rows.append({"path": place["path"], "name": attrs.get("name"), "branch": branch, "status": status})
        out += [{**r, "keep": keep} for r in rows]
    return out

