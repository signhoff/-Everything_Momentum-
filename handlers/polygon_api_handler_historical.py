# polygon_api_handler_historical.py
import requests
import logging
import datetime # Retained as it's used by type hints, though not directly in code logic now
from typing import Optional, Callable, Dict, Any, TYPE_CHECKING

# --- Configuration and Utility Imports ---
# Attempt to import the API key from the configuration file.
# This allows the handler to be used without explicitly passing the key if configured globally.
POLYGON_API_KEY_FROM_CONFIG = None
try:
    from configs.polygon_config import POLYGON_API_KEY as POLYGON_API_KEY_FROM_CONFIG
except ImportError:
    # Log a warning if the config file or key is not found.
    # The API key can still be provided during class instantiation.
    logging.warning("config.polygon_config.py not found or POLYGON_API_KEY not in it. "
                    "API key must be provided at PolygonAPIHandlerHistorical instantiation if not set globally.")

# The POLYGON_UTILS_FORMAT_FUNCTION import is removed from here as it was only used in the __main__ block.
# If any method in this class were to use it, it would be imported here.

# Configure logger for this module
# This setup ensures that the module has its own logger.
# Basic configuration is applied if no handlers are already set for this logger.
logger = logging.getLogger(__name__)
if not logger.handlers:
    # BasicConfig is generally for the root logger, but for a library module,
    # it's often better to let the application configure logging.
    # However, to ensure some output if used standalone or in simple scripts:
    # logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # For now, we'll assume the application consuming this module will configure logging.
    # If direct output is needed when no app-level config is present, add a NullHandler
    # or a basic StreamHandler for this specific logger.
    # Example: logger.addHandler(logging.NullHandler())
    # For development/debugging, a StreamHandler can be useful:
    import sys
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        handler_stream = logging.StreamHandler(sys.stdout)
        formatter_stream = logging.Formatter('%(asctime)s - %(name)s (PolygonAPIHandler) - %(levelname)s - %(message)s')
        handler_stream.setFormatter(formatter_stream)
        logger.addHandler(handler_stream)
    logger.setLevel(logging.INFO) # Default level for this logger


class PolygonAPIHandlerHistorical:
    """
    Handles historical data fetching from Polygon.io using direct HTTP requests.
    This class uses the 'requests' library. For more complex interactions,
    Polygon.io's official 'polygon-python-client' library might be considered.
    """
    def __init__(self, api_key: Optional[str] = None, status_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        """
        Initializes the PolygonAPIHandlerHistorical.

        Args:
            api_key (Optional[str]): The Polygon.io API key. If None, attempts to use
                                     POLYGON_API_KEY_FROM_CONFIG.
            status_callback (Optional[Callable[[Dict[str, Any]], None]]): A callback function
                that accepts a dictionary payload for status updates.
                The dictionary will have keys like "type", "module", "message".
        """
        self.status_callback = status_callback
        self._log_status_message("Initializing PolygonAPIHandlerHistorical...")

        if api_key:
            self.api_key = api_key
            self._log_status_message("Using provided API key for Polygon.")
        elif POLYGON_API_KEY_FROM_CONFIG:
            self.api_key = POLYGON_API_KEY_FROM_CONFIG
            self._log_status_message("Using API key from config.polygon_config for Polygon.")
        else:
            self.api_key = None # Explicitly set to None
            logger.error("POLYGON API KEY NOT PROVIDED OR FOUND IN CONFIG. Operations will fail.")
            self._log_status_message("ERROR: Polygon API key not configured. Operations will fail.", level="ERROR")

        # Check for common placeholder API keys
        if self.api_key and (self.api_key.startswith("YOUR_") or self.api_key == "bpgAS4iOMalkGnGmvpMpOC9eWBY5Raep_placeholder"): # Example placeholder
            logger.error("Polygon API Key appears to be a placeholder. Please configure a valid API key.")
            self._log_status_message("ERROR: Polygon API Key is a placeholder. Further operations may fail.", level="ERROR")
            # Depending on strictness, you might want to set self.api_key = None here

        self.base_url = "https://api.polygon.io"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "CalendarSpreadApp/1.0"}) # More specific User-Agent
        
        self._client_initialized_successfully = False # Tracks if initialize_client has run successfully

        self._log_status_message(f"PolygonAPIHandlerHistorical instance created. API key configured: {bool(self.api_key)}")

    def _log_status_message(self, message_text: str, level: str = "INFO", exc_info: bool = False, module_name: str = "PolygonHandler"):
        """
        Helper method to log messages and send structured status updates via the callback.

        Args:
            message_text (str): The message to log.
            level (str): The logging level (e.g., "INFO", "ERROR", "WARNING").
            exc_info (bool): If True, exception information is added to the logging message.
            module_name (str): The name of the module reporting the status.
        """
        log_level_upper = level.upper()
        if log_level_upper == "ERROR": logger.error(message_text, exc_info=exc_info)
        elif log_level_upper == "WARNING": logger.warning(message_text, exc_info=exc_info)
        else: logger.info(message_text, exc_info=exc_info)

        if self.status_callback:
            try:
                payload = {
                    "type": level.lower(),
                    "module": module_name,
                    "message": message_text
                }
                self.status_callback(payload)
            except Exception as e_cb:
                # Log error during callback execution but don't let it break the handler
                logger.error(f"Error occurred in Polygon status_callback: {e_cb}", exc_info=True)

    def initialize_client(self) -> bool:
        """
        Explicitly initializes and tests the connection to Polygon.io.
        This method should be called and return True before attempting to fetch data.

        Returns:
            bool: True if initialization and connection test are successful, False otherwise.
        """
        if self._client_initialized_successfully:
            self._log_status_message("Polygon client is already initialized successfully.")
            return True

        if not self.api_key:
            self._log_status_message("Cannot initialize Polygon client: API key is not set.", level="ERROR")
            self._client_initialized_successfully = False
            return False

        self._log_status_message("Attempting to initialize and test Polygon client connection...")
        if self.test_connection():
            self._log_status_message("Polygon client initialization and connection test successful.")
            self._client_initialized_successfully = True
            return True
        else:
            # test_connection() logs specific errors.
            self._log_status_message("Polygon client initialization failed (connection test was unsuccessful). Check logs for details.", level="ERROR")
            self._client_initialized_successfully = False
            return False

    def is_connected(self) -> bool:
        """
        Checks if the client has been successfully initialized via initialize_client().

        Returns:
            bool: True if the client is initialized and connected, False otherwise.
        """
        return self._client_initialized_successfully

    def test_connection(self) -> bool:
        """
        Tests the API connection to Polygon.io using the configured API key.
        This involves making a simple, non-data-intensive API call.

        Returns:
            bool: True if the connection is successful, False otherwise.
        """
        if not self.api_key:
            self._log_status_message("Cannot test Polygon connection: API key is not set.", level="WARNING")
            return False
        
        # Using a lightweight endpoint for connection testing, e.g., market status or a single ticker.
        test_url = f"{self.base_url}/v3/reference/tickers/AAPL" # A common, stable ticker
        params = {'apiKey': self.api_key}
        self._log_status_message(f"Testing Polygon connection with URL: {test_url}")

        try:
            response = self.session.get(test_url, params=params, timeout=10) # 10-second timeout
            response.raise_for_status()  # Raises HTTPError for bad responses (4XX or 5XX)
            # If we reach here, the request was successful.
            # Success message is logged by initialize_client if called from there.
            return True
        except requests.exceptions.HTTPError as http_err:
            err_msg = f"Polygon API connection test failed (HTTPError): {http_err}. "
            if http_err.response is not None:
                err_msg += f"Status: {http_err.response.status_code}. Response: {http_err.response.text[:200]}"
            else:
                err_msg += "No response object."
            self._log_status_message(err_msg, level="ERROR")
        except requests.exceptions.Timeout:
            self._log_status_message("Polygon API connection test failed: Request timed out.", level="ERROR")
        except requests.exceptions.ConnectionError:
            self._log_status_message("Polygon API connection test failed: Connection error (e.g., DNS failure, refused connection).", level="ERROR")
        except requests.exceptions.RequestException as req_err:
            self._log_status_message(f"Polygon API connection test failed (RequestException): {req_err}", level="ERROR")
        except Exception as e:
            self._log_status_message(f"An unexpected error occurred during Polygon connection test: {e}", level="ERROR", exc_info=True)
        return False

    def get_historical_option_price(self, option_symbol: str, evaluation_date_str: str) -> Optional[Dict[str, Any]]:
        """
        Fetches historical open/close price for a specific option contract on a given date.

        Args:
            option_symbol (str): The Polygon.io formatted option symbol (e.g., "O:AAPL241220C00150000").
            evaluation_date_str (str): The date for which to fetch the price, in "YYYY-MM-DD" format.

        Returns:
            Optional[Dict[str, Any]]: A dictionary containing the option's open/close data
                                      if found, otherwise None.
        """
        if not self.is_connected():
            self._log_status_message("Cannot fetch option price: Polygon client not successfully initialized.", level="ERROR")
            return None

        if not option_symbol.startswith("O:"):
            # Polygon option symbols typically start with "O:".
            logger.warning(f"Option symbol '{option_symbol}' does not start with 'O:'. Ensure it's correctly formatted for Polygon options API.")
            # Optionally, send a status message if this is a common user error.
            # self._log_status_message(f"Warning: Option symbol '{option_symbol}' may be incorrectly formatted.", level="WARNING")


        # API endpoint for daily open/close for an option contract.
        url = f"{self.base_url}/v1/open-close/{option_symbol}/{evaluation_date_str}"
        params = {'apiKey': self.api_key, 'adjusted': 'true'} # 'adjusted' handles splits/dividends.
        self._log_status_message(f"Fetching Polygon option data: {url} for date: {evaluation_date_str}")

        try:
            response = self.session.get(url, params=params, timeout=15) # 15-second timeout for data requests
            response.raise_for_status() # Check for HTTP errors
            data = response.json()

            # Polygon specific checks for no data or errors
            if data.get("status") == "NOT_FOUND" or data.get("resultsCount") == 0 or data.get("status") == "ERROR":
                message = (f"No data found by Polygon for option {option_symbol} on {evaluation_date_str}. "
                           f"Status: {data.get('status', 'N/A')}. Message: {data.get('message', 'N/A')}")
                self._log_status_message(message, level="WARNING")
                return None
            
            # Validate returned symbol (case-insensitive comparison)
            if data.get("symbol", "").upper() != option_symbol.upper():
                self._log_status_message(f"Polygon symbol mismatch for {option_symbol} on {evaluation_date_str}. "
                                       f"Expected: {option_symbol}, Got: {data.get('symbol', 'N/A')}", level="WARNING")
                # This might not be a fatal error, but it's worth noting.

            # Ensure essential price fields are present
            if 'close' not in data and 'open' not in data: # At least one should ideally be present
                self._log_status_message(f"Essential price fields ('open' or 'close') missing in Polygon response "
                                       f"for {option_symbol} on {evaluation_date_str}. Data: {str(data)[:200]}", level="WARNING")
                return None # Or handle as partial data if appropriate

            self._log_status_message(f"Successfully fetched Polygon option data for {option_symbol} on {evaluation_date_str}: "
                                   f"Open={data.get('open', 'N/A')}, Close={data.get('close', 'N/A')}, Volume={data.get('volume', 'N/A')}")
            return data

        except requests.exceptions.HTTPError as http_err:
            err_msg = f"HTTP error fetching data for {option_symbol} on {evaluation_date_str}: {http_err}. "
            if http_err.response is not None:
                err_msg += f"Status: {http_err.response.status_code}. Response: {http_err.response.text[:200]}"
                if http_err.response.status_code == 404: # Specifically handle 404 as "no data"
                   self._log_status_message(f"No data found (404) from Polygon for option {option_symbol} on {evaluation_date_str}.", level="WARNING")
                   return None
            else:
                err_msg += "No response object."
            self._log_status_message(err_msg, level="ERROR")
            return None
        except requests.exceptions.Timeout:
            self._log_status_message(f"Request timed out fetching data for {option_symbol} on {evaluation_date_str}.", level="ERROR")
            return None
        except requests.exceptions.ConnectionError:
            self._log_status_message(f"Connection error fetching data for {option_symbol} on {evaluation_date_str}.", level="ERROR")
            return None
        except requests.exceptions.RequestException as req_err: # Catch other requests-related errors
            self._log_status_message(f"Request exception fetching data for {option_symbol} on {evaluation_date_str}: {req_err}", level="ERROR")
            return None
        except ValueError as json_err:  # Handles JSONDecodeError
            response_text_snippet = response.text[:200] if 'response' in locals() and hasattr(response, 'text') else 'No response text available'
            self._log_status_message(f"JSON decoding error for {option_symbol} on {evaluation_date_str}: {json_err}. "
                                   f"Response text snippet: {response_text_snippet}", level="ERROR")
            return None
        except Exception as e: # Catch-all for any other unexpected errors
            self._log_status_message(f"Unexpected error fetching Polygon data for {option_symbol} on {evaluation_date_str}: {e}",
                                   level="ERROR", exc_info=True)
            return None

# The __main__ block has been removed and will be placed in a separate test file.
