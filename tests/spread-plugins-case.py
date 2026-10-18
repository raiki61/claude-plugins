#!/usr/bin/env python3
"""scripts/spread-plugins.py（役「配布」の道具）を、claude・herdr・git を偽物の runner にして回す。

使い方: python3 tests/spread-plugins-case.py <場合>
- only-company-talks: /reload-plugins は部署と窓口の会話（company.role の在る場所）にだけ打ち、入力欄に字の在る会話と手元の
  設定で除いた作業場は飛ばす。入っている自分の marketplace のプラグインだけ更新する
- failure-is-nonzero: 1 つでも失敗したら 1 で終わる（works-dispatch が AI の部署に回す）。marketplace の更新は落ちたら 1 回だけ打ち直し、
  それでも落ちても入った版が全部本流とそろえば失敗に数えない
- local-accounts: 手元の設定の accounts（部署を起こさないアカウント）にも配り、works-dispatch の設定と同じ設定のフォルダは 1 回だけ
- broken-copy: 更新が 0 で終わっても、入った写しに .claude-plugin/plugin.json が無いか、版が本流（origin/main）とそろわなければ
  失敗に数え、失敗の行を出力の終わりに並べ直す。本流の版を読めなくても失敗に数える。本流は全アカウントに配った後に読み、
  版のずれたアカウントだけ 1 回配り直して照らし直す（配る間に本流が進んだとき）
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


def world(fail=(), installed=None, gone="", version="1.0.0", main="1.0.0", flaky=()):
    """(runner, 打った命令の並び)。flaky は最初の 1 回だけ落ちる命令。installed は入った写しの場所（省けば plugin.json の在る場所）、gone は clone から消えたファイル。
    version は入った版（関数なら、その設定のフォルダで打った plugin update の数から版を返す）、main は本流（origin/main）の
    plugin.json の版（None なら本流を読めない）。"""
    calls = []
    installed = installed or plugin_dir()
    panes = [{"pane_id": "a:1", "workspace_id": "a", "agent": "claude", "agent_status": "idle", "cwd": "/dept"},
             {"pane_id": "b:1", "workspace_id": "b", "agent": "claude", "agent_status": "idle", "cwd": "/mine"},
             {"pane_id": "c:1", "workspace_id": "c", "agent": "claude", "agent_status": "done", "cwd": "/typed"},
             {"pane_id": "d:1", "workspace_id": "d", "agent": "claude", "agent_status": "idle", "cwd": "/skipped"},
             {"pane_id": "e:1", "workspace_id": "e", "agent": None, "cwd": "/dept"},
             {"pane_id": "f:1", "workspace_id": "f", "agent": "claude", "agent_status": "working", "cwd": "/busy"}]
    labels = {"a": "割り振り", "b": "作業の会話", "c": "点検", "d": "plugins1", "e": "シェル", "f": "説明書"}

    def runner(argv, env=None):
        calls.append((argv, (env or {}).get("CLAUDE_CONFIG_DIR")))
        if argv[:3] == ["claude", "plugin", "list"]:
            v = version(sum(1 for a, e in calls if a[:3] == ["claude", "plugin", "update"] and e == (env or {}).get(
                "CLAUDE_CONFIG_DIR"))) if callable(version) else version
            return 0, json.dumps([{"id": f"a@{MARKET}", "scope": "user", "installPath": installed, "version": v},
                                  {"id": "x@other", "scope": "user"}, {"id": f"p@{MARKET}", "scope": "project"}])
        if argv[:4] == ["claude", "plugin", "marketplace", "list"]:
            return 0, json.dumps([{"name": "other", "installLocation": "/m/other"},
                                  {"name": MARKET, "installLocation": "/m/mine"}])
        if argv[:1] == ["claude"]:
            line = " ".join(argv)
            first = line in flaky and sum(1 for a, _ in calls if " ".join(a) == line) == 1
            return (1, "network") if line in fail or first else (0, "")
        if argv[:3] == ["herdr", "workspace", "list"]:
            return 0, json.dumps({"result": {"workspaces": [{"workspace_id": k, "label": v} for k, v in labels.items()]}})
        if argv[:3] == ["herdr", "pane", "list"]:
            return 0, json.dumps({"result": {"panes": panes}})
        if argv[:3] == ["herdr", "pane", "read"]:
            return 0, TYPED if argv[3] == "c:1" else EMPTY
        if argv[:3] == ["herdr", "agent", "prompt"]:
            return 0, ""
        if argv[:2] == ["git", "-C"] and argv[2] == str(sp.ROOT) and argv[3] == "fetch":
            return 0, ""
        if argv[:2] == ["git", "-C"] and argv[2] == str(sp.ROOT) and argv[3] == "show":
            if main is None:
                return 128, "fatal: invalid object name 'origin/main'"
            if argv[4] == "origin/main:.claude-plugin/marketplace.json":
                return 0, json.dumps({"plugins": [{"name": "a", "source": "./a"}, {"name": "gone", "source": "./gone"}]})
            if argv[4] in ("origin/main:a/.claude-plugin/plugin.json", "origin/main:gone/.claude-plugin/plugin.json"):
                return 0, json.dumps({"version": main})
            raise AssertionError(argv)
        if argv[:4] == ["git", "-C", "/m/mine", "ls-files"]:
            return 0, gone
        if argv[:4] == ["git", "-C", "/m/mine", "checkout"]:
            return 0, ""
        if argv[:1] == ["git"]:
            return (0, "作業\n") if argv[2] in ("/dept", "/typed", "/skipped", "/busy") else (1, "")
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
    assert prompts == ["a:1"], prompts   # 手の空いた部署だけ（作業の会話・打ちかけ・手元の除外・会話の居ないペイン・番の途中は飛ばす）
    updates = [(a[3], env) for a, env in calls if a[:3] == ["claude", "plugin", "update"]]
    assert updates == [(f"a@{MARKET}", None), (f"a@{MARKET}", "/c/p1")], updates
    assert "点検（c:1）: 入力フィールドに字が在るので飛ばす" in out and "plugins1（d:1）: 手元の設定で除く" in out, out
    assert "説明書（f:1）: ターンの途中なので飛ばす（ターンの終わりに替わる）" in out, out
    assert not [a for a, _ in calls if a[:4] == ["herdr", "pane", "read", "f:1"]], calls   # 番の途中の画面は読みもしない
    print("ONLY_COMPANY_TALKS_OK")


def failure_is_nonzero():
    runner, _ = world(fail={f"claude plugin update a@{MARKET}"})
    rc, out = run(runner, {})
    assert rc == 1 and "失敗 2 件" in out, (rc, out)
    runner, calls = world(fail={f"claude plugin marketplace update {MARKET}"}, version="0.9.0")
    rc, out = run(runner, {})
    tries = [a for a, _ in calls if a[:4] == ["claude", "plugin", "marketplace", "update"]]
    assert rc == 1 and "- main: claude plugin marketplace update" in out and len(tries) == 8, (rc, out, tries)   # 打ち直しても落ち、版も古ければ失敗（配り直しを含めアカウントごとに 2 回まで）
    runner, calls = world(fail={f"claude plugin marketplace update {MARKET}"})   # 別の会話が先に取り直して版はそろった
    rc, out = run(runner, {})
    tries = [a for a, _ in calls if a[:4] == ["claude", "plugin", "marketplace", "update"]]
    assert rc == 0 and len(tries) == 4 and "main: marketplace の更新は落ちたが、入った版は main とそろったので失敗に数えない" in out, (rc, out, tries)
    runner, _ = world(fail={f"claude plugin marketplace update {MARKET}"}, main=None)   # 本流を読めなければそろったと言えない
    rc, out = run(runner, {})
    assert rc == 1 and "- main: claude plugin marketplace update" in out, (rc, out)
    runner, calls = world(flaky={f"claude plugin marketplace update {MARKET}"})   # 別の会話の取り直しとぶつかった
    rc, out = run(runner, {})
    tries = [a for a, _ in calls if a[:4] == ["claude", "plugin", "marketplace", "update"]]
    assert rc == 0 and len(tries) == 3, (rc, out, tries)   # 落ちた 1 回だけ打ち直す
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
    runner, _ = world(version="1.0.0", main="1.1.0")   # 古い版が入った（marketplace の clone が古いままなど）
    rc, out = run(runner, {})
    tail = out.strip().splitlines()
    assert rc == 1 and tail[-3] == "失敗 2 件:", (rc, out)
    assert all("版が main とそろわない: 入った版 1.0.0・main 1.1.0" in x for x in tail[-2:]), out
    runner, calls = world(version=lambda n: "1.1.0" if n >= 2 else "1.0.0", main="1.1.0")   # 配る間に本流が進んだ
    rc, out = run(runner, {})
    updates = [env for a, env in calls if a[:3] == ["claude", "plugin", "update"]]
    assert rc == 0 and updates == [None, "/c/p1", None, "/c/p1"], (rc, out, updates)   # ずれたアカウントだけ 1 回配り直す
    assert out.count(f"claude plugin update a@{MARKET} 済（1.1.0）") == 2, out
    runner, calls = world(version=lambda n: "1.1.0" if n >= 1 else "1.0.0", main="1.1.0")
    rc, out = run(runner, {})
    assert rc == 0 and len([a for a, _ in calls if a[:3] == ["claude", "plugin", "update"]]) == 2, out   # そろえば配り直さない
    runner, _ = world()
    rc, out = run(runner, {})
    assert rc == 0 and out.count(f"claude plugin update a@{MARKET} 済（1.0.0）") == 2, out
    runner, calls = world()   # 本流は全アカウントに配った後に読む（配る間に本流へ入った版を、入った版が新しいのにそろわないと数えない）
    run(runner, {})
    seq = [i for i, (a, _) in enumerate(calls) if a[:2] == ["claude", "plugin"] and a[2] in ("update", "marketplace")
           and "list" not in a]
    reads = [i for i, (a, _) in enumerate(calls) if a[:1] == ["git"] and a[2] == str(sp.ROOT)]
    assert reads and min(reads) > max(seq), calls
    runner, calls = world(main=None)   # 本流の版を読めなければ、照らせないので失敗に数える
    rc, out = run(runner, {})
    assert rc == 1 and "main の版を読めない" in out.strip().splitlines()[-1], out
    runner, calls = world(main=None)
    rc, out = run(runner, {"dry_run": True})   # 空打ちでは本流を読みに行かない
    assert rc == 0 and not [a for a, _ in calls if a[:1] == ["git"] and a[2] == str(sp.ROOT)], out
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
