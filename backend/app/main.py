from fastapi import FastAPI

from app.api.jobs import router as jobs_router
from app.api.recommendations import router as recommendations_router
from app.api.images import router as images_router
from app.api.posts import router as posts_router

app = FastAPI(
    title="Image Relevance API",
    version="0.1.0",
)

app.include_router(jobs_router)
app.include_router(recommendations_router)
app.include_router(images_router)
app.include_router(posts_router)

@app.get("/health")
def health():
    return {"status": "ok"}