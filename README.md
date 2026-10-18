# claude-plugins

[![test](https://github.com/raiki61/claude-plugins/actions/workflows/test.yml/badge.svg)](https://github.com/raiki61/claude-plugins/actions/workflows/test.yml)

A marketplace of Claude Code plugins (marketplace name: `raiki61`). It includes tools that repeat a review or a research task until a fresh reviewer stops finding new problems, checks that run before you post to GitHub, an overview of the tasks you run in parallel, and a tool that opens a Claude Code session for each task and has it report back.

## Language

This README and each plugin's README are in English. Everything else in the repository is written in Japanese: the names, descriptions, and instructions of the skills and commands, [CONTRIBUTING.md](CONTRIBUTING.md), and the design records under `docs/`. The plugins are written for Japanese-speaking users.

## Plugins

This marketplace ships 8 plugins. Install only the ones you need. If you are not sure where to start, try convergence-loops: besides Claude Code it needs only git, Python 3.12 or later, and bash (no tool from the [tool tiers](#tool-tiers) below), and `/review-loop` reviews and fixes your latest code change.

| Plugin | What it does | Docs |
|---|---|---|
| **convergence-loops** | Repeats a review, research, diagnosis, or first-read check of a document, each round with a fresh reviewer, until no new problems turn up | [README](convergence-loops/README.md) |
| **gates** | Hooks that block a GitHub post until a reader with no context (an AI subagent) can follow it, and report on documents you write | [README](gates/README.md) |
| **attention** | Shows which of your open pull requests and issues is waiting for you, and where you left off | [README](attention/README.md) |
| **graphloops** | The review and research of convergence-loops, with a program instead of the conversation driving the steps | [README](graphloops/README.md) |
| **works** | Sends a fix request for your repository to darkfactory, a multi-step AI workflow that runs on Archon | [README](works/README.md) |
| **works-factory** | Sends a fix request to the factory in [raiki61/works-factory](https://github.com/raiki61/works-factory) | [SKILL.md](works-factory/skills/works-factory/SKILL.md) |
| **works-dispatch** | Opens a Claude Code session in its own workspace for each task, hands it the request, and has it return a summary | [README](works-dispatch/README.md) |
| **tiers** | Checks that the external tools a plugin needs are in place | [README](tiers/README.md) |

## Install

Inside Claude Code, add the marketplace, then install the plugins you need.

```
/plugin marketplace add raiki61/claude-plugins
/plugin install convergence-loops@raiki61
```

From a terminal, these two lines do the same.

```bash
claude plugin marketplace add raiki61/claude-plugins
claude plugin install convergence-loops@raiki61
```

`@raiki61` is the marketplace name. Installing a plugin that depends on other plugins installs those too (for example, installing works-dispatch also installs tiers). To move to a newer version, run `claude plugin marketplace update raiki61`, then `claude plugin update <plugin>@raiki61`, and restart Claude Code.

## Tool tiers

Some plugins need external tools besides Claude Code. The tools are grouped into 4 tiers. Each tier also needs the tools of the tiers below it.

- Tier 0: Claude Code only.
- Tier 1: gh (the GitHub CLI), installed and logged in.
- Tier 2: [herdr](https://herdr.dev), installed and running. herdr splits the terminal into one workspace per task and lets a program type into the Claude Code session in each one. If you start Claude Code for different accounts with different commands, each of those commands must also be found by your shell.
- Tier 3: Archon, a tool that runs a workflow of AI steps in order.

A plugin's README lists what it needs under the heading 「要る物」 ("Requirements"). Of these, works-dispatch needs tier 2 and works needs Archon. To check whether the tools are in place, install tiers and run `/tiers:check` inside Claude Code. It only reports what is missing and how to install it; it installs nothing.

## Contributing

How to run the tests and the repository's rules are in [CONTRIBUTING.md](CONTRIBUTING.md) (Japanese). License: MIT ([LICENSE](LICENSE)).
