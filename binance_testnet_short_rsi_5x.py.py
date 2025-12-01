import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests 
import random 
import datetime

# =====================================================================
# ÉTAPE 1 : CONFIGURATION ET PARAMÈTRES (SIMULATION PURE)
# =====================================================================

# --- Clés API (Uniquement pour Telegram) ---
API_KEY = '' 
SECRET = ''  

# --- Configuration Telegram (OBLIGATOIRE) ---
TELEGRAM_BOT_TOKEN = '7751726920:AAEMIJqpRw91POu_RDUTN8SOJvMvWSxcuz4' 
# 🛑 IMPORTANT : METTRE ICI VOTRE CHAT ID NUMÉRIQUE CORRECT (ex: -1234567890)
TELEGRAM_CHAT_ID = '5104739573' 

# --- Paramètres de la Stratégie (SHORT) ---
TIMEFRAME = '1m'        
RSI_LENGTH = 14         
RSI_ENTRY_LEVEL = 70    # Signal SHORT : Vente si RSI > 70 (Surachat)
MAX_SYMBOLS_TO_SCAN = 20 # Nombre de symboles scannés par cycle
TIME_TO_WAIT_SECONDS = 2 # 🟢 Fréquence du cycle : 2 secondes
# Pas de limite MAX_OPEN_TRADES

# --- Paramètres de Simulation ---
TRADE_AMOUNT_USDC = 1.0  # Capital simulé par trade (en USDC)
LEVERAGE = 5             # Levier simulé
TAKE_PROFIT_PCT = 0.015  # 1.5% de Take Profit
STOP_LOSS_PCT = 0.50     # 50% de Stop Loss
REPORT_FREQUENCY = 20    # Fréquence des rapports

# --- Capital de Départ Virtuel ---
INITIAL_BALANCE_USDC = 100.0 

# INITIALISATION DE L'EXCHANGE (Mode Public SANS CLÉS)
exchange = ccxt.binance({
    'enableRateLimit': True, 
    'options': {
        'defaultType': 'spot', 
    }
})

# --- Variables Globales de Suivi de Performance (Simulées) ---
TRANSACTION_COUNT = 0                 
WIN_COUNT = 0                         
LOSS_COUNT = 0                        
open_positions = {}                   
SIM_BALANCE_USDC = INITIAL_BALANCE_USDC 

# =====================================================================
# ÉTAPE 2 : FONCTIONS DE SUPPORT
# =====================================================================

def send_telegram_message(message):
    """ Envoie un message via l'API Telegram. """
    
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ CONFIGURATION INCOMPLÈTE : Token ou Chat ID manquant.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status() 
        
    except requests.exceptions.RequestException as e:
        print(f"❌ ÉCHEC TELEGRAM : {e}")


def get_usdc_symbols():
    """ 
    Récupère toutes les paires XXX/USDC disponibles sur l'API publique.
    """
    try:
        temp_exchange = ccxt.binance({
            'enableRateLimit': True, 
            'options': {'defaultType': 'public'}
        })
        markets = temp_exchange.load_markets() 
        usdc_symbols = [
            s for s in markets.keys() 
            if s.endswith('/USDC') and markets[s]['active'] and not s.endswith(('DOWN/USDC', 'UP/USDC'))
        ]
        return random.sample(usdc_symbols, min(len(usdc_symbols), MAX_SYMBOLS_TO_SCAN))
        
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des symboles: {e}")
        return ['BTC/USDC', 'ETH/USDC', 'BNB/USDC'] 

def fetch_ohlcv(symbol, timeframe, limit):
    """ Récupère les données de prix de Binance. """
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='ms')
        df.set_index('Timestamp', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()

def check_trade_signal(df):
    """ Vérifie la condition de signal SHORT (RSI > 70). """
    if df.empty or len(df) < RSI_LENGTH:
        return False, None
        
    # Calcul des indicateurs
    df['RSI_14'] = ta.rsi(df['Close'], length=RSI_LENGTH)
    df.dropna(subset=['RSI_14'], inplace=True) 
    
    if df.empty:
        return False, None
        
    last = df.iloc[-1]
    
    # LOGIQUE SHORT : Vente si RSI > 70 (Surachat)
    if last['RSI_14'] > RSI_ENTRY_LEVEL: 
        return True, last['Close']
        
    return False, None

# =====================================================================
# ÉTAPE 3 : FONCTIONS DE PAPER TRADING (SIMULÉES)
# =====================================================================

def execute_simulated_trade(symbol, entry_price):
    """ 
    Simule l'ouverture d'une position SHORT (Ordre de Marché).
    """
    global open_positions, SIM_BALANCE_USDC
    
    if SIM_BALANCE_USDC < TRADE_AMOUNT_USDC:
        print(f"❌ Impossible d'ouvrir SHORT sur {symbol}. Solde simulé insuffisant: {SIM_BALANCE_USDC:.2f} USDC.")
        return False
        
    amount_in_base_asset = (TRADE_AMOUNT_USDC * LEVERAGE) / entry_price
    
    SIM_BALANCE_USDC -= TRADE_AMOUNT_USDC
    
    open_positions[symbol] = {
        'entry_price': entry_price,
        'amount': amount_in_base_asset,
        'entry_time': time.time(),
        # Calcul inverse pour SHORT :
        'tp_price': entry_price * (1 - TAKE_PROFIT_PCT), # TP = Prix en baisse de 1.5%
        'sl_price': entry_price * (1 + STOP_LOSS_PCT)  # SL = Prix en hausse de 50%
    }
    
    print("-" * 50)
    print(f"📝 SHORT OUVERT (SIMULÉ, Ordre de Marché) sur {symbol} | Entrée: {entry_price:.4f}") 
    return True

def simulate_close_trade(symbol, current_price):
    """ 
    Simule la fermeture d'une position (TP ou SL) et met à jour le P&L virtuel.
    """
    global open_positions, TRANSACTION_COUNT, WIN_COUNT, LOSS_COUNT, SIM_BALANCE_USDC
    
    if symbol not in open_positions:
        return False

    trade = open_positions[symbol]
    
    result = None
    close_price = current_price
    
    # 1. Vérification TP/SL (LOGIQUE SHORT)
    if current_price <= trade['tp_price']:
        # 🟢 GAIN : Le prix a baissé jusqu'au TP 🟢
        result = "GAIN (TP)"
        WIN_COUNT += 1
        close_price = trade['tp_price'] # Exécution au prix limite exact
        
    elif current_price >= trade['sl_price']:
        # 🔴 PERTE : Le prix a monté jusqu'au SL 🔴
        result = "PERTE (SL)"
        LOSS_COUNT += 1

    else:
        return False # Pas de clôture, le script continue

    # 2. Calcul du P&L simulé 
    percentage_change = (trade['entry_price'] - close_price) / trade['entry_price'] 
    pnl_usd = percentage_change * (TRADE_AMOUNT_USDC * LEVERAGE)
    
    # 3. Mise à jour du solde virtuel (Capital initial + P&L)
    SIM_BALANCE_USDC += TRADE_AMOUNT_USDC + pnl_usd
    
    # 4. Mise à jour des statistiques et suppression de la position
    TRANSACTION_COUNT += 1
    del open_positions[symbol] 
    
    # 🔔 ENVOI DU MESSAGE À LA CLÔTURE (TP ou SL validé) 🔔
    print(f"--- 🔔 {symbol} FERMÉ: {result} ---")
    send_telegram_message(
        f"🚨 **CLÔTURE SHORT (SIMULÉE) - {result}**\n"
        f"==================================\n"
        f"Asset: **{symbol}**\n"
        f"P&L du Trade: **{pnl_usd:.4f} USDC**\n"
        f"Prix d'Entrée: {trade['entry_price']:.4f}\n"
        f"Prix de Clôture (Simulé): {close_price:.4f}\n"
        f"==================================\n"
        f"💰 **NOUVEAU SOLDE VIRTUEL TOTAL: {SIM_BALANCE_USDC:.2f} USDC**"
    )
    
    if TRANSACTION_COUNT % REPORT_FREQUENCY == 0:
        generate_report()

    return True

# =====================================================================
# ÉTAPE 4 : FONCTIONS DE RAPPORT
# =====================================================================

def generate_report():
    """ Génère et envoie le rapport de performance sur Telegram. """
    global TRANSACTION_COUNT, WIN_COUNT, LOSS_COUNT, INITIAL_BALANCE_USDC, SIM_BALANCE_USDC

    win_rate = (WIN_COUNT / TRANSACTION_COUNT) * 100 if TRANSACTION_COUNT > 0 else 0
    pnl_total = SIM_BALANCE_USDC - INITIAL_BALANCE_USDC
    
    report_message = (
        f"📊 **RAPPORT DE PERFORMANCE (PAPER TRADING)**\n"
        f"--- {time.strftime('%Y-%m-%d %H:%M')} ---\n"
        f"➡️ **Solde Virtuel Actuel : {SIM_BALANCE_USDC:.2f} USDC**\n"
        f"💰 P&L Total : {pnl_total:.2f} USDC\n"
        f"-----------------------------------------\n"
        f"📝 **Statistiques (Total Trades : {TRANSACTION_COUNT})**\n"
        f"✅ Trades Gagnants (TP) : {WIN_COUNT}\n"
        f"❌ Trades Perdants (SL) : {LOSS_COUNT}\n"
        f"📈 Taux de Succès : {win_rate:.2f} %"
    )
    send_telegram_message(report_message)

# =====================================================================
# ÉTAPE 5 : LA BOUCLE PRINCIPALE 24/7 (AVEC GESTION D'ERREURS)
# =====================================================================

def run_bot():
    """ Boucle principale qui exécute l'analyse et la simulation sur toutes les cryptos. """
    
    print(f"🤖 Bot SHORT MULTI-CRYPTO PAPER TRADING démarré (RSI > {RSI_ENTRY_LEVEL}, 1m, SCAN/{TIME_TO_WAIT_SECONDS}S).")
    print(f"🔔 MODE SIMULATION. Solde virtuel de départ: {INITIAL_BALANCE_USDC:.2f} USDC")
    
    while True:
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            
            usdc_symbols = get_usdc_symbols() 
            print(f"\n[{timestamp}] --- Scan du marché démarré ({len(usdc_symbols)} symboles, {len(open_positions)} positions ouvertes) ---")
            
            
            for symbol in usdc_symbols:
                
                data = fetch_ohlcv(symbol, TIMEFRAME, limit=RSI_LENGTH + 5)
                
                if data.empty:
                    continue

                current_price = data['Close'].iloc[-1]
                
                # A. GESTION DES POSITIONS EXISTANTES
                if symbol in open_positions:
                    simulate_close_trade(symbol, current_price) 
                
                # B. RECHERCHE DE NOUVEAUX SIGNAUX (SANS limite)
                elif symbol not in open_positions: 
                    signal_detected, entry_price = check_trade_signal(data)
                    
                    if signal_detected:
                        execute_simulated_trade(symbol, entry_price) 


            # 4. Temps d'attente fixe (2 secondes)
            print(f"Fin du cycle. Prochain scan dans {TIME_TO_WAIT_SECONDS} seconde(s).")
            time.sleep(TIME_TO_WAIT_SECONDS) 

        except requests.exceptions.RequestException as e:
            error_message = f"❌ ALERTE CONNEXION : Erreur réseau ou API. Détail: {e}"
            print(error_message)
            send_telegram_message(f"⚠️ **ALERTE CONNEXION RÉSEAU** ⚠️\n{error_message}")
            time.sleep(15) 

        except Exception as e:
            error_message = f"❌ ERREUR CRITIQUE DANS LE BOT : Le bot va redémarrer le cycle. Détail: {e}"
            print(error_message)
            send_telegram_message(f"🚨 **ALERTE CRASH POTENTIEL** 🚨\n{error_message}")
            time.sleep(30) 

# Décommentez la ligne ci-dessous pour lancer le bot !
run_bot()
