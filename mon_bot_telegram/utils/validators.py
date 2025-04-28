import re
from typing import Optional, Union
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger('TelegramBot')

class ValidationError(Exception):
    """Erreur de validation des données"""
    pass

class PostType(Enum):
    """Types de publications supportés"""
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    TEXT = "text"

class Validator:
    """Classe de validation des données"""
    
    @staticmethod
    def validate_username(username: str) -> str:
        """
        Valide un nom d'utilisateur Telegram
        
        Args:
            username: Nom d'utilisateur à valider
            
        Returns:
            Nom d'utilisateur validé
            
        Raises:
            ValidationError: Si le nom d'utilisateur est invalide
        """
        if not username:
            raise ValidationError("Le nom d'utilisateur ne peut pas être vide")
            
        # Supprime le @ s'il est présent
        username = username.lstrip('@')
        
        # Vérifie le format
        if not re.match(r'^[a-zA-Z0-9_]{5,32}$', username):
            raise ValidationError(
                "Le nom d'utilisateur doit contenir entre 5 et 32 caractères "
                "alphanumériques ou underscores"
            )
            
        return username
    
    @staticmethod
    def validate_channel_id(channel_id: Union[int, str]) -> int:
        """
        Valide un ID de canal Telegram
        
        Args:
            channel_id: ID de canal à valider
            
        Returns:
            ID de canal validé
            
        Raises:
            ValidationError: Si l'ID est invalide
        """
        try:
            channel_id = int(channel_id)
        except (ValueError, TypeError):
            raise ValidationError("L'ID du canal doit être un nombre")
            
        if channel_id <= 0:
            raise ValidationError("L'ID du canal doit être positif")
            
        return channel_id
    
    @staticmethod
    def validate_post_type(post_type: Union[str, PostType]) -> PostType:
        """
        Valide un type de publication
        
        Args:
            post_type: Type de publication à valider
            
        Returns:
            Type de publication validé
            
        Raises:
            ValidationError: Si le type est invalide
        """
        if isinstance(post_type, PostType):
            return post_type
            
        try:
            return PostType(post_type.lower())
        except ValueError:
            raise ValidationError(
                f"Type de publication invalide. Types supportés: "
                f"{', '.join(t.value for t in PostType)}"
            )
    
    @staticmethod
    def validate_schedule_time(schedule_time: Union[str, datetime]) -> datetime:
        """
        Valide une date de programmation
        
        Args:
            schedule_time: Date à valider
            
        Returns:
            Date validée
            
        Raises:
            ValidationError: Si la date est invalide
        """
        if isinstance(schedule_time, datetime):
            if schedule_time <= datetime.now():
                raise ValidationError(
                    "La date de programmation doit être dans le futur"
                )
            return schedule_time
            
        try:
            # Essaye différents formats de date
            formats = [
                "%Y-%m-%d %H:%M",
                "%d/%m/%Y %H:%M",
                "%d-%m-%Y %H:%M"
            ]
            
            for fmt in formats:
                try:
                    dt = datetime.strptime(schedule_time, fmt)
                    if dt <= datetime.now():
                        raise ValidationError(
                            "La date de programmation doit être dans le futur"
                        )
                    return dt
                except ValueError:
                    continue
                    
            raise ValidationError(
                "Format de date invalide. Utilisez YYYY-MM-DD HH:MM ou "
                "DD/MM/YYYY HH:MM"
            )
            
        except Exception as e:
            raise ValidationError(f"Erreur de validation de la date: {e}")
    
    @staticmethod
    def validate_caption(caption: Optional[str], max_length: int = 1024) -> Optional[str]:
        """
        Valide une légende de publication
        
        Args:
            caption: Légende à valider
            max_length: Longueur maximale autorisée
            
        Returns:
            Légende validée
            
        Raises:
            ValidationError: Si la légende est invalide
        """
        if caption is None:
            return None
            
        if len(caption) > max_length:
            raise ValidationError(
                f"La légende ne peut pas dépasser {max_length} caractères"
            )
            
        return caption.strip()
    
    @staticmethod
    def validate_file_size(size_bytes: int, max_size_mb: int = 50) -> int:
        """
        Valide la taille d'un fichier
        
        Args:
            size_bytes: Taille en octets
            max_size_mb: Taille maximale en Mo
            
        Returns:
            Taille validée
            
        Raises:
            ValidationError: Si la taille est invalide
        """
        max_bytes = max_size_mb * 1024 * 1024
        
        if size_bytes <= 0:
            raise ValidationError("La taille du fichier doit être positive")
            
        if size_bytes > max_bytes:
            raise ValidationError(
                f"La taille du fichier ne peut pas dépasser {max_size_mb} Mo"
            )
            
        return size_bytes

class InputValidator:
    """Classe de validation des entrées utilisateur"""
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """
        Valide une URL
        
        Args:
            url: L'URL à valider
            
        Returns:
            bool: True si l'URL est valide
        """
        url_pattern = r'https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)'
        is_valid = re.match(url_pattern, url) is not None
        if not is_valid:
            logger.warning(f"URL invalide: {url}")
        return is_valid
    
    @staticmethod
    def validate_channel_name(name: str) -> bool:
        """
        Valide un nom de canal
        
        Args:
            name: Le nom du canal à valider
            
        Returns:
            bool: True si le nom est valide
        """
        is_valid = re.match(r'^@?[a-zA-Z0-9_]{5,32}$', name) is not None
        if not is_valid:
            logger.warning(f"Nom de canal invalide: {name}")
        return is_valid
    
    @staticmethod
    def sanitize_text(text: str) -> str:
        """
        Nettoie le texte des caractères potentiellement dangereux
        
        Args:
            text: Le texte à nettoyer
            
        Returns:
            str: Le texte nettoyé
        """
        # Remplacement des caractères HTML dangereux
        text = text.replace('<', '&lt;').replace('>', '&gt;')
        
        # Suppression des caractères de contrôle
        text = ''.join(char for char in text if ord(char) >= 32)
        
        return text
    
    @staticmethod
    def validate_datetime(datetime_str: str) -> Optional[str]:
        """
        Valide une chaîne de date/heure
        
        Args:
            datetime_str: La chaîne de date/heure à valider
            
        Returns:
            Optional[str]: La date/heure formatée si valide, None sinon
        """
        try:
            # Format attendu: JJ/MM/AAAA HH:MM
            datetime_pattern = r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$'
            if not re.match(datetime_pattern, datetime_str):
                logger.warning(f"Format de date/heure invalide: {datetime_str}")
                return None
                
            # Vérification de la validité de la date
            day, month, year = map(int, datetime_str.split()[0].split('/'))
            if not (1 <= day <= 31 and 1 <= month <= 12 and year >= 2023):
                logger.warning(f"Date invalide: {datetime_str}")
                return None
                
            # Vérification de la validité de l'heure
            hour, minute = map(int, datetime_str.split()[1].split(':'))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                logger.warning(f"Heure invalide: {datetime_str}")
                return None
                
            return datetime_str
            
        except Exception as e:
            logger.error(f"Erreur lors de la validation de la date/heure: {e}")
            return None 