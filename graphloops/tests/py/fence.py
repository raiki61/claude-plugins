"""pytest の柵 2 つ。bash の台本の EXPECTED_CHECKS と同じ意図——黙って走らなかったテストに気づく。
置き場の conftest.py が pytest_configure で install(config, 置き場, 件数の定数) を呼んで載せる。

bash の台本は、環境に道具や OS の機能が無くて走らない検査を「# SKIP <能力>: <理由>」の印つきの行で出して件数に入れ、root の
tests/run.sh が合格と別に一覧にする（TAP 14 の SKIP 指示子。FAIL_ON_SKIP=1 で、SKIP_ALLOW に能力の名前が無い見送りを失敗に数える）。
ここで飛ばしを常に失敗に数えるのは、この置き場のテストが環境で分かれず 3 つの OS で全部走る前提だから——ここでの飛ばしは
環境の見送りでなく、テストが黙って消えた印になる。環境で分かれるテストを足すなら、この柵ごと見直す。

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

3. **検査の件数の柵と到達の柵**（盤面を回す台本を載せる土台の分。expect_sim で期待値を渡した置き場だけ）。台本の
   check が走った件数（conftest.py が各テストの前後の差で数えて add_sim_checks に渡す）を期待値と != で突き合わせ、
   到達した値（reach）の集合の大きさを期待値と != で突き合わせる——bash の台本の EXPECTED_CHECKS と VOCAB_REACHED・
   DELIVERY_SEEN と同じ意図。当てるのは件数の柵と同じ全件の回で、しかも -k・-m・--deselect で 1 件も選び外さなかった回
   だけ（選び外すと走る検査が減るのは正しい）。外した回は理由を 1 行出す。

**pytest-xdist（-n）の下でも同じ数え方にする。** controller は自分で集めず、worker が集めて走らせる（xdist の How it works）。
worker では今の数え方（collectstart・itemcollected・add_sim_checks・reach）をそのまま動かし、結果を config.workeroutput に
入れる。controller は pytest_testnodedown で node.workeroutput を受け取り、件数とモジュールの集合は 1 つの worker の値を
（全 worker が同じ物を集める——違えばそれ自体を失敗にする）、検査の件数は和を、到達は和集合を使う。worker から届く node id の
一覧で数えないのは、テストが 0 件のモジュールが id に現れず、上の 2 の「テストを全部消したファイル」を見落とすから。
飛ばしの見張りは controller に届く報告（xdist が運ぶ）で見る。worker は判定しない。

状態は config ごとの登録物に持つ（モジュールの大域に置くと、pytester で内側に回した pytest と数が混ざる）。
"""
import pathlib

import pytest


NAME = "graphloops-fence"


def install(config, root, expected):
    config.pluginmanager.register(Fence(pathlib.Path(root).resolve(), expected), NAME)


def expect_sim(config, checks, reached):
    """盤面を回す台本の検査の件数と、到達した値の数の期待値を渡す（渡さない置き場ではこの 2 つの柵は付かない）"""
    config.pluginmanager.get_plugin(NAME).expected_sim = (checks, reached)


def add_sim_checks(config, n):
    config.pluginmanager.get_plugin(NAME).sim_checks += n


def reach(config, value):
    config.pluginmanager.get_plugin(NAME).reached.add(str(value))


class Fence:
    def __init__(self, root, expected):
        self.root = root
        self.expected = expected
        self.expected_sim = None
        self.collected = 0
        self.modules = set()
        self.sim_checks = 0
        self.reached = set()
        self.deselected = 0
        self.workers = []   # controller が受け取った worker ごとの結果（-n の回だけ）
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

    def pytest_deselected(self, items):
        self.deselected += len(items)

    @pytest.hookimpl(optionalhook=True)   # pytest-xdist の hook（入っていない回は呼ばれない）
    def pytest_testnodedown(self, node, error):
        got = getattr(node, "workeroutput", {}).get(NAME)
        self.workers.append(got if got is not None else {"lost": str(error or "結果が届かない")})

    def pytest_collectreport(self, report):
        # モジュール丸ごとの飛ばしは収集の段で起き、テストの報告（runtest_logreport）には現れない
        if report.skipped:
            self.skipped.append(f"{report.nodeid}: {_why(report)}")

    def pytest_runtest_logreport(self, report):
        if report.skipped:
            self.skipped.append(f"{report.nodeid}: {_why(report)}")

    def pytest_sessionfinish(self, session):
        if hasattr(session.config, "workerinput"):   # worker は数えて controller へ渡すだけ（判定は controller）
            session.config.workeroutput[NAME] = {
                "collected": self.collected, "modules": sorted(map(str, self.modules)),
                "sim_checks": self.sim_checks, "reached": sorted(self.reached), "deselected": self.deselected}
            return
        collected, modules, sim_checks, reached, deselected = self._totals()
        if self.skipped:
            self.problems.append(f"飛ばされたテストが {len(self.skipped)} 件（飛ばしは失敗扱い）: " + " / ".join(self.skipped[:5]))
        files = {p.resolve() for pat in session.config.getini("python_files") for p in self.root.rglob(pat)}
        full = modules == files
        if not full:
            self.notes.append(f"件数の柵を外した（置き場のテストのファイル {len(files)} 本のうち {len(modules & files)} 本だけを集めた）")
        elif collected != self.expected:
            self.problems.append(f"集めたテストが {collected} 件（{self.expected} 件を期待）——テストの消滅か、件数の更新漏れ")
        if self.expected_sim is not None and full:
            want_checks, want_reached = self.expected_sim
            if deselected:
                self.notes.append(f"検査の件数の柵と到達の柵を外した（{deselected} 件のテストを選び外した）")
            else:
                if sim_checks != want_checks:
                    self.problems.append(f"台本の検査が {sim_checks} 件走った（{want_checks} 件を期待）——検査の空振りか、件数の更新漏れ")
                if len(reached) != want_reached:
                    self.problems.append(f"到達した値が {len(reached)} 個（{want_reached} 個を期待）: {sorted(reached)}")
        if self.problems and session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def _totals(self):
        """(集めた件数, 集めたモジュール, 検査の件数, 到達, 選び外した件数)。-n の回は worker から届いた値で組む"""
        if not self.workers:
            return self.collected, self.modules, self.sim_checks, self.reached, self.deselected
        lost = [w["lost"] for w in self.workers if "lost" in w]
        got = [w for w in self.workers if "lost" not in w]
        if lost:
            self.problems.append(f"worker {len(lost)} 本の数えた結果が届かない（{lost[0]}）——件数の柵を当てられない")
        if not got:
            return 0, set(), 0, set(), 0
        shapes = {(w["collected"], tuple(w["modules"]), w["deselected"]) for w in got}
        if len(shapes) > 1:
            self.problems.append(f"worker ごとに集めた物が違う（{len(shapes)} 通り）——件数の柵を当てられない")
        first = got[0]
        return (first["collected"], {pathlib.Path(m) for m in first["modules"]}, sum(w["sim_checks"] for w in got),
                set().union(*(w["reached"] for w in got)), first["deselected"])

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
