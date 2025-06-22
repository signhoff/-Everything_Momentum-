# quantitative_momentum_trader/main.py
"""
Main execution script for the Quantitative Momentum Trading System.

This script orchestrates the entire trading process:
1.  Sets up logging and loads configuration.
2.  Checks if the current day is a designated rebalancing day.
3.  Initializes the DataManager to fetch all required market and historical data.
4.  Instantiates the PortfolioConstructor to generate the new target portfolio
    based on the selected strategy.
5.  Connects to the Interactive Brokers TWS via the IBKRStockHandler.
6.  Initializes the ExecutionManager to compare the current and target portfolios,
    calculate the necessary trades, and execute them.
7.  Disconnects from the TWS upon completion.

This script is designed to be run on a schedule (e.g., a daily cron job).
"""

import logging
import datetime
import asyncio
import os

# --- Project-specific Imports ---
from configs import strategy_config, ibkr_config
from utils import logging_config
from engine.data_manager import DataManager
from engine.portfolio_constructor import PortfolioConstructor
from engine.execution_manager import ExecutionManager
from handlers.ibkr_stock_handler import IBKRStockHandler

# Initialize a logger for this main script
logger = logging.getLogger(__name__)

def is_rebalance_day() -> bool:
    """
    Determines if today is a rebalancing day based on the strategy configuration.

    Returns:
        bool: True if today is a rebalance day, False otherwise.
    """
    today = datetime.date.today()
    
    if strategy_config.REBALANCE_PERIOD == 'QUARTERLY':
        # Rebalance months: January (1), April (4), July (7), October (10)
        rebalance_months = [1, 4, 7, 10]
        if today.month not in rebalance_months:
            return False
    elif strategy_config.REBALANCE_PERIOD == 'MONTHLY':
        # Rebalance every month, no month check needed
        pass
    else:
        logger.error(f"Unknown rebalance period: {strategy_config.REBALANCE_PERIOD}")
        return False

    # Check if it's the Nth trading day of the month.
    # This is a simplified check assuming weekday = trading day.
    # A robust implementation would use a market calendar library.
    if today.weekday() >= 5: # Saturday or Sunday
        return False
        
    # Check if it's the first weekday of the month
    if today.day <= 7 and today.weekday() < 5: # First week
        # Simple check for the first trading day
        if strategy_config.REBALANCE_DAY_OF_PERIOD == 1:
            first_day_of_month = today.replace(day=1)
            # Find the first weekday
            first_trading_day = first_day_of_month
            while first_trading_day.weekday() >= 5:
                first_trading_day += datetime.timedelta(days=1)
            
            return today == first_trading_day
    
    return False

async def main_async_workflow():
    """
    The main asynchronous workflow for the trading system.
    """
    logger.info("--- Starting Quantitative Momentum Trading System ---")
    
    if not is_rebalance_day():
        logger.info("Today is not a rebalance day. Exiting.")
        return

    logger.info("REBALANCE DAY DETECTED. Starting the rebalancing process...")

    # --- 1. Data Acquisition ---
    logger.info("--- [Step 1/4] Data Acquisition ---")
    data_manager = DataManager(tickers_csv_path=strategy_config.UNIVERSE_TICKERS_CSV_PATH)
    hist_data = data_manager.fetch_historical_data(period=strategy_config.YFINANCE_DATA_PERIOD)
    comp_info = data_manager.fetch_company_info()

    if hist_data is None or not comp_info:
        logger.error("Failed to acquire necessary data. Aborting rebalance.")
        return

    # --- 2. Portfolio Construction ---
    logger.info("--- [Step 2/4] Portfolio Construction ---")
    portfolio_constructor = PortfolioConstructor(
        historical_data=hist_data,
        company_info=comp_info,
        config=strategy_config
    )
    target_portfolio_tickers = portfolio_constructor.generate_target_portfolio()
    
    if not target_portfolio_tickers:
        logger.warning("Portfolio construction resulted in an empty target portfolio. No trades will be made.")
        # Decide if we should liquidate everything or hold. For now, we just won't place new trades.
    
    logger.info(f"Generated target portfolio with {len(target_portfolio_tickers)} stocks.")

    # --- 3. Connection and Execution ---
    logger.info("--- [Step 3/4] Connection and Execution ---")
    ibkr_handler = IBKRStockHandler()
    
    try:
        # Connect to Interactive Brokers TWS
        is_connected = await ibkr_handler.connect(
            host=ibkr_config.HOST,
            port=ibkr_config.PORT,
            clientId=ibkr_config.CLIENT_ID_GUI_GENERAL
        )

        if not is_connected:
            logger.error("Failed to connect to IBKR TWS. Aborting execution.")
            return

        execution_manager = ExecutionManager(ibkr_handler, strategy_config)

        # Get current portfolio from IBKR
        current_portfolio = await execution_manager.get_current_portfolio()

        # Calculate trades needed
        orders = await execution_manager.calculate_rebalance_orders(
            target_portfolio=target_portfolio_tickers,
            current_portfolio=current_portfolio
        )
        
        # Execute the rebalance
        await execution_manager.execute_rebalance(
            orders_to_liquidate=orders['orders_to_liquidate'],
            orders_to_place=orders['orders_to_place']
        )

    except Exception as e:
        logger.error(f"An error occurred during the execution phase: {e}", exc_info=True)
    finally:
        # --- 4. Disconnect ---
        logger.info("--- [Step 4/4] Disconnecting ---")
        if ibkr_handler.is_connected():
            await ibkr_handler.disconnect()
        logger.info("--- Quantitative Momentum Trading System Finished ---")


if __name__ == "__main__":
    # Ensure log directory exists
    if not os.path.exists('logs'):
        os.makedirs('logs')
        
    # Setup logging configuration
    logging_config.setup_logging(log_level='INFO')
    
    # Run the main asynchronous event loop
    try:
        asyncio.run(main_async_workflow())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application manually interrupted. Shutting down.")
    except Exception as e:
        logger.critical(f"An unhandled critical error occurred in main: {e}", exc_info=True)