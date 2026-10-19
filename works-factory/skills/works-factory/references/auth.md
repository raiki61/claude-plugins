# 認証の道と「認証が無い」で止まった時

殻（このプラグインの `bin/works-factory`）が AI の役を起こす時に使う Claude の認証の選び方と、止まった時の直し方。

## ログインか keychain の項目で動く人

- 普段の `claude` と `gh` のログインのまま動く。Claude のアカウントを macOS の keychain の項目で選ぶ時は、`WORKS_FACTORY_KEYCHAIN_ITEM=<項目の名>` を付ける（値は表示も保存もしない）。
  - 毎回付けずに済ませるなら、使う Claude Code の設定の置き場の `settings.json` の `env` に `WORKS_FACTORY_KEYCHAIN_ITEM=<項目の名>` に当たる組を書く。Claude Code が Bash の子に渡すので、殻がそのまま拾う。
  - 殻が「認証が無い」で止まったら、`security find-generic-password -s <項目の名>` で項目が在るかを確かめる（`-w` を付けず、値を出さない）。項目の名を推して試さず、人に聞く。

## API キーで動く人

- キーを環境変数 `ANTHROPIC_API_KEY` に置いて起こす（`ANTHROPIC_AUTH_TOKEN` も同じく拾う）。殻は「認証は ANTHROPIC_API_KEY から拾う」と出して、そのキーで AI の役を起こす。
- 毎回付けずに済ませるなら、使う Claude Code の設定の置き場の `settings.json` の `env` に `ANTHROPIC_API_KEY` の組を書く（Claude Code が Bash の子に渡すので、Claude Code の中から殻を打つ時に効く。自分の端末から打つ時は環境に置く）。
- 上の `WORKS_FACTORY_KEYCHAIN_ITEM=<項目の名>` は付けない。付けると殻はその項目のログインを使い、`ANTHROPIC_API_KEY` を子から外す。API キーの入った項目を名指しても読めずに止まる。
- 今の殻は `settings.json` の `apiKeyHelper`（キーを出すコマンド）を読まない。`apiKeyHelper` だけで認証している人は「認証が無い」で止まるので、そのコマンドの出すキーを `ANTHROPIC_API_KEY` に置いて起こす。
- macOS で既定の設定の置き場（`~/.claude`）に Claude のログインが残っていると、キーが環境に無い時は止まらずにそのログインのアカウントで起こす。殻の出す「認証は … から拾う」の行で確かめる（`ANTHROPIC_API_KEY` を置けばキーが先に拾われる）。
- `apiKeyHelper` を殻が読む直しは raiki61/works-factory の issue #795（2026-10-20 の時点で未修正）。
