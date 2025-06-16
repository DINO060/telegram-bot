# Corrections pour le format visuel du bot
# Ces extraits doivent être appliqués aux fonctions correspondantes dans bot.py

# -------------------------------------------------------------------------------
# POUR LA FONCTION add_url_button_to_post
# -------------------------------------------------------------------------------

"""
# Remplacer la partie demandant le texte et l'URL dans add_url_button_to_post par:

# Message exactement comme dans la capture d'écran
message_text = (
    "Envoyez-moi le texte et l'URL du bouton au format:\n"
    "Texte du bouton | https://votre-url.com\n\n"
    "Par exemple:\n"
    "🎬 Regarder l'épisode | https://example.com/watch"
)

keyboard = [[InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_url_button_{post_index}")]]

# Vérifier si le message contient un média
message = query.message
if message.photo or message.video or message.document:
    # Pour les messages avec média, on envoie un nouveau message
    await context.bot.send_message(
        chat_id=message.chat_id,
        text=message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
else:
    # Pour les messages texte, on peut modifier le message existant
    await query.edit_message_text(
        message_text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
"""

# -------------------------------------------------------------------------------
# POUR LA FONCTION handle_url_input
# -------------------------------------------------------------------------------

"""
# Message de confirmation comme dans la capture d'écran après traitement de l'URL
await update.message.reply_text(f"✅ Bouton ajouté : {button_text}")

# Pour la partie qui construit les boutons d'action:
# Ajout des boutons d'action comme dans la capture d'écran
keyboard.extend([
    [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
    [InlineKeyboardButton("Supprimer les boutons URL", callback_data=f"remove_url_buttons_{post_index}")],
    [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
])
"""

# -------------------------------------------------------------------------------
# POUR LA FONCTION add_reactions_to_post
# -------------------------------------------------------------------------------

"""
# Message exactement comme dans la capture d'écran 
message_text = (
    "Envoyez-moi une ou plusieurs réactions emoji que vous souhaitez "
    "ajouter à ce post.\n"
    "Par exemple : 👍 😀 🔥 ❤️\n\n"
    "Ces réactions seront visibles par les spectateurs du canal."
)
"""

# -------------------------------------------------------------------------------
# POUR LA FONCTION handle_reaction_input
# -------------------------------------------------------------------------------

"""
# Message de confirmation exactement comme dans la capture d'écran
await update.message.reply_text(
    "✅ Réactions ajoutées avec succès !\nVous pouvez continuer à m'envoyer des messages."
)

# CORRECTION IMPORTANTE: TRAITER LES EMOJI SÉPARÉS PAR "/"
# Remplacer cette ligne:
# reactions = [r.strip() for r in text.split() if r.strip()]
# Par ceci (pour traiter les émojis séparés par espace OU par /):
reactions = []
# D'abord diviser par le séparateur "/"
for part in text.split('/'):
    part = part.strip()
    if part:
        # Ensuite, pour chaque partie, diviser par espace
        for emoji in part.split():
            emoji = emoji.strip()
            if emoji:
                reactions.append(emoji)

# Limiter à 8 réactions
if len(reactions) > 8:
    reactions = reactions[:8]
    await update.message.reply_text("⚠️ Maximum 8 réactions permises. Seules les 8 premières ont été gardées.")
"""

# -------------------------------------------------------------------------------
# POUR LA SUPPRESSION DES BOUTONS URL - NOUVEAU BOUTON
# -------------------------------------------------------------------------------

"""
# Ajouter ce bouton pour la suppression des URL dans la section des réactions
[InlineKeyboardButton("Supprimer les boutons URL", callback_data=f"remove_url_buttons_{post_index}")]
"""

# -------------------------------------------------------------------------------
# MESSAGE D'ERREUR AMÉLIORÉ pour "Chat not found"
# -------------------------------------------------------------------------------

"""
# Dans la fonction send_post_now, remplacer le message d'erreur simple par:
if "Chat not found" in error_message:
    await update.message.reply_text(
        f"❌ Erreur: Canal introuvable\n\n"
        f"Vérifiez que:\n"
        f"1. Le canal @{channel_username} existe\n"
        f"2. Le bot est administrateur du canal\n"
        f"3. Vous avez bien spécifié le nom du canal sans '@'"
    )
else:
    await update.message.reply_text(f"❌ Erreur lors de l'envoi : {error_message}")
""" 