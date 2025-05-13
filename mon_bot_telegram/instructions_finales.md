# Instructions pour l'implémentation des boutons Réactions, URL et Suppression

Voici les étapes à suivre pour implémenter les trois fonctionnalités demandées dans votre bot Telegram :

## Fichiers créés

1. `mon_bot_telegram/reaction_functions.py` : Contient toutes les fonctions pour gérer les réactions et boutons URL
2. `mon_bot_telegram/implementation_steps.md` : Guide détaillé des étapes d'implémentation
3. `mon_bot_telegram/instructions_finales.md` : Ce fichier que vous lisez actuellement

## Étapes d'implémentation

### 1. Modifier les états de conversation

Dans le fichier `bot.py`, recherchez le bloc où sont définis les états de conversation (vers la ligne 144) :

```python
(
    MAIN_MENU,
    POST_CONTENT,
    POST_ACTIONS,
    # ... autres états ...
    WAITING_TIMEZONE,
    WAITING_THUMBNAIL,
) = range(16)
```

Modifiez-le pour ajouter les deux nouveaux états :

```python
(
    MAIN_MENU,
    POST_CONTENT,
    POST_ACTIONS,
    # ... autres états ...
    WAITING_TIMEZONE,
    WAITING_THUMBNAIL,
    WAITING_REACTION_INPUT,  # Nouvel état pour les réactions
    WAITING_URL_INPUT,       # Nouvel état pour les boutons URL
) = range(18)
```

### 2. Ajouter l'import dans bot.py

Au début du fichier `bot.py`, ajoutez cette ligne d'import :

```python
from mon_bot_telegram.reaction_functions import handle_reaction_input, handle_url_input, add_reactions_to_post, remove_reactions, add_url_button_to_post, remove_url_buttons
```

### 3. Ajouter les nouveaux états au ConversationHandler

Dans la configuration du ConversationHandler (vers la ligne 1171), ajoutez :

```python
WAITING_REACTION_INPUT: [
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reaction_input),
    CallbackQueryHandler(handle_callback),
],
WAITING_URL_INPUT: [
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url_input),
    CallbackQueryHandler(handle_callback),
],
```

### 4. Ajouter les gestionnaires de callback

Dans la fonction `handle_callback` du fichier `bot.py`, ajoutez cette section (avant la condition "Si aucun callback n'a été reconnu") :

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

## Fonctionnalités ajoutées

### 1. Bouton "Ajouter des réactions"
- Permet d'ajouter jusqu'à 8 emojis comme réactions à un post
- Les réactions sont affichées sous forme de boutons cliquables
- Les utilisateurs peuvent cliquer sur les réactions pour interagir

### 2. Bouton "Ajouter un bouton URL"
- Permet d'ajouter des boutons avec un texte personnalisé qui redirigent vers une URL
- Format: "Texte du bouton, https://example.com"
- Les boutons URL apparaissent au-dessus des boutons d'action

### 3. Bouton "Supprimer"
- Permet de supprimer des messages et leurs données associées
- Fonctionnalité déjà présente dans votre code via la fonction `handle_delete_post`

## Test des fonctionnalités

1. Démarrez votre bot avec la commande habituelle
2. Créez un nouveau post (texte, image, vidéo, etc.)
3. Dans l'interface du post, vous verrez les boutons:
   - "Ajouter des réactions"
   - "Ajouter un bouton URL" 
   - "Supprimer"
4. Testez chaque fonctionnalité pour vous assurer qu'elle fonctionne comme prévu

## Dépannage

Si vous rencontrez des erreurs:
1. Vérifiez les journaux du bot pour identifier l'erreur
2. Assurez-vous que tous les fichiers sont correctement importés
3. Vérifiez que les modifications ont été appliquées aux bons endroits dans le code

Pour toute question supplémentaire, n'hésitez pas à demander de l'aide. 