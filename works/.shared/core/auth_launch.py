#!/usr/bin/env python3
"""works の殻が Claude Code の認証を拾い、Archon を起こす起こし役（標準ライブラリだけ・3.9）。

順（設計 works/docs/specs/2026-09-29-launch-core-design.md 2.6『順の形』）:
1. 前の段: WORKS_KEYCHAIN_ITEM を名指していれば、その項目を写しの read_keychain で読む。取れなければ次へ進まず止まる
2. 真ん中: 本流 claude_auth.py の写しの auth_env を丸ごと呼ぶ（受け継いだ認証 → CLAUDE_KEYCHAIN_SERVICE か設定の置き場から
   導いた項目）。本流の部品を並べ直さない——本流の順が変われば、写しの同期でそのまま従う
3. 後ろの段: 真ん中が足せなかった時だけ、macOS で Claude Code 自身の keychain の項目を読む

keychain は利用者の HOME で読む（security はログイン keychain を $HOME 基準で探す）。値は標準出力・引数に出さない。

  auth_launch.py check --user-home <path> --user-config <path か空> [--for <殻の名>]
      値を読んで捨て、出どころの名だけを標準出力に 1 行。無ければ標準エラーに案内を 1 行出して 2
  auth_launch.py exec --user-home <path> --user-config <path か空> -- <実行ファイル> <引数…>
      同じ順で子の環境を組み、今のプロセスを実行ファイルに置き換える（WORKS_DEV_NO_AUTH=1 なら読まずに置き換える）
  auth_launch.py howto
      認証が無い時の案内の 1 行（殻が自分の言葉で止まる時に使う）
"""
import sys

sys.dont_write_bytecode = True   # python3 -I は PYTHONDONTWRITEBYTECODE を見ないので、pack に __pycache__ を作らない

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402
import subprocess  # noqa: E402
import unicodedata  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # -I はスクリプトのフォルダを sys.path に入れない
import claude_auth  # noqa: E402

HOWTO = ("認証が無い。keychain にトークンの項目が既に在るなら、その項目名を WORKS_KEYCHAIN_ITEM か CLAUDE_KEYCHAIN_SERVICE に"
         "設定する（どちらも無ければ設定の置き場から導く claude-code-oauth-<名> を見る）。無ければ claude にログインするか、"
         "claude setup-token で作ったトークンを CLAUDE_CODE_OAUTH_TOKEN に置く")

# 名指しで決めた時に子から外す名。Claude Code は CLAUDE_CODE_OAUTH_TOKEN より上の資格を先に使う
# （code.claude.com/docs/en/authentication の Authentication precedence）。写しの INHERITED に無い FOUNDRY の旗もここで外す
ABOVE_TOKEN = tuple(claude_auth.INHERITED) + ("CLAUDE_CODE_USE_FOUNDRY",)


def user_runner(user_home):
    """security を利用者の HOME で起こす runner（写しの read_keychain に渡す）"""
    def run(args, **kw):
        return subprocess.run(args, env={**os.environ, "HOME": user_home}, **kw)
    return run


def claude_code_items(user_config):
    """Claude Code 自身が keychain に認証を置く項目の名の候補（先に試す物から）。CLAUDE_CONFIG_DIR を設定した Claude Code は
    `Claude Code-credentials-<その値（NFC）の sha256 の頭 8 桁>` に置き、無ければ `Claude Code-credentials`"""
    items = []
    if user_config:
        digest = hashlib.sha256(unicodedata.normalize("NFC", user_config).encode("utf-8")).hexdigest()[:8]
        items.append("Claude Code-credentials-" + digest)
    items.append("Claude Code-credentials")
    return items


def login_json_runner(runner):
    """Claude Code の項目の値は JSON（claudeAiOauth.accessToken）かトークンそのもの。JSON ならトークンだけに替えて返す runner
    （時間切れ・例外・sk-ant-oat01- の検査は写しの read_keychain に任せる）"""
    def run(args, **kw):
        p = runner(args, **kw)
        raw = (p.stdout or "").strip()
        try:
            tok = ((json.loads(raw) or {}).get("claudeAiOauth") or {}).get("accessToken") or ""
        except (ValueError, AttributeError):
            return p
        return subprocess.CompletedProcess(args, getattr(p, "returncode", 0), stdout=tok if isinstance(tok, str) else "")
    return run


def resolve(env, user_home, user_config, platform=sys.platform, runner=None):
    """(子に足す認証の変数, 出どころの名, 止まる理由)。取れた時は止まる理由が None、取れない時は変数が None"""
    runner = runner or user_runner(user_home)
    named = env.get("WORKS_KEYCHAIN_ITEM")
    if named:
        tok, note = claude_auth.read_keychain(named, runner)
        if not tok:
            return None, "keychain の項目 " + named, "keychain の項目 %s を読めない: %s" % (named, note)
        return {"CLAUDE_CODE_OAUTH_TOKEN": tok}, "keychain の項目 %s（WORKS_KEYCHAIN_ITEM）" % named, None
    menv = dict(env, HOME=user_home, CLAUDE_CONFIG_DIR=user_config or str(pathlib.Path(user_home) / ".claude"))
    out, note = claude_auth.auth_env(menv, platform=platform, runner=runner)
    if claude_auth.added(note):
        got = {k: out[k] for k in claude_auth.INHERITED if out.get(k)}
        name = claude_auth.inherited(env)
        if name:
            return got, name, None
        return got, "keychain の項目 %s（CLAUDE_KEYCHAIN_SERVICE か設定の置き場から導いた名）" % note[len("keychain("):-1], None
    if platform == "darwin":
        for service in claude_code_items(user_config):
            tok, _ = claude_auth.read_keychain(service, login_json_runner(runner))
            if tok:
                return {"CLAUDE_CODE_OAUTH_TOKEN": tok}, "Claude Code の keychain の項目 " + service, None
    return None, None, "%s、Claude Code の keychain の項目 %s にも無い" % (note, " ".join(claude_code_items(user_config)))


def child_env(env, got, named):
    """子の環境: 受けた環境（隔離した HOME・CLAUDE_CONFIG_DIR のまま）に認証の変数だけを足す。名指しで決めた時は、
    それより上に効く資格を外す（外さないと名指しが効かない）"""
    out = {k: v for k, v in env.items() if not (named and k in ABOVE_TOKEN)}
    out.update(got)
    return out


def main(argv):
    ap = argparse.ArgumentParser(prog="auth_launch.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("howto")
    for cmd in ("check", "exec"):
        p = sub.add_parser(cmd)
        p.add_argument("--user-home", required=True)
        p.add_argument("--user-config", default="")
        p.add_argument("--for", dest="caller", default="auth_launch.py")
        if cmd == "exec":
            p.add_argument("argv", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    if a.cmd == "howto":
        print(HOWTO)
        return 0
    if a.cmd == "exec":
        target = a.argv[1:] if a.argv[:1] == ["--"] else a.argv
        if not target:
            ap.error("exec には -- の後に実行ファイルが要る")
        if os.environ.get("WORKS_DEV_NO_AUTH") == "1":
            os.execve(target[0], target, dict(os.environ))
    got, name, why = resolve(os.environ, a.user_home, a.user_config)
    if got is None:
        print("%s: %s（%s）" % (a.caller, HOWTO, why), file=sys.stderr)
        return 2
    if a.cmd == "check":
        print(name)
        return 0
    os.execve(target[0], target, child_env(os.environ, got, bool(os.environ.get("WORKS_KEYCHAIN_ITEM"))))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
