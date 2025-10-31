# GEMINI.md - TQQQ Grid Trading Bot

## Project Overview

This project is an automated, resilient grid trading bot written in Python. It uses Interactive Brokers (TWS or Gateway) for trading and Alpaca for real-time market data.

## Architecture

The bot uses a hybrid approach for its operation:
- **Trading:** All orders (BUY and SELL) are executed through the Interactive Brokers API (`ib_insync`).
- **Market Data:** Real-time price data for TQQQ is fetched from the Alpaca API (`alpaca-py`). This is used to trigger the initial (Level 0) buy order.

This separation allows the bot to leverage the real-time data from Alpaca while using the robust trading infrastructure of Interactive Brokers.

A key feature of this bot is its **self-healing startup logic**. Instead of relying on a potentially stale local state file, the bot reconstructs its entire inventory of open positions at startup by:
1.  Fetching all open SELL orders for TQQQ from TWS.
2.  Using the quantity of each SELL order to determine its corresponding grid `level` (via the `tqqq_trading_strategy - lots.csv.csv` map).
3.  Reverse-engineering the original purchase price from the SELL order's limit price (which is set at a +1% profit target).

This makes the bot highly resilient to crashes or restarts, as it derives its state directly from the broker. The local `bot_state.json` file is used as a persistent backup of the reconstructed state, not as the primary source of truth for recovery.

**Limitation:** The self-healing logic assumes that the share quantity for each grid level is unique. The `tqqq_trading_strategy - lots.csv.csv` file shows that quantities are unique for higher-value levels but have duplicates at lower levels. In a scenario with multiple open lots of the same small size, the reconstruction logic might face ambiguity.

## Building and Running

### 1. Dependencies

This project requires Python 3. The primary dependencies are:

*   `ib_insync`
*   `pandas`
*   `alpaca-py`

### 2. Setup

1.  **Create a Virtual Environment:** It is highly recommended to run the bot in a dedicated virtual environment. The existing `ib_bot_env` directory suggests this is the intended practice.
    ```bash
    python3 -m venv ib_bot_env
    ```

2.  **Activate the Environment:**
    ```bash
    source ib_bot_env/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install pandas ib_insync
    ```

### 3. Configuration

*   **Interactive Brokers:** Ensure Trader Workstation (TWS) or IB Gateway is running, configured for API access, and set to the correct port (default is `7497` for paper trading).
*   **Script Configuration:** Key parameters such as connection details (`IB_HOST`, `IB_PORT`), the profit target, and file paths are defined as constants at the top of `tqqq_grid_bot.py`.
*   **Strategy Definition:** The grid itself (levels and share quantities) is defined in `tqqq_trading_strategy - lots.csv.csv`.

### 4. Running the Bot

Once the setup is complete and TWS is running, execute the main script from the project root directory:

```bash
python3 tqqq_grid_bot.py
```

The bot will start, connect to TWS, and begin its initialization and trading logic. All activities are logged to the console and to `bot_log.txt`.

## Development Conventions

*   **State Management:** The authoritative state is derived from TWS at startup, as described in the overview. This is the core architectural principle.
*   **Core Logic:** The bot is event-driven, reacting primarily to order fills (`on_fill` event).
    *   **BUY Logic:** A "Level 0" buy is triggered by the first market data tick if no position exists. Subsequent buys are placed as a 3-order conditional queue, which is refreshed after every BUY fill.
    *   **SELL Logic:** Every BUY fill immediately triggers the placement of a corresponding GTC (Good-Til-Canceled) SELL order with a limit price set to `purchase_price * 1.01`.
*   **Safety:**
    *   A `show_critical_alert` function provides a safe shutdown mechanism for unrecoverable errors (like state reconstruction failure).
    *   An `asyncio.Lock` (`processing_lock`) is used within event handlers to prevent race conditions and duplicate order placements.
*   **Logging:** The script logs its operations to both the console and a file, `bot_log.txt`. The file is opened in append mode (`'a'`) to preserve history across runs.
