from typing import Optional, List, Dict
from enum import Enum
import logging
from telegram import Update, Message
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class PostType(Enum):
    """Types de messages supportés"""
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    TEXT = "text"

class MessageError(Exception):
    """Exception pour les erreurs d'envoi de messages"""
    pass

async def send_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    post_type: PostType,
    content: str,
    caption: Optional[str] = None,
    buttons: Optional[List[Dict]] = None
) -> Message:
    """
    Envoie un message de n'importe quel type avec gestion d'erreurs
    
    Args:
        update: Objet Update de Telegram
        context: Contexte de la conversation
        chat_id: ID du chat destinataire
        post_type: Type de message à envoyer
        content: Contenu du message
        caption: Légende optionnelle
        buttons: Boutons optionnels
        
    Returns:
        Message: L'objet message envoyé
        
    Raises:
        MessageError: Si l'envoi échoue
    """
    try:
        if post_type == PostType.PHOTO:
            return await context.bot.send_photo(
                chat_id=chat_id,
                photo=content,
                caption=caption,
                reply_markup=buttons
            )
        elif post_type == PostType.VIDEO:
            return await context.bot.send_video(
                chat_id=chat_id,
                video=content,
                caption=caption,
                reply_markup=buttons
            )
        elif post_type == PostType.DOCUMENT:
            return await context.bot.send_document(
                chat_id=chat_id,
                document=content,
                caption=caption,
                reply_markup=buttons
            )
        elif post_type == PostType.TEXT:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=content,
                reply_markup=buttons
            )
        else:
            raise MessageError(f"Type de message non supporté: {post_type}")
            
    except Exception as e:
        logger.error(f"Erreur d'envoi de message: {e}")
        raise MessageError(f"Impossible d'envoyer le message: {str(e)}")

async def edit_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int,
    chat_id: int,
    text: str,
    buttons: Optional[List[Dict]] = None
) -> Message:
    """
    Modifie un message existant
    
    Args:
        update: Objet Update de Telegram
        context: Contexte de la conversation
        message_id: ID du message à modifier
        chat_id: ID du chat
        text: Nouveau texte
        buttons: Nouveaux boutons optionnels
        
    Returns:
        Message: Le message modifié
    """
    try:
        return await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=buttons
        )
    except Exception as e:
        logger.error(f"Erreur de modification de message: {e}")
        raise MessageError(f"Impossible de modifier le message: {str(e)}")

async def delete_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message_id: int,
    chat_id: int
) -> bool:
    """
    Supprime un message
    
    Args:
        update: Objet Update de Telegram
        context: Contexte de la conversation
        message_id: ID du message à supprimer
        chat_id: ID du chat
        
    Returns:
        bool: True si la suppression a réussi
    """
    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
        return True
    except Exception as e:
        logger.error(f"Erreur de suppression de message: {e}")
        raise MessageError(f"Impossible de supprimer le message: {str(e)}") 