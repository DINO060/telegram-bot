import traceback
import logging
import sys
import os
import asyncio
import signal
import time

# Configuration du logging pour capturer toutes les erreurs
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot_debug.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("BotDebugger")

# Variables globales
bot_instance = None

# Gestionnaire de signal pour l'arrêt propre
def signal_handler(sig, frame):
    logger.info("Signal d'arrêt reçu. Arrêt propre en cours...")
    if bot_instance:
        try:
            # Gérer la fermeture propre via la fonction shutdown du bot
            if hasattr(bot_instance, 'shutdown') and callable(bot_instance.shutdown):
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(bot_instance.shutdown())
                    # Donner le temps de fermer proprement
                    time.sleep(3)
                    logger.info("Arrêt propre terminé")
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt propre: {e}")
    sys.exit(0)

# Enregistrer les gestionnaires de signaux
signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill

try:
    logger.info("Démarrage du bot avec débogage...")
    
    # Importer le bot - si l'importation échoue, nous le saurons
    logger.info("Importation du module bot...")
    import bot
    
    # Stocker l'instance du bot pour l'arrêt propre
    bot_instance = bot
    
    # Lancer le bot avec gestion d'exceptions
    logger.info("Lancement de la fonction main()...")
    bot.main()
    
except Exception as e:
    error_trace = traceback.format_exc()
    logger.error(f"Exception critique: {e}")
    logger.error(f"Traceback:\n{error_trace}")
    
    # Garder la fenêtre ouverte pour lire l'erreur
    print("\n\n=============== ERREUR CRITIQUE ===============")
    print(f"Type d'erreur: {type(e).__name__}")
    print(f"Message: {e}")
    print("\nTraceback détaillé:")
    print(error_trace)
    print("===============================================\n")
    
    # Maintenir le programme en vie pour lire l'erreur
    input("Appuyez sur Entrée pour quitter...") 