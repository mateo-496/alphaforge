"""Mathematical models and metrics for country risk calculations."""
from tools.risk_calculator import calculate_risk

def country_risk(country_data: dict, bank_data: dict | None = None) -> float:
    """Compute R_c (sovereign risk metric) from country and banking data.
    
    Referenced in output_example.py as tools.risk_math.country_risk.
    Returns float score (0.0 to 100.0).
    """
    assessment = calculate_risk(country_data, bank_data)
    score = assessment.get("score")
    if score is None:
        return 0.0
    return float(score)
