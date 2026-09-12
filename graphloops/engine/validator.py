"""graph が宣言する plugin の中の物（記録の検証器 scripts/<loop>-record.py・役割 agent の定義 agents/<役>.md）の探し方と、検証器の呼び方、報告前の仕上げ。"""
import glob
import json
import os
import pathlib
import re
import subprocess
import sys

from .rules import hook
from .util import PLUGIN_ROOT, die

VALIDATOR_TIMEOUT = 600  # 秒


def env_root(plugin):
    """plugin の置き場を指す環境変数の名前（convergence-loops → CONVERGENCE_LOOPS_ROOT）。"""
    return plugin.upper().replace("-", "_") + "_ROOT"


def _sibling_is(plugin):
    """この plugin と同じリポジトリに並ぶ plugin か（親の plugin.json の name で見る）。"""
    try:
        return json.loads((PLUGIN_ROOT.parent / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("name") == plugin
    except (OSError, ValueError):
        return False


def find_plugin_path(rel, plugin, explicit=None, kind="file"):
    """plugin の中のファイルかディレクトリを順に探す: 明示 → <PLUGIN>_ROOT → 同じリポジトリに並ぶ plugin → インストール済みキャッシュの最新版。
    plugin が無ければ明示だけ。"""
    cands = []
    if explicit:
        cands.append(pathlib.Path(explicit))
    if plugin:
        env = os.environ.get(env_root(plugin))
        if env:
            cands.append(pathlib.Path(env) / rel)
        if _sibling_is(plugin):
            cands.append(PLUGIN_ROOT.parent / rel)
        # キャッシュは**実行中のプロファイル 1 つ**だけ見る（CLAUDE_CONFIG_DIR、既定は ~/.claude）。
        # 以前は ~/.claude* を横断していたので、別プロファイル・別マーケットプレイスの同名プラグインが
        # 版の大小だけで選ばれ、動いている出所と無関係なコードが importlib でこのプロセスに読み込まれた。
        cfg = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or (pathlib.Path.home() / ".claude"))
        hits = glob.glob(str(cfg / "plugins" / "cache" / "*" / plugin / "*" / rel))
        depth = len(pathlib.Path(rel).parts)

        def _ver(p):
            # 版ディレクトリ名。数値でない部分が混ざっても TypeError で落とさない（比較できる形に揃える）
            name = pathlib.Path(p).parents[depth - 1].name
            return [(0, int(x)) if x.isdigit() else (1, x) for x in re.split(r"[.\-]", name)]

        hits.sort(key=_ver, reverse=True)
        # 出所（マーケットプレイス）が複数に跨がったら選ばない——明示を求める
        origins = {pathlib.Path(h).parents[depth].parent.name for h in hits}
        if len(origins) > 1:
            die(f"{plugin} の {rel} が複数の出所に在る（{sorted(origins)}）——どれを使うか --validator で明示しろ")
        cands += [pathlib.Path(h) for h in hits]
    for c in cands:
        if c.is_file() if kind == "file" else c.is_dir():
            return str(c.resolve())
    return None


def find_validator(loop, plugin, explicit=None):
    """検証器の名前は <loop>-record.py で、loop 名の末尾の -loop は付かない（research-loop → research-record.py）。"""
    loop = loop[:-5] if loop.endswith("-loop") else loop
    return find_plugin_path(f"scripts/{loop}-record.py", plugin, explicit=explicit)


def agent_def(agent_type):
    """役割 agent の定義（<plugin>:<役> の agents/<役>.md）を読む——道具・モデル・effort と本文（役の指示）。

    None = 定義が見つからない（接頭の無い組み込み agent を含む）。tools の行が無い定義は全部を継承する（[] は道具なし）。
    本文が要るのは、道具ゼロの役を別プロセスの CLI で起こすときに system prompt として渡すため（launch_cli）。
    """
    plugin, _, role = agent_type.rpartition(":")
    if not plugin:
        return None
    f = find_plugin_path(f"agents/{role}.md", plugin)
    if not f:
        return None
    parts = pathlib.Path(f).read_text(encoding="utf-8").split("---")
    fm = parts[1] if len(parts) > 2 else ""
    body = "---".join(parts[2:]).strip() if len(parts) > 2 else ""

    def field(name):
        m = re.search(rf"^{name}:\s*(.*)$", fm, re.M)
        return m.group(1).strip() if m else None

    tools = field("tools")
    return {
        "file": str(f),
        "tools": ["*"] if tools is None else [t.strip() for t in tools.strip("[] ").split(",") if t.strip()],
        "model": field("model"),
        "effort": field("effort"),
        "body": body,
    }


def agent_tools(agent_type):
    d = agent_def(agent_type)
    return None if d is None else d["tools"]


def deliver_mode(agent_type, path_tools):
    """プロンプトの渡し方: 役が path_tools（graph の deliver.path_tools——自分でファイルを読める道具）のどれかを持てば path、
    持たなければ paste。定義が見つからなければ paste（安全側——貼れば必ず届く）。"""
    tools = agent_tools(agent_type)
    if tools is None or not path_tools:
        return "paste"
    return "path" if ("*" in tools or any(t in tools for t in path_tools)) else "paste"


def run_validator(b, target=None):
    """検証器を回す。target を省くと graph の record.validator_arg（file か dir）に従う。"""
    v = b.state.get("validator")
    if not v:
        return {"exit": None, "out": "検証器が見つからない（init --validator で渡すか、graph の plugin の置き場を " + (env_root(b.plugin) if b.plugin else "<PLUGIN>_ROOT") + " で指す）"}
    if target is None:
        arg = b.graph.get("record", {}).get("validator_arg", "file")
        target = b.dir / ("rounds" if arg == "dir" else "record.json")
    try:
        r = subprocess.run([sys.executable, v, str(target)], capture_output=True, text=True, encoding="utf-8", timeout=VALIDATOR_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"exit": None, "out": f"検証器が {VALIDATOR_TIMEOUT} 秒で終わらない（{v}）", "validator": v}
    return {"exit": r.returncode, "out": (r.stdout + r.stderr).strip(), "validator": v}


def finalize(b):
    """報告の前の仕上げ。ループ固有の仕上げは rules の finalize、engine は痕跡の一覧を process に写す。"""
    fn = hook(b.rules, "finalize")
    if fn:
        fn(b)
    proc = b.record.setdefault("process", {})
    if isinstance(proc, dict):
        proc["skipped"] = [{"node": k, "reason": v} for r in b.state["rounds"] for k, v in r["skipped"].items()]
        proc["truncated_inputs"] = b.state.get("truncated", [])
        proc["git_mismatches"] = b.state.get("git_mismatches", [])
        proc["thickness_changes"] = b.state.get("thickness_changes", [])
        proc["patches"] = b.state.get("patches", [])
        proc["graph_changes"] = b.state.get("graph_changes", [])
