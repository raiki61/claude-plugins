---
vars:
  kind: text      # the purpose stage's one sentence on the kind of system
  purpose: text   # the purpose stage's one sentence on what the change is for, means taken out
  hidden: list    # W1's hidden-choice questions; empty on the first ask
  noTools: flag   # true when W2 runs on the default agent instead of a blind judge
  lenses: text    # the lens texts the script picked for this stage (LENS_TABLE.W2)
---
{{lenses}}

[s7.1][s7.2][s7.3][s7.4] In general, how is this kind of system divided into parts, what flows between the parts, where is the source of truth kept, which way do the dependencies point, and where are the boundaries drawn? Give each together with the reason it is placed that way. Describe structure, not solutions or tools.

Kind of system: {{kind}}
{{#if hidden}}

[s8.2] Also answer these questions about such a system, each with the reason:
{{hidden|bullets}}
{{/if}}

If you cannot say anything beyond statements that would fit any system, set notFound to true and say so in general.

Then design from zero. Purpose: {{purpose}}
First doubt whether the question holds: is something to be built at all for this purpose? Set questionStands and say why in whyQuestion. If it holds, list in design the elements you would build from this purpose alone (D1, D2, ... in id), each with what it adds and what it removes or makes unnecessary. If it does not hold, leave design empty.{{#if noTools}}

Do not use any tool. Think only from what is given here.{{/if}}
