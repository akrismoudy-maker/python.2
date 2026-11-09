"""Adaptateur de géolocalisation : IP -> code pays, avec cache et gestion d'erreurs.

Pourquoi ce module existe : processing/geo_location.py (non modifiable) n'a ni
timeout, ni gestion des erreurs réseau, renvoie None sans dire pourquoi
(HTTP 429, 404...) et construit une URL avec un double slash. Ici on appelle
ipinfo.io nous-mêmes, en loguant chaque cas.

Règles :
- IP privée / loopback / non routable : pays "Private", sans appel réseau ;
- IP déjà connue (cache sqlite) : pas d'appel réseau ;
- erreur réseau, timeout, HTTP != 200 : pays "Unknown", NON mis en cache
  (un prochain lancement réessaiera) ;
- limite atteinte (429), token refusé (401/403) ou trop d'erreurs d'affilée :
  on arrête d'appeler l'API pour le reste du lancement.
"""
import ipaddress
from collections import Counter
from typing import Final, Iterable, Optional

import requests

from config import IPINFO_TIMEOUT, IPINFO_TOKEN, IPINFO_URL
from logger_config import get_logger
from storage.event_store import COUNTRY_PRIVATE, COUNTRY_UNKNOWN, EventStore

logger = get_logger(__name__, "processing.log")

MAX_CONSECUTIVE_ERRORS: Final[int] = 5
FATAL_STATUS: Final[tuple[int, ...]] = (401, 403, 429)


class GeoLocator:
    """Trouve le pays d'une IP via ipinfo.io, avec cache persistant."""

    def __init__(
        self,
        store: EventStore,
        token: Optional[str] = IPINFO_TOKEN,
        timeout: float = IPINFO_TIMEOUT,
    ) -> None:
        self.store: EventStore = store
        self.timeout: float = timeout
        self.cache: dict[str, str] = store.get_cached_countries()
        self.stats: Counter[str] = Counter()
        self._consecutive_errors: int = 0
        self._api_disabled: bool = False
        self._session = requests.Session()
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"

    def _disable_api(self, reason: str) -> None:
        self._api_disabled = True
        logger.error("Appels ipinfo arrêtés pour ce lancement : %s", reason)

    def _register_error(self) -> None:
        self._consecutive_errors += 1
        if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            self._disable_api(f"{MAX_CONSECUTIVE_ERRORS} erreurs d'affilée")

    def _fetch(self, ip: str) -> Optional[str]:
        """Appelle ipinfo. Retourne le code pays, 'Private' (bogon) ou None en cas d'échec."""
        url = f"{IPINFO_URL}/{ip}/json"
        try:
            response = self._session.get(url, timeout=self.timeout)
        except requests.Timeout:
            logger.error("Timeout ipinfo (%.0fs) pour %s", self.timeout, ip)
            self._register_error()
            return None
        except requests.ConnectionError as exc:
            logger.error("Erreur réseau ipinfo pour %s : %s", ip, exc.__class__.__name__)
            self._register_error()
            return None
        except requests.RequestException:
            logger.exception("Erreur requests inattendue pour %s", ip)
            self._register_error()
            return None

        if response.status_code != 200:
            logger.error("ipinfo a répondu HTTP %d pour %s", response.status_code, ip)
            if response.status_code in FATAL_STATUS:
                self._disable_api(f"HTTP {response.status_code}")
            else:
                self._register_error()
            return None

        try:
            data = response.json()
        except ValueError:
            logger.error("Réponse ipinfo non JSON pour %s", ip)
            self._register_error()
            return None

        self._consecutive_errors = 0
        if data.get("bogon"):
            return COUNTRY_PRIVATE
        country = data.get("country")
        if not country:
            logger.warning("ipinfo n'a pas renvoyé de pays pour %s", ip)
            return None
        return str(country)

    def lookup(self, ip: str) -> str:
        """Retourne le pays de `ip` : code ISO (ex 'FR'), 'Private' ou 'Unknown'."""
        if ip in self.cache:
            self.stats["cached"] += 1
            return self.cache[ip]

        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            logger.warning("IP invalide, pas de géolocalisation : %r", ip)
            self.stats["invalid"] += 1
            return COUNTRY_UNKNOWN

        if not address.is_global:  # 127.0.0.1, 10.x, 192.168.x, ::1...
            country: Optional[str] = COUNTRY_PRIVATE
        elif self._api_disabled:
            self.stats["skipped"] += 1
            return COUNTRY_UNKNOWN
        else:
            country = self._fetch(ip)

        if country is None:
            self.stats["failed"] += 1
            return COUNTRY_UNKNOWN

        self.cache[ip] = country
        self.store.cache_country(ip, country)
        self.stats["private" if country == COUNTRY_PRIVATE else "resolved"] += 1
        return country

    def resolve_all(self, ips: Iterable[str]) -> Counter[str]:
        """Géolocalise une liste d'IP (dans l'ordre donné). Retourne les compteurs."""
        for i, ip in enumerate(ips, start=1):
            self.lookup(ip)
            if i % 200 == 0:
                logger.info("%d IP traitées", i)
        logger.info("Géolocalisation terminée : %s", dict(self.stats))
        return self.stats
