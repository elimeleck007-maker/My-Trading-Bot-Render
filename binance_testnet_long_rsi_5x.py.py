import ccxt
import pandas as pd
import numpy as np
import time
import requests
import random
import datetime
import sys
import math

# =====================================================================
# ÉTAPE 1 : CONFIGURATION ET PARAMÈTRES (LONG TRADING SPOT)
# =====================================================================

# --- Clés API (OBLIGATOIRE) ---
API_KEY = 'i6NcQsRfIn0RAWU7AHIBOEsK9ocFIAbjcnpiWyGb4thC10etiIDbHGWZao6BiVZK'
SECRET = '9dSivwWbTFYT0ZlBgdhkdFgAJ0bIT4nFfAWrS2GTO467QiGtsDBzBd6zxFD0758L'

# --- Configuration Telegram (OBLIGATOIRE) ---
TELEGRAM_BOT_TOKEN = '7751726920:AAEMIJqpRw91POu_RDUTN8SOJvMvWSxcuz4'
# ⚠️ ATTENTION : Utilisation du tiret pour l'ID de canal/groupe
TELEGRAM_CHAT_ID = '-5104739573'

# --- Paramètres de la Stratégie (LONG) ---
TIMEFRAME = '1m'
RSI_LENGTH = 14                 
RSI_ENTRY_LEVEL = 15            
MAX_SYMBOLS_TO_SCAN = 30
TIME_TO_WAIT_SECONDS = 3

# --- Paramètres de Trading Réel ---
MAX_OPEN_POSITIONS = 5
# ## MODIFICATION CLÉ ## : Montant réduit pour couvrir les frais (0.1%)
COLLATERAL_AMOUNT_USDC = 1.99   
TAKE_PROFIT_PCT = 0.003         # 0.3%
STOP_LOSS_PCT = 0.50            # 50%
EQUITY_REPORT_INTERVAL_SECONDS = 300

# INITIALISATION DE L'EXCHANGE (BINANCE SPOT SIMPLE)
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
    }
})

# Variables Globales de Suivi
TRANSACTION_COUNT = 0
WIN_COUNT = 0
LOSS_COUNT = 0
last_equity_report_time = 0
open_positions = {}

# =====================================================================
# ÉTAPE 2 : FONCTIONS DE SUPPORT
# =====================================================================

def send_telegram_message(message):
    """ Envoie un message à Telegram sans lever d'exception en cas d'erreur 429. """
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Avertissement: Les clés Telegram sont manquantes. Les notifications sont désactivées.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    
    try:
        response = requests.post(url, data=payload, timeout=5)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        if response.status_code == 429:
            print(f"❌ ÉCHEC TELEGRAM (429): Trop de requêtes. Pause recommandée.")
        else:
            print(f"❌ ÉCHEC TELEGRAM : {e}")

def get_usdc_symbols():
    """ Récupère les symboles Spot actifs, filtrés par Min Notional <= 2.0 USDC. """
    global exchange, MAX_SYMBOLS_TO_SCAN
    try:
        markets = exchange.load_markets()
        eligible_symbols = []
        
        for symbol, market in markets.items():
            is_usdc_usdt = symbol.endswith('/USDC') or symbol.endswith('/USDT')
            is_active_spot = market['spot'] and market['active']
            
            if is_usdc_usdt and is_active_spot:
                min_notional_limit = market['limits']['cost']['min'] if market['limits']['cost'] and market['limits']['cost']['min'] else 0
                
                # Le filtre d'entrée Min Notional doit être <= 2.0 USDC
                if min_notional_limit <= 2.0:
                    eligible_symbols.append(symbol)

        if not eligible_symbols:
            print("❌ ALERTE : Aucun symbole Spot n'a été trouvé avec une taille minimale <= 2 USDC.")
            return []
            
        print(f"✅ {len(eligible_symbols)} paires Spot éligibles (Min Notional <= 2 USDC) détectées. Scanning {min(len(eligible_symbols), MAX_SYMBOLS_TO_SCAN)} au hasard.")
        
        return random.sample(eligible_symbols, min(len(eligible_symbols), MAX_SYMBOLS_TO_SCAN))
        
    except Exception as e:
        print(f"❌ Erreur inattendue dans get_usdc_symbols: {e}")
        return []

def fetch_ohlcv(symbol, timeframe, limit):
    global exchange
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='ms')
        df.set_index('Timestamp', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()

def calculate_rsi(df, length=14):
    """ Calcule le RSI manuellement. """
    df['change'] = df['Close'].diff()
    df['gain'] = df['change'].apply(lambda x: x if x > 0
