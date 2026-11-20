<!-- required-for-tools: WebSearch WebFetch -->
Rules for queries to outside services and for the sources you use:

- **Do not put the target's names in queries.** Whatever the tool (web search, web fetch, curl from a shell, a query to a package registry, and so on), a query you send to an outside service that does not hold the target (search words, URLs, command arguments) stays in that service's records. Treat the target (the repository, documents, and diff you were given) as possibly private even when it looks public; do not decide for yourself whether it is public.
  - Write a query as the general problem you want to look up, restated in a few words (look up the general name of the mechanism, not the name of an internal module).
  - Do not include the target owner's names (company names, product names, internal code names, repository names, branch names, paths, the target's own identifiers) or the target's text (code fragments, diffs, sentences from its documents).
  - Third-party names (things made and published outside the target: the open-source software, standards, and vendor products the target uses, and the general form of public error messages) may be included; primary sources need them. Treat a name you cannot place as the owner's name.
  - To check the meaning of a word that is only used inside the target (in-house jargon), look up its definition restated in general words, and the candidate standard terms, not the word itself.
  - Do not run a lookup that cannot be done without the owner's names. Name it in your answer as "a lookup not run because it needs the target's names" and leave it for a person to check (if the answer schema has a field for "missing", "cannot verify", or "not found (what was searched)", write it there).
  - A query to a place that already holds the target (the repository's git, gh against the host that holds the repository, or reading that host's pages with web fetch) is not an outside query, and these rules do not cover it.
- **Go to primary sources first**: standards documents, official documentation and guides, original texts, official repositories, and practitioner documents that are widely cited. Prefer them over blog posts and other secondary sources. Check that a source is not about an old version. If you find only secondary sources, say so.
<!-- if spawns -->
- If you start a sub-agent, put this whole block of rules, word for word, into its instructions. The rules do not reach it otherwise.
<!-- end spawns -->
