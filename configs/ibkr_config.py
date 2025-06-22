# config/ibkr_config.py
import logging
import sys

# Logger for config file sanity checks (if any)
# This logger remains in case other modules might want to perform
# sanity checks on the loaded config, or if you plan to add
# more sophisticated validation directly within this file later.
logger = logging.getLogger(__name__)
if not logger.hasHandlers():  # Avoid duplicate handlers
    ch = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s (IBKR_Config) - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.setLevel(logging.INFO) # Default level, can be overridden by global LOG_LEVEL

# --- IBKR Connection Parameters ---
HOST = '127.0.0.1'
PORT = 7497  # 7497 for TWS Paper Trading, 7496 for TWS Live, 4002 for Gateway Paper, 4001 for Gateway Live
# Ensure the port matches your TWS/Gateway API settings

# Client IDs for main application components (e.g., GUI)
# Ensure these are unique for each concurrent connection to IBKR.
CLIENT_ID_GUI_STOCK = 101
CLIENT_ID_GUI_OPTION = 102
CLIENT_ID_GUI_GENERAL = 103  # If GUI needs another general purpose connection

# --- IV Crush Calculation Defaults ---
DEFAULT_IV_CRUSH_FACTOR_IF_NO_HISTORY = 0.75  # e.g., IV retains 75% of value (25% drop)
RISK_FREE_RATE = 0.045  # Example risk-free rate (e.g., 4.5%)
HISTORICAL_IV_DTE_TARGET = 35  # Target days to expiration for options used in historical IV calculation

# --- Strike Selection Parameters for Historical IV Calculation ---
STRIKE_INCREMENT_GUESS = 1.0  # General guess if ticker-specific is not found
STRIKE_INCREMENT_AAPL = 5.0
STRIKE_INCREMENT_MSFT = 5.0
STRIKE_INCREMENT_SPY = 1.0
STRIKE_INCREMENT_QQQ = 1.0
STRIKE_INCREMENT_IWM = 1.0
# Add more ticker-specific strike increments as needed

# Number of *additional* standard strikes around ATM for historical IV analysis.
NUM_STRIKES_AROUND_ATM_HISTORICAL_IV = 1

# --- Optimal Calendar Spread Finder Parameters ---
# MAX_BACK_WEEKS_DIFFERENCE = 5  # Max weeks between front and back month expirations, TO BE REMOVED
MIN_PROFIT_DEBIT_RATIO = 0.5   # Minimum acceptable overall Profit/Debit ratio
NUM_OTM_STRIKES_TO_CONSIDER = 2 # Number of OTM strikes (each side, C & P) for calendar components
# General strike increment for selecting OTM strikes for the optimal spread finder,
# if a ticker-specific one isn't used or if the GUI doesn't provide one.
# STRIKE_INCREMENT_FOR_OTM_CALENDARS = 1.00  # DELETE from code no longer in use

# Crucial assumption: Estimated IV for the back leg of a calendar spread
# at the time the front leg expires, after the earnings event.
# This is a critical estimate of the back-leg option's Implied Volatility
# after the front-leg expires and the earnings event has passed,
# significantly impacting calendar spread P&L projections.
ASSUMED_IV_BACK_LEG_AT_FRONT_EXPIRY = 0.25  # Example: 25% IV. This may need tuning.

# --- Scoring Weights & Penalties for Optimal Spread Finder ---
WEIGHT_SIGMA_COVERAGE_LOWER = 50
WEIGHT_SIGMA_COVERAGE_UPPER = 50
WEIGHT_PROFIT_DEBIT_RATIO_OVERALL = 20  # Multiplier for (Max Profit / Total Debit)
WEIGHT_PROFIT_DEBIT_RATIO_ATM = 10     # Multiplier for (P&L at ATM Pin / Total Debit)
PENALTY_FOR_UNCOVERED_SIGMA_SIDE = -100
PENALTY_LOW_PROFITABILITY = -50        # Penalty if Profit/Debit Ratio < MIN_PROFIT_DEBIT_RATIO

# --- API Call Delays & Timeouts ---
IBKR_API_DELAY_SECONDS = 0.05   # Small delay between certain IBKR calls if needed
IBKR_CONNECTION_TIMEOUT_SECONDS = 15 # Timeout for initial connection confirmation
IBKR_REQUEST_TIMEOUT_SECONDS = 45    # Timeout for individual data requests

# --- Logging Configuration ---
LOG_LEVEL = 'INFO'  # Recommended: DEBUG, INFO, WARNING, ERROR, CRITICAL

# Note: The if __name__ == '__main__': block for printing configs
# and test-specific client IDs have been moved to test_files/test_config_verification.py
