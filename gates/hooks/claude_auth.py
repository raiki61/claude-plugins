#!/usr/bin/env python3
"""別プロセスの claude を起こすときに、**認証だけ**を子の環境へ足す。起動そのものは呼ぶ側が持つ。

**この本文は複数のプラグインに写しで在る**。**正本はリポジトリ直下の `scripts/claude_auth.py`**で、
写しは `gates/hooks/` と `graphloops/scripts/`（2026-09-15 時点）。

実行時に跨いで読む道は在る——`convergence-loops` はリポジトリ全体が配られるので、キャッシュ越しに
1 本を共有できる（実測 2026-09-15: `~/.claude/plugins/cache/raiki61/convergence-loops/<版>/` に
`gates/ graphloops/ scripts/ …` が丸ごと在った）。**それを採っていない**のは、キャッシュから拾えるのが
「いちばん新しい版」だからで、gates の版と認証コードの版が黙ってずれる組み合わせが起こる。
認証は静かに壊れる場所（実測: 認証切れは終了コード 0 の 1 行で返る）なので、ここに版のずれを持ち込まない。

直すのは正本 1 か所、配るのは `python3 scripts/shared-copies.py --sync scripts/claude_auth.py`。
同一性は `tests/run.sh` の柵が見る——**どれか 1 つだけ直すと赤くなる**。

**なぜ要るか。** 子は対話の claude の認証を継がない。利用者の `claude` がシェル関数のラッパ
（Keychain から OAuth トークンを読んで `CLAUDE_CODE_OAUTH_TOKEN` に入れてから実体を起こす形）のとき、
子は実体を直に起こすのでラッパを通らず、ハーネスも子の環境にトークンを渡さない（実測 2026-09-15:
Bash から見える環境では `CLAUDE_CODE_OAUTH_TOKEN` も `CLAUDE_CONFIG_DIR` も空だった）。
**落ち方は静か**——実測 2026-09-15: 素で起こした `claude -p` は
『Failed to authenticate: OAuth session expired and could not be refreshed』の 1 行を
**標準出力に・終了コード 0 で**返した。rc では捕まらない。

**なぜトークンを argv に置かないか。** 起動の argv は呼ぶ側の文脈や記録（graphloops なら
`record.json`）に写るので、秘密がそこに残る。呼ぶ側の Bash に `$(security find-generic-password …)` を
書かせる形も採れない——auto mode の分類器が資格情報の実体化として止める（実測 2026-09-15）。
この層の中から呼ぶ分は止まらない。

**段**（上から順に、決まった時点で止める）:

1. 親の環境に認証が在る（`INHERITED`）→ 何も足さない。**利用者が選んだ経路を黙って別の口に差し替えない**
2. macOS の Keychain（サービス名は呼ぶ側の指定 → `CLAUDE_KEYCHAIN_SERVICE` → `CLAUDE_CONFIG_DIR` から導出）
3. 何も足さない——子自身の保存済み認証（`<CLAUDE_CONFIG_DIR>/.credentials.json`）に委ねる。
   **Keychain の無い環境ではここが本線**で、2 は空振りする。全 OS で効くのは
   「`CLAUDE_CONFIG_DIR` を必ず子へ明示する」ことの方

`auth_env` は採った段の名前も返す。呼ぶ側はそれを人の見える所（標準エラー・ログ）に出すこと
——**認証を足せたかどうかが見えないと、認証落ちが役の返答の不良と区別できない**。
段の名前にトークンそのものは出さない。
"""
import os
import pathlib
import subprocess
import sys

# 親の環境に在れば認証は足さない。子（claude）が読む経路——サブスクの OAuth・API キー・
# 企業のゲートウェイ・Bedrock / Vertex。**旗の 2 つは値も見る**（`=0` は「使わない」の意味で、
# 在るだけで認証が在ることにはならない）。
INHERITED = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
             "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
FLAGS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
OFF = ("", "0", "false", "False", "no")
TOKEN_PREFIX = "sk-ant-oat01-"


def config_dir(env):
    return env.get("CLAUDE_CONFIG_DIR") or str(pathlib.Path.home() / ".claude")


def keychain_service(cfg, env, explicit=None):
    """Keychain のサービス名。プロファイルごとに別項目なので `CLAUDE_CONFIG_DIR` の末尾から導く。

    呼ぶ側が自分の環境変数（gates の `COLDREAD_KEYCHAIN_SERVICE` 等）で上書きしたいことがあるので、
    explicit を先に見る。導出の規則は利用者のシェルラッパの命名慣行に合わせてある:
    `~/.claude` → `claude-code-oauth-default`、`~/.claude-p1` → `claude-code-oauth-p1`。
    """
    if explicit:
        return explicit
    if env.get("CLAUDE_KEYCHAIN_SERVICE"):
        return env["CLAUDE_KEYCHAIN_SERVICE"]
    base = os.path.basename(cfg.rstrip("/\\"))
    return "claude-code-oauth-" + ("default" if base == ".claude" else base.replace(".claude-", ""))


def read_keychain(service, runner=subprocess.run):
    """`(トークン, 段の名前)`。取れなければ `(None, 空振りの理由)`——**例外は投げない**。

    取れないことは異常ではない（mac 以外・項目が無い・利用者が別経路で認証している）。ここで落とすと、
    子の保存済み認証で普通に動く場まで起こせなくなる。
    """
    try:
        p = runner(["security", "find-generic-password", "-s", service, "-w"],
                   capture_output=True, encoding="utf-8", timeout=10)
    except Exception as e:  # security が無い・落ちた・時間切れ
        return None, "keychain-error(%s)" % type(e).__name__
    tok = (p.stdout or "").strip()
    if not tok:
        return None, "keychain-miss"
    if not tok.startswith(TOKEN_PREFIX):
        # 壊れた値を渡すと子は認証エラーで起動すらしない。渡さなければ保存済み認証で動く目が残る
        return None, "keychain-malformed"
    return tok, "keychain"


def inherited(env):
    """親の環境に在る認証の名前（無ければ None）。旗は値が「使わない」でないことまで見る。"""
    for k in INHERITED:
        v = env.get(k)
        if v and not (k in FLAGS and v in OFF):
            return k
    return None


def auth_env(env, platform=sys.platform, runner=subprocess.run, service=None):
    """子に渡す環境と、採った段の名前を返す。渡された env は壊さない（写しを返す）。"""
    out = dict(env)
    cfg = config_dir(out)
    out["CLAUDE_CONFIG_DIR"] = cfg  # 全 OS 共通の段。mac 以外はこれだけが効く
    got = inherited(out)
    if got:
        return out, "inherited(%s)" % got
    if platform != "darwin":
        return out, "none"
    svc = keychain_service(cfg, out, service)
    tok, note = read_keychain(svc, runner)
    if tok:
        out["CLAUDE_CODE_OAUTH_TOKEN"] = tok
        return out, "keychain(%s)" % svc
    return out, "%s(%s)" % (note, svc)


def added(note):
    """認証を足せた段か。足せていない回だけ、呼ぶ側が静かな落ち方の注意を出せるようにする。"""
    return note.startswith(("inherited(", "keychain("))


QUIET_FAILURE_NOTE = ("認証は足していない——子自身の保存済み認証で起きる。認証切れは"
                      "『Failed to authenticate…』の 1 行が**終了コード 0 のまま**返る形で出るので、"
                      "返答が短い非 JSON ならまずここを疑う")
