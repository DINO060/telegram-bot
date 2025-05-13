async def handle_url_input(update: Update, context):
    """Gère l'input des boutons URL"""
    if 'waiting_for_url' not in context.user_data or 'current_post_index' not in context.user_data:
        return WAITING_PUBLICATION_CONTENT

    try:
        post_index = context.user_data['current_post_index']
        text = update.message.text.strip()

        # Validation du format
        if '|' not in text:
            await update.message.reply_text(
                "❌ Format incorrect. Utilisez : Texte du bouton | URL\n"
                "Exemple : Visiter le site | https://example.com"
            )
            return WAITING_PUBLICATION_CONTENT

        button_text, url = [part.strip() for part in text.split('|', 1)]

        # Validation de l'URL
        if not url.startswith(('http://', 'https://')):
            await update.message.reply_text(
                "❌ L'URL doit commencer par http:// ou https://"
            )
            return WAITING_PUBLICATION_CONTENT

        # Ajout du bouton au post
        if 'buttons' not in context.user_data['posts'][post_index]:
            context.user_data['posts'][post_index]['buttons'] = []
        context.user_data['posts'][post_index]['buttons'].append({
            'text': button_text,
            'url': url
        })

        # Construction du nouveau clavier
        keyboard = []

        # Ajout des réactions existantes
        if context.user_data['posts'][post_index].get('reactions'):
            current_row = []
            for reaction in context.user_data['posts'][post_index]['reactions']:
                current_row.append(InlineKeyboardButton(
                    f"{reaction}",
                    callback_data=f"react_{post_index}_{reaction}"
                ))
                if len(current_row) == 4:
                    keyboard.append(current_row)
                    current_row = []
            if current_row:
                keyboard.append(current_row)

        # Ajout des boutons URL
        for btn in context.user_data['posts'][post_index]['buttons']:
            keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])

        # Ajout des boutons d'action
        keyboard.extend([
            [InlineKeyboardButton(
                "Supprimer les réactions" if context.user_data['posts'][post_index].get('reactions') else "➕ Ajouter des réactions", 
                callback_data=f"remove_reactions_{post_index}" if context.user_data['posts'][post_index].get('reactions') else f"add_reactions_{post_index}")],
            [InlineKeyboardButton("Supprimer les boutons URL", callback_data=f"remove_url_buttons_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
            [InlineKeyboardButton("✅ Envoyer", callback_data="send_post")]
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Suppression de l'ancien message d'aperçu s'il existe
        preview_info = context.user_data.get('preview_messages', {}).get(post_index)
        if preview_info:
            try:
                await context.bot.delete_message(
                    chat_id=preview_info['chat_id'],
                    message_id=preview_info['message_id']
                )
            except Exception:
                pass

        # Envoi du nouveau message avec le bouton URL
        post = context.user_data['posts'][post_index]
        sent_message = None

        if post["type"] == "photo":
            sent_message = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=post["content"],
                caption=post.get("caption"),
                reply_markup=reply_markup
            )
        elif post["type"] == "video":
            sent_message = await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=post["content"],
                caption=post.get("caption"),
                reply_markup=reply_markup
            )
        elif post["type"] == "document":
            sent_message = await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=post["content"],
                caption=post.get("caption"),
                reply_markup=reply_markup
            )
        elif post["type"] == "text":
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=post["content"],
                reply_markup=reply_markup
            )

        if sent_message:
            # Mise à jour des informations du message d'aperçu
            if 'preview_messages' not in context.user_data:
                context.user_data['preview_messages'] = {}
            context.user_data['preview_messages'][post_index] = {
                'message_id': sent_message.message_id,
                'chat_id': update.effective_chat.id
            }

        # Message de confirmation et retour à l'état d'attente
        await update.message.reply_text(
            "✅ Bouton URL ajouté avec succès !\n"
            "Vous pouvez continuer à m'envoyer des messages."
        )

        # Nettoyage du contexte
        del context.user_data['waiting_for_url']
        del context.user_data['current_post_index']
        return WAITING_PUBLICATION_CONTENT

    except Exception as e:
        logger.error(f"Erreur lors du traitement du bouton URL : {e}")
        await update.message.reply_text(
            "❌ Erreur lors du traitement du bouton URL.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return WAITING_PUBLICATION_CONTENT 