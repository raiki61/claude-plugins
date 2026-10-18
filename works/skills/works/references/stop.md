# works: 止め方と続け方

run を止める・取り消す・続ける時と、止めた run の報告を組む時に読む。命令の頭の `<works の置き場>` は、SKILL.md の命令の置き場（入れたプラグインの置き場の絶対パス）に読み替えて打つ。

止め方は 1 つで、打つのは SKILL.md の「命令」の `stop` の行。

- 関所で待っている run には `respond … stop` を、走っている run には止め札（中で `sh "<works の置き場>/dev/stop.sh" <run-id> "<理由>"` を、利用の家を埋めて打つ）を置く。止め札では、走っている AI の節は最後まで走り、次の境の節で止まる。どちらも報告は出る。
- すぐ止めたい時だけ、`show` が出した「取り消す」の行（`cancel <run-id>`）を使う（報告の節まで届かない。下の report.sh で組む）。持ち主が消えた run には出ない（Archon の cancel は答えない持ち主の run を止められない）。代わりに出る `abandon` の行で記録を閉じる（cancelled になれば `use.sh` の show・wait が差分を書いて片付ける）。
- 続ける: 殻が出した「続ける」の行（`resume <run-id>`）で、済んだ節の続きから回る。Archon が受ける failed か paused の run にだけ出る（走っている run・持ち主が消えた run には出ない）。
- 節が落ちた run（ブロックの中の出し直しが上限（3 回）を超えたときを含む）でも報告の節は走る。受け止めると宣言した段（`[optional]`）の落ちは、線の終わりまで届いた run では結末を `interrupted` にせず、冒頭 3 に「落ちたが、線が宣言のとおり受け止めた節」の行で並び、冒頭 1 の残りと次の run の依頼に「確かめていない（再実行の要あり）」と載る（Archon の run の状態は失敗のまま残りうる）。それ以外の落ちは結末 `interrupted` の `report.md` と `next-request.json` が盤面に残り、冒頭 3 に落ちた節とその誤りの文が出る。start で落ちた run は盤面が無く、報告も無い。
- 取り消し・abandon で止めた run は報告の節まで届かない。対象の根で、止め札と同じ `WORKS_DEV_HOME=…` を前に付けて `sh "<works の置き場>/dev/report.sh" <run-id>` を打つと、盤面から報告を組む（結末 `interrupted`）。
