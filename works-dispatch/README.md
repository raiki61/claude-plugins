# works-dispatch

A Claude Code plugin that starts a separate Claude Code session for each task, hands it the work, and has it return a summary to the session that asked when it is done. It can also open the PRs where it is your turn, each in its own workspace, and have a session read them.

It is for people who run several Claude Code sessions in parallel on one repository. The main prerequisites are herdr (runs one terminal workspace per task), Python 3.11 or later and git, and, only for opening PRs, a gh login and the attention plugin; several Claude Code accounts are optional (see "Pick an account" below).

The skill's and command's instructions and descriptions are written in Japanese.

This README uses the following terms (the Japanese word used in the skill and in the program's output is in parentheses).

- **Front desk** (窓口): the Claude Code session that talks with the person and hands out work. It is used for a long time.
- **Department** (部署): the side that does the requested work. A pair of a workspace for one git branch (a worktree) and one Claude Code session working in it. One is set up per task and cleaned up when it is done.
- **Company** (会社): the repository that departments are set up from.
- **Delivery** (納品): a department returning a summary with fixed headings to the front desk.

## What it does

- **Ask and have it deliver**: from the front desk, set up a department and give it a request (`--ask`). When it is done, the department returns a summary to the front desk (`--deliver`). If a department's session tries to stop without delivering, it is sent back up to 3 times.
- **Open the PRs where it is your turn**: opens each PR where it is your turn (your own PRs where it is your turn to fix, and PRs where it is your turn to review) in its own workspace and has the session read what has happened since last time. The list of these PRs comes from `/whose-turn`, and the catch-up comes from `/catchup`; both are commands of the attention plugin, another plugin in this repository. When someone else on the PR posts a new reply, that PR's workspace is opened again, and the workspaces of closed PRs are cleaned up. It can also open work that starts from an issue (`--issue`).
- **Pick an account**: if you use several Claude Code accounts, it starts the session on an account with spare usage.
- **Overview and cleanup**: lists the departments for each company (`--tree`). Lists the open requests as a tree, like a personal to-do list, rebuilt each time from the request ledger (the log of requests and deliveries) of the company you run it in and of every other company (repository) that a row names, for example as the sender or the receiver of a request (`--todo`; see [docs/ledger.md](docs/ledger.md)). Removes finished departments (`--clean`). Merges a department's branch into the mainline following the rules (`--land`; see [docs/land.md](docs/land.md)). Before merging, it checks whether the branch deletes lines that another department merged first, and stops if it does.

dispatch itself does not use AI. It is a script that uses only the Python standard library; only the sessions it starts use AI.

## Requirements

- **Required tier (要る段): 2** (the tiers of [tiers](../tiers/README.md)). herdr (a tool that splits the terminal into one workspace per task and lets you operate the Claude Code sessions inside from outside; [herdr.dev](https://herdr.dev)) is running. A gh (the GitHub CLI) login is needed only for opening PRs, and for companies that use a PR or CI to merge into the mainline (setting up departments, asking them, and having them deliver does not read GitHub; `[[repos]]` in the dispatch settings file lists the repositories whose PRs it opens; when the file has no `[[repos]]` entries, a missing gh is not an error and `--check` only adds a note about it).
- Python 3.11 or later, and git. The hooks pick the first of `python3`, `python`, `py -3` (in that order) that actually starts and is 3.11 or later (they do not pick the 3.9 that ships with macOS). On Windows, if typing `python3` or `python` opens the Microsoft Store (the stand-in that appears when Python is not installed), install Python, then go to Settings → Apps → App execution aliases and turn off the "App Installer" entries for `python.exe` and `python3.exe`.
- One clone of the repository you want to try it on, with the default branch (main or similar) checked out. Department workspaces are created from this clone. origin does not have to be GitHub (a local bare repository works too). The name of the mainline branch is taken from the clone's local `origin/HEAD`, and if that is missing, origin is asked (if neither decides it, for example right after cloning an empty bare repository, push the mainline branch and then run `git remote set-head origin --auto`).
- Only for opening PRs: the attention plugin (which has the `/catchup` command) and a dispatch settings file (`--init` writes a draft; the steps are in the 「初めて」 ("first time") section of [references/setup.md](skills/dispatch/references/setup.md)).

The reason for each requirement, and what `--check` verifies, are in [docs/prerequisites.md](docs/prerequisites.md).

## Try it in 5 minutes

From setting up one department and asking it something, until the summary comes back to the front desk.

1. Install the plugin. The tiers dependency is installed with it.

   ```bash
   claude plugin marketplace add raiki61/claude-plugins
   claude plugin install works-dispatch@raiki61
   ```

2. Start herdr (the tool that splits the terminal into one workspace per task, listed under "Required tier" above). Inside it, open the folder of the clone you are trying it on, and start the front desk session with a name (`窓口` means "front desk"). If the folder is new to Claude Code, answer the trust prompt.

   ```bash
   claude --name 窓口
   ```

3. Have the front desk check that the tools are in place. If something is missing, install it with the printed steps and run it again. If you only use departments, a gh login is not needed, so `--check` does not stop on missing gh and only adds a note (`/tiers:check 段 2`, which checks tier 2, counts a missing gh login as missing, as the tier rules say).

   ```
   /works-dispatch:dispatch --check
   ```

4. (Optional) Have it write a draft of the company shape. The company shape is a file (`.claude/company.toml` in the company's repository) that holds the company's name, its roles (the rules for a department's work), and how to merge into the mainline. You can try it without one (the role becomes the default `作業` ("work"), and the delivery headings become the defaults in step 6 below). With `--local`, it writes to `~/.config/works-dispatch/companies/` instead of inside the repository, so the repository you are trying it on does not change. If you only use departments, the dispatch settings file (`~/.config/works-dispatch/dispatch.toml`) is not needed.

   ```
   /works-dispatch:dispatch --init-company --local
   ```

5. Ask from the front desk. Pass the department's name (`--task`) and a new branch for the department to use (`--branch`). (The request text below means "Read README.md and list 3 places where a first-time reader is likely to get stuck"; `試し` means "trial".)

   ```
   /works-dispatch:dispatch --ask 作業 --text "README.md を読んで、初めての人が詰まりそうな所を 3 つ挙げて" --task 試し --branch try/first
   ```

   In herdr, the workspace and the screen (a pane showing the department's session) for the department 「試し」 open, and the department's session receives the request and starts working. The front desk does not have to wait and can go on to other work.

6. When it is done, the department writes its summary under the headings 「結論・決め手・残った疑問・枝」 ("conclusion, deciding reason, remaining questions, branch") and returns it. One line, `納品です（受付 …、試し・枝 try/first から）: 【結論】…` ("Delivery (request …, from 試し, branch try/first): [conclusion] …"), is typed into the front desk's screen. The full text stays in the clone's `.git/company/inbox/`.

7. Clean up the department. `--clean` lists the departments that can be removed, and `--clean --apply` removes them. Departments whose session is still running are listed as 「残す」 ("keep") with the reason (the conditions for removal are in the `--clean` item of [references/clean.md](skills/dispatch/references/clean.md)).

   A one-off department is a department set up for a single request. After it has delivered and finished merging into the mainline, the department's session itself can run `--done` (the command that sets the "finished" mark). Then the session stops at the end of that turn (one response of the session), and the department's room (the workspace, worktree, session, and local branch) is cleaned up under the same rules as `--clean`. To stop and fold up a department's room that has no "finished" mark, use `--retire <部署>`, where `<部署>` is the department.

   The dispatch settings file is not needed for this (pass the path of the main clone to `--repo`, or run it from inside that clone).

   ```
   /works-dispatch:dispatch --clean
   ```

Other uses (opening the PRs where it is your turn [your own PRs where it is your turn to fix, and PRs where it is your turn to review], how to write accounts, per-role settings, herdr's appearance) are in [SKILL.md](skills/dispatch/SKILL.md) and the separate files it points to by topic (`skills/dispatch/references/`).

## More detail

- [docs/prerequisites.md](docs/prerequisites.md): the requirements and why each is needed.
- [docs/land.md](docs/land.md): the rules for merging a department's work into the mainline (`--land` and the company shape's `[land]`).
- [docs/internals.md](docs/internals.md): the internal structure (nodes, interfaces to the outside, guards D1–D8, tests). For people who modify it.
- [docs/observed.md](docs/observed.md): a record of how herdr, Claude Code, and others behave, tested and confirmed by hand.
- [CHANGELOG.md](CHANGELOG.md): change log.
