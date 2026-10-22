from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.api.images import router as images_router
from app.api.jobs import router as jobs_router
from app.api.posts import router as posts_router
from app.api.recommendations import router as recommendations_router
from app.config import PROJECT_ROOT
from app.api.auth import router as auth_router
from app.api.embedding_jobs import router as embedding_jobs_router

def create_app(frontend_dir: Path | None = None) -> FastAPI:
    application = FastAPI(
        title="Image Relevance API",
        version="0.1.0",
    )

    routers = (
        jobs_router,
        recommendations_router,
        images_router,
        posts_router,
        auth_router,
        embedding_jobs_router,
    )

    for router in routers:
        # Preserve existing CLI/demo API URLs.
        application.include_router(router)

        # Same-origin URLs used by the frontend.
        application.include_router(router, prefix="/api")

    @application.get("/health")
    @application.get("/api/health")
    def health():
        return {"status": "ok"}

    build_directory = (
        frontend_dir
        if frontend_dir is not None
        else PROJECT_ROOT / "frontend" / "dist"
    )

    # Register static serving after every API route.
    if (build_directory / "index.html").is_file():
        application.mount(
            "/",
            StaticFiles(directory=build_directory, html=True),
            name="frontend",
        )
    else:
        @application.get("/", include_in_schema=False)
        def frontend_unavailable():
            raise HTTPException(
                status_code=503,
                detail="Frontend build unavailable. Run npm run build in frontend.",
            )

    return application


app = create_app()