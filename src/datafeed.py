from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

import pandas as pd
import pandas_market_calendars as pmc
import yfinance as yf
import pytz

_STANDARD_FIELD_ORDER = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
_PRICE_FIELD_NAMES = {name.lower() for name in _STANDARD_FIELD_ORDER}
_PRICE_FIELD_MAP = {name.lower(): name for name in _STANDARD_FIELD_ORDER}


def _normalize_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten multi-index columns returned by yfinance to standard OHLC names."""
    if df is None or df.empty:
        return df

    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        # use the final level, which where yfinance stores field names
        field_level = out.columns.nlevels - 1
        out.columns = out.columns.get_level_values(field_level)

    normalized = []
    for col in out.columns:
        name = str(col).strip()
        mapped = _PRICE_FIELD_MAP.get(name.lower())
        normalized.append(mapped or name)
    out.columns = normalized

    if "Close" not in out.columns and len(out.columns) > 0:
        # fall back to expected field order if yfinance returned duplicate ticker columns
        count = min(len(out.columns), len(_STANDARD_FIELD_ORDER))
        out.columns = _STANDARD_FIELD_ORDER[:count] + list(out.columns[count:])
    return out

def nyse_calendar():
    # print("retrieving NYSE calendar instance")
    return pmc.get_calendar("XNYS")


def is_trading_day(date_et: dt.date) -> bool:
    # print(f"checking if {date_et} is a trading day")
    cal = nyse_calendar()
    schedule = cal.schedule(start_date=date_et, end_date=date_et)
    return not schedule.empty


def previous_trading_day(date_et: dt.date) -> dt.date:
    # print(f"finding previous trading day before {date_et}")
    cal = nyse_calendar()
    schedule = cal.valid_days(start_date=date_et - dt.timedelta(days=14), end_date=date_et - dt.timedelta(days=1))
    if len(schedule) == 0:
        raise ValueError("no prior trading day found in the past 2 weeks!?!")
    return schedule[-1].date()


def kth_previous_trading_day(date_et: dt.date, k: int) -> dt.date:
    # print(f"computing {k}th previous trading day from {date_et}")
    if k <= 0:
        raise ValueError("k must be positive")
    d = date_et
    for _ in range(k):
        d = previous_trading_day(d)
    return d


def _download_daily(symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    # yfinance handles inclusive start, exclusive end for dates
    # print(f"downloading daily data for {symbol} {start} -> {end}")
    df = yf.download(
        tickers=symbol,
        start=start.isoformat(),
        end=(end + dt.timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
    )
    return _normalize_price_columns(df)


def _series_to_date_close_map(df: pd.DataFrame) -> dict[str, float]:
    # print(f"converting DataFrame with {0 if df is None else len(df)} rows to date->close map")
    if df is None or df.empty:
        return {}
    if "Close" not in df.columns:
        return {}
    idx_dates = [pd.Timestamp(ts).date() for ts in df.index]
    closes = df["Close"].tolist()
    return {d: float(c) for d, c in zip(idx_dates, closes) if pd.notna(c)}


def get_prev_and_today_close(symbol: str, trade_date: dt.date) -> Tuple[Optional[float], Optional[float]]:
    # print(f"getting prev/today close for {symbol} on {trade_date}")
    start = trade_date - dt.timedelta(days=14)
    df = _download_daily(symbol, start, trade_date)
    m = _series_to_date_close_map(df)
    prev = previous_trading_day(trade_date)
    prev_close = m.get(prev)
    today_close = m.get(trade_date)
    return prev_close, today_close


def get_recent_closes(symbol: str, end_date: dt.date, lookback_trading_days: int = 6) -> list[Tuple[dt.date, float]]:
    # print(f"gathering recent closes for {symbol} ending {end_date} over {lookback_trading_days} days")
    start = end_date - dt.timedelta(days=21)
    df = _download_daily(symbol, start, end_date)
    m = _series_to_date_close_map(df)
    # build list of last N trading days up to end_date (exclusive)
    cal = nyse_calendar()
    valid = cal.valid_days(start_date=start, end_date=end_date)
    dates = [pd.Timestamp(x).date() for x in valid]
    dates = [d for d in dates if d < end_date]
    dates_sorted = sorted(dates)[-lookback_trading_days:]
    return [(d, m[d]) for d in dates_sorted if d in m]

# minute data (for commit price)
ET_TZ = pytz.timezone("America/New_York")
UTC_TZ = pytz.UTC

def _download_minute_day(symbol: str, trade_date: dt.date) -> pd.DataFrame:
    # print(f"downloading minute-level data for {symbol} on {trade_date}")
    start_utc = ET_TZ.localize(dt.datetime.combine(trade_date, dt.time(9, 25))).astimezone(UTC_TZ)
    end_utc = ET_TZ.localize(dt.datetime.combine(trade_date, dt.time(16, 5))).astimezone(UTC_TZ)
    df = yf.download(
        tickers=symbol,
        start=start_utc,
        end=end_utc,
        interval="1m",
        auto_adjust=False,
        progress=False,
    )
    return _normalize_price_columns(df)

def _ensure_et_index(df: pd.DataFrame) -> pd.DataFrame:
    # print("ensuring DataFrame index is ET localized")
    if df is None or df.empty:
        return df
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        idx_et = idx.tz_localize(UTC_TZ).tz_convert(ET_TZ)
    else:
        idx_et = idx.tz_convert(ET_TZ)
    out = df.copy()
    out.index = idx_et
    return out

def get_minute_bar_near_et(symbol: str, trade_date: dt.date, target_et: dt.datetime, tolerance_minutes: int = 2) -> Tuple[Optional[float], Optional[str]]:
    """
    return (close_price, bar_ts_et_iso) for the 1m bar nearest to target_et within tolerance.
    target_et must be timezone-aware ET datetime.
    """
    # print(f"looking for minute bar near {target_et} for {symbol}")
    if target_et.tzinfo is None:
        target_et = ET_TZ.localize(target_et)
    df = _download_minute_day(symbol, trade_date)
    if df is None or df.empty:
        return None, None
    if "Close" not in df.columns:
        return None, None
    df_et = _ensure_et_index(df)
    diffs = pd.Series(df_et.index - target_et, index=df_et.index)
    diffs_abs = diffs.abs()
    i_min = diffs_abs.idxmin() if not diffs_abs.empty else None
    if i_min is None:
        return None, None
    min_delta = abs((i_min - target_et).total_seconds())
    if min_delta > tolerance_minutes * 60:
        return None, None
    row = df_et.loc[i_min]
    close_val = row["Close"] if isinstance(row, pd.Series) and "Close" in row else None
    if close_val is None or pd.isna(close_val):
        return None, None
    return float(close_val), i_min.isoformat()

def get_price_at_bar_et(symbol: str, trade_date: dt.date, bar_ts_et_iso: str, tolerance_minutes: int = 2) -> Tuple[Optional[float], Optional[str]]:
    """
    refetch 1m data for the day and return price nearest to the provided ET bar timestamp.
    """
    # print(f"fetching price at bar {bar_ts_et_iso} for {symbol} on {trade_date}")
    try:
        ts = pd.Timestamp(bar_ts_et_iso)
        if ts.tz is None:
            target_et = ET_TZ.localize(ts.to_pydatetime())
        else:
            target_et = ts.tz_convert(ET_TZ).to_pydatetime().replace(tzinfo=ET_TZ)
    except Exception:
        return None, None
    return get_minute_bar_near_et(symbol, trade_date, target_et, tolerance_minutes)

