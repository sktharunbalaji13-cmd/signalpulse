import pytest
from app.core.config import settings
from app.db import session as db_session
from app.db.models import Base
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


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