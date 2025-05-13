#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sqlite3
import logging
import sys
import os
from pathlib import Path

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Chemin de la base de données
DEFAULT_DB_PATH = "bot.db"

def fix_database(db_path=None):
    """
    Script pour vérifier et réparer la structure de la base de données
    """
    if not db_path:
        db_path = DEFAULT_DB_PATH

    logger.info(f"Vérification de la base de données: {db_path}")
    
    # Vérifier si le fichier existe
    if not os.path.exists(db_path):
        logger.error(f"Base de données introuvable: {db_path}")
        return False
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # 1. Vérifier si la table 'channels' existe
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'")
            if not cursor.fetchone():
                logger.error("Table 'channels' introuvable! Création de la table...")
                cursor.execute('''
                    CREATE TABLE channels (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        username TEXT UNIQUE NOT NULL,
                        user_id INTEGER DEFAULT NULL
                    )
                ''')
                logger.info("Table 'channels' créée avec succès")
            else:
                logger.info("Table 'channels' trouvée")
            
            # 2. Vérifier les colonnes existantes dans 'channels'
            cursor.execute("PRAGMA table_info(channels)")
            columns = cursor.fetchall()
            column_names = [col[1] for col in columns]
            logger.info(f"Colonnes existantes dans 'channels': {column_names}")
            
            # 3. Ajouter la colonne 'user_id' si elle n'existe pas
            if 'user_id' not in column_names:
                logger.info("Ajout de la colonne 'user_id' à la table 'channels'...")
                cursor.execute("ALTER TABLE channels ADD COLUMN user_id INTEGER DEFAULT NULL")
                logger.info("Colonne 'user_id' ajoutée avec succès")
            else:
                logger.info("Colonne 'user_id' déjà présente")
            
            # 4. Vérifier les index existants
            cursor.execute("PRAGMA index_list(channels)")
            indexes = cursor.fetchall()
            index_names = [idx[1] for idx in indexes]
            logger.info(f"Index existants: {index_names}")
            
            # 5. Ajouter un index sur 'user_id' si nécessaire
            if not any('user_id' in idx.lower() for idx in index_names):
                logger.info("Ajout d'un index sur 'user_id'...")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_channels_user_id ON channels(user_id)")
                logger.info("Index sur 'user_id' créé avec succès")
            else:
                logger.info("Index sur 'user_id' déjà présent")
            
            # 6. Compter les enregistrements dans 'channels'
            cursor.execute("SELECT COUNT(*) FROM channels")
            count = cursor.fetchone()[0]
            logger.info(f"Nombre total de canaux: {count}")
            
            # 7. Récupérer et afficher quelques exemples
            cursor.execute("SELECT id, name, username, user_id FROM channels LIMIT 5")
            channels = cursor.fetchall()
            if channels:
                logger.info("Exemples de canaux dans la base de données:")
                for channel in channels:
                    logger.info(f"ID: {channel[0]}, Nom: {channel[1]}, Username: {channel[2]}, User ID: {channel[3]}")
            
            # Commit des modifications
            conn.commit()
            logger.info("Base de données vérifiée et mise à jour avec succès")
            return True
            
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de la vérification/réparation: {e}")
        return False
    except Exception as e:
        logger.error(f"Erreur générale: {e}")
        return False

def main():
    """Fonction principale"""
    logger.info("=== SCRIPT DE RÉPARATION DE LA BASE DE DONNÉES ===")
    
    # Vérifier les arguments
    db_path = DEFAULT_DB_PATH
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    # Exécuter la réparation
    success = fix_database(db_path)
    
    if success:
        logger.info("Réparation terminée avec succès!")
        sys.exit(0)
    else:
        logger.error("Échec de la réparation.")
        sys.exit(1)

if __name__ == "__main__":
    main() 