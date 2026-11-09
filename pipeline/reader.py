"""Adaptateur d'ingestion : lit TOUS les fichiers auth.log* de data/ (y compris .gz).

Pourquoi ce module existe : ingestion/raw.py (non modifiable) ne lit qu'un seul
fichier à cause du `return` dans la boucle, plante si le premier fichier n'est
pas un .gz et affiche les erreurs avec print(). Voir "Limites connues" du README.
Ici on relit les fichiers proprement, avec un log pour chaque erreur possible.
"""
import gzip
import re
import zlib
from pathlib import Path
from typing import Final, Iterator

from logger_config import get_logger

logger = get_logger(__name__, "ingestion.log")

# auth.log, auth.log.1, auth.log.2.gz ...
FILE_RE: Final[re.Pattern[str]] = re.compile(r"^auth\.log(?:\.(?P<n>\d+))?(?:\.gz)?$")


class IngestionError(Exception):
    """Le dossier de données est inutilisable (introuvable, illisible...)."""


def list_log_files(data_dir: Path) -> list[Path]:
    """Liste les fichiers auth.log*, du plus ancien au plus récent.

    logrotate numérote les fichiers à l'envers : auth.log.4.gz est le plus ancien,
    auth.log (sans numéro) le plus récent.
    """
    try:
        entries = [p for p in data_dir.iterdir() if p.is_file()]
    except FileNotFoundError as exc:
        logger.error("Dossier de données introuvable : %s", data_dir)
        raise IngestionError(f"dossier introuvable : {data_dir}") from exc
    except NotADirectoryError as exc:
        logger.error("Ce chemin n'est pas un dossier : %s", data_dir)
        raise IngestionError(f"pas un dossier : {data_dir}") from exc
    except PermissionError as exc:
        logger.error("Permission refusée sur le dossier : %s", data_dir)
        raise IngestionError(f"permission refusée : {data_dir}") from exc
    except OSError as exc:
        logger.exception("Impossible de lister le dossier %s", data_dir)
        raise IngestionError(f"lecture impossible : {data_dir}") from exc

    files: list[tuple[int, Path]] = []
    for path in entries:
        match = FILE_RE.match(path.name)
        if match is None:
            logger.warning("Fichier ignoré (nom inattendu) : %s", path.name)
            continue
        number = int(match.group("n")) if match.group("n") else 0
        files.append((number, path))

    files.sort(key=lambda item: (-item[0] if item[0] else 1, item[1].name))
    if not files:
        logger.error("Aucun fichier auth.log* dans %s", data_dir)
        raise IngestionError(f"aucun fichier auth.log* dans {data_dir}")
    return [path for _, path in files]


def _decode(raw: bytes, path: Path, line_no: int) -> str:
    """Décode une ligne en UTF-8 ; en cas d'octets invalides, on les remplace."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        logger.warning("Encodage invalide dans %s ligne %d : %s", path.name, line_no, exc)
        return raw.decode("utf-8", errors="replace")


def _iter_lines(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        for line_no, raw in enumerate(handle, start=1):
            yield _decode(raw, path, line_no).rstrip("\r\n")


def read_file(path: Path) -> list[str]:
    """Lit un fichier (texte ou .gz) et retourne ses lignes.

    En cas d'erreur, l'erreur est loguée et on retourne les lignes déjà lues
    (liste vide si le fichier est illisible), pour que les autres fichiers
    soient quand même traités.
    """
    lines: list[str] = []
    try:
        for line in _iter_lines(path):
            lines.append(line)
    except FileNotFoundError:
        logger.error("Fichier introuvable : %s", path)
    except PermissionError:
        logger.error("Permission refusée : %s", path)
    except gzip.BadGzipFile:
        logger.error("Fichier gzip corrompu (en-tête invalide) : %s", path)
    except (EOFError, zlib.error):
        logger.error("Fichier gzip tronqué ou corrompu : %s (%d lignes lues)", path, len(lines))
    except OSError:
        logger.exception("Erreur de lecture : %s", path)
    else:
        logger.info("%s : %d lignes lues", path.name, len(lines))
    return lines


def read_all(data_dir: Path) -> list[tuple[str, list[str]]]:
    """Lit tous les fichiers du dossier. Retourne [(nom_du_fichier, lignes), ...]."""
    result: list[tuple[str, list[str]]] = []
    for path in list_log_files(data_dir):
        result.append((path.name, read_file(path)))
    total = sum(len(lines) for _, lines in result)
    logger.info("%d fichiers lus, %d lignes au total", len(result), total)
    return result
