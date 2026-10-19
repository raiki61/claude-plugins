"""記録の検証器 scripts/review-record.py の検査（tests/run.sh の review-record.py のセクションを同じプロセスへ移した物）。

- test_validator: 表（review_record_cases.CASES）の 1 行 = 台本の検査 1 件。検証器を runpy で __main__ として走らせるので、
  終了コードの契約の境界（__main__ の段の try/except。想定外の例外を exit 2 に倒す）まで同じプロセスで通る
- test_validator_in_child: 表の where が smoke の行（再帰の深さが同じプロセスでは pytest の分だけ浅い）を子プロセスで起動し（cli）、
  test_validator と同じ check() で終了コード・標準出力・標準エラーを検める
- test_cli_smoke_*: 子プロセスでしか見えない物（終了コードそのもの・標準出力のバイト列の文字コード）だけを数件
- test_ledger_*: 台帳（ledger.py）が台本の行を 1 件も落とさずに表へ対応づけ、行き先が集めたテストに在ること
"""
import collections
import os
import pathlib
import runpy
import subprocess
import sys

import broken_records
import coverage_proof
import ledger
import pytest
from review_record_cases import ANY, CASES, Case

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
VALIDATOR = REPO / "convergence-loops" / "scripts" / "review-record.py"


@pytest.fixture(scope="session")
def work(tmp_path_factory):
    w = tmp_path_factory.mktemp("broken")
    broken_records.write_all(REPO, w)
    return w


def resolve(arg, work):
    if arg == "--json":
        return arg
    return str(REPO / arg[len("repo:"):]) if arg.startswith("repo:") else str(work / arg)


def run_validator(args, monkeypatch, capsys):
    """検証器を __main__ として同じプロセスで走らせる ——（終了コード, 標準出力, 標準エラー）

    record_common は sys.modules から外して毎回読み直させる（子プロセスで起動する台本と同じく、import の時の行も毎回通る）。
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


def check(case, code, out, err):
    shown = f"{case.was}\n--- stdout\n{out}\n--- stderr\n{err}"
    assert code == case.exit, f"exit {case.exit} を期待したが {code}: {shown}"
    # 記録の不正（2）は record_common.fail が標準エラーに出す。0 と 1 の判定と履歴は標準出力。流れを分けて見る
    # （台本は 2>&1 で混ぜて見ていた——分けて見る方が狭くない）
    if case.exit == 2:
        assert "記録が不正: " in err, f"標準エラーに記録の不正の診断が無い: {shown}"
    else:
        assert "記録が不正" not in err, f"exit {case.exit} なのに標準エラーに記録の不正の診断が在る: {shown}"
    if case.want != ANY:
        # 空の期待は部分一致が恒真になる（台本の expect_output の頭の番人と同じ）
        assert case.want.strip(), f"期待の文言が空（表の行の want。見ないなら ANY）: {case.id}"
        # --json は終了コードによらず結果の JSON を標準出力に出す（exit 2 の診断は標準エラーにも出る）
        on_err = case.exit == 2 and "--json" not in case.args
        stream = err if on_err else out
        assert case.want in stream, f"{'標準エラー' if on_err else '標準出力'}に '{case.want}' が無い: {shown}"


@pytest.mark.parametrize("case", [c for c in CASES if c.where == "inproc"], ids=lambda c: c.id)
def test_validator(case, work, monkeypatch, capsys):
    check(case, *run_validator([resolve(a, work) for a in case.args], monkeypatch, capsys))


def test_check_rejects_empty_want():
    with pytest.raises(AssertionError, match="期待の文言が空"):
        check(Case("empty", (), 0, " ", "空の期待"), 0, "何かの出力", "")


def cli(*args, env=None):
    """子プロセスで検証器を起動する。出力はバイトのまま受ける（文字コードを見る検査があるので、復号はテストの側でする）"""
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


@pytest.mark.parametrize("case", [c for c in CASES if c.where == "smoke"], ids=lambda c: c.id)
def test_validator_in_child(case, work):
    got = cli(*[resolve(a, work) for a in case.args])
    check(case, got.returncode, got.stdout.decode("utf-8", "replace"), got.stderr.decode("utf-8", "replace"))


def test_optimize_stops_the_suite():
    got = subprocess.run([sys.executable, "-O", "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", str(HERE)],
                         capture_output=True, cwd=HERE)
    assert got.returncode != 0, got
    assert b"PytestConfigWarning" in got.stdout + got.stderr, got


@pytest.fixture(scope="session")
def collected_ids():
    return ledger.collected()


@pytest.fixture(scope="session")
def pairs():
    return ledger.pair(ledger.script_rows())[0]


def test_ledger_matches_script(pairs, collected_ids):
    rows = [r for r, _ in pairs]
    table = [ledger.row_of(c) for c in CASES]
    assert collections.Counter(rows) == collections.Counter(table), (
        f"台本にだけ在る: {collections.Counter(rows) - collections.Counter(table)} / "
        f"表にだけ在る: {collections.Counter(table) - collections.Counter(rows)}")
    assert not ledger.stray(pairs, collected_ids), "行き先が集めたテストに無いか、ほかの行と重なる（表の where・id を見よ）"


# 本物の pairs と集めた id から、入口が実際に作る状態を作る: where の誤記・id の重複は「集まらない」、潰れた行き先は「重なる」
@pytest.mark.parametrize("breaks", ["not-collected", "shared"])
def test_ledger_stray_catches(pairs, collected_ids, breaks):
    ids, bad = set(collected_ids), list(pairs)
    if breaks == "not-collected":
        ids.discard(bad[0][1])
    else:
        bad[1] = (bad[1][0], bad[0][1])
    assert {r for r, _ in ledger.stray(bad, ids)} >= {bad[0][0]}


def test_ledger_dest_deselects_one(pairs):
    """台帳の行き先を、赤の腕と同じ起動方法（cwd はリポジトリのルート）で --deselect に渡すと、ちょうど 1 件外れる"""
    got, res = coverage_proof.pytest_nodes.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                                                "--deselect", pairs[0][1], str(HERE)], cwd=REPO)
    assert got.returncode == 0, got
    assert coverage_proof.deselected(["--deselect", pairs[0][1]], res, got.stdout.decode("utf-8", "replace")) == 1, got


@pytest.mark.parametrize("body, why", [
    ("undefined_helper 1 x y", "読み切れない"),
    ('expect_output 1 "x" "y" "$UNSET_VAR"', "読み切れない"),
    ("ran=$((ran + 1))", "expect_output・expect_exit を通らない"),
], ids=["undefined-helper", "undefined-var", "hand-counted"])
def test_ledger_script_rows_rejects_unread(tmp_path, body, why):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "run.sh").write_text("\n".join([ledger.SECTION[0], body, ledger.SECTION[1], ""]), encoding="utf-8")
    with pytest.raises(SystemExit, match=why):
        ledger.script_rows(root=tmp_path)


def test_ledger_table_is_current(pairs):
    assert ledger.block(ledger.DOC.read_text(encoding="utf-8")) == ledger.render(pairs), \
        "MIGRATION.md の台帳の表が古い——手で直さず python3 tests/py/ledger.py で書き直せ"


@pytest.mark.parametrize("raised, code", [
    (SystemExit("台帳の不備の文"), 2),
    (ValueError("境目が無い"), 2),
    (SystemExit(1), 1),
], ids=["systemexit-text", "exception", "systemexit-int"])
def test_coverage_proof_boundary(monkeypatch, raised, code):
    def main():
        raise raised
    monkeypatch.setattr(coverage_proof, "main", main)
    with pytest.raises(SystemExit) as e:
        coverage_proof.guarded_main()
    assert e.value.code == code


def test_coverage_proof_deselected_nothing_stops():
    res = {"collected": [], "deselected": 0, "failed": [], "errors": []}
    assert coverage_proof.deselected([], res, "181 passed in 1.8s") == 0
    with pytest.raises(SystemExit) as e:
        coverage_proof.deselected(["--deselect", "tests/py/test_review_record.py::test_validator[hist-carry-age]"],
                                  res, "181 passed in 1.8s")
    assert e.value.code == 2


def test_coverage_proof_unread_result_stops():
    """pytest の結果の JSON が無い（pytest が終わりまで来なかった）回は、選び外した件数を 0 と読まずに止める"""
    with pytest.raises(SystemExit) as e:
        coverage_proof.deselected([], None, "INTERNALERROR")
    assert e.value.code == 2


@pytest.mark.parametrize("change", ["validator", "script-before-end", "templates", "script-after-end"])
def test_coverage_proof_digest_tracks_inputs(tmp_path, change):
    cl = tmp_path / "convergence-loops"
    (cl / "scripts").mkdir(parents=True)
    (cl / "templates" / "sub").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    files = {"validator": cl / "scripts" / "review-record.py", "templates": cl / "templates" / "sub" / "r.json"}
    for f in [*files.values(), cl / "scripts" / "record_common.py"]:
        f.write_text("x\n", encoding="utf-8")
    script = tmp_path / "tests" / "run.sh"
    lines = ["head", ledger.SECTION[0], "body", ledger.SECTION[1], "tail"]
    script.write_text("\n".join(lines), encoding="utf-8")
    before = coverage_proof.inputs_digest(tmp_path, ("v",))
    if change == "script-before-end":
        script.write_text("\n".join(["head2", *lines[1:]]), encoding="utf-8")
    elif change == "script-after-end":
        script.write_text("\n".join([*lines[:-1], "tail2"]), encoding="utf-8")
    else:
        files[change].write_text("y\n", encoding="utf-8")
    assert (coverage_proof.inputs_digest(tmp_path, ("v",)) != before) == (change != "script-after-end")


FAKE_COVERAGE = '''import os
class Coverage:
    @classmethod
    def current(cls):
        return cls()
    def switch_context(self, name):
        with open(os.environ["FAKE_CTX"], "w", encoding="utf-8") as f:
            f.write(name)
def process_startup():
    return Coverage() if os.environ["FAKE_STARTED_BY"] == "site" else None
'''


@pytest.mark.parametrize("started_by", ["site", "pth"])
def test_coverage_proof_site_names_validator_launch(tmp_path, started_by):
    """検証器の起動に引数の文脈を付ける。pip で入れた coverage.py は .pth が先に測りを始め、sitecustomize の process_startup は
    None を返す（pth）。そのときも始まっている測りに付ける"""
    (tmp_path / "fake").mkdir()
    (tmp_path / "fake" / "coverage.py").write_text(FAKE_COVERAGE, encoding="utf-8")
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "sitecustomize.py").write_text(coverage_proof.SITE, encoding="utf-8")
    script = tmp_path / "scripts" / "review-record.py"
    script.parent.mkdir()
    script.write_text("", encoding="utf-8")
    ctx = tmp_path / "ctx"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(tmp_path / "site"), str(tmp_path / "fake")]),
           "COVERAGE_PROCESS_START": "x", "COVPROOF_WORK": str(tmp_path / "w"), "COVPROOF_ROOT": str(REPO),
           "FAKE_CTX": str(ctx), "FAKE_STARTED_BY": started_by}
    got = subprocess.run([sys.executable, str(script), str(tmp_path / "w" / "hist"), str(REPO / "t.json")],
                         env=env, capture_output=True)
    assert got.returncode == 0, got
    assert ctx.read_text(encoding="utf-8") == "argv:hist repo:t.json"
