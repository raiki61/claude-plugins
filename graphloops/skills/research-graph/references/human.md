# research-graph の人に聞く番・人が止める・子の残り

3. **人に聞く番**。`next` が `awaiting_human` を返したら、`ask` の中身を依頼者に見せて答えをもらい、返す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" answer --text <continue|stop|escalate> --note "<依頼者の答えの本文>" --dir <DIR>
   ```

   **聞き方**: 質問の道具（選択肢を並べて選ばせる型）を使うな。依頼者はループの間ずっと別の作業をしていて、答える時点で文脈を持っていない。選択肢だけ並んだ問いは初見では決められない。散文で、次を冒頭にまとめて出せ: ①何のループが・何を調べていて・どこで止まったか ②なぜ止まったか（きっかけの実物——どの主張・どの判定か）③答えの候補ごとに何が起きるか ④あなたの推奨と根拠（人でないと決められない事項では推奨を書くな）。内部の語彙（節の名前・安定キー・stuck 等の種別名）は使うなら初出で中身から言え。答えは自由な文で受け、`answer` の語に写すのはあなたの仕事である。

   **人が途中で止める**（人に聞いていない時点でも）: 依頼者が「止めて」と言ったら、理由を添えて止める——止めた事実と理由は盤面の `stop` と記録の `process.halted` に残り、次の `next` は graph が宣言する後始末の節（最上位の `stop.node` の下流＝報告の節）だけを出す。止めた周に走らなかった節は止めた印（`process.stopped_nodes`。省いた機構 `process.skipped` とは別）になり、engine が起こし中の役の子は木ごと止まる（Agent・任せ先で起こした試行は engine が持たないので、出力が名指しした物を回す側が止める）。今の止め方（人に聞いている番の `answer --text stop`・init の `--stop-after-round N`・`next` を打たずに置いて盤面から再開する）はそのまま使える。`run` の回し手は SIGTERM で一時停止する（起こし済みの役を待ち、新しい役を起こさない。pid は `run` の出力と盤面の置き場の `runner.json`）。init の版の graph に `stop` の宣言が無い run は、報告の節を出さずに止まる（`halted` の `by: stop`。記録の検証は `loop.py finalize`）:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" stop --reason "<依頼者の止める理由>" --dir <DIR>
   ```

   **run の子の残りを見る・止める**: 受け付けの後に残った子（止め切れなかった木・`launch` が先に死んだ試行の子）は、`loop.py children --dir <DIR>` が盤面の印から一覧し（信号は送らない）、`--stop --reason "<理由>"` で木ごと止める。ps の文字列でプロセスを探して止めるな（同じ機械の別の run に当たる）。既定で止めるのは `launch` が居なくなった後の止め残しだけで、いま走っている試行の子と受け付けの前の instance の子は `--include-running` を付けたときだけ止まる（受け付けの前の試行は relaunch・stop で止める）。印を持たない子（engine が起こしていない物）はこの口に映らない。外の土台（engine を子として起こし、取り消すときに SIGTERM の後で SIGKILL を送る物）の下で回すなら、止める猶予（既定 5 秒。環境変数 GL_KILL_GRACE）をその土台の取り消しの猶予より十分短くせよ——同じか長いと、engine が孫を止め終える前に外から消され、孫が残る。短くするのは必要だが足りない（止める木の本数と数え上げの時間にも伸びる）。立てる場所と上限・下限は [README の「Running under an external harness」](../../../README.md#running-under-an-external-harness)。
