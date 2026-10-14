"""Browser-facing protections for the loopback-only API."""
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class LocalOriginMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            ports = {"5173", "8000", os.getenv("WEB_PORT", "5173"), os.getenv("API_PORT", "8000")}
            trusted = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost") for port in ports}
            origin = request.headers.get("origin")
            # Local scripts have no Origin. Browsers must not write cross-site,
            # even when a simple request would otherwise bypass CORS preflight.
            if (origin is not None and origin not in trusted) or request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "不允许来自此网页的本地 API 写入请求"}, status_code=403)
        return await call_next(request)
