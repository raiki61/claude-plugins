<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# 修正役が範囲を計画役に相談する（範囲の相談と事前の確かめ）

状態: 入れた（2026-10-07 に形を替えた）。相談は修正の輪の中の Archon の節（頼み・答え・確かめ）で起きる。前の形（修正役の Bash から
`claude --resume` を起こすコマンド `askplan.py`）は、Claude Code が Bash の子から認証を外すので 1 度も答えを得られず（run 195h）、
退けた（下の「前の形と退けた訳」）。残りは本物の run での確かめ（下の「残り」）。

## 目的と語

読む前提: works（このリポジトリの works/ にある、修正依頼を直して出荷する仕組み）の全体は works/README.md と works/docs/specs/2026-09-27-darkfactory-single-run-design.md に在る。食い違いの申し出と裁定は works/.shared/core/conflict.py の頭、修正役の下請けは works/docs/plans/2026-10-06-fresh-session.md・2026-10-06-parallel-units.md。run の名はその試験運用の 1 回の実行の名。

run 195g（0.2.29）の修正の段は、修正役が修正案の項目の「書いてよいパス」の外（例: works/CHANGELOG.md。直しに伴って更新すべき物）と、TDD の輪が凍らせたテストを書き換え、受け付けに 3 回拒まれて単位が止まり、1 単位も取り込めなかった。範囲を広げる道は「修正役が食い違いの申し出を返す → その起動が終わる → 裁定役が裁く → 案を直す（run に 1 回）→ 修正役を起こし直す」しか無かった。

持ち主の方向（2026-10-06）: 「範囲を広げるかは仕様の判断なので、厳しいロボットではなく計画さんと会話して仕様を決めるべき」。修正役は許しを得て直しを続け、合意は案への追記として残る。機械に残すのは事実の確かめ（差分が合意した範囲の中・凍ったテストに触れていない・新しい赤が無い）だけ。裁定役は修正役と計画役の意見が割れた時だけに残す。

持ち主の方向（2026-10-07）: 相談は修正の輪の中の Archon の節にする（修正役が返答で頼み → 計画役の会話の続きの節が答える → 機械の節が確かめて記録する → 修正役が同じ会話の続きで直す）。役の Bash から claude を起こさない。包み（adapter）を通して認証を中継する形（枝 wip/ask-auth2）は、役の権限を広げるので退けた。

この文書の語:

- 修正役・下請け: 修正のブロック（`works/blk-fix/blk-fix.yaml`）の AI の節 fix（1 回目）・fix-ruled（裁定の後の 2 回目。fix の会話の続き）と、修正役が Agent の道具で起こす項目ごとの実装役（`works/.shared/core/seat.py` の `g1_section`）
- 計画役: 修正案を書く AI の節（線 darkfactory では blk-plan の節 plan。印 `works-node: plan`）。修正のブロックは名を知らず、入力 `plan_session` の値（会話の印の名）だけを受ける（ブロックの独立）
- 項目・範囲: 承認済みの修正案の項目と、その「書いてよいパス」（allowed_paths の glob と受け入れのテストのファイル）。`out_of_scope` は範囲の中でも触らない物（`works/blk-fix/lib/planscope.py`）
- 凍ったテスト: TDD の輪が緑にした単位のテストのファイル。輪の後に変えてよいのはテストの変更の許し（`conflict.test_permits`）の中だけ
- 包み: Archon が起こす claude の前に挟まる `works/.shared/core/claude-adapter` と `adapter.py`。役の会話の id を `<包みの家>/sessions/<cwd の hash>/<印の名>.id` に記録し、印の `continue=<名>` でその会話を継ぐ
- 範囲の相談（相談）: 修正役が返答の欄 `consult` で頼み、修正の輪の 3 つの節が答える仕組み
- 合意: 相談で計画役が許した範囲（項目ごとのパスとテストの変更の範囲）。受け付けが読む
- 事前の確かめ（確かめ）: 修正役と下請けが Bash で回す `factchecks.py`。受け付けの事実の確かめ（凍ったテスト・書き込みの出どころ・範囲）を、試験を回さずに返す（claude は起こさない）

## 形（2026-10-07）

修正の輪（`fix-loop`。2 回目の `fix-ruled-loop` も同じ形）の 1 周:

```
fix-prep ─▶ fix ─▶ fix-consult ─▶ plan-answer ─▶ fix-consult-check ─▶ fix-accept
 (script)   (AI)    (script)        (AI。when go)   (script)             (script)     (script)
```

2 回目の輪は `fix-ruled-prep ─▶ fix-ruled ─▶ fix-ruled-consult ─▶ plan-answer-ruled ─▶ fix-ruled-consult-check ─▶ fix-ruled-accept`。

1. **頼み（役の返答の欄 `consult`）**: 修正役は範囲の外が要る時、変える前に返答の任意の欄 `consult`（`conflict.CONSULT_SCHEMA`。項目ごとに 1 件 `{item, paths, tests, why}`）を書いて周を終える。ほかの欄は途中の形でよい（その周は受け付けが見ない）。作業ツリーの直しは残す。下請けは自分で相談せず、まとめ役の修正役に頼みを報告する（`rules/direct.md` の節 fix-ask-sub）。
2. **頼みの節 `fix-consult`**（`scripts/consult_prep.py` → `consult.ask`）: 返答に `consult` が無ければ何もしない（`consulted: false`）。在れば頼みごとに機械の先の確かめ（`consult.screen`: 知らない項目・頼む物が無い・理由が短い・根の外のパス・全部がもう範囲の中。`out_of_scope` に当たる頼みは断らない——下の「out_of_scope の考え直し」）をして、盤面の今の scope の周の状態（`consult-<段>.json`）に積む。聞く頼みが在れば、入力 `plan_session` の名で包みが記録した会話の id を、ブロックの中の名 `fix-planner` の id として包みの置き場に写し（`consult.alias`）、答えの節の指示書（`consult-<段>-<周>-ask.md`）を書いて `go: true`。相手の会話の id が無い（plan_session が空・計画役が走っていない）なら、その頼みは聞けない行にして `go: false`。
3. **答えの節 `plan-answer`**（AI。opus・medium。印 `works-node: plan-answer continue=fix-planner`）: 包みが SDK の会話の旗を外して `--resume <fix-planner の id>` で起こす（計画役の会話の続き。fork しない）。道具は計画役と同じ読むだけの物（Read・Grep・Glob・WebSearch・WebFetch）。答えは `consult.ANSWER_SCHEMA`（`answers: [{ask, decision: allow|deny|defer, paths, tests, spec, reason}]`）。
4. **確かめの節 `fix-consult-check`**（`scripts/consult_check.py` → `consult.settle`）: 答えを頼みごとに確かめ（`consult.judge`。許すのは頼んだ物の中だけ。頼んでいない物は捨てて注記。形の崩れた答えは invalid で許しを作らない）、1 頼み 1 行を盤面の trace（`conflict.ASKED_OP`）に書く（断った・聞けなかった行も）。修正役が読む答えのファイル（`consult-<段>-<周>.md`）を書く。出力 `consulted: true` で、後ろの受け付け（fix-accept。修正役の並べの枝では枝の確かめ fix-lane-step-<n>）はその周を回さない（受け付けは拒否の理由のファイルも最後の結果の控えも書かない。`done` は立てない）。
5. **続き**: 次の周の支度（`fixrules.prep` が `consult.take` を引く）は、指示書を組み直さず、答えのファイルと前の指示書を名指す短い続きの指示書（`rules/direct.md` の節 fix-consult-resume）だけを書く。`iteration` は前の回のまま（相談の周は受け付けの 3 回に数えない）。修正役は同じ会話の続きで起きる: 1 回目の修正役は印の旗 `self-resume`（下の「包みの旗 self-resume」）、2 回目は今までどおり `continue=fix`。
6. **合意の読み口**（前の形から変えない）: `conflict.agreed(b)`（trace の行のうち allow）1 つ。範囲は `planscope.with_agreed` が項目の allowed_paths に足し（`out_of_scope` には勝たない。ただし許したパスと字のまま同じパスは、その項目の `out_of_scope` から外す——下の「out_of_scope の考え直し」）、テストは `conflict.test_permits` が許しに入れる（凍結の検査と最後の人の関所の書き換えたテストの一覧も同じ口）。事前の確かめも同じ口で読む。報告は `report.plan_ask_lines` が回数・答えごとの数・許した範囲を出す。

### out_of_scope の考え直し（持ち主 2026-10-07「相談で考え直させる」）

前は先の確かめが、頼んだパスがその項目の `out_of_scope` に当たると答えの節に聞かずに断り（「修正案が明示に外したパスで、相談では足さない。要るなら食い違いの申し出で返せ」）、修正役は `scope_needed` の申し出で返すしかなかった。run 54d81ef1（canary。置き場 `~/.cache/works-canary/20261007-101440-74823`）は、直しに伴う `CHANGELOG.md` の 1 行が項目 1 の `out_of_scope` に当たって断られ、申し出 → 裁定 `fix_plan_item` → 修正案の直しの関所で無人の run が止まった。外した本人に理由を見せて考え直させれば済む所を、案の誤りの道（修正案の直し・事前審査・人の関所）に回していた。

- 先の確かめは `out_of_scope` に当たる頼みを断らず、答えの節へ回す。ほかの断り（知らない項目・根の外・もう範囲の中・理由が短い・枠）はそのまま。
- 指示書（`consult.question`）は相談ごとに当たりを並べる（`consult.oos_hits`）: その項目の `out_of_scope` なら「あなたがこの項目の out_of_scope に書いた物」と glob と外した理由（修正案の欄の `why`）を字のまま引き、外した理由が今も立つかを直している側の理由と比べて考え直させる。ほかの項目の `out_of_scope` に当たるなら、その項目と glob と理由を名指す（e7906845 の決まりどおり、ほかの項目の `out_of_scope` はこの項目が許すパスを禁じないので、許せばこの項目の単位の変更としてだけ通る）。
- 確かめの節は、trace の行に当たり（`out_of_scope`: `{path, item, glob, why}`）と、allow ならその項目の `out_of_scope` を外した物（`overrode_out_of_scope`: `{path, glob, why}`）を書く。答えのファイルと報告の相談の行（`report.plan_ask_lines`）は「out_of_scope を外した」か「外したままにした」を言う。
- 範囲の照らし（`planscope.with_agreed`）は、合意の行の許したパスと許したテストの範囲のパスを、その項目の写しの `out_of_scope_lifted`（`planscope.LIFTED`）に並べ、字のまま同じパスに限ってその項目の `out_of_scope` から外す（`_oos_hit`）。glob の許しで広げない・ほかの項目の `out_of_scope` は外さない（単位に結べない変更は今どおり全部の項目の `out_of_scope` で照らし、外した項目だけが当たらなくなる）。受け付けと事前の確かめは同じ `planscope.check` を通るので、同じに効く。守りのファイル・根の外は今どおり（合意は範囲の照らしにしか効かない。根の外の頼みは先の確かめが断る）。
- deny・defer は何も外さない。修正役は今どおり範囲の中で直すか、仕様として割れていれば `scope_needed` の申し出で返す。
- 合意は今どおり盤面の trace の行だけ（sandbox の外の確かめの節が書く）。

### 包みの旗 self-resume

Archon の輪は、直前に終わった AI の節の会話を次の AI の節に継がせる（v0.11.1 の dag-executor の `lastSequentialSession`。`fresh_context: false` の輪は 2 周目の頭の節にも前の周の最後の会話を渡す）。輪に答えの節が挟まると、次の周の修正役は計画役の会話を継いでしまう。そこで修正役の印に旗 `self-resume` を足した（`works-node: fix self-resume`。`recount.fix_output_format` が付ける）。包み（`adapter.plan` の 1）は旗を持つ節について:

- SDK が会話を継ぐ起動（`--resume`・`-r` を付けた起動。輪の 2 周目から）は、SDK の会話の旗を外して `--resume <この節自身の記録した id>` で起こす（fork しない）。自分の id が無ければ起こさない（fail closed）。
- SDK が会話を継がない起動（輪の 1 周目）は旗の無い節と同じに新しい会話。

答えの節が無い周（相談の無い run）は、SDK が継がせる会話がもともと修正役自身の会話なので、振る舞いは前と同じ（fork でなく同じ id に積むことだけが違う）。

### ブロックの独立と印

印は YAML に静的に書く（Archon は `output_format` の中の `$INPUTS` を置き換えると確かめていない）。答えの節の継ぐ相手を `continue=plan` と書くと、blk-fix が blk-plan の節の名を知ることになる。そこで印はブロックの中の名 `continue=fix-planner` にし、頼みの節（sandbox の外の script）が入力 `plan_session` の名の id をこの名で写す（`consult.alias`。包みの置き場の書き方は包みと同じ一時ファイルからの置き換え）。線 darkfactory は今までどおり 2 つの blk-fix の include に `plan_session: plan` を渡す。

### 回数の枠（R50）

輪は受け付けの done で抜ける（max_iterations に当てて run を落とさない。R50）。相談の周も輪の周を 1 つ使うので、輪の上限は受け付けの 3 回（`accept.GIVE_UP_AFTER`）と相談の周の枠（`consult.BUDGET` = 9）の和の 12。枠を使い切った後の `consult` は、頼みの節が相談の周にせず（`spent: true`）、受け付けが拒否の行（確かめの id `consult`）にする。これで輪の周は「相談 9 + 受け付け 3」を超えない。

### 柵との突き合わせ

- 役の Bash から claude を起こさない。答えの節は Archon が起こす普通の AI の節で、認証は Archon の起動のまま（包みは env を変えない）。
- 合意は盤面の trace に sandbox の外の節が書く（前の形は役の Bash が書ける run ごとの置き場を通ったので偽れた。今は役が書ける所の行を合意に数えない。`tests/test_fix_precheck.py` の test_run_place_rows_do_not_count）。
- 新しい盤面のファイルは作らない: 状態・問い・答え・続きの指示書は今の scope の周の作業ファイル（scope の根の私物）、記録は trace の行。部品の窓の照らし（`scopes.check_window`）で宣言の外にならないことを `tests/test_consult.py` が見る。
- 計画役の会話は答えの節の分だけ伸びる（前の形の「元の会話を 1 バイトも変えない」はやめた）。案の直し（blk-plan の plan-revise continue=plan）がその後に同じ会話を継ぐと、相談で許した範囲を覚えている。これは利点と見た。
- 答えの節は `mutates_checkout: false`（読むだけ）。同じ層に他の節は無いので並びは変わらない。

## 前の形と退けた訳（2026-10-06〜07 の記録）

前の形（0.2.32〜0.2.35）: 修正役か下請けが sandbox の中の Bash で `askplan.py <控え> --item <n> --paths … --why …` を走らせ、機械が計画役の transcript を run ごとの置き場の私物の設定の置き場へ写し、`claude -p --resume <写しの id>` を子として起こして 1 問 1 答した。記録は run ごとの置き場の `exchanges.jsonl` に積み、受け付けが頭で盤面の trace へ写した。

退けた訳:

1. **認証**（止めになった物）: Claude Code は Bash の道具の子から `CLAUDE_CODE_OAUTH_TOKEN` を外す。run 195h の相談は全部 refused か unavailable（`keychain の項目 claude-code-oauth-p3 を読めない: keychain-miss`）で、1 度も答えを得られなかった。継いだ認証を先に使う直し（run 68f35d6b の後。0.2.32 の候補）も、継ぐ物が子に来ないので効かなかった。sandbox は keychain を読ませないので、keychain の段にも落ちられない。
2. **包みを通して認証を中継する形**（枝 wip/ask-auth2）: 役が包みに頼んで認証つきの子を起こさせる。役の権限（認証を持つ子を起こす力）を広げるので、持ち主が退けた（2026-10-07）。
3. **合意を偽れる**: 記録が役の書ける所を通るので、修正役が `exchanges.jsonl` に allow の行を書けば範囲が広がった（守りは merged.json・bash_writes の申告と同じ水準で、報告に並ぶことで人が見るだけだった）。
4. 入れ子の sandbox の中の claude の子の書き込み先（HOME の下のキャッシュ・自動更新の置き場）を、私物の HOME と自動更新を止める env で避けていた。有料の試しをしないままで、ここも危険として残っていた。

前の形から残した物: 先の確かめ（screen）・答えの確かめ（judge）・答えの形・合意の読み口（conflict.agreed・planscope.with_agreed・test_permits）・事前の確かめ（factchecks.py。claude を起こさないので害が無い）・拒否の頭（planscope.REJECT_ASK。文は返答の欄 consult を言う形に替えた）・報告の行。`askplan.py` は `consult.py` に名を替え、起動・認証・会話の写し・錠・run ごとの置き場の記録の部分を消した。

### run 249・249b で相談が起きなかった訳（2026-10-06 に直した。今の形でもそのまま効く）

1. 範囲の照らしが、項目 1 の `out_of_scope`（`works/.shared/core/**`）を項目 2 の単位にも当て、項目 2 が `allowed_paths` に明示に許したパスの直しを拒んだ。修正役から見ればそのファイルは自分の項目の範囲の中なので、相談しても「もう範囲の中」で断られる。
   - 直し: `planscope._oos_hit_for`。行の単位の項目が明示に許したパス（`allowed_paths`・受け入れと書き換えのテストのファイル・合意）は、その単位の項目の `out_of_scope` だけで照らす。単位に結べない変更は今どおり全部の項目の `out_of_scope` で拒む。
2. 受け付けの範囲の拒否の文の頭（`planscope.REJECT`）が「範囲の外が要るなら食い違いの申し出で返せ」と言い、指示書の相談の節と食い違っていた。
   - 直し: その段の相談の控えが在る時（`consult.offered`）は頭を `planscope.REJECT_ASK`（allowed_paths の外が要るなら返答の consult で相談せよ。聞けない・許されずに割れる時と `out_of_scope` の物が要る時だけ申し出）にする。事前の確かめはいつも `REJECT_ASK`。

## 指示書

- 修正役（`rules/direct.md` の節 fix-ask）: 範囲の外（`out_of_scope` に当たる物も）が要る・凍ったテストを書き換えたい時は、黙って出ずに・申し出で起動を終えずに、返答の `consult` で相談せよ。allow なら答えのファイルの「範囲に入った物」だけを足して続ける（仕様の補いに従う）。deny なら範囲の中で直すか、仕様として割れているなら食い違いの申し出。defer は今の run で直さない（`not_done` に理由）。答えの無い頼み（refused・unavailable・invalid）は理由を読み、聞けなければ申し出。枠を使い切った後は受け付けが拒む。下請けが範囲の外を報告したら、まとめ役が `consult` に書く。返答の前に事前の確かめを走らせる。
- 下請け（`rules/direct.md` の節 fix-ask-sub。g1・g3 の実装役のファイルの終わりに機械が足す）: 範囲の外が要れば変えずに、報告に「範囲の相談が要る」と項目・パス・テスト・理由を書いて返す。事前の確かめは `--reply` なしで走らせる。
- 続きの指示書（節 fix-consult-resume）: 答えのファイルと前の指示書を名指す。決まりは貼り直さない（同じ会話の続き）。
- brief の決まりの 2 と 8（`rules/brief.md`）: 範囲の外が要る時、指示書に相談の節が在れば先に返答の `consult` で相談する。相談の無い役（TDD の輪）は今どおり申し出。
- 申し出の手引き（`seat.DIVERGENCE_SCENES` の scope_needed）: 相談の節が在れば先に consult で相談して許されなかった時。下請けは相談が要ることをまとめ役に報告する。
- 食い違いの申し出の `scope_needed` は、相談が聞けない・計画役が deny したが修正役は仕様として要ると見る、の時の道に残る（意見が割れた時の裁定役）。

## 入れた物（2026-10-07）

- `works/blk-fix/lib/consult.py`（`askplan.py` の名を替えた）: 頼みの読み・先の確かめ・答えの確かめ・問いと答えのファイル・相手の会話の写し・状態・3 つの節の中身・相談の控え
- `works/blk-fix/scripts/consult_prep.py`・`consult_check.py`: 頼みの節と確かめの節
- `works/blk-fix/blk-fix.yaml`: 2 つの修正の輪に 3 節ずつ・修正役の印の旗 self-resume・`consult` の欄・輪の上限 12・締める節と受け付けの `consulted`
- `works/.shared/core/adapter.py`・`node_marker.py`: 旗 self-resume
- `works/.shared/core/conflict.py`（`CONSULT_FIELD`・`CONSULT_SCHEMA`）・`recount.py`（修正役の output_format）
- `works/.shared/core/stage-models.json`: plan-answer・plan-answer-ruled は plan_writer（opus・medium）
- `works/blk-fix/scripts/accept.py`（相談の周の出口・枠の拒否）・`units.py`（相談の周は締めない）・`lib/fixrules.py`（控え・続きの指示書・下請けの節）・`lib/factchecks.py`（合意は盤面だけ）・`lib/planscope.py`（拒否の頭）
- `works/blk-fix/rules/direct.md`・`brief.md`・`works/.shared/core/seat.py`: 指示書
- 試験: `tests/test_consult.py`（FAST）・`tests/test_fix_precheck.py`（HEAVY。本物の盤面で頼み → 答え → 確かめ → 続き → 受け付け）・形の試験（test_blk_fix・test_blk_fix_conflict・test_fix_rules・test_yaml_rules・test_tool_parity・test_node_marker・test_fix_accept_all）・筋書きの stub（`*/fixtures/*.stubs.yaml` の頼みの節と確かめの節）

## 危険

- 包みの無い run（`WORKS_DEV_ADAPTER=0`）では印の `continue=`・`self-resume` が効かない。答えの節は Archon が渡す修正役の会話を継ぎ、次の周の修正役は答えの節の会話を継ぐ（2 回目の修正役の continue=fix と同じ制約）。
- 計画役の会話が長いと、答えの節の起動ごとに入力のトークンが掛かる（会話を compact しない）。
- 輪の上限が 3 から 12 に上がった。受け付けの 3 回で抜ける決まりは変わらないが、相談が続けば 1 段の修正の時間は伸びる。

## 残り

- 本物の run での確かめ: 範囲の外のパスが要る依頼（例: 直しに伴って works/CHANGELOG.md の 1 行が要るが、修正案の項目の allowed_paths に CHANGELOG が無い）で、(1) 修正役が `consult` を返す、(2) 答えの節が計画役の会話の続きで起きる（包みの起動の記録 launches の plan-answer の行が session.mode continued・of fix-planner・id が plan の id と同じ）、(3) trace に plan_scope_asked の allow の行が残る、(4) 次の周の修正役が自分の会話に戻る（launches の fix の 2 行目が continued・of fix・sdk に計画役の id）、(5) 受け付けが CHANGELOG を範囲に入れて通す、(6) 報告に「範囲の相談」の行が出る。
- TDD の輪の役にも同じ形を渡すか（今は渡さない。輪の並べの節を Archon の節にする作業が、この輪の形を写して使う予定）。
