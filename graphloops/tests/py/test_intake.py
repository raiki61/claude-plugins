"""踏んだ事実を利用者の環境に残す記録器（engine/intake.py）と、その口（loop.py の最上段・loop.py intake）。
launch の ok でない行は simulate.py の test_engine_launch、報告の頭の 1 行は simulate_review.py の test_converges が端から端まで見る。"""
import http.server
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import types

import pytest

from conftest import PLUGIN, REPO
from engine import commands, intake
from engine.commands import launch_cause

LOOP = PLUGIN / "scripts" / "loop.py"


def loop(*args, env=None, cwd=None):
    e = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PLUGIN_DATA", intake.DETAIL_ENV)}
    return subprocess.run([sys.executable, str(LOOP), *args], capture_output=True, text=True, encoding="utf-8",
                          env={**e, **(env or {})}, cwd=cwd)


def rows(d):
    f = pathlib.Path(d) / intake.LOG
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.is_file() else []


def test_failure_leaves_structured_row_with_key_without_version(tmp_path):
    data = tmp_path / "data"
    r = loop("next", "--dir", str(tmp_path / "none"), env={"CLAUDE_PLUGIN_DATA": str(data)})
    assert r.returncode == 2
    [row] = rows(data)
    assert row["kind"] == "auto" and row["where"] == "loop.py next" and row["exit"] == 2
    assert row["exc"] == "SystemExit" and row["func"] == "board.__init__"   # die の呼び元（util.py の小ツールは飛ばす）
    assert {"plugin", "version", "os", "python", "key"} <= set(row) and "stderr" not in row and "what" not in row
    assert intake.key_of({**row, "version": "99.0.0"}) == row["key"]


def test_stderr_head_only_when_opted_in(tmp_path):
    data = tmp_path / "data"
    r = loop("next", "--dir", str(tmp_path / "none"), env={"CLAUDE_PLUGIN_DATA": str(data), intake.DETAIL_ENV: "1"})
    [row] = rows(data)
    assert r.returncode == 2 and "読めない" in row["stderr"] and len(row["stderr"]) <= intake.CLIP


def test_different_failures_of_one_subcommand_get_different_keys(tmp_path):
    data = tmp_path / "data"
    env = {"CLAUDE_PLUGIN_DATA": str(data)}
    loop("next", "--dir", str(tmp_path / "none"), env=env)       # 盤面が読めない
    loop("next", env=env, cwd=tmp_path)                          # --dir が無く current も無い（git の外）
    a, b = rows(data)
    assert a["where"] == b["where"] == "loop.py next" and a["exit"] == b["exit"] == 2
    assert a["func"] != b["func"] and a["key"] != b["key"]


def test_recording_failure_changes_neither_exit_code_nor_stderr(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    args = ("next", "--dir", str(tmp_path / "none"))
    plain = loop(*args)
    broken = loop(*args, env={"CLAUDE_PLUGIN_DATA": str(blocker / "sub")})   # 置き場が作れない
    assert (broken.returncode, broken.stderr, broken.stdout) == (plain.returncode, plain.stderr, plain.stdout)


def test_data_dir_flag_on_other_subcommands_is_not_a_place_to_write(tmp_path):
    r = loop("next", "--dir", "none", "--data-dir", "stray", cwd=tmp_path)
    assert r.returncode == 2 and not (tmp_path / "stray").exists()


def test_unreadable_board_under_dir_keeps_reject_exit(tmp_path):
    """--dir の盤面が壊れていても、記録器の読みは SystemExit を上げない（exit 1 の拒否が 2 に化けない）"""
    board = tmp_path / "board"
    board.mkdir()
    (board / "state.json").write_text("{", encoding="utf-8")
    data = tmp_path / "data"
    r = loop("intake", "--what", " ", "--dir", str(board), "--data-dir", str(data))
    assert r.returncode == 1 and r.stderr.count("NG ") == 1 and "空" in r.stderr
    [row] = rows(data)
    assert row["exit"] == 1 and row["exc"] == "Reject" and "run" not in row


@pytest.mark.parametrize("argv,want", [
    (["done", "--node", "p1.hygiene[src/secret/path.py]#2"], "loop.py done --node p1.hygiene"),
    (["done", "--node=p2.diagnose#3", "--dir", "x"], "loop.py done --node p2.diagnose"),
    (["--x"], "loop.py ?"),
    (["/home/me/secret/loop-state"], "loop.py ?"),
    (["done", "--node", "../../etc/passwd"], "loop.py done"),
])
def test_where_keeps_only_stable_parts(argv, want):
    assert intake.where_of(argv) == want


def test_data_dir_order_and_derivation(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    assert intake.data_dir() is None
    root = tmp_path / "plugins" / "cache" / "mk.t" / "graphloops" / "1.2.3"
    root.mkdir(parents=True)
    monkeypatch.setattr(intake, "PLUGIN_ROOT", root)
    assert intake.data_dir() == tmp_path / "plugins" / "data" / "graphloops-mk-t"   # Claude Code の id の規則
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "env"))
    assert intake.data_dir() == tmp_path / "env"
    assert intake.data_dir("${CLAUDE_PLUGIN_DATA}") == tmp_path / "env"
    assert intake.data_dir(str(tmp_path / "given")) == tmp_path / "given"


def test_commit_is_the_plugin_not_the_repo_under_review(tmp_path, monkeypatch):
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    subprocess.run(["git", "-C", str(other), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    monkeypatch.chdir(other)
    mine = subprocess.run(["git", "-C", str(PLUGIN), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, encoding="utf-8")
    assert intake.provenance().get("commit") == ((mine.stdout.strip() or None) if mine.returncode == 0 else None)
    root = tmp_path / "plugins" / "cache" / "mkt" / "graphloops" / "1.0.0"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text('{"name": "graphloops", "version": "1.0.0"}', encoding="utf-8")
    (tmp_path / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"graphloops@mkt": [{"installPath": str(root), "gitCommitSha": "abcdef0123456789"}]}}), encoding="utf-8")
    p = intake.provenance({"engine": {"root": str(root), "version": "1.0.0"}, "loop_name": "review-loop", "run_id": "r1", "round": 2, "graph_sha": "g"})
    assert (p["plugin"], p["version"], p["commit"]) == ("graphloops", "1.0.0", "abcdef012345")
    assert p["run"] == {"loop_name": "review-loop", "run_id": "r1", "round": 2, "graph_sha": "g"}
    assert intake.stamp_line({"engine": {"root": str(root), "version": "1.0.0"}, "loop_name": "review-loop",
                              "run_id": "r1", "round": 2, "graph_sha": "g"}) == "graphloops 1.0.0 (abcdef012345) / review-loop run r1 / round 2 / graph g"


def _cached(tmp_path, ver, name="graphloops"):
    root = tmp_path / "plugins" / "cache" / "mkt" / name / ver
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name, "version": ver}), encoding="utf-8")
    return root


def _ledger_row(path, scope="user", project=None):
    """台帳の 1 行。形は実物（~/.claude-p3/plugins/installed_plugins.json、2026-10-19）から採った——version 2 の台帳で、
    鍵は <plugin>@<marketplace>、値は行の配列。project の行だけ projectPath を持つ"""
    row = {"scope": scope, "installPath": str(path), "version": pathlib.Path(path).name, "installedAt": "2026-09-17T01:34:17.746Z",
           "lastUpdated": "2026-10-18T23:00:06.887Z", "gitCommitSha": "03172b6be3a93fd207ed73180cfab6e67d8b0810"}
    return {**row, "projectPath": str(project)} if project else row


def _ledger(tmp_path, plugins):
    f = tmp_path / "plugins" / intake.LEDGER
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8")
    return tmp_path / "plugins"


def _orphan(root):
    (root / ".orphaned_at").write_text("1792062845530", encoding="utf-8")   # 実物の中身（作った時刻のミリ秒）
    return root


def test_installed_roots_reads_install_path_not_the_largest_folder_name(tmp_path):
    """版はフォルダの名前の大小で選ばない——commit の名前のフォルダ（字で比べると版の番号より上）と、.orphaned_at の付いた外れた版を拾わない"""
    cur, _sha, _gone = _cached(tmp_path, "0.36.0"), _cached(tmp_path, "ea10b213686c"), _orphan(_cached(tmp_path, "0.99.0"))
    assert intake.version_key("ea10b213686c") > intake.version_key("0.99.0") > intake.version_key("0.36.0")   # 名前で選ぶと外れる
    plugins = _ledger(tmp_path, {"graphloops@mkt": [_ledger_row(cur)], "gates@mkt": [_ledger_row(tmp_path / "x")]})
    assert intake.installed_roots(plugins, "graphloops", cwd=tmp_path) == ({"mkt": cur.resolve()}, [])


def test_installed_roots_prefers_the_project_row_for_this_place_and_refuses_orphans(tmp_path):
    user, pinned = _cached(tmp_path, "0.49.0"), _cached(tmp_path, "0.45.0")
    here, other = tmp_path / "repo", tmp_path / "elsewhere"
    (here / "sub").mkdir(parents=True)
    (here / ".git").mkdir()
    plugins = _ledger(tmp_path, {"graphloops@mkt": [_ledger_row(user), _ledger_row(pinned, "project", here)]})
    assert intake.installed_roots(plugins, "graphloops", cwd=here / "sub")[0] == {"mkt": pinned.resolve()}   # git のルートで当てる
    assert intake.installed_roots(plugins, "graphloops", cwd=other)[0] == {"mkt": user.resolve()}             # ほかの場所の行は効かない
    _orphan(pinned)
    roots, why = intake.installed_roots(plugins, "graphloops", cwd=here)
    assert roots == {} and ".orphaned_at" in why[0]   # 効く行が外れた版なら、広い scope の行（user）に黙って倒さない
    plugins = _ledger(tmp_path, {"graphloops@mkt": [_ledger_row(user), {**_ledger_row(user), "scope": "managed"}]})
    roots, why = intake.installed_roots(plugins, "graphloops", cwd=other)
    assert roots == {"mkt": user.resolve()} and "知らない scope 'managed'" in why[0]
    (plugins / intake.LEDGER).unlink()
    assert intake.installed_roots(plugins, "graphloops") == ({}, [f"台帳 {plugins / intake.LEDGER} が無い"])


def test_find_plugin_path_takes_the_installed_version_and_stops_when_it_cannot_tell(tmp_path, monkeypatch):
    from engine import validator
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert validator.find_plugin_path("agents/x.md", "fakeplug") is None   # 入っていない
    cur, newer_name = _cached(tmp_path, "0.36.0", "fakeplug"), _cached(tmp_path, "ea10b213686c", "fakeplug")
    for r in (cur, newer_name):
        (r / "agents").mkdir()
        (r / "agents" / "x.md").write_text(r.name, encoding="utf-8")
    (newer_name / "agents" / "only-old.md").write_text("old", encoding="utf-8")
    with pytest.raises(SystemExit):   # キャッシュに在るのに台帳が無い——名前の大小で選ばずに止める
        validator.find_plugin_path("agents/x.md", "fakeplug")
    _ledger(tmp_path, {"fakeplug@mkt": [_ledger_row(cur)]})
    assert validator.find_plugin_path("agents/x.md", "fakeplug") == str((cur / "agents" / "x.md").resolve())
    assert validator.find_plugin_path("agents/only-old.md", "fakeplug") is None   # 入っている版に無ければ、ほかの版の物を読まない
    _orphan(cur)
    with pytest.raises(SystemExit):
        validator.find_plugin_path("agents/x.md", "fakeplug")
    _orphan(newer_name)
    (tmp_path / "plugins" / intake.LEDGER).unlink()
    assert validator.find_plugin_path("agents/x.md", "fakeplug") is None   # 外れた版だけ残っている＝入っていない


def test_install_drift_compares_the_running_root_with_the_ledger(tmp_path):
    old, new = _cached(tmp_path, "0.9.0"), _cached(tmp_path, "0.10.0")
    _ledger(tmp_path, {"graphloops@mkt": [_ledger_row(new)]})
    assert intake.install_drift(old, cwd=tmp_path) == {"installed": str(new.resolve()), "version": "0.10.0", "why": ""}
    assert intake.install_drift(new, cwd=tmp_path) is None
    assert intake.install_drift(PLUGIN) is None           # checkout から走る回は比べない
    _orphan(new)
    got = intake.install_drift(new, cwd=tmp_path)          # 動いている版が外れた版になった
    assert got["installed"] is None and ".orphaned_at" in got["why"]


def test_init_notices_name_a_missing_declaration_and_a_newer_version(tmp_path, monkeypatch):
    g = {"nodes": {"p4.ci": {"engine_run": {"builtin": "x"}}, "p0.base": {}}}
    monkeypatch.setattr(intake, "install_drift", lambda: None)
    monkeypatch.setattr(intake, "claude_drift", lambda: None)
    monkeypatch.setattr(intake, "backlog", lambda: None)
    root = str(tmp_path)
    assert any(".review-checks.json が無い" in n for n in commands.init_notices(g, root))
    (tmp_path / ".review-checks.json").write_text("{壊れた", encoding="utf-8")
    assert any("読めない" in n for n in commands.init_notices(g, root))
    (tmp_path / ".review-checks.json").write_text(json.dumps({"suite": [{"name": "t", "argv": ["x"]}]}), encoding="utf-8")
    assert commands.init_notices(g, root) == []
    assert commands.init_notices({"nodes": {"p0.base": {}}}, root) == []   # 走らせるだけのノードを持たない graph には言わない
    monkeypatch.setattr(intake, "install_drift", lambda: {"installed": "/x/9.9.9", "version": "9.9.9", "why": ""})
    assert any("9.9.9（/x/9.9.9）が入っている" in n for n in commands.init_notices(g, root))
    monkeypatch.setattr(intake, "install_drift", lambda: {"installed": None, "version": "", "why": "台帳が無い"})
    assert any("確かめられない（台帳が無い）" in n for n in commands.init_notices(g, root))


def _claude_on_path(tmp_path, monkeypatch, version, code=0):
    """--version に version を返す代役の claude を PATH の先頭に置く（標準入力を読まない——読めば init が止まる）"""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    exe = bindir / "claude"
    exe.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\nexit {code}\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    return exe


@pytest.mark.skipif(os.name == "nt", reason="代役の claude を #! の台本で置く")
def test_claude_drift_compares_the_claude_on_path_with_the_pinned_version(tmp_path, monkeypatch):
    """入れた置き場から走る回は、PATH の claude の版を見本の控え（tests/py/cli/versions.json）と比べる——違えば init が知らせる
    （docs/standards/breakage-detection.md の決まり 3）"""
    root = _cached(tmp_path, "0.40.0")
    pin = root.joinpath(*intake.CLAUDE_PIN)
    pin.parent.mkdir(parents=True)
    pin.write_text(json.dumps({"help": {"claude": "2.1.303 (Claude Code)"}}), encoding="utf-8")
    exe = _claude_on_path(tmp_path, monkeypatch, "2.1.303 (Claude Code)")
    assert intake.claude_drift(root) is None
    assert intake.claude_drift(PLUGIN) is None                 # checkout から走る回は比べない（試験の出力を手元の claude の版で揺らさない）
    _claude_on_path(tmp_path, monkeypatch, "2.2.0 (Claude Code)")
    assert intake.claude_drift(root) == {"installed": "2.2.0 (Claude Code)", "exit": 0, "exe": str(exe),
                                         "pinned": "2.1.303 (Claude Code)"}
    _claude_on_path(tmp_path, monkeypatch, "2.1.303 (Claude Code)", code=1)
    got = intake.claude_drift(root)
    assert (got["installed"], got["exit"]) == (None, 1)   # 落ちた --version の出力は版として読まない
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert intake.claude_drift(root) is None                    # claude が無い回は起動の行が落ちて見える


def test_init_notices_name_a_claude_version_drift_and_the_live_check(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "install_drift", lambda: None)
    monkeypatch.setattr(intake, "backlog", lambda: None)
    monkeypatch.setattr(intake, "claude_drift", lambda: {"installed": "2.2.0 (Claude Code)", "exit": 0, "exe": "/x/claude",
                                                         "pinned": "2.1.303 (Claude Code)"})
    [n] = commands.init_notices({"nodes": {}}, str(tmp_path))
    assert all(w in n for w in ("2.2.0 (Claude Code)", "/x/claude", "2.1.303 (Claude Code)", intake.CLAUDE_CHECK, "intake --what"))


def test_init_reads_the_declaration_from_the_board_cwd_not_a_leftover_git_cwd(tmp_path, monkeypatch):
    """init の知らせは盤面の inputs.cwd の作業ツリーから宣言を読む——同じプロセスで前に置かれた util.GIT_CWD（別のリポジトリ）に依らない
    （cli と同じプロセスの口で知らせの数が割れない）"""
    from glharness import inproc
    from engine import util
    here, elsewhere = tmp_path / "here", tmp_path / "elsewhere"
    for r in (here, elsewhere):
        r.mkdir()
        subprocess.run(["git", "init", "-q", str(r)], check=True)
    (elsewhere / ".review-checks.json").write_text(json.dumps({"suite": [{"name": "t", "argv": ["x"]}]}), encoding="utf-8")
    monkeypatch.setattr(util, "GIT_CWD", str(elsewhere))
    r = inproc(["init", "--loop", "review-loop", "--request", "検査", "--dir", str(tmp_path / "st"), "--no-engine-runners",
                "--validator", str(REPO / "convergence-loops" / "scripts" / "review-record.py")], cwd=here)
    assert r.returncode == 0, r.stderr
    assert ".review-checks.json が無い" in r.stderr


def test_convergence_loops_dependency_floor_is_met_by_the_repo():
    """graphloops の依存の下限（version の >=x.y.z）が、同じリポジトリの convergence-loops の版以下——下限の書き損じで graphloops 自身を
    読み込みの時点で無効にしない（範囲の外なら Claude Code は依存する側を無効にする）"""
    from conftest import REPO
    dep = [d for d in json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["dependencies"]
           if d["name"] == "convergence-loops"]
    assert len(dep) == 1 and dep[0]["version"].startswith(">=")
    floor = intake.version_key(re.sub(r"^[<>=^~ ]+", "", dep[0]["version"]))
    cl = json.loads((REPO / "convergence-loops" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert cl["name"] == "convergence-loops" and floor <= intake.version_key(cl["version"])


def test_version_key_follows_semver_precedence():
    """SemVer 2.0.0 §11 の例の並び。プレリリースは同じ本体の正式版より下で、build（+ 以降）は見ない。プレリリースの無い名前の並びは
    数字の大小のまま（0.9 < 0.10）"""
    chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0",
             "1.0.1", "1.1.0", "2.0.0"]
    assert sorted(reversed(chain), key=intake.version_key) == chain
    assert intake.version_key("0.22.0") > intake.version_key("0.22.0-rc1")
    assert intake.version_key("1.0.0+build.5") == intake.version_key("1.0.0")
    assert sorted(["0.10.0", "0.9.0", "0.9.10"], key=intake.version_key) == ["0.9.0", "0.9.10", "0.10.0"]


def test_manual_row_has_no_key_and_export_hands_over_once(tmp_path):
    data = tmp_path / "data"
    loop("next", "--dir", str(tmp_path / "none"), env={"CLAUDE_PLUGIN_DATA": str(data), intake.DETAIL_ENV: "1"})
    r = loop("intake", "--what", "判定が同じ単位を 2 度挙げた", "--data-dir", str(data))
    assert r.returncode == 0
    auto, manual = rows(data)
    assert manual["kind"] == "manual" and manual["what"] == "判定が同じ単位を 2 度挙げた" and "key" not in manual and "stderr" in auto
    out = tmp_path / "out.jsonl"
    assert loop("intake", "--export", str(out), "--data-dir", str(data)).returncode == 0
    got = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert [g["kind"] for g in got] == ["auto", "manual"] and all("stderr" not in g for g in got)
    assert loop("intake", "--export", str(out), "--data-dir", str(data)).returncode == 0
    assert out.read_text(encoding="utf-8") == ""
    loop("intake", "--export", str(out), "--all", "--with-stderr", "--data-dir", str(data))
    assert "stderr" in json.loads(out.read_text(encoding="utf-8").splitlines()[0])


def test_send_without_destination_keeps_rows_local(tmp_path):
    data = tmp_path / "data"
    loop("intake", "--what", "x", "--data-dir", str(data))
    r = loop("intake", "--send", "--data-dir", str(data))
    assert r.returncode == 0 and "未設定" in r.stdout and intake.pending(data)[0]


def test_send_posts_structured_rows_and_hands_them_over(tmp_path):
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    data = tmp_path / "data"
    loop("next", "--dir", str(tmp_path / "none"), env={"CLAUDE_PLUGIN_DATA": str(data), intake.DETAIL_ENV: "1"})
    assert loop("intake", "--set-url", f"http://127.0.0.1:{srv.server_port}/", "--data-dir", str(data)).returncode == 0
    r = loop("intake", "--send", "--data-dir", str(data), env={"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})   # 手元の受けに proxy を挟まない
    srv.server_close()
    assert r.returncode == 0, r.stderr
    [body] = got
    assert "loop.py next exit=2" in body["text"] and [x["where"] for x in body["records"]] == ["loop.py next"]
    assert "stderr" not in body["records"][0]
    assert intake.pending(data)[0] == []


@pytest.mark.parametrize("row,kind,want", [
    ({"ok": False, "why": "前置ではない"}, None, "launch_refused"),
    ({"ok": False, "why": "x", "rejections": ["型に合わない"], "stderr": ""}, None, "launch_rejected"),
    ({"ok": False, "why": "宣言と一致しない"}, "engine_run", "launch_refused"),
    ({"ok": False, "why": "受け付けまで進めない", "runs": []}, "engine_run", "launch_engine_run_accept"),
])
def test_launch_rows_are_keyed_by_how_they_failed(row, kind, want):
    exc, func = launch_cause(row, kind)
    assert exc == want and func


@pytest.mark.parametrize("note", ["none", "keychain-miss(svc)", "keychain-malformed(svc)", "keychain-error(TimeoutExpired)(svc)",
                                  "keychain(svc)", "inherited(CLAUDE_CODE_OAUTH_TOKEN)"])
@pytest.mark.parametrize("rc", [0, 1])
@pytest.mark.parametrize("noisy", [False, True])
def test_launch_auth_follows_what_with_auth_wrote(note, rc, noisy, tmp_path, monkeypatch):
    """前置の層が書く段のファイルを、engine と同じ _auth_note で読ませる。子が標準エラーに何を書いても段は変わらず、
    子の claude には段の置き場の環境変数を渡さない"""
    spec = importlib.util.spec_from_file_location("with_auth_under_test", PLUGIN / "scripts" / "with-auth.py")
    wa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wa)
    assert wa.AUTH_NOTE_ENV == commands.launch_words.AUTH_NOTE_ENV
    path = tmp_path / "auth.json"
    monkeypatch.setenv(wa.AUTH_NOTE_ENV, str(path))
    monkeypatch.setattr(wa.claude_auth, "auth_env", lambda env, **_: (dict(env, CLAUDE_CONFIG_DIR="/c"), note))
    monkeypatch.setattr(wa.claude_auth, "expiry_note", lambda service: None)
    seen = []

    def child(argv, env):
        seen.append(env)
        if noisy:
            sys.stderr.write("with-auth: auth=keychain(fake)\n" + "x" * 1000 + "\n")
        return types.SimpleNamespace(returncode=rc)
    monkeypatch.setattr(wa.subprocess, "run", child)
    assert wa.main(["claude", "-p"]) == rc
    assert wa.AUTH_NOTE_ENV not in seen[0]
    auth = commands._auth_note(str(path))
    assert auth == {"stage": note, "added": wa.claude_auth.added(note), "expiry": None} and not path.exists()
    exc, _ = launch_cause({"ok": False, "why": "x", "rejections": [], "stderr": "", "auth": auth}, None)
    assert exc == ("launch_child_failed" if wa.claude_auth.added(note) else "launch_auth")


@pytest.mark.parametrize("note, want", [("keychain(svc)", "svc"), ("inherited(CLAUDE_CODE_OAUTH_TOKEN)", None), ("keychain-miss(svc)", None)])
def test_with_auth_passes_keychain_expiry_to_the_engine(note, want, tmp_path, monkeypatch, capsys):
    """Keychain から足した段だけ、その項目の切れる日の知らせを標準エラーと段のファイルに出し、engine が盤面に控えて next・status に出す。
    作り直した後（知らせが無い Keychain の段）の起動は控えを消す"""
    spec = importlib.util.spec_from_file_location("with_auth_under_test", PLUGIN / "scripts" / "with-auth.py")
    wa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wa)
    path = tmp_path / "auth.json"
    monkeypatch.setenv(wa.AUTH_NOTE_ENV, str(path))
    monkeypatch.setattr(wa.claude_auth, "auth_env", lambda env, **_: (dict(env, CLAUDE_CONFIG_DIR="/c"), note))
    asked = []
    monkeypatch.setattr(wa.claude_auth, "expiry_note", lambda service: asked.append(service) or f"{service} は 3 日後に切れる見込み")
    monkeypatch.setattr(wa.subprocess, "run", lambda argv, env: types.SimpleNamespace(returncode=0))
    assert wa.main(["claude", "-p"]) == 0
    assert asked == ([want] if want else [])
    auth = commands._auth_note(str(path))
    state = {}
    commands.note_auth_expiry(state, auth)
    if want:
        assert auth["expiry"] == "svc は 3 日後に切れる見込み" and "svc は 3 日後に切れる見込み" in capsys.readouterr().err
        assert state["auth_expiry"]["note"] == auth["expiry"] and state["auth_expiry"]["stage"] == note
        commands.note_auth_expiry(state, {**auth, "stage": "keychain(other)", "expiry": None})
        assert state["auth_expiry"]["note"] == auth["expiry"]   # 別の項目の起動では消さない
        commands.note_auth_expiry(state, {**auth, "expiry": None})
    assert "auth_expiry" not in state
    if not want:
        state["auth_expiry"] = {"stage": "keychain(svc)", "note": "x", "at": "t"}
        commands.note_auth_expiry(state, auth)   # Keychain でない段の回は、前の控えを消さない
        assert state["auth_expiry"]["note"] == "x"


@pytest.mark.parametrize("rejections", [[], ["拒否"]])
@pytest.mark.parametrize("stage, added, want", [("keychain(svc)", True, "launch_short_line"), ("keychain-miss(svc)", False, "launch_auth")])
def test_short_line_is_its_own_cause(rejections, stage, added, want):
    """最後の回が短い 1 行なら、拒否の後の続きの回でも short_line。認証を足せなかった段なら、まず認証を名指す"""
    exc, func = launch_cause({"ok": False, "why": "x", "rejections": rejections, "short_line": True,
                              "auth": {"stage": stage, "added": added, "expiry": None}}, None)
    assert (exc, func) == (want, "role_run.unwrap")


@pytest.mark.parametrize("body", [None, "", "{", "[]", '{"stage": "none"}', '{"stage": 1, "added": true}'])
def test_launch_auth_unread_when_the_note_is_missing_or_malformed(body, tmp_path):
    path = tmp_path / "auth.json"
    if body is not None:
        path.write_text(body, encoding="utf-8")
    auth = commands._auth_note(str(path))
    assert auth is None and not path.exists()
    exc, _ = launch_cause({"ok": False, "why": "x", "rejections": [], "stderr": "with-auth: auth=keychain(svc)", "auth": auth}, None)
    assert exc == "launch_auth_unread"


def test_failed_swallows_errors_while_building_its_row(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))

    def boom(tb):
        raise AttributeError("is_relative_to")
    monkeypatch.setattr(intake, "raised_in", boom)
    assert intake.failed(["next"], 2, SystemExit(2)) is None


def test_launch_rows_get_their_cause_and_errors_are_swallowed(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    got = [{"id": "p1.x", "ok": False, "why": "前置ではない"}, {"id": "p1.y", "ok": True}]
    commands.mark_launch_failures(got, {}, None)
    assert got[0]["cause"] == "launch_refused" and "cause" not in got[1] and len(rows(tmp_path / "data")) == 1

    def boom(r, kind):
        raise KeyError("rejections")
    monkeypatch.setattr(commands, "launch_cause", boom)
    got = [{"id": "p1.x", "ok": False}, {"id": "p1.z", "ok": False}]
    commands.mark_launch_failures(got, {}, None)
    assert [("cause" in g) for g in got] == [False, False]
    assert [(x["exc"], x["func"]) for x in rows(tmp_path / "data")[1:]] == [("KeyError", "commands.launch_cause")] * 2

    monkeypatch.setattr(intake, "record", lambda *a, **k: 1 / 0)
    assert commands.mark_launch_failures([{"id": "p1.x", "ok": False}], {}, None) is None


def test_set_url_rejects_non_http(tmp_path):
    r = loop("intake", "--set-url", "file:///etc/passwd", "--data-dir", str(tmp_path / "data"))
    assert r.returncode == 1 and intake.url_of(tmp_path / "data") is None


def test_key_reads_a_missing_part_as_empty():
    """鍵の部品が無い（None）のと空の文字列は同じ鍵——フィールドの有無の違いで同じ問題を割らない"""
    assert intake.key_of({"where": "loop.py next", "exc": None}) == intake.key_of({"where": "loop.py next", "exc": ""})


def test_quiet_swallows_errors_but_lets_keyboard_interrupt_through():
    """記録器の握りは呼び元を止めない（例外は None で返す）が、利用者の中断（KeyboardInterrupt）だけは外へ通す"""
    def boom(e):
        raise e
    assert intake.quiet(boom)(RuntimeError("検査用")) is None
    assert intake.quiet(boom)(SystemExit(3)) is None
    with pytest.raises(KeyboardInterrupt):
        intake.quiet(boom)(KeyboardInterrupt())


def test_unhanded_rows_are_named_on_init_and_status_until_seen(tmp_path):
    """記録を書くだけでは誰も読まない——まだ手渡していない行の数・置き場・手渡す手を init と status が毎回出し、--seen で止まる"""
    data, env = tmp_path / "data", {"CLAUDE_PLUGIN_DATA": str(tmp_path / "data")}
    for _ in range(2):
        loop("next", "--dir", str(tmp_path / "none"), env=env)
    loop("intake", "--what", "判定が揺れた", "--data-dir", str(data))
    board = tmp_path / "st"
    r = loop("init", "--loop", "review-loop", "--request", "検査", "--dir", str(board), "--no-engine-runners",
             "--validator", str(REPO / "convergence-loops" / "scripts" / "review-record.py"), env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    [note] = [n for n in json.loads(r.stdout)["notes"] if "失敗の記録" in n]
    assert "3 件" in note and str(data / intake.LOG) in note and "loop.py next SystemExit ×2" in note and "手で残した 1 行 ×1" in note
    assert "--export" in note and "--seen" in note and note in r.stderr
    st = json.loads(loop("status", "--dir", str(board), env=env).stdout)
    assert st["intake"] == note
    r = loop("intake", "--seen", "--data-dir", str(data))
    assert r.returncode == 0 and "3 件を手渡し済みにした" in r.stdout
    assert "intake" not in json.loads(loop("status", "--dir", str(board), env=env).stdout)
    assert len(rows(data)) == 3   # 既読にしても行は消さない（--export --all で読める）
    assert "intake" not in json.loads(loop("status", "--dir", str(board)).stdout)   # 置き場の決まらない回（checkout から直に走る）は出さない


def test_log_is_capped_and_rows_dropped_before_handing_over_are_named(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(intake, "CAP", 3)
    for i in range(5):
        intake.record("manual", "loop.py intake", what=f"w{i}", given_dir=str(data))
    assert [r["what"] for r in rows(data)] == ["w2", "w3", "w4"]
    b = intake.backlog(str(data))
    assert b["pending"] == 3 and b["lost"] == 2
    _, total = intake.pending(data)
    intake.handed(data, total)
    assert intake.backlog(str(data)) is None
    intake.record("manual", "loop.py intake", what="w5", given_dir=str(data))   # 手渡した後に切っても、手渡した所はずれない
    assert [r["what"] for r in intake.pending(data)[0]] == ["w5"] and intake.backlog(str(data))["lost"] == 0


def test_old_cursor_and_broken_lines_still_count(tmp_path):
    """前の版の印（数 1 つ）を読み、壊れた行は読めない印の行として数える——飛ばすと印がずれ、落とすと書き出しも知らせも止まる"""
    data = tmp_path / "data"
    data.mkdir()
    (data / intake.LOG).write_text('{"kind": "manual", "what": "a"}\n{壊れた\n{"kind": "manual", "what": "b"}\n', encoding="utf-8")
    (data / intake.CURSOR).write_text("1", encoding="utf-8")
    got, total = intake.pending(data)
    assert total == 3 and [r["kind"] for r in got] == ["unreadable", "manual"] and got[0]["line"] == "{壊れた"
    assert intake.backlog(str(data))["pending"] == 2


def test_notice_material_failures_are_named_on_stderr(monkeypatch, capsys):
    """知らせの材料が落ちても止めないが、黙らない——関数の名前と例外の型を標準エラーに 1 行出す"""
    def boom(*a, **k):
        raise RuntimeError("検査用")
    monkeypatch.setattr(intake, "data_dir", boom)
    monkeypatch.setattr(intake, "_installed", boom)
    assert intake.backlog() is None and intake.install_drift() is None
    err = capsys.readouterr().err
    assert "intake.backlog が RuntimeError" in err and "intake.install_drift が RuntimeError" in err


def test_pending_reads_rows_and_cursor_under_the_lock(tmp_path, monkeypatch):
    """行と印は足す・切る・手渡すと同じ錠の中で読む——間に切られると、通し番号の終わりがずれて見ていない行を手渡し済みにする"""
    from engine import filelock
    data = tmp_path / "data"
    intake.record("manual", "loop.py intake", what="w", given_dir=str(data))
    held, real = [], intake._rows

    def spy(d):
        h = filelock.try_hold(d / intake.LOCK)   # 錠が持たれていれば取れない
        held.append(h is None)
        filelock.release(h)
        return real(d)
    monkeypatch.setattr(intake, "_rows", spy)
    intake.pending(data)
    intake.backlog(str(data))   # 錠を入れ子にしない（入れ子は自分を待って止まる）
    assert held == [True, True]


def test_seen_counts_only_what_it_newly_hands_over_even_with_all(tmp_path):
    data = tmp_path / "data"
    for w in ("a", "b"):
        intake.record("manual", "loop.py intake", what=w, given_dir=str(data))
    intake.handed(data, intake.pending(data)[1])
    intake.record("manual", "loop.py intake", what="c", given_dir=str(data))
    r = loop("intake", "--seen", "--all", "--data-dir", str(data))
    assert r.returncode == 0 and "1 件を手渡し済みにした" in r.stdout, r.stdout


def test_notice_quotes_the_data_dir_and_says_what_hands_over(monkeypatch):
    monkeypatch.setattr(intake, "backlog", lambda: {"dir": "/tmp/a b", "file": "/tmp/a b/intake.jsonl", "pending": 1, "oldest": None,
                                                    "lost": 0, "top": [("手で残した 1 行", 1)]})
    note = commands.intake_notice()
    assert "--data-dir '/tmp/a b' --seen" in note and "届け先が未設定の --send は進めない" in note


def test_project_row_of_the_main_clone_counts_in_its_linked_worktree(tmp_path, monkeypatch):
    """Claude Code は主の clone で入れた行の projectPath に主の clone を書く——linked worktree で回しても、その行が効く"""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    main, wt = tmp_path / "main", tmp_path / "wt"
    main.mkdir()
    subprocess.run([*g, "-C", str(main), "init", "-q"], check=True)
    subprocess.run([*g, "-C", str(main), "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run([*g, "-C", str(main), "worktree", "add", "-q", str(wt)], check=True, capture_output=True)
    (wt / "sub").mkdir()
    user, pinned = _cached(tmp_path, "0.49.0"), _cached(tmp_path, "0.45.0")
    plugins = _ledger(tmp_path, {"graphloops@mkt": [_ledger_row(user), _ledger_row(pinned, "project", main)]})
    assert intake.installed_roots(plugins, "graphloops", cwd=wt / "sub")[0] == {"mkt": pinned.resolve()}
    other = tmp_path / "other"
    other.mkdir()
    assert intake.installed_roots(plugins, "graphloops", cwd=other)[0] == {"mkt": user.resolve()}


def test_find_plugin_path_names_each_ledger_warning_once(tmp_path, monkeypatch, capsys):
    """find_plugin_path は役ごとに引かれる——同じ台帳の警告をプロセスで 1 度だけ出す"""
    from engine import validator
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(validator, "_WARNED", set())
    cur = _cached(tmp_path, "0.36.0", "fakeplug")
    (cur / "agents").mkdir()
    for n in ("a", "b"):
        (cur / "agents" / f"{n}.md").write_text(n, encoding="utf-8")
    _ledger(tmp_path, {"fakeplug@mkt": [_ledger_row(cur), {**_ledger_row(cur), "scope": "managed"}]})
    assert validator.find_plugin_path("agents/a.md", "fakeplug") and validator.find_plugin_path("agents/b.md", "fakeplug")
    assert capsys.readouterr().err.count("知らない scope 'managed'") == 1
