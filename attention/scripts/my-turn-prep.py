#!/usr/bin/env python3
"""/my-turn の「掘る段」の下ごしらえ。PR の差分・規約・指紋を機械で用意し、JSON 1 つで返す。

使い方:
  my-turn-prep.py <PR 番号> [--prior <記録.json>] [--headless]
  my-turn-prep.py --sync <PR 番号>          PR のブランチに居て遅れているだけなら、PR の先頭へ fast-forward する
  my-turn-prep.py --quotes <記録.json>     記録の中の根拠の写しを照合する
  my-turn-prep.py --quotes --b64 <頭> <id>:<行> ...
                                          引数の根拠を照合する（Workflow の写しの照合の段が打つ。1 行ずつ base64）
  my-turn-prep.py --save-record <記録.json> <Workflow の出力のファイル>
                                          Workflow が返した記録を、記録のファイルに書く
  my-turn-prep.py --check-report <記録.json> <報告.md>
                                          記録の台帳の id と下書きの場所が、会話の報告に全部在るかを照合する

PR の作業場（cwd）で打つ。判定はしない——材料を集めて Workflow（my-turn-dig.js）へ渡す形に
するだけ。終了の値は、続けてよいとき 0、止めるとき 1（`ok: false`）、使い方の誤りは 2。
設計は attention/docs/my-turn-workflow-design.md の 2・5・7・11。
"""

import argparse
import base64
import binascii
import json
import os
import posixpath
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import changemap  # noqa: E402 — 差分の取り方の部品（DIFF_SANE）を /what-am-i-doing と共用
import my_turn_record  # noqa: E402 — 記録の版と書き方（my-turn-headless.py と共用）
from fnv import fnv32  # noqa: E402 — my-turn-dig.js の fnv と同じ値（steps-prep.py・world-excerpts.py と共用）

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# 差分の本文から外す lock file（basename で照合）。--stat と changed には残す
LOCK_NAMES = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock",
              "go.sum", "bun.lockb", "packages.lock.json", "Package.resolved"}
ENV_SUBAGENT_MODEL = "CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL"
# 使う人の git の設定（diff.external・textconv・color.ui=always・接頭辞）で差分の本文と patch-id を変えない
DIFF_PLAIN = changemap.DIFF_SANE
# 日本語などの path を \350… の形に書き換えない（段が読む差分のファイルの path を、変えたファイルの一覧と同じ綴りにする）
QUOTE_OFF = ("-c", "core.quotepath=off")


class Stop(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def run(args, cwd=None, timeout=120, stdin=None, text=True, env=None):
    """外部コマンドを 1 回走らせる。(終了の値, 標準出力)。起動できない・時間切れは (-1, "")。text=False はバイトのまま。"""
    enc = {"encoding": "utf-8", "errors": "replace"} if text else {}
    try:
        r = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, timeout=timeout, env=env, **enc)
    except (OSError, subprocess.TimeoutExpired):
        return -1, ("" if text else b"")
    return r.returncode, r.stdout


def git_bytes(*args, stdin=None):
    """git をバイトのまま走らせる。テキストの読みは \r\n を \n に変えるので、改行だけの直しを見落とす。"""
    return run(["git", *args], stdin=stdin, text=False)


def git(*args, stdin=None):
    return run(["git", *args], stdin=stdin)


def must_git(*args, stdin=None):
    rc, out = git(*args, stdin=stdin)
    if rc != 0:
        sub = list(args)
        while sub[:1] == ["-c"]:  # 頭の -c <設定> は飛ばし、どのコマンドが失敗したかを言う
            sub = sub[2:]
        raise Stop("git-failed", "git %s が失敗しました。作業場が git のリポジトリか確かめてください" % " ".join(sub[:2]))
    return out


def is_lock(path):
    base = path.rsplit("/", 1)[-1]
    return base.endswith(".lock") or base in LOCK_NAMES


def emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False))
    return code


def stop_obj(code, message):
    return {"ok": False, "stop": code, "message": message}


def abs_path(p, top):
    """区切りを / にし、相対なら repo のルートに繋ぎ、./ と a/../b を畳んだ絶対の path（dig.js の absOf と同じ）。"""
    p = p.strip().replace("\\", "/")
    if not (posixpath.isabs(p) or re.match(r"^[A-Za-z]:/", p)):
        p = top.replace("\\", "/").rstrip("/") + "/" + p
    return posixpath.normpath(p)


def norm_path(p, top):
    """repo の中ならリポジトリ相対の path に。repo の外か空なら None（git cat-file が fatal で止まる）。"""
    t = top.replace("\\", "/").rstrip("/") + "/"
    a = abs_path(p, top)
    return (a[len(t):] or None) if a.startswith(t) else None


def pr_remote(repo_name):
    """(PR のリポジトリを指す remote の名, 見つかったか)。fork の作業場では origin が自分の fork を指すので、
    URL で探す。見つからなければ origin（見つからなかったことは prep の remoteMatched で報告に出る）。"""
    rc, out = git("remote", "-v")
    pat = re.compile(r"[/:]%s(?:\.git)?/?$" % re.escape(repo_name), re.I)
    names = []
    for line in out.splitlines() if rc == 0 else []:
        f = line.split()
        if len(f) >= 3 and f[2] == "(fetch)" and pat.search(f[1]) and f[0] not in names:
            names.append(f[0])
    if not names:
        return "origin", False
    return ("origin" if "origin" in names else names[0]), True


def blobs(rev, paths):
    """{path: その版の object の sha（無ければ None）}。git cat-file --batch-check の 1 回で引く。"""
    paths = list(paths)
    asked = [p for p in paths if "\n" not in p and "\r" not in p]  # 改行を含む path は 1 行の問いにならない
    if not asked:
        return {p: None for p in paths}
    lines = must_git("cat-file", "--batch-check", stdin="".join("%s:%s\n" % (rev, p) for p in asked)).splitlines()
    if len(lines) != len(asked):
        raise Stop("git-failed", "git cat-file --batch-check の答えの行の数が、問うた数と合いません")
    got = {p: (m.group(1) if m else None)
           for p, m in zip(asked, (re.match(r"^([0-9a-f]{40,64}) \S+ \d+$", ln) for ln in lines))}
    return {p: got.get(p) for p in paths}


def record_complete(rec):
    """前の回の記録に、何も返さなかったエージェントが 1 体も無いか（段の一部だけ落ちた回も欠けに数える）。"""
    counts = rec.get("counts")
    stages = counts.get("stages") if isinstance(counts, dict) else None
    if not isinstance(stages, dict):
        return False
    return all(isinstance(e, dict) and not e.get("null") for e in stages.values())


def load_record(path):
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        raise Stop("prior-unreadable", "記録 %s を読めません（無いか、JSON でない）。パスを確かめてください" % path)
    if not isinstance(rec, dict):
        raise Stop("prior-unreadable", "記録 %s の形が違います（JSON のオブジェクトでない）" % path)
    return rec


def changed_files(a, b):
    # --no-renames: 名前を変えたファイルの古い path も載せる（lock file を移したとき、古い側の全部の削除が本文に残らない）
    out = must_git(*QUOTE_OFF, "diff", *DIFF_PLAIN, "--no-renames", "--name-only", "-z", a, b)
    return sorted(p for p in out.split("\0") if p)


def body_args(a, b, excluded):
    return [*QUOTE_OFF, "diff", *DIFF_PLAIN, "-U10", a, b, "--", ".", *[":(exclude,literal)" + p for p in excluded]]


def patch_id_of(patch):
    """差分のバイトの patch-id。空の差分は ""。"""
    if not patch:
        return ""
    # --verbatim は空白と改行の字も比べる（字下げ・CRLF だけの直しを「変わっていない」にしない）。無い git（2.39 より前）は --stable
    rc, out = git_bytes("patch-id", "--verbatim", stdin=patch)
    if rc != 0:
        rc, out = git_bytes("patch-id", "--stable", stdin=patch)
    if rc != 0:
        raise Stop("git-failed", "git patch-id が失敗しました")
    return (out.decode("ascii", "replace").split() or [""])[0]


def diff_key(a, b):
    """差分のファイルの中身の比べの鍵: commit の件名の一覧・stat・本文（lock file を除く）の patch-id。
    commit の sha と行の番号（base の側の動き）は数えない。"""
    excluded = [p for p in changed_files(a, b) if is_lock(p)]
    rc, patch = git_bytes(*body_args(a, b, excluded))
    if rc != 0:
        raise Stop("git-failed", "git diff %s %s が失敗しました" % (a[:7], b[:7]))
    subjects = must_git("-c", "log.showSignature=false", "log", "--reverse", "--format=%s", "%s..%s" % (a, b))
    return patch_id_of(patch), subjects, must_git(*QUOTE_OFF, "diff", *DIFF_PLAIN, "--stat=1000", a, b)


def write_diff(path, a, b, a7, b7):
    """差分ファイルを書く: 見出し・commit 一覧・stat・本文（lock file を除く）。(変えたファイル, 外した物, stat) を返す。"""
    files = changed_files(a, b)
    excluded = [p for p in files if is_lock(p)]
    # log.showSignature を切る（gpg の検証の行が commit の一覧に混ざる）
    log = must_git("-c", "log.showSignature=false", "log", "--reverse", "--format=%H %s", "%s..%s" % (a, b))
    stat = must_git(*QUOTE_OFF, "diff", *DIFF_PLAIN, "--stat=1000", a, b)
    # 本文はバイトで取る（テキストの読みは \r\n と単独の \r を \n に変え、改行の字だけの直しが本文から消える）
    rc, raw = git_bytes(*body_args(a, b, excluded))
    if rc != 0:
        raise Stop("git-failed", "git diff %s %s が失敗しました" % (a7, b7))
    body = raw.decode("utf-8", "replace")

    def nl(s):
        return s if s == "" or s.endswith("\n") else s + "\n"

    text = ("# commits %s..%s\n%s# stat\n%s# diff -U10 (lock files left out: %s)\n%s"
            % (a7, b7, nl(log), nl(stat), ", ".join(excluded) or "none", nl(body)))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return files, excluded, stat


RULE_NAMES = ("AGENTS.md", "CLAUDE.md", "REVIEW.md")


def ancestor_dirs(paths):
    """paths の各ファイルの親の階層を、ルート（""）まで全部。paths が空なら空。"""
    return {"/".join(p.split("/")[:i]) for p in paths for i in range(p.count("/") + 1)}


def rule_paths(changed, base):
    # ルートの .claude/ の下の決まりも Claude Code は読む（AGENTS.md は CLAUDE.md の代わりに使うリポジトリが在る）
    cands = {".claude/AGENTS.md", ".claude/CLAUDE.md"}
    cands |= {d + "/" + name if d else name for d in ancestor_dirs(changed) for name in RULE_NAMES}
    keep = [p for p, sha in blobs(base, sorted(cands)).items() if sha]
    # ルートが先、あとは階層の辞書順、同じ階層では名前の辞書順
    return sorted(keep, key=lambda p: (p.split("/")[:-1], p.rsplit("/", 1)[-1]))


# ---- 段 0 の足し（lines・deletedTests・決まりの文書の広げ・identitySignals）----
# どれも、git が失敗しても下ごしらえを止めない（空の値と stage0Errors に訳を足す）

CLASSES = ("impl", "test", "check", "ci", "docs", "config", "generated")
# ファイルの区分の表。上から順に当てる（最初に当たった物）。残りは impl
TEST_DIRS = ("tests", "test", "__tests__")
TEST_NAME_RE = re.compile(r"(^test_.*\.py$|_test\.[^/]+$|\.test\.[^/]+$|\.spec\.[^/]+$)")
CHECK_RE = re.compile(r"(^|/)scripts/check[^/]*$|(^|/)[^/]*lint[^/]*$|(^|/)\.pre-commit-config\.yaml$|(^|/)[^/]*check[^/]*\.(py|sh|mjs)$")
DOC_EXTS = (".md", ".rst", ".txt")
CONFIG_EXTS = (".json", ".toml", ".yaml", ".yml", ".ini", ".cfg")


def classify(path, binary=False):
    """ファイルの path から区分（CLASSES のどれか）を返す。lock file と数えられない（バイナリ）物は generated。"""
    base = path.rsplit("/", 1)[-1]
    parts = path.split("/")
    if is_lock(path) or binary:
        return "generated"
    if path.startswith(".github/"):
        return "ci"
    if any(d in TEST_DIRS for d in parts[:-1]) or TEST_NAME_RE.search(base):
        return "test"
    if CHECK_RE.search(path):
        return "check"
    if base.endswith(DOC_EXTS) or "docs" in parts[:-1]:
        return "docs"
    if base.endswith(CONFIG_EXTS):
        return "config"
    return "impl"


def numstat_rows(a, b):
    """git diff --numstat（差分の本文と同じ範囲）の行: [(足した行, 消した行, path, バイナリか)]。"""
    out = must_git(*QUOTE_OFF, "diff", *DIFF_PLAIN, "--no-renames", "--numstat", "-z", a, b)
    rows = []
    for rec in out.split("\0"):
        m = re.match(r"^(\d+|-)\t(\d+|-)\t(.+)$", rec, re.S)
        if m:
            binary = m.group(1) == "-"
            rows.append((0 if binary else int(m.group(1)), 0 if binary else int(m.group(2)), m.group(3), binary))
    return rows


def count_lines(a, b):
    by = {c: {"added": 0, "deleted": 0, "files": 0} for c in CLASSES}
    for add, dele, path, binary in numstat_rows(a, b):
        e = by[classify(path, binary)]
        e["added"] += add
        e["deleted"] += dele
        e["files"] += 1
    impl_added = by["impl"]["added"]
    ratio = round((by["test"]["added"] + by["check"]["added"]) / impl_added, 2) if impl_added else None
    return {"byClass": by, "testToImpl": ratio}


# 言語ごとの、試験の名前の取り出し
def _names_py(text):
    return re.findall(r"def\s+(test_\w+)", text)


def _names_js(text):
    return [m.group(2) for m in re.finditer(r"\b(?:it|test|describe)\(\s*(['\"`])(.+?)\1", text)]


def _names_go(text):
    return re.findall(r"func\s+(Test\w+)", text)


def _names_rust(text):
    lines, out = text.split("\n"), []
    for i, ln in enumerate(lines[:-1]):
        if ln.strip().startswith("#[test]"):
            m = re.search(r"\bfn\s+(\w+)", lines[i + 1])
            if m:
                out.append(m.group(1))
    return out


def _names_sh(text):
    return re.findall(r"^(\w+)\s*\(\)", text, re.M)


TEST_NAME_PATTERNS = (
    ((".py",), _names_py),
    ((".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"), _names_js),
    ((".go",), _names_go),
    ((".rs",), _names_rust),
    ((".sh",), _names_sh),
)


def test_name_finder(path):
    for exts, fn in TEST_NAME_PATTERNS:
        if path.endswith(exts):
            return fn
    return None


def show_text(rev, path):
    """その版のファイルの字。無ければ None。"""
    rc, out = git_bytes("show", "%s:%s" % (rev, path))
    return out.decode("utf-8", "replace") if rc == 0 else None


def deleted_tests(changed, base, head):
    """base に在って head に無い試験の関数・ケース。ファイルごと消えた物は files にも、中の名前は names にも載せる。
    名前を取れない言語の試験のファイル（base に在る物）は uncounted。"""
    from collections import Counter
    files, names, uncounted = [], [], []
    for path in changed:
        if classify(path) != "test":
            continue
        old, new = show_text(base, path), show_text(head, path)
        if old is None:
            continue  # base に無い（足した）試験は、消えようが無い
        if new is None:
            files.append(path)
        find = test_name_finder(path)
        if find is None:
            uncounted.append(path)
            continue
        gone = Counter(find(old)) - Counter(find(new or ""))
        for name in find(old):  # base に出る順で、足りない数だけ数える
            if gone[name] > 0:
                gone[name] -= 1
                names.append({"path": path, "name": name})
    return {"files": files, "names": names, "uncounted": uncounted}


RULE_EXTRA_NAMES = ("architecture.md", "ARCHITECTURE.md", "CONTRIBUTING.md")
ADR_DIRS = ("docs/adr/", "adr/", "doc/adr/", "docs/decisions/", "decisions/")
LEDGER_WORDS = ("ledger", "台帳", "decisions")
RULES_EXTRA_CAP = 40


def extra_rule_paths(changed, base, old):
    """決まりの文書に足す物（base の版）: 構成・貢献の文書、ADR のフォルダの下、名前に ledger・台帳・decisions を含む物。
    (足す path の一覧〔上限で切った後〕, 上限で外した数)。old は今までの決まりの path（重ねて足さない）。"""
    dirs = {""} | ancestor_dirs(changed)
    tree = must_git(*QUOTE_OFF, "ls-tree", "-r", "--name-only", "-z", base)
    found = set()
    for p in tree.split("\0"):
        if not p:
            continue
        d, _, name = p.rpartition("/")
        if (d in dirs and (name in RULE_EXTRA_NAMES or any(w in name.lower() for w in LEDGER_WORDS))
                or p.startswith(ADR_DIRS)):
            found.add(p)
    keep = sorted(found - set(old), key=lambda p: (p.split("/")[:-1], p.rsplit("/", 1)[-1]))
    return keep[:RULES_EXTRA_CAP], max(0, len(keep) - RULES_EXTRA_CAP)


SIGNAL_CAP = 50
SIGNAL_TEXT_MAX = 200
WORKFLOW_RE = re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")
PERM_KEY_RE = re.compile(r"^\s*(permissions\s*:|id-token\s*:|[\w-]+\s*:\s*write\b)")
SECRETS_RE = re.compile(r"secrets\.")
SETTING_NAME_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Z0-9_]*(?:TOKEN|API_KEY|SECRET|PRIVATE_KEY|CREDENTIALS?)[A-Z0-9_]*(?![A-Za-z0-9_])")
IAM_PATH_RE = re.compile(r"(^|[/_.-])iam([/_.-]|$)", re.I)
TF_IAM_RE = re.compile(r"aws_iam_|google_.*_iam|azurerm_role")
K8S_ROLE_RE = re.compile(r"^\s*kind\s*:\s*(Cluster)?Role(Binding)?\b")


def signal_of(path, text):
    if WORKFLOW_RE.match(path) and PERM_KEY_RE.search(text):
        return True
    if SECRETS_RE.search(text) or SETTING_NAME_RE.search(text) or K8S_ROLE_RE.search(text):
        return True
    if path.endswith(".tf") and TF_IAM_RE.search(text):
        return True
    return bool(IAM_PATH_RE.search(path)) and bool(text.strip())


def identity_signals(base, head):
    """差分（-U0）が足した行のうち、新しい身元・権限の印に見える物。(一覧〔上限で切った後〕, 上限で外した数)。"""
    rc, raw = git_bytes(*QUOTE_OFF, "diff", *DIFF_PLAIN, "--no-renames", "-U0", base, head)
    if rc != 0:
        raise Stop("git-failed", "git diff -U0 が失敗しました")
    found, path, ln, skip = [], None, 0, False
    for row in raw.decode("utf-8", "replace").split("\n"):
        if row.startswith("diff --git "):
            path, skip = None, False
        elif row.startswith("+++ "):
            path = row[4:].rstrip("\r")
            path = path[2:] if path.startswith("b/") else None  # /dev/null（消したファイル）は足した行が無い
            skip = bool(path) and is_lock(path)
        elif row.startswith("@@"):
            m = re.match(r"^@@ -\S+ \+(\d+)", row)
            ln = int(m.group(1)) if m else 0
        elif row.startswith("+") and path and not skip:
            text = row[1:].strip()
            if signal_of(path, text):
                found.append({"path": path, "line": ln, "text": text[:SIGNAL_TEXT_MAX]})
            ln += 1
    return found[:SIGNAL_CAP], max(0, len(found) - SIGNAL_CAP)


def repo_of_remote(remote):
    """branch.<名>.remote の値（remote の名か URL）が指すリポジトリの "owner/name"（小文字）。読めなければ None。"""
    url = remote
    if not re.search(r"[/:\\]", remote):
        rc, out = git("remote", "get-url", remote)
        url = out.strip() if rc == 0 else ""
    m = re.search(r"[/:\\]([^/:\\]+)[/\\]([^/\\]+?)(?:\.git)?[/\\]?$", url)
    return ("%s/%s" % (m.group(1), m.group(2))).lower() if m else None


def is_pr_branch(cur, pr, info, repo_name):
    """今のブランチ cur が PR の head のブランチか。追跡先が PR の head を指すか（gh pr checkout・/catchup が作る形:
    同じリポジトリの refs/heads/<head>、fork の URL の refs/heads/<head>、base の refs/pull/N/head）、同じリポジトリの
    PR で名前が head と同じなら、そう見る。fork の PR は名前だけでは見ない（fork の head が main のような名前で来ると、
    base 側の手元の main を PR の先頭へ進めてしまう）。"""
    head_ref = info.get("headRefName") or ""
    owner = (info.get("headRepositoryOwner") or {}).get("login") or ""
    name = (info.get("headRepository") or {}).get("name") or ""
    rc, merge = git("config", "--get", "branch.%s.merge" % cur)
    rc2, remote = git("config", "--get", "branch.%s.remote" % cur)
    merge, remote = (merge.strip() if rc == 0 else ""), (remote.strip() if rc2 == 0 else "")
    if remote:
        at = repo_of_remote(remote)
        if merge == "refs/pull/%d/head" % pr and at == repo_name.lower():
            return True
        if head_ref and merge == "refs/heads/" + head_ref and owner and name and at == ("%s/%s" % (owner, name)).lower():
            return True
    return not info.get("isCrossRepository") and bool(head_ref) and cur == head_ref


def sync(pr):
    """PR のブランチに居て手元が遅れているだけなら、PR の先頭まで fast-forward する（/my-turn・/my-turn-deep の手順 2）。
    進めるのは、PR のブランチに居て・追跡ファイルに未コミットの変更が無く・手元の先頭が PR の先頭の祖先のときだけ。
    それ以外は動かさずに止まる（別のブランチ・detached は /catchup で移る。手元が先に進んでいる・分かれているときは、
    どちらを残すかを人が決める）。git pull --ff-only でなく PR の先頭の commit へ merge --ff-only するのは、追跡先の
    設定の無いブランチでも、追跡先が PR の head と別の所を指していても、行き先を PR の先頭に決めるため。"""
    rc, out = run(["gh", "pr", "view", str(pr), "--json",
                   "headRefOid,headRefName,isCrossRepository,headRepository,headRepositoryOwner,url"], timeout=60)
    try:
        info = json.loads(out)
        head_oid, url = info["headRefOid"], info["url"]
        m = re.match(r"https?://[^/]+/([^/]+/[^/]+)/pull/\d+", url)
        if rc != 0 or not (head_oid and m):
            raise ValueError
        repo_name = m.group(1)
    except (ValueError, KeyError, TypeError):
        raise Stop("gh-failed", "gh pr view %s が失敗したか、読めない答えでした。gh auth status と PR の番号を確かめてください" % pr)
    old = must_git("rev-parse", "HEAD").strip()
    if old == head_oid:
        return {"ok": True, "synced": False, "head": old}
    rc, cur = git("symbolic-ref", "--short", "-q", "HEAD")
    cur = cur.strip() if rc == 0 else ""
    if not cur or not is_pr_branch(cur, pr, info, repo_name):
        where = "ブランチ %s" % cur if cur else "detached HEAD"
        raise Stop("not-pr-branch", "手元は %s で、PR #%s のブランチ（%s）ではありません。/catchup %s で PR のブランチへ移ってから呼び直してください"
                   % (where, pr, info.get("headRefName") or "?", pr))
    dirty = [ln for ln in must_git("status", "--porcelain", "--untracked-files=no").splitlines() if ln.strip()]
    if dirty:
        raise Stop("dirty", "追跡ファイルに未コミットの変更が %d 件あるので、PR の先頭へ更新しません。自分の編集か確かめ、"
                   "commit か stash してから呼び直してください" % len(dirty))
    if not changemap.has_commit(head_oid):
        remote, _ = pr_remote(repo_name)
        git("fetch", "--no-tags", remote, "refs/pull/%s/head" % pr)
        if not changemap.has_commit(head_oid):
            raise Stop("fetch-failed", "PR の先頭の commit %s を %s から取れませんでした。ネットワークと %s の設定を確かめてください"
                       % (head_oid[:7], remote, remote))
    if git("merge-base", "--is-ancestor", old, head_oid)[0] != 0:
        if git("merge-base", "--is-ancestor", head_oid, old)[0] == 0:
            raise Stop("ahead", "手元の %s は PR の先頭より先に進んでいます（push していない commit が在る）。push してから呼び直してください" % cur)
        raise Stop("diverged", "手元の %s と PR の先頭が分かれています（手元にだけ在る commit と、PR にだけ在る commit が両方在る。"
                   "force push の後など）。どちらを残すかを決めて揃えてから呼び直してください" % cur)
    # 書く操作は timeout で殺さない（途中で殺すと書きかけの木と index.lock が残る）
    git_rc = run(["git", "merge", "--ff-only", "-q", head_oid], timeout=None)[0]
    new = must_git("rev-parse", "HEAD").strip()
    if new != head_oid:
        raise Stop("ff-failed", "git merge --ff-only %s が通りませんでした（終了の値 %s。未追跡のファイルが上書きされる、など）。"
                   "手で打って訳を見てください" % (head_oid[:7], git_rc))
    count = must_git("rev-list", "--count", "%s..%s" % (old, new)).strip()
    return {"ok": True, "synced": True, "branch": cur, "from": old, "head": new, "commits": int(count)}


def own_base(base_ref, merge_base):
    """(範囲の始まり, 訳)。取り込み先のブランチが書き換わった（rebase の後に force push された）PR では、merge-base が
    取り込み先の今の先頭でなく、もっと前（多くは main）に落ち、取り込み先の前の版の commit まで PR の差分に載る
    （guided-resolver の #2653。取り込み先 issue-1732 が書き換わり、merge でない 22 commit のうち 10 が #2531 の前の版だった）。
    取り込み先に同じ変更（patch-id）の無い commit（PR 自身の commit）が、先頭から first-parent で続く所（間の merge の
    commit は PR のブランチが取り込んだ物として通す）だけに在るなら、その下の commit（取り込み先の前の版の先頭）を始まりに
    する。間に merge の commit が在れば、取り込んだ側をその前の版の先頭に同じ順で merge した commit を作り（ref は作らない）、
    それを始まりにする。そうでない（PR 自身の commit が混ざっている・作った merge がぶつかる）なら merge-base のままにし、
    訳に書く。訳は、範囲を変えたときと、変えられなかったときだけ。
    取り込み先が remote の既定のブランチ（`<remote>/HEAD` の指す先。ふつうは main）なら照合しない。既定のブランチは
    ふつう書き換えないうえ、--cherry-pick は merge-base の後に取り込み先に入った commit の全部の patch-id を数えるので、
    main が大きく進んだ PR で毎回遅くなる。"""
    rc, head_ref = git("symbolic-ref", "-q", "refs/remotes/%s/HEAD" % base_ref.split("/", 1)[0])
    if rc == 0 and head_ref.strip() == "refs/remotes/" + base_ref:
        return merge_base, ""
    rc, out = git("rev-list", "--right-only", "--cherry-pick", "--no-merges", "%s...HEAD" % base_ref)
    if rc != 0:
        return merge_base, ""
    own = set(out.split())
    rest = [c for c in must_git("rev-list", "--no-merges", "%s..HEAD" % merge_base).split() if c]
    if not own or len(own) == len(rest):
        return merge_base, ""
    keep = ("%s との merge-base の後の、merge でない %d commit のうち %d は同じ変更が %s に在る（取り込み先が書き換わった）が、"
            "PR 自身の commit と分けられないので、範囲は merge-base から取った。PR を %s に rebase すると分かれる"
            % (base_ref, len(rest), len(rest) - len(own), base_ref, base_ref))
    merged, seen, old_tip = [], 0, None
    for line in must_git("rev-list", "--first-parent", "--parents", "%s..HEAD" % merge_base).splitlines():
        c, *parents = line.split()
        if len(parents) > 1:
            merged.extend(reversed(parents[1:]))  # 3 つ以上の親（octopus）も、取り込んだ側を全部足す
        elif c in own:
            seen += 1
        else:
            old_tip = c
            break
    if old_tip is None or seen != len(own):
        return merge_base, keep
    base = old_tip
    if merged:
        env = dict(os.environ, GIT_AUTHOR_NAME="attention", GIT_AUTHOR_EMAIL="attention@invalid",
                   GIT_COMMITTER_NAME="attention", GIT_COMMITTER_EMAIL="attention@invalid")
        # 同じ PR の先頭からは同じ commit になるよう、日時は PR の先頭の物にする
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = must_git("log", "-1", "--format=%cI", "HEAD").strip()
        unmerged = ("%s との merge-base の後の、merge でない %d commit のうち %d は同じ変更が %s に在る（取り込み先が書き換わった）が、"
                    "%s の前の版の先頭 %s に PR のブランチが取り込んだ物を merge できなかった（ぶつかった・git が 2.38 より古い）"
                    "ので、範囲は merge-base から取った" % (base_ref, len(rest), len(rest) - len(own), base_ref, base_ref, old_tip[:7]))
        for side in reversed(merged):  # 古い merge から
            rc, tree = git("merge-tree", "--write-tree", base, side)  # --write-tree は git 2.38 から
            if rc != 0 or not tree.strip():
                return merge_base, unmerged
            # 利用者の commit.gpgsign で署名させない（pinentry で止まる・回ごとに commit が変わる）
            rc, made = run(["git", "-c", "commit.gpgsign=false", "commit-tree", tree.split()[0], "-p", base, "-p", side,
                            "-m", "attention: %s の前の版の先頭に、PR のブランチが取り込んだ物を merge した始まり" % base_ref],
                           env=env)
            if rc != 0 or not made.strip():
                return merge_base, unmerged
            base = made.strip()
    return base, ("%s との merge-base の後の、merge でない %d commit のうち %d は同じ変更が %s に在る（取り込み先が書き換わった）"
                  "ので、範囲を %s から取った"
                  % (base_ref, len(rest), len(rest) - len(own), base_ref,
                     ("%s の前の版の先頭 %s に、PR のブランチが merge で取り込んだ %d 件を merge した commit %s"
                      % (base_ref, old_tip[:7], len(merged), base[:7])) if merged
                     else "%s の前の版の先頭 %s" % (base_ref, old_tip[:7])))


def prep(pr, prior, headless):
    if os.environ.get(ENV_SUBAGENT_MODEL) and not headless:
        raise Stop("subagent-model-env",
                   "環境変数 %s が設定されています。Workflow の段のモデル指定が効かなくなるので、"
                   "unset してから /my-turn-deep を呼び直してください（ヘッドレスの形なら --headless）" % ENV_SUBAGENT_MODEL)
    rc, out = run(["gh", "pr", "view", str(pr), "--json", "headRefOid,baseRefName,url"], timeout=60)
    try:
        info = json.loads(out)
        head_oid, base_ref, url = info["headRefOid"], info["baseRefName"], info["url"]
        m = re.match(r"https?://[^/]+/([^/]+/[^/]+)/pull/\d+", url)
        if rc != 0 or not (head_oid and base_ref and m):
            raise ValueError
        repo_name = m.group(1)
    except (ValueError, KeyError, TypeError):
        raise Stop("gh-failed", "gh pr view %s が失敗したか、読めない答えでした。gh auth status と PR の番号を確かめてください" % pr)
    remote, remote_matched = pr_remote(repo_name)
    # refspec を明示する（single-branch の clone や狭い remote.<名>.fetch でも <remote>/<base> を今にする）
    if git("fetch", remote, "+refs/heads/%s:refs/remotes/%s/%s" % (base_ref, remote, base_ref))[0] != 0:
        raise Stop("fetch-failed", "git fetch %s %s が失敗しました。ネットワークと %s の設定を確かめてください" % (remote, base_ref, remote))
    head = must_git("rev-parse", "HEAD").strip()
    if head != head_oid:
        raise Stop("head-mismatch", "手元の HEAD が PR の先頭と違います。my-turn-prep.py --sync %s で PR の先頭に追いついてから（止まったら、その訳に従ってから）/my-turn-deep を呼び直してください" % pr)
    rc, out = git("merge-base", remote + "/" + base_ref, "HEAD")
    if rc != 0 or not out.strip():
        raise Stop("no-merge-base", "%s/%s と HEAD の共通の祖先が見つかりません（履歴が別、または浅い clone）。git fetch --unshallow などで履歴を取ってください" % (remote, base_ref))
    base, base_note = own_base(remote + "/" + base_ref, out.strip())
    commits = [c for c in must_git("rev-list", "--reverse", "%s..HEAD" % base).split() if c]
    if not commits:
        raise Stop("empty-range", "base..HEAD に commit がありません。見る差分が無いので止めます")

    # 読めない記録（書きかけで切れたなど）で毎回止まらないよう、前の回が無いものとして全部を掘る
    rec, prior_unreadable = None, None
    if prior:
        try:
            rec = load_record(prior)
        except Stop as e:
            prior_unreadable = e.message
    common = must_git("rev-parse", "--git-common-dir").strip()
    # リンクを解いた実パス（top〔--show-toplevel〕と、--quotes が比べる realpath と同じ綴り）
    record_dir = os.path.join(os.path.realpath(common), "attention", "my-turn")
    os.makedirs(record_dir, exist_ok=True)
    top = must_git("rev-parse", "--show-toplevel").strip()
    # 差分のファイルの名前の印は 7 字（前の回の名前 priorRunDiff と合わせる）。段が打つ git show の印（base7）は、
    # 大きいリポジトリでも曖昧にならない長さにする
    head7 = head[:7]
    base7 = must_git("rev-parse", "--short=7", base).strip()

    diff_path = os.path.join(record_dir, "%s..%s.diff" % (base[:7], head7))
    changed, excluded, stat = write_diff(diff_path, base, head, base[:7], head7)
    rc_p, patch = git_bytes("diff", *DIFF_PLAIN, base, head)
    if rc_p != 0:
        raise Stop("git-failed", "git diff %s %s が失敗しました" % (base7, head7))
    patch_id = patch_id_of(patch)
    stat_lines = stat.strip().splitlines()

    prior_head, prior_missing, pb = None, False, None
    if rec is not None:
        ph, pb = rec.get("head"), rec.get("base")
        prior_head = ph if isinstance(ph, str) and ph else None
        prior_missing = bool(prior_head) and not changemap.has_commit(prior_head)
    then_ok = bool(prior_head) and not prior_missing

    # 指紋: 変えたファイルと、段が従う決まりの文書と、前回の記録が読んだ・分けた・根拠にしたファイル
    rule_list = rule_paths(changed, base)
    paths = set(changed) | set(rule_list)
    # 形の違う記録（版 1: checked の中の files・evidence の at）は使い回さず、近道も取らない（その PR は 1 回掘り直す）
    old_shape = rec is not None and rec.get("version") != my_turn_record.RECORD_VERSION
    unknown = old_shape  # 前の回が読んだのに指紋を取れないファイル（repo の外・git dir の中・改行を含む path）が在るか
    if rec is not None and not old_shape:
        for p in record_paths(rec):
            if in_record_dir(p, top, record_dir):
                continue  # 記録のフォルダは commit に無い（差分は patch-id で、thread などは手順 6 で見る）
            n = norm_path(p, top)
            # git dir の中は commit に無い。改行を含む path（名前を 2 つ繋いだ写し違い）も問えない
            if n and not n.startswith(".git/") and "\n" not in n and "\r" not in n:
                paths.add(n)
            else:
                unknown = True
    paths = sorted(paths)
    then = blobs(prior_head, paths) if then_ok else {}
    now = blobs("HEAD", paths)
    fingerprints = {p: {"then": then.get(p), "now": now[p]} for p in paths}
    changed_set = set(changed)

    unchanged = False
    prior_diff = None
    diff_same = False
    if rec is not None:
        # 前の回に結果を返さなかった段が在れば、記録は欠けているので使い回さずに掘り直す。
        # patch-id が同じでも、ノードが読んだ PR の外のファイル（呼ぶ先・決まりの文書）が rebase で変わりうるので、指紋も全部同じときだけ
        if (rec.get("patchId") is not None and rec.get("patchId") == patch_id and record_complete(rec)
                and then_ok and not unknown
                # 変えていないファイルが前の回も今も無い（untracked・ignored）なら、中身を比べられないので同じとみなさない
                and all(f["then"] == f["now"] and (f["then"] is not None or p in changed_set)
                        for p, f in fingerprints.items())):
            unchanged = True
        # 2 本目の差分は、前の head が今の head の祖先で、その間に merge の commit が無いときだけ作る。rebase の後や
        # base を merge した後に作ると、base の側の動きが全部「前の回の後に足された物」に載る（そのときは 1 本目だけで
        # 掘り、使い回しは指紋で決める）
        if (then_ok and not unchanged and prior_head != head
                and git("merge-base", "--is-ancestor", prior_head, head)[0] == 0
                and git("rev-list", "--merges", "-n", "1", "%s..%s" % (prior_head, head)) == (0, "")):
            p7 = prior_head[:7]
            prior_diff = os.path.join(record_dir, "%s..%s.diff" % (p7, head7))
            write_diff(prior_diff, prior_head, head, p7, head7)
        # 差分のファイルを読んだノードは、前の回の差分のファイルと今の物の中身が同じときだけ使い回す
        # （変えたファイルの指紋で比べると、消したファイルで毎回掘り直し、PR から外したファイルを見落とす）
        # 比べは git を 10 回ほど呼ぶので、差分のファイルを読んだノードが在るときだけ（unchanged でも、前の回の後に
        # 来た指摘で近道を取らない回は使い回すので比べる）
        if (then_ok and isinstance(pb, str) and pb and changemap.has_commit(pb)
                and reads_diff(rec, top, record_dir)):
            diff_same = diff_key(pb, prior_head) == diff_key(base, head)

    # 前の回の 1 本目の差分のファイルの名前。差分を読んだノードは、これだけを読んだときに使い回す（前の回の 2 本目の
    # 差分は「その前の回の後に足された物」で、今の回には当てはまらない）
    prior_run_diff = "%s..%s.diff" % (pb[:7], prior_head[:7]) if (then_ok and isinstance(pb, str) and pb) else None
    reuse = (prior_reuse(rec, fingerprints, top, record_dir, diff_same and prior_run_diff)
             if (rec is not None and then_ok and not old_shape) else None)
    stage0_errors = []

    def stage0(name, fn, empty):
        try:
            return fn()
        except Stop as e:
            stage0_errors.append("%s: %s" % (name, e.message))
            return empty

    extra, rules_cut = stage0("rules", lambda: extra_rule_paths(changed, base, rule_list), ([], 0))
    rules = [{"path": p, "show": "git show %s:%s" % (base7, p)} for p in rule_list + extra]
    lines = stage0("lines", lambda: count_lines(base, head),
                   {"byClass": {c: {"added": 0, "deleted": 0, "files": 0} for c in CLASSES}, "testToImpl": None})
    deleted = stage0("deletedTests", lambda: deleted_tests(changed, base, head), {"files": [], "names": [], "uncounted": []})
    signals, signals_cut = stage0("identitySignals", lambda: identity_signals(base, head), ([], 0))
    here = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.abspath(os.path.join(here, "..", "workflows", "my-turn-dig.js"))
    return {
        "ok": True, "pr": pr, "repo": repo_name, "baseRef": base_ref, "remote": remote, "remoteMatched": remote_matched,
        "base": base, "baseNote": base_note, "head": head, "base7": base7, "head7": head7,
        "recordDir": record_dir, "record": os.path.join(record_dir, "%d.json" % pr),
        "diff": diff_path, "priorDiff": prior_diff, "priorHead": prior_head,
        "priorHeadMissing": prior_missing, "priorUnreadable": prior_unreadable, "unchanged": unchanged,
        "diffSame": diff_same, "priorRunDiff": prior_run_diff,
        "patchId": patch_id, "stat": stat_lines[-1] if stat_lines else "",
        "commits": commits, "changed": changed, "excluded": excluded, "rules": rules, "rulesCut": rules_cut,
        "lines": lines, "deletedTests": deleted, "identitySignals": signals, "identitySignalsCut": signals_cut,
        "stage0Errors": stage0_errors,
        "claudeMdChanged": any(p.rsplit("/", 1)[-1] == "CLAUDE.md" for p in changed),
        "fingerprints": {p: file_state(f) for p, f in fingerprints.items()}, "priorReuse": reuse, "scriptPath": script_path,
        # Workflow の写しの照合の段が打つ物（my-turn-dig.js の Quotes。run-python.sh で打つ --quotes --b64）
        "quoteCheck": {"runPython": os.path.join(here, "run-python.sh"), "prep": os.path.abspath(__file__)},
    }


def file_state(f):
    """指紋の組を、Workflow に渡す短い印にする（会話が args に写すので、sha の組を写させない）。
    same: 前の回の head と今の head で同じ中身。moved: 違う（前の回に無く今在るも）。gone: 今の head に無い（前の回は在った）。
    absent: どちらにも無い。前の回の head が無いときは、在るファイルは全部 moved。"""
    if f["then"] is not None and f["then"] == f["now"]:
        return "same"
    if f["now"] is None:
        return "gone" if f["then"] is not None else "absent"
    return "moved"


def record_paths(rec):
    """前の回の記録が読んだ・分けた・根拠にした path の全部: ノードの files と parts と、記録のどこかの根拠
    （ノード・反証・臭いの問いの evidence の path）と、指摘の在り処（priorFindings の at）。"""
    out = []

    def walk(v):
        if isinstance(v, dict):
            p = ev_path(v) if is_evidence(v) else loc_path(v.get("at"))
            if p:
                out.append(p)
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(rec)
    for node in rec.get("nodes") or []:
        if isinstance(node, dict):
            _, read, parts = node_paths(node)
            out += [p for p in read + parts if isinstance(p, str)]
    return out


def in_record_dir(p, top, record_dir):
    # リポジトリの相対の path（main の clone では .git/attention/my-turn/…）も記録のフォルダに数える
    return isinstance(p, str) and abs_path(p, top).startswith(record_dir.replace("\\", "/").rstrip("/") + "/")


def is_record_diff(p, top, record_dir):
    return in_record_dir(p, top, record_dir) and p.strip().endswith(".diff")


def is_url(s):
    return isinstance(s, str) and s.strip().startswith(("http://", "https://"))


def is_evidence(v):
    """根拠の 1 件（{path, line, quote}。my-turn-dig.js の EVIDENCE）か。"""
    return isinstance(v, dict) and isinstance(v.get("path"), str) and "line" in v and "quote" in v


def ev_path(e):
    """根拠の 1 件が指すファイル。頭の commit の印（<base7>: や、使い回したノードの <前の base7>:）は版の印で
    path ではないので外す。URL は None（my-turn-dig.js の pathOf と同じ）。"""
    s = e.get("path").strip() if isinstance(e, dict) and isinstance(e.get("path"), str) else ""
    if not s or is_url(s):
        return None
    return re.sub(r"^[0-9a-f]{7,64}:(?=.)", "", s)


def loc_path(at):
    """文の中の在り処（[<commit の印>:]path:行）の path。前の指摘（priorFindings）の at に使う。URL は None。"""
    s = at.strip() if isinstance(at, str) else ""
    if not s or is_url(s):
        return None
    s = re.sub(r"^[0-9a-f]{7,64}:(?=.*:\d+(-\d+)?$)", "", s)
    return re.sub(r":\d+(-\d+)?$", "", s)


def node_paths(node):
    """ノードの urls と、読んだファイル（files と、根拠〔evidence〕の path）と部品（parts）。

    根拠の行が載るファイルを files に挙げていないノードもあるので、根拠の path も読んだに数える。"""
    ev = [ev_path(e) for e in node.get("evidence") or [] if isinstance(e, dict)]
    return (list(node.get("urls") or []), list(node.get("files") or []) + [p for p in ev if p],
            list(node.get("parts") or []))


def verdict_paths(node):
    """前の回の反証（verdict）の根拠の path。使い回す末端の判定を持ち越すかは、これらのファイルが同じかで決める。"""
    v = node.get("verdict")
    ev = v.get("evidence") if isinstance(v, dict) else None
    return [p for p in (ev_path(e) for e in ev or [] if isinstance(e, dict)) if p]


def reads_diff(rec, top, record_dir):
    """前の回の記録に、記録のフォルダの差分のファイル（*.diff）を読んだ・部品に挙げたノードが在るか。"""
    for node in rec.get("nodes") or []:
        if isinstance(node, dict):
            _, read, parts = node_paths(node)
            if any(is_record_diff(p, top, record_dir) for p in read + parts + verdict_paths(node)):
                return True
    return False


# GitHub の issue・PR・検索の URL。答えが gh で読んだ今の状態に頼っている印（ノードは gh で読んだ物の URL を urls に書く）
LIVE_GITHUB_RE = re.compile(r"^https?://(api\.)?github\.com/(search|repos/[^/]+/[^/]+/(issues|pulls)|[^/]+/[^/]+/(issues|pulls?))([/?#]|$)", re.I)


def is_live_github(u):
    return isinstance(u, str) and bool(LIVE_GITHUB_RE.match(u.strip()))


REUSE_FIELDS = ("key", "question", "resultStatus", "answer", "files", "urls", "evidence", "parts", "premises",
                "children", "verdict", "worth", "findingKind", "locations", "cost", "finePremise")


def prior_reuse(rec, fingerprints, top, record_dir, same_diff):
    """前の回の記録から、使い回せるノードだけを抜いた小さい形（Workflow の args の priorRecord に渡す）。

    記録を丸ごと args に載せると、会話がその全部を Workflow の呼び出しに書き写すことになる。使い回せるかの
    判定は Workflow（my-turn-dig.js の reuse）も同じ条件でもう一度するので、ここは絞るだけ（設計の 7）。
    """
    def is_diff(p):
        return is_record_diff(p, top, record_dir)

    def considered(paths):
        # 記録のフォルダの差分のファイルは、ファイルごとには数えない（same_diff〔本文が今と同じ、前の回の 1 本目の
        # 差分のファイルの名前。無ければ None〕で見る）
        return [p for p in paths if not is_diff(p)]

    def same(p):
        # 記録のフォルダのほかのファイル（thread・justifications）は毎回書き直すので、同じとみなさない
        if not isinstance(p, str) or in_record_dir(p, top, record_dir):
            return False
        n = norm_path(p, top)
        fp = fingerprints.get(n) if n else None
        return bool(fp) and fp["then"] is not None and fp["then"] == fp["now"]

    def same_d(p):
        return bool(same_diff) and posixpath.basename(p.strip().replace("\\", "/")) == same_diff

    nodes = []
    for node in rec.get("nodes") or []:
        if not isinstance(node, dict) or node.get("resultStatus") not in ("leaf", "split", "unverified", "undecided"):
            continue
        urls, read, parts = node_paths(node)
        files = considered(read)
        # 差分のファイルを読んだノードは、files に挙げていないファイルの差分も読んでいる。
        # 差分の本文が前の回と同じときだけ使い回す
        diffs = [f for f in read + parts if is_diff(f)]
        if not (files or diffs) or not all(same(f) for f in files) or not all(same_d(f) for f in diffs):
            continue
        # GitHub の今の状態（open な issue・PR・検索の結果）に頼った答えは使い回さない（my-turn-dig.js の liveGitHub）
        if any(is_live_github(u) for u in urls + [e.get("path") for e in node.get("evidence") or [] if isinstance(e, dict)]):
            continue
        # web のページに頼った答えは、比べた PR の部品のファイルも同じときだけ
        if urls and not all(same(f) for f in considered(parts)):
            continue
        item = {k: node.get(k) for k in REUSE_FIELDS}
        # 反証が根拠にしたファイルが変わったら、判定は持ち越さない（もう一度反証する）
        vread = verdict_paths(node)
        if not all(same(f) for f in considered(vread)) or not all(same_d(f) for f in vread if is_diff(f)):
            item["verdict"] = None
        nodes.append(item)
    return {"version": my_turn_record.RECORD_VERSION, "kind": rec.get("kind"), "purpose": rec.get("purpose"),
            "general": rec.get("general"), "nodes": nodes}


def walk_quotes(node, found):
    """記録の中の根拠（{path, line, quote}）の全部。照合できるのは、行の番号が在り写しが空でない物だけ。"""
    if isinstance(node, dict):
        if is_evidence(node) and isinstance(node.get("quote"), str) and node["quote"].strip():
            found.append(node)
        for v in node.values():
            walk_quotes(v, found)
    elif isinstance(node, list):
        for v in node:
            walk_quotes(v, found)


# Workflow（my-turn-dig.js の CTRL）が段の返した字から外す字。引用も外されて記録に載るので、ファイルの行からも外して比べる
CTRL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def lines_of(text):
    """行に分ける。区切りは \n だけ（splitlines は \f や U+2028 でも切り、エージェントの数える行とずれる）。"""
    text = text.replace("\r\n", "\n")
    return (text[:-1] if text.endswith("\n") else text).split("\n")


class QuoteReader:
    """根拠の 1 件（path・行・写し）を、その版のファイルのその 1 行と比べる。

    path の頭の commit の印は版を選ぶ: base の印なら base、ほかの印は解いた commit（使い回したノードの前の回の
    base）。解けなければ、名前が 16 進の字だけのファイルかもしれないので head の path として読む。記録のフォルダ
    （差分・会話・正当化のファイル）は commit に無いので、ディスクのファイルを読む。"""

    def __init__(self, base, head, top, record_dir):
        self.base, self.head, self.top, self.record_dir = base, head, top, record_dir
        self.cache, self.revs = {}, {}

    def lines(self, rev, path):
        key = (rev, path)
        if key not in self.cache:
            if rev == "disk":
                try:
                    with open(path, encoding="utf-8", errors="replace", newline="") as f:
                        self.cache[key] = lines_of(f.read())
                except OSError:
                    self.cache[key] = None
            else:
                rc, out = git_bytes("show", "%s:%s" % (rev, path))  # テキストの読みは単独の \r も行の区切りに変える
                self.cache[key] = lines_of(out.decode("utf-8", "replace")) if rc == 0 else None
        return self.cache[key]

    def why_missing(self, path, line, quote):
        """合えば None、合わなければ訳。"""
        rev, spec, unresolved = self.head, path.strip(), None
        m = re.match(r"^([0-9a-f]{7,64}):(.+)$", spec)
        if m:
            sha, rest = m.groups()
            if self.base and self.base.startswith(sha):
                rev, spec = self.base, rest
            else:
                if sha not in self.revs:
                    rc_r, out_r = git("rev-parse", "--verify", "--quiet", sha + "^{commit}")
                    self.revs[sha] = out_r.strip() if rc_r == 0 and out_r.strip() else None
                if self.revs[sha]:
                    rev, spec = self.revs[sha], rest
                else:
                    unresolved = sha
        disk = os.path.realpath(abs_path(spec, self.top))
        if rev == self.head and disk.startswith(self.record_dir + os.sep):
            where, lines = "記録のフォルダ", self.lines("disk", disk)
            shown = disk
        else:
            shown = norm_path(spec, self.top)
            if not shown:
                return "場所がリポジトリの外です"
            if rev is None:
                return "base か head が無く、どの版を読むか決まりません"
            where, lines = rev[:7], self.lines(rev, shown)
        if lines is None:
            return ("%s に %s が無い" % (where, shown)
                    + ("（%s は commit の印としても解けない。短い印が曖昧か、force-push の後に消えた）" % unresolved
                       if unresolved else ""))
        if line > len(lines):
            return "行 %d が範囲外（%s は %d 行）" % (line, shown, len(lines))
        if CTRL_RE.sub("", quote.strip()) not in CTRL_RE.sub("", lines[line - 1]):
            return "その行に引用が見つからない（文字が違う）"
        return None


def bad_shape(path, line, quote):
    if not isinstance(path, str) or not path.strip():
        return "path が空です"
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        return "line が 1 以上の整数でない"
    if not isinstance(quote, str) or not quote.strip():
        return "quote が空です"
    return None


def check_quotes(record_path):
    """記録の中の根拠の写しの全部を照合する（報告の後に、反証〔W10〕の根拠も含めて確かめる形）。"""
    rec = load_record(record_path)
    base, head = rec.get("base"), rec.get("head")
    found = []
    walk_quotes(rec, found)
    top = must_git("rev-parse", "--show-toplevel").strip()  # 在り処が作業場の絶対の path でも読む（Workflow の norm と同じ）
    record_dir = os.path.dirname(os.path.realpath(record_path))  # 記録は <記録のフォルダ>/<番号>.json に在る
    reader = QuoteReader(base if isinstance(base, str) and base else None,
                         head if isinstance(head, str) and head else None, top, record_dir)
    checked, missing = 0, []
    for q in found:
        path, line, quote = q["path"], q.get("line"), q["quote"]
        if is_url(path) or line == 0:
            continue  # web のページと行の無い在り処は、照合の外
        checked += 1
        why = bad_shape(path, line, quote) or reader.why_missing(path, line, quote)
        if why:
            missing.append({"path": path, "line": line, "quote": quote, "why": why})
    return {"ok": True, "checked": checked, "missing": missing}


def b64_rows(words):
    """--b64 の引数を行に戻す。1 語目は頭の行の base64、続く語は <id>:<1 件の行の base64>。
    1 行のコマンドにするのは、ヘッドレスの許しの規則 Bash(bash <run-python.sh> <この台本> --quotes --b64 *) に
    当てるため（here-document の複数行は規則に当たらず、dontAsk で拒まれた。PR 2574・2594 のヘッドレスの回）。
    戻せない語と、id が中の行と違う語は、id だけの切れた行にして garbled に数えさせる。id も読めない語は捨てる
    （checked に数えないので、Workflow は数の違う束を丸ごと確かめていない物にする）。"""
    def unb64(word):
        try:
            return base64.b64decode(word, validate=True).decode("utf-8")
        except (binascii.Error, ValueError):
            return None
    rows = [(unb64(words[0]) or "") if words else ""]
    for w in words[1:]:
        m = re.match(r"^(Q\d+):(.*)$", w)
        if not m:
            continue
        row = unb64(m.group(2))
        if row is None or not re.match(r'^\s*\["%s"' % m.group(1), row):
            row = '["%s"' % m.group(1)
        rows.append(row)
    return rows


def check_rows(rows):
    """根拠の行を照合する（Workflow の写しの照合の段が打つ形）。

    1 行目は {workdir, base, head, recordDir}、続く行は 1 件ずつ [id, path, line, quote, sum]。sum が合わない行と
    読めない行は照合せず garbled に数える。id も読めない行と、前の行と同じ id の行は checked に数えない（Workflow は
    数の違う束を丸ごと確かめていない物にする。同じ id を数えると、1 件を重ねて別の 1 件を落とした写しの数が合い、
    落ちた件が照合済みに数わる）。"""
    rows = [l for l in (x.rstrip("\r\n") for x in rows) if l.strip()]
    try:
        head_row = json.loads(rows[0]) if rows else None
    except ValueError:
        head_row = None
    if not isinstance(head_row, dict) or not isinstance(head_row.get("workdir"), str):
        raise Stop("quotes-input", "1 行目が {workdir, base, head, recordDir} の JSON でありません")
    try:
        os.chdir(head_row["workdir"])
    except OSError:
        raise Stop("quotes-input", "作業場 %s に移れません" % head_row["workdir"])
    rc, top = git("rev-parse", "--show-toplevel")
    if rc != 0 or not top.strip():
        raise Stop("quotes-input", "%s は git の作業場でありません" % head_row["workdir"])
    rd = head_row.get("recordDir")
    reader = QuoteReader(head_row.get("base") or None, head_row.get("head") or None, top.strip(),
                         os.path.realpath(rd) if isinstance(rd, str) and rd else os.path.join(top.strip(), ".no-record-dir"))
    checked, missing, garbled, seen = 0, [], [], set()
    for row in rows[1:]:
        try:
            item = json.loads(row)
        except ValueError:
            item = None
        if not (isinstance(item, list) and item and isinstance(item[0], str)):
            m = re.match(r'^\s*\["(Q\d+)"', row)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                checked += 1
                garbled.append(m.group(1))
            continue
        if item[0] in seen:
            continue
        seen.add(item[0])
        checked += 1
        if len(item) != 5 or not isinstance(item[1], str) or not isinstance(item[3], str) or not isinstance(item[4], str) \
                or not isinstance(item[2], int) or fnv32("%s\n%s\n%s\n%s" % (item[0], item[1], item[2], item[3])) != item[4]:
            garbled.append(item[0])
            continue
        why = bad_shape(item[1], item[2], item[3]) or reader.why_missing(item[1], item[2], item[3])
        if why:
            missing.append({"id": item[0], "why": why})
    return {"ok": True, "checked": checked, "missing": missing, "garbled": garbled}


def save_record(out_path, src_path):
    """Workflow の出力のファイル（か記録そのものの JSON）から記録を取り出して、記録のファイルに書く。"""
    try:
        rec = my_turn_record.load_result(src_path)
        my_turn_record.write(out_path, rec)
    except my_turn_record.RecordError as e:
        raise Stop("record", str(e))
    return {"ok": True, "record": out_path, "nodes": len(rec.get("nodes") or []), "head": rec.get("head")}


def check_report(record_path, report_path):
    """記録の台帳の全部の id が報告に在るか、行き先が下書きの件の「path:行」が報告に在るかを照合する。
    読めない・版や形が違うときは (None, 訳)。"""
    try:
        rec = my_turn_record.load_result(record_path)
    except my_turn_record.RecordError as e:
        return None, str(e)
    ledger = rec.get("ledger")
    if not isinstance(ledger, list):
        return None, "記録に台帳（ledger の一覧）がありません"
    try:
        with open(report_path, encoding="utf-8") as f:
            report = f.read()
    except OSError:
        return None, "報告 %s を読めません" % report_path
    missing_ids, missing_locs = [], []
    for item in ledger:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            return None, "台帳に id の無い件があります"
        if not re.search(r"(?<![A-Za-z0-9/._-])%s(?!\d)" % re.escape(item["id"]), report):
            missing_ids.append(item["id"])
        if item.get("route") != "draft":
            continue
        for loc in item.get("locations") or []:
            if not isinstance(loc, dict):
                continue
            path, line = loc.get("path"), loc.get("line")
            if not isinstance(path, str) or not path or not isinstance(line, int) or isinstance(line, bool) or line <= 0:
                continue
            if not re.search(r"%s:%d(?!\d)" % (re.escape(path), line), report):
                missing_locs.append({"id": item["id"], "at": "%s:%d" % (path, line)})
    return {"ok": not missing_ids and not missing_locs, "items": len(ledger),
            "missingIds": missing_ids, "missingLocations": missing_locs}, None


def emit_run(fn):
    """fn の答えを終了の値 0 で出す。Stop で止まったら止まりの形を 1 で出す"""
    try:
        return emit(fn(), 0)
    except Stop as e:
        return emit(stop_obj(e.code, e.message), 1)


def main(argv):
    if argv[:2] == ["--quotes", "--b64"]:
        # 写しの照合の形（--quotes --b64 <頭> <id>:<行> ...）。argparse は --quotes の値に --b64 を取れないので、先に受ける
        return emit_run(lambda: check_rows(b64_rows(argv[2:])))
    ap = argparse.ArgumentParser(prog="my-turn-prep.py", add_help=True)
    ap.add_argument("pr", nargs="?", type=int)
    ap.add_argument("--prior")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--sync", type=int, metavar="PR")
    ap.add_argument("--quotes")
    ap.add_argument("--save-record", nargs=2, metavar=("RECORD", "OUTPUT"))
    ap.add_argument("--check-report", nargs=2, metavar=("RECORD", "REPORT"))
    a = ap.parse_args(argv)
    if sum(x is not None for x in (a.pr, a.sync, a.quotes, a.save_record, a.check_report)) != 1:
        ap.error("PR の番号か --sync か --quotes か --save-record か --check-report のどれか 1 つを渡してください")
    if a.check_report:
        res, why = check_report(os.path.abspath(a.check_report[0]), os.path.abspath(a.check_report[1]))
        if res is None:
            print(why, file=sys.stderr)
            return 2
        return emit(res, 0 if res["ok"] else 1)
    if a.save_record:
        return emit_run(lambda: save_record(os.path.abspath(a.save_record[0]), os.path.abspath(a.save_record[1])))
    prior = os.path.abspath(a.prior) if a.prior else None
    quotes = os.path.abspath(a.quotes) if a.quotes else None
    rc, top = git("rev-parse", "--show-toplevel")
    if rc == 0 and top.strip():
        # 作業場の下位のディレクトリで打っても、差分の本文の pathspec（. と除外）をルートで解く
        os.chdir(top.strip())
    if a.sync is not None:
        return emit_run(lambda: sync(a.sync))
    return emit_run(lambda: check_quotes(quotes) if quotes else prep(a.pr, prior, a.headless))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
