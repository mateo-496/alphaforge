"""Central configuration, read from environment variables (see .env.example)."""
import os

REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
SEC_IDENTITY = os.environ.get("SEC_IDENTITY", "AlphaForge Datathon alphaforge@example.com")

# Geopolitical agent: S3 bucket/prefix holding research documents, optional Bedrock Knowledge Base over it.
GEO_S3_BUCKET = "datathon-equipe-5-017820693871"