"""Assemble un cycle de modèle et l'écrit en tuiles .ttwx."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from types import ModuleType

from . import arome, ecmwf, gfs, icon
from .grib import decode_field
from .tiles import MISSING, TILE_DEGREES, encode_tile, tile_name

log = logging.getLogger(__name__)


def run_id(run: datetime) -> str:
    return run.strftime("%Y%m%d%H")


def run_iso(run: datetime) -> str:
    return run.strftime("%Y-%m-%dT%H:%M:%SZ")


MODELS: dict[str, ModuleType] = {arome.MODEL: arome, ecmwf.MODEL: ecmwf, gfs.MODEL: gfs, icon.MODEL: icon}


def produce(
    model: ModuleType,
    run: datetime,
    out_dir: Path,
    *,
    steps: list[int] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    workers: int = 6,
) -> Path:
    """Télécharge le cycle, écrit les tuiles et le manifest. Renvoie le dossier du cycle.

    `bbox` (lat min, lon min, lat max, lon max) limite les tuiles écrites, pour les essais.
    """
    steps = steps or model.forecast_steps()
    tile_degrees = getattr(model, "TILE_DEGREES", TILE_DEGREES)
    variables = model.VARIABLES
    names = [variable.name for variable in variables]
    cube: np.ndarray | None = None
    latitudes = longitudes = None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Fenêtre glissante : au plus 2 × workers échéances téléchargées d'avance,
        # pour borner la mémoire (une échéance AROME pèse environ 40 Mo).
        downloads = {}
        pending = iter(steps)
        for step in list(steps)[: 2 * workers]:
            downloads[step] = pool.submit(model.download_step, run, step)
            next(pending)
        # Décodage dans ce fil, dans l'ordre : ecCodes n'est pas sollicité en parallèle.
        for step_index, step in enumerate(steps):
            files = downloads.pop(step).result()
            following = next(pending, None)
            if following is not None:
                downloads[following] = pool.submit(model.download_step, run, following)
            if hasattr(model, "extract"):
                decoded = list(model.extract(step, files).values())
            else:
                decoded = []
                for name, message in files:
                    field = decode_field(message)
                    # Le nom vient de la requête (index ou fichier), pas du GRIB :
                    # les noms courts ecCodes varient selon le centre et l'échéance.
                    field.short_name = name
                    decoded.append(field)
            for field in decoded:
                if field.short_name not in names:
                    continue
                if cube is None:
                    latitudes, longitudes = field.latitudes, field.longitudes
                    shape = (len(variables), len(steps), len(latitudes), len(longitudes))
                    cube = np.full(shape, MISSING, dtype="<i2")
                elif not (np.array_equal(latitudes, field.latitudes)
                          and np.array_equal(longitudes, field.longitudes)):
                    raise RuntimeError(f"h+{step} : grille différente pour {field.short_name}")
                variable_index = names.index(field.short_name)
                cube[variable_index, step_index] = variables[variable_index].quantize(field.values)
            log.info("h+%d décodée (%d/%d)", step, step_index + 1, len(steps))

    if cube is None:
        raise RuntimeError("aucun champ décodé")

    run_dir = out_dir / model.MODEL / run_id(run)
    run_dir.mkdir(parents=True, exist_ok=True)
    # Arrondi : 0,01 et non 0,00999999999999801 (lat0 + r·dlat dans l'app).
    dlat = round(float(latitudes[1] - latitudes[0]), 9)
    dlon = round(float(longitudes[1] - longitudes[0]), 9)
    jobs = []
    for lat0 in range(-90, 90, tile_degrees):
        if bbox and (lat0 + tile_degrees <= bbox[0] or lat0 >= bbox[2]):
            continue
        upper = lat0 + tile_degrees
        rows = np.where((latitudes >= lat0) & ((latitudes < upper) | (upper == 90)))[0]
        if rows.size == 0:
            continue
        for lon0 in range(-180, 180, tile_degrees):
            if bbox and (lon0 + tile_degrees <= bbox[1] or lon0 >= bbox[3]):
                continue
            columns = np.where((longitudes >= lon0) & (longitudes < lon0 + tile_degrees))[0]
            if columns.size == 0:
                continue
            jobs.append((lat0, lon0, rows, columns))

    def write(job) -> None:
        lat0, lon0, rows, columns = job
        block = cube[:, :, rows[0] : rows[-1] + 1, columns[0] : columns[-1] + 1]
        blob = encode_tile(
            model=model.MODEL,
            run=run_iso(run),
            steps=steps,
            variables=variables,
            lat0=float(latitudes[rows[0]]),
            lon0=float(longitudes[columns[0]]),
            dlat=dlat,
            dlon=dlon,
            data=block,
        )
        (run_dir / f"{tile_name(lat0, lon0)}.ttwx").write_bytes(blob)

    # zlib libère le verrou de Python : la compression profite de plusieurs cœurs.
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        for _ in pool.map(write, jobs):
            pass
    count = len(jobs)

    manifest = {
        "format": 1,
        "model": model.MODEL,
        "run": run_iso(run),
        "steps": steps,
        "tileDegrees": tile_degrees,
        "variables": names,
        "tiles": count,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    log.info("%d tuiles écrites dans %s", count, run_dir)
    return run_dir
