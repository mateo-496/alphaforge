import json
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from config import AWS_REGION, S3_BUCKET

def save_json(key: str, data: dict) -> dict:
    if not S3_BUCKET:
        return {"saved": False, "reason": "S3_BUCKET not configured; result remains in program output."}
    client = boto3.client("s3", region_name=AWS_REGION)
    try:
        client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json"
        )
        return {"saved": True, "bucket": S3_BUCKET, "key": key}
    except (BotoCoreError, ClientError) as exc:
        return {"saved": False, "reason": str(exc)}

def load_json(key: str, default=None):
    if not S3_BUCKET:
        return default
    client = boto3.client("s3", region_name=AWS_REGION)
    try:
        response = client.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except client.exceptions.NoSuchKey:
        return default
    except (BotoCoreError, ClientError, json.JSONDecodeError):
        return default
