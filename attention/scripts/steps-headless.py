#!/usr/bin/env python3
"""世界の解の DW（attention/workflows/dig-world.js）のヘッドレスの形: `claude -p` の別の会話に Workflow を 1 回回させる。

使い方（PR の作業場〔cwd〕で打つ）:
  steps-headless.py world <PR 番号> [--budget-usd 40] [--config-dir <設定のフォルダ>] [--dry-run]

steps-prep.py --next world が書いた <PR>-steps/world-args.json に、段ごとの役（roles）を足して
<PR>-steps/world-args-headless.json に書き、裏の会話に Workflow を回させる。返りは steps-prep.py の --save と
同じ照合をしてから <PR>-steps/world.json に書く。裏の会話には設定・フック・CLAUDE.md を渡さない
（重い版の my-turn-headless.py と同じ絞り。部品はそこから読み込む。my-turn-headless.py は変えない）。
--config-dir は走らせるアカウントの設定のフォルダ（無ければ親の CLAUDE_CONFIG_DIR）。

設計の 4 はヘッドレスの形を最初は使わないとしたが、この会話には Workflow のツールが無いので、測りの 1 回をこの形で回す
（裏のエージェントに CLAUDE.md が足されないので、探す役が対象の名前を知る道も無くなる）。
走らせる会話は Bash の run_in_background で打つ。
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
import claude_auth  # noqa: E402 — 子の claude に認証を足す（リポジトリの scripts/ の写し）

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


heavy = load("my_turn_headless", "my-turn-headless.py")   # child_env・parse_result・BLIND_JUDGE_PROMPT・RULE_UNSAFE
prep = load("steps_prep", "steps-prep.py")                # steps_dir・shape_problems・unwrap・write_json

SCRIPT = os.path.join(ROOT, "workflows", "dig-world.js")
STAGES = ["Restate", "Leak", "Search", "Recheck", "General", "Compare"]
DEFAULT_BUDGET_USD = "40"
NO_TOOLS = ["Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Workflow", "Agent"]

# terms: english-begin
SYSTEM = ("You run one task and nothing else. Read the JSON file at {args}. Call the Workflow tool exactly once "
          "with scriptPath = {script} and args = that JSON value unchanged. "
          "If the Workflow tool call returns an error, output only {{\"workflowError\": <the error text>}} in that "
          "same turn and stop. If the call succeeds, the run goes on in the background: do not try to wait for it "
          "or poll it, and end your turn with no output. When the run ends, its finish notice starts a new turn. "
          "In that turn, if the notice says the run failed, output only {{\"workflowError\": <the notice's error "
          "text>}}; else if the notice names an output file, output only "
          "{{\"outputFile\": <that path, exactly as given>}} as JSON; otherwise output the whole return value as "
          "JSON. Output nothing else. Never edit files.")
PROMPT = "Read {args}, run the world dig workflow once on it with the Workflow tool, and print the JSON the system prompt asks for."
STAGE_PROMPT = ("You are one stage of the world dig workflow. Follow the stage text you are given. You have no file "
                "access. Never write to GitHub.")
SEARCH_PROMPT = ("You are the search stage of the world dig workflow. Follow the stage text you are given. Your only "
                 "tools are web search and web fetch. Never write to GitHub.")
RECHECK_PROMPT = ("You are the excerpt re-fetch stage of the world dig workflow. Follow the stage text you are given: "
                  "run the one command it gives and report its output. Never modify files.")
# terms: english-end


def agents():
    defs = {}
    for k in STAGES:
        d = {"description": "Stage %s of the world dig workflow." % k, "prompt": STAGE_PROMPT,
             "tools": [], "disallowedTools": NO_TOOLS, "omitClaudeMd": True}
        if k == "Search":
            d.update(prompt=SEARCH_PROMPT, tools=["WebSearch", "WebFetch"],
                     disallowedTools=[t for t in NO_TOOLS if t not in ("WebSearch", "WebFetch")])
        elif k == "Recheck":
            d.update(prompt=RECHECK_PROMPT, tools=["Bash"], disallowedTools=[t for t in NO_TOOLS if t != "Bash"])
        elif k == "General":
            d.update(description="Blind eye of the world dig workflow: thinks only from what is given.",
                     prompt=heavy.BLIND_JUDGE_PROMPT)
        defs["world-" + k] = d
    return defs


SHQ_PLAIN = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")   # dig-world.js の shq が囲まずに残す字だけの path


def excerpt_check():
    """取り直しの台本は、Workflow（SCRIPT）と同じ checkout の物を渡す。world-args.json の excerptCheck は、書いた
    steps-prep.py の checkout の path を持ち、その作業場が消えると取り直しが全部「照合できなかった」になる
    （#2555 の 4 回目。excerptCheck は sum に入らない）"""
    xc = {"runPython": os.path.join(HERE, "run-python.sh"),
          "script": os.path.join(ROOT, "steps", "world", "world-excerpts.py")}
    missing = [v for v in xc.values() if not os.path.isfile(v)]
    return xc, missing


def recheck_rule(xc):
    """取り直しの段が打つコマンドの許し（dig-world.js の EXCERPT_COMMAND と同じ頭）。path に規則の中で意味を持つ字が
    在れば組めないので None（取り直しは拒まれ、DW は抜き書きを照合できなかった物として数える）"""
    rp, sc = (xc or {}).get("runPython"), (xc or {}).get("script")
    if not (isinstance(rp, str) and isinstance(sc, str) and rp and sc) or heavy.RULE_UNSAFE & set(rp + sc):
        return None
    # dig-world.js の shq が引用符で囲む path（日本語の字・$ など）は、コマンドの字と規則の字が揃わず当たらない
    if not all(SHQ_PLAIN.match(x) for x in (rp, sc)):
        return None
    return "Bash(bash %s %s --b64 *)" % (rp, sc)


def main(argv):
    ap = argparse.ArgumentParser(prog="steps-headless.py")
    ap.add_argument("dw", choices=["world"])
    ap.add_argument("pr")
    ap.add_argument("--budget-usd", default=DEFAULT_BUDGET_USD)
    ap.add_argument("--config-dir")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        sdir = prep.steps_dir(a.pr)
    except prep.Stop as e:
        print(json.dumps({"ok": False, "message": e.message}, ensure_ascii=False))
        return 1
    src = os.path.join(sdir, "world-args.json")
    try:
        with open(src, encoding="utf-8") as f:
            args = json.load(f)
    except (OSError, ValueError):
        print(json.dumps({"ok": False, "message": "%s を読めません。先に steps-prep.py --next world を打ってください" % src},
                         ensure_ascii=False))
        return 1
    args["roles"] = {k: "world-" + k for k in STAGES}   # roles は sum に入らない（dig-world.js の SUM_KEYS）
    args["excerptCheck"], missing = excerpt_check()
    if missing:
        print(json.dumps({"ok": False, "message": "取り直しの台本が在りません: %s" % ", ".join(missing)}, ensure_ascii=False))
        return 1
    args_file = os.path.join(sdir, "world-args-headless.json")
    prep.write_json(args_file, args)
    rule = recheck_rule(args.get("excerptCheck"))
    argv_c = ["claude", "-p", PROMPT.format(args=args_file), "--model", "sonnet", "--output-format", "json",
              "--max-budget-usd", str(a.budget_usd),
              "--tools", "Read,Bash,Workflow,WebFetch,WebSearch", "--setting-sources", "",
              "--disable-slash-commands", "--strict-mcp-config",
              "--settings", '{"disableAllHooks":true}',
              "--system-prompt", SYSTEM.format(args=args_file, script=SCRIPT),
              "--agents", json.dumps(agents(), ensure_ascii=False),
              "--add-dir", os.path.dirname(SCRIPT), "--add-dir", sdir,
              "--permission-mode", "dontAsk",
              "--allowedTools", "Workflow", "Read", "WebFetch", "WebSearch", *([rule] if rule else [])]
    env0 = dict(os.environ)
    if a.config_dir:
        env0["CLAUDE_CONFIG_DIR"] = os.path.abspath(os.path.expanduser(a.config_dir))
    _, dropped = heavy.child_env(env0)
    if a.dry_run:
        print(json.dumps({"argv": argv_c, "envDropped": dropped, "argsFile": args_file, "recheckRule": rule},
                         ensure_ascii=False))
        return 0
    env, auth = claude_auth.auth_env(env0)
    env, _ = heavy.child_env(env)
    sys.stderr.write("steps-headless: 認証の段 %s・設定のフォルダ %s\n" % (auth, env.get("CLAUDE_CONFIG_DIR")))
    out_path = os.path.join(sdir, "world-headless.json")
    t0 = time.time()
    try:
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            rc = subprocess.run(argv_c, cwd=os.getcwd(), env=env, stdin=subprocess.DEVNULL, stdout=fh).returncode
    except OSError as e:
        print(json.dumps({"ok": False, "message": "claude を起動できません: %s" % e.strerror}, ensure_ascii=False))
        return 1
    wall = round(time.time() - t0)
    try:
        with open(out_path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
        out = json.loads(raw)
    except (OSError, ValueError):
        out = None
    if not isinstance(out, dict) or claude_auth.auth_failed(raw):
        print(json.dumps({"ok": False, "exit": rc, "output": out_path, "auth": auth,
                          "message": "claude の出力が JSON でないか、認証で止まりました。%s を見てください" % out_path},
                         ensure_ascii=False))
        return 1
    note, saved, val = None, None, heavy.parse_result(out.get("result") or "")
    if isinstance(val, dict) and isinstance(val.get("outputFile"), str) and len(val) == 1:
        try:
            with open(val["outputFile"], encoding="utf-8") as f:
                val = prep.unwrap(json.load(f))
        except (OSError, ValueError):
            note, val = "Workflow の出力のファイル（%s）を読めません" % val["outputFile"], None
    if isinstance(val, dict) and isinstance(val.get("workflowError"), str):
        note, val = "Workflow の呼び出しが失敗しました: %s" % val["workflowError"], None
    if val is not None and not note:
        bad = prep.shape_problems(val)
        if bad:
            note = "返りの形が違うので world.json に書きません: %s" % " / ".join(bad[:5])
            prep.write_json(os.path.join(sdir, "world-unsaved.json"), val)
        else:
            saved = os.path.join(sdir, "world.json")
            prep.write_json(saved, val)
    if out.get("subtype") == "error_max_budget_usd":
        note = "上限の額（--max-budget-usd %s ドル）で止まり、Workflow も止められました%s" % (a.budget_usd, "（%s）" % note if note else "")
    if saved is None and not note:
        note = "Workflow の返りを result から読めませんでした。%s の result を見てください" % out_path
    ok = rc == 0 and not out.get("is_error") and not note and saved is not None
    usage = out.get("modelUsage")
    summary = {"ok": ok, "exit": rc, "output": out_path, "saved": saved, "auth": auth,
               "costUsd": out.get("total_cost_usd"), "durationMs": out.get("duration_ms"), "wallSeconds": wall,
               "sessionId": out.get("session_id"), "models": sorted(usage) if isinstance(usage, dict) else [],
               "status": val.get("status") if isinstance(val, dict) else None}
    if note:
        summary["message"] = note
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
