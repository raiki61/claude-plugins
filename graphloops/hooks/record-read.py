#!/usr/bin/env python3
"""読んだ事実を、読んだその瞬間に盤面の隣へ 1 行残す（PostToolUse:Read）。

**なぜフックなのか。** 読了の柵はこれまで、会話の記録（転写 JSONL）を engine が後から開いて
本文の痕跡を探していた。公式文書は転写を内部形式と明記しており、engine が自前で glob して
解析する形は版ごとに壊れうる。実際、形が変わった疑いを別扱いする分岐・辞書でない行の守り・
大きい結果の外出し（tool-results/）の見分けを、壊れるたびに足してきた。

**フックなら一次情報として取れる。** 公式文書（code.claude.com/docs/en/hooks、2026-09-21 取得）が
挙げる 2 点がそのまま効く: `tool_response` は "the full tool output (not truncated for hooks)" で、
フックは subagent の中でも発火して `agent_id` が載る。後から漁る必要も、外出しを見分ける必要も無い。

**文書を信じずに実物で測った**（2026-09-22、macOS）。この設定を `--settings` で渡した子の claude を
起こし、3 点を確かめた——**文書がそう書いていることは、ハーネスがそうすることの証拠にならない**:
  1. Read のたびに発火する（記録の tool_use_id が `toolu_01HsNpjr7UvQHHN9b6Y2V1Xa` で、
     こちらが作れる値ではない。path と sha も現物と一致）
  2. offset 付きの読みは `partial: true` で残る（全文の証拠にしない側へ倒れる）
  3. **subagent の中でも発火し、`agent_id` が載る**（Explore に読ませた回は
     `agent_id: a6562aad50ab27481`、親自身の読みは `agent_id: null`）
この 3 点目が、転写の走査では原理的に取れなかったもの——親の転写に subagent の読みは残らないので、
engine は「どこまで読みに行くか」を未決のまま抱えていた。

**書く先は盤面の隣で、回っている run が在るときだけ。** 最初は利用者ごとの置き場
（`$CLAUDE_CONFIG_DIR/graphloops/reads/<session>.jsonl`）へ session 単位で永久に書く形にしたが、
それは **graphloops を使っていない session の読み取り履歴まで、寿命を決めずに溜める**形だった。
参照した実装（spotify/portal-ai-plugins の shunt、Apache-2.0）のフックは**ディスクに 1 バイトも
書かず**、一時ファイルを使う所は `trap … EXIT` で必ず消し、README にも「何も残らない」と明記している。
盤面の隣に書けば寿命は run の寿命になり、保持期限も削除処理も上限も要らなくなる——**溜めないので、
消す仕掛けが要らない**。run が無ければ何も書かない。

**残す証拠は「その時のファイルの sha」と「部分読みか」。** 読んだ中身そのものを残さないのは、
文書の本文をこちらのディスクへ写すことになるため。engine は後から同じファイルの sha を取って
突き合わせるので、**読んだ後に文書が変わっていれば一致しない**（読み直しを求める側に倒れる）。

**射程は Read だけ。** cat / sed / head でも読めるが、bash のコマンド行からパスを取り出すのは
綴りの数だけ穴が開く（パイプ・リダイレクト・変数・別名）。取りこぼした読み方は engine 側が
転写の走査へ落として拾う——**この記録は「在れば強い」証拠であって、唯一の証拠ではない**。
"""
import hashlib
import json
import os
import pathlib
import sys
import time


def boards(cwd):
    """cwd の在るリポジトリで**いま回っている run** の盤面（0 個以上）。

    `git` は呼ばない——Read のたびに走るので、子プロセス 1 つぶんの遅さを毎回払わない。
    `.git` を上へ辿るだけで足りる（worktree の `.git` がファイルの配置は gitdir: を読む）。
    """
    try:
        here = pathlib.Path(cwd).resolve()
    except (OSError, ValueError):
        return []
    for d in (here, *here.parents):
        g = d / ".git"
        if not g.exists():
            continue
        if g.is_file():                         # linked worktree: `gitdir: <path>` の 1 行
            try:
                line = g.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return []
            if not line.startswith("gitdir:"):
                return []
            g = pathlib.Path(line.split(":", 1)[1].strip())
        out = []
        try:
            for cur in sorted((g / "graphloops").glob("*/current")):
                b = pathlib.Path(cur.read_text(encoding="utf-8").strip())
                if b.is_dir():
                    out.append(b)
        except OSError:
            return []
        return out
    return []


def main():
    try:
        d = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0                                  # 読めない入力で道具を止めない（記録は在れば強い証拠）
    if not isinstance(d, dict) or d.get("tool_name") != "Read":
        return 0
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    path = ti.get("file_path")
    if not path:
        return 0
    dirs = boards(d.get("cwd") or os.getcwd())
    if not dirs:
        return 0                                  # **回っている run が無い回は 1 バイトも書かない**
    try:
        real = os.path.realpath(path)
        raw = pathlib.Path(real).read_bytes()
    except OSError:
        return 0                                  # 読めたはずのものが読めない——記録しないだけ
    resp = d.get("tool_response")
    row = json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": d.get("session_id"),
        "agent_id": d.get("agent_id"),            # subagent の中なら誰が読んだかが入る
        "path": real,
        "file_sha": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        # **部分読みを「読んだ」と書かない。** offset / limit が付いた読みは文書の一部しか
        # 会話に入っていないので、全文の証拠にはならない。0 も指定として扱う（未指定と区別する）
        "partial": ti.get("offset") is not None or ti.get("limit") is not None,
        "resp_bytes": len(resp) if isinstance(resp, str) else None,
        "tool_use_id": d.get("tool_use_id"),      # ハーネスが振る。回す側には予測できない
    }, ensure_ascii=False)
    for b in dirs:
        try:
            with open(b / "reads.jsonl", "a", encoding="utf-8") as f:
                f.write(row + "\n")
        except OSError:
            pass                                  # 書けなくても道具は止めない
    return 0


if __name__ == "__main__":
    sys.exit(main())
