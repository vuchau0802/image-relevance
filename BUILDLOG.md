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

## Dataset delivery hardening

- Preserved the original 50 images and their registered checksums while
  preparing a separate dataset-v1 release asset.
- Used AI assistance for a standard-library downloader, checksum inventory,
  offline tests, and setup documentation. The user published the asset
  and verified both local and public download paths.
- A first download returned 404 because only GitHub's automatic source
  ZIP was available. Attaching the actual image ZIP resolved the issue.
- Full-suite database setup timeouts were resolved by waiting for the
  database container to become ready; the subsequent run passed 39 tests.
- The user staged removal of images from Git tracking; all 50 originals
  remain locally. Earlier Git history and the release tag remain unchanged.
- At this earlier checkpoint, other findings (dependencies, private SDK exception imports,
  persistence duplication, and isolated test setup) remain outstanding.

## Combined review fixes

- Used AI assistance to implement the requested review fixes in one change.
- Replaced private SDK exception imports with public exception-cause/status
  inspection, verified against the actual installed SDK's mocked transport.
- Centralized metadata upserts and path/checksum checks, bounded model output,
  and retained the separately documented synchronous retry demo utility.
- Added a durable ai_calls table and migration. Audit creation and budget
  reservation share a transaction; client construction happens afterward.
- Default tests now use fake credentials and skip marked database tests. Added
  a distinct disposable PostgreSQL service, guarded integration runner, and CI.
- Verified minimal dependency installation in a fresh virtual environment,
  pip consistency, 44 offline passes/17 explicit skips, all 61 integration-suite
  passes, and migration/model agreement. No paid or free Gemini calls were used.
- Added code licensing, a frontend placeholder, submission-manifest draft, and
  setup/architecture/limitations documentation. The brief was checked directly
  for required files and its prohibition on force-pushing published history.
- Preserved the dataset release, local originals, provenance corrections,
  original/reprocessing job history, and 50-image corpus classifications.
- Two dependency deprecation warnings remain; dependencies were not upgraded
  merely to suppress warnings. Final matching acceptance probes remain pending.

## Phase 4 evaluation and hardening

- Used AI assistance for the frozen-baseline loader, evaluation runner,
  synthetic tests, analysis, and documentation. The user edited files,
  ran PowerShell verification, and confirmed the labels by visual review.
- The assistant drafted 12 new queries and proposed labels after inspecting
  the existing corpus, without viewing those queries' ranking scores.
  This provenance is recorded; the set is not an independent benchmark.
- Froze labels, baseline implementation, embedding settings, and threshold
  0.85 before evaluation. Seeded and embedded only post text, excluding labels.
- The user ran the first evaluation: 9/12 cases passed. Kept both false
  rejections and the snowy-fox false acceptance in the preserved baseline report.
- Preserved the first JSON report and verified its hash against the original.
- Reviewed a 79-call embedding audit snapshot and the user's Free tier
  evidence. Kept unavailable token usage as unknown and distinguished the
  application's USD 0 estimate from actual provider billing.
- Earlier first-run checkpoint: 261 passed, two dependency warnings, in 7.28 seconds.
  Dependency consistency, migration agreement, and demo readiness passed.
- No final Phase 4 commit was created by the assistant. The user requested
  completion of the work before committing.

### Subsequent development pilot and verification

- Added versioned post requirements and image scene evidence, reviewed
  imports, and a separate context pilot command with AI assistance.
- The pilot rejected the snowy-fox mismatch. The original Beetle and
  scooter false rejections remain unresolved at threshold 0.85.
- Added eight vehicle development queries after corpus inspection; the
  user confirmed the labels and obtained 8/8 with the original ranker.
- Direct inspection established that img_028 is a boxy four-door sedan;
  an initially accepted Beetle correction was withdrawn before any
  classification or embedding change.
- Original baseline and first-run evidence were preserved. Inspected
  failures now inform development, not a new held-out accuracy claim.
- Latest user-run suite: 302 passed, two dependency warnings, in 8.89
  seconds. Dependency consistency, migration agreement, demo readiness,
  and the preserved report hash were verified by the user.
