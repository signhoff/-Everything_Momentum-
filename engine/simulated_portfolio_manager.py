# quantitative_momentum_trader/engine/simulated_portfolio_manager.py
"""
Manages the state of a simulated trading portfolio.

This class handles loading and saving the portfolio's cash and positions
to a CSV file, allowing state to persist between script runs without
interacting with a live brokerage account for holdings.
"""

import logging
import os
import pandas as pd
from typing import Dict, List

logger = logging.getLogger(__name__)

class SimulatedPortfolioManager:
    """
    Manages portfolio state (cash, positions) via a local CSV file.
    """
    def __init__(self, csv_path: str, initial_cash: float):
        """
        Initializes the manager.

        Args:
            csv_path (str): The file path for the portfolio state CSV.
            initial_cash (float): The starting cash amount if no portfolio file exists.
        """
        self.csv_path = csv_path
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.positions: Dict[str, int] = {}
        self._load_portfolio()

    def _load_portfolio(self) -> None:
        """
        Loads the portfolio from the CSV file. If the file doesn't exist,
        it initializes a new portfolio with the starting cash.
        """
        if os.path.exists(self.csv_path):
            try:
                df = pd.read_csv(self.csv_path)
                # First row, 'Value' column is cash
                self.cash = float(df[df['Ticker'] == 'CASH']['Quantity'].iloc[0])
                # The rest are positions
                positions_df = df[df['Ticker'] != 'CASH']
                self.positions = dict(zip(positions_df['Ticker'], positions_df['Quantity'].astype(int)))
                logger.info(f"Successfully loaded portfolio from {self.csv_path}. Cash: ${self.cash:,.2f}, Positions: {len(self.positions)}")
            except Exception as e:
                logger.error(f"Error loading portfolio from {self.csv_path}. Reverting to initial state. Error: {e}")
                self._initialize_new_portfolio()
        else:
            logger.warning(f"Portfolio file not found at {self.csv_path}. Creating new portfolio.")
            self._initialize_new_portfolio()

    def _initialize_new_portfolio(self) -> None:
        """Sets the portfolio to its initial state and saves it."""
        self.cash = self.initial_cash
        self.positions = {}
        self.save_portfolio()

    def save_portfolio(self) -> None:
        """Saves the current portfolio state (cash and positions) to the CSV file."""
        try:
            cash_df = pd.DataFrame([{'Ticker': 'CASH', 'Quantity': self.cash}])
            
            # Check if there are any positions to save
            if self.positions:
                positions_df = pd.DataFrame(list(self.positions.items()), columns=['Ticker', 'Quantity'])
                # FIX for FutureWarning: Concat cash and positions DFs
                portfolio_df = pd.concat([cash_df, positions_df], ignore_index=True)
            else:
                # If no positions, just save the cash DataFrame
                portfolio_df = cash_df

            portfolio_df.to_csv(self.csv_path, index=False)
            logger.info(f"Successfully saved portfolio state to {self.csv_path}.")
        except Exception as e:
            logger.error(f"Failed to save portfolio state: {e}", exc_info=True)

    def get_total_value(self, current_prices: Dict[str, float]) -> float:
        """
        Calculates the total market value of the portfolio.

        Args:
            current_prices (Dict[str, float]): A dictionary mapping tickers to their current prices.

        Returns:
            float: The total portfolio value (cash + market value of all positions).
        """
        market_value = 0.0
        for ticker, quantity in self.positions.items():
            price = current_prices.get(ticker)
            if price is not None:
                market_value += quantity * price
            else:
                logger.warning(f"Could not find price for position {ticker} during valuation. It will be excluded.")
        
        return self.cash + market_value

    def simulate_trades(self, orders: List[Dict], prices: Dict[str, float]) -> None:
        """
        Updates the portfolio state by simulating the execution of trades.

        Args:
            orders (List[Dict]): A list of calculated order dictionaries.
            prices (Dict[str, float]): A dictionary mapping tickers to their execution prices.
        """
        logger.info("Simulating execution of trades to update portfolio state...")
        for order in orders:
            ticker = order['ticker']
            quantity = order['quantity']
            action = order['action']
            price = prices.get(ticker)

            if price is None:
                logger.error(f"Cannot simulate trade for {ticker}: No price available. Skipping order.")
                continue

            trade_value = quantity * price

            if action == 'BUY':
                self.cash -= trade_value
                self.positions[ticker] = self.positions.get(ticker, 0) + quantity
            elif action == 'SELL':
                self.cash += trade_value
                self.positions[ticker] = self.positions.get(ticker, 0) - quantity
            elif action == 'SSHORT':
                self.cash += trade_value  # Cash received from shorting
                self.positions[ticker] = self.positions.get(ticker, 0) - quantity
            
            # Clean up positions with zero quantity
            if self.positions.get(ticker) == 0:
                del self.positions[ticker]

        logger.info(f"Trade simulation complete. New cash: ${self.cash:,.2f}, Positions: {len(self.positions)}")