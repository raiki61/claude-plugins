# research-graph のループの外へ出る道（開いた問い・段の引き上げ・省くノード）と終わり

4. **ループの外へ出る道**。ノード `p0.claims`（主張を洗い出す役）の返答に「開いた問い」（地図がまだ無い・選択肢の洗い出しが要る）があれば、`done` がその旨を返す。それは閉じた主張（一次情報で確証か相違かを決められる、範囲の決まった主張）の検証では解けないので、このループの外で deep-research（広く調べて地図や選択肢を洗い出す別の調査。このプラグインは走らせない）に委ね、持ち帰った事実主張を次の周に入れる:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" add --file <claims.json> --reason "deep-research の持ち帰り" --dir <DIR>
   ```

   相違が結論の芯に刺さった・stuck（再照合した相違がまた相違になり、前提側の誤りが疑われる状態）が出たら、厚さの段を上げる（義務。下げる道は無い。`<段>` は `light`・`standard`・`heavy` のどれか。graph の `thickness.tiers`）: `loop.py thicken --to <段> --reason "<理由>" --dir <DIR>`。optional のノードを省くときは `loop.py skip --node <id> --reason "<理由>" --dir <DIR>`（報告の「省略した機構」に載る）。

5. **終わり**。最後のノード `report` の前に engine が記録を仕上げて検証器を回す。通らなければ `report` は出ない（record.json と trace.jsonl を見て直す。手当ては `loop.py patch`——痕跡が残る最終手段）。`report` の本文は盤面の置き場の `report.md` に保存される。それを依頼者の言語でそのまま出せ。`reflect` の提案（グラフ・プロンプト・engine・検証器のどこを直すべきか）は run の中で書き換えず、依頼者に見せる。
