---
name: when-to-ask-a-person
description: Decides whether a question really needs a person, first checking whether standard practice or the request settles it, and asks only when sources disagree, priorities decide it, or a recorded decision would be overturned. Use when about to stop and ask, or when wondering "can we decide this ourselves". Not for wording the question itself.
---

# Ask a person only what nothing else settles

**Core rule: before a question goes to a person, ask whether the standard practice or the request's own text settles it on one answer. If it does, decide it yourself and name that source.**

## Pitfalls (read first)

- **A means the request proposes decides nothing.** It is a proposal to doubt against the standard practice. The request's text settles the cost it accepts and the scope it asks for, not the means.
- **"It narrows today's behaviour" or "it touches policy" is not by itself a reason to ask.**
- **Finding nothing is not a reason to ask either.** When nothing settles it and none of the three cases fits, go ahead with your own recommendation and say where you searched.

## Steps

### 1. Look for what settles it

- The standard practice: standards, the established practice of well-known open-source software, official documents, and any rows you were given on how the world solves the same problem.
- The request's own text.
- If one settles the answer, decide it yourself; the item passes without asking.

### 2. Ask a person only in three cases

1. **The deciding sources disagree**: the earlier decisions, the policy, how the target already solves the same problem, and the standard practice point to different answers.
2. **The answer changes with how a person ranks priorities** (what to give up as the cost), and the standard practice does not settle that ranking.
3. **Following the deciding sources would overturn a recorded decision** (a person's earlier decisions and answers).

An item that fits none of the three does not go to a person: decide it and write its deciding source.

### 3. Not case 2

- Which of several behaviours to turn on, where, and how strongly is not case 2 when the standard practice makes it a setting whose default keeps today's behaviour and leaves where and how strongly to the operators. Whether to turn it off in older environments is settled the same way.
- A loss that a limit outside the fix causes (a limit of an outside service or platform) is not case 2 when the request's text already accepts it.

### 4. When nothing settles it

When you find neither a standard practice nor any of the request's text that settles the item, and it fits none of the three cases, go ahead with your own recommendation. If the answer then turns out to change with how a person ranks priorities, it is case 2.

### 5. Always a person, regardless

These always go to a person:

- a write to the outside;
- an operation that cannot be undone;
- a change to the policy document;
- widening a protection;
- a web search result that raised a new doubt about the fix;
- a touch on a protected path.

## Done when

- Every open item is either decided with a deciding source, or goes to a person under a named case or as one of the items that always go to a person.
- No item goes to a person only because nothing was found, or only because it narrows today's behaviour or touches policy.
- No means the request proposes was taken as a deciding source.

## How to report

- **A decided item**: one line with its deciding source — a URL and its section, or the request's text word for word in quotes.
- **An item decided with nothing to settle it**: write as its source "no standard found", followed by where you searched (the standards, projects, and documents you checked and found silent).
- **An item that goes to a person**: name which of the three cases applies (several may apply), or that it is one of the items that always go to a person.

## Example

Input: two open questions before a fix. (a) The fix makes slow calls fail sooner; is a rise in failed calls acceptable? The request says "Stop the page from hanging; a few more failed loads are fine." (b) The fix needs the deploy job's credentials to reach one more service.

Reply:
- (a) Decided without asking. Deciding source: the request's text, "a few more failed loads are fine" — it accepts that cost.
- (b) Goes to a person: it widens a protection, which always goes to a person.

## Works well with

- A way of writing a question to a person so that a first-time reader can decide from the text alone.
- Comparing a request with how practitioners solve the same problem, which supplies the standard practice.
