#!/usr/bin/env python3
"""変異の腕を撃つ実行器。腕の一覧は tests/mutations.json（リポジトリに置き、柵を直す差分が同じ変更で腕も直す）。

腕 1 本ごとにリポジトリの写しを一時ディレクトリに作り、その写しの上で 1 か所だけ壊して台本を走らせ、赤になるかを見る（走らせるのは、
腕の tests か印の写しで行を通した台本が分かればその台本だけ、分からなければ台本一式）。自動の腕（--auto）は台本の前に pytest の段を
持つ: 印の写しで pytest（graphloops/tests/py）が行を通していれば、先に通したテストだけ（帰属できない・import の時の行なら pytest 一式）を
撃ち、赤なら Killed で打ち切る。緑なら台本をいつもどおり撃つ（網は台本だけの頃より狭まらない）。台本が通らず pytest だけが通す行は
台本を撃たない。Google の変異テストがその行を覆うテストだけを走らせるのと同じ形（Petrović ほか "Practical Mutation Testing at Scale"
arXiv:2102.11378 §2.1-2.2）。
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

自動の腕（--auto: auto_targets・auto_arms_for・auto_marker）は Python の AST で壊すので、上の理由は当たらない。cosmic-ray には
差分の行に絞る cr-filter-git と、全変異に共通のテストのコマンドが在り、そこは同じ機能である。それでも使わない理由は 3 つ
（2026-09-25 に一次情報で確かめた）。(1) 作業ツリーをその場で書き換える: 変異は src/cosmic_ray/mutating.py の
MutationVisitor.mutate_path が対象ファイルを開いて上書きし、util.py の restore_contents が finally で書き戻す。写しを作る仕組みは無く、
分散実行で衝突しないのは各 worker が別に用意した複製を持つ前提（公式 tutorials/distributed）。review-loop は P1 の前後で作業ツリーを
突き合わせ、書き換えを止めるので、写しは結局こちらで作ることになる。(2) 通らない行を撃つ前に外す口が無い: 公式の filter は
cr-filter-pragma・cr-filter-operators・cr-filter-git だけで（how-tos/filters）、被覆で未到達の変異を除く物は無い。自動の腕は印の写し
1 回で通らない行を外し（NoCoverage。印の写しが緑の回だけ）、撃つ数を減らす。(3) どの検査が落ちたかを残さない: src/cosmic_ray/work_item.py の WorkResult が
持つのは test_outcome・worker_outcome・生の output・diff で、落ちた検査の名前（killedBy）を持たない。自動の腕も一覧の腕と同じ --out に
入り、--gate-efficacy と --reuse を 1 本で通す。依存を足さない配布方針（issue #6）は配布する実行時の決定で、開発用の CI までは縛らない
——だから理由に数えない。

**mutmut との受け持ち**（2026-09-27 から。人の決定: 変異の関門は pytest を中心にする）: 差分の行の腕（--auto）は、pytest の
テストも台本も、この実行器が撃つ（上の pytest の段。行ごとの覆いは印の写しで取る——coverage の動的 context は Python 3.14 の既定の
core で使えず、子のプロセスにテストの名前を運ばないので使わない）。mutmut は、pytest が覆うモジュール（graphloops/engine/schema.py。
設定は graphloops/setup.cfg）を差分に依らず丸ごと撃ち、生き残りを pytest 側のテストで殺す道具として残す。撃つのは CI で、手元では
撃たない（人の方針。載せる workflow は別の変更。設定と回し方は graphloops/README.md の「検査」節）。一覧の腕（字列置換・expect と killedBy の突合）は expect が台本の
検査の名前なので、台本だけで撃つ。週 1 回の CI（mutation.yml）で落とす柵もこの実行器に在る。

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
    python3 tests/mutate.py --auto <rev>               # 一覧の腕に加えて、<rev> からの差分が足した Python の文と式の腕も撃つ
                                                       # （1 行 1 本・効かない行は外す。--every-node で全部の節。pytest の段を先に撃つ）
    python3 tests/mutate.py --confirm-survivors        # 絞った台本・絞った pytest が緑の腕を、台本一式・pytest 一式で確かめ直す（版を出す前の関門・週 1 回の全腕）
    python3 tests/mutate.py --deadline-at <ISO 時刻>   # その時刻までに書き終える（残った腕は pending。--reuse で続きから）
    python3 tests/mutate.py --gate-efficacy r.json     # --out の結果を review-loop の p1.gate_efficacy の返答の形で印字

--out の形は変異テストの報告の共通形式（mutation-testing-report-schema。Stryker ほかが使う）に寄せる: 腕ごとに
status（Killed / Survived / NoCoverage / Timeout / RuntimeError / Ignored）と、実際に落ちた検査 killedBy。共通形式の外の欄は
empty（撃てた腕 0 本の理由）・partial（撃つ途中の版。腕 1 本ごとに書き直す）・pending（期限で撃たずに残った腕）・pruned（1 行 1 本と
効かない行の規則で作らなかった自動の腕と理由）・marker_unhealthy（印の写しが赤で、通らない行を決めなかった理由。そのとき通らなかった
自動の腕は status が Pending で unrunnable に理由）・worktree_moved（基点を写した後に作業ツリーで変わった、腕の結果を決めるファイル。
撃った結果は基点の版の物で、終了コードと証拠には使わない）の 6 つと、印の写しの detail（赤の回の検査ごとの本文と出力の末尾）と、腕ごとの cover（印の写しで行を通した台本。? は帰属できない印）と
attribution（赤の出どころ: narrowed＝絞った台本から / unrelated＝絞った台本は緑で一式の確かめ直しだけ赤 / unattributed＝一式だけで撃った /
pytest＝行を通した pytest のテストから / pytest_whole＝pytest 一式だけで撃った / pytest_unrelated＝絞った pytest は緑で pytest 一式の確かめ直しだけ赤）と、
自動の腕の pytest_cover（印の写しで行を通した pytest のテストの node id）・pytest（pytest の段の結果と撃ち方 how）・pytest_selected（pytest を
絞って緑）・pytest_only（台本が行を通さない腕）、印の写しの pytest・pytest_seen・pytest_cover・script_seen（seen は台本と pytest の和）、
control の pytest（腕が撃つテストのファイルの和。赤なら pytest の赤だけを証拠にしない）、pytest の段を足さなかった理由 pytest_stage（--gate-efficacy の material にも出る）。
止める信号（SIGTERM・SIGINT・SIGHUP）を受けたら、起こした子のグループと写しを片付けて 128＋信号の番号で抜ける。

写しの置き場: 1 回の起動が一時ディレクトリの下に根（mutate-run-*）を 1 つ持ち、隣のロックのファイル（<根>.lock）を起動の間握る
（flock。Windows は msvcrt.locking。どちらも無い OS はロック無しで、前の起動の根を拾わない）。起動の頭で作業ツリーを根の下の基点に
1 回だけ写し、腕・control・印の写しは全部基点から作る（同じ回の写しが同じ版を見る）。--auto と --changed-since の差分・腕の字列の
検査も基点から取る（本物の index を写した一時の index と GIT_WORK_TREE で、基点を git の作業ツリーとして読む）。写しの中で
起こす子には TMPDIR を写しの作業場の下に向けて渡す（入れ子の実行器・台本の一時物も作業場ごと消える）。根は終わるときに消し、
SIGKILL などで残った根は、次の起動がロックの解けた物だけを消す（期限で死とみなさない。旧形式の mutate-<tag>-* は触らない）。

終了コード: 0 = 撃った腕（1 本以上）が全部、赤・当たりの証拠つきで control が緑（--check なら全腕の字列と証拠の口が在る）
/ 1 = そうでない / 2 = 一覧が読めない。時間切れ・台本が 1 本も当たらなかった腕は赤でなく『走り切らない』
"""
import argparse
import atexit
import collections
import concurrent.futures as cf
import copy as copymod
import datetime
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
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARMS_FILE = ROOT / "tests" / "mutations.json"
# bash は PATH の順で引く。裸の名前を Popen に渡すと、Windows では CreateProcess が PATH より先にシステムのディレクトリを探し、
# Git の bash でなく C:\Windows\System32\bash.exe（WSL の起動口）に当たりうる（posix では execvp と同じ結果）
BASH = shutil.which("bash") or "bash"
SUITES = {"graphloops": [BASH, "graphloops/tests/run.sh"], "root": [BASH, "tests/run.sh"]}
# 腕に関係する台本だけを走らせる先（graphloops の台本は GL_TEST_ONLY で関数を絞れる）。1 腕ごとに台本一式を回すと
# CPU で約 8 分かかり、全腕では 24 コアでも 1 時間を超えた。関数 1 本なら秒の単位で済む
SCRIPTS = ("graphloops/tests/simulate.py", "graphloops/tests/simulate_review.py")
TIMEOUT = 1500
# --deadline-at の期限の手前に残す幅（秒）。最後の腕が終わってから、任せ先が --gate-efficacy を組んで返答を書くまでの分
TAIL = 300
NO_TEST = "に当たる台本が 1 本も無い"   # graphloops/tests/parallel.py の collect が出す拒否文
# 持ち越しの指紋に入れる台本（腕の結果を決める検査の側）。壊す側のファイルは腕ごとに足す
DRIVERS = ("tests/run.sh", "graphloops/tests/run.sh", "graphloops/tests/parallel.py") + SCRIPTS
# 止める信号を受けたとき、起こした子のグループへ SIGTERM → SIGKILL を送る間の猶予（秒）。engine（graphloops/engine/role_run.py の
# KILL_GRACE）がこの実行器を止めるときは SIGTERM の 5 秒後に SIGKILL を送るので、2 段の猶予と写しの掃除がその前に済む幅にする
STOP_GRACE = 1
# 印の写しで『どの台本が行を通したか』を読む書式。正本は graphloops/tests/parallel.py（TEST_THREAD・TAG）で、ここはその写し
# （揃いは tests/run.sh の mut-owner の検査が縛る）。同じプロセスの中はスレッドの名前、子のプロセスは作業場の名前の印で見分ける
OWNER_THREAD = "gl-test~"
OWNER_DIR = re.compile(r"GLT~([^~/\\]+)~([^~/\\]+)~")
UNKNOWN = "?"   # 帰属できない印（台本の外のスレッド・作業場の外の cwd・bash の台本）。1 つでも在る腕は台本一式で撃つ
# 自動の腕を前段で撃つ pytest の置き場と起こし方の頭。版の固定は対象リポジトリの宣言（.review-checks.json の suite の pytest の段）と
# 同じ——宣言の段の名前は札で意味を持たないので宣言からは引かず、揃いは tests/run.sh の mut-pytest の検査が縛る
PYDIR = "graphloops/tests/py"
PYTEST = ["uv", "run", "--no-project", "--with", "pytest==9.1.1", "--with", "pytest-xdist==3.8.0", "python", "-m", "pytest"]
PYTEST_WORKERS = "4"   # ファイル単位・一式で撃つ回の -n。node id で絞る回は 0（worker を起こす分の方が重い）
# 印の写しの pytest の回だけ、テストの node id（pytest.ini の置き場から見た形）を運ぶ環境変数。書くのは graphloops/tests/py/conftest.py、
# 読むのは mark_write の印の 4 つ目の欄（揃いは graphloops/tests/py/test_mutate_mark.py が縛る）。回の外の印（収集の時の import）は ?
PYTEST_MARK = "GL_MARK_PYTEST"
# node id を並べた引数がこの字数を超える腕は、テストのファイル単位に落とす（Windows の cmd の 8191 字・CreateProcess の 32767 字の手前）
ARGV_MAX = 8000
PYTEST_RED = re.compile(r"^(?:FAILED|ERROR) (.+?)(?: - .*)?$")   # -ra の短い要約の行（pytest.ini の addopts）
PYTEST_STAGE = False   # 自動の腕に pytest の段を足すか（main が pytest_ready で立てる。台本が import して使う回は立たない）

_LIVE, _LOCK = set(), threading.Lock()   # 生きている子（Popen）。止める信号で木ごと止める先
STOPPING = threading.Event()


class Stopped(BaseException):
    """止める信号（SIGTERM・SIGINT・SIGHUP）を受けた。子のグループは stop_groups で止めてある。BaseException の派生にするのは、
    腕の中の Exception を捕まえる口に飲まれず main まで抜けるため（engine の role_run.StopSignal と同じ形）"""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def stop_groups():
    """生きている子のグループを全部止める。**全グループへ先に同じ信号を送ってから 1 回だけ待つ**——1 本ずつ待つと、-j の本数ぶん
    待つ間に止める側（engine）の SIGKILL がこの実行器に届き、後ろのグループと写しが残る"""
    if not hasattr(os, "killpg"):
        return
    with _LOCK:
        live = list(_LIVE)

    def alive(p):
        p.poll()   # 長を回収する（回収しない長はゾンビのままグループに残り、消滅が見えない）
        try:
            os.killpg(p.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for p in live:
            try:
                os.killpg(p.pid, sig)
            except OSError:
                pass
        end = time.monotonic() + STOP_GRACE
        while live and time.monotonic() < end:
            live = [p for p in live if alive(p)]
            if live:
                time.sleep(0.05)
        if not live:
            return


def install_stop_handlers():
    """止める信号を受けたら、子のグループを止めてから Stopped を上げる。子は run_group が別のプロセスグループに切り離すので、この実行器に
    届いた信号は子に届かない——ここで止めないと、写しの中の台本が親の居ないまま走り続ける（実測 2026-09-26 06:37: CPU 76%）"""
    def stop(signum, _frame):
        if STOPPING.is_set():
            return   # 片付けの最中に届いた 2 度目の信号は、片付けを中断させない
        STOPPING.set()
        stop_groups()
        raise Stopped(signum)
    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)


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


def auto_targets(rev, root=ROOT, env=None):
    """rev からの差分が足した Python の行 ——{相対パス: {行番号}}（未追跡の .py は全行）。git が動かなければ None。
    基点から取るときは root に基点、env に base_git() を渡す"""
    g = lambda *a: subprocess.run(["git", "-C", str(root), "-c", "core.quotePath=false", *a], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", env=env)
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


# 1 行に 1 本だけ残すときの種類の順（先の種類を残す）。同じ種類なら列の小さい方
KIND_ORDER = ("cond", "or", "and", "ifexp", "stmt")
# 効かない行（Google の arid ノード）: 呼び出しの文のうち、壊しても検査が見る値を変えない物。このリポジトリの検査は CLI の出力と
# trace を読むので、print・標準エラー・trace は入れない（0.21.0 の関門で print の文の腕は 6 本中 5 本が Killed）
ARID_CALLS = ("time.sleep", "warnings.warn")
ARID_RECEIVERS = ("logging", "log", "logger", "LOG")


def _dotted(f):
    import ast
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
        return ".".join(reversed(parts))
    return ""


def arid(node):
    """効かない文か（ログ・警告・待ちの呼び出しの文）"""
    import ast
    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
        return ""
    name = _dotted(node.value.func)
    if name in ARID_CALLS or ("." in name and name.split(".")[0] in ARID_RECEIVERS):
        return name
    return ""


def auto_arms_for(rel, text, added, every=False, pruned=None):
    """差分が足した行に当たる Python の文と式から、機械で腕を作る（ast の 1 本の規則。形を字面で列挙しない）:
    if の条件は False に、or の各項は False に・and の各項は True に（その項だけで柵が効く形を潰す）、条件式は else の側に、
    raise・式の呼び出し・累算代入（errs += …）の文は pass に。当てる場所は位置（文字の offset）で持つ——字列の一意性に頼らない。
    JSON・Markdown・台本の分岐は対象外（腕の一覧 mutations.json が持つ）。

    **既定は Google 型に絞る**（Petrović と Ivanković "State of Mutation Testing at Google" ICSE-SEIP 2018 の §3・§4）: 1 行に 1 本
    （KIND_ORDER の順で決定的に選ぶ。Google は無作為に選ぶが、--reuse の指紋を再現できるようにする）、効かない行（arid）の腕は
    作らない。外した腕は pruned（渡されれば）に理由つきで積む——撃たなかった腕を記録から見えるようにする。every なら絞らない（今の撃ち方）"""
    import ast
    tree = ast.parse(text)
    # 関数の本体の行（import の時に走る行は、最初に import した台本にしか印が付かないので、台本の絞りに使わない）
    bodies = [(n.body[0].lineno, n.end_lineno) for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.body]
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
                     "auto": {"start": s, "end": e, "new": new, "stmt": stmt,
                              "in_function": any(lo <= node.lineno <= hi for lo, hi in bodies)},
                     "_line": node.lineno, "_rank": (KIND_ORDER.index(kind), node.col_offset),
                     "_arid": arid(node) if stmt else ""}
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
    out, drop = list(arms.values()), []
    if not every:
        keep = {}
        for x in out:
            if x["_arid"]:
                drop.append((x, f"効かない行（{x['_arid']} の呼び出し）"))
            elif x["_line"] not in keep or x["_rank"] < keep[x["_line"]]["_rank"]:
                keep[x["_line"]] = x
        drop += [(x, f"1 行 1 本（同じ行の {keep[x['_line']]['id']} を撃つ）") for x in out
                 if not x["_arid"] and keep[x["_line"]] is not x]
        out = [x for x in out if x in keep.values()]
    if pruned is not None:
        pruned += [{"id": x["id"], "title": x["title"], "file": x["file"], "reason": why} for x, why in drop]
    for x in out:
        for k in ("_line", "_rank", "_arid"):
            x.pop(k)
    return out


def mark_write(hits, aid):
    """印の 1 行を書く式: 腕の id・スレッドの名前・cwd・pytest のテスト（PYTEST_MARK。台本の回は空）をタブで区切る
    （どの台本が通したかは owner_of が、どの pytest のテストかは read_hits が読む）"""
    return (f"__import__('builtins').open({str(hits)!r}, 'a').write({aid!r} + '\\t' + __import__('threading').current_thread().name"
            f" + '\\t' + __import__('os').getcwd() + '\\t' + __import__('os').environ.get({PYTEST_MARK!r}, '') + '\\n')")


def owner_of(thread, cwd):
    """印の行を書いた台本（'<台本のファイル名>~<関数名>'）。見分けられなければ UNKNOWN"""
    if thread.startswith(OWNER_THREAD):
        return thread[len(OWNER_THREAD):]
    m = OWNER_DIR.search(cwd)
    return f"{m.group(1)}~{m.group(2)}" if m else UNKNOWN


def read_hits(hits, pytest=False):
    """印のファイル → (通った腕の id の一覧, 腕 → 通した台本の一覧)。pytest なら pytest の回の行（4 つ目の欄が在る）だけを読み、
    腕 → 通したテストの node id（帰属できなければ ?）の一覧を返す。台本の回の行は 4 つ目の欄が空"""
    cover = {}
    if hits.exists():
        for ln in hits.read_text(encoding="utf-8").splitlines():
            aid, _, rest = ln.partition("\t")
            thread, _, rest = rest.partition("\t")
            cwd, _, node = rest.partition("\t")
            if not aid.strip() or bool(node) != pytest:
                continue
            cover.setdefault(aid.strip(), set()).add(node if pytest else owner_of(thread, cwd))
    return sorted(cover), {k: sorted(v) for k, v in cover.items()}


def auto_marker(text, a, hits):
    """自動の腕の印の差し込み ——[(位置, 順, 副, 文字列)]（同じ位置では外側の式の包みが外に来る順に並ぶ）。式は評価されたときに印を書く形で包み、文は前の行に印の 1 行を置く。
    文が行の途中から始まる（if x: raise …）ときは差せない（空の一覧）"""
    w = mark_write(hits, a["id"])
    s, e = a["auto"]["start"], a["auto"]["end"]
    if a["auto"]["stmt"]:
        ls = text.rfind("\n", 0, s) + 1
        return [(ls, 0, 0, f"{text[ls:s]}{w}\n")] if not text[ls:s].strip() else []
    # 同じ位置の頭は内側（終わりが近い）から、閉じは外側（始まりが遠い）から差す——後から差した物が前に来るので、外側が外に残る
    return [(s, 0, e, f"(({w}) and False or ("), (e, 1, s, "))")]


def mutate(root, a):
    # 写しの台本は bash が読むので、Windows の text モードの改行の変換（\n → \r\n）を通さずに書く（marker_run も同じ）
    p = root / a["file"]
    text = p.read_text(encoding="utf-8")
    if "auto" in a:
        x = a["auto"]
        p.write_text(text[:x["start"]] + x["new"] + text[x["end"]:], encoding="utf-8", newline="\n")
        return
    if "json" in a:
        doc = json.loads(text)
        t = json_target(doc, a["json"]["path"])
        if "remove" in a["json"]:
            t.remove(a["json"]["remove"])
        else:
            t.pop(a["json"]["del"])
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    else:
        p.write_text(text.replace(a["old"], a["new"]), encoding="utf-8", newline="\n")


# 根の生死を期限でなくロックで見るのは、ロックはプロセスの死で必ず解けるから
ROOT_PREFIX = "mutate-run-"
_RUN = {"root": None, "lock": None, "fd": None}
_BASES = {}
_BASE_GIT = {}
_SCRATCH = set()          # copy が作った写しの repo。run_group はここで起こす子にだけ、写しの下の TMPDIR を渡す
_ROOT_LOCK = threading.RLock()


def _try_lock(fd):
    """排他ロックを待たずに取る ——True＝取れた / False＝他が握っている / None＝この OS にロックの口が無い"""
    try:
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    except ImportError:
        pass
    try:
        import msvcrt
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    except ImportError:
        return None


def _drop(root, lock, fd):
    """根を消し、ロックのファイルを最後に消す——途中で殺されても、残り物は次の起動の sweep_roots が見つけられる。
    Windows は開いたファイルを消せないので、閉じてから消す"""
    shutil.rmtree(root, ignore_errors=True)
    if os.name == "nt":
        os.close(fd)
        fd = None
    try:
        os.unlink(lock)
    except OSError:
        pass
    if fd is not None:
        os.close(fd)


def sweep_roots(tmp):
    """前の起動が残した根を消す。消すのは (1) ロックを取れた（持ち主が死んだ）根 と (2) ロックのファイルの無い根（作る側はロックを
    握ってから根を作り、消す側は根を消してからロックを消すので、ロックの無い根は消しかけの残り）だけ。ロックの口が無い OS では (1) を
    しない（生きた根と見分けられない）。旧形式の写し（mutate-<tag>-*）は持ち主が分からないので触らない"""
    for lk in sorted(tmp.glob(ROOT_PREFIX + "*.lock")):
        try:
            fd = os.open(lk, os.O_RDWR)
        except OSError:
            continue
        try:
            got = _try_lock(fd)
            # 開いてからロックを取るまでに持ち主が消して別の起動が同じ名前で作り直した回は、別の物を掴んでいるので触らない
            mine = got and os.path.samestat(os.fstat(fd), os.stat(lk))
        except OSError:
            got = mine = False
        if not mine:
            os.close(fd)
            if got is None:
                break
            continue
        _drop(lk.with_suffix(""), lk, fd)
    for d in sorted(tmp.glob(ROOT_PREFIX + "*")):
        if d.is_dir() and not d.with_name(d.name + ".lock").exists():
            shutil.rmtree(d, ignore_errors=True)


def run_root():
    """この起動の写しの根（初めて呼ばれたときに作る）。ロックのファイル（mkstemp）を作ってロックを握ってから、同じ名前の根を作る。
    根とロックは終わるときに atexit が消す（正常・例外・止める信号の sys.exit）。SIGKILL などで残った根は次の起動の sweep_roots が拾う"""
    with _ROOT_LOCK:
        if _RUN["root"] is None:
            tmp = pathlib.Path(tempfile.gettempdir())
            sweep_roots(tmp)
            while True:
                fd, lock = tempfile.mkstemp(prefix=ROOT_PREFIX, suffix=".lock")
                ok = _try_lock(fd)
                # 作ってからロックを取るまでに、別の起動の sweep_roots に消された回は作り直す
                if ok is not False and os.path.exists(lock) and os.path.samestat(os.fstat(fd), os.stat(lock)):
                    root = pathlib.Path(lock[:-len(".lock")])
                    try:
                        root.mkdir()
                        break
                    except FileExistsError:
                        os.unlink(lock)
                os.close(fd)
            _RUN.update(root=root, lock=lock, fd=fd)
            atexit.register(release_root)
        return _RUN["root"]


def release_root():
    with _ROOT_LOCK:
        if _RUN["root"] is not None:
            _drop(_RUN["root"], _RUN["lock"], _RUN["fd"])
            _RUN.update(root=None, lock=None, fd=None)
            _BASES.clear()
            _BASE_GIT.clear()
            _SCRATCH.clear()


def scratch_dir(tag):
    """腕ごとの作業場。自動の腕の id（auto:<パス>:<行>:<列>:<種類>）は / と : を含むので、そのまま接頭辞にすると
    mkdtemp が在りもしない親ディレクトリを探して落ちる（実測 2026-09-24: 4 周目の差分の検算が 80 本撃った所で全部失った）"""
    return pathlib.Path(tempfile.mkdtemp(prefix=f"mutate-{re.sub(r'[^0-9A-Za-z._-]', '_', tag)}-", dir=run_root()))


def base():
    """基点: 作業ツリーを起動の中で 1 回だけ根の下に写した物。腕・control・印の写しはここから作る——写すたびに生きた作業ツリーを
    読み直すと、同じ回の写しが別々の時刻の木を見て、control の緑が腕の写しの版の緑にならない。
    **版に入るファイルだけを写す**（追跡中と、.gitignore に当たらない未追跡）。丸ごと写していた頃は .venv など無視対象まで
    腕ごとに複製した"""
    with _ROOT_LOCK:
        key = str(ROOT)
        if key not in _BASES:
            b = pathlib.Path(tempfile.mkdtemp(prefix="base-", dir=run_root())) / "repo"
            ls = subprocess.run(["git", "-C", str(ROOT), "-c", "core.quotePath=false", "ls-files", "-z", "--cached", "--others",
                                 "--exclude-standard"], capture_output=True)
            for rel in sorted({x for x in ls.stdout.decode("utf-8", "replace").split("\0") if x}):
                src, dst = ROOT / rel, b / rel
                if not (src.is_file() or src.is_symlink()):
                    continue   # 消したが index に残る物
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_symlink():
                    dst.symlink_to(os.readlink(src))
                else:
                    shutil.copy2(src, dst)
            b.mkdir(parents=True, exist_ok=True)
            _BASES[key] = b
        return _BASES[key]


def base_git():
    """基点を git の作業ツリーとして読む環境（GIT_DIR は本物、GIT_WORK_TREE は基点、index は本物を写した一時の物）。組めなければ None。
    基点は .git を持たないファイルの写しなので、差分を作業ツリーから取ると、写しと差分が別々の時刻の版を指す。
    本物の index は時刻ごと写す（index の時刻が新しくなると、同じ秒に書き換えたファイルを綺麗と見誤る）。写しに --really-refresh を
    当てるのは assume-unchanged の印を外すため——印を持ったままだと、git は基点の中身を見ずに古い中身で差分を出す。fsmonitor は本物の
    作業ツリーの変化を答え、split index は GIT_DIR に共有の index を書くので切る。index を写して refresh する手は
    graphloops/rules/review-loop.py の _worktree_tree と同じ。あちらと違って add -A・write-tree を打たないので、本物の object の置き場に
    も書かない（足すなら GIT_OBJECT_DIRECTORY を隔離してから）"""
    with _ROOT_LOCK:
        key = str(ROOT)
        if key not in _BASE_GIT:
            b = base()
            g = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, encoding="utf-8",
                                          errors="replace")
            gd, ix = g("rev-parse", "--absolute-git-dir"), g("rev-parse", "--path-format=absolute", "--git-path", "index")
            if gd.returncode or ix.returncode or not gd.stdout.strip():
                return None
            idx = b.parent / "index"
            try:
                shutil.copy2(ix.stdout.strip(), idx)
            except FileNotFoundError:
                pass   # 1 度も add していない repo（追跡中のファイルが無い）
            try:
                n = int(os.environ.get("GIT_CONFIG_COUNT") or 0)
            except ValueError:
                return None
            # 呼び手の環境に足す（置き換えると PATH が消える）。設定は呼び手が積んだ GIT_CONFIG_* の後ろに積む
            env = {**os.environ, "GIT_DIR": gd.stdout.strip(), "GIT_WORK_TREE": str(b), "GIT_INDEX_FILE": str(idx),
                   "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_COUNT": str(n + 2),
                   f"GIT_CONFIG_KEY_{n}": "core.fsmonitor", f"GIT_CONFIG_VALUE_{n}": "false",
                   f"GIT_CONFIG_KEY_{n + 1}": "core.splitIndex", f"GIT_CONFIG_VALUE_{n + 1}": "false"}
            r = subprocess.run(["git", "-C", str(b), "update-index", "-q", "--really-refresh"], env=env, capture_output=True)
            if r.returncode:
                return None
            _BASE_GIT[key] = env
        return _BASE_GIT[key]


def worktree_moved(sel):
    """基点を写した後に作業ツリーで変わったファイルのうち、撃った腕の結果を決めるもの（指紋に入るファイル）。記録にだけ使う"""
    b = base()
    read = lambda p: p.read_bytes() if p.is_file() else None
    files = {f for x in sel for f in (x["file"],) + drivers_of(b, x) + drivers_of(ROOT, x)}
    return [f for f in sorted(files) if read(b / f) != read(ROOT / f)]


def pytest_files(root):
    """pytest の段の結果を決めるファイル（置き場のテスト・設定と、版を固定した宣言）。自動の腕の指紋にだけ入れる"""
    d = root / PYDIR
    own = sorted(f"{PYDIR}/{p.name}" for p in d.glob("*.py")) if d.is_dir() else []
    return (".review-checks.json", f"{PYDIR}/pytest.ini", *own)


def drivers_of(root, a):
    """腕の結果を決める検査の側のファイル: 台本一式と、自動の腕なら pytest の段のファイル（一覧の腕は pytest を撃たないので、
    pytest のテストを直しても一覧の腕の持ち越しは外さない）"""
    return DRIVERS + (pytest_files(root) if "auto" in a else ())


def copy(tag):
    """基点から腕の写しを作る ——(写しの repo, 作業場)。作る途中の例外・止める信号では作業場を消してから投げ直す（呼び元の
    try より前で残る窓を閉じる）。作業場の tmp は、写しの中で起こす子の一時の置き場（run_group が TMPDIR に渡す）"""
    src = base()
    d = scratch_dir(tag)
    try:
        repo = d / "repo"
        shutil.copytree(src, repo, symlinks=True)
        (d / "tmp").mkdir()
        # tests/run.sh は git の中で走る前提の検査を持つ——写しに素の repo を作る（コミットは 1 つ）
        for c in (["init", "-q"], ["add", "-A"], ["-c", "user.name=m", "-c", "user.email=m@m", "commit", "-qm", "x"]):
            subprocess.run(["git", *c], cwd=repo, capture_output=True)
        with _ROOT_LOCK:
            _SCRATCH.add(str(repo))
        return repo, d
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise


def child_env(cwd, env):
    """写しの中で起こす子の環境: TMPDIR・TMP・TEMP を写しの作業場の tmp に向ける。写しの中の台本・入れ子の実行器・後片付けを
    壊した変異体の一時物も、作業場ごと消える。写しでない cwd（台本が直に呼ぶ回）の環境は変えない"""
    if str(cwd) not in _SCRATCH:
        return env
    tmp = str(pathlib.Path(cwd).parent / "tmp")
    return {**(os.environ if env is None else env), "TMPDIR": tmp, "TMP": tmp, "TEMP": tmp}


def run_group(argv, cwd, env=None, failfast=False):
    """子を自分のプロセスグループで起こし、時間切れならグループごと殺す ——（exit か "timeout" か "stopped", 標準出力＋標準エラー）。
    subprocess.run の timeout は直下の子しか殺さない——実行器そのものを壊した腕では、写しの台本が写しの実行器を呼び、
    殺し損ねた孫が増え続けて全体を時間切れにした（2026-09-23 の 3 周目の撃ち直し）。
    failfast なら最初の FAIL の行でグループごと止めて exit 1 を返す（自動の腕は赤と印で証拠がそろい、どの検査かを要らない）。
    起こした子は _LIVE に載せ、止める信号（install_stop_handlers）で木ごと止める。止めた回は "stopped"——赤と読ませない"""
    # POSIX は新しいプロセスグループで起こす（setpgid。セッションは抜けない）——この実行器が SIGKILL で止められても、起こした側
    # （engine の子を止める口）が同じセッションの仲間として拾える。setsid で抜けると親の消えた子孫を拾う手が無い。
    # Windows にはプロセスグループへの信号（killpg・SIGKILL）が無いので、新しいプロセスグループで起こして taskkill /T で
    # 木ごと止める（graphloops/engine/role_run.py の _spawn と _kill と同じ分け方）
    group = ({"process_group": 0} if os.name == "posix"
             else {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)})
    p = subprocess.Popen(argv, cwd=cwd, env=child_env(cwd, env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", **group)
    with _LOCK:
        _LIVE.add(p)
    late = {"v": False}

    def killpg():
        # グループが先に自然終了していると ProcessLookupError（pgid を使い回されていれば PermissionError）が飛ぶ。
        # 握り潰さないと腕 1 本の競合で実行器ごと落ち、--out を書く前に全部の結果を失う（実測 2026-09-24、failfast の直後）
        try:
            if os.name == "posix":
                os.killpg(p.pid, signal.SIGKILL)
            else:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        except (ProcessLookupError, PermissionError):
            pass

    def kill():
        late["v"] = True
        killpg()
    timer = threading.Timer(TIMEOUT, kill)
    timer.start()
    out, stopped = [], False
    try:
        if STOPPING.is_set():   # 信号の片付けが _LIVE を読んだ後に起こした子（止める信号の後の腕）は、ここで自分で止める
            killpg()
        for line in p.stdout:
            out.append(line)
            if failfast and line.startswith("  FAIL ") and NO_TEST not in line:
                stopped = True
                killpg()
                break
        p.wait()
    finally:
        timer.cancel()
        with _LOCK:
            _LIVE.discard(p)
    if STOPPING.is_set():
        return "stopped", ""
    if late["v"]:
        return "timeout", ""
    return (1 if stopped else p.returncode), "".join(out)


def run_suite(repo, suite, failfast=False, env=None, detail=False):
    """台本一式を走らせる。detail なら赤の回に本文も返す（fails＝FAIL の行ごとに続く行、end＝出力の末尾。graphloops の台本は
    FAIL を 1 行で出し、例外の本文は最後に投げ直した末尾の標準エラーに出るので、両方が要る）"""
    rc, body = run_group(SUITES[suite], repo, env=env, failfast=failfast)
    if rc == "stopped":
        raise Stopped(0)
    if rc == "timeout":
        return {"rc": "timeout", "failed": [f"{TIMEOUT} 秒で打ち切り"], "tail": []}
    lines = body.splitlines()
    failed = [l.strip()[5:].strip() for l in lines if l.startswith("  FAIL ")]
    tail = [l for l in lines if "件失敗" in l or "件すべて緑" in l or l.startswith("graphloops:")]
    out = {"rc": rc, "failed": failed, "tail": tail}
    if detail and rc != 0:
        fails = []
        for i, l in enumerate(lines):
            if l.startswith("  FAIL ") and len(fails) < 8:
                nxt = []
                for m in lines[i + 1:i + 13]:
                    if m.startswith(("  ok ", "  FAIL ")):
                        break
                    nxt.append(m)
                fails.append({"line": l.strip(), "after": nxt})
        out["detail"] = {"fails": fails, "end": lines[-40:]}
    return out


def run_selected(repo, tests, failfast=False):
    """腕の tests（台本 → 関数名）だけを走らせる。failfast なら最初の FAIL で止める（残りの台本は走らせない）"""
    rcs, failed = [], []
    for script, fns in tests.items():
        if failfast and failed:
            break
        rc, body = run_group([sys.executable, script], repo, env={**os.environ, "GL_TEST_ONLY": ",".join(fns)}, failfast=failfast)
        if rc == "stopped":
            raise Stopped(0)
        if rc == "timeout":
            rcs.append("timeout"); continue
        # 絞った名前が台本に 1 本も無いと collect が exit 1 で抜ける——壊した行とは無関係の赤なので、撃てないと言う
        rcs.append("no-test" if NO_TEST in body else rc)
        failed += [l.strip()[5:].strip() for l in body.splitlines() if l.startswith("  FAIL ")]
    bad = [x for x in rcs if x != 0]
    return {"rc": bad[0] if bad else 0, "failed": failed, "tail": [], "selected": True}


CONFIRM = False   # --confirm-survivors: 絞った台本が緑の腕を台本一式で確かめ直す（main が立てる）


def cover_why(a, key):
    """腕の覆い（key＝cover は台本・pytest_cover は pytest）で絞れるか ——(覆い, 絞れない理由)。台本と pytest の撃ち分けが同じ規則を
    読む 1 本の口: 一覧の腕（not_auto）・印が無い（no_cover）・帰属できない印（unknown_owner）・import の時に走る行（import_time）"""
    cov = a.get(key)
    if "auto" not in a:
        return cov, "not_auto"
    if not cov:
        return cov, "no_cover"
    if UNKNOWN in cov:
        return cov, "unknown_owner"
    if not a["auto"].get("in_function"):
        return cov, "import_time"
    return cov, ""


def pytest_pick(a):
    """自動の腕を前段で撃つ pytest の引数と撃ち方 ——(引数 か None, 撃ち方)。撃ち方: nodes＝行を通したテストの node id だけ /
    files＝そのテストのファイル（node id の並びが ARGV_MAX を超える・置き場の全ファイルに及ぶ——全ファイルなら件数の柵も当たる）/
    unknown_owner・import_time＝pytest 一式（選び方が分からない行は一式に倒す）/ not_auto・no_cover＝pytest を撃たない"""
    cov, why = cover_why(a, "pytest_cover")
    if why in ("not_auto", "no_cover"):
        return None, why
    if why:
        return [PYDIR], why
    files = sorted({n.split("::")[0] for n in cov})
    nodes = [f"{PYDIR}/{n}" for n in cov]
    every = {p.name for p in (base() / PYDIR).glob("test_*.py")}
    if set(files) >= every or len(" ".join(nodes)) > ARGV_MAX:
        return [f"{PYDIR}/{f}" for f in files], "files"
    return nodes, "nodes"


def pytest_ready():
    """pytest の段を足せるか ——理由（足せるなら空）。足せない回は今の撃ち方（台本だけ）のまま撃つ"""
    if not shutil.which(PYTEST[0]):
        return f"{PYTEST[0]} が PATH に無い（pytest を起こせない）"
    if not (base() / PYDIR).is_dir():
        return f"{PYDIR} が無い"
    return ""


def run_pytest(repo, args, failfast=False):
    """pytest を写しで走らせる（run_suite・run_selected と同じ返りの形）。failed は落ちたテストの node id（pytest.ini の置き場から見た形。
    印の cover と同じ形）。赤と読むのは rc 1（テストが落ちた。件数などの柵の赤も含む）と、ERROR の行の在る rc 2（収集で落ちた）だけ——
    ほかの終了（使い方の誤り 4・集まらない 5・内部の誤り 3・uv の失敗）は壊した行と無関係なので no-test（撃てない）と言う"""
    nodes = any("::" in x for x in args)
    argv = PYTEST + ["-n", "0" if nodes else PYTEST_WORKERS, "-p", "no:cacheprovider"] + (["-x"] if failfast else []) + list(args)
    env = {k: v for k, v in os.environ.items() if k != PYTEST_MARK}
    rc, body = run_group(argv, repo, env=env)
    if rc == "stopped":
        raise Stopped(0)
    if rc == "timeout":
        return {"rc": "timeout", "failed": [f"{TIMEOUT} 秒で打ち切り"], "tail": []}
    lines = body.splitlines()
    failed = [m.group(1) for m in map(PYTEST_RED.match, lines) if m]
    tail = lines[-5:]
    if rc == 1 or (rc == 2 and failed):
        return {"rc": rc, "failed": failed or ["pytest の柵（fence）が赤"], "tail": tail}
    if rc != 0:
        return {"rc": "no-test", "failed": [], "tail": tail, "why": f"pytest が赤でない終わり方をした（rc={rc}）"}
    return {"rc": 0, "failed": [], "tail": tail}


def narrow_why(a):
    """自動の腕を回す台本（台本 → 関数名）と、絞れないときの理由 ——(台本 か None, 理由)。絞るのは、印の写しで行を通した台本が全部
    分かり、行が関数の本体に在るときだけ。理由は、一覧の腕（not_auto）・印が無い（no_cover）・帰属できない印（unknown_owner）・
    import の時に走る行（import_time）・台本の一覧（SCRIPTS）の外の台本（outside_scripts）。理由の件数は evaluate が数える"""
    cov, why = cover_why(a, "cover")
    if why:
        return None, why
    tests = {}
    for o in cov:
        script, _, fn = o.partition("~")
        rel = f"graphloops/tests/{script}"
        if rel not in SCRIPTS or not fn:
            return None, "outside_scripts"
        tests.setdefault(rel, set()).add(fn)
    return {s: sorted(v) for s, v in sorted(tests.items())}, ""


def narrowed(a):
    """自動の腕を回す台本（台本 → 関数名）。絞れなければ None（台本一式で撃つ）"""
    return narrow_why(a)[0]


def one(a):
    if ignored(a):
        mx = a["python_max"]
        return {"id": a["id"], "title": a["title"], "status": "Ignored", "own": False, "rc": None, "failed": [], "killedBy": [],
                "tail": [f"Python {mx} 以前でしか撃てない（今は {sys.version_info[0]}.{sys.version_info[1]}）"]}
    if STOPPING.is_set():
        raise Stopped(0)   # 止める信号の後に取り出された腕は写しも作らない
    repo, d = copy(a["id"])
    try:
        mutate(repo, a)
        # 写しの腕の一覧は空にする（marker_run と同じ）——壊した字列は写しの一覧から見て 0 か所なので、写しの tests/run.sh が
        # 走らせる --check が必ず赤になり、生き残った変異を Killed と書いていた
        if a["file"] != "tests/mutations.json" and (repo / "tests" / "mutations.json").is_file():
            (repo / "tests" / "mutations.json").write_text('{"arms": []}\n', encoding="utf-8")
        r = None
        auto = "auto" in a
        head = {"id": a["id"], "title": a["title"], **({"cover": a["cover"]} if "cover" in a else {}),
                **({"pytest_cover": a["pytest_cover"]} if "pytest_cover" in a else {})}
        # **pytest の段（前段）**: 印の写しで pytest が行を通した自動の腕は、先に通したテストだけを撃つ。赤なら Killed で打ち切る。
        # 緑・撃てない回は、今の道（台本）をそのまま撃つ——pytest を足しても今の網を狭めない（台本だけが殺す腕も台本で殺す）
        py = None
        args, how = pytest_pick(a) if auto and PYTEST_STAGE else (None, "")
        if args:
            py = {**run_pytest(repo, args, failfast=True), "how": how}
            if py["rc"] not in (0, "timeout", "no-test"):
                return pytest_killed(head, py, "pytest" if how in ("nodes", "files") else "pytest_whole")
        if auto and py is not None and "cover" not in a:
            # 台本が行を通さない腕（今までは撃たずに NoCoverage）は台本を撃たない。pytest が緑なら生き残り
            if py["rc"] in ("timeout", "no-test"):
                return {**head, "status": "Timeout" if py["rc"] == "timeout" else "RuntimeError", "own": False, "rc": py["rc"],
                        "failed": py["failed"][:3], "killedBy": [], "tail": py["tail"], "pytest": py, "pytest_only": True,
                        "unrunnable": "時間切れ（pytest）" if py["rc"] == "timeout" else py.get("why") or "pytest を撃てない"}
            return pytest_green(repo, head, py, {"rc": 0, "failed": [], "tail": [], "selected": False, "pytest_only": True})
        tests = narrowed(a) if auto else (a.get("tests") if a["suite"] == "graphloops" else None)
        if tests:
            r = run_selected(repo, tests, failfast=auto)
            # 絞った台本が気づかない腕を台本一式で確かめ直すのは --confirm-survivors の回だけ（版を出す前の関門。人の決定 2026-09-26）。
            # 確かめ直して赤なら、行を通した台本の外の検査が落とした——件数・語彙の到達・本文を読む柵のように台本の関数の外で
            # 決定的に落ちる検査もあれば、揺れた検査もある。見分けられないので attribution に印を残し、証拠は外さない
            if r["rc"] == 0 and CONFIRM:
                r = {**run_suite(repo, a["suite"], failfast=auto), "selected": False, "confirmed": True}
        if r is None:
            r = {**run_suite(repo, a["suite"], failfast=auto), "selected": False}
        if r["rc"] in ("timeout", "no-test"):
            return {"id": a["id"], "title": a["title"], "status": "Timeout" if r["rc"] == "timeout" else "RuntimeError",
                    "own": False, **r, "killedBy": [], "failed": r["failed"][:3],
                    "unrunnable": "時間切れ" if r["rc"] == "timeout" else "tests の関数名が台本に無い（--map で結び直せ）"}
        red = r["rc"] != 0
        own = bool(a.get("expect")) and any(f.startswith(a["expect"]) for f in r["failed"])
        if not red and py is not None:
            return pytest_green(repo, head, py, r)
        # 赤の出どころ: narrowed＝絞った台本（自動の腕なら行を通した台本）から / unrelated＝絞った台本は緑で一式の確かめ直しで赤 /
        # unattributed＝台本一式だけで撃った（帰属できない）。揺れた検査の赤を見分ける材料として記録に残す（再試行はしない）。
        # pytest の段の赤は pytest_killed が pytest / pytest_whole / pytest_unrelated と書く
        why = ("narrowed" if r.get("selected") else "unrelated" if r.get("confirmed") else "unattributed") if red else None
        return {**head, "status": "Killed" if red else "Survived", "own": own,
                **r, "killedBy": r["failed"][:20], "failed": r["failed"][:3],
                **({"attribution": why} if why else {}), **({"pytest": py} if py is not None else {})}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def pytest_killed(head, py, why):
    """pytest の段の赤で Killed にした腕の行。killedBy は落ちたテストの node id"""
    return {**head, "status": "Killed", "own": False, "rc": py["rc"], "failed": py["failed"][:3], "killedBy": py["failed"][:20],
            "tail": py["tail"], "selected": False, "pytest": py, "attribution": why}


def pytest_green(repo, head, py, r):
    """pytest の段も台本（r）も緑の腕の行。pytest を絞っていて --confirm-survivors の回なら、pytest 一式で確かめ直す（赤なら
    pytest_unrelated の Killed。台本の confirmed と同じく、揺れか絞った外のテストかは見分けない）"""
    narrowed_py = py["rc"] == 0 and py["how"] in ("nodes", "files")
    if narrowed_py and CONFIRM:
        full = {**run_pytest(repo, [PYDIR], failfast=True), "how": "confirm"}
        if full["rc"] not in (0, "timeout", "no-test"):
            return {**pytest_killed(head, full, "pytest_unrelated"), "pytest_first": py}
        py = {**py, "confirmed": full["rc"]}
        narrowed_py = full["rc"] != 0
    return {**head, "status": "Survived", "own": False, **r, "killedBy": [], "failed": [], "pytest": py,
            **({"pytest_selected": True} if narrowed_py else {})}


def control(suites, selected=None, pytest=None):
    """壊していない写しで、撃つときと同じ走らせ方が緑になるか（絞った台本も、絞った形のまま確かめる）。pytest は腕が撃つ pytest の
    テストのファイルの和（node id は並べない——argv の長さと件数の柵を node id で外さないため）。pytest の結果は control_ok に入れず、
    赤なら pytest で殺した腕だけを証拠から外す（evaluate）"""
    repo, d = copy("control")
    try:
        res = {s: run_suite(repo, s) for s in sorted(suites)}
        if selected:
            res["selected"] = run_selected(repo, selected)
        if pytest:
            res["pytest"] = run_pytest(repo, pytest)
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
            w = mark_write(hits, a["id"])
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
            (repo / rel).write_text(t, encoding="utf-8", newline="\n")
        # 印は複数行の old を割るので、写しの中の --check（tests/run.sh が走らせる）が字列の消失で赤になる。
        # 印の写しは『守る行を通ったか』だけを見る所なので、写しの一覧は空にする（本物の一覧は触らない）
        (repo / "tests" / "mutations.json").write_text('{"arms": []}\n', encoding="utf-8")
        # GL_MARK_OWNERS: graphloops の台本の土台（parallel.workspace）が作業場の名前に台本の印を挟む（子のプロセスの印を帰属させる）
        env = {k: v for k, v in os.environ.items() if k != PYTEST_MARK}
        r = run_suite(repo, "root", env={**env, "GL_MARK_OWNERS": "1"}, detail=True)   # tests/run.sh は graphloops の台本も内包する
        seen, cover = read_hits(hits)
        out = {**r, "failed": r["failed"][:5], "placed": sorted(placed), "seen": seen, "cover": cover, "skipped": skipped}
        if PYTEST_STAGE and any("auto" in a and a["id"] in placed for a in arms):
            # 同じ写しで pytest 一式も走らせ、印の 4 つ目の欄（テストの node id）で pytest の覆いを取る。緑の回だけ使う——赤の回
            # （途中で止まった記録）は pytest の覆いを持たず、seen も台本の分だけにして、今の撃ち方に落ちる
            rc, body = run_group(PYTEST + ["-n", PYTEST_WORKERS, "-p", "no:cacheprovider", PYDIR], repo, env={**env, PYTEST_MARK: UNKNOWN})
            if rc == "stopped":
                raise Stopped(0)
            ok = rc == 0
            pseen, pcover = read_hits(hits, pytest=True) if ok else ([], {})
            out.update(script_seen=seen, seen=sorted(set(seen) | set(pseen)), pytest_seen=pseen, pytest_cover=pcover,
                       pytest={"rc": rc, "failed": [m.group(1) for m in map(PYTEST_RED.match, body.splitlines()) if m][:5],
                               "tail": body.splitlines()[-5:], **({} if ok else {"why": f"印の写しの pytest が緑でない（rc={rc}）——pytest の覆いを使わない"})})
        return out
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


def changed_since(rev, root=ROOT, env=None):
    """その版から変わったファイル（未追跡の新しいファイルも。git diff は未追跡を出さない）。基点から取るときは root と env を auto_targets と同じに"""
    got = set()
    for args in (["diff", "--name-only", rev], ["ls-files", "--others", "--exclude-standard"]):
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", env=env)
        if out.returncode != 0:
            print(f"NG 版 {rev} から変わったファイルを引けない（{out.stderr.strip()[:120]}）", file=sys.stderr)
            sys.exit(2)
        got |= set(out.stdout.splitlines())
    return got


def write_out(out, res):
    """--out を書く口はこの 1 本。一時ファイルに書いてから置き換える（途中で殺されても、読める前の版か新しい版のどちらかが残る）。
    撃つ途中でも腕 1 本ごとに書く——最後に 1 度だけ書いていたとき、期限で切ると結果が 1 本も残らず、それが『期限を付けるな』の
    理由になっていた（実測 2026-09-24）。途中の版は partial と未撃ちの pending を持ち、--reuse はそこからも続けられる"""
    if not out:
        return
    p = pathlib.Path(out)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def write_empty(out, why):
    """撃てた腕が 0 本の回も --out を書く——--gate-efficacy がそこから not_run（理由つき）を組める。終了コードは 1 のまま
    （0 本を合格と言わない）。書かずに抜けていた頃は、任せ先が --gate-efficacy を打つと読み込みで落ち、返す形が何も無かった"""
    write_out(out, {"schemaVersion": "1", "arms": [], "empty": why})


def pick(arms, only=None, files=None, since=None, root=ROOT, env=None):
    """一覧の腕を絞る（絞りが無ければ全部）。0 本の判定は呼び元が自動の腕と合わせた後の 1 か所で行う"""
    sel = arms
    if only:
        sel = [x for x in sel if x["id"] in set(only.split(","))]
    if files:
        sel = [x for x in sel if x["file"] in set(files.split(","))]
    if since:
        ch = changed_since(since, root, env)
        sel = [x for x in sel if x["file"] in ch]
    return sel


SURVIVED = ("Survived", "NoCoverage")   # 壊しても台本が赤にならなかった腕（NoCoverage は緑の印の写しで印の行も通らなかった）。腕の結果の正本は status だけ
MARKER_RED = "印の写しが赤（rc={rc}）で、途中までの記録から『通らない行』を決めない——通らなかった自動の腕は撃たず、NoCoverage にもしない"


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
    if m.get("rc", 0) != 0:
        res["marker_unhealthy"] = MARKER_RED.format(rc=m.get("rc"))
    # control の pytest が赤の回は、pytest の段の赤を証拠にしない（台本で殺した腕の証拠は残す——回ごとは落とさない）
    py_ctl_ok = (res["control"].get("pytest") or {"rc": 0})["rc"] == 0
    for r in fresh:
        # 印を差した行を台本も pytest も一度も通らない。印の写しが赤の回は途中で止まった記録なので、通らなかったとは言えない
        if r.get("status") == "Survived" and m.get("rc", 0) == 0 and r["id"] in m["placed"] and r["id"] not in m["seen"]:
            r["status"] = "NoCoverage"
        r["evidence"] = ""
        r.pop("no_evidence_why", None)
        if r.get("status") == "Killed":
            e = exp.get(r["id"])
            r["evidence"] = (f"killedBy に expect『{e[:40]}』" if r["own"] else "" if e else
                             (f"印 {r['id']} が写しの出力に現れた" if r["id"] in m["seen"] else ""))
            if str(r.get("attribution", "")).startswith("pytest") and not py_ctl_ok:
                r["evidence"], r["no_evidence_why"] = "", "pytest の赤だが、壊していない写しの pytest も赤（control）"
    res["summary"] = {"green": [r["id"] for r in fresh if r.get("status") in SURVIVED],
                      "skipped": [r["id"] for r in fresh if r.get("status") == "Ignored"],   # 撃てない腕は status だけで持つ（旗の 2 系統にしない）
                      "unrunnable": [r["id"] for r in fresh if r.get("unrunnable")],
                      "unhit": sorted(set(m["placed"]) - set(m["seen"])),
                      "no_evidence": [r["id"] for r in fresh if r.get("status") == "Killed" and not r["evidence"]],
                      # 赤の出どころ（one の attribution）と、一式で確かめていない緑。証拠と終了コードには使わず、見える形にだけする
                      "unrelated": [r["id"] for r in fresh if r.get("attribution") == "unrelated"],
                      "unattributed": [r["id"] for r in fresh if r.get("attribution") == "unattributed"],
                      "narrowed_green": [r["id"] for r in fresh if r.get("status") == "Survived" and r.get("selected")],
                      # pytest の段: 赤の出どころ（pytest＝行を通したテストから / pytest_whole＝pytest 一式だけで撃った / pytest_unrelated＝
                      # 絞った pytest は緑で一式の確かめ直しだけ赤）・pytest を絞って緑（一式で確かめていない）・台本は通らず pytest だけが
                      # 通した腕・pytest の撃ち方の内訳（nodes / files / 一式に倒した理由）
                      "by_pytest": [r["id"] for r in fresh if r.get("attribution") in ("pytest", "pytest_whole")],
                      "pytest_unrelated": [r["id"] for r in fresh if r.get("attribution") == "pytest_unrelated"],
                      "pytest_narrowed_green": [r["id"] for r in fresh if r.get("status") == "Survived" and r.get("pytest_selected")],
                      "pytest_only": sorted(set(m.get("pytest_seen", ())) - set(m.get("script_seen", m.get("seen", ())))),
                      "pytest_how": dict(sorted(collections.Counter((r.get("pytest") or {}).get("how") for r in fresh if r.get("pytest")).items())),
                      "pytest_control_ok": py_ctl_ok,
                      "pruned": len(res.get("pruned") or []),
                      # 印の写しで見えない・絞れない腕の内訳: 差せない腕の数（理由は marker.skipped）と、通ったが台本一式で撃つ腕の理由別の数
                      # （通らない腕は unhit）
                      "unplaced": len(m.get("skipped") or {}),
                      "whole_suite_why": dict(sorted(collections.Counter(
                          narrow_why(x)[1] for x in sel
                          if "auto" in x and x["id"] in m.get("script_seen", m.get("seen", ())) and narrowed(x) is None).items())),
                      "control_ok": all(v["rc"] == 0 for k, v in res["control"].items() if k != "pytest")}
    return res["summary"]


def ignored(a):
    """この Python では撃てない腕か（python_max より新しい版）"""
    mx = a.get("python_max")
    return bool(mx) and sys.version_info[:2] > tuple(int(x) for x in mx.split("."))


def fingerprint(root, a):
    """持ち越してよいかを決める指紋: 腕の定義・壊すファイル・台本一式の本文（自動の腕は pytest の段のファイルも）。どれかが変われば撃ち直す。
    ほかのファイルの変更で結果が変わる腕は拾わない（StrykerJS の incremental と同じ割り切り）——拾うのは週 1 回の全腕
    （.github/workflows/mutation.yml）で、その schedule が止まっていない間だけ（止まる条件と戻し方はそのファイルの頭）"""
    h = hashlib.sha256(json.dumps(a, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    for f in (a["file"],) + drivers_of(root, a):
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
    # 期限で撃たずに残った腕は、撃てた腕と同じ行にして証拠にならない側に数える（黙って落とすと、残りを撃たないまま clean になる）
    shot = [r for r in res["arms"] if r.get("status") != "Ignored"] + list(res.get("pending") or [])
    ign = [f"{r['id']}" for r in res["arms"] if r.get("status") == "Ignored"]
    def why(r):
        if r.get("status") == "Survived" and (r.get("selected") or r.get("pytest_selected") or r.get("pytest_only")):
            said = [s for s, on in (("絞った台本だけで緑。台本一式では確かめていない", r.get("selected")),
                                    ("台本は行を通さないので撃っていない", r.get("pytest_only")),
                                    ("絞った pytest だけで緑。pytest 一式では確かめていない", r.get("pytest_selected"))) if on]
            tail = "——--confirm-survivors で確かめ直せる" if r.get("selected") or r.get("pytest_selected") else ""
            return f"Survived（{'。'.join(said)}{tail}）"
        return r.get("unrunnable") or r.get("no_evidence_why") or r.get("status")
    arms = [{"gate": r.get("file", ""), "arm": f"{r['id']} {r['title']}", "red_confirmed": r.get("status") == "Killed",
             "control_green": ok, "hit_evidence": r.get("evidence") or "",
             **({"note": why(r)} if not proven(r) else {})} for r in shot]
    note = f"（この Python では撃てない腕: {' '.join(ign)}）" if ign else ""
    if res.get("pruned"):
        note += f"（1 行 1 本・効かない行で撃たなかった自動の腕 {len(res['pruned'])} 本は --out の pruned に理由つき）"
    # pytest の段が外れた回は、関門が台本だけの撃ち方に落ちたことを判定役に見せる（人の決定: 変異の関門は pytest を中心にする）
    py_off = res.get("pytest_stage") or ((res.get("marker") or {}).get("pytest") or {}).get("why")
    if py_off:
        note += f"（pytest の段を使っていない: {py_off}。自動の腕も台本だけで撃った）"
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
                    "条件式・raise・式の呼び出し・累算代入）。腕の一覧に宣言していない入口を生き残りとして出す。一覧の腕（絞りがあれば絞った物）と併せて撃つ")
    ap.add_argument("--deadline-at", metavar="ISO", help="この時刻（ISO 8601。時差つき）までに結果を書き終える。新しい腕を始めるのは"
                    "期限の 段の数×TIMEOUT＋TAIL 秒前まで（段は台本・pytest・確かめ直しの数）。撃たずに残った腕は --out の pending に入り、同じ --out を --reuse に渡すと続きから撃てる")
    ap.add_argument("--reuse", help="前回の --out。腕の定義・壊すファイル・台本一式が同じで、赤と当たりの証拠が在った腕を撃たずに持ち越す")
    ap.add_argument("--gate-efficacy", help="--out の結果を p1.gate_efficacy の返答の形で印字する")
    ap.add_argument("--arms-file", help="腕の一覧の置き場（既定は tests/mutations.json。台本が壊した一覧で --check の赤を見るため）")
    ap.add_argument("--every-node", action="store_true", help="--auto の腕を 1 行 1 本に畳まず、効かない行の腕も作る（Google 型に絞る前の撃ち方）")
    ap.add_argument("--confirm-survivors", action="store_true", help="絞った台本（腕の tests・自動の腕の行を通した台本）が緑の腕を"
                    "台本一式で、絞った pytest（自動の腕の行を通したテスト）が緑の腕を pytest 一式で確かめ直す。版を出す前の関門と週 1 回の全腕で付ける")
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
    global CONFIRM, PYTEST_STAGE
    CONFIRM = a.confirm_survivors
    autos, pruned = [], []
    view = (ROOT, None)   # 差分を取る木と git の環境。差分を取る回は基点（写しと差分が同じ版を指す）
    if a.auto or a.changed_since:
        view = (base(), base_git())
        if view[1] is None:
            print(f"NG 基点を git の作業ツリーとして読めない（{ROOT} の git dir・index を引けないか、一時の index を更新できない）",
                  file=sys.stderr)
            sys.exit(2)
    py_off = ""
    if a.auto:
        b = view[0]
        py_off = pytest_ready()
        PYTEST_STAGE = not py_off
        if py_off:
            print(f"pytest の段を足さない（{py_off}）——自動の腕も台本だけで撃つ", flush=True)
        tg = auto_targets(a.auto, *view)
        if tg is None:
            print(f"NG --auto {a.auto}: git diff が取れない", file=sys.stderr)
            sys.exit(2)
        for rel, lines in sorted(tg.items()):
            autos += auto_arms_for(rel, (b / rel).read_text(encoding="utf-8"), lines, every=a.every_node, pruned=pruned)
        ids += [x["id"] for x in autos]
        if pruned:
            print(f"自動の腕: 1 行 1 本・効かない行で {len(pruned)} 本を撃たない（--out の pruned に理由つき。--every-node で全部撃つ）", flush=True)
    # **一覧の腕（絞りがあれば絞った物）と自動の腕の和を撃ち、0 本の判定は和の後の 1 か所で行う。** 絞りの中で 0 本を判定して
    # いたとき、一覧に腕の無いファイルだけを直した周は、自動の腕が在っても撃つ前に抜けた。--auto だけのときに一覧の腕を
    # 捨てていたので、次の周の頭で一覧と前の周の差分の自動の腕を 1 回で撃てなかった
    sel = pick(arms, a.only, a.files, a.changed_since, *view) + autos
    if not sel:
        why = "撃つ腕が 0 本（絞りの条件に当たる腕も、--auto の差分が足した Python の文も無い。0 本を合格と言わない）"
        write_empty(a.out, why)
        print(f"NG {why}", file=sys.stderr)
        sys.exit(1)
    b = base()   # 字列の検査も、腕を撃つのと同じ基点で
    srcs = {s: suite_source(b, s) for s in {x["suite"] for x in sel}}
    bad = [(x["id"], why) for x in sel if (why := anchor_problem(b, x, srcs[x["suite"]]))]
    if bad:
        for i, why in bad:
            print(f"NG 腕 {i}: {why}", file=sys.stderr)
        sys.exit(1)
    prev = reusable(a.reuse) if a.reuse else {}
    fps = {x["id"]: fingerprint(b, x) for x in sel}
    carried = [x for x in sel if (prev.get(x["id"]) or {}).get("fingerprint") == fps[x["id"]]]
    fire = [x for x in sel if x not in carried]
    if fire and not carried and all(ignored(x) for x in fire):
        # 撃てる腕が 0 本——写しで control を回す前に止める（pytest が 1 本も集まらなかった回を専用の終了コード 5 で返すのと同じく、0 本を合格と言わない）
        why = f"撃てる腕が 0 本（{len(fire)} 本とも python_max より新しい Python {sys.version_info[0]}.{sys.version_info[1]} では撃てない）"
        write_empty(a.out, why)
        print(f"NG {why}", file=sys.stderr)
        sys.exit(1)
    # **期限: 新しい仕事（印の写し・腕）を始めてよいのは cutoff まで。** 始めた仕事は子を順に起こす段の数×TIMEOUT のうちに終わるので、
    # 結果は期限の TAIL 秒前までに書き終わる（control は最初に始めるので、同じ幅に収まる）。段は台本 1 に、pytest の段（印の写しの
    # pytest・腕の前段）で 1、--confirm-survivors の台本一式で 1、その pytest 一式で 1 を足す。期限を見るのは仕事を始める時の 1 回だけ（now の 1 本の口）
    stages = 1 + PYTEST_STAGE + CONFIRM + (CONFIRM and PYTEST_STAGE)
    cutoff = (datetime.datetime.fromisoformat(a.deadline_at) - datetime.timedelta(seconds=TIMEOUT * stages + TAIL)) if a.deadline_at else None
    late = lambda: cutoff is not None and now(cutoff.tzinfo) >= cutoff
    print(f"撃つ腕 {len(fire)} 本（全 {len(arms)} 本" + (f"・持ち越し {len(carried)} 本" if carried else "") + "）", flush=True)
    res = {"schemaVersion": "1", "arms": [{**prev[x["id"]], "carried": True} for x in carried], "pruned": pruned,
           **({"pytest_stage": py_off} if py_off else {})}
    pend = lambda xs: [{"id": x["id"], "title": x["title"], "file": x["file"], "status": "Pending",
                        "unrunnable": "期限で撃たずに残った（同じ --out を --reuse に渡して続きを撃て）"} for x in xs]
    write_out(a.out, {**res, "partial": True, "pending": pend(fire)})
    install_stop_handlers()
    try:
        skipped_late = shoot(a, res, fire, sel, fps, late, pend)
    except Stopped as e:
        # 子のグループは信号の口（stop_groups）が止め、写しは腕ごとの finally が、根は atexit が消す（shoot が走っている腕の終わりを待つ）。
        # 撃てた腕までの --out は腕ごとに書いてある
        print(f"NG 止める信号（{e.signum}）を受けた——起こした子のグループと写しを片付けて抜ける（撃てた腕までの --out は残る）",
              file=sys.stderr, flush=True)
        sys.exit(128 + e.signum if e.signum else 1)
    if skipped_late:
        res["pending"] = pend(skipped_late)
        print(f"期限で撃たずに残った腕 {len(skipped_late)} 本: {' '.join(x['id'] for x in skipped_late)}"
              "（同じ --out を --reuse に渡して続きを撃て）", flush=True)
    res["arms"].sort(key=lambda r: ids.index(r["id"]))
    s = evaluate(res, sel)
    m, green, skipped, unrun, unhit, noev, ctrl_ok = (res["marker"], s["green"], s["skipped"], s["unrunnable"], s["unhit"],
                                                       s["no_evidence"], s["control_ok"])
    fired = len([r for r in res["arms"] if not r.get("carried")]) - len(skipped)
    why_n = " ".join(f"{k} {v}" for k, v in s["whole_suite_why"].items())
    print(f"control: {'緑' if ctrl_ok else '赤'} / 印: {len(m['seen'])} / {len(m['placed'])} 本が通った（写しは rc={m['rc']}）"
          + (f" / 差せない {s['unplaced']}" if s["unplaced"] else "") + (f" / 通ったが台本一式で撃つ {why_n}" if why_n else ""))
    print(f"赤 {fired - len(green) - len(unrun)} / 緑 {len(green)}: {' '.join(green)}"
          + (f" / 撃てない {len(skipped)}: {' '.join(skipped)}" if skipped else "")
          + (f" / 走り切らない {len(unrun)}: {' '.join(unrun)}" if unrun else "")
          + (f" / 持ち越し {len(carried)}" if carried else ""))
    if unhit:
        print(f"印を差したが通らなかった腕: {' '.join(unhit)}")
    if noev:
        print(f"赤だが当たりの証拠が無い腕（expect を宣言した腕は、落ちた検査に expect が無い）: {' '.join(noev)}")
    if s["unrelated"] or s["unattributed"] or s["narrowed_green"]:
        print(f"赤の出どころ: 絞った台本は緑で一式だけ赤 {len(s['unrelated'])}（揺れか台本の関数の外の検査）: {' '.join(s['unrelated'])}"
              f" / 台本一式だけで撃った赤 {len(s['unattributed'])} / 一式で確かめていない緑 {len(s['narrowed_green'])}")
    if s["pytest_how"] or s["pytest_only"]:
        print(f"pytest の段: 撃ち方 {s['pytest_how']} / pytest の赤 {len(s['by_pytest'])} / 絞った pytest は緑で一式だけ赤 "
              f"{len(s['pytest_unrelated'])}: {' '.join(s['pytest_unrelated'])} / pytest 一式で確かめていない緑 {len(s['pytest_narrowed_green'])}"
              f" / 台本は通らず pytest だけが通した腕 {len(s['pytest_only'])}" + ("" if s["pytest_control_ok"] else " / control の pytest が赤（pytest の赤は証拠にしない）"))
    nowhere = [i for i in unhit if i.startswith("auto:")]
    if nowhere:
        print(f"覆いの無い行（台本も pytest も通らない）の自動の腕 {len(nowhere)} 本")
    res["summary"]["carried"] = [x["id"] for x in carried]
    moved = worktree_moved(sel)
    if moved:
        res["worktree_moved"] = moved
        print(f"基点を写した後に作業ツリーで変わったファイル: {' '.join(moved)}（撃った結果は基点の版の物）", file=sys.stderr)
    write_out(a.out, res)
    shot = [r for r in res["arms"] if r.get("status") != "Ignored"]
    sys.exit(0 if shot and not skipped_late and healthy(res) and all(proven(r) for r in shot) else 1)


def now(tz):
    """期限を見る時刻の 1 本の口（台本が差し替えて、期限の切り替わりを印のファイルで起こす）"""
    return datetime.datetime.now(tz)


def shoot(a, res, fire, sel, fps, late, pend):
    """印の写し・control・腕を撃って res に積む。返すのは期限で撃たずに残った腕"""
    pre_marker, unreached, res_pre, skipped_late = None, [], [], []
    if any("auto" in x for x in fire) and not late():
        # **自動の腕は、印の写しで一度も通らない行を撃たない**——壊しても台本が気づけない行なので、撃つまでもなく生き残り
        # （NoCoverage。腕の無い入口）。撃つのは通った行の腕だけ（全部を台本一式で撃つと 1 周の修正で 2 時間を超えた）。
        # 印の写しが赤の回は、通らなかったのか途中で止まったのかを決められないので、撃たずに『走り切らない』側に置く（生き残りと言わない。
        # この回は healthy が偽なので、終了コードも --gate-efficacy も証拠にしない）
        pre_marker = marker_run(fire)
        seen = set(pre_marker["seen"])
        red = pre_marker["rc"] != 0
        unreached = [x for x in fire if "auto" in x and x["id"] not in seen and x["id"] in pre_marker["placed"]]
        fire = [x for x in fire if x not in unreached]
        row = ({"status": "Pending", "unrunnable": MARKER_RED.format(rc=pre_marker["rc"]), "tail": []} if red else
               {"status": "NoCoverage", "tail": ["印の写しで一度も通らない行（撃たずに生き残りと数える）"]})
        res_pre = [{"id": x["id"], "title": x["title"], "own": False, "rc": None, "failed": [], "killedBy": [], **row,
                    "file": x["file"], "fingerprint": fps[x["id"]]} for x in unreached]
        # 行を通した台本（印の写しの記録）を腕に渡す——one がその台本だけを回す（narrowed）
        for x in fire:
            if "auto" in x and x["id"] in pre_marker["cover"]:
                x["cover"] = pre_marker["cover"][x["id"]]
            if "auto" in x and x["id"] in pre_marker.get("pytest_cover", {}):
                x["pytest_cover"] = pre_marker["pytest_cover"][x["id"]]
        nar = [x for x in fire if narrowed(x)]
        hows = collections.Counter(pytest_pick(x)[1] for x in fire if "auto" in x and "pytest_cover" in x)
        print(f"自動の腕: 印の写しで通った {len([x for x in fire if 'auto' in x])} 本を撃つ（うち行を通した台本だけで撃つ {len(nar)} 本"
              + (f"・pytest を先に撃つ {sum(hows.values())} 本 {dict(sorted(hows.items()))}" if hows else "")
              + f"）・通らない {len(unreached)} 本は撃たない" + (f"（{MARKER_RED.format(rc=pre_marker['rc'])}）" if red else ""), flush=True)
        if (pre_marker.get("pytest") or {}).get("why"):
            print(pre_marker["pytest"]["why"], flush=True)
    if late():
        skipped_late, fire = fire, []
    LATE = object()

    def start(x):
        """腕を始める。始める時に期限を過ぎていれば撃たずに LATE を返す（期限の判定はここの 1 か所）"""
        return LATE if late() else one(x)
    with cf.ThreadPoolExecutor(max(1, a.j)) as ex:
        union, pyfiles = {}, set()
        for x in fire:
            # control は撃つときと同じ絞り方で確かめる——手書きの腕の tests も、自動の腕の行を通した台本も、pytest の段はテストのファイルで
            for s, fns in (narrowed(x) or x.get("tests") or {}).items():
                union.setdefault(s, set()).update(fns)
            if PYTEST_STAGE:
                pyfiles.update(f.split("::")[0] for f in (pytest_pick(x)[0] or ()))
        py_ctl = {"pytest": [PYDIR] if PYDIR in pyfiles else sorted(pyfiles)} if pyfiles else {}
        # 撃つ腕が無い（全部持ち越し）回は写しで control を走らせない——持ち越した腕の健全さは前の回の結果が持つ
        fc = ex.submit(control, {x["suite"] for x in fire} | {"root"}, {s: sorted(v) for s, v in union.items()}, **py_ctl) if fire else None
        fm = None if pre_marker else (ex.submit(marker_run, fire) if fire else None)   # 全部持ち越しの回は印の写しを走らせない（差す腕が無い）
        fa = {ex.submit(start, x): x for x in fire}
        empty_marker = {"rc": 0, "failed": [], "tail": [], "placed": [], "seen": [], "cover": {}, "skipped": {}}

        def snapshot():
            """途中の版: 撃った腕・未撃ちの腕・（終わっていれば）control と印の写し。両方そろっていれば証拠まで付けて、--reuse が読める形にする"""
            done_ids = {r["id"] for r in res["arms"]}
            snap = {**copymod.deepcopy(res), "arms": copymod.deepcopy(res["arms"]) + copymod.deepcopy(res_pre), "partial": True,
                    "pending": pend([x for x in fire + [y for y in skipped_late if y not in fire] if x["id"] not in done_ids])}
            if (fc is None or fc.done()) and (pre_marker or fm is None or fm.done()):
                snap["control"] = fc.result() if fc else {"carried": {"rc": 0}}
                snap["marker"] = pre_marker or (fm.result() if fm else empty_marker)
                evaluate(snap, sel)
            return snap

        def take(f):
            got = f.result()
            if got is LATE:
                skipped_late.append(fa[f])   # 撃った腕には積まない（pending にだけ載る）
                write_out(a.out, snapshot())
                return
            r = {**got, "file": fa[f]["file"], "fingerprint": fps[fa[f]["id"]]}
            res["arms"].append(r)
            killed = r.get("status") == "Killed"
            mark = "red  " if killed else "GREEN" if r.get("status") in SURVIVED else "skip "
            print(f"  {mark} {r['id']} {r['title']}" + ("" if r["own"] or not killed else "（赤は別の検査から）"), flush=True)
            write_out(a.out, snapshot())
        try:
            for f in cf.as_completed(fa):
                take(f)
            res["control"] = fc.result() if fc else {"carried": {"rc": 0}}
            res["marker"] = pre_marker or (fm.result() if fm else empty_marker)
        except Stopped:
            # with の外へ抜ける前に、始まっていない腕を取り消す（抜けてからの shutdown(wait=True) は、残りの腕を写しから順に消化する）
            ex.shutdown(wait=True, cancel_futures=True)
            raise
        res["arms"] += res_pre
    return skipped_late


if __name__ == "__main__":
    # 起動の口でだけ直す（台本が import mutate して使うので、取り込んだ側の標準出力は書き換えない）
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    main()
