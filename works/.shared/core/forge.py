"""対象のリポジトリの remote が forge（PR を持つホスト。今は GitHub だけ）かを、git だけで決める 1 か所。層 L1（works の物を
何も知らない。標準ライブラリだけで Python 3.9 で動く。ghreads と entry・report が読む）。

core は git だけで動き、gh・GitHub は外側の forge の層（持ち主の決定 2026-10-07）。forge の無い remote では、PR を前提に
する確かめ（並行 PR。利用者が名指した PR・issue は gh が読めなかった時だけ）は「確かめられなかった」ではなく「条件に当たら
ない」。それを AI の役に決めさせず（canary の run 5318f732 は同じローカルの origin で役が awaiting_human と書き、round_limit
になった）、ここで機械が決める。GitHub の remote で gh が無い・未ログイン・API が落ちた時は、確かめる物が在るので forge が在る側（今どおり）。

- classify(url) -> {kind, where}: URL の形だけで決める。kind は GITHUB・NO_REMOTE（空）・LOCAL_PATH（パス・file:）・OTHER_HOST
  （GitHub でないホスト。GitLab・自前のホストなど）。where はホスト（userinfo とポートを落とす）かパス。トークンは載せない
- detect(repo) -> {kind, remote, where}: upstream の remote を先に、無ければ origin（写しの rules の _github_repo と同じ選び方）。
  git が remote を引けない（リポジトリでない・git が無い）は UNKNOWN（決めない）
- redact(text) -> str: 文の中の URL の userinfo（トークン）を落とす
- reason(d) -> str: forge の無い種類なら "no_forge: <種類>（…）"、それ以外（GitHub・UNKNOWN・形の崩れた値・None）は ""

GitHub と数えるホストは github.com（www・ssh の下を含む。ssh の形は github.com で始まる別名も）と GitHub Enterprise Cloud の
<名>.ghe.com。自前のホストの
GitHub Enterprise Server（任意のドメイン）は形から分からないので OTHER_HOST に入る。
"""
import re
import subprocess
import urllib.parse

GITHUB = "github"
NO_REMOTE = "no_remote"
LOCAL_PATH = "local_path"
OTHER_HOST = "other_host"
UNKNOWN = "unknown"
NO_FORGE = (NO_REMOTE, LOCAL_PATH, OTHER_HOST)
PREFIX = "no_forge"
LOOP_KEY = "forge"   # 盤面の loop の欄（works が run の初めに detect の返りを置く）

GITHUB_HOSTS = ("github.com", "www.github.com", "ssh.github.com")
GHE_CLOUD = re.compile(r"^[a-z0-9][a-z0-9-]*\.ghe\.com$")
# scp の形 [user@]host:path（:// を持たず、最初の : の前に / が無い。1 文字の前置きは Windows のドライブ）
SCP = re.compile(r"^(?:[^@/:]+@)?([^@/:]+):(?!//)")
WIN_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _host_kind(host: str, *, ssh: bool = False) -> str:
    """ssh の形（ssh:// と scp の形）は github.com で始まるホストも GitHub（~/.ssh/config の Host の別名 github.com-work など。
    写しの rules の GITHUB_REMOTE と同じ広さ）"""
    h = host.lower().rstrip(".")
    ok = h in GITHUB_HOSTS or GHE_CLOUD.match(h) or (ssh and h.startswith("github.com"))
    return GITHUB if ok else OTHER_HOST


def classify(url) -> dict:
    """URL の形から {kind, where}。読めない URL は OTHER_HOST（where に URL を載せない）"""
    try:
        return _classify(url)
    except ValueError:
        return {"kind": OTHER_HOST, "where": "（読めない URL）"}


def _classify(url) -> dict:
    u = (url or "").strip() if isinstance(url, str) else ""
    if not u:
        return {"kind": NO_REMOTE, "where": ""}
    if WIN_DRIVE.match(u):
        return {"kind": LOCAL_PATH, "where": u}
    if u.lower().startswith("file:"):
        p = urllib.parse.urlsplit(u)
        return {"kind": LOCAL_PATH, "where": urllib.parse.unquote(p.path) or u.split(":", 1)[1]}
    if "://" in u:
        p = urllib.parse.urlsplit(u)
        try:
            host = p.hostname or ""
        except ValueError:
            host = ""
        if not host:
            return {"kind": OTHER_HOST, "where": "（ホストの読めない URL）"}
        return {"kind": _host_kind(host, ssh=p.scheme.lower() in ("ssh", "git+ssh", "ssh+git")), "where": host.lower()}
    if "::" in u.split("/", 1)[0]:   # git の remote helper（<transport>::<address>）
        return {"kind": OTHER_HOST, "where": f"remote helper {u.split('::', 1)[0]}"}
    m = SCP.match(u)
    if m:
        return {"kind": _host_kind(m.group(1), ssh=True), "where": m.group(1).lower()}
    return {"kind": LOCAL_PATH, "where": u}


USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/@\s]+@")


def redact(text: str) -> str:
    """文の中の URL の userinfo（ユーザー名・トークン）を落とす（https://x:TOKEN@github.com/o/r → https://github.com/o/r）"""
    return USERINFO.sub(r"\1", text) if isinstance(text, str) else text


def _git(repo, *args):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", stdin=subprocess.DEVNULL)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def detect(repo) -> dict:
    """repo の remote の forge の種類 {kind, remote, where}"""
    if _git(repo, "rev-parse", "--git-dir") is None:
        return {"kind": UNKNOWN, "remote": "", "where": ""}
    remotes = set((_git(repo, "remote") or "").split())
    up = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}") or ""
    name = up.split("/", 1)[0] if "/" in up else ""
    remote = name if name in remotes else "origin"
    url = _git(repo, "remote", "get-url", remote) if remote in remotes else None
    return {"remote": remote, **classify(url)}


def reason(d) -> str:
    """forge の無い種類なら "no_forge: <種類>（…）"。それ以外は ""（今どおり確かめる側）"""
    if not isinstance(d, dict) or d.get("kind") not in NO_FORGE:
        return ""
    kind, remote, where = d["kind"], d.get("remote") or "origin", d.get("where") or ""
    what = {NO_REMOTE: f"remote '{remote}' が無い",
            LOCAL_PATH: f"remote '{remote}' はローカルのパス {where}",
            OTHER_HOST: f"remote '{remote}' のホスト {where} は GitHub でない"}[kind]
    return f"{PREFIX}: {kind}（{what}。PR を持つホストが無いので、PR を前提にする確かめは条件に当たらない）"
