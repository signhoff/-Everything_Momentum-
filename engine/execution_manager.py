# quantitative_momentum_trader/engine/execution_manager.py
"""
Execution Manager for the Quantitative Momentum Trading System.

This module is responsible for the trade calculation part of the rebalancing process.
It interfaces with the Interactive Brokers (IBKR) handler to get prices, and calculates
the necessary buy/sell orders to align the portfolio based on total value.
"""

import logging
from typing import List, Dict, Any, Optional
import math

from ibapi.contract import Contract
from ibapi.order import Order

from handlers.ibkr_stock_handler import IBKRStockHandler

logger = logging.getLogger(__name__)

class ExecutionManager:
    """
    Manages the rebalancing calculation by interacting with a brokerage handler.
    """
    def __init__(self, ibkr_handler: Optional[IBKRStockHandler], config: Any):
        self.ibkr_handler = ibkr_handler
        self.config = config
        logger.info("ExecutionManager initialized.")

    async def calculate_rebalance_orders(
        self, 
        target_portfolio: Dict[str, List[str]], 
        current_portfolio: Dict[str, int],
        total_portfolio_value: float,
        current_prices: Dict[str, float]
    ) -> Dict[str, List[Dict]]:
        """
        Compares the target and current portfolios to generate rebalancing orders
        with actual quantities based on an equal-weighting scheme.

        Args:
            target_portfolio (Dict[str, List[str]]): Dict with 'longs' and 'shorts' lists.
            current_portfolio (Dict[str, int]): The current positions from the simulation.
            total_portfolio_value (float): The total current value of the simulated portfolio.
            current_prices (Dict[str, float]): A dictionary of current market prices for tickers.

        Returns:
            Dict[str, List[Dict]]: A dictionary containing four lists of calculated orders.
        """
        logger.info("Calculating rebalancing orders for long/short portfolio...")
        
        target_longs = target_portfolio.get('longs', [])
        target_shorts = target_portfolio.get('shorts', [])
        
        # Determine the dollar amount to allocate to each position
        # For a long/short portfolio, we allocate half the value to longs and half to shorts.
        total_positions = len(target_longs) + len(target_shorts)
        if total_positions == 0:
            logger.warning("Target portfolio is empty, no new positions to calculate.")
            position_size_per_stock = 0
        else:
            # This is a simplified equal-weight allocation
            position_size_per_stock = total_portfolio_value / total_positions

        # --- Calculate target quantities for new portfolio ---
        target_quantities = {}
        for ticker in target_longs:
            price = current_prices.get(ticker)
            if price:
                target_quantities[ticker] = math.floor(position_size_per_stock / price)
        for ticker in target_shorts:
            price = current_prices.get(ticker)
            if price:
                # Store short quantities as negative numbers
                target_quantities[ticker] = -math.floor(position_size_per_stock / price)

        # --- Determine actions by comparing current state to target state ---
        all_relevant_tickers = set(current_portfolio.keys()) | set(target_quantities.keys())
        orders = []

        for ticker in all_relevant_tickers:
            current_qty = current_portfolio.get(ticker, 0)
            target_qty = target_quantities.get(ticker, 0)
            
            if current_qty == target_qty:
                continue # No trade needed

            trade_qty = abs(target_qty - current_qty)
            
            if target_qty > current_qty:
                # Need to buy (either to open a new long or cover/reduce a short)
                action = 'BUY'
            else:
                # Need to sell (either to close a long or open/add to a short)
                action = 'SELL' if current_qty > 0 else 'SSHORT'

            orders.append({
                'ticker': ticker, 'action': action, 'quantity': trade_qty, 'order_type': self.config.ORDER_TYPE
            })

        logger.info(f"Order calculation complete. Total orders to place: {len(orders)}.")
        return {'all_orders': orders}