"""Stockage des événements SSH parsés dans une base sqlite3 (bibliothèque standard).

Deux tables :
- events   : un enregistrement par événement (ou par groupe "message repeated N times")
- ip_cache : pays déjà trouvés pour chaque IP, pour ne pas rappeler l'API ipinfo
"""
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterator, Optional, Sequence

from logger_config import get_logger

logger = get_logger(__name__, "storage.log")

STATUS_SUCCESS: Final[str] = "Success"
STATUS_FAILED: Final[str] = "Failed"
STATUS_INVALID: Final[str] = "Invalid"

COUNTRY_UNKNOWN: Final[str] = "Unknown"
COUNTRY_PRIVATE: Final[str] = "Private"

SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT    NOT NULL,                -- 'YYYY-MM-DD HH:MM:SS'
    ip       TEXT    NOT NULL,
    username TEXT    NOT NULL,
    status   TEXT    NOT NULL CHECK (status IN ('Success', 'Failed', 'Invalid')),
    country  TEXT,
    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    source   TEXT    NOT NULL                 -- fichier d'origine
);
CREATE INDEX IF NOT EXISTS idx_events_status ON events (status);
CREATE INDEX IF NOT EXISTS idx_events_ip     ON events (ip);

CREATE TABLE IF NOT EXISTS ip_cache (
    ip         TEXT PRIMARY KEY,
    country    TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class StorageError(Exception):
    """Erreur de stockage (base inaccessible, requête invalide...)."""


@dataclass(frozen=True)
class Event:
    """Un événement d'authentification SSH.

    `attempts` vaut 1 en général ; il vaut N pour une ligne
    "message repeated N times" (N tentatives identiques résumées par syslog).
    """
    timestamp: str
    ip: str
    username: str
    status: str
    attempts: int = 1
    country: Optional[str] = None
    source: str = ""


class EventStore:
    """Accès à la base sqlite des événements."""

    def __init__(self, db_path: Path) -> None:
        self.db_path: Path = db_path
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn: sqlite3.Connection = sqlite3.connect(db_path)
            self._conn.executescript(SCHEMA)
        except OSError as exc:  # dossier non créable, permission refusée...
            logger.exception("Dossier de la base inaccessible : %s", db_path)
            raise StorageError(f"dossier inaccessible : {db_path}") from exc
        except sqlite3.Error as exc:  # fichier verrouillé, corrompu, lecture seule...
            logger.exception("Ouverture de la base impossible : %s", db_path)
            raise StorageError(f"ouverture impossible : {db_path}") from exc
        logger.info("Base ouverte : %s", db_path)

    # --- utilitaires -------------------------------------------------

    @contextmanager
    def _guard(self, action: str) -> Iterator[None]:
        """Log et convertit les erreurs sqlite en StorageError."""
        try:
            yield
        except sqlite3.Error as exc:
            logger.exception("Erreur SQLite pendant : %s", action)
            raise StorageError(f"{action} : {exc}") from exc

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            logger.exception("Erreur à la fermeture de la base")

    def __enter__(self) -> "EventStore":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- événements --------------------------------------------------

    def reset_events(self) -> None:
        """Vide la table events (le cache d'IP est conservé)."""
        with self._guard("vidage de events"), self._conn:
            self._conn.execute("DELETE FROM events")
            self._conn.execute("DELETE FROM sqlite_sequence WHERE name = 'events'")
        logger.info("Table events vidée")

    def add_events(self, events: Sequence[Event]) -> int:
        """Insère les événements en une transaction. Retourne le nombre inséré."""
        rows = [
            (e.timestamp, e.ip, e.username, e.status, e.country, e.attempts, e.source)
            for e in events
        ]
        with self._guard("insertion des événements"), self._conn:
            self._conn.executemany(
                "INSERT INTO events (ts, ip, username, status, country, attempts, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        logger.info("%d événements insérés", len(rows))
        return len(rows)

    def ips_by_priority(self) -> list[str]:
        """IP distinctes, les plus actives en échecs d'abord (utile si l'API est limitée)."""
        rows = self.query(
            "SELECT ip FROM events GROUP BY ip "
            "ORDER BY SUM(CASE WHEN status = 'Failed' THEN attempts ELSE 0 END) DESC, "
            "SUM(attempts) DESC"
        )
        return [ip for (ip,) in rows]

    def query(self, sql: str, params: Sequence[object] = ()) -> list[tuple]:
        """Exécute une requête de lecture (utilisée par serving/)."""
        with self._guard(f"requête : {sql.strip()[:80]}"):
            return self._conn.execute(sql, params).fetchall()

    # --- cache des IP ------------------------------------------------

    def get_cached_countries(self) -> dict[str, str]:
        """Retourne tout le cache {ip: pays}."""
        return dict(self.query("SELECT ip, country FROM ip_cache"))

    def cache_country(self, ip: str, country: str) -> None:
        with self._guard(f"écriture du cache pour {ip}"), self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO ip_cache (ip, country) VALUES (?, ?)", (ip, country)
            )

    def apply_countries(self) -> None:
        """Remplit events.country depuis ip_cache ; sans entrée -> 'Unknown'."""
        with self._guard("mise à jour des pays"), self._conn:
            self._conn.execute(
                "UPDATE events SET country = COALESCE("
                "(SELECT country FROM ip_cache WHERE ip_cache.ip = events.ip), ?)",
                (COUNTRY_UNKNOWN,),
            )
