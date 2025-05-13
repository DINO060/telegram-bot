#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Chemin de la base de données
DB_PATH = "bot.db"

async def simpleadd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Commande simple pour ajouter un canal directement à la base de données"""
    logger.info("=== COMMANDE SIMPLEADD APPELÉE ===")
    
    # Extraire les arguments de la commande
    args = context.args
    if not args or len(' '.join(args).split(',')) != 2:
        await update.message.reply_text(
            "ℹ️ Format correct: /simpleadd Nom du canal, @username\n\n"
            "Exemples:\n"
            "- /simpleadd Mon Canal, @username\n"
            "- /simpleadd Mon Canal, username\n"
            "- /simpleadd Mon Canal, https://t.me/username"
        )
        return
    
    # Joindre les arguments et les séparer par la virgule
    channel_info = ' '.join(args)
    name, username_part = map(str.strip, channel_info.split(',', 1))
    
    # Extraction de l'username
    if username_part.startswith('@'):
        username = username_part[1:]
    elif 't.me/' in username_part.lower():
        username = username_part.split('/')[-1]
    else:
        username = username_part
    
    # Nettoyage de l'username
    username = ''.join(c for c in username if c.isalnum() or c == '_')
    
    # Vérification que l'username n'est pas vide
    if not username:
        await update.message.reply_text("❌ Username invalide. Veuillez réessayer.")
        return
    
    user_id = update.effective_user.id
    logger.info(f"Tentative d'ajout: Nom={name}, Username={username}, UserID={user_id}")
    
    # Insertion directe dans la base de données
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Vérifier si la table et la colonne existent
            cursor.execute("PRAGMA table_info(channels)")
            columns = [col[1] for col in cursor.fetchall()]
            logger.info(f"Structure de la table channels: {columns}")
            
            # Insertion avec ou sans user_id selon la structure
            if 'user_id' in columns:
                cursor.execute(
                    "INSERT INTO channels (name, username, user_id) VALUES (?, ?, ?)",
                    (name, username, user_id)
                )
            else:
                cursor.execute(
                    "INSERT INTO channels (name, username) VALUES (?, ?)",
                    (name, username)
                )
            
            conn.commit()
            logger.info("Canal ajouté avec succès")
            
            # Message de confirmation
            await update.message.reply_text(
                f"✅ Canal '{name}' (@{username}) ajouté avec succès!"
            )
    
    except sqlite3.IntegrityError:
        await update.message.reply_text("⚠️ Ce canal existe déjà.")
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite: {e}")
        await update.message.reply_text(f"❌ Erreur de base de données: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur générale: {e}")
        await update.message.reply_text(f"❌ Erreur inattendue: {str(e)}")

async def checkdb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Vérifie la structure de la base de données et retourne des informations de diagnostic"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Vérifier les tables existantes
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            # Vérifier la structure de la table channels
            cursor.execute("PRAGMA table_info(channels)")
            columns = cursor.fetchall()
            
            # Compter les canaux
            cursor.execute("SELECT COUNT(*) FROM channels")
            count = cursor.fetchone()[0]
            
            # Compter les canaux par utilisateur si la colonne existe
            user_counts = []
            if any(col[1] == 'user_id' for col in columns):
                cursor.execute("SELECT user_id, COUNT(*) FROM channels GROUP BY user_id")
                user_counts = cursor.fetchall()
            
            # Construire le message de diagnostic
            message = "📊 Diagnostic de la base de données :\n\n"
            message += f"Tables: {', '.join(t[0] for t in tables)}\n\n"
            message += "Structure de la table channels:\n"
            for col in columns:
                message += f"- {col[1]} ({col[2]})\n"
            
            message += f"\nNombre total de canaux: {count}\n"
            
            if user_counts:
                message += "\nCanaux par utilisateur:\n"
                for user_id, count in user_counts:
                    message += f"- User {user_id}: {count} canaux\n"
            
            await update.message.reply_text(message)
            
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite dans checkdb: {e}")
        await update.message.reply_text(f"❌ Erreur lors de la vérification: {str(e)}")
    except Exception as e:
        logger.error(f"Erreur générale dans checkdb: {e}")
        await update.message.reply_text(f"❌ Erreur inattendue: {str(e)}")

def main():
    """Fonction principale pour démarrer le bot de test avec les commandes simples"""
    # Remplacer YOUR_BOT_TOKEN par votre token Telegram
    application = ApplicationBuilder().token("YOUR_BOT_TOKEN").build()
    
    # Ajouter les handlers pour nos commandes
    application.add_handler(CommandHandler("simpleadd", simpleadd))
    application.add_handler(CommandHandler("checkdb", checkdb))
    
    # Démarrer le bot
    logger.info("Bot de commandes simples démarré")
    application.run_polling()

if __name__ == "__main__":
    main() 