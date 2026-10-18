#!/usr/bin/env python3
"""coldread ゲートの試験で、読み役の代役(COLDREAD_READER_CMD)が返す答えを組む。

ゲートは読み役を claude -p --output-format json --json-schema で起動し、答えの structured_output を読む
(docs/standards/machine-readable-values.md の決まり 1)。代役も同じ形を標準出力に出す。標準入力は読まない
(依頼文を見る代役は、自分で読んでからこれを呼ぶ)。

使い方:
  coldread-reply.py [KIND[/CAUSE][+carried]=TEXT ...]   指摘の答え(引数なしは指摘ゼロ)
  coldread-reply.py --verdicts [N=old|new|still|fixed ...]  比べる係(OLD/NEW)・問い直す係(STILL/FIXED)の答え
  coldread-reply.py --error MESSAGE                      is_error の答え(認証切れの形)
KIND は stuck・echo・question・guess・redundant、CAUSE は word・referent・flow。
"""
import json
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def finding(arg):
    head, sep, text = arg.partition("=")
    if not sep:
        sys.exit("coldread-reply: KIND=TEXT の形でない: %r" % arg)
    head, carried = (head[:-len("+carried")], True) if head.endswith("+carried") else (head, False)
    kind, _, cause = head.partition("/")
    item = {"kind": kind, "text": text}
    if cause:
        item["cause"] = cause
    if carried:
        item["carried"] = True
    return item


def main(args):
    if args[:1] == ["--error"]:
        reply = {"type": "result", "subtype": "success", "is_error": True, "result": " ".join(args[1:])}
    else:
        if args[:1] == ["--verdicts"]:
            pairs = [a.partition("=") for a in args[1:]]
            out = {"verdicts": [{"n": int(n), "verdict": v} for n, _, v in pairs]}
        else:
            out = {"findings": [finding(a) for a in args]}
        reply = {"type": "result", "subtype": "success", "is_error": False,
                 "result": json.dumps(out, ensure_ascii=False), "structured_output": out}
    # UTF-8 の bytes で書く(Windows の stdout の code page に依らせない。ゲートは UTF-8 strict で読む)
    sys.stdout.buffer.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")


if __name__ == "__main__":
    main(sys.argv[1:])
