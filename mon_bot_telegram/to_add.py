# Fonctions manquantes à ajouter au bot.py

# Variable globale pour le userbot
userbot = None

async def start(update, context):
    """Point d'entrée principal du bot"""
    keyboard = [
        [InlineKeyboardButton("📝 Nouvelle publication", callback_data="create_publication")],
        [InlineKeyboardButton("📅 Publications planifiées", callback_data="planifier_post")],
        [InlineKeyboardButton("📊 Statistiques", callback_data="channel_stats")],
        [InlineKeyboardButton("⚙️ Paramètres", callback_data="settings")]
    ]
    reply_keyboard = [
        [KeyboardButton("Tout supprimer"), KeyboardButton("Aperçu")],
        [KeyboardButton("Annuler"), KeyboardButton("Envoyer")]
    ]
    reply_markup = ReplyKeyboardMarkup(
        reply_keyboard,
        resize_keyboard=True,
        one_time_keyboard=False
    )

    try:
        if update.message:
            await update.message.reply_text(
                "Bienvenue sur le Publisher Bot!\nQue souhaitez-vous faire ?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            await update.message.reply_text(
                "Actions rapides :",
                reply_markup=reply_markup
            )
        else:
            await update.callback_query.edit_message_text(
                "Bienvenue sur le Publisher Bot!\nQue souhaitez-vous faire ?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            await update.callback_query.message.reply_text(
                "Actions rapides :",
                reply_markup=reply_markup
            )
        return MAIN_MENU
    except Exception as e:
        logger.error(f"Erreur lors du démarrage : {e}")
        return MAIN_MENU

async def send_post_now(update, context, scheduled_post=None):
    """Envoie un post immédiatement"""
    try:
        # Vérification du rate limit
        if not await rate_limiter.can_send_message(
                update.effective_chat.id,
                update.effective_user.id
        ):
            await update.message.reply_text(
                "⚠️ Trop de messages envoyés. Veuillez attendre un moment."
            )
            return

        if scheduled_post:
            post = scheduled_post
        else:
            post = context.user_data.get('current_post')

        if not post:
            await update.message.reply_text("❌ Aucun post à envoyer")
            return

        channel_id = post.get('channel_id')
        if not channel_id:
            await update.message.reply_text("❌ Canal non spécifié")
            return

        # Récupérer les informations du canal
        channel = db_manager.get_channel_by_username(post['channel'], update.effective_user.id)
        if not channel:
            await update.message.reply_text("❌ Canal non trouvé")
            return

        # Envoyer le post selon son type
        try:
            if post['type'] == 'photo':
                await context.bot.send_photo(
                    chat_id=channel[0],
                    photo=post['content'],
                    caption=post.get('caption')
                )
            elif post['type'] == 'video':
                await context.bot.send_video(
                    chat_id=channel[0],
                    video=post['content'],
                    caption=post.get('caption')
                )
            elif post['type'] == 'document':
                await context.bot.send_document(
                    chat_id=channel[0],
                    document=post['content'],
                    caption=post.get('caption')
                )
            else:  # texte
                await context.bot.send_message(
                    chat_id=channel[0],
                    text=post['content']
                )

            await update.message.reply_text("✅ Post envoyé avec succès!")

        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du post : {e}")
            await update.message.reply_text(f"❌ Erreur lors de l'envoi : {str(e)}")

    except Exception as e:
        logger.error(f"Erreur dans send_post_now : {e}")
        await update.message.reply_text("❌ Une erreur est survenue")

async def handle_post_content(update, context):
    """Gère la réception du contenu d'un post"""
    try:
        message = update.message

        # Initialiser la liste des posts si elle n'existe pas
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []

        # Vérifier la limite de 24 fichiers
        if len(context.user_data['posts']) >= 24:
            await message.reply_text(
                "⚠️ Vous avez atteint la limite de 24 fichiers pour ce post.\n"
                "Veuillez d'abord envoyer ce post avant d'en ajouter d'autres."
            )
            return WAITING_PUBLICATION_CONTENT

        # Créer le nouveau post
        post_data = {
            "type": None,
            "content": None,
            "caption": None,
            "reactions": [],
            "buttons": [],
            "channel": context.user_data.get('selected_channel', {}).get('username', config.DEFAULT_CHANNEL)
        }

        # Déterminer le type de contenu
        if message.photo:
            post_data.update({
                "type": "photo",
                "content": message.photo[-1].file_id,
                "caption": message.caption
            })
        elif message.video:
            post_data.update({
                "type": "video",
                "content": message.video.file_id,
                "caption": message.caption
            })
        elif message.document:
            post_data.update({
                "type": "document",
                "content": message.document.file_id,
                "caption": message.caption
            })
        elif message.text:
            post_data.update({
                "type": "text",
                "content": message.text
            })
        else:
            await message.reply_text("❌ Type de contenu non pris en charge.")
            return WAITING_PUBLICATION_CONTENT

        # Ajouter le post à la liste
        context.user_data['posts'].append(post_data)
        post_index = len(context.user_data['posts']) - 1
        context.user_data['current_post_index'] = post_index
        context.user_data['current_post'] = post_data

        # Afficher l'aperçu et les options
        keyboard = [
            [
                InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}"),
                InlineKeyboardButton("🗑️ Supprimer", callback_data=f"delete_post_{post_index}")
            ],
            [
                InlineKeyboardButton("💬 Réactions", callback_data=f"add_reactions_{post_index}"),
                InlineKeyboardButton("🔗 Bouton URL", callback_data=f"add_url_button_{post_index}")
            ],
            [
                InlineKeyboardButton("📤 Envoyer", callback_data="send_post"),
                InlineKeyboardButton("📅 Planifier", callback_data="schedule_send")
            ],
            [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
        ]

        # Message de confirmation avec prévisualisation
        await message.reply_text(
            f"✅ Post ajouté! Type: {post_data['type']}"
            + (f"\nCaption: {post_data['caption'][:100]}{'...' if post_data['caption'] and len(post_data['caption']) > 100 else ''}" if post_data['caption'] else "")
            + f"\nPour: @{post_data['channel']}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Afficher un aperçu du post
        if post_data['type'] == 'photo':
            await message.reply_photo(
                photo=post_data['content'],
                caption=post_data.get('caption'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif post_data['type'] == 'video':
            await message.reply_video(
                video=post_data['content'],
                caption=post_data.get('caption'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif post_data['type'] == 'document':
            await message.reply_document(
                document=post_data['content'],
                caption=post_data.get('caption'),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif post_data['type'] == 'text':
            await message.reply_text(
                f"📝 Aperçu: \n\n{post_data['content'][:500]}{'...' if len(post_data['content']) > 500 else ''}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur dans handle_post_content: {e}")
        await message.reply_text(
            "❌ Une erreur est survenue lors du traitement de votre contenu.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

# Classe de gestionnaire de base de données si elle n'existe pas
class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.setup_database()

    def setup_database(self):
        # Implémentation minimale pour éviter les erreurs
        pass

    def list_channels(self, user_id):
        # Retourne une liste vide pour éviter les erreurs
        return []

    def get_channel_by_username(self, username, user_id):
        # Implémentation minimale
        return None

# Classe de gestionnaire de planification si elle n'existe pas 
class SchedulerManager:
    def __init__(self, db_manager):
        self.scheduler = AsyncIOScheduler()
        self.db_manager = db_manager

    def start(self):
        self.scheduler.start()

    def stop(self):
        """Arrête le planificateur s'il est en cours d'exécution"""
        try:
            if self.scheduler.running:
                self.scheduler.shutdown()
                logger.info("Scheduler arrêté avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt du scheduler: {e}")

    # Méthodes minimales pour éviter les erreurs
    async def execute_scheduled_post(self, post_id):
        logger.info(f"Exécution du post planifié {post_id}")

# Fonction pour initialiser le client Telethon
async def start_telethon_client():
    """Initialise le client Telethon"""
    try:
        client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
        await client.start()
        logger.info("Client Telethon démarré avec succès")
        return client
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du client Telethon: {e}")
        return None

async def init_userbot():
    """Initialise le userbot au démarrage du bot"""
    global userbot
    userbot = await start_telethon_client() 