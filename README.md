# Image Relevance

A Python/FastAPI backend for classifying images and, in later phases,
matching images to blog posts.

## Current status

Implemented:

- Vision metadata validation and confidence-based review decisions.
- PostgreSQL persistence and Alembic migrations.
- Idempotent batch jobs, claim leases, retries, and recovery.
- Bounded worker runs and a shared daily vision call limit.
- Tenant-scoped job-status API.

Latest validation: 39 tests passed, with two dependency deprecation warnings.

Corpus processing is verified: all 50 demo images have completed status
and 50 metadata records exist. The original job retains two failed items;
a separate reprocessing job completed both images. Historical job failures
do not imply current corpus failures. Classification accuracy is not yet
measured, and img_006's species identification remains unconfirmed.

Embeddings, ranking, subject-mismatch guards, and frontend integration
are not yet implemented.

## Requirements

- Python 3.14.5 was used in the observed environment; other versions have not been verified against backend/requirements.txt.
- Docker Desktop with Docker Compose
- Gemini API key with available model quota

## Configuration

Copy .env.example to .env and replace placeholder values.

Keep .env private. The application loads it from the project root.

The example configuration uses gemini-3.5-flash-lite and a daily allowance
of 40. Earlier results used gemini-3.8-flash; each metadata record stores
the actual vision_model used. Model changes do not reset daily usage.

VISION_DAILY_CALL_LIMIT limits reservations per tenant and UTC day.
This counter is separate from Google's project quota and reset schedule.
Failed requests consume reservations. Calls made before guard activation
are not included; earlier SDK retries may also have made extra requests.

X-Tenant-ID is caller-controlled for local development.
Authenticated tenant identity is required before deployment.

## Install dependencies

Run from the project root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

If .venv already exists, skip its creation.

For a fresh setup, copy the configuration template:

```powershell
Copy-Item .env.example .env
```

Skip this command if .env already exists. Edit .env and replace the
API-key and database-password placeholders before continuing.

## Start PostgreSQL and apply migrations

From the project root:

```powershell
docker compose up -d db
docker compose ps
```

Wait until the database is healthy, then:

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m scripts.check_database
```

Expected connection-check output:

```text
Database connection successful: 1
```

POSTGRES_PASSWORD initializes the password on a new database volume.
Changing .env alone does not change an existing database user's password.

## Seed the image corpus

Place the image files referenced by data/manifest.json in data/images.

From backend:

```powershell
..\.venv\Scripts\python.exe -m scripts.seed_images
```

The seed validates paths and provenance field formats, computes SHA-256
checksums, and rejects duplicate IDs or identical image files. It does not
verify attribution accuracy or license rights. Existing records with the
same file path and checksum are skipped; changed provenance fields are
not updated by a repeated seed run.

## Start the API

From backend:

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Interactive API documentation:
http://127.0.0.1:8000/docs

Health endpoint:
http://127.0.0.1:8000/health

## Create and process a batch job

In a second PowerShell window, navigate to backend:

```powershell
..\.venv\Scripts\python.exe -m scripts.create_batch_job
```

Copy the returned job_id, then substitute it below:

```powershell
..\.venv\Scripts\python.exe -m app.workers.runner --job-id YOUR_JOB_ID --max-items 3
```

The creation script uses the demo tenant and the
initial-image-processing idempotency key. Repeating it returns the
original job rather than creating another job for that key.

The worker stops when:

- It reaches --max-items.
- No eligible item is ready.
- An attempt is unsuccessful.
- The daily call allowance is unavailable.

Retries have an available_at delay. Rerun the worker when items are
eligible and provider quota is available. A budget block releases the
claim without consuming the image's processing attempt.

The worker uses at most three attempts per item and a 120-second claim
lease. Interrupted workers may leave claims processing until lease
recovery runs. SDK retries are disabled with attempts=0 in the installed
Interactions SDK; persistent job retries are managed by the worker.

The guard limits call reservations, not dollar spending or requests per
minute. A reservation is retained if the process crashes after reserving
it, even if the request never reaches Gemini. Provider rate-limit reset
times and Retry-After delays are not currently used by retry scheduling.

Expired claims are recovered when the worker starts. To run recovery
without contacting Gemini, substitute the job ID:

```powershell
..\.venv\Scripts\python.exe -c "from app.repositories.jobs import recover_expired_claims; print(recover_expired_claims('demo', 'YOUR_JOB_ID'))"
```

## Read job progress

With the API running, substitute the job ID:

```powershell
Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/jobs/YOUR_JOB_ID" `
    -Headers @{ "X-Tenant-ID" = "demo" } |
    ConvertTo-Json
```

A job unavailable under the supplied tenant returns HTTP 404.
A missing tenant header returns HTTP 422.

## Run tests

From backend, with PostgreSQL running and migrations applied:

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q
```

Database tests use temporary tenants. The tests do not require
available Gemini quota; mocked calls use no provider requests.

## Evidence and generated files

See EVIDENCE.md for observed results and BUILDLOG.md for development notes.

data/ai_calls.jsonl and data/processed are generated local artifacts
and are excluded from Git. Keep source manifests, posts, and evaluation
references tracked.

A completed classification passed schema validation and the configured
confidence threshold. It does not establish that the prediction is
correct; model confidence has not been calibrated.

## Preserve database data

The database uses a persistent Docker volume.

```powershell
docker compose stop db
```

stops the database without removing its stored data.

## Reprocess failed images

From backend, with database migrations applied:

```powershell
..\.venv\Scripts\python.exe -m scripts.create_reprocessing_job
```

Copy the returned job ID and pass it to the worker's --job-id option.
This script uses the fixed failed-image-reprocessing-v1 idempotency key.
Repeated execution returns the same job; it does not start another round.
Failed images receive new job items with fresh attempt allowances, while
the earlier failed job items and attempt counts remain unchanged.

## Reviewed dataset correction

Visual inspection found swapped provenance references for img_037 and
img_038. The manifest now attributes img_037 (three plates of food) to
Lily Banse and img_038 (vegetable salad bowl) to Anna Pelzer. post_009's
evaluation reference is img_038. Image files and model predictions were
not changed. This is a dataset-label correction, not a measured matching
accuracy result.

For an existing database seeded before the correction, run:

```powershell
..\.venv\Scripts\python.exe -m scripts.sync_reviewed_provenance
```

This checks registered image paths and checksums and synchronizes only
the two reviewed demo provenance records. A new seed uses the corrected
manifest directly. Ordinary repeated seeding does not update provenance.

## Download the original image dataset

The original corpus is packaged as the dataset-v1 GitHub release asset
image-relevance-images-v1.zip. Image attribution and licenses remain in
data/manifest.json. The archive and individual original-image hashes are
pinned in data/dataset.json. The release must be published before its
public download URL works.

From backend, restore the corpus after installing Python:

```powershell
..\.venv\Scripts\python.exe -m scripts.download_dataset
```

The downloader uses only Python's standard library, requires no API key
or database, verifies the archive and every image, and refuses to replace
different existing images. Registered original images and their checksums
are preserved. Installation uses hard links in a temporary staging area
on the destination filesystem (the current Windows NTFS setup supports
this); a filesystem without hard-link support cannot use this installer.

To check already-present images without downloading:

```powershell
..\.venv\Scripts\python.exe -m scripts.download_dataset --verify-only
```

To use the separately downloaded ZIP instead of a network request:

```powershell
..\.venv\Scripts\python.exe -m scripts.download_dataset --archive "PATH_TO_ZIP"
```

The code supports restoring images outside the repository with
--destination PATH. The seed and worker still use data/images unless
their configuration is changed separately. Downloading images does not
seed or change the database, classifications, or job history.

The archive is approximately 161 MB, so allow disk space for the archive,
temporary image staging, and the installed corpus. The pinned archive
SHA-256 is:

```text
0a95fae32a5925ba129b925a2608c2774ca42934d40ec28990661f31ff6d5dc6
```

The public dataset asset was downloaded and verified against all 50
original image checksums. data/images/ is ignored, and image removals
from Git tracking are staged for the dataset-delivery commit. Local
images remain intact. Earlier commits and the dataset-v1 tag still
contain image blobs; Git history has not been rewritten. A shallow
clone of the updated main branch avoids fetching that older history.

