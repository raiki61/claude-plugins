#!/usr/bin/env python3
"""解析が例外で落ちたときの倒れ先を検査する。run.sh の expect_output から呼ぶ。

解析器を「必ず例外を投げる代役」に差し替えて main() を動かす。実物の入力で
非 ValueError の例外を起こす手段が実行環境(Python の版)に依存するため、
代役で機構だけを固定する。ここが allow に倒れると、投稿が無検査で通る。
"""
import importlib.util
import io
import json
import os
import sys

gate_path = os.path.join(os.path.dirname(__file__), "..", "gates", "hooks", "coldread-gate.py")
spec = importlib.util.spec_from_file_location("coldread_gate", gate_path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def always_raises(command):
    raise RuntimeError("代役: 想定外の例外")


gate.posting_bodies = always_raises
command = "gh issue comment 1 --body '%s'" % ("これは検査対象の本文です。" * 20 + "x" * 420)
sys.stdin = io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}))
buf = io.StringIO()
real_stdout, sys.stdout = sys.stdout, buf
try:
    gate.main()
except SystemExit:
    pass
finally:
    sys.stdout = real_stdout
print(buf.getvalue().strip() or "ALLOW_EMPTY")
