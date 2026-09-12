# graphloops は車輪の再発明か（見立て）

このリポジトリの `graphloops/` は、収束ループ（結果が動かなくなるまで回す手順）を JSON のグラフに写し、機械（engine）が盤面を持って回す Claude Code のプラグインである。Claude Code は Anthropic のコマンドライン型のコーディング環境で、メインの会話（ここでは「回す側」と呼ぶ）と、そこから立てる子の会話（subagent。ここでは役の定義を持たせたものを「役割 agent」と呼ぶ）を持つ。graphloops は汎用の実行基盤（engine）と、ループごとの算術（rules）と、節ごとのプロンプトから成る。この文書は「engine の汎用部は既存のソフトウェアの再発明ではないか」という問いへの見立てで、事実の主張を一次情報で校正しながら育てている（校正の経緯は末尾の「訂正の記録」）。

## 凡例（本文で使う役割語）

このループは調査者（surveyor＝メインの会話）が主張を棚卸しし、検証は別の会話の役が行う。役割語は次のとおり。

- **checker**: 主張を一次情報に照合して確証／相違／留保／検証不能の判定を返す役（役割 agent の investigator）
- **refuter**: checker の「相違」判定と、結論が乗る確証を、反証を試みて再判定する役（judge）。相違はこの役を経て初めて確定する
- **rederiver**: 調査結果を見せず、問いと制約だけから見立てを独立に導出する役（blind-judge）。その導出と本文を突き合わせるのが「独立導出の突合」
- **cold-reader**: 経緯を知らない初見の読み手として本文だけを通読し、導出が再現できるかを判定する役
- 主張の末尾の角括弧: **確証**＝一次情報が主張どおり、**相違**＝食い違う、**留保**＝概ね正しいが重要な限定が要る、**検証不能**＝一次情報に到達できない

## 見立て

engine が持つ機能は 7 つある。依存関係を持つ工程（DAG）の実行順の計算、同時に走らせてよい組（波）の抽出、項目ごとの扇形展開、条件による節の有効化、返答の型検査（JSON Schema の部分集合）、盤面のディスク保存と再開、人への問い合わせでの中断と再開。この 7 つはどれも新しくなく、LLM アプリ向けのグラフ実行基盤と汎用のワークフロー実行基盤に既にある（下の主張 1〜6）。その意味で汎用部は再発明である。

それでも engine を書いた理由は、動く場所の制約にある。理由は頑健な順に並べる（弱い前提が外れても結論が崩れない順）。

1. **制御の反転**。このループでは工程の実行者はメインの会話（回す側）と役割 agent で、engine は「次に何をするか」を返す被呼出側にしかなれない。この向きに合わないのは、自分で Claude Code を子として起動する taskflow 型と、Claude Code 同梱の Workflow（主張 7〜9・17）で、これは梱包と独立に構造で合わない。**ライブラリ型（LangGraph・Burr・LlamaIndex Workflows）にはこの理由は当てはまらない**——LangGraph は agent の節ごとに interrupt を置き、ディスク永続の checkpointer と同じ thread_id で別プロセスから再開できる（主張 19〜21）ので、回す側が手番ごとに呼ぶ形に組み直せる（Burr・LlamaIndex は同種の仕組みを持つが、別プロセスからの再開は未照合）。ライブラリ型に対して残る理由は、取り分の薄さ（結論の見立て）と梱包（理由 5）である。
2. **状態の所有**。節を走らせてよいかは共有の記録（`rounds/round-N.json` 等）から導く射影で、合否は既存 4 ループ共通の検証器に通した記録で決まる。候補が独自の進捗状態を持てば状態の持ち主が 2 つになる。
3. **実行者の不均質**。subagent を投げる仕組み（Claude Code 組み込みの Workflow を含む）は、自分のホストであるメインの会話を実行者にできない。棚卸し・統合・修正・報告を subagent に降ろすと、見える文脈と道具の許可が変わる。人待ちの節は不定長の中断と別セッションでの再開を要る。
4. **門番の所在**。道具の遮断（役割 agent の `tools`）と書き込み・投稿の門番（hook）は Claude Code の側にある。候補が遮断を自分側に要求する設計は、担保が定義から言い渡しに落ちる後退である。
5. **梱包**。配布の方針は「必須は git / python3 / bash だけ」（README）で、pip で入る依存を足さない。これは最も可逆で最も弱い理由で、結論の見出しには置かない——配布方針が緩めば、この理由だけが消える。

## 事実の主張（校正の対象）

各主張の末尾の角括弧は、一次情報で確かめた結果（2026-09-12 時点）。

1. LangGraph は、状態の永続化（checkpointer）と、実行を止めて人の入力を待つ仕組み（interrupt）を持つ。interrupt を使うには checkpointer をコンパイル時に設定することが前提。［確証。LangChain 公式ドキュメント］
2. LangGraph は Python か JavaScript のライブラリで、利用者のプロセス内に import して使い、モデルの呼び出しは利用者が組み込む設計である。「Claude Code の subagent を実行者にする経路は無い」は公式資料に肯定も否定も無く、現時点で見つからないという報告に留まる。［留保。GitHub README・公式ドキュメント］
3. pydantic-graph（pydantic-ai と同じ版番号で配布。最新安定版 2.43.0）は、現行版では状態の永続化を自前で持たない。`pydantic_graph.persistence` は V2（v2.0.0 系）への移行に伴い削除され（v2.0.0 安定版は 2026-06-23）、復活していない。新しい graph builder API は並列実行下で一貫したスナップショットを取る難しさを理由に、意図的に状態を保存しない。中断と再開が要るなら、別パッケージ Pydantic AI Harness の StepPersistence（agent の実行の保存・再開・分岐が対象で、任意のグラフの汎用の後継ではない）か、Temporal・DBOS・Prefect・Restate との durable execution 連携を使う。［留保まで確認。pydantic 公式の changelog・graph の文書・PyPI・harness のソース］
4. Burr（DAGWorks。リポジトリは apache/burr へ移管）は、LLM アプリを状態機械として書く Python ライブラリで、状態の永続化のためのフックと、`inputs` を持つ工程で人の入力を待つ仕組みを持つ。［確証。Burr 公式ドキュメント・リポジトリ］
5. LlamaIndex の Workflows は、イベント駆動で工程をつなぐ仕組みで、`InputRequiredEvent` と `HumanResponseEvent` で人の入力待ちを実装できる。［確証。LlamaIndex 公式ドキュメント］
6. Temporal は durable execution の基盤で、ワークフローが Signal（人の承認など）を長時間待てる。Python SDK は pip で入るが、実行には Temporal のサーバー（別配布の CLI・セルフホスト・Cloud のどれか）が要る。Prefect は Python のワークフロー基盤で、`pause_flow_run` / `suspend_flow_run` でフローを止めて人の入力を待てる（Server か Cloud のバックエンドが前提）。［確証。Temporal・Prefect の公式ドキュメント］
7. Claude Code には Workflow（dynamic workflows）というツールがあり、JavaScript の script で agent()・pipeline()・parallel() を呼び、返答を JSON Schema で強制できる。再開は `/workflows` の画面でランを選ぶか、同じ script で relaunch を依頼する形で、完了済みの agent は保存結果から返る。利用者が扱う「run の id」という API は一次情報で確認できていない。［留保。Claude Code 公式ドキュメント］（このリポジトリの Claude Code の環境では Workflow ツールに resumeFromRunId という引数が見えるが、公式ドキュメントには無い。文書は公式ドキュメントに合わせる）
8. Workflow の script は、ファイルシステムとシェルへ直接アクセスできず、モジュール読み込みも無い（`import()` を含む script は実行開始前に失敗する）。読み書きとコマンド実行は script が起動する subagent が行い、その道具の呼び出しには通常の session と同じ権限の検査とサンドボックスが掛かる。静的な import 文や require の扱い、モジュール読み込みを伴わない Node のグローバルが使えるか否かは公式ドキュメントに記述が無い。［確証（反証を経た）。同上］
9. Workflow はバックグラウンドで非同期に実行され、起動（権限モードによる起動時の承認の後）直後にメインの会話へ制御が戻る。実行中の script は、途中でメインの会話に処理を明け渡して作業結果を受け取って再開する経路を持たない（No mid-run user input。唯一の例外は agent の権限プロンプトで、これは承認であって作業の受け渡しではない。段階間に承認を挟むなら段階ごとに別のワークフローにする）。一時停止・停止・同一セッション内の再開はできる（止めた run の再開は同じ script での relaunch で、差分以降を再実行する）。［確証（反証を経た）。同上］
10. Claude Code の Agent 機能で立てた subagent は、SendMessage で同じ文脈のまま続けて指示できる（組み込みの Explore と Plan は除く）。［確証。Claude Code 公式ドキュメント］
11. subagent の定義ファイル（agents/*.md）は、frontmatter の `tools` で持てる道具を allowlist として制限できる（`tools` は継承する集合を狭める方向にしか働かない。fork は対象外。制限は道具の単位で、Bash を許したまま「書けない」とは言えない）。［確証。同上］
12. graphloops の engine は 10 ファイル・1,091 行（空行を除くと 963 行）の Python で、rules は 2 ループ分（review 510・research 426）で 936 行、prompts は 51 本で 590 行。rules と prompts を合わせて約 1,500 行（1,526 行）である。行数はエディタ表示行で、wc -l だと 1,091 / 936 / 577——差が出るのは prompts だけ（末尾に改行の無いファイルが 13 本）。［相違を 2 周で訂正。このリポジトリの実測］
13. heggria/taskflow（0.3.0-beta.1.2、TypeScript 製、beta）は、宣言的 DAG・12 種の工程・resume・replay・trace を持ち、DSL には approval（人の承認）の工程もあるコーディングエージェント向けのランタイムで、Claude Code へは MCP（JSON-RPC 2.0 / stdio）サーバとプラグインで配られる（Pi へはネイティブ拡張）。ホストが MCP から呼ぶのは taskflow_run / taskflow_resume / taskflow_trace など 20 個の制御・観測ツールで、工程の実行はホストの会話ターンの外で起きる——前景実行では DAG は MCP サーバのプロセス内で回り、ツール呼び出しは DAG 全体の完了まで返らない。長いフロー向けの background では、サーバが切り離した Node のワーカを起動し、それが MCP の要求と独立に DAG を回す。どちらでも agent の工程は taskflow がホストの CLI を `claude -p`（セッションを継承しない隔離プロセス）として起動して実行し、ホストの会話が工程の実行者になることはない。プラグインが同梱するのは MCP の登録と案内の skill だけで、ホスト側の agents / commands は持たない。MCP 経由の実行は非対話なので approval の工程は自動で拒否される（Claude Code から使う限り人の承認の門にはならない）。実行要件は Node.js 22.19 以上（pnpm が要るのはモノリポを開発する場合）。［留保まで確認。GitHub の README・docs・package.json・ソース・npm］
14. jpicklyk/task-orchestrator は Kotlin + SQLite + MCP SDK 製で、依存グラフ・SQLite の永続化・get_next_item() によるプル型の実行を持ち、Claude Code のプラグインとして配布される。README と Wiki が示す 2 つの導入経路はどちらも `docker run` を前提で、Docker 抜きの実行手順は公開文書に無い。［留保。GitHub の README・Wiki］
15. barkain/claude-code-workflow-orchestration は Claude Code のプラグインとして配布される。Team Mode の状態は 2 つの一時ファイルで、完了時か次のユーザープロンプト時に自動削除される。README に「No session resumption」と明記される。前提条件は uv と bun が両プラットフォームで必須、Python 3.12 以上は Windows の節に required、jq は macOS/Linux では但し書きなしで列挙され Windows では optional。依存ゼロではない。［留保。GitHub の README］
16. darrenapfel/claudecode-orchestrator は README 冒頭で DEPRECATED と明記され、後継 limerIQ（www.limeriq.ai）へ案内している。通知文は 2026-04-21 に改訂されているが、コード本体は 2025-07-05 の v5.0.0 以降更新が無い。［留保。GitHub の README とコミット履歴］
17. Claude Code の dynamic workflow の再開は同じセッション内に限られる（比較表の Interruption 欄「Resumable in the same session」）。ここでの「同じセッション」はプロセスの寿命とは別で、セッションのバックグラウンド化・`claude --resume`・cloud の再オープンを含む。新しく始めたセッションからは引き継げないと公式文書が明示し、`/fork` で複製したセッションについては記載が無い。公式文書に記載された、別のセッションから盤面を引き継ぐ手段は無い。［確証。Claude Code 公式ドキュメント］
18. graphloops の graphcheck.py は Python 標準ライブラリの graphlib（3.9 で追加）を import する一方、リポジトリの README は必須要件を python 3.8 以降と書いている。3.8 では graphcheck.py が動かない。［確証。Python 公式の What's New 3.9・このリポジトリの実物］
19. LangGraph（1.x 系）は、interrupt とディスクか DB に永続する checkpointer を組み合わせると、interrupt で止まった後にプロセスを終え、後から別のプロセスで同じ thread_id と Command(resume=...) を渡して再開できる。再開は止まった行からでなく、interrupt を呼んだ節（タスク）の先頭から再実行され、interrupt の呼び出しが保存された値を返して先へ進む。成立条件は 5 つ——永続の checkpointer（InMemorySaver は不可。SqliteSaver は公式が demos と小規模向けで多スレッドに耐えないと明記）・新しいプロセスで同じ構造のグラフを組み直して同じ保存先を指す・状態と interrupt の値が直列化できる（pickle_fallback の既定は false）・interrupt で制御が返った後に正常終了する（強制終了では失われる）。［留保。LangChain 公式ドキュメント・公式リポジトリの実装。「プロセスをまたいで」と名指しした一文は無く、複数の記述からの帰結］
20. LangGraph（1.x 系）で、同時に走る複数の節がそれぞれ interrupt を呼ぶと、それらは 1 回の呼び出しでまとめて返り、interrupt の id ごとに値を対応づけた辞書を Command(resume=...) に渡す 1 回で再開できる。id は節を実行するタスクの単位（1 つの節が interrupt を 2 回呼ぶと同じ id）で、同時に返るのは同じ段で止まった分だけ。［確証。同上］
21. LangGraph（1.x 系・Graph API）で、interrupt を呼んだ節は再開時に先頭から再実行される。interrupt より前の副作用は冪等でなければならないと公式が警告する。再実行されるのは interrupt した当のタスクだけで、同じ段で正常に終わった他の節は再実行されない。Functional API の @task は完了結果が再生されるので挙動が異なる。［確証。同上］

## 候補の地図（左＝業界の位置づけ／右＝このループへの適用）

| 候補 | DAG | 永続化 | 人の入力待ち | 実行者 | 梱包 |
|---|---|---|---|---|---|
| LangGraph | あり | あり | あり | 自プロセス（interrupt で反転可） | pip |
| pydantic-graph 2.x | あり | なし | なし | 自プロセス | pip |
| Burr | あり | フック | あり | 自プロセス | pip |
| LlamaIndex Workflows | イベント | あり | あり | 自プロセス | pip |
| Temporal | あり | あり | Signal | Worker | pip + サーバー |
| Prefect | あり | あり | あり | Worker | pip + サーバー |
| Claude Code Workflow | script | 同一セッション | なし | subagent | 組み込み |
| Claude Code Workflow（background） | script | 同一セッション | なし | subagent | 組み込み |
| taskflow | あり | あり | MCP 経由では自動拒否 | ホスト CLI の隔離セッション | Node 22.19+ |
| task-orchestrator | あり | SQLite | なし（記述なし） | 不明 | Docker |
| barkain | なし | 一時 | なし | メインの会話 | uv + bun |
| graphloops | あり | あり | あり | メインの会話 + 役割 agent | 標準ライブラリ |

右の適用: 「メインの会話を実行者にし、盤面をディスクに置き、人待ちで止まる」を同時に満たす既存物は、調べた範囲に無い。ただし「無い」の意味は 2 つに分かれる。taskflow・task-orchestrator・Workflow は向きが逆で組めない。ライブラリ型は interrupt と永続化で回す側が駆動する形に組める（LangGraph で確認。主張 19〜21）ので、「組めない」でなく「組んでも取り分が薄い」である（結論の見立て）。メインの会話を実行者にする既製品は barkain だけだが、DAG も永続化も持たない。

## 白地図（調べていないところ）

- GitHub のコード検索（`graphlib.TopologicalSorter` と `.claude-plugin` を同時に持つリポジトリの横断検索）は当たっていない。web 検索の断片だけ
- jcmrs/claude-code-spec-kit-subagent-plugin、turing-machines/mentals-ai、「1code」は検索結果の要約止まりで、リポジトリ本体を読んでいない
- Claude Code Workflow の script が Node のグローバル（fetch・process 等）を使えるか（主張 8 の空白）
- LangGraph 等に Claude Code の subagent を実行者にする経路が「無い」ことの確証（主張 2 の空白）
- Burr・LlamaIndex Workflows で、別プロセスからの再開（主張 19 の LangGraph 相当）が組めるか
- 既存 4 ループの検証器が graphloops の記録を無改造で受けるか（graphloops のテストは research-record.py と review-record.py の実物に記録を通しているが、この文書の主張としては照合していない）
- Claude Code の Workflow の版を固定する手段（主張 7 の resumeFromRunId のように、公式文書に無い引数が環境に見える——固定できない依存は pip 依存とは別種の危険）
- engine がループ固有の知識を持っていないことの検査（「engine はループの中身を知らない」は定義であって検証結果ではない）

## 結論の見立て

全面の置き換えは、駆動器型（taskflow・task-orchestrator）と Claude Code の Workflow に対しては構造でできず、ライブラリ型（LangGraph）に対しては組めるが割に合わない。

ライブラリ型に置き換えたときの取り分は行数で見積もれる。engine の 1,091 行のうち、日程管理と永続化に当たるのは advance.py と board.py と commands.py の一部で、空行と注釈を除いて約 400 行（実測は 2026-09-12。機能への分類は筆者）。LangGraph に載せると、この 400 行の代わりに JSON のグラフを StateGraph に翻訳する層を書き、周をまたぐ参照・被覆の再発行・instance_deps による早出し・once・active_in・same_context_as は対応物が無いので翻訳層で同じ意味を書き直す。役の返答を保存する out/ と記録の record.json はセッションと検証器が読むので残り、LangGraph の checkpoint と保存が二重になる。差し引きの行数はほぼゼロか増え、代わりにプラグインを入れる全員の開発機で依存の解決（pip か uv と初回の取得）が要る。最も近い既存物は taskflow だが、DAG を自分のプロセスで回し、Claude Code を隔離セッションとして起動する駆動器型で、メインの会話を実行者にはしない。

部分の置き換えは成立しうる。位相順の計算は Python 標準ライブラリの graphlib で足りる（engine は既にそれを使う）。subagent の起動は Claude Code の Agent 機能に載っている。門番は hook にある。Claude Code の Workflow は「メインの会話が実行する節を含まない直線区間」（checker→refuter の扇など）に限り使える。

置き換えの取り分には上限がある。消えるのはスケジューリングの核だけで、rules 936 行と prompts 51 本はループ固有の意味なので残る。engine を「ループの中身を知らない」と定義した時点で、取り分は engine の一部に切られている。

この結論は恒久ではない。再評価の引き金を 2 つ置く。(a) Claude Code の Workflow が、メインの会話を実行者にする節と、別セッションからの再開を備えたとき。(b) engine の行数か変更頻度が rules を超えたとき。行数は wc -l（現在値 engine 1,091・rules 936）。変更頻度は `git log --since` で四半期ごとに数える、engine/ と rules/ にそれぞれ触れた commit の数（現在値は両方 0——graphloops はまだ commit されていないので、初回 commit の四半期から数え始める）。もう 1 つ、engine に再試行・入れ子のグラフ・別の機械での再開が要るようになったときも見直す（既製の基盤が買ってくれるものが増える）。

二択に落とさない。第三の選択肢として「engine を消し、回す側の会話が graphs/*.json と記録を直接読んで次の節を決める」がある。実行者は JSON を読めるので原理的には可能だが、手で導いた実行可否は機械で検証できず、記録と検証器を置いた目的を損なう。採らないが、選択肢としては残す。

## 訂正の記録（append-only）

1. 主張 7〜9（Workflow の性質）はこのリポジトリのどのファイルにも裏付けが無く、記憶で書かれていた。一次情報（Claude Code 公式ドキュメント）で校正した（内部の突合の指摘）。
2. 制約「engine/ 9 本」は `__init__.py` を数えない数え方で、ファイル数は 10。行数の実測値を明示した（内部の突合の指摘）。
3. 主張 3: pydantic-graph の永続化は現行版で削除されている。v1 系の知識を現在形で書いていた（相違）。
4. 主張 12: engine 1,091 行・rules 936 行・prompts 51 本 590 行に書き換え。約 2,000 行は約 25% の過大だった（相違）。
5. 主張 13（taskflow）: 「MCP 経由で次の工程を渡してホストの LLM が実行する」は逆で、DAG は MCP サーバのプロセス内で回り、ホストの CLI を隔離セッションとして起動する駆動器型（相違）。候補の地図と結論の「最も近い既存物」を書き換えた。
6. 主張 2・7・8・9・14・15・16 に限定を付けた（留保）。主張 8 と 9 は結論が乗る主張なので、一般化していた部分（Node の API 全般・完了まで走る）を原文の射程に縮めた。
7. 「見立て」の理由の並びを、独立導出（rederiver）の指摘どおり頑健な順に組み直し、梱包（pip 禁止）を最後に置いた。制約を緩めると消える理由と消えない理由を分けるため。
8. 主張 12 の括弧内の wc -l の数字を 934 から 936 に直し、差が出るのは prompts だけと添えた（2 周目の相違。1 周目の反証役の数字を写し間違えていた）。
9. 主張 3 の版の粒度を「V2 への移行に伴い」に弱め、StepPersistence の対象が agent の実行であることを添えた（留保）。
10. 主張 13（taskflow）に、background では切り離した Node のワーカが DAG を回すこと、MCP 経由では approval が自動で拒否されること、pnpm は開発時だけ要ることを足した（留保）。候補の地図の「人の入力待ち」を「MCP 経由では自動拒否」に直した。
11. 主張 8・9 が反証を経て確証になったので、その適用条件（権限の検査とサンドボックス・権限プロンプトの例外・relaunch は差分以降の再実行）を本文に足した。主張 17（再開は同じセッション内。fork は記載なし）と 18（graphlib は 3.9 以降で README の 3.8 と食い違う）を足した。
12. 理由 1（制御の反転）の射程からライブラリ型を外した。LangGraph は interrupt と永続の checkpointer で、回す側が手番ごとに呼んで別プロセスから再開する形に組める（主張 19〜21）。「駆動器型は梱包と独立に構造で合わない」は taskflow 型と Workflow にだけ成り立つ。ループの run は 2 周目で停止していたので、この 3 主張は run の外で refuter（judge）に反証させて書いた（判定の生の返答は run の盤面の extra/ に置いた）。起点は依頼者の指摘「Python で組んだ時点で、違いは pip で入れるかどうかだけでは」。
13. 結論を「できない」から「駆動器型と Workflow にはできず、ライブラリ型には組めるが割に合わない」に直し、取り分を行数で見積もった（独立導出との突合が挙げた未決 U3——機能別の行数——を実測して入れた）。
14. 凡例を足した。checker・refuter・rederiver・cold-reader が本文で未定義だった（初見の読み手の指摘）。
15. 再評価の引き金 (b) の「変更頻度」に計測方法と現在値を足した（初見の読み手の指摘）。白地図に、独立導出との突合が挙げた未決（検証器の受け入れ・Workflow の版の固定・engine のループ非依存の検査）と、Burr・LlamaIndex の別プロセス再開を足した。

## 残る決定事項（人が決めること）

- 配布方針「必須は git / python3 / bash だけ」を緩めて pip 依存を許すか。推奨は「今は緩めない」——LangGraph に載せても差し引きの行数がほぼゼロで、代償（依存の解決）は利用者全員が払う（結論の見立て）。python3 を許して pip を許さない線引きは README の方針であって物理ではなく、書き直せる。緩める必要が出たとき（別の依存が本当に要るとき）は、即席の仮想環境（uv run と PEP 723 のインライン依存のように、実行時に環境を作って終わったら捨てる形）が導入手順を増やさない手段になる。ただし uv 自体が新しい必須の道具になり、プロキシ下の開発機では初回の取得が失敗する余地が増える。
- graphloops の必須 Python を 3.9 以降と明記するか、graphcheck.py から graphlib を外して 3.8 に合わせるか（主張 18）。
