# works-dispatch

作業ごとに Claude Code の会話を別に立てて仕事を頼み、終わったら要約を頼んだ会話へ返させる Claude Code のプラグイン。自分の番の PR を、PR ごとの作業場に開いて読ませることもできる。

ここでは次の言葉を使う。

- **窓口**: 人と話し、仕事を頼む側の Claude Code の会話。長く使い続ける。
- **部署**: 頼まれた仕事をする側。git の枝 1 本の作業場（worktree）と、そこで働く Claude Code の会話 1 つの組。仕事ごとに立てて、終わったら片付ける。
- **会社**: 部署を立てる元のリポジトリ。
- **納品**: 部署が、決まった見出しの要約を窓口へ返すこと。

## 何ができるか

- **頼む・納品させる**: 窓口から部署を立てて頼む（`--ask`）。部署は終わったら要約を窓口へ返す（`--deliver`）。部署の会話が納品せずに止まろうとすると、3 回まで差し戻す。
- **自分の番の PR を開く**: 自分の番の PR（attention プラグインの `/whose-turn` が並べる物）を、PR ごとの作業場に開き、前回からの動き（`/catchup`）を読ませる。相手から新しい返事が来た PR は開き直し、閉じた PR の作業場は片付ける。issue から始める作業も開ける（`--issue`）。
- **アカウントを選ぶ**: Claude Code のアカウントを複数使うなら、使用率に余裕のあるアカウントで会話を起こす。
- **見渡す・片付ける**: 会社ごとの部署の一覧を出す（`--tree`）。済んだ部署を消す（`--clean`）。部署の枝を決まりに従って本流に入れる（`--land`。[docs/land.md](docs/land.md)）。

dispatch 自身は AI を使わない。Python の標準ライブラリだけのスクリプトで、AI を使うのは起こした会話だけ。

## 要る物

- **要る段: 2**（[tiers](../tiers/README.md) の段）。herdr（端末を作業場ごとに分け、中の Claude Code の会話を外から操作する道具。[herdr.dev](https://herdr.dev)）が動いている。gh（GitHub の CLI）のログインは、PR を開く使い方と、本流への入れ方に PR か CI を使う会社だけに要る（部署の回は GitHub を読まない。`--check` は、設定に `[[repos]]` が無ければ gh の足りない物を注記にとどめる）。
- Python 3.11 以降と git。フックは `python3`・`python`・`py -3` の順に、実際に起きて 3.11 以上の物を選ぶ（macOS 付属の 3.9 は選ばない）。Windows で `python3` や `python` を打つと Microsoft Store が開く（Python を入れていないときに出る代わりの物）なら、Python を入れ、設定 → アプリ → アプリ実行エイリアス で `python.exe` と `python3.exe` の「アプリ インストーラー」を切る。
- 試すリポジトリの clone を 1 つ。既定の枝（main など）を開いておく。部署の作業場は、この clone から作る。origin は GitHub でなくてよい（手元の bare リポジトリでも立つ）。本流の枝の名前は、clone の手元の `origin/HEAD` から取り、無ければ origin に問う（空の bare を clone した直後など、どちらでも決まらなければ、本流の枝を push してから `git remote set-head origin --auto` を打つ）。
- PR を開く使い方だけ: attention プラグイン（`/catchup` の命令を持つ）と、dispatch の設定のファイル（`--init` が下書きを書く。手順は [SKILL.md](skills/dispatch/SKILL.md) の「初めて」）。

前提ごとの理由と、`--check` が確かめる中身は [docs/prerequisites.md](docs/prerequisites.md)。

## 5 分で試す

部署を 1 つ立てて頼み、要約が窓口に返ってくるまで。

1. プラグインを入れる。依存の tiers も一緒に入る。

   ```bash
   claude plugin marketplace add raiki61/claude-plugins
   claude plugin install works-dispatch@raiki61
   ```

2. herdr の中で、試すリポジトリの clone のフォルダを開き、窓口の会話を名前を付けて起こす。初めてのフォルダなら、信頼の確認に答える。

   ```bash
   claude --name 窓口
   ```

3. 窓口に、道具がそろっているかを点検させる。足りない物があれば、出た入れ方で入れてから打ち直す。部署だけを使うなら gh のログインは要らないので、`--check` は gh の足りない物を止めずに注記にする（`/tiers:check 段 2` は段の決まりどおり gh のログインも足りない物に数える）。

   ```
   /works-dispatch:dispatch --check
   ```

4. （任意）会社の形の下書きを書かせる。会社の形は、会社の名前・役（部署の仕事の決まり）・本流への入れ方を書くファイルで、無くても試せる（役は既定の `作業`、納品の見出しは下の 6 の既定になる）。`--local` を付けると、リポジトリの中でなく `~/.config/works-dispatch/companies/` に書くので、試すリポジトリを変えない。部署だけを使うなら、dispatch の設定のファイル（`~/.config/works-dispatch/dispatch.toml`）は要らない。

   ```
   /works-dispatch:dispatch --init-company --local
   ```

5. 窓口から頼む。部署の名前（`--task`）と、部署が使う新しい枝（`--branch`）を渡す。

   ```
   /works-dispatch:dispatch --ask 作業 --text "README.md を読んで、初めての人が詰まりそうな所を 3 つ挙げて" --task 試し --branch try/first
   ```

   herdr に部署「試し」の画面が開き、部署の会話が頼みを受けて働き始める。窓口は待たずに次の仕事をしてよい。

6. 部署は終わると、要約を「結論・決め手・残った疑問・枝」の見出しで書いて返す。窓口の画面に `納品です（受付 …、試し・枝 try/first から）: 【結論】…` の 1 行が打ち込まれる。全文は clone の `.git/company/inbox/` に残る。

7. 部署を片付ける。`--clean` が消せる部署を並べ、`--clean --apply` で消す。会話がまだ動いている部署は並ばない（消す条件は [SKILL.md](skills/dispatch/SKILL.md) の `--clean`）。dispatch の設定のファイルは要らない（`--repo` に代表の clone のパスを渡すか、その clone の中から打つ）。

   ```
   /works-dispatch:dispatch --clean
   ```

ほかの使い方（自分の番の PR を開く、アカウントの書き方、役ごとの設定、herdr の見た目）は [SKILL.md](skills/dispatch/SKILL.md) に在る。

## もっと詳しく

- [docs/prerequisites.md](docs/prerequisites.md): 前提と、なぜ要るか。
- [docs/land.md](docs/land.md): 部署の成果を本流に入れる決まり（`--land` と会社の形の `[land]`）。
- [docs/internals.md](docs/internals.md): 内部の作り（ノード・外への口・柵 D1〜D8・試験）。直す人向け。
- [docs/observed.md](docs/observed.md): herdr・Claude Code などの振る舞いを、手元で試して確かめた記録。
- [CHANGELOG.md](CHANGELOG.md): 変更の記録。
