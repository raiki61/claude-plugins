"""searchgate・waitgate・destgate の殻が共有する部品: 標準入出力を UTF-8 にする・隣の coldread-gate.py を読み込む口・
止めた記録を書いて拒む口・検査に失敗したら拒む包み。

前は 3 本がそれぞれ同じ物を書いていた。止めた記録の置き場のフォルダは coldread の log_line が作る。
"""
import importlib.util
import json
import os
import sys

# 各殻は入力を読む前にこの部品を読み込むので、ここで直せば 3 本とも読む前に UTF-8 になる
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_coldread = None


def load_coldread():
    """止めた記録の置き場・記録の書き方・deny の出し方と解析部は coldread と同じ 1 本を使う。1 回のフックで 1 度だけ読む。"""
    global _coldread
    if _coldread is None:
        spec = importlib.util.spec_from_file_location(
            "coldread_gate", os.path.join(os.path.dirname(os.path.abspath(__file__)), "coldread-gate.py"))
        cr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cr)
        _coldread = cr
    return _coldread


def refuse(cr, gate, entry, reason):
    """止めた記録（<設定の置き場>/<gate>/denies.log）に entry を 1 行書き、reason で拒む。"""
    cr.log_line(os.path.join(cr.CONFIG_DIR, gate, "denies.log"), entry)
    cr.deny(reason)


def run(main, failed, deny=None):
    """main を回し、検査できないもの(例外)を黙って通さず止める(coldread と同じ倒し方)。failed は訳(例外の文の頭 150 字)から
    拒む理由の文を作る。deny を渡せばそれで拒み、無ければ PreToolUse の deny の JSON を出す。"""
    try:
        main()
    except Exception as exc:
        reason = failed(str(exc)[:150])
        try:
            (deny or _print_deny)(reason)
        except Exception:
            # 渡した deny 自体が落ちても(coldread-gate.py を読めないなど)、例外のまま終えると Claude Code は止めずに通すので、
            # 自前の deny で止める
            _print_deny(reason)


def _print_deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))
