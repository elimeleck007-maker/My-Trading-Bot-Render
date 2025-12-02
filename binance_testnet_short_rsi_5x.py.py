import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests 
import random 
import datetime

# =====================================================================
# ÉTAPE 1 : CONFIGURATION ET PARAMÈTRES (CONFIG UTILISATEUR)
# =====================================================================

# --- Clés API (Uniquement pour Telegram) ---
API_KEY = '' 
SECRET = '' 

# --- Configuration Telegram (OBLIGATOIRE) ---
TELEGRAM_BOT_TOKEN = '7751726920:AAEMIJqpRw91POu_RDUTN8SOJvMvWSxcuz4' 
TELEGRAM_CHAT_ID = '5104739573' 

# --- Paramètres de la Stratégie (SHORT) ---
TIMEFRAME = '1m'          # ✅ RESTAURÉ : 1 minute
RSI_LENGTH = 14           
RSI_ENTRY_LEVEL = 70      # ✅ MODIFIÉ : 70 (Condition de surachat très forte)
MAX_SYMBOLS_TO_SCAN = 10  # ✅ RESTAURÉ : 10 symboles
TIME_TO_WAIT_SECONDS = 2  

# --- Paramètres de Simulation (Gains Maximisés) ---
COLLATERAL_AMOUNT_USDC = 2.0   # Maintenu à 2.0 USDC pour les gains
LEVERAGE = 5              
TAKE_PROFIT_PCT = 0.005   # Maintenu à 0.5%
STOP_LOSS_PCT = 0.50      
REPORT_FREQUENCY = 20     

# Paramètre de rapport d'équité périodique
EQUITY_REPORT_INTERVAL_SECONDS = 300 

# --- Capital de Départ Virtuel ---
INITIAL_BALANCE_USDC = 100.0 

# INITIALISATION DE L'EXCHANGE (Mode Public SANS CLÉS - SPOT)
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

last_equity_report_time = 0 


# =====================================================================
# ÉTAPE 2 : FONCTIONS DE SUPPORT (INCHANGÉES)
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
        requests.post(url, data=payload, timeout=5).raise_for_status() 
        
    except requests.exceptions.RequestException as e:
        print(f"❌ ÉCHEC TELEGRAM : {e}")


def get_usdc_symbols():
    # Fonction inchangée
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
        # Utilise MAX_SYMBOLS_TO_SCAN = 10
        return random.sample(usdc_symbols, min(len(usdc_symbols), MAX_SYMBOLS_TO_SCAN))
        
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des symboles: {e}")
        return ['BTC/USDC', 'ETH/USDC', 'BNB/USDC'] 

def fetch_ohlcv(symbol, timeframe, limit):
    # Fonction inchangée
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='ms')
        df.set_index('Timestamp', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()

def check_trade_signal(df):
    """ Vérifie la condition de signal SHORT (RSI > RSI_ENTRY_LEVEL=70). """
    if df.empty or len(df) < RSI_LENGTH:
        return False, None, None
        
    df['RSI_14'] = ta.rsi(df['Close'], length=RSI_LENGTH)
    df.dropna(subset=['RSI_14'], inplace=True) 
    
    if df.empty:
        return False, None, None
        
    last = df.iloc[-1]
    
    # Utilise RSI_ENTRY_LEVEL = 70
    if last['RSI_14'] > RSI_ENTRY_LEVEL: 
        return True, last['Close'], last['RSI_14']
        
    return False, None, None

# =====================================================================
# ÉTAPE 3 : FONCTIONS DE PAPER TRADING (SIMULÉES) (INCHANGÉES)
# =====================================================================

def execute_simulated_trade(symbol, entry_price, rsi_value):
    """ 
    Simule l'ouverture d'une position SHORT.
    """
    global open_positions, SIM_BALANCE_USDC
    
    if SIM_BALANCE_USDC < COLLATERAL_AMOUNT_USDC:
        print(f"❌ Solde simulé insuffisant: {SIM_BALANCE_USDC:.2f} USDC.")
        return False
        
    amount_in_base_asset = (COLLATERAL_AMOUNT_USDC * LEVERAGE) / entry_price
    
    SIM_BALANCE_USDC -= COLLATERAL_AMOUNT_USDC 
    
    open_positions[symbol] = {
        'entry_price': entry_price,
        'borrowed_amount': amount_in_base_asset,
        'entry_time': time.time(),
        'rsi_at_entry': rsi_value, 
        'tp_price': entry_price * (1 - TAKE_PROFIT_PCT), 
        'sl_price': entry_price * (1 + STOP_LOSS_PCT)  
    }
    
    print("-" * 50)
    print(f"📝 SHORT OUVERT (SIMULÉ, Margin 5x) sur {symbol} | Entrée: {entry_price:.4f} | RSI: {rsi_value:.2f}") 
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
    
    if current_price <= trade['tp_price']:
        result = "GAIN (TP)"
        WIN_COUNT += 1
        close_price = trade['tp_price'] 
        
    elif current_price >= trade['sl_price']:
        result = "PERTE (SL)"
        LOSS_COUNT += 1
        close_price = trade['sl_price']

    else:
        return False 

    percentage_change = (trade['entry_price'] - close_price) / trade['entry_price'] 
    pnl_usd = percentage_change * (COLLATERAL_AMOUNT_USDC * LEVERAGE)
    
    SIM_BALANCE_USDC += COLLATERAL_AMOUNT_USDC + pnl_usd
    
    TRANSACTION_COUNT += 1
    del open_positions[symbol] 
    
    # 🔔 ENVOI DU MESSAGE À LA CLÔTURE
    print(f"--- 🔔 {symbol} FERMÉ: {result} ---")
    send_telegram_message(
        f"🚨 **CLÔTURE SHORT (SIMULÉE) - {result}**\n"
        f"==================================\n"
        f"Asset: **{symbol}**\n"
        f"P&L du Trade: **{pnl_usd:.4f} USDC**\n"
        f"Prix d'Entrée: {trade['entry_price']:.4f}\n"
        f"Prix de Clôture: {close_price:.4f}\n"
        f"==================================\n"
        f"💰 **SOLDE DISPONIBLE ACTUEL: {SIM_BALANCE_USDC:.2f} USDC**"
    )
    
    if TRANSACTION_COUNT % REPORT_FREQUENCY == 0:
        generate_report()

    return True

# =====================================================================
# ÉTAPE 4 : FONCTIONS DE RAPPORT D'ÉQUITÉ ET DE P&L (INCHANGÉES)
# =====================================================================

def get_unrealized_pnl_and_collateral():
    # Fonction inchangée
    total_unrealized_pnl = 0.0
    total_collateral_engaged = 0.0
