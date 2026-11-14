"""API Gateway -> orchestrator. Parse, call, return only. TODO: persist to DynamoDB."""
import json

from core.schemas import InvestorProfile, Portfolio, Scenario
from orchestrator import chain


def handler(event, context):
    body = json.loads(event["body"])
    result = chain.run(Portfolio(**body["portfolio"]), InvestorProfile(**body.get("profile", {})),
                       Scenario(**body["scenario"]))
    return {"statusCode": 200, "body": result.model_dump_json()}
