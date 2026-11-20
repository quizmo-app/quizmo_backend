from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    application = FastAPI(
        title="Quizmo API",
        version="0.1.0",
        description="Quizmo Backend API",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.get("/", response_model=MessageResponse, tags=["root"])
    async def read_root() -> MessageResponse:
        return MessageResponse(message="Welcome to Quizmo API")

    @application.get("/health", response_model=HealthResponse, tags=["health"])
    async def health_check() -> HealthResponse:
        return HealthResponse(status="ok")

    return application


app = create_app()
