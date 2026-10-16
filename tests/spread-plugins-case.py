#!/usr/bin/env python3
"""scripts/spread-plugins.py（役「配布」の道具）を、claude・herdr・git を偽物の runner にして回す。

使い方: python3 tests/spread-plugins-case.py <場合>
- only-company-talks: /reload-plugins は部署と窓口の会話（company.role の在る場所）にだけ打ち、入力欄に字の在る会話と手元の
  設定で除いた作業場は飛ばす。入っている自分の marketplace のプラグインだけ更新する
- failure-is-nonzero: 1 つでも失敗したら 1 で終わる（works-dispatch が AI の部署に回す）
- local-accounts: 手元の設定の accounts（部署を起こさないアカウント）にも配り、works-dispatch の設定と同じ設定のフォルダは 1 回だけ
- broken-copy: 更新が 0 で終わっても、入った写しに .claude-plugin/plugin.json が無ければ失敗に数え、失敗の行を出力の終わりに並べ直す
- mend-clone: marketplace の clone の作業ツリーから消えたファイルが在れば、プラグインの更新の前に戻す
"""

import importlib.util
import io
import json
import os
import pathlib
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("spread_plugins", ROOT / "scripts" / "spread-plugins.py")
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)

RULE = "─" * 20
EMPTY = f"{RULE}\n❯ \n{RULE}\n"
TYPED = f"{RULE}\n❯ 打ちかけ\n{RULE}\n"
MARKET = sp.marketplace_name()


def plugin_dir(whole=True):
    d = pathlib.Path(tempfile.mkdtemp())
    if whole:
        (d / ".claude-plugin").mkdir()
        (d / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    return str(d)


def world(fail=(), installed=None, gone=""):
    """(runner, 打った命令の並び)。installed は入った写しの場所（省けば plugin.json の在る場所）、gone は clone から消えたファイル。"""
    calls = []
    installed = installed or plugin_dir()
    panes = [{"pane_id": "a:1", "workspace_id": "a", "agent": "claude", "cwd": "/dept"},
             {"pane_id": "b:1", "workspace_id": "b", "agent": "claude", "cwd": "/mine"},
             {"pane_id": "c:1", "workspace_id": "c", "agent": "claude", "cwd": "/typed"},
             {"pane_id": "d:1", "workspace_id": "d", "agent": "claude", "cwd": "/skipped"},
             {"pane_id": "e:1", "workspace_id": "e", "agent": None, "cwd": "/dept"}]
    labels = {"a": "割り振り", "b": "作業の会話", "c": "点検", "d": "plugins1", "e": "シェル"}

    def runner(argv, env=None):
        calls.append((argv, (env or {}).get("CLAUDE_CONFIG_DIR")))
        if argv[:3] == ["claude", "plugin", "list"]:
            return 0, json.dumps([{"id": f"a@{MARKET}", "scope": "user", "installPath": installed},
                                  {"id": "x@other", "scope": "user"}, {"id": f"p@{MARKET}", "scope": "project"}])
        if argv[:4] == ["claude", "plugin", "marketplace", "list"]:
            return 0, json.dumps([{"name": "other", "installLocation": "/m/other"},
                                  {"name": MARKET, "installLocation": "/m/mine"}])
        if argv[:1] == ["claude"]:
            return (1, "network") if " ".join(argv) in fail else (0, "")
        if argv[:3] == ["herdr", "workspace", "list"]:
            return 0, json.dumps({"result": {"workspaces": [{"workspace_id": k, "label": v} for k, v in labels.items()]}})
        if argv[:3] == ["herdr", "pane", "list"]:
            return 0, json.dumps({"result": {"panes": panes}})
        if argv[:3] == ["herdr", "pane", "read"]:
            return 0, TYPED if argv[3] == "c:1" else EMPTY
        if argv[:3] == ["herdr", "agent", "prompt"]:
            return 0, ""
        if argv[:4] == ["git", "-C", "/m/mine", "ls-files"]:
            return 0, gone
        if argv[:4] == ["git", "-C", "/m/mine", "checkout"]:
            return 0, ""
        if argv[:1] == ["git"]:
            return (0, "作業\n") if argv[2] in ("/dept", "/typed", "/skipped") else (1, "")
        raise AssertionError(argv)
    return runner, calls


def run(runner, value, local='skip = ["plugins1"]\n'):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "dispatch.toml").write_text('accounts = [{ name = "main", command = "claude" },'
                                     ' { name = "p1", command = "claude-p1", config_dir = "/c/p1" }]\n', encoding="utf-8")
    (d / "spread.toml").write_text(local, encoding="utf-8")
    out = io.StringIO()
    old = sys.stdout
    sys.stdout = out
    try:
        rc = sp.main(io.StringIO(json.dumps(value)), runner, {"WORKS_DISPATCH_CONFIG": str(d / "dispatch.toml")},
                     str(d / "spread.toml"))
    finally:
        sys.stdout = old
    return rc, out.getvalue()


def only_company_talks():
    runner, calls = world()
    rc, out = run(runner, {})
    assert rc == 0, out
    prompts = [a[3] for a, _ in calls if a[:3] == ["herdr", "agent", "prompt"]]
    assert prompts == ["a:1"], prompts   # 部署だけ（作業の会話・打ちかけ・手元の除外・会話の居ないペインは飛ばす）
    updates = [(a[3], env) for a, env in calls if a[:3] == ["claude", "plugin", "update"]]
    assert updates == [(f"a@{MARKET}", None), (f"a@{MARKET}", "/c/p1")], updates
    assert "点検（c:1）: 入力欄に字が在るので飛ばす" in out and "plugins1（d:1）: 手元の設定で除く" in out, out
    print("ONLY_COMPANY_TALKS_OK")


def failure_is_nonzero():
    runner, _ = world(fail={f"claude plugin update a@{MARKET}"})
    rc, out = run(runner, {})
    assert rc == 1 and "失敗 2 件" in out, (rc, out)
    print("FAILURE_IS_NONZERO_OK")


def local_accounts():
    runner, calls = world()
    rc, out = run(runner, {}, 'skip = ["plugins1"]\n'
                  'accounts = [{ name = "ollama", config_dir = "/c/ollama" }, { name = "p1", config_dir = "/c/p1/" }]\n')
    assert rc == 0, out
    updates = [(a[3], env) for a, env in calls if a[:3] == ["claude", "plugin", "update"]]
    assert updates == [(f"a@{MARKET}", None), (f"a@{MARKET}", "/c/p1"), (f"a@{MARKET}", "/c/ollama")], updates
    print("LOCAL_ACCOUNTS_OK")


def broken_copy():
    runner, _ = world(installed=plugin_dir(whole=False))
    rc, out = run(runner, {})
    assert rc == 1, (rc, out)
    tail = out.strip().splitlines()
    assert tail[-3] == "失敗 2 件:" and all(x.startswith("- ") and "plugin.json が無い" in x for x in tail[-2:]), out
    assert f"claude plugin update a@{MARKET} 済" not in out, out
    print("BROKEN_COPY_OK")


def mend_clone():
    runner, calls = world(gone="attention/README.md\ntiers/README.md\n")
    rc, out = run(runner, {})
    assert rc == 0, out
    seq = [a for a, _ in calls if a[:1] == ["git"] and a[2] == "/m/mine" or a[:3] == ["claude", "plugin", "update"]]
    assert seq[:3] == [["git", "-C", "/m/mine", "ls-files", "--deleted"], ["git", "-C", "/m/mine", "checkout", "--", "."],
                       ["claude", "plugin", "update", f"a@{MARKET}"]], seq   # 戻してから更新する
    assert "main: marketplace の clone の作業ツリーに 2 個のファイルが無いので戻す 済" in out, out
    runner, calls = world()
    run(runner, {})
    assert not [a for a, _ in calls if a[:4] == ["git", "-C", "/m/mine", "checkout"]], calls   # 欠けが無ければ触らない
    runner, calls = world(gone="a\n")
    rc, out = run(runner, {"dry_run": True})
    assert rc == 0 and "無いので戻す（空打ち）" in out and not [a for a, _ in calls if "checkout" in a], out
    print("MEND_CLONE_OK")


if __name__ == "__main__":
    {"only-company-talks": only_company_talks, "failure-is-nonzero": failure_is_nonzero,
     "local-accounts": local_accounts, "broken-copy": broken_copy, "mend-clone": mend_clone}[sys.argv[1]]()
