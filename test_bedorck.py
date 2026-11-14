import boto3
from dotenv import load_dotenv
load_dotenv()
brt = boto3.client("bedrock-runtime", region_name="us-east-1")
MODEL = "global.anthropic.claude-haiku-5-5"
r = brt.converse(modelId=MODEL,
    messages=[{"role": "user", "content": [{"text": "Say hi in 5 words."}]}])
print(r["output"]["message"]["content"][0]["text"])