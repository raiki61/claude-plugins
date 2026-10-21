# 人と固めた仕様から進める

通常の依頼とは別に、設計書と機械向けの表を渡す入口。`WF` はこのプラグインの `bin/works-factory`。初回は `WF workflow status --cwd <対象>` を打ち、固定版を取り寄せる。工場の取り置きは `${XDG_CACHE_HOME:-~/.cache}/works-factory-plugin/<PIN の commit>` に在る。以下の `SOURCE` はその絶対パス。

## 1. 設計書と表を用意する

設計書は Markdown、表は YAML。設計書には構成と振る舞いを書く。目的・受け入れ条件・試験コマンド・触らない物は表だけに書き、設計書の見出しに同じ項目を置かない。テストを先に書いて直す所があるなら、設計書に `## TDD で直す所` と空でない本文を置く。

表の形は工場の `lib/spectable.py` の `SCHEMA`。例の `run` は準備用の仮の値で、本線を起動する前に実際の審査の run の完全な id に替える。

```yaml
design: docs/change-design.md
purpose: 何を実現するか
acceptance:
  - key: example
    given: 前提（省略可）
    when: 操作やきっかけ
    then: 期待する振る舞い
test_cmd: "試験を走らせるコマンド（省略可）"
out_of_scope:
  - glob: "触らないパスのパターン"
    why: 触らない理由
reviews:
  - part: works-factory-plan-review
    run: pending
    findings: []
  - part: works-factory-independent-design
    run: pending
    findings: []
  - part: works-factory-premises
    run: pending
    findings: []
  - part: works-factory-prior-decisions
    run: pending
    findings: []
  - part: works-factory-world
    run: pending
    findings: []
```

表の `design` と表自身の相対パスは対象のリポジトリのルートから読む。設計書と表は run の作業ツリーでも読める場所に置く。審査中に対象や仕様が変わったら、変わった版で審査し直す。

## 2. 会話の中で審査する

計画の審査・独立設計・前提の確認・過去の決定の確認・業界の定石との比較の 5 部品を、同じ対象で単独の run として必ず回す。仕様を固める会話の中で指摘を直し、残す指摘は人が明示して受け入れた物だけにする。

1. 方針の文を置くフォルダを用意し、入力を工場自身のコマンドで組む。自分で文を組み直さない。

   ```
   uv run --script SOURCE/bin/_lib/spec-inputs.py <対象のルート> <表のパス> --proposal-dir <用意したフォルダの絶対パス>
   ```

2. 返った JSON の `ok` が偽なら `problems` を直す。真なら `args` を使う。`args` は部品名をキーにした配列で、各要素は `名前=値` の字。要素ごとに `--input` を付け、値全体を 1 引数として渡す。計画の審査の `proposal_file` も省かない。

   ```
   WF workflow run <args の部品名> --cwd <同じ対象> --input '<args の要素>' ...
   ```

3. Bash の `run_in_background` で起動し、終わりの知らせから `WF workflow get <run> --json --cwd <対象>` で結果を読む。各部品の結果を確認し、指摘を直したら入力を組み直して影響する部品を再審査する。
4. 最終版を審査した各 run の id を `reviews[].run` に書く。残した指摘は `findings` に `{key, text, handling: accepted, owner_words}` の形で記録し、`owner_words` に人が受け入れた言葉を書く。指摘が無ければ空配列。AI が代わりに受け入れたことにしない。

指摘の `key` は任意に付けない。各 run の `terminal_record.returns.value` のポインタが指すファイルを、`terminal_record.artifacts.root` から読んで取得する。

- 計画の審査: `holes` が指す JSON の `faces[].key`。
- 前提の確認: `constraints` が指す JSON の `constraints` 配列で、`contradicts` がある行の `premises-<1 始まりの行番号>`。番号は配列全体で数える。
- 過去の決定: `material` が指す JSON の `reply.conflicts` 配列の `prior-<1 始まりの行番号>`。
- 業界の定石: `rows` が指す JSONL の、`versus.verdict=differs` の行の `class_id`。
- 独立設計: 機械が照合する指摘キーは無いが、結果は確認する。

入力を組む際、`reviews` は審査する文から外れるので、run の id を書き戻しただけでは審査した版は変わらない。殻は本線の起動時に、部品名・終了状態・入力・出力・指摘の受け入れを実際の run の記録と照合する。仮の id、古い仕様を審査した記録、受け入れていない指摘は通らない。

## 3. 本線を起動する

```
WF workflow run works-factory-line --cwd <対象> --input spec_table=<表のパス>
```

- `request`・`pr`・`base`・`spec`・`fix_fixture` とは組めず、`works-factory-chain` でも使えない。`base` は run の入力の名で、起動スクリプトの `--from` とは別。
- 試験コマンドは表の `test_cmd` に置く。`unattended=true` は組めるが、承認が必要なら通常どおり止まる。
- 審査の記録や表に欠けがあれば、AI を起動する前に止まる。
- 工場の中では判定と計画を 1 回ずつ回し、会話で済ませた計画の審査の往復は繰り返さない。
- 仕様と対象が食い違う、触らないパスに当たる、修正中に再計画や再判定が必要になる時は、仕様を書き換えず止めて返す。仕様を直して再審査し、新しい run を起動する。
- 能力を狭める変更の判断の根拠が設計書や表で不足する場合は、修正前の承認ノードで人に確認する。承認すれば同じ run で進める。
- 最後の試験・独立したレビュー・承認・差分の hash の確認は通常の入口と同じ。止まった run の未検証の変更を、検証済みとして当てない。
