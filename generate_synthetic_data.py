import sqlite3
import pandas as pd
import numpy as np
import logging

# --- Configuration ---
SOURCE_DAILY_DB = 'daily_data.sqlite'
SOURCE_SAMPLE_CSV = 'frd_sample_etf_TQQQ/TQQQ_1min_sample.csv'
TARGET_SYNTHETIC_DB = 'synthetic_data.sqlite'
TRADING_MINUTES_PER_DAY = 390  # 6.5 hours * 60 minutes

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger()

def analyze_intraday_patterns(sample_file):
    """Analyzes the 1-minute sample data to find the typical volatility."""
    log.info(f"Analyzing intraday patterns from '{sample_file}'...")
    try:
        df = pd.read_csv(sample_file)
        # Calculate minute-to-minute percentage change
        df['pct_change'] = df['close'].pct_change()
        # Get the standard deviation of these changes, which is our volatility measure
        volatility = df['pct_change'].std()
        log.info(f"Calculated intraday 1-min volatility (std dev): {volatility:.6f}")
        return volatility
    except Exception as e:
        log.error(f"Failed to analyze sample data: {e}")
        return None

def generate_constrained_random_walk(start, end, high, low, steps, volatility):
    """Generates a random walk constrained by O, H, L, C values."""
    if steps <= 1:
        return np.array([start, end])

    # Generate a random path and scale it by the learned volatility
    random_steps = np.random.randn(steps) * volatility
    path = start + np.cumsum(random_steps)

    # Adjust the path to ensure it respects the High and Low
    path = np.clip(path, low, high)

    # Pin the path to the start and end points
    path[0] = start
    # Linearly adjust the entire path to meet the closing price
    drift = np.linspace(0, end - path[-1], steps)
    path += drift
    
    # One final clip to ensure H/L are respected after the drift
    path = np.clip(path, low, high)
    path[-1] = end # Ensure the last point is exactly the close

    return np.round(path, 2)

def generate_and_store_synthetic_data(volatility_model):
    """Reads daily data, generates synthetic data, and stores it."""
    log.info(f"Reading daily data from '{SOURCE_DAILY_DB}'...")
    try:
        conn_source = sqlite3.connect(SOURCE_DAILY_DB)
        daily_df = pd.read_sql_query("SELECT * FROM daily_bars ORDER BY timestamp ASC", conn_source)
        conn_source.close()
        log.info(f"Read {len(daily_df)} daily bars.")
    except Exception as e:
        log.error(f"Failed to read from source database: {e}")
        return

    all_synthetic_data = []
    log.info("Generating synthetic intraday data... (this will take several minutes)")

    for index, row in daily_df.iterrows():
        open_price, high_price, low_price, close_price = row['open'], row['high'], row['low'], row['close']
        
        intraday_path = generate_constrained_random_walk(
            open_price, close_price, high_price, low_price, 
            TRADING_MINUTES_PER_DAY, volatility_model
        )
        
        day_timestamp = pd.to_datetime(row['timestamp']).date()
        start_time = pd.Timestamp(f'{day_timestamp} 09:30:00')
        timestamps = [start_time + pd.Timedelta(minutes=i) for i in range(TRADING_MINUTES_PER_DAY)]
        
        day_df = pd.DataFrame({'timestamp': timestamps, 'close': intraday_path})
        all_synthetic_data.append(day_df)

    if not all_synthetic_data:
        log.error("No synthetic data was generated.")
        return

    synthetic_df = pd.concat(all_synthetic_data, ignore_index=True)
    log.info(f"Generated a total of {len(synthetic_df)} synthetic 1-minute bars.")

    try:
        log.info(f"Storing synthetic data in '{TARGET_SYNTHETIC_DB}'...")
        conn_target = sqlite3.connect(TARGET_SYNTHETIC_DB)
        synthetic_df.to_sql('minute_bars', conn_target, if_exists='replace', index=False)
        conn_target.close()
        log.info("Synthetic data successfully stored.")
    except Exception as e:
        log.error(f"Failed to store synthetic data: {e}")

if __name__ == '__main__':
    # 1. Analyze the real intraday sample to get a volatility model
    volatility_model = analyze_intraday_patterns(SOURCE_SAMPLE_CSV)
    if volatility_model:
        # 2. Generate the synthetic data based on the model
        generate_and_store_synthetic_data(volatility_model)