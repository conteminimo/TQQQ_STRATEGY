
import pandas as pd
import sqlite3
import logging

# --- Configuration ---
LOTS_CSV_FILE = 'tqqq_trading_strategy - lots.csv.csv'
INITIAL_CAPITAL = 150000.0
PROFIT_TARGET_PERCENT = 1.01
BUY_TRIGGER_PERCENT = 0.99
SYNTHETIC_DATA_DB = 'synthetic_data.sqlite'

# --- Enhanced Logging ---
log_file_handler = logging.FileHandler('simulation_debug.log', mode='w')
log_file_handler.setLevel(logging.DEBUG)
log_file_handler.setFormatter(logging.Formatter('%(message)s'))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO) # Only show summary results on console
console_handler.setFormatter(logging.Formatter('%(message)s'))

logging.basicConfig(level=logging.DEBUG, handlers=[log_file_handler, console_handler])
log = logging.getLogger()

def load_lot_map(path):
    try:
        df = pd.read_csv(path, header=None, names=['level', 'shares_to_buy'])
        return df
    except Exception as e:
        log.error(f"Error loading lot map: {e}")
        return None

def load_data_from_sqlite(db_path, table_name):
    log.info(f"Loading data from table '{table_name}' in '{db_path}'...")
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(f"SELECT * FROM {table_name} ORDER BY timestamp ASC", conn)
        conn.close()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        log.info(f"Successfully loaded {len(df)} data points.")
        return df
    except Exception as e:
        log.error(f"Failed to load data from SQLite: {e}")
        return None

class Portfolio:
    def __init__(self, initial_capital, lot_map_df, name="Generic"):
        self.name = name
        self.cash = initial_capital
        self.shares = 0
        self.lot_map = lot_map_df
        self.trades_executed = 0
        self.total_realized_pnl = 0.0
        self.open_lots = []
        self.next_buy_level = 0
        self.current_reference_price = None
        self.initial_capital = initial_capital

    def get_shares_for_level(self, level):
        if level < len(self.lot_map):
            return self.lot_map.iloc[level]['shares_to_buy']
        return 0

    def attempt_buy(self, current_price, timestamp):
        buy_trigger_price = self.current_reference_price * BUY_TRIGGER_PERCENT
        log.debug(f"[{timestamp}] Attempting BUY for level {self.next_buy_level}. Price: {current_price:.2f}, Trigger: < {buy_trigger_price:.2f}")

        if current_price <= buy_trigger_price:
            shares_to_buy = self.get_shares_for_level(self.next_buy_level)
            if shares_to_buy <= 0:
                log.debug(f"[{timestamp}] -> No shares configured for level {self.next_buy_level}. Skipping buy.")
                return False

            cost = shares_to_buy * current_price
            if self.cash >= cost:
                log.debug(f"[{timestamp}] -> SUCCESS: Executing BUY of {shares_to_buy} shares @ {current_price:.2f}")
                self._execute_buy(current_price, shares_to_buy, self.next_buy_level)
                self.current_reference_price = current_price
                self.next_buy_level += 1
                return True
            else:
                log.debug(f"[{timestamp}] -> FAIL: Insufficient cash. Needed: {cost:.2f}, Have: {self.cash:.2f}")
        return False

    def _execute_buy(self, price, quantity, level):
        raise NotImplementedError("Subclasses must implement _execute_buy")

    def attempt_sell(self, current_price, timestamp):
        raise NotImplementedError("Subclasses must implement _attempt_sell")

    def calculate_final_value(self, final_price):
        unrealized_pnl = 0.0
        if self.shares > 0:
            if isinstance(self, USPortfolio):
                for lot in self.open_lots:
                    unrealized_pnl += (final_price - lot['buy_price']) * lot['quantity']
        
        total_pnl = self.total_realized_pnl + unrealized_pnl
        final_portfolio_value = self.cash + (self.shares * final_price)
        return final_portfolio_value, total_pnl, unrealized_pnl

class USPortfolio(Portfolio):
    def __init__(self, initial_capital, lot_map_df):
        super().__init__(initial_capital, lot_map_df, name="US Specific-Lot")

    def _execute_buy(self, price, quantity, level):
        self.cash -= price * quantity
        self.shares += quantity
        self.open_lots.append({'buy_price': price, 'quantity': quantity, 'level': level})

    def attempt_sell(self, current_price, timestamp):
        if not self.open_lots: return False
        
        lot_to_sell = self.open_lots[0] # FIFO
        sell_target_price = lot_to_sell['buy_price'] * PROFIT_TARGET_PERCENT
        log.debug(f"[{timestamp}] Attempting SELL for lot bought at {lot_to_sell['buy_price']:.2f}. Price: {current_price:.2f}, Target: > {sell_target_price:.2f}")

        if current_price >= sell_target_price:
            profit = (current_price - lot_to_sell['buy_price']) * lot_to_sell['quantity']
            log.debug(f"[{timestamp}] -> SUCCESS: Executing SELL of {lot_to_sell['quantity']} shares @ {current_price:.2f} for a profit of {profit:.2f}")
            self.cash += current_price * lot_to_sell['quantity']
            self.shares -= lot_to_sell['quantity']
            self.total_realized_pnl += profit
            self.open_lots.pop(0)
            self.trades_executed += 1
            return True
        return False

def run_simulation():
    lot_map_df = load_lot_map(LOTS_CSV_FILE)
    if lot_map_df is None: return

    # Load data from the new SQLite database
    data_df = load_data_from_sqlite('unadjusted_market_data.sqlite', 'tqqq_1min_unadjusted')
    if data_df is None or data_df.empty: return

    us_portfolio = USPortfolio(INITIAL_CAPITAL, lot_map_df)

    # Set the starting price from the first row of the data
    initial_price = data_df['close'].iloc[0]
    us_portfolio.current_reference_price = initial_price
    log.info(f"Starting simulation with initial reference price: {initial_price:.2f}")
    log.info(f"Detailed log will be written to simulation_debug.log")

    log.info(f"Running simulation over {len(data_df)} 1-minute bars...")

    for index, row in data_df.iterrows():
        current_price = row['close']
        timestamp = row['timestamp']
        
        us_portfolio.attempt_buy(current_price, timestamp)
        us_portfolio.attempt_sell(current_price, timestamp)

    log.info("\n--- Simulation Results ---")
    final_price = data_df['close'].iloc[-1]

    us_final_value, us_total_pnl, us_unrealized_pnl = us_portfolio.calculate_final_value(final_price)

    log.info(f"US Portfolio ({us_portfolio.name}):")
    log.info(f"  Final Portfolio Value: {us_final_value:.2f}")
    log.info(f"  Total PnL (Realized + Unrealized): {us_total_pnl:.2f}")
    log.info(f"  Trades Executed (Buy-Sell Cycles): {us_portfolio.trades_executed}")

if __name__ == '__main__':
    run_simulation()
