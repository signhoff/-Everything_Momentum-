# main.py
"""
Main application file for the Quantitative Momentum Trading System.

This script runs a full end-to-end "paper trade" simulation and execution.
It checks daily to see if a rebalance is due based on the strategy's timeframe
(daily, weekly, or monthly) and only runs on the first business day of that period.

Its workflow is as follows:
1.  On its scheduled run, it determines if a rebalance is due.
2.  If so, it downloads historical data and connects to TWS.
3.  It loops through strategies and timeframes due for rebalancing.
4.  For EACH due combination, it:
    a. Loads the local portfolio state.
    b. Constructs a new target portfolio.
    c. Fetches live prices for valuation.
    d. Calculates the exact rebalancing trades needed.
    e. Prompts the user for confirmation.
    f. Executes the trades in the TWS paper account.
    g. Simulates the trades locally to update the portfolio state file.
"""

import logging
import asyncio
import os
import pandas as pd
from datetime import datetime
from typing import List, Literal, Any

# --- Project-specific Imports ---
from configs import strategy_config, ibkr_config
from utils import logging_config
from engine.data_manager import DataManager
from engine.portfolio_constructor import PortfolioConstructor
from engine.execution_manager import ExecutionManager
from engine.simulated_portfolio_manager import SimulatedPortfolioManager
from handlers.ibkr_stock_handler import IBKRStockHandler

logger = logging.getLogger(__name__)


def is_rebalance_day(timeframe: Literal['DAILY', 'WEEKLY', 'MONTHLY']) -> bool:
    """
    Checks if today is the first valid business day for the rebalancing period.
    - DAILY: Always true.
    - WEEKLY: True if today is the first business day of the week (handles Monday holidays).
    - MONTHLY: True if today is the first business day of the month.
    """
    today = pd.to_datetime(datetime.today().date())  # Use pandas for robust date handling

    if timeframe == 'DAILY':
        logger.info("DAILY timeframe: Rebalancing is always triggered.")
        return True

    if timeframe == 'WEEKLY':
        # Find the start of the current week (Monday)
        start_of_week = today - pd.to_timedelta(today.dayofweek, unit='d')
        # The first business day of a period is the first date in a business-day range
        first_business_day = pd.bdate_range(start_of_week, start_of_week + pd.DateOffset(days=6))[0]
        if today == first_business_day:
            logger.info(f"WEEKLY timeframe: Today ({today.date()}) is the first business day of the week, triggering rebalance.")
            return True
        logger.info(f"WEEKLY timeframe: Today ({today.date()}) is not the first business day of the week (which is {first_business_day.date()}), skipping.")
        return False

    if timeframe == 'MONTHLY':
        # Find the start of the current month
        start_of_month = today.to_period('M').to_timestamp()
        # The first business day of a period is the first date in a business-day range
        first_business_day = pd.bdate_range(start_of_month, start_of_month + pd.DateOffset(days=6))[0]
        if today == first_business_day:
            logger.info(f"MONTHLY timeframe: Today ({today.date()}) is the first business day of the month, triggering rebalance.")
            return True
        logger.info(f"MONTHLY timeframe: Today ({today.date()}) is not the first business day of the month (which is {first_business_day.date()}), skipping.")
        return False

    return False


async def run_simulation_workflow():
    """
    Main asynchronous workflow. Connects to TWS, calculates trades,
    and executes them upon user confirmation.
    """
    logger.info("--- [LIVE PAPER TRADING RUN] Starting Quantitative Momentum Trading System ---")

    # --- Define Strategies and Timeframes to Run ---o
    strategies_to_run: List[Literal['CORE', 'SMOOTH', 'FROG_IN_PAN']] = ['CORE', 'SMOOTH', 'FROG_IN_PAN']
    timeframes_to_run: List[Literal['DAILY', 'WEEKLY', 'MONTHLY']] = ['MONTHLY', 'WEEKLY', 'DAILY']
    initial_portfolio_cash = 10000.0

    # --- Check which timeframes are due for rebalancing ---
    timeframes_due = [tf for tf in timeframes_to_run if is_rebalance_day(tf)]

    if not timeframes_due:
        logger.info("No timeframes are due for rebalancing today. Exiting workflow.")
        print("No timeframes are due for rebalancing today.")
        return

    # --- Step 1 (Once): Data Acquisition ---
    print("\n--- [Step 1] Acquiring Base Historical Data (once for all simulations) ---")
    data_manager = DataManager(tickers_csv_path=strategy_config.UNIVERSE_TICKERS_CSV_PATH)
    hist_data = data_manager.fetch_historical_data()
    if hist_data is None:
        logger.error("Failed to acquire historical data. Aborting run.")
        return
    comp_info = data_manager.fetch_company_info()
    print("✅ Base historical and company data acquired.")

    # --- Manage a single IBKR connection for the entire run ---
    ibkr_handler = IBKRStockHandler()
    try:
        # Connect once at the beginning
        print("\n--- [Connecting to TWS] ---")
        is_connected = await ibkr_handler.connect(host=ibkr_config.HOST, port=ibkr_config.PORT, clientId=ibkr_config.CLIENT_ID_GUI_GENERAL)
        if not is_connected:
            logger.critical("Could not connect to TWS. Aborting run.")
            print("❌ Could not connect to TWS. Please ensure TWS is running and API is enabled.")
            return
        print("✅ Connected to TWS.")

        # --- Main Loop to run for each DUE strategy and timeframe ---
        for timeframe in timeframes_due:
            for strategy_name in strategies_to_run:
                print(f"\n\n================== Running: Strategy={strategy_name}, Timeframe={timeframe} ==================")
                logger.info(f"--- Starting simulation for Strategy: {strategy_name}, Timeframe: {timeframe} ---")

                strategy_config.STRATEGY_NAME = strategy_name

                # --- Step 2: Load Simulated Portfolio ---
                portfolio_file = f'{strategy_name}_{timeframe}_portfolio_state.csv'
                portfolio_csv_path = os.path.join('data', portfolio_file)
                print(f"\n--- [Step 2/8] Loading Portfolio: {portfolio_file} ---")
                sim_portfolio = SimulatedPortfolioManager(csv_path=portfolio_csv_path, initial_cash=initial_portfolio_cash)
                print(f"✅ Portfolio loaded. Cash: ${sim_portfolio.cash:,.2f}, Positions: {len(sim_portfolio.positions)}")

                # --- Step 3: Portfolio Construction ---
                print(f"\n--- [Step 3/8] Constructing Target Portfolio ---")
                portfolio_constructor = PortfolioConstructor(hist_data, comp_info, strategy_config)
                target_portfolio, detailed_report_df = portfolio_constructor.generate_target_portfolio(timeframe=timeframe)
                print(f"✅ Target Portfolio generated. Longs: {len(target_portfolio['longs'])}, Shorts: {len(target_portfolio['shorts'])}")

                # --- Step 4: Save Detailed Report ---
                print(f"\n--- [Step 4/8] Saving Detailed Report ---")
                try:
                    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    report_file = f"{strategy_name}_{timeframe}_report_{timestamp}.csv"
                    report_path = os.path.join('output', report_file)
                    report_cols = ['Rank', 'Decile', 'Momentum', 'Volatility', 'PositivePeriods', 'marketCap', 'sector']
                    final_cols = [col for col in report_cols if col in detailed_report_df.columns]
                    if not detailed_report_df.empty:
                        detailed_report_df[final_cols].to_csv(report_path)
                        print(f"✅ Detailed report saved to: {report_path}")
                except Exception as e:
                    logger.error(f"Failed to save detailed report: {e}")

                # --- Step 5: Fetch Live Prices via TWS ---
                print(f"\n--- [Step 5/8] Fetching Live Prices ---")
                tickers_needed = set(sim_portfolio.positions.keys()) | set(target_portfolio.get('longs', [])) | set(target_portfolio.get('shorts', []))
                print(f"Fetching live prices for {len(tickers_needed)} unique tickers...")
                live_prices = await ibkr_handler.get_current_stock_prices_for_tickers(list(tickers_needed))
                print(f"✅ Fetched {len(live_prices)} prices.")

                # --- Step 6: Portfolio Valuation ---
                print(f"\n--- [Step 6/8] Portfolio Valuation ---")
                total_portfolio_value = sim_portfolio.get_total_value(live_prices)
                print(f"✅ Current Total Portfolio Value: ${total_portfolio_value:,.2f}")

                # --- Step 7: Trade Calculation ---
                print(f"\n--- [Step 7/8] Calculating Rebalance Orders ---")
                # Create a temporary ExecutionManager for calculation only (handler is None)
                temp_exec_manager = ExecutionManager(ibkr_handler=None, config=strategy_config)
                calculated_orders = await temp_exec_manager.calculate_rebalance_orders(
                    target_portfolio, sim_portfolio.positions, total_portfolio_value, live_prices
                )
                all_orders = calculated_orders.get('all_orders', [])

                print(f"\n--- [PROCESS OUTPUT] Calculated Trades for {strategy_name} ({timeframe}) ---")
                if all_orders:
                    for order in all_orders:
                        print(f"  - {order['action']:<7} | {order['ticker']:<6} | Qty: {order['quantity']}")
                else:
                    print("  - No trades needed. Portfolio is aligned with target.")

                # --- Step 8: Trade Execution (Live in TWS) ---
                print(f"\n--- [Step 8/8] EXECUTION ---")
                if all_orders:
                    try:
                        # SAFETY PROMPT
                        confirm = input("Press Enter to execute the calculated trades in TWS Paper Account, or type 'skip' to continue without trading: ")
                        if confirm.lower() == 'skip':
                            print("Skipping execution for this run.")
                            logger.warning("User skipped trade execution.")
                        else:
                            # Create a new ExecutionManager with the live handler for execution
                            live_exec_manager = ExecutionManager(ibkr_handler=ibkr_handler, config=strategy_config)
                            await live_exec_manager.execute_rebalance_orders(all_orders)
                            print("✅ Orders submitted to TWS.")
                    except (KeyboardInterrupt, SystemExit):
                        logger.warning("Execution interrupted by user.")
                        print("\nExecution aborted by user.")
                        # Do not proceed with saving state if execution was aborted
                        return
                
                # Always simulate the trades to keep the local portfolio state file up-to-date
                sim_portfolio.simulate_trades(all_orders, live_prices)
                sim_portfolio.save_portfolio()
                print(f"✅ New portfolio state saved to {portfolio_csv_path}")

    finally:
        # Disconnect at the very end
        if ibkr_handler.is_connected():
            print("\n--- [Disconnecting from TWS] ---")
            await ibkr_handler.disconnect()
            print("✅ Disconnected from TWS.")

    print("\n\n================== Live Paper Trading Run Finished ==================")


if __name__ == "__main__":
    for dir_name in ['logs', 'data', 'output']:
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)

    logging_config.setup_logging(log_level='INFO')

    try:
        print("---")
        print("--- Make sure your Interactive Brokers TWS or Gateway is running ---")
        print(f"--- and the API port is set to {ibkr_config.PORT} for paper trading. ---")
        input("Press Enter to start the batch simulation workflow...")
        asyncio.run(run_simulation_workflow())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Simulation run manually interrupted.")
    except Exception as e:
        logger.critical(f"An unhandled critical error occurred in the simulation: {e}", exc_info=True)