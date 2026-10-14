from fastapi import FastAPI

from app.api.jobs import router as jobs_router


app = FastAPI(
    title="Image Relevance API",
    version="0.1.0",
)

app.include_router(jobs_router)


@app.get("/health")
def health():
    return {"status": "ok"}