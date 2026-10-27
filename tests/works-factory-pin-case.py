#!/usr/bin/env python3
"""scripts/works-factory-pin.py（役「工場の版の見張り」のツール）を、gh を偽物にし、工場を一時の git のリポジトリで作って回す。

使い方: python3 tests/works-factory-pin-case.py <場合>
- target: PIN の後の工場の main の commit を新しい順に見て、CI（tests）が緑の最初の物を上げ先にする。頭が途中なら前の緑に、緑が無ければ
  0 で黙る。PIN が頭なら 0。知らせる時は 1 で終わり、手順の行を最後に出す。dry_run は覚えない
- told: 知らせた上げ先は、このツールから回した頼みが開いている間は黙り、閉じた後も同じ上げ先なら黙る。知らせた後に頼みが立っていなければ
  知らせ直す。上げ先が進めば知らせ直す
- surface: スキルが引いた語・パスのうち前の木に在って上げ先の木に無い物、本線の inputs の出入り、WORKS_FACTORY_* の出入り、README と殻の
  変更を拾う。どれにも当たらない上げは「当たり無し」
- write: --write が PIN を上げ先に替え、CHANGELOG の [Unreleased] の Changed に PR の番号と差分の URL の 1 行を足す（Changed が無ければ作る）。
  緑でない commit・PIN の後に無い commit の名指しは書かずに止める
- unreadable: gh が落ちたら黙らず 1 で知らせる。ただし、このツールの頼みが開いていれば gh を読む前に黙る。入力が JSON のオブジェクトでなければ 2
- page: 比べの一覧をページで繰り、main の先の本数（ahead_by）まで読む
- edges: CHANGELOG の Changed の空行の無い形・Unreleased が最後のセクションの形、inputs の下げた続きの行と列 0 のコメント
- title: works-dispatch が頼みに付ける題の形が、このツールの見分ける形のまま（calls.hand_over の字を見る）
- auto: 照合に当たりが無い上げは、代表の clone に作ったブランチで PIN と CHANGELOG を commit し、--land（偽物の dispatch.py）で main に入れて
  0 で終わる。--land が入れなければ 1 で作業に回し、手順の行を最後に出す。どちらも作ったブランチと worktree を消す。照合に当たりが在れば
  機械の上げを打たない。機械の上げの --land の合図で呼ばれたら工場を読まずに黙る
"""

import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("works_factory_pin", ROOT / "scripts" / "works-factory-pin.py")
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)

TITLE = f"ツール 工場の版の見張り/{wp.TOOL} が片づけられなかった仕事"
SKILL = """# works-factory

起動は `${CLAUDE_PLUGIN_ROOT}/bin/works-factory` で、`--input design_only=true` を付ける。
依頼の全項目は `lib/carry.py` の `parts()`。鍵は `WORKS_FACTORY_OLD` で選ぶ。
"""
LOG = """# 変更の記録

## [Unreleased]

## [0.1.0] - 2026-10-01

### Changed

- old line
"""


def tmp():
    base = os.environ.get("CLAUDE_JOB_DIR")
    where = os.path.join(base, "tmp") if base else None
    if where:
        os.makedirs(where, exist_ok=True)
    return tempfile.mkdtemp(prefix="works-factory-pin-", dir=where)


def git(cwd, *argv):
    return subprocess.run(["git", "-C", cwd, *argv], check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def factory():
    """工場の見本: (リポジトリ, [A, B, C, D] の sha)。A→B で名前の替わり・消し・README と殻の変更、B→C・C→D は lib の中だけ。"""
    d = os.path.join(tmp(), "factory")
    os.makedirs(d)
    git(d, "init", "-q")

    def put(files, msg):
        for name, body in files.items():
            p = os.path.join(d, name)
            if body is None:
                os.remove(p)
                continue
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
        git(d, "add", "-A")
        git(d, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-qm", msg)
        return git(d, "rev-parse", "HEAD")

    line = "name: line\ninputs:\n  request: {default: ''}\n  {name}: {{default: ''}}\nnodes:\n  - id: x\n"
    a = put({"README.md": "readme\n", "bin/works-factory": "env WORKS_FACTORY_OLD\n", "lib/carry.py": "def parts(): pass\n",
             "workflows/line/works-factory-line.yaml": line.replace("{name}", "design_only").replace("{{", "{").replace("}}", "}")},
            "first")
    b = put({"README.md": "readme 2\n", "bin/works-factory": "env WORKS_FACTORY_NEW\n", "lib/carry.py": None,
             "workflows/line/works-factory-line.yaml": line.replace("{name}", "design_talk").replace("{{", "{").replace("}}", "}")},
            "#10 名前を替える (#11)")
    c = put({"lib/other.py": "x = 1\n"}, "#12 中だけ (#13)")
    e = put({"lib/other.py": "x = 2\n"}, "中だけ その 2 (#14)")
    return d, [a, b, c, e]


def plugin(pin):
    root = pathlib.Path(tmp()) / "root"
    skill = root / "works-factory" / "skills" / "works-factory"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL, encoding="utf-8")
    (root / "works-factory" / "PIN").write_text(pin + "\n", encoding="utf-8")
    (root / "works-factory" / "CHANGELOG.md").write_text(LOG, encoding="utf-8")
    return root


def setup(asks=()):
    d = tmp()
    inbox = os.path.join(d, *wp.deliver.INBOX)
    os.makedirs(inbox)
    with open(os.path.join(inbox, wp.deliver.LOG), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(a, ensure_ascii=False) + "\n" for a in asks)
    return d


class Fake:
    """gh の偽物と、git の共通のディレクトリの答え。ほかの git は本物を打つ。shas は工場の main の commit（古い順）、checks は sha ごとの
    check の run の並び（無ければ空）。"""

    def __init__(self, gitdir, shas, titles, checks, broken=False):
        self.gitdir, self.shas, self.titles, self.checks, self.broken = gitdir, shas, titles, checks, broken

    def __call__(self, argv, cwd=None):
        if argv[0] == "git":
            if "--git-common-dir" in argv:
                return 0, self.gitdir + "\n", ""
            return wp.run(argv)
        if self.broken:
            return 1, "", "HTTP 502"
        path = argv[2]
        if "/compare/" in path:
            pin = path.split("/compare/")[1].split("...")[0]
            query = dict(q.split("=") for q in path.split("?")[1].split("&"))
            size, page = int(query["per_page"]), int(query["page"])
            after = self.shas[self.shas.index(pin) + 1:]
            rows = after[(page - 1) * size:page * size]
            return 0, json.dumps({"ahead_by": len(after), "behind_by": 0,
                                  "commits": [{"sha": s, "commit": {"message": self.titles.get(s, "t") + "\n\n本文"}} for s in rows]}), ""
        sha = path.split("/commits/")[1].split("/")[0]
        return 0, json.dumps({"check_runs": self.checks.get(sha, [])}), ""


def ok():
    return [{"name": "tests", "status": "completed", "conclusion": "success"}]


def go(fake, root, value="{}", argv=(), now=100.0, env=None, lander=wp.land_pin):
    """env を省けば空（WORKS_DISPATCH が無いので、機械の上げは打てずに作業に回る）。"""
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        code = wp.main(argv=list(argv), stdin=io.StringIO(value), runner=fake, root=root, now=now, env={} if env is None else env,
                       lander=lander)
    finally:
        sys.stdout = old
    return code, out.getvalue()


def check(cond, msg):
    if not cond:
        print(f"NG {msg}")
        sys.exit(1)


def world(pin_at, checks, asks=()):
    repo, shas = factory()
    os.environ["WORKS_FACTORY_PLUGIN_REPO"] = repo
    titles = dict(zip(shas, ["first", "#10 名前を替える (#11)", "#12 中だけ (#13)", "中だけ その 2 (#14)"]))
    d = setup(asks)
    return Fake(d, shas, titles, {shas[i]: v for i, v in checks.items()}), plugin(shas[pin_at]), shas, d


def target():
    fake, root, shas, d = world(1, {2: ok(), 3: [{"name": "tests", "status": "in_progress", "conclusion": None}]})
    code, out = go(fake, root, '{"dry_run": true}')
    last = out.strip().splitlines()[-1]
    check(code == 1 and f"--write {shas[2]} " in last, f"頭が途中の時に前の緑を選ばないか、手順の行が最後に無い: {code} {out}")
    check(shas[3][:8] in out and "#13" in out and "#14" not in out, f"頭の CI の注記か取り込む PR が違う: {out}")
    check(not os.path.exists(os.path.join(d, wp.STATE)), "dry_run なのに覚えた")
    fake.checks = {}
    code, out = go(fake, root)
    check(code == 0 and shas[2][:8] not in out, f"緑が無いのに黙らない: {code} {out}")
    fake, root, shas, d = world(3, {})
    code, out = go(fake, root)
    check(code == 0, f"PIN が頭なのに黙らない: {code} {out}")
    print("TARGET_OK")


def told():
    ask = {"kind": "ask", "status": "queued", "id": "20261026-000000-aaaaaa", "title": TITLE, "at": 201.0}
    fake, root, shas, d = world(1, {2: ok()})
    check(go(fake, root)[0] == 1, "最初の上げ先を知らせない")
    code, out = go(fake, root, now=200.0)
    check(code == 1, f"知らせた後に頼みが立っていないのに黙った: {code} {out}")
    with open(os.path.join(d, *wp.deliver.INBOX, wp.deliver.LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps(ask, ensure_ascii=False) + "\n")   # works-dispatch が出力を頼みに変えた形
    with open(os.path.join(d, wp.STATE), encoding="utf-8") as f:
        check(json.load(f)["told"] == shas[2], "知らせた上げ先を覚えない")
    code, out = go(fake, root)
    check(code == 0, f"頼みが開いているのに知らせ直した: {code} {out}")
    with open(os.path.join(d, *wp.deliver.INBOX, wp.deliver.LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "deliver", "ask": ask["id"], "at": 1.0}) + "\n")
    code, out = go(fake, root)
    check(code == 0, f"閉じた後に同じ上げ先を知らせ直した: {code} {out}")
    fake.checks[shas[3]] = ok()
    code, out = go(fake, root)
    check(code == 1 and f"--write {shas[3]} " in out, f"上げ先が進んだのに知らせ直さない: {code} {out}")
    print("TOLD_OK")


def surface():
    fake, root, shas, d = world(0, {1: ok()})
    code, out = go(fake, root, '{"dry_run": true}')
    check(code == 1, f"上げ先を知らせない: {code} {out}")
    for want in ("design_only", "lib/carry.py", "WORKS_FACTORY_OLD", "+design_talk -design_only",
                 "+WORKS_FACTORY_NEW -WORKS_FACTORY_OLD", "README.md", "bin/works-factory"):
        check(want in out, f"照合に {want} が無い: {out}")
    check("CLAUDE_PLUGIN_ROOT" not in out and "request" not in out, f"工場に関わらない語か、変わらない入力を拾った: {out}")
    fake, root, shas, d = world(1, {2: ok()})
    code, out = go(fake, root, '{"dry_run": true}')
    face = wp.surface(shas[1], shas[2], os.path.join(d, wp.SOURCE), fake, root)
    check(code == 1 and face == [], f"lib の中だけの上げで当たりを出した: {face} {out}")
    print("SURFACE_OK")


def write():
    fake, root, shas, d = world(1, {2: ok(), 3: ok()})
    code, out = go(fake, root, argv=["--write", shas[2]])
    check(code == 0 and (root / "works-factory" / "PIN").read_text() == shas[2] + "\n", f"名指した commit に PIN を替えない: {code} {out}")
    log = (root / "works-factory" / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = log.split("## [Unreleased]\n")[1].split("## [0.1.0]")[0]
    line = re.search(r"\A\n### Changed\n\n- [^\n]*`works-factory/PIN`[^\n]*" + shas[2][:8] + r"[^\n]*raiki61/works-factory#13[^\n]*/compare/"
                     + shas[1][:12] + r"\.\.\." + shas[2][:12] + r"[^\n]*\n\n\Z", unreleased)
    check(line is not None, f"Unreleased の Changed の行が違う: {unreleased}")
    check(log.count("- old line") == 1 and "## [0.1.0] - 2026-10-01\n\n### Changed\n\n- old line" in log, f"前の版の記録を崩した: {log}")
    code, out = go(fake, root, argv=["--write"])
    check(code == 0 and (root / "works-factory" / "PIN").read_text() == shas[3] + "\n", f"省いた時に今の上げ先に替えない: {out}")
    log = (root / "works-factory" / "CHANGELOG.md").read_text(encoding="utf-8")
    check(log.count("### Changed") == 2 and log.index(shas[3][:8]) < log.index(shas[2][:8]), f"既に在る Changed に足さない: {log}")
    fake, root, shas, d = world(1, {2: ok()})
    for bad, want in ((shas[3], 1), (shas[0], 1), ("abc", 2)):
        code, out = go(fake, root, argv=["--write", bad])
        check(code == want and (root / "works-factory" / "PIN").read_text() == shas[1] + "\n", f"{bad} を書いた: {code} {out}")
    print("WRITE_OK")


def unreadable():
    fake, root, shas, d = world(1, {2: ok()})
    fake.broken = True
    code, out = go(fake, root)
    check(code == 1 and "HTTP 502" in out, f"gh の失敗を黙った: {code} {out}")
    with open(os.path.join(d, *wp.deliver.INBOX, wp.deliver.LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "ask", "status": "queued", "id": "20261026-000000-bbbbbb", "title": TITLE, "at": 1.0}) + "\n")
    code, out = go(fake, root)
    check(code == 0, f"頼みが開いているのに gh の失敗を知らせ直した: {code} {out}")
    fake.broken = False
    for bad in ("[1]", "{"):
        code, out = go(fake, root, bad)
        check(code == 2, f"読めない入力 {bad} を 2 で止めない: {code} {out}")
    print("UNREADABLE_OK")


def page():
    shas = [f"{i:040x}" for i in range(1, 2 * wp.PAGE + 12)]
    fake = Fake(tmp(), shas, {}, {shas[-1]: ok()})
    to, commits = wp.target(shas[0], fake)
    check(to == shas[-1] and len(commits) == len(shas) - 1, f"ページを繰って main の先まで読まない: {to} {len(commits)}")
    print("PAGE_OK")


def edges():
    for text in ("# x\n\n## [Unreleased]\n### Changed\n- old\n", "# x\n\n## [Unreleased]\n\n### Changed\n\n- old\n\n## [0.1.0]\n"):
        got = wp.add_changed(text, "- new")
        check(got.count("### Changed") == 1 and got.index("- new") < got.index("- old"), f"在る Changed の頭に足さない: {got!r}")
    got = wp.add_changed("# x\n\n## [Unreleased]\n", "- new")
    check(re.search(r"## \[Unreleased\]\n\n### Changed\n\n- new\n", got) is not None, f"最後のセクションの Unreleased に Changed を作らない: {got!r}")
    yaml = "inputs:\n# 列 0 の注記\n  a:\n    default: x\n  b: {default: y}\nnodes:\n  c: 1\n"
    got = wp.inputs(yaml)
    check(sorted(got) == ["a", "b"] and "default: x" in got["a"], f"下げた続きの行か列 0 の注記で読み違えた: {got}")
    print("EDGES_OK")


def title():
    src = (ROOT / "works-dispatch" / "dispatch" / "calls.py").read_text(encoding="utf-8")
    check("\"title\": f\"ツール {role_name}/{tool['name']} が片づけられなかった仕事\"" in src,
          "works-dispatch の calls.hand_over が頼みに付ける題の形が変わった。scripts/works-factory-pin.py の mine の見分けと TITLE を合わせる")
    print("TITLE_OK")


# 偽物の dispatch.py: --repo <代表の clone> --land <ブランチ> を受け、引数と LANDING を記録に書き、push するなら ブランチを origin の main に push する
FAKE_DISPATCH = """import os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["PIN_CASE_RECORD"], "a", encoding="utf-8") as f:
    f.write(" ".join(args) + " " + os.environ.get("%s", "") + "\\n")
if os.environ.get("PIN_CASE_PUSH") == "1":
    subprocess.run(["git", "-C", args[1], "push", "-q", "origin", args[3] + ":main"], check=True)
    print("FAKE_LAND_PUSHED")
else:
    print("FAKE_LAND_RED")
    sys.exit(1)
""" % wp.LANDING


def plugins(pin):
    """claude-plugins の見本: (代表の clone のルート, origin の bare)。main に PIN・CHANGELOG・スキルを置く。"""
    base = tmp()
    origin, source = os.path.join(base, "origin.git"), os.path.join(base, "source")
    git(base, "init", "-q", "--bare", "-b", "main", origin)
    git(base, "clone", "-q", origin, source)
    git(source, "config", "user.name", "T")
    git(source, "config", "user.email", "t@example.invalid")
    git(source, "checkout", "-q", "-b", "main")
    made = plugin(pin)
    shutil.copytree(made / "works-factory", os.path.join(source, "works-factory"))
    git(source, "add", "-A")
    git(source, "commit", "-qm", "first")
    git(source, "push", "-q", "origin", "main")
    os.makedirs(os.path.join(source, ".git", *wp.deliver.INBOX))
    return source, origin


def auto():
    repo, shas = factory()
    os.environ["WORKS_FACTORY_PLUGIN_REPO"] = repo
    titles = dict(zip(shas, ["first", "#10 名前を替える (#11)", "#12 中だけ (#13)", "中だけ その 2 (#14)"]))
    script = os.path.join(tmp(), "dispatch.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(FAKE_DISPATCH)
    record = os.path.join(tmp(), "record")
    env = {**os.environ, "WORKS_DISPATCH": script, "WORKS_DISPATCH_PYTHON": sys.executable, "PIN_CASE_RECORD": record}

    def leftovers(source):
        branches = git(source, "branch", "--list", wp.BRANCH + "*")
        trees = [x for x in git(source, "worktree", "list", "--porcelain").splitlines() if x.startswith("worktree ")]
        return branches, len(trees)

    # 入れられる --land: main の PIN が上げ先になり、0 で終わる
    source, origin = plugins(shas[1])
    fake = Fake(os.path.join(source, ".git"), shas, titles, {shas[2]: ok()})
    code, out = go(fake, pathlib.Path(source), env={**env, "PIN_CASE_PUSH": "1"})
    check(code == 0 and "FAKE_LAND_PUSHED" in out and "#13" in out, f"照合に当たりの無い上げを機械で入れない: {code} {out}")
    check(git(origin, "show", "main:works-factory/PIN") == shas[2], f"origin の main の PIN が上げ先でない: {out}")
    log = git(origin, "show", "main:works-factory/CHANGELOG.md")
    check(f"`works-factory/PIN`）を {shas[2][:8]} に上げた" in log and "raiki61/works-factory#13" in log, f"CHANGELOG に上げの行が無い: {log}")
    with open(record, encoding="utf-8") as f:
        said = f.read()
    check(f"--repo {source} --land {wp.BRANCH}{shas[2][:12]} {shas[2]}" in said, f"--land の引数か {wp.LANDING} が違う: {said}")
    check(leftovers(source) == ("", 1), f"作ったブランチか worktree が残った: {leftovers(source)}")
    # 入れられない --land: 1 で作業に回し、手順の行を最後に出す
    source, origin = plugins(shas[1])
    fake = Fake(os.path.join(source, ".git"), shas, titles, {shas[2]: ok()})
    code, out = go(fake, pathlib.Path(source), env=env)
    check(code == 1 and "FAKE_LAND_RED" in out, f"--land の失敗を作業に回さない: {code} {out}")
    check(f"--write {shas[2]} " in out.strip().splitlines()[-1], f"手順の行が最後に無い: {out}")
    check(git(origin, "show", "main:works-factory/PIN") == shas[1], "入れられなかったのに main の PIN が変わった")
    check(leftovers(source) == ("", 1), f"失敗の後に作ったブランチか worktree が残った: {leftovers(source)}")
    # 照合に当たりが在る上げは機械で打たない
    called = []
    fake, root, shas2, d = world(0, {1: ok()})
    code, out = go(fake, root, env=env, lander=lambda *a: called.append(a))
    check(code == 1 and not called, f"照合に当たりが在るのに機械の上げを打った: {code} {called} {out}")
    # 機械の上げの --land の合図で呼ばれたら、工場を読まずに黙る（gh を壊しておき、読めば 1 になる）
    fake.broken = True
    code, out = go(fake, root, env={wp.LANDING: shas2[1]})
    check(code == 0, f"機械の上げの合図で黙らない: {code} {out}")
    print("AUTO_OK")


if __name__ == "__main__":
    {"target": target, "told": told, "surface": surface, "write": write, "unreadable": unreadable, "page": page, "edges": edges,
     "title": title, "auto": auto}[sys.argv[1]]()
