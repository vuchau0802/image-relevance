# Image Relevance

Python/FastAPI backend for classifying images and, in Phase 3, matching them
to blog posts. The Phase 2 corpus run produced 50 completed images and 50
metadata records. Original retry failures remain in the original job;
reprocessing completed both failed images without changing that history.

## Architecture

```text
FastAPI /health, /jobs/{job_id}
             |
       repositories ---------------- PostgreSQL / Alembic
             |                        images, metadata, jobs,
       background worker              job items, daily usage, AI calls
             |
    path + checksum validation
             |
    daily reservation + started audit (one transaction)
             |
    Gemini -> schema/confidence validation -> shared metadata upsert
```

HTTP, business logic, persistence, and worker entry points are separate.
The React/TypeScript frontend is planned; frontend/ is reserved for the planned implementation.

Verification: 44 offline tests pass with 17 explicit integration skips; the
complete isolated-database suite passes all 61 tests. Two dependency
deprecation warnings remain. No real Gemini calls are used in tests.

## Requirements and installation

- Python 3.14 was used for local verification.
- Docker Desktop with Compose is needed for the API database and integration
  tests. Offline unit tests need neither Docker nor API credentials.
- Available Gemini image-model quota is needed only for actual classification.

From the project root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

Skip venv creation if it already exists. Production-only installation can use
backend/requirements.txt. These files list direct runtime dependencies and
test dependencies separately; optional FastAPI cloud/CLI extras are not used.

For a new setup only:

```powershell
Copy-Item .env.example .env
```

Do not overwrite an existing .env. Replace the API-key and database-password
placeholders. Never commit this file. The example vision model is
gemini-3.5-flash-lite and the local daily allowance is 40. Earlier corpus
results used gemini-3.8-flash; each metadata record stores its actual model.

POSTGRES_PASSWORD initializes a fresh volume. Editing .env does not change an
existing database user's password. PowerShell environment values override
.env values. For the API, Python loads .env from the project root.

## Run and migrate

From the root, this starts PostgreSQL, waits for readiness, applies migrations,
and serves the API:

```powershell
.\.venv\Scripts\python.exe backend/scripts/run_demo.py
```

Alternatively, run the steps separately:

```powershell
docker compose up -d --wait db
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m scripts.check_database
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Health: http://127.0.0.1:8000/health

Interactive documentation: http://127.0.0.1:8000/docs

Existing installations must apply migration e5a0c4d8b912 before running the
revised worker, because new AI-call records use PostgreSQL rather than JSONL.

## Download and seed

Images are delivered through the published dataset-v1 release asset, rather
than tracked in the current source tree. Attribution is in data/manifest.json.
data/dataset.json pins the ZIP size/SHA-256 and each original image checksum.

From the root, with the database initialized:

```powershell
.\.venv\Scripts\python.exe backend/scripts/seed_demo.py
```

This downloads about 161 MB, registers the images, and creates the initial
demo job. It prints a job ID and makes no Gemini calls. It does not classify
the corpus. Existing unchanged image registrations are skipped.

For individual commands from backend:

```powershell
..\.venv\Scripts\python.exe -m scripts.download_dataset
..\.venv\Scripts\python.exe -m scripts.seed_images
..\.venv\Scripts\python.exe -m scripts.create_batch_job
```

The downloader uses only the standard library; it verifies every image and
refuses to replace differing existing files. It uses same-volume hard links
for atomic installation, so the destination filesystem must support them
(the verified Windows NTFS setup does). Allow space for the ZIP and
temporary image staging. Useful offline options:

```powershell
..\.venv\Scripts\python.exe -m scripts.download_dataset --verify-only
..\.venv\Scripts\python.exe -m scripts.download_dataset --archive "PATH_TO_ZIP"
```

The seed validates paths and provenance field formats and computes checksums;
it does not prove source attribution or classification accuracy. Repeated
seeding does not update changed provenance fields. For a database seeded
before the reviewed img_037/img_038 correction, run:

```powershell
..\.venv\Scripts\python.exe -m scripts.sync_reviewed_provenance
```

img_037 is Lily Banse's three-plate food photo; img_038 is Anna Pelzer's salad.
post_009's evaluation reference is img_038. The correction did not alter files
or model predictions. The MIT license covers project code, not these photos;
their original source licenses and attributions remain applicable.

## Process and recover jobs

From backend, substitute the job ID printed by the creation script:

```powershell
..\.venv\Scripts\python.exe -m app.workers.runner --job-id YOUR_JOB_ID --max-items 3
```

The demo creation script uses the fixed initial-image-processing idempotency
key. Repeating it returns the same job. The worker stops at its claim limit,
when nothing is ready, or after an unsuccessful attempt or budget block.

An item has at most three attempts per job, a 120-second claim lease, and
persisted exponential retry delays. A budget block releases its claim without
consuming a processing attempt. A crash can consume an attempt/reservation;
expired leases are recovered at worker startup. To recover without AI calls:

```powershell
..\.venv\Scripts\python.exe -c "from app.repositories.jobs import recover_expired_claims; print(recover_expired_claims('demo', 'YOUR_JOB_ID'))"
```

To create a new job for failed images:

```powershell
..\.venv\Scripts\python.exe -m scripts.create_reprocessing_job
```

This uses failed-image-reprocessing-v1. Repeated execution returns that same
job, rather than starting more retry rounds. Old job items are preserved.

The persistent worker owns batch retries. scripts.process_one is a separate
synchronous development utility using run_with_retries; the worker never
nests that retry helper. Each actual utility attempt also reserves allowance
and creates an audit record. Internal SDK retries are disabled with attempts=0.

## Job-status API and call audit

```powershell
Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/jobs/YOUR_JOB_ID" `
    -Headers @{ "X-Tenant-ID" = "demo" } |
    ConvertTo-Json
```

A missing tenant header returns 422; a job outside that tenant returns 404.
The header is caller-controlled for local development. Authentication must
provide trusted tenant identity before deployment.

New calls are logged to ai_calls. A started row is committed atomically with
the tenant's daily reservation before client construction. Completion stores
status, model, image/job attribution, usage when returned, and an error class
on failure. Concurrent calls do not append to a shared log file. Interrupted
requests are marked interrupted when possible; a hard process kill or failed
audit finalization leaves a started row for reconciliation. Historical
data/ai_calls.jsonl remains local and is not automatically imported.

From the project root, inspect recent records without raw responses/secrets:

```powershell
docker compose exec db psql -U image_relevance -d image_relevance -P pager=off -c "SELECT image_id, model, status, input_tokens, output_tokens, error_type FROM ai_calls WHERE tenant_id = 'demo' ORDER BY created_at DESC LIMIT 10;"
```

## Tests and CI

Offline unit suite, from backend:

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q --tb=short
```

Integration tests are explicitly skipped in this default command. Tests
override real credentials and database settings before importing the app.

For the complete suite, start the separate disposable test database:

```powershell
docker compose -f ..\docker-compose.test.yml -p image-relevance-tests up -d --wait
..\.venv\Scripts\python.exe -m scripts.run_integration_tests
```

It uses port 55432 and image_relevance_test, applies all migrations, and runs
unit and integration tests. It does not use the demo database or real Gemini.
An explicit TEST_DATABASE_URL can override the destination, but its database
name must end in _test. The Docker test password is a public disposable test
credential, not a production credential. Remove only the test service with:

```powershell
docker compose -f ..\docker-compose.test.yml -p image-relevance-tests down
```

GitHub Actions provisions the same isolated database. A live API server is not
needed for tests. See EVIDENCE.md for actual test counts and verification.

## Limits and submission status

- Call reservations are limited per tenant and UTC day, independently of
  Google's model/project quotas. Changing models does not reset reservations.
- A $0 configured free-tier estimate is not verified billing or a dollar
  budget. Failed/abandoned reservations are not refunded automatically.
- Pre-guard calls were not backfilled. Older SDK retries could make more than
  one HTTP request under one historical reservation.
- Provider Retry-After and quota-window reset times are not yet integrated.
- Completed classification means bounded schema and confidence checks passed;
  it does not prove accuracy. img_006's species remains unconfirmed.
- Embeddings, ranking, mismatch guards, no-match explanations, review APIs,
  and measured evaluation are still future work. capstone.yaml is a Phase 2
  manifest draft, not a claim that final acceptance probes are implemented.
- Current source tracking excludes images, runtime output, secrets, and the
  project brief. Earlier commits and dataset-v1 retain image blobs. History
  was preserved in accordance with the brief; no force-push was performed.

The demo database persists in its Docker volume. docker compose stop db
preserves that data. See BUILDLOG.md for AI assistance and corrections.
