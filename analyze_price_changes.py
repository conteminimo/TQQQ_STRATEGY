import sqlite3
import pandas as pd

def analyze_price_volatility():
    db_path = 'synthetic_data.sqlite'
    conn = sqlite3.connect(db_path)

    try:
        # Carica i dati sintetici in un DataFrame di pandas
        df = pd.read_sql_query("SELECT timestamp, close FROM minute_bars ORDER BY timestamp", conn)
        
        # Assicura che la colonna 'timestamp' sia in formato datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Ordina i dati per timestamp, anche se la query SQL dovrebbe già farlo
        df = df.sort_values(by='timestamp').reset_index(drop=True)

        # Calcola la variazione percentuale del prezzo di chiusura
        df['price_change'] = df['close'].pct_change()

        # Conta le occorrenze di aumento e diminuzione dell'1%
        price_increase_count = (df['price_change'] >= 0.01).sum()
        price_decrease_count = (df['price_change'] <= -0.01).sum()

        print(f"Analisi dei dati da '{db_path}':")
        print(f"Numero totale di barre da 1 minuto: {len(df)}")
        print(f"Numero di volte in cui il prezzo è aumentato dell'1% o più: {price_increase_count}")
        print(f"Numero di volte in cui il prezzo è diminuito dell'1% o più: {price_decrease_count}")

    finally:
        conn.close()

if __name__ == "__main__":
    analyze_price_volatility()
