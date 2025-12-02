import ccxt
import time
import random
import datetime
import pandas as pd
import pandas_ta as ta
import requests

# ====================================================================
# 1. PARAMÈTRES ET CONFIGURATION
# ====================================================================

# --- Clés API (Binance Testnet Futures) ---
API_KEY = 'YOUR_API_KEY'
SECRET = 'YOUR_SECRET_KEY'

# --- Configuration Telegram ---
TELEGRAM_BOT_TOKEN = '7751726920:AAEMIJqpRw91POu_RDUTN8SOJvMvWSxcuz4' 
TELEGRAM_CHAT_ID = '5104739573' 

# --- Paramètres de Connexion CCXT ---
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future', # Mode Futures pour la simplicité du SHORT
        'testnet': True,
    }
})

# --- Paramètres de Stratégie & Trading ---
TIMEFRAME = '1m'               # Unité de temps de scalping
RSI_LENGTH = 14
RSI_ENTRY_LEVEL = 65           # Entrée SHORT si RSI > 65
RSI_EXIT_LEVEL = 50            # Sortie RSI (si le TP/SL n'est pas touché)

MAX_SYMBOLS_TO_SCAN = 5        # Vitesse : Scanner seulement 5 paires pour un cycle rapide
INITIAL_BALANCE_USDT = 1000.00 # Solde de départ de la simulation (USDT)
ENTRY_SIZE_PERCENT = 0.05      # 5% du capital par position
LEVERAGE = 5                   # Levier souhaité (x5)

# --- Paramètres de Scalping Rapide (Sorties) ---
TAKE_PROFIT_PERCENT = 0.005    # 0.5% (Sortie rapide pour scalping)
STOP_LOSS_PERCENT = 0.01       # 1% (Stop Loss)
TIME_TO_WAIT_SECONDS = 7       # Fréquence : 7 secondes (compromis sûr contre Erreur 429)

# ====================================================================
# 2. GESTION DES POSITIONS ET MESSAGES
# ====================================================================

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
    """Calcule la taille de l'entrée en fonction du % de la balance et du levier."""
    global simulated_balance
    notional_size = simulated_balance * ENTRY_SIZE_PERCENT * LEVERAGE
    return notional_size / current_price

def get_random_pairs(max_count):
    """
    CORRIGÉ : Récupère une liste aléatoire de paires futures/USDT à scanner.
    Cible /USDT pour éviter l'erreur de symbole.
    """
    try:
        markets = exchange.load_markets()
        usdt_futures = [symbol for symbol in markets 
                        if symbol.endswith('/USDT') and 'USD' not in symbol]
                        
        return random.sample(usdt_futures, min(max_count, len(usdt_futures)))
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des symboles: {e}")
        return []

def execute_simulated_trade(symbol, current_price, rsi_value):
    """Execute un trade simulé (ouverture SHORT)."""
    global simulated_balance

    entry_amount = get_entry_size(current_price)
    
    # Enregistrement de la position
    open_positions[symbol] = {
        'direction': 'SHORT',
        'entry_price': current_price,
        'entry_time': datetime.datetime.now(),
        'amount': entry_amount,
        'rsi_at_entry': rsi_value
    }

    # NOTE : PAS DE NOTIFICATION TELEGRAM ICI (pour ne notifier que les clôtures)
    print(f"📝 SHORT OUVERT (SIMULÉ) sur {symbol} | Entrée: {current_price:.4f} | RSI: {rsi_value:.2f}")


def simulate_close_trade(symbol, current_price, reason="RSI Exit"):
    """Simule la clôture d'une position ouverte et envoie la notification."""
    global simulated_balance
    
    position = open_positions.pop(symbol)
    
    entry_price = position['entry_price']
    amount = position['amount']
    
    # Calcul du P&L (SHORT)
    pnl = (entry_price - current_price) * amount
    simulated_balance += pnl
    
    # Envoi de la notification Telegram (UNIQUEMENT pour la clôture)
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

# ====================================================================
# 3. LOGIQUE DE TRADING (SHORT)
# ====================================================================

def check_short_strategy(symbol):
    """Vérifie la stratégie RSI pour les ventes à découvert (SHORT)."""
    try:
        # Récupération des données historiques (OHLCV)
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME,
