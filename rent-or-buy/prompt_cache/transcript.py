"""会話の記録（Claude Code の transcript の JSONL）から、翻訳に渡す事実を出す。

この形は 2026-10-24 の Claude Code 2.1.310 の記録で確かめた物で、公式の文書に書かれた形ではない。
読めない行は数えて飛ばし、必要な値が 1 つも読めなければ TranscriptError。
"""
import json
from typing import Optional


class TranscriptError(Exception):
    """記録を読めない。"""


def _context(usage: dict) -> int:
    return sum(int(usage.get(k) or 0) for k in
               ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))


def _cache(usage: dict) -> tuple:
    """(キャッシュに書いた量, 読んだ量)。書いた量にキャッシュに無い入力を含め、和が文脈になるようにする（compact の後の最初の要求が
    キャッシュに当たらなかったときに、compact の後の文脈を小さく見積もらない）。"""
    read = int(usage.get("cache_read_input_tokens") or 0)
    return _context(usage) - read, read


def read(path) -> dict:
    """次の鍵を持つ表を返す（読めた物だけ）。

    model・context_tokens（最後の応答）、last_request_at（会話の本体の最後の要求の時刻）、after_write_tokens・after_read_tokens
    （最後の compact の後の最初の応答がキャッシュに書いた量と読んだ量。compact が無いか、その後に応答がまだ無ければ出さない）、
    contexts_after_compact（最後の compact の後の応答ごとの文脈。compact が無ければ全部）、skipped_lines。
    """
    model: Optional[str] = None
    last_request_at: Optional[str] = None
    compacted = False
    responses: dict = {}  # message.id → (model, 文脈, (書いた量, 読んだ量))。同じ id の行は内容のブロックごとで、最後の行を採る
    order: list = []      # compact の後に出た id の順
    skipped = 0
    try:
        # バイトのまま行に割る（bytes.splitlines は \n と \r だけで割る。str.splitlines は JSON の文字列の中の U+2028 などでも割る）。
        # 書き込み中の記録は最後で多バイトの字が切れていることがあるので、字への直しは行ごとにして、その行だけ飛ばす
        with open(path, "rb") as f:
            lines = f.read().splitlines()
    except OSError as e:
        raise TranscriptError("cannot open the transcript: %s" % e)
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8"))
            kind = row.get("type")
            if kind == "api-request":
                if row.get("querySource") == "repl_main_thread" and row.get("timestamp"):
                    last_request_at = row["timestamp"]
            elif kind == "system" and row.get("subtype") == "compact_boundary":
                compacted, responses, order = True, {}, []
            elif kind == "assistant" and not row.get("isSidechain"):
                msg = row["message"]
                ctx = _context(msg["usage"])
                if not isinstance(msg["model"], str):
                    raise TypeError("model is not a string")
                if ctx > 0 and not msg["model"].startswith("<"):  # <synthetic> は実の応答ではない
                    if msg["id"] not in responses:
                        order.append(msg["id"])
                    responses[msg["id"]] = (msg["model"], ctx, _cache(msg["usage"]))
        except (ValueError, KeyError, TypeError, AttributeError):
            skipped += 1  # 形の違う行は飛ばして数える。出力の transcript.skipped_lines に出る
    out: dict = {"skipped_lines": skipped}
    if order:
        model, ctx, _ = responses[order[-1]]
        out.update(model=model, context_tokens=ctx)
        if compacted:
            out["after_write_tokens"], out["after_read_tokens"] = responses[order[0]][2]
    # compact の直後に応答がまだ無いときも、直前の応答の値は捨てている（compact の前の文脈は古い）
    out["contexts_after_compact"] = [responses[i][1] for i in order]
    if last_request_at:
        out["last_request_at"] = last_request_at
    if not compacted and not ({"model", "last_request_at"} & set(out)):
        raise TranscriptError("no response, request or compact mark could be read from the transcript (skipped lines: %d)" % skipped)
    return out
