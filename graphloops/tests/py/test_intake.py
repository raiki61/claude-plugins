"""踏んだ事実を利用者の環境に残す記録器（engine/intake.py）と、その口（loop.py の最上段・loop.py intake）。
launch の ok でない行は simulate.py の test_engine_launch、報告の頭の 1 行は simulate_review.py の test_converges が端から端まで見る。"""
import http.server
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import threading
import types

import pytest

from conftest import PLUGIN
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
    assert row["exc"] == "SystemExit" and row["func"] == "board.__init__"   # die の呼び元（util.py の小道具は飛ばす）
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
def test_launch_auth_follows_what_with_auth_wrote(note, rc, noisy, monkeypatch, capsys):
    """前置の層が実際に書く標準エラーを、role_run と同じく末尾 600 字に切って読ませる（頭が切れても子の落ちた行で読む）"""
    spec = importlib.util.spec_from_file_location("with_auth_under_test", PLUGIN / "scripts" / "with-auth.py")
    wa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wa)
    monkeypatch.setattr(wa.claude_auth, "auth_env", lambda env, **_: (dict(env, CLAUDE_CONFIG_DIR="/c"), note))

    def child(argv, env):
        if noisy:
            sys.stderr.write("x" * 1000 + "\n")
        return types.SimpleNamespace(returncode=rc)
    monkeypatch.setattr(wa.subprocess, "run", child)
    capsys.readouterr()
    assert wa.main(["claude", "-p"]) == rc
    err = capsys.readouterr().err.strip()[-600:]
    exc, _ = launch_cause({"ok": False, "why": "x", "rejections": [], "stderr": err}, None)
    if noisy and rc == 0:
        assert exc == "launch_auth_unread"
    else:
        assert exc == ("launch_child_failed" if wa.claude_auth.added(note) else "launch_auth")


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
    """鍵の部品が無い（None）のと空の文字列は同じ鍵——欄の有無の違いで同じ問題を割らない"""
    assert intake.key_of({"where": "loop.py next", "exc": None}) == intake.key_of({"where": "loop.py next", "exc": ""})


def test_quiet_swallows_errors_but_lets_keyboard_interrupt_through():
    """記録器の握りは呼び元を止めない（例外は None で返す）が、利用者の中断（KeyboardInterrupt）だけは外へ通す"""
    def boom(e):
        raise e
    assert intake.quiet(boom)(RuntimeError("検査用")) is None
    assert intake.quiet(boom)(SystemExit(3)) is None
    with pytest.raises(KeyboardInterrupt):
        intake.quiet(boom)(KeyboardInterrupt())
