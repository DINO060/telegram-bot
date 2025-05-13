import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Constantes pour les états de conversation
MAIN_MENU = 0
POST_ACTIONS = 2

async def handle_url_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Traite la saisie des informations du bouton URL"""
    try:
        # Vérifier qu'on est bien en attente d'URL
        if not context.user_data.get('waiting_for_url', False):
            await update.message.reply_text(
                "❌ Je n'attends pas d'URL actuellement.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer le texte et l'URL
        url_input = update.message.text.strip()
        
        # Vérifier le format (texte, url)
        if "," not in url_input:
            await update.message.reply_text(
                "❌ Format incorrect. Utilisez : Texte du bouton, https://example.com",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Séparer le texte et l'URL
        parts = url_input.split(",", 1)
        button_text = parts[0].strip()
        button_url = parts[1].strip()
        
        # Vérifier que le texte et l'URL ne sont pas vides
        if not button_text or not button_url:
            await update.message.reply_text(
                "❌ Le texte du bouton et l'URL ne peuvent pas être vides.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Vérifier que l'URL est valide
        if not button_url.startswith(("http://", "https://", "t.me/")):
            button_url = "https://" + button_url
        
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
        
        # Ajouter le bouton URL au post
        post = context.user_data['posts'][post_index]
        if 'buttons' not in post:
            post['buttons'] = []
        
        # Ajouter le nouveau bouton
        post['buttons'].append({
            'text': button_text,
            'url': button_url
        })
        
        # Mise à jour de current_post si nécessaire
        if context.user_data.get('current_post_index') == post_index:
            context.user_data['current_post'] = post
        
        # Créer un aperçu actualisé avec le bouton URL
        keyboard = [
            [InlineKeyboardButton("Supprimer les boutons URL", callback_data=f"remove_url_buttons_{post_index}")],
            [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
            [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
            [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
        ]
        
        # Ajouter les boutons URL
        url_buttons = []
        for btn in post['buttons']:
            url_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
        
        # Ajouter les réactions si elles existent
        if post.get('reactions'):
            reaction_buttons = []
            for emoji in post['reactions']:
                reaction_buttons.append(InlineKeyboardButton(f"{emoji}", callback_data=f"react_{post_index}_{emoji}"))
            if reaction_buttons:
                keyboard.insert(0, reaction_buttons)
        
        # Insérer les boutons URL au début du clavier
        keyboard = url_buttons + keyboard
        
        # Envoi du nouveau message avec le bouton URL
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
            f"✅ Bouton URL ajouté avec succès : {button_text} → {button_url}"
        )
        
        # Réinitialiser l'état d'attente
        context.user_data['waiting_for_url'] = False
        
        return POST_ACTIONS
        
    except Exception as e:
        logger.error(f"Erreur dans handle_url_input: {e}")
        logger.exception("Traceback complet:")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de l'ajout du bouton URL.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU 