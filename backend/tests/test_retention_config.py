"""M15.1 retention configuration tests (ADR 0013)."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


class TestRetentionDaysConfig:
    def test_default_retention_days_is_30(self):
        assert Settings(_env_file=None).retention_days == 30

    def test_environment_override_works(self, monkeypatch):
        monkeypatch.setenv("RETENTION_DAYS", "7")
        assert Settings(_env_file=None).retention_days == 7

    @pytest.mark.parametrize("bad_value", ["0", "-1", "-30"])
    def test_zero_or_negative_rejected(self, monkeypatch, bad_value):
        """Zero/negative must never be silently accepted (it could be read as
        'delete everything' or 'delete the future')."""
        monkeypatch.setenv("RETENTION_DAYS", bad_value)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_retention_cutoff_uses_configured_days(self):
        from datetime import UTC, datetime, timedelta

        from app.services.retention import retention_cutoff

        now = datetime.now(UTC)
        cutoff = retention_cutoff(now=now, retention_days=30)
        assert cutoff == now - timedelta(days=30)