# rent-or-buy

A small Claude Code plugin that decides, by calculation only, between paying a little each time (rent) and paying once (buy) when you do not know how long the need will last (the ski rental problem). It is used for two decisions in a Claude Code session:

- **keepalive**: while a session waits, keep sending short requests so the prompt cache does not expire, or stop and pay to rewrite the cache later.
- **compact**: keep reading a large context, or pay once to summarize and shrink it.

Terms: `keepalive` is a short request sent only to keep the prompt cache from expiring (the cache lives 5 minutes or 1 hour after the last request; if it expires, the next request pays to rewrite it). `compact` is Claude Code's operation that summarizes the conversation to shrink the context. LiteLLM is an open-source project that publishes a JSON table of model prices.

Inputs, in short (all costs in one unit the caller chooses; the cache layer uses dollars): `rent` is the cost of one more rental (for keepalive, one request); `buy` is the one-time cost (for keepalive, the extra cost of rewriting the expired cache; for compact, the cost of the summary); `spent` is the total already paid in rentals in this round (a round is one wait for keepalive, the span since the previous compact for compact); `certain` says whether the event that ends the renting (the next real request) is sure to come.

The plugin has no skills and does not touch the session. Callers (scripts, hooks, other plugins) run `bin/rent-or-buy` with JSON on standard input and read JSON from standard output. It keeps no decision state: the caller passes the running totals (`spent`) each time. The only files it writes are the optional decision log and the daily price cache (see Environment). When the plugin is missing or fails, the caller should fall back to its own fixed numbers.

The design is in `docs/specs/2026-10-24-rent-or-buy-design.md` in the repository. The skill-level text of this repository is in Japanese; this README is English only.

## Install

```
/plugin marketplace add raiki61/claude-plugins
/plugin install rent-or-buy@raiki61
```

Claude Code puts the `bin/` of an enabled plugin on the PATH of its Bash tool. Python 3.11+ (standard library only) is required.

## Commands

All commands read a JSON object from standard input (empty input means `{}`) and print one JSON object. Exit code: 0 decided, 2 bad input, 3 unknown model, 4 unreadable transcript (`snapshot` failures exit 1). On a non-zero exit the output is `{"error": "<key>", "why": "..."}`.

- `rent-or-buy decide`: the core, with `rent`, `buy`, `spent`, `certain` and the optional keys of section 2.1 of the design. Optional keys: `miss` (share of rentals that fail to avoid the buy), `hazard` (probability the ending event comes in the next interval), `deferred`/`defer_limit` (postponements so far / allowed), `forced` (the caller's hard limit was reached), `ask` (ask the other side before buying), `answer` (its reply: `{"go": true, "prep": {...}}` or `{"go": false, "why": "..."}`), `policy` (name of the stopping rule, default `fixed`). Output: `action` (`rent` or `buy`), `why` (reason, Japanese text), `consult` (true when the caller should ask the other side and call again with `answer`), `prep` (preparation info from the reply, for example the compact focus), `policy` (rule used).
- `rent-or-buy keepalive [--transcript FILE]`: needs `model`, `lifetime` (cache lifetime in seconds: 300 or 3600), `context_tokens`, `spent`, `certain`. With a transcript, `model`, `context_tokens` and `last_request_at` are filled from it (standard input wins). Adds `next_at` (when to send the next request) to the output.
- `rent-or-buy compact [--transcript FILE]`: needs `model`, `lifetime`, `context_tokens`, `spent`. With a transcript, those and `post_tokens` (context size right after the previous compact, in tokens) are filled from it, and `spent` is computed as the extra cost of reading the larger context, compared with the post-compact size, in every response since the last compact.
- `rent-or-buy prices MODEL`: the normalized model name, the unit prices used and where they came from.
- `rent-or-buy snapshot`: rebuild the bundled price snapshot from LiteLLM's main branch (run by the maintainer; needs the network).

The input key `prices` overrides unit prices for one call (`{"claude-opus-5-5": {"input_cost_per_token": 4e-6}}`, LiteLLM field names). Keepalive and compact outputs also carry `rent`, `buy`, `prices` (`snapshot`, `latest` or `override`, with its origin), `version` and `guide` (the commit of the notes repository that holds the formulas).

## Layout

- `rent_or_buy/`: the algorithm. Knows nothing about Claude. Public names: `decide`, `register` (add a stopping rule by name), `append_record` (append one line to the decision log).
- `prompt_cache/`: the fit to Claude's prompt cache: prices, model-name normalization, transcript reader, translation from session facts to the core's input.
- `bin/rent-or-buy`: the command. Nothing outside the plugin imports the two modules; `tests/test_boundary.py` checks four rules: the algorithm imports only the standard library and itself; the cache layer uses only the algorithm's public names; nothing outside the plugin imports either module; the algorithm contains no Claude-specific words.

## Environment

- `RENT_OR_BUY_OFFLINE=1`: never fetch the latest prices.
- `RENT_OR_BUY_PRICES`: path of a JSON file of price overrides (same shape as the `prices` key).
- `RENT_OR_BUY_MODEL_ALIASES`: extra model-name table, `name=model,name=model` or a JSON object.
- `RENT_OR_BUY_RECORD`: where to append the decision log (JSON Lines, rotated at 10 MB); `off` disables it. Default `<cache dir>/decisions.jsonl`.
- `RENT_OR_BUY_CACHE_DIR`: cache directory, default `~/.cache/rent-or-buy` (holds `latest.json`, fetched at most once a day, and the decision log).

## Prices

Unit prices come from a bundled copy of LiteLLM's price table (`prompt_cache/snapshot.json`, with the commit and date), refreshed from LiteLLM at most once a day into the cache directory, then your override file, then the per-call `prices`. Model names are normalized (cloud prefixes, `[1m]` (the 1M-context suffix), dates and versions removed) and looked up exactly; there is no fuzzy matching, so an unknown name fails with exit code 3 instead of using another model's price.
