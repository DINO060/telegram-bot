"""
Gestionnaire des fonctions de planification pour le bot Telegram
"""

import logging
import asyncio
import sqlite3
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import pytz

from mon_bot_telegram.conversation_states import (
    MAIN_MENU, SEND_OPTIONS, WAITING_PUBLICATION_CONTENT
)

logger = logging.getLogger('UploaderBot')

# Classe de gestionnaire de planification
class SchedulerManager:
    def __init__(self, db_manager):
        self.scheduler = AsyncIOScheduler()
        self.db_manager = db_manager

    def start(self):
        self.scheduler.start()

    def stop(self):
        """Arrête le planificateur s'il est en cours d'exécution"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown()
                logger.info("Scheduler arrêté avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt du scheduler: {e}")

    # Méthodes minimales pour éviter les erreurs
    async def execute_scheduled_post(self, post_id):
        logger.info(f"Exécution du post planifié {post_id}")


async def planifier_post(update, context):
    """Affiche les posts planifiés et permet d'en planifier un nouveau"""
    logger.info("Fonction planifier_post appelée")
    try:
        user_id = update.effective_user.id
        
        # Récupérer les posts planifiés depuis la base de données
        scheduled_posts = context.application.bot_data.get('db_manager').get_scheduled_posts(user_id)
        
        # Construire le message
        message = "📅 *Publications planifiées*\n\n"
        
        if not scheduled_posts:
            message += "Aucune publication planifiée pour le moment."
        else:
            # Trier les posts par date
            scheduled_posts.sort(key=lambda x: x['scheduled_time'])
            
            # Afficher chaque post planifié
            for i, post in enumerate(scheduled_posts, 1):
                scheduled_time = datetime.strptime(post['scheduled_time'], '%Y-%m-%d %H:%M:%S')
                # Convertir en fuseau horaire de l'utilisateur
                user_timezone = context.application.bot_data.get('db_manager').get_user_timezone(user_id) or "UTC"
                local_tz = pytz.timezone(user_timezone)
                scheduled_time = pytz.UTC.localize(scheduled_time).astimezone(local_tz)
                
                message += f"*{i}. Publication prévue le {scheduled_time.strftime('%d/%m/%Y à %H:%M')}*\n"
                message += f"Type: {post['type']}\n"
                if post.get('caption'):
                    message += f"Légende: {post['caption'][:50]}...\n" if len(post['caption']) > 50 else f"Légende: {post['caption']}\n"
                message += "\n"

        # Construire le clavier
        keyboard = [
            [InlineKeyboardButton("➕ Nouvelle publication planifiée", callback_data="create_publication")],
            [InlineKeyboardButton("🗑 Supprimer une publication", callback_data="delete_scheduled_post")],
            [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
        ]

        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        return MAIN_MENU
    except Exception as e:
        logger.error(f"Erreur dans planifier_post: {e}")
        error_message = f"❌ Erreur lors de la planification : {e}"
        keyboard = [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                error_message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                error_message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return MAIN_MENU


def handle_schedule_in_reply_keyboard(update, context, user_text):
    """Partie scheduling de handle_reply_keyboard"""
    if user_text == "envoyer":
        # Vérifier si un post planifié est sélectionné
        if 'current_scheduled_post' in context.user_data:
            from mon_bot_telegram.bot import send_post_now
            scheduled_post = context.user_data['current_scheduled_post']
            return send_post_now(update, context, scheduled_post=scheduled_post)
        posts = context.user_data.get("posts", [])
        if not posts:
            return None  # Pas de gestion ici
        
        # Configuration du post à envoyer
        from mon_bot_telegram.config import config
        channel = posts[0].get("channel", config.DEFAULT_CHANNEL)
        keyboard = [
            [InlineKeyboardButton("Régler temps d'auto destruction", callback_data="auto_destruction")],
            [InlineKeyboardButton("Maintenant", callback_data="send_now")],
            [InlineKeyboardButton("Planifier", callback_data="schedule_send")],
            [InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]
        ]
        
        return {
            'message': f"Vos {len(posts)} fichiers sont prêts à être envoyés à {channel}.\nQuand souhaitez-vous les envoyer ?",
            'keyboard': InlineKeyboardMarkup(keyboard),
            'state': SEND_OPTIONS
        }
    
    return None 