"""Claude Code の会話の記録（`<設定のフォルダ>/projects/<置き場>/<session id>.jsonl`）を読む共通部。
/what-am-i-doing と /reflect で共用。

記録の形と置き場の名前の作り方はハーネスの持ち物で、公開の約束が無い。ほかに読む口が無いので読むが、
読み方はここに 1 つだけ置く（docs/standards/machine-readable-values.md の「直さないと決めた物」）。
"""

import re

# Bash の中身から「区切りになる操作」を拾う。全部のコマンドを並べても追いつく助けにならないので、
# 後から見て節目と分かるものだけキーを付ける。キーは言語に依らない値で、表示の語は LANDMARK_LABELS から引く
LANDMARKS = (
    (re.compile(r"\bgit\s+commit\b"), "commit"),
    (re.compile(r"\bgit\s+push\b"), "push"),
    (re.compile(r"\bgit\s+rebase\b"), "rebase"),
    (re.compile(r"\bgh\s+pr\s+create\b"), "pr_create"),
    (re.compile(r"\bgh\s+(pr\s+(review|comment)|api\s+\S*/(comments|reviews))"), "review_comment"),
    (re.compile(r"\bgh\s+run\s+(watch|view)\b"), "ci"),
    (re.compile(r"tests?/run\.sh|\bpytest\b|\bnpm\s+test\b|\bunittest\b"), "test"),
)
LANDMARK_LABELS = {"commit": "コミット", "push": "push", "rebase": "rebase", "pr_create": "PR 作成",
                   "review_comment": "レビュー・コメント", "ci": "CI 確認", "test": "テスト実行"}


# user の行の promptSource（その発言の出どころ）。人が打った物と、人でない物（`claude -p` と SDK の sdk・
# ハーネスが差し込む system）を分ける。どちらにも無い値は、Claude Code が足した新しい種類として数えて出す——
# 黙ってどちらかに混ぜると、人の発言が落ちても数が減るだけで誰も気づかない（2026-10-19、
# suggestion_accepted〔出された提案の文を人が受けて送った物〕を知らずに 6 件落としていた）。
# 2026-10-19 に 5 つのアカウントの直近 3 日の記録で見た値は、この 5 つだけ
HUMAN_SOURCES = frozenset({"typed", "queued", "suggestion_accepted"})
OTHER_SOURCES = frozenset({"sdk", "system"})


def prompt_source(entry):
    """user の行の出どころのキー: "human"・"other"・"unknown"（知らない値）・None（promptSource が無い）。"""
    src = entry.get("promptSource")
    if src is None:
        return None
    if src in HUMAN_SOURCES:
        return "human"
    return "other" if src in OTHER_SOURCES else "unknown"


def unknown_sources_note(counts):
    """知らない promptSource の値の注記の文。counts は値ごとの件数で、空なら None。"""
    if not counts:
        return None
    return ("会話の記録に、知らない promptSource（発言の出どころ）の値があった: "
            + "・".join(f"{k} {n} 件" for k, n in sorted(counts.items()))
            + "。人の発言かどうか決められないので、人の発言に数えていない")


def landmarks(command):
    """コマンドの文字列に当たる区切りのキー（LANDMARKS の順）。文字列でなければ空。"""
    if not isinstance(command, str):
        return []
    return [key for rx, key in LANDMARKS if rx.search(command)]


def project_folder(config, cwd):
    """cwd の記録の置き場。session id が無いときと、同じ id の記録が複数あるときの絞り込みに使う。

    実物は英数字以外を全部 `-` に替えた名前（例: `/Users/me/.herdr/wt` → `-Users-me--herdr-wt`）。
    `/` だけを替えていたとき、`.herdr` を含む作業場で記録が見つからなかった（2026-10-19）。長いパスは名前が
    切り詰められて合わないので、session id が取れる所ではまず名前に依らずに探す（transcript_path）。"""
    return config / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def transcript_path(config, session_id, cwd):
    """記録の実体と、読む人に添える注記（無ければ None）。見つからなければ (None, 理由)。

    session id が取れれば、置き場の名前を自分で作らずに `projects/*/<id>.jsonl` を探す
    （graphloops の rules/research-loop.py の transcript_path と同じ形）。見つからなくても
    最新の記録へは倒さない——並んだ会話の別の記録を、この会話の物として見せてしまう。
    session id が取れないときだけ、cwd の置き場の最新を出し、そう出したと注記する。"""
    if session_id:
        hits = sorted(config.glob(f"projects/*/{session_id}.jsonl"))
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, f"{config}/projects/*/{session_id}.jsonl に記録が無い"
        # 同じ id が 2 つの置き場に在るのは、記録を写したときくらい。cwd の置き場の物なら選べる
        mine = [h for h in hits if h.parent == project_folder(config, cwd)]
        if len(mine) == 1:
            return mine[0], None
        return None, "session id の記録が {} 件あり、どれか決められない（{}）".format(
            len(hits), "、".join(str(h) for h in hits))
    folder = project_folder(config, cwd)
    files = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None, f"{folder} に記録が無い（CLAUDE_CODE_SESSION_ID も無い）"
    return files[-1], ("CLAUDE_CODE_SESSION_ID が無いので、この作業場の最新の記録を出した"
                       "（並んだ会話があれば、別の会話の記録かもしれない）")
