
import os
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
# It's a good practice to use environment variables for sensitive data like API keys
ALPACA_KEY = os.environ.get('ALPACA_KEY')
ALPACA_SECRET = os.environ.get('ALPACA_SECRET')

def get_tqqq_price():
    """
    Connects to Alpaca, fetches the latest price for TQQQ, and returns it.

    Returns:
        float: The last price of TQQQ, or None if an error occurs.
    """
    if not ALPACA_KEY or not ALPACA_SECRET:
        print("Error: ALPACA_KEY and ALPACA_SECRET environment variables must be set.")
        return None

    # Create a data client
    data_client = StockHistoricalDataClient(ALPACA_KEY, ALPACA_SECRET)

    # Ticker symbol for TQQQ
    tqqq_symbol = "TQQQ"

    try:
        # Prepare the request for the latest quote
        request_params = StockLatestQuoteRequest(symbol_or_symbols=tqqq_symbol)

        # Get the latest quote
        latest_quote = data_client.get_stock_latest_quote(request_params)

        # Extract the ask price (or bid price, depending on your strategy)
        if latest_quote and tqqq_symbol in latest_quote:
            return latest_quote[tqqq_symbol].ask_price

        return None

    except Exception as e:
        print(f"Error fetching price from Alpaca: {e}")
        return None

if __name__ == '__main__':
    # Example of how to use the function
    # Make sure to set your environment variables before running this
    # export ALPACA_KEY="YOUR_KEY"
    # export ALPACA_SECRET="YOUR_SECRET"
    price = get_tqqq_price()
    if price is not None:
        print(f"The latest price of TQQQ is: {price}")
    else:
        print("Failed to get the price of TQQQ.")
