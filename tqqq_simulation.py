import pandas as pd
import sqlite3
import logging

# --- Configuration ---
LOTS_CSV_FILE = 'tqqq_trading_strategy - lots.csv.csv'
INITIAL_CAPITAL = 150000.0
PROFIT_TARGET_PERCENT = 1.01
BUY_TRIGGER_PERCENT = 0.99
SYNTHETIC_DATA_DB = 'synthetic_data.sqlite'

logging.basicConfig(level=logging.INFO, format='%(message)s')
log = logging.getLogger()

def load_lot_map(path):
    try:
        df = pd.read_csv(path, header=None, names=['level', 'shares_to_buy'])
        return df
    except Exception as e:
        log.error(f"Error loading lot map: {e}")
        return None

def load_synthetic_data(db_path):
    log.info(f"Loading synthetic data from '{db_path}'...")
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("SELECT * FROM minute_bars ORDER BY timestamp ASC", conn)
        conn.close()
        log.info(f"Successfully loaded {len(df)} synthetic data points.")
        return df
    except Exception as e:
        log.error(f"Failed to load synthetic data: {e}")
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

    def attempt_buy(self, current_price):
        if self.current_reference_price is None:
            # This should not happen if initial price is set, but as a fallback
            shares_to_buy = self.get_shares_for_level(0)
            cost = shares_to_buy * current_price
            if self.cash >= cost:
                self._execute_buy(current_price, shares_to_buy, 0)
                self.current_reference_price = current_price
                self.next_buy_level = 1
                return True
        elif current_price <= self.current_reference_price * BUY_TRIGGER_PERCENT:
            shares_to_buy = self.get_shares_for_level(self.next_buy_level)
            cost = shares_to_buy * current_price
            if self.cash >= cost:
                self._execute_buy(current_price, shares_to_buy, self.next_buy_level)
                self.current_reference_price = current_price
                self.next_buy_level += 1
                return True
        return False

    def _execute_buy(self, price, quantity, level):
        raise NotImplementedError("Subclasses must implement _execute_buy")

    def attempt_sell(self, current_price):
        raise NotImplementedError("Subclasses must implement _attempt_sell")

    def calculate_final_value(self, final_price):
        unrealized_pnl = 0.0
        if self.shares > 0:
            if isinstance(self, USPortfolio):
                for lot in self.open_lots:
                    unrealized_pnl += (final_price - lot['buy_price']) * lot['quantity']
            elif isinstance(self, CanadianPortfolio):
                unrealized_pnl = (final_price - self.average_cost()) * self.shares
        
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

    def attempt_sell(self, current_price):
        if not self.open_lots: return False
        lot_to_sell = self.open_lots[0] # FIFO
        if current_price >= lot_to_sell['buy_price'] * PROFIT_TARGET_PERCENT:
            profit = (current_price - lot_to_sell['buy_price']) * lot_to_sell['quantity']
            self.cash += current_price * lot_to_sell['quantity']
            self.shares -= lot_to_sell['quantity']
            self.total_realized_pnl += profit
            self.open_lots.pop(0)
            self.trades_executed += 1
            return True
        return False

class CanadianPortfolio(Portfolio):
    def __init__(self, initial_capital, lot_map_df):
        super().__init__(initial_capital, lot_map_df, name="Canadian Average Cost")
        self.total_cost = 0.0

    def _execute_buy(self, price, quantity, level):
        self.cash -= price * quantity
        self.shares += quantity
        self.total_cost += price * quantity
        self.open_lots.append({'buy_price': price, 'quantity': quantity, 'level': level})

    def average_cost(self):
        if self.shares == 0: return 0.0
        return self.total_cost / self.shares

    def attempt_sell(self, current_price):
        if not self.open_lots: return False
        lot_to_sell = self.open_lots[0] # FIFO trigger
        if current_price >= lot_to_sell['buy_price'] * PROFIT_TARGET_PERCENT:
            quantity_to_sell = lot_to_sell['quantity']
            if self.shares < quantity_to_sell:
                quantity_to_sell = self.shares
                if quantity_to_sell == 0: return False
            
            avg_cost_at_sale = self.average_cost()
            realized_pnl = (current_price - avg_cost_at_sale) * quantity_to_sell
            
            self.cash += current_price * quantity_to_sell
            self.shares -= quantity_to_sell
            self.total_cost -= avg_cost_at_sale * quantity_to_sell
            self.total_realized_pnl += realized_pnl
            self.open_lots.pop(0)
            self.trades_executed += 1
            return True
        return False

def run_simulation():
    lot_map_df = load_lot_map(LOTS_CSV_FILE)
    if lot_map_df is None: return

    synthetic_data = load_synthetic_data(SYNTHETIC_DATA_DB)
    if synthetic_data is None or synthetic_data.empty: return

    us_portfolio = USPortfolio(INITIAL_CAPITAL, lot_map_df)
    ca_portfolio = CanadianPortfolio(INITIAL_CAPITAL, lot_map_df)

    # Set the starting price for the simulation
    initial_price = 102.81
    us_portfolio.current_reference_price = initial_price
    ca_portfolio.current_reference_price = initial_price
    log.info(f"Starting simulation with initial reference price: {initial_price:.2f}")

    log.info(f"Running simulation over {len(synthetic_data)} synthetic 1-minute bars...")

    for index, row in synthetic_data.iterrows():
        current_price = row['close']
        
        us_portfolio.attempt_buy(current_price)
        us_portfolio.attempt_sell(current_price)
        
        ca_portfolio.attempt_buy(current_price)
        ca_portfolio.attempt_sell(current_price)

    log.info("\n--- Simulation Results ---")
    final_price = synthetic_data['close'].iloc[-1]

    us_final_value, us_total_pnl, us_unrealized_pnl = us_portfolio.calculate_final_value(final_price)
    ca_final_value, ca_total_pnl, ca_unrealized_pnl = ca_portfolio.calculate_final_value(final_price)

    log.info(f"US Portfolio ({us_portfolio.name}):")
    log.info(f"  Final Portfolio Value: {us_final_value:.2f}")
    log.info(f"  Total PnL (Realized + Unrealized): {us_total_pnl:.2f}")
    log.info(f"  Trades Executed (Buy-Sell Cycles): {us_portfolio.trades_executed}")

    log.info(f"\nCanadian Portfolio ({ca_portfolio.name}):")
    log.info(f"  Final Portfolio Value: {ca_final_value:.2f}")
    log.info(f"  Total PnL (Realized + Unrealized): {ca_total_pnl:.2f}")
    log.info(f"  Trades Executed (Buy-Sell Cycles): {ca_portfolio.trades_executed}")

if __name__ == '__main__':
    run_simulation()
