import traceback
import logging
import sys
import os

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

try:
    logger.info("Démarrage du bot avec débogage...")
    
    # Importer le bot - si l'importation échoue, nous le saurons
    logger.info("Importation du module bot...")
    import bot
    
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