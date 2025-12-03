import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests 
import random 
import datetime

# =====================================================================
# ÉTAPE 1 : CONFIGURATION ET PARAMÈTRES (LIVE TRADING SPOT MARGIN)
# =====================================================================

# --- Clés API (OBLIGATOIRE pour le Live Trading) ---
# 🚨🚨 REMPLACEZ PAR VOS VRAIES CLÉS BINANCE SPOT ! 🚨🚨
API_KEY = 'i6NcQsRfIn0RAWU7AHIBOEsK9ocFIAbjcnpiWyGb4thC10etiIDbHGWZao6BiVZK' 
SECRET = '9dSivwWbTFYT0ZlBgdhkdFgAJ0bIT4nFfAWrS2GTO467QiGtsDBzBd6zxFD0758L' 

# --- Configuration Telegram (OBLIGATOIRE) ---
TELEGRAM_BOT_TOKEN = '7751726920:AAEMIJqpRw91POu_RDUTN8SOJvMvWSxcuz4' 
TELEGRAM_CHAT_ID = '5104739573' 

# --- Paramètres de la Stratégie (SHORT) ---
TIMEFRAME = '1m'          
RSI_LENGTH = 14           
RSI_ENTRY_LEVEL = 70      
MAX_SYMBOLS_TO_SCAN = 10  # Limite fixée à 10, conforme à votre restriction Binance
TIME_TO_WAIT_SECONDS = 2  

# --- Paramètres de Trading Réel (Adapté à votre capital initial de 23 USDC) ---
COLLATERAL_AMOUNT_USDC = 2.0   # Marge utilisée par trade (2.0 USDC, OK pour 23 USDC total)
LEVERAGE = 5                   
TAKE_PROFIT_PCT = 0.005        # 0.5% (TP)
STOP_LOSS_PCT = 0.50           # 50% (SL)
REPORT_FREQUENCY = 20          

# Paramètre de rapport d'équité périodique
EQUITY_REPORT_INTERVAL_SECONDS = 300 

# INITIALISATION DE L'EXCHANGE (BINANCE SPOT MARGIN ISOLÉ)
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'isolated_margin', 
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
    """ 
    Récupère les symboles et filtre pour ne garder que les 10 paires maximum 
    pour lesquelles un compte de Marge Isolée est déjà configuré (activé).
    """
    
    # 1. Récupérer tous les comptes de Marge Isolée actifs
    try:
        all_isolated_accounts = exchange.sapi_get_margin_isolated_all_account()
        
        # Extraire les symboles internes (ex: BTCUSDC) où la marge isolée est active
        activated_symbol_ids = {
            exchange.safe_value(account, 'symbol') 
            for account in all_isolated_accounts['assets'] 
        }
        
        # Convertir les symboles internes au format CCXT (ex: BTC/USDC)
        markets = exchange.load_markets()
        activated_ccxt_symbols = {
            market['symbol'] for market in markets.values() 
            if market['id'] in activated_symbol_ids and market['active']
        }

        # 2. Filtrer pour ne garder que les paires /USDC (ou /USDT)
        usdc_symbols = [
            s for s in activated_ccxt_symbols
            if s.endswith('/USDC') or s.endswith('/USDT')
        ]
        
        # 3. Sélectionner un maximum de 10 symboles aléatoirement parmi les symboles PRÊTS
        if not usdc_symbols:
            print("❌ ALERTE : Aucun compte de Marge Isolée /USDC ou /USDT activé n'a été trouvé. Vérifiez l'activation manuelle.")
            return [] 
            
        print(f"✅ {len(usdc_symbols)} paires de Marge Isolée activées détectées. Scanning {min(len(usdc_symbols), MAX_SYMBOLS_TO_SCAN)} au hasard.")
        return random.sample(usdc_symbols, min(len(usdc_symbols), MAX_SYMBOLS_TO_SCAN))
        
    except ccxt.ExchangeError as e:
        print(f"❌ Erreur API Binance lors de la vérification de la marge isolée: {e}. (Vérifiez l'autorisation 'Enable Margin' de la clé API)")
        return [] 
    except Exception as e:
        print(f"❌ Erreur inattendue dans get_usdc_symbols: {e}")
        return []

def fetch_ohlcv(symbol, timeframe, limit):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Timestamp'] = pd.to_datetime(df['Timestamp'], unit='ms')
        df.set_index('Timestamp', inplace=True)
        return df
    except Exception:
        return pd.DataFrame()

def check_trade_signal(df):
    if df.empty or len(df) < RSI_LENGTH:
        return False, None, None
        
    df['RSI_14'] = ta.rsi(df['Close'], length=RSI_LENGTH)
    df.dropna(subset=['RSI_14'], inplace=True) 
    
    if df.empty:
        return False, None, None
        
    last = df.iloc[-1]
    
    if last['RSI_14'] > RSI_ENTRY_LEVEL: 
        return True, last['Close'], last['RSI_14']
        
    return False, None, None

# =====================================================================
# ÉTAPE 3 : FONCTIONS DE LIVE TRADING (SPOT MARGIN)
# =====================================================================

def transfer_collateral_to_isolated_margin(symbol, amount):
    """ Tente de transférer le collatéral du compte Spot vers le compte Marge Isolé. """
    quote_asset = exchange.markets[symbol]['quote'] 
    try:
        transfer = exchange.transfer(
            code=quote_asset, 
            amount=amount, 
            from_account='spot', 
            to_account='isolated',
            params={'symbol': exchange.market_id(symbol)}
        )
        print(f"💸 Transfert réussi de {amount} {quote_asset} vers la marge isolée de {symbol}.")
        return True
    except ccxt.ExchangeError as e:
        if 'not enough asset' in str(e):
            print(f"⚠️ ALERTE : Solde Spot insuffisant en {quote_asset} pour transférer {amount}. Trade annulé.")
            return False
        else:
            # Si déjà présent ou autre avertissement mineur
            return True
    except Exception as e:
        print(f"❌ Erreur inattendue de transfert: {e}")
        return False


def execute_live_trade(symbol, entry_price, rsi_value):
    """ 
    Exécute un trade SHORT réel sur Binance Spot Margin.
    """
    global open_positions
    
    base_asset = exchange.markets[symbol]['base'] 
    quote_asset = exchange.markets[symbol]['quote'] 

    # 1. Calcul de l'emprunt
    amount_usd_notional = COLLATERAL_AMOUNT_USDC * LEVERAGE
    amount_base_asset = amount_usd_notional / entry_price
    amount_to_borrow = exchange.amount_to_precision(symbol, amount_base_asset)
    
    # 2. Transférer le collatéral (vérifie aussi si le Spot est suffisant)
    if not transfer_collateral_to_isolated_margin(symbol, COLLATERAL_AMOUNT_USDC):
        return False

    try:
        # 3. Emprunt de l'actif de base
        exchange.borrow(base_asset, amount_to_borrow, symbol)
        print(f"💰 Emprunt réussi de {amount_to_borrow} {base_asset} sur {symbol}.")
        
        # 4. Vente à découvert (Short Entry)
        order = exchange.create_order(
            symbol, 
            'market', 
            'sell', 
            amount_to_borrow,
            params={'sideEffectType': 'MARGIN_BUY'} 
        )
        
        # 5. Calcul des prix TP et SL
        tp_price = entry_price * (1 - TAKE_PROFIT_PCT)
        sl_price = entry_price * (1 + STOP_LOSS_PCT) 
        tp_price = exchange.price_to_precision(symbol, tp_price)
        sl_price = exchange.price_to_precision(symbol, sl_price)

        # 6. Enregistrement de la position dans le suivi local
        open_positions[symbol] = {
            'borrowed_amount': amount_to_borrow,
            'entry_price': float(order['price']) if order['price'] else entry_price,
            'tp_price': tp_price, 
            'sl_price': sl_price,
            'base_asset': base_asset,
            'quote_asset': quote_asset
        }

        # 7. Notification Telegram
        send_telegram_message(
            f"✅ **SHORT OUVERT - LIVE MARGIN**\n"
            f"=======================\n"
            f"Asset: **{symbol}** (RSI: {rsi_value:.2f})\n"
            f"Entrée: {open_positions[symbol]['entry_price']:.4f}\n"
            f"Marge: {COLLATERAL_AMOUNT_USDC} {quote_asset} | Levier: 5x\n"
            f"TP: {tp_price:.4f} | SL: {sl_price:.4f}"
        )
        
        print(f"📝 SHORT OUVERT (LIVE MARGIN) sur {symbol} | Entrée: {open_positions[symbol]['entry_price']:.4f}")
        return True

    except ccxt.ExchangeError as e:
        error_msg = f"❌ ÉCHEC TRADING {symbol} (Marge) : {e}"
        print(error_msg)
        send_telegram_message(f"🚨 **ÉCHEC DU TRADE MARGIN** : {symbol}\n{error_msg}")
        return False
    except Exception as e:
        print(f"❌ ERREUR CRITIQUE DANS execute_live_trade: {e}")
        return False

def close_live_trade(symbol, current_price):
    """ 
    Gère la fermeture d'une position Short Spot Margin (TP/SL) et le remboursement.
    """
    global open_positions, TRANSACTION_COUNT, WIN_COUNT, LOSS_COUNT
    
    if symbol not in open_positions:
        return False

    trade = open_positions[symbol]
    
    # 1. Vérification TP/SL
    result_type = None
    if current_price <= trade['tp_price']:
        result_type = "GAIN (TP)"
        WIN_COUNT += 1
        close_price = trade['tp_price'] 
    elif current_price >= trade['sl_price']:
        result_type = "PERTE (SL)"
        LOSS_COUNT += 1
        close_price = trade['sl_price']
    else:
        return False 

    borrowed_amount = trade['borrowed_amount']
    base_asset = trade['base_asset']

    try:
        # 2. Rachat de l'actif emprunté (Clôture du Short)
        exchange.create_order(
            symbol, 
            'market', 
            'buy', 
            borrowed_amount,
            params={'sideEffectType': 'MARGIN_BUY'}
        )
        
        # 3. Remboursement (Repay)
        exchange.repay(base_asset, borrowed_amount, symbol)
        
        TRANSACTION_COUNT += 1
        
        # 4. Calcul du P&L (Simplifié)
        pnl_usd = float(borrowed_amount) * (trade['entry_price'] - close_price)
        
        # 5. Notification Telegram
        send_telegram_message(
            f"🚨 **CLÔTURE SHORT MARGIN - {result_type}**\n"
            f"P&L estimé: **{pnl_usd:.4f} {trade['quote_asset']}**\n"
        )
        
        print(f"--- 🔔 {symbol} FERMÉ: {result_type} ---")
        del open_positions[symbol]
        return True

    except ccxt.ExchangeError as e:
        print(f"❌ ERREUR CLÔTURE {symbol} (Marge): {e}")
        send_telegram_message(f"🚨 **ÉCHEC DE CLÔTURE MARGIN** : {symbol}\n{e}")
        return False
    except Exception as e:
        print(f"❌ Erreur inattendue de clôture: {e}")
        return False

def get_live_equity_and_pnl():
    """ Récupère le solde réel du compte Spot pour le rapport. """
    try:
        balance = exchange.fetch_balance(params={'type': 'spot'})
        total_usd_balance = balance['total'].get('USDC', 0) + balance['total'].get('USDT', 0)
        return float(total_usd_balance)

    except Exception as e:
        print(f"❌ ERREUR lors du fetch du solde Spot Live: {e}")
        return 0.0

def send_equity_report():
    """ Envoie le solde SPOT et les positions ouvertes. """
    total_spot_balance = get_live_equity_and_pnl()
    
    report_message = (
        f"⏰ **MISE À JOUR SPOT MARGIN**\n"
        f"--- {time.strftime('%Y-%m-%d %H:%M')} ---\n"
        f"💵 **Solde SPOT (USDC/USDT) : {total_spot_balance:.2f}**\n"
        f"💼 Positions ouvertes : {len(open_positions)}"
    )
    send_telegram_message(report_message)


def generate_report():
    """ Génère et envoie le rapport de performance. """
    global TRANSACTION_COUNT, WIN_COUNT, LOSS_COUNT
    
    send_equity_report() 

    win_rate = (WIN_COUNT / TRANSACTION_COUNT) * 100 if TRANSACTION_COUNT > 0 else 0
    
    report_message = (
        f"📊 **RAPPORT DE PERFORMANCE**\n"
        f"📝 **Statistiques (Total Trades : {TRANSACTION_COUNT})**\n"
        f"📈 Taux de Succès : {win_rate:.2f} %"
    )
    send_telegram_message(report_message)

# =====================================================================
# ÉTAPE 5 : LA BOUCLE PRINCIPALE 24/7
# =====================================================================

def run_bot():
    """ Boucle principale qui exécute l'analyse et le trading réel. """
    global last_equity_report_time
    
    try:
        exchange.fetch_balance(params={'type': 'spot'})
        print(f"✅ CONNEXION BINANCE SPOT MARGIN ÉTABLIE.")
    except Exception as e:
        print(f"❌ ERREUR DE CONNEXION/AUTHENTIFICATION: {e}")
        print("Veuillez vérifier vos API KEY/SECRET et l'accès Marge Spot.")
        return 

    print(f"🤖 Bot SHORT LIVE SPOT MARGIN démarré (RSI > {RSI_ENTRY_LEVEL}, UT: {TIMEFRAME}).")
    
    last_equity_report_time = time.time()
    
    while True:
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            
            usdc_symbols = get_usdc_symbols() 
            
            if not usdc_symbols:
                print(f"\n[{timestamp}] --- AUCUNE PAIRE ACTIVÉE TROUVÉE. Vérification dans 60s. ---")
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
                if symbol in open_positions: 
                    continue
                    
                data = fetch_ohlcv(symbol, TIMEFRAME, limit=RSI_LENGTH + 1)
                
                if data.empty:
                    continue

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

# Décommentez la ligne ci-dessous pour lancer le bot EN LIVE SUR MARGE SPOT !
run_bot()
