import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Constantes pour les états de conversation
MAIN_MENU = 0
POST_ACTIONS = 2

async def add_reactions_to_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Interface pour ajouter des réactions à un post"""
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
        
        # Stocker l'état d'attente dans le contexte utilisateur
        context.user_data['waiting_for_reactions'] = True
        context.user_data['current_post_index'] = post_index
        
        keyboard = [
            [InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_reactions_{post_index}")]
        ]
        
        await query.edit_message_text(
            "✨ Ajout de réactions\n\n"
            "Envoyez-moi les réactions séparées par des /\n"
            "Exemple: 🔥/😍/Wow/Incroyable/👍/❤️\n\n"
            "• Maximum 8 réactions\n"
            "• Emojis ou textes courts acceptés",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return POST_ACTIONS
    
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout de réactions: {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de l'ajout de réactions.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU 