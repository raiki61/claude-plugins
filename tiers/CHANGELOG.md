# 変更の記録（tiers）

tiers（`/tiers:check` スキルと `bin/tiers`）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]

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
