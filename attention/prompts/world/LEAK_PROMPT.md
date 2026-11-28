---
vars:
  lang: text      # the language of the answer's free text (args.lang, English when not given)
  items: list     # one "## Item <n>" section per restated line, laid out by the script (leakItem)
---
You check restated problem classes. Each item below has a problem class (problem, activity, queries) and, apart from it, the means a change request chose (proposed). A problem class must name the need without presupposing that means: a reader who sees only the problem class must not be led to the request's mechanism.

For each item, set `presupposes` true when the problem, the activity or a query assumes the means: it names the mechanism, its steps or its shape, even in plain words that are not identifiers. Example: "how to pause processing and resume it from where it stopped" presupposes pause-and-resume; "processing that needs a person's answer partway through" does not. A problem class that names which component does a part of the work (who raises a question, who starts a step, who holds the state) also presupposes the means when the request chose that component, even if the request states it as a given: "when the build server has to tell the reviewer that a build broke" fixes who tells; "a reviewer has to learn that a build broke" does not. Three things do not presuppose the means. First, a part given from outside the problem, which the request could not choose (a condition of the platform such as "a browser cannot keep a secret", or an existing interface the caller has no say over), may stay in the problem class. Second, the name of an established practice that names the kind of problem or change ("zero-downtime deployment", "backward-compatible API change", "cache invalidation") is not a means; the name of a mechanism that answers it ("blue-green deployment", "two-phase commit", "pause and resume") is. Third, an item marked "arises from the means of line N" is a problem that exists only because of the means the request chose in line N: that means is the premise the problem rests on and may stay in the problem class. Only the item's own means (proposed) must not be presupposed. When you set `presupposes` true, say why in one sentence in `why`, quoting the words that carry the means. Otherwise set it false and leave `why` empty. Write `why` in {{lang}}.
You have no tools. Do not call any tool.

{{items|join:"\n\n"}}

Return one entry in `items` for every item above (`n` is the item number). Return only JSON that matches the output schema.
