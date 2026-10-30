# 変更の記録（tiers）

tiers（プラグインが要る外のツールが PC にそろっているかを点検する Claude Code のプラグイン。`/tiers:check` スキルと `bin/tiers`、0.9.0 からは statusline も持つ）の版ごとの、利用者に効く違いを新しい順に並べる。形は [Keep a Changelog 1.1.0](https://keepachangelog.com/ja/1.1.0/) に従い、版の番号は [Semantic Versioning](https://semver.org/lang/ja/) の形（x.y.z）で振る。

版の出し方（この記録を書き足す段。git の tag は作らない）は、リポジトリのルートの `docs/releasing.md` に在る。

## [Unreleased]

## [0.13.0] - 2026-10-30

### Changed

- `lib/tiers_check.py` で、ほかのモジュールに在るファイルの読み込みを呼ぶようにし、同じ文を作る分かれ道を 1 つにまとめた。`statusline/statusline.sh` で、jq の出力の 3 行を 1 回で読むようにし、書いてすぐ上書きされる代入と、通らない検査を消した。利用者の操作と出力は変えていない（頼み 486c02）。

## [0.12.1] - 2026-10-26

### Fixed

- `bin/tiers`・`bin/tiers-settings`・`bin/tiers-statusline` の頭が Python を選ぶとき、`python3`・`python` の後、`py -3` の前に、`python3.20` から要る版（`tiers`・`tiers-settings` は `python3.8`、`tiers-statusline` は `python3.11`）までの版の付いた名前を新しい順に試すようにした。前は、要る版以上の Python が `python3.14` のような版の付いた名前でだけ PATH に在り、PATH の `python3` がそれより古いとき、入っている Python を見つけられずに止まっていた。uv で入れた Python はこの形になる。選べないときの 1 行には、試した名前の範囲と、入れてあるのに見つからないなら入れた場所を PATH に足すことを足した。今動いている機械で選ばれる Python は変わらない（同じ決まり: リポジトリの `docs/standards/cross-os.md` の決まり 1）。

## [0.12.0] - 2026-10-26

### Changed

- statusline の PR の番号と題の控えの鍵を、0.11.1 の `cksum` でなく Python の `hashlib` で作るようにした（作業場とブランチの SHA-1 の頭 16 桁）。BSD と GNU で違いうる外のコマンドに頼らず、Python の標準ライブラリに寄せる（持ち主の方針 2026-10-26。リポジトリのルートの `docs/standards/cross-os.md` の決まり 2）。鍵は 0.11.0 までの `shasum` の鍵と同じ値に戻るので、0.11.0 から上げた PC では PR を取り直さない。`python3` が無いなどで鍵が作れないときは、ほかのブランチの PR を出さないよう、PR を出さない。

## [0.11.1] - 2026-10-26

### Fixed

- statusline の PR の番号と題の控え（`${TMPDIR:-/tmp}/herdr-pr-<鍵>`）の鍵を、`shasum` でなく `cksum`（POSIX のコマンド）で作るようにした。`shasum` は POSIX に無く、Debian の slim などの最小のイメージでは入っていない（2026-10-26 に `python:3.14-slim` で確かめた）。無いと鍵が空になり、どのブランチも同じ控えを読むので、ほかのブランチの PR の番号と題を黙って出していた。鍵は CRC とバイト数でできていて、長さの違うブランチどうしはぶつからない。鍵の形が替わるので、入れた後に 1 回だけ PR を取り直す（前の形の控えは一時の置き場に残るが、読まれない）。
- 「⧖ バックグラウンド作業中 N 本」の数が、Linux で `~/.local/share/claude/versions/<版>` を直に起動した会話で 0 になっていたのを直した。会話の Claude を探すのに、処理の名前（`ps -o comm=`）がパスを含む形（`*/claude/versions/*`）を見ていたが、Linux の名前はパスを持たず版の数字（例: `2.1.302`）だけになる。名前で当たらなければ、実行ファイルのパス（`/proc/<pid>/exe`）で見るようにした（2026-10-26 に Linux のコンテナーで、前の形が当たらず、直した形が当たるのを確かめた）。
- `tiers-statusline` を Windows で打つと、入口で「macOS と Linux だけで動く」と 1 行出して止まる（終了コード 1）ようにした。前は、リンクを張る所で traceback を出して落ちるか、Windows では動かない statusLine を `settings.json` に書いていた。statusline は bash・ps・jq で動くので、Windows では WSL の中の Claude Code で打つ。
- `bin/tiers`・`bin/tiers-settings`・`bin/tiers-statusline` の入口が、`python3`・`python`・`py -3` のうち起動できる物を、版を見ずに採っていたのを直した。`tiers` と `tiers-settings` は 3.8 以上、`tiers-statusline` は 3.11 以上（上書きを TOML として確かめる `tomllib` が 3.11 から）の物だけを採り、無ければその版を名指して止まる。前は、`python` が Python 2 や古い 3 の PC で、構文の誤りや `tomllib` の import の失敗で落ちていた（3.8〜3.10 で `tiers` と `tiers-settings` が動き、3.10 で `tiers-statusline` が止まるのを 2026-10-26 に確かめた）。

## [0.11.0] - 2026-10-23

### Added

- 段 2（`tiers --tier 2`）の点検に、起動コマンドごとのアカウントの `settings.json` の `permissions.deny` に `"AskUserQuestion"`（Claude が選択肢の画面で問うツール）があるかを足した。項目の名前は「選択肢の画面で問うツール（<フォルダ>）」で、feedbackDrafts と同じく、フォルダは `auth status --json` の `configDirectory` と `--config-dir` から引き、点検は何も書き換えない。Claude がこのツールで問うと、その会話は窓を開いてキーを押すまで進まず、ほかの会話からは答えられない（2026-10-23、持ち主の勤め先のリポジトリ guided-resolver で、works-dispatch が開いた会話が止まった）。括弧付きの `AskUserQuestion(...)` は通さない。`permissions` が JSON のオブジェクト（`{...}`）でない（並びや文字など、型が違う）か、`deny` が並び（`[...]`）でないときは、`tiers-settings setup` が書けないので、点検はその項目の直し方の 1 行目に「その形を手で直してから」を出す。中身の在る `permissions` や空の `permissions` は止めず、`deny` を足す。

### Changed

- `tiers-settings setup` が、`feedbackDrafts` に加えて `permissions.deny` の末尾に `"AskUserQuestion"` を足すようにした（既に在れば触らず、ほかの項目は消さない。前の `settings.json` は今までどおり `.bak` で 1 つ残す）。`permissions` か `deny` の型が違う（上と同じ）`settings.json` には何も書かずに止まる（終了コード 1）。中身の空の `settings.json` を {} と同じに扱うようにした（点検と同じ扱い）。
- 起動コマンドの `auth status --json` に `configDirectory` が無いときの項目の名前を、「フィードバックの下書き（<コマンド>）」から「アカウントの設定（<コマンド>）」にした（2 つの設定の両方に係るため）。README の「Feedback drafts」は「Account settings」の下に移した。

## [0.10.0] - 2026-10-23

### Added

- 段 2（`tiers --tier 2`）の点検に、起動コマンド（`--launcher` で渡す、アカウントごとに Claude Code を起動するコマンド）ごとのアカウントの `settings.json` に `"feedbackDrafts": "off"`（Claude がフィードバックの下書きをためない設定）があるかを足した。Claude が Claude Code の組み込みの SendFeedback のツールで下書きをためた会話は、`/exit` の前に送るか捨てるかの確認で止まる。そのため、Claude Code の会話を `/exit` で閉じて回る works-dispatch（このリポジトリの別のプラグイン）が、その会話を閉じられなかった（2026-10-23 に、持ち主の勤め先のリポジトリ guided-resolver で起きた）。アカウントの設定のフォルダは、段 2 がそのアカウントのログインを確かめるのに打つ `<起動コマンド> auth status --json` の答えの `configDirectory` から引く（無ければ足りない物として出す）。`--config-dir` で渡したフォルダも見る。無ければ、書くコマンドと、手で書く場所を出す。点検は今までどおり何も書き換えない。
- 書く側のコマンド `tiers-settings setup [--config-dir フォルダ ...]` を足した。`--config-dir` で渡した各フォルダ（省けば `CLAUDE_CONFIG_DIR` のフォルダ、それも無ければ `~/.claude`）の `settings.json` に `"feedbackDrafts": "off"` を書き、前の物は `tiers-statusline setup` と同じく `settings.json.bak.<日時>-tiers` の名前で隣に残す。段 2 の点検でこの設定が足りないと出たら、利用者はこのコマンドを打つ（または、そのアカウントの `/config` で Claude-drafted feedback を off にする）。README の「Feedback drafts」。

## [0.9.2] - 2026-10-20

### Fixed

- 新しく作った設定のフォルダで、`settings.json` の `statusLine` が tiers のリンク（`<設定のフォルダ>/plugins/data/tiers-raiki61/current`）の下を指しているのにリンクが無く、状態の行が出なかった（ほかのフォルダから写した `settings.json` のパスを書き換えたときに起きる。`tiers-statusline setup` を打てば直ったが、打つ手が要った）。SessionStart のフックが、リンクが無く statusLine がそのリンクの下を指すときはリンクを作る。statusLine がほかを指すフォルダには今までどおり作らない。

## [0.9.1] - 2026-10-20

### Fixed

- 試験だけの直し（tiers の動きは変わらない）: Windows の CI で赤だった 2 つを直した。`tests/test_tiers_check.py` の試験の偽物（Probe の代わり）がパスを `/` 区切りの字のまま比べていて、tiers が `os.path.join` で作る `\` 区切りのパスと当たらず、段 0 の点検（Claude Code が入れたプラグインを書き留めるファイル `plugins/installed_plugins.json` が、消えた置き場を指していないか）が 1 件も赤を出さなかった（偽物の側で `/` と `\` を同じに見るようにした）。`tests/test_statusline.py` は、子プロセスの出力を読む所に `encoding="utf-8"` を、直に起動したときの標準出力に UTF-8 への切り替えを足した（Windows の既定の文字コードで日本語が落ちないように）。

## [0.9.0] - 2026-10-19

### Added

- statusline を足した（`statusline/`。使うかは利用者が決め、`tiers-statusline setup [--config-dir フォルダ ...]` で入れる）。herdr（端末を作業場とペインに分けて並べ、中の AI の会話の状態をサイドバーに見せるツール）の中では、裏の処理（`run_in_background` の Bash・Monitor・裏で立てたサブエージェント）を待つ間、画面の下に「⧖ バックグラウンド作業中 N 本」を出し、herdr が会話の状態を画面の字から見分ける判定ルールに、手元の上書き（`~/.config/herdr/agent-detection/claude.toml`）で規則を 1 つ足し、その会話を作業中に見せる。持ち主の手元の `~/.claude/statusline.sh`・`herdr-bg-hold.sh`・herdr の上書きを移した物。
  - `setup` は、アカウントごとの `settings.json` の `statusLine` を書き（前の物は `settings.json.bak.<日時>-tiers` で残す）、herdr の上書きを作る。プラグインは statusLine を入れられないので、道具で書く。
  - herdr の上書きは、herdr が配ったルールの後ろに足す規則（`statusline/claude-rule.toml`）を足して作り、配られたルールが替わると statusline が `tiers-statusline refresh` を起こして作り直す。手で写した上書きは herdr の配り直しを隠し続ける（手元の上書きは 2026.09.11.1 のままで、配られた 2026.10.11.1 の規則が効いていなかった）。
  - SessionStart のフックを足した。会話を始めるたびに `${CLAUDE_PLUGIN_DATA}/current` を今の版へのリンクに張り替える（statusLine はこのリンクの下を指すので、版を上げても書き直さない）。会話に字は出さない。
- 段 2 の点検（`--config-dir` を渡したとき）で、statusLine が tiers の statusline を指すフォルダだけ、リンクと herdr の上書きがそろっているかを見る。

### Changed

- スキル `check` に `disable-model-invocation: true` を付け、常に載る文脈を 0 にした（前は説明が毎回の会話に載った。`claude plugin details` の見積もりで約 47 トークン）。人は今までどおり `/tiers:check` で打てる。会話からは呼べなくなったので、会話の中の点検は Bash のツールで `tiers --tier N` を打つ。`claude plugin details` の見積もりはこの指定を見ないので、0 と出ない（約 30 トークンと出る。実際に載っているかは会話の記録の `skill_listing` の行で見る）（docs/design.md の「常に載る文脈を 0 にする」）。

## [0.8.1] - 2026-10-19

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
