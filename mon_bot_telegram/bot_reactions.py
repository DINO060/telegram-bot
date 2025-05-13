import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Constantes pour les états de conversation
MAIN_MENU = 0
POST_ACTIONS = 2

async def handle_reaction_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Traite la saisie des emojis de réaction"""
    try:
        # Vérifier qu'on est bien en attente de réactions
        if not context.user_data.get('waiting_for_reactions', False):
            await update.message.reply_text(
                "❌ Je n'attends pas de réactions actuellement.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer les emojis
        reactions_text = update.message.text.strip()
        
        # Vérifier que le texte contient des emojis
        if not reactions_text:
            await update.message.reply_text(
                "❌ Veuillez envoyer au moins un emoji.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer l'index du post
        post_index = context.user_data.get('current_post_index')
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await update.message.reply_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Extraire les emojis du texte (simple split pour cet exemple)
        emojis = reactions_text.split()
        
        # Limiter à 8 réactions maximum
        if len(emojis) > 8:
            emojis = emojis[:8]
            await update.message.reply_text(
                "⚠️ Maximum 8 réactions permises. Seules les 8 premières ont été gardées."
            )
        
        # Ajouter les réactions au post
        post = context.user_data['posts'][post_index]
        post['reactions'] = emojis
        
        # Mise à jour de current_post si nécessaire
        if context.user_data.get('current_post_index') == post_index:
            context.user_data['current_post'] = post
        
        # Créer un aperçu actualisé avec les réactions
        keyboard = [
            [InlineKeyboardButton("Supprimer les réactions", callback_data=f"remove_reactions_{post_index}")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
            [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
            [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
        ]
        
        # Afficher les réactions dans le message
        reaction_buttons = []
        for emoji in emojis:
            reaction_buttons.append(InlineKeyboardButton(f"{emoji}", callback_data=f"react_{post_index}_{emoji}"))
        
        if reaction_buttons:
            keyboard.insert(0, reaction_buttons)
        
        # Ajouter les boutons URL s'ils existent
        if post.get('buttons'):
            url_buttons = []
            for btn in post['buttons']:
                url_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
            keyboard = url_buttons + keyboard
        
        # Envoi du nouveau message avec les réactions
        post = context.user_data['posts'][post_index]
        
        if post["type"] == "photo":
            sent_message = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=post["content"],
                caption=post.get("caption"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif post["type"] == "video":
            sent_message = await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=post["content"],
                caption=post.get("caption"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif post["type"] == "document":
            sent_message = await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=post["content"],
                caption=post.get("caption"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:  # texte
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=post["content"],
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        # Message de confirmation
        await update.message.reply_text(
            f"✅ Réactions ajoutées avec succès : {' '.join(emojis)}"
        )
        
        # Réinitialiser l'état d'attente
        context.user_data['waiting_for_reactions'] = False
        
        return POST_ACTIONS
        
    except Exception as e:
        logger.error(f"Erreur dans handle_reaction_input: {e}")
        logger.exception("Traceback complet:")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de l'ajout des réactions.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU 