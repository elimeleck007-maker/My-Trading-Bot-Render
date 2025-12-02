import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests 
import random 
import datetime

# =====================================================================
# ÉTAPE 1 : CONFIGURATION ET PARAMÈTRES (SIMULATION AJUSTÉE)
# =====================================================================

# --- Clés API (Uniquement pour Telegram) ---
API_KEY = '' 
SECRET = '' 

# --- Configuration Telegram (OBLIGATOIRE) ---
TELEGRAM_BOT_TOKEN = '7751726920:AAEMIJqpRw91POu_RDUTN8SOJvMvWSxcuz4' 
TELEGRAM_CHAT_ID = '5104739573' 

# --- Paramètres de la Stratégie (SHORT) ---
TIMEFRAME = '5m'          
RSI_LENGTH = 14           
RSI_ENTRY_LEVEL = 60      
MAX_SYMBOLS_TO_SCAN = 20  
TIME_TO_WAIT_SECONDS = 2  

# --- Paramètres de Simulation ---
COLLATERAL_AMOUNT_USDC = 1.0   
LEVERAGE = 5              
TAKE_PROFIT_PCT = 0.005   
STOP_LOSS_PCT = 0.50      
REPORT_FREQUENCY = 20     

# NOUVEAU PARAMÈTRE : Rapport d'équité toutes les 5 minutes
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

# NOUVELLE VARIABLE GLOBALE pour le suivi du temps
last_equity_report_time = 0 


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
    # Fonction inchangée
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
# ÉTAPE 3 : FONCTIONS DE PAPER TRADING (SIMULÉES)
# =====================================================================

def execute_simulated_trade(symbol, entry_price, rsi_value):
    # Fonction inchangée
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
    # Fonction inchangée
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
# ÉTAPE 4 : FONCTIONS DE RAPPORT D'ÉQUITÉ ET DE P&L
# =====================================================================

def get_unrealized_pnl_and_collateral():
    # Fonction inchangée
    total_unrealized_pnl = 0.0
    total_collateral_engaged = 0.0
    
    if not open_positions:
        return 0.0, 0.0

    symbols_to_fetch = list(open_positions.keys())
    
    try:
        tickers = exchange.fetch_tickers(symbols_to_fetch)
    except Exception as e:
        print(f"❌ Erreur lors du fetch des tickers pour le P&L non réalisé: {e}")
        return 0.0, 0.0

    for symbol, trade in open_positions.items():
        if symbol in tickers:
            current_price = tickers[symbol]['last']
            
            percentage_change = (trade['entry_price'] - current_price) / trade['entry_price']
            pnl_usd = percentage_change * (COLLATERAL_AMOUNT_USDC * LEVERAGE)
            
            total_unrealized_pnl += pnl_usd
            total_collateral_engaged += COLLATERAL_AMOUNT_USDC 

    return total_unrealized_pnl, total_collateral_engaged


def send_equity_report():
    """ 
    NOUVELLE FONCTION : Calcule et envoie l'équité totale immédiatement via Telegram. 
    """
    global SIM_BALANCE_USDC, INITIAL_BALANCE_USDC
    
    unrealized_pnl, collateral_engaged = get_unrealized_pnl_and_collateral()
    total_equity = SIM_BALANCE_USDC + collateral_engaged + unrealized_pnl
    
    total_pnl_since_start = total_equity - INITIAL_BALANCE_USDC
    
    report_message = (
        f"⏰ **MISE À JOUR D'ÉQUITÉ (TEMPS RÉEL)**\n"
        f"--- {time.strftime('%Y-%m-%d %H:%M')} ---\n"
        f"💵 **ÉQUITÉ TOTALE ACTUELLE : {total_equity:.2f} USDC**\n"
        f"📈 P&L Total (Réalisé + Flottant) : {total_pnl_since_start:+.2f} USDC\n"
        f"-----------------------------------------\n"
        f"💰 Solde Disponible : {SIM_BALANCE_USDC:.2f} USDC\n"
        f"💼 Collatéral Engagé : {collateral_engaged:.2f} USDC\n"
        f"📉 P&L Flottant (Non Réalisé) : {unrealized_pnl:+.2f} USDC"
    )
    send_telegram_message(report_message)


def generate_report():
    """ Génère et envoie le rapport de performance (inchangé, mais utilise la nouvelle fonction ci-dessus). """
    global TRANSACTION_COUNT, WIN_COUNT, LOSS_COUNT, INITIAL_BALANCE_USDC, SIM_BALANCE_USDC

    # Cette fonction est principalement pour les stats de performance globale
    # L'envoi de l'équité est désormais géré par send_equity_report()
    
    send_equity_report() # On s'assure que le rapport d'équité est envoyé avec le rapport de performance

    win_rate = (WIN_COUNT / TRANSACTION_COUNT) * 100 if TRANSACTION_COUNT > 0 else 0
    
    report_message = (
        f"📊 **RAPPORT DE PERFORMANCE (STATISTIQUES)**\n"
        f"📝 **Statistiques (Total Trades : {TRANSACTION_COUNT})**\n"
        f"✅ Trades Gagnants (TP) : {WIN_COUNT}\n"
        f"❌ Trades Perdants (SL) : {LOSS_COUNT}\n"
        f"📈 Taux de Succès : {win_rate:.2f} %"
    )
    send_telegram_message(report_message)

# =====================================================================
# ÉTAPE 5 : LA BOUCLE PRINCIPALE 24/7 (AVEC GESTION DE TEMPS POUR L'ÉQUITÉ)
# =====================================================================

def run_bot():
    """ Boucle principale qui exécute l'analyse et la simulation sur toutes les cryptos. """
    global last_equity_report_time
    
    print(f"🤖 Bot SHORT MULTI-CRYPTO PAPER TRADING démarré (RSI > {RSI_ENTRY_LEVEL}, TP={TAKE_PROFIT_PCT*100}%, Marge={COLLATERAL_AMOUNT_USDC:.1f} USDC).")
    print(f"🔔 MODE SIMULATION. Solde virtuel de départ: {INITIAL_BALANCE_USDC:.2f} USDC")
    
    # Initialisation du temps de rapport
    last_equity_report_time = time.time()
    
    while True:
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            
            usdc_symbols = get_usdc_symbols() 
            print(f"\n[{timestamp}] --- Scan du marché démarré ({len(usdc_symbols)} symboles, {len(open_positions)} positions ouvertes) ---")
            
            
            for symbol in usdc_symbols:
                
                data = fetch_ohlcv(symbol, TIMEFRAME, limit=RSI_LENGTH + 1)
                
                if data.empty:
                    continue

                current_price = data['Close'].iloc[-1]
                
                # A. GESTION DES POSITIONS EXISTANTES
                if symbol in open_positions:
                    simulate_close_trade(symbol, current_price) 
                
                # B. RECHERCHE DE NOUVEAUX SIGNAUX
                elif symbol not in open_positions: 
                    signal_detected, entry_price, rsi_value = check_trade_signal(data) 
                    
                    if signal_detected:
                        execute_simulated_trade(symbol, entry_price, rsi_value) 

            # GESTION DU RAPPORT D'ÉQUITÉ PÉRIODIQUE PAR TÉLÉGRAM
            if (time.time() - last_equity_report_time) >= EQUITY_REPORT_INTERVAL_SECONDS:
                send_equity_report()
                last_equity_report_time = time.time()
                
            # Affichage console (inchangé)
            unrealized_pnl, collateral_engaged = get_unrealized_pnl_and_collateral()
            total_equity = SIM_BALANCE_USDC + collateral_engaged + unrealized_pnl
            
            print(f"💰 SOLDE DISPONIBLE (Trades Fermés): {SIM_BALANCE_USDC:.2f} USDC")
            print(f"💵 **ÉQUITÉ TOTALE ACTUELLE (avec P&L flottant): {total_equity:.2f} USDC**")
            
            # 4. Temps d'attente
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
