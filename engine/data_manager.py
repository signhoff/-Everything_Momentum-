#engine/data_manager.py
"""
Data Manager for the Quantitative Momentum Trading System.

This module is responsible for all data acquisition tasks, including:
- Loading the initial stock universe from a CSV file.
- Caching and retrieving historical price data.
- Caching and retrieving company fundamental data (market cap, sector).
"""

import logging
import os
import pandas as pd
import numpy as np
import yfinance as yf
import time
import json
from datetime import datetime
from typing import List, Dict, Optional, Any

# Assuming strategy_config is in the configs directory, accessible from the project root
from configs import strategy_config

logger = logging.getLogger(__name__)

class DataManager:
    """
    Handles fetching and managing all financial data, with a focus on daily caching
    to minimize API calls to yfinance.
    """
    def __init__(self, tickers_csv_path: str):
        """
        Initializes the DataManager by loading the universe data from the specified CSV.
        The CSV must contain 'Ticker' and 'Sector' columns.

        Args:
            tickers_csv_path (str): The file path to the CSV containing tickers and sectors.
        """
        self.tickers_csv_path = tickers_csv_path
        self.universe_df = pd.DataFrame()
        self.universe_tickers: List[str] = []
        
        try:
            self.universe_df = pd.read_csv(self.tickers_csv_path)
            if 'Ticker' not in self.universe_df.columns or 'Sector' not in self.universe_df.columns:
                raise ValueError("CSV must contain 'Ticker' and 'Sector' columns.")
            
            self.universe_tickers = self.universe_df['Ticker'].dropna().str.upper().unique().tolist()
            logger.info(f"Successfully loaded {len(self.universe_tickers)} unique tickers and their sectors.")
        except FileNotFoundError:
            logger.error(f"Ticker universe file not found at: {self.tickers_csv_path}")
        except Exception as e:
            logger.error(f"An error occurred while reading the ticker file: {e}", exc_info=True)

        self.raw_historical_data: Optional[pd.DataFrame] = None
        self.company_info: Dict[str, Dict] = {}
        
        # Define paths for both cache files
        self.historical_data_cache_path = os.path.join('data', 'historical_data.parquet')
        self.company_info_cache_path = os.path.join('data', 'company_info.json')

        logger.info(f"DataManager initialized with {len(self.universe_tickers)} tickers from {tickers_csv_path}.")

    def _get_required_fetch_period(self) -> str:
        """
        Calculates the required yfinance fetch period based on the longest lookback.
        This makes the data fetching robust to changes in strategy lookback configs.

        Returns:
            str: The period string for yfinance download (e.g., "2y", "3y").
        """
        lookbacks = strategy_config.MOMENTUM_LOOKBACKS
        
        # Convert all lookbacks to an approximate number of years
        daily_years = lookbacks.get('DAILY', 0) / 252.0
        weekly_years = lookbacks.get('WEEKLY', 0) / 52.0
        monthly_years = lookbacks.get('MONTHLY', 0) / 12.0

        # Find the longest lookback required in years
        max_years_required = max(daily_years, weekly_years, monthly_years, 1.0) # Ensure at least 1 year
        
        # Add a 1-year buffer for lags and calendar differences, then round up
        fetch_years = int(np.ceil(max_years_required)) + 1
        
        logger.info(f"Determined that {fetch_years} years of data are needed to satisfy all lookback periods.")
        return f"{fetch_years}y"

    def fetch_historical_data(self, interval: str = "1d") -> Optional[pd.DataFrame]:
        """
        Fetches historical OHLCV data. It first checks for a fresh local cache
        (from the same day) before downloading from yfinance. The download period
        is dynamically determined by the strategy configurations.

        Args:
            interval (str): The data interval.

        Returns:
            Optional[pd.DataFrame]: The historical data DataFrame.
        """
        if os.path.exists(self.historical_data_cache_path):
            file_mod_time = datetime.fromtimestamp(os.path.getmtime(self.historical_data_cache_path))
            if file_mod_time.date() == datetime.today().date():
                logger.info(f"Loading fresh historical data from cache: {self.historical_data_cache_path}")
                self.raw_historical_data = pd.read_parquet(self.historical_data_cache_path)
                return self.raw_historical_data

        # Dynamically determine the required period
        fetch_period = self._get_required_fetch_period()
        logger.info(f"Cache not found or stale. Downloading {fetch_period} of fresh historical data from yfinance...")
        
        if not self.universe_tickers:
            logger.warning("Cannot fetch historical data: ticker universe is empty.")
            return None

        try:
            # Use the dynamically calculated period for the download
            data = yf.download(self.universe_tickers, period=fetch_period, interval=interval, auto_adjust=False)
            if data is None or data.empty:
                logger.warning("yfinance download returned no data.")
                return None

            data = data.dropna(axis=1, how='all')
            self.raw_historical_data = data
            
            logger.info(f"Saving fresh historical data to cache: {self.historical_data_cache_path}")
            self.raw_historical_data.to_parquet(self.historical_data_cache_path)
            return self.raw_historical_data
        except Exception as e:
            logger.error(f"An error occurred during yfinance download: {e}", exc_info=True)
            return None

    def fetch_company_info(self) -> Dict[str, Dict]:
        """
        Fetches company info. Checks for a fresh local cache (from the same day)
        before fetching market caps from yfinance. Sector data is always sourced
        from the local CSV file.

        Returns:
            Dict[str, Dict]: A dictionary containing 'marketCap' and 'sector' for each ticker.
        """
        if os.path.exists(self.company_info_cache_path):
            file_mod_time = datetime.fromtimestamp(os.path.getmtime(self.company_info_cache_path))
            if file_mod_time.date() == datetime.today().date():
                logger.info(f"Loading fresh company info from cache: {self.company_info_cache_path}")
                with open(self.company_info_cache_path, 'r') as f:
                    self.company_info = json.load(f)
                return self.company_info
        
        logger.info("Company info cache not found or stale. Processing fresh info...")
        info_df = self.universe_df.set_index('Ticker')['Sector'].to_dict()
        final_info_dict = {ticker: {'sector': sector, 'marketCap': None} for ticker, sector in info_df.items()}

        logger.info("Fetching market caps from yfinance...")
        for i, ticker in enumerate(self.universe_tickers):
            try:
                if (i + 1) % 50 == 0:
                    logger.info(f"Progress: Fetched market cap for {i+1}/{len(self.universe_tickers)} tickers.")

                t = yf.Ticker(ticker)
                market_cap = t.info.get('marketCap')
                time.sleep(0.05) # Small delay to be polite to the API

                if ticker in final_info_dict:
                    final_info_dict[ticker]['marketCap'] = market_cap
                
            except Exception as e:
                logger.warning(f"Could not fetch market cap for ticker {ticker}: {e}")
                if ticker in final_info_dict:
                    final_info_dict[ticker]['marketCap'] = None

        self.company_info = final_info_dict
        
        logger.info(f"Saving fresh company info to cache: {self.company_info_cache_path}")
        with open(self.company_info_cache_path, 'w') as f:
            json.dump(self.company_info, f, indent=4)

        logger.info("Finished processing all company info.")
        return self.company_info