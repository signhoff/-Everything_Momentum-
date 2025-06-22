# utils/financial_calculations.py
# Core financial formulas for options pricing, P&L, Implied Volatility, and Spread Analysis.

import datetime
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq # For implied volatility calculation
import logging
import sys
from typing import List, Dict, Any, Optional, Callable

# Logger for this module
logger_fc = logging.getLogger(__name__)
if not logger_fc.hasHandlers():
    handler_fc = logging.StreamHandler(sys.stdout)
    # Added module name to logger for clarity in combined logs
    formatter_fc = logging.Formatter('%(asctime)s - %(name)s (financial_calculations) - %(levelname)s - %(message)s')
    handler_fc.setFormatter(formatter_fc)
    logger_fc.addHandler(handler_fc)
    logger_fc.setLevel(logging.INFO)
    logger_fc.propagate = False


def black_scholes_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
    """
    Calculates the Black-Scholes option price.

    Args:
        S: Current stock price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free interest rate (annualized).
        sigma: Implied volatility (annualized).
        option_type: "call", "put", "c", or "p".

    Returns:
        The Black-Scholes price of the option, or np.nan if inputs are invalid.
    """
    try:
        # Ensure all inputs are floats for calculation
        S, K, T, r, sigma = float(S), float(K), float(T), float(r), float(sigma)
    except ValueError:
        logger_fc.warning(f"BS Price Error: Non-numeric input. S={S}, K={K}, T={T}, r={r}, sigma={sigma}")
        return np.nan

    opt_type_lower = option_type.lower()

    # Handle edge case: Time to expiration is zero or negligible
    if T <= 1e-9:
        logger_fc.debug(f"BS Price Info: T near zero ({T:.2e}). Returning intrinsic value. S={S}, K={K}")
        return max(0.0, S - K) if opt_type_lower in ["call", "c"] else max(0.0, K - S)

    # Handle edge case: Volatility is zero or negligible
    if sigma <= 1e-9:
        logger_fc.debug(f"BS Price Info: Sigma near zero ({sigma:.2e}). Returning discounted intrinsic. S={S}, K={K}, T={T}")
        if opt_type_lower in ["call", "c"]:
            return max(0.0, S - K * np.exp(-r * T))
        elif opt_type_lower in ["put", "p"]:
            return max(0.0, K * np.exp(-r * T) - S)
        else:
            logger_fc.error(f"BS Price Error (sigma=0): Invalid option type. Original: '{option_type}'.")
            return np.nan

    # Handle edge cases for stock price or strike price being zero or negative
    if S <= 1e-9: # Stock price is zero or negative
        logger_fc.debug(f"BS Price Info: S near zero ({S:.2e}). K={K}, T={T}")
        return K * np.exp(-r * T) if opt_type_lower in ["put", "p"] else 0.0
    if K <= 1e-9: # Strike price is zero or negative
        logger_fc.debug(f"BS Price Info: K near zero ({K:.2e}). S={S}, T={T}")
        return S if opt_type_lower in ["call", "c"] else 0.0


    d1_denominator = sigma * np.sqrt(T)
    if abs(d1_denominator) < 1e-9:
        logger_fc.warning(f"BS Price Warning: d1_denominator (sigma*sqrt(T)) near zero: {d1_denominator}. S={S}, K={K}, T={T}, sigma={sigma}. Returning intrinsic.")
        return max(0.0, S - K) if opt_type_lower in ["call", "c"] else max(0.0, K - S)

    d1_val = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / d1_denominator
    d2_val = d1_val - sigma * np.sqrt(T)

    if opt_type_lower == "call" or opt_type_lower == "c":
        price = S * norm.cdf(d1_val) - K * np.exp(-r * T) * norm.cdf(d2_val)
    elif opt_type_lower == "put" or opt_type_lower == "p":
        price = K * np.exp(-r * T) * norm.cdf(-d2_val) - S * norm.cdf(-d1_val)
    else:
        logger_fc.error(f"BS Price Error: Invalid option type. Original input: '{option_type}'.")
        return np.nan

    return max(0.0, price) # Ensure price is not negative

def implied_volatility(option_price: float, S: float, K: float, T: float, r: float, option_type: str = "call",
                       low_vol: float = 1e-5, high_vol: float = 3.0, tol: float = 1e-6, max_iter: int = 100) -> float:
    """
    Calculates implied volatility using Brent's method.

    Args:
        option_price: Market price of the option.
        S: Current stock price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free interest rate (annualized).
        option_type: "call", "put", "c", or "p".
        low_vol: Lower bound for IV search.
        high_vol: Upper bound for IV search.
        tol: Tolerance for the IV solver.
        max_iter: Maximum iterations for the IV solver.

    Returns:
        The implied volatility, or np.nan if calculation fails.
    """
    if T <= 1e-9: # Time to expiration is zero or negative
        logger_fc.debug(f"IV Warning: Time to expiration is zero or negative (T={T:.2e}). S={S}, K={K}, Px={option_price}. Returning NaN.")
        return np.nan

    is_call = option_type.lower() in ["call", "c"]
    is_put = option_type.lower() in ["put", "p"]

    if not (is_call or is_put):
        logger_fc.error(f"IV Error: Invalid option_type '{option_type}' passed to implied_volatility.")
        return np.nan

    # If option price is very low for an OTM option, IV is likely very low.
    if option_price < tol: # Using tol as a threshold for "near zero" price
        if (is_call and S < K) or (is_put and S > K): # Out-of-the-money
             logger_fc.debug(f"IV Info: OTM option price is near zero ({option_price:.4f}). S={S}, K={K}, T={T:.4f}. Returning low_vol ({low_vol}).")
             return low_vol

    opt_type_normalized = "call" if is_call else "put"

    # Objective function for Brent's method: difference between BS price and market price
    def objective_function(sigma_obj: float) -> float:
        if sigma_obj < 1e-7: sigma_obj = 1e-7 # Ensure sigma is positive for BS calculation
        return black_scholes_price(S, K, T, r, sigma_obj, opt_type_normalized) - option_price

    try:
        # Check for arbitrage: option price must be >= discounted intrinsic value
        intrinsic_discounted = 0.0
        if opt_type_normalized == "call":
            intrinsic_discounted = max(0.0, S - K * np.exp(-r * T))
            if option_price < intrinsic_discounted - tol: # Allow for small tolerance
                logger_fc.warning(f"IV Warning (Call): Price {option_price:.4f} < Discounted Intrinsic {intrinsic_discounted:.4f}. S={S}, K={K}, T={T:.4f}, r={r}. Returning low_vol.")
                return low_vol
        else: # Put option
            intrinsic_discounted = max(0.0, K * np.exp(-r * T) - S)
            if option_price < intrinsic_discounted - tol:
                logger_fc.warning(f"IV Warning (Put): Price {option_price:.4f} < Discounted Intrinsic {intrinsic_discounted:.4f}. S={S}, K={K}, T={T:.4f}, r={r}. Returning low_vol.")
                return low_vol

        # Evaluate objective function at the bounds
        val_at_low_vol = objective_function(low_vol)
        val_at_high_vol = objective_function(high_vol)

        # If root is already at one of the bounds
        if abs(val_at_low_vol) < tol:
            logger_fc.debug(f"IV Info: Root found near low_vol ({low_vol}). S={S}, K={K}, T={T:.4f}, Px={option_price}")
            return low_vol
        if abs(val_at_high_vol) < tol:
            logger_fc.debug(f"IV Info: Root found near high_vol ({high_vol}). S={S}, K={K}, T={T:.4f}, Px={option_price}")
            return high_vol

        # If objective function has the same sign at both bounds, Brent's method may fail.
        # This can happen if the option price is outside the range achievable by varying IV within [low_vol, high_vol].
        if val_at_low_vol * val_at_high_vol > 0:
            logger_fc.warning(
                f"IV Solver Issue: Objective function has same sign at bounds [{low_vol}, {high_vol}]. "
                f"Params: OptPx={option_price:.4f}, S={S:.2f}, K={K:.2f}, T={T:.4f}, r={r:.4f}, Type={opt_type_normalized}. "
                f"f(low_vol={low_vol})={val_at_low_vol:.4f}, f(high_vol={high_vol})={val_at_high_vol:.4f}"
            )
            # Attempt to expand high_vol if market price is higher than BS at high_vol (val_at_high_vol < 0)
            if val_at_high_vol < 0:
                original_high_vol = high_vol
                for i in range(1, 4): # Try expanding a few times
                    expanded_high_vol = original_high_vol * (2**i)
                    if expanded_high_vol > 10.0 : expanded_high_vol = 10.0 # Cap expansion to a very high IV
                    val_at_expanded_high = objective_function(expanded_high_vol)
                    logger_fc.debug(f"IV Solver: Expanding high_vol to {expanded_high_vol:.2f}, f()={val_at_expanded_high:.4f}")
                    if val_at_low_vol * val_at_expanded_high < 0: # Found a bracket
                        high_vol = expanded_high_vol # Update high_vol for brentq
                        logger_fc.info(f"IV Solver: Found bracket with expanded high_vol={high_vol:.2f}")
                        break
                    if expanded_high_vol >= 10.0: break # Stop if max expansion reached
                # Check again after expansion attempt
                if val_at_low_vol * objective_function(high_vol) > 0:
                    logger_fc.warning("IV Solver: Still same sign after expanding high_vol. Returning NaN.")
                    return np.nan
            # If market price is lower than BS price even at low_vol (val_at_low_vol > 0)
            elif val_at_low_vol > 0:
                 logger_fc.warning(f"IV Solver: Market price {option_price:.4f} is below BS price at low_vol ({low_vol}). Returning low_vol.")
                 return low_vol
            else: # Other unhandled same-sign cases
                logger_fc.warning("IV Solver: Unhandled same-sign scenario. Returning NaN.")
                return np.nan

        # Use Brent's method to find the root (implied volatility)
        iv = brentq(objective_function, low_vol, high_vol, xtol=tol, rtol=tol, maxiter=max_iter)
        
        # Clamp IV to the search bounds just in case brentq slightly overshoots due to tolerance
        if iv < low_vol: iv = low_vol
        if iv > high_vol: iv = high_vol
        return iv

    except ValueError as e: # Error from brentq if bounds are invalid or other issues
        logger_fc.error(f"IV Error (Brentq ValueError): {e} for Px={option_price}, S={S}, K={K}, T={T}, r={r}, Type={opt_type_normalized}")
        return np.nan
    except RuntimeError as e: # Typically "failed to converge" from brentq
        logger_fc.error(f"IV Error (Brentq RuntimeError - max_iter likely): {e} for Px={option_price}, S={S}, K={K}, T={T}, r={r}, Type={opt_type_normalized}")
        return np.nan
    except Exception as e_unhandled: # Catch any other unexpected errors
        logger_fc.error(f"IV Error (Unhandled Exception): {e_unhandled} for Px={option_price}, S={S}, K={K}, T={T}, r={r}, Type={opt_type_normalized}", exc_info=True)
        return np.nan


def calculate_time_to_expiration_in_years(expiration_date_str: str, valuation_date_str: Optional[str] = None) -> float:
    """
    Calculates the time to expiration in years from a given valuation date.
    Dates should be in YYYY-MM-DD format.

    Args:
        expiration_date_str: The option's expiration date as "YYYY-MM-DD".
        valuation_date_str: The date of valuation as "YYYY-MM-DD". Defaults to today.

    Returns:
        Time to expiration in years. Returns a very small positive number if expired or at expiry.
    
    Raises:
        ValueError: If date strings are not in the correct format.
    """
    try:
        exp_date = datetime.datetime.strptime(expiration_date_str, "%Y-%m-%d").date()
    except ValueError:
        logger_fc.error(f"TTE Error: Invalid expiration_date_str format: '{expiration_date_str}'. Expected YYYY-MM-DD.")
        raise 

    if valuation_date_str:
        try:
            val_date = datetime.datetime.strptime(valuation_date_str, "%Y-%m-%d").date()
        except ValueError:
            logger_fc.error(f"TTE Error: Invalid valuation_date_str format: '{valuation_date_str}'. Expected YYYY-MM-DD.")
            raise
    else:
        val_date = datetime.date.today()

    if exp_date <= val_date:
        return 1e-9  # Effectively zero or past, return a very small positive number to avoid division by zero in BS
    
    # Using 365.25 to account for leap years on average
    return (exp_date - val_date).days / 365.25


def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Helper function to calculate d1 for Black-Scholes."""
    if T <= 1e-9 or sigma <= 1e-9: return np.nan # Avoid issues with zero T or sigma
    if S <= 0 or K <= 0: return np.nan # log(S/K) undefined or problematic

    d1_denominator_val = sigma * np.sqrt(T)
    if abs(d1_denominator_val) < 1e-9: # Avoid division by zero
        logger_fc.warning(f"d1 calc: denominator sigma*np.sqrt(T) is near zero ({d1_denominator_val}). S={S}, K={K}, T={T}, sigma={sigma}")
        return np.nan 
    return (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / d1_denominator_val

def _d2(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Helper function to calculate d2 for Black-Scholes."""
    if T <= 1e-9 or sigma <= 1e-9: return np.nan # Consistent with _d1 check

    d1_val = _d1(S, K, T, r, sigma)
    if np.isnan(d1_val): return np.nan # Propagate NaN if d1 failed

    sigma_sqrt_T = sigma * np.sqrt(T)
    # If sigma*sqrt(T) is extremely small, d2 is effectively d1.
    # This check avoids issues if d1 is large and sigma*sqrt(T) is ~0, which could lead to large d2.
    if abs(sigma_sqrt_T) < 1e-9 and abs(d1_val) > 1e-6 : # Check if d1 is significant
         logger_fc.debug(f"d2 calc: sigma*sqrt(T) is near zero ({sigma_sqrt_T}) but d1 is not ({d1_val}). Returning d1 for d2.")
         return d1_val # d2 approaches d1 as sigma*sqrt(T) approaches 0
    return d1_val - sigma_sqrt_T


def calculate_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str = 'call') -> Dict[str, float]:
    """
    Calculates Black-Scholes Greeks for a European option (Delta, Gamma, Vega, Theta, Rho).

    Args:
        S: Current stock price.
        K: Strike price.
        T: Time to expiration in years.
        r: Risk-free interest rate (annualized).
        sigma: Implied volatility (annualized).
        option_type: "call", "put", "c", or "p".

    Returns:
        A dictionary containing the calculated greeks. Values can be np.nan if calculation is not possible.
    """
    greeks = { 'delta': np.nan, 'gamma': np.nan, 'vega': np.nan, 'theta': np.nan, 'rho': np.nan }
    opt_type_lower = option_type.lower()

    if opt_type_lower not in ["call", "c", "put", "p"]:
        logger_fc.error(f"Greeks Error: Invalid option_type '{option_type}'")
        return greeks

    # Handle At Expiration (T is very small)
    if T <= 1e-6:
        logger_fc.debug(f"Greeks Info: T near zero ({T:.2e}). Calculating greeks at expiration. S={S}, K={K}")
        if opt_type_lower in ["call", "c"]: 
            greeks['delta'] = 1.0 if S > K else (0.5 if S == K else 0.0)
        elif opt_type_lower in ["put", "p"]: 
            greeks['delta'] = -1.0 if S < K else (-0.5 if S == K else 0.0)
        # Gamma is theoretically infinite ATM, zero otherwise. Often treated as 0 or very large.
        greeks['gamma'] = 0.0 # Or np.inf if S == K, but 0 is common simplification
        greeks['vega'] = 0.0 # No time for volatility to have an effect
        greeks['theta'] = 0.0 # No time value left to decay
        greeks['rho'] = 0.0 # Discounting effect minimal over zero time
        return greeks

    # Handle Zero Volatility (sigma is very small)
    if sigma <= 1e-6:
        logger_fc.debug(f"Greeks Info: Sigma near zero ({sigma:.2e}). Calculating greeks for zero volatility. S={S}, K={K}, T={T}")
        # Delta becomes a step function based on discounted intrinsic value
        discounted_K = K * np.exp(-r * T)
        if opt_type_lower in ["call", "c"]: 
            greeks['delta'] = 1.0 if S > discounted_K else (0.5 if S == discounted_K else 0.0)
        elif opt_type_lower in ["put", "p"]: 
            greeks['delta'] = -1.0 if S < discounted_K else (-0.5 if S == discounted_K else 0.0)
        greeks['vega'] = 0.0 # No sensitivity to vol if vol is zero
        # Gamma, Theta, Rho are problematic (often infinite at strike or zero). Return NaNs or zeros.
        greeks['gamma'] = np.nan # Or 0.0 / np.inf
        greeks['theta'] = np.nan # Or 0.0
        greeks['rho'] = np.nan   # Or 0.0
        return greeks

    d1_val = _d1(S, K, T, r, sigma)
    d2_val = _d2(S, K, T, r, sigma)

    if np.isnan(d1_val) or np.isnan(d2_val):
        logger_fc.warning(f"Greeks Warning: d1 ({d1_val}) or d2 ({d2_val}) is NaN. S={S}, K={K}, T={T}, r={r}, sigma={sigma}. Cannot calculate greeks.")
        return greeks # Return dict with NaNs

    N_d1 = norm.cdf(d1_val)
    N_d2 = norm.cdf(d2_val)
    n_d1 = norm.pdf(d1_val) # phi(d1), normal probability density function

    # Delta
    if opt_type_lower in ["call", "c"]: 
        greeks['delta'] = N_d1
    elif opt_type_lower in ["put", "p"]: 
        greeks['delta'] = N_d1 - 1.0

    # Gamma
    if S > 0 and sigma > 0 and T > 0: # Denominator checks for gamma: S * sigma * sqrt(T)
        gamma_denominator = S * sigma * np.sqrt(T)
        if abs(gamma_denominator) > 1e-9:
            greeks['gamma'] = n_d1 / gamma_denominator
        else:
            logger_fc.warning(f"Greeks Warning (Gamma): Denominator S*sigma*sqrt(T) near zero ({gamma_denominator}). S={S}, sigma={sigma}, T={T}")
            # Gamma can be very large if ATM and denominator is small
            greeks['gamma'] = np.inf if n_d1 > 1e-9 else 0.0 
    else:
        greeks['gamma'] = np.nan # If S, sigma, or T is zero/negative

    # Vega (per 1% change in IV)
    greeks['vega'] = S * n_d1 * np.sqrt(T) / 100.0

    # Theta (per day)
    # Common theta formula: -(S * n_d1 * sigma) / (2 * sqrt(T)) -/+ r * K * exp(-rT) * N(+/-d2)
    # The sign of the second term depends on call/put
    term1_theta = (S * n_d1 * sigma) / (2 * np.sqrt(T)) if T > 1e-9 else 0 # Avoid division by zero if T is tiny
    
    if opt_type_lower in ["call", "c"]:
        term2_theta_call = r * K * np.exp(-r * T) * N_d2
        theta_val = -term1_theta - term2_theta_call
    elif opt_type_lower in ["put", "p"]:
        N_minus_d2 = norm.cdf(-d2_val) # N(-d2)
        term2_theta_put = r * K * np.exp(-r * T) * N_minus_d2
        theta_val = -term1_theta + term2_theta_put
    else: # Should not happen due to earlier check
        theta_val = np.nan
    greeks['theta'] = theta_val / 365.0 # Convert annualized theta to per day

    # Rho (per 1% change in r)
    if opt_type_lower in ["call", "c"]:
        greeks['rho'] = K * T * np.exp(-r * T) * N_d2 / 100.0
    elif opt_type_lower in ["put", "p"]:
        N_minus_d2 = norm.cdf(-d2_val) # N(-d2)
        greeks['rho'] = -K * T * np.exp(-r * T) * N_minus_d2 / 100.0
    else: # Should not happen
        greeks['rho'] = np.nan

    return greeks


def generate_pl_profile_at_front_expiry(
    strategy_legs_data: List[Dict[str, Any]],
    stock_price_range: np.ndarray,
    front_month_exp_datetime: datetime.datetime,
    back_month_exp_datetime: datetime.datetime,
    risk_free_rate: float,
    assumed_iv_for_back_leg_at_front_expiry: float,
    status_callback: Optional[Callable[[Dict[str, Any]], None]] = None
) -> Optional[Dict[str, Any]]:
    """
    Calculates the P&L profile for a multi-leg option strategy (e.g., calendar spread)
    at the moment of the earliest (front-month) expiration.

    Args:
        strategy_legs_data: List of dicts, each describing an option leg.
            Required keys: 'strike' (float), 'type' (str, 'C'/'P'), 
                           'action' (str, 'BUY'/'SELL'), 'quantity' (int), 
                           'initial_price' (float, per share), 
                           'expiry' (str, "YYYYMMDD").
        stock_price_range: Numpy array of underlying stock prices at front-month expiration
                           for which to calculate P&L.
        front_month_exp_datetime: datetime.datetime object of the front month's expiration.
                                  This is the point in time for P&L calculation.
        back_month_exp_datetime: datetime.datetime object of the back month's expiration.
                                 Used to determine remaining time for back legs.
        risk_free_rate: Annualized risk-free interest rate (e.g., 0.05 for 5%).
        assumed_iv_for_back_leg_at_front_expiry: The assumed annualized implied volatility
                                                 for any back-month legs at the moment the
                                                 front-month leg(s) expire.
        status_callback: Optional callback function for sending status updates,
                         e.g., to a GUI. Expects a dict payload.

    Returns:
        A dictionary containing:
            'stock_prices': List of stock prices used for the profile.
            'pnl_values': List of corresponding P&L values.
            'total_debit': The net cost to establish the spread.
            'max_potential_profit': Maximum profit found within the given stock price range.
            'breakeven_points': List of estimated stock prices where P&L is zero.
        Returns None if a critical error occurs during calculation.
    """
    module_name_for_callback = "FinancialCalculations_PL" 
    def _log_status_fc(msg_type: str, message: str):
        """Internal helper for logging and status callback."""
        if status_callback:
            status_callback({"module": module_name_for_callback, "type": msg_type, "message": message})
        
        # Also log to module logger
        if msg_type == "error": logger_fc.error(message)
        elif msg_type == "warning": logger_fc.warning(message)
        elif msg_type == "debug": logger_fc.debug(message)
        else: logger_fc.info(message)

    _log_status_fc("info", "Calculating P&L profile for spread strategy...")

    if not strategy_legs_data:
        _log_status_fc("error", "No strategy legs provided for P&L calculation.")
        return None
    if not isinstance(stock_price_range, np.ndarray) or stock_price_range.ndim != 1 or stock_price_range.size == 0:
        _log_status_fc("error", "stock_price_range must be a non-empty 1D numpy array.")
        return None


    total_initial_cost = 0.0 # Can be debit (positive) or credit (negative)
    parsed_legs = []

    for i, leg_data in enumerate(strategy_legs_data):
        try:
            strike = float(leg_data['strike'])
            opt_type = str(leg_data['type']).upper()
            action = str(leg_data['action']).upper()
            quantity = int(leg_data.get('quantity', 1))
            initial_price = float(leg_data['initial_price'])
            expiry_str = str(leg_data['expiry']) # YYYYMMDD

            if opt_type not in ['C', 'P']:
                _log_status_fc("error", f"Invalid option type '{opt_type}' for leg {i}.")
                return None
            if action not in ['BUY', 'SELL']:
                _log_status_fc("error", f"Invalid action '{action}' for leg {i}.")
                return None
            if quantity <= 0:
                _log_status_fc("error", f"Quantity must be positive for leg {i}, got {quantity}.")
                return None

            cost_of_leg = initial_price * quantity * 100 # Standard 100 multiplier

            if action == 'BUY':
                total_initial_cost += cost_of_leg
            elif action == 'SELL':
                total_initial_cost -= cost_of_leg
            
            parsed_legs.append({
                'strike': strike,
                'type': opt_type,
                'action': action,
                'quantity': quantity,
                'expiry_dt': datetime.datetime.strptime(expiry_str, "%Y%m%d") # Store as datetime
            })
        except (KeyError, ValueError, TypeError) as e:
            _log_status_fc("error", f"Missing, invalid, or wrong type of data for leg {i}: {e}. Leg data: {leg_data}")
            return None
    
    pnl_values_list = []

    # Ensure naive datetime objects for comparison if timezone info is present but not consistent
    # The calculation point is precisely at front_month_exp_datetime
    eval_datetime_naive = front_month_exp_datetime.replace(tzinfo=None) if front_month_exp_datetime.tzinfo else front_month_exp_datetime
    
    # Calculate TTE for the back leg from the perspective of the front leg's expiry
    # This is the time remaining for the back leg when the front leg expires.
    T_remaining_back_leg = 0.0
    if back_month_exp_datetime > front_month_exp_datetime:
        bm_exp_dt_naive = back_month_exp_datetime.replace(tzinfo=None) if back_month_exp_datetime.tzinfo else back_month_exp_datetime
        time_diff_seconds = (bm_exp_dt_naive - eval_datetime_naive).total_seconds()
        # Consider a full day for TTE if expiring on the same day but later time, or future days.
        # If precisely at expiry, TTE is effectively zero unless there's an intraday component not modeled here.
        # For simplicity, if bm_exp_dt_naive is on the same day as eval_datetime_naive, TTE is near zero.
        # If it's a future day, calculate days / 365.25
        if time_diff_seconds > 0 : # Back month expires after front month evaluation point
             # More precise TTE using total_seconds for partial days, though typically whole days are used for DTE.
             # For options pricing, often DTE/365 is used. If front_month_exp_datetime is EOD, then it's (days_diff)/365
             # Let's assume front_month_exp_datetime is the exact moment of expiry.
            T_remaining_back_leg = max(0.0, time_diff_seconds / (365.25 * 24 * 60 * 60))

    elif back_month_exp_datetime < front_month_exp_datetime:
        _log_status_fc("error", "Back month expiry is before front month expiry. Invalid for calendar-like spread P&L at front expiry.")
        return None
    # If back_month_exp_datetime == front_month_exp_datetime, T_remaining_back_leg remains 0.0

    _log_status_fc("debug", f"Time remaining for back leg at front expiry: {T_remaining_back_leg:.4f} years.")

    for S_at_expiry in stock_price_range:
        value_of_position_at_front_expiry = 0.0
        for leg in parsed_legs:
            K_leg = leg['strike']
            opt_type_leg = leg['type']
            action_leg = leg['action']
            qty_leg = leg['quantity']
            multiplier = 100 

            leg_val_at_front_exp = 0.0

            # If the leg's expiry is on or before the front month's evaluation datetime
            if leg['expiry_dt'].date() <= eval_datetime_naive.date():
                # This leg expires at or before the P&L calculation point. Its value is intrinsic.
                if opt_type_leg == 'C':
                    leg_val_at_front_exp = max(0, S_at_expiry - K_leg)
                elif opt_type_leg == 'P':
                    leg_val_at_front_exp = max(0, K_leg - S_at_expiry)
            else: # This is a longer-dated leg (back-month leg)
                if T_remaining_back_leg > 1e-9: # If there's significant time left
                    # Value it using Black-Scholes with the assumed IV and remaining TTE
                    # Ensure S_at_expiry is used as the underlying price for this BS calculation
                    bs_price_back_leg = black_scholes_price(
                        S=S_at_expiry, K=K_leg, T=T_remaining_back_leg,
                        r=risk_free_rate, sigma=assumed_iv_for_back_leg_at_front_expiry,
                        option_type=opt_type_leg
                    )
                    if np.isnan(bs_price_back_leg):
                        _log_status_fc("warning", f"BS price for back leg (S={S_at_expiry}, K={K_leg}, T={T_remaining_back_leg:.4f}, IV={assumed_iv_for_back_leg_at_front_expiry:.3f}) returned NaN. Assuming 0 value for this leg at this stock price.")
                        leg_val_at_front_exp = 0.0 # Default to 0 if BS fails
                    else:
                        leg_val_at_front_exp = bs_price_back_leg
                else: # No significant time left for the back leg either (e.g., T_remaining_back_leg is 0)
                     if opt_type_leg == 'C': leg_val_at_front_exp = max(0, S_at_expiry - K_leg)
                     elif opt_type_leg == 'P': leg_val_at_front_exp = max(0, K_leg - S_at_expiry)
            
            # Add or subtract leg value based on action (BUY/SELL)
            if action_leg == 'BUY':
                value_of_position_at_front_expiry += leg_val_at_front_exp * qty_leg * multiplier
            elif action_leg == 'SELL':
                value_of_position_at_front_expiry -= leg_val_at_front_exp * qty_leg * multiplier
        
        pnl_at_s = value_of_position_at_front_expiry - total_initial_cost
        pnl_values_list.append(pnl_at_s)

    pnl_values_np = np.array(pnl_values_list)
    max_potential_profit = np.max(pnl_values_np) if pnl_values_np.size > 0 else 0.0
    
    # Calculate breakeven points by finding where P&L crosses zero
    breakeven_points = []
    if pnl_values_np.size > 1 and stock_price_range.size == pnl_values_np.size:
        for i in range(len(stock_price_range) - 1):
            pnl1, pnl2 = pnl_values_np[i], pnl_values_np[i+1]
            s1, s2 = stock_price_range[i], stock_price_range[i+1]
            
            # Check if P&L crosses zero between s1 and s2
            if (pnl1 < 0 and pnl2 >= 0) or (pnl1 >= 0 and pnl2 < 0):
                if abs(pnl2 - pnl1) > 1e-9: # Avoid division by zero if P&L is flat
                    # Linear interpolation to find the stock price at P&L = 0
                    breakeven_stock_price = s1 - pnl1 * (s2 - s1) / (pnl2 - pnl1)
                    breakeven_points.append(breakeven_stock_price)
                elif abs(pnl1) < 1e-9 : # pnl1 is (close to) zero
                    breakeven_points.append(s1)
                # (pnl2 being zero is caught by the next iteration's pnl1)

    _log_status_fc("info", f"P&L profile calculated. Initial Cost: {total_initial_cost:.2f}, Max Profit (in range): {max_potential_profit:.2f}")
    return {
        "stock_prices": stock_price_range.tolist(), # Convert numpy array to list for JSON compatibility if needed
        "pnl_values": pnl_values_np.tolist(),
        "total_initial_cost": total_initial_cost, # Renamed from total_debit for clarity (can be credit)
        "max_potential_profit": max_potential_profit,
        "breakeven_points": sorted(list(set(bp for bp in breakeven_points if not np.isnan(bp)))) # Remove NaNs and duplicates
    }
