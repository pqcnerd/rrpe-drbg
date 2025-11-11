# commit / reveal cycle

this walk through runs a full prediction cycle for a single trade date and then extracts entropy from the accumulated symbols. The commands start from the repository root (`rrpe-drbg/`).

## install & activate the project venv (I use a wsl)

the examples below assume you are inside the virtual environment:

```bash
./misc/install.sh
source misc/venv/bin/activate
```

for future sessions, just rerun the `source` line to reenter the environment.

## commit the prediction

commit the model’s prediction for a specific trading day. The `--force` flag lets you bypass the normal timing guardrails so you can replay historical dates.

```bash
python -m src.main commit --date 2025-11-05 --force
```

- writes the commitment payload and hash to `outputs/daily/2025-11-05.json`
- captures the preclose price snapshot that will be reused during reveal

## reveal and verify

reveal the prediction after the close, reconstruct the canonical payload, and verify the original commitment hash.

```bash
python -m src.main reveal --date 2025-11-05 --force
```

- validates the commitment hash matches the reveal payload
- appends a 4-byte symbol `[prediction, outcome, sign_bit, mag_q]` to `outputs/entropy_log.csv`

## extract randomness

run the extractor to turn the accumulated prediction error symbols into uniform bits. override the extraction window and bit length to flex the pipeline.

```bash
python -m src.main extract --date 2025-11-05 --window 512 --bits 512
```

- uses the latest drand beacon seed plus the 512 most recent symbols
- emits a 512-bit hex digest under `outputs/daily/2025-11-05.json` in the `"extractor"` field

## bonus: live (today) workflow

skip the `--date` argument to operate on today in nyt. the CLI autodetects the current trading day.

```bash
python -m src.main commit --force
python -m src.main reveal --force
python -m src.main extract --window 256 --bits 256
```

inspect the resulting randomness by opening the latest JSON artifact:

```bash
cat outputs/daily/$(date -u +"%Y-%m-%d").json | jq '.extractor.output_hex'
```