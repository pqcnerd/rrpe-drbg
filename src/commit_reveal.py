from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, Optional

import pytz
from . import config, datafeed, predictor

def _canonical_json(obj: Dict[str, Any]) -> str:
    # print(f"canonicalizing JSON for keys: {sorted(obj.keys())}")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _et_datetime(d: date, t: time) -> datetime:
    # print(f"converting date {d} and time {t} to ET datetime")
    et = pytz.timezone("America/New_York")
    return et.localize(datetime.combine(d, t)).replace(tzinfo=None)


def _now_et_wall() -> datetime:
    # print("capturing current ET wall-clock timestamp")
    et = pytz.timezone("America/New_York")
    return datetime.now(et).replace(tzinfo=None, microsecond=0)


def _within_window(now_wall: datetime, d: date, start_t: time, end_t: time) -> bool:
    # print(f"checking trading window for {d}: {start_t} -> {end_t}")
    start_dt = _et_datetime(d, start_t)
    end_dt = _et_datetime(d, end_t)
    current = _et_datetime(now_wall.date(), now_wall.time().replace(microsecond=0))
    return start_dt <= current <= end_dt


def _context(trade_date: date, symbol: str) -> str:
    # print(f"building context string for {symbol} on {trade_date}")
    exch = getattr(config, "SYMBOL_EXCHANGE", {}).get(symbol, config.EXCHANGE)
    return f"{trade_date.isoformat()}|{symbol}|{exch}|close"


def _salt(secret_key: bytes, context: str) -> str:
    # print(f"creating salt for context: {context}")
    return hmac.new(secret_key, context.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


COMMIT_PRICE_DECIMALS = 4


def _round_commit_price(value: float) -> float:
    return round(float(value), COMMIT_PRICE_DECIMALS)


def _hash_commit_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _recover_commit_price(
    base_payload: Dict[str, Any],
    salt: str,
    commit_hex: str,
    approx_price: Optional[float] = None,
) -> Optional[float]:
    checked: set[float] = set()

    def _try_candidate(candidate: float) -> Optional[float]:
        rounded = _round_commit_price(candidate)
        if rounded <= 0:
            return None
        if rounded in checked:
            return None
        checked.add(rounded)
        payload = {**base_payload, "p_commit": rounded, "salt": salt}
        digest = _hash_commit_payload(payload)
        if digest == commit_hex:
            return rounded
        return None

    if approx_price is not None:
        approx = _round_commit_price(approx_price)
        result = _try_candidate(approx)
        if result is not None:
            return result
        step = 10 ** -COMMIT_PRICE_DECIMALS
        max_offset = 2.0
        steps = int(max_offset / step)
        for i in range(1, steps + 1):
            delta = i * step
            for candidate in (approx + delta, approx - delta):
                result = _try_candidate(candidate)
                if result is not None:
                    return result

    coarse_step = 0.01
    max_price = 2000.0
    iterations = int(max_price / coarse_step) + 1
    for i in range(iterations):
        candidate = i * coarse_step
        result = _try_candidate(candidate)
        if result is not None:
            return result

    fine_step = 10 ** -COMMIT_PRICE_DECIMALS
    max_price_fine = 1000.0
    iterations_fine = int(max_price_fine / fine_step) + 1
    for i in range(iterations_fine):
        candidate = i * fine_step
        result = _try_candidate(candidate)
        if result is not None:
            return result

    return None


def _ensure_commit_inputs(
    rec: Dict[str, Any],
    sym: str,
    trade_date: date,
    secret_bytes: bytes,
) -> Dict[str, Any]:
    commit_hex = rec.get("commit")
    if not commit_hex:
        raise RuntimeError(f"Missing commit for {sym} on {trade_date}")

    ctx = _context(trade_date, sym)
    existing_inputs = rec.get("commit_inputs") or {}
    stored_commit_ts = existing_inputs.get("timestamp_commit_utc") or rec.get("committed_at_utc", "")
    bar_ts_iso = existing_inputs.get("commit_bar_ts_et") or rec.get("commit_bar_ts_et")
    if not bar_ts_iso:
        et = pytz.timezone("America/New_York")
        bar_ts_iso = et.localize(datetime.combine(trade_date, time(15, 55))).isoformat()

    prediction_candidates: List[int] = []
    if "prediction" in existing_inputs:
        try:
            prediction_candidates.append(int(existing_inputs["prediction"]))
        except Exception:
            pass
    try:
        guess_pred = int(predictor.predict_next_move(sym, trade_date))
    except Exception:
        guess_pred = 1
    for candidate in (guess_pred, 0, 1):
        if candidate not in prediction_candidates:
            prediction_candidates.append(candidate)
    if not prediction_candidates:
        prediction_candidates = [0, 1]

    approx_price: Optional[float] = None
    if "p_commit" in existing_inputs:
        try:
            approx_price = float(existing_inputs["p_commit"])
        except Exception:
            approx_price = None
    if approx_price is None:
        p_commit_guess, _ = datafeed.get_price_at_bar_et(
            sym,
            trade_date,
            bar_ts_iso,
            tolerance_minutes=config.COMMIT_BAR_TOLERANCE_MINUTES,
        )
        if p_commit_guess is not None:
            approx_price = p_commit_guess

    salt = _salt(secret_bytes, ctx)
    stored_price_val: Optional[float] = None
    if "p_commit" in existing_inputs:
        try:
            stored_price_val = float(existing_inputs["p_commit"])
        except Exception:
            stored_price_val = None

    for pred in prediction_candidates:
        base_payload = {
            "symbol": sym,
            "prediction": int(pred),
            "commit_bar_ts_et": bar_ts_iso,
            "timestamp_commit_utc": stored_commit_ts,
            "context": ctx,
        }

        if stored_price_val is not None:
            rounded = _round_commit_price(stored_price_val)
            payload = {**base_payload, "p_commit": rounded, "salt": salt}
            if _hash_commit_payload(payload) == commit_hex:
                sanitized = {**base_payload, "p_commit": rounded}
                rec["commit_inputs"] = sanitized
                if not existing_inputs:
                    print(f"backfilled commit inputs for {sym} on {trade_date}")
                return sanitized

        recovered = _recover_commit_price(base_payload, salt, commit_hex, approx_price)
        if recovered is not None:
            sanitized = {**base_payload, "p_commit": recovered}
            rec["commit_inputs"] = sanitized
            if not existing_inputs:
                print(f"recovered legacy commit price for {sym} on {trade_date}: {recovered}")
            return sanitized

    raise RuntimeError(f"Unable to reconcile commit payload for {sym} on {trade_date}")


@dataclass
class SymbolRecord:
    symbol: str
    commit: Optional[str] = None
    context: Optional[str] = None
    committed_at_utc: Optional[str] = None
    prediction: Optional[int] = None
    salt: Optional[str] = None
    outcome: Optional[int] = None
    symbol_bits: Optional[str] = None
    close_prev: Optional[float] = None
    close_today: Optional[float] = None
    provider: Optional[str] = None
    tie: Optional[bool] = None
    revealed_at_utc: Optional[str] = None


def _load_daily(path: str) -> Dict[str, Any]:
    # print(f"loading daily JSON from {path}")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_daily(path: str, obj: Dict[str, Any]) -> None:
    # print(f"persisting daily JSON to {path}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=False)


def _symbol_lookup(symbols: List[Dict[str, Any]], symbol: str) -> Optional[Dict[str, Any]]:
    # print(f"looking up symbol entry for {symbol}")
    for rec in symbols:
        if rec.get("symbol") == symbol:
            return rec
    return None


def _ensure_header_csv() -> None:
    # print(f"ensuring entropy CSV header exists at {config.ENTROPY_LOG}")
    expected = [
        "date","symbol","prediction","outcome","symbol_bits","commit","context","salt",
        "close_prev","close_today","provider","tie",
        "p_commit","p_reveal","commit_bar_ts_et","delta","sign_bit","mag_q","symbol_bytes_hex",
    ]
    os.makedirs(os.path.dirname(config.ENTROPY_LOG), exist_ok=True)
    if not os.path.exists(config.ENTROPY_LOG):
        with open(config.ENTROPY_LOG, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(expected)
        return
    # Migrate header if needed
    with open(config.ENTROPY_LOG, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if not lines:
        with open(config.ENTROPY_LOG, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(expected)
        return
    current_header = lines[0].strip()
    if current_header != ",".join(expected):
        with open(config.ENTROPY_LOG, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(expected) + "\n")
            # preserve existing rows; they may have fewer columns
            for line in lines[1:]:
                f.write(line)


def _append_entropy_csv(trade_date: date, rec: Dict[str, Any]) -> None:
    # print(f"appending entropy CSV row for {rec.get('symbol')} on {trade_date}")
    _ensure_header_csv()
    with open(config.ENTROPY_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            trade_date.isoformat(),
            rec.get("symbol"),
            rec.get("prediction"),
            rec.get("outcome"),
            rec.get("symbol_bits"),
            rec.get("commit"),
            rec.get("context"),
            rec.get("salt"),
            rec.get("close_prev"),
            rec.get("close_today"),
            rec.get("provider"),
            rec.get("tie"),
            rec.get("p_commit"),
            rec.get("p_reveal"),
            rec.get("commit_bar_ts_et"),
            rec.get("delta"),
            rec.get("sign_bit"),
            rec.get("mag_q"),
            rec.get("symbol_bytes_hex"),
        ])


def perform_commit(trade_date: date, enforce_window: bool = True) -> bool:
    # print(f"perform_commit called for {trade_date} enforce_window={enforce_window}")
    if not datafeed.is_trading_day(trade_date):
        print(f"{trade_date} is not a trading day")
        return False

    now_wall = _now_et_wall()
    if enforce_window and not _within_window(now_wall, trade_date, config.SCHEDULE.commit_start, config.SCHEDULE.commit_end):
        print(f"current time {now_wall} is outside commit window for {trade_date}")
        return False

    secret = os.getenv(config.SALT_ENV_VAR)
    if not secret:
        raise RuntimeError(f"Missing secret env var {config.SALT_ENV_VAR}")
    secret_bytes = secret.encode("utf-8")

    config.ensure_output_dirs()
    path = os.path.join(config.DAILY_DIR, f"{trade_date.isoformat()}.json")
    doc = _load_daily(path)
    if not doc:
        doc = {
            "date": trade_date.isoformat(),
            "symbols": [],
            "meta": {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "code_commit": os.getenv(config.GITHUB_SHA_ENV, ""),
            },
        }

    changed = False
    for sym in config.SYMBOLS:
        existing_rec = _symbol_lookup(doc["symbols"], sym)
        if existing_rec and existing_rec.get("commit"):
            print(f"commit already exists for {sym} on {trade_date}, skipping")
            continue
        # determine commit bar price near 15:55 ET
        et = pytz.timezone("America/New_York")
        target = et.localize(datetime.combine(trade_date, time(15, 55)))
        print(f"fetching minute bar data for {sym} on {trade_date} near {target}")
        p_commit, bar_ts_iso = datafeed.get_minute_bar_near_et(sym, trade_date, target, tolerance_minutes=config.COMMIT_BAR_TOLERANCE_MINUTES)
        if p_commit is None or bar_ts_iso is None:
            print(f"could not fetch minute bar data for {sym} on {trade_date} (p_commit={p_commit}, bar_ts_iso={bar_ts_iso})")
            continue
        print(f"successfully fetched minute bar for {sym}: price={p_commit}, timestamp={bar_ts_iso}")
        ctx = _context(trade_date, sym)
        P = predictor.predict_next_move(sym, trade_date)
        s = _salt(secret_bytes, ctx)
        commit_ts_utc = datetime.now(timezone.utc).isoformat()
        p_commit_val = _round_commit_price(p_commit)
        commit_inputs = {
            "symbol": sym,
            "prediction": int(P),
            "p_commit": p_commit_val,
            "commit_bar_ts_et": bar_ts_iso,
            "timestamp_commit_utc": commit_ts_utc,
            "context": ctx,
        }
        payload = {**commit_inputs, "salt": s}
        C = _hash_commit_payload(payload)
        rec = _symbol_lookup(doc["symbols"], sym)
        if not rec:
            rec = {"symbol": sym}
            doc["symbols"].append(rec)
        rec.update({
            "commit": C,
            "commit_bar_ts_et": bar_ts_iso,
            "committed_at_utc": commit_ts_utc,
            "commit_inputs": commit_inputs,
        })
        changed = True
        print(f"created commit for {sym} on {trade_date}")

    if changed:
        _save_daily(path, doc)
        print(f"saved daily file for {trade_date}")
    else:
        print(f"no changes made for {trade_date} - all symbols either already committed or failed to fetch data")
    return changed


def perform_reveal(trade_date: date, enforce_window: bool = True) -> bool:
    # print(f"perform_reveal called for {trade_date} enforce_window={enforce_window}")
    if not datafeed.is_trading_day(trade_date):
        return False

    now_wall = _now_et_wall()
    if enforce_window and not _within_window(now_wall, trade_date, config.SCHEDULE.reveal_start, config.SCHEDULE.reveal_end):
        return False

    secret = os.getenv(config.SALT_ENV_VAR)
    if not secret:
        raise RuntimeError(f"Missing secret env var {config.SALT_ENV_VAR}")
    secret_bytes = secret.encode("utf-8")

    path = os.path.join(config.DAILY_DIR, f"{trade_date.isoformat()}.json")
    if not os.path.exists(path):
        return False
    doc = _load_daily(path)
    changed_any = False

    for sym in config.SYMBOLS:
        rec = _symbol_lookup(doc.get("symbols", []), sym)
        if not rec or not rec.get("commit"):
            continue
        if rec.get("revealed_at_utc"):
            continue
        prev_close, today_close = datafeed.get_prev_and_today_close(sym, trade_date)
        if prev_close is None or today_close is None:
            continue
        commit_inputs = _ensure_commit_inputs(rec, sym, trade_date, secret_bytes)
        ctx = commit_inputs["context"]
        P = int(commit_inputs["prediction"])
        bar_ts_iso = commit_inputs["commit_bar_ts_et"]
        stored_commit_ts = commit_inputs["timestamp_commit_utc"]
        p_commit_val = _round_commit_price(commit_inputs["p_commit"])
        commit_inputs["p_commit"] = p_commit_val
        rec["commit_inputs"] = commit_inputs
        s = _salt(secret_bytes, ctx)
        payload = {**commit_inputs, "salt": s}
        C_expected = _hash_commit_payload(payload)
        if C_expected != rec["commit"]:
            raise RuntimeError(f"Commit mismatch for {sym} on {trade_date}")
        O = 1 if today_close > prev_close else 0
        bits = f"{P}{O}"
        tie = today_close == prev_close
        delta = float(today_close) - float(p_commit_val)
        sign_bit = 1 if delta > 0 else 0
        mag_q = min(int(abs(delta) * 100), 255)
        symbol_bytes_hex = bytes([int(P), int(O), int(sign_bit), int(mag_q)]).hex()
        rec.update({
            "prediction": P,
            "salt": s,
            "outcome": O,
            "symbol_bits": bits,
            "close_prev": prev_close,
            "close_today": today_close,
            "provider": config.PROVIDER,
            "tie": tie,
            "context": ctx,
            "p_commit": p_commit_val,
            "p_reveal": float(today_close),
            "commit_bar_ts_et": bar_ts_iso,
            "delta": delta,
            "sign_bit": sign_bit,
            "mag_q": mag_q,
            "symbol_bytes_hex": symbol_bytes_hex,
            "revealed_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        _append_entropy_csv(trade_date, {**rec, "symbol": sym})
        changed_any = True

    if changed_any:
        _save_daily(path, doc)
    return changed_any

