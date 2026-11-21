"""/my-turn の記録（掘った木の写し）の版と書き方。my-turn-prep.py の --save-record と my-turn-headless.py が共用する。

記録は Workflow（my-turn-dig.js）の戻り値そのもの。Workflow の出力のファイル（終わりの知らせの <output-file>）は
{summary, agentCount, logs, result: <戻り値>, ...} の JSON なので、result を取り出して書く。
設計は attention/docs/my-turn-workflow-design.md の 7。
"""

import json

import atomic  # 同じ lib/ にある。書きかけを残さない書き方

# my-turn-dig.js の RECORD_VERSION と同じ値にそろえる。違う版の記録は使い回さない（my-turn-prep.py の --prior）
# 3: ノードに worth・findingKind・locations・cost・finePremise を足し、記録に purpose と指摘の台帳（ledger）を足した
RECORD_VERSION = 3
# 前の版で、記録を書いた段（W11）が足していた項目。今の戻り値には無いが、古い材料から写したときに残さない
DROP_KEYS = ("recordPath", "recordWritten", "recordError", "recordModel")


class RecordError(Exception):
    pass


def unwrap(val):
    """出力のファイルの包み（result を持つ物）を外して、戻り値を返す。result が JSON の文字列でも読む。"""
    if isinstance(val, dict) and "result" in val and "version" not in val and "stopped" not in val:
        val = val["result"]
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except ValueError:
                raise RecordError("出力のファイルの result が JSON でありません")
    return val


def check(val):
    """記録として書ける形か。書けなければ訳を RecordError で投げる。"""
    if not isinstance(val, dict):
        raise RecordError("Workflow の戻り値が JSON のオブジェクトでありません")
    if "stopped" in val:
        raise RecordError("Workflow が止まった回（stopped: %s）なので、記録は書きません" % val.get("stopped"))
    if val.get("version") != RECORD_VERSION:
        raise RecordError("記録の版が %r で、今の版（%d）と違います" % (val.get("version"), RECORD_VERSION))
    return {k: v for k, v in val.items() if k not in DROP_KEYS}


def load_result(path):
    """Workflow の出力のファイル（か、戻り値をそのまま書いたファイル）から記録を取り出す。"""
    try:
        with open(path, encoding="utf-8") as f:
            val = json.load(f)
    except (OSError, ValueError):
        raise RecordError("%s を読めません（無いか、JSON でない）" % path)
    return check(unwrap(val))


def write(path, rec):
    """記録を書く。同じフォルダの一時のファイルに書いてから置き換え、途中で切れた記録を残さない（lib/atomic.py）。"""
    try:
        atomic.write_text(path, json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
    except OSError as e:
        raise RecordError("記録 %s を書けません: %s" % (path, e.strerror or e))
