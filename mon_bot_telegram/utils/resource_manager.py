import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import logging
from typing import List, Optional

logger = logging.getLogger('TelegramBot')

class ResourceManager:
    """Gestionnaire de ressources pour le bot"""
    
    def __init__(self, download_folder: Path, max_storage_mb: int = 1000):
        """
        Initialise le gestionnaire de ressources
        
        Args:
            download_folder: Dossier de téléchargement
            max_storage_mb: Limite de stockage en Mo
        """
        self.download_folder = Path(download_folder)
        self.max_storage_bytes = max_storage_mb * 1024 * 1024
        
        # Création du dossier s'il n'existe pas
        self.download_folder.mkdir(parents=True, exist_ok=True)
    
    async def cleanup_old_files(self, max_age_hours: int = 24) -> None:
        """
        Nettoie les fichiers plus vieux que max_age_hours
        
        Args:
            max_age_hours: Âge maximum des fichiers en heures
        """
        try:
            now = datetime.now()
            cutoff_time = now - timedelta(hours=max_age_hours)
            
            for file_path in self.download_folder.glob('*'):
                if file_path.is_file():
                    file_modified = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_modified < cutoff_time:
                        try:
                            file_path.unlink()
                            logger.info(f"Fichier supprimé: {file_path.name}")
                        except Exception as e:
                            logger.error(f"Erreur lors de la suppression de {file_path.name}: {e}")
                            
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des fichiers: {e}")
    
    def check_storage_usage(self) -> bool:
        """
        Vérifie si l'utilisation du stockage est dans les limites
        
        Returns:
            bool: True si l'utilisation est dans les limites
        """
        try:
            total_size = sum(f.stat().st_size for f in self.download_folder.glob('*') if f.is_file())
            is_under_limit = total_size <= self.max_storage_bytes
            
            if not is_under_limit:
                logger.warning(
                    f"Limite de stockage dépassée: {total_size / (1024*1024):.2f}MB / "
                    f"{self.max_storage_bytes / (1024*1024):.2f}MB"
                )
                
            return is_under_limit
            
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de l'espace de stockage: {e}")
            return False
    
    def get_storage_info(self) -> dict:
        """
        Récupère les informations sur l'utilisation du stockage
        
        Returns:
            dict: Informations sur le stockage
        """
        try:
            total_size = sum(f.stat().st_size for f in self.download_folder.glob('*') if f.is_file())
            file_count = sum(1 for _ in self.download_folder.glob('*') if _.is_file())
            
            return {
                'total_size_mb': total_size / (1024 * 1024),
                'max_size_mb': self.max_storage_bytes / (1024 * 1024),
                'file_count': file_count,
                'is_under_limit': total_size <= self.max_storage_bytes
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des informations de stockage: {e}")
            return {
                'total_size_mb': 0,
                'max_size_mb': self.max_storage_bytes / (1024 * 1024),
                'file_count': 0,
                'is_under_limit': False
            }
    
    def clear_storage(self) -> bool:
        """
        Vide complètement le dossier de stockage
        
        Returns:
            bool: True si le nettoyage a réussi
        """
        try:
            for file_path in self.download_folder.glob('*'):
                if file_path.is_file():
                    file_path.unlink()
                elif file_path.is_dir():
                    shutil.rmtree(file_path)
                    
            logger.info("Stockage vidé avec succès")
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage du stockage: {e}")
            return False 