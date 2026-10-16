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
7. 入れたら、都度の部署は --clean と同じ部品（clean.departments・clean.retire）で片付ける。常駐の部署は残す。
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
from nodes import bump, clean, land, provision, tree

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
        checker=run_check):
    """--land <名前>。rows は dispatch._department_rows、reasons は片付けで残す訳（dispatch.DEPT_REASONS）。"""
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
    if rules["problems"]:
        print("止めた（取り込みの決まりが読めない）:\n" + "\n".join(f"- {p}" for p in rules["problems"]))
        return 2
    gate = rules["gate"] or "-"
    print(f"部署 {attrs.get('name') or name}（枝 {branch or '-'}）: 取り込み方 {rules['mode']}、関門 {gate}"
          + (f"、版上げ {rules['bump']}" if rules["bump"] else ""))
    if rules["mode"] == "none":
        print("取り込みの決まりが none なので、何もしない（会社の形の [land] で決める）")
        return 0
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
        return _tidy(cfg, repo, ports, found, path, rows, reasons)
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
    return _tidy(cfg, repo, ports, found, path, rows, reasons)


def _tidy(cfg, repo, ports, found, path, rows, reasons):
    """入れた部署を片付ける（--clean の部署の決まりと部品）。"""
    notes = []
    row = next((r for r in rows(cfg, repo, ports, found, notes) if os.path.realpath(r["path"]) == os.path.realpath(path)), None)
    for n in notes:
        print(n)
    if row is None:
        print("部署は残した（片付けの候補にならない。会話の属性 company.session が無い部署は手で片付ける）")
        return 0
    if not row["removable"]:
        print(f"部署は残した（{reasons[row['reason']]}）")
        return 0
    got = clean.retire(row, repo.source, provision.label(repo, row["branch"]), ports.herdr, ports.git, claudex)
    print("部署を片付けた" if got["removed"] else f"部署を片付けられなかった: {got['detail']}")
    return 0 if got["removed"] else 1

