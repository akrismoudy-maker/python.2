"""Orchestration du pipeline : lecture -> parsing -> stockage -> géolocalisation.

Étapes de run_pipeline() :
1. lire tous les fichiers de data/ (.gz compris)      -> pipeline.reader
2. parser chaque ligne en Event                        -> pipeline.parser
3. stocker les événements dans sqlite                  -> storage.event_store
4. trouver le pays de chaque IP et l'ajouter           -> pipeline.geo
Le dashboard (serving/) est lancé ensuite par main.py.
"""
from collections import Counter
from pathlib import Path

from config import DATA_DIR, DB_PATH, LOG_YEAR
from logger_config import get_logger
from pipeline import reader
from pipeline.geo import GeoLocator
from pipeline.parser import AuthLogParser
from storage.event_store import Event, EventStore

logger = get_logger(__name__, "main.log")


def run_pipeline(
    data_dir: Path = DATA_DIR,
    db_path: Path = DB_PATH,
    year: int = LOG_YEAR,
    geolocate: bool = True,
) -> dict[str, object]:
    """Exécute le pipeline complet et retourne un petit bilan.

    Les erreurs fatales (dossier introuvable, base inutilisable) remontent
    sous forme d'IngestionError / StorageError, à gérer dans main.py.
    """
    logger.info("Pipeline démarré (data=%s, db=%s, année=%d)", data_dir, db_path, year)

    files = reader.read_all(data_dir)

    parser = AuthLogParser(year)
    events: list[Event] = []
    for name, lines in files:
        events.extend(parser.parse_lines(lines, source=name))
    logger.info("Parsing terminé : %d événements, compteurs=%s", len(events), dict(parser.stats))

    geo_stats: Counter[str] = Counter()
    with EventStore(db_path) as store:
        store.reset_events()  # la base est reconstruite à chaque lancement
        store.add_events(events)
        if geolocate:
            locator = GeoLocator(store)
            geo_stats = locator.resolve_all(store.ips_by_priority())
        else:
            logger.info("Géolocalisation désactivée (--no-geo) : on utilise seulement le cache")
        store.apply_countries()

    summary: dict[str, object] = {
        "files": len(files),
        "lines": sum(len(lines) for _, lines in files),
        "events": len(events),
        "parser": dict(parser.stats),
        "geo": dict(geo_stats),
    }
    logger.info("Pipeline terminé : %s", summary)
    return summary
