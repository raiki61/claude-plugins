# research-graph のループの外へ出る道（開いた問い・段の引き上げ・省く節）と終わり

4. **ループの外へ出る道**。`p0.claims` の返答に「開いた問い」（地図がまだ無い・選択肢の洗い出しが要る）があれば、`done` がその旨を返す。それは閉じた主張の検証では解けないので、このループの外で deep-research に委ね、持ち帰った事実主張を次の周に入れる:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" add --file <claims.json> --reason "deep-research の持ち帰り" --dir <DIR>
   ```

   相違が結論の芯に刺さった・stuck が出たら段を上げる（義務。下げる道は無い）: `loop.py thicken --to <段> --reason "<理由>" --dir <DIR>`。optional の節を省くときは `loop.py skip --node <id> --reason "<理由>" --dir <DIR>`（報告の「省略した機構」に載る）。

5. **終わり**。最後の節 `report` の前に engine が記録を仕上げて検証器を回す。通らなければ `report` は出ない（record.json と trace.jsonl を見て直す。手当ては `loop.py patch`——痕跡が残る最終手段）。`report` の本文は盤面の置き場の `report.md` に保存される。それを依頼者の言語でそのまま出せ。`reflect` の提案（グラフ・プロンプト・engine・検証器のどこを直すべきか）は run の中で書き換えず、依頼者に見せる。
