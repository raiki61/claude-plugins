# 配る形の標準（plugin.json・marketplace の項目・README の入れ方）

プラグインの説明書き（`<プラグイン>/.claude-plugin/plugin.json`。以下 plugin.json）と、ルートの marketplace の一覧（`.claude-plugin/marketplace.json` の `plugins` の項目。以下 marketplace の項目）と、README の入れ方の行をどう書くか。
読むのは、プラグインを直す各担当と、この標準を機械で守らせる検査を書く点検。

## 決まり

1. **公式の検査で、対象の 6 つのプラグインの警告と助言を 0 にする。** リポジトリのルートで `claude plugin validate .` を打つ。works・works-factory は標準の対象の外なので、その 2 つの author の警告（一覧の plugins[4]・plugins[5]）は残り、警告 2 件の後に `✔ Validation passed with warnings` で終わる（2026-10-17 に実測）（標準の対象は [README](README.md) の「対象」）。
   ルートで打つと、marketplace の項目と、相対パスで載る各プラグインの plugin.json を一度に見る（[Create a marketplace の Problems that validation reports](https://code.claude.com/docs/en/plugin-marketplaces#problems-that-validation-reports)）。
   警告は読み込みを止めないが、公式は CI では `--strict` で警告を失敗にする道を用意している（[Plugin manifest reference の Validate the manifest](https://code.claude.com/docs/en/plugins-reference#validate-the-manifest)「Pass `--strict` to turn warnings into failures in CI」）。下の 2〜4 は、今の警告と助言を消すための個別の決まり。
2. **plugin.json に author を書く。** 形は `"author": { "name": "raiki61" }`（marketplace の `owner.name` と同じ）。
   公式の検査は author の無い plugin.json に警告を出す（同じセクション「a missing `version`, `description`, or `author`」）。
3. **description は plugin.json の 1 か所に書き、marketplace の項目には書かない。**
   - 両方に書くと、利用者の `/plugin` の一覧と詳細に出るのは marketplace の項目の方で、plugin.json の方は画面に出ない（[Marketplace reference の Display fields](https://code.claude.com/docs/en/plugins/marketplace-reference#display-fields)「For a field you set on the entry, users see the entry's value, even when `plugin.json` sets a different one.」）。2 か所に持つと片方だけ直して食い違い、直したのに画面が変わらない。
   - 項目に書かなければ plugin.json の値が出る（同じセクション「For a field the entry leaves unset, users see the `plugin.json` value.」）。この marketplace の項目は全部相対パスの source なので、入れる前の一覧でも plugin.json が読まれる（同じセクション「Before install, Claude Code can read `plugin.json` only for entries with a relative-path source」）。
   - version も同じ理由で plugin.json だけに書く（今も marketplace の項目には書いていない。両方に書くと plugin.json が勝ち、公式の検査が警告を出す。[Marketplace reference の Plugin entries](https://code.claude.com/docs/en/plugins/marketplace-reference#plugin-entries)）。
4. **README に入れ方の行を書く。** marketplace を足す行と、`<名前>@raiki61` で入れる行の 2 行（例は下）。
   公式の検査は、入れ方の行の無い README に助言を出す（`This README has no line that installs "<名前>" from a marketplace`）。助言は判定を変えないが、README を読んで入れる人が迷う所なので、警告と同じに扱う。

   ```
   /plugin marketplace add raiki61/claude-plugins
   /plugin install <名前>@raiki61
   ```

   シェルから打つ形（`claude plugin marketplace add …`・`claude plugin install …`）でもよい。今の README は tiers・works-dispatch がシェルの形、convergence-loops が `/plugin` の形で、どちらも公式の検査が入れ方の行と認める。
5. **新しく作るコマンドは `skills/<名前>/SKILL.md` に置く。** 公式は新しいプラグインに `skills/` を勧める（[Plugin manifest reference の Standard layout](https://code.claude.com/docs/en/plugins-reference#standard-layout)「Prefer `skills/` for new plugins」）。今 `commands/` に在る物は、`commands/` も読み込まれるので移さない。

## 守らせ方

公式の検査のコマンド `claude` は CI に無い（ルートの `tests/run.sh` の marketplace の検査の注記）。CI では、決まり 2〜4 をルートの `tests/run.sh` の検査（出力の印 `MANIFEST_STANDARD_OK`。2026-10-17 に点検が入れた、commit 6b54d12b）が同じ形に見る。works・works-factory はこの検査の外す一覧に載り、2 つが標準を満たすと検査が赤で知らせて、外す一覧から消させる。手元では、直した後にルートで `claude plugin validate .` を打って確かめる。
