"""記録の検証器 scripts/review-record.py の検査（tests/run.sh の review-record.py の節を同じプロセスへ移した物）。

- test_validator: 表（review_record_cases.CASES）の 1 行 = 台本の検査 1 件。検証器を runpy で __main__ として走らせるので、
  終了コードの契約の境界（__main__ の段の try/except。想定外の例外を exit 2 に倒す）まで同じプロセスで通る
- test_cli_smoke_*: 子プロセスでしか見えない物（終了コードそのもの・標準出力のバイト列の文字コード・再帰の深さ）だけを数件
- test_ledger_*: 台帳（ledger.py）が台本の行を 1 件も落とさずに表へ対応づけていること
"""
import collections
import os
import pathlib
import runpy
import subprocess
import sys

import broken_records
import ledger
import pytest
from review_record_cases import ANY, CASES

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
VALIDATOR = REPO / "scripts" / "review-record.py"


@pytest.fixture(scope="session")
def work(tmp_path_factory):
    w = tmp_path_factory.mktemp("broken")
    broken_records.write_all(REPO, w)
    return w


def resolve(arg, work):
    return str(REPO / arg[len("repo:"):]) if arg.startswith("repo:") else str(work / arg)


def run_validator(args, monkeypatch, capsys):
    """検証器を __main__ として同じプロセスで走らせる ——（終了コード, 標準出力, 標準エラー）

    record_common は sys.modules から外して毎回読み直させる（子プロセスで起こす台本と同じく、import の時の行も毎回通る）。
    検証器が sys.path の先頭に足す scripts/ と argv は monkeypatch が戻す。
    """
    monkeypatch.setattr(sys, "argv", [str(VALIDATOR), *args])
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "record_common", raising=False)
    try:
        runpy.run_path(str(VALIDATOR), run_name="__main__")
        code = 0
    except SystemExit as e:
        code = 0 if e.code is None else e.code
    got = capsys.readouterr()
    return code, got.out, got.err


@pytest.mark.parametrize("case", [c for c in CASES if c.where == "inproc"], ids=lambda c: c.id)
def test_validator(case, work, monkeypatch, capsys):
    code, out, err = run_validator([resolve(a, work) for a in case.args], monkeypatch, capsys)
    shown = f"{case.was}\n--- stdout\n{out}\n--- stderr\n{err}"
    assert code == case.exit, f"exit {case.exit} を期待したが {code}: {shown}"
    # 記録の不正（2）は record_common.fail が標準エラーに出す。0 と 1 の判定と履歴は標準出力。流れを分けて見る
    # （台本は 2>&1 で混ぜて見ていた——分けて見る方が狭くない）
    if case.exit == 2:
        assert "記録が不正: " in err, f"標準エラーに記録の不正の診断が無い: {shown}"
    else:
        assert "記録が不正" not in err, f"exit {case.exit} なのに標準エラーに記録の不正の診断が在る: {shown}"
    if case.want != ANY:
        stream = err if case.exit == 2 else out
        assert case.want in stream, f"{'標準エラー' if case.exit == 2 else '標準出力'}に '{case.want}' が無い: {shown}"


def cli(*args, env=None):
    """子プロセスで検証器を起こす。出力はバイトのまま受ける（文字コードを見る検査があるので、復号はテストの側でする）"""
    return subprocess.run([sys.executable, str(VALIDATOR), *args], capture_output=True,
                          env={**os.environ, **(env or {})})


@pytest.mark.parametrize("name, code, stream, want", [
    ("hist", 0, "stdout", "連続 2 ラウンド"),
    ("tmpl-1", 1, "stdout", "前ラウンドの記録が無い"),
    ("drop-base", 2, "stderr", "記録が不正: "),
    ("unhashable-status", 2, "stderr", "想定外の例外（TypeError）"),
], ids=["exit0", "exit1", "exit2", "exit2-boundary"])
def test_cli_smoke_exit_codes(work, name, code, stream, want):
    got = cli(str(work / name))
    assert got.returncode == code, got
    assert want in getattr(got, stream).decode("utf-8"), got


@pytest.mark.parametrize("args", [(), ("{w}/tmpl-12", "{w}/tmpl-1")], ids=["no-args", "too-many-args"])
def test_cli_smoke_argument_count(work, args):
    got = cli(*[a.format(w=work) for a in args])
    assert got.returncode == 2, got
    assert "記録が不正: 引数は記録のディレクトリ 1 個" in got.stderr.decode("utf-8"), got


def test_cli_smoke_utf8_output_under_ascii_locale(work):
    """Windows の既定コンソールの類（UTF-8 でない出力の文字コード）でも、落ちずに UTF-8 で書く"""
    got = cli(str(work / "hist"), env={"PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"})
    assert got.returncode == 0, got
    assert "r1:— → r2:suggest/defer" in got.stdout.decode("utf-8"), got


def test_cli_smoke_deep_nesting(work):
    """深いネストの JSON も 1 と区別して 2 で落ちる。経路（再帰の上限で境界が受けるか、読み切って型の検査が受けるか）は
    環境で変わるので終了コードだけを見る。同じプロセスでは再帰の上限が pytest の分だけ浅いので、子で見る"""
    assert cli(str(work / "deep")).returncode == 2


def test_optimize_stops_the_suite():
    """-O の下で assert が消えたまま緑にならない（pytest.ini の filterwarnings が pytest 自身の警告を誤りにする）"""
    got = subprocess.run([sys.executable, "-O", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", str(HERE)],
                         capture_output=True, cwd=HERE)
    assert got.returncode != 0, got
    assert b"PytestConfigWarning" in got.stdout + got.stderr, got


def test_ledger_matches_script():
    """台本の検査と表の行が (終了コード, 期待の文言, 説明文) の多重集合で一致する（片方だけ直すと赤）"""
    rows = ledger.script_rows()
    table = [(c.exit, c.want, c.was) for c in CASES]
    assert collections.Counter(rows) == collections.Counter(table), (
        f"台本にだけ在る: {collections.Counter(rows) - collections.Counter(table)} / "
        f"表にだけ在る: {collections.Counter(table) - collections.Counter(rows)}")
    pairs, extra = ledger.pair(rows)
    assert all(dest for _, dest in pairs) and not extra


def test_ledger_table_is_current():
    """MIGRATION.md の台帳の表が、今の台本と表から作った物と一致する（手で直さない。python3 tests/py/ledger.py で書き直す）"""
    pairs, _ = ledger.pair(ledger.script_rows())
    assert ledger.block(ledger.DOC.read_text(encoding="utf-8")) == ledger.render(pairs)
