# 0076. --land の検査は、変更が入力に当たるテストだけを回し、全部のテストは main に入った後の CI が回す

- 状態: 採用
- 一部の置き換え: [0073](0073-land-bumps-and-no-tags.md) の「手元の関門」の中身（`[land]` の `check` が回すテスト）をこの ADR が決める。[0071](0071-test-sizes-and-where-they-run.md) の大きさの軸と、手元で重い試験を回さない決めはそのまま
- 日付: 2026-10-20
- 決めた人: 持ち主（2026-10-20「一旦テストは全部飛ばしてclaudepluginsはいれましょう。」「そのあとにreferenceを見ながらテストやCI、マージ周りの再構築を行いましょう」、同じ日の「変えたところだけにします」）。どのテストをどこで回すかの割り当ては、下の出どころの原典に当てた作業の部署の推し（受付 00407b。覆せる）
- 実装: 入った（`tests/land-check.py`、`tests/run.sh` の `scope`、`.claude/company.toml` の `[land]` の `check`、works-dispatch の `dispatch/tests/parallel.py`）

## 文脈

- `--land`（部署のブランチを main に入れる works-dispatch のコマンド）の検査は、1 本の `tests/run.sh`（約 750 件の検査を順に 1 つずつ回す）を丸ごと回していた。2026-10-20 に、混んだ機械（24 コア、load average 20〜35）で 1 回が 45 分ほどかかり、18:22 から 19:45 まで main に何も入らなかった。
- 同じ日に検査ごとの時間を測った（load average 11〜30）。全体 25 分 44 秒のうち、works-dispatch のテスト（`unittest discover` の 1 本）が 18 分（7 割）で、次は `tests/mutate.py` の検査の一群（合わせて約 4 分）。ほかの約 700 件は合わせて 3 分ほど。
- 落ちたテストの名前が `--land` の出力に出なかった。`--land` は検査の出力の末尾 20 行だけを部署に渡し、`tests/land-check.py` は `tests/run.sh` の赤の検査の名前（例「works-dispatch/dispatch: ノードの試験と決まりのチェック」）までしか出さず、その中の unittest のどれが落ちたかは捨てていた。
- GitHub の merge queue は使えない（組織が持つ公開のリポジトリか、Enterprise Cloud の組織の非公開のリポジトリだけ。このリポジトリは個人のアカウントの物）。main の CI を待って入れる形は、「CI は待たない」決め（[0073](0073-land-bumps-and-no-tags.md)）とぶつかる。

## 決定

### 1. 回す場所は 3 つ

1. **手元**（部署の作業場）: 触ったプラグインのテストだけ（ルートの CLAUDE.md の「試験」のセクションのまま）。
2. **`--land` の検査**（main に入れる前に止める所）: 次の順に回し、どれかが赤なら入れない。
   1. 軽い検査（`scripts/light-check.sh`。共有の写し・試験の件数・語・機械が読む値の決まりの 4 つ。数十秒。main への直接の push でもフックが回す）
   2. この変更が入力に当たるテストだけ（`tests/land-check.py`。下の 2）
   3. 初見の読み手（gates の branch-check。AI を起動して費用がかかるので最後）
3. **main に入った後の CI**（`.github/workflows/test.yml`）: 全部のテストを、全部の OS の組で回す。`--land` で見送ったテストもここで回る。赤は点検が、赤の元の commit を git revert で戻す（[0073](0073-land-bumps-and-no-tags.md) のまま）。決まった時刻に走らせる実行は置かない（持ち主は cron などの定期の起動を置かない）。

### 2. `--land` で回すテストの選び方

- main との分かれ目から変わったファイルを取り、その頭のディレクトリのプラグインと、それに `plugin.json` の `dependencies` で依存するプラグイン（依存の依存も）を「変わったプラグイン」に数える。
- `tests/run.sh` の検査は `scope` で入力（プラグインの名前か、ファイルのパスの頭）を宣言する。宣言した入力がどれも変わっていなければ、その検査は走らせずに見送りの行を出す。宣言の無い検査は毎回回す。
- `tests/run.sh` 自身が変わった回と、分かれ目を取れない回は全部を回す。全部を回したいときは `TESTS_LAND_ALL=1` を付ける。
- 前から `--land` で見送っていた graphloops の模擬実行（CI が組に分けて回す）は、今のまま見送る。

### 3. 速さ

- 目安は 1 回 10 分以内。混んだ機械でもこれを超えないことを狙う。
- works-dispatch のテストは、偽物の git に移したうえで、クラスを小さい組に分けて 4 つのプロセスで並べて回す（`works-dispatch/dispatch/tests/parallel.py`。受付 41ffe3）。
- `tests/land-check.py` は、終わりにかかった時間と、そのときの load average を出す（遅くなったら、どの `--land` から遅くなったかを後から追える）。

### 4. 落ちたテストの名前を出す

- `tests/land-check.py` は、止めた赤の検査ごとに 1 行「落ちた: <検査の名前> ← <中で落ちたテストの名前>」を、出力の最後の行のすぐ前に出す（`--land` が部署に渡す末尾 20 行に入る）。
- 中で落ちたテストの名前は、捕った出力から拾う: unittest の `FAIL:`・`ERROR:` の行、works-dispatch の `parallel.py` の同じ形の行、pytest の要約の `FAILED` の行、中で回した別の台本の赤の行。どれも無ければ、最後の `...Error` の行を 1 つ出す。1 つの検査で 8 件より多ければ「ほか N 件」に畳む。

## 比べた案

- **`--land` で全部のテストを回す**（Rust と Go の形。捨てた案）: 混んだ機械で 45 分かかり、`--land` の列（1 本ずつ通す）が止まる。このリポジトリは部署が 1 日に何十本も入れるので、待ちが積み上がる。
- **`--land` でテストを回さない**（19:45 からの仮の形。捨てた案）: 部署が入れるたびに main に赤が積み上がった前の形に戻る（2026-10-19、受付 b9ab0d）。
- **GitHub の merge queue か、必須の status check で CI を待つ**（捨てた案）: merge queue は個人のリポジトリで使えない。必須の status check は「CI は待たない」決めとぶつかる。
- **`tests/run.sh` をプラグインごとのファイルに割って並べる**（今回は採らない）: 時間の 7 割は works-dispatch のテスト 1 本で、それを並べれば目安に収まる。残りの約 700 件は合わせて 3 分ほどで、割る手間に見合う縮みが無い。目安を超えたら見直す。

## 理由

- 止める検査には速くて揺れない物だけを置き、重い物は入った後に回す形は、Google（SWE book 23 章）・Meta・NVIDIA などの原典と同じ向き。原典は全部をマージ前に回すか（Rust・Go）で割れるが、割れた片方の Rust の形は、このリポジトリの待ちの長さでは成り立たない。
- 変わった物とその依存元を選ぶ形は、Nx の affected と同じ。vLLM も差分を見て関わるテストの群だけを回す。
- 入った後の赤を戻す（revert）道が決まっている（[0073](0073-land-bumps-and-no-tags.md)）ので、見送ったテストの赤も、入った後の CI で見つけて戻せる。

## 結果

- 楽になる: works-dispatch だけを変えた `--land` は、全部のテストを回さない。落ちたテストの名前が部署への知らせに載るので、部署は出力を探さずに直せる。
- 難しくなる: `scope` の宣言が漏れると、変えた所の赤を main の CI まで見落とす（入った後に revert で戻す）。宣言の無い検査は毎回回るので、漏れは「回しすぎ」の向きにだけ起きるようにしてある。
- `tests/run.sh` を変えた `--land` は全部を回すので、遅いまま。

## 見直す条件

- `--land` の 1 回が、`tests/run.sh` を変えない回で 10 分を超えたら、`tests/run.sh` をプラグインごとに割って並べるかを決め直す。
- main の CI で、`--land` で見送ったテストの赤が週に 2 回より多く出たら、`scope` の宣言の漏れを調べ、選び方を広げるかを決め直す。

## 出どころ

- 持ち主の言葉（2026-10-20）: 上の「決めた人」。
- 実測（2026-10-20）: 上の「文脈」の時間。
- my_notes の reference/ のノート（持ち主の、外の原典を写したノートの置き場）:
  - `reference/secondary/ci/presubmit-test-subset-or-all.md`（マージ前に走らせるテストを一部に絞るかで、CI の原典は割れる）
  - `reference/secondary/ci/deferred-tests-run-on-merge-or-schedule.md`（後ろに回したテストは、マージを引き金か決まった間隔で機械が走らせる）
  - `reference/secondary/ci/affected-runs-include-dependents.md`（変わったものから対象を選ぶ仕組みは、依存元まで含められる）
  - `reference/primary/ci/google-continuous-integration.md`・`reference/primary/ci/dora-continuous-integration.md`・`reference/primary/ci/vllm-ci.md`・`reference/primary/monorepo/nx.md`・`reference/primary/ci/github-merge-queue.md`・`reference/primary/ci/fowler-ci-fix-broken-builds-and-visibility.md`
- 原典:
  - Winters・Manshreck・Wright 編『Software Engineering at Google』23 章「Continuous Integration」<https://abseil.io/resources/swe-book/html/ch23.html>（"Our general rule of thumb is: only fast, reliable ones."、"After a change has been submitted, we use TAP to asynchronously run all potentially affected tests, including larger and slower tests."）
  - DORA「Continuous integration」<https://dora.dev/capabilities/continuous-integration/>（"with an upper limit of about 10 minutes"）
  - Nx の affected（変わったファイルが属するプロジェクトと、それに依存するプロジェクトだけでタスクを回す）<https://nx.dev/docs/features/ci-features/affected>
  - vLLM「Keeping vLLM production quality」<https://vllm.ai/blog/2026-07-16-keeping-vllm-production-quality>（"inspects the diff, and schedules only the relevant groups."）
  - GitHub「Managing a merge queue」<https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue>
  - Martin Fowler「Continuous Integration」<https://martinfowler.com/articles/continuousIntegration.html>（"Usually the best way to fix the build is to revert the latest commit from the mainline"）
