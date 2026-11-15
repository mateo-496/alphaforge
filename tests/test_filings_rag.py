import io
import json
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from tools import filings_rag


@pytest.fixture
def rag(monkeypatch):
    monkeypatch.setenv("KB_ID", "KB")
    monkeypatch.setenv("KB_DATA_SOURCE_ID", "DS")
    monkeypatch.setenv("S3_BUCKET", "filings-bucket")
    monkeypatch.setenv("KB_S3_PREFIX", "source/alphaforge_filings")
    objects = {}
    calls = []

    class S3:
        def head_object(self, Bucket, Key):
            if Key not in objects:
                raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

        def put_object(self, Bucket, Key, Body, **kwargs):
            objects[Key] = Body

        def get_object(self, Bucket, Key):
            return {"Body": io.BytesIO(objects[Key])}

    class Bedrock:
        def start_ingestion_job(self, **kwargs):
            calls.append(kwargs)
            return {"ingestionJob": {"ingestionJobId": "job1", "status": "STARTING"}}

        def get_ingestion_job(self, **kwargs):
            return {"ingestionJob": {"ingestionJobId": "job1", "status": "FAILED",
                                     "failureReasons": ["Ingestion failed"]}}

    s3, bedrock = S3(), Bedrock()
    monkeypatch.setattr(filings_rag.boto3, "client",
                        lambda service, **kwargs: s3 if service == "s3" else bedrock)
    monkeypatch.setattr(filings_rag, "_annual_filing", lambda ticker, as_of: SimpleNamespace(
        accession_no="0000000123-26-000001", form="10-K", filing_date="2026-02-25",
        filing_url="https://www.sec.gov/Archives/edgar/data/123/filing.htm"))
    monkeypatch.setattr(filings_rag, "_sec_get", lambda url: SimpleNamespace(
        content=b"<html><body>Actual risk text.<script>ignore</script></body></html>"))
    return objects, calls, s3, bedrock


def test_indexes_filing_and_starts_without_waiting(rag):
    objects, calls, _, _ = rag
    result = filings_rag.index_annual_filings(["NVDA"], "2026-11-14")
    key = "source/alphaforge_filings/NVDA/0000000123-26-000001.txt"
    assert objects[key] == b"Actual risk text."
    metadata = json.loads(objects[key + ".metadata.json"])["metadataAttributes"]
    assert metadata == result["filings"][0]
    assert result["ingestion_job_id"] == "job1"
    assert result["status"] == "STARTING"
    assert len(calls) == 1
    filings_rag.index_annual_filings(["NVDA"], "2026-11-14")
    assert len(objects) == 2
    assert len(calls) == 2


def test_knowledge_base_configuration_and_permissions_errors_are_visible(rag, monkeypatch):
    monkeypatch.delenv("KB_ID")
    with pytest.raises(ValueError, match="KB_ID"):
        filings_rag.index_annual_filings(["NVDA"], "2026-11-14")
    monkeypatch.setenv("KB_ID", "KB")
    monkeypatch.delenv("S3_BUCKET")
    with pytest.raises(ValueError, match="S3_BUCKET"):
        filings_rag.index_annual_filings(["NVDA"], "2026-11-14")


def test_index_status_reports_failure(rag):
    status = filings_rag.filing_index_status("job1")
    assert status["status"] == "FAILED"
    assert status["failure_reasons"] == ["Ingestion failed"]


def test_search_checks_filing_identity_and_archive_text(rag, monkeypatch):
    objects, _, s3, bedrock = rag
    index = filings_rag.index_annual_filings(["NVDA"], "2026-11-14")
    meta = index["filings"][0]
    key = "source/alphaforge_filings/NVDA/0000000123-26-000001.txt"
    results = [{"content": {"text": "Actual risk text."}, "metadata": meta,
                "location": {"s3Location": {"uri": f"s3://filings-bucket/{key}"}}, "score": 0.9}]

    class Runtime:
        def retrieve(self, **kwargs):
            filters = kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]["filter"]["andAll"]
            assert filters == [{"equals": {"key": "ticker", "value": "NVDA"}},
                               {"equals": {"key": "accession", "value": meta["accession"]}}]
            return {"retrievalResults": results}

    runtime = Runtime()
    monkeypatch.setattr(filings_rag.boto3, "client",
                        lambda service, **kwargs: {"s3": s3, "bedrock-agent": bedrock,
                                                   "bedrock-agent-runtime": runtime}[service])
    found = filings_rag.search_indexed_filing("NVDA", meta["accession"], "risk")
    assert found["passages"][0]["text"] == "Actual risk text."
    assert found["passages"][0]["source"]["url"] == meta["source_url"]
    results[0]["content"]["text"] = "Invented risk."
    with pytest.raises(ValueError, match="not verified"):
        filings_rag.search_indexed_filing("NVDA", meta["accession"], "risk")
    results[0]["content"]["text"] = "actual risk text."
    with pytest.raises(ValueError, match="not verified"):
        filings_rag.search_indexed_filing("NVDA", meta["accession"], "risk")
    results[0]["content"]["text"] = "Actual risk text."
    results[0]["location"]["s3Location"]["uri"] = "s3://filings-bucket/other.txt"
    with pytest.raises(ValueError, match="different filing"):
        filings_rag.search_indexed_filing("NVDA", meta["accession"], "risk")


def test_denied_ingestion_start_keeps_archived_filings(rag, monkeypatch):
    objects, _, _, bedrock = rag

    def denied(**kwargs):
        raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "StartIngestionJob")

    monkeypatch.setattr(bedrock, "start_ingestion_job", denied)
    result = filings_rag.index_annual_filings(["NVDA"], "2026-11-14")
    assert result["status"] == "SYNC_REQUIRED" and result["ingestion_job_id"] is None
    assert len(objects) == 2
