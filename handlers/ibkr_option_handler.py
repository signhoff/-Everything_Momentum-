# ibkr_option_handler.py
import logging
import asyncio
import sys 
from typing import List, Dict, Any, Optional, Set, Callable

from ibapi.contract import Contract
from ibapi.common import BarData

from handlers.ibkr_base_handler import IBKRBaseHandler
from handlers.ibkr_api_wrapper import IBKRApiError 

module_logger = logging.getLogger(__name__)
if not module_logger.hasHandlers():
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s (IBKROptionHandler) - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    module_logger.addHandler(handler)
    module_logger.setLevel(logging.INFO) 
    module_logger.propagate = False

class IBKROptionHandler(IBKRBaseHandler):
    def __init__(self, status_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        super().__init__(status_callback=status_callback)
        if not hasattr(self, '_is_connected_flag'): 
            self._is_connected_flag: bool = False
        self._log_status("info", f"{self.__class__.__name__} instance created.")

    async def request_sec_def_opt_params_async(self, underlying_symbol: str, underlying_sec_type: str = "STK", underlying_con_id: int = 0, fut_fop_exchange: str = "", timeout_sec: int = 30) -> List[Dict[str, Any]]:
        if not self.is_connected():
            self._log_status("error", "Not connected to IBKR for option parameter request.")
            raise ConnectionError("Not connected to IBKR.")

        if not self.loop or not self.loop.is_running():
            self._log_status("warning", "IBKR event loop not available or not running for option parameter request. Attempting to get current loop.")
            try:
                self.loop = asyncio.get_running_loop()
                if self.wrapper and hasattr(self.wrapper, 'set_event_loop'): 
                    self.wrapper.set_event_loop(self.loop)
                self._log_status("info", f"Acquired/re-set running loop: {self.loop} for option parameter request.")
            except RuntimeError:
                 self._log_status("error", "No running asyncio event loop found for option parameter request.")
                 raise RuntimeError("Asyncio event loop not available for option parameter request.")

        actual_con_id = underlying_con_id
        if actual_con_id == 0 and underlying_symbol:
            self._log_status("info", f"Resolving conId for {underlying_symbol} ({underlying_sec_type})...")
            underlying_contract_for_conid = Contract()
            underlying_contract_for_conid.symbol = underlying_symbol.upper()
            underlying_contract_for_conid.secType = underlying_sec_type.upper()
            underlying_contract_for_conid.currency = "USD" 

            if underlying_sec_type.upper() == "STK":
                underlying_contract_for_conid.exchange = "SMART"
                major_indices_primary_ex = {"SPY": "ARCA", "QQQ": "NASDAQ", "IWM": "ARCA", "DIA": "ARCA"}
                major_stocks_primary_ex = {"AAPL": "NASDAQ", "MSFT": "NASDAQ", "AMZN": "NASDAQ", "GOOGL": "NASDAQ", "GOOG": "NASDAQ", "TSLA": "NASDAQ", "NVDA": "NASDAQ"}
                if underlying_symbol.upper() in major_indices_primary_ex:
                    underlying_contract_for_conid.primaryExchange = major_indices_primary_ex[underlying_symbol.upper()]
                elif underlying_symbol.upper() in major_stocks_primary_ex:
                     underlying_contract_for_conid.primaryExchange = major_stocks_primary_ex[underlying_symbol.upper()]
            elif underlying_sec_type.upper() == "IND":
                if underlying_symbol.upper() in ["SPX", "VIX", "NDX", "RUT"]: 
                    underlying_contract_for_conid.exchange = "CBOE"

            try:
                details = await super().request_contract_details_async(underlying_contract_for_conid, timeout_sec=15)
                if details and isinstance(details, list) and len(details) > 0 and details[0].contract.conId:
                    actual_con_id = details[0].contract.conId
                    self._log_status("info", f"Resolved {underlying_symbol} ({underlying_sec_type}) to conId: {actual_con_id}")
                else:
                    msg = f"Could not resolve a valid conId for {underlying_symbol} ({underlying_sec_type}). Details received: {details}"
                    self._log_status("error", msg)
                    raise IBKRApiError(reqId=0, code=200, message=msg)
            except IBKRApiError as e:
                self._log_status("error", f"API error resolving conId for {underlying_symbol} ({underlying_sec_type}): {e}")
                raise
            except Exception as e_resolve:
                self._log_status("error", f"Unexpected error resolving conId for {underlying_symbol} ({underlying_sec_type}): {e_resolve}", exc_info=True)
                raise IBKRApiError(reqId=0, code=500, message=f"Unexpected error resolving conId for {underlying_symbol}: {e_resolve}")

        if actual_con_id == 0:
            msg = f"Cannot request option parameters: underlyingConId is 0 for {underlying_symbol} after resolution attempt."
            self._log_status("error", msg)
            raise IBKRApiError(reqId=0, code=321, message=msg)

        req_id = self.get_next_req_id()
        future = self.loop.create_future()
        if not hasattr(self.wrapper, 'futures') or not hasattr(self.wrapper, 'request_data_store'):
             self._log_status("error", "Wrapper not properly initialized with futures/request_data_store for opt params.")
             raise AttributeError("Wrapper attributes 'futures' or 'request_data_store' not initialized.")
        self.wrapper.futures[req_id] = future
        self.wrapper.request_data_store[req_id] = [] 

        self._log_status("info", f"Requesting option parameters for {underlying_symbol} (ConId: {actual_con_id}, SecType: {underlying_sec_type}, TargetExch: '{fut_fop_exchange}') (ReqId: {req_id})...")
        if not self.client:
            self._log_status("error", "IBKR client not initialized for opt params request.")
            raise ConnectionError("IBKR client not initialized.")
        
        self.client.reqSecDefOptParams(req_id, underlying_symbol.upper(), fut_fop_exchange.upper(), underlying_sec_type.upper(), actual_con_id)
        try:
            return await asyncio.wait_for(future, timeout=timeout_sec)
        except asyncio.TimeoutError:
            self._log_status("error", f"Timeout requesting option parameters for {underlying_symbol} (ReqId: {req_id}).")
            raise 
        except IBKRApiError as e: 
            self._log_status("error", f"API error requesting option parameters for {underlying_symbol} (ReqId: {req_id}): {e}")
            raise 
        finally: 
            self.wrapper.futures.pop(req_id, None)
            self.wrapper.request_data_store.pop(req_id, None)

    async def get_option_expirations_async(self, underlying_symbol: str, underlying_sec_type: str = "STK", underlying_con_id: int = 0, fut_fop_exchange: str = "", timeout_sec: int = 30) -> List[str]:
        all_param_sets = await self.request_sec_def_opt_params_async(underlying_symbol, underlying_sec_type, underlying_con_id, fut_fop_exchange, timeout_sec)
        all_expirations: Set[str] = set()
        for param_set in all_param_sets:
            if "expirations" in param_set and isinstance(param_set["expirations"], set):
                all_expirations.update(param_set["expirations"])
        
        if not all_expirations:
            self._log_status("warning", f"No expirations found for {underlying_symbol}. Param sets received: {len(all_param_sets)}")
        return sorted(list(all_expirations))

    async def get_option_chain_strikes_async(self, underlying_symbol: str, expiration_date_str: str, underlying_sec_type: str = "STK", underlying_con_id: int = 0, fut_fop_exchange: str = "", option_exchange_filter: str = "", timeout_sec: int = 30) -> List[float]:
        all_param_sets = await self.request_sec_def_opt_params_async(underlying_symbol, underlying_sec_type, underlying_con_id, fut_fop_exchange, timeout_sec)
        all_strikes: Set[float] = set()
        found_expiration_for_filter = False

        for param_set in all_param_sets:
            current_chain_exchange = param_set.get("exchange", "").upper()
            if option_exchange_filter and current_chain_exchange != option_exchange_filter.upper():
                continue 

            if "expirations" in param_set and isinstance(param_set["expirations"], set) and expiration_date_str in param_set["expirations"]:
                found_expiration_for_filter = True 
                if "strikes" in param_set and isinstance(param_set["strikes"], set):
                    all_strikes.update(param_set["strikes"])
        
        if not found_expiration_for_filter:
            self._log_status("warning", f"Expiration {expiration_date_str} not found for {underlying_symbol} (Exchange filter: '{option_exchange_filter if option_exchange_filter else 'Any'}').")
        elif not all_strikes: 
             self._log_status("warning", f"No strikes found for {underlying_symbol} exp {expiration_date_str} (Exchange filter: '{option_exchange_filter if option_exchange_filter else 'Any'}').")
        
        return sorted(list(all_strikes))

    async def _qualify_option_contract(self, symbol: str, sec_type: str, expiration: str, strike: float, right: str, initial_exchange_user_pref: str, currency: str, trading_class_val: Optional[str], multiplier_val: Optional[str]) -> Optional[Contract]:
        tc_to_use = trading_class_val if trading_class_val else symbol.upper()
        mult_to_use = multiplier_val if multiplier_val else "100"

        base_contract_params = {
            "symbol": symbol.upper(), "secType": sec_type.upper(), "lastTradeDateOrContractMonth": expiration,
            "strike": strike, "right": right.upper(), "currency": currency.upper(),
            "tradingClass": tc_to_use, "multiplier": mult_to_use
        }
        attempt_configs = []

        if initial_exchange_user_pref:
            c1 = Contract(); vars(c1).update(base_contract_params); c1.exchange = initial_exchange_user_pref.upper()
            attempt_configs.append({"contract": c1, "desc": f"UserPref Exch ({c1.exchange})"})

        if not initial_exchange_user_pref or initial_exchange_user_pref.upper() == "SMART":
            common_prim_exchanges = ["CBOE", "NASDAQOM", "ARCA", "AMEX", "ISE", "BOX"] 
            for prim_ex in common_prim_exchanges:
                c_smart = Contract(); vars(c_smart).update(base_contract_params)
                c_smart.exchange = "SMART"; c_smart.primaryExchange = prim_ex
                attempt_configs.append({"contract": c_smart, "desc": f"SMART with PrimExch {prim_ex}"})
        
        common_us_option_exchanges = ["CBOE", "AMEX", "PHLX", "ISE", "NASDAQOM", "BOX", "ARCA", "GEMINI", "MIAX", "PEARL", "EMERALD", "NASDAQBX"]
        for ex_loop in common_us_option_exchanges:
            if initial_exchange_user_pref and ex_loop == initial_exchange_user_pref.upper(): continue
            c_specific = Contract(); vars(c_specific).update(base_contract_params); c_specific.exchange = ex_loop
            attempt_configs.append({"contract": c_specific, "desc": f"Specific Exch ({ex_loop})"})
            
        if initial_exchange_user_pref: 
            c_blank = Contract(); vars(c_blank).update(base_contract_params); c_blank.exchange = ""
            attempt_configs.append({"contract": c_blank, "desc": "Blank Exch (IBKR Resolve)"})
        
        self._log_status("info", f"Attempting to qualify option: {symbol} {expiration} K{strike}{right}. Max attempts: {len(attempt_configs)}")

        for i, config_item in enumerate(attempt_configs):
            contract_to_qualify = config_item["contract"]
            desc = config_item["desc"]
            self._log_status("debug", f"Qualify attempt {i+1}/{len(attempt_configs)} ({desc}): Exch='{contract_to_qualify.exchange}', PrimEx='{getattr(contract_to_qualify, 'primaryExchange', '')}', TC='{contract_to_qualify.tradingClass}'")
            
            try:
                details_list = await super().request_contract_details_async(contract_to_qualify, timeout_sec=7) 
                if details_list: 
                    qualified_contract = details_list[0].contract
                    self._log_status("info", f"Qualification SUCCESS ({desc}) for {qualified_contract.localSymbol if qualified_contract.localSymbol else 'N/A'} (ConId: {qualified_contract.conId}, Exch: {qualified_contract.exchange}, PrimEx: {qualified_contract.primaryExchange})")
                    return qualified_contract
            except IBKRApiError as e:
                if e.code == 200: 
                    self._log_status("debug", f"Qualify attempt {i+1} ({desc}) failed: {e.message}")
                else: 
                    self._log_status("warning", f"API error on qualification attempt {i+1} ({desc}): {e}")
            except asyncio.TimeoutError:
                 self._log_status("debug", f"Timeout on qualification attempt {i+1} ({desc}).") 
            except Exception as e_qual:
                self._log_status("error", f"Unexpected error on qualification attempt {i+1} ({desc}): {e_qual}", exc_info=True)
        
        self._log_status("warning", f"Failed to qualify option after all attempts for {symbol} {expiration} K{strike}{right} with initial exchange '{initial_exchange_user_pref}'.")
        return None

    async def request_option_market_data_snapshot_async(self, underlying_symbol: str, expiration_date_str: str, strike: float, right: str, exchange: str = "SMART", currency: str = "USD", trading_class: Optional[str] = None, multiplier: Optional[str] = None, regulatorySnapshot: bool = False, timeout_sec: int = 20) -> Dict[str, Any]:
        """Requests a market data snapshot for a specific option contract after qualifying it."""
        if not self.is_connected():
            self._log_status("error", "Not connected to IBKR for option snapshot request.")
            raise ConnectionError("Not connected to IBKR.")
        
        qualified_contract = await self._qualify_option_contract(
            symbol=underlying_symbol, sec_type="OPT", expiration=expiration_date_str,
            strike=strike, right=right, initial_exchange_user_pref=exchange,
            currency=currency, trading_class_val=trading_class, multiplier_val=multiplier
        )

        if not qualified_contract or not qualified_contract.conId:
            msg = f"Failed to qualify option contract for snapshot: {underlying_symbol} {expiration_date_str} K{strike}{right}"
            self._log_status("error", msg)
            raise IBKRApiError(reqId=0, code=200, message=msg) 

        self._log_status("info", f"Requesting market data snapshot for qualified option: {qualified_contract.localSymbol if qualified_contract.localSymbol else vars(qualified_contract)}")
        # Call super().request_market_data_snapshot_async WITHOUT genericTickList as it's handled by base for snapshots
        return await super().request_market_data_snapshot_async(
            contract=qualified_contract, 
            regulatorySnapshot=regulatorySnapshot, # Pass this along
            timeout_sec=timeout_sec
        )

    async def request_historical_option_data_async(self, underlying_symbol: str, expiration_date_str: str, strike: float, right: str, endDateTime: str, durationStr: str = "1 D", barSizeSetting: str = "1 day", whatToShow: str = "TRADES", useRTH: bool = True, exchange: str = "SMART", currency: str = "USD", trading_class: Optional[str] = None, multiplier: Optional[str] = None, formatDate: int = 1, timeout_sec: int = 60) -> List[BarData]:
        """Requests historical bar data for a specific option contract after qualifying it."""
        if not self.is_connected():
            self._log_status("error", "Not connected to IBKR for historical option data request.")
            raise ConnectionError("Not connected to IBKR.")

        qualified_contract = await self._qualify_option_contract(
            symbol=underlying_symbol, sec_type="OPT", expiration=expiration_date_str,
            strike=strike, right=right, initial_exchange_user_pref=exchange,
            currency=currency, trading_class_val=trading_class, multiplier_val=multiplier
        )

        if not qualified_contract or not qualified_contract.conId:
            msg = f"Failed to qualify option contract for historical data: {underlying_symbol} {expiration_date_str} K{strike}{right}"
            self._log_status("error", msg)
            raise IBKRApiError(reqId=0, code=200, message=msg)
        
        self._log_status("info", f"Requesting historical data for qualified option: {qualified_contract.localSymbol if qualified_contract.localSymbol else vars(qualified_contract)}")
        return await super().request_historical_data_async(
            contract=qualified_contract, endDateTime=endDateTime, durationStr=durationStr,
            barSizeSetting=barSizeSetting, whatToShow=whatToShow, useRTH=useRTH,
            formatDate=formatDate, keepUpToDate=False, 
            chartOptions=[], 
            timeout_sec=timeout_sec
        )
