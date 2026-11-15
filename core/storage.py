"""Local disk vs S3, switched by STORAGE env var. Keys are the same in both: 'scenarios/global/latest.json'."""
import json
from pathlib import Path

from core import config

LOCAL_ROOT = Path("data")


def _s3():
    import boto3
    if not config.S3_BUCKET:
        raise RuntimeError("STORAGE=s3 needs S3_BUCKET")
    return boto3.client("s3", region_name=config.REGION)


def write_text(key: str, text: str) -> None:
    if config.STORAGE == "s3":
        _s3().put_object(Bucket=config.S3_BUCKET, Key=key, Body=text.encode(), ContentType="application/json")
    else:
        p = LOCAL_ROOT / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def read_text(key: str) -> str:
    if config.STORAGE == "s3":
        return _s3().get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read().decode()
    return (LOCAL_ROOT / key).read_text()


def exists(key: str) -> bool:
    if config.STORAGE == "s3":
        from botocore.exceptions import ClientError
        try:
            _s3().head_object(Bucket=config.S3_BUCKET, Key=key)
            return True
        except ClientError:
            return False
    return (LOCAL_ROOT / key).exists()


def list_keys(prefix: str) -> list[str]:
    """All keys under a prefix, sorted."""
    if config.STORAGE == "s3":
        keys, pager = [], _s3().get_paginator("list_objects_v2")
        for page in pager.paginate(Bucket=config.S3_BUCKET, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return sorted(keys)
    root = LOCAL_ROOT / prefix
    if not root.exists():
        return []
    return sorted(p.relative_to(LOCAL_ROOT).as_posix() for p in root.rglob("*") if p.is_file())


def write_json(key: str, obj) -> None:
    write_text(key, json.dumps(obj, indent=2, default=str))


def read_json(key: str):
    return json.loads(read_text(key)) if exists(key) else None
