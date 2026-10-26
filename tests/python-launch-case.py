#!/usr/bin/env python3
"""全部のプラグインのフックとスキル・コマンドの本文が、Python を素の名前で起動していないかを見る（OS をまたいで動かす標準
docs/standards/cross-os.md の決まり 1）。

素の `python3` は、Windows では Microsoft Store へ誘う代わりの物（アプリ実行エイリアスの python3.exe）に当たり、macOS 付属の物は 3.9 で
3.11 以上を要る台本が動かない（https://docs.python.org/3/using/windows.html）。`command -v python3 || command -v python` は「在るか」だけを見て
代わりの物を選ぶ。フックの失敗は Claude Code が止めないので、ゲートが黙って外れる。正しい形は各プラグインの run-python.sh
（python3・python・py -3 を実際に起動して要る版を選ぶ入口）を通す形。

使い方: python3 tests/python-launch-case.py <場合>
- tree: marketplace に載る全部のプラグイン（.claude-plugin/marketplace.json の source）の hooks/hooks.json・skills/**/*.md・commands/**/*.md を見る
- arms: 下の検査が、壊した例で落ち、壊していない例で通ることを見る（チェックが空振りしていないか）

見ること（1 行ずつ）:
- 素の起動: 前に名前の字（英数字・. / \\ -）が続かない `python`・`python3`・`python3.N` の後に、空白と起動の引数（- で始まる旗・
  引用符・$・<・\\・~・@ で始まる物か、.py の台本か、/ を含む路）が続く。JSON の配列の `"python3", "x.py"` の形も。
  `run-python.sh` の中の python・`/usr/bin/python3` のような路の一部・文の中の「python や」は当たらない
- 在るかで選ぶ形: `command -v python`・`which python`・`type -p python`（python3 も。名前を引用符で囲んでも）

agents/ の本文は見ない（今の物が Python を書くのは、リポジトリの中で写しを配るコマンドの注釈だけで、利用者の会話が打つ物でない）。
plugin.json にフックを直に書いた（hooks が object の）プラグインは、plugin.json も見る。

いま当たる行で、プラグインのファイルを起動する行でない物は EXEMPT に、ファイルと行の字の一部・訳を載せて緑で始める。載せた字が
当たらなくなったら赤で知らせるので、EXEMPT から消す（残すと、後で同じ形が戻っても見えない。tests/skill-body-case.py と同じ形）。
"""

import json
import pathlib
import re
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
STANDARD = "docs/standards/cross-os.md の決まり 1"
CUSTOM_PATHS = ("skills", "commands", "hooks")   # hooks は路の文字列のときだけ置き場の変更（object なら直に書いたフック）

BARE = re.compile(r"(?<![\w./\\-])python(?:3(?:\.\d+)?)?(?:[ \t]+(?=[-\"'$<\\~@]|[\w.{}-]*/|[\w./{}-]*\.py\b)|\\?\",[ \t]*\\?\")")
EMPTY_SCAN = "フックか本文が 1 つも見つからない（走査が空回りしている）"
EXISTS = re.compile(r"\b(?:command[ \t]+-v|which|type[ \t]+-p)[ \t]+[\"']?python")

# プラグインのファイルを起動する行でない物（ファイル: {行の字の一部: 訳}）
EXEMPT = {
    "works-dispatch/skills/dispatch/references/call.md": {
        'command = "python3 scripts/spread-plugins.py"':
            "会社の形（company.toml）の書き方の例。会社のリポジトリの台本を、そのリポジトリが選ぶ Python で走らせる値",
    },
    "works-dispatch/skills/dispatch/references/roles.md": {
        'deliver_check = "python3 scripts/check_deliver.py"': "会社の形の書き方の例（同上）",
        'ask_check = "python3 scripts/check_ask.py"': "会社の形の書き方の例（同上）",
    },
    "works/skills/works/references/start.md": {
        "`python3 -m unittest -q`": "直す対象のリポジトリの試験のコマンド（test_cmd）の例",
    },
}


def launches(line):
    return bool(BARE.search(line) or EXISTS.search(line))


def hits(text):
    """(行の番号, 行) の list。番号は 1 から。"""
    return [(i, line) for i, line in enumerate(text.split("\n"), 1) if launches(line)]


def targets(root):
    """見るファイルの list と、走査そのものの食い違いの list を返す。"""
    market = json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    found, bad = [], []
    for plugin in market["plugins"]:
        src = root / plugin["source"]
        manifest = src / ".claude-plugin" / "plugin.json"
        declared = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
        custom = [k for k in CUSTOM_PATHS if k in declared and not (k == "hooks" and isinstance(declared[k], dict))]
        if isinstance(declared.get("hooks"), dict):
            found.append(manifest)
        if custom:
            bad.append(f"{plugin['name']}: plugin.json が置き場（{', '.join(custom)}）を変えている。このチェックの走査も合わせて直す")
        found += sorted({*src.glob("hooks/hooks.json"), *src.glob("skills/**/*.md"), *src.glob("commands/**/*.md")})
    if not any(f.name == "hooks.json" for f in found) or not any(f.suffix == ".md" for f in found):
        bad.append(EMPTY_SCAN)
    return found, bad


def scan(root, exempt):
    found, bad = targets(root)
    used = set()
    for path in found:
        rel = path.relative_to(root).as_posix()
        allowed = exempt.get(rel, {})
        for n, line in hits(path.read_text(encoding="utf-8")):
            # 外す字を抜いた残りにも起動が在れば落とす（長い行の中の、外した例の隣に書いた起動を見落とさない）
            keys = [k for k in allowed if k in line]
            used.update((rel, k) for k in keys)
            rest = line
            for k in keys:
                rest = rest.replace(k, " ")
            if launches(rest):
                bad.append(f"{rel}:{n}: Python を素の名前か「在るか」で起動している。そのプラグインの run-python.sh を通す（{STANDARD}）: {line.strip()[:160]}")
    bad += [f"{rel}: EXEMPT の「{k}」がもう当たらない（tests/python-launch-case.py の EXEMPT から消す）"
            for rel, keys in sorted(exempt.items()) for k in keys if (rel, k) not in used]
    return found, bad


def tree():
    found, bad = scan(ROOT, EXEMPT)
    if bad:
        print("\n".join(bad))
        return 1
    print(f"PYTHON_LAUNCH_OK {len(found)} 件（外す一覧に {sum(map(len, EXEMPT.values()))} 行）")
    return 0


def arms():
    with tempfile.TemporaryDirectory() as tmp:
        return _arms(pathlib.Path(tmp))


def _arms(d):
    bare = [
        'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/x.py"',
        '"command": "python3 \\"${CLAUDE_PLUGIN_ROOT}/hooks/x.py\\""',
        "`python3 -I x.py`",
        "python x.py --out",
        "python3.12 -c 'print(1)'",
        "a && python3 scripts/x.py",
        'PY=$(command -v python3 || command -v python)',
        "command -v python3 >/dev/null",
        'which python3',
        'type -p "python3"',
        '"args": ["python3", "x.py"]',
        "python3 ~/x.py",
        "python3 @args",
        "python3 scripts/tool",
    ]
    fine = [
        'bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/x.py"',
        '"command": "bash \\"${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh\\" --once \\"${CLAUDE_PLUGIN_ROOT}/hooks/x.py\\""',
        "`python3` に替えて打たない",
        "python や MCP のツールで書いても",
        "言語名の枠（```python 等）",
        "/usr/bin/python3 -c 1",
        "my_python3 x.py",
        "Python 3.12 以上",
        "`python3` か `python` を打つ",
        '"python3" という名前',
    ]
    for s in bare:
        assert hits(s), f"素の起動を落とさない: {s}"
    for s in fine:
        assert not hits(s), f"起動でない行を落とす: {s}"

    # 走査と外す一覧: hooks.json・skills の下の深い .md・commands の下の .md を見て、外した行は通し、当たらなくなった字は消させる
    r = d / "repo"
    files = {
        "a/hooks/hooks.json": '{"command": "python3 \\"${CLAUDE_PLUGIN_ROOT}/hooks/x.py\\""}\n',
        "a/skills/s/SKILL.md": "本文\n",
        "a/skills/s/references/deep/r.md": "`python3 x.py`\n",
        "a/commands/sub/c.md": "`python3 -m y`\n例 `python3 -m y` と `python3 z.py`\n",
        "a/scripts/x.md": "python3 x.py\n",
        "moved/skills/t/SKILL.md": "本文\n",
        "inline/skills/u/SKILL.md": "本文\n",
    }
    for rel, body in files.items():
        (r / rel).parent.mkdir(parents=True, exist_ok=True)
        (r / rel).write_text(body, encoding="utf-8")
    extra = {"moved": {"hooks": "./other.json"}, "inline": {"hooks": {"Stop": [{"hooks": [{"command": "python3 x.py"}]}]}}}
    for p in ("a", "moved", "inline"):
        (r / p / ".claude-plugin").mkdir(parents=True)
        (r / p / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": p, **extra.get(p, {})}, indent=1), encoding="utf-8")
    (r / ".claude-plugin").mkdir()
    (r / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"plugins": [{"name": p, "source": f"./{p}"} for p in ("a", "moved", "inline")]}), encoding="utf-8")
    found, bad = scan(r, {"a/commands/sub/c.md": {"python3 -m y": "訳"}, "a/skills/s/SKILL.md": {"python3 z": "訳"}})
    assert sorted(f.relative_to(r).as_posix() for f in found) == \
        ["a/commands/sub/c.md", "a/hooks/hooks.json", "a/skills/s/SKILL.md", "a/skills/s/references/deep/r.md",
         "inline/.claude-plugin/plugin.json", "inline/skills/u/SKILL.md", "moved/skills/t/SKILL.md"], f"走査の拾い方が違う: {found}"
    want = ["moved: plugin.json が置き場（hooks）", "a/commands/sub/c.md:2: ", "a/hooks/hooks.json:1: ",
            "a/skills/s/references/deep/r.md:1: ", "inline/.claude-plugin/plugin.json:", "a/skills/s/SKILL.md: EXEMPT の「python3 z」がもう当たらない"]
    assert len(bad) == len(want) and all(b.startswith(w) for b, w in zip(bad, want)), f"走査の食い違いの拾い方が違う: {bad}"
    _, bad = scan(r, {})
    assert any(b.startswith("a/commands/sub/c.md:1: ") for b in bad), "外していない行を落とさない"
    empty = d / "empty"
    (empty / ".claude-plugin").mkdir(parents=True)
    (empty / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": []}), encoding="utf-8")
    assert scan(empty, {})[1] == [EMPTY_SCAN], "空回りを落とさない"
    print("PYTHON_LAUNCH_ARMS_OK")
    return 0


if __name__ == "__main__":
    sys.exit({"tree": tree, "arms": arms}[sys.argv[1]]())
