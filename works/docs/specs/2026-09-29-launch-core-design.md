# 起動の殻の共通の口（launch.py）の設計（2026-09-29・下書き 1 版）

状態: **下書き 2 版**（持ち主の審査待ち）。1 版の後に先例（6 節）を調べ、受け方・出力の版・名前の柵・Python の起こし方・既定の表の形を直した。

## 平易版（3 行）

- works を起こす殻が 4 本（`use.sh`・`dogfood.sh`・`real-run.sh`・`archon.sh`）あり、起こす前の準備（認証・claude の場所・家・包み・入力・控え・表示）を殻ごとに写して持っている。写しはもう食い違っていて、直すたびに 3〜4 か所に手が要る。
- 準備を Python の部品 1 つ（`works/dev/launch.py`）に寄せ、殻はその部品を呼んで結果を使うだけにする。利用者が打つコマンドと手順書は変えない。
- 3 回に分けて自分食いの run で入れる。どの回も今の試験を緑のまま保ち、部品は速い段の試験で直に確かめる。

## 0. 語

- **殻**: `works/dev/` の sh の起動の入口。利用者が打つのは `use.sh`（手順書 `works/skills/works/SKILL.md`）。`dogfood.sh` は自分食い、`real-run.sh` は実走の確かめ、`archon.sh` は隔離した Archon を起こす所。
- **準備**: Archon を起こす前に決める物。認証の出どころ・claude の実行ファイル・開発の家（`WORKS_DEV_HOME`）・包み（`claude-adapter`）を通すか・模型の指定・ラインの入力（`--input`）・run の控え（ledger）・続きの行・run の表示。
- **部品**: この設計で作る `works/dev/launch.py`。

## 1. 今の姿（2026-09-29 に読んだ事実）

- 準備の処理は sh の関数で guard.sh に 8 個、lib.sh に 8 個、use.sh に 9 個。sh の文字列に埋まった Python は 22 か所（use.sh 9・lib.sh 9・他 4）。lib.sh の run の表示 `works_dev_show_run` は約 180 行の Python を sh の文字列に持つ。
- 写しと食い違い:
  - 認証の順の正本は guard.sh の `works_dev_auth_candidates`（token の env → `WORKS_KEYCHAIN_ITEM` → Claude Code 自身の keychain）。dogfood.sh:90 と real-run.sh:35 は古い 2 段の規則のままで、Claude Code 自身の keychain だけの人は use.sh では通り、この 2 本では止まる。
  - claude の実行ファイルの解決が 4 か所（archon.sh・dogfood.sh・real-run.sh・use.sh）。
  - 包みの有無（`ADAPTER_MODE`）を決める行が 3 か所。`unset WORKS_MODEL_PINNED` が 4 か所。
  - 開発の家の既定が 2 種類（`$TMPDIR/works-dev` と、試験の道具・手本の道具の `$HOME/.cache/works-dev`）。
  - ラインの入力: 最後の関所の既定が dogfood.sh は `always`（`WORKS_DOGFOOD_FINAL_GATE`）、use.sh は `when_needed`（`WORKS_USE_FINAL_GATE`）、real-run.sh は渡さない。`policy_md`・`gates`・`thickness` は use.sh だけが渡す。
  - run の控えの JSON は、書くのが lib.sh、読むのが lib.sh と use.sh の 2 か所で、欄を別々に読む。
- 今日の実害: 続きの行の組み立てで、空の模型の指定 `''` が答えの行の引用の中で入れ子になり、試験が赤になった（自分食い 91 番の取り込み）。

## 2. 決めたこと

### 2.1 入口の殻は 4 本とも残し、名前・引数・出す文言を変えない

- 決め手: 汚れの元は入口の数でなく、準備の写し。入口を減らすと、利用者の手順書・自分食いの起こし方・試験が動き、汚れを消す直しが別の所を動かす。
- 捨てた案: `use.sh` 1 本に寄せる（入口の数は汚れの原因でなく、変える範囲だけが大きい）。殻ごと Python にする（変更が最大で、macOS の `/usr/bin/python3`（3.9）で走る形を守る手間が増える。準備を寄せれば引用の入れ子は消える）。

### 2.2 準備は `works/dev/launch.py` 1 本に置く

- 標準ライブラリだけ・Python 3.9 で動く（殻は今も `python3` を呼んでいる。配布の下限は 3.9）。
- `works/dev/` に置く（プラグインに入り、Archon の pack には写らない。pack に入れる物ではない）。
- 殻から `python3 -I "$DEV_DIR/launch.py" <動詞> --for=<殻の名> …` で呼ぶ。`-I` は PYTHON* の環境変数と利用者の site-packages を読まない（3.4 以降。下限 3.9 で使える）。
- 部品は結果を **sh の代入の行**で返し、殻は **2 段**で受ける: `out=$(python3 -I … ) || exit $?` の後に `eval "$out"`。`eval "$(部品)"` と 1 段で書くと、部品が失敗しても終了コードは 0 になり `set -e` でも止まらない（2026-09-29 に手元の /bin/sh で確かめた。POSIX は代入だけの単純コマンドの終了コードを最後の置換の物と定める）。今の use.sh の `eval "$(python3 -c …)"` もこの形で直す。
- 失敗の時、部品は標準出力に何も出さず、1 行の理由と入れ方を標準エラーに出して 0 以外で終わる（途中まで出た代入が効かないように）。
- 出力の 1 行目に版の行（`WORKS_LAUNCH_FORMAT=1`）を置き、殻は版が合わなければ止める（git の `--porcelain=v2` と同じ考え。殻と部品の片方だけ古い状態を見つける）。
- 値は `shlex.quote` で囲み、変数の名前は部品の側で許した名前の一覧（`[A-Z_][A-Z0-9_]*` に当たり、かつ一覧に在る物）だけを出す（`shlex.quote` は名前を守らない。direnv は名前も逃がしている）。
- 秘密は部品を通さない: 部品は認証の**出どころの名**（`env`・`item <名>`・`claude <名>`）だけを決め、値を読むのは今どおり archon.sh だけ。部品の標準出力に token は決して出ない。

### 2.3 動詞

| 動詞 | 返す物 | 今の在りか |
|---|---|---|
| `env <殻>` | 家・claude・認証の出どころ・包み・模型の代入 | guard.sh・各殻 |
| `inputs <殻>` | Archon に渡す `--input` の並び | 各殻 |
| `ledger save/load/list` | run の控えの読み書き | lib.sh・use.sh |
| `go <殻>` | 続きの行 | lib.sh |
| `show <殻>` | run の表示 | lib.sh |

- 既定の表: 優先の順は **旗 > 環境変数 > 殻ごとの既定 > 共通の既定** の 1 つの表として部品に持つ（Click の `default_map`・argparse の `set_defaults` の層に当たる）。`show` は値ごとに出どころ（旗・環境変数・殻の既定・共通の既定）を添える（git config の `--show-origin` と同じ。殻どうしの食い違いがその場で見える）。
- `env`: 殻ごとに違う所（dogfood.sh は家を `$TMPDIR/works-dev`、use.sh は `WORKS_USE_HOME`）は部品の中の 1 つの表（殻 → 既定）に書く。試験の道具と手本の道具の家の既定もこの表から引く（2 種類をなくす）。
- `inputs`: 入力の名と型の正本は `darkfactory/darkfactory.yaml` の `inputs`（自分食い 55 件目で入力の名の集合はここを正本にした）。殻ごとの既定（最後の関所など）は部品の中の 1 つの表に置き、今ある環境変数（`WORKS_USE_FINAL_GATE`・`WORKS_DOGFOOD_FINAL_GATE`・`WORKS_USE_POLICY_MD` など）は、その表で名指しして今どおり効かせる（名は消さない）。real-run.sh も同じ表を通るので、渡し漏れが消える。
- `ledger`: 控えの形を部品の 1 か所で決め、欄に版（`schema`）を足す。古い控え（版の欄が無い物）も今どおり読む。
- 起動が 0 以外で終わった後の結び方も `ledger` の 1 か所で決め、3 本の殻（use.sh・dogfood.sh・real-run.sh）は同じ関数を通す。緩い結び方（run の一覧から最後の物を拾う）はしない。盤面にこの起動の依頼（起動ごとに一意の写し）を持つ run が在る時だけ結び、控えを書き、続きの行を出す（節の途中で落ちた run を起こした時の値で再開できるように）。無ければ一覧に触れず、控えも続きの行も書かずに元の終了コードで終わる。出どころ: 自分食い 107 件目（run 83f66086）で、この扱いが殻ごとの部分の直しとして 3 本に割れ（use.sh だけが盤面で結び、lib.sh に 6 つ目の引数が足された）、独立の目の R1・R2 がともに作り直しが要ると判定したため、取り込まずにこの設計へ移した。
- `go`・`show`: lib.sh の Python をそのまま部品の関数に移す（中身の振る舞いは変えない）。続きの行は引数の並びから `shlex.join` 相当で組み、答えの行に包む時も同じ関数で 1 回だけ引用する（入れ子を作らない）。

### 2.4 殻に残す物

- Claude Code の一時フォルダを拒む柵（`works_dev_refuse_claude_tmp`）は sh のまま、部品より先に走らせる（何かを作る前・認証を確かめる前に止まる約束を保つ）。
- keychain から値を読む所・Archon を `exec` する所・切り離して起こす所（`detach_archon`）は殻に残す。
- この設計の外: herdr の枠への集計、試験の枠の印、mise の信頼の引き継ぎ。外の道具や機械ごとの手当ての置き場は別の設計で決める（汚れの拾い出しの B）。この設計では動かさない。

### 2.5 失敗の扱い

- 部品が決められない時（認証が無い・claude が無い・入力の型が違う）は、今の殻と同じ文言の 1 行と入れ方を標準エラーに出し、0 以外で終わる。殻は `eval` の前に終了コードを見て止まる。
- 認証が見つからない時・keychain が読めない時の振る舞いも順の一部として部品の表に書く（git の credential helper の `quit`、gh の平文への退避のように、見つからない時を決めておく）。今の振る舞い（名指しの項目が空なら次へ進まず止まる）は変えない。
- 期限・時間切れは足さない（ADR 0007）。

## 3. 試験

- 新しい `works/tests/test_launch.py`（速い段・small）: 動詞ごとに、env の辞書と一時のファイルを渡して出力を見る。`security` の呼び出しは偽物に差し替える。子プロセスは起こさない。
- 今の殻の試験（`test_dev`・`test_use`・`test_dev_model`）はそのまま緑であること。文言を縛っている試験は変えない（振る舞いを変えない証）。
- 柵（ratchet）: 4 本の殻と lib.sh の `python3 -c` の数を数え、増えたら赤。認証の順・claude の解決を殻に書き戻したら赤（語で見る）。
- 受け方: 部品が 0 以外で終わった時に殻が止まり、代入が 1 つも効かないことを縛る（1 段の eval に戻したら赤）。版の行が合わない時に止まることを縛る。
- 起動の時間: 部品の import は標準ライブラリの最小限にし、`python3 -X importtime` で測った値を 1 回だけ記録する（期限にはしない）。重ければ Homebrew のように軽い動詞を sh に残すかを決め直す。
- 今日の食い違いの再発を縛る: dogfood.sh と real-run.sh が Claude Code 自身の keychain だけで起こせること、3 本の殻が同じ入力の既定表を通ることを試験で見る。

## 4. 入れ方（3 回に分ける）

各回は自分食いの run 1 本。いま走っている 107 番（起動の止まり方）と 109 番（ブロックごとの模型）が同じ殻を触るので、両方を取り込んだ後の最新の版で 1 回目を起こす。汚れの目（110 番）が入っていれば各回の修正案をそれに通す。

1. `env`: 部品を作り、4 本の殻の認証・claude・家・包み・模型を部品に寄せる（食い違いの実害がここ）。
2. `ledger`・`go`・`show`: lib.sh と use.sh の埋め込みの Python を部品に移す。
3. `inputs`: 入力の既定の表を作り、3 本の殻を通す。

## 5. 見直す条件

- 部品が 800 行を超えるか、起動の準備でない役目（盤面を読む・報告を組む など）が入り始めたら、動詞ごとのモジュールに割る。
- 5 本目の殻が要る話が出たら、2.1 の「4 本とも残す」を決め直す。

## 6. 先例（2026-09-29 に一次情報で調べた。検索語に対象の名前は入れていない）

- 薄い sh の入口と 1 つの解決役: pyenv（入口 `libexec/pyenv` は環境変数の設定と `pyenv-<cmd>` への exec だけ）<https://raw.githubusercontent.com/pyenv/pyenv/master/libexec/pyenv>。Homebrew（`bin/brew` が場所の解決と環境の絞り込み、`brew.sh` が軽いコマンドを bash のまま片付け、残りを Ruby に渡す。理由は "run quickly"）<https://raw.githubusercontent.com/Homebrew/brew/main/Library/Homebrew/brew.sh>。git は sh のコマンドを C の builtin へ移した（POSIX でない環境のパスの変換・プロセスの多さ・内部の API を使えないこと）<https://git.github.io/SoC-2019-Ideas/>。asdf は bash から Go へ丸ごと書き直し、互換が崩れた <https://asdf-vm.com/guide/upgrading-to-v0-16.html>（2.1 で殻ごと書き直す案を捨てた裏付け）。
- 代入の行を出して eval で受ける形: ssh-agent `-s` <https://man.openbsd.org/ssh-agent.1>・`brew shellenv` <https://docs.brew.sh/Manpage>・direnv（名前も逃がす）<https://direnv.net/man/direnv.1.html>。`shlex.quote` は POSIX の shell 専用 <https://docs.python.org/3/library/shlex.html>。
- 認証の出どころの順: gh（GH_TOKEN → GITHUB_TOKEN → keyring、使えなければ平文）<https://cli.github.com/manual/gh_help_environment>・git の credential helper（順に試し揃えば止まる、`quit`）<https://git-scm.com/docs/gitcredentials>・AWS CLI の順 <https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html>。どれも秘密の値は使う側のプロセスが自分で取り、表示や eval の出力に載せない。
- 設定の優先順と出どころ: Click（"The first source that produces a value wins"・`ParameterSource`）<https://click.palletsprojects.com/en/stable/options/>・argparse の `set_defaults` <https://docs.python.org/3/library/argparse.html>・git config の scope と `--show-origin` <https://git-scm.com/docs/git-config>・12-factor（env を束にしない）<https://12factor.net/config>。
- 出力の形の版: git status の `--porcelain=v2` <https://git-scm.com/docs/git-status>。

