# Image Relevance Engine — Design

## Problem
Given an image library and an article, recommend images that match
the article's meaning. Reject misleading images and return
"no confident match" when no suitable image exists.

## Scope
- Approximately 50 images across five subject groups.
- At least 10 manually labeled articles.
- One vision model and one embedding model.
- Background image processing.
- Image recommendations with explanations.
- Human approval and rejection.
- A small React frontend after the backend works.

## Non-goal
Automatic image generation is outside the initial scope.

## Technology
- Backend: Python and FastAPI.
- Validation: Pydantic.
- Database: PostgreSQL.
- Database access: SQLAlchemy.
- Migrations: Alembic.
- Similarity calculation: NumPy.
- Processing: separate Python worker with persisted jobs.
- Frontend: React and TypeScript.
- AI provider: Gemini free-tier models or local Ollama.
- Exact model names will be configuration values.

## Image metadata
Every vision response must satisfy this structure:

```json
{
  "subject": "red fox",
  "category": "animal",
  "attributes": ["orange fur", "forest"],
  "caption": "A red fox standing in a forest",
  "confidence": 0.94
}
```

Validation rules:
- All fields are required.
- Subject, category, and caption must be nonempty strings.
- Attributes must be a list of strings.
- Confidence must be between 0 and 1.
- Invalid output is retried or marked failed.
- Low-confidence output is flagged for human review.