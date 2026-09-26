---
title: 'Story 1.1: Triage-decision schema'
type: 'feature'
created: '2026-09-26'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '021f60f5cfd699babe04666e6e17eecd83e1cecd'
context: ['{project-root}/TRIAGE_POLICY.md', '{project-root}/_bmad-output/specs/spec-epic-1/SPEC.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Nothing in the repo defines what a valid triage decision is. Epic 2's agent needs a schema to emit as structured output and to retry against; Epic 3's `valid_schema` scorer needs the same definition to score against. Without it both epics guess.

**Approach:** Add one importable Pydantic v2 model, `TriageDecision`, in a new top-level `triage_schema.py`, carrying category, priority, route and rationale. Valid decisions parse; everything else raises a validation error that names the offending field and what is wrong with it.

## Boundaries & Constraints

**Always:** Pydantic v2 (`pydantic>=2.8`, already a dependency) so LangChain's structured output can consume the model directly. Field names are exactly `category`, `priority`, `route`, `rationale`. Category values are `billing`, `bug`, `access`, `performance`, `how-to`; priority `P1`–`P4`; route `billing-team`, `bug-team`, `access-team`, `performance-team`, `how-to-team` — matching `TRIAGE_POLICY.md`. Unknown fields are rejected, not ignored. Runs fully offline.

**Never:** No agent, no MCP tools, no `load_seed.py`, no eval — story 2 and Epics 2–3 own those. Do not edit `seed/`, `eval/labelled_tickets.csv`, `TRIAGE_POLICY.md` or `mcp/triage_server.py`. No new dependencies. No `app.db` or SQLite work in this story.

**Decided (human, 2026-09-26):** `route` is validated for membership in the route set only — a decision pairing `category: billing` with `route: bug-team` is accepted by the schema, and keeping the category→route table is the agent's job via `TRIAGE_POLICY.md`, not the schema's. `rationale` is validated as a non-empty string only — "one sentence" stays guidance in the agent's prompt and something Epic 3's judge weighs; no sentence-count check, so abbreviations never trip a false rejection.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Valid decision | `{category: billing, priority: P2, route: billing-team, rationale: "Double charge is money at stake."}` | Parses into a `TriageDecision`; fields readable and round-trip back to the same dict | N/A |
| Missing field | Same minus `route` | Rejected | Error names `route` as missing |
| Extra field | Valid decision plus `confidence: 0.9` | Rejected | Error names `confidence` as not permitted |
| Value outside set | `priority: P5` | Rejected | Error names `priority` and lists the allowed values |
| Unknown category | `category: refund` | Rejected | Error names `category` and lists the allowed values |
| Wrong type | `priority: 2` (int), `rationale: 5` | Rejected | Error names the field and the expected type |
| Empty rationale | `rationale: ""` or whitespace only | Rejected | Error names `rationale` as empty |

</frozen-after-approval>

## Code Map

- `mcp/triage_server.py` -- naming precedent (`triage_*` module, module-level docstring, type hints). Read-only in this story; the schema does not import it.
- `run_agent.py` -- shows how top-level modules are imported (`from agent import triage`), so `triage_schema.py` belongs at the repo root alongside it. Not changed here.
- `TRIAGE_POLICY.md` -- source of the category/priority/route vocabulary and the category→route table. Read-only.
- `pyproject.toml` -- `pydantic>=2.8` already present; `testpaths = ["tests"]`, and `tests/` does not exist yet, so this story creates it. No edit needed.
- `_bmad-output/specs/spec-epic-2/SPEC.md` -- CAP-4 consumes this model as LangChain structured output and retries once on validation failure; CAP-1 expects `billing`/`P2`/`billing-team` for T-1042.
- `_bmad-output/specs/spec-epic-3/SPEC.md` -- CAP-2's `valid_schema` scorer validates agent output against this model.

## Tasks & Acceptance

**Execution:**
- [x] `triage_schema.py` -- create it: module docstring, `Category`/`Priority`/`Route` value sets, and a `TriageDecision` Pydantic v2 model with `model_config = ConfigDict(extra="forbid")` and a validator rejecting a blank `rationale` -- one importable definition both later epics validate against.
- [x] `tests/test_triage_schema.py` -- create it with `tests/__init__.py` if imports need it: one test per I/O & Edge-Case Matrix row, asserting both rejection and that the error message names the offending field -- the matrix is the contract, so it is what gets tested.

**Acceptance Criteria:**
- Given a fresh checkout, when `uv run pytest` runs, then every test in `tests/test_triage_schema.py` passes and no other test breaks.
- Given `TriageDecision`, when Epic 2 passes it to LangChain as a structured-output schema, then it is accepted as a Pydantic v2 model with no wrapper — verified here by `TriageDecision.model_json_schema()` returning a schema whose `properties` are exactly the four fields.
- Given a rejected decision, when the raised `ValidationError` is stringified, then the text names the offending field, so a retrying agent can tell what to fix.
- Given the story is complete, when the repo is inspected, then `app.db`, `mcp/triage_server.py`, `seed/` and `eval/` are untouched.

## Implementation Notes

- `triage_schema.py` (repo root, alongside `run_agent.py`): `Category`, `Priority` and `Route` are `typing.Literal` aliases, so Pydantic inlines their allowed values into both the error text and `model_json_schema()` -- no enum classes and no `$defs`, which keeps the JSON schema's `properties` exactly the four fields for LangChain structured output.
- `extra="forbid"` via `ConfigDict` gives the "Extra inputs are not permitted" rejection with the offending key in the error `loc`.
- Blank `rationale` is caught by a `field_validator` rather than `min_length`, because whitespace-only text has non-zero length. The validator returns the value unchanged (no stripping) so a valid decision round-trips byte-for-byte.
- `tests/__init__.py` was needed: the project has no build backend, so it is not installed into the venv; making `tests` a package puts the repo root on `sys.path` and lets `from triage_schema import TriageDecision` resolve under `uv run pytest`.
- `validate_assignment=True` sits alongside `extra="forbid"` so a post-construction edit -- e.g. applying the policy's Enterprise priority bump -- is validated too, and `__all__` declares the three vocabulary aliases as exports so Epic 2's prompt and Epic 3's scorers reuse them instead of re-hardcoding the value lists.
- Tests also pin the two human decisions (membership-only `route`, no sentence-count check), the unstripped rationale round-trip, out-of-set `route`, explicit `null` per field, and a JSON round-trip, so a later change that tightened any of them would fail rather than pass silently.
- The empty-rationale row is parametrized over `""`, spaces and tabs/newlines, so 11 tests cover the 7 matrix rows plus the structured-output acceptance criterion.

## Spec Change Log

## Review Triage Log

| # | Finding (layer) | Verdict | Evidence | Route |
|---|---|---|---|---|
| 1 | Route/category independence unpinned by any test (verification-gap, blind) | medium | Pre-verified: a cross-field `model_validator` forcing `route == f"{category}-team"` survives the suite, 11 passed. Over-tightening would break Epic 2 structured output against a green suite. | patch |
| 2 | No sentence-count check on `rationale` unpinned (verification-gap) | medium | Pre-verified: a sentence-count rejection inside the validator survives the suite; every fixture rationale is a single sentence. Re-introduces exactly the false rejections the human decision ruled out. | patch |
| 3 | Byte-for-byte rationale round-trip unpinned (verification-gap, blind) | low | Pre-verified: `return value.strip()` survives the suite; the valid fixture rationale has no padding, so no assertion distinguishes the two. Filed defer, but caused by this change and the fix is one assertion in a test file already being touched. | patch |
| 4 | No test rejects an out-of-set `route` (edge-case) | low | Confirmed: no test supplies a bad route. `category` and `priority` sets ARE pinned -- their error-message assertions list every allowed value -- so `Route` is the one vocabulary a typo could corrupt undetected. | patch |
| 5 | Only billing/P2/billing-team ever constructed, so other members untested (edge-case) | low | Partly false: the category and priority error-message assertions already list every allowed value, so a typo there fails the suite. Confirmed by execution. Reduces to row 4 (route), same root cause. | patch (grouped with 4) |
| 6 | Field assignment is unvalidated (edge-case) | medium | Confirmed by execution: `d.priority = "P9"` is accepted and sticks. Epic 2 applying the policy Enterprise bump by assignment would bypass validation entirely. Fix is `validate_assignment=True` on the existing `ConfigDict`; `frozen=True` is not adopted -- it removes capability nothing asked to remove. | patch |
| 7 | Vocabularies not declared as exports, so Epic 2/3 will re-hardcode them (blind) | medium | Confirmed: no `__all__`, and neither the docstring nor the story names the aliases as reusable. Duplicated vocabulary across epics is the exact defect this module exists to prevent. | patch |
| 8 | No explicit-null coverage (blind) | low | Confirmed by execution: `None` is correctly rejected on `category`, `route` and `rationale`, each naming the field -- behavior is right, only the test is missing. Null is a common structured-output failure mode and the test is one parametrized case. | patch |
| 9 | No JSON round-trip test (blind) | low | Confirmed: `model_validate_json`/`model_dump_json` round-trips correctly but is untested; Epic 3 `valid_schema` scorer plausibly receives a JSON string rather than a dict. | patch |
| 10 | `eval/run_eval.py` will not be able to `import triage_schema` (blind) | medium | Confirmed: running a script in `eval/` puts `eval/` on `sys.path[0]`, not the repo root. Real, but Epic 3 code must carry the fix and no trivial in-story change resolves it. | defer |
| 11 | Epic 1 `SPEC.md` still lists both Open Questions as open (blind) | medium | Confirmed: the story frozen block answers both, but the canonical epic contract does not. AGENTS.md requires spec changes go through `/bmad-spec`, which is outside this build. | defer |
| 12 | `additionalProperties: false` may break Gemini `responseSchema` (blind) | maybe-false | Cannot settle here: this epic makes no network calls and the agent does not exist yet. If the key is dropped, extras surface at parse time and Epic 2 retry absorbs it; if the request is rejected outright, Epic 2 breaks. Settled by one Gemini structured-output call, or by reading the langchain-google-genai schema sanitizer. | defer |
| 13 | Zero-width-only rationale passes (edge-case) | low | Confirmed by execution: a zero-width-space string survives `.strip()` and is accepted. Rejected: a model emitting only zero-width characters is not an everyday case, and the fix adds a printable-character guard. | rejected |
| 14 | No `max_length` on `rationale` (edge-case, blind) | low | Real but unlikely: structured output is token-bounded, so a multi-megabyte rationale is not an everyday case, and the fix adds a constraint parameter. | rejected |
| 15 | No per-field `Field(description=...)` (blind) | low | Real, but `TRIAGE_POLICY.md` is the agent prompt in Epic 2 and already carries the one-sentence-rationale instruction. The fix adds parameters for guidance the model already receives. | rejected |
| 16 | Code Map misdescribes `run_agent.py` import (blind) | low | Confirmed accurate: the import is deferred inside `main()` in a `try/except ImportError`, not module-level. The conclusion drawn from it (root-level placement) still holds. Rejected because the fix edits this build's spec. | rejected |
| 17 | `tests/__init__.py` couples collection to pytest prepend import mode (blind) | low | Confirmed: it works today only because prepend inserts the first non-package ancestor. No everyday path changes the import mode, and the alternative fix restructures the mechanism and contradicts this story's diff-scope acceptance criterion. | rejected |

## Verification

**Commands:**
- `uv run pytest` -- expected: all tests pass, collected from `tests/`.
- `uv run python -c "from triage_schema import TriageDecision; print(TriageDecision(category='billing', priority='P2', route='billing-team', rationale='Double charge is money at stake.'))"` -- expected: prints the decision, no error.
- `git status --porcelain` -- expected: only `triage_schema.py`, `tests/` and this spec file appear.
