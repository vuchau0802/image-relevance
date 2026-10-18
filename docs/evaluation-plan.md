# Evaluation and hardening plan

## Frozen baseline

- Code commit: a518b4f82679ff782c55ded4809a7dbe4707e838
- Embedding model: gemini-embedding-001
- Dimensions: 768
- Task type: SEMANTIC_SIMILARITY
- Minimum match similarity: 0.85
- Subject guard: the implementation at the baseline commit
- Image corpus: the existing 50-image dataset

## Evaluation scope

Evaluate new post queries against the fixed image corpus.

This measures performance on new queries. It does not establish
generalization to unseen images or an independent image dataset.

The original 11 posts are regression cases.
The six calibration posts were used to select the threshold.
Neither set counts as held-out evaluation.

## Labeling rules

Create at least 12 new posts:

- Eight posts with one or more suitable corpus images.
- Four posts with no suitable corpus image.
- Cover animals, vehicles, food, and landscapes.
- Include cases with the right general subject but the wrong activity
  or setting.

Review the actual images before assigning labels.
Record every acceptable image ID, rather than forcing one answer when
several images satisfy the post.

Freeze the labels before viewing ranking scores or predictions.

Do not put expected image IDs or evaluation labels into embedding text.

## Evaluation rules

Do not change the threshold, aliases, prompts, or ranking code after
viewing held-out results.

Record failures without correcting labels merely to match predictions.

A genuine labeling correction must be documented with its reason.
If results influence implementation changes, that set becomes development
data; a new untouched set is required for another held-out claim.

Missing embeddings or unsupported execution states are evaluation errors,
not successful no-match decisions.

## Metrics

Report counts and denominators alongside percentages:

- Top-1 match rate: correct accepted top images divided by matchable posts.
  Abstentions count as failures.
- Accepted top-prediction precision: correct accepted predictions divided
  by all accepted predictions.
- Coverage: accepted predictions divided by all evaluated posts.
- Correct no-match rejection rate: correctly rejected negative posts
  divided by all negative posts.
- False acceptances and false rejections.

Report calibration, regression, and held-out results separately.
