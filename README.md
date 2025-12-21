# rrpe-drbg
a cryptographic random number gen reseeded by own predictive error on chaotic rw processes

## verdict (read this first)
this is an **experimental, auditable randomness-beacon-style mixer**, not a production-grade cryptographic DRBG

- **do not use for keys / secrets**: this project does *not* claim CSPRNG/DRBG security (NIST-style) and is not suitable for generating private keys, nonces, seeds, or long-term secrets
- **output strength is often “as strong as drand”**: the extractor computes `SHA256(drand_seed || symbol_bytes_stream)`. if `drand` is honest/available, the output is already high-quality public randomness; the market-derived bytes mostly act as additional mixing/commitment-to-reality
- **offline mode is deterministic**: if `drand` fetch fails, the code falls back to a fixed all-zero seed; in that mode the output becomes a deterministic hash of the logged market-derived symbols
- **threat model matters**: the market inputs are public, structured, and can be biased/manipulated (data source quirks, revisions, outages, potential price steering, selective participation). this repo is best viewed as a transparent experiment in “reflexive randomness,” not a security primitive
*note: the rest is the old readme without seeing the docs generated.*

experimental cryptographic randomness beacon that continuously *re-entropizes itself* using the outcome of its own failed predictions.  
everyday (or moreso every close?), the system makes a publicly verifiable prediction about an inherently unpredictable real-world signal (ex. whether a stock index will rise or fall at the next close) and commits that prediction before the outcome is known.  
once reality is observed, a **4-byte symbol** is formed from the prediction, outcome, and price movement: `[prediction, outcome, sign_bit, mag_q]`, which is appended to an ever growing sequence of **prediction error pairs**.  
this sequence is then passed through a **cryptographic extractor** (SHA-256) to yield a uniform random output. 

> in effect, the generators own inability to predict a chaotic world becomes its entropy source.

## motivation
traditional randomness beacons rely on:
- hardware noise (quantum RNGs, ring oscillators)
- cryptographic primitives (VRFs, drand, NIST beacon)
- physical processes (lotteries, atmospheric noise)

these sources are often opaque or centralized.  
by contrast, I am proposing a *public, reflexive* randomness process:
- anyone can verify the data (market prices are public)
- entropy arises from epistemic limits (predictive error)
- commitments ensure no hindsight bias
- the system is fully transparent and auditable on GitHub

this reframes *failure of prediction* not as a bug, but as a **cryptographic feature**.

## concept overview

### daily prediction
at each trading day `t`, the system predicts whether a stock's next close will be higher or lower than the previous close:  

`P_t ∈ {0,1}` where `1 = "predict up"`, `0 = "predict down"`.

### commit phase
before the market closes (at 15:55 ET), the system:
- fetches the 1 minute bar price `p_commit` near commit time
- generates a deterministic salt via `HMAC_SHA256(RRPE_SALT_KEY, context)[:32]`
- builds a canonical JSON payload containing: `symbol`, `prediction`, `p_commit`, `commit_bar_ts_et`, `timestamp_commit_utc`, `salt`, `context`
- computes the commitment hash: `C_t = SHA256(canonical_json)`

this ensures the prediction cannot be altered after the fact.

### reveal phase
after the market closes (16:04–16:12 ET about):
- the actual outcome `O_t ∈ {0,1}` is determined from the close price.
- the prediction, salt, and `p_commit` are revealed.
- the commitment is verified by reconstructing the canonical JSON and checking:  
  `SHA256(canonical_json) == C_t`
- a 4-byte symbol is created: `[P_t, O_t, sign_bit, mag_q]` where:
  - `P_t` = prediction (0 or 1)
  - `O_t` = outcome (0 or 1, based on whether close > prev_close)
  - `sign_bit` = 1 if `p_reveal - p_commit > 0` else 0
  - `mag_q` = min(int(abs(p_reveal - p_commit) * 100), 255)

### entropy accumulation
over `N` observations, concatenate 4-byte symbols:  

`X = bytes_1 || bytes_2 || ... || bytes_N`

where each `bytes_i` is the 4-byte symbol `[P_i, O_i, sign_bit_i, mag_q_i]`.

this represents the **empirical trace of predictive failure.**

### extraction
to remove bias and temporal correlation, apply a cryptographic extractor (seeded SHA-256):  

`R_t = SHA256(seed || X)[:m]`

where `seed` is a public seed from the latest drand beacon (concatenated as bytes), `X` is the concatenated symbol bytes, and `[:m]` takes the first `m` hex characters (where `m = out_bits // 4`).  
The result `R_t` is the **reflexive random output** — verifiable, auditable, and grounded in real-world chaos.

## key idea — *reflexive randomness*
> the generator’s predictive limitations become its entropy reservoir.

this creates a *cybernetic feedback loop*:
1. the model predicts reality  
2. reality disproves the model  
3. the failure pattern re-entropizes the model’s RNG state  
4. the cycle repeats  

mathematically, if the prediction stream has min-entropy `H∞(X) > 0`, a hash-based extractor guarantees nearly uniform output bits (Leftover Hash Lemma):

`||R_t − U_m|| <= 2^{−(Hinf(X) − m)/2}`

thus, as long as the world resists perfect prediction, entropy is continuously renewed.

## example workflow

### using the command line interface

the recommended way:

```bash
# commit predictions for a trading day
python -m src.main commit --date 2025-11-09

# reveal predictions after market close
python -m src.main reveal --date 2025-11-09

# extract randomness from accumulated symbols (uses latest drand seed and last N symbols from entropy_log.csv)
python -m src.main extract --date 2025-11-09 --window 256 --bits 256
```

### programmatic usage

if you need to use the functions directly:

```python
from datetime import date
from src.predictor import predict_next_move
from src.commit_reveal import perform_commit, perform_reveal
from src.extractor import run_for_date

# prediction
trade_date = date(2025, 11, 9)
pred = predict_next_move("AAPL", trade_date)  # 0 = down, 1 = up

# commit (requires RRPE_SALT_KEY env var)
changed = perform_commit(trade_date, enforce_window=False)

# reveal (after market close)
changed = perform_reveal(trade_date, enforce_window=False)

# extraction (uses latest drand seed and collects last N symbols from entropy_log.csv)
changed = run_for_date(trade_date, window=256, out_bits=256)
# output is written to outputs/daily/YYYY-MM-DD.json in the "extractor" field
```

## entropy evaluation

symbol frequency distribution

shannon entropy H(X) = −sum(p_i log_2 p_i)

min-entropy Hinf(X) = −log₂(max p_i)

autocorrelation of symbol sequences

these quantify genuine unpredictability in the prediction error stream before extraction.

---

## implementation details (4-byte symbols)

the implementation incorporates the pre-close price snapshot and the close-to-commit delta, producing a richer entropy signal (typically 6–12 bits per round).

### concept

at each round, the system commits to a snapshot **before** the outcome is known, then reveals after the market closes:

- `p_commit` = price at commit time (1-minute bar near 15:55 ET)
- `p_reveal` = official closing price (16:00 ET)
- `prediction` ∈ {0, 1} meaning "predict up/down"

after reveal we derive:
- `outcome = 1 if p_reveal > prev_close else 0` (direction of daily close change)
- `delta = p_reveal - p_commit` (price change from commit time to close)
- `sign_bit = 1 if delta > 0 else 0` (direction of delta)
- `mag_q = min(int(abs(delta) * 100), 255)` (quantized magnitude in cents, capped at 255)

### commit phase (15:55 ET)

1. fetch 1 minute bar nearest to 15:55 ET (within 15 minutes)
2. record `p_commit = round(bar.Close, 4)` and `commit_bar_ts_et` (ISO timestamp in ET)
3. build canonical JSON payload:
```json
{
  "symbol": "AAPL",
  "prediction": 1,
  "p_commit": 178.45,
  "commit_bar_ts_et": "2025-11-10T15:55:00-05:00",
  "timestamp_commit_utc": "2025-11-10T20:55:00Z",
  "salt": "a1b2c3d4...",
  "context": "2025-11-10|AAPL|NASDAQ|close"
}
```
4. Compute commitment hash:
```
commit_hash = SHA256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```
5. publish only `commit_hash` and `commit_bar_ts_et` (no leak of prediction or price)

### reveal phase (~16:05–16:10 ET)

1. re-fetch the minute bar using `commit_bar_ts_et` to reconstruct `p_commit`
2. fetch official close `p_reveal` from daily data
3. rebuild the payload deterministically and verify: `SHA256(canonical_json) == commit_hash`
4. compute symbol components:
   - `outcome = 1 if p_reveal > prev_close else 0` (based on daily close comparison)
   - `delta = p_reveal - p_commit`
   - `sign_bit = 1 if delta > 0 else 0` (direction of commit-to-close delta)
   - `mag_q = min(int(abs(delta) * 100), 255)`
5. emit 4-byte symbol: `[prediction, outcome, sign_bit, mag_q]` → `symbol_bytes_hex` (8 hex chars)

### entropy components

| component | description | entropy source |
|-----------|-------------|----------------|
| `prediction` | what the agent believed | human/model uncertainty |
| `outcome` | what reality did | market direction |
| `sign_bit` | direction of delta | chaotic movement |
| `mag_q` | size of change (0–255) | market volatility |

together these four fields typically yield **6–12 bits of entropy per round**, an order of magnitude more than a simple 2-bit prediction/outcome pair.

### artifacts

per symbol in `outputs/daily/YYYY-MM-DD.json`:
- **fields**: `p_commit`, `p_reveal`, `commit_bar_ts_et`, `delta`, `sign_bit`, `mag_q`, `symbol_bytes_hex`

CSV `outputs/entropy_log.csv` includes all columns.

### extraction

extraction uses 4-byte symbols:
```
concatenated_bytes = bytes.fromhex(symbol_bytes_hex_1 + symbol_bytes_hex_2 + ...)
seed_bytes = bytes.fromhex(seed_hex)  # or seed.encode('utf-8') if not hex
output = SHA256(seed_bytes + concatenated_bytes).hexdigest()[:bits//4]  # first (bits//4) hex chars = bits bits of output
```

---

## runbook (SPY, AAPL; ET schedule)

- Commit window: 15:54–15:56 ET (actual commit scheduled at 15:55)
- Reveal window: 16:04–16:12 ET (after close prints settle)
- Symbols: SPY, AAPL (NYSE/NASDAQ close)
- Provider: yfinance daily close

### local usage

- set secret: export `RRPE_SALT_KEY` to a persistent, private value.
- install deps: `pip install -r requirements.txt`
- Commands:
  - `python -m src.main commit --date YYYY-MM-DD --force` (pre-close commit)
  - `python -m src.main reveal --date YYYY-MM-DD --force` (post-close reveal)
  - `python -m src.main extract --window 256 --bits 256`

artifacts:
- `outputs/daily/YYYY-MM-DD.json`
- `outputs/entropy_log.csv`

### verification

#### implementation
1. **verify commit hash**:
   - reconstruct the canonical JSON payload using:
     - `symbol`, `prediction` (from reveal)
     - `p_commit` (re-fetched using `commit_bar_ts_et`)
     - `commit_bar_ts_et` (from commit artifact)
     - `timestamp_commit_utc` (from commit artifact)
     - `salt = HMAC_SHA256(RRPE_SALT_KEY, context)[:32]`
     - `context = f"{date}|{symbol}|{exchange}|close"`
   - serialize with `json.dumps(payload, sort_keys=True, separators=(",", ":"))`
   - compute `SHA256(canonical_json)` and verify it matches `commit_hash`

2. **verify reveal computations**:
   - confirm `p_reveal` matches public close price
   - verify `outcome = 1 if p_reveal > prev_close else 0` (where `prev_close` is the previous trading day's close)
   - verify `delta = p_reveal - p_commit`
   - verify `sign_bit = 1 if delta > 0 else 0`
   - verify `mag_q = min(int(abs(delta) * 100), 255)`
   - verify `symbol_bytes_hex = bytes([prediction, outcome, sign_bit, mag_q]).hex()`

3. **Reproduce extraction**:
   - collect last N rows from `entropy_log.csv`
   - concatenate `symbol_bytes_hex` values as bytes
   - fetch latest drand seed (not date-specific)
   - concatenate seed bytes with symbol bytes: `seed_bytes + concatenated_bytes`
   - compute `SHA256(seed_bytes + concatenated_bytes).hexdigest()[:bits//4]` and compare to artifact (first bits//4 hex characters = bits bits of output)

all data is public and verifiable; the only secret is `RRPE_SALT_KEY` used for deterministic salt generation.