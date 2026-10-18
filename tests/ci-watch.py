#!/usr/bin/env python3
"""main の CI の赤・止まった定期の workflow・1 度も回っていない workflow を、直す担当（点検）の受付に届ける（会社の形
.claude/company.toml の役「CI の見張り」のツール。標準 docs/standards/breakage-detection.md の決まり 1・2・6）。

works-dispatch の機械窓口のツールとして、main に入れた後の合図（[[land.after]]）か `dispatch.py --call` で呼ばれる。持ち主は定期の
起動（cron）を置かないと決めているので、main へ入れる動きに乗せる（main へ誰も入れない間は、この見張りも止まる）。知らせる物が在れば、
その行を出して 1 で終わる。works-dispatch がその出力を添えて役の fallback_role（点検）への頼みに変える（新しい通知の仕組みは作らない）。

見る物（GitHub に登録された全部の workflow。gh workflow list と gh run list --branch main の JSON で読む）:
- 赤: main の最新の決着した run（成功か失敗。取り消し・飛ばしは数えない。読む数の中に決着した run が無ければ、決着ごとに最新を
  引く）が失敗。最後の緑から最新の赤までの commit の範囲を添える
  （main の run は後の push に替えられて取り消されることが多く、どの commit が赤にしたか 1 つに決まらないため）
- 止まった定期: schedule の run の間隔（過去の schedule の run の間の、一番長い間）と 1 日を足した長さより、最後の schedule の run が古い。
  GitHub は動きの無いリポジトリの定期の workflow を 60 日で止める。schedule の run は別に引く（push の run が多いと読む数から外れる）。
  schedule の run が 1 件しか無い間は、間隔が分からないので見ない
- 回っていない: main に 1 度も run が無い（文書が「回す」と書いた workflow を、誰も起動していない）
- 止められた: workflow の状態が active でない（disabled_inactivity など）

同じ件を何度も頼まない: 知らせた件の鍵（workflow と種類と、赤なら最後の緑の run）を覚え（代表の clone の git の共通の
ディレクトリの ci-watch.json）、覚えた件は、このツールから回した頼みが閉じていないうちは知らせない。新しい件は、開いた頼みが在っても
知らせる。頼みが閉じた後は、閉じた後に新しく決着した赤の run が在るときだけ知らせ直す（戻しの commit の run が決着する前に同じ赤を
頼み直さない）。回っていない・止められた・止まった定期の件は、閉じた後は知らせ直さない（担当が見て閉じた物。直って消えた後に
また起きれば、新しい件として知らせる）。リポジトリに workflow のファイルが無い物（GitHub が足す物・消した物）は見ない。

使い方: python3 tests/ci-watch.py < 入力の JSON（省けば {}。{"dry_run": true} なら、知らせる物を出すだけで覚えない）
終了の値: 0 = 知らせる物が無い / 1 = 知らせる物が在る（その行を出す）か、gh・台帳を読めない / 2 = 入力が読めない
"""

import datetime
import json
import os
import pathlib
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
# 開いた頼みの見分けは works-dispatch の物をそのまま使う（scripts/spread-plugins.py と同じ形。写すと割れる）
sys.path.insert(0, str(ROOT / "works-dispatch" / "dispatch"))
from nodes import deliver  # noqa: E402

TOOL = "ci-watch"   # 会社の形の [[roles.tools]] の name。works-dispatch が回す頼みの題「ツール <役>/<name> が…」で、このツールの頼みを見分ける
STATE = "ci-watch.json"
RED = ("failure", "timed_out", "startup_failure")
GREEN = ("success",)
RUNS = 100   # workflow ごとに読む run の数。この中に緑が無ければ、最後の緑を別に引く
SLACK = datetime.timedelta(days=1)
FIELDS = "databaseId,status,conclusion,event,headSha,createdAt,url"


def run(argv):
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout or "", p.stderr or ""


def gh_json(argv, runner):
    code, out, err = runner(["gh", *argv])
    if code != 0:
        raise RuntimeError(f"gh {' '.join(argv)} が {code} で終わった: {err.strip()[-300:]}")
    try:
        return json.loads(out)
    except ValueError as e:
        raise RuntimeError(f"gh {' '.join(argv)} の出力を JSON として読めない（{e}）") from e


def when(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def runs_of(wf, runner, *extra, limit=RUNS):
    return gh_json(["run", "list", "--workflow", str(wf["id"]), "--branch", "main", *extra, "--limit", str(limit), "--json", FIELDS],
                   runner)


def newest(runs):
    return max(runs, key=lambda r: when(r["createdAt"])) if runs else None


def findings(runner, now, root=ROOT):
    """知らせる物の並び。1 件は {key, text, since}。since は赤の件の最新の赤の run の時刻（頼みが閉じた後に知らせ直すかの見分け）で、
    ほかの件は None。gh を読めなければ RuntimeError。"""
    found = []
    for wf in gh_json(["workflow", "list", "--all", "--json", "id,name,path,state"], runner):
        name, path = wf["name"], wf["path"]
        if not (root / path).is_file():
            continue
        if wf["state"] != "active":
            found.append({"key": f"{path}:state:{wf['state']}", "since": None,
                          "text": f"{name}（{path}）の状態が {wf['state']}。戻すなら gh workflow enable {os.path.basename(path)}"})
        runs = runs_of(wf, runner)
        if not runs:
            found.append({"key": f"{path}:never", "since": None,
                          "text": f"{name}（{path}）は main で 1 度も回っていない。起動するなら gh workflow run {os.path.basename(path)}"})
            continue
        decided = [r for r in runs if r["status"] == "completed" and r["conclusion"] in RED + GREEN]   # 新しい順
        if not decided:   # 読む数の全部が取り消しか途中なら、決着ごとに最新を引く
            decided = sorted((r for c in RED + GREEN for r in runs_of(wf, runner, "--status", c, limit=1)),
                             key=lambda r: when(r["createdAt"]), reverse=True)
        if decided and decided[0]["conclusion"] in RED:
            last = decided[0]
            green = next((r for r in decided if r["conclusion"] in GREEN), None) or newest(runs_of(wf, runner, "--status", "success",
                                                                                                    limit=1))
            span = (f"赤にした commit の候補は、最後の緑 {green['headSha'][:8]}（run {green['databaseId']}）から {last['headSha'][:8]} までの"
                    f" commit（git log {green['headSha'][:8]}..{last['headSha'][:8]}）" if green
                    else "main で 1 度も緑になっていないので、赤にした commit を絞れない")
            # 鍵は最後の緑で決める（赤の続いた run が読む数を超えても、同じ赤の続きを別の件と数えない）
            found.append({"key": f"{path}:red:{green['databaseId'] if green else 'never-green'}", "since": when(last["createdAt"]),
                          "text": f"{name}（{path}）が main で赤: run {last['databaseId']}（{last['conclusion']}・{last['event']}・"
                                  f"{last['createdAt']}）{last['url']}。{span}"})
        sched = sorted(when(r["createdAt"]) for r in runs_of(wf, runner, "--event", "schedule"))
        if len(sched) >= 2:
            gap = max(b - a for a, b in zip(sched, sched[1:]))
            if now - sched[-1] > gap + SLACK:
                found.append({"key": f"{path}:stale:{sched[-1].isoformat()}", "since": None,
                              "text": f"{name}（{path}）の定期の run が止まっている: 最後は {sched[-1].isoformat()}（今まで "
                                      f"{(now - sched[-1]).days} 日。今までの間隔は長くて {gap.days} 日）"})
    return found


def common_dir(runner):
    code, out, err = runner(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if code != 0 or not out.strip():
        raise RuntimeError(f"git の共通のディレクトリが分からない: {err.strip()[-300:]}")
    return out.strip()


def mine(inbox):
    """このツールから回した頼みの (閉じていない物が在るか, 最後に閉じた時刻〔無ければ None〕)。頼みの題は works-dispatch が
    「ツール <役>/<name> が片づけられなかった仕事」で付ける（calls.hand_over。形が変わったら tests/ci-watch-case.py の title が赤になる）。"""
    marker = f"/{TOOL} "
    rows = deliver.records(inbox)
    ids = {r["id"] for r in rows if r.get("kind") == "ask" and r.get("id") and marker in (r.get("title") or "")}
    still = any(r["id"] in ids for r in deliver.open_asks(rows))
    closed = deliver.closed_ids(rows) & ids
    at = [r["at"] for r in rows if r.get("kind") in ("deliver", "forwarded", "withdrawn") and isinstance(r.get("at"), (int, float))
          and (r.get("ask") if r.get("kind") == "deliver" and r.get("ask") else r.get("id")) in closed]
    return still, (datetime.datetime.fromtimestamp(max(at), datetime.timezone.utc) if at else None)


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise RuntimeError(f"覚えた件（{path}）を読めない（{e}）。消せば、今の件を全部知らせ直す") from e
    if not isinstance(got, dict) or not isinstance(got.get("told"), list):
        raise RuntimeError(f"覚えた件（{path}）の形が違う（told の並びが無い）。消せば、今の件を全部知らせ直す")
    return got


def save_state(path, told):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"told": sorted(told)}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main(stdin=None, runner=run, now=None):
    raw = (sys.stdin if stdin is None else stdin).read().strip() or "{}"
    try:
        value = json.loads(raw)
        dry = bool(value.get("dry_run")) if isinstance(value, dict) else None
    except ValueError as e:
        print(f"止めた: 入力を JSON として読めない（{e}）")
        return 2
    if dry is None:
        print("止めた: 入力は JSON のオブジェクトにする")
        return 2
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        found = findings(runner, now)
        cdir = common_dir(runner)
        state_path = os.path.join(cdir, STATE)
        told = set(load_state(state_path).get("told", []))
        still_open, closed_at = mine(deliver.inbox_of(cdir))
    except RuntimeError as e:
        print(f"CI の見張りが読めなかった: {e}")
        return 1
    keys = {x["key"] for x in found}
    # 知らせ済みの件は、頼みが開いている間は黙り、閉じた後は閉じた後に新しく決着した赤だけ知らせ直す（閉じた記録の無い件は、頼みに
    # なったかが分からないので知らせ直す）
    tell = [x for x in found if x["key"] not in told
            or (not still_open and (closed_at is None or (x["since"] is not None and x["since"] > closed_at)))]
    if not tell:
        print("知らせる物は無い" + (f"（{len(found)} 件は知らせ済みで、その頼みが開いている）" if found else ""))
        if not dry:
            save_state(state_path, told & keys)   # 直った件は忘れる（また壊れたら知らせ直す）
        return 0
    print("\n".join(f"- {x['text']}" for x in tell))
    # 数の行は最後に出す（works-dispatch が頼みに載せるのは出力の末尾の行なので、件が多いと頭の行が落ちる）
    print(f"main の CI に、知らせる物が上の {len(tell)} 件ある（新しい件か、前に知らせた頼みが閉じた後に新しく赤になった件）")
    if not dry:
        save_state(state_path, (told & keys) | {x["key"] for x in tell})
    return 1


if __name__ == "__main__":
    sys.exit(main())
