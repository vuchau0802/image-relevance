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

Still to implement and demonstrate: persisted background jobs and retries, failure reporting, database migrations and tenant isolation, idempotent processing, budget enforcement, stored image/post embeddings, ranked matching, subject-mismatch rejection, no-confident-match behavior, review endpoints, and measured evaluation results.

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
- Latest job summary: 49 total, 4 completed, 45 pending,
  0 processing, 0 needs_review, and 0 failed.
- Including img_001, processed separately, 5 corpus images have completed.
- AI call logs include image ID, job ID, attempt, status, and token
  usage when returned. Failed calls had no reported token counts.

### Automated validation

Command:
python -m pytest tests -q

Result: 23 passed, 1 Google SDK deprecation warning.

Four database integration tests cover expired-claim recovery,
final-attempt lease exhaustion, completion with duplicate-completion
rejection, and rejection of a claim under a different tenant.

### Remaining work

The batch is still running. Full-corpus processing, a shared budget
guard, embeddings, matching, and evaluation are not yet verified.