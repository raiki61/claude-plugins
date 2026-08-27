# convergence-loops

[![test](https://github.com/raiki61/claude-plugins/actions/workflows/test.yml/badge.svg)](https://github.com/raiki61/claude-plugins/actions/workflows/test.yml)

> **English** — Four Claude Code loops that keep reviewing, researching, diagnosing, or first-reading until they reach a fixed point, with the implementer and the grader held in separate contexts. The machine is only ever allowed to declare failure, never convergence.
>
> **The instructions are in Japanese, but you don't have to read them — Claude does.** The loops report back in *your* language, so they work whatever you speak. Japanese is kept for the prompts because the criteria lean on the imperative force of the original wording and a translation would loosen it. You only need to read `REVIEW.md` yourself if you want to grow the criteria.

Claude Code のプラグイン。収束するまで回す 4 つのループ(convergence-loops)と、外部投稿の門番(coldread)を配る。

- **`/review-loop`** — 実装したコード変更を、レビューと修正を繰り返して収束させる
- **`/research-loop`** — 設計・手法・技術選定の見立てを、業界 / 学界の一次情報で校正してからドメインに最適化する
- **`/doctor-loop`** — リポジトリの現状そのものを読み取り専用で診て、改善候補（減らす・機械チェック化する・構造を正す・時代に合わせる）を新規所見が出なくなるまで検証し、**提案だけ**を返す（変更は適用しない）。変更を診るのではなく、**変更を待たずに診る**
- **`/firstread-loop`** — 書き上げた文書が、書いていない人に通じるかを確かめて、**通じなかったところを直す**。その文書を知らない読み役を毎回新しく立てて、**用事だけを渡してリポジトリの入口から探させ**、**どこで止まったか・読んだ後に何を誤解したか・読みながらどんな疑問が湧いたか**を集める。答えの出なかった疑問は、文書の抜けではなく設計の穴かもしれないので、埋めずに残す。読みやすさの点数は測らない ── **書いた本人は、自分の文書が分かるかどうかを判定できない**。これがこのループの前提

## coldread(別プラグイン・フック)

`coldread` は 2 本目のプラグイン。ループ集ではなく**フック**で、有効化した環境の gh 投稿
(issue・PR の本文)を PreToolUse で捕まえ、文脈ゼロの読み手に初見で読ませて、理解を妨げる
詰まりが直るまで投稿を止める。/firstread-loop がリポジトリ文書向けの重い検査であるのに対し、
こちらは単体で読まれる短文向けの軽い妹で、呼ばなくても効く。投稿の挙動が変わるため
convergence-loops には同梱せず、単体で有効化する。詳細は `coldread/README.md`。

どれも「1 回やって終わり」ではなく、**不動点（レビューなら指摘ゼロ、調査なら新規相違ゼロ、診断なら新規所見ゼロ、初読なら新規の詰まりゼロ）に達するまで回して、達しなければ達しなかったと報告する**形になっている。

## 普通のレビュー依頼と違うところ

これが効いている理由は 4 つに絞れる。

**1. 実装者と採点者を別 context に分ける（writer ≠ grader）**

ループを回す session（writer）は findings を機械的に集めるだけで、ラベルの確定・根本診断・収束判定をしない。それは別 context の subagent（grader）がやる。writer は grader が確定した `[block]` を直すだけで、自分でラベルを下げられない。異議があるときも自分で覆さず、別 context の grader に再判定させる。自分の実装を自分で採点させると、作業を減らして得する側が合格基準を決めることになる。

**2. 機械に合格を宣言させない。不合格だけを宣言させる**

`review-record.py` が返すのは「収束を妨げるもの N 件」だけ。「阻害要因は無い」は収束の宣言ではなく、*機械で見つかる範囲に* 何も無いという意味にすぎない。収束を宣言するのは人。

**3. 無言の省略を「なし」と誤認させない**

「条件に当たらないのでやらなかった（`not_applicable`）」と「やるべきだったが飛ばした（`not_run`）」を別の値で記録し、欄が空なら検証エラーで落ちる。散文で書かせるとこの 2 つが潰れ、後者が前者に化ける。実行しなかった検査が「問題なし」として報告に混じるのが、このループが塞いだ元の穴だった。

**4. 入力の隔離が違う目を並べる**

同じ diff に対して、タスク文脈を知る grader・findings を渡さない grader・**diff が何の機能かを知らせない** grader・リポジトリの外（公式ドキュメント・OSS の issue）だけを見る grader を並列に走らせる。入力が違う目は違う層を拾う——文脈を知らない grader は「この用途なら妥当」という正当化ができないので、言語・フレームワーク一般の衛生違反を拾う。隔離は言い渡しでなく道具で担保する——文脈を遮断する目は道具を一切持たない役割 agent で立てるので、近傍コードにも web にも物理的に届かない（下の「役割 agent」）。

さらに `/review-loop` は**読むだけで収束させない**。主経路を実際に 1 回動かして通った値を観測し、新設した検証ゲートはわざと違反を作って赤くなることを確認する。「テストが緑」を観測として書くことを禁じている。

## インストール

marketplace は **GitHub リポジトリ / 任意の git URL / ローカルディレクトリ**のどれでも指せる。

```bash
/plugin marketplace add raiki61/claude-plugins                      # GitHub
/plugin marketplace add https://git.example.com/team/claude-plugins   # 社内 git
/plugin marketplace add //fileserver/share/claude-plugins             # 共有フォルダ・ローカルパス

/plugin install convergence-loops@raiki61
```

`marketplace` は道具の配布元、`plugin` はそこから入れる道具の束のこと。**セットアップは要らない**。入れたらすぐ使える。

**ただし入手経路には 1 つ条件がある**——次の節を読んでから配布方法を選べ。上の 3 つは対等な選択肢ではない。

## 依存と入手経路

`/review-loop` は欠陥の局所レビューに公式プラグイン `pr-review-toolkit` を使う。これを `plugin.json` の `dependencies` で宣言してあるので、**このプラグインを入れると一緒に入る**（公式 marketplace `claude-plugins-official` にある）。

**その解決に失敗すると、このプラグイン全体がロードされない**（`/review-loop` だけでなく `/research-loop` も使えない）。使えないと気づいたら `claude plugin list` で状態を見て、`pr-review-toolkit` を入れ直せ。依存を宣言する代わりに `/review-loop` の中で導入コマンドを実行する形は採っていない——宣言が未解決のときプラグインがロードされないので、その導入コマンドには到達できず両立しない。

**この制約が効くのは、`claude-plugins-official`（GitHub 上）に到達できない環境**だ。上のインストール節の 3 つのうち、**共有フォルダ・ローカルパス配布はこれに当たりやすい**（エアギャップの社内環境で使う動機がある人ほど当たる）。到達できないなら、利用者に先に `/plugin install pr-review-toolkit@claude-plugins-official` を通せる経路を用意するか、そこを通せないことを承知の上で配れ。

**欠陥の観点が 1 つ静かに欠けたレビューが通るより、止まる方を選んでいる。** これは同梱の `REVIEW.md` が「検査自体が実行不能に終わったとき赤くなるか」を要求していることを、この配布物自身に適用した結果である。

観点の正本は同梱の `REVIEW.md` で、そこには**固有の技術名が一つも書かれていない**。アーキテクチャ境界も標準機構も、対象リポジトリの README・lint 設定・パッケージマニフェスト・近傍コードから grader が毎回読んで把握する。固有の技術名を観点側に書き写すと、その瞬間に正本の複製になり、リポジトリが変わっても古いまま残るため。

対象リポジトリのルートに `REVIEW.md` を置くと、そこに書いた観点も併用される（無くても走る）。

## 使い方

```
/review-loop                    実装・リファクタリング・バグ修正の後に
/research-loop <調べたいこと>    設計文書の論拠固め・技術選定・方式検討で
/doctor-loop                    変更を待たず、現状から改善候補を掘りたいときに
/firstread-loop <読者が持つ用事>  文書を書き上げた後、通じるか確かめたいときに
```

`/review-loop` はコード変更のレビュー、`/research-loop` は見立ての校正、`/firstread-loop` は文書が読み手に通じるかの検証。逆に使わない。

## 役割 agent

4 ループが立てる subagent は、`agents/` に同梱した 6 つの役割定義で起動する。役割＝モデル × effort × 持てる道具の組で、手順書は役割名だけを書き、モデル名を書かない（写しは腐る）。

| 役割 | 役目 | 道具 |
|---|---|---|
| `inspector` | リポジトリを読んで採点する安い目 | Read / Glob / Grep |
| `investigator` | 履歴・`gh`・web まで探しに行く安い目 | ＋ Bash / WebSearch / WebFetch |
| `cold-reader` | 文脈を遮断した初見の読み手 | **なし** |
| `judge` | 覆せない判定を下す高い目 | Read / Glob / Grep / WebSearch / WebFetch |
| `blind-judge` | 内部を遮断した独立導出・突合の高い目 | **なし** |
| `reader` | `/firstread-loop` の読み役 | Read / Glob / Grep |

どの役も書く道具（Edit / Write）を持たない。`investigator` だけは Bash を持つので、起動する手順書が前後の作業ツリー突合で押さえる——「書き換えるな」を言い渡しで守らせない。遮断系の 2 役は道具ゼロで起動し、プロンプトに貼られた本文だけを読む——「読むな」と言い渡して守らせる代わりに、読めなくしてある。変え方は `docs/customize.md`「役割 agent を変える」。

## 走らせると何が起きるか

`/review-loop` は 1 ラウンドを **P0**（基準点と「元の目的」の固定）→ **P1**（素材集め・grader を並列起動）→ **P2**（診断・根本原因への変換とラベル確定）→ **P3**（修正）→ **P4**（再採点と機械突合）で回す。`[block]` が 0 になったら **P-R** の収束ゲート——R1 最小性 / R2 ゼロベース再導出 / R3 全体整合 / R4 見えてないスコープ——に進み、1 つでも `redesign-needed` なら新ラウンドに戻る。

収束は**連続 2 ラウンド**で阻害要因ゼロ・CI 緑・R1〜R4 が全て `pass`。到達しなければ「収束せず」として止まり、判断を人に返す（ラウンド上限 5、超えたら必ず停止）。**黙って打ち切らない**のが設計の要点で、stuck / thrash / 前提不成立 / 未観測はそれぞれ別の停止条件として報告される。

## 依存

**必須**: `git` / `python3` または `python`（3.7 以降を想定。実測は 3.12・3.13）/ `bash`

**`/review-loop` が呼ぶもの**:

| 依存 | 用途 | 無いとき |
|---|---|---|
| `pr-review-toolkit` プラグイン | 欠陥の局所レビュー（`review-pr`） | 上の「依存と入手経路」が正本 |
| 組み込み `/simplify` | 品質（reuse・簡素化・効率）の局所レビュー | Claude Code 本体に同梱 |
| 組み込み `/security-review` | 認証・データ取扱い・外部 I/O に触れるとき | 同上 |
| `gh` CLI | 並行 PR との衝突チェック | 他ホストでは同等コマンドに読み替え。読み替えられないなら「確認できなかった」と報告させる |

**`/research-loop` が呼ぶもの**: `WebSearch` / `WebFetch`、`Workflow` ツール（使えない環境では同じ構造を `Agent` の並列起動で再現する手順が本文にある）、`python3` と同梱の `research-record.py`（実行記録の検証——最終報告の必須欄の正本。実行できない環境では script 本文を読んで目視照合する手順が本文にある）

**`/firstread-loop` が呼ぶもの**: `python3` と同梱の `firstread-record.py`（周の記録の検証——**聞いていない素材を「無かった」と書けなくする**のと、先に書いた答えがファイルとして実在するかの確認が主目的）

**`/doctor-loop` が呼ぶもの**: 対象リポジトリに既にある読み取り専用の計器（lint・型検査・テスト等。無ければ「試せなかった計器」として報告）、`python3` と同梱の `doctor-record.py`（実行記録の検証。記録は対象リポジトリの作業ツリーの**外**に書く——変更禁止の規律と両立させるため）

## この型が保証しないもの

- **指示は日本語のみ**。報告は利用者の言語で返るので使う分には支障がない。命令の強さ（「無言の省略を禁ずる」「注記は最後の手段」）で規律を保っている箇所が多く、訳で緩むため日本語のままにしている
- **GitHub 前提の箇所がある**（並行 PR の衝突チェック）
- **`comment-ratio.sh` が数えられるのは Python と C 系コメントの言語だけ**。`#` 系（Ruby・Shell）は対象外——足しても注釈を 1 行も拾えないまま「0%」を自信ありげに出すので、行数で別に測る
- **C 系の注釈カウントは近似**。字句解析をしないので、文字列やテンプレートリテラルの中に `/*` があると `*/` までの全行を注釈として数える（過大側）。行末コメントは数えない（過小側）。ラウンド間で比べる値なので、この 2 つのバイアスは入力の中身次第で効き方が変わる。Python は `tokenize` で数えるのでこの制約は無い
- **`claude-plugins-official` に到達できない環境では、このプラグイン全体が使えない**（詳細と復帰手順は上の「依存と入手経路」）
- **subagent を多数起動する**。1 ラウンドあたり grader 数体、収束ゲートで数体。軽い確認には向かない
- **ラウンド上限**（review-loop は 5、research-loop は 4）。超えたら「収束せず」として止まり、判断を人に返す。黙って打ち切らないことを優先している

## 動作確認

**これはこのプラグイン自身を開発・改造する人向けの検証で、利用者が対象リポジトリで走らせるものではない。** `/plugin install` で入れた場合、実体はプラグインのキャッシュに置かれて作業ディレクトリには現れないので、`tests/run.sh` は clone しないと存在しない。

```bash
git clone https://github.com/raiki61/claude-plugins
cd claude-plugins
bash tests/run.sh
```

検査するもの——`review-record.py`・`research-record.py`・`doctor-record.py`・`firstread-record.py` の終了コードの区別（記録が不正・読めない・引数違い・想定外の例外を非収束と混ぜないこと。後者は「収束の偽装だけを塞ぎ、停止の正直な申告は通す」ことも含む）、`comment-ratio.sh` の注釈カウントと計測漏れの扱い、依存の宣言と marketplace の許可リストの整合、マニフェストの必須欄、手順書が名指しする `REVIEW.md` のセクションが実在するか、手順書が名指しする役割 agent が `agents/` に実在し・どの役も書く道具を持たず・遮断系は道具ゼロで・手順書にモデル名の写しが戻っていないか、手順書に自作の導入コマンドと `-R` 無しの `gh` が戻っていないか、配布物に固有の技術名が混ざっていないか。件数はここに書き写さない（腐るので、走らせた出力を見てほしい）。CI が Linux / macOS / Windows で同じものを回す。

検査が空振りした場合も `exit 2` で落ちるので、対象が空でも緑になる穴は塞いである。**ゲートは違反をわざと作って赤を確認したものだけを「機能している」と扱う**（`REVIEW.md` の「動かして赤・失敗を一度も見ていない保護機構を『機能している』と扱わない」を自分に適用した）。**赤を確認していないガードはまだ複数残っている**（`comment-ratio.sh` の `python3` 不在ガードと例外境界、`SyntaxError` の腕、`git` の 120 秒タイムアウト分岐）。件数をここに書き写さない——数えて書いた瞬間に腐る。確かめたいなら、当該ガードを壊して `bash tests/run.sh` が赤くなるかを見てほしい。

`review-record.py` の終了コードは `0`（阻害なし）/ `1`（阻害あり）/ `2`（記録が不正）の 3 値。**2 と 1 を取り違えないこと**——2 は記録を直して再実行する合図で、非収束の判定ではない。

## ライセンス

MIT。
