# プラグインをまたぐ標準

この marketplace（リポジトリのルートの `.claude-plugin/marketplace.json`）が配るプラグインの、書き方と作りの揃え方を決めた所。
読むのは、プラグインを直す各担当（直す前に、下の一覧から当たる標準を開いて合わせる）と、標準の担当（次の回に、下の台帳でずれがどこまで片付いたかを知り、続きを頼む）。

「担当」「点検」などは、このリポジトリの会社の形（`.claude/company.toml`）が決める部署（受け持ちを持つ Claude Code の会話）の名前。頼むと受付番号が付き、頼み先の部署が受けて、済めば納品で返す。受け持ちは次のとおり。

- 見渡し: attention
- 見直し: convergence-loops・graphloops
- 割り振り: works-dispatch・tiers
- 点検: gates と、CI・ルートの `tests/`
- 説明書: ルートの README・CLAUDE.md・CONTRIBUTING.md など、プラグインをまたぐ文書
- 作業: 受け持ちの無い一度きりの直し
- 標準: この docs/standards/

決め方: 標準は Claude Code の公式の文書と、公式の検査のコマンド `claude plugin validate`（以下「公式の検査」）を正にして書く。手元の好みでは決めない。
公式に決まりが無い所だけ、このリポジトリの今の多数の形を標準にする。

対象: marketplace に載るプラグインのうち、works と works-factory を除く 6 つ（attention・convergence-loops・gates・graphloops・tiers・works-dispatch）。
works と works-factory は誰の受け持ちでもないので、標準の担当は見るだけで、直しを頼まない。
ただし[スキルの書き方](skill-authoring.md)は、持ち主の頼み（2026-10-18）で works と works-factory も対象にし、直しは一度きりの直しを受ける作業に頼む。

## 標準の一覧

- [配る形（plugin.json・marketplace の項目・README の入れ方）](plugin-manifest.md)
- [スキルの書き方（本文の長さ・別ファイルへの分け方・description）](skill-authoring.md)。対象は上の 6 つに加え works と works-factory も含む（標準の中の「対象」）
- [機械が読む値の受け渡し（構造で渡す・外のツールは機械向けの出力で読む・言語に依らないキー・黙って崩さない・自作も写しもしない）](machine-readable-values.md)。対象は上の 6 つに加えルートの `scripts/`・`tests/`

## 進め方（標準の担当がすること）

1. 起動されたら、この台帳の「ずれ」の続きを見て、main ブランチに入ったかを確かめて書き直す。
2. 各プラグインの今の作りを標準と見比べ、ずれの大きい順に 1〜3 個を選ぶ。
3. ずれの直しは、そのプラグインの担当に頼む。標準を機械で守らせる検査（CI・ルートの `tests/`）は点検に頼む。ルートの README・CLAUDE.md・CONTRIBUTING.md から標準を指す直しは説明書に頼む。
4. 頼んだ受付番号をこの台帳に書く。

## ずれの台帳

ずれの番号は「回-番号」（例: 1-2 は 1 回目の 2 つ目）。状態は 見つけた → 頼んだ（受付番号）→ 入った（commit）の順に進む。

### 1 回目（2026-10-17、受付 20261017-065611-6c364c）

前の回は無い（docs/standards/ はこの回に作った）。公式の検査（Claude Code 2.1.302）をリポジトリのルートと 6 つのプラグインに当てて、次のずれを見つけた。

- 1-1 plugin.json に author が無い（6 つとも。works・works-factory も同じ）。公式の検査が警告を出す。状態: 入った（対象のプラグインの全部）
- 1-2 description を plugin.json と marketplace の項目の 2 か所に持ち、convergence-loops・gates・graphloops は中身が違う。利用者の画面に出るのは marketplace の項目の方なので、plugin.json の方を直しても画面は変わらない。状態: 入った（対象のプラグインの全部）
- 1-3 README に入れ方の行が無い（attention・gates・graphloops）。公式の検査が助言を出す。状態: 入った（対象のプラグインの全部）

頼んだ受付（1-1〜1-3 をまとめて、受け持ちのプラグインごとに）:

- 見渡し（attention）: 20261017-070336-504bb8 → 入った（d6f91472）
- 見直し（convergence-loops・graphloops）: 20261017-070354-0f5cbe → 入った（febd3617）
- 割り振り（tiers・works-dispatch）: 20261017-070325-80831b → 入った（ae06fe0c。README の入れ方の行は元から在った）
- 点検（gates と、[配る形の標準](plugin-manifest.md)の決まり 2〜4 をルートの tests/ で見る検査。検査はほかの 3 件が main に入ってから）: 20261017-070322-aabbb8 → 入った（gates は a8f36daf、検査は 6b54d12b・a5b0ce1f）

1 回目の締め: 公式の検査に残る警告は、対象の外の works・works-factory の author だけ。2 つは誰の受け持ちでもないので頼む先が無く、標準の担当も直さない。誰かが直して標準を満たせば、ルートの検査が外す一覧から消すよう赤で知らせる。

見送ったずれ（1 回目）:

- コマンドの置き場が `commands/`（attention・convergence-loops・graphloops）と `skills/`（gates・tiers・works-dispatch）に割れている。公式の文書は `skills/` を勧めるが、「新しいプラグインには」の条件付きで、`commands/` も読み込む（[Plugin manifest reference の Standard layout](https://code.claude.com/docs/en/plugins-reference#standard-layout)「Prefer `skills/` for new plugins」）。移すと呼び出しの名前と振る舞いを確かめ直すことになるので、標準では新しく作る物を `skills/` にするとだけ決め、今ある物は移さない。
- 試験の置き場が、ルートの `tests/`（attention・convergence-loops・gates）とプラグインの中（graphloops・tiers・works-dispatch）に割れている。公式に決まりが無く、どちらも CI（`.github/workflows/test.yml`）から回るので、今は揃えない。

### 2 回目（2026-10-18、受付 20261018-005346-25a518）

[スキルの書き方の標準](skill-authoring.md)を作り、marketplace に載る全プラグインのスキルとコマンド 17 本の本文を測った。決まり 1（本文 5,000 字以下・500 行未満）を超えるのは 11 本。description（決まり 7）は 17 本とも 1,024 字以下（いちばん長い attention の catchup で 415 字）。

- 2-1 スキルの書き方の標準の決まり 1・4・5 を機械で見る検査が無い。状態: 頼んだ（点検 20261018-011005-129e80）
- 2-2 attention の catchup 18,615 字・whose-turn 7,532 字・what-am-i-doing 6,230 字。状態: 頼んだ（見渡し 20261018-011022-65db74）
- 2-3 convergence-loops の review-loop 41,438 字・firstread-loop 24,339 字（625 行）・doctor-loop 23,192 字・research-loop 21,620 字、graphloops の review-graph 35,018 字・research-graph 13,424 字。状態: 頼んだ（見直し 20261018-011038-156f7f）
- 2-4 works-dispatch の dispatch 57,001 字。状態: 頼んだ（割り振り 20261018-011052-5f6b13。並んで動く dispatch の層の分け方の点検 20261018-002923-983a64 にも足しで知らせた）
- 2-5 works の works 22,704 字。状態: 頼んだ（作業 20261018-011113-3952f3。works は受け持ちが無いので、持ち主の頼みに従って作業に回した）
  - 2026-10-19 の途中の納品（20261018-211411-c65522）: 本文は 4,942 字・79 行に縮んだが、まだ main に入っていない。初見読みのゲートが、別ファイルを SKILL.md の本文なしで読んで止めるため。ゲートの直しは点検に頼んである（20261018-211334-d8053f）。
  - 標準が追う物 1: 本文の余りは上限まで 58 字。次に本文へ足す物が出たら、削る所を標準が決める。
  - 標準が追う物 2: 上限を超えたスキルを外す一覧を見る検査（2-1）が入ったら、その一覧から works/skills/works を消す。
- 2-6 ルートの CLAUDE.md から標準を指していない。状態: 頼んだ（説明書 20261018-011057-6dc6b0）

標準の内の物: attention の my-turn・reflect、gates の coldread（4,962 字）、graphloops の intake、tiers の check、works-factory の works-factory（4,189 字）。

2-1〜2-6 は、標準が main に入った後（b1a21382）に頼んだ。納品が届いたら、次の回にここを「入った（commit）」に書き直す。

### 3 回目（2026-10-19、受付 20261018-204600-6563b9）

持ち主の頼み（「そういう感じで全体的に汚いところないかリファクタリングしよう。」）で、[機械が読む値の受け渡しの標準](machine-readable-values.md)を作った。6 つのプラグインとルートの scripts・tests をサブエージェント 5 本に読ませて洗い出し、構造で持つべき値を文から拾う・世間の解を自作する・黙って崩れる・言語や特定のツールに縛られる・同じ処理を写す、の 5 種類を 114 件見つけた（読み取り役の指摘で、各担当が直す前に確かめる）。プラグインごとの多い順にまとめて頼む。

- 3-1 attention: 会話の記録の置き場の名前の作り方が違い、`.herdr` を含む作業場で `/what-am-i-doing` が記録を見つけられない（今壊れている）。ほか、表示の文字列の末尾の一致で「自分に渡された」を決める・`@名前` の一致が緩い・gh の失敗を空の結果に見せる・種類を日本語の表示の語で持つ・git の出力を `-z` 無しで読む・同じ正規表現と diff の読み方の写し。状態: 頼んだ（見渡し 20261018-210609-f10955）
- 3-2 convergence-loops と graphloops: review-record.py の日本語の出力の行で review-loop の行き先を決める・comment-ratio.sh の `scalars:` の行を読む・graphloops が `claude -p` で起動する子の会話（役）の答えを `--json-schema` 無しで受けて文から JSON を探す・前の回の印を日本語の添え書きで持つ・記録の列挙が日本語の値・子の会話の定義ファイル（agents/*.md）の frontmatter の自作の読み方（YAML のリストの形で、子に渡すツールが黙って空になる）・壊れた状態のファイルを空として読む。状態: 頼んだ（見直し 20261018-210618-4394cb）
- 3-3 gates とルートの tests: 初見読みのゲートが読み手の答えを日本語の見出しと「なし」の語で読む・フックの入力を読めないと通す・`except: pass` で状態の保存が黙って止まる・dest-gate の `owner_repo` の写し・tests/run.sh が YAML と frontmatter を行と正規表現で読み、日本語の決まった文で方針を見る。加えて、標準の決まり 3・4 を数で守らせる検査。状態: 頼んだ（点検 20261018-210622-72ff3f）
- 3-4 works-dispatch と tiers: 台帳（`log.jsonl`）の読めない行を黙って飛ばして位置を進める・行き詰まりを解く処理が例外を黙って捨てる・終了コードが日本語の理由の文字列の一致で決まる・部署の種類（常設か都度か）と、会社の形（`.claude/company.toml`）の役（担当・作業など）の既定の名前が日本語の値・`git config` を `-z` 無しで読む・`gh issue develop --list` の表を列で切る・自作の原子的な書き込みとロックが 6 か所と 5 か所。tiers は herdr の状態を人向けの出力で読み、Claude Code のログインを見ない。状態: 頼んだ（受付 20261018-210650-305f6d）。頼み先は my_notes の段取り。works-dispatch と tiers を受け持つ割り振りは、今は頼みを受けられずに止まっている（直しは受付 20261018-200403-0732ab）。そのため標準の担当は段取りに頼み、段取りが作業に回す。段取りは、持ち主のノートのリポジトリ my_notes の、部署へ頼みを配る部署。作業は、一度きりの直しを受ける部署。
- 3-5 ルートの scripts: `spread-plugins.py` の入力フィールドの判定が works-dispatch の直す前の写しで、割れている・成否を自分の出した日本語の行で決める・`shared-copies.py` と `terms.py` が読めないファイルを黙って数から外す・`claude_auth.py` がトークンの頭の形の違いを黙って捨てる。状態: 頼んだ（作業 20261018-210630-9cdb7f）

直さないと決めた物と訳は、標準の「直さないと決めた物」に書いた。
