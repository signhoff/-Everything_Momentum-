# handlers/ibkr_base_handler.py

import threading
import time
import logging
import asyncio
from typing import List, Dict, Any, Optional, Union, Callable 

import sys 

from ibapi.client import EClient
from ibapi.contract import Contract, ContractDetails
from ibapi.common import BarData
from ibapi.order import Order

from handlers.ibkr_api_wrapper import IBKROfficialAPIWrapper, IBKRApiError

# Logger for this module
logger = logging.getLogger(__name__) 
if not logger.hasHandlers():
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s (IBKRBaseHandler) - %(levelname)s - %(message)s') 
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

class IBKRBaseHandler:
    def __init__(self, status_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.status_callback = status_callback 
        self.wrapper = IBKROfficialAPIWrapper(status_callback=self.status_callback, base_handler_ref=self) 
        self.client = EClient(self.wrapper)
        self._req_id_counter: int = 0 
        self.api_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock() 
        self.loop: Optional[asyncio.AbstractEventLoop] = None 
        self._is_connected_flag: bool = False

        try:
            # Adjusted to import from the root-level app_config
            import app_config
            log_level_str = getattr(app_config, 'LOG_LEVEL_STR', 'INFO').upper()
            logger.setLevel(getattr(logging, log_level_str, logging.INFO))
        except (ImportError, AttributeError):
            logger.info("LOG_LEVEL not found in app_config, using default INFO for IBKRBaseHandler logger.")
            pass 

        self._log_status("info", f"{self.__class__.__name__} instance created.")

    def _log_status(self, msg_type: str, message: str, **kwargs):
        """
        Helper to log messages and send structured status updates via callback.
        """
        log_level_map = {
            "error": logging.ERROR, "warning": logging.WARNING,
            "info": logging.INFO, "debug": logging.DEBUG
        }
        actual_class_name = self.__class__.__name__
        effective_logger = logger
        effective_logger.log(log_level_map.get(msg_type.lower(), logging.INFO), f"[{actual_class_name}] {message}")

        if self.status_callback:
            payload = {"module": actual_class_name, "type": msg_type.lower(), "message": message}
            payload.update(kwargs)
            try:
                self.status_callback(payload)
            except Exception as e_cb:
                effective_logger.error(f"Error in status_callback from {actual_class_name}: {e_cb}", exc_info=True)

    def _initialize_req_id_counter(self):
        if self.wrapper.next_valid_order_id is not None and self.wrapper.next_valid_order_id > 0:
            with self._lock: 
                self._req_id_counter = self.wrapper.next_valid_order_id
            self._log_status("info", f"Request ID counter initialized from nextValidId. Starting at: {self._req_id_counter}")
        else:
            with self._lock:
                self._req_id_counter = int(time.time() * 1000) % 1000000 
            self._log_status("warning", f"NextValidId not available or invalid ({self.wrapper.next_valid_order_id}). Using time-based fallback for reqId counter starting at {self._req_id_counter}.")


    def get_next_req_id(self) -> int:
        with self._lock:
            if self._req_id_counter == 0:
                self._req_id_counter = int(time.time() * 1000) % 1000000
                self._log_status("warning", f"ReqID counter was 0, using time-based fallback: {self._req_id_counter}.")
            self._req_id_counter += 1
            return self._req_id_counter

    def _client_thread_target(self):
        self._log_status("info", "IBKR API client thread starting execution.")
        try:
            self.client.run()
        except Exception as e:
            self._log_status("error", f"Exception in IBKR API client thread: {e}", exc_info=True)
        finally:
            self._log_status("info", "IBKR API client thread finished.")
            if self.client.isConnected(): 
                self._log_status("warning", "Client thread finished, but client still reports as connected. Signaling EWrapper.")
                if hasattr(self.wrapper, 'connectionClosed'): 
                    self.wrapper.connectionClosed()
            self._is_connected_flag = False # Ensure flag is reset when thread exits
        self._log_status("info", "IBKR API client thread starting execution.")


    async def connect(self, host: str, port: int, clientId: int,
                      loop: Optional[asyncio.AbstractEventLoop] = None, 
                      timeout_sec: int = 10) -> bool:
        
        self._log_status("info", f"Attempting to connect to IBKR at {host}:{port} with ClientID {clientId}")
        
        self.loop = loop or asyncio.get_running_loop()
        if not self.loop: 
            self._log_status("error", "No asyncio event loop available for IBKR connection.")
            return False
        
        self.wrapper.set_event_loop(self.loop) 

        if self.client.isConnected() and self._is_connected_flag:
            self._log_status("info", "Already connected to IBKR.")
            if self._req_id_counter == 0 and self.wrapper.next_valid_order_id > 0:
                self._initialize_req_id_counter()
            return True

        self.wrapper.reset_connection_state() 
        self._is_connected_flag = False

        try:
            self.client.connect(host, port, clientId)
        except Exception as e:
            self._log_status("error", f"Exception during EClient.connect call: {e}", exc_info=True)
            self.wrapper.connection_error_code = -1 
            self.wrapper.connection_error_message = str(e)
            return False 

        if not self.api_thread or not self.api_thread.is_alive():
            self.api_thread = threading.Thread(target=self._client_thread_target, daemon=True, name=f"IBClientThread_CID{clientId}")
            self.api_thread.start()
        else:
            self._log_status("info", "IBKR API thread already running.")

        self._log_status("info", f"Waiting for connection confirmation (timeout: {timeout_sec}s)...")
        try:
            await asyncio.wait_for(
                self.loop.run_in_executor(None, self.wrapper.connection_event.wait, timeout_sec), 
                timeout=timeout_sec + 1 
            )
        except asyncio.TimeoutError:
            self._log_status("error", f"IBKR connection attempt timed out after {timeout_sec}s for ClientID {clientId}.")
            self._shutdown_client_and_thread()
            return False
        except Exception as e_wait: 
            self._log_status("error", f"Error waiting for IBKR connection event for ClientID {clientId}: {e_wait}", exc_info=True)
            self._shutdown_client_and_thread()
            return False


        if self.wrapper.connection_error_code is not None:
            self._log_status("error", f"IBKR connection failed. Code: {self.wrapper.connection_error_code}, Msg: {self.wrapper.connection_error_message}")
            self._shutdown_client_and_thread()
            return False
        elif self.wrapper.next_valid_order_id > 0 and self.wrapper.initial_connection_made:
            self._log_status("info", f"Successfully connected to IBKR (ClientID: {clientId}) and received NextValidId: {self.wrapper.next_valid_order_id}.")
            self._initialize_req_id_counter() 
            self._log_status("info", "Requesting delayed market data (type 3).")
            self.client.reqMarketDataType(3) 
            self._is_connected_flag = True 
            return True
        else:
            self._log_status("warning", f"IBKR connection event for ClientID {clientId} occurred, but state is not fully confirmed (NextValidId: {self.wrapper.next_valid_order_id}, InitialConnection: {self.wrapper.initial_connection_made}). Connection failed.")
            self._shutdown_client_and_thread()
            return False
        
    def _shutdown_client_and_thread(self):
        """Helper to disconnect client and set connected flag to False."""
        if self.client.isConnected():
            self._log_status("info", "Disconnecting client due to connection issue or shutdown.")
            self.client.disconnect() 
        self._is_connected_flag = False

    async def disconnect(self):
        if self.client.isConnected():
            self._log_status("info", "Disconnecting from IBKR...")
            self.client.disconnect() 
        else:
            self._log_status("info", "Already disconnected or was never connected to IBKR.")

        if self.api_thread and self.api_thread.is_alive():
            self._log_status("info", "Waiting for IBKR API thread to terminate (max 5s)...")
            try:
                if self.loop and self.loop.is_running():
                    await self.loop.run_in_executor(None, self.api_thread.join, 5.0)
                else: 
                    self.api_thread.join(5.0)
            except Exception as e:
                self._log_status("error", f"Error joining IBKR API thread: {e}")
            
            if self.api_thread and self.api_thread.is_alive(): 
                self._log_status("warning", "IBKR API thread did not terminate cleanly after disconnect signal.")
        
        self.api_thread = None 
        self._is_connected_flag = False 
        if hasattr(self.wrapper, 'initial_connection_made'): 
            self.wrapper.initial_connection_made = False
        self._log_status("info", "IBKR disconnection process complete.")

    def is_connected(self) -> bool:
        return self.client.isConnected() and self._is_connected_flag


        
    # --- NEW METHOD ADDED HERE ---
    # Add this method inside the IBKRBaseHandler class
    async def get_account_summary_async(self, tags: str = "NetLiquidation", timeout_sec: int = 15) -> Dict[str, Any]:
        """Requests account summary data from IBKR."""
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR.")

        req_id = self.get_next_req_id()
        future = self.loop.create_future()
        self.wrapper.futures[req_id] = future
        self.wrapper.request_data_store[req_id] = {}

        self.client.reqAccountSummary(req_id, "All", tags)

        try:
            summary_data = await asyncio.wait_for(future, timeout=timeout_sec)
            return summary_data
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout requesting account summary (ReqId: {req_id}).")
            raise
        finally:
            self.client.cancelAccountSummary(req_id)

    async def get_portfolio_positions_async(self, timeout_sec: int = 15) -> Dict[str, Dict[str, Any]]:
        """
        Fetches all current portfolio positions from IBKR.

        Args:
            timeout_sec (int): Timeout in seconds for the request.

        Returns:
            Dict[str, Dict[str, Any]]: A dictionary where keys are stock tickers and
            values are dictionaries containing position and average cost details.
            Example: {'SPY': {'position': 100, 'averageCost': 450.25}}
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR.")

        # Create a future to await the result from the wrapper
        future = self.loop.create_future()
        self.wrapper._positions_future = future
        self.wrapper._positions_data = []  # Clear any old data

        self._log_status("info", "Requesting current portfolio positions...")
        self.client.reqPositions()  # This triggers the 'position' and 'positionEnd' callbacks

        try:
            # Wait for the future to be resolved by the positionEnd callback
            raw_positions = await asyncio.wait_for(future, timeout=timeout_sec)
            
            # Format the raw data into the desired dictionary structure
            formatted_positions = {}
            for pos_data in raw_positions:
                contract = pos_data['contract']
                # Ensure we only process stocks for this application's purpose
                if contract.secType == 'STK':
                    formatted_positions[contract.symbol] = {
                        'position': pos_data['position'],
                        'averageCost': pos_data['averageCost']
                    }
            
            self._log_status("info", f"Successfully fetched {len(formatted_positions)} stock positions.")
            return formatted_positions

        except asyncio.TimeoutError:
            self._log_status("error", "Timeout requesting portfolio positions.")
            raise
        finally:
            # Always cancel the subscription to stop receiving position updates
            self.client.cancelPositions()
            self.wrapper._positions_future = None  # Clear the future  

    async def execute_order_async(self, contract: Contract, order: Order, timeout_sec: int = 15) -> Dict[str, Any]:
        """
        Places an order and waits for submission confirmation.

        Args:
            contract (Contract): The contract object for the order.
            order (Order): The order object to be placed.
            timeout_sec (int): Timeout in seconds to wait for submission status.

        Returns:
            Dict[str, Any]: A dictionary with the final status of the order submission.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR.")

        order_id = self.get_next_req_id() # Using the main reqId sequence for simplicity
        future = self.loop.create_future()
        self.wrapper.futures[order_id] = future

        self._log_status("info", f"Placing order {order.action} {order.totalQuantity} {contract.symbol} (OrderId: {order_id}).")
        self.client.placeOrder(order_id, contract, order)

        try:
            result = await asyncio.wait_for(future, timeout=timeout_sec)
            self._log_status("info", f"Order submission confirmed for OrderId {order_id}. Status: {result.get('status')}")
            return result
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout waiting for order submission confirmation for OrderId {order_id}.")
            # The order might have been placed, but we didn't get a timely status update.
            # Real-world logic would require reconciliation here.
            raise
        finally:
            self.wrapper.futures.pop(order_id, None)

    async def request_contract_details_async(self, contract_input: Union[Contract, str], secType_if_str: str = "STK", exchange_if_str: str = "SMART", currency_if_str: str = "USD", timeout_sec: int = 10) -> List[ContractDetails]:
        if not self.is_connected() or not self.loop:
            self._log_status("error", "Not connected or loop not set for contract details request.")
            raise ConnectionError("Not connected to IBKR or event loop not set.")

        actual_contract: Contract
        if isinstance(contract_input, str):
            self._log_status("debug", f"Creating Contract object for symbol '{contract_input}'")
            actual_contract = Contract()
            actual_contract.symbol = contract_input.upper()
            actual_contract.secType = secType_if_str.upper()
            actual_contract.exchange = exchange_if_str.upper()
            actual_contract.currency = currency_if_str.upper()
        elif isinstance(contract_input, Contract):
            actual_contract = contract_input
        else:
            raise TypeError(f"contract_input must be a ticker symbol string or an IB Contract object, got {type(contract_input)}")

        req_id = self.get_next_req_id()
        api_future = self.loop.create_future() 
        
        if not hasattr(self.wrapper, 'futures') or not hasattr(self.wrapper, 'request_data_store'):
             self._log_status("error", "Wrapper not properly initialized with futures/request_data_store for contract details.")
             raise AttributeError("Wrapper futures or request_data_store not initialized.")
        self.wrapper.futures[req_id] = api_future
        self.wrapper.request_data_store[req_id] = [] 

        contract_display = f"{actual_contract.symbol} {actual_contract.secType} {actual_contract.exchange}"
        if actual_contract.lastTradeDateOrContractMonth: contract_display += f" {actual_contract.lastTradeDateOrContractMonth}"
        if hasattr(actual_contract, 'strike') and actual_contract.strike and actual_contract.strike > 0 : # type: ignore
            contract_display += f" K{actual_contract.strike}{actual_contract.right if hasattr(actual_contract, 'right') and actual_contract.right else ''}" # type: ignore
        
        self._log_status("info", f"Requesting contract details for {contract_display} (ReqId: {req_id})...")
        self.client.reqContractDetails(req_id, actual_contract)
        try:
            return await asyncio.wait_for(api_future, timeout=timeout_sec)
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout requesting contract details for {contract_display} (ReqId: {req_id}).")
            # No need to pop here, finally block will handle it.
            raise
        except IBKRApiError as e: 
            self._log_status("error", f"API error requesting contract details for {contract_display} (ReqId: {req_id}): {e}")
            raise
        finally:
            self.wrapper.futures.pop(req_id, None)
            self.wrapper.request_data_store.pop(req_id, None)


    async def request_historical_data_async(self, contract: Contract, endDateTime: str = "", durationStr: str = "1 D", barSizeSetting: str = "1 day", whatToShow: str = "TRADES", useRTH: bool = True, formatDate: int = 1, keepUpToDate: bool = False, chartOptions: Optional[List[Any]] = None, timeout_sec: int = 60) -> List[BarData]:
        if not self.is_connected() or not self.loop:
            self._log_status("error", "Not connected or loop not set for historical data request.")
            raise ConnectionError("Not connected to IBKR or event loop not set.")
        
        req_id = self.get_next_req_id()
        api_future = self.loop.create_future()
        if not hasattr(self.wrapper, 'futures') or not hasattr(self.wrapper, 'request_data_store'):
             self._log_status("error", "Wrapper not properly initialized with futures/request_data_store for historical data.")
             raise AttributeError("Wrapper futures or request_data_store not initialized.")
        self.wrapper.futures[req_id] = api_future
        self.wrapper.request_data_store[req_id] = [] 

        contract_display_name = contract.localSymbol if contract.localSymbol else f"{contract.symbol} {contract.secType}"
        self._log_status("info", f"Requesting historical data for {contract_display_name} (ReqId: {req_id}). End: '{endDateTime}', Dur: '{durationStr}', Bar: '{barSizeSetting}', What: '{whatToShow}', useRTH: {useRTH}")
        self.client.reqHistoricalData(req_id, contract, endDateTime, durationStr, barSizeSetting, whatToShow, 1 if useRTH else 0, formatDate, keepUpToDate, chartOptions if chartOptions else [])
        try:
            return await asyncio.wait_for(api_future, timeout=timeout_sec)
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout requesting historical data for {contract_display_name} (ReqId: {req_id}).")
            raise
        except IBKRApiError as e:
            self._log_status("error", f"API error requesting historical data for {contract_display_name} (ReqId: {req_id}): {e}")
            raise
        finally:
            self.wrapper.futures.pop(req_id, None)
            self.wrapper.request_data_store.pop(req_id, None)


    async def request_market_data_snapshot_async(self, contract: Contract, 
                                                 genericTickList: str = "",
                                                 regulatorySnapshot: bool = False, 
                                                 timeout_sec: int = 20) -> Dict[str, Any]: # Return type is Dict
        """
        Requests a market data snapshot. For snapshots, a specific genericTickList is usually not provided;
        IBKR returns a standard set of ticks.
        """
        if not self.is_connected() or not self.loop:
            self._log_status("error", "Not connected or loop not set for market data snapshot.")
            raise ConnectionError("Not connected to IBKR or event loop not set.")
        
        req_id = self.get_next_req_id()
        api_future = self.loop.create_future()
        self.wrapper.futures[req_id] = api_future
        self.wrapper.request_data_store[req_id] = {}

        contract_display_name = contract.localSymbol if contract.localSymbol else f"{contract.symbol} {contract.secType}"
        self._log_status("info", f"Requesting market data snapshot for {contract_display_name} (ReqId: {req_id}).")

        # Pass the arguments to the EClient method
        self.client.reqMktData(req_id, contract, genericTickList, True, regulatorySnapshot, []) # snapshot=True

        try:
            result = await asyncio.wait_for(api_future, timeout=timeout_sec)
            return result
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout requesting market data snapshot for {contract_display_name} (ReqId: {req_id}).")
            raise
        except IBKRApiError as e:
            self._log_status("error", f"API error requesting market data snapshot for {contract_display_name} (ReqId: {req_id}): {e}")
            raise
        finally:
            # Cancel the stream to be safe, although snapshots should be brief
            self.client.cancelMktData(req_id)
            self.wrapper.futures.pop(req_id, None)
            self.wrapper.request_data_store.pop(req_id, None)

# Add this new method to your IBKRBaseHandler class


