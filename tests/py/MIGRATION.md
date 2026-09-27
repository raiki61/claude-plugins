# ルートの台本から pytest への移し替えの台帳

## 台帳（review-record.py の節）

<!-- ledger:begin -->
| 終了 | 台本の検査（説明文） | 期待の文言 | 読む記録 | 移した先 |
|---|---|---|---|---|
| 1 | round-1 だけの記録は、比較の欠落を阻害要因に数える | 前ラウンドの記録が無い | tmpl-1 | test_review_record.py::test_validator[tmpl-1-no-prev] |
| 1 | 解消した直後のラウンドは連続 2 ラウンドの 1 ラウンド目 | 前ラウンドに阻害要因が 4 件あった | tmpl-12 | test_review_record.py::test_validator[tmpl-12-prev-blockers] |
| 1 | 問いが立った周には帰属せず、印だけが付く | （今ラウンドに立った問い——再審は次の周） | tmpl-1 | test_review_record.py::test_validator[tmpl-1-fresh-mark] |
| 1 | 増えた scalar だけを、増えた scalar の節に出す | 増えた scalar（阻害要因ではない。相殺する削除があるか R1 に見せろ）:⏎  - scalar 'doc_lines': 120 → 135⏎  - scalar 'comment_ratio_pct': 18 → 21⏎持ち越し | tmpl-12 | test_review_record.py::test_validator[tmpl-12-grown-scalars] |
| 0 | 2 ラウンド続けて阻害なしなら exit 0 | 連続 2 ラウンド | hist | test_review_record.py::test_validator[hist-two-rounds] |
| 0 | 阻害なしを収束と名乗らない | これは収束の宣言ではない | hist | test_review_record.py::test_validator[hist-not-convergence] |
| 0 | 持ち越しは実際に見たラウンドと古さを見せる | 素材 prior_decisions: round 1 の判定を流用（2 ラウンド前） | hist | test_review_record.py::test_validator[hist-carry-age] |
| 2 | 不正な記録は 1 と区別して落ちる: drop-material | 素材 'hygiene' の返答が無い | drop-material | test_review_record.py::test_validator[drop-material] |
| 2 | 不正な記録は 1 と区別して落ちる: drop-defer-reason | defer に構造的理由が無い | drop-defer-reason | test_review_record.py::test_validator[drop-defer-reason] |
| 2 | 不正な記録は 1 と区別して落ちる: drop-base | 必須の欄 'base' が無い | drop-base | test_review_record.py::test_validator[drop-base] |
| 2 | 不正な記録は 1 と区別して落ちる: drop-round | 必須の欄 'round' が無い | drop-round | test_review_record.py::test_validator[drop-round] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-base | base が違う | bad-base | test_review_record.py::test_validator[bad-base] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-round | ファイル名の番号と違う | bad-round | test_review_record.py::test_validator[bad-round] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-status | status が不正 | bad-status | test_review_record.py::test_validator[bad-status] |
| 2 | 不正な記録は 1 と区別して落ちる: clean-without-checked | 'checked' が要る | clean-without-checked | test_review_record.py::test_validator[clean-without-checked] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-label | label が不正 | bad-label | test_review_record.py::test_validator[bad-label] |
| 2 | 不正な記録は 1 と区別して落ちる: drop-key | key が無い | drop-key | test_review_record.py::test_validator[drop-key] |
| 2 | 不正な記録は 1 と区別して落ちる: drop-reviews | 必須の欄 'reviews' が無い | drop-reviews | test_review_record.py::test_validator[drop-reviews] |
| 2 | 不正な記録は 1 と区別して落ちる: drop-review-R3 | R3 の verdict が無い | drop-review-R3 | test_review_record.py::test_validator[drop-review-R3] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-review-status | R1 の status が不正 | bad-review-status | test_review_record.py::test_validator[bad-review-status] |
| 2 | 不正な記録は 1 と区別して落ちる: review-only-R2 | R1 は premise-invalid にできない | review-only-R2 | test_review_record.py::test_validator[review-only-R2] |
| 2 | 不正な記録は 1 と区別して落ちる: review-only-R34 | R1 は not_applicable にできない | review-only-R34 | test_review_record.py::test_validator[review-only-R34] |
| 2 | 不正な記録は 1 と区別して落ちる: pass-without-reason | R3 は status=pass なので 'reason' が要る | pass-without-reason | test_review_record.py::test_validator[pass-without-reason] |
| 2 | 不正な記録は 1 と区別して落ちる: carry-without-from | 'from_round' が要る | carry-without-from | test_review_record.py::test_validator[carry-without-from] |
| 2 | 不正な記録は 1 と区別して落ちる: carry-from-future | 今ラウンド（2）より前でない | carry-from-future | test_review_record.py::test_validator[carry-from-future] |
| 2 | 不正な記録は 1 と区別して落ちる: carry-from-not-applicable | 前ラウンドが not_applicable なので持ち越せない | carry-from-not-applicable | test_review_record.py::test_validator[carry-from-not-applicable] |
| 2 | 不正な記録は 1 と区別して落ちる: not-object | 記録の最上位が object でない | not-object | test_review_record.py::test_validator[not-object] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-round-type | 'round' が整数でない | bad-round-type | test_review_record.py::test_validator[bad-round-type] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-round-bool | 'round' が整数でない | bad-round-bool | test_review_record.py::test_validator[bad-round-bool] |
| 2 | 不正な記録は 1 と区別して落ちる: round-below-one | 'round' が 1 以上でない | round-below-one | test_review_record.py::test_validator[round-below-one] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-materials-type | 'materials' が object でない | bad-materials-type | test_review_record.py::test_validator[bad-materials-type] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-units-type | 'units' が配列でない | bad-units-type | test_review_record.py::test_validator[bad-units-type] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-unit-type | units[0] が object でない | bad-unit-type | test_review_record.py::test_validator[bad-unit-type] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-reviews-type | 'reviews' が object でない | bad-reviews-type | test_review_record.py::test_validator[bad-reviews-type] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-from-round-type | 'from_round' は数で書け | bad-from-round-type | test_review_record.py::test_validator[bad-from-round-type] |
| 2 | 不正な記録は 1 と区別して落ちる: bad-scalars-type | 'scalars' が object でない | bad-scalars-type | test_review_record.py::test_validator[bad-scalars-type] |
| 2 | 不正な記録は 1 と区別して落ちる: null-scalars | 'scalars' が object でない | null-scalars | test_review_record.py::test_validator[null-scalars] |
| 2 | 不正な記録は 1 と区別して落ちる: unhashable-status | 想定外の例外（TypeError） | unhashable-status | test_review_record.py::test_validator[unhashable-status] |
| 2 | 前ラウンドの key が unhashable でも 1 と区別して落ちる | 想定外の例外（TypeError） | unhashable-key | test_review_record.py::test_validator[unhashable-key] |
| 2 | 初回ラウンドに持ち越しは書けない | 今ラウンド（1）より前でない | r1-carry | test_review_record.py::test_validator[r1-carry] |
| 2 | 前ラウンドとの突合: carry-chain-broken | 持ち越しが連鎖していない | carry-chain-broken | test_review_record.py::test_validator[carry-chain-broken] |
| 2 | 前ラウンドとの突合: review-carry-chain-broken | R2 の from_round（1）が前ラウンド（2）でない | review-carry-chain-broken | test_review_record.py::test_validator[review-carry-chain-broken] |
| 2 | 前ラウンドとの突合: reopen-without-evidence | reopen_evidence が無い | reopen-without-evidence | test_review_record.py::test_validator[reopen-without-evidence] |
| 1 | 前ラウンドとの突合: reopen-with-evidence | 既受容 defer の再審。新証拠: 本番ログで上限超過のクエリを 3 件観測 | reopen-with-evidence | test_review_record.py::test_validator[reopen-with-evidence] |
| 1 | 前ラウンドとの突合: skip-PR | R3 が not_applicable だが、P-R への到達を妨げる阻害要因が記録に無い | skip-PR | test_review_record.py::test_validator[skip-PR] |
| 1 | 前ラウンドとの突合: redesign | R2 が redesign-needed | redesign | test_review_record.py::test_validator[redesign] |
| 1 | 前ラウンドとの突合: premise-invalid | 収束を宣言せずユーザーに諮れ | premise-invalid | test_review_record.py::test_validator[premise-invalid] |
| 1 | 前ラウンドとの突合: unverifiable | 収束を宣言せずユーザーに諮れ | unverifiable | test_review_record.py::test_validator[unverifiable] |
| 1 | 前ラウンドとの突合: review-not-run | R4 が not_run | review-not-run | test_review_record.py::test_validator[review-not-run] |
| 0 | 前ラウンドとの突合: defer-dropped | 台帳には残る | defer-dropped | test_review_record.py::test_validator[defer-dropped-ledger] |
| 0 | 前ラウンドとの突合: defer-dropped | [人へ] fork | defer-dropped | test_review_record.py::test_validator[defer-dropped-fork] |
| 1 | 前ラウンドとの突合: material-awaiting | 素材 'consistency' が人の起動待ち | material-awaiting | test_review_record.py::test_validator[material-awaiting] |
| 1 | 前ラウンドとの突合: material-not-run | 素材 'hygiene' が未実施 | material-not-run | test_review_record.py::test_validator[material-not-run] |
| 2 | 前ラウンドとの突合: dup-key | 突合の識別子なので 1 ラウンドに 1 つ | dup-key | test_review_record.py::test_validator[dup-key] |
| 1 | 前ラウンドとの突合: found-no-units | 素材が found なのに units が空 | found-no-units | test_review_record.py::test_validator[found-no-units] |
| 1 | 同じ [block] キーが 2 ラウンド残れば残存の印を出す | 残存——過去のラウンドにも在った | stuck | test_review_record.py::test_validator[stuck] |
| 2 | 問いの台帳: q-split-on-do-now | split の origin / depends が [block] / do-now | q-split-on-do-now | test_review_record.py::test_validator[q-split-on-do-now] |
| 2 | 問いの台帳: q-split-on-block | split の origin / depends が [block] / do-now | q-split-on-block | test_review_record.py::test_validator[q-split-on-block] |
| 2 | 問いの台帳: q-bad-kind | kind が不正 | q-bad-kind | test_review_record.py::test_validator[q-bad-kind] |
| 2 | 問いの台帳: q-bad-status | status が不正 | q-bad-status | test_review_record.py::test_validator[q-bad-status] |
| 2 | 問いの台帳: q-without-reason | 'reason' が要る | q-without-reason | test_review_record.py::test_validator[q-without-reason] |
| 2 | 問いの台帳: q-fork-one-option | options は選択肢 2 つ以上の配列 | q-fork-one-option | test_review_record.py::test_validator[q-fork-one-option] |
| 2 | 問いの台帳: q-resolved-without-resolution | 'resolution' が要る | q-resolved-without-resolution | test_review_record.py::test_validator[q-resolved-without-resolution] |
| 2 | 問いの台帳: q-origin-missing | origin が今ラウンドの units にも defer 台帳にも無い | q-origin-missing | test_review_record.py::test_validator[q-origin-missing] |
| 2 | 問いの台帳: q-awaiting-unlisted | 素材 'main_path_observation' が awaiting_human なのに問いの台帳に無い | q-awaiting-unlisted | test_review_record.py::test_validator[q-awaiting-unlisted] |
| 2 | 問いの台帳: q-awaiting-origin-clean | awaiting の origin 'hygiene' が awaiting_human でない | q-awaiting-origin-clean | test_review_record.py::test_validator[q-awaiting-origin-clean] |
| 2 | 問いの台帳: q-review-unlisted | R1 が unverifiable なのに問いの台帳に無い | q-review-unlisted | test_review_record.py::test_validator[q-review-unlisted] |
| 2 | 問いの台帳: q-premise-origin-mismatch | premise の origin R2 が premise-invalid でない | q-premise-origin-mismatch | test_review_record.py::test_validator[q-premise-origin-mismatch] |
| 2 | 問いの台帳: q-dup-key | の key が重複: x | q-dup-key | test_review_record.py::test_validator[q-dup-key] |
| 2 | 問いの台帳: q-legacy-ask-human | 人に聞く候補は questions（問いの台帳）に | q-legacy-ask-human | test_review_record.py::test_validator[q-legacy-ask-human] |
| 2 | 問いの台帳: q-not-list | 'questions' が配列でない | q-not-list | test_review_record.py::test_validator[q-not-list] |
| 2 | 問いの台帳: q-drop | 必須の欄 'questions' が無い | q-drop | test_review_record.py::test_validator[q-drop] |
| 2 | 問いの台帳: q-not-object | questions[2] が object でない | q-not-object | test_review_record.py::test_validator[q-not-object] |
| 2 | 問いの台帳: q-no-key | に key が無い（周をまたぐ突合に使う | q-no-key | test_review_record.py::test_validator[q-no-key] |
| 2 | 問いの台帳: q-empty-reason | 'reason' が空（きっかけ・根拠を書け） | q-empty-reason | test_review_record.py::test_validator[q-empty-reason] |
| 2 | 問いの台帳: q-depends-type | depends は、この答え待ちで手を止めるユニットの key の配列 | q-depends-type | test_review_record.py::test_validator[q-depends-type] |
| 2 | 問いの台帳: q-fork-options-type | options は選択肢 2 つ以上の配列 | q-fork-options-type | test_review_record.py::test_validator[q-fork-options-type] |
| 2 | 問いの台帳: q-origin-field-missing | なので origin（units の key）が要る | q-origin-field-missing | test_review_record.py::test_validator[q-origin-field-missing] |
| 2 | 問いの台帳: q-awaiting-origin-not-material | なので origin は素材名 | q-awaiting-origin-not-material | test_review_record.py::test_validator[q-awaiting-origin-not-material] |
| 2 | 問いの台帳: q-review-origin-not-r | なので origin は R1〜R4 | q-review-origin-not-r | test_review_record.py::test_validator[q-review-origin-not-r] |
| 2 | 問いの台帳: q-thrash-with-origin | なので origin / depends を持てない | q-thrash-with-origin | test_review_record.py::test_validator[q-thrash-with-origin] |
| 2 | 問いの台帳: q-thrash-with-depends | なので origin / depends を持てない | q-thrash-with-depends | test_review_record.py::test_validator[q-thrash-with-depends] |
| 2 | 問いの台帳: q-awaiting-depends-missing | depends が今ラウンドの units にも defer 台帳にも無い | q-awaiting-depends-missing | test_review_record.py::test_validator[q-awaiting-depends-missing] |
| 2 | 問いの台帳: q-fork-options-empty-item | options は選択肢 2 つ以上の配列 | q-fork-options-empty-item | test_review_record.py::test_validator[q-fork-options-empty-item] |
| 2 | 問いの台帳: q-depends-item-type | depends は、この答え待ちで手を止めるユニットの key の配列 | q-depends-item-type | test_review_record.py::test_validator[q-depends-item-type] |
| 2 | 問いの台帳: q-premise-unlisted | R2 が premise-invalid なのに問いの台帳に無い | q-premise-unlisted | test_review_record.py::test_validator[q-premise-unlisted] |
| 2 | 問いの台帳: q-review-origin-status-unverifiable | の origin R2 が unverifiable でない | q-review-origin-status-unverifiable | test_review_record.py::test_validator[q-review-origin-status-unverifiable] |
| 2 | 問いの台帳: q-no-open-via-depends | rule の origin / depends が [block] / do-now | q-no-open-via-depends | test_review_record.py::test_validator[q-no-open-via-depends] |
| 2 | 問いの台帳: q-awaiting-listed-resolved | が awaiting_human なのに問いの台帳に無い | q-awaiting-listed-resolved | test_review_record.py::test_validator[q-awaiting-listed-resolved] |
| 2 | 問いの台帳: q-unhashable-key | 想定外の例外（TypeError） | q-unhashable-key | test_review_record.py::test_validator[q-unhashable-key] |
| 2 | 保留した問いは黙って落とせない | 前ラウンドの問い（held）が今ラウンドの台帳に無い | q-dropped | test_review_record.py::test_validator[q-dropped] |
| 2 | 人へ回した問いも黙って落とせない | 前ラウンドの問い（escalate）が今ラウンドの台帳に無い | q-dropped-escalate | test_review_record.py::test_validator[q-dropped-escalate] |
| 2 | 出どころの実在検査は depends にも当たる（綴り違いが黙って無効にならない） | depends が今ラウンドの units にも defer 台帳にも無い | q-depends-missing | test_review_record.py::test_validator[q-depends-missing] |
| 1 | 決着しても出どころが開いているうちは decided で、台帳から降りない（要求を満たす） | [block] 未解消 | q-stuck-decided | test_review_record.py::test_validator[q-stuck-decided] |
| 2 | 出どころが開いたまま resolved と書けない（1 件置いて要求を永久に黙らせる形を塞ぐ） | 出どころが [block] / do-now のまま resolved | q-resolved-while-open | test_review_record.py::test_validator[q-resolved-while-open] |
| 2 | 出どころを持たない種類を置いても stuck の振り分け要求は満たされない | 2 ラウンド連続の残存＝stuck）のに問いの台帳に無い | q-stuck-other-kind | test_review_record.py::test_validator[q-stuck-other-kind] |
| 1 | R1〜R4 の人に諮る verdict も保留の問いに帰属する | 残る阻害要因は保留の問いに帰属するものだけ（1 件） | human-repeat | test_review_record.py::test_validator[human-repeat-attributed] |
| 1 | 人の起動待ちの素材も保留の問いに帰属する | （保留の問いに帰属——答えを待っている） | q-material-attribution | test_review_record.py::test_validator[q-material-attribution] |
| 2 | 出どころの実在検査は round 1 にも掛かる | origin が今ラウンドの units にも defer 台帳にも無い | q-origin-missing-round1 | test_review_record.py::test_validator[q-origin-missing-round1] |
| 1 | 前提不成立でも、問いが held のうちは短絡しない（載せた周には聞かない） | 保留の問いに帰属する阻害要因 1 件は聞くのを待て——帰属しない 1 件を先に直せ | q-premise-not-escalate | test_review_record.py::test_validator[q-premise-not-escalate] |
| 1 | premise 以外の escalate では前提不成立を出さない | 残る阻害要因は保留の問いに帰属するものだけ（1 件） | q-escalate-not-premise | test_review_record.py::test_validator[q-escalate-not-premise] |
| 2 | 同じ [block] が 3 周続けば台帳への記載を要求する | 2 ラウンド連続の残存＝stuck）のに問いの台帳に無い | q-stuck-unlisted | test_review_record.py::test_validator[q-stuck-unlisted] |
| 1 | 残る阻害が保留の問いだけなら「聞く時」を出す | 残る阻害要因は保留の問いに帰属するものだけ（1 件） | q-stuck-listed | test_review_record.py::test_validator[q-stuck-listed-ask] |
| 1 | 同じ形でも、問いが立った周には帰属せず印だけが付く（立った周には聞かない） | （今ラウンドに立った問い——再審は次の周） | q-fresh | test_review_record.py::test_validator[q-fresh] |
| 1 | ループが決めた問い（decided）の阻害要因は仕事であって、聞く時ではない | 帰属しない 1 件を先に直せ | q-resolved-is-work | test_review_record.py::test_validator[q-resolved-is-work] |
| 1 | 帰属する阻害要因の行に印が付く | （保留の問いに帰属——答えを待っている） | q-stuck-listed | test_review_record.py::test_validator[q-stuck-listed-mark] |
| 1 | 帰属しない阻害が残るうちは聞かない | 帰属しない 1 件を先に直せ | q-mixed | test_review_record.py::test_validator[q-mixed] |
| 1 | do-now の行は [block] と別の見出しで出る | [suggest] do-now 未対応 | tmpl-1 | test_review_record.py::test_validator[tmpl-1-do-now-heading] |
| 1 | depends に挙げたユニットの阻害も問いに帰属する | 残る阻害要因は保留の問いに帰属するものだけ（2 件） | q-depends | test_review_record.py::test_validator[q-depends] |
| 1 | premise の escalate は他の阻害の帰属を問わず「聞く時」 | 前提不成立が確定（escalate） | q-premise-escalate | test_review_record.py::test_validator[q-premise-escalate] |
| 2 | unit の key が R の名前と同じでも、別の域の問いはそのユニットを指したことにならない | 2 ラウンド連続の残存＝stuck）のに問いの台帳に無い: R2 | domain-separation | test_review_record.py::test_validator[domain-separation] |
| 2 | 問いが載った周に R1 を持ち越した記録は不正 | 台帳の未決の問いが前ラウンドから変わったのに R1 が carried_over | q-new-r1-carried | test_review_record.py::test_validator[q-new-r1-carried] |
| 2 | 同じ key のまま中身を総取り替えした周も、R1 を持ち越せない | 台帳の未決の問いが前ラウンドから変わったのに R1 が carried_over | q-swap-r1-carried | test_review_record.py::test_validator[q-swap-r1-carried] |
| 2 | ループが決めた問いが未決に戻った周も、R1 を持ち越せない | 台帳の未決の問いが前ラウンドから変わったのに R1 が carried_over | q-reopen-r1-carried | test_review_record.py::test_validator[q-reopen-r1-carried] |
| 1 | 同じ形でも R1 を走らせていれば通る（対照） | [block] 未解消 | q-new-r1-ran | test_review_record.py::test_validator[q-new-r1-ran] |
| 1 | 持ち越した問いだけの周は R1 も持ち越してよい（縛るのは新しく載った問い） | [block] 未解消 | q-carried-r1-carried | test_review_record.py::test_validator[q-carried-r1-carried] |
| 2 | 大小が違うだけのファイルを黙って捨てない | は記録の名前でない | name-case | test_review_record.py::test_validator[name-case] |
| 2 | 桁の異体字のファイル名も黙って受理せず、黙って捨てもしない | は記録の名前でない | name-unidigit | test_review_record.py::test_validator[name-unidigit] |
| 2 | 正規表現の軸に載らない綴りでも、最新ラウンドを黙って捨てない | は記録の名前でない | name-tail | test_review_record.py::test_validator[name-tail] |
| 1 | 退避先のディレクトリと OS の成果物では鳴らさない（対照） | 前ラウンドの記録が無い | name-ok | test_review_record.py::test_validator[name-ok] |
| 1 | 出どころで手を止めない問いだけが残る周も、台帳が黙って終わらない | 台帳に未決の問いが 1 件（うち人へ 0 件） | q-thrash-silent | test_review_record.py::test_validator[q-thrash-silent] |
| 2 | 連鎖のキーを depends に並べても stuck の振り分け要求は満たされない（見るのは origin） | 2 ラウンド連続の残存＝stuck）のに問いの台帳に無い | q-stuck-via-depends | test_review_record.py::test_validator[q-stuck-via-depends] |
| 2 | 3 周の窓は滑る（連鎖が 1 周のびると、次の組で要求が立つ） | round 4: 同じ [block] が 3 ラウンドの記録に続けて在る | stuck-window-slide | test_review_record.py::test_validator[stuck-window-slide] |
| 1 | 2 周の残存では、まだ台帳への記載を要求しない（対照） | （残存——過去のラウンドにも在った） | stuck-two-rounds | test_review_record.py::test_validator[stuck-two-rounds] |
| 1 | ループが決めた問いの出どころは、記録から消えていてよい | [block] 未解消 | q-resolved-origin-gone | test_review_record.py::test_validator[q-resolved-origin-gone] |
| 1 | ループが決めた split（decided）は、開いた [block] を指していてよい | [block] 未解消 | q-resolved-split-open | test_review_record.py::test_validator[q-resolved-split-open] |
| 2 | 出どころの実在検査は中間のラウンドにも掛かる | round 2: questions[0] の origin | q-origin-missing-mid | test_review_record.py::test_validator[q-origin-missing-mid] |
| 2 | 別レビューの記録が混ざったら、退避の案内を出して止まる | 混ざっていないか | mixed-base | test_review_record.py::test_validator[mixed-base] |
| 1 | 前ラウンドの [block] が記録から消えたら報告する（defer 側との非対称を消す） | 過去のラウンドの [block] で今ラウンドの記録に無いキー | block-dropped | test_review_record.py::test_validator[block-dropped] |
| 2 | 人に諮る verdict を持ち越すと記録の不正になる（阻害要因から消えるため） | 前ラウンドが unverifiable なので持ち越せない | carry-from-human | test_review_record.py::test_validator[carry-from-human] |
| 1 | 人に諮る verdict は、同じ値を書き直せば毎ラウンド数えられる | R1 が unverifiable（収束を宣言せずユーザーに諮れ） | human-repeat | test_review_record.py::test_validator[human-repeat-counted] |
| 2 | round-0.json を黙って捨てない | 1 から始まる番号でない | round-zero | test_review_record.py::test_validator[round-zero] |
| 2 | ゼロ詰めの別名が同じ番号に潰れるのを落とす | 同じ番号 | round-dup | test_review_record.py::test_validator[round-dup] |
| 1 | count: 0 を「値が無い」と言わない | 収束を妨げるもの | count-zero | test_review_record.py::test_validator[count-zero] |
| 2 | 空文字は欠落と分けて診断する | が空（何を見たかを書け） | checked-empty | test_review_record.py::test_validator[checked-empty] |
| 2 | 存在しないラウンド 0 からの流用を落とす（外すと素材を一度も見ずに収束できる） | from_round が 1 以上でない | from-round-zero | test_review_record.py::test_validator[from-round-zero] |
| 1 | 連鎖が 2 周ぶんなら、3 周の窓では台帳への記載を要求しない（窓の幅を測る） | （残存——過去のラウンドにも在った） | stuck-window-width | test_review_record.py::test_validator[stuck-window-width] |
| 2 | UTF-8 でない記録は「開けない」「JSON でない」と別の診断で落ちる | UTF-8 として読めない | badenc | test_review_record.py::test_validator[badenc] |
| 2 | 縮退値（false / [] / {}）で明示返答の欄を埋められない | が空（何を見たかを書け） | checked-false | test_review_record.py::test_validator[checked-false] |
| 2 | 文を要求する欄に数を書いても「埋まっている」にならない | が空（何を見たかを書け） | checked-number | test_review_record.py::test_validator[checked-number] |
| 2 | 1 ラウンド記録から落としても、台帳は全ラウンドの和なので再審を止める | reopen_evidence が無い | ledger-gap | test_review_record.py::test_validator[ledger-gap] |
| 0 | ディレクトリを渡すと全ラウンドの履歴を出す | 履歴（round 1〜3 | hist | test_review_record.py::test_validator[hist-history] |
| 0 | 台帳の問いは阻害要因にせず、人に聞く候補として出す | 問いの台帳（人に聞く候補。載せた周には聞かない | hist | test_review_record.py::test_validator[hist-question-ledger] |
| 0 | 問いの推移を履歴に出す（決めた問いは次の周から消えてよい） | r1:held(awaiting) → r2:resolved(awaiting) → r3:— | hist | test_review_record.py::test_validator[hist-question-timeline] |
| 0 | 台帳の件数の推移を出す | 問いの台帳の件数（保留・人へ・ループが決めた）: 1・0・0 → 1・0・1 → 1・1・0 | hist | test_review_record.py::test_validator[hist-question-counts] |
| 0 | 阻害要因が 0 でも、台帳に未決が残っていれば判定行がそう言う | 台帳に未決の問いが 2 件（うち人へ 1 件） | hist | test_review_record.py::test_validator[hist-open-questions] |
| 0 | 要対応の件数の推移を出す | 要対応（[block]＋do-now）の件数: 3 → 0 → 0 | hist | test_review_record.py::test_validator[hist-owed-counts] |
| 2 | 連番に穴があれば履歴を出さずに落ちる | round-2.json が無い | hist-gap | test_review_record.py::test_validator[hist-gap] |
| 0 | 直したはずのキーが戻れば履歴に印を付ける | r1:block → r2:— → r3:nit（消えて 1 回戻った） | hist-return | test_review_record.py::test_validator[hist-return] |
| 0 | 初出のキーを「戻った」と数えない（注記が付かない） | r1:— → r2:suggest/defer → r3:suggest/defer⏎ | hist | test_review_record.py::test_validator[hist-first-seen-not-returned] |
| 2 | 壊れた JSON は 1 と区別して落ちる | JSON として読めない | truncated | test_review_record.py::test_validator[truncated] |
| 2 | 記録のディレクトリでないものを渡したら 1 と区別して落ちる | ディレクトリでない | does-not-exist | test_review_record.py::test_validator[does-not-exist] |
| 2 | 読めない記録は 1 と区別して落ちる | 開けない | unreadable | test_review_record.py::test_validator[unreadable] |
| 2 | 引数なしは 1 と区別して落ちる | （終了コードだけ） | （引数なし） | test_review_record.py::test_validator[no-args] |
| 2 | 引数が多すぎる場合も 1 と区別して落ちる | （終了コードだけ） | tmpl-12 repo:templates/round-1.example.json | test_review_record.py::test_validator[too-many-args] |
| 2 | 深いネストの JSON も 1 と区別して落ちる（経路は環境で変わる） | （終了コードだけ） | deep | test_review_record.py::test_validator_in_child[deep] |
<!-- ledger:end -->

## 上位互換の証明

台本の節（tests/run.sh の review-record.py の節）が見ていたものを、この置き場が全部見ていることを 3 段で示す。

1. **行の対応**: 台本の検査 1 件ごとに行き先がある。`test_ledger_matches_script` が、台本の行と表（`review_record_cases.CASES`）を
   `ledger.Row`（終了コード・期待の文言・説明文・読む記録）の多重集合で突き合わせる（同じ説明文の行が 2 つあるので、集合にすると
   片方を落としても通る。読む記録まで見るので、期待が同じ行どうしで読む記録を入れ替えても赤になる）。行き先（台帳の「移した先」）は
   pytest が集めたテストの node id と照らし、集まっていない・ほかの行と重なる行き先があれば赤になる（表の where の誤記・id の重複）
2. **入力の一致**: [broken_records.py](broken_records.py) は壊した記録の作り方を写さず、tests/run.sh の `write_broken_records` の
   heredoc を読んで走らせる
3. **被覆の包含**: 台本の節が検証器（scripts/review-record.py・scripts/record_common.py）の中で通した行が、この置き場が通した行の
   和に含まれる。測る道具は [coverage_proof.py](coverage_proof.py)（使い方と終了コードは道具の docstring）

2 までで言えるのは「同じ引数・同じ入力で同じ検証器を走らせる」ところまでで、起こし方の違い（台本は子プロセスで `"$@" 2>&1`、
ここは `runpy` で同じプロセス）が通る行を変えないことは言えない。3 はそこを実測で埋める。

### 被覆の包含の測り方

- 台本が実際に起こした引数の集合が台帳の読み取り（`ledger.script_rows`）と違えば、道具は終了 2 で止まる。台帳の `args_of` の
  読み違いもここで出る
- **赤の腕**: `--only-new` で旧い側を回し直さずに新しい側だけを回し、`-- --deselect "test_review_record.py::test_validator[<id>]"`
  で 1 件を外す。id は台帳の表の「移した先」の列の値をそのまま渡す（node id は tests/py を根に作る。`tests/py/` を頭に付けると
  何も外れない）。何も外れなければ、道具は pytest の要約の「N deselected」を見て終了 2 で止まる。外した検査だけが通していた行が
  あれば終了 1 になる。どの 1 件で赤になるかは、旧い側の測りを取った回に決めてここに書く
- 限り: 測るのは行だけで、枝は測らない。新しい側の同じプロセスの行は 1 つの文脈（`new`）にまとまる

**結果: 包含は未実施。** 旧い側は、人が許した testslot の枠で 1 回回す（問いの台帳の held の問い）か、CI の段（下の「門と CI の段」）で
回し、結果をここに書く。

### 変異の腕（CI で撃つ手順）

人の方針は「変異は CI だけで撃つ・pytest の側の mutmut も CI に載せる」。今は、どちらの腕もこの置き場を撃つ者が居ない。

- **手書きの腕**: [tests/mutations.json](../mutations.json) で scripts/review-record.py を壊す腕は n01・n02（suite は root。expect は
  `graphloops: graphcheck`）と OA1（suite は graphloops。graphloops/tests/simulate_review.py の検査が落とす）の 3 本。どれも節の検査で
  落ちる腕ではないので、台本の節を消しても付け替えは要らない。節の検査を当てにする腕を足すなら、腕の実行器 [tests/mutate.py](../mutate.py)
  に pytest の口が要る（今は bash の台本しか回せない。[graphloops/README.md の「検査」](../../graphloops/README.md#検査) の
  「置き場の方針」）
- **mutmut**: この置き場のテストのままでは、pytest の側の mutmut は review-record.py の変異を拾えない。mutmut の trampoline は、
  変異の名前の module と、呼ばれた関数の `__module__` を突き合わせ、違えば元の関数を呼ぶ（mutmut の
  [src/mutmut/mutation/trampoline.py](https://github.com/boxed/mutmut/blob/main/src/mutmut/mutation/trampoline.py)）。検証器は
  `runpy.run_path(run_name="__main__")` で（子プロセスでも `__main__` として）起こすので、関数の `__module__` は `__main__` になり、
  変異は効かず、どのテストにも結び付かない。載せる job を作る run が選ぶ道は次の 2 つ:
  - 本体を import できるモジュールへ移し、scripts/review-record.py を薄い殻にする（scripts/ を触る）
  - テストの側で、検証器を mutmut が付ける module の名前のまま読み込み、`__main__` の段の境界（想定外の例外を 2 に倒す）は子プロセスの
    検査に任せる
- **既存の記述とのずれ**（どれも tests/py の外なので、この run では直していない）: graphloops/README.md の「検査」節・tests/mutate.py の
  docstring の「mutmut との受け持ち」・.github/workflows/mutation.yml の冒頭の注記は、どれも「mutmut は手元で撃ち CI では回さない。
  受け持ちは graphloops/engine/schema.py」と書いている。人の方針とも、ここに足す 2 本目の対象とも食い違う。直すのは、CI の job を
  足す run か、下の fork が「tests/py の外を触ってよい」と答えた周

### 門と CI の段

この置き場を回す門は、まだ無い。[.github/workflows/test.yml](../../.github/workflows/test.yml) の pytest の job と
[.review-checks.json](../../.review-checks.json) は graphloops/tests/py だけを回す。だから台帳の突合（`test_ledger_matches_script`）も、
手で `python3 -m pytest tests/py` を回したときにしか赤にならない。門に載せる（test.yml の pytest の job に段を、.review-checks.json に項を足す。
fence は 1 回の起動に 1 つの置き場しか載せないので別の起動）には tests/py の外を触る。それをこの run で行うかは、問いの台帳の fork
（新しい置き場を門に載せるために tests/py の外を触ってよいか）の答え待ち。**台本の節を消す run の前提は、この置き場が門に載っていること。**

### 台本の側を消す run でやること

- ledger.py・coverage_proof.py と、それを見る検査（`test_ledger_*`・`test_coverage_proof_*`）を同じ変更で消す
- **生成の正本の向きを逆にする。** 今は壊した記録の作り方の正本が台本の `write_broken_records` に在り、broken_records.py がそれを読む。
  台本の review-record.py の節を消しても、research-record.py・doctor-record.py の節が同じ記録を使うので、生成は残る。その run
  （か、fork が「tests/py の外を触ってよい」と答えた周）で、heredoc の本文を broken_records.py へ移し、台本の `write_broken_records` が
  `python3 tests/py/broken_records.py <ROOT> <WORK>` を起こす形にする。broken_records.py の関数の形の検め（HEAD・TAIL）も、そこで消える
- この置き場の件数の定数（conftest.py の `EXPECTED_ITEMS`）と台本の件数の定数（`EXPECTED_CHECKS`）を、消した分だけ直す
