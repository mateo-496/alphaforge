import os

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "global.anthropic.claude-haiku-5-5")
STORAGE = os.getenv("STORAGE", "local")  # local | s3
S3_BUCKET = os.getenv("S3_BUCKET", "")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "")
SEC_IDENTITY = os.getenv("SEC_IDENTITY", "")
USE_MOCK = os.getenv("USE_MOCK", "1") == "1"
