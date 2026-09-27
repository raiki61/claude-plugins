# 借りた superpowers のスキルを無人の役で読むときの読み替え

対象は、利用者が Claude Code に入れた superpowers のスキルのうち、借りる 5 本（`.shared/borrow/borrow.json` の `skills`。`dev/toolset.py` が隔離した設定の `skills/` に写す）。版は利用者が入れた物に従い、works は写しを持たない。スキルの文が人（your human partner）や調整役（下請けの AI を起こす親の会話）を前提にしている所は、works の無人の役ではこのファイルの決まりで読み替える。スキルの文とこのファイルがぶつかったら、このファイルが勝つ。さらに、役の指示書（`blk-*/commands/*.md` と、支度の節が組んで役に読ませる指示書）と節の `output_format` は、このファイルより勝つ。

## 読み方

- 下の見出しが読み替えの決まり。行の番号やスキルの文そのものには結び付けない（スキルは利用者の入れた版で変わる）。当てはまる言い回しを見たら、その決まりで読む。
- `systematic-debugging/` の `.ts` と `.sh` はコードの例で、役への指示ではない。

## 義務の単位の行き先（修正役。どの決まりもこれに従う）

修正の決まりの正本 `blk-fix/rules/common.md`（機械が修正役と TDD の輪の役の指示書に組み込む）と同じ行。受け付け（`fix_covers_open_units`）は、直す義務の単位が `changes` に無ければ、`not_done` に理由を書いても拒む。

- **義務の単位の行き先**: 直す義務の単位（[block] と do-now）は、必ず直して `changes` に 1 行で載せる（人の答えが無いと直し方が決まらない単位だけは、直さずに「食い違いの申し出」で返す）。判定の前提・直し方に疑いが残っても、方針に反しない範囲で一番ましな直しを載せ（根を塞げなければ `root_or_symptom` を symptom にして why に理由を書く）、それが判定のフレーミングへの異議なら `rejudge_requested` に書く（判定役が次に読み直す）。`not_done` に書けるのは、受け付けが免除する単位（問いの台帳で fork の出どころか depends に挙がった単位）と、義務の外の単位だけ。

## ASK 人に聞く・確かめてもらう・許しを得る

無人の役には聞く相手が居ない。止まって答えを待たない（待っても答えは来ず、受け付けの輪が上限まで回って run が落ちる）。

- 修正役（`blk-fix` の `fix`）は、上の「義務の単位の行き先」に従う。直す義務の単位は、分かる範囲で一番ましな直しを `changes` に載せる。人の答えが無いと直し方が決まらない単位は、直さずに食い違いの申し出（`conflicts`。`which_is_right` は unknown）で返す——裁定役が人に回し、最後の人の関所に届く（正本 `blk-fix/rules/common.md` の「食い違いの申し出」）。`rejudge_requested` は判定のフレーミングへの異議だけで、人への問いを書かない（読むのは判定役）。義務の外の単位は `not_done` に理由を書いてよい（`unit_key`・`why`）。
- 差分の審査への手直し（`blk-refix`）は、その穴を `declared` で残し、`how` に何が分からないかを書く。
- 読むだけの役（判定・審査）は、分からないまま置いた前提を、返答の型の中の理由の欄に書く。
- TDD の例外（使い捨ての試作・生成したコード・設定のファイル）に当たるかどうかは、役は決めない。役は先のテストを省かない。省いてよい単位は線の側（修正案の route と機械の決まり。TDD の節が入ったら本線 fix-tdd の `route: direct`）が決める。
- 分からない項目があるうちは実装を始めない、という原則（receiving-code-review）はそのまま効く。分からない項目は上のとおり返答に書き、分かった項目だけを直す。

## THREE-FAILS 3 回直して効かなければ、人と構成を話す

4 回目の直しを打たない。「義務の単位の行き先」に従い、試した 3 つのうち一番ましな直しを残して `changes` に載せ（根を塞げていなければ `root_or_symptom` を symptom にする）、試した 3 つの直し、それぞれがどこに新しい症状を出したか、構成を疑う理由を `rejudge_requested` に書く。義務の外の単位なら、同じ理由を `not_done` に書いて直しを打ち切ってよい。ここで数えるのは 1 つの会話の中の直しの試み。受け付けの輪（`loop_group` の `max_iterations: 3`）の出し直しとは別に数える。

## POLICY 人の決めたこと・方針とぶつかる

自分の判断で通さない。修正役は「義務の単位の行き先」に従う: 直す義務の単位は、方針に反しない範囲の直しで閉じるならそれを `changes` に載せ、閉じないなら直さずに食い違いの申し出（`between` に方針の文書の行を含め、`which_is_right` は unknown）で人に回す。義務の外の単位なら `not_done` に書く。手直しは `declared` の `how` に書く。方針の文書は書き換えない（`blk-fix/rules/common.md`・`blk-refix/commands/refix.md` と同じ）。

## COMMIT commit・push・PR・merge

修正役は commit しない。`git add`・`git commit`・`git stash`・`git reset`・`git checkout` で作業ツリーや履歴を動かさず、差分は作業ツリーに残したまま返す（`blk-fix/rules/common.md` と同じ）。push・PR・merge は役の仕事ではない（線の後ろのブロックと人の関所が持つ）。「commit の前に確かめる」は「返答を返す前に確かめる」と読む。

## SP-REF `superpowers:` の名前での参照

無視する。Archon はプラグインを読まないので、`superpowers:` の付いた名前では何も読まれない。同じ名前のスキルが隔離した設定に在り、節が `skills:` に宣言していれば、`superpowers:` を除いた名前で Skill の道具から読める。宣言されていなければ読まない。

## DISPATCH 下請けの AI を起こす・調整役として振る舞う

起こさない。役の道具に Agent は無い。別の目の審査は、線の別の節（`blk-delta` の審査役など）が新しい会話で受け持つ。`requesting-code-review/code-reviewer.md` をテストの審査役の手引きに使うときは、`Subagent (general-purpose):` の枠と `description:` の行を読み飛ばし、`prompt: |` の中身だけを手引きとして読む。角括弧の埋め草（`[DESCRIPTION]` など）は、engine が渡す材料で埋まる。

## DELEGATE エージェントの報告を信じない

役の返答は、engine（受け付けの節）が差分と試験を自分で確かめ直す。役は「確かめた」と書くなら、走らせたコマンドとその結果を返答に書く。役がほかのエージェントに仕事を任せることは無い。

## GIT-RANGE git で審査の範囲を取る・差分を出す

審査役は Bash を持たない（`allowed_tools` は Read・Grep・Glob）。範囲の版と差分は engine が切ってファイルで渡すので、そのパスを Read する。`git worktree add` もしない。修正役は git で読む（`git diff`・`git log`・`git show`）のはよいが、HEAD・index・枝は動かさない（決まり COMMIT）。

## GITHUB GitHub のスレッドに返信する

しない。返答は節の `output_format` の JSON だけで、外へ書き込まない。

## PUSHBACK 審査の指摘に反論する

相手に話しかけない。反論は返答の欄に書く。差分の審査への手直しなら、穴の key ごとに `declared` と、`how` に技術的な理由を書く。修正役は「義務の単位の行き先」に従う: 直す義務の単位への反論は `rejudge_requested` に書き、その単位は `changes` に載せる。義務の外の単位なら `not_done` に書く。理由には確かめた事実（ファイルと行・走らせた試験）を書く。

## QUOTE 人の言葉の引用・人との会話の例

引用と例に込めた原則（分からない項目があれば実装を始めない・外の審査は確かめてから直す・要らない物は作らない・モックでなく本物の振る舞いを試す）はそのまま効く。会話の相手は居ないので、例の「聞き返す」は決まり ASK で読み替える。receiving-code-review の「From your human partner」は、works では判定役が出して受け付けが通した単位に当たり、「From External Reviewers」は差分の審査役の指摘に当たる。systematic-debugging の「your human partner's Signals」に当たるのは、受け付けが拒んだ理由のファイル（`reason_file`）。

## OUTPUT 返答の形

`code-reviewer.md` の出力の形（Strengths・Issues・Assessment の「Ready to merge?」）より、節の `output_format` の JSON の型が勝つ。merge してよいかは役が決めない。

## SCENARIO スキルの作者の試験の台本と、作った記録

`systematic-debugging/` の `test-pressure-*.md`・`test-academic.md`・`CREATION-LOG.md` は、スキルを作った人が AI の振る舞いを試した台本と作った記録で、役への指示ではない。`SKILL.md` からも指されていない。読まない。
