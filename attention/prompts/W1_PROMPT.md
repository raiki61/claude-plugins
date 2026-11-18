---
vars:
  prFiles: text         # the PR_FILES text
  extraSmells: text     # how many extra smell questions at most
  smellQuestions: list  # the fixed smell questions, each already numbered as "(1) ..."
---
{{prFiles}}

Read the whole diff file and the code around it.

1. structure [s6.1][s6.2]: Describe the system that contains what the PR touches, without this repository's own words: its parts, what flows between parts (values, facts, calls), which part is the source of truth and which only reads, the direction of dependencies, and the boundaries. Show where in it the parts the PR touches sit. [s6.3] For a documents-only PR, first decide whether to draw the mechanism the documents explain or where the documents live (who reads them, which is the source of truth). [s6.4] Do not write this PR's solution (the mechanism it builds, its checks, how it composes names). [s6.5] But do draw the checks, tests and CI mechanisms this PR adds as parts, together with what they watch.
2. kind [s6.7]: In one sentence, what kind of system this is and what the touched parts want to keep consistent there. Free text, no fixed category. [s7.6] Use no word from this repository and no word that names this PR's choice; the sentence goes to a reader who must not see the PR.
3. mechanisms [s10.1][s10.2][s10.3]: Each mechanism this PR builds in one sentence, and the premise it compensates for (what breaks without it: human hands, an agreement kept elsewhere, an outside tool's behaviour), in the form "builds X; it is needed because Y does not have Z". Include every check and test mechanism the PR adds.
4. selfMade (entry of step 15) [s6.6]: The self-made parts (built by hand where a standard from the world would do). Use the --stat of the diff file to see where the added lines gather; if many are in places that are not the main purpose (checks, tests, glue), list those first. Hand-made lists (numbers, types, special-case tables) count as self-made. Give the files as a comma-separated list.
5. extraSmells: Up to {{extraSmells}} code-smell or risk questions that the five fixed smell questions below cannot catch for this PR, each with one line on why none of the five catches it. Empty is fine.
   Fixed questions: {{smellQuestions|join:" "}}
6. hiddenChoices [s8.2]: Questions about where this PR's structure makes a choice, with the chosen answer hidden (for example "Which side holds the source of truth?", "Where is the boundary drawn?"). They are asked only if the general structure turns out too generic to compare. No word from this repository.
7. noParts [s6.8]: true when no parts can be named (a version number bump only and the like); then give noPartsReason, and structure, kind and mechanisms may be empty.
