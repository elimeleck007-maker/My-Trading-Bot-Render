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

# --- Clés API (Uniquement pour l'utilisation de l'API de test) ---
# NOTE: Ces clés NE SONT PAS UTILISÉES POUR LA SIMULATION, mais sont nécessaires 
# si ccxt tente de se connecter.
API_KEY = 'VOTRE_CLE_API' 
SECRET = 'VOTRE_SECRET_API' 

# --- Configuration Telegram (OBLIGATOIRE) ---
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
RSI_ENTRY_LEVEL = 65    # 🟢 MODIFIÉ : Signal SHORT : Vente si RSI > 65 (pour plus de trades)
RSI_EXIT_LEVEL = 50     # Signal de Sortie : Clôture si RSI < 50
MAX_SYMBOLS_TO_SCAN = 5 # 🟢 MODIFIÉ : Scanner seulement 5 paires pour la vitesse
INITIAL_BALANCE_USDC = 1000.0 
ENTRY_SIZE_PERCENT = 0.05 # 5% de la balance par position
MAX_OPEN_POSITIONS = 30 # Limite pour éviter les dépassements

# --- Scalping / Fréquence du Cycle ---
PROFIT_SCALPING_PERCENT = 0.005 # 🟢 NOUVEAU : Take Profit fixe à 0.5%
TIME_TO_WAIT_SECONDS = 7 # 🟢 MODIFIÉ : Fréquence du cycle : 7 secondes (Compromis sûr)

# =====================================================================
# ÉTAPE 2 : GESTION DES POSITIONS ET MESSAGES (SHORT)
# =====================================================================

# Dictionnaire de suivi des positions ouvertes
open_positions = {}
simulated_balance = INITIAL_BALANCE_USDC

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
    """Récupère une liste aléatoire de paires futures/USDC à scanner."""
    try:
        markets = exchange.load_markets()
        usdc_futures = [symbol for symbol in markets if symbol.endswith('/USDC')]
        return random.sample(usdc_futures, min(max_count, len(usdc_futures)))
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

    message = (
        f"--------------------------------------------------\n"
        f"📝 {direction.upper()} OUVERT (SIMULÉ, Ordre de Marché) sur {symbol}\n"
        f"  | Entrée: {current_price:.4f}\n"
        f"  | Montant: {entry_amount:.4f}\n"
        f"  | RSI: {rsi_value:.2f}\n"
        f"--------------------------------------------------"
    )
    print(message)
    send_telegram_message(message)

def simulate_close_trade(symbol, current_price, reason="RSI Exit"):
    """Simule la clôture d'une position ouverte."""
    global simulated_balance
    
    position = open_positions.pop(symbol)
    
    entry_price = position['entry_price']
    amount = position['amount']
    
    # Calcul du P&L (SHORT)
    pnl = (entry_price - current_price) * amount
        
    simulated_balance += pnl
    
    # Alerte Telegram
    direction = position['direction']
    pnl_percent = (pnl / (position['entry_price'] * amount)) * 100
    
    message = (
        f"--------------------------------------------------\n"
        f"❌ {direction.upper()} CLÔTURÉ ({reason}) sur {symbol}\n"
        f"  | Entrée: {entry_price:.4f}\n"
        f"  | Clôture: {current_price:.4f}\n"
        f"  | P&L: {pnl:.2f} USDC ({pnl_percent:.2f}%)\n"
        f"  | Nouvelle Balance: {simulated_balance:.2f} USDC\n"
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
        # Récupération des données historiques (OHLCV)
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=RSI_LENGTH + 10)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Calcul de l'indicateur RSI
        df['RSI'] = ta.rsi(df['close'], length=RSI_LENGTH)
        current_rsi = df['RSI'].iloc[-1]
        current_price = df['close'].iloc[-1]
        
        # --- LOGIQUE DE SORTIE ---
        if symbol in open_positions:
            position = open_positions[symbol]
            entry_price = position['entry_price']
            
            # 1. Sortie par Take Profit rapide (0.5%)
            profit_percent = (entry_price - current_price) / entry_price
            if profit_percent >= PROFIT_SCALPING_PERCENT:
                simulate_close_trade(symbol, current_price, reason="Scalping TP")
                return # Sortie du cycle de vérification

            # 2. Sortie par RSI (si le TP n'a pas été atteint)
            if current_rsi < RSI_EXIT_LEVEL: 
                simulate_close_trade(symbol, current_price)
            return

        # --- LOGIQUE D'ENTRÉE ---
        if symbol not in open_positions and len(open_positions) < MAX_OPEN_POSITIONS:
            # SHORT : Entrée si RSI est en zone de Surachat (RSI > 65)
            if current_rsi > RSI_ENTRY_LEVEL:
                execute_simulated_trade(symbol, 'SHORT', current_price, current_rsi)
                
    except Exception as e:
        print(f"❌ Erreur lors du traitement de {symbol} (SHORT): {e}")

def main_loop():
    """La boucle de scan et de trading."""
    cycle_count = 0
    
    while True:
        cycle_count += 1
        
        symbols_to_scan = get_random_pairs(MAX_SYMBOLS_TO_SCAN)
        
        print(f"\n[CYCLE {cycle_count}] --- Scan du marché démarré ({len(symbols_to_scan)} symboles, {len(open_positions)} positions ouvertes) ---")
        print(f"Balance actuelle: {simulated_balance:.2f} USDC")

        # Exécution de la Stratégie SHORT
        for symbol in symbols_to_scan:
            check_short_strategy(symbol)

        # Attente
        print(f"Fin du cycle. Prochain scan dans {TIME_TO_WAIT_SECONDS} seconde(s).")
        time.sleep(TIME_TO_WAIT_SECONDS)

# =====================================================================
# ÉTAPE 4 : LANCEMENT
# =====================================================================
if __name__ == '__main__':
    main_loop()
