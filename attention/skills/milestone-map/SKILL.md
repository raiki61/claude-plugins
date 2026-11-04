---
name: milestone-map
description: 「マイルストーン全体はどうなっている？」「何が何を止めている？」への答え。1 つのリポジトリの open のマイルストーン全部を、期日の順に左から右へ流れる 1 枚の HTML の地図にする。issue 1 件をカード 1 枚にし、blocked by を矢印で、クリティカルパスを太線で描く。マイルストーンを全体で見渡すときに使う。自分の番の PR の全件は /whose-turn、1 件の PR や issue は /catchup。
model: sonnet
allowed-tools: Bash
---
マイルストーン全体を 1 枚に見渡すフェーズにいる。正本は GitHub のマイルストーン・issue・blocked by で、このスキルは読むだけ。
GitHub の issue・マイルストーン・blocked by を書き換えるな（依存を付けるのは人が地図を見てから決める）。

## やらないこと

- `gh issue list` / `gh api` でマイルストーンや issue の一覧を組み立て直すな。取り方の正本は同梱の `scripts/milestone-map.py`（下の `${CLAUDE_PLUGIN_ROOT}` は、Claude Code がこのプラグインのルートのフォルダに置き換える変数）で、色と線の定義・見ていないものは `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/milestone-map.py" --help` にある。
- 地図に推定や見込み（いつ終わりそうか・本文から読んだ依存）を足すな。地図は GitHub から取った事実だけを描く。
- 件数を数え直すな。機械の出した数をそのまま使う。スクリプトが失敗したら、そのエラーをそのまま報告して終わる。
- subagent・Agent・Workflow を立てるな。

## やること

1. `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/milestone-map.py" $ARGUMENTS` を実行する（引数なし＝今のリポジトリ。`--repo OWNER/NAME` で別のリポジトリ）。
2. 出力は 3 行: ページのパス・数の 1 行（マイルストーン・issue・色ごとの件数・blocked by の件数と描いた線の本数・クリティカルパスの件数）・VS Code で開いたかの行。

## 返答

出力の 3 行をそのまま返す。足すのは、クリティカルパスが無いときに「blocked by を付けると線とクリティカルパスが出る」の 1 行だけ。表は使わない。
