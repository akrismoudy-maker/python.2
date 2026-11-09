"""Chemins et paramètres communs au projet.

Tout ce qui peut changer d'une machine à l'autre est regroupé ici,
pour ne pas avoir de chemins écrits en dur dans les autres modules.
"""
import os
from pathlib import Path
from typing import Final, Optional

BASE_DIR: Final[Path] = Path(__file__).resolve().parent

DATA_DIR: Final[Path] = BASE_DIR / "data"      # logs auth.log* à analyser
LOG_DIR: Final[Path] = BASE_DIR / "logs"       # logs de l'application
OUTPUT_DIR: Final[Path] = BASE_DIR / "output"  # graphiques PNG + base sqlite
DB_PATH: Final[Path] = OUTPUT_DIR / "events.db"

# Les lignes de auth.log n'ont pas d'année ("May 24 00:04:36").
# On la fixe ici ; elle peut être changée avec la variable d'environnement LOG_YEAR.
LOG_YEAR: Final[int] = int(os.environ.get("LOG_YEAR", "2026"))

# Token ipinfo.io optionnel (variable d'environnement IPINFO_TOKEN).
# Sans token, la limite gratuite est basse (de l'ordre de 1000 requêtes par jour).
IPINFO_TOKEN: Final[Optional[str]] = os.environ.get("IPINFO_TOKEN") or None
IPINFO_URL: Final[str] = "https://ipinfo.io"
IPINFO_TIMEOUT: Final[float] = 5.0  # secondes
