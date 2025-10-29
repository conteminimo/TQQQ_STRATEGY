import asyncio
import pandas as pd
from ib_insync import *
import logging
import time
import json
import os
import sys

# --- 1. CONFIGURATION ---
LOTS_CSV_FILE = 'tqqq_trading_strategy - lots.csv.csv'
STATE_FILE = 'bot_state.json'  # File to save open lots
SYMBOL = "TQQQ"
EXCHANGE = "SMART"
CURRENCY = "USD"
PROFIT_TARGET_PERCENT = 1.01  # 1% profit (1.01 multiplier)
BUY_TRIGGER_PERCENT = 0.99  # 1% drop (0.99 multiplier)
POLL_INTERVAL_SEC = 20     # Main loop sleep interval
ORDER_TIMEOUT_SEC = 120    # Max time to wait for the Level 0 order fill
L0_BUY_BUFFER = 1.0025     # 0.25% buffer for Level 0 LMT order
FUTURE_BUY_QUEUE_DEPTH = 3 # Place 3 future conditional orders

# --- IB Connection Config ---
IB_HOST = '127.0.0.1'
IB_PORT = 7497  # 7497 for Paper Trading
IB_CLIENT_ID = 101

# --- Setup Logging (to file and console) ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("bot_log.txt"),
                              logging.StreamHandler()])
log = logging.getLogger()

# --- 8. Critical Alert System (No GUI) ---
def show_critical_alert(title, message):
    """
    Prints a critical error to the log, beeps, and forces shutdown.
    """
    log.critical("=" * 60)
    log.critical(f"CRITICAL ALERT: {title}")
    log.critical(message)
    log.critical("The bot will now SHUT DOWN to prevent damage.")
    log.critical("Please review the logs and perform the Manual Reset Procedure.")
    log.critical("=" * 60)
    
    # Beep the console
    print('\a')
    
    # Cleanly exit the program
    sys.exit(1) # Exit with an error code

class Lot:
    """Class to keep track of each individual purchase."""
    def __init__(self, level, quantity, purchase_price, sell_order_id=None):
        self.level = int(level)
        self.quantity = int(quantity)
        self.purchase_price = float(purchase_price)
        self.sell_target_price = round(float(purchase_price) * PROFIT_TARGET_PERCENT, 2)
        self.sell_order_id = sell_order_id

    def to_dict(self):
        """Converts the object to a dictionary for JSON saving."""
        return self.__dict__

    @staticmethod
    def from_dict(data):
        """Creates a Lot object from a dictionary (loaded from JSON)."""
        return Lot(
            data['level'],
            data['quantity'],
            data['purchase_price'],
            data.get('sell_order_id') # Use .get() for safety
        )

class GridBot:
    def __init__(self, lot_map_path, state_path):
        self.ib = IB()
        self.lot_map = self.load_lot_map(lot_map_path)
        self.state_path = state_path
        self.lot_inventory = self.load_state()  # Already purchased lots
        self.contract = None # Will be qualified in run()
        self.next_level = self.calculate_next_level()
        self.buy_reference_price = self.find_reference_price() # Price of the last buy trigger
        self.processing_lock = asyncio.Lock() # Lock to prevent duplicate processing

        log.info("--- INITIAL STATE ---")
        log.info(f"Next level to buy: {self.next_level}")
        log.info(f"Lots already in inventory: {len(self.lot_inventory)}")
        log.info(f"Last buy trigger price: {self.buy_reference_price}")
        log.info("----------------------")

    # --- 3. File & State Management ---
    def load_lot_map(self, path):
        try:
            df = pd.read_csv(path, header=None, names=['level', 'shares_to_buy'])
            log.info(f"CSV file '{path}' loaded with {len(df)} levels.")
            return df
        except Exception as e:
            log.error(f"Could not read CSV file '{path}': {e}")
            sys.exit(1)

    def load_state(self):
        """Loads the open lot inventory from a JSON file."""
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r') as f:
                    data = json.load(f)
                    log.info(f"Previous state loaded from '{self.state_path}'.")
                    return [Lot.from_dict(d) for d in data]
            except Exception as e:
                log.warning(f"Could not read state file '{self.state_path}': {e}. Starting fresh.")
        return []

    def save_state(self):
        """Saves the current inventory to a JSON file."""
        try:
            with open(self.state_path, 'w') as f:
                json.dump([lot.to_dict() for lot in self.lot_inventory], f, indent=4)
            log.info(f"State successfully saved to '{self.state_path}'.")
        except Exception as e:
            log.error(f"Critical error: Could not save state to '{self.state_path}': {e}")

    def calculate_next_level(self):
        if not self.lot_inventory:
            return 0  # Start from level 0
        open_levels = {lot.level for lot in self.lot_inventory}
        max_open_level = max(open_levels)
        return max_open_level + 1
    
    def find_reference_price(self):
        """Finds the price of the last *trigger*, if it exists."""
        if self.next_level == 0:
            return None # No buys yet
        
        try:
            l0_lot = next(lot for lot in self.lot_inventory if lot.level == 0)
            price = l0_lot.purchase_price
            # Compound down to the last level's TRIGGER PRICE
            for _ in range(self.next_level - 1):
                price = price * BUY_TRIGGER_PERCENT
            return round(price, 2)
        except StopIteration:
            # This should not happen if next_level > 0, but as a safeguard:
            log.warning("Could not find Level 0 lot to calculate reference price. This may cause errors.")
            return None

    # --- 2. Connection ---
    async def connect(self):
        """Attempts to connect to TWS"""
        try:
            log.info(f"Attempting to connect to TWS at {IB_HOST}:{IB_PORT}...")
            await self.ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
            version = self.ib.client.serverVersion()
            log.info(f"Connection to TWS successful. Server Version: {version}")
            
            log.info("Setting market data type to 3 (Delayed)...")
            self.ib.reqMarketDataType(3)
            
            self.contract = Stock(SYMBOL, EXCHANGE, CURRENCY)
            await self.ib.qualifyContractsAsync(self.contract)
            log.info(f"Contract {SYMBOL} qualified.")
            
            return True
        except Exception as e:
            log.error(f"Connection failed: {e}")
            return False

    # --- 7. Reconciliation Check ---
    async def reconcile_state(self):
        """
        Cross-references TWS reality with the local state file.
        Stops the bot with an alert if any mismatch is found.
        """
        log.info("Starting state reconciliation...")
        
        # 1. Check Positions
        log.info("Checking TWS positions...")
        tws_position_qty = 0
        positions = await self.ib.reqPositionsAsync()
        for pos in positions:
            if pos.contract.conId == self.contract.conId:
                tws_position_qty = pos.position
                break
        
        local_position_qty = sum(lot.quantity for lot in self.lot_inventory)
        
        if tws_position_qty != local_position_qty:
            msg = (
                f"POSITION MISMATCH!\n\n"
                f"TWS reports position: {tws_position_qty} {SYMBOL}\n"
                f"Local 'bot_state.json' reports: {local_position_qty} {SYMBOL}\n\n"
                f"To prevent errors, the bot will shut down.\n\n"
                f"MANUAL RESET PROCEDURE:\n"
                f"1. Manually close all open {SYMBOL} positions in TWS.\n"
                f"2. Manually cancel all open {SYMBOL} orders in TWS.\n"
                f"3. Delete the 'bot_state.json' file.\n"
                f"4. Restart the bot."
            )
            show_critical_alert("Reconciliation Failed", msg)

        log.info(f"Position check OK: TWS ({tws_position_qty}) == Local ({local_position_qty})")

        # 2. Check Open Orders (SELLs and BUYs)
        log.info("Checking open orders...")
        tws_open_orders = await self.ib.reqAllOpenOrdersAsync()
        
        # Check SELL Orders
        local_sell_order_ids = {lot.sell_order_id for lot in self.lot_inventory if lot.sell_order_id}
        tws_sell_order_ids = {
            o.orderId for o in tws_open_orders 
            if o.contract.conId == self.contract.conId and o.action == 'SELL'
        }
        
        if local_sell_order_ids != tws_sell_order_ids:
            msg = (
                f"SELL ORDER MISMATCH!\n\n"
                f"Local 'bot_state.json' expects SELL order IDs: {local_sell_order_ids}\n"
                f"TWS reports open SELL order IDs: {tws_sell_order_ids}\n\n"
                f"To prevent errors, the bot will shut down.\n\n"
                f"MANUAL RESET PROCEDURE:\n"
                f"1. Manually close all open {SYMBOL} positions in TWS.\n"
                f"2. Manually cancel all open {SYMBOL} orders in TWS.\n"
                f"3. Delete the 'bot_state.json' file.\n"
                f"4. Restart the bot."
            )
            show_critical_alert("Reconciliation Failed", msg)

        log.info("Open SELL orders check OK.")

        # Check BUY Orders
        expected_buy_triggers = self.calculate_expected_buy_triggers()
        tws_buy_triggers = {
            round(o.lmtPrice, 2) for o in tws_open_orders 
            if o.contract.conId == self.contract.conId and o.action == 'BUY'
        }
        
        if expected_buy_triggers != tws_buy_triggers:
            msg = (
                f"BUY ORDER MISMATCH!\n\n"
                f"Local state expects {FUTURE_BUY_QUEUE_DEPTH} BUY orders at prices: {expected_buy_triggers}\n"
                f"TWS reports open BUY orders at prices: {tws_buy_triggers}\n\n"
                f"To prevent errors, the bot will shut down.\n\n"
                f"MANUAL RESET PROCEDURE:\n"
                f"1. Manually close all open {SYMBOL} positions in TWS.\n"
                f"2. Manually cancel all open {SYMBOL} orders in TWS.\n"
                f"3. Delete the 'bot_state.json' file.\n"
                f"4. Restart the bot."
            )
            show_critical_alert("Reconciliation Failed", msg)
        
        log.info("Open BUY orders check OK.")
        log.info("Reconciliation successful. State is synchronized.")

    def calculate_expected_buy_triggers(self):
        """Calculates the 3 expected future trigger prices."""
        if self.next_level == 0:
            return set() # Expect 0 open orders if L0 not bought
            
        triggers = set()
        price = self.buy_reference_price
        for _ in range(FUTURE_BUY_QUEUE_DEPTH):
            price = round(price * BUY_TRIGGER_PERCENT, 2)
            triggers.add(price)
        return triggers


    # --- 4. & 5. Main Logic Engine ---
    
    async def run(self):
        """Main bot loop."""
        if not await self.connect():
            log.error("Cannot start bot. Connection failed.")
            return
        
        await self.reconcile_state()
        
        # --- V16 FIX: 'fillEvent' -> 'filledEvent' ---
        self.ib.filledEvent += self.on_fill
        log.info("Subscribed to fill events.")

        if self.next_level == 0:
            log.info("Subscribing to market data to trigger Level 0 buy.")
            self.ib.reqMktData(self.contract, '', False, False)
            self.ib.pendingTickersEvent += self.on_pending_ticker
        else:
            log.info("Level 0 already purchased. Waiting for fills on existing orders.")
        
        log.info("Bot started successfully. Monitoring...")

        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL_SEC)
                log.info(f"Bot running... Open lots: {len(self.lot_inventory)}. Next level: {self.next_level}")

        except (KeyboardInterrupt, SystemExit):
            log.info("Manual stop received. Disconnecting...")
        finally:
            # --- V16 FIX: 'fillEvent' -> 'filledEvent' ---
            self.ib.filledEvent -= self.on_fill
            self.ib.pendingTickersEvent -= self.on_pending_ticker
            self.ib.disconnect()
            log.info("Bot disconnected.")

    def on_pending_ticker(self, tickers):
        """
        Callback for price updates.
        ONLY used to trigger the Level 0 buy.
        """
        for ticker in tickers:
            if ticker.contract.conId == self.contract.conId:
                current_price = ticker.last
                if current_price and current_price > 0:
                    log.debug(f"New TQQQ price: {current_price}")
                    if not self.processing_lock.locked() and self.next_level == 0:
                        asyncio.create_task(self.execute_buy_level_0(current_price))

    async def execute_buy_level_0(self, current_price):
        """
        Places the initial Level 0 buy order using an LMT+buffer
        to simulate a Market order that works in pre-market.
        """
        await self.processing_lock.acquire()
        try:
            if self.next_level != 0:
                log.warning("execute_buy_level_0 called, but next_level is not 0. Ignoring.")
                return

            log.info(f"Placing first buy (Level 0) at market price: {current_price}")
            
            quantity = int(self.lot_map.at[0, 'shares_to_buy'])
            limit_price = round(current_price * L0_BUY_BUFFER, 2)
            
            trade = await self.place_and_monitor_order("BUY", quantity, limit_price)
            
            if trade.orderStatus.status == 'Filled':
                log.info(f"Level 0 Buy order (OrderId: {trade.order.orderId}) confirmed as Filled.")
                # The on_fill() event will now take over.
                
                log.info("Unsubscribing from market data ticker.")
                self.ib.pendingTickersEvent -= self.on_pending_ticker
            else:
                log.warning(f"Level 0 Buy order (OrderId: {trade.order.orderId}) failed. Status: {trade.orderStatus.status}. Will retry on next tick.")
                
        finally:
            self.processing_lock.release()

    async def on_fill(self, fill):
        """
        This is the main "engine" of the bot.
        It reacts to all order execution confirmations.
        """
        if fill.contract.conId != self.contract.conId:
            return # Not our contract

        await self.processing_lock.acquire()
        try:
            action = fill.execution.side
            orderId = fill.order.orderId
            quantity = fill.execution.shares
            fill_price = fill.execution.avgPrice
            
            log.info(f"--- FILL RECEIVED ---")
            log.info(f"Action: {action}, OrderId: {orderId}, Qty: {quantity}, Price: {fill_price}")

            if action == "BOT":
                # --- A BUY order was filled ---
                log.info("Processing BUY fill...")
                
                level = self.next_level
                
                # Create the new lot
                new_lot = Lot(level, quantity, fill_price)
                
                # Place its corresponding SELL order
                sell_trade = await self.place_sell_order(new_lot)
                
                # Add the SELL order ID to the lot
                new_lot.sell_order_id = sell_trade.order.orderId
                log.info(f"Placed corresponding SELL order (GTC, +1%) with OrderId: {new_lot.sell_order_id}")
                
                # Add new lot to inventory and save
                self.lot_inventory.append(new_lot)
                self.save_state()
                
                # Update bot's internal state
                self.buy_reference_price = fill_price if level == 0 else round(self.buy_reference_price * BUY_TRIGGER_PERCENT, 2)
                self.next_level += 1
                log.info(f"State updated. New next_level: {self.next_level}. New ref_price: {self.buy_reference_price}")
                
                # Place the next 3 future orders
                await self.place_future_buy_queue()

            elif action == "SLD":
                # --- A SELL order was filled ---
                log.info("Processing SELL fill...")
                
                lot_to_remove = next((lot for lot in self.lot_inventory if lot.sell_order_id == orderId), None)
                
                if lot_to_remove:
                    self.lot_inventory.remove(lot_to_remove)
                    self.save_state()
                    log.info(f"Sell for Level {lot_to_remove.level} confirmed. Lot removed from inventory.")
                else:
                    log.warning(f"Received a SELL fill for OrderId {orderId}, but no matching lot was found in state file!")

        except Exception as e:
            log.error(f"Error in on_fill handler: {e}")
        finally:
            self.processing_lock.release()
            log.info("--- FILL PROCESSING COMPLETE ---")

    async def place_sell_order(self, lot: Lot):
        """
        Places a GTC SELL LMT order for a given lot.
        """
        log.info(f"Placing GTC SELL Limit order for Level {lot.level}: {lot.quantity} shares @ {lot.sell_target_price}")
        order = LimitOrder(
            action='SELL',
            totalQuantity=lot.quantity,
            lmtPrice=lot.sell_target_price,
            Tif='GTC',
            outsideRth=True
        )
        trade = self.ib.placeOrder(self.contract, order)
        await self.ib.sleep(0.1) # Brief pause to ensure order is submitted
        return trade

    async def place_future_buy_queue(self):
        """
        Places the next {FUTURE_BUY_QUEUE_DEPTH} conditional BUY orders.
        """
        log.info(f"Placing next {FUTURE_BUY_QUEUE_DEPTH} conditional BUY orders...")
        
        # This function cancels old orders and places the new queue
        # First, cancel all existing conditional BUY orders
        open_orders = await self.ib.reqAllOpenOrdersAsync()
        for o in open_orders:
            if o.contract.conId == self.contract.conId and o.action == 'BUY':
                log.warning(f"Cancelling old conditional BUY order (Id: {o.orderId}, Price: {o.lmtPrice}) to place new queue.")
                self.ib.cancelOrder(o)
        
        await self.ib.sleep(0.5) # Pause to allow cancellations to process

        # Now, place the new queue
        current_trigger_price = self.buy_reference_price
        
        for i in range(FUTURE_BUY_QUEUE_DEPTH):
            level_to_queue = self.next_level + i
            if level_to_queue >= len(self.lot_map):
                log.info(f"Reached end of lot map. No more future orders to place.")
                break # Stop if we run out of levels
                
            trigger_price = round(current_trigger_price * BUY_TRIGGER_PERCENT, 2)
            quantity = int(self.lot_map.at[level_to_queue, 'shares_to_buy'])
            
            log.info(f"Placing conditional BUY for Level {level_to_queue}: {quantity} shares, Trigger/LMT @ {trigger_price}")
            await self.place_conditional_buy(quantity, trigger_price)
            
            current_trigger_price = trigger_price # Compound for the next loop

    async def place_conditional_buy(self, quantity, trigger_price):
        """Places a single conditional LMT order."""
        try:
            # Create the Limit order
            order = LimitOrder(
                action='BUY',
                totalQuantity=quantity,
                lmtPrice=trigger_price, # LMT price is the same as trigger
                outsideRth=True,
                transmit=False # Do not transmit yet
            )
            
            # Create the Price Condition
            condition = PriceCondition(
                conId=self.contract.conId,
                exchange=self.contract.exchange,
                price=trigger_price,
                isMore=False, # Trigger when price is LESS than or equal
                isConjunction=True
            )
            order.conditions.append(condition)
            
            # Now set transmit to True
            order.transmit = True
            
            # Place the conditional order
            self.ib.placeOrder(self.contract, order)

        except Exception as e:
            log.error(f"Failed to place conditional order for Lvl {self.next_level}: {e}")

    async def place_and_monitor_order(self, action, quantity, limit_price):
        """
        Submits the L0 LMT order and waits for it to be Filled.
        Returns the Trade object.
        """
        order = LimitOrder(action, quantity, limit_price, outsideRth=True)
        trade = self.ib.placeOrder(self.contract, order)
        log.info(f"Order {action} {quantity} {SYMBOL} LMT @ {limit_price} submitted. OrderId: {trade.order.orderId}. Waiting for fill...")
        
        start_time = time.time()
        while trade.orderStatus.status not in ['Filled', 'Cancelled', 'ApiCancelled', 'Inactive']:
            await self.ib.sleep(2) # Wait 2 seconds
            
            if time.time() - start_time > ORDER_TIMEOUT_SEC:
                log.error(f"Order {trade.order.orderId} TIMEOUT (not filled after {ORDER_TIMEOUT_SEC}s). Cancelling.")
                self.ib.cancelOrder(trade.order)
                await self.ib.sleep(1) # Wait for cancellation
                break # Exit loop

            log.info(f"Order {trade.order.orderId} still pending... Status: {trade.orderStatus.status}")
        
        return trade


# --- Main execution ---
async def main():
    bot = GridBot(LOTS_CSV_FILE, STATE_FILE)
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Program terminated.")
    except Exception as e:
        log.critical(f"Unhandled critical exception: {e}")
        # In case the error happens outside the reconcile function
        show_critical_alert("Unhandled Exception", f"The bot crashed with an unexpected error:\n\n{e}\n\nPlease check logs and reset.")