"""rules/review-loop.py の _paste_copy と DIFF_FIXED_ARGS を、本物の git の小さなリポジトリで確かめる"""
import pathlib
import re
import subprocess
import types

import pytest

from conftest import PLUGIN
from engine import util
from engine.rules import load_rules
from engine.schema import load_graph

GRAPH = PLUGIN / "graphs" / "review-loop.json"
RULES = load_rules(GRAPH, load_graph(GRAPH)[0])
STATE_SCHEMA = load_graph(GRAPH)[0]["state_schema"]   # 写しの記録（diff_paste_log）は合わせ方の口（write_loop）で書く
read_room = 1000   # 台本の read_room_bytes


def sh(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def rows(n, fmt):
    return "".join(fmt.format(i) for i in range(n))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    sh(r, "init", "-q")
    sh(r, "config", "user.email", "t@example.com")
    sh(r, "config", "user.name", "t")
    (r / "code.py").write_text("x = 1\n", encoding="utf-8")
    (r / ".gitattributes").write_text("gen/** linguist-generated\n", encoding="utf-8")
    sh(r, "add", "-A")
    sh(r, "commit", "-qm", "base")
    base = sh(r, "rev-parse", "HEAD").strip()
    (r / "code.py").write_text("x = 2\ny = 3\n", encoding="utf-8")
    (r / "gen").mkdir()
    (r / "gen" / "big.json").write_text(rows(3000, '{{"row": {}}}\n'), encoding="utf-8")
    (r / "gen" / "small.json").write_text(rows(300, '{{"s": {}}}\n'), encoding="utf-8")
    (r / "new").mkdir()
    (r / "new" / "decl.json").write_text(rows(200, '{{"d": {}}}\n'), encoding="utf-8")
    (r / "lib.py").write_text(rows(400, "v{} = 0\n"), encoding="utf-8")
    # この差分が自分で宣言した生成データ（new/**）と、自分のコードを生成データと言い張る宣言（lib.py）
    (r / ".gitattributes").write_text("gen/** linguist-generated\nnew/** linguist-generated\nlib.py linguist-generated\n", encoding="utf-8")
    sh(r, "add", "-A")
    sh(r, "commit", "-qm", "next")
    snap = sh(r, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(util, "GIT_CWD", str(r))
    raw = subprocess.run(["git", "-C", str(r), "diff", *RULES.DIFF_FIXED_ARGS, base, snap], capture_output=True, check=True).stdout
    names = [n for n in sh(r, "diff", "--name-only", "-z", base, snap).split("\0") if n]
    return types.SimpleNamespace(root=r, base=base, snap=snap, raw=raw, names=names)


def board(tmp_path, budget, base=None):
    launch = {} if budget is None else {"input_budget_bytes": budget, "read_room_bytes": read_room}
    return types.SimpleNamespace(round=1, dir=tmp_path, loop_state={}, graph={"launch": launch, "state_schema": STATE_SCHEMA}, record={"base": base})


def full_copy(tmp_path, raw):
    f = tmp_path / "diff-r1.patch"
    f.write_bytes(raw)
    return f


def section(raw, path):
    return next(b"diff --git " + s for s in raw.split(b"diff --git ") if s.startswith(f"a/{path} ".encode()))


def paste(tmp_path, repo, budget):
    b = board(tmp_path, budget, repo.base)
    f = full_copy(tmp_path, repo.raw)
    got = pathlib.Path(RULES._paste_copy(b, repo.raw, f, repo.snap, repo.names))
    return b, f, got


def test_no_budget_declared_pastes_full(tmp_path, repo):
    b = board(tmp_path, None)
    f = full_copy(tmp_path, repo.raw)
    assert RULES._paste_copy(b, repo.raw, f, repo.snap, repo.names) == str(f)
    assert "diff_paste_log" not in b.loop_state


def test_within_budget_pastes_full(tmp_path, repo):
    b, f, got = paste(tmp_path, repo, len(repo.raw) + RULES.PASTE_ROOM + read_room)
    assert got == f and "diff_paste_log" not in b.loop_state


def test_over_budget_summarizes_base_generated_first(tmp_path, repo):
    # BASE が宣言した大きい生成データ 1 本を替えれば収まる予算——ほかは全文のまま
    big = section(repo.raw, "gen/big.json")
    b, f, got = paste(tmp_path, repo, len(repo.raw) - len(big) + 1000 + RULES.PASTE_ROOM + read_room)
    assert got != f and got.name == "diff-r1.paste.patch"
    body = got.read_text(encoding="utf-8")
    assert '"row": 2999' not in body and "+3000 -0 行" in body and "生成データ（BASE の宣言）" in body
    assert '"s": 299' in body and "+y = 3" in body and "+v399 = 0" in body
    assert f.read_bytes() == repo.raw
    row = b.loop_state["diff_paste_log"][0]
    assert [(x["path"], x["tier"]) for x in row["summarized"]] == [("gen/big.json", "base_generated")]
    assert row["still_over"] is False and row["paste_bytes"] == len(got.read_bytes()) <= row["limit"]


def test_every_summarized_section_is_readable_from_the_full_copy(tmp_path, repo):
    # 人の関所の答え（2026-09-27）の条件: 要約しても本文を見られなくなる周は無い——要約の行が示す行範囲が、全文の写しの
    # その節と 1 バイトも違わない（役が Read の offset/limit で読む範囲）
    b, f, got = paste(tmp_path, repo, RULES.PASTE_ROOM + read_room + 1500)
    lines = f.read_bytes().split(b"\n")
    body = got.read_text(encoding="utf-8")
    row = b.loop_state["diff_paste_log"][0]
    assert {x["path"] for x in row["summarized"]} >= {"gen/big.json", "gen/small.json", "new/decl.json", "lib.py"}
    for x in row["summarized"]:
        first, last = x["lines"]
        assert b"\n".join(lines[first - 1:last]) + b"\n" == section(repo.raw, x["path"]), x["path"]
        assert f"本文は Read で読める全文の {first}〜{last} 行目" in body


def test_stops_only_when_it_fits_or_nothing_is_left(tmp_path, repo):
    # どの予算でも: 収まったか、要約できる節（.gitattributes の外）を全部替えたか——先頭の注を勘定から外すと、収まる前に止まる
    sections = len([n for n in repo.names if n != ".gitattributes"])
    for cut in range(0, len(repo.raw), len(repo.raw) // 40):
        b, _, got = paste(tmp_path, repo, len(repo.raw) - cut + RULES.PASTE_ROOM + read_room)
        row = (b.loop_state.get("diff_paste_log") or [None])[0]
        if row:
            assert not row["still_over"] or len(row["summarized"]) == sections, (cut, row)
            assert row["still_over"] == (len(got.read_bytes()) > row["limit"])


def test_tiers_in_order_and_gitattributes_kept(tmp_path, repo):
    # BASE の宣言 → この差分の宣言 → そのほか。この差分が自分のコードを生成データと宣言しても BASE の生成データより先には替わらない
    b, _, got = paste(tmp_path, repo, RULES.PASTE_ROOM + read_room + 10)
    row = b.loop_state["diff_paste_log"][0]
    order = [(x["tier"], x["path"]) for x in row["summarized"]]
    assert order[:2] == [("base_generated", "gen/big.json"), ("base_generated", "gen/small.json")]
    assert [t for t, _ in order] == sorted((t for t, _ in order), key=RULES.PASTE_TIERS.index)
    assert ("diff_generated", "lib.py") in order and ("diff_generated", "new/decl.json") in order
    assert ".gitattributes" not in [p for _, p in order]
    assert section(repo.raw, ".gitattributes").decode("utf-8") in got.read_text(encoding="utf-8")   # 宣言の変更は本文で貼る
    assert row["still_over"] is True and "全部替えても" in row["why"]


def test_attr_unreadable_still_fits_by_the_last_tier(tmp_path, repo, monkeypatch):
    real = RULES.git
    monkeypatch.setattr(RULES, "git", lambda *a, **k: None if a[0] == "check-attr" else real(*a, **k))   # 古い git の形
    b, _, got = paste(tmp_path, repo, len(repo.raw) // 2 + RULES.PASTE_ROOM + read_room)
    row = b.loop_state["diff_paste_log"][0]
    assert "check-attr" in row["why"] and row["still_over"] is False
    assert {x["tier"] for x in row["summarized"]} == {"other"} and row["summarized"][0]["path"] == "gen/big.json"


def test_quoted_header_path_is_found(tmp_path, repo):
    # 非 ASCII を含むパスは、git が見出しを C の書き方でクオートする（core.quotePath の既定）。
    # " と \\ は Windows のファイル名に使えないので、綴りの組み立てだけを直に見る
    assert RULES._header_tails('a"\\b\t')[1] == b' "b/a\\"\\\\b\\t"'
    odd = "gen/日本 語.json"
    (repo.root / odd).write_text(rows(2000, "{}\n"), encoding="utf-8")
    sh(repo.root, "add", "-A")
    sh(repo.root, "commit", "-qm", "odd")
    snap = sh(repo.root, "rev-parse", "HEAD").strip()
    raw = subprocess.run(["git", "-C", str(repo.root), "diff", *RULES.DIFF_FIXED_ARGS, repo.base, snap], capture_output=True, check=True).stdout
    assert b'"b/gen/' in raw                                     # 前提: 見出しがクオートされている
    names = [n for n in sh(repo.root, "diff", "--name-only", "-z", repo.base, snap).split("\0") if n]
    b = board(tmp_path, len(raw) - len(section(raw, "gen/big.json")) + RULES.PASTE_ROOM + read_room, repo.base)
    RULES._paste_copy(b, raw, full_copy(tmp_path, raw), snap, names)
    assert odd in [x["path"] for x in b.loop_state["diff_paste_log"][0]["summarized"]]


@pytest.mark.parametrize("key,value", [("diff.noprefix", "true"), ("diff.mnemonicPrefix", "true"), ("color.ui", "always"),
                                       ("diff.relative", "true")])
def test_user_git_config_does_not_change_the_copy(tmp_path, repo, monkeypatch, key, value):
    # 利用者の設定のまま撮ると、見出しの前置き・色・範囲が変わって節を名前で引けず、生成データが先に替わらない
    sh(repo.root, "config", key, value)
    if key == "diff.relative":   # 相対の範囲に効くのは git の cwd がサブディレクトリのとき（inputs.cwd はそうでありうる）
        monkeypatch.setattr(util, "GIT_CWD", str(repo.root / "new"))
    monkeypatch.setattr(RULES, "_freeze_revision", lambda b: repo.snap)
    b = board(tmp_path, len(repo.raw) - len(section(repo.raw, "gen/big.json")) + 1000 + RULES.PASTE_ROOM + read_room, repo.base)
    b.cond = lambda name, overlay=None: (False, "")
    d = RULES._take_diff(b)
    assert d["ok"] and d["raw"] == repo.raw
    assert [(x["path"], x["tier"]) for x in b.loop_state["diff_paste_log"][0]["summarized"]] == [("gen/big.json", "base_generated")]
    # 貼る写しは差分の一式（節の出力の snapshot。hist.snapshot・hist.after_fix が読む）に載り、全文の写しとは別のファイル
    snap = d["snapshot"]
    assert snap["paste_file"] == b.loop_state["diff_paste_log"][0]["file"] != snap["diff_file"]


def test_diff_attributes_are_read_from_base(tmp_path, repo, monkeypatch):
    # 差分が自分の .gitattributes で自分のコードを -diff にしても、全部の役の差分から本文が消えない（GIT_ATTR_SOURCE は git 2.42 から。
    # 古い git は作業ツリーの属性で描く——その形も見て、どちらの版でも黙って変わらないことを確かめる）
    (repo.root / ".gitattributes").write_text("code.py -diff\n", encoding="utf-8")
    sh(repo.root, "add", "-A")
    sh(repo.root, "commit", "-qm", "hide")
    snap = sh(repo.root, "rev-parse", "HEAD").strip()
    monkeypatch.setattr(RULES, "_freeze_revision", lambda b: snap)
    b = board(tmp_path, None, repo.base)
    b.cond = lambda name, overlay=None: (False, "")
    raw = RULES._take_diff(b)["raw"]
    ver = tuple(int(x) for x in re.findall(r"\d+", sh(repo.root, "version"))[:2])
    assert (b"+y = 3" in raw) == (ver >= (2, 42)) and (b"Binary files" in raw) == (ver < (2, 42))


def test_added_md_links_read_attributes_from_base(tmp_path, repo):
    # リンクの検査も本文を読む git diff——差分が *.md -diff を足しても、足したリンクが検査から消えない（git 2.42 未満は今の形）
    (repo.root / "doc.md").write_text("# t\n", encoding="utf-8")
    sh(repo.root, "add", "-A")
    sh(repo.root, "commit", "-qm", "doc")
    base = sh(repo.root, "rev-parse", "HEAD").strip()
    (repo.root / "doc.md").write_text("# t\n[x](nowhere.md)\n", encoding="utf-8")
    (repo.root / ".gitattributes").write_text("*.md -diff\n", encoding="utf-8")
    got = RULES._added_md_links(base, str(repo.root))
    ver = tuple(int(x) for x in re.findall(r"\d+", sh(repo.root, "version"))[:2])
    assert (("doc.md", 2, "nowhere.md", None) in got) == (ver >= (2, 42)), got


def test_notices_name_the_summarized_rows(tmp_path):
    b = types.SimpleNamespace(state={}, loop_state={"diff_paste_log": [
        {"round": 2, "diff": "diff-r2-after-fix.patch", "bytes": 3, "limit": 1, "still_over": False,
         "summarized": [{"path": "gen/a.json", "added": 1, "deleted": 0, "bytes": 2, "lines": [1, 3], "tier": "base_generated"},
                        {"path": "lib.py", "added": 1, "deleted": 0, "bytes": 2, "lines": [4, 6], "tier": "other"}]},
        {"round": 2, "diff": "diff-r2.patch", "bytes": 3, "limit": 1, "still_over": True, "summarized": [],
         "why": "要約できる節を全部替えても予算を超える——起こすのは止めない"}]})
    got = [n for n in RULES.notices(b) if "予算" in n]
    assert len(got) == 2 and "gen/a.json" in got[0] and "修正後の写しは r2.compare" in got[0] and "Read で読む" in got[0]
    assert "生成データ（BASE の宣言） 1・差分 1" in got[0] and "全部替えても" in got[1]


def test_graph_declares_budget_room_and_read_file():
    g = load_graph(GRAPH)[0]
    launch = g["launch"]
    assert launch["input_budget_bytes"] - RULES.PASTE_ROOM - launch["read_room_bytes"] > 0
    for nid, snap in (("p1.hygiene", "snapshot"), ("r2.compare", "after_fix")):
        n = g["nodes"][nid]
        assert (f"file:hist.{snap}.paste_file" in n["reads"] and f"file:hist.{snap}.diff_file" not in n["reads"]
                and n["read_file"] == f"hist.{snap}.diff_file")
