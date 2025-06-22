# config/polygon_config.py
# This file contains configuration for the Polygon.io API.

# --- Polygon API Configuration ---
# IMPORTANT: Ensure POLYGON_API_KEY is your actual Polygon.io API key.
# For security, consider using environment variables for API keys in production
# or shared environments.
POLYGON_API_KEY = "enter your api key here" # Replace with your key if different

# This value will be used by modules interacting with the Polygon API.
POLYGON_API_DELAY_SECONDS = 1.00  # Adjust as needed based on your API plan.

# You can add other Polygon-specific settings here if needed, for example:
# POLYGON_BASE_URL = "https://api.polygon.io"

# Note: The if __name__ == '__main__': block for printing and basic validation
# has been moved to test_files/test_config_verification.py
