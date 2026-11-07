"""Téléchargement des prévisions ouvertes ECMWF IFS 0,25° (data.ecmwf.int).

Mêmes champs et mêmes échéances que le fournisseur ECMWF de l'app
(CapNav/ECMWFWeatherProvider.swift) : seuls les messages utiles sont
téléchargés, grâce à l'index publié à côté de chaque fichier.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from .http import get, not_found
from .tiles import Variable

log = logging.getLogger(__name__)

MODEL = "ecmwf"
BASE_URL = "https://data.ecmwf.int/forecasts"
REQUIRED = {"10u", "10v"}

VARIABLES = [
    Variable("10u", "m s-1", 0.01, 0.0),
    Variable("10v", "m s-1", 0.01, 0.0),
    Variable("10fg", "m s-1", 0.01, 0.0),
    Variable("2t", "K", 0.01, 273.15),
    Variable("tp", "m", 0.0001, 0.0),
    Variable("tcc", "1", 0.0001, 0.0),
]


# Noms de paramètre publiés selon l'échéance pour la même grandeur. De H+93 à
# H+144, la rafale s'appelle « 10fg3 » (max sur 3 h) au lieu de « 10fg ».
ALIASES = {"10fg3": "10fg", "10fg6": "10fg"}


def canonical_name(name: str) -> str:
    return ALIASES.get(name, name)


def forecast_steps() -> list[int]:
    """0 à 144 h toutes les 3 h, puis toutes les 6 h jusqu'à 240 h."""
    return list(range(0, 145, 3)) + list(range(150, 241, 6))


def file_url(run: datetime, step: int, suffix: str) -> str:
    day = run.strftime("%Y%m%d")
    cycle = run.strftime("%H")
    name = f"{day}{cycle}0000-{step}h-oper-fc.{suffix}"
    return f"{BASE_URL}/{day}/{cycle}z/ifs/0p25/oper/{name}"


def index(run: datetime, step: int) -> list[dict]:
    text = get(file_url(run, step, "index")).decode("utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def latest_complete_run(now: datetime | None = None) -> datetime:
    """Cycle 00 ou 12 UTC le plus récent dont la dernière échéance est publiée."""
    now = now or datetime.now(timezone.utc)
    last_step = forecast_steps()[-1]
    candidate = now.replace(minute=0, second=0, microsecond=0)
    candidate = candidate.replace(hour=0 if candidate.hour < 12 else 12)
    for _ in range(5):
        try:
            index(candidate, last_step)
            return candidate
        except Exception as error:  # noqa: BLE001
            if not not_found(error):
                raise
        candidate -= timedelta(hours=12)
    raise RuntimeError("aucun cycle ECMWF complet trouvé")


def download_step(run: datetime, step: int) -> list[tuple[str, bytes]]:
    """Champs d'une échéance : (nom de variable, message GRIB)."""
    wanted = {variable.name for variable in VARIABLES}
    records = [
        record for record in index(run, step)
        if canonical_name(record.get("param", "")) in wanted
    ]
    found = {canonical_name(record["param"]) for record in records}
    # Comme dans l'app : le vent est indispensable, les autres champs non
    # (la rafale ou le cumul peuvent manquer à H+0). Ils restent alors absents.
    if not REQUIRED <= found:
        raise RuntimeError(f"h+{step} : vent absent de l'index")
    if found != wanted:
        log.warning("h+%d : paramètres absents %s", step, sorted(wanted - found))
    url = file_url(run, step, "grib2")
    fields = []
    for record in sorted(records, key=lambda r: r["_offset"]):
        start = record["_offset"]
        chunk = get(url, byte_range=(start, start + record["_length"] - 1))
        if len(chunk) != record["_length"] or not chunk.startswith(b"GRIB"):
            raise RuntimeError(f"h+{step} : réponse partielle pour {record['param']}")
        fields.append((canonical_name(record["param"]), chunk))
    return fields
