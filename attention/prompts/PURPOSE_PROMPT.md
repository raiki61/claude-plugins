---
vars:
  prFiles: text
  lenses: text     # the lens texts the script picked for this stage (LENS_TABLE.Purpose)
  leaked: list     # words of the means found in purpose or kind on the first ask; empty on the first ask
---
{{prFiles}}

Read the PR conversation first, then the justifications file named in the shared rules, then the diff file.

{{lenses}}

1. purpose: In one sentence, what this PR is for, with every means taken out: the outcome a person wants, not how this PR gets it. Take it from the PR body and the issue it closes before reading the diff.
2. means: Each means this PR chose, one item each, copied as the PR words it (a tool, a mechanism, a file layout, a check, a name scheme). Copy the words; do not reword them.
3. kind [s6.7]: In one sentence, what kind of system this is and what the touched parts want to keep consistent there. Free text, no fixed category. [s7.6] Use no word from this repository and no word that names this PR's choice; the sentence goes to a reader who must not see the PR. No word of the means above may appear in purpose or in kind.
4. claims: Every reason the PR gives and every "cannot", "not needed" or "already handled" it asserts (in the body, the comments, the commit messages, code comments and records it adds), one item each: the claim as written and where it is (a path and line, or the comment's URL).
{{#if leaked}}

On the first ask these words of the means appeared in purpose or kind: {{leaked|join:", "}}. Rewrite purpose and kind without them; keep means and claims as they were unless they were wrong.
{{/if}}
