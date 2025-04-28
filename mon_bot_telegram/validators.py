import re
from typing import Optional, Dict, Any
from datetime import datetime
import pytz
from constants import VALIDATION_PATTERNS, ALLOWED_FILE_TYPES, ERROR_MESSAGES

class Validator:
    @staticmethod
    def validate_time(time_str: str) -> Optional[datetime]:
        """Valide et convertit une chaîne d'heure en objet datetime"""
        try:
            if not re.match(VALIDATION_PATTERNS['time'], time_str):
                return None

            if ':' in time_str:
                hour, minute = map(int, time_str.split(':'))
            elif ' ' in time_str:
                hour, minute = map(int, time_str.split())
            else:
                hour = int(time_str)
                minute = 0

            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None

            return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def validate_url(url: str) -> bool:
        """Valide une URL"""
        return bool(re.match(VALIDATION_PATTERNS['url'], url))

    @staticmethod
    def validate_file_type(file_path: str, expected_type: str) -> bool:
        """Valide le type d'un fichier"""
        if expected_type not in ALLOWED_FILE_TYPES:
            return False

        file_ext = file_path.lower().split('.')[-1]
        return f'.{file_ext}' in ALLOWED_FILE_TYPES[expected_type]

    @staticmethod
    def validate_file_size(file_path: str, max_size_bytes: int) -> bool:
        """Valide la taille d'un fichier"""
        try:
            import os
            return os.path.getsize(file_path) <= max_size_bytes
        except (OSError, TypeError):
            return False

    @staticmethod
    def validate_post_data(post_data: Dict[str, Any]) -> bool:
        """Valide les données d'un post"""
        required_fields = ['type', 'content']
        return all(field in post_data for field in required_fields)

    @staticmethod
    def validate_timezone(timezone: str) -> bool:
        """Valide un fuseau horaire"""
        try:
            pytz.timezone(timezone)
            return True
        except pytz.exceptions.UnknownTimeZoneError:
            return False

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Nettoie un texte pour éviter les injections"""
        # Supprimer les caractères potentiellement dangereux
        return re.sub(r'[<>]', '', text)

    @staticmethod
    def validate_buttons(buttons_data: str) -> Optional[Dict]:
        """Valide et parse les données des boutons"""
        try:
            import json
            buttons = json.loads(buttons_data)
            if not isinstance(buttons, list):
                return None

            for button in buttons:
                if not isinstance(button, dict):
                    return None
                if 'text' not in button or 'url' not in button:
                    return None
                if not Validator.validate_url(button['url']):
                    return None

            return buttons
        except (json.JSONDecodeError, TypeError):
            return None