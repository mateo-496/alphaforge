"""JSON storage on local disk (./data/<key>) or S3 (STORAGE=s3), plus a 24-hour cache for public market data."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from core import config

LOCAL_ROOT = config.DATA_DIR


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


def _memo_key(namespace: str, ident: Any) -> str:
    raw = json.dumps(ident, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    return f"agent-cache/{namespace}/{hashlib.sha256(raw.encode()).hexdigest()}.json"


def memo_get(namespace: str, ident: Any) -> Any:
    """A saved agent answer for exactly this input (`ident`), or None. Never raises: a cache miss just costs a call."""
    if not config.LLM_CACHE:
        return None
    try:
        entry = read_json(_memo_key(namespace, ident))
        return entry["value"] if entry else None
    except Exception:
        return None


def memo_put(namespace: str, ident: Any, value: Any) -> None:
    """Save an agent answer under its exact input. No expiry: the input carries the data date, the model and the
    prompt, so new data or a new prompt is a new key."""
    if not config.LLM_CACHE:
        return
    try:
        write_json(_memo_key(namespace, ident), {"saved_at": datetime.now(timezone.utc).isoformat(), "value": value})
    except Exception:
        pass


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
