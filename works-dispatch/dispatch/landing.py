#!/usr/bin/env python3
"""入口の --land（部署の成果を本流に入れる）の流れ。dispatch.py の一部で、同じ入口の層に置く（ほかの部署と同時に dispatch.py を
触るぶつかりを減らすため、別のファイルにした）。ノード（nodes/land.py・nodes/bump.py・nodes/clean.py）を並べる順だけを持つ。

順（会社の形の設計 8 章。決まりの欄は nodes/land.py の read_rules）:
1. 部署を名前（属性 company.name）か枝の名前で探し、会社の形の [land] を、部署の役で読む。取り込み方が none なら何もしない。
2. pr: 部署の枝を origin に出し、本流への PR を出して止める。
3. ff-after-ci: 本流を取り直す。もう入っていれば片付けへ。本流が部署の枝の祖先でなければ、部署に載せ直しを頼んで止める。
4. 版上げ（bump = "marketplace"）があれば、一時の場所で部署の枝の先頭の上に版を上げる commit を作る（部署の枝は動かさない）。
5. 関門: CI の枝の形なら、その枝の頭を GitHub Actions の設定が書いていることを確かめ、その枝へ候補を push して run を待つ。check なら、手元の検証のコマンドを候補の場所で回す。
6. 赤なら、部署に失敗の要点を頼む。緑なら本流を取り直し、まだ祖先なら本流を早送りして push する（関門の枝は消す）。
   進んでいれば、部署に載せ直しを頼む。
7. 入れたら、都度の部署は --clean と同じ部品（clean.departments・clean.retire）で片付ける。常駐の部署は残す。片付けられない
   都度の部署（納品の直後で会話がまだ止まりきっていない、など）には入れた印（属性 company.landed）を書いて残し、次の --land
   （どの部署でも）が、片付けられる形になっていれば一緒に片付ける。止まるのを待たないのは、こちらから期限を足さないため（D5）。

--dry-run（_preview）は 1 の後で分かれ、決まりと、することの見立て（載せ直しが要るか・入れる commit・上げる版・関門・片付け）を
出すだけにする。何も書かない: 本流の先頭は fetch せず origin に問い合わせて読み（ls-remote。手元の ref は変えない）、版は
一時の場所を作らず、部署の場所で本当の流れと同じ bump.plan を回して見積もり、関門に出さず、手元の検証を回さず、
部署の窓（herdr のペイン）に打ち込まず、片付けない。本当の流れが止まる所と、見立てそのものの失敗では 1 を返す。
"""

import datetime
import os
import shutil
import subprocess
import tempfile
import time

import claudex
import config
import ghx
import gitx
import herdr
from nodes import bump, clean, land, provision, role, tree

RUN_PAUSE_S = 10  # 関門の枝に push した後、run が現れるのを見に行く間


def run_check(command, cwd):
    """手元の検証のコマンドを cwd で回す。(終わりの値, 出力)。"""
    p = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _ask(ports, place, text):
    """部署の窓に打ち込む。窓が無い・打ち込めなければ、文を出して呼んだ側に渡させる。"""
    try:
        pane = land.pane_of(ports.herdr.panes(), place)
        if pane:
            land.ask(pane, text, ports.herdr)
            return f"部署の窓 {pane} に頼んだ: {text}"
    except herdr.HerdrError as e:
        return f"部署の窓に打ち込めなかった（{e}）。次の文を部署に渡す: {text}"
    return f"部署の窓が herdr に無いので打ち込めなかった。次の文を部署に渡す: {text}"


def _find(found, name, attrs_of):
    hits = []
    for p in found:
        if p.get("linked") and not p.get("prunable"):
            a = attrs_of(p["path"])
            if a.get("name") == name or p.get("branch") == name:
                hits.append((p, a))
    return hits


def main(cfg, repo, name, ports, rows, reasons, config_path=None, pause=lambda: time.sleep(RUN_PAUSE_S), today=None,
        checker=run_check, dry_run=False):
    """--land <名前>。rows は dispatch._department_rows、reasons は片付けで残す訳（dispatch.DEPT_REASONS）。
    dry_run なら、することの見立てを出すだけで何も書かない（_preview）。"""
    g, out = ports.git, []
    try:
        found = ports.places(repo)
    except herdr.HerdrError as e:
        print(f"止めた: 元の clone の worktree を読めない（{e}）")
        return 1
    hits = _find(found, name, ports.attrs)
    if len(hits) != 1:
        print(f"止めた: 部署 {name} が" + ("無い（名前か枝の名前で探した）" if not hits else f" {len(hits)} つ在る（枝の名前で指す）"))
        return 1
    place, attrs = hits[0]
    branch, path, source = place.get("branch"), place["path"], repo.source
    info = tree.read_info(source, os.path.dirname(config.path_of(config_path, os.environ)))
    rules = land.read_rules(info.get("path"), attrs.get("role"), info.get("text"))
    for n in info["notes"]:
        print(f"注記: {n}")
    if rules["problems"]:
        print("止めた（取り込みの決まりが読めない）:\n" + "\n".join(f"- {p}" for p in rules["problems"]))
        return 2
    # gh のアカウントは --task と同じ決め方（dispatch の設定の [[repos]] の gh_user を先に、無ければ会社の形の gh_user）
    repo = repo._replace(gh_user=role.gh_user(repo.gh_user, role.load(info.get("path"), info.get("text")))[0])
    gate = rules["gate"] or "-"
    print(f"部署 {attrs.get('name') or name}（枝 {branch or '-'}）: 取り込み方 {rules['mode']}、関門 {gate}"
          + (f"、版上げ {rules['bump']}" if rules["bump"] else ""))
    if rules["mode"] == "none":
        print("取り込みの決まりが none なので、何もしない（会社の形の [land] で決める）")
        return 0
    if dry_run:
        print("空打ち（--dry-run）: することを見立てるだけで、何も書かない・push しない・部署に頼まない")
    if not branch:
        print("止めた: 部署が枝に乗っていない")
        return 1
    if not ports.is_clean(path):
        print("止めた: 部署の場所に未コミットの変更か git に足していないファイルが有る")
        return 1
    try:
        main = rules["main"] or ports.default_branch(repo)
        env = ports.gh_env(repo)
        head = g.rev(path, "HEAD")
        if dry_run:
            return _preview(cfg, repo, ports, found, place, attrs.get("name") or name, rules, main, head, rows, reasons)
        if rules["mode"] == "pr":
            if rules["bump"]:
                print("注記: 取り込み方 pr では版を上げない（版上げは PR の側で）")
            print(f"PR を出した: {land.offer_pr(source, repo.repo, branch, main, g, ports.gh, env)}")
            return 0
        base = land.refresh(source, main, g)
    except (gitx.GitError, ghx.GhError) as e:
        print(f"止めた: {e}")
        return 1
    if g.is_ancestor(source, head, base):
        print(f"枝 {branch} はもう本流 {main} に入っている")
        return _tidy(cfg, repo, ports, found, path, rows, reasons, head)
    if not g.is_ancestor(source, base, head):
        print(_ask(ports, place, land.rebase_text(branch, main, rules["bump"])))
        return 1

    candidate, stage, where = head, None, path
    try:
        if rules["bump"]:
            stage = tempfile.mkdtemp(prefix="dispatch-land-")
            land.stage(source, stage, head, g)
            where = stage
            got = bump.make(stage, today or datetime.date.today().isoformat(), g)
            if got["sha"]:
                candidate = got["sha"]
                print(f"版を上げた: {got['subject']}（commit {candidate[:7]}）")
            else:
                print("版の据え置きは無い（版を上げる commit は作らない）")
        if rules["gate"] == land.GATE_CHECK:
            code, said = checker(rules["check"], where)
            verdict = {"result": "green" if code == 0 else "red"}
            label = f"手元の検証 {rules['check']}"
            points = said.splitlines()[-land.FAIL_LINES:]
        else:
            ref = land.gate_branch(rules["gate"], attrs.get("name") or name, branch)
            if ref in (main, branch):
                raise ValueError(f"関門の枝 {ref} が本流か部署の枝と同じ名前になる（land.gate の頭を替える）")
            if not land.ci_on(where, rules["gate"]):
                raise ValueError(f"関門の枝 {ref} に push しても CI が起きない（.github/workflows のどれも "
                                 f"{rules['gate'].split('*', 1)[0]} を書いていない）")
            land.publish(source, candidate, ref, g)
            print(f"関門に出した: {ref}（commit {candidate[:7]}）")
            verdict = land.wait_gate(repo.repo, ref, candidate, ports.gh, env, pause)
            label = f"CI {ref}" + (f" {verdict['run'].get('url')}" if verdict.get("run") else "")
            points = ports.gh.run_failure(repo.repo, verdict["run"]["id"], land.FAIL_LINES, env=env) \
                if verdict["result"] == "red" else []
    except (gitx.GitError, ghx.GhError, bump.BumpError, OSError, ValueError) as e:
        print(f"止めた: {e}")
        return 1
    finally:
        if stage:
            try:
                land.unstage(source, stage, g)
            except gitx.GitError as e:
                print(f"注記: 一時の場所 {stage} を消せなかった（{e}）")
            shutil.rmtree(stage, ignore_errors=True)
    print(f"関門（{label}）: {'緑' if verdict['result'] == 'green' else '赤'}")
    if verdict["result"] == "red":
        print(_ask(ports, place, land.red_text(branch, label, points)))
        return 1
    try:
        base = land.refresh(source, main, g)
    except gitx.GitError as e:
        print(f"止めた: 本流を取り直せない（{e}）")
        return 1
    if not g.is_ancestor(source, base, candidate):
        print(_ask(ports, place, land.rebase_text(branch, main, rules["bump"])))
        return 1
    try:
        land.advance(source, main, candidate, g)
    except gitx.GitError as e:
        # 断られた訳を、本流を取り直して分ける: 先に進んでいれば載せ直しを頼み、そうでなければ（枝の保護・認証など）止める
        try:
            moved = not g.is_ancestor(source, land.refresh(source, main, g), candidate)
        except gitx.GitError:
            moved = False
        if moved:
            print(_ask(ports, place, land.rebase_text(branch, main, rules["bump"])))
        else:
            print(f"止めた: 本流 {main} への push が断られた（{e}）")
        return 1
    try:
        local = land.follow(source, main, candidate, g)
    except gitx.GitError as e:
        local = f"そろえられなかった: {e}"
    print(f"本流 {main} を {candidate[:7]} へ早送りして push した（手元の {main}: {local}）")
    if rules["gate"] != land.GATE_CHECK:
        try:
            land.drop_gate(source, ref, g)
        except gitx.GitError as e:
            print(f"注記: 関門の枝 {ref} を消せなかった（{e}）")
    return _tidy(cfg, repo, ports, found, path, rows, reasons, candidate)


def _preview(cfg, repo, ports, found, place, name, rules, main, head, rows, reasons):
    """--land --dry-run の見立て。本当の流れ（main）と同じ所で止まると見立てたら、同じ終わりの値を返す。"""
    g, branch, path, source = ports.git, place["branch"], place["path"], repo.source
    if rules["mode"] == "pr":
        if rules["bump"]:
            print("注記: 取り込み方 pr では版を上げない（版上げは PR の側で）")
        print(f"する事: 部署の枝 {branch}（{head[:7]}）を origin に push し、本流 {main} への PR を出す")
        return 0
    try:
        base = g.remote_rev(source, main)
    except gitx.GitError as e:
        print(f"止めた: origin の本流 {main} を読めない（{e}）")
        return 1
    if base is None:
        print(f"止めた: origin に本流 {main} が無い")
        return 1
    known = g.rev(source, base) is not None   # 手元に無い commit なら、本流は手元の知らない所へ進んでいる
    print(f"本流 {main}: origin の先頭 {base[:7]}（origin に問い合わせて読んだ。手元の ref は取り直していない）")
    if known and g.is_ancestor(source, head, base):
        print(f"見立て: 枝 {branch} はもう本流 {main} に入っているので、片付けに進む")
        return _tidy(cfg, repo, ports, found, path, rows, reasons, head, dry_run=True)
    if not (known and g.is_ancestor(source, base, head)):
        print(f"見立て: 本流が部署の枝の祖先でないので、関門に出さずに止まる（載せ直しが要る）。部署に頼む文:\n"
              f"{land.rebase_text(branch, main, rules['bump'])}")
        return 1
    try:
        got = g.subjects(source, base, head)
        print(f"入れる commit（{len(got)} 件）:\n" + "\n".join(f"- {c}" for c in got))
        if rules["bump"]:
            plan, market = bump.plan(path, g)
            if plan:
                print("上げる版: " + " / ".join(f"{r['name']} {r['old']} → {r['new']}（{r['level']}）" for r in plan)
                      + f" / marketplace {market[0]} → {market[1]}（一時の場所で、部署の枝の先頭の上に commit を足す）")
            else:
                print("上げる版: 無い（版の据え置きが無いので、版を上げる commit は作らない）")
        if rules["gate"] == land.GATE_CHECK:
            print(f"関門: 手元の検証 {rules['check']} を、" + ("版を上げた一時の場所" if rules["bump"] else "部署の場所") + "で回す")
        else:
            ref = land.gate_branch(rules["gate"], name, branch)
            if ref in (main, branch):
                raise ValueError(f"関門の枝 {ref} が本流か部署の枝と同じ名前になる（land.gate の頭を替える）")
            if not land.ci_on(path, rules["gate"]):
                raise ValueError(f"関門の枝 {ref} に push しても CI が起きない（.github/workflows のどれも "
                                 f"{rules['gate'].split('*', 1)[0]} を書いていない）")
            print(f"関門: 候補の commit を枝 {ref} に push し、その run の結末を待つ（緑なら関門の枝を消す）")
    except (gitx.GitError, bump.BumpError, OSError, ValueError) as e:
        print(f"止めた: {e}")
        return 1
    print(f"緑なら: 本流をもう一度取り直し、まだ祖先なら本流 {main} を候補へ早送りして push する。赤なら失敗の要点を部署に頼む")
    return _tidy(cfg, repo, ports, found, path, rows, reasons, head, dry_run=True)


def _tidy(cfg, repo, ports, found, path, rows, reasons, landed, dry_run=False):
    """入れた部署を片付ける（--clean の部署の決まりと部品）。片付けられない都度の部署には、入れた印 company.landed（入れた commit）を
    書いて残す。前の --land が残した部署（印の有る部署）も、片付けられる形になっていれば片付ける。終わりの値は入れた部署の分だけ。
    dry_run なら、片付けるか残すかの見立てを出すだけ（印を書かず、片付けない）。"""
    notes = []
    all_rows = rows(cfg, repo, ports, found, notes)
    for n in notes:
        print(n)
    me = os.path.realpath(path)
    row = next((r for r in all_rows if os.path.realpath(r["path"]) == me), None)
    if row is None:
        print(f"部署は残{'す' if dry_run else 'した'}（片付けの候補にならない。会話の属性 company.session が無い部署は手で片付ける）")
        code = 0
    elif dry_run:
        if row["removable"]:
            print("入れた後、部署を片付ける（--clean と同じ部品）")
        elif row["reason"] == "resident":
            print(f"部署は残す（{reasons[row['reason']]}）")
        else:
            print(f"部署は残し、入れた印（company.landed）を書く（{reasons[row['reason']]}）")
        code = 0
    elif row["removable"]:
        got = clean.retire(row, repo.source, provision.label(repo, row["branch"]), ports.herdr, ports.git, claudex)
        print("部署を片付けた" if got["removed"] else f"部署を片付けられなかった: {got['detail']}")
        code = 0 if got["removed"] else 1
    elif row["reason"] == "resident":
        print(f"部署は残した（{reasons[row['reason']]}）")
        code = 0
    else:
        try:
            provision.mark(path, repo.source, {"landed": landed}, ports.git)
            later = "片付けられる形になれば（会話が止まった後など）、次の --land（どの部署でも）か --clean --apply が片付ける"
        except (gitx.GitError, OSError) as e:
            later = f"入れた印を書けなかった（{e}）ので、次の --land は拾わない。片付けられる形になれば --clean --apply で片付ける"
        print(f"部署は残した（{reasons[row['reason']]}）。{later}")
        code = 0
    for r in all_rows:
        if os.path.realpath(r["path"]) == me or not r["removable"] or not ports.attrs(r["path"]).get("landed"):
            continue
        who = r["name"] or r["branch"] or r["path"]
        if dry_run:
            print(f"前の --land で残した部署 {who} も片付ける")
            continue
        got = clean.retire(r, repo.source, provision.label(repo, r["branch"]), ports.herdr, ports.git, claudex)
        print(f"前の --land で残した部署 {who} を片付けた" if got["removed"]
              else f"前の --land で残した部署 {who} を片付けられなかった: {got['detail']}")
    return code

