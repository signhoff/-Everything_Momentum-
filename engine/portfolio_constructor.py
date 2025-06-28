# quantitative_momentum_trader/engine/portfolio_constructor.py
"""
Portfolio Constructor for the Quantitative Momentum Trading System.

This module implements the core logic for the different momentum strategies.
It takes raw data from the DataManager, applies the necessary filters and
calculations, and generates a final target portfolio based on the selected
strategy's rules. This version generates both long and short positions.
"""

import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple, Literal

# Initialize a logger for this module
logger = logging.getLogger(__name__)

class PortfolioConstructor:
    """
    Constructs a target portfolio based on a specified momentum strategy and timeframe.
    """
    def __init__(self, historical_data: pd.DataFrame, company_info: Dict[str, Dict], config: Any):
        """
        Initializes the PortfolioConstructor.

        Args:
            historical_data (pd.DataFrame): DataFrame with historical OHLCV data.
            company_info (Dict[str, Dict]): Dictionary with 'marketCap' and 'sector'.
            config (Any): Configuration module with strategy parameters.
        """
        self.historical_data = historical_data
        self.company_info = company_info
        self.config = config
        self.eligible_stocks = pd.DataFrame()
        logger.info("PortfolioConstructor initialized.")

    def _apply_universe_filters(self) -> None:
        """Applies liquidity and sector filters to the stock universe."""
        logger.info("Applying universe filters (liquidity and sector)...")
        info_df = pd.DataFrame.from_dict(self.company_info, orient='index').dropna(subset=['marketCap', 'sector'])
        info_df.index.name = 'Ticker'
        
        # Liquidity Filter
        liquidity_cutoff = info_df['marketCap'].quantile(self.config.LIQUIDITY_FILTER_PERCENTILE)
        initial_count = len(info_df)
        info_df = info_df[info_df['marketCap'] >= liquidity_cutoff]
        logger.info(f"Liquidity filter: Removed {initial_count - len(info_df)} stocks below the "
                    f"{self.config.LIQUIDITY_FILTER_PERCENTILE:.0%} market cap percentile (cutoff: ${liquidity_cutoff:,.0f}).")

        # Sector Filter
        initial_count = len(info_df)
        info_df = info_df[~info_df['sector'].str.strip().isin(self.config.SECTORS_TO_EXCLUDE)]
        logger.info(f"Sector filter: Removed {initial_count - len(info_df)} stocks from excluded sectors "
                    f"({self.config.SECTORS_TO_EXCLUDE}).")

        self.eligible_stocks = info_df
        logger.info(f"Finished universe filtering. {len(self.eligible_stocks)} stocks eligible.")

    def _calculate_momentum(self, timeframe: Literal['DAILY', 'WEEKLY', 'MONTHLY']) -> None:
        """
        Calculates momentum for a given timeframe based on the configuration.
        This version correctly handles daily data without resampling.

        Args:
            timeframe (str): The timeframe to use ('DAILY', 'WEEKLY', 'MONTHLY').
        """
        logger.info(f"Calculating momentum for timeframe: {timeframe}...")
        
        timeframe_map = {'WEEKLY': 'W', 'MONTHLY': 'ME'}
        lookback = self.config.MOMENTUM_LOOKBACKS[timeframe]
        lag = self.config.MOMENTUM_LAGS[timeframe]

        adj_close = self.historical_data['Adj Close']
        
        # --- START OF FIX ---
        # Only resample if the timeframe is not daily.
        if timeframe in timeframe_map:
            resample_code = timeframe_map[timeframe]
            prices = adj_close.resample(resample_code).last()
        elif timeframe == 'DAILY':
            # For daily, use the data as-is, no resampling needed.
            prices = adj_close
        else:
            raise ValueError(f"Invalid timeframe '{timeframe}' specified for momentum calculation.")
        # --- END OF FIX ---

        # Calculate momentum on the correctly prepared price series
        momentum = prices.pct_change(periods=lookback - lag, fill_method=None).shift(lag)
        
        latest_momentum = momentum.iloc[-1]
        self.eligible_stocks['Momentum'] = latest_momentum
        
        # Drop stocks where momentum could not be calculated
        self.eligible_stocks.dropna(subset=['Momentum'], inplace=True)
        
        logger.info(f"Momentum calculated for {len(self.eligible_stocks)} stocks using {timeframe} data.")

    def _apply_smoothness_filter(self, timeframe: Literal['DAILY', 'WEEKLY', 'MONTHLY']) -> None:
        """Applies the smoothness filter for the 'SMOOTH' strategy."""
        logger.info("Applying smoothness filter...")
        initial_count = len(self.eligible_stocks)
        self.eligible_stocks = self.eligible_stocks[self.eligible_stocks['Momentum'] > 0]
        logger.info(f"Removed {initial_count - len(self.eligible_stocks)} stocks with negative momentum.")
        
        timeframe_map = {'DAILY': 'D', 'WEEKLY': 'W', 'MONTHLY': 'M'}
        resample_code = timeframe_map[timeframe]
        lookback = self.config.MOMENTUM_LOOKBACKS[timeframe]

        adj_close = self.historical_data['Adj Close']
        resampled_prices = adj_close.resample(resample_code).last()
        resampled_returns = resampled_prices.pct_change()
        
        positive_periods_count = resampled_returns.iloc[-lookback:].apply(lambda x: np.sum(x > 0))
        self.eligible_stocks['PositivePeriods'] = positive_periods_count
        
        min_periods = self.config.SMOOTHNESS_MIN_POSITIVE_PERIODS
        initial_count = len(self.eligible_stocks)
        self.eligible_stocks = self.eligible_stocks[self.eligible_stocks['PositivePeriods'] >= min_periods]
        logger.info(f"Removed {initial_count - len(self.eligible_stocks)} stocks with fewer than {min_periods} positive {timeframe.lower()} periods.")
        
    def _apply_volatility_screen(self) -> None:
        """Applies the low volatility screen for the 'FROG_IN_PAN' strategy."""
        logger.info("Applying low volatility screen...")
        adj_close = self.historical_data['Adj Close']
        daily_returns = adj_close[self.eligible_stocks.index].pct_change()
        volatility = daily_returns.iloc[-self.config.VOLATILITY_LOOKBACK_DAYS:].std()
        self.eligible_stocks['Volatility'] = volatility
        self.eligible_stocks.dropna(subset=['Volatility'], inplace=True)
        
        volatility_cutoff = self.eligible_stocks['Volatility'].quantile(self.config.VOLATILITY_CUTOFF_PERCENTILE)
        initial_count = len(self.eligible_stocks)
        self.eligible_stocks = self.eligible_stocks[self.eligible_stocks['Volatility'] <= volatility_cutoff]
        logger.info(f"Volatility screen: Removed {initial_count - len(self.eligible_stocks)} stocks above the "
                    f"{self.config.VOLATILITY_CUTOFF_PERCENTILE:.0%} volatility percentile.")

    def generate_target_portfolio(self, timeframe: Literal['DAILY', 'WEEKLY', 'MONTHLY']) -> Tuple[Dict[str, List[str]], pd.DataFrame]:
        """
        Main public method to generate the target portfolio and a detailed report.

        Args:
            timeframe (str): The calculation timeframe ('DAILY', 'WEEKLY', 'MONTHLY').

        Returns:
            A dictionary of long/short ticker lists and a detailed report DataFrame.
        """
        strategy = self.config.STRATEGY_NAME
        logger.info(f"--- Starting portfolio construction for strategy: {strategy}, Timeframe: {timeframe} ---")

        # Initial filtering based on liquidity and sector
        self._apply_universe_filters()
        
        # Apply volatility screen FIRST if the strategy is FROG_IN_PAN
        if strategy == 'FROG_IN_PAN':
            self._apply_volatility_screen()
        else:
            self.eligible_stocks['Volatility'] = None # Ensure column exists for reporting

        # Calculate momentum based on the specified timeframe
        self._calculate_momentum(timeframe)

        # Apply smoothness filter if the strategy is SMOOTH
        if strategy == 'SMOOTH':
            self._apply_smoothness_filter(timeframe)

        logger.info("Ranking stocks and selecting top/bottom percentiles...")
        self.eligible_stocks['Rank'] = self.eligible_stocks['Momentum'].rank(ascending=False, method='first')
        
        # Use dropna() when creating deciles to handle cases with fewer than 10 stocks
        if len(self.eligible_stocks) >= 10:
            self.eligible_stocks['Decile'] = pd.qcut(self.eligible_stocks['Rank'], 10, labels=False, duplicates='drop') + 1
        else:
            self.eligible_stocks['Decile'] = 1
            
        report_df = self.eligible_stocks.sort_values(by='Rank')
        
        cutoff_n = int(len(report_df) * self.config.TOP_PERCENTILE_CUTOFF)
        if cutoff_n == 0 and len(report_df) > 0:
            cutoff_n = 1
        
        long_tickers = report_df.head(cutoff_n).index.tolist()
        short_tickers = report_df.tail(cutoff_n).index.tolist()
        
        logger.info(f"Final target portfolio generated. Longs: {len(long_tickers)}, Shorts: {len(short_tickers)}.")
        target_portfolio = {'longs': long_tickers, 'shorts': short_tickers}
        
        return target_portfolio, report_df