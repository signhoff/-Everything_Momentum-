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
from typing import List, Dict, Any, Tuple

# Initialize a logger for this module
logger = logging.getLogger(__name__)

class PortfolioConstructor:
    """
    Constructs a target portfolio based on a specified momentum strategy.
    """
    def __init__(self, historical_data: pd.DataFrame, company_info: Dict[str, Dict], config: Any):
        """
        Initializes the PortfolioConstructor.

        Args:
            historical_data (pd.DataFrame): A DataFrame containing historical OHLCV data.
                                            Must have a multi-level header with ('Adj Close', 'Ticker').
            company_info (Dict[str, Dict]): A dictionary with ticker keys and values containing
                                            'marketCap' and 'sector'.
            config (Any): A configuration object (e.g., a module) containing strategy parameters.
        """
        self.historical_data = historical_data
        self.company_info = company_info
        self.config = config
        self.eligible_stocks = pd.DataFrame()
        logger.info("PortfolioConstructor initialized.")

    def _apply_universe_filters(self) -> None:
        """
        Applies liquidity and sector filters to the initial stock universe.
        This method modifies `self.eligible_stocks`.
        """
        logger.info("Applying universe filters (liquidity and sector)...")
        
        # Create a DataFrame from the company info dictionary
        info_df = pd.DataFrame.from_dict(self.company_info, orient='index')
        info_df.index.name = 'Ticker'
        
        # Filter 1: Liquidity (Market Cap)
        info_df.dropna(subset=['marketCap'], inplace=True)
        liquidity_cutoff = info_df['marketCap'].quantile(self.config.LIQUIDITY_FILTER_PERCENTILE)
        initial_count = len(info_df)
        info_df = info_df[info_df['marketCap'] >= liquidity_cutoff]
        logger.info(f"Liquidity filter: Removed {initial_count - len(info_df)} stocks below the "
                    f"{self.config.LIQUIDITY_FILTER_PERCENTILE:.0%} market cap percentile (cutoff: ${liquidity_cutoff:,.0f}).")

        # Filter 2: Sector
        initial_count = len(info_df)
        info_df = info_df[~info_df['sector'].isin(self.config.SECTORS_TO_EXCLUDE)]
        logger.info(f"Sector filter: Removed {initial_count - len(info_df)} stocks from excluded sectors "
                    f"({self.config.SECTORS_TO_EXCLUDE}).")

        self.eligible_stocks = info_df
        logger.info(f"Finished universe filtering. {len(self.eligible_stocks)} stocks are eligible for momentum calculation.")

    def _calculate_12_2_momentum(self) -> None:
        """
        Calculates the 12-2 momentum for each stock in `self.eligible_stocks`.
        The result is stored as a new 'Momentum' column in `self.eligible_stocks`.
        """
        logger.info("Calculating 12-2 momentum...")
        adj_close = self.historical_data['Adj Close']
        monthly_prices = adj_close.resample('ME').last()
        momentum = monthly_prices.pct_change(periods=self.config.MOMENTUM_LOOKBACK - self.config.MOMENTUM_LAG).shift(self.config.MOMENTUM_LAG)
        latest_momentum = momentum.iloc[-1]
        self.eligible_stocks['Momentum'] = latest_momentum
        self.eligible_stocks.dropna(subset=['Momentum'], inplace=True)
        logger.info(f"Momentum calculated for {len(self.eligible_stocks)} stocks.")

    def _apply_smoothness_filter(self) -> None:
        """
        Applies the smoothness filter for the 'SMOOTH' strategy.
        Filters stocks based on the number of positive months and positive momentum score.
        This method modifies `self.eligible_stocks`.
        """
        logger.info("Applying smoothness filter...")
        initial_count = len(self.eligible_stocks)
        self.eligible_stocks = self.eligible_stocks[self.eligible_stocks['Momentum'] > 0]
        logger.info(f"Removed {initial_count - len(self.eligible_stocks)} stocks with negative momentum.")
        
        adj_close = self.historical_data['Adj Close']
        monthly_prices = adj_close.resample('M').last()
        monthly_returns = monthly_prices.pct_change()
        positive_months_count = monthly_returns.iloc[-self.config.MOMENTUM_LOOKBACK:].apply(lambda x: np.sum(x > 0))
        self.eligible_stocks['PositiveMonths'] = positive_months_count
        
        min_months = self.config.SMOOTHNESS_MIN_POSITIVE_MONTHS
        initial_count = len(self.eligible_stocks)
        self.eligible_stocks = self.eligible_stocks[self.eligible_stocks['PositiveMonths'] >= min_months]
        logger.info(f"Removed {initial_count - len(self.eligible_stocks)} stocks with fewer than {min_months} positive months.")
        
    def _apply_volatility_screen(self) -> None:
        """
        Applies the low volatility screen for the 'FROG_IN_PAN' strategy.
        Calculates daily return volatility, adds it as a column, and then removes
        the most volatile stocks. This method modifies `self.eligible_stocks`.
        """
        logger.info("Applying low volatility screen...")
        
        adj_close = self.historical_data['Adj Close']
        
        # Calculate daily returns only for eligible tickers to save computation
        eligible_tickers = self.eligible_stocks.index
        daily_returns = adj_close[eligible_tickers].pct_change()
        
        # Calculate volatility (standard deviation of daily returns) over the lookback period
        volatility = daily_returns.iloc[-self.config.VOLATILITY_LOOKBACK_DAYS:].std()
        
        # Add the calculated volatility as a new column
        self.eligible_stocks['Volatility'] = volatility
        
        # Remove stocks with no volatility score
        self.eligible_stocks.dropna(subset=['Volatility'], inplace=True)
        
        # Remove the most volatile stocks
        volatility_cutoff = self.eligible_stocks['Volatility'].quantile(self.config.VOLATILITY_CUTOFF_PERCENTILE)
        initial_count = len(self.eligible_stocks)
        self.eligible_stocks = self.eligible_stocks[self.eligible_stocks['Volatility'] <= volatility_cutoff]
        logger.info(f"Volatility screen: Removed {initial_count - len(self.eligible_stocks)} stocks above the "
                    f"{self.config.VOLATILITY_CUTOFF_PERCENTILE:.0%} volatility percentile.")

    def generate_target_portfolio(self) -> Tuple[Dict[str, List[str]], pd.DataFrame]:
        """
        Main public method to generate the target portfolio and a detailed report.
        Orchestrates filtering, calculation, and ranking based on the selected strategy.

        Returns:
            Tuple[Dict[str, List[str]], pd.DataFrame]: 
                - A dictionary with 'longs' and 'shorts' ticker lists.
                - A detailed pandas DataFrame with all calculated metrics for analysis.
        """
        strategy = self.config.STRATEGY_NAME
        logger.info(f"--- Starting portfolio construction for strategy: {strategy} ---")

        if strategy == 'FROG_IN_PAN':
            self.eligible_stocks = pd.DataFrame(index=self.historical_data['Adj Close'].columns)
            self._apply_volatility_screen()
            info_df = pd.DataFrame.from_dict(self.company_info, orient='index')
            self.eligible_stocks = self.eligible_stocks.join(info_df, how='inner')
            self._apply_universe_filters()
        else:
            self._apply_universe_filters()
            # For non-volatility strategies, we still want the column in the report
            self.eligible_stocks['Volatility'] = None
        
        self._calculate_12_2_momentum()

        if strategy == 'SMOOTH':
            self._apply_smoothness_filter()

        logger.info("Ranking stocks by momentum and selecting top and bottom percentiles...")
        
        # Add Rank and Decile columns for the report
        self.eligible_stocks['Rank'] = self.eligible_stocks['Momentum'].rank(ascending=False, method='first')
        self.eligible_stocks['Decile'] = pd.qcut(self.eligible_stocks['Rank'], 10, labels=False, duplicates='drop') + 1
        
        # Sort by rank for the final report
        report_df = self.eligible_stocks.sort_values(by='Rank')
        
        # Determine the number of stocks for each side of the portfolio
        cutoff_n = int(len(report_df) * self.config.TOP_PERCENTILE_CUTOFF)
        if cutoff_n == 0 and len(report_df) > 0:
            cutoff_n = 1 # Ensure at least one stock is selected if possible
        
        # Select the top N for the long portfolio
        long_portfolio_df = report_df.head(cutoff_n)
        long_tickers = long_portfolio_df.index.tolist()
        
        # Select the bottom N for the short portfolio
        short_portfolio_df = report_df.tail(cutoff_n)
        short_tickers = short_portfolio_df.index.tolist()
        
        logger.info(f"Final target portfolio generated. Longs: {len(long_tickers)}, Shorts: {len(short_tickers)}.")
        
        target_portfolio = {'longs': long_tickers, 'shorts': short_tickers}
        
        return target_portfolio, report_df