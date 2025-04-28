from typing import Dict, List, Optional
import os
from pathlib import Path
import logging
from dotenv import load_dotenv

# Chargement des variables d'environnement
load_dotenv()

# Configuration du logging
logger = logging.getLogger(__name__)

# Chemins des dossiers
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "bot.db"
DOWNLOAD_FOLDER = BASE_DIR / "downloads"
BACKUP_FOLDER = BASE_DIR / "backups"

# Création des dossiers si nécessaire
for folder in [DOWNLOAD_FOLDER, BACKUP_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)

# Configuration du bot
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN n'est pas défini dans les variables d'environnement")

# Configuration de la base de données
DB_CONFIG = {
    "path": str(DB_PATH),
    "timeout": 30,
    "check_same_thread": False
}

# Configuration des limites
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 Mo
MAX_STORAGE_SIZE = 1000 * 1024 * 1024  # 1 Go
MAX_BACKUP_FILES = 5

# Messages d'erreur
ERROR_MESSAGES = {
    "invalid_time": "Format d'heure invalide. Utilisez HH:MM",
    "file_too_large": "Le fichier est trop volumineux",
    "storage_full": "L'espace de stockage est plein",
    "database_error": "Erreur de base de données",
    "permission_denied": "Permission refusée"
}

# Configuration des timezones
DEFAULT_TIMEZONE = "UTC"
SUPPORTED_TIMEZONES = [
    "UTC",
    "Europe/Paris",
    "America/New_York",
    "Asia/Tokyo"
]

# Configuration des types de fichiers autorisés
ALLOWED_FILE_TYPES = {
    "photo": [".jpg", ".jpeg", ".png", ".gif"],
    "video": [".mp4", ".mov", ".avi"],
    "document": [".pdf", ".doc", ".docx", ".txt"]
}

# Configuration des réactions
DEFAULT_REACTIONS = ["👍", "❤️", "🔥", "🎉", "🤔"]

# Configuration des boutons
MAX_BUTTONS_PER_ROW = 3
MAX_BUTTONS_TOTAL = 8

# Configuration des tâches planifiées
CLEANUP_INTERVAL = 3600  # 1 heure
BACKUP_INTERVAL = 86400  # 24 heures

# Classe pour gérer les paramètres
class Settings:
    def __init__(self):
        self.bot_token = BOT_TOKEN
        self.db_config = DB_CONFIG
        self.max_file_size = MAX_FILE_SIZE
        self.max_storage_size = MAX_STORAGE_SIZE
        self.max_backup_files = MAX_BACKUP_FILES
        self.error_messages = ERROR_MESSAGES
        self.default_timezone = DEFAULT_TIMEZONE
        self.supported_timezones = SUPPORTED_TIMEZONES
        self.allowed_file_types = ALLOWED_FILE_TYPES
        self.default_reactions = DEFAULT_REACTIONS
        self.max_buttons_per_row = MAX_BUTTONS_PER_ROW
        self.max_buttons_total = MAX_BUTTONS_TOTAL
        self.cleanup_interval = CLEANUP_INTERVAL
        self.backup_interval = BACKUP_INTERVAL

# Instance unique des paramètres
settings = Settings()