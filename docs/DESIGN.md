# Image Relevance Engine — Design

## Problem
Find suitable images for blog articles based on image content.
Reject misleading matches and return "no confident match" when
no suitable image exists.

## Scope and stack
Approximately 50 images across four categories.
Python, FastAPI, Pydantic, PostgreSQL, SQLAlchemy, and Alembic.
One vision model and one embedding model, configured through environment
variables. Use a verified free-tier provider or local Ollama.
A React frontend will be added after the backend works.

## Architecture
HTTP routes validate requests and call service functions.
Services implement vision processing, matching, and guard decisions.
The database stores images, posts, metadata, vectors, jobs, and reviews.
A separate worker processes persisted background jobs.

Images → validated vision metadata → description embeddings
Posts → article embeddings
Vectors → similarity ranking → mismatch guard → suggestions → review

## Image metadata
Required fields: subject, category, attributes, caption, confidence.
Confidence must be between 0 and 1.
Invalid responses are retried, then marked failed.
Low-confidence results are flagged for human review.

## Database
Tables: images, image_metadata, tags, image_tags, posts, embeddings,
jobs, job_items, suggestions, reviews, ai_calls.
Records are tenant-scoped. Index foreign keys and job status.
Store image checksums and embedding model versions.
Unique processing keys prevent duplicate results after retries.

## Matching and guard
Embed image descriptions and article text using one embedding model.
Rank candidates using cosine similarity.
Articles initially provide an explicit required_subject.
Normalize known aliases, including Vulpes vulpes → red fox.
Reject uncertain metadata, incompatible subjects, and low similarity.
Thresholds are configurable and will be tuned using development labels.
Every rejection includes a readable explanation.

## API
GET /health
POST /images
GET /images
POST /posts
POST /jobs/process-images
GET /jobs/{id}
GET /posts/{id}/images
GET /suggestions/{id}
POST /suggestions/{id}/review

## Reliability and cost
Jobs record progress, attempts, and terminal errors.
Temporary failures use limited retries with backoff.
Every AI attempt records usage when available, cost, and outcome.
Configure call limits and a spending guard.
Secrets stay in environment variables and are never logged.

## Evaluation
The initial dataset contains 50 images:
20 animals, 10 vehicles, 10 food images, and 10 landscapes.

There are 11 example articles:
10 with a manually selected correct image and one penguin article
expected to return "no confident match".

Evaluation labels live in data/evaluation.json and are never
used by the matching pipeline.

Report top-1 accuracy on the 10 matchable articles.
Report the no-match case separately.
Test forced wolf rejection for a fox article.

Tune thresholds on a development subset, then measure results
on an untouched evaluation subset.

## Non-goal
Automatic image generation is outside the initial scope.