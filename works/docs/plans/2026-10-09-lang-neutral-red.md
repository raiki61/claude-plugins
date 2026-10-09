# 赤緑の読みを言語に依らない形へ（全体の計画の段 1.1・1.2 と決め 2）

## 平たく言うと（3 行）

- 何の話か: works が Python 以外の対象を直す時に、試験の選び・既存のテストの凍結・赤の確かめが黙って外れる穴を塞ぎ、赤の理由を CPython の例外の名でなく言語に依らない形で読む。
- やること: (1) 表に無い拡張子をコードと見る (2) テストのファイルを宣言と事実上の名の慣習で見分ける (3) 赤が error・一式に居ない時は読むだけの役が理由を決め、機械が引用の実在を確かめる (4) keep-essence の 1 の文を合わせる。
- 止め時: 1 つの手順が見込みより大きければ、前の手順を済ませて止め、報告する（依頼の決まり）。

状態: 手順 1・2 は済み（枝 wip/lang-neutral）。手順 3・4 は見積もりが手順 1・2 の数倍になったので入らずに止め、設計を報告した（下の手順 3）。2026-10-09、main 04137594（0.2.52）の事実で書いた。全体の計画 `docs/plans/2026-10-09-clean-whole.md`（枝 wip/roadmap）の段 1 の Task 1.1・1.2 と決め 2（持ち主 2026-10-09「もちろん言語に依らない方がいい」）。棚卸しは `docs/language-neutral-inventory.md` の束 D2（4-1・4-3・4-7）と 4-5・4-6・5-3。

**目的:** Python で今ある守りを 1 つも緩めずに、ほかの言語の対象で守りが黙って空になる所を無くす。

**作り:** 言語の表を足さない。拡張子の既定を「分からない＝コード（全部を回す）」に反転し、テストのファイルは修正案と役の宣言を正本、事実上の名の慣習（テストの実行器が自分で探す名の形）を予備にする。慣習の置き場は今ある 1 か所（`.shared/core/impact.py` の `is_test`）だけにし、`blk-fix` はそれを呼ぶ。

**道具:** Python 3.12（標準ライブラリだけ）・unittest・git。

## 考えの棚卸し（知る場所: 前 → 後）

| 考え | 前 | 後 |
| --- | --- | --- |
| 文書かコードか | `impact._lang`（表の外は文書） | 同じ所（表の外はコード） |
| テストのファイルの名の慣習 | `impact.TEST_NAME`・`tddloop.TEST_FILE`（.py だけ）・`tddloop.PYTEST_FILE`・`blk-plan/lib/ripple.py` の `is_test` | `impact.is_test`・`tddloop.PYTEST_FILE`（実行器の引数の都合。束 D1 で外す） |
| 文書と宣言する口 | 無い | `impact._declared_docs`（git の属性 `linguist-documentation`） |
| 宣言されたテストのファイル | 単位の `test_files` だけ（ハッシュの凍結） | `tddloop.declared_test_files`（単位の申告・約束の tests と rewrites のパス） |
| 赤の理由 | `tddloop.NAME_KINDS`・写しの `red_problems`（error を拒む） | 手順 3（下） |

`entry.GATE_FILE_PATTERNS`（ゲートの定義のファイル。CI・lint の設定まで含む別の考え）は触らない。

## 手順

### 手順 1: 表に無い拡張子をコードと見る（`.shared/core/impact.py` の `_lang`）

- [ ] 赤: `tests/test_impact.py` に `test_unknown_extension_selects_tests`（`.zig` のファイルを起点にすると `all_tests_required` が真で理由に `unknown-language`）と、`test_known_doc_and_dotfile_stay_doc`（`.md`・`.jsonl`・`.gitignore`・拡張子の無い `LICENSE` は文書のまま）
- [ ] 入れる: 拡張子が在り `DOC_EXT` に無い物は `unknown`（読めないコード）。`DOC_EXT` にデータの形 `jsonl`・`ndjson` を足す。ドットで始まり他に点の無い名（`.gitignore` など）と、拡張子もシバンも無い名は今どおり文書
- [ ] 緑・commit

### 手順 2: テストのファイルを宣言と慣習で見分ける

- [ ] 赤: `tests/test_impact.py` の `test_is_test_by_cross_ecosystem_convention`（`FooTest.java`・`foo_spec.rb`・`foo_test.zig`・`FooTests.cs` が module、`test_data.json`・`test_notes.md` は module でない）。`tests/test_blk_fix_tdd.py` に `test_frozen_test_file_non_python`（直しの段で単位の外の既存の `.go` のテストのファイルの行を消すと拒む・足すだけは通す）・`test_declared_test_file_counts`（慣習に当たらない名でも約束の tests が名指したファイルはテストのファイル）・`test_vanish_scope_non_python_is_whole`（.py でないテストのファイルに触れたら一式の全部）
- [ ] 入れる:
  - `impact.is_test(path)`: 今の名の型に、語の頭・尾の慣習（`test_*`・`*_test`・`*.spec`・`*.test`。実装の名と重なる `*_spec`・`*Test`・`*Tests`・`*Spec`・`*IT` はテストのフォルダの下だけ）を、Python でも文書でも設定でもない拡張子の時だけ足す（審査で、実装の `tensor_spec.py`・`KeySpec.java` をテストと見て凍らせる形を見つけて狭めた）。訳: これは各実行器が自分で探す名の形（pytest の python_files・go test・Jest の testMatch・RSpec・Maven の surefire と failsafe）で、言語ごとの表でなく名の形 1 つ
  - `tddloop.declared_test_files(st) -> set[str]`・`tddloop.is_test_file(path, declared) -> bool`（宣言に在るか `impact.is_test(path) == "module"`）。`TEST_FILE` を消し、`_moved_test_files`・`fixgates._test_files` はこれを呼ぶ
  - `_vanish_scope`: .py でないテストのファイルに触れたら `None`（一式の全部。JUnit の行とファイルを言語に依らず結べないので、分からない＝全部を見る）
  - `_other_test_edits`: .py でない既存のテストのファイル（単位の頭に在った物）で行を消した・置き換えた差分を拒む（足すだけは通す）。.py は今どおり関数の単位で見る
- [ ] 緑・commit

### 手順 3: 赤の理由を言語に依らない形で読む（決め 2）

- 機械の事実: 名指しが passed でない（failure・error・一式に居ない）・終了コードが 0 でない・名指しの外は元のまま
- error か一式に居ない名指しが在る時だけ、読むだけの役が生のログ（`suite-<n>.log`）・JUnit の本文・修正案の宣言（`red_kind`・`red_why`・`adds`）から「準備の失敗か、機能が無いか」を決め、根拠の行を引用する。機械は引用がログか JUnit に字のまま在るかを確かめる（`conflict.cite_problem` の型）
- Python の failure の行は今どおり `NAME_KINDS` と `adds` の完全一致で綴りの誤りを拒む（強さを下げない）
- 要る作り: 読み役の AI の節を TDD の輪 5 本（`tdd-loop`・`tdd-rest-loop`・`tdd-lane-loop-1〜3`）に足す（役を起こせるのは Archon の YAML の節だけ）・`stage-models.json` に 5 段（組 `light`）・事後の関門 `fixgates._red_green`（base で failure を要る）を同じ決まりに・模擬実行の stubs・配線の試験・グラフの地図の作り直し
- 止め時の判断: 上の作りは手順 1・2 の数倍の大きさなので、手順 1・2 を出してから見積もりと設計を報告し、持ち主の通しを待つ（依頼の決まり「見込みより大きければ止めて報告」）

### 手順 4: keep-essence の 1 の文を合わせる

- 手順 3 が入る commit で一緒に直す（入る前に文だけ変えると、文書が今の動きと食い違う）

## 見落としやすい所

1. 拡張子の無い・ドットで始まる設定のファイル（`LICENSE`・`.gitignore`）を起点にした変更: 文書のまま（全部を回さない）
2. `.png` などのバイナリ: 中身で `binary` と見るので、拡張子の反転に当たらない
3. works 自身の `COPIED_FROM.changemap`（拡張子 `changemap`）: 反転でコードに数えられ、`impact.py`・`changemap.py` を直す run が全部を回す形になった（審査で分かった）。git の属性 `linguist-documentation`（事実上の標準）で文書と宣言できる口を足し、根の `.gitattributes` で宣言した
4. Python の対象: `TEST_FILE` に無かった `*-case.py`・`*-suite.py`・宣言のファイルも凍結の照らしに入る（強くなる側）
5. .py でないテストのファイルの末尾に改行の無い時に行を足すと、git は最後の行を置き換えたと数えるので、直し・整えの段で拒む（拒む側。直す役は末尾に改行を足せば通る）
