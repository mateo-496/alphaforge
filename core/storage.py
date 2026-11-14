"""Local disk vs S3, switched by STORAGE env var."""
from pathlib import Path

from core import config


def write_text(key: str, text: str) -> None:
    if config.STORAGE == "s3":
        import boto3
        boto3.client("s3").put_object(Bucket=config.S3_BUCKET, Key=key, Body=text.encode())
    else:
        p = Path("data") / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def read_text(key: str) -> str:
    if config.STORAGE == "s3":
        import boto3
        return boto3.client("s3").get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read().decode()
    return (Path("data") / key).read_text()
