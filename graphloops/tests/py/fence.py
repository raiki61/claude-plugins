"""pytest の柵 2 つ。bash の台本の EXPECTED_CHECKS と同じ意図——黙って走らなかったテストに気づく。
置き場の conftest.py が pytest_configure で install(config, 置き場, 件数の定数) を呼んで載せる。

1. **飛ばしは失敗。** テスト単位の skip・skipif・xfail（pytest_runtest_logreport）と、モジュール丸ごとの
   skip(allow_module_level=True)・importorskip（pytest_collectreport）の両方を拾う。後者を見ないと、import できない
   モジュールがテストごと消えても緑になる。xfail も「走らせたが結果を見ない」ので飛ばしに数える。
2. **件数の柵。** 置き場の中で集めたテストの数を、件数の定数と != で突き合わせる。下限（<）にしないのは bash 側と
   同じ理由——テストを消した変更が緑で通る。数えるのは pytest_itemcollected（-k・-m・--deselect・--sw・testmon の
   選び直しより前）なので、集めた後で絞る回は柵を付けたまま突き合わせてよい。
   **置き場のテストのファイルを全部集めた回だけ当てる。** 引数のパス・node id・--ignore・--lf・testmon が
   ファイルを集めない回は、集めたモジュールの集合が置き場のファイルの集合（python_files の形で glob）と食い違うので、
   柵を外して理由を 1 行出す。絞り方を選択肢の表で推し量らない——手で並べた表は、pytest や plugin が集める段の
   選択肢を足した周に黙って外れる。テストが 0 件になったファイルもモジュールとしては集まるので、全件の回のままで赤になる。

状態は config ごとの登録物に持つ（モジュールの大域に置くと、pytester で内側に回した pytest と数が混ざる）。
"""
import pathlib

import pytest


def install(config, root, expected):
    config.pluginmanager.register(Fence(pathlib.Path(root).resolve(), expected))


class Fence:
    def __init__(self, root, expected):
        self.root = root
        self.expected = expected
        self.collected = 0
        self.modules = set()
        self.skipped = []
        self.notes = []
        self.problems = []

    def _inside(self, path):
        return pathlib.Path(path).resolve().is_relative_to(self.root)

    def pytest_collectstart(self, collector):
        if isinstance(collector, pytest.Module) and self._inside(collector.path):
            self.modules.add(pathlib.Path(collector.path).resolve())

    def pytest_itemcollected(self, item):
        if self._inside(item.path):
            self.collected += 1

    def pytest_collectreport(self, report):
        # モジュール丸ごとの飛ばしは収集の段で起き、テストの報告（runtest_logreport）には現れない
        if report.skipped:
            self.skipped.append(f"{report.nodeid}: {_why(report)}")

    def pytest_runtest_logreport(self, report):
        if report.skipped:
            self.skipped.append(f"{report.nodeid}: {_why(report)}")

    def pytest_sessionfinish(self, session):
        if self.skipped:
            self.problems.append(f"飛ばされたテストが {len(self.skipped)} 件（飛ばしは失敗扱い）: " + " / ".join(self.skipped[:5]))
        files = {p.resolve() for pat in session.config.getini("python_files") for p in self.root.rglob(pat)}
        if self.modules != files:
            self.notes.append(f"件数の柵を外した（置き場のテストのファイル {len(files)} 本のうち {len(self.modules & files)} 本だけを集めた）")
        elif self.collected != self.expected:
            self.problems.append(f"集めたテストが {self.collected} 件（{self.expected} 件を期待）——テストの消滅か、件数の更新漏れ")
        if self.problems and session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter):
        for n in self.notes:
            terminalreporter.write_line(n)
        for p in self.problems:
            terminalreporter.write_line(p, red=True)


def _why(report):
    if hasattr(report, "wasxfail"):
        return f"xfail（{report.wasxfail}）"
    lr = report.longrepr
    return str(lr[2] if isinstance(lr, tuple) and len(lr) == 3 else lr)
