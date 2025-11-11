
import mysql.connector
import pandas as pd

# --- CONFIGURAZIONE ---
# Modifica con i dettagli del tuo database MySQL
DB_CONFIG = {
    'host': 'localhost',
    'user': 'il_tuo_utente',
    'password': 'la_tua_password'
}
DB_NAME = 'market_data'
TABLE_NAME = 'tqqq_unadjusted'
DATA_FILE_PATH = 'TQQQ_1_Minute_Interval_Data/TQQQ_full_1min_UNADJUSTED.txt' # Assicurati che il percorso sia corretto

def create_database_and_table(cursor):
    """Crea il database e la tabella se non esistono."""
    try:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} DEFAULT CHARACTER SET 'utf8'")
        cursor.execute(f"USE {DB_NAME}")
        print(f"Database '{DB_NAME}' selezionato.")
        
        create_table_query = f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            `timestamp` DATETIME PRIMARY KEY,
            `open` DECIMAL(10, 4),
            `high` DECIMAL(10, 4),
            `low` DECIMAL(10, 4),
            `close` DECIMAL(10, 4),
            `volume` INT
        )
        """
        cursor.execute(create_table_query)
        print(f"Tabella '{TABLE_NAME}' creata o già esistente.")
    except mysql.connector.Error as err:
        print(f"Errore durante la creazione del database/tabella: {err}")
        raise

def load_data_to_mysql():
    """Carica i dati dal file di testo al database MySQL."""
    try:
        # Leggi i dati dal file di testo usando pandas
        # 'sep='\s+'' indica che le colonne sono separate da uno o più spazi
        df = pd.read_csv(DATA_FILE_PATH, sep='\s+')
        print(f"Letti {len(df)} record dal file di testo.")
    except FileNotFoundError:
        print(f"ERRORE: Il file di dati non è stato trovato al percorso: {DATA_FILE_PATH}")
        return

    try:
        # Connessione a MySQL
        cnx = mysql.connector.connect(**DB_CONFIG)
        cursor = cnx.cursor()

        # Crea database e tabella
        create_database_and_table(cursor)

        # Prepara la query di inserimento
        insert_query = f"""
        INSERT INTO {TABLE_NAME} (timestamp, open, high, low, close, volume)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            open=VALUES(open), high=VALUES(high), low=VALUES(low), 
            close=VALUES(close), volume=VALUES(volume)
        """
        
        # Crea una lista di tuple dai dati del DataFrame
        data_to_insert = [tuple(row) for row in df.itertuples(index=False)]

        # Esegui l'inserimento in blocco
        cursor.executemany(insert_query, data_to_insert)
        cnx.commit()

        print(f"Successo! {cursor.rowcount} record sono stati inseriti o aggiornati nella tabella '{TABLE_NAME}'.")

    except mysql.connector.Error as err:
        print(f"Errore di MySQL: {err}")
    finally:
        if 'cnx' in locals() and cnx.is_connected():
            cursor.close()
            cnx.close()
            print("Connessione a MySQL chiusa.")

if __name__ == "__main__":
    load_data_to_mysql()
