import io
import json
import re
import boto3
import pandas as pd
from botocore.exceptions import ClientError
from strands import tool
from core import config


# Initialize the S3 client
s3_client = boto3.client('s3', region_name=config.REGION)

# Exact text of every tool result shown to the model (Strands sends dicts as json.dumps),
# used afterwards by code to verify evidence quotes. Cleared by the agent before each run.
RETRIEVED_TEXT: list[str] = []
# Country name -> ISO3 code for every country matched during the run.
MATCHED_COUNTRIES: dict[str, str] = {}

@tool
def extract_portfolio_from_s3_excel(target_countries: list[str], months: int = 24,
                                    sheet_name: str | int = 0) -> dict:
    """
    Get the Geopolitical Risk (GPR) index for countries from data_gpr_export.xls in S3.

    The file has one row per month and one column per series: gpr (global index, 1985-2019=100),
    gprc_<iso3> (country GPR: % of newspaper articles, since 1985) and gprhc_<iso3>
    (historical country GPR, since 1900). Returns the last `months` monthly rows for the
    requested countries, plus the global index.

    Args:
        target_countries: Country names ("Taiwan", "United States") or ISO3 codes ("TWN").
        months: Number of most recent months to return.
        sheet_name: Excel sheet to read (index or name).
    """
    GPT_path = "raw/gpr_data/data_gpr_export.xls"
    try:
        print(f"Downloading Excel file from s3://{config.GEO_S3_BUCKET}/{GPT_path}...")
        
        # 1. Fetch object from S3 into an in-memory byte stream
        response = s3_client.get_object(Bucket=config.GEO_S3_BUCKET, Key=GPT_path)
        excel_bytes = response['Body'].read()
        
        # 2. Read spreadsheet bytes using pandas
        # engine=None lets pandas automatically infer openpyxl (.xlsx) or xlrd (.xls)
        df = pd.read_excel(io.BytesIO(excel_bytes), sheet_name=sheet_name)
        
        # Normalize column names to lowercase/strings for safer searching
        df.columns = [str(col).strip().lower() for col in df.columns]
        
        print(f"Successfully loaded spreadsheet. Columns found: {list(df.columns)}")
        
        # 3. Countries are COLUMNS (gprc_twn, ...), not row values. The var_name/var_label
        #    columns are the legend: GPRC_TWN -> "Country GPR: Percent of articles (Taiwan)".
        countries = {}  # iso3 (lowercase) -> country name
        for name, label in df[["var_name", "var_label"]].dropna().itertuples(index=False):
            code = re.fullmatch(r"gprc_([a-z]{3})", str(name).strip().lower())
            country = re.search(r"\(([^)]+)\)\s*$", str(label))
            if code and country:
                countries[code.group(1)] = country.group(1)

        matched, unmatched = {}, []
        for target in target_countries:
            t = target.strip().lower()
            code = t if t in countries else next((c for c, n in countries.items() if n.lower() == t), None)
            if code:
                matched[countries[code]] = code
            else:
                unmatched.append(target)

        # 4. Keep month + global index + the matched countries' columns, last `months` rows
        columns = ["month", "gpr"] + [f"{p}_{c}" for c in matched.values() for p in ("gprc", "gprhc")]
        data = df[columns].dropna(subset=["month", "gpr"]).tail(months).copy()
        data["month"] = pd.to_datetime(data["month"]).dt.strftime("%Y-%m")  # JSON-serializable
        extracted_records = data.round(4).astype(object).where(data.notna(), None).to_dict(orient="records")

        result = {
            "source_file": f"s3://{config.GEO_S3_BUCKET}/{GPT_path}",
            "target_countries": target_countries,
            "matched_countries": {name: code.upper() for name, code in matched.items()},
            "columns": {"gpr": "Global GPR index (1985-2019 = 100)",
                        "gprc_<iso3>": "Country GPR: % of articles (10 newspapers, since 1985)",
                        "gprhc_<iso3>": "Historical country GPR: % of articles (3 newspapers, since 1900)"},
            "total_rows_scanned": len(df),
            "matched_rows_count": len(extracted_records),
            "extracted_data": extracted_records
        }
        if unmatched:
            result["unmatched_countries"] = unmatched
            result["available_countries"] = sorted(countries.values())
        MATCHED_COUNTRIES.update(result["matched_countries"])
        RETRIEVED_TEXT.append(json.dumps(result, ensure_ascii=False))
        return result
    except ClientError as e:
        error_msg = e.response['Error']['Message']
        print(f"AWS S3 Error: {error_msg}")
        return {"error": error_msg}
    except Exception as e:
        print(f"Unexpected error processing Excel file: {str(e)}")
        return {"error": str(e)}

def quote_is_verified(quote: str) -> bool:
    """Exact-substring check (whitespace/quote style normalized) against the tool outputs."""
    def norm(t: str) -> str:
        return re.sub(r"\s+", " ", t.replace("'", '"')).strip().lower()
    q = norm(quote)
    return bool(q) and any(q in norm(t) for t in RETRIEVED_TEXT)


def tools() -> list:
    """Tools exposed to the agent; the KB tool only when a Knowledge Base is configured."""
    return [extract_portfolio_from_s3_excel]