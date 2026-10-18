# 機械窓口: `--call` と合図

役ごとに、AI を起こさずに機械で答える道具を会社の形に書ける。どの会社にどんな道具を置くか（道具の台本そのものも）は会社の形とそのリポジトリが決め、works-dispatch は呼ぶ仕組みだけを持つ。機械窓口を付けてよいのは、**成功と失敗を機械で決められる仕事だけ**（道具は片づいたら終了の値 0、片づかなかったら 0 以外を返す）。

```toml
[[roles]]
name = "配布"
machine = true                       # AI の部署を持たない役（--ask で宛てられない）

[[roles.tools]]
name = "spread-plugins"              # 以下 4 つは MCP の道具の定義（Tool）の欄に合わせる
title = "全アカウントに配る"
description = "…"
inputSchema = { type = "object", properties = { dry_run = { type = "boolean" } }, additionalProperties = false }
command = "python3 scripts/spread-plugins.py"   # origin の既定の枝の中身（一時の worktree）の根で走らせる。入力の JSON を標準入力に渡す
fallback_role = "作業"               # 片づかなかったときに回す役（省けばその道具を持つ役。machine の役では要る）
```

```
bash "${CLAUDE_PLUGIN_ROOT}/hooks/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/dispatch/dispatch.py" --call <会社/役> <道具の名前> [--input <JSON の字か @ファイル>] [--dry-run]
```

- **呼ばれて動く道具**（`--call`）: 片づけば答えを出して 0 で終わる。片づかなければ、外れ（`kind: "miss"`）を受付箱の台帳に残し、その入力を AI への頼みに変えて回す役に回し、受付番号を出して 3 で終わる（頼み元は呼んだ会話。待つか、自分で進めるかは頼み元が選ぶ）。回し方は `--ask` と同じで、回す役の常設の部署が在ればその順番待ちに積み、無ければ一度きりの部署を自動で立てる（名前は「<道具を持つ役>：<道具の title>」、枝は `work/<道具の name>-<受付番号の末尾 6 字>`）。入力は、物であること・`required`・`additionalProperties = false`・各鍵の `type` だけを確かめる。
- **合図で動く道具**: 出来事の欄に書いておくと、その出来事の後に呼ぶ。最初の出来事は本流に入れた後（`[[land.after]]`。「本流に入れる」）。
- MCP のサーバーは立てない（各会話の文脈に道具の定義を載せないため）。道具の一覧と外れの回数は `--tree` の会社の行に出る。
- 道具は会社の形を origin の既定の枝から読む（`--ask` と同じ）ので、会社の形に足した道具は本流に入ってから呼べる。
- 道具を走らせる場所は、代表の clone から一時のフォルダ（`<一時のフォルダ>/works-dispatch-tool-<字>/tree`）に作る worktree で、走らせ終えたら消す。作るときに、作った処理の番号（pid）を訳にした鍵（`git worktree lock` の訳 `works-dispatch-tool pid <番号>`）を掛ける。処理が殺される（Bash の持ち時間切れなど）と消す所まで行かずに残るので、次に道具を走らせるときと `--clean --apply` が、作った処理がもう居ない物を消す。場所がもう無いのに git の記録だけ残った物も消す。鍵の無い物（この直しより前の版が作った）は、アカウントごとに入っている版が違う間、前の版の道具が今走っている場所かもしれないので消さず、`--clean` が訳と消し方を添えて並べる。道具がその場所で作った commit（写しの道具は来歴を commit して push する）が push されないまま殺されたときに失わないよう、先頭の commit がどの枝にも無ければ `refs/company/kept-tools/<commit の id>` に残してから消す（中を見るなら `git log refs/company/kept-tools/<id>`、要らなければ `git update-ref -d` で消す）。未コミットの変更か git に足していないファイルが在る場所は消さず、`--clean` が訳と消し方を添えて並べる。Windows では処理が居るかを確かめない（`os.kill` が処理を止めるため）ので、番号の鍵の物は消さない。`--tree` は「（道具の一時の場所）」、`--clean` は「道具の一時の場所」の行で出す。`--clean` に「残す」と出た道具の一時の場所は、道具が走っていないのを確かめてから、その行に添えた手順（commit を残す `git update-ref` と、`git worktree remove -f -f`）で消す。
