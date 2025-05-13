#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sqlite3
import logging
import sys
import os

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def migrate_channels():
    """
    Migre les canaux existants pour ajouter l'ID utilisateur
    Attribue par défaut l'ID 0 (système) aux canaux existants
    """
    # Chemin direct vers la base de données
    db_path = 'bot.db'
    if not os.path.exists(db_path):
        logger.error(f"Base de données non trouvée à l'emplacement: {db_path}")
        logger.info("Recherche de la base de données dans le répertoire courant...")
        # Liste tous les fichiers .db du répertoire courant
        db_files = [f for f in os.listdir('.') if f.endswith('.db')]
        if db_files:
            logger.info(f"Fichiers de base de données trouvés: {db_files}")
            db_path = db_files[0]
            logger.info(f"Utilisation de la base de données: {db_path}")
        else:
            logger.error("Aucune base de données trouvée")
            return False
    
    try:
        # Vérifier si la colonne user_id existe déjà
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            logger.info(f"Connexion établie avec la base de données {db_path}")
            
            # Vérifier si la table channels existe
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'")
            if not cursor.fetchone():
                logger.error("La table 'channels' n'existe pas")
                return False
                
            # Vérifier si la colonne existe
            cursor.execute("PRAGMA table_info(channels)")
            columns = cursor.fetchall()
            logger.info(f"Colonnes existantes: {[col[1] for col in columns]}")
            
            column_names = [col[1] for col in columns]
            if 'user_id' not in column_names:
                # Ajouter la colonne user_id
                logger.info("Ajout de la colonne user_id à la table channels")
                cursor.execute("ALTER TABLE channels ADD COLUMN user_id INTEGER DEFAULT NULL")
                
                # Créer un index sur la colonne
                logger.info("Création de l'index sur user_id")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_channels_user ON channels(user_id)")
            else:
                logger.info("La colonne user_id existe déjà")
            
            # Mettre à jour les canaux existants avec l'ID système
            logger.info("Attribution de l'ID système (0) aux canaux existants")
            cursor.execute("UPDATE channels SET user_id = 0 WHERE user_id IS NULL")
            
            # Compter les canaux migrés
            cursor.execute("SELECT COUNT(*) FROM channels WHERE user_id = 0")
            count = cursor.fetchone()[0]
            
            # Valider les modifications
            conn.commit()
            
            logger.info(f"Migration terminée. {count} canaux ont été attribués à l'utilisateur système.")
            
            # Afficher les canaux migrés
            cursor.execute("SELECT id, name, username, user_id FROM channels")
            channels = cursor.fetchall()
            for channel in channels:
                logger.info(f"Canal: {channel}")
            
            return True
            
    except sqlite3.Error as e:
        logger.error(f"Erreur lors de la migration: {e}")
        return False
        
if __name__ == "__main__":
    logger.info("Démarrage de la migration des canaux...")
    success = migrate_channels()
    
    if success:
        logger.info("Migration terminée avec succès!")
        sys.exit(0)
    else:
        logger.error("Échec de la migration.")
        sys.exit(1) 