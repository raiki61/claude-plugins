"""coldwrite の宣言設定を機械で突合する。

守るのは 2 つ。①6 ハンドラの複製が 1 本だけ直し漏れる事故(`if` 以外は完全同一であること)。
②拡張子一覧が 4 箇所(hooks.json・plugin.json・coldwrite/README.md・トップ README)で
食い違う事故。正本は hooks.json の `if` 列で、他の 3 箇所を追従側として検査する。
"""
import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent


def fail(msg):
    print("COLDWRITE_CFG_NG:", msg)
    sys.exit(1)


hooks = json.loads((ROOT / "coldwrite/hooks/hooks.json").read_text(encoding="utf-8"))
groups = hooks["hooks"]["PreToolUse"]
if len(groups) != 1 or groups[0]["matcher"] != "Write":
    fail("PreToolUse は matcher Write の 1 グループのみのはず")
handlers = groups[0]["hooks"]

exts = []
base = None
for h in handlers:
    m = re.fullmatch(r"Write\(\*\*/\*\.([a-z0-9]+)\)", h.get("if", ""))
    if not m:
        fail("if が Write(**/*.拡張子) の形でない: %r" % h.get("if"))
    exts.append(m.group(1))
    rest = {k: v for k, v in h.items() if k != "if"}
    if base is None:
        base = rest
    elif rest != base:
        fail("ハンドラが if 以外で食い違う(直し漏れ): %s" % m.group(1))
if len(exts) != len(set(exts)):
    fail("拡張子が重複している")
if base.get("type") != "prompt":
    fail("type が prompt でない")
if "model" in base:
    # 設計条件: model は書かない(coldwrite/README.md「設計条件」。エイリアス・無効 ID は
    # 警告のみでフックごとスキップ=素通しになる fail-open を実測済み)
    fail("model が指定されている(設計条件違反)")
if "coldwrite:skip" not in base.get("prompt", ""):
    fail("判定プロンプトに逃げ道(coldwrite:skip)が無い")

joined = "/".join(exts)
followers = {
    "coldwrite/.claude-plugin/plugin.json": [joined],
    ".claude-plugin/marketplace.json": [joined],
    "README.md": [joined],
    "coldwrite/README.md": ["`**/*.%s`" % e for e in exts] + ["coldwrite:skip"],
}
for rel, needles in followers.items():
    text = (ROOT / rel).read_text(encoding="utf-8")
    for needle in needles:
        if needle not in text:
            fail("%s に %r が無い(hooks.json と不整合)" % (rel, needle))

print("COLDWRITE_CFG_OK")
