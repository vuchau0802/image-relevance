# Image Relevance

React/TypeScript application with Clerk sign-in and a Python/FastAPI backend for classifying images
and matching their descriptions to blog posts using cached embeddings,
subject rules, and cosine similarity. The Phase 2 corpus run produced
50 completed images and 50
metadata records. Original retry failures remain in the original job;
reprocessing completed both failed images without changing that history.

## Architecture

```text
React frontend + Clerk session -> FastAPI /api/posts, /api/posts/{post_id}/images
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

Latest user-run verification: 795 backend tests passed against the isolated
test database, with two existing dependency deprecation warnings. All 125
frontend tests, the production build, and ESLint passed.
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

### Sign-in and account configuration

Configure CLERK_ISSUER and CLERK_AUTHORIZED_PARTIES in the root .env using
the placeholders in .env.example. Authorized parties must include the exact
origins used to open the app, such as http://127.0.0.1:8000 and
http://127.0.0.1:5173. Use the issuer for the same Clerk application as the
frontend publishable key.

For a new frontend setup, from frontend:

```powershell
Copy-Item .env.example .env.local
```

Set VITE_CLERK_PUBLISHABLE_KEY in frontend/.env.local. Do not overwrite an
existing file. The root .env configures the backend; frontend/.env.local
configures Vite and remains separate. Both local environment files are
ignored. Commit only placeholder examples. Rebuild the frontend after
changing its environment configuration.

The browser sends a Clerk session bearer token. The backend validates it
and derives a stable private workspace from the verified issuer and user.
X-Tenant-ID does not grant access. Content endpoints require sign-in and
scope database lookups to that workspace. GET /api/me checks the session;
POST /api/workspace creates or returns its workspace. Seeded demo content
does not automatically become content in a new account's workspace.

### Posts, uploads, previews, and attribution

Users can create, edit, prepare, and delete their own posts. The post picker
loads API pages ordered by post ID. Editing content requires preparation of
its current embedding before matching. The selected post's details include
the current failed preparation job when a retry is available.

Users can upload JPEG images up to 10 MiB and 20 million pixels. Uploads
are validated, normalized, and stored under data/uploads/<workspace>/.
Duplicate uploads reuse the workspace's existing image. Your images lists
private uploads with analysis status and current embedding readiness.
Analyze the image, then prepare its embedding before matching. Images that
need review are excluded from matching.

GET /api/images/{image_id}/file verifies the registered path, workspace,
and SHA-256 before serving a JPEG. Attribution is returned separately by
GET /api/images/{image_id}/attribution. The frontend fetches authenticated
image blobs and releases temporary object URLs. Source/license links allow
only http(s) URLs; source licenses apply separately from the code license.
No Gemini API key is sent to the browser.

Deleting a post removes its current source and embeddings. Deleting an
image removes access immediately and queues durable physical file cleanup.
Queued or running processing blocks deletion. Image cleanup validates the
private path and checksum and is retried by the workspace worker. Historical
processing/audit records are retained where supported; terminal vision item
rows referencing a deleted image are removed and job summaries refreshed.

### Continuous processing and recovery

Run the API and the workspace worker in separate terminals. From backend:

```powershell
..\.venv\Scripts\python.exe -m app.workers.workspace_runner
```

Keep this worker running while using analysis, preparation, and image
deletion. The API queues work; it does not run the continuous worker.
The worker discovers workspace jobs, processes vision and embedding items,
recovers expired claims, respects daily allowances, and processes image
file cleanup tasks. Stop it with Ctrl+C; restart it after worker code changes.

Failed analysis and preparation jobs can be retried explicitly. Each retry
preserves the previous failure history and reuses duplicate requests or
compatible active work. Preparation retries require unchanged input and
embedding settings; changed content/settings require a new preparation
request. Failure discovery restores retry controls after a page refresh.
Retries still consume allowance when they start a provider request.

Cards show cosine similarity as a score, not a correctness probability.
No-match and unsupported-subject responses explain abstention; incomplete
results are provisional. Requests are cancelled or ignored when switching
posts. If the backend is unavailable, a recommendation request displays an
error and Try again. Restore the backend and retry without reloading the page.

Commit package-lock.json; node_modules/ and dist/ remain ignored. This root
README is the single setup README. HTTPS, hosted storage, backups, persistent
worker supervision, and public deployment remain separate work. A complete
real-browser end-to-end test suite is not established.

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

Signed-in clients can read GET /api/jobs/{job_id} for analysis progress and
GET /api/embedding-jobs/{job_id} for preparation progress. Both require a
valid session bearer token and return 404 for jobs outside that workspace.
The browser obtains its session token through Clerk; a tenant header is not
an authentication substitute. Internal corpus utilities continue to accept
explicit tenant IDs and should run only in a trusted operator environment.

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
Frontend tests cover authenticated request helpers, backend session states,
post selection/create/edit/delete, image uploads and pagination, analysis and
embedding retries, failure recovery after reload, request cancellation, and
recommendation refresh. API responses are mocked; image previews and
attribution are mocked in App tests. No running backend or provider
credentials are required. These tests do not establish real browser image
decoding or external link navigation.

### Latest verification

- User-run isolated backend suite: 795 passed, with two existing dependency
  deprecation warnings. Tests use fake provider responses.
- Frontend: 125 tests passed; production build and ESLint passed.
- Local browser checks established sign-in, account workspace creation,
  private uploads, analysis/preparation progress, post editing and deletion,
  and matching. The edited forest post returned an image at similarity 0.852.
- Browser image deletion was verified. Three physical cleanup tasks then
  completed on their first attempt with no errors after the worker started.
- Analysis and embedding retry behavior is covered by automated tests.
  Live retry verification remains pending: the user's workspace had no
  failed images or failed preparation jobs available at the checkpoint.
- Image readiness and failure discovery share metadata reads. A batching
  test checks the same query count for one and seven images.
- These are local checks, not evidence of a publicly deployed service or a
  complete automated browser end-to-end suite.

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
  Clerk authentication, private uploads, account-owned content, deletion,
  and processing retries are implemented locally. Review APIs, hosted
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
