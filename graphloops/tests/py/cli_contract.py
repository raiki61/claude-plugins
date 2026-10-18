"""graphloops が子の claude を起動するときに頼る外の形（旗・旗の値・設定のキー・包みのフィールド・環境変数）を、実物から採った見本と
突き合わせる口。試験（test_cli_contract.py）は見本（同じ置き場の cli/）だけを読み、claude を起動しない。

使い方（リポジトリのルートから）:
    python3 graphloops/tests/py/cli_contract.py --live     手元の claude で確かめる（下の「起動の確かめ」。費用なし）
    python3 graphloops/tests/py/cli_contract.py --capture  手元の claude で見本（help の全文・ログインしていない回の包み）を採り直す

なぜ要るか: 旗の名前が消えれば claude は『unknown option』で落ちる（落ちるので見える）が、設定のキーの改名は黙って捨てられ
（sandbox が静かに効かなくなる）、包みのフィールドの改名は費用 0・誤りの種類 success に黙って落ちる。fakeclaude.py は手で書いた
想像の形なので、どれも捕まえない（docs/standards/breakage-detection.md の決まり 3）。

起動の確かめ（--live と --capture）は、空の設定のフォルダ（CLAUDE_CONFIG_DIR）で資格情報を外し、API の宛先を開いていない手元の
口（ANTHROPIC_BASE_URL）に向けて、engine と同じ旗の並び（engine/launch_words.py の形ごとの語。--json-schema つき）で claude -p を起動する。claude は旗と値と --settings の型を確かめた後、
ログインしていないので API を呼ばずに包み（is_error が真・result が『Not logged in』）を返す——費用は掛からない。
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PLUGIN = HERE.parents[1]
REPO = PLUGIN.parent
FIX = HERE / "cli"
sys.path.insert(0, str(PLUGIN))

from engine import commands, launch_words, role_run  # noqa: E402
from engine.schema import cli_schema  # noqa: E402

HELP = FIX / "claude-help.txt"                       # claude --help の全文（--capture が採る）
PROBE = FIX / "claude-result-not-logged-in.json"     # 起動の確かめの包み（--capture が採る）
SUCCESS = FIX / "claude-result-success.json"         # 本物の 1 往復の包み（手で採った。採り方は versions.json の success）
SCHEMA = FIX / "settings-schema-keys.json"           # 設定の JSON Schema のキーと型（採り方は中の source）
VERSIONS = FIX / "versions.json"                     # 見本を採った claude の版と採り方

# help の選択肢に載らないが受け付ける値（claude 2.1.303 の --permission-mode の choices は manual を載せ、default を載せない）。
# 試験は、ここに載せた値が起動の確かめの旗の並び（versions.json の probe.argvs）に入り、包みが返ったことを見る
HIDDEN_VALUES = {"--permission-mode": {"default"}}
# 値が , で区切った一覧の旗（help の選択肢と 1 つずつ比べる。空の一覧も値）
LIST_FLAGS = ("--setting-sources",)
# 起動の確かめで穴を埋める値（rules の値でなく、claude が受け付ける形の代表）
FILL = {"model": "haiku", "effort": "high", "tools": "Read", "allowed_tools": "Read", "session_id": None}
# 起動の確かめで --json-schema に渡す schema を持つノード（graph の名前, ノード）。engine と同じく cli_schema で engine だけが読む語
# （note など）を外し、同じ綴り（advance.claude_words）にして渡す——入れ子の object・配列・enum・minLength・minimum を持つ実物の形
PROBE_SCHEMA_NODE = ("review-loop", "p0.purpose_review")
# claude の本体に名前が残っているかを見る環境変数（engine が子に渡す・読む物）
ENV_NAMES = ("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "CLAUDE_CODE_TMPDIR")
# 包みのフィールドのうち、--json-schema を渡した子の包みにだけ在る物（role_run.unwrap が本文として読む）。ログインしていない回の包みには
# 無いので、claude の本体に名前が残っているかを見る
STRUCTURED_READS = ("structured_output",)
OPTION_LINE = re.compile(r"^ {2,6}(-[A-Za-z], )?--[A-Za-z]")
FLAG = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")
BRACKET = re.compile(r"(--[A-Za-z][\w-]*)\[(-[\w-]+)\]")


# ---------------------------------------------------------------- help を読む
def help_blocks(text):
    """help の旗の段 ——{旗: 段の全文}。段は旗の行（字下げ 2〜6 の - で始まる行）から次の旗の行の前まで。別名（-p, --print・
    --allowedTools, --allowed-tools）は同じ段を指す"""
    blocks, cur = {}, None
    for line in text.splitlines():
        if OPTION_LINE.match(line):
            head = re.split(r" {2,}|<|\[", line.strip(), maxsplit=1)[0]
            cur = [line]
            for f in FLAG.findall(head):
                blocks[f] = cur
        elif cur is not None and line.startswith(" "):
            cur.append(line)
        else:
            cur = None
    return {f: "\n".join(b) for f, b in blocks.items()}


def help_flags(text):
    """help が名乗る旗 ——(旗の段を持つ旗の集合, 段を持たず本文の --x[-y] の形でだけ名乗る旗の集合)"""
    defined = set(help_blocks(text))
    mentioned = {base + tail for base, tail in BRACKET.findall(text)} - defined
    return defined, mentioned


def help_choices(text, flag):
    """旗の段が並べる値の一覧（choices: "a", "b" の形か、(a, b, c) の形）。並べていなければ None"""
    block = help_blocks(text).get(flag)
    if block is None:
        return None
    flat = " ".join(block.split())
    m = re.search(r"choices: ((?:\"[^\"]*\"(?:, )?)+)", flat)
    if m:
        return re.findall(r"\"([^\"]*)\"", m.group(1))
    m = re.findall(r"\(((?:[a-z]+, )+[a-z]+)\)", flat)
    return m[-1].split(", ") if m else None


# ---------------------------------------------------------------- graphloops が使う物
def launch_argvs():
    """engine が claude を起動する語（engine/launch_words.py の形ごとの語。穴は埋めない）——[(形・語の種類, 語)]。形は全部
    （launch_words.KINDS）、語の種類は初めの起動（argv）と同じ会話を続ける起動（resume）で、どちらも --json-schema つき
    （schema を持たないノードの子の語は、これから --json-schema を除いた物）"""
    return [(f"{kind}.{name}", launch_words.argv(kind, resume=resume, schema=True))
            for kind in launch_words.KINDS for name, resume in (("argv", False), ("resume", True))]


def used_flags():
    """graphloops が claude に渡す旗の集合（起動する語と、engine がチェックする旗の一覧 commands.TOOLED_FLAGS など）"""
    flags = (set(commands.TOOLED_FLAGS) | set(commands.ISOLATED_FLAGS) | set(commands.ISOLATED_READ_FLAGS) | set(commands.DELEGATE_FLAGS)
             | set(commands.RUNNER_FLAGS) | set(commands.OPTIONAL_FLAGS))
    for _, argv in launch_argvs():
        flags |= {a for a in argv[1:] if a.startswith("-")}
    return flags


def used_values():
    """旗ごとに graphloops が渡す決まった値 ——{旗: 値の集合}。起動する語の穴（{…}）でない値・engine が固定する値（FIXED_VALUES）・
    engine が決める権限の形（role_run の各形）・役の定義と graph の effort"""
    vals = {f: {v} for f, v in commands.FIXED_VALUES.items()}
    for _, argv in launch_argvs():
        for f, v in zip(argv[1:], argv[2:]):
            if f.startswith("--") and not v.startswith("-") and not re.fullmatch(r"\{\w+\}", v):
                vals.setdefault(f, set()).add(v)
    modes = {role_run.tooled_permission(["Read"])["permission_mode"], role_run.delegate_permission()[0],
             role_run.unfenced_delegate_permission()[0]}
    vals.setdefault("--permission-mode", set()).update(modes)
    vals.setdefault("--effort", set()).update(used_efforts())
    return vals


def used_efforts():
    """役の定義（convergence-loops/agents/*.md の頭の effort）と graph の中の effort の値"""
    out = set()
    for md in sorted((REPO / "convergence-loops" / "agents").glob("*.md")):
        m = re.search(r"^effort:\s*(\S+)\s*$", md.read_text(encoding="utf-8").split("\n---", 1)[0], re.M)
        if m:
            out.add(m.group(1))

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "effort" and isinstance(v, str) and not v.startswith("{"):
                    out.add(v)
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for g in sorted((PLUGIN / "graphs").glob("*.json")):
        walk(json.loads(g.read_text(encoding="utf-8")))
    return out


def used_settings():
    """engine が --settings に渡す形の代表（sandbox の形・書き換える回す側の形・任せ先の形。どれも deny つき）——[(名前, 辞書)]"""
    deny = ["Bash(rm:*)"]
    tooled = role_run._with_deny({"sandbox": {**role_run.SANDBOX_BASE, "filesystem": {"denyWrite": ["/x"]}}}, deny)
    return [("tooled_permission の sandbox の形（runner_permission の edit も同じ）", tooled),
            ("delegate_settings", json.loads(role_run.delegate_settings(["/x"], deny))),
            ("unfenced_delegate_permission", json.loads(role_run.unfenced_delegate_permission(deny)[2]))]


def dotted(d, prefix=""):
    """辞書の葉までのキーの綴り（a.b.c）の集合"""
    out = set()
    for k, v in d.items():
        name = prefix + k
        out |= dotted(v, name + ".") if isinstance(v, dict) and v else {name}
    return out


def probe_schema():
    """起動の確かめで --json-schema に渡す値——PROBE_SCHEMA_NODE のノードの schema を engine と同じ形・綴りにした物。engine のチェック
    （commands._json_schema_refusal）が通さない値なら落とす（engine が渡さない値を確かめても意味が無い）"""
    graph, node = PROBE_SCHEMA_NODE
    schema = json.loads((PLUGIN / "graphs" / f"{graph}.json").read_text(encoding="utf-8"))["nodes"][node]["schema"]
    value = json.dumps(cli_schema(schema), ensure_ascii=False, separators=(",", ":"))
    why = commands._json_schema_refusal(value)
    if why:
        raise SystemExit(f"起動の確かめの schema（{graph} の {node}）を engine のチェックが拒む: {why}")
    return value


def probe_argvs(role_file):
    """起動の確かめで打つ語——起動する語（resume でない語）ごとに穴を埋め、権限の形は engine が決める値を全部試す。--settings は
    最初の形（used_settings の頭）で埋め、残りの形は --settings を持つ最初の語で 1 回ずつ試す。--json-schema は probe_schema の値"""
    out, seen = [], set()
    modes = sorted(used_values()["--permission-mode"])
    settings = [json.dumps(s, sort_keys=True) for _, s in used_settings()]
    schema = probe_schema()

    def add(argv, mode, setting):
        fill = {**FILL, "permission_mode": mode, "settings": setting, "role_file": role_file, "json_schema": schema}
        filled = [re.sub(r"\{(\w+)\}", lambda m: str(fill[m.group(1)]), a) for a in argv]
        if tuple(filled) not in seen:
            seen.add(tuple(filled))
            out.append(filled + ["ok"])
    first = [a for _, a in launch_argvs() if "--resume" not in a]
    for argv in first:
        for mode in (modes if "{permission_mode}" in argv else [None]):
            add(argv, mode, settings[0])
    carrier = next(a for a in first if "{settings}" in a)
    for setting in settings[1:]:
        add(carrier, modes[0], setting)
    return out


def unlisted_values(text):
    """graphloops が渡す値のうち、help の選択肢に無い物 ——[(旗, 値, 選択肢)]。選択肢を並べない旗は見ない。HIDDEN_VALUES は除く"""
    out = []
    for f, vals in sorted(used_values().items()):
        choices = help_choices(text, f)
        if choices is None:
            continue
        for v in sorted(vals - HIDDEN_VALUES.get(f, set())):
            parts = [x for x in v.split(",") if x] if f in LIST_FLAGS else [v]
            out += [(f, x, choices) for x in parts if x not in choices]
    return out


# ---------------------------------------------------------------- 手元の claude を起動する
def _claude():
    exe = shutil.which("claude")
    return pathlib.Path(exe).resolve() if exe else None


def _probe_env(cfg):
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                        "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "GRAPHLOOPS_ENGINE_CHILD")}
    # 資格情報の無い空の設定のフォルダ・開いていない手元の口——ログインしていても API へ届かない
    return {**env, "CLAUDE_CONFIG_DIR": str(cfg), "ANTHROPIC_BASE_URL": "http://127.0.0.1:9"}


def run_probes(exe):
    """起動の確かめ ——[(語, 終わりの値, 標準出力, 標準エラー)]。語の中の一時のパスは <一時> に伏せる"""
    with tempfile.TemporaryDirectory(prefix="gl-cli-") as tmp:
        role = pathlib.Path(tmp) / "role.md"
        role.write_text("probe\n", encoding="utf-8")
        out = []
        for argv in probe_argvs(str(role)):
            r = subprocess.run([str(exe)] + argv[1:], cwd=tmp, env=_probe_env(pathlib.Path(tmp) / "cfg"), capture_output=True,
                               text=True, timeout=120, stdin=subprocess.DEVNULL)
            out.append(([a.replace(tmp, "<一時>") for a in argv], r.returncode, r.stdout, r.stderr))
        return out


def check_probe(argv, rc, stdout, stderr):
    """起動の確かめ 1 回の不合格の理由（合格なら None）——旗・値が拒まれない・--settings が読める・包みが返り engine の読む
    フィールドがそろう"""
    if "unknown option" in stderr or "is invalid" in stderr or "Error processing" in stderr:
        return f"claude が旗か値を拒んだ: {stderr.strip()[:300]}"
    if "did not load" in stderr:
        return f"claude が --settings を読まなかった: {stderr.strip()[:300]}"
    try:
        env = json.loads(stdout)
    except ValueError:
        return f"包みが返らない（exit {rc}）: {stdout.strip()[:200]} {stderr.strip()[:200]}"
    if not (isinstance(env, dict) and env.get("type") == "result"):
        return f"type が result の包みでない: {stdout.strip()[:200]}"
    lost = [k for k in role_run.ENVELOPE_READS if k not in env]
    return f"包みに engine が読むフィールドが無い: {lost}" if lost else None


def live(exe):
    """手元の claude と見本の突き合わせ ——不合格の理由の一覧"""
    probs = []
    version = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    text = subprocess.run([str(exe), "--help"], capture_output=True, text=True, timeout=60).stdout
    pinned = json.loads(VERSIONS.read_text(encoding="utf-8"))["help"]["claude"]
    print(f"手元の claude: {version}（{exe}）。見本: {pinned}")
    defined, mentioned = help_flags(text)
    for f in sorted(used_flags() - defined - mentioned):
        probs.append(f"旗 {f} が claude --help に無い")
    probs += [f"{f} の値 {v!r} が claude --help の選択肢 {c} に無い" for f, v, c in unlisted_values(text)]
    for argv, rc, out, err in run_probes(exe):
        why = check_probe(argv, rc, out, err)
        if why:
            probs.append(f"起動の確かめ {' '.join(argv[:12])} …: {why}")
    body = exe.read_bytes() if exe.stat().st_size > 1_000_000 else None
    if body is None:
        probs.append(f"{exe} は claude の本体でない（1 MB 未満——包みの台本の類）ので、設定のキーと環境変数の名前を確かめられない")
    else:
        keys = set().union(*(dotted(s) for _, s in used_settings()))
        for name in sorted({k.rsplit(".", 1)[-1] for k in keys} | set(ENV_NAMES) | set(role_run.ENVELOPE_READS)
                           | set(STRUCTURED_READS)):
            if name.encode() not in body:
                probs.append(f"{name} が claude の本体に無い（設定のキー・環境変数・包みのフィールドの名前が変わった疑い）")
    if version != pinned:
        print(f"注意: 見本は {pinned} で採った。合格なら --capture で採り直して commit する")
    return probs


def capture(exe):
    """help の全文と起動の確かめの包みを見本に書き直す（本物の 1 往復の包み claude-result-success.json は書き換えない）"""
    version = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    HELP.write_text(subprocess.run([str(exe), "--help"], capture_output=True, text=True, timeout=60).stdout, encoding="utf-8")
    probes = run_probes(exe)
    bad = [(a, why) for a, rc, out, err in probes for why in [check_probe(a, rc, out, err)] if why]
    if bad:
        raise SystemExit(f"起動の確かめが通らない回が在る（見本を書き直さない）: {bad[0]}")
    env = json.loads(probes[0][2])
    env.update({k: "00000000-0000-0000-0000-000000000000" for k in ("session_id", "uuid") if k in env})
    PROBE.write_text(json.dumps(env, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    meta = json.loads(VERSIONS.read_text(encoding="utf-8")) if VERSIONS.is_file() else {}
    today = datetime.date.today().isoformat()
    meta["help"] = {"claude": version, "captured": today, "how": "claude --help"}
    meta["probe"] = {"claude": version, "captured": today, "argvs": [a for a, *_ in probes],
                     "how": "cli_contract.py --capture（空の CLAUDE_CONFIG_DIR・資格情報なし・ANTHROPIC_BASE_URL は開いていない手元の口）"}
    VERSIONS.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"見本を書き直した（{version}）: {HELP.name}・{PROBE.name}・{VERSIONS.name}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="graphloops が頼る claude の形を、手元の claude と突き合わせる（費用なし）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--live", action="store_true", help="手元の claude で確かめる")
    g.add_argument("--capture", action="store_true", help="手元の claude で見本を採り直す")
    a = ap.parse_args(argv)
    exe = _claude()
    if exe is None:
        print("claude が PATH に無い——確かめられない", file=sys.stderr)
        return 2
    if a.capture:
        capture(exe)
        return 0
    probs = live(exe)
    for p in probs:
        print(f"NG {p}")
    print("ok 手元の claude は graphloops が頼る形を持つ" if not probs else f"NG {len(probs)} 件")
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main())
