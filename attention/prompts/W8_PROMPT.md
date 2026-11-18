---
vars:
  prFiles: text
  structure: text
  mechanisms: list      # "<mechanism> (premise: <premise>)"
  selfMade: list        # "<part> [<files>]"
  smells: list          # "(<n>) <verdict>: <first line of the answer>", or "(<n>) not returned"
  tree: list            # one line per node: "- <id> [<status>] <first line of the question> => <first line of the answer>"
  unreadChanged: list
  unread: list
  round: text
  oddRound: flag        # true in rounds 1, 3, 5 ...
---
{{prFiles}}

Structure, mechanisms and self-made parts (from the structure stage):
{{structure}}
Mechanisms: {{mechanisms|join:"; "|or:"(none)"}}
Self-made: {{selfMade|join:"; "|or:"(none)"}}

Code-smell answers: {{smells|join:" "}}

The question tree so far (id [status] question => answer):
{{tree|join:"\n"}}

Changed files no node and no smell answer read: {{unreadChanged|join:", "|or:"(none)"}}
Not read in the conversation's steps: {{unread|join:", "|or:"(none)"}}

Round {{round}}. What is missing from this tree? {{#if oddRound}}This round, look first at the parts, mechanisms, premises and self-made parts of the structure that no node asked about.{{else}}This round, look first at the changed files nobody read and at the "unverified" nodes that reading something else would decide.{{/if}}
Return each gap as a question with why (which part or file is missing) and where. If nothing is missing, return no gaps and say in reason what you compared the tree against.
