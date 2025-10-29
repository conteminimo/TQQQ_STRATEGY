import asyncio
import pandas as pd
from ib_insync import *
import logging
import time
import json
import os

# --- 1. CONFIGURAZIONE ---
NOME_FILE_CSV = 'tqqq_trading_strategy - lots.csv.csv'
NOME_FILE_STATO = 'stato_bot.json'  # File per salvare i lotti aperti
SIMBOLO = "TQQQ"
SCAMBIO = "SMART"
VALUTA = "USD"
PROFIT_TARGET_PERCENT = 1.0  # % di profitto (1.0 = 1%)
POLL_INTERVALLO_SEC = 10     # Intervallo controllo prezzo (secondi)

# --- Configurazione Connessione IB ---
IB_HOST = '127.0.0.1'
IB_PORT = 7497  # 7497 per Paper Trading
IB_CLIENT_ID = 101

# --- Setup Logging (per file e console) ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("bot_log.txt"),
                              logging.StreamHandler()])
log = logging.getLogger()

class GridBot:
    def __init__(self, mappa_lotti_path, stato_path):
        self.ib = IB()
        self.mappa_lotti = self.carica_mappa_lotti(mappa_lotti_path)
        self.stato_path = stato_path
        self.inventario_lotti = self.carica_stato()
        self.contratto = self.crea_contratto()
        self.prossimo_livello = self.calcola_prossimo_livello()
        self.prezzo_riferimento_acquisto = self.trova_prezzo_riferimento()

        log.info("--- STATO INIZIALE ---")
        log.info(f"Prossimo livello da acquistare: {self.prossimo_livello}")
        log.info(f"Lotti già aperti in inventario: {len(self.inventario_lotti)}")
        log.info(f"Prezzo di riferimento acquisto: {self.prezzo_riferimento_acquisto}")
        log.info("----------------------")

    def carica_mappa_lotti(self, path):
        try:
            df = pd.read_csv(path, header=None, names=['livello', 'azioni_da_comprare'])
            log.info(f"File CSV '{path}' caricato con {len(df)} livelli.")
            return df
        except Exception as e:
            log.error(f"Impossibile leggere il file CSV '{path}': {e}")
            exit()

    def carica_stato(self):
        if os.path.exists(self.stato_path):
            try:
                with open(self.stato_path, 'r') as f:
                    data = json.load(f)
                    log.info(f"Stato precedente caricato da '{self.stato_path}'.")
                    return [Lotto.from_dict(d) for d in data]
            except Exception as e:
                log.warning(f"Impossibile leggere file stato '{self.stato_path}': {e}. Ripartiamo da zero.")
        return []

    def salva_stato(self):
        try:
            with open(self.stato_path, 'w') as f:
                json.dump([lotto.to_dict() for lotto in self.inventario_lotti], f, indent=4)
        except Exception as e:
            log.error(f"Errore critico: Impossibile salvare lo stato su '{self.stato_path}': {e}")

    def calcola_prossimo_livello(self):
        if not self.inventario_lotti:
            return 0
        livelli_aperti = {lotto.livello for lotto in self.inventario_lotti}
        max_livello_aperto = max(livelli_aperti)
        return max_livello_aperto + 1
    
    def trova_prezzo_riferimento(self):
        if not self.inventario_lotti:
            return None
        ultimo_lotto = max(self.inventario_lotti, key=lambda lotto: lotto.livello)
        return ultimo_lotto.prezzo_acquisto

    def crea_contratto(self):
        contratto = Stock(SIMBOLO, SCAMBIO, VALUTA)
        return contratto

    async def connetti(self):
        try:
            log.info(f"Tentativo di connessione a TWS su {IB_HOST}:{IB_PORT}...")
            await self.ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)
            
            versione = self.ib.client.serverVersion()
            log.info(f"Connessione a TWS riuscita. Versione Server: {versione}")
            log.info(f"Connessione e setup completati.")
            return True
        except Exception as e:
            log.error(f"Connessione fallita: {e}")
            return False

    async def run(self):
        """Loop principale del bot."""
        if not await self.connetti():
            log.error("Impossibile avviare il bot. Connessione fallita.")
            return
            
        # --- ECCO LA RIGA CHE HAI TROVATO (v6) ---
        # Imposta il tipo di dati a 3 (Delayed)
        # Questo risolve l'errore 354
        log.info("Imposto il tipo di dati di mercato a 3 (Delayed)...")
        self.ib.reqMarketDataType(3)
        # ----------------------------------------

        await self.ib.qualifyContractsAsync(self.contratto)

        self.ib.reqMktData(self.contratto, '', False, False)
        self.ib.pendingTickersEvent += self.on_pending_ticker
        
        log.info("Bot avviato. In attesa di dati di mercato per TQQQ...")

        try:
            while True:
                await asyncio.sleep(POLL_INTERVALLO_SEC)
                log.info(f"Bot in esecuzione... Lotti aperti: {len(self.inventario_lotti)}. Prossimo livello: {self.prossimo_livello}")

        except (KeyboardInterrupt, SystemExit):
            log.info("Stop manuale ricevuto. Disconnessione...")
        finally:
            self.ib.pendingTickersEvent -= self.on_pending_ticker
            self.ib.disconnect()
            log.info("Bot disconnesso.")

    def on_pending_ticker(self, tickers):
        """Funzione chiamata ogni volta che arriva un nuovo prezzo."""
        for ticker in tickers:
            if ticker.contract.conId == self.contratto.conId:
                prezzo_attuale = ticker.last
                if prezzo_attuale and prezzo_attuale > 0:
                    log.debug(f"Nuovo prezzo TQQQ: {prezzo_attuale}")
                    asyncio.create_task(self.gestisci_logica(prezzo_attuale))

    async def gestisci_logica(self, prezzo_attuale):
        """Controlla se dobbiamo comprare o vendere."""
        
        # 1. LOGICA DI VENDITA
        lotti_da_rimuovere = []
        for lotto in self.inventario_lotti:
            if prezzo_attuale >= lotto.prezzo_vendita_target:
                log.info(f"TARGET VENDITA COLPITO! Vendo {lotto.quantita} azioni (Livello {lotto.livello}) a {prezzo_attuale}")
                await self.piazza_ordine("SELL", lotto.quantita)
                lotti_da_rimuovere.append(lotto)
        
        if lotti_da_rimuovere:
            self.inventario_lotti = [lotto for lotto in self.inventario_lotti if lotto not in lotti_da_rimuovere]
            self.salva_stato()
            self.prezzo_riferimento_acquisto = self.trova_prezzo_riferimento()

        # 2. LOGICA DI ACQUISTO
        if self.prossimo_livello == 0 and not self.inventario_lotti:
            log.info(f"Eseguo il primo acquisto (Livello 0) al prezzo di mercato: {prezzo_attuale}")
            await self.esegui_acquisto(prezzo_attuale)

        elif self.prezzo_riferimento_acquisto and prezzo_attuale <= (self.prezzo_riferimento_acquisto * 0.99):
            log.info(f"TARGET ACQUISTO COLPITO! Prezzo {prezzo_attuale} <= {self.prezzo_riferimento_acquisto * 0.99}")
            await self.esegui_acquisto(prezzo_attuale)

    async def esegui_acquisto(self, prezzo_acquisto):
        livello = self.prossimo_livello
        if livello >= len(self.mappa_lotti):
            log.warning(f"Tutti i {len(self.mappa_lotti)} livelli sono già stati acquistati. Fine degli acquisti.")
            return

        quantita = int(self.mappa_lotti.at[livello, 'azioni_da_comprare'])
        log.info(f"Eseguo acquisto Livello {livello} - Quantità: {quantita} @ {prezzo_acquisto}")

        await self.piazza_ordine("BUY", quantita)
        
        nuovo_lotto = Lotto(livello, quantita, prezzo_acquisto)
        self.inventario_lotti.append(nuovo_lotto)
        log.info(f"Nuovo lotto aggiunto: Livello {livello}, Qta: {quantita}, Prezzo Acq: {prezzo_acquisto}, Target Vendita: {nuovo_lotto.prezzo_vendita_target}")

        self.prezzo_riferimento_acquisto = prezzo_acquisto
        self.prossimo_livello += 1
        
        self.salva_stato()

    async def piazza_ordine(self, azione, quantita):
        """Crea e invia un ordine a mercato."""
        ordine = MarketOrder(azione, quantita)
        trade = self.ib.placeOrder(self.contratto, ordine)
        log.info(f"Ordine {azione} di {quantita} {SIMBOLO} inviato. OrderId: {trade.order.orderId}")
        await asyncio.sleep(1)


class Lotto:
    """Classe per tenere traccia di ogni singolo acquisto."""
    def __init__(self, livello, quantita, prezzo_acquisto):
        self.livello = int(livello)
        self.quantita = int(quantita)
        self.prezzo_acquisto = float(prezzo_acquisto)
        self.prezzo_vendita_target = float(prezzo_acquisto * (1 + (PROFIT_TARGET_PERCENT / 100)))

    def to_dict(self):
        return self.__dict__

    @staticmethod
    def from_dict(data):
        lotto = Lotto(data['livello'], data['quantita'], data['prezzo_acquisto'])
        lotto.prezzo_vendita_target = data['prezzo_vendita_target']
        return lotto


async def main():
    bot = GridBot(NOME_FILE_CSV, NOME_FILE_STATO)
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Programma terminato.")