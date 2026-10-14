"""herdr への口。dispatch で herdr を呼ぶのはこの 1 か所だけ（設計書 4 節）。

herdr は版が 0.x で互換を約束していない。herdr の文書は、手元の版の API を `herdr api schema` で確かめるよう求めている。
出力の形が変わって壊れたら、直すのはこのファイルだけになる。出力の形は 2026-10-14 に herdr 0.9.3 の実物で読んだ。

書く関数は run・prompt・create_workspace・close_workspace で、呼んでよいノードは柵（tests/fences.py の D4 の表）が構文木で見る。
"""

import json
import subprocess

STALLED = "agent_prompt_stalled"


class HerdrError(Exception):
    def __init__(self, argv, detail):
        super().__init__(f"{' '.join(argv[:3])}: {detail}")
        self.argv = argv
        self.detail = detail


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env)


def _error_code(text):
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return None
    err = obj.get("error") if isinstance(obj, dict) else None
    return err.get("code") if isinstance(err, dict) else None


def _call(argv, runner):
    """herdr を呼び、成功なら result を返す。失敗は (code, 文) を持つ HerdrError。"""
    p = runner(argv)
    if p.returncode != 0:
        code = _error_code(p.stdout) or _error_code(p.stderr)
        raise HerdrError(argv, code or (p.stderr or p.stdout).strip()[:300])
    try:
        return json.loads(p.stdout).get("result", {})
    except (ValueError, AttributeError):
        raise HerdrError(argv, f"JSON でない出力: {p.stdout[:200]!r}")


def panes(runner=_default_runner):
    out = []
    for p in _call(["herdr", "pane", "list"], runner).get("panes", []):
        out.append({**p, "agent": p.get("agent")})
    return out


def workspace_labels(runner=_default_runner):
    ws = _call(["herdr", "workspace", "list"], runner).get("workspaces", [])
    return {w["workspace_id"]: w.get("label") for w in ws}


def agent(target, runner=_default_runner):
    """1 つのペインのエージェントの情報（agent・agent_status など）。"""
    return _call(["herdr", "agent", "get", target], runner).get("agent", {})


def methods(runner=_default_runner):
    """手元の herdr の API のメソッドの名の集合（始める前の確かめに使う）。"""
    p = runner(["herdr", "api", "schema", "--json"])
    if p.returncode != 0:
        raise HerdrError(["herdr", "api", "schema"], (p.stderr or p.stdout).strip()[:300])
    found = set()

    def walk(x):
        if isinstance(x, dict):
            m = x.get("method")
            if isinstance(m, dict) and isinstance(m.get("const"), str):
                found.add(m["const"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(json.loads(p.stdout))
    return found


def run(pane, command, runner=_default_runner):
    """ペインのシェルにコマンドを打ち込み、Enter まで送る。書く口その 1。"""
    _call(["herdr", "pane", "run", pane, command], runner)


def wait_ready(pane, runner=_default_runner):
    """起こした直後に、会話が見つかって入力を待つまで待ち、状態を返す。

    会話が見つかる前のペインに効くかは、持ち主の前の確かめ（計画の Task 10）で決める。
    """
    return _call(["herdr", "agent", "wait", pane, "--until", "idle"], runner).get("agent", {}).get("agent_status", "idle")


def prompt(target, text, wait, runner=_default_runner):
    """会話にプロンプトを送る。書く口その 2。文は argv の 1 つでそのまま渡し、シェルを通さない。

    wait が真なら、送った後に動き出したのを見てから止まるまで待ち、その状態（idle・done・blocked）を返す。
    herdr の組み込みの見張りが返す agent_prompt_stalled は、誤りではなく "stalled" の状態として返す。
    wait が偽なら "sent"。
    """
    argv = ["herdr", "agent", "prompt", target, text] + (["--wait"] if wait else [])
    try:
        result = _call(argv, runner)
    except HerdrError as e:
        if e.detail == STALLED:
            return "stalled"
        raise
    if not wait:
        return "sent"
    return result.get("agent", {}).get("agent_status", "idle")


def create_workspace(cwd, label, runner=_default_runner):
    """作業フォルダを cwd にして herdr の作業場を開く（前に出さない）。{"workspace_id", "pane_id"} を返す。書く口。"""
    r = _call(["herdr", "workspace", "create", "--cwd", cwd, "--label", label, "--no-focus"], runner)
    ws = r.get("workspace", {})
    pane = r.get("root_pane", {})
    return {"workspace_id": ws.get("workspace_id"), "pane_id": pane.get("pane_id")}


def close_workspace(workspace_id, runner=_default_runner):
    """herdr の作業場を閉じる。書く口。"""
    _call(["herdr", "workspace", "close", workspace_id], runner)
