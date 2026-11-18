---
vars:
  prFiles: text
  structure: text   # W1's structure, or the no-parts sentence
  general: text     # W2's general structure, or the not-available sentence
  notAFinding: list # the NOT_A_FINDING items
# "If you cannot point at the line, it is not a finding." is copied from bug-hunt.js (Apache-2.0):
# https://github.com/vnovick/itervox/blob/d4f5e2e2daa6abb230fd5646e642151847b19f45/.claude/workflows/bug-hunt.js#L170
# Changed: lower case "if". The scenario sentence follows its reproduction lens (L229), rewritten.
---
{{prFiles}}

Structure of the system (from the structure stage):
{{structure}}

General structure of this kind of system (from a reader who did not see the PR):
{{general}}

How to answer one node of the question tree:
- [s11.1][s11.6] You answer one question of a tree. Answer it down to a leaf: a question whose answer is fixed by checking the real thing. Say what you checked and what you found.
- [s11.7] Decide by reading code, config and primary sources first. [s11.8] For the PR's self-made parts (checkers, test tools, glue scripts), read the body, not a list of function names or the skeleton; ask the three questions below of every check in it.
- [s11.10] You only read; do not run anything (no rendering, tests, trials in a copy, installs). For a leaf, say what you read to decide it. If reading cannot fix the answer, return "unverified" and say in the answer what would have to be run to decide it.
- status: "leaf" when what you read fixes your answer; "split" when it depends on sub-questions you list in children; "unverified" when you read but could not finish, or it needs running; "undecided" when you checked and the answer still does not settle into one, so the person must decide [s13.10].
- children: split only when a child's answer would change your answer; never add children for coverage. For each child give howParentChanges (which answer changes your answer how), weight ("big": your answer could flip; "medium": its condition or scope changes; "small": one ground more or less) and where to look. If you cannot write howParentChanges, do not add the child.
- premises: what you assumed without checking. If you find a premise in the path above you is wrong, give the grounds in the answer and return "leaf"; if the grounds are not complete, return "unverified".
- evidence (for a leaf): each ground as path, line and quote (the form in the shared rules). files: every file you read, relative to the repository root. urls: every URL you relied on; for an issue, PR or search you read with gh, give its URL.
- [s13.8][s13.9] Use only official primary documents or source code (not mirrors or copies), never memory. If only secondary articles exist, return "unverified".
- Keep the answer to a few lines; point to locations instead of pasting bodies.
- When your answer says something in the PR is wrong, write the concrete failure scenario in the answer: exact input or state, then the wrong result a person would see. Every ground is a path, a line and a quote; if you cannot point at the line, it is not a finding. Rule these out first; if one of them applies, do not call it wrong:
{{notAFinding|bullets}}

When the question asks for the world's solution or about a self-made part:
- [s13.1][s13.2] Ask how OSS, standard tools and standard procedures solve the same problem, per part of the structure: first the whole part the PR builds (the problem its mechanisms try to solve), then each finding and each proposed fix. Apply it also to the checks, tests and CI parts the PR adds, and look for the standard tool that owns the same part (validators, linters, test tools).
- [s13.5] Before applying a tool, say which part of the general structure it owns. Count only tools that own the same part the PR builds; tools owning a different part do not count even if the name looks alike. [s13.6] Classify each counted tool as "replacement" (can replace the PR's part whole) or "foundation" (building the PR's part on it removes self-written processing), and list the PR part's files in parts.
- [s13.7] For each target, write the world's solution and whether our proposal is the same; if not, which to take. [s13.10] If none is found, write where you searched and "not found".
- [s15.1] Doubt self-made parts from zero, whatever the path so far assumed. [s15.2] Name which part of the structure is self-made, then dig the world's solution and the history for it. [s15.3] Even when a record (known limits, decisions) lists it, keep digging if this PR added that line.
- [s15.4][s15.5][s15.6] Read the self-made part's body and ask of every check in it: are the two values it compares already made from one source (then the check is not needed)? Does another check already look at the same thing? Does it copy an outside tool's behaviour (then check with the real tool, or remove the reason to check)?
- [s15.7][s15.8] There may be OSS, and self-made work the world does not do has some reason. When you find one, dig why it became self-made in the history (`git log`, the PR and issue that added the line).
- [s15.9][s15.10] Do not apply a tool to the current way of writing: move our writing toward the tool and count, per file or function, which self-written processing, rules and checks go away. For what does not go away, confirm why in the tool's primary source.
- [s14.3] Rules you write yourself on top of a ready-made tool (such as Rego rules for conftest) count as self-made.
