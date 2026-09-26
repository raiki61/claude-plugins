"""台本用の小さなテストの実行器: <dir>/test_*.py の test_* 関数を走らせ、JUnit XML を書く（pytest の --junitxml の形の要点だけ）。
TDD の流れ（graphs/review-loop-tdd.json）の赤・緑の確認を、台本のリポジトリで pytest なしに撃つため。
モジュールの読み込みで落ちたら error（テスト 1 件分の行）、テストの中の例外は failure。1 件でも落ちたら exit 1。

    python3 tinyjunit.py <JUnit XML の書き先> [<テストの置き場>（既定 tests）]
"""
import importlib.util
import pathlib
import sys
from xml.sax.saxutils import quoteattr


def main():
    out, root = sys.argv[1], pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "tests")
    rows, bad = [], 0
    for f in sorted(root.glob("test_*.py")):
        cls = quoteattr(".".join(f.with_suffix("").parts))
        spec = importlib.util.spec_from_file_location(f.stem, f)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:  # noqa: BLE001 — 読み込みの失敗は種類を問わず error の行にする
            rows.append(f"<testcase classname={cls} name={quoteattr(f.stem)}><error message={quoteattr(repr(e))}/></testcase>")
            bad += 1
            continue
        for name in sorted(n for n, v in vars(mod).items() if n.startswith("test_") and callable(v)):
            try:
                getattr(mod, name)()
                rows.append(f"<testcase classname={cls} name={quoteattr(name)}/>")
            except Exception as e:  # noqa: BLE001 — テストの中の例外は failure
                rows.append(f"<testcase classname={cls} name={quoteattr(name)}><failure message={quoteattr(repr(e))}/></testcase>")
                bad += 1
    pathlib.Path(out).write_text('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="tinyjunit">'
                                 + "".join(rows) + "</testsuite></testsuites>", encoding="utf-8")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
