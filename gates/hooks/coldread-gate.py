#!/usr/bin/env python3
"""外部投稿ゲート (PreToolUse/Bash)。

gh で issue / PR へ本文を投稿するコマンドを検出すると、フック自身が読み役を走らせる:
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
  COLDREAD_READER_CMD        読み役コマンドの差し替え(shell 文字列。stdin に依頼文+本文)。テスト用
  COLDREAD_MODEL             既定 sonnet
  COLDREAD_EFFORT            既定 medium
  COLDREAD_MIN_LEN           これ未満のコマンドは素通し。既定 400
  COLDREAD_KEYCHAIN_SERVICE  macOS Keychain の OAuth トークンのサービス名(未指定なら
                             CLAUDE_CONFIG_DIR の末尾から推定: ~/.claude-p1 → claude-code-oauth-p1)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

# Windows では stdio が cp1252 になり日本語の deny メッセージで UnicodeEncodeError に
# なるため、UTF-8 に固定する(hook の入出力は常に UTF-8 の JSON)。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
STATE_DIR = os.path.join(CONFIG_DIR, "coldread-gate")
SKIP_LOG = os.path.join(STATE_DIR, "skip.log")
DENY_LOG = os.path.join(STATE_DIR, "denies.log")
MIN_LEN = int(os.environ.get("COLDREAD_MIN_LEN", "400"))
READER_TIMEOUT = 210
DENY_STREAK_WINDOW = 30 * 60

# gh コマンドか(コマンド位置に gh。環境変数の前置は許す)
GH_RE = re.compile(r"(?:^|[;&|]\s*|\$\(\s*)(?:[A-Z_]+=\S+\s+)*gh\s", re.MULTILINE)
# 外向きの本文を運ぶ旗を持つか。サブコマンドを列挙しない——--body/--notes/--comment 等は
# gh 全体の共通規約なので、issue/pr/release/gist や将来のコマンドもこれで網に入る。
# 注意: 素の -f/--field を指標にしない(gh api graphql -f query=... は読み取りで、
# 巻き込むと長い GraphQL が誤って止まる)。フィールド名 body= のときだけ拾う。
PAYLOAD_RE = re.compile(
    r"(?:"
    r"--(?:body|notes|comment)(?:[= ]|$)"
    r"|-b[= ]"
    r"|--(?:body|notes)-file[= ]"  # 実ファイル指定も拾う(抽出できず deny になる=検査できないものは通さない)
    r"|--input[= ]-"
    r"|(?:-f|-F|--field|--raw-field)[= ]?body="
    r")",
    re.MULTILINE,
)

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


def body_candidates(command: str) -> list:
    out = []
    for m in re.finditer(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?\n(.*?)\n\1(?:\n|$)", command, re.S):
        text = m.group(2)
        out.append(text)
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and isinstance(obj.get("body"), str):
                out.append(obj["body"])
        except ValueError:
            pass
    flags = r"(?:--body|--notes|--comment|-b|(?:-f|-F|--field|--raw-field)[= ]?body)"
    for m in re.finditer(flags + r"[= ]'((?:[^'\\]|\\.)*)'", command, re.S):
        out.append(m.group(1))
    for m in re.finditer(flags + r'[= ]"((?:[^"\\]|\\.)*)"', command, re.S):
        out.append(m.group(1))
    return out


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
        proc = subprocess.run(
            override, shell=True, input=READER_PROMPT + body,
            capture_output=True, encoding="utf-8", errors="replace", timeout=READER_TIMEOUT,
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
                    capture_output=True, text=True, timeout=10,
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
            capture_output=True, encoding="utf-8", errors="replace", timeout=READER_TIMEOUT,
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
        command = payload.get("tool_input", {}).get("command", "")
    except Exception:
        allow()

    if not GH_RE.search(command) or not PAYLOAD_RE.search(command) or len(command) < MIN_LEN:
        allow()

    if "COLDREAD_SKIP=1" in command:
        log_line(SKIP_LOG, command[:200].replace("\n", " "))
        log_line(DENY_LOG, "skip")
        allow()

    bodies = [b for b in body_candidates(command) if len(b.strip()) >= 200]
    if not bodies:
        deny(
            "外部投稿ゲート: この投稿は本文をコマンドから取り出せない形をしている"
            "(エディタ起動・実ファイル指定など)。検査できないものは通せない。\n"
            "本文をヒアドキュメント(--body-file - <<'EOF' ... EOF)か --body で渡す形にして再実行すること。\n"
            + ESCAPE_NOTE
        )
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
