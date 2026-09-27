# works

持ち主の普段の作業を Archon（AI の工程を YAML で書いて機械が順に回す道具）の上に移す pack。最初の生産ライン `darkfactory` は、人の修正依頼を判定 → 修正 → テスト → 人の承認 → 修正の審査の順に流す。並べ方は Archon に任せ、差を付けるのは各節の受け付け——graphloops（このリポジトリの既存のプラグイン）の規則と記録の検証器を `.shared/core/` に写して使い、中身が通ったときだけ次へ進める。

## 入れ方

```
archon plugin install raiki61/claude-plugins/works@<tag>
```

## 要る物

- Archon v0.11.1 以上 0.12.0 未満（`archon-plugin.json` の `compatibility.archon` が `>=0.11.1 <0.12.0`。確かめたのは v0.11.1 だけ）。
- uv（script の節は `runtime: uv` で起きる）と git。節のスクリプトは PEP 723 の塊を持つので、対象が pyproject.toml を持っても uv は対象の project を拾わない（worktree に .venv・uv.lock を作らない）。既知の限界: 対象の uv の設定（`[tool.uv]`・`uv.toml`）は読まれるので、それが壊れているか、手元の uv に合わない `required-version` を持つと、works の script の節は起動時に終了コード 2 で止まる。直すのは対象か uv の設定。`UV_NO_CONFIG=1` を Archon の環境に立てて逃げるのは勧めない: 対象自身の uv の動きも変わり（テストのコマンドや修正役の Bash が私的な index を読まずに公開の PyPI から解決する）、偽の赤と依存の取り違えの口になる。
- 対象リポジトリに git の remote。Archon は run ごとの worktree を既定で `origin/<既定の枝>` から切るので、remote が無いと run が始まらない。手元の枝や commit していない変更は worktree に入らないので、依頼の JSON は対象の外に置いて絶対パスで渡す（`skills/works/SKILL.md` の 2 節）。

## Claude Code のスキル

`skills/works/SKILL.md`（`/works`）に、依頼の JSON の書き方・起動の 1 行・人の関所での答え方・run の後に見る物（判定・審査の返答・修正の差分・run ごとの worktree）を置く。Claude Code のプラグインの定義は `.claude-plugin/plugin.json`。

持ち主に確かめること: Claude Code のプラグインとして配るには、リポジトリ直下の `.claude-plugin/marketplace.json` に works の 1 行が要る。共有のファイルなので、まだ足していない。

## 開発の回し方

テストは `works/tests/run.sh`。実際に Archon の上で回す手順（実行ファイルの取得・使い捨ての対象作り・`archon workflow test` 相当の検査・自分食い）は `works/dev/` を見る。キャッシュした Archon の実行ファイルの sha256 が合わないときは、止まった時の 1 行に出るそのファイルを消して回し直せば取り直す（殻は消さない）。

直しながら回すのは速い段 `WORKS_TESTS=fast sh works/tests/run.sh [-k 名前]`（git のリポジトリ・Archon・golden・プロセスの木を使わないモジュールだけ。`WORKS_TESTS=heavy` は残りの重い段で、2 つを合わせると全部）。作業の終わりと merge の前は、既定（何も付けない）の全部を回す。どのモジュールがどちらの段かは `works/tests/tiers.py` に 1 か所で書き、新しいテストのモジュールはどちらかに書き足す（書き忘れると段を選んだ実行とテストが止める）。全部と heavy は、機械全体で重いテストを同時に 4 本までにする枠の台本（mainline の `testslot.sh`。既定の置き場は `/Users/p03623/src/claude-plugins/.git/graphloops/ops/testslot.sh`、`WORKS_TESTSLOT` で差し替え。枠の置き場は台本の約束 `TESTSLOT_DIR`（既定は `/private/tmp/claude-<uid>/testslots`）で、`run.sh` が解決して台本へ渡す）を通して、枠が空くまで期限なしで待ってから回る。台本が無い・枠の置き場に書けない（サンドボックスの中など）ときは、1 行出して枠を取らずに回す。

`works/dev/archon.sh`（固定した版の Archon を隔離して回す殻）の認証に既定の口座は無い。AI を呼ぶ実行（`workflow run`・`workflow approve`・`workflow resume`、`dev/real-run.sh`）の前に、次のどちらかを設定する:

1. `CLAUDE_CODE_OAUTH_TOKEN`（`claude setup-token` で作るトークン）
2. `WORKS_KEYCHAIN_ITEM`（そのトークンを入れた macOS の keychain の項目名。`security find-generic-password -s <名> -w` で読む）

両方あれば 1 を使う。どちらも無ければ、案内を 1 行出して止まる。keychain の項目が空の値を返したときも同じく止まる。`WORKS_DEV_NO_AUTH=1` のときは認証を読まない（テスト・`validate`・`workflow test` 用。`dev/check.sh` は付けて回すので認証が要らない）。

認証を使う実行のたびに、`archon.sh` は隔離した Archon の設定（`$WORKS_DEV_HOME/archon-home/config.yaml`）に模型を書く（`WORKS_DEV_MODEL`。既定は opus。run の題を作る模型 `TITLE_GENERATION_MODEL` も、設定していなければ同じにする）。書かないと Claude CLI の既定の模型で黙って回る。`WORKS_DEV_NO_AUTH=1` のときは書かない。

開発の家（`WORKS_DEV_HOME`。既定は `$TMPDIR/works-dev`）・使い捨ての対象・その origin は、Claude Code の一時フォルダ（`/private/tmp/claude-*`・`/tmp/claude-*`）の下に置けない。サンドボックスの中の Bash がそこへ書けるためで、`dev/` の殻はその下に解けるパスを終了コード 2 で拒む（設計書 7 節）。

## 実走

本物の AI でライン `darkfactory` を 1 回回す殻が `works/dev/real-run.sh`（費用が掛かる。回す前に持ち主の了承を取る）。

1. `WORKS_KEYCHAIN_ITEM=<keychain の項目名> sh works/dev/real-run.sh [<dir>]` を前景で打つ。使い捨ての対象を作り、ライン（模型は `WORKS_DEV_MODEL`、既定は opus）を回し、人の関所で止まって戻る。
2. 関所の文面の「テストが緑か」「テストのログ」と、殻が出す「修正の差分がある worktree」を見る。修正は対象ではなく、Archon が run ごとに切った worktree の中にある。
3. 殻が出す approve のコマンドを打つ。承認はその場で続き（差分の審査）を回して終わる。`resume` は失敗・中断から続けるときだけ要る。

### 結果（2026-09-26・Archon v0.11.1・opus・3 回）

| run | 仕掛け | 関所まで | 承認から終わり | 費用 | 拒否 | 審査の穴 |
|---|---|---|---|---|---|---|
| 4d11a59b | 無し | 3分00秒 | 1分20秒 | $0.59 | 0 | 0 |
| 3e5bcda1 | 未追跡のファイル | 3分00秒 | 1分02秒 | $0.66 | 2 | 2 |
| 62915c41 | 空の commit | 1分44秒 | 50秒 | $0.45 | 0 | 0 |

費用は Archon が節ごとに記録した額（OAuth の名目の額）の合計で、3 回で $1.70。AI の呼び出し 1 回あたりの額はおおよそ判定 $0.15〜0.22・修正 $0.16〜0.20・審査 $0.05〜0.16（出し直しがあればその役の額は回数分かさむ。run 3e5bcda1 では判定が 2 回で $0.295、審査が 2 回で $0.206）。

- 赤になった所は無い。3 回とも判定の輪が通り、修正の後の `python3 -m unittest -q` が緑、関所で止まり、承認の後に差分の審査が `ok: true` で終わった。
- run 3e5bcda1 では、読むだけの役（判定・審査）の 1 周目の間だけ worktree に未追跡のファイルを置き、受け付けに 1 回ずつ拒ませた。2 周目のプロンプトに拒んだ理由がそのまま貼られ（1 周目は空）、2 周目は 1 周目の会話の続き（Archon が 1 周目の会話を fork して続ける）で出し直し、通った。
- 修正役の出し直し（修正の受け付けが拒んだ後の 2 周目）は、3 回とも起きていない。修正で確かめたのは、1 周目の「拒んだ理由」が空で貼られることだけ。
- run 62915c41 では、依頼の受け付けの後に worktree で空の commit を打って HEAD を動かした。判定の受け付けは HEAD ではなく周の頭の版（`base` の出力）で数えた。ラインの `base_rev` が script の節まで届いている。
- 判定役・修正役・審査役は 3 回とも別々の新しい会話で始まった（前の役の会話を引き継がない）。
- run 3e5bcda1 の審査が挙げた 2 件は本物の指摘: 修正役が docstring に「statistics.mean・numpy.clip と同じ定義」と書き足したが、空の列・`lo > hi` のときは一致しない（宣言と実装のずれ）。
- 回すのに要った準備: Archon は run ごとに切る worktree の元を remote から取るので、remote の無い対象では止まる（`real-run.sh` が対象の外に裸のリポジトリを作って origin にする）。隔離した HOME からは `~/.local/bin/claude` を見つけられないので、`CLAUDE_BIN_PATH` を渡す。

## 自分食い（dogfood）

works 自身の直しをライン `darkfactory` に回す殻が `works/dev/dogfood.sh`（費用が掛かる。回す前に持ち主の了承を取る）。

1. 依頼の JSON を書く（形は `skills/works/SKILL.md`）。置き場所はどこでもよい（殻が写して渡す）。
2. `WORKS_KEYCHAIN_ITEM=<keychain の項目名> sh works/dev/dogfood.sh <依頼の JSON> "<テストのコマンド>" [<dir>]` を前景で打つ。殻は、このリポジトリの今の HEAD（commit 済みの物だけ）を `<dir>/repo` に clone し、works を `.archon/workflows/works` に写して枝 `dogfood-base` に commit し、`<dir>/origin.git` を origin にしてラインを回す。`<dir>` の既定は `$TMPDIR` の下の一時フォルダ。人の関所で止まって戻る。
3. 実走と同じく、関所の文面と殻が出す worktree を見て、approve のコマンドを打つ。
4. 審査が終わったら、殻が出す `git -C <このリポジトリ> apply <fix.diff のパス>` で差分を取り込み、手元でテストを回してから commit する。
   修正が `works/` でなく pack の写し（`.archon/workflows/works`）を書き換えていたら、その部分は取り込まない（殻は「注意:」の 1 行を出す）。`<dir>` に前の回の `repo`・`origin.git`・`request.json` が在ると、殻は何も書かずに止まる。

### 結果（2026-09-26・Archon v0.11.1・opus・2 回）

| run | 依頼 | 費用 | 審査の指摘 | 取り込んだ commit |
|---|---|---|---|---|
| dd52a646 | 悪い見本ごとに違反の文面まで照合 | $1.00 | 0 | f3baa2e |
| 98978777 | validate が 0 本なら赤 | $0.75 | 0 | fef8877 |

分かったこと:

- 模型は固定しないと黙って変わる。当初は `real-run.sh` だけが模型を設定に書いていたので、`archon.sh workflow run` を直に打つと Claude CLI の既定の模型（sonnet）で回った。今は `archon.sh` が認証を使う実行のたびに書く（開発の回し方の節）。
- テストのコマンドが確かめるのは、渡した物だけ。ラインにはまだ全体を回す CI の節が無いので、迷ったら全体（`sh works/tests/run.sh`）を渡す。
- サンドボックスの中の修正役は `tests/test_dev.py` を回せない。サンドボックスの TMPDIR は `/tmp/claude-*` の下で、`guard.sh` がそこを拒むため。修正役は環境のせいの赤を 10 件ほど報告するが、修正の良し悪しとは関係ない。
- 修正役は run の worktree に `__pycache__` などの git が無視するファイルを残すことがある。fix.diff には載らないが、テストの節の緑赤を左右した（自分食いの run で、バイトコードが無いことを見る試験が偽の赤になった）。今は blk-fix が修正役の前に git が無視するファイルを控え（節 `ignored-before`）、修正役の後、テストの前に、控えに無かった物だけを消す（節 `clean`。消した物は関所の文面に出る）。判定・審査の読むだけの検査（作業ツリーの写し）も、git が無視するファイルの増減・書き換えを見る。

## 足りない所

- 修正の受け付けは、直す義務の残る単位ごとに修正の行が在るか（`fix_plan_covers_units`）までを見る。graphloops の `fix_covers_open_units`（修正の後に判定の `class_query` を機械で数え直し、単位が閉じたかを見る）とは違う。修正の後の機械による数え直しは未実装（周の輪の段で入れる予定）。
- 周の輪（2 周目以降）・修正案の事前審査など、設計書 6 節の「範囲の外」に挙げた物は無い。

## 仕様

設計の正本は [`docs/specs/2026-09-26-darkfactory-design.md`](docs/specs/2026-09-26-darkfactory-design.md)。実装計画は [`docs/plans/2026-09-26-darkfactory-v1.md`](docs/plans/2026-09-26-darkfactory-v1.md)。
