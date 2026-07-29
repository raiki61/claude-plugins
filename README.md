# review-loops

> **English** — Two Claude Code loops that keep reviewing (or researching) until they reach a fixed point, with the implementer and the grader held in separate contexts. The machine is only ever allowed to declare failure, never convergence.
>
> **The instructions are in Japanese, but you don't have to read them — Claude does.** The loops report back in *your* language, so they work whatever you speak. Japanese is kept for the prompts because the criteria lean on the imperative force of the original wording and a translation would loosen it. You only need to read `REVIEW.md` yourself if you want to grow the criteria.

Claude Code のプラグイン。収束するまで回す 2 つのループを配る。

- **`/review-loop`** — 実装したコード変更を、レビューと修正を繰り返して収束させる
- **`/research-loop`** — 設計・手法・技術選定の見立てを、業界 / 学界の一次情報で校正してからドメインに最適化する

どちらも「1 回レビューして終わり」ではなく、**不動点に達するまで回して、達しなければ達しなかったと報告する**形になっている。

## 普通のレビュー依頼と違うところ

これが効いている理由は 4 つに絞れる。

**1. 実装者と採点者を別 context に分ける（writer ≠ grader）**

ループを回す session（writer）は findings を機械的に集めるだけで、ラベルの確定・根本診断・収束判定をしない。それは別 context の subagent（grader）がやる。writer は grader が確定した `[block]` を直すだけで、自分でラベルを下げられない。異議があるときも自分で覆さず、別 context の grader に再判定させる。自分の実装を自分で採点させると、作業を減らして得する側が合格基準を決めることになる。

**2. 機械に合格を宣言させない。不合格だけを宣言させる**

`review-record.py` が返すのは「収束を妨げるもの N 件」だけ。「阻害要因は無い」は収束の宣言ではなく、*機械で見つかる範囲に* 何も無いという意味にすぎない。収束を宣言するのは人。

**3. 無言の省略を「なし」と誤認させない**

「条件に当たらないのでやらなかった（`not_applicable`）」と「やるべきだったが飛ばした（`not_run`）」を別の値で記録し、欄が空なら検証エラーで落ちる。散文で書かせるとこの 2 つが潰れ、後者が前者に化ける。実行しなかった検査が「問題なし」として報告に混じるのが、このループが塞いだ元の穴だった。

**4. 入力の隔離が違う目を並べる**

同じ diff に対して、タスク文脈を知る grader・findings を渡さない grader・**diff が何の機能かを知らせない** grader・リポジトリの外（公式ドキュメント・OSS の issue）だけを見る grader を並列に走らせる。入力が違う目は違う層を拾う——文脈を知らない grader は「この用途なら妥当」という正当化ができないので、言語・フレームワーク一般の衛生違反を拾う。

さらに `/review-loop` は**読むだけで収束させない**。主経路を実際に 1 回動かして通った値を観測し、新設した検証ゲートはわざと違反を作って赤くなることを確認する。「テストが緑」を観測として書くことを禁じている。

## インストール

marketplace は **GitHub リポジトリ / 任意の git URL / ローカルディレクトリ**のどれでも指せる。リポジトリを立てずに、共有フォルダに置いて配ることもできる。

```bash
/plugin marketplace add raiki61/claude-review-loops                 # GitHub
/plugin marketplace add https://git.example.com/team/review-loops   # 社内 git
/plugin marketplace add //fileserver/share/review-loops             # 共有フォルダ・ローカルパス

/plugin install review-loops
```

**セットアップは要らない**。入れたらすぐ使える。

観点の正本は同梱の `REVIEW.md` で、そこには**固有の技術名が一つも書かれていない**。アーキテクチャ境界も標準機構も、対象リポジトリの README・lint 設定・パッケージマニフェスト・近傍コードから grader が毎回読んで把握する。固有の技術名を観点側に書き写すと、その瞬間に正本の複製になり、リポジトリが変わっても古いまま残るため。

自分のチームが事故から足した観点があれば、対象リポジトリのルートに `REVIEW.md` を置けば併用される（無くても走る）。観点は使う人が育てる資産なので（`REVIEW.md` の「この規約の育て方」）、プラグイン側には言語非依存のものだけを置いている。

## 使い方

```
/review-loop                    実装・リファクタリング・バグ修正の後に
/research-loop <調べたいこと>    設計文書の論拠固め・技術選定・方式検討で
```

`/review-loop` はコード変更のレビュー、`/research-loop` は見立ての校正。逆に使わない。

## 走らせると何が起きるか

`/review-loop` は 1 ラウンドを **P0**（基準点と「元の目的」の固定）→ **P1**（素材集め・grader を並列起動）→ **P2**（診断・根本原因への変換とラベル確定）→ **P3**（修正）→ **P4**（再採点と機械突合）で回す。`[block]` が 0 になったら **P-R** の収束ゲート——R1 最小性 / R2 ゼロベース再導出 / R3 全体整合 / R4 見えてないスコープ——に進み、1 つでも `redesign-needed` なら新ラウンドに戻る。

収束は**連続 2 ラウンド**で阻害要因ゼロ・CI 緑・R1〜R4 が全て `pass`。到達しなければ「収束せず」として止まり、判断を人に返す（ラウンド上限 5、超えたら必ず停止）。**黙って打ち切らない**のが設計の要点で、stuck / thrash / 前提不成立 / 未観測はそれぞれ別の停止条件として報告される。

## 依存

**必須**: `git` / `python3` または `python`（3.7 以降を想定。実測は 3.12・3.13）/ `bash`

**`/review-loop` が呼ぶもの**:

| 依存 | 用途 | 無いとき |
|---|---|---|
| `pr-review-toolkit` プラグイン | 欠陥の局所レビュー（`review-pr`） | **`/review-loop` が冒頭で自動導入する**（冪等・既にあれば no-op）。失敗しても止まらず `awaiting_human` として記録に残る |
| 組み込み `/simplify` | 品質（reuse・簡素化・効率）の局所レビュー | Claude Code 本体に同梱 |
| 組み込み `/security-review` | 認証・データ取扱い・外部 I/O に触れるとき | 同上 |
| `gh` CLI | 並行 PR との衝突チェック | 他ホストでは同等コマンドに読み替え。読み替えられないなら「確認できなかった」と報告させる |

**`/research-loop` が呼ぶもの**: `WebSearch` / `WebFetch`、`Workflow` ツール（使えない環境では同じ構造を `Agent` の並列起動で再現する手順が本文にある）

## この型が保証しないもの

- **指示は日本語のみ**。報告は利用者の言語で返るので使う分には支障がないが、**観点を自分で育てる側に回るには `REVIEW.md` を読む必要がある**。命令の強さ（「無言の省略を禁ずる」「注記は最後の手段」）で規律を保っている箇所が多く、訳で緩むため日本語のままにしている
- **GitHub 前提の箇所がある**（並行 PR の衝突チェック）
- **`comment-ratio.sh` が数えられるのは Python と C 系コメントの言語だけ**。`#` 系（Ruby・Shell）は対象外——足しても注釈を 1 行も拾えないまま「0%」を自信ありげに出すので、行数で別に測る
- **subagent を多数起動する**。1 ラウンドあたり grader 数体、収束ゲートで数体。軽い確認には向かない
- **ラウンド上限**（review-loop は 5、research-loop は 4）。超えたら「収束せず」として止まり、判断を人に返す。黙って打ち切らないことを優先している

## 動作確認

`review-record.py` の挙動は同梱の実例で確かめられる。

```bash
# 非収束（block 2 件 + do-now 未対応 + 前ラウンド無し）→ exit 1
python3 scripts/review-record.py templates/round-1.example.json

# 阻害なし（block 解消・defer は構造的理由つき）→ exit 0。増えた scalar も出る
python3 scripts/review-record.py templates/round-2.example.json templates/round-1.example.json
```

終了コードは `0`（阻害なし）/ `1`（阻害あり）/ `2`（記録が不正）。**2 と 1 を取り違えないこと**——2 は記録を直して再実行する合図で、非収束の判定ではない。

## ライセンス

MIT。
