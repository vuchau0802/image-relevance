# Image Relevance

React/TypeScript demo with a Python/FastAPI backend for classifying images
and matching their descriptions to blog posts using cached embeddings,
subject rules, and cosine similarity. The Phase 2 corpus run produced
50 completed images and 50
metadata records. Original retry failures remain in the original job;
reprocessing completed both failed images without changing that history.

## Architecture

```text
React frontend -> FastAPI /api/posts, /api/posts/{post_id}/images
                  /api/images/{image_id}/file and /attribution
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
The React/TypeScript frontend in frontend/ loads tenant posts from the API,
ranked image previews, creator credits, source/license links, and loading,
no-match, incomplete, and request-error states. It uses the original ranker;
the separate context pilot is not connected to this UI.

Latest user-run verification: 336 backend tests passed in 6.54 seconds
against the isolated test database, with two dependency deprecation
warnings. All 10 frontend tests, the production build, and ESLint passed.
Default offline backend runs explicitly skip database integration tests.
Automated tests use fake provider responses rather than real Gemini calls.

## Requirements and installation

- Python 3.14 was used for local verification.
- Node.js and npm are required for the frontend build and tests; use a
  version compatible with the locked Vite/Vitest packages.
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

## Frontend: single-server demo

For a database already prepared with demo sources and current embeddings,
build the frontend from the project root:

```powershell
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
.\.venv\Scripts\python.exe backend/scripts/run_demo.py
```

Open http://127.0.0.1:8000. The startup script starts PostgreSQL, waits for
readiness, applies migrations, and launches FastAPI on localhost. It does not
build the frontend or prepare missing classifications/embeddings; see
Download and seed below for data preparation.

FastAPI serves frontend/dist at / and its compiled assets from /assets/.
The browser uses /api routes on the same origin; Vite need not be running.
If the build is missing at backend startup, / returns 503 with a build
instruction while API routes remain available. Rebuild and restart FastAPI
after frontend changes. A successful build is local deployment preparation,
not evidence of a publicly deployed service.

### Optional Vite development server

For automatic frontend updates, run these in separate terminals from the
project root, with PostgreSQL running and migrations applied:

```powershell
# Terminal 1: backend
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2: frontend
cd frontend
npm.cmd run dev
```

Open http://127.0.0.1:5173. Vite forwards /api requests to the backend and
removes the /api prefix. Existing unprefixed API URLs remain supported for
CLI utilities and earlier clients. /health and /api/health both return the
health response; an unknown /api route returns 404 rather than the frontend.

### Posts, previews, and attribution

The post picker loads every page of GET /api/posts?offset=0&limit=50 instead
of duplicating a post list in React. Pages contain items and next_offset;
null next_offset means the final page. Pagination is ordered by post ID.
The endpoint lists all posts for the selected tenant, including calibration
and development posts if they have been seeded. An empty list and a failed
load have separate states; Reload posts retries a failed list request.

The shared frontend request helper sends X-Tenant-ID: demo for post listing,
recommendations, image files, and attribution. This is caller-controlled
tenant scoping for a local demo, not authenticated user identity. Login,
server-derived workspace ownership, and private user uploads are planned.
No Gemini API key is sent to the browser. Ranking uses cached embeddings.

GET /api/images/{image_id}/file looks up the image by tenant and checks the
registered corpus path and SHA-256 before serving the original JPEG.
GET /api/images/{image_id}/attribution returns the creator, source URL, and
license URL. Both require the tenant header. The frontend fetches image
blobs with that header and releases temporary object URLs. Attribution links
allow only http(s) URLs. Source licenses apply separately from the code license.

Cards show cosine similarity as a score, not a correctness probability.
No-match and unsupported-subject responses show an explanation; incomplete
results are labeled provisional. Aborted or outdated recommendation responses
are ignored when switching posts.

If the backend is unavailable, a new recommendation request displays an error
and Try again. Restart the backend and click Try again to retry. Existing
results do not automatically check backend health; select another post to
trigger a request when testing an outage.

Commit package-lock.json; node_modules/ and dist/ remain ignored. This root
README is the single setup README. HTTPS, hosted storage, backups, persistent
worker supervision, and authenticated multi-user deployment remain separate
work. A complete real-browser end-to-end test suite is not established.

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

GitHub Actions provisions the same isolated database. A live API server is
not needed for these tests.

Frontend checks, from frontend:

```powershell
npm.cmd test
npm.cmd run build
npm.cmd run lint
```

npm.cmd test runs Vitest once; npm.cmd run test:watch starts watch mode.
The 10 frontend tests cover post selection/empty/retry states, multi-page
loading and pagination failures, recommendation no-match/retry behavior,
and ignoring a late response after post selection changes. API responses
are mocked; image preview and attribution components are mocked in App tests.
These tests do not establish real browser image decoding or external link
navigation. No running backend or provider credentials are required.

### Latest verification

- User-run isolated backend suite: 336 passed, two existing dependency
  deprecation warnings, in 6.54 seconds.
- Image API: 13 tests passed for file/attribution responses, tenant lookup,
  required headers, missing files, checksum mismatch, and path containment.
- Post API/repository: eight API tests and four isolated-database tests cover
  tenant forwarding/filtering, input validation, ordering, and pagination.
- Frontend serving: nine tests passed using a temporary build, covering index
  and asset delivery, health/API precedence, unknown paths, and absent builds.
- Frontend: 10 tests passed in 1.28 seconds; build and lint passed. An observed
  duplicate React key warning was corrected and was absent in the rerun.
- Live local requests: /api/health returned 200; an unknown /api path returned
  404. Image-file requests returned 200 for demo, 404 for another tenant,
  and 422 without the header. Attribution JSON was returned for img_001.
- User-supplied browser output showed the API-backed post list, fox/Yosemite
  recommendations, creator/source/license credits, and a penguin no-match
  state. An outage showed a 502 error and Try again, followed by restored
  results after backend restart. Page text alone does not independently
  establish image rendering, link navigation, or the exact recovery action.
- Earlier dependency/migration/readiness checks passed at their recorded
  checkpoints. They were not rerun for this documentation-only update.

Original evaluation artifacts remain under docs/evidence and are separate
from development checks. The preserved first-run report SHA-256 remains
`59b59fb4128993645af416bcdbba4ef2e2517a5bd1160fca36cb548ef48c1606`.
The separate context pilot rejected the inspected snowy-fox mismatch;
eight vehicle development cases passed at 0.85. These are development
results and do not replace the original 9/12 new-query evaluation.

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
  Review APIs, authenticated tenant identity, private uploads, hosted
  deployment, and independent held-out evaluation remain outstanding.
  Single-server static frontend serving is implemented. Subject rules
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
