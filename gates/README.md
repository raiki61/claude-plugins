# gates — gatekeeper hooks

For people who use Claude Code to post to GitHub with gh (the GitHub CLI) or to write documents, and want a check that the text gets across to a first-time reader before it goes out. It is also for anyone who runs several Claude Code sessions on one machine and wants to keep a session from searching the whole disk or from waiting in a loop that never ends. Install the plugin (see Install); the coldread, searchgate and waitgate hooks are on as soon as it is installed, and destgate stays off until you create its allowlist. After Install and the first coldread section, the later sections are reference: the limits of what is caught, the details of each gatekeeper, and the measurements behind each decision.

This plugin distributes hooks that stop an operation until a check passes: outward-facing operations, searches that would load the whole machine, and hand-written waiting loops that would leave a session stuck. There are currently 4 gatekeepers: coldread (whether the text gets across to a first-time reader), destgate (an allowlist for destinations), searchgate (no searches from / or the whole home) and waitgate (no hand-written waiting loops). coldread stops posts to gh before they are written; for local documents (md and so on) it reads them after they are written and returns findings to whoever wrote them (the parent session or a subagent worker) when that writer finishes (it does not stop them).

The coldread skill's instructions and description are written in Japanese.

Changes per version are in [CHANGELOG.md](CHANGELOG.md). How versions are released (the step of adding to the change log; no git tags are made) is in [docs/releasing.md](../docs/releasing.md) (relative to the repository root; it is not in the copy installed as a plugin. Read it in a clone or on GitHub: https://github.com/raiki61/claude-plugins).

## Install

```
/plugin marketplace add raiki61/claude-plugins
/plugin install gates@raiki61
```

### When the reader is not logged in

coldread starts its reader as a separate `claude -p`. On Linux and Windows, that reader can only use the login that Claude Code saves in
`<CLAUDE_CONFIG_DIR>/.credentials.json` (`~/.claude/.credentials.json` if `CLAUDE_CONFIG_DIR` is not set; on Windows `%USERPROFILE%\.claude\.credentials.json`),
or a key that is present in the hook's own environment.

- If you pass your Claude Code key only as the environment variable `CLAUDE_CODE_OAUTH_TOKEN` (a `claude setup-token` token, common in containers and VMs)
  and have no `.credentials.json`, the reader does not start: Claude Code 2.1.310 did not pass `CLAUDE_CODE_OAUTH_TOKEN` to hook processes (measured on Linux and Windows, 2026-10-26),
  and the reader ends with "Not logged in · Please run /login". Every gh post is then stopped as not checked, and each turn ends with a list of documents the reader could not read.
  A key in the `env` of `settings.json` does not help either: the reader starts with `--setting-sources ""`, which loads no settings files.
- Fix: run `claude auth login` (or `/login` in a session) once in that environment, so that `.credentials.json` exists. You can keep `CLAUDE_CODE_OAUTH_TOKEN` for your own sessions.
  When the reader fails with no key in the hook's environment and no `.credentials.json`, one line pointing here is added to the gate's stop reason,
  the end-of-turn notice, and the output of `branch-check` and the manual `read`.
- On macOS the reader reads the token from the Keychain instead (see `COLDREAD_KEYCHAIN_SERVICE` under the settings below).

## coldread — gatekeeper for external posts

A PreToolUse hook catches commands that post text to GitHub with gh (issue/PR comments and bodies, release notes, gists, etc.), and **the hook itself
runs coldreader (a reader with zero context; a headless Claude in a separate process)** to check the text as a first-time reader.
If there are "blockers" (詰まり: places that prevent understanding), it puts those findings in the deny reason and stops the post.
"Questions" (疑問: things the reader understood but whose answer is not in the text) do not stop it; they are passed along.

The same hook also looks at one kind of text that works-dispatch (the plugin in this repository that hands requests to per-task sessions and returns their results) sends to another session: the summary file of `--deliver` (a result returned to the session that asked).
Requests and notes (`--text` and `--brief`, sent with `--ask`, `--note`, or `--task`) are not read, and neither is most of a summary: they go from one AI session to another, and a session that does not understand something can ask back (decided by the owner, the person who runs these sessions, 2026-10-20).
Before, the hook read requests and whole summaries with zero context, and stopped them over words the asking session had written itself: on 2026-10-20, 832 `--deliver` commands were stopped against 253 passed, and one summary was stopped 5 times until the session gave up and asked a person to send it.
What a person reads is kept: from the summary's front matter (a TOML block whose first and closing lines are `+++`, read by works-dispatch), the open questions whose holder (the party who follows the question up) is the owner (`owner:choose` or `owner:confirm`).
The reader reads only those questions, however short the summary is, with zero context (the owner reads them without the sessions' context), shown as a list under 「持ち主への問い」 in the form works-dispatch hands them on; a summary with none is passed without starting the reader.
The command it looks for starts with `dispatch.py` itself or with `python`/`py`/`bash`/`sh`/`run-python.sh` (the wrapper the works-dispatch skill writes) and has `dispatch.py` as a later word, with any flags in between (`python3 -X utf8`, `run-python.sh --min 3.11`); prefixes of the flag that argparse accepts (`--deli`) count too. `--help` and `--dry-run` send nothing and are not read.
The checks for files and stdin are the same as for `gh` (a summary file the hook cannot read stops the command), and destgate does not check these commands (they have no GitHub destination).
Front matter that is missing, is not valid TOML, or has unknown top-level fields has no questions to read (works-dispatch refuses to send invalid front matter anyway); on Python 3.10 or older, which has no `tomllib` and cannot parse TOML, the reader is given the raw front matter text, unparsed, if it contains an owner holder value; otherwise the command is passed.
**A summary that was sent is remembered as read**, whether the reader ran or not: the local-document check at the end of the turn (below) does not read it again, because a text that has arrived can no longer be fixed (2026-10-19: 5 blockers on a summary that had already been delivered).
**A `gh` text that passed a full zero-context read is remembered as read** in the same way (this applies to `--body-file` and other body files of `gh` posts).
Reads that are more lenient are not remembered: a text read with the screen around it (for a reply or edit, the PR/issue thread the hook fetches with gh; for a new PR or issue, what its page will show; see the next paragraph), and a text passed on the 3rd or later read of the same post after it was stopped and rewritten, where only blockers left over from earlier reads stop it (see "From the 3rd round" below). A file edited after it was sent no longer matches the remembered content, so the end-of-turn check reads it like any other document.

The context the reader has depends on where the post goes. Replies and edits attached to an existing PR/issue thread are read with the title, number,
file and line, the original comment, and the earlier replies all visible on the same screen, so **the hook fetches
that screen with gh and gives it to the reader as known**. For new PRs and issues (`gh pr create`, `gh issue create`), the reader is
not looking at the text alone either. What GitHub shows around the text — the title, the repository, (for a PR) the base and head branches,
the list of changed files, and the titles and states of the #numbers the text points to — is assembled by the hook from the command's flags and from gh and git, and passed along (issues that
the PR closes are listed next to the PR with their titles. When the reader read without them, it stopped even at `Closes #660` on the first line of the text, saying "I don't know which issue this is".
On 2026-10-17, the bodies of 3 new PRs in works-factory were stopped 7 times in total). New releases, gists, and
discussions are still read with zero context. When the reader read without the thread's screen, it raised as blockers even the @name of the other person, the PR number, the labels the other person
added, and the other person's own words, and when the writer fixed those, the result was a reply explaining to the addressee their own name and the meaning of
their own comment (measured on PR 1583 on 2026-09-06: one reply was stopped 39 times, grew from 1,021 to
2,555 characters, and went out through the escape hatch. A version shortened back was also stopped). Places where the text explains what is on the screen
are passed along as 「冗長」 ("redundant") without stopping, and for replies the deny's advice on how to fix is also "cut rather than add".

The screen passed along goes as far as what participants actually see: title, number, state (open/merged/draft), the full body, the list of changed
files, the earlier replies (the one just before the reply being answered is never cut), and the titles of the #numbers that the body and the thread refer to.
**What the screen makes known is "what is being referred to", not "how to write it"** — if the text uses the other person's phrasing, jargon from outside the industry,
or metaphors as its own prose, that is a blocker even if the same words are on the screen (pointing at the other person's words to answer them is known).
If the screen is treated as a dictionary of the thread's vocabulary, the reader gets pulled along by the thread's quirky writing, and that pushes the text toward copying
those quirks. Places that copy are stopped as 「なぞり」 ("echoing"), the same as blockers (the fix is not to add explanation but to replace them with your own words).
When this was folded into the condition sentence for blockers, the actual reader picked up none of the cases, but when asked as a separate field it picked up all 3 words, and did not pick up replies that quote and
point at them (measured on 2026-09-07 with 北極星・ニアバイ・クロージング ("north star", "nearby", "closing")). Measured on PR 1429 on 2026-09-07: a zero-context reader (a session started before the update and still running 0.8.0)
raised "what are #1231 #1581 #1283" and "what is the 9/2 proposal" as blockers, and after 6 denies the text grew from 5,455 to 10,179 characters
(a 19-word glossary took 25% of it) and went out through the escape hatch. Every one of the blockers was something that would not have come up if the reader had seen the thread.

- It does not rely on the writer's self-report that the check ran — there is structurally no hole of "just stamping a 'checked' mark and passing"
- It checks only whether the text gets across — it does not look at whether the post should be made at all, under whose name, or where it goes. **Do not
  mistake passing for approval** (the pass and send-back messages say so every time). Destinations are restricted by destgate below
- On every retry a new coldreader reads the fixed text — the hook drives convergence mechanically
- **There is no escape hatch for an agent to turn the check off by itself** (owner's decision 2026-10-16). The former `COLDREAD_SKIP=1` was used 22 times as a way to
  avoid rewriting the body file and post unchecked. Now it has no effect even if written in the command; only the fact that it was written is
  recorded as `refused` in `$CLAUDE_CONFIG_DIR/coldread-gate/skip.log`, and the stop reason also says 「効かない」 ("has no effect").
  The stop reason does not point to an escape hatch. Only when it stopped because it could not read the text (could not check it) does it say: if you cannot fix it, hand it to the owner and stop.
  When it read the text and stopped it, the gate settles on its own by the "From the 3rd round" rule below (the way for the owner to let a post through was removed; see "The way for the owner to let a post through was removed" below)
- When the owner wants to post it themselves, they type `gh` in their own terminal (the hook only runs inside Claude Code). For Claude Code's
  `!` (shell mode), the official documentation says it "runs without going through Claude" and "does not need Claude's interpretation or approval"
  (the "Shell mode with ! prefix" section of https://code.claude.com/docs/en/interactive-mode; confirmed on 2026-10-16), but
  it does not say whether PreToolUse hooks apply — **needs confirmation** (if they apply, typing it with `!` is stopped by the same check)
- Pass-throughs suspected of slipping through the net are recorded in `misses.log` with the spelling of the flag that matched and the first word of that simple command
  (`sh`, `python3`, `echo`, etc.) — if they cannot be told apart from "it was not a post", there is no way to measure how much was pushed out
  to back doors when the gatekeeper is tightened. Matching spellings inside heredoc contents are not counted. The recorded first word lets you sort out later which matches were really flags of another tool or words inside a document, rather than gh posts that slipped through.
  They are recorded regardless of command length
- It does not skip by command length (before, commands shorter than 400 characters were passed before parsing without even a record, and short posts carrying a body file or
  a variable went out unread 54 times in the most recent 14 days). Not sending short boilerplate replies to the reader is decided by passing them when the extracted text is
  under 200 characters. It does not apply to read-only gh commands, or to gh with `--help`, `-h`, or `--version` (which print help and end)
- It also stops when coldreader cannot be started (because no check was done). If that does not get fixed, hand it to the owner (the person who runs this Claude Code session and owns the repository)
- coldreader is started with `claude -p --output-format json --json-schema`, and the gate reads only the `structured_output` field: a list of findings, each with
  a kind key (`stuck`, `echo`, `question`, `guess`, `redundant`), an optional cause key (`word`, `referent`, `flow`), `carried`, and the text. The Japanese labels in the
  stop reason are made from these keys afterwards; the reader's prose is never parsed. An answer that is not in this shape (not JSON, `is_error`, an unknown kind,
  an empty text) is not read as "no findings": the post is stopped. The gate also stops when it cannot read its own hook input (it used to let the command through)
- When the screen cannot be fetched (no gh, no auth, offline), the reader reads with zero context and the writer is told so (it does not stop)
- coldreader does not read the user's CLAUDE.md or settings (it is started with `--setting-sources ""`). If the reader holds rules meant for writers,
  such as "write so that a first-time reader understands", as its own instructions, it leans toward raising every identifier as a blocker
  (measured on 2026-09-06: started plainly, it quoted headings from the user's CLAUDE.md)
- **From the 2nd rewrite on, a reader who knows the previous round reads it** (owner 2026-10-17). The 1st round's reader reads the whole text and lists everything.
  The readers from the 2nd round on are given the previous round's findings (including the fields that do not stop) and the diff from the previous round's text (line by line), and the reasons to stop are limited to
  "blockers and echoes from the previous round that are still unresolved" and "things newly created by what the fix added or rewrote".
  Things newly noticed in parts that were not rewritten are parts the 1st round's reader read in full and did not raise as blockers, so they are returned as questions or guesses.
  Findings that would make the writer undo a fix that answered the previous round's findings (cut the added explanation as redundant, etc.) are also not allowed. Back when a brand-new reader read the
  whole text every time, readers that did not know the previous round made opposite demands (the 2nd round: "it restates the earlier comment, so cut it"; the 3rd round:
  "it does not restate which option of the earlier comment"), each picked up new edge points the previous reader had not mentioned, and the same post kept getting stopped 3
  times (5 posts in works-factory on 2026-10-17). The previous round's text and findings are kept, one per pair of writer (session) and destination, in
  `$CLAUDE_CONFIG_DIR/coldread-gate/rounds/`, and deleted once the post passes (ones older than 30 minutes are deleted when writing).
  The previous round is carried over only when 8 or more of the text's 16 fingerprints match; a text rewritten by more than half, and a different
  post to the same destination, are read in full as a 1st round
- **From the 3rd round, it stops only on blockers and echoes left over from the previous round** (owner 2026-10-17: 「ある程度出たと判断したら進む形にしよう」, "once we judge enough has come out, let it move on").
  The previous round's findings are passed to the reader split into the ones that stopped the post and the ones that did not. The reader sets `carried: true` on a blocker
  (`stuck`) or echo (`echo`) finding left over from the previous round, and findings without it are returned as questions without stopping. The number of findings that stop is capped at
  one less than the number that stopped in the previous round if the text was fixed (the excess moves to questions), and at the previous round's number if it was resubmitted without fixing.
  Even if the reader marks new things, the number that stops goes down with every fix and passes at 0 — the gate settles on its own. Resubmitting without fixing does not reduce it.
  Rounds that cannot carry over the previous round's record (more than half the text rewritten, more than 30 minutes in between, a different version) go back to the 1st round
- **There is no limit on the number of round trips, and no way for the owner to let a post through** (owner 2026-10-17: 「上限はいらないわ」 "no limit needed", 「人からパスを売ってもらう運用はやめて」 "stop the practice of getting a pass from a person").
  When the same post is stopped 3 times in a row, the stop reason starts with 「同じ投稿が 3 回続けて止まった」 ("the same post was stopped 3 times in a row") and the note that from here on it stops only on what is left over from the previous round
  (the sequence of the text's character counts for each round is included too), and `stuck.log` records the session, version, kind of destination, the sequence of stop reasons, and the sequence of text lengths
  (the text itself is not copied; it is material for fixing the gate side). Before, it stopped at 3 without reading.
  3 was chosen from the distribution of consecutive stops in `denies.log` (2026-09 to 10, 4 profiles, with readers that did not know the previous round): after 1 stop, 178 of 301 posts
  passed next time; after 2 stops, 49 of 94; after 3 stops, 2 of 33.
  The wobble was the habit of promoting questions (the meaning was clear but the reader wanted evidence) to blockers, so the request text narrowed the blocker line to
  "at that spot the meaning cannot be taken and reading cannot continue" and stated "when in doubt, it is a question" (the same reply passed 3 of 4 times,
  and the 10,179-character version 2 of 2. Consultant jargon, unresolved references, and undefined abbreviations with zero context still stopped) (a note placed at the end had been ignored 36 times).
  Further, blockers are limited to cases where the meaning of a word, what something refers to, or how sentences connect cannot be taken, and the reader is made to write which one right after 「詰まり: 」. Content review that asks for decision material,
  evidence, or examples is moved to questions (on 2026-10-17, on works-factory PR #677, the 3rd round's reader stopped on "is the range not allowed the same as
  the previous inspection", every time evidence was added the added sentence was questioned again, and the text swelled from 473 to 1,351 characters)
  "The same post" is decided by the writer (session), the destination, and how close the text is. The log is shared per profile, so counting denies from parallel
  sessions would treat the 1st round's writer as stopped repeatedly (measured on 2026-09-07). Closeness of the text is judged by whether 3 or more of the 16
  text fingerprints left on each line of `denies.log` (16 MinHash values of 5-character fragments; the text cannot be recovered) match — a version that was added to and
  doubled in size counts as the same post, and a post on a different topic to the same destination does not. Denies where the text could not be extracted (no fingerprint)
  are not counted in the run of posts that have text. When a post whose text cannot be extracted is stopped, earlier denies are counted by destination only.
  Rounds where the reader read the text and stopped it, and rounds where it stopped without being able to read the text (too long, unparseable, not extractable, reader not running), are counted separately,
  and rounds of the other kind are skipped (rounds that were stopped because the body file was rewritten inside the same command had been counted as "4 times in a row"; 2026-10-17).
  When it hits a deny from a different version, it stops counting, and the previous round's record (`rounds/`) from a different version is not carried over either (one round of 0.22.3
  was added to the rounds of 0.23.0, and "3 times in a row" appeared on the new version's 2nd round; 2026-10-17)
- **The way for the owner to let a post through was removed** (owner 2026-10-17: 「人からパスを売ってもらう運用はやめて」, "stop the practice of getting a pass from a person"). In 0.23.0, the stop reason included
  「coldread-pass <番号>」 (`<番号>` is a number), and when the owner typed only this form in the session's input box, the next attempt was let through. Even if the owner said in the session
  "you may let it through", the machine could not receive that, and the writer got stuck (works-factory PR #677 was stopped 5 times, and the 4th and 5th were
  all questions asking for material to decide whether to merge it). Now, the 2 rules above (content-review questions go to questions; from the 3rd round it stops only on what is left over
  from the previous round) make the gate settle on its own. When the owner posts it themselves, as before they type it with Claude Code's ! or in their own terminal
- The titles of referenced items (#numbers the text points to) cannot be fixed by the writer, so words in those titles do not stop the post (it stops only when the text uses the word
  as its own words). The title of a new PR (`--title`) can be fixed by the writer, so it is read as before
- Each line of `denies.log` carries the session, version, and destination (grep to find which session on which version posted where).
  If the installed version differs from the one running, one line is added to the check result and is also shown on the owner's screen (the `systemMessage` field of the hook output); the check itself runs as usual.
  The installed version is the `installPath` in Claude Code's `<config>/plugins/installed_plugins.json`; an `installPath` folder that contains a `.orphaned_at` file (Claude Code's mark on a version it will remove) does not count.
  Only entries that apply to the current project count: `user` entries, and `project`/`local` entries whose `projectPath` is the current folder, its git work tree, the main work tree of a linked worktree, or the `CLAUDE_PROJECT_DIR` environment variable (the project folder Claude Code passes to hooks).
  Among those, the narrowest scope wins (`local`, then `project`, then `user`). If that entry's `installPath` folder is missing or contains `.orphaned_at`, no note is shown; the gate does not fall back to a wider entry.
  The hook's version is fixed when the session starts, and a session kept open for a long time keeps checking with the old version even after an update
  (measured: it stayed on 0.8.0 for 16 hours)
- When the reader (`claude -p`) answers with a short single line that is not JSON, or with an `is_error` answer about authentication, the gate treats it as "the reader could not read"
  (an expired login or a used-up usage limit both answer this way, with exit code 0), names it as such to the writer, and, for the gate on gh posts to GitHub, logs `reader-auth` in `denies.log`.
  When the reader was started with a token from a Keychain item and that item was written 335 days ago or more (`claude setup-token` tokens last one year),
  one line asking to remake the token goes out the same two ways as the version-mismatch line above: it is added to the check result the model receives (the hook's reason or context text),
  and it is shown on the owner's screen through the `systemMessage` field of the hook output. This line appears at most once a day per Keychain item.
  The line is not shown by the check that `--land` runs before merging (`branch-check`), because `--land` drops that output when the check passes.
  One exception: the end-of-turn check that runs in the background of an interactive session can only send text back to the model, so there the line reaches the owner only when the model relays it (the line itself asks the model to)
- When the session's account replaces the model with a non-Claude one (an `ANTHROPIC_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`, or `ANTHROPIC_DEFAULT_*_MODEL` value without `claude` in it, in the environment or in the `env` of `settings.json` in `CLAUDE_CONFIG_DIR`),
  the reader does not inherit that replacement, because the check was tuned for the reader running on sonnet and haiku, and another model would read with a different strictness. Instead, the gate removes the replacement, the gateway URL, and the keys from the reader's environment, and runs the reader with another account from the works-dispatch settings
  (`WORKS_DISPATCH_CONFIG`, default `~/.config/works-dispatch/dispatch.toml`; read only): an account other than the session's, whose `settings.json` has no such replacement, with a token found for it.
  Accounts with a lower usage record (`<limits_dir>/<name>.json`) come first, then the ones without a record in config order. If the reader answers as "could not read" (login or usage limit), the next account is tried.
  The answer must show (in `modelUsage`) that only `claude-` models ran, including the requested one; otherwise that answer is not used and the check stops as not checked, the same as when the reader fails. With no usable account, the check also stops as not checked and says the settings need such an account.
  A gateway URL alone, or a Claude model name (a Bedrock or Vertex ID), is not a replacement: the reader runs on the user's own route as before
- The reader uses a short, dedicated `--system-prompt` instead of Claude Code's coding instructions. The inspection instructions, text, screen context, and rewrite history still go through stdin unchanged. `--tools ""`, an empty strict MCP configuration, and `--disable-slash-commands` keep the reader from acting on instructions inside the inspected text. `--no-session-persistence` prevents saving the reader's conversation; it is a privacy setting, not a token discount. The model and effort defaults are unchanged.
- The reader keeps prompt caching enabled but sets `FORCE_PROMPT_CACHING_5M=1` for its child process (Claude Code 2.1.242 or later). Separate single-turn sessions can reuse an identical prefix; disabling all caching would lose those reads. A unique document tail is often never reused, so the 5-minute write price is preferable to the 1-hour write price. The [official caching reference](https://code.claude.com/docs/en/prompt-caching) documents the setting; [API pricing](https://platform.claude.com/docs/en/about-claude/pricing) distinguishes the two write rates. This does not guarantee a lower total bill: generation and reasoning are separate costs.
- Each reader process attempt writes one metadata-only JSON line to `<config>/coldread-gate/reader-usage.jsonl` in the **writer's** configuration directory. It records the full writer session and agent IDs, company, department, request ID, reader session ID and profile, requested and actual models, effort, mode, timing, status, and token/cost counters. These source IDs are selected as follows:
  - Writer session ID: the first nonempty value from the hook input's `session_id`, the environment variables `CLAUDE_CODE_SESSION_ID` and `CLAUDE_SESSION_ID`, then the Git setting `company.session`. Writer agent ID comes only from the hook input's `agent_id`.
  - Department and request ID: the Git settings `company.name` and `company.ask`, including settings specific to a Git worktree (a separate checkout of the same repository). The gate reads them in the hook input's working directory (`cwd`), or the current directory when run manually. Manual document inspection (`read`) uses the current directory, not the document's directory. Pre-merge document inspection (`branch-check`) uses its worktree; if it has no `company.*` settings, the gate uses another worktree only when exactly one listed worktree has the inspected branch checked out. That branch is the checked-out branch, or the unique local ancestor branch identified in a temporary detached checkout as explained under "Read before merging into the mainline" below.
  - Company: the top-level `name` in the company configuration (`.claude/company.toml`) on origin's default branch (`origin/HEAD`). If the file is unavailable, the gate tries the main repository's copy, then the per-repository company file, reading the first existing file. To locate that company file, the gate takes the parent directory of the configuration file path specified by the environment variable `WORKS_DISPATCH_CONFIG`. When the variable is unset or empty, the configuration file path is `~/.config/works-dispatch/dispatch.toml`, so its parent directory is `~/.config/works-dispatch/`. The company file is under that parent directory at `companies/<URL-encoded-real-repository-path>.toml`; this lookup reads the company file, not `dispatch.toml`. A missing or empty company name falls back to the main repository's directory name. On Python 3.10 or earlier, the standard TOML parser (`tomllib`) is unavailable, so the gate skips these configuration files and uses the repository's directory name. Company is `null` if the Git repository cannot be identified; other unavailable IDs/settings are also `null`, for example department and request ID outside a works-dispatch department worktree.
  No prompt, finding text, path, credentials, or stderr is copied into this log. New logs are created with owner-only permissions.
- The `usage` fields are `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, `thinking_tokens`, `nonthinking_output_tokens`, `ephemeral_5m_input_tokens`, and `ephemeral_1h_input_tokens`. `output_tokens` **includes** thinking; do not add it again. The nonthinking remainder is not an exact count of visible JSON: it can include the harness's structured-output machinery. Missing counters are `null`, not zero. A timed-out attempt keeps its assigned reader session ID but normally has no final usage; do not count such attempts as free. `models` carries per-model counters and the CLI's cost basis; the reported dollars are API/list-price equivalents where indicated, not a subscription invoice.
- Consumers should ingest both `reader-usage.jsonl` and `.1` before rotation discards older lines, deduplicate by `(call_id, attempt)`, and join `company`, `department`, `request_id`, and the full writer/reader IDs. Count missing usage and failed attempts separately. Reads served from the gate's local result cache start no reader process and produce no usage line. If writing the usage log fails, a notice reaches the writer through the hook output (or stderr for manual/branch checks); the inspection result is still returned.
- `denies.log`, `docs.log`, and the other logs are moved to `<name>.1` when they grow past 2 MB (the previous `.1` is dropped).
  Counting how many times in a row the same post was stopped reads only the last 400 lines of `denies.log`

Settings are environment variables (all optional): `COLDREAD_MODEL` (default sonnet), `COLDREAD_EFFORT` (default
medium), `COLDREAD_MAX_LEN` (commands longer than this are stopped without parsing; body files are also read up to this many characters; default 100000), `COLDREAD_KEYCHAIN_SERVICE` (the service name used on macOS
to read the OAuth token from the Keychain), `COLDREAD_READER_CMD` (replaces coldreader), and
`COLDREAD_GH_CMD` (replaces the gh used to fetch the screen; for tests). For local documents, see the section below.

## Reach of the net (honest limits)

The decision is made by "is a flag that carries the text in gh's own argument list" (attribution is checked per simple command.
The history of the approach and the PATH shim plan for the next stage are in [docs/coldread-gate-next.md](../docs/coldread-gate-next.md)).
The following are accepted as out of scope in principle, or as forms that are stopped without reading the content:

- Posts without a flag are out of scope: `gh pr create --fill` (the text comes from commit messages) and launching an editor (a person writes interactively)
- graphql is detected by the `mutation` keyword (when the query is passed as `-F query=@file`, the file is read and checked). A mutation is taken to
  carry text only in the `body:` (and `readme:`) fields, and only those fields' values (a block string, a string, or for `$variable` the value passed with `-f`/`-F`)
  and values passed by field name like `input[body]=` are given to the reader — extracting the whole query as text would send
  fields other than `body:` (IDs, tokens, settings values) to coldreader too. Mutations without such a field
  (`resolveReviewThread`, etc.) are not posts, so they are not stopped (back when they were all stopped, 57 of the round trips were these).
  Mutations where the field's value cannot be determined (`$variable` not passed, not a string) are stopped
- Forms where `gh` does not appear as a command are outside the decision: `xargs -I{} gh ...`, `sh -c "gh ..."`, gh inside quotes.
  Only here does it fall to pass-through (allow) — prefixes `env`, `command`, `exec`, `nohup`, `time`, `timeout`, `gtimeout` are
  inside the decision (for `timeout` it skips the time value and the values of `-s` and `-k`; for `env` the values of `-u` and `-C`), but
  other prefixes such as `sudo` and `nice` are not caught by the net. `$(…)` inside double quotes (`--body "$(cat <<'EOF' … EOF)"`) and
  gh called from another program such as Python's subprocess are not followed as an extension of the parsing (a PATH shim, where gh's arguments arrive in the form after
  the shell has finished parsing them, is being considered separately; [docs/coldread-gate-next.md](../docs/coldread-gate-next.md))
- Once it is known to be a call to `gh`, what could not be read is not passed through: the subcommand cannot be identified
  (an unknown global flag comes before it), the text is passed via command substitution or a variable that cannot be resolved, the `--input` JSON has
  a long string outside the text positions (`.body` and a review's `comments[].body`), or the value of a graphql mutation's text field
  cannot be determined — all of these are stopped as "cannot be checked". However, `` ` `` and `$(` inside single quotes are not expanded, so
  they are read as part of the text (so that normal prose containing code fences is not stopped)
- For works-dispatch, a send whose command does not start as above (`uv run …/dispatch.py`, `sh -c "python3 …/dispatch.py …"`, `dispatch.py` named through a variable) is outside the decision and passes;
  when its simple command still has the word `dispatch.py` and a body flag, the flag and the first word go to `misses.log`, as for `gh`
- A heredoc is treated only as the text of the simple command it is attached to. Even if another command's
  heredoc is on the same line, it is not mixed into gh's text
- **The hook reads body files itself** (`--body-file f`, `--notes-file f`, `-F f`, `-F body=@f`, `--input f`).
  Before, it stopped them as "cannot extract" and made the writer rewrite them as heredocs; that caused 124 round trips, 22 of which went out unchecked through the escape hatch.
  It reads them only when it can say statically that the content is the same as what gh will read; if it cannot say so, it stops (fail-closed):
  - Paths are resolved as far as: literal, `~/` (expanded with HOME), a variable assigned in the same command (`S=/abs; gh … --body-file "$S/b.md"`),
    relative to the cwd in the hook's input (according to the official documentation, after Claude runs cd it points to the new location), and relative after `cd <absolute path> &&`.
    A variable is resolved only when the text shows that the assignment always runs and reaches gh: assigned only once, not inside a condition (`if`, `||`), a loop,
    a pipe, `&`, or a subshell that closes first, and not reassigned with `+=`, `read`, `printf -v`, `declare`, `for`, `eval`, etc.
    (`$( … )` and pipes of other commands in between are not looked at). Unresolvable variables, `~user`, globs, relative paths after a cd followed by `;` or after `if cd …`,
    and relative paths after `env -C` are stopped
  - If the same command contains a command that writes the body file, and it is a single `cat > f <<'EOF'` that always runs before gh
    (not inside a condition, `||`, a pipe, or `&`), that heredoc is read (the file at the time of the hook has old content). If there are other writers (`cp`, `mv`, `sed`, `git`… that take the body file's name as an argument, or
    a redirect to that file, including gh's own `> f`), it is stopped. Commands that take the name as an argument but do not write
    (`cat`, `wc`, `head`, `ls`, `grep`, etc.) and commands that run after gh finishes (the cleanup in `gh … --body-file f && rm f`;
    except inside loops or functions) are not counted
  - The file is opened with O_NONBLOCK, and after opening, fstat checks that it is a regular file (if a FIFO waits for a writer and stalls the hook, the post passes unchecked on the hook's
    timeout). Files that exceed `COLDREAD_MAX_LEN` characters, are not UTF-8, or cannot be read are stopped
  - **Remaining holes**: another process rewriting the file between the hook reading it and gh reading it (time of check vs. time of use; CWE-367), and
    a program in the same command that rewrites the body file without taking its name as an argument (writing it inside a script, etc.) cannot be prevented
- Standard input from a pipe or another process (`cat f | gh … --body-file -`) cannot be read, so it is stopped. It is stopped even if readable text
  is present alongside. Text passed in a variable (`--body "$B"`) is read only when it can be resolved from an assignment in the same command, under the same conditions as paths
- If the text of a heredoc with an unquoted delimiter (`<<EOF`) contains `$` or `` ` ``, the text the shell expands and posts differs from the literal text, so
  it is stopped (if quoted as `<<'EOF'`, it is read). The same goes for double-quoted text with a variable mixed into part of it (`--body "See: $B"`):
  it is read only when it can be resolved from an assignment in the same command. The end line of `<<EOF` may not be indented (only tabs with `<<-` are allowed, as in bash)
- gh right after `if`, `while`, or `until` (in the condition position) is also caught by the net
- Commands with unclosed quotes, whose parsing crashes with an exception, or that exceed the limit (default 100,000 characters) are also stopped, because whether they are posts
  cannot be confirmed (fail-closed)
- Even if the text can be extracted, if it is under 200 characters it is passed without going to coldreader (so that coldreader is not started for short boilerplate replies)
- When one command carries several texts, only the longest one is passed to coldreader. A works-dispatch summary is never the one chosen: the `gh` text is read however long the summary is, and a command that also delivers a summary with owner questions is stopped and must be split into two commands. A review JSON's `.body` and
  its line comments (`comments[].body`) are combined into one and read together (before, line comments were not looked at when `.body` was present, and 27 went out unread)
- On a heredoc's start line, forms where a flag or pipe follows the delimiter on the same line (`<<'J' -q .html_url`, `<<'EOF' | tail`), and
  forms with 2 heredocs on one line, are also read as the text of the simple command they are attached to
- Flag spellings change meaning by context, so long flags (`--body`, `--notes`, `--comment`, `--readme`,
  `--body-file`, `--notes-file`) are treated as text by spelling alone, and short forms (`-b`, `-c`, `-n`, `-F`) are treated as text only inside subcommands where they
  mean text (decided by scanning every subcommand of gh 2.96.0).
  So `gh pr checkout -b <branch name>`, `gh issue view -c`, `gh run download -n`, etc. are
  not posts and are not caught by the net. Conversely, even if gh adds posting subcommands, they are caught by the net if written with long flags.
  New subcommands used only with short forms are missed
- The hook's start line runs `hooks/run-python.sh` with bash. It tries `python3`, `python` and `py -3` in that order and uses the
  first one that actually starts and is Python 3.9 or newer (on Windows, `python3`/`python` can be the Microsoft Store placeholder,
  which only prints an install hint; picking the first name on PATH would make every hook fail and the gates silently not run).
  If none works, it prints how to fix it once per conversation and the gates do not run. In an environment without bash, the host
  cannot start the hook at all, so the gatekeeper does not run regardless of how the start line is written
- The screen for a new PR or issue is assembled only for `gh pr create` and `gh issue create`. The title is taken from `--title`, the repository from
  `-R` (if absent, `gh repo view` in the place where gh runs), and the PR's branches from `--base` (if absent, the default branch) and `--head` (if absent, the current branch
  of the place where gh runs);
  changed files come from GitHub's compare (available only when the branch has been pushed), and the titles of #numbers are looked up with the issues API.
  The place where gh runs is read as far as a preceding `cd <absolute path> &&`. For forms where the place cannot be determined (cd with a relative path, etc.), lookups that depend on the place
  are not made and nothing is passed (so that the content of a different branch in the hook's location is not passed as the screen). Even a word that is in the screen's title, if the text uses it
  as its own word and the meaning cannot be taken, is a blocker (what the screen makes clear is what is pointed at, not the meaning of the word).
  What could not be fetched is not passed, and the writer is told so (the rest is used for reading). Forms that create directly with `gh api`
  (POST to `repos/o/r/pulls`, etc.) and the title in forms that omit the title with `--fill` are not picked up
- The thread's screen is passed only when the destination is an existing thread: when the `gh api` path is
  `repos/o/r/pulls/N/comments/ID/replies` (also the form without the PR number), `repos/o/r/pulls/comments/ID`, `repos/o/r/pulls/N/comments`,
  `repos/o/r/pulls/N/reviews`, `repos/o/r/issues/N/comments`, `repos/o/r/issues/comments/ID`, or
  `repos/o/r/(issues|pulls)/N`, or for `gh pr comment/review/close/reopen/merge/revert/edit` and
  `gh issue comment/close/reopen/edit` (resolving the number, URL, or branch is left to gh itself; `gh pr comment` without a number
  means the current branch's PR). For a review thread, only the replies chained to the same root are passed; for a PR/issue
  conversation, the body (up to 12,000 characters) and the most recent 30 comments (the list is fetched 100 at a time, up to 5 pages; when the total exceeds 40,000 characters, the oldest
  are dropped first, and the 1 comment just before the one being answered is never cut). Up to 8 titles of #numbers that the body and the thread refer to. The gh calls that fetch the screen are cut off after 40 seconds
  in total and fall back to zero context (because if the hook itself times out, the post passes unchecked). `gh discussion` does
  not fetch the screen (zero context)
- Values that are not text are not sent to coldreader (an external process): `gh secret set --body`,
  `gh variable set --body` (the value is the secret itself), and `gh api --input` JSON (only when it has `.body`
  is that content read; JSON without it is not sent)

## coldread — local documents (read after writing; return findings without stopping)

When a document with the extension md, mdx, adoc, asciidoc, rst, or txt is written, a PostToolUse hook
only records the path per role that wrote it and ends. The tools it picks up are Write, Edit, MultiEdit, Bash, and MCP writing tools (see "Breadth of pickup" below). When the writing role ends, the documents that role wrote are read by coldreader once each,
with the same request text as for posts (`COLD_PROMPT` in `coldread-gate.py`; the single source of truth for the first-reader viewpoint is this one place).
If there are blockers, the findings are returned and the writing role is made to continue (the writes are not undone). Guesses (places the reader filled in by guessing) and questions are returned along with blockers.
If there are only guesses and questions, the writing role is not woken, and `guess=<count>` is recorded in `docs.log` (as with the post gatekeeper and the branch gate, only blockers stop).
Back when guesses also woke the role, the reader wrote down even guesses that did not hinder understanding, so almost every document came with findings, and every fix got the fixed section
read again (in 5 hours on 2026-10-17: 12 blockers against 395 guesses; 17% of the usage spent on fix cycles).

- **Range read**: for documents that already existed, only the sections containing the rewritten parts (from a heading to just before the next heading; for md and mdx `#`, for adoc `=`,
  for rst underlined lines; for documents without headings, the rewritten lines plus the surrounding text up to paragraph breaks) and the opening that tells what the document is (the title and first paragraph) are
  given to the reader, and findings are asked for only there. For sections over 2000 characters, not the whole section but only the section heading and the paragraphs and list items containing the rewritten lines (including continuations such as indented child items
  and code fences) are given. Back when long sections were read whole, after fixing just 2–3 places in a section of about 14,000 characters, the branch gate
  raised new blockers from unrewritten items of the same section on every run, and it finally passed on the 6th run. Words that may be explained in omitted sections are to be raised as questions, not blockers. Newly created documents and
  documents where the extract would be 80% or more of the whole are read in full. The previous version is the content before writing at the time the role first recorded it in that run
  (for Write and Edit, `originalFile` in the hook's input; for Bash, the HEAD version before it ran [for a document committed in the same command, the version before that commit]; for MCP tools, the HEAD version at recording time. A document
  not in HEAD is a new document). Back when whole documents were read, adding a few lines to a document of about 200 lines made the reader time out, and every one-sentence fix brought back old questions about
  sections that had not been fixed. When extracted, the length field in `docs.log` is "characters passed/total characters"
- **Skill documents are read with what is read before them**: for a document in a skill folder (`skills/<name>/`, the folder that holds a file named exactly `SKILL.md`), the reader gets a note before the body.
  A separate file (such as `references/*.md`) gets the skill's `SKILL.md` as premise; the reader takes the words and steps explained there as known and reports only on the body.
  `SKILL.md` does not get the content of the files it points to, only their names (files of the same folder whose relative path is written in `SKILL.md`) and the note that they are opened where `SKILL.md` points,
  so their content missing from `SKILL.md` is not a blocker; a pointer that does not say when to open it or what is in it, and words not explained within `SKILL.md`, are still reported.
  The premise is the current content in the working tree for the read the hook runs at the end of each turn, for the branch gate, and for the manual command `bash hooks/run-python.sh hooks/coldread-gate.py read <パス>` (on a rerun of the branch gate, a changed `SKILL.md` alone does not make its separate files read again; see the branch gate below).
  An agent using a skill reads `SKILL.md` first and opens a separate file when `SKILL.md` points to it (`docs/standards/skill-authoring.md`, rules 3 and 4). Read alone, a separate file lost the words explained in `SKILL.md`,
  and `SKILL.md` was blocked because the content it pointed to was not there; each fix brought new blockers elsewhere and the branch gate kept stopping (2026-10-18: 7 → 19 blockers when splitting 3 skills of attention).
  `SKILL.md` is not given the pointed content because the agent reads `SKILL.md` before opening them, and because a `SKILL.md` that points to 12 files would make one edit read most of the folder
- **Generated files are not read**: documents marked `linguist-generated` in `.gitattributes` (the GitHub Linguist mark; with no value or `=true`;
  `-linguist-generated` and `=false` count as unmarked) are not read. To mark them, add one line to `.gitattributes` such as `reference/_snapshots/** linguist-generated`
- **Documents covered by another check can also be excluded**: even human-written documents, where a different check is responsible (such as notes that copy and are checked against an original),
  are not read if you add one line to `.gitattributes` such as `reference/primary/** -coldread` (only the `-coldread` form excludes; do not use the generated-file mark, which means something else)

How findings are returned depends on the writing role:

- **Documents written by a subagent (worker)** are read when that role ends (the SubagentStop hook), and the full findings are returned to that role
  to fix. Records are separated by `agent_id` in the hook's input (present only inside subagents), so they are not read
  at the end of the parent session. Before, they were read at the end of the parent session's turn, so the findings reached the parent, which could only resend them to the worker, eating up the parent's context.
  It also wasted reads on drafts a worker had not finished writing
- **Documents written by the parent session** are read at the end of the turn (the Stop hook). The full findings are not piled into the parent's context;
  they are written out to files in `$CLAUDE_CONFIG_DIR/coldread-gate/docs/findings/` (the newest 200 are kept), and only a short notice is returned with the number of documents, the counts, the file location, and
  「新しいサブエージェントに渡して直させる。推測で埋めた箇所のうち書き手の意図と違うものだけは親が見る」 ("hand it to a new subagent to fix; only the guesses that differ from the writer's intent are for the parent to look at").
  The notice also says to pass that subagent the model and effort that the repository's instruction files (CLAUDE.md, AGENTS.md, etc.) prescribe, if any, and to leave them unset otherwise.
  gates names no model itself; the using repository decides (for example, sending routine wording fixes to a cheaper model).
  In an interactive session it reads in the background, so if /clear is typed while it reads, the notice reaches the session after /clear. A session that ended with /clear is
  remembered by the SessionEnd hook (reason is clear) in `$CLAUDE_CONFIG_DIR/coldread-gate/docs/cleared`, and the notice for that session's documents says
  「/clear で終わった前の会話(id)が書いた文書で、意図はこの会話に無い。詰まりは直させ、推測で埋めた箇所は文書のほかの所・commit の記録・頼みのファイルで意図が確かめられるものだけを直させ、確かめられないものは残す」
  ("these documents were written by the previous session (id) that ended with /clear, and their intent is not in this session. Have the blockers fixed; for guesses, fix only those whose intent can be confirmed from elsewhere in the document, the commit history, or the request file, and leave the ones that cannot")
- **Read before merging into the mainline (メインブランチに入れる前に読む; the branch gate)**: `bash <gates の置き場>/hooks/run-python.sh <gates の置き場>/hooks/coldread-gate.py branch-check [--base <メインブランチの ref>]` (`<gates の置き場>` is where gates is installed; `<メインブランチの ref>` is the mainline ref)
  compares against the point where the branch split off from the mainline (by default the branch that `origin/HEAD` points to) and reads the documents the branch added or changed with the same reader and viewpoint. Documents that already existed are
  compared with the version at the split point, and only the rewritten sections are read (for long sections, only the rewritten paragraphs and items; see "Range read" above). For documents the branch added too,
  lines that existed in the split-point version of documents the branch deleted or changed (where they moved from) (compared ignoring leading/trailing whitespace and heading `#`) are treated as pre-existing lines,
  and only sections containing newly written lines are read. If every line is pre-existing, the document is not read. Copies of lines left in the original are treated the same way.
  This is so that when sections of a skill's body SKILL.md are moved to `references/` without changing a character, sentences that were already in the mainline are not read again.
  Trade-off: if, at the new location, words that were explained in an earlier section of the original body become unclear, the branch gate does not catch it (the entry guidance and word explanations
  that stay in the body SKILL.md are still read when that SKILL.md itself is read, as before). The end-of-turn read still reads added documents in full as before.
  If there is even 1 blocker, it stops with exit code 1; if there are only guesses and questions, it passes with 0.
  Blockers that were already in the mainline version do not stop the branch: for a document that existed at the split point, each blocker is sent with the new and the split-point versions
  to the same reader model, which answers whether the split-point version blocks a reader at the same place for the same reason. Those are listed in the full findings under
  「メインブランチの版にも在った詰まり」 ("blockers also in the mainline version") and counted apart in the last line, but do not change the exit code. If the answer is unsure it counts as new,
  and if the comparison cannot run, every blocker counts as new (both stop as before). Documents the branch added are not compared.
  This is because rewording that spreads over a whole document (such as replacing words with established IT terms) makes even the rewritten-sections read cover most of a long document,
  so blockers that were always there kept stopping the merge and moved to another place after each fix (2026-10-19: 36 → 17 → 23 blockers).
  Reading the split-point version separately and matching the two lists is not used, because the reader picks different places on each read, so blockers that were already there would rarely match.
  With `--fixer <Python file>` (a file that defines `fix_text(text)` returning the text with words replaced; this repository passes `works-dispatch/dispatch/terms.py`, the list of established IT terms),
  `fix_text` is applied to the split-point version (for added documents, to the lines moved from the original), and a current line that differs from the old line only where `fix_text` changed a word is not counted as rewritten.
  This covers lines equal to the `fix_text` result and lines where a different word was chosen by hand at the same place, if that word is only katakana, ASCII letters, digits, hyphens, and spaces (up to 12 characters per place).
  Kanji and hiragana are not allowed there, because they can add meaning (such as 「ブランチ以外」, "other than the branch"); deleting the word is also counted as rewritten.
  Lines that also change text outside the replaced words are read as before. If the file cannot be loaded or has no `fix_text`, it stops with exit code 2;
  if `fix_text` raises, returns something other than a string, or changes the number of lines, no replacement is applied and documents are read as before.
  This is because replacing words with established IT terms spreads over almost every section, so the rewritten-sections read went over 80% (`DOC_WHOLE_RATIO`) and read whole documents,
  stopping on old writing (2026-10-19: 394 blockers in 80 of 108 graphloops and convergence-loops documents, none about the replaced words).
  Whether a replaced word fits its meaning is checked by the side that replaced the words, which sees the old and new words side by side, not by the cold reader.
  It also stops with 1 if there are documents for which the reader could not be started (passing them unread would make the gate silently empty). At the end of standard output, it prints the blocker lines (with paths from the
  root of the working tree) and the counts and the location of the file with the full text. Verdicts for the same request text are remembered in `$CLAUDE_CONFIG_DIR/coldread-gate/docs/branch/`, so
  reruns after the mainline moves forward and the branch is rebased do not read again.
  A rerun on the same branch reads only what changed since the last run: per branch and document, the gate keeps the version it last finished reading and its verdict
  in `$CLAUDE_CONFIG_DIR/coldread-gate/docs/branch-last/` (the newest 2,000 are kept), reads only the sections rewritten since that version (the same range read as above),
  and does not read again a document whose text has not changed (also when only the premise `SKILL.md` of a separate file changed).
  The blockers that stopped the last run are asked again only when the document's text or its premise changed: each is sent with the whole current version and the premise
  to the same reader model, which answers whether it still blocks a reader at the same place for the same reason (`still`) or not (`fixed`) in a JSON answer. `still` blockers stop as before, `fixed` ones do not,
  and an unsure answer or a check that cannot run keeps the blocker. A blocker is dropped without asking when every passage the reader copied from the document into the `quotes` field of its answer (each 4 characters or more) was word for word in the version where the blocker was found and is gone from the current version: the section that held those passages was rewritten and is read anew in this run (on 2026-10-19 the re-ask answered "still blocks" for a blocker whose quoted passage had been rewritten, so asking would have kept a fixed blocker). If neither text nor premise changed, the blockers stop again without asking, because each new question
  could let an unfixed blocker pass on the reader's variation. Only blockers found in this run are compared with the mainline version (a blocker the mainline version also has does not stop the branch; see above).
  A run is not kept when the reader could not be started, or when the re-ask or the mainline comparison could not run; the next run starts again from the version kept before (verdicts already read are remembered, so this costs no new read).
  The kept versions are not used when the reader's request text, the model, or the effort changes (such as after updating gates to a new version).
  `--land` runs the check in a temporary worktree with no branch checked out (a detached HEAD, with the version bump commit on top of the branch);
  there the gate looks for a local branch whose latest commit is in HEAD's history and comes after the split point (the commit where the branch left the mainline); the mainline and other branches whose latest commit is at or before the split point do not match.
  Normally this is exactly one branch, the branch being merged, because the temporary worktree is that branch plus the version bump commit; the gate then uses that branch's last run.
  When HEAD is ahead of that branch's latest commit (the version bump commit on top), the gate reads each document as it is in the branch's latest commit, not as it is in the worktree,
  and keeps that version. The bump is added by `--land`, not written by the author. If the gate kept the bumped version, a rerun in the branch's own worktree (before the bump) would see the moved headings
  (such as `## [Unreleased]` becoming a version heading in a CHANGELOG) as the only rewrite. The reader would get only those headings and report that it cannot read any content (2026-10-19).
  If zero or several local branches match, it uses no last run and reads from the split point as before.
  This is because fixing one line made the reader read the unfixed paragraphs of the same extract again, and the reader picks different places on each read,
  so new blockers kept coming from paragraphs that were not touched (2026-10-19: 10 → 2 → about 10 → 7 blockers over 4 `--land` runs while splitting a works skill).
  It is the same shape as reviewing only the changes since the last review (GitHub's "changes since last review", CodeRabbit's incremental review).
  Trade-off: a sentence that becomes unclear because another section or the premise `SKILL.md` changed (such as a word explanation removed from `SKILL.md`) is not caught until its own section changes.
  A branch recreated with the same name as a deleted one continues from the deleted branch's last run. Another branch has no last run and reads from the split point.
  To use it, write it as one of the check commands that run before a branch is merged into the mainline. In this repository,
  the works-dispatch plugin's (a tool that starts sessions in a workspace per branch to carry out work) command for merging a branch into the mainline, `--land`, first runs
  the command written in `check` under `[land]` in `.claude/company.toml`, and does not merge the branch if that command fails. In this repository that `check` command runs `python3 gates/hooks/coldread-gate.py branch-check` after the other checks, joined with `&&`, so a blocker stops the merge.
  Back when documents were read only at the end of a turn, for sessions that finish everything up to merging into the mainline within one turn (sessions started by works-dispatch to carry out work),
  the findings arrived after the merge into the mainline (8 cases on 2026-10-17). That is why it also reads with this check before merging into the mainline
- **The end of the parent session's turn is not made to wait**: in interactive sessions (including agent view sessions), the Stop hook runs in the background with `asyncRewake`
  ("Run hooks in the background" in Claude Code's hooks documentation). The turn ends immediately, and when reading finishes with findings,
  the hook wakes the session with exit code 2 and standard error to notify it (if there are no findings, nothing happens). Before, the end of the turn waited until reading finished,
  and with an xhigh reader one read took from several tens of seconds to 210 seconds. In sessions without a screen (`claude -p`), background hooks are cut off at the end of the session,
  so it waits and reads as before. They are told apart by `CLAUDE_CODE_ENTRYPOINT`, which Claude Code passes to hooks (interactive is `cli`, `-p` is `sdk-cli`):
  when it is absent or starts with `sdk`, it waits and reads; other values (IDE extensions, etc.) read in the background. The limit for one reader run is 420 seconds both when reading in the background and when waiting
  (subagent end, `claude -p`, manual `read`, the branch gate). Back when only waiting reads were cut at 210 seconds, an xhigh
  read of a memo of about 8,000 characters exceeded 210 seconds, and no matter how many times the worker rewrote it, it timed out and no findings came out. Documents that could not be read are returned to the writer
  with the reason, timeout or could not start. At subagent end, it waits and reads as before, in order to return the findings to that role to fix
- **Breadth of pickup** (the owner's policy: 「防ぐより、ひっかける幅を増やす」, "rather than preventing, widen what gets caught". Before, only documents written with Write, Edit, and MultiEdit were picked up,
  and documents written with `cat > x.md <<EOF`, `tee`, `sed -i`, or python were never read):
  - Bash: before it runs (PreToolUse; the same hook as the post gatekeeper), the mtime and size of the documents in the change list of cwd's git working tree (`git status --porcelain
    --untracked-files=all`; including untracked files) are noted, and after it runs (PostToolUse, and PostToolUseFailure after a failure) they are taken again, and documents that were added or changed are put on the record. Documents that were already changed before are
    not picked up unless they change while it runs. For outside git and for documents git does not look at (in .gitignore), write targets inside the command (see "What counts as a document the role wrote" below)
    are also picked up statically (relative paths are resolved with the input's cwd). git is run with `GIT_OPTIONAL_LOCKS=0`
    and does not take the index lock. If one run takes more than 5 seconds, only the static reading is used. Documents written and committed in the same command are picked up from the difference in the
    git commit entries (headings `commit`, `commit (initial)`, `commit (amend)`) among the HEAD movement records (reflog) added while it ran
  - Documents brought in by git (Bash): documents that entered the working tree through a rebase onto origin/main, merge, pull, checkout, stash pop, etc.
    are not picked up as documents written by the writing role. Differences from HEAD movement records other than commits (headings such as `rebase (pick)`, `checkout: moving …`,
    `commit (merge)`; the difference of a merge commit is the other branch's content) are not picked up, and for commands that ran git commands that write the working tree (`checkout`, `restore`, `reset`, `rebase`, `merge`, `pull`,
    `cherry-pick`, `revert`, `am`, `apply`, `stash`) or that moved HEAD by something other than a commit, differences in the change list are not picked up either
    (write targets whose content is in the command text are picked up). Documents stopped by a conflict (change-list marks `UU`, `AA`, etc.) are never picked up, and are picked up after they are fixed and `git add`ed.
    Up to 0.18.0, the whole difference between HEAD before and after was picked up, and in a session that rebased, 6 documents that came in from the mainline were read and findings were returned to a role that had not written them
  - What counts as a document the role wrote (Bash): only writes whose content is in the command text count as documents the writing role wrote: the destinations of `cat` and `tee`
    receiving a heredoc or here-string, the destinations of `echo` and `printf`, the destinations of `tee` and `cat` receiving those through a pipe, and `sed -i`. Destinations of
    redirected output of other commands (`sed -n … ci.log > x.txt`, `git log > x.txt`, `python3 - > x.md` running a heredoc as a script) and
    destinations of `cp`/`mv`/`install` are copies of content from elsewhere, so they are not picked up, and are also excluded from git's change-list difference (0.14.0 did pick them up, and
    the reader read a temporary file holding an excerpt of a CI log and returned blockers)
  - MCP tools: for tools whose names look like writing tools (write, edit, create, update, save, move, copy, etc.), the path field of the input is picked up
  - NotebookEdit is not picked up (`.ipynb` is not among the document extensions, so it would not be read even if picked up; the matcher names for Write, Edit, and MultiEdit are not changed because works relies on them by name)
  - When roles run side by side in the same checkout (workers of the same session, the parent and a worker, parallel sessions), documents other roles wrote while a Bash ran also
    show up in the change-list difference. Documents picked up by difference are assigned to only one role, telling the writing role apart in the following order. Before, they were assigned to the role that ran the command, and
    in a session running 7 workers side by side, a worker that ran a check taking 3 minutes received findings on notes that other workers wrote in the meantime (2026-10-17)
    1. If there is a mark that another role wrote that document while it ran (set by Write, Edit, MCP tools, and Bash with a write target in the command text; also set on documents picked up
       by another role's Bash difference and assigned to that role by this order), assign it to that role
    2. If there is no mark, and another role's Bash was also running at the time the document changed (mtime; for documents picked up by commit, the reflog time),
       choose first the role whose command text contains the document's name (for documents picked up by commit, the role whose command contains `git commit`), then the role that started running later
    3. Before reading, look at the role that last wrote the document, and if it is another role, do not read it (it is read at the end of the role that wrote it last)
    Forms that cannot be told apart: a document written during a long Bash run without its name appearing in the command text is assigned to the Bash of another role that started later and
    was still running at the same time. The write marks and the Bash windows are kept in `claims` and `windows` under `$CLAUDE_CONFIG_DIR/coldread-gate/docs/`
    (when over 1 MB, lines older than 24 hours are discarded), and the windows of running Bash commands are read from the pre-run notes (`docs/snap/`)
  - Not picked up: documents written later by Bash run in the background (`run_in_background`), ways of writing outside git where the write target does not
    appear in the command text (writing inside python or a script), and MCP tools whose names do not look like writing tools
  - Cost (measured on this macOS environment on 2026-10-16; the median time added per Bash run, total of the before and after hooks): outside git
    about 70ms (mostly starting python for the after hook), this repository (about 2,600 files) about 140ms, a repository of about 5,800 files
    about 170ms, a synthetic repository of 100,000 files with 2,000 untracked documents about 720ms (one `git status` takes about 260ms).
    If it is too heavy, turn off the whole local-document gatekeeper with `COLDREAD_DOCS_OFF=1`
- Posts cannot be taken back once made, so they are stopped before writing. Local documents can be fixed after writing, so they are not stopped. Reading on every write would
  make each Edit wait and read the same document many times
- The reader runs a cheaper model than for posts, with higher effort (default haiku, high; change with `COLDREAD_DOC_MODEL` and `COLDREAD_DOC_EFFORT`).
  This is because Anthropic's [effort documentation](https://platform.claude.com/docs/en/build-with-claude/effort) says to use high for Haiku 5.5 for knowledge work and
  strict instruction following, and to use xhigh and max only where evaluations show they improve quality. The reader for posts stays at sonnet, medium
- Not read: under 300 characters (`COLDREAD_DOC_MIN_LEN`), a `coldread:skip` or `coldwrite:skip` mark on the first line,
  the `linguist-generated` mark, the same content as before writing, and the same content as read before (the content's sha256 is remembered in `$CLAUDE_CONFIG_DIR/coldread-gate/docs/seen`)
- Files written in a temporary location outside a git working tree are not read either (copies the writing role placed for itself, or request documents it was given).
  Temporary locations are the candidates Python's `tempfile` chooses a temporary folder from (the environment variables `TMPDIR`, `TEMP`, `TMP`, and fixed OS locations:
  `/tmp`, `/var/tmp`, `/usr/tmp` on macOS and Linux, and `~\AppData\Local\Temp` and `%SYSTEMROOT%\Temp` on Windows), plus
  the actually chosen `tempfile.gettempdir()`. Both the spelling and the real path are compared (macOS `/tmp` → `/private/tmp`, `/var` → `/private/var`).
  Claude Code's scratchpad (on macOS, `/private/tmp/claude-<uid>/…`) falls under this too. Claude Code's per-session temporary locations
  (`$CLAUDE_CONFIG_DIR/jobs/<session id>/tmp/` and `$CLAUDE_JOB_DIR/tmp/`; where agent view sessions put request summaries and copies) are also
  treated as temporary locations. Inside git, files are read even under a temporary location.
  To change the roots, use `COLDREAD_TMP_DIRS` (separated by `os.pathsep`; used instead of the defaults)
- A fixed document is read again at the end of that role, and if it is not fixed it has the same content and is not read again — if you decide not to take a finding,
  you may just finish. When reading while waiting, Claude Code cuts off consecutive returns after 8
- To turn off only the local-document gatekeeper, use `COLDREAD_DOCS_OFF=1` (the post gatekeeper stays)
- The record is `$CLAUDE_CONFIG_DIR/coldread-gate/docs.log` (read, reasons for not reading, reader could not be started; subagent lines
  carry `agent_id` in `aid=`. Lines where the reader was started carry the seconds the read took in the form `35s` and the reader's effort in the form `e=high`.
  If you write `COLDREAD_DOC_EFFORT` in `env` in an account's settings.json, the effort changes only for that account's sessions)
- The list of documents a role (the parent session or a subagent) wrote (`docs/<session>.pending`, or `docs/<session>.<agent_id>.pending` for a subagent) is renamed to
  `<list>.<pid>-<time>.reading` before it is read, and removed only after the read ends. If the reader is cut off (the hook timeout, or a background read
  killed when the conversation closes), the `.reading` file stays; the next time that same role ends a turn (Stop or SubagentStop), one older than 960 seconds (the hooks' 900-second timeout
  plus a margin) is taken back: its paths are added to that read's `.reading` file, the file is removed, and its documents are read again,
  except those already read with no blocker to return (marked `#done` in the `.reading` file)
- One end reads at most 8 documents (4 at a time, two rounds of the 420-second reader limit inside the 900-second hook timeout).
  The rest go back to the list, the role is told how many were left, and they are read at its next end.
  A parent conversation run with `claude -p` has no next end after the notice, so there all documents are read in one end
- Lists and `.reading` files last modified more than 1 day ago (the writer ended without them being read) are reported once at the end of a parent conversation's turn (not a subagent),
  both to the conversation and on the owner's screen, with the paths and how to read or remove them
- Manual entry point to read one file: `bash hooks/run-python.sh hooks/coldread-gate.py read <パス>` (`<パス>` is the path; exit code 1 if there are blockers. `run-python.sh` picks a Python that actually starts; a bare `python3` can hit the Microsoft Store placeholder on Windows).
  The request text itself is printed by `bash hooks/run-python.sh hooks/coldread-gate.py prompt`

Before, coldwrite, a separate plugin, read documents with a prompt-type hook before Write and stopped the write. A prompt-type hook sees only the content passed
to the tool, so with Edit it could read only the few replaced lines, not the whole document. It was moved to gates, coldwrite was removed from the marketplace, and
the name was reassigned to gates with `renames` in `marketplace.json` (settings that had coldwrite enabled are rewritten by Claude Code to the gates name).

First-read checks of documents across the whole repository are done by convergence-loops' `/firstread-loop` (the heavy older sibling).
This one is the light younger sibling for short texts read on their own, and as a hook it works without being called.

## destgate — allowlist for post destinations (dormant by default)

The second gatekeeper, restricting a different axis from coldread: "may this be posted to that destination". The decision is deterministic (no LLM).

- If `$CLAUDE_CONFIG_DIR/destgate/allowlist` does not exist, it does nothing. Creating it turns it on
- The format is one pattern per line: `owner/repo`, `owner/*`, `gist` (lines starting with # and empty lines are ignored)
- The destination is determined in the same order gh itself resolves it: `-R/--repo` → the `gh api`
  path `repos/{owner}/{repo}` or `orgs/{org}` → if neither, the repository gh picks for the current directory
  (`gh repo view --json nameWithOwner`; not `origin`, because gh may pick the `gh repo set-default` repository or another remote).
  Posts whose destination cannot be identified are stopped with a request to specify `-R` explicitly
- **There is no escape hatch**. To let something through, a person adds it to the list — that addition becomes the record
- **Managing the list is a person's job**. A model that received a deny editing the list itself to get through would be disabling the gatekeeper,
  and the deny message forbids it too (it cannot be enforced by machine, so it is stated as a rule)
- It fails closed: when the list exists, a hook input it cannot read, and a gh command it cannot parse, are stopped (the destination cannot be checked)

## searchgate — no searches from / or the whole home

The third gatekeeper. It protects the local machine instead of what goes out. On 2026-10-24, two `find / -name …` commands run by sessions
(Claude Code runs find as `bfs`) used 860% CPU in total (about 8.6 cores) for an hour and pushed the load average to 55–70 on a 24-core machine. They outlived the Bash
timeout, and `pkill -f "find / …"` did not match the `bfs` process name. Writing "do not search from /" into one repository's instructions does
not reach sessions working on other repositories, and a session can still miss it, so this is one rule, enforced by a hook, for every session.

- The rule: if the start of a search is `/`, a large folder right under it (macOS: `/Users`, `/System`, `/System/Volumes/Data`, `/Volumes`,
  `/private`, `/opt`; Linux: `/home`, `/usr`, `/var`, `/mnt`, `/media`, `/root`, `/srv`), a Windows drive root or a large folder right under it
  (`Users`, `Windows`, `Program Files`, `Program Files (x86)`, `ProgramData`), or the home folder itself (written as `~`, `$HOME` or its
  absolute path), the call is stopped before it runs, and the session is told to start from its working
  folder (the folder the session runs in) or from the place the thing is known to be kept. Anything below these (`~/.cache/works-factory`,
  `/opt/homebrew`, `/usr/local/lib`, the working folder) passes. Only the start is checked: an allowed search is not limited in depth or running time
- A Windows drive is the same place however it is written: `C:/…`, `C:\…`, Git Bash's `/c/…`, Cygwin's `/cygdrive/c/…` or WSL's `/mnt/c/…`.
  Upper and lower case are not told apart (the default file systems of macOS and Windows do not, so `/users` searches the same folder as `/Users`)
- What it reads (a PreToolUse hook, which runs before each Bash, Glob and Grep call): `find`, `bfs`, `gfind`, `fd`, `rg` and `grep -r` in Bash, also behind `nice`, `sudo`,
  `xargs`, `timeout` and so on, and inside `bash -c "…"`, `eval`, `$( … )` and `` ` … ` ``; the `path` of the Glob and Grep tools and the
  fixed head of a Glob pattern (`/Users/**/x` starts at `/Users`; a pattern with no wildcard looks at one path and passes). A start with a shell
  wildcard counts as the folder above the wildcard (`find ~/*` starts at the home folder). With no path, the start is the session's working folder
- Variables in the start are resolved from assignments in the same command (`D=/; find $D`) and from `~`/`$HOME`; a relative start is resolved
  from a preceding `cd <absolute path>` (followed by `&&`, `;` or a new line; a bare `cd` is the home folder) or the session's working folder.
  Calls that take no start (`--help`, `--version`, `command -v rg`) pass. A start it cannot resolve (an unknown variable, an assignment inside an
  `if`) is not stopped, because nothing in the text says it is wide
- The decision is deterministic (no LLM) and **there is no escape hatch**. It fails closed: if the check itself fails (input it cannot read),
  the call is stopped. Stops are logged to `$CLAUDE_CONFIG_DIR/searchgate/denies.log` (the Claude Code
  settings folder, `~/.claude` by default)

## waitgate — no hand-written waiting loops

The fourth gatekeeper. On 2026-10-24, sessions that waited for a background job with a loop they wrote themselves (`until grep -q … out.txt;
do sleep 3; done`, `while pgrep -f "research.py theme"; do sleep 5; done`) kept looping after the job was gone, and the sessions stood still
for 28 hours, 16 hours and 38 minutes. Running the loop in the foreground does not help: when a foreground Bash command reaches its timeout,
Claude Code moves it to the background instead of stopping it (["Foreground commands that move to the background"](https://code.claude.com/docs/en/tools-reference)).
The right way to wait is to run the awaited command itself with Bash's `run_in_background` and end the turn; Claude Code wakes the session when
it finishes.

- The rule: a Bash call is stopped before it runs, in the foreground or the background, if it has a `while` or `until` loop that runs `sleep`,
  or if it has a `while`/`until` loop (or a `for` loop that runs `sleep`) together with `pgrep`/`pidwait -f` (`--full`), `pkill -0` or
  `ps … | grep` (`pkill -0` sends no signal; it only checks whether a matching process is alive). These look for processes by the whole
  command line, so two loops waiting for the same text find each other's shells and never end.
  A `pgrep -f` inside any `for` loop is stopped too (run it in a separate Bash call to pass), and `for ((;;))`, which has no end condition,
  counts as a `while` loop
- What passes: a single `pgrep -f` with no loop, loops that do not run `sleep`, `while read` loops (they end when the input ends, e.g.
  `ps aux | grep x | while read u p _; do kill $p; done`), a `for` loop that runs `sleep` a fixed number of times, `ps | grep` in a `for` loop without `sleep`, and `--until` or `for` inside a word or an option
- What it reads: loop words at the head of a command (start of a line, after `;`, `&`, `|`, `(`, `)`, `{`, `}`, `!`, `do`, `then`, `else` or `time`). Text in
  quotes and here-document bodies is ignored, except the arguments of `bash -c` (also `bash -o pipefail -c`) and `eval`, `$( … )` and `` ` … ` `` inside double quotes, and a
  here-document read by a shell (`bash <<EOF`). Not seen: a loop inside `python3 -c`, `awk` over `ps`, or a loop in another script
- The decision is deterministic (no LLM) and **there is no escape hatch**. It fails closed: if the check itself fails, the call is stopped.
  Stops are logged to `$CLAUDE_CONFIG_DIR/waitgate/denies.log` (`~/.claude` by default). The rules are copied from my_notes' `tools/no_wait_loop.py` (master 2d951aab)
