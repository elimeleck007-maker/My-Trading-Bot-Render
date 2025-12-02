import time
import requests
import random
import datetime
import ccxt
import pandas as pd
import pandas_ta as ta

# =====================================================================
# ÉTAPE 1 : CONFIGURATION ET PARAMÈTRES (SIMULATION SHORT)
# =====================================================================

# --- Clés API ---
API_KEY = 'VOTRE_CLE_API' 
SECRET = 'VOTRE_SECRET_API' 

# --- Configuration Telegram ---
TELEGRAM_BOT_TOKEN = '7751726920:AAEMIJqpRw91POu_RDUTN8SOJvMvWSxcuz4' 
TELEGRAM_CHAT_ID = '5104739573' 

# --- Paramètres de Connexion CCXT ---
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'testnet': True,
    }
})

# --- Paramètres de la Stratégie (SHORT) ---
TIMEFRAME = '1m'
RSI_LENGTH = 14
RSI_ENTRY_LEVEL = 65     # Entrée SHORT si RSI > 65
RSI_EXIT_LEVEL = 50      # NON UTILISÉ pour la sortie
MAX_SYMBOLS_TO_SCAN = 5  
INITIAL_BALANCE_USDT = 1000.0 # Utilisé en USDT pour la compatibilité API
ENTRY_SIZE_PERCENT = 0.05 
MAX_OPEN_POSITIONS = 30 

# --- Scalping / Fréquence du Cycle ---
PROFIT_SCALPING_PERCENT = 0.005 # Take Profit fixe à 0.5%
STOP_LOSS_PERCENT = 0.05        # 🔴 MODIFIÉ : Stop Loss fixe à 5.0%
TIME_TO_WAIT_SECONDS = 7 

# =====================================================================
# ÉTAPE 2 : GESTION DES POSITIONS ET MESSAGES (SHORT)
# =====================================================================

open_positions = {}
simulated_balance = INITIAL_BALANCE_USDT

def send_telegram_message(message):
    """Envoie un message via l'API Telegram."""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown'
        }
        try:
            requests.post(url, data=payload, timeout=5)
        except Exception as e:
            print(f"[ERREUR TELEGRAM] Impossible d'envoyer le message : {e}")

def get_entry_size(current_price):
    """Calcule la taille de l'entrée en fonction du % de la balance."""
    global simulated_balance
    amount_to_risk = simulated_balance * ENTRY_SIZE_PERCENT
    return amount_to_risk / current_price

def get_random_pairs(max_count):
    """
    CORRECTION : Récupère une liste aléatoire de paires futures/USDT valides.
    """
    try:
        markets = exchange.load_markets()
        usdt_futures = [symbol for symbol in markets 
                        if symbol.endswith('/USDT') and 'USD' not in symbol]
        return random.sample(usdt_futures, min(max_count, len(usdt_futures)))
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des symboles: {e}")
        return []

def execute_simulated_trade(symbol, direction, current_price, rsi_value):
    """Execute un trade simulé (ouverture)."""
    global simulated_balance

    entry_amount = get_entry_size(current_price)
    
    open_positions[symbol] = {
        'symbol': symbol,
        'direction': direction,
        'entry_price': current_price,
        'entry_time': datetime.datetime.now(),
        'amount': entry_amount,
        'rsi_at_entry': rsi_value
    }
    
    # PAS DE NOTIFICATION TELEGRAM À L'OUVERTURE
    print(f"📝 SHORT OUVERT (SIMULÉ) sur {symbol} | Entrée: {current_price:.4f} | RSI: {rsi_value:.2f}")

def simulate_close_trade(symbol, current_price, reason="Clôture"):
    """Simule la clôture d'une position ouverte et ENVOIE LA NOTIFICATION."""
    global simulated_balance
    
    position = open_positions.pop(symbol)
    
    entry_price = position['entry_price']
    amount = position['amount']
    
    # Calcul du P&L (SHORT)
    pnl = (entry_price - current_price) * amount
        
    simulated_balance += pnl
    
    # Alerte Telegram (UNIQUEMENT POUR LA CLÔTURE)
    direction = position['direction']
    pnl_percent = (pnl / (position['entry_price'] * amount)) * 100
    
    message = (
        f"--------------------------------------------------\n"
        f"❌ {direction.upper()} CLÔTURÉ ({reason}) sur {symbol}\n"
        f"  | Entrée: {entry_price:.4f} | Clôture: {current_price:.4f}\n"
        f"  | P&L: **{pnl:.2f} USDT ({pnl_percent:.2f}%)**\n"
        f"  | Nouvelle Balance: {simulated_balance:.2f} USDT\n"
        f"--------------------------------------------------"
    )
    print(message)
    send_telegram_message(message)

# =====================================================================
# ÉTAPE 3 : LOGIQUE DE TRADING (SHORT)
# =====================================================================

def check_short_strategy(symbol):
    """Vérifie la stratégie RSI pour les ventes à découvert (SHORT)."""
    try:
        # Récupération des données historiques (OH
