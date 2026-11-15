import json
import logging
from typing import Any
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from config import AWS_REGION, BEDROCK_MODEL_ID

logger = logging.getLogger(__name__)

def explain_risk(country: str, assessment: dict, country_data: dict, bank_data: dict) -> str:
    """Generate risk explanation using Bedrock converse API, with fallback if unavailable."""
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
    try:
        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 700}
        )
        return "".join(
            item.get("text", "")
            for item in response["output"]["message"]["content"]
            if "text" in item
        )
    except Exception as exc:
        logger.warning("Bedrock invocation failed: %s. Using local synthesis.", exc)
        label = assessment.get("label", "Moderate risk")
        score = assessment.get("score", 0.0)
        return (
            f"Preliminary sovereign risk assessment for {country} indicates {label} (Composite Score: {score}/100). "
            f"Public debt is {country_data.get('public_debt_pct_gdp', 'N/A')}% of GDP, "
            f"annual inflation is {country_data.get('inflation_pct', 'N/A')}%, "
            f"and banking sector non-performing loans stand at {bank_data.get('nonperforming_loans_pct', 'N/A')}%. "
            f"Calculated under illustrative weighted heuristic."
        )

def generate_insights_with_bedrock(country: str, payload: dict) -> dict[str, Any]:
    """Ask Bedrock for structured claims and event insights if available."""
    if not BEDROCK_MODEL_ID:
        return {}
    try:
        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        prompt = f"""You are a sovereign financial risk modeling assistant for AlphaForge.
Analyze the country metrics and return a JSON object with:
"explanation": a concise analytical narrative (max 3 sentences),
"claims": a list of objects with fields:
  - "channel": one of ["trade_tariffs", "export_controls", "sanctions", "conflict_exposure", "supply_chain", "regulatory", "fx_capital_controls", "financial_stress"]
  - "statement": one factual sentence summarizing a quantitative finding
  - "value": numeric float or null
  - "unit": string (e.g. "pct", "usd") or null
  - "score": integer severity 0 to 5
  - "confidence": float between 0.0 and 1.0
  - "evidence_quote": short quote from data (max 200 chars)
  - "locator": data indicator or section name
"events": a list of forward-looking risk events with fields:
  - "type": string event type
  - "date": "YYYY-MM-DD"
  - "channel": valid channel from list above
  - "severity": integer 0 to 5
  - "likelihood": float 0.0 to 1.0

Data:
{json.dumps(payload, ensure_ascii=False, indent=2)}

Respond with valid JSON only. Do not wrap in markdown or backticks.
"""
        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 1000}
        )
        text = "".join(
            item.get("text", "")
            for item in response["output"]["message"]["content"]
            if "text" in item
        ).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(text)
    except Exception as exc:
        logger.warning("Bedrock structured generation not available: %s", exc)
        return {}
