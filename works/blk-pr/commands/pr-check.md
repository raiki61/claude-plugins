# P0-5 並行 PR 衝突チェック（任せ先の役。6 段を順に。段を飛ばすな）

お前は読むだけの役。ファイルを書く・消す・git の状態（HEAD・枝・stash）を動かすことはしない。受け付けは、役を起こす前の作業ツリー・HEAD の sha・枝と比べ、変わっていれば返答を拒む。

渡し物: `$pr-snap.output.brief_file`（Read せよ。JSON）

**gh は包みの読む口 `"$WORKS_GH"` を通して打て**。素の `gh` は包みが拒む（許すのは `pr list`・`pr view`・`pr diff` の `-R` つきと、`repo view <OWNER/REPO>` だけ）。`$WORKS_GH` が空なら gh を打てないので、material を not_run（reason に「包みの読む口が無い」）で返せ。

- `cwd`: 対象のリポジトリ。`base`: BASE（周の頭で固めた版）
- `fallback`: この節が任せ先に落ちた理由。engine は 1〜5 段を同梱の parallel-pr.py で済ませようとして、交差が在った・remote が GitHub でない・gh が無いのどれかで役に回した
- `changed_files`: 変更ファイル集合（機械が取った。差分が空の判定から入る run では、依頼が指す場所 `request_wheres` に名指された追跡中のファイル）

**この指示書が届くのは、engine が 1〜5 段を済ませられなかったか、交差が在ったときだけ**。交差が在って落ちた時も、1〜5 段を自分で確かめ直してから 6 段へ進め。

1. 対象リポジトリを解決する: `git remote get-url <upstream の remote>`（upstream は `git rev-parse --abbrev-ref @{u}`。無ければ origin）から owner/repo を導け。以降の `"$WORKS_GH"` には全て `-R <owner/repo>`。**`gh repo view` の値をこの確認に使うな**（cwd の remote から解決するので検査が恒真になる）。導けないなら以降を「確認できなかった」（awaiting_human）。取り違えた一覧で「衝突なし」と書くな。
2. 自分の PR を除外する: `"$WORKS_GH" pr list -R <owner/repo> --limit 100 --json number,headRefName,headRefOid` で列挙し、`git rev-parse HEAD` と headRefOid が一致する PR を先に外せ（外さないとレビュー対象そのものをスコープ外にする自己言及的な誤判定になる。ブランチ名で照合するな——detached HEAD では空文字になる）。
3. 列挙が打ち切られていないか: 返った件数が --limit と同じなら打ち切られた可能性がある → truncated=true・material は awaiting_human。打ち切られた一覧で「衝突なし」と書くな。
4. 変更ファイル集合: 渡し物の `changed_files`。**集合が空なら clean と書くな**——空の集合との交差は何も確かめていない。not_run（reason に何が空だったか）で返せ。
5. 残った PR の変更ファイル: `"$WORKS_GH" pr view <n> -R <owner/repo> --json files --jq '.files[].path'`。交差するものが「同一ファイルを触る並行 PR」。
6. 交差した箇所を担当の PR に渡す。ただし申し送りは投稿せず、下書きを返す: `"$WORKS_GH" pr diff <n> -R <owner/repo>` で hunk を見て、衝突・重複が判明した箇所は、その変更を主導している PR の物として本ループのスコープから外し（`excluded` に 1 hunk 1 行）、その PR の担当へ渡す申し送りの下書き（どの PR の・どのファイルの・どの hunk が・この run のどの変更とぶつかるか・どちらを先に入れるかの問い）を `conflicts[].note` に書き、`handed_over: false` で返せ（このラインは担当の PR へ投稿しない。持ち主の決定 2026-09-27。下書きは報告の冒頭に載り、人が担当の PR へ渡す。外した hunk は後の役——判定・修正案・修正——に触らない範囲として渡る）。

**書き込みの gh と、HEAD・枝を動かす語を打つな**（`gh api`（読むだけの形も含めて丸ごと。graphql の mutation も）・`gh pr comment`・`gh pr review`・`gh pr edit`・`gh pr create`・`gh pr close`・`gh pr merge`・`gh pr ready`・`gh pr reopen`・`gh pr checkout`・`gh issue comment`・`gh issue create`・`gh issue edit`・`gh issue close`・`gh issue reopen`・`gh label`・`gh release create`・`git checkout`・`git switch`・`git stash`・`git reset`。gh で打ってよいのは包みの読む口を通した `"$WORKS_GH" pr list -R <owner/repo>`・`"$WORKS_GH" pr view <n> -R <owner/repo>`・`"$WORKS_GH" pr diff <n> -R <owner/repo>` だけ）。`handed_over: true` の行を 1 つでも返せば、受け付けが拒む。

GitHub 以外のホストでは同等の読むコマンドに読み替えろ（書き込みの語は同じく使わない）。読み替えられないなら awaiting_human。gh の通信が sandbox で拒まれて確かめられないなら、material を not_run（reason に拒まれたコマンドとその出力）で返してよい。**未確認を clean と書くな。**

## 返答の書き方

- `repo`: 1 段で導いた owner/repo。`listed`: 2 段で返った件数（自分の PR を外す前）。`truncated`: 3 段。
- `conflicts`: 交差した PR ごとに 1 行 `{pr, files, handed_over: false, note}`。`pr` は PR の番号の文字列、`files` は交差したファイル、`note` は 6 段の下書き。
- `excluded`: 6 段で本ループのスコープから外す hunk を 1 行ずつ `{pr, file, start, end, why}`。`pr` は `conflicts` に在る PR、`file` はその行の `files` に在るファイル、`start`・`end` は**今の作業ツリーの**そのファイルの行の範囲（1 始まり・両端を含む）、`why` は何とぶつかるか。外す hunk を持つ PR の行には `note`（下書き）が要る。ファイルが同じでも hunk がぶつからない PR は外さない。外す物が無ければ `excluded: []`。
- 素材（`material`）の書き方: status は found（見つけた。count と detail）／clean（今ラウンドに見たが無かった。checked に何を見たか）／not_applicable（条件に当たらない。reason）／awaiting_human（人の起動待ち。reason）／not_run（やるべきだったが飛ばした。reason）。carried_over（前の周の流用）は走らなかった節に機械が書く——走った役は今の周の判定を書け（流用と書いても拒まれる）。欄と値の正本は review-record.py。

## 前の返答が拒まれたとき

前の返答を拒んだ理由（初回は空）: $LOOP_PREV.pr-accept.output.reason

理由が空でなければ、そこに挙がった所だけを直して、同じ型でもう一度返せ。
