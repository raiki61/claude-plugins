# プラグインをまたぐ標準

この marketplace（リポジトリの根の `.claude-plugin/marketplace.json`）が配るプラグインの、書き方と作りの揃え方を決めた所。
読むのは、プラグインを直す各担当（直すときに合わせる）と、標準の担当（次の回に、ずれがどこまで片付いたかをここで知る）。

決め方: 標準は Claude Code の公式の文書と、公式の検査の命令 `claude plugin validate`（以下「公式の検査」）を正にして書く。手元の好みでは決めない。
公式に決まりが無い所だけ、このリポジトリの今の多数の形を標準にする。

対象: marketplace に載るプラグインのうち、works と works-factory を除く 6 つ（attention・convergence-loops・gates・graphloops・tiers・works-dispatch）。
works と works-factory は誰の受け持ちでもないので、標準の担当は見るだけで、直しを頼まない。

## 標準の一覧

- [配る形（plugin.json・marketplace の項目・README の入れ方）](plugin-manifest.md)

## 進め方（標準の担当がすること）

1. 起こされたら、この台帳の「ずれ」の続きを見て、本流（main ブランチ）に入ったかを確かめて書き直す。
2. 各プラグインの今の作りを標準と見比べ、ずれの大きい順に 1〜3 個を選ぶ。
3. ずれの直しは、そのプラグインの担当に頼む。標準を機械で守らせる検査（CI・根の `tests/`）は点検に頼む。根の README・CLAUDE.md・CONTRIBUTING.md から標準を指す直しは説明書に頼む。
4. 頼んだ受付番号をこの台帳に書く。

## ずれの台帳

ずれの番号は「回-番号」（例: 1-2 は 1 回目の 2 つ目）。状態は 見つけた → 頼んだ（受付番号）→ 入った（commit）の順に進む。

### 1 回目（2026-10-17、受付 20261017-065611-6c364c）

前の回は無い（docs/standards/ はこの回に作った）。公式の検査（Claude Code 2.1.302）をリポジトリの根と 6 つのプラグインに当てて、次のずれを見つけた。

- 1-1 plugin.json に author が無い（6 つとも。works・works-factory も同じ）。公式の検査が警告を出す。状態: 一部入った（attention・convergence-loops・graphloops。残りは下の受付）
- 1-2 description を plugin.json と marketplace の項目の 2 か所に持ち、convergence-loops・gates・graphloops は中身が違う。利用者の画面に出るのは marketplace の項目の方なので、plugin.json の方を直しても画面は変わらない。状態: 一部入った（attention・convergence-loops・graphloops。残りは下の受付）
- 1-3 README に入れ方の行が無い（attention・gates・graphloops）。公式の検査が助言を出す。状態: 一部入った（attention・convergence-loops・graphloops。残りは下の受付）

頼んだ受付（1-1〜1-3 をまとめて、受け持ちのプラグインごとに）:

- 見渡し（attention）: 20261017-070336-504bb8 → 入った（d6f91472）
- 見直し（convergence-loops・graphloops）: 20261017-070354-0f5cbe → 入った（febd3617）
- 割り振り（tiers・works-dispatch）: 20261017-070325-80831b
- 点検（gates と、決まり 2〜4 を根の tests/ で見る検査。検査はほかの 3 件が本流に入ってから）: 20261017-070322-aabbb8

見送ったずれ:

- コマンドの置き場が `commands/`（attention・convergence-loops・graphloops）と `skills/`（gates・tiers・works-dispatch）に割れている。公式の文書は `skills/` を勧めるが、「新しいプラグインには」の条件付きで、`commands/` も読み込む（[Plugin manifest reference の Standard layout](https://code.claude.com/docs/en/plugins-reference#standard-layout)「Prefer `skills/` for new plugins」）。移すと呼び出しの名前と振る舞いを確かめ直すことになるので、標準では新しく作る物を `skills/` にするとだけ決め、今ある物は移さない。
- 試験の置き場が、根の `tests/`（attention・convergence-loops・gates）とプラグインの中（graphloops・tiers・works-dispatch）に割れている。公式に決まりが無く、どちらも CI（`.github/workflows/test.yml`）から回るので、今は揃えない。
