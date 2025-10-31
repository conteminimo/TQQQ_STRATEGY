import sqlite3
import logging

# --- CONFIGURATION ---
DB_FILE = 'db_tqqq_grid_bot.sqlite'
log = logging.getLogger(__name__)

def get_db_connection():
    """Creates a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # This allows accessing columns by name
    return conn

def initialize_database():
    """
    Initializes the database and creates the 'trades' table if it doesn't exist.
    This function is safe to run every time the bot starts.
    """
    log.info(f"Initializing database at '{DB_FILE}'...")
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # SQL statement to create the trades table
        # This table will track every buy and its corresponding sell.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level INTEGER NOT NULL,
                
                -- Buy Order Details --
                buy_order_id INTEGER NOT NULL UNIQUE,
                buy_quantity REAL NOT NULL,
                buy_price REAL NOT NULL,
                buy_timestamp TEXT NOT NULL,

                -- Status of the Lot --
                -- 'OPEN': Bought, waiting to be sold.
                -- 'CLOSED': Successfully sold.
                status TEXT NOT NULL CHECK(status IN ('OPEN', 'CLOSED')),

                -- Sell Order Details (filled in later) --
                sell_order_id INTEGER UNIQUE,
                sell_quantity REAL,
                sell_price REAL,
                sell_timestamp TEXT
            );
        ''')

        conn.commit()
        log.info("Database initialized successfully. 'trades' table is ready.")

    except Exception as e:
        log.error(f"Error initializing database: {e}")
        raise  # Re-raise the exception to stop the bot if DB fails
def create_buy_trade(level, buy_order_id, quantity, price, timestamp):
    """
    Records a new BUY trade in the database with 'OPEN' status.
    
    Returns:
        int: The id of the newly created trade record.
    """
    log.info(f"Recording new BUY in DB: Level {level}, OrderID {buy_order_id}, Qty {quantity}, Price {price}")
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO trades (level, buy_order_id, buy_quantity, buy_price, buy_timestamp, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (level, buy_order_id, quantity, price, str(timestamp), 'OPEN')
        )
        conn.commit()
        new_id = cursor.lastrowid
        log.info(f"Successfully recorded new BUY trade with DB ID {new_id}.")
        return new_id
    except sqlite3.IntegrityError:
        log.warning(f"Trade with buy_order_id {buy_order_id} already exists in the database. Skipping.")
        return None
    except Exception as e:
        log.error(f"Error creating buy trade in database: {e}")
        raise
    finally:
        conn.close()

def update_trade_with_sell_order(db_id, sell_order_id):
    """Updates a trade record with the ID of the corresponding SELL order."""
    log.info(f"Updating trade DB ID {db_id} with SELL OrderID {sell_order_id}")
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE trades
            SET sell_order_id = ?
            WHERE id = ?
            ''',
            (sell_order_id, db_id)
        )
        conn.commit()
        log.info(f"Successfully updated trade DB ID {db_id}.")
    except Exception as e:
        log.error(f"Error updating trade with sell order: {e}")
        # We don't re-raise here to avoid stopping the bot for a non-critical DB update
    finally:
        conn.close()

def close_trade(sell_order_id, sell_quantity, sell_price, sell_timestamp):
    """Marks a trade as 'CLOSED' in the database."""
    log.info(f"Closing trade in DB for SELL OrderID {sell_order_id}")
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE trades
            SET status = 'CLOSED',
                sell_quantity = ?,
                sell_price = ?,
                sell_timestamp = ?
            WHERE sell_order_id = ?
            ''',
            (sell_quantity, sell_price, str(sell_timestamp), sell_order_id)
        )
        conn.commit()
        log.info(f"Successfully closed trade for SELL OrderID {sell_order_id}.")
    except Exception as e:
        log.error(f"Error closing trade in database: {e}")
    finally:
        conn.close()

def get_open_trades():
    """Retrieves all trades with status 'OPEN' from the database."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE status = 'OPEN'")
        return cursor.fetchall()
    finally:
        conn.close()

def get_trade_by_sell_order_id(sell_order_id):
    """Retrieves a single trade by its sell_order_id."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE sell_order_id = ?", (sell_order_id,))
        return cursor.fetchone()
    finally:
        conn.close()
if __name__ == '__main__':
    # This allows you to run this file directly to set up the database
    logging.basicConfig(level=logging.INFO)
    initialize_database()
    print(f"Database '{DB_FILE}' has been created/verified successfully.")
