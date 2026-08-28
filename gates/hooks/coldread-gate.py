#!/usr/bin/env python3
"""外部投稿ゲート (PreToolUse/Bash)。

gh で GitHub へ本文を投稿するコマンド(issue/PR のコメント・本文、release notes、gist 等)を
検出すると、フック自身が読み役を走らせる:
コマンドから本文を取り出し、文脈ゼロの別プロセス(既定は claude -p の headless 実行)に
初見で読ませ、理解を妨げた「詰まり」が出たら deny の理由にその指摘を載せて止める。
「疑問」(理解はできたが答えが本文に無いもの)は止めずに申し送る——疑問ゼロの文章は
ほぼ書けず、疑問で止めるとゲートが厳しすぎて逃げ道が常態化するため。

検査の実行を書き手(モデル)の申告に頼らないので、「検査した印だけ押して通す」穴が
構造的に無い(自動の振る舞いはフックが実行する、の原則)。再実行のたびに新しい
読み手が直後の本文を読むため、「毎回新規の読み役」も機械が保証する。

逃げ道は COLDREAD_SKIP=1 の 1 本(記録が残る)。読み役が起動できないときも
deny + 逃げ道の案内にする(投稿不能にはならない)。連続 3 回 deny されたら、
残る指摘の採否を判断して skip してよい旨を案内する(初見指摘は読み手ごとに揺れ、
完全収束しないため。firstread-loop と同じ知見)。

環境変数:
  COLDREAD_SKIP=1            この 1 回だけゲートを通す(記録が残る)
  COLDREAD_READER_CMD        読み役コマンドの差し替え(POSIX sh 文字列として sh -c 実行。stdin に依頼文+本文)。テスト用
  COLDREAD_MODEL             既定 sonnet
  COLDREAD_EFFORT            既定 medium
  COLDREAD_MIN_LEN           これ未満のコマンドは素通し。既定 400
  COLDREAD_KEYCHAIN_SERVICE  macOS Keychain の OAuth トークンのサービス名(未指定なら
                             CLAUDE_CONFIG_DIR の末尾から推定: ~/.claude-p1 → claude-code-oauth-p1)
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

# Windows では stdio が locale 既定の code page になり(GitHub Actions windows-latest で
# cp1252 を実測。日本語 Windows なら cp932)、日本語の deny メッセージが UnicodeEncodeError で
# 落ちてフック自体が素通りになるため、UTF-8 に固定する(hook の入出力は UTF-8 の JSON)。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
STATE_DIR = os.path.join(CONFIG_DIR, "coldread-gate")
SKIP_LOG = os.path.join(STATE_DIR, "skip.log")
DENY_LOG = os.path.join(STATE_DIR, "denies.log")
MIN_LEN = int(os.environ.get("COLDREAD_MIN_LEN", "400"))
# 上限。これを超える文字列は正規表現の後方追跡(HEREDOC_RE)が重くなりうるので解析せず deny
MAX_LEN = int(os.environ.get("COLDREAD_MAX_LEN", "100000"))
READER_TIMEOUT = 210
DENY_STREAK_WINDOW = 30 * 60

# ---- 投稿の判定 ------------------------------------------------------------
# 「gh らしさ」と「旗らしさ」を文字列全体へ独立に照合する方式は、複合コマンドで別コマンドの
# 旗を gh の物と誤認し(git checkout -b)、引用・短縮形で取りこぼした(0.2.x で実測)。
# gh 側に機械可読な read/write 分類は無い(https://github.com/cli/cli/issues/12912 が
# 同要求のまま停滞)ため、シェル文字列を段階的に解く:
# ヒアドキュメントを盾置換(shlex はヒアドキュメントを解析できない) → shlex(POSIX 引用規則)で
# トークン化 → リダイレクトを除き ; | & && || 改行 () で単純コマンドに区切り、gh の引数列の
# 中だけで「本文を運ぶ旗」を見る。同型の前処理(ヒアドキュメント盾置換)は guardian など先行例が
# あるが、単純コマンド分割と旗表は自作なので網羅性はテストで守る。方式の経緯と、これを不要に
# する次段(PATH シム + gh __complete 案)は docs/coldread-gate-next.md。
# 対象外と受容した形は gates/README.md「網の射程」。
# デリミタは引用の有無(' か " か無し)と . - を許し、<<- の字下げ終端も拾う。
HEREDOC_RE = re.compile(
    r"""<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_.-]*)\1\n(.*?)\n[ \t]*\2(?:\n|$)""", re.S
)

# 本文を運ぶ旗の表(非 api 経路はこれを引く。api・gist 経路は下でハードコード)。
# text=次の値が本文 / file=ファイル指定(- は stdin)。短縮形は gh 2.96.0 で確認:
# -b/--body・-F/--body-file(release では -n/--notes・-F/--notes-file)・-c/--comment(issue/pr の
# close・reopen)。-F は文脈で意味が変わる旗で、gh api では --field、workflow run でも field。
# それらは本文投稿ではないので下の NON_POSTING で表ごと除外する(is_api は別処理)。
TEXT_FLAGS = {
    "--body": "text", "-b": "text",
    "--notes": "text", "-n": "text",
    "--comment": "text", "-c": "text",
    "--body-file": "file", "--notes-file": "file", "-F": "file",
}
# gh pr review の -c/--comment はレビュー種別を選ぶ真偽旗で、本文を取らない(gh 2.96.0 で確認)
COMMENT_IS_BOOLEAN = {("pr", "review")}
# 本文旗と同じ綴りの旗を持つが投稿でない(値が機微・設定・入力)サブコマンド。表ごと除外する。
NON_POSTING = {("secret", "set"), ("variable", "set"), ("workflow", "run")}
# 値を取る global 旗(サブコマンド語の特定でだけ読み飛ばす)。-H/-X は api の前置で挟まりうる。
GLOBAL_VALUE_FLAGS = {"-R", "--repo", "-H", "--header", "-X", "--method"}
WRAPPERS = {"env", "command", "exec", "nohup"}
OP_CHARS = set("();<>|&\n")
# リダイレクト演算子(演算子と行き先を読み飛ばす)。&> >& <& は & を含むが区切りではない。
REDIRECT_OPS = {"<", ">", ">>", "<<", "<<<", "<&", ">&", "&>", "&>>", ">|"}
VAR_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\Z")
# 前段の粗選別。部分文字列だと highlight・through 等の語で解析に入ってしまう
GH_WORD_RE = re.compile(r"\bgh\b")


def shield_heredocs(command):
    """ヒアドキュメント本文を取り出し、解析用の文字列では印に置き換える。"""
    bodies = []

    def repl(m):
        bodies.append(m.group(3))
        return " __HEREDOC__ \n"

    return HEREDOC_RE.sub(repl, command), bodies


def tokenize(text):
    """POSIX の引用規則でトークン化する。引用が閉じない等で解析できなければ None。"""
    lex = shlex.shlex(text, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"  # 改行は区切りの演算子として残す
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:
        return None


def simple_commands(tokens):
    """演算子で区切った単純コマンドのトークン列を返す。リダイレクトは演算子と行き先ごと除く。"""
    cmds, cur, i = [], [], 0
    while i < len(tokens):
        tok = tokens[i]
        if tok and all(c in OP_CHARS for c in tok):
            if tok in REDIRECT_OPS:
                # 2>&1 の 2 のような先行 fd 番号はリダイレクトの一部で、引数ではない
                if cur and cur[-1].isdigit():
                    cur.pop()
                i += 2  # 演算子とその行き先(fd かファイル名)を読み飛ばす
                continue
            # ; | & && || 改行 () は単純コマンドの区切り
            if cur:
                cmds.append(cur)
                cur = []
            i += 1
            continue
        cur.append(tok)
        i += 1
    if cur:
        cmds.append(cur)
    return cmds


def gh_args(tokens):
    """単純コマンド 1 件が gh 呼び出しなら gh より後のトークン列を、違えば None を返す。"""
    i, after_wrapper = 0, False
    while i < len(tokens):
        tok = tokens[i]
        if tok == "gh" or tok.endswith("/gh"):
            return tokens[i + 1:]
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*=", tok):
            i += 1
            continue
        if tok in WRAPPERS:
            after_wrapper = True
            i += 1
            continue
        if after_wrapper and tok.startswith("-"):
            i += 1
            continue
        return None
    return None


def subcommand(args):
    """引数列の先頭の位置引数(最大 2 語)。旗の意味が api 系かどうかで変わるため先に確定する。"""
    words, i = [], 0
    while i < len(args) and len(words) < 2:
        tok = args[i]
        if tok in GLOBAL_VALUE_FLAGS:
            i += 2
            continue
        if tok.startswith("-") and tok != "-":
            break
        words.append(tok)
        i += 1
    return tuple(words)


def classify(args, heredoc_bodies):
    """gh の引数列から (本文候補, 検査できない本文の説明) を返す。"""
    sub = subcommand(args)
    if sub in NON_POSTING:
        return [], []  # 投稿でないので本文検出も検査もしない
    is_api = sub[:1] == ("api",)
    is_graphql = sub == ("api", "graphql")
    candidates, blocked = [], []

    def add(kind, value):
        if kind == "text":
            # 変数・コマンド置換は実行時まで中身が無く、検査できない
            if VAR_RE.match(value) or value.startswith("$("):
                blocked.append("変数・コマンド置換渡し")
            else:
                candidates.append(value)
        elif value in ("-", "@-"):
            if heredoc_bodies:
                candidates.extend(heredoc_bodies)
            else:
                blocked.append("別プロセスからの stdin 渡し")
        else:
            blocked.append("実ファイル指定")

    i, n, seen_ddash = 0, len(args), False
    while i < n:
        tok = args[i]
        if tok == "--":
            seen_ddash = True
        elif not seen_ddash and tok.startswith("-") and tok != "-":
            name, val = tok, None
            if tok.startswith("--") and "=" in tok:
                name, val = tok.split("=", 1)
            elif not tok.startswith("--") and len(tok) > 2:
                name, val = tok[:2], tok[2:]  # -b本文 の密着形
            if is_api:
                if name in ("-f", "-F", "--field", "--raw-field"):
                    if val is None and i + 1 < n:
                        i += 1
                        val = args[i]
                    if val and "=" in val:
                        key, fval = val.split("=", 1)
                        if key == "query" and is_graphql:
                            # mutation は投稿——長い文字列リテラルを本文として読ませる。
                            # query のみは素通し(長い GraphQL の読み取りを止めない)。
                            if re.search(r"\bmutation\b", fval):
                                candidates.extend(re.findall(r'"""(.*?)"""', fval, re.S))
                                candidates.extend(re.findall(r'"((?:[^"\\]|\\.)*)"', fval))
                        elif key == "body":
                            if name in ("-F", "--field") and fval.startswith("@"):
                                add("file", "@-" if fval == "@-" else fval[1:])
                            else:
                                add("text", fval)
                elif name == "--input":
                    if val is None and i + 1 < n:
                        i += 1
                        val = args[i]
                    add("file", val or "")
            else:
                kind = TEXT_FLAGS.get(name)
                if kind and not (name in ("-c", "--comment") and sub in COMMENT_IS_BOOLEAN):
                    if val is None and i + 1 < n:
                        i += 1
                        val = args[i]
                    add(kind, val or "")
        i += 1

    # gist は本文旗を持たず、位置引数(- は stdin)が本文そのもの。
    # -d/--desc・-f/--filename は値を取るので、その値を位置引数と数えない。
    if sub == ("gist", "create"):
        pos, j = [], 2
        while j < len(args):
            t = args[j]
            if t in ("-d", "--desc", "-f", "--filename"):
                j += 2
                continue
            if t.startswith("-") and t != "-":
                j += 1
                continue
            pos.append(t)
            j += 1
        if "-" in pos or "__HEREDOC__" in pos:
            add("file", "-")
        elif pos:
            blocked.append("実ファイル指定")

    return candidates, blocked


def posting_bodies(command):
    """コマンド文字列から (本文候補, 検査できない本文の説明, 解析成否) を返す。"""
    shielded, heredoc_bodies = shield_heredocs(command)
    tokens = tokenize(shielded)
    if tokens is None:
        return [], [], False
    candidates, blocked = [], []
    for simple in simple_commands(tokens):
        args = gh_args(simple)
        if args is None:
            continue
        c, b = classify(args, heredoc_bodies)
        candidates.extend(c)
        blocked.extend(b)
    # --input - に渡る JSON(このリポジトリの投稿作法)は、殻でなく .body を読ませる。
    # 殻は必ず本文より長いので、候補に残すと max(長さ) が殻を選び本文が読まれない。
    for text in list(candidates):
        try:
            obj = json.loads(text)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("body"), str):
            candidates.remove(text)
            candidates.append(obj["body"])
    return candidates, blocked, True


READER_PROMPT = """あなたはこの文章について何も知らない初見の読者です。会話の経緯もリポジトリも見ていません。
以下の「本文」だけを読み、理解を実際に妨げた事実だけを報告してください。

見る観点:
(1) この文章があなたに求めていること(読んで何をすべきか)が言えるか
(2) 冒頭 3 行で「何の話か・自分に関係あるか・急ぐか」が掴めるか
(3) 本文の中だけでは意味を解決できない略語・識別子・参照は無いか
(4) 意味を推測で埋めた箇所は無いか
(5) 読み終えて残った疑問は何か

報告の形式(この 3 種類だけ。問題の無かった観点は一切書かない):
- (1)〜(4) に該当し、理解を実際に妨げたもの → 1 行 1 件、行頭に「詰まり: 」
- (5) のうち、理解はできたが答えが本文に無い疑問 → 1 行 1 件、行頭に「疑問: 」
- どちらも 1 件も無ければ、他に何も書かず CLEAN とだけ出力
規則: 点数・総評・文体の好み・軽微な言い換え提案は書かない。読めば分かることへの確認は書かない。日本語で。

--- 本文 ---
"""


def allow() -> None:
    sys.exit(0)


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    sys.exit(0)


def log_line(path: str, text: str) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s\t%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def deny_streak() -> int:
    try:
        with open(DENY_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-10:]
    except OSError:
        return 0
    n = 0
    now = time.time()
    for line in reversed(lines):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2:
            break
        try:
            ts = time.mktime(time.strptime(parts[0], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            break
        if now - ts > DENY_STREAK_WINDOW or parts[1] != "deny":
            break
        n += 1
    return n


def keychain_service() -> str:
    svc = os.environ.get("COLDREAD_KEYCHAIN_SERVICE")
    if svc:
        return svc
    # 利用者のシェルラッパーの命名慣行から推定: ~/.claude → -default, ~/.claude-p1 → -p1
    base = os.path.basename(CONFIG_DIR.rstrip("/"))
    suffix = "default" if base == ".claude" else base.replace(".claude-", "")
    return "claude-code-oauth-" + suffix


def run_reader(body: str):
    """読み役を起動して出力文字列を返す。失敗は例外。"""
    override = os.environ.get("COLDREAD_READER_CMD")
    if override:
        # POSIX シェル文字列として sh -c で実行する。shell=True だと Windows では
        # cmd.exe に渡ってしまい、/dev/null 等が解決できない(GitHub Actions windows-latest で実測)。
        # 復号は strict に保つ——errors="replace" だと壊れた読み役出力で「詰まり」の行頭一致が
        # 崩れ、deny が無音 allow に化ける。読めない出力は例外→deny(検査できないものは通さない)。
        proc = subprocess.run(
            ["sh", "-c", override], input=READER_PROMPT + body,
            capture_output=True, encoding="utf-8", timeout=READER_TIMEOUT,
        )
    else:
        # 認証: トークンを Keychain から読み、形式を検査して環境変数で渡す(ディスクにもログにも書かない)。
        # 取れなくても claude 自身の保存済み認証で動く場合があるため、失敗は握って進む。
        env = dict(os.environ)
        env.setdefault("CLAUDE_CONFIG_DIR", CONFIG_DIR)
        if "CLAUDE_CODE_OAUTH_TOKEN" not in env and sys.platform == "darwin":
            try:
                tok = subprocess.run(
                    ["security", "find-generic-password", "-s", keychain_service(), "-w"],
                    capture_output=True, encoding="utf-8", timeout=10,
                ).stdout.strip()
                if tok.startswith("sk-ant-oat01-"):
                    env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
            except Exception:
                pass
        claude_bin = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
        os.makedirs(STATE_DIR, exist_ok=True)
        proc = subprocess.run(
            [claude_bin, "-p", READER_PROMPT + body,
             "--model", os.environ.get("COLDREAD_MODEL", "sonnet"),
             "--effort", os.environ.get("COLDREAD_EFFORT", "medium")],
            capture_output=True, encoding="utf-8", timeout=READER_TIMEOUT,
            cwd=STATE_DIR, env=env,  # cwd を state 側にしてプロジェクト設定を子に読ませない
        )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or not out:
        raise RuntimeError((proc.stderr or "empty output")[:200])
    return out


ESCAPE_NOTE = (
    "軽微と判断した指摘を残して通すとき・検査器が使えないときは、"
    "コマンド先頭に COLDREAD_SKIP=1 を付けて再実行する(記録が残る)。"
)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        command = payload.get("tool_input", {}).get("command", "") or ""
    except Exception:
        allow()

    if len(command) < MIN_LEN or not GH_WORD_RE.search(command):
        allow()

    if "COLDREAD_SKIP=1" in command:
        log_line(SKIP_LOG, command[:200].replace("\n", " "))
        log_line(DENY_LOG, "skip")
        allow()

    # 解析の失敗は例外の形でも起こりうる(壊れた JSON の再帰・想定外の入力)。
    # 「引用が閉じない」を deny にしているのに例外だけ素通りでは、検査を避ける口になる。
    # 捕まえるのは Exception 全体で、ValueError に狭めるな——狭めた瞬間に、それ以外の例外は
    # フックのクラッシュ(=PreToolUse は続行)になって無検査で通る。
    try:
        if len(command) > MAX_LEN:
            raise RuntimeError("コマンドが長すぎる(%d 文字)" % len(command))
        candidates, blocked, parsed = posting_bodies(command)
    except Exception as exc:
        parsed, candidates, blocked = False, [], []
        parse_error = str(exc)[:150]
    else:
        parse_error = "引用が閉じていない等"
    if not parsed:
        log_line(DENY_LOG, "deny")
        deny(
            "外部投稿ゲート: このコマンドは解析できない(%s)。" % parse_error
            + "gh を含むため、投稿かどうか確かめられないものは通せない。\n"
            "引用を直して再実行すること。\n" + ESCAPE_NOTE
        )

    # 「検査できない本文がある」は、別の本文が読めたかどうかと独立に止める。
    # ここを bodies の有無に従属させると、読める本文と同居した投稿が無検査で通る。
    if blocked:
        log_line(DENY_LOG, "deny")
        deny(
            "外部投稿ゲート: この投稿は本文をコマンドから取り出せない形をしている(%s)。"
            "検査できないものは通せない。\n"
            "本文はヒアドキュメント(<<'EOF' ... EOF)か、そのサブコマンドの本文旗"
            "(--body / --notes 等)に直接書いて再実行すること。\n"
            % "・".join(sorted(set(blocked))) + ESCAPE_NOTE
        )

    bodies = [b for b in candidates if len(b.strip()) >= 200]
    if not bodies:
        allow()
    # 複数の本文が同居するときは最長を代表として読ませる(全部読ませると読み役の回数と
    # 待ち時間が本文の数だけ増える)。取りこぼしの受容は gates/README.md「網の射程」。
    body = max(bodies, key=len)

    try:
        out = run_reader(body)
    except Exception as exc:
        log_line(DENY_LOG, "deny")
        deny(
            "外部投稿ゲート: 読み役の起動に失敗した(%s)。\n" % str(exc)[:150]
            + "手動で検査するなら skill『coldread』の手順で読み役を立てること。\n"
            + ESCAPE_NOTE
        )

    lines = [l.strip() for l in out.splitlines() if l.strip()]
    blocking = [l for l in lines if l.startswith("詰まり")]
    questions = [l for l in lines if l.startswith("疑問")]
    is_clean = bool(re.fullmatch(r"\**CLEAN\**\.?", lines[-1])) or out.strip() in ("CLEAN", "**CLEAN**")

    if is_clean or not blocking:
        log_line(DENY_LOG, "allow")
        if questions:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": "冷読は通過(詰まりゼロ)",
                    "additionalContext": "投稿は通したが、初見の読み手に残った疑問(必要なら本文に反映して編集してよい):\n" + "\n".join(questions),
                }
            }, ensure_ascii=False))
        sys.exit(0)

    streak = deny_streak() + 1
    log_line(DENY_LOG, "deny")
    tail = (
        "\n\n【%d 回連続で止まっている】初見指摘は読み手ごとに揺れる。残る指摘の採否を自分で判断し、"
        "採らない指摘を理由にもう直さないなら COLDREAD_SKIP=1 で通してよい(記録が残る)。" % streak
        if streak >= 3 else "\n\n" + ESCAPE_NOTE
    )
    deny(
        "外部投稿ゲート: 文脈ゼロの読み手(別プロセス)がこの本文で詰まった。以下を直してから"
        "同じ形で再実行すること(再実行時は直した本文を新しい読み手が検査する):\n\n"
        + "\n".join(blocking + questions)[:1500]
        + "\n\n直し方: 指摘の類型を言語化してから、同型を本文全体で掃討する(指摘された 1 箇所だけ直さない)。"
        "詳細は skill『coldread』。"
        + tail
    )


if __name__ == "__main__":
    main()
