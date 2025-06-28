# README.txt

## Quantitative Momentum Trading System: 
This project provides a complete Python application for implementing and simulating quantitative momentum stock selection 
strategies. The methodologies are based on the principles described in the book "Quantitative Momentum."

---

## Primary Objective is to build a system that can:
1.  Filter a large universe of stocks based on liquidity, sector, and volatility.
2.  Rank the remaining stocks using a proven momentum factor (12-2 momentum).
3.  Construct a target portfolio of the top-performing stocks to go long on and the bottom-performing stocks to go short on.
4.  Simulate the rebalancing process in a self-contained environment, using live market data for calculations but without 
executing any real trades.
5.  Maintain a persistent state of the simulated portfolio between runs.
6.  Generate detailed reports for analysis and validation.

---

## Core Strategy: 12-2 Momentum
The foundation of this program is the **12-2 Momentum** factor. This number represents a stock's total price return over 
a 10-month period that is lagged by two months.
For example, if a rebalance is performed in June, the momentum score is the stock's performance from the end of June of 
the previous year (t-12) to the end of April of the current year (t-2).
* **Why a 12-month lookback?** It captures a stable, intermediate-term trend.
* **Why a 2-month lag?** It avoids the "short-term reversal" effect, where recent top performers often dip temporarily.

Based on the principles of quantitative momentum investing, this type of strategy is designed to capture intermediate-term 
trends, so it should be run on a monthly or quarterly basis. Rebalancing more frequently (like weekly) often leads to 
excessive transaction costs and can be influenced by short-term market noise rather than the underlying momentum factor. 
Rebalancing less frequently (like annually) can fail to adapt to changing market trends.

### Implemented Strategies
The system can run and analyze three distinct variations of the momentum strategy:
1.  **CORE Momentum**: The baseline strategy. It filters for liquidity and sector, then ranks all eligible stocks by their 
12-2 momentum. It targets the top 10% for long positions and the bottom 10% for short positions.
2.  **SMOOTH Momentum**: A "quality-focused" version of CORE. Before ranking, it adds a filter to only include stocks that 
have had at least 7 positive-return months out of the last 12.
3.  **FROG_IN_PAN (Low Volatility Momentum)**: A risk-averse approach. It *first* removes the 20% most volatile stocks from 
the universe and *then* applies the CORE momentum logic to the remaining, more stable stocks.

---

## Basic Functionality
The program is orchestrated by the main test script, `tests/test_trader_workflow.py`, which performs a complete simulation 
cycle.
* **Batch Processing**: In a single run, the script simulates all three strategies (`CORE`, `SMOOTH`, and `FROG_IN_PAN`) 
sequentially.
* **Data Caching**: To minimize API calls and speed up execution, the system caches data on a daily basis:
    * **Historical Price Data**: Downloaded from `yfinance` and stored in `data/historical_data.parquet`.
    * **Company Info (Market Cap)**: Fetched from `yfinance` and stored in `data/company_info.json`.
    * *Note: The cache is refreshed only once per day. Subsequent runs on the same day are nearly instantaneous.*
* **Live Price Fetching**: The system connects to a running instance of Interactive Brokers Trader Workstation (TWS) or 
Gateway to fetch real-time prices. This is used for accurate portfolio valuation and share quantity calculations. **No
 trades are ever executed.**
* **Portfolio Simulation**: The state of each strategy's portfolio (cash and positions) is managed locally in separate 
CSV files (e.g., `data/CORE_portfolio_state.csv`). This allows the simulation to be entirely separate from your actual 
brokerage account.
* **Reporting**: For each strategy run, a detailed, timestamped CSV report is generated in the `output` folder, showing 
every stock considered and the metrics used for ranking and selection.

---

*** IMPORTANT VARIABLE CHANGES ***
*Portfolio Size*: can be adjusted by changing a single variable in the strategy configuration file.

    File: configs/strategy_config.py
    Variable: TOP_PERCENTILE_CUTOFF

This vairable controls the percentage of stocks selected for both the long portfolio (the top %) and the 
short portfolio (the bottom %).

To make the adjustments you would set the variable as follows:

    For 5%: TOP_PERCENTILE_CUTOFF: float = 0.05
    For 2.5%: TOP_PERCENTILE_CUTOFF: float = 0.025
    For 1%: TOP_PERCENTILE_CUTOFF: float = 0.01

*Starting Portfolio Value*: can be adjusted in the main simulation script: `tests/test_trader_workflow.py`.

The value is set inside the main `for` loop where the `SimulatedPortfolioManager` is initialized for each strategy.

* **File:** `tests/test_trader_workflow.py`
    ```python
    sim_portfolio = SimulatedPortfolioManager(csv_path=portfolio_csv_path, initial_cash=2500.0)
    ```

To change the starting value, simply modify the `initial_cash` number in that line. For example, to start with $100,000, 
you would change it to:

```python
sim_portfolio = SimulatedPortfolioManager(csv_path=portfolio_csv_path, initial_cash=100000.0)
```

This `initial_cash` value is only used the very first time you run a simulation for a specific strategy, 
when its corresponding `_portfolio_state.csv` file does not yet exist. After the first run, the script will load the last known 
cash and positions from that CSV file.

*Rebalancing*: Your program is already built to handle this, with quarterly rebalancing set as the default, which is a very common and robust 
choice for this strategy.

You can control this frequency directly in the configuration file:

    File: configs/strategy_config.py
    Variable: REBALANCE_PERIOD

You can set this variable to either 'QUARTERLY' or 'MONTHLY'. The main simulation script reads this setting and will only perform 
its rebalancing logic on the appropriate days (e.g., the first trading day of January, April, July, and October for quarterly rebalancing).

---

## How to Use
### 1. Setup and Installation
1.  **Create a Virtual Environment**:
    ```bash
    python -m venv venv
    ```
2.  **Activate It**:
    * Windows: `.\venv\Scripts\activate`
    * macOS/Linux: `source venv/bin/activate`
3.  **Install Dependencies**: Ensure your `requirements.txt` file is up-to-date and run:
    ```bash
    pip install -r requirements.txt
    ```
### 2. Configuration
1.  **`configs/ibkr_config.py`**: Set your TWS/Gateway connection port (e.g., `7497` for paper trading).
2.  **`data/sp500_tickers.csv`**: Populate this file with the universe of stocks you want to analyze. It must contain 
`Ticker` and `Sector` columns.
### 3. Running the Simulation
1.  **Start Interactive Brokers TWS/Gateway**: Log in to your paper trading account and ensure API connections are 
enabled.
2.  **Execute the Test Script**: Open a terminal in the project root, activate your virtual environment, and run:
    ```bash
    python tests/test_trader_workflow.py
    ```
3.  The script will guide you through the process, running simulations for all three strategies and saving all relevant 
output files.