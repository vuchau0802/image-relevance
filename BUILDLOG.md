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
- At that earlier stage, background jobs, controlled retries, database persistence, embeddings, matching, review APIs, and a budget guard were future work; later progress is recorded below.

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
At that earlier checkpoint, the corpus processing job was unfinished.

## Phase 2 corpus completion and review

- Added a shared PostgreSQL daily call counter, concurrent-reservation
  and blocked-worker tests, and a tenant-scoped job-status endpoint.
- Corrected SDK retry configuration to attempts=0 after inspecting the
  installed Interactions SDK; earlier attempts=1 allowed an extra retry.
- Investigated password authentication failures. Recreating the database
  container restored host connectivity without removing its data volume.
- Switched vision processing to gemini-3.5-flash-lite and explicitly
  increased the local daily allowance from 20 to 40. Earlier results keep
  their recorded model, and existing reservations remain counted.
- Finished the original job with 47 completed items and 2 failed items.
- Added failed-image reprocessing and regression tests. The new job
  completed img_024 and img_026 while preserving their original failures.
- Verified 50 completed corpus images and 50 metadata records.
- During targeted visual review, found img_037/img_038 provenance was
  swapped and post_009 pointed at the wrong image. The earlier Phase 1
  review note did not establish that every pairing was correct.
- Corrected the manifest and evaluation reference, then synchronized
  the two database provenance records after checksum verification.
- Latest user-run validation: 34 tests passed, 2 dependency warnings.
- Used AI assistance for the code, tests, diagnostics, documentation,
  and targeted image review; the user ran PowerShell and verified results.
- Matching accuracy, calibrated confidence, and broad visual review are
  not established. img_006's species identification remains unconfirmed.
