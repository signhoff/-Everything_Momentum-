# quantitative_momentum_trader/configs/strategy_config.py
"""
Configuration file for all quantitative momentum trading strategies.

This file centralizes parameters for strategy selection, momentum calculation,
rebalancing, and filtering criteria. Modifying these values will alter the
behavior of the trading engine without requiring code changes in the core logic.
"""

from typing import Literal

# --- Strategy Selection ---
# Choose the strategy to execute.
# 'CORE': Baseline quantitative momentum (12-2 momentum ranking).
# 'SMOOTH': Core momentum with an added "smoothness" filter (number of positive months).
# 'FROG_IN_PAN': Low volatility momentum (filters by volatility before applying momentum ranking).
STRATEGY_NAME: Literal['CORE', 'SMOOTH', 'FROG_IN_PAN'] = 'FROG_IN_PAN'


# --- Rebalancing Parameters ---
# Defines the frequency of portfolio rebalancing.
# 'QUARTERLY': Rebalances on the first trading day of January, April, July, October.
# 'MONTHLY': Rebalances on the first trading day of each month.
REBALANCE_PERIOD: Literal['QUARTERLY', 'MONTHLY'] = 'QUARTERLY'

# Determines which day of the rebalance period to trade.
# For example, 1 means the first trading day of the period.
REBALANCE_DAY_OF_PERIOD: int = 1


# --- Momentum Calculation Parameters ---
# The lookback period (in months) for calculating total return.
MOMENTUM_LOOKBACK: int = 12

# The lag period (in months) to exclude from the lookback to avoid short-term reversal.
# A value of 2 means we calculate the return from t-12 to t-2.
MOMENTUM_LAG: int = 2


# --- Portfolio Construction Parameters ---
# The percentage of top-ranked stocks to include in the target portfolio.
# 0.10 represents the top decile (1%).
TOP_PERCENTILE_CUTOFF: float = 0.01

# The percentage of bottom market cap stocks to exclude for liquidity reasons.
# 0.20 means the bottom 20% (quintile) of stocks by market cap are removed.
LIQUIDITY_FILTER_PERCENTILE: float = 0.20


# --- Strategy-Specific Filter Parameters ---

# For 'SMOOTH' Strategy:
# The minimum number of positive-return months required within the MOMENTUM_LOOKBACK period.
SMOOTHNESS_MIN_POSITIVE_MONTHS: int = 7

# For 'FROG_IN_PAN' Strategy:
# The lookback period (in trading days) for calculating daily return volatility.
VOLATILITY_LOOKBACK_DAYS: int = 252

# The percentile cutoff for the volatility screen.
# 0.80 means we keep the 80% of stocks with the LOWEST volatility,
# effectively removing the top 20% (quintile) of the most volatile stocks.
VOLATILITY_CUTOFF_PERCENTILE: float = 0.80


# --- Universe & Data Parameters ---
# Filepath for the CSV containing the initial stock universe.
UNIVERSE_TICKERS_CSV_PATH: str = "data/sp500_tickers.csv"

# The historical data period to fetch from yfinance.
# Should be long enough to cover all lookback calculations (e.g., momentum and volatility).
# "2y" (2 years) is generally a safe choice for a 1-year lookback.
YFINANCE_DATA_PERIOD: str = "2y"

# Sectors to exclude from the investment universe.
# Financials are commonly excluded from simple momentum strategies.
SECTORS_TO_EXCLUDE: list[str] = ["Financial Services", "Financials"]

# --- Execution Parameters ---
# The type of order to use for rebalancing trades.
# 'MKT' for Market Order, 'LMT' for Limit Order.
# Using MKT orders is simpler for ensuring execution during rebalancing.
ORDER_TYPE: Literal['MKT', 'LMT'] = 'MKT'

# A small delay in seconds between placing buy orders during rebalancing.
# This can help avoid API rate limiting issues.
DELAY_BETWEEN_BUYS_S: float = 1.0