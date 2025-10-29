from ib_insync import IB
import asyncio

# --- Configurazione Connessione ---
IB_HOST = '127.0.0.1'  # '127.0.0.1' significa "questo computer"
IB_PORT = 7497         # 7497 è la porta di default per TWS Paper Trading
IB_CLIENT_ID = 1       # Un numero qualsiasi per identificare questo script

async def run_test():
    """
    Tenta di connettersi a IB TWS
    """
    ib = IB()
    print(f"Tentativo di connessione a TWS su {IB_HOST}:{IB_PORT}...")
    
    try:
        await ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
        
        # Se la connessione ha successo
        print("\n-------------------------------------------------")
        print("CONGRATULAZIONI! Connessione a TWS (Paper) riuscita.")
        print(f"Versione TWS: {ib.version()}")
        print("Siamo pronti per lo script completo.")
        print("-------------------------------------------------\n")
        
        # Disconnettiamoci
        ib.disconnect()

    except Exception as e:
        # Se la connessione fallisce
        print("\n-------------------------------------------------")
        print("ERRORE: Connessione FALLITA.")
        print(f"Dettagli: {e}")
        print("\nPossibili cause:")
        print("1. TWS non è in esecuzione?")
        print("2. Non hai effettuato l'accesso al conto PAPER?")
        print("3. Le impostazioni API in TWS non sono corrette?")
        print("   (Controlla: Abilita client ActiveX, Porta 7497, IP 127.0.0.1)")
        print("-------------------------------------------------\n")

if __name__ == "__main__":
    # ib_insync richiede un "loop" asincrono per funzionare
    try:
        asyncio.run(run_test())
    except (KeyboardInterrupt, SystemExit):
        print("Test interrotto.")