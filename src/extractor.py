from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import date, datetime, timezone
from typing import List, Tuple, Optional

import requests

from . import config


def _read_entropy_log_rows() -> Tuple[List[str], List[dict]]:
    if not os.path.exists(config.ENTROPY_LOG):
        return [], []
    with open(config.ENTROPY_LOG, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = [r for r in reader]
    return list(fieldnames), rows


def _collect_bits(window: int) -> str:
    _, rows = _read_entropy_log_rows()
    bits_list: List[str] = [r.get("symbol_bits", "") for r in rows if r.get("symbol_bits")]  # type: ignore
    bits_list = bits_list[-window:]
    return "".join(bits_list)


def _collect_bytes(window: int) -> Optional[bytes]:
    fieldnames, rows = _read_entropy_log_rows()
    if "symbol_bytes_hex" not in fieldnames:
        return None
    hex_list: List[str] = [r.get("symbol_bytes_hex", "") for r in rows if r.get("symbol_bytes_hex")]  # type: ignore
    hex_list = hex_list[-window:]
    if not hex_list:
        return None
    try:
        return b"".join(bytes.fromhex(h) for h in hex_list if h)
    except Exception:
        return None


def fetch_drand_seed() -> Tuple[str, str]:
    url = os.getenv("DRAND_URL", config.DRAND_URL)
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        randomness = data.get("randomness") or data.get("signature") or ""
        return url, str(randomness)
    except Exception:
        # Fallback to empty/zero seed if offline; still deterministic
        return url, "0" * 64


def _seed_bytes(seed_value: str) -> bytes:
    try:
        if all(c in "0123456789abcdef" for c in seed_value.lower()) and len(seed_value) % 2 == 0:
            return bytes.fromhex(seed_value)
    except Exception:
        pass
    return seed_value.encode("utf-8")


def extract_randomness_from_bytes(symbol_bytes: bytes, seed_value: str, out_bits: int) -> str:
    payload = _seed_bytes(seed_value) + symbol_bytes
    digest = hashlib.sha256(payload).hexdigest()
    hex_len = out_bits // 4
    return digest[:hex_len]


def extract_randomness(bits_concat: str, seed_value: str, out_bits: int) -> str:
    payload = _seed_bytes(seed_value) + bits_concat.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    hex_len = out_bits // 4
    return digest[:hex_len]


def run_for_date(trade_date: date, window: int = config.EXTRACT_WINDOW, out_bits: int = config.EXTRACT_BITS) -> bool:
    # only proceed if the daily file exists and at least one symbol revealed
    path = os.path.join(config.DAILY_DIR, f"{trade_date.isoformat()}.json")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    if not any(rec.get("revealed_at_utc") for rec in doc.get("symbols", [])):
        return False

    seed_url, seed_value = fetch_drand_seed()
    byte_stream = _collect_bytes(window)
    if byte_stream:
        output_hex = extract_randomness_from_bytes(byte_stream, seed_value, out_bits)
    else:
        bits_concat = _collect_bits(window)
        output_hex = extract_randomness(bits_concat, seed_value, out_bits)

    doc["extractor"] = {
        "seed_source": seed_url,
        "seed_value": seed_value,
        "window": window,
        "output_bits": out_bits,
        "output_hex": output_hex,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    return True
