"""
Bot Telegram pour la gestion des publications avec réactions et boutons URL
"""

import os
# Configuration de l'encodage pour gérer correctement les emojis
os.environ['PYTHONIOENCODING'] = 'utf-8'

import re
import logging
import asyncio
import sqlite3
import io
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, List, Dict, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from dotenv import load_dotenv
import pytz
import time
import sys
import platform
from telethon import TelegramClient
import math
from PIL import Image
from media_callback_handler import handle_media_callback
# Import des fonctions de gestion des réactions (version corrigée)
# (Supprimer complètement l'import ci-dessous, il est incorrect)
# from mon_bot_telegram.reaction_functions import (
#     add_reactions_to_post,
#     remove_reactions,
#     add_url_button_to_post,
#     remove_url_buttons,
#     handle_reaction_input,
#     handle_url_input,
#     handle_reaction_click,
#     handle_post_content
# )
from mon_bot_telegram.conversation_states import (
    MAIN_MENU, POST_CONTENT, POST_ACTIONS, SEND_OPTIONS, AUTO_DESTRUCTION,
    SCHEDULE_SEND, EDIT_POST, SCHEDULE_SELECT_CHANNEL, STATS_SELECT_CHANNEL,
    WAITING_CHANNEL_INFO, SETTINGS, BACKUP_MENU, WAITING_CHANNEL_SELECTION,
    WAITING_PUBLICATION_CONTENT, WAITING_TIMEZONE, WAITING_THUMBNAIL,
    WAITING_REACTION_INPUT, WAITING_URL_INPUT, WAITING_RENAME_INPUT,
    WAITING_SCHEDULE_TIME, WAITING_EDIT_TIME, WAITING_CUSTOM_USERNAME
)
from mon_bot_telegram.config import settings
from mon_bot_telegram.database.manager import DatabaseManager
from mon_bot_telegram.handlers.reaction_functions import (
    handle_reaction_input,
    handle_url_input,
    remove_reactions,
    remove_url_buttons,
)
from mon_bot_telegram.handlers.schedule_handler import (
    SchedulerManager,
    planifier_post,
    handle_schedule_in_reply_keyboard
)
from mon_bot_telegram.handlers.thumbnail_handler import (
    handle_thumbnail_functions,
    handle_add_thumbnail_to_post,
    handle_set_thumbnail_and_rename,
    handle_view_thumbnail,
    handle_delete_thumbnail,
    handle_thumbnail_input,
    handle_add_thumbnail,
    handle_rename_input
)
from pyrogram import Client

load_dotenv()

REPLY_KEYBOARD_BUTTONS = ["Tout supprimer", "Aperçu", "Annuler", "Envoyer"]
reply_keyboard_filter = filters.TEXT & filters.Regex(f"^({'|'.join(REPLY_KEYBOARD_BUTTONS)})$")


# -----------------------------------------------------------------------------
# CONFIGURATION SÉCURISÉE
# -----------------------------------------------------------------------------
class Config:
    def __init__(self):
        # Chargement depuis variables d'environnement
        self.API_ID = os.getenv('API_ID')
        self.API_HASH = os.getenv('API_HASH')
        self.BOT_TOKEN = os.getenv('BOT_TOKEN')
        self.ADMIN_IDS = self._parse_admin_ids(os.getenv('ADMIN_IDS', '[]'))

        # Paramètres par défaut
        self.DOWNLOAD_FOLDER = os.getenv('DOWNLOAD_FOLDER', 'downloads/')
        self.SESSION_NAME = os.getenv('SESSION_NAME', 'uploader_session')
        self.DB_PATH = os.getenv('DB_PATH', 'bot.db')

        # Limites
        self.BOT_MAX_MEDIA_SIZE = 50 * 1024 * 1024  # 50 Mo (limite des bots Telegram)
        self.USERBOT_MAX_MEDIA_SIZE = 2 * 1024 * 1024 * 1024  # 2 Go (limite d'utilisateur Telegram)

        # Défaut
        self.DEFAULT_CHANNEL = os.getenv('DEFAULT_CHANNEL', 'https://t.me/sheweeb')

        # Validation et préparation
        self._validate_config()
        self._prepare_directories()

    def _parse_admin_ids(self, admin_ids_str):
        try:
            return [int(id.strip()) for id in admin_ids_str.strip('[]').split(',') if id.strip()]
        except ValueError:
            logging.warning("Format incorrect pour ADMIN_IDS. Utilisation d'une liste vide.")
            return []

    def _validate_config(self):
        if not all([self.API_ID, self.API_HASH, self.BOT_TOKEN]):
            raise ValueError("Configuration incomplète : API_ID, API_HASH et BOT_TOKEN sont requis")

    def _prepare_directories(self):
        os.makedirs(self.DOWNLOAD_FOLDER, exist_ok=True)


class RateLimiter:
    def __init__(self):
        self.user_timestamps = {}

    async def can_send_message(self, chat_id, user_id, limit=1, per_seconds=1):
        now = time.time()
        key = (chat_id, user_id)
        timestamps = self.user_timestamps.get(key, [])
        # On ne garde que les timestamps récents
        timestamps = [t for t in timestamps if now - t < per_seconds]
        if len(timestamps) < limit:
            timestamps.append(now)
            self.user_timestamps[key] = timestamps
            return True
        return False


rate_limiter = RateLimiter()


# -----------------------------------------------------------------------------
# CONFIGURATION DU LOGGING
# -----------------------------------------------------------------------------
def setup_logging():
    """Configure le système de logging"""
    # Créer le dossier logs s'il n'existe pas
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Configuration du logger principal
    logger = logging.getLogger('UploaderBot')
    logger.setLevel(logging.INFO)

    # Handler pour la console avec encodage UTF-8
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    console_handler.stream.reconfigure(encoding='utf-8')  # Configuration de l'encodage UTF-8
    logger.addHandler(console_handler)

    # Handler pour le fichier avec encodage UTF-8
    file_handler = logging.FileHandler('logs/bot.log', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# Configuration globale
logger = setup_logging()
config = Config()

# Fonction utilitaire pour normaliser les noms de canaux
def normalize_channel_username(channel_username):
    """
    Normalise le nom d'utilisateur d'un canal en enlevant le @ s'il est présent
    Retourne None si l'entrée est vide ou None
    """
    if not channel_username:
        return None
    return channel_username.lstrip('@') if isinstance(channel_username, str) else None

def debug_thumbnail_search(user_id, channel_username, db_manager):
    """Fonction de debug pour diagnostiquer les problèmes de recherche de thumbnails"""
    logger.info(f"=== DEBUG THUMBNAIL SEARCH ===")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Channel Username Original: '{channel_username}'")
    
    # Normalisation
    clean_username = normalize_channel_username(channel_username)
    logger.info(f"Channel Username Normalisé: '{clean_username}'")
    
    # Tester différentes variantes
    test_variants = [
        channel_username,
        clean_username,
        f"@{clean_username}" if clean_username and not clean_username.startswith('@') else clean_username,
        clean_username.lstrip('@') if clean_username else None
    ]
    
    logger.info(f"Variants à tester: {test_variants}")
    
    # Tester chaque variant
    for variant in test_variants:
        if variant:
            result = db_manager.get_thumbnail(variant, user_id)
            logger.info(f"Test variant '{variant}': {result}")
    
    # Vérifier directement dans la base de données
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT channel_username, thumbnail_file_id FROM channel_thumbnails WHERE user_id = ?", (user_id,))
        all_thumbnails = cursor.fetchall()
        logger.info(f"TOUS les thumbnails pour user {user_id}: {all_thumbnails}")
        conn.close()
    except Exception as e:
        logger.error(f"Erreur lors de la vérification DB: {e}")
    
    logger.info(f"=== FIN DEBUG ===")

def ensure_thumbnail_table_exists():
    """S'assure que la table channel_thumbnails existe"""
    try:
        import sqlite3
        conn = sqlite3.connect(config.DB_PATH)
        cursor = conn.cursor()
        
        # Vérifier si la table existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_thumbnails'")
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            logger.info("Création de la table channel_thumbnails manquante...")
            cursor.execute('''
                CREATE TABLE channel_thumbnails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_username TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    thumbnail_file_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_username, user_id)
                )
            ''')
            conn.commit()
            logger.info("✅ Table channel_thumbnails créée avec succès!")
        else:
            logger.info("✅ Table channel_thumbnails existe déjà")
        
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ Erreur lors de la création de la table channel_thumbnails: {e}")
        return False

# Initialisation de la base de données
db_manager = DatabaseManager()
db_manager.setup_database()

# Vérifier et créer la table channel_thumbnails si nécessaire
def ensure_channel_thumbnails_table():
    """S'assure que la table channel_thumbnails existe dans la base de données"""
    try:
        cursor = db_manager.connection.cursor()
        
        # Vérifier si la table existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_thumbnails'")
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            logger.info("⚠️ Table channel_thumbnails manquante - création en cours...")
            cursor.execute('''
                CREATE TABLE channel_thumbnails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_username TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    thumbnail_file_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_username, user_id)
                )
            ''')
            db_manager.connection.commit()
            logger.info("✅ Table channel_thumbnails créée avec succès!")
        else:
            logger.info("✅ Table channel_thumbnails existe déjà")
        
        return True
    except Exception as e:
        logger.error(f"❌ Erreur lors de la vérification de la table channel_thumbnails: {e}")
        return False

# Exécuter la vérification
ensure_channel_thumbnails_table()

logger.info(f"Base de données initialisée avec succès")


# -----------------------------------------------------------------------------
# DECORATEURS ET UTILITAIRES
# -----------------------------------------------------------------------------
def admin_only(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in config.ADMIN_IDS:
            await update.message.reply_text("❌ Vous n'avez pas les permissions nécessaires.")
            return
        return await func(update, context, *args, **kwargs)

    return wrapped


async def retry_operation(operation, max_retries=3, delay=1):
    for attempt in range(max_retries):
        try:
            return await operation()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Tentative {attempt + 1} échouée: {e}")
            await asyncio.sleep(delay * (attempt + 1))


# -----------------------------------------------------------------------------
# DÉFINITION DES ÉTATS DE LA CONVERSATION
# -----------------------------------------------------------------------------
# Stockage des réactions
reaction_counts = {}

# Variable globale pour le userbot
userbot = None

# Ensemble pour stocker les callbacks déjà traités
processed_callbacks = set()

# Filtres personnalisés
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

# Instances des filtres
waiting_for_url_filter = WaitingForUrlFilter()
waiting_for_reactions_filter = WaitingForReactionsFilter()
reply_keyboard_filter = ReplyKeyboardFilter()




# SchedulerManager maintenant importé de schedule_handler


# Initialisation du gestionnaire de planification
scheduler_manager = SchedulerManager(db_manager)


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
    return userbot


def log_conversation_state(update, context, function_name, state_return):
    """Enregistre les informations d'état de conversation pour débogage"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    logger.info(f"[ÉTAT] Fonction: {function_name}, Utilisateur: {user_id}, Chat: {chat_id}")
    logger.info(f"[ÉTAT] État de retour: {state_return}")
    logger.info(f"[ÉTAT] État stocké: {context.user_data.get('conversation_state', 'Non défini')}")

    # Détecter les incohérences potentielles
    if 'conversation_state' in context.user_data and state_return != context.user_data['conversation_state']:
        logger.warning(
            f"[ÉTAT] Incohérence détectée! Retour: {state_return}, Stocké: {context.user_data['conversation_state']}")

    # Mettre à jour l'état stocké
    context.user_data['conversation_state'] = state_return

    return state_return


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


async def create_publication(update, context):
    """Affiche la liste des canaux disponibles pour créer une publication"""
    try:
        # Vérification pour éviter les modifications redondantes
        if update.callback_query and hasattr(update.callback_query, '_answered') and update.callback_query._answered:
            return WAITING_CHANNEL_SELECTION

        user_id = update.effective_user.id  # Récupération de l'ID utilisateur
        logger.info(f"create_publication appelé par l'utilisateur {user_id}")

        # Récupération des canaux depuis la base de données avec gestion d'erreur
        try:
            channels = db_manager.list_channels(user_id)
            logger.info(f"Canaux trouvés pour l'utilisateur {user_id}: {channels}")
        except Exception as e:
            logger.error(f"Exception lors de la récupération des canaux: {e}")
            channels = []  # Définir une liste vide en cas d'erreur

        # Si aucun canal n'est configuré, proposer d'en ajouter un ou d'utiliser le canal par défaut
        if not channels:
            keyboard = [
                [InlineKeyboardButton("➕ Ajouter un canal", callback_data="add_channel")],
                [InlineKeyboardButton("🔄 Utiliser le canal par défaut", callback_data="use_default_channel")],
                [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
            ]

            message_text = (
                "⚠️ Aucun canal configuré\n\n"
                "Pour publier du contenu, vous devez d'abord configurer un canal Telegram.\n"
                "Vous pouvez soit :\n"
                "• Ajouter un canal existant dont vous êtes administrateur\n"
                "• Utiliser le canal par défaut (temporaire)"
            )

            try:
                if update.callback_query:
                    await update.callback_query.edit_message_text(
                        message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    await update.message.reply_text(
                        message_text,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            except Exception as msg_error:
                logger.error(f"Erreur lors de l'envoi du message 'aucun canal': {msg_error}")
                # Si on ne peut même pas envoyer ce message, essayer un message plus simple
                try:
                    if update.callback_query:
                        await update.callback_query.answer("Aucun canal configuré. Utilisez le menu.")
                    else:
                        await update.message.reply_text(
                            "Aucun canal configuré. Ajoutez-en un ou utilisez le canal par défaut.")
                except:
                    pass

            return WAITING_CHANNEL_SELECTION

        # Construction du clavier avec 2 canaux par ligne
        keyboard = []
        current_row = []

        for i, channel in enumerate(channels):
            # Ajoute un bouton pour chaque canal avec callback data contenant l'username
            current_row.append(InlineKeyboardButton(
                channel['name'],
                callback_data=f"select_channel_{channel['username']}"
            ))

            # Crée une nouvelle ligne tous les 2 boutons
            if len(current_row) == 2 or i == len(channels) - 1:
                keyboard.append(current_row)
                current_row = []

        # Ajout des boutons d'action
        keyboard.append([
            InlineKeyboardButton("➕ Ajouter un canal", callback_data="add_channel")
        ])
        keyboard.append([
            InlineKeyboardButton("️↩️ Menu principal", callback_data="main_menu")
        ])

        message_text = (
            "📝 Sélectionnez un canal pour votre publication :\n\n"
            "• Choisissez un canal existant, ou\n"
            "• Ajoutez un nouveau canal"
        )

        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    message_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        except Exception as msg_error:
            logger.error(f"Erreur lors de l'affichage du sélecteur de canal: {msg_error}")
            # Tenter une approche plus simple en cas d'erreur
            try:
                if update.callback_query:
                    await update.callback_query.answer("Erreur d'affichage. Essayez /start")
                else:
                    await update.message.reply_text("Erreur d'affichage. Utilisez /start pour recommencer.")
            except:
                pass

        return WAITING_CHANNEL_SELECTION

    except Exception as e:
        logger.error(f"Erreur lors de l'affichage des canaux: {e}")
        logger.exception("Traceback complet:")

        # Message d'erreur avec bouton de retour
        keyboard = [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]
        error_message = "❌ Une erreur est survenue lors de la récupération des canaux."

        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    error_message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    error_message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        except Exception as msg_error:
            logger.error(f"Erreur lors de l'envoi du message d'erreur: {msg_error}")
            # Tenter un dernier message simple
            try:
                if update.callback_query:
                    await update.callback_query.answer("Erreur technique. Réessayez plus tard.")
                else:
                    await update.message.reply_text("Erreur technique. Réessayez plus tard.")
            except:
                pass

        return MAIN_MENU


# planifier_post maintenant importé de schedule_handler


async def send_post_now(update, context, scheduled_post=None):
    # Initialiser les variables pour éviter les erreurs de référence
    file_size = 0
    file_size_mb = 0.0
    limit_bytes = 50 * 1024 * 1024  # 50 Mo en bytes
    
    try:
        if scheduled_post:
            posts = [scheduled_post]
            channel = scheduled_post.get('channel', config.DEFAULT_CHANNEL)
        else:
            posts = context.user_data.get("posts", [])
            if not posts:
                if update.message:
                    await update.message.reply_text("❌ Il n'y a pas de fichiers à envoyer.")
                elif hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.message.reply_text("❌ Il n'y a pas de fichiers à envoyer.")
                return MAIN_MENU
            channel = posts[0].get("channel", config.DEFAULT_CHANNEL)

        # Correction : ajouter @ si besoin pour les canaux publics
        if isinstance(channel, str) and not channel.startswith('@') and not channel.startswith('-100'):
            channel = '@' + channel

        for post_index, post in enumerate(posts):
            post_type = post.get("type")
            content = post.get("content")
            caption = post.get("caption") or ""
            filename = post.get("filename")
            # Ajout du texte custom si défini pour ce canal
            custom_usernames = context.user_data.get('custom_usernames', {})
            channel_username = post.get("channel")
            custom_text = custom_usernames.get(channel_username)
            if custom_text:
                if caption:
                    caption = f"{caption}\n{custom_text}"
                else:
                    caption = custom_text

            # --- Construction du clavier (réactions + boutons URL) ---
            keyboard = []
            # Réactions (max 4 par ligne)
            reactions = post.get("reactions", [])
            if reactions:
                current_row = []
                for reaction in reactions:
                    current_row.append(InlineKeyboardButton(f"{reaction}", callback_data=f"react_{post_index}_{reaction}"))
                    if len(current_row) == 4:
                        keyboard.append(current_row)
                        current_row = []
                if current_row:
                    keyboard.append(current_row)
            # Boutons URL
            buttons = post.get("buttons", [])
            for btn in buttons:
                keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

            # Préparer le thumbnail si disponible
            thumbnail = post.get('thumbnail')

            # --- Envoi du fichier selon son type ---
            if post_type == "photo":
                await context.bot.send_photo(
                    chat_id=channel,
                    photo=content,
                    caption=caption if caption else None,
                    reply_markup=reply_markup
                )
            elif post_type == "video" or post_type == "document":
                # Vérifier d'abord la taille du fichier pour décider de la méthode d'envoi
                try:
                    file_obj = await context.bot.get_file(content)
                    file_size = file_obj.file_size
                    file_size_mb = file_size / (1024 * 1024)
                    logger.info(f"DEBUG: Taille du fichier {post_type}: {file_size} bytes ({file_size_mb:.1f} Mo)")
                    
                    # Si le fichier est <= 50 Mo, utiliser le bot normal
                    if file_size <= limit_bytes:
                        logger.info(f"DEBUG ENVOI: Type={post_type}, utilisation du bot normal (fichier <= 50 Mo)")
                        
                        if post_type == "video":
                            kwargs = {
                                'chat_id': channel,
                                'video': content,
                                'caption': caption if caption else None,
                                'reply_markup': reply_markup
                            }
                            if thumbnail:
                                kwargs['thumbnail'] = thumbnail
                            await context.bot.send_video(**kwargs)
                        else:  # document
                            kwargs = {
                                'chat_id': channel,
                                'document': content,
                                'caption': caption if caption else None,
                                'reply_markup': reply_markup
                            }
                            if thumbnail:
                                kwargs['thumbnail'] = thumbnail
                            await context.bot.send_document(**kwargs)
                    
                    else:
                        # Fichier > 50 Mo, utiliser le userbot
                        logger.info(f"DEBUG ENVOI: Type={post_type}, utilisation du userbot (fichier > 50 Mo)")
                        
                        # Récupérer le userbot depuis bot_data
                        userbot = context.application.bot_data.get('userbot')
                        if not userbot:
                            logger.error("DEBUG: Userbot non initialisé dans bot_data!")
                            await context.bot.send_message(
                                chat_id=channel,
                                text="❌ Userbot non initialisé. Impossible d'envoyer le fichier volumineux."
                            )
                            return MAIN_MENU
                        
                        # Télécharger le fichier
                        file_path = await file_obj.download_to_drive()
                        logger.info(f"DEBUG: Téléchargement vers {file_path}")
                        
                        # Envoyer via userbot
                        logger.info(f"DEBUG: Envoi via userbot vers {channel}")
                        try:
                            if post_type == "video":
                                await userbot.send_file(channel, file_path, caption=caption)
                            else:  # document
                                await userbot.send_file(channel, file_path, caption=caption)
                            
                            logger.info("DEBUG: Envoi userbot réussi")
                        finally:
                            # Nettoyer le fichier temporaire
                            try:
                                os.remove(file_path)
                                logger.info(f"DEBUG: Fichier temporaire supprimé: {file_path}")
                            except Exception as cleanup_error:
                                logger.warning(f"Impossible de supprimer le fichier temporaire: {cleanup_error}")
                                
                except Exception as file_error:
                    if "File is too big" in str(file_error):
                        logger.info(f"Fichier trop volumineux pour get_file() (>20 Mo), tentative avec bot normal")
                    else:
                        logger.error(f"Erreur lors de la récupération du fichier: {file_error}")
                    # Si on ne peut pas récupérer la taille, essayer d'abord avec le bot
                    try:
                        logger.info(f"DEBUG ENVOI: Type={post_type}, tentative avec bot normal (taille inconnue)")
                        if post_type == "video":
                            kwargs = {
                                'chat_id': channel,
                                'video': content,
                                'caption': caption if caption else None,
                                'reply_markup': reply_markup
                            }
                            if thumbnail:
                                kwargs['thumbnail'] = thumbnail
                            await context.bot.send_video(**kwargs)
                        else:  # document
                            kwargs = {
                                'chat_id': channel,
                                'document': content,
                                'caption': caption if caption else None,
                                'reply_markup': reply_markup
                            }
                            if thumbnail:
                                kwargs['thumbnail'] = thumbnail
                            await context.bot.send_document(**kwargs)
                    except Exception as bot_error:
                        if "File is too big" in str(bot_error) or "too large" in str(bot_error).lower():
                            logger.info("DEBUG: Fichier trop volumineux pour le bot, basculement vers userbot")
                            # Basculer vers userbot si le fichier est trop gros
                            userbot = context.application.bot_data.get('userbot')
                            if not userbot:
                                raise Exception("Userbot non initialisé et fichier trop volumineux pour le bot")
                            
                            # Re-télécharger et envoyer via userbot
                            file_obj = await context.bot.get_file(content)
                            file_path = await file_obj.download_to_drive()
                            try:
                                if post_type == "video":
                                    await userbot.send_file(channel, file_path, caption=caption)
                                else:
                                    await userbot.send_file(channel, file_path, caption=caption)
                            finally:
                                try:
                                    os.remove(file_path)
                                except:
                                    pass
                        else:
                            raise bot_error
            elif post_type == "text":
                await context.bot.send_message(
                    chat_id=channel,
                    text=caption or content,
                    reply_markup=reply_markup
                )
        # Nettoyage du contexte
        if not scheduled_post:
            context.user_data.pop("posts", None)
            context.user_data.pop("preview_messages", None)
            context.user_data.pop("current_scheduled_post", None)
        if update.message:
            await update.message.reply_text(
                "✅ Post envoyé avec succès !",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
            )
        elif hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.message.reply_text(
                "✅ Post envoyé avec succès !",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
            )
        return MAIN_MENU
    except Exception as e:
        logger.error(f"Erreur dans send_post_now: {e}")
        logger.error(f"DEBUG ERREUR: Type={type(e).__name__}, Message='{str(e)}'")
        logger.error(f"DEBUG ERREUR: Taille fichier={file_size} bytes, Limite={limit_bytes} bytes")
        logger.error(f"DEBUG ERREUR: Utilisation userbot={file_size > limit_bytes if file_size > 0 else 'Inconnu'}")
        
        # Messages d'erreur spécifiques
        error_msg = "❌ Une erreur est survenue lors de l'envoi du post."
        if "File is too big" in str(e):
            if file_size > limit_bytes:
                error_msg += f"\n📁 Fichier trop volumineux: {file_size_mb:.1f} Mo (limite userbot: 2000 Mo)"
            else:
                error_msg += f"\n📁 Fichier trop volumineux: {file_size_mb:.1f} Mo (limite bot: 50 Mo)"
        elif "TimeoutError" in str(e) or "timeout" in str(e).lower():
            error_msg += "\n⏱️ Timeout de connexion. Réessayez dans quelques minutes."
        else:
            error_msg += f"\n🔧 Détails: {str(e)}"
        
        error_msg += "\n\nVeuillez réessayer."
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=error_msg
        )


async def handle_send_now(update, context):
    """Gère la demande d'envoi immédiat d'un post"""
    await send_post_now(update, context)
    return ConversationHandler.END


# -----------------------------------------------------------------------------
# GESTIONNAIRE DE CALLBACKS
# -----------------------------------------------------------------------------
async def handle_callback(update, context):
    """Gère les callbacks des boutons inline."""
    try:
        # Cas 1: Callback query - Sélection d'un canal
        if update.callback_query:
            query = update.callback_query
            await query.answer()
        
        if query.data == "settings":
            return await settings(update, context)
        elif query.data == "custom_settings":
            return await handle_custom_settings(update, context)
        elif query.data == "create_publication":
            return await create_publication(update, context)
        elif query.data == "planifier_post":
            return await planifier_post(update, context)
        elif query.data == "main_menu":
            return await start(update, context)
        elif query.data == "channels":
            return await channels(update, context)
        elif query.data == "timezone":
            return await handle_timezone(update, context)
        elif query.data == "scheduled_posts":
            return await scheduled_posts(update, context)
        elif query.data == "delete_scheduled_post":
            return await handle_delete_scheduled_post(update, context)
        elif query.data.startswith("confirm_delete_post_"):
            return await handle_confirm_delete_post(update, context)
        elif query.data.startswith("schedule_"):
            return await handle_schedule_time(update, context)
        elif query.data.startswith("edit_time_"):
            return await handle_edit_time(update, context)
        elif query.data.startswith("cancel_post_"):
            return await handle_cancel_post(update, context)
        elif query.data.startswith("select_channel_"):
            return await handle_channel_selection(update, context)
        elif query.data.startswith("edit_file_"):
            post_index = int(query.data.split('_')[-1])
            context.user_data['current_post_index'] = post_index
            
            # Récupérer le post à modifier
            if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
                await query.message.reply_text(
                    "❌ Post introuvable.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                )
                return MAIN_MENU
                
            post = context.user_data['posts'][post_index]
            
            # Créer le sous-menu avec les options selon le type de fichier
            keyboard = []
            
            # Pour les fichiers média (photo, video, document), afficher les options thumbnail
            if post['type'] in ['photo', 'video', 'document']:
                keyboard.extend([
                    [InlineKeyboardButton("📎 Upload Thumbnail", callback_data=f"upload_thumbnail_{post_index}")],
                    [InlineKeyboardButton("🖼️✏️ Set Thumbnail + Rename", callback_data=f"set_thumbnail_rename_{post_index}")],
                    [InlineKeyboardButton("✏️ Rename", callback_data=f"rename_post_{post_index}")],
                ])
            else:  # Pour les textes, seulement rename
                keyboard.append([InlineKeyboardButton("✏️ Rename", callback_data=f"rename_post_{post_index}")])
            
            # Option de retour (SANS le bouton Supprimer car il est déjà disponible)
            keyboard.append([InlineKeyboardButton("↩️ Retour", callback_data="main_menu")])
            
            # Répondre au callback et envoyer un nouveau message
            await query.answer("Options de modification...")
            
            file_type_text = {
                'photo': 'photo',
                'video': 'vidéo', 
                'document': 'document',
                'text': 'texte'
            }.get(post['type'], 'fichier')
            
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✏️ Édition du {file_type_text}\n\nChoisissez une option de modification :",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return WAITING_PUBLICATION_CONTENT
        elif query.data.startswith("add_thumbnail_"):
            post_index = int(query.data.split('_')[-1])
            # Vérifier si une miniature existe déjà pour ce post
            post = context.user_data['posts'][post_index]
            if post.get('thumbnail'):
                await query.message.reply_text(
                    "❌ Ce fichier a déjà une miniature. Supprimez-la d'abord avant d'en ajouter une autre.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
                )
                return WAITING_PUBLICATION_CONTENT
            # Chercher la miniature enregistrée pour le canal
            channel_username = post.get('channel')
            user_id = update.effective_user.id
            clean_username = channel_username.lstrip('@') if channel_username else None
            thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
            if not thumbnail_file_id:
                await query.message.reply_text(
                    "❌ Aucune miniature enregistrée pour ce canal. Utilisez le menu custom du canal pour en ajouter une.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
                )
                return WAITING_PUBLICATION_CONTENT
            # Ajouter la miniature au post
            post['thumbnail'] = thumbnail_file_id
            # Envoyer l'aperçu à jour
            await send_preview_file(update, context, post_index)
            await query.message.reply_text(
                "✅ Miniature du canal ajoutée à ce fichier !",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
            )
            return WAITING_PUBLICATION_CONTENT
        elif query.data.startswith("add_thumbnail_rename_"):
            post_index = int(query.data.split('_')[-1])
            context.user_data['waiting_for_thumbnail'] = True
            context.user_data['waiting_for_rename'] = True
            context.user_data['thumbnail_rename_mode'] = True
            context.user_data['current_post_index'] = post_index
            await query.message.reply_text(
                "Envoie-moi la miniature (image) pour ce fichier :",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="main_menu")]])
            )
            return WAITING_THUMBNAIL
        # Nouveaux callbacks pour les réactions
        elif query.data.startswith("add_reactions_"):
            post_index = int(query.data.split('_')[-1])
            context.user_data['waiting_for_reactions'] = True
            context.user_data['current_post_index'] = post_index
            try:
                await query.edit_message_text(
                    "Entrez les réactions séparées par des / (ex: 👍/❤️/🔥)\nMaximum 8 réactions.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="main_menu")]])
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    await query.message.reply_text(
                        "Entrez les réactions séparées par des / (ex: 👍/❤️/🔥)\nMaximum 8 réactions.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="main_menu")]])
                    )
            return WAITING_REACTION_INPUT
        elif query.data.startswith("remove_reactions_"):
            return await remove_reactions(update, context)
        # Nouveaux callbacks pour les boutons URL
        elif query.data.startswith("add_url_button_"):
            post_index = int(query.data.split('_')[-1])
            context.user_data['waiting_for_url'] = True
            context.user_data['current_post_index'] = post_index
            try:
                await query.edit_message_text(
                    "Entrez le texte et l'URL du bouton au format :\nTexte du bouton | URL\nExemple : Visiter le site | https://example.com",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="main_menu")]])
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    await query.message.reply_text(
                        "Entrez le texte et l'URL du bouton au format :\nTexte du bouton | URL\nExemple : Visiter le site | https://example.com",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="main_menu")]])
                    )
            return WAITING_URL_INPUT
        elif query.data.startswith("remove_url_buttons_"):
            return await remove_url_buttons(update, context)
        # Nouveau callback pour la suppression
        elif query.data.startswith("delete_post_"):
            post_index = int(query.data.split('_')[-1])
            if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
                context.user_data['posts'].pop(post_index)
            try:
                await query.edit_message_text(
                    "✅ Post supprimé avec succès !",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    await query.message.reply_text(
                        "✅ Post supprimé avec succès !",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                    )
            return MAIN_MENU
        # Nouveau callback pour le renommage
        elif query.data.startswith("rename_post_"):
            post_index = int(query.data.split('_')[-1])
            context.user_data['waiting_for_rename'] = True
            context.user_data['current_post_index'] = post_index
            
            # Répondre au callback et envoyer un nouveau message
            await query.answer("Préparation du renommage...")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="✏️ Renommer le fichier\n\nEnvoie-moi le nouveau nom pour ce fichier (avec l'extension).\nPar exemple: mon_document.pdf",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Annuler", callback_data="main_menu")]])
            )
            return WAITING_RENAME_INPUT
        elif query.data == "cancel_schedule":
            try:
                await query.edit_message_text(
                    "❌ Planification annulée.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    await query.message.reply_text(
                        "❌ Planification annulée.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
                    )
            return MAIN_MENU
        elif query.data == "add_channel":
            try:
                await query.edit_message_text(
                    "Veuillez entrer le nom du canal et son @username au format :\nNom du canal | @username",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="main_menu")]])
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="Veuillez entrer le nom du canal et son @username au format :\nNom du canal | @username",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="main_menu")]])
                )
            return WAITING_CHANNEL_INFO
        elif query.data == "send_now":
            await send_post_now(update, context)
            return ConversationHandler.END
        elif query.data.startswith("custom_channel_"):
            return await handle_custom_channel(update, context)
        elif query.data == "add_username":
            channel_username = context.user_data.get('custom_channel')
            custom_usernames = context.user_data.get('custom_usernames', {})
            if channel_username and custom_usernames.get(channel_username):
                await query.edit_message_text(
                    "❌ Un texte/username est déjà enregistré pour ce canal. Supprimez-le d'abord avant d'en ajouter un autre.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="settings")]])
                )
                return SETTINGS
            await query.edit_message_text(
                "Veuillez envoyer le texte ou username à ajouter (entre crochets, ex: [@MONUSERNAME] ou [🔥 Ma chaîne]) :",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="settings")]])
            )
            return WAITING_CUSTOM_USERNAME
        elif query.data == "manage_channels":
            return await manage_channels(update, context)
        elif query.data == "add_thumbnail":
            # Rediriger vers le bon handler dans thumbnail_handler.py
            return await handle_add_thumbnail(update, context)
        elif query.data.startswith("select_thumb_channel_"):
            return await handle_select_thumb_channel(update, context)
        elif query.data.startswith("select_username_channel_"):
            return await handle_select_username_channel(update, context)
        elif query.data.startswith("custom_select_channel_"):
            return await handle_custom_select_channel(update, context)

        # ---------- GESTION DES THUMBNAILS ----------
        elif query.data == "thumbnail_menu":
            return await handle_thumbnail_functions(update, context)

        elif query.data == "view_thumbnail":
            return await handle_view_thumbnail(update, context)

        elif query.data == "delete_thumbnail":
            return await handle_delete_thumbnail(update, context)

        elif query.data.startswith("upload_thumbnail_"):
            # Upload Thumbnail - applique automatiquement le thumbnail enregistré
            return await handle_add_thumbnail_to_post(update, context)

        elif query.data.startswith("set_thumbnail_rename_"):
            # Set Thumbnail + Rename - applique le thumbnail ET demande le nouveau nom
            return await handle_set_thumbnail_and_rename(update, context)

        elif query.data == "edit_username":
            return await handle_add_username(update, context)

        elif query.data == "delete_username":
            channel_username = context.user_data.get('custom_channel')
            if channel_username:
                user_id = update.effective_user.id
                # Utiliser la fonction de normalisation
                clean_username = normalize_channel_username(channel_username)
                
                # Supprimer le tag de la base de données
                success = db_manager.set_channel_tag(clean_username, user_id, None)
                
                if success:
                    await query.edit_message_text(
                        f"✅ Tag supprimé pour @{clean_username}",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")
                        ]])
                    )
                else:
                    await query.edit_message_text(
                        "❌ Erreur lors de la suppression du tag.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")
                        ]])
                    )
            else:
                await query.edit_message_text(
                    "❌ Aucun canal sélectionné.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
                    ]])
                )
            return SETTINGS

        # Modifier le cas add_thumbnail pour qu'il corresponde à votre logique
        elif query.data == "add_thumbnail":
            # Vérifier si on est dans le contexte d'un canal sélectionné
            selected_channel = context.user_data.get('selected_channel', {})
            if selected_channel:
                channel_username = selected_channel.get('username')
                await query.edit_message_text(
                    f"🖼️ Enregistrer un thumbnail pour @{channel_username}\n\n"
                    f"Envoyez-moi une image pour l'utiliser comme thumbnail par défaut.\n\n"
                    f"• Le thumbnail doit être une image (JPEG ou PNG recommandé)\n"
                    f"• Taille maximale : 200 KB\n"
                    f"• Dimensions recommandées : 320x320 px",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Annuler", callback_data="thumbnail_menu")
                    ]])
                )
                context.user_data['waiting_for_channel_thumbnail'] = True
                return WAITING_THUMBNAIL
            else:
                # Si pas de canal sélectionné, demander de choisir
                await query.edit_message_text(
                    "❌ Veuillez d'abord sélectionner un canal via le bouton Custom.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
                    ]])
                )
                return SETTINGS
            
    except Exception as e:
        logger.error(f"Erreur dans handle_callback: {e}")
        await update.callback_query.message.reply_text(
            "❌ Une erreur est survenue. Veuillez réessayer.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def handle_post_content(update, context):
    """Gère la réception du contenu d'un post (texte, photo, vidéo, document)."""
    message = update.message
    REPLY_KEYBOARD_BUTTONS = ["Tout supprimer", "Aperçu", "Annuler", "Envoyer"]
    # Ne pas traiter les commandes du ReplyKeyboard comme des posts
    if message.text and message.text.strip() in REPLY_KEYBOARD_BUTTONS:
        return  # On laisse le handler du ReplyKeyboard gérer ça
    # Initialiser la liste des posts si elle n'existe pas
    if 'posts' not in context.user_data:
        context.user_data['posts'] = []
    # Vérifier la limite de 24 fichiers
    if len(context.user_data['posts']) >= 24:
        await message.reply_text(
            "⚠️ Vous avez atteint la limite de 24 fichiers pour ce post.\nVeuillez d'abord envoyer ce post avant d'en ajouter d'autres."
        )
        keyboard = [
            [InlineKeyboardButton("✏️ Edit File", callback_data="edit_file")],
            [InlineKeyboardButton("❌ Annuler", callback_data="main_menu")]
        ]
        await message.reply_text(
            "Que souhaitez-vous faire ?",
            reply_markup=InlineKeyboardMarkup(keyboard)
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
    # Définir les boutons d'action - boutons principaux
    keyboard = [
        [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
        [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
        [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}")],
        [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
    ]
    # Envoyer l'aperçu avec les boutons
    try:
        sent_message = None
        
        # Essayer d'abord l'aperçu normal, puis basculer si nécessaire
        file_too_large = False
        actual_file_size = None
        
        if post_data["type"] in ["video", "document"]:
            try:
                file_obj = await context.bot.get_file(post_data["content"])
                actual_file_size = file_obj.file_size
                if file_obj.file_size > 50 * 1024 * 1024:  # 50 Mo
                    file_too_large = True
                    logger.info(f"Fichier trop volumineux pour aperçu: {file_obj.file_size} bytes")
            except Exception as size_error:
                # Si on ne peut pas récupérer la taille, on va quand même essayer l'aperçu
                logger.info(f"Impossible de vérifier la taille du fichier ({size_error}), tentative d'aperçu normal")
        
        # Essayer d'envoyer l'aperçu d'abord (même si on ne connaît pas la taille)
        sent_message = None
        try:
            if post_data["type"] == "photo":
                sent_message = await context.bot.send_photo(
                    chat_id=message.chat_id,
                    photo=post_data["content"],
                    caption=post_data["caption"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post_data["type"] == "video" and not file_too_large:
                sent_message = await context.bot.send_video(
                    chat_id=message.chat_id,
                    video=post_data["content"],
                    caption=post_data["caption"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post_data["type"] == "document" and not file_too_large:
                sent_message = await context.bot.send_document(
                    chat_id=message.chat_id,
                    document=post_data["content"],
                    caption=post_data["caption"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post_data["type"] == "text":
                sent_message = await context.bot.send_message(
                    chat_id=message.chat_id,
                    text=post_data["content"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        except Exception as preview_error:
            # Si l'aperçu échoue (fichier trop gros), alors on envoie le message alternatif
            if "File is too big" in str(preview_error) or "too large" in str(preview_error).lower():
                logger.info(f"Aperçu impossible (fichier trop volumineux), affichage du message alternatif")
                file_too_large = True
            else:
                # Autre erreur, on la propage
                logger.error(f"Erreur lors de l'aperçu: {preview_error}")
                raise preview_error
        
        # Si l'aperçu a échoué à cause de la taille, envoyer le message alternatif
        if file_too_large and not sent_message:
            file_type_text = "vidéo" if post_data["type"] == "video" else "document"
            size_text = f" ({actual_file_size / (1024*1024):.1f} Mo)" if actual_file_size else " (taille inconnue)"
            preview_text = f"📁 {file_type_text.capitalize()} ajouté(e){size_text}\n"
            if post_data.get("caption"):
                preview_text += f"📝 Légende: {post_data['caption']}\n"
            preview_text += "\n⚠️ Aperçu non disponible (fichier volumineux)\n✅ Le fichier sera envoyé via userbot lors de la publication"
            
            sent_message = await context.bot.send_message(
                chat_id=message.chat_id,
                text=preview_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        if sent_message:
            # Sauvegarder les informations du message d'aperçu
            if 'preview_messages' not in context.user_data:
                context.user_data['preview_messages'] = {}
            context.user_data['preview_messages'][post_index] = {
                'message_id': sent_message.message_id,
                'chat_id': message.chat_id
            }
        # Afficher le nombre de fichiers restants
        remaining_files = 24 - len(context.user_data['posts'])
        await message.reply_text(
            f"✅ Fichier ajouté ! Il vous reste {remaining_files} fichiers disponibles dans ce post.\nVous pouvez continuer à m'envoyer des fichiers pour ce post ou cliquer sur 'Edit File' quand vous avez terminé."
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du message: {e}")
        await message.reply_text("❌ Erreur lors de l'envoi du message.")
        return WAITING_PUBLICATION_CONTENT
    return WAITING_PUBLICATION_CONTENT


# handle_reaction_input maintenant importé de reaction_functions


async def handle_url_input(update, context):
    """Gère l'input des boutons URL pour un post."""
    if 'waiting_for_url' not in context.user_data or 'current_post_index' not in context.user_data:
        return WAITING_PUBLICATION_CONTENT
    try:
        post_index = context.user_data['current_post_index']
        text = update.message.text.strip()
        if '|' not in text:
            await update.message.reply_text(
                "❌ Format incorrect. Utilisez : Texte du bouton | URL\nExemple : Visiter le site | https://example.com"
            )
            return WAITING_PUBLICATION_CONTENT
        button_text, url = [part.strip() for part in text.split('|', 1)]
        if not url.startswith(('http://', 'https://')):
            await update.message.reply_text(
                "❌ L'URL doit commencer par http:// ou https://"
            )
            return WAITING_PUBLICATION_CONTENT
        if 'buttons' not in context.user_data['posts'][post_index]:
            context.user_data['posts'][post_index]['buttons'] = []
        context.user_data['posts'][post_index]['buttons'].append({
            'text': button_text,
            'url': url
        })
        # Construction du nouveau clavier
        keyboard = []
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
        for btn in context.user_data['posts'][post_index]['buttons']:
            keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
        keyboard.extend([
            [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
            [InlineKeyboardButton("Supprimer les boutons URL", callback_data=f"remove_url_buttons_{post_index}")],
            [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        preview_info = context.user_data.get('preview_messages', {}).get(post_index)
        if preview_info:
            try:
                await context.bot.delete_message(
                    chat_id=preview_info['chat_id'],
                    message_id=preview_info['message_id']
                )
            except Exception:
                pass
        post = context.user_data['posts'][post_index]
        sent_message = None
        
        # Vérifier si le fichier est trop volumineux pour l'aperçu
        file_too_large = False
        if post["type"] in ["video", "document"]:
            try:
                file_obj = await context.bot.get_file(post["content"])
                if file_obj.file_size > 50 * 1024 * 1024:  # 50 Mo
                    file_too_large = True
            except Exception:
                file_too_large = True  # Par sécurité
        
        if file_too_large:
            # Pour les gros fichiers, envoyer un message texte au lieu de l'aperçu
            file_type_text = "vidéo" if post["type"] == "video" else "document"
            preview_text = f"📁 {file_type_text.capitalize()} (fichier volumineux)\n"
            if post.get("caption"):
                preview_text += f"📝 Légende: {post['caption']}\n"
            preview_text += "\n⚠️ Aperçu non disponible (fichier > 50 Mo)\n✅ Le fichier sera envoyé via userbot lors de la publication"
            
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=preview_text,
                reply_markup=reply_markup
            )
        else:
            # Pour les fichiers normaux, envoyer l'aperçu habituel
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
            if 'preview_messages' not in context.user_data:
                context.user_data['preview_messages'] = {}
            context.user_data['preview_messages'][post_index] = {
                'message_id': sent_message.message_id,
                'chat_id': update.effective_chat.id
            }
        await update.message.reply_text(
            "✅ Bouton URL ajouté avec succès !\nVous pouvez continuer à m'envoyer des messages."
        )
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


async def handle_channel_info(update, context):
    """Gère l'ajout d'un nouveau canal"""
    try:
        text = update.message.text
        if "|" not in text:
            await update.message.reply_text(
                "❌ Format incorrect. Utilisez :\nnom_du_canal | @username_du_canal"
            )
            return WAITING_CHANNEL_INFO
        name, username = text.split("|", 1)
        name = name.strip()
        username = username.strip()
        if not is_valid_channel_username(username):
            await update.message.reply_text(
                "❌ Le nom de canal ou le lien est invalide. Utilisez uniquement un @username public ou t.me/username. Les liens d'invitation t.me/+ ne sont pas supportés."
            )
            return WAITING_CHANNEL_INFO
        # Nettoyer le username avant de l'enregistrer
        username = clean_channel_username(username)
        try:
            db_manager.add_channel(name, username, update.effective_user.id)
        except sqlite3.IntegrityError:
            await update.message.reply_text(
                "❌ Ce canal existe déjà."
            )
            return MAIN_MENU
        except Exception as db_error:
            logger.error(f"Erreur lors de l'ajout du canal : {db_error}")
            await update.message.reply_text(
                "❌ Une erreur est survenue lors de l'ajout du canal."
            )
            return MAIN_MENU
        keyboard = [
            [InlineKeyboardButton("➕ Ajouter un autre canal", callback_data="add_channel")],
            [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")],
        ]
        await update.message.reply_text(
            f"✅ Canal '{name}' ajouté avec succès !\nUsername: {username}",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return MAIN_MENU
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout du canal : {e}")
        await update.message.reply_text("❌ Une erreur est survenue lors de l'ajout du canal.")
        return MAIN_MENU


async def handle_timezone(update, context):
    """Affiche la demande de saisie du fuseau horaire à l'utilisateur."""
    try:
        message = (
            "🌍 Veuillez entrer votre fuseau horaire au format :\n"
            "• Europe/Paris\n"
            "• America/New_York\n"
            "• Asia/Tokyo\n"
            "• Africa/Cairo\n\n"
            "Vous pouvez trouver la liste complète ici :\n"
            "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="settings")]])
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annuler", callback_data="settings")]])
            )
        return WAITING_TIMEZONE
    except Exception as e:
        logger.error(f"Erreur dans handle_timezone : {e}")
        await update.message.reply_text("❌ Une erreur est survenue lors de l'affichage du fuseau horaire.")
        return MAIN_MENU


async def handle_thumbnail_input(update, context):
    """Gère la réception d'une image à utiliser comme thumbnail"""
    try:
        # Vérifier si on attend un thumbnail pour un canal
        if context.user_data.get('waiting_for_channel_thumbnail', False):
            selected_channel = context.user_data.get('selected_channel', {})
            if not selected_channel:
                await update.message.reply_text(
                    "❌ Aucun canal sélectionné.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )
                return MAIN_MENU
            
            if not update.message.photo:
                await update.message.reply_text(
                    "❌ Merci d'envoyer une photo (image) pour la miniature.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
                    ]])
                )
                return WAITING_THUMBNAIL
            
            channel_username = selected_channel.get('username')
            user_id = update.effective_user.id
            
            # Nettoyer le nom d'utilisateur du canal (enlever @ s'il est présent)
            clean_username = channel_username.lstrip('@') if channel_username else None
            
            if not clean_username:
                await update.message.reply_text(
                    "❌ Erreur: impossible de déterminer le canal cible.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
                    ]])
                )
                return SETTINGS
            
            photo = update.message.photo[-1]  # Prendre la meilleure qualité
            file_size = photo.file_size
            
            # Vérifier la taille du thumbnail
            if file_size > 200 * 1024:
                await update.message.reply_text(
                    f"⚠️ Ce thumbnail fait {file_size / 1024:.1f} KB, ce qui dépasse la limite recommandée de 200 KB.\n"
                    f"Il pourrait ne pas s'afficher correctement.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Utiliser quand même", callback_data="confirm_large_thumbnail")],
                        [InlineKeyboardButton("❌ Réessayer", callback_data="add_thumbnail")]
                    ])
                )
                context.user_data['temp_thumbnail'] = photo.file_id
                return WAITING_THUMBNAIL
            
            # Enregistrer le thumbnail dans la base de données
            if db_manager.save_thumbnail(clean_username, user_id, photo.file_id):
                logger.info(f"ENREGISTREMENT: user_id={user_id}, channel={clean_username}, file_id={photo.file_id}")
                context.user_data['waiting_for_channel_thumbnail'] = False
                
                await update.message.reply_text(
                    f"✅ Thumbnail enregistré avec succès pour @{clean_username}!",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")
                    ]])
                )
                
                return SETTINGS
            else:
                await update.message.reply_text(
                    "❌ Erreur lors de l'enregistrement du thumbnail.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")
                    ]])
                )
                return SETTINGS
        
        # Ancien code pour la compatibilité
        elif context.user_data.get('waiting_for_thumbnail', False):
            # Code existant pour l'ancien système global
            photo = update.message.photo[-1]
            context.user_data['user_thumbnail'] = photo.file_id
            context.user_data['waiting_for_thumbnail'] = False
            
            await update.message.reply_text(
                "✅ Thumbnail enregistré!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
                ]])
            )
            return SETTINGS
        
        else:
            await update.message.reply_text(
                "❌ Je n'attends pas de thumbnail actuellement.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement du thumbnail: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors du traitement de votre image.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_preview(update, context):
    """Affiche l'aperçu de tous les fichiers du post."""
    posts = context.user_data.get("posts", [])
    if not posts:
        await update.message.reply_text("❌ Il n'y a pas encore de fichiers dans ce post.")
        return

    # Compteurs pour le résumé
    type_counts = {
        "photo": 0,
        "video": 0,
        "document": 0,
        "text": 0
    }

    # Envoi de chaque fichier
    for post in posts:
        post_type = post.get("type")
        content = post.get("content")
        caption = post.get("caption") or ""

        # Mise à jour des compteurs
        type_counts[post_type] = type_counts.get(post_type, 0) + 1

        # Envoi du fichier ou du texte selon le type
        if post_type == "photo":
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=content,
                caption=caption if caption else None
            )
        elif post_type == "video":
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=content,
                caption=caption if caption else None
            )
        elif post_type == "document":
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=content,
                caption=caption if caption else None
            )
        elif post_type == "text":
            await update.message.reply_text(caption or content)

    # Construction du message récapitulatif
    summary = "Aperçu des fichiers dans ce post :\n\n"
    total_files = len(posts)
    summary += f"Total : {total_files} fichier(s)\n"

    if type_counts["photo"] > 0:
        summary += f"📸 Photos : {type_counts['photo']}\n"
    if type_counts["video"] > 0:
        summary += f"🎥 Vidéos : {type_counts['video']}\n"
    if type_counts["document"] > 0:
        summary += f"📄 Documents : {type_counts['document']}\n"
    if type_counts["text"] > 0:
        summary += f"📝 Messages texte : {type_counts['text']}\n"

    await update.message.reply_text(summary)


async def handle_channel_selection(update, context):
    """Gère la sélection d'un canal et prépare la réception du contenu ou traite le contenu reçu"""
    try:
        # Cas 1: Callback query - Sélection d'un canal
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            
            # Extraire le nom d'utilisateur du canal du callback_data
            channel_username = query.data.replace("select_channel_", "")
            user_id = update.effective_user.id
            
            # Récupérer les informations du canal depuis la base de données
            channels = db_manager.list_channels(user_id)
            channel_name = next((channel['name'] for channel in channels if channel['username'] == channel_username), channel_username)
            
            # Stocker le canal sélectionné dans le contexte
            context.user_data['selected_channel'] = {
                'username': channel_username,
                'name': channel_name
            }
            
            # Message de confirmation
            message = (
                f"✅ Canal sélectionné : {channel_name}\n\n"
                f"Envoyez-moi le contenu que vous souhaitez publier (texte, photo, vidéo ou document).\n\n"
                f"Vous pouvez envoyer jusqu'à 24 fichiers pour ce post."
            )
            
            # Clavier avec les boutons d'action
            keyboard = [
                [InlineKeyboardButton("❌ Annuler", callback_data="main_menu")]
            ]
            
            try:
                await query.edit_message_text(
                    message,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Erreur lors de l'édition du message sélection canal: {e}")
            
            return WAITING_PUBLICATION_CONTENT
        
        # Cas 2: Message normal - Contenu reçu après sélection du canal
        else:
            # Vérifier qu'un canal est sélectionné
            if 'selected_channel' not in context.user_data:
                await update.message.reply_text(
                    "❌ Aucun canal sélectionné. Veuillez d'abord sélectionner un canal.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="create_publication")]])
                )
                return WAITING_CHANNEL_SELECTION
            
            # Rediriger vers handle_post_content pour traiter le contenu
            return await handle_post_content(update, context)
        
    except Exception as e:
        logger.error(f"Erreur dans handle_channel_selection: {e}")
        
        # Gestion d'erreur selon le type d'update
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    "❌ Une erreur est survenue lors de la sélection du canal. Veuillez réessayer.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                )
            except:
                await update.callback_query.message.reply_text(
                    "❌ Une erreur est survenue. Retour au menu principal.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
                )
        else:
            await update.message.reply_text(
                "❌ Une erreur est survenue. Retour au menu principal.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
            )
        
        return MAIN_MENU


async def handle_content_after_channel_selection(update, context):
    """Gère le contenu reçu après qu'un canal ait été sélectionné"""
    try:
        # Vérifier qu'un canal est sélectionné
        if 'selected_channel' not in context.user_data:
            await update.message.reply_text(
                "❌ Aucun canal sélectionné. Veuillez d'abord sélectionner un canal.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Retour", callback_data="create_publication")]])
            )
            return WAITING_CHANNEL_SELECTION
        
        # Rediriger vers handle_post_content pour traiter le contenu
        return await handle_post_content(update, context)
        
    except Exception as e:
        logger.error(f"Erreur dans handle_content_after_channel_selection: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue. Retour au menu principal.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def handle_reply_keyboard(update, context):
    """Gère les interactions avec le clavier de réponse"""
    try:
        user_text = update.message.text.strip().lower()
        logger.info(f"handle_reply_keyboard: reçu '{user_text}'")

        if user_text == "envoyer":
            # Vérifier si un post planifié est sélectionné
            if 'current_scheduled_post' in context.user_data:
                scheduled_post = context.user_data['current_scheduled_post']
                return await send_post_now(update, context, scheduled_post=scheduled_post)
            posts = context.user_data.get("posts", [])
            if not posts:
                await update.message.reply_text("❌ Il n'y a pas encore de fichiers à envoyer.")
                return WAITING_PUBLICATION_CONTENT
            channel = posts[0].get("channel", config.DEFAULT_CHANNEL)
            keyboard = [
                [InlineKeyboardButton("Régler temps d'auto destruction", callback_data="auto_destruction")],
                [InlineKeyboardButton("Maintenant", callback_data="send_now")],
                [InlineKeyboardButton("Planifier", callback_data="schedule_send")],
                [InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]
            ]
            await update.message.reply_text(
                f"Vos {len(posts)} fichiers sont prêts à être envoyés à {channel}.\nQuand souhaitez-vous les envoyer ?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SEND_OPTIONS
        elif user_text == "aperçu":
            await handle_preview(update, context)
            return WAITING_PUBLICATION_CONTENT
        elif user_text == "annuler":
            context.user_data.pop("posts", None)
            context.user_data.pop("preview_messages", None)
            context.user_data.pop("current_scheduled_post", None)
            await update.message.reply_text("Publication annulée. Retour au menu principal.")
            return await start(update, context)
        elif user_text == "tout supprimer":
            if 'preview_messages' in context.user_data:
                for preview_info in context.user_data['preview_messages'].values():
                    try:
                        await context.bot.delete_message(
                            chat_id=preview_info['chat_id'],
                            message_id=preview_info['message_id']
                        )
                    except Exception:
                        pass
            context.user_data.pop("posts", None)
            context.user_data.pop("preview_messages", None)
            context.user_data.pop("current_scheduled_post", None)
            await update.message.reply_text("✅ Tous les fichiers ont été supprimés.")
            return await start(update, context)
        else:
            return await handle_post_content(update, context)
        return WAITING_PUBLICATION_CONTENT
    except Exception as e:
        logger.error(f"Erreur dans handle_reply_keyboard : {e}")
        await update.message.reply_text("❌ Une erreur est survenue. Retour au menu principal.")
        return await start(update, context)


async def diagnostic(update, context):
    await update.message.reply_text("Diagnostic non implémenté.")
    return MAIN_MENU


async def db_diagnostic(update, context):
    await update.message.reply_text("Diagnostic DB non implémenté.")
    return MAIN_MENU


async def debug_state(update, context):
    await update.message.reply_text("Debug state non implémenté.")
    return MAIN_MENU


async def handle_reaction_click(update, context):
    query = update.callback_query
    await query.answer()
    try:
        # Extraire l'index du post et l'emoji
        data = query.data  # ex: react_0_👍
        parts = data.split('_')
        if len(parts) < 3:
            await query.answer("Erreur de format de réaction")
            return MAIN_MENU
        post_index = int(parts[1])
        emoji = '_'.join(parts[2:])

        # Stockage des réactions en mémoire (par chat, post, emoji)
        chat_id = query.message.chat_id
        message_id = query.message.message_id
        key = (chat_id, message_id, post_index, emoji)
        reaction_counts = context.bot_data.setdefault('reaction_counts', {})
        reaction_counts[key] = reaction_counts.get(key, 0) + 1
        count = reaction_counts[key]

        # Récupérer le post pour reconstruire le clavier
        posts = context.user_data.get('posts', [])
        if post_index >= len(posts):
            await query.answer("Post introuvable")
            return MAIN_MENU
        post = posts[post_index]
        reactions = post.get('reactions', [])
        buttons = post.get('buttons', [])

        # Reconstruire le clavier avec les compteurs
        keyboard = []
        current_row = []
        for r in reactions:
            k = (chat_id, message_id, post_index, r)
            c = reaction_counts.get(k, 0)
            label = f"{r} {c}" if c > 0 else r
            current_row.append(InlineKeyboardButton(label, callback_data=f"react_{post_index}_{r}"))
            if len(current_row) == 4:
                keyboard.append(current_row)
                current_row = []
        if current_row:
            keyboard.append(current_row)
        for btn in buttons:
            keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Mettre à jour le clavier du message
        try:
            await query.edit_message_reply_markup(reply_markup=reply_markup)
        except Exception as e:
            if "Message is not modified" not in str(e):
                await query.message.reply_text("Erreur lors de la mise à jour du clavier des réactions.")
        await query.answer(f"+1 pour {emoji}")
        return MAIN_MENU
    except Exception as e:
        logger.error(f"Erreur dans handle_reaction_click: {e}")
        await query.answer("Erreur lors du traitement de la réaction")
        return MAIN_MENU


async def settings(update, context):
    """Affiche le menu des paramètres du bot."""
    try:
        user_id = update.effective_user.id
        keyboard = [
            [InlineKeyboardButton("🌐 Gérer mes canaux", callback_data='manage_channels')],
            [InlineKeyboardButton("⏰ Fuseau horaire", callback_data='timezone')],
            [InlineKeyboardButton("🎨 Custom", callback_data='custom_settings')],
            [InlineKeyboardButton("🏠 Retour au menu principal", callback_data='main_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.message:
            await update.message.reply_text(
                "⚙️ *Paramètres*\n\nConfigurez vos préférences et gérez vos canaux Telegram ici.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.callback_query.edit_message_text(
                "⚙️ *Paramètres*\n\nConfigurez vos préférences et gérez vos canaux Telegram ici.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        logger.info(f"Utilisateur {user_id} a ouvert les paramètres")
        return SETTINGS
    except Exception as e:
        logger.error(f"Erreur dans settings : {e}")
        if update.message:
            await update.message.reply_text("❌ Erreur lors de l'affichage des paramètres.")
        else:
            await update.callback_query.edit_message_text("❌ Erreur lors de l'affichage des paramètres.")
        return MAIN_MENU

async def manage_channels(update, context):
    """Affiche la liste des canaux de l'utilisateur avec option de suppression."""
    try:
        user_id = update.effective_user.id
        channels = db_manager.list_channels(user_id)
        if not channels:
            await update.callback_query.edit_message_text(
                "Vous n'avez pas encore ajouté de canaux.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="settings")]])
            )
            return SETTINGS
        message = "🌐 *Vos canaux* :\n\n"
        keyboard = []
        for channel in channels:
            message += f"• {channel['name']} (@{channel['username']})\n"
            keyboard.append([
                InlineKeyboardButton(f"❌ Supprimer {channel['name']}", callback_data=f"delete_channel_{channel['username']}")
            ])
        keyboard.append([InlineKeyboardButton("↩️ Retour", callback_data="settings")])
        await update.callback_query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return SETTINGS
    except Exception as e:
        logger.error(f"Erreur dans manage_channels : {e}")
        await update.callback_query.edit_message_text(
            "❌ Erreur lors de l'affichage des canaux.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="settings")]])
        )
        return SETTINGS

async def cleanup(application):
    """Fonction de nettoyage pour arrêter proprement le bot et le client Telethon"""
    try:
        # Arrêter le scheduler s'il existe
        if hasattr(application, 'scheduler_manager'):
            application.scheduler_manager.stop()
            logger.info("Scheduler arrêté avec succès")
        
        # Déconnecter le client Telethon
        if hasattr(application, 'bot_data') and 'userbot' in application.bot_data:
            await application.bot_data['userbot'].disconnect()
            logger.info("Client Telethon déconnecté avec succès")
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage: {e}")

async def send_large_file(update: Update, context):
    """Gère l'envoi de fichiers volumineux via le userbot."""
    try:
        message = update.message
        file = None
        file_name = None
        file_type = None

        # Détecter le type de média
        if message.document:
            file = message.document
            file_name = file.file_name or "document"
            file_type = "document"
        elif message.video:
            file = message.video
            file_name = file.file_name or "video.mp4"
            file_type = "video"
        elif message.photo:
            file = message.photo[-1]  # Prendre la meilleure qualité
            file_name = f"photo_{file.file_id}.jpg"
            file_type = "photo"
        else:
            await message.reply_text("❌ Type de fichier non supporté pour l'envoi de gros fichiers.")
            return

        # Télécharger le fichier dans le dossier de téléchargement
        download_path = os.path.join(config.DOWNLOAD_FOLDER, file_name)
        file_obj = await file.get_file()
        await file_obj.download_to_drive(download_path)

        file_size = os.path.getsize(download_path)
        max_bot_size = getattr(config, 'BOT_MAX_MEDIA_SIZE', 50 * 1024 * 1024)
        max_userbot_size = getattr(config, 'USERBOT_MAX_MEDIA_SIZE', 2 * 1024 * 1024 * 1024)

        # Si le fichier est trop gros pour le userbot
        if file_size > max_userbot_size:
            await message.reply_text("❌ Fichier trop volumineux pour être envoyé (limite 2 Go)")
            os.remove(download_path)
            return

        # Si le fichier est petit, l'envoyer avec le bot
        if file_size <= max_bot_size:
            if file_type == "document":
                await context.bot.send_document(chat_id=message.chat_id, document=download_path)
            elif file_type == "video":
                await context.bot.send_video(chat_id=message.chat_id, video=download_path)
            elif file_type == "photo":
                await context.bot.send_photo(chat_id=message.chat_id, photo=download_path)
            await message.reply_text("✅ Fichier envoyé via le bot !")
            os.remove(download_path)
            return

        # Sinon, utiliser Telethon (userbot)
        try:
            await message.reply_text("⏳ Upload du fichier en cours...")
            userbot = context.application.bot_data.get('userbot')
            if not userbot:
                await message.reply_text("❌ Userbot non initialisé. Impossible d'envoyer le fichier volumineux.")
                return

            await retry_operation(
                lambda: userbot.send_file(
                    message.chat_id,
                    download_path,
                    caption="📤 Voici votre fichier !"
                )
            )
            await message.reply_text("✅ Fichier envoyé via le userbot !")
        finally:
            if os.path.exists(download_path):
                os.remove(download_path)

    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du fichier : {e}")
        # Exécuter le nettoyage
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(cleanup(application))
        else:
            loop.run_until_complete(cleanup(application))

class ResourceManager:
    def __init__(self, download_folder: str, max_storage_mb: int = 1000):
        self.download_folder = download_folder
        self.max_storage_bytes = max_storage_mb * 1024 * 1024
        os.makedirs(download_folder, exist_ok=True)

    async def cleanup_old_files(self, max_age_hours: int = 24):
        """Nettoie les fichiers plus vieux que max_age_hours"""
        try:
            current_time = time.time()
            for filename in os.listdir(self.download_folder):
                file_path = os.path.join(self.download_folder, filename)
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getmtime(file_path)
                    if file_age > (max_age_hours * 3600):
                        os.remove(file_path)
                        logger.info(f"Fichier supprimé: {filename}")
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des fichiers: {e}")

    def check_storage_usage(self) -> bool:
        """Vérifie si l'utilisation du stockage est dans les limites"""
        try:
            total_size = 0
            for dirpath, _, filenames in os.walk(self.download_folder):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    total_size += os.path.getsize(fp)
            return total_size <= self.max_storage_bytes
        except Exception as e:
            logger.error(f"Erreur lors de la vérification du stockage: {e}")
            return False

# Initialisation du gestionnaire de ressources
resource_manager = ResourceManager(config.DOWNLOAD_FOLDER)

class InputValidator:
    @staticmethod
    def validate_url(url: str) -> bool:
        """Valide une URL"""
        url_pattern = re.compile(
            r'^(https?://)?'  # http:// ou https://
            r'(([a-z\d]([a-z\d-]*[a-z\d])*)\.)+[a-z]{2,}|'  # domaine
            r'((\d{1,3}\.){3}\d{1,3}))'  # ou IP
            r'(\:\d+)?(\/[-a-z\d%_.~+]*)*'  # port et chemin
            r'(\?[;&a-z\d%_.~+=-]*)?'  # paramètres de requête
            r'(\#[-a-z\d_]*)?$',  # fragment
            re.IGNORECASE
        )
        return bool(url_pattern.match(url))

    @staticmethod
    def validate_channel_name(name: str) -> bool:
        """Valide un nom de canal"""
        return bool(re.match(r'^[a-zA-Z0-9_]{5,32}$', name))

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Nettoie le texte des caractères indésirables"""
        # Supprime les caractères de contrôle
        text = ''.join(char for char in text if ord(char) >= 32)
        # Échappe les caractères spéciaux Markdown
        text = text.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[')
        return text

# Initialisation du validateur
input_validator = InputValidator()

async def cancel_reactions(update, context):
    """Annule l'ajout de réactions et retourne au menu principal"""
    try:
        await update.callback_query.edit_message_text(
            "❌ Ajout de réactions annulé.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return MAIN_MENU
    except Exception as e:
        logger.error(f"Erreur dans cancel_reactions: {e}")
        return MAIN_MENU

async def select_emoji(update, context):
    """Gère la sélection d'un emoji pour les réactions"""
    return WAITING_REACTION_INPUT

async def remove_emoji(update, context):
    """Gère la suppression d'un emoji des réactions"""
    return WAITING_REACTION_INPUT

async def finish_reactions(update, context):
    """Termine l'ajout de réactions"""
    return WAITING_PUBLICATION_CONTENT

async def cancel_url_button(update, context):
    """Annule l'ajout d'un bouton URL"""
    return WAITING_PUBLICATION_CONTENT

async def handle_custom_settings(update, context):
    """Gère les paramètres personnalisés pour les canaux"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    channels = db_manager.list_channels(user_id)
    
    if not channels:
        await query.edit_message_text(
            "❌ Aucun canal configuré.\nAjoutez d'abord un canal via /start.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="settings")
            ]])
        )
        return SETTINGS
    
    keyboard = []
    for channel in channels:
        keyboard.append([
            InlineKeyboardButton(
                f"📺 {channel['name']}", 
                callback_data=f"custom_channel_{channel['username']}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton("↩️ Retour", callback_data="settings")])
    
    await query.edit_message_text(
        "📋 Choisissez un canal pour gérer ses paramètres:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return SETTINGS

async def handle_custom_channel(update, context):
    """Gère la sélection d'un canal pour les paramètres personnalisés"""
    query = update.callback_query
    await query.answer()
    
    # Extraire le nom d'utilisateur du canal depuis callback_data
    channel_username = query.data.replace("custom_channel_", "")
    user_id = update.effective_user.id
    
    # Log pour debug
    logger.info(f"handle_custom_channel: channel_username={channel_username}, user_id={user_id}")
    
    # Stocker le canal sélectionné pour les opérations suivantes
    context.user_data['custom_channel'] = channel_username
    context.user_data['selected_channel'] = {'username': channel_username}
    
    # Récupérer les informations du canal
    channel_info = db_manager.get_channel_by_username(channel_username, user_id)
    logger.info(f"handle_custom_channel: channel_info={channel_info}")
    
    if not channel_info:
        # Essayer de chercher le canal sans nettoyer (au cas où il y aurait un problème de formatage)
        channels = db_manager.list_channels(user_id)
        logger.info(f"handle_custom_channel: all channels for user {user_id}: {[ch['username'] for ch in channels]}")
        
        # Chercher le canal manuellement
        channel_info = None
        for channel in channels:
            if channel['username'] == channel_username or channel['username'] == channel_username.lstrip('@'):
                channel_info = channel
                break
        
        if not channel_info:
            await query.edit_message_text(
                f"❌ Canal introuvable.\n\nRecherché: {channel_username}\nCanaux disponibles: {[ch['username'] for ch in channels[:3]]}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
                ]])
            )
            return SETTINGS
    
    # Vérifier l'état des paramètres
    existing_tag = db_manager.get_channel_tag(channel_username, user_id)
    existing_thumbnail = db_manager.get_thumbnail(channel_username, user_id)
    
    keyboard = []
    
    # Gestion des thumbnails
    if existing_thumbnail:
        keyboard.append([InlineKeyboardButton("🖼️ Gérer le thumbnail", callback_data="thumbnail_menu")])
    else:
        keyboard.append([InlineKeyboardButton("➕ Ajouter un thumbnail", callback_data="add_thumbnail")])
    
    # Gestion des tags/usernames
    if existing_tag:
        keyboard.append([InlineKeyboardButton(f"✏️ Modifier le tag: {existing_tag}", callback_data="edit_username")])
        keyboard.append([InlineKeyboardButton("🗑️ Supprimer le tag", callback_data="delete_username")])
    else:
        keyboard.append([InlineKeyboardButton("➕ Ajouter un tag/username", callback_data="add_username")])
    
    keyboard.append([InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")])
    
    message = f"⚙️ Paramètres pour @{channel_username}\n\n"
    message += f"📺 Nom: {channel_info['name']}\n"
    message += f"🖼️ Thumbnail: {'✅ Configuré' if existing_thumbnail else '❌ Non configuré'}\n"
    message += f"🏷️ Tag: {existing_tag if existing_tag else '❌ Non configuré'}"
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return SETTINGS

async def handle_custom_select_channel(update, context):
    channel_username = query.data.replace("channel_", "")
    context.user_data['custom_channel'] = channel_username
    keyboard = [
        [InlineKeyboardButton("Ajouter une miniature", callback_data="add_thumbnail")],
        [InlineKeyboardButton("Ajouter un texte/username", callback_data="add_username")],
        [InlineKeyboardButton("↩️ Retour", callback_data="settings")]
    ]
    await update.callback_query.edit_message_text(
        f"Canal sélectionné : @{channel_username}\nQue souhaitez-vous faire ?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SETTINGS

# Modifie handle_add_thumbnail et handle_add_username pour utiliser context.user_data['custom_channel']
async def handle_add_thumbnail(update, context):
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        # Fallback vers selected_channel
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
        
    if not channel_username:
        await update.callback_query.edit_message_text("Aucun canal sélectionné.")
        return SETTINGS
    
    user_id = update.effective_user.id
    # Nettoyer le nom d'utilisateur du canal (enlever @ s'il est présent)
    clean_username = channel_username.lstrip('@')
    
    # **NOUVELLE VÉRIFICATION** : Empêcher l'ajout de plusieurs thumbnails
    existing_thumbnail = db_manager.get_thumbnail(clean_username, user_id)
    if existing_thumbnail:
        await update.callback_query.edit_message_text(
            f"⚠️ Un thumbnail est déjà enregistré pour @{clean_username}.\n\n"
            f"Pour changer le thumbnail, vous devez d'abord supprimer l'ancien via le menu de gestion des thumbnails.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")
            ]])
        )
        return SETTINGS
    
    # Stocker le canal pour le traitement du thumbnail
    context.user_data['selected_channel'] = {'username': channel_username}
    context.user_data['waiting_for_channel_thumbnail'] = True
    
    await update.callback_query.edit_message_text(
        f"📷 Envoyez-moi l'image à utiliser comme thumbnail pour @{channel_username}.\n\n"
        "L'image doit faire moins de 200 KB.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Annuler", callback_data=f"custom_channel_{clean_username}")
        ]])
    )
    return WAITING_THUMBNAIL

async def handle_add_username(update, context):
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        # Fallback vers selected_channel
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    user_id = update.effective_user.id
    if not channel_username:
        await update.callback_query.edit_message_text("Aucun canal sélectionné.")
        return SETTINGS
    if db_manager.get_channel_tag(channel_username, user_id):
        await update.callback_query.edit_message_text(
            "⚠️ Un texte est déjà enregistré pour ce canal. Supprime-le avant d'en ajouter un nouveau.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{channel_username.lstrip('@')}")
            ]])
        )
        return SETTINGS
    context.user_data['waiting_for_tag'] = True
    await update.callback_query.edit_message_text(
        "✏️ Entrez le texte entre crochets [...] que vous souhaitez associer à ce canal.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Annuler", callback_data=f"custom_channel_{channel_username.lstrip('@')}")
        ]])
    )
    return WAITING_CUSTOM_USERNAME

async def handle_tag_input(update, context):
    """Gère l'ajout d'un tag pour un canal."""
    try:
        user_id = update.effective_user.id
        channel_username = context.user_data.get('custom_channel')
        if not channel_username:
            # Fallback vers selected_channel
            selected_channel = context.user_data.get('selected_channel', {})
            channel_username = selected_channel.get('username')
        
        tag_text = update.message.text
        
        if not channel_username:
            await update.message.reply_text(
                "❌ Erreur : aucun canal sélectionné.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")]])
            )
            return SETTINGS
        
        # Nettoyer le nom d'utilisateur du canal (enlever @ s'il est présent)
        clean_username = channel_username.lstrip('@')
        
        # Enregistrer le tag dans la base de données
        success = db_manager.set_channel_tag(clean_username, user_id, tag_text)
        
        if success:
            await update.message.reply_text(
                f"✅ Tag enregistré pour @{clean_username} : {tag_text}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")]])
            )
        else:
            await update.message.reply_text(
                "❌ Erreur lors de l'enregistrement du tag.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")]])
            )
        
        # Nettoyer les variables temporaires
        context.user_data.pop('waiting_for_tag', None)
        context.user_data.pop('custom_channel', None)
        
        return SETTINGS
        
    except Exception as e:
        logger.error(f"Erreur dans handle_tag_input: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")]])
        )
        return SETTINGS

# ============================================================================
# NOUVELLES FONCTIONS DE GESTION DES THUMBNAILS
# ============================================================================

async def handle_thumbnail_functions(update, context):
    """Affiche les options de gestion des thumbnails pour un canal"""
    query = update.callback_query
    await query.answer()
    
    # Récupérer le canal sélectionné
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    if not channel_username:
        await query.edit_message_text(
            "❌ Aucun canal sélectionné.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    
    # Nettoyer le nom d'utilisateur du canal (enlever @ s'il est présent)
    clean_username = channel_username.lstrip('@')
    
    # Vérifier si un thumbnail existe déjà
    existing_thumbnail = db_manager.get_thumbnail(clean_username, user_id)
    
    keyboard = []
    
    if existing_thumbnail:
        keyboard.append([InlineKeyboardButton("👁️ Voir le thumbnail actuel", callback_data="view_thumbnail")])
        keyboard.append([InlineKeyboardButton("🔄 Changer le thumbnail", callback_data="add_thumbnail")])
        keyboard.append([InlineKeyboardButton("🗑️ Supprimer le thumbnail", callback_data="delete_thumbnail")])
    else:
        keyboard.append([InlineKeyboardButton("➕ Ajouter un thumbnail", callback_data="add_thumbnail")])
    
    keyboard.append([InlineKeyboardButton("↩️ Retour", callback_data=f"custom_channel_{clean_username}")])
    
    message = f"🖼️ Gestion du thumbnail pour @{clean_username}\n\n"
    message += "✅ Thumbnail enregistré" if existing_thumbnail else "❌ Aucun thumbnail enregistré"
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return SETTINGS

async def handle_add_thumbnail_to_post(update, context):
    """Applique automatiquement le thumbnail enregistré à un post"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Extraire l'index du post
        post_index = int(query.data.split("_")[-1])
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post = context.user_data['posts'][post_index]
        channel_username = post.get('channel', context.user_data.get('selected_channel', {}).get('username'))
        user_id = update.effective_user.id
        
        # Utiliser la fonction de normalisation
        clean_username = normalize_channel_username(channel_username)
        
        if not clean_username:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Impossible de déterminer le canal cible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer le thumbnail enregistré avec logs de debug améliorés
        logger.info(f"RECHERCHE THUMBNAIL: user_id={user_id}, canal_original='{channel_username}', canal_nettoye='{clean_username}'")
        thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
        logger.info(f"RESULTAT THUMBNAIL: {thumbnail_file_id}")
        
        # DEBUG: Si pas trouvé, faire un diagnostic complet
        if not thumbnail_file_id:
            debug_thumbnail_search(user_id, channel_username, db_manager)
        
        # DEBUG: Vérifier quels thumbnails existent pour cet utilisateur
        logger.info(f"DEBUG: Vérification de tous les thumbnails pour user_id={user_id}")
        
        if not thumbnail_file_id:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Aucun thumbnail enregistré pour @{clean_username}.\n"
                     "Veuillez d'abord enregistrer un thumbnail via les paramètres.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚙️ Aller aux paramètres", callback_data="custom_settings"),
                    InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
                ]])
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Appliquer le thumbnail au post
        post['thumbnail'] = thumbnail_file_id
        
        # Mettre à jour le message pour confirmer
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"✅ Thumbnail appliqué au post!\n\n"
                 f"Le thumbnail enregistré pour @{clean_username} a été ajouté à votre {post['type']}.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_add_thumbnail_to_post: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_set_thumbnail_and_rename(update, context):
    """Applique le thumbnail ET permet de renommer le fichier"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Extraire l'index du post
        post_index = int(query.data.split("_")[-1])
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post = context.user_data['posts'][post_index]
        channel_username = post.get('channel', context.user_data.get('selected_channel', {}).get('username'))
        user_id = update.effective_user.id
        
        # Utiliser la fonction de normalisation
        clean_username = normalize_channel_username(channel_username)
        
        if not clean_username:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ Impossible de déterminer le canal cible.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Récupérer et appliquer le thumbnail
        thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
        
        if thumbnail_file_id:
            post['thumbnail'] = thumbnail_file_id
            thumbnail_status = "✅ Thumbnail appliqué"
        else:
            thumbnail_status = "⚠️ Aucun thumbnail enregistré pour ce canal"
        
        # Stocker l'index pour le renommage
        context.user_data['waiting_for_rename'] = True
        context.user_data['current_post_index'] = post_index
        
        # Demander le nouveau nom
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"🖼️✏️ Thumbnail + Renommage\n\n"
                 f"{thumbnail_status}\n\n"
                 f"Maintenant, envoyez-moi le nouveau nom pour votre fichier (avec l'extension).\n"
                 f"Par exemple: mon_document.pdf",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_rename_{post_index}")
            ]])
        )
        
        return WAITING_RENAME_INPUT
        
    except Exception as e:
        logger.error(f"Erreur dans handle_set_thumbnail_and_rename: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_view_thumbnail(update, context):
    """Affiche le thumbnail enregistré pour un canal"""
    query = update.callback_query
    await query.answer()
    
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    if not channel_username:
        await query.edit_message_text(
            "❌ Aucun canal sélectionné.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    clean_username = normalize_channel_username(channel_username)
    
    thumbnail_file_id = db_manager.get_thumbnail(clean_username, user_id)
    
    if thumbnail_file_id:
        try:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=thumbnail_file_id,
                caption=f"🖼️ Thumbnail actuel pour @{clean_username}"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔄 Changer", callback_data="add_thumbnail")],
                [InlineKeyboardButton("🗑️ Supprimer", callback_data="delete_thumbnail")],
                [InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")]
            ]
            
            await query.message.reply_text(
                "Que voulez-vous faire avec ce thumbnail?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            logger.error(f"Erreur lors de l'affichage du thumbnail: {e}")
            await query.edit_message_text(
                "❌ Impossible d'afficher le thumbnail.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
                ]])
            )
    else:
        await query.edit_message_text(
            "❌ Aucun thumbnail enregistré pour ce canal.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
            ]])
        )
    
    return SETTINGS

async def handle_delete_thumbnail(update, context):
    """Supprime le thumbnail enregistré pour un canal"""
    query = update.callback_query
    await query.answer()
    
    channel_username = context.user_data.get('custom_channel')
    if not channel_username:
        selected_channel = context.user_data.get('selected_channel', {})
        channel_username = selected_channel.get('username')
    
    if not channel_username:
        await query.edit_message_text(
            "❌ Aucun canal sélectionné.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="custom_settings")
            ]])
        )
        return SETTINGS
    
    user_id = update.effective_user.id
    clean_username = normalize_channel_username(channel_username)
    
    if db_manager.delete_thumbnail(clean_username, user_id):
        await query.edit_message_text(
            f"✅ Thumbnail supprimé pour @{clean_username}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
            ]])
        )
    else:
        await query.edit_message_text(
            "❌ Erreur lors de la suppression du thumbnail.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="thumbnail_menu")
            ]])
        )
    
    return SETTINGS

async def handle_rename_input(update, context):
    """Gère la saisie du nouveau nom de fichier"""
    try:
        if not context.user_data.get('waiting_for_rename') or 'current_post_index' not in context.user_data:
            await update.message.reply_text(
                "❌ Aucun renommage en cours.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        post_index = context.user_data['current_post_index']
        new_filename = update.message.text.strip()
        
        # Validation du nom de fichier
        if not new_filename or '/' in new_filename or '\\' in new_filename:
            await update.message.reply_text(
                "❌ Nom de fichier invalide. Évitez les caractères spéciaux / et \\.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_rename_{post_index}")
                ]])
            )
            return WAITING_RENAME_INPUT
        
        # Appliquer le nouveau nom
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            context.user_data['posts'][post_index]['filename'] = new_filename
            
            # Nettoyer les variables temporaires
            context.user_data.pop('waiting_for_rename', None)
            context.user_data.pop('current_post_index', None)
            
            await update.message.reply_text(
                f"✅ Fichier renommé en : {new_filename}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            
            return WAITING_PUBLICATION_CONTENT
        else:
            await update.message.reply_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Erreur dans handle_rename_input: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

def is_valid_channel_username(username):
    # Vérifie que le username commence par @ ou t.me/ et ne contient pas d'espaces
    username = username.strip()
    if username.startswith("@") and len(username) > 5 and " " not in username:
        return True
    if username.startswith("t.me/") and len(username) > 8 and " " not in username:
        return True
    return False

def clean_channel_username(username):
    """
    Nettoie le username d'un canal pour ne garder que le @username ou t.me/username.
    """
    username = username.strip()
    if username.startswith("t.me/"):
        username = "@" + username[5:]
    if not username.startswith("@"):
        username = "@" + username
    return username

async def remove_reactions(update, context):
    """Supprime toutes les réactions d'un post"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Extraire l'index du post
        post_index = int(query.data.split('_')[-1])
        
        # Supprimer les réactions du post
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            context.user_data['posts'][post_index]['reactions'] = []
            
            # Reconstruire le clavier sans réactions
            keyboard = [
                [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
                [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}")]
            ]
            
            # Mettre à jour le message
            try:
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Erreur lors de la mise à jour du message: {e}")
            
            await query.message.reply_text("✅ Réactions supprimées avec succès!")
            
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"Erreur dans remove_reactions: {e}")
        await query.answer("Erreur lors de la suppression des réactions")
        return WAITING_PUBLICATION_CONTENT

async def remove_url_buttons(update, context):
    """Supprime tous les boutons URL d'un post"""
    try:
        query = update.callback_query
        await query.answer()
        
        # Extraire l'index du post
        post_index = int(query.data.split('_')[-1])
        
        # Supprimer les boutons URL du post
        if 'posts' in context.user_data and post_index < len(context.user_data['posts']):
            context.user_data['posts'][post_index]['buttons'] = []
            
            # Reconstruire le clavier sans boutons URL
            keyboard = [
                [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
                [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
                [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")],
                [InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}")]
            ]
            
            # Mettre à jour le message
            try:
                await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Erreur lors de la mise à jour du message: {e}")
            
            await query.message.reply_text("✅ Boutons URL supprimés avec succès!")
            
        return WAITING_PUBLICATION_CONTENT
        
    except Exception as e:
        logger.error(f"Erreur dans remove_url_buttons: {e}")
        await query.answer("Erreur lors de la suppression des boutons URL")
        return WAITING_PUBLICATION_CONTENT

async def send_preview_file(update, context, post_index):
    """Envoie un aperçu du fichier modifié"""
    try:
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            return
        
        post = context.user_data['posts'][post_index]
        
        # Supprimer l'ancien aperçu s'il existe
        preview_info = context.user_data.get('preview_messages', {}).get(post_index)
        if preview_info:
            try:
                await context.bot.delete_message(
                    chat_id=preview_info['chat_id'],
                    message_id=preview_info['message_id']
                )
            except Exception:
                pass
        
        # Créer les boutons d'action
        keyboard = [
            [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
        ]

        # Ajouter les boutons de thumbnail selon le type
        if post['type'] in ['photo', 'video', 'document']:
            keyboard.append([
                InlineKeyboardButton("📎 Upload Thumbnail", callback_data=f"upload_thumbnail_{post_index}"),
                InlineKeyboardButton("🖼️✏️ Set Thumbnail + Rename", callback_data=f"set_thumbnail_rename_{post_index}")
            ])
            keyboard.append([InlineKeyboardButton("✏️ Rename", callback_data=f"rename_post_{post_index}")])
        else:
            keyboard.append([InlineKeyboardButton("✏️ Renommer", callback_data=f"rename_post_{post_index}")])

        keyboard.append([InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")])
        keyboard.append([InlineKeyboardButton("✏️ Edit File", callback_data=f"edit_file_{post_index}")])
        
        # Envoyer le nouvel aperçu
        sent_message = None
        
        # Vérifier si le fichier est trop volumineux pour l'aperçu
        file_too_large = False
        if post["type"] in ["video", "document"]:
            try:
                file_obj = await context.bot.get_file(post["content"])
                if file_obj.file_size > 50 * 1024 * 1024:  # 50 Mo
                    file_too_large = True
            except Exception:
                file_too_large = True  # Par sécurité
        
        if file_too_large:
            # Pour les gros fichiers, envoyer un message texte au lieu de l'aperçu
            file_type_text = "vidéo" if post["type"] == "video" else "document"
            preview_text = f"📁 {file_type_text.capitalize()} (fichier volumineux)\n"
            if post.get("caption"):
                preview_text += f"📝 Légende: {post['caption']}\n"
            preview_text += "\n⚠️ Aperçu non disponible (fichier > 50 Mo)\n✅ Le fichier sera envoyé via userbot lors de la publication"
            
            sent_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=preview_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Pour les fichiers normaux, envoyer l'aperçu habituel
            if post["type"] == "photo":
                sent_message = await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=post["content"],
                    caption=post.get("caption"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post["type"] == "video":
                # Inclure le thumbnail s'il existe
                kwargs = {
                    'chat_id': update.effective_chat.id,
                    'video': post["content"],
                    'caption': post.get("caption"),
                    'reply_markup': InlineKeyboardMarkup(keyboard)
                }
                if post.get('thumbnail'):
                    kwargs['thumbnail'] = post['thumbnail']
                sent_message = await context.bot.send_video(**kwargs)
            elif post["type"] == "document":
                # Inclure le thumbnail s'il existe
                kwargs = {
                    'chat_id': update.effective_chat.id,
                    'document': post["content"],
                    'caption': post.get("caption"),
                    'reply_markup': InlineKeyboardMarkup(keyboard)
                }
                if post.get('thumbnail'):
                    kwargs['thumbnail'] = post['thumbnail']
                sent_message = await context.bot.send_document(**kwargs)
            elif post["type"] == "text":
                sent_message = await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=post["content"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        
        # Sauvegarder les informations du nouveau message d'aperçu
        if sent_message:
            if 'preview_messages' not in context.user_data:
                context.user_data['preview_messages'] = {}
            context.user_data['preview_messages'][post_index] = {
                'message_id': sent_message.message_id,
                'chat_id': update.effective_chat.id
            }
    
    except Exception as e:
        logger.error(f"Erreur dans send_preview_file: {e}")

def main():
    try:
        # Configuration de l'application
        application = Application.builder().token(config.BOT_TOKEN).build()

        # Ajout de logs pour le démarrage
        logger.info("Initialisation de l'application...")

        # Initialisation des compteurs de réactions globaux
        application.bot_data['reaction_counts'] = {}

        # Initialisation du scheduler
        application.scheduler_manager = SchedulerManager(db_manager)
        application.scheduler_manager.start()
        logger.info("Scheduler démarré avec succès")

        # Log des états de conversation pour débogage
        logger.info(f"Définition des états de conversation:")
        logger.info(f"MAIN_MENU = {MAIN_MENU}")
        logger.info(f"POST_CONTENT = {POST_CONTENT}")
        logger.info(f"POST_ACTIONS = {POST_ACTIONS}")
        logger.info(f"WAITING_PUBLICATION_CONTENT = {WAITING_PUBLICATION_CONTENT}")
        logger.info(f"WAITING_REACTION_INPUT = {WAITING_REACTION_INPUT}")
        logger.info(f"WAITING_URL_INPUT = {WAITING_URL_INPUT}")

        # Initialisation du userbot Telethon
        userbot = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
        userbot.start()
        logger.info("Client Telethon démarré avec succès")
        application.bot_data['userbot'] = userbot

        # Define additional global handlers that work in all states
        global_handlers = [
            CallbackQueryHandler(handle_callback),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_content),
        ]

        # Définition du ConversationHandler avec les différents états
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", start),
                CommandHandler("create", create_publication),
                CommandHandler("settings", settings),
            ],
            states={
                MAIN_MENU: [
                    CallbackQueryHandler(handle_callback),
                    MessageHandler(filters.TEXT & ~filters.COMMAND & ~reply_keyboard_filter, handle_post_content),
                ],
                POST_CONTENT: [
                    MessageHandler(filters.Document.ALL, send_large_file),
                    MessageHandler(filters.PHOTO, send_large_file),
                    MessageHandler(filters.VIDEO, send_large_file),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_content),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_REACTION_INPUT: [
                    MessageHandler(filters.TEXT, handle_reaction_input),
                    CallbackQueryHandler(cancel_reactions, pattern="^cancel_reactions_"),
                    CallbackQueryHandler(select_emoji, pattern="^select_emoji_"),
                    CallbackQueryHandler(remove_emoji, pattern="^remove_emoji_"),
                    CallbackQueryHandler(finish_reactions, pattern="^finish_reactions_"),
                    CallbackQueryHandler(handle_callback)
                ],
                WAITING_URL_INPUT: [
                    MessageHandler(filters.TEXT, handle_url_input),
                    CallbackQueryHandler(cancel_url_button, pattern="^cancel_url_button_"),
                    CallbackQueryHandler(handle_callback)
                ],
                WAITING_CHANNEL_SELECTION: [
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_THUMBNAIL: [
                    MessageHandler(filters.PHOTO, handle_thumbnail_input),
                ],
                WAITING_CUSTOM_USERNAME: [
                    MessageHandler(filters.TEXT, handle_tag_input),
                ],
                WAITING_CHANNEL_INFO: [
                    MessageHandler(filters.TEXT, handle_channel_info),
                ],
                SETTINGS: [
                    CallbackQueryHandler(handle_callback),
                ],
                POST_ACTIONS: [
                    CallbackQueryHandler(handle_callback),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_content),
                ],
                WAITING_PUBLICATION_CONTENT: [
                    MessageHandler(filters.PHOTO, handle_content_after_channel_selection),
                    MessageHandler(filters.VIDEO, handle_content_after_channel_selection),
                    MessageHandler(filters.Document.ALL, handle_content_after_channel_selection),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_content_after_channel_selection),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_RENAME_INPUT: [
                    MessageHandler(filters.TEXT, handle_rename_input),
                    CallbackQueryHandler(handle_callback),
                ],
                # ... autres états ...
            },
            fallbacks=[
                CommandHandler("cancel", lambda update, context: MAIN_MENU),
                CommandHandler("start", start),
                CallbackQueryHandler(handle_callback),
            ],
            per_message=False,
            name="main_conversation",
            persistent=False,
            allow_reentry=True,
        )

        logger.info("ConversationHandler configuré avec états: %s",
                    ", ".join(str(state) for state in conv_handler.states.keys()))

        application.add_handler(conv_handler, group=0)  # Priorité maximale
        application.add_handler(CallbackQueryHandler(handle_reaction_click, pattern=r'^react_'), group=1)
        application.add_handler(MessageHandler(reply_keyboard_filter, handle_reply_keyboard), group=1)
        application.add_handler(CommandHandler("diagnostic", diagnostic))
        application.add_handler(CommandHandler("db_diagnostic", db_diagnostic))
        application.add_handler(CommandHandler("debug", debug_state))
        logger.info("Ajout du handler de callback global")
        application.add_error_handler(lambda update, context:
            logger.error(f"Erreur non gérée : {context.error}", exc_info=context.error))

        logger.info("Démarrage du bot...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot: {e}")
    finally:
        # Exécuter le nettoyage
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(cleanup(application))
        else:
            loop.run_until_complete(cleanup(application))

if __name__ == '__main__':
    main()