from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd


def _shannon_entropy_from_counts(counts: Dict[str, int]) -> float:
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c <= 0:
            continue
        p = c / total
        h -= p * math.log(p, 2)
    return h


def _min_entropy_from_counts(counts: Dict[str, int]) -> float:
    total = sum(counts.values())
    if total <= 0:
        return 0.0
    max_p = max(c / total for c in counts.values() if c > 0)
    return -math.log(max_p, 2) if max_p > 0 else 0.0


def _counts(series: Iterable[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for x in series:
        if x is None:
            continue
        s = str(x)
        if s == "" or s.lower() == "nan":
            continue
        out[s] = out.get(s, 0) + 1
    return out


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _load_entropy_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    # norm common numeric fields if present
    for col in ("prediction", "outcome", "sign_bit", "mag_q"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("delta", "close_prev", "close_today", "p_commit", "p_reveal"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _decode_symbol_bytes_hex(hex_str: str) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(hex_str, str) or len(hex_str) != 8:
        return None
    try:
        b = bytes.fromhex(hex_str)
        if len(b) != 4:
            return None
        return int(b[0]), int(b[1]), int(b[2]), int(b[3])
    except Exception:
        return None


def _with_decoded_fields(df: pd.DataFrame) -> pd.DataFrame:
    if "symbol_bytes_hex" not in df.columns:
        return df
    decoded = df["symbol_bytes_hex"].apply(_decode_symbol_bytes_hex)
    df = df.copy()
    df["sb_pred"] = decoded.apply(lambda t: t[0] if t is not None else pd.NA)
    df["sb_outcome"] = decoded.apply(lambda t: t[1] if t is not None else pd.NA)
    df["sb_sign"] = decoded.apply(lambda t: t[2] if t is not None else pd.NA)
    df["sb_mag_q"] = decoded.apply(lambda t: t[3] if t is not None else pd.NA)
    for col in ("sb_pred", "sb_outcome", "sb_sign", "sb_mag_q"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _bits_to_int(bits: str) -> Optional[int]:
    if not isinstance(bits, str) or len(bits) != 2 or any(c not in "01" for c in bits):
        return None
    return int(bits, 2)


def _compute_autocorr(values: List[float], max_lag: int) -> List[Tuple[int, float]]:
    if len(values) < 3:
        return []
    s = pd.Series(values, dtype="float64")
    out: List[Tuple[int, float]] = []
    for lag in range(1, max_lag + 1):
        try:
            r = float(s.autocorr(lag=lag))
        except Exception:
            r = float("nan")
        out.append((lag, r))
    return out


def _matplotlib() -> "tuple[object, object]":
    # defer imp mpl so running without the extra dep fails with a clean message
    import matplotlib.pyplot as plt  # type: ignore

    return plt, plt.style


def _savefig(fig, path: str) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=160)


@dataclass(frozen=True)
class ReportConfig:
    csv_path: str
    docs_dir: str
    assets_dir: str
    rolling_window: int
    max_lag: int


def generate_report(cfg: ReportConfig) -> Dict[str, object]:
    if not os.path.exists(cfg.csv_path):
        raise FileNotFoundError(f"CSV not found: {cfg.csv_path}")

    _ensure_dir(cfg.docs_dir)
    _ensure_dir(cfg.assets_dir)

    df = _load_entropy_csv(cfg.csv_path)
    df = _with_decoded_fields(df)
    if "date" in df.columns:
        df = df.sort_values(["date", "symbol"] if "symbol" in df.columns else ["date"])

    plt, _ = _matplotlib()
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.grid": True,
            "grid.alpha": 0.25,
            "axes.titlesize": 12,
            "axes.labelsize": 10,
        }
    )

    # p1 symbol_bits freq
    if "symbol_bits" in df.columns:
        counts_bits = _counts(df["symbol_bits"].astype(str).tolist())
        order = ["00", "01", "10", "11"]
        xs = [k for k in order if k in counts_bits] + [k for k in sorted(counts_bits.keys()) if k not in order]
        ys = [counts_bits.get(k, 0) for k in xs]
        fig = plt.figure(figsize=(7.2, 4.0))
        ax = fig.add_subplot(1, 1, 1)
        ax.bar(xs, ys, color="#334155")
        ax.set_title("symbol_bits frequency (prediction,outcome)")
        ax.set_xlabel("symbol_bits")
        ax.set_ylabel("count")
        _savefig(fig, os.path.join(cfg.assets_dir, "symbol_bits_frequency.png"))
        plt.close(fig)
    else:
        counts_bits = {}

    # p2 delta dist
    if "delta" in df.columns:
        fig = plt.figure(figsize=(7.2, 4.0))
        ax = fig.add_subplot(1, 1, 1)
        series = df["delta"].dropna().astype(float)
        ax.hist(series, bins=24)
        ax.set_title("delta distribution (close_today - p_commit)")
        ax.set_xlabel("delta")
        ax.set_ylabel("count")
        _savefig(fig, os.path.join(cfg.assets_dir, "delta_distribution.png"))
        plt.close(fig)

    # p3 mag_q dist
    if "mag_q" in df.columns:
        fig = plt.figure(figsize=(7.2, 4.0))
        ax = fig.add_subplot(1, 1, 1)
        series = df["mag_q"].dropna().astype(float)
        ax.hist(series, bins=24, range=(0, 255))
        ax.set_title("mag_q distribution (|delta| * 100, capped at 255)")
        ax.set_xlabel("mag_q")
        ax.set_ylabel("count")
        _savefig(fig, os.path.join(cfg.assets_dir, "mag_q_distribution.png"))
        plt.close(fig)

    # p4 pred acc over time (per workday)
    if {"prediction", "outcome", "date"}.issubset(set(df.columns)):
        df_acc = df.dropna(subset=["prediction", "outcome", "date"]).copy()
        df_acc["correct"] = (df_acc["prediction"].astype(int) == df_acc["outcome"].astype(int)).astype(int)
        daily = df_acc.groupby(df_acc["date"].dt.date)["correct"].mean().reset_index()
        fig = plt.figure(figsize=(7.2, 4.0))
        ax = fig.add_subplot(1, 1, 1)
        ax.plot(daily["date"].astype(str), daily["correct"], marker="o", linewidth=1.5, color="#0f766e")
        ax.set_title("prediction accuracy over time (mean across symbols)")
        ax.set_xlabel("date")
        ax.set_ylabel("accuracy")
        ax.set_ylim(0, 1)
        ax.tick_params(axis="x", rotation=45)
        _savefig(fig, os.path.join(cfg.assets_dir, "prediction_accuracy_over_time.png"))
        plt.close(fig)

    # p5 rolling Shannon entropy of symbol_bits
    rolling_entropy: List[float] = []
    if "symbol_bits" in df.columns:
        bits_list = [b for b in df["symbol_bits"].astype(str).tolist() if b in ("00", "01", "10", "11")]
        if len(bits_list) >= cfg.rolling_window:
            for i in range(len(bits_list)):
                lo = max(0, i + 1 - cfg.rolling_window)
                window = bits_list[lo : i + 1]
                h = _shannon_entropy_from_counts(_counts(window))
                rolling_entropy.append(h)
            fig = plt.figure(figsize=(7.2, 4.0))
            ax = fig.add_subplot(1, 1, 1)
            ax.plot(range(1, len(rolling_entropy) + 1), rolling_entropy, color="#1d4ed8", linewidth=1.5)
            ax.set_title(f"rolling Shannon entropy of symbol_bits (window={cfg.rolling_window})")
            ax.set_xlabel("observation index (in CSV order)")
            ax.set_ylabel("entropy (bits)")
            ax.set_ylim(0, 2)
            _savefig(fig, os.path.join(cfg.assets_dir, "rolling_entropy_symbol_bits.png"))
            plt.close(fig)

    # p6 autocorr of symbol_bits (mapped 0..3)
    autocorr_rows: List[Tuple[int, float]] = []
    if "symbol_bits" in df.columns:
        ints = [_bits_to_int(b) for b in df["symbol_bits"].astype(str).tolist()]
        ints = [float(x) for x in ints if x is not None]
        autocorr_rows = _compute_autocorr(ints, cfg.max_lag)
        if autocorr_rows:
            lags = [x[0] for x in autocorr_rows]
            rs = [x[1] for x in autocorr_rows]
            fig = plt.figure(figsize=(7.2, 4.0))
            ax = fig.add_subplot(1, 1, 1)
            ax.bar(lags, rs, color="#7c3aed")
            ax.axhline(0.0, color="black", linewidth=1)
            ax.set_title("autocorrelation of symbol_bits (00..11 mapped to 0..3)")
            ax.set_xlabel("lag")
            ax.set_ylabel("autocorr")
            _savefig(fig, os.path.join(cfg.assets_dir, "autocorrelation_symbol_bits.png"))
            plt.close(fig)

    # summary
    date_min = None
    date_max = None
    if "date" in df.columns:
        dmin = df["date"].dropna().min()
        dmax = df["date"].dropna().max()
        date_min = dmin.date().isoformat() if hasattr(dmin, "date") else None
        date_max = dmax.date().isoformat() if hasattr(dmax, "date") else None

    stats = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "csv_path": cfg.csv_path,
        "rows": int(len(df)),
        "date_min": date_min,
        "date_max": date_max,
        "symbols": dict(df["symbol"].value_counts().to_dict()) if "symbol" in df.columns else {},
        "symbol_bits_counts": counts_bits,
        "symbol_bits_shannon_entropy_bits": _shannon_entropy_from_counts(counts_bits) if counts_bits else None,
        "symbol_bits_min_entropy_bits": _min_entropy_from_counts(counts_bits) if counts_bits else None,
        "autocorrelation_symbol_bits": [{"lag": lag, "r": r} for lag, r in autocorr_rows],
        "rolling_window_symbol_bits": cfg.rolling_window if rolling_entropy else None,
    }

    summary_path = os.path.join(cfg.docs_dir, "entropy_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    return stats


def main() -> int:
    p = argparse.ArgumentParser(description="Generate docs graphs from outputs/entropy_log.csv")
    p.add_argument("--csv", default=os.path.join("outputs", "entropy_log.csv"))
    p.add_argument("--docs", default="docs")
    p.add_argument("--window", type=int, default=32, help="Rolling window size for entropy plot")
    p.add_argument("--max-lag", type=int, default=20, help="Max lag for autocorrelation plot")
    args = p.parse_args()

    docs_dir = args.docs
    assets_dir = os.path.join(docs_dir, "assets")
    cfg = ReportConfig(
        csv_path=args.csv,
        docs_dir=docs_dir,
        assets_dir=assets_dir,
        rolling_window=max(2, int(args.window)),
        max_lag=max(1, int(args.max_lag)),
    )

    stats = generate_report(cfg)
    print(f"wrote docs assets -> {assets_dir}")
    print(f"wrote stats -> {os.path.join(docs_dir, 'entropy_summary.json')}")
    if stats.get("symbol_bits_shannon_entropy_bits") is not None:
        print(f"symbol_bits H ≈ {stats['symbol_bits_shannon_entropy_bits']:.4f} bits")
    if stats.get("symbol_bits_min_entropy_bits") is not None:
        print(f"symbol_bits H∞ ≈ {stats['symbol_bits_min_entropy_bits']:.4f} bits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


