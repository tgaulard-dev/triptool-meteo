"""Téléchargement d'ICON-EU sur l'Open Data du DWD (opendata.dwd.de).

Mêmes champs et mêmes échéances que le fournisseur ICON de l'app
(CapNav/DWDICONWeatherProvider.swift). Le DWD publie un fichier GRIB2
compressé en BZip2 par paramètre et par échéance, sur toute l'Europe.
"""

from __future__ import annotations

import bz2
import logging
from datetime import datetime, timedelta, timezone

from .http import get, not_found
from .tiles import Variable

log = logging.getLogger(__name__)

MODEL = "icon"
BASE_URL = "https://opendata.dwd.de/weather/nwp/icon-eu/grib"

# (dossier DWD, jeton du nom de fichier, variable stockée)
# Unités d'origine ICON : précipitations en kg m-2 (= mm), nébulosité en %.
PARAMETERS = [
    ("u_10m", "U_10M", Variable("10u", "m s-1", 0.01, 0.0)),
    ("v_10m", "V_10M", Variable("10v", "m s-1", 0.01, 0.0)),
    ("vmax_10m", "VMAX_10M", Variable("10fg", "m s-1", 0.01, 0.0)),
    ("t_2m", "T_2M", Variable("2t", "K", 0.01, 273.15)),
    ("tot_prec", "TOT_PREC", Variable("tp", "kg m-2", 0.1, 0.0)),
    ("clct", "CLCT", Variable("tcc", "%", 0.01, 0.0)),
]
VARIABLES = [variable for _, _, variable in PARAMETERS]
REQUIRED = {"10u", "10v"}


def forecast_steps() -> list[int]:
    """Toutes les 3 h jusqu'à H+120, comme l'app."""
    return list(range(0, 121, 3))


def file_url(run: datetime, step: int, folder: str, token: str) -> str:
    stamp = run.strftime("%Y%m%d%H")
    cycle = run.strftime("%H")
    name = f"icon-eu_europe_regular-lat-lon_single-level_{stamp}_{step:03d}_{token}.grib2.bz2"
    return f"{BASE_URL}/{cycle}/{folder}/{name}"


def latest_complete_run(now: datetime | None = None) -> datetime:
    """Cycle 00/06/12/18 UTC le plus récent dont la dernière échéance est publiée
    pour tous les paramètres."""
    now = now or datetime.now(timezone.utc)
    last_step = forecast_steps()[-1]
    candidate = now.replace(minute=0, second=0, microsecond=0)
    candidate = candidate.replace(hour=candidate.hour - candidate.hour % 6)
    for _ in range(5):
        try:
            for folder, token, _ in PARAMETERS:
                get(file_url(candidate, last_step, folder, token), method="HEAD")
            return candidate
        except Exception as error:  # noqa: BLE001
            if not not_found(error):
                raise
        candidate -= timedelta(hours=6)
    raise RuntimeError("aucun cycle ICON-EU complet trouvé")


def canonical_name(name: str) -> str:
    return name


def download_step(run: datetime, step: int) -> list[tuple[str, bytes]]:
    """Champs d'une échéance : (nom de variable, message GRIB décompressé)."""
    fields = []
    for folder, token, variable in PARAMETERS:
        try:
            data = bz2.decompress(get(file_url(run, step, folder, token)))
        except Exception as error:  # noqa: BLE001
            if variable.name in REQUIRED or not not_found(error):
                raise
            log.warning("h+%d : %s absent", step, token)
            continue
        if not data.startswith(b"GRIB"):
            raise RuntimeError(f"h+{step} : {token} n'est pas un GRIB")
        fields.append((variable.name, data))
    return fields
