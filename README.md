Certamente. Questa è un'ottima idea.

Ecco il riepilogo completo e dettagliato del progetto in inglese, come da tua richiesta. Puoi usare questo testo come "master prompt" per qualsiasi interazione futura, per assicurarti che io abbia immediatamente il quadro completo di tutte le decisioni che abbiamo preso.

---

### TQQQ Python Grid Bot: Project Master Summary (V13)

#### 1. Project Objective
To create an automated Python trading bot that connects to Interactive Brokers (IBKR) to execute a specific grid trading strategy on the **TQQQ** ETF. The bot must be robust, stateful, and capable of operating during pre-market, regular, and post-market sessions.

#### 2. Technical Stack & Connection
* **Language:** Python 3
* **API Library:** `ib_insync`
* **Broker:** Interactive Brokers (IBKR)
* **Connection Software:** The script connects to a running instance of **Trader Workstation (TWS)** or IB Gateway on the same machine.
* **Connection Endpoint:** `host='127.0.0.1'`, `port=7497` (default port for **Paper Trading**).
* **Market Data:** The script must explicitly request **delayed data (Type 3)** to avoid subscription errors (Error 354).
    * **Code:** `self.ib.reqMarketDataType(3)` must be called immediately after a successful connection.

#### 3. Core File & State Management
* **Input File (Lot Map):** The bot reads its primary instructions from a CSV file named `tqqq_trading_strategy - lots.csv.csv`. This file contains 88 rows, mapping each `level` (0-87) to the exact number of `shares_to_buy`.
* **State File (Inventory):** The bot *must* be stateful. It tracks its inventory of open positions by reading from and writing to a JSON file named `bot_state.json`.
* **Stateful Logic:**
    * An open lot (a `Lot` object) is written to `bot_state.json` **only after** its corresponding `BUY` order has been confirmed as **`Filled`**.
    * When the bot starts, it reads `bot_state.json` to load its current inventory and determine the `next_level` to buy.
    * This prevents the bot from creating duplicate positions or losing its place if restarted.

#### 4. BUY Logic (The "Engine")
This is the most critical logic, composed of two different order types.

**A. Initial Buy (Level 0)**
This logic applies *only* when the bot has no inventory (`next_level == 0`).
* **Conceptual Goal:** To enter the market *immediately*, simulating a "Market Order".
* **Technical Implementation:** Because `MarketOrder` (MKT) is rejected outside regular trading hours (RTH), the bot *must* use a `LimitOrder` (LMT).
* **Price Buffer:** To guarantee an immediate fill (like a MKT order), this LMT order *must* use a **price buffer**. The limit price is set slightly *above* the current price.
    * **Example:** `limit_price = current_price * (1 + 0.0025)` (i.e., +0.25% slippage buffer).
* **Flag:** The order *must* include `outsideRth=True`.

**B. Future Buys (Level 1-87)**
This logic applies to all subsequent purchases.
* **Order Type:** These are **Conditional Trigger Orders** submitted to the IBKR server.
* **No Buffer:** These orders do **not** use a price buffer. The `lmtPrice` is set to be *identical* to the `triggerPrice`.
* **Chained (Compounded) Triggers:** The trigger price for each level is **1% below the trigger price of the *previous* level**, not the initial price.
    * *Example:*
        1.  Level 0 `BUY` fills at **$100.00**.
        2.  Script calculates trigger for Level 1: `100.00 * 0.99 = $99.00`.
        3.  Script calculates trigger for Level 2: `99.00 * 0.99 = $98.01`.
        4.  Script calculates trigger for Level 3: `98.01 * 0.99 = $97.03`.
* **3-Order Queue (Key Logic):** As soon as an order (e.g., Level 0) is confirmed as `Filled`, the bot *must* immediately submit the **next 3** conditional `BUY` orders (e.g., for Levels 1, 2, and 3) to the IBKR servers.
* **Queue Maintenance:** When the Level 1 order is filled, the bot is notified. It then places the *next* order in the sequence (e.g., for Level 4, with a trigger of `97.03 * 0.99`), thus always maintaining a 3-order conditional queue on the server.
* **Flag:** All conditional orders *must* include `outsideRth=True`.

Sì, mi dice moltissimo. Hai assolutamente ragione, e ti chiedo scusa per aver omesso questo dettaglio tecnico cruciale dal riepilogo.

È **esattamente** come dici tu. È questo il "cervello" della mappatura 1-a-1.

Il mio riepilogo precedente era concettualmente corretto ("mappatura 1-a-1") ma non specificava *come* l'avremmo implementata. Il "come" è proprio usando gli ID degli ordini, come hai giustamente ricordato.

---

### Modifica alla Sezione 5 (SELL Logic) del Riepilogo

Ecco la versione aggiornata e corretta della Sezione 5 del "Master Summary", che include la tua precisazione.

*(Il resto del riepilogo V13 rimane invariato)*.

#### 5. SELL Logic (The "Profit Taker")
This logic is executed immediately after *any* `BUY` order is filled.

* **1-to-1 Mapping:** The strategy is *not* FIFO/LIFO. Each `BUY` lot is tied to its own specific `SELL` order.
* **Order ID Linking (Key Logic):** The link between a `BUY` and its corresponding `SELL` is managed via Order IDs.
    1.  A `BUY` order (e.g., for Level 0) is confirmed as `Filled`.
    2.  The bot *immediately* submits the corresponding `SELL` order (GTC, +1%).
    3.  TWS returns a new, unique `orderId` for this `SELL` order (e.g., `sell_order_id: 201`).
    4.  The bot *must* save this `sell_order_id` *inside* the `Lot` object in the `bot_state.json` file.
    * *Example `bot_state.json` entry:*
        `{ "level": 0, "quantity": 94, "purchase_price": 100.00, "sell_target_price": 101.00, "sell_order_id": 201 }`
* **State Management:** This allows the bot to know exactly which `SELL` order on the TWS server corresponds to which lot in its internal inventory. If a `SELL` order is filled, the bot will receive a notification for that `orderId` and will know to remove the *exact* corresponding lot from its state.
* **Order Type:** The sell order is a `LimitOrder` (LMT).
* **Order Flag:** The order *must* be set as **GTC ("Good-Til-Canceled")** and `outsideRth=True`.
* **Target Price:** The limit price is set to **1% above** the lot's specific purchase price (e.g., `purchase_price * 1.01`).

#### 6. Critical Bug Prevention & Robustness
To prevent the catastrophic failures seen in testing (e.g., order spam), the script *must* adhere to the following:
* **Order Spam (Critical):** The bot *must* use an `asyncio.Lock` (`processing_lock`). When `on_pending_ticker` fires, it must acquire this lock *before* processing any logic. This prevents multiple ticks from triggering the same logic (e.g., placing 10x Level 0 orders). The lock is released only after all logic for that tick is complete.
* **Order Monitoring (Critical):** When the bot places an order, it *must not* assume success. It must enter an asynchronous `while` loop (the `place_and_monitor_order` function) and actively wait for the order status to become final (`Filled`, `Cancelled`).
* **Timeout:** The `place_and_monitor_order` function *must* have a timeout (e.g., 120 seconds). If the order is not final by then, the bot must cancel the order and log an error.
* **`sleep` Bug Fix (Critical):** The correct asynchronous sleep command in `ib_insync` is `await self.ib.sleep(seconds)`, **NOT** `sleepAsync`. Using the wrong command causes the monitoring loop to fail and leads to order spam.
