
# Image Relevance

A local application for uploading images and finding suitable matches for blog
posts. Built with React, TypeScript, FastAPI, PostgreSQL, Clerk, and Gemini.
Matching uses cached embeddings, a subject guard, and cosine similarity;
the application abstains when no candidate meets its threshold.

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

## Features

- Sign-in with account-owned workspaces and authenticated content access.
- Create, edit, delete, and prepare posts for matching.
- Upload JPEGs, analyze them, prepare embeddings, and browse private images.
- Retry failed processing while preserving job history.
- Delete images with durable background file cleanup.
- Per-workspace image limits, daily AI-call allowances, and call auditing.

## Local setup

Requires Python 3.14, Node.js/npm compatible with the locked dependencies,
Docker Desktop with Compose, a Clerk application, and Gemini API access.

From the project root in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

For a new installation only, copy the environment examples. Do not overwrite
existing local configuration:

```powershell
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env.local
```

Configure the root `.env` with database credentials, Gemini settings,
`CLERK_ISSUER`, and `CLERK_AUTHORIZED_PARTIES`. Set
`VITE_CLERK_PUBLISHABLE_KEY` in `frontend/.env.local` using the same Clerk
application. Authorized parties must include the exact browser origin.
The example includes `http://127.0.0.1:8000` and `http://127.0.0.1:5173`.
Keep both local environment files out of Git.

The default image limit is 100 registered images per workspace, configurable
with `MAX_IMAGES_PER_WORKSPACE`. Duplicates remain allowed at capacity.
Changing `POSTGRES_PASSWORD` does not change an existing database password.

Build the frontend:

```powershell
cd frontend
npm.cmd ci
npm.cmd run build
cd ..
```

## Run

From the project root, start PostgreSQL, apply migrations, and launch FastAPI:

```powershell
.\.venv\Scripts\python.exe backend/scripts/run_demo.py
```

In a separate terminal, start the worker:

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.workers.workspace_runner
```

Keep both processes running. The worker handles analysis, embeddings, expired
claims, and image file cleanup. Stop with Ctrl+C. Rebuild and restart the API
after frontend changes; restart the worker after worker code changes.

Open [the app](http://127.0.0.1:8000),
[API documentation](http://127.0.0.1:8000/docs), or
[health check](http://127.0.0.1:8000/api/health).
For frontend development, run `npm.cmd run dev` from `frontend` and open
[Vite](http://127.0.0.1:5173) while the backend and worker remain running.

Sign in, create a post, upload a JPEG, analyze the image, prepare both
embeddings, and view the matches. New accounts start with their own content;
seeded demo data is not automatically assigned to them. Content APIs use
Clerk bearer tokens; `X-Tenant-ID` does not authorize access.

Uploads are limited to JPEG, 10 MiB, and 20 million pixels. Files are
normalized and stored privately under `data/uploads/<workspace>/`.
Queued or running work blocks deletion. Deleting an image removes API access
immediately; physical removal follows when the worker processes cleanup.

The optional corpus preparation command is
`.\.venv\Scripts\python.exe backend/scripts/seed_demo.py` from the root.
It may download data and make quota-consuming provider calls; it is separate
from the private-account upload workflow.

## Verify

Backend checks, from `backend`:

```powershell
..\.venv\Scripts\python.exe -m pytest tests -q --tb=short
docker compose -f ..\docker-compose.test.yml -p image-relevance-tests up -d --wait
..\.venv\Scripts\python.exe -m scripts.run_integration_tests
```

The first command skips database integration tests. The full runner uses the
isolated `_test` database on port 55432, applies migrations, and uses fake
provider responses. It does not use the persistent demo database.

Frontend checks, from `frontend`:

```powershell
npm.cmd test
npm.cmd run build
npm.cmd run lint
```

Latest user-run results: **805 backend tests**, **130 frontend tests**, build,
and lint passed. Two existing backend dependency deprecation warnings remain.
The manual two-account demo verified owner access, cross-account rejection,
unauthenticated rejection, editing, deletion, and the signed-out UI.

## Limits and project notes

- Similarity is not a correctness probability. Subject aliases are finite,
  descriptions can be wrong, and context mismatches remain possible.
- The original new-query evaluation passed **9/12** cases. Later development
  checks do not replace that result. See the linked evaluation report.
- This is locally verified, not publicly deployed. Production storage,
  HTTPS, backups, monitoring, worker supervision, request rate limits, and
  shared provider budgets remain future work.
- The image limit counts registered records, not disk bytes. Failed cleanup
  or uncertain commits can leave orphan files; reconciliation is not automated.
- Automated retry tests pass; live failed-job retry verification remains
  pending because no suitable failed jobs were available in the demo.
- The UI uses the original ranker; the separate context pilot is not wired
  into it. Human review APIs and a full automated browser suite are unfinished.
- Daily reservations do not replace provider quotas. A configured zero-cost
  estimate is not verified billing.

Further details: [design](docs/DESIGN.md),
[evaluation plan](docs/evaluation-plan.md),
[evaluation results](docs/phase4-results.md),
[preserved first-run report](docs/evidence/heldout-first-run.json), and
[development log / AI assistance](BUILDLOG.md).

The demo database persists in its Docker volume. `docker compose stop db`
preserves its data. Source image licenses apply separately from the code
license; image provenance is available through attribution.
