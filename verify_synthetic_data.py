import sqlite3
import pandas as pd
from datetime import timedelta
import logging
import numpy as np

# --- Configuration ---
DAILY_DB = 'daily_data.sqlite'
SYNTHETIC_DB = 'synthetic_data.sqlite'
TRADING_MINUTES_PER_DAY = 390

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger()

def get_db_connection(db_file):
    """Helper to get a database connection."""
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn

def verify_data():
    log.info("--- Starting Synthetic Data Verification ---")

    # 1. Load Daily Data
    try:
        conn_daily = get_db_connection(DAILY_DB)
        daily_df = pd.read_sql_query("SELECT * FROM daily_bars ORDER BY timestamp ASC", conn_daily)
        conn_daily.close()
        daily_df['timestamp'] = pd.to_datetime(daily_df['timestamp'])
        log.info(f"Loaded {len(daily_df)} daily bars from {DAILY_DB}.")
    except Exception as e:
        log.error(f"Failed to load daily data: {e}")
        return False

    # 2. Load Synthetic Data
    try:
        conn_synthetic = get_db_connection(SYNTHETIC_DB)
        synthetic_df = pd.read_sql_query("SELECT * FROM minute_bars ORDER BY timestamp ASC", conn_synthetic)
        conn_synthetic.close()
        synthetic_df['timestamp'] = pd.to_datetime(synthetic_df['timestamp'])
        log.info(f"Loaded {len(synthetic_df)} synthetic 1-minute bars from {SYNTHETIC_DB}.")
    except Exception as e:
        log.error(f"Failed to load synthetic data: {e}")
        return False

    if daily_df.empty or synthetic_df.empty:
        log.error("One or both dataframes are empty. Cannot verify.")
        return False

    # 3. Check Date Range
    daily_start = daily_df['timestamp'].min().date()
    daily_end = daily_df['timestamp'].max().date()
    synthetic_start = synthetic_df['timestamp'].min().date()
    synthetic_end = synthetic_df['timestamp'].max().date()

    log.info(f"Daily Data Range: {daily_start} to {daily_end}")
    log.info(f"Synthetic Data Range: {synthetic_start} to {synthetic_end}")

    if daily_start != synthetic_start or daily_end != synthetic_end:
        log.warning("Date range mismatch between daily and synthetic data. This might be expected if daily data covers non-trading days.")
    else:
        log.info("Date ranges match (start and end dates).")

    # 4. Check Granularity (for a sample)
    sample_days = daily_df['timestamp'].dt.date.unique()
    if len(sample_days) > 5:
        sample_days = np.random.choice(sample_days, 5, replace=False)

    granularity_ok = True
    for day in sample_days:
        day_synthetic_data = synthetic_df[synthetic_df['timestamp'].dt.date == day]
        if len(day_synthetic_data) > 1:
            time_diffs = day_synthetic_data['timestamp'].diff().dropna()
            if not (time_diffs == timedelta(minutes=1)).all():
                log.error(f"Granularity check failed for day {day}: Not all bars are 1-minute apart.")
                granularity_ok = False
                break
        if len(day_synthetic_data) != TRADING_MINUTES_PER_DAY:
            log.warning(f"Day {day} has {len(day_synthetic_data)} bars, expected {TRADING_MINUTES_PER_DAY}. (Might be due to holidays/partial days)")

    if granularity_ok:
        log.info("Granularity check passed for sampled days (1-minute intervals).")

    # 5. Check O/H/L/C Constraints (for a sample)
    constraints_ok = True
    for _, daily_row in daily_df.sample(min(5, len(daily_df))).iterrows():
        day = daily_row['timestamp'].date()
        synthetic_day_data = synthetic_df[synthetic_df['timestamp'].dt.date == day]

        if synthetic_day_data.empty:
            log.warning(f"No synthetic data found for daily bar on {day}. Skipping constraint check for this day.")
            continue

        synthetic_open = synthetic_day_data['close'].iloc[0]
        synthetic_close = synthetic_day_data['close'].iloc[-1]
        synthetic_high = synthetic_day_data['close'].max()
        synthetic_low = synthetic_day_data['close'].min()

        if not np.isclose(synthetic_open, daily_row['open'], atol=0.01):
            log.error(f"Day {day}: Synthetic Open ({synthetic_open:.2f}) != Daily Open ({daily_row['open']:.2f})")
            constraints_ok = False
        if not np.isclose(synthetic_close, daily_row['close'], atol=0.01):
            log.error(f"Day {day}: Synthetic Close ({synthetic_close:.2f}) != Daily Close ({daily_row['close']:.2f})")
            constraints_ok = False
        if synthetic_high > daily_row['high'] + 0.01:
            log.error(f"Day {day}: Synthetic High ({synthetic_high:.2f}) > Daily High ({daily_row['high']:.2f})")
            constraints_ok = False
        if synthetic_low < daily_row['low'] - 0.01:
            log.error(f"Day {day}: Synthetic Low ({synthetic_low:.2f}) < Daily Low ({daily_row['low']:.2f})")
            constraints_ok = False

        if not constraints_ok:
            log.info(f"  Daily OHL: {daily_row['open']:.2f}/{daily_row['high']:.2f}/{daily_row['low']:.2f}/{daily_row['close']:.2f}")
            log.info(f"  Synth OHL: {synthetic_open:.2f}/{synthetic_high:.2f}/{synthetic_low:.2f}/{synthetic_close:.2f}")

    if constraints_ok:
        log.info("OHLC constraints check passed for sampled days.")
    else:
        log.error("OHLC constraints check FAILED for one or more sampled days.")

    log.info("--- Synthetic Data Verification Complete ---")
    return constraints_ok and granularity_ok

if __name__ == '__main__':
    verify_data()
