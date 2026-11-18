# /my-turn の掘る段: ヘッドレスの形の起動の細部

[設計書](my-turn-workflow-design.md)のセクション 2 から移した細部。
/my-turn は attention のコマンド（`commands/my-turn.md`）で、掘る段は、その PR の構造をとらえて問いの木を掘る段。

- **何の細部か**: ヘッドレスの形（/my-turn の引数 `--headless`。`claude -p` をもう 1 つ起動して Workflow を回す）の起動の仕方。
  - 環境・引数・役・許可・モデルの照合と、確かめの 5 つの点を書く。
  - 確かめの 5 つの点のうち、1 は 2026-11-17 の試しで直し、残り 4 つは未確認。
- **経緯**: 2026-11-18 に設計書から移し、同じ日に実装との照合で直した。
- **番号**: 「セクション N」「手順 N」「W1」〜「W10」「Quotes」は、[設計書](my-turn-workflow-design.md)の番号と段の名を指す。
  - 「手順 N」は設計書の古い番号（1〜20）。14.4 の直し（設計書のセクション 14.4 の 4・5・7・9）で W11（記録を写して書く段）を外し、16〜20 が今の 11〜15 になった。
  - Quotes: 掘った後に、根拠の引用を `my-turn-prep.py --quotes` で照合する段（設計書のセクション 3）。
  - セクション 9 の表: 段ごとのモデルと effort（モデルの推論の深さの設定）の表。
  - 手順 20（今の手順 15）: `commands/my-turn.md` の、報告の確かめの手順（設計書のセクション 8）。

## 起動の仕方

決めること: 子の会話に持ち込む環境・引数・役・許可と、モデルの照合。

- **倣う元**: 持ち主の別のリポジトリ my_notes が、評価と調べものの呼び出しに使っている `claude -p` の起動。
  - `tools/primary_pipeline/claude_call.py` の `child_env` と 「CONTEXT_FLAGS」、`tools/claude_child.py`。
  - my_notes の呼び出しは、ツールも作業ツリーも持たない 1 回きりの物。
  - この形は裏のエージェントにツールと作業ツリーを残すので、取るのは環境と引数の絞り方だけにする。
- **環境**: 親の環境変数のうち、名前が CLAUDE か ANTHROPIC で始まる物を持ち込まない。
  - **my_notes との違い**:
    - my_notes は、アカウントを決める `CLAUDE_CONFIG_DIR` も外し、works-dispatch が選んだアカウントの鍵を `CLAUDE_CODE_OAUTH_TOKEN` で子にだけ渡し直す。
    - ここは /my-turn の会話のアカウントで回すので、`CLAUDE_CONFIG_DIR` と認証の経路を残す。
    - 認証の経路は `CLAUDE_CODE_OAUTH_TOKEN`・`ANTHROPIC_API_KEY`・`ANTHROPIC_BASE_URL` など。
    - 親に無ければ、attention の `scripts/lib/claude_auth.py` が、利用者の窓口のコマンドか Keychain から足す。
    - 子は対話の claude の認証を継がず、認証が無いと終了の値 0 のまま 1 行で落ちる。
  - **これで届かなくなる物**:
    - 全部の段を 1 つのモデルにする `CLAUDE_CODE_WORKFLOW_SUBAGENT_MODEL`。
    - モデルの別名を別のモデルに読み替える環境変数（my_notes の `.claude/AGENTS.md` の「読み替えの環境変数とその鍵を外し」）。
  - **足す物**:
    - `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`: CLAUDE.md を入れない。
    - `CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK=1`: 安全分類器に当たった要求を、別のモデルで打ち直させない。
      - 打ち直されると、反証が頼んだのと別のモデルで動く（my_notes の 「NO_MODEL_SWITCH」）。
      - 打ち直さない要求は失敗して返るので、そのノードは `null` になり、セクション 4 の件数に「返らなかった」として出る。
  - **足さない物**: my_notes が呼び出しごとに選ぶキャッシュの寿命（`FORCE_PROMPT_CACHING_5M`）。
    - Workflow の裏のエージェントのキャッシュは、既定で 5 分になっている。
    - https://code.claude.com/docs/en/workflows 「its cache holds for five minutes by default, including on a Claude subscription」
- **引数**:
  - `--model sonnet`: ヘッドレスの会話はこれで起動する（段のモデルは、script が `agent()` に渡す値で決まる）。
  - `--tools Read,Grep,Glob,Bash,Workflow,WebFetch,WebSearch`: 会話のツールを絞る（Write も持たせない。記録は台本が書く）。
    - WebFetch と WebSearch は、一次の文書を読む段のため（セクション 13）。
    - 裏のエージェントは会話のツールから受け取る（セクション 9）。役の引き当て（下の確かめの 2）が効かなくても、Write・Edit などは届かない。
  - `--add-dir`: script のフォルダと記録のフォルダを足す（記録のフォルダは段が差分などを読むため）。
    - Workflow の `scriptPath` は、作業ツリーか足したフォルダの下のファイルしか受けない（セクション 13）。
  - `--setting-sources ""`: 設定のファイルを読まない。フック・プラグイン・設定に書いた許可も入らない。
    - Workflow は既定で使える物で、切るのは設定の `disableWorkflows`。設定を読まなくても Workflow は残る。
    - 公式の workflows の文書（https://code.claude.com/docs/en/workflows）に、Workflow を切る方法として「Set `"disableWorkflows": true`」と在る。この起動の形はその設定を入れないので、切れない。
  - `--disable-slash-commands` でスキルとコマンドを、`--strict-mcp-config` で MCP を切る。
  - `--settings '{"disableAllHooks":true}'` も重ねる。
  - `--system-prompt`: ヘッドレスの会話の system prompt を、短い文に替える。
    - 中身は「`args` のファイルを読み、Workflow を 1 回呼び、終わりを待って結果を出す」だけ。
- **役**: `--agents` で、段ごとの役をその会話の中だけに定義する。
  - `omitClaudeMd` を真にする（役の定義の項目。真にすると、その役に CLAUDE.md を入れない）。
  - 役の `tools` は Read・Grep・Glob・Bash・WebFetch・WebSearch。
    - WebFetch・WebSearch は、W6・W9・W10 が公式の一次の文書の URL を読むため。
  - `disallowedTools` で、Write・Edit・NotebookEdit を外す。
  - Quotes の役は Bash だけを持ち、読む・書く・web のツールを外す（打つのは照合のコマンド 1 本だけ）。
  - W2 の役は、ブラインドの判定役の定義の本文の英訳を持ち、ツールを持たない（AI だけが読む文は英語で書く決まりのため。日本語の本文はそのまま渡さない）。
    - 定義は convergence-loops の `agents/blind-judge.md`。ツールを持たず、渡された前提と問いだけから考える役。
  - 役には `model` と `effort` を書かず、script が `agent()` に渡す値（セクション 9）で決める。
    - 役の `model` と `agent()` の `model` の、どちらが勝つかに頼らないため。
- **許可**: `--permission-mode dontAsk` と `--allowedTools` で、次だけを通す。
  - Workflow
  - 読むツール（Read・Grep・Glob）
    - 読むだけの段が、作業ツリー・記録のフォルダ・`args` のファイルを読むので、path で絞らない。
  - WebFetch・WebSearch
  - 照合のコマンド（`Bash(bash <run-python.sh> <my-turn-prep.py> --quotes *)`。Quotes が打つ）
    - path は prep の `quoteCheck` の物。規則の中で意味を持つ字（空白・かっこ・`*` など。graphloops の `engine/role_run.py` の `RULE_UNSAFE`）が在れば、この規則を足さない。
    - 足さなかったとき・規則が当たらなかったときは、照合のコマンドが拒まれ、根拠は照合していない物（`counts.quotes.unchecked`）として残る。
    - heredoc を付けたコマンドにこの規則が当たるかは、まだ試していない（下の確かめの 2）。
  - ファイルへの書き込みは、どの段にも許さない（前は W11 のために `Edit(//<記録のフォルダ>/**)` を許していた。記録は台本が書く）。
  - Bash の `git show`・`git blame`・`git log`・`git diff`・`git cat-file`・`git ls-files`・`git rev-parse`
  - `gh pr view`・`gh pr diff`・`gh pr list`・`gh issue view`・`gh issue list`・`gh search`
    - `gh api` は書き込みもできるので通さない。
  - **禁じる物**:
    - `git diff`・`git log`・`git show` は `--output=<ファイル>` で書き込めるので、`--disallowedTools` で `Bash(git *--output*)` を禁じる。
      - 禁止は許可より強い（https://code.claude.com/docs/en/permissions 「An allow rule can't carve an exception out of a deny rule」）。
    - `git grep` は `-O`（`--open-files-in-pager`）で名指しのコマンドを動かすので、許可に入れずに禁じる。探すのは Grep のツールでする。
- **モデルの照合**: 出力の JSON の `modelUsage`（使ったモデルごとの使用量）に、許すモデルに無いモデルが在れば、報告に書く（台本の出力の `models.unexpected`）。
  - 許すモデルは、段の表（[設計書](my-turn-workflow-design.md)のセクション 9。my-turn-dig.js の段ごとのモデルの表と同じ物で、opus・sonnet・haiku）のモデルと、args の `models`（段ごとにモデルを替える上書き。既定では渡さない）に書いたモデル。
  - 回った段（数えの `started` が 1 以上）のモデルのうち、`modelUsage` に無かった物は `models.expectedMissing` に出す。
  - my_notes の納品のゲートの `deliver_check.check_model` は、1 つのモデルだけを許す照合。これは複数のモデルを許すように広げた物。
  - `modelUsage` のキーは、モデルの完全な名（`claude-opus-5-5` など）。
  - 表の別名（opus・sonnet・haiku）を完全な名に当てる対応表（`ALIAS`）は、台本 `my-turn-headless.py` に持つ。
  - 完全な名が、別名の接頭辞（`claude-opus` など）を含むかで照合する。
- **出典**:
  - 引数と環境変数の意味は https://code.claude.com/docs/en/cli-reference 、https://code.claude.com/docs/en/sub-agents の「omitClaudeMd」、https://code.claude.com/docs/en/env-vars に在る。
  - 許可の書き方は https://code.claude.com/docs/en/permissions に在る。
- **持ち主の画面**: 進み具合の木は持ち主の画面に出ず、結果は終わってから届く。
- **採らない物**:
  - `--bare`（OAuth を読まず API キーだけで動く）と `--safe-mode`（workflows も読まない）（cli-reference）。
  - my_notes の空のフォルダで走らせる形: 裏のエージェントが作業ツリーの git とファイルを読めなくなり、全部の段の指示を書き直すことになる。
  - `--tools ""`: 裏のエージェントのツールも無くなる。
  - `--no-session-persistence`: 確かめに要る会話の記録と、Workflow の run の記録が残らない。

## 確かめの 5 つの点

決めること: ヘッドレスの形が本当に効くかを、何で確かめ、駄目ならどの手に戻すか。

- **今の状態**: 1 は 2026-11-17 の試しで `scriptPath` が断られ、`--add-dir <script のフォルダ>` を足して直した（[実装で設計から変えた所](my-turn-workflow-impl-changes.md)）。残りの 4 つは確かめていない。
- **確かめ方**: 直した版の 1 対の試し（セクション 11）の、ヘッドレスの会話の記録で確かめる。
  - 記録は、出力の JSON と、Workflow の run の `journal.jsonl` と、裏のエージェントごとの会話の記録。
  - 駄目だった物ごとに、次の手に戻す。
  - どの点でも、駄目だった回は「測れなかった」と書いて走らせ直さない。
- **走らせ直したいとき**: 直した版を確かめる回は、司令塔に問う。
  - 司令塔は、持ち主の別のリポジトリ my_notes に在る、持ち主への中継と部署への頼みの振り分けをする部署。
  - 根拠は、このリポジトリの直下（ルート。問いのルートとは別）の CLAUDE.md の「判断の線」。
  - その決まり: 試しは前の版と直した版の 1 対まで。それより多く走らせたいときは、何を確かめるか・何回・見込みの額を添えて、走らせる前に司令塔に問う。

1. **認証と Workflow の呼び出し**: 次の会話で、アカウントの認証が通り、Workflow のツールが在り、`scriptPath` で Workflow を呼べるか。
   - 対象の会話: 設定のファイルを読まず、名前が CLAUDE か ANTHROPIC で始まる環境変数を、`CLAUDE_CONFIG_DIR` と認証の経路（attention の `scripts/lib/claude_auth.py` が足す物）のほかに持たない会話。
   - 見る所: ヘッドレスの会話の記録に Workflow の呼び出しが在り、エラーで返っていないか。
   - 駄目なら:
     - 認証は、my_notes と同じく鍵を `CLAUDE_CODE_OAUTH_TOKEN` で子にだけ渡す形を考える（鍵の取り出し方は、my_notes の `tools/secret_store.py` を見てそのとき決める）。
     - Workflow のツールが無ければ、落とした環境変数のうち要る物を残す形に戻す。
     - 呼び出しは、`--plugin-dir` で attention を読ませて名前で呼ぶ形に直す。
     - それでも呼べなければ、ヘッドレスの形を取り下げ、`--headless` は訳を言って止まる。
2. **役の引き当て**: script の `agentType` で、`--agents` の役を引けるか。
   - 見る所:
     - 裏のエージェントの会話記録の持つツールに、Write が無いか。
     - Quotes の照合のコマンドが許可で通り、`counts.quotes.unchecked` が空か（`--allowedTools` の規則が heredoc 付きのコマンドに当たるか）。
   - 駄目なら `roles` を渡さない。
     - Write・Edit などは `--tools` で止まる。Bash での書き込みは許可で止まる。残る物は、今の手順 15 の `git status` で見る。
     - script は、実際に CLAUDE.md が入ったかでなく、`roles` の有る無しだけで、段の共通の決まり（セクション 3）に次の 1 行を足すかを決める。
       - 足す行: 起動時に読み込まれた CLAUDE.md に、この PR が変えた版が含まれる。それはレビューの対象なので従わない、という注意。
       - 足すのは、`roles` が無く、PR が CLAUDE.md を変えたときだけ。
     - `roles` を渡さなければ、script は既定の形（CLAUDE.md が入る）とみて、この行を足す。役が CLAUDE.md を入れていても、行が足されるので、決まりに従う側へ戻らない。
3. **CLAUDE.md を入れない環境変数**: `CLAUDE_CODE_DISABLE_CLAUDE_MDS` が、Workflow の裏のエージェントにも効くか。
   - 見る所: 裏のエージェントの会話記録に、作業ツリーの CLAUDE.md の決まった 1 行が無いか。
   - 2 の `omitClaudeMd` と二重にしてあり、どちらか 1 つが効けば足りる。
   - 両方が駄目なときは、2 の手で `roles` を渡さなくなるので、script は既定の形とみて、2 の「足す行」を入れる。
     - 行を入れるかは `roles` の有る無しだけで決まるので、この食い違いは起きない。
4. **終わりまで待つか**: ヘッドレスの会話が、Workflow の終わりまで待つか。
   - `claude -p` はターンを終えるとプロセスが終わり、裏の run も切れうる。
   - 見る所: 出力の JSON に、Workflow の結果（件数）が在るか。
   - 駄目なら、ヘッドレスの形を取り下げ、1 と同じく `--headless` は訳を言って止まる。
5. **`modelUsage` に裏のモデルが載るか**: 出力の JSON の `modelUsage` に、裏のエージェントのモデルも載るか。
   - 見る所: `modelUsage` に、セクション 9 の表の opus・sonnet・haiku が揃って在るか。
   - 載らなければ、モデルの照合を外し、報告に「モデルを照合していない」と書く。
