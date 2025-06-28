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


