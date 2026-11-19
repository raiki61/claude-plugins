---
vars:
  prior: list   # earlier findings to check against: "<id> [<state>, <kind>] <finding> (at <where>)"
---
Decisions already made: these findings were raised before on this PR, settled, withdrawn, or raised by the person you work for:
{{prior|bullets}}
Also read the decision records, ADRs and ledgers of the folders this PR touches (among the rule documents in the shared rules). Name every change in this PR that undoes one of these decisions, and every place where a finding we might raise would undo one (for example asking the author to go back to a form the person already recommended and the author took). For each, cite the decision and where it was made.
