#!/usr/bin/env python3
"""いま自分が居るセッションで何が起きたかを、記録から取り出して時系列に並べる。

〈目的〉並行して開いたセッションに戻ったとき、**その場に居なかった人でも同じ所まで
追いつける**材料を出す。判定（何のスレッドか・次の一手）はしない——それは読む人か
/what-am-i-doing の AI の仕事。

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

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import changemap  # noqa: E402 — 変更ファイルの木。/catchup と共用
from stance import stance  # noqa: E402 — 立場の判定。/catchup と共用

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
    """扱っている PR で私が何者か。判定は lib/stance.py（/catchup と共用）で、ここは gh から
    素の値（作者・レビュー依頼先・送ったレビュー・担当・発言）を取り出すだけ。

    「今どっちの立場か」は、戻ったときに真っ先に要る情報なのに、会話からは読み取りにくい
    （どちらの側でもレビューの話をするため）。GitHub に残っている事実から機械で決める。"""
    args = ["pr", "view"]
    if number:
        args.append(str(number))
    args += ["--json", "number,title,state,author,reviewRequests,reviews,assignees,comments,isDraft,url"]
    raw = gh(cwd, *args)
    if not raw:
        return None
    try:
        pr = json.loads(raw)
    except json.JSONDecodeError:
        return None
    me = gh(cwd, "api", "user", "--jq", ".login")
    if not me:
        pr["role"] = "判定できない（gh の認証ユーザを取れない）"
        return pr
    author = (pr.get("author") or {}).get("login", "")
    requested = [(r or {}).get("login") for r in pr.get("reviewRequests") or []]

    def mine(items):
        return any(((x or {}).get("author") or {}).get("login") == me for x in items or [])

    reviewed = mine(pr.get("reviews"))
    label = stance(me, author, True, requested, reviewed,
                   [(a or {}).get("login") for a in pr.get("assignees") or []],
                   reviewed or mine(pr.get("comments")))
    if author == me:
        pr["role"] = label
    else:
        # 作者と依頼先は、私が作者でないときに読む人が次に要る名前なので添える
        pr["role"] = (f"{label}（作者は {author}、レビュー依頼は "
                      + (", ".join(r for r in requested if r) or "誰にも出ていない") + "）")
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


def about(turn, phrase):
    """往復が話題の語句を含むか（依頼と返答の冒頭で見る。大文字小文字と空白の連なりは区別しない）。
    語ごとの OR にはしない——「さっきの 4 件」を「4」「件」で当てると、ほぼ全往復が残る（実測）。"""
    text = " ".join((turn["ask"] + " " + turn["reply"]).split()).lower()
    return " ".join(phrase.split()).lower() in text


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


def render(title, turns, started, touched, cwd, full, limit, topic=None):
    out = []
    w = out.append
    w(f"# このスレッド — {title or '（題が付いていない）'}")
    branch = git(cwd, "branch", "--show-current")
    w(f"  {cwd}" + (f" · ブランチ {branch}" if branch else ""))
    span = f"開始 {started:%m-%d %H:%M}" if started else "開始 不明"
    w(f"  {span} · 最後の動き {touched:%m-%d %H:%M} · やり取り {len(turns)} 往復")
    total = len(turns)
    if topic:
        # 話題で絞る（/catchup が番号でない語で呼ばれたとき）。会話にしか無い話題は GitHub に
        # 見に行く先が無いので、その語が出た往復だけを背骨として出す
        turns = [t for t in turns if about(t, topic)]
        w(f"  話題「{topic}」が出た往復 {len(turns)} 件だけを出す（全 {total} 往復）")
    w("")

    shown, elided = turns, 0
    if not full and len(turns) > limit:
        head = limit // 3
        shown = turns[:head] + [None] + turns[head - limit:]
        elided = len(turns) - limit
    w("## 経過（依頼と、それに対して何をしたか）")
    if not turns:
        w("  この話題が出た往復は無い" if topic else "  依頼の記録がまだ無い")
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
    # 呼ばれた頻度の高い番号から順に当てる。issue の番号や消えた PR は gh が
    # 失敗して None になるので次の候補へ、全部外れたらブランチの PR に落とす
    pr = None
    for number in numbers[:3]:
        pr = role_on(cwd, number)
        if pr:
            break
    if not pr and branch:
        pr = role_on(cwd)
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

    dirty, tree = changemap.working_tree(cwd)
    w("## いま手元に残っているもの")
    if dirty:
        w(f"  未コミット {len(dirty)} 件: " + ", ".join(dirty[:8])
          + ("…" if len(dirty) > 8 else ""))
        # 木は「全体のどこを触っているか」を IDE の変更一覧と同じ形で見せる。周辺の追跡ファイルを
        # 薄く並べるので、変更ファイルの名前だけより場所が読める。そのまま diff の枠に貼れる
        w("  木（行頭 + が新規・~ が変更・- が削除。そのまま diff の枠に貼る）:")
        out.extend(tree)
        out.extend(render_frames(cwd, dirty))
    else:
        w("  未コミットの変更なし")
    w("")

    w("見ていないもの:")
    # 上限や話題で外した分は、件数と「それで何を見落としうるか」まで書く（/catchup と同じ）。
    # 件数だけでは、読む人がこの報告のどこを疑えばよいか分からない
    w("  - 私の返答は各ターンの冒頭だけ。続きと、道具に渡した中身は記録の側にある")
    if elided:
        w(f"  - 間の {elided} 往復（--full で出る）。そこで決めたことがあれば見落とす")
    if topic and total > len(turns):
        w(f"  - 話題「{topic}」が出なかった往復 {total - len(turns)} 件。言い換えで呼ばれていれば見落とす")
    w("  - 記録に残らないやり取り（別のセッション・チャット・口頭）")
    w("  - 題は序盤に付いたまま更新されない。古い可能性がある")
    return "\n".join(out)


def _head_and_outline(path, lines):
    """新規 file は先頭コメント（自己紹介）と骨組みだけ——全行が新しいので枠は何も伝えない。"""
    out = []
    head, cut = changemap.file_head(path, lines)
    out.extend("    | " + ln for ln in head)
    if cut:
        out.append(f"    （先頭は {changemap.HEAD_LINES} 行で切った）")
    out.extend("    | " + ln for ln in changemap.outline(path, lines)[:changemap.OUTLINE_CAP])
    return out


def render_frames(cwd, dirty, only=None, cap=changemap.FRAME_FILE_CAP):
    """未コミットの変更の中身を、関数まるごと（git diff -W HEAD）の枠で。新規 file（未追跡・add 済み）は
    先頭コメントと骨組みだけ、散文・設定は 1 行だけ——どちらも --frame なら全部出す。追跡 file で diff に
    hunk が無ければ（バイナリ・mode・改名だけ）その旨。only は 1 file に絞る path（--frame）。"""
    out = []
    w = out.append
    paths = (only,) if only else ()
    frames = changemap.framed_diff(changemap.function_diff(cwd=cwd, rev="HEAD", paths=paths) or "")
    targets = [only] if only else sorted(dirty)
    if not only:
        w("  変更の中身（" + changemap.FRAME_NOTE + f"。1 file {cap} 行、合計 {changemap.FRAME_TOTAL_CAP} 行を"
          "超えたら関数の切れ目で止めて、残りは --frame path で）:")
    total = 0
    for path in targets:
        info = frames.get(path)
        full = pathlib.Path(cwd) / path
        tracked = bool((changemap.git("ls-files", "--", path, cwd=cwd) or "").strip())
        if info is None and tracked:
            if only:
                sys.exit(f"{path} は追跡 file で、未コミットの変更が diff に無い（変更なし・バイナリ・mode・改名だけ）")
            w(f"    === {path}（中身が diff に無い。バイナリ・mode・改名だけ）")
            continue
        if info is None or (info["new"] and not only):
            # 新規（未追跡・add 済み）は先頭と骨組みだけ
            if not full.is_file():
                continue
            try:
                lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            kind = "add 済みの新規" if info else "未追跡の新規"
            w(f"    === {path}（{kind}。{len(lines)} 行。先頭と骨組みだけ——全文は --frame {path} か file を開く）")
            out.extend(_head_and_outline(path, lines))
            continue
        if not only and changemap.is_prose(path):
            w(f"    === {path}（散文・設定。枠は出さない——何を言うようになったかは file で。--frame {path} で枠は出る）")
            continue
        if not only and total >= changemap.FRAME_TOTAL_CAP:
            w(f"    === {path}（合計の上限。--frame {path} で出る）")
            continue
        w(f"    === {path}" + ("（新規）" if info["new"] else ""))
        rows = changemap.join_frames(path, info, cap=None if only else cap)
        for prefix, ln in rows:
            w("    " + prefix + ln)
        total += len(rows)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(
        description="このセッションで何が起きたかを、追いつける形で並べる")
    p.add_argument("--frame", metavar="path",
                   help="この file の未コミットの変更だけを、関数まるごとの枠で全部出す（上限なし）。"
                        "セッション記録は読まない")
    p.add_argument("--limit", type=int, default=25,
                   help="出す往復の上限（既定 25。超えたら間を省く）")
    p.add_argument("--full", action="store_true",
                   help="全往復を省かず、依頼と返答も切り詰めずに出す（返答は最初のひとまとまりのまま）")
    p.add_argument("--topic", nargs="+", metavar="語",
                   help="この語句が出た往復だけを出す（/catchup が番号でない語で呼ばれたとき）。"
                        "複数の語は 1 つの語句として続けて当てる")
    a = p.parse_args(argv)
    topic = " ".join(a.topic).strip() if a.topic else None
    if a.topic and not topic:
        sys.exit("--topic には話題の語句を渡す（空だった）")

    cwd = pathlib.Path.cwd()
    if a.frame:
        lines = render_frames(cwd, [a.frame], only=a.frame)
        if not lines:
            sys.exit(f"{a.frame} が無い（path はリポジトリの根からの相対）")
        print("\n".join(lines))
        return 0
    path = transcript_path(os.environ.get("CLAUDE_CODE_SESSION_ID"), cwd)
    if not path:
        sys.exit(f"このディレクトリ（{cwd}）のセッション記録が見つからない")

    title, turns, first, touched = read(path)
    print(render(title, turns, stamp(first) or touched, touched, cwd, a.full, a.limit,
                 topic=topic))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        sys.exit(f"what-am-i-doing.py が想定外の例外で停止: {type(e).__name__}: {e}")
