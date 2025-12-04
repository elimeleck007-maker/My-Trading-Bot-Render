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
TELEGRAM_CHAT_ID = '-5104739573' # ⚠️ CORRECTION : Utilisation du tiret pour l'ID de canal/groupe

# --- Paramètres de la Stratégie (LONG) ---
TIMEFRAME = '1m'
RSI_LENGTH = 14                 # LONGUEUR DEMANDÉE: 14
RSI_ENTRY_LEVEL = 15            # SEUIL DEMANDÉ: 15
MAX_SYMBOLS_TO_SCAN = 30
TIME_TO_WAIT_SECONDS = 3

# --- Paramètres de Trading Réel ---
MAX_OPEN_POSITIONS = 5
# ⚠️ CORRECTION : Montant réduit pour couvrir les frais de transaction (0.1%)
COLLATERAL_AMOUNT_USDC = 1.99   
TAKE_PROFIT_PCT = 0.003         # TP DEMANDÉ: 0.3% (0.003)
STOP_LOSS_PCT = 0.50            # SL DEMANDÉ: 50% (0.50)
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
        # ⚠️ CORRECTION : Vérification du statut de la réponse pour détecter le 429
        response = requests.post(url, data=payload, timeout=5)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        # Gestion simplifiée de l'erreur pour éviter le blocage 429 répétitif
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
    
    # VÉRIFICATION : Ne pas ouvrir si la limite maximale est atteinte
    if len(open_positions) >= MAX_OPEN_POSITIONS:
        print(f"❌ REJET {symbol}: Limite de {MAX_OPEN_POSITIONS} positions ouvertes atteinte.")
        return False

    quote_asset = exchange.markets[symbol]['quote']
    
    # ⚠️ CORRECTION 1 : Vérification et ajustement du solde réel disponible
    try:
        balance = exchange.fetch_balance(params={'type': 'spot'})
        available_usdc_usdt = balance['free'].get(quote_asset, 0)
        
        # Le montant à utiliser est le minimum entre l'objectif (1.99) et le solde réel disponible
        collateral_to_use = min(COLLATERAL_AMOUNT_USDC, available_usdc_usdt)
        
        min_notional = exchange.markets[symbol]['limits']['cost']['min']
        
        if collateral_to_use < min_notional:
             print(f"❌ REJET {symbol}: Solde disponible ({available_usdc_usdt:.4f} {quote_asset}) insuffisant ou inférieur au minimum notionnel ({min_notional:.4f}).")
             return False

    except Exception as e:
        print(f"❌ ERREUR VÉRIFICATION SOLDE {symbol}: {e}")
        return False
    
    # 1. Calcul de la quantité à acheter (base_asset)
    amount_base_asset = collateral_to_use / entry_price
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
        # Supprimé l'envoi Telegram direct ici pour éviter le 429 répétitif en cas de solde nul
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

    # ⚠️ CORRECTION 2 : Interroger le solde réel disponible sur le compte Binance
    base_asset = symbol.split('/')[0]
    try:
        balance = exchange.fetch_balance(params={'type': 'spot'})
        # Utiliser la quantité "free" (disponible) réelle sur Binance
        amount_to_sell = balance['free'].get(base_asset, 0)
        
        # Appliquer la précision de l'exchange au solde réel
        amount_to_sell = exchange.amount_to_precision(symbol, amount_to_sell)

        if float(amount_to_sell) < exchange.markets[symbol]['limits']['amount']['min']: 
             print(f"⚠️ CLÔTURE {symbol}: Solde disponible ({amount_to_sell}) est sous la taille minimale. Position locale supprimée.")
             del open_positions[symbol]
             return False

    except Exception as e:
        print(f"❌ ERREUR LORS DE LA VÉRIFICATION DE SOLDE RÉEL pour {symbol}: {e}")
        return False

    try:
        # COMMANDE DE VENTE (LONG EXIT)
        order = exchange.create_order(
            symbol, 
            'market', 
            'sell', 
            float(amount_to_sell) # Utiliser le solde réel disponible et précis
        )
        
        TRANSACTION_COUNT += 1
        
        # 4. Calcul du P&L (Simplifié)
        real_close_price = float(order.get('average', close_price))
        pnl_usd = float(order.get('filled', amount_to_sell)) * (real_close_price - trade['entry_price'])
        
        # 5. Notification Telegram
        send_telegram_message(
            f"🚨 **CLÔTURE LONG SPOT - {result_type}**\n"
            f"--- **{symbol}** ---\n"
            f"P&L estimé: **{pnl_usd:.4f} {trade['quote_asset']}**\n"
            f"Clôture: {real_close_price:.4f}"
        )
        
        print(f"--- 🔔 {symbol} FERMÉ: {result_type} ---")
        del open_positions[symbol]
        return True

    except ccxt.ExchangeError as e:
        print(f"❌ ERREUR CLÔTURE {symbol} (SPOT): {e}")
        return False
    except Exception as e:
        print(f"❌ Erreur inattendue de clôture: {e}")
        return False

def get_live_equity_and_pnl():
    """ Récupère le solde réel du compte Spot pour le rapport. """
    global exchange
    try:
        balance = exchange.fetch_balance(params={'type': 'spot'})
        # Ne considérer que le solde libre (non utilisé dans un ordre) pour les USDC/USDT
        total_usd_balance = balance['free'].get('USDC', 0) + balance['free'].get('USDT', 0)
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
        print("Veuillez vérifier vos API KEY/SECRET et
