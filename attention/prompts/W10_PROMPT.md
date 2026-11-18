---
vars:
  prFiles: text
  quoted: flag   # true for a leaf or a smell answer (it has its own quotes), false for a fix option or a group
  text: text     # one of W10_LEAF, W10_SMELL, W10_FIX, W10_GROUP
---
{{prFiles}}

Try to refute the claim below. {{#if quoted}}First check whether the quotes really support the answer: is the claim actually supported by the quote, or is it an overreach or a misread? Then check the claim itself in the code and the sources.{{else}}It has no quotes of its own: check the content at the world-solution URL and whether the quotes of the leaves it rests on support it.{{/if}}
verdict: "stands" when you could not refute it, "falls" when it is wrong (give evidence), "unverifiable" when you cannot check it (say why in reason; it stays "unverified", not refuted).

{{text}}
