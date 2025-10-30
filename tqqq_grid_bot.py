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
STATE_FILE = 'bot_state.json'
SYMBOL = "TQQQ"
EXCHANGE = "SMART"
CURRENCY = "USD"
PROFIT_TARGET_PERCENT = 1.01
BUY_TRIGGER_PERCENT = 0.99
POLL_INTERVAL_SEC = 20
ORDER_TIMEOUT_SEC = 120
L0_BUY_BUFFER = 1.0025
FUTURE_BUY_QUEUE_DEPTH = 3

IB_HOST = '127.0.0.1'
IB_PORT = 7497
IB_CLIENT_ID = 101

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("log_tqqq_grid_bot.log", mode='a'),
                              logging.StreamHandler()])
log = logging.getLogger()

def show_critical_alert(title, message):
    log.critical("=" * 60)
    log.critical(f"CRITICAL ALERT: {title}")
    log.critical(message)
    log.critical("The bot will now SHUT DOWN to prevent damage.")
    log.critical("=" * 60)
    print('\a')
    sys.exit(1)

class Lot:
    def __init__(self, level, quantity, purchase_price, sell_order_id=None):
        self.level = int(level)
        self.quantity = int(quantity)
        self.purchase_price = float(purchase_price)
        self.sell_target_price = round(float(purchase_price) * PROFIT_TARGET_PERCENT, 2)
        self.sell_order_id = sell_order_id

    def to_dict(self):
        return self.__dict__

    @staticmethod
    def from_dict(data):
        return Lot(
            data['level'],
            data['quantity'],
            data['purchase_price'],
            data.get('sell_order_id')
        )

class GridBot:
    def __init__(self, lot_map_path, state_path):
        self.ib = IB()
        self.lot_map = self.load_lot_map(lot_map_path)
        self.state_path = state_path
        self.contract = None
        self.lot_inventory = []
        self.next_level = 0
        self.buy_reference_price = None
        self.processing_lock = asyncio.Lock()
        self.l0_buy_in_progress = False
        log.info("GridBot initialized.")

    def load_lot_map(self, path):
        try:
            df = pd.read_csv(path, header=None, names=['level', 'shares_to_buy'])
            log.info(f"CSV file '{path}' loaded with {len(df)} levels.")
            return df
        except Exception as e:
            log.error(f"Could not read CSV file '{path}': {e}")
            sys.exit(1)

    def save_state(self):
        try:
            with open(self.state_path, 'w') as f:
                json.dump([lot.to_dict() for lot in self.lot_inventory], f, indent=4)
            log.info(f"State successfully saved to '{self.state_path}'.")
        except Exception as e:
            log.error(f"Critical error: Could not save state to '{self.state_path}': {e}")

    def calculate_next_level(self):
        if not self.lot_inventory:
            return 0
        open_levels = {lot.level for lot in self.lot_inventory}
        return max(open_levels) + 1

    def find_reference_price(self):
        if not self.lot_inventory:
            return None
        try:
            highest_level_lot = max(self.lot_inventory, key=lambda lot: lot.level)
            price = highest_level_lot.purchase_price

            if highest_level_lot.level > 0:
                l0_lot = next(lot for lot in self.lot_inventory if lot.level == 0)
                ref_price = l0_lot.purchase_price
                for _ in range(highest_level_lot.level):
                    ref_price = ref_price * BUY_TRIGGER_PERCENT
                price = ref_price

            return round(price, 2)
        except StopIteration:
            log.warning("Could not find Level 0 lot to calculate reference price.")
            return None

    async def connect(self):
        try:
            log.info(f"Attempting to connect to TWS at {IB_HOST}:{IB_PORT}...")
            await self.ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
            log.info(f"Connection to TWS successful. Server Version: {self.ib.client.serverVersion()}")
            self.ib.reqMarketDataType(3)
            self.contract = Stock(SYMBOL, EXCHANGE, CURRENCY)
            await self.ib.qualifyContractsAsync(self.contract)
            log.info(f"Contract {SYMBOL} qualified.")
            return True
        except Exception as e:
            log.error(f"Connection failed: {e}")
            return False

    async def run(self):
        if not await self.connect():
            return
        await self.initialize_state_from_tws()
        self.ib.execDetailsEvent += self.on_fill
        log.info("Subscribed to fill events. Bot started successfully. Monitoring...")
        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL_SEC)
                log.info(f"Bot running... Open lots: {len(self.lot_inventory)}. Next level: {self.next_level}")
        except (KeyboardInterrupt, SystemExit):
            log.info("Manual stop received...")
        finally:
            log.info("Disconnecting...")
            self.ib.disconnect()
            log.info("Bot disconnected.")

    async def initialize_state_from_tws(self):
        log.info("Initializing state from TWS using self-healing logic...")
        qty_to_level_map = {v: k for k, v in self.lot_map.set_index('level')['shares_to_buy'].to_dict().items()}

        # Use ib.openTrades() to get the current list of open orders known to ib_insync
        open_sell_trades = [t for t in self.ib.openTrades() if t.contract.conId == self.contract.conId and t.order.action == 'SELL']

        if not open_sell_trades:
            log.info("No open SELL orders found.")
            positions = await self.ib.reqPositionsAsync()
            tws_position = next((p for p in positions if p.contract.conId == self.contract.conId), None)
            if tws_position is None or tws_position.position == 0:
                log.info("No TQQQ position found. Starting Level 0 buy logic.")
                self.next_level = 0
                self.lot_inventory = []
                self.buy_reference_price = None
                self.ib.reqMktData(self.contract, '', False, False)
                self.ib.pendingTickersEvent += self.on_pending_ticker
                log.info("Waiting for first price tick to place Level 0 order...")
            else:
                show_critical_alert("State Reconstruction Failed", f"Found {tws_position.position} shares in TWS but NO corresponding open SELL orders. Cannot reconstruct state.")
            return

        log.info(f"Found {len(open_sell_trades)} open SELL orders. Reconstructing inventory...")
        reconstructed_inventory = []
        for trade in open_sell_trades:
            quantity = trade.order.totalQuantity
            sell_price = trade.order.lmtPrice
            sell_order_id = trade.order.orderId
            level = qty_to_level_map.get(quantity)
            if level is None:
                show_critical_alert("State Reconstruction Failed", f"Found SELL order for {quantity} shares, but this quantity does not exist in the lot map.")
                return
            purchase_price = round(sell_price / PROFIT_TARGET_PERCENT, 2)
            new_lot = Lot(level, quantity, purchase_price, sell_order_id)
            reconstructed_inventory.append(new_lot)
            log.info(f"Reconstructed Lot: Level {level}, Qty {quantity}, Buy Price {purchase_price}, Sell OrderId {sell_order_id}")

        self.lot_inventory = reconstructed_inventory
        self.save_state()
        self.next_level = self.calculate_next_level()
        self.buy_reference_price = self.find_reference_price()
        log.info(f"Inventory successfully reconstructed. Next level: {self.next_level}. Ref price: {self.buy_reference_price}")
        log.info("Setting up BUY queue...")
        await self.place_future_buy_queue()

    def on_pending_ticker(self, tickers):
        for ticker in tickers:
            if ticker.contract.conId == self.contract.conId and ticker.last > 0:
                if self.next_level == 0 and not self.l0_buy_in_progress:
                    asyncio.create_task(self.execute_buy_level_0(ticker.last))

    async def execute_buy_level_0(self, current_price):
        async with self.processing_lock:
            if self.next_level != 0:
                log.warning("execute_buy_level_0 called, but next_level is not 0. Ignoring.")
                return
            log.info(f"Placing first buy (Level 0) at market price: {current_price}")
            quantity = int(self.lot_map.iloc[0]['shares_to_buy'])
            limit_price = round(current_price * L0_BUY_BUFFER, 2)
            trade = await self.place_and_monitor_order("BUY", quantity, limit_price)
            if trade and trade.orderStatus.status == 'Filled':
                log.info(f"Level 0 Buy order (Id: {trade.order.orderId}) confirmed as Filled.")
                self.ib.pendingTickersEvent -= self.on_pending_ticker
            else:
                log.warning(f"Level 0 Buy order failed or was cancelled. Status: {trade.orderStatus.status if trade else 'Unknown'}.")
                self.l0_buy_in_progress = False

    async def on_fill(self, trade: Trade, fill: Fill):
        if fill.contract.conId != self.contract.conId:
            return
        async with self.processing_lock:
            action = fill.execution.side
            orderId = fill.execution.orderId
            log.info(f"--- FILL RECEIVED: {action} order {orderId} ---")
            if action == "BOT":
                if any(lot.level == self.next_level for lot in self.lot_inventory):
                    log.warning(f"Ignoring duplicate BUY fill for Level {self.next_level}.")
                    return
                level = self.next_level
                new_lot = Lot(level, fill.execution.shares, fill.execution.avgPrice)
                sell_trade = await self.place_sell_order(new_lot)
                new_lot.sell_order_id = sell_trade.order.orderId
                self.lot_inventory.append(new_lot)
                self.save_state()
                self.buy_reference_price = new_lot.purchase_price if level == 0 else round(self.buy_reference_price * BUY_TRIGGER_PERCENT, 2)
                self.next_level += 1
                log.info(f"State updated. New next_level: {self.next_level}. New ref_price: {self.buy_reference_price}")
                await self.place_future_buy_queue(filledOrderId=orderId)
            elif action == "SLD":
                lot_to_remove = next((lot for lot in self.lot_inventory if lot.sell_order_id == orderId), None)
                if lot_to_remove:
                    self.lot_inventory.remove(lot_to_remove)
                    self.save_state()
                    log.info(f"Sell for Level {lot_to_remove.level} confirmed. Lot removed from inventory.")
                else:
                    log.warning(f"Received SELL fill for OrderId {orderId}, but no matching lot found!")
            log.info("--- FILL PROCESSING COMPLETE ---")

    async def place_sell_order(self, lot: Lot):
        log.info(f"Placing GTC SELL Limit for Lvl {lot.level}: {lot.quantity} @ {lot.sell_target_price}")
        order = LimitOrder('SELL', lot.quantity, lot.sell_target_price, tif='GTC', outsideRth=True)
        return self.ib.placeOrder(self.contract, order)

    async def place_future_buy_queue(self, filledOrderId=None):
        log.info("Placing/Updating next {FUTURE_BUY_QUEUE_DEPTH} conditional BUY orders...")

        # Use the more reliable ib.openTrades() to find orders to cancel
        # This list is populated by ib_insync from openOrder events
        open_trades = self.ib.openTrades()
        for trade in open_trades:
            # Skip the order that was just filled to prevent a race condition
            if trade.order.orderId == filledOrderId:
                continue

            # Cancel any other open BUY orders for this symbol that are LMT or LIT
            if trade.contract.conId == self.contract.conId and trade.order.action == 'BUY' and trade.order.orderType in ('LMT', 'LIT'):
                log.warning(f"Cancelling old BUY order (Id: {trade.order.orderId}, Type: {trade.order.orderType}).")
                self.ib.cancelOrder(trade.order)

        await asyncio.sleep(0.5)

        current_trigger_price = self.buy_reference_price
        for i in range(FUTURE_BUY_QUEUE_DEPTH):
            level_to_queue = self.next_level + i
            if level_to_queue >= len(self.lot_map):
                log.info("Reached end of lot map.")
                break
            if current_trigger_price is None or current_trigger_price <= 0:
                log.error(f"Cannot place future orders: Invalid reference price ({current_trigger_price}).")
                return

            trigger_price = round(current_trigger_price * BUY_TRIGGER_PERCENT, 2)
            quantity = int(self.lot_map.iloc[level_to_queue]['shares_to_buy'])
            log.info(f"Placing conditional BUY for Lvl {level_to_queue}: {quantity} shares, Trigger @ {trigger_price}")
            await self.place_conditional_buy(quantity, trigger_price)
            current_trigger_price = trigger_price

    async def place_conditional_buy(self, quantity, trigger_price):
        # Using a Limit-if-Touched (LIT) order for robust conditional execution.
        order = Order()
        order.action = 'BUY'
        order.orderType = 'LIT'
        order.totalQuantity = quantity
        order.lmtPrice = trigger_price
        order.auxPrice = trigger_price
        order.outsideRth = True
        order.transmit = True

        self.ib.placeOrder(self.contract, order)

    async def place_and_monitor_order(self, action, quantity, limit_price):
        order = LimitOrder(action, quantity, limit_price, outsideRth=True)
        trade = self.ib.placeOrder(self.contract, order)
        log.info(f"Order {action} {quantity} {SYMBOL} LMT @ {limit_price} submitted (Id: {trade.order.orderId}). Waiting for fill...")
        start_time = time.time()
        while trade.orderStatus.status not in OrderStatus.DoneStates:
            await asyncio.sleep(2)
            if time.time() - start_time > ORDER_TIMEOUT_SEC:
                log.error(f"Order {trade.order.orderId} TIMEOUT. Cancelling.")
                self.ib.cancelOrder(trade.order)
                return None
            log.info(f"Order {trade.order.orderId} pending... Status: {trade.orderStatus.status}")
        log.info(f"Order {trade.order.orderId} finished. Final Status: {trade.orderStatus.status}")
        return trade

async def main():
    bot = GridBot(LOTS_CSV_FILE, STATE_FILE)
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Program terminated.")
    except Exception as e:
        log.critical(f"Unhandled critical exception: {e}", exc_info=True)
        show_critical_alert("Unhandled Exception", f"Bot crashed:\\n\\n{e}")