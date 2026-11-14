import json
from typing import Any
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from config import AWS_REGION, S3_BUCKET

def save_json(key: str, data: Any) -> dict:
    """Save JSON data or Pydantic model to S3 bucket."""
    if not S3_BUCKET:
        return {"saved": False, "reason": "S3_BUCKET not configured; result remains in program output."}
    
    if hasattr(data, "model_dump"):
        serialized = data.model_dump(mode="json")
    elif isinstance(data, (dict, list)):
        serialized = data
    else:
        serialized = str(data)

    try:
        client = boto3.client("s3", region_name=AWS_REGION)
        client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(serialized, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json"
        )
        return {"saved": True, "bucket": S3_BUCKET, "key": key}
    except (BotoCoreError, ClientError, Exception) as exc:
        return {"saved": False, "reason": str(exc)}

def load_json(key: str, default: Any = None) -> Any:
    """Load JSON data from S3 bucket."""
    if not S3_BUCKET:
        return default
    try:
        client = boto3.client("s3", region_name=AWS_REGION)
        response = client.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except (BotoCoreError, ClientError, json.JSONDecodeError, Exception):
        return default
