# works

works は、AI に修正の仕事を任せるための Claude Code のプラグイン。

- 中の工場「darkfactory」が修正の依頼を受け取り、次の順で 1 本の流れとして回す。
  1. 調べる
  2. 何が問題かを判定する
  3. 直し方を計画する
  4. 直す
  5. 別の AI が差分を審査する
  6. テストを走らせる
  7. 別の目で確かめる
  8. 報告する
- どの工程でも、AI の返事は機械が形と中身を確かめ、通った時だけ次へ進む。人が確かめる所（関所）で止まるのは、始める時と、AI と機械が決めきれない時（最後の関所を毎回にする設定もある）。
- 流れの図と、工程ごとに何をしているかは [docs/darkfactory-flow.md](docs/darkfactory-flow.md) に在る。

仕組みの要点: Archon（AI の工程を YAML で書き、機械が順に回す道具）の上で動く pack。工程を並べるのは Archon に任せる。各工程の受け付けの規則と記録の検証器は、このリポジトリの既存のプラグイン graphloops から `.shared/core/` に写して使う。

## 入れ方（ほかのリポジトリで使う）

入口は Claude Code のスキル `skills/works/SKILL.md`（`/works`）。手順の正本はそこで、ここは要点だけ。

1. プラグインを 3 つ入れる。works と、works の AI の役が借りる 2 つ（coldwrite・pr-review-toolkit）。superpowers のスキルは works に写した固定の版を使うので入れなくてよい。リポジトリの clone は要らない。
   - `claude plugin marketplace add raiki61/claude-plugins`（登録済みなら `claude plugin marketplace update raiki61`）→ `claude plugin install works@raiki61`・`claude plugin install coldwrite@raiki61`
   - `claude plugin install pr-review-toolkit@claude-plugins-official`（marketplace `claude-plugins-official`（GitHub の anthropics/claude-plugins-official）が無ければ先に `claude plugin marketplace add anthropics/claude-plugins-official`）
2. 起動の殻 `dev/use.sh` と pack は、Claude Code が入れたプラグインの置き場（`~/.claude/plugins/cache/raiki61/works/<版>/`）の中に在る。スキルの行は、Claude Code がスキルを読む時にそこの絶対パスへ置き換える形（プラグインのスキルの置き換え CLAUDE_PLUGIN_ROOT）で書いてあるので、`/works` から打てばその置き場の `use.sh` が起きる。
3. 対象リポジトリで確かめる（AI を起こさない）: `sh <置き場>/dev/use.sh check <対象>`。最後の行が `Results: 1 valid, 0 with errors, …` なら入っている（Claude Code に組み込みのスキル `code-review`・`simplify`・`security-review` の WARNING の 3 行は出てよい）。借りる物が入っていなければ、足りない物ごとに 1 行の理由と入れるコマンドを出して止まる（`start` も AI を起こす前に同じ所で止まる）。uv・claude・認証・対象の条件で足りない物も、入れ方つきで全部並べて 0 以外で終わる。
4. 回す: `sh <置き場>/dev/use.sh start [--base <版> | --pr <番号>] [--] [<対象>] <依頼の JSON か -> ["<test_cmd>" [<tdd_suite>]]`（対象を省けば今いるフォルダの git の根。`--base`・`--pr` は変更の差分から入り、旗は対象より前に置く。変更だけなら依頼の JSON を `-`。この `-` は標準入力でなく依頼を省く意味。手元に commit していない変更が在ると包んだ commit が run の HEAD になるので、`--pr` は PR の head と違うとして拒まれ、`--base` の差分には包んだ変更も入る）。関所で止まるたびに次に打つ行が出る。`use.sh show <対象> [<run-id>]` で、その対象で start が結んだ一番新しい run（か名指しの run）の状態・報告の置き場・差分のファイルを出し直す。進める `use.sh approve <対象> <run-id>`・答える `answer`・関所で待つ run の `stop` は、残りの工程を切り離して回してすぐ戻る（出力は `<家>/logs/`）。その後は `use.sh wait <対象> <run-id>` が決まった時間のうちに戻って状態を返す。差分は `use.sh apply <対象> <run-id>` で当てる。run の worktree・枝・控え（包んだ基を守る参照と読み出しのファイル）と、修正の段がその worktree から切った単位の worktree・守りの参照（`refs/works/units/` の下）は自動で片付く: 正常に終わった・取り消した run（状態 completed・cancelled）は `wait`・`show` が差分を `<家>/diffs/` に書き終えた後に消し、落ちた run（failed）などの生きていない run は次の `start` が Archon を起こす前に差分を書いてから消す。走っている・関所で待つ run と、差分を書けなかった run は残す。差分のファイルと盤面は消さない。片付けた run は Archon の resume で続けられないので、修正は差分のファイルから `apply` で取り戻す。`start` が片付けた run の id と状態は、`start` の出力と、その起動の報告の冒頭 2（入口・段・決めた人の節）に 1 行で出る。手で片付けるのは `use.sh clean <対象> <run-id>`（自動の片付けと同じ中身）。関所には `use.sh answer <対象> <run-id> continue|stop "<一言>" "<答えた者>"` で答え（答えた者は必須。外したい単位と理由は一言に書く）（関所の文の答えの行もこの形）、止めるのは `use.sh stop <対象> <run-id> "<理由>"` の 1 つ。`start` は起動の直後に、この起動の依頼（`<家>/requests/` に写した物）を盤面に持つ run を 1 つに結び（一覧の先頭を推定で採らない。結べなければ候補の run id と show の行だけを出す。依頼を `-` で省いた start は、`--pr` なら隔離の前に読んだ読み出しのファイル（`<家>/reads/` の起動ごとに一意の物）で結び、`--base` だけなら結ばない）、run の控え（`<家>/runs/<run-id>.json`。模型・claude の実行ファイル・keychain の項目の名・包み）を書き、別の殻で打つ `answer`・`stop` はその値で Archon を起こし、`show` が出す進める・続きの行もその値で組む。

このリポジトリの clone で works 自身を直している時は、clone の `works/dev/use.sh` をそのまま打ってもよい（同じ殻で、pack はその clone の `works/` から写る）。marketplace の works の行（リポジトリ直下の `.claude-plugin/marketplace.json`）が GitHub に届く前の works を試すなら `claude --plugin-dir <clone>/works`。

`use.sh` の決まり:

- pack は対象に置かず、利用の家（`WORKS_USE_HOME`。既定 `${XDG_STATE_HOME:-~/.local/state}/works/use-<対象の clone の実際のパスの sha256 の頭 8 字>`。Archon は 1 つの家に同じリポジトリの clone を 1 か所しか登録できないので、clone ごとに分ける。家には、その家を作った clone の実際のパスを 1 行書いた目印 `target` を置く。前の既定の家 `works/use` に残っている run は `WORKS_USE_HOME=${XDG_STATE_HOME:-~/.local/state}/works/use` と名指せば続けられる）の Archon の全体の工程の置き場 `archon-home/workflows/works` に、起こすたびに写す。Archon v0.11.1 は `$ARCHON_HOME/workflows/<pack>/` も探す（実行ファイルの中の探し方で確かめ、使い捨ての対象で `validate`・`workflow test works` が通った）。
- Archon と AI の役は `archon.sh` を通してだけ起こす。家は開発の家（`WORKS_DEV_HOME`）を継がない（走っている自分食いの家を書き換えない）。
- run の worktree は `--from <対象の HEAD>` で切る。commit していない変更・未追跡のファイルが在れば、一時の index で包んだ commit（`.gitignore` の物は入れない。対象の作業ツリー・index・枝は動かさない。包んだ commit は `git gc` に消されないよう `refs/works/wraps/<commit>` にだけ参照を置く。参照は run の控え `<家>/runs/<run-id>.json` の `wrap_ref` に残し、`clean` がその控えの在る run と一緒に消す。`start` が run を結べなかった時は、起動が 0 で終わり生きた候補の run が在れば run が使うので外さずに候補と一緒に `<家>/unbound/` に控え、候補の run の `clean` が消す（ほかの候補が生きている間は消さず、最後の候補の `clean` で消す）。起動が落ちたか、読めた一覧で候補が無ければその場で外す。run の一覧が読めない時は生きた run が在るか分からないので外さず、候補の無い控えに残して 1 で終わる（その対象の生きた run が無くなった後の `clean` が消す）。控えに `wrap_ref` の無い run（この仕組みの前に起こした run）の参照は `clean` が知らないので残り、`git update-ref -d refs/works/wraps/<commit>` で外す）から切り、包んだことを起動と `show` に出す。対象は下のフォルダでもよい（git の根で回す）。`/private/tmp` の下・git のリポジトリの外は全部の命令が、pack の写し `.archon/workflows/works` が在る・remote の `origin` が無い・依頼・認証・uv・claude が無い時は `start` が何もせずに 1 行で止まる（`check` は全部並べる）。
- 最後の関所は既定で要る時だけ（`WORKS_USE_FINAL_GATE=always` で毎回）。Claude の包みは既定で通す（`WORKS_DEV_ADAPTER=0` で外すと `adapter=optional` と「包み無し」）。`WORKS_USE_UNATTENDED=1` は起動の関所を越え、人が決める関所に着いたら止めて報告へ進める（判定の保留の問いだけでは修正前の関所を開かず、問いの出どころだけを飛ばして直し、問いを報告の冒頭に並べる）。`WORKS_USE_UNATTENDED`・`WORKS_DESIGN_ONLY` は 1 か空だけを受け、ほかの値（`on` など）なら何も作らずに止まる。入力 `policy_md`・`gates`・`thickness` は `WORKS_USE_POLICY_MD`・`WORKS_USE_GATES`・`WORKS_USE_THICKNESS`。`thickness` の既定は自動（判定の単位ごとに機械が軽量か標準を決め、全部が軽量の run だけ差分の審査（とレンズ・手直し）と独立の目（コメントの削除候補と R1〜R4）を省いて報告の冒頭 2 に名指す）。`標準` で今の工程を全部回し、`軽量` で全部の単位を軽量に固定する。
- 木・枝の形の機能は run ごとに切れる（入力 `features_off`。`use.sh` は `WORKS_USE_FEATURES_OFF`、`dogfood.sh` は `WORKS_FEATURES_OFF`。同じ依頼を全部 on と切った形で回して比べる口。空は全部 on＝今どおり）。語をカンマで区切って並べる: `judge_verify`（判定の裏取りの下請けを起こさず、修正案の役に申し送りを貼らない）・`review_tree`（事前審査の項目ごとの下請けを起こさず、審査役 1 つが案の全体を審査する。項目が 1 つの案で木を使わない道と同じ受け付け）・`tdd_lanes`（TDD の輪の並べの周を使わず、tdd の単位を順に回す）・`fix_lanes`（修正役の項目ごとの単位の worktree を切らず、項目の下請けを作業ツリーで順に起こす）。知らない語は `start` が AI の前で止める。差分の審査の穴の枝の名札（木の段 4a）は表示だけなので切る口は無い。切った機能は run の `versions.json` の `settings.features_off`・盤面の start の控え・報告の冒頭 2 の頭の行（`機能: 全部 on` か `切った機能: …`）に残り、run どうしを並べて比べられる。run の呼び直しで替えれば止まる。固定材料（`fix_fixture`）から始める run は替えてよい（判定・修正案は写しの物のままで、効くのは `tdd_lanes`・`fix_lanes`）。
- 修正案を書く役の模型を比べるなら `WORKS_DEV_MODEL` を使う（下の「模型」の段落）。明示は表 `.shared/core/stage-models.json` に載った段（前付けの無い役の段）の全部に効き、修正案の段だけには絞れない。今の表では修正案の役（plan・plan-revise）だけが opus で、コードを書く役と軽い役は sonnet なので、`WORKS_DEV_MODEL=sonnet` の run と明示しない run（修正案の役は opus）を比べると、このラインで替わるのは修正案の役（plan・plan-revise）だけになる（仕様を書く役 spec-write・spec-revise もこの表で替わるが、このラインに無い）。`WORKS_DEV_MODEL=opus` はコードを書く役と軽い役も opus に替えるので、修正案の役だけの比べにならない。effort は段の値のまま、前付けを持つ役（判定役・事前審査役などの judge と blind-judge）は替わらない。包み（`WORKS_DEV_ADAPTER`）を外した run では明示が段に効かない。替えた段は報告の「## 模型」に段の宣言と並んで出る。
- `tdd_suite` を省くと、`test_cmd` が pytest の 1 コマンドの時だけ `--junitxml` を足す実行器を家の `suites/` に書いて渡し、そうでなければ空（直に直す）にして 1 行で知らせる。
- 差分は家の `diffs/run-<id>.diff`。当てるのは人（`apply` は `git apply --check` の後に当て、対象のファイルを消す差分は `WORKS_USE_ALLOW_DELETE=1` の時だけ当てる。記録が止まりを示す run（最後の関所の `stop`・止め札・ラインの止め）の差分は `WORKS_USE_ALLOW_STOPPED=1` の時だけ当てる。commit はしない）。
- works は自分の置き場（`works/`）の外のリポジトリを読まない。Claude Code はプラグインの置き場だけをキャッシュ（`plugins/cache/raiki61/works/<版>/`）に写し、`.git` も隣のプラグイン（`coldwrite/` など）も写さないため。借りる物は利用者が入れたプラグインから取る（下の「選んだ物だけの隔離した Claude の設定」）。pack に写す時は、Claude Code がキャッシュの版の置き場に置く印（`.in_use/`・`.orphaned_at`）を除く。

`archon plugin install raiki61/claude-plugins/works@<tag>` で入れて Archon を直に打つ形は、tag を打つまで入らず、入れても AI の役が利用者の本物の `~/.claude` を読む（下の「選んだ物だけの隔離した Claude の設定」）ので、まだ使わない。

## 要る物

- Archon v0.11.1 以上 0.12.0 未満（`archon-plugin.json` の `compatibility.archon` が `>=0.11.1 <0.12.0`。確かめたのは v0.11.1 だけ）。
- uv（script の節は `runtime: uv` で起きる）と git。節のスクリプトは PEP 723 の塊を持つので、対象が pyproject.toml を持っても uv は対象の project を拾わない（worktree に .venv・uv.lock を作らない）。既知の限界: 対象の uv の設定（`[tool.uv]`・`uv.toml`）は読まれるので、それが壊れているか、手元の uv に合わない `required-version` を持つと、works の script の節は起動時に終了コード 2 で止まる。直すのは対象か uv の設定。`UV_NO_CONFIG=1` を Archon の環境に立てて逃げるのは勧めない: 対象自身の uv の動きも変わり（テストのコマンドや修正役の Bash が私的な index を読まずに公開の PyPI から解決する）、偽の赤と依存の取り違えの口になる。
- 対象リポジトリには git の remote の `origin` が要る（Archon v0.11.1 は `--from` を渡しても、origin の無い対象では run の worktree を切れずに終了コード 1 で落ちる）。無ければ `dev/use.sh` の `check` が並べ、`start` は Archon を起こす前に止まる。入れ方は `git remote add origin <URL>`。預ける先が無く手元だけで回すなら、対象の外に `git init --bare <対象>.origin.git` を作って origin にし、`git push origin HEAD` の後に `git remote set-head origin <push した枝>` で `origin/HEAD` を置く（`dev/real-run.sh` と同じ形）。殻は対象の remote を書き換えない。依頼の JSON は対象の外に置いてよい（`dev/use.sh` は依頼を利用の家に写して渡す）。
- `start` は origin の既定の枝（`origin/HEAD` が指す枝、無ければ `origin/main`、次に `origin/master`）を Archon の土台（`--base`）に毎回渡す（Archon は対象を最初に登録した時の枝を覚えて更新しないので、登録した時の枝が消えても止まらない）。どれも無ければ枝を推さず、Archon を起こす前に `git fetch origin` と、それでも無い時の `git remote set-head origin -a`（または `git remote set-head origin <枝>`）を案内して止まる（裸の origin に機能の枝だけを push した対象は、fetch しても `origin/HEAD` ができない）。`origin/HEAD` が消えた枝を指す時（改名の後の `git fetch --prune`）は、それを渡さずに `origin/main`・`origin/master` へ進む。

## Claude Code のスキル

`skills/works/SKILL.md`（`/works`）に、入れ方・依頼の JSON の書き方・起動の 1 行（`dev/use.sh`）・人の関所での答え方・報告と差分の取り込み方を置く。Claude Code のプラグインの定義は `.claude-plugin/plugin.json`、配る行はリポジトリ直下の `.claude-plugin/marketplace.json` の `works`（source `./works`）。

## 開発の回し方

テストは `works/tests/run.sh`。実際に Archon の上で回す手順（実行ファイルの取得・使い捨ての対象作り・`archon workflow test` 相当の検査・自分食い）は `works/dev/` を見る。キャッシュした Archon の実行ファイルの sha256 が合わないときは、止まった時の 1 行に出るそのファイルを消して回し直せば取り直す（殻は消さない）。

線の中の書く役（修正・TDD の輪・手直し）は一式を回さず、直した単位に当たる試験だけを絞って回す（決まりの正本 [`works/.shared/core/writerules/common.md`](.shared/core/writerules/common.md#守ること) の「守ること」）。一式の緑は線の最後のテストの段が確かめ、TDD の実行器が在る run では修正の受け付け（`fix-accept`）が版からの変更に当たる試験を機械で選んで回す。直しながら回すのは速い段 `WORKS_TESTS=fast sh works/tests/run.sh [-k 名前]`（試験ごとに git のリポジトリを作らない・uv run・Archon・golden・プロセスの木・決まった秒の待ちを使わないモジュールだけ。種の git を `works/tests/gitkit.py` の型の写しで配るのは可。`WORKS_TESTS=heavy` は残りの重い段で、2 つを合わせると全部）。作業の終わりと merge の前は、既定（何も付けない）の全部を回す。CI は全部を `WORKS_SHARD=<番号>/<組の数>`（番号は 0 起点）で 4 組に分けて別の runner で並べる（分け方は `tiers.py` の `shard_of`。組の和がちょうど全部なのは `test_tiers` が縛る。回すモジュールの名前だけを見るのは `python3 works/tests/tiers.py list <fast|heavy|all>`）。どのモジュールがどちらの段かは `works/tests/tiers.py` に 1 か所で書き、新しいテストのモジュールはどちらかに書き足す（書き忘れると段を選んだ実行とテストが止める）。全部と heavy は、機械全体で重いテストを同時に 4 本までにする枠の台本（mainline の `testslot.sh`。既定の置き場は `/Users/p03623/src/claude-plugins/.git/graphloops/ops/testslot.sh`、`WORKS_TESTSLOT` で差し替え。枠の置き場は台本の約束 `TESTSLOT_DIR`（既定は `/private/tmp/claude-<uid>/testslots`）で、`works/.shared/core/slotwrap.sh` が解決して台本へ渡す。約束の正本はこの 1 本）を通して、枠が空くまで期限なしで待ってから回る。台本が無い・枠の置き場に書けない（サンドボックスの中など）ときは、1 行出して枠を取らずに回す（`WORKS_TESTSLOT` を空にして、中の試験が起こす段にも同じ 1 行を繰り返させない）。枠を持つ台本の下から呼ばれたら取り直さない。run の中で試験を起こす口（engine の宣言の段・`test_cmd`・blk-tests の plain と mid・TDD の輪と修正の受け付けの実行器）も `tree_run.slotted_run` から同じ `slotwrap.sh` を通るので、並べた run の重い試験も同時に 4 本まで（それぞれ宣言の xdist が最大 4 worker で 16 ≤ 24 コア）。枠を待つ前に段のログへ 1 行出し、run の中では盤面の `testslot.json` に待ち・枠の中を書く（段が終われば消す）。`works_dev_show_run`（use.sh の show）はそれを `試験の枠: 待っている（N 分…）` の 1 行で、herdr の集計は `走る N（うち枠待ち k）` で出す（人の答えの要る待ちではないので blocked にしない）。枠を取った段は待った秒を `wait_s` に分けて記録し、`wall_s` は実行の時間のまま。TDD の実行器は外の `tddloop.run_suite` が `nice -n 19` を付けて枠を取り、待った秒を `suite-<n>.log` の末尾に書く（ADR [0071](../docs/adr/0071-test-sizes-and-where-they-run.md) の 3 の 1）。速い段と TDD の実行器の中は `WORKS_TESTSLOT` を空にして、中の試験が起こす試験にも枠を取らせない（外で取った枠と二重に数えない）。

TDD の修正の段が使うテストの実行器（ラインの入力 `tdd_suite`）は `works/dev/tdd-suite.sh <JUnit XML の書き先> [pytest の引数]`。同じ試験を既製の pytest で回し、結末を JUnit XML に書く。段は `WORKS_TDD_TIER`（既定 fast・heavy）で、段のファイルは `tiers.py` の `paths` の口から引く。枠の台本と nice は、この殻を起こす外の `tddloop.run_suite` が付け、中の試験が起こす試験には取らせない（`WORKS_TESTSLOT` を空にする）。後ろの pytest の引数のうち、ファイル・node id は段の外の試験を集める先に足し（呼ぶ側の cwd からの相対か絶対パス）、`-k` は集めた中を絞る。試験の根（パスから上へ辿って最初に `conftest.py` が在る置き場。辿り着かなければ works の根）が違う名指しは、1 つのプロセスに 2 つの engine を載せないよう根ごとに別の pytest で流し（works の根を先に）、根ごとの JUnit は `junitparser merge` で書き先の 1 つに合わせる。終了コードは各プロセスの最大で、`-k` などで 0 件（5）の根は、ほかの根が 1 つでも走っていれば赤にしない。TDD の輪の赤・緑の回は env `TDD_SUITE_ONLY=1` を付けて呼び、殻は後ろに足した試験が在れば段の一覧を集めずそれだけを走らせる（赤は名指しだけ、緑は名指しと単位の変更が届く元の一式のモジュールのファイル。届く試験が分からなければ合図なしの一式）。TDD の輪は名指しを段の中か外かに依らず全部、受け付けは選んだ試験のうちこの run で変えた・足した pytest の試験のモジュール（`test_*.py`・`*_test.py`）だけを、絶対パスで後ろに足して回す（段のファイルと重なって同じ試験が 2 行載れば、輪が 1 件にまとめて数える）。届いただけで段の外の試験は手元で回さず、『手元で回さなかった』として受け付けの知らせ・盤面の trace（`fix_tests_selected` の `ci_left`）・最後の人の関所に名前で並べる。読み込みで落ちるモジュールが在っても一式を止めず（`--continue-on-collection-errors`）、そのモジュールは error の 1 行で載る。unittest と pytest では結末の数え方が一部違う（例外で落ちた試験は unittest では error、pytest では failure。`-k` は unittest では名前の部分一致、pytest では式）。pytest は一番外の `def test_*` も試験として拾うので、試験の道具の関数は `test_` で始めない（`test_tiers` が縛る）。

`works/dev/archon.sh`（固定した版の Archon を隔離して回す殻）の認証は、利用者自身の物だけを拾う（どこかの口座で黙って回さない。R20）。順は起こし役 `.shared/core/auth_launch.py` が持ち、真ん中は本流 `scripts/claude_auth.py` の写し（`.shared/core/claude_auth.py`。`scripts/shared-copies.py` が同一を縛る）の `auth_env` を丸ごと呼ぶ。AI を呼ぶ実行（`workflow run`・`workflow approve`・`workflow resume`、`dev/real-run.sh`）で、上から順に:

1. `WORKS_KEYCHAIN_ITEM`（トークンを入れた macOS の keychain の項目名）。その起動で名指した物なので、受け継いだ `CLAUDE_CODE_OAUTH_TOKEN` などより先に効き、子の環境からそれより上に効く資格（`ANTHROPIC_API_KEY`・`ANTHROPIC_AUTH_TOKEN`・クラウドの旗）を外す。空・`sk-ant-oat01-` で始まらない値なら次へ進まず止まる
2. 本流の段: 受け継いだ認証（`CLAUDE_CODE_OAUTH_TOKEN`（`claude setup-token` で作るトークン）・`ANTHROPIC_API_KEY` など）、無ければ keychain の `CLAUDE_KEYCHAIN_SERVICE` の項目か、設定の置き場から導く `claude-code-oauth-<名>`（`~/.claude` なら `default`、`~/.claude-p3` なら `p3`）
3. macOS で Claude Code 自身が keychain に置いたログインの項目（`CLAUDE_CONFIG_DIR` を設定していれば `Claude Code-credentials-<その値の sha256 の頭 8 桁>`、次に `Claude Code-credentials`。値の `claudeAiOauth.accessToken`）。ログインのトークンは数時間で切れるので、長い run にはトークンを置く。項目の名の付け方は Claude Code の版で変わりうる

keychain は隔離の前の利用者の HOME で読む。拾った出どころの名を 1 行出す（値は出さない）。トークンは殻の変数・標準出力を通らず、起こし役が同じプロセスから Archon を起こす時に子の環境にだけ置く（Archon の前に起こす `claude plugin` の CLI と `claude --version` には渡さない。認証は要らない）。keychain は実行ファイルに触る前の確かめと最後の起動で 2 回読む（`use.sh` から起こした時は確かめを `use.sh` が済ませる）。どれも無ければ、案内を 1 行出して止まる（keychain に既に在る項目の名指しを、トークンの新規作成より先に案内する）。gh・git の資格は隔離した家の役に渡さない（役ごとに分けて渡せないため。隔離した家の gh は未ログインで、並行 PR の確かめは gh の失敗の理由つきで人に回る）。`WORKS_DEV_NO_AUTH=1` のときは認証を読まない（テスト・`validate`・`workflow test` 用。`dev/check.sh` は付けて回すので認証が要らない）。

認証を使う実行のたびに、`archon.sh` は隔離した Archon の設定（`$WORKS_DEV_HOME/archon-home/config.yaml`）に模型を書く（`WORKS_DEV_MODEL`。空か未設定なら `dev/guard.sh` の `WORKS_DEV_MODEL_DEFAULT`（環境では替わらない）。既定を埋めるのは `archon.sh` だけで、入口の殻は埋めない。明示か既定かは `WORKS_MODEL_FROM` に残して下へ渡す。明示せずに起こした run の続き・答えの行は、start の時の既定を `WORKS_MODEL_PINNED` に添えて起こす（`archon.sh` はそれで解いて出どころに名を残し、Archon には継がせない）。run の題を作る模型 `TITLE_GENERATION_MODEL` も、設定していなければ同じにする）。書かないと Claude CLI の既定の模型で黙って回る。`WORKS_DEV_NO_AUTH=1` のときは書かない。この設定の模型は全体の既定で、Archon は段の `model:`・工程の `model:`・この設定の順に先のものを使う。works の YAML は、AI の段（`prompt:` か `command:` を持つ段）の全部に `model:` と `effort:` を書く（持ち主 2026-10-06）。役の前付け（`.shared/core/agents/<役>.md` の `model`・`effort`）を持つ役の段は前付けと同じ値（今は judge・blind-judge が opus・high、inspector・investigator・cold-reader が sonnet・medium）、前付けの無い役の段は表 [.shared/core/stage-models.json](.shared/core/stage-models.json) の値（試験 [tests/test_tool_parity.py](tests/test_tool_parity.py) は同じ表を `STAGE_MODEL` に読む）で、仕分けは次の 3 つ: 修正案・仕様を書く役（blk-plan の plan・plan-revise、blk-spec の spec-write・spec-revise）は opus・medium、コードとテストを書く役（blk-fix の tdd・fix・fix-ruled、blk-refix の refix・refix2）は sonnet・high、読んで確かめる・まとめる軽い役（借りたレンズ、r1-comments、CI・pr-check の任せ先、前提の実測、目的の文、素材集めの任せ先と局所レビュー、報告の書き手）は sonnet・medium。試験は欠けも表との食い違いも名指すので、値を替えるときは表と段を一緒に直す。だから既定（`dev/guard.sh` の `WORKS_DEV_MODEL_DEFAULT`。今は sonnet）が効くのは run の題だけで、段の模型は替わらない。`WORKS_DEV_MODEL` を明示した run では、包み（`WORKS_DEV_ADAPTER=1`。`use.sh`・`dogfood.sh` の既定）が表 `stage-models.json` の段（前付けの無い役の段）の起動の `--model` をその値に替える（`.shared/core/adapter.py` の頭の 19。前は前付けに模型の無い段が設定の模型で走り、`WORKS_DEV_MODEL=opus` でその段を opus にできた。段ごとの明示へ替えた時にこの力が落ちたので戻した。[CHANGELOG.md](CHANGELOG.md#unreleased)）。effort は段の値のまま、前付けを持つ役の段（judge・blind-judge・inspector・investigator・cold-reader）は替えない。明示は run の控えに残り、続き・答えの行も同じ値で起こすので、run の間ずっと効く。包みが既定を明示と取り違えないよう、`archon.sh` は解いた既定を `WORKS_DEV_MODEL` に書き戻さない。段の `model:` は Archon 自身が読んで Claude に渡すので、包み（`WORKS_DEV_ADAPTER`）を外した run でも同じに効くが、明示の模型で段を替えるのは包みだけなので、包みを外した run では `WORKS_DEV_MODEL` は run の題にしか効かない（`archon.sh` が 1 行で言う）。

effort も、Archon の段が役の前付けを読まないので、段に書く（前付けを持つ役は前付けと同じ値、無い役は表 `stage-models.json` の値。工程の頭には書かない）。書かないと Claude Code の既定（opus は medium、sonnet は high）で黙って走る。一致は欠けも含めて [tests/test_tool_parity.py](tests/test_tool_parity.py) が全部の段で見る。段の中で役が起こす下請け（blk-plan の plan-review が項目ごとに起こす general-purpose の下請け、修正役が項目ごとに起こす下請けなど）は、模型は親の段を継ぐが、effort を継ぐかは Claude Code の文書に書かれていない（works は下請けの effort を指定しない）。段の `effort:` は段ごとの設定なので、`WORKS_DEV_MODEL` のような全体の設定では替わらない（包みが明示の模型で段を替える時も effort は段の値）。ただし Archon v0.11.1 がそれを Claude の起動にどう渡すか（`--effort` の旗か、SDK の別の経路か）は、まだ実の run で確かめていない。包みは起動の記録（launches）の `effort` に Archon が渡した `--effort` を残すので、実の run の後にそこが前付けの値か（`None` なら旗では届いていない）を見て確かめる。

対象（`archon.sh` を打つ cwd）の根の mise の設定を利用者が `mise trust` 済みなら、認証を使う実行のたびに `archon.sh` は隔離の前にそれを `mise trust --show` で読み、run の worktree の置き場（`$WORKS_DEV_HOME/archon-home/workspaces`）を `MISE_TRUSTED_CONFIG_PATHS` に足す（mise の公式の設定。前の値は残す）。mise の信頼はパスに結び付くので、足さないと run の worktree の中のテストで設定が信頼されず、道具の失敗が偽の赤になる。信頼していない対象では足さない。

開発の家（`WORKS_DEV_HOME`。既定は `$TMPDIR/works-dev`）・使い捨ての対象・その origin は、Claude Code の一時フォルダ（`/private/tmp/claude-*`・`/tmp/claude-*`）の下に置けない。サンドボックスの中の Bash がそこへ書けるためで、`dev/` の殻はその下に解けるパスを終了コード 2 で拒む（設計書 7 節）。

run ごとの版は、線の `start` が盤面の隣 `artifacts/runs/<run id>/versions.json` に書く（`.shared/core/versions.py`。入力を拒む run でも書く）: pack の中身の sha256・写した元の works の commit と手元の書き換えの有無と works の版（`dev/lib.sh` が pack の写しに置く `.works-source.json`。元の works が git で追跡されていない時（プラグインのキャッシュから起こした時）は commit と書き換えの有無が null で、版は `.claude-plugin/plugin.json` の version）・`VERSION`・graphloops の写しの行・借りた物の版（`$CLAUDE_CONFIG_DIR/.works-toolset.json`）・Archon の版と Claude Code の `--version`（`archon.sh` が env の `WORKS_ARCHON_VERSION`・`WORKS_CLAUDE_VERSION` で渡す）。全体の模型の要求と出どころ（`model`。`archon.sh` が渡す `WORKS_DEV_MODEL` か `WORKS_MODEL_RESOLVED` と `WORKS_MODEL_FROM`）も載る。分からない値は null にして、`unknown` に理由を書く。節ごとの模型は、包みが起動の記録の `model` に子へ渡した `--model` を残し（`--effort` も同じく `effort` に残す。effort は読むだけで変えない。明示の模型で段の `--model` を替えた起動は `model_declared` に段の宣言も残す）、報告の「## 模型」の節が全体の値と節ごとの値（run の途中で替われば全部。替えた段は段の宣言も）を出す。Archon の `metadata.model_bindings` は応答から推した名で、works の記録の元にしない。

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

## 選んだ物だけの隔離した Claude の設定（借りた superpowers のスキルと部品・coldwrite・pr-review-toolkit）

AI の節は全部 `settingSources: [user]` で、開発の殻 `dev/archon.sh` が隔離した `$WORKS_DEV_HOME/claude-config`（`CLAUDE_CONFIG_DIR`）を読む。そこに置くのは許す一覧 `.shared/borrow/borrow.json` の物だけで、`dev/toolset.py` が実行のたびに組む。対象の CLAUDE.md（project）は読ませない。

- superpowers は、works に写した固定の版（`.shared/borrow/superpowers/<版>/`。写しを作り直すのは `dev/toolset.py vendor <版>` だけ）から入れる。利用者が入れた superpowers の版は run に使わず、開発の再開の確かめ（CLI `newer`）が比べるだけ。入れる前に、写しの使うファイルを `borrow.json` の `superpowers.pin` の sha256 と照らし、合わなければ違うファイルを 1 行ずつ名指して何も写さずに止まる。
- coldwrite・pr-review-toolkit は、利用者が Claude Code に入れたプラグインから取る（本線の graphloops と同じ。版は Claude Code が今に保ち、入れた版をそのまま使う。works は写しを持たない）。探すのは、隔離の前の利用者の設定の置き場（`CLAUDE_CONFIG_DIR`、無ければ `~/.claude`。`archon.sh` が隔離の前に決めて `toolset.py --user-config` で渡す。相対の値は殻が cd の前に絶対パスに直し、隔離した置き場と同じなら `toolset.py` が名指しで止まる）の `plugins/installed_plugins.json` の `<名>@<marketplace>` の行（Claude Code と同じく local > project > user の scope の行。local・project は `projectPath` が対象リポジトリの行だけ）。`enabledPlugins` で無効にしてあっても借り、利用者の側の値を記録の `source_enabled` に残す。
- coldwrite・pr-review-toolkit で確かめるのは works が名前で頼る物だけ: pr-review-toolkit の agent のレンズ（`agents/<名>.md`。borrow.json の `agents`。写しの graph が名指しする物を全部含むことを `tests/test_toolset.py` が見る）、coldwrite の `PreToolUse` の `Write` の hook（`hooks/hooks.json`）。中身・版・バイトは見ない（役は読むだけなので、名前が在れば新しい版で動く）。入っていない・名前が無い物は、1 物 1 行の理由と入れるコマンドを出して止まり、Archon を起こさない。
- superpowers（Claude Code のプラグインのスキル集）の写しから、test-driven-development・systematic-debugging・verification-before-completion・receiving-code-review・requesting-code-review の 5 本だけを設定の `skills/` へ、部品（スキルとしては使わず、中の文を役の指示書に使うファイル。SDD の `implementer-prompt.md`・`task-reviewer-prompt.md`）を `works-parts/superpowers/<相対パス>` へ、バイトのまま写す。プラグインとしては入れない（有効にすると SessionStart の hook が using-superpowers を差し込み、無人の役の約束が崩れる）。節は `skills: [<名>]` で名指ししてよく、名前は borrow.json の一覧の中だけ（`tests/test_yaml_rules.py`）。
- coldwrite（書く散文の初見検査の PreToolUse:Write のフック）と pr-review-toolkit（素材集めの局所レビューのレンズの agent）は、入れた置き場を設定の中の手元の marketplace `works-local`（`works-marketplace/`）に写し、Claude Code の CLI（`claude plugin marketplace add`・`claude plugin install <名>@works-local`）で入れる。中身が変わった時だけ入れ直す（Claude Code のキャッシュの印 `.in_use/`・`.orphaned_at` は写さず、比べもしない）。CLI の後に `settings.json` の `enabledPlugins` に載っていなければ止まる。認証の要らない道（`WORKS_DEV_NO_AUTH=1`。validate・テスト）は claude を起こさず、スキルだけを写す（借りる物の確かめは同じ）。
- 入れた版（coldwrite・pr-review-toolkit は `installed_plugins.json` の行の version、superpowers は pin の版と commit）と置き場と中身の sha256 は、見えるようにするために `.works-toolset.json` に残し、run ごとの `versions.json` の `borrowed` に載る。
- Context7（ライブラリの今の文書の MCP。upstash/context7・MIT）は、使用許諾が MIT・Apache-2.0・BSD の時だけ設定の置き場の `works-mcp.json` に遠くの口 `https://mcp.context7.com/mcp` を書く（外れなら何も写さずに止まる）。Archon の役の節は周りの MCP を読まない（`--strict-mcp-config`）ので、包みがこのファイルを web を持つ役に `--mcp-config` で渡す（既定は渡さない。`WORKS_CONTEXT7_MCP=on` の時だけ。下の「Claude の包み」）。これとは別に、修正役と修正案の役の支度の節が Context7 の HTTP API から単位のライブラリの文書を取り、指示書の節「ライブラリの今の文書（Context7）」に貼る（`.shared/core/libdocs.py`。鍵は env の `CONTEXT7_API_KEY`、無ければ鍵なしの低い上限。`WORKS_CONTEXT7=off` で網に出ない）。
- 柵: 一覧の外（CLAUDE.md・rules/・agents/・commands/・output-styles/・settings.json 以外の settings*.json・一覧の外のスキル・`works-parts/` の下の部品の外のファイル・settings.json の `enabledPlugins`・`extraKnownMarketplaces` 以外の鍵・ほかのプラグインと marketplace）が在れば、名前を出して終了コード 2 で止まる（`archon.sh` も Archon を起こさない）。Claude Code が自分で書く状態（projects/・.claude.json・backups/・plugins/cache/ など）は見ない。手で確かめるなら `python3 dev/toolset.py guard <置き場>`。
- **開発の殻の外では隔離されない。** 利用者が自分の Archon で pack を入れる場合、`CLAUDE_CONFIG_DIR` は利用者の本物の `~/.claude` で、`[user]` の節は利用者の CLAUDE.md・hooks・プラグインを読む。殻の外の入れ方（利用者のキャッシュから選ぶ版上げと関門）は P1 計画 Task 21。
- 無人の読み替え: スキルの文が人（your human partner）や下請けの AI を前提にする所は、`.shared/borrow/unattended.md` の決まりで読み替える。借りたスキルを読める役（道具に Skill を持つ役）の指示書に、支度のスクリプトがその全文を載せる（`.shared/core/rolekit.py` の `skill_overlay`）（直す義務の単位は必ず直して `changes` に載せ、判定への異議は `rejudge_requested` に、人に聞きたいことは食い違いの申し出（`which_is_right` は unknown・`kind` は `needs_context`。裁定役が人に回す）に書く。`not_done` は受け付けが免除する単位と義務の外の単位だけ。修正役は commit しない、`superpowers:` の参照は無視、など）。
- 試験は本物のプラグインも利用者の設定も読まない（superpowers は works の写しを読む）。`tests/test_toolset.py` が偽の利用者の設定（偽のプラグインを入れた形）を作って回すので、プラグインの入っていない CI でも通る。

## Claude の包み

`.shared/core/claude-adapter` は、Archon が起こす Claude Code の実行ファイルの前に挟む薄い殻（芯は `.shared/core/adapter.py`）。役が読んだファイルの記録・再審の役が判定役の会話の続きで起きること・役に書かせない場所の柵・止める時に孫まで止めることを受け持つ。形は本物の Archon v0.11.1・SDK 0.3.282・claude 2.1.283 との有料の試しで確かめ、試験（`tests/test_adapter.py`）は偽の claude で縛る。今のラインの YAML はまだ印を持たないので、入れても何も足さずに素通しする（印を付けるのは線 A の後の作業）。

入れ方:

1. Archon の設定 `assistants.claude.claudeBinaryPath` に包みの絶対パスを書く（これが主。env の `CLAUDE_BIN_PATH` は設定より強いので、一時の上書きに使える）。
2. 本物の claude を `WORKS_REAL_CLAUDE`（絶対パス）で渡す。無ければ包みは PATH の実行ファイル `claude` を使う（包み自身を指す物は飛ばす）。
3. 置き場（包みの家）を `WORKS_ADAPTER_HOME` で渡す。既定は `${XDG_STATE_HOME:-~/.local/state}/works/adapter`（切符と同じ）。絶対パスでなければ包みは起動を拒む。役の sandbox の Bash から書けない場所に置く（`/private/tmp/claude-*` は不可）。
4. 開発の殻では `WORKS_DEV_ADAPTER=1` を付けて `dev/archon.sh`・`dev/real-run.sh` を打つ（`dev/dogfood.sh`・`dev/use.sh` は付けなくても既定で包みを通す。外すなら `WORKS_DEV_ADAPTER=0`）。`archon.sh` が隔離した設定に `claudeBinaryPath` を書き、`CLAUDE_BIN_PATH` を `WORKS_REAL_CLAUDE` へ移し、家を `$WORKS_DEV_HOME/adapter` にする。殻が出す承認・続きのコマンドにも同じ札が付く。

包みがすること・しないこと:

- どの節の起動かは、役の `output_format` の一番上の `description` に置く印 `works-node: <節の名>[ continue=<継ぐ節の名>]` で見分ける。SDK がそれを argv の `--json-schema` に載せる。印の無い起動（Archon が run の題を作る `--tools ""` の起動など）は、下の網の閉じのほかは argv を 1 バイトも変えない。
- 印のある起動には、`--settings` に PostToolUse:Read のフック（`.shared/core/record-read.py`。graphloops の写しで、書く先だけ替えた）を足す。SDK が渡した `--settings`（sandbox）の鍵は上書きしない。`--settings` が無い節にはフックだけの `--settings` を足す。`--setting-sources`・`--model` ほかの旗は触らない（CLAUDE.md を止めるのは YAML の `settingSources: [user]` と隔離した設定の柵 `dev/toolset.py`。`--model` は下の run の明示の模型の時だけ替える）。
- 同じ `--settings` に PostToolUse:Edit|Write|NotebookEdit のフック（`.shared/core/record-write.py`）も足し、書いた後のファイルの sha を `<家>/reads/<cwd の hash>/writes.jsonl` に 1 行ずつ書く（包みが印のある起動の前に空のファイルを作る）。書く役の受け付け（blk-fix の `fix-accept`・`tdd-step`）は版からの変更をこの記録と返答の欄 `bash_writes`（Bash で書いたファイルのパスと理由）に突き合わせ、どちらも無い変更を拒む。射程は今の中身を編集の道具が書いたか申告したかまでで、Bash で書いた後に同じ中身を Edit で書き直した物は区別しない（出どころの全部は証さない）。手直しの役（blk-refix）の返答は写しの graph の形のまま申告の欄を持たないので、拒まずに報告に出す。記録のファイルが無い run（包みが無い起動）は突き合わせずに通し、報告に「書き込みの記録が無い run」の行を出す（`.shared/core/writes.py`）。
- 読んだ記録は `<家>/reads/<cwd の hash>/reads.jsonl` に、ファイルの sha と部分読みかを 1 行ずつ書く。形は graphloops のままなので engine の `hook_evidence` がそのまま読む。Claude の子の env には `ARTIFACTS_DIR` が来ないので、run は cwd（Archon が run ごとに切る worktree）で分ける。
- 判定役（`works-node: judge`）は、包みが `--session-id=<uuid>` を足して起こし、id を `<家>/sessions/<cwd の hash>/judge.id` に書く。SDK が自分で `--resume`・`--session-id` を付けた起動はその id を記録する。
- 再審（`works-node: rejudge continue=judge`。YAML の節は `context: fresh`）は、SDK の会話の旗を外して `--resume <judge の id>` で起こす（fork しない）。id が無ければ子を起こさず、1 行を出して終了コード 3 で止まる。ただし Archon はこれを落ちた起動として約 12 回起こし直すので、先に script の節で id が在るかを見る。再開した節の費用の表示は判定役の分を重ねて数える（SDK の `total_cost_usd` が累積のため）。
- 網を閉じる（印の有無に依らない）: Archon は役を bypassPermissions で起こし、YAML の `sandbox.network` から `strictAllowlist` を捨てる。この形の Claude Code（2.1.283）は、`allowedDomains` に無い宛先への Bash の通信を自動で通す。そこで包みは、`--settings` の `sandbox.network.allowedDomains` が `*` を含まない配列の起動に `strictAllowlist: true` を足す（`*` の網・網の一覧の無い sandbox は触らない）。`--settings` が読めない・2 つ・sandbox や網の形が違う起動は、印が無くても起こさずに 1 行を出して終了コード 3 で止まる。WebFetch・WebSearch はこの鍵の外。
- 借りる MCP を渡す（印のある起動だけ。**既定は渡さない**）: env の `WORKS_CONTEXT7_MCP=on` の時だけ、設定の置き場に `works-mcp.json` が在れば、`--tools` に WebFetch を持つ起動に `--mcp-config=<ファイル>` を足す（役が書く問いは対象のコードの字を外のサービスへ運びうるため、持ち主が決めるまで安全側）。web を持たない役・道具ゼロの役・SDK が自分の `--mcp-config` を渡した起動には足さない。読めなければ足さずに起動の記録の `fence.mcp` に理由を書く。
- 検索語の規律を足す（印のある道具を持つ起動だけ）: 写しの `.shared/core/agents/judge.md` の「検索語に対象の名前を載せるな」の塊を字のまま切り出し、`--append-system-prompt` で役に渡す（SDK の値が在れば後ろに繋ぐ）。works の役は agents/*.md を読まないため。SDK が `--append-system-prompt-file` を渡した起動・塊を引けない起動は起こさない。塊の sha の先頭 16 字を `fence.query_rule` に残す。
- 対象の持ち主の禁止を写す（印のある起動だけ）: 役は対象リポジトリの project の設定の段を読まないので、役の cwd の worktree の根の `.claude/settings.json`・`.claude/settings.local.json` の `permissions.deny` だけを `--settings` の `permissions.deny` の後ろに足す（allow・ほかの鍵・CLAUDE.md・フックは読まない。本流 `graphloops/engine/role_run.py` の `repo_deny` と同じ読み方）。足した数を `fence.repo_deny` に残す。ファイルが読めない・`permissions.deny` が空でない文字列の配列でない起動は、そのファイルを名指して起こさない。
- engine の子の目印（印のある起動だけ）: 子の env に `GRAPHLOOPS_ENGINE_CHILD=1` を立てる（役の Bash の子にも継がれる）。本流 `graphloops/engine/role_run.py` の `ENGINE_CHILD_ENV` と同じ名なので、対象の `tests/run.sh` などが既に読む形のまま、AI の役からの重い一式を拒める。線の節が走らせる一式は包みを通らないので立たない。
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
- 指示書の全文版と差分版（トークンの節約）: 支度のスクリプトが指示書（`prompt_file`。既定は全文版の写し）の隣に `<stem>.full.md`・`<stem>.delta.md`・`<stem>.variants.json`（`{full, delta, rules_sha, iteration, sections}`）を書くと、包みは印のある起動の stdin を中継し（バイトは変えない）、最初の指示文が名指す指示書に、子へ渡す前に全文版か差分版を書く。差分版は、継ぐ会話（fork の鎖を包みの起動の記録で辿る）が同じ `rules_sha` の全文版をこの包みから受け取り、Read のフックの記録で読み切り、会話の記録（`$CLAUDE_CONFIG_DIR/projects/*/<id>.jsonl`）に要約・古い道具の結果の消去の跡が無い時だけ。差分版の頭には全文版のパスを名指す 1 段を足す（会話から規則が消えていたら読み直させる）。ほかは全文版。`variants.json` が無ければ何もしない。選んだ版と理由は起動の記録の `prompt` に残る（Archon の DB のトークンと突き合わせる）。
- 本物の claude は子として新しいセッションで起こす（標準出力・標準エラーは継がせ、標準入力は印の無い起動は継がせ・印のある起動は上の版を決めるために中継し、終了コードは子のまま）。走っている間は 0.2 秒ごとに木の仲間（グループ・セッション・親子の鎖。開始時刻で番号の再利用を見分ける）を数えて溜め、SIGINT・SIGTERM・SIGHUP を受けた時と claude が終わった後に、`tree_run.stop_group`（数え上げ→送る→数え直し。TERM → 2 秒 → KILL）で溜めた仲間ごと止める（claude の Bash の道具はコマンドを別のグループで走らせるので、claude だけを止めると SIGTERM を無視する孫が残る）。信号で止めた時は 1 秒待ってから抜ける（すぐ抜けると Archon の run が running のまま固まる）。上限の勘定は tree_run と同じで、Archon の cancel の猶予 5 秒より前に抜ける。
- 名前は `.js` で終わらせない（Archon が `.js` の実行ファイルに `--no-env-file` を足すため）。
- 版上げで壊れうる所（今は壊れていない）: SDK が `--json-schema` の渡し方・`--resume` の綴り・`--settings` の位置を変える、Claude がフックの入力の形を変える。版を上げたら `tests/adapter/argv/` の実物の argv を取り直す。

## 実走

本物の AI でライン `darkfactory` を 1 回回す殻が `works/dev/real-run.sh`（費用が掛かる。回す前に持ち主の了承を取る）。

1. `WORKS_KEYCHAIN_ITEM=<keychain の項目名> sh works/dev/real-run.sh [<dir>]` を前景で打つ。使い捨ての対象を作り、ライン（段の模型は YAML の AI の段ごとに書いた `model:`。`WORKS_DEV_MODEL`（未設定なら `archon.sh` が `dev/guard.sh` の `WORKS_DEV_MODEL_DEFAULT` を解く）は run の題に効き、明示すれば包みを通した run の前付けの無い役の段にも効く）を回し、人の関所で止まって戻る。
2. 関所の文面の「テストが緑か」「テストのログ」と、殻が出す「修正の差分がある worktree」を見る。修正は対象ではなく、Archon が run ごとに切った worktree の中にある。
3. 殻が出す approve のコマンドを打つ。承認はその場で続き（差分の審査）を回して終わる。`WORKS_KEYCHAIN_ITEM` で起こしたなら、出た行に項目名が載っているので、export していない殻でもそのまま打てる。`CLAUDE_CODE_OAUTH_TOKEN` だけで起こしたなら、値は出さないので、それを export した殻で打つ。`resume` は失敗・中断から続けるときだけ要る。殻が出す承認・関所の答え・続き・止める・取り消しの行は `works/dev/continue.sh` を通り、Archon を呼ぶ前に run を起こした herdr の枠へ「走る」を、戻った後にその run の今の状態を送る（別の枠・枠の外から打っても起こした枠へ届く）。その後に `sh works/dev/real-run.sh --show <dir> <run-id>` で行を出し直す。

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
3. 起動の関所（`launch`）で止まって戻る。殻が出す approve のコマンドで越える。修正の前の関所（要る時だけ）と最後の関所は、関所の文に載る答えの行（隔離した `archon.sh` の `respond <run-id> continue "<一言>"`。止めるなら `stop "<理由>"`）で答える（`skills/works/SKILL.md` の 3 節）。殻は入力 `tdd_suite=works/dev/tdd-suite.sh`・`adapter=`（空＝包みを求める。既定で包みを通す。`WORKS_DEV_ADAPTER=0` で外すと `adapter=optional`）・`final_gate=always` を渡す。
4. 報告まで済んだら、殻が出す `git -C <このリポジトリ> apply <dir>/run-<id>.diff` で差分（run の worktree と周の頭の版の差。手直しも未追跡も入る）を取り込み、手元でテストを回してから commit する。差分は修正が在る時だけ書く（起動の関所ではまだ無いので書かない）。殻が出す承認・関所の答え・続き（resume）・止める（reject）・取り消し（cancel）の行と関所の文の答えの行は `works/dev/continue.sh` を通り、Archon を呼ぶ前に run を起こした herdr の枠へ「走る」を、戻った後にその run の今の状態を送る。殻が出す行は、その後に `sh works/dev/dogfood.sh --show <dir> <run-id>` で差分を今の worktree から書き直す。Archon の生のコマンドで続けた後は、殻が出す「差分だけを書き直す」の行を打つ。
   修正が `works/` でなく pack の写し（`.archon/workflows/works`）を書き換えていたら、その部分は取り込まない（殻は「注意:」の 1 行を出す）。依頼は起動ごとの写し `<dir>/requests/<日時>-<pid>.json` に写して渡す（`<dir>` を使い直しても、前の起動の run と結び違えない）。`<dir>` に前の回の `repo`・`origin.git`・`github-reads.json` か、前の版の固定名の写し `request.json` が在ると、殻は何も書かずに止まる（`requests/` は残っていても止めない）。

### 結果（2026-09-26・Archon v0.11.1・opus・2 回）

| run | 依頼 | 費用 | 審査の指摘 | 取り込んだ commit |
|---|---|---|---|---|
| dd52a646 | 悪い見本ごとに違反の文面まで照合 | $1.00 | 0 | f3baa2e |
| 98978777 | validate が 0 本なら赤 | $0.75 | 0 | fef8877 |

分かったこと:

- 模型は固定しないと黙って変わる。当初は `real-run.sh` だけが模型を設定に書いていたので、`archon.sh workflow run` を直に打つと Claude CLI の既定の模型（sonnet）で回った。今は `archon.sh` が認証を使う実行のたびに書く（開発の回し方の節）。
- テストのコマンドが確かめるのは、渡した物だけ。ラインにはまだ全体を回す CI の節が無いので、迷ったら全体（`sh works/tests/run.sh`）を渡す。
- サンドボックスの中の修正役は `tests/test_dev.py` を回せない。サンドボックスの TMPDIR は `/tmp/claude-*` の下で、`guard.sh` がそこを拒むため。修正役は環境のせいの赤を 10 件ほど報告するが、修正の良し悪しとは関係ない。
- 包みは、Bash を持つ役（sandbox が enabled・allowWrite に `/` が無い・網を閉じていない・切符が在る）の起動にだけ、run ごとの置き場 `<切符の board の親>/run-place` を `sandbox.filesystem.allowWrite` に足し、子の env に `UV_CACHE_DIR`（`<置き場>/uv-cache`）と `WORKS_RUN_PLACE`（`<置き場>`。試験の `linekit.work_home` が `WORKS_DEV_HOME` より先に見て `<置き場>/single` を使う）を立てる。サンドボックスが既定で書ける場所は作業ツリーと `$TMPDIR` だけで、uv のキャッシュ（`XDG_CACHE_HOME` の下）と試験の置き場はその外だったため。`TMPDIR` は Claude Code が書ける一時フォルダへ向けるので向けず、`WORKS_DEV_HOME`・`XDG_CACHE_HOME` は run をまたぐ共有の置き場なので向けない。起動の記録の `fence.run_place` に足した置き場（足せなければ理由）が残る（`.shared/core/adapter.py` の頭の 17）。
- run の明示の模型（印のある起動だけ）: env の `WORKS_DEV_MODEL` が空でない run（利用者の明示。`archon.sh` は既定を書き戻さない）では、表 `.shared/core/stage-models.json` の段（前付けを持たない役の段。段の名は印の名）の起動の `--model` を全部その値に替える。`--effort` は段の値のまま、前付けを持つ役の段・印の無い起動は替えない。替えた起動は起動の記録に `model_declared`（段の宣言）を足し、`model` は子に渡した値。明示が在るのに表が読めない起動は起こさない（明示を黙って落とさない）。包みを外した run には効かない（`.shared/core/adapter.py` の頭の 19）。
- 修正役は run の worktree に `__pycache__` などの git が無視するファイルを残すことがある。fix.diff には載らないが、テストの節の緑赤を左右した（自分食いの run で、バイトコードが無いことを見る試験が偽の赤になった）。今は blk-fix が修正役の前に git が無視するファイルを控え（節 `ignored-before`）、修正役の後、テストの前に、控えに無かった物だけを消す（節 `clean`。消した物の全件は盤面の `fix-removed.json` に書き、出口には件数とそのファイルを出す。報告の冒頭と最後の関所には、0 本でも件数と全パスが出る）。判定・審査の読むだけの検査（作業ツリーの写し）も、git が無視するファイルの増減・書き換えを見る。

## canary（版ごとの確かめの 1 run）

普段の依頼ではたまにしか通らない道を、決まった小さな対象と決まった依頼で 1 run にまとめて通す殻が `works/dev/canary.sh`（費用が掛かる。回す前に持ち主の了承を取る）。種は `works/dev/canary-seed/`（標準ライブラリだけの `calc.py`・`textfmt.py` とそのテスト・`CHANGELOG.md`。種のテストは緑で、バグを突くテストはまだ無い）、依頼は `works/dev/canary-request.json`（3 件）。狙う道:

- (a) 別のファイルの 2 項目以上（`calc.py:mean` と `textfmt.py` の 2 件）: TDD の輪の枝と修正役の項目の並べ
- (b) 同じファイルの 2 項目（`textfmt.py` の頭の `pad_left` と末尾の `truncate`。直しの塊は離れていて、足すテストは同じ `test_textfmt.py` の末尾の挿しだけ）: 重なる枝の 3 方向の合わせと試験のファイルの union
- (c) 範囲の外が要る直し（`mean` の直しに要る `CHANGELOG.md` の 1 行。依頼が修正案に `allowed_paths` へも `out_of_scope` へも入れさせない）: 範囲の相談
- (d) run の中の案の直し: 起きてもよい（起こさせない）

回し方:

1. `WORKS_KEYCHAIN_ITEM=<keychain の項目名> sh works/dev/canary.sh [<置き場>]` を裏で起こす（無人の run で報告まで前景で回るので、Claude Code からは `run_in_background` か切り離しの殻で起こす）。置き場の既定は `~/.cache/works-canary/<日時>-<pid>` で、`repo/`（対象。枝 `main`）・`origin.git/`・`home/`（利用の家 `WORKS_USE_HOME`）を作り、`use.sh start` を `WORKS_USE_UNATTENDED=1`・test_cmd `python3 -m pytest -q`（`use.sh` が JUnit の実行器を書くので TDD の輪が回る）で起こす。`python3 -I` で pytest が読めない・`WORKS_KEYCHAIN_ITEM` が空・置き場に前の回の物が在る時は、何も作らずに止まる。`--build-only` は対象と origin を作って起動の行を出すだけ（認証も Archon も使わない）。
2. 走っている間の run id と状態は、殻が最初に出す `use.sh show` の行で見る。終わると殻が run id と確かめの行を出す。
3. `python3 works/dev/canary_check.py <置き場> [<run-id>]` で、何が実際に通ったかを出す（読むだけ。`--json` で JSON。`--db <archon.db> --run <run-id>` でほかの run も読める）。(a)〜(c) が yes・attempted・no のどれかと証拠（TDD の輪の枝の数と下請けの同時の最大・修正役が当てた項目・重なりのファイルと union・相談の答え）、(d) の数、修正案の項目と `allowed_paths`、AI の節の費用の和と時間、差分のファイルを出す。終了コードは (a)〜(c) が全部 yes なら 0、どれかが違えば 1、引数や db の誤りは 2。

種のテストが緑でバグが在ること・試験の中だけに持つ参照の直しで各件が独立に直ること・(b) の前提（直しの塊が食い違わず、足すテストは挿しだけの食い違い）・依頼が入口の型を通ることは `tests/test_canary.py`（FAST）が縛る。依頼が修正案の決めを文で言うだけなので、計画役が従わなければ (b)・(c) は通らない（その時は確かめ役が no か attempted と出す）。

## 足りない所

- 修正の受け付けは、直す義務の残る単位ごとに修正の行が在るか（`fix_plan_covers_units`）までを見る。graphloops の `fix_covers_open_units`（修正の後に判定の `class_query` を機械で数え直し、単位が閉じたかを見る）とは違う。修正の後の機械による数え直しは未実装（周の輪の段で入れる予定）。
- 周の輪（2 周目以降）・修正案の事前審査など、設計書 6 節の「範囲の外」に挙げた物は無い。

## 仕様

設計の正本は [`docs/specs/2026-09-26-darkfactory-design.md`](docs/specs/2026-09-26-darkfactory-design.md)。実装計画は [`docs/plans/2026-09-26-darkfactory-v1.md`](docs/plans/2026-09-26-darkfactory-v1.md)。

これから入れる物（実装前。どちらも盤面の層 [`docs/specs/2026-09-26-board-layer-design.md`](docs/specs/2026-09-26-board-layer-design.md) の上に載る）:

- 線 A（1 回の run を review-graph と同じ工程に強くする）: 設計 [`docs/specs/2026-09-27-darkfactory-single-run-design.md`](docs/specs/2026-09-27-darkfactory-single-run-design.md)・計画 [`docs/plans/2026-09-27-darkfactory-single-run.md`](docs/plans/2026-09-27-darkfactory-single-run.md)
- 線 B（直ったと言えるまで何周も回す入口 `darkfactory-rounds`）: 設計 [`docs/specs/2026-09-27-darkfactory-rounds-design.md`](docs/specs/2026-09-27-darkfactory-rounds-design.md)・計画 [`docs/plans/2026-09-27-darkfactory-rounds.md`](docs/plans/2026-09-27-darkfactory-rounds.md)
