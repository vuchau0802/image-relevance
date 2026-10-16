# Evidence

These results were captured from the local development run. They demonstrate the implemented features below; they do not yet prove completion of the full capstone.

## Phase 1: dataset and evaluation references

The dataset checks reported:

```text
Manifest entries: 50
Missing files: 0
```

The manifest check found no missing source, creator, or license fields. The evaluation-reference check reported 11 entries, with every `PostExists` and `ImageReferenceValid` value equal to `True`. These checks establish file presence and reference validity, not matching accuracy or image classification quality.

## Phase 2: API health endpoint

Request:

```http
GET http://127.0.0.1:8000/health
```

Observed response: HTTP 200.

```json
{
  "status": "ok"
}
```

## Phase 2: schema validation and confidence decisions

Command run from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q
```

Actual output:

```text
...........                                                                                                      [100%]
11 passed in 0.11s
```

The tests cover valid metadata, invalid confidence values, blank subjects, unsupported categories, unexpected fields, missing captions, low-confidence review status, the threshold boundary, and invalid thresholds. Low-confidence behavior has been demonstrated with test data; a real low-confidence corpus result has not yet been demonstrated.

## Phase 2: single-image vision processing

Command run from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m scripts.process_one
```

Actual output:

```text
{
  "status": "completed",
  "metadata": {
    "subject": "red fox",
    "category": "animal",
    "attributes": [
      "reddish-orange fur",
      "white chest and throat",
      "black legs",
      "bushy tail",
      "erect triangular ears",
      "standing on wet asphalt"
    ],
    "caption": "A red fox stands on a wet asphalt road looking forward towards the camera.",
    "confidence": 0.99
  },
  "reason": "Classification meets the confidence threshold."
}
Saved result: E:\Internship\FlyRank\image-relevance\data\processed\img_001.json
```

The result passed Pydantic validation and the configured confidence threshold of 0.70. The confidence value is model-reported and has not been calibrated against the evaluation dataset.

## Phase 2: per-call usage and cost record

Command run from `backend/`:

```powershell
Get-Content "..\data\ai_calls.jsonl" -Tail 1
```

Actual record:

```json
{"call_id": "5cabd189-9f8d-4133-8419-3642f82682cf", "timestamp": "2026-10-11T02:37:27.924222+00:00", "tenant_id": "demo", "image_id": "img_001", "operation": "vision", "model": "gemini-3.8-flash", "status": "completed", "input_tokens": 1201, "output_tokens": 106, "estimated_cost_usd": 0.0, "cost_basis": "Configured free-tier project"}
```

This records one successful vision call attributed to `img_001`: 1,201 input tokens and 106 output tokens. The $0 cost is the application's free-tier estimate, not an independently verified billing statement. The timestamp above is preserved in UTC.

## Phase 2: secret-file exclusion

Command run from `backend/`:

```powershell
git check-ignore ../.env
```

Actual output:

```text
../.env
```

## Remaining evidence

Full-corpus processing and the targeted provenance/evaluation correction are now verified. Remaining evidence includes broader visual result review, broader tenant-isolation checks and authentication, stored image/post embeddings, ranked matching, subject-mismatch rejection, no-confident-match behavior, review endpoints, and measured evaluation results. Concurrent reservation enforcement and blocked-worker behavior have now passed automated tests. Background jobs, retries, idempotent job creation, migrations, and initial budget checks are documented below.

## Persistent jobs, retries, and bounded processing

- Created a processing job containing 49 images; img_001 had already
  been processed separately.
- Repeating job creation with the same tenant and idempotency key
  returned the same job ID. The database contained one matching job.
- Job ID: df3a71f3-9d5a-499e-b872-f21ca62b45da.
- img_002 completed on attempt 2 after a timeout and a targeted repair
  following correction of timeout classification.
- img_003 was automatically rescheduled after two InternalServerError
  failures and completed on attempt 3. Its last_error was cleared.
- Running the worker with --max-items 2 attempted img_004 and img_005.
  img_004 completed; img_005 encountered InternalServerError and was
  rescheduled. The worker stopped after the unsuccessful attempt.
- img_005 completed on attempt 2 after an InternalServerError.
- Earlier job snapshot (before subsequent batches): 49 total, 6 completed, 43 pending,
  0 processing, 0 needs_review, and 0 failed.
- At that earlier snapshot, including img_001 processed separately, 7 corpus images had completed processing. These counts do not establish classification accuracy.
- AI call logs include image ID, job ID, attempt, status, and token
  usage when returned. Failed calls had no reported token counts.

### Earlier automated validation

Command:
python -m pytest tests -q

Result: 23 passed, 1 Google SDK deprecation warning.

Four database integration tests cover expired-claim recovery,
final-attempt lease exhaustion, completion with duplicate-completion
rejection, and rejection of a claim under a different tenant.

### Remaining work

At this earlier stage the batch was unfinished. Full-corpus processing has since been verified in the latest snapshot; broader visual review, embeddings, matching, and evaluation remain outstanding. Concurrent reservation enforcement and budget-block claim release are verified in the later test section below.

## Daily vision call guard

- Added a PostgreSQL counter per tenant and UTC date.
- Four integration tests verify limit enforcement, zero allowance,
  separate tenant allowances, and lowering a limit below existing usage.
- At this earlier stage, the full test suite reported 27 passed and 1 Google SDK deprecation warning.
- A worker run with VISION_DAILY_CALL_LIMIT=0 added no AI-call records.
- img_006 remained pending with attempts=0 and no claim token or lease.
- Job counts remained unchanged: 4 completed, 45 pending, 0 failed.
- Calls made before guard activation have not been backfilled.
- Concurrency had not been tested at this stage; the later concurrent reservation test passed.

## Guarded batch results and classification review

- With the normal daily limit restored to 20, a two-item run completed
  img_006 and img_007 on attempt 1.
- The PostgreSQL counter for tenant demo and UTC date 2026-10-11 showed
  2 reserved calls after that run. Later counter observations are recorded
  below; this value is historical.
- img_006 was stored with subject coyote and model-reported confidence
  0.95. Its caption was: "A coyote stands on a pine needle-covered ground
  at the edge of a forest, looking directly at the camera."
- img_006 was collected from a page describing a wolf. Its actual species
  requires visual review; neither the page description nor the model
  prediction establishes ground truth. Its stored completed status means
  validation and the confidence threshold passed, not verified accuracy.
- img_007 completed with subject grey wolf.
- A subsequent run with --max-items 5 claimed img_008 on attempt 1.
  The attempt encountered APITimeoutError, and the worker stopped after
  one claim. The job summary continued to show 6 completed, 43 pending,
  0 processing, 0 needs_review, and 0 failed.
- The timeout was rescheduled rather than counted as a permanent failure.
  A subsequent attempt 2 encountered RateLimitError. Attempt 3 later
  completed with subject gray wolf, and its last_error was cleared.
- Tests at that earlier stage reported 27 passed and 1 SDK deprecation
  warning; the latest full suite result is recorded below.

## Interrupted worker recovery

- img_023 received a 429 response; the worker was interrupted during
  the SDK retry wait.
- Expired-claim recovery reported: requeued=1, failed=0.
- After recovery, img_023 was pending with attempts=1, no lease,
  and last_error="Worker lease expired before completion".
- The local counter showed 17 reservations for UTC date 2026-10-13.
- Disabled SDK retries using HttpRetryOptions(attempts=0), leaving
  retry scheduling to the persistent worker.
- Earlier reservations may include additional SDK HTTP retries.
- Validation after the change: 27 passed, 1 SDK deprecation warning.

## Concurrent budget and blocked-worker validation

- Four concurrent reservation requests with a daily limit of two
  produced two successes and two budget blocks.
- The stored reservation count remained two.
- A worker budget-block test preserved the previous attempt count
  and error, returned the image to pending, and cleared claim ownership.
- No Gemini request, AI-call log entry, or metadata record was created
  by the blocked operation.
- Targeted tests: 6 passed, 1 SDK deprecation warning.
- Full suite: 29 passed, 1 SDK deprecation warning.

## Job-status API

- GET /jobs/{job_id} returned the demo tenant's persisted job summary.
- Requesting the same job with X-Tenant-ID: different-tenant returned
  HTTP 404 with {"detail":"Job not found"}.
- Omitting X-Tenant-ID returned HTTP 422 for the missing header.
- Three automated endpoint tests passed.
- Full suite: 32 passed, 2 dependency deprecation warnings.
- The tenant header scopes lookups but is caller-controlled.
  Authentication is still required before deployment.



## Latest processing snapshot

Based on worker output and database queries supplied by the user:

- All 50 demo images have status completed.
- image_metadata contains 50 records for tenant demo.
- Original job df3a71f3-9d5a-499e-b872-f21ca62b45da finished as
  completed_with_errors: 49 total, 47 completed, 2 failed,
  0 pending, 0 processing, and 0 needs_review.
- Reprocessing job b7636238-50ba-46a7-b8a2-caa218d418c5 finished as
  completed: 2 total, 2 completed, 0 failed, and 0 pending.
- img_024 completed as Vespa scooter and img_026 as truck on attempt 1
  in the reprocessing job. Each original job item remains failed with
  attempts=3; each new item is completed with attempts=1.
- Creating the reprocessing job twice returned the same job ID.
- Earlier corpus-checkpoint full suite: 34 passed, 2 dependency deprecation
  warnings, in 1.80 seconds after provenance synchronization.
- Completed status establishes schema/threshold acceptance, not verified
  classification accuracy or calibrated model confidence.
- Earlier usage-counter observations are historical. The configured
  daily allowance was increased from 20 to 40; model changes and limit
  changes preserve existing reservations.

## Budget and logging limitations

- The application limits reservations per tenant and UTC day, not dollar
  spending. A $0 free-tier estimate is not a verified billing total.
- This allowance is separate from Google's project-wide rate limits.
- Pre-guard calls were not backfilled; earlier SDK retries could make
  multiple HTTP requests under one reservation.
- SDK retries are now configured with attempts=0. Interrupted requests
  retain their reservation and processing attempt; expired leases require
  recovery. A reserved call may not reach the provider if a process crashes.
- At the earlier checkpoint, logs were local JSONL records, not stored in PostgreSQL, and
  are not a crash-proof per-HTTP-request audit trail.
- Retry scheduling does not yet use provider Retry-After headers or
  distinguish daily quota exhaustion from shorter rate-limit windows.
- Concurrent reservation and blocked-worker tests do not establish
  provider quota availability, calibrated confidence, or classification
  correctness. Full-corpus processing is now verified; these implementation limitations and the unconfirmed species review remain documented.

## Retry exhaustion: img_024

- Attempt 2 encountered APITimeoutError.
- Attempt 3 encountered RateLimitError.
- The item became failed with attempts=3 and
  last_error="Processing failed: RateLimitError".
- Job summary: 22 completed, 26 pending, 0 processing,
  0 needs_review, and 1 failed.
- The failed item's attempt history was preserved.
- The latest error concerns provider quota; classification was not obtained.

## Final model and dataset review

- Changed VISION_MODEL to gemini-3.5-flash-lite after failures with
  gemini-3.8-flash. Subsequent successful requests do not by themselves
  prove why the earlier requests failed or which model is more accurate.
- img_027's database record explicitly showed vision_model
  gemini-3.5-flash-lite and subject Deutsche Post DHL delivery vans.
- Visual inspection showed img_037 contains three plates of food,
  while img_038 contains a vegetable salad bowl. Their source references
  and creators had been swapped in the manifest.
- Corrected img_037 to Lily Banse's photo --YHSwy6uqvk and img_038
  to Anna Pelzer's photo IGfIGP5ONV0, with Unsplash License references.
- Ran scripts.sync_reviewed_provenance successfully. A database query
  confirmed the corrected creators and source URLs for both images.
- Corrected post_009's evaluation reference to img_038; PowerShell JSON
  inspection confirmed the new value.
- Image files, classification metadata, and job history were unchanged
  by provenance synchronization. The earlier criticism of img_037's
  broad prediction arose from the incorrect evaluation reference.
- img_006's coyote prediction remains unconfirmed at species level.
  Source titles and model confidence are not treated as ground truth.
- No ranking or matching accuracy result is claimed from this review.

## Dataset delivery and repository tracking

- Packaged the unchanged originals as image-relevance-images-v1.zip:
  160822607 bytes, SHA-256
  0a95fae32a5925ba129b925a2608c2774ca42934d40ec28990661f31ff6d5dc6.
- Added data/dataset.json with the release URL and all 50 original-file
  sizes and checksums, plus scripts.download_dataset.
- Five offline tests passed, covering restoration, preservation of
  existing files, archive integrity, path traversal, and image integrity.
- Existing-file verification reported 50 original images verified.
- Both local-archive installation and public release download reported:
  Verified 50 images; installed 0 missing files.
- The full suite initially had three database setup timeouts. After
  waiting for PostgreSQL readiness, the latest run reported 39 passed,
  2 dependency deprecation warnings, in 2.10 seconds.
- After git rm --cached, PowerShell confirmed 50 local image files and
  zero image files in Git's index. These removals are staged, not yet
  confirmed committed. Local originals and database checksums are intact.
- Older commits and the dataset-v1 tag retain the image blobs. No history
  rewrite or full-history repository-size reduction has been verified.

## Combined Phase 2 review hardening

Commands and actual results from a fresh Python 3.14 virtual environment:

```text
python -m pip install -r backend/requirements-dev.txt
Installation succeeded with the curated direct dependencies.

python -m pip check
No broken requirements found.

python -m pytest tests -q --tb=short
44 passed, 17 skipped, 2 warnings in 2.79s

python -m scripts.run_integration_tests
61 passed, 2 warnings in 2.89s

python -m alembic check
No new upgrade operations detected.
```

The offline command requires no Docker, .env, or Gemini key. Its 17 skips are
explicit integration tests, not claimed passes. The full command ran all 61
tests against the isolated image_relevance_test database on port 55432, with
fake API credentials. A new database was migrated from the first revision
through e5a0c4d8b912. The same complete suite also passed in the original
environment. No actual Gemini requests were made for this verification.

- test_installed_sdk_wrapped_transport_error_is_retryable_without_hidden_retry
  exercised the installed Interactions SDK with an httpx mock transport for
  connection and timeout failures. Each case observed one HTTP attempt;
  retry classification used public cause/status information, not private imports.
- test_registered_image_verification_rejects_escape_and_changed_bytes checked
  the common path/checksum validator. Both processing paths now share the
  metadata upsert; the single-image integration test saved one row on repeated
  calls and rejected modified image bytes.
- Seven schema cases reject empty/blank attributes and oversized subjects,
  captions, attribute lists, and attribute strings.
- ai_calls records and daily reservations now commit atomically before client
  creation. Integration tests verify audit creation, completion, blocked-call
  behavior, rollback of invalid attribution, and tenant isolation.
- Mocked vision tests verify successful usage, interrupted/failed audit status,
  client-construction failure, and no client construction on a budget block.
- Local JSONL append logging is retired for new calls. Historical JSONL is
  retained locally, not imported or relabeled as database evidence. Hard-killed
  processes can leave durable started rows requiring reconciliation.
- Added separate direct runtime/dev requirements, isolated test Compose and CI,
  shared image validation/persistence, model exports, a frontend placeholder,
  MIT code license, and a Phase 2 capstone.yaml draft with run/seed/test commands.
- Legacy published Git history and dataset-v1 still contain original image
  blobs. The current source snapshot excludes them and restores exact originals
  from the verified release. History was not rewritten or force-pushed.
- Dollar spending enforcement, provider quota-window-aware scheduling,
  authenticated tenant identity, and the Phase 3 matching probes remain outside
  the implemented milestone. These are not claimed complete by capstone.yaml.

### Applied-repository checks before the combined commit

- Applied additive migration e5a0c4d8b912 to the demo database successfully.
- Read-only queries confirmed 50 completed demo images, 50 metadata records,
  and the original completed_with_errors job plus completed reprocessing job.
- Running the complete suite from the updated repository in the fresh
  environment reported 61 passed, 2 warnings, in 3.00 seconds.
- The exact capstone.yaml test command reported 44 passed and 17 integration
  skips, with no Docker or API credentials required by that command.
- Live-database API smoke checks returned: /health 200, demo job 200,
  different-tenant job 404, and missing-tenant job 422.
- Submission manifest and GitHub Actions YAML parsed successfully. CI has
  been configured but no remote GitHub Actions run is claimed here.
