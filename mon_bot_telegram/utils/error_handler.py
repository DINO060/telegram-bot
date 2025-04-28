import logging
from typing import Optional, Type, Callable, Awaitable
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger('TelegramBot')

class BotError(Exception):
    """Classe de base pour les erreurs du bot"""
    def __init__(self, message: str, user_message: Optional[str] = None):
        self.message = message
        self.user_message = user_message or "Une erreur est survenue. Veuillez réessayer plus tard."
        super().__init__(message)

class DatabaseError(BotError):
    """Erreur liée à la base de données"""
    pass

class ValidationError(BotError):
    """Erreur de validation"""
    pass

class ResourceError(BotError):
    """Erreur liée aux ressources"""
    pass

async def handle_error(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    error: Exception
) -> None:
    """
    Gestionnaire centralisé des erreurs
    
    Args:
        update: Mise à jour Telegram
        context: Contexte du bot
        error: Exception à gérer
    """
    try:
        # Log de l'erreur
        logger.error(f"Erreur non gérée: {error}", exc_info=True)
        
        # Message par défaut
        error_message = "Une erreur est survenue. Veuillez réessayer plus tard."
        
        # Messages personnalisés selon le type d'erreur
        if isinstance(error, BotError):
            error_message = error.user_message
        elif isinstance(error, DatabaseError):
            error_message = "Erreur de base de données. Veuillez réessayer plus tard."
        elif isinstance(error, ValidationError):
            error_message = "Données invalides. Veuillez vérifier votre saisie."
        elif isinstance(error, ResourceError):
            error_message = "Erreur de ressources. Veuillez réessayer plus tard."
        
        # Envoi du message d'erreur à l'utilisateur
        if update.effective_message:
            await update.effective_message.reply_text(error_message)
            
    except Exception as e:
        logger.critical(f"Erreur dans le gestionnaire d'erreurs: {e}", exc_info=True)

def error_handler(
    error_types: Optional[list[Type[Exception]]] = None
) -> Callable[[Callable], Callable]:
    """
    Décorateur pour la gestion des erreurs
    
    Args:
        error_types: Types d'erreurs à gérer
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs) -> Awaitable:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if error_types and not any(isinstance(e, error_type) for error_type in error_types):
                    raise
                
                # Récupération du contexte
                update = None
                context = None
                
                for arg in args:
                    if isinstance(arg, Update):
                        update = arg
                    elif isinstance(arg, ContextTypes.DEFAULT_TYPE):
                        context = arg
                
                if update and context:
                    await handle_error(update, context, e)
                else:
                    logger.error(f"Erreur sans contexte: {e}", exc_info=True)
                
                return None
                
        return wrapper
    return decorator 