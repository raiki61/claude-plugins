#!/usr/bin/env python3
"""tests/ci-watch.py（役「CI の見張り」のツール）を、gh と git を偽物の runner にし、受付箱の台帳を一時の階層に作って回す。

使い方: python3 tests/ci-watch-case.py <場合>
- red-range: main の最新の決着した run が赤なら 1 で終わり、run の URL と、最後の緑から最新の赤までの commit の範囲を出す。取り消しの
  run は決着に数えない。読む数の中に緑が無ければ、成功の run を別に引く。1 度も緑が無ければそう書く。dry_run は覚えない
  読む数の全部が取り消しなら、決着ごとに最新を引いて赤を見る。リポジトリにファイルの無い workflow は見ない
- told-while-open: 知らせた件は、このツールから回した頼みが開いているうちは知らせない（0 で終わる）。新しい件だけは知らせる
- reopen-after-close: 頼みが閉じた（納品された）後は、閉じた後に決着した赤の run が在るときだけ知らせ直す（戻しの run が決着する
  前は黙る）。閉じた記録の無い件は知らせ直す。緑に戻った件は忘れる
- age: 1 度も回っていない workflow・止められた workflow・間隔と 1 日より古い定期の run を知らせる。定期の run は、push の run が
  読む数を埋めても別に引く
- unreadable: gh が落ちたら黙らず 1 で知らせる。入力が JSON のオブジェクトでなければ 2
- title: works-dispatch が頼みに付ける題の形が、このツールの見分ける形のまま（calls.hand_over の字を見る）
"""

import datetime
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
spec = importlib.util.spec_from_file_location("ci_watch", ROOT / "tests" / "ci-watch.py")
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)

NOW = datetime.datetime(2026, 10, 19, 12, 0, tzinfo=datetime.timezone.utc)
TEST = {"id": 1, "name": "test", "path": ".github/workflows/test.yml", "state": "active"}
TITLE = f"ツール CI の見張り/{cw.TOOL} が片づけられなかった仕事"


def r(i, conclusion, sha, at="2026-10-18T10:00:00Z", event="push", status="completed"):
    return {"databaseId": i, "status": status, "conclusion": conclusion, "event": event, "headSha": sha * 8, "createdAt": at,
            "url": f"https://example.invalid/runs/{i}"}


class Fake:
    """gh と git の偽物。workflows は gh workflow list の答え、runs は workflow の id ごとの run（新しい順）。"""

    def __init__(self, gitdir, workflows, runs, broken=False):
        self.gitdir, self.workflows, self.runs, self.broken = gitdir, workflows, runs, broken

    def __call__(self, argv):
        if argv[0] == "git":
            return 0, self.gitdir + "\n", ""
        if self.broken:
            return 1, "", "HTTP 502"
        if argv[1:3] == ["workflow", "list"]:
            return 0, json.dumps(self.workflows), ""
        got = self.runs.get(int(argv[argv.index("--workflow") + 1]), [])
        if "--status" in argv:
            got = [x for x in got if x["conclusion"] == argv[argv.index("--status") + 1]]
        if "--event" in argv:
            got = [x for x in got if x["event"] == argv[argv.index("--event") + 1]]
        return 0, json.dumps(got[:int(argv[argv.index("--limit") + 1])]), ""


def setup(asks=()):
    """一時の git の共通のディレクトリ。asks は台帳の行（kind ask などの dict）の並び。"""
    d = tempfile.mkdtemp(prefix="ci-watch-")
    inbox = os.path.join(d, *cw.deliver.INBOX)
    os.makedirs(inbox)
    with open(os.path.join(inbox, cw.deliver.LOG), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(a, ensure_ascii=False) + "\n" for a in asks)
    return d


def go(fake, value="{}"):
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        code = cw.main(stdin=io.StringIO(value), runner=fake, now=NOW)
    finally:
        sys.stdout = old
    return code, out.getvalue()


def told(d):
    with open(os.path.join(d, cw.STATE), encoding="utf-8") as f:
        return json.load(f)["told"]


def check(cond, msg):
    if not cond:
        print(f"NG {msg}")
        sys.exit(1)


def red_range():
    d = setup()
    runs = {1: [r(9, None, "c", status="queued"), r(8, "cancelled", "b"), r(7, "failure", "a"), r(6, "success", "0")]}
    code, out = go(Fake(d, [TEST], runs), '{"dry_run": true}')
    check(code == 1 and "run 7" in out and "https://example.invalid/runs/7" in out, f"赤の run を出さない: {code} {out}")
    check("git log 00000000..aaaaaaaa" in out, f"最後の緑から赤までの範囲が無い: {out}")
    check(not os.path.exists(os.path.join(d, cw.STATE)), "dry_run なのに覚えた")
    many = {1: [r(100 + i, "failure", "f") for i in range(cw.RUNS)] + [r(5, "success", "5")]}
    code, out = go(Fake(d, [TEST], many))
    check(code == 1 and "git log 55555555..ffffffff" in out, f"読む数の外の緑を引かない: {out}")
    check(told(d) == [".github/workflows/test.yml:red:5"], f"鍵が最後の緑で決まらない: {told(d)}")
    code, out = go(Fake(setup(), [TEST], {1: [r(7, "failure", "a")]}))
    check(code == 1 and "1 度も緑になっていない" in out, f"緑の無い赤を書かない: {out}")
    hidden = {1: [r(200 + i, "cancelled", "c") for i in range(cw.RUNS)] + [r(7, "failure", "a"), r(6, "success", "0")]}
    code, out = go(Fake(setup(), [TEST], hidden))
    check(code == 1 and "run 7" in out and "git log 00000000..aaaaaaaa" in out, f"取り消しに埋もれた赤を見ない: {code} {out}")
    gone = {"id": 9, "name": "pages", "path": "dynamic/pages/pages-build-deployment", "state": "active"}
    code, out = go(Fake(setup(), [gone], {9: [r(7, "failure", "a")]}))
    check(code == 0, f"リポジトリに無い workflow を見た: {out}")
    print("RED_RANGE_OK")


def told_while_open():
    ask = {"kind": "ask", "status": "queued", "id": "20261019-000000-aaaaaa", "title": TITLE}
    d = setup([ask])
    fake = Fake(d, [TEST], {1: [r(7, "failure", "a"), r(6, "success", "0")]})
    check(go(fake)[0] == 1, "最初の赤を知らせない")
    code, out = go(fake)
    check(code == 0 and "知らせ済み" in out, f"頼みが開いているのに知らせ直した: {code} {out}")
    mutation = {"id": 2, "name": "mutation", "path": ".github/workflows/mutation.yml", "state": "active"}
    fake.workflows.append(mutation)
    fake.runs[2] = [r(20, "failure", "d", event="schedule")]
    code, out = go(fake)
    check(code == 1 and "mutation" in out and "test.yml" not in out, f"新しい件だけを知らせない: {out}")
    print("TOLD_WHILE_OPEN_OK")


def reopen_after_close():
    ask = {"kind": "ask", "status": "queued", "id": "20261019-000000-aaaaaa", "title": TITLE}
    d = setup([ask])
    fake = Fake(d, [TEST], {1: [r(7, "failure", "a", "2026-10-18T10:00:00Z"), r(6, "success", "0")]})
    go(fake)
    closed = datetime.datetime(2026, 10, 18, 11, 0, tzinfo=datetime.timezone.utc).timestamp()
    with open(os.path.join(d, *cw.deliver.INBOX, cw.deliver.LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "deliver", "ask": ask["id"], "at": closed}) + "\n")
    fake.runs[1].insert(0, r(8, None, "b", "2026-10-18T10:50:00Z", status="in_progress"))
    code, out = go(fake)
    check(code == 0, f"閉じた後に、戻しの run の決着を待たずに同じ赤を知らせ直した: {code} {out}")
    fake.runs[1][0] = r(8, "failure", "b", "2026-10-18T11:30:00Z")
    code, out = go(fake)
    check(code == 1 and "run 8" in out, f"閉じた後に決着した赤を知らせ直さない: {code} {out}")
    fake.runs[1].insert(0, r(9, "success", "c", "2026-10-18T12:00:00Z"))
    code, out = go(fake)
    check(code == 0 and told(d) == [], f"緑に戻った件を忘れない: {code} {out} {told(d)}")
    d = setup()
    fake = Fake(d, [TEST], {1: [r(7, "failure", "a"), r(6, "success", "0")]})
    go(fake)
    check(go(fake)[0] == 1, "頼みになった記録の無い件を知らせ直さない")
    print("REOPEN_AFTER_CLOSE_OK")


def age():
    d = setup()
    wfs = [{"id": 3, "name": "cover-moved", "path": ".github/workflows/cover-moved.yml", "state": "active"},
           {"id": 2, "name": "mutation", "path": ".github/workflows/mutation.yml", "state": "disabled_inactivity"}]
    weekly = [r(22, "success", "c", "2026-10-05T03:17:00Z", "schedule"), r(21, "success", "b", "2026-09-28T03:17:00Z", "schedule"),
              r(20, "success", "a", "2026-09-21T03:17:00Z", "schedule")]
    code, out = go(Fake(d, wfs, {2: weekly}))
    check(code == 1 and "gh workflow run cover-moved.yml" in out, f"回っていない workflow を知らせない: {out}")
    check("disabled_inactivity" in out and "gh workflow enable mutation.yml" in out, f"止められた workflow を知らせない: {out}")
    check("定期の run が止まっている" in out, f"古い定期の run を知らせない: {out}")
    fresh = [r(23, "success", "d", "2026-10-12T03:17:00Z", "schedule")] + weekly
    code, out = go(Fake(setup(), [dict(wfs[1], state="active")], {2: fresh}))
    check(code == 0, f"間隔の内の定期の run を止まったと見た: {out}")
    pushes = [r(300 + i, "success", "e", "2026-10-19T00:00:00Z") for i in range(cw.RUNS)]
    code, out = go(Fake(setup(), [dict(wfs[1], state="active")], {2: pushes + weekly}))
    check(code == 1 and "定期の run が止まっている" in out, f"push の run に埋もれた定期の run を見ない: {out}")
    print("AGE_OK")


def unreadable():
    code, out = go(Fake(setup(), [TEST], {}, broken=True))
    check(code == 1 and "読めなかった" in out and "HTTP 502" in out, f"gh の失敗を黙った: {code} {out}")
    for bad in ("[1]", "{"):
        code, out = go(Fake(setup(), [TEST], {}), bad)
        check(code == 2, f"読めない入力 {bad} を 2 で止めない: {code} {out}")
    print("UNREADABLE_OK")


def title():
    src = (ROOT / "works-dispatch" / "dispatch" / "calls.py").read_text(encoding="utf-8")
    check("\"title\": f\"ツール {role_name}/{tool['name']} が片づけられなかった仕事\"" in src,
          "works-dispatch の calls.hand_over が頼みに付ける題の形が変わった。tests/ci-watch.py の mine の見分けと TITLE を合わせる")
    print("TITLE_OK")


if __name__ == "__main__":
    {"red-range": red_range, "told-while-open": told_while_open, "reopen-after-close": reopen_after_close, "age": age,
     "unreadable": unreadable, "title": title}[sys.argv[1]]()
