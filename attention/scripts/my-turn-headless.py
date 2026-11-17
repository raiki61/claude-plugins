#!/usr/bin/env python3
"""/my-turn のヘッドレスの形: `claude -p` の別の会話に Workflow（my-turn-dig.js）を回させる。

使い方: my-turn-headless.py <args.json> [--budget-usd 30] [--dry-run]

<args.json> は会話が書いた Workflow の args（pr・workdir・prep・files.record を持つ）。ここで
`roles`（段ごとの役の名前）を足して <recordDir>/<pr>-args-headless.json に書き、
裏の会話には設定・フック・CLAUDE.md・環境変数のうち CLAUDE/ANTHROPIC で始まる物（設定のフォルダと認証は除く）を渡さない。
走らせる会話は Bash の run_in_background で打つ。設計は attention/docs/my-turn-workflow-design.md の 2。
"""

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import claude_auth  # noqa: E402 — 子の claude に認証を足す（リポジトリの scripts/ の写し）

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROLE_KEYS = ["W1", "W2", "W3", "W4", "W6", "W7", "W8", "W9", "W10answers", "W10fixes", "W11"]
# アカウントを決める設定のフォルダと、認証の経路（claude_auth が足した物か、親が持っていた物）だけを残す
KEEP_ENV = {"CLAUDE_CONFIG_DIR", "ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS",
            # mTLS の代理を通る利用者のクライアント証明書（無いと子が接続で落ちる）
            "CLAUDE_CODE_CLIENT_CERT", "CLAUDE_CODE_CLIENT_KEY", "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
            # Windows で Git Bash が既定の所に無いときの在り処（無いと子が Bash のツールを持てない）
            "CLAUDE_CODE_GIT_BASH_PATH",
            *claude_auth.INHERITED}
# Bedrock・Vertex・Foundry の経路の付き物（地域・プロジェクト・認証を飛ばす旗）。モデルの読み替えの変数はここに入らない
KEEP_PREFIXES = ("ANTHROPIC_BEDROCK_", "ANTHROPIC_VERTEX_", "ANTHROPIC_FOUNDRY_", "CLAUDE_CODE_SKIP_")
ADD_ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK": "1"}
ALIAS = {"fable": "claude-fable", "opus": "claude-opus", "sonnet": "claude-sonnet", "haiku": "claude-haiku"}
BASE_ALIASES = ["opus", "sonnet", "haiku"]

BASH_RULES = ["git show *", "git blame *", "git log *", "git diff *", "git cat-file *", "git ls-files *",
              "git rev-parse *", "gh pr view *", "gh pr diff *", "gh pr list *",
              "gh issue view *", "gh issue list *", "gh search *"]  # gh api は渡さない
# 許可より強い禁止。git の --output はファイルを書き、git grep の -O（--open-files-in-pager）は名指しのコマンドを
# 動かすので、PR の文に仕込まれた指示に従っても通らないようにする（git grep は Grep のツールで足りる）
DENY_BASH = ["git *--output*", "git grep *"]

SYSTEM = ("You run one task and nothing else. Read the JSON file at {args}. Call the Workflow tool exactly once "
          "with scriptPath = {script} and args = that JSON value unchanged. Wait until the workflow run "
          "finishes; do not end your turn while it is running. Then, if the return value has recordWritten = true, "
          "output only {{\"recordPath\": <its recordPath>, \"recordWritten\": true}} as JSON; "
          "otherwise output the whole return value as JSON. If the Workflow tool call itself fails, output only "
          "{{\"workflowError\": <the error text>}}. Output nothing else. Never edit files.")
PROMPT = ("Read {args}, run the /my-turn dig workflow once on it with the Workflow tool, and print the JSON "
          "the system prompt asks for.")

STAGE_PROMPT = ("You are one read-only stage of the /my-turn dig workflow. Follow the stage text you are given. "
                "Never modify files. Never write to GitHub.")
W11_PROMPT = ("You are the record-writing stage of the /my-turn dig workflow. Follow the stage text you are given. "
              "You may write only the record file under {record_dir}. Never modify any other file. "
              "Never write to GitHub.")
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


def agents(record_dir):
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
        elif k == "W11":
            d.update(description="Record-writing stage of the /my-turn dig workflow.",
                     prompt=W11_PROMPT.format(record_dir=record_dir),
                     tools=["Read", "Write"], disallowedTools=["Edit", "Bash", "NotebookEdit"])
        defs["my-turn-" + k] = d
    return defs


def rpath(p):
    """権限ルールの絶対パス: リンクを解いた実パスの先頭に / を 1 つ足す（/home/... は //home/...）。

    allow の規則はリンクの綴りと解いた先の両方に当たるときだけ効き、dontAsk では当たらない書き込みが黙って拒まれる
    （macOS の /tmp → /private/tmp）。Windows の綴りは POSIX の形（C:\\Users → /c/Users）に直す
    （https://code.claude.com/docs/en/permissions 。graphloops/engine/role_run.py の read_rule と同じ）。"""
    real = os.path.realpath(p)
    if os.name == "nt":
        w = pathlib.PureWindowsPath(real)
        real = "/" + w.drive.rstrip(":").lower() + "/" + "/".join(w.parts[1:])
    return "/" + real.replace("\\", "/")


# 権限の規則の中で意味を持つ字（graphloops/engine/role_run.py の RULE_UNSAFE と同じ）
RULE_UNSAFE = frozenset("*?[]{}(),\\ \t\n\r")


def allowed_tools(record_dir):
    # Read は全部のファイルに通す（読むだけの段が作業場・記録のフォルダ・args のファイルを読む）。書けるのは記録のフォルダだけ
    return (["Workflow", "Read", "Grep", "Glob", "WebFetch", "WebSearch",
             "Edit(%s/**)" % rpath(record_dir).rstrip("/")] + ["Bash(%s)" % r for r in BASH_RULES])


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
    """(材料, 止める訳)。記録が書けた回は、返り値の全体を出力に写させず（大きい PR で出力の上限に当たる）、
    記録のファイルから組む。書けなかった回は、出力が返り値の全体。"""
    val = parse_result(result) if isinstance(result, str) else None
    if isinstance(val, dict) and isinstance(val.get("workflowError"), str):
        return None, "Workflow の呼び出しが失敗しました: %s" % val["workflowError"]
    if not isinstance(val, dict) or not ("stopped" in val or "version" in val or val.get("recordWritten") is True):
        return None, "Workflow の返り値を読めません（Workflow が動かなかった可能性）。出力の result を見てください"
    if val.get("recordWritten") is not True:
        return val, None
    try:
        if val.get("recordPath") != rec_path:
            raise ValueError
        with open(rec_path, encoding="utf-8") as f:
            rec = json.load(f)
        if not isinstance(rec, dict):
            raise ValueError
    except (OSError, ValueError, TypeError):
        return None, "記録が書けたと返ったが、記録のファイル（%s）を読めません" % rec_path
    # 記録の counts は W11 の前に数えた物。W11 の分は、記録が書けた（W11 が返った）ことから機械で足す。
    # 子の会話に counts を写させると、入れ子の大きい物の写し違いが手順 15 の照合に入る
    counts = rec.get("counts")
    if isinstance(counts, dict) and isinstance(counts.get("stages"), dict):
        w11 = {"started": 1, "returned": 1, "null": [], "empty": [], "reused": [], "skipped": []}
        if isinstance(rec.get("recordModel"), str):
            w11["models"] = [rec["recordModel"]]
        counts = {**counts, "stages": {**counts["stages"], "W11": w11}}
    return {**rec, "counts": counts, "recordPath": rec_path, "recordWritten": True, "recordError": None}, None


def main(argv):
    ap = argparse.ArgumentParser(prog="my-turn-headless.py")
    ap.add_argument("args_json")
    ap.add_argument("--budget-usd", default="30")
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
    if RULE_UNSAFE & set(rpath(record_dir)):
        # 書き込みの許可 Edit(//<記録のフォルダ>/**) が組めない（かっこ・空白・カンマで規則が切れ、W11 が黙って拒まれる）
        print(json.dumps({"ok": False, "message": "記録のフォルダの path（%s）に、権限の規則で意味を持つ字（%s）が在るので、"
                          "ヘッドレスの形では記録を書けません。既定の形（会話が Workflow を呼ぶ）で回してください"
                          % (record_dir, "".join(sorted(RULE_UNSAFE & set(rpath(record_dir)))).strip() or "空白")},
                         ensure_ascii=False))
        return 1
    args["roles"] = {k: "my-turn-" + k for k in ROLE_KEYS}
    os.makedirs(record_dir, exist_ok=True)
    args_file = os.path.abspath(os.path.join(record_dir, "%s-args-headless.json" % pr))
    with open(args_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(args, f, ensure_ascii=False, indent=2)
    _, dropped = child_env(os.environ)  # dry-run で見せる分。認証は起動の直前に足す
    argv_c = ["claude", "-p", PROMPT.format(args=args_file), "--model", "sonnet", "--output-format", "json",
              "--max-budget-usd", str(a.budget_usd),
              "--tools", "Read,Grep,Glob,Bash,Write,Workflow,WebFetch,WebSearch", "--setting-sources", "",
              "--disable-slash-commands", "--strict-mcp-config",
              "--settings", '{"disableAllHooks":true}',
              "--system-prompt", SYSTEM.format(args=args_file, script=script),
              "--agents", json.dumps(agents(record_dir), ensure_ascii=False),
              # Workflow の scriptPath は作業場か足したフォルダの下のファイルしか受けない。記録のフォルダも、
              # worktree では作業場の外（clone の .git の下）に在るので足す（W11 が書き、段が差分を読む）
              "--add-dir", os.path.dirname(os.path.abspath(script)), "--add-dir", record_dir,
              "--disallowedTools", *["Bash(%s)" % r for r in DENY_BASH],
              "--permission-mode", "dontAsk", "--allowedTools", *allowed_tools(record_dir)]
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
    val, note = build_materials(out.get("result"), (args.get("files") or {}).get("record"))
    materials = None
    if val is not None:
        materials = os.path.join(record_dir, "%s-materials.json" % pr)
        with open(materials, "w", encoding="utf-8", newline="\n") as f:
            json.dump(val, f, ensure_ascii=False, indent=2)
    usage = out.get("modelUsage")
    used = list(usage.keys()) if isinstance(usage, dict) else []
    ok = rc == 0 and not out.get("is_error") and not note
    summary = {"ok": ok, "exit": rc, "output": out_path, "materials": materials, "auth": auth,
               "costUsd": out.get("total_cost_usd"), "durationMs": out.get("duration_ms"),
               "models": check_models(used, args.get("models"), val.get("counts") if isinstance(val, dict) else None)}
    if note:
        summary["message"] = note
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
