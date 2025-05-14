import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler
from mon_bot_telegram.constants import CONVERSATION_STATES

logger = logging.getLogger(__name__)

# Constantes pour les états de conversation
# Ces valeurs doivent correspondre à celles dans votre fichier principal
MAIN_MENU = 0  
POST_ACTIONS = 2  
WAITING_REACTION_INPUT = 21  # Mis à jour pour correspondre à CONVERSATION_STATES
WAITING_URL_INPUT = 22  # Mis à jour pour correspondre à CONVERSATION_STATES

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
        
        # S'assurer que 'posts' existe
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Aucun post disponible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
            
        # Vérifier que le post existe
        if post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Stocker l'index du post pour utilisation future
        context.user_data['current_post_index'] = post_index
        context.user_data['waiting_for_reactions'] = True
        
        # Créer un clavier avec des emojis populaires
        emoji_keyboard = [
            [
                InlineKeyboardButton("👍", callback_data=f"select_emoji_{post_index}_👍"),
                InlineKeyboardButton("❤️", callback_data=f"select_emoji_{post_index}_❤️"),
                InlineKeyboardButton("😂", callback_data=f"select_emoji_{post_index}_😂"),
                InlineKeyboardButton("🔥", callback_data=f"select_emoji_{post_index}_🔥")
            ],
            [
                InlineKeyboardButton("👏", callback_data=f"select_emoji_{post_index}_👏"),
                InlineKeyboardButton("🎉", callback_data=f"select_emoji_{post_index}_🎉"),
                InlineKeyboardButton("😍", callback_data=f"select_emoji_{post_index}_😍"),
                InlineKeyboardButton("🙏", callback_data=f"select_emoji_{post_index}_🙏")
            ],
            [
                InlineKeyboardButton("✅", callback_data=f"select_emoji_{post_index}_✅"),
                InlineKeyboardButton("👌", callback_data=f"select_emoji_{post_index}_👌"),
                InlineKeyboardButton("💯", callback_data=f"select_emoji_{post_index}_💯"),
                InlineKeyboardButton("⭐", callback_data=f"select_emoji_{post_index}_⭐")
            ],
            [
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_reactions_{post_index}"),
                InlineKeyboardButton("✅ Terminer", callback_data=f"finish_reactions_{post_index}")
            ]
        ]
        
        # Message pour demander les réactions - envoi d'un nouveau message au lieu de modifier
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✨ Ajout de réactions\n\n"
                "Cliquez sur les emojis ci-dessous pour les ajouter comme réactions ou envoyez vos propres emojis.\n"
                "Vous pouvez sélectionner jusqu'à 8 réactions.\n\n"
                "Ces réactions seront visibles par les spectateurs du canal.",
            reply_markup=InlineKeyboardMarkup(emoji_keyboard)
        )
        
        # Initialiser la liste des réactions sélectionnées si elle n'existe pas
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            post = context.user_data['posts'][post_index]
            if 'reactions' not in post:
                post['reactions'] = []
        
        return WAITING_REACTION_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans add_reactions_to_post: {e}")
        logger.exception("Traceback complet:")
        try:
            # Envoyer un nouveau message au lieu de modifier
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Une erreur est survenue lors de l'ajout de réactions.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        except Exception as inner_e:
            logger.error(f"Erreur secondaire: {inner_e}")
        return MAIN_MENU


async def select_emoji(update, context):
    """Gère la sélection d'un emoji via un bouton"""
    query = update.callback_query
    try:
        await query.answer()
        
        # Extraire l'index du post et l'emoji depuis callback_data
        # Format: select_emoji_INDEX_EMOJI
        parts = query.data.split('_', 3)
        if len(parts) < 4:
            raise ValueError("Format de callback incorrect")
        
        post_index = int(parts[2])
        emoji = parts[3]
        
        # S'assurer que 'posts' existe
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Aucun post disponible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Vérifier que le post existe
        if post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Ajouter l'emoji à la liste des réactions si ce n'est pas déjà fait
        post = context.user_data['posts'][post_index]
        if 'reactions' not in post:
            post['reactions'] = []
            
        # Éviter les doublons
        if emoji not in post['reactions']:
            # Limiter à 8 réactions maximum
            if len(post['reactions']) < 8:
                post['reactions'].append(emoji)
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="⚠️ Maximum 8 réactions permises."
                )
                return WAITING_REACTION_INPUT
        
        # Recréer le clavier avec les emojis déjà sélectionnés en haut
        emoji_keyboard = [
            [
                InlineKeyboardButton("👍", callback_data=f"select_emoji_{post_index}_👍"),
                InlineKeyboardButton("❤️", callback_data=f"select_emoji_{post_index}_❤️"),
                InlineKeyboardButton("😂", callback_data=f"select_emoji_{post_index}_😂"),
                InlineKeyboardButton("🔥", callback_data=f"select_emoji_{post_index}_🔥")
            ],
            [
                InlineKeyboardButton("👏", callback_data=f"select_emoji_{post_index}_👏"),
                InlineKeyboardButton("🎉", callback_data=f"select_emoji_{post_index}_🎉"),
                InlineKeyboardButton("😍", callback_data=f"select_emoji_{post_index}_😍"),
                InlineKeyboardButton("🙏", callback_data=f"select_emoji_{post_index}_🙏")
            ],
            [
                InlineKeyboardButton("✅", callback_data=f"select_emoji_{post_index}_✅"),
                InlineKeyboardButton("👌", callback_data=f"select_emoji_{post_index}_👌"),
                InlineKeyboardButton("💯", callback_data=f"select_emoji_{post_index}_💯"),
                InlineKeyboardButton("⭐", callback_data=f"select_emoji_{post_index}_⭐")
            ],
            [
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_reactions_{post_index}"),
                InlineKeyboardButton("✅ Terminer", callback_data=f"finish_reactions_{post_index}")
            ]
        ]
        
        # Ajouter une rangée pour afficher les emojis sélectionnés
        selected_emojis = post['reactions']
        if selected_emojis:
            selected_row = []
            for emoji in selected_emojis:
                selected_row.append(InlineKeyboardButton(f"{emoji}", callback_data=f"remove_emoji_{post_index}_{emoji}"))
            emoji_keyboard.insert(0, selected_row)
        
        # Mettre à jour le message avec les emojis sélectionnés
        await query.edit_message_text(
            text=f"✨ Ajout de réactions\n\n"
                f"Emojis sélectionnés: {' '.join(selected_emojis) if selected_emojis else 'Aucun'}\n\n"
                "Cliquez sur les emojis ci-dessous pour les ajouter comme réactions ou envoyez vos propres emojis.\n"
                "Vous pouvez sélectionner jusqu'à 8 réactions.\n\n"
                "Ces réactions seront visibles par les spectateurs du canal.",
            reply_markup=InlineKeyboardMarkup(emoji_keyboard)
        )
        
        return WAITING_REACTION_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans select_emoji: {e}")
        logger.exception("Traceback complet:")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Une erreur est survenue lors de la sélection de l'emoji.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def remove_emoji(update, context):
    """Supprime un emoji spécifique de la liste des réactions"""
    query = update.callback_query
    try:
        await query.answer()
        
        # Extraire l'index du post et l'emoji depuis callback_data
        parts = query.data.split('_', 3)
        if len(parts) < 4:
            raise ValueError("Format de callback incorrect")
        
        post_index = int(parts[2])
        emoji = parts[3]
        
        # S'assurer que 'posts' existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Supprimer l'emoji de la liste des réactions
        post = context.user_data['posts'][post_index]
        if 'reactions' in post and emoji in post['reactions']:
            post['reactions'].remove(emoji)
        
        # Recréer le clavier avec les emojis restants
        emoji_keyboard = [
            [
                InlineKeyboardButton("👍", callback_data=f"select_emoji_{post_index}_👍"),
                InlineKeyboardButton("❤️", callback_data=f"select_emoji_{post_index}_❤️"),
                InlineKeyboardButton("😂", callback_data=f"select_emoji_{post_index}_😂"),
                InlineKeyboardButton("🔥", callback_data=f"select_emoji_{post_index}_🔥")
            ],
            [
                InlineKeyboardButton("👏", callback_data=f"select_emoji_{post_index}_👏"),
                InlineKeyboardButton("🎉", callback_data=f"select_emoji_{post_index}_🎉"),
                InlineKeyboardButton("😍", callback_data=f"select_emoji_{post_index}_😍"),
                InlineKeyboardButton("🙏", callback_data=f"select_emoji_{post_index}_🙏")
            ],
            [
                InlineKeyboardButton("✅", callback_data=f"select_emoji_{post_index}_✅"),
                InlineKeyboardButton("👌", callback_data=f"select_emoji_{post_index}_👌"),
                InlineKeyboardButton("💯", callback_data=f"select_emoji_{post_index}_💯"),
                InlineKeyboardButton("⭐", callback_data=f"select_emoji_{post_index}_⭐")
            ],
            [
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_reactions_{post_index}"),
                InlineKeyboardButton("✅ Terminer", callback_data=f"finish_reactions_{post_index}")
            ]
        ]
        
        # Ajouter une rangée pour afficher les emojis sélectionnés
        selected_emojis = post.get('reactions', [])
        if selected_emojis:
            selected_row = []
            for emoji in selected_emojis:
                selected_row.append(InlineKeyboardButton(f"{emoji}", callback_data=f"remove_emoji_{post_index}_{emoji}"))
            emoji_keyboard.insert(0, selected_row)
        
        # Mettre à jour le message avec les emojis restants
        await query.edit_message_text(
            text=f"✨ Ajout de réactions\n\n"
                f"Emojis sélectionnés: {' '.join(selected_emojis) if selected_emojis else 'Aucun'}\n\n"
                "Cliquez sur les emojis ci-dessous pour les ajouter comme réactions ou envoyez vos propres emojis.\n"
                "Vous pouvez sélectionner jusqu'à 8 réactions.\n\n"
                "Ces réactions seront visibles par les spectateurs du canal.",
            reply_markup=InlineKeyboardMarkup(emoji_keyboard)
        )
        
        return WAITING_REACTION_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans remove_emoji: {e}")
        logger.exception("Traceback complet:")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Une erreur est survenue lors de la suppression de l'emoji.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def finish_reactions(update, context):
    """Finalise l'ajout de réactions et affiche le message avec les réactions sélectionnées"""
    query = update.callback_query
    try:
        await query.answer()
        
        # Extraire l'index du post depuis callback_data
        if not query.data.startswith("finish_reactions_"):
            raise ValueError("Format de callback incorrect")
            
        post_index_str = query.data.replace("finish_reactions_", "")
        post_index = int(post_index_str)

        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Récupérer les réactions
        post = context.user_data['posts'][post_index]
        emojis = post.get('reactions', [])
        
        # Réinitialiser l'état d'attente
        context.user_data['waiting_for_reactions'] = False
        
        # Construire le nouveau clavier
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
        try:
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
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du message avec réactions: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Une erreur est survenue lors de l'envoi du message.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
            
        # Message de confirmation
        if emojis:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ Réactions ajoutées avec succès : {' '.join(emojis)}"
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="ℹ️ Aucune réaction n'a été ajoutée."
            )
        
        # Sauvegarder les réactions dans la base de données si elle existe
        if 'db_manager' in context.bot_data:
            db_manager = context.bot_data['db_manager']
            if post.get('db_id'):
                # Mise à jour de la publication dans la base de données
                db_manager.update_post_reactions(post['db_id'], emojis)
        
        return POST_ACTIONS
        
    except Exception as e:
        logger.error(f"Erreur dans finish_reactions: {e}")
        logger.exception("Traceback complet:")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Une erreur est survenue lors de la finalisation des réactions.",
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
        
        # S'assurer que 'posts' existe
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
            await update.message.reply_text(
                "❌ Aucun post disponible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Vérifier que le post existe
        if post_index is None or post_index >= len(context.user_data['posts']):
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
        
        # Ajout des boutons URL s'ils existent
        if post.get('buttons'):
            url_buttons = []
            for btn in post['buttons']:
                url_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
            keyboard = url_buttons + keyboard
        
        # Envoi du nouveau message avec les réactions
        try:
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
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du message avec réactions: {e}")
            await update.message.reply_text(
                "❌ Une erreur est survenue lors de l'envoi du message.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
            
        # Message de confirmation
        await update.message.reply_text(
            f"✅ Réactions ajoutées avec succès : {' '.join(emojis)}"
        )
        
        # Réinitialiser l'état d'attente
        context.user_data['waiting_for_reactions'] = False
        
        # Sauvegarder les réactions dans la base de données si elle existe
        if 'db_manager' in context.bot_data:
            db_manager = context.bot_data['db_manager']
            if post.get('db_id'):
                # Mise à jour de la publication dans la base de données
                db_manager.update_post_reactions(post['db_id'], emojis)
        
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
    query = update.callback_query
    try:
        await query.answer()

        # Extraire l'index du post depuis callback_data
        if not query.data.startswith("remove_reactions_"):
            raise ValueError("Format de callback incorrect")
            
        post_index_str = query.data.replace("remove_reactions_", "")
        post_index = int(post_index_str)
        
        # S'assurer que 'posts' existe
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
            await query.edit_message_text(
                "❌ Aucun post disponible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Vérifier que le post existe
        if post_index >= len(context.user_data['posts']):
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
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        
        # Mise à jour de current_post si nécessaire
        if context.user_data.get('current_post_index') == post_index:
            context.user_data['current_post'] = post
            
        # Sauvegarder la suppression des réactions dans la base de données si elle existe
        if 'db_manager' in context.bot_data:
            db_manager = context.bot_data['db_manager']
            if post.get('db_id'):
                # Mise à jour de la publication dans la base de données
                db_manager.update_post_reactions(post['db_id'], [])
        
        # Message de confirmation
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Réactions supprimées avec succès."
        )
        
        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur dans remove_reactions: {e}")
        logger.exception("Traceback complet:")
        try:
            await query.edit_message_text(
                "❌ Une erreur est survenue lors de la suppression des réactions.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        except:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Une erreur est survenue lors de la suppression des réactions.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )
            except:
                pass
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
        
        # S'assurer que 'posts' existe
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Aucun post disponible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
            
        # Vérifier que le post existe
        if post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Stocker l'index du post pour utilisation future
        context.user_data['current_post_index'] = post_index
        context.user_data['waiting_for_url'] = True
        context.user_data['url_input_step'] = 'text'  # Commencer par demander le texte
        
        # Message pour demander le texte du bouton
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔗 Ajout d'un bouton URL\n\n"
            "1️⃣ Étape 1/2: Envoyez-moi le texte à afficher sur le bouton.\n"
            "Par exemple : \"Voir plus\", \"Télécharger\", \"Site officiel\"",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_url_button_{post_index}")
            ]])
        )
        
        return WAITING_URL_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans add_url_button_to_post: {e}")
        logger.exception("Traceback complet:")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Une erreur est survenue lors de l'ajout du bouton URL.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        except Exception as inner_e:
            logger.error(f"Erreur secondaire: {inner_e}")
        return MAIN_MENU


async def handle_url_input(update, context):
    """Traite la saisie du texte et de l'URL pour un bouton"""
    try:
        # Vérifier qu'on est bien en attente d'un URL
        if not context.user_data.get('waiting_for_url', False):
            await update.message.reply_text(
                "❌ Je n'attends pas d'URL actuellement.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer l'input
        user_input = update.message.text.strip()
        
        # Vérifier que l'input n'est pas vide
        if not user_input:
            await update.message.reply_text(
                "❌ Le texte ne peut pas être vide.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data="main_menu")
                ]])
            )
            return WAITING_URL_INPUT
        
        # Récupérer l'index du post
        post_index = context.user_data.get('current_post_index')
        
        # S'assurer que 'posts' existe
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
            await update.message.reply_text(
                "❌ Aucun post disponible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Vérifier que le post existe
        if post_index is None or post_index >= len(context.user_data['posts']):
            await update.message.reply_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Traiter l'entrée en fonction de l'étape
        if context.user_data.get('url_input_step') == 'text':
            # Première étape: enregistrer le texte et demander l'URL
            context.user_data['url_button_text'] = user_input
            context.user_data['url_input_step'] = 'url'
            
            await update.message.reply_text(
                f"✅ Texte du bouton: \"{user_input}\"\n\n"
                "2️⃣ Étape 2/2: Maintenant, envoyez-moi l'URL vers laquelle le bouton doit rediriger.\n"
                "Par exemple: https://monsite.com",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_url_button_{post_index}")
                ]])
            )
            return WAITING_URL_INPUT
            
        elif context.user_data.get('url_input_step') == 'url':
            # Deuxième étape: enregistrer l'URL et créer le bouton
            
            # Vérifier le format de l'URL (basique)
            import re
            url_pattern = re.compile(r'^https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)$')
            if not url_pattern.match(user_input):
                await update.message.reply_text(
                    "❌ Format d'URL invalide. Assurez-vous que l'URL commence par http:// ou https://.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("Réessayer", callback_data=f"add_url_button_{post_index}")
                    ]])
                )
                return POST_ACTIONS
            
            # Récupérer le texte du bouton
            button_text = context.user_data.get('url_button_text', "Lien")
            button_url = user_input
            
            # Créer ou mettre à jour la liste des boutons
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
            
            # Construire le nouveau clavier
            keyboard = [
                [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                [InlineKeyboardButton("🗑️ Supprimer les boutons URL", callback_data=f"remove_url_buttons_{post_index}")],
                [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
                [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
            ]
            
            # Ajouter les boutons URL au début du clavier
            url_buttons = []
            for btn in post['buttons']:
                url_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                
            # Ajouter les réactions si elles existent
            reaction_buttons = []
            if post.get('reactions'):
                for emoji in post['reactions']:
                    reaction_buttons.append(InlineKeyboardButton(f"{emoji}", callback_data=f"react_{post_index}_{emoji}"))
                if reaction_buttons:
                    keyboard.insert(0, reaction_buttons)
            
            # Ajouter les boutons URL au début
            keyboard = url_buttons + keyboard
            
            # Envoi du nouveau message avec le bouton URL
            try:
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
            except Exception as e:
                logger.error(f"Erreur lors de l'envoi du message avec bouton URL: {e}")
                await update.message.reply_text(
                    "❌ Une erreur est survenue lors de l'envoi du message.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )
                return MAIN_MENU
                
            # Message de confirmation
            await update.message.reply_text(
                f"✅ Bouton URL ajouté : \"{button_text}\" → {button_url}"
            )
            
            # Réinitialiser l'état d'attente et les variables temporaires
            context.user_data['waiting_for_url'] = False
            if 'url_input_step' in context.user_data:
                del context.user_data['url_input_step']
            if 'url_button_text' in context.user_data:
                del context.user_data['url_button_text']
            
            # Sauvegarder les boutons URL dans la base de données si elle existe
            if 'db_manager' in context.bot_data:
                db_manager = context.bot_data['db_manager']
                if post.get('db_id'):
                    # Mise à jour de la publication dans la base de données
                    db_manager.update_post_buttons(post['db_id'], post['buttons'])
            
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
    """Supprime tous les boutons URL du post"""
    query = update.callback_query
    try:
        await query.answer()

        # Extraire l'index du post depuis callback_data
        if not query.data.startswith("remove_url_buttons_"):
            raise ValueError("Format de callback incorrect")
            
        post_index_str = query.data.replace("remove_url_buttons_", "")
        post_index = int(post_index_str)

        # S'assurer que 'posts' existe
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
            await query.edit_message_text(
                "❌ Aucun post disponible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Vérifier que le post existe
        if post_index >= len(context.user_data['posts']):
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
            [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
            [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
            [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
        ]

        # Ajouter les réactions si elles existent
        reaction_buttons = []
        if post.get('reactions'):
            for emoji in post['reactions']:
                reaction_buttons.append(InlineKeyboardButton(f"{emoji}", callback_data=f"react_{post_index}_{emoji}"))
            if reaction_buttons:
                keyboard.insert(0, reaction_buttons)

        # Mettre à jour le message avec le nouveau clavier
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        
        # Mise à jour de current_post si nécessaire
        if context.user_data.get('current_post_index') == post_index:
            context.user_data['current_post'] = post
            
        # Sauvegarder la suppression des boutons URL dans la base de données si elle existe
        if 'db_manager' in context.bot_data:
            db_manager = context.bot_data['db_manager']
            if post.get('db_id'):
                # Mise à jour de la publication dans la base de données
                db_manager.update_post_buttons(post['db_id'], [])
        
        # Message de confirmation
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Boutons URL supprimés avec succès."
        )
        
        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur dans remove_url_buttons: {e}")
        logger.exception("Traceback complet:")
        try:
            await query.edit_message_text(
                "❌ Une erreur est survenue lors de la suppression des boutons URL.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        except:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Une erreur est survenue lors de la suppression des boutons URL.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )
            except:
                pass
        return MAIN_MENU


async def delete_post(update, context):
    """Supprime un message et ses données associées"""
    query = update.callback_query
    try:
        await query.answer()

        # Extraire l'index du post depuis callback_data
        if not query.data.startswith("delete_post_"):
            raise ValueError("Format de callback incorrect")
            
        post_index_str = query.data.replace("delete_post_", "")
        post_index = int(post_index_str)

        # S'assurer que 'posts' existe
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
            await query.edit_message_text(
                "❌ Aucun post disponible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
            
        # Vérifier que le post existe
        if post_index >= len(context.user_data['posts']):
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Récupérer le post avant de le supprimer
        post = context.user_data['posts'][post_index]
        post_id = post.get('db_id')
        message_id = query.message.message_id

        # Supprimer le message de Telegram
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=message_id
            )
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du message: {e}")
            # Continuer malgré l'erreur, car l'important est de supprimer les données

        # Supprimer le post de la liste des posts
        context.user_data['posts'].pop(post_index)

        # Supprimer les données associées dans la base de données si elle existe
        if 'db_manager' in context.bot_data and post_id:
            db_manager = context.bot_data['db_manager']
            db_manager.delete_post(post_id)

        # Message de confirmation
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Message supprimé.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        
        return MAIN_MENU

    except Exception as e:
        logger.error(f"Erreur dans delete_post: {e}")
        logger.exception("Traceback complet:")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Une erreur est survenue lors de la suppression du post.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        except:
            pass
        return MAIN_MENU


async def cancel_reactions(update, context):
    """Annule l'ajout de réactions"""
    query = update.callback_query
    try:
        await query.answer()

        # Extraire l'index du post depuis callback_data
        if not query.data.startswith("cancel_reactions_"):
            raise ValueError("Format de callback incorrect")

        post_index_str = query.data.replace("cancel_reactions_", "")
        post_index = int(post_index_str)

        # Réinitialiser l'état d'attente
        context.user_data['waiting_for_reactions'] = False
        
        # Préparer le clavier avec les options d'origine
        keyboard = []
        
        # S'assurer que 'posts' existe
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            post = context.user_data['posts'][post_index]
            
            # Construire le clavier standard
            keyboard = [
                [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
                [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
            ]
            
            # Ajouter les boutons URL s'ils existent
            if post.get('buttons'):
                url_buttons = []
                for btn in post['buttons']:
                    url_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                keyboard = url_buttons + keyboard
                
            # Ajouter les réactions si elles existent
            if post.get('reactions'):
                reaction_buttons = []
                for emoji in post['reactions']:
                    reaction_buttons.append(InlineKeyboardButton(f"{emoji}", callback_data=f"react_{post_index}_{emoji}"))
                if reaction_buttons:
                    keyboard.insert(0, reaction_buttons)
        else:
            # Si le post n'est pas disponible, revenir au menu principal
            keyboard = [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]

        # Envoyer un nouveau message au lieu de modifier
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Ajout de réactions annulé.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur dans cancel_reactions: {e}")
        logger.exception("Traceback complet:")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Une erreur est survenue.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        except Exception as inner_e:
            logger.error(f"Erreur secondaire: {inner_e}")
        return MAIN_MENU


async def cancel_url_button(update, context):
    """Annule l'ajout d'un bouton URL"""
    query = update.callback_query
    try:
        await query.answer()

        # Extraire l'index du post depuis callback_data
        if not query.data.startswith("cancel_url_button_"):
            raise ValueError("Format de callback incorrect")

        post_index_str = query.data.replace("cancel_url_button_", "")
        post_index = int(post_index_str)

        # Réinitialiser l'état d'attente
        context.user_data['waiting_for_url'] = False
        if 'url_input_step' in context.user_data:
            del context.user_data['url_input_step']
        if 'url_button_text' in context.user_data:
            del context.user_data['url_button_text']
        
        # Préparer le clavier avec les options d'origine
        keyboard = []
        
        # S'assurer que 'posts' existe
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            post = context.user_data['posts'][post_index]
            
            # Construire le clavier standard
            keyboard = [
                [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
                [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
            ]
            
            # Ajouter les boutons URL s'ils existent
            if post.get('buttons'):
                url_buttons = []
                for btn in post['buttons']:
                    url_buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                keyboard = url_buttons + keyboard
                
            # Ajouter les réactions si elles existent
            if post.get('reactions'):
                reaction_buttons = []
                for emoji in post['reactions']:
                    reaction_buttons.append(InlineKeyboardButton(f"{emoji}", callback_data=f"react_{post_index}_{emoji}"))
                if reaction_buttons:
                    keyboard.insert(0, reaction_buttons)
        else:
            # Si le post n'est pas disponible, revenir au menu principal
            keyboard = [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]

        # Envoyer un nouveau message au lieu de modifier
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ Ajout de bouton URL annulé.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur dans cancel_url_button: {e}")
        logger.exception("Traceback complet:")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Une erreur est survenue.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        except Exception as inner_e:
            logger.error(f"Erreur secondaire: {inner_e}")
        return MAIN_MENU 