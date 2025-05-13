import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Fonction pour vérifier que toutes les importations fonctionne
def check_imports():
    """Vérifie que toutes les importations sont correctes"""
    try:
        # Vérifier si les types de média sont accessibles
        media_types = [InputMediaPhoto, InputMediaVideo, InputMediaDocument]
        logger.info(f"Imports vérifiés: {len(media_types)} types de média disponibles")
        return True
    except Exception as e:
        logger.error(f"Erreur dans les importations: {e}")
        return False 