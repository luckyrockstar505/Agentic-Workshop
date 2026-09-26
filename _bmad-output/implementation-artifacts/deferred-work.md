# Deferred work

- source_spec: `_bmad-output/specs/spec-epic-1/stories/1-triage-decision-schema.md`
  summary: Epic 3's `eval/run_eval.py` cannot `import triage_schema`, because running a script in `eval/` puts `eval/` on sys.path[0] rather than the repo root.
  evidence: Confirmed by an import probe run from `eval/`, which raises ModuleNotFoundError. Story 1.1 solved the same problem for `tests/` via `tests/__init__.py`, but nothing covers `eval/`. Epic 3 must carry an explicit sys.path insertion, or the project needs a build backend so the root module is installed.

- source_spec: `_bmad-output/specs/spec-epic-1/stories/1-triage-decision-schema.md`
  summary: `_bmad-output/specs/spec-epic-1/SPEC.md` still lists both Open Questions as open, although story 1.1 records the human's answers.
  evidence: The route-vs-category and one-sentence-rationale questions were decided on 2026-09-26 and are frozen in the story spec, but the epic SPEC is the declared canonical contract Epic 2 and Epic 3 build from. AGENTS.md requires spec changes go through `/bmad-spec`, which is outside a bmad-build run.

- source_spec: `_bmad-output/specs/spec-epic-1/stories/1-triage-decision-schema.md`
  summary: `extra="forbid"` serializes to `additionalProperties: false`, which Gemini's responseSchema subset may drop or reject when Epic 2 uses TriageDecision as structured output.
  evidence: Unverified here -- Epic 1 makes no network calls and the agent does not exist yet. If the key is silently dropped, extra fields surface only at parse time and consume Epic 2 CAP-4's single retry; if the request is rejected outright, Epic 2 structured output breaks. Settled by one Gemini structured-output call once the agent exists, or by reading how langchain-google-genai sanitizes JSON schemas.
