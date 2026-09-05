"""Application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .core.errors import WorkspaceError
from .db import init_db
from .providers import bootstrap
from .providers.base import close_http_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger("workspace")


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap()
    init_db()
    from .core.registry import registry
    from .providers import CAPABILITIES

    health = registry.health(CAPABILITIES)
    for capability, entries in health.items():
        available = [e["name"] for e in entries if e["available"]]
        if available:
            log.info("%-18s → %s", capability, ", ".join(available))
        else:
            log.warning("%-18s → none available", capability)
    yield
    await close_http_client()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "An evidence-first research workspace. Every answer reports what was found, "
        "where it came from, and how certain it is."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(WorkspaceError)
async def workspace_error_handler(_: Request, exc: WorkspaceError) -> JSONResponse:
    """Surface *why* something could not be done — never a generic failure."""
    return JSONResponse(status_code=exc.status, content={"error": exc.to_dict()})


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic v2 puts the original exception object in ``ctx``; strip it so the
    # response stays JSON-serialisable while keeping the human-readable message.
    issues = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()[:8]
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_request",
                "message": issues[0]["message"] if issues else "The request could not be processed.",
                "detail": {"issues": issues},
            }
        },
    )


from .api.routes import (  # noqa: E402
    citations, data, diagrams, exports, files, health, projects, research,
)

for router in (
    health.router, projects.router, research.router, files.router,
    data.router, diagrams.router, citations.router, exports.router,
):
    app.include_router(router, prefix="/api")


@app.get("/")
def root() -> dict:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/api/health",
        "providers": "/api/providers",
        "principle": (
            "Every answer states what was found, where it came from, and how certain it is."
        ),
    }
