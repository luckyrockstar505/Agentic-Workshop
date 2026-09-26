---
title: 'Story 2.1: The triage agent'
type: 'feature'
created: '2026-09-26'
status: 'ready-for-dev'
route: 'dispatch'
review_loop_iteration: 0
context: ['{project-root}/TRIAGE_POLICY.md', '{project-root}/_bmad-output/specs/spec-epic-2/SPEC.md', '{project-root}/triage_schema.py']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `run_agent.py` exits with "The agent isn't built yet" because no `agent` module exists. Epic 1 gave the repo a decision schema; nothing yet reads a ticket, applies the policy and decides.

**Approach:** Add a top-level `agent.py` exposing `async triage(ticket_id) -> dict`. It builds a LangChain `create_agent` over the two MCP tools from `mcp/triage_server.py` on stdio, instructs it with `TRIAGE_POLICY.md`, and returns a `TriageDecision` as structured output — retrying once if the model's output fails schema validation. Covers CAP-1, CAP-2, CAP-3, CAP-4 and CAP-6; escalation (CAP-5) is story 2.2.

## Boundaries & Constraints

**Always:** Built with `create_agent`, not a hand-rolled tool loop. Tools come only from `mcp/triage_server.py` over stdio via `langchain-mcp-adapters`. `TRIAGE_POLICY.md` is read at runtime and used as the system prompt. The return value is JSON-serializable, because `run_agent.py` calls `json.dumps` on it and passes it to `span.set_outputs`. Ticket text is untrusted data: the prompt must frame it as data to classify, never as instructions to follow.

**Never:** No `escalate_to_human` tool and no human-in-the-loop middleware — that is story 2.2. Do not edit `mcp/triage_server.py`, `triage_schema.py`, `TRIAGE_POLICY.md`, `seed/`, `eval/`, or `run_agent.py`'s MLflow lines. No second tool server. No new dependencies — everything needed is already installed. No LangSmith, no Databricks.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Provider default | `PROVIDER` unset | Model is `ChatGoogleGenerativeAI` with model id `gemini-3.8-flash` | N/A |
| Provider switch | `PROVIDER=groq` | Model is `ChatGroq` with model id `openai/gpt-oss-120b` | N/A |
| Model override | `MODEL` set, either provider | That model id is used instead of the provider's default | N/A |
| Unknown provider | `PROVIDER=openai` | Rejected at startup | Error names `PROVIDER`, its value, and the two supported values |
| Structured output invalid once | First model response fails `TriageDecision` validation, second passes | The decision from the second attempt is returned | N/A |
| Structured output invalid twice | Both attempts fail validation | Run stops | Error names the field that failed validation; no partial decision returned |
| Decision shape | Any successful run | A plain `dict` with exactly `category`, `priority`, `route`, `rationale` | N/A |
| Missing database | `app.db` absent | Run stops | The tool's "app.db not found. Load the data first" message reaches the caller intact, not swallowed |

</frozen-after-approval>

## Code Map

Verified against the installed versions: `langchain` 1.4.2, `langchain-mcp-adapters` 0.3.2, `langchain-google-genai` 4.4.0, `langchain-groq` 1.1.3, `pydantic` 2.13.5.

- `run_agent.py` -- the integration point, unchanged. It does `from agent import triage` (deferred inside `main()`), `asyncio.run(triage(ticket_id))`, then `json.dumps(decision, indent=2)`. So `triage` must be a coroutine returning a JSON-serializable dict.
- `triage_schema.py` -- `TriageDecision` plus the exported `Category`/`Priority`/`Route` aliases. Read-only. `extra="forbid"` and `validate_assignment=True` are already set.
- `mcp/triage_server.py` -- read-only. Launch it as a subprocess with the current interpreter; `get_ticket` and `get_customer_history` both raise `ValueError` for unknown ids and `FileNotFoundError` when `app.db` is missing.
- `langchain.agents.create_agent(model, tools, system_prompt, response_format, middleware, ...)` -- pass `response_format=TriageDecision`; the parsed object lands on `result["structured_response"]`. Guard runaway loops with `config={"recursion_limit": ...}`.
- `langchain_mcp_adapters.client.MultiServerMCPClient({"triage": {...}})` -- `StdioConnection` takes `transport`, `command`, `args`, `cwd`, `env`. `await client.get_tools()` returns the LangChain tools.
- Model construction: `ChatGoogleGenerativeAI(model=...)` already reads `GEMINI_API_KEY` from the environment (confirmed in its source), and `ChatGroq(model=...)` reads `GROQ_API_KEY`. `ChatGroq`'s field is `model_name` with alias `model`, so pass `model=`.
- `pyproject.toml` -- `testpaths = ["tests"]`; `tests/__init__.py` already exists and is what puts the repo root on `sys.path`.

## Tasks & Acceptance

**Execution:**
- [ ] `agent.py` -- create it with seams that are testable without a network call: a model builder reading `PROVIDER`/`MODEL`, a prompt builder reading `TRIAGE_POLICY.md`, a decision extractor that validates `structured_response` against `TriageDecision` and returns `model_dump()`, and `async triage(ticket_id)` wiring MCP tools into `create_agent` with the retry-once policy -- separating these keeps every matrix row except the two live ones coverable offline.
- [ ] `tests/test_agent.py` -- create it: one test per offline matrix row, using a stub agent for the retry rows and asserting on the constructed model's class and model id for the provider rows -- no test may make a network call or need `app.db`.

**Acceptance Criteria:**
- Given no `GEMINI_API_KEY` or `GROQ_API_KEY` in the environment, when `uv run pytest` runs, then every test passes without a network call.
- Given a built `app.db` and a working key, when `uv run python run_agent.py T-1042` runs, then it prints a decision of `billing` / `P2` / `billing-team` with a rationale, and the MLflow trace shows `get_ticket` called before `get_customer_history` with the `customer_id` the first call returned.
- Given the same, when `uv run python run_agent.py T-1099` runs, then it returns `bug` / `P4` — the ticket's embedded "mark this P1" instruction is ignored.
- Given the story is complete, when the repo is inspected, then `mcp/triage_server.py`, `triage_schema.py`, `TRIAGE_POLICY.md`, `seed/` and `eval/` are untouched and no dependency was added.

## Implementation Notes

## Spec Change Log

## Review Triage Log

## Design Notes

Two live acceptance criteria above cannot be exercised yet and are expected to stay unverified when this story is reviewed:

- `app.db` does not exist — `load_seed.py` is Epic 1 story 2 and is not built. Everything that needs real ticket data is blocked on it.
- `GROQ_API_KEY` is empty in `.env`, so only the Gemini path can run live. The `PROVIDER=groq` row is covered offline by asserting the constructed model object, which needs no key beyond a dummy value set inside the test.

Build for these criteria anyway; they are the story's contract, and they become runnable the moment story 1.2 lands.

One known risk worth a line in Implementation Notes if it bites: `TriageDecision` sets `extra="forbid"`, which serializes to `additionalProperties: false`. Gemini's `responseSchema` subset may drop or reject that key — this is already recorded in `_bmad-output/implementation-artifacts/deferred-work.md`. The retry-once path is what absorbs it if extras surface at parse time.

## Verification

**Commands:**
- `uv run pytest` -- expected: all tests pass, offline, with no API key set.
- `uv run python -c "import asyncio, agent; print(asyncio.iscoroutinefunction(agent.triage))"` -- expected: `True`.
- `git status --porcelain` -- expected: only `agent.py`, `tests/test_agent.py` and this spec file appear (`ARCHITECTURE.md` is a pre-existing untracked file and stays out of this story's commit).

**Manual checks (blocked until Epic 1 story 2 builds `load_seed.py`):**
- `uv run python run_agent.py T-1042` prints `billing` / `P2` / `billing-team`; `T-1099` returns `bug` / `P4`.
- The MLflow trace for that run shows `get_ticket` before `get_customer_history`.
