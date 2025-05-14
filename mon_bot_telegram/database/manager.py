from typing import Dict, List, Optional
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from config.settings import settings
import os
import json

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Exception pour les erreurs de base de données"""
    pass


class DatabaseManager:
    """
    Gestionnaire de base de données pour le bot Telegram

    Cette classe gère toutes les opérations liées à la base de données,
    y compris la création de tables, l'ajout de messages et la récupération
    des données.
    """

    def __init__(self, db_path: str = settings.db_config["path"]):
        self.db_path = db_path
        self.connection = None
        self.setup_database()

    def setup_database(self) -> bool:
        """Initialise la base de données et crée les tables nécessaires"""
        try:
            # Assurons-nous que le dossier parent existe
            db_dir = os.path.dirname(self.db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                logger.info(f"Dossier de base de données créé: {db_dir}")
            
            self.connection = sqlite3.connect(
                self.db_path,
                timeout=settings.db_config["timeout"],
                check_same_thread=settings.db_config["check_same_thread"]
            )
            cursor = self.connection.cursor()

            # Table des canaux
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Table des publications avec colonnes pour les réactions et boutons URL
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    post_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    caption TEXT,
                    buttons TEXT,
                    reactions TEXT,
                    scheduled_time TIMESTAMP,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (channel_id) REFERENCES channels (id)
                )
            ''')

            # Table des fuseaux horaires des utilisateurs
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_timezones (
                    user_id INTEGER PRIMARY KEY,
                    timezone TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Vérifier si la colonne reactions existe déjà
            cursor.execute("PRAGMA table_info(posts)")
            columns = cursor.fetchall()
            column_names = [column[1] for column in columns]
            
            # Ajouter la colonne reactions si elle n'existe pas
            if 'reactions' not in column_names:
                cursor.execute("ALTER TABLE posts ADD COLUMN reactions TEXT")
                logger.info("Colonne 'reactions' ajoutée à la table posts")

            self.connection.commit()
            return True

        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la configuration de la base de données: {e}")
            raise DatabaseError(f"Erreur de configuration de la base de données: {e}")

    def check_database_status(self) -> Dict[str, bool]:
        """Vérifie l'état de la base de données"""
        try:
            cursor = self.connection.cursor()

            # Vérifie les tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()

            return {
                "connection": self.connection is not None,
                "tables": len(tables) >= 2,  # Au moins 2 tables (channels et posts)
                "writable": self._test_write()
            }

        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la vérification de la base de données: {e}")
            return {
                "connection": False,
                "tables": False,
                "writable": False
            }

    def _test_write(self) -> bool:
        """Teste si la base de données est accessible en écriture"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def add_channel(self, name: str, username: str) -> bool:
        """Ajoute un nouveau canal à la base de données"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO channels (name, username) VALUES (?, ?)",
                (name, username)
            )
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de l'ajout du canal: {e}")
            raise DatabaseError(f"Erreur lors de l'ajout du canal: {e}")

    def get_channel(self, username: str) -> Optional[Dict]:
        """Récupère les informations d'un canal"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT id, name, username FROM channels WHERE username = ?",
                (username,)
            )
            result = cursor.fetchone()
            if result:
                return {
                    "id": result[0],
                    "name": result[1],
                    "username": result[2]
                }
            logger.info(f"Aucun canal trouvé avec l'username '{username}'")
            return None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération du canal: {e}")
            raise DatabaseError(f"Erreur lors de la récupération du canal: {e}")

    def list_channels(self) -> List[tuple]:
        """Liste tous les canaux"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT id, name, username FROM channels")
            results = cursor.fetchall()
            logger.info(f"Récupération de {len(results)} canaux réussie")
            return results
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la liste des canaux: {e}")
            raise DatabaseError(f"Erreur lors de la liste des canaux: {e}")

    def add_post(self, channel_id: int, post_type: str, content: str,
                 caption: Optional[str] = None, buttons: Optional[List[Dict]] = None,
                 reactions: Optional[List[str]] = None, scheduled_time: Optional[str] = None) -> Optional[int]:
        """Ajoute une nouvelle publication"""
        try:
            cursor = self.connection.cursor()
            # Convertir les boutons et réactions en JSON
            buttons_json = json.dumps(buttons) if buttons else None
            reactions_json = json.dumps(reactions) if reactions else None
            
            cursor.execute(
                """
                INSERT INTO posts 
                (channel_id, post_type, content, caption, buttons, reactions, scheduled_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (channel_id, post_type, content, caption, buttons_json, reactions_json, scheduled_time)
            )
            self.connection.commit()
            return cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de l'ajout de la publication: {e}")
            raise DatabaseError(f"Erreur lors de l'ajout de la publication: {e}")

    def get_scheduled_post(self, post_id: int) -> Optional[Dict]:
        """Récupère une publication planifiée"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT id, channel_id, post_type, content, caption, buttons, reactions, scheduled_time
                FROM posts
                WHERE id = ? AND status = 'pending'
                """,
                (post_id,)
            )
            result = cursor.fetchone()
            if result:
                return {
                    "id": result[0],
                    "channel_id": result[1],
                    "post_type": result[2],
                    "content": result[3],
                    "caption": result[4],
                    "buttons": json.loads(result[5]) if result[5] else None,
                    "reactions": json.loads(result[6]) if result[6] else None,
                    "scheduled_time": result[7]
                }
            return None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération de la publication: {e}")
            raise DatabaseError(f"Erreur lors de la récupération de la publication: {e}")

    def update_post_schedule(self, post_id: int, new_datetime: datetime) -> bool:
        """Met à jour l'horaire d'une publication"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "UPDATE posts SET scheduled_time = ? WHERE id = ?",
                (new_datetime, post_id)
            )
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la mise à jour de l'horaire: {e}")
            raise DatabaseError(f"Erreur lors de la mise à jour de l'horaire: {e}")

    def update_post_reactions(self, post_id: int, reactions: List[str]) -> bool:
        """Met à jour les réactions d'une publication"""
        try:
            cursor = self.connection.cursor()
            reactions_json = json.dumps(reactions) if reactions else None
            cursor.execute(
                "UPDATE posts SET reactions = ? WHERE id = ?",
                (reactions_json, post_id)
            )
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la mise à jour des réactions: {e}")
            raise DatabaseError(f"Erreur lors de la mise à jour des réactions: {e}")

    def update_post_buttons(self, post_id: int, buttons: List[Dict]) -> bool:
        """Met à jour les boutons URL d'une publication"""
        try:
            cursor = self.connection.cursor()
            buttons_json = json.dumps(buttons) if buttons else None
            cursor.execute(
                "UPDATE posts SET buttons = ? WHERE id = ?",
                (buttons_json, post_id)
            )
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la mise à jour des boutons URL: {e}")
            raise DatabaseError(f"Erreur lors de la mise à jour des boutons URL: {e}")

    def delete_post(self, post_id: int) -> bool:
        """Supprime une publication"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            self.connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la suppression de la publication: {e}")
            raise DatabaseError(f"Erreur lors de la suppression de la publication: {e}")

    def get_future_scheduled_posts(self) -> List[Dict]:
        """Récupère toutes les publications planifiées futures"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                SELECT id, channel_id, post_type, content, caption, buttons, reactions, scheduled_time
                FROM posts
                WHERE status = 'pending' AND scheduled_time > datetime('now')
                ORDER BY scheduled_time ASC
                """
            )
            results = cursor.fetchall()
            posts = []
            for result in results:
                posts.append({
                    "id": result[0],
                    "channel_id": result[1],
                    "post_type": result[2],
                    "content": result[3],
                    "caption": result[4],
                    "buttons": json.loads(result[5]) if result[5] else None,
                    "reactions": json.loads(result[6]) if result[6] else None,
                    "scheduled_time": result[7]
                })
            return posts
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération des publications planifiées: {e}")
            raise DatabaseError(f"Erreur lors de la récupération des publications planifiées: {e}")

    def get_user_timezone(self, user_id: int) -> Optional[str]:
        """Récupère le fuseau horaire d'un utilisateur"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT timezone FROM user_timezones WHERE user_id = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else None
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la récupération du fuseau horaire: {e}")
            raise DatabaseError(f"Erreur lors de la récupération du fuseau horaire: {e}")

    def save_user_timezone(self, user_id: int, timezone: str) -> bool:
        """Enregistre le fuseau horaire d'un utilisateur"""
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO user_timezones (user_id, timezone)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                timezone = excluded.timezone,
                updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, timezone)
            )
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de l'enregistrement du fuseau horaire: {e}")
            raise DatabaseError(f"Erreur lors de l'enregistrement du fuseau horaire: {e}")

    def __del__(self):
        """Ferme la connexion à la base de données lors de la destruction de l'objet"""
        if self.connection:
            self.connection.close()