---
id: SPEC-epic-1
companions: [../../../TRIAGE_POLICY.md, ../../../mcp/triage_server.py]
sources: [../../../INTENT.md]
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Epic 1: triage data and schema

## Why

The triage agent (Epic 2) and its eval (Epic 3) both need two things that don't exist yet: a single definition of what a valid triage decision is, and the seed tickets and customers in the `app.db` that `mcp/triage_server.py` already reads. Epic 1 lays that foundation so later epics build on a fixed contract and real data instead of guessing.

## Capabilities

- **CAP-1**
  - **intent:** Any triage decision can be checked against one schema: a category, a priority, a route and a one-sentence rationale.
  - **success:** A decision with category in {billing, bug, access, performance, how-to}, priority in {P1, P2, P3, P4}, route in {billing-team, bug-team, access-team, performance-team, how-to-team} and a rationale is accepted. Anything else — a missing field, an extra field, a wrong type, or a value outside those sets — is rejected with an error that names what is wrong.

- **CAP-2**
  - **intent:** One command, `uv run python load_seed.py`, loads `seed/tickets.csv` and `seed/customers.csv` into a local SQLite file, `app.db`.
  - **success:** After the command, `app.db` has a `tickets` table (24 rows) and a `customers` table (20 rows) with the same columns as the CSVs. T-1047's quoted, comma-containing text loads intact, and the `get_ticket` and `get_customer_history` queries in `mcp/triage_server.py` return rows from it.

- **CAP-3**
  - **intent:** Loading is repeatable.
  - **success:** Running `load_seed.py` twice in a row leaves identical `tickets` and `customers` contents, with no duplicated rows.

## Constraints

- Python 3.12 or newer, managed with uv.
- Files in `seed/` are read-only.
- No network calls and no API keys; everything in this epic runs offline.
- `mcp/triage_server.py` reads `app.db` as `tickets(ticket_id, customer_id, created_at, text)` and `customers(customer_id, name, plan, open_tickets)`; those table and column names must keep working.

## Non-goals

- The agent, the MCP tools, evals and any user interface.

## Success signal

On a fresh checkout, `uv run python load_seed.py` (run once or twice) produces an `app.db` that `mcp/triage_server.py` can serve T-1042 and customer C-77 from, and the schema accepts `billing` / `P2` / `billing-team` with a one-sentence rationale while rejecting a decision with priority `P5`.

## Assumptions

- `open_tickets` is stored as an integer so the policy's Enterprise rule (3 or more open tickets) compares numerically; other columns stay text.
- Epic 2 uses this schema as the agent's structured output, so it must be consumable that way.

## Open Questions

- Must `route` match `category` per `TRIAGE_POLICY.md`'s one-to-one table (billing → billing-team, etc.), or is any listed route accepted with any category?
- Is "one-sentence rationale" enforced as a non-empty string only, or by a check that rejects multi-sentence text?
