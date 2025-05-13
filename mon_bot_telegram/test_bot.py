"""
Script de test pour vérifier le démarrage du bot.
"""
import asyncio
import logging
from main import main

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("TestBot")

async def test_startup():
    """
    Test simple pour vérifier que le bot démarre correctement.
    Cette fonction essaye de démarrer le bot et attrape toute exception 
    qui pourrait se produire pendant le processus de démarrage.
    """
    logger.info("Démarrage du test du bot...")
    
    try:
        # Nous encapsulons le démarrage du bot dans un task avec un timeout
        # pour ne pas bloquer indéfiniment
        bot_task = asyncio.create_task(main())
        
        # Attendre un court instant pour voir si des erreurs se produisent au démarrage
        await asyncio.sleep(5)
        
        logger.info("Le bot semble avoir démarré correctement!")
        
        # Pour un test réel, vous voudriez attendre plus longtemps
        # mais pour ce test simple, nous annulons la tâche après 5 secondes
        bot_task.cancel()
        
        try:
            await bot_task
        except asyncio.CancelledError:
            logger.info("Test terminé - le bot a été arrêté.")
            
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot: {e}")
        raise
    
if __name__ == "__main__":
    asyncio.run(test_startup()) 