#!/usr/bin/env python3
"""works-factory プラグインの工場の固定 commit（works-factory/PIN）を、raiki61/works-factory の main の CI が緑の一番新しい commit に
上げる頼みを作る（会社の形 .claude/company.toml の役「工場の版の見張り」のツール）。

works-dispatch の機械窓口のツールとして、`dispatch.py --call 工場の版の見張り works-factory-pin` か、main に入れた後の合図
（[[land.after]]）で呼ばれる。持ち主は定期の起動（cron）を置かないと決めているので、tests/ci-watch.py と同じく main へ入れる動きに乗せる。
上げる物が在れば、その行を出して 1 で終わり、works-dispatch がその出力を添えて役の fallback_role（作業）への頼みに変える。作業の部署は
`python3 scripts/works-factory-pin.py --write` で PIN と CHANGELOG を直し、スキルに効く変更が出ていればスキルを直して、--land で入れる
（版は --land が上げ、配布は --land の後の合図の spread-plugins がする）。

見る物:
- 上げ先: 工場の main のうち PIN より新しい commit を新しい順に見て、check の名 `tests`（工場の .github/workflows/tests.yml の集めの job）が
  緑の最初の物。main の頭の CI が途中か赤なら、その前の緑の commit に上げる
- スキルに効く変更（照合）: 前の PIN と上げ先の 2 つの木を比べ、次を並べる。並んだら、作業の部署はスキルと references を読み直す
  - スキル（works-factory/skills/works-factory の .md）が `` ` `` で引いた語・パスのうち、前の PIN の木に在って上げ先の木に無い物（名前が替わったか消えた）
  - 本線と周の鎖の入力（workflows/line・chain の yaml の頭の inputs）の、足した・消した・中身を変えた名前
  - 工場の殻と bin/lib が読む環境変数（WORKS_FACTORY_*）の、足した・消した名前
  - 工場の README.md・bin の殻（bin/works-factory・bin/apply）の変更

同じ上げ先を何度も頼まない: 知らせた上げ先を代表の clone の git の共通のディレクトリの works-factory-pin.json に覚える。このツールから回した
頼みが開いている間は黙る。閉じた後は、覚えた上げ先と違う上げ先が出たときだけ知らせる（作業の部署が上げずに閉じた上げ先は頼み直さない）。

使い方:
  python3 scripts/works-factory-pin.py < 入力の JSON（省けば {}。{"dry_run": true} なら、知らせる物を出すだけで覚えない）
  python3 scripts/works-factory-pin.py --write [<commit>]   作業の部署の作業場で、PIN と CHANGELOG の [Unreleased] を書き、照合の結果を出す
終了の値: 0 = 上げる物が無い（--write は書いた） / 1 = 上げる物が在る（その行を出す）か、gh・git を読めない / 2 = 入力・引数が読めない
"""

import json
import os
import pathlib
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
# 開いた頼みの見分けは works-dispatch の物をそのまま使う（tests/ci-watch.py と同じ形。写すと割れる）
sys.path.insert(0, str(ROOT / "works-dispatch" / "dispatch"))
from nodes import deliver  # noqa: E402

TOOL = "works-factory-pin"   # 会社の形の [[roles.tools]] の name。works-dispatch が回す頼みの題「ツール <役>/<name> が…」で、このツールの頼みを見分ける
STATE = "works-factory-pin.json"
SOURCE = "works-factory-pin.git"   # 2 つの木を比べるための、工場の取り置き（git の共通のディレクトリの中の bare の clone）
REPO = "raiki61/works-factory"
CHECK = "tests"
PLUGIN = "works-factory"
INPUT_FILES = ("workflows/line/works-factory-line.yaml", "workflows/chain/works-factory-chain.yaml")
FACE_FILES = ("README.md", "bin/works-factory", "bin/apply")
ENV = re.compile(r"WORKS_FACTORY_[A-Z0-9_]+")
SHA = re.compile(r"[0-9a-f]{40}")


def run(argv, cwd=None):
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    return p.returncode, p.stdout or "", p.stderr or ""


def gh_json(path, runner):
    code, out, err = runner(["gh", "api", path])
    if code != 0:
        raise RuntimeError(f"gh api {path} が {code} で終わった: {err.strip()[-300:]}")
    try:
        return json.loads(out)
    except ValueError as e:
        raise RuntimeError(f"gh api {path} の出力を JSON として読めない（{e}）") from e


def read_pin(root):
    pin = (root / PLUGIN / "PIN").read_text(encoding="utf-8").strip()
    if not SHA.fullmatch(pin):
        raise RuntimeError(f"{PLUGIN}/PIN が 40 桁の commit でない: {pin}")
    return pin


def green(sha, runner):
    """check の名 CHECK の run が 1 つ以上在り、全部が決着して成功か。"""
    runs = gh_json(f"repos/{REPO}/commits/{sha}/check-runs?check_name={CHECK}", runner).get("check_runs") or []
    return bool(runs) and all(r.get("status") == "completed" and r.get("conclusion") == "success" for r in runs)


def target(pin, runner):
    """(上げ先の sha, PIN の後の工場の main の commit の並び〔古い順。1 件は (sha, 題)〕)。上げ先が無ければ sha は None。"""
    got = gh_json(f"repos/{REPO}/compare/{pin}...main", runner)
    if got.get("behind_by"):
        raise RuntimeError(f"PIN {pin[:8]} が工場の main の祖先でない（main が {got['behind_by']} 本後ろ。force push か PIN の誤り）")
    commits = [(c["sha"], (c.get("commit", {}).get("message") or "").splitlines()[0] if c.get("commit") else "")
               for c in got.get("commits") or []]
    if len(commits) != got.get("ahead_by", len(commits)):
        raise RuntimeError(f"比べの一覧が {len(commits)} 本で、main の先の本数 {got.get('ahead_by')} と合わない（一覧の上限を超えた）")
    for sha, _ in reversed(commits):
        if green(sha, runner):
            return sha, commits
    return None, commits


def upto(commits, sha):
    """commits の頭から sha までの並び（sha が無ければ None）。"""
    idx = next((i for i, (s, _) in enumerate(commits) if s == sha), None)
    return None if idx is None else commits[:idx + 1]


def prs(commits):
    """題の末尾の (#番号)（工場の squash の merge の形）から、取り込んだ PR の番号の並び。"""
    out = []
    for _, title in commits:
        m = re.search(r"\(#(\d+)\)\s*$", title)
        if m:
            out.append(int(m.group(1)))
    return out


def fetch(cache, url, shas, runner):
    """工場の取り置き（bare）に、shas の木を取ってくる。"""
    if not os.path.isdir(cache):
        code, _, err = runner(["git", "init", "-q", "--bare", cache])
        if code != 0:
            raise RuntimeError(f"工場の取り置き {cache} を作れない: {err.strip()[-300:]}")
    missing = [s for s in shas if runner(["git", "-C", cache, "cat-file", "-e", f"{s}^{{tree}}"])[0] != 0]
    if missing:
        code, _, err = runner(["git", "-C", cache, "fetch", "-q", "--depth", "1", url, *missing])
        if code != 0:
            raise RuntimeError(f"工場の commit を取れない（git fetch {url}）: {err.strip()[-300:]}")


def show(cache, sha, path, runner):
    code, out, _ = runner(["git", "-C", cache, "show", f"{sha}:{path}"])
    return out if code == 0 else None


def has_path(cache, sha, path, runner):
    return runner(["git", "-C", cache, "cat-file", "-e", f"{sha}:{path}"])[0] == 0


def has_text(cache, sha, text, runner):
    return runner(["git", "-C", cache, "grep", "-q", "-F", "-e", text, sha])[0] == 0


def inputs(yaml_text):
    """頭の inputs: の下の 1 段下げの行を、名前から行への辞書に。"""
    found, inside = {}, False
    for line in (yaml_text or "").splitlines():
        if line.startswith("inputs:"):
            inside = True
            continue
        if inside:
            if line and not line.startswith(" "):
                break
            m = re.match(r"  ([A-Za-z_][\w-]*):", line)
            if m:
                found[m.group(1)] = line
    return found


def cited(skill_dir):
    """スキルの .md が `` ` `` で引いた語（4 字以上で、英数字・_・-・/・. だけの物）とパス。"""
    words = set()
    for md in sorted(skill_dir.rglob("*.md")):
        for span in re.findall(r"`([^`\n]+)`", md.read_text(encoding="utf-8")):
            for w in re.findall(r"[A-Za-z0-9_./-]+", span):
                w = w.strip("./")
                if len(w) >= 4 and not w.startswith("$"):
                    words.add(w)
    return sorted(words)


def surface(old, new, cache, runner, root=ROOT):
    """スキルに効く変更の行の並び（空なら照合に当たる物が無い）。"""
    lines = []
    gone = []
    for w in cited(root / PLUGIN / "skills" / PLUGIN):
        if "/" in w:
            if has_path(cache, old, w, runner) and not has_path(cache, new, w, runner):
                gone.append(w)
        elif has_text(cache, old, w, runner) and not has_text(cache, new, w, runner):
            gone.append(w)
    if gone:
        lines.append("スキルが引いた語・パスで、上げ先の工場から消えた物: " + "、".join(gone))
    for f in INPUT_FILES:
        a, b = inputs(show(cache, old, f, runner)), inputs(show(cache, new, f, runner))
        moved = [f"+{k}" for k in sorted(b.keys() - a.keys())] + [f"-{k}" for k in sorted(a.keys() - b.keys())] \
            + [f"~{k}" for k in sorted(a.keys() & b.keys()) if a[k] != b[k]]
        if moved:
            lines.append(f"{f} の inputs の変更（+ 足した・- 消した・~ 中身を変えた）: " + " ".join(moved))
    envs = {}
    for sha in (old, new):
        code, out, _ = runner(["git", "-C", cache, "grep", "-h", "-o", "-E", ENV.pattern, sha, "--", "bin", "lib"])
        envs[sha] = set(ENV.findall(out)) if code in (0, 1) else set()
    moved = [f"+{k}" for k in sorted(envs[new] - envs[old])] + [f"-{k}" for k in sorted(envs[old] - envs[new])]
    if moved:
        lines.append("工場が読む環境変数の変更: " + " ".join(moved))
    code, out, err = runner(["git", "-C", cache, "diff", "--name-only", old, new, "--", *FACE_FILES])
    if code != 0:
        raise RuntimeError(f"工場の 2 つの木を比べられない: {err.strip()[-300:]}")
    if out.strip():
        lines.append("工場の README と殻の変更: " + "、".join(out.split()))
    return lines


def common_dir(runner, root=ROOT):
    code, out, err = runner(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if code != 0 or not out.strip():
        raise RuntimeError(f"git の共通のディレクトリが分からない: {err.strip()[-300:]}")
    return out.strip()


def mine(inbox):
    """このツールから回した頼みのうち、閉じていない物が在るか。頼みの題は works-dispatch が「ツール <役>/<name> が片づけられなかった仕事」で
    付ける（calls.hand_over。形が変わったら tests/works-factory-pin-case.py の title が赤になる）。"""
    marker = f"/{TOOL} "
    rows = deliver.records(inbox)
    ids = {r["id"] for r in rows if r.get("kind") == "ask" and r.get("id") and marker in (r.get("title") or "")}
    return any(r["id"] in ids for r in deliver.open_asks(rows))


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise RuntimeError(f"覚えた上げ先（{path}）を読めない（{e}）。消せば、今の上げ先を知らせ直す") from e
    return got if isinstance(got, dict) else {}


def save_state(path, sha):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"told": sha}, f)
    os.replace(tmp, path)


def url_of():
    return os.environ.get("WORKS_FACTORY_PLUGIN_REPO") or f"https://github.com/{REPO}.git"


def watch(stdin, runner, root):
    raw = stdin.read().strip() or "{}"
    try:
        value = json.loads(raw)
        dry = bool(value.get("dry_run")) if isinstance(value, dict) else None
    except ValueError as e:
        print(f"止めた: 入力を JSON として読めない（{e}）")
        return 2
    if dry is None:
        print("止めた: 入力は JSON のオブジェクトにする")
        return 2
    try:
        pin = read_pin(root)
        to, commits = target(pin, runner)
        if to is None:
            print(f"上げる物は無い（PIN {pin[:8]} の後の工場の main の commit {len(commits)} 本に、CI〔{CHECK}〕が緑の物が無い）"
                  if commits else f"上げる物は無い（PIN {pin[:8]} が工場の main の頭）")
            return 0
        cdir = common_dir(runner, root)
        state_path = os.path.join(cdir, STATE)
        told = load_state(state_path).get("told")
        if mine(deliver.inbox_of(cdir)):
            print(f"上げる物は在る（{to[:8]}）が、このツールから回した頼みが開いているので黙る")
            return 0
        if told == to:
            print(f"上げる物は在る（{to[:8]}）が、前に知らせて頼みが閉じた上げ先と同じなので黙る（作業の部署が上げずに閉じた。工場の main が進めば知らせ直す）")
            return 0
        cache = os.path.join(cdir, SOURCE)
        fetch(cache, url_of(), [pin, to], runner)
        face = surface(pin, to, cache, runner, root)
    except (RuntimeError, OSError) as e:
        print(f"工場の版の見張りが読めなかった: {e}")
        return 1
    head, commits = commits[-1][0], upto(commits, to)
    numbers = prs(commits)
    print(f"工場 {REPO} の main で CI〔{CHECK}〕が緑の {to[:8]} が、{PLUGIN}/PIN の {pin[:8]} より {len(commits)} 本先に在る"
          + (f"（main の頭 {head[:8]} の CI はまだ緑でない）" if head != to else ""))
    print(f"差分: https://github.com/{REPO}/compare/{pin[:12]}...{to[:12]}")
    print("取り込む PR: " + ("・".join(f"#{n}" for n in numbers) if numbers else "（題から番号を拾えなかった）"))
    print("スキルに効く変更の照合: " + ("当たり無し" if not face else f"{len(face)} 件"))
    print("\n".join(f"- {x[:300]}" for x in face))
    # 手順の行は最後に出す（works-dispatch が頼みに載せるのは出力の末尾の行なので）
    print(f"手順: 作業場で python3 scripts/works-factory-pin.py --write {to} を打つ（PIN と CHANGELOG の [Unreleased] を書き、照合の結果の全部を出す）。"
          + ("照合で当たりが在るので、スキル（works-factory/skills/works-factory の SKILL.md と references）を工場の該当の PR と README に"
             "合わせて直し、CHANGELOG の行に利用者に効く違いを書き足してから --land で入れる。" if face else "照合で当たりが無いので、そのまま --land で入れる。")
          + "版は --land が上げ、配布は --land の後の合図がする")
    if not dry:
        save_state(state_path, to)
    return 1


def changelog_line(old, new, numbers):
    got = "・".join(f"raiki61/works-factory#{n}" if i == 0 else f"#{n}" for i, n in enumerate(numbers))
    return (f"- 工場の固定 commit（`works-factory/PIN`）を {new[:8]} に上げた。"
            + (f"取り込んだ PR は {got}。" if numbers else "")
            + f"差分は https://github.com/{REPO}/compare/{old[:12]}...{new[:12]} 。")


def add_changed(text, line):
    """CHANGELOG の [Unreleased] の Changed に 1 行を足した全文。Changed が無ければ [Unreleased] の頭に作る。"""
    head = "## [Unreleased]\n"
    at = text.find(head)
    if at < 0:
        raise RuntimeError("CHANGELOG に ## [Unreleased] の見出しが無い")
    body_from = at + len(head)
    nxt = text.find("\n## [", body_from)
    body_to = len(text) if nxt < 0 else nxt + 1
    body = text[body_from:body_to]
    m = re.search(r"^### Changed\n\n", body, re.M)
    if m:
        body = body[:m.end()] + line + "\n" + body[m.end():]
    else:
        body = "\n### Changed\n\n" + line + "\n" + body
    return text[:body_from] + body + text[body_to:]


def write(argv, runner, root):
    if len(argv) > 1 or (argv and not SHA.fullmatch(argv[0])):
        print("止めた: --write に渡せるのは 40 桁の commit 1 つだけ（省けば今の上げ先）")
        return 2
    try:
        pin = read_pin(root)
        to, commits = target(pin, runner)
        if argv:
            to = argv[0]
            if upto(commits, to) is None:
                raise RuntimeError(f"{to[:8]} が PIN {pin[:8]} の後の工場の main の commit に無い")
            if not green(to, runner):
                raise RuntimeError(f"{to[:8]} の CI〔{CHECK}〕が緑でない")
        if to is None:
            print("上げる物は無い（PIN の後に CI が緑の commit が無い）")
            return 0
        commits = upto(commits, to)
        cache = os.path.join(common_dir(runner, root), SOURCE)
        fetch(cache, url_of(), [pin, to], runner)
        face = surface(pin, to, cache, runner, root)
        log = root / PLUGIN / "CHANGELOG.md"
        log.write_text(add_changed(log.read_text(encoding="utf-8"), changelog_line(pin, to, prs(commits))), encoding="utf-8")
        (root / PLUGIN / "PIN").write_text(to + "\n", encoding="utf-8")
    except (RuntimeError, OSError) as e:
        print(f"止めた: {e}")
        return 1
    print(f"書いた: {PLUGIN}/PIN を {pin[:8]} → {to[:8]}、{PLUGIN}/CHANGELOG.md の [Unreleased] の Changed に 1 行")
    print("取り込んだ commit:")
    print("\n".join(f"- {s[:8]} {t}" for s, t in commits))
    print("スキルに効く変更の照合: " + ("当たり無し" if not face else ""))
    print("\n".join(f"- {x}" for x in face))
    if face:
        print("照合で当たりが在る。スキルと references を工場の PR と README に合わせて直し、CHANGELOG に利用者に効く違いを書き足す")
    return 0


def main(argv=None, stdin=None, runner=run, root=ROOT):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--write"]:
        return write(argv[1:], runner, root)
    if argv:
        print(f"止めた: 知らない引数 {' '.join(argv)}")
        return 2
    return watch(sys.stdin if stdin is None else stdin, runner, root)


if __name__ == "__main__":
    sys.exit(main())
