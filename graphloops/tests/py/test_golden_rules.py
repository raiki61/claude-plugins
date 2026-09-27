"""規則（rules/*.py）の今の振る舞いを、実在の盤面と筋書きの台本の途中の状態から作った固定具の上で固定する特徴づけのテスト。

手順 3 の作り替え（規則の形を変えるが振る舞いは変えない）の安全網。固定具と期待値は graphloops/tests/golden_make.py が作る
（期待値を手で書かない）。どの本番の変更で赤くなるか:
- contract（外の約束）: 条件の真偽と理由が変わって節の走らせる判断が変わる・受け付けの可否か拒む理由が変わる・機械の節が別の
  次の節や問いを出す・記録（record.json）に書く値が変わる・周の印（done・na と理由）が変わる。作り替えの run はこれを変えてはならない
- internal（内部の形）: 規則の表の名前ごとの返り・loop の状態の鍵・機械の節の出力の形が変わる。作り替えで作り直してよい
  （`golden_make.py expect`。差分は審査に出る）
- 覆いの一覧（golden/expect/coverage.json）: 規則の表とフックの名前が増えた・消えた・覆いが変わったのに一覧が古い
- 衛生: 固定具・期待値に家のパス・利用者名・秘密が入った、固定具が上限を超えた
"""
import json

import pytest

import golden_adapter as ga

FIXTURES = ga.fixture_paths()
IDS = [f"{p.parent.name}/{p.stem}" for p in FIXTURES]


@pytest.fixture(scope="module")
def observed(tmp_path_factory):
    cache = {}

    def get(path):
        if path not in cache:
            obs, _ = ga.observe(ga.load_fixture(path), tmp_path_factory.mktemp("golden"))
            cache[path] = ga.jsonable(obs)
        return cache[path]
    return get


def _expected(layer, path):
    return ga.platform_norm(json.loads(ga.expect_path(layer, path).read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_contract(path, observed):
    assert observed(path)["contract"] == _expected("contract", path)


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_internal(path, observed):
    assert observed(path)["internal"] == _expected("internal", path)


def test_every_fixture_has_both_layers_and_no_orphans():
    """期待値の欠け（固定具に期待値が無い）と余り（固定具の無い期待値）の両方を赤にする"""
    names = {(p.parent.name, p.name) for p in FIXTURES}
    assert names, "固定具が 1 つも無い（網が空）"
    for layer in ("contract", "internal"):
        got = {(p.parent.name, p.name) for p in (ga.GOLDEN / "expect" / layer).glob("*/*.json")}
        assert got == names, f"{layer}: 欠け {sorted(names - got)} ／ 余り {sorted(got - names)}"
    loops = {p.parent.name for p in FIXTURES}
    assert loops == set(ga.LOOPS), f"固定具の無いループ: {sorted(set(ga.LOOPS) - loops)}"


def test_coverage_accounts_for_every_public_name():
    """母集団（読み込んだ規則の 6 つの表とフック）の全部の名前が覆いの一覧に在り、一覧は期待値から機械で出した物と同じ"""
    cov = json.loads((ga.GOLDEN / "expect" / "coverage.json").read_text(encoding="utf-8"))
    assert sorted(cov) == sorted(ga.LOOPS)
    for loop in ga.LOOPS:
        pop = ga.population(loop)
        assert {t: sorted(rows) for t, rows in cov[loop].items()} == pop, f"{loop}: 一覧の名前が規則の表・フックと合わない"
        calls = [_expected("internal", p).get("calls", []) for p in FIXTURES if p.parent.name == loop]
        assert ga.coverage(loop, calls) == cov[loop], f"{loop}: 覆いの一覧が期待値から出した物と違う（golden_make.py expect で作り直せ）"


def test_fixtures_are_small_and_clean():
    files = sorted(ga.GOLDEN.rglob("*.json"))
    assert files
    for p in files:
        text = p.read_text(encoding="utf-8")
        assert not ga.forbidden_in(text), f"{p.relative_to(ga.GOLDEN)} に禁じる形: {ga.forbidden_in(text)[:3]}"
        if "fixtures" in p.relative_to(ga.GOLDEN).parts:
            assert len(text.encode("utf-8")) <= ga.size_limit, f"{p.relative_to(ga.GOLDEN)} が {len(text.encode('utf-8'))} バイト"


def test_frozen_clock_ignores_the_machine_time_zone():
    """固めた時計を手元の時差に寄せても（util.now の形）、走らせる機械の TZ に依らず FROZEN_NOW になる——CI の UTC で
    記録の時刻だけが +00:00 に変わり、固定具を作った機械と突き合わせが割れた（2026-09-27）"""
    got = ga._FrozenDateTime.now().astimezone().isoformat(timespec="seconds")
    assert got == ga.FROZEN_NOW


def test_windows_paths_are_tokened_and_written_as_json(tmp_path, monkeypatch):
    """Windows の区切り（\\）の置き場も、JSON の文字列に埋めた形（engine が標準出力に出す JSON の本文・repr の Errno の文）まで
    印に戻り、JSON の本文のファイルには JSON として読める綴りで埋まる。/ の OS でも Windows の形で確かめる（CI の Windows で
    実パスが印に戻らず、埋めた返答を engine が JSON として読めなかった。2026-09-27）"""
    place = ga.Place(tmp_path)
    win = "C:\\Users\\u\\board"
    place.to_real = [("<RUN>", win)]
    place.to_real_json = [("<RUN>", json.dumps(win)[1:-1])]
    place.to_token = sorted(((f, "<RUN>") for f in ga._forms(win)), key=lambda x: -len(x[0]))
    out = json.dumps({"dir": win + "\\out.json"})
    assert place.token(out) == json.dumps({"dir": "<RUN>\\out.json"})
    files = place.real_files({"a.txt": {ga.TEXT_KEY: '{"lane": "<RUN>/lanes/x.json"}'}, "b.txt": {ga.TEXT_KEY: "<RUN> は JSON でない"}})
    assert json.loads(files["a.txt"][ga.TEXT_KEY])["lane"] == win + "/lanes/x.json"
    assert files["b.txt"][ga.TEXT_KEY] == win + " は JSON でない"
    monkeypatch.setattr(ga.os, "sep", "\\")
    assert ga.platform_norm({"out": json.dumps({"record": "<RUN>\\record.json"})}) == {"out": json.dumps({"record": "<RUN>/record.json"})}
