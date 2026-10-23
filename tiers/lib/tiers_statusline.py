"""Claude Code のステータスライン（statusline/statusline.sh）と、その印「⧖ バックグラウンド作業中 N 本」を herdr に作業中と見分けさせる
判定ルールを、入れて保つツール。tiers の点検（tiers_check.py）と違い、利用者が打って初めて設定を書く。

なぜツールが要るか（2026-10-19 に読んだ公式の文書）:
- プラグインは statusLine を入れられない。プラグインの settings.json で効くのは agent と subagentStatusLine だけ
  （https://code.claude.com/docs/en/plugins-reference の settings）。そこで、アカウントごとの settings.json の statusLine を、ここで書く。
- herdr の判定ルールの手元の上書き（~/.config/herdr/agent-detection/claude.toml）は、配られたルールに足すのでなく丸ごと置き換え、
  上書きが在る間は herdr が配り直したルールも効かない（https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/agents.mdx
  の「Local overrides can replace a remote or bundled manifest」「Local overrides always win」）。そこで上書きを手で写さず、herdr が取った
  配られたルール（~/.local/state/herdr/agent-detection/remote/claude.toml）の後ろに statusline/claude-rule.toml を足して作り、配られた
  ルールが替わるたびに作り直す（statusline.sh が、配られたルールか足す規則の方が新しいのを見て refresh を起動する）。
- statusLine のコマンドは、プラグインの版が上がっても替わらない場所を指す必要がある（版ごとにフォルダが替わる。キャッシュのフォルダの
  名前には commit の印の物も混ざるので、名前の並びで最新を選べない）。プラグインの SessionStart のフックが、会話を始めるたびに
  ${CLAUDE_PLUGIN_DATA}/current を今の版（${CLAUDE_PLUGIN_ROOT}）へのリンクに張り替え、statusLine はそのリンクの下を指す。リンクが無くても、
  settings.json の statusLine がそのリンクの下を指していれば、フックが作る（ほかのフォルダから写した settings.json で、setup を打たずに出るように）。

使い方:
    tiers-statusline setup [--config-dir フォルダ ...]   アカウントごとに statusLine を書き（前の settings.json は .bak で残す）、
                                                        herdr の上書きを作る（前の上書きが tiers の物でなければ .bak で残して置き換える）
    tiers-statusline refresh                            herdr の上書きを、配られたルールと足す規則から作り直す（tiers の物でない
                                                        上書きは触らない）

終了コード: 0 = 済んだ / 1 = できなかった物がある / 2 = 使い方が違う
macOS と Linux だけ（statusline.sh と bg-count.sh は bash・ps・jq で動く）。Python 3.11 以上（上書きが TOML として読めるかを tomllib で確かめる）。
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

MARKETPLACE = "raiki61"
PLUGIN_ID = f"tiers@{MARKETPLACE}"
DATA_NAME = f"tiers-{MARKETPLACE}"   # ${CLAUDE_PLUGIN_DATA} のフォルダの名前（id の英数字・_・- 以外を - にした物）
RULE_ID = "local_bg_wait_mark_working"
ROOT = pathlib.Path(__file__).resolve().parent.parent
RULE = ROOT / "statusline" / "claude-rule.toml"
MARK = "# tiers-statusline が作った herdr の判定ルールの上書き。"   # 上書きの 1 行目。これで始まる物だけを作り直す（statusline.sh も頭で見分ける）


def data_link(config_dir):
    """そのアカウントの、今の版の tiers を指すリンク（SessionStart のフックが張り替える）。"""
    return pathlib.Path(os.path.expanduser(config_dir)) / "plugins" / "data" / DATA_NAME / "current"


def command_for(config_dir):
    """そのアカウントの settings.json の statusLine.command に書く値。"""
    return str(data_link(config_dir) / "statusline" / "statusline.sh")


def herdr_paths(env):
    """(手元の上書き, herdr が取った配られたルール)。"""
    home = env.get("HOME") or os.path.expanduser("~")
    conf = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    state = env.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")
    return (pathlib.Path(conf, "herdr", "agent-detection", "claude.toml"),
            pathlib.Path(state, "herdr", "agent-detection", "remote", "claude.toml"))


def read_file(path):
    try:
        return pathlib.Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def write_file(path, text):
    """書きかけを読ませない（statusline.sh が 30 秒ごとに、ペインの数だけ並んで起動しうる）。path がリンク（dotfiles の管理など）なら、
    リンクを普通のファイルで置き換えず、リンクの先に書く。"""
    path = pathlib.Path(os.path.realpath(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def backup(path):
    """前の物を同じフォルダに .bak.<日時>-tiers で残す（持ち主の今の残し方 settings.json.bak.<日時>-<訳> に合わせる）。"""
    dest = path.with_name(f"{path.name}.bak.{time.strftime('%Y%m%d-%H%M%S')}-tiers")
    dest.write_bytes(path.read_bytes())
    return dest


def compose(base, rule):
    """配られたルール base の後ろに足す規則 rule を足した上書き。TOML として読めなければ ValueError（壊れた上書きを herdr は捨てて
    配られたルールに戻るので、印が作業中に見えなくなる）。読めるかを確かめられない Python（3.10 まで）でも ValueError（確かめずに書くと、
    壊れた上書きが次に herdr が配り直すまで残る）。"""
    try:
        import tomllib
    except ImportError:
        raise ValueError("上書きが TOML として読めるかを確かめるのに Python 3.11 以上が要る") from None
    # base は herdr が取って書いた物。書きかけを読んで行の切れ目で途切れると、TOML として読めたまま herdr の規則が欠ける
    try:
        got = tomllib.loads(base)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"herdr が配った Claude の判定ルールが TOML として読めない（{e}）") from e
    if got.get("id") != "claude" or not got.get("rules"):
        raise ValueError("herdr が配った Claude の判定ルールに id = \"claude\" か規則が無い（herdr が書いている途中かもしれない）")
    text = (f"{MARK}tiers の statusline/claude-rule.toml を、herdr が配った claude.toml の後ろに足した。手で直さない"
            "（herdr が配り直すと tiers-statusline refresh が作り直す）。\n" + base.rstrip("\n") + "\n\n" + rule.rstrip("\n") + "\n")
    try:
        got = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"作った上書きが TOML として読めない（{e}）") from e
    if not any(r.get("id") == RULE_ID for r in got.get("rules", []) if isinstance(r, dict)):
        raise ValueError(f"作った上書きに規則 {RULE_ID} が無い")
    return text


def refresh(env=None, force=False, run=None):
    """herdr の上書きを作り直す。(済んだか, 言うこと)。force なら tiers の物でない上書きも .bak で残して置き換える（setup から）。"""
    env = os.environ if env is None else env
    run = run or subprocess.run   # 既定を引数に書くと、読み込んだ時の subprocess.run に決まり、試験が差し替えられない
    over, remote = herdr_paths(env)
    base = read_file(remote)
    if base is None:
        return False, f"herdr が配った Claude の判定ルール（{remote}）が無い。herdr を起動するか herdr server update-agent-manifests を打ってから、もう一度打つ"
    cur = read_file(over)
    if cur is not None and not cur.startswith(MARK) and not force:
        return True, f"{over} は tiers が作った物でないので触らない（置き換えるなら tiers-statusline setup）"
    try:
        want = compose(base, RULE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        if cur is not None and cur.startswith(MARK):
            os.utime(over)   # statusline.sh が 30 秒ごとに起動して同じ失敗を繰り返さないよう、次に herdr が配り直すまで待たせる
        return False, str(e)
    if cur == want:
        os.utime(over)   # 配られたルールの方が新しいままだと、statusline.sh が 30 秒ごとに起動し続ける
        return True, f"{over} は今の配られたルールから作った物のまま"
    saved = backup(over) if cur is not None and not cur.startswith(MARK) else None
    write_file(over, want)
    # 動いている herdr に読み直させる。動いていなければ、次に起動したときに読む
    try:
        run(["herdr", "server", "reload-agent-manifests"], capture_output=True)
    except OSError:   # herdr が PATH に無い。上書きは書けたので、herdr を起動したときに読まれる
        pass
    return True, f"{over} を作り直した" + (f"（前の物は {saved}）" if saved else "")


def installed_root(config_dir):
    """そのアカウントに user の範囲で入った tiers の置き場。無ければ None。"""
    text = read_file(pathlib.Path(os.path.expanduser(config_dir), "plugins", "installed_plugins.json"))
    try:
        entries = json.loads(text).get("plugins", {}).get(PLUGIN_ID) if text else None
    except (ValueError, AttributeError):
        return None
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and e.get("scope") == "user" and isinstance(e.get("installPath"), str) and os.path.isdir(e["installPath"]):
            return e["installPath"]
    return None


def uses_it(config_dir):
    """そのアカウントの statusLine が、ここの statusline を指しているか。"""
    text = read_file(pathlib.Path(os.path.expanduser(config_dir), "settings.json"))
    try:
        line = json.loads(text).get("statusLine") if text else None
    except (ValueError, AttributeError):
        return False
    return isinstance(line, dict) and line.get("command") == command_for(config_dir)


def setup_one(config_dir):
    """(済んだか, 言うこと)。"""
    root = installed_root(config_dir)
    if root is None:
        return False, f"{config_dir}: {PLUGIN_ID} が user の範囲で入っていない。CLAUDE_CONFIG_DIR={config_dir} claude plugin install {PLUGIN_ID} を打ってから、もう一度打つ"
    link = data_link(config_dir)
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(link) and not os.path.islink(link):
        return False, f"{config_dir}: {link} がリンクでない（フォルダかファイル）。中を確かめて退けてから、もう一度打つ"
    if os.path.realpath(link) != os.path.realpath(root):
        tmp = link.with_name(f"current.{os.getpid()}.tmp")
        if os.path.lexists(tmp):
            os.unlink(tmp)
        os.symlink(root, tmp)
        os.replace(tmp, link)
    path = pathlib.Path(os.path.expanduser(config_dir), "settings.json")
    text = read_file(path)
    try:
        settings = json.loads(text) if text else {}
    except ValueError as e:
        return False, f"{path} が JSON として読めない（{e}）。直してから、もう一度打つ"
    want = {**(settings.get("statusLine") if isinstance(settings.get("statusLine"), dict) else {}),
            "type": "command", "command": command_for(config_dir)}
    want.setdefault("refreshInterval", 30)   # 裏の処理の数は会話が黙っている間にも替わる。印を消すのが遅れないように時計でも描き直す
    if settings.get("statusLine") == want:
        return True, f"{config_dir}: statusLine は前から tiers の statusline を指している"
    saved = backup(path) if text is not None else None
    write_file(path, json.dumps({**settings, "statusLine": want}, ensure_ascii=False, indent=2) + "\n")
    return True, f"{config_dir}: statusLine を {want['command']} にした" + (f"（前の物は {saved}）" if saved else "")


def main(argv=None, stdout=None, env=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="tiers-statusline", description="tiers の statusline と herdr の判定ルールの上書きを入れて保つ")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="アカウントごとに statusLine を書き、herdr の上書きを作る")
    s.add_argument("--config-dir", action="append", default=[], metavar="フォルダ",
                   help="アカウントの Claude Code の設定のフォルダ（繰り返して複数。省けば CLAUDE_CONFIG_DIR か ~/.claude）")
    sub.add_parser("refresh", help="herdr の上書きを作り直す（tiers の物でなければ触らない）")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    results = []
    if a.cmd == "setup":
        dirs = list(dict.fromkeys(a.config_dir)) or [env.get("CLAUDE_CONFIG_DIR") or "~/.claude"]
        results += [setup_one(d) for d in dirs]
    results.append(refresh(env, force=a.cmd == "setup"))
    for ok, said in results:
        # できなかった物は stderr にも出す（statusline.sh は裏で打つ refresh の stderr だけをエラーの記録に残す）
        print(said if ok else f"できなかった: {said}", file=stdout if ok else stderr)
    return 0 if all(ok for ok, _ in results) else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
