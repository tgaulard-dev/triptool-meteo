"""Téléchargement de GFS 0,25° depuis l'archive ouverte de NOAA sur AWS
(noaa-gfs-bdp-pds), mêmes fichiers que NOMADS sans sa limite de requêtes.

Mêmes champs et mêmes échéances que le fournisseur GFS de l'app
(CapNav/NOAAGFSWeatherProvider.swift) : seuls les messages utiles sont
téléchargés, grâce à l'index .idx publié à côté de chaque fichier.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .http import get, not_found
from .tiles import Variable

log = logging.getLogger(__name__)

MODEL = "gfs"
BASE_URL = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
REQUIRED = {"10u", "10v"}

# Unités d'origine GFS : précipitations en kg m-2 (= mm), nébulosité en %.
VARIABLES = [
    Variable("10u", "m s-1", 0.01, 0.0),
    Variable("10v", "m s-1", 0.01, 0.0),
    Variable("10fg", "m s-1", 0.01, 0.0),
    Variable("2t", "K", 0.01, 273.15),
    Variable("tp", "kg m-2", 0.1, 0.0),
    Variable("tcc", "%", 0.01, 0.0),
    Variable("cape", "J kg-1", 1.0, 0.0),
]


def forecast_steps() -> list[int]:
    """Horaire jusqu'à H+120, puis toutes les 3 h jusqu'à H+384, comme l'app."""
    return list(range(0, 121)) + list(range(123, 385, 3))


def file_url(run: datetime, step: int, suffix: str = "") -> str:
    day = run.strftime("%Y%m%d")
    cycle = run.strftime("%H")
    return f"{BASE_URL}/gfs.{day}/{cycle}/atmos/gfs.t{cycle}z.pgrb2.0p25.f{step:03d}{suffix}"


def variable_for(record: list[str]) -> str | None:
    """Variable stockée pour une ligne d'index (nom:niveau:échéance), sinon None."""
    name, level, period = record[3], record[4], record[5]
    if name == "UGRD" and level == "10 m above ground":
        return "10u"
    if name == "VGRD" and level == "10 m above ground":
        return "10v"
    if name == "GUST" and level == "surface":
        return "10fg"
    if name == "TMP" and level == "2 m above ground":
        return "2t"
    # Deux APCP par fichier : la tranche courante et le cumul depuis le début du
    # cycle (« 0-N hour acc », « 0-5 day acc »). Seul le second est gardé.
    if name == "APCP" and level == "surface" and period.startswith("0-"):
        return "tp"
    # Nébulosité instantanée (« N hour fcst » ou « anl »), pas la moyenne.
    if name == "TCDC" and level == "entire atmosphere" and "ave" not in period:
        return "tcc"
    if name == "CAPE" and level == "surface":
        return "cape"
    return None


def index(run: datetime, step: int) -> list[tuple[str, int, int | None]]:
    """(variable, début, fin incluse ou None pour la fin du fichier) des messages utiles."""
    lines = [line.split(":") for line in get(file_url(run, step, ".idx")).decode().splitlines() if line]
    wanted = []
    for position, record in enumerate(lines):
        variable = variable_for(record)
        if variable is None or any(variable == item[0] for item in wanted):
            continue
        start = int(record[1])
        end = int(lines[position + 1][1]) - 1 if position + 1 < len(lines) else None
        wanted.append((variable, start, end))
    return wanted


def latest_complete_run(now: datetime | None = None) -> datetime:
    """Cycle 00/06/12/18 UTC le plus récent dont la dernière échéance est publiée."""
    now = now or datetime.now(timezone.utc)
    last_step = forecast_steps()[-1]
    candidate = now.replace(minute=0, second=0, microsecond=0)
    candidate = candidate.replace(hour=candidate.hour - candidate.hour % 6)
    for _ in range(6):
        try:
            get(file_url(candidate, last_step, ".idx"), method="HEAD")
            return candidate
        except Exception as error:  # noqa: BLE001
            # S3 répond 403 (et non 404) pour un fichier absent d'un bucket public.
            if not (not_found(error) or getattr(error, "code", None) == 403):
                raise
        candidate -= timedelta(hours=6)
    raise RuntimeError("aucun cycle GFS complet trouvé")


def canonical_name(name: str) -> str:
    return name


def download_step(run: datetime, step: int) -> list[tuple[str, bytes]]:
    """Champs d'une échéance : (nom de variable, message GRIB)."""
    records = index(run, step)
    found = {variable for variable, _, _ in records}
    if not REQUIRED <= found:
        raise RuntimeError(f"h+{step} : vent absent de l'index")
    wanted = {variable.name for variable in VARIABLES}
    if found != wanted:
        # Normal à H+0 : pas de cumul de pluie.
        log.info("h+%d : paramètres absents %s", step, sorted(wanted - found))
    url = file_url(run, step)
    fields = []
    for variable, start, end in records:
        if end is None:
            raise RuntimeError(f"h+{step} : {variable} en fin de fichier, longueur inconnue")
        chunk = get(url, byte_range=(start, end))
        if len(chunk) != end - start + 1 or not chunk.startswith(b"GRIB"):
            raise RuntimeError(f"h+{step} : réponse partielle pour {variable}")
        fields.append((variable, chunk))
    return fields
