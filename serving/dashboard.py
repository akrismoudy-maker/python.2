"""Dashboard matplotlib : 3 graphiques sauvegardés en PNG (+ affichage optionnel).

1. tentatives échouées par pays
2. connexions réussies par utilisateur
3. tentatives avec 'Invalid user' : par nom d'utilisateur et par IP
"""
from pathlib import Path
from typing import Final, Optional

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from config import DB_PATH, OUTPUT_DIR
from logger_config import get_logger
from serving import queries
from storage.event_store import COUNTRY_PRIVATE, COUNTRY_UNKNOWN, EventStore, StorageError

logger = get_logger(__name__, "serving.log")

BAR_COLOR: Final[str] = "#2a78d6"
MUTED_COLOR: Final[str] = "#9a9a95"   # pays inconnus / privés
INK: Final[str] = "#0b0b0b"
INK_SECONDARY: Final[str] = "#52514e"
GRID: Final[str] = "#e4e3df"
SURFACE: Final[str] = "#fcfcfb"
TOP_N: Final[int] = 15


def _barh(ax: Axes, data: list[tuple[str, int]], title: str, xlabel: str, ylabel: str,
          muted: tuple[str, ...] = ()) -> None:
    """Barres horizontales triées (la plus grande en haut) avec la valeur au bout."""
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=INK)
    ax.set_xlabel(xlabel, color=INK_SECONDARY)
    ax.set_ylabel(ylabel, color=INK_SECONDARY)
    ax.tick_params(colors=INK_SECONDARY, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)

    if not data:
        ax.text(0.5, 0.5, "Aucune donnée", ha="center", va="center",
                transform=ax.transAxes, color=INK_SECONDARY)
        ax.set_xticks([])
        ax.set_yticks([])
        return

    labels = [label for label, _ in data]
    values = [value for _, value in data]
    colors = [MUTED_COLOR if label in muted else BAR_COLOR for label in labels]
    bars = ax.barh(labels, values, color=colors, height=0.65)
    ax.set_ylim(max(len(data), 6) - 0.5, -0.5)  # évite une barre géante quand il y a peu de données
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))  # pas de 0.2 pour des comptages
    ax.set_axisbelow(True)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.bar_label(bars, labels=[f"{v:,}".replace(",", " ") for v in values],
                 padding=3, fontsize=9, color=INK)
    ax.margins(x=0.12)


def _new_figure(ncols: int = 1, width: float = 9) -> tuple[Figure, list[Axes]]:
    fig, axes = plt.subplots(1, ncols, figsize=(width, 6), facecolor=SURFACE, squeeze=False)
    return fig, list(axes[0])


def _draw_failed_by_country(ax: Axes, store: EventStore) -> None:
    _barh(ax, queries.failed_by_country(store, TOP_N),
          f"1. Tentatives échouées par pays (top {TOP_N})",
          "Nombre de tentatives échouées", "Pays (code ISO)",
          muted=(COUNTRY_UNKNOWN, COUNTRY_PRIVATE))


def _draw_success_by_user(ax: Axes, store: EventStore) -> None:
    _barh(ax, queries.success_by_user(store, TOP_N), "2. Connexions réussies par utilisateur",
          "Nombre de connexions réussies", "Utilisateur")


def _draw_invalid_by_user(ax: Axes, store: EventStore) -> None:
    _barh(ax, queries.invalid_by_user(store, TOP_N),
          f"3a. 'Invalid user' : top {TOP_N} par nom d'utilisateur",
          "Nombre de tentatives", "Nom d'utilisateur invalide")


def _draw_invalid_by_ip(ax: Axes, store: EventStore) -> None:
    _barh(ax, queries.invalid_by_ip(store, TOP_N),
          f"3b. 'Invalid user' : top {TOP_N} par adresse IP",
          "Nombre de tentatives", "Adresse IP")


GEO_NOTE: Final[str] = "Gris : pays inconnu (IP non géolocalisée) ou IP privée."


def chart_failed_by_country(store: EventStore) -> Figure:
    fig, (ax,) = _new_figure()
    _draw_failed_by_country(ax, store)
    fig.text(0.01, 0.01, GEO_NOTE, fontsize=8, color=INK_SECONDARY)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def chart_success_by_user(store: EventStore) -> Figure:
    fig, (ax,) = _new_figure(width=8)
    _draw_success_by_user(ax, store)
    fig.tight_layout()
    return fig


def chart_invalid_users(store: EventStore) -> Figure:
    fig, (ax_user, ax_ip) = _new_figure(ncols=2, width=14)
    _draw_invalid_by_user(ax_user, store)
    _draw_invalid_by_ip(ax_ip, store)
    fig.tight_layout()
    return fig


def chart_combined(store: EventStore) -> Figure:
    """Les 3 graphiques dans une seule fenêtre (le 3 a deux panneaux : 3a nom, 3b IP)."""
    fig, axes = plt.subplots(2, 2, figsize=(16, 11), facecolor=SURFACE)
    _draw_failed_by_country(axes[0][0], store)
    _draw_success_by_user(axes[0][1], store)
    _draw_invalid_by_user(axes[1][0], store)
    _draw_invalid_by_ip(axes[1][1], store)
    fig.suptitle("Analyse des logs SSH (auth.log)", fontsize=15, fontweight="bold", color=INK)
    fig.text(0.01, 0.005, GEO_NOTE, fontsize=8, color=INK_SECONDARY)
    fig.tight_layout(rect=(0, 0.02, 1, 0.96))
    return fig


def _save(fig: Figure, path: Path) -> bool:
    try:
        fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    except OSError:
        logger.exception("Écriture du graphique impossible : %s", path)
        return False
    logger.info("Graphique écrit : %s", path)
    return True


def build_dashboard(
    db_path: Path = DB_PATH,
    output_dir: Path = OUTPUT_DIR,
    show: bool = True,
) -> list[Path]:
    """Génère les graphiques en PNG dans output_dir (3 individuels + dashboard.png) et retourne les fichiers écrits.

    show=True ouvre UNE fenêtre matplotlib (dashboard combiné) (ignoré sans écran, backend Agg).
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Dossier de sortie inaccessible : %s", output_dir)
        return []

    builders = {
        "1_failed_by_country.png": chart_failed_by_country,
        "2_success_by_user.png": chart_success_by_user,
        "3_invalid_users.png": chart_invalid_users,
        "dashboard.png": chart_combined,  # les 3 graphiques ensemble, seule figure affichée
    }
    written: list[Path] = []
    combined: Optional[Figure] = None
    figures: list[Figure] = []
    try:
        with EventStore(db_path) as store:
            for filename, build in builders.items():
                try:
                    fig = build(store)
                except StorageError:
                    logger.error("Graphique %s ignoré : requête impossible", filename)
                    continue
                except Exception:  # erreur de dessin matplotlib : on garde les autres graphiques
                    logger.exception("Erreur de dessin pour %s", filename)
                    continue
                if filename == "dashboard.png":
                    combined = fig
                else:
                    figures.append(fig)
                if _save(fig, output_dir / filename):
                    written.append(output_dir / filename)
    except StorageError:
        logger.error("Dashboard impossible : base inaccessible (%s)", db_path)

    # Une seule fenêtre : on ferme les graphiques individuels (déjà sauvegardés en PNG)
    for fig in figures:
        plt.close(fig)
    if show and combined is not None and matplotlib.get_backend().lower() != "agg":
        plt.show()
    if combined is not None:
        plt.close(combined)
    logger.info("Dashboard terminé : %d/%d fichiers", len(written), len(builders))
    return written
