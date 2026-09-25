---
description: graphloops を使っていて踏んだ問題を、1 行の説明を添えて利用者の環境に残す。たまった分を 1 ファイルに書き出して作者へ手渡す口と、届け先を設定して送る口も持つ。Claude Code 組み込みの /bug・/feedback（Anthropic 宛）とは別物で、宛先はこのプラグインの作者。
argument-hint: <踏んだことの 1 行> | export <書き出し先> | send | set-url <URL>
allowed-tools: Bash
---

## これは何か

graphloops の engine は、非 0 で終わった呼び出し（拒否・読めない盤面・想定外の例外）と、`loop.py launch` で役が落ちた行を、利用者の環境に 1 件 1 行で自動で残す。このコマンドは、自動では拾えない問題（判定や手順がおかしい、など）を人が 1 行で書き足す口と、たまった分を作者へ渡す口である。

- **置き場**: Claude Code がプラグインに渡す持続の置き場 `${CLAUDE_PLUGIN_DATA}` の下の `intake.jsonl`。プラグインの更新では消えない（アンインストールの最後の 1 回では消える）
- **残す欄**: プラグインの名前・版・取れればコミット・OS と Python の版・呼び口・終了コード・例外の型と上げた関数（launch の行は終了コードを持たず、例外の型の欄に落ち方の種類と、それを決めた関数が入る。種類の一覧は engine の `commands.launch_cause` が正本）・run の番号と周・同じ問題を数える鍵（版を含まない）・人が書いた 1 行。本文・差分・記録の中身・パスは残さない。標準エラーの頭は、環境変数 `GRAPHLOOPS_INTAKE_STDERR=1` を立てたときだけ 500 字まで残す
- **残す処理は本体を止めない**: 書けなくても、engine の終了コードと出力は変わらない。認証もネットワークも使わない（使うのは下の send だけ）

## 使い方

引数（`$ARGUMENTS`）の頭の語で分ける。どれでもなければ、引数の全体を 1 行の説明として残す。

1. **1 行を残す**（既定）: 回している run があれば、その盤面の置き場を `--dir` に添える（run の番号と周が行に載る）。
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" intake --data-dir "${CLAUDE_PLUGIN_DATA}" --what "<1 行の説明>" [--dir <盤面の置き場>]
   ```
2. **export <書き出し先>**: まだ手渡していない行を 1 ファイル（JSONL）に書き出し、手渡した所を進める。そのファイルを作者へ渡す。`--all` で手渡し済みも含めて全部、`--with-stderr` で残していれば標準エラーの頭も書き出す（既定は落とす）。
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" intake --data-dir "${CLAUDE_PLUGIN_DATA}" --export <書き出し先>
   ```
3. **send**: まだ手渡していない行を、設定した届け先へ POST する（本文は `{"text": 1 行 1 件の要約, "records": 行の配列}`。標準エラーの欄は送らない）。届け先が未設定なら何も送らず、手元に残すだけ。
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" intake --data-dir "${CLAUDE_PLUGIN_DATA}" --send
   ```
4. **set-url <URL>**: 届け先を決める（空の文字列で消す）。届け先は置き場の `intake-config.json` の 1 か所に残る。
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" intake --data-dir "${CLAUDE_PLUGIN_DATA}" --set-url "<URL>"
   ```

返った 1 行（`ok …` か `NG …`）をそのまま利用者に見せる。`注意:` の行が出たら、自動の行と手の行の置き場が別の場所になっている——その行も見せる。GitHub には触らない（issue を作らない）。
