import logging
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from utils.message_utils import send_message, PostType, MessageError
from database.manager import DatabaseManager
from utils.validators import Validator
from utils.error_handler import handle_error
from managers.database import db_manager
from utils.constants import MAIN_MENU, POST_CONTENT, SCHEDULE_SETUP, SETTINGS

logger = logging.getLogger('TelegramBot')


class CommandHandlers:
    """Gestionnaire des commandes du bot"""

    def __init__(
            self,
            db_manager: DatabaseManager,
            scheduled_tasks: 'ScheduledTasks'
    ):
        """
        Initialise le gestionnaire de commandes

        Args:
            db_manager: Gestionnaire de base de données
            scheduled_tasks: Gestionnaire de tâches planifiées
        """
        self.db_manager = db_manager
        self.scheduled_tasks = scheduled_tasks

        logger.info("Gestionnaire de commandes initialisé")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Gère la commande /start"""
        user = update.effective_user
        user_id = user.id

        # Message de bienvenue
        welcome_message = (
            f"👋 Bonjour {user.first_name} !\n\n"
            "Je suis votre assistant de gestion pour Telegram. Je vous aide à créer, "
            "planifier et publier du contenu sur vos canaux Telegram.\n\n"
            "Que souhaitez-vous faire aujourd'hui ?"
        )

        # Initialisation de la structure de données utilisateur si nécessaire
        if 'posts' not in context.user_data:
            context.user_data['posts'] = []
        if 'selected_channel' not in context.user_data:
            context.user_data['selected_channel'] = None

        # Création du clavier inline
        keyboard = [
            [InlineKeyboardButton("📝 Créer une publication", callback_data='create')],
            [InlineKeyboardButton("🕒 Planifier une publication", callback_data='schedule')],
            [InlineKeyboardButton("⚙️ Paramètres", callback_data='settings')],
            [InlineKeyboardButton("❓ Aide", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Envoyer le message avec le clavier
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)

        # Sauvegarder le fuseau horaire de l'utilisateur s'il n'est pas défini
        timezone = self.db_manager.get_user_timezone(user_id)
        if not timezone:
            self.db_manager.save_user_timezone(user_id, 'Europe/Paris')  # Fuseau par défaut

        logger.info(f"Utilisateur {user_id} a démarré le bot")

        return MAIN_MENU

    async def create_publication(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Gère la commande /create"""
        user_id = update.effective_user.id

        # Réinitialiser les données utilisateur pour cette session
        context.user_data['posts'] = []
        context.user_data['selected_channel'] = None

        # Récupérer les canaux de l'utilisateur
        channels = self.db_manager.list_channels(user_id)

        if not channels:
            await update.message.reply_text(
                "Vous n'avez pas encore configuré de canaux. "
                "Veuillez d'abord ajouter un canal dans les paramètres."
            )
            return ConversationHandler.END

        # Créer un clavier avec les canaux disponibles
        keyboard = []
        for channel in channels:
            button = [InlineKeyboardButton(
                f"@{channel['username']} - {channel['name']}",
                callback_data=f"channel_{channel['username']}"
            )]
            keyboard.append(button)

        # Ajouter un bouton d'annulation
        keyboard.append([InlineKeyboardButton("Annuler", callback_data="cancel")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Demander à l'utilisateur de sélectionner un canal
        await update.message.reply_text(
            "Veuillez sélectionner le canal sur lequel vous souhaitez publier:",
            reply_markup=reply_markup
        )

        logger.info(f"Utilisateur {user_id} a commencé la création d'une publication")

        return MAIN_MENU

    async def planifier_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Gère la commande /schedule"""
        user_id = update.effective_user.id

        # Message explicatif
        await update.message.reply_text(
            "La planification vous permet de programmer l'envoi automatique de vos publications.\n\n"
            "Commençons par créer votre publication, puis nous configurerons l'heure d'envoi."
        )

        # Réinitialiser les données utilisateur pour cette session
        context.user_data['posts'] = []
        context.user_data['selected_channel'] = None
        context.user_data['is_scheduled'] = True  # Marquer comme planifié

        # Récupérer les canaux de l'utilisateur
        channels = self.db_manager.list_channels(user_id)

        if not channels:
            await update.message.reply_text(
                "Vous n'avez pas encore configuré de canaux. "
                "Veuillez d'abord ajouter un canal dans les paramètres."
            )
            return ConversationHandler.END

        # Créer un clavier avec les canaux disponibles
        keyboard = []
        for channel in channels:
            button = [InlineKeyboardButton(
                f"@{channel['username']} - {channel['name']}",
                callback_data=f"channel_{channel['username']}"
            )]
            keyboard.append(button)

        # Ajouter un bouton d'annulation
        keyboard.append([InlineKeyboardButton("Annuler", callback_data="cancel")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        # Demander à l'utilisateur de sélectionner un canal
        await update.message.reply_text(
            "Veuillez sélectionner le canal sur lequel vous souhaitez planifier une publication:",
            reply_markup=reply_markup
        )

        logger.info(f"Utilisateur {user_id} a commencé la planification d'une publication")

        return SCHEDULE_SETUP

    async def settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Gère la commande /settings"""
        user_id = update.effective_user.id

        # Création du clavier inline pour les paramètres
        keyboard = [
            [InlineKeyboardButton("🌐 Gérer mes canaux", callback_data='manage_channels')],
            [InlineKeyboardButton("⏰ Fuseau horaire", callback_data='timezone')],
            [InlineKeyboardButton("🔄 Publications planifiées", callback_data='scheduled_posts')],
            [InlineKeyboardButton("🏠 Retour au menu principal", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Envoyer le message avec le clavier
        await update.message.reply_text(
            "⚙️ *Paramètres*\n\n"
            "Configurez vos préférences et gérez vos canaux Telegram ici.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

        logger.info(f"Utilisateur {user_id} a ouvert les paramètres")

        return SETTINGS

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Annule la conversation en cours"""
        user_id = update.effective_user.id

        # Réinitialiser les données utilisateur
        if 'posts' in context.user_data:
            context.user_data['posts'] = []
        if 'selected_channel' in context.user_data:
            context.user_data['selected_channel'] = None

        await update.message.reply_text(
            "🛑 Opération annulée. Que souhaitez-vous faire maintenant ?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Retour au menu principal", callback_data="main_menu")]
            ])
        )

        logger.info(f"Utilisateur {user_id} a annulé l'opération en cours")

        return MAIN_MENU

    async def list_publications(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Gère la commande /list

        Args:
            update: Mise à jour Telegram
            context: Contexte du bot
        """
        try:
            # Récupère les publications planifiées
            posts = self.db_manager.get_future_scheduled_posts()

            if not posts:
                await update.message.reply_text("Aucune publication planifiée.")
                return

            # Formatage de la liste
            message = "📋 Publications planifiées :\n\n"
            for post in posts:
                channel = self.db_manager.get_channel(post['channel_id'])
                message += (
                    f"📅 {post['scheduled_time']}\n"
                    f"📢 {channel['name']}\n"
                    f"📝 {post['caption'][:50]}...\n\n"
                )

            await update.message.reply_text(message)

        except Exception as e:
            await handle_error(update, context, e)

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Gère la commande /help

        Args:
            update: Mise à jour Telegram
            context: Contexte du bot
        """
        help_text = (
            "🤖 *Aide et Instructions*\n\n"
            "*Commandes principales:*\n"
            "/start - Démarre le bot et affiche le menu principal\n"
            "/create - Crée une nouvelle publication\n"
            "/schedule - Planifie une publication\n"
            "/settings - Configure vos préférences\n"
            "/help - Affiche ce message d'aide\n\n"

            "*Création de publications:*\n"
            "1. Sélectionnez un canal\n"
            "2. Envoyez les fichiers et/ou textes que vous souhaitez publier\n"
            "3. Utilisez les boutons du clavier pour prévisualiser, envoyer ou annuler\n\n"

            "*Planification:*\n"
            "1. Créez votre publication comme d'habitude\n"
            "2. Définissez la date et l'heure de publication\n"
            "3. Confirmez la planification\n\n"

            "*Gestion des canaux:*\n"
            "Dans les paramètres, vous pouvez ajouter de nouveaux canaux ou modifier les existants. "
            "Assurez-vous que le bot soit administrateur des canaux que vous souhaitez gérer.\n\n"

            "Pour toute question supplémentaire, contactez l'administrateur du bot."
        )

        await update.message.reply_text(help_text, parse_mode='Markdown')

        logger.info(f"Utilisateur {update.effective_user.id} a demandé l'aide")

        return None


# Fonction d'erreur générique pour les commandes
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gère les erreurs survenues pendant l'exécution des commandes"""
    logger.error(f"Une erreur s'est produite: {context.error}")

    # Envoyer un message d'erreur à l'utilisateur si possible
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "Une erreur s'est produite lors du traitement de votre demande. "
            "Veuillez réessayer ou contacter l'administrateur du bot."
        )

    # Journaliser les détails de l'erreur
    logger.error(f"Update {update} a causé l'erreur {context.error}", exc_info=True)