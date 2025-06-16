"""
Utilitaires de planification pour le bot Telegram.
"""
import logging
import sqlite3
import asyncio
import json
from typing import Dict, Any
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

logger = logging.getLogger('SchedulerUtils')

async def send_scheduled_file(post: Dict[str, Any]) -> bool:
    """
    Envoie un fichier planifié au canal spécifié.
    
    Args:
        post: Les données du post à envoyer
        
    Returns:
        bool: True si l'envoi a réussi
    """
    try:
        logger.info(f"Envoi du fichier planifié : {post.get('id')}")
        app = Application.get_current()
        if not app:
            logger.error("Application Telegram introuvable")
            return False

        # Préparer le message à envoyer
        channel = post.get('channel_username')
        post_type = post.get('type')
        content = post.get('content')
        caption = post.get('caption')
        
        # Construire le clavier avec les boutons URL si présents
        keyboard = None
        if post.get('buttons'):
            try:
                # Remplacer eval() par json.loads() pour une meilleure sécurité
                if isinstance(post['buttons'], str):
                    try:
                        buttons = json.loads(post['buttons'])
                    except json.JSONDecodeError:
                        logger.warning("Impossible de décoder les boutons comme JSON, utilisation telle quelle")
                        buttons = post['buttons']
                else:
                    buttons = post['buttons']
                    
                keyboard_buttons = []
                for btn in buttons:
                    keyboard_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                keyboard = InlineKeyboardMarkup(keyboard_buttons)
            except Exception as e:
                logger.error(f"Erreur lors de la conversion des boutons : {e}")

        # Envoyer le message selon son type
        sent_message = None
        if post_type == "photo":
            sent_message = await app.bot.send_photo(
                chat_id=channel,
                photo=content,
                caption=caption,
                reply_markup=keyboard
            )
        elif post_type == "video":
            sent_message = await app.bot.send_video(
                chat_id=channel,
                video=content,
                caption=caption,
                reply_markup=keyboard
            )
        elif post_type == "document":
            sent_message = await app.bot.send_document(
                chat_id=channel,
                document=content,
                caption=caption,
                reply_markup=keyboard
            )
        elif post_type == "text":
            sent_message = await app.bot.send_message(
                chat_id=channel,
                text=content,
                reply_markup=keyboard
            )

        if sent_message:
            logger.info(f"Message planifié envoyé avec succès : {post.get('id')}")
            
            # Supprimer le post de la base de données
            try:
                db_path = post.get('db_path', 'bot.db')  # Utiliser un chemin par défaut si non spécifié
                with sqlite3.connect(db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM posts WHERE id = ?", (post['id'],))
                    conn.commit()
                    logger.info(f"Post {post['id']} supprimé de la base de données")
            except sqlite3.Error as e:
                logger.error(f"Erreur lors de la suppression du post de la base de données : {e}")
            
            return True
        else:
            logger.error(f"Échec de l'envoi du message planifié : {post.get('id')}")
            return False

    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du fichier planifié : {e}")
        return False 