#!/usr/bin/env python3
"""いま自分が居るセッションで何が起きたかを、記録から取り出して時系列に並べる。

〈目的〉並行して開いたセッションに戻ったとき、**その場に居なかった人でも同じ所まで
追いつける**材料を出す。判定（何のスレッドか・次の一手）はしない——それは読む人か
/whatamidoing の AI の仕事。

〈なぜ記録から取るか〉会話は長くなると要約されて前半が消える。記録の側には依頼も返答も
道具の使用も全部残っていて、要約を挟まないので痩せない。**「何を頼まれたか」だけでは
追いつけない**——「それに対して何をしたか」が要る。だから往復で並べる。

〈返答は冒頭だけ〉各ターンの返答は全文ではなく冒頭を取る。全文を並べると記録の写しに
なり、読む方が会話を遡るのと変わらなくなる。冒頭には結論が来る書き方を前提にしている
（そうでない書き方のセッションでは、ここは弱い手がかりになる）。

〈題が古びること〉Claude Code は序盤に付けた題（aiTitle）を後から更新しない。実測: 話題が
PR の棚卸しからプラグイン作りへ移った後も題は「PR残件確認」のままだった。題は出すが頼らない。
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 依頼者が自分で打った発言だけを拾う印。tool_result も user レコードとして落ちるので、
# これで絞らないと道具の出力が依頼に化ける（実測: 219 件中 189 件が tool_result）
TYPED = {"typed", "queued"}

# Bash の中身から「区切りになる操作」を拾う。全部のコマンドを並べても追いつく助けに
# ならないので、後から見て節目と分かるものだけ名前を付ける
LANDMARKS = (
    (re.compile(r"\bgit\s+commit\b"), "コミット"),
    (re.compile(r"\bgit\s+push\b"), "push"),
    (re.compile(r"\bgit\s+rebase\b"), "rebase"),
    (re.compile(r"\bgh\s+pr\s+create\b"), "PR 作成"),
    (re.compile(r"\bgh\s+run\s+(watch|view)\b"), "CI 確認"),
    (re.compile(r"tests?/run\.sh|\bpytest\b|\bnpm\s+test\b"), "テスト実行"),
)


# 依頼文に出てくる PR / issue の番号。何の件を扱っているかは、たいてい依頼者が
# 番号で呼んでいるので、そこから拾うのが一番素直
REFERENCED = re.compile(r"#(\d{1,6})\b")


def pick_reference(asks):
    """会話で呼ばれた番号を、本題である見込みの高い順に並べる。

    立場はブランチの PR ではなく会話の本題で決めたい。本題はたいてい依頼者が
    繰り返し番号で呼ぶので、頻度の高い順（同数なら後に呼ばれた方）にする。
    ブランチから引くと、別件のブランチに居るだけで別の PR を拾う（実測: レビューの
    セッションで、たまたま居たブランチの PR #1595 を本題として出した）。"""
    count, last = {}, {}
    for i, text in enumerate(asks):
        for hit in REFERENCED.findall(text):
            count[hit] = count.get(hit, 0) + 1
            last[hit] = i
    return sorted(count, key=lambda n: (-count[n], -last[n]))


def gh(cwd, *args):
    """gh を呼ぶ。認証切れ・ネット無し・PR 無しは失敗であって異常ではないので、
    空文字を返して呼び出し側で節ごと落とす（材料が減るだけで、判定は壊れない）。"""
    try:
        r = subprocess.run(  # noqa: S603 — 引数はこのファイル内のリテラルと数字だけ
            ["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def role_on(cwd, number=None):
    """扱っている PR で自分が実装者かレビュワーかを決める。

    「今どっちの立場か」は、戻ったときに真っ先に要る情報なのに、会話からは読み取りにくい
    （どちらの側でもレビューの話をするため）。作者とレビュー依頼先は記録に残っているので、
    そこから機械で決める。"""
    args = ["pr", "view"]
    if number:
        args.append(str(number))
    args += ["--json", "number,title,state,author,reviewRequests,isDraft,url"]
    raw = gh(cwd, *args)
    if not raw:
        return None
    try:
        pr = json.loads(raw)
    except json.JSONDecodeError:
        return None
    me = gh(cwd, "api", "user", "--jq", ".login")
    author = (pr.get("author") or {}).get("login", "")
    reviewers = [(r or {}).get("login") for r in pr.get("reviewRequests") or []]
    if me and author == me:
        pr["role"] = "実装者（この PR の作者）"
    elif me and me in reviewers:
        pr["role"] = "レビュワー（レビュー依頼が来ている）"
    elif me:
        pr["role"] = f"どちらでもない（作者は {author}、レビュー依頼は "
        pr["role"] += (", ".join(r for r in reviewers if r) or "誰にも出ていない") + "）"
    else:
        pr["role"] = "判定できない（gh の認証ユーザを取れない）"
    return pr


def transcript_path(session_id, cwd):
    """記録の実体を探す。session id が取れれば一意、取れなければ最新にする。"""
    config = pathlib.Path(
        os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude")
    folder = config / "projects" / str(cwd).replace("/", "-")
    if not folder.is_dir():
        return None
    if session_id:
        exact = folder / f"{session_id}.jsonl"
        if exact.exists():
            return exact
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def text_of(content):
    """message.content から人に見える文字列だけを取る。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [b.get("text", "") for b in content
             if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(p for p in parts if p)


def read(path):
    """記録を 1 度なめて、題と往復の並びを組み立てる。

    往復は「依頼者が打った発言」から次の発言までを 1 つとして数える。返答も道具の使用も
    その区間に属させる——どの依頼に対して何をしたかが、ここで結びつく。"""
    title, first_ts, turns = None, None, []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = o.get("type")
            if first_ts is None and o.get("timestamp"):
                first_ts = o["timestamp"]

            if kind == "ai-title" and o.get("aiTitle"):
                title = o["aiTitle"]
            elif kind == "user" and o.get("promptSource") in TYPED:
                body = text_of(o.get("message", {}).get("content"))
                if body.strip():
                    turns.append({"at": o.get("timestamp"), "ask": body.strip(),
                                  "reply": "", "tools": {}, "marks": []})
            elif kind == "assistant" and turns:
                turn = turns[-1]
                content = o.get("message", {}).get("content", [])
                said = text_of(content)
                # 返答は最初のひとまとまりだけ。以降は道具を挟んだ続きで、冒頭に結論が来る
                if said.strip() and not turn["reply"]:
                    turn["reply"] = said.strip()
                if isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict) or b.get("type") != "tool_use":
                            continue
                        name = b.get("name", "?")
                        turn["tools"][name] = turn["tools"].get(name, 0) + 1
                        cmd = (b.get("input") or {}).get("command", "")
                        for pattern, label in LANDMARKS:
                            if isinstance(cmd, str) and pattern.search(cmd) \
                                    and label not in turn["marks"]:
                                turn["marks"].append(label)
    return title, turns, first_ts, dt.datetime.fromtimestamp(path.stat().st_mtime)


def git(cwd, *args):
    try:
        r = subprocess.run(  # noqa: S603 — 引数はこのファイル内のリテラルだけ
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def dirty_paths(porcelain):
    """git status --porcelain の各行からパスだけを取る。

    位置で切ってはいけない。状態欄は 2 文字だが、出力全体を strip した時点で 1 行目の
    先頭空白が消え、以降の桁がずれる（実測: " M deploy/..." が "M deploy/..." になり、
    3 文字目から切ると "eploy/..." になった）。空白で 1 回だけ割って後ろを取る。"""
    out = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        out.append(parts[1] if len(parts) > 1 else parts[0])
    return out


def stamp(raw):
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def squeeze(text, limit):
    s = " ".join(text.split())
    return s[:limit] + "…" if limit and len(s) > limit else s


def render(title, turns, started, touched, cwd, full, limit):
    out = []
    w = out.append
    w(f"# このスレッド — {title or '（題が付いていない）'}")
    branch = git(cwd, "branch", "--show-current")
    w(f"  {cwd}" + (f" · ブランチ {branch}" if branch else ""))
    span = f"開始 {started:%m-%d %H:%M}" if started else "開始 不明"
    w(f"  {span} · 最後の動き {touched:%m-%d %H:%M} · やり取り {len(turns)} 往復")
    w("")

    shown, elided = turns, 0
    if not full and len(turns) > limit:
        head = limit // 3
        shown = turns[:head] + [None] + turns[head - limit:]
        elided = len(turns) - limit
    w("## 経過（依頼と、それに対して何をしたか）")
    if not turns:
        w("  依頼の記録がまだ無い")
    for item in shown:
        w("")
        if item is None:
            w(f"  … 間の {elided} 往復は省いた（--full で全部出る）")
            continue
        at = stamp(item["at"])
        head = f"  [{at:%m-%d %H:%M}] " if at else "  "
        w(head + squeeze(item["ask"], 0 if full else 160))
        if item["reply"]:
            w("      → " + squeeze(item["reply"], 0 if full else 200))
        detail = []
        if item["marks"]:
            detail.append("・".join(item["marks"]))
        if item["tools"]:
            detail.append("道具 " + ", ".join(
                f"{k}×{v}" for k, v in sorted(item["tools"].items(),
                                              key=lambda kv: -kv[1])[:4]))
        if detail:
            w("      " + " / ".join(detail))
    w("")

    numbers = pick_reference([turn["ask"] for turn in turns])
    if branch:
        # 呼ばれた頻度の高い番号から順に当てる。issue の番号や消えた PR は gh が
        # 失敗して None になるので次の候補へ、全部外れたらブランチの PR に落とす
        pr = None
        for number in numbers[:3]:
            pr = role_on(cwd, number)
            if pr:
                break
        pr = pr or role_on(cwd)
        if pr:
            w("## 扱っている件と、私の立場")
            draft = "・下書き" if pr.get("isDraft") else ""
            w(f"  #{pr.get('number')} {pr.get('title', '')}"
              f"（{str(pr.get('state', '')).lower()}{draft}）")
            w(f"  {pr.get('url', '')}")
            w(f"  **私の立場: {pr['role']}**")
            others = [n for n in numbers if n != str(pr.get("number"))]
            if others:
                w("  会話に出てきた他の番号: " + ", ".join("#" + n for n in others[:7]))
            w("")

    if started:
        since = started.strftime("%Y-%m-%dT%H:%M:%S")
        log = git(cwd, "log", "--oneline", f"--since={since}", "-20")
        if log:
            lines = log.splitlines()
            w(f"## このセッションの間に入ったコミット — {len(lines)} 件")
            for line in lines:
                w("  " + line)
            w("")

    dirty = dirty_paths(git(cwd, "status", "--porcelain"))
    w("## いま手元に残っているもの")
    if dirty:
        w(f"  未コミット {len(dirty)} 件: " + ", ".join(dirty[:8])
          + ("…" if len(dirty) > 8 else ""))
    else:
        w("  未コミットの変更なし")
    w("")

    w("見ていないもの:")
    w("  - 私の返答は各ターンの冒頭だけ。続きと、道具に渡した中身は記録の側にある")
    w("  - 記録に残らないやり取り（別のセッション・チャット・口頭）")
    w("  - 題は序盤に付いたまま更新されない。古い可能性がある")
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="このセッションで何が起きたかを、追いつける形で並べる")
    p.add_argument("--limit", type=int, default=25,
                   help="出す往復の上限（既定 25。超えたら間を省く）")
    p.add_argument("--full", action="store_true", help="全往復を全文で出す")
    a = p.parse_args(argv)

    cwd = pathlib.Path.cwd()
    path = transcript_path(os.environ.get("CLAUDE_CODE_SESSION_ID"), cwd)
    if not path:
        sys.exit(f"このディレクトリ（{cwd}）のセッション記録が見つからない")

    title, turns, first, touched = read(path)
    print(render(title, turns, stamp(first) or touched, touched, cwd, a.full, a.limit))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        sys.exit(f"whatamidoing.py が想定外の例外で停止: {type(e).__name__}: {e}")
