#!/usr/bin/env python3
"""入口の --land（部署の成果をメインブランチに入れる）の流れ。dispatch.py の一部で、同じ入口の層に置く（ほかの部署と同時に dispatch.py を
触るぶつかりを減らすため、別のファイルにした）。ノード（nodes/land.py・nodes/bump.py・nodes/clean.py）を並べる順だけを持つ。

順（会社の形の設計 8 章。決まりのフィールドは nodes/land.py の read_rules）:
1. 部署を名前（属性 company.name。無ければ前の名前 company.former-names）かブランチの名前で探し、会社の形の [land] を、部署の役で読む。取り込み方が none なら何もしない。
2. pr: 部署のブランチを origin に出し、メインブランチへの PR を出して止める。
3. ff-after-ci: メインブランチを取り直す。もう入っていれば片付けへ。メインブランチが部署のブランチの祖先でなければ、部署の場所で git でリベースする
   （nodes/land.py の auto_rebase）。機械で解けないぶつかりが残れば、元に戻して部署にリベースを頼んで止める。
4. 版上げ（bump = "marketplace"）があれば、一時の場所で部署のブランチの先頭の上に版を上げる commit を作る（部署のブランチは動かさない）。
5. ゲート: CI のブランチの形なら、そのブランチの頭を GitHub Actions の設定が書いていることを確かめ、そのブランチへ候補を push して run を待つ。check なら、手元の検証のコマンドを候補の場所で回す。
6. 赤なら、部署に失敗の要点を頼む。緑ならメインブランチを取り直し、まだ祖先ならメインブランチを fast-forward して push する（ゲートのブランチは消す）。
   進んでいれば、同じにリベースしてゲートから回し直す（リベースできなければ部署に頼む）。
7. 入れたら、畳む部署は --clean と同じ部品（clean.departments・clean.retire）で片付ける。always の部署は残す。片付けられない
   畳む部署（納品の直後で会話がまだ止まりきっていない、など）には入れた印（属性 company.landed）を書いて残し、次の --land
   （どの部署でも）が、片付けられる形になっていれば一緒に片付ける。止まるのを待たないのは、こちらから期限を足さないため（D5）。

会社の形の [land] に queue（列の置き場）が有れば、3 のメインブランチの取り直しの直前に列（nodes/landqueue.py）へ申し出て、6 で push し終える
（か、止まる）まで列の先頭を持つ。同じ clone で同時に打った --land と、同じ列に並ぶほかの処理（my_notes の collect など）は、申し出た順に
1 本ずつ「リベース → ゲート → push」を通り、互いの push でメインブランチが先に進んでやり直すことが無い。

--dry-run（_preview）は 1 の後で分かれ、決まりと、することの見立て（リベースが要るか・入れる commit・上げる版・ゲート・片付け）を
出すだけにする。何も書かない: メインブランチの先頭は fetch せず origin に問い合わせて読み（ls-remote。手元の ref は変えない）、版は
一時の場所を作らず、部署の場所で本当の流れと同じ bump.plan を回して見積もり、ゲートに出さず、手元の検証を回さず、
部署の窓（herdr のペイン）に打ち込まず、片付けない。本当の流れが止まる所と、見立てそのものの失敗では 1 を返す。
"""

import datetime
import json
import os
import shutil
import subprocess
import tempfile
import time
import types

from ports import chat, term
import config
import ghx
import gitx
from nodes import batch, bump, clean, deliver, land, landqueue, provision, role, tree, wake

RUN_PAUSE_S = 10  # ゲートのブランチに push した後、run が現れるのを見に行く間
FAILED = "failed"   # 代表の clone のメインブランチをそろえる git が誤りを返した（gitx.advance_branch の値に並べる、こちらの札）
LAGS = ("dirty", "local_only", FAILED)   # 代表の clone のメインブランチが遅れたまま残り、窓口に知らせる形
# 手元の検証に渡す環境変数の名前（land_env。gates の coldread-gate.py の LAND_TIP・LAND_KEY・LAND_BRANCH と同じ字）
WORKS_LAND_TIP, WORKS_LAND_KEY, WORKS_LAND_BRANCH = "WORKS_LAND_TIP", "WORKS_LAND_KEY", "WORKS_LAND_BRANCH"


def run_check(command, cwd, env=None):
    """手元の検証のコマンドを cwd で回す。env は今の環境に足す変数（land_env）。(終わりの値, 出力)。"""
    p = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**deliver.child_env(), **(env or {})})
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def land_env(tip, key, branch):
    """手元の検証に渡す環境変数（束の設計 5.3）。初見の読み手のゲート（gates の branch-check）が、推し量りより先に使う。
    tip は文書を読む commit（版上げの前の先頭）、key は前の回の控えの鍵、branch は読み手の記録の帰属を引く部署のブランチ。"""
    return {WORKS_LAND_TIP: tip, WORKS_LAND_KEY: key, WORKS_LAND_BRANCH: branch}


def _ask(ports, place, text):
    """部署の窓に打ち込む。窓が無い・打ち込めなければ、文を出して呼んだ側に渡させる。"""
    try:
        pane = land.pane_of(ports.term.panes(), place)
        if pane:
            land.ask(pane, text, ports.term)
            return f"部署の窓 {pane} に頼んだ: {text}"
    except term.Error as e:
        return f"部署の窓に打ち込めなかった（{e}）。次の文を部署に渡す: {text}"
    return f"部署の窓が {term.NAME} に無いので打ち込めなかった。次の文を部署に渡す: {text}"


def _sweep(place, made):
    """手元の検証が部署の場所に作った、git に足していないファイル（py_compile の __pycache__ など）を消す。--clean が「git に足して
    いないファイルが有る」として部署を残さないため。消すのは検証の前に無かった物だけ（.gitignore に当たる物は数えず、触らない）。"""
    for rel in sorted(made):
        target = os.path.join(place, rel)
        try:
            os.remove(target)
        except OSError:
            continue
        folder = os.path.dirname(target)
        while os.path.realpath(folder) != os.path.realpath(place):
            try:
                os.rmdir(folder)   # 空になったフォルダだけ消える
            except OSError:
                break
            folder = os.path.dirname(folder)


def _find(found, name, attrs_of):
    """部署を名前かブランチの名前で探す。当たらなければ前の名前（--reorg が書く company.former-names）で探す。"""
    office = next((attrs_of(p["path"]) for p in found if not p.get("linked")), {})
    rows = [(p, a) for p in found if p.get("linked") and not p.get("prunable")
            for a in [attrs_of(p["path"])] if not tree.copied_from(office, a)]   # 本社の属性の写しは部署でない
    hits = [(p, a) for p, a in rows if a.get("name") == name or p.get("branch") == name]
    return hits or [(p, a) for p, a in rows if name in gitx.former_names(a)]


def main(cfg, repo, name, ports, rows, reasons, config_path=None, pause=lambda: time.sleep(RUN_PAUSE_S), today=None,
        checker=run_check, dry_run=False, keep_removal=False, after=None, hold=None):
    """--land <名前>。rows は dispatch._department_rows、reasons は片付けで残す訳（dispatch.DEPT_REASONS）。
    after はメインブランチへ push し終えた後に、会社の形の [[land.after]]（合図。受付の設計 5.5）の並びと代表の clone と部署の属性を渡して
    呼ぶ関数（calls.fire）で、出す行の並びを返す。
    dry_run なら、することの見立てを出すだけで何も書かない（_preview）。hold は列の順番（landqueue.Hold）で、回し直し（main_again）が
    前の回の順番を持ったまま渡す。省けば、この回で持ち、終わるときに手放す。"""
    if hold is not None:
        return _main(cfg, repo, name, ports, rows, reasons, config_path, pause, today, checker, dry_run, keep_removal, after, hold)
    with landqueue.Hold() as hold:
        return _main(cfg, repo, name, ports, rows, reasons, config_path, pause, today, checker, dry_run, keep_removal, after, hold)


def _main(cfg, repo, name, ports, rows, reasons, config_path, pause, today, checker, dry_run, keep_removal, after, hold):
    g = ports.git
    try:
        found = ports.places(repo)
    except term.Error as e:
        print(f"止めた: 元の clone の worktree を読めない（{e}）")
        return 1
    hits = _find(found, name, ports.attrs)
    if len(hits) != 1:
        print(f"止めた: 部署 {name} が" + ("無い（今の名前・前の名前・ブランチの名前で探した。部署の名前は --tree の「会話」に出る）"
                                         if not hits else f" {len(hits)} つ在る（ブランチの名前で指す）"))
        return 1
    place, attrs = hits[0]
    if attrs.get("name") != name and place.get("branch") != name:
        print(f"注記: {name} は前の名前。部署の今の名前は {attrs.get('name') or '-'}")
    branch, path, source = place.get("branch"), place["path"], repo.source
    info = tree.read_info(source, os.path.dirname(config.path_of(config_path, os.environ)), g)
    rules = land.read_rules(info.get("path"), attrs.get("role"), info.get("text"))
    for n in info["notes"]:
        if n not in rules["problems"]:   # [land] の知らない鍵は、下の止めた訳に出す
            print(f"注記: {n}")
    if rules["problems"]:
        print("止めた（取り込みの決まりが読めない）:\n" + "\n".join(f"- {p}" for p in rules["problems"]))
        return 2
    # gh のアカウントは --task と同じ決め方（dispatch の設定の [[repos]] の gh_user を先に、無ければ会社の形の gh_user）
    repo = repo._replace(gh_user=role.gh_user(repo.gh_user, role.load(info.get("path"), info.get("text")))[0])
    gate = rules["gate"] or "-"
    print(f"部署 {attrs.get('name') or name}（ブランチ {branch or '-'}）: 取り込み方 {rules['mode']}、ゲート {gate}"
          + (f"、版上げ {rules['bump']}" if rules["bump"] else ""))
    if rules["mode"] == "none":
        print("取り込みの決まりが none なので、何もしない（会社の形の [land] で決める）")
        return 0
    if dry_run:
        print("空打ち（--dry-run）: することを見立てるだけで、何も書かない・push しない・部署に頼まない")
    if not branch:
        print("止めた: 部署がブランチに乗っていない")
        return 1
    try:
        provision.hide_claude_dir(source, g)   # 前の版で立てた部署にも、手元だけの無視の決まり（__pycache__/ など）を足す
    except (gitx.GitError, OSError):
        pass   # 足せなくても、下の確かめがそのまま見る
    if not ports.is_clean(path):
        print("止めた: 部署の場所に未コミットの変更か git に足していないファイルが有る")
        return 1
    try:
        main = rules["main"] or ports.default_branch(repo)
        # gh の鍵は、GitHub を使う取り込み方（pr と CI のブランチのゲート）でだけ取り出す。手元の検証のゲートなら GitHub を要さない
        env = ports.gh_env(repo) if rules["mode"] == "pr" or rules["gate"] != land.GATE_CHECK else None
        head = g.rev(path, "HEAD")
        if dry_run:
            return _preview(cfg, repo, ports, found, place, attrs.get("name") or name, rules, main, head, rows, reasons,
                            attrs, keep_removal)
        if rules["mode"] == "pr":
            if rules["bump"]:
                print("注記: 取り込み方 pr では版を上げない（版上げは PR の側で）")
            print(f"PR を出した: {land.offer_pr(source, repo.repo, branch, main, g, ports.gh, env)}")
            return 0
        if rules["queue"]:
            queue = os.path.join(g.common_dir(source), rules["queue"])
            try:
                hold.take(queue, name=(attrs.get("name") or name, branch))   # 名乗れば、判断役の --land-order が順を決められる
            except OSError as e:
                print(f"止めた: メインブランチへ入れる列（{queue}）に入れない: {e}")
                return 1
        base = land.refresh(source, main, g)
    except (gitx.GitError, ghx.GhError) as e:
        print(f"止めた: {e}")
        return 1
    run = types.SimpleNamespace(
        cfg=cfg, repo=repo, ports=ports, rows=rows, reasons=reasons, found=found, place=place, attrs=attrs, name=attrs.get("name") or name,
        branch=branch, path=path, source=source, info=info, rules=rules, main=main, env=env, pause=pause, today=today, checker=checker,
        after=after, hold=hold, keep_removal=keep_removal,
        again=lambda: main_again(cfg, repo, name, ports, rows, reasons, config_path, pause, today, checker, keep_removal, after, hold))
    bundles = rules["batch"] > 1 and hold.queue is not None
    if bundles:
        # 束の会社は順番を取った後に HEAD を読み直し（列で待つ間に足した commit も入れる）、前の束で入っていれば受け取る（束の設計 8.2）
        head = g.rev(path, "HEAD")
        code, head = _adopt(run, head, base)
        if code is not None:
            return code
    if g.is_ancestor(source, head, base):
        print(f"ブランチ {branch} はもうメインブランチ {main} に入っている")
        hold.drop()
        return _tidy(cfg, repo, ports, found, path, rows, reasons, head)
    if not g.is_ancestor(source, base, head):
        head = _rebase_here(ports, place, path, branch, base, main, rules)
        if head is None:
            return 1
    stop = _overwrite_gate(ports, place, attrs, branch, base, head, keep_removal)
    if stop is not None:
        print(stop)
        return 1
    if bundles:
        code, head = _batch(run, head, base)
        if code is not None:
            return code
    stage = tempfile.mkdtemp(prefix="dispatch-land-") if rules["bump"] else None
    try:
        if stage:
            land.stage(source, stage, head, g)
        candidate = _bump(run, head, stage) if stage else head
        verdict, label, points, ref = _gate(run, head, candidate, stage or path)
    except (gitx.GitError, ghx.GhError, bump.BumpError, OSError, ValueError) as e:
        print(f"止めた: {e}")
        return 1
    finally:
        if stage:
            _unstage(run, stage)
    print(f"ゲート（{label}）: {'緑' if verdict['result'] == 'green' else '赤'}")
    if verdict["result"] == "red":
        print(_ask(ports, place, land.red_text(branch, label, points)))
        return 1
    code = _publish(run, candidate)
    return _finish(run, candidate, ref) if code is None else code


def _unstage(run, stage):
    """一時の場所を消す（git の worktree の記録とフォルダ）。消せなければ注記だけ出す。"""
    try:
        land.unstage(run.source, stage, run.ports.git)
    except gitx.GitError as e:
        print(f"注記: 一時の場所 {stage} を消せなかった（{e}）")
    shutil.rmtree(stage, ignore_errors=True)


def _bump(run, head, stage):
    """版上げの段: 一時の場所 stage（HEAD が head に居る）に版を上げる commit を作る。候補の commit を返す（据え置きが無ければ head）。"""
    g = run.ports.git
    got = bump.make(stage, run.today or datetime.date.today().isoformat(), g)
    if not got["sha"]:
        print("版の据え置きは無い（版を上げる commit は作らない）")
        return head
    print(f"版を上げた: {got['subject']}（commit {got['sha'][:7]}）")
    for r in got["rows"]:
        if r.get("why"):
            print(f"注記: {r['name']} は{r['why']}")
    return got["sha"]


def _gate(run, head, candidate, where, riders=()):
    """ゲートの段: 候補 candidate を、手元の検証なら場所 where で回し、CI のブランチの形ならゲートのブランチに出して run を待つ。
    (結末, ゲートの名前, 失敗の要点, ゲートのブランチ〔手元の検証なら None〕)。手元の検証には、初見の読み手のゲート（gates の branch-check）が
    文書を読む commit（版上げの前の head）と前の回の控えの鍵と帰属を引くブランチを、環境変数で渡す（束の設計 5.3）。
    riders は束に乗せた部署のブランチの並び。束なら控えの鍵に束の印を付け、ゲートのブランチの名前を全員のブランチと比べ、
    ゲートのブランチへの push を一時の場所 where から打つ（束の設計 5.2）。"""
    g, rules = run.ports.git, run.rules
    key = f"{run.branch} batch" if riders else run.branch   # ブランチの名前は空白を含められないので、実在のブランチの鍵とぶつからない
    if rules["gate"] == land.GATE_CHECK:
        before = g.untracked(where)
        code, said = run.checker(rules["check"], where, land_env(head, key, run.branch))
        if where == run.path:
            _sweep(where, g.untracked(where) - before)
        return ({"result": "green" if code == 0 else "red"}, f"手元の検証 {rules['check']}",
                said.splitlines()[-land.FAIL_LINES:], None)
    ref = _gate_ref(rules["gate"], run.name, run.branch, where, (run.main, run.branch, *riders))
    land.publish(where if riders else run.path, candidate, ref, g)   # push は部署の作業場から（下の advance と同じ訳）。束は候補の木から
    print(f"ゲートに出した: {ref}（commit {candidate[:7]}）")
    verdict = land.wait_gate(run.repo.repo, ref, candidate, run.ports.gh, run.env, run.pause)
    label = f"CI {ref}" + (f" {verdict['run'].get('url')}" if verdict.get("run") else "")
    points = run.ports.gh.run_failure(run.repo.repo, verdict["run"]["id"], land.FAIL_LINES, env=run.env) \
        if verdict["result"] == "red" else []
    return verdict, label, points, ref


def _gate_ref(gate, name, branch, where, taken):
    """CI のブランチの形のゲートが push する先を決める。taken（メインブランチと部署のブランチ）と同じ名前になるか、where の
    GitHub Actions の設定がその頭を書いていなければ ValueError。"""
    ref = land.gate_branch(gate, name, branch)
    if ref in taken:
        raise ValueError(f"ゲートのブランチ {ref} がメインブランチか部署のブランチと同じ名前になる（land.gate の頭を替える）")
    if not land.ci_on(where, gate):
        raise ValueError(f"ゲートのブランチ {ref} に push しても CI が起きない（.github/workflows のどれも "
                         f"{gate.split('*', 1)[0]} を書いていない）")
    return ref


def _publish(run, candidate):
    """出す段: メインブランチを取り直し、まだ候補の祖先ならメインブランチを候補へ fast-forward して push する。push したら None。
    メインブランチが先に進んでいれば、部署の場所でリベースしてゲートから回し直した終わりの値（リベースできなければ 1）、止まれば 1。"""
    g, source, main = run.ports.git, run.source, run.main
    rebase = lambda base: run.again() if _rebase_here(run.ports, run.place, run.path, run.branch, base, main, run.rules) else 1
    try:
        base = land.refresh(source, main, g)
    except gitx.GitError as e:
        print(f"止めた: メインブランチを取り直せない（{e}）")
        return 1
    if not g.is_ancestor(source, base, candidate):
        # ゲートを回す間にメインブランチが先に進んだ: リベースできれば、リベースしたブランチでゲートから回し直す
        return rebase(base)
    try:
        # push は部署の作業場から打つ。push の前のゲート（core.hooksPath の相対の .githooks など）は git を打った作業場の物が走るので、
        # 代表の clone が遅れていると古いゲートが走り、メインブランチの今の決まりで通るはずの push を止めた（2026-10-17 の my_notes。5d75df）
        land.advance(run.path, main, candidate, g)
    except gitx.GitError as e:
        # 断られた訳を、メインブランチを取り直して分ける: 先に進んでいればリベースを頼み、そうでなければ（ブランチの保護・認証など）止める
        try:
            moved = not g.is_ancestor(source, land.refresh(source, main, g), candidate)
        except gitx.GitError:
            moved = False
        if not moved:
            print(f"止めた: メインブランチ {main} への push が断られた（{e}）")
            return 1
        try:
            base = land.refresh(source, main, g)
        except gitx.GitError as e2:
            print(f"止めた: メインブランチを取り直せない（{e2}）")
            return 1
        return rebase(base)
    return None


def _finish(run, candidate, ref, riders=()):
    """後始末の段（push し終えた後）: 束の控えと疑いの印を掃き、列の順番を渡し、代表の clone をそろえ、合図を打ち、company.base を進め、ゲートのブランチを消し、片付ける。
    riders は束に乗せた部署（_look の事実の並び）で、合図に乗った部署の属性を渡す（合図は束ごとに 1 回。束の設計 9）。"""
    g, source, main = run.ports.git, run.source, run.main
    if run.hold.queue:
        # 順番を持つ間に掃く（後ろの束ね役が push の前に書いた控えを、push されなかった物と見て消さない）。入れたブランチの疑いの印も外す
        _sweep_batches(run, candidate)
        try:
            _suspects_without(run, {run.branch, *(f["branch"] for f in riders)})
        except OSError as e:
            print(f"注記: 疑いの印を書き直せなかった（{e}）。印はブランチの先頭が動けば当たらなくなる")
    run.hold.drop()   # push し終えたので、列の次の処理に順番を渡す（代表の clone のそろえ・合図・片付けは順番の外で）
    _, local, err, notes = _follow(source, main, g, candidate)
    for n in notes:
        print(n)
    print(f"メインブランチ {main} を {candidate[:7]} へ fast-forward して push した（手元の {main}: {local if err is None else f'そろえられなかった: {err}'}）")
    if local in LAGS:
        print(_tell_desk(source, run.info, main, candidate, local, g, err))
    if run.after and run.rules["after"]:
        for line in run.after(run.rules["after"], source, run.attrs, **({"members": [f["attrs"] for f in riders]} if riders else {})):
            print(line)
    try:
        # この部署がメインブランチを知った位置を、入れた後のメインブランチに進める（次の --land のゲートは、ここより後にほかの部署が入れた行を見る）
        provision.mark(run.path, source, {"base": candidate}, g)
    except (gitx.GitError, OSError) as e:
        print(f"注記: メインブランチを知った位置（company.base）を書けなかった（{e}）。次の --land の書き換えのゲートは前の位置で見る")
    if ref:
        try:
            land.drop_gate(source, ref, g)
        except gitx.GitError as e:
            print(f"注記: ゲートのブランチ {ref} を消せなかった（{e}）")
    return _tidy(run.cfg, run.repo, run.ports, run.found, run.path, run.rows, run.reasons, candidate)


def _look(run, base, only=None):
    """束の顔ぶれを決める事実を集める（batch.select に渡す。束の設計 4.2）。見るのは、束ね役が先頭を取った時に待っていた札（hold.seen）の
    うち束ね役より後ろの物（only を渡せばその札だけ）。乗る札の部署の場所は読むだけで書かない。"""
    g, hold = run.ports.git, run.hold
    queue = hold.queue
    waiting = hold.seen[hold.seen.index(hold.ticket) + 1:] if hold.ticket in hold.seen else []
    alive = set(landqueue.alive(queue))
    marks, records = landqueue.suspects(queue), landqueue.batches(queue)
    out = []
    for ticket in waiting:
        if only is not None and ticket not in only:
            continue
        who = landqueue.who(queue, ticket)
        f = {"ticket": ticket, "who": who, "alive": ticket in alive, "name": (who and who[0]) or ticket, "path": None}
        out.append(f)
        branch = who[1] if who else ""
        hits = [(p, a) for p, a in _find(run.found, branch, run.ports.attrs) if p.get("branch") == branch] if branch else []
        head = g.rev(hits[0][0]["path"], "HEAD") if len(hits) == 1 else None
        if not head:
            continue
        place, attrs = hits[0]
        step = (batch.adoptable(records, branch, base, head, True, run.source, g) or (None,))[0]
        rules = land.read_rules(run.info.get("path"), attrs.get("role"), run.info.get("text"))
        f.update(branch=branch, place=place, path=place["path"], attrs=attrs, head=head,
                 # 前の束で入り、まだ受け取っていない札も入っている（写しは元と別の commit なので、祖先の判定だけでは見えない）。
                 # 束の後に commit を足した札は、自分の場所で受け取ってから入れる（束の設計 8.2）
                 landed=g.is_ancestor(run.source, head, base) or step == "reset", unadopted=step == "onto",
                 same=not rules["problems"] and all(rules[k] == run.rules[k] for k in land.FIELDS),
                 clean=run.ports.is_clean(place["path"]), suspect=marks.get(branch) == head)
    return out


def _stack(run, head, base, riders, stage):
    """重ねる段（束の設計 4.3）: 一時の場所を束ね役の先頭 head で作り、乗る札のブランチを順に写す。ぶつかる・ほかの部署が入れた行を消す・
    変更の記録を書いていない札に当たったら、その札を外してそこで閉じる。(重ねた先頭, 乗せた札の並び〔各札に元 original と写し stacked を
    足す〕)。束ね役が変更の記録を書いていなければ None（束の数 1 の道で、版上げが今と同じに止める）。"""
    g = run.ports.git
    land.stage(run.source, stage, head, g)
    if run.rules["bump"]:
        miss = bump.misses(stage, base, g)
        if miss:
            print(f"束: 束ね役のブランチが変更の記録を書いていない（{'・'.join(miss)}）ので、束にせず 1 本で通す")
            return None
    top, kept = head, []
    for f in riders:
        fork = g.merge_base(stage, f["head"], base) or base
        new, left = land.stack_one(stage, top, fork, f["head"], g)
        why = None if new else f"ぶつかる（{'・'.join(left)}）"
        if why is None and f["attrs"].get("base"):
            try:
                hits = land.taken(stage, f["attrs"]["base"], top, new, g)
                why = f"ほかの部署が入れた行を {len(hits)} 行消す" if hits else None
            except gitx.GitError as e:
                why = f"書き換えの取り合いを見られない（{e}）"
        if why is None and run.rules["bump"]:
            miss = bump.misses(stage, top, g)
            why = f"変更の記録を書いていない（{'・'.join(miss)}）" if miss else None
        if why:
            if new:
                land.drop_to(stage, top, g)
            print(f"束: 札 {f['name']} で閉じた（{why}）。その札は自分の順番で 1 本で通る")
            break
        kept.append({**f, "original": f["head"], "stacked": new})
        top = new
    return top, kept


def _suspects_without(run, branches, add=None):
    """疑いの印から branches を外し、add（{ブランチ: commit}）を足して書く。ブランチの先頭が印の commit から動いた印（部署が直して push し直した）も
    ここで掃除する（束の設計 6.2）。"""
    g, queue = run.ports.git, run.hold.queue
    marks = {b: s for b, s in landqueue.suspects(queue).items()
             if b not in branches and g.rev(run.source, f"refs/heads/{b}") == s}
    landqueue.set_suspects(queue, {**marks, **(add or {})})


def _sweep_batches(run, base):
    """受け取りの済んだ束の控えと、push されなかった束の控えを消す（束の設計 11。列の先頭を持つ処理だけが打つ）。"""
    g = run.ports.git
    tip_of = lambda b: g.rev(run.source, f"refs/heads/{b}") if b else None   # noqa: E731
    try:
        for ticket, record in landqueue.batches(run.hold.queue):
            if batch.finished(record, base, tip_of, g, run.source):
                landqueue.drop_batch(run.hold.queue, ticket)
    except (gitx.GitError, OSError) as e:
        print(f"注記: 束の控えを掃けなかった（{e}）。残っても、入ったかは写しが祖先かで見るので、誤って受け取ることは無い")


def _batch_once(run, head, base, riders, stage):
    """束を 1 回作って回す（重ねる → 版上げ → ゲート → 出す）。(結末, 値)。結末は single（束にしない）・red（赤。束をほどいた）・
    gone（乗る札が抜けた。値は残す札の並び）・moved（メインブランチが進んだ。値は新しい先頭）・stop（値は終わりの値）・
    pushed（値は (候補, ゲートのブランチ, 乗せた札の並び)）。"""
    g, queue = run.ports.git, run.hold.queue
    try:
        got = _stack(run, head, base, riders, stage)
        if got is None:
            return "single", None
        top, kept = got
        if not kept:
            print("束: 乗せられる札が無いので、1 本で通す")
            return "single", None
        landqueue.mark_riders(queue, [f["ticket"] for f in kept], run.name)
        print(f"束: {run.name} と {'・'.join(f['name'] for f in kept)} の {1 + len(kept)} 本を、1 回のゲートで入れる")
        candidate = _bump(run, top, stage) if run.rules["bump"] else top
        verdict, label, points, ref = _gate(run, top, candidate, stage, [f["branch"] for f in kept])
    except (gitx.GitError, ghx.GhError, bump.BumpError, OSError, ValueError) as e:
        print(f"止めた: {e}")
        return "stop", 1
    print(f"ゲート（{label}）: {'緑' if verdict['result'] == 'green' else '赤'}")
    if verdict["result"] == "red":
        _suspects_without(run, (), {f["branch"]: f["original"] for f in kept})
        print("束が赤だったので束をほどき、束ね役 1 本で回し直す（乗っていた札には疑いの印を付け、それぞれの順番で 1 本ずつ通る）")
        return "red", None
    alive = landqueue.alive(queue)
    gone = next((i for i, f in enumerate(kept) if f["ticket"] not in alive), None)
    if gone is not None:
        print(f"束: 札 {kept[gone]['name']} がゲートの間に列を抜けたので、その札から後ろを外して束を作り直す")
        return "gone", kept[:gone]
    members = [{"ticket": run.hold.ticket, "name": run.name, "branch": run.branch, "original": head, "stacked": head}]
    members += [{k: f[k] for k in ("ticket", "name", "branch", "original", "stacked")} for f in kept]
    try:
        now = land.refresh(run.source, run.main, g)
        if not g.is_ancestor(run.source, now, candidate):
            return "moved", now
        # 控えは push の前に書く（push の後に落ちても、乗った部署が写しを引ける。束の設計 8.1）。push されなければ次の掃除が消す
        landqueue.write_batch(queue, run.hold.ticket, {"leader": run.name, "main_before": base, "candidate": candidate, "members": members})
    except (gitx.GitError, OSError) as e:
        print(f"止めた: {e}")
        return "stop", 1
    try:
        land.advance(stage, run.main, candidate, g)   # push は候補の木から（push の前のフックを候補の木から走らせる。束の設計 5.2）
    except gitx.GitError as e:
        try:
            now = land.refresh(run.source, run.main, g)
        except gitx.GitError:
            now = None
        if now is None or g.is_ancestor(run.source, now, candidate):
            print(f"止めた: メインブランチ {run.main} への push が断られた（{e}）")
            return "stop", 1
        return "moved", now
    return "pushed", (candidate, ref, kept)


def _batch(run, head, base):
    """束の道（束の設計 4〜8）。列の先頭を取ったこの --land が束ね役になり、後ろに待つ札の部署のブランチを一時の場所に重ねて、1 回の版上げと
    ゲートで入れる。束にしない・ほどいたなら (None, head)（呼ぶ側が束の数 1 の道を head で回す）、止まるか入れたなら (終わりの値, head)。"""
    g, queue = run.ports.git, run.hold.queue
    if landqueue.suspects(queue).get(run.branch) == head:
        print("束にしない（このブランチには疑いの印が有る。前の束が赤だった）")
        return None, head
    riders, closed, why = batch.select(_look(run, base), run.rules["batch"])
    if not riders:
        if closed is not None:
            print(f"束にしない（次の札 {closed['name']}: {why}）")
        return None, head
    if closed is not None:
        print(f"束: 札 {closed['name']} で閉じた（{why}）")
    marked, got = set(), None
    try:
        while True:
            marked |= {f["ticket"] for f in riders}
            stage = tempfile.mkdtemp(prefix="dispatch-land-")
            try:
                tag, got = _batch_once(run, head, base, riders, stage)
            finally:
                _unstage(run, stage)
            if tag in ("single", "red"):
                return None, head
            if tag == "stop":
                return got, head
            if tag == "pushed":
                break
            if tag == "gone":
                riders = got
                continue
            # ゲートの間にメインブランチが進んだ: 束ね役を部署の場所でリベースし、同じ顔ぶれで重ね直してゲートから回し直す（束の設計 8.1）
            base = got
            if not g.is_ancestor(run.source, base, head):
                head = _rebase_here(run.ports, run.place, run.path, run.branch, base, run.main, run.rules)
                if head is None:
                    return 1, None
            stop = _overwrite_gate(run.ports, run.place, run.attrs, run.branch, base, head, run.keep_removal)
            if stop is not None:
                print(stop)
                return 1, head
            print("メインブランチが先に進んでいたので、同じ顔ぶれで重ね直してゲートから回し直す")
            riders, closed, why = batch.select(_look(run, base, {f["ticket"] for f in riders}), run.rules["batch"])
            if closed is not None:
                print(f"束: 札 {closed['name']} で閉じた（{why}）")
    finally:
        landqueue.unmark_riders(queue, sorted(marked))
    candidate, ref, kept = got
    print(f"束で入れた: {run.name}・{'・'.join(f['name'] for f in kept)}（乗った部署は、それぞれの --land か作業場の追いつきで受け取る）")
    return _finish(run, candidate, ref, kept), head


def _adopt(run, head, base):
    """受け取り（束の設計 8.2）: 前の束でこの部署のブランチの写しがメインブランチに入っていれば、部署の場所で受け取る。(終わりの値か None, head)。
    None なら今の道を head で続ける（受け取る物が無い・束の後に足した commit を写しの上へ移した）。"""
    g, ports = run.ports.git, run.ports
    got = batch.adoptable(landqueue.batches(run.hold.queue), run.branch, base, head, ports.is_clean(run.path), run.path, g)
    if got is None:
        return None, head
    step, record, row = got
    leader = record.get("leader") or "-"
    again = f"中身はメインブランチに入った（束ね役 {leader}）。手元の変更を commit してから --land を打ち直す"
    if step == "dirty":
        print(_ask(ports, run.place, again))
        return 1, head
    try:
        new, said = land.adopt(run.path, run.branch, row, step, g)
    except gitx.GitError as e:
        print(f"受け取りの git が断った（{e}）")
        print(_ask(ports, run.place, again))
        return 1, head
    if new is None:
        print(f"束（束ね役 {leader}）で入った中身の上に、その後の commit を移すとぶつかりが残った（{'・'.join(said)}）。元に戻した")
        print(_ask(ports, run.place, land.rebase_text(run.branch, run.main, run.rules["bump"]) + f" ぶつかるファイル: {'・'.join(said)}"))
        return 1, head
    for n in said:
        print(f"注記: {n}")
    try:
        provision.mark(run.path, run.source, {"base": record["candidate"]}, g)
        run.attrs["base"] = record["candidate"]
    except (gitx.GitError, OSError) as e:
        print(f"注記: メインブランチを知った位置（company.base）を書けなかった（{e}）。次の --land の書き換えのゲートは前の位置で見る")
    _suspects_without(run, {run.branch})
    if step == "onto":
        print(f"束（束ね役 {leader}）で入った中身の上に、その後の commit を移した（{new[:7]}）。残りを入れる")
        return None, new
    print(f"束（束ね役 {leader}）でメインブランチに入った（ブランチ {run.branch} を写し {new[:7]} に替えた）")
    _sweep_batches(run, base)
    run.hold.drop()
    return _tidy(run.cfg, run.repo, ports, run.found, run.path, run.rows, run.reasons, new), new


def catch_up(source, info, main, g):
    """代表の clone の手元のメインブランチを、origin のメインブランチの先頭へそろえる（--deliver の後）。--land の後のそろえと同じく、そろえられなければ
    窓口に台帳の知らせで渡す。部署が --land を通さずに手で push した成果も、代表の clone に届けるため（2026-10-17 の my_notes。
    部署が git push origin HEAD:master で入れ、代表の clone の master が黙って遅れた。受付 d3f166）。取り直せなくても（手元のネットワークの
    誤りなど）、手元の origin/<メインブランチ>（部署の push が書き換える）までそろえる。出す行の並びを返す。"""
    sha, local, err, out = _follow(source, main, g)
    if not sha:
        return out
    if local == "updated":
        out.append(f"代表の clone の {main} をメインブランチ {sha[:7]} へ進めた")
    elif local in LAGS:
        out.append(_tell_desk(source, info, main, sha, local, g, err))
    return out


def _follow(source, main, g, sha=None):
    """メインブランチを取り直し、代表の clone の手元のメインブランチを sha（省けば取り直した origin/<メインブランチ> の先頭）へ fast-forward する。取り直せなくても、
    sha か手元の origin/<メインブランチ> まではそろえる。(sha, 結果, 誤り, 注記の並び)。結果は gitx.advance_branch の値か FAILED。"""
    notes = []
    try:
        land.refresh(source, main, g)
    except gitx.GitError as e:
        notes.append(f"注記: メインブランチ {main} を取り直せなかった（{e}）。手元に在るメインブランチの先頭まで代表の clone をそろえる")
    sha = sha or g.rev(source, f"refs/remotes/origin/{main}")
    if not sha:
        return None, None, None, notes
    try:
        return sha, land.advance_local(source, main, sha, g), None, notes
    except gitx.GitError as e:
        return sha, FAILED, e, notes


def _tell_desk(source, info, main, candidate, local, g, err=None):
    """代表の clone のメインブランチを進められなかったことを、その会社の窓口（本社の --desk の会話）に台帳の知らせで渡す。窓口の会話のフックと
    決まりは代表の clone の作業ツリーから読まれるので、進まないとメインブランチに入れた物が窓口に効かない（5d75df）。出す行を返す。"""
    why, fix = {"dirty": ("git merge --ff-only が断った（書きかけがメインブランチの変更とぶつかるか、merge・rebase の途中など）",
                          f"書きかけを片付けるか commit してから、代表の clone で git merge --ff-only origin/{main} を打つ"),
                "local_only": (f"代表の clone の {main} に、メインブランチに無い commit が有る",
                               f"その commit をメインブランチに入れるか別のブランチに移してから、代表の clone で git merge --ff-only origin/{main} を打つ"),
                FAILED: (f"git が誤りを返した（{err}）",
                         f"代表の clone で git fetch origin {main} と git merge --ff-only origin/{main} を打つ")}[local]
    attrs = g.worktree_attrs(source)
    company = tree.company_name(source, info)
    to = wake.address(company, attrs["name"]) if attrs.get("name") else info.get("desk")   # 会社の形の desk: ほかの会社の窓口が兼ねる
    if not to:
        return f"注記: 代表の clone の {main} をメインブランチ {candidate[:7]} に進められなかった（{why}）。窓口が名付けられていないので知らせていない"
    seen = f"{local} {g.rev(source, f'refs/heads/{main}')}"
    if attrs.get("behind") == seen:
        return f"注記: 代表の clone の {main} を進められなかった（{why}）。同じ形は前に窓口へ知らせたので、知らせ直さない"
    text = (f"知らせ（返事は要らない）: {company} の代表の clone（{source}）の {main} をメインブランチ {candidate[:7]} に進められなかった（{why}）。"
            f"代表の clone の作業ツリーから読むフックと会社の形は前の版のまま。{fix}")
    try:
        far, _ = deliver.parse_target(to)
        inbox = deliver.inbox_of(g.common_dir(source))
        if far and far != company:
            # ほかの会社の窓口: その窓口の居る会社の受付箱の台帳に置く（待ち受けはその会社の台帳を読む）
            inbox = next((deliver.inbox_of(g.common_dir(p)) for p in _company_roots() if tree.company_name(p, tree.read_info(p, None, g)) == far),
                         inbox)
        deliver.log(inbox, wake.notice(to, None, wake.NOTE, None, text, time.time()))
        provision.mark(source, source, {"behind": seen}, g)
    except (gitx.GitError, OSError) as e:
        return f"注記: 代表の clone の {main} を進められなかった（{why}）。窓口に知らせられなかった（{e}）"
    return f"注記: 代表の clone の {main} を進められなかった（{why}）。窓口 {to} に台帳の知らせで渡した"


def _company_roots():
    """herdr に開いている会社の代表の clone の並び（ほかの会社の窓口の受付箱を引く）。読めなければ空。"""
    try:
        return [w["repo_root"] for w in term.workspaces() if w.get("repo_root")]
    except (term.Error, OSError):   # herdr が入っていない（FileNotFoundError）も、知らせを自分の会社の台帳に置く
        return []


def main_again(cfg, repo, name, ports, rows, reasons, config_path, pause, today, checker, keep_removal, after, hold):
    """リベースしたブランチで、--land を頭から回し直す（ゲートも書き換えの取り合いのゲートも、リベースしたブランチでもう一度通す）。
    列の順番（hold）は持ったまま回し直す（列に並び直さない）。"""
    print("リベースしたブランチで、ゲートから回し直す")
    return main(cfg, repo, name, ports, rows, reasons, config_path, pause, today, checker, False, keep_removal, after, hold)


def _rebase_here(ports, place, path, branch, base, main, rules):
    """メインブランチが先に進んだ部署のブランチを、部署の場所で git のリベース（land.auto_rebase）でメインブランチの上に載せ、origin の部署のブランチにも出す。
    リベースした頭の commit を返す。git が機械で解けないぶつかりが残れば、リベースをやめて元のブランチに戻し、部署の会話にリベースを
    頼んで None（今までどおり）。部署の会話の手直しは、git の解けないぶつかりだけに要る（持ち主 2026-10-17「gitとかの機能で
    マージをできるだけ」）。"""
    if not ports.is_clean(path):
        # ゲートを待つ間に部署の会話が書いた（窓口から打った --land）。書きかけをリベースに巻き込まない
        print(_ask(ports, place, land.rebase_text(branch, main, rules["bump"])))
        return None
    try:
        new, left = land.auto_rebase(path, branch, base, ports.git)
    except gitx.GitError as e:
        new, left = None, [f"（{e}）"]
    if new:
        print(f"メインブランチ {main} が先に進んでいたので、ブランチ {branch} を git でメインブランチの上にリベースした（{new[:7]}）"
              + (f"。注記: {'・'.join(left)}" if left else f"。origin の {branch} にも出した"))
        return new
    print(f"メインブランチ {main} が先に進んでいて、git でリベースするとぶつかりが残った（{'・'.join(left)}）。リベースは元に戻した")
    print(_ask(ports, place, land.rebase_text(branch, main, rules["bump"]) + f" ぶつかるファイル: {'・'.join(left)}"))
    return None


def _overwrite_gate(ports, place, attrs, branch, main_sha, head, keep_removal, dry_run=False):
    """書き換えの取り合いのゲート。部署がメインブランチを最後に知った位置（属性 company.base。--task がブランチを作ったときと、この部署の --land の
    後に書く）より後に、ほかの部署がメインブランチへ入れた行を、部署のブランチが消していれば止める文を返す（部署の窓に打ち込む。dry_run なら
    打ち込まない）。通すなら None。位置の記録が無い部署（前の版で立てた部署）は見ずに注記だけを出す（今のメインブランチとの merge-base は、
    リベースした後のブランチではメインブランチの先頭になり、何も見つけないため）。"""
    since = attrs.get("base")
    if not since:
        print("注記: この部署にはメインブランチを知った位置（company.base）の記録が無いので、書き換えの取り合いのゲートは見ない"
              "（前の版で立てた部署。この --land の後から記録する）")
        return None
    try:
        hits = land.taken(place["path"], since, main_sha, head, ports.git)
    except gitx.GitError as e:
        print(f"注記: 書き換えの取り合いのゲートを見られなかった（{e}）")
        return None
    if not hits:
        print(f"書き換えの取り合いのゲート: 通った（{since[:7]} より後にほかの部署が入れた行を、このブランチは消していない）")
        return None
    if keep_removal:
        print(f"書き換えの取り合いのゲート: このブランチはほかの部署が入れた {len(hits)} 行を消すが、--keep-removal で通す")
        return None
    text = land.taken_text(branch, since, hits)
    if dry_run:
        return f"止まる見立て: {text}"
    return _ask(ports, place, text)


def _preview(cfg, repo, ports, found, place, name, rules, main, head, rows, reasons, attrs=None, keep_removal=False):
    """--land --dry-run の見立て。本当の流れ（main）と同じ所で止まると見立てたら、同じ終わりの値を返す。"""
    g, branch, path, source = ports.git, place["branch"], place["path"], repo.source
    if rules["mode"] == "pr":
        if rules["bump"]:
            print("注記: 取り込み方 pr では版を上げない（版上げは PR の側で）")
        print(f"する事: 部署のブランチ {branch}（{head[:7]}）を origin に push し、メインブランチ {main} への PR を出す")
        return 0
    try:
        base = g.remote_rev(source, main)
    except gitx.GitError as e:
        print(f"止めた: origin のメインブランチ {main} を読めない（{e}）")
        return 1
    if base is None:
        print(f"止めた: origin にメインブランチ {main} が無い")
        return 1
    if rules["queue"]:
        print(f"列: 本当に打てば、メインブランチを取り直す前に列 {os.path.join(g.common_dir(source), rules['queue'])} に並び、"
              "push し終えるまで先頭を持つ（空打ちでは並ばない）")
    known = g.rev(source, base) is not None   # 手元に無い commit なら、メインブランチは手元の知らない所へ進んでいる
    print(f"メインブランチ {main}: origin の先頭 {base[:7]}（origin に問い合わせて読んだ。手元の ref は取り直していない）")
    if known and g.is_ancestor(source, head, base):
        print(f"見立て: ブランチ {branch} はもうメインブランチ {main} に入っているので、片付けに進む")
        return _tidy(cfg, repo, ports, found, path, rows, reasons, head, dry_run=True)
    if not (known and g.is_ancestor(source, base, head)):
        print(f"見立て: メインブランチが部署のブランチの祖先でないので、本当に打てば部署の場所で git でリベースしてからゲートに出す（空打ちでは"
              f"リベースしないので、ここで止まる）。機械で解けないぶつかりが残れば、部署に頼む文:\n"
              f"{land.rebase_text(branch, main, rules['bump'])}")
        return 1
    stop = _overwrite_gate(ports, place, attrs or {}, branch, base, head, keep_removal, dry_run=True)
    if stop is not None:
        print(stop)
        return 1
    try:
        got = g.subjects(source, base, head)
        print(f"入れる commit（{len(got)} 件）:\n" + "\n".join(f"- {c}" for c in got))
        if rules["bump"]:
            plan, market = bump.plan(path, g)
            if plan:
                print("上げる版: " + " / ".join(f"{r['name']} {r['old']} → {r['new']}（{r['level']}" + (f"。{r['why']}" if r.get("why") else "") + "）"
                                       for r in plan)
                      + f" / marketplace {market[0]} → {market[1]}（一時の場所で、部署のブランチの先頭の上に commit を足す）")
            else:
                print("上げる版: 無い（版の据え置きが無いので、版を上げる commit は作らない）")
        if rules["gate"] == land.GATE_CHECK:
            print(f"ゲート: 手元の検証 {rules['check']} を、" + ("版を上げた一時の場所" if rules["bump"] else "部署の場所") + "で回す")
        else:
            ref = _gate_ref(rules["gate"], name, branch, path, (main, branch))
            print(f"ゲート: 候補の commit をブランチ {ref} に push し、その run の結末を待つ（緑ならゲートのブランチを消す）")
    except (gitx.GitError, bump.BumpError, OSError, ValueError) as e:
        print(f"止めた: {e}")
        return 1
    print(f"緑なら: メインブランチをもう一度取り直し、まだ祖先ならメインブランチ {main} を候補へ fast-forward して push する。赤なら失敗の要点を部署に頼む")
    if rules["batch"] > 1 and rules["queue"]:
        _preview_batch(g, source, os.path.join(g.common_dir(source), rules["queue"]), rules["batch"], branch, head)
    if rules["after"]:
        print("入れた後の合図: " + "、".join(f"{x['role']}/{x['tool']}" for x in rules["after"]) + " を呼ぶ（片づかなければ AI に回す）")
    return _tidy(cfg, repo, ports, found, path, rows, reasons, head, dry_run=True)


def _preview_batch(g, source, queue, limit, branch, head):
    """--land --dry-run の束の見立て（束の設計 10）。読むだけで、一時の場所を作らない。本当に打てば列の最後に並ぶので、この部署は先に並んだ
    札の束に乗るか、先頭を取って後ろに待つ札を束ねる。今列に待つ札の次の束の見込みと、部署のブランチと merge してぶつかる見込みの札を出す。"""
    waiting = landqueue.alive(queue) if os.path.isdir(queue) else []
    print(f"束: 上限 {limit} 本。本当に打てば列の最後に並び、先に並んだ札の束に乗るか、先頭を取ったときに後ろに待つ札を束ねる（今待つ札 {len(waiting)} 本）")
    if not waiting:
        return
    marks = landqueue.suspects(queue)
    nxt = batch.upcoming([(n, landqueue.who(queue, n)) for n in waiting[1:]], limit, marks)
    name = lambda n: (landqueue.who(queue, n) or (n,))[0] or n   # noqa: E731
    print(f"- 今先頭で進む札: {name(waiting[0])}。次の束の見込み: {'・'.join(name(n) for n in nxt) or '無し'}")
    clash = [name(n) for n in waiting for w in [landqueue.who(queue, n)] if w and w[1] and w[1] != branch
             and g.rev(source, f"refs/heads/{w[1]}") and g.merges_clean(source, head, f"refs/heads/{w[1]}") is False]
    if clash:
        print(f"- 部署のブランチと merge するとぶつかる見込み: {'・'.join(clash)}（同じ束に入れば、ぶつかる札の手前で束を閉じる）")
    if branch in marks:
        print("- このブランチには疑いの印が有る（前の束が赤だった）ので、束に乗らずに 1 本で通る")
    print("- 見積もりは名乗り・疑いの印・merge の見込みだけで見た物で、外れうる（当たらなかったぶつかりは本番の重ねる段で出る）")


def _tidy(cfg, repo, ports, found, path, rows, reasons, landed, dry_run=False):
    """入れた部署を片付ける（--clean の部署の決まりと部品）。片付けられない畳む部署には、入れた印 company.landed（入れた commit）を
    書いて残す。前の --land が残した部署（印の有る部署）も、片付けられる形になっていれば片付ける。終わりの値は入れた部署の分だけ。
    dry_run なら、片付けるか残すかの見立てを出すだけ（印を書かず、片付けない）。"""
    def retire(r):
        return clean.retire(r, repo.source, provision.label(repo, r["branch"]), ports.term, ports.git, chat, ports.account_env)
    notes = []
    all_rows = rows(cfg, repo, ports, found, notes)
    for n in notes:
        print(n)
    me, code = os.path.realpath(path), 0
    row = next((r for r in all_rows if os.path.realpath(r["path"]) == me), None)
    if row is None:
        print(f"部署は残{'す' if dry_run else 'した'}（片付けの候補にならない。会話の属性 company.session も company.job も無い部署は、部署の会話の中から --done を打つと id が書かれる）")
    elif dry_run:
        if row["removable"]:
            print("入れた後、部署を片付ける（--clean と同じ部品）")
        elif row["reason"] == "persistent":
            print(f"部署は残す（{reasons[row['reason']]}）")
        else:
            print(f"部署は残し、入れた印（company.landed）を書く（{reasons[row['reason']]}）")
    elif row["removable"]:
        got = retire(row)
        print("部署を片付けた" if got["removed"] else f"部署を片付けられなかった: {got['detail']}")
        code = 0 if got["removed"] else 1
    elif row["reason"] == "persistent":
        # always の部署は作業場を残す。入れたブランチは、部署が次の頼みでブランチを移った後に消す（sweep_branches）ので、ブランチと入れた commit を書く
        later = "入れたブランチは、部署が次のブランチに移った後の --land か --clean --apply が消す"
        if row["branch"]:
            try:
                # 書くのは部署のブランチの先頭（版を上げる commit はメインブランチの側にだけ在り、部署のブランチの先頭と違う）。
                # ゲートを待つ間に部署が commit を足していれば、先頭は入れた物に含まれない。書くと、入っていない commit ごとブランチが消える
                tip = ports.git.rev(path, "HEAD")
                if ports.git.is_ancestor(path, tip, landed):
                    landed_map = {**clean.landed_of(ports.attrs(path), strict=True), row["branch"]: tip}
                    provision.mark(path, repo.source, {clean.LANDED_BRANCHES: json.dumps(landed_map, ensure_ascii=False)}, ports.git)
                else:
                    later = f"ブランチ {row['branch']} に入れた後の commit が在るので、入れたブランチとは書かない（続きを入れれば消える）"
            except (gitx.GitError, OSError) as e:
                later = f"入れたブランチを書けなかった（{e}）ので、手元のブランチ {row['branch']} は手で消す"
        print(f"部署は残した（{reasons[row['reason']]}）。{later}")
    else:
        try:
            provision.mark(path, repo.source, {"landed": landed}, ports.git)
            later = "片付けられる形になれば（会話が止まった後など）、次の --land（どの部署でも）か --clean --apply が片付ける"
        except (gitx.GitError, OSError) as e:
            later = f"入れた印を書けなかった（{e}）ので、次の --land は拾わない。片付けられる形になれば --clean --apply で片付ける"
        print(f"部署は残した（{reasons[row['reason']]}）。{later}")
    for r in all_rows:
        if os.path.realpath(r["path"]) == me or not r["removable"] or not ports.attrs(r["path"]).get("landed"):
            continue
        who = r["name"] or r["branch"] or r["path"]
        if dry_run:
            print(f"前の --land で残した部署 {who} も片付ける")
            continue
        got = retire(r)
        print(f"前の --land で残した部署 {who} を片付けた" if got["removed"]
              else f"前の --land で残した部署 {who} を片付けられなかった: {got['detail']}")
    if not dry_run:
        for line in sweep_branches(repo, ports, found, apply=True):
            print(line)
    return code


SWEEP_SAID = {"deleted": "消した", "open": "まだ開いている（部署が次のブランチに移った後に消す）", "would": "消せる",
              "moved": "入れた後に commit が有るので消さず、記録から外した", "failed": "git が断った（次に回す）"}


def sweep_branches(repo, ports, found, apply):
    """always の部署が入れ終えた前の手元のブランチを消し（clean.sweep_landed）、残す物を属性に書き戻す。出す行の並び。"""
    rows = clean.sweep_landed(found, ports.attrs, repo.source, apply, ports.git)
    out, written = [], set()
    for r in rows:
        if r["status"] != "open":
            out.append(f"always の部署 {r['name'] or r['path']} の入れ終えたブランチ {r['branch']}: {SWEEP_SAID[r['status']]}")
        if apply and r["path"] not in written:
            try:
                if clean.landed_of(ports.attrs(r["path"]), strict=True) == r["keep"]:
                    continue
                written.add(r["path"])
                provision.mark(r["path"], repo.source,
                               {clean.LANDED_BRANCHES: json.dumps(r["keep"], ensure_ascii=False) if r["keep"] else None}, ports.git)
            except (gitx.GitError, OSError) as e:
                out.append(f"always の部署 {r['name'] or r['path']} の入れたブランチの記録を書き戻せなかった（{e}）")
    return out

