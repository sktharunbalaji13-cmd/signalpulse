from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    db: str


def _db_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - readiness must not raise
        return False


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness + readiness.

    Returns HTTP 200 with ``status=ok`` only when the database is reachable, so
    a platform health check can rely on it. If the DB is down the endpoint
    reports ``status=degraded`` with HTTP 503 (not-ready).
    """
    db_ready = _db_ready()
    if not db_ready:
        raise HTTPException(
            status_code=503,
            detail={"status": "degraded", "db": "down"},
        )
    return HealthResponse(
        status="ok",
        service="signalpulse-api",
        version=settings.app_version,
        db="ok",
    )
