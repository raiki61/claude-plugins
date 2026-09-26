"""台本を同時に走らせる土台。**検査の中身は何も変えない。**

なぜ要るか: 検査の時間はほぼ全部が子プロセスの起動待ちで、判定そのものはゼロに近い
（実測 2026-09-13: simulate_review.py は 94.7 秒のうち 93.8 秒が子プロセス 1,561 回ぶんの起動待ち。
内訳は loop.py done が 934 回 53.9 秒・loop.py next が 442 回 35.3 秒・git が 151 回 2.8 秒）。
**待ちなので同時に走らせれば素直に縮む**——engine を実物の CLI 越しに叩く形は保つ。
中で呼ぶのをやめて速くする道もあるが、それは「何を検査しているか」を静かに狭める。

入れてよい前提（入れる前に確かめた・崩れたら直列に戻せ）:
- 各台本は `workspace()` で自分の作業場を作り、他の台本の作業場を触らない
- `os.chdir` を呼ばない（子プロセスの cwd は毎回明示で渡している）
- `os.environ[...] = ...` を書かない（読むだけ。`main` 冒頭の pop は起動前に 1 度）

直列に戻す: `GL_TEST_WORKERS=1 python3 simulate.py`（並列でだけ落ちる台本を切り分けるときに使う）
"""
import concurrent.futures
import os
import pathlib
import shutil
import tempfile
import threading
import traceback

# 件数（ran）と失敗一覧の共有更新を守る。**`ran += 1` は不可分ではない**——素で並列にすると
# 数え落とし、件数の柵（run.sh の EXPECTED_CHECKS）が走るたび違う値で赤くなる（＝柵が信用できなくなる）。
LOCK = threading.Lock()

_buf = threading.local()


SKIP_MARK = " # SKIP"   # 見送りの行の印（TAP 14 の SKIP 指示子）。root の tests/run.sh の note_skips がこの印で拾う


def skip_line(desc, capability, reason):
    """環境で走れなかった検査の 1 行。**合格の行と別の印を付け、欠けた能力の名前（capability。小文字・数字・- の 1 語）を
    説明文の頭に置く**——合格と同じ『ok』だけで出していたとき、道具や OS の機能の無い CI が走らないまま緑になり、柵にも
    CI にも止める口が無かった。拾って数え、一覧にし、名前で許すか決めて FAIL_ON_SKIP=1 で失敗に数えるのは root の
    tests/run.sh の 1 か所だけ（層ごとに一覧を作ると同じ見送りを二重に数える。名前の形を見るのもそこだけ）"""
    return f"  ok   {desc}{SKIP_MARK} {capability}: {reason}"


def line(text):
    """1 行を、その台本のまとまりに溜める。直列（溜め先が無い）ときは素通しで出す。"""
    buf = getattr(_buf, "lines", None)
    if buf is None:
        print(text)
    else:
        buf.append(text)


def collect(ns):
    """モジュールに在る `test_*` を**定義順に全部**集める。`parallel.collect(globals())` で呼ぶ。

    **手で並べない。** 並べていたとき、台本を足して呼び出しを書き忘れると誰も気づかなかった
    ——呼ばれない台本は件数を増やさないので、件数の柵（EXPECTED_CHECKS）は期待値と一致したまま緑になる。
    graph を名前で並べていて 5 本目が誰にも検査されなかったのと同じ穴（2026-09-13 に同種を 2 か所で潰した）。

    件数の柵は捨てない——こちらは「足した台本が走らない」を、柵は「台本や検査が消えた」を見る。
    見ている向きが逆なので両方要る。
    """
    tests = [v for k, v in ns.items()
             if k.startswith("test_") and callable(v) and getattr(v, "__module__", None) == ns.get("__name__")]
    # **GL_TEST_ONLY=名前,名前 で台本を絞る**（変異の腕を撃つ実行器 tests/mutate.py が、腕に関係する台本だけを
    # 走らせるため）。絞った回は件数の柵が合わないので run.sh を通さずに呼ぶ
    only = os.environ.get("GL_TEST_ONLY")
    if only:
        want = set(only.split(","))
        tests = [v for v in tests if v.__name__ in want]
        if not tests:   # 当たらない名前を 0 本のまま緑にしない（全台本の検査を外した回は母数 0 の柵が効かない）
            print(f"  FAIL GL_TEST_ONLY（{only}）に当たる台本が 1 本も無い")
            raise SystemExit(1)
    return tests


def workspace(prefix):
    """作業場を 1 つ作り、`(持ち手, パス)` を返す。**後始末は標準ライブラリに任せる。**

    以前は `mkdtemp` ＋ モジュール変数の集合（MADE）＋ `atexit` で「落ちた回も消す」を自作していた。
    それは `tempfile.TemporaryDirectory` の再実装で（`weakref.finalize` が、正常終了・未捕捉例外・
    `SystemExit` のいずれでもプロセス終了時に消す）、しかも**後から並列化を足したときに自作の集合だけ
    排他の外に残った**——件数と失敗一覧には LOCK が在るのに、集合の add には無かった。

    `ignore_cleanup_errors=True` は Windows 対策でもある: git が object を読み取り専用で置くので、
    素の rmtree は PermissionError で落ちる（実測: CI の windows-latest）。掃除の失敗で検査を落とさない。

    **持ち手（第 1 要素）を捨てると、その場で作業場が消える**——呼ぶ側は検査の間だけ生きる変数に受けろ。
    """
    td = tempfile.TemporaryDirectory(prefix=prefix, ignore_cleanup_errors=True)
    return td, pathlib.Path(td.name)


def rm(p):
    """作業場の掃除——台本が作業場を消す口はこの 1 本（simulate.py・simulate_review.py の rm がここを呼ぶ）。

    **一時の置き場（tempfile.gettempdir()）より深いパスだけを消し、外を指したら例外にする。** 消す物のパスを計算で作る台本が、
    計算に失敗した回の既定値の親を渡すと、ignore_errors の rmtree は / やホームを黙って消しに行く（実測 2026-09-26: 任せ先の
    launch が失敗した回に `kept = Path(one.get("kept") or "/nonexistent")` の親 "/" を消しに行った）。掃除の失敗は握り潰すが、
    外を消せという指示は握り潰さない。

    Windows は git の object を読み取り専用で置き、素の rmtree が PermissionError で落ちる（実測: CI の windows-latest）——
    掃除の失敗で検査本体を落とさない（ignore_errors）"""
    real = os.path.realpath(p)
    base = os.path.realpath(tempfile.gettempdir())
    if real == base or os.path.commonpath([real, base]) != base:
        raise ValueError(f"rm: 一時の置き場（{base}）より深いパスでないので消さない: {p}")
    shutil.rmtree(p, ignore_errors=True)


def workers(n_tests):
    """同時に走らせる本数。子プロセスの終了待ちなので CPU 数まで上げてよい。"""
    env = os.environ.get("GL_TEST_WORKERS")
    if env:
        return max(1, int(env))
    return max(1, min(n_tests, os.cpu_count() or 4))


def run_all(tests):
    """台本を同時に走らせ、**出力は台本ごとにまとめて、渡された順で**出す。

    素で並列に print すると 20 本ぶんの ok / FAIL が混ざり、どの台本が落ちたのか読めなくなる
    ——検査は落ちたときに読む物なので、そこを壊すと速くした意味が無い。

    例外は握り潰さない。溜めた行を全部出してから最初の 1 本を投げ直す。直列版と違うのは、
    例外が出ても残りの台本が走りきる点——落ちた 1 本で他が全部見えなくなるのを避ける
    （途中で止まった台本のぶん件数は足りなくなるので、件数の柵がどちらにせよ赤くする）。
    """
    n = workers(len(tests))
    if n == 1:
        for fn in tests:
            try:
                fn()
            except BaseException:   # 並列の枝と同じ 1 行を残してから投げ直す（1 本に絞った回も例外を FAIL として読める）
                print(f"  FAIL {fn.__name__} が例外で抜けた: {traceback.format_exc().strip().splitlines()[-1]}", flush=True)
                raise
        return

    def one(fn):
        _buf.lines = []
        try:
            fn()
            return _buf.lines, None
        except BaseException as e:  # 出力を出しきってから投げ直す。ここで止めない
            _buf.lines.append(f"  FAIL {fn.__name__} が例外で抜けた: {traceback.format_exc().strip().splitlines()[-1]}")
            return _buf.lines, e

    first = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=n) as ex:
        for lines, err in ex.map(one, tests):
            for ln in lines:
                print(ln)
            if err is not None and first is None:
                first = err
    if first is not None:
        raise first
