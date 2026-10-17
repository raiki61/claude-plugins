#!/usr/bin/env python3
"""land ノード: 部署の成果を本流（本社の主の枝。main など）に入れる決まりを読み、関門に出し、通れば本流を早送りする。外に書く。

会社の形の設計の 8 章（検証をどこで回すかも会社の形に書く）と 4.10 の 1（部署の畳み方と成果の取り込み）に当たる。
入口の --land（landing.py）が、この順で呼ぶ。
1. 決まりを読む（read_rules）。会社の形のファイル（`.claude/company.toml`、無ければ設定の置き場の companies/）の [land] の表。
   無ければ取り込み方は none（何もしない。前の版と同じ動き）。役ごとに [land.roles.<役>] で欄を替えられる。
2. 本流が部署の枝の祖先でなければ（ほかの部署が先に入れた）、部署の場所で git で載せ直す（auto_rebase）。機械で解けないぶつかりが
   残れば、載せ直しを元に戻して、部署に載せ直しを頼む（ask）。
3. 関門に出す。関門が CI の枝の形（例 release/*。* に部署の名前）なら、その枝へ候補の commit を push し（publish）、その commit の
   run を待つ（wait_gate）。関門が check なら、入口が手元の検証のコマンドを回す。
4. 赤なら、部署に失敗の要点を渡す（ask）。緑で、本流がまだ候補の祖先なら、本流を候補へ早送りして push する（advance）。
   その間に本流が進んでいれば、2 と同じに載せ直して関門から回し直す（載せ直せなければ部署に頼む）。2 つの部署が同時に入れようとしても、本流に入る順は
   早送りで 1 本ずつに決まる。
部署に頼むのは herdr の打ち込み（ask）だけ。頼みと納品の仕組みは別に作るので、ここは打ち込むだけの小さな口にしておく。
"""

import os
import pathlib
import re
import tomllib

MODES = ("ff-after-ci", "pr", "none")
GATE_CHECK = "check"   # 関門を CI でなく手元の検証にする印
BUMPS = ("marketplace",)
FIELDS = ("mode", "gate", "check", "bump", "main")
FAIL_LINES = 20  # 赤の要点に載せる記録の行数
ASK_CHARS = 2000  # 部署に打ち込む文の上限の字数


def _after(raw, path, problems):
    """[[land.after]]（本流に入れた後に呼ぶ道具の並び。受付の設計 5.5）を読む。形の違う項目は problems に書いて外す。"""
    if not isinstance(raw, list):
        problems.append(f"{path}: land.after が表の並び（[[land.after]]）で無い")
        return []
    out = []
    for i, x in enumerate(raw):
        if not (isinstance(x, dict) and all(isinstance(x.get(k), str) and x[k].strip() for k in ("role", "tool"))
                and isinstance(x.get("input", {}), dict)):
            problems.append(f"{path}: land.after[{i}] は role・tool（空でない文字列）と input（表。省けば空）で書く")
            continue
        out.append({"role": x["role"].strip(), "tool": x["tool"].strip(), "input": x.get("input") or {}})
    return out


def read_rules(path, role=None, text=None):
    """会社の形のファイルの [land] の表を読み、役 role の [land.roles.<役>] を上に重ねる。text を渡せば、それを中身として読む
    （tree.read_info が読んだ物。path は注記に出す場所の札）。{mode, gate, check, bump, main, problems}。ファイルが無い・表が
    無ければ mode は none。"""
    out = {"mode": "none", "gate": None, "check": None, "bump": None, "main": None, "after": [], "problems": []}
    if not path or text is None and not os.path.isfile(path):
        return out
    try:
        if text is None:
            with open(path, "rb") as f:
                raw = tomllib.load(f).get("land")
        else:
            raw = tomllib.loads(text).get("land")
    except (OSError, tomllib.TOMLDecodeError) as e:
        out["problems"].append(f"{path}: TOML として読めない（{e}）")
        return out
    if raw is None:
        return out
    if not isinstance(raw, dict):
        out["problems"].append(f"{path}: land が表で無い")
        return out
    out["after"] = _after(raw.get("after", []), path, out["problems"])
    layers = [raw]
    roles = raw.get("roles", {})
    if role and isinstance(roles, dict) and isinstance(roles.get(role), dict):
        layers.append(roles[role])
    for layer in layers:
        for k in FIELDS:
            if k in layer:
                if isinstance(layer[k], str) and layer[k].strip():
                    out[k] = layer[k].strip()
                else:
                    out["problems"].append(f"{path}: land の {k} が空でない文字列で無い")
    if out["mode"] not in MODES:
        out["problems"].append(f"{path}: land.mode は {'・'.join(MODES)} のどれか（{out['mode']} は知らない）")
    if out["mode"] == "ff-after-ci":
        if not out["gate"]:
            out["problems"].append(f"{path}: land.mode が ff-after-ci なのに land.gate（CI の枝の形か check）が無い")
        elif out["gate"] == GATE_CHECK and not out["check"]:
            out["problems"].append(f"{path}: land.gate が check なのに land.check（手元の検証のコマンド）が無い")
        elif out["gate"] != GATE_CHECK and not re.fullmatch(r"[^*]+/\*", out["gate"]):
            out["problems"].append(f"{path}: land.gate は check か、固定の頭の後ろに /* を付けた枝の形（例 release/*）")
    if out["bump"] and out["bump"] not in BUMPS:
        out["problems"].append(f"{path}: land.bump は {'・'.join(BUMPS)} だけ（{out['bump']} は知らない）")
    return out


def gate_branch(gate, name, branch):
    """関門の枝の名前。* に部署の名前を入れる。名前が枝の名前に使えない字を含めば、部署の枝の / を - にした物を入れる。"""
    part = name if name and re.fullmatch(r"[A-Za-z0-9._-]+", name) else branch.replace("/", "-")
    return gate.replace("*", part)


def _inside(cwd, path):
    c, p = pathlib.PurePath(os.path.realpath(cwd)), pathlib.PurePath(os.path.realpath(path))
    return c == p or p in c.parents


def pane_of(panes, place):
    """部署の窓（herdr のペイン）。部署の作業場の中か、部署の場所の中に居るペインのうち、Claude Code の会話を先に。無ければ None。"""
    mine = [p for p in panes if (place.get("workspace") and p.get("workspace_id") == place["workspace"])
            or (p.get("cwd") and _inside(p["cwd"], place["path"]))]
    mine.sort(key=lambda p: p.get("agent") != "claude")
    return mine[0]["pane_id"] if mine else None


def rebase_text(branch, main, bump):
    again = "版は上げずに" if bump else "版を上げ直して"
    return (f"本流 {main} が先に進んだので、枝 {branch} を入れられなかった。{branch} を origin/{main} の上に載せ直し（rebase）、"
            f"{again} push し直して、終わったら知らせて。")


UNRELEASED = "## [Unreleased]"   # 変更の記録（Keep a Changelog の形）の、まだ版に入れていない節の見出し


def resolve_changelog(path):
    """変更の記録（名前が CHANGELOG.md）のぶつかりを、どれも Unreleased の節の頭で起きた物なら解いて書き直し、True。
    載せ直しの途中のぶつかりの印は、<<<<<<< の側が載せ直す先（本流と、もう載せ直した commit）、>>>>>>> の側が今載せ直す commit。
    部署は版を上げない（版は本流に入れる命令が上げる）ので、部署の側の書き足しはいつも Unreleased の頭に在り、本流の側はそこへ
    ほかの部署の書き足しを入れたか、Unreleased を版の見出しにした。解き方は、部署の側の書き足しを Unreleased のすぐ下に、本流の側を
    その後に置く（2026-10-17 に手で 3 度解いた形）。ほかの所のぶつかり・ほかのファイルは解かない（False。部署の会話に頼む）。"""
    if os.path.basename(path) != "CHANGELOG.md":
        return False
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return False
    out, i, solved = [], 0, False
    while i < len(lines):
        if not lines[i].startswith("<<<<<<< "):
            out.append(lines[i])
            i += 1
            continue
        before = [x for x in out if x.strip()]
        if not before or before[-1].strip() != UNRELEASED:
            return False
        try:
            mid = next(j for j in range(i + 1, len(lines)) if lines[j] == "=======")
            end = next(j for j in range(mid + 1, len(lines)) if lines[j].startswith(">>>>>>> "))
        except StopIteration:
            return False
        ours = lines[i + 1:mid]
        if any(x.startswith("## [") for x in lines[mid + 1:end]):
            return False   # 部署の側に版の見出しが在る（部署が版を上げる会社）。ほかの部署の書き足しを部署の版に入れない
        base = next((j for j in range(i + 1, mid) if lines[j].startswith("||||||| ")), None)   # diff3 の形なら共通の祖先を外す
        if base is not None:
            ours = lines[i + 1:base]
        theirs = lines[mid + 1:end]
        while theirs and not theirs[-1].strip():
            theirs.pop()
        out += theirs + [""] + ours
        i, solved = end + 1, True
    if not solved:
        return False
    pathlib.Path(path).write_text("\n".join(out), encoding="utf-8")
    return True


def auto_rebase(place, branch, base, g):
    """部署の場所で、枝を本流 base の上に git で載せ直し、origin の部署の枝も載せ直した物にする。(載せ直した頭の commit か None,
    並び)。並びは、載せ直せなければ解けなかったファイル、載せ直せたら注記（origin に出せなかったなど）。ぶつかりは、git rerere が前の解き方で解いた物と、変更の記録の Unreleased の頭の物（resolve_changelog）
    だけを機械で解く。ほかが残れば載せ直しをやめて元の枝に戻す（部署の会話に頼む）。"""
    old = g.rev(place, "HEAD")
    try:
        ok, files = g.rebase(place, base)
        while not ok:
            left = [f for f in files if not resolve_changelog(os.path.join(place, f))]
            if left:
                g.rebase_abort(place)
                return None, left
            for f in files:
                g.add_path(place, f)
            before = g.rev(place, "HEAD")
            ok, files = g.rebase_continue(place)
            if not ok and not files and g.rev(place, "HEAD") == before:
                g.rebase_abort(place)   # 解けていないファイルが無いのに進まない（空になった commit など）。人に任せる
                return None, ["（git rebase --continue が進まない）"]
    except (g.GitError, OSError) as e:
        if g.rebasing(place):
            g.rebase_abort(place)   # 途中のまま残さない
        return None, [f"（{e}）"]
    new = g.rev(place, "HEAD")
    if new == old:
        return None, ["（載せ直しても枝が動かない）"]
    pushed = None
    if new != old:
        # origin の部署の枝も載せ直した物にする（無ければ作る）。本流へ入れるのには要らないので、出せなくても載せ直しは使う
        try:
            g.push_rebased(place, branch, g.remote_rev(place, branch) or "", new)
        except g.GitError as e:
            pushed = f"origin の {branch} は出せなかった（{e}）"
    return new, [pushed] if pushed else []


def red_text(branch, where, points):
    body = " / ".join(x.strip() for x in points if x.strip())
    text = f"関門（{where}）が赤だったので、枝 {branch} を本流に入れなかった。直して push し直し、終わったら知らせて。失敗の要点: {body}"
    return text[:ASK_CHARS]


TAKEN_SHOWN = 12   # 部署に打ち込む「消す行」の上限の数


def _hunks(text):
    """git diff -U0 の字から、ファイルごとの (古い側の始まり, 数, 新しい側の始まり, 数, その hunk の行の並び)。"""
    out, path, cur = {}, None, None
    for line in (text or "").splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else path   # 消したファイル（+++ /dev/null）は diff --git の行の名前のまま
        elif line.startswith("--- "):
            continue
        elif line.startswith("diff --git "):
            path = line.split(" b/", 1)[1] if " b/" in line else None
        elif line.startswith("@@") and path is not None:
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                cur = (int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1), [])
                out.setdefault(path, []).append(cur)
        elif cur is not None and line[:1] in "+-":
            cur[4].append(line)
    return out


def taken(source, since, main, head, g):
    """since（部署が本流を最後に知った位置）より後に本流へ入った行のうち、部署の枝（main から head への差分）が消す行。
    [{path, line（main での行番号）, text, commit, subject}]。部署が前に読んだ中身を覚えたまま書き直すと、ほかの部署がその間に
    入れた行を消しても git の衝突にならず、関門の試験も通る（まっさらな環境での 2 回目の試しの 5）ので、行の出どころで見る。"""
    added = {}
    for path, hunks in _hunks(g.diff_zero(source, since, main)).items():
        nums = added.setdefault(path, {})
        for _, _, new_start, new_count, lines in hunks:
            texts = [x[1:] for x in lines if x.startswith("+")]
            for i in range(new_count):
                nums[new_start + i] = texts[i] if i < len(texts) else ""
    out = []
    for path, hunks in _hunks(g.diff_zero(source, main, head)).items():
        if path not in added:
            continue
        for old_start, old_count, _, _, _ in hunks:
            for n in range(old_start, old_start + old_count):
                if n in added[path]:
                    sha, subject = g.blame_line(source, main, path, n)
                    out.append({"path": path, "line": n, "text": added[path][n], "commit": sha, "subject": subject})
    return out


def taken_text(branch, since, hits):
    """部署の窓に打ち込む、消す行の知らせ。"""
    shown = " / ".join(f"{h['path']}:{h['line']}「{' '.join(h['text'].split())[:60]}」（{(h['commit'] or '-')[:7]} "
                       f"{(h['subject'] or '')[:40]}）" for h in hits[:TAKEN_SHOWN])
    more = f" ほか {len(hits) - TAKEN_SHOWN} 行" if len(hits) > TAKEN_SHOWN else ""
    text = (f"枝 {branch} を本流に入れる前に止めた。この部署が本流を最後に知った後（{since[:7]}）にほかの部署が本流へ入れた行を、"
            f"この枝が消している: {shown}{more}。前に読んだ中身で書き直していないかを確かめ、その行を残す形に取り込み直して push し、"
            "--land を打ち直す。わざと消すなら --land <部署の名前> --keep-removal で入れる。")
    return text[:ASK_CHARS]


def ask(pane, text, h):
    """部署の窓に頼みを打ち込む（herdr agent prompt。待たない）。"""
    return h.prompt(pane, " ".join(text.split()), False)


def publish(source, sha, ref, g):
    """候補の commit を origin の関門の枝へ出す（前に出した物は上書きする。関門の枝は取り込みの命令の持ち物）。"""
    g.push(source, sha, ref, force=True)


def ci_on(root, gate):
    """関門の枝の頭（release/* なら release/）を、root の GitHub Actions の設定（.github/workflows）のどれかが書いているか。
    書いていなければ、関門の枝に push しても run が起きないので待たない（待つ回数に上限を置かないため、先に確かめる）。"""
    head = gate.split("*", 1)[0]
    flows = pathlib.Path(root, ".github", "workflows")
    files = sorted(flows.glob("*.yml")) + sorted(flows.glob("*.yaml")) if flows.is_dir() else []
    return any(head in f.read_text(encoding="utf-8", errors="replace") for f in files)


def wait_gate(repo, ref, sha, gh, env=None, pause=lambda: None):
    """その枝のその commit の run が現れるまで見に行き（回数に上限を置かない。CI が起きる設定は ci_on で先に確かめる）、
    終わりを待つ。{result: green・red, run}。"""
    while True:
        got = gh.runs_for(repo, ref, sha, env=env)
        if got:
            run = got[0]
            break
        pause()
    if run.get("status") != "completed":
        run = gh.watch_run(repo, run["id"], env=env)
    return {"result": "green" if run.get("conclusion") == "success" else "red", "run": run}


def advance(source, main, sha, g):
    """origin の本流を sha へ早送りして push する（origin が先に進んでいれば git が断る。GitError）。"""
    g.push(source, sha, main)


def follow(source, main, sha, g):
    """push した後に、手元の origin/<本流> と手元の本流をそろえる。手元の本流の結果（gitx.advance_branch の値）を返す。"""
    g.fetch(source, main)
    return g.advance_branch(source, main, sha)


def drop_gate(source, ref, g):
    """入れた後の関門の枝を origin から消す。"""
    return g.drop_remote(source, ref)


def offer_pr(source, repo, branch, main, g, gh, env=None):
    """部署の枝を origin に出し、本流への PR を出す。PR の URL を返す。"""
    g.push(source, g.rev(source, f"refs/heads/{branch}"), branch)
    return gh.create_pr(repo, branch, main, env=env)


def stage(source, path, sha, g):
    """版を上げる commit を作る一時の場所を sha で作る。"""
    g.add_detached(source, path, sha)


def unstage(source, path, g):
    g.remove_detached(source, path)


def refresh(source, main, g):
    """origin の本流を取り直し、その commit を返す。"""
    g.fetch(source, main)
    return g.rev(source, f"refs/remotes/origin/{main}")
