"""S3 cache for shared public market data, never for portfolio weights."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import boto3
from botocore.exceptions import ClientError


LOCAL_ROOT = Path("data")


def _local_cached(key: str, fetch: Callable[[], dict]) -> dict[str, Any]:
    """Same 24-hour reuse rule as S3, on local disk (./data/<key>), for development without a bucket."""
    path = LOCAL_ROOT / key
    if path.exists():
        entry = json.loads(path.read_text())
        age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["cached_at"])
        if timedelta(0) <= age < timedelta(hours=24):
            return entry["data"]
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cached_at": datetime.now(timezone.utc).isoformat(), "data": data}))
    return data


def cached(namespace: str, params: dict, fetch: Callable[[], dict]) -> dict[str, Any]:
    """S3 cache when S3_BUCKET is set; local disk otherwise (MARKET_CACHE=s3 makes S3 mandatory)."""
    identity = json.dumps({"version": 1, "namespace": namespace, "params": params},
                          sort_keys=True, separators=(",", ":"))
    key = f"market-cache/v1/{namespace}/{hashlib.sha256(identity.encode()).hexdigest()}.json"
    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        if os.environ.get("MARKET_CACHE") == "s3":
            raise ValueError("S3_BUCKET must be set for the shared market data cache")
        return _local_cached(key, fetch)
    client = boto3.client("s3")
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("NoSuchKey", "404"):
            raise
    else:
        entry = json.loads(response["Body"].read())
        cached_at = datetime.fromisoformat(entry["cached_at"])
        if cached_at.tzinfo is None:
            raise ValueError("Cached timestamp has no timezone")
        age = datetime.now(timezone.utc) - cached_at
        if timedelta(0) <= age < timedelta(hours=24):
            return entry["data"]
    data = fetch()
    entry = {"cached_at": datetime.now(timezone.utc).isoformat(), "data": data}
    client.put_object(Bucket=bucket, Key=key, Body=json.dumps(entry).encode("utf-8"),
                      ContentType="application/json", ServerSideEncryption="AES256")
    return data
