from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

from app.schemas.upload import MAX_UPLOAD_BYTES


# Allow space for multipart boundaries and the creator field.
MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024


class LimitedUploadRequest(Request):
    async def stream(self):
        received = 0

        async for chunk in super().stream():
            received += len(chunk)

            if received > MAX_UPLOAD_REQUEST_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Upload request is too large",
                )

            yield chunk


class UploadLimitRoute(APIRoute):
    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def limited_handler(request: Request):
            if request.method != "POST":
                return await original_handler(request)

            content_length = request.headers.get("content-length")

            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid Content-Length",
                    ) from None

                if declared_size < 0:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid Content-Length",
                    )

                if declared_size > MAX_UPLOAD_REQUEST_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="Upload request is too large",
                    )

            limited_request = LimitedUploadRequest(
                request.scope,
                request.receive,
            )
            return await original_handler(limited_request)

        return limited_handler