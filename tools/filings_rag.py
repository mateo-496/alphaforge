"""Archive SEC annual filings and retrieve verified passages through a shared Knowledge Base."""
import json
import os
import re
from datetime import date, datetime, timezone

import boto3
from botocore.exceptions import ClientError
from bs4 import BeautifulSoup

from tools.filings import _annual_filing
from tools.market_data import _sec_get, _validate_ticker

_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_SEC_URL = re.compile(r"^https://www\.sec\.gov/Archives/edgar/data/\d+/[A-Za-z0-9._/-]+$")


def _settings():
    kb_id = os.environ.get("KB_ID", "").strip()
    source_id = os.environ.get("KB_DATA_SOURCE_ID", "").strip()
    if not kb_id or not source_id:
        raise ValueError("KB_ID and KB_DATA_SOURCE_ID are required for filing RAG")
    region = os.environ.get("AWS_REGION", "us-east-1")
    return kb_id, source_id, region


def _source_location() -> tuple[str, str]:
    bucket = os.environ.get("S3_BUCKET", "").strip()
    if not bucket:
        raise ValueError("S3_BUCKET is required for filing RAG")
    prefix = os.environ.get("KB_S3_PREFIX", "alphaforge_filings").strip("/") + "/"
    if any(part in (".", "..") for part in prefix.split("/")):
        raise ValueError("Invalid KB_S3_PREFIX")
    return bucket, prefix


def _exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    return True


def index_annual_filings(tickers: list[str], as_of: str) -> dict:
    """Archive latest eligible annual filings and start an asynchronous KB ingestion job."""
    date.fromisoformat(as_of)
    if not tickers or len(tickers) != len(set(tickers)):
        raise ValueError("tickers must be a non-empty list of unique symbols")
    kb_id, source_id, region = _settings()
    bucket, prefix = _source_location()
    s3 = boto3.client("s3", region_name=region)
    archived = []
    for ticker in tickers:
        _validate_ticker(ticker)
        filing = _annual_filing(ticker, as_of)
        accession = filing.accession_no
        url = filing.filing_url
        if not _ACCESSION.fullmatch(accession) or not _SEC_URL.fullmatch(url):
            raise ValueError(f"Invalid SEC source metadata for {ticker}")
        metadata = {"ticker": ticker, "accession": accession, "form": filing.form,
                    "filing_date": str(filing.filing_date), "source_url": url}
        key = f"{prefix}{ticker}/{accession}.txt"
        metadata_key = key + ".metadata.json"
        if not _exists(s3, bucket, key) or not _exists(s3, bucket, metadata_key):
            soup = BeautifulSoup(_sec_get(url).content, "html.parser")
            for element in soup(["script", "style"]):
                element.decompose()
            text = soup.get_text("\n", strip=True)
            if not text:
                raise ValueError(f"SEC filing is empty for {ticker}")
            body = text.encode("utf-8")
            if len(body) > 50 * 1024 * 1024:
                raise ValueError(f"SEC filing exceeds the Knowledge Base size limit for {ticker}")
            s3.put_object(Bucket=bucket, Key=key, Body=body,
                          ContentType="text/plain; charset=utf-8", ServerSideEncryption="AES256")
            s3.put_object(Bucket=bucket, Key=metadata_key,
                          Body=json.dumps({"metadataAttributes": metadata}).encode("utf-8"),
                          ContentType="application/json", ServerSideEncryption="AES256")
        archived.append(metadata)
    agent = boto3.client("bedrock-agent", region_name=region)
    try:
        job = agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=source_id)["ingestionJob"]
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in ("AccessDeniedException", "AccessDenied"):
            raise
        # Files are already in S3: the role may not start syncs, so one must be started
        # manually (console: Knowledge Base > data source > Sync).
        return {"filings": archived, "ingestion_job_id": None, "status": "SYNC_REQUIRED"}
    return {"filings": archived, "ingestion_job_id": job["ingestionJobId"], "status": job["status"]}


def filing_index_status(ingestion_job_id: str) -> dict:
    """Get the ingestion status without waiting for completion."""
    kb_id, source_id, region = _settings()
    if not ingestion_job_id.strip():
        raise ValueError("ingestion_job_id must not be empty")
    agent = boto3.client("bedrock-agent", region_name=region)
    job = agent.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=source_id,
                                  ingestionJobId=ingestion_job_id)["ingestionJob"]
    return {"ingestion_job_id": job["ingestionJobId"], "status": job["status"],
            "statistics": job.get("statistics", {}), "failure_reasons": job.get("failureReasons", [])}


def search_indexed_filing(ticker: str, accession: str, query: str) -> dict:
    """Retrieve passages from one specific filing and check them against the S3 archive."""
    _validate_ticker(ticker)
    if not _ACCESSION.fullmatch(accession) or not query.strip():
        raise ValueError("A valid SEC accession and non-empty query are required")
    kb_id, source_id, region = _settings()
    bucket, prefix = _source_location()
    key = f"{prefix}{ticker}/{accession}.txt"
    text = boto3.client("s3", region_name=region).get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    result = boto3.client("bedrock-agent-runtime", region_name=region).retrieve(
        knowledgeBaseId=kb_id, retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {
            "numberOfResults": 8, "filter": {"andAll": [
                {"equals": {"key": "ticker", "value": ticker}},
                {"equals": {"key": "accession", "value": accession}},
            ]}}})
    passages = []
    for item in result["retrievalResults"]:
        metadata = item.get("metadata", {})
        uri = item.get("location", {}).get("s3Location", {}).get("uri")
        if metadata.get("ticker") != ticker or metadata.get("accession") != accession or uri != f"s3://{bucket}/{key}":
            raise ValueError("Knowledge Base returned a passage from a different filing")
        excerpt = item["content"].get("text", "").strip()
        if not excerpt or excerpt not in text:
            raise ValueError("Knowledge Base returned a passage not verified against the S3 archive")
        url = metadata.get("source_url", "")
        if not _SEC_URL.fullmatch(url):
            raise ValueError("Knowledge Base returned an invalid SEC source URL")
        passages.append({"text": excerpt, "retrieval_score": item.get("score"),
                         "source": {"title": f"{ticker} {metadata['form']} filed {metadata['filing_date']}",
                                    "url": url, "locator": f"SEC accession {accession}; retrieved passage",
                                    "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}})
    return {"ticker": ticker, "accession": accession, "passages": passages}
