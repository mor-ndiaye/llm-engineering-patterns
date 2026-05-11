# Architectural Patterns

A running notebook of patterns, pitfalls, and lessons learned while building agentic LLM systems.
Curated alongside the projects in `mor-ndiaye/*` repos.

## Format

Each entry follows:

- **Pattern / Pitfall** — name in 1 line
- **Context** — where I hit it
- **The thing** — what to remember
- **Why it matters** — the underlying principle
- **Reference** — link to the repo / commit where it appeared

---

## MS Learn Agent - Sprint 1

### What I learned while building the fondations of the `ms-learn-agent`

#### 1. Sentinel values vs absence of kwarg

- **The thing:** Don't invent magic defaults like `0` or `""` to mean "absent".
  Just don't pass the kwarg.
- **Why it matters:** The signature of the called function is the contract.
  If `search(max_results: int = 5)` has a default, passing `0` to mean "use
  default" duplicates that contract in the caller. Build kwargs dynamically:

```python
  kwargs = {"query": query}
  if level := tool_input.get("level"):
      kwargs["level"] = level
  return search(**kwargs)
```

- **Reference:** `ms-learn-agent/tools.py::execute_tool`

#### 2. Exhaustive `stop_reason` handling in agent loops

- **The thing:** `Message.stop_reason` can be `end_turn`, `tool_use`,
  `max_tokens`, `stop_sequence`, `pause_turn`. Branch explicitly on each you
  expect, raise on anything else.
- **Why it matters:** A naive `if tool_use: ... else: return text` treats
  `max_tokens` (truncated reply) as a normal answer. The user gets silent
  garbage. Truncation must be loud, not invisible.
- **Reference:** `ms-learn-agent/agent.py::agent_loop`

#### 3. Text extraction by `block.type`, not `hasattr`

- **The thing:** Iterate `response.content` and select with `block.type ==
  "text"`. Anthropic's idiomatic way. Concatenate multiple text blocks if
  several exist.
- **Why it matters:** `hasattr(block, "text")` is fragile (any block with a
  `.text` attribute would match) and `next(...)` only takes the first one.
- **Reference:** `ms-learn-agent/agent.py::_extract_text`

#### 4. Anthropic SDK auto-serialization of content blocks

- **The thing:** When you pass `response.content` (a `list[ContentBlock]`)
  back into `messages.create(..., messages=[{"role": "assistant", "content":
  response.content}, ...])`, the SDK calls `.model_dump()` on each block.
  Equivalent to passing dicts manually, just less verbose.
- **Why it matters:** Knowing this lets you understand exactly what the API
  receives. Useful for debugging and for explaining the loop in interviews
  or training material.
- **Reference:** Anthropic Python SDK, Pydantic models for `TextBlock`,
  `ToolUseBlock`, etc.

#### 5. Module-level execution is a leak

- **The thing:** All test/demo code goes under `if __name__ == "__main__":`
  or in a separate `examples/` folder. Never run an agent at import time.
- **Why it matters:** A consumer doing `from agent import agent_loop` should
  not pay for tokens. Logging API key prefixes "for debug" is also noise +
  a tiny security leak — let `Anthropic()` raise its own clear error if the
  env var is missing.
- **Reference:** `ms-learn-agent/agent.py`

#### 6. Imports in a flat Python project — execute as module

- **The thing:** `python script.py` puts the *script's directory* on
  `sys.path`, not the project root. To import sibling-of-root code from a
  script in `examples/`, run as a module from the root:

```bash
  python -m examples.run_advisor
```

- **Why it matters:** Avoids the junior anti-pattern of `sys.path.insert(...)`
  hacks at the top of every example file. The mechanism (where Python
  resolves modules from) is universal across languages — understand it
  once, save hours forever.
- **Reference:** `ms-learn-agent/examples/run_advisor.py`

#### 7. Property + backing attribute — never share names

- **The thing:** A `@property` named `__x` whose body checks
  `if self.__x is None` recurses infinitely (the read of `self.__x` re-enters
  the getter). Backing attributes get a different name, or use
  `functools.cached_property` and skip the manual cache entirely.
- **Why it matters:** Name mangling on `__double` is for inheritance
  protection, not for "more private than `_single`". Reach for it only when
  needed. For lazy expensive properties, `cached_property` is the modern
  idiom.

```python
  @cached_property
  def _modules_by_uid(self) -> dict[str, dict]:
      return {m["uid"]: m for m in self._get_catalog()["modules"]}
```

- **Reference:** `ms-learn-agent/ms_learn_client.py`,
  RecursionError debugging session

#### 8. Operator precedence — `in` binds tighter than `or`

- **The thing:** `level in module.get("levels") or []` evaluates as
  `(level in module.get("levels")) or []` — the `or []` is a useless dead
  branch and you get `TypeError` if `levels` is `None`. The defensive default
  must wrap the `.get()` itself:

```python
  level in (module.get("levels") or [])
```

- **Why it matters:** When you write defensive guards, the parentheses must
  cover the actual sub-expression you're protecting. Read out loud what your
  expression evaluates to — that's the operator precedence test.
- **Reference:** `ms-learn-agent/ms_learn_client.py::search_modules`

#### 9. `raise_for_status()` before `.json()`

- **The thing:** Order matters when handling HTTP responses. A 5xx with an
  HTML body crashes `.json()` with `JSONDecodeError` *before* you can raise
  the real HTTP error. Raise on status first, parse second.

```python
  response = httpx.get(url, timeout=30.0)
  response.raise_for_status()
  data = response.json()
```

- **Why it matters:** Error classification beats error obscuration. Your
  caller wants `HTTPStatusError`, not a confusing `JSONDecodeError` that
  hides the underlying 500.
- **Reference:** `ms-learn-agent/ms_learn_client.py::_load_catalog`

#### 10. Always set HTTP timeouts

- **The thing:** `httpx.get(url, timeout=30.0)`. Never call without an
  explicit timeout. Same rule for any HTTP client (`requests`, `aiohttp`,
  Node `fetch`).
- **Why it matters:** A hung connection without timeout will block your
  agent indefinitely. In an agent loop, a stuck tool call freezes the whole
  conversation. Timeouts are not optional.
- **Reference:** stack convention V3.4 — `httpx` over `requests`

#### 11. Mutation in-place vs return-new

- **The thing:** Python's mutating methods return `None`:
  - `list.sort()` → `None` (use `sorted(list)` for a new list)
  - `list.append()` → `None`
  - `dict.update()` → `None`
  - `set.add()` → `None`
- **Why it matters:** `return some_list.sort(...)` returns `None` to the
  caller. Silent. Easy to ship to prod. Memorize: **methods named after
  side effects return None; functions named after the result return the
  result.**
- **Reference:** `ms-learn-agent/ms_learn_client.py`,
  search returning `null` to the agent

#### 12. Negating a compound condition — flip the action too

- **The thing:** Going from "keep when X" to "skip when X" requires negating
  the condition **AND** keeping the right action verb. De Morgan's laws:
  - `not (A and B)` ≡ `(not A) or (not B)`
  - `not (A or B)` ≡ `(not A) and (not B)`

  Concretely:

```python
  # Skip if level filter is set and doesn't match
  if level is not None and level not in (module.get("levels") or []):
      continue
```

  Cannot be simplified to:

```python
  if level is None or level in (...):  # ← inverted: now skips when matching
      continue
```

- **Why it matters:** Flipping the condition without flipping the action
  inverts the program's behavior silently. The output is "wrong but
  plausible-looking" — the worst category of bug.
- **Reference:** `ms-learn-agent/ms_learn_client.py::search_modules`,
  agent returning beginner courses when intermediate was requested

#### 13. Filter-then-stop vs score-and-rank

- **The thing:** When ranking search results, never `break` early on the
  first N matches. You get the first N **in catalog order**, not the best N.
  Score everything, sort, then slice.
- **Why it matters:** Early termination only works if the iteration is
  already in priority order. A flat catalog is not. The score-and-rank
  shape is the universal search pipeline:
candidates → score-all → rank → top-K → project
- **Reference:** `ms-learn-agent/ms_learn_client.py::search_modules`

#### 14. Universal search pipeline shape

- **The thing:** Naive word-matching today, BM25 next, embeddings + cosine
  similarity at Sprint 3. The **shape** stays identical:
  1. Score every candidate against the query
  2. Sort by score descending
  3. Truncate to top-K
  4. Project to the fields the consumer needs
- **Why it matters:** This is also the RAG retrieval pipeline. Learning the
  shape on a flat catalog with naive scoring is the same mental model as
  retrieval over a vector store. The substitutability of the "score"
  function is the whole point.
- **Reference:** `ms-learn-agent/ms_learn_client.py`, anticipated for Sprint
  3 RAG work

#### 15. Tool descriptions are prompts

- **The thing:** Tool `description` and parameter `description` fields are
  injected into Claude's system prompt as part of the tool schema. Wordy,
  redundant, typo-laden descriptions waste tokens and confuse the model.
  Be terse and let the JSON Schema do its job:

```python
  "description": (
      "Search Microsoft Learn courses by query. Returns up to "
      "`max_results` courses (default 5). Optional `level` filter."
  )
```

  No need to spell out the enum values in prose if they're already in
  `enum: [...]`.

- **Why it matters:** Token cost on every call + model attention dilution.
  For a 3-tool agent it's marginal; for 20+ tools it compounds.
- **Reference:** `ms-learn-agent/tools.py::TOOLS`

#### 16. JSON Schema — `integer` vs `number`

- **The thing:** `"type": "number"` in JSON Schema accepts floats. For
  integer-only fields use `"type": "integer"`.
- **Why it matters:** With `"number"`, Claude may pass `3.0` and your
  Python code calling `range(3.0)` or `list[:3.0]` will crash. Schema is
  contract — make it match the runtime expectation.
- **Reference:** `ms-learn-agent/tools.py::TOOLS::search_ms_learn_courses`

---

### POC `agent_loop_minimal.py`

#### 17. Tool calls are optional by default

- **The thing:** Claude is not obligated to call a tool just because one is
  available. The default `tool_choice={"type": "auto"}` lets the model
  decide. For some prompts (e.g. "what's the weather in Tokyo"), Claude
  may answer from priors ("Tokyo is usually mild") and skip the tool
  entirely.
- **Why it matters:** A non-deterministic agent makes for flaky demos and
  invisible hallucinations. If a tool MUST be called, enforce it:
  - `tool_choice={"type": "any"}` — must call some tool
  - `tool_choice={"type": "tool", "name": "X"}` — must call tool X
  - Or write the system prompt to make the rule explicit
- **Reference:** `llm-engineering-patterns/manual-pocs/agent_loop_minimal.py`,
  observed run 3 of 3 where Claude skipped the weather tool entirely

#### 18. Tool use enforcement trial in tool descriptions

Tool descriptions describe the contract, not the implementation. Don't tell Claude "use your internal X tool" — Claude has only the tools you give it. The description is for selecting and parameterizing the tool, not for prescribing its inner workings.

#### 19. Env vars path resolving

Use Path(__file__).parent / "..." for files co-located with code (env files, config, fixtures). Use Path.cwd() / "..." only when you genuinely want "wherever the user invoked us from" semantics (rare, mostly for CLI tools). __file__-relative is the default for everything else.

NB: The `find_dotenv` method from the `dotenv` package could also be used like below but is not reliable if you have multiple files with the same name.
```python
from dotenv import find_dotenv
load_dotenv(find_dotenv(".env.local"), override=True)
``` 

## Open questions / parking lot

- Should the in-memory catalog be deduplicated by uid at load time, or only
  on-demand via `_modules_by_uid`? Duplicates in MS Learn API: not yet
  observed, not yet ruled out.
- Cache invalidation strategy beyond TTL: should we hash a small "version"
  endpoint to detect updates faster than 24h? Currently overkill.
- For `search_modules`, should we expose the score back to the agent (let
  Claude see relative match quality)? Pro: more info for ranking decisions.
  Con: surface area, harder to swap scoring later.
