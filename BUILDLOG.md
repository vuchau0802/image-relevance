## Phase 1 — Design and dataset
- Selected Python/FastAPI and PostgreSQL for the backend.
- Planned a React/TypeScript frontend.
- Defined image metadata, database tables, API endpoints,
  background processing, and mismatch-guard rules.
- Created a 50-entry image manifest with source, creator,
  and license information.
- Created 11 sample articles.
- Added 10 proposed image pairings and one no-match case.
- Validated JSON and confirmed all evaluation references exist.
- Used AI assistance for planning, provenance lookup,
  example articles, and validation commands.
- Visually reviewed the 10 labeled image/article pairings.
## Phase 2 — Backend foundation and first vision call

- Created a Python virtual environment and installed backend dependencies; `pip check` reported no broken requirements.
- Started FastAPI and verified that `GET /health` returns HTTP 200 with `{"status":"ok"}` through the interactive API documentation.
- Defined a Pydantic image metadata schema that rejects malformed responses.
- Added confidence decisions that flag classifications below the configured threshold for review; all 11 schema and decision tests passed.
- Configured Gemini using environment variables and confirmed that `.env` is ignored by Git. The API key is not included in this log.
- Processed `img_001.jpg` with `gemini-3.8-flash`; the validated result identified a red fox and was saved to `data/processed/img_001.json`.
- Inspected the call log: 1,201 input tokens, 106 output tokens, completed status, and a $0 free-tier cost estimate attributed to `img_001`.
- Recorded the actual outputs in `EVIDENCE.md`. Confidence calibration and evaluation accuracy are still pending.

### AI assistance and corrections

- Used AI assistance to draft the FastAPI endpoint, metadata schema, confidence service, tests, settings loader, and single-image processing code.
- Ran the supplied commands and inspected their outputs during implementation.
- Corrected the initial Git setup after commands were run in a folder without a Git repository; initialized the existing project folder and connected it to GitHub.
- Replaced missing image provenance with individual photo-page URLs and verified creator/license details. Supplied page text for sources the assistant could not retrieve.
- Background jobs, controlled retries, database persistence, embeddings, matching, review APIs, and a budget guard remain future work.

## Background worker progress

Added persistent jobs and job items, idempotent job creation,
claim tokens, expiring leases, completion, and retry scheduling.

Used AI assistance to develop the implementation and recovery tests.
Corrected timeout classification after a real APITimeoutError was
initially treated as permanent. A targeted repair preserved the
attempt count, and the next attempt succeeded.

Verified automatic retries separately: img_003 completed on its third
attempt after two InternalServerError responses.

Added --max-items to limit attempts per worker invocation. A two-item
run completed img_004 and rescheduled img_005 after an API error.

Validation: 23 tests passed, including four database integration tests.
The corpus processing job remains unfinished.