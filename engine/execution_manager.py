# engine/execution_manager.py
"""
Handles the calculation and execution of rebalancing trades.
"""
import logging
import math
import asyncio
from typing import Dict, List, Any

# --- NEW: Imports for creating IBKR Contracts and Orders ---
from ibapi.contract import Contract
from ibapi.order import Order

# --- Project-specific Imports ---
from handlers.ibkr_stock_handler import IBKRStockHandler

logger = logging.getLogger(__name__)

class ExecutionManager:
    """
    Calculates rebalancing orders and executes them via the IBKR handler.
    """
    # --- MODIFIED: __init__ now requires an IBKRStockHandler instance ---
    def __init__(self, ibkr_handler: IBKRStockHandler, config: Any):
        """
        Initializes the ExecutionManager.

        Args:
            ibkr_handler (IBKRStockHandler): An active IBKR handler for placing orders.
            config (Any): The strategy configuration module.
        """
        self.ibkr_handler = ibkr_handler
        self.config = config
        logger.info("ExecutionManager initialized for live order execution.")

    async def calculate_rebalance_orders(self,
                                         target_portfolio: Dict[str, List[str]],
                                         current_positions: Dict[str, int],
                                         total_portfolio_value: float,
                                         current_prices: Dict[str, float]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Calculates the orders needed to rebalance the current portfolio to the target.

        Args:
            target_portfolio (Dict[str, List[str]]): Dict with 'longs' and 'shorts' lists.
            current_positions (Dict[str, int]): Dict of current tickers and quantities.
            total_portfolio_value (float): The total current value of the portfolio.
            current_prices (Dict[str, float]): Dict of tickers and their live prices.

        Returns:
            Dict containing a list of all order details.
        """
        all_orders: List[Dict[str, Any]] = []
        
        target_longs = set(target_portfolio.get('longs', []))
        target_shorts = set(target_portfolio.get('shorts', []))
        current_holdings = set(current_positions.keys())

        # --- Step 1: Calculate Sell Orders ---
        # Sell longs that are no longer in the target long portfolio.
        longs_to_sell = current_holdings.intersection(
            {t for t, q in current_positions.items() if q > 0}
        ) - target_longs
        
        for ticker in longs_to_sell:
            quantity_to_sell = current_positions[ticker]
            all_orders.append({
                'action': 'SELL', 'ticker': ticker, 'quantity': quantity_to_sell,
                'orderType': self.config.ORDER_TYPE
            })
            logger.info(f"Calculated SELL order for {quantity_to_sell} shares of {ticker}.")

        # Cover shorts that are no longer in the target short portfolio.
        shorts_to_cover = current_holdings.intersection(
            {t for t, q in current_positions.items() if q < 0}
        ) - target_shorts
        
        for ticker in shorts_to_cover:
            # Quantity will be negative, so we take its absolute value
            quantity_to_buy_back = abs(current_positions[ticker])
            all_orders.append({
                'action': 'BUY', 'ticker': ticker, 'quantity': quantity_to_buy_back,
                'orderType': self.config.ORDER_TYPE
            })
            logger.info(f"Calculated BUY to cover order for {quantity_to_buy_back} shares of {ticker}.")

        # --- Step 2: Calculate Buy/Short Orders ---
        # The total number of positions we want to hold (long and short)
        total_target_positions = len(target_longs) + len(target_shorts)
        if total_target_positions == 0:
            logger.info("Target portfolio is empty, no new buy/short orders to calculate.")
            return {'all_orders': all_orders}

        # Calculate position size, assuming equal weight for simplicity
        # For a long/short portfolio, total value is used to size each leg.
        # A more complex model might allocate 100% to longs and 100% to shorts.
        # Here we use a simpler equal weight across all positions.
        position_size_per_stock = total_portfolio_value / total_target_positions

        # Buy new longs that are not in the current portfolio.
        longs_to_buy = target_longs - current_holdings
        for ticker in longs_to_buy:
            price = current_prices.get(ticker)
            if price and price > 0:
                quantity_to_buy = math.floor(position_size_per_stock / price)
                if quantity_to_buy > 0:
                    all_orders.append({
                        'action': 'BUY', 'ticker': ticker, 'quantity': quantity_to_buy,
                        'orderType': self.config.ORDER_TYPE
                    })
                    logger.info(f"Calculated BUY order for {quantity_to_buy} shares of {ticker}.")
            else:
                logger.warning(f"Could not get a valid price for {ticker}, cannot calculate buy order.")
        
        # Short new shorts that are not in the current portfolio.
        shorts_to_add = target_shorts - current_holdings
        for ticker in shorts_to_add:
            price = current_prices.get(ticker)
            if price and price > 0:
                quantity_to_short = math.floor(position_size_per_stock / price)
                if quantity_to_short > 0:
                     all_orders.append({
                        'action': 'SELL', 'ticker': ticker, 'quantity': quantity_to_short,
                        'orderType': self.config.ORDER_TYPE
                    })
                     logger.info(f"Calculated SELL (short) order for {quantity_to_short} shares of {ticker}.")
            else:
                logger.warning(f"Could not get a valid price for {ticker}, cannot calculate short order.")
                
        return {'all_orders': all_orders}


    # --- NEW: Method to execute trades ---
    async def execute_rebalance_orders(self, calculated_orders: List[Dict[str, Any]]):
        """
        Executes a list of calculated orders in TWS.

        Args:
            calculated_orders (List[Dict[str, Any]]): The list of orders to execute.
                                                      From the 'all_orders' key.
        """
        if not calculated_orders:
            logger.info("No orders to execute.")
            return

        logger.info(f"Preparing to execute {len(calculated_orders)} orders.")
        for order_details in calculated_orders:
            ticker = order_details['ticker']
            
            # 1. Create the IBKR Contract object
            contract = Contract()
            contract.symbol = ticker
            contract.secType = "STK"
            contract.exchange = "SMART"
            contract.currency = "USD"

            # 2. Create the IBKR Order object
            order = Order()
            order.action = order_details['action']
            order.orderType = self.config.ORDER_TYPE
            order.totalQuantity = order_details['quantity']
            order.outsideRth = self.config.EXECUTE_ORDERS_OUTSIDE_RTH
            
            # 3. Place the order
            print(f"  - Submitting {order.action} order for {order.totalQuantity} shares of {ticker}...")
            try:
                # --- MODIFIED: Swapped arguments to match the new standardized function signature ---
                await self.ibkr_handler.execute_order_async(contract, order)
                
                # Use configured delay to avoid overwhelming the API
                await asyncio.sleep(self.config.DELAY_BETWEEN_BUYS_S)
            except Exception as e:
                logger.error(f"Failed to place order for {ticker}: {e}", exc_info=True)
                print(f"  - ERROR placing order for {ticker}. Check logs.")