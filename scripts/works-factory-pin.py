#!/usr/bin/env python3
"""works-factory プラグインの工場の固定 commit（works-factory/PIN）を、raiki61/works-factory の main の CI が緑の一番新しい commit に
上げる頼みを作る（会社の形 .claude/company.toml の役「工場の版の見張り」のツール）。

works-dispatch の機械窓口のツールとして、`dispatch.py --call 工場の版の見張り works-factory-pin` か、main に入れた後の合図
（[[land.after]]）で呼ばれる。持ち主は定期の起動（cron）を置かないと決めているので、tests/ci-watch.py と同じく main へ入れる動きに乗せる。
上げる物が在り、スキルに効く変更の照合に当たりが無ければ、AI を立てずに自分で上げる（機械の上げ。land_pin）: 代表の clone に一時の
worktree とブランチ（works-factory-pin/<上げ先の頭 12 字>）を作り、PIN と CHANGELOG を書いて commit し、works-dispatch の --land で main に
入れる（版は --land が上げ、配布は --land の後の合図の spread-plugins がする）。入れたら 0 で終わる。
照合に当たりが在るとき・機械の上げが失敗したときは、その行を出して 1 で終わり、works-dispatch がその出力を添えて役の fallback_role（作業）への
頼みに変える。作業の部署は `python3 scripts/works-factory-pin.py --write` で PIN と CHANGELOG を直し、スキルに効く変更が出ていれば
スキルを直して、--land で入れる。
機械の上げの --land の後の合図は、もう一度このツールを呼ぶ。そのときは環境変数 LANDING（機械の上げが --land に渡す）を見て、工場を読まずに
黙る（工場の main がさらに進んでいれば、次に誰かが main に入れたときに上げる）。

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
終了の値: 0 = 上げる物が無いか、機械の上げで main に入れた（--write は書いた） / 1 = 作業に回す上げが在る（その行を出す）か、gh・git を
読めないか、機械の上げが失敗した / 2 = 入力・引数が読めない
"""

import json
import os
import pathlib
import re
import subprocess
import shutil
import sys
import tempfile
import time

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
# 開いた頼みの見分けは works-dispatch の物をそのまま使う（tests/ci-watch.py と同じ形。写すと割れる）
sys.path.insert(0, str(ROOT / "works-dispatch" / "dispatch"))
import todo  # noqa: E402
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
MAIN = "main"   # claude-plugins のメインブランチ。機械の上げは origin のこのブランチの頭から切る
BRANCH = "works-factory-pin/"   # 機械の上げのブランチの名前の頭（後ろに上げ先の頭 12 字）。--land はこの名前で部署を探す
LANDING = "WORKS_FACTORY_PIN_LANDING"   # 機械の上げが --land に渡す環境変数（値は上げ先）。その --land の合図で呼ばれたこのツールは黙る
LAND_TAIL = 12   # 機械の上げが失敗したときに出す、--land の出力の終わりの行数（頼みに載るのは出力の末尾 20 行なので、上げ先の行から手順の行までをその中に収める）
PAGE = 100   # 比べ（compare）の commit の一覧を 1 回に引く数（GitHub の per_page の上限）。既定の 30 では、31 本より先の main を読み切れない


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
    commits, page = [], 1
    while True:
        got = gh_json(f"repos/{REPO}/compare/{pin}...main?per_page={PAGE}&page={page}", runner)
        if got.get("behind_by"):
            raise RuntimeError(f"PIN {pin[:8]} が工場の main の祖先でない（main が {got['behind_by']} 本後ろ。force push か PIN の誤り）")
        if not isinstance(got.get("ahead_by"), int):
            raise RuntimeError("比べの答えに main の先の本数（ahead_by）が無い")
        rows = got.get("commits") or []
        commits += [(c["sha"], ((c.get("commit") or {}).get("message") or "").splitlines()[:1] or [""]) for c in rows]
        if len(commits) >= got["ahead_by"] or not rows:
            break
        page += 1
    commits = [(sha, title[0]) for sha, title in commits]
    if len(commits) != got["ahead_by"]:
        raise RuntimeError(f"比べの一覧が {len(commits)} 本で、main の先の本数 {got['ahead_by']} と合わない")
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


CODE_DIRS = ("bin", "lib", "workflows")   # 語の消えを探す所。docs・CHANGELOG・README は前の名前を移しの説明に残すので見ない


def has_text(cache, sha, text, runner):
    code, _, err = runner(["git", "-C", cache, "grep", "-q", "-F", "-e", text, sha, "--", *CODE_DIRS])
    if code not in (0, 1):
        raise RuntimeError(f"工場の木 {sha[:8]} を探せない（git grep が {code} で終わった）: {err.strip()[-300:]}")
    return code == 0


def inputs(yaml_text):
    """頭の inputs: の下の項目を、名前からその項目の行（下げの深い続きの行も含む）への辞書に。"""
    found, inside, name = {}, False, None
    for line in (yaml_text or "").splitlines():
        if line.startswith("inputs:"):
            inside = True
            continue
        if not inside or line.startswith("#") or not line.strip():
            continue
        if not line.startswith(" "):
            break
        m = re.match(r"  ([A-Za-z_][\w-]*):", line)
        if m:
            name = m.group(1)
            found[name] = line
        elif name and line.startswith("   "):
            found[name] += "\n" + line
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
        code, out, err = runner(["git", "-C", cache, "grep", "-h", "-o", "-E", ENV.pattern, sha, "--", "bin", "lib"])
        if code not in (0, 1):
            raise RuntimeError(f"工場の木 {sha[:8]} の環境変数を探せない（git grep が {code} で終わった）: {err.strip()[-300:]}")
        envs[sha] = set(ENV.findall(out))
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


def place_dir(runner, place):
    """place の属するリポジトリの git の共通のディレクトリ（git でなければ None）。todo.inboxes_from がほかの会社の受付箱を引くのに渡す。"""
    code, out, _ = runner(["git", "-C", place, "rev-parse", "--path-format=absolute", "--git-common-dir"])
    return os.path.normpath(out.strip()) if code == 0 and out.strip() else None


def mine(inbox, place_common):
    """このツールから回した頼みの (閉じていない物が在るか, 一番新しい頼みの時刻〔Unix 時刻。無ければ None〕)。頼みの題は works-dispatch が
    「ツール <役>/<name> が片づけられなかった仕事」で付ける（calls.hand_over。形が変わったら tests/works-factory-pin-case.py の title が赤になる）。
    閉じたかは --todo と同じく、台帳の行が指すほかの会社の受付箱まで足し合わせた行で見る（todo.inboxes_from。頼み元がほかの会社の会話なら、
    納品の行はその会社の受付箱にだけ在る）。place_common は作業場のパスから git の共通のディレクトリを引く物（git でなければ None）。"""
    marker = f"/{TOOL} "
    _, rows = todo.inboxes_from([inbox], place_common)
    asks = [r for r in rows if r.get("kind") == "ask" and r.get("id") and marker in (r.get("title") or "")]
    ids = {r["id"] for r in asks}
    at = [r["at"] for r in asks if isinstance(r.get("at"), (int, float))]
    return any(r["id"] in ids for r in deliver.open_asks(rows)), (max(at) if at else None)


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise RuntimeError(f"覚えた上げ先（{path}）を読めない（{e}）。消せば、今の上げ先を知らせ直す") from e
    return got if isinstance(got, dict) else {}


def save_state(path, sha, at):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"told": sha, "at": at}, f)
    os.replace(tmp, path)


def url_of():
    return os.environ.get("WORKS_FACTORY_PLUGIN_REPO") or f"https://github.com/{REPO}.git"


def watch(stdin, runner, root, now, env, lander):
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
    if env.get(LANDING):
        print(f"機械の上げ（上げ先 {env[LANDING][:8]}）が打った --land の合図なので黙る（工場の main がさらに進んでいれば、次に main に入れたときに上げる）")
        return 0
    try:
        cdir = common_dir(runner, root)
        # 開いた頼みを先に見る（工場を読めない失敗も頼みに変わるので、読む前に見ないと、失敗が続く間 main に入れるたびに頼みが積まれる）
        still_open, asked_at = mine(deliver.inbox_of(cdir), lambda place: place_dir(runner, place))
        if still_open:
            print("このツールから回した頼みが開いているので黙る")
            return 0
        state_path = os.path.join(cdir, STATE)
        state = load_state(state_path)
        pin = read_pin(root)
        to, commits = target(pin, runner)
        if to is None:
            print(f"上げる物は無い（PIN {pin[:8]} の後の工場の main の commit {len(commits)} 本に、CI〔{CHECK}〕が緑の物が無い）"
                  if commits else f"上げる物は無い（PIN {pin[:8]} が工場の main の頭）")
            return 0
        # 同じ上げ先で黙るのは、知らせた後に頼みが立って閉じた時だけ（頼みが立たなかった知らせは知らせ直す）
        told_at = state.get("at")
        if state.get("told") == to and asked_at is not None and isinstance(told_at, (int, float)) and asked_at >= told_at:
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
    if not dry:
        save_state(state_path, to, now)
    failed = None
    if not face and not dry:
        try:
            landed, said = lander(pin, to, commits, cdir, runner, env)
        except (RuntimeError, OSError) as e:
            failed = str(e)
        else:
            if not landed:
                print(f"機械の上げは打たなかった: {said}")
                return 0
            print(f"機械の上げ: {PLUGIN}/PIN を {pin[:8]} → {to[:8]} に上げて main に入れた（照合に当たり無し。取り込んだ PR: "
                  + ("・".join(f"#{n}" for n in numbers) or "題から番号を拾えなかった") + "）")
            print(said)
            return 0
    print(f"工場 {REPO} の main で CI〔{CHECK}〕が緑の {to[:8]} が、{PLUGIN}/PIN の {pin[:8]} より {len(commits)} 本先に在る"
          + (f"（main の頭 {head[:8]} の CI はまだ緑でない）" if head != to else ""))
    print(f"差分: https://github.com/{REPO}/compare/{pin[:12]}...{to[:12]}")
    print("取り込む PR: " + ("・".join(f"#{n}" for n in numbers) if numbers else "（題から番号を拾えなかった）"))
    print("スキルに効く変更の照合: " + ("当たり無し" if not face else f"{len(face)} 件"))
    print("\n".join(f"- {x[:300]}" for x in face) + ("\n（照合の行は 300 字で切った。全文は --write の出力）" if any(len(x) > 300 for x in face) else ""))
    if failed:
        print(f"機械の上げが失敗した（作業に回す）: {failed}")
    elif dry and not face:
        print("空打ちなので、機械の上げ（照合に当たりが無いので、本当に打てば AI を立てずに main に入れる）は打たない")
    # 手順の行は最後に出す（works-dispatch が頼みに載せるのは出力の末尾の行なので）
    print(f"手順: 作業場で python3 scripts/works-factory-pin.py --write {to} を打つ（PIN と CHANGELOG の [Unreleased] を書き、照合の結果の全部を出す）。"
          + ("照合で当たりが在るので、スキル（works-factory/skills/works-factory の SKILL.md と references）を工場の該当の PR と README に"
             "合わせて直し、CHANGELOG の行に利用者に効く違いを書き足してから --land で入れる。" if face else "照合で当たりが無いので、そのまま --land で入れる。")
          + "版は --land が上げ、配布は --land の後の合図がする")
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
    nxt = re.compile(r"^## \[", re.M).search(text, body_from)
    body_to = len(text) if nxt is None else nxt.start()
    body = text[body_from:body_to]
    m = re.search(r"^### Changed\n\n?", body, re.M)
    if m:
        body = body[:m.end()] + line + "\n" + body[m.end():]
    else:
        body = "\n### Changed\n\n" + line + "\n" + (body if body.strip() else "\n")
    return text[:body_from] + body + text[body_to:]


def put(root, pin, to, commits):
    """PIN を to に替え、CHANGELOG の [Unreleased] の Changed に上げの 1 行を足す。"""
    log = root / PLUGIN / "CHANGELOG.md"
    text = add_changed(log.read_text(encoding="utf-8"), changelog_line(pin, to, prs(commits)))   # 書く前に両方を組む（片方だけ書いて止まらない）
    (root / PLUGIN / "PIN").write_text(to + "\n", encoding="utf-8")
    log.write_text(text, encoding="utf-8")


def must(argv, runner, what):
    code, out, err = runner(argv)
    if code != 0:
        raise RuntimeError(f"{what}（{' '.join(argv[:4])} … が {code} で終わった）: {(err or out).strip()[-300:]}")
    return out


def land_pin(pin, to, commits, cdir, runner, env):
    """機械の上げ: 代表の clone に origin/MAIN の頭から一時の worktree とブランチを作り、PIN と CHANGELOG を書いて commit し、works-dispatch の
    --land で main に入れる。(入れたか, 出す行)。入れたら出す行は --land の出力の終わり。入れる物がもう無い（origin/MAIN の PIN が上げ先か、
    ほかの上げで見張りが読んだ PIN と違う・同じ上げを走らせている処理が居る）なら入れずに訳を返す。入れようとして入らなければ RuntimeError。
    --land はほかの部署と同じ列（会社の形の [land] の queue）に並び、同じゲート（[land] の check）を通る。合図の中から打っても、外の --land は
    push し終えて列の順番を手放した後に合図を呼ぶので、列で待ち合って止まらない。作った worktree とブランチ（--land が push した origin の
    ブランチも）は、入っても入らなくても消す。"""
    dispatch = env.get("WORKS_DISPATCH")
    if not dispatch:
        raise RuntimeError("works-dispatch から呼ばれていない（環境変数 WORKS_DISPATCH が無い）ので、--land を打てない")
    python = env.get("WORKS_DISPATCH_PYTHON") or sys.executable
    source = os.path.dirname(cdir) if os.path.basename(cdir) == ".git" else cdir   # 代表の clone のルート（works-dispatch の gitx.root_of と同じ）
    branch = f"{BRANCH}{to[:12]}"
    must(["git", "-C", source, "fetch", "-q", "origin", MAIN], runner, f"origin の {MAIN} を取り直せない")
    # 見張りが読んだ木（works-dispatch がツールを走らせる一時の場所）は fetch していないので、取り直した origin/MAIN の PIN で決め直す
    code, now_pin, _ = runner(["git", "-C", source, "show", f"origin/{MAIN}:{PLUGIN}/PIN"])
    now_pin = now_pin.strip() if code == 0 else None
    if now_pin == to:
        return False, f"上げ先 {to[:8]} はもう origin の {MAIN} の PIN に入っている（ほかの機械の上げか手の上げが先に入れた）"
    if now_pin != pin:
        return False, (f"origin の {MAIN} の PIN が {(now_pin or '読めない')[:8]} で、見張りが読んだ {pin[:8]} と違う（ほかの上げが先に入った）ので打たない。"
                       "次に main に入れたときの合図で見直す")
    for e in listed(source, runner):
        if e.get("branch") == f"refs/heads/{branch}":
            why = e.get("locked") or ""
            pid = why[len(OWNER):].strip() if why.startswith(OWNER) else ""
            if pid.isdigit() and alive(int(pid)):
                return False, f"同じ上げ先の機械の上げを、ほかの処理（pid {pid}）が走らせているので打たない"
            # 殺された機械の上げの残り（作った処理がもう居ないか、鍵が無い）。消してから作り直す
            runner(["git", "-C", source, "worktree", "remove", "--force", "--force", e["path"]])
    runner(["git", "-C", source, "worktree", "prune"])
    temp = tempfile.mkdtemp(prefix="works-factory-pin-")
    place = os.path.join(temp, "tree")
    try:
        must(["git", "-C", source, "worktree", "add", "-q", "--lock", "--reason", f"{OWNER}{os.getpid()}", "-B", branch, place, f"origin/{MAIN}"],
             runner, "一時の worktree を作れない")
        if runner(["git", "-C", place, "config", "--type=bool", "--get", "extensions.worktreeConfig"])[1].strip() == "true":
            # git は代表の clone の worktree ごとの設定（部署の属性 company.*）を新しい worktree に写すので、本社の部署に見えないように消す
            runner(["git", "-C", place, "config", "--worktree", "--remove-section", "company"])
        root = pathlib.Path(place)
        put(root, pin, to, commits)
        must(["git", "-C", place, "add", f"{PLUGIN}/PIN", f"{PLUGIN}/CHANGELOG.md"], runner, "上げを git に足せない")
        must(["git", "-C", place, "commit", "-q", "-m", f"works-factory: 工場の固定 commit（PIN）を {to[:8]} に上げる（機械の上げ。scripts/works-factory-pin.py）"],
             runner, "上げを commit できない")
        p = subprocess.run([python, dispatch, "--repo", source, "--land", branch], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env={**env, LANDING: to})
        said = "\n".join(((p.stdout or "") + (p.stderr or "")).rstrip().splitlines()[-LAND_TAIL:])
        fetched = runner(["git", "-C", source, "fetch", "-q", "origin", MAIN])[0] == 0
        code, landed, _ = runner(["git", "-C", source, "show", f"origin/{MAIN}:{PLUGIN}/PIN"])
        if code == 0 and landed.strip() == to:
            return True, said
        if not fetched and p.returncode == 0:   # 取り直せないときだけ --land の終了の値に頼る（入ったのに作業に回さない）
            return True, said + f"\n注記: 入れた後に origin の {MAIN} を取り直せなかったので、--land の終了の値 0 で入ったとみた"
        raise RuntimeError(f"--land が main に入れなかった（終了の値 {p.returncode}）。--land の出力の終わり:\n{said}")
    finally:
        left = [what for argv, what in ((["git", "-C", source, "worktree", "remove", "--force", "--force", place], "worktree"),
                                        (["git", "-C", source, "branch", "-D", branch], "ブランチ"))
                if runner(argv)[0] != 0 and (what != "worktree" or os.path.exists(place))]
        if left:
            print(f"注記: 機械の上げの{'と'.join(left)}（{place}・{branch}）を消せなかった。次の機械の上げが残りとして消す")
        # --land はリベースしたブランチを origin に push するので、入らなくても origin に残る。在れば消す（ls-remote の 2 は「無い」）
        code, _, err = runner(["git", "-C", source, "ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"])
        what = "在るかを確かめられなかった" if code not in (0, 2) else None
        if code == 0:
            code, _, err = runner(["git", "-C", source, "push", "-q", "origin", "--delete", branch])
            what = "消せなかった" if code != 0 else None
        if what:
            why = ((err or "").strip().splitlines() or ["訳は出なかった"])[-1]
            print(f"注記: origin の機械の上げのブランチ {branch} が{what}（{why}）。在れば手で git push origin --delete {branch} を打つ")
        shutil.rmtree(temp, ignore_errors=True)


OWNER = "works-factory-pin pid "   # 機械の上げの worktree の鍵の訳。後ろに作った処理の pid（works-dispatch の nodes/tools.py の OWNER と同じ形）


def alive(pid):
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def listed(source, runner):
    """代表の clone の worktree の並び（git worktree list --porcelain）。1 件は {path, branch, locked}。読めなければ空。"""
    code, out, _ = runner(["git", "-C", source, "worktree", "list", "--porcelain"])
    rows = []
    for line in (out if code == 0 else "").splitlines():
        if line.startswith("worktree "):
            rows.append({"path": line[len("worktree "):], "branch": None, "locked": None})
        elif rows and line.startswith("branch "):
            rows[-1]["branch"] = line[len("branch "):]
        elif rows and (line == "locked" or line.startswith("locked ")):
            rows[-1]["locked"] = line[len("locked "):]
    return rows


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
        put(root, pin, to, commits)
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


def main(argv=None, stdin=None, runner=run, root=ROOT, now=None, env=None, lander=land_pin):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--write"]:
        return write(argv[1:], runner, root)
    if argv:
        print(f"止めた: 知らない引数 {' '.join(argv)}")
        return 2
    return watch(sys.stdin if stdin is None else stdin, runner, root, time.time() if now is None else now,
                 os.environ if env is None else env, lander)


if __name__ == "__main__":
    sys.exit(main())
