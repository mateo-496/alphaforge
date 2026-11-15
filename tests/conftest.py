import pytest

from storage import s3_service


@pytest.fixture(autouse=True)
def no_real_s3(monkeypatch):
    """Tests must never read or write the shared S3 bucket configured in .env."""
    monkeypatch.setattr(s3_service, "S3_BUCKET", "")


@pytest.fixture(autouse=True)
def no_real_country_risk_inputs(monkeypatch):
    """The country risk agent falls back to the macro score when GPR/OFR data cannot be fetched."""
    from tools import country_risk_inputs

    def offline(*args, **kwargs):
        raise RuntimeError("network disabled in tests")
    monkeypatch.setattr(country_risk_inputs, "_gpr_frame", offline)
    monkeypatch.setattr(country_risk_inputs, "stress_percentile", offline)
