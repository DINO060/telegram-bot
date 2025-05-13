import asyncio
import logging
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler
)
from telegram import InlineKeyboardButton

from config.settings import settings, setup_logging
from database.manager import DatabaseManager
from handlers.callback_handlers import handle_callback
from utils.message_utils import PostType, MessageError
from mon_bot_telegram.handlers.command_handlers import CommandHandlers
from mon_bot_telegram.handlers.message_handlers import (
    handle_text,
    handle_media,
    handle_schedule_text,
    handle_schedule_media,
    handle_timezone,
)
from mon_bot_telegram.constants import CONVERSATION_STATES, BOT_TOKEN
from mon_bot_telegram.handlers.scheduled_tasks import ScheduledTasks
from mon_bot_telegram.reaction_functions import (
    add_reactions_to_post,
    handle_reaction_input,
    remove_reactions,
    add_url_button_to_post,
    handle_url_input,
    remove_url_buttons
)

# États de la conversation
MAIN_MENU, CREATE_PUBLICATION, PLANIFIER_POST, WAITING_TIMEZONE = range(4)

# 1. Définition des filtres personnalisés
class WaitingForUrlFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text:
            return False
        context = message.get_bot().application.user_data.get(message.from_user.id, {})
        return context.get('waiting_for_url', False)

class WaitingForReactionsFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text:
            return False
        context = message.get_bot().application.user_data.get(message.from_user.id, {})
        return context.get('waiting_for_reactions', False)

class ReplyKeyboardFilter(filters.MessageFilter):
    def filter(self, message):
        if not message.text:
            return False
        return message.text.lower() in ["envoyer", "aperçu", "annuler", "tout supprimer"]

waiting_for_url_filter = WaitingForUrlFilter()
waiting_for_reactions_filter = WaitingForReactionsFilter()
reply_keyboard_filter = ReplyKeyboardFilter()

# 1. Bouton du menu principal (dans la fonction start)
keyboard = [
    [InlineKeyboardButton("📝 Nouvelle publication", callback_data="create_publication")],
    [InlineKeyboardButton("📅 Publications planifiées", callback_data="planifier_post")],
    [InlineKeyboardButton("✏️ Modifier une publication", callback_data="edit_post")],
    [InlineKeyboardButton("📊 Statistiques", callback_data="channel_stats")],
    [InlineKeyboardButton("⚙️ Paramètres", callback_data="settings")]
]

# 2. Configuration du ConversationHandler
conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        MAIN_MENU: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_keyboard),
            CallbackQueryHandler(handle_callback),
        ],
        WAITING_CHANNEL_SELECTION: [
            CallbackQueryHandler(handle_callback),
        ],
        WAITING_PUBLICATION_CONTENT: [
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
            CallbackQueryHandler(handle_callback),
            MessageHandler(
                filters.PHOTO | filters.VIDEO | filters.Document.ALL | (
                        filters.TEXT & ~filters.COMMAND & ~reply_keyboard_filter),
                handle_post_content
            ),
        ],
        POST_ACTIONS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~reply_keyboard_filter, handle_post_actions_text),
            CallbackQueryHandler(handle_callback),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        SEND_OPTIONS: [
            CallbackQueryHandler(handle_callback),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        AUTO_DESTRUCTION: [
            CallbackQueryHandler(handle_auto_destruction),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        SCHEDULE_SEND: [
            CallbackQueryHandler(handle_schedule_time, pattern="^schedule_(today|tomorrow)$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_schedule_time),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        EDIT_POST: [
            CallbackQueryHandler(handle_callback),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        SCHEDULE_SELECT_CHANNEL: [
            CallbackQueryHandler(show_scheduled_post, pattern=r"^show_post_"),
            CallbackQueryHandler(handle_edit_time, pattern="^modifier_heure$"),
            CallbackQueryHandler(handle_send_now, pattern="^envoyer_maintenant$"),
            CallbackQueryHandler(handle_cancel_post, pattern="^annuler_publication$"),
            CallbackQueryHandler(planifier_post, pattern="^retour$"),
            CallbackQueryHandler(handle_confirm_cancel, pattern="^confirm_cancel$"),
            CallbackQueryHandler(handle_callback),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        STATS_SELECT_CHANNEL: [
            CallbackQueryHandler(show_scheduled_post, pattern=r"^show_post_"),
            CallbackQueryHandler(handle_callback),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        WAITING_CHANNEL_INFO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~reply_keyboard_filter, handle_channel_info),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        SETTINGS: [
            CallbackQueryHandler(handle_callback),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        WAITING_TIMEZONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND & ~reply_keyboard_filter, handle_timezone_input),
            CallbackQueryHandler(handle_callback),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        BACKUP_MENU: [
            CallbackQueryHandler(handle_callback),
            MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
        ],
        CONVERSATION_STATES['STATS_MENU']: [
            CallbackQueryHandler(handle_callback)
        ],
        # Nouveaux états pour les réactions et boutons URL
        CONVERSATION_STATES['WAITING_REACTION_INPUT']: [
            MessageHandler(filters.TEXT, handle_reaction_input),
            CallbackQueryHandler(handle_callback)
        ],
        CONVERSATION_STATES['WAITING_URL_INPUT']: [
            MessageHandler(filters.TEXT, handle_url_input),
            CallbackQueryHandler(handle_callback)
        ]
    },
    fallbacks=[
        CommandHandler("start", start),
        MessageHandler(reply_keyboard_filter, handle_reply_keyboard),
    ],
    per_message=False,
)

async def main():
    # Configuration du logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logger = logging.getLogger(__name__)

    try:
        # Initialisation de l'application
        application = Application.builder().token(BOT_TOKEN).build()

        # Initialisation de la base de données
        db_manager = DatabaseManager()
        application.bot_data['db_manager'] = db_manager

        # Initialisation des gestionnaires
        command_handlers = CommandHandlers()
        message_handlers = MessageHandlers()
        scheduled_tasks = ScheduledTasks()

        # Configuration du gestionnaire de conversation
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", command_handlers.start),
                CommandHandler("create", command_handlers.create),
                CommandHandler("schedule", command_handlers.schedule),
                CommandHandler("stats", command_handlers.stats),
                CommandHandler("settings", command_handlers.settings),
                CallbackQueryHandler(handle_callback)
            ],
            states={
                CONVERSATION_STATES['MAIN_MENU']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['WAITING_CHANNEL_SELECTION']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['WAITING_PUBLICATION_CONTENT']: [
                    MessageHandler(filters.TEXT, handle_text),
                    MessageHandler(filters.PHOTO | filters.VIDEO, handle_media),
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['WAITING_SCHEDULE_TEXT']: [
                    MessageHandler(filters.TEXT, handle_schedule_text)
                ],
                CONVERSATION_STATES['WAITING_SCHEDULE_MEDIA']: [
                    MessageHandler(filters.PHOTO | filters.VIDEO, handle_schedule_media)
                ],
                CONVERSATION_STATES['WAITING_TIMEZONE']: [
                    MessageHandler(filters.TEXT, handle_timezone)
                ],
                CONVERSATION_STATES['POST_ACTIONS']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['SEND_OPTIONS']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['AUTO_DESTRUCTION']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['SCHEDULE_SEND']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['EDIT_POST']: [
                    MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL,
                                   message_handlers.handle_edit_content)
                ],
                CONVERSATION_STATES['SCHEDULE_SELECT_CHANNEL']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['STATS_SELECT_CHANNEL']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['WAITING_CHANNEL_INFO']: [
                    MessageHandler(filters.TEXT, message_handlers.handle_channel_info)
                ],
                CONVERSATION_STATES['SETTINGS']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['BACKUP_MENU']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['WAITING_CONFIRMATION']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['WAITING_NEW_TIME']: [
                    MessageHandler(filters.TEXT, message_handlers.handle_new_time)
                ],
                CONVERSATION_STATES['SCHEDULED_POSTS_MENU']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['STATS_MENU']: [
                    CallbackQueryHandler(handle_callback)
                ],
                # Nouveaux états pour les réactions et boutons URL
                CONVERSATION_STATES['WAITING_REACTION_INPUT']: [
                    MessageHandler(filters.TEXT, handle_reaction_input),
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['WAITING_URL_INPUT']: [
                    MessageHandler(filters.TEXT, handle_url_input),
                    CallbackQueryHandler(handle_callback)
                ]
            },
            fallbacks=[
                CommandHandler("cancel", command_handlers.cancel),
                CommandHandler("help", command_handlers.help)
            ],
            per_message=False
        )

        # Ajout des gestionnaires à l'application
        application.add_handler(conv_handler)

        # Démarrage du bot
        logger.info("Démarrage du bot...")
        await application.initialize()
        await application.start()
        await application.run_polling()

    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot: {e}")
        raise


async def start(update, context):
    """Gère la commande /start"""
    user = update.effective_user
    welcome_message = (
        f"👋 Bonjour {user.first_name}!\n\n"
        "Je suis votre assistant de publication Telegram.\n"
        "Utilisez les commandes suivantes:\n"
        "/create - Créer une nouvelle publication\n"
        "/schedule - Planifier une publication\n"
        "/settings - Configurer le bot"
    )

    await update.message.reply_text(welcome_message)
    return MAIN_MENU


async def cancel(update, context):
    """Annule la conversation en cours"""
    await update.message.reply_text("❌ Opération annulée")
    return ConversationHandler.END


if __name__ == '__main__':
    asyncio.run(main())