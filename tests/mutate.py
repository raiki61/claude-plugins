#!/usr/bin/env python3
"""変異の腕を撃つ実行器。腕の一覧は tests/mutations.json（リポジトリに置き、柵を直す差分が同じ変更で腕も直す）。

腕 1 本ごとにリポジトリの写しを一時ディレクトリに作り、その写しの上で 1 か所だけ壊して台本一式を走らせ、赤になるかを見る。
**本物の作業ツリーは触らない。** 壊していない写しでも 1 本走らせて緑を確かめ（control）、全腕の印を 1 つの写しに入れて
走らせ、守る行を実際に通ったかを見る（marker）。赤・control の緑・当たりの証拠の 3 つがそろって、その腕は覆いの証拠になる。
当たりの証拠は、expect を宣言した腕なら「実際に落ちた検査（killedBy）に expect が在る」こと、宣言しない腕なら印が出たこと。
expect を宣言したのに別の検査だけで赤になった腕は、宣言が古いか的外れなので証拠にしない。

定番の変異テストの道具を使わない理由（2026-09-24 に一次情報で確かめた）: この一覧の腕は「ファイルの中の字列 1 か所を置き換える」形で、
Python だけでなく JSON（graph）・Markdown（プロンプト）・シェル（台本）も狙い、腕ごとに落ちるべき検査（expect）と実際に落ちた検査
（killedBy）を突き合わせる。mutmut は .py だけを AST の演算子で変え、pytest を中で走らせる（https://github.com/boxed/mutmut の
src/mutmut/configuration.py・README）。cosmic-ray も Python の AST だけを変え、任意のテストのコマンドは走らせられるが、残すのは終了コード
による KILLED / SURVIVED と生の標準出力だけ（https://github.com/sixty-north/cosmic-ray の src/cosmic_ray/testing.py）。Stryker は
JS / TS / C# / Scala の AST の演算子（https://stryker-mutator.io/docs/mutation-testing-elements/supported-mutators/）。どれも任意の
字列置換の腕と、検査ごとの突合を持たない——報告の形だけを Stryker ほかの共通形式に寄せる（下）。

以前はこの工程を、回す側（LLM）が周ごとに使い捨てのスクリプトで書いていた。置換対象の字列がコードの書き換えで消えた腕は
黙って外れ（2026-09-23 のレビューでは 1 周目に 25 本、2 周目に 18 本）、印の差し込みで写しを構文エラーにする
誤りも 2 度起きた。一覧をリポジトリに置き、`--check` を台本（tests/run.sh）から毎回走らせるので、消えた字列はその変更の
中で赤になる。

使い方:
    python3 tests/mutate.py --check                    # 字列が今の版に 1 か所ずつ在るかだけ（速い。tests/run.sh が呼ぶ）
    python3 tests/mutate.py [-j 6] [--out r.json]      # 全腕を撃つ
    python3 tests/mutate.py --changed-since <rev>      # その版から変わったファイルを狙う腕だけ撃つ
    python3 tests/mutate.py --files a.py,b.py / --only d01,K1a
    python3 tests/mutate.py --reuse prev.json          # 前回の --out から、腕も指紋も変わっていない腕の結果を持ち越す
    python3 tests/mutate.py --gate-efficacy r.json     # --out の結果を review-loop の p1.gate_efficacy の返答の形で印字

--out の形は変異テストの報告の共通形式（mutation-testing-report-schema。Stryker ほかが使う）に寄せる: 腕ごとに
status（Killed / Survived / NoCoverage / Timeout / RuntimeError / Ignored）と、実際に落ちた検査 killedBy。

終了コード: 0 = 撃った腕（1 本以上）が全部、赤・当たりの証拠つきで control が緑（--check なら全腕の字列と証拠の口が在る）
/ 1 = そうでない / 2 = 一覧が読めない。時間切れ・台本が 1 本も当たらなかった腕は赤でなく『走り切らない』
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARMS_FILE = ROOT / "tests" / "mutations.json"
SUITES = {"graphloops": ["bash", "graphloops/tests/run.sh"], "root": ["bash", "tests/run.sh"]}
# 腕に関係する台本だけを走らせる先（graphloops の台本は GL_TEST_ONLY で関数を絞れる）。1 腕ごとに台本一式を回すと
# CPU で約 8 分かかり、全腕では 24 コアでも 1 時間を超えた。関数 1 本なら秒の単位で済む
SCRIPTS = ("graphloops/tests/simulate.py", "graphloops/tests/simulate_review.py")
TIMEOUT = 1500
NO_TEST = "に当たる台本が 1 本も無い"   # graphloops/tests/parallel.py の collect が出す拒否文
# 持ち越しの指紋に入れる台本（腕の結果を決める検査の側）。壊す側のファイルは腕ごとに足す
DRIVERS = ("tests/run.sh", "graphloops/tests/run.sh", "graphloops/tests/parallel.py") + SCRIPTS


def load():
    try:
        return json.loads(ARMS_FILE.read_text(encoding="utf-8"))["arms"]
    except (OSError, ValueError, KeyError) as e:
        print(f"NG {ARMS_FILE} を読めない（{e}）", file=sys.stderr)
        sys.exit(2)


def json_target(doc, path):
    cur = doc
    for k in path:
        cur = cur[k]
    return cur


def suite_source(root, suite):
    """その腕の赤を出しうる台本の本文（root の台本は graphloops の台本も内包する）"""
    files = [f for f in DRIVERS if suite == "root" or f.startswith("graphloops/")]
    return "".join((root / f).read_text(encoding="utf-8") for f in files if (root / f).is_file())


# expect の頭のこの字数が台本の本文に字面で無ければ、その検査はもう無い（描画した値は頭に置かない）。8 字では 141 腕中 62 腕の頭が
# 別の検査名と共有されていた（2026-09-24 の review-graph 1 周目）ので 16 字にした。落ちるのは検査の宣言で、撃ったときの突合は expect 全体
EXPECT_HEAD = 16
# 台本の土台（graphloops/tests/parallel.py）が例外で抜けた台本に付ける行——関数名が台本に在ることで見る
RAISED = re.compile(r"^(test_\w+) が例外で抜けた")


def anchor_problem(root, a, src=None):
    if "auto" in a:
        return ""   # 自動の腕は今の本文から作る（字列の消失が起きない）。証拠は印が持つ
    if not a.get("expect") and not a.get("marker"):
        return "expect も marker も無い（赤が狙いの検査から出たかを見る口が無い）"
    if a.get("expect"):
        src = suite_source(root, a["suite"]) if src is None else src
        m = RAISED.match(a["expect"])
        if m:
            if f"def {m.group(1)}(" not in src:
                return f"expect の台本 {m.group(1)} が {a['suite']} の台本に無い"
        elif a["expect"][:EXPECT_HEAD] not in src:
            return f"expect の頭 {a['expect'][:EXPECT_HEAD]!r} が {a['suite']} の台本に無い（検査の文言が変わったか消えた）"
    p = root / a["file"]
    if not p.is_file():
        return f"file {a['file']} が無い"
    text = p.read_text(encoding="utf-8")
    if "json" in a:
        try:
            t = json_target(json.loads(text), a["json"]["path"])
        except (KeyError, IndexError, TypeError, ValueError) as e:
            return f"json の path が引けない（{type(e).__name__}: {e}）"
        where = "/".join(map(str, a["json"]["path"])) or "頂点"
        if "remove" in a["json"] and a["json"]["remove"] not in t:
            return f"json の {where} に {a['json']['remove']!r} が無い"
        if "del" in a["json"] and a["json"]["del"] not in t:
            return f"json の {where} に鍵 {a['json']['del']!r} が無い"
        return ""
    n = text.count(a["old"])
    return "" if n == 1 else f"old が {n} か所（1 か所であること）"


AUTO_SKIP = ("tests/", "graphloops/tests/")   # 台本は撃たない（tests/mutate.py は腕の実行器そのもので、撃つ）


def auto_targets(rev, root=ROOT):
    """rev からの差分が足した Python の行 ——{相対パス: {行番号}}（未追跡の .py は全行）。git が動かなければ None"""
    g = lambda *a: subprocess.run(["git", "-C", str(root), "-c", "core.quotePath=false", *a], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
    d = g("diff", "-U0", "--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", rev, "--", "*.py")
    new = g("ls-files", "--others", "--exclude-standard", "--", "*.py")
    if d.returncode or new.returncode:
        return None
    out, cur = {}, None
    for line in d.stdout.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
            continue
        m = re.match(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)
        if m and cur:
            s, n = int(m.group(1)), int(m.group(2) or 1)
            out.setdefault(cur, set()).update(range(s, s + n))
    for rel in new.stdout.splitlines():
        if rel.strip() and (root / rel).is_file():
            out[rel] = set(range(1, (root / rel).read_text(encoding="utf-8").count("\n") + 2))
    return {k: v for k, v in out.items() if v and (k == "tests/mutate.py" or not k.startswith(AUTO_SKIP)) and (root / k).is_file()}


def auto_arms_for(rel, text, added):
    """差分が足した行に当たる Python の文と式から、機械で腕を作る（ast の 1 本の規則。形を字面で列挙しない）:
    if の条件は False に、or の各項は False に・and の各項は True に（その項だけで柵が効く形を潰す）、条件式は else の側に、
    raise・式の呼び出し・累算代入（errs += …）の文は pass に。当てる場所は位置（文字の offset）で持つ——字列の一意性に頼らない。
    JSON・Markdown・台本の分岐は対象外（腕の一覧 mutations.json が持つ）"""
    import ast
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))
    off = lambda l, c: starts[l - 1] + len(lines[l - 1].encode("utf-8")[:c].decode("utf-8", "ignore"))   # ast の列はバイト
    span = lambda n: (off(n.lineno, n.col_offset), off(n.end_lineno, n.end_col_offset))
    suite = "graphloops" if rel.startswith("graphloops/") else "root"
    arms = {}

    def add(node, kind, new, stmt=False):
        s, e = span(node)
        aid = f"auto:{rel}:{node.lineno}:{node.col_offset}:{kind}"
        arms[aid] = {"id": aid, "title": f"{kind}: {' '.join(text[s:e].split())[:50]}", "file": rel, "suite": suite,
                     "auto": {"start": s, "end": e, "new": new, "stmt": stmt}}
    for node in ast.walk(tree):
        if getattr(node, "lineno", None) not in added:
            continue
        if isinstance(node, ast.If):
            add(node.test, "cond", "False")
        elif isinstance(node, ast.BoolOp):
            for v in node.values:
                if v.lineno in added:
                    add(v, "or" if isinstance(node.op, ast.Or) else "and", "False" if isinstance(node.op, ast.Or) else "True")
        elif isinstance(node, ast.IfExp):
            s, e = span(node.orelse)
            add(node, "ifexp", f"({text[s:e]})")
        elif isinstance(node, (ast.Raise, ast.AugAssign)) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            add(node, "stmt", "pass", stmt=True)
    return list(arms.values())


def auto_marker(text, a, hits):
    """自動の腕の印の差し込み ——[(位置, 順, 副, 文字列)]（同じ位置では外側の式の包みが外に来る順に並ぶ）。式は評価されたときに印を書く形で包み、文は前の行に印の 1 行を置く。
    文が行の途中から始まる（if x: raise …）ときは差せない（空の一覧）"""
    w = f"__import__('builtins').open({str(hits)!r}, 'a').write({a['id']!r} + '\\n')"
    s, e = a["auto"]["start"], a["auto"]["end"]
    if a["auto"]["stmt"]:
        ls = text.rfind("\n", 0, s) + 1
        return [(ls, 0, 0, f"{text[ls:s]}{w}\n")] if not text[ls:s].strip() else []
    # 同じ位置の頭は内側（終わりが近い）から、閉じは外側（始まりが遠い）から差す——後から差した物が前に来るので、外側が外に残る
    return [(s, 0, e, f"(({w}) and False or ("), (e, 1, s, "))")]


def mutate(root, a):
    p = root / a["file"]
    text = p.read_text(encoding="utf-8")
    if "auto" in a:
        x = a["auto"]
        p.write_text(text[:x["start"]] + x["new"] + text[x["end"]:], encoding="utf-8")
        return
    if "json" in a:
        doc = json.loads(text)
        t = json_target(doc, a["json"]["path"])
        if "remove" in a["json"]:
            t.remove(a["json"]["remove"])
        else:
            t.pop(a["json"]["del"])
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        p.write_text(text.replace(a["old"], a["new"]), encoding="utf-8")


def scratch_dir(tag):
    """腕ごとの作業場。自動の腕の id（auto:<パス>:<行>:<列>:<種類>）は / と : を含むので、そのまま接頭辞にすると
    mkdtemp が在りもしない親ディレクトリを探して落ちる（実測 2026-09-24: 4 周目の差分の検算が 80 本撃った所で全部失った）"""
    return pathlib.Path(tempfile.mkdtemp(prefix=f"mutate-{re.sub(r'[^0-9A-Za-z._-]', '_', tag)}-"))


def copy(tag):
    d = scratch_dir(tag)
    repo = d / "repo"
    # **版に入るファイルだけを写す**（追跡中と、.gitignore に当たらない未追跡）。丸ごと写していた頃は .venv など無視対象まで
    # 腕ごとに複製した
    ls = subprocess.run(["git", "-C", str(ROOT), "-c", "core.quotePath=false", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                        capture_output=True)
    for rel in sorted({x for x in ls.stdout.decode("utf-8", "replace").split("\0") if x}):
        src, dst = ROOT / rel, repo / rel
        if not (src.is_file() or src.is_symlink()):
            continue   # 消したが index に残る物
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            dst.symlink_to(os.readlink(src))
        else:
            shutil.copy2(src, dst)
    # tests/run.sh は git の中で走る前提の検査を持つ——写しに素の repo を作る（コミットは 1 つ）
    for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=m", "-c", "user.email=m@m", "commit", "-qm", "x"]):
        subprocess.run(["git", *c], cwd=repo, capture_output=True)
    return repo, d


def run_group(argv, cwd, env=None, failfast=False):
    """子を自分のプロセスグループで起こし、時間切れならグループごと殺す ——（exit か "timeout", 標準出力＋標準エラー）。
    subprocess.run の timeout は直下の子しか殺さない——実行器そのものを壊した腕では、写しの台本が写しの実行器を呼び、
    殺し損ねた孫が増え続けて全体を時間切れにした（2026-09-23 の 3 周目の撃ち直し）。
    failfast なら最初の FAIL の行でグループごと止めて exit 1 を返す（自動の腕は赤と印で証拠がそろい、どの検査かを要らない）"""
    import threading
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", start_new_session=True)
    late = {"v": False}

    def kill():
        late["v"] = True
        os.killpg(p.pid, signal.SIGKILL)
    timer = threading.Timer(TIMEOUT, kill)
    timer.start()
    out, stopped = [], False
    try:
        for line in p.stdout:
            out.append(line)
            if failfast and line.startswith("  FAIL ") and NO_TEST not in line:
                stopped = True
                os.killpg(p.pid, signal.SIGKILL)
                break
        p.wait()
    finally:
        timer.cancel()
    if late["v"]:
        return "timeout", ""
    return (1 if stopped else p.returncode), "".join(out)


def run_suite(repo, suite, failfast=False):
    rc, body = run_group(SUITES[suite], repo, failfast=failfast)
    if rc == "timeout":
        return {"rc": "timeout", "failed": [f"{TIMEOUT} 秒で打ち切り"], "tail": []}
    failed = [l.strip()[5:].strip() for l in body.splitlines() if l.startswith("  FAIL ")]
    tail = [l for l in body.splitlines() if "件失敗" in l or "件すべて緑" in l or l.startswith("graphloops:")]
    return {"rc": rc, "failed": failed, "tail": tail}


def run_selected(repo, tests):
    """腕の tests（台本 → 関数名）だけを走らせる"""
    rcs, failed = [], []
    for script, fns in tests.items():
        rc, body = run_group([sys.executable, script], repo, env={**os.environ, "GL_TEST_ONLY": ",".join(fns)})
        if rc == "timeout":
            rcs.append("timeout"); continue
        # 絞った名前が台本に 1 本も無いと collect が exit 1 で抜ける——壊した行とは無関係の赤なので、撃てないと言う
        rcs.append("no-test" if NO_TEST in body else rc)
        failed += [l.strip()[5:].strip() for l in body.splitlines() if l.startswith("  FAIL ")]
    bad = [x for x in rcs if x != 0]
    return {"rc": bad[0] if bad else 0, "failed": failed, "tail": [], "selected": True}


def one(a):
    if ignored(a):
        mx = a["python_max"]
        return {"id": a["id"], "title": a["title"], "status": "Ignored", "own": False, "rc": None, "failed": [], "killedBy": [],
                "tail": [f"Python {mx} 以前でしか撃てない（今は {sys.version_info[0]}.{sys.version_info[1]}）"]}
    repo, d = copy(a["id"])
    try:
        mutate(repo, a)
        # 写しの腕の一覧は空にする（marker_run と同じ）——壊した字列は写しの一覧から見て 0 か所なので、写しの tests/run.sh が
        # 走らせる --check が必ず赤になり、生き残った変異を Killed と書いていた
        if a["file"] != "tests/mutations.json" and (repo / "tests" / "mutations.json").is_file():
            (repo / "tests" / "mutations.json").write_text('{"arms": []}\n', encoding="utf-8")
        r = None
        if a.get("tests") and a["suite"] == "graphloops":
            r = run_selected(repo, a["tests"])
            if r["rc"] == 0:   # 絞った台本が気づかなければ、台本一式で確かめ直す（絞りの取りこぼしを緑と言わない）
                r = {**run_suite(repo, a["suite"]), "selected": False}
        if r is None:
            r = {**run_suite(repo, a["suite"], **({"failfast": True} if "auto" in a else {})), "selected": False}
        if r["rc"] in ("timeout", "no-test"):
            return {"id": a["id"], "title": a["title"], "status": "Timeout" if r["rc"] == "timeout" else "RuntimeError",
                    "own": False, **r, "killedBy": [], "failed": r["failed"][:3],
                    "unrunnable": "時間切れ" if r["rc"] == "timeout" else "tests の関数名が台本に無い（--map で結び直せ）"}
        red = r["rc"] != 0
        own = bool(a.get("expect")) and any(f.startswith(a["expect"]) for f in r["failed"])
        return {"id": a["id"], "title": a["title"], "status": "Killed" if red else "Survived", "own": own,
                **r, "killedBy": r["failed"][:20], "failed": r["failed"][:3]}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def control(suites, selected=None):
    """壊していない写しで、撃つときと同じ走らせ方が緑になるか（絞った台本も、絞った形のまま確かめる）"""
    repo, d = copy("control")
    try:
        res = {s: run_suite(repo, s) for s in sorted(suites)}
        if selected:
            res["selected"] = run_selected(repo, selected)
        return res
    finally:
        shutil.rmtree(d, ignore_errors=True)


def marker_run(arms):
    """全腕の印を 1 つの写しに入れて台本を 1 度走らせる。印は挙動を変えない（ファイルへ 1 行書くだけ）。
    差し込む位置は元の本文で全部決めてから後ろから入れる——先に差した印が後の腕の字列を割らない。"""
    repo, d = copy("marker")
    hits = d / "hits.txt"
    plan, placed, skipped = {}, [], {}
    try:
        for a in arms:
            if "auto" in a:
                t = plan.setdefault(a["file"], [(repo / a["file"]).read_text(encoding="utf-8"), []])[0]
                ins = auto_marker(t, a, hits)
                if not ins:
                    skipped[a["id"]] = "文が行の途中から始まる"
                    continue
                plan[a["file"]][1].extend(ins)
                placed.append(a["id"])
                continue
            mk = a.get("marker")
            if not mk or "old" not in a:
                continue
            t = plan.setdefault(a["file"], [(repo / a["file"]).read_text(encoding="utf-8"), []])[0]
            if t.count(a["old"]) != 1:
                skipped[a["id"]] = "old が 1 か所でない"
                continue
            idx = t.index(a["old"]); ls = t.rindex("\n", 0, idx) + 1; le = t.index("\n", idx)
            w = f"open({str(hits)!r}, 'a').write({a['id']!r} + '\\n')"
            cond = mk.get("cond")
            if mk["where"] == "after":
                nxt = t[le + 1:t.index("\n", le + 1)]
                pos, indent = le + 1, nxt[:len(nxt) - len(nxt.lstrip())]
            else:
                line = t[ls:le]
                if line.lstrip().startswith(("or ", "and ", "(", ")")) or not line.strip():
                    skipped[a["id"]] = "式の途中の行"
                    continue
                pos, indent = ls, line[:len(line) - len(line.lstrip())]
            plan[a["file"]][1].append((pos, 0, 0, f"{indent}{('if ' + cond + ': ') if cond else ''}{w}\n"))
            placed.append(a["id"])
        for rel, (t, ins) in plan.items():
            # 後ろから差す。同じ位置では包みの頭（順 0）を先に差し、閉じ（順 1）がその前に来る形にする
            for pos, _, _, s in sorted(ins, key=lambda x: (-x[0], x[1], x[2])):
                t = t[:pos] + s + t[pos:]
            (repo / rel).write_text(t, encoding="utf-8")
        # 印は複数行の old を割るので、写しの中の --check（tests/run.sh が走らせる）が字列の消失で赤になる。
        # 印の写しは『守る行を通ったか』だけを見る所なので、写しの一覧は空にする（本物の一覧は触らない）
        (repo / "tests" / "mutations.json").write_text('{"arms": []}\n', encoding="utf-8")
        r = run_suite(repo, "root")   # tests/run.sh は graphloops の台本も内包する
        seen = sorted(set(hits.read_text(encoding="utf-8").split())) if hits.exists() else []
        return {**r, "failed": r["failed"][:5], "placed": sorted(placed), "seen": seen, "skipped": skipped}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def build_map(arms):
    """腕の expect（赤になるべき検査の名前の頭）を台本の本文から引き、それを含む test_ 関数を腕の tests に書く。
    引けない腕は tests を持たず、台本一式で撃つ"""
    import ast
    src = {s: (ROOT / s).read_text(encoding="utf-8") for s in SCRIPTS}
    spans = {}
    for s, text in src.items():
        tree = ast.parse(text)
        spans[s] = [(n.lineno, n.end_lineno, n.name) for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    hit = 0
    for a in arms:
        a.pop("tests", None)
        e = a.get("expect")
        if not e or a["suite"] != "graphloops":
            continue
        found = {}
        for n in range(min(len(e), 24), 5, -1):   # 描画された文字列の頭のうち、本文に字面で在る最長の部分
            key = e[:n]
            for s, text in src.items():
                for i, line in enumerate(text.splitlines(), 1):
                    if key in line:
                        for lo, hi, name in spans[s]:
                            if lo <= i <= hi:
                                found.setdefault(s, set()).add(name)
            if found:
                break
        if found:
            a["tests"] = {s: sorted(v) for s, v in found.items()}
            hit += 1
    return hit


def changed_since(rev, root=ROOT):
    """その版から変わったファイル（未追跡の新しいファイルも。git diff は未追跡を出さない）"""
    got = set()
    for args in (["diff", "--name-only", rev], ["ls-files", "--others", "--exclude-standard"]):
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")
        if out.returncode != 0:
            print(f"NG 版 {rev} から変わったファイルを引けない（{out.stderr.strip()[:120]}）", file=sys.stderr)
            sys.exit(2)
        got |= set(out.stdout.splitlines())
    return got


def write_empty(out, why):
    """撃てた腕が 0 本の回も --out を書く——--gate-efficacy がそこから not_run（理由つき）を組める。終了コードは 1 のまま
    （0 本を合格と言わない）。書かずに抜けていた頃は、任せ先が --gate-efficacy を打つと読み込みで落ち、返す形が何も無かった"""
    if out:
        pathlib.Path(out).write_text(json.dumps({"schemaVersion": "1", "arms": [], "empty": why}, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8")


def pick(arms, only=None, files=None, since=None, out=None):
    sel = arms
    if only:
        sel = [x for x in sel if x["id"] in set(only.split(","))]
    if files:
        sel = [x for x in sel if x["file"] in set(files.split(","))]
    if since:
        ch = changed_since(since)
        sel = [x for x in sel if x["file"] in ch]
    if not sel:
        why = "撃つ腕が 0 本（絞りの条件に当たる腕が無い。0 本を合格と言わない）"
        write_empty(out, why)
        print(f"NG {why}", file=sys.stderr)
        sys.exit(1)
    return sel


SURVIVED = ("Survived", "NoCoverage")   # 壊しても台本が赤にならなかった腕（NoCoverage は印の行も通らなかった）。腕の結果の正本は status だけ


def healthy(res):
    """撃った回そのものが証拠になる状態か: 壊していない写しが緑で、印の写しも緑"""
    return bool(res.get("summary", {}).get("control_ok")) and (res.get("marker") or {}).get("rc", 1) == 0


def proven(r):
    """腕 1 本が覆いの証拠か: 赤（Killed）で当たりの証拠つき。**終了コード・--gate-efficacy・--reuse は全部これを使う**
    ——3 か所に写していた頃は、印の写しが赤の回や腕 0 本でも gate_efficacy だけ clean を出した"""
    return r.get("status") == "Killed" and bool(r.get("evidence"))


def evaluate(res, sel):
    """撃った結果に状態と当たりの証拠を付け、summary を組む。**expect を宣言した腕の証拠は、実際に落ちた検査（killedBy）に
    expect が在ることだけ**——宣言した検査と別の検査で赤になった腕を、印が出たことで証拠にすると、古い・的外れの宣言が
    黙って通る（実測 2026-09-23: 台本を書き換えた周に古い字列のまま残った expect が 14 腕）"""
    m = res["marker"]
    fresh = [r for r in res["arms"] if not r.get("carried")]
    exp = {x["id"]: x.get("expect") for x in sel}
    for r in fresh:
        if r.get("status") == "Survived" and r["id"] in m["placed"] and r["id"] not in m["seen"]:
            r["status"] = "NoCoverage"   # 印を差した行を台本が一度も通らない
        r["evidence"] = ""
        if r.get("status") == "Killed":
            e = exp.get(r["id"])
            r["evidence"] = (f"killedBy に expect『{e[:40]}』" if r["own"] else "" if e else
                             (f"印 {r['id']} が写しの出力に現れた" if r["id"] in m["seen"] else ""))
    res["summary"] = {"green": [r["id"] for r in fresh if r.get("status") in SURVIVED],
                      "skipped": [r["id"] for r in fresh if r.get("status") == "Ignored"],   # 撃てない腕は status だけで持つ（旗の 2 系統にしない）
                      "unrunnable": [r["id"] for r in fresh if r.get("unrunnable")],
                      "unhit": sorted(set(m["placed"]) - set(m["seen"])),
                      "no_evidence": [r["id"] for r in fresh if r.get("status") == "Killed" and not r["evidence"]],
                      "control_ok": all(v["rc"] == 0 for v in res["control"].values())}
    return res["summary"]


def ignored(a):
    """この Python では撃てない腕か（python_max より新しい版）"""
    mx = a.get("python_max")
    return bool(mx) and sys.version_info[:2] > tuple(int(x) for x in mx.split("."))


def fingerprint(root, a):
    """持ち越してよいかを決める指紋: 腕の定義・壊すファイル・台本一式の本文。どれかが変われば撃ち直す。
    ほかのファイルの変更で結果が変わる腕は拾わない（StrykerJS の incremental と同じ割り切り）——拾うのは週 1 回の全腕
    （.github/workflows/mutation.yml）で、その schedule が止まっていない間だけ（止まる条件と戻し方はそのファイルの頭）"""
    h = hashlib.sha256(json.dumps(a, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    for f in (a["file"],) + DRIVERS:
        p = root / f
        h.update(f.encode("utf-8") + b"\0" + (p.read_bytes() if p.is_file() else b"<none>") + b"\0")
    return h.hexdigest()


def reusable(prev_path):
    """前回の --out から、持ち越せる腕（赤で当たりの証拠つき・control 緑の回）を id → 結果で"""
    try:
        prev = json.loads(pathlib.Path(prev_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"NG 前回の結果 {prev_path} を読めない（{e}）", file=sys.stderr)
        sys.exit(2)
    if not healthy(prev):
        return {}
    return {r["id"]: r for r in prev.get("arms", []) if proven(r) and r.get("fingerprint")}


def gate_efficacy(res):
    """--out の結果を p1.gate_efficacy の返答（material と arms）に組む。判定は proven と healthy だけで、終了コードと同じ。
    この Python では撃てない腕（Ignored）は腕の行に入れず、名前を material に書く（終了コードも Ignored では落とさない）"""
    ok = healthy(res)
    shot = [r for r in res["arms"] if r.get("status") != "Ignored"]
    ign = [f"{r['id']}" for r in res["arms"] if r.get("status") == "Ignored"]
    arms = [{"gate": r.get("file", ""), "arm": f"{r['id']} {r['title']}", "red_confirmed": r.get("status") == "Killed",
             "control_green": ok, "hit_evidence": r.get("evidence") or "",
             **({"note": r.get("unrunnable") or r.get("status")} if not proven(r) else {})} for r in shot]
    note = f"（この Python では撃てない腕: {' '.join(ign)}）" if ign else ""
    if not arms:
        return {"material": {"status": "not_run", "reason": (res.get("empty") or "撃てた腕が 0 本") + note}, "arms": arms}
    short = [x["arm"] for x, r in zip(arms, shot) if not (ok and proven(r))]
    if short:
        mat = {"status": "found", "count": len(short),
               "detail": ("" if ok else "control か印の写しが赤（撃った回そのものが証拠にならない）。") + "証拠にならない腕: " + " / ".join(short) + note}
    else:
        mat = {"status": "clean", "checked": f"tests/mutate.py で {len(arms)} 腕を撃ち、全腕が赤・当たりの証拠つき・control と印の写しが緑" + note}
    return {"material": mat, "arms": arms}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--map", action="store_true", help="腕ごとに関係する台本（test_ 関数）を引いて一覧に書き戻す")
    ap.add_argument("-j", type=int, default=6)
    ap.add_argument("--only")
    ap.add_argument("--files")
    ap.add_argument("--changed-since")
    ap.add_argument("--out")
    ap.add_argument("--auto", metavar="REV", help="REV からの差分が足した Python の文と式から腕を機械で作って撃つ（if の条件・or/and の項・"
                    "条件式・raise・式の呼び出し・累算代入）。腕の一覧に宣言していない入口を生き残りとして出す。--only 等の絞りと併せれば一覧の腕も撃つ")
    ap.add_argument("--reuse", help="前回の --out。腕の定義・壊すファイル・台本一式が同じで、赤と当たりの証拠が在った腕を撃たずに持ち越す")
    ap.add_argument("--gate-efficacy", help="--out の結果を p1.gate_efficacy の返答の形で印字する")
    ap.add_argument("--arms-file", help="腕の一覧の置き場（既定は tests/mutations.json。台本が壊した一覧で --check の赤を見るため）")
    a = ap.parse_args()
    if a.gate_efficacy:
        print(json.dumps(gate_efficacy(json.loads(pathlib.Path(a.gate_efficacy).read_text(encoding="utf-8"))), ensure_ascii=False, indent=1))
        sys.exit(0)
    global ARMS_FILE
    if a.arms_file:
        ARMS_FILE = pathlib.Path(a.arms_file)
    arms = load()
    ids = [x["id"] for x in arms]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if a.map:
        doc = json.loads(ARMS_FILE.read_text(encoding="utf-8"))
        n = build_map(doc["arms"])
        ARMS_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{len(doc['arms'])} 腕のうち {n} 腕に台本を結んだ（残りは台本一式で撃つ）")
        sys.exit(0)
    if a.check:
        srcs = {s: suite_source(ROOT, s) for s in {x["suite"] for x in arms}}
        bad = [(x["id"], why) for x in arms if (why := anchor_problem(ROOT, x, srcs[x["suite"]]))]
        for i in dup:
            print(f"NG 腕の id {i} が重複")
        for i, why in bad:
            print(f"NG 腕 {i}: {why}——柵を直したなら、同じ変更でこの腕も今の字列に直せ")
        print(f"{len(arms)} 腕のうち字列か証拠の口の無い腕 {len(bad)}・id の重複 {len(dup)}")
        sys.exit(1 if bad or dup else 0)
    autos = []
    if a.auto:
        tg = auto_targets(a.auto)
        if tg is None:
            print(f"NG --auto {a.auto}: git diff が取れない", file=sys.stderr)
            sys.exit(2)
        for rel, lines in sorted(tg.items()):
            autos += auto_arms_for(rel, (ROOT / rel).read_text(encoding="utf-8"), lines)
        ids += [x["id"] for x in autos]
    filtered = a.only or a.files or a.changed_since
    if a.auto and not filtered and not autos:
        why = f"撃つ腕が 0 本（--auto {a.auto} からの差分が足した Python の文が無い）"
        write_empty(a.out, why)
        print(f"NG {why}", file=sys.stderr)
        sys.exit(1)
    sel = (pick(arms, a.only, a.files, a.changed_since, out=a.out) if filtered or not a.auto else []) + autos
    srcs = {s: suite_source(ROOT, s) for s in {x["suite"] for x in sel}}
    bad = [(x["id"], why) for x in sel if (why := anchor_problem(ROOT, x, srcs[x["suite"]]))]
    if bad:
        for i, why in bad:
            print(f"NG 腕 {i}: {why}", file=sys.stderr)
        sys.exit(1)
    prev = reusable(a.reuse) if a.reuse else {}
    fps = {x["id"]: fingerprint(ROOT, x) for x in sel}
    carried = [x for x in sel if (prev.get(x["id"]) or {}).get("fingerprint") == fps[x["id"]]]
    fire = [x for x in sel if x not in carried]
    if fire and not carried and all(ignored(x) for x in fire):
        # 撃てる腕が 0 本——写しで control を回す前に止める（pytest が 1 本も集まらなかった回を専用の終了コード 5 で返すのと同じく、0 本を合格と言わない）
        why = f"撃てる腕が 0 本（{len(fire)} 本とも python_max より新しい Python {sys.version_info[0]}.{sys.version_info[1]} では撃てない）"
        write_empty(a.out, why)
        print(f"NG {why}", file=sys.stderr)
        sys.exit(1)
    print(f"撃つ腕 {len(fire)} 本（全 {len(arms)} 本" + (f"・持ち越し {len(carried)} 本" if carried else "") + "）", flush=True)
    res = {"schemaVersion": "1", "arms": [{**prev[x["id"]], "carried": True} for x in carried]}
    pre_marker, unreached = None, []
    if any("auto" in x for x in fire):
        # **自動の腕は、印の写しで一度も通らない行を撃たない**——壊しても台本が気づけない行なので、撃つまでもなく生き残り
        # （NoCoverage。腕の無い入口）。撃つのは通った行の腕だけ（全部を台本一式で撃つと 1 周の修正で 2 時間を超えた）
        pre_marker = marker_run(fire)
        seen = set(pre_marker["seen"])
        unreached = [x for x in fire if "auto" in x and x["id"] not in seen and x["id"] in pre_marker["placed"]]
        fire = [x for x in fire if x not in unreached]
        res_pre = [{"id": x["id"], "title": x["title"], "status": "NoCoverage", "own": False, "rc": None, "failed": [], "killedBy": [],
                    "tail": ["印の写しで一度も通らない行（撃たずに生き残りと数える）"], "file": x["file"], "fingerprint": fps[x["id"]]}
                   for x in unreached]
        print(f"自動の腕: 印の写しで通った {len([x for x in fire if 'auto' in x])} 本を撃つ・通らない {len(unreached)} 本は撃たない", flush=True)
    with cf.ThreadPoolExecutor(max(1, a.j)) as ex:
        union = {}
        for x in fire:
            for s, fns in (x.get("tests") or {}).items():
                union.setdefault(s, set()).update(fns)
        # 撃つ腕が無い（全部持ち越し）回は写しで control を走らせない——持ち越した腕の健全さは前の回の結果が持つ
        fc = ex.submit(control, {x["suite"] for x in fire} | {"root"}, {s: sorted(v) for s, v in union.items()}) if fire else None
        fm = None if pre_marker else (ex.submit(marker_run, fire) if fire else None)   # 全部持ち越しの回は印の写しを走らせない（差す腕が無い）
        fa = {ex.submit(one, x): x for x in fire}
        for f in cf.as_completed(fa):
            r = {**f.result(), "file": fa[f]["file"], "fingerprint": fps[fa[f]["id"]]}
            res["arms"].append(r)
            killed = r.get("status") == "Killed"
            mark = "red  " if killed else "GREEN" if r.get("status") in SURVIVED else "skip "
            print(f"  {mark} {r['id']} {r['title']}" + ("" if r["own"] or not killed else "（赤は別の検査から）"), flush=True)
        res["control"] = fc.result() if fc else {"carried": {"rc": 0}}
        res["marker"] = pre_marker or (fm.result() if fm else {"rc": 0, "failed": [], "tail": [], "placed": [], "seen": [], "skipped": {}})
        res["arms"] += res_pre if pre_marker else []
    res["arms"].sort(key=lambda r: ids.index(r["id"]))
    s = evaluate(res, sel)
    m, green, skipped, unrun, unhit, noev, ctrl_ok = (res["marker"], s["green"], s["skipped"], s["unrunnable"], s["unhit"],
                                                       s["no_evidence"], s["control_ok"])
    fired = len([r for r in res["arms"] if not r.get("carried")]) - len(skipped)
    print(f"control: {'緑' if ctrl_ok else '赤'} / 印: {len(m['seen'])} / {len(m['placed'])} 本が通った（写しは rc={m['rc']}）")
    print(f"赤 {fired - len(green) - len(unrun)} / 緑 {len(green)}: {' '.join(green)}"
          + (f" / 撃てない {len(skipped)}: {' '.join(skipped)}" if skipped else "")
          + (f" / 走り切らない {len(unrun)}: {' '.join(unrun)}" if unrun else "")
          + (f" / 持ち越し {len(carried)}" if carried else ""))
    if unhit:
        print(f"印を差したが通らなかった腕: {' '.join(unhit)}")
    if noev:
        print(f"赤だが当たりの証拠が無い腕（expect を宣言した腕は、落ちた検査に expect が無い）: {' '.join(noev)}")
    res["summary"]["carried"] = [x["id"] for x in carried]
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    shot = [r for r in res["arms"] if r.get("status") != "Ignored"]
    sys.exit(0 if shot and healthy(res) and all(proven(r) for r in shot) else 1)


if __name__ == "__main__":
    main()
