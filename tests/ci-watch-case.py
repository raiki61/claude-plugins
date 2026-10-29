#!/usr/bin/env python3
"""tests/ci-watch.py（役「CI の見張り」のツール）を、gh と git を偽物の runner にし、受付箱の台帳を一時の階層に作って回す。

使い方: python3 tests/ci-watch-case.py <場合>
- red-range: main の最新の決着した run が赤なら 1 で終わり、run の URL と、最後の緑から最新の赤までの commit の範囲を出す。取り消しの
  run は決着に数えない。読む数の中に緑が無ければ、成功の run を別に引く。1 度も緑が無ければそう書く。dry_run は覚えない
  読む数の全部が取り消しなら、決着ごとに最新を引いて赤を見る。リポジトリにファイルの無い workflow は見ない
- told-while-open: 知らせた件は、このツールから回した頼みが開いているうちは知らせない（0 で終わる）。新しい件だけは知らせる。
  開いた頼みのうち一番新しい物を回してから REPEAT を過ぎたら、開いた頼みの受付を添えて知らせ直す（回した時刻の無い頼みでは黙る）
- cross: 頼み元がほかの会社の会話で、納品の行がその会社の受付箱にだけ在る頼みは、--todo と同じく台帳の行が指す受付箱まで足し合わせて
  閉じたとみる（自分の受付箱だけ見て開いているとみて黙り続けない）
- reopen-after-close: 頼みが閉じた（納品された）後は、閉じた後に決着した赤の run が在るときだけ知らせ直す（戻しの run が決着する
  前は黙る）。閉じた記録の無い件は知らせ直す。緑に戻った件は忘れる。頼みが直しをほかの部署へ回して閉じたら（cause がその頼みを
  指す頼み。孫まで）、回した頼みが開いている間は黙り、全部閉じた後に決着した赤だけ知らせ直す
- age: 1 度も回っていない workflow・止められた workflow・間隔と 1 日より古い定期の run を知らせる。定期の run は、push の run が
  読む数を埋めても別に引く
- unreadable: gh が落ちたら黙らず 1 で知らせる。入力が JSON のオブジェクトでなければ 2
- limited: gh が GitHub の利用制限で断られた回は 0 で黙り、当たり始めた時刻を覚える（覚えた件は消さない。dry_run は覚えない）。
  REPEAT を過ぎても続けば 1 で知らせて時刻を替え、読めた回は時刻を消す
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


def r(i, conclusion, sha, at="2026-10-18T10:00:00Z", event="push", status="completed", updated=None):
    return {"databaseId": i, "status": status, "conclusion": conclusion, "event": event, "headSha": sha * 8, "createdAt": at,
            "updatedAt": updated or at, "url": f"https://example.invalid/runs/{i}"}


class Fake:
    """gh と git の偽物。workflows は gh workflow list の答え、runs は workflow の id ごとの run（新しい順）。"""

    def __init__(self, gitdir, workflows, runs, broken=False, err="HTTP 502"):
        self.gitdir, self.workflows, self.runs, self.broken, self.err = gitdir, workflows, runs, broken, err
        self.places = {}   # git -C <場所> の共通のディレクトリの答えを場所ごとに替える物（無い場所は gitdir）

    def __call__(self, argv):
        if argv[0] == "git":
            return 0, self.places.get(argv[2], self.gitdir) + "\n", ""
        if self.broken:
            return 1, "", self.err
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


def go(fake, value="{}", now=NOW):
    out = io.StringIO()
    old, sys.stdout = sys.stdout, out
    try:
        code = cw.main(stdin=io.StringIO(value), runner=fake, now=now)
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
    check(out.strip().splitlines()[-1].startswith("main の CI に、知らせる物が"), f"数の行が最後に無い: {out}")
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
    # 回した時刻が在り、REPEAT の内なら黙り、過ぎたら同じ件を、開いた頼みの受付を添えて知らせ直す
    old = {"kind": "ask", "status": "queued", "id": "20261017-000000-bbbbbb", "title": TITLE,
           "at": (NOW - cw.REPEAT - datetime.timedelta(hours=2)).timestamp()}
    new = dict(old, id="20261019-000000-cccccc", at=(NOW - cw.REPEAT + datetime.timedelta(hours=2)).timestamp())
    d = setup([old, new])
    fake = Fake(d, [TEST], {1: [r(7, "failure", "a"), r(6, "success", "0")]})
    go(fake)
    code, out = go(fake)
    check(code == 0 and f"{datetime.datetime.fromtimestamp(new['at'], datetime.timezone.utc) + cw.REPEAT:%Y-%m-%d %H:%M} UTC" in out,
          f"回してから REPEAT の内の頼みが開いているのに知らせ直した: {code} {out}")
    d = setup([new | {"at": old["at"]}, old])
    fake = Fake(d, [TEST], {1: [r(7, "failure", "a"), r(6, "success", "0")]})
    go(fake)
    code, out = go(fake)
    check(code == 1 and "run 7" in out and old["id"] in out and new["id"] in out and "--withdraw" in out,
          f"開いたまま REPEAT を過ぎた頼みの件を知らせ直さない: {code} {out}")
    check("--withdraw" not in out.strip().splitlines()[-1], f"数の行が最後に無い: {out}")
    print("TOLD_WHILE_OPEN_OK")


def cross():
    # 頼み元の会社の受付箱を、行の boss.inbox（受付箱を直に指す）と from.place（作業場から git で引く）の 2 つの道で指す
    for via in ("boss", "place"):
        place = tempfile.mkdtemp(prefix="ci-watch-place-")   # 頼み元の会社の作業場
        other = cw.deliver.inbox_of(os.path.join(place, ".git"))
        os.makedirs(other)
        ask = {"kind": "ask", "status": "queued", "id": "20261019-000000-aaaaaa", "title": TITLE,
               "at": datetime.datetime(2026, 10, 19, 11, 0, tzinfo=datetime.timezone.utc).timestamp()}
        ask.update({"boss": {"inbox": other}} if via == "boss" else {"from": {"place": place}})
        d = setup([ask])
        fake = Fake(d, [TEST], {1: [r(7, "failure", "a", "2026-10-18T10:00:00Z"), r(6, "success", "0")]})
        fake.places[place] = os.path.dirname(os.path.dirname(other))
        go(fake)
        code, out = go(fake)
        check(code == 0 and "run 7" not in out, f"{via}: 納品の無い頼みを閉じたとみた: {code} {out}")
        with open(os.path.join(other, cw.deliver.LOG), "w", encoding="utf-8") as f:   # 納品の行は頼み元の会社の受付箱にだけ在る
            f.write(json.dumps({"kind": "deliver", "ask": ask["id"], "at": ask["at"] + 600}) + "\n")
        fake.runs[1].insert(0, r(8, "failure", "b", "2026-10-19T11:30:00Z"))
        code, out = go(fake)
        check(code == 1 and "run 8" in out, f"{via}: ほかの会社の受付箱にだけ納品が在る頼みを開いているとみた: {code} {out}")
    print("CROSS_OK")


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
    # 閉じる前に始まり、閉じた後に赤で決着した run(戻しを push してすぐ納品した)。知らせられなかった納品は閉じたに数えない
    with open(os.path.join(d, *cw.deliver.INBOX, cw.deliver.LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "deliver", "ask": ask["id"], "status": "failed", "at": closed + 2700}) + "\n")
        f.write(json.dumps({"kind": "deliver", "ask": ask["id"], "for": "x", "at": closed + 2800}) + "\n")
    fake.runs[1][0] = r(8, "failure", "b", "2026-10-18T10:50:00Z", updated="2026-10-18T11:30:00Z")
    code, out = go(fake)
    check(code == 1 and "run 8" in out, f"閉じた後に決着した赤を知らせ直さない: {code} {out}")
    fake.runs[1].insert(0, r(9, "success", "c", "2026-10-18T12:00:00Z"))
    code, out = go(fake)
    check(code == 0 and told(d) == [], f"緑に戻った件を忘れない: {code} {out} {told(d)}")
    d = setup()
    fake = Fake(d, [TEST], {1: [r(7, "failure", "a"), r(6, "success", "0")]})
    go(fake)
    check(go(fake)[0] == 1, "頼みになった記録の無い件を知らせ直さない")
    # 閉じた頼みが直しをほかの部署へ回していれば（cause がその頼みを指す頼み。孫まで）、回した頼みが開いている間は、閉じた後に決着した
    # 赤も黙る。回した頼みが全部閉じた後は、その後に決着した赤だけ知らせ直す
    def log(*rows):
        with open(os.path.join(d, *cw.deliver.INBOX, cw.deliver.LOG), "a", encoding="utf-8") as f:
            f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
    at = lambda hm: datetime.datetime(2026, 10, 19, *hm, tzinfo=datetime.timezone.utc).timestamp()
    d = setup([ask])
    fake = Fake(d, [TEST], {1: [r(7, "failure", "a", "2026-10-18T10:00:00Z"), r(6, "success", "0")]})
    go(fake)
    child = {"kind": "ask", "status": "sent", "id": "20261019-000000-bbbbbb", "title": "直しの頼み", "cause": ask["id"], "at": at((9, 0))}
    grand = {"kind": "ask", "status": "queued", "id": "20261019-000000-cccccc", "title": "直しの続き", "cause": child["id"], "at": at((9, 5))}
    log(child, grand, {"kind": "deliver", "ask": ask["id"], "at": at((9, 0))})
    fake.runs[1].insert(0, r(8, "failure", "b", "2026-10-19T08:00:00Z", updated="2026-10-19T09:30:00Z"))
    code, out = go(fake)
    check(code == 0, f"直しを回した頼みが開いているのに、閉じた後に決着した赤を知らせ直した: {code} {out}")
    log({"kind": "deliver", "ask": child["id"], "at": at((9, 10))})
    code, out = go(fake)
    check(code == 0, f"孫の頼みが開いているのに、知らせ直した: {code} {out}")
    log({"kind": "deliver", "ask": grand["id"], "at": at((11, 0))})
    code, out = go(fake)
    check(code == 0, f"回した頼みが閉じる前に決着した赤を、閉じた後に知らせ直した: {code} {out}")
    fake.runs[1].insert(0, r(9, "failure", "c", "2026-10-19T11:00:00Z", updated="2026-10-19T11:30:00Z"))
    code, out = go(fake)
    check(code == 1 and "run 9" in out, f"回した頼みが全部閉じた後に決着した赤を知らせ直さない: {code} {out}")
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


def limited():
    # 2 次の制限の文は GitHub の答えの形（頭に "rate limit" が在り、末尾の 300 字には残らない長さ）
    err = ("gh: You have exceeded a secondary rate limit. Please wait a few minutes before you try again. If you reach out to GitHub "
           "Support for help, please include the request ID 0000:0000:0000000:0000000:00000000 and timestamp 2026-10-28 23:45:16 UTC. "
           "For more on scraping GitHub and how it may affect your rights, please review our Terms of Service "
           "(https://docs.github.com/en/site-policy/github-terms/github-terms-of-service) (HTTP 403)")
    d = setup()
    with open(os.path.join(d, cw.STATE), "w", encoding="utf-8") as f:
        json.dump({"told": ["a:red:1"]}, f)
    state = lambda: json.load(open(os.path.join(d, cw.STATE), encoding="utf-8"))
    code, out = go(Fake(d, [TEST], {}, broken=True, err=err), '{"dry_run": true}')
    check(code == 0 and "limited" not in state(), f"dry_run の利用制限で時刻を覚えた: {code} {out} {state()}")
    code, out = go(Fake(d, [TEST], {}, broken=True, err=err))
    check(code == 0 and "secondary rate limit" in out and state() == {"told": ["a:red:1"], "limited": NOW.timestamp()},
          f"利用制限を黙って覚えない: {code} {out} {state()}")
    code, out = go(Fake(d, [TEST], {}, broken=True, err=err), now=NOW + cw.REPEAT)
    check(code == 0 and state()["limited"] == NOW.timestamp(), f"REPEAT のうちに知らせたか、当たり始めた時刻を替えた: {code} {out} {state()}")
    later = NOW + cw.REPEAT + datetime.timedelta(hours=1)
    code, out = go(Fake(d, [TEST], {}, broken=True, err=err), now=later)
    check(code == 1 and "secondary rate limit" in out and state()["limited"] == later.timestamp(), f"REPEAT を過ぎた利用制限を黙った: {code} {out} {state()}")
    code, out = go(Fake(d, [TEST], {}, broken=True, err="HTTP 403: Resource not accessible by integration"), now=later)
    check(code == 1 and "HTTP 403" in out and state()["limited"] == later.timestamp(), f"利用制限でない 403 を黙った: {code} {out}")
    code, out = go(Fake(d, [], {}), now=later)
    check(code == 0 and "limited" not in state(), f"読めた回に利用制限の時刻を消さない: {code} {out} {state()}")
    print("LIMITED_OK")


def title():
    src = (ROOT / "works-dispatch" / "dispatch" / "calls.py").read_text(encoding="utf-8")
    check("\"title\": f\"ツール {role_name}/{tool['name']} が片づけられなかった仕事\"" in src,
          "works-dispatch の calls.hand_over が頼みに付ける題の形が変わった。tests/ci-watch.py の mine の見分けと TITLE を合わせる")
    print("TITLE_OK")


if __name__ == "__main__":
    {"red-range": red_range, "told-while-open": told_while_open, "cross": cross, "reopen-after-close": reopen_after_close, "age": age,
     "unreadable": unreadable, "limited": limited, "title": title}[sys.argv[1]]()
