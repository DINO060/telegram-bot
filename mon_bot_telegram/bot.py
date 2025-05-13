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
)
from dotenv import load_dotenv
import pytz
import time
import sys
import platform
from telethon import TelegramClient
import math

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

# Stockage des réactions
reaction_counts = {}

# Variable globale pour le userbot
userbot = None

# Ensemble pour stocker les callbacks déjà traités
processed_callbacks = set()

# Classe de gestionnaire de base de données si elle n'existe pas
class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        # Vérifier si le chemin est absolu ou relatif
        if not os.path.isabs(self.db_path):
            self.db_path = os.path.join(os.path.dirname(__file__), self.db_path)
        logger.info(f"Chemin de la base de données: {self.db_path}")
        self.check_db_access()  # Vérifier l'accès à la base de données
        self.setup_database()
    
    def check_db_access(self):
        """Vérifie si la base de données est accessible"""
        db_dir = os.path.dirname(self.db_path)
        try:
            # Vérifier que le dossier existe ou le créer
            if not os.path.exists(db_dir) and db_dir:
                os.makedirs(db_dir, exist_ok=True)
                logger.info(f"Dossier de base de données créé: {db_dir}")
            
            # Essayer d'ouvrir une connexion pour vérifier l'accès
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                # Augmenter le timeout pour attendre si la BD est verrouillée
                conn.execute("PRAGMA busy_timeout = 5000")
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                logger.info(f"Connexion à la base de données réussie: {result}")
                
                # Vérifier également l'existence des tables principales
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'")
                has_channels_table = cursor.fetchone() is not None
                if not has_channels_table:
                    logger.warning("La table 'channels' n'existe pas encore")
                    # Création immédiate si elle n'existe pas
                    self.setup_database()
                    
                return True
        except sqlite3.Error as e:
            logger.error(f"ERREUR SQL - Impossible d'accéder à la base de données: {e}")
            logger.error(f"Dossier parent: {db_dir}, Existe: {os.path.exists(db_dir) if db_dir else 'N/A'}")
            if db_dir and os.path.exists(db_dir):
                logger.error(f"Permissions du dossier parent: {os.access(db_dir, os.W_OK)}")
                # Liste les fichiers du dossier pour plus d'informations
                try:
                    logger.error(f"Contenu du dossier: {os.listdir(db_dir)}")
                except Exception as dir_error:
                    logger.error(f"Impossible de lister le contenu du dossier: {dir_error}")
            
            # En cas d'erreur d'accès, tenter de recréer la base de données
            try:
                # Si le fichier existe mais est inaccessible, essayer de le supprimer
                if os.path.exists(self.db_path):
                    os.remove(self.db_path)
                    logger.warning(f"Fichier de base de données supprimé pour recréation: {self.db_path}")
                # Créer une nouvelle connexion pour recréer la base
                self.setup_database()
                logger.info("Tentative de recréation de la base de données")
                return True
            except Exception as recreate_error:
                logger.error(f"Échec de la recréation de la base de données: {recreate_error}")
            
            return False
        except Exception as e:
            logger.error(f"ERREUR CRITIQUE - Impossible d'accéder à la base de données: {e}")
            logger.error(f"Dossier parent: {db_dir}, Existe: {os.path.exists(db_dir) if db_dir else 'N/A'}")
            logger.error(f"Permissions du dossier parent: {os.access(db_dir, os.W_OK) if db_dir and os.path.exists(db_dir) else 'N/A'}")
            return False

    def setup_database(self):
        """Initialisation de la base de données avec gestion des migrations"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Table des canaux
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        username TEXT NOT NULL,
                        user_id INTEGER NOT NULL
                    )
                ''')
                
                # Table des posts programmés
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS scheduled_posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_id INTEGER NOT NULL,
                        type TEXT NOT NULL,
                        content TEXT NOT NULL,
                        caption TEXT,
                        scheduled_time DATETIME NOT NULL,
                        FOREIGN KEY (channel_id) REFERENCES channels (id)
                    )
                ''')
                
                conn.commit()
                logger.info("Base de données initialisée avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de l'initialisation de la base de données: {e}")

    def list_channels(self, user_id):
        """Récupère la liste des canaux de l'utilisateur"""
        try:
            logger.info(f"Récupération des canaux pour l'utilisateur {user_id}")
            
            # Ajout d'un délai pour éviter les problèmes d'accès concurrent
            time.sleep(0.1)
            
            # Si la base de données n'est pas accessible, retourner une liste vide
            if not self.check_db_access():
                logger.error("Base de données inaccessible, retour d'une liste vide")
                return []
            
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                # Augmenter le timeout pour attendre si la BD est verrouillée
                conn.execute("PRAGMA busy_timeout = 5000")
                cursor = conn.cursor()
                # Vérifier si la table existe
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'")
                if not cursor.fetchone():
                    logger.error("La table 'channels' n'existe pas")
                    return []
                
                cursor.execute(
                    "SELECT name, username FROM channels WHERE user_id = ?",
                    (user_id,)
                )
                channels = cursor.fetchall()
                logger.info(f"Canaux trouvés: {channels}")
                return channels
        except sqlite3.OperationalError as e:
            logger.error(f"Erreur SQL lors de la récupération des canaux: {e}")
            # Retourne une liste vide en cas d'erreur plutôt que de faire planter le bot
            return []
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des canaux: {e}")
            # Retourne une liste vide en cas d'erreur plutôt que de faire planter le bot
            return []

    def get_channel_by_username(self, username, user_id):
        """Récupère les informations d'un canal par son username"""
        try:
            logger.info(f"Récupération du canal @{username} pour l'utilisateur {user_id}")
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, name FROM channels WHERE username = ? AND user_id = ?",
                    (username, user_id)
                )
                channel = cursor.fetchone()
                logger.info(f"Canal trouvé: {channel}")
                return channel
        except Exception as e:
            logger.error(f"Erreur lors de la récupération du canal @{username}: {e}")
            return None

    def add_channel(self, name, username, user_id):
        """Ajoute un canal à la base de données"""
        try:
            logger.info(f"Ajout du canal {name} (@{username}) pour l'utilisateur {user_id}")
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Vérifie si le canal existe déjà
                cursor.execute(
                    "SELECT id FROM channels WHERE username = ? AND user_id = ?",
                    (username, user_id)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # Mise à jour du canal existant
                    cursor.execute(
                        "UPDATE channels SET name = ? WHERE username = ? AND user_id = ?",
                        (name, username, user_id)
                    )
                    logger.info(f"Canal @{username} mis à jour")
                else:
                    # Insertion d'un nouveau canal
                    cursor.execute(
                        "INSERT INTO channels (name, username, user_id) VALUES (?, ?, ?)",
                        (name, username, user_id)
                    )
                    logger.info(f"Canal @{username} ajouté")
                
                conn.commit()
                
                # Retourner l'id du canal
                cursor.execute(
                    "SELECT id FROM channels WHERE username = ? AND user_id = ?",
                    (username, user_id)
                )
                channel_id = cursor.fetchone()[0]
                return channel_id
        except Exception as e:
            logger.error(f"Erreur lors de l'ajout du canal @{username}: {e}")
            raise

    def delete_channel(self, username, user_id):
        """Supprime un canal de la base de données"""
        try:
            logger.info(f"Suppression du canal @{username} pour l'utilisateur {user_id}")
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM channels WHERE username = ? AND user_id = ?",
                    (username, user_id)
                )
                conn.commit()
                deleted = cursor.rowcount > 0
                logger.info(f"Canal @{username} supprimé: {deleted}")
                return deleted
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du canal @{username}: {e}")
            return False

    def add_scheduled_post(self, channel_id, post_type, content, scheduled_time, caption=None):
        """Ajoute un post programmé à la base de données"""
        try:
            logger.info(f"Ajout d'un post programmé pour le canal {channel_id}")
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO scheduled_posts 
                    (channel_id, type, content, caption, scheduled_time) 
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (channel_id, post_type, content, caption, scheduled_time)
                )
                conn.commit()
                post_id = cursor.lastrowid
                logger.info(f"Post programmé ajouté avec ID: {post_id}")
                return post_id
        except Exception as e:
            logger.error(f"Erreur lors de l'ajout du post programmé: {e}")
            return None

    def delete_scheduled_post(self, post_id):
        """Supprime un post programmé de la base de données"""
        try:
            logger.info(f"Suppression du post programmé {post_id}")
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM scheduled_posts WHERE id = ?",
                    (post_id,)
                )
                conn.commit()
                deleted = cursor.rowcount > 0
                logger.info(f"Post programmé {post_id} supprimé: {deleted}")
                return deleted
        except Exception as e:
            logger.error(f"Erreur lors de la suppression du post programmé {post_id}: {e}")
            return False

# Initialisation du gestionnaire de base de données
db_manager = DatabaseManager(config.DB_PATH)

# Classe de gestionnaire de planification
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

def log_conversation_state(update, context, function_name, state_return):
    """Enregistre les informations d'état de conversation pour débogage"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    logger.info(f"[ÉTAT] Fonction: {function_name}, Utilisateur: {user_id}, Chat: {chat_id}")
    logger.info(f"[ÉTAT] État de retour: {state_return}")
    logger.info(f"[ÉTAT] État stocké: {context.user_data.get('conversation_state', 'Non défini')}")
    
    # Détecter les incohérences potentielles
    if 'conversation_state' in context.user_data and state_return != context.user_data['conversation_state']:
        logger.warning(f"[ÉTAT] Incohérence détectée! Retour: {state_return}, Stocké: {context.user_data['conversation_state']}")
    
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
                        await update.message.reply_text("Aucun canal configuré. Ajoutez-en un ou utilisez le canal par défaut.")
                except:
                    pass
            
            return WAITING_CHANNEL_SELECTION

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

async def planifier_post(update, context):
    """Affiche les posts planifiés et permet d'en planifier un nouveau"""
    logger.info("Fonction planifier_post appelée")
    try:
        # Interface simplifiée pour revenir au menu principal
        keyboard = [
            [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
        ]
        
        message = "📅 Gestion des publications planifiées"
        
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
        
        return MAIN_MENU
    except Exception as e:
        logger.error(f"Erreur dans planifier_post: {e}")
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

async def handle_send_now(update, context):
    """Gère la demande d'envoi immédiat d'un post"""
    await send_post_now(update, context)
    return ConversationHandler.END

# -----------------------------------------------------------------------------
# GESTIONNAIRE DE CALLBACKS
# -----------------------------------------------------------------------------
async def handle_callback(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    
    # Création d'un identifiant unique pour ce callback
    callback_id = f"{query.message.message_id}_{data}"
    
    # Vérifier si ce callback a déjà été traité
    if callback_id in processed_callbacks:
        logger.warning(f"Callback déjà traité, ignoré : {callback_id}")
        await query.answer("Action déjà traitée")
        return
    
    # Marquer ce callback comme traité
    processed_callbacks.add(callback_id)
    
    # Limiter la taille de l'ensemble pour éviter une croissance infinie
    if len(processed_callbacks) > 1000:
        # Garder seulement les 500 derniers callbacks
        processed_callbacks.clear()
    
    try:
        # Ajout de logs détaillés pour le débogage
        logger.info(f"Callback reçu : {query.data} de l'utilisateur {user_id}")
        logger.info(f"Message ID: {query.message.message_id}, Chat ID: {query.message.chat_id}")
        logger.info(f"État de conversation actuel : {context.user_data.get('conversation_state', 'Non défini')}")
        logger.info(f"Canal sélectionné : {context.user_data.get('selected_channel', 'Aucun')}")
        logger.info(f"Posts en cours : {len(context.user_data.get('posts', []))}")
        
        # Répondre au callback pour éviter le symbole de chargement
        try:
            await query.answer()
        except Exception as e:
            logger.error(f"Erreur lors de la réponse au callback: {e}")
            # Continuer malgré l'erreur

        # Analyser le type de callback pour un meilleur diagnostic
        callback_type = data.split('_')[0] if '_' in data else data
        logger.info(f"Type de callback détecté: {callback_type}")

        # ---------- MENU PRINCIPAL ET NAVIGATION ----------
        if data == "main_menu":
            return await start(update, context)

        elif data == "create_publication":
            return await create_publication(update, context)

        elif data == "planifier_post":
            return await planifier_post(update, context)

        elif data == "use_default_channel":
            # Utiliser le canal par défaut pour cette session
            default_channel = config.DEFAULT_CHANNEL.replace("https://t.me/", "")
            if default_channel.startswith("@"):
                default_channel = default_channel[1:]  # Supprimer le @ initial
                
            context.user_data['selected_channel'] = {
                'username': default_channel,
                'name': "Canal par défaut"
            }
            
            await query.edit_message_text(
                f"✅ Canal par défaut sélectionné : @{default_channel}\n\n"
                f"Envoyez-moi le contenu que vous souhaitez publier (texte, photo, vidéo ou document).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="create_publication")
                ]])
            )
            
            return WAITING_PUBLICATION_CONTENT

        # ---------- SÉLECTION DE CANAL ----------
        elif data.startswith("select_channel_"):
            try:
                # Extraire le nom du canal
                channel_username = data.replace("select_channel_", "")
                logger.info(f"Sélection du canal demandée : @{channel_username}")
                
                # Récupérer les informations du canal
                channel_info = db_manager.get_channel_by_username(channel_username, user_id)
                logger.info(f"Informations du canal récupérées: {channel_info}")
                
                if not channel_info:
                    logger.error(f"Canal introuvable dans la base de données : @{channel_username}")
                    await query.edit_message_text(
                        f"❌ Canal @{channel_username} introuvable dans la base de données.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Retour", callback_data="create_publication")
                        ]])
                    )
                    return WAITING_CHANNEL_SELECTION
                
                # Stocker l'information du canal sélectionné
                context.user_data['selected_channel'] = {
                    'username': channel_username,
                    'name': channel_info[1]
                }
                logger.info(f"Canal stocké dans context.user_data: {context.user_data['selected_channel']}")
                
                # Message pour demander le contenu à publier
                await query.edit_message_text(
                    f"✅ Canal @{channel_username} sélectionné!\n\n"
                    f"Envoyez-moi maintenant le contenu que vous souhaitez publier :\n"
                    f"• Texte simple\n"
                    f"• Photo (avec ou sans légende)\n"
                    f"• Vidéo (avec ou sans légende)\n"
                    f"• Document (avec ou sans légende)",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="create_publication")
                    ]])
                )
                
                logger.info(f"Canal @{channel_username} sélectionné avec succès par l'utilisateur {user_id}")
                return WAITING_PUBLICATION_CONTENT
            
            except Exception as e:
                logger.error(f"Erreur lors de la sélection du canal: {e}")
                logger.exception("Traceback complet de l'erreur:")
                await query.edit_message_text(
                    "❌ Une erreur est survenue lors de la sélection du canal.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="create_publication")
                    ]])
                )
                return WAITING_CHANNEL_SELECTION

        # ---------- GESTION DES FICHIERS VOLUMINEUX ----------
        elif data == "use_telethon":
            # Rediriger vers la fonction de gestion des fichiers volumineux avec Telethon
            if 'pending_large_file' in context.user_data:
                stored_update = context.user_data.pop('pending_large_file')['update']
                await handle_userbot_file(stored_update, context)
                await query.edit_message_text("⏳ Traitement du fichier via Telethon en cours...")
            else:
                await query.edit_message_text("❌ Aucun fichier en attente.")
            return WAITING_PUBLICATION_CONTENT

        elif data == "compress_file":
            # Compression du fichier (surtout pour les vidéos)
            return await handle_compress_file(update, context)

        elif data == "split_file":
            # Découpage du fichier en parties
            return await handle_split_file(update, context)

        elif data == "cancel_upload":
            # Annuler l'upload du fichier volumineux
            if 'pending_large_file' in context.user_data:
                context.user_data.pop('pending_large_file')
                await query.edit_message_text("⚠️ Envoi annulé. Veuillez utiliser un fichier plus petit.")
            else:
                await query.edit_message_text("❌ Aucun fichier en attente.")
            return WAITING_PUBLICATION_CONTENT

        # ---------- GESTION DES POSTS PLANIFIÉS ----------
        elif data == "show_post" or data.startswith("show_post_"):
            return await show_scheduled_post(update, context)

        elif data == "modifier_heure":
            return await handle_edit_time(update, context)

        elif data == "envoyer_maintenant":
            return await handle_send_now(update, context)

        elif data == "annuler_publication":
            return await handle_cancel_post(update, context)

        elif data == "confirm_cancel":
            return await handle_confirm_cancel(update, context)

        elif data == "retour":
            return await planifier_post(update, context)

        # ---------- GESTION DE LA SUPPRESSION ----------
        elif data == "delete_post" or data.startswith("delete_post_"):
            logger.info(f"Traitement de la suppression du post avec callback_data: {data}")
            return await handle_delete_post(update, context)

        # ---------- GESTION DU RENOMMAGE ----------
        elif data == "rename_post" or data.startswith("rename_post_"):
            logger.info(f"Traitement du renommage du post avec callback_data: {data}")
            return await handle_rename_post(update, context)

        elif data.startswith("cancel_rename_"):
            # Annuler l'opération de renommage
            if 'waiting_for_rename' in context.user_data:
                del context.user_data['waiting_for_rename']
            if 'current_post_index' in context.user_data:
                del context.user_data['current_post_index']
            await query.message.reply_text("❌ Opération de renommage annulée.")
            return WAITING_PUBLICATION_CONTENT

        # ---------- GESTION DES CANAUX ----------
        elif data == "manage_channels":
            return await handle_manage_channels(update, context)

        elif data == "add_channel":
            return await handle_add_channel(update, context)

        elif data.startswith("delete_channel_"):
            return await handle_delete_channel(update, context)

        elif data.startswith("confirm_delete_"):
            # Confirmation de suppression d'un canal
            channel_username = data.split("_")[-1]
            try:
                deleted = db_manager.delete_channel(channel_username, user_id)
                if deleted:
                    await query.edit_message_text(
                        f"✅ Canal @{channel_username} supprimé avec succès.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Retour à la gestion des canaux", callback_data="manage_channels")
                        ]])
                    )
                else:
                    await query.edit_message_text(
                        f"❌ Canal @{channel_username} introuvable ou déjà supprimé.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")
                        ]])
                    )
            except Exception as e:
                logger.error(f"Erreur lors de la suppression du canal @{channel_username}: {e}")
                await query.edit_message_text(
                    f"❌ Erreur lors de la suppression du canal: {str(e)}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")
                    ]])
                )
            return SETTINGS

        # ---------- GESTION DE LA PLANIFICATION ----------
        elif data in ["schedule_today", "schedule_tomorrow"]:
            # Stocker le jour sélectionné
            context.user_data['schedule_day'] = 'today' if data == "schedule_today" else 'tomorrow'
            return await schedule_send(update, context)

        # ---------- GESTION DES RÉACTIONS ----------
        elif data == "add_reactions" or data.startswith("add_reactions_"):
            logger.info(f"Traitement de l'ajout de réactions avec callback_data: {data}")
            return await add_reactions_to_post(update, context)

        elif data == "remove_reactions" or data.startswith("remove_reactions_"):
            logger.info(f"Traitement de la suppression des réactions avec callback_data: {data}")
            return await remove_reactions(update, context)

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
            if 'current_post_index' in context.user_data:
                del context.user_data['current_post_index']
            await query.message.reply_text("❌ Opération d'ajout de bouton URL annulée.")
            return WAITING_PUBLICATION_CONTENT

        elif data.startswith("cancel_reactions_"):
            # Annuler l'opération d'ajout de réactions
            if 'waiting_for_reactions' in context.user_data:
                del context.user_data['waiting_for_reactions']
            if 'current_post_index' in context.user_data:
                del context.user_data['current_post_index']
            await query.message.reply_text("❌ Opération d'ajout de réactions annulée.")
            return WAITING_PUBLICATION_CONTENT
            
        # ---------- GESTION DES RÉACTIONS INDIVIDUELLES ----------
        elif data.startswith("react_"):
            logger.info(f"Réaction individuelle détectée: {data}")
            # Code pour gérer les réactions individuelles
            parts = data.split('_')
            if len(parts) >= 3:
                try:
                    post_index = int(parts[1])
                    reaction = parts[2]
                    logger.info(f"Réaction {reaction} pour le post {post_index}")
                    await query.answer(f"Vous avez réagi avec {reaction}")
                    # Ici vous pouvez ajouter le code pour traiter la réaction
                except (ValueError, IndexError) as e:
                    logger.error(f"Erreur lors du traitement de la réaction: {e}")
                    await query.answer("Erreur lors du traitement de la réaction")
            return

        # ---------- ENVOI ET OPTIONS ----------
        elif data == "send_post" or data == "Envoyer":
            logger.info("Tentative d'envoi du post")
            return await send_post_now(update, context)

        elif data == "schedule_send":
            return await schedule_send(update, context)

        elif data == "auto_destruction":
            return await auto_destruction(update, context)

        # ---------- PARAMÈTRES ET FUSEAU HORAIRE ----------
        elif data == "settings":
            return await settings(update, context)

        elif data == "set_timezone":
            return await handle_timezone_setup(update, context)

        # ---------- GESTION DE LA PERSONNALISATION ----------
        elif data == "customer_settings":
            return await handle_customer_settings(update, context)

        elif data == "add_thumbnail":
            await query.edit_message_text(
                "🖼️ Thumbnail pour vos posts\n\n"
                "Envoyez-moi une image pour l'utiliser comme thumbnail.\n\n"
                "• Le thumbnail doit être une image (JPEG ou PNG recommandé).\n"
                "• Taille maximale : 200 KB (au-delà, Telegram l'ignore).\n"
                "• Dimensions recommandées : 320x320 px (pas obligatoire mais conseillé).",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("❌ Annuler", callback_data="customer_settings")]])
                )
            # Définir l'état d'attente du thumbnail
            context.user_data['waiting_for_thumbnail'] = True
            return WAITING_THUMBNAIL

        elif data == "use_thumbnail_anyway":
            # Utiliser le thumbnail malgré la taille excessive
            if 'temp_thumbnail' in context.user_data:
                context.user_data['user_thumbnail'] = context.user_data.pop('temp_thumbnail')
                context.user_data['waiting_for_thumbnail'] = False
                await query.edit_message_text(
                    "✅ Thumbnail enregistré malgré sa taille.\n"
                    "⚠️ Telegram pourrait l'ignorer sur certains types de médias.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="customer_settings")]
                    ])
                )
            else:
                await query.edit_message_text(
                    "❌ Aucun thumbnail temporaire trouvé.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("↩️ Retour", callback_data="customer_settings")]
                    ])
                )
            return SETTINGS

        # Si aucun callback n'a été reconnu, log et retourner au menu
        else:
            logger.warning(f"Callback non reconnu : {data}")
            await query.answer("Cette action n'est pas disponible actuellement.")
            return await start(update, context)

    except Exception as e:
        logger.error(f"Erreur dans handle_callback pour {data}: {e}")
        logger.exception("Traceback complet:")
        try:
            await query.answer("Une erreur est survenue.")
            await query.message.reply_text(
                "❌ Une erreur est survenue lors du traitement de votre demande.\n"
                "Veuillez réessayer ou utiliser /start pour redémarrer.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
                ])
            )
        except Exception as send_error:
            logger.error(f"Erreur secondaire : {send_error}")
        return MAIN_MENU


def main():
    """Point d'entrée principal du bot"""
    global userbot

    try:
        # Configuration de l'application
        application = Application.builder().token(config.BOT_TOKEN).build()
        
        # Ajout de logs pour le démarrage
        logger.info("Initialisation de l'application...")
        
        # Démarrage du scheduler
        scheduler_manager.start()
        logger.info("Scheduler démarré avec succès")

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
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_actions_text),
                ],
                POST_CONTENT: [
                    MessageHandler(filters.Document.ALL, send_large_file),
                    MessageHandler(filters.PHOTO, send_large_file),
                    MessageHandler(filters.VIDEO, send_large_file),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_content),
                    CallbackQueryHandler(handle_callback),
                ],
                POST_ACTIONS: [
                    CallbackQueryHandler(handle_callback),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_actions_text),
                ],
                SEND_OPTIONS: [
                    CallbackQueryHandler(handle_callback),
                ],
                AUTO_DESTRUCTION: [
                    CallbackQueryHandler(handle_auto_destruction),
                ],
                SCHEDULE_SEND: [
                    CallbackQueryHandler(handle_callback),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_schedule_time),
                ],
                EDIT_POST: [
                    CallbackQueryHandler(handle_callback),
                ],
                SCHEDULE_SELECT_CHANNEL: [
                    CallbackQueryHandler(handle_callback),
                ],
                STATS_SELECT_CHANNEL: [
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_CHANNEL_INFO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_info),
                    CallbackQueryHandler(handle_callback),
                ],
                SETTINGS: [
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_TIMEZONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_timezone_input),
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_THUMBNAIL: [
                    MessageHandler(filters.PHOTO, handle_thumbnail_input),
                    CallbackQueryHandler(handle_callback),
                ],
                BACKUP_MENU: [
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_CHANNEL_SELECTION: [
                    CallbackQueryHandler(handle_callback),
                ],
                WAITING_PUBLICATION_CONTENT: [
                    MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO | (filters.TEXT & ~filters.COMMAND), handle_post_content),
                    CallbackQueryHandler(handle_callback),
                ],
            },
            fallbacks=[
                CommandHandler("cancel", lambda update, context: MAIN_MENU),
                CommandHandler("start", start),
                # Ajout d'un fallback global pour les callbacks
                CallbackQueryHandler(handle_callback),
            ],
            per_message=False,
            name="main_conversation",
            persistent=False,
            allow_reentry=True,
        )

        # Log des handlers configurés
        logger.info("ConversationHandler configuré avec états: %s", ", ".join(str(state) for state in conv_handler.states.keys()))

        # Ajout des handlers
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler("diagnostic", diagnostic))
        application.add_handler(CommandHandler("db_diagnostic", db_diagnostic))
        
        # Ajouter un handler en dehors du ConversationHandler pour capturer tous les callbacks
        # qui ne seraient pas gérés par le ConversationHandler
        logger.info("Ajout du handler de callback global")
        application.add_handler(CallbackQueryHandler(handle_callback), group=1)
        
        # Ajouter un handler d'erreur pour capturer toutes les erreurs non gérées
        application.add_error_handler(lambda update, context: 
            logger.error(f"Erreur non gérée : {context.error}", exc_info=context.error))

        # Initialisation du userbot pour les fichiers volumineux
        asyncio.get_event_loop().create_task(init_userbot())
        logger.info("Initialisation du userbot Telethon demandée")

        # Démarrage du bot
        logger.info("Démarrage du bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)

    except Exception as e:
        logger.error(f"Erreur dans main: {e}")
        logger.exception("Traceback complet:")
    finally:
        # Arrêt propre
        logger.info("Arrêt du bot")

        # Fermer proprement le client Telethon
        try:
            if userbot and userbot.is_connected():
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(userbot.disconnect())
                    logger.info("Client Telethon en cours de déconnexion")
        except Exception as e:
            logger.error(f"Erreur lors de la déconnexion de Telethon: {e}")

        # Arrêt du scheduler
        try:
            scheduler_manager.stop()
            logger.info("Scheduler arrêté avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt du scheduler: {e}")


# Fonction pour arrêter proprement le bot
async def shutdown():
    """Fonction d'arrêt propre du bot"""
    global userbot

    # Déconnecter le client Telethon
    if userbot and userbot.is_connected():
        try:
            logger.info("Déconnexion du client Telethon...")
            await userbot.disconnect()
            logger.info("Client Telethon déconnecté avec succès")
        except Exception as e:
            logger.error(f"Erreur lors de la déconnexion de Telethon: {e}")

    # Arrêter le scheduler
    try:
        scheduler_manager.stop()
        logger.info("Scheduler arrêté avec succès")
    except Exception as e:
        logger.error(f"Erreur lors de l'arrêt du scheduler: {e}")


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

        # Définir les boutons d'action uniquement
        keyboard = [
            [InlineKeyboardButton("✨ Ajouter des réactions", callback_data=f"add_reactions_{post_index}")],
            [InlineKeyboardButton("🔗 Ajouter un bouton URL", callback_data=f"add_url_button_{post_index}")],
            [InlineKeyboardButton("📝 Renommer", callback_data=f"rename_post_{post_index}")],
            [InlineKeyboardButton("❌ Supprimer", callback_data=f"delete_post_{post_index}")]
        ]

        # Envoyer seulement l'aperçu du post avec les boutons
        # AUCUN message de confirmation ou d'information supplémentaire
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
                post_data['content'],
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

async def handle_post_actions_text(update, context):
    """Gère les actions textuelles sur les posts en cours de création"""
    try:
        text = update.message.text.lower()
        
        if text == "envoyer":
            return await send_post_now(update, context)
        elif text == "annuler":
            if 'posts' in context.user_data:
                context.user_data.pop('posts')
            if 'current_post' in context.user_data:
                context.user_data.pop('current_post')
            if 'current_post_index' in context.user_data:
                context.user_data.pop('current_post_index')
            
            await update.message.reply_text(
                "❌ Création de publication annulée.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        elif text == "aperçu":
            if 'current_post' in context.user_data:
                post = context.user_data['current_post']
                
                # Afficher un aperçu du post selon son type
                if post['type'] == 'photo':
                    await update.message.reply_photo(
                        photo=post['content'],
                        caption=post.get('caption')
                    )
                elif post['type'] == 'video':
                    await update.message.reply_video(
                        video=post['content'],
                        caption=post.get('caption')
                    )
                elif post['type'] == 'document':
                    await update.message.reply_document(
                        document=post['content'],
                        caption=post.get('caption')
                    )
                elif post['type'] == 'text':
                    await update.message.reply_text(
                        f"📝 Aperçu: \n\n{post['content']}"
                    )
            else:
                await update.message.reply_text("❌ Aucun post en cours.")
            
            return POST_ACTIONS
        elif text == "tout supprimer":
            if 'posts' in context.user_data:
                context.user_data.pop('posts')
            if 'current_post' in context.user_data:
                context.user_data.pop('current_post')
            if 'current_post_index' in context.user_data:
                context.user_data.pop('current_post_index')
            
            await update.message.reply_text(
                "🗑️ Tous les posts ont été supprimés.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        else:
            # Si le texte ne correspond à aucune commande, on traite comme un nouveau post
            return await handle_post_content(update, context)
            
    except Exception as e:
        logger.error(f"Erreur dans handle_post_actions_text: {e}")
        return MAIN_MENU

async def diagnostic(update, context):
    """Commande de diagnostic pour vérifier l'état du bot"""
    try:
        # Vérification des variables globales importantes
        global userbot, scheduler_manager
        
        # Informations système
        system_info = f"OS: {platform.system()} {platform.version()}\n"
        system_info += f"Python: {sys.version}\n"
        system_info += f"Asyncio: {asyncio.__version__}\n"
        
        # État des composants
        components_status = "Statut des composants:\n"
        components_status += f"- Userbot: {'Connecté' if userbot and userbot.is_connected() else 'Non connecté'}\n"
        components_status += f"- Scheduler: {'Actif' if scheduler_manager.scheduler.running else 'Inactif'}\n"
        
        # Informations sur la boucle asyncio
        loop_info = "Boucle asyncio:\n"
        loop = asyncio.get_event_loop()
        loop_info += f"- Boucle en cours d'exécution: {loop.is_running()}\n"
        loop_info += f"- Boucle fermée: {loop.is_closed()}\n"
        
        # Rapport complet
        report = f"📊 RAPPORT DE DIAGNOSTIC\n\n{system_info}\n{components_status}\n{loop_info}"
        
        await update.message.reply_text(report)
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur lors du diagnostic: {str(e)}")

async def db_diagnostic(update, context):
    """Diagnostic de la base de données"""
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Liste des tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = cursor.fetchall()
            
            report = "📊 DIAGNOSTIC DE LA BASE DE DONNÉES\n\n"
            report += "Tables présentes:\n"
            
            for table in tables:
                table_name = table[0]
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                report += f"- {table_name}: {count} entrées\n"
                
                # Obtenir la structure de la table
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                report += "  Colonnes: " + ", ".join(col[1] for col in columns) + "\n\n"
            
            await update.message.reply_text(report)
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur lors du diagnostic de la BD: {str(e)}")

async def handle_auto_destruction(update, context):
    """Gère les options d'auto-destruction pour un post"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "⚙️ Fonction d'auto-destruction non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def handle_edit_time(update, context):
    """Permet de modifier l'heure d'un post planifié"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "⚙️ Fonction de modification d'heure non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def schedule_send(update, context):
    """Interface pour planifier l'envoi d'un post"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "⚙️ Fonction de planification non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def settings(update, context):
    """Affiche les paramètres du bot"""
    keyboard = [
        [InlineKeyboardButton("🕒 Fuseau horaire", callback_data="set_timezone")],
        [InlineKeyboardButton("📊 Gérer les canaux", callback_data="manage_channels")],
        [InlineKeyboardButton("🎨 Personnalisation", callback_data="customer_settings")],
        [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
    ]
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "⚙️ Paramètres du bot",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "⚙️ Paramètres du bot",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return SETTINGS

async def auto_destruction(update, context):
    """Gère les options d'auto-destruction pour un post"""
    return await handle_auto_destruction(update, context)

async def send_large_file(update, context):
    """Gère l'envoi de fichiers volumineux"""
    try:
        message = update.message
        user_id = update.effective_user.id
        
        # Vérifier quel type de fichier a été envoyé
        if message.document:
            file_info = message.document
            file_type = "document"
        elif message.photo:
            file_info = message.photo[-1]  # Prendre la meilleure qualité
            file_type = "photo"
        elif message.video:
            file_info = message.video
            file_type = "video"
        else:
            await message.reply_text("❌ Type de fichier non supporté.")
            return WAITING_PUBLICATION_CONTENT
        
        file_size = file_info.file_size
        
        # Si le fichier est trop volumineux pour un bot mais OK pour userbot
        if file_size > config.BOT_MAX_MEDIA_SIZE and file_size <= config.USERBOT_MAX_MEDIA_SIZE:
            # Vérifier que le userbot est disponible
            global userbot
            if userbot and userbot.is_connected():
                # Rediriger directement vers handle_userbot_file au lieu d'afficher les options
                context.user_data['pending_large_file'] = {
                    'update': update,
                    'file_info': file_info,
                    'file_type': file_type
                }
                
                return await handle_userbot_file(update, context)
            else:
                # Si le userbot n'est pas disponible, informer l'utilisateur
                keyboard = [[InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]]
                await message.reply_text(
                    f"⚠️ Ce fichier est trop volumineux pour être envoyé directement.\n"
                    f"Le service userbot n'est pas disponible actuellement."
                    f"\nTaille maximale : {config.BOT_MAX_MEDIA_SIZE / (1024 * 1024):.2f} MB.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return WAITING_PUBLICATION_CONTENT
        
        # Si le fichier dépasse même la capacité du userbot
        elif file_size > config.USERBOT_MAX_MEDIA_SIZE:
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Compresser", callback_data="compress_file"),
                    InlineKeyboardButton("✂️ Découper", callback_data="split_file")
                ],
                [InlineKeyboardButton("❌ Annuler", callback_data="cancel_upload")]
            ]
            
            await message.reply_text(
                f"⚠️ Ce fichier est trop volumineux (même pour le userbot).\n"
                f"Taille maximale: {config.USERBOT_MAX_MEDIA_SIZE / (1024 * 1024 * 1024):.2f} GB.\n\n"
                f"Vous pouvez :\n"
                f"• Compresser le fichier (surtout pour les vidéos)\n"
                f"• Découper le fichier en plusieurs parties\n"
                f"• Annuler et utiliser un fichier plus petit",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            # Stocker les informations du fichier pour traitement ultérieur
            context.user_data['pending_large_file'] = {
                'update': update,
                'file_info': file_info,
                'file_type': file_type
            }
            
            return WAITING_PUBLICATION_CONTENT
        
        # Si le fichier est d'une taille acceptable, le traiter normalement
        else:
            return await handle_post_content(update, context)
    
    except Exception as e:
        logger.error(f"Erreur dans send_large_file: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors du traitement de votre fichier.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_userbot_file(update, context):
    """Gère l'envoi de fichiers très volumineux via userbot Telethon"""
    try:
        # Vérification de l'initialisation du userbot
        global userbot
        if userbot is None or not userbot.is_connected():
            userbot = await start_telethon_client()
        if userbot is None:
            await update.message.reply_text(
                "❌ Impossible de se connecter au service userbot. Veuillez réessayer plus tard."
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Récupérer les informations sur le fichier
        message = update.message
        
        if message.document:
            file_type = "document"
            file_obj = message.document
            file_name = file_obj.file_name
            file_size = file_obj.file_size
        elif message.photo:
            file_type = "photo"
            file_obj = message.photo[-1]  # Meilleure qualité
            file_name = f"photo_{message.message_id}.jpg"
            file_size = file_obj.file_size
        elif message.video:
            file_type = "video"
            file_obj = message.video
            file_name = file_obj.file_name or f"video_{message.message_id}.mp4"
            file_size = file_obj.file_size
        else:
            await update.message.reply_text("❌ Type de fichier non pris en charge pour l'envoi via userbot.")
            return WAITING_PUBLICATION_CONTENT
        
        # Vérifier si le fichier n'est pas trop volumineux même pour le userbot
        if file_size > config.USERBOT_MAX_MEDIA_SIZE:
            await update.message.reply_text(
                f"❌ Ce fichier est trop volumineux même pour le userbot.\n"
                f"La limite est de {config.USERBOT_MAX_MEDIA_SIZE / (1024 * 1024 * 1024):.2f} GB."
            )
            return WAITING_PUBLICATION_CONTENT
        
        # Télécharger le fichier
        await update.message.reply_text(
            f"⏳ Téléchargement du fichier en cours...\n"
            f"Taille: {file_size / (1024 * 1024):.2f} MB"
        )
        
        download_path = os.path.join(config.DOWNLOAD_FOLDER, file_name)
        
        # Télécharger le fichier via PTB
        file = await context.bot.get_file(file_obj.file_id)
        await file.download_to_drive(download_path)
        
        # Informer l'utilisateur
        await update.message.reply_text(
            f"⏳ Fichier téléchargé, envoi en cours via userbot..."
        )
        
        # Envoi du fichier via userbot
        caption = message.caption or ""
        await userbot.send_file(
            context.user_data.get('selected_channel', {}).get('username', config.DEFAULT_CHANNEL),
            download_path,
            caption=caption
        )
        
        # Nettoyage et confirmation
        os.remove(download_path)
        await update.message.reply_text("✅ Fichier envoyé avec succès via userbot!")
        
        return WAITING_PUBLICATION_CONTENT
    
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du fichier via userbot: {e}")
        await update.message.reply_text(
            f"❌ Erreur lors de l'envoi : {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_thumbnail_input(update, context):
    """Gère la réception d'une image à utiliser comme thumbnail"""
    try:
        # Vérifier si on est en attente d'un thumbnail
        if not context.user_data.get('waiting_for_thumbnail', False):
            await update.message.reply_text(
                "❌ Je n'attends pas de thumbnail actuellement.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        photo = update.message.photo[-1]  # Prendre la meilleure qualité
        file_size = photo.file_size
        
        # Vérifier la taille du thumbnail (200 KB max recommandé par Telegram)
        if file_size > 200 * 1024:
            # Stocker temporairement le thumbnail
            context.user_data['temp_thumbnail'] = photo.file_id
            
            # Informer l'utilisateur que l'image est peut-être trop grande
            keyboard = [
                [InlineKeyboardButton("✅ Utiliser quand même", callback_data="use_thumbnail_anyway")],
                [InlineKeyboardButton("❌ Annuler", callback_data="customer_settings")]
            ]
            
            await update.message.reply_text(
                f"⚠️ Ce thumbnail fait {file_size / 1024:.1f} KB, ce qui dépasse la limite recommandée de 200 KB.\n\n"
                f"Telegram pourrait l'ignorer. Vous pouvez soit :\n"
                f"• L'utiliser quand même\n"
                f"• Annuler et réessayer avec une image plus petite",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return WAITING_THUMBNAIL
        
        # Si la taille est acceptable, enregistrer le thumbnail
        context.user_data['user_thumbnail'] = photo.file_id
        context.user_data['waiting_for_thumbnail'] = False
        
        await update.message.reply_text(
            "✅ Thumbnail enregistré avec succès!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="customer_settings")
            ]])
        )
        
        return SETTINGS
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement du thumbnail: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors du traitement de votre image.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_timezone_setup(update, context):
    """Interface pour configurer le fuseau horaire"""
    query = update.callback_query
    await query.answer()
    
    # Construire la liste des fuseaux horaires courants
    common_timezones = [
        "Europe/Paris", "Europe/London", "America/New_York", 
        "America/Los_Angeles", "Asia/Tokyo", "Australia/Sydney"
    ]
    
    keyboard = []
    for tz in common_timezones:
        keyboard.append([InlineKeyboardButton(tz, callback_data=f"set_tz_{tz}")])
    
    # Ajouter un bouton pour saisir manuellement
    keyboard.append([InlineKeyboardButton("🔎 Autre fuseau horaire", callback_data="manual_timezone")])
    keyboard.append([InlineKeyboardButton("↩️ Retour", callback_data="settings")])
    
    await query.edit_message_text(
        "🕒 Sélectionnez votre fuseau horaire :\n\n"
        "Cette configuration est utilisée pour la planification des publications.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return WAITING_TIMEZONE

async def handle_timezone_input(update, context):
    """Gère la saisie manuelle d'un fuseau horaire"""
    try:
        timezone_str = update.message.text.strip()
        
        # Vérifier si le fuseau horaire est valide
        try:
            timezone = pytz.timezone(timezone_str)
            # Enregistrer le fuseau horaire
            context.user_data['timezone'] = timezone_str
            
            await update.message.reply_text(
                f"✅ Fuseau horaire configuré : {timezone_str}\n"
                f"Heure actuelle dans ce fuseau : {datetime.now(timezone).strftime('%H:%M:%S')}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")
                ]])
            )
            
            return SETTINGS
            
        except pytz.exceptions.UnknownTimeZoneError:
            # Suggérer des fuseaux horaires similaires
            similar_timezones = [tz for tz in pytz.common_timezones if timezone_str.lower() in tz.lower()]
            
            if similar_timezones:
                keyboard = []
                # Afficher jusqu'à 5 suggestions
                for tz in similar_timezones[:5]:
                    keyboard.append([InlineKeyboardButton(tz, callback_data=f"set_tz_{tz}")])
                
                keyboard.append([InlineKeyboardButton("↩️ Retour", callback_data="set_timezone")])
                
                await update.message.reply_text(
                    f"❌ Fuseau horaire '{timezone_str}' non reconnu.\n\n"
                    f"Voici quelques suggestions :",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    f"❌ Fuseau horaire '{timezone_str}' non reconnu.\n\n"
                    f"Veuillez saisir un fuseau horaire valide (par exemple: Europe/Paris).",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Retour", callback_data="set_timezone")
                    ]])
                )
            
            return WAITING_TIMEZONE
    
    except Exception as e:
        logger.error(f"Erreur lors du traitement du fuseau horaire: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors du traitement de votre saisie.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="settings")
            ]])
        )
        return SETTINGS

async def handle_customer_settings(update, context):
    """Affiche les paramètres de personnalisation"""
    query = update.callback_query
    await query.answer()
    
    # Construire le clavier des options
    keyboard = [
        [InlineKeyboardButton("🖼️ Thumbnail par défaut", callback_data="add_thumbnail")],
        [InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")]
    ]
    
    # Vérifier si un thumbnail est déjà défini
    has_thumbnail = 'user_thumbnail' in context.user_data
    
    # Texte du message
    message = "🎨 Paramètres de personnalisation\n\n"
    message += f"• Thumbnail par défaut: {'✅ Défini' if has_thumbnail else '❌ Non défini'}\n"
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return SETTINGS

async def handle_schedule_time(update, context):
    """Gère la réception de l'heure pour la planification"""
    try:
        time_text = update.message.text.strip()
        
        # Format attendu: HH:MM
        time_pattern = r'^([01]\d|2[0-3]):([0-5]\d)$'
        match = re.match(time_pattern, time_text)
        
        if not match:
            await update.message.reply_text(
                "❌ Format d'heure invalide. Utilisez le format HH:MM (ex: 14:30).",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="schedule_send")
                ]])
            )
            return SCHEDULE_SEND
        
        # Extraire les heures et minutes
        hour, minute = map(int, match.groups())
        
        # Récupérer le jour sélectionné (aujourd'hui ou demain)
        schedule_day = context.user_data.get('schedule_day', 'today')
        
        # Construire la date/heure
        now = datetime.now()
        if schedule_day == 'today':
            schedule_date = datetime(now.year, now.month, now.day, hour, minute)
            # Si l'heure est déjà passée, la reporter au lendemain
            if schedule_date < now:
                await update.message.reply_text(
                    "⚠️ Cette heure est déjà passée pour aujourd'hui.\n"
                    "Veuillez choisir une heure future ou sélectionner demain.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📅 Choisir demain", callback_data="schedule_tomorrow")],
                        [InlineKeyboardButton("↩️ Annuler", callback_data="main_menu")]
                    ])
                )
                return SCHEDULE_SEND
        else:  # tomorrow
            tomorrow = now + timedelta(days=1)
            schedule_date = datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, minute)
        
        # Enregistrer les informations de planification
        if 'current_post' in context.user_data:
            post = context.user_data['current_post']
            post_id = context.user_data.get('current_post_id', f"temp_{int(time.time())}")
            
            # Créer l'ID du job scheduler
            job_id = f"post_{post_id}"
            
            # Planifier le job
            scheduler_manager.scheduler.add_job(
                scheduler_manager.execute_scheduled_post,
                'date',
                run_date=schedule_date,
                args=[post_id],
                id=job_id
            )
            
            # Confirmation
            await update.message.reply_text(
                f"✅ Publication planifiée pour le "
                f"{schedule_date.strftime('%d/%m/%Y à %H:%M')}.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            
            # Nettoyer les données temporaires
            context.user_data.pop('current_post', None)
            context.user_data.pop('current_post_index', None)
            context.user_data.pop('schedule_day', None)
            
            return MAIN_MENU
        else:
            await update.message.reply_text(
                "❌ Aucun post à planifier.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
    
    except Exception as e:
        logger.error(f"Erreur lors de la planification: {e}")
        await update.message.reply_text(
            "❌ Une erreur est survenue lors de la planification.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_compress_file(update, context):
    """Affiche l'interface de compression de fichier"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "⚙️ Fonction de compression non disponible actuellement.\n"
        "Cette fonctionnalité est en cours de développement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def handle_split_file(update, context):
    """Affiche l'interface de découpage de fichier"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "⚙️ Fonction de découpage non disponible actuellement.\n"
        "Cette fonctionnalité est en cours de développement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def handle_channel_info(update, context):
    """Traite les informations du canal fournies par l'utilisateur"""
    logger.info("========== DÉBUT DE HANDLE_CHANNEL_INFO ==========")
    logger.info(f"Message reçu: {update.message.text}")

    user_id = update.effective_user.id
    logger.info(f"User ID: {user_id}")

    message_text = update.message.text

    # Récupérer db_manager
    db_manager_to_use = db_manager

    # Vérifier l'état d'attente
    waiting_info = context.user_data.get('waiting_for_channel_info', False)
    logger.info(f"État d'attente 'waiting_for_channel_info': {waiting_info}")

    # Afficher tout le contexte utilisateur pour débogage
    logger.info(f"Contenu complet de context.user_data: {context.user_data}")

    # Vérifier si on attend des informations de canal
    if not waiting_info:
        logger.info("Pas en attente d'informations de canal, envoi du message d'erreur")
        await update.message.reply_text(
            "❌ Opération non valide. Retournez au menu principal.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

    # Réinitialiser l'état d'attente
    context.user_data['waiting_for_channel_info'] = False
    logger.info("État d'attente réinitialisé à False")

    # Vérifier le format des informations
    try:
        # Format accepté: "Nom du canal, username" ou "Nom du canal, @username" ou "Nom du canal, https://t.me/username"
        parts = message_text.split(',')
        if len(parts) != 2:
            logger.warning(f"Format incorrect: {message_text} (nombre de parties: {len(parts)})")
            raise ValueError("Format incorrect")

        name = parts[0].strip()
        username_part = parts[1].strip()
        logger.info(f"Nom: '{name}', Username original: '{username_part}'")

        # Extraire le username selon différents formats
        if username_part.startswith('@'):
            # Format @username
            username = username_part[1:]  # Supprimer le @ initial
        elif 't.me/' in username_part.lower() or 'telegram.me/' in username_part.lower():
            # Format URL - extraire le username qui est après le dernier /
            username = username_part.split('/')[-1]
        else:
            # Format simple sans @ ni URL
            username = username_part

        logger.info(f"Username après extraction: '{username}'")

        # Nettoyer le username (enlever tous les caractères non alphanumériques sauf _)
        username = ''.join(c for c in username if c.isalnum() or c == '_')
        logger.info(f"Username nettoyé: '{username}'")

        # Vérifier que le username n'est pas vide
        if not username:
            logger.info("Username vide après nettoyage")
            await update.message.reply_text(
                "❌ Username invalide. Veuillez fournir un username valide.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")
                ]])
            )
            return SETTINGS

        # Ajouter le canal à la base de données avec l'ID utilisateur
        try:
            logger.info(f"Tentative d'ajout du canal: {name} (@{username}) pour l'utilisateur {user_id}")
            db_manager_to_use.add_channel(name, username, user_id)
            logger.info(f"Canal ajouté avec succès via db_manager")

            # Message de confirmation avec boutons pour ajouter un autre canal ou revenir au menu
            keyboard = [
                [InlineKeyboardButton("➕ Ajouter un autre canal", callback_data="add_channel")],
                [InlineKeyboardButton("📊 Gérer les canaux", callback_data="manage_channels")],
                [InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")]
            ]
            await update.message.reply_text(
                f"✅ Canal @{username} ajouté avec succès!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SETTINGS

        except Exception as e:
            logger.error(f"Erreur lors de l'ajout du canal dans la base de données: {e}")
            await update.message.reply_text(
                f"❌ Erreur lors de l'ajout du canal: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")
                ]])
            )
            return SETTINGS

    except ValueError:
        # Format incorrect
        await update.message.reply_text(
            "❌ Format incorrect. Utilisez: \"Nom du canal, @username\" ou \"Nom du canal, https://t.me/username\"",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")
            ]])
        )
        return SETTINGS

    except Exception as e:
        logger.error(f"Erreur non gérée dans handle_channel_info: {e}")
        await update.message.reply_text(
            f"❌ Une erreur est survenue: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_add_channel(update, context):
    """Interface pour ajouter un nouveau canal"""
    query = update.callback_query
    await query.answer()
    
    # Marquer l'attente des informations du canal
    context.user_data['waiting_for_channel_info'] = True
    
    await query.edit_message_text(
        "➕ Ajouter un canal Telegram\n\n"
        "Envoyez-moi les informations du canal au format:\n"
        "\"Nom du canal, @username\"\n\n"
        "Exemples:\n"
        "• \"Mon canal, @mon_canal\"\n"
        "• \"Actualités, https://t.me/actualites\"\n\n"
        "⚠️ Assurez-vous que le bot est administrateur du canal!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Annuler", callback_data="manage_channels")
        ]])
    )
    
    return WAITING_CHANNEL_INFO

async def handle_manage_channels(update, context):
    """Affiche la liste des canaux et options de gestion"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Récupérer la liste des canaux
        channels = db_manager.list_channels(update.effective_user.id)
        
        keyboard = []
        
        # Afficher les canaux existants
        if channels:
            for name, username in channels:
                keyboard.append([
                    InlineKeyboardButton(f"{name} (@{username})", callback_data=f"channel_info_{username}"),
                    InlineKeyboardButton("🗑️", callback_data=f"delete_channel_{username}")
                ])
        
        # Boutons d'action
        keyboard.append([InlineKeyboardButton("➕ Ajouter un canal", callback_data="add_channel")])
        keyboard.append([InlineKeyboardButton("↩️ Retour aux paramètres", callback_data="settings")])
        
        # Texte du message
        message = "📊 Gestion des canaux\n\n"
        
        if channels:
            message += "Canaux configurés:\n"
            for i, (name, username) in enumerate(channels, 1):
                message += f"{i}. {name} (@{username})\n"
        else:
            message += "Aucun canal configuré. Utilisez le bouton \"Ajouter un canal\"."
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return SETTINGS
        
    except Exception as e:
        logger.error(f"Erreur dans handle_manage_channels: {e}")
        await query.edit_message_text(
            f"❌ Une erreur est survenue: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_delete_channel(update, context):
    """Gère la suppression d'un canal"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Extraire le username du canal
        channel_username = query.data.split('_')[-1]
        
        # Demander confirmation
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirmer", callback_data=f"confirm_delete_{channel_username}"),
                InlineKeyboardButton("❌ Annuler", callback_data="manage_channels")
            ]
        ]
        
        await query.edit_message_text(
            f"⚠️ Êtes-vous sûr de vouloir supprimer le canal @{channel_username}?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return SETTINGS
        
    except Exception as e:
        logger.error(f"Erreur dans handle_delete_channel: {e}")
        await query.edit_message_text(
            f"❌ Une erreur est survenue: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Retour", callback_data="manage_channels")
            ]])
        )
        return SETTINGS

async def handle_cancel_post(update, context):
    """Gère l'annulation d'un post planifié"""
    query = update.callback_query
    await query.answer()
    
    # Interface simplifiée puisque la fonctionnalité n'est pas complètement implémentée
    await query.edit_message_text(
        "⚙️ Fonction d'annulation non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def handle_confirm_cancel(update, context):
    """Confirme l'annulation d'un post planifié"""
    query = update.callback_query
    await query.answer()
    
    # Interface simplifiée puisque la fonctionnalité n'est pas complètement implémentée
    await query.edit_message_text(
        "⚙️ Fonction de confirmation d'annulation non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def show_scheduled_post(update, context):
    """Affiche les détails d'un post planifié"""
    query = update.callback_query
    await query.answer()
    
    # Interface simplifiée puisque la fonctionnalité n'est pas complètement implémentée
    await query.edit_message_text(
        "⚙️ Fonction d'affichage des posts planifiés non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def handle_delete_post(update, context):
    """Supprime un post de la liste des posts en cours de création"""
    query = update.callback_query
    await query.answer()
    
    try:
        # Extraire l'index du post
        post_index = int(query.data.split("_")[-1])
        
        # Vérifier que le post existe
        if 'posts' not in context.user_data or post_index >= len(context.user_data['posts']):
            await query.edit_message_text(
                "❌ Post introuvable.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
                ]])
            )
            return MAIN_MENU
        
        # Supprimer le post
        removed_post = context.user_data['posts'].pop(post_index)
        post_type = removed_post.get('type', 'inconnu')
        
        # Mettre à jour l'index courant si nécessaire
        if 'current_post_index' in context.user_data and context.user_data['current_post_index'] == post_index:
            context.user_data.pop('current_post_index')
            context.user_data.pop('current_post', None)
        
        # Message de confirmation
        await query.edit_message_text(
            f"✅ Post de type {post_type} supprimé avec succès.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        
        return MAIN_MENU
        
    except Exception as e:
        logger.error(f"Erreur dans handle_delete_post: {e}")
        await query.edit_message_text(
            f"❌ Une erreur est survenue: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Menu principal", callback_data="main_menu")
            ]])
        )
        return MAIN_MENU

async def handle_rename_post(update, context):
    """Interface pour renommer un post (modifier sa légende)"""
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
        context.user_data['waiting_for_rename'] = True
        context.user_data['current_post_index'] = post_index
        context.user_data['current_state'] = POST_ACTIONS

        keyboard = [
            [InlineKeyboardButton("❌ Annuler", callback_data=f"cancel_rename_{post_index}")]
        ]

        # Vérifier si le message contient un média
        message = query.message
        post = context.user_data['posts'][post_index]
        current_caption = post.get("caption", "") if post["type"] != "text" else post.get("content", "")

        info_text = (
            "✏️ Renommer le post\n\n"
            f"Contenu actuel:\n{current_caption[:100]}{'...' if len(current_caption) > 100 else ''}\n\n"
            "Envoyez-moi le nouveau texte pour ce post."
        )

        if message.photo or message.video or message.document:
            # Pour les messages avec média, on envoie un nouveau message
            await context.bot.send_message(
                chat_id=message.chat_id,
                text=info_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Pour les messages texte, on peut modifier le message existant
            await query.edit_message_text(
                info_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        return POST_ACTIONS

    except Exception as e:
        logger.error(f"Erreur lors du renommage du post : {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Erreur lors du renommage du post.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Retour", callback_data="main_menu")]])
        )
        return POST_ACTIONS

async def add_reactions_to_post(update, context):
    """Interface pour ajouter des réactions à un post"""
    query = update.callback_query
    await query.answer()
    
    # Fonction simplifiée car non entièrement implémentée
    await query.edit_message_text(
        "⚙️ Fonction d'ajout de réactions non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def remove_reactions(update, context):
    """Retire les réactions d'un post"""
    query = update.callback_query
    await query.answer()
    
    # Fonction simplifiée car non entièrement implémentée
    await query.edit_message_text(
        "⚙️ Fonction de suppression de réactions non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def add_url_button_to_post(update, context):
    """Interface pour ajouter un bouton URL à un post"""
    query = update.callback_query
    await query.answer()
    
    # Fonction simplifiée car non entièrement implémentée
    await query.edit_message_text(
        "⚙️ Fonction d'ajout de bouton URL non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

async def remove_url_buttons(update, context):
    """Retire les boutons URL d'un post"""
    query = update.callback_query
    await query.answer()
    
    # Fonction simplifiée car non entièrement implémentée
    await query.edit_message_text(
        "⚙️ Fonction de suppression de boutons URL non disponible actuellement.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Retour", callback_data="main_menu")
        ]])
    )
    return MAIN_MENU

if __name__ == '__main__':
    main()