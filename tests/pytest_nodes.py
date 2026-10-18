"""pytest の結果（集めた node id・選び外した件数・落ちたテスト）を JSON で書く pytest のプラグイン。

試験のツール（tests/mutate.py・tests/py/ledger.py・tests/py/coverage_proof.py）が pytest の結果を読む 1 か所。前は pytest が人に
見せる出力（-ra の短い要約の「FAILED <node id> - …」・--collect-only -q の行・「N deselected」）を正規表現で拾っていて、pytest の
版や表示の設定（-q の数・色・幅）で黙って読み違えうる（docs/standards/machine-readable-values.md の決まり 2）。node id は pytest の
報告（report.nodeid・item.nodeid）からそのまま取る（https://docs.pytest.org/en/stable/reference/reference.html#hooks）。

使い方: 環境変数 PYTEST_NODES_OUT に書く先のパスを置き、`-p pytest_nodes` で読み込む（このファイルの置き場を PYTHONPATH に足す）。
JUnit XML（--junitxml）を使わないのは、testcase の classname が node id のパスと class を `.` でつないだ形になり、node id に戻せないため。

書く形: {"collected": [node id…], "deselected": 件数, "failed": [落ちたテストの node id…], "errors": [集められなかったファイルの node id…]}
- collected は集めて選び外した後に残った物。pytest-xdist で並べた回は親が集めず選び外しもしないので、collected は空、
  deselected は 0（読む側は並べない回でだけ使う）。
- failed は呼び出し・前後の準備（setup・teardown）のどこかで落ちたテスト。errors は集めるときに落ちたファイル（読み込みの失敗など）。
"""
import json
import os

import pytest

OUT = "PYTEST_NODES_OUT"


class _Nodes:
    def __init__(self):
        self.collected, self.deselected, self.failed, self.errors = [], 0, [], []

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]

    def pytest_deselected(self, items):
        self.deselected += len(items)

    def pytest_collectreport(self, report):
        if report.failed:
            self.errors.append(report.nodeid)

    def pytest_runtest_logreport(self, report):
        if report.failed and report.nodeid not in self.failed:
            self.failed.append(report.nodeid)

    @pytest.hookimpl(tryfirst=True)   # ほかのプラグインの終わりの処理（件数のチェックなど）が抜けても、先に書いておく
    def pytest_sessionfinish(self, session):
        with open(os.environ[OUT], "w", encoding="utf-8") as f:
            json.dump({"collected": self.collected, "deselected": self.deselected,
                       "failed": self.failed, "errors": self.errors}, f, ensure_ascii=False)


def pytest_configure(config):
    # pytest-xdist の worker は書かない（報告は親へ送られ、親の同じフックに届く。worker も書くと同じファイルを奪い合う）
    if os.environ.get(OUT) and not hasattr(config, "workerinput"):
        config.pluginmanager.register(_Nodes(), "pytest_nodes_out")


def run(argv, cwd, env=None):
    """argv（`python -m pytest …` までの起動の列。`-p pytest_nodes` はここで足す）を走らせる ——（CompletedProcess, 結果の dict か None）。
    結果が None なのは pytest が終わりまで来なかった（起動の失敗・内部の誤り）とき。呼び元が終了コードと合わせて止める"""
    import subprocess
    import tempfile
    env = dict(os.environ if env is None else env)
    here = os.path.dirname(os.path.abspath(__file__))
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [here, env.get("PYTHONPATH")]))
    fd, out = tempfile.mkstemp(prefix="pytest-nodes-", suffix=".json")
    os.close(fd)
    env[OUT] = out
    try:
        got = subprocess.run([*argv, "-p", "pytest_nodes"], cwd=cwd, env=env, capture_output=True)
        try:
            with open(out, encoding="utf-8") as f:
                return got, json.load(f)
        except ValueError:
            return got, None   # 空のまま（pytest が終わりまで来なかった）
    finally:
        os.unlink(out)
