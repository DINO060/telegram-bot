# Fichier contenant les updates à faire dans handle_callback
# Ajouter dans la fonction handle_callback:

# ---------- GESTION DES RÉACTIONS ----------
elif data == "add_reactions" or data.startswith("add_reactions_"):
    logger.info(f"Traitement de l'ajout de réactions avec callback_data: {data}")
    return await add_reactions_to_post(update, context)

elif data == "remove_reactions" or data.startswith("remove_reactions_"):
    logger.info(f"Traitement de la suppression des réactions avec callback_data: {data}")
    return await remove_reactions(update, context)

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
    return CONVERSATION_STATES['POST_ACTIONS']

# ---------- GESTION DES BOUTONS URL ----------
elif data == "add_url_button" or data.startswith("add_url_button_"):
    logger.info(f"Traitement de l'ajout de bouton URL avec callback_data: {data}")
    return await add_url_button_to_post(update, context)

elif data == "remove_url_buttons" or data.startswith("remove_url_buttons_"):
    logger.info(f"Traitement de la suppression des boutons URL avec callback_data: {data}")
    return await remove_url_buttons(update, context)

elif data.startswith("cancel_url_button_"):
    # Annuler l'opération d'ajout de bouton URL
    if 'waiting_for_url' in context.user_data:
        del context.user_data['waiting_for_url']
    if 'url_input_step' in context.user_data:
        del context.user_data['url_input_step']
    if 'url_button_text' in context.user_data:
        del context.user_data['url_button_text']
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
    return CONVERSATION_STATES['POST_ACTIONS'] 