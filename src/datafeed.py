from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

import pandas as pd
import pandas_market_calendars as pmc
import yfinance as yf
import pytz

def nyse_calendar():
    return pmc.get_calendar("XNYS")


def is_trading_day(date_et: dt.date) -> bool:
    cal = nyse_calendar()
    schedule = cal.schedule(start_date=date_et, end_date=date_et)
    return not schedule.empty


def previous_trading_day(date_et: dt.date) -> dt.date:
    cal = nyse_calendar()
    schedule = cal.valid_days(start_date=date_et - dt.timedelta(days=14), end_date=date_et - dt.timedelta(days=1))
    if len(schedule) == 0:
        raise ValueError("no prior trading day found in the past 2 weeks!?!")
    return schedule[-1].date()


def kth_previous_trading_day(date_et: dt.date, k: int) -> dt.date:
    if k <= 0:
        raise ValueError("k must be positive")
    d = date_et
    for _ in range(k):
        d = previous_trading_day(d)
    return d


def _download_daily(symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    # yfinance handles inclusive start, exclusive end for dates
    df = yf.download(
        tickers=symbol,
        start=start.isoformat(),
        end=(end + dt.timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
    )
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(0, axis=1)
    return df


def _series_to_date_close_map(df: pd.DataFrame) -> dict[str, float]:
    if df is None or df.empty:
        return {}
    idx_dates = [pd.Timestamp(ts).date() for ts in df.index]
    closes = df["Close"].tolist()
    return {d: float(c) for d, c in zip(idx_dates, closes) if pd.notna(c)}


def get_prev_and_today_close(symbol: str, trade_date: dt.date) -> Tuple[Optional[float], Optional[float]]:
    start = trade_date - dt.timedelta(days=14)
    df = _download_daily(symbol, start, trade_date)
    m = _series_to_date_close_map(df)
    prev = previous_trading_day(trade_date)
    prev_close = m.get(prev)
    today_close = m.get(trade_date)
    return prev_close, today_close


def get_recent_closes(symbol: str, end_date: dt.date, lookback_trading_days: int = 6) -> list[Tuple[dt.date, float]]:
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

# minute data (for hybrid commit price)
# #todo: add this to the config.py file?
ET_TZ = pytz.timezone("America/New_York")
UTC_TZ = pytz.UTC

def _download_minute_day(symbol: str, trade_date: dt.date) -> pd.DataFrame:
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
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(0, axis=1)
    return df

def _ensure_et_index(df: pd.DataFrame) -> pd.DataFrame:
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
    if target_et.tzinfo is None:
        target_et = ET_TZ.localize(target_et)
    df = _download_minute_day(symbol, trade_date)
    if df is None or df.empty:
        return None, None
    df_et = _ensure_et_index(df)
    diffs = (df_et.index - target_et).to_series().abs()
    i_min = diffs.idxmin() if not diffs.empty else None
    if i_min is None:
        return None, None
    min_delta = abs((i_min - target_et).total_seconds())
    if min_delta > tolerance_minutes * 60:
        return None, None
    try:
        close_val = float(df_et.loc[i_min]["Close"])
    except Exception:
        return None, None
    return close_val, i_min.isoformat()

def get_price_at_bar_et(symbol: str, trade_date: dt.date, bar_ts_et_iso: str, tolerance_minutes: int = 2) -> Tuple[Optional[float], Optional[str]]:
    """
    refetch 1m data for the day and return price nearest to the provided ET bar timestamp.
    """
    try:
        ts = pd.Timestamp(bar_ts_et_iso)
        if ts.tz is None:
            target_et = ET_TZ.localize(ts.to_pydatetime())
        else:
            target_et = ts.tz_convert(ET_TZ).to_pydatetime().replace(tzinfo=ET_TZ)
    except Exception:
        return None, None
    return get_minute_bar_near_et(symbol, trade_date, target_et, tolerance_minutes)

