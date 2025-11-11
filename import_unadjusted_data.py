
import sqlite3
import pandas as pd

# --- CONFIGURAZIONE ---
# Percorso del file di testo con i dati di prezzo
DATA_FILE_PATH = 'TQQQ_1_Minute_Interval_Data/TQQQ_full_1min_UNADJUSTED.txt'

# Nome del file del database SQLite che verrà creato
DB_FILE = 'unadjusted_market_data.sqlite'

# Nome della tabella in cui verranno inseriti i dati
TABLE_NAME = 'tqqq_1min_unadjusted'

def load_data_to_sqlite():
    """Carica i dati di prezzo dal file di testo a un database SQLite."""
    try:
        # Leggi i dati dal file, specificando che non c'è header e fornendo i nomi delle colonne.
        # il separatore è la virgola.
        column_names = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        df = pd.read_csv(DATA_FILE_PATH, header=None, names=column_names, sep=',')
        # Assicura che la colonna timestamp sia in formato datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        print(f"Letti {len(df)} record dal file '{DATA_FILE_PATH}'.")
    except FileNotFoundError:
        print(f"ERRORE: Il file di dati non è stato trovato al percorso: {DATA_FILE_PATH}")
        print("Assicurati che il file esista e che il percorso sia corretto.")
        return
    except Exception as e:
        print(f"Errore durante la lettura del file: {e}")
        return

    try:
        # Connessione al database SQLite (verrà creato se non esiste)
        conn = sqlite3.connect(DB_FILE)
        print(f"Connesso al database SQLite '{DB_FILE}'.")

        # Usa pandas per scrivere il DataFrame direttamente nella tabella SQL
        # 'if_exists='replace'' significa che se la tabella esiste già, verrà sostituita.
        # Puoi cambiarlo in 'append' se vuoi aggiungere dati senza cancellare i vecchi.
        df.to_sql(TABLE_NAME, conn, if_exists='replace', index=False)

        print(f"Successo! {len(df)} record sono stati inseriti nella tabella '{TABLE_NAME}'.")

    except sqlite3.Error as e:
        print(f"Errore di SQLite: {e}")
    finally:
        if 'conn' in locals():
            conn.close()
            print("Connessione a SQLite chiusa.")

if __name__ == "__main__":
    load_data_to_sqlite()
