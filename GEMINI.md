# GEMINI.md - TQQQ Grid Trading Bot

## Project Overview

This project is an automated, resilient grid trading bot written in Python. It leverages a hybrid architecture, utilizing Interactive Brokers (TWS or Gateway) for trade execution and Alpaca for real-time market data. Its core strength lies in a robust, database-driven state management system that ensures high resilience and self-healing capabilities against unexpected interruptions or discrepancies with the broker's records.

## Building and Running

### 1. Dependencies

This project requires Python 3. The primary dependencies are:

*   `ib_insync`: For interacting with Interactive Brokers.
*   `pandas`: For data manipulation, especially for the grid strategy CSV.
*   `alpaca-py`: For fetching real-time market data from Alpaca.
*   `python-dotenv`: For securely loading environment variables from a `.env` file.
*   `sqlite3`: Python's built-in SQLite library for persistent state management.

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
    pip install pandas ib_insync alpaca-py python-dotenv
    ```

4.  **Configure API Keys:** Create a `.env` file in the project root directory with your Alpaca API keys. This file is ignored by Git for security.
    ```
    ALPACA_KEY="YOUR_ALPACA_KEY_ID"
    ALPACA_SECRET="YOUR_ALPACA_SECRET_KEY"
    ```

5.  **Initialize Database:** Run the `db_tqqq.py` script once to create the SQLite database file.
    ```bash
    python3 db_tqqq.py
    ```

### 3. Running the Bot

Once the setup is complete and TWS is running, execute the main script from the project root directory:

```bash
python3 tqqq_grid_bot.py
```

The bot will start, connect to TWS, and begin its initialization and trading logic. All activities are logged to the console and to `bot_log.txt`.

## Strategy & Architecture

This bot executes a grid trading strategy on the TQQQ ETF. It uses a hybrid architecture for resilience and real-time data accuracy.

- **Core Strategy**: The bot works through a series of BUY levels defined in a `.csv` file. When a BUY order for a certain level is filled, a corresponding Good-Til-Canceled (GTC) SELL order is immediately placed with a 1% profit target. Subsequent BUY orders are queued as conditional orders on the broker.

- **Hybrid Data/Trading Model**:
  - **Trading Execution**: All orders (BUY and SELL) are executed via the Interactive Brokers API, using the `ib_insync` library.
  - **Real-Time Market Data**: To trigger the initial (Level 0) buy and to provide a real-time price feed in the log, the bot uses the Alpaca API via `alpaca-py`.

- **State Management & Self-Healing**:
  - **Persistence**: The bot's state is persisted in a local SQLite database (`db_tqqq_grid_bot.sqlite`). Every BUY and SELL is recorded transactionally.
  - **Single Source of Truth**: The broker (Interactive Brokers) is treated as the ultimate source of truth.
  - **Startup Reconciliation**: On every startup, the bot performs a full reconciliation routine to ensure its internal state is perfectly synchronized with the broker. This routine:
    1.  Populates its local database by reverse-engineering lots from any open SELL orders found on IB.
    2.  Detects and closes trades that were sold while the bot was offline.
    3.  Identifies any "orphan" shares (positions held at the broker but not tracked in the database) and creates new SELL orders for them based on the portfolio's average cost.
    4.  Rebuilds its in-memory state from the reconciled database.
