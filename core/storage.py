"""JSON storage on local disk (./data/<key>) or S3 (STORAGE=s3), plus a 24-hour cache for public market data."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from core import config

LOCAL_ROOT = Path("data")


def _s3():
    import boto3
    if not config.S3_BUCKET:
        raise RuntimeError("STORAGE=s3 needs S3_BUCKET")
    return boto3.client("s3", region_name=config.REGION)


def write_json(key: str, obj) -> None:
    text = json.dumps(obj, indent=2, default=str)
    if config.STORAGE == "s3":
        _s3().put_object(Bucket=config.S3_BUCKET, Key=key, Body=text.encode(), ContentType="application/json")
    else:
        p = LOCAL_ROOT / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def read_json(key: str):
    """The stored object, or None if the key does not exist."""
    if config.STORAGE == "s3":
        from botocore.exceptions import ClientError
        try:
            return json.loads(_s3().get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read())
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
    p = LOCAL_ROOT / key
    return json.loads(p.read_text()) if p.exists() else None


def list_keys(prefix: str) -> list[str]:
    if config.STORAGE == "s3":
        keys, pager = [], _s3().get_paginator("list_objects_v2")
        for page in pager.paginate(Bucket=config.S3_BUCKET, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return sorted(keys)
    root = LOCAL_ROOT / prefix
    return sorted(p.relative_to(LOCAL_ROOT).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []


def cached(namespace: str, params: dict, fetch: Callable[[], Any], hours: int = 24) -> Any:
    """fetch() result, reused for `hours`. For public data only (prices, SEC tables, FRED), never portfolios."""
    ident = json.dumps({"namespace": namespace, "params": params}, sort_keys=True, separators=(",", ":"))
    key = f"market-cache/v2/{namespace}/{hashlib.sha256(ident.encode()).hexdigest()}.json"
    entry = read_json(key)
    if entry:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["cached_at"])
        if timedelta(0) <= age < timedelta(hours=hours):
            return entry["data"]
    data = fetch()
    write_json(key, {"cached_at": datetime.now(timezone.utc).isoformat(), "data": data})
    return data
