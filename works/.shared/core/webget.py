"""web の取得と run をまたぐ控え。層 L1（works の物を何も知らない。標準ライブラリだけ）。

機械（支度の script の節。Claude の sandbox の外）が網から文書を取る口と、取った物を run をまたいで使い回す控えを 1 か所に
持つ。前はライブラリの文書の節（libdocs）の中に在ったのを、世界の解の段（計画 docs/plans/2026-10-09-world-solution.md の
W1）も同じ口を使うので寄せた。振る舞いは前の libdocs の物と同じ（転送の決まり・読む量・控えの形と使う長さの決め方）。

網の口:
- safe_url(url) -> bool: 網に出してよい URL か（https で、host が点を持つ名。IP の字・localhost・点の無い社内の名・利用者名と
  合言葉を持つ URL は不可）。転送の先の確かめと、呼ぶ側の URL の選びが使う（社内の網や http へ転送させない）
- SafeRedirect: 転送は safe_url を通る先にだけ付いていく（ほかは 3xx のまま返す）
- http_get(url, headers, max_body) -> (状態の番号, 本文の頭 max_body バイトまで)。網に届かなければ FetchError（文は 1 行）。
  HTTP の誤りの状態は例外にせず番号と本文で返す。URL の字が Request に組めなければ ValueError のまま（前の libdocs と同じ。
  呼ぶ側は get の例外を取れなかった理由にする）。期限は足さない（呼ぶ側の節の宣言だけ）
- is_off(env, switch) -> bool: 網に出ない切り替え（値の前後の空白と大小を無視して off の時だけ真）。切り替えの名は呼ぶ側が持つ
  （libdocs は WORKS_LIBDOCS_WEB）。off の時に控えも読まないかは呼ぶ側が決める

run をまたぐ控え:
- shared_root(env, sub) -> Path | None: 置き場は包みの家（SHARED_ENV。開発の殻 dev/archon.sh が利用の家ごとに export する）の
  下の sub。利用の家ごとに分かれ、run を重ねても残り、切符が役に書かせない場所なので、役が控えを書き換えて後の run に混ぜることは
  できない。env に無い・相対なら None（包みを外した run・試験。run をまたぐ控えは使わない）
- Store(root, schema, ttl): 名ごとに 1 本の JSON（dict）。get(name, now, statuses=None) は schema が揃い、状態 status が statuses
  のどれか（None なら問わない）で、取った時刻 at（数）から ttl 秒の内（0 <= now - at < ttl）の物だけを返す。put(name, doc) は
  同じ置き場を同時に走る run と読み合うので一時のファイルに書いて置き換え、書けなければ理由の 1 行を返す。names(now, statuses=None)
  は get が返す名の一覧（控えの類を役に見せる世界の解の段が使う）。root が None なら読まず・書かない（put は空を返す）
"""
import ipaddress
import json
import os
import pathlib
import tempfile
import urllib.error
import urllib.parse
import urllib.request

SHARED_ENV = "WORKS_ADAPTER_HOME"


class FetchError(Exception):
    """網に届かない・答えが読めない（文は 1 行）"""


def safe_url(url) -> bool:
    """網に出してよい URL か: https で、host が点を持つ名（IP の字・localhost・点の無い社内の名は不可）で、利用者名・合言葉を持たない"""
    if not isinstance(url, str):
        return False
    try:
        p = urllib.parse.urlsplit(url.strip())
        host = (p.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if p.scheme != "https" or p.username or p.password or "." not in host or host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return True


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    """転送は safe_url を通る先（https・公の host の名）にだけ付いていく（ほかは 3xx のまま返す）"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_url(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get(url: str, headers: dict, max_body: int) -> tuple:
    """(状態の番号, 本文の頭 max_body バイトまで)。網に届かなければ FetchError。期限は足さない（節の宣言だけ）"""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.build_opener(SafeRedirect).open(req) as r:  # noqa: S310  宛先は呼ぶ側が選んだ口（転送は safe_url だけ）
            return r.status, r.read(max_body)
    except urllib.error.HTTPError as e:
        return e.code, e.read(max_body) or b""
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise FetchError(f"{type(e).__name__}: {e}"[:200]) from None


def is_off(env, switch: str) -> bool:
    """env の switch が off か（前後の空白と大小を無視）"""
    return str(env.get(switch, "")).strip().lower() == "off"


def shared_root(env, sub: str) -> pathlib.Path | None:
    """run をまたぐ控えの置き場（SHARED_ENV の絶対パスの下の sub）。env に無い・相対なら None（使わない）"""
    home = env.get(SHARED_ENV) or ""
    return pathlib.Path(home) / sub if os.path.isabs(home) else None


class Store:
    """run をまたぐ控えの置き場 root の、名ごとの JSON。root が None なら読まず・書かない"""

    def __init__(self, root: pathlib.Path | None, schema: str, ttl: float):
        self.root = pathlib.Path(root) if root is not None else None
        self.schema = schema
        self.ttl = ttl

    def _read(self, name: str):
        try:
            doc = json.loads((self.root / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) and doc.get("schema") == self.schema else None

    def _fresh(self, doc, now: float) -> bool:
        at = doc.get("at")
        return isinstance(at, (int, float)) and not isinstance(at, bool) and 0 <= now - at < self.ttl

    def get(self, name: str, now: float, statuses=None):
        """控えの 1 本（statuses の状態で、ttl の内の物）。無ければ None"""
        doc = self._read(name) if self.root is not None else None
        return doc if doc and (statuses is None or doc.get("status") in statuses) and self._fresh(doc, now) else None

    def names(self, now: float, statuses=None) -> list:
        """置き場の名のうち get が返す物（名の順。一時のファイルは数えない）。root が None・置き場が無いなら空"""
        if self.root is None or not self.root.is_dir():
            return []
        return [p.name for p in sorted(self.root.glob("*.json"))
                if not p.name.startswith(".tmp-") and self.get(p.name, now, statuses) is not None]

    def put(self, name: str, doc: dict) -> str:
        """控えに書く（一時のファイルに書いて置き換える）。書けなければ理由の 1 行。root が None なら何もしない"""
        if self.root is None:
            return ""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".tmp-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
                os.replace(tmp, self.root / name)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except OSError as e:
            return f"{name}: {type(e).__name__}: {e}"[:200]
        return ""
