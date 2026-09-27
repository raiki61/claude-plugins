# 借りた superpowers のスキルを無人の役で読むときの読み替え

対象は superpowers 6.4.2 の写し（`6.4.2/skills/` の 5 本）。写しは直さない。スキルの文が人（your human partner）や調整役（下請けの AI を起こす親の会話）を前提にしている所は、works の無人の役ではこのファイルの決まりで読み替える。スキルの文とこのファイルがぶつかったら、このファイルが勝つ。さらに、役の指示書（`blk-*/commands/*.md`）と節の `output_format` は、このファイルより勝つ。

## 読み方

- 下の見出しが読み替えの決まり。名前（ASK など）は、末尾の「行の索引」が使う。
- 行の索引は、写しの `.md` のうち、人か調整役を前提にする言い回しの目印に当たる行を全部並べる。1 行の形は `<写しの中のパス>:<行番号> [<決まりの名>] <その行の文>`。
- 目印の正規表現は `tests/test_sp_skills.py` の `TRIGGERS`。広めに取るので、語が当たっただけの行もある（決まり NA）。
- 試験（`tests/test_sp_skills.py`）は、目印に当たる行が全部索引に在り、索引の文が写しの行と同じであることを見る。新しい版を写して人への問いが増えたり行が動いたりすると赤くなるので、そのとき読み替えを見直す。
- 走査は `.md` だけ。`systematic-debugging/` の `.ts` と `.sh` はコードの例で、役への指示ではない。

## ASK 人に聞く・確かめてもらう・許しを得る

無人の役には聞く相手が居ない。止まって答えを待たない（待っても答えは来ず、受け付けの輪が上限まで回って run が落ちる）。

- 修正役（`blk-fix` の `fix`）は、直さない単位と理由を `not_done` に書く（`unit_key`・`why`。`why` には何が分からないか・何が要るかを書く）。ただし直す義務の単位（[block] と do-now）の `not_done` は、fork の出どころでない限り受け付けが拒む。義務の単位で判定の前提そのものが疑わしいときは、`rejudge_requested` に理由を書き（再審の道）、この周は判定どおり直す。
- 差分の審査への手直し（`blk-refix`）は、その穴を `declared` で残し、`how` に何が分からないかを書く。
- 読むだけの役（判定・審査）は、分からないまま置いた前提を、返答の型の中の理由の欄に書く。
- TDD の例外（使い捨ての試作・生成したコード・設定のファイル）は、自分で例外と決めて先のテストを省かない。省くなら、省いた理由を返答に書く（TDD の節が入ったら、本線 fix-tdd の `route: direct` の理由の欄に書く）。
- 分からない項目があるうちは実装を始めない、という原則（receiving-code-review）はそのまま効く。分からない項目は上のとおり返答に書き、分かった項目だけを直す。

## THREE-FAILS 3 回直して効かなければ、人と構成を話す

4 回目の直しを打たない。`not_done`（義務の単位なら `rejudge_requested`）に、試した 3 つの直し、それぞれがどこに新しい症状を出したか、構成を疑う理由を書く。ここで数えるのは 1 つの会話の中の直しの試み。受け付けの輪（`loop_group` の `max_iterations: 3`）の出し直しとは別に数える。

## POLICY 人の決めたこと・方針とぶつかる

自分の判断で通さない。どの方針の項とぶつかるかを、修正役は `not_done` に、手直しは `declared` の `how` に書く。方針の文書は書き換えない（`blk-fix/commands/fix.md`・`blk-refix/commands/refix.md` と同じ）。

## COMMIT commit・push・PR・merge

修正役は commit しない。`git add`・`git commit`・`git stash`・`git reset`・`git checkout` で作業ツリーや履歴を動かさず、差分は作業ツリーに残したまま返す（`blk-fix/commands/fix.md` と同じ）。push・PR・merge は役の仕事ではない（線の後ろのブロックと人の関所が持つ）。「commit の前に確かめる」は「返答を返す前に確かめる」と読む。

## SP-REF `superpowers:` の名前での参照

無視する。Archon はプラグインを読まないので、`superpowers:` の付いた名前では何も読まれない。同じ名前のスキルがこの写しに在り、節が `skills:` に宣言していれば、`superpowers:` を除いた名前で Skill の道具から読める。宣言されていなければ読まない。

## DISPATCH 下請けの AI を起こす・調整役として振る舞う

起こさない。役の道具に Agent は無い。別の目の審査は、線の別の節（`blk-delta` の審査役など）が新しい会話で受け持つ。`requesting-code-review/code-reviewer.md` をテストの審査役の手引きに使うときは、`Subagent (general-purpose):` の枠と `description:` の行を読み飛ばし、`prompt: |` の中身だけを手引きとして読む。角括弧の埋め草（`[DESCRIPTION]` など）は、engine が渡す材料で埋まる。

## DELEGATE エージェントの報告を信じない

役の返答は、engine（受け付けの節）が差分と試験を自分で確かめ直す。役は「確かめた」と書くなら、走らせたコマンドとその結果を返答に書く。役がほかのエージェントに仕事を任せることは無い。

## GIT-RANGE git で審査の範囲を取る・差分を出す

審査役は Bash を持たない（`allowed_tools` は Read・Grep・Glob）。範囲の版と差分は engine が切ってファイルで渡すので、そのパスを Read する。`git worktree add` もしない。修正役は git で読む（`git diff`・`git log`・`git show`）のはよいが、HEAD・index・枝は動かさない（決まり COMMIT）。

## GITHUB GitHub のスレッドに返信する

しない。返答は節の `output_format` の JSON だけで、外へ書き込まない。

## PUSHBACK 審査の指摘に反論する

相手に話しかけない。反論は返答の欄に書く。差分の審査への手直しなら、穴の key ごとに `declared` と、`how` に技術的な理由を書く。修正役なら `not_done` か `rejudge_requested` に書く。理由には確かめた事実（ファイルと行・走らせた試験）を書く。

## QUOTE 人の言葉の引用・人との会話の例

引用と例に込めた原則（分からない項目があれば実装を始めない・外の審査は確かめてから直す・要らない物は作らない・モックでなく本物の振る舞いを試す）はそのまま効く。会話の相手は居ないので、例の「聞き返す」は決まり ASK で読み替える。receiving-code-review の「From your human partner」は、works では判定役が出して受け付けが通した単位に当たり、「From External Reviewers」は差分の審査役の指摘に当たる。systematic-debugging の「your human partner's Signals」に当たるのは、受け付けが拒んだ理由のファイル（`reason_file`）。

## OUTPUT 返答の形

`code-reviewer.md` の出力の形（Strengths・Issues・Assessment の「Ready to merge?」）より、節の `output_format` の JSON の型が勝つ。merge してよいかは役が決めない。

## SCENARIO スキルの作者の試験の台本と、作った記録

`systematic-debugging/` の `test-pressure-*.md`・`test-academic.md`・`CREATION-LOG.md` は、スキルを作った人が AI の振る舞いを試した台本と作った記録で、役への指示ではない。`SKILL.md` からも指されていない。読まない。

## NA 語が当たっただけ

人も調整役も前提にしない行（例: 「commit の前にバグを捕まえる」という TDD の利点の説明、「Ask:」で始まる自問）。読み替えは無い。

## 行の索引

```
skills/test-driven-development/SKILL.md:24 [ASK] **Exceptions (ask your human partner):**
skills/test-driven-development/SKILL.md:234 [NA] | "TDD will slow me down" | TDD IS the pragmatic path: catches bugs before commit, prevents regressions, lets you refactor without fear. "Pragmatic" shortcuts mean debugging in production — slower, not faster. |
skills/test-driven-development/SKILL.md:312 [ASK] | Don't know how to test | Write wished-for API. Write assertion first. Ask your human partner. |
skills/test-driven-development/SKILL.md:330 [ASK] No exceptions without your human partner's permission.
skills/test-driven-development/writing-good-tests.md:50 [NA] exit codes. Documents that instruct agents are tested by the consuming
skills/test-driven-development/writing-good-tests.md:51 [SP-REF] agent's behavior (superpowers:writing-skills); prose for humans earns no
skills/test-driven-development/writing-good-tests.md:96 [QUOTE] **your human partner's correction:** "Are we testing the behavior of a
skills/test-driven-development/writing-good-tests.md:126 [NA] production class. Ask: is this method called only from tests? Does this
skills/test-driven-development/writing-good-tests.md:132 [QUOTE] components. **your human partner's question:** "Do we need to be using a
skills/test-driven-development/writing-good-tests.md:154 [NA] trivial code and human prose earn none, and a test written to satisfy
skills/systematic-debugging/SKILL.md:66 [NA] - Git diff, recent commits
skills/systematic-debugging/SKILL.md:165 [ASK] - Ask for help
skills/systematic-debugging/SKILL.md:177 [SP-REF] - Use the `superpowers:test-driven-development` skill for writing proper failing tests
skills/systematic-debugging/SKILL.md:189 [SP-REF] - Use the `superpowers:verification-before-completion` skill before claiming success
skills/systematic-debugging/SKILL.md:196 [THREE-FAILS] - DON'T attempt Fix #4 without architectural discussion
skills/systematic-debugging/SKILL.md:210 [THREE-FAILS] **Discuss with your human partner before attempting more fixes**
skills/systematic-debugging/SKILL.md:233 [QUOTE] ## your human partner's Signals You're Doing It Wrong
skills/systematic-debugging/root-cause-tracing.md:45 [NA] ### 3. Ask: What Called This?
skills/verification-before-completion/SKILL.md:3 [COMMIT] description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always
skills/verification-before-completion/SKILL.md:47 [DELEGATE] | Agent completed | VCS diff shows changes | Agent reports "success" |
skills/verification-before-completion/SKILL.md:54 [COMMIT] - About to commit/push/PR without verification
skills/verification-before-completion/SKILL.md:55 [DELEGATE] - Trusting agent success reports
skills/verification-before-completion/SKILL.md:69 [DELEGATE] | "Agent said success" | Verify independently |
skills/verification-before-completion/SKILL.md:100 [DELEGATE] **Agent delegation:**
skills/verification-before-completion/SKILL.md:102 [DELEGATE] ✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
skills/verification-before-completion/SKILL.md:103 [DELEGATE] ❌ Trust agent report
skills/verification-before-completion/SKILL.md:112 [COMMIT] - Committing, PR creation, task completion
skills/verification-before-completion/SKILL.md:114 [DELEGATE] - Delegating to agents
skills/receiving-code-review/SKILL.md:12 [ASK] **Core principle:** Verify before implementing. Ask before assuming. Technical correctness over social comfort.
skills/receiving-code-review/SKILL.md:20 [ASK] 2. UNDERSTAND: Restate requirement in own words (or ask)
skills/receiving-code-review/SKILL.md:36 [ASK] - Ask clarifying questions
skills/receiving-code-review/SKILL.md:37 [PUSHBACK] - Push back with technical reasoning if wrong
skills/receiving-code-review/SKILL.md:45 [ASK] ASK for clarification on unclear items
skills/receiving-code-review/SKILL.md:52 [QUOTE] your human partner: "Fix 1-6"
skills/receiving-code-review/SKILL.md:55 [ASK] ❌ WRONG: Implement 1,2,3,6 now, ask about 4,5 later
skills/receiving-code-review/SKILL.md:56 [ASK] ✅ RIGHT: "I understand items 1,2,3,6. Need clarification on 4 and 5 before proceeding."
skills/receiving-code-review/SKILL.md:61 [QUOTE] ### From your human partner
skills/receiving-code-review/SKILL.md:63 [ASK] - **Still ask** if scope unclear
skills/receiving-code-review/SKILL.md:77 [PUSHBACK] Push back with technical reasoning
skills/receiving-code-review/SKILL.md:80 [ASK] Say so: "I can't verify this without [X]. Should I [investigate/ask/proceed]?"
skills/receiving-code-review/SKILL.md:82 [POLICY] IF conflicts with your human partner's prior decisions:
skills/receiving-code-review/SKILL.md:83 [POLICY] Stop and discuss with your human partner first
skills/receiving-code-review/SKILL.md:86 [QUOTE] **your human partner's rule:** "External feedback - be skeptical, but check carefully"
skills/receiving-code-review/SKILL.md:98 [QUOTE] **your human partner's rule:** "You and reviewer both report to me. If we don't need this feature, don't add it."
skills/receiving-code-review/SKILL.md:104 [ASK] 1. Clarify anything unclear FIRST
skills/receiving-code-review/SKILL.md:113 [PUSHBACK] ## When To Push Back
skills/receiving-code-review/SKILL.md:115 [PUSHBACK] Push back when:
skills/receiving-code-review/SKILL.md:121 [POLICY] - Conflicts with your human partner's architectural decisions
skills/receiving-code-review/SKILL.md:123 [PUSHBACK] **How to push back:**
skills/receiving-code-review/SKILL.md:125 [PUSHBACK] - Ask specific questions
skills/receiving-code-review/SKILL.md:127 [POLICY] - Involve your human partner if architectural
skills/receiving-code-review/SKILL.md:129 [PUSHBACK] **If you're uncomfortable pushing back out loud:** Name that tension, then tell your partner about the issue you've seen. They'll appreciate your honesty.
skills/receiving-code-review/SKILL.md:173 [ASK] | Partial implementation | Clarify all items first |
skills/receiving-code-review/SKILL.md:174 [ASK] | Can't verify, proceed anyway | State limitation, ask for direction |
skills/receiving-code-review/SKILL.md:198 [QUOTE] your human partner: "Fix items 1-6"
skills/receiving-code-review/SKILL.md:200 [ASK] ✅ "Understand 1,2,3,6. Need clarification on 4 and 5 before implementing."
skills/receiving-code-review/SKILL.md:203 [GITHUB] ## GitHub Thread Replies
skills/receiving-code-review/SKILL.md:205 [GITHUB] When replying to inline review comments on GitHub, reply in the comment thread (`gh api repos/{owner}/{repo}/pulls/{pr}/comments/{id}/replies`), not as a top-level PR comment.
skills/requesting-code-review/SKILL.md:8 [DISPATCH] Dispatch a code reviewer subagent to catch issues before they cascade. The reviewer gets precisely crafted context for evaluation — never your session's history.
skills/requesting-code-review/SKILL.md:15 [DISPATCH] - After each task in subagent-driven development
skills/requesting-code-review/SKILL.md:17 [COMMIT] - Before merge to main
skills/requesting-code-review/SKILL.md:28 [GIT-RANGE] BASE_SHA=$(git rev-parse HEAD~1)  # or: git merge-base origin/main HEAD
skills/requesting-code-review/SKILL.md:29 [GIT-RANGE] HEAD_SHA=$(git rev-parse HEAD)
skills/requesting-code-review/SKILL.md:32 [DISPATCH] **2. Dispatch code reviewer subagent:**
skills/requesting-code-review/SKILL.md:34 [DISPATCH] Dispatch a `general-purpose` subagent, filling the template at [code-reviewer.md](code-reviewer.md)
skills/requesting-code-review/SKILL.md:39 [GIT-RANGE] - `{BASE_SHA}` - Starting commit
skills/requesting-code-review/SKILL.md:40 [GIT-RANGE] - `{HEAD_SHA}` - Ending commit
skills/requesting-code-review/SKILL.md:46 [PUSHBACK] - Push back if reviewer is wrong (with reasoning)
skills/requesting-code-review/SKILL.md:55 [GIT-RANGE] BASE_SHA=$(git log --oneline | grep "Task 1" | head -1 | awk '{print $1}')
skills/requesting-code-review/SKILL.md:56 [GIT-RANGE] HEAD_SHA=$(git rev-parse HEAD)
skills/requesting-code-review/SKILL.md:58 [DISPATCH] [Dispatch code reviewer subagent]
skills/requesting-code-review/SKILL.md:64 [DISPATCH] [Subagent returns]:
skills/requesting-code-review/SKILL.md:79 [DISPATCH] | "I'll just review the diff myself instead of dispatching a reviewer" | You're the coordinator — reviewing the diff inline burns the context window you need to keep driving the work. Dispatch a reviewer subagent: the diff and the evaluation live in its context, and only the findings come back to you. |
skills/requesting-code-review/SKILL.md:91 [PUSHBACK] - Push back with technical reasoning
skills/requesting-code-review/SKILL.md:93 [PUSHBACK] - Request clarification
skills/requesting-code-review/code-reviewer.md:3 [DISPATCH] Use this template when dispatching a code reviewer subagent.
skills/requesting-code-review/code-reviewer.md:8 [DISPATCH] Subagent (general-purpose):
skills/requesting-code-review/code-reviewer.md:29 [GIT-RANGE] git diff --stat [BASE_SHA]..[HEAD_SHA]
skills/requesting-code-review/code-reviewer.md:30 [GIT-RANGE] git diff [BASE_SHA]..[HEAD_SHA]
skills/requesting-code-review/code-reviewer.md:39 [NA] requirement, and a spec's silence is not permission. Grade such
skills/requesting-code-review/code-reviewer.md:52 [GIT-RANGE] Your review is read-only on this checkout. Do not mutate the working tree, the index, HEAD, or branch state in any way. Use tools like `git show`, `git diff`, and `git log` to inspect history. If you need a working copy of a different revision, check it out into a separate temporary directory (e.g. `git worktree add /tmp/review-[SHA] [SHA]`) — never move HEAD on this checkout.
skills/requesting-code-review/code-reviewer.md:54 [DISPATCH] ## You Do Not Dispatch Subagents
skills/requesting-code-review/code-reviewer.md:56 [DISPATCH] Do all of this review yourself. Never spawn a subagent to review part
skills/requesting-code-review/code-reviewer.md:57 [DISPATCH] of the diff, and never spawn another reviewer for a second opinion.
skills/requesting-code-review/code-reviewer.md:59 [DISPATCH] reviewer you spawn duplicates one of them at full cost, and its
skills/requesting-code-review/code-reviewer.md:133 [OUTPUT] **Ready to merge?** [Yes | No | With fixes]
skills/requesting-code-review/code-reviewer.md:157 [GIT-RANGE] - `[BASE_SHA]` — starting commit
skills/requesting-code-review/code-reviewer.md:158 [GIT-RANGE] - `[HEAD_SHA]` — ending commit
skills/requesting-code-review/code-reviewer.md:190 [NA] - Add progress reporting for user experience
skills/requesting-code-review/code-reviewer.md:195 [OUTPUT] **Ready to merge: With fixes**
skills/systematic-debugging/CREATION-LOG.md:57 [SCENARIO] Created 4 validation tests following skills/meta/testing-skills-with-subagents:
skills/systematic-debugging/CREATION-LOG.md:64 [SCENARIO] - User "in a hurry", symptom fix looks easy
skills/systematic-debugging/CREATION-LOG.md:97 [SCENARIO] - ✅ Clarifies relationship to TDD
skills/systematic-debugging/test-pressure-1.md:3 [SCENARIO] **IMPORTANT: This is a real scenario. You must choose and act. Don't ask hypothetical questions - make the actual decision.**
skills/systematic-debugging/test-pressure-2.md:3 [SCENARIO] **IMPORTANT: This is a real scenario. You must choose and act. Don't ask hypothetical questions - make the actual decision.**
skills/systematic-debugging/test-pressure-2.md:40 [SCENARIO] - Commit and go to dinner
skills/systematic-debugging/test-pressure-3.md:3 [SCENARIO] **IMPORTANT: This is a real scenario. You must choose and act. Don't ask hypothetical questions - make the actual decision.**
skills/systematic-debugging/test-pressure-3.md:14 [SCENARIO] You're investigating why the new feature breaks existing user sessions. The senior engineer has been typing in the codebase for 3 minutes while you all watch their screen share.
skills/systematic-debugging/test-pressure-3.md:39 [SCENARIO] - Tech lead approved the approach
skills/systematic-debugging/test-pressure-3.md:46 [SCENARIO] **A) Push back: "I think we should investigate the root cause first"**
skills/systematic-debugging/test-pressure-3.md:56 [SCENARIO] - Tech lead approved
```
