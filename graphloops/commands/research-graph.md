---
description: 設計・手法・技術選定の見立てを、業界/学界の一次情報で校正してからドメイン最適化する調査ループのグラフ実行版（/research-loop と同じ目的・同じ記録の形）。起動するのは、人が /research-graph と打ったときか「工程に回して」と言ったときだけ——AI は自分から起動せず、設計文書の論拠固め・技術選定・方式検討・直し方の見立ての校正に当たったら人に提案する。回す手順は機械（engine）が持ち、この手順書は engine の呼び方だけを書く。コード変更のレビューには使わない。
allowed-tools: Bash, Agent, Read, Write, Edit, Grep, Glob, WebSearch, WebFetch
---

## これは何か

見立て文書（設計・手法・技術選定の仮説を書いた文書）の中の「外部に照合できる主張」を一次情報で判定させ、訂正を統合し、独立の目のゲートを通して、新しい相違が出なくなるまで回す調査ループである。convergence-loops の `/research-loop` と目的も記録の形も同じで、違いは手順の置き場だけ——散文の手順書の代わりに、グラフ（`graphs/research-loop.json`: 節・依存・役・プロンプト・返答の型）を engine（`scripts/loop.py`）が読み、盤面（どの節が終わったか・何周目か）・同時に走らせてよい組・渡してはいけないもの・件数の突合・連続カウント・上限・止める条件を機械が持つ。ループの算術（記録の初期形・扇の項目の選び方・収束判定）は `rules/research-loop.py` にある。記録の欄と語彙の正本は convergence-loops の `scripts/research-record.py` で、engine は報告の前にそれを回す。

このループを回す session が **surveyor**（調査者・統合者）で、それはあなたである。あなたがするのは判断作業だけ——問いと制約の棚卸し・主張の棚卸し・訂正の統合・ドメイン適応・報告。判定（確証・相違・留保・検証不能）は一切しない。判定は別 context の役割 agent が返し、engine がそれを記録に写す。

役割 agent は convergence-loops に同梱の `agents/*.md` を使う。役は engine が `loop.py launch` で起こす（役の定義を読んで起こすので、あなたは役の名前を扱わない）。engine が起こせない役だけ、`agent_type`（`convergence-loops:investigator` のような値）をそのまま Agent の `subagent_type` に渡す（下の「`launch` を持たない agent」）。モデル・道具は役の定義が正本で、この手順書にもグラフにも書かない。

## 手順

1. **始める**。依頼文と見立て文書を渡して盤面を作る:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" init --loop research-loop --request @<依頼文のファイル> --document <見立て文書>
   ```

   返ってきた `dir`（盤面の置き場）を **以降の全部の呼び出しに `--dir <DIR>` で渡せ**。省くと engine は `current` から推測するが、同じリポジトリに別の run が在ると取り違えて拒む（別ループの run が並ぶと exit 2）。名指しが既定の導線である。

   `--request` は文字列でもよい。段は既定で標準。**軽量にしてよいのは依頼者がそう言ったときだけ**で、そのときに限り `--thickness 軽量 --decider 依頼者指定` を添える（回す側の判断で下げる道は無い。engine が拒む）。N 周目の締めの後で次の周を開かずに止めるなら `--stop-after-round N`（`status` が stopped、`halted` が `by: stop_after_round`。止めた後の `next` は節を出さない）。無人で走るなら `--unattended`（人に聞く番になったら保守的に止まり、聞きたかったことを報告に載せる）。返ってきた `overview` を読め——ループ全体の形はここだけで渡す。

2. **回す**。`next` を呼び、返った `ready` を全部こなし、`done` で返す。これを `status` が converged か stopped になって `ready` が空になるまで繰り返す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" next --dir <DIR>
   ```

   `ready` の各要素は 1 つの節（instance）で、`mode` が 3 種類ある（cli・agent・runner）。**役の節（runner 以外）は、`launch` を持っていれば engine が起こす**:
   - **`launch` を持つ節（cli・agent）** — cli は道具ゼロの遮断系（`cold-reader` / `blind-judge`）、agent は道具つきの役（`investigator` / `inspector` / `judge`）。**`loop.py launch` を Bash の背景実行で呼び、手番を終えるな**——背景の出力のファイル（ハーネスが返す置き場。自分でリダイレクトしない）に `launch` の要約（`"launched"` の JSON）が出るまで、前景で 1 回 10 分未満の見に行くコマンドを繰り返せ（例: `for i in $(seq 1 54); do grep -q '"launched"' <出力のファイル> && break; sleep 10; done`。完了の知らせは届かないことがあるので待たない。先頭が `sleep` のコマンドは Bash が拒む）。engine が役を `claude -p` の子として起こし、子の終了を直接待って返答を `out_path` に書き、受け付け（`done` の中身）まで済ませる（`--node` で 1 節だけ、省くと同じ波の `launch` を持つ節を全部並列に）。役の返答の本文はあなたの文脈に入らない。`ok` の節は `done` 不要——そのまま `next`。拒まれたら engine が同じ会話に出し直させる（時間の上限は付けない）。ok でなければ `why` を読み、拒否が上限まで続いた・子が落ちたなら `loop.py relaunch --node <id> --reason <理由>` の後に `launch`（relaunch は新しい試行を書いてから前の試行の子を木ごと止める）。`why` が『起こし直された古い試行』の行は次の手が要らない。**自分の Bash から起こすな**: 出力をファイルに落とす綴りは auto mode の分類器が『Auto-Mode Bypass』で止める（実測 2026-09-15: 同じ層でも出力が会話に出る形は通り、`< 材料 > out_path` は止まった）。止められても別の綴りを探すな。**Agent ツールで起こすな**——ハーネスが subagent に CLAUDE.md 階層と git status を注入する。CLAUDE.md は役の定義の `omitClaudeMd` で省けるが、git status は止められない（公式文書 code.claude.com/docs/en/sub-agents、2026-09-25 取得: 『Every other built-in and custom subagent loads both, unless its definition sets the omitClaudeMd field to skip the user, project, and local CLAUDE.md files.』『You can't change which subagents receive git status. Only Explore and Plan skip it.』）。実測 2026-09-12: 道具ゼロの `cold-reader` が利用者の CLAUDE.md の1 項目を逐語で引用した。`--setting-sources ""` は CLAUDE.md ごと外す。材料は標準入力で渡るので貼る上限に当たらない（2026-09-12 にこの環境——macOS・claude 2.1.269——で観測: 748,883 バイトと 774,021 バイトの入力が先頭・末尾とも欠けずに届いた。測定の記録は docs/loop-contract.md の T 節（リポジトリのルート基準。プラグインとして入れた実体には無いので、clone か GitHub で見る: https://github.com/raiki61/claude-plugins）。上限の値は目安で、入り切らなければ API が落として done が拒む）。組織管理の CLAUDE.md だけは外せないので、完全な遮断とは名乗らない。**子は対話の claude の認証を継がない**（実測 2026-09-12: 『Failed to authenticate…』の 1 行・73 バイトが返り、`done` が非 JSON として拒んだ）——なので engine は認証だけを足す層（`scripts/with-auth.py`）を前置して起こす。`launch` の結果は 1 件ずつ `ok` と `why` と `stderr` を返す。**ok でなければ stderr の `with-auth: auth=…` を読め**: `keychain(…)` / `inherited(…)` なら認証は足りていて原因は役の返答の側、`none` / `keychain-miss(…)` なら認証が足りていない。包みを解けなかった回（『誤りで終わった』『result が無い』『標準出力が空』）と子が exit 0 以外で終わった回は、何が返ったかが盤面の `trace.jsonl` の `op` が `role_run` の行（`stdout_head`・`subtype`）に在る。包みでない出力を本文として読んだ回はその行の `envelope` が false で、会話の番号・費用などの要約が無く、拒まれても同じ会話に続きを頼まない。engine が起こせない節（`why` が『前置ではない』『旗が無い』『権限の形』『定義が読めない』『claude が無い』）は、迂回を組まず人に渡せ。**道具つきの役**も同じ綴りで起こす（graph の `launch.tooled`。理由の正本は review-loop の graph の同じ欄）: 役の定義の本文を system prompt に足し、道具・モデル・effort を定義どおりに argv に並べ、権限は engine が道具から決める——先に許した物だけが通る `dontAsk` で聞く先を持たず、コマンドを走らせる道具（Bash）を持つ役（investigator）には Bash を丸ごと許さず読むだけのコマンドの前置（gh の issue・pr の list と view・pr diff・search・repo view と git remote get-url）だけを許す。先行議論の突合（`p0.prior_decisions`）は GitHub の issue・PR を gh で読み（非公開のリポジトリも読める）、gh が使えない場だけ WebFetch で読む。どちらでも届かなければ checked=false が返り、新しい相違がゼロの周に収束の前で人に聞く（無人なら止まる）。investigator が作業ツリーを変えて突合で止まったら、返答は `out_path` に在るので、戻してから `done --node <id>`（自分の変更なら `--accept-tree-change`）。
   - **`launch` を持たない agent** — 役の定義がこの環境に無い・定義が道具の一覧を持たない・ファイルを書く道具を持つ・モデルか effort を名指ししない役。今の graph の道具つきの 3 役はどれも engine が起こせる定義を持つのでここには落ちない（標準の筋書きで出る役の節に `launch` が付くことは、このリポジトリの検査が確かめている）が、役を足す・定義を変えるとここに落ちうる。同じ plugin の役の定義が読めない環境では、遮断系かどうかが決まらないので `next` が止まる。落ちた節は、`subagent_type` に `agent_type` を渡して Agent ツールで**直接**起こし（`deliver` が `path` なら「`<prompt_file>` を Read し、その指示にそのまま従え。返答は指示どおりの JSON だけ」の 1 文、`paste` なら本文をそのまま貼る。**本文に足すな・削るな・言い換えるな**）、返答を `out_path` に書いて `done --node <id> --agent-id <役の id>`。このときだけ役の返答があなたの文脈に入る。
   - **runner** — あなたの仕事。`prompt_file` の指示に従って自分でやり、返答の JSON（`report` は本文そのもの）を `out_path` に保存する。記録や役の返答は本文でなく置き場のパスと 1 行の要約で渡される（あなたは受け取った時に一度読んでいる）——要る所だけ Read で読む。

   同じ `ready` に載った節は互いに依存が無い。`launch` を持つ節は 1 回の `launch` でまとめて並列に起こる。runner の節（と `launch` を持たない agent の節）は、返答を保存したら:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" done --node "<id>" --output <返答のファイル> --dir <DIR>
   ```

   `done` が exit 1 で拒んだら、理由を読んで直す。役の節なら、理由を添えて**同じ役に返させろ**（`launch` で起こした節は engine が同じ会話に出し直させる。上限まで拒まれたら `relaunch` で起こし直す）——あなたが JSON を補ったり判定を書き換えたりしてはいけない（回す側は採点しない）。runner の節なら自分の返答を直す。`ready` が空で `status` が running なら、もう一度 `next`（機械の節が進んで次の波が出る）。

3. **人に聞く番**。`next` が `awaiting_human` を返したら、`ask` の中身を依頼者に見せて答えをもらい、返す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" answer --text <continue|stop|escalate> --note "<依頼者の答えの本文>" --dir <DIR>
   ```

   **聞き方**: 質問の道具（選択肢を並べて選ばせる型）を使うな。依頼者はループの間ずっと別の作業をしていて、答える時点で文脈を持っていない。選択肢だけ並んだ問いは初見では決められない。散文で、次を冒頭にまとめて出せ: ①何のループが・何を調べていて・どこで止まったか ②なぜ止まったか（きっかけの実物——どの主張・どの判定か）③答えの候補ごとに何が起きるか ④あなたの推奨と根拠（人でないと決められない事項では推奨を書くな）。内部の語彙（節の名前・安定キー・stuck 等の種別名）は使うなら初出で中身から言え。答えは自由な文で受け、`answer` の語に写すのはあなたの仕事である。

4. **ループの外へ出る道**。`p0.claims` の返答に「開いた問い」（地図がまだ無い・選択肢の洗い出しが要る）があれば、`done` がその旨を返す。それは閉じた主張の検証では解けないので、このループの外で deep-research に委ね、持ち帰った事実主張を次の周に入れる:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" add --file <claims.json> --reason "deep-research の持ち帰り" --dir <DIR>
   ```

   相違が結論の芯に刺さった・stuck が出たら段を上げる（義務。下げる道は無い）: `loop.py thicken --to <段> --reason "<理由>" --dir <DIR>`。optional の節を省くときは `loop.py skip --node <id> --reason "<理由>" --dir <DIR>`（報告の「省略した機構」に載る）。

5. **終わり**。最後の節 `report` の前に engine が記録を仕上げて検証器を回す。通らなければ `report` は出ない（record.json と trace.jsonl を見て直す。手当ては `loop.py patch`——痕跡が残る最終手段）。`report` の本文は盤面の置き場の `report.md` に保存される。それを依頼者の言語でそのまま出せ。`reflect` の提案（グラフ・プロンプト・engine・検証器のどこを直すべきか）は run の中で書き換えず、依頼者に見せる。

## 人の方針

人が決めた、どの run にも効く決まりは、対象リポジトリの共有の git ディレクトリ（`git rev-parse --git-common-dir` が指す所）の下の `graphloops/policy.md` に置けば、`init` が拾う（別の文書なら `init --input policy_md=<パス>`）。問いの確定・反証・統合・内部照合・適用の節に、役には本文が、回す側には置き場が届く。置き場の決め方と文書の変化の扱いは [review-graph の「人の方針」](review-graph.md#人の方針) と同じ——ただしこの loop には周の途中の関所が無いので、文書が init の後に変わっても周の途中では人に聞かない。init の時点の版（sha と写しの置き場）を記録の `process.policy` に固定し、報告の前の仕上げで比べて、変わっていれば `process.policy_change`（前後の写しと差分の置き場）に残し、報告の冒頭に出す。

## 守ること

- **run の途中でプラグインの版を上げても、走っている run の graph は init の時の版のまま**: 盤面は init の時の graph を、その置き場（インストールされた版のディレクトリ）の絶対パスで持ち、graph・指示書・rules・検証器をそこから読み続ける。置き場のファイルそのものが書き換わる形（`--plugin-dir` などでその場から読み込んだプラグイン）では graph も変わり、変わった周は `next` の `notes` と `process.graph_changes` に出る。engine（`loop.py`）は今インストールされている版で動き、役の定義（convergence-loops の `agents/<役>.md` の道具・モデル・effort・system prompt に足す本文）は節を描くたび（`next` が節を出すとき）に今見つかる版から読む——どの engine が周を回したかは、替わった周の `next` の `notes` に出る。新しい版の graph や指示書の動きが要るなら、走っている run を仕上げてから新しい run を始めよ。盤面を別の版の graph へ付け替える手順は用意していない（`loop.py patch` で state を書き換えれば変わるが、それは手当ての口で、この用途には案内しない）。更新で置き換わった古い版のディレクトリは後で掃除されることがあり（公式の plugins の読み込みの文書『Cleanup of previous versions』）、消えるとその run は開けなくなる。古い版の graph が役を `--output-format text` で起こしても、engine は包みでない標準出力を本文として読むので、返答は受け付けまで届く。
- 記録（`record.json`）を直接編集しない。判定の欄は役の返答から engine だけが書く。
- 済んだ節に `done` し直さない（同じ周で回し直して有利な判定を採らない。やり直しは次の周）。
- 会話が圧縮されて場所を見失ったら `loop.py status --dir <DIR>` → `loop.py next --dir <DIR>`。盤面はディスクにある。
- 置き場は `git rev-parse --git-dir` の下（作業ツリーの外）。investigator の前後で engine が `git status --porcelain` を突き合わせ、差があれば `done` を拒む。自分の変更なら `--accept-tree-change "<理由>"` で痕跡付きで通す。
- **engine の出力を会話から外さない**（`> file` へ落として読まない形にしない）。見立て文書を読んだかの確かめは、この session の転写に残る道具の結果を engine が読んで判断する——engine を回した出力そのものが「この run を回したのは会話の主である」印になっているので、出力を捨てると確かめが成立せず、その回は「確かめられなかった」として記録に残る（読んでいないのに通るわけではない。確かめが立たないだけで、痕跡は報告に出る）。同じ理由で、**engine を回した出力が会話に残らない場から回すと確かめは成立しない**（この会話自体が下請けの場合を含む）——確かめさせたいなら、engine の出力が会話に出る場から回せ。engine は転写の由来を判定していないので、これは engine の保証ではなく、出力が転写に載るかどうかの話である。
- 報告は依頼者の言語で書く。この手順書が日本語なのは理由にならない。
