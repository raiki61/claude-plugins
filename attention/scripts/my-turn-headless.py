#!/usr/bin/env python3
"""/my-turn のヘッドレスの形: `claude -p` の別の会話に Workflow（my-turn-dig.js）を回させる。

使い方: my-turn-headless.py <args.json> [--budget-usd 100] [--dry-run]

<args.json> は会話が書いた Workflow の args（pr・workdir・prep・files.record を持つ）。ここで
`roles`（段ごとの役の名前）と `caller`（/attention:my-turn-deep からの起動の合図）を足して
<recordDir>/<pr>-args-headless.json に書き、
Workflow の戻り値（記録）は、裏の会話でなくこの台本が files.record に書く（設計の 7）。
裏の会話には設定・フック・CLAUDE.md・環境変数のうち CLAUDE/ANTHROPIC で始まる物（設定のフォルダと認証は除く）を渡さない。
走らせる会話は Bash の run_in_background で打つ。設計は attention/docs/my-turn-workflow-design.md の 2。
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import claude_auth  # noqa: E402 — 子の claude に認証を足す（リポジトリの scripts/ の写し）
import my_turn_record  # noqa: E402 — 記録の版と書き方（my-turn-prep.py の --save-record と共用）

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Workflow（my-turn-dig.js）の CALLER と同じ値。args の caller がこれでないと、Workflow はエージェントを立てずに止まる
CALLER = "attention:my-turn-deep"
ROLE_KEYS = ["Purpose", "W1", "W2", "W3", "W4", "W6", "Redig", "W7", "W8", "Lines", "W9", "W10answers", "W10fixes", "Quotes"]
# アカウントを決める設定のフォルダと、認証の経路（claude_auth が足した物か、親が持っていた物）だけを残す
KEEP_ENV = {"CLAUDE_CONFIG_DIR", "ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS",
            # mTLS の代理を通る利用者のクライアント証明書（無いと子が接続で落ちる）
            "CLAUDE_CODE_CLIENT_CERT", "CLAUDE_CODE_CLIENT_KEY", "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
            # Windows で Git Bash が既定の所に無いときの在り処（無いと子が Bash のツールを持てない）
            "CLAUDE_CODE_GIT_BASH_PATH",
            *claude_auth.INHERITED}
# Bedrock・Vertex・Foundry の経路の付き物（地域・プロジェクト・認証を飛ばす旗）。モデルの読み替えの変数はここに入らない
KEEP_PREFIXES = ("ANTHROPIC_BEDROCK_", "ANTHROPIC_VERTEX_", "ANTHROPIC_FOUNDRY_", "CLAUDE_CODE_SKIP_")
# CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0: 子がターンを終えた後も、裏の Workflow が終わるまで待たせる（既定は 10 分で
# 止めて途中の結果を捨てる。2026-11-18 の PR #2574 で材料が返らなかった）。時間の歯止めは無く、額の歯止めは --max-budget-usd
ADD_ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK": "1",
           "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}
# 1 回の掘る段を回し切る額より上に置く。上限に当たると claude -p は裏の Workflow を止め、材料は返らず、使った額は無駄になる
# （PR #2574 の 1 回は 199 エージェントで約 65 ドル。docs/my-turn-workflow-impl-changes.md）
DEFAULT_BUDGET_USD = "100"
ALIAS = {"fable": "claude-fable", "opus": "claude-opus", "sonnet": "claude-sonnet", "haiku": "claude-haiku"}
BASE_ALIASES = ["opus", "sonnet", "haiku"]

BASH_RULES = ["git show *", "git blame *", "git log *", "git diff *", "git cat-file *", "git ls-files *",
              "git rev-parse *", "gh pr view *", "gh pr diff *", "gh pr list *",
              "gh issue view *", "gh issue list *", "gh search *"]  # gh api は渡さない
# 許可より強い禁止。git の --output はファイルを書き、git grep の -O（--open-files-in-pager）は名指しのコマンドを
# 動かすので、PR の文に仕込まれた指示に従っても通らないようにする（git grep は Grep のツールで足りる）
DENY_BASH = ["git *--output*", "git grep *"]

SYSTEM = ("You run one task and nothing else. Read the JSON file at {args}. Call the Workflow tool exactly once "
          "with scriptPath = {script} and args = that JSON value unchanged. "
          "If the Workflow tool call returns an error, output only {{\"workflowError\": <the error text>}} in that "
          "same turn and stop. If the call succeeds, the run goes on in the background: do not try to wait for it "
          "or poll it, and end your turn with no output. When the run ends, its finish notice starts a new turn. "
          "In that turn, if the notice says the run failed, output only {{\"workflowError\": <the notice's error "
          "text>}}; else if the notice names an output file, output only "
          "{{\"outputFile\": <that path, exactly as given>}} as JSON; otherwise output the whole return value as "
          "JSON. Output nothing else. Never edit files.")
PROMPT = ("Read {args}, run the /my-turn dig workflow once on it with the Workflow tool, and print the JSON "
          "the system prompt asks for.")

STAGE_PROMPT = ("You are one read-only stage of the /my-turn dig workflow. Follow the stage text you are given. "
                "Never modify files. Never write to GitHub.")
QUOTES_STAGE_PROMPT = ("You are the quote-check stage of the /my-turn dig workflow. Follow the stage text you are given: "
                       "run the one command it gives and report its output. Never modify files. Never write to GitHub.")
# 正本: convergence-loops/agents/blind-judge.md の本文（英訳した。1 本だけ Read してよい例外は除く）
BLIND_JUDGE_PROMPT = (
    "You derive independently from what you are given, or compare two things you are given. "
    "You have no tools: you cannot open code, documents, history or the web. What you are given is the whole world. "
    "Do not try to call tools. Do not reconstruct by guesswork what was not given; filling in \"it must be like this "
    "now\" turns independent derivation into confirmation. Before deriving, doubt whether the question itself "
    "exists; if it does not stand, say so instead of deriving. When comparing, compare structure; differences in "
    "wording are not differences. Leave no silent omissions in your reply: write verdicts only in the vocabulary "
    "you were told to use, and always give the reason.")


def child_env(env):
    dropped = sorted(k for k in env if k.startswith(("CLAUDE", "ANTHROPIC")) and k not in KEEP_ENV
                     and not k.startswith(KEEP_PREFIXES))
    out = {k: v for k, v in env.items() if k not in dropped}
    out.update(ADD_ENV)
    return out, dropped


def agents():
    # WebFetch・WebSearch は、W6・W9・W10 が公式の一次の文書の URL を根拠にし確かめるため（既定の形の段と同じ）
    ro = {"tools": ["Read", "Grep", "Glob", "Bash", "WebFetch", "WebSearch"],
          "disallowedTools": ["Write", "Edit", "NotebookEdit"]}
    defs = {}
    for k in ROLE_KEYS:
        d = {"description": "Read-only stage %s of the /my-turn dig workflow." % k,
             "prompt": STAGE_PROMPT, **ro, "omitClaudeMd": True}
        if k == "W2":
            d.update(description="Blind judge stage of the /my-turn dig workflow: thinks only from what is given.",
                     prompt=BLIND_JUDGE_PROMPT, tools=[],
                     disallowedTools=["Read", "Grep", "Glob", "Bash", "Write", "Edit", "NotebookEdit",
                                      "WebFetch", "WebSearch", "Workflow", "Agent"])
        elif k == "Quotes":
            # 打つのはコマンド 1 本だけ（許すのは allowed_tools の照合の規則）。読む・web は要らない
            d.update(description="Quote-check stage of the /my-turn dig workflow: runs one command.",
                     prompt=QUOTES_STAGE_PROMPT, tools=["Bash"],
                     disallowedTools=["Read", "Grep", "Glob", "Write", "Edit", "NotebookEdit",
                                      "WebFetch", "WebSearch", "Workflow", "Agent"])
        defs["my-turn-" + k] = d
    return defs


# 権限の規則の中で意味を持つ字（graphloops/engine/role_run.py の RULE_UNSAFE に、引用符の 2 つを足した）
RULE_UNSAFE = frozenset("*?[]{}(),\\ \t\n\r'\"")


def quote_rule(quote_check):
    """写しの照合の段（Quotes）が打つコマンドの許可。my-turn-dig.js の quoteCommand と同じ頭
    （bash <run-python.sh> <my-turn-prep.py> --quotes - と、その後の照合の行）。path に規則の中で意味を持つ字が
    在れば組めないので None（照合の段のコマンドは拒まれ、Workflow は根拠を確かめていない物として数えて残す）。"""
    qc = quote_check if isinstance(quote_check, dict) else {}
    rp, pp = qc.get("runPython"), qc.get("prep")
    if not (isinstance(rp, str) and isinstance(pp, str) and rp and pp) or RULE_UNSAFE & set(rp + pp):
        return None
    return "Bash(bash %s %s --quotes *)" % (rp, pp)


def allowed_tools(quote_check):
    # Read は全部のファイルに通す（読むだけの段が作業場・記録のフォルダ・args のファイルを読む）。書ける所は無い
    rule = quote_rule(quote_check)
    return (["Workflow", "Read", "Grep", "Glob", "WebFetch", "WebSearch"] + ["Bash(%s)" % r for r in BASH_RULES]
            + ([rule] if rule else []))


def override_aliases(models):
    """args の models（{段: {model, effort}}）が指すモデルの名。"""
    return [v["model"] for v in (models or {}).values() if isinstance(v, dict) and isinstance(v.get("model"), str)]


def check_models(used, models, counts):
    """used（子の modelUsage の名）を、段の表と args の models の名と比べる。expectedMissing は、回った段
    （counts.stages の started が 1 以上）に Workflow が渡したモデルのうち、使われなかった物。数えが無ければ None。"""
    prefixes = [ALIAS.get(a, a) for a in BASE_ALIASES + override_aliases(models)]
    # 前方一致でなく含むかで見る（Bedrock・Vertex の名は us.anthropic.claude-opus-… などの形）
    unexpected = [u for u in used if not any(p in u for p in prefixes)]
    stages = counts.get("stages") if isinstance(counts, dict) else None
    missing = None
    if isinstance(stages, dict):
        ran = {m for e in stages.values() if isinstance(e, dict) and (e.get("started") or 0) > 0
               for m in e.get("models") or [] if isinstance(m, str)}
        missing = sorted(a for a in ran if not any(ALIAS.get(a, a) in u for u in used))
    return {"used": used, "unexpected": unexpected, "expectedMissing": missing}


def parse_result(text):
    """出力の文の JSON（```json の囲みは外す）。読めなければ None。"""
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*?)\n?```\s*$", t, re.S)
    try:
        return json.loads(m.group(1) if m else t)
    except ValueError:
        return None


def build_materials(result, rec_path):
    """(材料, 止める訳, 書いた記録の path)。子の会話は、Workflow の出力のファイルの path（outputFile）か戻り値の全体を返す。
    ファイルから読むのは、大きい PR で戻り値の全体を出力に写させると出力の上限に当たり、写し違いも入るため。
    止まらずに終わった回は、戻り値（記録）を rec_path に書く（W11 をやめた。設計の 3）。
    記録を書けなくても、読めた戻り値は材料として返す（材料は捨てない。設計の 3）。"""
    val = parse_result(result) if isinstance(result, str) else None
    if isinstance(val, dict) and isinstance(val.get("workflowError"), str):
        return None, "Workflow の呼び出しが失敗しました: %s" % val["workflowError"], None
    if isinstance(val, dict) and isinstance(val.get("outputFile"), str) and len(val) == 1:
        try:
            with open(val["outputFile"], encoding="utf-8") as f:
                val = my_turn_record.unwrap(json.load(f))
        except (OSError, ValueError, my_turn_record.RecordError):
            return None, "Workflow の出力のファイル（%s）を読めません" % val["outputFile"], None
    if not isinstance(val, dict) or not ("stopped" in val or "version" in val):
        return None, "Workflow の戻り値を読めません（Workflow が動かなかった可能性）。出力の result を見てください", None
    if "stopped" in val:
        return val, None, None
    try:
        rec = my_turn_record.check(val)
    except my_turn_record.RecordError as e:
        return val, str(e), None
    try:
        if not isinstance(rec_path, str) or not rec_path:
            raise my_turn_record.RecordError("args の files.record が無いので、記録を書けません")
        my_turn_record.write(rec_path, rec)
    except my_turn_record.RecordError as e:
        return rec, str(e), None
    return rec, None, rec_path


def main(argv):
    ap = argparse.ArgumentParser(prog="my-turn-headless.py")
    ap.add_argument("args_json")
    ap.add_argument("--budget-usd", default=DEFAULT_BUDGET_USD)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        with open(a.args_json, encoding="utf-8") as f:
            args = json.load(f)
        pr, workdir = args["pr"], args["workdir"]
        prep = args["prep"]
        record_dir, script = prep["recordDir"], prep["scriptPath"]
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"ok": False, "message": "args.json を読めないか、pr・workdir・prep.recordDir・prep.scriptPath が足りません"},
                         ensure_ascii=False))
        return 1
    args["roles"] = {k: "my-turn-" + k for k in ROLE_KEYS}
    # この台本を打つのは /attention:my-turn-deep の手順 9 だけなので、Workflow が受ける合図をここで渡す（頼み 839571）
    args["caller"] = CALLER
    os.makedirs(record_dir, exist_ok=True)
    args_file = os.path.abspath(os.path.join(record_dir, "%s-args-headless.json" % pr))
    with open(args_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(args, f, ensure_ascii=False, indent=2)
    _, dropped = child_env(os.environ)  # dry-run で見せる分。認証は起動の直前に足す
    argv_c = ["claude", "-p", PROMPT.format(args=args_file), "--model", "sonnet", "--output-format", "json",
              "--max-budget-usd", str(a.budget_usd),
              "--tools", "Read,Grep,Glob,Bash,Workflow,WebFetch,WebSearch", "--setting-sources", "",
              "--disable-slash-commands", "--strict-mcp-config",
              "--settings", '{"disableAllHooks":true}',
              "--system-prompt", SYSTEM.format(args=args_file, script=script),
              "--agents", json.dumps(agents(), ensure_ascii=False),
              # Workflow の scriptPath は作業場か足したフォルダの下のファイルしか受けない。記録のフォルダも、
              # worktree では作業場の外（clone の .git の下）に在るので足す（段が差分を読む）
              "--add-dir", os.path.dirname(os.path.abspath(script)), "--add-dir", record_dir,
              "--disallowedTools", *["Bash(%s)" % r for r in DENY_BASH],
              "--permission-mode", "dontAsk", "--allowedTools", *allowed_tools(prep.get("quoteCheck"))]
    if a.dry_run:
        print(json.dumps({"argv": argv_c, "envDropped": dropped, "envAdded": ADD_ENV, "argsFile": args_file},
                         ensure_ascii=False))
        return 0

    # 認証は親の環境（窓口・Keychain を読む口を含む）から足し、足した後で上の絞りをかけ直す
    env, auth = claude_auth.auth_env(os.environ)
    env, _ = child_env(env)
    sys.stderr.write("my-turn-headless: 認証の段 %s\n" % auth)
    if not claude_auth.added(auth):
        sys.stderr.write("my-turn-headless: %s\n" % claude_auth.QUIET_FAILURE_NOTE)
    out_path = os.path.join(record_dir, "%s-headless.json" % pr)
    try:
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            rc = subprocess.run(argv_c, cwd=workdir, env=env, stdin=subprocess.DEVNULL, stdout=fh).returncode
    except OSError as e:
        print(json.dumps({"ok": False, "exit": -1, "output": out_path, "message": "claude を起動できません: %s" % e.strerror},
                         ensure_ascii=False))
        return 1
    try:
        with open(out_path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        raw = ""
    try:
        out = json.loads(raw)
        if not isinstance(out, dict):
            raise ValueError
    except ValueError:
        out = None
    # 認証の失敗は終了の値 0 の 1 行で返る（claude_auth.auth_failed）。上限の額のせいにしない
    auth_out = bool(claude_auth.auth_failed(raw))
    if out is None or auth_out:
        why = ("認証の失敗か使用枠の上限で止まった形です（出力の頭: %s）" % raw.strip()[:120]
               if auth_out else "claude の出力が無いか、JSON ではありません（上限の額で止まった可能性）")
        print(json.dumps({"ok": False, "exit": rc, "output": out_path, "auth": auth, "authFailed": auth_out,
                          "message": "%s。%s を見てください" % (why, out_path)}, ensure_ascii=False))
        return 1
    val, note, record = build_materials(out.get("result"), (args.get("files") or {}).get("record"))
    if out.get("subtype") == "error_max_budget_usd":
        # 上限の額に当たると claude -p は裏の Workflow も止める。「Workflow が動かなかった」と取り違えさせない
        note = ("上限の額（--max-budget-usd %s ドル）で止まり、Workflow も止められました。--budget-usd を上げて回し直してください"
                % a.budget_usd)
    materials = None
    if val is not None:
        materials = os.path.join(record_dir, "%s-materials.json" % pr)
        with open(materials, "w", encoding="utf-8", newline="\n") as f:
            json.dump(val, f, ensure_ascii=False, indent=2)
    usage = out.get("modelUsage")
    used = list(usage.keys()) if isinstance(usage, dict) else []
    ok = rc == 0 and not out.get("is_error") and not note
    summary = {"ok": ok, "exit": rc, "output": out_path, "materials": materials, "record": record, "auth": auth,
               "costUsd": out.get("total_cost_usd"), "durationMs": out.get("duration_ms"),
               "models": check_models(used, args.get("models"), val.get("counts") if isinstance(val, dict) else None)}
    if note:
        summary["message"] = note
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
