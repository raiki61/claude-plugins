#!/usr/bin/env python3
"""このリポジトリの marketplace のプラグインを、手元の全アカウントに配る（会社の形 .claude/company.toml の役「配布」のツール）。

works-dispatch の機械窓口のツールとして、`dispatch.py --call 配布 spread-plugins` か、main に入れた後の合図（[[land.after]]）で
呼ばれる。入力の JSON（`{"dry_run": true}` で、することだけを出す）を標準入力で受ける。片づいたら 0、1 つでも失敗したら 1 で
終わり、works-dispatch がその仕事を AI の部署（役「作業」）に回す。

すること:
1. アカウントごとに（works-dispatch の設定の accounts と、手元の設定 `~/.config/claude-plugins/spread.toml` の accounts。
   設定のフォルダ config_dir ごとに Claude Code を起動する）、`claude plugin marketplace update <このリポジトリの marketplace>`
   を打ち（落ちたら 1 回だけ打ち直す。それでも落ちても、入った版が全部 main とそろえば失敗に数えない）、入っているこの marketplace のプラグインだけ `claude plugin update <id>` を打つ。marketplace の clone の作業ツリーから
   消えたファイルは戻し、入った写しに .claude-plugin/plugin.json が無ければ失敗に数える。works-dispatch の設定に載るのは
   部署を起動する先のアカウントだけなので、Claude Code を使うが部署は起動しないアカウントは手元の設定の accounts に書く
   （書き方は works-dispatch の設定と同じ `{ name = "…", config_dir = "…" }`。同じ設定のフォルダは 1 回だけ配る）。
   全アカウントに配った後に、入ったプラグインの版が main（origin/main。先に git fetch する）の plugin.json の版と同じかを
   照合し、違えば版のずれたアカウントだけ 1 回配り直して照合し直し、まだ違えば失敗に数える。main は配った後に読む。配る前に
   読むと、配る間に別の部署が main へ入れた版を marketplace が先に拾い、入った版が main より新しいのに「そろわない」と数える
   （2026-10-17 に works-dispatch 0.36.0 で実測）。配り直すのは、配る間に main が進むと先に配ったアカウントが前の版のまま
   残るため（2026-10-17 に works-dispatch 0.37.0 で実測）。全アカウントが main の版に合えば、版はそろっている（会話が installed_plugins.json を手で見なくて済む）。
2. herdr に開いている Claude Code の会話のうち、部署と窓口の会話（場所の git の設定に company.role が在る物）にだけ
   `/reload-plugins` を打つ。持ち主の作業の会話に打つと herdr で done に替わり、ノイズになるため（この決まりは組織の物なので、
   works-dispatch でなくここに置く）。ターンの途中の会話（herdr が idle・done と見ていない物）と、入力フィールドに字が入っている会話は
   飛ばす。飛ばした会話は、works-dispatch のターンの終わりのフック（dispatch/refresh_hook.py）が、その会話のターンの終わりの手の空いた
   時に替える。/clear では替わらない（2026-10-17 に Claude Code 2.1.302 で確かめた）。
3. その人だけの除外は手元の設定の `skip`（herdr の作業場の名前の並び）に置く。持ち主の値を配布物に書かない。
4. 外のツールの形が変わったら、何も更新せずに「配った」と出さず、失敗に数える: `claude plugin list --json` の物に id か scope が無い・
   この marketplace のプラグインが user の scope に 0 件・herdr のペインに claude の会話が 0 個・herdr の知らない状態（KNOWN_STATUS の外）。
   そのため、配る先のアカウントには、この marketplace のプラグインを 1 つ以上入れておく（0 件のアカウントは毎回失敗に数える。
   形が変わって id が読めないときと見分けが付かないため）。試験は実物から採った見本（tests/fixtures/spread-plugins/）で回す。

使い方: python3 scripts/spread-plugins.py < 入力の JSON（省けば {}）
終了の値: 0 = 配った（飛ばした会話は数えない）/ 1 = 失敗が在る（失敗の行を出力の終わりに並べ直す）/ 2 = 入力か設定が読めない
"""

import json
import os
import pathlib
import subprocess
import sys
import tomllib

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
# herdr への口・会話の手が空いたと見る状態・入力フィールドの打ちかけの見分けは、works-dispatch の物をそのまま使う（写すと割れる。
# 前は写しで、works-dispatch が Claude Code の薄字の候補を打った字と数えないよう直った後も、こちらは候補の出た会話を飛ばしていた）
sys.path.insert(0, str(ROOT / "works-dispatch" / "dispatch"))
import herdr  # noqa: E402
from nodes import deliver, refresh  # noqa: E402

DISPATCH_CONFIG = "~/.config/works-dispatch/dispatch.toml"   # works-dispatch の設定の既定の場所（WORKS_DISPATCH_CONFIG で替わる）
LOCAL = "~/.config/claude-plugins/spread.toml"             # その人だけの配る先の足しと除外
RELOAD = refresh.RELOAD
# herdr が会話に付ける状態のうち知っている物。手の空いた物は refresh.IDLE、ターンの途中は refresh.BUSY。unknown は herdr が
# 状態をまだ決めていない会話（herdr 0.9.3 の実物の pane list に出る）で、ターンの途中と同じに飛ばす
KNOWN_STATUS = refresh.IDLE + refresh.BUSY + ("unknown",)


def run(argv, env=None):
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def marketplace_name(root=ROOT):
    return json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))["name"]


def read_toml(path):
    p = pathlib.Path(os.path.expanduser(path))
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def listed(table, key, kind, where):
    """設定の表の key の並び。並びでないか、kind でない物が混ざれば ValueError（黙って飛ばすと、配る先や除外が知らずに減る）。"""
    got = table.get(key, [])
    if not isinstance(got, list) or not all(isinstance(x, kind) for x in got):
        raise ValueError(f"{where} の {key} が {kind.__name__} の並びでない")
    return got


def accounts(env=os.environ, local=LOCAL):
    """配る先のアカウントの並び [(名前, 設定のフォルダか None)]。works-dispatch の設定の物に手元の設定の物を足し、
    同じ設定のフォルダは先の 1 つだけ残す。works-dispatch の設定が無いか accounts が空なら、既定の 1 つから始める。"""
    path = env.get("WORKS_DISPATCH_CONFIG") or DISPATCH_CONFIG
    raw = listed(read_toml(path), "accounts", dict, path) or [{"name": "default"}]
    out, seen = [], set()
    for a in raw + listed(read_toml(local), "accounts", dict, local):
        if not all(isinstance(a.get(k, ""), str) for k in ("name", "config_dir")):
            raise ValueError(f"accounts の name・config_dir が文字列でない: {a}")
        d = a.get("config_dir")
        key = os.path.realpath(os.path.expanduser(d)) if d else None
        if key not in seen:
            seen.add(key)
            out.append((a.get("name") or "?", d))
    return out


def skips(path=LOCAL):
    return listed(read_toml(path), "skip", str, path)


def step(account, kind, text, failed):
    """1 つの手の結果。成否と種類はフィールドで持ち、text は人に見せるだけ（後で text を読んで分岐しない）。
    kind は marketplace-update・mend・list・update・version・main・talk・reload のどれか。"""
    return {"account": account, "kind": kind, "text": text, "failed": failed}


def claude_env(config_dir, env=os.environ):
    out = {k: v for k, v in env.items() if k != "CLAUDE_CONFIG_DIR"}
    if config_dir:
        out["CLAUDE_CONFIG_DIR"] = os.path.expanduser(config_dir)
    return out


def mend_clone(name, market, env, dry, runner=run):
    """その設定のフォルダの marketplace の clone で、作業ツリーから消えた tracked のファイルを index から戻す。step の並び。
    clone のやり直しが途中で切れると、作業ツリーが欠けたまま marketplace update は済になり、その後の plugin update は
    欠けた写しを入れるか（plugin.json の無い写しは版でなく commit の名前の版で入る）「destination is empty after copy」で
    失敗する（2026-10-17 に p2 で実測）。marketplace update は欠けを戻さないので、ここで戻す。"""
    code, out = runner(["claude", "plugin", "marketplace", "list", "--json"], env)
    try:
        loc = next((m.get("installLocation") for m in json.loads(out) if isinstance(m, dict) and m.get("name") == market),
                   None) if code == 0 else None
    except ValueError:
        loc = None
    if not loc:
        return []   # 戻せないときも、入った写しの検査（update_account）が欠けを失敗に数える
    code, out = runner(["git", "-C", loc, "ls-files", "--deleted"])
    if code != 0:
        return [step(name, "mend", f"{name}: marketplace の clone の欠けを確かめられない 失敗（{out.strip()[:200]}）", True)]
    gone = out.splitlines()
    if not gone:
        return []
    what = f"{name}: marketplace の clone の作業ツリーに {len(gone)} 個のファイルが無いので戻す"
    if dry:
        return [step(name, "mend", what + "（空打ち）", False)]
    code, out = runner(["git", "-C", loc, "checkout", "--", "."])
    return [step(name, "mend", what + (" 済" if code == 0 else f" 失敗（{out.strip()[:200]}）"), code != 0)]


def expected_versions(market, root=ROOT, runner=run):
    """(main の {id: 版}, 読めなかったときの行か None)。main は origin/main で、先に fetch する（fetch が切れても手元の
    origin/main で照合する。--land の push の後なら手元の origin/main も入れた commit を指す）。全アカウントに配った後に呼ぶ。"""
    runner(["git", "-C", str(root), "fetch", "--quiet", "origin", "main"])
    def show(path):
        code, out = runner(["git", "-C", str(root), "show", f"origin/main:{path}"])
        if code != 0:
            raise ValueError(out.strip()[:200])
        return json.loads(out)
    try:
        out = {}
        for p in show(".claude-plugin/marketplace.json").get("plugins", []):
            src = p.get("source")
            if isinstance(src, str) and src.startswith("./"):
                out[f"{p['name']}@{market}"] = show(f"{src[2:]}/.claude-plugin/plugin.json").get("version")
        return out, None
    except (ValueError, KeyError, AttributeError) as e:
        return {}, f"main の版を読めない（{e}）"


def installed_ids(name, market, env, runner=run):
    """(入っているこの marketplace のプラグインの {id: (入った場所, 版)}, 読めなかったときの行か None)。user の scope の物だけ。"""
    code, out = runner(["claude", "plugin", "list", "--json"], env)
    try:
        got = json.loads(out) if code == 0 else None
    except ValueError:
        got = None
    if not isinstance(got, list):
        return {}, f"{name}: 入っているプラグインを読めない（{out.strip()[:200]}）"
    # 使うフィールドが消えた・名前が変わったときに、何も更新せず「配った」と出さない（Claude Code の版で形が変わりうる）
    # scope が消えたときに全部を user と見て、project の scope の物まで更新しない
    shapeless = [p for p in got if not (isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("scope"), str))]
    if shapeless:
        return {}, f"{name}: claude plugin list --json の {len(shapeless)} 件に id か scope が無い（形が変わったか: {json.dumps(shapeless[0], ensure_ascii=False)[:200]}）"
    ids = {p["id"]: (p.get("installPath"), p.get("version")) for p in got if p["id"].endswith("@" + market)
           and p["scope"] == "user"}
    if not ids:
        # 配る先のアカウントには、この marketplace のプラグインが入っているはず。0 件は形の変化か、入れ損ねたアカウント
        return {}, f"{name}: この marketplace（{market}）のプラグインが user の scope に 1 つも無い（claude plugin list --json の id・scope の形が変わったか、入っていない）"
    return ids, None


def update_account(name, config_dir, market, dry, runner=run):
    """1 つのアカウントの marketplace とプラグインを更新する。(step の並び, 写しの揃った [(名前, id, 版)])。
    入った写しに .claude-plugin/plugin.json が無ければ失敗に数える（欠けた写しを済と数えない）。版は check_versions が照合する。"""
    env = claude_env(config_dir)
    steps = []

    def note(kind, line, failed):
        steps.append(step(name, kind, line, failed))

    argv = ["claude", "plugin", "marketplace", "update", market]
    if dry:
        note("marketplace-update", f"{name}: {' '.join(argv)}（空打ち）", False)
    else:
        code, out = runner(argv, env)
        if code != 0:
            # 同じ設定のフォルダの別の会話が同じ時に marketplace を取り直すと、clone の置き場（<名前>..clone）がぶつかって
            # 落ちる（shallow.lock が在る・index を書けない。2026-10-17 に main で実測し、打ち直すと通った）。1 回だけ打ち直す
            code, out = runner(argv, env)
        note("marketplace-update", f"{name}: {' '.join(argv)} " + ("済" if code == 0 else f"失敗（{out.strip()[:200]}）"), code != 0)
    steps += mend_clone(name, market, env, dry, runner)
    ids, err = installed_ids(name, market, env, runner)
    if err:
        note("list", err, True)
    done, whole = [], []
    for i in sorted(ids):
        argv = ["claude", "plugin", "update", i]
        if dry:
            note("update", f"{name}: {' '.join(argv)}（空打ち）", False)
            continue
        code, out = runner(argv, env)
        if code != 0:
            note("update", f"{name}: {' '.join(argv)} 失敗（{out.strip()[:200]}）", True)
        else:
            done.append(i)
    if done:
        after, err = installed_ids(name, market, env, runner)
        for i in done:
            head = f"{name}: claude plugin update {i} "
            where, version = after.get(i, (None, None))
            if err:
                note("update", head + f"失敗（入った写しを確かめられない: {err}）", True)
            elif not where or not (pathlib.Path(where) / ".claude-plugin" / "plugin.json").is_file():
                note("update", head + f"失敗（入った写しに .claude-plugin/plugin.json が無い: {where}）", True)
            else:
                whole.append((name, i, version))
    return steps, whole


def check_versions(whole, want):
    """写しの揃ったプラグインの版を main の {id: 版} と照合する。step の並び。「済」と出すのは版が main と同じときだけ
    （古い版を済と数えない）。main に無いプラグイン（marketplace から外した物）は版を照合しない。"""
    steps = []
    for name, i, version in whole:
        head = f"{name}: claude plugin update {i} "
        if i in want and version != want[i]:
            steps.append(step(name, "version", head + f"失敗（版が main とそろわない: 入った版 {version}・main {want[i]}）", True))
        else:
            steps.append(step(name, "version", head + f"済（{version}）", False))
    return steps


def is_company_place(cwd, runner=run):
    """その場所が部署か窓口か（git の設定 company.role が在る）。"""
    code, out = runner(["git", "-C", cwd, "config", "--worktree", "--get", "company.role"])
    return code == 0 and bool(out.strip())


def reload_talks(skip, dry, runner=run, herdr_run=herdr._default_runner):
    """部署と窓口の会話に /reload-plugins を打つ。step の並び。herdr は herdr_run（argv → CompletedProcess）で呼ぶ。"""
    try:
        labels = herdr.workspace_labels(herdr_run)
        panes = herdr.panes(herdr_run)
    except (herdr.HerdrError, OSError) as e:   # OSError は herdr が入っていない・起動できないとき
        return [step(None, "talk", f"herdr を読めない（{e}）", True)]
    steps = []
    talks = [p for p in panes if p.get("agent") == "claude"]
    if not talks:
        # 配るのは herdr に開いた会話（main に入れた部署か、--call を打った会話）から打つ前提で、その会話自身が 1 つは居る。
        # claude の会話のペインが 0 個なのは、herdr の形（agent の名前か値）が変わったとき
        return [step(None, "talk", f"herdr のペインに claude の会話が 1 つも無い（herdr pane list の agent の形が変わったか。ペイン {len(panes)} 個）", True)]
    for p in talks:
        if not p.get("cwd"):
            continue
        where = f"{labels.get(p.get('workspace_id')) or p.get('workspace_id')}（{p['pane_id']}）"
        if labels.get(p.get("workspace_id")) in skip:
            steps.append(step(None, "talk", f"{where}: 手元の設定で除く", False))
            continue
        if not is_company_place(p["cwd"], runner):
            continue   # 持ち主の作業の会話（部署でも窓口でもない）には打たない
        if p.get("agent_status") not in KNOWN_STATUS:
            steps.append(step(None, "talk", f"{where}: herdr の知らない状態 {p.get('agent_status')!r} なので飛ばす（herdr の形が変わったか）", True))
            continue
        if p.get("agent_status") not in refresh.IDLE:
            steps.append(step(None, "talk", f"{where}: ターンの途中なので飛ばす（ターンの終わりに替わる）", False))
            continue
        try:
            box = deliver.typed(herdr.read(p["pane_id"], 40, herdr_run, ansi=True))   # 薄字の候補は打った字と数えない
        except (herdr.HerdrError, OSError) as e:
            steps.append(step(None, "talk", f"{where}: 画面を読めない（{e}）", True))
            continue
        if box is None:
            steps.append(step(None, "talk", f"{where}: 入力フィールドが見えないので飛ばす", False))
            continue
        if box:
            steps.append(step(None, "talk", f"{where}: 入力フィールドに字が在るので飛ばす", False))
            continue
        if dry:
            steps.append(step(None, "reload", f"{where}: {RELOAD}（空打ち）", False))
            continue
        try:
            got = herdr.prompt(p["pane_id"], RELOAD, False, herdr_run)
        except (herdr.HerdrError, OSError) as e:
            got = str(e)
        ok = got == "sent"   # herdr の見張りが止めた打ち込みは "stalled" で返る（herdr.prompt）
        steps.append(step(None, "reload", f"{where}: {RELOAD} " + ("済" if ok else f"失敗（{got}）"), not ok))
    return steps


def main(stdin=sys.stdin, runner=run, env=os.environ, local=LOCAL, herdr_run=herdr._default_runner):
    try:
        value = json.loads(stdin.read() or "{}")
        if not isinstance(value, dict):
            raise ValueError("JSON の物で無い")
        dry = bool(value.get("dry_run"))
        market = marketplace_name()
        accs, skip = accounts(env, local), skips(local)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as e:
        print(f"止めた: 入力か設定を読めない（{e}）")
        return 2
    steps, whole = [], []
    for name, config_dir in accs:
        got, ok = update_account(name, config_dir, market, dry, runner)
        steps += got
        whole += ok
    if whole:   # main は配った後に読む（配る間に main へ入った版を、入った版が新しいのにそろわないと数えないため）
        want, err = expected_versions(market, runner=runner)
        # 配る間に main が進むと、先に配ったアカウントは前の版のまま残る（2026-10-17 に works-dispatch 0.37.0 で実測）。
        # 版のずれたアカウントだけ 1 回配り直し、main を読み直して照合する
        stale = {n for n, i, v in whole if i in want and v != want[i]}
        if stale and not err:
            whole = [w for w in whole if w[0] not in stale]
            for name, config_dir in accs:
                if name in stale:
                    got, ok = update_account(name, config_dir, market, dry, runner)
                    steps += got
                    whole += ok
            want, err = expected_versions(market, runner=runner)
        if err:
            steps.append(step(None, "main", err, True))
        steps += check_versions(whole, want)
        if not err:
            # 打ち直しても marketplace の更新が落ちたアカウントでも、入った版が全部 main と同じなら目的は果たしている。同じ設定のフォルダの
            # 別の会話が clone を取り直している間は打ち直しもぶつかって落ち、その会話の取り直しで版はそろう（2026-10-17 に main で実測）
            off = {n for n, i, v in whole if i in want and v != want[i]}
            even = {n for n, i, v in whole if i in want} - off
            for n in sorted(even):
                fell = [s for s in steps if s["account"] == n and s["kind"] == "marketplace-update" and s["failed"]]
                for s in fell:
                    s["failed"] = False
                if fell:
                    steps.append(step(n, "marketplace-update",
                                      f"{n}: marketplace の更新は落ちたが、入った版は main とそろったので失敗に数えない", False))
    steps += reload_talks(skip, dry, runner, herdr_run)
    bad = [s["text"] for s in steps if s["failed"]]
    # 失敗の行は終わりに並べ直す（works-dispatch が作業に回す頼みには出力の終わりしか載らない）
    print("\n".join([s["text"] for s in steps] + ([f"失敗 {len(bad)} 件:"] + [f"- {x}" for x in bad] if bad else ["配った"])))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
