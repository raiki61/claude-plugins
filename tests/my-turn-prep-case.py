#!/usr/bin/env python3
"""attention/scripts/my-turn-prep.py と my-turn-headless.py を、一時の git リポジトリと偽の gh・claude で動かして確かめる。

GitHub にも本物の claude にも触れない。gh と claude は一時の場所の bin/ に置いた偽物（PATH の先頭）。git だけ本物で、
origin は一時の bare リポジトリ。cwd はこのリポジトリではなく一時の作業場を渡す（本体に git を打たない）。
ケース名を引数で選び、通れば `<名前>_OK` を出す。知らない名前は「使い方」で落ちる。"""

import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
PREP = str(ROOT / "attention" / "scripts" / "my-turn-prep.py")
HEADLESS = str(ROOT / "attention" / "scripts" / "my-turn-headless.py")
GIT = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
       "-c", "init.defaultBranch=main", "-c", "core.autocrlf=false"]
POSIX = os.name != "nt"  # 偽の gh・claude は shebang の台本なので、Windows では走らせない


def git(repo, *args, stdin=None):
    r = subprocess.run([*GIT, "-C", repo, *args], check=True, capture_output=True, input=stdin,
                       encoding="utf-8", errors="replace")
    return r.stdout.strip()


def write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def commit(repo, msg, **files):
    for rel, text in files.items():
        write(repo, rel.replace("__", "/").replace("_DOT_", "."), text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def check(cond, msg):
    if not cond:
        print("FAIL: " + msg)
        sys.exit(1)


def fake(path, body):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!%s\n%s" % (sys.executable, body))
    os.chmod(path, 0o755)


FAKE_GH = """import os, sys
sys.stdout.write(open(os.environ["FAKE_GH_JSON"], encoding="utf-8").read())
sys.exit(int(os.environ.get("FAKE_GH_RC", "0")))
"""
FAKE_CLAUDE = """import json, os, sys
d = os.environ["FAKE_CLAUDE_DIR"]
json.dump({"argv": sys.argv[1:], "env": sorted(os.environ), "cwd": os.getcwd(),
           "bgWait": os.environ.get("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS")}, open(os.path.join(d, "seen.json"), "w"))
sys.stdout.write(open(os.path.join(d, "canned.json"), encoding="utf-8").read())
sys.exit(int(os.environ.get("FAKE_CLAUDE_RC", "0")))
"""


class Env:
    """repo（作業場）・origin（bare）・偽の gh を持つ一時の組。main に base の commit が 1 つ入っている。"""

    def __init__(self, tmp):
        self.tmp = tmp
        self.origin = os.path.join(tmp, "origin.git")
        self.repo = os.path.join(tmp, "r")
        self.bin = os.path.join(tmp, "bin")
        self.work = os.path.join(tmp, "work")
        os.makedirs(self.bin)
        os.makedirs(self.work)
        subprocess.run([*GIT, "init", "-q", "--bare", self.origin], check=True)
        os.makedirs(self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "remote", "add", "origin", self.origin)
        self.gh_json = os.path.join(tmp, "gh.json")
        fake(os.path.join(self.bin, "gh"), FAKE_GH)
        self.pr = 7

    def base_commit(self, **files):
        c = commit(self.repo, "base", **files)
        git(self.repo, "push", "-q", "origin", "main")
        return c

    def set_gh(self, head, base="main", raw=None):
        with open(self.gh_json, "w", encoding="utf-8") as f:
            f.write(raw if raw is not None else json.dumps(
                {"headRefOid": head, "baseRefName": base, "url": "https://github.com/o/r/pull/%d" % self.pr}))

    def env(self, **extra):
        e = dict(os.environ)
        e.pop("CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL", None)
        e["PATH"] = self.bin + os.pathsep + e["PATH"]
        e["FAKE_GH_JSON"] = self.gh_json
        e.update(extra)
        return e

    def prep(self, *args, env=None, script=None, cwd=None, stdin=None):
        r = subprocess.run([sys.executable, script or PREP, *args], cwd=cwd or self.repo, env=env or self.env(),
                           capture_output=True, encoding="utf-8", errors="replace", input=stdin)
        try:
            return r.returncode, json.loads(r.stdout)
        except ValueError:
            print("FAIL: 出力が JSON でない: rc=%s out=%r err=%r" % (r.returncode, r.stdout, r.stderr))
            sys.exit(1)


def with_env(fn):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        fn(Env(tmp))


def feature(e, **files):
    """main の base から feat を切り、files を 1 commit。set_gh まで済ませて head を返す。"""
    git(e.repo, "switch", "-q", "-c", "feat")
    head = commit(e.repo, "feat change", **files)
    e.set_gh(head)
    return head


def case_env_stop():
    def body(e):
        e.base_commit(a_DOT_txt="a\n")
        head = feature(e, b_DOT_txt="b\n")
        env = e.env(CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL="haiku")
        rc, o = e.prep("7", env=env)
        check(rc == 1 and o["ok"] is False and o["stop"] == "subagent-model-env", "環境変数で止まらない %r" % o)
        check(o["message"], "message が空")
        rc, o = e.prep("7", "--headless", env=env)
        check(rc == 0 and o["ok"] and o["head"] == head, "--headless でも止まった %r" % o)
        # 空の値は止めない
        rc, o = e.prep("7", env=e.env(CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL=""))
        check(rc == 0, "空の値で止まった")
    if not POSIX:
        return skip("env-stop")
    with_env(body)


def skip(name):
    print("windows では偽の gh を走らせないので見送り")
    return None


def case_stops():
    def body(e):
        base = e.base_commit(a_DOT_txt="a\n")
        head = feature(e, b_DOT_txt="b\n")
        # head の不一致
        e.set_gh("0" * 40)
        rc, o = e.prep("7")
        check(rc == 1 and o["stop"] == "head-mismatch" and "--sync 7" in o["message"], "head-mismatch %r" % o)
        # gh の失敗・読めない答え
        e.set_gh(head, raw="not json")
        rc, o = e.prep("7")
        check(rc == 1 and o["stop"] == "gh-failed", "gh-failed(junk) %r" % o)
        rc, o = e.prep("7", env=e.env(FAKE_GH_RC="1"))
        check(rc == 1 and o["stop"] == "gh-failed", "gh-failed(rc) %r" % o)
        e.set_gh(head)
        # 空の範囲: base と同じ commit に居る
        git(e.repo, "switch", "-q", "main")
        e.set_gh(base)
        rc, o = e.prep("7")
        check(rc == 1 and o["stop"] == "empty-range", "empty-range %r" % o)
        # fetch の失敗: origin の向き先を無い所へ
        git(e.repo, "switch", "-q", "feat")
        e.set_gh(head)
        git(e.repo, "remote", "set-url", "origin", os.path.join(e.tmp, "nowhere.git"))
        rc, o = e.prep("7")
        check(rc == 1 and o["stop"] == "fetch-failed", "fetch-failed %r" % o)
        git(e.repo, "remote", "set-url", "origin", e.origin)
        # 共通の祖先なし: 履歴の別の孤児ブランチ
        git(e.repo, "switch", "-q", "--orphan", "lone")
        h2 = commit(e.repo, "lone", z_DOT_txt="z\n")
        e.set_gh(h2)
        rc, o = e.prep("7")
        check(rc == 1 and o["stop"] == "no-merge-base", "no-merge-base %r" % o)
        # 使い方の誤りは 2
        r = subprocess.run([sys.executable, PREP], cwd=e.repo, env=e.env(), capture_output=True)
        check(r.returncode == 2, "引数なしが 2 でない")
    if not POSIX:
        return skip("stops")
    with_env(body)


def case_diff():
    def body(e):
        base = e.base_commit(a_DOT_txt="a\n", yarn_DOT_lock="lock0\n", sub__c_DOT_txt="c\n")
        git(e.repo, "switch", "-q", "-c", "feat")
        c1 = commit(e.repo, "first", a_DOT_txt="a\nA2\n", yarn_DOT_lock="lock1\nlock2\n")
        # 日本語の名のファイル: 差分のファイルの stat と本文の見出しも、変えたファイルの一覧と同じ綴りで載る
        head = commit(e.repo, "second", sub__d_DOT_txt="d\n", Cargo_DOT_lock="cargo\n", 設計_DOT_md="j\n")
        e.set_gh(head)
        rc, o = e.prep("7")
        check(rc == 0 and o["ok"], "ok でない %r" % o)
        check(o["pr"] == 7 and o["repo"] == "o/r" and o["baseRef"] == "main", "pr/repo/baseRef %r" % o)
        check(o["base"] == base and o["head"] == head, "base/head")
        check(o["base7"] == base[:7] and o["head7"] == head[:7], "7 桁")
        check(o["commits"] == [c1, head], "commits %r" % o["commits"])
        check(o["changed"] == sorted(["Cargo.lock", "a.txt", "sub/d.txt", "yarn.lock", "設計.md"]), "changed %r" % o["changed"])
        check(sorted(o["excluded"]) == ["Cargo.lock", "yarn.lock"], "excluded %r" % o["excluded"])
        check(o["stat"].strip().startswith("5 files changed"), "stat %r" % o["stat"])
        common = os.path.abspath(os.path.join(e.repo, git(e.repo, "rev-parse", "--git-common-dir")))
        want_dir = os.path.join(common, "attention", "my-turn")
        check(os.path.realpath(o["recordDir"]) == os.path.realpath(want_dir), "recordDir %r" % o["recordDir"])
        check(o["record"] == os.path.join(o["recordDir"], "7.json"), "record")
        check(o["diff"] == os.path.join(o["recordDir"], "%s..%s.diff" % (base[:7], head[:7])), "diff 名")
        check(o["priorDiff"] is None and o["priorHead"] is None and o["priorHeadMissing"] is False
              and o["unchanged"] is False, "prior 系の既定")
        check(o["patchId"] and len(o["patchId"]) == 40, "patchId")
        check(o["scriptPath"].replace("\\", "/").endswith("workflows/my-turn-dig.js")
              and os.path.isabs(o["scriptPath"]), "scriptPath")
        # 指紋は、変えたファイルと決まりの文書の、短い印（sha の組は args に写させない）
        check(set(o["fingerprints"]) == set(o["changed"]) | {r["path"] for r in o["rules"]}, "fingerprints の鍵 %r" % o["fingerprints"])
        check(o["fingerprints"]["a.txt"] == "moved", "指紋 a.txt（前の回が無いので moved）")
        text = open(o["diff"], encoding="utf-8").read()
        i_c, i_s, i_d = text.index("# commits "), text.index("# stat\n"), text.index("# diff -U10 (lock files left out: ")
        check(i_c == 0 and i_c < i_s < i_d, "見出しの順")
        check(text.startswith("# commits %s..%s\n" % (base[:7], head[:7])), "commits 見出し")
        check("%s second" % head in text and "%s first" % c1 in text, "log の行")
        check(text.index("first") < text.index("second"), "log が古い順でない")
        check("left out: Cargo.lock, yarn.lock)" in text or "left out: yarn.lock, Cargo.lock)" in text, "除外の一覧")
        stat, body_ = text[i_s:i_d], text[i_d:]
        check("yarn.lock" in stat and "Cargo.lock" in stat, "lock が stat に無い")
        check("lock2" not in body_ and "cargo" not in body_, "lock の本文が残った")
        check("+A2" in body_ and "+d" in body_, "本文に通常の差分が無い")
        jp = "設計.md"  # 比べるのはファイルの名前（機械の値）で、人の文ではない
        check(jp in stat and "diff --git a/%s b/%s" % (jp, jp) in body_ and "\\350" not in text, "日本語の path が書き換わった")
        # 下位のディレクトリで打っても、本文はリポジトリ全体の差分で、lock も外れる
        rc, o2 = e.prep("7", cwd=os.path.join(e.repo, "sub"))
        body2 = open(o2["diff"], encoding="utf-8").read().split("# diff -U10 ", 1)[1]
        check(rc == 0 and "+A2" in body2 and "+d" in body2 and "lock2" not in body2, "下位のディレクトリで本文が欠けた")
        # PR のリポジトリ（o/r）を指す remote が無ければ origin で、見つからなかったと返す
        check(o["remote"] == "origin" and o["remoteMatched"] is False, "remote の既定 %r" % o.get("remote"))
        # push の URL だけが o/r を指す remote は選ばない（base は fetch の側から取る）
        git(e.repo, "remote", "set-url", "--push", "origin", "https://example.com/o/r.git")
        rc, o_push = e.prep("7")
        check(rc == 0 and o_push["remoteMatched"] is False, "push の URL で選んだ %r" % o_push.get("remoteMatched"))
        # fork の作業場: origin は別で、upstream が o/r を指す → upstream の base で範囲を取る
        up = os.path.join(e.tmp, "o", "r.git")
        subprocess.run([*GIT, "clone", "-q", "--bare", e.origin, up], check=True)
        git(e.repo, "remote", "add", "upstream", up)
        rc, o3 = e.prep("7")
        check(rc == 0 and o3["remote"] == "upstream" and o3["remoteMatched"] is True and o3["base"] == base,
              "upstream の remote %r" % {k: o3.get(k) for k in ("remote", "remoteMatched", "base")})
        # 狭い fetch の設定（upstream/main を追わない）でも、refspec を明示するので upstream/main が取れる
        git(e.repo, "config", "remote.upstream.fetch", "+refs/heads/none:refs/remotes/upstream/none")
        git(e.repo, "update-ref", "-d", "refs/remotes/upstream/main")
        rc, o4 = e.prep("7")
        check(rc == 0 and o4["ok"] and o4["base"] == base, "狭い fetch の設定 %r" % o4)
        # 使う人の git の設定（外の diff のツール・色）で差分の本文と patch-id が変わらない
        git(e.repo, "config", "diff.external", "false")
        git(e.repo, "config", "color.ui", "always")
        rc, o5 = e.prep("7")
        body5 = open(o5["diff"], encoding="utf-8").read() if rc == 0 else ""
        check(rc == 0 and o5["patchId"] == o["patchId"] and "+A2" in body5 and "\x1b[" not in body5,
              "git の設定で差分が変わった %r" % o5)
        # lock file の名前を変えた（中身は base と同じ）: 古い path の削除も本文から外れる
        os.remove(os.path.join(e.repo, "yarn.lock"))
        moved = commit(e.repo, "move lock", app__yarn_DOT_lock="lock0\n")
        e.set_gh(moved)
        rc, o6 = e.prep("7")
        body6 = open(o6["diff"], encoding="utf-8").read().split("# diff -U10 ", 1)[1] if rc == 0 else ""
        check(rc == 0 and sorted(o6["excluded"]) == ["Cargo.lock", "app/yarn.lock", "yarn.lock"] and "lock0" not in body6,
              "名前を変えた lock file %r" % o6.get("excluded"))
        # 改行の字だけの直し（LF→CRLF）も本文に載る（テキストの読みは \r\n を \n に変え、- と + が同じ行に見える）
        crlf = commit(e.repo, "crlf", sub__d_DOT_txt="d\r\n")
        e.set_gh(crlf)
        rc, o7 = e.prep("7")
        with open(o7["diff"], encoding="utf-8", newline="") as f:
            body7 = f.read().split("# diff -U10 ", 1)[1] if rc == 0 else ""
        check(rc == 0 and "+d\r\n" in body7, "CRLF の直しが本文から消えた %r" % body7[-200:])
    if not POSIX:
        return skip("diff")
    with_env(body)


def case_rules():
    def body(e):
        base = e.base_commit(CLAUDE_DOT_md="root rules\n", REVIEW_DOT_md="root review\n",
                             pkg__CLAUDE_DOT_md="pkg rules\n", pkg__x_DOT_py="x\n", other__y_DOT_py="y\n",
                             other__REVIEW_DOT_md="other review\n", pkg__AGENTS_DOT_md="pkg agents\n",
                             _DOT_claude__AGENTS_DOT_md="dot agents\n")
        feature(e, pkg__x_DOT_py="x2\n", newdir__CLAUDE_DOT_md="new rules\n", newdir__z_DOT_py="z\n")
        rc, o = e.prep("7")
        check(rc == 0, "ok でない %r" % o)
        paths = [r["path"] for r in o["rules"]]
        check(paths == ["CLAUDE.md", "REVIEW.md", ".claude/AGENTS.md", "pkg/AGENTS.md", "pkg/CLAUDE.md"],
              "rules %r" % paths)
        check(o["rules"][4]["show"] == "git show %s:pkg/CLAUDE.md" % base[:7], "show %r" % o["rules"][4])
        check(o["claudeMdChanged"] is True, "claudeMdChanged")
    if not POSIX:
        return skip("rules")
    with_env(body)


def case_prior():
    def body(e):
        e.base_commit(a_DOT_txt="a\n", b_DOT_txt="b\n", sub__r_DOT_txt="r\n")
        git(e.repo, "switch", "-q", "-c", "feat")
        c1 = commit(e.repo, "one", a_DOT_txt="a\nA\n")
        e.set_gh(c1)
        rc, o1 = e.prep("7")
        check(rc == 0, "1 回目 %r" % o1)
        rec = os.path.join(e.tmp, "rec.json")

        def write_rec(**kw):
            # 前の回の 1 本目の差分のファイル（<前の base>..<前の head>.diff）と、2 本目の差分のファイル
            dn = "%s..%s.diff" % (o1["base"][:7], kw.get("head", c1)[:7])
            # odd: repo の外・改行を含む path を読んだノード（指紋を取れないので、近道を取らない）
            odd = [{"files": [os.path.join(e.repo, "sub", "r.txt"), "./b.txt", "/outside/zzz", "../outside.py", "a.txt\nb.txt"],
                    "parts": ["a.txt"]}] if kw.pop("odd", False) else [{"parts": ["a.txt"]}]
            d = {"version": 3, "head": c1, "base": o1["base"], "patchId": o1["patchId"],
                 "nodes": odd + [
                           {"key": "same file", "resultStatus": "leaf", "answer": "A", "files": ["sub/r.txt"], "urls": []},
                           {"key": "url moved", "resultStatus": "leaf", "files": ["sub/r.txt"], "urls": ["https://x"], "parts": ["b.txt"]},
                           # GitHub の issue・PR・検索に頼った答えは、ファイルが同じでも使い回さない（gh で読んだ今の状態）
                           {"key": "gh issue", "resultStatus": "leaf", "files": ["sub/r.txt"], "urls": ["https://github.com/o/r/issues/3"]},
                           {"key": "gh search", "resultStatus": "leaf", "files": ["sub/r.txt"], "urls": [],
                            "evidence": [{"path": "https://api.github.com/search/issues?q=x", "line": 0, "quote": "q"}]},
                           # 記録のフォルダの差分は数えず、thread は毎回書き直すので同じとみなさない
                           {"key": "diff and same", "resultStatus": "leaf", "files": [os.path.join(o1["recordDir"], dn), "sub/r.txt"], "urls": []},
                           {"key": "second diff", "resultStatus": "leaf", "files": [os.path.join(o1["recordDir"], "zzzzzzz.." + dn.split("..")[1]), "sub/r.txt"], "urls": []},
                           {"key": "thread", "resultStatus": "leaf", "files": [os.path.join(o1["recordDir"], "7-thread.md"), "sub/r.txt"], "urls": []},
                           {"key": "rel diff", "resultStatus": "leaf", "files": [".git/attention/my-turn/" + dn, "sub/r.txt"], "urls": []},
                           {"key": "diff only", "resultStatus": "leaf", "files": [os.path.join(o1["recordDir"], dn)], "urls": []},
                           # parts に差分のファイルを挙げた URL のノードも、差分が同じときだけ
                           {"key": "url diff part", "resultStatus": "leaf", "files": [" sub/r.txt"], "urls": ["https://x"],
                            "parts": [" " + os.path.join(o1["recordDir"], dn)]}],
                 "kind": "K", "general": {"text": "G"},
                 "counts": {"stages": {"W6": {"started": 2, "returned": 2, "null": []}}, "allNull": []}}
            d.update(kw)
            with open(rec, "w", encoding="utf-8") as f:
                json.dump(d, f)

        # 差分が変わった: 2 つ目の差分が出る
        c2 = commit(e.repo, "two", a_DOT_txt="a\nA\nB\n", b_DOT_txt="b2\n")
        e.set_gh(c2)
        write_rec(odd=True)
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and not o["unchanged"] and not o["priorHeadMissing"], "prior 通常 %r" % o)
        check(o["priorHead"] == c1, "priorHead")
        check(o["priorDiff"] == os.path.join(o["recordDir"], "%s..%s.diff" % (c1[:7], c2[:7])), "priorDiff 名")
        t = open(o["priorDiff"], encoding="utf-8").read()
        check(t.startswith("# commits %s..%s\n" % (c1[:7], c2[:7])) and "+B" in t and "+A\n" not in t.split("# diff")[1],
              "2 つ目の差分の中身")
        fps = o["fingerprints"]
        check(set(fps) == {"a.txt", "b.txt", "sub/r.txt"}, "指紋の鍵 %r" % sorted(fps))
        check(fps["a.txt"] == "moved", "a.txt の指紋 %r" % fps)
        check(fps["sub/r.txt"] == "same", "絶対パスの正規化")
        check(fps["b.txt"] == "moved", "b.txt の指紋")
        ru = o["priorReuse"]
        # 差分を読んだノードは、差分の本文が変わったので使い回さない
        check(o["diffSame"] is False, "diffSame %r" % o["diffSame"])
        check(ru and ru["kind"] == "K" and [n["key"] for n in ru["nodes"]] == ["same file"], "使い回せるノードだけを抜く %r" % ru)
        # 根拠（evidence の path）に挙げただけのファイルも読んだ物に数える（<commit>: の頭は外す）
        # （sub/r.txt は PR の外で、根拠にしか挙げていないので、指紋に在るのは根拠を数えた印）
        write_rec(nodes=[{"key": "ev", "resultStatus": "leaf", "files": [], "evidence": [{"path": "b.txt", "line": 1, "quote": "b"}]},
                         {"key": "ev hex", "resultStatus": "leaf", "files": [],
                          "evidence": [{"path": c1[:7] + ":b.txt", "line": 1, "quote": "b"}]},
                         {"key": "ev same", "resultStatus": "leaf", "files": [], "evidence": [{"path": "sub/r.txt", "line": 1, "quote": "r"}]},
                         {"key": "ev same hex", "resultStatus": "leaf", "files": [],
                          "evidence": [{"path": c1[:7] + ":sub/r.txt", "line": 1, "quote": "r"}]}])
        rc, o = e.prep("7", "--prior", rec)
        check("sub/r.txt" in o["fingerprints"] and [n["key"] for n in o["priorReuse"]["nodes"]] == ["ev same", "ev same hex"],
              "根拠の path の指紋と使い回し %r %r" % (sorted(o["fingerprints"]), o["priorReuse"]))
        # 反証（verdict）の根拠のファイルが変わった末端は、使い回すが判定は持ち越さない
        v = {"verdict": "stands", "reason": "r"}
        write_rec(nodes=[{"key": "v moved", "resultStatus": "leaf", "files": ["sub/r.txt"],
                          "verdict": {**v, "evidence": [{"path": "b.txt", "line": 1, "quote": "b"}]}},
                         {"key": "v same", "resultStatus": "leaf", "files": ["sub/r.txt"],
                          "verdict": {**v, "evidence": [{"path": "sub/r.txt", "line": 1, "quote": "r"}]}}])
        rc, o = e.prep("7", "--prior", rec)
        got = {n["key"]: n["verdict"] for n in o["priorReuse"]["nodes"]}
        check(got.get("v moved", 0) is None and (got.get("v same") or {}).get("verdict") == "stands", "反証の根拠と判定 %r" % got)
        # 同じ patch-id: 空 commit を足す → unchanged、2 つ目の差分なし
        c3 = commit(e.repo, "empty")
        e.set_gh(c3)
        write_rec(head=c2, patchId=o["patchId"])
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and o["unchanged"] is True and o["priorDiff"] is None and o["priorHead"] == c2, "unchanged %r" % o)
        # 本文が同じでも、差分のファイルの commit の一覧が育ったので、差分を読んだノードは使い回さない
        check(o["diffSame"] is False and [n["key"] for n in o["priorReuse"]["nodes"]] == ["same file", "url moved"],
              "commit の一覧が育ったときの使い回し %r" % o["priorReuse"])
        # 同じ head で記録が欠けていた: 差分のファイルが同じなので、差分を読んだノードも使い回す
        # （main の clone の相対の path も差分のファイル。差分だけを読んだノードも）
        write_rec(head=c3, patchId=o["patchId"], counts={"stages": {"W6": {"null": ["W6 a"]}}, "allNull": []})
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False and o["diffSame"] is True and [n["key"] for n in o["priorReuse"]["nodes"]]
              == ["same file", "url moved", "diff and same", "rel diff", "diff only", "url diff part"],
              "差分が同じときの使い回し %r" % o["priorReuse"])
        # PR から外した（base に戻した）ファイルの差分も、差分を読んだノードの使い回しを止める
        git(e.repo, "switch", "-q", "-c", "rv")
        git(e.repo, "checkout", o["base"], "--", "b.txt")
        crv = commit(e.repo, "revert b")
        e.set_gh(crv)
        write_rec(head=c3, patchId=o["patchId"])
        rc, o_rv = e.prep("7", "--prior", rec)
        check("b.txt" not in o_rv["changed"] and o_rv["diffSame"] is False
              and [n["key"] for n in o_rv["priorReuse"]["nodes"]] == ["same file"],  # url moved は部品の b.txt が動いた
              "戻したファイルで差分のノードを使い回す %r" % o_rv)
        # 消したファイル（指紋が無い）が在っても、差分のファイルが同じなら差分のノードを使い回す
        os.remove(os.path.join(e.repo, "b.txt"))
        cdel = commit(e.repo, "drop b")
        e.set_gh(cdel)
        rc, o_d = e.prep("7")
        write_rec(head=cdel, patchId=o_d["patchId"], counts={"stages": {"W6": {"null": ["W6 a"]}}, "allNull": []})
        rc, o_d = e.prep("7", "--prior", rec)
        check(o_d["unchanged"] is False and o_d["diffSame"] is True and "b.txt" in o_d["changed"]
              and "diff only" in [n["key"] for n in o_d["priorReuse"]["nodes"]],
              "消したファイルで差分のノード %r" % o_d)
        # lock file だけの直しは本文に載らないが、差分のファイルの stat に載るので使い回さない
        write_rec(head=cdel, patchId=o_d["patchId"])
        write(e.repo, "yarn.lock", "lock\n")  # 件名は同じまま、lock file を足す
        git(e.repo, "add", "-A")
        git(e.repo, "commit", "-q", "--amend", "-m", "drop b")
        clk = git(e.repo, "rev-parse", "HEAD")
        e.set_gh(clk)
        write_rec(head=cdel, patchId=o_d["patchId"], counts={"stages": {"W6": {"null": ["W6 a"]}}, "allNull": []})
        rc, o_d = e.prep("7", "--prior", rec)
        check(o_d["diffSame"] is False, "lock file だけの直しで diffSame %r" % o_d["diffSame"])
        git(e.repo, "switch", "-q", "feat")
        e.set_gh(c3)
        # base を merge しても patch-id が同じ
        git(e.repo, "switch", "-q", "main")
        commit(e.repo, "main moves", m_DOT_txt="m\n")
        git(e.repo, "push", "-q", "origin", "main")
        git(e.repo, "switch", "-q", "feat")
        c4 = commit(e.repo, "x")  # 本物の merge は下
        git(e.repo, "merge", "-q", "--no-edit", "main")
        c5 = git(e.repo, "rev-parse", "HEAD")
        e.set_gh(c5)
        # 前の回の後に base を merge した: 前の head は祖先だが、base の側の動きを 2 本目の差分に載せない
        write_rec(head=c4, patchId="different")
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and o["unchanged"] is False and o["priorDiff"] is None, "merge の後の 2 本目 %r" % o)
        write_rec(head=c3, patchId=None)
        rc, o = e.prep("7")
        write_rec(head=c3, patchId=o["patchId"])
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is True and o["priorDiff"] is None, "merge 後の unchanged %r" % o)
        # 指紋を取れないファイル（repo の外・改行を含む path）か、前の回も今も無いファイル（untracked）を読んだ記録は近道を取らない
        write_rec(head=c3, patchId=o["patchId"], odd=True)
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False, "repo の外を読んだ記録で unchanged %r" % o["unchanged"])
        write(e.repo, "untracked.txt", "u\n")
        write_rec(head=c3, patchId=o["patchId"], nodes=[{"key": "u", "resultStatus": "leaf", "files": ["untracked.txt"]}])
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False and o["fingerprints"]["untracked.txt"] == "absent", "untracked を読んだ記録で unchanged %r" % o)
        os.remove(os.path.join(e.repo, "untracked.txt"))
        # 臭いの問いの根拠（ノードでない所の evidence）に挙げたファイルも指紋に入れる（m.txt は main から来た）
        write_rec(head=c3, patchId=o["patchId"], smells=[{"id": "S1", "answer": {"evidence": [{"path": "m.txt", "line": 1, "quote": "m"}]}}])
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False and o["fingerprints"].get("m.txt") == "moved", "臭いの根拠のファイルが動いても unchanged %r" % o)
        # patch-id が同じでも、ノードが読んだ PR の外のファイルが前の回の head と違えば近道を取らない（m.txt は main から来た）
        write_rec(head=c3, patchId=o["patchId"], nodes=[{"key": "k", "resultStatus": "leaf", "files": ["m.txt"]}])
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False and o["fingerprints"]["m.txt"] == "moved", "外のファイルが動いても unchanged %r" % o)
        # 前の回に結果を返さなかった段が在る記録は、patch-id が同じでも使い回さない
        write_rec(head=c3, patchId=o["patchId"], counts={"stages": {"W6": {"null": ["W6 a"]}}, "allNull": ["W6"]})
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False, "欠けた記録で unchanged %r" % o)
        # 欠けの無い記録は unchanged（下の版の違う記録と比べる）
        write_rec(head=c3, patchId=o["patchId"])
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is True and o["priorReuse"] is not None, "欠けの無い記録で unchanged でない %r" % o)
        # 版の違う記録（版 1: checked の中の files・evidence の at）は使い回さず、近道も取らない
        write_rec(head=c3, patchId=o["patchId"], version=1)
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and o["unchanged"] is False and o["priorReuse"] is None and o["priorHead"] == c3,
              "版 1 の記録を使い回した %r" % o)
        # 1 つ前の版 2 の記録も使い回さない
        write_rec(head=c3, patchId=o["patchId"], version=2)
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and o["unchanged"] is False and o["priorReuse"] is None, "版 2 の記録を使い回した %r" % o)
        # 同じ head で記録が欠けていた: 掘り直すが、空の 2 本目の差分は作らない
        write_rec(head=c5, patchId=o["patchId"], counts={"stages": {"W6": {"null": ["W6 a"]}}, "allNull": []})
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False and o["priorDiff"] is None, "同じ head の 2 本目 %r" % o)
        # 段の一部のノードだけが返らなかった記録も欠けている
        write_rec(head=c3, patchId=o["patchId"], counts={"stages": {"W6": {"started": 3, "returned": 2, "null": ["W6 b"]}}, "allNull": []})
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False, "一部が落ちた記録で unchanged %r" % o)
        # counts の形が壊れた記録でも止まらず、使い回さない
        write_rec(head=c3, patchId=o["patchId"], counts=["W6"])
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and o["unchanged"] is False, "壊れた counts %r" % o)
        # 字下げだけの直しは「変わっていない」にしない
        write_rec(head=c5, patchId=o["patchId"])
        c6 = commit(e.repo, "indent", a_DOT_txt="a\n  A\nB\n")
        e.set_gh(c6)
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False, "字下げだけで unchanged %r" % o)
        # 改行の字（LF→CRLF）だけの直しも「変わっていない」にしない（PR が足したファイルだけを CRLF にする）
        cn = commit(e.repo, "new file", n_DOT_txt="x\ny\n")
        e.set_gh(cn)
        rc, o = e.prep("7")
        write_rec(head=cn, patchId=o["patchId"])
        c7 = commit(e.repo, "crlf", n_DOT_txt="x\r\ny\r\n")
        e.set_gh(c7)
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is False, "CRLF だけで unchanged %r" % o)
        # rebase の後（前の head が今の head の祖先でない）: base の側の動きを載せた 2 本目の差分を作らない
        git(e.repo, "switch", "-q", "-c", "other", "main")
        cx = commit(e.repo, "elsewhere", z_DOT_txt="z\n")
        git(e.repo, "switch", "-q", "feat")
        write_rec(head=cx, patchId="different")
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and o["priorHeadMissing"] is False and o["priorHead"] == cx and o["priorDiff"] is None,
              "rebase の後の 2 本目 %r" % o)
        # 前回の head がこの repo に無い
        write_rec(head="1" * 40, patchId="different")
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and o["priorHeadMissing"] is True and o["priorDiff"] is None and o["priorHead"] == "1" * 40,
              "priorHeadMissing %r" % o)
        check(o["priorReuse"] is None, "前回の head が無いときは使い回さない")
        check(all(v != "same" for v in o["fingerprints"].values()), "missing 時の指紋")
        # 読めない記録
        with open(rec, "w") as f:
            f.write("{nope")
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and o["priorUnreadable"] and o["priorHead"] is None and o["priorReuse"] is None
              and o["priorDiff"] is None, "読めない記録で前の回が無い扱いにならない %r" % o)
        # base の側で決まりの文書（段が従う REVIEW.md）が変わった: PR の patch-id が同じでも近道を取らない
        rc, o = e.prep("7")
        write_rec(head=git(e.repo, "rev-parse", "HEAD"), patchId=o["patchId"], nodes=[])
        rc, o = e.prep("7", "--prior", rec)
        check(o["unchanged"] is True, "決まりの文書の前に unchanged でない %r" % o)
        git(e.repo, "switch", "-q", "main")
        commit(e.repo, "rules", REVIEW_DOT_md="review\n")
        git(e.repo, "push", "-q", "origin", "main")
        git(e.repo, "switch", "-q", "feat")
        git(e.repo, "merge", "-q", "--no-edit", "main")
        e.set_gh(git(e.repo, "rev-parse", "HEAD"))
        rc, o = e.prep("7", "--prior", rec)
        check(rc == 0 and o["unchanged"] is False and o["fingerprints"].get("REVIEW.md") == "moved"
              and "REVIEW.md" in [r["path"] for r in o["rules"]], "決まりの文書が変わっても unchanged %r" % o)
    if not POSIX:
        return skip("prior")
    with_env(body)


def ev(path, line, quote):
    return {"path": path, "line": line, "quote": quote}


# my-turn-dig.js の fnv（UTF-16 の単位の FNV-1a）を node で出した値。Python の側（fnv32）が同じ値を出すかを見る
JS_FNV = {"a.py\n1\nx": "4964b612", "docs/読む.md\n12\n「引用」の行 😀": "98bd3c2f", "": "811c9dc5"}


def ascii_json(v):
    """my-turn-dig.js の asciiJson と同じ形（ASCII の外の字を UTF-16 の \\uXXXX で書く）。"""
    return json.dumps(v, ensure_ascii=True, separators=(",", ":"))


def case_quotes():
    def body(e):
        base = e.base_commit(f_DOT_txt="one\ntwo\nthree\n")
        # base の印の頭 8 字の名前のファイル（印としても読めるが、後に : が無いので path）
        head = feature(e, f_DOT_txt="one\nTWO changed\nthree\nfour\n", g_DOT_txt="page\fbreak\nafter\n", cafebabe="hex name\n",
                       **{base[:8]: "hex base\n", "読む_DOT_md": "「引用」の行 😀\n"})
        rec = os.path.join(e.tmp, "rec.json")
        write(e.tmp, "7-thread.md", "body\nthe author said so\n")  # 記録のフォルダ（rec の在るフォルダ）のファイル
        with open(rec, "w", encoding="utf-8") as f:
            json.dump({"base": base, "head": head, "nodes": [
                ev(os.path.join(e.tmp, "7-thread.md"), 2, "the author said so"),
                ev("g.txt", 2, "after"),  # \f で行を切らない
                ev("g.txt", 1, "pagebreak"),  # Workflow は引用から \f を外して記録に書く
                ev("%s:f.txt" % head[:7], 2, "TWO changed"),  # base でない commit の印
                ev("f.txt", 2, "TWO changed"),
                ev(os.path.join(e.repo, "f.txt"), 2, "TWO changed"),
                ev("/elsewhere/f.txt", 2, "TWO changed"),
                ev("f.txt", 3, " three "),
                ev("f.txt", 2, "TWO chenged"),
                ev("f.txt", 9, "four"),
                ev("%s:f.txt" % base[:7], 2, "two"),
                ev("%s:f.txt" % base[:7], 2, "TWO changed"),
                ev("https://example.com/x", 0, "anything"),
                ev("nofile.txt", 1, "x"),
                ev("f.txt", "2", "x"),  # 行が整数でない
                ev("1234567:f.txt", 2, "TWO changed"),  # 解けない commit の印
                ev("cafebabe", 1, "hex name"),  # 名前が 16 進の字だけのファイル
                ev(base[:8], 1, "hex base"),
                ev("f.txt", 1, "   "),
                ev("f.txt", 0, "one"),  # 行の無い在り処は照合の外
                {"deep": [ev("f.txt", 4, "four")]},
                {"deep": [ev("f.txt", 4, "four")]},
            ]}, f)
        rc, o = e.prep("--quotes", rec, script=PREP)
        check(rc == 0 and o["ok"], "quotes ok %r" % o)
        got = sorted((m["path"], str(m["line"]), m["quote"]) for m in o["missing"])
        want = sorted([("f.txt", "2", "TWO chenged"), ("f.txt", "9", "four"), ("%s:f.txt" % base[:7], "2", "TWO changed"),
                       ("nofile.txt", "1", "x"), ("f.txt", "2", "x"), ("/elsewhere/f.txt", "2", "TWO changed"),
                       ("1234567:f.txt", "2", "TWO changed")])
        check(got == want, "missing %r" % got)
        check(all(m["why"] for m in o["missing"]), "why が空")
        check(any("1234567" in m["why"] and m["path"].startswith("1234567") for m in o["missing"]), "解けない印の訳 %r" % o["missing"])
        check(o["checked"] == 19, "checked %r" % o["checked"])  # URL・行 0・空の quote は数えない
        with open(rec, "w") as f:
            f.write("nope")
        rc, o = e.prep("--quotes", rec)
        check(rc == 1 and o["stop"] == "prior-unreadable", "unreadable")

        # --b64 の形（Workflow の写しの照合の段が打つ物）: 1 語目が頭、続く語が <id>:<[id, path, 行, 写し, 印] の base64>
        sys.path.insert(0, os.path.dirname(PREP))
        import importlib.util
        spec = importlib.util.spec_from_file_location("my_turn_prep", PREP)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for k, v in JS_FNV.items():
            check(mod.fnv32(k) == v, "fnv32 が my-turn-dig.js の fnv と違う %r" % k)

        def item(i, path, line, quote, bad=False):
            return ascii_json([i, path, line, quote, "0" * 8 if bad else mod.fnv32("%s\n%s\n%s\n%s" % (i, path, line, quote))])

        lines = [ascii_json({"workdir": e.repo, "base": base, "head": head, "recordDir": e.tmp}),
                 item("Q1", "f.txt", 2, "TWO changed"),
                 item("Q2", "読む.md", 1, "「引用」の行 😀"),  # ASCII の外と UTF-16 の対の字
                 item("Q3", "f.txt", 2, "TWO chenged"),
                 item("Q4", "%s:f.txt" % base[:7], 2, "two"),
                 item("Q5", os.path.join(e.tmp, "7-thread.md"), 2, "the author said so"),
                 item("Q6", "f.txt", 2, "TWO changed", bad=True),  # 印が合わない（写し違い）
                 '["Q7", "f.txt", 2',  # 途中で切れた行
                 item("Q8", "f.txt", 0, "one"),  # 形が違う（行が 1 より小さい）
                 "", "junk"]
        def word(row):
            # my-turn-dig.js の quoteCommand と同じ形: 頭は base64 だけ、件は <id>:<base64>
            m = re.match(r'^\["(Q\d+)"', row)
            b = base64.b64encode(row.encode("utf-8")).decode("ascii")
            return "%s:%s" % (m.group(1), b) if m else b

        words = [word(lines[0])] + [word(l) for l in lines[1:] if l.startswith('["Q')]
        words += ["Q9:@@not-base64@@",  # 戻せない語（写し違い）は、その id で garbled
                  "Q10:" + base64.b64encode(item("Q11", "f.txt", 2, "TWO changed").encode()).decode(),  # 前の id と中の id が違う
                  word(item("Q1", "f.txt", 2, "TWO changed")),  # 同じ id の 2 度目は数えない（重ねて別の件を落とした写しの数を合わせない）
                  "junk"]  # id も読めない語は数えない
        # 作業場の外から打っても、頭の workdir で読む
        rc, o = e.prep("--quotes", "--b64", *words, cwd=e.tmp)
        check(rc == 0 and o["ok"] and o["checked"] == 10, "引数の照合 %r" % o)
        check(sorted(m["id"] for m in o["missing"]) == ["Q3", "Q8"] and o["garbled"] == ["Q6", "Q7", "Q9", "Q10"], "合わない物 %r" % o)
        # 頭が読めない
        for head_word in ("nope", base64.b64encode(b"nope").decode()):
            rc, o = e.prep("--quotes", "--b64", head_word)
            check(rc == 1 and o["ok"] is False and o["stop"] == "quotes-input", "頭の無い入力 %r" % o)

        # --save-record: Workflow の出力のファイル（result が戻り値の JSON の文字列）から記録を書く（既定の形の手順 9）
        out = os.path.join(e.tmp, "wf.output")
        recd = os.path.join(e.tmp, "rd", "7.json")
        val = {"version": 3, "pr": 7, "head": head, "nodes": [{"id": "n1"}], "recordWritten": False}
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"summary": "s", "result": json.dumps(val)}, f)
        rc, o = e.prep("--save-record", recd, out)
        saved = json.load(open(recd, encoding="utf-8"))
        check(rc == 0 and o["ok"] and o["nodes"] == 1 and o["head"] == head
              and saved == {k: v for k, v in val.items() if k != "recordWritten"}, "記録の書き込み %r %r" % (o, saved))
        # 止まった回・版の違う戻り値は書かず、前の記録を残す
        for bad in ({"stopped": "W1", "version": 3}, {**val, "version": 1}, {**val, "version": 2}, ["x"]):
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"result": bad}, f)
            rc, o = e.prep("--save-record", recd, out)
            check(rc == 1 and o["stop"] == "record" and json.load(open(recd, encoding="utf-8")) == saved, "書かない戻り値 %r %r" % (bad, o))
        rc, o = e.prep("--save-record", recd, os.path.join(e.tmp, "none"))
        check(rc == 1 and o["stop"] == "record", "無い出力のファイル %r" % o)
    if not POSIX:
        return skip("quotes")
    with_env(body)


def case_headless():
    QC = {"runPython": "/p/scripts/run-python.sh", "prep": "/p/scripts/my-turn-prep.py"}

    def body(e):
        # 記録のフォルダはリンクの先（macOS の /tmp → /private/tmp の形）。記録は台本がリンクの綴りのまま書く
        os.makedirs(os.path.join(e.tmp, "rd-real"))
        rd = os.path.join(e.tmp, "rd")
        os.symlink(os.path.join(e.tmp, "rd-real"), rd)
        fake(os.path.join(e.bin, "claude"), FAKE_CLAUDE)
        fdir = os.path.join(e.tmp, "fc")
        os.makedirs(fdir)
        args_json = os.path.join(e.tmp, "args.json")
        with open(args_json, "w", encoding="utf-8") as f:
            json.dump({"pr": 7, "workdir": e.work, "prep": {"recordDir": rd, "scriptPath": "/x/workflows/my-turn-dig.js",
                                                             "quoteCheck": QC},
                       "files": {"record": os.path.join(rd, "7.json")}, "models": {"W3": {"model": "fable"}}}, f)
        # 認証は親が持っている形にして、窓口のコマンドや Keychain を読ませない
        env = e.env(CLAUDE_FOO="1", ANTHROPIC_BAR="2", CLAUDE_CONFIG_DIR="/cfg", CLAUDE_CODE_DISABLE_CLAUDE_MDS="0",
                    ANTHROPIC_VERTEX_PROJECT_ID="p", ANTHROPIC_DEFAULT_OPUS_MODEL="x",
                    CLAUDE_CODE_OAUTH_TOKEN="dummy", CLAUDE_TOKEN_HELPER="", CLAUDE_CODE_CLIENT_CERT="/c.pem",
                    CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="600000", FAKE_CLAUDE_DIR=fdir)

        def launch(*extra):
            r = subprocess.run([sys.executable, HEADLESS, args_json, *extra], env=env, capture_output=True,
                               encoding="utf-8", errors="replace")
            try:
                return r.returncode, json.loads(r.stdout)
            except ValueError:
                print("FAIL: 出力が JSON でない rc=%s %r %r" % (r.returncode, r.stdout, r.stderr))
                sys.exit(1)

        rc, d = launch("--dry-run")
        check(rc == 0, "dry-run rc")
        check("CLAUDE_FOO" in d["envDropped"] and "ANTHROPIC_BAR" in d["envDropped"]
              and "CLAUDE_CONFIG_DIR" not in d["envDropped"], "envDropped %r" % d["envDropped"])
        check(d["envDropped"] == sorted(d["envDropped"]), "envDropped が整列していない")
        check(d["envAdded"] == {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK": "1",
                                "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"}, "envAdded")
        argv = d["argv"]
        check(argv[:2] == ["claude", "-p"], "argv 先頭")

        def after(flag):
            return argv[argv.index(flag) + 1]
        check(after("--model") == "sonnet" and after("--output-format") == "json", "model/format")
        check(after("--max-budget-usd") == "100", "budget の既定")
        check(after("--tools") == "Read,Grep,Glob,Bash,Workflow,WebFetch,WebSearch", "tools")
        check(after("--setting-sources") == "", "setting-sources")
        check("--disable-slash-commands" in argv and "--strict-mcp-config" in argv, "フラグ")
        check(json.loads(after("--settings")) == {"disableAllHooks": True}, "settings")
        check(after("--permission-mode") == "dontAsk", "permission-mode")
        dirs = [argv[i + 1] for i, a in enumerate(argv) if a == "--add-dir"]
        check(dirs == ["/x/workflows", rd], "add-dir が script のフォルダと記録のフォルダでない %r" % dirs)
        sysprompt = after("--system-prompt")
        check("/x/workflows/my-turn-dig.js" in sysprompt and "Workflow" in sysprompt, "system prompt")
        argsf = d["argsFile"]
        check(argsf == os.path.join(rd, "7-args-headless.json") and argsf in argv[2], "argsFile / prompt")
        rules = argv[argv.index("--allowedTools") + 1:]
        for want in ["Workflow", "Read", "Grep", "Glob", "WebFetch", "WebSearch",
                     "Bash(bash /p/scripts/run-python.sh /p/scripts/my-turn-prep.py --quotes --b64 *)",
                     "Bash(git show *)", "Bash(git blame *)", "Bash(git log *)", "Bash(git diff *)",
                     "Bash(git cat-file *)", "Bash(git ls-files *)", "Bash(git rev-parse *)",
                     "Bash(gh pr view *)", "Bash(gh pr diff *)", "Bash(gh pr list *)", "Bash(gh issue view *)",
                     "Bash(gh issue list *)", "Bash(gh search *)"]:
            check(want in rules, "許可ルールに無い: " + want)
        check(not any("gh api" in r or "git grep" in r for r in rules), "gh api か git grep が許可に入った")
        check(not any(r.startswith(("Edit", "Write")) for r in rules), "書き込みの許可が残った %r" % rules)
        check("never edit files" in after("--system-prompt").lower() and "outputFile" in after("--system-prompt"),
              "system prompt が出力のファイルの path を返させない")
        # 子は待つ手を持たないので、待たずにターンを終えさせる（前の「終わるまでターンを終えるな」は守れなかった）
        check("end your turn with no output" in sysprompt and "end your turn while" not in sysprompt,
              "system prompt が待たずにターンを終えさせない")
        deny = argv[argv.index("--disallowedTools") + 1:argv.index("--permission-mode")]
        check(deny == ["Bash(git *--output*)", "Bash(git grep *)"], "禁止のルール %r" % deny)
        ag = json.loads(after("--agents"))
        keys = "Purpose W1 W2 W3 W4 W6 Redig W7 W8 Lines W9 W10answers W10fixes Quotes".split()
        check(sorted(ag) == sorted("my-turn-" + k for k in keys), "役の一覧 %r" % sorted(ag))
        for name, a in ag.items():
            check("model" not in a and "effort" not in a, name + " に model/effort")
            check(a["omitClaudeMd"] is True and a["description"] and a["prompt"], name + " の定義")
            check("Write" not in a["tools"] and "Edit" not in a["tools"], name + " の Write")
            check((a["tools"] == []) == (name == "my-turn-W2"), name + " の tools の空")
            web = "WebFetch" in a["tools"] and "WebSearch" in a["tools"]
            check(web == (name not in ("my-turn-W2", "my-turn-Quotes")), name + " の web のツール")
        check(ag["my-turn-Quotes"]["tools"] == ["Bash"] and "Read" in ag["my-turn-Quotes"]["disallowedTools"], "Quotes のツール")
        saved = json.load(open(argsf, encoding="utf-8"))
        check(saved["roles"] == {k: "my-turn-" + k for k in keys} and saved["pr"] == 7, "args-headless の roles")
        check(saved.get("caller") == "attention:my-turn-deep", "args-headless に起動の合図（caller）が無い")
        check(not os.path.exists(os.path.join(fdir, "seen.json")), "dry-run が起動した")

        # 本番: 偽の claude
        canned = {"is_error": False, "result": "```json\n{\"stopped\": \"W1\"}\n```", "total_cost_usd": 1.25, "duration_ms": 4321,
                  "modelUsage": {"claude-sonnet-4-6": {}, "us.anthropic.claude-opus-4-7-v1:0": {}, "claude-weird-1": {}}}

        def run_raw(text, *extra):
            """偽の claude の標準出力を text にして、1 回起動する。"""
            with open(os.path.join(fdir, "canned.json"), "w") as f:
                f.write(text)
            return launch(*extra)

        def run_with(result, *extra):
            """偽の claude の答えの result を替えて、1 回起動する。"""
            canned["result"] = result
            return run_raw(json.dumps(canned), *extra)

        rc, s = run_with(canned["result"], "--budget-usd", "5")
        check(rc == 0 and s["ok"] is True and s["exit"] == 0, "real run %r" % s)
        check(s["costUsd"] == 1.25 and s["durationMs"] == 4321, "cost/duration")
        check(s["auth"] == "inherited(CLAUDE_CODE_OAUTH_TOKEN)", "認証の段 %r" % s.get("auth"))
        check(s["output"] == os.path.join(rd, "7-headless.json"), "output 名")
        check(s["materials"] == os.path.join(rd, "7-materials.json")
              and json.load(open(s["materials"])) == {"stopped": "W1"}, "materials")
        # Bedrock の形の名（us.anthropic.claude-opus-…）も opus に数える
        check(s["models"]["used"] == ["claude-sonnet-4-6", "us.anthropic.claude-opus-4-7-v1:0", "claude-weird-1"], "used")
        check(s["models"]["unexpected"] == ["claude-weird-1"], "unexpected %r" % s["models"])
        # 数え（counts）の無い答え（W1 で止まった形）は、来なかったモデルを数えない
        check(s["models"]["expectedMissing"] is None, "expectedMissing %r" % s["models"])
        seen = json.load(open(os.path.join(fdir, "seen.json")))
        check(os.path.realpath(seen["cwd"]) == os.path.realpath(e.work), "cwd が workdir でない")
        check("CLAUDE_FOO" not in seen["env"] and "ANTHROPIC_BAR" not in seen["env"]
              and "CLAUDE_CONFIG_DIR" in seen["env"] and "CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK" in seen["env"]
              and "CLAUDE_CODE_OAUTH_TOKEN" in seen["env"] and "CLAUDE_TOKEN_HELPER" not in seen["env"]
              and "ANTHROPIC_VERTEX_PROJECT_ID" in seen["env"] and "ANTHROPIC_DEFAULT_OPUS_MODEL" not in seen["env"]
              and "CLAUDE_CODE_CLIENT_CERT" in seen["env"], "子の環境")
        # 親が 10 分の既定を持っていても、子は Workflow の終わりまで待つ（PR #2574 の打ち切り）
        check(seen["bgWait"] == "0", "子の待つ上限 %r" % seen["bgWait"])
        check(seen["argv"][seen["argv"].index("--max-budget-usd") + 1] == "5", "budget の指定")
        # 止まらずに終わった回: 子は Workflow の出力のファイルの path だけを返し、台本がそこから記録を書く
        rec = os.path.join(rd, "7.json")
        wf_out = os.path.join(e.tmp, "wf.output")
        body_rec = {"version": 3, "pr": 7, "nodes": [{"id": "n1"}], "recordPath": "stale",
                    "counts": {"stages": {"W6": {"started": 1, "returned": 1, "null": [], "models": ["sonnet"]},
                                          "W3": {"started": 0, "returned": 0, "null": [], "models": ["fable"]},
                                          "Quotes": {"started": 1, "returned": 1, "null": [], "models": ["haiku"]}},
                               "allNull": []}}
        with open(wf_out, "w", encoding="utf-8") as f:
            json.dump({"summary": "done", "agentCount": 3, "result": json.dumps(body_rec)}, f)
        rc, s = run_with(json.dumps({"outputFile": wf_out}))
        want = {k: v for k, v in body_rec.items() if k != "recordPath"}
        check(rc == 0 and s["ok"] is True and s["record"] == rec and json.load(open(rec)) == want
              and json.load(open(s["materials"])) == want, "出力のファイルから書いた記録 %r" % s)
        # 来なかったモデルは、回った段（W6 の sonnet と Quotes の haiku）の物だけ。回らなかった W3 の fable は数えない
        check(s["models"]["expectedMissing"] == ["haiku"], "回った段のモデル %r" % s["models"])
        # 子が戻り値の全体を返した回も、同じく記録を書く
        os.unlink(rec)
        rc, s = run_with(json.dumps(want))
        check(rc == 0 and s["ok"] is True and json.load(open(rec)) == want, "戻り値の全体から書いた記録 %r" % s)
        # 版の違う戻り値は記録にしないが、材料は捨てない
        os.unlink(rec)
        rc, s = run_with(json.dumps({**want, "version": 1}))
        check(rc == 1 and s["ok"] is False and s["record"] is None and not os.path.exists(rec) and isinstance(s["message"], str)
              and json.load(open(s["materials"]))["version"] == 1, "版の違う戻り値 %r" % s)
        # 記録を書けない（files.record の親がファイル）: 材料は書き、record は返さない
        blocker = os.path.join(e.tmp, "blocker")
        open(blocker, "w").close()
        orig_args = open(args_json, encoding="utf-8").read()
        bad = json.loads(orig_args)
        bad["files"]["record"] = os.path.join(blocker, "7.json")
        with open(args_json, "w", encoding="utf-8") as f:
            json.dump(bad, f)
        rc, s = run_with(json.dumps(want))
        with open(args_json, "w", encoding="utf-8") as f:
            f.write(orig_args)
        check(rc == 1 and s["ok"] is False and s["record"] is None and isinstance(s["message"], str)
              and json.load(open(s["materials"])) == want, "書けない記録 %r" % s)
        # 出力のファイルが読めない
        rc, s = run_with(json.dumps({"outputFile": os.path.join(e.tmp, "none.output")}))
        check(rc == 1 and s["ok"] is False and s["materials"] is None and "none.output" in s["message"], "読めない出力のファイル %r" % s)
        # Workflow の呼び出しが失敗した回: 子の答えの訳が message に出る
        rc, s = run_with(json.dumps({"workflowError": "scriptPath rejected"}))
        check(rc == 1 and s["ok"] is False and "scriptPath rejected" in s["message"], "workflowError %r" % s)
        # result が JSON でない
        rc, s = run_with("just text")
        check(rc == 1 and s["materials"] is None and s["ok"] is False and s["message"], "materials なし %r" % s)
        # JSON だが Workflow の返り値でない（Workflow が断られた回の子の答えの形）
        rc, s = run_with(json.dumps({"recordWritten": False, "error": "rejected"}))
        check(rc == 1 and s["materials"] is None and s["ok"] is False, "返り値でない JSON %r" % s)
        # 上限の額で止まった回: Workflow も止められたと言い、「動かなかった」と取り違えさせない
        rc, s = run_raw(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True,
                                    "errors": [], "total_cost_usd": 100.2, "modelUsage": {}}))
        check(rc == 1 and s["ok"] is False and s["materials"] is None and "--budget-usd" in s["message"]
              and "100" in s["message"], "上限の額で止まった回 %r" % s)
        # 出力が JSON でない（途中で切れた形。1 行の短い答えは認証の失敗の形なので、複数の行にする）
        rc, s = run_raw('{"type": "result",\n "result": "cut')
        check(rc == 1 and s["ok"] is False and s["message"] and s["authFailed"] is False, "壊れた出力 %r" % s)
        # 認証の失敗（終了の値 0 の 1 行）は上限の額のせいにしない
        rc, s = run_raw("Failed to authenticate: OAuth session expired")
        check(rc == 1 and s["ok"] is False and s["authFailed"] is True
              and "OAuth session expired" in s["message"], "認証の失敗 %r" % s)
        # Foundry の経路: 親の環境をそのまま継ぎ、Keychain や OAuth の鍵の段を選ばない（claude_auth が継ぐ経路に数える）
        canned["result"] = "```json\n{\"stopped\": \"W1\"}\n```"
        saved = {k: env.pop(k) for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if k in env}
        env["CLAUDE_CODE_USE_FOUNDRY"] = "1"
        rc, s = run_raw(json.dumps(canned))
        del env["CLAUDE_CODE_USE_FOUNDRY"]
        env.update(saved)
        check(rc == 0 and s["auth"] == "inherited(CLAUDE_CODE_USE_FOUNDRY)", "Foundry の認証の段 %r" % s)
        # 照合の台本の path に規則の字（空白・かっこ）が在る: 照合の許可を組まずに起動する（照合の段は断られ、
        # Workflow が確かめていない根拠として数えて残す）
        for bad in ("/p q/run-python.sh", "/p(1)/run-python.sh"):
            with open(args_json, "w", encoding="utf-8") as f:
                json.dump({"pr": 7, "workdir": e.work, "prep": {"recordDir": rd, "scriptPath": "/x/workflows/my-turn-dig.js",
                                                                 "quoteCheck": {**QC, "runPython": bad}}}, f)
            rc, d = launch("--dry-run")
            rules = d["argv"][d["argv"].index("--allowedTools") + 1:]
            check(rc == 0 and not any("--quotes" in r for r in rules), "規則の字の path %r %r" % (bad, rules))
    if not POSIX:
        return skip("headless")
    with_env(body)


def case_lines():
    def body(e):
        e.base_commit(**{"README.md": "r\n", "src/a.py": "a\n"})
        feature(e, **{"src/a.py": "a\n1\n2\n3\n4\n", "src/new.py": "x\ny\n",
                      "tests/test_a.py": "def test_a():\n    pass\n", "docs/guide.md": "g\n",
                      ".github/workflows/ci.yml": "name: ci\n", "scripts/check-x.sh": "echo\nexit 0\n",
                      "pkg/config.toml": "a = 1\n", "package-lock.json": "{}\n", "web/app.spec.ts": "t\n"})
        rc, o = e.prep("7")
        check(rc == 0 and o["stage0Errors"] == [], "ok でない %r" % o)
        by = o["lines"]["byClass"]
        check(sorted(by) == sorted(["impl", "test", "check", "ci", "docs", "config", "generated"]), "区分の鍵 %r" % sorted(by))
        # 実装は src/a.py の 4 行と src/new.py の 2 行。試験は test_a.py の 2 行と app.spec.ts の 1 行
        want = {"impl": (6, 2), "test": (3, 2), "check": (2, 1), "ci": (1, 1), "docs": (1, 1), "config": (1, 1), "generated": (1, 1)}
        for c, (added, files) in want.items():
            check(by[c] == {"added": added, "deleted": 0, "files": files}, "区分 %s %r" % (c, by[c]))
        # 試験と検査の足した行 5 ÷ 実装の足した行 6
        check(o["lines"]["testToImpl"] == 0.83, "testToImpl %r" % o["lines"]["testToImpl"])
    if not POSIX:
        return skip("lines")
    with_env(body)

    # 実装の足した行が 0 なら null、バイナリは generated
    def body2(e):
        e.base_commit(a_DOT_txt="a\n")
        git(e.repo, "switch", "-q", "-c", "feat")
        with open(os.path.join(e.repo, "img.bin"), "wb") as f:
            f.write(b"\x00\x01\x02")
        head = commit(e.repo, "bin", **{"tests/test_a.py": "def test_a():\n    pass\n"})
        e.set_gh(head)
        rc, o = e.prep("7")
        check(o["lines"]["testToImpl"] is None, "impl が 0 のとき null %r" % o["lines"])
        check(o["lines"]["byClass"]["generated"]["files"] == 1 and o["lines"]["byClass"]["generated"]["added"] == 0,
              "バイナリ %r" % o["lines"]["byClass"]["generated"])
    with_env(body2)


def case_deleted_tests():
    def body(e):
        e.base_commit(**{
            "tests/test_a.py": "def test_one():\n    pass\n\ndef test_two():\n    pass\n\ndef test_dup():\n    pass\n\ndef test_dup():\n    pass\n",
            "web/a.test.js": "it('keeps', () => {})\nit(\"goes away\", () => {})\ntest(`tpl`, () => {})\n",
            "tests/old_test.go": "package x\nfunc TestGone(t *testing.T) {}\n",
            "tests/whole_test.py": "def test_whole():\n    pass\n",
            "tests/spec_test.rb": "it 'x' do\nend\n",
            "src/impl.py": "def test_not_a_test_file():\n    pass\n"})
        git(e.repo, "switch", "-q", "-c", "feat")
        git(e.repo, "rm", "-q", "tests/whole_test.py")
        write(e.repo, "tests/test_a.py", "def test_one():\n    pass\n\ndef test_dup():\n    pass\n")
        write(e.repo, "web/a.test.js", "it('keeps', () => {})\n")
        write(e.repo, "tests/old_test.go", "package x\n")
        write(e.repo, "tests/spec_test.rb", "it 'x' do\nend\n# touched\n")
        write(e.repo, "src/impl.py", "x = 1\n")
        head = commit(e.repo, "drop tests")
        e.set_gh(head)
        rc, o = e.prep("7")
        check(rc == 0 and o["stage0Errors"] == [], "ok でない %r" % o)
        d = o["deletedTests"]
        check(d["files"] == ["tests/whole_test.py"], "ファイルごと %r" % d["files"])
        got = sorted((n["path"], n["name"]) for n in d["names"])
        want = sorted([("tests/test_a.py", "test_two"), ("tests/test_a.py", "test_dup"), ("web/a.test.js", "goes away"),
                       ("web/a.test.js", "tpl"), ("tests/old_test.go", "TestGone"), ("tests/whole_test.py", "test_whole")])
        check(got == want, "消えた名前 %r" % got)
        check(d["uncounted"] == ["tests/spec_test.rb"], "数えられない %r" % d["uncounted"])
    if not POSIX:
        return skip("deleted-tests")
    with_env(body)


def case_rules_wide():
    def body(e):
        base = e.base_commit(**{
            "CONTRIBUTING.md": "c\n", "docs/adr/0001-x.md": "adr\n", "pkg/sub/ARCHITECTURE.md": "arch\n",
            "pkg/DECISIONS.md": "d\n", "pkg/sub/x.py": "x\n", "other/CONTRIBUTING.md": "other\n",
            "docs/ledger.md": "not a root or ancestor folder\n", "台帳.md": "l\n", "pkg/sub/notes.md": "n\n",
            "decisions/d1.md": "d1\n", "src/adr/z.md": "not an adr folder\n"})
        feature(e, **{"pkg/sub/x.py": "x2\n"})
        rc, o = e.prep("7")
        check(rc == 0 and o["stage0Errors"] == [] and o["rulesCut"] == 0, "ok でない %r" % o)
        paths = [r["path"] for r in o["rules"]]
        for p in ("CONTRIBUTING.md", "docs/adr/0001-x.md", "pkg/sub/ARCHITECTURE.md", "pkg/DECISIONS.md", "台帳.md", "decisions/d1.md"):
            check(p in paths, "%s が決まりに無い %r" % (p, paths))
        for p in ("other/CONTRIBUTING.md", "docs/ledger.md", "src/adr/z.md", "pkg/sub/notes.md"):
            check(p not in paths, "%s を拾った %r" % (p, paths))
        item = [r for r in o["rules"] if r["path"] == "docs/adr/0001-x.md"][0]
        check(item["show"] == "git show %s:docs/adr/0001-x.md" % base[:7], "show %r" % item)
    if not POSIX:
        return skip("rules-wide")
    with_env(body)

    # 足す物は 40 件で切り、外した数を rulesCut に出す
    def body2(e):
        e.base_commit(**{"docs/adr/%03d.md" % i: "a\n" for i in range(45)}, **{"a.txt": "a\n"})
        feature(e, **{"a.txt": "b\n"})
        rc, o = e.prep("7")
        check(len(o["rules"]) == 40 and o["rulesCut"] == 5, "上限 %d %r" % (len(o["rules"]), o["rulesCut"]))
    with_env(body2)


def case_identity():
    def body(e):
        e.base_commit(a_DOT_txt="a\n")
        feature(e, **{".github/workflows/ci.yml": "name: ci\non: push\npermissions:\n  id-token: write\njobs:\n  b:\n    steps:\n      - run: echo ${{ secrets.DEPLOY_KEY }}\n",
                      "src/app.py": "x = 1\nAPI_TOKEN = os.environ['MY_API_TOKEN']\n",
                      "infra/main.tf": 'resource "aws_iam_role" "r" {}\n', "k8s/r.yaml": "kind: ClusterRoleBinding\n",
                      "README.md": "plain text\n"})
        rc, o = e.prep("7")
        check(rc == 0 and o["stage0Errors"] == [] and o["identitySignalsCut"] == 0, "ok でない %r" % o)
        got = {(s["path"], s["line"]): s["text"] for s in o["identitySignals"]}
        wf = ".github/workflows/ci.yml"
        check(got.get((wf, 3)) == "permissions:", "permissions: %r" % got)
        check((wf, 4) in got and (wf, 8) in got, "id-token・secrets %r" % got)
        check(got.get(("src/app.py", 2), "").startswith("API_TOKEN"), "設定の名前 %r" % got)
        check(("infra/main.tf", 1) in got and ("k8s/r.yaml", 1) in got, "IAM・role %r" % got)
        check(not any(p == "README.md" or (p == "src/app.py" and n == 1) for p, n in got), "余計な行 %r" % got)
    if not POSIX:
        return skip("identity")
    with_env(body)

    # 上限 50 で切り、外した数を出す
    def body2(e):
        e.base_commit(a_DOT_txt="a\n")
        feature(e, **{"s.py": "".join("T%d_TOKEN = 1\n" % i for i in range(55))})
        rc, o = e.prep("7")
        check(len(o["identitySignals"]) == 50 and o["identitySignalsCut"] == 5, "上限 %r" % o["identitySignalsCut"])
    with_env(body2)


def case_check_report():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        def prep(*args):
            r = subprocess.run([sys.executable, PREP, *args], capture_output=True, encoding="utf-8", errors="replace")
            return r.returncode, r.stdout, r.stderr

        def files(rec, report):
            rp, mp = os.path.join(tmp, "rec.json"), os.path.join(tmp, "report.md")
            with open(rp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            with open(mp, "w", encoding="utf-8") as f:
                f.write(report)
            return rp, mp
        ledger = [
            {"id": "L1", "route": "draft", "into": "", "locations": [{"path": "src/a.py", "line": 10, "quote": "q"},
                                                                    {"path": "src/b.py", "line": 7, "quote": "q"}]},
            {"id": "L2", "route": "report", "into": "", "locations": [{"path": "src/c.py", "line": 3, "quote": "q"}]},
            {"id": "L12", "route": "drop", "into": "", "locations": []},
        ]
        rec = {"version": 3, "ledger": ledger}
        # 全部在る（L2 の場所は下書きでないので要らない）
        rp, mp = files(rec, "L1: src/a.py:10 と src/b.py:7\nL2 は報告\nL12 は捨てた\n")
        rc, out, _ = prep("--check-report", rp, mp)
        o = json.loads(out)
        check(rc == 0 and o == {"ok": True, "items": 3, "missingIds": [], "missingLocations": []}, "全部在る %r" % o)
        # id が欠ける（L1 は L12 の頭の一致では数えない）。行が 100 なら 10 は当たらない
        rp, mp = files(rec, "L12 だけ。src/a.py:100 と src/b.py:7\nL2\n")
        rc, out, _ = prep("--check-report", rp, mp)
        o = json.loads(out)
        check(rc == 1 and o["ok"] is False and o["missingIds"] == ["L1"]
              and o["missingLocations"] == [{"id": "L1", "at": "src/a.py:10"}], "欠け %r" % o)
        # 下書きの場所が欠ける
        rp, mp = files(rec, "L1 L2 L12 src/a.py:10\n")
        rc, out, _ = prep("--check-report", rp, mp)
        o = json.loads(out)
        check(rc == 1 and o["missingIds"] == [] and o["missingLocations"] == [{"id": "L1", "at": "src/b.py:7"}], "場所の欠け %r" % o)
        # 版違い・台帳なし・台帳が一覧でない・報告が無い
        for bad in ({"version": 2, "ledger": ledger}, {"version": 3}, {"version": 3, "ledger": "x"}):
            rp, mp = files(bad, "L1\n")
            rc, out, err = prep("--check-report", rp, mp)
            check(rc == 2 and out == "" and err.strip(), "不正な記録 %r rc=%s err=%r" % (bad, rc, err))
        rp, mp = files(rec, "x")
        rc, out, err = prep("--check-report", rp, os.path.join(tmp, "none.md"))
        check(rc == 2 and err.strip(), "報告が無い rc=%s" % rc)
        # Workflow の出力の包みも読める
        rp, mp = files({"summary": "s", "result": rec}, "L1 L2 L12 src/a.py:10 src/b.py:7")
        rc, out, _ = prep("--check-report", rp, mp)
        check(rc == 0, "出力の包みを読めない rc=%s %r" % (rc, out))
        # 排他: PR の番号と同時には使えない
        rc, out, err = prep("7", "--check-report", rp, mp)
        check(rc == 2, "排他 rc=%s" % rc)


def case_sync():
    """--sync: PR のブランチに居て遅れているだけなら PR の先頭まで fast-forward し、それ以外は手元を動かさずに止まる。"""
    def body(e):
        base = e.base_commit(a_DOT_txt="a\n")
        git(e.repo, "switch", "-q", "-c", "feat")
        c1 = commit(e.repo, "c1", b_DOT_txt="1\n")
        c2 = commit(e.repo, "c2", b_DOT_txt="2\n")
        git(e.repo, "push", "-q", "origin", "feat", "feat:refs/pull/7/head")

        def gh(head, ref="feat", cross=False, owner="o"):
            e.set_gh(head, raw=json.dumps({"headRefOid": head, "baseRefName": "main", "headRefName": ref,
                                           "isCrossRepository": cross, "headRepository": {"name": "r"},
                                           "headRepositoryOwner": {"login": owner},
                                           "url": "https://github.com/o/r/pull/7"}))

        def at():
            return git(e.repo, "rev-parse", "HEAD")

        def sync():
            return e.prep("--sync", "7")

        # 既に先頭に居る: 動かさない
        gh(c2)
        rc, o = sync()
        check(rc == 0 and o["ok"] and o["synced"] is False and o["head"] == c2, "同じ head %r" % o)
        # 遅れているだけで、先頭の commit が手元に在る（PR #2574 の形）: 進める
        git(e.repo, "reset", "-q", "--hard", c1)
        rc, o = sync()
        check(rc == 0 and o["synced"] is True and o["from"] == c1 and o["head"] == c2 and o["commits"] == 1
              and o["branch"] == "feat" and at() == c2, "遅れ（手元に在る） %r" % o)
        # 先頭の commit が手元に無い: base の remote の refs/pull/7/head から取って進める
        other = os.path.join(e.tmp, "other")
        subprocess.run([*GIT, "clone", "-q", "-b", "feat", e.origin, other], check=True, capture_output=True)
        c3 = commit(other, "c3", b_DOT_txt="3\n")
        git(other, "push", "-q", "origin", "feat", "feat:refs/pull/7/head")
        gh(c3)
        rc, o = sync()
        check(rc == 0 and o["synced"] is True and o["head"] == c3 and at() == c3, "遅れ（取ってくる） %r" % o)
        # 追跡ファイルに未コミットの変更: 動かさない
        git(e.repo, "reset", "-q", "--hard", c2)
        write(e.repo, "a.txt", "changed\n")
        rc, o = sync()
        check(rc == 1 and o["stop"] == "dirty" and at() == c2, "未コミット %r" % o)
        git(e.repo, "checkout", "-q", "--", "a.txt")
        # 別のブランチ（main は PR の先頭の祖先だが、PR のブランチではない）: 動かさず /catchup を案内する
        git(e.repo, "switch", "-q", "main")
        rc, o = sync()
        check(rc == 1 and o["stop"] == "not-pr-branch" and "/catchup 7" in o["message"] and at() == base, "別のブランチ %r" % o)
        # detached: 動かさない
        git(e.repo, "switch", "-q", "--detach", c2)
        rc, o = sync()
        check(rc == 1 and o["stop"] == "not-pr-branch" and at() == c2, "detached %r" % o)
        # 手元が先に進んでいる・分かれている: 動かさない
        git(e.repo, "switch", "-q", "feat")
        git(e.repo, "reset", "-q", "--hard", c3)
        c4 = commit(e.repo, "c4", d_DOT_txt="4\n")
        rc, o = sync()
        check(rc == 1 and o["stop"] == "ahead" and at() == c4, "先に進んでいる %r" % o)
        git(e.repo, "reset", "-q", "--hard", c2)
        c5 = commit(e.repo, "c5", d_DOT_txt="5\n")
        rc, o = sync()
        check(rc == 1 and o["stop"] == "diverged" and at() == c5, "分かれている %r" % o)
        # fork の PR で head の名前が main: 手元の main は名前が同じでも PR のブランチと見ない
        git(e.repo, "switch", "-q", "main")
        gh(c3, ref="main", cross=True, owner="f")
        rc, o = sync()
        check(rc == 1 and o["stop"] == "not-pr-branch" and at() == base, "fork の main %r" % o)
        # fork の PR を base の refs/pull/7/head で追跡するブランチ（gh pr checkout の形）: 進める
        up = os.path.join(e.tmp, "o", "r.git")
        subprocess.run([*GIT, "clone", "-q", "--bare", e.origin, up], check=True, capture_output=True)
        git(e.repo, "remote", "add", "up", up)
        git(e.repo, "switch", "-q", "-c", "pr7", c2)
        git(e.repo, "config", "branch.pr7.remote", "up")
        git(e.repo, "config", "branch.pr7.merge", "refs/pull/7/head")
        rc, o = sync()
        check(rc == 0 and o["synced"] is True and o["branch"] == "pr7" and at() == c3, "fork の追跡 %r" % o)
        # 排他: PR の番号と同時には使えない
        r = subprocess.run([sys.executable, PREP, "7", "--sync", "7"], cwd=e.repo, env=e.env(), capture_output=True)
        check(r.returncode == 2, "排他が 2 でない")
    if not POSIX:
        return skip("sync")
    with_env(body)


def case_rewritten_base():
    """取り込み先のブランチが書き換わった PR（guided-resolver の #2653）: 取り込み先の前の版の commit を範囲に入れない。"""
    def body(e):
        e.base_commit(a_DOT_txt="a\n")
        git(e.repo, "switch", "-q", "-c", "stack")
        s1 = commit(e.repo, "s1", s_DOT_txt="s\n")
        git(e.repo, "push", "-q", "origin", "stack")
        git(e.repo, "switch", "-q", "-c", "feat")
        f1 = commit(e.repo, "f1", f_DOT_txt="f\n")
        e.set_gh(f1, base="stack")
        # 書き換わる前: merge-base のまま、訳は空
        rc, o = e.prep("7")
        check(rc == 0 and o["base"] == s1 and o["baseNote"] == "" and o["changed"] == ["f.txt"], "書き換わる前 %r" % o)
        # main が進み、取り込み先を main に rebase して force push する（s1 は同じ変更の別の commit になる）
        git(e.repo, "switch", "-q", "main")
        m2 = commit(e.repo, "m2", a_DOT_txt="a2\n")
        git(e.repo, "push", "-q", "origin", "main")
        git(e.repo, "switch", "-q", "stack")
        git(e.repo, "rebase", "-q", "main")
        git(e.repo, "push", "-q", "-f", "origin", "stack")
        git(e.repo, "switch", "-q", "feat")
        rc, o = e.prep("7")
        check(rc == 0 and o["base"] == s1 and o["changed"] == ["f.txt"] and o["commits"] == [f1] and s1[:7] in o["baseNote"],
              "書き換わった取り込み先の前の版の commit が範囲に載った %r" % o)
        # PR のブランチが main を merge で取り込んだ後: 前の版の先頭に同じ物を merge した commit を始まりにする
        git(e.repo, "merge", "-q", "--no-edit", m2)
        mg = git(e.repo, "rev-parse", "HEAD")
        f2 = commit(e.repo, "f2", g_DOT_txt="g\n")
        e.set_gh(f2, base="stack")
        rc, o = e.prep("7")
        made = o.get("base")
        check(rc == 0 and isinstance(made, str) and made not in (s1, m2) and sorted(o["changed"]) == ["f.txt", "g.txt"]
              and sorted(o["commits"]) == sorted([f1, mg, f2]) and s1[:7] in o["baseNote"] and made[:7] in o["baseNote"],
              "merge の後に、取り込み先の前の版と main の変更が範囲に載った %r" % o)
        check(git(e.repo, "rev-parse", made + "^1") == s1 and git(e.repo, "rev-parse", made + "^2") == m2,
              "作った始まりの親が、前の版の先頭と取り込んだ物でない")
        rc, o2 = e.prep("7")
        check(rc == 0 and o2["base"] == made, "同じ先頭から作った始まりが回ごとに変わる %r" % o2)
        # PR 自身の commit が、取り込み先の前の版の commit の下に混ざる（先頭から続かない）: merge-base のままにし、訳を書く
        git(e.repo, "switch", "-q", "-c", "mixed", "origin/main")
        x1 = commit(e.repo, "x1", x_DOT_txt="x\n")
        git(e.repo, "cherry-pick", s1)  # cherry-pick には -q が無い（git 2.43 は使い方の誤りの 129 で止まる）
        x2 = commit(e.repo, "x2", y_DOT_txt="y\n")
        e.set_gh(x2, base="stack")
        rc, o = e.prep("7")
        mb = git(e.repo, "merge-base", "origin/stack", "HEAD")
        check(rc == 0 and o["base"] == mb and x1 in o["commits"] and o["baseNote"] != "", "混ざった形 %r" % o)
    if not POSIX:
        return skip("rewritten-base")
    with_env(body)


CASES = {"env-stop": case_env_stop, "stops": case_stops, "diff": case_diff, "rules": case_rules,
         "prior": case_prior, "quotes": case_quotes, "headless": case_headless,
         "lines": case_lines, "deleted-tests": case_deleted_tests, "rules-wide": case_rules_wide,
         "identity": case_identity, "check-report": case_check_report, "sync": case_sync,
         "rewritten-base": case_rewritten_base}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in CASES:
        print("使い方: my-turn-prep-case.py <%s>" % "|".join(CASES))
        sys.exit(1)
    CASES[sys.argv[1]]()
    print(sys.argv[1].upper().replace("-", "_") + "_OK")
