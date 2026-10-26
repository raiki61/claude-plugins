# tiers

A Claude Code plugin that checks whether the external tools a plugin needs (Claude Code, gh, herdr, Archon, and so on: tools you install on the PC separately from the plugin) are in place, and prints what is missing and how to install it. The check installs nothing.

It also ships an opt-in status line (see "Status line" below) that shows 「⧖ バックグラウンド作業中 N 本」 ("background work running: N") while a session waits for its background work, and makes herdr show that session as working.

tiers adds nothing to the context of every session: the skill is for people only (`disable-model-invocation`), and the hook and the status line print nothing into the conversation. (`claude plugin details` still shows an estimate of about 30 tokens, because the estimate ignores `disable-model-invocation`. To see what is really loaded, look for `tiers:check` in the `skill_listing` rows of a session transcript under `<config>/projects/`.)

The skill's and command's instructions and descriptions are written in Japanese.

## What it does

- Checks the required tools grouped into tiers (see "Tiers" below). Give it one tier and it checks every tool up to that tier.
- For each missing tool, prints install steps for the OS (macOS, Linux, Windows), only for the OS it is running on. The install steps were copied from each tool's official README. It only prints them; a person installs by hand.
- People run it with `/tiers:check`. Claude itself cannot start this skill (so its description is not loaded into every session); inside a session, Claude runs `tiers --tier N` with the Bash tool instead. Other plugins install tiers as a dependency and call the same check when they start (currently connected: works-dispatch, a plugin in the same repository that starts a separate Claude Code session for each task and hands it the work).

## Requirements

- **Required tier (要る段): 0** (Claude Code only).
- Python 3.8 or later (3.11 or later for the statusline). `bin/tiers` runs with the first of `python3`, `python`, `py -3` that starts and is new enough, in that order. On Windows, if typing `python3` or `python` opens the Microsoft Store (the stand-in that appears when Python is not installed), install Python, then go to Settings → Apps → App execution aliases and turn off the "App Installer" entries for `python.exe` and `python3.exe`.

## Try it in 5 minutes

1. Install the plugin. If you installed works-dispatch, it is already installed as a dependency.

   ```bash
   claude plugin marketplace add raiki61/claude-plugins
   claude plugin install tiers@raiki61
   ```

2. In a Claude Code session, type the check. (`段 2` means "tier 2".)

   ```
   /tiers:check 段 2
   ```

3. Read the result. When everything is in place, the output looks like the following (the output is in Japanese: 「要るツールの点検（段 0〜2）」 means "check of required tools (tiers 0-2)", and 「結果: 足りない物は無い」 means "result: nothing is missing"). If something is missing, that line gets install steps (by hand). After installing, run the same check again. On a fresh setup the 「フィードバックの下書き」 ("feedback drafts") and 「選択肢の画面で問うツール」 ("the tool that asks with a choice prompt") lines are usually missing at first; see "Account settings" below.

   ```
   要るツールの点検（段 0〜2）
    ok  段 0 Claude Code: 2.1.301 (Claude Code)
 ok  段 0 Claude Code のログイン: ログイン済み（oauth_token）
    ok  段 1 gh: gh version 2.102.0 (2026-09-30)
    ok  段 1 gh のログイン: gh auth status が通る
    ok  段 2 herdr: herdr 0.9.3
    ok  段 2 herdr の動き: herdr の server が動いている
    ok  段 2 起動コマンド claude: claude がシェルで見つかる
    ok  段 2 フィードバックの下書き（/home/you/.claude）: feedbackDrafts が off（/home/you/.claude/settings.json。claude が起動するアカウント）
    ok  段 2 選択肢の画面で問うツール（/home/you/.claude）: permissions.deny に AskUserQuestion が在る（/home/you/.claude/settings.json。claude が起動するアカウント）
   結果: 足りない物は無い
   ```

## Tiers

A higher-numbered tier includes the lower ones (checking tier 2 also checks tier 0 and tier 1). If the calling plugin has a way of use that does not need tier 1's gh, that check leaves it out on its own side (example: works-dispatch's `--check` only adds a note about missing gh for people who use only its departments, the separate per-task Claude Code sessions it starts, and not its PR features).

- Tier 0: Claude Code only. Whether `claude --version` succeeds and Claude Code is logged in (`loggedIn` in the JSON from `claude auth status --json`, run in the user's login shell so that a token the shell sets is seen).
- Tier 1: gh (the GitHub CLI). Whether it is installed (`gh --version`) and logged in (`gh auth status`).
- Tier 2: herdr (a tool that splits the terminal into one workspace per task and lets you operate the AI sessions inside from outside). Whether it is installed (`herdr --version`) and its server is running (`running` in the JSON from `herdr status server --json`). Also, whether the command that starts each account (passed with the `--launcher` option of `tiers`, described under the usage below; `claude` if omitted) can be found in the user's login shell and whether that account is logged in (the same `auth status --json`, for each launcher other than `claude`) (on Linux and macOS it is looked up with `command -v` in the login shell, which also counts shell functions and aliases; on Windows it is looked up on PATH, and if not found, functions (and aliases) defined in `$PROFILE`, the file PowerShell reads at startup, are looked up with PowerShell's `Get-Command`). Also, for each launcher that is found and logged in, whether that account's `settings.json` has `"feedbackDrafts": "off"` and `"AskUserQuestion"` in `permissions.deny` (see "Account settings" below; each is its own line in the result). The account's settings folder is read from `configDirectory` in the JSON of that launcher's `auth status --json` (the login check above); if that field is missing, this check is reported as missing for that launcher unless at least one `--config-dir` is given (then the folders given are checked instead), and the fix is to update Claude Code or pass the folder with `--config-dir`.
- Tier 3: Archon (a tool that runs AI workflows step by step). Whether `archon` is on PATH.

For each missing tool, it returns install steps. The install commands were copied from the install section of each tool's official README (read on 2026-10-16; per OS: macOS, Linux, Windows). For tier 2, so that a first-time user can set things up alone, it also returns guidance (`guide`: supplements to herdr's per-OS install steps, how to install the herdr–Claude Code integration, and how to create the start commands) in addition to the install commands. The content of the guidance and its sources are in the "段 2 の案内" (tier 2 guidance) section of [docs/design.md](docs/design.md).

## Usage

`tiers` is in this plugin's `bin/`. Inside a Claude Code session (the Bash tool), Claude Code puts `bin/` on PATH, so you can run it by name.

```bash
tiers --tier <0〜3> [--launcher <コマンド> ...] [--config-dir <フォルダ> ...] [--json]
```

- `--tier` picks how far to check; the tiers (0 = Claude Code, 1 = gh, 2 = herdr and the commands that start each account (see `--launcher` below), 3 = Archon) are listed under "Tiers" above.
- `--launcher` is only looked at for tier 2 and above (passing it with tier 0 or 1 is not an error; it is ignored). It can be given any number of times (`--launcher claude-p1 --launcher claude-p2`). Every command passed is looked up, and if even one is not found, it counts as missing.
- `--config-dir` is the Claude Code settings folder of one account (the folder you set as `CLAUDE_CONFIG_DIR`, such as `~/.claude-p2`). It can be given any number of times. Without `--config-dir`, none of the checks below run for that folder (the account settings check still runs for the folders found from the launchers). For each folder given:
  - Tier 0 checks every entry in `plugins/installed_plugins.json` (Claude Code's record of installed plugins). Each entry's folder (`installPath`) must still exist and must not carry the old-version mark `.orphaned_at` (Claude Code removes a folder with this mark after 14 days). An entry that fails is reported as missing, with the `claude plugin uninstall` command that removes it. Such entries are typically project-scope ones (installed for one project only), and while they remain it is unclear which entry takes effect.
  - Tier 2 (only when `--tier 2` or higher) checks that herdr's Claude Code integration is current for that folder. It runs `herdr integration status` with `CLAUDE_CONFIG_DIR` set to the folder and reads the `claude` line (herdr 0.9.3 prints `claude: current (v10) (<path>)`; the states are current, outdated, not installed, and unknown). herdr 0.9.3 has no JSON output for this, so a line in an unknown shape or state is reported as missing instead of passed.
  - Tier 2 also checks the status line (see "Status line" below) for each folder whose `statusLine` points to tiers: that the `current` link exists (a link in the plugin's data folder that points to the installed version of tiers; `statusLine` runs the script through it) and that herdr's local override (`~/.config/herdr/agent-detection/claude.toml`, a file that replaces herdr's rules for reading a Claude Code session's state) is the one tiers builds from the rules herdr downloaded most recently. A folder that does not use it is reported as fine, with the setup command.
  - Tier 2 also checks `"feedbackDrafts": "off"` and `"AskUserQuestion"` in `permissions.deny` in the folder's `settings.json` (see "Account settings" below). A folder that a launcher already resolves to is checked once.
  - A folder that does not exist is reported as missing (once, by the tier 0 check).
- Exit codes: 0 = everything is in place, 1 = something is missing, 2 = wrong usage.
- The `--json` format (`schema` is the format's version number, currently 1; it is raised only for changes that would break callers) is described at the top of [`lib/tiers_check.py`](lib/tiers_check.py). Missing tools are the `checks[]` items with `ok: false`, and they carry `problem` (why it is missing), `fix` (a list of install-step lines), and `guide` (a list of guidance lines; an empty list `[]` if none). Every item carries `tier` (the tier), `name` (the tool's name), `ok`, and `found` (what was found; `null` for missing items). The human-readable output prints the same `guide` lines under 「案内:」 ("guidance:").

## Status line

An opt-in Claude Code status line (`statusline/statusline.sh`). It prints the model and usage lines. Inside herdr (a terminal workspace manager that shows the state of the AI sessions in its panes), it also prints 「⧖ バックグラウンド作業中 N 本」 while the session has background work that will end (`run_in_background` Bash, Monitor, and background subagents). A watcher that never ends is not counted if its command line contains the text `herdr:ignore`. When a session ends its turn and waits for that work, herdr would otherwise show it as done. A herdr detection rule (`statusline/claude-rule.toml`) makes herdr show it as working instead. Inside herdr it also sends the pane's sidebar tokens (branch, open PR via `gh pr list`, context and usage) with `herdr pane report-metadata`, and keeps the account's usage in `~/.cache/claude-limits/<account>.json`. macOS and Linux only; it needs bash, `ps`, `jq`, and Python 3.11 or later (`setup` and `refresh` read TOML with `tomllib`).

Set it up per account (the folder you set as `CLAUDE_CONFIG_DIR`; without `--config-dir`, `CLAUDE_CONFIG_DIR` or `~/.claude`). Before setup, tiers must be installed at user scope in that account, and herdr must have run once so that its downloaded rules (`~/.local/state/herdr/agent-detection/remote/claude.toml`) exist; otherwise setup says what to do and exits with 1. The new `statusLine` takes effect in sessions started after setup. Inside a Claude Code session `tiers-statusline` is on PATH like `tiers`; from a terminal, run it from the plugin folder (`<config>/plugins/cache/raiki61/tiers/<version>/bin/tiers-statusline`).

```bash
tiers-statusline setup --config-dir ~/.claude --config-dir ~/.claude-p2
```

- It writes `statusLine` into each account's `settings.json` (a plugin cannot set `statusLine` itself: in a plugin's `settings.json` only `agent` and `subagentStatusLine` take effect, per the [plugins reference](https://code.claude.com/docs/en/plugins-reference)). The old file is kept next to it as `settings.json.bak.<date>-tiers`. Other `statusLine` keys (such as `padding`) are kept; `refreshInterval` defaults to 30 seconds.
- `statusLine` points to `<config>/plugins/data/tiers-raiki61/current/statusline/statusline.sh`. The `current` link is pointed at the installed version by the plugin's `SessionStart` hook at every session start, so plugin updates need no new setup. If the link is missing but `statusLine` already points to it (for example, a `settings.json` copied into a new config folder with the path changed), the hook creates the link; it does nothing for a folder whose `statusLine` points elsewhere.
- It builds herdr's local override `~/.config/herdr/agent-detection/claude.toml` as herdr's downloaded rules plus `claude-rule.toml`, and runs `herdr server reload-agent-manifests`. A local override replaces herdr's rules as a whole and always wins ([herdr agents docs](https://raw.githubusercontent.com/herdrdev/herdr/v0.9.5/docs/next/website/src/content/docs/agents.mdx)), so a hand-copied override goes stale when herdr updates its rules. The status line therefore runs `tiers-statusline refresh` in the background whenever herdr's downloaded rules or the rule file are newer than the override. An override not written by tiers is replaced only by `setup` (and kept as `.bak`); `refresh` leaves it alone.
- `tiers --tier 2 --config-dir <folder>` checks this for each account whose `statusLine` points to tiers.
- To undo: copy `settings.json.bak.<date>-tiers` back to `settings.json` (or put your own `statusLine` back), delete `~/.config/herdr/agent-detection/claude.toml` (or restore its `.bak.<date>-tiers`), and run `herdr server reload-agent-manifests`. The `current` link under `plugins/data/tiers-raiki61/` can stay; the hook only re-points a link that exists (it creates one only while `statusLine` points to it), and nothing else reads it.

## Account settings

Tier 2 checks two keys in each account's `settings.json`. Without either one, a session can stop at a prompt on its screen, and a tool that drives sessions from outside (works-dispatch) cannot get past it. The check reads only the account's `settings.json`, not managed settings (the settings an administrator deploys).

### Feedback drafts

Claude Code's SendFeedback tool lets Claude draft a feedback report and queue it on your machine. When a session has a queued draft, `/exit` first asks whether to review or discard it, so a tool that closes sessions with `/exit` from outside gets stuck. Setting `feedbackDrafts` to `"off"` makes Claude Code remove the SendFeedback tool, so no drafts are queued ([tools reference, "SendFeedback tool behavior"](https://code.claude.com/docs/en/tools-reference); [settings reference, `feedbackDrafts`](https://code.claude.com/docs/en/settings-reference)). The setting's scope is user or managed, so it goes in each account's `settings.json`; a value in managed settings takes precedence over the one in `settings.json`. `CLAUDE_CODE_SEND_FEEDBACK=0` works for one session only, and `DISABLE_FEEDBACK_COMMAND=1` also turns off `/feedback` typed by people, so tiers uses neither.

Instead of `tiers-settings`, you can turn **Claude-drafted feedback** off in `/config` in that account. Whether `/exit` still asks about drafts queued before the setting was turned off is not stated in the official docs.

### Choice prompts

Claude Code's AskUserQuestion tool lets Claude ask a multiple-choice question on the session's screen. The question stays open until someone answers it there, so a session that works-dispatch opened waits until a person opens its window and presses a key; another session cannot answer it (2026-10-23, in the author's workplace repository). A deny rule with the bare tool name, `"AskUserQuestion"` in `permissions.deny`, keeps Claude from using the tool ([tools reference](https://code.claude.com/docs/en/tools-reference): tool names are the strings used in permission rules, and tools without a rule format accept only the bare name). Claude then asks in plain text, which a person or another session can answer by typing. Deny lists from different settings files are combined, not replaced ([settings, "Lists merge instead of overriding"](https://code.claude.com/docs/en/settings)). `askUserQuestionTimeout` is not used, because its timer never starts in a background session (the same tools reference, "Question auto-continue timeout"). This also applies to sessions you start by hand in that account: Claude asks in text there too.

### Writing them

`tiers --tier 2` checks both (the check writes nothing). To write them, run the command below with one `--config-dir` per account, each naming that account's settings folder (the folder you set as `CLAUDE_CONFIG_DIR`). If you omit `--config-dir`, it writes to the folder in `CLAUDE_CONFIG_DIR`, or to `~/.claude` if that is not set. It sets `"feedbackDrafts": "off"`, appends `"AskUserQuestion"` to the end of `permissions.deny` (creating `permissions` or `deny` if missing), and keeps every other key and entry; the old file is kept next to it as `settings.json.bak.<date>-tiers`. An empty or missing `settings.json` is treated as `{}`. A folder that does not exist, a `settings.json` that is not a JSON object, or a `permissions` that is not an object (or a `deny` that is not a list) is left alone and reported (exit code 1). It takes effect in sessions started afterwards. Like `tiers-statusline`, `tiers-settings` is on PATH inside a Claude Code session; from a terminal, run it from the plugin folder (`<config>/plugins/cache/raiki61/tiers/<version>/bin/tiers-settings`). On Windows, that file cannot be started directly from PowerShell or cmd; run it with Python instead (`python <config>\plugins\cache\raiki61\tiers\<version>\bin\tiers-settings setup ...`).

```bash
tiers-settings setup --config-dir ~/.claude --config-dir ~/.claude-p2
```

## More detail

- [docs/design.md](docs/design.md): decisions (why it installs nothing, why it is a shared plugin) and what was tested and confirmed.
- [docs/from-other-plugins.md](docs/from-other-plugins.md): how to connect tiers from other plugins. For plugin authors.
- [CHANGELOG.md](CHANGELOG.md): change log.
- Tests: from the repository root, `python3 -B -m unittest discover -s tiers/tests`. They do not start external tools; the probe interface (`Probe`) is replaced with a fake. They are also part of the full test run (`tests/run.sh`).
