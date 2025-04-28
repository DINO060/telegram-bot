# Début du fichier bot.py
import os
import re
import logging
import asyncio
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, List, Dict
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from telethon import TelegramClient, events
from dotenv import load_dotenv
import pytz
from utils import (
    TimezoneManager,
    TimeInputValidator,
    MessageTemplates,
    KeyboardManager,
    PostEditingState
)
from telegram.error import TelegramError
from telethon.tl.types import InputPeerChannel
from telethon.errors import FloodWaitError
import time
from pathlib import Path
import shutil
import json
from config.settings import settings
from database.manager import DatabaseManager
from utils.message_utils import PostType, MessageError
from handlers.callback_handlers import handle_callback

load_dotenv()


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
        self.BOT_MAX_MEDIA_SIZE = 100 * 1024 * 1024  # 10 Mo
        self.USERBOT_MAX_MEDIA_SIZE = 2 * 1024 * 1024 * 1024  # 2 Go

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


# -----------------------------------------------------------------------------
# CONFIGURATION DU LOGGING
# -----------------------------------------------------------------------------
def setup_logging():
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    os.makedirs('logs', exist_ok=True)

    file_handler = logging.FileHandler('logs/uploader_bot.log')
    file_handler.setFormatter(log_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)

    logger = logging.getLogger('UploaderBot')
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Configuration globale
logger = setup_logging()
config = Config()


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
(
    MAIN_MENU,
    WAITING_CHANNEL_SELECTION,
    WAITING_PUBLICATION_CONTENT,
    POST_ACTIONS,
    SEND_OPTIONS,
    AUTO_DESTRUCTION,
    SCHEDULE_SEND,
    EDIT_POST,
    SCHEDULE_SELECT_CHANNEL,
    STATS_SELECT_CHANNEL,
    WAITING_CHANNEL_INFO,
    SETTINGS,
    WAITING_TIMEZONE,
    BACKUP_MENU,
    WAITING_NEW_TIME,  # Nouvel état pour la modification d'heure
) = range(15)

# Stockage des réactions
reaction_counts = {}


# -----------------------------------------------------------------------------
# GESTIONNAIRE DE BASE DE DONNÉES
# -----------------------------------------------------------------------------
class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.setup_database()

    def setup_database(self):
        """Initialisation de la base de données avec gestion des migrations"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Table de versionnage du schéma
                cursor.execute('''CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )''')

                # Vérification de la version actuelle
                cursor.execute('SELECT version FROM schema_version ORDER BY version DESC LIMIT 1')
                result = cursor.fetchone()
                current_version = result[0] if result else 0

                # Tables principales
                migrations = {
                    1: '''CREATE TABLE IF NOT EXISTS channels (
                            id INTEGER PRIMARY KEY, 
                            name TEXT NOT NULL, 
                            username TEXT NOT NULL UNIQUE
                        )''',
                    2: '''CREATE TABLE IF NOT EXISTS posts (
                            id INTEGER PRIMARY KEY, 
                            channel_id INTEGER, 
                            type TEXT NOT NULL, 
                            content TEXT NOT NULL, 
                            caption TEXT, 
                            buttons TEXT, 
                            scheduled_time TEXT,
                            message_id INTEGER,
                            FOREIGN KEY (channel_id) REFERENCES channels(id)
                        )''',
                    3: '''CREATE TABLE IF NOT EXISTS files (
                            id INTEGER PRIMARY KEY,
                            path TEXT NOT NULL,
                            upload_date TEXT NOT NULL
                        )''',
                    4: '''CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel_id)''',
                    5: '''CREATE INDEX IF NOT EXISTS idx_posts_scheduled ON posts(scheduled_time)''',
                    6: '''CREATE TABLE IF NOT EXISTS user_timezones (
                            user_id INTEGER PRIMARY KEY,
                            timezone TEXT NOT NULL
                        )'''
                }

                # Vérification et application des migrations
                for version, migration in migrations.items():
                    if version > current_version:
                        cursor.execute(migration)
                        cursor.execute('INSERT INTO schema_version (version) VALUES (?)', (version,))
                        logger.info(f"Migration {version} appliquée avec succès")

                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de l'initialisation de la base de données : {e}")
            raise

    def add_channel(self, name: str, username: str):
        """Ajoute un nouveau canal"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO channels (name, username) VALUES (?, ?)",
                    (name, username)
                )
                conn.commit()
                logger.info(f"Canal ajouté : {name} ({username})")
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de l'ajout du canal : {e}")
            raise

    def list_channels(self) -> List[tuple]:
        """Liste tous les canaux"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name, username FROM channels")
                return cursor.fetchall()
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération des canaux : {e}")
            return []

    def add_post(self, channel_id: int, post_type: str, content: str,
                 caption: Optional[str] = None, buttons: Optional[List[Dict]] = None,
                 scheduled_time: Optional[str] = None):
        """Ajoute un nouveau post"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO posts (channel_id, type, content, caption, buttons, scheduled_time) 
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (channel_id, post_type, content, caption,
                     str(buttons) if buttons else None,
                     scheduled_time)
                )
                conn.commit()
                logger.info(f"Post ajouté : type {post_type}, canal {channel_id}")
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de l'ajout du post : {e}")
            raise

    def save_user_timezone(self, user_id: int, timezone: str):
        """Sauvegarde le fuseau horaire d'un utilisateur"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO user_timezones (user_id, timezone) VALUES (?, ?)",
                    (user_id, timezone)
                )
                conn.commit()
                logger.info(f"Fuseau horaire sauvegardé pour l'utilisateur {user_id}: {timezone}")
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la sauvegarde du fuseau horaire : {e}")
            raise

    def get_user_timezone(self, user_id: int) -> Optional[str]:
        """Récupère le fuseau horaire d'un utilisateur"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT timezone FROM user_timezones WHERE user_id = ?", (user_id,))
                row = cursor.fetchone()
                return row[0] if row else None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération du fuseau horaire : {e}")
            return None

    def get_scheduled_post(self, post_id):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT p.id, p.type, p.content, p.caption, p.scheduled_time, c.name, c.username
                    FROM posts p
                    JOIN channels c ON p.channel_id = c.id
                    WHERE p.id = ?
                """, (post_id,))
                post = cursor.fetchone()
                if post:
                    return {
                        'id': post[0],
                        'type': post[1],
                        'content': post[2],
                        'caption': post[3],
                        'scheduled_time': post[4],
                        'buttons': post[5],
                        'channel_name': post[6],
                        'channel_username': post[7],
                        'scheduled_date': datetime.strptime(post[4], '%Y-%m-%d %H:%M:%S')
                    }
            return None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération du post planifié : {e}")
            return None


# Initialisation du gestionnaire de base de données
db_manager = DatabaseManager(config.DB_PATH)


# -----------------------------------------------------------------------------
# GESTIONNAIRE DE RESSOURCES
# -----------------------------------------------------------------------------
class ResourceManager:
    def __init__(self, download_folder, max_storage_mb=1000):
        self.download_folder = download_folder
        self.max_storage_mb = max_storage_mb
        self._cleanup_task = None

    async def cleanup_old_files(self, max_age_hours=24):
        """Nettoie les fichiers anciens de manière asynchrone."""
        try:
            if not os.path.exists(self.download_folder):
                return

            current_time = datetime.now()
            for filename in os.listdir(self.download_folder):
                file_path = os.path.join(self.download_folder, filename)
                if os.path.isfile(file_path):
                    file_age = current_time - datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_age.total_seconds() > max_age_hours * 3600:
                        try:
                            os.remove(file_path)
                            logger.info(f"Fichier supprimé : {filename}")
                        except Exception as e:
                            logger.error(f"Erreur lors de la suppression de {filename} : {e}")
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des fichiers : {e}")

    def check_storage_usage(self) -> bool:
        """Vérifie l'utilisation du stockage."""
        try:
            if not os.path.exists(self.download_folder):
                return True

            total_size = 0
            for filename in os.listdir(self.download_folder):
                file_path = os.path.join(self.download_folder, filename)
                if os.path.isfile(file_path):
                    total_size += os.path.getsize(file_path)

            total_size_mb = total_size / (1024 * 1024)
            return total_size_mb <= self.max_storage_mb
        except Exception as e:
            logger.error(f"Erreur lors de la vérification du stockage : {e}")
            return False

    async def start_cleanup_task(self):
        """Démarre la tâche de nettoyage périodique."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_cleanup_task(self):
        """Arrête la tâche de nettoyage périodique."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def _cleanup_loop(self):
        """Boucle de nettoyage périodique."""
        try:
            while True:
                await self.cleanup_old_files()
                await asyncio.sleep(3600)  # Nettoyage toutes les heures
        except asyncio.CancelledError:
            logger.info("Tâche de nettoyage arrêtée")
        except Exception as e:
            logger.error(f"Erreur dans la boucle de nettoyage : {e}")


# Initialisation du gestionnaire de ressources
resource_manager = ResourceManager(config.DOWNLOAD_FOLDER)


# -----------------------------------------------------------------------------
# GESTIONNAIRE DE PLANIFICATION
# -----------------------------------------------------------------------------
class SchedulerManager:
    def __init__(self, db_manager):
        self.scheduler = AsyncIOScheduler()
        self.db_manager = db_manager

    def start(self):
        self.scheduler.start()

        # Tâche de nettoyage quotidien des fichiers
        self.scheduler.add_job(
            resource_manager.cleanup_old_files,
            'interval',
            hours=24,
            id='cleanup_files'
        )

        # Tâche de sauvegarde quotidienne de la base de données
        self.scheduler.add_job(
            self._create_database_backup,
            'cron',
            hour=3,  # 3h du matin
            id='daily_backup'
        )

        # Restauration des tâches planifiées
        self.restore_scheduled_tasks()

    def stop(self):
        self.scheduler.shutdown()

    def _create_database_backup(self):
        backup_dir = 'backups'
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'bot_backup_{timestamp}.db')

        try:
            with sqlite3.connect(config.DB_PATH) as source_conn:
                with sqlite3.connect(backup_path) as backup_conn:
                    source_conn.backup(backup_conn)

            logger.info(f"Backup de la base de données créé : {backup_path}")

            # Nettoyer les vieux backups (garder les 5 derniers)
            self._cleanup_old_backups(backup_dir)
        except Exception as e:
            logger.error(f"Erreur lors de la création du backup : {e}")

    def _cleanup_old_backups(self, backup_dir, keep_count=5):
        try:
            backup_files = [f for f in os.listdir(backup_dir) if f.startswith('bot_backup_')]
            backup_files.sort(reverse=True)

            for old_backup in backup_files[keep_count:]:
                os.remove(os.path.join(backup_dir, old_backup))
                logger.info(f"Ancien backup supprimé : {old_backup}")
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des backups : {e}")

    def restore_from_backup(self, backup_file):
        try:
            backup_path = os.path.join('backups', backup_file)
            if not os.path.exists(backup_path):
                logger.error(f"Fichier de backup non trouvé : {backup_path}")
                return False

            temp_backup = f"{config.DB_PATH}.temp"
            with sqlite3.connect(config.DB_PATH) as current_db:
                with sqlite3.connect(temp_backup) as temp_db:
                    current_db.backup(temp_db)

            try:
                with sqlite3.connect(backup_path) as backup_conn:
                    with sqlite3.connect(config.DB_PATH) as target_conn:
                        backup_conn.backup(target_conn)

                os.remove(temp_backup)
                logger.info(f"Base de données restaurée depuis : {backup_file}")
                return True

            except Exception as restore_error:
                logger.error(f"Erreur lors de la restauration : {restore_error}")
                with sqlite3.connect(temp_backup) as temp_db:
                    with sqlite3.connect(config.DB_PATH) as current_db:
                        temp_db.backup(current_db)
                os.remove(temp_backup)
                return False

        except Exception as e:
            logger.error(f"Erreur lors de la restauration du backup : {e}")
            return False

    def restore_scheduled_tasks(self):
        try:
            with sqlite3.connect(config.DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, channel_id, type, content, caption, buttons, scheduled_time 
                    FROM posts 
                    WHERE scheduled_time > datetime('now')
                ''')
                scheduled_posts = cursor.fetchall()

                for post in scheduled_posts:
                    scheduled_time = datetime.strptime(post[6], '%Y-%m-%d %H:%M:%S')
                    self.scheduler.add_job(
                        self._execute_scheduled_post,
                        'date',
                        run_date=scheduled_time,
                        args=[post],
                        id=f'post_{post[0]}'
                    )
                    logger.info(f"Tâche restaurée pour le post {post[0]}")
        except Exception as e:
            logger.error(f"Erreur lors de la restauration des tâches : {e}")

    async def _execute_scheduled_post(self, post_data):
        logger.info(f"Exécution du post planifié : {post_data[0]}")


# Initialisation du gestionnaire de planification
scheduler_manager = SchedulerManager(db_manager)


# -----------------------------------------------------------------------------
# VALIDATION DES ENTRÉES
# -----------------------------------------------------------------------------
class InputValidator:
    @staticmethod
    def validate_url(url: str) -> bool:
        url_pattern = r'https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)'
        return bool(re.match(url_pattern, url))

    @staticmethod
    def validate_channel_name(name: str) -> bool:
        return bool(re.match(r'^@?[a-zA-Z0-9_]{5,32}$', name))

    @staticmethod
    def sanitize_text(text: str) -> str:
        return text.replace('<', '&lt;').replace('>', '&gt;')


# -----------------------------------------------------------------------------
# CRÉATION DU CLIENT TELETHON
# -----------------------------------------------------------------------------
userbot = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)


@userbot.on(events.NewMessage)
async def handle_userbot_file(event):
    """Gère les fichiers reçus via le userbot"""
    # Ignorer les messages envoyés par le userbot lui-même
    if event.out:
        return

    if event.media:
        try:
            if not resource_manager.check_storage_usage():
                logger.warning("Espace de stockage insuffisant")
                return

            # Tentative de téléchargement silencieuse
            file_path = await event.message.download_media(file=config.DOWNLOAD_FOLDER)

            if not file_path or not os.path.exists(file_path):
                logger.error("Échec du téléchargement du fichier")
                return

            # Enregistrement en base de données silencieux
            try:
                with sqlite3.connect(config.DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO files (path, upload_date) VALUES (?, ?)",
                        (file_path, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                    )
                    conn.commit()
                    logger.info(f"Fichier enregistré : {file_path}")
            except sqlite3.Error as db_error:
                logger.error(f"Erreur base de données : {db_error}")
                return

        except Exception as e:
            logger.error(f"Erreur dans handle_userbot_file : {e}")
            return


async def send_large_file(update: Update, context):
    try:
        user_id = update.message.chat_id
        file_path = os.path.join(config.DOWNLOAD_FOLDER, "video.mp4")

        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            if file_size > config.USERBOT_MAX_MEDIA_SIZE:
                await update.message.reply_text("❌ Fichier trop volumineux!")
                return

            await retry_operation(
                lambda: userbot.send_file(user_id, file_path, caption="📤 Voici votre fichier!")
            )
        else:
            await update.message.reply_text("❌ Fichier non trouvé!")
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du fichier : {e}")
        await update.message.reply_text("❌ Erreur lors de l'envoi")


# -----------------------------------------------------------------------------
# FONCTIONS DE GESTION DES POSTS ET RÉACTIONS
# -----------------------------------------------------------------------------
async def start(update: Update, context):
    """Point d'entrée principal du bot"""
    keyboard = [
        [InlineKeyboardButton("📝 Nouvelle publication", callback_data="create_publication")],
        [InlineKeyboardButton("📅 Publications planifiées", callback_data="planifier_post")],
        [InlineKeyboardButton("✏️ Modifier une publication", callback_data="edit_post")],
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


# Ajoutez ces fonctions dans cet ordre après la fonction start() et avant send_post_now()

async def create_publication(update: Update, context):
    """Affiche la liste des canaux disponibles pour créer une publication"""
    try:
        # Récupération des canaux depuis la base de données
        channels = db_manager.list_channels()

        # Construction du clavier avec 2 canaux par ligne
        keyboard = []
        current_row = []

        for i, (name, username) in enumerate(channels):
            # Ajoute un bouton pour chaque canal avec callback data contenant l'username
            current_row.append(InlineKeyboardButton(
                name,
                callback_data=f"select_channel_{username}"
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
            InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
        ])

        message_text = (
            "📝 Sélectionnez un canal pour votre publication :\n\n"
            "• Choisissez un canal existant, ou\n"
            "• Ajoutez un nouveau canal"
        )

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

        return WAITING_CHANNEL_SELECTION

    except Exception as e:
        logger.error(f"Erreur lors de l'affichage des canaux: {e}")

        # Message d'erreur avec bouton de retour
        keyboard = [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]
        error_message = "❌ Une erreur est survenue lors de la récupération des canaux."

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

        return MAIN_MENU


async def handle_channel_selection(update: Update, context):
    """Gère la sélection d'un canal et prépare la réception du contenu"""
    query = update.callback_query
    await query.answer()

    try:
        # Extraction du nom d'utilisateur du canal depuis callback_data
        _, _, channel_username = query.data.partition('_channel_')

        # Récupération du nom du canal depuis la base de données
        channels = db_manager.list_channels()
        channel_name = next((name for name, username in channels if username == channel_username), channel_username)

        # Stockage du canal sélectionné dans le contexte utilisateur
        context.user_data['selected_channel'] = {
            'username': channel_username,
            'name': channel_name
        }

        # Message de confirmation
        await query.edit_message_text(
            f"✅ Canal sélectionné : {channel_name}\n\n"
            f"Envoyez-moi le contenu que vous souhaitez publier (texte, photo, vidéo ou document)."
        )

        return WAITING_PUBLICATION_CONTENT

    except Exception as e:
        logger.error(f"Erreur lors de la sélection du canal: {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de la sélection du canal.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Retour", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def handle_post_content(update: Update, context):
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
                "content": InputValidator.sanitize_text(message.text)
            })
        else:
            await message.reply_text("❌ Type de contenu non pris en charge.")
            return WAITING_PUBLICATION_CONTENT

        # Ajouter le post à la liste
        context.user_data['posts'].append(post_data)
        post_index = len(context.user_data['posts']) - 1

        # Créer le clavier avec les boutons d'action
        keyboard = []

        # Ajouter le bouton des réactions seulement s'il n'y en a pas déjà
        if not post_data.get('reactions'):
            keyboard.append(
                [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")])

        keyboard.extend([
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
        ])

        # Envoyer l'aperçu avec les boutons
        try:
            sent_message = None
            if post_data["type"] == "photo":
                sent_message = await context.bot.send_photo(
                    chat_id=message.chat_id,
                    photo=post_data["content"],
                    caption=post_data["caption"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post_data["type"] == "video":
                sent_message = await context.bot.send_video(
                    chat_id=message.chat_id,
                    video=post_data["content"],
                    caption=post_data["caption"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif post_data["type"] == "document":
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
                f"✅ Fichier ajouté ! Il vous reste {remaining_files} fichiers disponibles dans ce post.\n"
                "Vous pouvez continuer à m'envoyer des fichiers pour ce post ou utiliser le bouton 'Envoyer' du menu quand vous avez terminé."
            )

        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du message: {e}")
            await message.reply_text("❌ Erreur lors de l'envoi du message.")
            return WAITING_PUBLICATION_CONTENT

        return WAITING_PUBLICATION_CONTENT

    except Exception as e:
        logger.error(f"Erreur dans handle_post_content: {e}")
        await message.reply_text("❌ Une erreur est survenue lors du traitement de votre post.")
        return WAITING_PUBLICATION_CONTENT


async def handle_post_actions_text(update: Update, context):
    """Gère les entrées textuelles dans l'état POST_ACTIONS"""
    try:
        # Vérifier si on attend des réactions
        if context.user_data.get('waiting_for_reactions'):
            return await handle_reaction_input(update, context)

        # Vérifier si on attend une URL
        if context.user_data.get('waiting_for_url'):
            return await handle_url_input(update, context)

        # Si aucun état d'attente spécifique, traiter comme contenu du post
        return await handle_post_content(update, context)

    except Exception as e:
        logger.error(f"Erreur dans handle_post_actions_text: {e}")
        await update.message.reply_text("❌ Une erreur est survenue lors du traitement de votre message.")
        return MAIN_MENU


async def remove_reactions(update: Update, context):
    """Supprime les réactions du post"""
    try:
        query = update.callback_query
        await query.answer()

        # Récupérer le post du contexte
        post = context.user_data.get('post', {})

        # Supprimer les réactions
        post['reactions'] = []

        # Construire le nouveau clavier
        keyboard = []

        # Ajouter les boutons URL existants s'il y en a
        if post.get('buttons'):
            for btn in post['buttons']:
                keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])

        # Ajouter les boutons d'action
        keyboard.extend([
            [InlineKeyboardButton("➕ Ajouter des réactions", callback_data="add_reactions")],
            [InlineKeyboardButton(
                "🔗 Ajouter un bouton URL" if not post.get('buttons') else "Supprimer boutons pour lien URL",
                callback_data="add_url_button" if not post.get('buttons') else "remove_url_buttons")],
            [InlineKeyboardButton("❌ Supprimer", callback_data="delete_post")]
        ])

        # Mettre à jour le message avec le nouveau clavier
        if post["type"] == "photo":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        elif post["type"] == "video":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        elif post["type"] == "document":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.message.edit_text(
                text=post.get("content", ""),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur lors de la suppression des réactions : {e}")
        await query.edit_message_text(
            "❌ Erreur lors de la suppression des réactions.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def remove_url_buttons(update: Update, context):
    """Supprime les boutons URL du post"""
    try:
        query = update.callback_query
        await query.answer()

        # Récupérer le post du contexte
        post = context.user_data.get('post', {})

        # Supprimer les boutons URL
        post['buttons'] = []

        # Construire le nouveau clavier
        keyboard = []

        # Ajouter les réactions existantes s'il y en a
        if post.get('reactions'):
            current_row = []
            for reaction in post['reactions']:
                current_row.append(InlineKeyboardButton(
                    f"{reaction}",
                    callback_data=f"react_0_{reaction}"
                ))
                if len(current_row) == 4:
                    keyboard.append(current_row)
                    current_row = []
            if current_row:
                keyboard.append(current_row)

        # Ajouter les boutons d'action
        keyboard.extend([
            [InlineKeyboardButton("Supprimer les réactions" if post.get('reactions') else "➕ Ajouter des réactions",
                                  callback_data="remove_reactions" if post.get('reactions') else "add_reactions")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data="add_url_button")],
            [InlineKeyboardButton("❌ Supprimer", callback_data="delete_post")]
        ])

        # Mettre à jour le message avec le nouveau clavier
        if post["type"] == "photo":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        elif post["type"] == "video":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        elif post["type"] == "document":
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.message.edit_text(
                text=post.get("content", ""),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur lors de la suppression des boutons URL : {e}")
        await query.edit_message_text(
            "❌ Erreur lors de la suppression des boutons URL.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def safe_edit_message_text(query, text, reply_markup=None):
    """Fonction utilitaire pour éditer le message de manière sécurisée"""
    try:
        if query.message.text:
            await query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await query.message.edit_reply_markup(reply_markup=reply_markup)
            await query.message.reply_text(text)
    except Exception as e:
        logger.error(f"Erreur dans safe_edit_message_text : {e}")


async def add_reactions_to_post(update: Update, context):
    """Interface pour ajouter des réactions au post"""
    try:
        query = update.callback_query
        await query.answer()

        # Extraire l'index du post depuis le callback_data
        post_index = int(query.data.split('_')[-1])

        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
            )
            return MAIN_MENU

        # Stockage de l'état d'attente dans le contexte utilisateur
        context.user_data['waiting_for_reactions'] = True
        context.user_data['current_post_index'] = post_index
        context.user_data['current_state'] = POST_ACTIONS

        keyboard = [
            [InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_reactions_{post_index}")]
        ]

        # Vérifier si le message contient un média
        message = query.message
        if message.photo or message.video or message.document:
            # Pour les messages avec média, on envoie un nouveau message
            await context.bot.send_message(
                chat_id=message.chat_id,
                text="Envoyez-moi les réactions que vous souhaitez ajouter, séparées par des /.\n\n"
                     "Vous pouvez utiliser des émojis ou du texte. Par exemple:\n"
                     "✅/🔥/Wow/Super/👍❤️\n\n"
                     "Les réactions apparaîtront comme des boutons sous votre message.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Pour les messages texte, on peut modifier le message existant
            await query.edit_message_text(
                "Envoyez-moi les réactions que vous souhaitez ajouter, séparées par des /.\n\n"
                "Vous pouvez utiliser des émojis ou du texte. Par exemple:\n"
                "✅/🔥/Wow/Super/👍/❤️\n\n"
                "Les réactions apparaîtront comme des boutons sous votre message.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur lors de l'ajout des réactions : {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Erreur lors de l'ajout des réactions.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
        )
        return POST_ACTIONS


async def add_url_button_to_post(update: Update, context):
    """Ajoute un bouton URL au post"""
    try:
        query = update.callback_query
        await query.answer()

        # Extraire l'index du post depuis le callback_data
        post_index = int(query.data.split('_')[-1])

        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
            )
            return MAIN_MENU

        # Stockage de l'état d'attente dans le contexte utilisateur
        context.user_data['waiting_for_url'] = True
        context.user_data['current_post_index'] = post_index
        context.user_data['current_state'] = POST_ACTIONS

        keyboard = [
            [InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_url_button_{post_index}")]
        ]

        # Vérifier si le message contient un média
        message = query.message
        if message.photo or message.video or message.document:
            # Pour les messages avec média, on envoie un nouveau message
            await context.bot.send_message(
                chat_id=message.chat_id,
                text="Envoyez-moi le texte et l'URL du bouton au format:\n"
                     "Texte du bouton | https://votre-url.com\n\n"
                     "Par exemple:\n"
                     "📺 Regarder l'épisode | https://example.com/watch",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Pour les messages texte, on peut modifier le message existant
            await query.edit_message_text(
                "Envoyez-moi le texte et l'URL du bouton au format:\n"
                "Texte du bouton | https://votre-url.com\n\n"
                "Par exemple:\n"
                "📺 Regarder l'épisode | https://example.com/watch",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur lors de l'ajout du bouton URL : {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Erreur lors de l'ajout du bouton URL.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
        )
        return POST_ACTIONS


async def handle_reaction_input(update: Update, context):
    """Gère l'input des réactions"""
    if 'waiting_for_reactions' not in context.user_data or 'current_post_index' not in context.user_data:
        return WAITING_PUBLICATION_CONTENT

    try:
        post_index = context.user_data['current_post_index']
        text = update.message.text
        reactions = [r.strip() for r in text.split('/') if r.strip()]

        if len(reactions) > 8:
            reactions = reactions[:8]
            await update.message.reply_text("⚠️ Maximum 8 réactions permises. Seules les 8 premières ont été gardées.")

        if not reactions:
            await update.message.reply_text(
                "❌ Aucune réaction valide détectée. Veuillez réessayer.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
            )
            return WAITING_PUBLICATION_CONTENT

        # Mise à jour du post dans le contexte
        context.user_data['posts'][post_index]['reactions'] = reactions

        # Construction du nouveau clavier
        keyboard = []

        # Ajout des réactions
        current_row = []
        for reaction in reactions:
            current_row.append(InlineKeyboardButton(
                f"{reaction}",
                callback_data=f"react_{post_index}_{reaction}"
            ))
            if len(current_row) == 4:
                keyboard.append(current_row)
                current_row = []
        if current_row:
            keyboard.append(current_row)

        # Ajout des boutons URL existants
        if context.user_data['posts'][post_index].get('buttons'):
            for btn in context.user_data['posts'][post_index]['buttons']:
                keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])

        # Ajout des boutons d'action
        keyboard.extend([
            [InlineKeyboardButton("Supprimer les réactions", callback_data=f"remove_reactions_{post_index}")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
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

        # Envoi du nouveau message avec les réactions
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
            "✅ Réactions ajoutées avec succès !\n"
            "Vous pouvez continuer à m'envoyer des messages."
        )

        # Nettoyage du contexte
        del context.user_data['waiting_for_reactions']
        del context.user_data['current_post_index']
        return WAITING_PUBLICATION_CONTENT

    except Exception as e:
        logger.error(f"Erreur lors du traitement des réactions : {e}")
        await update.message.reply_text(
            "❌ Erreur lors du traitement des réactions.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return WAITING_PUBLICATION_CONTENT


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
            [InlineKeyboardButton("➕ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
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


async def planifier_post(update: Update, context):
    """Affiche les publications planifiées par chaîne."""
    try:
        # Récupérer tous les posts planifiés futurs
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.id, p.type, p.content, p.caption, p.scheduled_time, c.name, c.username
                FROM posts p
                JOIN channels c ON p.channel_id = c.id
                WHERE p.scheduled_time > datetime('now')
                ORDER BY p.scheduled_time
            """)
            scheduled_posts = cursor.fetchall()

        if not scheduled_posts:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    "❌ Aucun post planifié trouvé.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )
            else:
                await update.message.reply_text("❌ Aucun post planifié trouvé.")
            return MAIN_MENU

        # Créer le clavier avec les posts planifiés
        keyboard = []

        # Récupérer le fuseau horaire de l'utilisateur
        user_id = update.effective_user.id
        user_timezone = db_manager.get_user_timezone(user_id) or "UTC"
        local_tz = pytz.timezone(user_timezone)

        # Message de résumé
        message = "📅 Publications planifiées :\n\n"

        # Ajouter un bouton pour chaque post
        for post in scheduled_posts:
            post_id, post_type, content, caption, scheduled_time, channel_name, channel_username = post

            # Convertir l'heure UTC en heure locale
            scheduled_datetime = datetime.strptime(scheduled_time, '%Y-%m-%d %H:%M:%S')
            local_time = scheduled_datetime.replace(tzinfo=pytz.UTC).astimezone(local_tz)

            # Créer le texte du bouton
            button_text = f"{local_time.strftime('%d/%m/%Y %H:%M')} - {channel_name} (@{channel_username})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"show_post_{post_id}")])

            # Ajouter au message
            message += f"• {button_text}\n"

        # Ajouter le bouton de retour
        keyboard.append([InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")])

        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return SCHEDULE_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Erreur dans planifier_post : {e}")
        error_message = "❌ Une erreur est survenue lors de l'affichage des publications planifiées."
        if update.callback_query:
            await update.callback_query.edit_message_text(
                error_message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
        else:
            await update.message.reply_text(error_message)
        return MAIN_MENU


async def handle_scheduled_channel(update: Update, context):
    """Affiche les posts planifiés d'une chaîne."""
    query = update.callback_query
    await query.answer()
    username = query.data.replace("scheduled_", "")

    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.id, p.type, p.content, p.caption, p.scheduled_time, c.username
                FROM posts p
                JOIN channels c ON p.channel_id = c.id
                WHERE p.scheduled_time > datetime('now') AND c.username = ?
                ORDER BY p.scheduled_time
            """, (username,))
            posts = cursor.fetchall()

        if not posts:
            await query.edit_message_text("❌ Aucun post planifié pour cette chaîne.")
            return SCHEDULE_SELECT_CHANNEL

        context.user_data['scheduled_posts'] = {str(post[0]): post for post in posts}

        keyboard = [[InlineKeyboardButton(
            f"{datetime.strptime(post[4], '%Y-%m-%d %H:%M:%S').strftime('%b %d, %H:%M %p')} ({post[1]})",
            callback_data=f"show_post_{post[0]}")]
            for post in posts]
        keyboard.append([InlineKeyboardButton("« Retour", callback_data="planifier_post")])

        await query.edit_message_text(
            "Choisissez une publication planifiée que vous souhaitez afficher ou supprimer.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return STATS_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Erreur dans handle_scheduled_channel : {e}")
        await query.edit_message_text("❌ Erreur lors de l'affichage des posts de cette chaîne.")
        return MAIN_MENU


async def show_scheduled_post(update: Update, context):
    """Affiche les détails d'une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        logger.info("Début de show_scheduled_post")
        logger.debug(f"Callback data reçu : {query.data}")

        # Extraire l'ID du post
        post_id = query.data.split('_')[-1]
        logger.debug(f"Post ID extrait : {post_id}")

        # Récupérer le post de la base de données
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.id, p.type, p.content, p.caption, p.scheduled_time, c.name, c.username
                FROM posts p
                JOIN channels c ON p.channel_id = c.id
                WHERE p.id = ?
            """, (post_id,))
            post_data = cursor.fetchone()

        if not post_data:
            logger.warning(f"Post {post_id} non trouvé")
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Convertir la date planifiée
        scheduled_time = datetime.strptime(post_data[4], '%Y-%m-%d %H:%M:%S')

        # Créer le dictionnaire du post
        post = {
            'id': post_data[0],
            'type': post_data[1],
            'content': post_data[2],
            'caption': post_data[3],
            'scheduled_time': post_data[4],
            'channel_name': post_data[5],
            'channel_username': post_data[6],
            'scheduled_date': scheduled_time
        }

        # Stocker le post dans le contexte
        context.user_data['current_scheduled_post'] = post

        # Construire le clavier avec les boutons d'action
        keyboard = [
            [InlineKeyboardButton("🕒 Modifier l'heure", callback_data="modifier_heure")],
            [InlineKeyboardButton("🚀 Envoyer maintenant", callback_data="envoyer_maintenant")],
            [InlineKeyboardButton("❌ Annuler la publication", callback_data="annuler_publication")],
            [InlineKeyboardButton("↩️ Retour", callback_data="retour")]
        ]

        # Envoyer d'abord le contenu du post
        try:
            if post['type'] == "photo":
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=post['content'],
                    caption=post.get('caption'),
                    reply_markup=None
                )
            elif post['type'] == "video":
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=post['content'],
                    caption=post.get('caption'),
                    reply_markup=None
                )
            elif post['type'] == "document":
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=post['content'],
                    caption=post.get('caption'),
                    reply_markup=None
                )
            elif post['type'] == "text":
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=post['content'],
                    reply_markup=None
                )
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du contenu : {e}")
            # Continue même si l'envoi du contenu échoue

        # Formater le message avec les détails
        message = (
            f"📝 Publication planifiée :\n\n"
            f"📅 Date : {scheduled_time.strftime('%d/%m/%Y')}\n"
            f"⏰ Heure : {scheduled_time.strftime('%H:%M')}\n"
            f"📍 Canal : {post['channel_name']}\n"
            f"📎 Type : {post['type']}\n"
        )

        # Envoyer le message avec les boutons
        await query.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        return SCHEDULE_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Erreur dans show_scheduled_post : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de l'affichage de la publication.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_reply_keyboard(update: Update, context):
    """Gère les interactions avec le clavier de réponse"""
    try:
        user_text = update.message.text.strip().lower()
        logger.info(f"handle_reply_keyboard: reçu '{user_text}'")

        if user_text == "envoyer":
            logger.info("Commande Envoyer reçue")

            # Vérifier si nous avons des posts à envoyer
            posts = context.user_data.get("posts", [])
            if not posts:
                await update.message.reply_text(
                    "❌ Aucun fichier à envoyer. Veuillez d'abord ajouter des fichiers."
                )
                return WAITING_PUBLICATION_CONTENT

            # Vérifier si un canal est sélectionné
            channel = posts[0].get("channel", config.DEFAULT_CHANNEL)

            # Créer le clavier inline avec les trois options
            keyboard = [
                [InlineKeyboardButton("⏰ Régler temps d'auto destruction", callback_data="auto_destruction")],
                [InlineKeyboardButton("➡️ Maintenant", callback_data="send_post")],
                [InlineKeyboardButton("📅 Planifier", callback_data="schedule_send")],
                [InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]
            ]

            await update.message.reply_text(
                f"Vos {len(posts)} fichiers sont prêts à être envoyés à {channel}.\n"
                "Quand souhaitez-vous les envoyer ?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SEND_OPTIONS

        elif user_text == "aperçu":
            await handle_preview(update, context)
            return WAITING_PUBLICATION_CONTENT

        elif user_text == "annuler":
            # Nettoyage du contexte
            context.user_data.clear()
            await update.message.reply_text(
                "Publication annulée. Retour au menu principal.\n"
                "Vous pouvez commencer une nouvelle publication quand vous voulez."
            )
            return await start(update, context)

        elif user_text == "tout supprimer":
            # Suppression de tous les messages d'aperçu
            if 'preview_messages' in context.user_data:
                for preview_info in context.user_data['preview_messages'].values():
                    try:
                        await context.bot.delete_message(
                            chat_id=preview_info['chat_id'],
                            message_id=preview_info['message_id']
                        )
                    except Exception:
                        pass

            # Nettoyage du contexte
            context.user_data.clear()
            await update.message.reply_text(
                "✅ Tous les fichiers ont été supprimés.\n"
                "Vous pouvez commencer une nouvelle publication."
            )
            return await start(update, context)

        else:
            # Si le texte n'est pas une commande du clavier, le traiter comme un contenu de post
            return await handle_post_content(update, context)

        return WAITING_PUBLICATION_CONTENT

    except Exception as e:
        logger.error(f"Erreur dans handle_reply_keyboard : {e}")
        await update.message.reply_text("❌ Une erreur est survenue. Retour au menu principal.")
        return await start(update, context)


async def handle_auto_destruction(update: Update, context):
    """Gère la configuration de l'auto-destruction"""
    try:
        query = update.callback_query
        hours = int(query.data.split('_')[1].replace('h', ''))

        # Envoyer d'abord le message
        send_result = await send_post_now(update, context)

        if send_result == MAIN_MENU:
            # Récupérer le message envoyé
            post = context.user_data.get('post', {})

            # Planifier la suppression
            deletion_time = datetime.now() + timedelta(hours=hours)
            scheduler_manager.scheduler.add_job(
                context.bot.delete_message,
                'date',
                run_date=deletion_time,
                args=[post.get('channel'), post.get('message_id')],
                id=f"delete_{post.get('message_id')}"
            )

            await query.edit_message_text(
                f"✅ Message envoyé et sera supprimé dans {hours} heures",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
            )

        return MAIN_MENU

    except Exception as e:
        logger.error(f"Erreur lors de la gestion de l'auto-destruction : {e}")
        await query.edit_message_text(
            "❌ Erreur lors de la configuration de l'auto-destruction.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def schedule_send(update: Update, context):
    """Interface de planification des messages"""
    try:
        query = update.callback_query
        await query.answer()

        # Récupérer le jour sélectionné s'il existe
        selected_day = context.user_data.get('schedule_day', None)

        # Créer les boutons avec les emojis appropriés
        keyboard = [
            [
                InlineKeyboardButton(
                    f"Aujourd'hui {'✅' if selected_day == 'today' else ''}",
                    callback_data="schedule_today"
                ),
                InlineKeyboardButton(
                    f"Demain {'✅' if selected_day == 'tomorrow' else ''}",
                    callback_data="schedule_tomorrow"
                ),
            ],
            [InlineKeyboardButton("↩️ Retour", callback_data="send_post")],
        ]

        # Construction du message
        day_status = "✅ Jour sélectionné : " + (
            "Aujourd'hui" if selected_day == "today" else "Demain") if selected_day else "❌ Aucun jour sélectionné"

        message_text = (
            "📅 Choisissez quand envoyer votre publication :\n\n"
            "1️⃣ Sélectionnez le jour (Aujourd'hui ou Demain)\n"
            "2️⃣ Envoyez-moi l'heure au format :\n"
            "   • '15:30' ou '1530' (24h)\n"
            "   • '6' (06:00)\n"
            "   • '5 3' (05:03)\n\n"
            f"{day_status}"
        )

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return SCHEDULE_SEND
    except Exception as e:
        logger.error(f"Erreur lors de la planification de l'envoi : {e}")
        await query.edit_message_text(
            "❌ Erreur lors de la planification.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def auto_destruction(update: Update, context):
    """Configuration de l'auto-destruction des messages"""
    try:
        query = update.callback_query
        keyboard = [
            [
                InlineKeyboardButton("1h", callback_data="destroy_1h"),
                InlineKeyboardButton("3h", callback_data="destroy_3h"),
                InlineKeyboardButton("6h", callback_data="destroy_6h"),
            ],
            [
                InlineKeyboardButton("12h", callback_data="destroy_12h"),
                InlineKeyboardButton("24h", callback_data="destroy_24h"),
                InlineKeyboardButton("48h", callback_data="destroy_48h"),
            ],
            [InlineKeyboardButton("↩️ Retour", callback_data="send_post")],
        ]
        await query.edit_message_text(
            "⏰ Après combien de temps le message doit-il s'auto-détruire ?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return AUTO_DESTRUCTION
    except Exception as e:
        logger.error(f"Erreur lors de la configuration de l'auto-destruction : {e}")
        await query.edit_message_text(
            "❌ Erreur lors de la configuration.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def handle_schedule_time(update: Update, context):
    """Gère l'entrée de l'heure pour la planification ou la modification."""
    try:
        # Gestion des callbacks pour la sélection du jour
        if update.callback_query:
            query = update.callback_query
            data = query.data

            if data in ["schedule_today", "schedule_tomorrow"]:
                # Stocker le jour sélectionné
                context.user_data['schedule_day'] = 'today' if data == "schedule_today" else 'tomorrow'
                jour = "Aujourd'hui" if context.user_data['schedule_day'] == 'today' else "Demain"

                # Mise à jour du message pour indiquer que l'heure est attendue
                await query.edit_message_text(
                    f"✅ Jour sélectionné : {jour}.\n\n"
                    "Envoyez-moi maintenant l'heure au format :\n"
                    "   • '15:30' ou '1530' (24h)\n"
                    "   • '6' (06:00)\n"
                    "   • '5 3' (05:03)",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="retour")
                    ]])
                )
                return WAITING_NEW_TIME

            await query.answer()
            return SCHEDULE_SEND

        # Gestion de l'entrée de l'heure
        if not update.message or not update.message.text:
            return WAITING_NEW_TIME

        # Vérifier si on a un jour sélectionné
        if 'schedule_day' not in context.user_data:
            await update.message.reply_text(
                "❌ Veuillez d'abord sélectionner un jour (Aujourd'hui ou Demain).",
                reply_markup=KeyboardManager.get_time_selection_keyboard()
            )
            return SCHEDULE_SEND

        # Traitement de l'heure entrée
        time_text = update.message.text.strip()
        try:
            # Convertir différents formats d'heure
            if ':' in time_text:
                hour, minute = map(int, time_text.split(':'))
            elif ' ' in time_text:
                hour, minute = map(int, time_text.split())
            else:
                if len(time_text) <= 2:  # Format simple (ex: "6")
                    hour = int(time_text)
                    minute = 0
                else:  # Format condensé (ex: "1530")
                    hour = int(time_text[:-2])
                    minute = int(time_text[-2:])

            # Validation de l'heure
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Heure invalide")

            # Récupérer le fuseau horaire de l'utilisateur
            user_id = update.effective_user.id
            user_timezone = db_manager.get_user_timezone(user_id) or "UTC"
            local_tz = pytz.timezone(user_timezone)

            # Calculer la date cible
            target_date = datetime.now(local_tz)
            if context.user_data['schedule_day'] == 'tomorrow':
                target_date += timedelta(days=1)

            target_date = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            utc_date = target_date.astimezone(pytz.UTC)

            # Vérifier que l'heure n'est pas déjà passée
            if utc_date <= datetime.now(pytz.UTC):
                await update.message.reply_text(
                    "❌ Cette heure est déjà passée. Veuillez choisir une heure future.",
                    reply_markup=KeyboardManager.get_time_selection_keyboard()
                )
                return SCHEDULE_SEND

            # Si nous modifions un post existant
            if 'editing_post_id' in context.user_data:
                post_id = context.user_data['editing_post_id']

                # Mettre à jour la base de données
                with sqlite3.connect(config.DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE posts SET scheduled_time = ? WHERE id = ?",
                        (utc_date.strftime('%Y-%m-%d %H:%M:%S'), post_id)
                    )
                    conn.commit()

                # Mettre à jour le scheduler
                job_id = f"post_{post_id}"
                if scheduler_manager.scheduler.get_job(job_id):
                    scheduler_manager.scheduler.remove_job(job_id)

                # Créer une nouvelle tâche planifiée
                async def scheduled_task():
                    try:
                        # Récupérer le post à jour depuis la base de données
                        with sqlite3.connect(config.DB_PATH) as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                SELECT p.id, p.type, p.content, p.caption, p.scheduled_time, c.name, c.username
                                FROM posts p
                                JOIN channels c ON p.channel_id = c.id
                                WHERE p.id = ?
                            """, (post_id,))
                            post_data = cursor.fetchone()

                            if post_data:
                                current_post = {
                                    'id': post_data[0],
                                    'type': post_data[1],
                                    'content': post_data[2],
                                    'caption': post_data[3],
                                    'scheduled_time': post_data[4],
                                    'channel_name': post_data[5],
                                    'channel_username': post_data[6]
                                }
                                await send_post_now(update, context, current_post)
                    except Exception as e:
                        logger.error(f"Erreur dans la tâche planifiée : {e}")

                scheduler_manager.scheduler.add_job(
                    scheduled_task,
                    'date',
                    run_date=utc_date,
                    id=job_id
                )

                # Message de confirmation
                formatted_time = TimezoneManager.format_time_for_user(target_date, user_timezone)
                await update.message.reply_text(
                    f"✅ Publication replanifiée pour {formatted_time} ({user_timezone})",
                    reply_markup=KeyboardManager.get_error_keyboard()
                )

                # Nettoyage du contexte
                context.user_data.pop('editing_post_id', None)
                context.user_data.pop('schedule_day', None)

                return MAIN_MENU
            else:
                # Traitement normal pour nouvelle planification
                # Le code existant...
                return SCHEDULE_SEND

        except ValueError:
            await update.message.reply_text(
                MessageTemplates.get_invalid_time_message(),
                reply_markup=KeyboardManager.get_time_selection_keyboard()
            )
            return SCHEDULE_SEND

    except Exception as e:
        logger.error(f"Erreur dans handle_schedule_time : {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de la planification.",
            reply_markup=KeyboardManager.get_error_keyboard()
        )
        return MAIN_MENU


async def handle_edit_post(update: Update, context):
    try:
        post_type = None
        content = None
        caption = None

        if update.message.photo:
            post_type = "photo"
            content = update.message.photo[-1].file_id
            caption = update.message.caption

        elif update.message.video:
            post_type = "video"
            content = update.message.video.file_id
            caption = update.message.caption

        elif update.message.document:
            post_type = "document"
            content = update.message.document.file_id
            caption = update.message.caption

        elif update.message.text:
            post_type = "text"
            content = InputValidator.sanitize_text(update.message.text)

        context.user_data["edit_post"] = {
            "type": post_type,
            "content": content,
            "caption": caption and InputValidator.sanitize_text(caption),
            "reactions": [],
            "buttons": [],
            "original_message_id": update.message.message_id
        }

        keyboard = [
            [InlineKeyboardButton("📝 Modifier le texte/légende", callback_data="edit_caption")],
            [InlineKeyboardButton("🔗 Modifier les boutons", callback_data="edit_buttons")],
            [InlineKeyboardButton("✨ Modifier les réactions", callback_data="edit_reactions")],
            [InlineKeyboardButton("❌ Supprimer", callback_data="delete_post")],
            [InlineKeyboardButton("↩️ Annuler", callback_data="main_menu")]
        ]

        await update.message.reply_text(
            "✅ Message à modifier reçu. Que souhaitez-vous modifier ?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur dans handle_edit_post : {e}")
        await update.message.reply_text("❌ Erreur lors de la modification du post.")
        return MAIN_MENU


async def send_post_now(update: Update, context, scheduled_post=None):
    """Envoie immédiatement le(s) post(s)"""
    try:
        logger.info("Début de send_post_now")

        # Si c'est un post planifié
        if scheduled_post:
            try:
                # Envoyer le post planifié
                channel = scheduled_post.get('channel')
                post_type = scheduled_post.get('type')
                content = scheduled_post.get('content')
                caption = scheduled_post.get('caption')

                if post_type == "photo":
                    await context.bot.send_photo(chat_id=channel, photo=content, caption=caption)
                elif post_type == "video":
                    await context.bot.send_video(chat_id=channel, video=content, caption=caption)
                elif post_type == "document":
                    await context.bot.send_document(chat_id=channel, document=content, caption=caption)
                elif post_type == "text":
                    await context.bot.send_message(chat_id=channel, text=content)

                # Supprimer le post de la base de données
                db_manager.delete_scheduled_post(scheduled_post['id'])

                # Envoyer un message de confirmation
                confirmation_message = f"✅ {success_count} fichier(s) envoyé(s) avec succès !\n\nPour créer une nouvelle publication, envoyez-moi un nouveau message ou utilisez /start."
                await update.callback_query.message.reply_text(confirmation_message)

                return WAITING_PUBLICATION_CONTENT

            except Exception as e:
                logger.error(f"Erreur lors de l'envoi du post planifié: {e}")
                await update.callback_query.message.reply_text("❌ Erreur lors de l'envoi du post planifié.")
                return WAITING_PUBLICATION_CONTENT

        # Si c'est un post immédiat
        posts = context.user_data.get('posts', [])
        if not posts:
            await update.callback_query.message.reply_text(
                "❌ Aucun fichier à envoyer.\n"
                "Veuillez d'abord ajouter des fichiers."
            )
            return WAITING_PUBLICATION_CONTENT

        success_count = 0
        for post in posts:
            try:
                channel = post.get('channel', config.DEFAULT_CHANNEL)
                if post['type'] == "photo":
                    await context.bot.send_photo(
                        chat_id=channel,
                        photo=post['content'],
                        caption=post.get('caption')
                    )
                elif post['type'] == "video":
                    await context.bot.send_video(
                        chat_id=channel,
                        video=post['content'],
                        caption=post.get('caption')
                    )
                elif post['type'] == "document":
                    await context.bot.send_document(
                        chat_id=channel,
                        document=post['content'],
                        caption=post.get('caption')
                    )
                elif post['type'] == "text":
                    await context.bot.send_message(
                        chat_id=channel,
                        text=post['content']
                    )
                success_count += 1
            except Exception as e:
                logger.error(f"Erreur lors de l'envoi d'un fichier: {e}")
                continue

        # Envoyer un message de confirmation
        confirmation_message = f"✅ {success_count} fichier(s) envoyé(s) avec succès !\n\nPour créer une nouvelle publication, envoyez-moi un nouveau message ou utilisez /start."
        await update.callback_query.message.reply_text(confirmation_message)

        # Nettoyer le contexte après l'envoi réussi
        context.user_data.clear()

        return WAITING_PUBLICATION_CONTENT

    except Exception as e:
        logger.error(f"Erreur dans send_post_now: {e}")
        await update.callback_query.message.reply_text("❌ Une erreur est survenue lors de l'envoi.")
        return WAITING_PUBLICATION_CONTENT


async def handle_send_now(update: Update, context):
    """Gère l'envoi immédiat d'un post planifié"""
    try:
        query = update.callback_query
        await query.answer()

        logger.info("Début de handle_send_now")

        # Vérifier si le post existe dans le contexte
        if 'current_scheduled_post' not in context.user_data:
            logger.warning("Post introuvable dans le contexte")
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        post = context.user_data['current_scheduled_post']
        logger.info(f"Post trouvé : {post.get('type')} pour le canal {post.get('channel_username')}")

        try:
            # Construire le clavier avec les boutons URL si présents
            keyboard = []
            if post.get('buttons'):
                try:
                    buttons = eval(post['buttons'])  # Convertir la chaîne en liste de dictionnaires
                    for btn in buttons:
                        keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                except Exception as e:
                    logger.error(f"Erreur lors de la conversion des boutons : {e}")

            # Envoyer le post
            sent_message = None
            if post['type'] == "photo":
                sent_message = await context.bot.send_photo(
                    chat_id=post['channel_username'],
                    photo=post['content'],
                    caption=post.get('caption'),
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            elif post['type'] == "video":
                sent_message = await context.bot.send_video(
                    chat_id=post['channel_username'],
                    video=post['content'],
                    caption=post.get('caption'),
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            elif post['type'] == "document":
                sent_message = await context.bot.send_document(
                    chat_id=post['channel_username'],
                    document=post['content'],
                    caption=post.get('caption'),
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
            elif post['type'] == "text":
                sent_message = await context.bot.send_message(
                    chat_id=post['channel_username'],
                    text=post['content'],
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )

            if sent_message:
                logger.info("Post envoyé avec succès")

                # Supprimer le post de la base de données
                with sqlite3.connect(config.DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM posts WHERE id = ?", (post['id'],))
                    conn.commit()
                logger.info("Post supprimé de la base de données")

                # Supprimer la tâche planifiée si elle existe
                job_id = f"post_{post['id']}"
                if scheduler_manager.scheduler.get_job(job_id):
                    scheduler_manager.scheduler.remove_job(job_id)
                    logger.info("Tâche planifiée supprimée")

                # Envoyer un nouveau message de confirmation au lieu de modifier l'ancien
                await query.message.reply_text(
                    "✅ Post envoyé avec succès !",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                    ]])
                )

                # Nettoyer le contexte
                context.user_data.pop('current_scheduled_post', None)
                return MAIN_MENU

        except Exception as e:
            logger.error(f"Erreur lors de l'envoi du post : {e}")
            await query.message.reply_text(
                "❌ Erreur lors de l'envoi du post.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

    except Exception as e:
        logger.error(f"Erreur dans handle_send_now : {e}")
        await query.message.reply_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_edit_time(update: Update, context):
    """Gère la modification de l'heure d'une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        logger.info("Début de handle_edit_time")

        # Récupérer le post actuel
        post = context.user_data.get('current_scheduled_post')
        if not post:
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Créer les boutons avec les emojis appropriés
        keyboard = [
            [
                InlineKeyboardButton("Aujourd'hui", callback_data="schedule_today"),
                InlineKeyboardButton("Demain", callback_data="schedule_tomorrow"),
            ],
            [InlineKeyboardButton("↩️ Retour", callback_data="retour")]
        ]

        # Construction du message
        message_text = (
            "📅 Choisissez la nouvelle date pour votre publication :\n\n"
            "1️⃣ Sélectionnez le jour (Aujourd'hui ou Demain)\n"
            "2️⃣ Envoyez-moi l'heure au format :\n"
            "   • '15:30' ou '1530' (24h)\n"
            "   • '6' (06:00)\n"
            "   • '5 3' (05:03)\n\n"
            "❌ Aucun jour sélectionné"
        )

        await query.edit_message_text(
            message_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Stocker l'ID du post pour la modification
        context.user_data['editing_post_id'] = post['id']
        return SCHEDULE_SEND

    except Exception as e:
        logger.error(f"Erreur dans handle_edit_time : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de la modification de l'heure.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_cancel_post(update: Update, context):
    """Annule une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        logger.info("Début de handle_cancel_post")

        # Récupérer les informations du post
        post = context.user_data.get('current_scheduled_post')
        if not post:
            await query.edit_message_text(
                "❌ Publication introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        # Demander confirmation
        keyboard = [
            [
                InlineKeyboardButton("✅ Oui, annuler", callback_data="confirm_cancel"),
                InlineKeyboardButton("❌ Non, garder", callback_data="retour")
            ]
        ]

        await query.edit_message_text(
            "⚠️ Êtes-vous sûr de vouloir annuler cette publication ?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SCHEDULE_SELECT_CHANNEL

    except Exception as e:
        logger.error(f"Erreur dans handle_cancel_post : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue lors de l'annulation.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def handle_confirm_cancel(update: Update, context):
    """Confirme l'annulation d'une publication planifiée"""
    try:
        query = update.callback_query
        await query.answer()

        post = context.user_data.get('current_scheduled_post')
        if not post:
            return await handle_error(update, context, "Publication introuvable")

        # Supprimer de la base de données
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM posts WHERE id = ?", (post['id'],))
            conn.commit()

        # Supprimer la tâche planifiée si elle existe
        job_id = f"post_{post['id']}"
        if scheduler_manager.scheduler.get_job(job_id):
            scheduler_manager.scheduler.remove_job(job_id)

        await query.edit_message_text(
            "✅ Publication annulée avec succès !",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )

        # Nettoyer le contexte
        context.user_data.pop('current_scheduled_post', None)
        return MAIN_MENU

    except Exception as e:
        return await handle_error(update, context, f"Erreur lors de la confirmation d'annulation : {e}")


async def handle_error(update: Update, context, error_message):
    """Gestion centralisée des erreurs"""
    logger.error(error_message)
    if update.callback_query:
        await update.callback_query.edit_message_text(
            f"❌ {error_message}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
    else:
        await update.message.reply_text(
            f"❌ {error_message}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
    return MAIN_MENU


async def handle_callback(update: Update, context):
    """Gère les interactions principales via callbacks"""
    query = update.callback_query
    await query.answer()

    try:
        # Ajout de logs pour le débogage
        logger.info(f"Callback reçu : {query.data}")

        # Extraire l'action et l'ID du post si présent
        callback_data = query.data
        action = callback_data
        post_id = None

        if '_' in callback_data:
            parts = callback_data.split('_')
            if len(parts) > 1 and parts[-1].isdigit():
                post_id = parts[-1]
                action = '_'.join(parts[:-1])
            else:
                action = callback_data

        logger.info(f"Action : {action}, Post ID : {post_id}")

        # ---------- MENU PRINCIPAL ET NAVIGATION ----------
        if action == "main_menu":
            return await start(update, context)

        elif action == "create_publication":
            return await create_publication(update, context)

        elif action == "planifier_post":
            return await planifier_post(update, context)

        # ---------- GESTION DES POSTS PLANIFIÉS ----------
        elif action == "show_post" or action.startswith("show_post_"):
            return await show_scheduled_post(update, context)

        elif action == "modifier_heure":
            return await handle_edit_time(update, context)

        elif action == "envoyer_maintenant":
            return await handle_send_now(update, context)

        elif action == "annuler_publication":
            return await handle_cancel_post(update, context)

        elif action == "confirm_cancel":
            return await handle_confirm_cancel(update, context)

        elif action == "retour":
            return await planifier_post(update, context)

        # ---------- GESTION DE LA PLANIFICATION ----------
        elif action in ["schedule_today", "schedule_tomorrow"]:
            # Stocker le jour sélectionné
            context.user_data['schedule_day'] = 'today' if action == "schedule_today" else 'tomorrow'

            # Mettre à jour le message avec le jour sélectionné
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"Aujourd'hui {'✅' if context.user_data['schedule_day'] == 'today' else ''}",
                        callback_data="schedule_today"
                    ),
                    InlineKeyboardButton(
                        f"Demain {'✅' if context.user_data['schedule_day'] == 'tomorrow' else ''}",
                        callback_data="schedule_tomorrow"
                    ),
                ],
                [InlineKeyboardButton("↩️ Retour", callback_data="retour")]
            ]

            day_status = "✅ Jour sélectionné : " + (
                "Aujourd'hui" if context.user_data['schedule_day'] == 'today' else "Demain"
            )

            message_text = (
                "📅 Choisissez la nouvelle date pour votre publication :\n\n"
                "1️⃣ Sélectionnez le jour (Aujourd'hui ou Demain)\n"
                "2️⃣ Envoyez-moi l'heure au format :\n"
                "   • '15:30' ou '1530' (24h)\n"
                "   • '6' (06:00)\n"
                "   • '5 3' (05:03)\n\n"
                f"{day_status}"
            )

            await query.edit_message_text(
                message_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SCHEDULE_SEND

        # ---------- GESTION DES RÉACTIONS ----------
        elif action == "add_reactions":
            return await add_reactions_to_post(update, context)

        elif action == "remove_reactions":
            return await remove_reactions(update, context)

        # ---------- GESTION DES BOUTONS URL ----------
        elif action == "add_url_button":
            return await add_url_button_to_post(update, context)

        elif action == "remove_url_buttons":
            return await remove_url_buttons(update, context)

        # ---------- ENVOI ET OPTIONS ----------
        elif action == "send_post" or action == "Envoyer":
            logger.info("Tentative d'envoi du post")
            return await send_post_now(update, context)

        elif action == "schedule_send":
            return await schedule_send(update, context)

        elif action == "auto_destruction":
            return await auto_destruction(update, context)

        # ---------- PARAMÈTRES ET FUSEAU HORAIRE ----------
        elif action == "settings":
            return await settings(update, context)

        elif action == "set_timezone":
            return await handle_timezone_setup(update, context)

        # Si le callback n'est pas reconnu
        logger.warning(f"Callback non reconnu : {action}")
        await query.edit_message_text(
            "❌ Option non reconnue. Retour au menu principal.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]
            )
        )
        return MAIN_MENU

    except Exception as e:
        logger.error(f"Erreur dans handle_callback : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]
            )
        )
        return MAIN_MENU


# ... après la fonction handle_url_input, par exemple :

async def handle_preview(update: Update, context):
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


async def delete_current_post(update: Update, context):
    """Supprime le post en cours s'il existe, sinon informe l'utilisateur."""
    if context.user_data.get("post"):
        context.user_data.pop("post")
        await update.message.reply_text("✅ Post supprimé.")
    else:
        await update.message.reply_text("❌ Il n'y a pas de post à supprimer.")
    # Retour au menu principal
    await start(update, context)


# -----------------------------------------------------------------------------
# FONCTIONS DE GESTION ET HANDLERS
# -----------------------------------------------------------------------------

async def handle_channel_info(update: Update, context):
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

        if not InputValidator.validate_channel_name(username):
            await update.message.reply_text(
                "❌ Le nom de canal est invalide. Utilisez uniquement des lettres, chiffres et _ (5-32 caractères)."
            )
            return WAITING_CHANNEL_INFO

        try:
            db_manager.add_channel(name, username)
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


async def settings(update: Update, context):
    """Affiche le menu des paramètres"""
    try:
        query = update.callback_query
        await query.answer()

        keyboard = [
            [InlineKeyboardButton("🌍 Fuseau horaire", callback_data="set_timezone")],
            [InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]
        ]

        await query.edit_message_text(
            "⚙️ Paramètres\n\n"
            "Choisissez une option :",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SETTINGS

    except Exception as e:
        logger.error(f"Erreur dans settings : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def handle_timezone_setup(update: Update, context):
    """Gère la configuration du fuseau horaire"""
    try:
        query = update.callback_query
        await query.answer()

        # Récupérer le fuseau horaire actuel de l'utilisateur
        user_id = query.from_user.id
        current_timezone = db_manager.get_user_timezone(user_id)

        if current_timezone:
            # Si un fuseau horaire existe déjà
            keyboard = [
                [InlineKeyboardButton("🌍 Changer de fuseau horaire", callback_data="change_timezone")],
                [InlineKeyboardButton("↩️ Retour", callback_data="settings")]
            ]
            await query.edit_message_text(
                f"🕓 Vous avez déjà configuré votre fuseau horaire : {current_timezone}\n\n"
                "Voulez-vous le modifier ?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SETTINGS
        else:
            # Si aucun fuseau horaire n'est configuré
            await query.edit_message_text(
                "🌍 Configuration du fuseau horaire\n\n"
                "Veuillez m'envoyer votre fuseau horaire au format :\n"
                "• Europe/Paris\n"
                "• America/New_York\n"
                "• Asia/Tokyo\n"
                "• Africa/Cairo\n\n"
                "Vous pouvez trouver votre fuseau horaire ici :\n"
                "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="settings")]])
            )
            return WAITING_TIMEZONE

    except Exception as e:
        logger.error(f"Erreur dans handle_timezone_setup : {e}")
        await query.edit_message_text(
            "❌ Une erreur est survenue.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def handle_timezone_input(update: Update, context):
    """Gère l'entrée du fuseau horaire par l'utilisateur"""
    try:
        timezone = update.message.text.strip()
        user_id = update.effective_user.id

        # Vérification du fuseau horaire
        try:
            import pytz
            pytz.timezone(timezone)
        except pytz.exceptions.UnknownTimeZoneError:
            await update.message.reply_text(
                "❌ Fuseau horaire invalide. Veuillez utiliser un fuseau valide comme :\n"
                "• Europe/Paris\n"
                "• America/New_York\n"
                "• Asia/Tokyo\n"
                "• Africa/Cairo",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="settings")]])
            )
            return WAITING_TIMEZONE

        # Sauvegarde du fuseau horaire
        db_manager.save_user_timezone(user_id, timezone)

        await update.message.reply_text(
            f"✅ Votre fuseau horaire a été défini sur : {timezone}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")]])
        )
        return SETTINGS

    except Exception as e:
        logger.error(f"Erreur dans handle_timezone_input : {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de la sauvegarde du fuseau horaire.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]])
        )
        return MAIN_MENU


async def handle_new_time_input(update: Update, context):
    """Traite l'entrée d'une nouvelle heure pour une publication planifiée"""
    try:
        # Vérifier si nous avons les informations nécessaires
        if 'editing_post_id' not in context.user_data or 'schedule_day' not in context.user_data:
            await update.message.reply_text(
                "❌ Informations manquantes pour la planification.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU

        post_id = context.user_data['editing_post_id']
        schedule_day = context.user_data['schedule_day']

        # Traitement de l'heure entrée
        time_text = update.message.text.strip()
        try:
            # Convertir différents formats d'heure
            if ':' in time_text:
                hour, minute = map(int, time_text.split(':'))
            elif ' ' in time_text:
                hour, minute = map(int, time_text.split())
            else:
                if len(time_text) <= 2:  # Format simple (ex: "6")
                    hour = int(time_text)
                    minute = 0
                else:  # Format condensé (ex: "1530")
                    if len(time_text) == 3:  # Format 130 (1h30)
                        hour = int(time_text[0])
                        minute = int(time_text[1:])
                    else:  # Format 1530
                        hour = int(time_text[:-2])
                        minute = int(time_text[-2:])

            # Validation de l'heure
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Heure invalide")

            # Récupérer le fuseau horaire de l'utilisateur
            user_id = update.effective_user.id
            user_timezone = db_manager.get_user_timezone(user_id) or "UTC"
            local_tz = pytz.timezone(user_timezone)

            # Calculer la date cible
            target_date = datetime.now(local_tz)
            if schedule_day == 'tomorrow':
                target_date += timedelta(days=1)

            target_date = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            utc_date = target_date.astimezone(pytz.UTC)

            # Vérifier que l'heure n'est pas déjà passée
            if utc_date <= datetime.now(pytz.UTC):
                await update.message.reply_text(
                    "❌ Cette heure est déjà passée. Veuillez choisir une heure future.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="modifier_heure")
                    ]])
                )
                return WAITING_NEW_TIME

            # Mettre à jour la base de données
            with sqlite3.connect(config.DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE posts SET scheduled_time = ? WHERE id = ?",
                    (utc_date.strftime('%Y-%m-%d %H:%M:%S'), post_id)
                )
                conn.commit()
                logger.info(f"Publication {post_id} replanifiée pour {utc_date}")

            # Mettre à jour le scheduler
            job_id = f"post_{post_id}"
            if scheduler_manager.scheduler.get_job(job_id):
                scheduler_manager.scheduler.remove_job(job_id)
                logger.info(f"Ancienne tâche {job_id} supprimée")

            # Fonction pour l'envoi programmé
            async def send_scheduled_post(post_id, bot):
                try:
                    # Récupérer les informations du post
                    with sqlite3.connect(config.DB_PATH) as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT p.id, p.type, p.content, p.caption, p.buttons, c.username
                            FROM posts p
                            JOIN channels c ON p.channel_id = c.id
                            WHERE p.id = ?
                        """, (post_id,))
                        post_data = cursor.fetchone()

                        if not post_data:
                            logger.error(f"Post {post_id} introuvable lors de l'envoi planifié")
                            return

                        post_id, post_type, content, caption, buttons_str, channel = post_data

                        # Construction du clavier
                        keyboard = None
                        if buttons_str:
                            try:
                                buttons = eval(buttons_str)
                                inline_keyboard = []
                                for btn in buttons:
                                    inline_keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                                keyboard = InlineKeyboardMarkup(inline_keyboard)
                            except Exception as e:
                                logger.error(f"Erreur lors de la conversion des boutons : {e}")

                        # Envoi du post selon son type
                        if post_type == "photo":
                            await bot.send_photo(chat_id=channel, photo=content, caption=caption, reply_markup=keyboard)
                        elif post_type == "video":
                            await bot.send_video(chat_id=channel, video=content, caption=caption, reply_markup=keyboard)
                        elif post_type == "document":
                            await bot.send_document(chat_id=channel, document=content, caption=caption,
                                                    reply_markup=keyboard)
                        elif post_type == "text":
                            await bot.send_message(chat_id=channel, text=content, reply_markup=keyboard)

                        # Suppression du post
                        cursor.execute("DELETE FROM posts WHERE id = ?", (post_id,))
                        conn.commit()
                        logger.info(f"Post {post_id} envoyé et supprimé")

                except Exception as e:
                    logger.error(f"Erreur lors de l'envoi du post planifié {post_id} : {e}")

            # Ajouter la nouvelle tâche planifiée
            scheduler_manager.scheduler.add_job(
                lambda: send_scheduled_post(post_id, context.bot),
                'date',
                run_date=utc_date,
                id=job_id
            )
            logger.info(f"Nouvelle tâche {job_id} planifiée pour {utc_date}")

            # Message de confirmation
            jour_str = "aujourd'hui" if schedule_day == 'today' else "demain"
            time_str = f"{hour:02d}:{minute:02d}"
            await update.message.reply_text(
                f"✅ Publication replanifiée pour {jour_str} à {time_str} ({user_timezone}).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )

            # Nettoyage du contexte
            context.user_data.pop('editing_post_id', None)
            context.user_data.pop('schedule_day', None)

            return MAIN_MENU

        except ValueError as ve:
            await update.message.reply_text(
                f"❌ Format d'heure invalide. Veuillez utiliser l'un des formats suivants :\n"
                "• '15:30' ou '1530' (24h)\n"
                "• '6' (06:00)\n"
                "• '5 3' (05:03)",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="modifier_heure")
                ]])
            )
            return WAITING_NEW_TIME

    except Exception as e:
        logger.error(f"Erreur dans handle_new_time_input : {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de la modification de l'heure.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU


async def main():
    """Point d'entrée principal du bot."""
    app = None
    try:
        # Configuration du logging
        setup_logging()
        logger.info("Démarrage du bot...")

        # Initialisation des composants
        config = Config()
        db_manager = DatabaseManager(config.DB_PATH)
        resource_manager = ResourceManager(config.DOWNLOAD_FOLDER)
        scheduler_manager = SchedulerManager(db_manager)

        # Initialisation de l'application Telegram
        app = Application.builder().token(config.BOT_TOKEN).build()

        # Configuration des handlers
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                MAIN_MENU: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reply_keyboard),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_CHANNEL_SELECTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_selection),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_PUBLICATION_CONTENT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_content),
                    CallbackQueryHandler(handle_callback),
                ],
                POST_ACTIONS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_actions_text),
                    CallbackQueryHandler(handle_callback),
                ],
                SEND_OPTIONS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_send_now),
                    CallbackQueryHandler(handle_callback),
                ],
                AUTO_DESTRUCTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auto_destruction),
                    CallbackQueryHandler(handle_callback),
                ],
                SCHEDULE_SEND: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_schedule_time),
                    CallbackQueryHandler(handle_callback),
                ],
                EDIT_POST: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_post),
                    CallbackQueryHandler(handle_callback),
                ],
                SCHEDULE_SELECT_CHANNEL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_scheduled_channel),
                    CallbackQueryHandler(handle_callback),
                ],
                STATS_SELECT_CHANNEL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_scheduled_channel),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_CHANNEL_INFO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_info),
                    CallbackQueryHandler(handle_callback),
                ],
                SETTINGS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, settings),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_TIMEZONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_timezone_input),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_NEW_TIME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_time_input),
                    CallbackQueryHandler(handle_callback),
                ],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            per_message=False  # Ajout de cette ligne
        )
        app.add_handler(conv_handler)

        # Initialisation du userbot Telethon
        userbot = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
        await userbot.start()

        # Démarrage des composants
        db_manager.setup_database()
        scheduler_manager.start()
        await resource_manager.start_cleanup_task()

        # Démarrage du bot
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        # Création d'un événement pour gérer l'arrêt
        stop_event = asyncio.Event()

        # Attendre jusqu'à ce que l'événement d'arrêt soit déclenché
        await stop_event.wait()

    except KeyboardInterrupt:
        logger.info("Arrêt du bot par l'utilisateur")
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot : {e}")
        raise
    finally:
        # Arrêt propre des composants dans l'ordre inverse
        if app is not None:
            logger.info("Arrêt de l'application...")
            await app.stop()
            await app.shutdown()

        if 'scheduler_manager' in locals():
            scheduler_manager.stop()

        if 'userbot' in locals() and userbot.is_connected():
            await userbot.disconnect()

        if 'resource_manager' in locals():
            await resource_manager.stop_cleanup_task()

        logger.info("Arrêt propre du bot terminé")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Annule la conversation en cours et retourne au menu principal"""
    await update.message.reply_text("❌ Opération annulée")
    return ConversationHandler.END


if __name__ == "__main__":
    try:
        # Utilisation de la boucle d'événements existante
        loop = asyncio.get_event_loop()

        # Exécution du bot
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Arrêt du bot par l'utilisateur")
    except Exception as e:
        logger.error(f"Erreur inattendue : {e}")
    finally:
        # La boucle d'événements sera fermée automatiquement par Python
        pass

