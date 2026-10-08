<!-- coldwrite:skip 内部の設計書。語は「目的と語」の節と works/README.md で定義 -->
# 返答の契約: 節の返答を返答の道具に任せず、本文で受けて確かめ、同じ会話で出し直させる

状態: 入れた（`.shared/core/replycontract.py`・包みの旗 `text-reply`・局所レビューの役に旗）。残りは本物の run での確かめ（6 節）。

## 平たく言うと（3 行）

- Claude の節は、返答を「返答の道具」に書く決まりで起きていた。下請け（fork で走る `/code-review`）もその道具を引き継ぎ、所見を親に返さずに道具へ書いて終わっていた（0.2.46 で記録から拾い戻す回り道を入れた）。
- 旗 `text-reply` を持つ節は、包み（claude-adapter）が返答の道具を渡さず、「最後に JSON を本文で出せ」と言い、受け取った本文を包みが型で確かめる。合わなければ同じ会話に理由を返して出し直させる（2 回まで）。合えば Archon に渡す形に包みが書き換える。
- 今の旗は局所レビューの役だけ。拾い戻しの回り道は、本物の run で確かめるまで外さずに残す。

## 目的と語

持ち主の承認（2026-10-08、「Y」）: 本流の review-graph の返答の受け方（`claude -p --output-format json` を `--json-schema` なしで起こし、返った後に検査し、拒めば同じ会話に理由を返して頼み直す）を、works の包みに入れる。

語:

- 返答の道具: Claude Code が schema を受けた時に足す道具 StructuredOutput
- 返答の契約: 本文で返させ、受けた後に型を確かめ、合わなければ同じ会話で出し直させる受け方（本流 `graphloops/engine/role_run.run_role`）
- 決め: 包みが result ごとに下す判断（accepted・reasked・gave_up・error・native）

## 1. 事実（v0.11.1 の Archon・SDK 0.3.282・Claude Code 2.1.294 の読み）

1. Archon は節の `output_format` を SDK の `outputFormat` にする（`dag-executor.ts` ~1809、`providers/claude/provider.ts` ~715-720）
2. SDK は schema を argv の `--json-schema` と、stdin の initialize の `jsonSchema` の**両方**で渡す（バンドルの transport の argv の組みと、Query（y_t）の initialize の形）。Claude Code は argv に schema が無いと initialize の schema で返答の道具を足す（2.1.294 の「Init JSON schema」）。だから argv だけ外しても道具は残る
3. Archon の provider は result の `structured_output` をそのまま節の出力に取り（`provider.ts` ~1292）、ajv で確かめ直す（`structured-output.ts` の `validateStructuredOutput`）。Claude は型を強いる provider と数えて出し直さず（`dag-executor.ts` ~2289-2296 の `maxReasks` が 0）、`structured_output` が無ければ節を `output_contract` で落とす（~3054）
4. Archon の指示文は文字列なので、SDK は 1 手の問い合わせと数え、**最初の result を見るまで stdin を閉じない**（`isSingleUserTurn`）。包みが result を持っている間、子の stdin に行を足せる。子（stream-json の stdin）は次の user の行を次の手として同じ会話・同じ子で処理する
5. 写す result の `total_cost_usd`・`modelUsage` は子の全部の手の累計（同じ子なので）。Archon の続きの起動（輪の 2 周目の `--resume`）は result の `session_id` を継ぐので、出し直しの手も同じ会話に積まれている

## 2. 決め

1. **旗は印の語に足す**（`node_marker.FLAGS`・`adapter.FLAGS` の `text-reply`）。ほかの包みの旗と同じ所で節ごとに選ぶ。YAML の `output_format` は今のまま（Archon が節の型を知る口で、`archon validate` も通る）
2. **schema は両方から外す**: argv の `--json-schema` は plan で外し（`Plan.reply` に持つ）、initialize の `jsonSchema` は stdin の中継で外す（`replycontract.strip_init_schema`。ほかの行はそのままのバイト）
3. **返答の形は system prompt で渡す**: 差し込みの表の行 `text_reply`（required）。塊は schema（一番上の印の `description` を外した物）と決まりの文で、同じ schema から同じ字（prompt のキャッシュを切らない）。下請けの答えはこの形に合わせさせず、最上位の会話の最後の返答だけに掛かると書く
4. **読み方と検査は本流に揃える**: 本文の読みは本流 `commands.parse_output` と同じ 3 候補の順。検査は写しの engine の型検査（`engine/schema.validate_schema`）。この検査が読まない語は Archon の ajv だけが見るので、旗の節の schema は読む語だけで書く（試験 `test_adapter_reply.PackCase` が縛る）
5. **出し直しは同じ子で**: 合わない result は写さず、子の stdin に理由の user の行（SDK の文字列の指示文と同じ形）を足す。上限は本流 graph の `resume_on_reject` と同じ 2。時間の上限は足さない。`--resume` の新しい子にしない（SDK が渡した hook・sandbox・設定をそのまま使え、木の止め方も 1 つで済む）
6. **使い切ったら Archon に任せる**: 最後の result を写し、JSON として読めた値は `structured_output` に置く。Archon の ajv が拒めば節が落ちる（黙って通さない）。包みの検査が Archon より厳しい所（`minLength` を空白を除いて数える）で誤って拒んでも、最後は Archon が決める
7. **誤りの result と、返答の道具で返った result は触らない**: subtype が success でない・`is_error` の result はそのまま写す（起こし直しは Archon の物）。`structured_output` を既に持つ result は schema を外し損ねた形で、そのまま写して記録に `native` と残す（canary の (j) が no にする）
8. **子の stdin は口（`adapter.InGate`）で書く**: SDK の行と理由の行を 1 行ずつ書き（行の途中に割り込まない）、SDK の stdin が先に終わっても決めが出るまで閉じない
9. **費用**: 持った result は費用の見せ直し（20）に渡さず、記録も書かない。写す result の累計は子の全部の手の累計なので、Archon の引き算はこの起動の費用の全部になる（試験 `test_spend_counts_all_turns_once`）
10. **stdin・stdout が stream-json でない起動は起こさない**（同じ会話に出し直させられない。fail closed）

## 3. 0.2.46 の拾い戻しを残すか

残す。旗の起動では fork に返答の道具が無いので、フック（`record-output.py`）は起きず、`diverted.recover` は戻す物を持たない。残す理由は 3 つ:

1. 本物の run で、返答の道具を外した fork の `/code-review` が所見を本文で返し、役がそれを `items` に写すことはまだ確かめていない。確かめるまで外さない（持ち主の意向: 大きく鳴る予備として残す）
2. 包みを外した run（`WORKS_DEV_ADAPTER=0` など）と、schema を外し損ねた起動では、今までの形がそのまま起きる。そこでは拾い戻しが今どおり効く
3. 旗の起動でも `/code-review` の行が空なら、今どおり「見ていない」と書く。本文で返った 0 件と、届かなかった物を見分けられないので、黙って「所見なし」に数えない側に倒す（報告の「未確認のレンズ」に出る。本物の run で確かめた後に、旗の起動の空の行の扱いを決め直す）

役の指示（`material.LENS_FORK_NOTE`）は両方の形に合わせた: 本文で返ったら `items` に写せ、『Skill execution completed』だけなら起こし直さず空で返せ。

## 4. 旗を付ける節

今は局所レビューの役（`works-node: local-review no-post no-tree-write text-reply`）だけ。fork で走る skill を起こすと確かめたのはこの節だけだから。Agent の道具を持つ役（修正役・判定の裏取り・事前審査）と Skill を持つ役（TDD・手直し）の下請けが返答の道具に書くかは、今の記録のフック（`outputs.jsonl`。旗の無い節でも下請けの呼び出しを残す）で次の run から見える。書いた跡が出たら、その節に旗を足す。

## 5. 試験

`tests/test_adapter_reply.py`（fast）: 印の旗・plan（schema を外す・system prompt の塊・stream-json でなければ拒む）・initialize の schema の外し・本文の読みと検査・決め（合う・出し直し・上限・誤り・native・書けない）・包みを子で起こして偽の claude（stream-json）で、1 回目の誤りから同じ子で 2 回目に合う形・費用・上限・旗の無い起動。`tests/test_canary.py` の (h)・(j)。`tests/test_diverted.py` の役の指示。

## 6. canary で確かめること

1. 局所レビューの起動の記録の `fence.text_reply` が在り、包みの家の `replies/<cwd の hash>.jsonl` に決めが残る（`dev/canary_check.py` の (j)）
2. 子が返答の道具を持たない: `outputs.jsonl` にその会話の行が無く、決めに `native` が無い
3. `/code-review` の所見が本文で返り、役が行の `items` に写す（局所レビューの控えの `unseen` が出ない。(h)）
4. Archon の節の費用が出し直しの手を含む（Archon の `node_completed` の費用と、会話の記録の累計）。写した result の累計が子の全部の手の累計であることは偽の claude でしか確かめていない
5. 出し直しが起きた時、Archon の `structured_output` が 2 回目の返答になり、輪の 2 周目の `--resume` が同じ会話を継ぐ
