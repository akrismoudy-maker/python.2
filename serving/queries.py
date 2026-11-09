"""Requêtes d'agrégation sur la base d'événements (sqlite).

Chaque fonction retourne une liste de (libellé, nombre), triée par nombre décroissant.
Les nombres sont des SUM(attempts), pour compter aussi les lignes
"message repeated N times".
"""
from storage.event_store import (
    STATUS_FAILED, STATUS_INVALID, STATUS_SUCCESS, EventStore,
)


def _pairs(rows: list[tuple]) -> list[tuple[str, int]]:
    return [(str(label), int(total)) for label, total in rows]


def failed_by_country(store: EventStore, limit: int = 15) -> list[tuple[str, int]]:
    """Tentatives échouées par pays (code ISO, 'Private' ou 'Unknown')."""
    return _pairs(store.query(
        "SELECT COALESCE(country, 'Unknown'), SUM(attempts) FROM events WHERE status = ? "
        "GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?",
        (STATUS_FAILED, limit),
    ))


def success_by_user(store: EventStore, limit: int = 15) -> list[tuple[str, int]]:
    """Connexions réussies par utilisateur."""
    return _pairs(store.query(
        "SELECT username, SUM(attempts) FROM events WHERE status = ? "
        "GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?",
        (STATUS_SUCCESS, limit),
    ))


def invalid_by_user(store: EventStore, limit: int = 15) -> list[tuple[str, int]]:
    """Lignes 'Invalid user' par nom d'utilisateur inexistant."""
    return _pairs(store.query(
        "SELECT username, SUM(attempts) FROM events WHERE status = ? "
        "GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT ?",
        (STATUS_INVALID, limit),
    ))
