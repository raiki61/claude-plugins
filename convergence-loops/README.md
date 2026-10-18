# convergence-loops

> Four Claude Code loops that keep reviewing, researching, diagnosing, or first-reading until they reach a fixed point, with the implementer and the grader held in separate contexts. The machine is only ever allowed to declare failure, never convergence.
>
> **The instructions are in Japanese, but you don't have to read them — Claude does.** The skills' and commands' instructions and descriptions are in Japanese. The loops report back in *your* language, so they work whatever you speak. Japanese is kept for the prompts because the criteria lean on the imperative force of the original wording and a translation would loosen it. You only need to read `REVIEW.md` yourself if you want to grow the criteria.

This plugin ships four loops that run until they converge. This README is for people who install the plugin and run the loops; the sections near the end on customizing and checks are for people who change the loops themselves.

Changes per version are in [CHANGELOG.md](CHANGELOG.md) (the log for convergence-loops; each other plugin has its own CHANGELOG.md in its own directory). How versions are released (the step that appends to the change log; no git tags are created) is in [docs/releasing.md](../docs/releasing.md).

- **`/review-loop`** — takes a code change you implemented and repeats review and fix until it converges
- **`/research-loop`** — calibrates your assessment of a design, method, or technology choice against primary sources from industry and academia, then optimizes it for your domain
- **`/doctor-loop`** — diagnoses the current state of the repository itself, read-only, and verifies improvement candidates (reduce, turn into a machine check, fix the structure, bring up to date) until no new findings appear, and returns **proposals only** (it applies no changes). It does not diagnose a change; it **diagnoses without waiting for a change**
- **`/firstread-loop`** — checks whether a finished document gets through to people who did not write it, and **fixes the places where it did not**. Each time it starts a fresh reader role that does not know the document, **gives it only a task and has it search from the repository's entry point**, and collects **where it stopped, what it misunderstood after reading, and what questions came up while reading**. Questions that got no answer may be a hole in the design rather than a gap in the document, so they are kept, not filled in. It does not measure a readability score ── **the author cannot judge whether their own document is understandable**. That is the premise of this loop

None of them is "do it once and stop". Each one **runs until it reaches a fixed point (zero findings for review, zero new discrepancies for research, zero new findings for diagnosis, zero new stumbling points for first-read), and if it does not reach it, reports that it did not**.

## How this differs from an ordinary review request

The reasons it works come down to four.

**1. Keep the implementer and the grader in separate contexts (writer ≠ grader)**

The session that runs the loop (the writer) only collects findings mechanically; it does not finalize labels, diagnose root causes, or judge convergence. A subagent in a separate context (the grader) does that. The writer only fixes the `[block]` items the grader has confirmed, and cannot downgrade a label itself. When it disagrees, it does not overturn the decision itself; it has a grader in a separate context re-judge. If you let an implementer grade its own work, the side that gains from doing less work gets to set the pass criteria.

**2. Never let the machine declare a pass. Let it declare only failures**

What `review-record.py` returns is only "N items blocking convergence". "No blockers" is not a declaration of convergence; it only means nothing was found *within what a machine can find*. Convergence is declared by a human.

**3. Do not let a silent omission pass as "none"**

"Not done because the condition did not apply (`not_applicable`)" and "should have been done but was skipped (`not_run`)" are recorded as different values, and an empty field fails validation. If you have the agent write this in prose, the two collapse and the latter turns into the former. A check that was never run getting reported as "no problems" is the original hole this loop was built to close.

**4. Run eyes with different input isolation side by side**

On the same diff, it runs in parallel a grader that knows the task context, a grader that is not given the findings, a grader that is **not told what feature the diff is for**, and a grader that looks only outside the repository (official documentation, OSS issues). Eyes with different inputs catch different layers — a grader that does not know the context cannot justify something with "this is fine for this use", so it catches hygiene violations general to the language or framework. The isolation is enforced by tools, not by instruction — the eyes that are cut off from context are started as role agents with no tools at all, so they physically cannot reach nearby code or the web (see "Role agents" below).

`/review-loop` **does not throw away trends across rounds**. Every round it re-grades in a fresh context, while the history of the record (the same finding flaring up again, things that were supposedly fixed reappearing, how the count of must-fix items changes) is passed to the judge after the verdict is finalized, to show it the cause of a flare-up (the code, the reviewer, or a rule misfiring) and any growth beyond the purpose. Candidates for asking a human (a fork in the design, something outside the purpose, a premise that does not hold, a main path that cannot be run, and so on) are **not asked in the round they come up**; they go into the question ledger (問いの台帳) and the next round's judge re-examines them — a question that looked hard only to the eyes of the round where it came up disappears with the next round's material and an independent re-derivation (measured: the 3 items that came up as forks in an earlier review all disappeared in later rounds through a zero-cost remedy outside the offered options). The loop stops to ask only when the machine says that the remaining blockers are only the ones attributed to held questions, and questions the loop decided by itself are listed in the report with their grounds. For comments, when it has the agent list candidates for deletion, it makes it **name where the same content already lives** (anything it cannot point to is not deleted), and **also makes it state in one sentence the fact a comment carries when it decides to keep it** (if only deleting had to be justified, silently keeping would become the cheaper choice). Together, these two requirements push toward removing comments: they work against the comments an AI adds so it can follow the code itself, which pile up until people can no longer read the code.

Further, `/review-loop` **does not converge by reading alone**. It actually runs the main path once and observes the values that went through, and for any newly added validation gate it deliberately creates a violation and confirms that the gate turns red. Writing "tests are green" as an observation is forbidden.

## Installation

A marketplace can point at **a GitHub repository, any git URL, or a local directory**.

```bash
/plugin marketplace add raiki61/claude-plugins                      # GitHub
/plugin marketplace add https://git.example.com/team/claude-plugins   # internal git
/plugin marketplace add //fileserver/share/claude-plugins             # shared folder / local path

/plugin install convergence-loops@raiki61
/plugin install gates@raiki61            # other plugins take the same form (name@raiki61)
```

A `marketplace` is where tools are distributed from, and a `plugin` is a bundle of tools you install from it. **No setup is needed**. You can use it right after installing.

To update, run the following 2 lines. You do not need to restart the session (`/reload-plugins` reloads and applies it):

```bash
! claude plugin marketplace update raiki61 && claude plugin update <plugin-name>@raiki61 -y
/reload-plugins
```

**If you want updates to be automatic, the installing side adds 1 line to its settings.** The distributing side cannot turn it on — auto-update is a field in the user's `settings.json`, and `marketplace.json` has no matching field (checked against the 4 marketplaces on hand. The official schema `https://anthropic.com/claude-code/marketplace.schema.json` returned 404 as of 2026-09-01, so it was not compared).

```jsonc
// ~/.claude/settings.json (under CLAUDE_CONFIG_DIR if you have set it)
"extraKnownMarketplaces": {
  "raiki61": {
    "source": { "source": "github", "repo": "raiki61/claude-plugins" },
    "autoUpdate": true
  }
}
```

`/plugin marketplace add` creates this field but does not add `autoUpdate`. Whether to turn it on is up to the person installing.

**However, there is one condition on how you obtain it** — read the next section before choosing how to distribute. The 3 options above are not equal choices.

## Dependencies and how you obtain them

`/review-loop` uses the official plugin `pr-review-toolkit` for local defect review. This is declared in `dependencies` in `plugin.json`, so **it is installed together when you install this plugin** (it is in the official marketplace `claude-plugins-official`).

**If resolving it fails, this whole plugin does not load** (not only `/review-loop` but also `/research-loop` becomes unavailable). If you notice it is not available, check the state with `claude plugin list` and reinstall `pr-review-toolkit`. The alternative of running an install command inside `/review-loop` instead of declaring the dependency is not used — when the declaration is unresolved the plugin does not load, so that install command could never be reached; the two cannot coexist.

**This constraint bites in environments that cannot reach `claude-plugins-official` (on GitHub)**. Of the 3 options in the installation section above, **distribution via a shared folder or local path tends to hit this** (the more reason someone has to use it in an air-gapped internal environment, the more likely they hit it). If it cannot be reached, either prepare a route through which users can first run `/plugin install pr-review-toolkit@claude-plugins-official`, or distribute knowing that it cannot go through.

**It chooses to stop rather than let a review pass with one defect perspective quietly missing.** This is the result of applying to this distribution itself the fail-open check of validation mechanisms (does a check that fails to run let things through as if it passed?) that the bundled `REVIEW.md` 「コード衛生観点」 (code hygiene perspective) requires.

The source of truth for the review perspectives is the bundled `REVIEW.md`, and **it does not contain a single project-specific technology name**. Architecture boundaries and standard mechanisms are read by the grader each time from the target repository's README, lint settings, package manifest, and nearby code. Copying specific technology names into the perspectives makes them a duplicate of the source of truth the moment you do it, and they stay stale when the repository changes.

If you put a `REVIEW.md` at the root of the target repository, the perspectives written there are used as well (it runs without one).

## Usage

```
/review-loop                         after implementation, refactoring, or a bug fix
/research-loop <what to look into>   to firm up a design document's grounds, choose a technology, or weigh approaches
/doctor-loop                         when you want to dig up improvement candidates from the current state, without waiting for a change
/firstread-loop <the reader's task>  after finishing a document, when you want to check it gets through

/review-graph                        the same review, run by a machine (engine) that holds the board
/research-graph <what to look into>  the executable version of the same research
```

**Which to use**: the 4 above (prose) are the default. The 2 `-graph` commands are versions where a machine runs the same loop, and **the record of the run stays on disk** (it can resume across context compaction; dependencies and waves, limits, and silent omissions are enforced by the machine). Use `-graph` if you need any of these: getting a long run through, running the record through the validator afterwards, or several people following the same run. For an everyday check that ends in one pass, the 4 prose commands are enough.


`/review-loop` is for reviewing code changes, `/research-loop` for calibrating an assessment, and `/firstread-loop` for checking whether a document gets through to its readers. Do not use them the other way around.

## Role agents

The subagents the 4 loops start are launched with the 6 role definitions bundled in `agents/`. A role = a combination of model × effort × allowed tools; the instruction files write only the role name, never a model name (copies rot).

| Role | Job | Tools |
|---|---|---|
| `inspector` | cheap eye that reads the repository and grades | Read / Glob / Grep |
| `investigator` | cheap eye that searches as far as history, `gh`, and the web | + Bash / WebSearch / WebFetch |
| `cold-reader` | first-time reader cut off from context | **none** |
| `judge` | expensive eye that hands down verdicts that cannot be overturned | Read / Glob / Grep / WebSearch / WebFetch |
| `blind-judge` | expensive eye for independent derivation and cross-checking, cut off from the internals | **none** |
| `reader` | the reader role of `/firstread-loop` | Read / Glob / Grep |

No role has writing tools (Edit / Write). Only `investigator` has Bash, so the instruction file that starts it checks the working tree before and after — "do not rewrite" is not enforced by instruction alone. The 2 isolated roles are started with zero tools and read only the text pasted into the prompt — instead of telling them "do not read" and hoping they obey, they are made unable to read. How to change them is in `docs/customize.md`, 「役割 agent を変える」 (changing role agents).

## What happens when you run it

`/review-loop` runs one round as **P0** (fix the baseline and the "original purpose") → **P1** (gather material, start graders in parallel) → **P2** (diagnose, convert to root causes, and finalize labels) → **P3** (fix) → **P4** (re-grade and machine cross-check). When `[block]` reaches 0, it moves to the **P-R** convergence gate — R1 minimality / R2 zero-based re-derivation / R3 overall consistency / R4 unseen scope — and if even one is `redesign-needed`, it goes back to a new round.

Convergence means, for **2 consecutive rounds**, zero blockers, green CI, and neither a redesign request nor an unrun item in R1–R4 (for R1 / R2, a round where the condition for running them again does not apply carries over the earlier verdict, and that counts; the example record for round 3, [templates/round-3.example.json](templates/round-3.example.json), has that shape: R2 is `carried_over`) (the 2 consecutive rounds and the R1–R4 verdicts are counted from the record by `review-record.py`, not self-reported by the writer). If it does not get there, it stops as "did not converge" and hands the decision back to a human (round limit 5; it always stops beyond that). **Not cutting off silently** is the core of the design: the remaining issues accumulate in the question ledger, and when it stops they all reach the human together.

## Dependencies

**Required**: `git` / `python3` or `python` (**3.12 or later**. CI pins and measures one minimum version — a lower bound that is not measured is not declared. It used to say 3.9, but when the local python was newer, syntax that fails only on 3.9 slipped past an all-green run and turned CI red on all 3 OSes (measured 2026-09-13). `graphlib`, used by `graphcheck.py`, was added in 3.9, so that is not the reason for the lower bound; the reason is **that the developer's machine and CI read the same syntax**) / `bash`

**What the local review calls** (both `/review-loop` and `/review-graph`; which one calls what is in the Use column):

| Dependency | Use | When missing |
|---|---|---|
| `pr-review-toolkit` plugin | `/review-loop` uses the coordinator `review-pr`. `/review-graph` names the lenses one by one (the source of truth for the list is `p1.local_review.skills` in `graphloops/graphs/review-loop.json`; the machine requires one record row per declared entry) | the "Dependencies and how you obtain them" section above is the source of truth |
| built-in `/code-review` | local defect review (P1 of `/review-graph`; `/review-loop` stays on `review-pr`) | bundled with Claude Code itself. A plugin with the same name also exists, so in environments that have it installed the names can collide |
| built-in `/simplify` | local review for quality (reuse, simplification, efficiency) | bundled with Claude Code itself |
| built-in `/security-review` | when the change touches authentication, data handling, or external I/O | same as above |
| `gh` CLI | conflict check against concurrent PRs | on other hosts, substitute the equivalent command. If it cannot be substituted, the loop is made to report "could not check" |

**What `/research-loop` calls**: `WebSearch` / `WebFetch`, the `Workflow` tool (in environments where it is not available, the instructions include a procedure to reproduce the same structure by starting `Agent`s in parallel), and `python3` with the bundled `research-record.py` (validation of the run record — the source of truth for the required fields of the final report. In environments where it cannot be run, the instructions include a procedure to read the script body and check by eye)

**What `/firstread-loop` calls**: `python3` with the bundled `firstread-record.py` (validation of each round's record — its main purposes are **making it impossible to write "there was none" for material that was never asked about**, and confirming that answers written earlier actually exist as files)

**What `/doctor-loop` calls**: read-only instruments that already exist in the target repository (lint, type checks, tests, etc.; if there are none, they are reported as "instruments that could not be tried"), and `python3` with the bundled `doctor-record.py` (validation of the run record. The record is written **outside** the target repository's working tree — to stay compatible with the rule against changing it)

## What this design does not guarantee

- **The instructions are Japanese only**. Reports come back in the user's language, so using it is not a problem. Many places keep their discipline through the force of the command (「無言の省略を禁ずる」 "silent omission is forbidden", 「注記は最後の手段」 "an annotation is the last resort"), which a translation would loosen, so they are kept in Japanese
- **Some places assume GitHub** (the conflict check against concurrent PRs)
- **`comment-ratio.sh` can count only Python and languages with C-style comments**. `#`-style languages (Ruby, Shell) are out of scope — adding them would confidently output "0%" without picking up a single annotation line, so measure them separately by line count
- **The annotation count for C-style languages is approximate**. It does no lexical analysis, so if a string or template literal contains `/*`, every line up to `*/` is counted as annotation (over-counting). End-of-line comments are not counted (under-counting). The value is meant for comparison between rounds, and how these 2 biases act depends on the content of the input. Python is counted with `tokenize`, so it does not have this limitation
- **In environments that cannot reach `claude-plugins-official`, this whole plugin is unusable** (details and recovery steps in "Dependencies and how you obtain them" above)
- **It starts many subagents**. A few graders per round, and a few at the convergence gate. Not suited to light checks
- **Round limits** (5 for review-loop, 4 for research-loop). Beyond that it stops as "did not converge" and hands the decision back to a human. Not cutting off silently takes priority

## License

MIT.
