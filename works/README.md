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

1. プラグインを入れる。works と、works の AI の役が借りる 2 つ（coldwrite・pr-review-toolkit）。借りる 2 つは works の依存（`.claude-plugin/plugin.json` の `dependencies`）で、works を入れると一緒に入る。ただし依存の marketplace が先に足されていないと入らず、works は読まれない。superpowers のスキルは works に写した固定の版を使うので入れなくてよい。リポジトリの clone は要らない。
   - `claude plugin marketplace add anthropics/claude-plugins-official`（pr-review-toolkit の marketplace。登録済みなら要らない）
   - `claude plugin marketplace add raiki61/claude-plugins`（登録済みなら `claude plugin marketplace update raiki61`）
   - `claude plugin install works@raiki61`（依存の coldwrite・pr-review-toolkit も入る）
2. 起動の殻 `dev/use.sh` と pack は、Claude Code が入れたプラグインの置き場（`~/.claude/plugins/cache/raiki61/works/<版>/`）の中に在る。スキルの行は、Claude Code がスキルを読む時にそこの絶対パスへ置き換える形（プラグインのスキルの置き換え CLAUDE_PLUGIN_ROOT）で書いてあるので、`/works` から打てばその置き場の `use.sh` が起きる。
3. 対象リポジトリで確かめる（AI を起こさない）: `sh <置き場>/dev/use.sh check <対象>`。最後の行が `Results: 1 valid, 0 with errors, …` なら入っている（Claude Code に組み込みのスキル `code-review`・`simplify`・`security-review` の WARNING の 3 行は出てよい）。借りる物が入っていなければ、足りない物ごとに 1 行の理由と入れるコマンドを出して止まる（`start` も AI を起こす前に同じ所で止まる）。uv・claude・認証・対象の条件で足りない物も、入れ方つきで全部並べて 0 以外で終わる。
4. 回す: `sh <置き場>/dev/use.sh start [--base <版> | --pr <番号>] [--] [<対象>] <依頼の JSON か -> ["<test_cmd>" [<tdd_suite>]]`（対象を省けば今いるフォルダの git の根。`--base`・`--pr` は変更の差分から入り、旗は対象より前に置く。変更だけなら依頼の JSON を `-`。この `-` は標準入力でなく依頼を省く意味）。関所で止まるたびに次に打つ行が出る。ほかの命令（`show`・`wait`・`approve`・`answer`・`stop`・`apply`・`clean`・`check`）の形と中身は [dev/use.sh](dev/use.sh) の頭、関所での答え方と差分の取り込み方は `skills/works/SKILL.md` に在る。要点:
   - 手元に commit していない変更が在ると包んだ commit が run の HEAD になるので、`--pr` は PR の head と違うとして拒まれ、`--base` の差分には包んだ変更も入る。
   - `approve`・`answer`・関所で待つ run の `stop` は残りの工程を切り離して回してすぐ戻り（出力は `<家>/logs/`）、その後は `wait` が決まった時間のうちに戻って状態を返す。
   - run の worktree・枝・控えは自動で片付く（終わった run は `wait`・`show` が差分を `<家>/diffs/` に書いた後、落ちた run は次の `start` が差分を書いてから。修正の段が切った単位の worktree と守りの参照も一緒に）。走っている・関所で待つ run と、差分を書けなかった run は残す。差分のファイルと盤面は消さない。片付けた run は Archon の resume で続けられないので、修正は差分のファイルから `apply` で取り戻す。`start` が片付けた run の id と状態は、`start` の出力と報告の冒頭 2 に 1 行で出る。
   - `start` は起動の直後に、この起動の依頼を盤面に持つ run を 1 つに結び（一覧の先頭を推定で採らない）、run の控え（`<家>/runs/<run-id>.json`。模型・claude の実行ファイル・keychain の項目の名・包み）を書く。別の殻で打つ `answer`・`stop` はその値で Archon を起こし、`show` が出す進める・続きの行もその値で組む。

このリポジトリの clone で works 自身を直している時は、clone の `works/dev/use.sh` をそのまま打ってもよい（同じ殻で、pack はその clone の `works/` から写る）。marketplace の works の行（リポジトリ直下の `.claude-plugin/marketplace.json`）が GitHub に届く前の works を試すなら `claude --plugin-dir <clone>/works`。

`use.sh` の決まり:

- pack は対象に置かず、利用の家（`WORKS_USE_HOME`。既定 `${XDG_STATE_HOME:-~/.local/state}/works/use-<対象の clone の実際のパスの sha256 の頭 8 字>`。Archon は 1 つの家に同じリポジトリの clone を 1 か所しか登録できないので、clone ごとに分ける。家には、その家を作った clone の実際のパスを 1 行書いた目印 `target` を置く。前の既定の家 `works/use` に残っている run は `WORKS_USE_HOME=${XDG_STATE_HOME:-~/.local/state}/works/use` と名指せば続けられる）の Archon の全体の工程の置き場 `archon-home/workflows/works` に、起こすたびに写す。Archon v0.11.1 は `$ARCHON_HOME/workflows/<pack>/` も探す（実行ファイルの中の探し方で確かめ、使い捨ての対象で `validate`・`workflow test works` が通った）。
- Archon と AI の役は `archon.sh` を通してだけ起こす。家は開発の家（`WORKS_DEV_HOME`）を継がない（走っている自分食いの家を書き換えない）。
- run の worktree は `--from <対象の HEAD>` で切る。commit していない変更・未追跡のファイルが在れば、一時の index で包んだ commit（`.gitignore` の物は入れない。対象の作業ツリー・index・枝は動かさない。包んだ commit は `git gc` に消されないよう `refs/works/wraps/<commit>` にだけ参照を置く。参照は run の控え `<家>/runs/<run-id>.json` の `wrap_ref` に残し、`clean` がその控えの在る run と一緒に消す。`start` が run を結べなかった時は、起動が 0 で終わり生きた候補の run が在れば run が使うので外さずに候補と一緒に `<家>/unbound/` に控え、候補の run の `clean` が消す（ほかの候補が生きている間は消さず、最後の候補の `clean` で消す）。起動が落ちたか、読めた一覧で候補が無ければその場で外す。run の一覧が読めない時は生きた run が在るか分からないので外さず、候補の無い控えに残して 1 で終わる（その対象の生きた run が無くなった後の `clean` が消す）。控えに `wrap_ref` の無い run（この仕組みの前に起こした run）の参照は `clean` が知らないので残り、`git update-ref -d refs/works/wraps/<commit>` で外す）から切り、包んだことを起動と `show` に出す。対象は下のフォルダでもよい（git の根で回す）。`/private/tmp` の下・git のリポジトリの外は全部の命令が、pack の写し `.archon/workflows/works` が在る・remote の `origin` が無い・依頼・認証・uv・claude が無い時は `start` が何もせずに 1 行で止まる（`check` は全部並べる）。
- 最後の関所は既定で守りのファイルを触った時だけ開く（`WORKS_USE_FINAL_GATE` は `protected_only`・`when_needed`・`always`。中身は `skills/works/SKILL.md`）。Claude の包みは既定で通す（`WORKS_DEV_ADAPTER=0` で外すと `adapter=optional` と「包み無し」）。`WORKS_USE_UNATTENDED=1` は起動の関所を越え、人が決める関所に着いたら止めて報告へ進める（判定の保留の問いだけでは修正前の関所を開かず、問いの出どころだけを飛ばして直し、問いを報告の冒頭に並べる）。機械は関所に答えない。報告は、関所で止めた項目と保留のままの台帳の問いへの答えの下書き（役が書いた推し `recommend` か問いの理由の推し。推しが無ければ `text` を空にし、狭めない案・世界の解・問いの選択肢を `note` に置く）を次の run の依頼の下書き `next-request.json` の `answers` に `draft: true` と出どころ `source` つきで置き（関所で止まらなくても保留の問いが残れば置く）、止めた直後の行と `show` がその置き場を言う。下書きのままの行は依頼の入口が拒むので、人が見直して `draft` と `source`（と `note`）を消してから使う（`text` が空の行は人が答えを書くまで拒まれる。台帳の問いの行は `question` の key で次の run の問いに当たる。関所の項目の行は次の run の関所の `continue` の一言の材料）。修正の段で案の項目の誤りと裁かれ、同じ run の中で直した項目（案の直し）が範囲を広げるだけ（`allowed_paths` に足す・`out_of_scope` から外すだけで、ほかの欄は字のまま同じ・事前審査が人に聞く穴を挙げない）なら、無人の run は案の直しの関所（`replan-gate`）を開かずに直した項目で修正に戻り、どの項目の範囲を何で広げたかを盤面の trace（`replan_widened_unattended`）と報告の冒頭 1（同じ run の中で直した修正案の項目）に残す（広げた範囲で作った差分は後の差分の審査が見る）。`rewrite_tests` を足した・ほかの欄も変えた直しは今どおり関所で止まる。人の居る run は範囲を広げるだけの直しも今どおり関所で聞く。`WORKS_USE_UNATTENDED`・`WORKS_DESIGN_ONLY` は 1 か空だけを受け、ほかの値（`on` など）なら何も作らずに止まる。入力 `policy_md`・`gates`・`thickness` は `WORKS_USE_POLICY_MD`・`WORKS_USE_GATES`・`WORKS_USE_THICKNESS`。`thickness` の既定は自動（判定の単位ごとに機械が軽量か標準を決め、全部が軽量の run だけ差分の審査（とレンズ・手直し）と独立の目（コメントの削除候補と R1〜R4）を省いて報告の冒頭 2 に名指す）。`標準` で今の工程を全部回し、`軽量` で全部の単位を軽量に固定する。
- 木・枝の形の機能は run ごとに切れる・入れられる（入力 `features_off`・`features_on`。`use.sh` は `WORKS_USE_FEATURES_OFF`・`WORKS_USE_FEATURES_ON`、`dogfood.sh` は `WORKS_FEATURES_OFF`・`WORKS_FEATURES_ON`。同じ依頼を機能を替えて回して比べる口）。語をカンマで区切って並べる: `graph_map`（旗 `map` の役に包みが工程の地図を足す。下の「Claude の包み」）・`judge_verify`（判定の裏取りの下請けを起こし、修正案の役に申し送りを貼る）・`review_tree`（事前審査の項目ごとの下請けと相乗りの審査。切ると審査役 1 つが案の全体を審査する。項目が 1 つの案で木を使わない道と同じ受け付け）・`tdd_lanes`（TDD の輪の並べの周。切ると tdd の単位を順に回す）・`fix_lanes`（修正役の項目ごとの単位の worktree。切ると項目の下請けを作業ツリーで順に起こす）。
  - 既定（どちらにも名指さない時。持ち主の決め 2026-10-08）: `judge_verify` は off、`review_tree` は auto（往復ごとに開いた項目を数え、2 つ以上なら木、1 つ以下なら審査役 1 つ）、ほかは on。理由は測り: 判定の裏取りは 27 単位の 11 run で後の段を 1 度も変えず 1 run に 0.6〜3 USD と 1〜2 分を足し、木は審査役 1 つの 2〜3 倍の費用で審査役 1 つが見逃した本物の穴を出さなかった（両方を切った組の測りで費用が約 30%・2.6 USD、時間が 2.3 分減った）。
  - 名指しが既定に勝つ: `features_on` の語は on（`judge_verify` を回す・`review_tree` を項目の数に依らず木にする）、`features_off` の語は off（`review_tree` をいつも審査役 1 つにする）。既定と同じ値の名指し（前からの `features_off=judge_verify` など）も拒まない。同じ語を両方に名指す・知らない語は `start` が AI の前で止める。差分の審査の穴の枝の名札（木の段 4a）は表示だけなので切る口は無い。
  - 入力は run の `versions.json` の `settings.features_off`・`settings.features_on` と盤面の start の控えに、on でない機能は報告の冒頭 2 の頭の行（`機能: judge_verify off・review_tree auto` のように。全部 on なら `機能: 全部 on`）に残り、run どうしを並べて比べられる。run の呼び直しで替えれば止まる。固定材料（`fix_fixture`）から始める run は替えてよい（判定・修正案は写しの物のままで、効くのは `tdd_lanes`・`fix_lanes`）。
- 修正案を書く役の模型を比べるなら `WORKS_DEV_MODEL` を使う（下の「模型」の段落）。明示は表 `.shared/core/stage-models.json` に載った段（前付けの無い役の段）の全部に効き、修正案の段だけには絞れない。今の表では修正案の役（plan・plan-revise）だけが opus で、コードを書く役と軽い役は sonnet なので、`WORKS_DEV_MODEL=sonnet` の run と明示しない run（修正案の役は opus）を比べると、このラインで替わるのは修正案の役（plan・plan-revise）だけになる（仕様を書く役 spec-write・spec-revise もこの表で替わるが、このラインに無い）。`WORKS_DEV_MODEL=opus` はコードを書く役と軽い役も opus に替えるので、修正案の役だけの比べにならない。effort は段の値のまま、前付けを持つ役（判定役・事前審査役などの judge と blind-judge）は替わらない。包み（`WORKS_DEV_ADAPTER`）を外した run では明示が段に効かない。替えた段は報告の「## 模型」に段の宣言と並んで出る。
- `tdd_suite` を省くと、`test_cmd` が pytest の 1 コマンドの時だけ `--junitxml` を足す実行器を家の `suites/` に書いて渡し、そうでなければ空（直に直す）にして 1 行で知らせる。
- **test_cmd と worktree**: `test_cmd` と `tdd_suite` は run の worktree の根で走り、TDD の輪と修正の並べの枝では単位の worktree の根で走る。どちらも commit から切るので、対象の git が無視する物（`.venv`・`node_modules`・ビルドの出力・`.env`）は無い（殻もラインも写さず、リンクもしない）。`test_cmd` は worktree の中で環境を作る形にする。uv の対象は `uv run pytest -q`（worktree ごとに `.venv` を作り、対象をその worktree から入れ直す。殻 `dev/archon.sh` が Archon の HOME・XDG を利用の家へ隔離するので、uv のキャッシュは利用の家の `xdg-cache/uv`（`UV_CACHE_DIR` を立てればそこ）で、その家の初めの run は依存を網から取る）。npm の対象は `npm ci && npm test`。poetry は `poetry run` が依存を入れないので `poetry install` を先に回す（poetry はこの版では試していない）。つないだコマンドは殻が TDD の実行器を書かないので、輪を回すなら `<tdd_suite>` を渡す。`.venv/bin/python` のような相対のパスは worktree に無いので走らない。対象の `.venv` を絶対パスで指す形と、`.venv` を立てた（activate した）殻から起こす形は走るが、対象をその `.venv` へ editable で入れていれば（`uv sync` の既定）、worktree の直しでなく対象の手元のコードを試し、赤と緑を読み違える（2026-10-08 に手元の試しで確かめた）。同じ理由で、対象の `.venv` を worktree へリンクしたり写したりする形（Archon の `worktree.copyFiles` も。これは run の worktree にしか効かない）は使わない。`start` は Archon を起こす前に `test_cmd` の形を見る。対象の手元（元の clone）を走らせる形（手元の在る物を絶対パスで指す・対象を editable で入れた対象の外の仮想環境を指すか立てた殻から起こす）は、run の試験が worktree の直しでなく手元のコードを試して直しの正誤に関わらず緑になり得る（黙った偽の緑）ので、`止める（test_cmd）` の行と理由・書き直す形・止めの外し方の 1 行を出して終了コード 2 で止める（依頼の写しも pack の写しも作らない）。形を知った上でそのまま回すなら `WORKS_USE_ALLOW_TESTCMD=1` を前に付けて打ち直す（未設定・空・1 だけを受ける）。worktree で走らない形（git が無視するパスを相対で指す。走れば落ちて分かる）は `注意（test_cmd）` の行で知らせるだけで止めない。止める形・注意の形・所を変える形の辿り方・読まない形（漏れ）は [dev/testcmd_check.py](dev/testcmd_check.py) の頭に在る。
- 差分は家の `diffs/run-<id>.diff`。当てるのは人（`apply` は `git apply --check` の後に当て、対象のファイルを消す差分は `WORKS_USE_ALLOW_DELETE=1` の時だけ当てる。記録が止まりを示す run（最後の関所の `stop`・止め札・ラインの止め）の差分は `WORKS_USE_ALLOW_STOPPED=1` の時だけ当てる。commit はしない）。
- **失敗や中断から続ける**（`use.sh show` が出す行。中身は Archon の `workflow resume <run-id>`）: Archon v0.11.1 の resume は済んだ節を飛ばし、落ちた・走っていた節を回し直す。輪は 1 周目から新しい会話で起き、落ちた節に依る済んだ節も回し直す。修正の段の輪の位置は盤面に在る（TDD の輪は `tdd-<k>/state.json`、並べの枝は枝の控え）ので、TDD の輪・その並べの枝・修正役の並べの枝は止まった単位・項目・段から続く（単位の worktree は使い直す）。止まった周の役の返答は残らないので、その段は新しい会話で出し直す（書きかけのファイルは残り、記録の無い書き込みなら確かめが拒んで出し直させる）。並べの枝の輪が 1 本落ちても（口座の上限など）締めの節は走って残りを順の輪へ回し、run は落ちたまま進む。resume はその枝の輪と締めを回し直すが、枝の輪は役を起こさずに抜け、締めは前の出口を返す（当てた差分を戻さない）。確かめの節が状態に「済んだ」を書いた直後、Archon が輪の済みを記録する前に止まった輪（TDD の順の輪・並べの枝の輪）も、resume で 1 周目から起きた時に役を起こさずに抜ける。機械の報告（`report`）は resume のたびに回し直す（`always_run`）ので、落ちた節が resume で済めば結末は「途中で終わった」（interrupted）でなくなる（前は前の試みの interrupted が使い回されて、出口の `result` が何度 resume しても落ちた）。AI の報告を回すか（`ai_report_go`）は AI の報告が始まった後の resume でも替わらないので、AI の報告の済んだ段は使い回される。resume は run を始めた時に Archon が写した工程の元（`<workspace>/workflow-source/runs/<run id>/`）で走るので、works を入れ替えてもその run の続きには効かない（直した版は次の `start` から効く）。続けられない所: 電源断・`kill -9` では run が running のまま残り、`workflow resume` は failed・paused だけを受ける（Ctrl-C と `kill` は failed にする）。続けられない run の直しは `apply` で取り出す。次の `start` が生きていない run を片付けると resume できないので、続けるならその前に（設計 [docs/plans/2026-10-07-lane-nodes.md](docs/plans/2026-10-07-lane-nodes.md) の 4）。
- works は自分の置き場（`works/`）の外のリポジトリを読まない。Claude Code はプラグインの置き場だけをキャッシュ（`plugins/cache/raiki61/works/<版>/`）に写し、`.git` も隣のプラグイン（`coldwrite/` など）も写さないため。借りる物は利用者が入れたプラグインから取る（下の「選んだ物だけの隔離した Claude の設定」）。pack に写す時は、Claude Code がキャッシュの版の置き場に置く印（`.in_use/`・`.orphaned_at`）を除く。

`archon plugin install raiki61/claude-plugins/works@<tag>` で入れて Archon を直に打つ形は、tag を打つまで入らず、入れても AI の役が利用者の本物の `~/.claude` を読む（下の「選んだ物だけの隔離した Claude の設定」）ので、まだ使わない。

## 要る物

- Archon v0.11.1 以上 0.12.0 未満（`archon-plugin.json` の `compatibility.archon` が `>=0.11.1 <0.12.0`。確かめたのは v0.11.1 だけ）。
- uv（script の節は `runtime: uv` で起きる）と git。節のスクリプトは PEP 723 の塊を持つので、対象が pyproject.toml を持っても uv は対象の project を拾わない（worktree に .venv・uv.lock を作らない）。既知の限界: 対象の uv の設定（`[tool.uv]`・`uv.toml`）は読まれるので、それが壊れているか、手元の uv に合わない `required-version` を持つと、works の script の節は起動時に終了コード 2 で止まる。直すのは対象か uv の設定。`UV_NO_CONFIG=1` を Archon の環境に立てて逃げるのは勧めない: 対象自身の uv の動きも変わり（テストのコマンドや修正役の Bash が私的な index を読まずに公開の PyPI から解決する）、偽の赤と依存の取り違えの口になる。
- core は git だけで動き、gh・GitHub は外側の forge の層。対象の remote（枝の upstream の remote、無ければ `origin`）が PR を持つホスト（github.com と `<名>.ghe.com`。ssh の形は `github.com-work` のような別名も）でない時——remote が無い・ローカルのパスか `file:`・GitLab や自前のホスト——は、run の初めに機械（`.shared/core/forge.py`）が決めて盤面の `loop.forge` に置き、並行 PR の確かめを条件外（素材 `parallel_pr` は `not_applicable`、理由は `no_forge: <種類>`）にする。AI の役には聞かず、検証器の阻害・問いの台帳の人待ちにもならない（報告の冒頭 2 に 1 行）。殻の隔離の前の読み出し（`ghreads.py read`）は、依頼が名指した PR・issue を forge の無い対象でも gh で読み（`GH_REPO`・別の remote・自前のドメインの GitHub Enterprise Server なら gh は読める。名指した物を黙って落とさない）、gh も GitHub のホストを見つけなかった項（gh が「remote が GitHub のホストを指さない」「remote が無い」と言うか、どこにもログインしていないか、gh が起きない）だけを `unreadable` でなく `not_applicable` と書き、`--pr` は base・head が読めなければ base を名指して回せと言って止まる。gh が GitHub のホストとして読みに行って読めなかった項（自前のドメインの GitHub Enterprise Server でログインが切れた・HTTP 401 など）は、forge の無い対象でも `unreadable` のまま理由に gh の言葉を残し、forge の無い決めは欄 `forge` に分けて書く（本当に条件外の項と見分ける）。`--pr` はログインしてから回せと言って止まる。並行 PR の確かめは、どちらでも forge の無い対象なら条件外のまま。GitHub の remote で gh が無い・未ログイン・API が落ちた時は今どおり（確かめる物が在るのに確かめられなかった: 人待ちか任せ先の役）。自前のドメインの GitHub Enterprise Server は形から分からないので forge の無い側に入る。
- 対象リポジトリには git の remote の `origin` が要る（Archon v0.11.1 は `--from` を渡しても、origin の無い対象では run の worktree を切れずに終了コード 1 で落ちる）。無ければ `dev/use.sh` の `check` が並べ、`start` は Archon を起こす前に止まる。入れ方は `git remote add origin <URL>`。預ける先が無く手元だけで回すなら、対象の外に `git init --bare <対象>.origin.git` を作って origin にし、`git push origin HEAD` の後に `git remote set-head origin <push した枝>` で `origin/HEAD` を置く（`dev/dogfood.sh`・`dev/canary.sh` が使い捨ての対象に作る形と同じ）。殻は対象の remote を書き換えない。依頼の JSON は対象の外に置いてよい（`dev/use.sh` は依頼を利用の家に写して渡す）。
- `start` は origin の既定の枝（`origin/HEAD` が指す枝、無ければ `origin/main`、次に `origin/master`）を Archon の土台（`--base`）に毎回渡す（Archon は対象を最初に登録した時の枝を覚えて更新しないので、登録した時の枝が消えても止まらない）。どれも無ければ枝を推さず、Archon を起こす前に `git fetch origin` と、それでも無い時の `git remote set-head origin -a`（または `git remote set-head origin <枝>`）を案内して止まる（裸の origin に機能の枝だけを push した対象は、fetch しても `origin/HEAD` ができない）。`origin/HEAD` が消えた枝を指す時（改名の後の `git fetch --prune`）は、それを渡さずに `origin/main`・`origin/master` へ進む。

## Claude Code のスキル

`skills/works/SKILL.md`（`/works`）に、入れ方・依頼の JSON の書き方・起動の 1 行（`dev/use.sh`）・人の関所での答え方・報告と差分の取り込み方を置く。Claude Code のプラグインの定義は `.claude-plugin/plugin.json`、配る行はリポジトリ直下の `.claude-plugin/marketplace.json` の `works`（source `./works`）。

## 開発の回し方

テストは `works/tests/run.sh`。実際に Archon の上で回す手順（実行ファイルの取得・使い捨ての対象作り・`archon workflow test` 相当の検査・自分食い）は `works/dev/` を見る。キャッシュした Archon の実行ファイルの sha256 が合わないときは、止まった時の 1 行に出るそのファイルを消して回し直せば取り直す（殻は消さない）。

線の中の書く役（修正・TDD の輪・手直し）は一式を回さず、直した単位に当たる試験だけを絞って回す（決まりの正本 [`works/.shared/core/writerules/common.md`](.shared/core/writerules/common.md#守ること) の「守ること」）。一式の緑は線の最後のテストの段が確かめ、TDD の実行器が在る run では修正の受け付け（`fix-accept`）が版からの変更に当たる試験を機械で選んで回す。直しながら回すのは速い段 `WORKS_TESTS=fast sh works/tests/run.sh [-k 名前]`（試験ごとに git のリポジトリを作らない・uv run・Archon・golden・プロセスの木・決まった秒の待ちを使わないモジュールだけ。種の git を `works/tests/gitkit.py` の型の写しで配るのは可。`WORKS_TESTS=heavy` は残りの重い段で、2 つを合わせると全部）。作業の終わりと merge の前は、既定（何も付けない）の全部を回す。CI は全部を `WORKS_SHARD=<番号>/<組の数>`（番号は 0 起点）で 4 組に分けて別の runner で並べる（分け方は `tiers.py` の `shard_of`。組の和がちょうど全部なのは `test_tiers` が縛る。回すモジュールの名前だけを見るのは `python3 works/tests/tiers.py list <fast|heavy|all>`）。どのモジュールがどちらの段かは `works/tests/tiers.py` に 1 か所で書き、新しいテストのモジュールはどちらかに書き足す（書き忘れると段を選んだ実行とテストが止める）。全部と heavy は、機械全体で重いテストを同時に 4 本までにする枠（[`.shared/core/slotwrap.sh`](.shared/core/slotwrap.sh)。台本は `WORKS_TESTSLOT` で差し替え。台本の既定の置き場・枠の置き場・台本が無い時の動きはその頭が正本）を通して、枠が空くまで期限なしで待ってから回る。run の中で試験を起こす口（engine の宣言の段・`test_cmd`・blk-tests の plain と mid・TDD の輪と修正の受け付けの実行器）も `tree_run.slotted_run` から同じ口を通るので、並べた run の重い試験も同時に 4 本まで。枠を待つ間は、`use.sh show` が `試験の枠: 待っている（N 分…）` の 1 行で、herdr の集計が `走る N（うち枠待ち k）` で出す（人の答えの要る待ちではないので blocked にしない）。枠を取った段は待った秒を `wait_s` に分けて記録し、`wall_s` は実行の時間のまま。TDD の実行器は外の `tddloop.run_suite` が `nice -n 19` を付けて枠を取り、待った秒を `suite-<n>.log` の末尾に書く（ADR [0071](../docs/adr/0071-test-sizes-and-where-they-run.md) の 3 の 1）。速い段と TDD の実行器の中は `WORKS_TESTSLOT` を空にして、中の試験が起こす試験にも枠を取らせない（外で取った枠と二重に数えない）。

TDD の修正の段が使うテストの実行器（ラインの入力 `tdd_suite`）は [`works/dev/tdd-suite.sh`](dev/tdd-suite.sh) `<JUnit XML の書き先> [pytest の引数]`。同じ試験を既製の pytest で回し、結末を JUnit XML に書く。段（`WORKS_TDD_TIER`）・後ろの引数の扱い・試験の根ごとの分け方・終了コード・枠の取り方は殻の頭に在る。TDD の輪の赤・緑の回は env `TDD_SUITE_ONLY=1` を付けて呼び、殻は後ろに足した試験が在れば段の一覧を集めずそれだけを走らせる（赤は名指しだけ、緑は名指しと単位の変更が届く元の一式のモジュールのファイル。届く試験が分からなければ合図なしの一式）。TDD の輪は名指しを段の中か外かに依らず全部、受け付けは選んだ試験のうちこの run で変えた・足した pytest の試験のモジュール（`test_*.py`・`*_test.py`）だけを、絶対パスで後ろに足して回す（段のファイルと重なって同じ試験が 2 行載れば、輪が 1 件にまとめて数える）。届いただけで段の外の試験は手元で回さず、『手元で回さなかった』として受け付けの知らせ・盤面の trace（`fix_tests_selected` の `ci_left`）・最後の人の関所に名前で並べる。unittest と pytest では結末の数え方が一部違う（例外で落ちた試験は unittest では error、pytest では failure。`-k` は unittest では名前の部分一致、pytest では式）。pytest は一番外の `def test_*` も試験として拾うので、試験の道具の関数は `test_` で始めない（`test_tiers` が縛る）。

`works/dev/archon.sh`（固定した版の Archon を隔離して回す殻）の認証は、利用者自身の物だけを拾う（どこかの口座で黙って回さない。R20）。順は起こし役 `.shared/core/auth_launch.py` が持ち、真ん中は本流 `scripts/claude_auth.py` の写し（`.shared/core/claude_auth.py`。`scripts/shared-copies.py` が同一を縛る）の `auth_env` を丸ごと呼ぶ。AI を呼ぶ実行（`workflow run`・`workflow approve`・`workflow resume`）で、上から順に:

1. `WORKS_KEYCHAIN_ITEM`（トークンを入れた macOS の keychain の項目名）。その起動で名指した物なので、受け継いだ `CLAUDE_CODE_OAUTH_TOKEN` などより先に効き、子の環境からそれより上に効く資格（`ANTHROPIC_API_KEY`・`ANTHROPIC_AUTH_TOKEN`・クラウドの旗）を外す。空・`sk-ant-oat01-` で始まらない値なら次へ進まず止まる
2. 本流の段: 受け継いだ認証（`CLAUDE_CODE_OAUTH_TOKEN`（`claude setup-token` で作るトークン）・`ANTHROPIC_API_KEY` など）、無ければ keychain の `CLAUDE_KEYCHAIN_SERVICE` の項目か、設定の置き場から導く `claude-code-oauth-<名>`（`~/.claude` なら `default`、`~/.claude-p3` なら `p3`）
3. macOS で Claude Code 自身が keychain に置いたログインの項目（`CLAUDE_CONFIG_DIR` を設定していれば `Claude Code-credentials-<その値の sha256 の頭 8 桁>`、次に `Claude Code-credentials`。値の `claudeAiOauth.accessToken`）。ログインのトークンは数時間で切れるので、長い run にはトークンを置く。項目の名の付け方は Claude Code の版で変わりうる

keychain は隔離の前の利用者の HOME で読む。拾った出どころの名を 1 行出す（値は出さない）。トークンは殻の変数・標準出力を通らず、起こし役が同じプロセスから Archon を起こす時に子の環境にだけ置く（Archon の前に起こす `claude plugin` の CLI と `claude --version` には渡さない。認証は要らない）。keychain は実行ファイルに触る前の確かめと最後の起動で 2 回読む（`use.sh` から起こした時は確かめを `use.sh` が済ませる）。どれも無ければ、案内を 1 行出して止まる（keychain に既に在る項目の名指しを、トークンの新規作成より先に案内する）。run の中の gh は利用者の gh のログインを継ぐ（持ち主 2026-10-08。本流の review-graph は利用者の環境のまま gh を打つ）。認証を使う実行で、`archon.sh` は隔離の前に gh の設定の置き場（`GH_CONFIG_DIR`、無ければ `$XDG_CONFIG_HOME/gh`、無ければ `~/.config/gh`）を解き、本物の gh をその置き場と隔離の前の HOME で起こすだけの口（包みを通す run は包みの家の、通さない run は `$WORKS_DEV_HOME` の `host-gh/<中身の印>/gh`。`dev/hostgh.py` が書く。中身ごとに置き場を分けるので、並べた起動が走っている run の口を書き換えない）を PATH の頭に置く。HOME も戻すのは、gh の既定のトークンの置き場の macOS の keychain を `security` が HOME から探すため（隔離した HOME では login の keychain が探す先に無い）。口が持つのはパスだけで、トークンは写さない・出さない・置かない（gh 自身の置き場のまま）。`GH_TOKEN` も立てない。利用者の gh がログインしていなければ gh の言葉のまま（並行 PR の確かめは gh の失敗の理由つきで人に回る。前の版と同じ）。AI の役は GitHub へ書けない: 包みが印のある起動の全部で gh を丸ごと拒み、読むだけの口だけを通し、`git push` も拒む（下の「Claude の包み」）。これは事故の柵で、堅い境ではない（役は利用者と同じ人で、同じ keychain を持つ。本流の review-graph は隔離もしない）。git の資格（push の資格など）は今どおり渡さない。`WORKS_DEV_NO_AUTH=1` のときは認証を読まない（テスト・`validate`・`workflow test` 用。`dev/check.sh` は付けて回すので認証が要らない）。

認証を使う実行のたびに、`archon.sh` は隔離した Archon の設定（`$WORKS_DEV_HOME/archon-home/config.yaml`）に模型を書く（`WORKS_DEV_MODEL`。空か未設定なら `dev/guard.sh` の `WORKS_DEV_MODEL_DEFAULT`（環境では替わらない）。既定を埋めるのは `archon.sh` だけで、入口の殻は埋めない。明示か既定かは `WORKS_MODEL_FROM` に残して下へ渡す。明示せずに起こした run の続き・答えの行は、start の時の既定を `WORKS_MODEL_PINNED` に添えて起こす（`archon.sh` はそれで解いて出どころに名を残し、Archon には継がせない）。run の題を作る模型 `TITLE_GENERATION_MODEL` も、設定していなければ同じにする）。書かないと Claude CLI の既定の模型で黙って回る。`WORKS_DEV_NO_AUTH=1` のときは書かない。この設定の模型は全体の既定で、Archon は段の `model:`・工程の `model:`・この設定の順に先のものを使う。works の YAML は、AI の段（`prompt:` か `command:` を持つ段）の全部に `model:` と `effort:` を書く（持ち主 2026-10-06）。役の前付け（`.shared/core/agents/<役>.md` の `model`・`effort`）を持つ役の段は前付けと同じ値（今は judge・blind-judge が opus・high、inspector・investigator・cold-reader が sonnet・medium）、前付けの無い役の段は表 [.shared/core/stage-models.json](.shared/core/stage-models.json) の値（試験 [tests/test_tool_parity.py](tests/test_tool_parity.py) は同じ表を `STAGE_MODEL` に読む）で、仕分けは次の 3 つ: 修正案・仕様を書く役（blk-plan の plan・plan-revise、blk-spec の spec-write・spec-revise と、修正案を書いた役の会話の続きで範囲の相談に答える blk-fix の plan-answer・plan-answer-ruled）は opus・medium、コードとテストを書く役（blk-fix の tdd・tdd-rest・tdd-lane-1〜3・fix・fix-ruled、blk-refix の refix・refix2）は sonnet・high、読んで確かめる・まとめる軽い役（借りたレンズ、r1-comments、CI・pr-check の任せ先、前提の実測、目的の文、素材集めの任せ先と局所レビュー、報告の書き手）は sonnet・medium。試験は欠けも表との食い違いも名指すので、値を替えるときは表と段を一緒に直す。だから既定（`dev/guard.sh` の `WORKS_DEV_MODEL_DEFAULT`。今は sonnet）が効くのは run の題だけで、段の模型は替わらない。`WORKS_DEV_MODEL` を明示した run では、包み（`WORKS_DEV_ADAPTER=1`。`use.sh`・`dogfood.sh` の既定）が表 `stage-models.json` の段（前付けの無い役の段）の起動の `--model` をその値に替える（`.shared/core/adapter.py` の頭の 19。前は前付けに模型の無い段が設定の模型で走り、`WORKS_DEV_MODEL=opus` でその段を opus にできた。段ごとの明示へ替えた時にこの力が落ちたので戻した。[CHANGELOG.md](CHANGELOG.md#unreleased)）。effort は段の値のまま、前付けを持つ役の段（judge・blind-judge・inspector・investigator・cold-reader）は替えない。明示は run の控えに残り、続き・答えの行も同じ値で起こすので、run の間ずっと効く。包みが既定を明示と取り違えないよう、`archon.sh` は解いた既定を `WORKS_DEV_MODEL` に書き戻さない。段の `model:` は Archon 自身が読んで Claude に渡すので、包み（`WORKS_DEV_ADAPTER`）を外した run でも同じに効くが、明示の模型で段を替えるのは包みだけなので、包みを外した run では `WORKS_DEV_MODEL` は run の題にしか効かない（`archon.sh` が 1 行で言う）。

effort も、Archon の段が役の前付けを読まないので、段に書く（前付けを持つ役は前付けと同じ値、無い役は表 `stage-models.json` の値。工程の頭には書かない）。書かないと Claude Code の既定（opus は medium、sonnet は high）で黙って走る。一致は欠けも含めて [tests/test_tool_parity.py](tests/test_tool_parity.py) が全部の段で見る。段の中で役が起こす下請け（blk-plan の plan-review が項目ごとに起こす general-purpose の下請け、修正役が項目ごとに起こす下請けなど）は、模型は親の段を継ぐが、effort を継ぐかは Claude Code の文書に書かれていない（works は下請けの effort を指定しない）。段の `effort:` は段ごとの設定なので、`WORKS_DEV_MODEL` のような全体の設定では替わらない（包みが明示の模型で段を替える時も effort は段の値）。ただし Archon v0.11.1 がそれを Claude の起動にどう渡すか（`--effort` の旗か、SDK の別の経路か）は、まだ実の run で確かめていない。包みは起動の記録（launches）の `effort` に Archon が渡した `--effort` を残すので、実の run の後にそこが前付けの値か（`None` なら旗では届いていない）を見て確かめる。

対象（`archon.sh` を打つ cwd）の根の mise の設定を利用者が `mise trust` 済みなら、認証を使う実行のたびに `archon.sh` は隔離の前にそれを `mise trust --show` で読み、run の worktree の置き場（`$WORKS_DEV_HOME/archon-home/workspaces`）を `MISE_TRUSTED_CONFIG_PATHS` に足す（mise の公式の設定。前の値は残す）。mise の信頼はパスに結び付くので、足さないと run の worktree の中のテストで設定が信頼されず、道具の失敗が偽の赤になる。信頼していない対象では足さない。

開発の家（`WORKS_DEV_HOME`。既定は `$TMPDIR/works-dev`）・使い捨ての対象・その origin は、Claude Code の一時フォルダ（`/private/tmp/claude-*`・`/tmp/claude-*`）の下に置けない。サンドボックスの中の Bash がそこへ書けるためで、`dev/` の殻はその下に解けるパスを終了コード 2 で拒む（設計書 7 節）。

run ごとの版は、線の `start` が盤面の隣 `artifacts/runs/<run id>/versions.json` に書く（`.shared/core/versions.py`。入力を拒む run でも書く）: pack の中身の sha256・写した元の works の commit と手元の書き換えの有無と works の版（`dev/lib.sh` が pack の写しに置く `.works-source.json`。元の works が git で追跡されていない時（プラグインのキャッシュから起こした時）は commit と書き換えの有無が null で、版は `.claude-plugin/plugin.json` の version）・`VERSION`・graphloops の写しの行・借りた物の版（`$CLAUDE_CONFIG_DIR/.works-toolset.json`）・Archon の版と Claude Code の `--version`（`archon.sh` が env の `WORKS_ARCHON_VERSION`・`WORKS_CLAUDE_VERSION` で渡す）。全体の模型の要求と出どころ（`model`。`archon.sh` が渡す `WORKS_DEV_MODEL` か `WORKS_MODEL_RESOLVED` と `WORKS_MODEL_FROM`）も載る。分からない値は null にして、`unknown` に理由を書く。節ごとの模型は、包みが起動の記録の `model` に子へ渡した `--model` を残し（`--effort` も同じく `effort` に残す。effort は読むだけで変えない。明示の模型で段の `--model` を替えた起動は `model_declared` に段の宣言も残す）、報告の「## 模型」の節が全体の値と節ごとの値（run の途中で替われば全部。替えた段は段の宣言も）を出す。Archon の `metadata.model_bindings` は応答から推した名で、works の記録の元にしない。

## 層と依存の向き

正本は試験 `works/tests/test_layers.py`（裁定 R59）。下は要約で、食い違えば試験が正しい。上の層は下の層だけを知ってよい（import も、ライン・include の id・ほかのブロックの名前を文字列で書くことも）。

- L0 写し: `.shared/core/graphloops`・`.shared/core/scripts`。works の物を何も知らない
- L1 基礎: `tree_run`・`script_io`・`node_marker`・`graphmap`（工程の地図）
- L2 包み: `adapter`・`ticket`・`claude-adapter`・`record-read.py`・`record-write.py`・`record-output.py`・`no-post-bin/works-gh`
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
- 修正役と修正案の役の支度の節が、単位のライブラリの文書を 2 つの出どころから順に取って盤面にファイルで控え、指示書の節「ライブラリの文書（手元の版・公式）」にその一覧を貼る（`.shared/core/libdocs.py`。持ち主 2026-10-08「全部使う」。設計 [docs/plans/2026-10-08-libdocs-sources.md](docs/plans/2026-10-08-libdocs-sources.md)。3 つめの出どころだった Context7 は、役に貸す MCP とあわせて持ち主 2026-10-09 の決めでやめた）。どれも登録も鍵も要らない: (1) 手元の版——run の作業ツリーと、同じリポジトリの main の作業ツリーに入っている `.venv`・`venv`・`.tox/*`・`.nox/*`・`node_modules`（単位のファイルの置き場から根まで上へ辿る。works は環境を作らない・入れない。TDD の輪の試験や利用者が作った物を読む）の中のライブラリを、import せずに読んだ単位が使う名の署名と説明（Python は `ast`、JS/TS は `.d.ts` と README）。読めた版を公式に問う版にする (2) 公式——PyPI の README と、docs の場所の `llms.txt`、npm は repository が GitHub の時の版の tag の README。送るのはライブラリの名・版と registry の答えに在った URL だけで、https の公の host の名だけに出る。取れた文書は今の周の `libdocs/<名>@<版>/` に丸ごと書き（手元は `local-<digest>.md`、公式は `official-<番>-<種>.md`）、節にはライブラリごとの名・入っている版・出どころ・ファイルのパスと、単位が使う名・公式の README の頭の 1 行だけを並べる。本文は貼らず、量の上限も無い（持ち主 2026-10-09。前の版の 4000 トークンの上限は Context7 の口が tokens を求め、本文を貼っていたから在った）。役は API の詳細が要る時にそのファイルを Read で読む（読むべき物には数えない）。どこからも取れなかったライブラリは節の頭に名指し、役に WebSearch・WebFetch で自分で引けと言う。`WORKS_LIBDOCS_WEB=off` で網に出ない（公式を引かない。手元は読む）。取った公式の文書は run の盤面のほかに、包みの家（`WORKS_ADAPTER_HOME`。利用の家ごと）の下の `libdocs/` にも控え、同じ家の後の run は 7 日の内なら網に出ずに使う。包みを外した run は盤面の控えだけを使う。前の版が同じ置き場に残した Context7 の控えは読まない。
- 柵: 一覧の外（CLAUDE.md・rules/・agents/・commands/・output-styles/・settings.json 以外の settings*.json・一覧の外のスキル・`works-parts/` の下の部品の外のファイル・settings.json の `enabledPlugins`・`extraKnownMarketplaces` 以外の鍵・ほかのプラグインと marketplace）が在れば、名前を出して終了コード 2 で止まる（`archon.sh` も Archon を起こさない）。Claude Code が自分で書く状態（projects/・.claude.json・backups/・plugins/cache/ など）は見ない。手で確かめるなら `python3 dev/toolset.py guard <置き場>`。
- **開発の殻の外では隔離されない。** 利用者が自分の Archon で pack を入れる場合、`CLAUDE_CONFIG_DIR` は利用者の本物の `~/.claude` で、`[user]` の節は利用者の CLAUDE.md・hooks・プラグインを読む。殻の外の入れ方（利用者のキャッシュから選ぶ版上げと関門）は P1 計画 Task 21。
- 無人の読み替え: スキルの文が人（your human partner）や下請けの AI を前提にする所は、`.shared/borrow/unattended.md` の決まりで読み替える。借りたスキルを読める役（道具に Skill を持つ役）の指示書に、支度のスクリプトがその全文を載せる（`.shared/core/rolekit.py` の `skill_overlay`）（直す義務の単位は必ず直して `changes` に載せ、判定への異議は `rejudge_requested` に、人に聞きたいことは食い違いの申し出（`which_is_right` は unknown・`kind` は `needs_context`。裁定役が人に回す）に書く。`not_done` は受け付けが免除する単位と義務の外の単位だけ。修正役は commit しない、`superpowers:` の参照は無視、など）。
- 試験は本物のプラグインも利用者の設定も読まない（superpowers は works の写しを読む）。`tests/test_toolset.py` が偽の利用者の設定（偽のプラグインを入れた形）を作って回すので、プラグインの入っていない CI でも通る。

## Claude の包み

`.shared/core/claude-adapter` は、Archon が起こす Claude Code の実行ファイルの前に挟む薄い殻（芯は `.shared/core/adapter.py`）。役が読んだファイルの記録・再審の役が判定役の会話の続きで起きること・役に書かせない場所の柵・止める時に孫まで止めることを受け持つ。形は本物の Archon v0.11.1・SDK 0.3.282・claude 2.1.283 との有料の試しで確かめ、試験（`tests/test_adapter.py`）は偽の claude で縛る。どの段で何をするか（下の一覧の中身）の正本は [`.shared/core/adapter.py`](.shared/core/adapter.py) の頭の番号つきの節で、ここは要約と、頭に無い決まりだけを持つ。

入れ方:

1. Archon の設定 `assistants.claude.claudeBinaryPath` に包みの絶対パスを書く（これが主。env の `CLAUDE_BIN_PATH` は設定より強いので、一時の上書きに使える）。
2. 本物の claude を `WORKS_REAL_CLAUDE`（絶対パス）で渡す。無ければ包みは PATH の実行ファイル `claude` を使う（包み自身を指す物は飛ばす）。
3. 置き場（包みの家）を `WORKS_ADAPTER_HOME` で渡す。既定は `${XDG_STATE_HOME:-~/.local/state}/works/adapter`（切符と同じ）。絶対パスでなければ包みは起動を拒む。役の sandbox の Bash から書けない場所に置く（`/private/tmp/claude-*` は不可）。
4. 開発の殻では `WORKS_DEV_ADAPTER=1` を付けて `dev/archon.sh` を打つ（`dev/dogfood.sh`・`dev/use.sh` は付けなくても既定で包みを通す。外すなら `WORKS_DEV_ADAPTER=0`）。`archon.sh` が隔離した設定に `claudeBinaryPath` を書き、`CLAUDE_BIN_PATH` を `WORKS_REAL_CLAUDE` へ移し、家を `$WORKS_DEV_HOME/adapter` にする。殻が出す承認・続きのコマンドにも同じ札が付く。

包みがすること・しないこと（括弧の番号は `adapter.py` の頭の節）:

- どの節の起動かは、役の `output_format` の一番上の `description` に置く印 `works-node: <節の名>[ continue=<継ぐ節の名>][ <旗>…]` で見分ける（SDK がそれを argv の `--json-schema` に載せる）。印の無い起動（Archon が run の題を作る `--tools ""` の起動など）は、網の閉じのほかは argv を変えない。印の跡が在るのに印として読めない起動は、素通しせずに claude を起こさず止まる（印の文法は `node_marker.parse` と同じ）。
- 記録のフック（1）: 印のある起動の `--settings` に、読んだファイルの記録（`record-read.py`。graphloops の写しで、engine の `hook_evidence` がそのまま読む形）・書いたファイルの記録（`record-write.py`）・下請けの会話が親の返答の道具に書いた物の記録（`record-output.py`）のフックを足す。書く役の受け付け（blk-fix の `fix-accept`・`tdd-step`）は版からの変更を書き込みの記録と返答の欄 `bash_writes` に突き合わせ、どちらも無い変更を拒む。射程は今の中身を編集の道具が書いたか申告したかまでで、Bash で書いた後に同じ中身を Edit で書き直した物は区別しない（出どころの全部は証さない。`.shared/core/writes.py`）。下請けの記録は、組み込みの skill `code-review` が fork で走って所見を親に返さない形（実測 2026-10-08）から、局所レビューの受け付けが所見を戻すのに使う（`.shared/core/diverted.py`。戻せない行は「所見なし」でなく「見ていない」と書く）。
- 会話の継ぎ（2）: 判定役の会話の id を記録し、再審（`continue=judge`）をその会話の続きで起こす。旗 `self-resume`・旗 `fork`（同時に走る枝の答えの節が修正案の役の会話の写しで答える）・単位の切れ目の新しい会話も包みが決める。
- 柵（3・6・6b・6c・18）: 線の `start` が書いた切符の守る場所（共通の `.git`・ほかの worktree・盤面など）を `permissions.deny` と sandbox の `denyWrite` に足す。旗 `no-tree-write`（CI の任せ先）・`isolated`（道具ゼロの独立の目）・`lane`（並べの枝の役を単位の worktree で起こす。設計 [docs/plans/2026-10-07-lane-nodes.md](docs/plans/2026-10-07-lane-nodes.md)）・修正の形ごとの道具の拒みも同じ所。
- 木ごと止める（4）: 本物の claude を子として起こし、信号を受けた時と終わった後に孫まで止める（claude の Bash の道具はコマンドを別のグループで走らせるので、claude だけを止めると孫が残る）。
- 読むだけの gh（5）: 印のある起動の全部で gh を丸ごと拒み、読む 4 つの形だけを通す口 `.shared/core/no-post-bin/works-gh` を env の `WORKS_GH` と PATH の頭の `gh` で渡す。`git push` も拒む。口は読む 4 つの形のほかの gh を全部拒むので、対象の試験が `gh --version` などを打つと赤になる。事故の柵で、堅い境ではない。
- 柵なしで起こさない（7）: `--settings` を読めない・混ぜられない、切符が在るのに読めない、会話の id を記録できない時は、claude を起こさずに 1 行を出して終了コード 3 で止まる。
- 網を閉じる（8。印の有無に依らない）: Archon は YAML の網の設定から `strictAllowlist` を捨てるので、包みが `allowedDomains` が `*` を含まない起動に `strictAllowlist: true` を足す。WebFetch・WebSearch はこの鍵の外。
- 指示書の全文版と差分版（9）: 同じ規則を全文版で読み切った会話の続きには差分版を渡す（トークンの節約）。疑いは全文版。
- system prompt の差し込みの表（13）: 表 `INJECTORS` の行を決まった順に足す。今の行は `query_rule`（検索語に対象の名前を載せるなという判定役の定義の塊）・`graph_map`（下）・`text_reply`（返答の契約）。
  - `graph_map` の地図の元（入口の YAML の隣の `<名>.graph.json`）は作る時に `uv run --no-project --with pyyaml python3 works/dev/graphmap_build.py build works` で書き、試験 `tests/test_graphmap.py` が今の YAML から組んだ物と字で同じかを縛る。今の旗 `map` は修正案の役の会話の 7 節（`plan`・`plan-revise`・`plan-answer`・`plan-answer-ruled`・`plan-answer-lane-1`〜`3`）だけ（持ち主 2026-10-07: 節ごとに選ぶ。設計 [docs/plans/2026-10-07-graph-map.md](docs/plans/2026-10-07-graph-map.md)）。
- 対象の持ち主の禁止を写す（14）: 役の cwd の worktree の根の `.claude/settings.json`・`.claude/settings.local.json` の `permissions.deny` だけを足す（allow・CLAUDE.md・フックは読まない）。
- engine の子の目印（15）: 子の env に `GRAPHLOOPS_ENGINE_CHILD=1` を立てる（本流の `ENGINE_CHILD_ENV` と同じ名）。対象の `tests/run.sh` などが既に読む形のまま、AI の役からの重い一式を拒める。
- 子の終わりの種分け（16）・run ごとの書ける置き場（17。下の「自分食い」）・run の明示の模型（19。上の「開発の回し方」）・費用の見せ直し（20。包みが会話を替えた起動でも Archon の節の費用と模型が本当の値になるようにする）・返答の契約（21。局所レビューの役を本流の review-graph と同じく本文の JSON で受け、合わなければ同じ会話で 2 回まで出し直させる。設計 [docs/plans/2026-10-08-reply-contract.md](docs/plans/2026-10-08-reply-contract.md)）。
- 起動ごとに `<家>/launches/<cwd の hash>.jsonl` に 1 行（時刻・節の名・足した柵・会話の id と継ぎ方）を書く。引数の本文は書かない。
- 会話の決まり（どの AI の節も、どの会話で起きるかを宣言する）: Archon v0.11.1 は、輪の中に限らず、直前に終わった AI の節の会話を次の AI の節に継がせる（dag-executor の `lastSequentialSession`。script・bash の節を挟んでも続く）。切れるのは、節が 2 つ以上の層（並べ）・節の `context: fresh`・組み込んだブロックの入口の節が AI の節の時・provider が替わる時だけで、ブロックの入口が script の節なら、中の最初の AI の節は組み込んだ側の前の会話を継ぐ。輪（`loop_group`）の 1 周目は外の会話を継がずに新しい会話で始まり、輪の節は終わっても会話を外へ渡さない。works は本流の review-graph（役ごとに新しい `claude -p` で、会話を継ぐのは宣言した時だけ）と同じに、会話を継ぐのを宣言した時だけにする。決まりは 4 つ: (1) 輪の外の AI の節は `context: fresh` か印 `continue=<相手>` を持つ（今の層の形でたまたま前の会話が切れているだけの節を残さない）。(2) 輪の中で最初に走る AI の節（頭。書いた順でなく `depends_on` の走る順）の 1 周目は新しい会話で、2 周目からの出し直しを同じ会話で続けるかは輪の `fresh_context` を書いて宣言する（受け付けが拒んだ時の同じ会話での出し直し）。(3) 輪の中の頭でない AI の節は `continue=<相手>` か `context: fresh`。(4) 会話を継ぐ輪に AI の節が 2 つ以上在れば、頭は旗 `self-resume` か `continue=<相手>` か `context: fresh`。輪の中の `include` は、展開された中の AI の節が会話を置くので、(3)・(4) では会話を置く節に数える。どれも 1 本の YAML の中で閉じるので、ブロックを別の工程に組み込んでも成り立つ。`tests/test_yaml_rules.py` の `SessionCase` が pack の全部の YAML で縛る。包みを外した run では `continue=`・旗 `self-resume` が効かない（`context: fresh` と輪の `fresh_context` は Archon 自身が守る）。
- 旗 `self-resume`（`works-node: fix self-resume`。範囲の相談の答えの節が挟まる修正の輪の修正役）: Archon の輪は直前に終わった AI の節の会話を次の AI の節に継がせる。輪の中に別の会話を継ぐ節（答えの節 `works-node: plan-answer continue=fix-planner`）が挟まると、次の周の修正役が修正案を書いた役の会話を継いでしまう。旗を持つ節は、SDK が会話を継ぐ起動（2 周目から）だけ SDK の会話の旗を外して `--resume <自分の id>` で起こす（fork しない）。自分の id が無ければ起こさない。1 周目は旗の無い節と同じに新しい会話。答えの節の継ぐ相手 `fix-planner` は、ブロックの入力 `plan_session` の名で包みが記録した会話の id を、頼みの節（script）が同じ置き場にこの名で写した物（ブロックはほかのブロックの節の名を YAML に書かない。[docs/plans/2026-10-06-ask-planner.md](docs/plans/2026-10-06-ask-planner.md)）。単位の切れ目の鍵を持つ節（修正役の並べの枝の役）は、旗 self-resume の続きの起動でも鍵が替われば新しい会話で起こす（枝の中の項目ごとに新しい会話）。報告の書き手（`works-node: report-write self-resume`）も同じ旗を持つ。書き手の輪には、書き手の出した物の頭を読む初見の読み手（`report-write-cold`。YAML の節は `context: fresh` で、どの周も新しい会話）が挟まるので、旗が無いと 2 周目の書き手は初見の読み手の会話を継ぐ。逆に `context: fresh` が無いと、初見の読み手は書き手の会話の続きで読み、1 回目から初見でなくなる（run f57a5374 で起きた）。輪に AI の節を 2 つ以上置く時のこの形（頭でない節は `continue=` か `context: fresh`、会話を継ぐ輪の頭の節は旗 `self-resume` か `continue=` か `context: fresh`）は、上の会話の決まりの一部として `tests/test_yaml_rules.py` の `SessionCase` が縛る。
- 名前は `.js` で終わらせない（Archon が `.js` の実行ファイルに `--no-env-file` を足すため）。
- 版上げで壊れうる所（今は壊れていない）: SDK が `--json-schema` の渡し方・`--resume` の綴り・`--settings` の位置を変える、Claude がフックの入力の形を変える。版を上げたら `tests/adapter/argv/` の実物の argv を取り直す。

## 自分食い（dogfood）

works 自身の直しをライン `darkfactory` に回す殻が [dev/dogfood.sh](dev/dogfood.sh)（費用が掛かる。回す前に持ち主の了承を取る）。何を作り、どの入力を渡し、どこで止まるか（環境の変数も）は殻の頭に在る。

1. 依頼の JSON を書く（形は `skills/works/SKILL.md`）。置き場所はどこでもよい（殻が起動ごとの写しにして渡す）。
2. `WORKS_KEYCHAIN_ITEM=<keychain の項目名> sh works/dev/dogfood.sh <依頼の JSON> "<テストのコマンド>" [<dir>]` を前景で打つ。このリポジトリの今の HEAD（commit 済みの物だけ）を `<dir>/repo` に clone して回し、起動の関所（`launch`）で止まって戻る。
3. 殻が出す approve の行で越える。修正の前の関所（要る時だけ）と最後の関所（この殻では毎回）は、関所の文に載る答えの行で答える（`skills/works/SKILL.md` の 3 節）。殻が出す承認・答え・続き・止める・取り消しの行は `works/dev/continue.sh` を通り、run を起こした herdr の枠へ前後の状態を送る。
4. 報告まで済んだら、殻が出す `git -C <このリポジトリ> apply <dir>/run-<id>.diff` で差分を取り込み、手元でテストを回してから commit する。差分の書き直しは `sh works/dev/dogfood.sh --show <dir> <run-id>`。修正が pack の写し（`.archon/workflows/works`）を書き換えていたら、その部分は取り込まない（殻が「注意:」の 1 行を出す）。

自分食いの run で踏んで、今の形にした所:

- 修正役は run の worktree に `__pycache__` などの git が無視するファイルを残すことがあり、テストの節の緑赤を左右した（バイトコードが無いことを見る試験が偽の赤になった）。今は blk-fix が修正役の前に git が無視するファイルを控え（節 `ignored-before`）、修正役の後・テストの前に、控えに無かった物だけを消す（節 `clean`。消した物の全件は盤面の `fix-removed.json`。報告の冒頭と最後の関所には 0 本でも件数と全パスが出る）。判定・審査の読むだけの検査（作業ツリーの写し）も、git が無視するファイルの増減・書き換えを見る。
- サンドボックスの中の役が書けるのは作業ツリーと `$TMPDIR` だけで、uv のキャッシュと試験の置き場はその外だった（試験が Claude Code の一時フォルダを使えば `guard.sh` が拒む）。今は包みが、Bash を持つ役の起動に run ごとの置き場を書ける場所として足し、子の env に `UV_CACHE_DIR` と `WORKS_RUN_PLACE`（試験の `linekit.work_home` が先に見る）を立てる。`TMPDIR` は Claude Code が書ける一時フォルダへ向けるので向けない（決まりは `.shared/core/adapter.py` の頭の 17）。

## canary（版ごとの確かめの 1 run）

普段の依頼ではたまにしか通らない道を、決まった小さな対象と決まった依頼で 1 run にまとめて通す殻が [dev/canary.sh](dev/canary.sh)（費用が掛かる。回す前に持ち主の了承を取る）。打ち方・旗・環境の変数・拒む形は殻の頭、通ったかの判じの決まりと終了コードは [dev/canary_check.py](dev/canary_check.py) の頭、固定材料の作り方と確かめは [dev/canary_fixture.py](dev/canary_fixture.py) の頭に在る。ここは依頼ごとに狙う道 (a)〜(k) と、種と依頼をその形にした訳を持つ。

依頼の語（`--request`）ごとの種と依頼:

- `tdd`（既定）: 種 `dev/canary-seed/`（標準ライブラリだけの `calc.py`・`textfmt.py`、ただ 1 本のテストのファイル `test_lib.py`・`CHANGELOG.md`・決まりを書いた `README.md`。種のテストは緑で、バグを突くテストはまだ無い。docstring の無い公開の関数が 2 つ在る）と依頼 `dev/canary-request.json`（2 件: `calc.py:mean` の分母と `textfmt.py:initials` の大文字）。道 (a)〜(d)
- `fix`: 同じ種と依頼 `dev/canary-request-fix.json`（2 件: `calc.py:clamp` と `textfmt.py:squeeze` の docstring の欠け）。道 (e)
- `units`: 判定から始めず、固定材料 `dev/canary-fixture-units/` の修正の直前の盤面から始める。道 (f)
- `large`: 測りの run。種 `dev/canary-seed-large/` と依頼 `dev/canary-request-large.json`（5 件）。道 (g)
- `lanes2`: 種 `dev/canary-seed-lanes2/` と依頼 `dev/canary-request-lanes2.json`（4 件）。道 (k)
- `change`: `fix` の種と依頼に commit しない 1 行の変更を足し、`use.sh start --base` で起こす。道 (h)(j)

どの依頼の件も docstring の約束と種の README の決まりで直し方が 1 つに決まる（端の振る舞いを決め手なしに選ぶ余地を残さない。前の形の `truncate` は印より小さい limit の振る舞いが約束に無く、修正が ValueError に決めたのを独立設計が人の判断と見て残り（round_limit）になった）。CHANGELOG の行も各件の依頼が名指す。ラインは 1 周の run で（`entry.start` の `stop_after_round=1`。canary が決めた物ではない）、報告の「止めたか」に出る「周の締めの後で止めた: init --stop-after-round 1」は普通の終わり。2 周目は回らないので、残り（検証器の阻害・最後のテストの赤・独立の目の阻害）が在れば結末は round_limit、無ければ fixed。canary は fixed で終わるのが狙い。origin は裸のローカルのリポジトリなので、並行 PR の確かめは機械が条件外（`no_forge: local_path`）にする（canary の殻は何も特別にしない）。

### 狙う道

- (a) 別のファイルの 2 項目（`calc.py:mean` と `textfmt.py:initials`）: TDD の輪の枝の並べ（TDD の輪が緑にしなかった項目が 2 つ残れば修正役の並べの枝。確かめ役はどちらの並べも数える）
- (b) 2 項目が同じファイルを別の所で変える: 種の README の決まりがテストを `test_lib.py` のモジュールごとのクラス（`TestCalc`・`TestTextfmt`）に、`CHANGELOG.md` の 1 行を `[Unreleased]` のモジュールごとの見出し（`### calc`・`### textfmt`。間に変わらない行が在る）の下に足させるので、2 項目の枝は同じ `test_lib.py` と `CHANGELOG.md` の離れた所を変える（テストを同じ末尾に足せば挿しだけの食い違い）: 重なる枝の 3 方向の合わせ（と試験のファイルの union）。計画役が 2 つの単位を別の項目にした時だけ通る（下の (b) の訳）
- (c) 範囲の外が要る直し（2 件とも README の決まりで要る `CHANGELOG.md` の 1 行。依頼の文が修正案に `allowed_paths` へも `out_of_scope` へも入れさせないと言う）: 範囲の相談。文に依り、確かではない（下の (c) の訳）
- (d) run の中の案の直し: 起きてもよい（起こさせない）
- (e) `fix`: 修正役の並べ（`fix-fork` → 枝の輪 `fix-lane-loop-<n>` → `fix-join`。[docs/plans/2026-10-07-fix-lane-nodes.md](docs/plans/2026-10-07-fix-lane-nodes.md) の 9 節の本物の確かめ）: 別のファイルの 2 項目が 2 本の枝に分かれて同時に走り、各枝の中で `CHANGELOG.md` の 1 行の範囲の相談をし、答えの節 `plan-answer-lane-<n>` が修正案の役の会話の写し（包みの旗 `fork`）で答え、締めが 2 本の枝の `CHANGELOG.md` の足しを 3 方向で合わせる（(a)(b)(c) も修正役の並べで通る）
- (f) `units`: 1 つの修正案の項目に 2 つの単位（0.2.38 の直しの本物の確かめ）: TDD の輪が先の単位の段で項目の受け入れのテストを全部直し、後の単位を段を回さずに機械が閉じる（`tdd-<k>/state.json` の単位の `covered_by`）。食い違いの申し出（TDD の輪の段 `conflict` の呼び・trace の `conflict_parked`）も裁定（`conflict_ruled`・裁定役の節 `rule` の起動）も起きない。判定・修正案の役は起きないので、費用は修正から先の分だけ
- (g) `large`: 全部 on と全部 off の時間と費用（下の (g) の測り）
- (h)(j) `change`: 記録のフック (h) と返答の契約 (j)（局所レビューの役 `p1.local_review`）。ほかの依頼は依頼だけから始める（start の控え `r1/start.json` の `entry` が `request`）ので、局所レビューの役は条件 `not_request_entry` で起きない（1 周の run は修正が入る前の周しか回らない）。`change` は `canary-seed` を 1 回 commit した上で `calc.py:median` の docstring の 1 行の字を commit せずに変え（振る舞いは変えない。変える字は `canary.sh` の `CHANGE_FROM`・`CHANGE_TO`）、`use.sh start --base <その commit>` に依頼 `canary-request-fix.json` を渡す。run は変更と依頼の両方から入り（`entry` が `both`）、局所レビューの役が変更を見る。手で同じ形を通した run e91112dd（0.2.48）で (h)(j) とも yes。依頼の 2 件は `fix` と同じなので (a)〜(e) も通りうるが、終了コードは (h)(j) だけで決める
- (i) 報告の初見の読み手の会話（`report-write-cold` の起動がどれも新しい会話か）: どの依頼でも出し、終了コードに数えない
- (k) `lanes2`: 修正役の並べの 1 本の枝の 2 つ目からの項目（run 97fd532f の直しの確かめ）: 枝の確かめは項目ごとに、その項目の頭（同じ枝の前の項目を受けた後の木）から照らす。前は枝の base から照らしたので、前の項目が変えたファイルが後の項目の `out_of_scope` に当たり、run 97fd532f では 3 本の枝の 2・3 項目目が 19 回拒まれて 1 つも当たらなかった。ほかの依頼は枝ごとに項目が 1 つなので、この道を通らない。種は `canary-seed-large` の振る舞いのバグを直した写しで、docstring の無い公開の関数が 4 つの別々のファイルに 1 つずつ在る（`stats.py:mode`・`units.py:km_to_miles`・`money.py:split_even`・`slugs.py:slugify`。どれも今のテストが振る舞いを確かめていて、先に落ちるテストが無いので direct が素直な案）。依頼の決めが 4 件を 4 項目にし、各項目の `allowed_paths` を自分のファイルだけ・`out_of_scope` をほかの 3 件のファイルにさせる。枝は 3 本までなので、4 項目なら 1 本の枝が 2 項目を順に直し（`fixlanes.assign`）、後の項目の `out_of_scope` に前の項目のファイルが在る。計画役が項目を 3 つ以下にまとめれば 2 項目の枝は植わらず (k) は no。`CHANGELOG.md` は無い（範囲の相談を起こさない）

### (b) の訳: 計画役の決まりからは決まらない

修正案の役の指示書（`.shared/core/gl-prompts/prompts/review-loop/p2.fix_plan.md`）は「1 つの案で複数の単位を閉じてよい（一撃の原理に沿うならそれが望ましい）」と言い、指示書の頭に貼る判定の単位の裏取りの申し送り（`blk-plan/lib/planblk.py` の `VERIFY_ASK`）は「重複・関わり・順番は項目の組み方と並べ方に使え」と言う。裏取りの相乗りの下請け（`blk-judge/lib/judgeverify.py` の `SYNERGY_ASK`）は関わりを「同じファイル・同じ名・同じ試験を触る」と決めているので、2 項目が同じファイルを触る形（(b) の前提そのもの）は必ず関わりとして申し送られ、まとめる向きに押す。どの指示書も、項目が並べの枝になることも、同じファイルの別の所を触る項目を枝の合わせが 3 方向で当てることも言わない。

本物の run では、同じファイルを触る 2 単位を計画役は 1 項目にまとめ（run 01004d2e は依頼の文が別の項目にと頼んでも「同じ import の行・同じクラスを触る」とまとめ、run a2097fd6 は裏取りの申し送りと判定者の見立て「根は 1 つに交わる」を受けてまとめた）、申し送りが無く判定者が「根が別」と見た run 54d81ef1（裏取り・審査の木・枝を切った）だけが 2 項目になった。これを受け、修正案の役の頭に項目の組み方の決まり（`planblk.ITEMS_RULE`。まとめるのは同じ根・同じ行か同じ塊・結果への依存の時だけ）を足し、裏取りの関わりを同じ所（`place: same`）と同じファイルの別の所（`place: apart`）に分け、別の所の関わりではまとめないと申し送りの頼みが言うようにした。その後の run 245042a7（全部 on）・4c32bf37（全部 off）も 1 項目にまとめたが、それは見出しの無い `[Unreleased]` の同じ所に 2 行を足す形が 3 方向の合わせで本当に食い違う（`git merge-file` が終了コード 1）「同じ塊」だったからで、決まりの正しい当て方だった。そこで種の `CHANGELOG.md` にモジュールごとの見出しを置き、2 件の足しが `test_lib.py` でも `CHANGELOG.md` でも食い違わない別の所になるようにした（依頼の文で分けてとは頼まない）。

残る揺れ: `CHANGELOG.md` の 2 つの足しの間の変わらない行は空行と `### textfmt` の 2 行だけで、2 件をまとめた前後 3 行の差分では 1 つの塊に見える。計画役がそれを同じ塊と読めばまたまとめる余地は残る（どこに足すかは修正役が決めるので、種の形では縛れない）。計画役の決まりで確かに分けさせるには指示書の直しが要り、持ち主の決め。(b) を狙う run は `WORKS_USE_FEATURES_OFF=judge_verify` を付けて回せる（申し送りの押しが無くなる代わりに裏取りを通らない）。

### (c) の訳: 範囲の相談は依頼の文に依る

依頼は修正案の決めを文で言うだけで、計画役が従わなければ通らない。依頼の文そのものは修正案の役の指示書に貼られず（貼られるのは判定の単位の名・判定者の見立て・裏取りの申し送りなど）、判定者や裏取りが写した時だけ届く。修正案の指示書は直しが触る物を `allowed_paths` に入れよと言い、種の README の決まりが `CHANGELOG.md` の 1 行を求めるので、計画役が `CHANGELOG.md` を `allowed_paths` に入れるのはむしろ指示書どおりで、そうなれば相談は起きない（run 245042a7・4c32bf37）。0.2.36 から相談は `out_of_scope` に当たる頼みを断らずに答えの節へ回すので、依頼の文は「相談が断る」とは言わない（工場に嘘を言わない）。相談を種の形で確かに起こす道（計画役が読めない・先に見込めない範囲の外の要りようを作る）は、計画役がリポジトリを全部読め、指示書が触る物を範囲に入れよと言う限り、工場を変えずには見つからない。確かにするなら修正案の受け付けか指示書の側の直しで、持ち主の決め。確かめ役は断った相談の訳（`why_refused`）を (c) の行に添える。

### (e) の訳: 既定の依頼では修正役の並べが植わらない

枝に入るのは、範囲（`allowed_paths`）を持ち、TDD の輪が緑にしなかった単位の項目だけで（`blk-fix/lib/fixlanes.py` の `candidates` が `fixrules.dispatched` で TDD の輪の緑の単位（`tddloop.green_units`: 振り分けが tdd・緑が ok・諦めていない）を外し、`fixrules.item_ranges` で `allowed_paths` の無い項目を外す）、それが単位を共にしない 2 本以上の枝に分かれた時だけ `fix-fork` が枝を切る（`fixlanes.fork`。ほかに形 g3・入力 `fix_lanes` が on・包みの書き込みの記録が在る run）。既定の依頼の 2 件は TDD の輪が緑にするので、枝は 0 本になる（run 0a5062f4 の `fix_lanes_planted` は「並べる枝が 2 本に満たない（範囲の在る項目 0・枝 0）」）。

単位が TDD の輪の外に出るのは、修正案の項目の道（`route`）が direct で TDD の役の振り分けも direct にした時（約束が tdd の単位は direct に振れない。`tddloop._plan_tdd`）、TDD の輪が諦めた時、実行器（`tdd_suite`）の無い run の時。`fix` は 1 つ目の道を種の事実で素直にする: 種の README の決まりは公開の関数に docstring を求め、docstring を足した・直した直しにも `CHANGELOG.md` の 1 行を求め、テストは振る舞いだけを確かめて docstring の有無や字を縛らないと言う。docstring を足すだけの直しは先に落ちる受け入れのテストが無く、修正案の指示書（tdd は先に落ちる受け入れのテストを 1 本以上。`planmarks.HEAD`）でも TDD の役の振り分けの指示（文書だけの直しを direct の例に挙げる。`tddloop.DO`）でも direct が素直な案になる。依頼の文は道も項目の分け方も言わない。実行器の無い run でも全部の単位が枝に入るが、それは枝の確かめの試験を回さない形で、実行器の在る普段の run の枝を確かめないので採らなかった。TDD の輪は振り分けの 1 回だけ回る。

(c) と同じく、計画役が `CHANGELOG.md` を `allowed_paths` に入れれば相談は起きず、(e) は attempted になる。判定役か計画役が 2 つの docstring の欠けを 1 単位・1 項目にまとめれば（同じ種類の直しで、範囲の外の `CHANGELOG.md` も共にするので、まとめる向きの押しは残る）、枝は 1 本で (e) は no。TDD の役が docstring を縛るテストを書いて tdd に振れば、その単位は緑になって枝に入らない（種の README の決まりがそれを抑える形）。

### (f) の固定材料

1 項目に 2 単位の形は今の種では自然に起きない（種の形が計画役に単位ごとの項目を作らせる）。そこで、前の種で計画役が 2 単位を 1 項目にまとめた本物の run 245042a7（0.2.36。TDD の輪の 2 つの単位が食い違いを申し出て parked・裁定 2 回）の h-fix の写し（`.shared/core/fixture.py` の固定材料）から始め、判定と修正案を作り直さない。取り込みは対象の木・依頼の文・start の入力が写した時と同じでないと拒むので、`dev/canary-fixture-units/` は `seed/`（その run の種。今の `canary-seed/` と別物）・`request.json`（その run の依頼。今の `canary-request.json` と別物）・`fix-fixture/`（盤面の写し）の 3 つを運ぶ。写しの中の置き場のパスは印に置き換えてあるので、どの機械でも使える。

盤面を開く時に works の表・graph・置き場の版が写した時と違えば start が「固定材料と works の版が違う」で拒む。古さは試験を赤にしない（ラインの表や graph を変えるたびに本物の run を求めないため。`tests/test_canary.py` は古ければ start も同じ物を名指して拒むことだけを見る）ので、CI が緑でも固定材料が古いことは在り、`python3 works/dev/canary_fixture.py check works/dev/canary-fixture-units` か `canary.sh --request units`（何かを作る前にこれで止まる）で初めて分かる。古くなったら、その版で 1 項目 2 単位の案になる本物の run を回して `canary_fixture.py build` で写し直す（`seed/` と `request.json` を種と依頼にして回すのが近道）。

### (g) の測り

同じ依頼を、全部 on は `WORKS_USE_FEATURES_ON=judge_verify,review_tree`、全部 off は `WORKS_USE_FEATURES_OFF=judge_verify,review_tree,tdd_lanes,fix_lanes,graph_map` を前に付けて canary.sh を起こし（use.sh がそのまま読む。何も付けない run は既定）、`canary_check.py --request large` の行を並べる。種は 5 つのモジュール（`stats.py`・`textfmt.py`・`units.py`・`money.py`・`slugs.py`）とテストの `test_lib.py`（モジュールごとのクラス）と決まりの `README.md`。依頼は振る舞いのバグ 3 件（`stats.py:median` の偶数の個数・`textfmt.py:pad_left` の埋める側・`units.py:c_to_f` の係数。どれも今のテストが突かない入力で docstring の約束を破る）と docstring の欠け 2 件（`money.py:split_even`・`slugs.py:slugify`）。5 件は別々の根・別々のファイルなので、項目の組み方の決まりでは 5 項目が素直な案で、振る舞いの 3 項目は tdd（TDD の輪の枝 3 本＝枝の上限）、docstring の 2 項目は direct（修正役の並べの枝 2 本）になる見込み。依頼の文は項目の分け方も道も言わない。振る舞いの 3 件はどれも受け入れのテストを `test_lib.py` に足すので、裏取りの相乗りがまとめる向きに押す余地は (b) と同じに残り、まとめられれば全部 on の run の (g) は attempted になる。`CHANGELOG.md` は無い（範囲の相談を起こさず、測りを並べの段に絞る）。費用の狙いは 1 run 25 USD 以下（2 件の canary の run 245042a7 が 7.4 USD）。

### 回し方

1. `WORKS_KEYCHAIN_ITEM=<keychain の項目名> sh works/dev/canary.sh [--request <語>] [<置き場>]` を裏で起こす（無人の run で報告まで前景で回るので、Claude Code からは `run_in_background` か切り離しの殻で起こす）。置き場の既定は `~/.cache/works-canary/<日時>-<pid>`。`--build-only` は対象と origin を作って起動の行を出すだけ（認証も Archon も使わない）。
2. 走っている間の run id と状態は、殻が最初に出す `use.sh show` の行で見る。終わると殻が run id と確かめの行を出す。
3. `python3 works/dev/canary_check.py <置き場> [<run-id>] [--request <語>]` で、何が実際に通ったかを出す（読むだけ。`--json` で JSON）。道ごとの yes・attempted・no（と依頼から始めた run の (h)(j) の `not_exercised`）の証拠、修正案の項目ごとの範囲と実際に変えたファイル、段ごとの分と AI の節の費用（Archon が費用を記録しなかった節は名指し、和は下限）を出す。終了コードに数える道は語ごとに違う（`fix` は (e) も、`units` は (f)・`large` は (g)・`lanes2` は (k)・`change` は (h)(j) だけ）。

種と依頼の前提（種のテストが緑で約束が赤・参照の直しで各件が独立に直る・(b) の 2 件の足しが 3 方向で食い違わずに合い、件ごとの枝が `git merge` でも枝の締めの口（`unittrees.diff`・`unittrees.apply`）でも食い違わない・依頼が項目の分け方を文で頼まない・各依頼の件と範囲の決め・(h) の変える字が種にちょうど 1 つ在る・固定材料が壊れていない）は `tests/test_canary.py`（FAST）が、殻が対象を作って `use.sh` を正しい引数で起こすことは `tests/test_canary_sh.py`（HEAVY。偽の `use.sh`）が縛る。

## 足りない所

- 周の輪（直ったと言えるまで 2 周目以降を回す）が無い。今のラインは 1 周の run で（`entry.start` の `stop_after_round=1`）、残りが在れば結末は round_limit のまま報告で終わる。続きは人が次の run の依頼に書く（報告の `next-request.json` の下書き）。周の輪は線 B（下の「仕様」）で、main には入っていない。

## 仕様

設計の正本は [`docs/specs/2026-09-26-darkfactory-design.md`](docs/specs/2026-09-26-darkfactory-design.md)。実装計画は [`docs/plans/2026-09-26-darkfactory-v1.md`](docs/plans/2026-09-26-darkfactory-v1.md)。どちらも盤面の層 [`docs/specs/2026-09-26-board-layer-design.md`](docs/specs/2026-09-26-board-layer-design.md) の上に載る。各計画の今の状態は [docs/plans/](docs/plans/) の各ファイルの頭の「状態:」の行に在る。

- 線 A（1 回の run を review-graph と同じ工程に強くする）: 入れた。今のライン `darkfactory` がこれ（修正の後の機械の数え直し `.shared/core/recount.py`・修正案の事前審査と往復 `.shared/core/converge.py` を含む）。設計 [`docs/specs/2026-09-27-darkfactory-single-run-design.md`](docs/specs/2026-09-27-darkfactory-single-run-design.md)・計画 [`docs/plans/2026-09-27-darkfactory-single-run.md`](docs/plans/2026-09-27-darkfactory-single-run.md)
- 線 B（直ったと言えるまで何周も回す入口 `darkfactory-rounds`）: 合流させずに置いた。作りかけは枝 `wip/works-trackB` にだけ在り、2026-09-27 から止まっている（main には無い）。設計 [`docs/specs/2026-09-27-darkfactory-rounds-design.md`](docs/specs/2026-09-27-darkfactory-rounds-design.md)・計画 [`docs/plans/2026-09-27-darkfactory-rounds.md`](docs/plans/2026-09-27-darkfactory-rounds.md)
