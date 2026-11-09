"""Adaptateur de traitement : transforme les lignes de auth.log en Event.

Pourquoi ce module existe : processing/extract_transforme.py (non modifiable)
contient une erreur de syntaxe dans sa regex (une apostrophe parasite) et ne peut
même pas être importé ; de plus sa fonction affiche au lieu de retourner.
On réécrit donc le parsing ici, avec nos propres regex.

Format d'une ligne (syslog classique, sans année) :
    May 24 00:04:36 ns sshd[1350968]: Failed password for root from 1.2.3.4 port 40940 ssh2

Messages sshd gardés :
    Accepted <méthode> for <user> from <ip> port <p>          -> Success
    Failed <méthode> for [invalid user] <user> from <ip> ...  -> Failed
    Invalid user <user> from <ip> port <p>                    -> Invalid
    message repeated N times: [ <un des messages ci-dessus> ] -> N tentatives
"""
import ipaddress
import re
from collections import Counter
from datetime import datetime
from typing import Final, Optional, Sequence

from logger_config import get_logger
from storage.event_store import STATUS_FAILED, STATUS_INVALID, STATUS_SUCCESS, Event

logger = get_logger(__name__, "processing.log")

EMPTY_USER: Final[str] = "(vide)"  # sshd peut logguer un nom d'utilisateur vide

MONTHS: Final[dict[str, int]] = {
    m: i for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}

# Regex compilées une seule fois (comme vu en cours).
SYSLOG_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+(?P<service>[^\s\[:]+)(?:\[(?P<pid>\d+)\])?:\s+(?P<message>.*)$"
)
REPEATED_RE: Final[re.Pattern[str]] = re.compile(
    r"^message repeated (?P<n>\d+) times: \[ (?P<inner>.*)\]$"
)
ACCEPTED_RE: Final[re.Pattern[str]] = re.compile(
    r"^Accepted (?P<method>\S+) for (?P<user>.*?) from (?P<ip>\S+) port (?P<port>\d+)"
)
FAILED_RE: Final[re.Pattern[str]] = re.compile(
    r"^Failed (?P<method>\S+) for (?:invalid user )?(?P<user>.*?) from (?P<ip>\S+) port (?P<port>\d+)"
)
INVALID_RE: Final[re.Pattern[str]] = re.compile(
    r"^Invalid user (?P<user>.*?) from (?P<ip>\S+) port (?P<port>\d+)"
)

# (regex, statut) testés dans cet ordre
RULES: Final[list[tuple[re.Pattern[str], str]]] = [
    (ACCEPTED_RE, STATUS_SUCCESS),
    (FAILED_RE, STATUS_FAILED),
    (INVALID_RE, STATUS_INVALID),
]
AUTH_PREFIXES: Final[tuple[str, ...]] = ("Accepted ", "Failed ", "Invalid user")


class AuthLogParser:
    """Parse les lignes de auth.log et garde des compteurs pour le bilan."""

    def __init__(self, year: int) -> None:
        self.year: int = year
        self.stats: Counter[str] = Counter()

    def _timestamp(self, month: str, day: str, time: str) -> Optional[str]:
        """Construit 'YYYY-MM-DD HH:MM:SS' (l'année vient de la config)."""
        try:
            moment = datetime.strptime(f"{self.year}-{MONTHS[month]:02d}-{int(day):02d} {time}",
                                       "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            return None
        return moment.strftime("%Y-%m-%d %H:%M:%S")

    def parse_line(self, line: str, source: str = "") -> Optional[Event]:
        """Retourne un Event, ou None si la ligne n'est pas un événement d'authentification.

        Les lignes qui ressemblent à un événement mais ne passent pas les regex
        sont loguées en WARNING (et comptées dans stats['unparsable']).
        """
        if not line.strip():
            return None

        head = SYSLOG_RE.match(line)
        if head is None:
            logger.warning("Ligne non parsable (en-tête syslog) dans %s : %r", source, line[:120])
            self.stats["unparsable"] += 1
            return None
        if head.group("service") != "sshd":
            self.stats["ignored_other_service"] += 1
            return None

        message = head.group("message")
        attempts = 1
        repeated = REPEATED_RE.match(message)
        if repeated:  # syslog a résumé N répétitions du même message
            attempts = int(repeated.group("n"))
            message = repeated.group("inner").strip()

        for regex, status in RULES:
            found = regex.match(message)
            if found is None:
                continue
            ip = found.group("ip")
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                logger.warning("IP invalide %r dans %s : %r", ip, source, line[:120])
                self.stats["invalid_ip"] += 1  # l'événement est gardé, le pays sera Unknown
            timestamp = self._timestamp(head.group("month"), head.group("day"), head.group("time"))
            if timestamp is None:
                logger.warning("Date invalide dans %s : %r", source, line[:120])
                self.stats["unparsable"] += 1
                return None
            self.stats[status] += attempts
            return Event(
                timestamp=timestamp,
                ip=ip,
                username=found.group("user") or EMPTY_USER,
                status=status,
                attempts=attempts,
                source=source,
            )

        if message.startswith(AUTH_PREFIXES):
            logger.warning("Message d'authentification non reconnu dans %s : %r", source, line[:120])
            self.stats["unparsable"] += 1
        else:
            self.stats["ignored_other_message"] += 1
        return None

    def parse_lines(self, lines: Sequence[str], source: str = "") -> list[Event]:
        """Parse toutes les lignes d'un fichier."""
        events = [e for e in (self.parse_line(line, source) for line in lines) if e is not None]
        logger.info("%s : %d lignes -> %d événements", source, len(lines), len(events))
        return events
