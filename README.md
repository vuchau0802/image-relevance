# Image Relevance

React/TypeScript demo with a Python/FastAPI backend for classifying images
and matching their descriptions
to blog posts using cached embeddings, subject rules, and cosine similarity. The Phase 2 corpus run produced 50 completed images and 50
metadata records. Original retry failures remain in the original job;
reprocessing completed both failed images without changing that history.

## Architecture

```text
FastAPI /health, /jobs/{job_id}, /posts/{post_id}/images
             |
       repositories ---------------- PostgreSQL / Alembic
             |                        images, metadata, jobs, posts,
       background worker              embeddings, daily usage, AI calls
             |
    path + checksum validation
             |
    daily reservation + started audit (one transaction)
             |
    Gemini -> schema/confidence validation -> shared metadata upsert
```

HTTP, business logic, persistence, and worker entry points are separate.
The React/TypeScript frontend in frontend/ presents the original demo posts,
ranked image previews, creator credits, source/license links, and loading,
no-match, incomplete, and request-error states. It uses the original ranker;
the separate context pilot is not connected to this UI.

Latest user-run verification: the isolated-database suite passed all
315 tests in 6.27 seconds, with two dependency deprecation warnings. Offline runs explicitly
skip database integration tests. Tests make no real Gemini requests.

## Requirements and installation

- Python 3.14 was used for local verification.
- Docker Desktop with Compose is needed for the API database and integration
  tests. Offline unit tests need neither Docker nor API credentials.
- Available Gemini quota is needed for actual classification and embedding generation.
  Ranking and evaluation use cached embeddings without provider requests.

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

Existing installations must run alembic upgrade head before using revised
workers or matching. Phase 3 adds posts, versioned embeddings, a separate
embedding allowance, and post attribution in PostgreSQL AI-call records.

## Frontend local development

The frontend uses React, TypeScript, and Vite. Install a Node.js version
compatible with the installed Vite package and npm. From the project root:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Keep this terminal running and open http://127.0.0.1:5173. The backend must
run separately on 127.0.0.1:8000 using the commands above, with demo data
prepared as described below. For a prepared database, a second terminal can
start only the API from the project root:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Vite forwards /api requests to the backend and removes the /api prefix.
Check the connection through http://127.0.0.1:5173/api/health. The frontend
sends X-Tenant-ID: demo for recommendations, image files, and attribution.
This is tenant scoping for a local demo, not authenticated user identity.
No Gemini API key is sent to the browser. Ranking uses cached embeddings.

Image files are served by GET /images/{image_id}/file after a tenant-scoped
database lookup and corpus path/checksum verification. Attribution is served
by GET /images/{image_id}/attribution. Both require X-Tenant-ID. The frontend
fetches image blobs with that header and releases temporary object URLs.
Cards show creator credits plus source/license links. Similarity is shown
as a score, not a correctness probability.

From frontend, check the production bundle and lint:

```powershell
npm.cmd run build
npm.cmd run lint
```

The user verified both commands successfully. Commit package-lock.json;
node_modules/ and dist/ are ignored. Documentation remains in this root
README rather than an additional frontend README.

If the backend is unavailable, a recommendation request displays an error
and a Try again button. Restart the backend and click Try again to retry.
Existing displayed results do not automatically trigger an outage check;
select another post to start a request when testing this behavior.

The current proxy is a development-server setup. A successful build creates
frontend/dist; production API routing and frontend serving are not configured
or verified by this workflow. Separate frontend automated tests and a full
browser end-to-end suite are not yet established.

## Download and seed

Images are delivered through the published dataset-v1 release asset, rather
than tracked in the current source tree. Attribution is in data/manifest.json.
data/dataset.json pins the ZIP size/SHA-256 and each original image checksum.

From the root, with the database initialized:

```powershell
.\.venv\Scripts\python.exe backend/scripts/seed_demo.py
```

This command starts PostgreSQL, applies migrations, verifies or downloads
the approximately 161 MB dataset, registers images, and seeds the original
11 posts. It then processes bounded vision and embedding batches as needed.

Existing classifications and current embeddings are reused. On a fresh
setup, preparation can make Gemini requests within the configured daily
allowances. It does not reset quotas or erase previous job history.

Exit code 0 means the expected demo images and posts have current embeddings
and matching is ready. Exit code 2 means preparation is unfinished. Inspect
the worker summary before rerunning after retry delays or allowance resets.
Failed or needs_review images require investigation.

Automated integration tests prepare a fresh miniature corpus using real seed,
worker, cache, audit, and ranking code with fake Gemini responses. They also
verify resumption after a budget block and a provider timeout. Docker/process
launches are mocked in these tests. A fresh full-corpus run with the live
provider remains unverified; the live local run reused existing data.

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

The individual scripts.create_batch_job utility uses the fixed initial-image-processing idempotency
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

For embeddings, an AI-call status of completed means the provider returned
a valid vector. It does not guarantee successful cache storage. Cache-write
failures propagate to the worker; an embedding job item completes only after
its cache entry exists. If storage failed, a later retry may require another
reserved provider request. These failure paths are covered by tests.

From the project root, inspect recent records without raw responses/secrets:

```powershell
docker compose exec db psql -U image_relevance -d image_relevance -P pager=off -c "SELECT image_id, model, status, input_tokens, output_tokens, error_type FROM ai_calls WHERE tenant_id = 'demo' ORDER BY created_at DESC LIMIT 10;"
```

## Embeddings, matching, and evaluation

After image processing is complete, run from backend:

```powershell
..\.venv\Scripts\python.exe -m scripts.seed_posts
..\.venv\Scripts\python.exe -m scripts.embed_one_image --image-id img_001
..\.venv\Scripts\python.exe -m scripts.embed_one_post --post-id post_001
```

Generate embeddings for each completed image and seeded post before ranking
that corpus. The single-source scripts accept --image-id or --post-id and
--tenant-id. Repeating a command reuses the current cache entry. Each cache
miss can consume one embedding reservation and provider request; stop a batch
on errors. Image embeddings use stored descriptions, not another image upload.

Embedding settings are EMBEDDING_MODEL=gemini-embedding-001,
EMBEDDING_DIMENSIONS=768, and EMBEDDING_DAILY_CALL_LIMIT=100. Both source types
use SEMANTIC_SIMILARITY. Cache keys include the tenant, source, model,
dimensions, task type, and exact prepared-input hash. Changed source text
requires a new embedding. Vectors are validated and normalized.

### Persistent embedding batches

From backend:

```powershell
..\.venv\Scripts\python.exe -m scripts.create_embedding_job
..\.venv\Scripts\python.exe -m app.workers.embedding_runner --job-id YOUR_JOB_ID --max-items 10
```

Job creation snapshots source text and hashes. Repeating the same tenant
and idempotency key returns the same job. Use a new key for a new source
snapshot or embedding configuration.

Workers use claim tokens, expiring leases, bounded attempts, retry delays,
and recovery. Budget blocks restore the unstarted attempt. Cache hits need
no provider request or reservation.

Check current demo readiness with:

```powershell
..\.venv\Scripts\python.exe -m scripts.demo_status
```

Evaluation requires complete current embedding coverage. Incomplete rankings
stop evaluation rather than being counted as successful rejections.

With current embeddings available:

```powershell
..\.venv\Scripts\python.exe -m scripts.rank_images --post-id post_010 --top 5

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/posts/post_010/images?top=5" `
    -Headers @{ "X-Tenant-ID" = "demo" } |
    ConvertTo-Json -Depth 6
```

The ranking endpoint is read-only and makes no Gemini requests. It checks
explicit subject aliases and selected caption evidence, then applies
MIN_MATCH_SIMILARITY=0.85. Scores are cosine similarities, not probabilities.
Responses are matched, no_confident_match, incomplete, or unsupported_subject.
Missing current image embeddings make results provisional. An unknown post
under that tenant returns 404; a missing current post embedding returns 409.
The local tenant header is caller-controlled and is not authentication.

Calibration labels are in data/calibration.json. After visual review, seed
its posts with scripts.seed_calibration and embed cal_001 through cal_006
using scripts.embed_one_post. Review labels before setting reviewed=true;
expected answers are not included in embedded post text.

To reproduce the reviewed calibration and original-post regression checks:

```powershell
..\.venv\Scripts\python.exe -m scripts.evaluate_matching
```

The script uses cached rankings and the configured threshold without tuning
it. It saves data/processed/matching_evaluation.json (gitignored), including
per-case decisions, returned scores, configuration, and label-file hashes.
Current results at 0.85 are 6/6 calibration cases and 10/11 regression cases.
The scooter post is a false rejection: score 0.784260. These small,
development-influenced sets do not establish independent held-out accuracy.

At the fixed 0.85 threshold:

- Matchable-post retrieval success: 9/10 (90%), counting the scooter
  abstention as a failure.
- Accepted top-prediction precision: 9/9 (100%).
- No-match rejection: 1/1 penguin case correctly rejected.
- Overall regression cases passed: 10/11 (90.9%).

These metrics use development-influenced regression examples, not an
independent held-out set. The 9/10 result includes threshold-based
abstention; it is not an unthresholded ranking-only top-1 score.

## Phase 4 evaluation results

With the baseline and 0.85 threshold frozen, 12 assistant-authored new
queries with user-reviewed labels produced:

- Correct accepted top matches: 6/8 matchable posts (75%).
- Accepted top-prediction precision: 6/7 (85.7%).
- Coverage: 7/12 posts (58.3%).
- Correct no-match rejection: 3/4 (75%).
- Overall cases passed: 9/12 (75%).

The Beetle and scooter cases were false rejections. A snowy-fox case
incorrectly accepted a fox photograph without snow. These failures remain
in the unchanged first-run report. A separate context-aware development
pilot was subsequently added using inspected failures. Those cases now
inform development and do not support a new held-out accuracy claim.
The original ranker and 0.85 threshold remain unchanged.
This is a new-query evaluation on the existing corpus, not an independent
benchmark. Earlier calibration and regression figures are separate.

See [the full results and cost limitations](docs/phase4-results.md),
[the frozen baseline](docs/heldout-baseline.json), and
[the preserved first-run report](docs/evidence/heldout-first-run.json).
The project tier was shown as Free tier; recorded USD 0 estimates are not
verified billing, and missing embedding token counts remain unknown.

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
- Embeddings, ranking, subject guards, no-match reasons, and measured
  calibration/regression checks and the local frontend demo are implemented.
  Review APIs, authenticated tenant identity, production frontend serving,
  and independent held-out evaluation remain outstanding. Subject rules
  rely on model descriptions and explicit aliases.
- capstone.yaml lists development endpoints. Its seed command delegates to
  resumable preparation and reports readiness after processing and embedding.
  Fresh full-corpus preparation with the live provider and final-capstone
  completion are not claimed.
- Current source tracking excludes images, runtime output, secrets, and the
  project brief. Earlier commits and dataset-v1 retain image blobs. History
  was preserved in accordance with the brief; no force-push was performed.

The demo database persists in its Docker volume. docker compose stop db
preserves that data. See BUILDLOG.md for AI assistance and corrections.
