<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# 修正役が範囲を計画役に相談する（範囲の相談と事前の確かめ）

状態: 入れた（修正役と下請けの指示書・受け付けの読み口・報告）。run 249・249b で相談が 1 度も起きなかった訳を 2 つ塞いだ（下の「run 249・249b で相談が起きなかった訳」）。残りは本物の run での確かめ（下の「残り」）。

## 目的と語

読む前提: works（このリポジトリの works/ にある、修正依頼を直して出荷する仕組み）の全体は works/README.md と works/docs/specs/2026-09-27-darkfactory-single-run-design.md に在る。食い違いの申し出と裁定は works/.shared/core/conflict.py の頭、修正役の下請けは works/docs/plans/2026-10-06-fresh-session.md・2026-10-06-parallel-units.md。run の名はその試験運用の 1 回の実行の名。

run 195g（0.2.29）の修正の段は、修正役が修正案の項目の「書いてよいパス」の外（例: works/CHANGELOG.md。直しに伴って更新すべき物）と、TDD の輪が凍らせたテストを書き換え、受け付けに 3 回拒まれて単位が止まり、1 単位も取り込めなかった。拒否 1 回の往復は 10〜20 分。範囲を広げる今の道は「修正役が食い違いの申し出を返す → その起動が終わる → 裁定役（新しい AI）が裁く → 案を直す（run に 1 回）→ 修正役を起こし直す」で、裁定の後の新しい申し出は裁けずに機械が最後の人の関所へ回す。

持ち主の方向（2026-10-06）: 「範囲を広げるかは仕様の判断なので、厳しいロボットではなく計画さんと会話して仕様を決めるべき」。修正役は許しを得て直しを続け、計画役が案を更新する。会話は `--resume` で再開する。機械に残すのは事実の確かめ（差分が合意した範囲の中・凍ったテストに触れていない・新しい赤が無い）だけ。裁定役は修正役と計画役の意見が割れた時だけに残す。

この文書の語:

- 修正役・下請け: 修正のブロック（`works/blk-fix/blk-fix.yaml`）の AI の節 fix・fix-ruled と、修正役が Agent の道具で起こす項目ごとの実装役（`works/.shared/core/seat.py` の `g1_section`）
- 計画役: 修正案を書く AI の節（線 darkfactory では blk-plan の節 plan。印 `works-node: plan`）。修正のブロックは名を知らず、入力 `plan_session` の値（会話の印の名）だけを受ける（ブロックの独立）
- 項目・範囲: 承認済みの修正案の項目と、その「書いてよいパス」（allowed_paths の glob と受け入れのテストのファイル）。`out_of_scope` は範囲の中でも触らない物（`works/blk-fix/lib/planscope.py`）
- 凍ったテスト: TDD の輪が緑にした単位のテストのファイル。輪の後に変えてよいのはテストの変更の許し（`conflict.test_permits`）の中だけ
- 包み: Archon が起こす claude の前に挟まる `works/.shared/core/claude-adapter` と `adapter.py`。役の会話の id を `<包みの家>/sessions/<cwd の hash>/<印の名>.id` に記録する
- run ごとの置き場: 盤面の隣の run-place（`adapter.run_place_of`）。包みが Bash を持つ役の sandbox の書ける所に足す。盤面・包みの家・Claude の設定の置き場は柵で書けない
- 範囲の相談（相談）: この一切れで足す道具。修正役か下請けが Bash で `ask_plan.py` を走らせ、機械が計画役の会話を再開して 1 問 1 答する
- 合意: 相談で計画役が許した範囲（項目ごとのパスとテストの変更の範囲）。受け付けが読む
- 事前の確かめ（確かめ）: この一切れで足すもう 1 つの道具 `fix_check.py`。受け付けの事実の確かめ（凍ったテスト・書き込みの出どころ・範囲）を、試験を回さずに返す

## 柵との突き合わせ（止めになるかを先に見た）

修正役の Bash は sandbox の中で走る。調べた結果と決め:

1. 盤面・包みの家・`CLAUDE_CONFIG_DIR`（と `~/.claude`・`~/.claude.json`）は切符の守る所で、sandbox は書かせない（`works/.shared/core/ticket.py`）。claude は会話の記録（transcript）を設定の置き場に書くので、計画役の会話をそのまま `--resume` すると記録を書けない。
   - 決め: 計画役の会話の記録（`<設定の置き場>/projects/<cwd の名>/<会話の id>.jsonl`）を、run ごとの置き場の下の私物の設定の置き場へ写し、`CLAUDE_CONFIG_DIR` をそこへ向けて `--resume` する。元の会話は 1 バイトも変わらない（`--fork-session` は元の置き場に新しい会話を書くので使えない）。2 回目からは写しの会話を継ぐ（計画役は前の相談を覚えている）。包みの記録の id が変わった（同じ run で案を直した 2 度目の計画役）ら写し直す。
2. 盤面は書けない。
   - 決め: 相談の記録と合意は run ごとの置き場（今の scope の下の `ask-plan/`）に書き、受け付け（sandbox の外の script）が盤面の trace に写す（`unitlanes` の当てた記録 merged.json と fix-units の関係と同じ形）。
3. 認証: claude の子は親の認証を継がないことがある（`works/.shared/core/claude_auth.py` の頭）。
   - 決め（2026-10-06 に直した）: 修正役の環境が継いだ認証（`claude_auth.INHERITED` の変数。修正役の claude 自身の認証）が在ればそれを使い、無い時だけ works の殻が Archon を起こす時と同じ `auth_launch.resolve`（WORKS_KEYCHAIN_ITEM → 本流 `claude_auth.auth_env`（親の環境・keychain）→ Claude Code 自身の keychain の項目）で子の環境を組む。子の `CLAUDE_CONFIG_DIR` だけを私物へ向け直す。トークンは子の環境にだけ置き、記録・標準出力・引数に出さない。記録に残すのは出どころの名だけ（`env:CLAUDE_CODE_OAUTH_TOKEN` か resolve の名）。
   - 直した訳（run 68f35d6b。0.2.32 の候補）: 修正役は道具を呼べたが、`unavailable`（`keychain の項目 claude-code-oauth-p3 を読めない: keychain-miss`）で返った。初めの形は resolve を先に呼び、resolve は WORKS_KEYCHAIN_ITEM の名指しを親の環境より先に見るので、sandbox が keychain を読ませない修正役の Bash では必ず外れていた。認証の通り道を読んだ: 殻（`auth_launch.py exec`）は名指しの項目のトークンを `CLAUDE_CODE_OAUTH_TOKEN` に入れて Archon を起こし、Archon は `CLAUDE_CODE_` の変数を消す時もこの名を残し（`CLAUDE_CODE_OAUTH_TOKEN`・`CLAUDE_CODE_USE_BEDROCK`・`CLAUDE_CODE_USE_VERTEX` を除く）、包み（`claude-adapter`）は env を変えずに claude を起こし、Claude Code（2.1.291）は `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`（既定は切。GitHub Actions の中では入）が入でない限り Bash の子から認証を消さない。継いだ認証は殻が同じ順で決めた物なので、先に使っても順は変わらない。
   - 採らなかった形: 包みか支度の節（sandbox の外）が認証を解いて、run ごとの置き場の下に短い間だけ読める資格のファイルを置く形。トークンを 1 度でもファイルに書く（盤面・記録の隣に残りうる）ので、継いだ環境で足りる今は採らない。`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` が入の場（継いだ認証が消える）では keychain の段へ落ち、sandbox の中では聞けず終了コード 3（今の道へ戻る）になる。その場で相談を使う要が出た時に、この形を考え直す。
4. 包みを通さない: 印を付けて包みを通すと、包みは会話の id を家に記録しようとして書けずに止まる（fail closed）。相談は役の起動ではなく、修正役の道具の 1 回の呼びなので、包みの柵（Read の記録・書き込みの柵）は要らない。計画役の子は道具を Read・Grep・Glob に絞り、設定は user の段だけ（対象の CLAUDE.md を読ませない。計画役の節の `settingSources: [user]` と同じ）。
5. 網: 修正役の節は sandbox の網の一覧を持たず、包みは網を閉じない（adapter.py の頭の 8）。claude の子は API に届く。
6. Python: 修正役の sandbox の `python3` は 3.9 のことがある。機械の 2 つのコマンドは、修正役の支度の節（uv で走る）の実行ファイルの絶対パスで書く（支度が指示書に書く）。

7. HOME の下の書き込み（2026-10-06 に足した）: claude は設定の置き場の外にも、HOME の下のキャッシュ（macOS の `~/Library/Caches/claude-cli-nodejs`）と自動更新の置き場（`~/.local/share/claude`）に書く。修正役の sandbox は HOME に書かせない。
   - 決め: 子の HOME を相談の置き場の下の `home/`（書ける所）へ向け、`DISABLE_AUTOUPDATER=1` を立てる。認証は環境で渡すので、子は HOME の keychain・保存済み認証を使わない。
   - 突き合わせた他の段: 会話の写し（`claude-home/`）は run 68f35d6b で書けていた（置き場の下）。網は 5 のとおり修正役の節に網の一覧が無く、包みは網を閉じない。

止めになる物は見つからなかった。ただし入れ子の sandbox の中で claude の子が全部の書き込み先に書けるかは、有料の試しをしていないので確かめていない（下の「危険」と「残り」）。

## 案

### 道具 1: 範囲の相談 `ask_plan.py`

```
<python> <pack>/blk-fix/scripts/ask_plan.py <相談の控え> --item <n> --paths a,b [--tests <パス>[:<行>],…] --why "<理由>"
```

- 相談の控え（`ask-plan.json`）は支度の節（fix-prep・fix-ruled-prep）が run ごとの置き場の今の scope の下に書く: 盤面・作業ツリー・計画役の会話の id の記録のパス・元の設定の置き場・本物の claude・計画役の model と effort・項目ごとの unit_keys と allowed_paths と out_of_scope。
- 機械の先の確かめ（AI に聞く前に断る）: 項目が在る・パスがリポジトリの根の中・`out_of_scope` に当たらない（当たれば計画役が明示に外したパスなので、相談でなく食い違いの申し出の道 fix_plan_item）・もう範囲の中なら聞かない。
- 問い: 項目・欲しいパスとテストの範囲・理由を並べ、計画役に「仕様として範囲を広げてよいか」を聞く。答えの形（JSON Schema。`--json-schema`）は `decision`（allow・deny・defer）・`paths`（許すパス。頼んだ物の部分集合）・`tests`（書き換えを許すテストの範囲）・`spec`（仕様の補い。修正役が従う）・`reason`。
- 機械の後の確かめ: 許したパスとテストは頼んだ物の中だけ（頼んでいない物を足した答えは、足した分を捨てて記録に残す）。形の崩れた答えは invalid として記録し、修正役に返す（許しは作らない）。
- 記録: 1 問 1 行を `ask-plan/exchanges.jsonl` に積む（番号・時刻・項目・頼んだ物・理由・答え・会話の id・認証の出どころの名）。並べた下請けが同時に聞いても、錠で 1 つずつにする（同じ写しの会話に 2 本の再開を同時に積まない）。
- 出力: 答えの 1 行の JSON。終了コードは 0（答えた。deny・defer も）・3（聞けない: 会話の記録が無い・認証が無い・claude が落ちた。理由つき）・2（使い方の誤り）。3 の時、修正役は今の道（食い違いの申し出の scope_needed）へ戻る。

### 道具 2: 事前の確かめ `fix_check.py`

```
<python> <pack>/blk-fix/scripts/fix_check.py <相談の控え> [--reply <下書きの返答の JSON>]
```

- 受け付け（`blk-fix/scripts/accept.py`）の `check_frozen`・`check_writes`・`check_plan_scope` をそのまま呼ぶ（規則を写さない）。試験は回さない（変更に当たる試験と事後の関門の束は受け付けだけ）。
- 盤面は読むだけ: `entry.open_board` に読み取りの印（env `WORKS_BOARD_PEEK=1`）を足し、scope の登録と窓の照らし（どちらも盤面を書く）を飛ばす。scope は控えの値で立てる。
- まだ受け付けが盤面へ写していない合意（run ごとの置き場の記録）も足して照らす（受け付けと同じ答えになる）。
- 出力: `{ok, rejects: [{check, text}]}`。終了コードは 0（通る）・1（拒否の行が在る）・2（回す側の誤り）。

### 受け付けの読み口（機械が持つ規則は 1 か所）

- 受け付けは頭で、run ごとの置き場の相談の記録のうち盤面にまだ無い行を、盤面の trace の行 `plan_scope_asked`（`conflict.ASKED_OP`）に写す（全部の答え。拒否の回でも写す——相談は受け付けの結果に依らず起きた事実）。
- 合意の読み口は `conflict.agreed(b)`（trace の行のうち allow）1 つ。
  - 範囲: `planscope.check` が項目ごとに合意のパスを allowed_paths に足す（`planscope.with_agreed`）。`out_of_scope` は今どおり勝つ（道具が先に断るので、ここに来るのは控えが変わった時だけ）。
  - テスト: `conflict.test_permits` が修正案の `rewrite_tests` と裁定の範囲に並べて合意の `tests` を許しに入れる。凍結の検査と最後の人の関所の書き換えたテストの一覧は同じ口から引くので、相談で許した書き換えも人に見える。
- 新しい盤面のファイルは作らない（trace の行だけ）。部品の窓の照らし（`scopes.check_window`）で宣言の外にならないことを試験で見る（0.2.28 の宣言の外の書き込みの型）。

### 指示書

- 修正役（`rules/direct.md` の節 fix-ask）: 範囲の外が要る・凍ったテストを書き換えたい時は、黙って出ずに・申し出で起動を終えずに、先に相談せよ。allow なら続けて直す（`spec` に従う）。deny なら範囲の中で直すか、仕様として割れているなら食い違いの申し出。defer は今の run で直さない（`not_done` に理由）。返答の前に事前の確かめを走らせ、出た行を直してから返せ。
- 下請け（`seat.g1_prompt` の後ろ）: 同じ 2 つのコマンドと決まりを、下請けのファイルの終わりに機械が足す（下請けは修正役の指示書を読まない）。
- brief の決まりの 8（`rules/brief.md`）: 範囲の外が要る時、指示書に相談の節が在れば先に相談する。相談の無い役（TDD の輪）は今どおり申し出。
- 食い違いの申し出の `scope_needed` は、相談が聞けない（終了コード 3）・計画役が deny したが修正役は仕様として要ると見る、の時の道に残る（意見が割れた時の裁定役）。

### 配線

- blk-fix の入力 `plan_session`（範囲の相談を受ける役の会話の印の名。空は相談しない）。darkfactory は 2 つの blk-fix の include に `plan_session: plan` を渡す。
- 報告（`report.head_reads`）に相談の行: 回数・allow・deny・defer・invalid の数と、許したパス。

## 決定（設計に無かった所。既存の設計に一番近い物を選んだ）

- 再開は fork でなく写し: 元の会話を変えない約束を、柵の中で守れる唯一の形。写しは run ごとの置き場に残るので、何を聞いて何と答えたかを後で読める。
- 合意は案のファイルを書き換えず、trace の行で足す: 承認済みの修正案の控え（plan-fields.json と brief）は凍結の印で守られ、書き換えると凍結の検査が盤面を止める。合意は「案への追記」として別に持ち、範囲とテストの許しの読み口で足す（裁定の limits を足すのと同じ形）。
- 合意は修正役が書ける所（run ごとの置き場）を通るので、偽れる。守りは merged.json・bash_writes の申告と同じ水準で、報告と最後の関所に全部の相談が並ぶことで人が見る。
- `out_of_scope` は相談で外さない: 計画役が明示に外したパスで、外すのは案の誤り（fix_plan_item）の道。
- deny の後に同じ物を聞き直すのは止めない（理由を変えて聞くのは会話）。回数の上限・期限は足さない（R50）。
- 計画役の model・effort は、包みの起動の記録の最後の計画役の行から引く（無ければ CLI の既定）。

## 危険

- 入れ子の sandbox の中の claude の子が、私物の設定の置き場と子の HOME の外（TMPDIR 以外の決まった場所）に書こうとして落ちうる。落ちれば終了コード 3 で、修正役は今の道へ戻る（害は今と同じ往復）。
- 親の環境に認証が無く（`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` が入の場など）keychain も sandbox から読めなければ、聞けない（3）。
- 計画役の会話が長いと、再開ごとに入力のトークンが掛かる（写しは compact しない）。

## 入れた物

- `works/blk-fix/lib/askplan.py`: 控え・問い・答えの形と確かめ・会話の写しと再開・記録・盤面への写し
- `works/blk-fix/scripts/ask_plan.py`・`fix_check.py`: 2 つのコマンド
- `works/blk-fix/lib/fixrules.py`・`rules/direct.md`・`rules/brief.md`・`works/.shared/core/seat.py`: 指示書
- `works/blk-fix/scripts/accept.py`: 頭で記録を盤面へ写す
- `works/.shared/core/conflict.py`・`works/blk-fix/lib/planscope.py`: 合意の読み口
- `works/.shared/core/entry.py`: 読み取りの印
- `works/.shared/core/report.py`: 報告の行
- `works/blk-fix/blk-fix.yaml`・`works/darkfactory/darkfactory.yaml`: 入力と配線

## run 249・249b で相談が起きなかった訳（2026-10-06 に直した）

どちらの run も支度の節が相談の控え（`ask-plan.json`）を書き、指示書に相談の節が載ったが、相談の記録（`exchanges.jsonl`）は空だった。249b（Archon の run 5436f585）の盤面で読んだ訳と直し:

1. 範囲の照らしが、項目 1 の `out_of_scope`（`works/.shared/core/**`）を項目 2 の単位にも当て、項目 2 が `allowed_paths` に明示に許した `works/.shared/core/spseam.py` の直しを 2 回拒んだ（`fixing/reject-accept_fix-*.txt`）。修正役から見ればそのファイルは自分の項目の範囲の中なので、相談の道具に聞いても「もう範囲の中」で断られる。単位は止まって持ち越され、run の中の案の直しで項目 1 の行を消すしかなかった（申し出 c1-1・c1-2）。
   - 直し: `planscope._oos_hit_for`。行の単位の項目が明示に許したパス（`allowed_paths`・受け入れと書き換えのテストのファイル・合意）は、その単位の項目の `out_of_scope` だけで照らす。単位の項目が許していないパスと、どの行も申告していない変わったパスは、今どおり全部の項目の `out_of_scope` で拒む（単位に結べない変更は緩めない。拒否の行は許す項目を名指して申告の道を言う）。`permits`（run の全部に効くテストの許し・裁定の limits）は明示の許しに数えない。
   - 案の受け付けで「ある項目の `out_of_scope` がほかの項目の `allowed_paths` に重なる」を拒む機械の確かめは足さない。直しの後は、重なりは「項目 1 は core を変えない・項目 2 は core の 1 ファイルを変える」の正しい書き方で、拒めば計画役に意味の在る行を消させる。glob どうしの重なりも機械では決め切れない。`out_of_scope` と tests の id のファイルの重なりの拒否（`planmarks._scope_overlaps`）は今のまま。
2. 受け付けの範囲の拒否の文の頭（`planscope.REJECT`）が「範囲の外が要るなら変えずに食い違いの申し出で返せ」と言い、指示書の相談の節（範囲の外が要るだけで申し出で起動を終えるな・先に相談せよ）と食い違っていた。修正役は拒否の文に従って申し出を返した。
   - 直し: その段の相談の控えが在る時（`askplan.offered`。控えの段の名が今の段と同じで、項目が在る）は、頭を `planscope.REJECT_ASK`（allowed_paths の外が要るなら相談のコマンドで聞け・聞けない・許されずに割れる時と `out_of_scope` の物が要る時だけ申し出）にする。事前の確かめ（`factchecks.precheck`）は相談の節の道具なので、いつも `REJECT_ASK`。控えが無い段は今どおり `REJECT`。brief の決まりの 2（数え直しが範囲の外を求める時）と、下請けの申し出の手引きの `scope_needed` の場面にも、相談の節が在れば先に相談すると書いた。

## 残り

- 本物の run での確かめ: 修正役の sandbox の中から claude の子が起きて答えること（網・書き込み・認証）。写しの会話が元の計画役の文脈を持っていること。受け付けが合意を読んで範囲の外の行を拒まないこと。run 249・249b では相談が 1 度も起きず、ここはまだ確かめていない（上の 2 つの訳を塞いだ後の run で、範囲の外が要る単位が出た時に見る）。
- 相談を TDD の輪の役にも渡すか（今は渡さない。輪の役は単位ごとに会話を切るので、入れるなら同じ控えを tdd-prep が書く）。
