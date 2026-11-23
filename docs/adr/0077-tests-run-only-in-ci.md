# 0077. 試験は手元でも --land のゲートでも回さず、main に入った後の CI だけが回す

部署（ブランチを main に入れる側）に関わる決め。急ぎの対応は要らない。部署は、作業場でも `--land`（部署のブランチを main に入れる works-dispatch のコマンド）のゲートでも試験を回さない。手元で回すのは、試験を走らせない数十秒の照合（軽い検査 `bash scripts/light-check.sh`）だけ。
試験は全部、main に入った後の CI（`.github/workflows/test.yml`）が回し、赤は点検（CI とルートの tests/ を受け持つ部署）が原因の commit を git revert で戻す。

- 状態: 採用
- 一部の置き換え: [0076](0076-land-runs-affected-tests.md) の決定 1〜4（回す場所・`--land` で回す試験の選び方・速さ・落ちた試験の名前の出し方）を置き換える。0076 の決定 5（入れる順を判断役が決められる `--land-order`）はそのまま。[0071](0071-test-sizes-and-where-they-run.md) の回す場所の 1（[0073](0073-land-bumps-and-no-tags.md) が変わらないと書いた「手元では small の全部と、変えた・足した試験だけを回す」）と、[0074](0074-graphloops-edits-by-desk-and-land.md) の「触ったプラグインの手元の試験」も置き換える。0071 の、重い試験と変異テストを手元で回さない決めは、軽い試験にも広げた形になる
- 日付: 2026-11-23
- 決めた人: 持ち主（2026-11-23「重いのでテストはCIで回すようにしてね」）。手元に残す照合の線引き（試験を走らせない物だけ）と、`tests/land-check.py` をゲートから外す形は、頼みを受けた点検の部署の推し（覆せる）
- 実装: 入った（ルートの `CLAUDE.md` の「試験」、`.claude/company.toml` の `[land]` の `check` と、役「担当」「作業」の本文）

## 文脈

- 2026-11-23 までの 2 日のリファクタリングの頼みで、部署が直しのたびに手元で graphloops の pytest（2061 件）・`graphloops/tests/simulate.py`（703 件）・`simulate_review.py`（1219 件）などを回し、機械が重くなった。ルートの `CLAUDE.md` の「試験」は「触ったモジュールの試験」を手元で許していたので、決まりの上では違反ではなかった。
- `--land` のゲートは、0076 から、軽い検査の次に `tests/land-check.py`（変更が入力に当たる `tests/run.sh` の検査だけを回す）を回していた。works-dispatch だけを変えた回で、混んだ機械で 8 分ほど、`tests/run.sh` を変えた回は全部を回して 25 分ほどかかる。ゲートは部署の機械で回るので、これも手元の試験に入る。
- main に入った後の CI（`.github/workflows/test.yml`）は、もう全部の試験を全部の OS の組で回している。入った後の赤を戻す道（[0073](0073-land-bumps-and-no-tags.md) の git revert）も決まっている。

## 決定

### 1. 回す場所は 2 つ

1. **手元**（部署の作業場と、`--land` のゲート。どちらも部署の機械で回る）: 試験を走らせない照合だけ。
   1. 軽い検査（`scripts/light-check.sh`）。中で回すのは、共有の写し（`scripts/shared-copies.py`）・語（`scripts/terms.py`）・機械が読む値の決まり（`tests/value-rules.py`）・静的検査の shellcheck（`scripts/shellcheck.sh`）と、消えた試験の一覧（`tests/removed-tests.py`。止めない）。どれも git の追跡下のファイルを読んで照合するだけで、試験を起動しない。数十秒。main への push の前のフック（`.githooks/pre-push`）も同じ物を回す。
   2. 語の直し（`works-dispatch/dispatch/terms.py --fix`。ファイルの語を置き換えるだけ）。
   3. `--land` のゲートの最後の初見の読み手（gates の `coldread-gate.py branch-check`。文書を AI に読ませる。試験ではないので残す）。
2. **main に入った後の CI**: 全部の試験（`tests/run.sh`・pytest の置き場・`works/tests/run.sh` など、`.github/workflows/test.yml` が回す物）。赤は点検が赤の元の commit を git revert で戻す（0073 のまま）。決まった時刻に走らせる実行は置かない（0076 のまま）。

手元で打たない物: `bash tests/run.sh`・`sh works/tests/run.sh`・pytest・unittest・模擬実行の台本（`simulate.py` など）・変異テスト（`tests/mutate.py`・mutmut・`works/dev/selfcheck.py`）・`tests/land-check.py`。

### 2. `tests/land-check.py` はゲートから外し、ファイルは残す

- `[land]` の `check` は `bash scripts/light-check.sh && python3 gates/hooks/coldread-gate.py branch-check ...` にした。
- `tests/land-check.py` と、`tests/run.sh` の `scope`（変えた所だけを回すための入力の宣言）・`tests/land-known-red.txt` は消さない。今は回す所が無いが、手元で試験を回す形へ戻す決めが出たとき、選び方（0076 の決定 2）と落ちた試験の名前の出し方（0076 の決定 4）をそのまま使える。消すかは別の頼みで決める。
- works の試験の決まり（`works/CLAUDE.md` の「出荷」の 1。手元で速い段とルートのチェックを回す）は、持ち主が別に回している所なので、この決めでは直していない。

## 比べた案

- **0076 のまま、`--land` のゲートで変更が当たる試験だけを回す**（捨てた案）: 部署の手元の試験を止めても、ゲートは部署の機械で 8〜25 分の試験を回す。持ち主の「テストはCIで回す」に合わない。
- **`--land` で main の CI の緑を待つ**（捨てた案）: 「CI は待たない」決め（0073）とぶつかる。GitHub の merge queue は個人のリポジトリで使えない（0076 の文脈）。
- **`tests/land-check.py` と `scope` を消す**（今回は採らない）: ゲートから外すだけで持ち主の言葉は満たせる。消すと 0076 の選び方を作り直す手間が残り、消す直しは `tests/run.sh`（約 1 万行）と `tests/mutate.py` に広がる。

## 理由

- 止める検査には速くて揺れない物だけを置き、重い物は入った後に回す形は、Google（SWE book 23 章）と同じ向き（0076 の理由のまま）。今回は、試験の全部を「重い物」の側に置いた。
- 入った後の赤を戻す道（revert）が決まっているので、ゲートで試験を回さなくても、赤は入った後の CI で見つけて戻せる（Martin Fowler の「Continuous Integration」）。

## 結果

- 楽になる: 部署の機械で試験が走らない。`--land` の 1 回は、軽い検査（数十秒）と初見読み（2〜4 分）で済む。
- 難しくなる: 赤は main に入った後の CI で初めて見つかる。ゲートが試験を回していなかった頃（2026-10-19 に `tests/run.sh` をゲートに足すより前）と同じく、部署が入れるたびに main に赤が積み上がりうる。赤は点検が revert で戻す。
- 部署は、自分の直しが試験に通るかを入れる前に知らない。CI の見張り（`.claude/company.toml` の `[[land.after]]` の「CI の見張り」）が、main に入れるたびに main の CI を見る。

## 見直す条件

- main の CI の赤が週に 2 回より多く出たら、ゲートに `tests/land-check.py` を戻すか（0076 の形）、CI を待つ形を持ち主に問い直す。

## 出どころ

- 持ち主の言葉（2026-11-23）: 上の「決めた人」。
- 原典:
  - Winters・Manshreck・Wright 編『Software Engineering at Google』23 章「Continuous Integration」<https://abseil.io/resources/swe-book/html/ch23.html>（"After a change has been submitted, we use TAP to asynchronously run all potentially affected tests, including larger and slower tests."）
  - Martin Fowler「Continuous Integration」<https://martinfowler.com/articles/continuousIntegration.html>（"Usually the best way to fix the build is to revert the latest commit from the mainline"）
