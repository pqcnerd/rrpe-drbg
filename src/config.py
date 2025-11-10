import os
from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class Schedule:
    commit_start: time
    commit_end: time
    reveal_start: time
    reveal_end: time


SYMBOLS = ["SPY", "AAPL"]
EXCHANGE = "NYSE"
ET_TZ_NAME = "America/New_York"
# print(f"configured base symbols: {SYMBOLS} on {EXCHANGE}")

SYMBOL_EXCHANGE = {
    "SPY": "NYSE",
    "AAPL": "NASDAQ",
}

SCHEDULE = Schedule(
    commit_start=time(15, 54, 0),
    commit_end=time(15, 56, 0),
    reveal_start=time(16, 4, 0),
    reveal_end=time(16, 12, 0),
)
# print(f"schedule initialized: {SCHEDULE}")

# Outputs
OUTPUTS_DIR = "outputs"
DAILY_DIR = os.path.join(OUTPUTS_DIR, "daily")
ENTROPY_LOG = os.path.join(OUTPUTS_DIR, "entropy_log.csv")

SALT_ENV_VAR = "RRPE_SALT_KEY" #todo: add this to the .env file
DRAND_URL = "https://drand.cloudflare.com/public/latest" #todo: add this to the .env file?

EXTRACT_WINDOW = 256
EXTRACT_BITS = 256

PROVIDER = "yfinance"
GITHUB_SHA_ENV = "GITHUB_SHA"

COMMIT_BAR_TOLERANCE_MINUTES = 15

def ensure_output_dirs() -> None:
    # print(f"ensuring output directories exist: {OUTPUTS_DIR}, {DAILY_DIR}")
    os.makedirs(DAILY_DIR, exist_ok=True)
    os.makedirs(OUTPUTS_DIR, exist_ok=True)

