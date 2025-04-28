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

from config.settings import settings, setup_logging
from database.manager import DatabaseManager
from handlers.callback_handlers import handle_callback
from utils.message_utils import PostType, MessageError
from mon_bot_telegram.handlers.command_handlers import CommandHandlers
from mon_bot_telegram.handlers.message_handlers import MessageHandlers
from mon_bot_telegram.constants import CONVERSATION_STATES, BOT_TOKEN
from mon_bot_telegram.handlers.scheduled_tasks import ScheduledTasks

# États de la conversation
MAIN_MENU, CREATE_PUBLICATION, PLANIFIER_POST, WAITING_TIMEZONE = range(4)


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
                    MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL,
                                   message_handlers.handle_publication_content)
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
                CONVERSATION_STATES['WAITING_TIMEZONE']: [
                    MessageHandler(filters.TEXT, message_handlers.handle_timezone)
                ],
                CONVERSATION_STATES['BACKUP_MENU']: [
                    CallbackQueryHandler(handle_callback)
                ],
                CONVERSATION_STATES['WAITING_SCHEDULE_TEXT']: [
                    MessageHandler(filters.TEXT, message_handlers.handle_schedule_text)
                ],
                CONVERSATION_STATES['WAITING_SCHEDULE_MEDIA']: [
                    MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL,
                                   message_handlers.handle_schedule_media)
                ],
                CONVERSATION_STATES['WAITING_SCHEDULE_TIME']: [
                    MessageHandler(filters.TEXT, message_handlers.handle_schedule_time)
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