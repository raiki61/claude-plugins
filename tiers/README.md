# tiers

プラグインが要る外の道具（Claude Code・gh・herdr・Archon など、プラグインとは別に PC に入れる道具）がそろっているかを点検し、足りない物と入れ方を出す Claude Code のプラグイン。何も入れない。

## 何ができるか

- 要る道具を段に分けて点検する（下の「段」）。段を 1 つ渡すと、その段までの道具を全部見る。
- 足りない物ごとに、入れ方を OS（macOS・Linux・Windows）に合わせて、走らせている OS の分だけ出す。入れ方は各道具の公式の README から写した。出すだけで、入れるのは人が手で行う。
- 人は `/tiers:check` で走らせる。ほかのプラグインは依存として tiers を入れ、使い始めに同じ点検を呼ぶ（今つないでいるのは、同じリポジトリのプラグイン works-dispatch。作業ごとに Claude Code の会話を別に立てて仕事を頼むプラグイン）。

## 要る物

- **要る段: 0**（Claude Code だけ）。
- Python 3。`bin/tiers` は `python3`・`python`・`py -3` の順に、実際に起きる物で動く。Windows で `python3` や `python` を打つと Microsoft Store が開く（Python を入れていないときに出る代わりの物）なら、Python を入れ、設定 → アプリ → アプリ実行エイリアス で `python.exe` と `python3.exe` の「アプリ インストーラー」を切る。

## 5 分で試す

1. プラグインを入れる。works-dispatch を入れた人は、依存としてもう入っている。

   ```bash
   claude plugin marketplace add raiki61/claude-plugins
   claude plugin install tiers@raiki61
   ```

2. Claude Code の会話で、点検させる。「要る道具がそろっているか見て」と頼んでもよい。

   ```
   /tiers:check 段 2
   ```

3. 結果を読む。そろっていれば次のように出る。足りなければ、その行に入れ方（手で）が付く。入れたら、同じ点検を打ち直す。

   ```
   要る道具の点検（段 0〜2）
    ok  段 0 Claude Code: 2.1.301 (Claude Code)
    ok  段 1 gh: gh version 2.102.0 (2026-09-30)
    ok  段 1 gh のログイン: gh auth status が通る
    ok  段 2 herdr: herdr 0.9.3
    ok  段 2 herdr の動き: herdr の server が動いている
    ok  段 2 起こし方の命令 claude: claude がシェルで見つかる
   結果: 足りない物は無い
   ```

## 段

番号の大きい段は小さい段を含む（段 2 を点検すると段 0 と段 1 も点検する）。使う側のプラグインに、段 1 の gh を要らない使い方があるなら、その点検の側で外して見る（例: works-dispatch の `--check` は、部署だけを使う人には gh の足りない物を注記にとどめる）。

- 段 0: Claude Code だけ。`claude --version` が通るか。
- 段 1: gh（GitHub の CLI）。入っているか（`gh --version`）、ログイン済みか（`gh auth status`）。
- 段 2: herdr（端末を作業場ごとに分けて、中の AI の会話を外から操作できる道具）。入っているか（`herdr --version`）、server が動いているか（`herdr status server` の `status: running`）。それと、アカウントの起こし方の命令（`--launcher` で渡す。省けば `claude`）が、利用者のログインのシェルで見つかるか（Linux・macOS はログインのシェルの `command -v` で探し、シェルの関数と別名も数える。Windows は PATH の上を探し、無ければ PowerShell の起動時に読む設定のファイル `$PROFILE` に書いた関数（と別名）を、PowerShell の `Get-Command` で探す）。
- 段 3: Archon（AI の工程を順に回す道具）。`archon` が PATH に在るか。

足りない物ごとに、入れ方を返す。入れ方の命令は各道具の公式の README の install の節から写した（2026-10-16 に読んだ。OS ごと: macOS・Linux・Windows）。段 2 は、初めての人が自分で準備できるように、入れ方の命令に加えて案内（`guide`。herdr の OS ごとの入れ方の補い、herdr と Claude Code の連携の入れ方、起こし方の命令の作り方）も返す。案内の中身と根拠は [docs/design.md](docs/design.md) の「段 2 の案内」。

## 使い方

`tiers` はこのプラグインの `bin/` に在る。Claude Code の会話の中（Bash の道具）では、Claude Code が `bin/` を PATH に入れるので、名前だけで起こせる。

```bash
tiers --tier <0〜3> [--launcher <命令> ...] [--json]
```

- `--launcher` は段 2 以上でだけ見る（段 0・1 で渡しても誤りにせず、見ない）。何度でも書ける（`--launcher claude-p1 --launcher claude-p2`）。渡した命令を全部探し、1 つでも見つからなければ足りない物になる。
- 終了コード: 0 = そろっている、1 = 足りない物がある、2 = 使い方が違う。
- `--json` の形（`schema` は形の版の番号で、今は 1。呼び手の動かなくなる変え方をしたときだけ上げる）は [`lib/tiers_check.py`](lib/tiers_check.py) の頭に在る。足りない物は `checks[]` の `ok: false` の項目で、`problem`（足りない訳）と `fix`（入れ方の行の並び）と `guide`（案内の行の並び。無ければ空の並び `[]`）を持つ。どの項目も `tier`（段）・`name`（道具の名前）・`ok`・`found`（見つけた物。足りない項目では `null`）を持つ。人の読む形は、同じ `guide` の行を「案内:」の下に出す。

## もっと詳しく

- [docs/design.md](docs/design.md): 決めたこと（何も入れない訳・共通のプラグインにした訳）と、試して確かめたこと。
- [docs/from-other-plugins.md](docs/from-other-plugins.md): ほかのプラグインから tiers をつなぐ形。プラグインを作る人向け。
- [CHANGELOG.md](CHANGELOG.md): 変更の記録。
- 試験: リポジトリの根から `python3 -B -m unittest discover -s tiers/tests`。外の道具は起こさず、口（`Probe`）を偽物に替える。全体の試験（`tests/run.sh`）にも載っている。
