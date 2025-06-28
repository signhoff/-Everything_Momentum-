# run_simulation_yfinance.py
"""
Offline simulation script for the Quantitative Momentum Trading System.

This script is a clone of the original trader workflow but uses yfinance to
fetch the most recent closing prices instead of a live connection to
Interactive Brokers. This allows for completely offline back-testing and analysis.

Its workflow is as follows:
1.  Acquires the main historical dataset once.
2.  Loops through defined strategies and timeframes.
3.  For EACH combination, it:
    a. Loads the strategy's specific portfolio state.
    b. Constructs a new target portfolio.
    c. Saves a detailed CSV report with full stock rankings.
    d. Fetches the latest closing prices from yfinance.
    e. Calculates the exact rebalancing trades needed.
    f. Simulates the trades and saves the new portfolio state file.
"""

import logging
import asyncio
import os
import pandas as pd
import yfinance as yf
from datetime import datetime
from typing import List, Dict, Any, Tuple

# --- Project-specific Imports ---
# Note: ibkr_config and ibkr_stock_handler are NOT imported.
from configs import strategy_config
from utils import logging_config
from engine.data_manager import DataManager
from engine.portfolio_constructor import PortfolioConstructor
from engine.execution_manager import ExecutionManager
from engine.simulated_portfolio_manager import SimulatedPortfolioManager

logger = logging.getLogger(__name__)

async def run_yfinance_simulation():
    """
    Main asynchronous workflow for the yfinance-based offline simulation.
    """
    logger.info("--- [YFINANCE OFFLINE SIMULATION] Starting ---")

    # --- Step 1 (Once): Data Acquisition ---
    print("\n--- [Step 1] Acquiring Base Historical Data ---")
    data_manager = DataManager(tickers_csv_path=strategy_config.UNIVERSE_TICKERS_CSV_PATH)
    hist_data = data_manager.fetch_historical_data()
    if hist_data is None:
        logger.error("Failed to acquire historical data. Aborting run.")
        return
    valid_tickers = hist_data.columns.get_level_values('Ticker').unique().tolist()
    data_manager.universe_tickers = valid_tickers
    comp_info = data_manager.fetch_company_info()
    print("✅ Base historical and company data acquired.")

    # --- Define Strategies to Run ---
    strategies_to_run = ['FROG_IN_PAN', 'CORE']
    timeframes_to_run = ['WEEKLY', 'DAILY']

    # --- Main Loop to run for each strategy ---
    for timeframe in timeframes_to_run:
        for strategy_name in strategies_to_run:
            print(f"\n\n================== Running Simulation for Strategy: {strategy_name}, Timeframe: {timeframe} ==================")
            logger.info(f"--- Starting simulation for strategy: {strategy_name}, timeframe: {timeframe} ---")

            # --- Set the current strategy in the config object ---
            strategy_config.STRATEGY_NAME = strategy_name

            # --- Step 2: Load Simulated Portfolio for the specific strategy ---
            portfolio_file = f'{strategy_name}_{timeframe}_portfolio_state.csv'
            print(f"\n--- [Step 2/7] Loading Portfolio for {strategy_name} ({timeframe}) ---")
            portfolio_csv_path = os.path.join('data', portfolio_file)
            sim_portfolio = SimulatedPortfolioManager(csv_path=portfolio_csv_path, initial_cash=5000.0)
            print(f"✅ Portfolio loaded. Cash: ${sim_portfolio.cash:,.2f}, Current Positions: {len(sim_portfolio.positions)}")

            # --- Step 3: Portfolio Construction ---
            print(f"\n--- [Step 3/7] Constructing Portfolio for {strategy_name} ({timeframe}) ---")
            portfolio_constructor = PortfolioConstructor(hist_data, comp_info, strategy_config)
            target_portfolio, detailed_report_df = portfolio_constructor.generate_target_portfolio(timeframe=timeframe)
            print(f"✅ Target Portfolio generated. Longs: {len(target_portfolio['longs'])}, Shorts: {len(target_portfolio['shorts'])}")

            # Save the detailed analysis report with a unique timestamp
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                filename = f"{strategy_name}_{timeframe}_report_{timestamp}.csv"
                report_path = os.path.join('output', filename)
                report_cols = ['Rank', 'Decile', 'Momentum', 'Volatility', 'PositivePeriods', 'marketCap', 'sector']
                final_cols = [col for col in report_cols if col in detailed_report_df.columns]
                detailed_report_df[final_cols].to_csv(report_path)
                print(f"✅ Detailed strategy report saved to: {report_path}")
            except Exception as e:
                logger.error(f"Failed to save detailed report for {strategy_name}: {e}")

            # --- Step 4: Fetch Latest Prices from yfinance ---
            print(f"\n--- [Step 4/7] Fetching Latest Prices from yfinance ---")
            live_prices = {}
            tickers_needed = list(set(sim_portfolio.positions.keys()) | set(target_portfolio.get('longs', [])) | set(target_portfolio.get('shorts', [])))

            if tickers_needed:
                try:
                    # Fetch last 2 days to ensure we get the most recent closing price
                    data = yf.download(tickers=tickers_needed, period="2d", interval="1d", progress=False)
                    if not data.empty and 'Adj Close' in data:
                        # Get the last available closing price for each ticker
                        last_prices = data['Adj Close'].iloc[-1]
                        live_prices = last_prices.dropna().to_dict()
                        print(f"✅ Fetched {len(live_prices)} prices from yfinance.")
                    else:
                        logger.warning(f"yfinance returned no data for tickers: {tickers_needed}")
                        print("- yfinance returned no data.")
                except Exception as e:
                    logger.error(f"An error occurred while fetching prices from yfinance: {e}")
            else:
                print("- No tickers needed for price fetching.")


            # --- Step 5: Fetch Prices from yfinance ---
            print(f"\n--- [Step 5/7] Fetching Latest Prices from yfinance ---")
            tickers_needed = list(set(sim_portfolio.positions.keys()) | set(target_portfolio.get('longs', [])) | set(target_portfolio.get('shorts', [])))
            live_prices = {}
            if tickers_needed:
                print(f"Fetching prices for {len(tickers_needed)} unique tickers one by one for robustness...")
                for ticker in tickers_needed:
                    try:
                        # Fetch data for a single ticker. Requesting a short history is more reliable.
                        ticker_data = yf.Ticker(ticker)
                        hist = ticker_data.history(period="5d", auto_adjust=True) # auto_adjust=True gives adjusted prices
                        if not hist.empty:
                            # The last available closing price
                            last_price = hist['Close'].iloc[-1]
                            live_prices[ticker] = last_price
                        else:
                            logger.warning(f"yfinance returned no historical data for {ticker}.")
                    except Exception as e:
                        logger.error(f"An exception occurred while fetching price for {ticker} from yfinance: {e}")
                
                print(f"✅ Fetched {len(live_prices)} of {len(tickers_needed)} prices from yfinance.")
            else:
                print("- No tickers needed for price fetching.")

            # --- Step 6: Trade Calculation ---
            print(f"\n--- [Step 6/8] Portfolio Valuation ---")
            total_portfolio_value = sim_portfolio.get_total_value(live_prices)
            print(f"✅ Current Total Portfolio Value: ${total_portfolio_value:,.2f}")

            # --- Step 7: Simulate & Save Portfolio State ---
            print(f"\n--- [Step 7/8] Calculating Rebalance Orders ---")
            execution_manager = ExecutionManager(ibkr_handler=None, config=strategy_config)
            calculated_orders = await execution_manager.calculate_rebalance_orders(
                target_portfolio,
                sim_portfolio.positions,
                total_portfolio_value, # This variable is now correctly defined
                live_prices
            )
            all_orders = calculated_orders.get('all_orders', [])
            print(f"\n--- [PROCESS OUTPUT] Calculated Trades ---")
            if all_orders:
                for order in all_orders:
                    print(f"  - {order['action']:<7} | {order['ticker']:<6} | Qty: {order['quantity']}")
            else:
                print("  - No trades needed.")

            # --- Step 8/8: Simulate Trades & Save Portfolio State ---
            print(f"\n--- [Step 8/8] Simulating Trades & Saving Portfolio State ---")
            sim_portfolio.simulate_trades(all_orders, live_prices)
            sim_portfolio.save_portfolio()
            print(f"✅ New portfolio state saved to {portfolio_csv_path}")


if __name__ == "__main__":
    # Setup directories if they don't exist
    for dir_name in ['logs', 'data', 'output']:
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)

    logging_config.setup_logging(log_level='INFO')

    try:
        input("Press Enter to start the yfinance-based offline simulation workflow...")
        asyncio.run(run_yfinance_simulation())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Simulation run manually interrupted.")
    except Exception as e:
        logger.critical(f"An unhandled critical error occurred in the simulation: {e}", exc_info=True)