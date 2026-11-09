"""Point d'entrée : lit les logs SSH, stocke les événements, génère le dashboard.

    uv run main.py              # pipeline complet + affichage des graphiques
    uv run main.py --no-show    # sans ouvrir de fenêtre (PNG seulement)
    uv run main.py --no-geo     # sans appeler ipinfo (utilise seulement le cache)
"""
import argparse
import sys

from logger_config import get_logger
from pipeline.orchestrator import run_pipeline
from pipeline.reader import IngestionError
from serving.dashboard import build_dashboard
from storage.event_store import StorageError

logger = get_logger(__name__, "main.log", console=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline d'analyse des logs SSH (auth.log)")
    parser.add_argument("--no-geo", action="store_true", help="ne pas appeler ipinfo.io")
    parser.add_argument("--no-show", action="store_true", help="ne pas afficher les graphiques")
    return parser.parse_args()


def main() -> int:
    """Retourne 0 si tout s'est bien passé, 1 sinon."""
    args = parse_args()
    try:
        summary = run_pipeline(geolocate=not args.no_geo)
        logger.info("%d lignes lues, %d événements stockés", summary["lines"], summary["events"])
        files = build_dashboard(show=not args.no_show)
    except (IngestionError, StorageError) as exc:
        logger.error("Arrêt du pipeline : %s", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrompu par l'utilisateur")
        return 1
    except Exception:
        logger.exception("Erreur inattendue")
        return 1

    if not files:
        logger.error("Aucun graphique généré, voir logs/serving.log")
        return 1
    logger.info("Terminé : %d fichiers dans output/", len(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
