---
description: graphloops を使っていて踏んだ問題を、1 行の説明を添えて利用者の環境に残す。たまった分を 1 ファイルに書き出して作者へ手渡す口と、届け先を設定して送る口も持つ。Claude Code 組み込みの /bug・/feedback（Anthropic 宛）とは別物で、宛先はこのプラグインの作者。
argument-hint: <踏んだことの 1 行> | export <書き出し先> | send | seen | set-url <URL>
allowed-tools: Bash
---

## これは何か

graphloops の engine（ループを回す本体 `scripts/loop.py`）は、次の 2 つを利用者の環境に 1 件 1 行で自動で残す（自動の行）。

- `loop.py` の呼び出しが非 0 で終わった回（拒否・読めない盤面・想定外の例外）。盤面は、run（ループの 1 回の実行）ごとの状態を置くディレクトリ
- `loop.py launch`（engine がノードを受け持つ役〔`agents/*.md` の定義で起動する子の claude〕を起動するコマンド）で、子の claude が失敗した回と、返答の差し戻しが上限まで続いた回

このコマンドは、自動では拾えない問題（判定や手順がおかしい、など）を人が 1 行で書き足す口（手の行）と、たまった分を作者へ渡す口である。

残すのは版・呼び口・終了コード・例外の型などの構造化したフィールドと、人が書いた 1 行だけ。役へ渡したプロンプトや役の返答の本文、レビューする差分、盤面の記録の中身、ファイルのパスは残さない。標準エラーの頭は、環境変数 `GRAPHLOOPS_INTAKE_STDERR=1` を立てたときだけ 500 字まで残す。置き場・残すフィールド・止めない約束（残すのに失敗しても、元の呼び出しの終了コードと出力を変えない）は [README の「踏んだ問題を残す」](../README.md#踏んだ問題を残すgraphloopsintake) に在る。

## 使い方

引数（`$ARGUMENTS`）の頭の語で分ける。どれでもなければ、引数の全体を 1 行の説明として残す。下の `${CLAUDE_PLUGIN_ROOT}` はプラグインの置き場、`${CLAUDE_PLUGIN_DATA}` は更新で消えないプラグインの保存先（記録の置き場）で、どちらも Claude Code がこの手順書の本文に埋める。コマンドは `python3` でなく、このプラグインの `hooks/run-python.sh` を通して起動する（`python3`・`python`・`py -3` の順に、実際に起きて 3.12 以上の物を選ぶ。Windows の `python3` が Microsoft Store へ誘う代わりの物でも動く）。下のコマンドの形をそのまま打ち、Python の名前を替えない。

1. **1 行を残す**（既定）: 回している run があれば、その盤面のディレクトリを `--dir` に添える（run の番号と周〔ループの何周目か〕が行に載る）。盤面のディレクトリは `loop.py init` と `loop.py status` が出す JSON の `dir` に在る（形は `$(git rev-parse --git-dir)/graphloops/<ループ>/<run の番号>/`）。
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" intake --data-dir "${CLAUDE_PLUGIN_DATA}" --what "<1 行の説明>" [--dir <盤面のディレクトリ>]
   ```
2. **export <書き出し先>**: まだ手渡していない行を 1 ファイル（JSONL）に書き出し、手渡した所を進める（書き出した時点で手渡し済みと数え、作者に届いたかは確かめない）。そのファイルは、作者と連絡の付く手段で利用者が渡す（このコマンドは渡さない）。`--all` で手渡し済みも含めて全部、`--with-stderr` で残していれば標準エラーの頭も書き出す（既定は落とす）。
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" intake --data-dir "${CLAUDE_PLUGIN_DATA}" --export <書き出し先>
   ```
3. **send**: まだ手渡していない行を、設定した届け先へ POST する（本文は `{"text": 1 行 1 件の要約, "records": 行の配列}`。標準エラーのフィールドは送らない）。届け先が未設定なら何も送らず、手元に残すだけ。届け先の URL は作者から受け取る（受け側の仕組みはまだ作っていない）。
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" intake --data-dir "${CLAUDE_PLUGIN_DATA}" --send
   ```
4. **seen**: まだ手渡していない行を、書き出さず送らずに手渡し済みにする（`loop.py init`・`status` が出す「まだ手渡していない行」の知らせが止まる）。行は消えず `intake.jsonl` に残る。中身を読んで、作者へ渡さなくてよいと決めたときに使う。
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" intake --data-dir "${CLAUDE_PLUGIN_DATA}" --seen
   ```
5. **set-url <URL>**: 届け先を決める（空の文字列で消す）。届け先は置き場の `intake-config.json` の 1 か所に残る。
   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/loop.py" intake --data-dir "${CLAUDE_PLUGIN_DATA}" --set-url "<URL>"
   ```

返った 1 行（`ok …` か `NG …`）をそのまま利用者に見せる。`注意:` の行は、手の行を残した置き場（`${CLAUDE_PLUGIN_DATA}`）と、engine が自動の行を残す置き場（engine の在り処から導いた所）が違うときに出る。その行も見せ、自動の行も書き出す・送るときは、注意の行に出た置き場を `--data-dir` に渡して同じコマンドを打つ。GitHub には触らない（issue を作らない）。
