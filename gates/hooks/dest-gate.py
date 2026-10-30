#!/usr/bin/env python3
"""destgate — 投稿の宛先を許可一覧で縛るゲート(PreToolUse:Bash)。

coldread(通じやすさ)とは別の軸「その宛先へ出してよいか」を検査する。
許可一覧が無ければ眠っている(何も出さず allow)。一覧の管理は人の仕事で、
モデルが自分で追記して通すのはゲートの無効化になる——deny 文言でも明示する。

coldread と別フックにしてあるのは、通じやすさの検査の倒れ方(読み役の故障・続けて止まる往復)に
宛先の検査を巻き込まないため(前は coldread に逃げ道 COLDREAD_SKIP=1 が在り、それで宛先の検査まで
外れる経路を作らないためでもあった)。宛先の判定は決定的(LLM なし)なので、
このゲート自身には逃げ道が無い——通したければ人が一覧へ追記する。それが記録になる。
解析部(トークン化・単純コマンド分割・旗表)は coldread-gate.py から読み込んで共有する。
"""
import fnmatch
import functools
import json
import os
import re
import sys
import time

# `sys.path[0]` に頼らない(coldread-gate.py が claude_auth を読むのと同じ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_auth  # noqa: E402
import gate_shell  # noqa: E402

# 解析部の coldread-gate.py は、許可一覧が在るときだけ読む(眠っている既定の形では、Bash のたびに読まない)
cr = None

CONFIG_DIR = claude_auth.config_dir(os.environ)   # 隣の coldread-gate と同じ置き場（決め方の正本は共通の claude_auth）
ALLOWLIST = os.path.join(CONFIG_DIR, "destgate", "allowlist")
DENY_LOG = os.path.join(CONFIG_DIR, "destgate", "denies.log")
# gh に宛先を引かせる時間の合計。hooks.json の destgate の timeout(30 秒)より短くする: フックが時間切れで終わると
# Claude Code は止めずに通すので、引き切れないときはこのゲートが自分で止める(宛先不明)
GH_BUDGET = 20
_DEADLINE = None   # coldread-gate.py を読んだ時から GH_BUDGET 秒
# 値に本文・題を取る旗(その値は宛先でない)
TEXT_FLAGS = {"-b", "--body", "-t", "--title"}
# 投稿先を指す issue・PR・discussion の URL(gh はこれを位置引数に受ける)
ITEM_URL_RE = re.compile(r"https?://[^/\s]+/(?P<o>[^/\s]+)/(?P<r>[^/\s]+)/(?:issues|pull|discussions)/\d+")


def patterns():
    """許可一覧(1 行 1 パターン。owner/repo・owner/*・gist。# 始まりと空行は無視)。"""
    try:
        with open(ALLOWLIST, encoding="utf-8") as f:
            return [ln.strip() for ln in f
                    if ln.strip() and not ln.strip().startswith("#")]
    except OSError:
        return []


def owner_repo(value):
    r"""-R の値から owner/repo を取り出す。取れなければ None。

    gh の -R は OWNER/REPO・HOST/OWNER/REPO・完全 URL(https/ssh)のどれも受けるので、
    末尾 2 セグメントを取り .git を落とす。ssh の別名ホスト(github.com-xxx:o/r)も
    : 以降がパスなので同じ規則で拾える。

    読むのは利用者が打った -R の値だけ。-R の無い投稿の宛先は git の remote の URL を読まず gh に解かせる(current_repo)。
    `\` を `/` に替えるのは、Windows で打った URL の綴りを受けるため。
    """
    v = value.strip().replace("\\", "/").rstrip("/")
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


@functools.lru_cache(maxsize=None)
def current_repo(cwd):
    """-R の無い投稿の宛先。gh 自身に解かせて owner/repo を返す。解けなければ None(宛先不明で止める)。

    origin を読まない: gh は -R の無いとき、gh repo set-default で決めた repo か、remote の中から選んだ repo へ投稿する
    (origin とは限らない。https://cli.github.com/manual/gh_repo_set-default)。投稿と同じ解き方の
    `gh repo view --json nameWithOwner` で引く(機械向けの形。docs/standards/machine-readable-values.md の決まり 2)。
    cwd ごとに 1 回だけ引き(1 本のコマンドの中の、-R の無い gh を同じ cwd で何度も引かない)、引く時間の合計は GH_BUDGET で縛る。"""
    try:
        # gh の呼び方(差し替えの口 COLDREAD_GH_CMD・時間の上限)は coldread の画面の取得と同じ 1 本
        screen = cr.Screen(cwd)
        screen.deadline = min(screen.deadline, _DEADLINE)
        got = screen.json(["repo", "view", "--json", "nameWithOwner"])
        name = got.get("nameWithOwner") if isinstance(got, dict) else None
    except Exception as exc:   # 起動できない・gh が失敗した・JSON でない: 宛先不明として止める(呼び元)
        cr.log_line(DENY_LOG, "gh repo view で宛先を引けない: %s" % str(exc)[:150].replace("\n", " "))
        return None
    if not isinstance(name, str) or name.count("/") != 1:
        cr.log_line(DENY_LOG, "gh repo view の nameWithOwner が owner/repo でない: %r" % (name,))
        return None
    return name


def dest_of(args, sub, cwd, gh_repo_env=False):
    """gh 引数列から投稿の宛先を決める。分からなければ None。

    cwd はその gh が走る場所(前の `cd <絶対パス> &&` を読んだもの。決まらなければ None)。gh_repo_env は、コマンドが
    環境変数 GH_REPO を書いている(gh は -R の無いとき GH_REPO の repo へ投稿する。https://cli.github.com/manual/gh_help_environment)。"""
    # -R / --repo が最優先(gh 自身の解決順もこれが勝つ)。旗の読み方は coldread と同じ 1 本(cr.flag_value)。
    # 何度も書けば gh は最後の値を使うので、全部を読み、食い違えば宛先不明にする(前は最初の値だけを見ていて、
    # `-R 許可した/repo -R 外/repo` を許可一覧の repo と取り違えて通していた)
    values = {owner_repo(v) for i, tok in enumerate(args) if tok.startswith(("-R", "--repo"))
              for v in [cr.flag_value(args[i:i + 2], "-R", "--repo")] if v is not None}
    # 本文・題の値が -R で始まる(`--title -Ro/r`)なら、gh はそれを -R と読まない。どちらか決めずに宛先不明にする
    if any(tok.startswith(("-R", "--repo")) and args[i - 1] in TEXT_FLAGS for i, tok in enumerate(args) if i):
        return None
    # 投稿先の issue・PR を URL で書けば、gh は -R でも走る場所でもなく URL の repo へ投稿する
    # (`gh pr comment https://github.com/o/r/pull/3`。前は走る場所の repo を宛先と取り違えて通していた)
    values |= {f"{m['o']}/{m['r']}" for i, tok in enumerate(args) if not (i and args[i - 1] in TEXT_FLAGS)
               for m in [ITEM_URL_RE.match(tok)] if m}
    if values:
        return values.pop() if len(values) == 1 else None
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
    # 明示が無ければ gh が GH_REPO か、走る場所のリポジトリから選んだ repo へ投稿する。GH_REPO の値と走る場所が
    # 読み切れないときは宛先不明にする(フックの cwd で引くと、別のリポジトリへの投稿を許可一覧の repo と取り違える)
    if gh_repo_env or not cwd:
        return None
    return current_repo(cwd)


def main():
    global cr, _DEADLINE
    allow_patterns = patterns()
    if not allow_patterns:
        return   # 一覧が無ければ眠る(入力も読まない)
    cr = gate_shell.load_coldread()
    _DEADLINE = time.time() + GH_BUDGET
    try:
        raw = json.load(sys.stdin)
        command = raw.get("tool_input", {}).get("command", "") if raw.get("tool_name") == "Bash" else ""
        if not isinstance(command, str):
            raise ValueError("tool_input.command が文字列でない")
    except Exception as exc:
        # 読めない入力を通さない(決まり 4: ゲートは入力を読めなかったら通さない側に倒す)
        why = str(exc)[:150]
        gate_shell.refuse(cr, "destgate", "deny 入力を読めない: %s" % why,
                          "外部投稿ゲート(destgate): フックの入力(JSON)を読めないので、宛先を検査できない: %s" % why)
    if not cr.GH_WORD_RE.search(command):
        return
    # 解析の入口は coldread と同じ cr.analyze 1 本。ここで独自に組むと、片方だけ
    # 正規化が入って宛先検査が黙って外れる(行継続の穴のとき現にそうなっていた)。gh が走る場所(前の cd)も同じ読み方で取る
    analysis = cr.analyze(command, raw.get("cwd") or None)
    snippet = command[:150].replace("\n", " ")
    if not analysis.parsed:
        # 解析できない gh のコマンドは宛先を確かめられないので通さない。宛先の軸は coldread(通じやすさの軸)に任せず
        # このゲートが自分で止める
        gate_shell.refuse(cr, "destgate", "deny 解析不能: " + snippet,
                          "外部投稿ゲート(destgate): 宛先の許可制が有効だが、このコマンドを解析できず、宛先を確かめられない。"
                          "引用符の閉じ忘れなどを直し、-R owner/repo で宛先を明示して再実行すること。")
    # GH_REPO はコマンドのどこで書いても(前置・export)後の gh に効くので、値を追わず、書いてあれば -R の無い宛先を不明にする。
    # Bash のコマンドは Claude Code の環境を継ぐので、この殻の環境に GH_REPO が在るときも同じに見る
    gh_repo_env = "GH_REPO" in cr.prepare(command)[0] or bool(os.environ.get("GH_REPO"))
    for sub, args, candidates, blocked, cwd in analysis.calls:
        if not candidates and not blocked:
            continue  # 投稿の形をしていない
        if sub and sub[0] == cr.DISPATCH_SUB:
            continue  # works-dispatch の納品・頼みは手元の会社の中で届き、GitHub の宛先を持たない(本文は coldread が読む)
        dest = dest_of(args, sub, cwd, gh_repo_env)
        if dest is None:
            gate_shell.refuse(cr, "destgate", "deny 宛先不明: " + snippet,
                              "外部投稿ゲート(destgate): 宛先の許可制が有効だが、この投稿の宛先を"
                              "コマンドから特定できない。-R owner/repo で宛先を明示して再実行すること。")
        matched = any(fnmatch.fnmatchcase(dest.lower(), pat.lower())
                      for pat in allow_patterns)
        if not matched:
            gate_shell.refuse(cr, "destgate", f"deny {dest}: " + snippet,
                              f"外部投稿ゲート(destgate): この投稿の宛先 {dest} は許可一覧に無い。\n"
                              f"許可一覧は {ALLOWLIST}(owner/repo か owner/* を 1 行ずつ)。\n"
                              "一覧の管理は人の仕事——この deny を受けたモデルは一覧を自分で編集せず、"
                              "宛先を許してよいか人に確認すること。")


if __name__ == "__main__":
    gate_shell.run(main, lambda why: "外部投稿ゲート(destgate): 検査自体に失敗した(%s)。" % why,
                   lambda reason: gate_shell.load_coldread().deny(reason))
