# Guide d'implémentation des boutons : Réactions, URL, et Suppression

## 1. Ajouter les nouveaux états de conversation

Dans le fichier `bot.py`, cherchez la section où sont définis les états (vers la ligne 144) :

```python
(
    MAIN_MENU,
    POST_CONTENT,
    POST_ACTIONS,
    SEND_OPTIONS,
    AUTO_DESTRUCTION,
    SCHEDULE_SEND,
    EDIT_POST,
    SCHEDULE_SELECT_CHANNEL,
    STATS_SELECT_CHANNEL,
    WAITING_CHANNEL_INFO,
    SETTINGS,
    BACKUP_MENU,
    WAITING_CHANNEL_SELECTION,
    WAITING_PUBLICATION_CONTENT,
    WAITING_TIMEZONE,
    WAITING_THUMBNAIL,
) = range(16)
```

Modifiez-la pour ajouter les deux nouveaux états :

```python
(
    MAIN_MENU,
    POST_CONTENT,
    POST_ACTIONS,
    SEND_OPTIONS,
    AUTO_DESTRUCTION,
    SCHEDULE_SEND,
    EDIT_POST,
    SCHEDULE_SELECT_CHANNEL,
    STATS_SELECT_CHANNEL,
    WAITING_CHANNEL_INFO,
    SETTINGS,
    BACKUP_MENU,
    WAITING_CHANNEL_SELECTION,
    WAITING_PUBLICATION_CONTENT,
    WAITING_TIMEZONE,
    WAITING_THUMBNAIL,
    WAITING_REACTION_INPUT,  # Nouvel état pour les réactions
    WAITING_URL_INPUT,       # Nouvel état pour les boutons URL
) = range(18)
```

## 2. Ajouter les imports nécessaires

Au début du fichier `bot.py`, ajoutez l'import :

```python
from mon_bot_telegram.reaction_functions import handle_reaction_input, handle_url_input
```

## 3. Remplacer les fonctions des boutons

### 3.1 Fonction add_reactions_to_post (vers ligne 2475)

```python
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
```

### 3.2 Fonction remove_reactions (vers ligne 2489)

```python
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
```

### 3.3 Fonction add_url_button_to_post (vers ligne 2503)

```python
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
```

### 3.4 Fonction remove_url_buttons (vers ligne 2517)

```python
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
```

## 4. Ajouter au ConversationHandler

Dans le fichier `bot.py`, trouvez la déclaration du ConversationHandler (vers la ligne 1171), et ajoutez les nouveaux états dans sa configuration :

```python
conv_handler = ConversationHandler(
    entry_points=[...],
    states={
        # ... autres états ...
        
        WAITING_REACTION_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reaction_input),
            CallbackQueryHandler(handle_callback),
        ],
        WAITING_URL_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_input),
            CallbackQueryHandler(handle_callback),
        ],
    },
    fallbacks=[...],
)
```

## 5. Modifier le handle_callback

Dans la fonction handle_callback du fichier `bot.py`, ajoutez cette section (peut-être avant la partie "Si aucun callback n'a été reconnu...") :

```python
# ---------- GESTION DES RÉACTIONS ----------
elif data == "add_reactions" or data.startswith("add_reactions_"):
    logger.info(f"Traitement de l'ajout de réactions avec callback_data: {data}")
    return await add_reactions_to_post(update, context)

elif data == "remove_reactions" or data.startswith("remove_reactions_"):
    logger.info(f"Traitement de la suppression des réactions avec callback_data: {data}")
    return await remove_reactions(update, context)

# ---------- GESTION DES BOUTONS URL ----------
elif data == "add_url_button" or data.startswith("add_url_button_"):
    logger.info(f"Traitement de l'ajout de bouton URL avec callback_data: {data}")
    return await add_url_button_to_post(update, context)

elif data == "remove_url_buttons" or data.startswith("remove_url_buttons_"):
    logger.info(f"Traitement de la suppression des boutons URL avec callback_data: {data}")
    return await remove_url_buttons(update, context)

# ---------- GESTION DES ANNULATIONS ----------
elif data.startswith("cancel_reactions_"):
    # Annuler l'opération d'ajout de réactions
    if 'waiting_for_reactions' in context.user_data:
        del context.user_data['waiting_for_reactions']
    if 'current_post_index' in context.user_data:
        post_index = int(data.replace("cancel_reactions_", ""))
        await query.edit_message_text(
            "❌ Opération d'ajout de réactions annulée.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
                [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
            ])
        )
    else:
        await query.edit_message_text(
            "❌ Opération d'ajout de réactions annulée.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
    return WAITING_PUBLICATION_CONTENT

elif data.startswith("cancel_url_button_"):
    # Annuler l'opération d'ajout de bouton URL
    if 'waiting_for_url' in context.user_data:
        del context.user_data['waiting_for_url']
    if 'current_post_index' in context.user_data:
        post_index = int(data.replace("cancel_url_button_", ""))
        await query.edit_message_text(
            "❌ Opération d'ajout de bouton URL annulée.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
                [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
            ])
        )
    else:
        await query.edit_message_text(
            "❌ Opération d'ajout de bouton URL annulée.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
    return WAITING_PUBLICATION_CONTENT
    
# ---------- GESTION DES RÉACTIONS INDIVIDUELLES ----------
elif data.startswith("react_"):
    logger.info(f"Réaction individuelle détectée: {data}")
    # Code pour gérer les réactions individuelles
    parts = data.split('_')
    if len(parts) >= 3:
        try:
            post_index = int(parts[1])
            reaction = parts[2]
            logger.info(f"Réaction {reaction} pour le post {post_index}")
            await query.answer(f"Vous avez réagi avec {reaction}")
            # Ici vous pouvez ajouter le code pour traiter la réaction
        except (ValueError, IndexError) as e:
            logger.error(f"Erreur lors du traitement de la réaction: {e}")
            await query.answer("Erreur lors du traitement de la réaction")
    return
``` 