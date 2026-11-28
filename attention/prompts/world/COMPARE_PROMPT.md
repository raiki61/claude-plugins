---
vars:
  rejected: text      # the machine's rejection of the last round (rejected.md, filled), or empty on the first round
  english: flag       # true when lang is English: the challenge forms are given as words to follow, not as a shape
  lang: text          # the language of the answer's free text (args.lang, English when not given)
  minChallenge: text  # the shortest challenge the machine accepts, in characters (LIMITS.minChallenge)
  layers: text        # LAYER_RULES.md
  problem: text       # the problem class
  members: list       # one line per request line in this class, laid out by the script (memberLine)
  rows: list          # one entry per counterpart row, laid out by the script (rowLine)
---
{{rejected}}You compare. Below are a problem class, the means a change request chose for it (one or more request lines), and rows that each say how one counterpart solves this class at one layer: a dependency of the target, a product of the same kind, a standard, or a general structure drawn by someone who did not see the request.
You have no tools. Do not call any tool. This prompt is everything you are given.

For every pair of a row and a request line, decide whether the request's means is the same as that row's practice, at that row's layer:
- `same`: the means does what the practice does at that layer.
- `differs`: the means does it another way at that layer. Write `challenge` {{#if english}}in the form "The request does X; <the counterpart> does Y. Choose Y unless …"{{else}}in {{lang}}, saying in {{lang}} what this English form says: "The request does X; <the counterpart> does Y. Choose Y unless …". The form is a shape, not words to quote: do not copy its English words, and write out what X, Y and N stand for instead of leaving the letters{{/if}}, at least {{minChallenge}} characters, naming the condition under which X would be the right choice.
- `none`: the request line proposes no means, or the row found nothing (marked "nothing found").
Do not decide whether differing is acceptable; a later step asks that. There is no fourth value.

A request line marked "judged at the level of line N" has a problem that exists only because of the means the request chose in line N, and this class is line N's problem. For such a line, decide whether the counterpart, with its practice for this class, has that problem at all. If its practice does not give rise to the problem, the verdict is `differs`, with `challenge` {{#if english}}in the form "The request has to do X because of the means of line N; <the counterpart> does Y, where the problem does not arise. Choose Y unless …"{{else}}in {{lang}}, saying in {{lang}} what this English form says: "The request has to do X because of the means of line N; <the counterpart> does Y, where the problem does not arise. Choose Y unless …". The form is a shape, not words to quote: do not copy its English words, and write out what X, Y and N stand for instead of leaving the letters{{/if}}. If the counterpart has the same problem, compare the line's means with how the counterpart handles it, as for any other line. "The problem does not arise" is an answer only when the counterpart's practice handles this class (line N's problem) in another way and that way avoids the problem; a counterpart that takes no part in this class (one that only makes values, or that sits on no side of this boundary) does not avoid the problem, it is merely absent: compare the line's means with what that counterpart does, as for any other line.

{{layers}}

## Problem class

{{problem}}

## Request lines and the means each chose

{{members|join:"\n"}}

## Rows

{{rows|join:"\n"}}

## How to answer

- `items`: one entry for every pair of a row above and a request line above: `{row, n, verdict, challenge, why}`. `row` is the row id (R1, G, ...), `n` the line number.
- `challenge`: only for `differs`; empty otherwise. `why`: one sentence on what decided the verdict.
- Write `challenge` and `why` in {{lang}}.

Return only JSON that matches the output schema.
