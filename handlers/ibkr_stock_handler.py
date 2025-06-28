# ibkr_stock_handler.py
import logging
import asyncio
import sys # Added for logger StreamHandler
from typing import List, Dict, Any, Optional, Callable

from ibapi.contract import Contract
from ibapi.common import BarData # Assuming BarData is used by base or for type hints
from ibapi.ticktype import TickTypeEnum # For parsing snapshot data

# Assuming these are in the same directory or project structure is handled by PYTHONPATH
from handlers.ibkr_base_handler import IBKRBaseHandler
from handlers.ibkr_api_wrapper import IBKRApiError # For specific error handling

# Logger for this module (e.g., "ibkr_stock_handler")
module_logger = logging.getLogger(__name__)
if not module_logger.hasHandlers():
    handler = logging.StreamHandler(sys.stdout) # Use sys.stdout
    formatter = logging.Formatter('%(asctime)s - %(name)s (IBKRStockHandler) - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    module_logger.addHandler(handler)
    module_logger.setLevel(logging.INFO) # Default level for this module's logger
    module_logger.propagate = False # Avoid duplicate logs if root logger is also configured

class IBKRStockHandler(IBKRBaseHandler):
    def __init__(self, status_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        super().__init__(status_callback=status_callback)
        self.module_name = self.__class__.__name__ # Use actual class name e.g. "IBKRStockHandler"
        # Initialize the _is_connected_flag from the base class if it's not already
        if not hasattr(self, '_is_connected_flag'):
            self._is_connected_flag: bool = False
        self._log_status("info", f"{self.module_name} instance created.") # Use base _log_status

    # _send_status is effectively replaced by using self._log_status from IBKRBaseHandler,
    # which already incorporates module name and status_callback logic.
    # If specific NaN handling for kwargs is needed before calling status_callback,
    # it would need to be in a method that prepares kwargs for _log_status or directly in _log_status.
    # For simplicity, we'll rely on IBKRBaseHandler._log_status and assume it handles kwargs appropriately
    # or that NaN values are not typically part of simple status updates.
    # If NaN needs special stringification for the callback, that logic should be centralized.

    def _create_stock_contract(self, ticker: str) -> Contract:
        """Helper to create a standard US stock contract."""
        contract = Contract()
        contract.symbol = ticker.upper()
        contract.secType = "STK"
        contract.currency = "USD"
        contract.exchange = "SMART"
        return contract

    async def get_stock_contract_details(self, ticker_symbol: str, exchange: str = "SMART", currency: str = "USD") -> Optional[Contract]:
        """
        Fetches complete contract details for a given stock ticker.
        """
        self._log_status("info", f"Fetching contract details for STK {ticker_symbol} on {exchange} ({currency}).")
        if not self.is_connected(): # is_connected() is from IBKRBaseHandler
            self._log_status("error", "Not connected to IBKR. Cannot fetch stock contract details.")
            return None

        contract = Contract()
        contract.symbol = ticker_symbol.upper()
        contract.secType = "STK"
        contract.exchange = exchange.upper()
        contract.currency = currency.upper()
        
        try:
            # request_contract_details_async is from IBKRBaseHandler
            contract_details_list = await super().request_contract_details_async(contract_input=contract)
            if contract_details_list: # It returns a list of ContractDetails objects
                # Assuming the first result is the primary one for a stock.
                qualified_contract = contract_details_list[0].contract 
                self._log_status("info", f"Successfully fetched contract details for {ticker_symbol}. ConId: {qualified_contract.conId}")
                return qualified_contract
            else:
                self._log_status("warning", f"No contract details found for STK {ticker_symbol}.")
                return None
        except IBKRApiError as e:
            self._log_status("error", f"API error fetching stock contract details for {ticker_symbol}: {e}")
            return None
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout fetching stock contract details for {ticker_symbol}.")
            return None
        except Exception as e:
            self._log_status("error", f"Unexpected error fetching stock contract details for {ticker_symbol}: {e}", exc_info=True)
            return None

    async def get_current_stock_price_async(self, ticker: str) -> Optional[float]:
        """
        Fetches the current market price for a single stock ticker.
        It resolves the contract first and checks for both live and delayed data ticks.
        """
        if not self.is_connected():
            self._log_status("error", "Not connected to IBKR.")
            return None

        base_contract = self._create_stock_contract(ticker)
        qualified_contract = await self.resolve_contract_details_async(base_contract)
        
        if not qualified_contract:
            self._log_status("warning", f"Could not resolve contract for {ticker}, cannot fetch price.")
            return None

        try:
            snapshot_data = await self.request_market_data_snapshot_async(qualified_contract)
            
            # --- MODIFIED: More robust price checking logic ---
            # The API wrapper stores tick data with string keys. We check for the most
            # relevant price, preferring live data over delayed, and last price over close price.
            # A price of -1.0 indicates data is not available.
            
            price_to_check = [
                snapshot_data.get("LAST"),
                snapshot_data.get("DELAYED_LAST"),
                snapshot_data.get("CLOSE"),
                snapshot_data.get("DELAYED_CLOSE")
            ]
            
            for price in price_to_check:
                if price is not None and price > 0:
                    self._log_status("info", f"Found valid price for {ticker}: {price}")
                    return price

            # If no valid price was found after checking all types
            self._log_status("warning", f"Snapshot for {ticker} did not contain a valid price. Data: {snapshot_data}")
            return None
            
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout fetching market data snapshot for {ticker}.")
            return None
        except IBKRApiError as e:
            self._log_status("error", f"API error fetching price for {ticker}: {e}")
            return None

    async def request_stock_historical_data_async(self, contract: Contract, endDateTime: str = "", durationStr: str = "1 D", barSizeSetting: str = "1 day", whatToShow: str = "TRADES", useRTH: bool = True, formatDate: int = 1, keepUpToDate: bool = False, chartOptions: Optional[List[Any]] = None, timeout_sec: int = 60) -> List[BarData]:
        """
        Requests historical bar data specifically for a stock contract.
        """
        if not self.is_connected():
            self._log_status("error", "Not connected to IBKR for historical stock data request.")
            raise ConnectionError("Not connected to IBKR.") 
        if contract.secType != "STK":
            self._log_status("error", f"Invalid contract type '{contract.secType}'. Expected STK for this method.")
            raise ValueError("This method is designed for STK (stock) contracts.")
        
        # Call the base class method
        return await super().request_historical_data_async(
            contract, endDateTime, durationStr, barSizeSetting, 
            whatToShow, useRTH, formatDate, keepUpToDate, 
            chartOptions if chartOptions else [], timeout_sec
        )

    async def request_stock_market_data_snapshot_async(self, contract: Contract, genericTickList: str = "100,101,104,105,106,107,165,221,225,233,236,258,456", regulatorySnapshot: bool = False, timeout_sec: int = 20) -> Dict[str, Any]:
        """
        Requests a market data snapshot specifically for a stock contract.
        """
        if not self.is_connected():
            self._log_status("error", "Not connected to IBKR for stock market data snapshot request.")
            raise ConnectionError("Not connected to IBKR.")
        if contract.secType != "STK":
            self._log_status("error", f"Invalid contract type '{contract.secType}'. Expected STK for this method.")
            raise ValueError("This method is designed for STK (stock) contracts.")

        # Call the base class method
        # The wrapper's tickSnapshotEnd resolves the future with request_data_store[reqId], which is a dict.
        return await super().request_market_data_snapshot_async(
            contract, genericTickList, regulatorySnapshot, timeout_sec
        )

    async def get_current_stock_prices_for_tickers(self, tickers: List[str]) -> Dict[str, float]:
        """
        Fetches the current market price for a list of stock tickers concurrently.

        Args:
            tickers (List[str]): A list of stock ticker symbols.

        Returns:
            Dict[str, float]: A dictionary mapping tickers to their current price.
                              Tickers for which a price could not be fetched will be omitted.
        """
        if not self.is_connected():
            self._log_status("error", "Not connected to IBKR for batch price request.")
            raise ConnectionError("Not connected to IBKR.")

        # Create a list of async tasks to run concurrently
        tasks = [self.get_current_stock_price_async(ticker) for ticker in tickers]
        
        # Run all tasks and gather the results
        # return_exceptions=True ensures that one failed request doesn't stop all others.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        live_prices: Dict[str, float] = {}
        for ticker, price_result in zip(tickers, results):
            if isinstance(price_result, Exception):
                self._log_status("error", f"An exception occurred while fetching price for {ticker}: {price_result}")
            elif price_result is not None:
                live_prices[ticker] = price_result
            else:
                self._log_status("warning", f"Could not retrieve price for {ticker}. It will be omitted from results.")

        return live_prices