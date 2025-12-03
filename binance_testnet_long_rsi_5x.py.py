import ccxt
import pandas as pd
import numpy as np 
# import pandas_ta as ta  # Reste commenté pour la stabilité
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
TELEGRAM_CHAT_ID = '5104739573' 

# --- Paramètres de la Stratégie (LONG) ---
TIMEFRAME = '1m'          
RSI_LENGTH = 14          
RSI_ENTRY_LEVEL = 15     # ACHAT si RSI < 15
MAX_SYMBOLS_TO_SCAN = 10 
TIME_TO_WAIT_SECONDS = 2  

# --- Paramètres de Trading Réel ---
COLLATERAL_AMOUNT_USDC = 20.0  # 🟢 CORRIGÉ : Montant à 20.0 USDC pour garantir le passage du filtre Notional
TAKE_PROFIT_PCT = 0.005        # 0.5% (TP)
STOP_LOSS_PCT = 0.50           # 50% (SL)
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
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Avertissement: Les clés Telegram sont manquantes. Les notifications sont désactivées.")
        return
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    
    try:
        requests.post(url, data=payload, timeout=5).raise_for_status() 
    except requests.exceptions.RequestException as e:
        print(f"❌ ÉCHEC TELEGRAM : {e}")

def get_usdc_symbols():
    """ Récupère des symboles Spot /USDC ou /USDT actifs (simplifié). """
    global exchange
    try:
        markets = exchange.load_markets()
        usdc_symbols = [
            s for s in markets.keys() 
            if s.endswith('/USDC') or s.endswith('/USDT') and markets[s]['spot'] and markets[s]['active']
        ]
        
        if not usdc_symbols:
            print("❌ ALERTE : Aucun symbole Spot /USDC ou /USDT n'a été trouvé.")
            return [] 
            
        print(f"✅ {len(usdc_symbols)} paires Spot actives détectées. Scanning {min(len(usdc_symbols), MAX_SYMBOLS_TO_SCAN)} au hasard.")
        return random.sample(usdc_symbols, min(len(usdc
