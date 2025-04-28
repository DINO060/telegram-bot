from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from typing import Optional, Dict, Any
import logging
from datetime import datetime

from database.manager import DatabaseManager
from utils.message_utils import PostType, MessageError
from utils.validators import InputValidator

logger = logging.getLogger(__name__)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la réception du texte d'une publication.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        MessageError: Si le texte est invalide ou trop long
    """
    try:
        text = update.message.text
        if not InputValidator.sanitize_text(text):
            raise MessageError("Le texte contient des caractères non autorisés")

        context.user_data['text'] = text

        keyboard = [
            [InlineKeyboardButton("✅ Publier", callback_data="publish")],
            [InlineKeyboardButton("❌ Annuler", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            f"Texte reçu:\n\n{text}\n\nQue souhaitez-vous faire ?",
            reply_markup=reply_markup
        )
        return 9  # WAITING_CONFIRMATION

    except MessageError as e:
        logger.error(f"Erreur de message: {str(e)}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
        return 4  # WAITING_TEXT
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
        return 4  # WAITING_TEXT


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la réception d'un média (photo/vidéo).

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        MessageError: Si le média n'est pas supporté
    """
    try:
        if update.message.photo:
            context.user_data['media'] = update.message.photo[-1].file_id
            context.user_data['media_type'] = 'photo'
        elif update.message.video:
            context.user_data['media'] = update.message.video.file_id
            context.user_data['media_type'] = 'video'
        else:
            raise MessageError("Format non supporté. Veuillez envoyer une photo ou une vidéo.")

        keyboard = [
            [InlineKeyboardButton("✅ Publier", callback_data="publish")],
            [InlineKeyboardButton("❌ Annuler", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Média reçu. Que souhaitez-vous faire ?",
            reply_markup=reply_markup
        )
        return 9  # WAITING_CONFIRMATION

    except MessageError as e:
        logger.error(f"Erreur de média: {str(e)}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
        return 5  # WAITING_MEDIA
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
        return 5  # WAITING_MEDIA


async def handle_schedule_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la réception du texte d'une publication planifiée.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        MessageError: Si le texte est invalide ou trop long
    """
    try:
        text = update.message.text
        if not InputValidator.sanitize_text(text):
            raise MessageError("Le texte contient des caractères non autorisés")

        context.user_data['text'] = text

        await update.message.reply_text(
            "Entrez la date et l'heure de publication (format: JJ/MM/AAAA HH:MM):"
        )
        return 10  # WAITING_SCHEDULE_TIME

    except MessageError as e:
        logger.error(f"Erreur de message planifié: {str(e)}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
        return 6  # WAITING_SCHEDULE_TEXT
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
        return 6  # WAITING_SCHEDULE_TEXT


async def handle_schedule_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la réception d'un média pour une publication planifiée.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        MessageError: Si le média n'est pas supporté
    """
    try:
        if update.message.photo:
            context.user_data['media'] = update.message.photo[-1].file_id
            context.user_data['media_type'] = 'photo'
        elif update.message.video:
            context.user_data['media'] = update.message.video.file_id
            context.user_data['media_type'] = 'video'
        else:
            raise MessageError("Format non supporté. Veuillez envoyer une photo ou une vidéo.")

        await update.message.reply_text(
            "Entrez la date et l'heure de publication (format: JJ/MM/AAAA HH:MM):"
        )
        return 10  # WAITING_SCHEDULE_TIME

    except MessageError as e:
        logger.error(f"Erreur de média planifié: {str(e)}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")
        return 7  # WAITING_SCHEDULE_MEDIA
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
        return 7  # WAITING_SCHEDULE_MEDIA


async def handle_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Gère la configuration du fuseau horaire.

    Args:
        update: L'objet Update de Telegram
        context: Le contexte de la conversation

    Returns:
        int: L'état suivant de la conversation

    Raises:
        MessageError: Si le fuseau horaire est invalide
    """
    try:
        timezone = update.message.text.strip()

        # Vérifier si le fuseau horaire est valide
        import pytz
        pytz.timezone(timezone)

        # Sauvegarder le fuseau horaire
        db = DatabaseManager()
        await db.update_user_timezone(update.effective_user.id, timezone)

        await update.message.reply_text(
            f"✅ Fuseau horaire configuré: {timezone}"
        )
        return ConversationHandler.END

    except pytz.exceptions.UnknownTimeZoneError:
        logger.error(f"Fuseau horaire invalide: {timezone}")
        await update.message.reply_text(
            "❌ Fuseau horaire invalide. Veuillez réessayer."
        )
        return 8  # WAITING_TIMEZONE
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}")
        await update.message.reply_text("❌ Une erreur inattendue s'est produite")
        return 8  # WAITING_TIMEZONE