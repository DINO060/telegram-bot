# Instructions pour ajouter les fonctionnalités de réactions et boutons URL

Ce document explique comment mettre en place les nouvelles fonctionnalités permettant à l'utilisateur d'ajouter des réactions et des boutons URL à ses posts.

## 1. Étapes d'installation

### 1.1 Ouvrir le fichier `bot.py` et ajouter les nouveaux états

Recherchez la section où sont définis les états de conversation (vers la ligne 144) :

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

Et modifiez-la pour ajouter les deux nouveaux états :

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

### 1.2 Vérifier que le fichier `reaction_functions.py` est bien présent

Ce fichier contient toutes les fonctions nécessaires pour gérer les réactions et les boutons URL. Si ce n'est pas le cas, créez-le avec le contenu fourni.

### 1.3 Mettre à jour le ConversationHandler

Recherchez le ConversationHandler dans le fichier `bot.py` (vers la ligne 1171) et ajoutez les nouveaux états :

```python
conv_handler = ConversationHandler(
    entry_points=[...],
    states={
        # ... autres états ...
        
        # Ajouter ces deux nouveaux blocs
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

### 1.4 Ajouter les imports nécessaires

Au début du fichier `bot.py`, ajoutez les imports pour les nouvelles fonctions :

```python
from mon_bot_telegram.reaction_functions import (
    add_reactions_to_post, 
    handle_reaction_input,
    remove_reactions,
    add_url_button_to_post,
    handle_url_input,
    remove_url_buttons
)
```

## 2. Erreurs courantes et solutions

### 2.1 Erreur "L'état n'existe pas dans le ConversationHandler"

Assurez-vous que vous avez bien ajouté les deux nouveaux états dans le ConversationHandler.

### 2.2 Erreur "module 'mon_bot_telegram.reaction_functions' has no attribute '...'"

Vérifiez que le fichier `reaction_functions.py` est complet et contient toutes les fonctions nécessaires.

### 2.3 Erreur "Fonction non définie"

Assurez-vous d'avoir importé les bonnes fonctions depuis `reaction_functions.py`.

## 3. Fonctionnalités ajoutées

### 3.1 Ajout de réactions

L'utilisateur peut ajouter des réactions (emojis) à ses posts. Ces réactions seront visibles pour les autres utilisateurs.

### 3.2 Boutons URL

L'utilisateur peut ajouter des boutons cliquables sous ses posts, qui redirigent vers un lien externe.

### 3.3 Suppression

Des fonctions de suppression sont également disponibles pour retirer les réactions ou les boutons URL ajoutés. 