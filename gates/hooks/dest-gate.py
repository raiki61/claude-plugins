#!/usr/bin/env python3
"""destgate — 投稿の宛先を許可一覧で縛る門番(PreToolUse:Bash)。

coldread(通じやすさ)とは別の軸「その宛先へ出してよいか」を検査する。
許可一覧が無ければ眠っている(何も出さず allow)。一覧の管理は人の仕事で、
モデルが自分で追記して通すのは門番の無効化になる——deny 文言でも明示する。

coldread と別フックにしてあるのは、COLDREAD_SKIP=1(通じやすさ検査の逃げ道)で
宛先の検査まで外れる経路を作らないため。宛先の判定は決定的(LLM なし)なので、
この門番自身には逃げ道が無い——通したければ人が一覧へ追記する。それが記録になる。
解析部(トークン化・単純コマンド分割・旗表)は coldread-gate.py から読み込んで共有する。
"""
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys

for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_spec = importlib.util.spec_from_file_location(
    "coldread_gate",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "coldread-gate.py"),
)
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)

CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
STATE_DIR = os.path.join(CONFIG_DIR, "destgate")
ALLOWLIST = os.path.join(STATE_DIR, "allowlist")
DENY_LOG = os.path.join(STATE_DIR, "denies.log")


def patterns():
    """許可一覧(1 行 1 パターン。owner/repo・owner/*・gist。# 始まりと空行は無視)。"""
    try:
        with open(ALLOWLIST, encoding="utf-8") as f:
            return [ln.strip() for ln in f
                    if ln.strip() and not ln.strip().startswith("#")]
    except OSError:
        return []


def owner_repo(value):
    """-R の値や URL から owner/repo を取り出す。取れなければ None。

    gh は OWNER/REPO・HOST/OWNER/REPO・完全 URL(https/ssh)のどれも受けるので、
    末尾 2 セグメントを取り .git を落とす。ssh の別名ホスト(github.com-xxx:o/r)も
    : 以降がパスなので同じ規則で拾える。
    """
    v = value.strip().rstrip("/")
    v = re.sub(r"^[a-z+]+://", "", v)
    v = v.split(":", 1)[-1] if ":" in v and "/" not in v.split(":", 1)[0] else v
    parts = [p for p in v.split("/") if p]
    if len(parts) < 2:
        return None
    o, r = parts[-2], parts[-1]
    r = re.sub(r"\.git$", "", r)
    if not o or not r or o.startswith("-"):
        return None
    return f"{o}/{r}"


def dest_of(args, sub, cwd):
    """gh 引数列から投稿の宛先を決める。分からなければ None。"""
    # -R / --repo が最優先(gh 自身の解決順もこれが勝つ)
    for i, tok in enumerate(args):
        if tok in ("-R", "--repo") and i + 1 < len(args):
            return owner_repo(args[i + 1])
        for f in ("-R", "--repo"):
            if tok.startswith(f + "="):
                return owner_repo(tok[len(f) + 1:])
        if tok.startswith("-R") and tok not in ("-R",) and not tok.startswith("--"):
            return owner_repo(tok[2:])
    if sub and sub[0] == "api":
        if len(sub) < 2:
            return None
        path = re.sub(r"^[a-z+]+://[^/]+", "", sub[1]).lstrip("/")
        seg = [p for p in path.split("/") if p]
        if len(seg) >= 3 and seg[0] == "repos":
            return f"{seg[1]}/{seg[2]}"
        if len(seg) >= 2 and seg[0] == "orgs":
            return f"{seg[1]}/*"
        return None  # graphql・users/... 等は宛先を特定できない
    if sub and sub[0] == "gist":
        return "gist"
    # 明示が無ければ gh はカレントの git remote へ投稿する
    try:
        url = subprocess.run(
            ["git", "-C", cwd or ".", "remote", "get-url", "origin"],
            capture_output=True, encoding="utf-8", timeout=10,
        ).stdout.strip()
        return owner_repo(url) if url else None
    except Exception:
        return None


def main():
    allow_patterns = patterns()
    raw = json.load(sys.stdin)
    if raw.get("tool_name") != "Bash":
        return
    command = raw.get("tool_input", {}).get("command", "")
    if not allow_patterns or not cr.GH_WORD_RE.search(command):
        return
    shielded, heredoc_bodies = cr.shield_heredocs(command)
    tokens = cr.tokenize(shielded)
    if tokens is None:
        return  # 解析不能は coldread が長さに応じて止める(射程は README)
    live = cr.has_live_substitution(shielded)
    for simple in cr.simple_commands(tokens):
        args = cr.gh_args(simple)
        if args is None:
            continue
        candidates, blocked = cr.classify(args, heredoc_bodies, live)
        if not candidates and not blocked:
            continue  # 投稿の形をしていない
        dest = dest_of(args, cr.subcommand(args), raw.get("cwd") or "")
        if dest is None:
            cr.log_line(DENY_LOG, "deny 宛先不明: " + command[:150].replace("\n", " "))
            cr.deny(
                "外部投稿ゲート(destgate): 宛先の許可制が有効だが、この投稿の宛先を"
                "コマンドから特定できない。-R owner/repo で宛先を明示して再実行すること。"
            )
        matched = any(fnmatch.fnmatchcase(dest.lower(), pat.lower())
                      for pat in allow_patterns)
        if not matched:
            cr.log_line(DENY_LOG, f"deny {dest}: " + command[:150].replace("\n", " "))
            cr.deny(
                f"外部投稿ゲート(destgate): この投稿の宛先 {dest} は許可一覧に無い。\n"
                f"許可一覧は {ALLOWLIST}(owner/repo か owner/* を 1 行ずつ)。\n"
                "一覧の管理は人の仕事——この deny を受けたモデルは一覧を自分で編集せず、"
                "宛先を許してよいか人に確認すること。"
            )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 検査できないものを黙って通さない(coldread と同じ倒し方)
        cr.deny("外部投稿ゲート(destgate): 検査自体に失敗した(%s)。" % str(exc)[:150])
