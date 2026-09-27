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

直しながら回すのは速い段 `WORKS_TESTS=fast sh works/tests/run.sh [-k 名前]`（試験ごとに git のリポジトリを作らない・uv run・Archon・golden・プロセスの木・決まった秒の待ちを使わないモジュールだけ。種の git を `works/tests/gitkit.py` の型の写しで配るのは可。`WORKS_TESTS=heavy` は残りの重い段で、2 つを合わせると全部）。作業の終わりと merge の前は、既定（何も付けない）の全部を回す。どのモジュールがどちらの段かは `works/tests/tiers.py` に 1 か所で書き、新しいテストのモジュールはどちらかに書き足す（書き忘れると段を選んだ実行とテストが止める）。全部と heavy は、機械全体で重いテストを同時に 4 本までにする枠の台本（mainline の `testslot.sh`。既定の置き場は `/Users/p03623/src/claude-plugins/.git/graphloops/ops/testslot.sh`、`WORKS_TESTSLOT` で差し替え。枠の置き場は台本の約束 `TESTSLOT_DIR`（既定は `/private/tmp/claude-<uid>/testslots`）で、`run.sh` が解決して台本へ渡す）を通して、枠が空くまで期限なしで待ってから回る。台本が無い・枠の置き場に書けない（サンドボックスの中など）ときは、1 行出して枠を取らずに回す。

TDD の修正の段が使うテストの実行器（ラインの入力 `tdd_suite`）は `works/dev/tdd-suite.sh <JUnit XML の書き先> [pytest の引数]`。同じ試験を既製の pytest で回し、結末を JUnit XML に書く。段は `WORKS_TDD_TIER`（既定 fast・heavy）で、段のファイルは `tiers.py` の `paths` の口から引く。読み込みで落ちるモジュールが在っても一式を止めず（`--continue-on-collection-errors`）、そのモジュールは error の 1 行で載る。heavy でも枠の台本は通さない。unittest と pytest では結末の数え方が一部違う（例外で落ちた試験は unittest では error、pytest では failure。`-k` は unittest では名前の部分一致、pytest では式）。pytest は一番外の `def test_*` も試験として拾うので、試験の道具の関数は `test_` で始めない（`test_tiers` が縛る）。

`works/dev/archon.sh`（固定した版の Archon を隔離して回す殻）の認証に既定の口座は無い。AI を呼ぶ実行（`workflow run`・`workflow approve`・`workflow resume`、`dev/real-run.sh`）の前に、次のどちらかを設定する:

1. `CLAUDE_CODE_OAUTH_TOKEN`（`claude setup-token` で作るトークン）
2. `WORKS_KEYCHAIN_ITEM`（そのトークンを入れた macOS の keychain の項目名。`security find-generic-password -s <名> -w` で読む）

両方あれば 1 を使う。どちらも無ければ、案内を 1 行出して止まる。keychain の項目が空の値を返したときも同じく止まる。`WORKS_DEV_NO_AUTH=1` のときは認証を読まない（テスト・`validate`・`workflow test` 用。`dev/check.sh` は付けて回すので認証が要らない）。

認証を使う実行のたびに、`archon.sh` は隔離した Archon の設定（`$WORKS_DEV_HOME/archon-home/config.yaml`）に模型を書く（`WORKS_DEV_MODEL`。既定は opus。run の題を作る模型 `TITLE_GENERATION_MODEL` も、設定していなければ同じにする）。書かないと Claude CLI の既定の模型で黙って回る。`WORKS_DEV_NO_AUTH=1` のときは書かない。

開発の家（`WORKS_DEV_HOME`。既定は `$TMPDIR/works-dev`）・使い捨ての対象・その origin は、Claude Code の一時フォルダ（`/private/tmp/claude-*`・`/tmp/claude-*`）の下に置けない。サンドボックスの中の Bash がそこへ書けるためで、`dev/` の殻はその下に解けるパスを終了コード 2 で拒む（設計書 7 節）。

## 層と依存の向き

正本は試験 `works/tests/test_layers.py`（裁定 R59）。下は要約で、食い違えば試験が正しい。上の層は下の層だけを知ってよい（import も、ライン・include の id・ほかのブロックの名前を文字列で書くことも）。

- L0 写し: `.shared/core/graphloops`・`.shared/core/scripts`。works の物を何も知らない
- L1 基礎: `tree_run`・`script_io`・`node_marker`
- L2 包み: `adapter`・`ticket`・`claude-adapter`・`record-read.py`・`no-post-bin/works-gh`
- L3 盤面と受け付け: `board`・`accept`・`policy`・`entry`（共有の部分）・`halt`（止め札）・`refix`・`recount`
- L4 ブロックの模块: 使うブロックが 1 つの模块（`ci_role`・`purpose`・`rejudge`・`prcheck`、`<blk>/lib/`）。持ち主のブロックとラインだけが使う
- L5 ブロック: `blk-*/`。ほかのブロック・ライン・自分に付く include の id を知らない
- L6 ラインの模块: 使うラインが 1 つの模块（`<line>/lib/`。例: `darkfactory/lib/` の境の節の中身）。持ち主のラインだけが使う
- L7 ライン: `<line>/`（`nodes.json` を持つフォルダ）。ブロックを名前で include してよい
- L8 `dev/`・L9 `tests/`: 全部を知ってよい。pack の中からは参照しない

ほかに、輪の無い import・`*/scripts/*.py` は YAML の節だけ（模块は `lib/` か core へ）・動的な import は定数だけ、を縛る。今ある破れは試験の `KNOWN` に載せてあり、減らす方向にだけ変える（直したら行を消す。残すと赤）。`KNOWN` に置けるのは破れの組だけで、「層が決まっていない」類の印（新しい core の模块の `unassigned` など）は置けない。失敗の文が印ごとに直し方（`MOD` に層を足す・`PLANNED_SCRIPTS` に足す など）を言う。`lib/` は Archon が探さない（探すのは `scripts/` など）ので、スクリプトとして拾われない。

## 借りた superpowers のスキル

superpowers（Claude Code のプラグインのスキル集。MIT。表示は `NOTICE`）6.4.2 から、test-driven-development・systematic-debugging・verification-before-completion・receiving-code-review・requesting-code-review の 5 本を `.shared/superpowers/6.4.2/skills/` にバイトのまま写している（元と写したファイルは同じ置き場の `COPIED_FROM`。写しは直さない）。

- 読ませ方: AI の節に `skills: [<名>]` と `settingSources: [user]` を書く。Archon は `[user]` のとき `$CLAUDE_CONFIG_DIR/skills/<名>/SKILL.md` を探す。開発の殻 `dev/archon.sh` は、実行のたびに `dev/skills.sh` で写しを隔離した `$WORKS_DEV_HOME/claude-config/skills/` へ写す。
- YAML の決まり（`tests/test_yaml_rules.py`）: `[user]` は、`skills:` を持ち、その全部が写しに在る節だけに許す。
- 柵: `[user]` は同じ置き場の CLAUDE.md・settings*.json・rules/・agents/・commands/・plugins/ も読ませる。`dev/skills.sh` は、そのどれかか借りる一覧の外のスキルが隔離した置き場に在れば、名前を出して終了コード 2 で止まる（`archon.sh` も Archon を起こさない）。
- **実物の線の YAML には、まだ `[user]` を入れない。** 開発の殻の外（利用者が自分の Archon で pack を入れる場合）では `CLAUDE_CONFIG_DIR` が利用者の本物の `~/.claude` で、借りたスキルは無く、利用者の CLAUDE.md と hooks を読む。殻の外の入れ方ができるまで、`[user]` は開発の殻の中の試しだけに使う。
- 無人の読み替え: スキルの文が人（your human partner）や下請けの AI を前提にする所は、`.shared/superpowers/unattended.md` の決まりで読み替える（直す義務の単位は必ず直して `changes` に載せ、人に聞きたいこと・疑いは `rejudge_requested` に書く。`not_done` は受け付けが免除する単位と義務の外の単位だけ。修正役は commit しない、`superpowers:` の参照は無視、など）。
- 試験（`tests/test_sp_skills.py`）は写しと元（プラグインのキャッシュ）のバイトの一致を見る。元が無ければ飛ばさずに赤になるので、同じ版の checkout を `WORKS_SP_SOURCE` に渡す。

## Claude の包み

`.shared/core/claude-adapter` は、Archon が起こす Claude Code の実行ファイルの前に挟む薄い殻（芯は `.shared/core/adapter.py`）。役が読んだファイルの記録・再審の役が判定役の会話の続きで起きること・役に書かせない場所の柵・止める時に孫まで止めることを受け持つ。形は本物の Archon v0.11.1・SDK 0.3.282・claude 2.1.283 との有料の試しで確かめ、試験（`tests/test_adapter.py`）は偽の claude で縛る。今のラインの YAML はまだ印を持たないので、入れても何も足さずに素通しする（印を付けるのは線 A の後の作業）。

入れ方:

1. Archon の設定 `assistants.claude.claudeBinaryPath` に包みの絶対パスを書く（これが主。env の `CLAUDE_BIN_PATH` は設定より強いので、一時の上書きに使える）。
2. 本物の claude を `WORKS_REAL_CLAUDE`（絶対パス）で渡す。無ければ包みは PATH の実行ファイル `claude` を使う（包み自身を指す物は飛ばす）。
3. 置き場（包みの家）を `WORKS_ADAPTER_HOME` で渡す。既定は `${XDG_STATE_HOME:-~/.local/state}/works/adapter`（切符と同じ）。絶対パスでなければ包みは起動を拒む。役の sandbox の Bash から書けない場所に置く（`/private/tmp/claude-*` は不可）。
4. 開発の殻では `WORKS_DEV_ADAPTER=1` を付けて `dev/archon.sh`・`dev/real-run.sh`・`dev/dogfood.sh` を打つ。`archon.sh` が隔離した設定に `claudeBinaryPath` を書き、`CLAUDE_BIN_PATH` を `WORKS_REAL_CLAUDE` へ移し、家を `$WORKS_DEV_HOME/adapter` にする。殻が出す承認・続きのコマンドにも同じ札が付く。

包みがすること・しないこと:

- どの節の起動かは、役の `output_format` の一番上の `description` に置く印 `works-node: <節の名>[ continue=<継ぐ節の名>]` で見分ける。SDK がそれを argv の `--json-schema` に載せる。印の無い起動（Archon が run の題を作る `--tools ""` の起動など）は、下の網の閉じのほかは argv を 1 バイトも変えない。
- 印のある起動には、`--settings` に PostToolUse:Read のフック（`.shared/core/record-read.py`。graphloops の写しで、書く先だけ替えた）を足す。SDK が渡した `--settings`（sandbox）の鍵は上書きしない。`--settings` が無い節にはフックだけの `--settings` を足す。`--setting-sources`・`--model` ほかの旗は触らない（CLAUDE.md を止めるのは YAML の `settingSources: []`）。
- 読んだ記録は `<家>/reads/<cwd の hash>/reads.jsonl` に、ファイルの sha と部分読みかを 1 行ずつ書く。形は graphloops のままなので engine の `hook_evidence` がそのまま読む。Claude の子の env には `ARTIFACTS_DIR` が来ないので、run は cwd（Archon が run ごとに切る worktree）で分ける。
- 判定役（`works-node: judge`）は、包みが `--session-id=<uuid>` を足して起こし、id を `<家>/sessions/<cwd の hash>/judge.id` に書く。SDK が自分で `--resume`・`--session-id` を付けた起動はその id を記録する。
- 再審（`works-node: rejudge continue=judge`。YAML の節は `context: fresh`）は、SDK の会話の旗を外して `--resume <judge の id>` で起こす（fork しない）。id が無ければ子を起こさず、1 行を出して終了コード 3 で止まる。ただし Archon はこれを落ちた起動として約 12 回起こし直すので、先に script の節で id が在るかを見る。再開した節の費用の表示は判定役の分を重ねて数える（SDK の `total_cost_usd` が累積のため）。
- 網を閉じる（印の有無に依らない）: Archon は役を bypassPermissions で起こし、YAML の `sandbox.network` から `strictAllowlist` を捨てる。この形の Claude Code（2.1.283）は、`allowedDomains` に無い宛先への Bash の通信を自動で通す。そこで包みは、`--settings` の `sandbox.network.allowedDomains` が `*` を含まない配列の起動に `strictAllowlist: true` を足す（`*` の網・網の一覧の無い sandbox は触らない）。`--settings` が読めない・2 つ・sandbox や網の形が違う起動は、印が無くても起こさずに 1 行を出して終了コード 3 で止まる。WebFetch・WebSearch はこの鍵の外。
- 印の無い起動で見分けられない形（`--json-schema` が 2 つ、読めない JSON）は、足さずに素通しし、stderr に警告を 1 行出す。
- 印のある起動は柵なしで起こさない: `--settings` を読めない・混ぜられない、切符のファイルが在るのに読めない、会話の id を記録できない時は、claude を起こさずに 1 行を出して終了コード 3 で止まる。
- 印の跡（`works-node:`）が `--json-schema` のどこかに在るのに、一番上の `description` の印として読めない起動（知らない旗・大文字・余分な空白・入れ子の `description`・印を持つ `--json-schema` が 2 つ・壊れた JSON）は素通しせず、claude を起こさずに 1 行を出して終了コード 3 で止まる（黙って新しい会話で再審させず、柵を落とさない）。印の文法は `node_marker.parse` と同じ。
- 印に `no-post` を持つ起動（並行 PR の任せ先の役。読むだけ）は、gh を許す物の一覧で組む。Claude Code の permissions は deny が allow に勝つので、規則だけでは「gh を拒んで一部だけ許す」と書けない。そこで次の 3 つを組み合わせる。
  - `permissions.deny` で gh を丸ごと拒む（`Bash(gh:*)`・PATH の上の本物の gh の絶対パスの全部の綴り・`Bash(git push:*)`）。
  - 読む 4 つの形だけを通す口 `.shared/core/no-post-bin/works-gh` を、env の `WORKS_GH`（絶対パス）で役に渡す。通すのは `pr list`・`pr view`・`pr diff` を `-R <OWNER/REPO>` 付きで、と `repo view <OWNER/REPO>`。`--web` は拒む。役は `"$WORKS_GH" pr view 12 -R o/r` の形で呼ぶ。
  - 同じ口を PATH の頭に `gh` の名でも置く。`command gh`・`xargs gh`・`sh -c "gh …"` のように、前方一致の規則をすり抜ける呼び方も同じ一覧を通る。
- SDK が `--resume <id> --fork-session` で継ぐ起動（Archon が輪の中の節を続ける形）は、新しい会話の id が argv に出ないので、包みが `--session-id=<uuid>` を足してその id を記録する（元の id を記録すると、後の再審が古い会話を継ぐ）。
- 柵（線の `start` が切符 `<家>/tickets/<cwd の hash>.json` を書いた run だけ）: 切符の守る場所（共通の `.git`・ほかの worktree・盤面など）に、起動の時に引き直す `CLAUDE_CONFIG_DIR` と `git worktree list` の今の worktree を足し、`/var` と `/private/var`・`/tmp` と `/private/tmp` の両方の綴りで `permissions.deny`（`Edit(//<場所>/**)`・`Write(…)`）に足す。これで Bash・Edit・Write が止まる。SDK が sandbox の塊を渡した起動は `sandbox.filesystem.denyWrite` にも足す（これだけでは Bash しか止まらない）。役の cwd の worktree 自身は守らない（切符に在る `<cwd>/.git` は守る）。
- 起動ごとに `<家>/launches/<cwd の hash>.jsonl` に 1 行（時刻 `at`・節の名・足したか・柵の数・会話の id と継ぎ方と元の id `from`）を書く。引数の本文は書かない。再審の前の確かめは `adapter.session_path`・`adapter.last_launch` でこれを読む。
- 本物の claude は子として新しいセッションで起こす（標準入出力は継がせ、終了コードは子のまま）。走っている間は 0.2 秒ごとに木の仲間（グループ・セッション・親子の鎖。開始時刻で番号の再利用を見分ける）を数えて溜め、SIGINT・SIGTERM・SIGHUP を受けた時と claude が終わった後に、`tree_run.stop_group`（数え上げ→送る→数え直し。TERM → 2 秒 → KILL）で溜めた仲間ごと止める（claude の Bash の道具はコマンドを別のグループで走らせるので、claude だけを止めると SIGTERM を無視する孫が残る）。信号で止めた時は 1 秒待ってから抜ける（すぐ抜けると Archon の run が running のまま固まる）。上限の勘定は tree_run と同じで、Archon の cancel の猶予 5 秒より前に抜ける。
- 名前は `.js` で終わらせない（Archon が `.js` の実行ファイルに `--no-env-file` を足すため）。
- 版上げで壊れうる所（今は壊れていない）: SDK が `--json-schema` の渡し方・`--resume` の綴り・`--settings` の位置を変える、Claude がフックの入力の形を変える。版を上げたら `tests/adapter/argv/` の実物の argv を取り直す。

## 実走

本物の AI でライン `darkfactory` を 1 回回す殻が `works/dev/real-run.sh`（費用が掛かる。回す前に持ち主の了承を取る）。

1. `WORKS_KEYCHAIN_ITEM=<keychain の項目名> sh works/dev/real-run.sh [<dir>]` を前景で打つ。使い捨ての対象を作り、ライン（模型は `WORKS_DEV_MODEL`、既定は opus）を回し、人の関所で止まって戻る。
2. 関所の文面の「テストが緑か」「テストのログ」と、殻が出す「修正の差分がある worktree」を見る。修正は対象ではなく、Archon が run ごとに切った worktree の中にある。
3. 殻が出す approve のコマンドを打つ。承認はその場で続き（差分の審査）を回して終わる。`WORKS_KEYCHAIN_ITEM` で起こしたなら、出た行に項目名が載っているので、export していない殻でもそのまま打てる。`CLAUDE_CODE_OAUTH_TOKEN` だけで起こしたなら、値は出さないので、それを export した殻で打つ。`resume` は失敗・中断から続けるときだけ要る。

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

これから入れる物（実装前。どちらも盤面の層 [`docs/specs/2026-09-26-board-layer-design.md`](docs/specs/2026-09-26-board-layer-design.md) の上に載る）:

- 線 A（1 回の run を review-graph と同じ工程に強くする）: 設計 [`docs/specs/2026-09-27-darkfactory-single-run-design.md`](docs/specs/2026-09-27-darkfactory-single-run-design.md)・計画 [`docs/plans/2026-09-27-darkfactory-single-run.md`](docs/plans/2026-09-27-darkfactory-single-run.md)
- 線 B（直ったと言えるまで何周も回す入口 `darkfactory-rounds`）: 設計 [`docs/specs/2026-09-27-darkfactory-rounds-design.md`](docs/specs/2026-09-27-darkfactory-rounds-design.md)・計画 [`docs/plans/2026-09-27-darkfactory-rounds.md`](docs/plans/2026-09-27-darkfactory-rounds.md)
