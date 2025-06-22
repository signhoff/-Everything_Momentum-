# handlers/ibkr_api_wrapper.py
import threading
import logging
import asyncio
from typing import Dict, Any, List, Optional, Set, Callable

from ibapi.wrapper import EWrapper
from ibapi.utils import iswrapper
from ibapi.common import BarData, TickAttrib
from ibapi.contract import Contract, ContractDetails # <-- Added Contract
from ibapi.ticktype import TickTypeEnum

# Logger for this module
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    # Basic handler setup, assuming main application might configure logging more globally.
    handler = logging.StreamHandler() # Use sys.stdout if preferred and sys is imported
    formatter = logging.Formatter('%(asctime)s - %(name)s (IBKRAPIWrapper) - %(levelname)s - %(message)s') # Clarified logger name
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO) # Default level
    logger.propagate = False # Avoid duplicate logs if root logger is also configured

class IBKRApiError(Exception):
    """Custom exception for API errors."""
    def __init__(self, reqId: int, code: int, message: str, advancedOrderRejectJson: str = ""): # Added advancedOrderRejectJson
        self.reqId = reqId
        self.code = code
        self.message = message
        self.advancedOrderRejectJson = advancedOrderRejectJson
        full_message = f"ReqId {reqId} - Code {code}: {message}"
        if advancedOrderRejectJson:
            full_message += f" (Advanced: {advancedOrderRejectJson})"
        super().__init__(full_message)

class IBKROfficialAPIWrapper(EWrapper):
    def __init__(self, status_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
                 base_handler_ref: Optional[Any] = None): # Modified __init__
        super().__init__()
        self.status_callback = status_callback
        self.base_handler_ref = base_handler_ref # Reference to the IBKRBaseHandler instance
        self.loop: Optional[asyncio.AbstractEventLoop] = None # Will be set by IBKRBaseHandler
        self.next_valid_order_id: int = 0 # Initialize to 0, set by nextValidId callback
        self.connection_event = threading.Event() # For signaling connection status
        self.connection_error_code: Optional[int] = None
        self.connection_error_message: Optional[str] = None
        self.initial_connection_made: bool = False # Set true after nextValidId
        self.futures: Dict[int, asyncio.Future] = {} # Stores asyncio.Future for requests
        self.request_data_store: Dict[int, Any] = {} # Stores data for pending requests
        # --- NEW ATTRIBUTES FOR POSITION HANDLING ---
        self._positions_future: Optional[asyncio.Future] = None
        self._positions_data: List[Dict[str, Any]] = []

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """Called by IBKRBaseHandler to set the correct asyncio event loop."""
        self.loop = loop

    def _log_wrapper_status(self, msg_type: str, message: str, **kwargs):
        """Internal logging and status reporting for the wrapper."""
        log_level_map = {"error": logging.ERROR, "warning": logging.WARNING, "info": logging.INFO, "debug": logging.DEBUG}
        logger.log(log_level_map.get(msg_type.lower(), logging.INFO), message)

        if self.status_callback:
            payload = {"module": self.__class__.__name__, "type": msg_type.lower(), "message": message}
            payload.update(kwargs)
            try:
                self.status_callback(payload)
            except Exception as e_cb:
                logger.error(f"Error in wrapper status_callback: {e_cb}")
        elif self.base_handler_ref and hasattr(self.base_handler_ref, '_log_status'):
            # Fallback to base_handler's logging if direct callback not used by wrapper
            try:
                self.base_handler_ref._log_status(msg_type, f"(Wrapper) {message}", **kwargs)
            except Exception as e_bh_log:
                 logger.error(f"Error calling base_handler_ref._log_status: {e_bh_log}")

    def _safe_set_future_exception(self, future: Optional[asyncio.Future], exception: Exception):
        """Helper to safely set future exceptions from the API thread."""
        if future and not future.done():
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(future.set_exception, exception)
            else:
                future.set_exception(exception)

    def _safe_set_future_result(self, future: Optional[asyncio.Future], result: Any):
        """Helper to safely set future results from the API thread."""
        if future and not future.done():
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(future.set_result, result)
            else:
                future.set_result(result)

    @iswrapper
    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = ""):
        """Handles errors and informational messages from TWS."""
        super().error(reqId, errorCode, errorString, advancedOrderRejectJson)

        # List of informational codes that should not be treated as fatal errors for a request.
        # 10167: Market data is not subscribed, delayed data displayed.
        # 2104, 2106, 2158: Market data farm connection status notifications.
        IGNORABLE_ERROR_CODES = [10167, 2104, 2106, 2108, 2158]

        if errorCode in IGNORABLE_ERROR_CODES:
            # Log these as informational warnings but do not fail the request.
            self._log_wrapper_status("warning", f"IBKR Info (Code {errorCode}): {errorString}")
            return

        # For actual errors, fail the corresponding future.
        if reqId != -1 and reqId in self.futures:
            future = self.futures.get(reqId)
            self._safe_set_future_exception(future, IBKRApiError(reqId, errorCode, errorString, advancedOrderRejectJson))
        else:
            # General error not associated with a specific request
            self._log_wrapper_status("error", f"IBKR API Error (ReqId: {reqId}, Code: {errorCode}): {errorString}")

    def connectionClosed(self):
        super().connectionClosed()
        self._log_wrapper_status("info", "IBKR connectionClosed callback received.")
        self.initial_connection_made = False
        for future in self.futures.values():
            self._safe_set_future_exception(future, IBKRApiError(-1, -1, "Connection closed by IBKR"))
        self._safe_set_future_exception(self._positions_future, IBKRApiError(-1, -1, "Connection closed by IBKR"))
        self.futures.clear()
        self.request_data_store.clear()
        self._positions_future = None
        self._positions_data = []

    @iswrapper
    def connectAck(self):
        super().connectAck()
        self._log_wrapper_status("info", "IBKR connectAck received.")
        # Connection is not fully confirmed until nextValidId

    @iswrapper
    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.next_valid_order_id = orderId
        self.initial_connection_made = True # Mark connection as established
        self.connection_error_code = None   # Clear any previous connection attempt errors
        self.connection_error_message = None
        
        self._log_wrapper_status("info", f"NextValidId received: {orderId}. Connection fully established.")
        
        if hasattr(self, 'connection_event') and self.connection_event:
            self.connection_event.set() # Signal successful connection to base_handler.connect()

        # Initialize reqId counter in base_handler if ref is available
        if self.base_handler_ref and hasattr(self.base_handler_ref, '_initialize_req_id_counter'):
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(self.base_handler_ref._initialize_req_id_counter)
            else:
                self._log_wrapper_status("warning", "Cannot call _initialize_req_id_counter: Loop not available or not running.")

    def reset_connection_state(self):
        """Called by IBKRBaseHandler before attempting a new connection."""
        self.initial_connection_made = False
        self.next_valid_order_id = 0
        if hasattr(self, 'connection_event') and self.connection_event:
            self.connection_event.clear()
        self.connection_error_code = None
        self.connection_error_message = None
        self._log_wrapper_status("info", "Connection state reset in wrapper.")

    @iswrapper
    def historicalData(self, reqId: int, bar: BarData):
        if reqId in self.futures:
            if reqId not in self.request_data_store:
                self.request_data_store[reqId] = []
            self.request_data_store[reqId].append(bar)

    @iswrapper
    def historicalDataEnd(self, reqId: int, start: str, end: str):
        super().historicalDataEnd(reqId, start, end)
        if reqId in self.futures:
            result = self.request_data_store.get(reqId, [])
            self._safe_set_future_result(self.futures.get(reqId), result)

    @iswrapper
    def contractDetails(self, reqId: int, contractDetails: ContractDetails):
        if reqId in self.futures:
            if reqId not in self.request_data_store:
                self.request_data_store[reqId] = []
            self.request_data_store[reqId].append(contractDetails)

    @iswrapper
    def contractDetailsEnd(self, reqId: int):
        super().contractDetailsEnd(reqId)
        if reqId in self.futures:
            result = self.request_data_store.get(reqId, [])
            self._safe_set_future_result(self.futures.get(reqId), result) # CORRECTED

    # --- Tick Data Handling ---
    def _store_tick_data(self, reqId: int, tickType: int, value: Any, is_snapshot_end_expected: bool = False):
        """Helper to store tick data. If snapshot, data is usually a dict."""
        if reqId in self.futures:
            # For snapshots, request_data_store[reqId] is usually a dict.
            # For streaming, it might be a list or handled differently.
            # This example assumes snapshot data is collected into a dict.
            if not isinstance(self.request_data_store.get(reqId), dict):
                 # If it's the first tick for a snapshot or not a dict, initialize as dict
                 self.request_data_store[reqId] = {}
            
            tick_name = TickTypeEnum.idx2name.get(tickType, str(tickType))
            self.request_data_store[reqId][tick_name] = value
            # self._log_wrapper_status("debug", f"Tick Stored. ReqId: {reqId}, Type: {tick_name}, Value: {value}")
        # If not is_snapshot_end_expected, this might be streaming data.
        # Streaming data handling would require a different mechanism (e.g., continuous callback).

    @iswrapper
    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: TickAttrib):
        super().tickPrice(reqId, tickType, price, attrib)
        self._store_tick_data(reqId, tickType, price, is_snapshot_end_expected=True)

    @iswrapper
    def tickSize(self, reqId: int, tickType: int, size: int): # Note: size is an integer in IB API
        super().tickSize(reqId, tickType, size)
        self._store_tick_data(reqId, tickType, size, is_snapshot_end_expected=True)

    @iswrapper
    def tickString(self, reqId: int, tickType: int, value: str):
        super().tickString(reqId, tickType, value)
        self._store_tick_data(reqId, tickType, value, is_snapshot_end_expected=True)

    @iswrapper
    def tickGeneric(self, reqId: int, tickType: int, value: float):
        super().tickGeneric(reqId, tickType, value)
        self._store_tick_data(reqId, tickType, value, is_snapshot_end_expected=True)

    @iswrapper
    def tickOptionComputation(self, reqId: int, tickType: int, tickAttrib: int, impliedVol: float, delta: float, optPrice: float, pvDividend: float, gamma: float, vega: float, theta: float, undPrice: float):
        super().tickOptionComputation(reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice)
        if reqId in self.futures: # Check if we are expecting data for this reqId
            if not isinstance(self.request_data_store.get(reqId), dict):
                self.request_data_store[reqId] = {} # Initialize as dict if not already

            data_key = TickTypeEnum.idx2name.get(tickType, f"OptionComputation_{tickType}")
            
            # Helper to check for IB's "not available" sentinels for greeks
            def is_valid_greek(val: Optional[float]) -> bool:
                return val is not None and val != float('inf') and val != float('-inf') and val == val # Check for NaN

            # Helper for prices that might be -1.0 if not available
            def is_valid_price(val: Optional[float]) -> bool:
                return val is not None and val != -1.0 and val == val # Check for NaN

            greeks_payload = {
                "impliedVol": impliedVol if is_valid_greek(impliedVol) and impliedVol >= 0 else None, # IV cannot be negative
                "delta": delta if is_valid_greek(delta) else None,
                "optPrice": optPrice if is_valid_price(optPrice) else None,
                "pvDividend": pvDividend if is_valid_price(pvDividend) else None, # pvDividend can be 0
                "gamma": gamma if is_valid_greek(gamma) else None,
                "vega": vega if is_valid_greek(vega) else None,
                "theta": theta if is_valid_greek(theta) else None,
                "undPrice": undPrice if is_valid_price(undPrice) else None,
                "tickAttrib": tickAttrib
            }
            self.request_data_store[reqId][data_key] = greeks_payload
            # self._log_wrapper_status("debug", f"tickOptionComputation. ReqId: {reqId}, Type: {data_key}, Data: {greeks_payload}")
        else:
            self._log_wrapper_status("debug", f"Received tickOptionComputation for unexpected ReqId {reqId}")

    @iswrapper
    def tickSnapshotEnd(self, reqId: int):
        super().tickSnapshotEnd(reqId)
        if reqId in self.futures:
            result = self.request_data_store.get(reqId, {})
            self._safe_set_future_result(self.futures.get(reqId), result) # CORRECTED

    @iswrapper
    def marketDataType(self, reqId: int, marketDataType: int):
        super().marketDataType(reqId, marketDataType)
        msg = f"MarketDataType. ReqId: {reqId}, Type: {marketDataType} (1=Live, 2=Frozen, 3=Delayed, 4=Delayed Frozen)"
        self._log_wrapper_status("info", msg)
        # Optionally store this if it's part of a snapshot request's expected data
        if reqId in self.request_data_store and isinstance(self.request_data_store.get(reqId), dict):
           self.request_data_store[reqId]['actualMarketDataType'] = marketDataType

    @iswrapper
    def securityDefinitionOptionParameter(self, reqId: int, exchange: str, underlyingConId: int, tradingClass: str, multiplier: str, expirations: Set[str], strikes: Set[float]):
        super().securityDefinitionOptionParameter(reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes)
        # self._log_wrapper_status("debug", f"SecurityDefinitionOptionParameter. ReqId: {reqId}, Exchange: {exchange}, TC: {tradingClass}, #Exp: {len(expirations)}, #Str: {len(strikes)}")
        if reqId in self.futures: # Check if we are expecting data for this reqId
            if reqId not in self.request_data_store:
                self.request_data_store[reqId] = [] # Initialize as list to store multiple param sets
            param_set = {
                "exchange": exchange,
                "underlyingConId": underlyingConId,
                "tradingClass": tradingClass,
                "multiplier": multiplier,
                "expirations": expirations, # This is a set
                "strikes": strikes         # This is a set
            }
            self.request_data_store[reqId].append(param_set)
        else:
            self._log_wrapper_status("debug", f"Received securityDefinitionOptionParameter for unexpected ReqId {reqId}")

    @iswrapper
    def securityDefinitionOptionParameterEnd(self, reqId: int):
        super().securityDefinitionOptionParameterEnd(reqId)
        self._log_wrapper_status("info", f"SecurityDefinitionOptionParameterEnd. ReqId: {reqId}")
        if reqId in self.futures:
            result = self.request_data_store.get(reqId, []) # Result is a list of dicts
            self._safe_set_future_result(reqId, result)
        else:
            self._log_wrapper_status("warning", f"ReqId {reqId} not in futures map for securityDefinitionOptionParameterEnd.")

    @iswrapper
    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str):
        super().accountSummary(reqId, account, tag, value, currency)
        if reqId in self.futures:
            if not isinstance(self.request_data_store.get(reqId), dict):
                self.request_data_store[reqId] = {}
            self.request_data_store[reqId][tag] = value

    @iswrapper
    def accountSummaryEnd(self, reqId: int):
        super().accountSummaryEnd(reqId)
        if reqId in self.futures:
            result = self.request_data_store.get(reqId, {})
            self._safe_set_future_result(self.futures.get(reqId), result)

    @iswrapper
    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        super().position(account, contract, position, avgCost)
        if self._positions_future and not self._positions_future.done():
            self._positions_data.append({"account": account,"contract": contract, "position": position, "averageCost": avgCost})

    @iswrapper
    def positionEnd(self):
        super().positionEnd()
        if self._positions_future and not self._positions_future.done():
            self._safe_set_future_result(self._positions_future, self._positions_data)
        self._positions_future = None
        self._positions_data = []

    @iswrapper
    def openOrder(self, orderId, contract, order, orderState):
        """Callback for receiving open order details."""
        super().openOrder(orderId, contract, order, orderState)
        # The orderState object contains the status, e.g., 'Submitted', 'Filled'
        # self._log_wrapper_status("info", f"openOrder - Id: {orderId}, Status: {orderState.status}")

    @iswrapper
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        """Callback for order status updates."""
        super().orderStatus(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        # self._log_wrapper_status("info", f"orderStatus - Id: {orderId}, Status: {status}, Filled: {filled}")

        # Check if this orderId is one we are waiting for
        if orderId in self.futures:
            # A list of statuses that indicate the order is in a final or stable state
            TERMINAL_STATES = ["Filled", "Cancelled", "ApiCancelled", "Inactive"]
            
            if status in TERMINAL_STATES:
                # If the order reaches a terminal state, we resolve the future
                self._safe_set_future_result(self.futures.get(orderId), {"status": status, "filled": filled})
            elif status == "Submitted":
                # We also consider "Submitted" as a success for fire-and-forget execution
                 self._safe_set_future_result(self.futures.get(orderId), {"status": status, "filled": filled})

    @iswrapper
    def _safe_set_future_result(self, future: asyncio.Future, result: Any):
        """Helper to safely set future results from the API thread."""
        if future and not future.done():
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(future.set_result, result)
            else:
                try:
                    future.set_result(result)
                except RuntimeError as e:
                    self._log_wrapper_status("error", f"RuntimeError setting future result directly: {e}")
