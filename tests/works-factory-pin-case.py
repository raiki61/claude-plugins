#!/usr/bin/env python3
"""scripts/works-factory-pin.py（役「工場の版の見張り」のツール）を、gh を偽物にし、工場を一時の git のリポジトリで作って回す。

使い方: python3 tests/works-factory-pin-case.py <場合>
- target: PIN の後の工場の main の commit を新しい順に見て、CI（tests）が緑の最初の物を上げ先にする。頭が途中なら前の緑に、緑が無ければ
  0 で黙る。PIN が頭なら 0。知らせる時は 1 で終わり、手順の行を最後に出す。dry_run は覚えない
- told: 知らせた上げ先は、このツールから回した頼みが開いている間は黙り、閉じた後も同じ上げ先なら黙る。上げ先が進めば知らせ直す
- surface: スキルが引いた語・パスのうち前の木に在って上げ先の木に無い物、本線の inputs の出入り、WORKS_FACTORY_* の出入り、README と殻の
  変更を拾う。どれにも当たらない上げは「当たり無し」
- write: --write が PIN を上げ先に替え、CHANGELOG の [Unreleased] の Changed に PR の番号と差分の URL の 1 行を足す（Changed が無ければ作る）。
  緑でない commit・PIN の後に無い commit の名指しは書かずに止める
- unreadable: gh が落ちたら黙らず 1 で知らせる。入力が JSON のオブジェクトでなければ 2
- title: works-dispatch が頼みに付ける題の形が、このツールの見分ける形のまま（calls.hand_over の字を見る）
"""

import importlib.util
import io
import json
import os
import pathlib
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

- 前の行
"""


def tmp():
    base = os.environ.get("CLAUDE_JOB_DIR")
    where = os.path.join(base, "tmp") if base else None
    if where:
        os.makedirs(where, exist_ok=True)
    return tempfile.mkdtemp(prefix="works-factory-pin-", dir=where)


def git(cwd, *argv):
    return subprocess.run(["git", "-C", cwd, *argv], check=True, capture_output=True, text=True).stdout.strip()


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
            after = self.shas[self.shas.index(pin) + 1:]
            return 0, json.dumps({"ahead_by": len(after), "behind_by": 0,
                                  "commits": [{"sha": s, "commit": {"message": self.titles.get(s, "t") + "\n\n本文"}} for s in after]}), ""
        sha = path.split("/commits/")[1].split("/")[0]
        return 0, json.dumps({"check_runs": self.checks.get(sha, [])}), ""


def ok():
    return [{"name": "tests", "status": "completed", "conclusion": "success"}]


def go(fake, root, value="{}", argv=()):
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        code = wp.main(argv=list(argv), stdin=io.StringIO(value), runner=fake, root=root)
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
    check(code == 1 and f"緑の {shas[2][:8]}" in out and "2 本先" not in out and "1 本先" in out, f"頭が途中の時に前の緑を選ばない: {code} {out}")
    check("main の頭" in out and "#13" in out and "#14" not in out, f"頭の CI の注記か取り込む PR が違う: {out}")
    check(out.strip().splitlines()[-1].startswith("手順: ") and shas[2] in out.strip().splitlines()[-1], f"手順の行が最後に無い: {out}")
    check(not os.path.exists(os.path.join(d, wp.STATE)), "dry_run なのに覚えた")
    fake.checks = {}
    code, out = go(fake, root)
    check(code == 0 and "緑の物が無い" in out, f"緑が無いのに黙らない: {code} {out}")
    fake, root, shas, d = world(3, {})
    code, out = go(fake, root)
    check(code == 0 and "main の頭" in out, f"PIN が頭なのに黙らない: {code} {out}")
    print("TARGET_OK")


def told():
    ask = {"kind": "ask", "status": "queued", "id": "20261026-000000-aaaaaa", "title": TITLE}
    fake, root, shas, d = world(1, {2: ok()})
    check(go(fake, root)[0] == 1, "最初の上げ先を知らせない")
    with open(os.path.join(d, *wp.deliver.INBOX, wp.deliver.LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps(ask, ensure_ascii=False) + "\n")   # works-dispatch が出力を頼みに変えた形
    with open(os.path.join(d, wp.STATE), encoding="utf-8") as f:
        check(json.load(f)["told"] == shas[2], "知らせた上げ先を覚えない")
    code, out = go(fake, root)
    check(code == 0 and "開いている" in out, f"頼みが開いているのに知らせ直した: {code} {out}")
    with open(os.path.join(d, *wp.deliver.INBOX, wp.deliver.LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "deliver", "ask": ask["id"], "at": 1.0}) + "\n")
    code, out = go(fake, root)
    check(code == 0 and "同じ" in out, f"閉じた後に同じ上げ先を知らせ直した: {code} {out}")
    fake.checks[shas[3]] = ok()
    code, out = go(fake, root)
    check(code == 1 and f"緑の {shas[3][:8]}" in out, f"上げ先が進んだのに知らせ直さない: {code} {out}")
    print("TOLD_OK")


def surface():
    fake, root, shas, d = world(0, {1: ok()})
    code, out = go(fake, root, '{"dry_run": true}')
    check(code == 1, f"上げ先を知らせない: {code} {out}")
    for want in ("消えた物: ", "design_only", "lib/carry.py", "WORKS_FACTORY_OLD", "+design_talk -design_only",
                 "+WORKS_FACTORY_NEW -WORKS_FACTORY_OLD", "README.md、bin/works-factory", "照合で当たりが在る"):
        check(want in out, f"照合に {want} が無い: {out}")
    check("CLAUDE_PLUGIN_ROOT" not in out and "request" not in out, f"工場に関わらない語か、変わらない入力を拾った: {out}")
    fake, root, shas, d = world(1, {2: ok()})
    code, out = go(fake, root, '{"dry_run": true}')
    check(code == 1 and "照合: 当たり無し" in out and "そのまま --land" in out, f"lib の中だけの上げで当たりを出した: {out}")
    print("SURFACE_OK")


def write():
    fake, root, shas, d = world(1, {2: ok(), 3: ok()})
    code, out = go(fake, root, argv=["--write", shas[2]])
    check(code == 0 and (root / "works-factory" / "PIN").read_text() == shas[2] + "\n", f"名指した commit に PIN を替えない: {code} {out}")
    log = (root / "works-factory" / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = log.split("## [Unreleased]\n")[1].split("## [0.1.0]")[0]
    check(f"\n### Changed\n\n- 工場の固定 commit（`works-factory/PIN`）を {shas[2][:8]} に上げた。取り込んだ PR は raiki61/works-factory#13。" in unreleased
          and f"/compare/{shas[1][:12]}...{shas[2][:12]}" in unreleased, f"Unreleased の Changed の行が違う: {unreleased}")
    check(log.count("- 前の行") == 1 and "## [0.1.0] - 2026-10-01\n\n### Changed\n\n- 前の行" in log, f"前の版の記録を崩した: {log}")
    code, out = go(fake, root, argv=["--write"])
    check(code == 0 and (root / "works-factory" / "PIN").read_text() == shas[3] + "\n", f"省いた時に今の上げ先に替えない: {out}")
    log = (root / "works-factory" / "CHANGELOG.md").read_text(encoding="utf-8")
    check(log.count("### Changed") == 2 and log.index(shas[3][:8]) < log.index(shas[2][:8]), f"既に在る Changed に足さない: {log}")
    fake, root, shas, d = world(1, {2: ok()})
    for bad, why in ((shas[3], "緑でない"), (shas[0], "無い"), ("abc", "40 桁")):
        code, out = go(fake, root, argv=["--write", bad])
        check(code in (1, 2) and why in out and (root / "works-factory" / "PIN").read_text() == shas[1] + "\n", f"{bad} を書いた: {code} {out}")
    print("WRITE_OK")


def unreadable():
    fake, root, shas, d = world(1, {2: ok()})
    fake.broken = True
    code, out = go(fake, root)
    check(code == 1 and "読めなかった" in out and "HTTP 502" in out, f"gh の失敗を黙った: {code} {out}")
    fake.broken = False
    for bad in ("[1]", "{"):
        code, out = go(fake, root, bad)
        check(code == 2, f"読めない入力 {bad} を 2 で止めない: {code} {out}")
    print("UNREADABLE_OK")


def title():
    src = (ROOT / "works-dispatch" / "dispatch" / "calls.py").read_text(encoding="utf-8")
    check("\"title\": f\"ツール {role_name}/{tool['name']} が片づけられなかった仕事\"" in src,
          "works-dispatch の calls.hand_over が頼みに付ける題の形が変わった。scripts/works-factory-pin.py の mine の見分けと TITLE を合わせる")
    print("TITLE_OK")


if __name__ == "__main__":
    {"target": target, "told": told, "surface": surface, "write": write, "unreadable": unreadable, "title": title}[sys.argv[1]]()
