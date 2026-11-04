---
name: milestone-map
description: 「マイルストーン全体はどうなっている？」「どれが間に合いそう？」への答え。1 つのリポジトリの open のマイルストーン全部を、期日の順の時間軸・残りの件数・閉じた実績からの見込み（50% と 85% の日付）・blocked by の線・依存の候補で 1 枚の HTML の地図にする。マイルストーンを全体で見渡すときに使う。自分の番の PR の全件は /whose-turn、1 件の PR や issue は /catchup。
model: sonnet
allowed-tools: Bash, Read, Write
---
マイルストーン全体を 1 枚に見渡すフェーズにいる。正本は GitHub のマイルストーン・issue・blocked by で、このスキルは読むだけ。
GitHub の issue・マイルストーン・blocked by を書き換えるな（依存を付けるのは人が地図を見てから決める）。

## やらないこと

- `gh issue list` / `gh api` でマイルストーンや issue の一覧を組み立て直すな。取り方の正本は同梱の `scripts/milestone-map.py`（下の `${CLAUDE_PLUGIN_ROOT}` は、Claude Code がこのプラグインのルートのフォルダに置き換える変数）で、見込みの出し方・線の定義・見ていないものは `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/milestone-map.py" --help` にある。
- 見込みの日付・件数・線を数え直すな。機械の出した数をそのまま使う。スクリプトが失敗したら、そのエラーをそのまま報告して終わる。
- subagent・Agent・Workflow を立てるな。読む材料は 1 つのファイルで足りる。

## 役割分担

- **スクリプト（機械）**: 母集団（open のマイルストーン全部と、その open の issue・PR・blocked by・親子・直近の閉じた件数）を固定し、見込み（モンテカルロ）・線・依存の候補・律速・見ていないものを全部出す。ページの図と詳細もスクリプトが描く
- **あなた（AI）**: 材料を読んで、全体の一言・目立つ点・マイルストーンごとの一言・受け皿の選び分けだけを書く。母集団を増減させない

## やること

1. `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/milestone-map.py" $ARGUMENTS --out` を実行し、返ってきたパスを **Read で**読む（引数なし＝今のリポジトリ。`--repo OWNER/NAME` で別のリポジトリ）。`--out` は出力を一時ファイルへ書いてパスだけ返す。材料は Bash の 1 回あたりの上限（約 30,000 バイト）を越えるので、**`cat` で読むな**。`--out` は値を取らないので `$ARGUMENTS` の後ろに置く。出力は JSON で、**鍵で読む**:
   - `milestones`: 1 本ずつ `number`・`title`・`due`（期日。無ければ null）・`overdue_days`（期日切れの日数）・`description`（説明文）・`headings`・`open`（残りの issue）・`weekly`（週ごとの閉じた件数。古い週から）・`forecast`（`state` が `ok` なら `p50`・`p85`・`late`〔85% が期日を越える〕・`wide`〔幅が広い訳〕。`none` は閉じた実績が無く見込めない、`done` は残り 0）・`blocked_issues`
   - `edges`（blocked by でマイルストーンをまたぐ線。`from` が止めている側）・`critical`（律速。線が無ければ null。`chain` が鎖のマイルストーンの番号の並び、`end` が鎖の 85% 側の終わり、`tail_due` が鎖の最後のマイルストーンの期日）・`outside`（外から止めている物）・`candidates`（依存の候補。blocked by ではない）・`scope`・`limits`・`not_seen`
   - `data_path`（ページの材料の全部）と `fields_path`（あなたが書くファイルの置き場）

2. `fields_path` に JSON を **Write で**書く。キーはこの 4 つだけ:
   - `headline`（80 字まで）: 全体の一言。期日切れ・見込みが期日を越える本数・線の有無など、材料の数から言えることだけ
   - `points`（6 件まで・各 120 字まで）: 目立つ点。材料の事実どうしの食い違い（期日は近いのに閉じた実績が 0・期日の逆転した線・`critical` の `end` が `tail_due` より後ろなど）と、説明文に書かれた順番や前提で blocked by になっていない物。説明文から読んだ物は「説明文には〜とある」と出どころを書く
   - `notes`（マイルストーンの番号の文字列 → 60 字まで）: 一言を添えたいマイルストーンだけ。全部に書かなくてよい
   - `trays`（番号の並び）: 受け皿（完了条件を置かず、溜めておくための物。名前や説明文が「Future」「いつか」「直近対応」のように終わりを持たない物）。迷ったら入れない。入れた物は図から外れ、図の下の段に並ぶ

3. `bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/milestone-map.py" --render <data_path> <fields_path>` を実行する。誤りがあれば直すべき所が 1 行ずつ返るので、`fields_path` を直して打ち直す。通れば 1 行目がページのパス、2 行目が全体の一言、3 行目が VS Code で開いたかの行。

## 守ること

- **出力に無いことを断定するな。** 「間に合う」「遅れる」は `forecast` の `late` と日付からだけ言う。`wide` があるマイルストーンの日付は幅が広いと添える。
- **blocked by と依存の候補を混ぜるな。** 候補は本文が触れているだけで、前提かは読んでいない。候補を依存と書かない。

## 返答

3 行で返す: ページのパス・全体の一言（`headline` のまま）・VS Code で開いたかの行。続けて `points` を箇条書きで添える。表は使わない。機械の出力の全文（JSON）は「全文を見せて」と求められたときだけ貼る。
