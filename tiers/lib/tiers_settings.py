"""アカウントごとの Claude Code の settings.json に、tiers の点検（段 2）が待つ設定を書くツール。tiers の点検（tiers_check.py）と違い、
利用者が打って初めて書く。

書く物は feedbackDrafts = "off" の 1 つ。Claude が SendFeedback のツールでフィードバックの下書きをためた会話は、/exit の前に送るか
捨てるかの確認を出して止まり、外から閉じられない（2026-10-23、works-dispatch が自分の番でなくなった PR の会話を閉じられなかった）。
"off" にすると Claude Code が SendFeedback のツールを外し、下書きがたまらない。2026-10-23 に読んだ公式の文書:
- https://code.claude.com/docs/en/tools-reference の「SendFeedback tool behavior」: 「Set Claude-drafted feedback to off in /config, which
  writes the feedbackDrafts setting, or set CLAUDE_CODE_SEND_FEEDBACK=0 for one session.」。環境変数は 1 つの会話にしか効かないので、
  設定のファイルに書く。管理者の managed settings に書いた値は、ここで書いた値より先に効く
- https://code.claude.com/docs/en/settings-reference の feedbackDrafts: 範囲は User か managed（なので、アカウントの設定のフォルダの
  settings.json に書く）。値は "notify"・"quiet"・"off"
採らない方: DISABLE_FEEDBACK_COMMAND=1 は人が打つ /feedback も止め、CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 は自動更新なども止める
（https://code.claude.com/docs/en/env-vars ）。

使い方:
    tiers-settings setup [--config-dir フォルダ ...]   アカウントごとに settings.json に書く（前の settings.json は .bak で残す）。
                                                      省けば CLAUDE_CONFIG_DIR か ~/.claude

終了コード: 0 = 済んだ / 1 = できなかった物がある / 2 = 使い方が違う
"""

import argparse
import json
import os
import pathlib
import sys

import tiers_statusline as statusline

KEY = "feedbackDrafts"
VALUE = "off"


def setup_one(config_dir):
    """(済んだか, 言うこと)。"""
    root = pathlib.Path(os.path.expanduser(config_dir))
    if not root.is_dir():   # 打ち間違いで、使われないフォルダを作らない
        return False, f"{config_dir}: フォルダが無い（アカウントの設定のフォルダ〔CLAUDE_CONFIG_DIR に入れる物〕を渡す）"
    path = root / "settings.json"
    text = statusline.read_file(path)
    try:
        settings = json.loads(text) if text else {}
    except ValueError as e:
        return False, f"{path} が JSON として読めない（{e}）。直してから、もう一度打つ"
    if not isinstance(settings, dict):
        return False, f"{path} の一番外が {{}} でない。直してから、もう一度打つ"
    if settings.get(KEY) == VALUE:
        return True, f"{config_dir}: {KEY} は前から {VALUE}"
    saved = statusline.backup(path) if text is not None else None
    statusline.write_file(path, json.dumps({**settings, KEY: VALUE}, ensure_ascii=False, indent=2) + "\n")
    return True, f"{config_dir}: {KEY} を {VALUE} にした（次に起動する会話から効く）" + (f"（前の物は {saved}）" if saved else "")


def main(argv=None, stdout=None, env=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="tiers-settings", description="アカウントの settings.json に、tiers の点検が待つ設定を書く")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help=f"アカウントごとに settings.json の {KEY} を {VALUE} にする")
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
