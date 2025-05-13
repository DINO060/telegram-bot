import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler
from mon_bot_telegram.constants import CONVERSATION_STATES

logger = logging.getLogger(__name__)

# Constantes pour les états de conversation
# Ces valeurs doivent correspondre à celles dans votre fichier principal
MAIN_MENU = 0  
POST_ACTIONS = 2  
WAITING_REACTION_INPUT = 16  
WAITING_URL_INPUT = 17  

# -----------------------------------------------------------------------------
# FONCTIONS POUR LES RÉACTIONS
# -----------------------------------------------------------------------------

async def add_reactions_to_post(update, context):
    """Interface pour ajouter des réactions à un post"""
    query = update.callback_query
    
    try:
        # Répondre au callback pour éviter le symbole de chargement
        await query.answer()
        
        # Extraire l'index du post
        if not query.data.startswith("add_reactions_"):
            raise ValueError("Format de callback incorrect")
        
        post_index_str = query.data.replace("add_reactions_", "")
        post_index = int(post_index_str)
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Stocker l'index du post pour utilisation future
        context.user_data['current_post_index'] = post_index
        context.user_data['waiting_for_reactions'] = True
        
        # Message pour demander les réactions
        await query.edit_message_text(
            "✨ Ajout de réactions\n\n"
            "Envoyez-moi une ou plusieurs réactions emoji que vous souhaitez ajouter à ce post.\n"
            "Par exemple : 👍 😂 🔥 ❤️\n\n"
            "Ces réactions seront visibles par les spectateurs du canal.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_reactions_{post_index}")
            ]])
        )
        
        return WAITING_REACTION_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans add_reactions_to_post: {e}")
        logger.exception("Traceback complet:")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de l'ajout de réactions.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_reaction_input(update, context):
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
            return WAITING_REACTION_INPUT
        
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


async def remove_reactions(update, context):
    """Supprime les réactions du post"""
    try:
        query = update.callback_query
        await query.answer()

        # Extraire l'index du post depuis callback_data
        if not query.data.startswith("remove_reactions_"):
            raise ValueError("Format de callback incorrect")
            
        post_index_str = query.data.replace("remove_reactions_", "")
        post_index = int(post_index_str)

        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Supprimer les réactions
        post = context.user_data['posts'][post_index]
        post['reactions'] = []

        # Construire le nouveau clavier
        keyboard = [
            [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
            [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
            [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
        ]

        # Ajouter les boutons URL existants s'il y en a
        if post.get('buttons'):
            url_buttons = []
            for btn in post['buttons']:
                url_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
            keyboard = url_buttons + keyboard

        # Mettre à jour le message avec le nouveau clavier
        if post["type"] == "photo":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        elif post["type"] == "video":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        elif post["type"] == "document":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(
                text=post.get("content", ""),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return POST_ACTIONS
    
    except Exception as e:
        logger.error(f"Erreur dans remove_reactions: {e}")
        logger.exception("Traceback complet:")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de la suppression des réactions.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


# -----------------------------------------------------------------------------
# FONCTIONS POUR LES BOUTONS URL
# -----------------------------------------------------------------------------

async def add_url_button_to_post(update, context):
    """Interface pour ajouter un bouton URL à un post"""
    query = update.callback_query
    
    try:
        # Répondre au callback pour éviter le symbole de chargement
        await query.answer()
        
        # Extraire l'index du post
        if not query.data.startswith("add_url_button_"):
            raise ValueError("Format de callback incorrect")
        
        post_index_str = query.data.replace("add_url_button_", "")
        post_index = int(post_index_str)
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Stocker l'index du post pour utilisation future
        context.user_data['current_post_index'] = post_index
        context.user_data['waiting_for_url'] = True
        
        # Message pour demander les informations du bouton URL
        await query.edit_message_text(
            "🔗 Ajout d'un bouton URL\n\n"
            "Envoyez-moi le texte et l'URL du bouton au format:\n"
            "Texte du bouton, https://example.com\n\n"
            "Exemple: Visiter notre site, https://telegram.org",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_url_button_{post_index}")
            ]])
        )
        
        return WAITING_URL_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans add_url_button_to_post: {e}")
        logger.exception("Traceback complet:")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de l'ajout du bouton URL.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_url_input(update, context):
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
            return WAITING_URL_INPUT
        
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
            return WAITING_URL_INPUT
        
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


async def remove_url_buttons(update, context):
    """Retire les boutons URL d'un post"""
    try:
        query = update.callback_query
        await query.answer()

        # Extraire l'index du post depuis callback_data
        if not query.data.startswith("remove_url_buttons_"):
            raise ValueError("Format de callback incorrect")
            
        post_index_str = query.data.replace("remove_url_buttons_", "")
        post_index = int(post_index_str)

        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Supprimer les boutons URL
        post = context.user_data['posts'][post_index]
        post['buttons'] = []

        # Construire le nouveau clavier
        keyboard = [
            [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
            [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
            [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
        ]

        # Ajouter les réactions existantes s'il y en a
        if post.get('reactions'):
            reaction_buttons = []
            for emoji in post['reactions']:
                reaction_buttons.append(InlineKeyboardButton(f"{emoji}", callback_data=f"react_{post_index}_{emoji}"))
            if reaction_buttons:
                keyboard.insert(0, reaction_buttons)

        # Mettre à jour le message avec le nouveau clavier
        if post["type"] == "photo":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        elif post["type"] == "video":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        elif post["type"] == "document":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(
                text=post.get("content", ""),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return POST_ACTIONS
    
    except Exception as e:
        logger.error(f"Erreur dans remove_url_buttons: {e}")
        logger.exception("Traceback complet:")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de la suppression des boutons URL.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU 