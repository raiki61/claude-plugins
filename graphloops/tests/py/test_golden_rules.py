"""規則（rules/*.py）の今の振る舞いを、実在の盤面と筋書きの台本の途中の状態から作った固定具の上で固定する特徴づけのテスト。

手順 3 の作り替え（規則の形を変えるが振る舞いは変えない）の安全網。固定具と期待値は graphloops/tests/golden_make.py が作る
（期待値を手で書かない。人が書くのは既知のずれの台帳 golden/known_deviations.json だけ）。どの本番の変更で赤くなるか:
- contract（外の約束）: 条件の真偽と理由が変わって節の走らせる判断が変わる・受け付けの可否か拒む理由が変わる・機械の節が別の
  次の節や問いを出す・記録（record.json）に書く値が変わる・周の印（done・na と理由）が変わる。作り替えの run はこれを変えてはならない
  （台帳に載った方針からのずれだけは、規則を方針どおりに直す run が台帳と一緒に変える）
- internal（内部の形）: 規則の表の名前ごとの返り・loop の状態の鍵・機械の節の出力の形が変わる。作り替えで作り直してよい
  （`golden_make.py expect`。差分は審査に出る）
- 観察の落ち方（classify_breaks の札ごと）: 固定具の欠け（宣言に在る欄が固定具に無いための die）・宣言に帰着できない壊れ
  （想定外の例外・例外 <型>・開けない・欄の解決以外の die）・台帳（known_deviations.json）と合わない方針からのずれ
- 固定具の形（shape.json）: 固定具を今の宣言で照らした違反の数えが変わった（観察の前に、どの固定具かが出る）
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


# 下の 3 本は赤の名前で原因の見当を分ける。期待値のファイルでなく今の観察を見る（期待値は作り直すまで古い）
@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_no_fixture_gap_in_observation(path, observed):
    gap = ga.classify_breaks(ga.load_fixture(path), observed(path))["gap"]
    assert not gap, f"固定具の欠け（宣言に在る欄が固定具に無いための die。固定具を集め直せ）: {gap[:3]}"


@pytest.mark.parametrize("path", FIXTURES, ids=IDS)
def test_no_unattributed_break_in_observation(path, observed):
    bad = ga.classify_breaks(ga.load_fixture(path), observed(path))["unattributed"]
    assert not bad, f"宣言に帰着できない壊れ（規則の欠陥か、コードが添字で読む欄・記録の欠け）: {bad[:3]}"


def test_known_deviations_match_ledger(observed):
    """実在の盤面で方針からずれた落ち方は、既知のずれの台帳（known_deviations.json）と両向きで一致する——台帳に無いずれは
    新しいずれ、観察に出ない台帳の行は規則が直った印（台帳と期待値を作り直す）"""
    import fnmatch
    rows = ga.known_deviations()
    seen, unlisted = set(), []
    for p in FIXTURES:
        for path in ga.classify_breaks(ga.load_fixture(p), observed(p))["deviation"]:
            hit = [i for i, r in enumerate(rows)
                   if any(fnmatch.fnmatch(ga.fixture_id(p), f) for f in r["fixtures"]) and path in r["paths"]]
            seen.update(hit)
            if not hit:
                unlisted.append((ga.fixture_id(p), path))
    assert not unlisted, f"台帳に無い方針からのずれ: {sorted(set(unlisted))[:5]}"
    gone = [r for i, r in enumerate(rows) if i not in seen]
    assert not gone, f"観察に出ない台帳の行（規則が直ったなら台帳から消し、期待値を作り直せ）: {gone}"


def test_fixture_shape_matches_expect():
    """固定具を今の宣言で照らした違反の数えが、期待値の shape.json と等しい（観察を回さない）。違えば、宣言か固定具が変わった
    ——どの固定具が古くなったかがここで先に出る（golden_make.py expect で作り直し、差分は審査に出る）"""
    diff = ga.shape_diff()
    assert not diff, f"固定具の形が期待値と違う（{len(diff)} 件）: {json.dumps(dict(list(diff.items())[:2]), ensure_ascii=False)[:600]}"


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
