# rent-or-buy: design

This is the canonical design document of rent-or-buy. A Japanese translation is in [design.ja.md](design.ja.md); when the two differ, this English version wins. Both files have the same headings in the same order, and `tests/test_docs.py` checks that.

Who reads this: people who maintain the plugin, people who write a caller for it, and anyone who takes the plugin out of this repository. How to call the commands is in [README.md](../README.md); this document explains why the plugin is built the way it is.

## 1. The problem

A Claude Code session meets two decisions where you either pay a little each time (rent) or pay once (buy), without knowing how long the need will last.

- keepalive: while a session waits for something (a background job, a message), the prompt cache expires 5 minutes or 1 hour after the last request. A short request sent before expiry keeps the cache alive (rent: one request). If you stop, the next real request pays to write the whole context to the cache again (buy: the extra cost of that rewrite).
- compact: Claude Code's operation that summarizes the conversation to shrink the context. Every request on a large context reads more cached tokens than it would after a compact (rent: the extra read on this request). A compact costs a summary and a new cache write once (buy).

This shape is the ski rental problem, also called the rent-or-buy problem ([Wikipedia: Ski rental problem](https://en.wikipedia.org/wiki/Ski_rental_problem)). Without a model of the future, the usual answers are fixed numbers: send a keepalive every N seconds up to M times, compact above a token threshold. These numbers do not move when prices, models or context sizes change.

rent-or-buy is a small component that makes these decisions from costs alone. It has no state, knows nothing about the caller's process, and is called as a command with JSON in and JSON out.

## 2. Layers

One plugin holds two Python modules (a modular monolith: shipped as one unit, the boundary inside is kept by tests).

```
  caller (a script, a hook, another plugin)
  │  runs the command bin/rent-or-buy (JSON on stdin, JSON on stdout). Never imports Python modules
  ▼
  prompt_cache/   the fit to Claude's prompt cache
  │  price table, model-name normalization, transcript reader, translation (session facts -> core input)
  ▼  uses only the public names of rent_or_buy (listed in __init__.py)
  rent_or_buy/    the rent-or-buy algorithm. Knows neither Claude nor tokens
     core decide, policy table, decision log
```

- Dependencies go one way, top to bottom. A lower layer never names a file, name or behavior of an upper layer.
- The algorithm is kept apart from Claude because the two change at different rates. The algorithm follows from theory and rarely changes. Prices, model names and the transcript format change whenever Anthropic or Claude Code changes them.
- Why not two plugins: there is one kind of caller today and no user of the algorithm alone. Two plugins would double version pinning and distribution, and the boundary can be kept by tests. If a second user appears, the `rent_or_buy/` folder can be moved out as it is.
- The component keeps no state. The caller passes the running totals every time.
- Policy (when to send a keepalive, when to ask the agent, how to run `/compact`, where to set Claude Code's automatic compact) belongs to the caller (section 7).
- If the component is missing or fails, the caller falls back to its own fixed numbers. It is a cost optimization, not a gate.

### 2.1 Keeping the boundary

`tests/test_boundary.py` checks four rules and fails when one breaks.

1. `rent_or_buy/` imports only the standard library (Python's `sys.stdlib_module_names`) and itself.
2. `prompt_cache/` uses only the public names of `rent_or_buy` (those in `rent_or_buy/__init__.py`) and never imports its inner files such as `rent_or_buy.policies`, so the inside can be rebuilt without breaking the outside.
3. Nothing outside the plugin imports `rent_or_buy` or `prompt_cache`. Outside code goes through the command.
4. `rent_or_buy/` contains no Claude words (claude, token, cache, compact, keepalive, and the Japanese words for cache, token and summary). Import checks alone cannot stop Claude knowledge written into names or text. The rule catches words only: a Claude unit price written as a bare number is not detected.

The test finds imports inside functions and conditions (it walks every node of the syntax tree with `ast`), relative imports (at most one level inside `rent_or_buy`), and imports through `importlib.import_module`, `__import__` and `getattr`. It does not find imports built from strings at run time or hidden in `exec` or `eval`.

No framework is used. The standard tool for import direction is import-linter's layers contract ([import-linter: layers](https://import-linter.readthedocs.io/en/stable/contract_types.html#layers)); Spring Modulith and Packwerk are the same kind of tool. They are made for code with dozens of modules, and here there are two. None of them can express rule 1 (standard library only, as an allow list) or rules 3 and 4, so a local test would remain anyway. Move to import-linter when there are four or more modules or when someone uses the algorithm from another repository.

## 3. Core: decide (`rent_or_buy/`)

### 3.1 Input

| key | type | meaning |
|---|---|---|
| rent | number | cost of renting once more |
| buy | number | cost of buying |
| spent | number | total paid in rentals in this round |
| certain | bool | whether the event that ends the renting is sure to come |
| miss | number, default 0 | share of rentals that fail to avoid the buy |
| hazard | number or null | probability the ending event comes in the next interval |
| deferred | integer, default 0 | postponements so far after a buy was decided |
| defer_limit | integer, default 0 | postponements allowed |
| forced | bool, default false | the caller's hard limit was reached |
| ask | bool, default false | ask the other side before buying (3.4) |
| answer | object, optional | the other side's reply, on the second call (3.4) |
| policy | string, default fixed | name of the stopping rule |

A round is one wait for keepalive, or the span since the previous compact for compact. For keepalive, the ending event is the next real request (the result or message the session waits for), and `miss` is the share of waits in which the cache expired although keepalives were sent.

The cost unit is the caller's choice (the cache layer uses dollars). Malformed input (negative numbers, wrong types, unknown keys, a malformed `answer`) is never silently corrected: the call stops with a reason.

### 3.2 Output

```json
{"action": "rent", "reason": "within_buy_cost", "why": "...", "consult": false, "prep": null, "policy": "fixed"}
```

- `action`: `rent` or `buy`.
- `consult`: true only when the policy says `buy`, `forced` is false, `ask` is true, `deferred < defer_limit` and no `answer` was given. The caller should ask the other side and call again (3.4).
- `prep`: preparation info from a "go" reply (for compact, the focus: one line that tells the summary what to keep). Otherwise null.
- `reason`: a short key for machines: `within_buy_cost`, `reached_buy_cost`, `hazard_above_ratio`, `hazard_below_ratio`, `no_hazard`, `forced`, `defer_limit_reached`, `consult_go`, `consult_deferred`, `consult_unreadable`, `unknown_policy_fallback`.
- `why`: the reason in English, for people.
- `policy`: the rule actually used.

A policy function returns `(action, reason, why)`. The cache layer adds the plugin version to the output (4.4).

### 3.3 Policies

Policies are looked up by name in a table, and callers can add their own (`register`). An unknown name falls back to `fixed`, and `why` says so.

`fixed` (the only policy in the first version) is deterministic. The part of the buy that renting can avoid is `(1 - miss) * buy`. Rent only while one more rental keeps the total below it: `spent + rent < (1 - miss) * buy`.

- When `certain` is true, this rule alone decides. With a constant rent and `miss = 0`, it rents `K = ceil(rho) - 1` times and then buys, where `rho = buy / rent`. Proof of the bound: let the event come after `t` intervals. If `t <= K`, the cost is `t * rent`, which is the optimum. Otherwise `t >= K + 1 >= rho`, so the optimum in hindsight is `buy`, and the cost is `K * rent + buy < buy + buy`. So the cost is always less than twice the optimum, which is the classic deterministic bound for ski rental ([Wikipedia](https://en.wikipedia.org/wiki/Ski_rental_problem)). `tests/test_core.py` checks it for many prices and lengths.
- When `rho` is not an integer, the best deterministic rule also compares stopping one rental earlier and takes the smaller ratio. `fixed` skips that comparison: the difference is one rental, both stay below 2, and compact's rent changes every round, so it cannot be counted in rentals. One rule that compares totals covers both scenes.
- Compact follows the same rule: compact when the extra read paid since the last compact (`spent`) reaches the cost of one compact (`buy`).
- When `certain` is false: rent only if `hazard` is given, `hazard > rent / ((1 - miss) * buy)`, and the rule above still allows renting. The ratio test compares one more rental against what it saves on average: with probability `hazard` the event comes in the next interval and the avoidable buy is saved. The total cap stays even while the event looks likely. Without `hazard`, buy.

Planned policies (not in the first version):

- `random`: choose the buy time at random. The expected cost is at most `e / (e - 1) ≈ 1.58` times the optimum, the randomized bound for ski rental ([Wikipedia](https://en.wikipedia.org/wiki/Ski_rental_problem)). The random seed goes to the decision log.
- `learned`: predict the wait length or the number of remaining requests from the decision log and choose the stop time with a trust level on the prediction (ski rental with predictions: [Purohit, Svitkina, Kumar, NeurIPS 2018](https://proceedings.neurips.cc/paper/2018/hash/73a427badebe0e32caa2e1fc7530b7f3-Abstract.html)).

Two rules are applied on top of every policy by the core.

- Hard limit: if `forced` is true, the answer is `buy` whatever the policy says (`reason` is `forced`, no asking). For compact, this is the caller's own line set below Claude Code's automatic compact.
- Postponement limit: when the policy says `buy`, `ask` is true and `deferred < defer_limit`, the other side is asked (3.4); a "not now" reply gives `rent`. When the limit is reached, the core buys without asking (`defer_limit_reached`). Each postponement can make the worst case worse than twice the optimum; the caller bounds that by choosing `defer_limit`.

### 3.4 Consult

A way to ask the other side before buying (for compact, the agent whose conversation would be summarized). The core does not know who the other side is.

- As a function: `decide(inputs, consult=fn)`. The core calls `fn` only when it should ask (the condition for `consult: true` in 3.2). The reply is one of:
  - `{"go": true, "prep": {...}}`: go ahead; `prep` is passed through (for compact, the focus).
  - `{"go": false, "why": "..."}`: postpone.
  - an exception or a malformed reply: treated as if nobody was asked; the core buys (`consult_unreadable`).
  Without `fn`, the core returns `consult: true`, as the command does.
- As a command, a function cannot be passed, so the call is split in two. The first call returns `{"action": "buy", "consult": true}`; the caller asks the other side and calls again with the reply in `answer`. After a postponement, the caller adds 1 to `deferred` from the next round. The core stays stateless. A malformed `answer` on the command is an input error, not a silent buy (only a malformed function reply becomes a buy).

### 3.5 More than two actions (planned)

At keepalive time there are really three actions: send (rent), compact (pay now to lower later rent), or stop (buy). Problems with three or more actions are called multislope ski rental ([Lotker, Patt-Shamir, Rawitz, "Rent, Lease or Buy", STACS 2008](https://arxiv.org/abs/0802.2832)). A compact shrinks the context and so lowers the price of each keepalive, which is exactly this shape. The first version has two actions; a list of actions as input (`options`) will be added after the decision log shows whether it pays.

### 3.6 Decision log

A function in the core appends one JSON Lines row per decision. It does not look at the content, so it knows nothing about Claude.

- The caller chooses the file. The command's default is `<cache dir>/decisions.jsonl`; `RENT_OR_BUY_RECORD` changes the path and `off` disables it.
- The log grows forever, so it has a cap: past 10 MB the file is renamed to `decisions.1.jsonl` and a new one starts. Only one old file is kept.
- If the log cannot be written (no folder, no permission), the decision is still made and the output carries the reason in `record`.

## 4. Cache layer (`prompt_cache/`)

### 4.1 Prices

The model is ccusage, a tool that computes Claude Code usage cost from the same transcripts and solves the same price and model-name problems. ccusage embeds a copy of LiteLLM's price table, fetches the latest table at run time, and falls back to the copy when the fetch fails ([ccusage pricing.rs](https://github.com/ryoppippi/ccusage/blob/main/rust/crates/ccusage-core/src/pricing.rs), `load_with_overrides`). rent-or-buy does the same.

- Bundled copy: `prompt_cache/snapshot.json`, taken from [LiteLLM's price table](https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json). Only entries for direct Anthropic access (names starting with `claude-`, without a provider prefix) and only the fields below are kept. The copy records the LiteLLM commit and the date it was taken.
- Fields used (dollars per token): input `input_cost_per_token`, 5-minute cache write `cache_creation_input_token_cost`, 1-hour cache write `cache_creation_input_token_cost_above_1hr`, cache read `cache_read_input_token_cost`, output `output_cost_per_token`. Models whose price rises with the request size (above 100,000 tokens) also have `..._above_100k_tokens` fields. The values were checked against [Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing) when the copy was taken.
- Latest: fetched from LiteLLM's main branch at most once a day into `<cache dir>/latest.json`. ccusage fetches on every run because a person runs it now and then; this component is called in the background on every keepalive, so it fetches at most daily. Fetched entries are checked (all five prices are positive finite numbers, read < input < write; tier fields are positive finite and not below the base price) and failing entries or fields are dropped. The two fetches (commit and table) have 5 seconds in total. Any failure falls back to the copy: the latest prices are an optimization and never stop a decision. A cached latest table older than the copy or than 7 days is ignored, and the output says `prices.latest_skipped: "stale"`. `RENT_OR_BUY_OFFLINE=1` never fetches (like ccusage's `--offline`).
- Overrides: a price file (path in `RENT_OR_BUY_PRICES`) and the per-call `prices` key are applied last and win.
- Refreshing the copy: the maintainer runs `bin/rent-or-buy snapshot`. ccusage refreshes its copy with a daily CI commit ([update-pricing.yaml](https://github.com/ryoppippi/ccusage/blob/main/.github/workflows/update-pricing.yaml)). Here it is manual, because a repository that bumps versions when changes are merged would conflict with automatic commits.
- The output's `prices` says which layer priced the call (`snapshot`, `latest`, `override`) and its origin (LiteLLM commit or fetch date).

Data-residency pricing (`inference_geo`, 1.1 times) and Fast mode multiply every field by the same factor (Anthropic's pricing page). Decisions depend only on price ratios, so the first version ignores both.

### 4.2 Measured values and defaults

`prompt_cache/prices.toml` holds the values that LiteLLM does not have. Callers can override each of them.

- keepalive: one keepalive writes 380 tokens to the cache and outputs 5 tokens. Measured on one keepalive prompt; other prompts differ.
- keepalive: margin `m` = 60 seconds before the cache expires (a keepalive every 4 minutes for the 5-minute cache). This matches the 240-second default of an existing keepalive plugin ([cache-keepalive](https://www.claudepluginhub.com/plugins/yujiachen-y-cache-keepalive-plugins-cache-keepalive)). Tighten it after the decision log shows how late requests actually go out.
- compact: 25,000 tokens of context after a compact and a 5,000-token summary. Example values, not measured.

### 4.3 Model names

The model name written in a transcript is not always the name in the price table: cloud prefixes, the 1M-context suffix `[1m]`, dated versions, names set by an internal proxy. ccusage matches exactly, then lowercases and replaces `.` and `@` with `-`, then falls back to the longest table name the given name contains (fuzzy matching). Users can add aliases in `CCUSAGE_MODEL_ALIASES` ([ccusage model_aliases.rs](https://github.com/ryoppippi/ccusage/blob/main/rust/crates/ccusage-core/src/model_aliases.rs)). rent-or-buy does this:

1. Look the name up in the user's alias table (`RENT_OR_BUY_MODEL_ALIASES`, `name=model` pairs separated by commas, or a JSON object, the same shape as ccusage).
2. Normalize: lowercase, drop a trailing `[...]`, drop everything before `claude-` (prefixes like `us.anthropic.`), replace `.` and `@` with `-`, drop a trailing date (`-20261001`) and version (`-v1:0`). Look the result up in the price table and the alias table.
3. If nothing matches, return "unknown model" (exit code 3). The caller falls back to its fixed numbers. The failed name goes to the decision log, so it can be added to the copy or to the aliases.

There is no fuzzy matching. ccusage sums past usage, where a close price does little harm. This component makes automatic decisions from prices, and another model's price would skew them.

The normalization tests use real names as samples: a transcript name from a direct Anthropic session (`claude-opus-5-5`) and cloud entries from LiteLLM's table (`us.anthropic.claude-opus-5-5` and others). Add names from other environments as samples when they are seen.

### 4.4 Translation

Translation turns the facts of a scene into the core's input. Prices are per token; `read` is the cache read price and `write` is the cache write price for the cache lifetime in use.

keepalive:

- Takes: model, cache lifetime (300 or 3600 seconds), context size, rentals paid so far in this wait (`spent`), whether the awaited event is certain (and, if known, `hazard` and `miss`), the time of the last request. The tokens one keepalive writes and outputs, and the margin `m`, default to 4.2.
- Maps: rent = one keepalive = `read * context + write * keepalive_write + output * keepalive_output`; buy = the extra cost of an expired cache = `(write - read) * context`.
- Returns: the core's output plus `next_at` (when to send the next keepalive), `rent`, `buy`, `prices` and `version`. `turn_end_at`, if given, is echoed for the decision log. For keepalive, `buy` means stop, so there is no asking.
- `next_at` = last request time + lifetime - `m`. The cache lifetime counts from the start of the request ([Claude Code prompt caching](https://code.claude.com/docs/en/prompt-caching)). The transcript stamps the time before the request leaves the machine, so this errs on the safe side. Counting from the end of the turn instead would also count the time spent generating the answer.

compact:

- Takes: model, the cache lifetime that the compact writes, context size, context size after the previous compact (default 4.2), summary size, extra read paid since the previous compact (`spent`), whether the cache is warm, the cost of one consult round trip, and the core's `forced`, `ask`, `deferred`, `defer_limit`, `answer`.
- Maps: rent = the extra read on this request = `(context - post_compact_context) * read` (0 if negative); buy = `post_compact_context * write + summary * output + consult_cost`. `certain` is true.
- Warm or cold cache does not change the decision when every write uses the same lifetime. With a 1-hour session cache and a 5-minute compact, a cold cache would favor compacting earlier, but there is no measurement yet, so the first version only logs it.
- Returns: the core's output (`buy` means compact now) plus `rent`, `buy`, `prices` and `version`. The caller adds `rent` to its running total and passes it next time.

Prices that rise above 100,000 tokens are chosen by the size of the request: the context size for reads, writes and output of a keepalive; the post-compact size for the compact's write; the pre-compact context size for the summary output.

### 4.5 Reading the transcript

So that callers need not count, a reader extracts the facts from the session transcript (Claude Code's JSON Lines file). On the command it is `--transcript FILE`.

- Context size: the sum of `input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens` in `message.usage` of the last response. A response is split into one line per content block with the same `message.id`, so lines are grouped by id.
- Model: `message.model` of the last response.
- Last request time: `timestamp` (UTC, ISO 8601) of the last line with `"type": "api-request"` and `querySource` `repl_main_thread` (requests of the main conversation only).
- Context after a compact: `compactMetadata.postTokens` of the last line with `"subtype": "compact_boundary"`.
- Extra read since the last compact: for each response after it, `(context - post_compact_context) * read` (0 if negative), summed.
- This format was checked on Claude Code 2.1.310 transcripts; it is not a documented format. Malformed lines are skipped and counted (`transcript.skipped_lines` in the output). If no value at all can be read, the result is "transcript unreadable" and the caller falls back to its fixed numbers.
- When the facts a scene needs (model and context size, and for keepalive also the last request time) are missing from both the transcript and standard input, for example right after a compact before any response, the command does not fill them with defaults and exits with code 4. It does not substitute the post-compact size for the context size, because the model is unknown too.

## 5. Command

`bin/rent-or-buy` (Claude Code puts the `bin/` of an enabled plugin on the PATH of its Bash tool). JSON object on standard input, one JSON object on standard output. Python 3.11 or later, standard library only (Claude Code plugins have no step that installs pip dependencies on the user's machine).

- `rent-or-buy decide`: the core as it is.
- `rent-or-buy keepalive [--transcript FILE]`: 4.4 keepalive. With a transcript, model, context size and last request time are filled from it (standard input wins).
- `rent-or-buy compact [--transcript FILE]`: 4.4 compact. With a transcript, model, context size, post-compact size and the extra read so far are filled from it.
- `rent-or-buy prices MODEL`: the normalized name, the prices used and their origin (for inspection).
- `rent-or-buy snapshot`: rebuild the bundled copy from LiteLLM's main branch (run by the maintainer).

Exit codes: 0 decided, 1 `snapshot` failed, 2 malformed input, 3 unknown model, 4 transcript unreadable. On a non-zero exit the output is still `{"error": "<key>", "why": "<English>"}`. Failures of `decide`, `keepalive` and `compact` are written to the decision log together with the input, so unknown model names can be collected (`prices` failures are not). `version` in outputs is the `version` of the plugin's `plugin.json`.

## 6. Decision log fields

Every row: time, scene (`decide`, `keepalive`, `compact`), input, output. Rows of the cache layer also carry `prices` and `version`, so a later mismatch between formula and component can be found.

- keepalive rows are meant to measure what is still guessed:
  - Times: the last request and the decision (the row's time), and the end of the turn when the caller passes it. When the sent request actually went out is filled in later from the transcript.
  - From these come the time to generate the last answer (turn end - last request) and the delay from decision to request.
  - A large cache write after a keepalive counts as a miss. Collected over many waits, this gives the miss rate `q(m)` for each margin `m`.
- compact rows: whether the cache was warm or cold, context size before and after, and the usage of the compact request and the next request (including which lifetime's write price applied), to compare cold and warm compacts by measurement.
- Outcome fields (whether it missed, what was written next, when the request went out) are unknown at decision time. The component has no state, so a tool that fills them later from the transcript is planned together with tuning `m` (section 10, step 4).

## 7. Callers

The component does not decide policy. A caller that wires it into a session dispatcher should do the following. This is the plan for the first caller in the original repository.

- keepalive: send at `next_at`, and turn the number of keepalives into the core's `action`. Just before sending, check whether the awaited event has already arrived; if so, do not send (otherwise a keepalive can go out in the same second as the result it was waiting for).
- compact:
  1. Decide only while waiting with an empty input box, that is, at keepalive time. At that moment ask the compact decision first; if it says compact, do not send the keepalive (the compact request reads the cache and keeps it alive). Otherwise ask the keepalive decision.
  2. When the compact decision returns `consult: true`, replace that keepalive's text with the question: "It is time to compact. Reply with one line naming the focus to keep, or with skip: and a reason if now is bad. Do not use tools." The request count stays one; only a few dozen tokens are added.
  3. Read the reply from the last response in the transcript and pass it as `answer` on the second call. On go, the caller types `/compact <focus>` into the session. On skip, count a postponement; past the limit, compact without a focus.
  4. Replace fixed thresholds (such as "compact above 100,000 tokens") with the core's `action` when the component is present, and keep them only as the fallback.
- Claude Code's automatic compact: keep it as a safety net, but raise its line (the `autoCompactWindow` setting) close to the context limit. It cannot choose its moment and may run in the middle of a turn, so it should not be the normal path.
- Finding the component: look up `rent-or-buy` in Claude Code's record of installed plugins (`installed_plugins.json`) and run its `bin/rent-or-buy`. If it is missing or exits non-zero, use the fixed numbers.

## 8. Layout and versions

```
rent-or-buy/
  .claude-plugin/plugin.json
  README.md, CHANGELOG.md
  docs/design.md, docs/design.ja.md   this document and its translation
  bin/rent-or-buy             the command (5)
  rent_or_buy/                the algorithm (3)
    __init__.py               public names: decide, InputError, register, append_record
    core.py                   decide, hard limit, postponement, consult
    policies.py               policy table and fixed
    record.py                 append to the decision log, rotate at the cap
  prompt_cache/               the cache layer (4)
    __init__.py
    prices.py                 copy, latest and overrides layered into unit prices
    names.py                  model-name normalization
    translate.py              keepalive and compact translation
    transcript.py             transcript reader
    snapshot.json             copy of LiteLLM's price table
    prices.toml               measured values and defaults
  tests/
    test_core.py              the promises of fixed (9)
    test_translate.py         translation, transcript and command, without network
    test_boundary.py          the four boundary rules (2.1)
    test_names.py             model-name normalization on real samples
    test_docs.py              the English and Japanese design documents stay aligned
```

- No skills. Callers are programs; there is no use from inside a conversation yet.
- Pin the component by commit SHA, not by tag (the original repository makes no tags).

## 9. Tests

Tests cover only the component's promises.

- With a constant rent and no postponement, `fixed` costs less than twice the optimum in hindsight for every wait length.
- The two-step consult: the first call gives `consult: true`; the second call gives `buy` (go) or `rent` (postpone).
- The four boundary rules (2.1).
- Model-name normalization (4.3) on real samples.
- The design document and its translation have the same headings in the same order and cite the same URLs.

## 10. Prior art and roadmap

No existing tool does the same thing (as far as a web search found):

- keepalive: there are break-even formulas for the interval and keepalive plugins (240 seconds, up to 7 requests), but all use fixed numbers and none decides when to stop.
- compact: OpenHands, Codex, Cline, Aider and Letta all compact at a size or ratio threshold. None was found that chooses the moment from a cost formula.
- Cache retention in inference servers: Continuum chooses retention time by expected gain, but for GPU memory and without a worst-case bound. One paper treats cost-based retention time as ski rental with the 2x worst case ([arXiv:2309.03521](https://arxiv.org/pdf/2309.03521)).
- Prices and model names follow ccusage (4.1, 4.3).

Steps. Measure each step's effect in the decision log before moving on.

1. Design (this document).
2. Core, cache layer, command and log; keepalive wired into a caller.
3. Compact policy in the caller (consult, skip limit, raised automatic compact line).
4. A tool that fills outcome fields, tuning of `m`, and a status line display.
5. `random`, `learned`, three or more actions, choosing the cache lifetime (5 minutes or 1 hour), and translating "continue the previous session or start a new one".

The first version covers steps 2 and 3.
