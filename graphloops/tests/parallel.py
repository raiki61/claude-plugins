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
import json
import os
import pathlib
import re
import shutil
import tempfile
import threading
import traceback

# 件数（ran）と失敗一覧の共有更新を守る。**`ran += 1` は不可分ではない**——素で並列にすると
# 数え落とし、件数の柵（run.sh の EXPECTED_CHECKS）が走るたび違う値で赤くなる（＝柵が信用できなくなる）。
LOCK = threading.Lock()

_buf = threading.local()


SKIP_MARK = " # SKIP"   # 見送りの行の印（TAP 14 の SKIP 指示子）。root の tests/run.sh の note_skips がこの印で拾う
# engine が起こした子の環境の印（run_all が読む）。名前の正本は engine/role_run.py の ENGINE_CHILD_ENV（揃いは test_engine_guards が縛る）
ENGINE_CHILD = "GRAPHLOOPS_ENGINE_CHILD"


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
    spec = shard_spec()
    if spec:
        if only:   # 2 つの絞りを重ねると、どちらの柵も合わない回が生まれる
            print("  FAIL GL_TEST_ONLY と組の指定（GL_SHARD_TOTAL）は同時に使えない")
            raise SystemExit(1)
        tests = assign(tests, spec["index"], spec["total"])
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
    td = tempfile.TemporaryDirectory(prefix=prefix + _test_tag(), ignore_cleanup_errors=True)
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


# 固定具の子の寿命を、起こした台本のプロセスの生存に縛る口（POSIX）。台本が排他ロックを握り、子はその共有ロックを待つだけの
# 1 行（hold_code）で眠る。台本が終わる・SIGKILL で消える（変異の実行器が failfast・時間切れでグループごと殺す回）とカーネルが
# ロックを離し、子は取れた所で終わる——台本の後始末（finally・ExitStack）は SIGKILL の下では走らず、グループ・セッションを
# 抜けた子には実行器の killpg も届かないので、時間で待たせていた頃は抜けた子が寿命いっぱい残った。engine が標準入力を閉じて
# 起こす子（run_tree・run_steps・run_role の先）は標準入力の EOF で縛れないので、この口を使う（台本が自分で起こす子は
# stdin=PIPE の EOF で縛る）。番号で信号を送る後始末は足さない（止めた後に再利用された番号へ届く）
_HELD = []


def creator_lock(dir):
    """dir に排他ロックを作って、このプロセスが終わるまで握る。返すのはロックの置き場（hold_code の子に渡す）。
    置き場が既に握られていれば待たずに例外（同じ置き場を 2 度握ろうとした台本を、止まらずに赤にする）"""
    import fcntl
    path = pathlib.Path(dir) / "creator.lock"
    f = open(path, "w", encoding="utf-8")
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with LOCK:
        _HELD.append(f)
    return str(path)


def hold_code(secs, first=""):
    """固定具の子の本文（python -c <本文> <ロックの置き場>）: 起こした台本がロックを離すまで待つ。secs は今までの寿命の上限を
    そのまま残す——止める側の欠陥で子が止まらない回に、子を待つ検査が赤にならず待ち続けないため（上限を足すのではない）。
    first は待つ前に呼ぶ文（グループを抜ける os.setpgid(0, 0) など）。引用符を含まないので sh の引用の中にも置ける"""
    return (f"import fcntl, os, signal, sys; {first}signal.alarm({int(secs)}); "
            "fcntl.flock(os.open(sys.argv[1], os.O_RDONLY), fcntl.LOCK_SH)")


# 走っている台本の名前。変異の実行器（tests/mutate.py の marker_run）が、印を書いた行を『どの台本が通したか』に帰属させる口。
# 同じプロセスの中はスレッドの名前（TEST_THREAD の接頭辞）で、台本が起こした子のプロセスは作業場の名前の印（TAG）で見分ける
# ——子の起動の呼び元は、作業場を cwd に渡しさえすれば何も持たなくてよい（env の渡し口を呼び元ごとに足すと、渡さない入口が残る）。
# 書式の正本はここで、tests/mutate.py の OWNER が同じ書式を読む（揃いは tests/run.sh の mut-owner の検査が縛る）
TEST_THREAD = "gl-test~"
TAG = "GLT~"
_cur = threading.local()


def _test_tag():
    """作業場の名前に挟む台本の印。挟むのは印の写しの回（環境変数 GL_MARK_OWNERS。tests/mutate.py の marker_run が立てる）の
    台本の中だけ——普段の回の作業場の名前は変えない（名前が長くなると Windows のパスの長さの上限に近づく）"""
    name = getattr(_cur, "name", None)
    return f"{TAG}{name}~" if name and os.environ.get("GL_MARK_OWNERS") else ""


def _as_test(fn):
    """台本 fn を、台本の名前をスレッドと作業場の印に付けて呼ぶ（終われば元の名前に戻す）"""
    th = threading.current_thread()
    old = th.name
    _cur.name = f"{pathlib.Path(fn.__code__.co_filename).name}~{fn.__name__}"
    th.name = TEST_THREAD + _cur.name
    try:
        fn()
    finally:
        th.name, _cur.name = old, None


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

    engine が起こした子（環境の ENGINE_CHILD）からは、GL_TEST_ONLY で絞らない回を走らせない——台本（simulate.py・simulate_review.py）は
    run.sh を通さずに直に起こせるので、run.sh の頭の拒みだけでは一式の大半が走る。どの台本もここを通る
    """
    if os.environ.get(ENGINE_CHILD) and not os.environ.get("GL_TEST_ONLY"):
        print(f"  FAIL engine が起こした子（環境の {ENGINE_CHILD}）からは台本の一式を走らせない（人の方針: 手元で e2e の一式を回さない。"
              "CI で回る）——変更に関わる筋書きを GL_TEST_ONLY=<台本の名前>,… で数件に絞れ", flush=True)
        raise SystemExit(2)
    n = workers(len(tests))
    if n == 1:
        for fn in tests:
            try:
                _as_test(fn)
            except BaseException:   # 並列の枝と同じ 1 行を残してから投げ直す（1 本に絞った回も例外を FAIL として読める）
                print(f"  FAIL {fn.__name__} が例外で抜けた: {traceback.format_exc().strip().splitlines()[-1]}", flush=True)
                raise
        return

    def one(fn):
        _buf.lines = []
        try:
            _as_test(fn)
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


# ---- 組（shard）に分けて CI の別々の job で回す ----
# 約束は Bazel の test sharding に倣う（組の総数と 0 始まりの番号を環境で渡し、組の中の割り当ては決定的）。
# 件数の柵と全台本の和で見る検査は 1 回の実行の中では当たらないので、組は数えた値と到達した集合を名簿に書くだけで、
# 当てるのは全組を待つまとめの口（merge）の 1 か所——組ごとに外すと、どの job でも走らない検査が生まれる。
SHARD_ENV = ("GL_SHARD_TOTAL", "GL_SHARD_INDEX", "GL_SHARD_GROUP", "GL_SHARD_MANIFEST")
_deferred = []


def shard_spec(env=None):
    """組の指定を読む。無い・総数 1 なら None。形が崩れていれば FAIL で抜ける（黙って全件に戻さない）"""
    env = os.environ if env is None else env
    total = env.get("GL_SHARD_TOTAL", "")
    if total in ("", "1"):
        return None
    try:
        total, index = int(total), int(env.get("GL_SHARD_INDEX", ""))
    except ValueError:
        print(f"  FAIL 組の指定が整数でない（GL_SHARD_TOTAL={env.get('GL_SHARD_TOTAL')}・GL_SHARD_INDEX={env.get('GL_SHARD_INDEX')}）")
        raise SystemExit(2)
    if total < 1 or not 0 <= index < total:
        print(f"  FAIL 組の番号 {index} が 0..{total - 1} に無い")
        raise SystemExit(2)
    if not env.get("GL_SHARD_MANIFEST") or not env.get("GL_SHARD_GROUP"):
        # 名簿の置き場が無い分割は、和の検算が誰にも当たらない
        print("  FAIL 組に分けた回は GL_SHARD_MANIFEST（名簿の置き場）と GL_SHARD_GROUP（まとめる単位）が要る")
        raise SystemExit(2)
    return {"total": total, "index": index, "group": env["GL_SHARD_GROUP"], "dir": pathlib.Path(env["GL_SHARD_MANIFEST"])}


def assign(tests, index, total):
    """定義順の i 番目を i % total の組に割り当てる（round-robin）。どの組にも同じ一覧から同じ答えが出る"""
    return [t for i, t in enumerate(tests) if i % total == index]


def aggregate(desc, kind, seen, want):
    """全台本の和で見る検査。組の回は名簿に積んで None を返し（まとめの口が和集合で当てる）、組でない回はその場の真偽を返す。
    kind: superset＝seen が want を全部含む／count＝seen の要素の数が want"""
    if shard_spec():
        _deferred.append({"desc": desc, "kind": kind, "seen": sorted(set(seen)), "want": want})
        return None
    return judge(kind, set(seen), want)


def judge(kind, seen, want):
    if kind == "superset":
        return seen >= set(want)
    if kind == "count":
        return len(seen) == want
    raise ValueError(f"aggregate の kind が知らない値: {kind}")


def write_manifest(name, doc):
    """組の名簿を 1 つ書く（name は台本のファイル名の stem か counts）。組でない回は何もしない"""
    spec = shard_spec()
    if not spec:
        return
    spec["dir"].mkdir(parents=True, exist_ok=True)
    body = {"group": spec["group"], "total": spec["total"], "index": spec["index"], **doc}
    (spec["dir"] / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def finish(script, tests):
    """台本の main の終わりに呼ぶ。組の回は、走らせた台本の本数と積んだ和の検査を名簿に書く"""
    write_manifest(pathlib.Path(script).stem, {"tests": len(tests), "deferred": _deferred})


def expected(run_sh):
    """期待値の正本（graphloops/tests/run.sh の EXPECTED_CHECKS・EXPECTED_TESTS）を読む——写しを持たない"""
    txt = pathlib.Path(run_sh).read_text(encoding="utf-8")
    got = {k: int(v) for k, v in re.findall(r"^(EXPECTED_CHECKS|EXPECTED_TESTS)=([0-9]+)$", txt, re.M)}
    if set(got) != {"EXPECTED_CHECKS", "EXPECTED_TESTS"}:
        raise ValueError(f"{run_sh} に EXPECTED_CHECKS・EXPECTED_TESTS の行が無い")
    return got["EXPECTED_CHECKS"], got["EXPECTED_TESTS"]


def merge(docs, groups, want_checks, want_tests):
    """全組の名簿（読んだ dict の一覧）を検算し、問題の文の一覧を返す（空なら緑）"""
    bad = []
    by = {}
    for d in docs:
        by.setdefault(d.get("group"), []).append(d)
    for g in sorted(set(by) - set(groups), key=str):
        bad.append(f"知らない group {g} の名簿が在る（--groups {','.join(groups)}）")
    for g in groups:
        rows = by.get(g, [])
        if not rows:
            bad.append(f"{g}: 名簿が 1 つも無い")
            continue
        totals = {d["total"] for d in rows}
        if len(totals) != 1:
            bad.append(f"{g}: 組の総数が揃わない {sorted(totals)}")
            continue
        total = totals.pop()
        shards = {}
        for d in rows:
            shards.setdefault(d["index"], []).append(d)
        if sorted(shards) != list(range(total)):
            bad.append(f"{g}: 組の番号 {sorted(shards)} が 0..{total - 1} と一致しない（欠けた組か、範囲の外の組）")
        files = {}
        for i, ds in sorted(shards.items()):
            names = [d["name"] for d in ds]
            if len(names) != len(set(names)):
                bad.append(f"{g}: 組 {i} の名簿が重なっている {sorted(names)}")
            files[i] = frozenset(names)
        if len(set(files.values())) > 1 or not all("counts" in f for f in files.values()):
            bad.append(f"{g}: 組ごとの名簿の揃いが崩れている {dict((i, sorted(f)) for i, f in files.items())}")
            continue
        counts = [d for d in rows if d["name"] == "counts"]
        sims = [d for d in rows if d["name"] != "counts"]
        checks = sum(d["checks"] for d in counts)
        tests = sum(d["tests"] for d in counts)
        if tests != sum(d["tests"] for d in sims):
            bad.append(f"{g}: counts の台本の本数の和 {tests} が台本の名簿の和 {sum(d['tests'] for d in sims)} と違う")
        agg = {}
        for d in sims:
            for x in d["deferred"]:
                agg.setdefault((d["name"], x["desc"]), []).append(x)
        for (name, desc), xs in sorted(agg.items()):
            if len(xs) != total or len({(x["kind"], json.dumps(x["want"])) for x in xs}) != 1:
                bad.append(f"{g}: {name} の和の検査『{desc}』が全組に同じ形で無い（{len(xs)}/{total} 組）")
                continue
            seen = set().union(*(x["seen"] for x in xs))
            if not judge(xs[0]["kind"], seen, xs[0]["want"]):
                bad.append(f"{g}: {name} の和の検査『{desc}』が和集合で通らない（{len(seen)} 件・期待 {xs[0]['want']}）")
        # 組の回の和の検査は aggregate が None を返して check() に届かず checks に数えられない——組でない回の件数と揃えるため足す
        if checks + len(agg) != want_checks:
            bad.append(f"{g}: 検査の件数の和 {checks}＋和の検査 {len(agg)} が EXPECTED_CHECKS={want_checks} と違う")
        if tests != want_tests:
            bad.append(f"{g}: 台本の本数の和 {tests} が EXPECTED_TESTS={want_tests} と違う")
    return bad


def _read_dirs(dirs):
    docs = []
    for d in dirs:
        for f in sorted(pathlib.Path(d).glob("*.json")):
            docs.append({**json.loads(f.read_text(encoding="utf-8")), "name": f.stem})
    return docs


def main(argv):
    """CLI の口。
    counts --checks N --tests N: graphloops/tests/run.sh が組の回に件数を名簿に書く
    index: 組の回は組の番号を、組でない回は空を出す（形が崩れていれば exit 2）
    merge --groups a,b <置き場>...: まとめの job が全組の名簿を検算する"""
    import argparse
    ap = argparse.ArgumentParser(prog="parallel.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("counts")
    c.add_argument("--checks", type=int, required=True)
    c.add_argument("--tests", type=int, required=True)
    sub.add_parser("index")
    m = sub.add_parser("merge")
    m.add_argument("--groups", required=True)
    m.add_argument("dirs", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "index":
        spec = shard_spec()
        print("" if spec is None else spec["index"])
        return 0
    if a.cmd == "counts":
        if not shard_spec():
            print("  FAIL counts は組の回（GL_SHARD_TOTAL が 2 以上）でだけ書く")
            return 2
        write_manifest("counts", {"checks": a.checks, "tests": a.tests})
        return 0
    want_checks, want_tests = expected(pathlib.Path(__file__).resolve().parent / "run.sh")
    groups = [g for g in a.groups.split(",") if g]
    bad = merge(_read_dirs(a.dirs), groups, want_checks, want_tests)
    for b in bad:
        print("  FAIL " + b)
    if bad:
        return 1
    print(f"SHARDS_OK（{len(groups)} group の組の和が EXPECTED_CHECKS={want_checks}・EXPECTED_TESTS={want_tests} と一致し、和の検査が通った）")
    return 0


if __name__ == "__main__":
    import sys
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
