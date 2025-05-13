from typing import Dict, Callable, Awaitable, Optional
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from datetime import datetime, timedelta
import sqlite3
import pytz
import os
import asyncio

from utils.message_utils import MessageError, PostType
from database.manager import DatabaseManager
from utils.validators import InputValidator
from utils.constants import MAIN_MENU, SCHEDULE_SELECT_CHANNEL, SCHEDULE_SEND
from utils.error_handler import handle_error
from utils.scheduler import SchedulerManager
# Nous n'importons plus scheduler_manager directement
import sys

# Import de la configuration
from config.settings import settings

# Import de scheduler_manager depuis le module parent (bot.py)
from inspect import currentframe
def get_scheduler_manager():
    """
    Récupère le scheduler_manager depuis le module bot.
    
    Cette fonction permet d'éviter les problèmes d'importation circulaire.
    """
    try:
        parent_module = sys.modules.get('bot')
        if parent_module and hasattr(parent_module, 'scheduler_manager'):
            return parent_module.scheduler_manager
        return None
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du scheduler_manager: {e}")
        return None

logger = logging.getLogger(__name__)

# Définition des types pour les gestionnaires
HandlerType = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


class CallbackError(Exception):
    """Exception pour les erreurs de callback"""
    pass


# Mapping des actions vers les gestionnaires
CALLBACK_HANDLERS: Dict[str, HandlerType] = {
    "main_menu": "start",
    "create_publication": "create_publication",
    "planifier_post": "planifier_post",
    "modifier_heure": "handle_edit_time",
    "envoyer_maintenant": "handle_send_now",
    "annuler_publication": "handle_cancel_post",
    "retour": "planifier_post",
    "preview": "handle_preview",
    "settings": "handle_settings",
    "timezone": "handle_timezone_setup",
    "schedule_send": "schedule_send"
}


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gère les callbacks de manière centralisée.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Raises:
        CallbackError: Si le callback est invalide ou non géré
    """
    query = update.callback_query
    user_id = update.effective_user.id
    if not query or not query.data:
        logger.warning("Callback sans données reçu")
        return

    try:
        # Récupération du callback data complet
        callback_data = query.data
        await query.answer()

        # Cas spécifiques pour les callbacks
        if callback_data == "main_menu":
            # Importer la fonction start du module parent
            from bot import start
            return await start(update, context)
            
        elif callback_data == "create_publication":
            # Importer la fonction create_publication du module parent
            from bot import create_publication
            return await create_publication(update, context)
            
        elif callback_data == "planifier_post":
            return await planifier_post(update, context)
            
        elif callback_data == "schedule_send":
            # Importer la fonction schedule_send du module parent
            return await schedule_send(update, context)
            
        elif callback_data == "schedule_today" or callback_data == "schedule_tomorrow":
            # Stocker le jour sélectionné
            context.user_data['schedule_day'] = 'today' if callback_data == "schedule_today" else 'tomorrow'
            return await schedule_send(update, context)
            
        elif callback_data == "modifier_heure":
            return await handle_edit_time(update, context)
            
        elif callback_data == "envoyer_maintenant":
            return await handle_send_now(update, context)
            
        elif callback_data == "annuler_publication":
            return await handle_cancel_post(update, context)
            
        elif callback_data == "confirm_cancel":
            return await handle_confirm_cancel(update, context)
            
        elif callback_data == "retour":
            return await planifier_post(update, context)
            
        elif callback_data == "settings":
            # Création d'un menu de paramètres simple
            keyboard = [
                [InlineKeyboardButton("🕒 Fuseau horaire", callback_data="set_timezone")],
                [InlineKeyboardButton("📢 Gérer les canaux", callback_data="manage_channels")],
                [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
            ]
            await query.edit_message_text(
                "⚙️ Paramètres\n\nChoisissez une option :",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SETTINGS
            
        # Si le callback n'est pas dans la liste des cas directement gérés
        logger.warning(f"Callback non géré directement : {callback_data}")
        await query.edit_message_text(
            f"⚠️ Action {callback_data} non implémentée. Retour au menu principal.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]
            )
        )
        return MAIN_MENU

    except Exception as e:
        logger.error(f"Erreur dans handle_callback : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]
            )
        )
        return MAIN_MENU


async def handle_edit_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gère la modification de l'heure d'une publication.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Raises:
        CallbackError: Si la publication n'est pas trouvée
    """
    query = update.callback_query
    try:
        post_id = context.user_data.get('current_post_id')
        if not post_id:
            raise CallbackError("Aucune publication en cours")

        await query.edit_message_text(
            "🕒 Entrez la nouvelle date et heure (format: JJ/MM/AAAA HH:MM):"
        )
        context.user_data['waiting_for_time'] = True

    except CallbackError as e:
        logger.error(f"Erreur de modification d'heure: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")


async def handle_send_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère l'envoi immédiat d'un post planifié"""
    try:
        query = update.callback_query
        await query.answer()

        if 'current_scheduled_post' not in context.user_data:
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        post = context.user_data['current_scheduled_post']
        
        try:
            keyboard = []
            if post.get('buttons'):
                try:
                    buttons = eval(post['buttons'])
                    for btn in buttons:
                        keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                except Exception as e:
                    logger.error(f"Erreur lors de la conversion des boutons : {e}")

            sent_message = None
            if post['type'] == "photo":
                sent_message = await context.bot.send_photo(
                    chat_id=post['channel_username'],
                    photo=post['content'],
                    caption=post.get('caption'),
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            elif post['type'] == "video":
                sent_message = await context.bot.send_video(
                    chat_id=post['channel_username'],
                    video=post['content'],
                    caption=post.get('caption'),
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            elif post['type'] == "document":
                sent_message = await context.bot.send_document(
                    chat_id=post['channel_username'],
                    document=post['content'],
                    caption=post.get('caption'),
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            elif post['type'] == "text":
                sent_message = await context.bot.send_message(
                    chat_id=post['channel_username'],
                    text=post['content'],
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )

            if sent_message:
                with sqlite3.connect(settings.db_config["path"]) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM posts WHERE id = ?", (post['id'],))
                    conn.commit()

                # Au lieu d'utiliser scheduler_manager directement, nous supprimons le job
                # en utilisant l'application associée au contexte
                job_id = f"post_{post['id']}"
                # Nous ne pouvons pas vérifier si le job existe sans scheduler_manager
                # Simplement essayer de supprimer le job s'il existe
                try:
                    if context.application and hasattr(context.application, 'job_queue'):
                        context.application.job_queue.remove_job(job_id)
                except Exception as e:
                    logger.warning(f"Le job {job_id} n'a pas pu être supprimé: {e}")

                await query.message.reply_text(
                    "✅ Post envoyé avec succès !",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )

                context.user_data.pop('current_scheduled_post', None)
                return MAIN_MENU

        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du post : {e}")
            await query.message.reply_text(
                "❌ Erreur lors de l'envoi du post.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

    except Exception as e:
        logger.error(f"Erreur dans handle_send_now : {e}")
        await query.message.reply_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gère l'annulation d'une publication.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Raises:
        CallbackError: Si la publication ne peut pas être annulée
    """
    query = update.callback_query
    try:
        if context.user_data.get('confirming_cancel'):
            post_id = context.user_data.get('current_post_id')
            if not post_id:
                raise CallbackError("Aucune publication à annuler")

            db_manager = context.bot_data.get('db_manager')
            if not db_manager or not db_manager.delete_post(post_id):
                raise CallbackError("Impossible d'annuler la publication")

            await query.edit_message_text("✅ Publication annulée")
            context.user_data.pop('confirming_cancel', None)
        else:
            context.user_data['confirming_cancel'] = True
            await query.edit_message_text(
                "⚠️ Êtes-vous sûr de vouloir annuler cette publication ?",
                reply_markup=[[
                    InlineKeyboardButton("Oui", callback_data="annuler_publication"),
                    InlineKeyboardButton("Non", callback_data="retour")
                ]]
            )

    except CallbackError as e:
        logger.error(f"Erreur d'annulation: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")


async def handle_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Gère l'aperçu d'une publication.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Raises:
        CallbackError: Si la publication n'est pas trouvée
    """
    query = update.callback_query
    try:
        post_data = context.user_data.get('current_post')
        if not post_data:
            raise CallbackError("Aucune publication en cours")

        preview_text = (
            f"📝 Aperçu de la publication:\n\n"
            f"Type: {post_data['type']}\n"
            f"Contenu: {post_data['content'][:100]}...\n"
            f"Légende: {post_data.get('caption', 'Aucune')}\n"
            f"Horaire: {post_data.get('scheduled_time', 'Immédiat')}"
        )

        await query.edit_message_text(preview_text)

    except CallbackError as e:
        logger.error(f"Erreur d'aperçu: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")


async def handle_post_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère le choix du type de publication.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        CallbackError: Si le type de publication est invalide
    """
    query = update.callback_query
    try:
        await query.answer()

        post_type = query.data.split('_')[-1]
        if post_type not in ['text', 'photo', 'video']:
            raise CallbackError("Type de publication invalide")

        context.user_data['post_type'] = post_type

        if post_type == 'text':
            await query.edit_message_text(
                "Entrez le texte de votre publication:"
            )
            return 4  # WAITING_TEXT

        await query.edit_message_text(
            "Envoyez la photo ou la vidéo:"
        )
        return 5  # WAITING_MEDIA

    except CallbackError as e:
        logger.error(f"Erreur de type de publication: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
        return 1  # CREATE_PUBLICATION
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")
        return 1  # CREATE_PUBLICATION


async def handle_schedule_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère le choix du type de publication à planifier.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        CallbackError: Si le type de publication est invalide
    """
    query = update.callback_query
    try:
        await query.answer()

        post_type = query.data.split('_')[-1]
        if post_type not in ['text', 'photo', 'video']:
            raise CallbackError("Type de publication invalide")

        context.user_data['post_type'] = post_type

        if post_type == 'text':
            await query.edit_message_text(
                "Entrez le texte de votre publication:"
            )
            return 6  # WAITING_SCHEDULE_TEXT

        await query.edit_message_text(
            "Envoyez la photo ou la vidéo:"
        )
        return 7  # WAITING_SCHEDULE_MEDIA

    except CallbackError as e:
        logger.error(f"Erreur de type de publication planifiée: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
        return 2  # PLANIFIER_POST
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")
        return 2  # PLANIFIER_POST


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère les paramètres du bot.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        CallbackError: Si le type de paramètre est invalide
    """
    query = update.callback_query
    try:
        await query.answer()

        setting_type = query.data.split('_')[-1]
        if setting_type not in ['timezone', 'other']:
            raise CallbackError("Type de paramètre invalide")

        if setting_type == 'timezone':
            await query.edit_message_text(
                "Entrez votre fuseau horaire (ex: Europe/Paris):"
            )
            return 8  # WAITING_TIMEZONE

        await query.edit_message_text(
            "Autres paramètres à venir..."
        )
        return ConversationHandler.END

    except CallbackError as e:
        logger.error(f"Erreur de paramètres: {str(e)}")
        await query.edit_message_text(f"❌ Erreur: {str(e)}")
        return 3  # SETTINGS
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await query.edit_message_text("❌ Une erreur inattendue s'est produite")
        return 3  # SETTINGS


async def handle_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la planification effective des messages"""
    try:
        # Gestion des callbacks pour la sélection du jour
        if update.callback_query:
            query = update.callback_query
            data = query.data

            if data in ["schedule_today", "schedule_tomorrow"]:
                # Stocker le jour sélectionné
                context.user_data['schedule_day'] = 'today' if data == "schedule_today" else 'tomorrow'
                jour = "Aujourd'hui" if context.user_data['schedule_day'] == 'today' else "Demain"

                # Mise à jour du message pour indiquer que l'heure est attendue
                await query.edit_message_text(
                    f"✅ Jour sélectionné : {jour}.\n\n"
                    "Envoyez-moi maintenant l'heure au format :\n"
                    "   • '15:30' ou '1530' (24h)\n"
                    "   • '6' (06:00)\n"
                    "   • '5 3' (05:03)",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="schedule_send")
                    ]])
                )
                return SCHEDULE_SEND

            await query.answer()
            return SCHEDULE_SEND

        # Gestion de l'entrée de l'heure
        if not update.message or not update.message.text:
            return SCHEDULE_SEND

        # Vérifier si un jour a été sélectionné
        if 'schedule_day' not in context.user_data:
            await update.message.reply_text(
                "❌ Veuillez d'abord sélectionner un jour (Aujourd'hui ou Demain).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND

        # Vérifier si nous avons des posts à planifier
        posts = context.user_data.get("posts", [])
        if not posts and 'current_scheduled_post' not in context.user_data:
            await update.message.reply_text(
                "❌ Aucun contenu à planifier. Veuillez d'abord envoyer du contenu.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Traitement de l'heure
        time_text = update.message.text.strip()
        logger.info(f"[DEBUG] Heure reçue: {time_text}")
        
        try:
            # Convertir différents formats d'heure
            if ':' in time_text:
                hour, minute = map(int, time_text.split(':'))
            elif ' ' in time_text:
                hour, minute = map(int, time_text.split())
            else:
                if len(time_text) <= 2:  # Format simple (ex: "6")
                    hour = int(time_text)
                    minute = 0
                else:  # Format condensé (ex: "1530")
                    hour = int(time_text[:-2])
                    minute = int(time_text[-2:])

            # Validation de l'heure
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Heure invalide")

            logger.info(f"[DEBUG] Heure validée: {hour:02d}:{minute:02d}")

            # Récupérer le fuseau horaire de l'utilisateur
            user_id = update.effective_user.id
            
            # Utilise la fonction get_user_timezone de DatabaseManager
            # Assurez-vous que cette fonction est correctement implémentée
            from database.manager import DatabaseManager
            db = DatabaseManager(settings.db_config["path"])
            user_timezone = db.get_user_timezone(user_id) or "UTC"
            
            local_tz = pytz.timezone(user_timezone)
            target_date = datetime.now(local_tz)

            if context.user_data['schedule_day'] == 'tomorrow':
                target_date += timedelta(days=1)

            target_date = target_date.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0
            )

            # Convertir en UTC pour le stockage
            utc_date = target_date.astimezone(pytz.UTC)
            logger.info(f"[DEBUG] Date calculée: {utc_date} (UTC)")

            # Vérifier que l'heure n'est pas déjà passée
            if utc_date <= datetime.now(pytz.UTC):
                logger.warning(f"[DEBUG] Heure déjà passée: {utc_date}")
                await update.message.reply_text(
                    "❌ Cette heure est déjà passée. Veuillez choisir une heure future.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="schedule_send")
                    ]])
                )
                return SCHEDULE_SEND

            success_count = 0

            # Si nous modifions un post existant
            if 'current_scheduled_post' in context.user_data:
                post = context.user_data['current_scheduled_post']
                post_id = post['id']
                logger.info(f"[DEBUG] Modification du post existant ID: {post_id}")

                # Mettre à jour la base de données
                with sqlite3.connect(settings.db_config["path"]) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE posts SET scheduled_time = ? WHERE id = ?",
                        (utc_date.strftime('%Y-%m-%d %H:%M:%S'), post_id)
                    )
                    conn.commit()

                # Mettre à jour le scheduler
                scheduler_manager = get_scheduler_manager()
                if scheduler_manager:
                    job_id = f"post_{post_id}"
                    if scheduler_manager.scheduler.get_job(job_id):
                        scheduler_manager.scheduler.remove_job(job_id)

                    # Créer une nouvelle tâche planifiée
                    scheduler_manager.scheduler.add_job(
                        func=lambda: asyncio.create_task(send_scheduled_file(post)),
                        trigger="date",
                        run_date=utc_date,
                        id=job_id
                    )

                success_count = 1
                
            else:
                # Planifier chaque nouveau post
                logger.info(f"[DEBUG] Planification de {len(posts)} nouveaux posts")
                scheduler_manager = get_scheduler_manager()
                
                for post in posts:
                    try:
                        # Trouver l'ID du channel
                        channel_username = post.get('channel')
                        channel_id = None
                        
                        # Chercher le channel_id dans la base de données
                        with sqlite3.connect(settings.db_config["path"]) as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                "SELECT id FROM channels WHERE username = ?",
                                (channel_username.replace('@', ''),)
                            )
                            result = cursor.fetchone()
                            if result:
                                channel_id = result[0]
                        
                        # Ajouter le post à la base de données
                        with sqlite3.connect(settings.db_config["path"]) as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                """
                                INSERT INTO posts (channel_id, type, content, caption, scheduled_time)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (channel_id, post['type'], post['content'],
                                 post.get('caption'), utc_date.strftime('%Y-%m-%d %H:%M:%S'))
                            )
                            post_id = cursor.lastrowid
                            conn.commit()

                        # Planifier la tâche
                        if scheduler_manager:
                            job_id = f"post_{post_id}"
                            scheduler_manager.scheduler.add_job(
                                func=lambda p=post: asyncio.create_task(send_scheduled_file(p)),
                                trigger="date",
                                run_date=utc_date,
                                id=job_id
                            )

                        success_count += 1
                    except Exception as e:
                        logger.error(f"[DEBUG] Erreur lors de la planification d'un post : {e}")
                        continue

            # Message de confirmation avec l'heure dans le fuseau de l'utilisateur
            day_str = "Aujourd'hui" if context.user_data['schedule_day'] == 'today' else "Demain"
            await update.message.reply_text(
                f"✅ {success_count} fichier(s) planifié(s) pour {day_str} à {hour:02d}:{minute:02d} ({user_timezone})",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )

            # Nettoyage du contexte
            context.user_data.clear()

            # Retour au menu principal
            from bot import start
            return await start(update, context)

        except ValueError:
            logger.warning(f"[DEBUG] Format d'heure invalide: {time_text}")
            await update.message.reply_text(
                "❌ Format d'heure invalide. Utilisez :\n"
                "• '15:30' ou '1530' (24h)\n"
                "• '6' (06:00)\n"
                "• '5 3' (05:03)",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND

    except Exception as e:
        logger.error(f"[DEBUG] Erreur générale dans handle_schedule_time : {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de la planification.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        from bot import start
        return await start(update, context)


async def handle_edit_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère la modification de l'heure d'une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        post = context.user_data.get('current_scheduled_post')
        if not post:
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        keyboard = [
            [
                InlineKeyboardButton("Aujourd'hui", callback_data="schedule_today"),
                InlineKeyboardButton("Demain", callback_data="schedule_tomorrow"),
            ],
            [InlineKeyboardButton("↩️ Retour", callback_data="retour")]
        ]

        message_text = (
            "📅 Choisissez la nouvelle date pour votre publication :\n\n"
            "1️⃣ Sélectionnez le jour (Aujourd'hui ou Demain)\n"
            "2️⃣ Envoyez-moi l'heure au format :\n"
            "   • '15:30' ou '1530' (24h)\n"
            "   • '6' (06:00)\n"
            "   • '5 3' (05:03)\n\n"
            "❌ Aucun jour sélectionné"
        )

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        context.user_data['editing_post_id'] = post['id']
        return SCHEDULE_SEND

    except Exception as e:
        logger.error(f"Erreur dans handle_edit_time : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de la modification de l'heure.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_cancel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Annule une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        post = context.user_data.get('current_scheduled_post')
        if not post:
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        keyboard = [
            [
                InlineKeyboardButton("✅ Oui, annuler", callback_data="confirm_cancel"),
                InlineKeyboardButton("❌ Non, garder", callback_data="retour")
            ]
        ]

        await query.edit_message_text(
            "⚠️ Êtes-vous sûr de vouloir annuler cette publication ?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SCHEDULE_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Erreur dans handle_cancel_post : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de l'annulation.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirme l'annulation d'une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        post = context.user_data.get('current_scheduled_post')
        if not post:
            return await handle_error(update, context, "Publication introuvable")

        with sqlite3.connect(settings.db_config["path"]) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM posts WHERE id = ?", (post['id'],))
            conn.commit()

        # Au lieu d'utiliser scheduler_manager directement, nous supprimons le job
        # en utilisant l'application associée au contexte
        job_id = f"post_{post['id']}"
        # Nous ne pouvons pas vérifier si le job existe sans scheduler_manager
        # Simplement essayer de supprimer le job s'il existe
        try:
            if context.application and hasattr(context.application, 'job_queue'):
                context.application.job_queue.remove_job(job_id)
        except Exception as e:
            logger.warning(f"Le job {job_id} n'a pas pu être supprimé: {e}")

        await query.edit_message_text(
            "✅ Publication annulée avec succès !",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )

        context.user_data.pop('current_scheduled_post', None)
        return MAIN_MENU

    except Exception as e:
        return await handle_error(update, context, f"Erreur lors de la confirmation d'annulation : {e}")


async def planifier_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les publications planifiées par chaîne."""
    try:
        with sqlite3.connect(settings.db_config["path"]) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.id, p.type, p.content, p.caption, p.scheduled_time, c.name, c.username
                FROM posts p
                JOIN channels c ON p.channel_id = c.id
                WHERE p.scheduled_time > datetime('now')
                ORDER BY p.scheduled_time
            """)
            scheduled_posts = cursor.fetchall()

        if not scheduled_posts:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "❌ Aucun post planifié trouvé.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )
            else:
                await update.message.reply_text("❌ Aucun post planifié trouvé.")
            return MAIN_MENU

        keyboard = []
        user_id = update.effective_user.id
        user_timezone = db_manager.get_user_timezone(user_id) or "UTC"
        local_tz = pytz.timezone(user_timezone)

        message = "📅 Publications planifiées :\n\n"

        for post in scheduled_posts:
            post_id, post_type, content, caption, scheduled_time, channel_name, channel_username = post
            scheduled_datetime = datetime.strptime(scheduled_time, '%Y-%m-%d %H:%M:%S')
            local_time = scheduled_datetime.replace(tzinfo=pytz.UTC).astimezone(local_tz)

            button_text = f"{local_time.strftime('%d/%m/%Y %H:%M')} - {channel_name} (@{channel_username})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"show_post_{post_id}")])
            message += f"• {button_text}\n"

        keyboard.append([InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")])

        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return SCHEDULE_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Erreur dans planifier_post : {e}")
        error_message = "❌ Une erreur est survenue lors de l'affichage des publications planifiées."
        if update.callback_query:
            await update.callback_query.edit_message_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        else:
            await update.message.reply_text(error_message)
        return MAIN_MENU


async def show_scheduled_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les détails d'une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        post_id = query.data.split('_')[-1]

        with sqlite3.connect(settings.db_config["path"]) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.id, p.type, p.content, p.caption, p.scheduled_time, c.name, c.username
                FROM posts p
                JOIN channels c ON p.channel_id = c.id
                WHERE p.id = ?
            """, (post_id,))
            post_data = cursor.fetchone()

        if not post_data:
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        scheduled_time = datetime.strptime(post_data[4], '%Y-%m-%d %H:%M:%S')

        post = {
            'id': post_data[0],
            'type': post_data[1],
            'content': post_data[2],
            'caption': post_data[3],
            'scheduled_time': post_data[4],
            'channel_name': post_data[5],
            'channel_username': post_data[6],
            'scheduled_date': scheduled_time
        }

        context.user_data['current_scheduled_post'] = post

        keyboard = [
            [InlineKeyboardButton("🕒 Modifier l'heure", callback_data="modifier_heure")],
            [InlineKeyboardButton("🚀 Envoyer maintenant", callback_data="envoyer_maintenant")],
            [InlineKeyboardButton("❌ Annuler la publication", callback_data="annuler_publication")],
            [InlineKeyboardButton("↩️ Retour", callback_data="retour")]
        ]

        try:
            if post['type'] == "photo":
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=post['content'],
                    caption=post.get('caption'),
                    reply_markup=None
                )
            elif post['type'] == "video":
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=post['content'],
                    caption=post.get('caption'),
                    reply_markup=None
                )
            elif post['type'] == "document":
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=post['content'],
                    caption=post.get('caption'),
                    reply_markup=None
                )
            elif post['type'] == "text":
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=post['content'],
                    reply_markup=None
                )
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du contenu : {e}")

        message = (
            f"📝 Publication planifiée :\n\n"
            f"📅 Date : {scheduled_time.strftime('%d/%m/%Y')}\n"
            f"⏰ Heure : {scheduled_time.strftime('%H:%M')}\n"
            f"📍 Canal : {post['channel_name']}\n"
            f"📎 Type : {post['type']}\n"
        )

        await query.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return SCHEDULE_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Erreur dans show_scheduled_post : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de l'affichage de la publication.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def schedule_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Interface de planification des messages"""
    try:
        query = update.callback_query
        await query.answer()

        # Récupérer le jour sélectionné s'il existe
        selected_day = context.user_data.get('schedule_day', None)

        # Créer les boutons avec les emojis appropriés
        keyboard = [
            [
                InlineKeyboardButton(
                    f"Aujourd'hui {'✅' if selected_day == 'today' else ''}",
                    callback_data="schedule_today"
                ),
                InlineKeyboardButton(
                    f"Demain {'✅' if selected_day == 'tomorrow' else ''}",
                    callback_data="schedule_tomorrow"
                ),
            ],
            [InlineKeyboardButton("↩️ Retour", callback_data="send_post")],
        ]

        # Construction du message
        day_status = "✅ Jour sélectionné : " + (
            "Aujourd'hui" if selected_day == "today" else "Demain") if selected_day else "❌ Aucun jour sélectionné"

        message_text = (
            "📅 Choisissez quand envoyer votre publication :\n\n"
            "1️⃣ Sélectionnez le jour (Aujourd'hui ou Demain)\n"
            "2️⃣ Envoyez-moi l'heure au format :\n"
            "   • '15:30' ou '1530' (24h)\n"
            "   • '6' (06:00)\n"
            "   • '5 3' (05:03)\n\n"
            f"{day_status}"
        )

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return SCHEDULE_SEND
    except Exception as e:
        logger.error(f"Erreur lors de la planification de l'envoi : {e}")
        await query.edit_message_text(
            "❌ Erreur lors de la planification.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
        )
        return MAIN_MENU