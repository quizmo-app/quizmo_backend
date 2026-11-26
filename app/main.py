"""FastAPI application factory and top-level health endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.auth.router import router as auth_router
from app.config import Settings
from app.database import init_db
from app.exceptions import register_exception_handlers
from app.insertions.router import router as insertions_router
from app.presentations.router import router as presentations_router
from app.quizzes.router import router as quizzes_router
from app.routers import cours


class MessageResponse(BaseModel):
    """Welcome message returned by the root endpoint."""

    message: str


class HealthResponse(BaseModel):
    """Health check payload."""

    status: str


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    runtime_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        init_db(runtime_settings.database_path)
        yield

    application = FastAPI(
        title="Quizmo API",
        version="0.1.0",
        description="Quizmo Backend API",
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    register_exception_handlers(application)

    application.include_router(auth_router)
    application.include_router(insertions_router)
    application.include_router(quizzes_router)
    application.include_router(presentations_router, prefix="/cours")
    application.include_router(presentations_router, prefix="/api/cours")
    application.include_router(cours.router)

    @application.get("/", response_model=MessageResponse, tags=["root"])
    async def read_root() -> MessageResponse:
        return MessageResponse(message="Welcome to Quizmo API")

    @application.get("/health", response_model=HealthResponse, tags=["health"])
    async def health_check() -> HealthResponse:
        return HealthResponse(status="ok")

    return application


app = create_app()
