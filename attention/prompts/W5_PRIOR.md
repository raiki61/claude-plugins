---
vars:
  received: flag   # true for a review comment the author received, false for an earlier finding
  state: text
  finding: text
  at: text         # where it is; empty when not known
---
{{#if received}}Review comment the author received{{else}}Earlier finding{{/if}} ({{state}}): {{finding}}{{#if at}} (at {{at}}){{/if}}. Where does it stand now in this PR, and what is left?
