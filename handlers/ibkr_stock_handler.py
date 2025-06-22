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

    async def get_current_stock_price_async(self, ticker_symbol: str, timeout_sec: int = 20) -> Optional[float]:
        """
        Fetches the current market price for a stock using a market data snapshot.
        Prioritizes LAST price, then DELAYED_LAST, then CLOSE.
        """
        self._log_status("info", f"Attempting to fetch current stock price for {ticker_symbol} from IBKR.")
        if not self.is_connected():
            self._log_status("error", f"Not connected. Cannot fetch current price for {ticker_symbol}.")
            return None

        qualified_contract = await self.get_stock_contract_details(ticker_symbol)
        if not qualified_contract:
            # get_stock_contract_details already logs the failure reason.
            self._log_status("warning", f"Cannot fetch current price for {ticker_symbol} due to missing contract details.")
            return None

        # Standard tick list for price data. Refer to IBKR API docs for TickTypeEnum members.
        # TickTypeEnum.LAST (4), TickTypeEnum.DELAYED_LAST (68), TickTypeEnum.CLOSE (9)
        price_tick_list = "4,9,68" 

        try:
            # Using the specialized method from this class, which calls the base.
            snapshot_data_dict = await self.request_stock_market_data_snapshot_async(
                contract=qualified_contract,
                genericTickList=price_tick_list,
                regulatorySnapshot=False, # Typically False for non-NBBO snapshots
                timeout_sec=timeout_sec
            )

            if not snapshot_data_dict: 
                self._log_status("warning", f"No market data snapshot returned for {ticker_symbol}.")
                return None
            
            # Extract prices: snapshot_data_dict is Dict[str, Any] where keys are TickTypeEnum names
            # The value from the wrapper is already the direct price/size, not a nested dict.
            last_price = snapshot_data_dict.get(TickTypeEnum.idx2name[TickTypeEnum.LAST])
            delayed_last_price = snapshot_data_dict.get(TickTypeEnum.idx2name[TickTypeEnum.DELAYED_LAST])
            close_price = snapshot_data_dict.get(TickTypeEnum.idx2name[TickTypeEnum.CLOSE])
            
            # Filter out IBKR's sentinel value for unavailable prices (-1.0)
            if last_price == -1.0: last_price = None
            if delayed_last_price == -1.0: delayed_last_price = None
            if close_price == -1.0: close_price = None
            
            price_to_use = None
            price_source_log = "N/A"

            if last_price is not None:
                price_to_use = last_price
                price_source_log = "Last Price"
            elif delayed_last_price is not None:
                price_to_use = delayed_last_price
                price_source_log = "Delayed Last Price"
            elif close_price is not None:
                price_to_use = close_price
                price_source_log = "Close Price"
            
            if price_to_use is not None:
                # Ensure it's a float, as tick data can sometimes be other types if not handled in wrapper
                price_to_use = float(price_to_use)
                self._log_status("info", # Changed type from "data_point" to "info" for consistency
                                 f"Current stock price for {ticker_symbol} ({price_source_log}): {price_to_use:.2f}",
                                 ticker=ticker_symbol, price=price_to_use, source=price_source_log)
                return price_to_use
            else:
                self._log_status("warning", f"Could not determine a valid price for {ticker_symbol} from snapshot. Data: {snapshot_data_dict}")
                return None
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout fetching current stock price for {ticker_symbol}.")
            return None
        except IBKRApiError as e: 
            self._log_status("error", f"API error fetching current stock price for {ticker_symbol}: {e}")
            return None
        except Exception as e:
            self._log_status("error", f"Unexpected error fetching current stock price for {ticker_symbol}: {e}", exc_info=True)
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

# The __main__ block has been removed and will be placed in a separate test file:
# test_files/test_ibkr_stock_handler.py
