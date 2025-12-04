import ccxt
import pandas as pd
import numpy as np 
# import pandas_ta as ta 
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
RSI_ENTRY_LEVEL = 15     # ACHAT si RSI < 15 (Ultra-survente)
MAX_SYMBOLS_TO_SCAN = 15 # Scan de 15 paires
TIME_TO_WAIT_SECONDS = 3  # 3 secondes d'attente

# --- Paramètres de Trading Réel ---
MAX_OPEN_POSITIONS = 5         # 🟢 NOUVEAU : Limite maximale de positions ouvertes en simultané
COLLATERAL_AMOUNT_USDC = 2.0   # Montant misé par transaction (2.0 USDC maximum)
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
    """ Récupère les symboles Spot actifs, filtrés par Min Notional <= 2.0 USDC. """
    global exchange, MAX_SYMBOLS_TO_SCAN
    try:
        markets = exchange.load_markets()
        eligible_symbols = []
        
        for symbol, market in markets.items():
            is_usdc_usdt = symbol.endswith('/USDC') or symbol.endswith('/USDT')
            is_active_spot = market['spot'] and market['active']
            
            if is_usdc_usdt and is_active_spot:
                # Tente de récupérer la limite minimale notionale (coût)
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
    """ Calcule le RSI manuellement en utilisant Pandas/Numpy. """
    df['change'] = df['Close'].diff()
    df['gain'] = df['change'].apply(lambda x: x if x > 0 else 0)
    df['loss'] = df['change'].apply(lambda x: abs(x) if x < 0 else 0)

    # Calcul de la moyenne mobile exponentielle (EMA) pour le lissage
    df['avg_gain'] = df['gain'].ewm(com=length - 1, adjust=False).mean()
    df['avg_loss'] = df['loss'].ewm(com=length - 1, adjust=False).mean()

    # Calcul du RS (Relative Strength)
    df['rs'] = df['avg_gain'] / df['avg_loss']
    
    # Calcul du RSI
    df['RSI'] = 100 - (100 / (1 + df['rs']))
    
    return df['RSI']

def check_trade_signal(df):
    """ APPLIQUE LA LOGIQUE RSI IMMÉDIATEMENT (avec calcul manuel). """
    global RSI_LENGTH, RSI_ENTRY_LEVEL
    
    if df.empty or len(df) <= RSI_LENGTH: 
        return False, None, None
        
    df['RSI_14'] = calculate_rsi(df, length=RSI_LENGTH)
    
    df.dropna(subset=['RSI_14'], inplace=True) 
    
    if df.empty:
        return False, None, None
        
    last = df.iloc[-1]
    
    # LOGIQUE LONG : Acheter si le RSI est sous le seuil
    if last['RSI_14'] < RSI_ENTRY_LEVEL: 
        return True, last['Close'], last['RSI_14']
        
    return False, None, None

# =====================================================================
# ÉTAPE 3 : FONCTIONS DE LIVE TRADING (SPOT)
# =====================================================================

def execute_live_trade(symbol, entry_price, rsi_value=None):
    """ Exécute un trade LONG (achat simple) réel sur Binance Spot. """
    global open_positions, exchange, COLLATERAL_AMOUNT_USDC, MAX_OPEN_POSITIONS
    
    # 🟢 VÉRIFICATION : Ne pas ouvrir si la limite maximale est atteinte
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        print(f"❌ REJET {symbol}: Limite de {MAX_OPEN_POSITIONS} positions ouvertes atteinte.")
        return False

    quote_asset = exchange.markets[symbol]['quote'] 
    
    # 1. Calcul de la quantité à acheter (base_asset)
    amount_base_asset = COLLATERAL_AMOUNT_USDC / entry_price
    amount_base_asset = exchange.amount_to_precision(symbol, amount_base_asset)
    
    try:
        # COMMANDE D'ACHAT (LONG ENTRY SPOT)
        order = exchange.create_order(
            symbol, 
            'market', 
            'buy', 
            amount_base_asset
        )
        
        real_entry_price = float(order.get('average', entry_price)) 
        real_amount_base = float(order.get('filled', amount_base_asset))

        # 2. Calcul des prix TP et SL
        tp_price = real_entry_price * (1 + TAKE_PROFIT_PCT)
        sl_price = real_entry_price * (1 - STOP_LOSS_PCT) 
        tp_price = exchange.price_to_precision(symbol, tp_price)
        sl_price = exchange.price_to_precision(symbol, sl_price)

        # 3. Enregistrement de la position
        open_positions[symbol] = {
            'amount': real_amount_base, 
            'entry_price': real_entry_price,
            'tp_price': tp_price, 
            'sl_price': sl_price,
            'quote_asset': quote_asset
        }

        # 4. Notification Telegram
        send_telegram_message(
            f"✅ **LONG OUVERT - LIVE SPOT** ({len(open_positions)}/{MAX_OPEN_POSITIONS})\n"
            f"=======================\n"
            f"Asset: **{symbol}** (RSI: {rsi_value:.2f})\n"
            f"Entrée: {open_positions[symbol]['entry_price']:.4f}\n"
            f"Montant: {real_amount_base:.4f} {symbol.split('/')[0]}\n"
            f"TP: {tp_price:.4f} | SL: {sl_price:.4f}"
        )
        
        print(f"📝 LONG OUVERT (SPOT) sur {symbol} | Entrée: {real_entry_price:.4f}")
        return True

    except ccxt.ExchangeError as e:
        error_msg = f"❌ ÉCHEC TRADING {symbol} (LONG SPOT) : {e}"
        print(error_msg)
        send_telegram_message(f"🚨 **ÉCHEC DU TRADE SPOT** : {symbol}\n{error_msg}")
        return False
    except Exception as e:
        print(f"❌ ERREUR CRITIQUE DANS execute_live_trade: {e}")
        return False

def close_live_trade(symbol, current_price):
    """ Gère la fermeture d'une position Long Spot (TP/SL) par la vente. """
    global open_positions, TRANSACTION_COUNT, WIN_COUNT, LOSS_COUNT, exchange
    
    if symbol not in open_positions:
        return False

    trade = open_positions[symbol]
    
    # 1. Vérification TP/SL
    result_type = None
    # LONG TP: Si le prix actuel est >= prix TP
    if current_price >= float(trade['tp_price']):
        result_type = "GAIN (TP)"
        WIN_COUNT += 1
        close_price = trade['tp_price'] 
    # LONG SL: Si le prix actuel est <= prix SL
    elif current_price <= float(trade['sl_price']):
        result_type = "PERTE (SL)"
        LOSS_COUNT += 1
        close_price = trade['sl_price']
    else:
        return False 

    # CORRECTION CRITIQUE : Tolérance aux frais et précision
    FEE_TOLERANCE = 0.9999 # Réduit de 0.01% pour laisser de la marge pour les frais et la précision
    amount_to_sell = trade['amount'] * FEE_TOLERANCE
    amount_to_sell = exchange.amount_to_precision(symbol, amount_to_sell)

    try:
        # COMMANDE DE VENTE (LONG EXIT)
        order = exchange.create_order(
            symbol, 
            'market', 
            'sell', 
            amount_to_sell
        )
        
        TRANSACTION_COUNT += 1
        
        # 4. Calcul du P&L (Simplifié)
        real_close_price = float(order.get('average', close_price))
        pnl_usd = amount_to_sell * (real_close_price - trade['entry_price'])
        
        # 5. Notification Telegram
        send_telegram_message(
            f"🚨 **CLÔTURE LONG SPOT - {result_type}**\n"
            f"P&L estimé: **{pnl_usd:.4f} {trade['quote_asset']}**\n"
        )
        
        print(f"--- 🔔 {symbol} FERMÉ: {result_type} ---")
        del open_positions[symbol]
        return True

    except ccxt.ExchangeError as e:
        print(f"❌ ERREUR CLÔTURE {symbol} (SPOT): {e}")
        send_telegram_message(f"🚨 **ÉCHEC DE CLÔTURE SPOT** : {symbol}\n{e}")
        return False
    except Exception as e:
        print(f"❌ Erreur inattendue de clôture: {e}")
        return False

def get_live_equity_and_pnl():
    """ Récupère le solde réel du compte Spot pour le rapport. """
    global exchange
    try:
        balance = exchange.fetch_balance(params={'type': 'spot'})
        total_usd_balance = balance['total'].get('USDC', 0) + balance['total'].get('USDT', 0)
        return float(total_usd_balance)

    except Exception as e:
        return 0.0

def send_equity_report():
    """ Envoie le solde SPOT et les positions ouvertes. """
    total_spot_balance = get_live_equity_and_pnl()
    
    report_message = (
        f"⏰ **MISE À JOUR SPOT**\n"
        f"--- {time.strftime('%Y-%m-%d %H:%M')} ---\n"
        f"💵 **Solde SPOT (USDC/USDT) : {total_spot_balance:.2f}**\n"
        f"💼 Positions ouvertes : {len(open_positions)}"
    )
    send_telegram_message(report_message)

# =====================================================================
# ÉTAPE 5 : LA BOUCLE PRINCIPALE 24/7
# =====================================================================

def run_bot():
    """ Boucle principale qui exécute l'analyse et le trading réel. """
    global last_equity_report_time
    global exchange 
    
    print(">>> PYTHON SCRIPT STARTED: Tentative de connexion API Binance...")
    
    try:
        exchange.fetch_balance(params={'type': 'spot'})
        print(f"✅ CONNEXION BINANCE SPOT ÉTABLIE.")
    except Exception as e:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"❌ ERREUR CRITIQUE DE CONNEXION/AUTHENTIFICATION: {e}")
        print("Veuillez vérifier vos API KEY/SECRET et l'accès Spot. Arrêt du bot.")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        
        sys.exit(1) 

    print(f"🤖 Bot LONG SPOT démarré (RSI < {RSI_ENTRY_LEVEL}, UT: {TIMEFRAME}).")
    
    last_equity_report_time = time.time()
    
    while True:
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            
            usdc_symbols = get_usdc_symbols() 
            
            if not usdc_symbols:
                print(f"\n[{timestamp}] --- AUCUNE PAIRE SPOT ÉLIGIBLE TROUVÉE. Vérification dans 60s. ---")
                time.sleep(60)
                continue
                
            print(f"\n[{timestamp}] --- Scan du marché démarré ({len(usdc_symbols)} symboles scannés, {len(open_positions)} positions ouvertes locales) ---")
            
            
            # 1. GESTION DES POSITIONS EXISTANTES
            symbols_to_check = list(open_positions.keys())
            for symbol in symbols_to_check:
                data = fetch_ohlcv(symbol, TIMEFRAME, limit=1)
                if not data.empty:
                    current_price = data['Close'].iloc[-1]
                    close_live_trade(symbol, current_price) 
            
            # 2. RECHERCHE DE NOUVEAUX SIGNAUX
            for symbol in usdc_symbols:
                # 🔴 VÉRIFICATION : SAUT DE NOUVELLES POSITIONS SI LA LIMITE EST ATTEINTE
                if len(open_positions) >= MAX_OPEN_POSITIONS:
                    break 
                
                if symbol in open_positions: 
                    continue
                    
                data = fetch_ohlcv(symbol, TIMEFRAME, limit=RSI_LENGTH + 10)
                
                if data.empty:
                    continue
                
                # Le signal utilise le calcul RSI manuel
                signal_detected, entry_price, rsi_value = check_trade_signal(data) 
                
                if signal_detected:
                    execute_live_trade(symbol, entry_price, rsi_value) 

            # GESTION DU RAPPORT D'ÉQUITÉ PÉRIODIQUE
            if (time.time() - last_equity_report_time) >= EQUITY_REPORT_INTERVAL_SECONDS:
                send_equity_report()
                last_equity_report_time = time.time()
                
            total_spot_balance = get_live_equity_and_pnl()
            print(f"💵 **Solde SPOT (USDC/USDT) : {total_spot_balance:.2f}**")
            
            print(f"Fin du cycle. Prochain scan dans {TIME_TO_WAIT_SECONDS} seconde(s).")
            time.sleep(TIME_TO_WAIT_SECONDS) 

        except ccxt.RateLimitExceeded as e:
            print(f"❌ ALERTE BINANCE: Limite de débit atteinte. Pause prolongée. Détail: {e}")
            time.sleep(60)
            
        except requests.exceptions.RequestException as e:
            error_message = f"❌ ALERTE CONNEXION : Erreur réseau ou API. Détail: {e}"
            print(error_message)
            send_telegram_message(f"⚠️ **ALERTE CONNEXION RÉSEAU** ⚠️\n{error_message}")
            time.sleep(15) 

        except Exception as e:
            error_message = f"❌ ERREUR CRITIQUE DANS LE BOT : Redémarrage du cycle. Détail: {e}"
            print(error_message)
            send_telegram_message(f"🚨 **ALERTE CRASH POTENTIEL** 🚨\n{error_message}")
            time.sleep(30) 

# =====================================================================
# Lancement de l'exécution
# =====================================================================

run_bot()