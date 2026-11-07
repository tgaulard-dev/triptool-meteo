"""AROME 0,01° (Météo-France), paquets publiés en données ouvertes.

Source : meteo.data.gouv.fr, « Paquets Arome - Résolution 0,01° » et
« 0,025° », Licence Ouverte 2.0. Un cycle toutes les 3 h, jusqu'à H+51.

L'app interroge aujourd'hui le service WCS AROME 0,01° de Météo-France (avec
clé d'API et quota d'environ 50 requêtes par minute). Les paquets 0,01°
horaires contiennent le vent, la température, les composantes de la rafale,
la pluie, la neige, le grésil et la CAPE, mais pas la nébulosité totale :
elle vient du paquet 0,025° (groupes de 6 h), repris au point le plus proche.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

import numpy as np

from .grib import Field, decode_field, split_messages
from .http import get, not_found
from .tiles import Variable

log = logging.getLogger(__name__)

MODEL = "arome"
TILE_DEGREES = 1  # 100 × 100 points à 0,01°
BASE_URL = "https://meteofrance-pnt.s3.rbx.io.cloud.ovh.net/pnt"
LAST_STEP = 51

VARIABLES = [
    Variable("10u", "m s-1", 0.01, 0.0),
    Variable("10v", "m s-1", 0.01, 0.0),
    Variable("10fg", "m s-1", 0.01, 0.0),
    Variable("2t", "K", 0.01, 273.15),
    Variable("tp", "kg m-2", 0.1, 0.0),
    Variable("tcc", "%", 0.01, 0.0),
    Variable("cape", "J kg-1", 1.0, 0.0),
]

# Identité GRIB2 (discipline, catégorie, numéro).
U10, V10, T2 = (0, 2, 2), (0, 2, 3), (0, 0, 0)
GUST_U, GUST_V = (0, 2, 23), (0, 2, 24)
RAIN, SNOW, GRAUPEL = (0, 1, 65), (0, 1, 66), (0, 1, 75)
CAPE = (0, 7, 6)
CLOUD = (0, 6, 1)

# Groupes d'échéances des paquets 0,025°.
GROUPS = [(0, 6), (7, 12), (13, 18), (19, 24), (25, 30), (31, 36), (37, 42), (43, 48), (49, 51)]

_group_lock = threading.Lock()
_group_cache: dict[tuple[str, int], bytes] = {}


def forecast_steps() -> list[int]:
    return list(range(0, LAST_STEP + 1))


def _run_text(run: datetime) -> str:
    return run.strftime("%Y-%m-%dT%H:%M:%SZ")


def hourly_url(run: datetime, package: str, step: int) -> str:
    r = _run_text(run)
    return f"{BASE_URL}/{r}/arome/001/{package}/arome__001__{package}__{step:02d}H__{r}.grib2"


def group_url(run: datetime, package: str, first: int, last: int) -> str:
    r = _run_text(run)
    span = f"{first:02d}H{last:02d}H"
    return f"{BASE_URL}/{r}/arome/0025/{package}/arome__0025__{package}__{span}__{r}.grib2"


def latest_complete_run(now: datetime | None = None) -> datetime:
    """Cycle le plus récent (toutes les 3 h) dont la dernière échéance est publiée."""
    now = now or datetime.now(timezone.utc)
    candidate = now.replace(minute=0, second=0, microsecond=0)
    candidate = candidate.replace(hour=candidate.hour - candidate.hour % 3)
    last_group = GROUPS[-1]
    for _ in range(9):
        try:
            for package in ("SP1", "SP2"):
                get(hourly_url(candidate, package, LAST_STEP), method="HEAD")
            get(group_url(candidate, "SP1", *last_group), method="HEAD")
            return candidate
        except Exception as error:  # noqa: BLE001
            if not not_found(error):
                raise
        candidate -= timedelta(hours=3)
    raise RuntimeError("aucun cycle AROME complet trouvé")


def _group_file(run: datetime, step: int) -> bytes:
    first, last = next(group for group in GROUPS if group[0] <= step <= group[1])
    key = (_run_text(run), first)
    with _group_lock:
        if key in _group_cache:
            return _group_cache[key]
    data = get(group_url(run, "SP1", first, last), timeout=300)
    with _group_lock:
        _group_cache[key] = data
        # Garder seulement les groupes du cycle en cours.
        for old in [k for k in _group_cache if k[0] != key[0]]:
            del _group_cache[old]
    return data


def download_step(run: datetime, step: int) -> list[tuple[str, bytes]]:
    """Fichiers bruts d'une échéance ; le tri des champs se fait dans `extract`."""
    files = [
        ("SP1", get(hourly_url(run, "SP1", step), timeout=300)),
        ("SP2", get(hourly_url(run, "SP2", step), timeout=300)),
        ("NEBUL", _group_file(run, step)),
    ]
    return files


def _nearest(source: Field, latitudes: np.ndarray, longitudes: np.ndarray) -> np.ndarray:
    """Valeurs de `source` au point le plus proche de chaque point cible."""
    dlat = source.latitudes[1] - source.latitudes[0]
    dlon = source.longitudes[1] - source.longitudes[0]
    rows = np.clip(np.rint((latitudes - source.latitudes[0]) / dlat).astype(int), 0, len(source.latitudes) - 1)
    columns = np.clip(np.rint((longitudes - source.longitudes[0]) / dlon).astype(int), 0, len(source.longitudes) - 1)
    return source.values[np.ix_(rows, columns)]


def extract(step: int, files: list[tuple[str, bytes]]) -> dict[str, Field]:
    """Champs stockés pour une échéance, tous sur la grille 0,01°."""
    found: dict[tuple[int, int, int], Field] = {}
    cloud: Field | None = None
    for package, data in files:
        for message in split_messages(data):
            field = decode_field(message)
            if package == "NEBUL":
                if field.parameter == CLOUD and field.end_step == step:
                    cloud = field
            else:
                found.setdefault(field.parameter, field)

    if U10 not in found or V10 not in found:
        raise RuntimeError(f"h+{step} : vent AROME absent")
    reference = found[U10]

    def named(name: str, values: np.ndarray) -> Field:
        return Field(name, reference.latitudes, reference.longitudes, values)

    fields = {"10u": named("10u", found[U10].values), "10v": named("10v", found[V10].values)}
    if T2 in found:
        fields["2t"] = named("2t", found[T2].values)
    if GUST_U in found and GUST_V in found:
        # Composantes de la rafale maximale : sa vitesse est la norme du vecteur.
        fields["10fg"] = named("10fg", np.hypot(found[GUST_U].values, found[GUST_V].values))
    if RAIN in found:
        total = found[RAIN].values.copy()
        for part in (SNOW, GRAUPEL):
            if part in found:
                total = total + found[part].values
        fields["tp"] = named("tp", total)
    if CAPE in found:
        fields["cape"] = named("cape", found[CAPE].values)
    if cloud is not None:
        fields["tcc"] = named("tcc", _nearest(cloud, reference.latitudes, reference.longitudes))
    else:
        log.warning("h+%d : nébulosité absente", step)
    return fields
