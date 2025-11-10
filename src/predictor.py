from __future__ import annotations

import datetime as dt

from . import datafeed


def predict_next_move(symbol: str, trade_date: dt.date) -> int:
    """
    deterministic, transparent predictor.
    strategy: sign of last daily return (prev - prevprev). if data insufficient,
    default to 1 (predict up) to remain deterministic.
    """
    # need previous two trading days relative to trade_date
    try:
        prev = datafeed.previous_trading_day(trade_date)
        prevprev = datafeed.previous_trading_day(prev)
    except Exception:
        return 1

    closes = dict(datafeed.get_recent_closes(symbol, trade_date, lookback_trading_days=6))
    if prev not in closes or prevprev not in closes:
        return 1

    last_ret = closes[prev] - closes[prevprev]
    return 1 if last_ret >= 0 else 0

