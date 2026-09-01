#!/usr/bin/env python3
"""いま自分が居るセッションが何のスレッドだったかの材料を、記録から取り出す。

〈目的〉並行して開いたセッションを切り替えたとき、「これ何をしていたんだっけ」を
毎回プロンプトで聞き直さずに済ませる。判定（何のスレッドか・次の一手）はしない——
それは読む人か /whatamidoing の AI の仕事。

〈なぜ記録から取るか〉会話は context に載っているが、長くなると要約されて前半が消える。
記録の側には**依頼者の発言が全部**残っていて、それがそのままスレッドの背骨になる。
要約を挟まず一次情報を並べるので、何を頼まれてきたかが痩せない。

〈題が古びること〉Claude Code は序盤に付けた題（aiTitle）を後から更新しない。実測: 話題が
PR の棚卸しからプラグイン作りへ移った後も題は「PR残件確認」のままだった。だから題は
出すが頼らない——判断の material は依頼者の発言の並びの方である。
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def transcript_path(session_id, cwd):
    """記録の実体を探す。session id が取れれば一意、取れなければ最新にする。"""
    config = pathlib.Path(
        os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude")
    slug = str(cwd).replace("/", "-")
    folder = config / "projects" / slug
    if not folder.is_dir():
        return None
    if session_id:
        exact = folder / f"{session_id}.jsonl"
        if exact.exists():
            return exact
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def read(path):
    """題と依頼者の発言の並びを取る。

    全行を json に通すと記録が大きいときに待たされる（実測: 1 セッションで数 MB）。
    欲しい 2 種類は行の中に型名が文字列で入っているので、先に文字列で絞る。"""
    title, prompts, first_ts = None, [], None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            # 開始時刻は記録の 1 件目から取る。ファイルの ctime は macOS では
            # inode の更新時刻で、追記のたびに動くので開始時刻にならない（実測）
            if first_ts is None and '"timestamp"' in line:
                try:
                    stamp = json.loads(line).get("timestamp")
                except json.JSONDecodeError:
                    stamp = None
                if stamp:
                    first_ts = dt.datetime.fromisoformat(
                        stamp.replace("Z", "+00:00")).astimezone()
            if '"ai-title"' not in line and '"last-prompt"' not in line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = o.get("type")
            if kind == "ai-title" and o.get("aiTitle"):
                title = o["aiTitle"]
            elif kind == "last-prompt" and o.get("lastPrompt"):
                text = o["lastPrompt"].strip()
                # 同じ発言が leafUuid 違いで何度も落ちる。連続の重複だけ畳む
                # （同じ言葉を後からもう一度言うことはあるので、全体の重複は消さない）
                if not prompts or prompts[-1] != text:
                    prompts.append(text)
    last_ts = dt.datetime.fromtimestamp(path.stat().st_mtime)
    return title, prompts, first_ts or last_ts, last_ts


def git(cwd, *args):
    try:
        r = subprocess.run(  # noqa: S603 — 引数はこのファイル内のリテラルだけ
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def one_line(text, limit):
    s = " ".join(text.split())
    return s[:limit] + "…" if len(s) > limit else s


def main(argv=None):
    p = argparse.ArgumentParser(
        description="このセッションが何のスレッドだったかの材料を出す")
    p.add_argument("--limit", type=int, default=20,
                   help="出す依頼の件数の上限（既定 20。超えたら間を省く）")
    p.add_argument("--full", action="store_true", help="依頼を全文・全件で出す")
    a = p.parse_args(argv)

    cwd = pathlib.Path.cwd()
    path = transcript_path(os.environ.get("CLAUDE_CODE_SESSION_ID"), cwd)
    if not path:
        sys.exit(f"このディレクトリ（{cwd}）のセッション記録が見つからない")

    title, prompts, started, touched = read(path)
    out = []
    w = out.append

    w(f"# このスレッド — {title or '（題が付いていない）'}")
    branch = git(cwd, "branch", "--show-current")
    dirty = [ln for ln in git(cwd, "status", "--porcelain").splitlines() if ln]
    w(f"  {cwd}" + (f" · ブランチ {branch}" if branch else ""))
    w(f"  開始 {started:%m-%d %H:%M} · 最後の動き {touched:%m-%d %H:%M}"
      f" · 依頼 {len(prompts)} 件")
    if dirty:
        w(f"  未コミット {len(dirty)} 件: "
          + ", ".join(ln[3:] for ln in dirty[:5]) + ("…" if len(dirty) > 5 else ""))
    w("")

    w(f"## 頼まれてきたこと（依頼者の言葉のまま・古い順） — {len(prompts)} 件")
    shown = prompts
    elided = 0
    if not a.full and len(prompts) > a.limit:
        head, tail = a.limit // 3, a.limit - a.limit // 3
        elided = len(prompts) - head - tail
        shown = prompts[:head] + [None] + prompts[-tail:]
    for item in shown:
        if item is None:
            w(f"  … 間の {elided} 件は省いた（--full で全部出る）")
            continue
        w("  - " + (item if a.full else one_line(item, 90)))
    w("")

    w("見ていないもの:")
    w("  - 私（AI）が何を返したか。ここに出るのは依頼者の発言だけ")
    w("  - 記録に残らないやり取り（別のセッション・チャット・口頭）")
    w("  - 題は序盤に付いたまま更新されない。古い可能性がある")
    print("\n".join(out))
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
