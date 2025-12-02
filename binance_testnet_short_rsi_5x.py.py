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
        'defaultType': 'future', # Utilisation de l'API Futures pour la simplicité du SHORT
        'testnet': True,
    }
})

# --- Paramètres de Stratégie & Trading ---
TIMEFRAME = '1m'               # Unité de temps de scalping
RSI_LENGTH = 14
RSI_ENTRY_LEVEL = 65           # Entrée SHORT si RSI > 65 (moins strict que 70)
RSI_EXIT_LEVEL = 50            # Sortie RSI (si le TP/SL n'est pas touché)

MAX_SYMBOLS_TO_SCAN = 5        # 🟢 Vitesse : Scanner seulement 5 paires pour un cycle rapide
INITIAL_BALANCE_USDT = 1000.00 # Solde de départ de la simulation (USDT)
ENTRY_SIZE_PERCENT = 0.05      # 5% du capital par position
LEVERAGE = 5                   # Levier souhaité (x5)

# --- Paramètres de Scalping Rapide (Sorties) ---
TAKE_PROFIT_PERCENT = 0.005    # 0.5% (Sortie rapide pour scalping)
STOP_LOSS_PERCENT = 0.01       # 1% (Stop Loss, plus large que le TP)
TIME_TO_WAIT_SECONDS = 7       # 🟢 Fréquence : 7 secondes (compromis sûr contre Erreur 429)

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
    # Notionnel désiré : Solde * Pourcentage d'entrée * Levier
    notional_size = simulated_balance * ENTRY_SIZE_PERCENT * LEVERAGE
    return notional_size / current_price

def get_random_pairs(max_count):
    """
    RÉPARÉ : Récupère une liste aléatoire de paires futures/USDT à scanner.
    Cible les paires /USDT pour éviter l'erreur de symbole.
    """
    try:
        markets = exchange.load_markets()
        # Filtre sur /USDT (la norme Future) et exclut les paires Fiat (ex: BUSD/USDT)
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
    
    # 2. Enregistrement de la position
    open_positions[symbol] = {
        'direction': 'SHORT',
        'entry_price': current_price,
        'entry_time': datetime.datetime.now(),
        'amount': entry_amount,
        'rsi_at_entry': rsi_value
    }

    message = (
        f"--------------------------------------------------\n"
        f"📝 SHORT OUVERT (SIMULÉ) sur {symbol}\n"
        f"  | Entrée: {current_price:.4f}\n"
        f"  | Montant: {entry_amount:.4f} (Levier x{LEVERAGE})\n"
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
    # P&L = (Prix d'entrée - Prix actuel) * Montant
    pnl = (entry_price - current_price) * amount
        
    simulated_balance += pnl
    
    # Alerte Telegram
    direction = position['direction']
    pnl_percent = (pnl / (position['entry_price'] * amount)) * 100
    
    message = (
        f"--------------------------------------------------\n"
        f"❌ {direction.upper()} CLÔTURÉ ({reason}) sur {symbol}\n"
        f"  | Entrée: {entry_price:.4f} | Clôture: {current_price:.4f}\n"
        f"  | P&L: {pnl:.2f} USDT ({pnl_percent:.2f}%)\n"
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
            
            # Calcul du PnL actuel pour une position SHORT (si le prix baisse, c'est un gain)
            pnl_percent = (entry_price - current_price) / entry_price
            
            # 1. Sortie par Take Profit rapide (0.5%)
            if pnl_percent >= TAKE_PROFIT_PERCENT:
                simulate_close_trade(symbol, current_price, reason="Scalping TP")
                return 

            # 2. Sortie par Stop Loss (1%)
            if pnl_percent <= -STOP_LOSS_PERCENT: # Le prix monte, c'est une perte
                simulate_close_trade(symbol, current_price, reason="Stop Loss")
                return 

            # 3. Sortie par RSI (si le TP/SL n'a pas été atteint)
            if current_rsi < RSI_EXIT_LEVEL: 
                simulate_close_trade(symbol, current_price, reason="RSI Exit")
            return

        # --- LOGIQUE D'ENTRÉE ---
        if symbol not in open_positions and len(open_positions) < MAX_OPEN_POSITIONS:
            # SHORT : Entrée si RSI est en zone de Surachat (RSI > 65)
            if current_rsi > RSI_ENTRY_LEVEL:
                execute_simulated_trade(symbol, current_price, current_rsi)
                
    except Exception as e:
        print(f"❌ Erreur lors du traitement de {symbol} (SHORT): {e}")

def main_loop():
    """La boucle de scan et de trading."""
    cycle_count = 0
    
    while True:
        cycle_count += 1
        
        # Sélection des paires (utilisera les paires /USDT valides)
        symbols_to_scan = get_random_pairs(MAX_SYMBOLS_TO_SCAN)
        
        print(f"\n[CYCLE {cycle_count}] --- Scan du marché démarré ({len(symbols_to_scan)} symboles, {len(open_positions)} positions ouvertes) ---")
        print(f"Balance actuelle: {simulated_balance:.2f} USDT")

        # Exécution de la Stratégie SHORT
        for symbol in symbols_to_scan:
            check_short_strategy(symbol)

        # Attente
        print(f"Fin du cycle. Prochain scan dans {TIME_TO_WAIT_SECONDS} seconde(s).")
        time.sleep(TIME_TO_WAIT_SECONDS)

# ====================================================================
# 4. LANCEMENT
# ====================================================================
if __name__ == '__main__':
    print("🤖 Bot de Trading Binance Testnet (SHORT Scalping) Démarré.")
    print(f"   Configuration: {TIMEFRAME}, Levier x{LEVERAGE}, TP: {TAKE_PROFIT_PERCENT*100:.2f}%, SL: {STOP_LOSS_PERCENT*100:.2f}%")
    print("-" * 50)
    
    try:
        main_loop()
    except KeyboardInterrupt:
        print("\n❌ Arrêt par l'utilisateur.")
