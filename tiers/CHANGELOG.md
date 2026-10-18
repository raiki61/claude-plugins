# 変更の記録（tiers）

tiers（`/tiers:check` スキルと `bin/tiers`）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]

### Changed

- README の `--config-dir` の説明を、段ごと（段 0 はプラグインの控えの置き場、段 2 は herdr の連携）の箇条書きに分け、project の範囲・herdr 0.9.3 の `integration status` の行の形と 4 つの状態を書き足した。

## [0.8.0] - 2026-10-19

### Added

- `--config-dir <フォルダ>` を足した。フォルダは、アカウントごとの Claude Code の設定のフォルダ（`CLAUDE_CONFIG_DIR` に渡す物。例: `~/.claude-p2`）で、繰り返して複数渡せる。渡したフォルダごとに、次を点検に足す（段は `--tier` で選ぶ点検の範囲で、段 0 は Claude Code、段 2 は herdr まで）。
  - 段 0: 入れたプラグインの控え（`plugins/installed_plugins.json`）の各項目の置き場（`installPath` のフォルダ）が在り、前の版の印（`.orphaned_at`。この印の付いた置き場は Claude Code が 14 日で消す）が付いていないか。消えた・消える置き場を指す項目は足りない物として出し、その項目を外すコマンド（`claude plugin uninstall`）を添える。きっかけは、2026-10-18 に `~/.claude-p2` で、消えた gates 0.7.0・attention 0.10.1 を指す project の範囲の項目が残っていたこと。
  - 段 2: herdr（端末を作業ごとに分け、中の AI の会話を外から操作するツール）の Claude Code の連携が今の版で入っているか。そのフォルダを `CLAUDE_CONFIG_DIR` にして `herdr integration status` を打ち、`claude` の行を読む。
  - 渡したフォルダが無ければ、足りない物として出す。
  - `claude` の行の形や状態の字が知らない物なら、合格にせず「読めない」として足りない物に出す。
- `--config-dir` を渡さなければ、点検の中身は 0.7.0 と同じ。

## [0.7.0] - 2026-10-19

### Changed

tiers は、プラグインが要る外のツールがこの PC にそろっているかを点検するプラグイン。段は、点検するツールの組を少ない方から並べた段階で、段 0 は Claude Code だけ、段 2 は herdr（端末の画面を作業ごとに分けて Claude Code の会話を並べるツール）とアカウントの起動コマンドまで。下の「足りない」は、点検の結果でその項目を足りない物として出し、終了コードを 1 にすること。

- 段 0 で、Claude Code にログインしているかも見る。見るのは `claude auth status --json` が返す JSON の `loggedIn`。前は `claude --version` が通るかだけを見たので、ログインが切れていても段 0 はそろっていると出した。段 2 の起動コマンドも、`claude` 以外はそのアカウントでログインしているかを見る。`claude auth status --json` の返した字が JSON として読めないときも、足りないと出す。
- herdr の server が動いているかを、`herdr status server --json` が返す JSON の `running` で見る。前は、人が読むための出力の「status: running」の行を正規表現で探していた。返した字が JSON として読めないときは、読めなかったことと終了コードを出し、足りないと出す。

## [0.6.0] - 2026-10-19

### Changed

- 出力と文書の「起動方法のコマンド」を「起動コマンド」にした（点検の項目の名前も変わる。例: `段 2 起動コマンド claude`）。ほかの文も IT の定着語にした。

## [0.5.4] - 2026-10-18

### Changed

- README を英語の 1 版に書き直した（日本語の版は置かない）。スキルとコマンドの名前・説明・本文は日本語のまま。決めは根の docs/readme-language.md。

## [0.5.3] - 2026-10-17

### Fixed

- `plugin.json` に作者（`author`）を書いた。Claude Code の公式の検査（`claude plugin validate`）の警告「No author information provided」が消える。説明は marketplace の項目から外し、`plugin.json` の 1 か所にした（`/plugin` の画面に出る文は変わらない）。

## [0.5.2] - 2026-10-17

### Fixed

- `docs/design.md` の依存の範囲の節が「範囲は依存先の git のタグで解く」とだけ書いていた。同じ marketplace の相対パスの依存はタグが無くても今の写しで入り、範囲は読み込むときに確かめる（Claude Code の文書 Plugin dependencies）ことを書いた。

## [0.5.1] - 2026-10-17

### Fixed

- `lib/tiers_check.py` の頭の注が、herdr（段 2 で点検する、端末を作業場とペインに分けて並べる道具）が足りないときに出す案内の根拠に、持ち主（このリポジトリの作者）の公開していないノートを指したまま、文も途中で切れていた（0.4.2 で `docs/design.md` だけ直していた）。herdr v0.9.5 の文書とソースに拠ることと、URL の在り処（`docs/design.md` の「段 2 の案内」の節。herdr の入れ方・起こし方・Claude Code との連携の案内を、出典の URL 付きで並べる）を書いた。
- Python が見つからない形を作る試験が、Ubuntu の CI では `/usr/bin` の python を見つけて落ちていた。PATH に sh だけを置いたフォルダを渡す。

## [0.5.0] - 2026-10-17

### Changed

- 文書だけの直し: plugin.json と marketplace の説明の「各プラグインがこれに依存する」を、今つないでいるのは works-dispatch だけ、に合わせる。振る舞いは変わらない。

## [0.4.4] - 2026-10-17

### Fixed

- 段 2 の「herdr の server が動いていない」に、どこの socket を見たか（`herdr status server` の `socket:` の行）を添える。HOME や設定の置き場が違うと、別の所の server を見ていることがある。

## [0.4.3] - 2026-10-16

### Fixed

- Windows で `bin/tiers` が動かなかった。頭の `#!/usr/bin/env python3` が、Python を入れていないと Microsoft Store へ誘う代わりの物に当たっていた。`bin/tiers` を sh と Python の両方で読める台本にし、sh で起こされたときは `python3`・`python`・`py -3` の順に、実際に起きる物で起こし直す（Python から起こす形はそのまま）。起こせる物が無ければ、直し方（設定 → アプリ → アプリ実行エイリアス で切る）を出す。README の「要る物」にも書いた。
- README の「段」に、使う側のプラグインが段 1 の gh を要らない使い方を持つときは、その点検の側で外して見ることを書いた（works-dispatch の `--check` の例）。

## [0.4.2] - 2026-10-16

### Fixed

- `docs/design.md` の「世間の形の調べ」と、段 2 の案内の herdr の根拠が、持ち主の公開していないノートのリポジトリを指していた。読んだ原典（Claude Code・Agent Skills・MCPB・gh・VS Code・Neovim・flutter・Homebrew・npm・Debian・Python の文書と、herdr v0.9.5 の文書とソース）の URL に替えた。

## [0.4.1] - 2026-10-16

### Fixed

- `docs/from-other-plugins.md` の、リポジトリの checkout から走らせるときに探す `tiers/bin/tiers` の場所を、「同じ checkout の中で自分のプラグインのフォルダと並ぶ所（例: `works-dispatch/` から見て `../tiers/bin/tiers`）」と書き直した。前は「隣の」とだけ書き、自分のリポジトリと並ぶフォルダとも読めた。

## [0.4.0] - 2026-10-16

### Changed

- README を初めての人向けに書き直した。頭に「何ができるか」「要る物」「5 分で試す」を置き、決めたことと試して確かめたことは `docs/design.md` に、ほかのプラグインからつなぐ形は `docs/from-other-plugins.md` に移した（中身は消していない）。

## [0.3.0] - 2026-10-16

### Changed

- README が名指す会社の形（部署の役と本流に入れる決まりを書く `.claude/company.toml`）の設計の文書を、本流に入れた `docs/specs/2026-10-16-company-shape-design.md`（リポジトリの根）に替えた。前は枝 `docs/company-shape` にしか無く、本流を clone した人は辿れなかった。

## [0.2.1] - 2026-10-16

### Fixed

- `/tiers:check` のスキルと README の段 2 の案内の説明を、初めての人が推測せずに読める形に直す（案内は足りない項目にだけ出ること、足りない項目は全部まとめて見せること、Windows の zip の中の ConPTY の実行時のファイル、`herdr status server` の出力の形の前提）。

## [0.2.0] - 2026-10-16

### Added

- 段 2（herdr と、アカウントの起こし方の命令）で足りない物に、初めての人が自分で準備するための案内を付ける。人の読む形は「案内:」の下に、`--json` は各項目の `guide`（行の並び。足りない項目だけが持つ）に同じ物を出す。`--json` の形の版 `schema` は 1 のまま（欄を足すだけで、今の呼び手はそのまま動くため）。
  - herdr が無い: OS ごとの入れ方の補い（Windows は WSL を通さないネイティブで一般提供、Windows の ARM64 は x86_64 の版をエミュレーションで動かす、エンドポイントのセキュリティが PowerShell のインストーラを止めたときのコマンドプロンプトでの入れ方、手で落とす zip は `herdr.exe` だけを写さずフォルダごと置く（同じフォルダに在る、Windows の疑似端末の仕組み ConPTY の実行時のファイルが要る）。Linux・macOS は置き場 `~/.local/bin` と、ほかの入れ方 Homebrew・mise・Nix）と、Claude Code の連携 `herdr integration install claude`。
  - herdr の server が動いていない: herdr を初めて起こしたときに herdr が出す初回の案内から連携を入れられることと、連携の入れ方。
  - 起こし方の命令（アカウントごとに Claude Code を起こすシェルの命令。`--launcher` で渡す）が見つからない: アカウントが 1 つなら起こし方の命令は要らないことを先に書き、アカウントごとに Claude Code の設定のフォルダを分けて、そのフォルダを環境変数 `CLAUDE_CONFIG_DIR` に入れて起こす関数か別名を、bash・zsh・PowerShell で示す（名前とフォルダは例）。

### Fixed

- Windows で、PowerShell の `$PROFILE` に書いた起こし方の関数を見つけられず、足りない物と言っていた。起こし方の命令が PATH の上に無ければ、PowerShell に、命令の有無を調べる `Get-Command` で聞く（pwsh が入っていれば先に聞き、見つからなければ Windows PowerShell にも聞く。`-NoProfile` を付けずに起こすので `$PROFILE` を読む）。

## [0.1.1] - 2026-10-16

### Fixed

- 試験の置き場 `tiers/tests` をパッケージにしない（`__init__.py` を消す）。works-dispatch の試験と同じ 1 回の pytest で回すと、どちらも `tests` というパッケージになってぶつかり、1 件が読み込めなかった。unittest は `-s tiers/tests` だけで回す。

## [0.1.0] - 2026-10-16

### Added

- 要る道具の段ごとの点検 `tiers --tier N [--launcher 命令 ...] [--json]`。段 0: Claude Code、段 1: gh（入っているか・ログイン済みか）、段 2: herdr（入っているか・動いているか）とアカウントの起こし方の命令、段 3: Archon。足りない物と、OS ごとの入れ方を返し、何も入れない。
- 人が同じ点検を走らせる `/tiers:check` スキル。
