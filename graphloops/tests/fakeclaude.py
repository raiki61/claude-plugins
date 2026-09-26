"""代役の claude（既定は `claude -p --output-format json` の包みを返す）。台本が役を起こす経路を端から端まで通すための物。

振る舞いは環境変数で選ぶ（起こされた子は起こした側の環境を継ぐ——前置の層 with-auth.py も継がせる）:
  FAKE_MODE   answer（既定。FAKE_OUT の中身を返す）／bad_then_answer（--resume の無い初回は散文、--resume なら FAKE_OUT）／
              error（is_error の包み）／error_noresult（result の無い誤りの包み。subtype は error_max_turns で errors を持つ）／
              text（包まずに FAKE_OUT の中身だけを書く——--output-format text の形）／sleep（SIGTERM を 1 秒遅れて処理する孫を立てて眠る。孫の pid を FAKE_PID に書く）／
              seen（届いた材料のバイト数と argv）
  FAKE_OUT    返答の本文のファイル
  FAKE_EXIT   書き終えた後の終了コード（既定 0）
  FAKE_KEEP   在れば、engine が渡す GRAPHLOOPS_KEEP の置き場にこの名前のファイルを書く（任せ先が残す物）
  FAKE_LOG    起こされるたびに argv・標準入力の頭・作業ディレクトリとその中身・TMPDIR を 1 行ずつ足すファイル
会話の番号は --resume に渡された値、無ければ FAKE_SESSION（既定 sess-1）。
"""
import os
import sys

BODY = r'''
import json, os, subprocess, sys, time
# 実物の claude -p と同じく UTF-8 で書く（Windows のパイプの既定は ANSI コードページで、日本語の答えが書けずに空の標準出力になった）
sys.stdout.reconfigure(encoding="utf-8")
raw = sys.stdin.buffer.read()
argv = sys.argv[1:]
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv, "stdin": raw.decode("utf-8", "replace")[:4000], "cwd": os.getcwd(),
                            "tmpdir": os.environ.get("TMPDIR"), "cwd_files": sorted(os.listdir("."))}, ensure_ascii=False) + "\n")
resumed = "--resume" in argv
sid = argv[argv.index("--resume") + 1] if resumed else os.environ.get("FAKE_SESSION", "sess-1")
mode = os.environ.get("FAKE_MODE", "answer")
if os.environ.get("FAKE_KEEP") and os.environ.get("GRAPHLOOPS_KEEP"):   # 任せ先が残す物を置く（engine が残す置き場）
    with open(os.path.join(os.environ["GRAPHLOOPS_KEEP"], os.environ["FAKE_KEEP"]), "w", encoding="utf-8") as f:
        f.write("kept\n")

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
    # 孫は出力の管を継がず、SIGTERM を受けてから 1 秒後に終わる（前置の層の先の claude が自分の子を片付けてから終わる形）。
    # 管を継がないので engine の読み終わりは孫を待たない——直下の子の終了だけで『止めた』と数える engine を、負荷に依らず赤にする
    grand = ("import signal, sys, time\n"
             "signal.signal(signal.SIGTERM, lambda *a: (time.sleep(1), sys.exit(0)))\n"
             "time.sleep(120)\n")
    child = subprocess.Popen([sys.executable, "-c", grand], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
