# 壊れたら機械が知らせる標準（時間や外の変化で、気づかないまま壊れる所を作らない）

時間が経つと壊れる所や、外の物の変化で壊れる所を、どう作らずにおくか。壊れたら、誰に・どこへ機械が知らせるか。
外の物とは、Claude Code・herdr・gh・git の版、会話の記録の置き場、設定、会社の形（`.claude/company.toml`）などを指す。
読むのは、プラグインのコード（Python・シェル・フック）・CI・ルートの `scripts/` を書く・直す各担当。

対象は [README](README.md) の「対象」の 6 つのプラグイン（attention・convergence-loops・gates・graphloops・tiers・works-dispatch）と、ルートの `scripts/`・`tests/`・CI（`.github/workflows/`）。
[機械が読む値の受け渡しの標準](machine-readable-values.md)は、値の渡し方と読み方を決める。この標準はその続きで、読み方が正しくても時間や外の変化で静かに壊れる物を扱う。

急ぐ物（今壊れている物）: 下の「なぜ要るか」の例のうち、最後の 1 件を除く 5 件。最後の 1 件は、壊れる日が近い物。各担当への頼みは [README](README.md) の台帳の 4 回目に並べた。

## なぜ要るか

2026-10-19 の洗い出しで、41 件見つけた（うち今壊れている物は 12 件ほど）。洗い出しは、標準の担当が持ち主の頼み（受付 20261018-213441-364fd0）を受け、読み取り専用のサブエージェント 4 本に、コードと手元の実物（ログ・控え・CI の記録）を読ませた物。
持ち主の言葉は「少しづつ気づかない間に壊れていってる倒壊ポイントがないかどうかも見ておいて」。
前の日にも、main の CI が 10-16 から 1 回も緑にならないまま続いた。部署の順番待ちも半日止まっていた。どちらも、別の用事で見た人が気づくまで、誰にも知らせが来なかった。

例（どれも 2026-10-19 に実物で確かめた）:

- main の CI の直近 100 回は、成功 0・取り消し 56・失敗 42。赤の知らせは GitHub から push した人（全部の部署が同じ GitHub のアカウント）のメールに行くだけで、直す担当の点検の受付には届かない。週 1 回の変異テストの workflow は、作ってから 3 回とも赤。各 job に `continue-on-error: true` が付いていて、外からは緑に見える。
- gates の初見読みのゲートは、読み手のモデルが答えの行の頭に `- ` を付けると「読み手が読めなかった」と記録する。指摘の中身は捨てられる。10-17 から 12 回起きた（`docs.log` の reader-down の行）。モデルの版や書き方が変わると起きる。
- graphloops は、エンジンの失敗を `intake.jsonl` に書くが、読む所が無い。3 つのアカウントに 68 行が溜まり、エンジンの不具合（`ValueError`・`SystemExit`）が誰にも渡っていない。
- graphloops の試験結果の控え（`checks-cache`）は、27 回のうち 1 回も使い回されていない。控えの照合の鍵に、会話ごとに変わる環境変数（`HERDR_PANE_ID` など）が入るため。外れは普段の動きと見分けが付かない。
- attention の `/reflect` は、既定の 1 週間の GitHub の動きを読むはずが、取れるのは直近の約 1 日分。GitHub の出来事の API は 300 件までで、部署の push が多いため。人の打った頼みも、Claude Code が足した新しい種類（`suggestion_accepted`）を数えずに落とす。
- herdr のタブのバーは、Claude Code が消す印（`.orphaned_at`）を付けた古い works-dispatch（0.1.3）の場所を指したまま動いている。消されると、使用枠の控えを定期に取り直す唯一の仕組みが止まる。部署を起動するアカウントは、その控えの古い数で選ばれ続ける。

## 決まり

1. **ログに書くだけは知らせではない。知らせは、直す担当の受付か、人が毎回見る所に届ける。**
   - 直す担当が決まる物は、その部署へ works-dispatch の `--ask` で頼む（受付に入り、順番待ちに積まれる）。同じ件の頼みが開いていれば足さない。
   - 担当の決まらない物・人の判断が要る物は、窓口が毎回見る `--todo` か `--tree` に 1 行の注記で出す。
   - ログ・`probe.log`・`*.jsonl` に書いただけの失敗は、知らせていない物として数える（読む所が無いログは、無いのと同じ）。
   - 知らせるのは、受けた担当が手を打てる物だけにする（[Google SRE の Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/)「Every page should be actionable.」）。
2. **定期に起きるはずの物と、溜まる物は、年齢で見る。**
   - 定期に回る物（変異テストの workflow・使用枠の取り直し・`--due` の受け持ちなど）は、最後に済んだ時刻を残す。それが決めた間隔を超えて古ければ知らせる。来るはずの知らせが来ないことも失敗として扱う（[Healthchecks.io](https://healthchecks.io/docs/)「It raises an alert as soon as a ping does not arrive on time.」）。
   - 順番待ち・受付・保留の一覧は、件数でなく一番古い物の年齢を見る（[Amazon SQS の ApproximateAgeOfOldestMessage](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-available-cloudwatch-metrics.html)「The age of the oldest unprocessed message in the queue.」）。
   - 控え（キャッシュ）は作った時刻を持つ。使う側は、決めた年齢より古い控えを使わずに知らせる。
   - 定期の起動を、ほかの動き（頼みや main へ入れること）に乗せるときは、その動きが止まると定期の物も止まることを書いておく。
3. **外の形に頼る所は、実物から採った見本で試験し、知らない値を起動時に知らせる。**
   - 外のツールの出力・会話の記録の行・フックの入力・設定のキーに頼る所は、手で書いた想像の形でなく、実物から採った見本（fixture）で試験する。読んだ値のうち使うフィールドが今も在るかを確かめる、契約の試験にする（[Martin Fowler の ContractTest](https://martinfowler.com/bliki/ContractTest.html)「These check that all the calls against your test doubles return the same results as a call to the external service would.」）。
   - 種類・状態の列挙を外から受ける所は、知らない値をほかの値に混ぜずに数えて出す（例: `promptSource` の `suggestion_accepted`、`claude agents --json` の状態の `done`）。
   - 起動時に安く確かめられる物（指す場所が在るか、入っている版か、要るフィールドが在るか）は、起動時の自己点検で確かめ、合わなければその場で止まるか知らせる（[Kubernetes の Liveness, Readiness, and Startup Probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/)「liveness probes could catch a deadlock, where an application is running, but unable to make progress」）。
4. **入っている版とずれた物を見つける。**
   - 動いている会話・設定・フックが、入っている版と違う版のプラグインの場所を指していたら知らせる。版の場所を選ぶときは、フォルダの名前の大小でなく `installed_plugins.json` の `installPath` を読み、`.orphaned_at` の付いた場所を使わない。
5. **足し続ける物は、上限か片付けの持ち主を決める。**
   - ログ・控え・残した一時フォルダ・台帳のように足し続ける物は、上限（大きさか年齢）を決めて片付けるか、片付ける担当を決める。上限を超えたら `--tree` に出す。
6. **CI の結果は、直す担当に届ける。**
   - main の CI の赤は、点検の受付に届ける（決まり 1）。GitHub のメールは push した人に行くだけなので、届いたとは数えない（[GitHub の Notifications for workflow runs](https://docs.github.com/en/actions/monitoring-and-troubleshooting-workflows/notifications-for-workflow-runs)）。
   - 定期の workflow は決まり 2 の年齢で見る。GitHub は、動きの無いリポジトリの定期の workflow を 60 日で止める（[Events that trigger workflows の schedule](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows)「scheduled workflows are automatically disabled when no repository activity has occurred in 60 days」）。
   - `continue-on-error: true` で job を緑に見せるときは、まとめの job が赤を拾う作りにする。
   - 文書が「回す」と書いた workflow が 1 回も回っていなければ知らせる。

## 守らせ方

- 決まり 1 の知らせの口は、works-dispatch の `--ask`・`--todo`・`--tree` を使う。新しい通知の仕組みは作らない。
- main の CI の赤を点検の受付に届ける物は、点検に頼んだ（台帳の 4 回目）。main へ入れるたびに works-dispatch が回す後の処理（会社の形の `[[land.after]]`）で、最新の済んだ run を見る形を案にした。持ち主は定期の起動（cron）を置かないと決めている（`.claude/company.toml` の標準の注）。そのため、main へ入れる動きに乗せる。
- 決まり 2〜5 は、見つけた物ごとに各担当へ頼んだ。全体を数で守る検査は、今は作らない。どの作りが年齢を見ていないかは、コードの形から機械で拾えないため。

## 直さないと決めた物

- main へ入れるゲートで試験を回すこと。持ち主は、CI を待たずに main へ入れ、赤は点検が後で戻すと決めている（2026-10-16。ルートの CLAUDE.md の「判断の線」）。手元の重い試験もやめると決めている（2026-10-06）。その代わり、赤が点検に届く口を作る（決まり 6）。
- GitHub の Actions の Node 20 の警告。GitHub が既に Node 24 で動かしていて、今は何も壊れていない。次に workflow を触るときに版を上げる。
- 前の洗い出しの頼み（受付 f10955・4394cb・72ff3f・e3915a・9cdb7f）と、受付 b0df65・f0a028 が触る所。重ねないため、この標準の頼みからは外した。
- works と works-factory（誰の受け持ちでもない）。
