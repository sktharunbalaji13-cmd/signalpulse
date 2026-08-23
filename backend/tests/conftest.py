import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db import session as db_session
from app.db.models import Base
from app.main import app


@pytest.fixture(autouse=True)
def clean_secrets(monkeypatch):
    """Keep every test offline and hermetic regardless of local .env.

    Real credentials in backend/.env must never leak into test runs (e.g. a
    live Guardian/Reddit request). Tests that need credentials set them
    explicitly via their own fixtures.
    """
    monkeypatch.setattr(settings, "guardian_api_key", "")
    monkeypatch.setattr(settings, "reddit_client_id", "")
    monkeypatch.setattr(settings, "reddit_client_secret", "")


@pytest.fixture(autouse=True)
def disable_semantic_stage(monkeypatch):
    """M11.1: keep the semantic stage off unless a test opts in, so unrelated
    tests never load the model or pay inference cost."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "semantic_enabled", False)


@pytest.fixture(autouse=True)
def admin_test_key(monkeypatch):
    """M14.1: set a known admin API key for every test so authenticated
    endpoints are accessible without per-test setup. Auth-specific tests
    override this value as needed."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Start each test with an empty rate-limit bucket (the limiter is a
    process-wide singleton keyed by client IP, so it must not accumulate
    across tests or later POSTs would spuriously 429)."""
    from app.services.rate_limit import reset_limiter

    reset_limiter()
    yield
    reset_limiter()


@pytest.fixture()
def session_factory(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db_session, "SessionLocal", testing_session)
    return testing_session


@pytest.fixture()
def client(session_factory):
    return TestClient(app)