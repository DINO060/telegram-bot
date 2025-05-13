import os
import json
import logging
from logging.handlers import RotatingFileHandler
from functools import wraps
from typing import Optional, List, Dict
import asyncio
from datetime import datetime
import sqlite3
from dotenv import load_dotenv
import re

# Chargement des variables d'environnement
load_dotenv()


# Configuration améliorée du logging
def setup_logging():
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    log_file = 'logs/bot.log'

    # Handler fichier avec rotation
    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5)
    file_handler.setFormatter(log_formatter)

    # Handler console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)

    # Configuration du logger
    logger = logging.getLogger('TelegramBot')
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()


# Classe de configuration sécurisée
class Config:
    def __init__(self):
        # Chargement depuis variables d'environnement
        self.API_ID = os.getenv('API_ID')
        self.API_HASH = os.getenv('API_HASH')
        self.BOT_TOKEN = os.getenv('BOT_TOKEN')
        self.ADMIN_IDS = json.loads(os.getenv('ADMIN_IDS', '[]'))
        self.DOWNLOAD_FOLDER = os.getenv('DOWNLOAD_FOLDER', 'downloads/')
        self.DB_PATH = os.getenv('DB_PATH', 'bot.db')

        # Validation de la configuration
        self.validate_config()

    def validate_config(self):
        if not all([self.API_ID, self.API_HASH, self.BOT_TOKEN]):
            raise ValueError("Configuration invalide: API_ID, API_HASH et BOT_TOKEN sont requis")

        if not os.path.exists(self.DOWNLOAD_FOLDER):
            os.makedirs(self.DOWNLOAD_FOLDER)


# Décorateur pour vérifier les permissions admin
def admin_only(func):
    @wraps(func)
    async def wrapped(update, context, *args, **kwargs):
        if update.effective_user.id not in Config().ADMIN_IDS:
            await update.message.reply_text("❌ Vous n'avez pas les permissions nécessaires.")
            return
        return await func(update, context, *args, **kwargs)

    return wrapped


# Gestionnaire de base de données amélioré
class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.setup_database()

    def setup_database(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Migration de la base de données
                cursor.execute('''CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )''')

                # Vérification de la version actuelle
                cursor.execute('SELECT version FROM schema_version ORDER BY version DESC LIMIT 1')
                result = cursor.fetchone()
                current_version = result[0] if result else 0

                # Application des migrations nécessaires
                self._apply_migrations(cursor, current_version)

                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de l'initialisation de la BDD: {e}")
            raise

    def _apply_migrations(self, cursor, current_version: int):
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
            3: '''CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel_id)''',
            4: '''CREATE INDEX IF NOT EXISTS idx_posts_scheduled ON posts(scheduled_time)'''
        }

        for version, migration in migrations.items():
            if version > current_version:
                try:
                    cursor.execute(migration)
                    cursor.execute('INSERT INTO schema_version (version) VALUES (?)', (version,))
                    logger.info(f"Migration {version} appliquée avec succès")
                except sqlite3.Error as e:
                    logger.error(f"Erreur lors de la migration {version}: {e}")
                    raise

    def create_backup(self) -> bool:
        """Crée une sauvegarde de la base de données"""
        try:
            # Création du dossier backups s'il n'existe pas
            backup_dir = 'backups'
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)

            # Génération du nom du fichier de backup avec timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(backup_dir, f'bot_backup_{timestamp}.db')

            # Connexion à la base de données source
            with sqlite3.connect(self.db_path) as source_conn:
                # Création d'une nouvelle base de données de backup
                with sqlite3.connect(backup_path) as backup_conn:
                    # Copie de toutes les données
                    source_conn.backup(backup_conn)

            # Nettoyage des vieux backups (garde les 5 plus récents)
            self._cleanup_old_backups(backup_dir, keep_count=5)

            logger.info(f"Backup créé avec succès: {backup_path}")
            return True

        except Exception as e:
            logger.error(f"Erreur lors de la création du backup: {e}")
            return False

    def _cleanup_old_backups(self, backup_dir: str, keep_count: int = 5):
        """Nettoie les anciens fichiers de backup"""
        try:
            # Liste tous les fichiers de backup
            backup_files = [f for f in os.listdir(backup_dir) if f.startswith('bot_backup_')]

            # Trie les fichiers par date de création
            backup_files.sort(reverse=True)

            # Supprime les fichiers excédentaires
            for old_backup in backup_files[keep_count:]:
                os.remove(os.path.join(backup_dir, old_backup))
                logger.info(f"Ancien backup supprimé: {old_backup}")

        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des backups: {e}")

    def restore_from_backup(self, backup_file: str) -> bool:
        """Restaure la base de données à partir d'un backup"""
        try:
            backup_path = os.path.join('backups', backup_file)
            if not os.path.exists(backup_path):
                logger.error(f"Fichier de backup non trouvé: {backup_path}")
                return False

            # Création d'une copie temporaire de la base actuelle
            temp_backup = f"{self.db_path}.temp"
            with sqlite3.connect(self.db_path) as current_db:
                with sqlite3.connect(temp_backup) as temp_db:
                    current_db.backup(temp_db)

            try:
                # Restauration depuis le backup
                with sqlite3.connect(backup_path) as backup_conn:
                    with sqlite3.connect(self.db_path) as target_conn:
                        backup_conn.backup(target_conn)

                # Suppression de la copie temporaire
                os.remove(temp_backup)
                logger.info(f"Base de données restaurée depuis: {backup_file}")
                return True

            except Exception as restore_error:
                # En cas d'erreur, on restaure la copie temporaire
                logger.error(f"Erreur lors de la restauration: {restore_error}")
                with sqlite3.connect(temp_backup) as temp_db:
                    with sqlite3.connect(self.db_path) as current_db:
                        temp_db.backup(current_db)
                os.remove(temp_backup)
                return False

        except Exception as e:
            logger.error(f"Erreur lors de la restauration du backup: {e}")
            return False

    def get_connection(self):
        return sqlite3.connect(self.db_path)


# Gestionnaire de ressources
class ResourceManager:
    def __init__(self, download_folder: str, max_storage_mb: int = 1000):
        self.download_folder = download_folder
        self.max_storage_bytes = max_storage_mb * 1024 * 1024

    async def cleanup_old_files(self, max_age_hours: int = 24):
        """Nettoie les fichiers plus vieux que max_age_hours"""
        try:
            now = datetime.now()
            for filename in os.listdir(self.download_folder):
                filepath = os.path.join(self.download_folder, filename)
                file_modified = datetime.fromtimestamp(os.path.getmtime(filepath))
                if (now - file_modified).total_seconds() > max_age_hours * 3600:
                    os.remove(filepath)
                    logger.info(f"Fichier supprimé: {filename}")
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des fichiers: {e}")

    def check_storage_usage(self) -> bool:
        """Vérifie si l'utilisation du stockage est dans les limites"""
        total_size = sum(os.path.getsize(os.path.join(self.download_folder, f))
                         for f in os.listdir(self.download_folder))
        return total_size <= self.max_storage_bytes


# Gestionnaire de tâches planifiées
class SchedulerManager:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def restore_scheduled_tasks(self, scheduler):
        """Restaure les tâches planifiées depuis la base de données"""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, channel_id, type, content, scheduled_time 
                    FROM posts 
                    WHERE scheduled_time > datetime('now')
                ''')
                scheduled_posts = cursor.fetchall()

                for post in scheduled_posts:
                    scheduled_time = datetime.strptime(post[4], '%Y-%m-%d %H:%M:%S')
                    scheduler.add_job(
                        'send_post_now',  # Nom de la fonction à appeler
                        'date',
                        run_date=scheduled_time,
                        args=[post[0]],  # post_id
                        id=f'post_{post[0]}'
                    )
                    logger.info(f"Tâche restaurée pour le post {post[0]}")
        except Exception as e:
            logger.error(f"Erreur lors de la restauration des tâches: {e}")


# Système de retry pour les opérations réseau
async def retry_operation(operation, max_retries=3, delay=1):
    """Réessaie une opération en cas d'échec"""
    for attempt in range(max_retries):
        try:
            return await operation()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Tentative {attempt + 1} échouée: {e}")
            await asyncio.sleep(delay * (attempt + 1))


# Validation des entrées utilisateur
class InputValidator:
    @staticmethod
    def validate_url(url: str) -> bool:
        """Valide une URL"""
        url_pattern = r'https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)'
        return re.match(url_pattern, url) is not None

    @staticmethod
    def validate_channel_name(name: str) -> bool:
        """Valide un nom de canal"""
        return re.match(r'^@?[a-zA-Z0-9_]{5,32}$', name) is not None

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Nettoie le texte des caractères potentiellement dangereux"""
        return text.replace('<', '&lt;').replace('>', '&gt;')


# Initialisation
def initialize_bot():
    """Initialise tous les composants du bot"""
    try:
        config = Config()
        db_manager = DatabaseManager(config.DB_PATH)
        resource_manager = ResourceManager(config.DOWNLOAD_FOLDER)
        # Ne pas créer d'instance de scheduler_manager ici pour éviter les conflits
        # La gestion du scheduler est faite dans bot.py

        return config, db_manager, resource_manager
    except Exception as e:
        logger.critical(f"Erreur lors de l'initialisation du bot: {e}")
        raise