import pytest

from core import config, llm, storage


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Tests never touch the shared S3 bucket, CloudTrail or the repo's data/ folder."""
    monkeypatch.setattr(config, "STORAGE", "local")
    monkeypatch.setattr(config, "CLOUDTRAIL_CHANNEL_ARN", "")
    monkeypatch.setattr(storage, "LOCAL_ROOT", tmp_path / "data")
    monkeypatch.setattr(llm, "TRACE_DIR", tmp_path / "traces")
