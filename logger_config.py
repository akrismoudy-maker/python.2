"""Configuration du logging de l'application.

Chaque module de l'application a son propre logger (getLogger(__name__))
et son propre fichier dans logs/, avec rotation par taille.

Utilisation dans un module :

    from logger_config import get_logger
    logger = get_logger(__name__, "storage.log")
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Final

from config import LOG_DIR

LOG_FORMAT: Final[str] = "%(asctime)s|%(levelname)s|%(name)s|%(message)s"
MAX_BYTES: Final[int] = 1_000_000  # 1 Mo par fichier
BACKUP_COUNT: Final[int] = 5       # 5 anciens fichiers gardés (.1 à .5)


def get_logger(
    name: str,
    log_file: str,
    level: int = logging.DEBUG,
    console: bool = False,
) -> logging.Logger:
    """Retourne le logger `name`, écrit dans logs/<log_file> avec rotation.

    Plusieurs loggers peuvent partager le même fichier (ex : reader.py,
    ingestion.log). Appeler la fonction deux fois pour le même logger
    n'ajoute pas de handler en double.

    Si le dossier ou le fichier de log est inutilisable (permission refusée,
    disque plein...), on retombe sur stderr pour ne jamais perdre l'erreur.
    """
    logger = logging.getLogger(name)
    if logger.handlers:  # déjà configuré
        return logger

    logger.setLevel(level)
    logger.propagate = False  # évite les doublons via le logger root
    formatter = logging.Formatter(LOG_FORMAT)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            filename=LOG_DIR / log_file,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        fallback = logging.StreamHandler(sys.stderr)
        fallback.setFormatter(formatter)
        logger.addHandler(fallback)
        logger.error("Impossible d'ouvrir le fichier de log %s/%s : %s", LOG_DIR, log_file, exc)

    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
