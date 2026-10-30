#!/usr/bin/env python3
"""scripts/spread-plugins.py（役「配布」のツール）を、claude・herdr・git を偽物の runner にして回す。

使い方: python3 tests/spread-plugins-case.py <場合>
- only-company-talks: /reload-plugins は部署と窓口の会話（company.role の在る場所）にだけ打ち、入力フィールドに字の在る会話と手元の
  設定で除いた作業場は飛ばす（薄字の候補だけの入力フィールドは空と見て打つ）。入っている自分の marketplace のプラグインだけ更新する
- bad-config: 設定の accounts と skip に形の違う物が混ざれば、黙って飛ばさずに 2 で止める
- failure-is-nonzero: 1 つでも失敗したら 1 で終わる（works-dispatch が AI の部署に回す）。marketplace の更新は落ちたら 1 回だけ打ち直し、
  それでも落ちても入った版が全部メインブランチとそろえば失敗に数えない。プラグインの更新が落ちたアカウントは 1 回だけ配り直す
- local-accounts: 手元の設定の accounts（部署を起動しないアカウント）にも配り、works-dispatch の設定と同じ設定のフォルダは 1 回だけ
- broken-copy: 更新が 0 で終わっても、入った写しに .claude-plugin/plugin.json が無いか、版がメインブランチ（origin/main）とそろわなければ
  失敗に数え、失敗の行を出力の終わりに並べ直す。メインブランチの版を読めなくても失敗に数える。メインブランチは全アカウントに配った後に読み、
  版のずれたアカウントだけ 1 回配り直して照合し直す（配る間にメインブランチが進んだとき）
- mend-clone: marketplace の clone の作業ツリーから消えたファイルが在れば、プラグインの更新の前に戻す。clone の置き場が無いとき
  （別の会話が取り直している間）は失敗に数えずに進む
- real-shapes: claude plugin list --json と herdr pane list の実物から採った見本（tests/fixtures/spread-plugins/）で、使うフィールドが
  読めて配れる（Claude Code 2.1.303・herdr 0.9.3 で採った。版が上がって形が変わったら採り直す）
- install-missing: marketplace の clone に載っているのに入っていないプラグインは claude plugin install で入れ、入れた写しと版も
  照合する（手元の設定の no_install の物は入れない）。入っている物を読めないときは入れない。clone の一覧の形が違えば失敗に数える
- shape-changed: 外のツールの形が変わったら（id の名前・この marketplace の物が 0 件・claude の窓が 0 件・知らない状態）、何も
  更新せずに「配った」と出さず、失敗に数える
"""

import importlib.util
import io
import json
import os
import pathlib
import subprocess
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
SUGGESTED = f"{RULE}\n❯ \x1b[2m消していいよ\x1b[22m\n{RULE}\n"   # Claude Code が薄字で出す次の文の候補（打った字ではない）
MARKET = sp.marketplace_name()


def plugin_dir(whole=True):
    d = pathlib.Path(tempfile.mkdtemp())
    if whole:
        (d / ".claude-plugin").mkdir()
        (d / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    return str(d)


FIXTURES = ROOT / "tests" / "fixtures" / "spread-plugins"


def world(fail=(), installed=None, gone="", version="1.0.0", main="1.0.0", flaky=(), listed=None, panes=None, offered=None):
    """(runner, 打ったコマンドの並び)。flaky は最初の 1 回だけ落ちるコマンド。installed は入った写しの場所（省けば plugin.json の在る場所）、gone は clone から消えたファイル。
    version は入った版（関数なら、その設定のフォルダで打った plugin update の数から版を返す）、main はメインブランチ（origin/main）の
    plugin.json の版（None ならメインブランチを読めない）。listed は claude plugin list --json の並びを返す関数（入った場所と版を受ける）、
    panes は herdr pane list の窓の並び（どちらも省けば手で書いた見本）。offered は marketplace の clone に載っている
    プラグインの名前の並び（省けば、claude plugin list --json に user の scope で入っている物と同じ。入っていない物が無い）。"""
    calls = []
    installed = installed or plugin_dir()
    panes = panes if panes is not None else [{"pane_id": "a:1", "workspace_id": "a", "agent": "claude", "agent_status": "idle", "cwd": "/dept"},
             {"pane_id": "b:1", "workspace_id": "b", "agent": "claude", "agent_status": "idle", "cwd": "/mine"},
             {"pane_id": "c:1", "workspace_id": "c", "agent": "claude", "agent_status": "done", "cwd": "/typed"},
             {"pane_id": "d:1", "workspace_id": "d", "agent": "claude", "agent_status": "idle", "cwd": "/skipped"},
             {"pane_id": "e:1", "workspace_id": "e", "agent": None, "cwd": "/dept"},
             {"pane_id": "f:1", "workspace_id": "f", "agent": "claude", "agent_status": "working", "cwd": "/busy"},
             {"pane_id": "g:1", "workspace_id": "g", "agent": "claude", "agent_status": "idle", "cwd": "/suggested"}]
    labels = {"a": "割り振り", "b": "作業の会話", "c": "点検", "d": "plugins1", "e": "シェル", "f": "説明書", "g": "見渡し"}

    def runner(argv, env=None):
        calls.append((argv, (env or {}).get("CLAUDE_CONFIG_DIR")))
        if argv[:4] == ["git", "-C", "/m/mine", "show"]:
            assert argv[4] == "HEAD:.claude-plugin/marketplace.json", argv
            if offered is not None:
                return 0, json.dumps({"plugins": [{"name": n, "source": f"./{n}"} for n in offered]})
            code, out = runner(["claude", "plugin", "list", "--json"], env)
            calls.pop()
            return 0, json.dumps({"plugins": [{"name": p["id"].rsplit("@", 1)[0]} for p in json.loads(out)
                                              if p.get("id", "").endswith("@" + MARKET) and p.get("scope") == "user"]})
        if argv[:3] == ["claude", "plugin", "list"]:
            v = version(sum(1 for a, e in calls if a[:3] == ["claude", "plugin", "update"] and e == (env or {}).get(
                "CLAUDE_CONFIG_DIR"))) if callable(version) else version
            if listed:
                return 0, json.dumps(listed(installed, v))
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
            assert "--ansi" in argv, argv   # 薄字を見分けるには制御の字ごと読む
            return 0, {"c:1": TYPED, "g:1": SUGGESTED}.get(argv[3], EMPTY)
        if argv[:3] == ["herdr", "agent", "prompt"]:
            return 0, json.dumps({"result": {}})
        if argv[:2] == ["git", "-C"] and argv[2] == str(sp.ROOT) and argv[3] == "fetch":
            return 0, ""
        if argv[:2] == ["git", "-C"] and argv[2] == str(sp.ROOT) and argv[3] == "show":
            if main is None:
                return 128, "fatal: invalid object name 'origin/main'"
            if argv[4] == "origin/main:.claude-plugin/marketplace.json":
                return 0, json.dumps({"plugins": [{"name": "a", "source": "./a"}, {"name": "gone", "source": "./gone"},
                                                  {"name": "attention", "source": "./attention"}]})
            if argv[4] in ("origin/main:a/.claude-plugin/plugin.json", "origin/main:gone/.claude-plugin/plugin.json",
                           "origin/main:attention/.claude-plugin/plugin.json"):
                return 0, json.dumps({"version": main})
            raise AssertionError(argv)
        if argv[:4] == ["git", "-C", "/m/mine", "ls-files"]:
            return 0, gone
        if argv[:4] == ["git", "-C", "/m/mine", "checkout"]:
            return 0, ""
        if argv[:1] == ["git"]:
            return (0, "作業\n") if argv[2] in ("/dept", "/typed", "/skipped", "/busy", "/suggested") else (1, "")
        raise AssertionError(argv)
    return runner, calls


def herdr_runner(runner):
    """偽物の runner（(終了の値, 出力)）を、works-dispatch の herdr の口が呼ぶ形（argv → CompletedProcess）にする。"""
    def call(argv, env=None):
        code, out = runner(argv, env)
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr="")
    return call


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
                     str(d / "spread.toml"), herdr_runner(runner))
    finally:
        sys.stdout = old
    return rc, out.getvalue()


def only_company_talks():
    runner, calls = world()
    rc, out = run(runner, {})
    assert rc == 0, out
    prompts = [a[3] for a, _ in calls if a[:3] == ["herdr", "agent", "prompt"]]
    assert prompts == ["a:1", "g:1"], prompts   # 手の空いた部署だけ（作業の会話・打ちかけ・手元の除外・会話の居ないペイン・ターンの途中は飛ばす。薄字の候補は打ちかけでない）
    updates = [(a[3], env) for a, env in calls if a[:3] == ["claude", "plugin", "update"]]
    assert updates == [(f"a@{MARKET}", None), (f"a@{MARKET}", "/c/p1")], updates
    assert "点検（c:1）: 入力フィールドに字が在るので飛ばす" in out and "plugins1（d:1）: 手元の設定で除く" in out, out
    assert "説明書（f:1）: ターンの途中なので飛ばす（ターンの終わりに替わる）" in out, out
    assert not [a for a, _ in calls if a[:4] == ["herdr", "pane", "read", "f:1"]], calls   # ターンの途中の画面は読みもしない
    print("ONLY_COMPANY_TALKS_OK")


def bad_config():
    for local in ('skip = ["plugins1", 3]\n', 'accounts = ["p9"]\n', 'accounts = { name = "p9" }\n'):
        runner, calls = world()
        rc, out = run(runner, {}, local)
        assert rc == 2 and "止めた" in out and not calls, (local, rc, out)
    runner, calls = world()
    rc, out = run(runner, {}, 'accounts = [{ name = "p9", config_dir = 3 }]\n')
    assert rc == 2 and "止めた" in out and not calls, (rc, out)
    print("BAD_CONFIG_OK")


def failure_is_nonzero():
    runner, calls = world(fail={f"claude plugin update a@{MARKET}"})
    rc, out = run(runner, {})
    updates = [env for a, env in calls if a[:3] == ["claude", "plugin", "update"]]
    assert rc == 1 and "失敗 2 件" in out and updates == [None, "/c/p1", None, "/c/p1"], (rc, out, updates)   # 配り直してもなお落ちれば失敗
    runner, calls = world(flaky={f"claude plugin update a@{MARKET}"})   # 別の会話が clone を取り直している間に打った
    rc, out = run(runner, {})
    updates = [env for a, env in calls if a[:3] == ["claude", "plugin", "update"]]
    assert rc == 0 and updates == [None, "/c/p1", None], (rc, out, updates)   # 落ちたアカウントだけ 1 回配り直す
    runner, calls = world(flaky={f"claude plugin update a@{MARKET}"})
    def mid_clone(argv, env=None, runner=runner, calls=calls):   # 取り直しの途中で clone の欠けも戻せなかった
        first = not [a for a, _ in calls if a[:4] == argv[:4]]
        if argv[:4] == ["git", "-C", "/m/mine", "ls-files"] and first:
            calls.append((argv, None))
            return 0, "a/.claude-plugin/plugin.json\n"
        if argv[:4] == ["git", "-C", "/m/mine", "checkout"] and first:
            calls.append((argv, None))
            return 1, "fatal: index.lock"
        return runner(argv, env)
    rc, out = run(mid_clone, {})
    assert rc == 0 and [a for a, _ in calls if a[:4] == ["git", "-C", "/m/mine", "checkout"]], (rc, out)   # 配り直して通れば、1 回目の clone の欠けの戻し損ねも数えない
    runner, calls = world(fail={f"claude plugin marketplace update {MARKET}"}, version="0.9.0")
    rc, out = run(runner, {})
    tries = [a for a, _ in calls if a[:4] == ["claude", "plugin", "marketplace", "update"]]
    assert rc == 1 and "- main: claude plugin marketplace update" in out and len(tries) == 8, (rc, out, tries)   # 打ち直しても落ち、版も古ければ失敗（配り直しを含めアカウントごとに 2 回まで）
    runner, calls = world(fail={f"claude plugin marketplace update {MARKET}"})   # 別の会話が先に取り直して版はそろった
    rc, out = run(runner, {}, local='skip = ["plugins1"]\nno_install = ["gone", "attention"]\n')
    tries = [a for a, _ in calls if a[:4] == ["claude", "plugin", "marketplace", "update"]]
    assert rc == 0 and len(tries) == 4 and "main: marketplace の更新は落ちたが、入った版は main とそろったので失敗に数えない" in out, (rc, out, tries)
    # 入った版がそろっても、main に在るのに入っていない物（更新の落ちた clone は main で足した物を載せない）が在れば失敗のまま
    runner, calls = world(fail={f"claude plugin marketplace update {MARKET}"})
    rc, out = run(runner, {})
    assert rc == 1 and "- main: claude plugin marketplace update" in out and "gone@" in out and "attention@" in out, (rc, out)
    runner, _ = world(fail={f"claude plugin marketplace update {MARKET}"})
    def stale(argv, env=None):   # fetch が落ちると手元の origin/main は古いかもしれず、そろったと言えない
        return (1, "network") if argv[:2] == ["git", "-C"] and argv[3:4] == ["fetch"] else runner(argv, env)
    rc, out = run(stale, {}, local='skip = ["plugins1"]\nno_install = ["gone", "attention"]\n')
    assert rc == 1 and "- main: claude plugin marketplace update" in out, (rc, out)
    runner, _ = world(fail={f"claude plugin marketplace update {MARKET}"})
    def twin(argv, env=None):   # 同じ名前で設定のフォルダの違うアカウントは、別に数える（片方の入った物で、もう片方の欠けを隠さない）
        code, out = runner(argv, env)
        if argv[:3] == ["claude", "plugin", "list"] and (env or {}).get("CLAUDE_CONFIG_DIR") != "/c/twin":
            got = json.loads(out)
            out = json.dumps(got + [dict(got[0], id=f"gone@{MARKET}")])
        return code, out
    rc, out = run(twin, {}, local='skip = ["plugins1"]\nno_install = ["attention"]\n'
                  'accounts = [{ name = "main", config_dir = "/c/twin" }]\n')
    assert rc == 1 and "main（/c/twin）: marketplace の更新が落ち、main に在る gone@" in out, (rc, out)
    assert "main: marketplace の更新は落ちたが、入った版は main とそろった" in out, (rc, out)
    runner, _ = world(fail={f"claude plugin marketplace update {MARKET}"}, main=None)   # メインブランチを読めなければそろったと言えない
    rc, out = run(runner, {})
    assert rc == 1 and "- main: claude plugin marketplace update" in out, (rc, out)
    runner, calls = world(flaky={f"claude plugin marketplace update {MARKET}"})   # 別の会話の取り直しとぶつかった
    rc, out = run(runner, {})
    tries = [a for a, _ in calls if a[:4] == ["claude", "plugin", "marketplace", "update"]]
    assert rc == 0 and len(tries) == 3, (rc, out, tries)   # 落ちた 1 回だけ打ち直す
    for broken in ({"herdr", "pane", "list"}, {"herdr", "agent", "prompt"}):   # herdr が落ちても配った結果を出し、失敗に数える
        runner, _ = world()
        def failing(argv, env=None, runner=runner, broken=broken):
            return (1, "boom") if broken <= set(argv[:3]) else runner(argv, env)
        rc, out = run(failing, {})
        assert rc == 1 and "boom" in out.strip().splitlines()[-1], (broken, rc, out)
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
    runner, calls = world(version=lambda n: "1.1.0" if n >= 2 else "1.0.0", main="1.1.0")   # 配る間にメインブランチが進んだ
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
    runner, calls = world()   # メインブランチは全アカウントに配った後に読む（配る間にメインブランチへ入った版を、入った版が新しいのにそろわないと数えない）
    run(runner, {})
    seq = [i for i, (a, _) in enumerate(calls) if a[:2] == ["claude", "plugin"] and a[2] in ("update", "marketplace")
           and "list" not in a]
    reads = [i for i, (a, _) in enumerate(calls) if a[:1] == ["git"] and a[2] == str(sp.ROOT)]
    assert reads and min(reads) > max(seq), calls
    runner, calls = world(main=None)   # メインブランチの版を読めなければ、照合できないので失敗に数える
    rc, out = run(runner, {})
    assert rc == 1 and "main の版を読めない" in out.strip().splitlines()[-1], out
    runner, calls = world(main=None)
    rc, out = run(runner, {"dry_run": True})   # 空打ちではメインブランチを読みに行かない
    assert rc == 0 and not [a for a, _ in calls if a[:1] == ["git"] and a[2] == str(sp.ROOT)], out
    print("BROKEN_COPY_OK")


def mend_clone():
    runner, calls = world(gone="attention/README.md\ntiers/README.md\n")
    rc, out = run(runner, {})
    assert rc == 0, out
    seq = [a for a, _ in calls if a[:1] == ["git"] and a[2] == "/m/mine" and a[3] != "show" or a[:3] == ["claude", "plugin", "update"]]
    assert seq[:3] == [["git", "-C", "/m/mine", "ls-files", "--deleted"], ["git", "-C", "/m/mine", "checkout", "--", "."],
                       ["claude", "plugin", "update", f"a@{MARKET}"]], seq   # 戻してから更新する
    assert "main: marketplace の clone の作業ツリーに 2 個のファイルが無いので戻す 済" in out, out
    runner, calls = world()
    run(runner, {})
    assert not [a for a, _ in calls if a[:4] == ["git", "-C", "/m/mine", "checkout"]], calls   # 欠けが無ければ触らない
    runner, calls = world(gone="a\n")
    rc, out = run(runner, {"dry_run": True})
    assert rc == 0 and "無いので戻す（空打ち）" in out and not [a for a, _ in calls if "checkout" in a], out
    # 別の会話が取り直している間で clone の置き場が無いときは、失敗に数えずに進む。置き場が在って git が落ちたときは失敗に数える
    missing = tempfile.mkdtemp()
    os.rmdir(missing)   # どの機械でも無い置き場
    for where, code, installed in ((missing, 0, None), (plugin_dir(), 1, None), (missing, 1, plugin_dir(whole=False))):
        runner, calls = world(installed=installed)
        def lost(argv, env=None):
            if argv[:4] == ["claude", "plugin", "marketplace", "list"]:
                return 0, json.dumps([{"name": MARKET, "installLocation": where}])
            if argv[:4] == ["git", "-C", where, "ls-files"]:
                return 128, f"fatal: cannot change to '{where}': No such file or directory"
            return runner(argv, env)
        rc, out = run(lost, {}, local='skip = ["plugins1"]\nno_install = ["gone", "attention"]\n')
        assert rc == code and ("clone が無いので欠けを確かめずに進む" in out) == (where == missing), (where, out)
        assert ("clone の欠けを確かめられない 失敗" in out) == (where != missing), (where, out)
        assert ("plugin.json が無い" in out) == bool(installed), (where, out)   # 置き場が無くても欠けた写しは失敗に数える
        assert [a for a, _ in calls if a[:3] == ["claude", "plugin", "update"]], calls   # どちらでもプラグインの更新は打つ
    # clone が無い間は main で足したプラグインを入れられないので、main に在って入っていない物は失敗に数える
    runner, calls = world()
    def blind(argv, env=None):
        if argv[:4] == ["claude", "plugin", "marketplace", "list"]:
            return 0, json.dumps([{"name": MARKET, "installLocation": missing}])
        if argv[:4] == ["git", "-C", missing, "ls-files"]:
            return 128, f"fatal: cannot change to '{missing}': No such file or directory"
        return runner(argv, env)
    rc, out = run(blind, {})
    assert rc == 1 and "marketplace の clone が無く、main に在る" in out and "gone@" in out, out
    print("MEND_CLONE_OK")


def real_list(installed, version):
    """実物から採った claude plugin list --json の見本。この marketplace の 1 件の入った場所と版だけ、試験の物に替える。"""
    got = json.loads((FIXTURES / "claude-plugin-list.json").read_text(encoding="utf-8"))
    for p in got:
        if p["id"].endswith("@" + MARKET):
            p.update(installPath=installed, version=version)
    return got


def real_panes():
    """実物から採った herdr pane list の窓の並び（claude の手の空いた会話 1 つと、会話の居ない窓 1 つ）。"""
    return json.loads((FIXTURES / "herdr-pane-list.json").read_text(encoding="utf-8"))["result"]["panes"]


def real_shapes():
    panes = real_panes()
    dept = panes[0]["cwd"]
    runner, calls = world(listed=real_list, panes=panes)
    def company(argv, env=None):   # 見本の会話の場所を部署と見る
        if argv[:2] == ["git", "-C"] and argv[2] == dept and "company.role" in argv:
            return 0, "作業\n"
        return runner(argv, env)
    rc, out = run(company, {})
    assert rc == 0 and out.strip().endswith("配った"), out
    updates = [(a[3], env) for a, env in calls if a[:3] == ["claude", "plugin", "update"]]
    assert updates == [(f"attention@{MARKET}", None), (f"attention@{MARKET}", "/c/p1")], updates   # 別の marketplace・project の scope は触らない
    assert [a[3] for a, _ in calls if a[:3] == ["herdr", "agent", "prompt"]] == [panes[0]["pane_id"]], calls
    print("REAL_SHAPES_OK")


def install_missing():
    new = plugin_dir()
    runner, calls = world(offered=["a", "new", "skipme"])
    def installing(argv, env=None):   # 入れた後の一覧に、そのアカウントで入れた物が載る
        code, out = runner(argv, env)
        here = (env or {}).get("CLAUDE_CONFIG_DIR")
        if argv[:3] == ["claude", "plugin", "list"] and [a for a, e in calls if a[:3] == ["claude", "plugin", "install"] and e == here]:
            out = json.dumps(json.loads(out) + [{"id": f"new@{MARKET}", "scope": "user", "installPath": new, "version": "1.0.0"}])
        return code, out
    rc, out = run(installing, {}, 'skip = ["plugins1"]\nno_install = ["skipme"]\n')
    assert rc == 0, out
    installs = [(a[3], env) for a, env in calls if a[:3] == ["claude", "plugin", "install"]]
    assert installs == [(f"new@{MARKET}", None), (f"new@{MARKET}", "/c/p1")], installs   # 入っている a と、除いた skipme は入れない
    assert out.count(f"claude plugin install new@{MARKET} 済（1.0.0）") == 2, out
    runner, calls = world(offered=["a", "new"])
    rc, out = run(runner, {"dry_run": True})
    assert rc == 0 and f"main: claude plugin install new@{MARKET}（空打ち）" in out, out
    assert not [a for a, _ in calls if a[:3] == ["claude", "plugin", "install"]], calls
    runner, calls = world(offered=["a", "new"], installed=plugin_dir(whole=False))   # 入れても写しが欠けていれば済と数えない
    rc, out = run(runner, {})
    assert rc == 1 and f"claude plugin install new@{MARKET} 失敗（入った写しに .claude-plugin/plugin.json が無い" in out, out
    runner, calls = world(offered=["a", "new"], fail={f"claude plugin install new@{MARKET}"})
    rc, out = run(runner, {})
    installs = [env for a, env in calls if a[:3] == ["claude", "plugin", "install"]]
    assert rc == 1 and installs == [None, "/c/p1", None, "/c/p1"], (out, installs)   # 落ちたら 1 回だけ配り直す
    def renamed(installed, version):
        return [{"plugin_id": f"a@{MARKET}", "scope": "user"}]
    runner, calls = world(listed=renamed, offered=["a", "new"])   # 入っている物を読めなければ、全部を入れ直さない
    rc, out = run(runner, {})
    assert rc == 1 and not [a for a, _ in calls if a[:3] == ["claude", "plugin", "install"]], calls
    runner, calls = world()
    def shapeless(argv, env=None):
        if argv[:4] == ["git", "-C", "/m/mine", "show"]:
            calls.append((argv, None))
            return 0, json.dumps({"entries": []})
        return runner(argv, env)
    rc, out = run(shapeless, {})
    names, (failed, _) = sp.offered("main", MARKET, {}, shapeless)
    assert rc == 1 and names == [] and failed, out   # 一覧の形が違えば、入れずに失敗に数える
    def no_location(argv, env=None):   # marketplace list が落ちて clone の置き場を読めない（取り直しの間と別に、失敗に数える）
        return (1, "boom") if argv[:4] == ["claude", "plugin", "marketplace", "list"] else runner(argv, env)
    names, (failed, line) = sp.offered("main", MARKET, {}, no_location)
    assert names == [] and failed and "置き場を読めない" in line, line
    print("INSTALL_MISSING_OK")


def shape_changed():
    def renamed(installed, version):   # id の名前が変わった
        return [{("plugin_id" if k == "id" else k): v for k, v in p.items()} for p in real_list(installed, version)]
    def others(installed, version):    # この marketplace の物が 1 つも見えない（scope の値が変わったなど）
        return [dict(p, scope="global") for p in real_list(installed, version)]
    def scopeless(installed, version):   # scope が消えた（全部を user と見て project の物まで更新しない）
        return [{k: v for k, v in p.items() if k != "scope"} for p in real_list(installed, version)]
    for listed, want in ((renamed, "id か scope が無い"), (others, "1 つも無い"), (scopeless, "id か scope が無い")):
        runner, calls = world(listed=listed, panes=real_panes())
        rc, out = run(runner, {})
        assert rc == 1 and want in out.strip().splitlines()[-1], (want, out)
        assert not [a for a, _ in calls if a[:3] == ["claude", "plugin", "update"]], calls
    panes = [{("kind" if k == "agent" else k): v for k, v in p.items()} for p in real_panes()]   # agent の名前が変わった
    runner, calls = world(listed=real_list, panes=panes)
    rc, out = run(runner, {})
    assert rc == 1 and "claude の会話が 1 つも無い" in out.strip().splitlines()[-1], out
    lists = []
    def vanished(installed, version):   # 最初の一覧には在り、更新の後の取り直しで消えた
        lists.append(1)
        return real_list(installed, version) if len(lists) == 1 else []
    runner, calls = world(listed=vanished, panes=real_panes())
    rc, out = run(runner, {})
    assert rc == 1 and "失敗（入った写しを確かめられない: main: この marketplace" in out, out
    runner, calls = world(listed=real_list, panes=[dict(real_panes()[0], agent_status="thinking")])   # 知らない状態
    def company(argv, env=None):
        if argv[:2] == ["git", "-C"] and "company.role" in argv:
            return 0, "作業\n"
        return runner(argv, env)
    rc, out = run(company, {})
    assert rc == 1 and "知らない状態 'thinking'" in out.strip().splitlines()[-1], out
    assert not [a for a, _ in calls if a[:3] == ["herdr", "agent", "prompt"]], calls
    print("SHAPE_CHANGED_OK")


if __name__ == "__main__":
    {"only-company-talks": only_company_talks, "bad-config": bad_config, "failure-is-nonzero": failure_is_nonzero,
     "local-accounts": local_accounts, "broken-copy": broken_copy, "mend-clone": mend_clone,
     "real-shapes": real_shapes, "install-missing": install_missing, "shape-changed": shape_changed}[sys.argv[1]]()
