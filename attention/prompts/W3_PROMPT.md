---
vars:
  prFiles: text
  structure: text   # W1's structure
  general: text     # W2's general structure
  design: list      # W2's design from zero: "<id>: <element> (adds: ...; removes: ...)"; empty when none
  means: list       # the purpose stage's means, as the PR words them
  lenses: text      # the lens texts the script picked for this stage (LENS_TABLE.W3)
---
{{prFiles}}

Structure of the system after this PR (from the structure stage):
{{structure}}

General structure of this kind of system (from a reader who did not see the PR):
{{general}}

Design from zero for the same purpose (from the same reader, who saw only the purpose sentence):
{{design|bullets}}

Means this PR chose (as the PR words them):
{{means|bullets}}

{{lenses}}

[s8.1] Put the two side by side and list the differences in how parts are cut, which way things flow, where the source of truth sits and where boundaries are drawn. If the general structure names tools or OSS, do not compare against them (a later stage does that).
[s8.2] If the general structure is only generic statements that fit any design, so it cannot be compared (different from agreeing with no differences), set comparable to false and say why in whyNotComparable.
[s9.1] For each difference decide: "align" with the general structure, or "may-differ" for a reason specific to here. [s9.2][s9.3] Decide against outside standards (written intent, the general structure, industry practice), not against the surrounding code: when the surroundings are already broken, the broken form looks consistent. [s9.4] A reason to differ may only be an outside standard or an immovable fact outside this PR (an outside tool's specification, law or contract, shown by its primary source). The repository's current state (settings, CI, code, layout, habits, existing checks) is never a reason, however it is phrased; if that is all, decide "align". [s9.5] If a reason uses a record (decision record, known limit, exception list), first check the line was not added by this PR; if it was, it is not a reason. basis: the outside standard used. [s9.6] ifThreeMore (for may-differ): if the same problem came three more times, what would pile up as an extension of this PR's form.
Then put the means beside the design from zero. For each means, say which design element it stands for; a means that stands for none is a difference (from "means"). Each design element the PR has no means for is a difference too (from "design"). Decide these as above: "align", or "may-differ" with an outside standard or an immovable fact as basis. from: "structure" for a difference between the two structures, "design" or "means" for these.
