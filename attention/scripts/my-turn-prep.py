#!/usr/bin/env python3
"""/my-turn の「掘る段」の下ごしらえ。PR の差分・規約・指紋を機械で用意し、JSON 1 つで返す。

使い方:
  my-turn-prep.py <PR 番号> [--prior <記録.json>] [--headless]
  my-turn-prep.py --quotes <記録.json>

PR の作業場（cwd）で打つ。判定はしない——材料を集めて Workflow（my-turn-dig.js）へ渡す形に
するだけ。終了の値は、続けてよいとき 0、止めるとき 1（`ok: false`）、使い方の誤りは 2。
設計は attention/docs/my-turn-workflow-design.md の 2・5・7・11。
"""

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import changemap  # noqa: E402 — 差分の取り方の部品（DIFF_SANE）を /what-am-i-doing と共用

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


def run(args, cwd=None, timeout=120, stdin=None, text=True):
    """外部コマンドを 1 回走らせる。(終了の値, 標準出力)。起動できない・時間切れは (-1, "")。text=False はバイトのまま。"""
    enc = {"encoding": "utf-8", "errors": "replace"} if text else {}
    try:
        r = subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, timeout=timeout, **enc)
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


def has_commit(sha):
    return git("cat-file", "-e", sha + "^{commit}")[0] == 0


def record_complete(rec):
    """前の回の記録に、何も返さなかったエージェントが 1 体も無いか（段の一部だけ落ちた回も欠けに数える）。
    W11 は記録を写すだけなので見ない（落ちた回は会話が同じ中身を書く。commands/my-turn.md の手順 15）。"""
    counts = rec.get("counts")
    stages = counts.get("stages") if isinstance(counts, dict) else None
    if not isinstance(stages, dict):
        return False
    return all(isinstance(e, dict) and not e.get("null") for s, e in stages.items() if s != "W11")


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


def rule_paths(changed, base):
    # ルートの .claude/ の下の決まりも Claude Code は読む（AGENTS.md は CLAUDE.md の代わりに使うリポジトリが在る）
    cands = {".claude/AGENTS.md", ".claude/CLAUDE.md"}
    for p in changed:
        parts = p.split("/")[:-1]
        for i in range(len(parts) + 1):
            d = "/".join(parts[:i])
            for name in RULE_NAMES:
                cands.add(d + "/" + name if d else name)
    keep = [p for p, sha in blobs(base, sorted(cands)).items() if sha]
    # ルートが先、あとは階層の辞書順、同じ階層では名前の辞書順
    return sorted(keep, key=lambda p: (p.split("/")[:-1], p.rsplit("/", 1)[-1]))


def prep(pr, prior, headless):
    if os.environ.get(ENV_SUBAGENT_MODEL) and not headless:
        raise Stop("subagent-model-env",
                   "環境変数 %s が設定されています。Workflow の段のモデル指定が効かなくなるので、"
                   "unset してから /my-turn を呼び直してください（ヘッドレスの形なら --headless）" % ENV_SUBAGENT_MODEL)
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
        raise Stop("head-mismatch", "手元の HEAD が PR の先頭と違います。/catchup %s で PR のブランチへ移ってから /my-turn を呼び直してください" % pr)
    rc, out = git("merge-base", remote + "/" + base_ref, "HEAD")
    if rc != 0 or not out.strip():
        raise Stop("no-merge-base", "%s/%s と HEAD の共通の祖先が見つかりません（履歴が別、または浅い clone）。git fetch --unshallow などで履歴を取ってください" % (remote, base_ref))
    base = out.strip()
    commits = [c for c in must_git("rev-list", "--reverse", "%s..HEAD" % base).split() if c]
    if not commits:
        raise Stop("empty-range", "base..HEAD に commit がありません。見る差分が無いので止めます")

    # 読めない記録（W11 の写しが切れたなど）で毎回止まらないよう、前の回が無いものとして全部を掘る
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
        prior_missing = bool(prior_head) and not has_commit(prior_head)
    then_ok = bool(prior_head) and not prior_missing

    # 指紋: 変えたファイルと、段が従う決まりの文書と、前回の記録が読んだ・分けた・根拠にしたファイル
    rule_list = rule_paths(changed, base)
    paths = set(changed) | set(rule_list)
    unknown = False  # 前の回が読んだのに指紋を取れないファイル（repo の外・git dir の中・改行を含む path）が在るか
    if rec is not None:
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
        if (then_ok and isinstance(pb, str) and pb and has_commit(pb)
                and reads_diff(rec, top, record_dir)):
            diff_same = diff_key(pb, prior_head) == diff_key(base, head)

    # 前の回の 1 本目の差分のファイルの名前。差分を読んだノードは、これだけを読んだときに使い回す（前の回の 2 本目の
    # 差分は「その前の回の後に足された物」で、今の回には当てはまらない）
    prior_run_diff = "%s..%s.diff" % (pb[:7], prior_head[:7]) if (then_ok and isinstance(pb, str) and pb) else None
    reuse = (prior_reuse(rec, fingerprints, top, record_dir, diff_same and prior_run_diff)
             if (rec is not None and then_ok) else None)
    rules = [{"path": p, "show": "git show %s:%s" % (base7, p)} for p in rule_list]
    script_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workflows", "my-turn-dig.js"))
    return {
        "ok": True, "pr": pr, "repo": repo_name, "baseRef": base_ref, "remote": remote, "remoteMatched": remote_matched,
        "base": base, "head": head, "base7": base7, "head7": head7,
        "recordDir": record_dir, "record": os.path.join(record_dir, "%d.json" % pr),
        "diff": diff_path, "priorDiff": prior_diff, "priorHead": prior_head,
        "priorHeadMissing": prior_missing, "priorUnreadable": prior_unreadable, "unchanged": unchanged,
        "diffSame": diff_same, "priorRunDiff": prior_run_diff,
        "patchId": patch_id, "stat": stat_lines[-1] if stat_lines else "",
        "commits": commits, "changed": changed, "excluded": excluded, "rules": rules,
        "claudeMdChanged": any(p.rsplit("/", 1)[-1] == "CLAUDE.md" for p in changed),
        "fingerprints": {p: file_state(f) for p, f in fingerprints.items()}, "priorReuse": reuse, "scriptPath": script_path,
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
    """前の回の記録が読んだ・分けた・根拠にした path の全部: ノードの checked.files と parts と、記録のどこかの
    根拠の在り処（ノード・反証・臭いの問い・直しの案の at）。"""
    out = []

    def walk(v):
        if isinstance(v, dict):
            p = at_path(v.get("at"))
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


def at_path(at):
    """根拠の在り処（[<commit の印>:]path:行）の path。URL は None（my-turn-dig.js の pathOfAt と同じ）。"""
    s = at.strip() if isinstance(at, str) else ""
    if not s or s.startswith(("http://", "https://")):
        return None
    s = re.sub(r"^[0-9a-f]{7,64}:(?=.*:\d+(-\d+)?$)", "", s)
    return re.sub(r":\d+(-\d+)?$", "", s)


def node_paths(node):
    """ノードの checked と、読んだファイル（checked.files と、根拠〔evidence〕の在り処の path）と部品（parts）。

    根拠の行が載るファイルを checked.files に挙げていないノードもあるので、根拠の path も読んだに数える。"""
    checked = node.get("checked") if isinstance(node.get("checked"), dict) else {}
    ev = [at_path(e.get("at")) for e in node.get("evidence") or [] if isinstance(e, dict)]
    return checked, list(checked.get("files") or []) + [p for p in ev if p], list(node.get("parts") or [])


def verdict_paths(node):
    """前の回の反証（verdict）の根拠の path。使い回す末端の判定を持ち越すかは、これらのファイルが同じかで決める。"""
    v = node.get("verdict")
    ev = v.get("evidence") if isinstance(v, dict) else None
    return [p for p in (at_path(e.get("at")) for e in ev or [] if isinstance(e, dict)) if p]


def reads_diff(rec, top, record_dir):
    """前の回の記録に、記録のフォルダの差分のファイル（*.diff）を読んだ・部品に挙げたノードが在るか。"""
    for node in rec.get("nodes") or []:
        if isinstance(node, dict):
            _, read, parts = node_paths(node)
            if any(is_record_diff(p, top, record_dir) for p in read + parts + verdict_paths(node)):
                return True
    return False


REUSE_FIELDS = ("key", "question", "resultStatus", "answer", "checked", "evidence", "parts", "premises",
                "children", "verdict")


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
        checked, read, parts = node_paths(node)
        files = considered(read)
        # 差分のファイルを読んだノードは、checked.files に挙げていないファイルの差分も読んでいる。
        # 差分の本文が前の回と同じときだけ使い回す
        diffs = [f for f in read + parts if is_diff(f)]
        if not (files or diffs) or not all(same(f) for f in files) or not all(same_d(f) for f in diffs):
            continue
        if any(re.search(r"(^|[\s;&|(])gh\s", " " + str(c)) for c in checked.get("commands") or []):
            continue
        if (checked.get("urls") or []) and not all(same(f) for f in considered(parts)):
            continue
        item = {k: node.get(k) for k in REUSE_FIELDS}
        # 反証が根拠にしたファイルが変わったら、判定は持ち越さない（もう一度反証する）
        vread = verdict_paths(node)
        if not all(same(f) for f in considered(vread)) or not all(same_d(f) for f in vread if is_diff(f)):
            item["verdict"] = None
        nodes.append(item)
    return {"kind": rec.get("kind"), "general": rec.get("general"), "nodes": nodes}


AT_RE = re.compile(r"^(.+):(\d+)(?:-(\d+))?$")


def walk_quotes(node, found):
    if isinstance(node, dict):
        if isinstance(node.get("at"), str) and isinstance(node.get("quote"), str) and node["quote"].strip():
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


def check_quotes(record_path):
    rec = load_record(record_path)
    base, head = rec.get("base"), rec.get("head")
    base = base if isinstance(base, str) and base else None
    head = head if isinstance(head, str) and head else None
    found = []
    walk_quotes(rec, found)
    cache, revs = {}, {}  # revs: commit の印 → 解いた sha（解けなければ None）
    checked, missing = 0, []
    top = must_git("rev-parse", "--show-toplevel").strip()  # 在り処が作業場の絶対の path でも読む（Workflow の norm と同じ）
    record_dir = os.path.dirname(os.path.realpath(record_path))  # 記録は <記録のフォルダ>/<番号>.json に在る
    for q in found:
        at, quote = q["at"], q["quote"].strip()
        if at.startswith(("http://", "https://")):
            continue
        checked += 1

        def miss(why):
            missing.append({"at": at, "quote": q["quote"], "why": why})

        rev, spec, unresolved = head, at, None
        m = re.match(r"^([0-9a-f]{7,64}):(.*)$", at)
        # 残りが path:行 でなければ、名前が 16 進の字だけのファイル（cafebabe:1）なので head の path として読む
        if m and AT_RE.match(m.group(2)):
            sha, rest = m.groups()
            # <base7>:path は base の版。使い回したノードは前の回の base の印を持つので、ほかの commit の印も解く
            if base and base.startswith(sha):
                rev, spec = base, rest
            else:
                if sha not in revs:
                    rc_r, out_r = git("rev-parse", "--verify", "--quiet", sha + "^{commit}")
                    revs[sha] = out_r.strip() if rc_r == 0 and out_r.strip() else None
                if revs[sha]:
                    rev, spec = revs[sha], rest
                else:
                    unresolved = sha  # 名前が 16 進の字だけのファイルかもしれないので、head の path としても読む
        mm = AT_RE.match(spec)
        if not mm:
            miss("場所の書き方が読めません（path:行 か path:開始-終了）")
            continue
        start = int(mm.group(2))
        end = int(mm.group(3)) if mm.group(3) else start
        if end < start or start < 1:
            miss("行の範囲が不正です")
            continue
        raw = mm.group(1)
        disk = os.path.realpath(abs_path(raw, top))
        on_disk = rev == head and disk.startswith(record_dir + os.sep)
        if on_disk:
            # 記録のフォルダ（差分・会話・正当化のファイル）は commit に無いので、ファイルを読む
            path, key = disk, ("disk", disk)
            if key not in cache:
                try:
                    with open(disk, encoding="utf-8", errors="replace", newline="") as f:
                        cache[key] = lines_of(f.read())
                except OSError:
                    cache[key] = None
        else:
            path = norm_path(raw, top)
            if not path:
                miss("場所がリポジトリの外です")
                continue
            if rev is None:
                miss("記録に base か head が無く、どの版を読むか決まりません")
                continue
            key = (rev, path)
            if key not in cache:
                rc, out = git_bytes("show", "%s:%s" % (rev, path))  # テキストの読みは単独の \r も行の区切りに変える
                cache[key] = lines_of(out.decode("utf-8", "replace")) if rc == 0 else None
        lines = cache[key]
        if lines is None:
            miss("%s に %s が無い" % ("記録のフォルダ" if on_disk else rev[:7], path)
                 + ("（%s は commit の印としても解けない。短い印が曖昧か、force-push の後に消えた）" % unresolved if unresolved else ""))
        elif end > len(lines):
            miss("行 %d が範囲外（%s は %d 行）" % (end, path, len(lines)))
        elif CTRL_RE.sub("", quote) not in CTRL_RE.sub("", "\n".join(lines[start - 1:end])):
            miss("その行に引用が見つからない（文字が違う）")
    return {"ok": True, "checked": checked, "missing": missing}


def main(argv):
    ap = argparse.ArgumentParser(prog="my-turn-prep.py", add_help=True)
    ap.add_argument("pr", nargs="?", type=int)
    ap.add_argument("--prior")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--quotes")
    a = ap.parse_args(argv)
    if (a.quotes is None) == (a.pr is None):
        ap.error("PR の番号か --quotes のどちらか 1 つを渡してください")
    prior = os.path.abspath(a.prior) if a.prior else None
    quotes = os.path.abspath(a.quotes) if a.quotes else None
    rc, top = git("rev-parse", "--show-toplevel")
    if rc == 0 and top.strip():
        # 作業場の下位のディレクトリで打っても、差分の本文の pathspec（. と除外）をルートで解く
        os.chdir(top.strip())
    try:
        if quotes:
            return emit(check_quotes(quotes), 0)
        return emit(prep(a.pr, prior, a.headless), 0)
    except Stop as e:
        return emit(stop_obj(e.code, e.message), 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
