import json
import boto3
from config import AWS_REGION, BEDROCK_MODEL_ID

def explain_risk(country: str, assessment: dict, country_data: dict, bank_data: dict) -> str:
    if not BEDROCK_MODEL_ID:
        return (
            "Bedrock is not configured. Set BEDROCK_MODEL_ID to a model enabled in "
            "your AWS account. The numerical assessment above was calculated locally. "
            f"Current classification: {assessment.get('label')}."
        )

    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    payload = {
        "country": country,
        "assessment": assessment,
        "country_data": country_data,
        "bank_data": bank_data
    }
    prompt = f"""
You are an analytical assistant explaining a preliminary national financial-risk
assessment. Use only the supplied data. Do not invent facts, fill missing values,
or claim the score is an official sovereign rating. Distinguish observed data from
interpretation. Mention data coverage and limitations. Explain the main risk drivers
and what additional data would improve confidence. Do not give investment advice.

Assessment data:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""
    response = client.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 700, "temperature": 0.2}
    )
    return "".join(
        item.get("text", "")
        for item in response["output"]["message"]["content"]
        if "text" in item
    )
