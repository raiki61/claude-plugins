"""Python を選ぶ入口（graphloops の hooks/run-python.sh と、convergence-loops の scripts/run-python.sh）が、PATH の頭の python3 が
Windows の Microsoft Store へ誘う代わりの物（起動すると案内を出して 9009 で終わる）でも、次の python へ進むこと。
convergence-loops は自前の試験の置き場を持たないので、同じ選び方の写しをここで一緒に見る"""
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import PLUGIN, REPO

ENTRIES = {"graphloops": PLUGIN / "hooks" / "run-python.sh",
           "convergence-loops": REPO / "convergence-loops" / "scripts" / "run-python.sh"}
NOT_FOUND = {"graphloops": 1, "convergence-loops": 127}   # 見つからないときの終了の値（入口の頭の注記）

pytestmark = pytest.mark.skipif(os.name != "posix", reason="SKIP posix-mode: 偽の python を PATH のフォルダに置く形は POSIX の物")


def fake_dir(tmp_path, with_python):
    """Store の代わりの物を python3 に置き、with_python なら本物の Python を python の名で並べたフォルダ"""
    d = tmp_path / "bin"
    d.mkdir()
    (d / "python3").write_text("#!/bin/sh\necho 'Python was not found; run without arguments to install from the Microsoft Store' >&2\n"
                               "exit 9009\n", encoding="utf-8")
    (d / "python3").chmod(0o755)
    if with_python:
        (d / "python").symlink_to(sys.executable)
    return d


def run(entry, path, *args, stdin="", tmp=None):
    env = {"PATH": str(path), **({"TMPDIR": str(tmp)} if tmp else {})}
    return subprocess.run([shutil.which("bash"), str(entry), *args], input=stdin, capture_output=True, text=True, encoding="utf-8",
                          env=env, timeout=60)


@pytest.mark.parametrize("name", list(ENTRIES))
def test_skips_store_stub(tmp_path, name):
    """python3 が代わりの物でも、python の本物で台本が走る（今までの `command -v python3` の形はここで代わりの物を起動して落ちた）"""
    r = run(ENTRIES[name], fake_dir(tmp_path, True), "-c", "import sys; print(sys.version_info >= (3, 12))")
    assert (r.returncode, r.stdout.strip()) == (0, "True"), r.stderr


@pytest.mark.parametrize("name", list(ENTRIES))
def test_none_found_says_why(tmp_path, name):
    """選べなければ、試した名前と直し方（アプリ実行エイリアスで python.exe などを切る）を 1 行で出し、入口ごとに決めた値で終わる（代わりの物の終了の値をそのまま返さない）"""
    r = run(ENTRIES[name], fake_dir(tmp_path, False), "-c", "pass")
    assert r.returncode == NOT_FOUND[name]
    assert r.stderr.startswith(f"{name}: Python 3.12 ") and all(w in r.stderr for w in ("python3", "py -3", "python.exe"))


def test_once_per_session(tmp_path):
    """読了のフックは Read のたびに走るので、選べない知らせは会話ごとに 1 回だけ誤りにし、2 回目からは黙って 0 で終わる"""
    path, payload = fake_dir(tmp_path, False), json.dumps({"session_id": "sess-1", "tool_name": "Read"})
    first = run(ENTRIES["graphloops"], path, "--once", "x.py", stdin=payload, tmp=tmp_path)
    second = run(ENTRIES["graphloops"], path, "--once", "x.py", stdin=payload, tmp=tmp_path)
    other = run(ENTRIES["graphloops"], path, "--once", "x.py", stdin=payload.replace("sess-1", "sess-2"), tmp=tmp_path)
    assert (first.returncode, second.returncode, second.stderr, other.returncode) == (1, 0, "", 1)


def test_hook_registration_goes_through_entry():
    """読了のフックの登録は、素の python3 でなく入口を通す（init の自己点検は、この登録の語をそのまま走らせて確かめる）"""
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["PostToolUse"]
    commands = [h["command"] for m in hooks for h in m["hooks"]]
    assert commands == ['bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" --once "${CLAUDE_PLUGIN_ROOT}/hooks/record-read.py"']
