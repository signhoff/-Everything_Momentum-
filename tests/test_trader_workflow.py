# quantitative_momentum_trader/tests/test_trader_workflow.py
"""
Test file for the Quantitative Momentum Trading System with a Simulated Portfolio.

This script runs a full end-to-end "paper trade" simulation for MULTIPLE
strategies in a single execution. Its workflow is as follows:
1.  Downloads the main historical dataset once.
2.  Loops through a defined list of strategies ('FROG_IN_PAN', 'CORE', 'SMOOTH').
3.  For EACH strategy in the loop, it:
    a. Loads the strategy's specific portfolio state (e.g., 'CORE_portfolio_state.csv').
    b. Constructs a new target portfolio based on that strategy's rules.
    c. Saves a unique, timestamped, detailed report for that strategy.
    d. Connects to TWS to fetch live prices for valuation and calculation.
    e. Calculates the exact rebalancing trades needed for that strategy.
    f. Prints the calculated trades to the terminal.
    g. Simulates the trades and saves the new state to that strategy's specific CSV file.
"""

import logging
import asyncio
import os
import pandas as pd
import time
from datetime import datetime

# --- Project-specific Imports ---
from configs import strategy_config, ibkr_config
from utils import logging_config
from engine.data_manager import DataManager
from engine.portfolio_constructor import PortfolioConstructor
from engine.execution_manager import ExecutionManager
from engine.simulated_portfolio_manager import SimulatedPortfolioManager
from handlers.ibkr_stock_handler import IBKRStockHandler

logger = logging.getLogger(__name__)

async def run_simulation_workflow():
    """
    Main asynchronous workflow for the offline simulation.
    """
    logger.info("--- [BATCH SIMULATION RUN] Starting Quantitative Momentum Trading System ---")

    # --- Step 1 (Once): Data Acquisition ---
    print("\n--- [Step 1] Acquiring Base Historical Data (once for all strategies) ---")
    data_manager = DataManager(tickers_csv_path=strategy_config.UNIVERSE_TICKERS_CSV_PATH)
    hist_data = data_manager.fetch_historical_data(period=strategy_config.YFINANCE_DATA_PERIOD)
    if hist_data is None:
        logger.error("Failed to acquire historical data. Aborting run.")
        return
    # Fetch company info only for tickers with valid historical data
    valid_tickers = hist_data.columns.get_level_values('Ticker').unique().tolist()
    data_manager.universe_tickers = valid_tickers
    comp_info = data_manager.fetch_company_info()
    print("✅ Base historical and company data acquired.")

    # --- Define Strategies to Run ---
    strategies_to_run = ['FROG_IN_PAN', 'CORE', 'SMOOTH']

    # --- Main Loop to run for each strategy ---
    for strategy_name in strategies_to_run:
        print(f"\n\n================== Running Simulation for Strategy: {strategy_name} ==================")
        logger.info(f"--- Starting simulation for strategy: {strategy_name} ---")

        # --- Set the current strategy in the config object ---
        strategy_config.STRATEGY_NAME = strategy_name

        # --- Step 2: Load Simulated Portfolio for the specific strategy ---
        print(f"\n--- [Step 2/7] Loading Portfolio for {strategy_name} ---")
        portfolio_csv_path = os.path.join('data', f'{strategy_name}_portfolio_state.csv')
        sim_portfolio = SimulatedPortfolioManager(csv_path=portfolio_csv_path, initial_cash=50000.0)
        print(f"✅ Portfolio loaded. Cash: ${sim_portfolio.cash:,.2f}, Current Positions: {sim_portfolio.positions}")

        # --- Step 3: Portfolio Construction ---
        print(f"\n--- [Step 3/7] Constructing Portfolio for {strategy_name} ---")
        portfolio_constructor = PortfolioConstructor(hist_data, comp_info, strategy_config)
        target_portfolio, detailed_report_df = portfolio_constructor.generate_target_portfolio()
        print(f"✅ Target Portfolio generated. Longs: {len(target_portfolio['longs'])}, Shorts: {len(target_portfolio['shorts'])}")

        # Save the detailed analysis report with a unique timestamp
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{strategy_name}_report_{timestamp}.csv"
            report_path = os.path.join('output', filename)
            report_cols = ['Rank', 'Decile', 'Momentum', 'Volatility', 'marketCap', 'sector']
            final_cols = [col for col in report_cols if col in detailed_report_df.columns]
            detailed_report_df[final_cols].to_csv(report_path)
            print(f"✅ Detailed strategy report saved to: {report_path}")
        except Exception as e:
            logger.error(f"Failed to save detailed report for {strategy_name}: {e}")

        # --- Step 4: Fetch Live Prices via TWS ---
        print(f"\n--- [Step 4/7] Connecting to TWS for Live Prices ---")
        ibkr_handler = IBKRStockHandler()
        live_prices = {}
        try:
            is_connected = await ibkr_handler.connect(host=ibkr_config.HOST, port=ibkr_config.PORT, clientId=ibkr_config.CLIENT_ID_GUI_STOCK)
            if not is_connected:
                logger.error(f"Could not connect to TWS for {strategy_name}. Skipping to next strategy.")
                continue
            
            tickers_needed = set(sim_portfolio.positions.keys()) | set(target_portfolio['longs']) | set(target_portfolio['shorts'])
            print(f"Fetching live prices for {len(tickers_needed)} unique tickers...")
            for ticker in tickers_needed:
                price = await ibkr_handler.get_current_stock_price_async(ticker)
                if price:
                    live_prices[ticker] = price
                await asyncio.sleep(0.1)
            print(f"✅ Fetched {len(live_prices)} prices.")

        finally:
            if ibkr_handler.is_connected():
                await ibkr_handler.disconnect()
            print("✅ Disconnected from TWS.")

        # --- Step 5: Portfolio Valuation ---
        print(f"\n--- [Step 5/7] Portfolio Valuation for {strategy_name} ---")
        total_portfolio_value = sim_portfolio.get_total_value(live_prices)
        print(f"✅ Current Total Portfolio Value: ${total_portfolio_value:,.2f}")

        # --- Step 6: Trade Calculation ---
        print(f"\n--- [Step 6/7] Calculating Rebalance Orders for {strategy_name} ---")
        execution_manager = ExecutionManager(ibkr_handler=None, config=strategy_config)
        calculated_orders = await execution_manager.calculate_rebalance_orders(
            target_portfolio, sim_portfolio.positions, total_portfolio_value, live_prices
        )
        all_orders = calculated_orders.get('all_orders', [])
        print(f"\n--- [PROCESS OUTPUT for {strategy_name}] Calculated Trades ---")
        if all_orders:
            for order in all_orders:
                print(f"  - Action: {order['action']:<7} | Ticker: {order['ticker']:<6} | Quantity: {order['quantity']}")
        else:
            print("  - No trades needed. Portfolio is aligned with target.")

        # --- Step 7: Simulate & Save Portfolio State ---
        print(f"\n--- [Step 7/7] Simulating & Saving Portfolio State for {strategy_name} ---")
        sim_portfolio.simulate_trades(all_orders, live_prices)
        sim_portfolio.save_portfolio()
        print(f"✅ New portfolio state saved to {portfolio_csv_path}")

    print("\n\n================== Batch Simulation Run Finished ==================")


if __name__ == "__main__":
    # Setup directories if they don't exist
    for dir_name in ['logs', 'data', 'output']:
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
        
    logging_config.setup_logging(log_level='INFO')
    
    try:
        print("---")
        print("--- Make sure your Interactive Brokers TWS or Gateway is running ---")
        print("--- and API connections are enabled for live data fetching.      ---")
        input("Press Enter to start the batch simulation workflow...")
        asyncio.run(run_simulation_workflow())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Simulation run manually interrupted.")
    except Exception as e:
        logger.critical(f"An unhandled critical error occurred in the simulation: {e}", exc_info=True)