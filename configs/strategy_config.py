# quantitative_momentum_trader/configs/strategy_config.py
"""
Configuration file for all quantitative momentum trading strategies.

This file centralizes parameters for strategy selection, momentum calculation,
rebalancing, and filtering criteria. Modifying these values will alter the
behavior of the trading engine without requiring code changes in the core logic.
"""

from typing import Literal, Dict

# --- Strategy Selection ---
# This can be set by the execution script. Default is 'CORE'.
STRATEGY_NAME: Literal['CORE', 'SMOOTH', 'FROG_IN_PAN'] = 'CORE'


# --- Rebalancing Parameters ---
# Defines the frequency of portfolio rebalancing.
# This setting is primarily for live execution logic.
REBALANCE_PERIOD: Literal['QUARTERLY', 'MONTHLY'] = 'QUARTERLY'
REBALANCE_DAY_OF_PERIOD: int = 1


# --- Momentum Calculation Parameters ---
# These dictionaries allow for dynamic lookback and lag periods based on the
# selected calculation timeframe ('DAILY', 'WEEKLY', 'MONTHLY').
# The key (e.g., 'MONTHLY') corresponds to the timeframe, and the value is the period count.
MOMENTUM_LOOKBACKS: Dict[str, int] = {
    'MONTHLY': 12,  # Look back 12 months
    'WEEKLY': 4,   # Look back 12 weeks
    'DAILY': 10    # Look back approximately one month
}

# The lag period to exclude from the lookback to avoid short-term reversal.
# A lag of 0 means no data is excluded.
MOMENTUM_LAGS: Dict[str, int] = {
    'MONTHLY': 0,   # Lag by 2 months (standard 12-2 momentum)
    'WEEKLY': 0,    # Lag by 1 weeks (approx. 1 month)
    'DAILY': 0      # No lag for daily calculation
}


# --- Portfolio Construction Parameters ---
# The percentage of top-ranked stocks to include in the target portfolio.
TOP_PERCENTILE_CUTOFF: float = 0.025

# The percentage of bottom market cap stocks to exclude for liquidity reasons.
LIQUIDITY_FILTER_PERCENTILE: float = 0.0


# --- Strategy-Specific Filter Parameters ---

# For 'SMOOTH' Strategy:
# The minimum number of positive periods required within the lookback.
# This will be interpreted as months for monthly, weeks for weekly, etc.
SMOOTHNESS_MIN_POSITIVE_PERIODS: int = 7

# For 'FROG_IN_PAN' Strategy:
# The lookback period (in trading days) for calculating daily return volatility.
VOLATILITY_LOOKBACK_DAYS: int = 252
# The percentile cutoff for the volatility screen (keeps stocks below this percentile).
VOLATILITY_CUTOFF_PERCENTILE: float = 0.85


# --- Universe & Data Parameters ---
UNIVERSE_TICKERS_CSV_PATH: str = "data/ticker_list.csv"
YFINANCE_DATA_PERIOD: str = "2y"
SECTORS_TO_EXCLUDE: list[str] = ["Financial Services", "Financials"]

# --- Execution Parameters ---
ORDER_TYPE: Literal['MKT', 'LMT'] = 'MKT'
DELAY_BETWEEN_BUYS_S: float = 1.0
EXECUTE_ORDERS_OUTSIDE_RTH: bool = False