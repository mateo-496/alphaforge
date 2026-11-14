"""S3 cache for shared public market data, never for portfolio weights."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import boto3
from botocore.exceptions import ClientError


def cached(namespace: str, params: dict, fetch: Callable[[], dict]) -> dict[str, Any]:
    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        raise ValueError("S3_BUCKET must be set for the shared market data cache")
    identity = json.dumps({"version": 1, "namespace": namespace, "params": params},
                          sort_keys=True, separators=(",", ":"))
    key = f"market-cache/v1/{namespace}/{hashlib.sha256(identity.encode()).hexdigest()}.json"
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
