from datetime import datetime, timezone
from tools.country_api import get_country_data
from tools.bank_api import get_bank_data
from tools.risk_calculator import calculate_risk
from tools.bedrock_service import explain_risk
from storage.s3_service import save_json

def analyze_country(country: str, bank: str | None = None) -> dict:
    country_data = get_country_data(country)
    bank_data = get_bank_data(country, bank)

    assessment = calculate_risk(country_data, bank_data)
    explanation = explain_risk(country, assessment, country_data, bank_data)

    result = {
        "country": country,
        "bank": bank,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "risk_assessment": assessment,
        "explanation": explanation,
        "data": {
            "country": country_data,
            "bank": bank_data
        },
        "disclaimer": (
            "Prototype assessment, not investment, credit, or sovereign-risk advice. "
            "Scores depend on source coverage, data quality, and the illustrative "
            "heuristics configured in this project."
        )
    }
    save_json(f"assessments/{country.lower().replace(' ', '-')}.json", result)
    return result
