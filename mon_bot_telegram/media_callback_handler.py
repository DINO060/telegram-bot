"""
Gestionnaire spécialisé pour les messages de média.
Cette approche adapte les méthodes utilisées selon le type de message (texte vs média).
"""

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import traceback
import sys
import os

# Add the parent directory to sys.path to ensure imports work correctly
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Définir le logger
logger = logging.getLogger(__name__)

# États de la conversation - ces valeurs doivent correspondre à celles définies dans bot.py
MAIN_MENU = 0
POST_ACTIONS = 17
WAITING_REACTION_INPUT = 16
WAITING_URL_INPUT = 17


async def handle_media_callback(update, context, data):
    """
    Handle callbacks for media files specifically.
    This is used for large files or forwarded messages where editing the original message might not work.
    """
    try:
        query = update.callback_query
        user_id = update.effective_user.id
        chat_id = query.message.chat_id
        message_id = query.message.message_id

        logger.info(f"Media callback handler processing: {data}")

        # Extract callback type and post index
        parts = data.split('_')
        callback_type = parts[0]
        post_index = int(parts[-1]) if parts[-1].isdigit() else None

        # Process based on callback type
        if callback_type == "add" and "reactions" in data:
            # Handle adding reactions to a media post
            context.user_data['waiting_for_reactions'] = True
            context.user_data['current_post_index'] = post_index

            # Send a new message requesting reactions
            await context.bot.send_message(
                chat_id=chat_id,
                text="Envoyez-moi les réactions que vous souhaitez ajouter, séparées par des /\n"
                     "✅/🔥/Super/❤️",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_reactions_{post_index}")
                ]])
            )

            # Answer the callback query to remove loading indicator
            await query.answer("Envoyez les réactions")
            return context.user_data.get('current_state', 'WAITING_REACTION_INPUT')

        elif callback_type == "add" and "url_button" in data:
            # Handle adding URL button to a media post
            context.user_data['waiting_for_url'] = True
            context.user_data['current_post_index'] = post_index

            # Send a new message requesting URL button details
            await context.bot.send_message(
                chat_id=chat_id,
                text="Envoyez-moi le texte et l'URL du bouton au format:\n"
                     "Texte du bouton | https://votre-url.com\n\n"
                     "Par exemple:\n"
                     "🎬 Regarder l'épisode | https://example.com/watch",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_url_button_{post_index}")
                ]])
            )

            # Answer the callback query
            await query.answer("Envoyez le texte et l'URL")
            return context.user_data.get('current_state', 'WAITING_URL_INPUT')

        elif callback_type == "delete" and "post" in data:
            # Handle deleting media post
            if 'posts' in context.user_data and post_index is not None and post_index < len(context.user_data['posts']):
                # Remove the post
                removed_post = context.user_data['posts'].pop(post_index)
                post_type = removed_post.get('type', 'inconnu')

                # Update current post index if needed
                if 'current_post_index' in context.user_data and context.user_data['current_post_index'] == post_index:
                    context.user_data.pop('current_post_index')
                    context.user_data.pop('current_post', None)

                # Send confirmation message
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Post de type {post_type} supprimé avec succès.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )

                # Answer the callback query
                await query.answer("Post supprimé")
                return context.user_data.get('current_state', 'MAIN_MENU')

        elif callback_type == "rename" and "post" in data:
            # Handle renaming media post (adding or changing caption)
            context.user_data['waiting_for_rename'] = True
            context.user_data['current_post_index'] = post_index

            # Get current caption if it exists
            post = context.user_data['posts'][post_index] if 'posts' in context.user_data and post_index < len(
                context.user_data['posts']) else {}
            current_caption = post.get("caption", "") if post.get("type") != "text" else post.get("content", "")

            # Send a new message asking for the new caption
            await context.bot.send_message(
                chat_id=chat_id,
                text="✏️ Renommer le post\n\n"
                     f"Contenu actuel:\n{current_caption[:100]}{'...' if len(current_caption) > 100 else ''}\n\n"
                     "Envoyez-moi le nouveau texte pour ce post.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_rename_{post_index}")
                ]])
            )

            # Answer the callback query
            await query.answer("Envoyez le nouveau texte")
            return context.user_data.get('current_state', 'POST_ACTIONS')

        elif callback_type == "remove" and "reactions" in data:
            # Handle removing reactions
            if 'posts' in context.user_data and post_index is not None and post_index < len(context.user_data['posts']):
                post = context.user_data['posts'][post_index]
                if 'reactions' in post:
                    post['reactions'] = []

                # Send confirmation
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="✅ Réactions supprimées"
                )

                # Answer the callback query
                await query.answer("Réactions supprimées")
                return context.user_data.get('current_state', 'POST_ACTIONS')

        elif callback_type == "remove" and "url_buttons" in data:
            # Handle removing URL buttons
            if 'posts' in context.user_data and post_index is not None and post_index < len(context.user_data['posts']):
                post = context.user_data['posts'][post_index]
                if 'buttons' in post:
                    post['buttons'] = []

                # Send confirmation
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="✅ Boutons URL supprimés"
                )

                # Answer the callback query
                await query.answer("Boutons URL supprimés")
                return context.user_data.get('current_state', 'POST_ACTIONS')

        # If we get here, the callback wasn't handled
        logger.warning(f"Media callback handler could not process: {data}")
        await query.answer("Cette action n'est pas disponible pour ce type de message")
        return None
        
    except Exception as e:
        logger.error(f"Error in handle_media_callback: {e}")
        logger.exception("Complete traceback:")
        try:
            await update.callback_query.answer("Une erreur est survenue")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Une erreur est survenue lors du traitement de votre demande.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
                ])
            )
        except Exception as send_error:
            logger.error(f"Secondary error: {send_error}")
        return None