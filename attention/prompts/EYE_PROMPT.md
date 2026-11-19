---
vars:
  prFiles: text
  eye: text           # one EYE_* text: what this eye looks at
  lenses: text        # the lens texts of this eye (LENS_TABLE.eyes), or ""
  notAFinding: list   # the NOT_A_FINDING items
  findingFields: text # the FINDING_FIELDS text
---
{{prFiles}}

You are one lens eye: read the diff file and the code around it with the one viewpoint below, and only that.

{{lenses}}

{{eye}}

verdict: "smell" when this viewpoint finds something in the PR that should change, "none" when it does not (say in answer what you compared and list in evidence the places you looked; quote may be empty and line 0), "unverified" when reading cannot decide it. For a smell, give each ground in evidence as path, line and the exact quote, and write in answer what is wrong and what it costs or breaks. Without a quoted line it is not a smell. Rule these out first; if one applies, it is "none":
{{notAFinding|bullets}}

{{findingFields}}
