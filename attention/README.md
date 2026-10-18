# attention

Tools for **getting an overview of parallel work and getting back into it**. One command gives the overview and two commands get you back in. **Each of the two covers a different thing you have lost.** The plugin also has `/my-turn`, which moves your turn forward after you are back, and `/reflect`, which looks back over a period and gives improvement proposals and observations.

The instructions and descriptions of the commands are written in Japanese, and so is most of their output.

Changes in each version are in [CHANGELOG.md](CHANGELOG.md). How versions are released (the step that adds to the change log; no git tags are created) is in [docs/releasing.md](../docs/releasing.md). That path is relative to the repository root and is not part of the installed plugin; read it in a clone or on GitHub: https://github.com/raiki61/claude-plugins.

| Command | When to use it | What you have lost |
|---|---|---|
| `/whose-turn` | Overview of everything | **What is open, and whose turn** |
| `/catchup [number] [指摘・地図・CI]` | Back to one item (HTML page) | **Where you stopped; what the PR is for** |
| `/what-am-i-doing` | Back to a session | **What this thread was for** |
| `/my-turn` | Move your turn forward | (How to proceed after you are back) |
| `/reflect [period]` | Day or week review (HTML page) | **What you repeat and what to fix** |

Details for the table:

- `/catchup` gets you back to one PR / issue, a branch, a commit (or a commit range), or a topic in the conversation. It moves to the matching branch, fetching it from origin if it is not local. The reply is one HTML page. What you have lost is **where in the conversation you stopped**, and **what you were told, and what the PR changes and why**. The optional words 指摘 (review comments), 地図 (map) and CI narrow the material.
- `/what-am-i-doing` is for when you switch sessions and come back. What you have lost is **what work this thread was doing**.
- `/my-turn` is for after `/catchup` has brought you back to one item and you move that turn forward. It digs into the review comments, compares them with known solutions elsewhere, and, if you are the reviewer, drafts review comments.
- `/reflect` is for looking back at the end of a day or a week. The reply is one HTML page; if you have set a place for a diary, it also writes to the diary. What you have lost is **what you keep repeating, where you spend effort, and what fix would pay off**.

## Installation

```
/plugin marketplace add raiki61/claude-plugins
/plugin install attention@raiki61
```

## What problem it solves

When you run several pieces of work in parallel, the first thing you have lost when you come back is **where in the conversation you stopped**, and you cannot recover it without rereading the GitHub page from the top. You have also forgotten what you were told and what the PR changes, even for your own PR. If you had not forgotten, you would not call a tool to get back. So the tool shows the position first, then explains the content for a first-time reader from the author's own text, and then appends the actual lines, as many as there are.

The same happens with sessions. With dozens of terminals open, **you no longer know what work a tab was doing.** You end up asking "what was I doing here?" every time.

In both cases, what you need first is **the position**. The content is explained in the author's words, and the lines are attached as they are, not summarized.

And before getting back, you need to see **what is open and where** all at once. `/whose-turn` fetches all open PRs and issues and works out by machine "whose turn it is, and why it is that person's turn now". The three commands are used in the order **everything → one item → session**. The prior art is the Attention Set in Gerrit / Google Critique, which is where this plugin's name comes from.

## `/whose-turn` — from all open items, show whose turn it is

### Usage

```
/whose-turn            # 自分
/whose-turn <login>    # 他の人
/whose-turn --all      # 全員分を人別に
```

(`/whose-turn` alone is for yourself, `<login>` for another person, `--all` for everyone, grouped by person.)

It fetches all open PRs and issues of the repository you are in, decides by machine for each PR whether "someone is waiting for you / it has not been handed to anyone yet / it cannot move until the other side acts", and reports it in two sections: **your turn** (自分の番; things you can move today) and **their turn** (相手の番; things that cannot move until the other side acts). It also adds mentions (where you were called with @login and have not replied) and issues assigned to you. Day counts are "since it entered its current state", not since the PR was created. When people other than the author are the only assignees of a PR, the author's turns (draft, CI red, changes requested, merge, never asked, and so on) move to those people: the author has handed the PR over, following GitHub's definition of an assignee (the person working on it). Copilot and other bots, mannequins (placeholder accounts for history imported from another service) and deleted accounts are not counted as people: if only bots are assigned, the author keeps the PR, and if people and bots are mixed, it moves to the people only. On GitHub servers that do not return the kind of assignee (no `assignedActors`), nothing moves, and "what was not looked at" says so. In unresolved threads between the author and the assignee, the person who was asked has the turn to reply, and the person who asked gets the turn to check the reply; both show on their own rows. The rows say `担当として受けた PR（起票は X）` ("PR received as assignee, opened by X") for the person who received it and `担当に渡した PR（担当は X）` ("PR handed to assignee X") for the author who handed it over. When the author is also an assignee, the author keeps the PR, and a PR nobody was asked to review stays under "not handed to anyone yet". When changes were requested and every person who requested changes (their latest review, not counting those who approved later) has been asked to review again, it is the reviewers' turn, not the holder's turn to address the review; what a requested reviewer said before the request does not count as their last word. `/catchup` decides who holds a PR with the same rules (the shared module `scripts/lib/turn.py`).

### Division of work

- **Script (machine)**: fixes the population and outputs all the material for judgment. It does not judge
- **AI**: reads the material and decides "does this need a reply" or "is it just look-and-close". It does not add to or remove from the population

The output is split in two by the marker `==== ここから下は判定の材料。貼らない ====` ("below this line is material for judgment; do not paste"). Above it is the report; below it are the mention posts and the full text of the threads. The AI does **not paste** this. Instead, it writes about 50 lines in 5 sections divided by what the reader has to do: **your turn** (everything you can move today; line 1 is the number and title, line 2 is the day count, role, action, and reason), **their turn** (a list of numbers and titles grouped by role, plus only the items where facts in the output contradict each other, such as "approved, but unresolved threads remain" or "a review was requested, but the other side has been silent for days"), **assigned issues**, **mentions you do not need to answer**, and **what was looked at**. A number always comes with a **title** (a noun phrase that shortens the machine's title to about 8 full-width characters). A line with only a number forces the reader to look up what the item is. Numbers are written as `[#number](URL)` links. The machine prints the URL on line 2 of each row (in terminals that support it, only the number is shown and you can click it to open; otherwise it expands to `#number (URL)`).
Rows for other people's PRs (where you are the reviewer) get a line 3 with one sentence from the author's description and the size (N files +A/-D). With only a title, the next question would be "what is in it?". **Each number has a row in only one section**, and a mention that needs a reply is merged into that PR's row. (If sections were split by where the signal came from, the same number would appear 2 or 3 times and the reader would have to match them up by eye.) The action is chosen from a closed vocabulary of 9 terms: レビュー (review), 再レビュー (re-review), 指摘に答える (answer review comments), 判断を返す (return a decision), 返信する (reply), 見て閉じる (look and close), マージ (merge), 依頼先を決める (decide whom to ask), CI を直す (fix CI). Reading down that column alone tells you which items finish quickly and which need real time. The order stays exactly as the script printed it; the AI does not reorder, so that the reader can check it against the machine output. Day counts and item counts use the machine's numbers as they are. The full machine output is pasted, without changing a single character, only when you say "全文を見せて" ("show me the full text"). **The population and "what was not looked at" are always stated, even briefly**. That is where the reader checks where the holes in the judgment are.

For two of the blind spots, namely whether you are included in a review request addressed to a Team, and whether your last body comment answers the other side's question, the AI goes and checks them with **a fixed procedure, up to 5 items each**, and writes the ones whose judgment changed in the "blind spot check" (死角の確認) section. Other blind spots (outside GitHub, notifications, no assignee set) are not checked; the report says they cannot be checked.

### Bundled script

```
python3 scripts/whose-turn.py [login] [--repo OWNER/NAME] [--all] [--materials] [--out]
python3 scripts/whose-turn.py [login] [--repo OWNER/NAME] --json [--all] [--materials] [--out]
```

`--json` outputs the same content as the report as JSON, with keys instead of text layout: `sections` (per person, the "your turn" and "their turn" PRs with number, URL, title, author, role, day count and fact lines; role is `implementer` when that person holds the PR, as its author or as the assignee who received it, and `reviewer` otherwise), `waits` (unanswered mentions, with the same role for PRs), `assigned_issues`, `scope`, `limits`, `blind_spots` and `not_seen`; with `--materials`, also the full texts (`waits[].text` and `threads`). The skill reads this JSON. `prs` keeps the earlier shape for other tools (works-dispatch): only your "your turn" PRs (number, URL, title, head branch, role, day count), in the same set and order as the "your turn" section of the report. `limited` lists the numbers of open PRs where the data the judgment uses hit a fetch limit (comments, reviews, threads or checks not fully read, or exactly 100 timeline events, the most the query takes), including PRs that are not in `prs`; whether such a PR is your turn may be wrong. Reaction limits are not counted, because reactions do not affect the judgment.

The definitions of the judgments and what is not looked at are in `--help`. The script's judgment of whose turn each PR is (the sections and rows of the report) is a pure function, and `tests/whose-turn-suite.py` pins its rules one line at a time (193 cases). The AI then only reads the materials to classify the mentions and threads, as the skill describes. All times, in headings and rows, are shown in local time.

Only this command runs on sonnet (the `model` in the command definition). The AI's job is to apply the rules to the material and sort it; it does not need a higher model's reasoning, and it is kept light because it is meant to run every day.

## `/catchup` — get back to one PR / issue

The authoritative description of what it takes in, what it does, and what it returns is [docs/catchup-spec.md](docs/catchup-spec.md) (the table of inputs, the table of sections, limits and how to get the rest, and differences from the current state). What follows is a summary of that and how to use it.

### Usage

```
/catchup 1505                 # 番号か URL（該当ブランチへ git switch で移る。手元に無ければ origin から取る）
/catchup                      # 今のブランチの PR（無ければブランチ名の番号を issue と見る）
/catchup 1569 指摘             # 焦点の語を後ろに付けると、末尾の材料をその 1 つに絞る（指摘・地図・CI）
/catchup 新しく出たもの        # 番号でない語は会話の中の話題（会話が材料。番号に結び付いていれば機械で補う）
/catchup setup                # VS Code で見る準備（拡張と設定 2 つ。下の「前提（HTML で見る）」）
```

In order:

- A number or URL: moves to the matching branch with git switch, fetching it from origin if it is not local.
- No argument: the PR of the current branch. If there is none, the number in the branch name is treated as an issue.
- A focus word after the number narrows the material at the end to that one kind: 指摘 (review comments), 地図 (map), CI.
- A word that is not a number is a topic in the conversation (新しく出たもの, "the new ones", is an example). The conversation is the material; if the topic is tied to a number, the machine fills in the rest.
- `setup`: prepares viewing in VS Code (an extension and two settings; see "Prerequisites (viewing as HTML)" below).

**The reply is one HTML page.** The terminal shows only the page's path and a one-line summary. (This started on 2026-10-15. Before that it was long prose in the terminal: 4,000 to 28,000 characters per item, median about 15,000, and about 90% of it was code the AI had just copied from the machine's frames.) The machine draws the page from a fixed template (`templates/catchup.html`), and the AI writes only small fields: whose turn, since last time, what is blocking, next step, explanation, figure. The page is stored at `~/.cache/attention/catchup/<owner>-<repo>/<番号>.html` (`<番号>` is the item number; the same item overwrites its page). An `index.html` in the same place lists the drawn pages, one row per item (item, title, whose turn, next step, updated).

### Prerequisites (viewing as HTML)

This format assumes the following viewing setup:

- You are connected with **VS Code Remote-SSH** to the machine where catchup runs (the page is written to that machine's `~/.cache`)
- The extension **Simple HTML Viewer** (`austin-spagnolo.simple-html-viewer`) is installed on the Remote side
- Two entries in the Remote Machine settings (`~/.vscode-server/data/Machine/settings.json`): in `workbench.editorAssociations`,
  `"**/.cache/attention/**/*.html": "simpleHtmlViewer.preview"` (opens catchup pages with the extension), and
  `"simpleHtmlViewer.autoRefresh": "onFileChange"` (an open page changes when it is redrawn)
- The workspace is trusted (by default the extension runs the page's scripts only in trusted workspaces)

`/catchup setup` (`catchup.py --setup`) finds the live windows, installs the extension if it is missing, adds the two settings (without deleting other keys, and saving a backup before writing), and draws and opens a sample page. To only check without changing anything, use `--setup --check`.

After drawing, the machine opens the page in every live VS Code window (it tries every socket for which `code --status` succeeds; a conversation inside herdr (a terminal multiplexer) may have inherited an old socket). With `ATTENTION_CATCHUP_OPEN=0` it does not open the page (for example, in conversations that works-dispatch, another plugin in this repository, starts). What you see degrades in this order of completeness: the page drawn by the extension inside VS Code → if the extension or the settings are missing, the HTML source opens → if VS Code is not connected, only the path is printed. **The page is a single HTML file that loads nothing from outside**, and opens in any browser (diff2html for drawing diffs and highlight.js for syntax colors are embedded inside, at pinned versions).

**There are 6 kinds of target: a number, a URL, a branch name, no argument (`this`), a commit, and a topic in the conversation.** When you pass only a number, it looks at the repository you are in. For an item in another repository, pass a URL or add `-R owner/repo`. With no argument (also when there is only a focus word), the target is the PR of the current branch. If there is none, the number in the branch name (`chore/1513-…` → #1513) is treated as an issue, and the local state (commits not pushed, the uncommitted tree) is appended at the end. On a branch with neither a PR nor a number (for example, work in progress on main), it does not ask GitHub and outputs only the local state and the content of the uncommitted changes (the same frames and jump targets as `/what-am-i-doing`). It does not stop, because stopping would return nothing to someone in the middle of writing.
When you pass a branch name, it moves to that branch first (if the branch is not local and exists only on origin, it creates a branch that tracks origin/<name>) and then resolves it the same way as no argument.
On a branch with neither a PR nor a number, the changes in the commits ahead of the default branch (the diff of the whole branch) are also shown as a tree and frames.
When you pass a commit (a sha, `HEAD~2`, a tag), it shows that commit in the same form: subject and body, a tree of changed files, and the content of the changes (frames and jump targets). This is the way to reread changes in a workflow that commits directly to the default branch without opening a PR. A commit range
`A..B` (`2971ea2..HEAD`, `HEAD~4..HEAD`) has the same form; the diff is between the A version and the B version, and the body is the subject of each commit.
A word that is not a number ("今の修正" "the current fix", "さっきの 4 件" "the 4 items from earlier") is first resolved to what it is tied to in the conversation. If it is tied to a number, a branch, or a commit, that is the target (if several commits were made in this session, the range from the oldest^ to the newest), and the output goes as far as the explanation and the map, just as when called directly. Only for topics that exist only in the conversation (such as a bundle of review findings) does it use `what-am-i-doing.py --topic "<語句>"` (`<語句>` is the phrase), taking the exchanges where that phrase appeared as the backbone and writing in the same form.

**When called with a number or URL, it moves to the matching branch** (the command definition file adds `--switch`). For a PR, this is the head branch; for an issue, it is the local branch whose name contains the number, when there is exactly one. It moves because when you come back to a PR or issue after working on something else, your local checkout is usually still on the other work's branch: you have lost not only your place in the conversation but also the branch, and moving puts you back on it. If the PR's branch is not local, it fetches just that one source from origin, creates the branch, and moves to it. The name and the tracking target are the same as `gh pr checkout` (for a PR from the same repository, `<head>` tracking `origin/<head>`; for a fork PR, `<head>` from `refs/pull/<number>/head`. If head is the default branch name, `<fork owner>/<head>`. If origin is your own fork (a triangular workflow), PRs from that fork are treated the same as PRs from the same repository).
Issue branches are not searched for on origin (choosing by number would be guesswork).
The reason it moved or did not move appears in the "branch" (ブランチ) row of the heading (when it did not move, also where you are now), and when it moved (or was already there), the local state is appended at the end. It does not move when tracked files have uncommitted changes (git silently carries them over unless they conflict, which leads to accidentally committing on another branch; if there are only untracked files, it moves), during a merge / rebase / cherry-pick, when the branch is checked out in another worktree, when it no longer exists on origin either (a merged PR whose branch was deleted; the row says how to get it), when the fetch fails (authentication fails without prompting in the terminal), and for a fork PR when the local branch with the same name does not contain the head commit (fork heads come with names like trunk / main). **The only things that change your local checkout are this `git switch` and that one
`git fetch`**, and existing local branches are not moved (no pull, merge, stash, or commit. The fetch updates only the
`origin/<head>` tracking ref). To go back, use `git switch -` (the original branch name remains in the row; a branch created from origin stays).
After moving, `/catchup` (no argument) points to the branch you moved to.

If several sessions share the same checkout, `/catchup` in one changes the branch of the other. It does not move if there are uncommitted changes, but it cannot protect a session that has committed and paused. To separate them, use `git worktree` (it does not move to a branch checked out in another worktree). If it did not move because of `Unable to create '…/index.lock'`, another session is in the middle of running git.

The page shows **the actual lines, all of them if there are any** (drawn by the machine; the AI does not copy them). The text material the AI reads gets the same things, in this order. `指摘` (review comments): for each unresolved thread, the full text of the other side's last comment and the whole function containing that line at head (with line numbers; common indentation is removed and string literals in assignments are folded; for files with no boundaries, 5 lines before and after. For items where it is my turn to reply and the other side replied after my comment, the whole function with a band over the changes since my comment, instead of the current state). This appears if there are unresolved threads with humans in them. `CI`: for each failed check, the log of the failed step up to the last `##[error]` (the job, step, and time at the start of each line are removed). This appears if there is red. `地図` (map): a tree of all changes and the skeleton of each file (always, for a PR). It does not vary by whether you are the author. Calling `/catchup` itself is a sign that you have forgotten the content, even of your own PR (measured: on your own PR the tree was not shown, and you wanted it). Adding a **focus word** at the end narrows it to that one kind (when in a hurry). If there is no material of that kind, a one-line "none" is shown.

The "what this PR does" (この PR がすること) part of the page contains **the explanation**: what this PR changes, why, and how, aimed at an engineer seeing this item for the first time. It consists of a one-line summary, a figure, a list of the terms in this section, 4 to 6 paragraphs of prose (premise / background and problem / what changes and how / what changes for users and what is not included; 400 to 1600 characters; no paths or function names, and terms that only make sense inside this repository are explained on first use), and the change points (listed as the figure's legend; clicking a box or a line in the figure shows the before and after next to it;
the diff opens in a large window only when you press the button). The AI writes it. The figure's lines (the flow of data) can also show code this PR does not change, such as the type of the receiving API, drawn from the PR's head version. If the premise is not in the description, it is filled in from the top of the README and the top of the files of the components being touched. The material is printed by the machine at the start of the end section:
the author's description (up to 60 lines; all of it with `--full`), the beginning of the issues it closes and the issues the description points to, and the leading comment of the map
(measured: for a PR with 28 files and +1030 lines, the 1 to 2 sentences the format provided and the 1 sentence of the map were not enough for a first-time reader to understand the content).

You can also run the script directly.

```
python3 scripts/catchup.py [1505|URL|this|<commit>] [指摘] [地図] [CI] [--switch] [-R owner/repo] [--full] [--limit 12] [--me <login>] [--frame path] [--out]
python3 scripts/catchup.py --render <描く材料.json> <欄.json>   # ページを描いて一覧を組み直し、VS Code で開く。出すのは path と 1 行
python3 scripts/catchup.py --setup [--check]                     # VS Code で見る準備
```

(`--render <drawing material JSON> <fields JSON>` draws the page, rebuilds the index, and opens it in VS Code, printing the path and one line. `--setup` prepares viewing in VS Code.)

Only with `--switch` does it change your local branch (by default it only reads). With `this` it does nothing. `--out` writes, along with the text material, the structure that the page template draws (the drawing material) as JSON to a temporary directory and prints its path. The shape and checks of the fields JSON are in sections 5.1 to 5.3 of
[docs/catchup-spec.md](docs/catchup-spec.md).

What follows is the content of the text material the AI reads (what is printed when you run the script directly).

The description material is the author's description (up to 60 lines; all of it with `--full`) and the beginning (12 lines) of the bodies of the issues it closes and the issues / PRs the description points to with # (up to 3). It is printed at the start of the end section regardless of focus. The map material is the changed files and their ± line counts, existing files in the same directory, name mentions (added lines that contain the name of another changed file, with those lines; a hint at what calls what), the leading comments and skeletons of new files, and the changes to existing
files. Changes to existing files are **not a diff but "the current state with bands added by the machine"**: the whole function (`git diff -W`), in a form you can paste as is into a frame colored for that language. Inside the solid frame `┏ … ┗` is what changed; faint lines starting with `#│` (the comment marker plus `│`) are before, colored lines are now, and the dotted line `┅` is a folded section (a terminal version of the IntelliJ gutter. In a unified diff, `@@` means nothing to a person, and `+`/`-` remove the syntax colors). Prose and settings (md, json, and so on) come out in the same form. They have no function boundaries, so the machine cuts them with 10 lines of context
(the content of the map is not varied by file type; if it were, a repository mostly made of md would be left with only the tree).
Every frame is preceded by `飛び先 path:行` ("jump target path:line"; the head line number. When the AI copies it into a heading in backticks, you can click it in the terminal to open it.
Only files deleted entirely do not get one).
Showing whole functions requires the local checkout to have the base and head commits; if it does not, the same form is built from `gh pr diff` with 3 lines of context, and the output says so. A long function over 200 lines is folded, keeping 30 lines before and after the change. If one file exceeds 300 lines, it stops at a function boundary; for the rest, use `catchup.py <番号> --frame <path>` (`<番号>` is the item number).
Existing files in the same directory are shown only when the local checkout is that repository's checkout (otherwise it says they "cannot be shown").
The head line for a review comment comes from `git show` if the local checkout is that repository's checkout and has that commit (uncommitted
edits are not mixed in); otherwise it is fetched from GitHub.

For a PR, the machine adds 4 more kinds of material. All are facts only; judgment is left to the AI.

- **飛び先 (jump target)**: before each frame of changes, `飛び先 path:行` (the head line number; the start line on the new side of the hunk. For a new
  file, `path:1` at the start of the leading material). The AI copies it into the heading of the location and into the notes for the second and later frames of the same file. Only files deleted entirely do not get one, because they no longer exist at head and cannot be opened
- **取り込み先 (merge target) / that branch's PR / 上に積む (stacked on top)**: only when base is not the default branch, "いまの状態" (current state) gets `取り込み先` and the PRs in the same repository whose head is that branch (up to 3; state, approval, author; if none, "none"). Open PRs that use this PR as base are listed under "つながっている先" (connected items) as `上に積む` (up to 3). A stacked PR does not get into the default branch until the one below it is merged
- **依頼先の候補 (reviewer candidates)**: one line with the reviewers GitHub suggests for the PR (suggested reviewers) and why each is suggested (commented on this PR, committed to the changed files). Who to ask is decided by me, not by the AI. The line appears only on a PR I hold (my own PR, or one I received as an assignee from an author who did not assign themselves) with no review request open now (requests to bots such as Copilot do not count; a request to a person still counts when a bot was also asked), and only in one of these cases:
  - no review request to a person was ever recorded
  - a request to a person was removed before anyone reviewed

  It does not appear in two cases:
  - someone other than the author reviewed after I asked. GitHub removes a reviewer from the request list once they submit a review, so the empty list does not mean "nobody was asked". The machine says it is my turn to request again or to answer the review
  - I never asked, someone other than the author is the only assignee, and nobody has reviewed yet. The machine shows the PR as waiting on that assignee (`担当 X 待ち`, "waiting on assignee X"); the assignee's `/catchup` shows the candidates, because the person who received the PR decides whom to ask. Only people (User accounts) count as assignees here: if only Copilot or other bots are assigned, the author still gets the candidates

  Who holds the PR follows `/whose-turn`: on a PR handed to an assignee, draft, CI red, conflicts, changes requested and merge are the assignee's turn (`CI 赤は担当（私）しか外せない`, "only the assignee (me) can fix the red CI"). If I asked someone or someone other than me reviewed before handing it over, deciding whom to ask stays with me as the author. "Changes requested" is not shown as my turn when everyone who requested changes has been asked to review again

  Whether I asked is read from the newest 100 review-request events. When older events may exist, the machine adds an item to its "見ていないもの" (what was not looked at) section at the end of the output
- **私の痕跡以降に変わった file (files changed since my last trace)**: based on the commit that my last trace (a review, the first comment in a thread, a push) points to, the files touched by the author's commits after it (for merge commits that pull in other branches, only their number is shown, not their files), with state (M/A/D…) and path. When the base is a body comment or a thread reply that is not tied to a commit, the commit closest by date is used as the base and the output says "approximate" (近似). If the base commit is not among the commits fetched (the newest 100), it tells by the total count whether history was rewritten (rebase) or it is outside the window, in one line; when it cannot tell whether history was rewritten, it says so. If the local checkout is that checkout, it runs
  `git log --name-status` once; otherwise it fetches each commit from GitHub (up to 20; the rest go under "見ていないもの" (what was not looked at))

The only dependencies are `gh` (authenticated) and `python3`. **"I" (私) is the `gh` authenticated user.** Pass `--me` only when you want to view it as someone else.

If you commit with an email not linked to GitHub, the commit author is empty on GitHub (only the name and email remain).
Commits matching the local `git config user.email` are counted as your own pushes. Without this, your own pushes would be mixed into "その後に起きたこと" (what happened after) as someone else's events, and "私が最後にしたこと" (what I did last) would look older than it is (measured: off by a month).
Names are not matched (that would make a push by someone else with the same name mine). The config used for matching is the one where the command runs, so unlinked commits that did not match are reported by name under "見ていないもの". When `--me` is passed, no matching is done.

### What comes back

**One page.** From the top, it is arranged in 3 tiers by reading time. 5 seconds: **the current turn** (whose turn, your position, one sentence, next step, and the row of what is blocking; these rows are lined up in the same order as the merge box at the bottom of a GitHub PR page; state values appear only in this row). 1 minute: **since last time** (the hand-offs of the turn, in the same vertical order as the GitHub PR conversation, plus short sentences on what was done last and the cause of what is blocking) and **what this PR does** (a figure whose form is chosen by the content, an explanation that starts from the premise, and change points whose diffs you can open). 5 minutes: **review comments**
(the same form as GitHub review threads: a diff excerpt, my last comment and the other side's in Markdown, and whether the file changed since last time), **CI** (the end of the log for each red check), **changes** (a diff you can switch between "since last time" and "whole PR"; the form of GitHub's Files changed), and **local**. At the end is what was not looked at.
The terminal gets only the path and one line:

```
/home/me/.cache/attention/catchup/example-app/482.html
#482 fix(api): 添付ファイルの取りこぼしを塞ぐ — 私の番。次: e5096175 を読み、[block] の直しを確かめる
```

The AI writes only the fields JSON, using the machine output (the author's description is also printed at the end) as material, and checks what is missing (why CI failed, whether the request has been handled) before writing. Each field holds one paragraph of the old prose:

```json
{
  "headline": "#1276（現場コネクタの要件の下書き）は私の PR で、動かすのは私のもう 1 本の PR #1596 の側。#1596 にレビュー依頼を出せば進む。",
  "where": "2 日前（9/1）に main を取り込んで push した。その後は誰も動いていない。8/27 の 250489 さんの申し送りは 9/1 の取り込みで済んでいる。手元は main から docs/1276-connector に移した。",
  "turn": "止めているのは CI の赤 3 本で、全部同じ文書検査。下書きを規則の対象から外す #1596（私の PR、レビュー依頼が未送）が通れば消える。承認はまだ無く、衝突も返事待ちの指摘も無い。",
  "next": ["#1596 のレビュー依頼を出す", "通ったら main を取り込み直す", "緑を確認する", "#1276 のレビュー依頼先を決める"],
  "lead": "…（初めて見る人に、どこの何をどう変えるかを 1 文で）",
  "figure": {"kind": "graph", "caption": "…", "nodes": [{"id": "a", "text": "…"}, {"id": "b", "text": "…", "in": "after"}], "edges": [{"from": "a", "to": "b", "in": "after"}]},
  "explain": ["前提", "背景と課題", "何をどう変えるか", "使う側から見た変化と、含まれないもの"],
  "points": {"items": [{"title": "…", "before": "…", "after": "…", "code": [{"path": "…", "find": "…"}]}]}
}
```

`headline` alone covers what the reader needs: their position, where it is stuck (I act on this item / the place to act is a different number / waiting on the other side / nobody's turn), and the one step. The order of the fields follows the hand-off format SBAR: `where` is what was done last (background), `turn` is what is blocking (assessment), and `next` is what to do next (recommendation). The same number is explained only once. The style is plain form, short sentences.

#### The basis for this format

(The following is the basis for the format from when it was prose in the terminal. The order and content rules of the fields still follow it. The parts tied to monospace and a single screen, namely line length and "speak to the reader in prose", are now handled by the machine's template, since the output became a page.)

The format is not a new invention. Fixed formats for handing stopped work to a person already exist, and the fields and their order come from them. What is left to design is only fitting it to the conditions of the medium, "monospace, Japanese, one screen, the reader is yourself", and that too is settled by established knowledge. The source of each rule (checked against primary sources; the conditions of application are noted too):

- **The conclusion on line 2**: the US Army writing regulation AR 25-50 (2020 edition, 1-38b) requires putting the main point at the beginning ("bottom
  line up front") together with the active voice. The US federal Federal Plain Language Guidelines (2011) also say
  "put the most important information first, background later". Both apply to official documents and letters, and are practice, not legal obligations
- **The order of the fields follows the hand-off format SBAR** (Situation → Background → Assessment → Recommendation):
  line 2 is S, "what I did last" is B, "what is blocking" is A, "what to do next" is R. SBAR was brought into healthcare by
  Kaiser Permanente in 2002, and comes from the reporting habits of US Navy submarine crews (personal practical experience, not an official
  procedure). "State" is separated from A because SBAR separates observation (S, B) from judgment (A).
  The writer is an AI and its judgment can be wrong, so the reader needs to know which rows to doubt
- **Do not remove fields; write "none"**: the hand-off format I-PASS includes the receiver's read-back (synthesis by receiver)
  as a component, and among residents at the 9 children's hospitals that adopted it, medical errors fell by 23% (Starmer et al., NEJM 2014).
  One-way text cannot use read-back, so detecting omissions relies on stating "not applicable" explicitly
- **Paragraphs of at most 4 sentences, sentences of about 40 characters**: the W3C Requirements for Japanese Text Layout (JLReq) put a horizontal line at a maximum of about
  40 characters, and Bringhurst for Western text gives 45 to 75 characters, ideally 66 (assuming a single column and body text size). In a terminal,
  the renderer wraps by width, so line length cannot be specified. Instead, sentences are cut to about 40 characters as the amount the eye follows in one breath, and
  paragraphs are kept short (GOV.UK suggests considering a split above 25 words)
- **Explain an item number (PR / issue number) on first use, and only use the number after that**: the experiments of Haviland & Clark (1974) showed that when the antecedent of a sentence's given information is
  directly in the preceding context, reading is faster than when it has to be bridged by inference (this is not about word order).
  If a number appears twice without explanation, the reader goes back to bridge it
- **5 paragraphs, no more**: the number of chunks working memory can hold at once is about 4 (3 to 5) (Cowan 2001; pure capacity under conditions where
  rehearsal is blocked. Miller's 7±2 is more than this). One bold paragraph plus 4 is at the limit
- **Dates as "N 日前（M/D）" (N days ago (M/D))**: matched with the day counts of /whose-turn. The cue a returning person has is elapsed time rather than the calendar
  (this is a judgment; there is no primary source)
- **One piece of information per sentence, active, affirmative**: Federal Plain Language Guidelines and GOV.UK (consider a split above 25
  words). As a Japanese public guideline there is the "やさしい日本語ガイドライン" (Easy Japanese Guidelines; Immigration Services Agency and Agency for Cultural Affairs, 2020), but
  its subject is information for supporting foreign residents; only its rules on sentence structure are borrowed here, not its vocabulary limits
- **Speak to the reader in prose**: a row of labels lined up in a monospace frame looks like "machine output", and the reader braces before reading
  (measured: the user said "読む気が失せる", "it kills my will to read"). A version with the same content written as one bold sentence plus short paragraphs got through. There are 4 grounds,
  all checked against primary sources. Text organized by the writer's categories is hard to read and should be reorganized by the reader's needs:
  Flower's (1979, College English) writer-based / reader-based prose. Use "you" to address the reader directly:
  Federal Plain Language Guidelines (2011, II "Use pronouns to speak directly to
  readers"). Stimuli that are easier to process are preferred: the review of processing fluency (Reber, Schwarz & Winkielman 2004,
  PSPR; a review of experiments on perceptual stimuli, so applying it to documents is an analogy). 79% of web readers scan, and highlighted
  keywords, meaningful subheadings, one idea per paragraph, and half the word count help: Nielsen (1997; observation of 19 participants)
- **Pictures for structure, prose for meaning**: CodeRabbit's PR summary (Walkthrough) adds a Sequence Diagram(s) section
  only to changes that have a flow that can be shown in a diagram, and the section is absent for PRs without one (the default behavior of the SaaS; it applies to review summaries,
  and the specification of when it draws has not been checked in public documentation). Here, pictures are drawn whenever the relationships between components can be stated (whether to skip them is
  up to the reader), and the meaning of the PR goes in the prose of the explanation.
  Measured: 3 first-time readers said "the figure is faster for the big picture, the prose for the meaning"
- **The reading order "caller → main body → helper" is kept as is**: Baum et al. (ICSME 2017) built a theory of the order in which changes are read during review,
  and 85% of respondents supported bottom-up (from the callee). In the follow-up experiment (Baum et al., EMSE 2019) the effect of order
  was only a tendency and not significant (an in-lab task by professional reviewers). Since there is no deciding factor, the order from the entry point is
  not changed; readers who want a different order can change it themselves

Measurements before settling on this format: when the same #1276 was output as "3 lines + 40 lines of machine output + explanation", 3 first-time readers
took 3, 3, and 44 lines to reach the answer and called it "duplicated" and "roundabout". The version as a code block with 5 fixed labels let all of them state the status correctly in
6 to 7 lines, but the user said "読む気が失せる" ("it kills my will to read"); a monospace frame looks like machine output.
It settled on prose with one bold sentence plus short paragraphs. A version whose line 2 said "私の番。ただし直すものは無い" ("my turn, but there is nothing to fix") was read as
a contradiction by 3 out of 3 readers, so the place to act (my other PR #1596) is written directly.

This is the machine output (the material the AI reads; what is printed when you run the script directly). Personal names and repository names are masked.

```
# #482 fix(api): 添付ファイルの取りこぼしを塞ぐ
  レビュアー · ● 私の番 — レビュー依頼が私に来ている
  PR open · 作者 hanako · 21 ファイル +328/-381
  https://github.com/example/app/pull/482

## 私が最後にしたこと
  09-01 09:15  コメント
  レビュー結果です。eec214ad まで確認しました。[block] 1 件・[suggest] 7 件・軽微 6 件です…

## 私に求められていること
  09-01 17:45  hanako の コメント
  ご指摘ありがとうございます。[block] 1 件と [suggest] 7 件すべてに対応し、e5096175 として push しました…

## その後に起きたこと — 4 件
  09-01 17:44  hanako が push
      e5096175 レビュー指摘対応 — ローカル層の打ち消しと注入の絞り込み (+62/-12)
  09-01 17:45  hanako が コメント
      ご指摘ありがとうございます。[block] 1 件と [suggest] 7 件すべてに対応し…
  09-01 19:13  taro が スレッド config/values.yaml:195（解決済）
      確認しました。接尾辞を畳んだ位置で引く形ですね…
  09-01 19:38  hanako が push
      fbf466b9 review round 4 対応 — 検査の素通り 3 点を塞ぐ (+162/-48)

## いまの状態
  承認: まだ承認されていない（REVIEW_REQUIRED） ／ 取り込み: 衝突なし（MERGEABLE）
  CI: 全 pass（緑 72）
  未解決スレッド: 0 件（うち人が入っているもの 0 件）

## つながっている先
  参照    08-30 10:02  #470 本番を main へ追随させ、自動同期を再開する

見ていないもの:
  - GitHub の外（チャット・口頭・メール）でのやり取り
  - diff の全文（下の地図は置き場所と骨組みと抜粋。gh pr diff で見る）
  - 名指しの無い発言が私への問いかどうか
  - 発言の全文。--full で出る

## 本文（材料。作者の言葉。件名と「説明」はここと地図の先頭コメントから書く）
  …（この下に本文と地図の材料が続く）
```

(The sections are: 私が最後にしたこと "what I did last", 私に求められていること "what is asked of me", その後に起きたこと "what happened after", いまの状態 "current state", つながっている先 "connected items", 見ていないもの "what was not looked at", and 本文 "description".)

**When you run the script directly, line 1 and the first 2 sections are enough to get back.** Line 1 tells you **your position** (implementer or reviewer) and
**whether you can act or are waiting**; "私が最後にしたこと" tells you **how far you had gone**, and
"私に求められていること" tells you **what the other side is waiting for**. In this example, you get back to "I gave review comments → the other side
fixed them and reported → now it is my turn to look" in 3 lines. The rest is material for verifying, to read only when needed.

**The key point is showing "私が最後にしたこと" (what I did last) and "私に求められていること" (what is asked of me) side by side.** Either one alone is not enough to get back.
Remembering what you said does not tell you what the other side wants now, and the reverse is also true.

The machine decides 3 things.

- **"私が最後にしたこと" includes pushes**, but **the range searched for requests is cut after your last comment (comment, review,
  thread).** A push is not a reply. If the range were cut at a push, a question that arrived before the push would count as answered
  and disappear
- **On your own items (as author or assignee), it also picks up the last comment without a mention, and says "名指しは無い" ("no mention").**
  Comments on your own PR usually do not name the addressee, and waiting only for mentions would drop them entirely. Whether it is a question
  is not decided by the machine, so the AI checks the text
- **References (another PR / issue wrote this number) are not counted as events.** They do not change the state of this item but take up
  display space and push real events out. They are placed only under "つながっている先" (connected items)

"見ていないもの" (what was not looked at) states, for anything cut off by fetch limits, **what could be missed** ("コミットの古い方 43 件。
私の痕跡や私宛の依頼がそこにあれば見落とす": "the older 43 commits; if a trace of mine or a request to me is there, it is missed"). A count alone does not tell the reader which part of this report to doubt.

The command definition files (the instructions the AI reads) are written as intent and criteria, and do not specify the wording of the output. If wording is specified, that phrase appears every time regardless of the situation and becomes noise (measured: on 2026-09-02, the global setting "if nothing is asked, say『読むだけでよい』 (just read)" made even chat replies end with "読むだけでよいターンです" ("this is a just-read turn")). Example sentences are given as one way of writing, with a note that they are not a template to copy.

## `/reflect` — look back over a period

```
/reflect               # 今日を含む 7 日
/reflect today         # 今日（yesterday・month・2026-10-15・2026-10-01..2026-10-15 も）
```

(No argument means the 7 days including today. `today` means today; `yesterday`, `month`, a date such as `2026-10-15`, and a range such as `2026-10-01..2026-10-15` also work.)

The machine (`scripts/reflect.py`) collects, for that period, the conversations, conversations started in the background (`claude -p` and so on), commits, GitHub activity,
Claude Code's `/insights` records, installed plugins and instruction files, and the ledger of past proposals. The AI writes
**improvement proposals** (in descending order of count × effort; before automating something, it first checks whether it can be stopped instead) and **observations and hints about
how you work**, and the machine draws them into one HTML page (`~/.cache/attention/reflect/<始まり>_<終わり>.html`, start_end).
The specification is [docs/reflect-spec.md](docs/reflect-spec.md).

- It reads only conversations in the current Claude Code config folder. To read other folders too, use `ATTENTION_REFLECT_CONFIG_DIRS`
  (joined with the OS path separator).
- If you set a place for a diary with `ATTENTION_REFLECT_DIARY_DIR`, then for a one-day period it rewrites the last section of that day's diary
  (`<置き場>/YYYY-MM-DD.md`, where `<置き場>` is that place), from `<!-- reflect:start -->` to `<!-- reflect:end -->`.
  It does not touch lines you wrote by hand.
- The proposal ledger is `${XDG_STATE_HOME:-~/.local/state}/attention/reflect-ledger.json`. If you say in the conversation that you adopt, reject, or defer a proposal,
  it is recorded with `reflect.py --decide`. Rejected proposals do not appear again.
- It has no mechanism for running on a schedule. If you want that, call `claude -p "/attention:reflect yesterday"` from your own environment's scheduler.

## `/what-am-i-doing` — get back to the session you are in

### Usage

```
/what-am-i-doing
```

It looks up your own record from `CLAUDE_CODE_SESSION_ID`, so no argument is needed.

### What comes back

**What comes back is an explanation, not a copy of the record.** The form is the same as `/catchup`: **prose as if speaking to a colleague**,
starting with 1 to 2 bold sentences, with a fixed paragraph order (situation → the reason it is stopped and the options → what to do next → where the records are).
About 15 lines and about 400 characters, in polite form (です・ます). The first paragraph covers "what was being done, and what the reader needs to provide". If a decision is pending,
it says what should be decided, down to the names of the options. "Situation" starts from what the reader knows (what they asked for or said),
and bugs are described by their symptoms. Options are written as "what to do" with subject and predicate, in words a first-time reader understands. Rejected options, things that were built,
and review records are not written in the body; they are pointed to by file or number, so it is clear that they do not need to be read now. The numbers of the items being handled
are links if the machine printed URLs.

This form comes from measurement. The person who received a 150-line reply (what the item is / position / what was done / decisions / order of next steps)
asked twice, "結局どういう判断をしてほしいのかだけ教えて" ("just tell me what decision you want from me") and "初見にもわかりやすく" ("make it clear for a first-time reader"), and the answer that got through
on the third try was prose in the order "the situation from the start → why a decision is needed → 3 ways to choose". That is the same order as the hand-off format
SBAR (situation → background → assessment → recommendation). A version folded into a code block with fixed labels passed with 3 first-time readers,
but the person said "読む気が失せる" ("it kills my will to read").

The goal is not a summary. **The reader does not go back through past exchanges, so this one reply alone must let them
catch up to the same point as someone who was there.** Success is judged by "can the reader carry out the next step
on their own?". So decisions come with **the options not chosen and why**, and things that were built come with **their location and count**.

The means of explanation are not fixed. The key point of a change is shown as **a few extracted lines of "before → after"**,
and which part of the system is touched is shown as **a picture of the system before and after** (the conditions for drawing and the rules to follow are the same as the explanation figure of `/catchup`.
It is checked for width and box-drawing lines with the bundled `figure-check.py` before output). But whether to include them is decided by the same measure every time:
**drop any element whose removal would not change what to do next**. So the length and means of the output differ
from session to session. The position (implementer or reviewer) is inferred by machine from the PR number mentioned most in the conversation. Reviews you sent are also counted
(when you send a review, GitHub removes you from the requested reviewers, so looking only at requested reviewers would drop a PR under review to "not participating").

### The bundled script is material, not output

```
python3 scripts/what-am-i-doing.py [--full] [--limit 25] [--topic 語句] [--frame path] [--out]
```

(`--topic 語句` takes a phrase.)

It outputs **pairs of a request and what was done about it**. Either one alone is not enough to catch up: a list of
"what was asked" is a list of questions and holds no state.

```
# このスレッド — PR残件確認
  /Users/me/src/app · ブランチ ci/1497-double-extension-yaml
  開始 09-01 19:22 · 最後の動き 09-02 06:32 · やり取り 23 往復

## 経過（依頼と、それに対して何をしたか）

  [09-01 19:23] 残件を教えて
      → 3 行で: open PR 33・issue 348 を全件走査。返信が要る呼びかけが 8 件…
      道具 Skill×1, Bash×1

  [09-02 06:26] 一番重要なのは理解できることだよね。だから教えるとこのトークンは…
      → そこが芯ですね。分かることが目的で、短さは手段——手段が目的を潰していました…
      コミット・push・テスト実行 / ツール Bash×4, Write×1

## このセッションの間に入ったコミット — 6 件
  988763b fix(attention): /catchup の「3 行を超えるな」を外す（marketplace 0.27.4）
  …

## いま手元に残っているもの
  未コミットの変更なし
```

When there are uncommitted local changes in 3 or more files, a tree of the changed files (with surrounding existing files shown faintly and only new ones in green) is pasted as is in a
`diff` frame. The component is `scripts/lib/changemap.py`, shared with the `/catchup` map. Below the tree comes
"変更の中身" (the content of the changes), in the same form as the `/catchup` map (frames of the current state with bands added by the machine; code as whole functions
via `git diff -W HEAD`, prose and settings with 10 lines of context). New files (untracked or added) show only their leading comment and skeleton. If one file exceeds 300 lines or the total exceeds 800 lines,
it stops at a function boundary; for the rest, use `what-am-i-doing.py --frame <path>` (one file, without a limit).
The AI copies the frames into code blocks with a language name (it copies the `（言語名 X）` ("language name X") that the machine puts at the end of the frame heading, or, if absent,
derives it from the file extension). The `飛び先 path:行` ("jump target path:line") before a frame opens that line when clicked in a supporting terminal.

Only **the beginning** of each turn's reply is taken. Listing the full text would make it a copy of the record, and reading it would be no different from
going back through the conversation. Turning points (commit, push, test run) are picked up from the content of Bash calls.

**The title (`aiTitle`) is not relied on.** Claude Code sets it early and never updates it, so after the topic moves on,
the old title keeps appearing (measured: after moving from an inventory to building a plugin, it stayed "PR残件確認" ("checking remaining PR items")).

## What this tool does not do

- **It does not judge.** "What should be done next" is decided by the reader or by the AI in `/catchup`. The scripts only output material
- **The scripts do not summarize diffs.** A summary of lines does not help you remember, and a machine summary uses words different from the actual lines.
  All the machine appends at the end is the author's description and the actual lines: **指摘 (review comments)** (for each unresolved thread with a comment from the other side, their comment and
  that line at head), **CI** (if there is red, the log of the failed step), **地図 (map)** (a tree of changed files, the author's
  leading comments and skeletons of new files, and frames of changes to existing files, that is, the current state with bands added). It does not vary by whether you are the author; everything that exists is appended. Lines are only
  copied from the machine output, not summarized. A focus word narrows it to one kind. The explanation of "what the PR is" is written by the AI from the author's description, the issues it closes, and
  leading comments (the "explanation" after the format)
- **`/catchup` does not take an inventory of everything.** It has one target (a number, a URL, the current branch, or a conversation topic), and
  deciding that number is the job of `/whose-turn`
- **The only things that change your local checkout are the `git switch` done by `--switch` of `/catchup` and the `git fetch` that gets the source of one branch that is not local.**
  It does not pull, merge, stash, commit, or `gh pr checkout`. If tracked files have uncommitted changes it does not move, and existing local branches are
  not moved by the fetch either. The other 2 commands, `/whose-turn` and `/what-am-i-doing`, only read the local checkout
- **It does not decide whom to ask for review.** It only shows GitHub's candidates (suggested reviewers) and the reasons. I decide whom to ask
- **The machine does not draw pictures.** The pictures of `/what-am-i-doing` are drawn by the AI in the words of the explanation, and the machine (`figure-check.py`) only checks width, line count, and misaligned
  box-drawing lines. For the figures of `/catchup`, the AI writes the arrangement of boxes (before and after) into a field, and the machine only turns it into SVG of a fixed form;
  the machine does not decide what becomes a box

## Prior art

The idea of making the turn explicit has prior art in the **Attention Set** of Gerrit and Google Critique (introduced in Critique in 2015), which goes as far as showing "why it is your turn now" in one line. What this tool adds, on top of that reason, is **putting the content of the request side by side with your own last comment**, which only makes sense when narrowed to one item rather than a list.

- <https://gerrit-review.googlesource.com/Documentation/user-attention-set.html>
- <https://www.gerritcodereview.com/design-docs/attention-set-use-cases.html>

"取り込み先 (merge target) / that branch's PR / 上に積む (stacked on top)" has prior art in Gerrit's **Related Changes** (which shows the parent-child relations of stacked changes on one item's page).
"依頼先の候補 (reviewer candidates)" uses GitHub's **suggested reviewers** (the suggestions shown on the PR page) as material as is;
this tool does not choose.
