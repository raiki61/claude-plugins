"""searchgate・waitgate・destgate の殻が共有する部品: 隣の coldread-gate.py を読み込む口と、検査に失敗したら拒む包み。

前は 3 本がそれぞれ同じ物を書いていた。止めた記録の置き場のフォルダは coldread の log_line が作る。
"""
import importlib.util
import json
import os


def load_coldread():
    """止めた記録の置き場・記録の書き方・deny の出し方と解析部は coldread と同じ 1 本を使う。"""
    spec = importlib.util.spec_from_file_location(
        "coldread_gate", os.path.join(os.path.dirname(os.path.abspath(__file__)), "coldread-gate.py"))
    cr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cr)
    return cr


def run(main, failed, deny=None):
    """main を回し、検査できないもの(例外)を黙って通さず止める(coldread と同じ倒し方)。failed は訳(例外の文の頭 150 字)から
    拒む理由の文を作る。deny を渡せばそれで拒み、無ければ PreToolUse の deny の JSON を出す。"""
    try:
        main()
    except Exception as exc:
        reason = failed(str(exc)[:150])
        if deny is not None:
            deny(reason)
            return
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}, ensure_ascii=False))
