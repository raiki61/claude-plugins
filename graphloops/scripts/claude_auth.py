#!/usr/bin/env python3
"""別プロセスの claude を起動するときに、**認証だけ**を子の環境へ足す。起動そのものは呼ぶ側が持つ。

**この本文は複数のプラグインに写しで在る**。**正本はリポジトリ直下の `scripts/claude_auth.py`**で、
写しは `gates/hooks/` と `graphloops/scripts/` と `works/.shared/core/` と `works-dispatch/dispatch/vendor/` と `attention/scripts/lib/`（2026-10-15 時点）。

実行時に跨いで読む道は無い——キャッシュに写るのはプラグインごとに自分のフォルダだけである。`convergence-loops` が
リポジトリのルートを配っていた間（0.43 まで。実測 2026-09-15: キャッシュに `gates/ graphloops/ scripts/ …` が丸ごと在った）も、
その道は採らなかった。キャッシュから拾えるのが「いちばん新しい版」で、gates の版と認証コードの版が黙ってずれる組み合わせが
起こるからである。認証は静かに壊れる場所（実測: 認証切れは終了コード 0 の 1 行で返る）なので、ここに版のずれを持ち込まない。

直すのは正本 1 か所、配るのは `python3 scripts/shared-copies.py --sync scripts/claude_auth.py`。
同一性は `tests/run.sh` のチェックが見る——**どれか 1 つだけ直すと赤くなる**。

**なぜ要るか。** 子は対話の claude の認証を継がない。利用者の `claude` がシェル関数のラッパ
（Keychain から OAuth トークンを読んで `CLAUDE_CODE_OAUTH_TOKEN` に入れてから実体を起動する形）のとき、
子は実体を直に起動するのでラッパを通らず、ハーネスも子の環境にトークンを渡さない（実測 2026-09-15:
Bash から見える環境では `CLAUDE_CODE_OAUTH_TOKEN` も `CLAUDE_CONFIG_DIR` も空だった）。
**落ち方は静か**——実測 2026-09-15: 素で起動した `claude -p` は
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
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import unicodedata

# 親の環境に在れば認証は足さない。子（claude）が読む経路——サブスクの OAuth・API キー・
# 企業のゲートウェイ・Bedrock / Vertex。**旗の 2 つは値も見る**（`=0` は「使わない」の意味で、
# 在るだけで認証が在ることにはならない）。
INHERITED = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
             "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
FLAGS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
OFF = ("", "0", "false", "False", "no")
TOKEN_PREFIX = "sk-ant-oat01-"
# `claude setup-token` のトークンの寿命（https://code.claude.com/docs/en/authentication の「Generate a long-lived token」:
# 「generate a one-year OAuth token」）。期限はサーバの側に在り、トークンの文字列からは読めないので、Keychain の項目を書き換えた日から数える
TOKEN_LIFETIME_DAYS = 365
EXPIRY_WARN_DAYS = 30   # 切れる日の何日前から知らせるか
# 認証の失敗は、子の標準出力に短い 1 行の JSON でない文が出て、終了コード 0 で返る（実測 2026-09-15 は 73 バイト）。
# 既知の文の約 4 倍を上限にする（文言が少し延びても拾い、JSON でない長い返答は拾わない）
AUTH_FAILURE_MAX_BYTES = 300


def config_dir(env):
    return env.get("CLAUDE_CONFIG_DIR") or str(pathlib.Path(env.get("HOME") or pathlib.Path.home()) / ".claude")


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
    子の保存済み認証で普通に動く場まで起動できなくなる。
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


def keychain_age_days(service, runner=subprocess.run, now=None):
    """Keychain の項目を最後に書き換えてから経った日数。項目が無い・読めなければ None——例外は投げない。

    属性（mdat。書き換えた時刻）だけを読み、値（トークン）は読まない（`-w` を付けない）。当てるのは、利用者が
    `claude setup-token` で作ったトークンを自分で書いた項目（keychain_service の名）だけ。同じトークンを書き直しても
    数え直しになる。Claude Code 自身が置く項目（claude_code_items）は自分で書き換わるので当てない。
    時間切れの 10 秒は read_keychain と同じ（security が固まったときに呼ぶ側ごと止めない）。
    """
    try:
        p = runner(["security", "find-generic-password", "-s", service],
                   capture_output=True, encoding="utf-8", timeout=10)
    except Exception:
        return None
    m = re.search(r'"mdat"<timedate>=\S*\s+"(\d{14})Z', p.stdout or "")
    if getattr(p, "returncode", 0) != 0 or not m:
        return None
    at = datetime.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
    return ((now or datetime.datetime.now(datetime.timezone.utc)) - at).days


def expiry_note(service, runner=subprocess.run, now=None):
    """Keychain の項目のトークンが、切れる日（書き換えた日から TOKEN_LIFETIME_DAYS 日）の EXPIRY_WARN_DAYS 日前を過ぎていれば
    人に見せる 1 行、まだなら None。書き換えた日を読めない（項目が無い・mac でない）ときも None。"""
    age = keychain_age_days(service, runner, now)
    if age is None or age < TOKEN_LIFETIME_DAYS - EXPIRY_WARN_DAYS:
        return None
    left = TOKEN_LIFETIME_DAYS - age
    if left > 0:
        when = "%d 日後に切れる見込み" % left
    elif left == 0:
        when = "今日切れる見込み"
    else:
        when = "切れた見込み（%d 日過ぎ）" % -left
    return ("Keychain の項目 %s のトークンは %d 日前に書いた物で、%s。`claude setup-token` で作り直し、"
            "この項目に書き直す" % (service, age, when))


def auth_failed(out):
    """子の標準出力が認証の失敗の形か。次のどちらかなら真。
    - 空でなく、AUTH_FAILURE_MAX_BYTES 以下の 1 行で、JSON として読めない（実測 2026-09-15 の形）
    - JSON の結果で `is_error` が真、`result` に authenticate か /login を含む（`--output-format json` の版で失敗がこの形で返る場合）

    JSON を返すはずの起動（`--output-format json` など）の出力にだけ使う。終了コードは見ない——認証の失敗は 0 で返る。
    使用枠の上限の 1 行（『Claude AI usage limit reached|…』など）も 1 つ目に当たる。どちらも「済んだ」ではないので、
    呼ぶ側は失敗に数えてよいが、知らせの文では認証と決めつけずに出力の頭を添える。
    """
    if isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    text = (out or "").strip()
    if not text:
        return False
    try:
        got = json.loads(text)
    except ValueError:
        return "\n" not in text and len(text.encode("utf-8")) <= AUTH_FAILURE_MAX_BYTES
    said = got.get("result") if isinstance(got, dict) else None
    return bool(isinstance(got, dict) and got.get("is_error") is True and isinstance(said, str)
                and ("authenticate" in said.lower() or "/login" in said))


def claude_code_items(user_config, home=None):
    """Claude Code 自身が Keychain に認証を置く項目の名の候補（先に試す物から）。CLAUDE_CONFIG_DIR を設定した Claude Code は
    `Claude Code-credentials-<その値（NFC）の sha256 の頭 8 桁>` に置き、無ければ `Claude Code-credentials`。
    user_config は Claude Code を起動するときの CLAUDE_CONFIG_DIR の値（入れずに起動するなら None）。
    足し書きの無い項目は既定のアカウントの物なので、user_config が既定のフォルダ（<home>/.claude）のときだけ候補に足す。
    別のフォルダのアカウントがそれを読むと、黙って別のアカウントの鍵で動く。"""
    if not user_config:
        return ["Claude Code-credentials"]
    digest = hashlib.sha256(unicodedata.normalize("NFC", user_config).encode("utf-8")).hexdigest()[:8]
    items = ["Claude Code-credentials-" + digest]
    default = os.path.join(home or str(pathlib.Path.home()), ".claude")
    if os.path.normpath(os.path.expanduser(user_config)) == os.path.normpath(default):
        items.append("Claude Code-credentials")
    return items


def _login_token(raw):
    """Claude Code が置いた認証の値（JSON の claudeAiOauth.accessToken か、トークンそのもの）からトークンを取り出す。"""
    raw = (raw or "").strip()
    try:
        tok = ((json.loads(raw) or {}).get("claudeAiOauth") or {}).get("accessToken") or ""
    except (ValueError, AttributeError):
        return raw
    return tok if isinstance(tok, str) else ""


def login_json_runner(runner):
    """read_keychain に渡す runner。Claude Code の項目の値が JSON なら、トークンだけに替えて返す
    （時間切れ・例外・sk-ant-oat01- の検査は read_keychain に任せる）。"""
    def run(args, **kw):
        p = runner(args, **kw)
        return subprocess.CompletedProcess(args, getattr(p, "returncode", 0), stdout=_login_token(p.stdout))
    return run


def account_token(user_config, env, explicit=None, platform=sys.platform, runner=subprocess.run):
    """1 つのアカウントの OAuth トークンを探し、`(トークン, 出どころ)` を返す。無ければ `(None, 探した所)`——例外は投げない。

    アカウントの持ち方は人で違うので、次の順に探す。
    1. 利用者が作った Keychain の項目（explicit → CLAUDE_KEYCHAIN_SERVICE → 設定のフォルダから導いた名）。値はトークンそのもの
    2. Claude Code 自身が置いた Keychain の項目（claude_code_items）。値は JSON
    3. 設定のフォルダの .credentials.json（Keychain の無い環境で Claude Code が置く所）
    user_config は Claude Code を起動するときの CLAUDE_CONFIG_DIR の値で、入れずに起動するアカウントは None。
    """
    cfg = user_config or str(pathlib.Path(env.get("HOME") or pathlib.Path.home()) / ".claude")
    tried = []
    if platform == "darwin":
        for service in [keychain_service(cfg, env, explicit)] + claude_code_items(user_config, env.get("HOME")):
            tok, note = read_keychain(service, login_json_runner(runner))
            if tok:
                return tok, "keychain(%s)" % service
            tried.append("%s:%s" % (service, note))
    path = os.path.join(cfg, ".credentials.json")
    try:
        with open(path, encoding="utf-8") as f:
            tok = _login_token(f.read())
    except FileNotFoundError:
        tried.append("%s:file-miss" % path)
    except (OSError, UnicodeDecodeError) as e:
        tried.append("%s:file-error(%s)" % (path, type(e).__name__))
    else:
        if tok.startswith(TOKEN_PREFIX):
            return tok, "file(.credentials.json)"
        # 形の違う値は渡さない（read_keychain の keychain-malformed と同じ訳）。捨てたことは探した所の並びに出す
        tried.append("%s:file-malformed" % path)
    return None, "見つからない: " + "、".join(tried)


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
