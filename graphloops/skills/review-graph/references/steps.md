# review-graph の手順（始める・回す・人に聞く番・止める・終わり）

## 手順

1. **始める**。何をレビューするか（PR 番号・ブランチ・一言）を依頼文として渡す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" init --loop review-loop --request "<何をレビューするか>"
   ```

   **人から直す依頼を持って来たなら**、最初の `next` の前に、「判定から入る（人の修正依頼）」の手順で依頼を `add` せよ——run が判定から入るのは 1 周目の P1 より前の `add` だけで、最初の `next` の前が確実である。

   旗が無ければ回し役なしで回る（本文の「早見」）。会話で回すなら `--no-engine-runners` を足す（消す予定の道）。対象リポジトリの決まりが変異テストを手元で撃たせない（CI か合流の後に限る）なら、`--input gates=merge` も足せ——付けない run では、ゲートの検算と最後の関門の任せ先が手元で変異の実行器を撃つ。

   返ってきた `dir`（盤面の置き場）を **以降の全部の呼び出しに `--dir <DIR>` で渡せ**。省くと engine は `current` から推測するが、同じリポジトリに別の run が在ると取り違えて拒む（別ループの run が並ぶと exit 2）。名指しが既定の導線である。

   検証器は同じリポジトリの `scripts/review-record.py` か、インストール済みの convergence-loops から engine が探す（見つからなければ `--validator <path>`）。**`--validator` で外のファイルを指すときは、隣に `record_common.py` も置け**——検証器 4 本が共有する土台を自分の隣から import するので、検証器 1 本だけ写すと `ModuleNotFoundError` で落ちる（実測 2026-09-15）。無人で走るなら `--unattended`。**N 周目で止める**なら `--stop-after-round N`——N 周目の締め（周の記録・検証器・収束の判定）まで済ませ、次の周を開かずに止まる（`status` が stopped、盤面と `status` の `halted` が `by: stop_after_round`。止めた後の `next` は節を出さず、報告も書かない）。並べた run を 1 周で止めて合流させるとき・プログラムが周の数を決めて回すときに使う。止めた run を次の周へ進めるなら `loop.py resume --reason "<理由>" --stop-after-round <次に止める周> --dir <DIR>`（止めずに回すなら `--no-stop-after-round`）——続けられるのは周の数で止めた run だけで（人や無人の規則が止めた run は拒む）、盤面の手当て（`patch`）で開けるな。続けた痕跡は盤面の `resumes` と記録の `process.resumes` に残る。収束・人に聞く番（上限・前提不成立）はそれより先に来る。返ってきた `overview` を読め——ループ全体の形はここだけで渡す。

2. **回す**。`loop.py run` を**前景で**打つ（Bash の timeout は最大に）。engine が起こせる節（役・走らせるだけの節・sandbox の中の任せ先）は、run が会話の Bash から切り離して立てる回し手が起こして受け付けまで進め、run は止まる所でだけ戻る。回し手は 1 つの run に 1 本だけで（盤面の置き場の錠で決まる。2 本目の run は回し手を立てずに付き添う）、見守りの run が Bash の上限に当たって止められても背景へ移されても、回し手と役は止まらない:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" run --dir <DIR>
   ```

   終了コードごとの次の手は本文の「早見」の 2（手引きはそこ 1 か所。値の表の正本は engine の `runner.CODES`・`HOW`）。13 で返った節は、各行の `handoff_why` と「会話で回す run の節のこなし方」の節の種類のとおりにこなす。回し手は他の節を回し続けている。

   出力は標準出力の最後の 1 行の JSON（`stop`・`code`・`status`・`round`・`handoff`・`needs_human`・`running`・背景の線の落ちた行 `lanes_failed`・`engine`・回し手の `runner.pid` と起動時刻・`how`）。役の返答の本文は出ない。回し手の出力は盤面の置き場の `run.log`、起こした節と止まった種類は `trace.jsonl` の `op` が `run` の行に残る。**回し手を一時停止する**なら、その pid に SIGTERM を送れ——起こし済みの役の終わりを待ち、新しい役を起こさずに抜ける（続きは `run` か `next` で盤面から）。

   13 で返る節と理由は「回し役なしで回す」、`next`・`ready`・`done` の往復で回すときの節の種類ごとのこなし方は「会話で回す run の節のこなし方」に在る。

3. **人に聞く番**。`next` が `awaiting_human` を返したら、`ask` の中身（問いの台帳で保留のもの）を依頼者に見せて答えをもらい、返す。答えの本文は `--note` に入れる（次の周の judge の再審に渡る）:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" answer --text continue --note "<答え>" --dir <DIR>
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" answer --text stop --dir <DIR>
   ```

   **聞き方**: 質問の道具（選択肢を並べて選ばせる型）を使うな。依頼者はループの間ずっと別の作業をしていて、答える時点で文脈を持っていない。選択肢だけ並んだ問いは初見では決められない。散文で、次を冒頭にまとめて出せ: ①何のループが・何を調べていて・どこで止まったか ②なぜ止まったか（きっかけの実物——どの問いが・何周目に・何から立ったか）③答えの候補ごとに何が起きるか ④あなたの推奨と根拠（`escalate` は judge が「人でないと決められない」と確定したものなので推奨を書くな。書いてよいのは台帳の `options` と `reason` だけ）。内部の語彙（節の名前・安定キー・stuck 等の種別名）は使うなら初出で中身から言え。答えは自由な文で受け、`answer` の語に写すのはあなたの仕事である。

   **周の途中の関所**（人の決定権の関所）: 今ある能力を減らす・狭める変更と、人の方針（「人の方針」）とぶつかる変更は、役が代償として決めない。修正の前（`p2.human_gate`）は修正案が自分で書いた狭め（`narrows`）と事前審査の後退（regression）・方針（policy）の穴を、修正の後（`r4.human_gate`）は R4 が BASE から消えたと見た能力と人の方針とのぶつかり（`policy_conflicts`。どちらも前に人が通した同じ文の行は除く）を、どちらも方針の文書が固定した版から変わっていればそれも（前後の写しと差分の置き場を添えて）、`next` が `awaiting_human`（`ask.in_round` が真）で返す。答え方は仕様の道の承認と同じ——`answer --text continue --note "<通す範囲と条件>"` は同じ周のまま先へ進み（答えは記録の `process.human_items` に残り、同じ周の修正役のプロンプトに届く。方針の文書の変更を通すとその版を固定し直す）、`answer --text stop` は run をその場で止める。無人（`--unattended`）ではここで止まる。**直す義務の単位をこの周の修正から外す**なら、修正の前の関所（`p2.human_gate`）への continue に `--detail <JSON のファイル>` を添える（`{"exclude": [{"unit": <番号か key>, "why": <理由>}]}`。番号は関所の問いが並べた番号）——外した単位と理由は記録の `process.human_items` に残り、修正役は直さずに `not_done` に書き、次の周の判定役（`p2.history`）が理由を見て振り分ける。note の自由文からは外さない。関所は後退・方針の穴か方針の文書の変化が在る周にだけ立つので、立たない周に単位を外したいなら、次の周の判定の前に `add` で依頼し、判定役に決めさせる。修正差分の審査は後退・方針の語を使えない（削除は今の姿に引く字列が無く、手直しの義務に入ると人より先に修正役が決めるため）——修正の後の後退と方針とのぶつかりは R4 が受ける。

   **人が途中で止める**（人に聞いていない時点でも）: 依頼者が「止めて」と言ったら、理由を添えて止める——止めた事実と理由は盤面の `stop` と記録の `process.halted` に残り、次の `next` は graph が宣言する後始末の節（最上位の `stop.node` の下流＝報告の節）だけを出す。止めた周に走らなかった節は止めた印（`process.stopped_nodes`。省いた機構 `process.skipped` とは別）になり、engine が起こし中の役の子は木ごと止まる（Agent・任せ先で起こした試行は engine が持たないので、出力が名指しした物を回す側が止める）。今の止め方（人に聞いている番の `answer --text stop`・init の `--stop-after-round N`・`next` を打たずに置いて盤面から再開する）はそのまま使える。`run` の回し手は SIGTERM で一時停止する（起こし済みの役を待ち、新しい役を起こさない。pid は `run` の出力と盤面の置き場の `runner.json`）——止めた記録を残して終えるのは `loop.py stop` である。init の版の graph に `stop` の宣言が無い run は、報告の節を出さずに止まる（`halted` の `by: stop`。記録の検証は `loop.py finalize`）:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" stop --reason "<依頼者の止める理由>" --dir <DIR>
   ```

   **run の子の残りを見る・止める**: 受け付けの後に残った子（止め切れなかった木・`launch` が先に死んだ試行の子）は、`loop.py children --dir <DIR>` が盤面の印から一覧し（信号は送らない）、`--stop --reason "<理由>"` で木ごと止める。ps の文字列でプロセスを探して止めるな（同じ機械の別の run に当たる）。既定で止めるのは `launch` が居なくなった後の止め残しだけで、いま走っている試行の子と受け付けの前の instance の子は `--include-running` を付けたときだけ止まる（受け付けの前の試行は relaunch・stop で止める）。印を持たない子（engine が起こしていない物）はこの口に映らない。外の土台（engine を子として起こし、取り消すときに SIGTERM の後で SIGKILL を送る物）の下で回すなら、止める猶予（既定 5 秒。環境変数 GL_KILL_GRACE）をその土台の取り消しの猶予より十分短くせよ——同じか長いと、engine が孫を止め終える前に外から消され、孫が残る。短くするのは必要だが足りない（止める木の本数と数え上げの時間にも伸びる）。立てる場所と上限・下限は [README の「外の土台の下で回すとき」](../../../README.md#外の土台の下で回すとき)。

4. **終わり**。最後の節 `report` の前に engine が記録を仕上げて検証器を回す。`report` の本文は盤面の置き場の `report.md` に保存される。それを依頼者の言語でそのまま出せ。ループが途中で終わったら、基準点の節で `git add -N` したパスを `git reset -- <path>` で戻せ（この手順が index を変える唯一の書き込み）。
