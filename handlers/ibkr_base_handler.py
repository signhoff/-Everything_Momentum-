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
        self._order_id_counter: int = 0  # Counter for order IDs
        self.api_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_connected_flag: bool = False

        self._log_status("info", f"{self.__class__.__name__} instance created.")

    def _log_status(self, msg_type: str, message: str, **kwargs):
        log_level_map = {
            "error": logging.ERROR, "warning": logging.WARNING,
            "info": logging.INFO, "debug": logging.DEBUG
        }
        actual_class_name = self.__class__.__name__
        logger.log(log_level_map.get(msg_type.lower(), logging.INFO), f"[{actual_class_name}] {message}")

        if self.status_callback:
            payload = {"module": actual_class_name, "type": msg_type.lower(), "message": message, **kwargs}
            try:
                self.status_callback(payload)
            except Exception as e_cb:
                logger.error(f"Error in status_callback from {actual_class_name}: {e_cb}", exc_info=True)

    def _initialize_req_id_counter(self):
        if self.wrapper.next_valid_order_id is not None and self.wrapper.next_valid_order_id > 0:
            with self._lock:
                self._req_id_counter = self.wrapper.next_valid_order_id
            self._log_status("info", f"Request ID counter initialized. Starting at: {self._req_id_counter}")
        else:
            with self._lock:
                self._req_id_counter = int(time.time() * 1000) % 1000000
            self._log_status("warning", f"Using time-based fallback for reqId counter starting at {self._req_id_counter}.")

    def get_next_req_id(self) -> int:
        with self._lock:
            if self._req_id_counter == 0:
                self._initialize_req_id_counter()
            self._req_id_counter += 1
            return self._req_id_counter
            
    def get_next_order_id(self) -> int:
        if self._order_id_counter == 0:
            error_msg = "Order ID counter has not been initialized from TWS. Cannot place order."
            self._log_status("critical", error_msg)
            raise ConnectionError(error_msg)
        with self._lock:
            order_id = self._order_id_counter
            self._order_id_counter += 1
        return order_id

    def _client_thread_target(self):
        self._log_status("info", "IBKR API client thread starting execution.")
        try:
            self.client.run()
        except Exception as e:
            self._log_status("error", f"Exception in IBKR API client thread: {e}", exc_info=True)
        finally:
            self._log_status("info", "IBKR API client thread finished.")
            self._is_connected_flag = False

    async def connect(self, host: str, port: int, clientId: int, loop: Optional[asyncio.AbstractEventLoop] = None, timeout_sec: int = 10) -> bool:
        self._log_status("info", f"Attempting to connect to IBKR at {host}:{port} with ClientID {clientId}")
        self.loop = loop or asyncio.get_running_loop()

        if self.client.isConnected() and self._is_connected_flag:
            return True

        self.wrapper.reset_connection_state()
        self.client.connect(host, port, clientId)
        
        if not self.api_thread or not self.api_thread.is_alive():
            self.api_thread = threading.Thread(target=self._client_thread_target, daemon=True, name=f"IBClientThread_CID{clientId}")
            self.api_thread.start()

        try:
            await asyncio.wait_for(self.loop.run_in_executor(None, self.wrapper.connection_event.wait, timeout_sec), timeout=timeout_sec + 1)
        except asyncio.TimeoutError:
            self._log_status("error", f"IBKR connection attempt timed out for ClientID {clientId}.")
            await self.disconnect()
            return False

        if self.wrapper.connection_error_code is not None:
            self._log_status("error", f"IBKR connection failed. Code: {self.wrapper.connection_error_code}, Msg: {self.wrapper.connection_error_message}")
            return False
        
        if self.wrapper.next_valid_order_id > 0 and self.wrapper.initial_connection_made:
            self._log_status("info", f"Successfully connected to IBKR. NextValidId: {self.wrapper.next_valid_order_id}.")
            self._initialize_req_id_counter()
            with self._lock:
                self._order_id_counter = self.wrapper.next_valid_order_id
            self._log_status("info", f"Order ID counter initialized. Starting at: {self._order_id_counter}")
            self.client.reqMarketDataType(3)
            self._is_connected_flag = True
            return True
        else:
            self._log_status("warning", "IBKR connection failed post-event.")
            return False

    async def disconnect(self):
        if self.client.isConnected():
            self._log_status("info", "Disconnecting from IBKR...")
            self.client.disconnect()
        
        if self.api_thread and self.api_thread.is_alive():
            await self.loop.run_in_executor(None, self.api_thread.join, 5.0)

        self.api_thread = None
        self._is_connected_flag = False
        self._log_status("info", "IBKR disconnection process complete.")

    def is_connected(self) -> bool:
        return self._is_connected_flag

    async def resolve_contract_details_async(self, contract: Contract, timeout_sec: int = 10) -> Optional[Contract]:
        if not self.is_connected() or not self.loop:
            raise ConnectionError("Not connected to IBKR.")

        req_id = self.get_next_req_id()
        api_future = self.loop.create_future()
        self.wrapper.futures[req_id] = api_future

        self._log_status("info", f"Resolving contract details for {contract.symbol} (ReqId: {req_id})...")
        self.client.reqContractDetails(req_id, contract)

        try:
            contract_details_list = await asyncio.wait_for(api_future, timeout=timeout_sec)
            if not contract_details_list:
                return None
            
            primary_contract = contract_details_list[0].contract
            for details in contract_details_list:
                if details.contract.primaryExchange in ["NYSE", "NASDAQ", "ARCA"]:
                    primary_contract = details.contract
                    break
            
            self._log_status("info", f"Resolved {contract.symbol} to conId: {primary_contract.conId} on {primary_contract.primaryExchange}")
            return primary_contract
        except (asyncio.TimeoutError, IBKRApiError) as e:
            self._log_status("error", f"Error/timeout resolving contract for {contract.symbol}: {e}")
            return None
        finally:
            self.wrapper.futures.pop(req_id, None)

    async def execute_order_async(self, contract: Contract, order: Order, timeout_sec: int = 15) -> Dict[str, Any]:
        if not self.is_connected() or not self.loop:
            raise ConnectionError("Not connected to IBKR.")

        order_id = self.get_next_order_id()
        order.orderId = order_id
        
        api_future = self.loop.create_future()
        self.wrapper.futures[order_id] = api_future

        self._log_status("info", f"Placing order {order.action} {order.totalQuantity} {contract.symbol} (OrderId: {order_id}).")
        self.client.placeOrder(order_id, contract, order)

        try:
            result = await asyncio.wait_for(api_future, timeout=timeout_sec)
            self._log_status("info", f"Order submission confirmed for OrderId {order_id}. Status: {result.get('status')}")
            return result
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout waiting for order submission confirmation for OrderId {order_id}.")
            raise
        finally:
            self.wrapper.futures.pop(order_id, None)

    async def request_market_data_snapshot_async(self, contract: Contract, timeout_sec: int = 20) -> Dict[str, Any]:
        if not self.is_connected() or not self.loop:
            raise ConnectionError("Not connected to IBKR.")
        
        req_id = self.get_next_req_id()
        api_future = self.loop.create_future()
        self.wrapper.futures[req_id] = api_future
        self.wrapper.request_data_store[req_id] = {}

        self._log_status("info", f"Requesting market data snapshot for {contract.symbol} (ReqId: {req_id}).")
        self.client.reqMktData(req_id, contract, "", True, False, [])

        result: Dict[str, Any] = {}
        try:
            result = await asyncio.wait_for(api_future, timeout=timeout_sec)
        except (asyncio.TimeoutError, IBKRApiError) as e:
            self._log_status("error", f"Error/timeout requesting snapshot for {contract.symbol}: {e}")
        finally:
            self.client.cancelMktData(req_id)
            self.wrapper.futures.pop(req_id, None)
            self.wrapper.request_data_store.pop(req_id, None)
            
        return result