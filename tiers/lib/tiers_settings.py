"""アカウントごとの Claude Code の settings.json に、tiers の点検（段 2）が待つ設定を書くツール。tiers の点検（tiers_check.py）と違い、
利用者が打って初めて書く。

書く物は NEEDS の 2 つ。

1. feedbackDrafts = "off"。Claude が SendFeedback のツールでフィードバックの下書きをためた会話は、/exit の前に送るか
捨てるかの確認を出して止まり、外から閉じられない（2026-10-23、works-dispatch が自分の番でなくなった PR の会話を閉じられなかった）。
"off" にすると Claude Code が SendFeedback のツールを外し、下書きがたまらない。2026-10-23 に読んだ公式の文書:
- https://code.claude.com/docs/en/tools-reference の「SendFeedback tool behavior」: 「Set Claude-drafted feedback to off in /config, which
  writes the feedbackDrafts setting, or set CLAUDE_CODE_SEND_FEEDBACK=0 for one session.」。環境変数は 1 つの会話にしか効かないので、
  設定のファイルに書く。管理者の managed settings に書いた値は、ここで書いた値より先に効く
- https://code.claude.com/docs/en/settings-reference の feedbackDrafts: 範囲は User か managed（なので、アカウントの設定のフォルダの
  settings.json に書く）。値は "notify"・"quiet"・"off"
採らない方: DISABLE_FEEDBACK_COMMAND=1 は人が打つ /feedback も止め、CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 は自動更新なども止める
（https://code.claude.com/docs/en/env-vars ）。
2. permissions.deny に "AskUserQuestion"（選択肢の画面で問うツール）。Claude がこのツールで問うと、その会話は窓を開いてキーを押すまで
   進まず、ほかの会話からは答えられない（2026-10-23、guided-resolver の issue #1895 で、works-dispatch が開いた会話が止まった）。
   並びの末尾に足し、ほかの項目は消さない。2026-10-23 に読んだ公式の文書:
   - https://code.claude.com/docs/en/tools-reference : ツールの名前は権限の決まり（permission rules）に書く字そのもので、
     AskUserQuestion のように決まりの書き方の表に無いツールは、括弧を付けない名前だけを受ける。問いは答えるまで開いたまま
   - https://code.claude.com/docs/en/settings の「Lists merge instead of overriding」: permissions の並びは、設定のファイルごとに
     置き換えず合わせる（ほかの場所の deny を消さない）
   採らない方: askUserQuestionTimeout（答えないまま置いた問いを閉じる設定）は、裏の会話（--bg）では時計が動かず、問いは答えるまで残る
   （同じ tools-reference の「Question auto-continue timeout」）。

使い方:
    tiers-settings setup [--config-dir フォルダ ...]   アカウントごとに settings.json に書く（前の settings.json は .bak で残す）。
                                                      省けば CLAUDE_CONFIG_DIR か ~/.claude

終了コード: 0 = 済んだ / 1 = できなかった物がある / 2 = 使い方が違う
"""

import argparse
import collections
import json
import os
import pathlib
import sys

import tiers_statusline as statusline

KEY = "feedbackDrafts"
VALUE = "off"
DENIED = "AskUserQuestion"

# 設定の状態: 足りている / 足りない（setup が書ける） / 形が違う（setup は書かず、人が直す）
OK, MISSING, BROKEN = "ok", "missing", "broken"


def _feedback_state(settings):
    value = settings.get(KEY)
    if value == VALUE:
        return OK, f"{KEY} が {VALUE}"
    return MISSING, f"{KEY} が" + ("無い" if value is None else f" {json.dumps(value, ensure_ascii=False)}")


def _feedback_add(settings):
    return {**settings, KEY: VALUE}


def _deny_state(settings):
    perms = settings.get("permissions", {})
    if not isinstance(perms, dict):
        return BROKEN, "permissions が {} でない"
    deny = perms.get("deny", [])
    if not isinstance(deny, list):
        return BROKEN, "permissions.deny が並び（[]）でない"
    if DENIED in deny:
        return OK, f"permissions.deny に {DENIED} が在る"
    return MISSING, f"permissions.deny に {DENIED} が無い"


def _deny_add(settings):
    perms = dict(settings.get("permissions", {}))
    return {**settings, "permissions": {**perms, "deny": list(perms.get("deny", [])) + [DENIED]}}


# name は tiers の点検の項目の名前、why は無いと何が起きるか、manual は手で書くときの 1 行、done は setup が書いたときの言葉
Need = collections.namedtuple("Need", "name state add why manual done")
NEEDS = (
    Need("フィードバックの下書き", _feedback_state, _feedback_add,
         "Claude がフィードバックの下書きをためると、/exit が送るか捨てるかの確認で止まり、外から会話を閉じられない",
         f'一番外の {{}} に "{KEY}": "{VALUE}" を足す（か、そのアカウントの Claude Code で /config を開き、Claude-drafted feedback を off にする）',
         f"{KEY} を {VALUE} にした"),
    Need("選択肢の画面で問うツール", _deny_state, _deny_add,
         "Claude が選択肢の画面で問うと、窓を開いてキーを押すまで会話が進まず、ほかの会話からは答えられない",
         f'"permissions" の "deny" の並びに "{DENIED}" を足す（無ければ一番外の {{}} に "permissions": {{"deny": ["{DENIED}"]}} を足す）',
         f"permissions.deny に {DENIED} を足した"),
)


def setup_one(config_dir):
    """(済んだか, 言うこと)。形が違う項目が 1 つでも有れば、何も書かない。"""
    root = pathlib.Path(os.path.expanduser(config_dir))
    if not root.is_dir():   # 打ち間違いで、使われないフォルダを作らない
        return False, f"{config_dir}: フォルダが無い（アカウントの設定のフォルダ〔CLAUDE_CONFIG_DIR に入れる物〕を渡す）"
    path = root / "settings.json"
    text = statusline.read_file(path)
    try:
        settings = json.loads(text) if text and text.strip() else {}
    except ValueError as e:
        return False, f"{path} が JSON として読めない（{e}）。直してから、もう一度打つ"
    if not isinstance(settings, dict):
        return False, f"{path} の一番外が {{}} でない。直してから、もう一度打つ"
    states = [(need, *need.state(settings)) for need in NEEDS]
    broken = [said for _, state, said in states if state == BROKEN]
    if broken:
        return False, f"{path} の{'・'.join(broken)}。直してから、もう一度打つ（何も書いていない）"
    todo = [need for need, state, _ in states if state == MISSING]
    if not todo:
        return True, f"{config_dir}: 前からそろっている（{'・'.join(said for _, _, said in states)}）"
    for need in todo:
        settings = need.add(settings)
    saved = statusline.backup(path) if text is not None else None
    statusline.write_file(path, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    return True, (f"{config_dir}: {'・'.join(need.done for need in todo)}（次に起動する会話から効く）"
                  + (f"（前の物は {saved}）" if saved else ""))


def main(argv=None, stdout=None, env=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="tiers-settings", description="アカウントの settings.json に、tiers の点検が待つ設定を書く")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help=f"アカウントごとに settings.json の {KEY} を {VALUE} にし、permissions.deny に {DENIED} を足す")
    s.add_argument("--config-dir", action="append", default=[], metavar="フォルダ",
                   help="アカウントの Claude Code の設定のフォルダ（繰り返して複数。省けば CLAUDE_CONFIG_DIR か ~/.claude）")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    dirs = list(dict.fromkeys(a.config_dir)) or [env.get("CLAUDE_CONFIG_DIR") or "~/.claude"]
    results = [setup_one(d) for d in dirs]
    for ok, said in results:
        print(said if ok else f"できなかった: {said}", file=stdout if ok else stderr)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
