---
vars:
  prFiles: text
  group: flag         # true for a group of findings and fixes, false for one fix option
  lenses: text        # LENS_TABLE.W10fixes
  text: text          # the fix option or the group, with the findings it rests on
---
{{prFiles}}

{{lenses}}

{{#if group}}
Judge each member of the group below one by one: "accept" when it belongs to the group (one fix settles it with the others, or the conflict is real for it), "falls" when it does not, "partly" when only part of it does (say which part in reason). Check every reason the group gives for taking a member in or leaving one out against facts you checked (the code, an official primary source), not against the group's own words. Then give the verdict for the group as a whole: "stands" when it holds, "falls" when it does not hold for any two members, "unverifiable" when you cannot check it (say why in reason). Give each member's verdict in members, by id.
{{else}}
Try to prove the fix option below is wrong. It has no quotes of its own: check the content at the world-solution URL, and whether the quotes of the findings it rests on support it. Then check whether it is how the world builds the same thing (the standard practice in official primary sources): a fix the practice does not use (pinning an isolation level, comparing with a pre-release build) falls unless the option gives a ground for departing.
verdict: "stands" when you could not refute it, "falls" when it is wrong or departs from the practice with no ground (give evidence), "unverifiable" when you cannot check it (say why in reason).
{{/if}}

{{text}}
