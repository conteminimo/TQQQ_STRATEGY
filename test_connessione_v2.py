from ib_insync import IB
import asyncio

# --- Configurazione Connessione ---
IB_HOST = '127.0.0.1'  # '127.0.0.1' significa "questo computer"
IB_PORT = 7497         # 7497 è la porta di default per TWS Paper Trading
IB_CLIENT_ID = 1       # Un numero qualsiasi per identificare questo script

async def run_test():
    """
    Tenta di connettersi a IB TWS e basta.
    """
    ib = IB()
    print(f"Tentativo di connessione a TWS su {IB_HOST}:{IB_PORT}...")
    
    try:
        await ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
        
        # Se la connessione ha successo, stampiamo e basta.
        print("\n-------------------------------------------------")
        print("CONGRATULAZIONI! Connessione a TWS (Paper) riuscita.")
        print("Questa volta non provo a stampare nient'altro.")
        print("La connessione è confermata.")
        print("-------------------------------------------------\n")
        
        # Disconnettiamoci
        ib.disconnect()

    except Exception as e:
        # Se la connessione fallisce (questa volta per davvero)
        print("\n-------------------------------------------------")
        print("ERRORE: Connessione FALLITA.")
        print(f"Dettagli: {e}")
        print("-------------------------------------------------\n")

if __name__ == "__main__":
    try:
        asyncio.run(run_test())
    except (KeyboardInterrupt, SystemExit):
        print("Test interrotto.")