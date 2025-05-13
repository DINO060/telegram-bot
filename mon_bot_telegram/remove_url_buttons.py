import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, InputMediaDocument
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Constantes pour les états de conversation
MAIN_MENU = 0
POST_ACTIONS = 2

async def remove_url_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Retire les boutons URL d'un post"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Extraire l'index du post depuis le callback_data
        post_index = int(query.data.split('_')[-1]) if '_' in query.data else 0
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer le post
        post = context.user_data['posts'][post_index]
        
        # Vérifier s'il y a des boutons URL à supprimer
        if not post.get('buttons'):
            await query.edit_message_text(
                "⚠️ Aucun bouton URL à supprimer pour ce post.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Supprimer les boutons URL
        old_buttons = post.get('buttons', [])
        post['buttons'] = []
        
        # Mettre à jour current_post si nécessaire
        if context.user_data.get('current_post_index') == post_index:
            context.user_data['current_post'] = post
        
        # Recréer le clavier sans les boutons URL
        keyboard = [
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
            [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
            [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
        ]
        
        # Ajouter les réactions si elles existent
        if post.get('reactions'):
            reaction_buttons = []
            current_row = []
            for i, emoji in enumerate(post['reactions']):
                current_row.append(InlineKeyboardButton(f"{emoji}", callback_data=f"react_{post_index}_{i}"))
                # 4 boutons par ligne maximum
                if len(current_row) == 4 or i == len(post['reactions']) - 1:
                    reaction_buttons.append(current_row)
                    current_row = []
            if reaction_buttons:
                keyboard = reaction_buttons + keyboard
        
        # Mettre à jour le message sans les boutons URL
        if post["type"] == "photo":
            try:
                await query.edit_message_media(
                    media=InputMediaPhoto(
                        media=post["content"],
                        caption=post.get("caption")
                    ),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Erreur lors de l'édition du média photo: {e}")
                # Méthode alternative: nouveau message
                await query.message.reply_photo(
                    photo=post["content"],
                    caption=post.get("caption"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                await query.edit_message_text(
                    "✅ Boutons URL supprimés. Veuillez utiliser le nouveau message ci-dessous."
                )
        elif post["type"] == "video":
            # Pour les vidéos, on ne peut pas éditer le média, donc on répond avec un nouveau message
            await query.message.reply_video(
                video=post["content"],
                caption=post.get("caption"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            # On informe l'utilisateur que l'ancien message doit être ignoré
            await query.edit_message_text(
                "✅ Boutons URL supprimés. Veuillez utiliser le nouveau message ci-dessous."
            )
        elif post["type"] == "document":
            # Pour les documents, on ne peut pas éditer le média, donc on répond avec un nouveau message
            await query.message.reply_document(
                document=post["content"],
                caption=post.get("caption"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            # On informe l'utilisateur que l'ancien message doit être ignoré
            await query.edit_message_text(
                "✅ Boutons URL supprimés. Veuillez utiliser le nouveau message ci-dessous."
            )
        else:  # texte
            await query.edit_message_text(
                text=post["content"],
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        # Confirmation
        await query.message.reply_text(
            f"✅ {len(old_buttons)} boutons URL supprimés avec succès."
        )
        
        return POST_ACTIONS
        
    except Exception as e:
        logger.error(f"Erreur lors de la suppression des boutons URL: {e}")
        logger.exception("Traceback complet:")
        try:
            await query.edit_message_text(
                "❌ Une erreur est survenue lors de la suppression des boutons URL.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        except:
            # Si on ne peut pas éditer le message, on répond avec un nouveau message
            await query.message.reply_text(
                "❌ Une erreur est survenue lors de la suppression des boutons URL.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        return MAIN_MENU 