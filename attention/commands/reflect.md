---
description: 「最近どうだった？ 何を直せばいい？」への答え。ある期間（today・yesterday・week（今日を含む 7 日。既定）・month（今日を含む 30 日）・YYYY-MM-DD・YYYY-MM-DD..YYYY-MM-DD）の会話・裏で起動された会話・commit・GitHub の動き・/insights の控えから、改善の提案と、持ち主の仕事の仕方についての気づきとヒントを 1 枚の HTML に出す。日記の置き場（ATTENTION_REFLECT_DIARY_DIR）を決めていれば、1 日の期間のとき、その日の日記に振り返りのセクションを書く。前に却下した提案は出さない。提案を採る・却下する・保留するも、この会話で伝えれば台帳に書く。
allowed-tools: Bash, Read, Write
---

/reflect は、ある期間の持ち主の作業（会話・commit・GitHub の動き）を振り返り、改善の提案と、仕事の仕方の気づきを 1 枚の HTML のページに出すコマンド。持ち主が「最近どうだった？」と聞いたときや、手で /reflect を打ったときに、下の手順で走らせる。

持ち主は、このプラグインを使う人（この会話の相手）である。仕様の正本は `attention/docs/reflect-spec.md`。機械は `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/reflect.py"`（`run-python.sh` は実際に起きる Python〔python3・python・py -3 の順〕を選ぶ入口で、`python3` に替えて打たない。以下 reflect.py）。材料を集めるのも、ページ・台帳・日記を書くのも機械で、AI が書くのはフィールドの JSON だけ（`/catchup` と同じ分担）。

言葉:

- 裏で起動された会話: 期間の中に人が打った発言の無い会話。`claude -p` やフックが起動したもの。裏で会話を起動するプラグインの重さや失敗は、ここに出る。
- 台帳: 出した提案と状態（`open`・`adopted`・`dismissed`・`held`）の控え。材料の JSON の `ledger` がその写し。
- `/insights`: Claude Code 組み込みのコマンド。最近の会話を分析した報告を、設定のフォルダの `usage-data/` に残す。材料の `insights` はその控え。

## 振り返る

1. `reflect.py <期間> --out` を走らせる。期間が無ければ `week`。1 行目に材料の JSON の path、2 行目に数（人の会話・発言・裏の会話・commit・GitHub の動きの件数）が出る。その JSON を Read で読む（`cat` で読まない。長ければ offset を進めて最後まで読む）。
2. 足りない所だけ自分で確かめる。
   - 提案が既に有る物を作れと言わないよう、`assets` のプラグイン・コマンド・スキルと、`assets.instructions` の指示ファイルのうち関わるものを読む。
   - 提案のうち `count × minutes` の大きいもの（ページで上に並ぶもの）は、世間に既製品や公式の機能が無いかを当たる。有ればそれを `existing` に書き、`kind` を `adopt` にする。
   - `insights.reports` が空か、最新の報告の日付が期間の終わりより古ければ、`unseen` に「/insights を打てば会話ごとの分析の控えが増える」と書く。
   - 材料の `coverage.notes`（見た範囲の欠け。GitHub の出来事が期間の頭に届かなかった・会話の記録が消えている・読んでいない設定のフォルダ・知らない記録の形）は、機械がページの頭に出す。`unseen` に写さず、欠けた範囲の数で言い切らない（例: GitHub の動きの件数は、出来事の取れた時刻より後の分）。出来事が切れたアカウントは、`github` の `search` に、期間に更新のあった PR・issue を機械が検索で補ってある。何をしたかまでは分からないので、そのアカウントの動きは「この PR・issue に関わった」までで書く。
3. フィールドの JSON を書く。置き場は材料の JSON の隣で、名前は材料の名前の `.json` を `.fields.json` に替えたもの。形の正本は仕様の「フィールド」のセクションで、全部の key を入れるとこうなる（`existing`・`unseen`・`diary` は省いてよい）。

   ```json
   {
     "headline": "期間の一言",
     "proposals": [{"id": "stop-manual-ci-watch", "title": "…", "kind": "stop", "evidence": "…",
                    "count": 6, "minutes": 3, "where": "…", "existing": "", "action": "…"}],
     "insights": [{"title": "…", "body": "…", "evidence": "…"}],
     "unseen": ["…"],
     "diary": "…"
   }
   ```

   - `proposals`（7 件まで）: `id` は `[a-z0-9-]` の 3〜60 字。`kind` は `stop`（やめる）・`automate`（自動にする）・`config`（設定を変える）・`adopt`（既製品に乗り換える）・`fix`（ツールを直す）のどれか。根拠（`evidence`）は材料の数で書く（何回・どの会話・どの裏の会話）。重さをトークンで言うときは、モデルごとの数（`output_by_model`・`models`）で言い、モデルの違う数を足したり比べたりしない（単価が数十倍違う。値段で比べるなら公式の単価で直し、直したと書く）。自動にする前に、やめられないか（`stop`）を先に考える。台帳で `dismissed` の id は出さない（出しても機械が落とす）。`adopted`・`held` の id は出してよく、ページに状態が付く。前と同じ提案（同じ場所の同じ手間を直すもの）なら台帳の id を使い回す。`count` と `minutes` は材料から見積もれるときだけ数を入れ、見積もれなければ null。`existing` は既に有る物・世間の既製品で、無ければ key ごと省くか空の文字列にする（どちらでも通る）。`where` は直す場所、`action` は最初の一手。
   - `insights`（7 件まで）: 持ち主の仕事の仕方について。時間の行き先、繰り返す頼み方、うまくいった型、つまずきの型。1 件ごとに根拠を `evidence` に書く。一般論は書かない。
   - `unseen`（文字列の並び）: 見ていないもの・確かめていないこと。
   - `diary`: 期間が 1 日で、材料の `diary_dir`（`ATTENTION_REFLECT_DIARY_DIR` の値）が空でないときだけ書く。Markdown で 2,000 字まで。「やったこと」（3〜6 行。公開のリポジトリなら PR の番号つき）と「気づき」（1〜2 個）の 2 つの見出しだけにする。持ち主に答えさせる問いは書かない（日記は持ち主が手で書き足す前提にしない）。日記のファイルは自分で書かない。`--render` が `<diary_dir>/YYYY-MM-DD.md` の末尾の振り返りのセクションをこの文で書き直す（セクションが無ければ足し、ファイルが無ければ作る）。
   - `headline`: 期間の一言（200 字まで）。
   - **非公開のリポジトリの件**（材料の `private.repos`）は、PR・issue の番号、リポジトリ名、件名を書かない。何の作業か（例: 文書の取り込みの部品のレビュー）、どのくらいの量か（例: レビュー 9 件・インラインのコメント 57 件）、言いたいことで書く。公開のリポジトリの件は、番号やリンクを書いてよい。`--render` が、非公開のリポジトリの名前と、そこで出てきた番号（`private.numbers`）をフィールドの文の中に見つけたら、終了コード 2 で止める。
4. `reflect.py --render <材料の JSON> <フィールドの JSON>` を走らせる。`--render` がページを描き、台帳と日記を書き、生きている VS Code の窓で開く（`/catchup` と共通の切り替えで、`ATTENTION_CATCHUP_OPEN=0` なら開かない。開ける窓が無ければ、開かなかったと 1 行出すだけで誤りにはしない）。終了コード 2 なら、出た誤りを直して走らせ直す。
5. 返答は、`--render` が出した行（ページの path、`headline`、落とした提案・日記・開いたかの行）だけにする。提案や気づきの中身は端末に写さない（ページで読む）。

## 決める

持ち主が提案を「採る」「却下」「保留」「戻す」（未決の `open` に戻す）と言ったら、`reflect.py --decide <id> <adopted|dismissed|held|open> --note "<持ち主の言った理由>"` を走らせ、出た 1 行を返す（理由を言われなければ `--note` は省く）。id はページの「台帳の id」の行にある。台帳に無い id なら終了コード 2 で誤りが出るので、ページの id を確かめ直す。

## 定時に回すとき

このコマンドは定時の仕組みを持たない。毎晩回したい人は、自分の環境の定時の仕組みから `claude -p "/attention:reflect yesterday"` を呼ぶ。
