# works: 止め方と続け方

/works のスキルの本文（このフォルダの 1 つ上の SKILL.md）から指される別ファイルで、run を止める・取り消す・続ける時と、止めた run の報告を組む時に読む。関所・止め札・節・盤面・利用の家などの語は SKILL.md の「語」に在る。命令の頭の `<works の置き場>` は、入れた works のプラグインの置き場の絶対パスで、SKILL.md の「命令」の行の `sh "…/dev/use.sh"` の `/dev/` より前の字をそのまま写す。

この別ファイルで決めるのは、どの命令で止める・続けるかと、止めた run の報告をどう組むか。run が関所で待っているか・走っているか・持ち主が消えたかは、`show` の状態の行と `持ち主:` の行で見分ける。

止め方は 1 つで、打つのは SKILL.md の「命令」の `stop` の行（`sh "<works の置き場>/dev/use.sh" stop <対象リポジトリ> <run-id> "<理由>"`）。run id と、run が関所で待っているか走っているかは `show` が出す。

- `use.sh stop` は run の状態を見て止め方を選ぶ。関所で待っている run には関所に `stop` と答え（Archon の `workflow respond <run-id> stop "<理由>"`）、走っている run には止め札を置く（`use.sh stop` が中で `sh "<works の置き場>/dev/stop.sh" <run-id> "<理由>"` を、利用の家を `WORKS_DEV_HOME` に埋めて打つ）。止め札では、走っている AI の節は最後まで走り、その次の境の節（止め札を見る節）で止まる。どちらも報告は出る。
- すぐ止めたい時だけ、`show` が出した「取り消す」の行（`cancel <run-id>`）を使う（報告の節まで届かない。下の report.sh で組む）。持ち主が消えた run（`show` の `持ち主:` の行が「消えた」と言う run。run を回していた process が Mac の停止などで居なくなった物）には出ない（Archon の cancel は答えない持ち主の run を止められない）。代わりに出る `abandon` の行で記録を閉じる（cancelled になれば `use.sh` の show・wait が差分を書いて片付ける）。
- 続ける: 殻が出した「続ける」の行（`resume <run-id>`）で、済んだ節の続きから回る。Archon が受ける failed か paused の run にだけ出る（走っている run・持ち主が消えた run には出ない）。
- 節が落ちた run（ブロックの中の出し直しが上限（3 回）を超えたときを含む）でも報告の節は走る。受け止めると宣言した段（`[optional]`）の落ちは、線の終わりまで届いた run では結末を `interrupted` にせず、報告の冒頭 3 に「落ちたが、線が宣言のとおり受け止めた節」の行で並び、冒頭 1 の残りと次の run の依頼に「確かめていない（再実行の要あり）」と載る（Archon の run の状態は失敗のまま残りうる）。それ以外の落ちは結末 `interrupted` の `report.md` と `next-request.json` が盤面に残り、冒頭 3 に落ちた節とその誤りの文が出る。start で落ちた run は盤面が無く、報告も無い。
- 取り消し・abandon で止めた run は報告の節まで届かない。対象リポジトリの根（git の最上位のフォルダ）で、`WORKS_DEV_HOME=<利用の家のパス>` を前に付けて（パスは自分で組まず、`show` が出す「取り消す」「続ける」の行の頭の `WORKS_DEV_HOME=` の値をそのまま写す） `sh "<works の置き場>/dev/report.sh" <run-id>` を打つと、盤面から報告を組む（結末 `interrupted`）。
