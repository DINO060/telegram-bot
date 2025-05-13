import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Constantes pour les états de conversation
MAIN_MENU = 0
POST_ACTIONS = 2

async def handle_post_actions_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère les actions textuelles sur les posts en cours de création"""
    try:
        text = update.message.text.lower()
        
        if text == "envoyer":
            from bot import send_post_now
            return await send_post_now(update, context)
        elif text == "annuler":
            if 'posts' in context.user_data:
                context.user_data.pop('posts')
            if 'current_post' in context.user_data:
                context.user_data.pop('current_post')
            if 'current_post_index' in context.user_data:
                context.user_data.pop('current_post_index')
            
            await update.message.reply_text(
                "❌ Création de publication annulée.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        elif text == "aperçu":
            if 'current_post' in context.user_data:
                post = context.user_data['current_post']
                
                # Afficher un aperçu du post selon son type
                if post['type'] == 'photo':
                    await update.message.reply_photo(
                        photo=post['content'],
                        caption=post.get('caption')
                    )
                elif post['type'] == 'video':
                    await update.message.reply_video(
                        video=post['content'],
                        caption=post.get('caption')
                    )
                elif post['type'] == 'document':
                    await update.message.reply_document(
                        document=post['content'],
                        caption=post.get('caption')
                    )
                elif post['type'] == 'text':
                    await update.message.reply_text(
                        f"📝 Aperçu: \n\n{post['content']}"
                    )
            else:
                await update.message.reply_text("❌ Aucun post en cours.")
            
            return POST_ACTIONS
        elif text == "tout supprimer":
            if 'posts' in context.user_data:
                context.user_data.pop('posts')
            if 'current_post' in context.user_data:
                context.user_data.pop('current_post')
            if 'current_post_index' in context.user_data:
                context.user_data.pop('current_post_index')
            
            await update.message.reply_text(
                "🗑️ Tous les posts ont été supprimés.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        # Traitement des réactions si on est en attente
        elif context.user_data.get('waiting_for_reactions') and context.user_data.get('current_post_index') is not None:
            # Extraire les réactions
            reactions_text = update.message.text
            emojis = [r.strip() for r in reactions_text.split('/') if r.strip()]
            
            if not emojis:
                await update.message.reply_text(
                    "❌ Veuillez envoyer au moins une réaction valide.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_reactions_{context.user_data['current_post_index']}")
                    ]])
                )
                return POST_ACTIONS
            
            post_index = context.user_data['current_post_index']
            
            # Limiter à 8 réactions maximum
            if len(emojis) > 8:
                emojis = emojis[:8]
                await update.message.reply_text("⚠️ Maximum 8 réactions permises. Seules les 8 premières ont été gardées.")
            
            # Ajouter les réactions au post
            post = context.user_data['posts'][post_index]
            post['reactions'] = emojis
            context.user_data['current_post'] = post
            
            # Créer un aperçu actualisé avec les réactions
            keyboard = [
                [InlineKeyboardButton("Supprimer les réactions", callback_data=f"remove_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
            ]
            
            # Afficher les réactions dans le message
            reaction_buttons = []
            current_row = []
            for i, emoji in enumerate(emojis):
                current_row.append(InlineKeyboardButton(f"{emoji}", callback_data=f"react_{post_index}_{i}"))
                # 4 boutons par ligne maximum
                if len(current_row) == 4 or i == len(emojis) - 1:
                    reaction_buttons.append(current_row)
                    current_row = []
            
            if reaction_buttons:
                keyboard = reaction_buttons + keyboard
            
            # Ajouter les boutons URL s'ils existent
            if post.get('buttons'):
                url_buttons = []
                for btn in post['buttons']:
                    url_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                keyboard = url_buttons + keyboard
            
            # Envoi du nouveau message avec les réactions
            if post["type"] == "photo":
                await update.message.reply_photo(
                    photo=post["content"],
                    caption=post.get("caption"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post["type"] == "video":
                await update.message.reply_video(
                    video=post["content"],
                    caption=post.get("caption"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post["type"] == "document":
                await update.message.reply_document(
                    document=post["content"],
                    caption=post.get("caption"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:  # texte
                await update.message.reply_text(
                    post["content"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            # Message de confirmation
            await update.message.reply_text(f"✅ Réactions ajoutées avec succès: {' '.join(emojis)}")
            
            # Réinitialiser l'état d'attente
            context.user_data['waiting_for_reactions'] = False
            
            return POST_ACTIONS
            
        # Traitement des boutons URL si on est en attente
        elif context.user_data.get('waiting_for_url') and context.user_data.get('current_post_index') is not None:
            # Récupérer le texte et l'URL
            url_input = update.message.text.strip()
            
            # Vérifier le format (texte | url)
            parts = []
            if "|" in url_input:
                parts = url_input.split("|", 1)
            elif "," in url_input:
                parts = url_input.split(",", 1)  # Accepter aussi la virgule comme séparateur
            else:
                await update.message.reply_text(
                    "❌ Format incorrect. Utilisez: \"Texte du bouton | https://example.com\"",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_url_button_{context.user_data['current_post_index']}")
                    ]])
                )
                return POST_ACTIONS
            
            # Séparer le texte et l'URL
            button_text = parts[0].strip()
            button_url = parts[1].strip()
            
            # Vérifier que le texte et l'URL ne sont pas vides
            if not button_text or not button_url:
                await update.message.reply_text(
                    "❌ Le texte du bouton et l'URL ne peuvent pas être vides.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_url_button_{context.user_data['current_post_index']}")
                    ]])
                )
                return POST_ACTIONS
            
            # Vérifier que l'URL est valide et ajouter https:// si nécessaire
            if not button_url.startswith(("http://", "https://", "t.me/")):
                button_url = "https://" + button_url
            
            post_index = context.user_data['current_post_index']
            post = context.user_data['posts'][post_index]
            
            # Ajouter le bouton URL au post
            if 'buttons' not in post:
                post['buttons'] = []
            
            # Ajouter le nouveau bouton
            post['buttons'].append({
                'text': button_text,
                'url': button_url
            })
            
            context.user_data['current_post'] = post
            
            # Créer un aperçu actualisé avec le bouton URL
            keyboard = [
                [InlineKeyboardButton("Supprimer les boutons URL", callback_data=f"remove_url_buttons_{post_index}")],
                [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
            ]
            
            # Ajouter les boutons URL
            url_buttons = []
            for btn in post['buttons']:
                url_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
            
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
            
            # Insérer les boutons URL au début du clavier
            keyboard = url_buttons + keyboard
            
            # Envoi du nouveau message avec le bouton URL
            if post["type"] == "photo":
                await update.message.reply_photo(
                    photo=post["content"],
                    caption=post.get("caption"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post["type"] == "video":
                await update.message.reply_video(
                    video=post["content"],
                    caption=post.get("caption"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post["type"] == "document":
                await update.message.reply_document(
                    document=post["content"],
                    caption=post.get("caption"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:  # texte
                await update.message.reply_text(
                    post["content"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            # Message de confirmation
            await update.message.reply_text(f"✅ Bouton URL ajouté: {button_text} → {button_url}")
            
            # Réinitialiser l'état d'attente
            context.user_data['waiting_for_url'] = False
            
            return POST_ACTIONS
        else:
            # Si le texte ne correspond à aucune commande, on traite comme un nouveau post
            from bot import handle_post_content
            return await handle_post_content(update, context)
            
    except Exception as e:
        logger.error(f"Erreur dans handle_post_actions_text: {e}")
        logger.exception("Traceback complet:")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors du traitement de votre action.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU 