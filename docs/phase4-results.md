# Phase 4: Evaluation and hardening results

## Frozen evaluation setup

- Baseline code commit: a518b4f82679ff782c55ded4809a7dbe4707e838.
- Embedding model: gemini-embedding-001; 768 dimensions;
  SEMANTIC_SIMILARITY; minimum match similarity 0.85.
- Twelve assistant-authored new post queries: eight matchable and four
  no-match cases, with labels visually reviewed and confirmed by the user.
- Labels and settings were frozen before viewing predictions. The runner
  verified the label hash, protected implementation paths, settings, and
  stored post text before scoring cached embeddings.
- This is a prospective new-query check on the existing development corpus,
  not an independently authored benchmark or an unseen-image evaluation.
- Current source-input hashes were captured at evaluation time. They were
  not separately frozen with the labels.

## First-run results

| Metric | Count | Rate |
|---|---:|---:|
| Correct accepted top matches / matchable posts | 6/8 | 75% |
| Accepted top-prediction precision | 6/7 | 85.7% |
| Coverage / all posts | 7/12 | 58.3% |
| Correct no-match rejection | 3/4 | 75% |
| Overall cases passed | 9/12 | 75% |

There were two false rejections and one incorrect acceptance. The matchable
post metric counts abstentions as failures; it is not an unthresholded
ranking-only top-1 score. Calibration (6/6) and earlier regression (10/11)
remain separate results and are not pooled with this set.

## Error analysis

| Case | Observed behavior | Explanation |
|---|---|---|
| eval_005 | Volkswagen Beetle case rejected | A subject-compatible image existed, but none met 0.85. |
| eval_006 | Motor scooter case rejected | A subject-compatible image existed, but none met 0.85. |
| eval_009 | img_002 incorrectly accepted at 0.8526444045396087 | The fox subject passed, but the required snowy setting was absent. |

The original baseline and first-run report remain unchanged. A separate
context-aware development pilot was subsequently added using inspected
failures. Those cases now inform development and do not support a new
held-out accuracy claim. The original ranker, labels, and threshold remain
unchanged.
The snowy-fox failure demonstrates that subject compatibility does not
establish activity or setting compatibility. The two false rejections show
that a single global threshold can also exclude suitable images.

## Preserved evidence and reproduction

- Baseline: [heldout-baseline.json](heldout-baseline.json).
- First-run report: [heldout-first-run.json](evidence/heldout-first-run.json).
- The user verified matching SHA-256 hashes for the generated and preserved
  reports. The report runner refuses to overwrite an existing first report.
- Seed with scripts.seed_heldout and embed eval_001 through eval_012. Labels
  and label reasons are excluded from the post embedding text.
- scripts.evaluate_heldout checks the frozen baseline and uses cached
  embeddings; it makes no Gemini requests. Run it only when no first report
  already exists. Preserve the committed original when reproducing elsewhere.

## Usage and cost accounting

At the user-supplied audit snapshot:

- 79 completed gemini-embedding-001 calls were recorded: 67 earlier calls
  and 12 evaluation-post calls.
- None had input or output token usage populated. NULL means unknown usage,
  not zero usage; no token-based paid-tier total can be derived from this data.
- The application estimate was USD 0 with cost basis:
  Configured free-tier estimate; not verified billing.
- The user supplied an AI Studio table showing the project's Free tier.
  That tier evidence supports the configured estimate but is not a verified
  provider billing statement.
- No vision rows appeared in that database audit query. Historical vision
  evidence is separate; the embedding audit is not a total project-cost ledger.
- Application daily guards cap reservations per tenant and UTC day, not
  dollar spending. Google limits are project-scoped and daily request quotas
  reset at midnight Pacific time; these windows are separate.
- A batch worker here is an application worker using standard requests,
  not Google's separately priced Batch API.

Official references checked during this phase:
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) and
[Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).
Exact model pricing and project quotas must be checked before a paid-tier
change; no unverified paid-model rate is asserted here.

## Final verification

User-run checks:

- pip check: No broken requirements found.
- alembic check: No new upgrade operations detected.
- Latest integration suite: 302 passed, two existing dependency deprecation
  warnings, in 8.89 seconds. The earlier first-run checkpoint was 261
  passed in 7.28 seconds.
- Demo readiness: true, 50 expected images and 11 original posts,
  no source issues and no missing current embeddings.

Fresh miniature-corpus preparation, budget-block resumption, and persisted
vision retry are tested with fake provider responses. The live demo
preparation reused existing data; full-corpus preparation with the live
provider is not claimed. Subject rules remain corpus-specific and ranking
still uses repeated cache lookups. These measured limitations are retained.

First-run report SHA-256: `59b59fb4128993645af416bcdbba4ef2e2517a5bd1160fca36cb548ef48c1606`.

## Subsequent development results

- Reviewed context was imported for three posts and seven images;
  repeating the import created no duplicates.
- The separate context pilot rejected eval_009 because the three
  threshold-passing fox candidates contradicted the snow requirement.
- eval_005 and eval_006 remain rejected at 0.85, with similarities
  0.823373 and 0.845849. Their context checks are not reached because
  the original ranker returns no threshold-passing candidates.
- Eight reviewed vehicle development queries passed with the original
  ranker: four correct matches and four correct no-match rejections.
  See [the vehicle development baseline](evidence/vehicle-development-baseline.json).
- These queries were written after inspecting the corpus. The 8/8
  result is a development check, not independent held-out accuracy.
- The 79-call cost snapshot above predates the eight subsequent vehicle
  query embedding calls and is not a current cumulative usage total.
