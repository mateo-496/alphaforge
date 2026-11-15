"""All settings, read once from the environment (.env is loaded here). See .env.example."""
import os
import re
import shutil
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------- where data lives ----------
# Locally: ./data. On Vercel (VERCEL is set by the platform) the deployed files are read-only and /tmp is the only
# writable, per-instance disk: the data/ folder shipped with the deployment (the caches and finished runs) is copied
# there once per instance, and new runs and cache entries are written there. DATA_DIR overrides both.
ON_VERCEL = bool(os.environ.get("VERCEL"))
BUNDLED_DATA = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.environ.get("DATA_DIR") or ("/tmp/data" if ON_VERCEL else "data"))


def _seed(src: Path, dst: Path) -> None:
    """Copy the deployed data/ into the writable DATA_DIR: contents only. The deployed files are read-only and
    copytree would copy that mode too, leaving DATA_DIR unwritable."""
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "traces"]
        out = dst / Path(root).relative_to(src)
        out.mkdir(parents=True, exist_ok=True)
        for f in files:
            if not f.endswith(".tmp"):
                shutil.copyfile(Path(root) / f, out / f)


if ON_VERCEL:   # libraries' own caches (edgartools, yfinance via platformdirs) go to the writable /tmp too
    os.environ.setdefault("EDGAR_LOCAL_DATA_DIR", "/tmp/edgar")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/.cache")
if ON_VERCEL and BUNDLED_DATA.is_dir() and not (DATA_DIR / ".seeded").exists():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _seed(BUNDLED_DATA, DATA_DIR)
    (DATA_DIR / ".seeded").touch()
# A new analysis runs inside one streamed request (progress, then the report) instead of a background task polled by
# the page: serverless instances do not share memory or disk, and may stop work once a response is sent.
STREAM_RUNS = os.environ.get("STREAM_RUNS", "1" if ON_VERCEL else "0") == "1"

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "global.anthropic.claude-sonnet-5-5")
SCENARIO_MODEL_ID = os.environ.get("SCENARIO_MODEL_ID", BEDROCK_MODEL_ID)

# S3 copy of the GPR index read by tools/country_risk_inputs.py (v1 country risk, kept but not called by the app)
GEO_S3_BUCKET = os.environ.get("GEO_S3_BUCKET", "datathon-equipe-5-017820693871")

# STORAGE=local -> ./data/<key>;  STORAGE=s3 -> s3://S3_BUCKET/<key>
STORAGE = os.environ.get("STORAGE", "local")
S3_BUCKET = os.environ.get("S3_BUCKET", "")

# LLM traces: always appended to data/traces/<day>.jsonl; also sent to CloudTrail Lake when a channel is set.
CLOUDTRAIL_CHANNEL_ARN = os.environ.get("CLOUDTRAIL_CHANNEL_ARN", "")

# The SEC wants "Name email" as the User-Agent value; strip a pasted "User-Agent:" prefix.
SEC_IDENTITY = re.sub(r"^\s*user-agent\s*:\s*", "", os.environ.get("SEC_IDENTITY", "").strip().strip("\"'"), flags=re.I)
if SEC_IDENTITY:
    os.environ["SEC_IDENTITY"] = SEC_IDENTITY

# Scenario agent
SUMMARY_MAX_CHARS = 350
SCENARIO_MAX_AGE_DAYS = int(os.environ.get("SCENARIO_MAX_AGE_DAYS", "7"))
SCENARIO_ALPHA = float(os.environ.get("SCENARIO_ALPHA", "0.35"))   # EMA weight of the newest run

# Filings agent (web/firms.py)
FILINGS_TOP_N = int(os.environ.get("FILINGS_TOP_N", "5"))
FILINGS_PARALLEL = int(os.environ.get("FILINGS_PARALLEL", "3"))
# Deadlines for reading a company's filing. 0 (default) = no deadline: a run reads and saves everything it has not
# seen yet, so the next run that needs the same company finds it saved. A positive value caps the wait; what is not
# read by then finishes in the background (saved only if the server is still running).
# On Vercel a request stops after 300 s (Hobby), so deadlines are on by default there.
FILINGS_WAIT_S = float(os.environ.get("FILINGS_WAIT_S", "45" if ON_VERCEL else "0")) or None       # filings agents, per run
EXPOSURE_TEXT_WAIT_S = float(os.environ.get("EXPOSURE_TEXT_WAIT_S", "60" if ON_VERCEL else "0")) or None   # filing-text pass

# Agent answers are saved and reused when the exact same input comes back (core/llm.ask, per-country notes and
# drivers). Keys include the model, the system prompt and the input, so changing any of them refreshes the answer.
# LLM_CACHE=0 forces fresh calls.
LLM_CACHE = os.environ.get("LLM_CACHE", "1") != "0"

# A finished, complete analysis is reused when the same portfolio, profile, analysis date and scenario country are
# submitted again within this many days (scenarios and GPR refresh weekly). 0 = always run.
RUN_CACHE_DAYS = float(os.environ.get("RUN_CACHE_DAYS", "7"))
# A reused run replays its progress: the original timeline sped up to fit REPLAY_MAX_S, then held REPLAY_STEP_S at
# each phase start / end and at least REPLAY_GAP_S between lines, so a run served from caches still reads step by step.
REPLAY_MAX_S = float(os.environ.get("REPLAY_MAX_S", "20"))
REPLAY_STEP_S = float(os.environ.get("REPLAY_STEP_S", "0.8"))
REPLAY_GAP_S = float(os.environ.get("REPLAY_GAP_S", "0.08"))
REPLAY_HOLD_S = float(os.environ.get("REPLAY_HOLD_S", "0.9"))   # each holding / company / country shown in progress 1-2x this
