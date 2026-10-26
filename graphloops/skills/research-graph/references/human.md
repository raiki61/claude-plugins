# research-graph の人に聞くターン・人が止める・子の残り

3. **人に聞くターン**。`next` が `awaiting_human` を返したら、`ask` の中身を依頼者に見せて答えをもらい、返す:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" answer --text <continue|stop|escalate> --note "<依頼者の答えの本文>" --dir <DIR>
   ```

   **聞き方**: 質問のツール（選択肢を並べて選ばせる型）を使うな。依頼者はループの間ずっと別の作業をしていて、答える時点で文脈を持っていない。選択肢だけ並んだ問いは初見では決められない。散文で、次を冒頭にまとめて出せ: ①何のループが・何を調べていて・どこで止まったか ②なぜ止まったか（きっかけの実物——どの主張・どの判定か）③答えの候補ごとに何が起きるか ④あなたの推奨と根拠（人でないと決められない事項では推奨を書くな）。内部の語彙（ノードの名前・安定キー・stuck 等の種別名）は使うなら初出で中身から言え。答えは自由な文で受け、`answer` の語に写すのはあなたの仕事である: `continue`＝次の周へ進む、`stop`＝止める、`escalate`＝厚さの段を最上段に上げて次の周へ進む（周の途中の問いで使えるのは `continue` と `stop` だけ）。

   **人が途中で止める**（人に聞いていない時点でも）: 依頼者が「止めて」と言ったら、理由を添えて止める——止めた事実と理由は盤面の `stop` と記録の `process.halted` に残り、次の `next` は graph が宣言する後始末のノード（最上位の `stop.node` の下流＝報告のノード）だけを出す。止めた周に走らなかったノードは止めた印（`process.stopped_nodes`。省いた機構 `process.skipped` とは別）になり、engine が起動中の役の子は木ごと止まる（Agent・任せ先で起動した試行は engine が持たないので、`loop.py stop` の出力の `handed_not_stopped` が挙げた試行を回す側が止める）。今の止め方（人に聞いているターンの `answer --text stop`・init の `--stop-after-round N`・`next` を打たずに置いて盤面から再開する）はそのまま使える。`run` の回し手は SIGTERM で一時停止する（起動済みの役を待ち、新しい役を起動しない。pid は `run` の出力と盤面の置き場の `runner.json`）。init の版の graph に `stop` の宣言が無い run は、報告のノードを出さずに止まる（`halted` の `by: stop`。記録の検証は `loop.py finalize`）:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" stop --reason "<依頼者の止める理由>" --dir <DIR>
   ```

   **run の子の残りを見る・止める**: 役の返答を engine が受け取った（受け付けた）後に残った子（止め切れなかった木・`launch` が先に死んだ試行の子）は、`loop.py children --dir <DIR>` が盤面の印から一覧し（信号は送らない）、`--stop --reason "<理由>"` で木ごと止める。ps の文字列でプロセスを探して止めるな（同じ機械の別の run に当たる）。既定で止めるのは `launch` が居なくなった後の止め残しだけで、いま走っている試行の子と受け付けの前の試行（instance。同じノードの 1 回分の起動）の子は `--include-running` を付けたときだけ止まる（受け付けの前の試行は、起動し直す `loop.py relaunch`・`stop` で止める）。印を持たない子（engine が起動していない物）はこの口に映らない。外の土台（engine を子として起動し、取り消すときに SIGTERM の後で SIGKILL を送る物）の下で回すなら、止める猶予（既定 5 秒。環境変数 GL_KILL_GRACE）をその土台の取り消しの猶予より十分短くせよ——同じか長いと、engine が孫を止め終える前に外から消され、孫が残る。短くするのは必要だが足りない（猶予は待つ分だけで、止め終えるまでの全体の時間は、止める木の本数と、木ごとのプロセス一覧の取得〔ps〕の時間にも伸びる。全体が外の土台の猶予に収まる値の保証は無いので、猶予は外の猶予より短い範囲で、できるだけ短くする）。猶予の値を環境変数で渡す場所と、猶予の上限・下限の決め方は [README の「外の土台の下で回すとき」](../../../README.md#外の土台の下で回すとき)。
