#!/usr/bin/env python3
"""land ノード: 部署の成果を本流（本社の主の枝。main など）に入れる決まりを読み、関門に出し、通れば本流を早送りする。外に書く。

会社の形の設計の 8 章（検証をどこで回すかも会社の形に書く）と 4.10 の 1（部署の畳み方と成果の取り込み）に当たる。
入口の --land（landing.py）が、この順で呼ぶ。
1. 決まりを読む（read_rules）。会社の形のファイル（`.claude/company.toml`、無ければ設定の置き場の companies/）の [land] の表。
   無ければ取り込み方は none（何もしない。前の版と同じ動き）。役ごとに [land.roles.<役>] で欄を替えられる。
2. 本流が部署の枝の祖先でなければ（ほかの部署が先に入れた）、関門に出さずに、部署に載せ直しを頼む（ask）。
3. 関門に出す。関門が CI の枝の形（例 release/*。* に部署の名前）なら、その枝へ候補の commit を push し（publish）、その commit の
   run を待つ（wait_gate）。関門が check なら、入口が手元の検証のコマンドを回す。
4. 赤なら、部署に失敗の要点を渡す（ask）。緑で、本流がまだ候補の祖先なら、本流を候補へ早送りして push する（advance）。
   その間に本流が進んでいれば、自分では merge せず、部署に載せ直しを頼む。2 つの部署が同時に入れようとしても、本流に入る順は
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


def read_rules(path, role=None, text=None):
    """会社の形のファイルの [land] の表を読み、役 role の [land.roles.<役>] を上に重ねる。text を渡せば、それを中身として読む
    （tree.read_info が読んだ物。path は注記に出す場所の札）。{mode, gate, check, bump, main, problems}。ファイルが無い・表が
    無ければ mode は none。"""
    out = {"mode": "none", "gate": None, "check": None, "bump": None, "main": None, "problems": []}
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


def red_text(branch, where, points):
    body = " / ".join(x.strip() for x in points if x.strip())
    text = f"関門（{where}）が赤だったので、枝 {branch} を本流に入れなかった。直して push し直し、終わったら知らせて。失敗の要点: {body}"
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
