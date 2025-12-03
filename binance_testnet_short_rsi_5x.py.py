import ccxt
import pandas as pd
import pandas_ta as ta
import time
import requests 
import random 
import datetime
import sys # Importé pour forcer la sortie en cas d'erreur de connexion

# (Les sections CONFIGURATION, PARAMÈTRES et FONCTIONS DE SUPPORT restent inchangées)
# ...

# =====================================================================
# ÉTAPE 5 : LA BOUCLE PRINCIPALE 24/7 (MODIFIÉE)
# =====================================================================

def run_bot():
    """ Boucle principale qui exécute l'analyse et le trading réel. """
    global last_equity_report_time
    
    # 🚨 LIGNE DE DÉBOGAGE AJOUTÉE 🚨
    print(">>> PYTHON SCRIPT STARTED: Tentative de connexion API Binance...")
    
    try:
        # Tentative de connexion / authentification
        exchange.fetch_balance(params={'type': 'spot'})
        print(f"✅ CONNEXION BINANCE SPOT MARGIN ÉTABLIE.")
    except Exception as e:
        # ❌ Si une erreur se produit (probablement une clé API invalide)
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"❌ ERREUR CRITIQUE DE CONNEXION/AUTHENTIFICATION: {e}")
        print("Veuillez vérifier vos API KEY/SECRET et l'accès Marge Spot. Arrêt du bot.")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        
        # On force l'arrêt ici, ce qui devrait vider le buffer de log
        sys.exit(1) 

    print(f"🤖 Bot SHORT LIVE SPOT MARGIN démarré (RSI > {RSI_ENTRY_LEVEL}, UT: {TIMEFRAME}).")
    
    last_equity_report_time = time.time()
    
    # ... (Le reste de la boucle while True reste inchangé) ...
    # ...

# =====================================================================
# Lancement de l'exécution
# =====================================================================

run_bot()
