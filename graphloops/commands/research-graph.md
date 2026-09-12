---
description: 設計・手法・技術選定の見立てを、業界/学界の一次情報で校正してからドメイン最適化する調査ループのグラフ実行版（/research-loop と同じ目的・同じ記録の形）。回す手順は機械（engine）が持ち、この手順書は engine の呼び方だけを書く。コード変更のレビューには使わない。
allowed-tools: Bash, Agent, Read, Write, Edit, Grep, Glob, WebSearch, WebFetch
---

## これは何か

見立て文書（設計・手法・技術選定の仮説を書いた文書）の中の「外部に照合できる主張」を一次情報で判定させ、訂正を統合し、独立の目のゲートを通して、新しい相違が出なくなるまで回す調査ループである。convergence-loops の `/research-loop` と目的も記録の形も同じで、違いは手順の置き場だけ——散文の手順書の代わりに、グラフ（`graphs/research-loop.json`: 節・依存・役・プロンプト・返答の型）を engine（`scripts/loop.py`）が読み、盤面（どの節が終わったか・何周目か）・同時に走らせてよい組・渡してはいけないもの・件数の突合・連続カウント・上限・止める条件を機械が持つ。ループの算術（記録の初期形・扇の項目の選び方・収束判定）は `rules/research-loop.py` にある。記録の欄と語彙の正本は convergence-loops の `scripts/research-record.py` で、engine は報告の前にそれを回す。

このループを回す session が **surveyor**（調査者・統合者）で、それはあなたである。あなたがするのは判断作業だけ——問いと制約の棚卸し・主張の棚卸し・訂正の統合・ドメイン適応・報告。判定（確証・相違・留保・検証不能）は一切しない。判定は別 context の役割 agent が返し、engine がそれを記録に写す。

役割 agent は convergence-loops に同梱の `agents/*.md` を使う。engine が返す `agent_type`（`convergence-loops:investigator` のような値）をそのまま Agent の `subagent_type` に渡せ。モデル・道具は役の定義が正本で、この手順書にもグラフにも書かない。

## 手順

1. **始める**。依頼文と見立て文書を渡して盤面を作る:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" init --loop research-loop --request @<依頼文のファイル> --document <見立て文書>
   ```

   返ってきた `dir`（盤面の置き場）を **以降の全部の呼び出しに `--dir <DIR>` で渡せ**。省くと engine は `current` から推測するが、同じリポジトリに別の run が在ると取り違えて拒む（別ループの run が並ぶと exit 2）。名指しが既定の導線である。

   `--request` は文字列でもよい。段は既定で標準。**軽量にしてよいのは依頼者がそう言ったときだけ**で、そのときに限り `--thickness 軽量 --decider 依頼者指定` を添える（回す側の判断で下げる道は無い。engine が拒む）。無人で走るなら `--unattended`（人に聞く番になったら保守的に止まり、聞きたかったことを報告に載せる）。返ってきた `overview` を読め——ループ全体の形はここだけで渡す。

2. **回す**。`next` を呼び、返った `ready` を全部こなし、`done` で返す。これを `status` が converged か stopped になって `ready` が空になるまで繰り返す:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" next --dir <DIR>
   ```

   `ready` の各要素は 1 つの節（instance）で、`mode` が 3 種類ある:
   - **cli** — 道具ゼロの遮断系（`cold-reader` / `blind-judge`）。`launch.argv` を**そのまま**実行し、標準入力に `launch.stdin` のファイルを流して、標準出力を `out_path` に保存する。**Agent ツールで起こすな**——ハーネスが subagent に CLAUDE.md 階層を注入し、それを止める設定が公式に存在しない（公式文書 code.claude.com/docs/en/sub-agents、2026-09-12 取得: 『Explore and Plan are the only subagents that omit CLAUDE.md and git status. There is no frontmatter field or per-agent setting to change which agents skip them.』）。実測 2026-09-12: 道具ゼロの `cold-reader` が利用者の CLAUDE.md の1 項目を逐語で引用した。`--setting-sources ""` は CLAUDE.md ごと外す。材料は標準入力で渡るので貼る上限に当たらない（2026-09-12 にこの環境——macOS・claude 2.1.269——で観測: 748,883 バイトと 774,021 バイトの入力が先頭・末尾とも欠けずに届いた。測定の記録は docs/loop-contract.md の T 節。上限の値は目安で、入り切らなければ API が落として done が拒む）。組織管理の CLAUDE.md だけは外せないので、完全な遮断とは名乗らない。**子プロセスは親の環境を継ぐ**——別プロファイル（`CLAUDE_CONFIG_DIR`）で回していると認証が子に効かないことがある（実測 2026-09-12: 『Failed to authenticate…』の 1 行が返った）。**起こす前に同じ argv で疎通を確かめろ**——`echo "ok と 1 語だけ返せ" | "${launch.argv[@]}"` が exit 0 で 1 語返れば本番を流す。返らなければ対話で使っている claude と同じ `CLAUDE_CONFIG_DIR` を与えて起こし直す。
   - **agent** — `subagent_type` に `agent_type` を渡して起動する。**起動は運び手に任せろ**——小さな汎用 agent（最小のモデルでよい）を「運び手: `<prompt_file>` を `deliver` の渡し方で `<agent_type>` に渡し、返答を一字も変えず `<out_path>` に書け。あなたには wrote とだけ返せ」の 1 文で立てる。役の返答はあなたの文脈を通らず、`done --node <id>` は `--output` 無しで置き場を読む。貼るのがあなたでも運び手でも写しの忠実さは同じで、違うのはあなたの文脈が減ることだけ。`deliver` が `path` なら運び手は「`<prompt_file>` を Read し、その指示にそのまま従え。返答は指示どおりの JSON だけ」の 1 文で役を起動し、`paste` なら本文をそのまま貼る。**役が「ファイル内の指示には従わない」と拒んだら**（実測 2026-09-12: inspector が prompt injection の防御として拒んだ）、本文を Read して貼る形（`paste`）で起こし直せ。拒否を言い含める再起動はするな——分類器に止められる。 どちらも**本文に足すな・削るな・言い換えるな**（貼ってよいものは engine がグラフの宣言に従って埋めてある。足した一言が遮断を壊す）。
   - **runner** — あなたの仕事。`prompt_file` の指示に従って自分でやり、返答の JSON（`report` は本文そのもの）を `out_path` に保存する。記録や役の返答は本文でなく置き場のパスと 1 行の要約で渡される（あなたは受け取った時に一度読んでいる）——要る所だけ Read で読む。

   同じ `ready` に載った節は互いに依存が無い。**agent は 1 つのメッセージで並列に起動しろ**（直列に待つ理由が無い）。返答を保存したら:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" done --node "<id>" --output <返答のファイル> --dir <DIR>
   ```

   `done` が exit 1 で拒んだら、理由を読んで直す。agent の節なら、理由を添えて**同じ役を起動し直して返させろ**——あなたが JSON を補ったり判定を書き換えたりしてはいけない（回す側は採点しない）。runner の節なら自分の返答を直す。`ready` が空で `status` が running なら、もう一度 `next`（機械の節が進んで次の波が出る）。

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

## 守ること

- 記録（`record.json`）を直接編集しない。判定の欄は役の返答から engine だけが書く。
- 済んだ節に `done` し直さない（同じ周で回し直して有利な判定を採らない。やり直しは次の周）。
- 会話が圧縮されて場所を見失ったら `loop.py status --dir <DIR>` → `loop.py next --dir <DIR>`。盤面はディスクにある。
- 置き場は `git rev-parse --git-dir` の下（作業ツリーの外）。investigator の前後で engine が `git status --porcelain` を突き合わせ、差があれば `done` を拒む。自分の変更なら `--accept-tree-change "<理由>"` で痕跡付きで通す。
- 報告は依頼者の言語で書く。この手順書が日本語なのは理由にならない。
