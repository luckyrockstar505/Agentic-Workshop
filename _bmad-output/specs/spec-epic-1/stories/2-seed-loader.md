---
title: 'Story 1.2: Seed loader'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '3abebe19b5639586b7eb54e629109f4da8f7f65d'
context: ['{project-root}/_bmad-output/specs/spec-epic-1/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `mcp/triage_server.py` reads an `app.db` that nothing creates, so every tool call fails with "app.db not found. Load the data first". Epic 2's agent and Epic 3's eval both need real ticket and customer data before they can run at all.

**Approach:** Add `load_seed.py` at the repo root. One command, `uv run python load_seed.py`, reads the two read-only CSVs in `seed/` and writes them into `app.db` as the `tickets` and `customers` tables, using the exact column names the MCP server queries. Re-running it leaves the database identical, with no duplicate rows.

## Boundaries & Constraints

**Always:** Table and column names stay exactly `tickets(ticket_id, customer_id, created_at, text)` and `customers(customer_id, name, plan, open_tickets)`, because `mcp/triage_server.py` selects those by name. `open_tickets` is stored as an integer so the policy's Enterprise rule (3 or more open tickets) compares numerically; the other columns stay text. `app.db` lives at the repo root, where the MCP server looks for it. Seed paths resolve from the script's own location, so the command works from any working directory. Everything runs offline — no network, no API key.

**Never:** Do not write to, move or reformat anything under `seed/` — those files are read-only inputs. Do not edit `mcp/triage_server.py` or `triage_schema.py`. No new dependencies; Python's standard `csv` and `sqlite3` are enough. No agent, no MCP tools, no eval — those are Epic 2 and Epic 3. Do not commit `app.db`; it is already gitignored.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh load | No `app.db` | Creates it with 24 `tickets` rows and 20 `customers` rows, columns named as above | N/A |
| Re-run | `app.db` already loaded | Contents are byte-identical to the first run: still 24 and 20 rows, no duplicates | N/A |
| Quoted comma | The `T-1047` row, whose text is quoted and contains a comma | Stored as `Refund the duplicate charge, please.` — one field, comma intact, no quotes | N/A |
| Numeric comparison | Any customer row | `open_tickets` is an integer, so `SELECT ... WHERE open_tickets >= 3` matches the four Enterprise customers at or above the threshold | N/A |
| Server can read it | After a load | `get_ticket('T-1042')` returns customer `C-77`, and `get_customer_history('C-77')` returns plan `Enterprise` with its ticket ids | N/A |
| Missing seed file | `seed/tickets.csv` absent | Stops without creating a half-loaded database | Error names the missing file path |
| Run from elsewhere | Invoked with a different working directory | Loads the same data into the same `app.db` at the repo root | N/A |

</frozen-after-approval>

## Code Map

- `mcp/triage_server.py` -- read-only; the consumer this story exists to satisfy. It resolves `DB_PATH` as `parent.parent / "app.db"` (repo root) and selects the exact column lists above. Its `_query` raises `FileNotFoundError` when `app.db` is missing.
- `seed/tickets.csv` -- read-only. 24 rows, header `ticket_id,customer_id,created_at,text`. Verified: ids unique, no empty cells, `T-1047`'s text is the only quoted field and it parses correctly with the stdlib `csv` module.
- `seed/customers.csv` -- read-only. 20 rows, header `customer_id,name,plan,open_tickets`. Verified: ids unique, `plan` is one of Starter/Team/Enterprise, `open_tickets` values are all digits 0–4, and every `customer_id` referenced by a ticket exists here.
- `_bmad-output/specs/spec-epic-1/stories/1-triage-decision-schema.md` -- the previous story in this epic, `done`. Its conventions carry over: modules live at the repo root, and `tests/__init__.py` already exists and is what puts the repo root on `sys.path` for `uv run pytest`.
- `.gitignore` -- already lists `app.db`; no change needed.
- `pyproject.toml` -- `testpaths = ["tests"]`; no change needed, and no dependency to add.

## Tasks & Acceptance

**Execution:**
- [x] `load_seed.py` -- create it: resolve `seed/` and `app.db` from the script's own path, read both CSVs with the stdlib `csv` reader, recreate the two tables so a re-run cannot duplicate or leave stale rows, insert with `open_tickets` cast to `int`, and print a one-line summary of what was loaded -- recreating rather than upserting is what makes CAP-3's "run it twice, same database" true by construction.
- [x] `tests/test_load_seed.py` -- create it: one test per I/O & Edge-Case Matrix row, each against a temporary database rather than the repo's `app.db`, including a test that runs the load twice and compares full table contents -- the matrix is the contract, so it is what gets tested.

**Acceptance Criteria:**
- Given a fresh checkout with no `app.db`, when `uv run python load_seed.py` runs twice in a row, then it succeeds both times and the database holds exactly 24 tickets and 20 customers afterwards.
- Given a loaded `app.db`, when `mcp/triage_server.py`'s `get_ticket` and `get_customer_history` queries run against it, then `T-1042` resolves to customer `C-77` and `C-77` resolves to Northwind / Enterprise / 2 open tickets.
- Given the load is complete, when `uv run pytest` runs, then every test passes and story 1.1's tests still pass.
- Given the story is complete, when the repo is inspected, then `seed/`, `mcp/triage_server.py`, `triage_schema.py` and `eval/` are untouched, no dependency was added, and `app.db` is untracked.

## Implementation Notes

- Both CSVs are read and fully validated before any database work begins. Validation covers the header (missing columns), empty cells, duplicate ids, a header-only file, and a non-numeric `open_tickets`; each raises a `ValueError` naming the file and the offending id, so bad seed data never reaches sqlite3 as a raw `NOT NULL`/`UNIQUE` constraint error. Files are opened `utf-8-sig` so a BOM cannot make the first column look absent.
- The database is built in a scratch file beside the target and moved over it with `os.replace`. `mcp/triage_server.py`'s `_query` guards only on `app.db` existing, so a half-built file would turn its "load the data first" message into a bare "no such table"; with the move, the target only ever holds a complete database and a failure leaves any previous one untouched.
- Because every run builds a brand-new file, a re-run cannot duplicate rows or keep stale ones -- that is what makes CAP-3 true by construction. `ticket_id`/`customer_id` are `TEXT PRIMARY KEY` and `open_tickets` is `INTEGER`; column names and order are exactly what the server selects.
- `main()` catches `FileNotFoundError`, `ValueError` and `sqlite3.Error`, printing `Seed load failed: ...` to stderr and exiting 1 rather than showing a traceback.
- `load_seed(db_path, seed_dir)` takes both paths as arguments, defaulting to the repo root, which is how the tests stay off the developer's real `app.db`. An autouse fixture asserts the real `app.db`'s existence and mtime are unchanged by every test.
- The "server can read it" test imports `mcp/triage_server.py` via `importlib.util.spec_from_file_location` and monkeypatches its `DB_PATH`, then calls `get_ticket`/`get_customer_history` directly -- transcribing its SQL into the test would let the copies drift with the loader while the real server broke.

## Spec Change Log

## Review Triage Log

| # | Finding (layer) | Verdict | Evidence | Route |
|---|---|---|---|---|
| 1 | Validation stops at the header: short rows, duplicate ids and header-only files all escape (blind, edge, vg-other) | medium | Confirmed by execution. Short row -> `sqlite3.IntegrityError: NOT NULL constraint failed`, uncaught by main's `except (FileNotFoundError, ValueError)`, so a raw traceback and no file named. Duplicate ticket_id -> `UNIQUE constraint failed`, same path. Header-only tickets.csv -> exit 0 printing 'Loaded 0 tickets', silently leaving an empty table. The module docstring promises a malformed file 'stops the run with an error naming the file'. | patch |
| 2 | A post-connect failure leaves a 0-byte app.db, degrading the MCP server's error (blind, edge) | medium | Confirmed twice over: both failure scenarios above left `app.db` present at 0 bytes with no tables. Then confirmed the consequence directly -- with a 0-byte app.db, `triage_server.get_ticket` raises `OperationalError: no such table: tickets` instead of its intended 'app.db not found. Load the data first', because `_query` guards only on `DB_PATH.exists()`. | patch |
| 3 | The atomic-reload property is entirely unpinned (verification-gap) | medium | Pre-verified by mutation: deleting BEGIN/COMMIT and replacing ROLLBACK with `pass` leaves 9 passed. Every failure-path test raises before `sqlite3.connect`, so no test ever enters the transaction. The one property Implementation Notes calls out is untested. | patch |
| 4 | AC-2 is verified against hand-copied SQL, never against mcp/triage_server.py (verification-gap) | medium | Confirmed: no test imports the server; the test executes transcribed SQL constants living in the same file as the code under test. I independently proved a file-path import works and returns real rows, which removes the story's stated reason for copying. | patch |
| 5 | `test_the_repos_own_database_is_never_touched_by_the_defaults` cannot fail (verification-gap, blind, edge) | medium | Confirmed by inspection: `SEED_DIR = ROOT/'seed'` and `DB_PATH = ROOT/'app.db'`, so `DB_PATH.parent == SEED_DIR.parent` is true by construction whatever ROOT is. It observes no call and no file, so it cannot detect a test that rebuilds the developer's real app.db -- the exact property its docstring claims to protect. | patch |
| 6 | main()'s failure exit path has no test (verification-gap, blind) | medium | Pre-verified: deleting main's whole try/except leaves 9 passed. The only CLI test asserts `returncode == 0`. Nothing pins exit 1 or the 'Seed load failed:' stderr line, which is what a chained `load_seed.py && ...` step gates on. | patch |
| 7 | `test_second_run_leaves_identical_contents` does not test stale-row removal (blind) | low | Confirmed by inspection: it loads the same valid seed twice and compares dumps, which passes equally against an upsert implementation. The stale-row risk that drop-and-recreate exists to eliminate is never exercised. | patch |
| 8 | A UTF-8 BOM makes a valid seed file fail with a misleading error (blind, edge) | low | Confirmed by execution: prepending a BOM yields `missing the column(s) ticket_id` -- naming a column plainly present in the file. Trigger requires re-saving a read-only seed file, so it is unlikely here, but the fix is a one-word change to `utf-8-sig` and strictly better. | patch |
| 9 | Test helpers leak sqlite connections (blind, edge, vg-other) | low | Confirmed: sqlite3's context manager commits but does not close -- the connection is still usable after the `with` block. I then hit the predicted consequence for real: `PermissionError: [WinError 32] ... used by another process` when unlinking a temp db with an open handle. On Windows this can break pytest tmp_path cleanup. | patch |
| 10 | `ROLLBACK` in the except handler can mask the original error (blind, edge) | low | Confirmed by execution: `ROLLBACK` with no active transaction raises `OperationalError: cannot rollback - no transaction is active`, which would replace the real cause. `conn.close()` in the finally already rolls back. | patch |
| 11 | Both ValueError validation branches are untested (blind) | low | Confirmed: no test references ValueError, the missing-column message, or the non-numeric open_tickets message -- the latter being the error tied to the policy's '3 or more' rule. | patch |
| 12 | Test robustness nits: unordered SQL asserted in order, subprocess without timeout, loose type annotation (edge, blind) | low | Confirmed by inspection: the ticket_ids assertion depends on unspecified SQLite row order; `subprocess.run` has no timeout, so a hung child blocks the suite indefinitely; `_ticket_rows` is annotated `tuple[str, str, str, str]` but a generator `tuple(...)` yields `tuple[str, ...]`. Each fix is a direct correction. | patch |
| 13 | No referential-integrity check between tickets and customers (blind) | low | Real but rejected: I verified every ticket's customer_id already exists in customers.csv, and `seed/` is read-only by project rule, so no demonstrated path reaches a dangling id. The fix adds a guard for state never shown reachable. | rejected |
| 14 | No guard against a negative open_tickets value (edge) | low | Real but rejected: verified all 20 values are digits 0-4 in a read-only file. Same reasoning as row 13 -- a guard for unreachable state. | rejected |
| 15 | Subprocess test asserts a literal count string instead of composing from EXPECTED_* constants (blind) | low | Confirmed but rejected as cosmetic: the literal and the constants cannot drift apart without the rest of the suite failing first, and nothing about the defect reaches a user or developer in everyday use. | rejected |

## Design Notes

Tests must not depend on the repo's real `app.db` — a developer running the suite should never have their database rebuilt as a side effect, and CI has no `app.db` at all. Point the loader at a temp path in tests, and let the two real-database checks live in the Verification commands instead.

## Verification

**Commands:**
- `uv run python load_seed.py && uv run python load_seed.py` -- expected: succeeds twice, reporting 24 tickets and 20 customers each time.
- `uv run python -c "import sqlite3; c=sqlite3.connect('app.db'); print(c.execute('SELECT COUNT(*) FROM tickets').fetchone()[0], c.execute('SELECT COUNT(*) FROM customers').fetchone()[0], c.execute(\"SELECT text FROM tickets WHERE ticket_id='T-1047'\").fetchone()[0])"` -- expected: `24 20 Refund the duplicate charge, please.`
- `uv run pytest` -- expected: all tests pass, story 1.1's included.
- `git status --porcelain` -- expected: `app.db` does not appear; only `load_seed.py`, `tests/test_load_seed.py` and this spec file are new to this story.
