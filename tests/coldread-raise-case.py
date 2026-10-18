#!/usr/bin/env python3
"""解析が例外で落ちたときの倒れ先を検査する。run.sh の expect_output から呼ぶ。

解析器を「必ず例外を投げる代役」に差し替えて main() を動かす。実物の入力で
非 ValueError の例外を発生させる手段が実行環境(Python の版)に依存するため、
代役で機構だけを固定する。ここが allow に倒れると、投稿が無検査で通る。

main() は記録(denies.log)を書くので、読み込む前に設定フォルダを一時フォルダへ向ける。向けないと
利用者の本物の記録にセッション ID の空の parse-fail が溜まる(2026-09-12 に 1 時間 196 件の塊を実測。
試験を回す回数だけ増え、本物の取りこぼしの分析を濁した)。
"""
import importlib.util
import io
import json
import os
import sys
import tempfile

_cfg = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["CLAUDE_CONFIG_DIR"] = _cfg.name

gate_path = os.path.join(os.path.dirname(__file__), "..", "gates", "hooks", "coldread-gate.py")
spec = importlib.util.spec_from_file_location("coldread_gate", gate_path)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def always_raises(*_args, **_kw):
    raise RuntimeError("代役: 想定外の例外")


gate.analyze = always_raises
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
    _cfg.cleanup()
print(buf.getvalue().strip() or "ALLOW_EMPTY")
