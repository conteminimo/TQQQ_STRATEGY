import sqlite3
import logging
from tvDatafeed import TvDatafeed, Interval

# --- Configuration ---
SYMBOL = "TQQQ"
EXCHANGE = "NASDAQ"
DB_FILE = 'daily_data.sqlite'
NUM_BARS_TO_FETCH = 5000 # Max for free user, provides many years of daily data

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger()

def setup_database():
    """Creates the database and the daily_bars table."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_bars (
            timestamp TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL
        );
    ''')
    conn.commit()
    conn.close()
    log.info(f"Database '{DB_FILE}' and table 'daily_bars' are ready.")

def download_and_store_data():
    """Fetches daily historical data and stores it in the SQLite database."""
    setup_database()
    
    try:
        tv = TvDatafeed()
        log.info(f"Fetching {NUM_BARS_TO_FETCH} daily bars for {SYMBOL} from {EXCHANGE}...")
        data = tv.get_hist(symbol=SYMBOL, exchange=EXCHANGE, interval=Interval.in_daily, n_bars=NUM_BARS_TO_FETCH)
        
        if data is None or data.empty:
            log.error("Failed to fetch historical data.")
            return

        log.info(f"Successfully fetched {len(data)} bars. Storing in database...")
        
        # Prepare data for insertion
        data.reset_index(inplace=True)
        data.rename(columns={'datetime': 'timestamp'}, inplace=True)
        data['timestamp'] = data['timestamp'].astype(str)

        conn = sqlite3.connect(DB_FILE)
        data.to_sql('daily_bars', conn, if_exists='replace', index=False)
        conn.close()
        
        log.info("Data successfully stored in 'daily_data.sqlite'.")

    except Exception as e:
        log.error(f"An error occurred: {e}")

if __name__ == '__main__':
    download_and_store_data()
