# utils/polygon_utils.py
import datetime # Retained for potential future utility functions

def format_polygon_option_symbol(underlying_ticker: str, expiration_date_str: str, option_type: str, strike_price: float) -> str:
    """
    Formats an option symbol into the standard Polygon.io format.
    Example: underlying_ticker="AAPL", expiration_date_str="250117",
             option_type="C", strike_price=170.0
             returns "O:AAPL250117C00170000"

    Args:
        underlying_ticker (str): The stock ticker (e.g., "AAPL"). Must be non-empty.
        expiration_date_str (str): Expiration date in "YYMMDD" format (e.g., "250117" for Jan 17, 2025).
                                   Must be a 6-digit string.
        option_type (str): 'C' for Call or 'P' for Put. Case-insensitive. Must be a string.
        strike_price (float): The strike price of the option. Must be a positive number.

    Returns:
        str: The formatted Polygon.io option symbol.

    Raises:
        ValueError: If any input parameters are invalid (e.g., incorrect format, type, or value).
        TypeError: If input parameters have an incorrect type that leads to an operation error.
    """
    if not (isinstance(underlying_ticker, str) and underlying_ticker.strip()): # Ensure not just whitespace
        raise ValueError("Underlying ticker must be a non-empty string.")
    
    if not (isinstance(expiration_date_str, str) and len(expiration_date_str) == 6 and expiration_date_str.isdigit()):
        raise ValueError(f"Expiration date string must be 6 digits (YYMMDD), got: '{expiration_date_str}'")
    
    # Add type check for option_type before calling .upper()
    if not isinstance(option_type, str):
        raise ValueError(f"Option type must be a string ('C' or 'P'), got type: {type(option_type)}")
        
    processed_option_type = option_type.upper()
    if processed_option_type not in ['C', 'P']:
        raise ValueError(f"Option type must be 'C' or 'P', got: '{option_type}'")
    
    if not isinstance(strike_price, (int, float)) or strike_price <= 0:
        raise ValueError(f"Strike price must be a positive number, got: {strike_price}")

    # Polygon.io requires the strike price to be an 8-digit integer representing the price * 1000.
    # Example: 150.0 -> 150000 -> "00150000"
    # Example: 150.5 -> 150500 -> "00150500"
    strike_as_int_scaled = int(strike_price * 1000)
    strike_formatted = str(strike_as_int_scaled).zfill(8)
    
    # Construct the symbol: O:{TICKER}{YYMMDD}{C/P}{STRIKE*1000, 8 digits}
    return f"O:{underlying_ticker.upper().strip()}{expiration_date_str}{processed_option_type}{strike_formatted}"

# The __main__ block has been removed and will be placed in a separate test file:
# test_files/test_polygon_utils.py
