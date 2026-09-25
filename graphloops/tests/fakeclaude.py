"""代役の claude（既定は `claude -p --output-format json` の包みを返す）。台本が役を起こす経路を端から端まで通すための物。

振る舞いは環境変数で選ぶ（起こされた子は起こした側の環境を継ぐ——前置の層 with-auth.py も継がせる）:
  FAKE_MODE   answer（既定。FAKE_OUT の中身を返す）／bad_then_answer（--resume の無い初回は散文、--resume なら FAKE_OUT）／
              error（is_error の包み）／error_noresult（result の無い誤りの包み。subtype は error_max_turns で errors を持つ）／
              text（包まずに FAKE_OUT の中身だけを書く——--output-format text の形）／sleep（孫を立てて眠る。孫の pid を FAKE_PID に書く）／
              seen（届いた材料のバイト数と argv）
  FAKE_OUT    返答の本文のファイル
  FAKE_EXIT   書き終えた後の終了コード（既定 0）
  FAKE_LOG    起こされるたびに argv と標準入力の頭を 1 行ずつ足すファイル
会話の番号は --resume に渡された値、無ければ FAKE_SESSION（既定 sess-1）。
"""
import os
import sys

BODY = r'''
import json, os, subprocess, sys, time
raw = sys.stdin.buffer.read()
argv = sys.argv[1:]
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv, "stdin": raw.decode("utf-8", "replace")[:4000]}, ensure_ascii=False) + "\n")
resumed = "--resume" in argv
sid = argv[argv.index("--resume") + 1] if resumed else os.environ.get("FAKE_SESSION", "sess-1")
mode = os.environ.get("FAKE_MODE", "answer")

def out(result, **kw):
    env = {"type": "result", "subtype": "success", "is_error": False, "result": result, "session_id": sid,
           "num_turns": 2, "duration_ms": 10, "total_cost_usd": 0.001, "usage": {"input_tokens": 1, "output_tokens": 1}}
    env.update(kw)
    sys.stdout.write(json.dumps(env, ensure_ascii=False))

def answer():
    with open(os.environ["FAKE_OUT"], encoding="utf-8") as f:
        return f.read()

if mode == "seen":
    out(json.dumps({"seen_bytes": len(raw), "argv": argv}))
elif mode == "error":
    out("API Error: overloaded", subtype="error_during_execution", is_error=True)
elif mode == "error_noresult":
    sys.stdout.write(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "session_id": sid,
                                 "errors": ["Reached maximum number of turns (9)"], "num_turns": 9, "duration_ms": 10,
                                 "total_cost_usd": 0.002, "usage": {"input_tokens": 1, "output_tokens": 1}}, ensure_ascii=False))
elif mode == "text":
    sys.stdout.write(answer())
elif mode == "sleep":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.environ["FAKE_PID"], "w", encoding="utf-8") as f:
        f.write(str(child.pid))
    time.sleep(120)
elif mode == "bad_then_answer" and not resumed:
    out("判定は次のとおりです（散文）")
else:
    out(answer(), permission_denials=[{"tool_name": "WebFetch", "tool_use_id": "t1", "tool_input": {}}] if resumed else [])
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
'''


def install(bindir):
    """bindir に代役の claude を置き、そのパスを返す。**実物と同じ実行形式で置く**（Windows は .bat——shebang を解さない。
    理由の正本は simulate.py の _fake_claude の注記）。"""
    impl = bindir / "fake_claude_env.py"
    impl.write_text(BODY, encoding="utf-8")
    if os.name == "nt":
        fake = bindir / "claude.bat"
        fake.write_text(f'@echo off\r\n"{sys.executable}" "{impl}" %*\r\n', encoding="utf-8")
        return fake
    fake = bindir / "claude"
    fake.write_text(f"#!{sys.executable}\n" + BODY, encoding="utf-8")
    fake.chmod(0o755)
    return fake
