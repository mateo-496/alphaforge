import pytest

from storage import s3_service


@pytest.fixture(autouse=True)
def no_real_s3(monkeypatch):
    """Tests must never read or write the shared S3 bucket configured in .env."""
    monkeypatch.setattr(s3_service, "S3_BUCKET", "")
