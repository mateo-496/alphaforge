"""Measured inputs for country risk: GPR percentile (S3) and global financial stress percentile (OFR)."""
import io
import re
from datetime import date
from functools import lru_cache
from typing import Optional

import boto3
import pandas as pd

from core import config
from tools import market_stress, risk_math, worldbank

GPR_KEY = "raw/gpr_data/data_gpr_export.xls"
WINDOW = 12  # months averaged to smooth the monthly GPR series
HISTORY = 120  # trailing months of 12-month means used as reference (the series drifts upward over decades)
STRESS_LOOKBACK_DAYS = 3650
ISO2_TO_ISO3 = {
    "AR": "ARG", "AU": "AUS", "BE": "BEL", "BR": "BRA", "CA": "CAN", "CH": "CHE", "CL": "CHL", "CN": "CHN",
    "CO": "COL", "DE": "DEU", "DK": "DNK", "EG": "EGY", "ES": "ESP", "FI": "FIN", "FR": "FRA", "GB": "GBR",
    "HK": "HKG", "HU": "HUN", "ID": "IDN", "IL": "ISR", "IN": "IND", "IT": "ITA", "JP": "JPN", "KR": "KOR",
    "MX": "MEX", "MY": "MYS", "NL": "NLD", "NO": "NOR", "PE": "PER", "PH": "PHL", "PL": "POL", "PT": "PRT",
    "RU": "RUS", "SA": "SAU", "SE": "SWE", "TH": "THA", "TN": "TUN", "TR": "TUR", "TW": "TWN", "UA": "UKR",
    "US": "USA", "VE": "VEN", "VN": "VNM", "ZA": "ZAF",
}


@lru_cache(maxsize=1)
def _gpr_frame() -> tuple[pd.DataFrame, dict[str, str]]:
    body = boto3.client("s3", region_name=config.REGION).get_object(
        Bucket=config.GEO_S3_BUCKET, Key=GPR_KEY)["Body"].read()
    df = pd.read_excel(io.BytesIO(body))
    df.columns = [str(c).strip().lower() for c in df.columns]
    names = {}
    for name, label in df[["var_name", "var_label"]].dropna().itertuples(index=False):
        code = re.fullmatch(r"gprc_([a-z]{3})", str(name).strip().lower())
        country = re.search(r"\(([^)]+)\)\s*$", str(label))
        if code and country:
            names[country.group(1).lower()] = code.group(1).upper()
    df = df.dropna(subset=["month"]).copy()
    df["month"] = pd.to_datetime(df["month"])
    return df, names


def resolve_iso3(country: str) -> Optional[str]:
    """ISO2, ISO3 or English name (as labelled in the GPR file) -> ISO3, None if the GPR file has no such country."""
    key = country.strip()
    if key.upper() in ISO2_TO_ISO3:
        return ISO2_TO_ISO3[key.upper()]
    df, names = _gpr_frame()
    if f"gprc_{key.lower()}" in df.columns:
        return key.upper()
    if key.lower() in names:
        return names[key.lower()]
    try:  # World Bank names such as "Korea, Rep." or "Russian Federation"
        iso3 = worldbank.resolve_country(key)
    except Exception:
        return None
    return iso3 if iso3 and f"gprc_{iso3.lower()}" in df.columns else None


def gpr_percentile(iso3: str, as_of: str) -> Optional[dict]:
    """Percentile of the latest 12-month mean country GPR within that country's last ten years of 12-month means.
    Measures how unusual current attention to geopolitical risk is for the country (the raw level is not
    comparable across countries: it depends on how much media coverage each country gets)."""
    df, _ = _gpr_frame()
    column = f"gprc_{iso3.lower()}"
    if column not in df.columns:
        return None
    series = df[df["month"] <= pd.Timestamp(date.fromisoformat(as_of))].set_index("month")[column].dropna()
    means = series.rolling(WINDOW).mean().dropna().iloc[-HISTORY:]
    if len(means) < 60:  # at least five years of 12-month means
        return None
    current = float(means.iloc[-1])
    return {"percentile": risk_math.percentile_rank(current, [float(v) for v in means]),
            "current_12m_mean": current, "month": means.index[-1].strftime("%Y-%m"), "history_months": len(means)}


def stress_percentile(as_of: str) -> Optional[dict]:
    """Percentile of the latest OFR Financial Stress Index within the last ten years (global, same for all countries)."""
    series = market_stress.get_market_series("OFR_FSI", as_of, STRESS_LOOKBACK_DAYS)
    values = [float(o["value"]) for o in series["observations"]]
    if len(values) < 250:
        return None
    return {"percentile": risk_math.percentile_rank(values[-1], values), "latest": values[-1],
            "date": str(series["observations"][-1]["date"])}


def country_risk_score(country: str, as_of: str, claims=()) -> dict:
    """R_c on [0, 1] from measured inputs only. Missing inputs are reported, never replaced by invented values."""
    iso3 = resolve_iso3(country)
    gpr = gpr_percentile(iso3, as_of) if iso3 else None
    try:
        stress = stress_percentile(as_of)
    except Exception:
        stress = None
    missing = [name for name, value in (("gpr", gpr), ("vol", stress)) if value is None] + ["epu"]
    score, contributions = risk_math.country_risk(
        gpr["percentile"] if gpr else None, None, stress["percentile"] if stress else None, list(claims))
    return {"country": country, "iso3": iso3, "score": score, "contributions": contributions,
            "gpr": gpr, "stress": stress, "missing_inputs": missing}
